"""Scheduling rules.

Two kinds live here:

  * SYSTEM rules (`locked: True`) — the guarantees the product makes about
    every roster. They cannot be edited, disabled or deleted through this
    API. The block is enforced server-side; hiding the controls in the UI is
    a convenience, not the protection.

  * CUSTOM rules — free text a shop owner writes, compiled into a structured
    constraint the solver can enforce. The common shapes are parsed
    deterministically, which works with no API key and gives the same answer
    every time; the LLM is a fallback for wording the parser cannot read.

A rule the solver cannot read does nothing at all, so an uncompiled rule is
reported rather than left looking active.
"""
import uuid
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status

from app.models import AIRuleIn
from app.services import llm
from app.services.rule_parser import parse_rule
from app.tenancy import ShopScope, CurrentScope

router = APIRouter(prefix="/ai-rules", tags=["rules"])

_LOCKED_MESSAGE = (
    "This is a system rule that guarantees safe, legal rosters. "
    "It cannot be changed or removed."
)


async def _get_or_404(scope: ShopScope, rule_id: str):
    rule = await scope.ai_rules.find_one({"rule_id": rule_id})
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return rule


def _reject_if_locked(rule) -> None:
    if rule.get("locked"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, _LOCKED_MESSAGE)


@router.get("")
async def list_rules(scope: ShopScope = CurrentScope):
    rules = await scope.ai_rules.find()
    # Locked rules first, so the guarantees are what an owner sees first.
    return sorted(rules, key=lambda r: (not r.get("locked"), r.get("title", "")))


async def _compile_locally(payload: AIRuleIn, scope: ShopScope) -> Dict[str, Any]:
    """Try to turn the wording into a constraint without the language model.

    A rule the solver cannot read does nothing. Previously that could only
    be avoided by configuring an API key, so a shop without one wrote rules
    that saved, displayed as enabled and were silently ignored. The common
    shapes are recognised here instead, and anything unrecognised is marked
    so the manager can see it is not in force.
    """
    employees = await scope.employees.find(limit=1000)
    compiled = parse_rule(payload.title, payload.description, employees)
    if compiled:
        # Auto-approved: a deterministic parse is auditable and reversible,
        # unlike a model's guess, so there is nothing to review.
        return {"compiled": compiled, "approved": True, "compiled_by": "parser"}
    return {"compiled": None, "approved": False, "compiled_by": None}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rule(payload: AIRuleIn, scope: ShopScope = CurrentScope):
    # Rules created through the API are never locked — only the seeded
    # system defaults are.
    return await scope.ai_rules.insert({
        "rule_id": f"rule_{uuid.uuid4().hex[:10]}",
        "locked": False,
        **payload.model_dump(),
        **await _compile_locally(payload, scope),
    })


@router.put("/{rule_id}")
async def update_rule(rule_id: str, payload: AIRuleIn, scope: ShopScope = CurrentScope):
    _reject_if_locked(await _get_or_404(scope, rule_id))
    await scope.ai_rules.update_one({"rule_id": rule_id}, {
        **payload.model_dump(),
        # Re-read the wording: an edited rule must not keep enforcing what
        # the previous wording meant.
        **await _compile_locally(payload, scope),
    })
    return await scope.ai_rules.find_one({"rule_id": rule_id})


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str, scope: ShopScope = CurrentScope):
    _reject_if_locked(await _get_or_404(scope, rule_id))
    await scope.ai_rules.delete_one({"rule_id": rule_id})
    return {"ok": True}


@router.post("/{rule_id}/compile")
async def compile_rule(rule_id: str, scope: ShopScope = CurrentScope):
    """Turn a free-text rule into a structured constraint via the LLM.

    Compiling does not activate the rule — the result must be reviewed and
    approved first. That keeps a model misreading a rule from silently
    changing how people are scheduled.
    """
    rule = await _get_or_404(scope, rule_id)
    _reject_if_locked(rule)

    employees = await scope.employees.find()
    try:
        compiled = await llm.compile_rule(rule["title"], rule["description"], employees)
    except llm.LLMUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    except ValueError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not interpret the rule: {exc}")
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Rule compilation failed: {exc}")

    # Re-compiling revokes prior approval: the constraint has changed, so the
    # earlier sign-off no longer applies to it.
    await scope.ai_rules.update_one(
        {"rule_id": rule_id}, {"compiled": compiled, "approved": False}
    )
    return {"compiled": compiled, "approved": False}


@router.post("/{rule_id}/approve-compiled")
async def approve_compiled_rule(rule_id: str, scope: ShopScope = CurrentScope):
    rule = await _get_or_404(scope, rule_id)
    if not rule.get("compiled"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This rule has not been compiled yet."
        )
    await scope.ai_rules.update_one({"rule_id": rule_id}, {"approved": True})
    return {"ok": True}
