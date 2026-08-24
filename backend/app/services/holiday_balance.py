"""Holiday entitlement: what someone has earned, used, and has left.

The balance has four inputs, and all four are needed to get it right:

    opening    what they carried in from whatever system the shop used
               before — set once during import, never recalculated
    accrued    earned from hours actually worked, at the statutory rate
    used       paid holiday taken, read from approved rosters
    adjustments manual corrections, each with a reason and a timestamp

Booking more paid holiday than someone has is blocked rather than warned
about, because the alternative is discovering it at payroll — after the
person has already been told they are off and paid.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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


def compute_balance(
    employee: Dict[str, Any],
    approved_rosters: List[Dict[str, Any]],
    *,
    shop: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full breakdown for one employee.

    Returned as a breakdown rather than a single number so the UI can show
    the working — an employee querying their balance wants to see where it
    came from, not be told to trust it.
    """
    employee_id = employee["employee_id"]
    worked = used = 0.0

    for roster in approved_rosters:
        for shift in roster.get("shifts", []):
            if shift.get("employee_id") != employee_id or not _is_countable(shift):
                continue
            hours = shift_paid_hours(shift)
            if shift.get("paid_holiday"):
                used += hours
            else:
                worked += hours

    opening = float(employee.get("opening_holiday_hours") or 0.0)
    adjustments = employee.get("holiday_adjustments") or []
    adjusted = sum(float(a.get("hours", 0)) for a in adjustments)
    accrued = worked * accrual_rate(shop)
    available = opening + accrued + adjusted - used

    return {
        "employee_id": employee_id,
        "name": employee.get("name"),
        "role": employee.get("role"),
        "opening_hours": round(opening, 2),
        "hours_worked": round(worked, 1),
        "accrued_hours": round(accrued, 2),
        "adjustment_hours": round(adjusted, 2),
        "used_hours": round(used, 1),
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
