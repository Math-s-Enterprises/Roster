"""Which rules a finished roster breaks, and which of them may be overridden.

WHY THIS EXISTS SEPARATELY FROM roster_validation
-------------------------------------------------
`roster_validation` answers "may I save this edit?" — a question about one
change, asked while the manager is still working. It deliberately compares
before against after, so a swap is not refused because of a problem it did not
cause and cannot fix.

This answers a different question: "is the finished week legal, and if not,
what exactly is wrong and who does it affect?" It is asked once, at approval,
over the whole roster, and its output is meant to be read by a person — a
name, a sentence, a number they can check against the contract.

REFUSING WAS THE WRONG SHAPE
----------------------------
Before this, an edit that broke a rule was simply blocked. That reads as the
app knowing better than the manager, and it does not: a manager swapping two
shifts at 6am has information the app cannot see — somebody swapped with a
colleague, somebody offered to cover, somebody is going home early anyway.
Blocking made the roster impossible to finish and taught people to avoid the
edit screen.

So the flow is now: warn, allow, mark the person, and require a deliberate
authenticated override before the week becomes real. The manager keeps the
decision; the record keeps the evidence.

THE TWO THAT ARE NEVER OVERRIDABLE
----------------------------------
Everything here can be forced through except:

  * `minor_curfew` — an under-16 outside 08:00-19:00. That is criminal law,
    not a company policy, and a signed-off record of it is discoverable.
  * `double_booked` — one person in two places at once. Not a judgement call
    at all; it is a data error, and forcing it produces a roster that cannot
    physically happen.

Everything else — contracted hours, weekly caps, six-day weeks, the rest gap,
twelve-hour shifts, booked leave — is the manager's to override, because they
carry the consequence and the app does not.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.services import availability as avail
from app.services.scheduler import (
    ABSOLUTE_MAX_SHIFT_HOURS,
    DAYS,
    MAX_WORKING_DAYS,
    MIN_REST_HOURS,
    MINOR_AGE,
    paid_hours,
    shift_duration_minutes,
    to_minutes,
)

# Breaches that stand whatever the manager says. See the module docstring.
HARD_FLOOR = ("minor_curfew", "double_booked")


def _is_leave(shift: Dict[str, Any]) -> bool:
    return bool(
        shift.get("paid_holiday") or shift.get("unpaid_holiday") or shift.get("sick")
    )


def _worked(shifts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        s for s in shifts
        if s.get("start") and s.get("end") and not _is_leave(s)
    ]


def _week_minutes(day: str, hhmm: str) -> int:
    """Minutes from Monday 00:00.

    Clock time is not enough: a 23:30 Monday start and a 07:00 Tuesday finish
    are seven and a half hours apart, not sixteen and a half backwards.
    """
    return DAYS.index(day) * 1440 + to_minutes(hhmm)


def _span(shift: Dict[str, Any]) -> tuple:
    start = _week_minutes(shift["day"], shift["start"])
    length = shift_duration_minutes(shift["start"], shift["end"])
    return start, start + length


def _leave_dates(holidays: List[Dict[str, Any]]) -> Dict[str, set]:
    blocked: Dict[str, set] = {}
    for holiday in holidays or []:
        if holiday.get("scope") not in ("employee", "unavailable", "sick"):
            continue
        employee_id = holiday.get("employee_id")
        if not employee_id:
            continue
        try:
            start = datetime.strptime(holiday["date"], "%Y-%m-%d").date()
            end = datetime.strptime(
                holiday.get("end_date") or holiday["date"], "%Y-%m-%d"
            ).date()
        except (KeyError, TypeError, ValueError):
            continue
        cursor = start
        while cursor <= end:
            blocked.setdefault(employee_id, set()).add(cursor.isoformat())
            cursor += timedelta(days=1)
    return blocked


def uncovered_hours(
    shifts: List[Dict[str, Any]],
    *,
    shop: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Open hours with nobody in the shop, computed from the shifts NOW.

    WHY THIS IS NOT READ OFF THE ROSTER
    -----------------------------------
    The solver writes `critical_issues` when it builds a week, and approval
    used to read that list back. It is a stored fact about a roster that has
    since changed: fill the gap by hand and the list still names it, so
    approval refuses a week that is actually covered and the manager has no
    way to clear it. §5 — derive state, never store it. The compliance audit
    beside this already recomputes from the shifts; this brings the coverage
    check into line.

    The SENTENCE the solver writes is still worth more, because it knows why
    nobody could be placed — whose day off, what the capacity shortfall is.
    That reasoning cannot be reconstructed here and is not the question being
    asked at approval, which is only: is anybody in the shop.

    Hours are counted the way the rest of the app counts them (§7d), so this
    agrees with the solver about what "covered" means rather than inventing a
    second answer.
    """
    from app.services.scheduler import _RosterBuilder

    open_24h = bool((shop or {}).get("open_24h"))
    by_day = {h.get("day"): h for h in (shop or {}).get("hours") or []}

    def open_hours(day: str) -> List[int]:
        if open_24h:
            return list(range(24))
        hours = by_day.get(day)
        if not hours or hours.get("closed"):
            return []
        start, end = to_minutes(hours.get("open") or "00:00"), \
            to_minutes(hours.get("close") or "00:00")
        if end <= start:
            return list(range(24))
        return sorted({(m // 60) % 24 for m in range(start, end, 60)})

    on_duty: Dict[tuple, int] = {}
    for shift in _worked(shifts):
        for pair in _RosterBuilder.hours_covered(
            shift["day"], shift["start"], shift["end"], wrap_week=True,
        ):
            on_duty[pair] = on_duty.get(pair, 0) + 1

    empty = []
    for day in DAYS:
        for hour in open_hours(day):
            if on_duty.get((day, hour), 0) == 0:
                empty.append({
                    "day": day,
                    "hour": hour,
                    "window": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
                })
    return empty


def audit(
    shifts: List[Dict[str, Any]],
    *,
    shop: Dict[str, Any],
    employees: List[Dict[str, Any]],
    week_start: str,
    holidays: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Every rule this week breaks, grouped by the person it affects.

    Each breach carries a sentence a manager can act on — the number that is
    wrong and the number it should be — rather than a rule name. "Rostered 48h
    against a 44h cap" tells them what to change; "weekly_hours_exceeded" does
    not.
    """
    by_id = {e["employee_id"]: e for e in employees}
    blocked = _leave_dates(holidays or [])
    max_days = int((shop or {}).get("max_working_days") or MAX_WORKING_DAYS)
    breaks_paid = bool((shop or {}).get("breaks_are_paid"))

    try:
        monday = datetime.strptime(week_start, "%Y-%m-%d").date()
        date_for = {DAYS[i]: (monday + timedelta(days=i)).isoformat() for i in range(7)}
    except (TypeError, ValueError):
        date_for = {}

    mine: Dict[str, List[Dict[str, Any]]] = {}
    for shift in _worked(shifts):
        mine.setdefault(shift["employee_id"], []).append(shift)

    # Who has leave this week. A week broken by holiday or sickness is SHORT
    # for a reason that is not a scheduling fault: they are paid for the
    # holiday, so the contract is being honoured even though the hours on the
    # roster do not add up to it. Flagging it sent the manager looking for a
    # problem that does not exist, on the one week where the answer is
    # already on the screen next to the name.
    #
    # Only the SHORT-hours check is suppressed. Everything else still stands:
    # somebody on leave Monday who then works six days, or a four-hour
    # turnaround around their holiday, is a real problem and leave does not
    # excuse it.
    on_leave = {
        s["employee_id"] for s in shifts
        if _is_leave(s) and s.get("employee_id")
    }
    on_leave |= {
        employee_id for employee_id, dates in blocked.items()
        if dates & set(date_for.values())
    }

    found: List[Dict[str, Any]] = []

    def add(employee, rule, message):
        found.append({
            "employee_id": employee.get("employee_id"),
            "name": employee.get("name", "Someone"),
            "rule": rule,
            "message": message,
            "overridable": rule not in HARD_FLOOR,
        })

    for employee_id, theirs in mine.items():
        employee = by_id.get(employee_id)
        if not employee:
            continue

        theirs = sorted(theirs, key=lambda s: _span(s)[0])
        name = employee.get("name", "Someone")

        # ---- hours against their own ceiling -----------------------------
        worked_hours = sum(
            paid_hours(s["start"], s["end"], breaks_paid=breaks_paid) for s in theirs
        )
        cap = avail.weekly_hour_cap(employee, week_start)
        if cap and worked_hours > cap + 0.01:
            add(employee, "weekly_hours",
                f"{name} is rostered {worked_hours:.1f}h against a {cap:.0f}h "
                f"limit — {worked_hours - cap:.1f}h over.")

        band = avail.contract_span_band(employee)
        if band:
            spanned = sum(
                shift_duration_minutes(s["start"], s["end"]) / 60 for s in theirs
            )
            low, high = band
            if spanned > high + 0.01:
                add(employee, "contract_over",
                    f"{name} is on {spanned:.1f}h against a {high:.1f}h "
                    f"contract — {spanned - high:.1f}h over.")
            elif spanned < low - 0.01 and employee_id not in on_leave:
                add(employee, "contract_under",
                    f"{name} is on {spanned:.1f}h but is contracted for at "
                    f"least {low:.1f}h — {low - spanned:.1f}h short, and paid "
                    f"either way.")

        # ---- days ---------------------------------------------------------
        days = {s["day"] for s in theirs}
        if len(days) > max_days:
            add(employee, "days_worked",
                f"{name} is working {len(days)} days — {len(days) - max_days} "
                f"more than the {max_days}-day limit, so they do not get two "
                f"days off.")

        # ---- per-shift ------------------------------------------------------
        for shift in theirs:
            hours = shift_duration_minutes(shift["start"], shift["end"]) / 60
            if hours > ABSOLUTE_MAX_SHIFT_HOURS + 0.01:
                add(employee, "shift_length",
                    f"{name}'s {shift['day']} shift is {hours:.1f}h — over the "
                    f"{ABSOLUTE_MAX_SHIFT_HOURS}h maximum for one shift.")

            if int(employee.get("age") or 99) < MINOR_AGE:
                start_m, end_m = to_minutes(shift["start"]), to_minutes(shift["end"])
                overnight = end_m <= start_m
                if overnight or start_m < 8 * 60 or end_m > 19 * 60:
                    add(employee, "minor_curfew",
                        f"{name} is under {MINOR_AGE} and is rostered "
                        f"{shift['start']}-{shift['end']} on {shift['day']}. "
                        f"Under-16s cannot work before 08:00 or after 19:00.")

            date_iso = date_for.get(shift["day"])
            if date_iso and date_iso in blocked.get(employee_id, set()):
                add(employee, "booked_leave",
                    f"{name} has booked leave on {shift['day']} and is "
                    f"rostered {shift['start']}-{shift['end']}.")

        # ---- between shifts -------------------------------------------------
        for earlier, later in zip(theirs, theirs[1:]):
            _, ends = _span(earlier)
            starts, _ = _span(later)
            if starts < ends:
                add(employee, "double_booked",
                    f"{name} is rostered {earlier['start']}-{earlier['end']} on "
                    f"{earlier['day']} and {later['start']}-{later['end']} on "
                    f"{later['day']} — those overlap.")
                continue
            rest = (starts - ends) / 60
            # A gap under an hour is a break in one long stint, not a
            # turnaround: a split shift is ordinary in retail and the rest rule
            # is not about it.
            if 1.0 <= rest < MIN_REST_HOURS:
                add(employee, "rest_gap",
                    f"{name} finishes {earlier['end']} on {earlier['day']} and "
                    f"starts {later['start']} on {later['day']} — {rest:.1f}h "
                    f"off, under the {MIN_REST_HOURS:.0f}h between shifts.")

    # Hard breaches first, then by person: whoever reads this should meet the
    # thing they cannot override before the things they can.
    found.sort(key=lambda b: (b["overridable"], b["name"], b["rule"]))
    return found


def group_by_employee(breaches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The same list, shaped for a screen that highlights names."""
    people: Dict[str, Dict[str, Any]] = {}
    for breach in breaches:
        entry = people.setdefault(breach["employee_id"], {
            "employee_id": breach["employee_id"],
            "name": breach["name"],
            "breaches": [],
            "has_hard": False,
        })
        entry["breaches"].append(breach)
        if not breach["overridable"]:
            entry["has_hard"] = True
    return sorted(
        people.values(), key=lambda p: (not p["has_hard"], p["name"]),
    )


def blocking(breaches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The ones no password can clear."""
    return [b for b in breaches if not b["overridable"]]
