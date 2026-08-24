"""Hours and wages for a date range, per employee.

WHAT THIS ANSWERS
-----------------
"How many hours did each person do last month, and what do I owe them?"

Three numbers per person, and the distinction between them is the whole
point:

    span hours    clock in to clock out — time on the premises
    paid hours    what the wage is calculated on
    break hours   the difference

When the shop pays through breaks, paid == span and break hours are zero.
When it does not, breaks come out of the paid figure. That single shop
setting moves every wage in this report, which is why it is stated at the top
of the output rather than left for the reader to assume.

WHY ONLY APPROVED ROSTERS
-------------------------
A draft is a proposal. Counting one would produce a wage bill for hours
nobody was ever told to work, and the figure would change under the reader as
the draft was edited. Approval is the moment a roster becomes the schedule
people work, so it is also the moment it becomes payable.

WHY SHIFTS ARE DATED INDIVIDUALLY
---------------------------------
A roster week is Monday to Sunday, but a payroll month is not. The week of
26 January runs into February, and counting the whole week into January would
put days in a month they were not worked — a total that cannot be reconciled
against a payslip. Every shift is therefore given its own calendar date and
tested against the range.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from app.services import availability as avail
from app.services.scheduler import (
    DAYS,
    shift_paid_hours,
    shift_span_hours,
    shop_breaks_paid,
)


def _parse(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def shift_date(week_start: str, day: str) -> Optional[date]:
    """The calendar date a shift falls on.

    Overnight shifts belong to the day they START, which is how the roster
    records them and how a payslip reads: somebody clocking on at 23:00 on
    Friday worked a Friday shift, even though most of it is Saturday.
    """
    monday = _parse(week_start)
    if monday is None or day not in DAYS:
        return None
    return monday + timedelta(days=DAYS.index(day))


def _is_leave(shift: Dict[str, Any]) -> bool:
    return bool(
        shift.get("paid_holiday") or shift.get("unpaid_holiday") or shift.get("sick")
    )


def _blank_row(employee: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "employee_id": employee["employee_id"],
        "name": employee.get("name", ""),
        "role": employee.get("role", ""),
        "employment_type": avail.employment_type(employee),
        "hourly_rate": float(employee.get("hourly_rate") or 0),
        "span_hours": 0.0,
        "paid_hours": 0.0,
        "break_hours": 0.0,
        "days_worked": 0,
        "paid_holiday_days": 0,
        "paid_holiday_hours": 0.0,
        "unpaid_holiday_days": 0,
        "sick_days": 0,
        "cost": 0.0,
        # Filled in below, and only for full-time contracts.
        "contract_hours": None,
        "contract_expected": None,
        "contract_variance": None,
        "short_weeks": [],
    }


def build_report(
    *,
    shop: Dict[str, Any],
    employees: List[Dict[str, Any]],
    rosters: Iterable[Dict[str, Any]],
    start: str,
    end: str,
) -> Dict[str, Any]:
    """Per-employee hours and wages for [start, end], both inclusive."""
    first, last = _parse(start), _parse(end)
    if first is None or last is None:
        raise ValueError("start and end must be YYYY-MM-DD")
    if last < first:
        first, last = last, first

    breaks_paid = shop_breaks_paid(shop)

    # Leavers are included: they worked the hours and are owed for them.
    rows: Dict[str, Dict[str, Any]] = {
        e["employee_id"]: _blank_row(e) for e in employees
    }

    # week_start -> employee_id -> span hours, for the contract check. Kept
    # per week because a contract is a weekly obligation: averaging a month
    # would hide one short week behind one long one.
    weekly_span: Dict[str, Dict[str, float]] = {}
    weeks_seen: Dict[str, bool] = {}

    for roster in rosters:
        if not roster.get("approved"):
            continue
        week_start = roster.get("week_start")
        if not week_start:
            continue

        for shift in roster.get("shifts", []):
            employee_id = shift.get("employee_id")
            row = rows.get(employee_id)
            if row is None:
                continue

            when = shift_date(week_start, shift.get("day", ""))
            if when is None or not (first <= when <= last):
                continue

            if shift.get("unpaid_holiday"):
                row["unpaid_holiday_days"] += 1
                continue
            if shift.get("sick"):
                row["sick_days"] += 1
                continue
            if shift.get("paid_holiday"):
                hours = shift_paid_hours(shift)
                row["paid_holiday_days"] += 1
                row["paid_holiday_hours"] += hours
                row["cost"] += hours * row["hourly_rate"]
                continue

            span = shift_span_hours(shift)
            paid = shift_paid_hours(shift)
            if breaks_paid:
                # The stored paid_hours was written with breaks deducted;
                # a shop that pays through them owes the full span.
                paid = span

            row["span_hours"] += span
            row["paid_hours"] += paid
            row["break_hours"] += max(0.0, span - paid)
            row["days_worked"] += 1
            row["cost"] += paid * row["hourly_rate"]

            weekly_span.setdefault(week_start, {})
            weekly_span[week_start][employee_id] = (
                weekly_span[week_start].get(employee_id, 0.0) + span
            )
            # Only weeks lying wholly inside the range can be judged against
            # a contract: half a week is short by definition, and flagging it
            # would cry wolf on every month boundary.
            monday = _parse(week_start)
            weeks_seen[week_start] = bool(
                monday and first <= monday and monday + timedelta(days=6) <= last
            )

    _apply_contracts(rows, employees, weekly_span, weeks_seen)

    ordered = sorted(
        (r for r in rows.values() if _has_anything(r)),
        key=lambda r: r["name"].lower(),
    )
    for row in ordered:
        for key in ("span_hours", "paid_hours", "break_hours",
                    "paid_holiday_hours", "cost"):
            row[key] = round(row[key], 2)

    return {
        "start": first.isoformat(),
        "end": last.isoformat(),
        "breaks_are_paid": breaks_paid,
        "rows": ordered,
        "totals": _totals(ordered),
        "weeks_counted": sorted(weeks_seen),
        "whole_weeks": sorted(w for w, whole in weeks_seen.items() if whole),
    }


def _has_anything(row: Dict[str, Any]) -> bool:
    """Drop people with nothing in the period rather than pad the table."""
    return bool(
        row["days_worked"] or row["paid_holiday_days"]
        or row["unpaid_holiday_days"] or row["sick_days"]
    )


def _apply_contracts(
    rows: Dict[str, Dict[str, Any]],
    employees: List[Dict[str, Any]],
    weekly_span: Dict[str, Dict[str, float]],
    weeks_seen: Dict[str, bool],
) -> None:
    """Compare salaried staff against what they are contracted to work.

    Judged week by week, and only on weeks lying wholly inside the range.
    A full-time contract is a weekly promise: somebody who does 35 hours one
    week and 50 the next has been let down once and overworked once, and a
    monthly average of 42.5 would report neither.
    """
    whole = [w for w, is_whole in weeks_seen.items() if is_whole]

    for employee in employees:
        row = rows.get(employee["employee_id"])
        if row is None:
            continue
        band = avail.contract_span_band(employee)
        if not band:
            continue

        minimum, target = band
        row["contract_hours"] = target
        if not whole:
            continue

        row["contract_expected"] = round(target * len(whole), 2)
        actual = sum(
            weekly_span.get(week, {}).get(employee["employee_id"], 0.0)
            for week in whole
        )
        row["contract_variance"] = round(actual - row["contract_expected"], 2)
        row["short_weeks"] = sorted(
            week for week in whole
            if weekly_span.get(week, {}).get(employee["employee_id"], 0.0) < minimum
        )


def _totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "people": len(rows),
        "span_hours": round(sum(r["span_hours"] for r in rows), 2),
        "paid_hours": round(sum(r["paid_hours"] for r in rows), 2),
        "break_hours": round(sum(r["break_hours"] for r in rows), 2),
        "paid_holiday_hours": round(sum(r["paid_holiday_hours"] for r in rows), 2),
        "days_worked": sum(r["days_worked"] for r in rows),
        "sick_days": sum(r["sick_days"] for r in rows),
        "cost": round(sum(r["cost"] for r in rows), 2),
    }
