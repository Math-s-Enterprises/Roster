"""Holiday entitlement: balances, adjustments, and booking capacity."""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, status

from app.models import HolidayAdjustment
from app.services import holiday_balance
from app.services.hierarchy import display_order
from app.tenancy import ShopScope, CurrentScope

log = logging.getLogger("roster.holidays")
router = APIRouter(prefix="/holiday-balance", tags=["holidays"])


async def _approved(scope: ShopScope) -> List[Dict[str, Any]]:
    return [r async for r in scope.rosters.stream({"approved": True})]


@router.get("")
async def all_balances(scope: ShopScope = CurrentScope):
    """Everyone's entitlement, in the shop's reading order."""
    approved = await _approved(scope)
    employees = display_order(await scope.employees.find(limit=1000), scope.shop)
    return [
        holiday_balance.compute_balance(e, approved, shop=scope.shop)
        for e in employees
    ]


@router.get("/{employee_id}")
async def employee_balance(
    employee_id: str,
    hours_per_day: float = Query(
        None, gt=0, le=24,
        description="Day length to price a booking at. Defaults to their contract / 5.",
    ),
    scope: ShopScope = CurrentScope,
):
    """One employee's entitlement, plus how many paid days it covers.

    `max_payable_days` is what lets the booking form stop the manager at the
    right day rather than refusing the whole booking after the fact.
    """
    employee = await scope.employees.find_one({"employee_id": employee_id})
    if not employee:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")

    balance = holiday_balance.compute_balance(
        employee, await _approved(scope), shop=scope.shop
    )
    day_hours = hours_per_day or round((employee.get("max_weekly_hours") or 40) / 5, 2)
    return {
        **balance,
        "hours_per_day": day_hours,
        "max_payable_days": holiday_balance.max_payable_days(balance, day_hours),
    }


@router.post("/{employee_id}/adjust")
async def adjust_balance(
    employee_id: str, payload: HolidayAdjustment, scope: ShopScope = CurrentScope
):
    """Manually correct a balance, recording why.

    Appended rather than applied in place: the list of adjustments is the
    audit trail, and an unexplained change to someone's entitlement is
    impossible to defend if they query it.
    """
    employee = await scope.employees.find_one({"employee_id": employee_id})
    if not employee:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")

    adjustment = holiday_balance.make_adjustment(
        payload.hours, payload.reason, by=scope.user.get("email", ""),
    )
    adjustments = list(employee.get("holiday_adjustments") or [])
    adjustments.append(adjustment)

    await scope.employees.update_one(
        {"employee_id": employee_id}, {"holiday_adjustments": adjustments}
    )

    updated = await scope.employees.find_one({"employee_id": employee_id})
    return {
        "ok": True,
        "adjustment": adjustment,
        "balance": holiday_balance.compute_balance(
            updated, await _approved(scope), shop=scope.shop
        ),
    }


@router.put("/{employee_id}/opening")
async def set_opening_balance(
    employee_id: str,
    hours: float = Query(..., ge=0, le=2000),
    scope: ShopScope = CurrentScope,
):
    """Set the balance carried in from whatever system the shop used before.

    Meant for initial setup. Changing it later silently would rewrite
    history, so a change to an already-set value is recorded as an
    adjustment instead of a quiet overwrite.
    """
    employee = await scope.employees.find_one({"employee_id": employee_id})
    if not employee:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")

    previous = employee.get("opening_holiday_hours")
    changes: Dict[str, Any] = {"opening_holiday_hours": hours}

    if previous is not None and abs(float(previous) - hours) > 1e-6:
        adjustments = list(employee.get("holiday_adjustments") or [])
        adjustments.append(holiday_balance.make_adjustment(
            0.0,
            f"Opening balance corrected from {float(previous):g}h to {hours:g}h.",
            by=scope.user.get("email", ""),
        ))
        changes["holiday_adjustments"] = adjustments

    await scope.employees.update_one({"employee_id": employee_id}, changes)
    updated = await scope.employees.find_one({"employee_id": employee_id})
    return holiday_balance.compute_balance(
        updated, await _approved(scope), shop=scope.shop
    )
