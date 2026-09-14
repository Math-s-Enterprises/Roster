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
from app.services import hierarchy, rule_parser
from app.services.scheduler import (
    ABSOLUTE_MAX_SHIFT_HOURS,
    covers_closing,
    DAYS,
    MAX_WORKING_DAYS,
    MIN_REST_HOURS,
    MINOR_AGE,
    paid_hours,
    shift_duration_minutes,
    shift_paid_hours,
    shift_span_hours,
    to_minutes,
)

# Breaches that stand whatever the manager says. See the module docstring.
HARD_FLOOR = ("minor_curfew", "double_booked")

# How far below the band is close enough. Half an hour on a 42.5h contract is
# a rounding artefact, not an unused half-day.
CONTRACT_TOLERANCE_HOURS = 0.5


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


def closing_role_breaches(
    shifts: List[Dict[str, Any]],
    *,
    shop: Dict[str, Any],
    employees: List[Dict[str, Any]],
    ai_rules: Optional[List[Dict[str, Any]]] = None,
    week_start: Optional[str] = None,
    holidays: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Trading days where a compiled closing role requirement is unmet."""
    constraints = rule_parser.compiled_constraints(ai_rules or [])
    if not any(
        rule_parser.closing_supervisor_rules(constraints, day) for day in DAYS
    ):
        return []

    by_id = {employee["employee_id"]: employee for employee in employees}
    hours_by_day = {
        row.get("day"): row for row in (shop or {}).get("hours") or []
    }
    closed_dates = set()
    for holiday in holidays or []:
        if holiday.get("scope") != "shop":
            continue
        try:
            start = datetime.strptime(holiday["date"], "%Y-%m-%d").date()
            end = datetime.strptime(
                holiday.get("end_date") or holiday["date"], "%Y-%m-%d"
            ).date()
        except (KeyError, TypeError, ValueError):
            continue
        while start <= end:
            closed_dates.add(start.isoformat())
            start += timedelta(days=1)

    try:
        monday = datetime.strptime(week_start or "", "%Y-%m-%d").date()
        date_for = {
            DAYS[index]: (monday + timedelta(days=index)).isoformat()
            for index in range(7)
        }
    except ValueError:
        date_for = {}

    breaches = []
    for day in DAYS:
        if not rule_parser.closing_supervisor_rules(constraints, day):
            continue
        hours = hours_by_day.get(day)
        if not hours or hours.get("closed") or date_for.get(day) in closed_dates:
            continue
        if (shop or {}).get("open_24h"):
            message = (
                f"The closing role rule cannot apply on {day}: this shop is "
                f"configured as open 24 hours and has no closing time."
            )
        else:
            open_m = to_minutes(hours["open"])
            close_m = to_minutes(hours["close"])
            if close_m <= open_m:
                close_m += 24 * 60

            covered = False
            for shift in _worked(shifts):
                if shift.get("day") != day:
                    continue
                employee = by_id.get(shift.get("employee_id"), {})
                if not hierarchy.is_supervisory(employee.get("role"), shop):
                    continue
                if covers_closing(shift["start"], shift["end"], close_m):
                    covered = True
                    break
            if covered:
                continue
            message = (
                f"Your closing rule requires at least one manager or supervisor "
                f"at {hours['close']} on {day}, but none is rostered then."
            )

        breaches.append({
            "employee_id": None,
            "name": "Closing coverage",
            "rule": "closing_role_requirement",
            "message": message,
            "overridable": True,
        })
    return breaches


def uncovered_hours(
    shifts: List[Dict[str, Any]],
    *,
    shop: Dict[str, Any],
    week_start: Optional[str] = None,
    history_rosters: Optional[List[Dict[str, Any]]] = None,
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
    from app.services.scheduler import _RosterBuilder, previous_week_roster

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
    previous = previous_week_roster(week_start, history_rosters)
    if previous is not None:
        for shift in _worked(previous.get("shifts") or []):
            if shift.get("day") != "sun":
                continue
            for pair in _RosterBuilder.hours_covered("sun", shift["start"], shift["end"]):
                if pair[0] == "mon":
                    on_duty[pair] = on_duty.get(pair, 0) + 1
    for shift in _worked(shifts):
        for pair in _RosterBuilder.hours_covered(
            shift["day"], shift["start"], shift["end"], wrap_week=previous is None,
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
    ai_rules: Optional[List[Dict[str, Any]]] = None,
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
    # THE SHOP'S SETTING, not the module constant.
    #
    # `max_working_days` and `breaks_are_paid` were already read from the
    # shop here; the rest gap was not, so `scheduler.py` built rosters to the
    # shop's figure while this warned against a hardcoded 11. A manager who
    # changed the setting saw the caution stay put for ever and reasonably
    # concluded the page needed refreshing. Two switches that can disagree is
    # one too many (§11).
    #
    # 11 hours is the figure in the Organisation of Working Time Act; the
    # model floors the setting at 10 so a shop cannot quietly go lower still.
    min_rest = float((shop or {}).get("min_rest_hours") or MIN_REST_HOURS)

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
        # NAME THE FIELD, not just the number.
        #
        # Four fields can set this cap — contracted hours, the weekly limit,
        # a term-time limit, a summer-break limit — and the Employees screen
        # calls them all "hours". "against a 20h limit" is true and useless:
        # the manager raised the weekly limit from 20 to 25, came back, saw
        # the same caution, and concluded the page was stale. It was not.
        # That week fell inside the student's summer break, whose own figure
        # was the binding one, and nothing said so.
        cap, cap_source = avail.weekly_hour_cap_explained(employee, week_start)
        if cap and worked_hours > cap + 0.01:
            # Only when the OTHER number differs, so an ordinary hourly
            # employee does not get a clause explaining a distinction that
            # does not apply to them.
            stated = float(employee.get("max_weekly_hours") or 0)
            aside = (
                f" Their weekly limit of {stated:g}h does not apply this week."
                if stated and abs(stated - cap) > 0.01
                and cap_source != "their weekly limit"
                else ""
            )
            add(employee, "weekly_hours",
                f"{name} is rostered {worked_hours:.1f}h against {cap_source} "
                f"of {cap:.0f}h — {worked_hours - cap:.1f}h over.{aside}")

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
            if 1.0 <= rest < min_rest:
                add(employee, "rest_gap",
                    f"{name} finishes {earlier['end']} on {earlier['day']} and "
                    f"starts {later['start']} on {later['day']} — {rest:.1f}h "
                    f"off, under the {min_rest:g}h between shifts.")

    found.extend(closing_role_breaches(
        shifts, shop=shop, employees=employees, ai_rules=ai_rules,
        week_start=week_start, holidays=holidays,
    ))

    # Hard breaches first, then by person: whoever reads this should meet the
    # thing they cannot override before the things they can.
    found.sort(key=lambda b: (b["overridable"], b["name"], b["rule"]))
    return found


def under_contract(
    shifts: List[Dict[str, Any]],
    *,
    employees: List[Dict[str, Any]],
    shop: Dict[str, Any],
    week_start: str,
    holidays: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Salaried staff whose week came in under their contracted minimum.

    Lives here, not in the solver, because the answer changes when the
    MANAGER changes something rather than when the roster changes. Raise
    somebody's contract from 39h to 42.5h and the week they are looking at
    is suddenly short — but the solver ran yesterday, and its stored answer
    still says everybody is fine. §5: a stored figure starts lying the moment
    the data behind it changes.

    The solver calls this too. Two implementations of "who is below their
    band" is the §11 trap, and this is a bad one to get wrong — it would tell
    a manager on the roster page something different from what the generator
    told them, about the same week, with no way to tell which was right.

    Only full-time contracts are checked. Their hours are OWED: the payslip is
    the same whether they work 41 or 42.5, so a short week is money the shop
    paid for and did not use. An hourly contract is a ceiling rather than a
    floor, and reporting against it flagged the whole team every week.

    Measured in hours ON THE FLOOR, breaks included, because that is how the
    contract is written (§8). Comparing a 42.5h contract against paid hours
    would show everybody permanently short by the length of their breaks.

    Anyone with booked leave that week is skipped: a week broken by holiday
    cannot reach the band, and saying so every time buries the cases where
    the shop simply did not roster somebody.
    """
    off_dates = _leave_dates(holidays or [])

    holiday_span: Dict[str, float] = {}
    worked_span: Dict[str, float] = {}
    for shift in shifts:
        employee_id = shift.get("employee_id")
        if not employee_id:
            continue
        if shift.get("paid_holiday"):
            # A holiday day stands in for the shift it replaced, so it counts
            # toward the contract at a normal day's length.
            holiday_span[employee_id] = (
                holiday_span.get(employee_id, 0.0) + shift_paid_hours(shift)
            )
        elif not (shift.get("unpaid_holiday") or shift.get("sick")):
            worked_span[employee_id] = (
                worked_span.get(employee_id, 0.0) + shift_span_hours(shift)
            )

    dates = _week_dates(week_start)

    out: List[Dict[str, Any]] = []
    for employee in hierarchy.display_order(employees, shop):
        employee_id = employee["employee_id"]
        if not avail.is_active(employee):
            continue

        band = avail.contract_span_band(employee)
        if not band:
            continue                       # hourly or student — capped, not targeted

        if off_dates.get(employee_id, set()) & dates:
            continue                       # leave that week; the band is not reachable

        minimum, target = band
        rostered = (
            worked_span.get(employee_id, 0.0) + holiday_span.get(employee_id, 0.0)
        )
        short = minimum - rostered
        if short <= CONTRACT_TOLERANCE_HOURS:
            continue

        out.append({
            "employee_id": employee_id,
            "name": employee.get("name", employee_id),
            "role": employee.get("role", ""),
            "contracted_hours": round(target, 1),
            "minimum_hours": round(minimum, 1),
            "rostered_hours": round(rostered, 1),
            "short_hours": round(short, 1),
        })
    return out


def _week_dates(week_start: str) -> set:
    """The seven ISO dates of a roster week, for matching booked leave."""
    try:
        monday = datetime.strptime(week_start, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return set()
    return {(monday + timedelta(days=n)).isoformat() for n in range(7)}


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
