"""Paid sick leave entitlement and what is left of it.

SET IN DAYS, SPENT IN HOURS
---------------------------
The entitlement is written in days because that is how the law writes it —
Ireland's Statutory Sick Leave is five days a year — and how a manager thinks
about it. It is spent in hours because a day is not a fixed quantity: a
part-timer losing a four-hour Saturday has not used the same thing as a
full-timer losing a ten-hour Monday, and counting both as "one day" quietly
robs one of them.

Each person's day is therefore converted using their own usual shift, taken
from what they have actually worked rather than from a contract field that
may never have been filled in.

Sick leave beyond the entitlement is not refused — people do not stop being
ill because an allowance ran out. It is recorded as unpaid, and reported.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.services.scheduler import shift_paid_hours

# Ireland's Statutory Sick Leave from 2024. A default, not a rule: shops
# elsewhere, and shops that pay more than the minimum, set their own.
DEFAULT_PAID_SICK_DAYS = 5

# Used only when somebody has no worked history at all to average.
FALLBACK_DAY_HOURS = 8.0


def paid_sick_days(shop: Optional[Dict[str, Any]] = None) -> float:
    value = (shop or {}).get("paid_sick_days")
    return float(value) if value is not None else float(DEFAULT_PAID_SICK_DAYS)


def usual_day_hours(
    employee_id: str, approved_rosters: List[Dict[str, Any]]
) -> float:
    """This person's average worked shift, in hours.

    The conversion rate between the entitlement's days and the hours it is
    actually spent in. Averaged over real shifts because a "day" for somebody
    on 12h nights is not a "day" for somebody on 4h Saturdays.
    """
    hours: List[float] = []
    for roster in approved_rosters:
        for shift in roster.get("shifts", []):
            if shift.get("employee_id") != employee_id:
                continue
            if shift.get("paid_holiday") or shift.get("unpaid_holiday") or shift.get("sick"):
                continue
            worked = shift_paid_hours(shift)
            if worked > 0:
                hours.append(worked)
    if not hours:
        return FALLBACK_DAY_HOURS
    return round(sum(hours) / len(hours), 2)


def _leave_year(shop: Optional[Dict[str, Any]], today: Optional[date] = None) -> str:
    """The year an entitlement is counted over. Calendar year by default."""
    today = today or date.today()
    return str((shop or {}).get("leave_year") or today.year)


def compute_sick_balance(
    employee: Dict[str, Any],
    approved_rosters: List[Dict[str, Any]],
    *,
    shop: Optional[Dict[str, Any]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Entitlement, used and remaining for one employee this leave year."""
    employee_id = employee["employee_id"]
    year = _leave_year(shop, today)
    days = paid_sick_days(shop)
    day_hours = usual_day_hours(employee_id, approved_rosters)
    entitlement = round(days * day_hours, 2)

    used = 0.0
    occurrences: List[Dict[str, Any]] = []
    for roster in approved_rosters:
        week = str(roster.get("week_start") or "")
        if not week.startswith(year):
            continue
        for shift in roster.get("shifts", []):
            if shift.get("employee_id") != employee_id or not shift.get("sick"):
                continue
            # A sick shift carries the hours the person would have worked.
            hours = shift_paid_hours(shift) or day_hours
            used += hours
            occurrences.append({
                "week_start": week,
                "day": shift.get("day"),
                "hours": round(hours, 2),
                "paid": None,     # filled below, once the running total is known
            })

    # Paid until the entitlement runs out, then unpaid. Ordered so the
    # earliest illness is the one that gets paid.
    running = 0.0
    for occurrence in occurrences:
        occurrence["paid"] = running < entitlement
        running += occurrence["hours"]

    remaining = max(0.0, entitlement - used)
    return {
        "employee_id": employee_id,
        "name": employee.get("name", ""),
        "leave_year": year,
        "entitlement_days": days,
        "usual_day_hours": day_hours,
        "entitlement_hours": entitlement,
        "used_hours": round(used, 2),
        "remaining_hours": round(remaining, 2),
        "remaining_days": round(remaining / day_hours, 1) if day_hours else 0.0,
        "exhausted": used >= entitlement,
        "occurrences": occurrences,
    }
