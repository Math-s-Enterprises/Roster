"""Rules applied to a hand-edited roster.

The generator enforces curfew, hour caps, availability and leave. Manual
editing bypassed every one of them: the save route checked only that a shift
had a sensible length and that nobody appeared twice in a day. A manager
could drag a fifteen-year-old onto a 23:00 shift, or push somebody twelve
hours past their contract, and it saved without a word — which defeats the
point of a tool whose job is to stop exactly that.

Two tiers, because not every rule deserves the same answer:

  BLOCKING   things that are not the manager's to override — the under-16
             curfew, the maximum shift length, rostering somebody who is on
             booked leave. The save is refused.

  WARNING    things a manager may legitimately decide to do — over
             contracted hours, outside somebody's stated availability, a
             shift unlike anything they have worked. The save proceeds and
             the roster records the warning.

Pure: no database, no request. Given the week's inputs it returns a verdict,
so it is exhaustively testable and can be reused by anything that writes
shifts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set

from app.services import availability as avail
from app.services.scheduler import (
    ABSOLUTE_MAX_SHIFT_HOURS,
    DAYS,
    MAX_WORKING_DAYS,
    MINOR_AGE,
    MIN_REST_HOURS,
    paid_hours,
    to_minutes,
    shift_duration_minutes,
    shop_breaks_paid,
    violates_minor_curfew,
)


@dataclass
class Verdict:
    blocking: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocking


def _week_span(day: str, start: str, end: str) -> Optional[tuple]:
    """A shift as minutes from Monday 00:00, so days compare correctly."""
    if day not in DAYS or not (start and end):
        return None
    base = DAYS.index(day) * 24 * 60
    first = base + to_minutes(start)
    last = base + to_minutes(end)
    if last <= first:                     # finishes after midnight
        last += 24 * 60
    return first, last


def _rest_breach(
    shift: Dict[str, Any], others: List[Dict[str, Any]], employee_id: str,
    min_rest: float = MIN_REST_HOURS,
) -> Optional[float]:
    """Hours of rest around this shift, if any neighbour leaves too few.

    `min_rest` is the SHOP's figure. It used to be the module constant, so
    the solver built to the shop's setting while this warned against a
    hardcoded 11 — a manager who changed the setting watched the caution stay
    put and reasonably concluded the page needed refreshing (§11: two
    switches that can disagree is one too many).
    """
    mine = _week_span(shift.get("day"), shift.get("start"), shift.get("end"))
    if not mine:
        return None
    required = min_rest * 60

    for other in others:
        if other.get("employee_id") != employee_id or _is_leave(other):
            continue
        # Two entries on one day are a double-booking, which has its own
        # check and its own message. Rest is about the gap between working
        # days; reporting "1h rest" for a split shift would bury the real
        # problem under a confusing one.
        if other.get("day") == shift.get("day"):
            continue
        theirs = _week_span(other.get("day"), other.get("start"), other.get("end"))
        if not theirs:
            continue
        if mine[0] >= theirs[1]:
            gap = mine[0] - theirs[1]
        elif theirs[0] >= mine[1]:
            gap = theirs[0] - mine[1]
        else:
            continue                      # overlapping; the double-booking
                                          # check has already spoken
        if gap < required:
            return gap / 60
    return None


def _is_leave(shift: Dict[str, Any]) -> bool:
    return bool(
        shift.get("paid_holiday") or shift.get("unpaid_holiday") or shift.get("sick")
    )


def _leave_dates(holidays: Iterable[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """employee_id -> dates they cannot be rostered.

    Mirrors how the solver reads leave, so a shift the generator would never
    have created cannot be introduced by hand either.
    """
    blocked: Dict[str, Set[str]] = {}
    for holiday in holidays:
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
        except (KeyError, ValueError):
            continue
        cursor = start
        while cursor <= end:
            blocked.setdefault(employee_id, set()).add(cursor.isoformat())
            cursor += timedelta(days=1)
    return blocked


def validate_shifts(
    shifts: List[Dict[str, Any]],
    *,
    shop: Dict[str, Any],
    employees: List[Dict[str, Any]],
    holidays: Optional[List[Dict[str, Any]]] = None,
    week_start: str,
    history_rosters: Optional[List[Dict[str, Any]]] = None,
) -> Verdict:
    """Check a proposed week of shifts against the same rules the solver uses."""
    verdict = Verdict()
    by_id = {e["employee_id"]: e for e in employees}
    blocked_dates = _leave_dates(holidays or [])
    shift_history = avail.build_shift_history(history_rosters or [])

    try:
        monday = datetime.strptime(week_start, "%Y-%m-%d").date()
        date_for_day = {DAYS[i]: (monday + timedelta(days=i)).isoformat() for i in range(7)}
    except ValueError:
        date_for_day = {}

    breaks_paid = shop_breaks_paid(shop)
    max_days = int((shop or {}).get("max_working_days") or MAX_WORKING_DAYS)
    min_rest = float((shop or {}).get("min_rest_hours") or MIN_REST_HOURS)
    days_worked: Dict[str, Set[str]] = {}
    seen: Set[tuple] = set()
    worked: Dict[str, float] = {}    # paid hours — an hourly ceiling
    spanned: Dict[str, float] = {}   # hours on the floor — a salaried contract
    # Who has holiday or sickness this week, which is the one reason a
    # salaried week is allowed to come in short.
    on_leave: Dict[str, bool] = {
        employee_id: any(d in dates for d in date_for_day.values())
        for employee_id, dates in blocked_dates.items()
    }

    for shift in shifts:
        employee_id = shift.get("employee_id")
        day = shift.get("day")
        employee = by_id.get(employee_id)
        name = (employee or {}).get("name") or employee_id or "Someone"

        key = (employee_id, day)
        if key in seen:
            verdict.blocking.append(f"{name} is rostered twice on {day}.")
            continue
        seen.add(key)

        if employee is None:
            verdict.blocking.append(
                f"A shift on {day} refers to an employee who no longer exists."
            )
            continue

        date_iso = date_for_day.get(day)
        if date_iso and date_iso in blocked_dates.get(employee_id, set()) and not _is_leave(shift):
            verdict.blocking.append(
                f"{name} is on booked leave on {day} and cannot be given a shift. "
                f"Cancel the leave on the Holidays page first."
            )
            continue

        # Leave carries no times, so nothing below applies to it.
        if _is_leave(shift):
            continue

        start, end = shift.get("start"), shift.get("end")
        if not (start and end):
            verdict.blocking.append(f"{name}'s shift on {day} has no times.")
            continue

        span = shift_duration_minutes(start, end) / 60
        if span <= 0:
            verdict.blocking.append(
                f"{name}'s shift on {day} ({start}–{end}) has no duration."
            )
            continue
        if span > ABSOLUTE_MAX_SHIFT_HOURS:
            verdict.blocking.append(
                f"{name}'s shift on {day} is {span:.1f}h, over the "
                f"{ABSOLUTE_MAX_SHIFT_HOURS}h maximum shift length."
            )
            continue

        # Eleven consecutive hours off between shifts. Measured across days
        # in real time: a night finishing 07:00 Tuesday and a 17:00 Tuesday
        # start is a ten-hour turnaround, not a thirty-four hour one.
        rest = _rest_breach(
            shift, [s for s in shifts if s is not shift], employee_id,
            min_rest,
        )
        if rest is not None:
            verdict.blocking.append(
                f"{name} would get only {rest:.1f}h rest around their {day} "
                f"shift — {min_rest:g}h is required between shifts."
            )
            continue

        if violates_minor_curfew(employee, start, end):
            verdict.blocking.append(
                f"{name} is under {MINOR_AGE}. Their shift on {day} "
                f"({start}–{end}) breaks the 08:00–19:00 curfew."
            )
            continue

        worked[employee_id] = worked.get(employee_id, 0.0) + paid_hours(
            start, end, breaks_paid=breaks_paid
        )
        spanned[employee_id] = spanned.get(employee_id, 0.0) + span
        days_worked.setdefault(employee_id, set()).add(day)

        # A shift unlike anything they have worked is refused. It never bites
        # on a new starter: with no history there is nothing to be unlike, so
        # somebody newly hired can still be rostered anywhere.
        familiarity = avail.check_familiarity(employee, start, end, shift_history)
        if familiarity.warning:
            verdict.blocking.append(f"{day}: {familiarity.warning}")
            continue

        # -- soft rules: the manager may have a reason ---------------------
        window = avail.check_availability(employee, day, start, end)
        if not window.allowed:
            verdict.warnings.append(f"{name} on {day}: {window.reason}")

        if not avail.is_active(employee):
            verdict.warnings.append(
                f"{name} is marked inactive but has a shift on {day}."
            )

    for employee in employees:
        employee_id = employee["employee_id"]
        name = employee.get("name", employee_id)
        band = avail.contract_span_band(employee)

        # Two days off a week, minimum.
        days = len(days_worked.get(employee_id, set()))
        if days > max_days:
            verdict.blocking.append(
                f"{name} would work {days} days this week. The limit is "
                f"{max_days}, so everybody keeps {7 - max_days} days off. "
                f"Remove one of their shifts first."
            )

        if band:
            # Salaried: measured on the floor, breaks included, because that
            # is how the contract is written.
            minimum, target = band
            floor_hours = spanned.get(employee_id, 0.0)
            if floor_hours > target + 0.01:
                verdict.blocking.append(
                    f"{name} would be on the floor {floor_hours:.1f}h against a "
                    f"{target:g}h contract — {floor_hours - target:.1f}h over. "
                    f"Shorten or remove one of their shifts first."
                )
            elif floor_hours and floor_hours < minimum - 0.01 and not on_leave.get(employee_id):
                # Short weeks are only acceptable when holiday or sickness
                # made the band unreachable. Otherwise the shop is paying a
                # full week for less than a full week.
                verdict.blocking.append(
                    f"{name} would be on the floor {floor_hours:.1f}h against a "
                    f"{target:g}h contract — {minimum - floor_hours:.1f}h short of the "
                    f"{minimum:g}h minimum. They are paid the same either way, so give "
                    f"them the hours or book the time as leave."
                )
            continue

        cap = avail.weekly_hour_cap(employee, week_start)
        hours = worked.get(employee_id, 0.0)
        if cap and hours > cap + 0.01:
            # Refused, not warned. Contracted hours are the number the
            # employee agreed to and payroll pays against; a roster that
            # quietly exceeds them is a problem discovered at the till, not
            # a judgement call for the manager to wave through.
            verdict.blocking.append(
                f"{name} would be rostered {hours:.1f}h against a {cap:g}h "
                f"contract — {hours - cap:.1f}h over. "
                f"Shorten or remove one of their shifts first."
            )

    return verdict
