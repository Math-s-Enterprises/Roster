"""Decision-time evidence, not learned preferences or retrospective guesses.

The scheduler remains the production decision-maker.  This module freezes the
facts needed to explain and eventually learn from one decision:

* the effective hard constraints and learned inputs the scheduler saw;
* the proposal it produced, including why each placed row exists;
* the final approval and the manager's corrections.

Nothing here changes ranking.  Evidence that cannot safely become a training
label is retained with a reason instead of being silently treated as one.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from pathlib import Path
from collections import Counter


EMPLOYEE_FIELDS = set("employee_id role departments age max_weekly_hours preferred_days_off is_active past_staff availability employment_type contract_span_hours contract_span_tolerance is_student term_time_max_hours summer_break".split())
SHOP_FIELDS = set("shop_id hours min_shift_hours max_shift_hours max_working_days roles departments multi_department open_24h shift_templates role_hierarchy min_rest_hours strict_days_off breaks_are_paid overstaff_tolerance".split())
SHIFT_FIELDS = set("employee_id day start end pinned extra fixed locked sick paid_holiday unpaid_holiday temp_override".split())
DECISION_SHIFT_FIELDS = SHIFT_FIELDS | {
    "contract_top_up", "supervisory_cover", "coverage_fallback",
    "preference_relaxed", "template_id", "template_name", "span_hours",
    "paid_hours", "break_minutes",
}


def select(record, fields):
    return deepcopy({k: v for k, v in record.items() if k in fields})


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _ordered(records, *keys):
    return sorted(records, key=lambda row: tuple(str(row.get(k, "")) for k in keys))


def _week_dates(week_start):
    try:
        monday = date.fromisoformat(week_start)
    except (TypeError, ValueError):
        return set()
    return {(monday + timedelta(days=offset)).isoformat() for offset in range(7)}


def _date_range(record):
    try:
        start = date.fromisoformat(record["date"])
        end = date.fromisoformat(record.get("end_date") or record["date"])
    except (KeyError, TypeError, ValueError):
        return set()
    if end < start:
        return set()
    return {
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    }


def hard_constraints(shop, employees, holidays, week_start):
    """Normalized limits effective for this week, without contact/pay data."""
    from app.services import availability as avail
    from app.services.scheduler import (
        ABSOLUTE_MAX_SHIFT_HOURS, MAX_WORKING_DAYS, MINOR_AGE,
        MINOR_EARLIEST_START, MINOR_LATEST_END, MIN_REST_HOURS,
    )

    dates = _week_dates(week_start)
    leave = {}
    shop_closed = set()
    for holiday in holidays:
        overlap = _date_range(holiday) & dates
        if not overlap:
            continue
        if holiday.get("scope") == "shop":
            shop_closed |= overlap
        elif holiday.get("scope") in ("employee", "unavailable", "sick"):
            employee_id = holiday.get("employee_id")
            if employee_id:
                leave.setdefault(employee_id, set()).update(overlap)

    per_employee = []
    for employee in _ordered(employees, "employee_id"):
        employee_id = employee.get("employee_id")
        cap, cap_source = avail.weekly_hour_cap_explained(employee, week_start)
        band = avail.contract_span_band(employee)
        per_employee.append({
            "employee_id": employee_id,
            "role": employee.get("role", ""),
            "active": avail.is_active(employee),
            "weekly_hour_cap": cap,
            "weekly_hour_cap_source": cap_source,
            "contract_span_band": list(band) if band else None,
            "preferred_days_off": sorted(employee.get("preferred_days_off") or []),
            "availability": deepcopy(employee.get("availability") or {}),
            "leave_dates": sorted(leave.get(employee_id, set())),
        })

    configured_max = float(shop.get("max_shift_hours") or ABSOLUTE_MAX_SHIFT_HOURS)
    return {
        "week_start": week_start,
        "policy": {
            "coverage_required_during_open_hours": True,
            "one_shift_per_employee_day": True,
            "familiarity_is_blocking_when_history_exists": True,
            "absolute_max_shift_hours": ABSOLUTE_MAX_SHIFT_HOURS,
            "effective_max_shift_hours": min(configured_max, ABSOLUTE_MAX_SHIFT_HOURS),
            "max_working_days": int(shop.get("max_working_days") or MAX_WORKING_DAYS),
            "min_rest_hours": float(shop.get("min_rest_hours") or MIN_REST_HOURS),
            "minor_age_threshold": MINOR_AGE,
            "minor_earliest_start": MINOR_EARLIEST_START,
            "minor_latest_end": MINOR_LATEST_END,
        },
        "shop_closed_dates": sorted(shop_closed),
        "employees": per_employee,
    }


def context(shop, employees, holidays, fixed_shifts, rules, *, week_start=None):
    payload = {
        "schema_version": 2,
        "shop": select(shop, SHOP_FIELDS),
        "employees": [select(e, EMPLOYEE_FIELDS) for e in _ordered(employees, "employee_id")],
        "holidays": [select(h, {
            "holiday_id", "employee_id", "date", "end_date", "scope",
            "hours_per_day",
        })
                     for h in _ordered(holidays, "date", "employee_id", "holiday_id")],
        "fixed_shifts": [select(f, SHIFT_FIELDS | {"fixed_shift_id", "enabled", "days"})
                         for f in _ordered(fixed_shifts, "employee_id", "fixed_shift_id")],
        "rules": [select(r, {"rule_id", "enabled", "approved", "compiled", "compiled_by", "locked", "title", "description"})
                  for r in _ordered(rules, "rule_id", "title")],
    }
    if week_start:
        payload["hard_constraints"] = hard_constraints(
            shop, employees, holidays, week_start,
        )
    # Stable across capture times and database result ordering.  It tells us
    # whether the manager approved under the same constraints as generation.
    payload["context_hash"] = digest(payload)
    payload["captured_at"] = datetime.now(timezone.utc).isoformat()
    return payload


def generation_context(shop, employees, holidays, fixed_shifts, rules, history, *,
                       week_start, seed, only_day, department, locked_shifts,
                       weights=None, demand=None):
    evidence = context(
        shop, employees, holidays, fixed_shifts, rules, week_start=week_start,
    )
    # Hash the deployed service sources, including uncommitted changes. This
    # identifies code; it does not pretend to preserve an executable build.
    sources = {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*.py"))}
    evidence.update({
        "solver_source_hash": digest(sources),
        "model_version": None,
        "week_start": week_start, "seed": seed, "only_day": only_day,
        "department": department,
        "locked_shifts": [select(s, SHIFT_FIELDS) for s in locked_shifts],
        "preference_weights": deepcopy(weights or {}),
        "demand_profile": deepcopy(demand.to_dict()) if demand is not None else None,
        "history_sources": [{
            "roster_id": r.get("roster_id"), "week_start": r.get("week_start"),
            "content_hash": digest(r),
        } for r in sorted(history, key=lambda r: (r.get("week_start", ""), r.get("roster_id", "")))],
        "replay_complete": False,
    })
    evidence["input_hash"] = digest({
        key: value for key, value in evidence.items() if key != "captured_at"
    })
    return evidence


def assignment_source(shift):
    if shift.get("extra"):
        return "extra"
    if shift.get("pinned") or shift.get("locked"):
        return "manager_locked"
    if shift.get("fixed"):
        return "fixed_shift"
    if shift.get("contract_top_up"):
        return "contract_top_up"
    if shift.get("supervisory_cover"):
        return "supervisory_cover"
    if shift.get("coverage_fallback"):
        return "coverage_floor"
    if shift.get("preference_relaxed"):
        return "preference_relaxed"
    return "learned_demand"


def constraint_outcome(shifts, *, shop, employees, holidays, week_start,
                       history_rosters=None):
    """Derived constraint result, stripped of names and free-text messages."""
    from app.services import compliance

    breaches = compliance.audit(
        shifts, shop=shop, employees=employees, holidays=holidays,
        week_start=week_start,
    )
    return {
        "uncovered_hours": compliance.uncovered_hours(
            shifts, shop=shop, week_start=week_start,
            history_rosters=history_rosters or [],
        ),
        "breaches": [select(b, {"employee_id", "rule", "overridable"})
                     for b in breaches],
        "under_contract": [select(row, {
            "employee_id", "role", "contracted_hours", "minimum_hours",
            "rostered_hours", "short_hours",
        }) for row in compliance.under_contract(
            shifts, employees=employees, shop=shop, week_start=week_start,
            holidays=holidays,
        )],
    }


def proposal(result, *, shop, employees, holidays, week_start,
             history_rosters=None):
    """The solver's final proposal, with placement provenance and checks."""
    roles = {e.get("employee_id"): e.get("role", "") for e in employees}
    decisions = []
    for shift in result.get("shifts") or []:
        if not (shift.get("employee_id") and shift.get("day")):
            continue
        row = select(shift, DECISION_SHIFT_FIELDS)
        row["role"] = roles.get(shift.get("employee_id"), "")
        row["assignment_source"] = (
            "paid_holiday" if shift.get("paid_holiday") else assignment_source(shift)
        )
        decisions.append(row)
    decisions.sort(key=lambda row: (
        row.get("day", ""), row.get("start", ""), row.get("employee_id", "")
    ))
    selected_shifts = [select(s, SHIFT_FIELDS) for s in result.get("shifts") or []]
    return {
        "schema_version": 1,
        "proposal_hash": digest(selected_shifts),
        "decisions": decisions,
        "constraint_outcome": constraint_outcome(
            result.get("shifts") or [], shop=shop, employees=employees,
            holidays=holidays, week_start=week_start,
            history_rosters=history_rosters,
        ),
        "summary": {
            "shift_rows": len(result.get("shifts") or []),
            "working_shift_rows": sum(
                bool(s.get("start") and s.get("end"))
                and not any(s.get(key) for key in (
                    "sick", "paid_holiday", "unpaid_holiday", "temp_override"
                ))
                for s in result.get("shifts") or []
            ),
            "issues": len(result.get("issues") or []),
            "critical_issues": len(result.get("critical_issues") or []),
        },
    }


def approval_evidence(*, approval_context, generation_context,
                      generation_shifts, final_shifts, corrections,
                      forced, uncovered_hours, breaches, constraint_result):
    """A final decision plus an explicit verdict on ordinary training use."""
    baseline_available = generation_shifts is not None
    generation_hash = (generation_context or {}).get("context_hash")
    approval_hash = (approval_context or {}).get("context_hash")
    context_unchanged = (
        generation_hash == approval_hash
        if generation_hash and approval_hash else None
    )
    reasons = []
    if not baseline_available:
        reasons.append("missing_generated_baseline")
    if not generation_context:
        reasons.append("missing_generation_context")
    if context_unchanged is False:
        reasons.append("decision_context_changed")
    if forced or breaches:
        reasons.append("forced_or_breaching_approval")
    if uncovered_hours:
        reasons.append("approved_with_uncovered_hours")
    if any(
        any(shift.get(key) for key in (
            "sick", "paid_holiday", "unpaid_holiday", "temp_override"
        ))
        for shift in final_shifts or []
    ):
        reasons.append("contains_exception_rows")

    if forced:
        outcome = "forced"
    elif uncovered_hours:
        outcome = "approved_with_gaps"
    elif corrections:
        outcome = "edited"
    else:
        outcome = "unchanged"

    return {
        "schema_version": 2,
        "context": approval_context,
        "shifts": [select(s, SHIFT_FIELDS) for s in final_shifts or []],
        "corrections": deepcopy(corrections or []),
        "baseline_available": baseline_available,
        "outcome": outcome,
        "context_unchanged": context_unchanged,
        "ordinary_training_eligible": not reasons,
        "exclusion_reasons": sorted(set(reasons)),
        "forced": forced,
        "uncovered_hours": deepcopy(uncovered_hours or []),
        "proposal_hash": digest([
            select(s, SHIFT_FIELDS) for s in (generation_shifts or [])
        ]) if baseline_available else None,
        "final_hash": digest([select(s, SHIFT_FIELDS) for s in final_shifts or []]),
        "constraint_outcome": deepcopy(constraint_result),
    }


def historical_examples(rosters, employee_ids=None):
    """Export observations and explicit outcomes, never guessed negatives.

    Ambiguous weeks are quarantined instead of silently selecting a version.
    Employee-day collisions invalidate both sides of a correction comparison.
    """
    eligible = [r for r in rosters if r.get("approved") and not r.get("exclude_from_ai")]
    counts = Counter(r.get("week_start") for r in eligible)
    for r in eligible:
        week = r.get("week_start")
        if not week or counts[week] > 1:
            yield {"kind": "quarantine", "roster_id": r.get("roster_id"), "week_start": week, "reason": "missing_or_duplicate_week"}
            continue
        approval = r.get("training_approval")
        shifts = approval.get("shifts", []) if approval else r.get("shifts", [])
        collisions = set()
        for rows in (shifts, r.get("generated_shifts", [])):
            keys = Counter((s.get("employee_id"), s.get("day")) for s in rows)
            collisions.update(k for k, n in keys.items() if n > 1)
        ordinary_eligible = bool(
            approval and approval.get("ordinary_training_eligible")
        )
        for s in shifts:
            reasons = []
            if (s.get("employee_id"), s.get("day")) in collisions:
                reasons.append("duplicate_employee_day")
            if not s.get("employee_id") or s.get("day") not in ("mon", "tue", "wed", "thu", "fri", "sat", "sun") or any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(s.get(k, ""))) for k in ("start", "end")):
                reasons.append("missing_or_invalid_shift_fields")
            if employee_ids is not None and s.get("employee_id") not in employee_ids:
                reasons.append("missing_employee_reference")
            if any(s.get(k) for k in ("sick", "paid_holiday", "unpaid_holiday", "temp_override")):
                reasons.append("exception")
            if r.get("force_approved"):
                reasons.append("forced_approval")
            yield {
                "kind": "quarantine" if reasons else "historical_observation",
                "shop_id": r.get("shop_id"), "roster_id": r.get("roster_id"),
                "week_start": week, "shift": select(s, SHIFT_FIELDS),
                "reasons": reasons, "source_hash": digest(r),
                "approval_snapshot_available": bool(approval),
                "decision_context_available": bool(r.get("training_context")),
                "eligibility_verified": ordinary_eligible and not reasons,
            }
        if not approval:
            yield {
                "kind": "approval_outcome", "shop_id": r.get("shop_id"),
                "roster_id": r.get("roster_id"), "week_start": week,
                "outcome": "unknown", "trainable": False,
                "reasons": ["missing_approval_snapshot"],
                "source_hash": digest(r),
            }
            for correction in r.get("corrections") or []:
                reasons = ["missing_approval_snapshot"]
                if not r.get("training_context"):
                    reasons.append("missing_generation_context")
                if correction.get("kind") != "swap":
                    reasons.append("not_a_pairwise_employee_choice")
                yield {
                    "kind": "manager_correction", "shop_id": r.get("shop_id"),
                    "roster_id": r.get("roster_id"), "week_start": week,
                    "correction": deepcopy(correction),
                    "training_label": None, "trainable": False,
                    "reasons": sorted(reasons), "source_hash": digest(r),
                }
            continue

        yield {
            "kind": "approval_outcome", "shop_id": r.get("shop_id"),
            "roster_id": r.get("roster_id"), "week_start": week,
            "outcome": approval.get("outcome", "unknown"),
            "edit_count": len(approval.get("corrections") or []),
            "trainable": ordinary_eligible,
            "reasons": deepcopy(approval.get("exclusion_reasons") or []),
            "proposal_hash": approval.get("proposal_hash"),
            "final_hash": approval.get("final_hash"),
            "context_unchanged": approval.get("context_unchanged"),
            "source_hash": digest(r),
        }
        for correction in approval.get("corrections") or []:
            reasons = list(approval.get("exclusion_reasons") or [])
            if not ordinary_eligible:
                reasons.append("approval_not_training_eligible")
            if correction.get("kind") != "swap":
                # A removal can mean leave, quiet trade, training, or a
                # preference.  It is a real manager action but not a safe
                # negative employee-choice label on its own.
                reasons.append("not_a_pairwise_employee_choice")
            if correction.get("kind") == "swap" and not (
                correction.get("employee_id")
                and correction.get("replaced_employee_id")
                and correction.get("slot")
            ):
                reasons.append("incomplete_swap")
            pairwise = correction.get("kind") == "swap" and not reasons
            yield {
                "kind": "manager_correction", "shop_id": r.get("shop_id"),
                "roster_id": r.get("roster_id"), "week_start": week,
                "correction": deepcopy(correction),
                "training_label": "pairwise_preference" if pairwise else None,
                "trainable": pairwise,
                "reasons": sorted(set(reasons)),
                "source_hash": digest(r),
            }
