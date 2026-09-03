"""Can this person work this shift, on this date?

Everything that decides an employee's eligibility for a specific shift lives
here, so the answer is computed one way and the reason is always available.

Handled:

  * active / inactive employment
  * advanced availability — earliest start, latest finish, working days,
    preferred shift band
  * student status and term-time hour limits
  * summer-break periods, when a student's cap lifts
  * unfamiliar shift detection — flagging a pattern somebody has never worked

Every check returns a reason string rather than a bare False. A roster that
says "Andi is not available" is useful; one that silently omits Andi is not,
and the manager has no way to tell a rule from a bug.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple

DAYS: Tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Shift bands, by start time. Used for the "preferred shift" setting, which
# is a coarser control than exact times and is what most people actually
# think in.
SHIFT_BANDS = {
    "morning": (0, 12 * 60),        # starts before midday
    "afternoon": (12 * 60, 17 * 60),
    "evening": (17 * 60, 24 * 60),
}

# A pattern must appear at least this often before absence of it counts as
# evidence. Someone who worked one 06:00 shift months ago has not
# established a pattern either way.
FAMILIARITY_MIN_SHIFTS = 8

# How far a start time may differ from anything they have worked before
# without being called unfamiliar. An hour absorbs 07:00 vs 07:30 without
# waving through 06:00 for someone who always starts at 10:00.
FAMILIAR_START_TOLERANCE_MINUTES = 60


def to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


@dataclass
class Eligibility:
    """Whether someone may work a shift, and why not if not."""
    allowed: bool
    reason: Optional[str] = None
    warning: Optional[str] = None   # allowed, but a human should look

    def __bool__(self) -> bool:
        return self.allowed


ALLOWED = Eligibility(True)


# ---------------------------------------------------------------------------
# Employment status
# ---------------------------------------------------------------------------
def is_active(employee: Dict[str, Any]) -> bool:
    """Default True: an employee record with no flag is a working employee.

    Defaulting to False would silently empty the roster of everybody the
    moment this field was introduced.
    """
    return employee.get("is_active", True) is not False


# ---------------------------------------------------------------------------
# Advanced availability
# ---------------------------------------------------------------------------
def _availability(employee: Dict[str, Any]) -> Dict[str, Any]:
    return employee.get("availability") or {}


def check_availability(
    employee: Dict[str, Any], day: str, start: str, end: str
) -> Eligibility:
    """Apply the employee's own availability window to a proposed shift.

    These are hard limits, not preferences: a student who cannot start before
    10:00 genuinely cannot open the shop, and rostering them 06:00-14:00
    produces a schedule that will not happen.
    """
    settings = _availability(employee)
    if not settings:
        return ALLOWED

    name = employee.get("name", "This employee")

    available_days = settings.get("available_days")
    if available_days and day not in available_days:
        return Eligibility(False, f"{name} is not available on {day}.")

    start_m, end_m = to_minutes(start), to_minutes(end)
    # An overnight shift ends the following day; compare its end against the
    # limit on that basis rather than as a smaller number than its start.
    overnight = end_m <= start_m

    earliest = settings.get("earliest_start")
    if earliest and start_m < to_minutes(earliest):
        return Eligibility(
            False, f"{name} cannot start before {earliest} (shift starts {start})."
        )

    latest = settings.get("latest_finish")
    if latest:
        latest_m = to_minutes(latest)
        # 00:00 as a finish means midnight, i.e. the end of the day.
        effective_end = 24 * 60 if (overnight or end_m == 0) else end_m
        effective_latest = 24 * 60 if latest_m == 0 else latest_m
        if effective_end > effective_latest:
            return Eligibility(
                False, f"{name} cannot work past {latest} (shift ends {end})."
            )

    if overnight and not settings.get("can_work_overnight", True):
        return Eligibility(False, f"{name} does not work overnight shifts.")

    preferred = settings.get("preferred_shift")
    if preferred and preferred != "any":
        band = SHIFT_BANDS.get(preferred)
        if band and not (band[0] <= start_m < band[1]):
            # A band mismatch is a preference, not an impossibility — it
            # warns rather than blocks, so cover is never lost over it.
            return Eligibility(
                True,
                warning=f"{name} prefers {preferred} shifts; {start}-{end} is outside that.",
            )

    return ALLOWED


# ---------------------------------------------------------------------------
# Students and summer break
# ---------------------------------------------------------------------------
def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def on_summer_break(employee: Dict[str, Any], on: date) -> bool:
    """Whether a student is inside their configured break period.

    Asks `employment_type`, not the raw `is_student` flag. The flag is the
    older field; the Employees screen now writes employment_type, so a
    student set up through the current interface was never recognised as
    being on a break and kept their term-time cap all year — invisibly,
    because nothing reports a cap that failed to lift.

    employment_type() falls back to is_student, so records written before
    that field existed still behave correctly.
    """
    if employment_type(employee) != "student":
        return False
    break_period = employee.get("summer_break") or {}
    start = _parse_date(break_period.get("start_date"))
    end = _parse_date(break_period.get("end_date"))
    if not (start and end):
        return False
    return start <= on <= end


# A salaried full-timer is contracted to be ON THE FLOOR for this long each
# week — clock in to clock out, breaks included. Deliberately a span figure
# rather than a paid one, because that is how a rota is read and how the
# contract is written. Their payslip is the same whether they land on 41 or
# 42.5, so the band is about honouring the contract, not about pay.
FULL_TIME_SPAN_HOURS = 42.5
# How far under they may fall and still be considered fulfilled.
FULL_TIME_SPAN_TOLERANCE = 1.5


def employment_type(employee: Dict[str, Any]) -> str:
    """'full_time_contract', 'student' or 'hourly'.

    Falls back to the older is_student flag so records written before this
    field existed keep behaving as they did.
    """
    declared = employee.get("employment_type")
    if declared in ("full_time_contract", "student", "hourly"):
        return declared
    return "student" if employee.get("is_student") else "hourly"


def is_full_time_contract(employee: Dict[str, Any]) -> bool:
    return employment_type(employee) == "full_time_contract"


def contract_span_band(employee: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """(minimum, maximum) hours on the floor for a salaried full-timer.

    None for everybody else, whose limit is a paid-hours ceiling rather than
    a band to land inside.
    """
    if not is_full_time_contract(employee):
        return None
    target = float(employee.get("contract_span_hours") or FULL_TIME_SPAN_HOURS)
    tolerance = float(
        employee.get("contract_span_tolerance")
        if employee.get("contract_span_tolerance") is not None
        else FULL_TIME_SPAN_TOLERANCE
    )
    return (max(0.0, target - tolerance), target)


def weekly_hour_cap(employee: Dict[str, Any], week_start: str) -> float:
    """This employee's PAID hour ceiling for the week beginning `week_start`.

    A student's term-time cap is often well below their contract, and lifts
    during the break. Using one flat number would either under-use them all
    summer or over-schedule them during term.

    A salaried full-timer is not governed by this at all — their limit is a
    span band, see contract_span_band — so they get a ceiling high enough
    never to be the binding constraint.
    """
    return weekly_hour_cap_explained(employee, week_start)[0]


def weekly_hour_cap_explained(
    employee: Dict[str, Any], week_start: str
) -> Tuple[float, str]:
    """The cap, and WHICH FIELD it came from, in the manager's words.

    One implementation, two questions — `weekly_hour_cap` is this without the
    explanation. Answering them separately is the §11 trap.

    The explanation exists because four different fields can set this number
    and the Employees screen shows them all as "hours". A manager raised a
    student's `max_weekly_hours` from 20 to 25, came back to the roster, and
    the caution had not moved — correctly, because that week fell inside
    their summer break and the break's own figure was the binding one.
    Nothing on the page said so, so the only available conclusion was that
    the app was stale. It was not; it was silent.

        "Fionn is rostered 22.0h against a 20h limit"

    is true and useless. The manager needs to know WHICH 20h, because that
    is the field they have to edit.
    """
    if is_full_time_contract(employee):
        band = contract_span_band(employee)
        if band:
            return band[1], "their contracted hours"
        return float(employee.get("max_weekly_hours") or 0), "their weekly limit"

    contract = float(employee.get("max_weekly_hours") or 0)
    if employment_type(employee) != "student":
        return contract, "their weekly limit"

    monday = _parse_date(week_start)
    if monday and on_summer_break(employee, monday):
        summer = (employee.get("summer_break") or {}).get("max_weekly_hours")
        if summer:
            return float(summer), "their summer-break limit"
        return contract, "their weekly limit"

    term_time = employee.get("term_time_max_hours")
    if term_time:
        return float(term_time), "their term-time limit"
    return contract, "their weekly limit"


# ---------------------------------------------------------------------------
# Familiarity
# ---------------------------------------------------------------------------
def build_shift_history(
    rosters: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Set[str]]]:
    """employee_id -> {"starts": {...}, "patterns": {...}, "days": {...}}.

    Built once per generation rather than per candidate check, because the
    check runs thousands of times inside the assignment loop.
    """
    history: Dict[str, Dict[str, Set[str]]] = {}
    for roster in rosters:
        for shift in roster.get("shifts", []):
            employee_id = shift.get("employee_id")
            start, end = shift.get("start"), shift.get("end")
            if not (employee_id and start and end):
                continue
            entry = history.setdefault(
                employee_id, {"starts": set(), "patterns": set(), "days": set()}
            )
            entry["starts"].add(start)
            entry["patterns"].add(f"{start}-{end}")
            if shift.get("day"):
                entry["days"].add(shift["day"])
    return history


def check_familiarity(
    employee: Dict[str, Any],
    start: str,
    end: str,
    history: Dict[str, Dict[str, Set[str]]],
) -> Eligibility:
    """Warn when a shift is unlike anything this person has worked.

    Deliberately a warning, never a block. Two reasons: a new employee has no
    history at all, so blocking on unfamiliarity would mean they could never
    be rostered; and a shop short-staffed on a Saturday morning needs the
    option to ask someone to cover an unusual shift, with the manager told
    rather than prevented.
    """
    entry = history.get(employee["employee_id"])
    if not entry:
        # No history is not evidence of unsuitability — it is a new starter.
        return ALLOWED

    total = len(entry["patterns"])
    if total < 1 or sum(1 for _ in entry["starts"]) == 0:
        return ALLOWED

    pattern = f"{start}-{end}"
    if pattern in entry["patterns"]:
        return ALLOWED

    start_m = to_minutes(start)
    closest = min(
        (abs(start_m - to_minutes(s)) for s in entry["starts"]),
        default=None,
    )
    if closest is not None and closest <= FAMILIAR_START_TOLERANCE_MINUTES:
        return ALLOWED

    name = employee.get("name", "This employee")
    usual = sorted(entry["starts"])[:3]
    return Eligibility(
        True,
        warning=(
            f"{name} has no previous {start} start (usually starts "
            f"{', '.join(usual)}). Please confirm this assignment."
        ),
    )


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------
def evaluate(
    employee: Dict[str, Any],
    day: str,
    start: str,
    end: str,
    *,
    history: Optional[Dict[str, Dict[str, Set[str]]]] = None,
) -> Eligibility:
    """Every availability rule for one candidate shift, in priority order."""
    if not is_active(employee):
        return Eligibility(False, f"{employee.get('name', 'Employee')} is not active.")

    verdict = check_availability(employee, day, start, end)
    if not verdict.allowed:
        return verdict

    warning = verdict.warning
    if history is not None:
        familiar = check_familiarity(employee, start, end, history)
        # Keep the availability warning if there is one; an unfamiliar-shift
        # note is the less urgent of the two.
        warning = warning or familiar.warning

    return Eligibility(True, warning=warning)
