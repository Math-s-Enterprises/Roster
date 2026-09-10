"""Holiday entitlement: what someone has earned, used, and has left.

The balance has five inputs, and all five are needed to get it right:

    opening    what they carried in from whatever system the shop used
               before — set once during import, never recalculated
    accrued    earned from hours actually worked, at the statutory rate
    used       paid holiday taken, read from approved rosters
    booked     paid holiday reserved for dates not yet on an approved roster
    adjustments manual corrections, each with a reason and a timestamp

Booking more paid holiday than someone has is blocked rather than warned
about, because the alternative is discovering it at payroll — after the
person has already been told they are off and paid.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from app.services.scheduler import shift_paid_hours

# Statutory accrual: 12.07% of hours worked. That is 5.6 weeks' leave spread
# over the 46.4 working weeks of a year, the standard figure for staff
# without fixed hours.
ACCRUAL_RATE = 0.1207


def accrual_rate(shop: Optional[Dict[str, Any]] = None) -> float:
    """Configurable per shop — jurisdictions and contracts differ."""
    if shop and shop.get("holiday_accrual_rate"):
        return float(shop["holiday_accrual_rate"])
    return ACCRUAL_RATE


def _is_countable(shift: Dict[str, Any]) -> bool:
    """Sick days and unpaid leave neither earn nor spend entitlement."""
    return not (shift.get("sick") or shift.get("unpaid_holiday"))


DAY_INDEX = {
    day: index for index, day in enumerate(
        ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    )
}


def _dates(record: Dict[str, Any]) -> List[str]:
    """Every valid date covered by a booking, inclusive."""
    try:
        start = date.fromisoformat(record["date"])
        end = date.fromisoformat(record.get("end_date") or record["date"])
    except (KeyError, TypeError, ValueError):
        return []
    if end < start:
        return []
    return [
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    ]


def _roster_date(roster: Dict[str, Any], shift: Dict[str, Any]) -> Optional[str]:
    """Calendar date represented by a roster's weekday row."""
    try:
        monday = date.fromisoformat(roster["week_start"])
        offset = DAY_INDEX[shift["day"]]
    except (KeyError, TypeError, ValueError):
        return None
    return (monday + timedelta(days=offset)).isoformat()


def _normal_paid_day(employee: Dict[str, Any]) -> float:
    """Fallback for legacy paid bookings which predate hours_per_day."""
    contract = float(employee.get("max_weekly_hours") or 0.0)
    return round(contract / 5, 2) if contract else 8.0


def compute_balance(
    employee: Dict[str, Any],
    approved_rosters: List[Dict[str, Any]],
    *,
    shop: Optional[Dict[str, Any]] = None,
    holidays: Optional[List[Dict[str, Any]]] = None,
    excluded_holiday_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Full breakdown for one employee.

    Returned as a breakdown rather than a single number so the UI can show
    the working — an employee querying their balance wants to see where it
    came from, not be told to trust it.
    """
    from app.services.learning import latest_per_week

    employee_id = employee["employee_id"]
    worked = used = 0.0
    used_dates: Set[str] = set()

    # Old data can contain two approved records for one week. Holiday pay was
    # only taken once in reality, so use the same one-week-one-vote rule as
    # every other learner/report instead of charging it twice.
    for roster in latest_per_week([
        roster for roster in approved_rosters if roster.get("approved", True)
    ]):
        for shift in roster.get("shifts", []):
            if shift.get("employee_id") != employee_id or not _is_countable(shift):
                continue
            hours = shift_paid_hours(shift)
            if shift.get("paid_holiday"):
                used += hours
                on = _roster_date(roster, shift)
                if on:
                    used_dates.add(on)
            else:
                worked += hours

    # A booking reserves entitlement immediately. Previously it was invisible
    # until its roster was approved, so a second booking could spend the same
    # hours again. Once an approved roster contains the paid-holiday row, its
    # date moves from booked to used and is deliberately not subtracted twice.
    excluded = excluded_holiday_ids or set()
    booked_by_date: Dict[str, float] = {}
    for holiday in holidays or []:
        if (
            holiday.get("scope") != "employee"
            or holiday.get("employee_id") != employee_id
            or holiday.get("holiday_id") in excluded
        ):
            continue
        hours = float(holiday.get("hours_per_day") or _normal_paid_day(employee))
        for on in _dates(holiday):
            if on in used_dates:
                continue
            # Overlapping legacy records still represent one paid day. Use
            # the larger stated value deterministically rather than charging
            # twice or depending on database result order.
            booked_by_date[on] = max(booked_by_date.get(on, 0.0), hours)
    booked = sum(booked_by_date.values())

    opening = float(employee.get("opening_holiday_hours") or 0.0)
    adjustments = employee.get("holiday_adjustments") or []
    adjusted = sum(float(a.get("hours", 0)) for a in adjustments)
    accrued = worked * accrual_rate(shop)
    available = opening + accrued + adjusted - used - booked

    return {
        "employee_id": employee_id,
        "name": employee.get("name"),
        "role": employee.get("role"),
        "opening_hours": round(opening, 2),
        "hours_worked": round(worked, 1),
        "accrued_hours": round(accrued, 2),
        "adjustment_hours": round(adjusted, 2),
        "used_hours": round(used, 1),
        "booked_hours": round(booked, 1),
        "booked_dates": sorted(booked_by_date),
        "available_hours": round(available, 2),
        "adjustments": adjustments,
    }


def check_can_book(
    balance: Dict[str, Any], hours_requested: float
) -> Dict[str, Any]:
    """Whether a proposed booking fits inside the available balance.

    Returns how many whole days would fit, so the UI can stop the manager at
    the right point rather than only telling them afterwards that the whole
    booking was refused.
    """
    available = float(balance["available_hours"])
    allowed = hours_requested <= available + 1e-6
    return {
        "allowed": allowed,
        "available_hours": round(available, 2),
        "requested_hours": round(hours_requested, 2),
        "shortfall_hours": round(max(0.0, hours_requested - available), 2),
    }


def max_payable_days(balance: Dict[str, Any], hours_per_day: float) -> int:
    """How many full paid days the remaining balance covers."""
    if hours_per_day <= 0:
        return 0
    return int((float(balance["available_hours"]) + 1e-6) // hours_per_day)


def make_adjustment(hours: float, reason: str, by: str = "") -> Dict[str, Any]:
    """A manual correction, always carrying its own explanation.

    Adjustments are appended, never edited: the history is the audit trail,
    and rewriting it would defeat the point.
    """
    return {
        "adjustment_id": f"adj_{uuid.uuid4().hex[:10]}",
        "hours": round(float(hours), 2),
        "reason": reason.strip(),
        "adjusted_by": by,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
