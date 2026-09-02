"""The roster solver — the core of the product.

Deliberately pure: no database, no network, no framework imports. It takes
plain dicts in and returns a plain dict out, which means it can be tested
exhaustively without a running server or database. Everything else in the
backend is plumbing around this module.

NON-NEGOTIABLE RULES (enforced here, not configurable by shop owners)
--------------------------------------------------------------------
1. Role priority   — higher-priority roles are always considered first, so
                     they get first claim on available hours.
2. Continuous cover— at least one person is scheduled for every minute the
                     shop is open. No gaps between opening and closing.
3. 24h cover       — for 24-hour shops, the same guarantee applies around
                     the clock, including overnight.
4. Legal limits    — under-16 curfew and weekly hour caps are never relaxed,
                     not even to satisfy rules 2 and 3.

Where rules conflict, rule 4 wins: the solver will report a gap it could not
legally fill rather than schedule someone illegally. Software cannot invent
a legally-eligible employee; that outcome is a staffing problem and is
surfaced as a CRITICAL issue for a human to resolve.
"""
import math
import random
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services import availability as avail
from app.services import hierarchy
from app.services import hours_target
from app.services import slot_owners

DAYS: Tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Fallback ordering for callers that pass no shop. The real ordering is the
# shop's configured role_hierarchy — see services/hierarchy.py — so that a
# business can rename or reorder its job titles without a code change.
ROLE_PRIORITY: Dict[str, int] = {
    "Manager": 0,
    "Supervisor": 1,
    "Cashier": 2,
    "Floor Assistant": 3,
    "Stocker": 4,
}
_UNRANKED_ROLE = 99

SUPERVISORY_ROLES = ("Manager", "Supervisor")

# Statutory limits. Constants rather than magic numbers so the legal basis
# is greppable and changeable in exactly one place.
MINOR_AGE = 16

# Nobody works more than five days in a week, so everybody gets two off.
MAX_WORKING_DAYS = 5
MINOR_EARLIEST_START = "08:00"
MINOR_LATEST_END = "19:00"

# The longest single shift anyone may be given, whatever the shop's own
# max_shift_hours says — every use is `min(shop setting, this)`.
#
# Was 11, which looks like it came from the 11-hour daily REST entitlement in
# the Organisation of Working Time Act 1997. That is a different quantity: 11
# consecutive hours off in each 24 implies up to 13 hours worked, not 11. Set
# to 12 at the shop's request, which leaves the rest period intact (12 worked
# + 11 off = 23 of 24).
ABSOLUTE_MAX_SHIFT_HOURS = 12

# Consecutive hours off between finishing one shift and starting the next.
# The daily rest entitlement in the Organisation of Working Time Act, and the
# shop's own health and safety rule.
#
# Checked against 30 weeks of the manager's real rosters before being made a
# constraint: 2009 consecutive pairs, 8 under eleven hours — 99.6%. Practice
# already followed it, so enforcing it cannot stop the solver reproducing the
# history it learns from.
MIN_REST_HOURS = 11.0

# Distinguishes "not computed yet" from "computed, and the answer is None".
_UNSET = object()

# Sorts after anybody who has actually worked a slot. Must not be derived
# from how many people are ranked — with one ranked person that number is 1,
# which ties them with everybody who has never worked it.
_UNRANKED_FOR_SLOT = 9_999


# ---------------------------------------------------------------------------
# Time helpers — the solver works in integer minutes-since-midnight, which
# makes all arithmetic trivial compared with string or datetime juggling.
# ---------------------------------------------------------------------------
def to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def to_hhmm(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def shift_duration_minutes(start: str, end: str) -> int:
    """Length of a shift, correctly handling the overnight wrap.

    23:00->07:00 is 8 hours, not -16. A shift whose start equals its end is
    treated as zero-length (invalid) rather than a full 24 hours, which is
    the more useful reading of what is almost certainly a data-entry error.
    """
    start_m, end_m = to_minutes(start), to_minutes(end)
    if end_m == start_m:
        return 0
    return end_m - start_m if end_m > start_m else (24 * 60 - start_m) + end_m


def _crosses_midnight(start: str, end: str) -> bool:
    return to_minutes(end) <= to_minutes(start)


# ---------------------------------------------------------------------------
# Breaks
# ---------------------------------------------------------------------------
# Unpaid break entitlement by shift length. Each entry is
# (minimum shift hours, unpaid break minutes), longest first so the first
# match wins.
#
# Breaks are NOT working time, so a contracted 40-hour week is 40 hours of
# *paid* time and the roster has to span longer than that to deliver it — a
# 10-hour shift with an hour of breaks pays 9. Treating span as paid time
# silently short-changes everyone by roughly 10%.
BREAK_SCHEDULE: Tuple[Tuple[float, int], ...] = (
    (10.0, 60),   # two 30-minute breaks
    (8.0, 45),    # 30 + 15
    (6.0, 30),
    (5.0, 15),
)


def break_minutes(span_hours: float) -> int:
    """Unpaid break for a shift of this length."""
    for threshold, minutes in BREAK_SCHEDULE:
        if span_hours >= threshold:
            return minutes
    return 0


def shift_paid_hours(shift: Dict[str, Any]) -> float:
    """Paid hours for a stored shift, whatever shape it is in.

    Handles three cases: entries that already carry `paid_hours` (everything
    the current solver writes), paid-holiday entries which have no times at
    all, and older rosters written before breaks were modelled.
    """
    if shift.get("paid_hours") is not None:
        return float(shift["paid_hours"])
    start, end = shift.get("start") or "", shift.get("end") or ""
    if not start or not end:
        return 0.0
    return paid_hours(start, end)


def paid_hours(start: str, end: str, *, breaks_paid: bool = False) -> float:
    """Hours actually paid: the shift's span, less its break if unpaid.

    This is what drives labour cost. Coverage still uses the full span,
    because somebody on a break is still on the premises — modelling exactly
    when each break falls is more precision than a weekly roster can carry.

    `breaks_paid` is a per-shop choice: some shops pay through breaks and
    some do not, and it changes every wage figure in the app. It does NOT
    change a full-time contract, which is written in span hours either way.
    """
    span = shift_duration_minutes(start, end) / 60
    if breaks_paid:
        return max(0.0, span)
    return max(0.0, span - break_minutes(span) / 60)


def shop_breaks_paid(shop: Optional[Dict[str, Any]]) -> bool:
    return bool((shop or {}).get("breaks_are_paid"))


def shift_span_hours(shift: Dict[str, Any]) -> float:
    """Hours on the floor for a stored shift — clock in to clock out.

    What a full-time contract is measured against, and what a rota sheet
    shows. Leave entries have no span: somebody on holiday is not present.
    """
    if shift.get("paid_holiday") or shift.get("unpaid_holiday") or shift.get("sick"):
        return 0.0
    if shift.get("span_hours") is not None:
        return float(shift["span_hours"])
    start, end = shift.get("start") or "", shift.get("end") or ""
    if not (start and end):
        return 0.0
    return shift_duration_minutes(start, end) / 60


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------
def collapse_hour_runs(
    gaps: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge consecutive uncovered hours on a day into one span.

    Six lines saying 17:00-18:00, 18:00-19:00 ... 22:00-23:00 describe one
    hole in the evening, and reading them as six problems is exactly the
    wrong impression: the manager needs one person for one stretch, not six
    decisions. `compare_to_usual` already collapses runs for the same reason
    (§7c) and the advisories now do too; this was the last per-hour list.

    Grouped by the REASON as well as the day, so "nobody could work this
    because Emma is on leave" and "nobody could work this because everyone
    is at their cap" stay separate sentences even when the hours touch —
    they are different problems with different fixes.

    Returns {day, from_hour, to_hour, window, hours, because}.
    """
    runs: List[Dict[str, Any]] = []
    for day in DAYS:
        current: Optional[Dict[str, Any]] = None
        for gap in sorted(
            (g for g in gaps if g.get("day") == day),
            key=lambda g: g.get("hour", 0),
        ):
            hour, because = gap.get("hour", 0), gap.get("because", "")
            if (current
                    and current["to_hour"] == hour
                    and current["because"] == because):
                current["to_hour"] = hour + 1
                current["hours"] += 1
                continue
            if current:
                runs.append(current)
            current = {
                "day": day, "from_hour": hour, "to_hour": hour + 1,
                "hours": 1, "because": because,
            }
        if current:
            runs.append(current)

    for run in runs:
        run["window"] = (
            f"{run['from_hour']:02d}:00-{run['to_hour'] % 24:02d}:00"
        )
    return runs


@dataclass
class Segment:
    """A block of time that must be staffed."""
    start: str
    end: str
    name: str = "Coverage"
    min_staff: int = 1
    template_id: Optional[str] = None

    @property
    def span_hours(self) -> float:
        """Clock length of the shift, including unpaid break time."""
        return shift_duration_minutes(self.start, self.end) / 60

    @property
    def duration_hours(self) -> float:
        """Paid hours — what counts against an employee's contract."""
        return paid_hours(self.start, self.end)


@dataclass
class SolveResult:
    shifts: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    critical_issues: List[str] = field(default_factory=list)
    compliance_score: int = 100
    labor_cost: float = 0.0
    total_hours: float = 0.0
    utilization: float = 0.0
    per_employee_hours: Dict[str, float] = field(default_factory=dict)
    # Every active employee who received no shifts, with the reason. Rule:
    # nobody is silently left off a roster.
    unrostered: List[Dict[str, str]] = field(default_factory=list)
    # Assignments that are legal but unlike anything the person has worked
    # before. Kept apart from `issues` so the manager sees a short list of
    # things to actively confirm rather than hunting through general advice.
    confirmations: List[Dict[str, str]] = field(default_factory=list)
    # Hours the solver could not staff without breaking a rule. Left empty
    # and reported rather than filled with somebody unsuitable — a blank the
    # manager can see and decide about beats a shift that will not happen.
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    # Days staffed by fewer people than the shop normally uses, even if the
    # hourly curve is satisfied. A handful of long shifts can cover every
    # hour and still leave a Sunday feeling empty.
    thin_days: List[Dict[str, Any]] = field(default_factory=list)
    # Contracted staff who finished the week below their hours. Contracted
    # hours are owed, not merely permitted, so falling short is reported
    # rather than left to be discovered on a payslip.
    under_contract: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shifts": self.shifts,
            "issues": self.issues,
            "critical_issues": self.critical_issues,
            "unrostered": self.unrostered,
            "confirmations": self.confirmations,
            "gaps": self.gaps,
            "thin_days": self.thin_days,
            "under_contract": self.under_contract,
            "compliance_score": self.compliance_score,
            "labor_cost": round(self.labor_cost, 2),
            "total_hours": round(self.total_hours, 1),
            "utilization": round(self.utilization, 1),
            "per_employee_hours": {k: round(v, 1) for k, v in self.per_employee_hours.items()},
        }


# ---------------------------------------------------------------------------
# Segment planning
# ---------------------------------------------------------------------------
def build_segments(shop: Dict[str, Any], open_m: int, close_m: int) -> List[Segment]:
    """Split a day's opening hours into back-to-back segments covering it all.

    Two constraints must hold simultaneously:
      * the segments must tile the whole open period with no gaps (rule 2);
      * no segment may exceed the shop's max shift length or the absolute
        ceiling of ABSOLUTE_MAX_SHIFT_HOURS (rule 4).

    Naively cutting fixed max-length blocks leaves a short remainder, and
    the obvious fixes are both wrong: dropping it leaves the end of the day
    uncovered, while merging it into the previous block produces an
    over-length shift. Dividing the day into equal parts satisfies both —
    e.g. a 12-hour day with a 9-hour cap becomes 2x6h, never 9h + 3h.
    """
    max_len = max(1, int(min(shop.get("max_shift_hours", 9), ABSOLUTE_MAX_SHIFT_HOURS) * 60))
    total = close_m - open_m
    if total <= 0:
        return []
    if total <= max_len:
        return [Segment(start=to_hhmm(open_m), end=to_hhmm(close_m))]

    segment_count = -(-total // max_len)  # ceil division
    base_length, remainder = divmod(total, segment_count)

    segments: List[Segment] = []
    cursor = open_m
    for index in range(segment_count):
        # Spread the remainder one minute at a time so lengths differ by at
        # most a minute and the segments still tile the day exactly.
        length = base_length + (1 if index < remainder else 0)
        segments.append(Segment(start=to_hhmm(cursor), end=to_hhmm(cursor + length)))
        cursor += length
    return segments


def segments_for_day(shop: Dict[str, Any], open_m: int, close_m: int) -> List[Segment]:
    """Explicit templates win; otherwise derive segments from opening hours."""
    templates = shop.get("shift_templates") or []
    if templates:
        return [
            Segment(
                start=t["start"],
                end=t["end"],
                name=t.get("name") or "Shift",
                min_staff=max(1, int(t.get("min_staff", 1))),
                template_id=t.get("template_id"),
            )
            for t in templates
        ]
    return build_segments(shop, open_m, close_m)


# ---------------------------------------------------------------------------
# Constraint checks
# ---------------------------------------------------------------------------
def violates_minor_curfew(employee: Dict[str, Any], start: str, end: str) -> bool:
    if employee.get("age", 99) >= MINOR_AGE:
        return False
    if _crosses_midnight(start, end):
        return True  # a minor may never work an overnight shift
    return (
        to_minutes(start) < to_minutes(MINOR_EARLIEST_START)
        or to_minutes(end) > to_minutes(MINOR_LATEST_END)
    )


def _matching_custom_rule(
    constraints: List[Dict[str, Any]],
    employee_id: str,
    day: str,
    start_m: int,
    end_m: int,
    open_m: int,
    close_m: int,
) -> Optional[Dict[str, Any]]:
    """First compiled custom rule this assignment would break, if any."""
    for rule in constraints:
        target_ids = rule.get("employee_ids") or []
        if target_ids and employee_id not in target_ids:
            continue
        target_days = [d.lower()[:3] for d in (rule.get("days") or [])]
        if target_days and day not in target_days:
            continue

        rule_type = (rule.get("type") or "").lower()
        if rule_type == "no_day":
            return rule
        if rule_type == "no_close" and end_m >= close_m - 30:
            return rule
        if rule_type == "no_open" and start_m <= open_m + 30:
            return rule
        # max_staff and not_together depend on who else is already placed,
        # so they are checked by the builder rather than here.
    return None


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------
class _RosterBuilder:
    """Mutable state for one solve. Kept in a class so the helper methods
    don't need to thread a dozen parameters through every call."""

    # Does the owner of a slot outrank a full-timer who is below their band?
    #
    # This is the single most consequential ordering decision in the solver
    # (CLAUDE.md §2b) and it was argued both ways before landing on True. It
    # is a class attribute rather than a bare `0 if ...` so the decision can
    # be turned OFF and the same week re-solved — which is the only way to
    # answer "is anybody short BECAUSE an owner kept their shift?" rather
    # than guessing. `ml/check_contract_cost.py` flips it.
    #
    # Production must never set this to False. Contract need is reached by
    # _top_up_contracts afterwards; taking a settled shift to reach it costs
    # the manager an edit and buys the contract nothing.
    OWNER_BEATS_CONTRACT = True

    def __init__(
        self,
        shop: Dict[str, Any],
        employees: List[Dict[str, Any]],
        holidays: List[Dict[str, Any]],
        fixed_shifts: List[Dict[str, Any]],
        ai_rules: List[Dict[str, Any]],
        week_start: str,
        weights: Dict[str, Any],
        demand: Optional[Any] = None,
        history_rosters: Optional[List[Dict[str, Any]]] = None,
        locked_shifts: Optional[List[Dict[str, Any]]] = None,
        seed: Optional[int] = None,
        only_day: Optional[str] = None,
    ):
        # Re-solve ONE day and leave the rest of the week exactly as it is.
        #
        # "Two people called in sick on Wednesday" does not want the whole
        # week rearranged — every other day that moves is a change the manager
        # has to read, understand and mostly undo. The other days are handed
        # in as locked shifts, so their hours still count against everybody's
        # weekly cap and five-day limit; this flag additionally stops the fill
        # passes adding anything new to them.
        self.only_day = only_day
        # A seed makes Regenerate offer a DIFFERENT arrangement of the shifts
        # nobody has a claim on, while leaving settled shifts alone. Without
        # one the solve is exactly as deterministic as it always was.
        #
        # Regenerate used to be a button that provably did nothing: same
        # inputs, same roster, so pressing it sixteen times saved sixteen
        # identical weeks. But the fix is not to shuffle everything — a
        # reshuffled roster hands back the 06:00 opening somebody has worked
        # for months, and every one of those is an edit the manager has to
        # undo. Only genuinely arbitrary choices are varied. See _pick_for_slot.
        self.rng = random.Random(seed) if seed is not None else None

        # Shifts the manager placed by hand. Laid down before anything else
        # and never moved, lengthened or trimmed — the whole point of
        # rebalancing is that your decisions survive and everybody else
        # rearranges around them.
        self.locked_by_day: Dict[str, List[Dict[str, Any]]] = {}
        for shift in locked_shifts or []:
            if shift.get("day") and shift.get("start") and shift.get("end"):
                self.locked_by_day.setdefault(shift["day"], []).append(shift)

        self.shop = shop
        self.employees = employees
        self.employees_by_id = {e["employee_id"]: e for e in employees}
        self.weights = weights or {}
        self.week_start = week_start
        # A DemandProfile (app.services.demand). Optional so the solver stays
        # importable and testable without it; when absent, one is derived from
        # the shop's opening hours.
        self.demand = demand

        # Default on: a requested day off is honoured absolutely. Shops that
        # would rather stay covered can turn it off in their settings.
        self.strict_days_off = shop.get("strict_days_off", True)

        # Configured job ladder, used both for who is considered first and
        # for the order rows appear in every view and export.
        self.role_ranks = hierarchy.rank_map(shop)

        # Shift history, for spotting assignments unlike anything a person
        # has worked before. Built once — the check runs thousands of times.
        self.shift_history = avail.build_shift_history(history_rosters or [])
        # Who normally works each shift. Built once per solve — it is asked
        # for every slot on every day.
        # Leavers keep their history but lose their claim: see build_owners.
        #
        # `known_shapes` lets an EXTRA count toward ownership, but only on a
        # shape the demand profile has already settled on as a real slot. A
        # shift the manager adds week after week eventually earns its place
        # in `day_slots` on its own frequency, and from then on the app can
        # learn whose it is. A one-off extra never creates an owner of a slot
        # that does not exist — which would turn "as well as" into "instead
        # of" (§2d).
        self.slot_owners = slot_owners.build_owners(
            history_rosters or [],
            {e["employee_id"] for e in employees if avail.is_active(e)},
            known_shapes={
                (day, start, end)
                for day in DAYS
                for start, end in (demand.slots_for(day) if demand else [])
            } or None,
        )

        # Why each employee ended up with no shifts. Every active employee
        # must be accounted for, so "not rostered" always has a stated
        # reason rather than being a silent omission.
        self.exclusions: Dict[str, str] = {}

        self.hours_by_day = {h["day"]: h for h in shop.get("hours", [])}
        (
            self.shop_closed_dates,
            self.employee_off_dates,
            self.paid_leave_dates,
        ) = self._index_holidays(holidays)
        self.fixed_by_employee_day = self._index_fixed_shifts(fixed_shifts)
        self.custom_constraints = [
            r["compiled"] for r in ai_rules
            if r.get("compiled") and r.get("approved", True)
        ]
        # Rules the solver cannot read do nothing. Silently ignoring them is
        # how somebody writes a rule, sees it listed as enabled, and gets a
        # roster that breaks it — so they are named instead.
        self.inactive_rules = [
            r.get("title") or "(untitled rule)"
            for r in ai_rules
            if not r.get("locked")
            and r.get("enabled", True)
            and not (r.get("compiled") and r.get("approved", True))
        ]

        start_date = datetime.strptime(week_start, "%Y-%m-%d").date()
        self.date_for_day = {
            DAYS[i]: (start_date + timedelta(days=i)).isoformat() for i in range(7)
        }

        # Weekly cap per person for THIS week. A student's ceiling differs
        # in term time and during their summer break, so it cannot be read
        # straight off the contract.
        self.hour_caps: Dict[str, float] = {
            e["employee_id"]: avail.weekly_hour_cap(e, week_start) for e in employees
        }

        # A salaried full-timer's contract is written in hours ON THE FLOOR,
        # breaks included, so their limit is a span band rather than a paid
        # ceiling. Everybody else is capped on paid hours as before.
        self.span_bands: Dict[str, Optional[Tuple[float, float]]] = {
            e["employee_id"]: avail.contract_span_band(e) for e in employees
        }
        self.breaks_paid = shop_breaks_paid(shop)

        # Nobody works more than this many days in a week, so everybody gets
        # at least two off. Configurable, because a shop may run a different
        # pattern, but five is the rule until told otherwise.
        self.max_working_days = int(shop.get("max_working_days") or MAX_WORKING_DAYS)

        # What a normal week currently looks like for each hourly employee.
        # Built last, because it needs the caps, the bands, the day limit and
        # the leave index above it.
        #
        # Derived every solve, never stored (§5): a cached copy would keep
        # describing somebody's old pattern after they changed it, which is
        # the exact failure this is meant to fix.
        self.hours_aim: Dict[str, float] = self._build_hours_aim(
            history_rosters)

        self.result = SolveResult()
        self.hours_used: Dict[str, float] = {e["employee_id"]: 0.0 for e in employees}
        self.span_used: Dict[str, float] = {e["employee_id"]: 0.0 for e in employees}
        self.days_worked: Dict[str, Set[str]] = {
            e["employee_id"]: set() for e in employees
        }

        # Live coverage counters, rebuilt as shifts are assigned.
        #   on_duty[day][hour]              -> total people on the floor
        #   role_on_duty[day][role][hour]   -> people of that role on the floor
        # Hours already reported as short, so the demand loop and the
        # coverage-floor pass cannot both report the same one.
        self.reported_gaps: Set[Tuple[str, int]] = set()
        self._shortfall_cache: Any = _UNSET
        self.min_rest_hours = float(
            (shop or {}).get("min_rest_hours") or MIN_REST_HOURS
        )

        # Who already has a shift on each day. Held on the builder because
        # the coverage pass can place a shift on a day other than the one it
        # is currently repairing.
        self.assigned_by_day: Dict[str, Set[str]] = {}

        # Who a strict day off was genuinely keeping off each day, snapshotted
        # while that day is filled rather than at the end of the week.
        self.blocked_by_day: Dict[str, List[str]] = {}

        self.on_duty: Dict[str, List[int]] = {d: [0] * 24 for d in DAYS}
        self.role_on_duty: Dict[str, Dict[str, List[int]]] = {
            d: defaultdict(lambda: [0] * 24) for d in DAYS
        }

        # Coverage carried in from the week before. Somebody working
        # 22:00-06:00 last Sunday is standing in the shop until 06:00 this
        # Monday, so those hours are already covered — reporting them as a
        # gap is a false alarm, and trying to fill them wastes staff on a
        # slot that is not empty.
        self.carried_in = self._seed_carry_in(history_rosters or [])

        # With a real previous week there is nothing to assume: this week's
        # own Sunday night belongs to NEXT Monday and is not counted here.
        # Without one — a brand-new shop, or a week generated out of order —
        # fall back to treating the rota as repeating, so the first week does
        # not report a phantom gap before opening on Monday.
        self.wrap_week = self.carried_in == 0

    def _seed_carry_in(self, history: List[Dict[str, Any]]) -> int:
        """Credit Monday's small hours to last Sunday's night shift.

        Reads the approved roster for the week immediately before this one.
        Only Sunday shifts can spill past the week boundary, and only paid
        working shifts count — somebody on holiday covers nothing.
        """
        try:
            previous_week = (
                datetime.strptime(self.week_start, "%Y-%m-%d").date() - timedelta(days=7)
            ).isoformat()
        except ValueError:
            return 0

        previous = next(
            (r for r in history if r.get("week_start") == previous_week), None
        )
        if not previous:
            return 0

        seeded = 0
        for shift in previous.get("shifts", []):
            if shift.get("day") != "sun":
                continue
            if shift.get("paid_holiday") or shift.get("unpaid_holiday") or shift.get("sick"):
                continue
            start, end = shift.get("start"), shift.get("end")
            if not (start and end):
                continue

            role = self.employees_by_id.get(
                shift.get("employee_id"), {}
            ).get("role") or ""
            for covered_day, hour in self.hours_covered("sun", start, end):
                if covered_day != "mon":
                    continue
                self.on_duty["mon"][hour] += 1
                if role:
                    self.role_on_duty["mon"][role][hour] += 1
                seeded += 1
        return seeded

    # -- indexing ---------------------------------------------------------
    @staticmethod
    def _date_range(holiday: Dict[str, Any]) -> Set[str]:
        start = datetime.strptime(holiday["date"], "%Y-%m-%d").date()
        end = datetime.strptime(holiday.get("end_date") or holiday["date"], "%Y-%m-%d").date()
        dates, cursor = set(), start
        while cursor <= end:
            dates.add(cursor.isoformat())
            cursor += timedelta(days=1)
        return dates

    def _index_holidays(self, holidays):
        """Split leave into 'cannot be rostered' and 'paid holiday taken'.

        Both block scheduling, but only paid holiday appears on the roster and
        draws down entitlement — so they are tracked separately rather than
        collapsed into one set.
        """
        shop_closed: Set[str] = set()
        employee_off: Dict[str, Set[str]] = {}
        paid_leave: Dict[str, Dict[str, Dict[str, Any]]] = {}

        for holiday in holidays:
            scope = holiday.get("scope")
            dates = self._date_range(holiday)

            if scope == "shop":
                shop_closed |= dates
                continue

            employee_id = holiday.get("employee_id")
            if not employee_id or scope not in ("employee", "unavailable", "sick"):
                continue

            employee_off.setdefault(employee_id, set()).update(dates)

            # Only 'employee' scope is paid holiday. 'unavailable' is unpaid
            # and 'sick' is handled by its own policy, so neither is recorded
            # as holiday taken.
            if scope == "employee":
                for date_iso in dates:
                    paid_leave.setdefault(employee_id, {})[date_iso] = holiday

        return shop_closed, employee_off, paid_leave

    @staticmethod
    def _index_fixed_shifts(fixed_shifts):
        mapping: Dict[str, Dict[str, Tuple[str, str]]] = {}
        for fixed in fixed_shifts:
            for day in fixed.get("days", []):
                mapping.setdefault(fixed["employee_id"], {})[day] = (fixed["start"], fixed["end"])
        return mapping

    # -- scoring ----------------------------------------------------------
    def _rank(self, employee: Dict[str, Any], segment_key: str, day: str) -> Tuple[int, float]:
        """Sort key: role priority first (RULE 1), learned affinity second.

        Used when there is no demand profile — seniority strictly first.
        """
        role_rank = hierarchy.rank_of(employee.get("role"), self.role_ranks)
        template_affinity = (
            self.weights.get("tpl", {}).get(employee["employee_id"], {}).get(segment_key, 0)
        )
        day_affinity = self.weights.get("day", {}).get(employee["employee_id"], {}).get(day, 0)
        return (role_rank, -(template_affinity * 2 + day_affinity))

    def _rank_for_demand(
        self,
        employee: Dict[str, Any],
        pattern_key: str,
        day: str,
        hours: List[int],
    ) -> Tuple[float, int, float, int, float]:
        """Sort key when a demand profile is driving the roster.

        Ordering: role deficit, then whether the shift is one they actually
        work, then hours fairness, then seniority, then learned affinity.
        Lower sorts first.

        RULE 1 still holds, but at the right scope. Seniority decides who gets
        hours across the week; role deficit decides which role fills a given
        hour. Once managers have met their target for 13:00, another manager
        scores below a floor assistant *for that hour* — while a manager still
        beats a floor assistant whenever both roles are equally short.

        Familiarity sits second because it was previously nowhere: the solver
        chose somebody and only then asked whether the shift was unlike
        anything they had worked, which is too late to act on. A night worker
        would be handed a 06:00 start while somebody who works mornings every
        week sat available. Ranking on it means an unfamiliar assignment
        happens only when nobody familiar is left — which is exactly when the
        warning is worth reading.

        It ranks BELOW role deficit deliberately. Covering the hour with the
        right role still matters more than everyone having a comfortable
        shift; familiarity breaks the tie, it does not overrule coverage.
        """
        role = employee.get("role") or ""
        role_rank = hierarchy.rank_of(role, self.role_ranks)

        # Negative deficit sorts first, so the most under-target role wins.
        deficit = -self._role_deficit(day, hours, role)

        template_affinity = (
            self.weights.get("tpl", {}).get(employee["employee_id"], {}).get(pattern_key, 0)
        )
        day_affinity = self.weights.get("day", {}).get(employee["employee_id"], {}).get(day, 0)

        return (
            deficit,
            self._unfamiliarity(employee, pattern_key),
            self._fill_ratio(employee),
            role_rank,
            -(template_affinity * 2 + day_affinity),
        )

    def _unfamiliarity(self, employee: Dict[str, Any], pattern_key: str) -> int:
        """0 if this is a shift they work, 1 if it would be a new shape.

        A new starter scores 0, not 1: having no history is not evidence of
        unsuitability, and penalising it would leave them last in every
        queue and effectively unrosterable.
        """
        try:
            start, end = pattern_key.split("-", 1)
        except ValueError:
            return 0
        return 1 if avail.check_familiarity(
            employee, start, end, self.shift_history
        ).warning else 0

    def _fill_ratio(self, employee: Dict[str, Any]) -> float:
        """How much of this person's contracted week is already rostered.

        Ranking on this spreads work the way a manager does instinctively.
        Without it the greedy loop keeps returning to whoever it ranked first
        until they hit their cap, then moves down the list — which produced
        rosters with three people pinned at 40h while four got nothing at all.

        Banded rather than continuous: comparing raw ratios would make a
        person on 12.0h always outrank one on 12.5h, letting a rounding
        difference override seniority entirely. Bands of 12.5% mean fairness
        decides only when two people are meaningfully differently loaded, and
        seniority still breaks ties within a band.
        """
        capacity = employee.get("max_weekly_hours") or 0
        if capacity <= 0:
            return 1.0  # no capacity recorded — treat as fully loaded
        ratio = self.hours_used.get(employee["employee_id"], 0.0) / capacity
        return round(ratio * 8) / 8

    def _role_deficit(self, day: str, hours: List[int], role: str) -> float:
        """How far below its learned target this role is, across `hours`.

        Positive means under-staffed for that role, so adding one helps.
        Zero or negative means the role is already at or over target, and the
        slot is better given to someone else.
        """
        if not self.demand or not role:
            return 0.0

        # Measured as a FRACTION of the role's target, not as a raw count.
        #
        # Raw counts hand every slot to whichever role has the most people.
        # A shop needing eight floor assistants and one supervisor gives the
        # assistants a shortfall of 0.8 and the supervisor 0.1, so the
        # supervisor loses every comparison and is never rostered at all —
        # which is why days kept coming out with nobody senior on them.
        #
        # As a fraction, both start 100% short, the tie falls to seniority,
        # and once the supervisor is on the floor their fraction drops below
        # the assistants' and the rest of the day fills normally.
        deficit = 0.0
        counted = 0
        for hour in hours:
            target = self.demand.role_target(day, hour, role)
            if target <= 0:
                continue
            counted += 1
            deficit += (target - self.role_on_duty[day][role][hour]) / target
        return deficit / max(1, counted)

    # -- eligibility ------------------------------------------------------
    def _is_eligible(
        self,
        employee: Dict[str, Any],
        segment: Segment,
        day: str,
        date_iso: str,
        assigned_today: Set[str],
        open_m: int,
        close_m: int,
        *,
        relax_preferences: bool,
    ) -> bool:
        """Checked in the documented priority order, hardest limits first.

        Each rejection records a reason against the employee, so a person who
        ends the week with no shifts can always be explained rather than
        having silently vanished from the roster.
        """
        employee_id = employee["employee_id"]

        # 1. Active employment.
        if not avail.is_active(employee):
            self._note_exclusion(employee_id, "No longer an active employee.")
            return False

        if employee_id in assigned_today:
            return False  # no double-booking within a day

        # 2b. Two days off a week, minimum. A hard rule everywhere, and one
        # the solver had no notion of — it would happily give somebody all
        # seven days if their hours allowed it.
        worked = self.days_worked.get(employee_id, set())
        if day not in worked and len(worked) >= self.max_working_days:
            self._note_exclusion(
                employee_id,
                f"Already working {len(worked)} days — the limit is "
                f"{self.max_working_days}, so they keep "
                f"{7 - self.max_working_days} days off.",
            )
            return False

        # 3. Approved leave.
        if date_iso in self.employee_off_dates.get(employee_id, set()):
            return False  # never relaxed

        # 4/5. Availability and advanced availability — hard limits. Someone
        # who cannot start before 10:00 genuinely cannot open the shop.
        verdict = avail.check_availability(employee, day, segment.start, segment.end)
        if not verdict.allowed:
            self._note_exclusion(employee_id, verdict.reason or "Unavailable.")
            return False

        # 6/7. Weekly limit. For a salaried full-timer that is a span ceiling
        # — 42.5 hours on the floor — because their contract is written that
        # way and their pay does not move with it. For everybody else it is a
        # paid-hours cap, which for a student varies with term and break.
        band = self.span_bands.get(employee_id)
        if band:
            span = shift_duration_minutes(segment.start, segment.end) / 60
            if self.span_used[employee_id] + span > band[1] + 1e-6:
                self._note_exclusion(
                    employee_id,
                    f"Would exceed their {band[1]:g}h contracted hours.",
                )
                return False
        else:
            cap = self.hour_caps.get(employee_id, employee.get("max_weekly_hours", 0))
            if self.hours_used[employee_id] + segment.duration_hours > cap:
                self._note_exclusion(
                    employee_id,
                    f"Would exceed their {cap:g}h weekly limit.",
                )
                return False

        # 7b. Rest between shifts. Eleven consecutive hours off in each 24 is
        # the daily rest entitlement in the Organisation of Working Time Act,
        # and the shop's own health and safety rule.
        #
        # Measured in real time, not clock time: a 23:30-07:00 night finishes
        # on the FOLLOWING day, so a 17:00 start that day is a ten-hour
        # turnaround. Comparing bare clock values would read it as thirty-four
        # and wave it through — which is exactly the case the rule exists for.
        short_rest = self._rest_breach(employee_id, day, segment.start, segment.end)
        if short_rest is not None:
            self._note_exclusion(
                employee_id,
                f"Only {short_rest:.1f}h rest since their last shift — "
                f"{self.min_rest_hours:g}h is required.",
            )
            return False

        # 8. Familiarity. Absolute: somebody who has never worked this shift
        # is not offered it, no matter how short the day is.
        #
        # `relax_preferences` deliberately does NOT lift this. It relaxes a
        # preferred DAY OFF, which is a different thing entirely — asking a
        # 06:00 person to come in on their Sunday off is what a manager
        # actually does, whereas putting a night worker on a 06:00 start is
        # not. Sharing one flag between the two meant the coverage floor did
        # the second when the first was available, which is how Kelvin and
        # Azaryia ended up opening the shop.
        #
        # Never bites on a new starter: check_familiarity treats no history
        # as no objection, so somebody newly hired can still be rostered.
        familiar = avail.check_familiarity(
            employee, segment.start, segment.end, self.shift_history
        )
        if familiar.warning:
            self._note_exclusion(
                employee_id, "Has not worked a shift like this before."
            )
            return False

        # Statutory curfew — never relaxed.
        if violates_minor_curfew(employee, segment.start, segment.end):
            self._note_exclusion(
                employee_id, f"Under {MINOR_AGE}: outside permitted hours."
            )
            return False

        # 9. Preferred days off — a preference, relaxable unless strict mode.
        if day in (employee.get("preferred_days_off") or []):
            if self.strict_days_off or not relax_preferences:
                return False

        broken = _matching_custom_rule(
            self.custom_constraints, employee_id, day,  # noqa: E128
            to_minutes(segment.start), to_minutes(segment.end), open_m, close_m,
        )
        if broken:
            self._note_exclusion(
                employee_id,
                f"Blocked by your rule: {broken.get('description', 'custom rule')}.",
            )
            return False

        if self._breaks_headcount_rule(employee_id, day):
            return False

        return True

    def _breaks_headcount_rule(self, employee_id: str, day: str) -> bool:
        """Custom rules that depend on who else is already on the day.

        `max_staff` and `not_together` cannot be judged from one assignment
        in isolation — they are about the shape of the day — so they live
        here rather than in the per-shift check.
        """
        on_day = {
            s["employee_id"] for s in self.result.shifts
            if s["day"] == day and not (
                s.get("paid_holiday") or s.get("unpaid_holiday") or s.get("sick")
            )
        }

        for rule in self.custom_constraints:
            days = [d.lower()[:3] for d in (rule.get("days") or [])]
            if days and day not in days:
                continue
            rule_type = (rule.get("type") or "").lower()

            if rule_type == "max_staff":
                limit = int(rule.get("value") or 0)
                if limit and employee_id not in on_day and len(on_day) >= limit:
                    self._note_exclusion(
                        employee_id,
                        f"Your rule caps {day} at {limit} staff.",
                    )
                    return True

            elif rule_type == "not_together":
                pair = set(rule.get("employee_ids") or [])
                if employee_id in pair and (pair - {employee_id}) & on_day:
                    self._note_exclusion(
                        employee_id,
                        "Your rule keeps them off the same shift as a colleague.",
                    )
                    return True
        return False

    def _warn_if_unfamiliar(
        self, employee: Dict[str, Any], day: str, start: str, end: str
    ) -> None:
        """Flag a shift unlike anything this person has worked before.

        A warning, never a block: a brand-new employee has no history at all,
        so blocking on unfamiliarity would mean they could never be rostered.
        The manager is told and decides.

        Recorded structurally rather than as a sentence in `issues` so the UI
        can group them by person and offer a confirm action, and so the same
        pairing is never reported twice.
        """
        verdict = avail.check_familiarity(employee, start, end, self.shift_history)
        if not verdict.warning:
            return

        employee_id = employee["employee_id"]
        if any(
            c["employee_id"] == employee_id and c["day"] == day
            for c in self.result.confirmations
        ):
            return

        self.result.confirmations.append({
            "employee_id": employee_id,
            "name": employee.get("name", employee_id),
            "day": day,
            "start": start,
            "end": end,
            "message": verdict.warning,
        })

    def _week_span(self, day: str, start: str, end: str) -> Tuple[int, int]:
        """A shift as minutes from Monday 00:00, so days compare correctly.

        Clock times alone cannot answer "how long between these two shifts":
        22:00 to 06:00 is eight hours if they are consecutive days and
        sixteen if they are not.
        """
        base = DAYS.index(day) * 24 * 60
        first = base + to_minutes(start)
        last = base + to_minutes(end)
        if last <= first:                     # finishes after midnight
            last += 24 * 60
        return first, last

    def _rest_breach(
        self, employee_id: str, day: str, start: str, end: str
    ) -> Optional[float]:
        """Hours of rest, if giving this shift would leave too few.

        Checks both directions. Somebody already down for a 06:00 start
        tomorrow cannot be given a shift finishing at 23:00 tonight either —
        the breach is the same whichever order the solver happens to place
        them in.
        """
        new_start, new_end = self._week_span(day, start, end)
        required = self.min_rest_hours * 60

        for shift in self.result.shifts:
            if shift.get("employee_id") != employee_id:
                continue
            if not (shift.get("start") and shift.get("end")):
                continue
            # Same-day entries are prevented elsewhere; rest is about the gap
            # between working days.
            if shift.get("day") == day:
                continue
            other_start, other_end = self._week_span(
                shift["day"], shift["start"], shift["end"]
            )
            if new_start >= other_end:
                gap = new_start - other_end
            elif other_start >= new_end:
                gap = other_start - new_end
            else:
                continue                      # overlapping; caught elsewhere
            if gap < required:
                return gap / 60
        return None

    def _note_exclusion(self, employee_id: str, reason: str) -> None:
        """Record why someone was passed over.

        First reason wins: the earliest check to reject them is the most
        fundamental one, and is the more useful thing to report.
        """
        self.exclusions.setdefault(employee_id, reason)

    # -- assignment -------------------------------------------------------
    @staticmethod
    def hours_spanned(start: str, end: str) -> List[int]:
        """Clock hours a shift is on the floor for, wrapping past midnight.

        23:30-07:00 yields [23, 0, 1, 2, 3, 4, 5, 6]. Paid-holiday entries
        have no times and cover nothing.

        Clock hours only — it does not say which DAY each hour falls on. Use
        `hours_covered` for anything that counts coverage, or an overnight
        shift's small hours get credited to the day it started.
        """
        if not start or not end:
            return []
        start_m, end_m = to_minutes(start), to_minutes(end)
        if end_m <= start_m:
            end_m += 24 * 60
        return sorted({(m // 60) % 24 for m in range(start_m, end_m, 60)})

    @staticmethod
    def hours_covered(
        day: str, start: str, end: str, *, wrap_week: bool = True
    ) -> List[Tuple[str, int]]:
        """(day, hour) pairs a shift actually covers.

        Saturday 22:00-06:00 covers Saturday 22:00 and 23:00, then SUNDAY
        00:00 through 05:00. Crediting all eight hours to Saturday — which is
        what counting clock hours alone does — tells the solver that Saturday
        morning is staffed by the shift that ends it, and that Sunday morning
        is empty when somebody is standing in the shop.

        `wrap_week` decides what happens at the far end. A Sunday night shift
        runs into the FOLLOWING Monday, which is next week's roster. When the
        previous week is known, this week's Sunday night is dropped here and
        Monday's small hours are seeded from real history instead. Only when
        there is no previous week does the wrap stand in, treating the rota as
        repeating so the first week does not report a phantom Monday gap.
        """
        if not start or not end:
            return []
        index = DAYS.index(day)
        start_m, end_m = to_minutes(start), to_minutes(end)
        if end_m <= start_m:
            end_m += 24 * 60

        covered = set()
        for minute in range(start_m, end_m, 60):
            offset = index + minute // (24 * 60)
            if offset > 6 and not wrap_week:
                continue  # spills into next week — not this roster's to count
            covered.add((DAYS[offset % 7], (minute // 60) % 24))
        return sorted(covered, key=lambda pair: (DAYS.index(pair[0]), pair[1]))

    def _record_shift(self, employee_id: str, day: str, start: str, end: str, **extra) -> None:
        span = shift_duration_minutes(start, end) / 60
        self.result.shifts.append({
            "shift_id": f"sh_{uuid.uuid4().hex[:8]}",
            "employee_id": employee_id,
            "day": day,
            "start": start,
            "end": end,
            "fixed": False,
            # Both figures are stored: span is what the person is present for
            # and what the rota shows; paid_hours is what they are paid and
            # what counts against their contract. Payroll needs the second,
            # the wall chart needs the first.
            "span_hours": round(span, 2),
            "break_minutes": 0 if self.breaks_paid else break_minutes(span),
            "paid_hours": round(paid_hours(start, end, breaks_paid=self.breaks_paid), 2),
            **extra,
        })
        # Both are tracked: paid hours drive wages and an hourly cap, span
        # drives a salaried contract. They are different numbers for the same
        # shift and conflating them is how somebody ends up 1.8h "over".
        self.hours_used[employee_id] += paid_hours(start, end, breaks_paid=self.breaks_paid)
        self.span_used[employee_id] += span
        self.days_worked.setdefault(employee_id, set()).add(day)

        # Keep coverage counters in step with every assignment, so the next
        # iteration sees the effect of this one.
        role = self.employees_by_id.get(employee_id, {}).get("role") or ""
        for covered_day, hour in self.hours_covered(
            day, start, end, wrap_week=self.wrap_week
        ):
            self.on_duty[covered_day][hour] += 1
            if role:
                self.role_on_duty[covered_day][role][hour] += 1

    def _build_hours_aim(self, history_rosters) -> Dict[str, float]:
        """What each hourly person could reasonably be given this week.

        The smallest of four, because any one alone is wrong:

          * what they have been working lately — the median of the last
            `TREND_WEEKS` weeks they appear in (`hours_target`)
          * what their availability can physically hold — somebody who has
            dropped to weekends cannot be given a full week, and their
            availability says so the moment it is entered, without waiting
            eight weeks for the trend to catch up
          * leave booked in THIS week — three days off cannot be worked, and
            aiming at a full week would push their hours onto days they are
            not there
          * their weekly cap, which for a student differs between term time
            and their summer break

        Salaried staff are absent from this entirely: their band is a promise
        the shop pays either way, and `_contract_need` already expresses it.
        """
        usual = hours_target.usual_hours(
            history_rosters or [], self.week_start,
            breaks_paid=self.breaks_paid,
        )
        aim: Dict[str, float] = {}
        for employee in self.employees:
            employee_id = employee["employee_id"]
            if employee_id not in usual or self.span_bands.get(employee_id):
                continue
            if not avail.is_active(employee):
                continue
            best = []
            for day in DAYS:
                if self.date_for_day.get(day) in self.employee_off_dates.get(
                    employee_id, set()
                ):
                    continue
                options = [
                    paid_hours(start, end, breaks_paid=self.breaks_paid)
                    for start, end in self._shapes_for_aim(day)
                    if avail.check_availability(
                        employee, day, start, end).allowed
                    and not violates_minor_curfew(employee, start, end)
                ]
                best.append(max(options) if options else 0.0)
            ceiling = sum(sorted(best, reverse=True)[:self.max_working_days])
            aim[employee_id] = min(
                usual[employee_id],
                ceiling,
                self.hour_caps.get(employee_id, usual[employee_id]),
            )
        return aim

    def _shapes_for_aim(self, day: str) -> List[Tuple[str, str]]:
        """The shift shapes this shop runs on a day, for sizing the aim."""
        if self.demand is None:
            return []
        return [tuple(slot) for slot in self.demand.slots_for(day)]

    def _unrecord_shift(self, shift: Dict[str, Any]) -> None:
        """The exact inverse of `_record_shift`, for undoing a trial move.

        Every counter `_record_shift` touches is reversed here, and that
        pairing is the whole safety of the rebalance pass: a counter left
        un-reversed does not fail loudly, it quietly inflates somebody's hours
        for the rest of the week and the roster comes out wrong somewhere
        else entirely.

        `test_recording_then_unrecording_a_shift_leaves_no_trace` keeps the
        two in step — it fails the moment `_record_shift` starts tracking
        something this does not give back.
        """
        employee_id = shift["employee_id"]
        day, start, end = shift["day"], shift["start"], shift["end"]
        span = shift_duration_minutes(start, end) / 60

        self.result.shifts.remove(shift)
        self.hours_used[employee_id] -= paid_hours(
            start, end, breaks_paid=self.breaks_paid)
        self.span_used[employee_id] -= span

        # Only give the day back if nothing else of theirs remains on it: two
        # shifts in a day is a split shift, which is ordinary in retail (§8).
        if not any(
            s["employee_id"] == employee_id and s["day"] == day
            for s in self.result.shifts
        ):
            self.days_worked.get(employee_id, set()).discard(day)
            self.assigned_by_day.get(day, set()).discard(employee_id)

        role = self.employees_by_id.get(employee_id, {}).get("role") or ""
        for covered_day, hour in self.hours_covered(
            day, start, end, wrap_week=self.wrap_week
        ):
            self.on_duty[covered_day][hour] -= 1
            if role:
                self.role_on_duty[covered_day][role][hour] -= 1

    # -- rebalancing hours ------------------------------------------------
    def _rebalance_hours(self) -> None:
        """Even out hourly staff against the hours they are currently working.

        WHY THIS IS A PASS AND NOT A SORT KEY
        -------------------------------------
        Two attempts to do this inside the per-slot ranking changed nothing at
        all, and could not have: the sort answers "who takes THIS shift",
        while "Jane should finish the week near 32 hours" is a property of all
        forty shifts together. A local rule cannot express a global target.
        Ranked high enough to bite, it stops being a fair share-out and starts
        taking settled shifts off the people who always work them.

        So the week is built exactly as before, and only then are the totals
        compared. By this point coverage, contracts and the demand shape are
        all settled, and what is left is genuinely a question of who holds
        which of the shifts nobody has a claim on.

        WHAT IT WILL NOT DO
        -------------------
        Move an OWNED shift (§2b), a pin, an extra, a fixed shift or a locked
        one. Break any rule — both people go back through `_is_eligible` and
        the whole move is rolled back on any failure, so coverage, rest,
        curfew, caps and the five-day limit are all exactly as before.
        Change anything at all unless it makes the week measurably fairer.

        Skipped entirely during a single-day rebalance: the manager asked
        about Wednesday, and quietly reshaping Monday to even out a total is
        not an answer to that (§2e).
        """
        if self.only_day is not None or not self.hours_aim:
            return

        # Bounded, and each move must strictly improve the total, so this
        # cannot oscillate between two people forever.
        for _ in range(self._MAX_REBALANCE_MOVES):
            if not self._one_rebalance_move():
                return

    _MAX_REBALANCE_MOVES = 40

    # How far off their usual week somebody has to be before it is worth
    # moving a shift. Below this the roster is being churned to chase
    # rounding, and every moved shift is a line the manager has to read.
    _REBALANCE_TOLERANCE_HOURS = 2.0

    def _one_rebalance_move(self) -> bool:
        """Find and apply the single best move. True if anything changed."""
        gap = {
            employee_id: self.hours_used.get(employee_id, 0.0) - aim
            for employee_id, aim in self.hours_aim.items()
        }
        over = sorted(
            (e for e, d in gap.items() if d > self._REBALANCE_TOLERANCE_HOURS),
            key=lambda e: (-gap[e], e),
        )
        under = sorted(
            (e for e, d in gap.items() if d < -self._REBALANCE_TOLERANCE_HOURS),
            key=lambda e: (gap[e], e),
        )
        if not over or not under:
            return False

        for receiver_id in under:
            receiver = self.employees_by_id.get(receiver_id)
            if not receiver:
                continue
            for donor_id in over:
                for shift in self._rebalanceable_shifts(donor_id):
                    hours = paid_hours(
                        shift["start"], shift["end"],
                        breaks_paid=self.breaks_paid)
                    # Strictly fairer, or it does not happen. Moving a
                    # 10-hour shift to somebody 2 hours short just moves the
                    # unfairness onto the other person.
                    before = abs(gap[donor_id]) + abs(gap[receiver_id])
                    after = (abs(gap[donor_id] - hours)
                             + abs(gap[receiver_id] + hours))
                    if after >= before:
                        continue

                    # AND the donor must not be pushed below their own usual
                    # week. Total distance falling is not enough on its own:
                    # taking 16 hours off somebody who was 10 hours over
                    # improves the total while leaving them 6 hours short,
                    # which is the same complaint from the other direction.
                    # Measured at the reference shop, Roisín went from +9.8h
                    # to -6.2h in exactly this way.
                    if gap[donor_id] - hours < 0:
                        continue
                    if self._try_move_shift(shift, receiver):
                        return True
        return False

    def _rebalanceable_shifts(self, employee_id: str) -> List[Dict[str, Any]]:
        """This person's shifts that nobody has a claim on, longest first.

        Longest first because it closes the gap in fewest moves, and every
        move is a change the manager has to recognise.
        """
        movable = [
            s for s in self.result.shifts
            if s["employee_id"] == employee_id
            and not s.get("pinned")
            and not s.get("extra")
            and not s.get("fixed")
            and not s.get("paid_holiday")
            and not s.get("unpaid_holiday")
            and not s.get("sick")
            # A settled shift is not spare capacity. This is the rule the
            # whole ownership design exists to protect (§2b), and the reason
            # the earlier ranking attempt had to sit below it.
            #
            # `regulars_of`, NOT `owner_of`. `owner_of` returns the single
            # top claimant, so on a shape that runs twice the SECOND regular
            # reads as unowned and their shift could be given away — which is
            # what happened to a Monday 06:00 somebody had worked every week,
            # because a colleague on the other instance ranked first.
            and employee_id not in slot_owners.regulars_of(
                self.slot_owners, s["day"], s["start"], s["end"])
        ]
        return sorted(
            movable,
            key=lambda s: (
                -paid_hours(s["start"], s["end"], breaks_paid=self.breaks_paid),
                s["day"], s["start"],
            ),
        )

    def _try_move_shift(
        self, shift: Dict[str, Any], receiver: Dict[str, Any]
    ) -> bool:
        """Hand one shift to somebody else, or leave everything untouched.

        Eligibility is judged against the week as it stands, and the move
        changes that week, so the receiver is checked AFTER the donor's shift
        is lifted — otherwise their own hours count against them and a
        straight swap of one shift for another looks impossible.
        """
        day = shift["day"]
        date_iso = self.date_for_day[day]
        hours = self.hours_by_day.get(day) or {}
        open_m = to_minutes(hours.get("open") or "00:00")
        close_m = to_minutes(hours.get("close") or "23:59")
        segment = Segment(start=shift["start"], end=shift["end"])
        donor_id = shift["employee_id"]

        self._unrecord_shift(shift)
        assigned = self.assigned_by_day.setdefault(day, set())

        if not self._is_eligible(
            receiver, segment, day, date_iso, assigned,
            open_m, close_m, relax_preferences=True,
        ):
            self._record_shift(donor_id, day, shift["start"], shift["end"])
            assigned.add(donor_id)
            return False

        self._record_shift(
            receiver["employee_id"], day, shift["start"], shift["end"])
        assigned.add(receiver["employee_id"])
        self.result.issues.append(
            f"{day} {shift['start']}-{shift['end']} moved from "
            f"{self.employees_by_id.get(donor_id, {}).get('name', donor_id)} "
            f"to {receiver.get('name', receiver['employee_id'])} — closer to "
            f"the hours they have each been working lately."
        )
        return True

    def _typical_paid_day(self, employee: Dict[str, Any]) -> float:
        """A normal day's pay for this person, in hours.

        Holiday pay is a normal day's pay, so it has to come from somewhere.
        Preference order: what the booking specified, then their usual shift
        length from history, then their contract spread over five days. Using
        a flat 8 hours for everyone would over-pay part-timers and under-pay
        anyone on long shifts.
        """
        employee_id = employee["employee_id"]
        patterns = self.weights.get("tpl", {}).get(employee_id) or {}
        if patterns:
            most_common = max(patterns, key=patterns.get)
            try:
                start, end = most_common.split("-")
                usual = paid_hours(start, end)
                if usual > 0:
                    return usual
            except ValueError:
                pass
        contract = employee.get("max_weekly_hours") or 0
        return round(contract / 5, 2) if contract else 0.0

    def _apply_paid_leave(self, day: str, date_iso: str, assigned_today: Set[str]) -> None:
        """Put booked paid holiday on the roster.

        Without this a person on holiday simply vanishes from the week: the
        manager cannot see why they are missing, and the hours never draw down
        their entitlement because the balance report reads roster shifts. The
        entry carries no times — it is not a shift, it is a paid absence — so
        it contributes nothing to coverage.
        """
        for employee in self.employees:
            employee_id = employee["employee_id"]
            booking = self.paid_leave_dates.get(employee_id, {}).get(date_iso)
            if not booking:
                continue

            hours = booking.get("hours_per_day") or self._typical_paid_day(employee)
            if hours <= 0:
                continue

            self.result.shifts.append({
                "shift_id": f"sh_{uuid.uuid4().hex[:8]}",
                "employee_id": employee_id,
                "day": day,
                "start": "", "end": "",
                "fixed": False,
                "paid_holiday": True,
                "label": booking.get("label") or "Holiday",
                "span_hours": 0.0,
                "break_minutes": 0,
                "paid_hours": round(hours, 2),
            })
            # Holiday is paid but is not work: it does not consume the weekly
            # working-hours cap, so hours_used is deliberately untouched.
            assigned_today.add(employee_id)

    def _apply_locked_shifts(self, day: str, assigned_today: Set[str]) -> None:
        """Lay down the manager's pinned shifts before anything is decided.

        Deliberately unchecked against the ordinary rules. A pin is a
        decision already made — usually with a reason the app cannot see,
        like somebody swapping with a colleague — and refusing it here would
        make the rebalance argue with the person using it. Anything a pin
        breaks is reported afterwards, so it is visible without being
        overruled.
        """
        for shift in self.locked_by_day.get(day, []):
            employee_id = shift.get("employee_id")
            if employee_id in assigned_today:
                continue
            if employee_id not in self.employees_by_id:
                continue
            # `extra` has to survive the round trip. An extra shift comes back
            # in as a locked one, and if it were laid down as an ordinary pin
            # it would start cancelling a demand slot — turning "this person
            # AS WELL AS the usual cover" into "this person INSTEAD OF it",
            # which is the opposite of what the manager asked for.
            self._record_shift(
                employee_id, day, shift["start"], shift["end"],
                pinned=True, **({"extra": True} if shift.get("extra") else {}),
            )
            assigned_today.add(employee_id)

    def _apply_fixed_shifts(self, day: str, date_iso: str, assigned_today: Set[str]) -> None:
        """Honour recurring fixed shifts before any automatic assignment.

        Applies to every shop type. (In the prototype this ran only for
        shops without templates, so 24-hour shops silently ignored their
        own fixed shifts.)
        """
        for employee in self.employees:
            employee_id = employee["employee_id"]
            fixed = self.fixed_by_employee_day.get(employee_id, {}).get(day)
            if not fixed:
                continue

            # Already placed today — by booked leave, a pin, or a locked day.
            #
            # Defensive, not a fix for a reproduced bug. Every other pass
            # checks this and this one did not; a second shift for the same
            # person on the same day would be invisible in the grid, which
            # draws one cell per person per day, while still counting twice in
            # every total. The weekly-cap check below happens to reject most
            # duplicates as a side effect, which is why nothing had shown.
            if employee_id in assigned_today:
                continue

            start, end = fixed

            if date_iso in self.employee_off_dates.get(employee_id, set()):
                self.result.issues.append(
                    f"{employee['name']} has a fixed shift on {day} but is on leave — skipped."
                )
                continue

            # Paid hours, to match how hours_used is accumulated. Comparing a
            # span against a contract here would reject fixed shifts that
            # actually fit once breaks are excluded.
            duration = paid_hours(start, end)
            if self.hours_used[employee_id] + duration > employee["max_weekly_hours"]:
                self.result.issues.append(
                    f"{employee['name']}'s fixed shift on {day} would exceed their weekly hour cap — skipped."
                )
                continue

            if violates_minor_curfew(employee, start, end):
                self.result.critical_issues.append(
                    f"{employee['name']} is under {MINOR_AGE} and their fixed shift on {day} "
                    f"({start}-{end}) breaks the curfew — skipped."
                )
                continue

            self._record_shift(employee_id, day, start, end, fixed=True)
            assigned_today.add(employee_id)

    def _staff_segment(
        self, segment: Segment, day: str, date_iso: str,
        assigned_today: Set[str], open_m: int, close_m: int,
    ) -> None:
        segment_key = f"{segment.start}-{segment.end}"
        ranked = sorted(self.employees, key=lambda e: self._rank(e, segment_key, day))
        assigned_count = self._count_existing_cover(segment, day)

        # Pass 1 honours every soft preference.
        # Pass 2 runs only if the coverage floor is still unmet, and relaxes
        # ONLY preferred-days-off. Legal limits are excluded from relaxation
        # in _is_eligible, so they hold in both passes.
        for relax in (False, True):
            if assigned_count >= segment.min_staff:
                break
            for employee in ranked:
                if assigned_count >= segment.min_staff:
                    break
                if not self._is_eligible(
                    employee, segment, day, date_iso, assigned_today,
                    open_m, close_m, relax_preferences=relax,
                ):
                    continue
                self._warn_if_unfamiliar(employee, day, segment.start, segment.end)
                self._record_shift(
                    employee["employee_id"], day, segment.start, segment.end,
                    template_id=segment.template_id,
                    template_name=segment.name,
                    **({"coverage_fallback": True} if relax else {}),
                )
                assigned_today.add(employee["employee_id"])
                assigned_count += 1

        self._report_coverage(segment, day, assigned_count)

    @staticmethod
    def _absolute_span(start: str, end: str) -> Tuple[int, int]:
        """Return (start, end) in minutes with end always after start.

        A block that crosses midnight has its end pushed into the next day
        (23:00-07:00 becomes 1380-1860). Comparing raw clock values instead
        makes an overnight block look like it ends before it begins, which
        silently breaks every interval comparison it takes part in.
        """
        start_m, end_m = to_minutes(start), to_minutes(end)
        if end_m <= start_m:
            end_m += 24 * 60
        return start_m, end_m

    def _count_existing_cover(self, segment: Segment, day: str) -> int:
        """How many already-placed shifts fully span this segment.

        Fixed shifts count toward a segment's staffing floor — without this,
        someone rostered 09:00-17:00 by a fixed shift would not satisfy a
        09:00-15:00 segment and the solver would over-staff it.

        Both sides are normalised for midnight-crossing first: a naive
        comparison let a 07:00-15:00 morning shift appear to cover a
        23:00-07:00 night block, so overnight cover was counted as satisfied
        and the night was left both unstaffed and unreported.

        Yesterday's night shift is considered too. Someone working
        22:00-06:00 on Saturday is on the floor for Sunday's early segment,
        and only counting shifts filed under Sunday would roster a second
        person alongside them.
        """
        seg_start, seg_end = self._absolute_span(segment.start, segment.end)
        previous = DAYS[(DAYS.index(day) - 1) % 7]
        covering = 0
        for shift in self.result.shifts:
            # Paid-holiday entries carry no times and cover nothing.
            if not (shift.get("start") and shift.get("end")):
                continue

            if shift["day"] == day:
                offset = 0
            elif shift["day"] == previous:
                # Shifted back a day, so an overnight shift's hours line up
                # with this day's segment on the same number line.
                offset = -24 * 60
            else:
                continue

            shift_start, shift_end = self._absolute_span(shift["start"], shift["end"])
            shift_start += offset
            shift_end += offset
            if shift_start <= seg_start and shift_end >= seg_end:
                covering += 1
        return covering

    def _report_coverage(self, segment: Segment, day: str, assigned: int) -> None:
        if assigned == 0:
            # Rules 2/3 breached: nobody in the roster can legally cover this.
            self.result.critical_issues.append(
                f"CRITICAL: {segment.name} on {day} ({segment.start}-{segment.end}) has NO "
                f"coverage — the shop would be left unattended. No employee is legally "
                f"available (all are on leave, at their hour cap, or curfew-restricted)."
            )
        elif assigned < segment.min_staff:
            # Floor met, target missed — a planning note, not a rule breach.
            self.result.issues.append(
                f"{segment.name} on {day} ({segment.start}-{segment.end}): "
                f"{assigned}/{segment.min_staff} staffed."
            )

    # -- demand-driven assignment ----------------------------------------
    # Backstop only. Each iteration either places a shift or retires an hour,
    # so the loop terminates on its own; this stops a future bug becoming a
    # hung request.
    _MAX_ITERATIONS_PER_DAY = 400

    def _would_overstaff(self, day: str, start: str, end: str) -> bool:
        """Whether adding one person on this shift exceeds the learned curve.

        Zero tolerance by default: the shop has run two people at 06:00 for
        six months, so a roster that puts four there is not following the
        history, it is spending money the shop has never spent. Callers fall
        back to allowing it when every option overstaffs, so coverage is
        never sacrificed to the ceiling.

        Checks EVERY hour the shift lands on, including the ones after
        midnight. Checking only today's hours let a 23:30-07:00 night shift
        through — its overnight half is tomorrow's, and it was quietly adding
        a fourth body to a 06:00 that has always had two.
        """
        if not self.demand:
            return False
        allowance = int(self.shop.get("overstaff_tolerance") or 0)
        for covered_day, hour in self.hours_covered(
            day, start, end, wrap_week=self.wrap_week
        ):
            required = self.demand.required(covered_day, hour)
            if required <= 0:
                continue  # an hour the shop does not staff to a target
            if self.on_duty[covered_day][hour] + 1 > required + allowance:
                return True
        return False

    def _open_hours(self, day: str) -> List[int]:
        """Hours the shop is open, from its configured opening times."""
        hours = self.hours_by_day.get(day)
        if not hours or hours.get("closed"):
            return []
        open_m, close_m = to_minutes(hours["open"]), to_minutes(hours["close"])
        if close_m <= open_m:
            # Open across midnight (or 00:00-23:59) — treat as the whole day.
            return list(range(24))
        return sorted({(m // 60) % 24 for m in range(open_m, close_m, 60)})

    @staticmethod
    def _crosses_midnight(pattern: Any) -> bool:
        return to_minutes(pattern.end) <= to_minutes(pattern.start)

    def _contract_shift_length(self, employee: Dict[str, Any]) -> Optional[float]:
        """How long each of a salaried employee's shifts should be.

        Planned up front rather than patched afterwards, because shift
        lengths interact: four ten-hour days is 40, and with a ten-hour
        ceiling a fifth shift of any legal length overshoots 42.5. Forty-one
        is then unreachable no matter how the finish times are nudged.

        Spreading the contract over the fewest days that can hold it — five
        eight-and-a-half hour days for 42.5 — is what a manager writes, and
        it leaves room to fine-tune the finish times afterwards.
        """
        band = self.span_bands.get(employee["employee_id"])
        if not band:
            return None
        target = band[1]
        max_shift = min(
            float(self.shop.get("max_shift_hours") or ABSOLUTE_MAX_SHIFT_HOURS),
            ABSOLUTE_MAX_SHIFT_HOURS,
        )
        if max_shift <= 0:
            return None

        days = max(1, math.ceil(target / max_shift - 1e-9))
        days = min(days, self.max_working_days)
        length = target / days
        min_shift = float(self.shop.get("min_shift_hours") or 0)
        return max(min_shift, min(length, max_shift))

    def _contract_need(self, employee: Dict[str, Any], span: float) -> float:
        """How much this slot helps a salaried employee reach their band.

        Lower sorts first, so a full-timer who is behind gets the longer
        shifts. Without this the top-up could only add DAYS, and with five
        days as the ceiling somebody on 8-hour shifts tops out at 40 — short
        of a 41-hour minimum they are already being paid for. Giving them the
        10-hour slot in the first place is how a manager solves it.

        Zero for everybody else, so hourly and student staff are ranked
        exactly as before.
        """
        band = self.span_bands.get(employee["employee_id"])
        if not band:
            return 0.0
        shortfall = band[0] - self.span_used.get(employee["employee_id"], 0.0)
        if shortfall <= 0:
            return 0.0
        # Negative so the biggest genuine help sorts first, capped at the
        # shortfall so an over-long shift is not preferred for its own sake.
        return -min(shortfall, span)

    # How far a placed shift's start may sit from a slot's and still be
    # taken as filling it. An hour covers "pinned at 06:00 against an
    # 06:00 slot" and "07:30 against 07:00", without letting an afternoon
    # shift cancel the morning opening.
    SLOT_MATCH_TOLERANCE_MINUTES = 60

    def _history_rank(
        self, eligible: List[Dict[str, Any]], day: str, start: str, end: str
    ) -> Dict[str, int]:
        """employee_id -> how strong their claim on this slot is, 0 = best.

        Two tiers, matching what a manager does:

          0        the owner — works this slot most of the time
          1, 2…    whoever else actually covers it, most often first

        Anybody with no history for the slot is absent from the map and sorts
        last, so a shift with no settled pattern is decided exactly as before.
        """
        if not self.slot_owners:
            return {}

        ranks: Dict[str, int] = {}
        available = {e["employee_id"] for e in eligible}

        owner = slot_owners.owner_of(
            self.slot_owners, day, start, end,
        )
        if owner and owner in available:
            ranks[owner] = 0

        # The usual person may be off. Falling back to seniority would hand a
        # 06:00 opening to whoever ranks highest rather than to whoever
        # actually opens when they are away.
        position = 1
        for employee_id in slot_owners.preference_order(
            self.slot_owners, day, start, end
        ):
            if employee_id in available and employee_id not in ranks:
                ranks[employee_id] = position
                position += 1

        return ranks

    def _closest_placed(
        self, placed: List[Dict[str, Any]], start: str, end: str
    ) -> Optional[Dict[str, Any]]:
        """The shift already on the floor that best answers this slot.

        Nearest start wins; the finish only breaks ties. A person is either
        there to open or they are not, and how long they stay is a separate
        question the contract and hour-fitting passes deal with.
        """
        want_start, want_end = to_minutes(start), to_minutes(end)
        best, best_key = None, None

        for shift in placed:
            gap = abs(to_minutes(shift["start"]) - want_start)
            if gap > self.SLOT_MATCH_TOLERANCE_MINUTES:
                continue
            key = (gap, abs(to_minutes(shift["end"]) - want_end))
            if best_key is None or key < best_key:
                best, best_key = shift, key

        return best

    def _staff_by_slots(
        self, day: str, date_iso: str, assigned_today: Set[str],
        open_m: int, close_m: int,
    ) -> None:
        """Fill the shifts this day actually runs, one at a time.

        The shop's own rota is a list of shifts — two people open at 06:00,
        one starts at 07:30, one covers the night — so this reproduces that
        list rather than inferring it from an hourly headcount.

        Inferring was the problem. A night shift still on the floor at 06:00
        is already counted in the historical curve, so filling 06:00 "to
        target" with fresh morning starts and then letting the night shift
        arrive on top put a fourth body on an hour that has always had
        three. Filling named slots cannot double-count, because each shift
        the shop runs is placed exactly once.

        Slots are taken earliest first: the opener is usually the hardest to
        fill, so it gets to choose while the most people are still free.
        """
        slots = self.demand.slots_for(day) if self.demand else []
        if not slots:
            return

        # Fixed shifts, pins and booked leave are already on the day. Anybody
        # standing there is a slot that no longer needs filling.
        #
        # Matched on START time, not on the exact pair. Exact matching meant a
        # pinned 06:00-14:00 did not cancel a 06:00-16:00 slot, so the solver
        # sent a third person to a morning that runs two — and the manager
        # deleted the person the solver had added because of their own pin.
        # What matters for coverage is that somebody opens, not that they
        # leave at the minute the learned shape says.
        #
        # Extra staff are excluded: they are deliberately ON TOP of the
        # requirement, so they must not cancel anything.
        placed = [
            s for s in self.result.shifts
            if s["day"] == day and s.get("start") and s.get("end")
            and not s.get("extra")
        ]

        # Two passes, because two slots can share a start time and the wrong
        # one gets cancelled otherwise.
        #
        # Monday runs 06:00-16:00 and 06:00-14:00. If the manager is already
        # standing on his own 06:00-14:00, matching purely by proximity lets
        # him cancel the 06:00-16:00 slot instead — and the person who owns
        # THAT one loses her shift to a slot she does not work.
        #
        # So: anybody standing on a slot they own claims it first. Whatever
        # is left is matched by nearest start.
        claimed = set()
        for index, (start, end) in enumerate(slots):
            owner = slot_owners.owner_of(
                self.slot_owners, day, start, end,
            )
            if owner is None:
                continue
            # They must actually be standing there. Owning Monday's opening
            # does not cancel it when the manager has pinned you to the
            # afternoon — that would leave the shop unopened.
            theirs = next(
                (
                    s for s in placed
                    if s["employee_id"] == owner
                    and abs(to_minutes(s["start"]) - to_minutes(start))
                    <= self.SLOT_MATCH_TOLERANCE_MINUTES
                ),
                None,
            )
            if theirs is not None:
                placed.remove(theirs)
                claimed.add(index)

        outstanding = []
        for index, (start, end) in enumerate(slots):
            if index in claimed:
                continue
            match = self._closest_placed(placed, start, end)
            if match is not None:
                # One placed shift cancels at most one slot, so a genuine
                # double-up on the same opening still gets filled.
                placed.remove(match)
                continue
            outstanding.append((start, end))

        # Hold each owner back from OTHER slots while their own is unfilled.
        #
        # Slots are filled earliest first, so an owner can be spent on an
        # earlier slot before their own comes up: Martin owns 10:00-19:00, but
        # 06:00-14:00 is offered first, its owner was on leave, and Martin was
        # the best of who was left — so he took it and his own shift went to
        # somebody else. Reordering the slots would fix it and break something
        # worse, because the opener is the hardest slot to fill and must keep
        # first refusal. Reserving the person instead leaves the order alone.
        #
        # Only ONE reservation each: nobody works two shifts in a day, so if
        # somebody owns two slots the earlier one is the one held for them.
        reservations: Dict[str, Tuple[str, str]] = {}
        for shape in outstanding:
            owner = slot_owners.owner_of(self.slot_owners, day, shape[0], shape[1])
            if owner is not None:
                reservations.setdefault(owner, shape)
        unfilled = set(outstanding)

        for start, end in outstanding:
            segment = Segment(start=start, end=end, min_staff=1)
            hours = [h for d, h in self.hours_covered(day, start, end) if d == day]
            unfilled.discard((start, end))
            held = {
                eid for eid, shape in reservations.items()
                if shape != (start, end) and shape in unfilled
            }

            best = None
            for relax in (False, True):
                eligible = [
                    e for e in self.employees
                    if self._is_eligible(
                        e, segment, day, date_iso, assigned_today,
                        open_m, close_m, relax_preferences=relax,
                    )
                ]
                # A reservation is a preference between candidates, never a
                # reason to leave a shift empty. If holding people back empties
                # the list, the slot in front of us wins — cover first.
                if held:
                    kept = [e for e in eligible if e["employee_id"] not in held]
                    if kept:
                        eligible = kept
                if eligible:
                    span = shift_duration_minutes(start, end) / 60
                    # The OWNER of a slot takes it, ahead of contract need.
                    #
                    # Contract need used to come first, and it swept the week.
                    # _contract_need returns a negative number for any salaried
                    # employee below their band, and zero for everybody else —
                    # so while a full-timer is short they outrank the owner on
                    # every slot they are eligible for. Monday is built first,
                    # when every shortfall is still the whole contract, so
                    # Monday took the worst of it: measured against the
                    # reference shop, four settled shifts changed hands on one
                    # day — the 06:00 opening its owner had worked for 14 of 24
                    # weeks, and three others.
                    #
                    # The contract still gets filled, because 41 hours can be
                    # reached from many combinations of shifts. It does not
                    # need THAT slot, only enough slots — and _top_up_contracts
                    # runs afterwards for anyone left short, with under_contract
                    # reporting whoever it cannot reach. Taking the shift
                    # somebody has opened every week for months buys nothing the
                    # contract needs and costs the manager an edit.
                    #
                    # Only rank 0 — the owner — jumps contract need. Someone who
                    # merely covers the slot sometimes does not: below, the
                    # order is exactly as it was.
                    history_rank = self._history_rank(eligible, day, start, end)

                    def rank_of(e):
                        return (
                            0 if (
                                self.OWNER_BEATS_CONTRACT
                                and history_rank.get(e["employee_id"]) == 0
                            ) else 1,
                            self._contract_need(e, span),
                            # UNRANKED, not len(ranks): with one ranked person
                            # len() is 1, which tied them with everybody who
                            # had never worked the slot and let ordinary
                            # ranking decide after all.
                            history_rank.get(e["employee_id"], _UNRANKED_FOR_SLOT),
                            self._rank_for_demand(e, f"{start}-{end}", day, hours),
                        )

                    best = self._pick_for_slot(
                        eligible, rank_of, day, start, end,
                    )
                    if relax:
                        self._note_relaxed_preference(best, day)
                    break

            if best is None:
                # Left empty on purpose. Pass 3 reports it so the manager can
                # see the blank and decide, rather than it being filled by
                # somebody the rules would not allow.
                continue

            # A salaried employee's shift is sized to their contract rather
            # than to the slot: the start is what the day needs, the finish
            # is what makes the week add up. Any hours this frees at the tail
            # are picked up by the coverage pass.
            finish = self._fit_length_to_contract(best, day, start, end)
            self._record_shift(best["employee_id"], day, start, finish)
            assigned_today.add(best["employee_id"])

    # How far down the ranking a seeded regeneration may reach. Two means
    # the usual pick and the next one or two behind them — people the manager
    # would regard as equally reasonable for a shift nobody owns. Wider than
    # that and Regenerate starts proposing the person who has covered the
    # slot once against the person who covers it most weeks, which is not
    # variety, it is a worse roster.
    VARIATION_DEPTH = 2

    def _pick_for_slot(self, eligible, rank_of, day: str, start: str, end: str):
        """The best candidate — or, when regenerating, a near-equal one.

        Without a seed this is exactly `min`, and the solver stays the
        deterministic thing it has always been.

        With a seed, three conditions all have to hold before anything varies:

          * the slot has no owner. A settled shift is not a coin toss, and
            handing Emma's opening to somebody else on a re-roll is an edit
            the manager has to undo.
          * the alternatives are no worse on CONTRACT need. Contract hours are
            already being paid for and are not traded for variety.
          * they are within VARIATION_DEPTH on preference. Somebody who has
            covered the slot twice does not get equal billing with whoever
            covers it most weeks.

        Choice is weighted by standing, so the usual person stays the most
        likely outcome — Regenerate offers a plausible alternative, not a
        random one.
        """
        ordered = sorted(eligible, key=rank_of)
        if self.rng is None or len(ordered) < 2:
            return ordered[0]

        if slot_owners.owner_of(self.slot_owners, day, start, end) is not None:
            return ordered[0]

        top = rank_of(ordered[0])
        # Same owner-tier and same contract need — anything else is not an
        # equal alternative, whatever its preference rank.
        pool = [
            e for e in ordered
            if rank_of(e)[:2] == top[:2]
            and rank_of(e)[2] - top[2] <= self.VARIATION_DEPTH
        ]
        if len(pool) < 2:
            return ordered[0]

        # Front-loaded weights: first choice twice as likely as second, and
        # so on. Over a few regenerations the manager sees real alternatives
        # without the roster losing its shape.
        weights = [1.0 / (index + 1) for index in range(len(pool))]
        return self.rng.choices(pool, weights=weights, k=1)[0]

    def _drop_duplicate_days(self) -> None:
        """Nobody appears twice on one day. Enforced at the boundary.

        Every pass is supposed to guarantee this and they each check it their
        own way, so the invariant was never stated in one place — and when it
        broke at the reference shop I could not reproduce which pass had done
        it. Two people came out on 60h with six shifts of ten, four of them
        real and two duplicated. Invisible in the grid, which draws one cell
        per person per day, and wrong in every total that counts rows.

        So it is asserted once, here, over the finished week. Cheaper than
        auditing five passes, and it holds whatever a sixth pass does later.

        The LONGER shift is kept. A duplicate is one of two things: the same
        shift laid down twice, in which case they are identical and it does
        not matter; or a real shift plus a shorter fragment, in which case the
        real one is the one to keep.
        """
        best: Dict[Tuple[str, str], Dict[str, Any]] = {}
        removed: List[Dict[str, Any]] = []

        for shift in self.result.shifts:
            if not (shift.get("start") and shift.get("end")):
                continue    # leave carries no times and cannot collide
            key = (shift["employee_id"], shift["day"])
            existing = best.get(key)
            if existing is None:
                best[key] = shift
                continue
            keep, drop = sorted(
                (existing, shift),
                key=lambda s: -shift_duration_minutes(s["start"], s["end"]),
            )
            best[key] = keep
            removed.append(drop)

        if not removed:
            return

        for shift in removed:
            self.result.shifts.remove(shift)
            # Undo the accounting, or the hours stay wrong even though the
            # row is gone — which is the same bug wearing a different hat.
            span = shift_duration_minutes(shift["start"], shift["end"]) / 60
            employee_id = shift["employee_id"]
            self.span_used[employee_id] = max(
                0.0, self.span_used.get(employee_id, 0.0) - span,
            )
            self.hours_used[employee_id] = max(
                0.0,
                self.hours_used[employee_id]
                - paid_hours(shift["start"], shift["end"],
                             breaks_paid=self.breaks_paid),
            )
            for covered_day, hour in self.hours_covered(
                shift["day"], shift["start"], shift["end"],
                wrap_week=self.wrap_week,
            ):
                self.on_duty[covered_day][hour] = max(
                    0, self.on_duty[covered_day][hour] - 1,
                )

        # Reported, not silently swallowed: a duplicate means a pass placed
        # somebody it should not have, and hiding that would leave the real
        # fault to be found again by a manager rather than by a test.
        names = ", ".join(sorted({
            f"{self.employees_by_id.get(s['employee_id'], {}).get('name', s['employee_id'])}"
            f" ({s['day']})"
            for s in removed
        }))
        self.result.issues.append(
            f"Removed {len(removed)} duplicate shift(s) — somebody was placed "
            f"twice on the same day: {names}. Please report this."
        )

    def _fit_length_to_contract(
        self, employee: Dict[str, Any], day: str, start: str, end: str
    ) -> str:
        """Trim a slot's finish to a salaried employee's per-shift length."""
        wanted = self._contract_shift_length(employee)
        if wanted is None:
            return end
        span = shift_duration_minutes(start, end) / 60
        if span <= wanted + 1e-6:
            return end  # already at or under their share; leave it alone

        # WHOLE HOURS, ROUNDED DOWN.
        #
        # This used to round to 30-minute steps, which is where every
        # manufactured half-hour finish in the roster came from: measured
        # across 8 solved weeks at the reference shop, 42 of 42 of them, all
        # on salaried staff, against a manager who ends a shift on a half
        # hour once in 555 shifts.
        #
        # The shop's own convention is the half-hour on the START — 07:30-16:00,
        # 23:30-07:00 — and a whole-hour finish. Matching that by moving the
        # start instead was considered and rejected: familiarity is keyed on
        # start time (§2), so nudging a start to tidy a finish risks offering
        # somebody a shift they have never worked, which is a far worse
        # trade than half an hour.
        #
        # DOWN rather than nearest, so a trim can never push somebody OVER
        # their band. It leaves them slightly short of the per-shift share —
        # 8h where 8.5 was wanted — and _top_up_contracts is what makes that
        # up elsewhere in the week. §2b already says the contract needs
        # ENOUGH slots, not any particular one. `under_contract` reports
        # anybody it cannot reach, so this cannot fail silently.
        #
        # THE STEP IS THE SHOP'S, NOT TOP OIL'S. Rounding to a whole hour is
        # right for a shop that ends shifts on the hour 99.8% of the time, and
        # wrong for one that genuinely runs 10:30 and 12:30 finishes — there,
        # every trim would drag the rota toward a convention it does not use.
        # `demand.finish_granularity` reads it off the shop's own rosters.
        # Sixty when there is no profile yet, which is also what a shop with
        # too little history to have a convention should get.
        step = int(getattr(self.demand, "edge_minutes", 60) or 60)
        minutes = int(wanted * 60 // step) * step
        new_end_m = (to_minutes(start) + minutes) % (24 * 60)
        new_end = f"{new_end_m // 60:02d}:{new_end_m % 60:02d}"
        if violates_minor_curfew(employee, start, new_end):
            return end
        return new_end

    def _staff_by_demand(
        self, day: str, date_iso: str, assigned_today: Set[str],
        *, only_overnight: bool = False,
    ) -> None:
        """Fill the day until the demand curve is satisfied.

        Repeatedly finds the worst-covered hour, picks the shift pattern that
        closes the most unmet demand, and gives it to the best eligible
        person. This is what produces overlapping, staggered shifts — the
        previous model tiled the day into fixed blocks and could not.

        Only hours a shift STARTING today can reach are considered. Today's
        small hours belong to yesterday's night shift, and a pattern is
        judged on the hours it actually lands on: matching by clock hour
        instead made a Monday 22:00-06:00 pattern look like the fix for
        Monday 00:00, so the solver placed one, saw hour zero still empty
        (those hours had landed on Tuesday), and placed another — eight in a
        row, until it ran out of staff.
        """
        open_hours = set(self._open_hours(day))
        if not open_hours:
            return

        patterns = [p for p in self.demand.patterns if p.covers()]
        if only_overnight:
            patterns = [p for p in patterns if self._crosses_midnight(p)]
        if not patterns:
            return

        # Hours we have already proven unfillable, so we stop retrying them.
        exhausted: Set[int] = set()

        for _ in range(self._MAX_ITERATIONS_PER_DAY):
            shortfalls = {
                hour: self.demand.required(day, hour) - self.on_duty[day][hour]
                for hour in open_hours
                if hour not in exhausted
                and self.demand.required(day, hour) > self.on_duty[day][hour]
            }
            if not shortfalls:
                return

            # Largest shortfall first; earliest hour breaks ties so the day
            # fills front-to-back and reads naturally.
            target_hour = max(shortfalls, key=lambda h: (shortfalls[h], -h))

            placement = self._best_placement(
                day, date_iso, target_hour, shortfalls, patterns, assigned_today
            )
            if placement is None:
                # Retired, not reported: an hour this pass cannot fill may
                # still be covered by a later day's overnight shift.
                exhausted.add(target_hour)
                continue

            employee, pattern, relaxed = placement
            self._warn_if_unfamiliar(employee, day, pattern.start, pattern.end)
            self._record_shift(
                employee["employee_id"], day, pattern.start, pattern.end,
                template_name=None,
                **({"preference_relaxed": True} if relaxed else {}),
            )
            assigned_today.add(employee["employee_id"])
            if relaxed:
                self._note_relaxed_preference(employee, day)

    def _best_placement(
        self,
        day: str,
        date_iso: str,
        target_hour: int,
        shortfalls: Dict[int, int],
        patterns: List[Any],
        assigned_today: Set[str],
    ) -> Optional[Tuple[Dict[str, Any], Any, bool]]:
        """Choose the (employee, pattern) pair that best closes the gap.

        Patterns are ranked by how much *total* unmet demand they absorb, not
        just whether they cover the target hour — a 06:00-16:00 shift that
        fills six short hours beats a 4-hour one that fills the same single
        hour. Historical usage breaks ties, so common shapes win over rare
        ones.
        """
        # Hours each pattern would actually put someone on the floor for
        # TODAY. An overnight pattern contributes only its evening hours
        # here; the rest land on tomorrow and are tomorrow's to count.
        today_hours = {
            pattern.key: [
                h for d, h in self.hours_covered(
                    day, pattern.start, pattern.end, wrap_week=self.wrap_week
                )
                if d == day
            ]
            for pattern in patterns
        }

        candidates = [p for p in patterns if target_hour in today_hours[p.key]]

        # The learned curve is a ceiling as well as a floor. A ten-hour
        # pattern picked to plug a 13:00 shortfall also adds a body to every
        # hour from 06:00 — which is how 06:00 ended up with four people when
        # the shop has always run two. Patterns that would push an hour more
        # than the tolerance above its historical level are dropped.
        within_target = [
            p for p in candidates if not self._would_overstaff(day, p.start, p.end)
        ]
        if within_target:
            candidates = within_target
        # If every option overstaffs somewhere, coverage still wins — an hour
        # with nobody in it is worse than an hour with one too many.

        if not candidates:
            return None

        def pattern_value(pattern) -> Tuple[float, int]:
            """Unmet demand a pattern absorbs, less the hours it wastes.

            Shift shapes are chunky — a 10-hour pattern used to plug a
            2-hour gap staffs eight hours nobody asked for, and that is real
            wage cost. Penalising the overshoot at half weight keeps the
            solver biased toward filling gaps while still preferring genuine
            shifts over a patchwork of short ones.
            """
            hours = today_hours[pattern.key]
            filled = sum(shortfalls.get(h, 0) for h in hours)
            wasted = sum(1 for h in hours if shortfalls.get(h, 0) <= 0)
            return (filled - 0.5 * wasted, pattern.count)

        ordered = sorted(candidates, key=pattern_value, reverse=True)

        # Every pattern is tried without relaxing anything before any pattern
        # is tried with preferences relaxed. Sweeping relax-last matters: the
        # previous ordering relaxed somebody's preferred day off on the
        # *first* pattern it looked at, even when a later pattern had a
        # perfectly willing employee. Legal limits are never relaxed in
        # either pass — see _is_eligible.
        for relax in (False, True):
            for pattern in ordered:
                segment = Segment(start=pattern.start, end=pattern.end, min_staff=1)
                eligible = [
                    e for e in self.employees
                    if self._is_eligible(
                        e, segment, day, date_iso, assigned_today,
                        0, 24 * 60, relax_preferences=relax,
                    )
                ]
                if eligible:
                    best = min(
                        eligible,
                        key=lambda e: self._rank_for_demand(
                            e, pattern.key, day, pattern.covers()
                        ),
                    )
                    # Only genuinely relaxed if this person had asked for the
                    # day off; the second pass also picks up ordinary staff.
                    relaxed = day in (best.get("preferred_days_off") or [])
                    return best, pattern, relaxed

        return None

    def _note_relaxed_preference(self, employee: Dict[str, Any], day: str) -> None:
        """Surface an overridden preference instead of silently applying it.

        A manager needs to know the roster broke somebody's requested day off,
        and why — otherwise they hand it to the team and find out the hard
        way.
        """
        message = (
            f"{employee['name']} was rostered on {day} despite requesting it off — "
            f"too few staff were available to cover the day otherwise."
        )
        if message not in self.result.issues:
            self.result.issues.append(message)

    def _blocked_by_days_off(self, day: str, date_iso: str) -> List[str]:
        """Staff a day off is genuinely keeping off this day.

        Only meaningful in strict mode, where that exclusion is absolute.
        Naming them turns an opaque "nobody is available" into a gap the
        manager can act on — they know exactly whose day off to renegotiate.

        Anyone who could not have worked anyway is left out. Listing someone
        who is on leave, or has too few hours left to take a shift, points
        the manager at a renegotiation that would not have helped, and the
        previous version did exactly that: it named everyone with the weekday
        marked off, which is how a gap at 02:00 came to be blamed on staff
        who were never going to be there.

        Captured while the day is being filled, not at the end of the week.
        By Sunday almost everyone is near their cap, so judging it afterwards
        would clear every name and report "nobody is available" for a gap the
        manager could in fact have fixed.
        """
        if not self.strict_days_off:
            return []
        if day in self.blocked_by_day:
            return self.blocked_by_day[day]

        names = []
        for employee in self.employees:
            employee_id = employee["employee_id"]
            if day not in (employee.get("preferred_days_off") or []):
                continue
            if date_iso in self.employee_off_dates.get(employee_id, set()):
                continue  # on leave — the day off is not what is stopping them
            if not avail.is_active(employee):
                continue
            # Too few hours left to work a shift at all is a harder limit
            # than a preference, so freeing the preference changes nothing.
            cap = self.hour_caps.get(employee_id, employee.get("max_weekly_hours", 0))
            remaining = cap - self.hours_used.get(employee_id, 0.0)
            if remaining < float(self.shop.get("min_shift_hours") or 0) or remaining <= 0:
                continue
            names.append(employee["name"])

        self.blocked_by_day[day] = names
        return names

    def _capacity_shortfall(self) -> Optional[Dict[str, float]]:
        """Is the week impossible before it starts?

        Compares the bare coverage floor — one person for every hour the shop
        is open — against the hours the team is allowed to work. Deliberately
        the most generous reading of both: no allowance for the 5-day limit,
        for two people being needed at once, or for anybody's availability.
        If even THAT does not add up, no amount of clever scheduling will
        help, and the manager needs telling plainly rather than being handed
        sixty-six identical lines about leave and curfews.

        Cached: it is asked once per uncovered hour and the answer cannot
        change during a solve.
        """
        if self._shortfall_cache is not _UNSET:
            return self._shortfall_cache

        needed = 0.0
        for day in DAYS:
            if self.date_for_day.get(day) in self.shop_closed_dates:
                continue
            window = self.hours_by_day.get(day)
            if not window or window.get("closed"):
                continue
            open_m = to_minutes(window.get("open") or "00:00")
            close_m = to_minutes(window.get("close") or "00:00")
            if close_m <= open_m:      # closes after midnight
                close_m += 24 * 60
            needed += (close_m - open_m) / 60

        available = 0.0
        for employee in self.employees:
            if not avail.is_active(employee):
                continue
            available += avail.weekly_hour_cap(employee, self.week_start)

        # A margin, because this exists to catch the hopeless case rather
        # than to second-guess a week that is merely tight.
        self._shortfall_cache = (
            {"needed": needed, "available": available}
            if available < needed else None
        )
        return self._shortfall_cache

    def _report_unfilled(self, day: str, hour: int) -> None:
        """Record one uncovered or under-covered hour.

        Idempotent per (day, hour): the demand loop and the coverage-floor
        pass both reach the same hour, and reporting it twice both doubled
        the list the manager reads and doubled the compliance penalty.
        """
        if (day, hour) in self.reported_gaps:
            return
        self.reported_gaps.add((day, hour))

        required = self.demand.required(day, hour)
        actual = self.on_duty[day][hour]
        window = f"{hour:02d}:00-{(hour + 1) % 24:02d}:00"
        blocked = self._blocked_by_days_off(day, self.date_for_day[day])

        # Structured alongside the sentence, so the grid can mark the hour
        # rather than the manager reading it out of a paragraph.
        gap = {
            "day": day,
            "hour": hour,
            "window": window,
            "required": required,
            "actual": actual,
            "severity": "uncovered" if actual == 0 else "short",
        }
        self.result.gaps.append(gap)

        # A named person beats general arithmetic: knowing whose day off to
        # renegotiate is something the manager can act on this afternoon.
        #
        # Running out of staff altogether comes next, and replaces the old
        # catch-all. Telling a shop that needs 109 hours from 60 hours of
        # staff that "everyone is on leave or curfew-restricted" sent them
        # hunting for holidays and under-16s that did not exist. The same
        # shortfall is also stated once, up front, by _report_understaffed.
        if blocked:
            names = ", ".join(sorted(blocked)[:4])
            more = f" and {len(blocked) - 4} others" if len(blocked) > 4 else ""
            because = (
                f" {len(blocked)} staff ({names}{more}) requested this day off and "
                f"days off are set to strict."
            )
        elif self._capacity_shortfall():
            shortfall = self._capacity_shortfall()
            because = (
                f" There are not enough staff hours to cover this week: "
                f"{shortfall['needed']:.0f}h needed, "
                f"{shortfall['available']:.0f}h available."
            )
        else:
            because = (
                " Everyone else is on leave, at their hour cap, or curfew-restricted."
            )

        # The REASON is stored on the gap rather than written into a sentence
        # here. Consecutive uncovered hours are one hole in the day, and
        # _describe_gaps turns each run into a single line at the end —
        # six lines from 17:00 to 23:00 read as six problems needing six
        # decisions, when the manager needs one person for one stretch.
        gap["because"] = because
        if actual != 0:
            self.result.issues.append(
                f"{day} {window}: {actual}/{required} staffed.{because}"
            )

    def _warn_on_oversubscribed_days(self) -> None:
        """Flag days where requested time off outstrips who is left.

        Preferred days off are a soft preference, so the solver will override
        them rather than leave the shop short — but a day where most of the
        team has asked to be off is a rota problem the manager needs to know
        about in advance, not something to discover from a silently
        overridden roster.
        """
        if not self.demand:
            return

        for day in DAYS:
            date_iso = self.date_for_day[day]
            if date_iso in self.shop_closed_dates:
                continue
            hours = self.hours_by_day.get(day)
            if not hours or hours.get("closed"):
                continue

            available = [
                e for e in self.employees
                if day not in (e.get("preferred_days_off") or [])
                and date_iso not in self.employee_off_dates.get(e["employee_id"], set())
            ]
            peak = max(
                (self.demand.required(day, h) for h in self._open_hours(day)),
                default=0,
            )
            if peak and len(available) < peak:
                requested_off = sum(
                    1 for e in self.employees
                    if day in (e.get("preferred_days_off") or [])
                )
                self.result.issues.append(
                    f"{day}: only {len(available)} staff are available but up to {peak} "
                    f"are needed at once ({requested_off} requested the day off, plus "
                    f"anyone on leave). Some preferences will be overridden."
                )

    def _trading_days(self) -> List[Tuple[str, str, int, int]]:
        """(day, date, open, close) for each day the shop actually trades."""
        trading = []
        for day in DAYS:
            date_iso = self.date_for_day[day]
            if date_iso in self.shop_closed_dates:
                continue
            hours = self.hours_by_day.get(day)
            if not hours or hours.get("closed"):
                continue

            open_m, close_m = to_minutes(hours["open"]), to_minutes(hours["close"])
            if close_m <= open_m:
                # Closing at or before opening means the day runs past
                # midnight — 22:00-06:00, or 00:00-00:00 for round-the-clock.
                # Treating that as a zero-length day skipped it entirely, so
                # a 24-hour shop configured the obvious way got no roster at
                # all and no explanation for it.
                close_m += 24 * 60
            trading.append((day, date_iso, open_m, close_m))
        return trading

    # -- main loop --------------------------------------------------------
    def solve(self) -> SolveResult:
        """Three passes over the week, in this order for a reason.

        Coverage wraps: Sunday's night shift is what covers Monday's small
        hours. So no hour can be judged short until every day is placed —
        doing it day by day made Monday look unattended at 02:00 while the
        shift covering it had not been created yet, and then double-staffed
        it once that shift appeared.

          1. fill each day to its learned demand
          2. then guarantee the floor, with the whole week visible
          3. then report whatever is still short
        """
        self._warn_on_oversubscribed_days()
        trading = self._trading_days()
        # Every day is still SET UP — leave, pins and fixed shifts are applied
        # across the week, so hours and rest gaps are counted against the real
        # week rather than against one day in isolation. Only the filling is
        # narrowed.
        fill = [t for t in trading if self.only_day in (None, t[0])]
        # Shared so the coverage pass, which may place a shift on the
        # previous day, still respects one shift per person per day.
        assigned_by_day = self.assigned_by_day

        # Pass 0 — what is already fixed: booked leave and recurring shifts.
        # Separated from the fill so the passes that follow all see the same
        # starting state, whichever day they are looking at.
        for day, date_iso, open_m, close_m in trading:
            # Recorded before this day spends anyone's hours, so a gap can be
            # explained by the day off that actually caused it.
            self._blocked_by_days_off(day, date_iso)

            assigned_today: Set[str] = set()
            assigned_by_day[day] = assigned_today
            self._apply_paid_leave(day, date_iso, assigned_today)
            # Pinned before recurring: if the manager put somebody somewhere
            # by hand this week, that beats the standing arrangement.
            self._apply_locked_shifts(day, assigned_today)
            self._apply_fixed_shifts(day, date_iso, assigned_today)

        # Pass 0b — senior cover for every day, before anything else spends
        # their hours.
        #
        # Managers are the scarcest thing on the roster and the five-day
        # limit binds them hardest: filling Monday through Friday first left
        # both supervisors used up, and the weekend with nobody senior at
        # all. Claiming one day at a time across the whole week first is what
        # a manager does before filling anything else in.
        self._ensure_supervisory_cover(fill)

        # Pass 1 — demand.
        for day, date_iso, open_m, close_m in fill:
            assigned_today = assigned_by_day[day]

            if self.demand is not None and self.demand.slots_for(day):
                # Slot-driven: rebuild the shifts this shop actually runs.
                self._staff_by_slots(day, date_iso, assigned_today, open_m, close_m)
            elif self.demand is not None:
                # Enough history for a curve but not for a day's shape —
                # fill until the learned curve is satisfied.
                self._staff_by_demand(day, date_iso, assigned_today)
            else:
                # No profile available — the original block behaviour.
                for segment in segments_for_day(self.shop, open_m, close_m):
                    self._staff_segment(segment, day, date_iso, assigned_today, open_m, close_m)

        # Pass 2 — the coverage floor is a separate, non-negotiable
        # guarantee: the curve says "how many", this says "never zero".
        if self.demand is not None:
            for day, date_iso, open_m, close_m in fill:
                self._enforce_coverage_floor(
                    day, date_iso, assigned_by_day[day], open_m, close_m
                )

        # Pass 2b — salaried staff are owed their hours.
        #
        # Reproducing the historical shape can leave a full-timer short, and
        # their payslip is the same either way, so a short week is hours the
        # shop has already bought and not used. Extra shifts are added for
        # them beyond the usual shape, and the day is reported as busier
        # than normal so the decision is visible rather than silent.
        if self.demand is not None:
            self._top_up_contracts(fill)
            # Then flex finish times, because a fifth shift of any available
            # length may overshoot while half an hour on an existing one
            # lands exactly.
            self._fit_contract_hours()
            # Finally, stretch a neighbouring shift over any hour still one
            # body short — cheaper and closer to the real rota than adding a
            # whole extra person for a single hour at changeover.
            self._close_short_hours()

        # Pass 2c — share the hours out against what people actually work.
        #
        # Last of the building passes, and deliberately so: coverage,
        # contracts and the demand shape are all settled by here, so what is
        # left is only the question of who holds the shifts nobody has a
        # claim on. Running it earlier would have it arguing with passes that
        # are answering harder questions.
        if self.demand is not None:
            self._rebalance_hours()

        # Pass 3 — report against final coverage.
        if self.demand is not None:
            for day, _, _, _ in trading:
                for hour in self._open_hours(day):
                    if self.on_duty[day][hour] < self.demand.required(day, hour) \
                            or self.on_duty[day][hour] == 0:
                        self._report_unfilled(day, hour)

        # Senior cover is repaired in pass 2a, so a second warning here would
        # only restate what that pass already reported when it could not.

        self._drop_duplicate_days()
        self._finalise()
        return self.result

    def _enforce_coverage_floor(
        self, day: str, date_iso: str, assigned_today: Set[str],
        open_m: int, close_m: int,
    ) -> None:
        """Guarantee at least one person whenever the shop is open (RULES 2/3).

        The demand curve is a target and can legitimately be zero for an hour
        the shop rarely staffs. The floor is not negotiable, so it is checked
        separately: any open hour still showing nobody gets one more pass,
        with soft preferences relaxed.

        A gap in the small hours is filled by a shift on the PREVIOUS day —
        nobody covers Sunday 02:00 by starting work on Sunday. So each hour
        is offered to patterns starting today and, failing that, to patterns
        starting yesterday.
        """
        for hour in self._open_hours(day):
            if self.on_duty[day][hour] > 0:
                continue
            if self._fill_one_hour(day, date_iso, hour, assigned_today, open_m, close_m):
                continue
            # Nothing else to do here. Pass 3 judges the finished week, once
            # every day's shifts — including the overnight ones that wrap
            # into the following morning — are in place.

    def _fill_one_hour(
        self, day: str, date_iso: str, hour: int,
        assigned_today: Set[str], open_m: int, close_m: int,
    ) -> bool:
        """Put one person on the floor at (day, hour). True if it worked."""
        previous = DAYS[(DAYS.index(day) - 1) % 7]
        patterns = self.demand.patterns if self.demand else []

        # Today first: a shift on the day itself is the ordinary answer, and
        # only the small hours genuinely need yesterday's night shift.
        for start_day in (day, previous):
            start_date = self.date_for_day[start_day]
            if start_date in self.shop_closed_dates:
                continue
            # Also skip a day the shop simply does not trade. Only the
            # one-off closure list was checked here, so repairing Monday's
            # small hours could start somebody's shift on a Sunday the shop
            # is shut all day.
            start_hours = self.hours_by_day.get(start_day)
            if not start_hours or start_hours.get("closed"):
                continue
            # Whoever already has a shift on the day we would be placing on.
            # Reusing today's set for a shift placed yesterday would let one
            # person be rostered twice on the same day.
            already = self.assigned_by_day.setdefault(
                start_day, assigned_today if start_day == day else set()
            )
            reachable = [
                p for p in patterns
                if (day, hour) in set(self.hours_covered(
                    start_day, p.start, p.end, wrap_week=self.wrap_week
                ))
            ]
            # Prefer a shape that fills the hour WITHOUT pushing a
            # neighbouring one over its historical level. A 23:30-07:00
            # night shift plugs Monday 00:00 and then quietly adds a fourth
            # body to a 06:00 that has always had three; a shorter overnight
            # pattern does the same job without the spill.
            tidy = [
                p for p in reachable
                if not self._would_overstaff(start_day, p.start, p.end)
            ]
            # Coverage still wins if nothing fits cleanly — an empty hour is
            # worse than an overlapping one.
            reachable = tidy or reachable

            for pattern in sorted(reachable, key=lambda p: p.count, reverse=True):
                segment = Segment(start=pattern.start, end=pattern.end, min_staff=1)
                for relax in (False, True):
                    eligible = [
                        e for e in self.employees
                        if self._is_eligible(
                            e, segment, start_day, start_date, already,
                            open_m, close_m, relax_preferences=relax,
                        )
                    ]
                    if not eligible:
                        continue
                    best = min(
                        eligible,
                        key=lambda e: self._rank_for_demand(
                            e, pattern.key, start_day, pattern.covers()
                        ),
                    )
                    self._record_shift(
                        best["employee_id"], start_day, pattern.start, pattern.end,
                        coverage_fallback=True,
                    )
                    already.add(best["employee_id"])
                    if start_day in (best.get("preferred_days_off") or []):
                        self._note_relaxed_preference(best, start_day)
                    return True
        return False

    def _ensure_supervisory_cover(
        self, trading: List[Tuple[str, str, int, int]]
    ) -> None:
        """Put a manager or supervisor on any day that has none.

        The check used to be a warning printed after the fact, which told
        the manager about a day with nobody senior on it but did nothing to
        fix it. Senior cover is the kind of thing a shop cannot open
        without, so it is now repaired like any other gap: find the busiest
        slot on that day, and give it to the most senior person available.
        """
        for day, date_iso, open_m, close_m in trading:
            if self._has_supervisor(day):
                continue

            seniors = [
                e for e in hierarchy.sort_employees(self.employees, self.shop)
                if hierarchy.is_supervisory(e.get("role"), self.shop)
            ]
            if not seniors:
                return  # the shop has nobody senior at all; nothing to place

            # Their usual shapes first, so the fix looks like a normal shift —
            # but a shape somebody else OWNS is tried last.
            #
            # This pass runs before the slot fill, so without that a manager
            # would be dropped straight onto the opening that a floor
            # assistant has worked every week for months, and ownership would
            # never get a say. Senior cover is still guaranteed: an owned
            # shape is only skipped while an unowned one will do.
            # Where to put them, best first:
            #
            #   0  a shape one of the seniors already owns — their own shift
            #   1  a shape nobody owns
            #   2  somebody else's shift, weakest claim first
            #
            # This pass runs before the slot fill, so without an ordering a
            # manager would be dropped onto whichever shape is most common —
            # usually the opening that a floor assistant has worked every
            # week for months. Senior cover is still guaranteed; it just
            # takes the least disruptive place to stand.
            senior_ids = {e["employee_id"] for e in seniors}

            def placement_rank(pattern):
                owner = slot_owners.owner_of(
                    self.slot_owners, day, pattern.start, pattern.end,
                )
                if owner in senior_ids:
                    return (0, -pattern.count)
                if owner is None:
                    return (1, -pattern.count)
                return (
                    2,
                    slot_owners.ownership_strength(
                        self.slot_owners, day, pattern.start, pattern.end,
                    ),
                    -pattern.count,
                )

            patterns = sorted(
                (p for p in (self.demand.patterns if self.demand else []) if p.covers()),
                key=placement_rank,
            )
            assigned_today = self.assigned_by_day.setdefault(day, set())
            placed = False
            for pattern in patterns:
                if placed:
                    break
                segment = Segment(start=pattern.start, end=pattern.end, min_staff=1)
                for relax in (False, True):
                    eligible = [
                        e for e in seniors
                        if self._is_eligible(
                            e, segment, day, date_iso, assigned_today,
                            open_m, close_m, relax_preferences=relax,
                        )
                    ]
                    if not eligible:
                        continue
                    best = eligible[0]  # already in seniority order
                    finish = self._fit_length_to_contract(
                        best, day, pattern.start, pattern.end
                    )
                    self._record_shift(
                        best["employee_id"], day, pattern.start, finish,
                        supervisory_cover=True,
                    )
                    assigned_today.add(best["employee_id"])
                    if relax:
                        self._note_relaxed_preference(best, day)
                    placed = True
                    break

            if not placed:
                self.result.issues.append(
                    f"No manager or supervisor could be rostered on {day}. "
                    f"Everyone senior is on leave, at their hour limit, or "
                    f"already working five days."
                )

    def _has_supervisor(self, day: str) -> bool:
        return any(
            hierarchy.is_supervisory(
                self.employees_by_id.get(s["employee_id"], {}).get("role"), self.shop
            )
            for s in self.result.shifts
            if s["day"] == day and not s.get("paid_holiday")
        )

    def _check_supervisory_cover(self, day: str) -> None:
        has_supervisor = any(
            hierarchy.is_supervisory(
                self.employees_by_id.get(s["employee_id"], {}).get("role"), self.shop
            )
            for s in self.result.shifts
            # Someone on paid holiday is not supervising anything.
            if s["day"] == day and not s.get("paid_holiday")
        )
        if not has_supervisor:
            self.result.issues.append(f"No manager or supervisor scheduled on {day}.")

    def _report_unrostered(self) -> None:
        """Account for every active employee who got no shifts.

        Requirement: nobody is silently omitted. A new starter with no
        history is the case that matters most — without this they simply
        never appear, and there is no way to tell that from a bug.
        """
        rostered = {s["employee_id"] for s in self.result.shifts}
        for employee in hierarchy.sort_employees(self.employees, self.shop):
            employee_id = employee["employee_id"]
            if employee_id in rostered or not avail.is_active(employee):
                continue

            reason = self.exclusions.get(employee_id)
            if not reason:
                # Passed every check and still got nothing: the week was
                # already covered before their turn came round.
                reason = (
                    "Not needed — staffing levels were met before they were "
                    "reached in the ordering."
                )
            self.result.unrostered.append({
                "employee_id": employee_id,
                "name": employee.get("name", employee_id),
                "role": employee.get("role", ""),
                "reason": reason,
            })

        if self.result.unrostered:
            names = ", ".join(u["name"] for u in self.result.unrostered[:5])
            more = (
                f" and {len(self.result.unrostered) - 5} others"
                if len(self.result.unrostered) > 5 else ""
            )
            self.result.issues.append(
                f"{len(self.result.unrostered)} active employee(s) received no shifts "
                f"({names}{more}). See the unrostered list for reasons."
            )

    def _order_shifts_for_display(self) -> None:
        """Sort the output the way the shop reads it, then by day.

        Display order, not allocation order: if the manager has arranged the
        rows by hand, the exported sheet and the emailed schedule follow that
        arrangement. Who was considered first for hours is a separate
        question and stays on the job ladder.

        Done once here so every consumer — grid, print view, export, email —
        gets the same order without each having to re-sort.
        """
        order = {
            e["employee_id"]: index
            for index, e in enumerate(hierarchy.display_order(self.employees, self.shop))
        }
        day_index = {day: i for i, day in enumerate(DAYS)}
        self.result.shifts.sort(
            key=lambda s: (
                order.get(s["employee_id"], len(order)),
                day_index.get(s["day"], 7),
                s.get("start") or "",
            )
        )

    # Under this, a shortfall is rounding rather than a real gap in someone's
    # week, and reporting it would be noise.
    _CONTRACT_TOLERANCE_HOURS = 0.5

    def _describe_gaps(self) -> None:
        """One sentence per RUN of uncovered hours, not per hour."""
        for run in collapse_hour_runs(
            [g for g in self.result.gaps if g.get("severity") == "uncovered"]
        ):
            hours = run["hours"]
            self.result.critical_issues.append(
                f"CRITICAL: {run['day']} {run['window']} has NO coverage"
                + (f" ({hours} hours)" if hours > 1 else "")
                + f" — the shop would be left unattended.{run['because']}"
            )

    def _report_under_contract(self) -> None:
        """Name any salaried full-timer whose week came in short.

        Only full-time contracts are checked. Their hours are OWED: the
        payslip is the same whether they work 41 or 42.5, so a short week is
        money the shop paid for and did not use. An hourly employee's
        contract is a ceiling rather than a floor, and reporting them for
        working under it flagged the entire team every single week.

        Measured in hours on the floor, breaks included, because that is how
        the contract is written. Comparing a 42.5h contract against paid
        hours would show everybody permanently short by the length of their
        breaks.

        Anyone with booked leave that week is skipped: a week broken by
        holiday or sickness cannot reach the band, and saying so every time
        would bury the cases where the shop simply did not roster somebody.
        """
        holiday_span: Dict[str, float] = {}
        for shift in self.result.shifts:
            if shift.get("paid_holiday"):
                # A holiday day stands in for the shift it replaced, so it
                # counts toward the contract at a normal day's length.
                holiday_span[shift["employee_id"]] = (
                    holiday_span.get(shift["employee_id"], 0.0) + shift_paid_hours(shift)
                )

        for employee in hierarchy.display_order(self.employees, self.shop):
            employee_id = employee["employee_id"]
            if not avail.is_active(employee):
                continue

            band = self.span_bands.get(employee_id)
            if not band:
                continue  # hourly or student — capped, not targeted

            if self.employee_off_dates.get(employee_id):
                continue  # leave that week; the band is not reachable

            minimum, target = band
            rostered = (
                self.span_used.get(employee_id, 0.0)
                + holiday_span.get(employee_id, 0.0)
            )
            short = minimum - rostered
            if short <= self._CONTRACT_TOLERANCE_HOURS:
                continue

            self.result.under_contract.append({
                "employee_id": employee_id,
                "name": employee.get("name", employee_id),
                "role": employee.get("role", ""),
                "contracted_hours": round(target, 1),
                "minimum_hours": round(minimum, 1),
                "rostered_hours": round(rostered, 1),
                "short_hours": round(short, 1),
            })

        if self.result.under_contract:
            worst = max(self.result.under_contract, key=lambda u: u["short_hours"])
            self.result.issues.append(
                f"{len(self.result.under_contract)} contracted employee(s) are below "
                f"their minimum hours, {worst['name']} by {worst['short_hours']:g}h. "
                f"They are paid the same either way, so those hours are unused."
            )

    def _top_up_contracts(self, trading: List[Tuple[str, str, int, int]]) -> None:
        """Give salaried staff extra shifts until they reach their minimum.

        Only full-time contracts: an hourly contract is a ceiling, not a
        floor, so somebody under their maximum is not owed anything.

        Uses the shapes the shop already runs, on days they are free, and
        stops the moment the band is reached. Everything else still applies —
        familiarity, curfew, days off, two days off a week — so a top-up
        cannot buy a rule breach.
        """
        patterns = [p for p in (self.demand.patterns if self.demand else []) if p.covers()]
        if not patterns:
            return

        for employee in hierarchy.sort_employees(self.employees, self.shop):
            employee_id = employee["employee_id"]
            band = self.span_bands.get(employee_id)
            if not band or not avail.is_active(employee):
                continue
            if self.employee_off_dates.get(employee_id):
                continue  # a week broken by leave cannot reach the band

            minimum = band[0]
            # Most common shapes first, so a top-up still looks like a shift
            # this shop runs rather than an odd block invented to fill hours.
            for pattern in sorted(patterns, key=lambda p: p.count, reverse=True):
                if self.span_used.get(employee_id, 0.0) >= minimum - 0.01:
                    break
                for day, date_iso, open_m, close_m in trading:
                    if self.span_used.get(employee_id, 0.0) >= minimum - 0.01:
                        break
                    assigned_today = self.assigned_by_day.setdefault(day, set())
                    segment = Segment(
                        start=pattern.start, end=pattern.end, min_staff=1
                    )
                    if not self._is_eligible(
                        employee, segment, day, date_iso, assigned_today,
                        open_m, close_m, relax_preferences=False,
                    ):
                        continue
                    self._record_shift(
                        employee_id, day, pattern.start, pattern.end,
                        contract_top_up=True,
                    )
                    assigned_today.add(employee_id)
                    self.result.issues.append(
                        f"{employee.get('name', employee_id)} was given an extra "
                        f"{pattern.start}-{pattern.end} on {day} to reach their "
                        f"{minimum:g}h contracted minimum."
                    )

    # Finish times are moved in half-hour steps, the granularity a rota is
    # actually written in. Anything finer produces shifts like 16:07.
    _FIT_STEP_MINUTES = 30

    def _reshape_shift(
        self, shift: Dict[str, Any], new_end: str, new_start: Optional[str] = None
    ) -> None:
        """Move a shift's start or finish, keeping every derived figure in step.

        Coverage counters, paid hours and span are all rebuilt, because a
        shift that changed length without them is a roster whose totals no
        longer describe it.
        """
        employee_id = shift["employee_id"]
        day, old_start, old_end = shift["day"], shift["start"], shift["end"]
        start = new_start or old_start
        role = self.employees_by_id.get(employee_id, {}).get("role") or ""

        for covered_day, hour in self.hours_covered(
            day, old_start, old_end, wrap_week=self.wrap_week
        ):
            self.on_duty[covered_day][hour] -= 1
            if role:
                self.role_on_duty[covered_day][role][hour] -= 1

        self.hours_used[employee_id] -= paid_hours(
            old_start, old_end, breaks_paid=self.breaks_paid
        )
        self.span_used[employee_id] -= shift_duration_minutes(old_start, old_end) / 60

        span = shift_duration_minutes(start, new_end) / 60
        shift["start"] = start
        shift["end"] = new_end
        shift["span_hours"] = round(span, 2)
        shift["break_minutes"] = 0 if self.breaks_paid else break_minutes(span)
        shift["paid_hours"] = round(
            paid_hours(start, new_end, breaks_paid=self.breaks_paid), 2
        )
        shift["length_adjusted"] = True

        for covered_day, hour in self.hours_covered(
            day, start, new_end, wrap_week=self.wrap_week
        ):
            self.on_duty[covered_day][hour] += 1
            if role:
                self.role_on_duty[covered_day][role][hour] += 1

        self.hours_used[employee_id] += paid_hours(
            start, new_end, breaks_paid=self.breaks_paid
        )
        self.span_used[employee_id] += span

    def _may_lengthen(
        self, shift: Dict[str, Any], new_start: str, new_end: str
    ) -> bool:
        """Whether stretching this shift stays inside every limit."""
        employee = self.employees_by_id.get(shift["employee_id"])
        if not employee:
            return False

        span = shift_duration_minutes(new_start, new_end) / 60
        max_shift = min(
            float(self.shop.get("max_shift_hours") or ABSOLUTE_MAX_SHIFT_HOURS),
            ABSOLUTE_MAX_SHIFT_HOURS,
        )
        if span > max_shift + 1e-6:
            return False

        if violates_minor_curfew(employee, new_start, new_end):
            return False

        # ELEVEN HOURS OF REST, WHICH THE REST OF THIS PASS ONLY CLAIMED TO
        # CHECK.
        #
        # `_close_short_hours` says in its own comments that a snap is
        # refused for "the 12-hour cap, the rest gap, a curfew". Two of those
        # three were true. Nothing here looked at rest, so a finish pushed an
        # hour later — or a start pulled an hour earlier — could eat into the
        # gap either side of it.
        #
        # Reported from the reference shop: "Kyle's fri shift was changed
        # from 10:00-19:00 to 10:00-20:00 to cover fri 19:00", leaving him
        # ten hours before his next shift. The roster then flagged him, so
        # the solver produced a breach and warned about its own work.
        #
        # This is the daily rest entitlement in the Organisation of Working
        # Time Act (§1 rule 6), not a preference, and §1 says what to do when
        # keeping it costs an hour of cover: leave the hour empty and say so.
        #
        # `_rest_breach` skips shifts on the same day, so a shift is never
        # compared against itself, and it checks BOTH directions — a start
        # moved earlier eats the gap from the previous day rather than the
        # next.
        if self._rest_breach(
            shift["employee_id"], shift["day"], new_start, new_end
        ) is not None:
            return False

        added_span = span - shift_duration_minutes(shift["start"], shift["end"]) / 60
        band = self.span_bands.get(shift["employee_id"])
        if band:
            if self.span_used.get(shift["employee_id"], 0.0) + added_span > band[1] + 1e-6:
                return False
        else:
            cap = self.hour_caps.get(
                shift["employee_id"], employee.get("max_weekly_hours", 0)
            )
            added_paid = (
                paid_hours(new_start, new_end, breaks_paid=self.breaks_paid)
                - paid_hours(shift["start"], shift["end"], breaks_paid=self.breaks_paid)
            )
            if self.hours_used.get(shift["employee_id"], 0.0) + added_paid > cap + 1e-6:
                return False

        # Moving a START changes what the shift IS to that person. An hour
        # either side is the same shift; more than that and they are being
        # asked to work something they do not work.
        if new_start != shift["start"]:
            if avail.check_familiarity(
                employee, new_start, new_end, self.shift_history
            ).warning:
                return False
            verdict = avail.check_availability(
                employee, shift["day"], new_start, new_end
            )
            if not verdict.allowed:
                return False

        return True

    def _close_short_hours(self) -> None:
        """Stretch a neighbouring shift over an hour that is one body short.

        A gap of an hour or two at a shift changeover does not need another
        person — it needs somebody finishing at 16:00 instead of 15:00, or
        starting at 15:00 instead of 16:00. That is what a manager does with
        a pen, and adding a whole extra shift for it would overstaff the rest
        of the day.

        Finishes are tried before starts. A finish time is just when somebody
        goes home; a start time is what the shift IS to them, and moving it
        risks handing them a shift they do not work.

        ONE ADVISORY PER SHIFT, NOT PER HOUR
        ------------------------------------
        A shift that is short by two consecutive hours gets stretched twice —
        once reaching 12:00, again reaching 13:00 — and reporting each pass
        separately read as two unrelated events:

            Emma's mon shift was changed from 06:00-12:00 to 06:00-12:30 ...
            Emma's mon shift was changed from 06:00-12:30 to 06:00-13:30 ...

        The manager does not care that it took two passes. They care that
        Emma's Monday finishes 90 minutes later than the generator first drew
        it. So stretches are accumulated per (person, day) and reported once
        at the end, from the ORIGINAL shape to the FINAL one.

        Same reasoning as compare_to_usual collapsing consecutive hours
        (CLAUDE.md §7c): a run of hours is one fact about the day.
        """
        if not self.demand:
            return

        # (employee_id, day) -> {"who", "was", "hours": [...]}. The final shape
        # is read off the shift itself at the end rather than tracked here,
        # because it is still being mutated while this runs.
        stretched: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for day in DAYS:
            # A frozen day is not re-solved, so it is not re-stretched either:
            # the promise of a single-day rebalance is that nothing else moves,
            # and half an hour on somebody's Friday finish is still a change
            # the manager did not ask for.
            if self.only_day not in (None, day):
                continue
            previous = DAYS[(DAYS.index(day) - 1) % 7]
            for hour in self._open_hours(day):
                required = self.demand.required(day, hour)
                # ONLY AN HOUR WITH NOBODY ON IT, NOT EVERY HOUR BELOW THE
                # AVERAGE.
                #
                # This used to fire whenever `on_duty < required`, and
                # `required` is a 24-week AVERAGE of bodies per hour while
                # the shifts placed are a DISCRETE list of the shop's real
                # shapes. Ten real shapes cannot reproduce an average hour by
                # hour, so the two disagree permanently: measured on the
                # reference shop, the shapes fall 24 hours short of the curve
                # and run 25 hours OVER it. Same total, different shape.
                #
                # Correcting only the short side then inflated every week and
                # produced one advisory per patched hour — eighteen in a
                # single week, each one a shift the manager had to read and
                # would not have written. He does not sit there eighteen
                # times thinking "not covered, let him finish an hour late".
                #
                # Measured over 8 weeks, narrowing this to genuinely empty
                # hours: advisories 15.1 -> 6.9, uncovered hours unchanged at
                # 0.8, and shifts matching the manager's own rota 38.6 -> 42.4
                # of 63.6. The week comes out 1.5% lighter and closer to the
                # shapes he actually writes.
                #
                # An hour that is short but not EMPTY is reported instead, by
                # "Against the usual" (§7c) — information the manager can act
                # on rather than a shift quietly made longer. An hour with
                # nobody on it is a different thing entirely: that is §1 rule
                # 1, and stretching a neighbour is much cheaper than adding a
                # whole shift for it.
                if required <= 0 or self.on_duty[day][hour] > 0:
                    continue

                nearby = [
                    s for s in self.result.shifts
                    if s.get("day") in (day, previous)
                    and s.get("start") and s.get("end")
                    and not s.get("pinned")  # the manager set these by hand
                    and not (s.get("paid_holiday") or s.get("unpaid_holiday")
                             or s.get("sick"))
                ]
                # Whoever has the most room in their week first, so the
                # stretch lands where it is least likely to cause a new
                # problem elsewhere.
                nearby.sort(key=lambda s: self._contract_need(
                    self.employees_by_id.get(s["employee_id"], {}), 1.0
                ))

                # One pass, not two. The old code tried a 30-minute stretch
                # and then a 60-minute one; snapping lands on the boundary
                # exactly, so a second attempt would retry the identical
                # candidate. If the snap is refused -- the 12-hour cap, the
                # rest gap, a curfew -- the hour stays short and is reported,
                # which is the honest outcome and what §1 asks for.
                for shift in nearby:
                    covered = set(self.hours_covered(
                        shift["day"], shift["start"], shift["end"],
                        wrap_week=self.wrap_week,
                    ))
                    if (day, hour) in covered:
                        continue

                    for later_finish in (True, False):
                        # SNAP TO THE HOUR, do not step towards it.
                        #
                        # This used to move the edge by 30 minutes and
                        # then ask hours_covered whether the hour was
                        # covered. It always said yes, because it floors a
                        # shift's start to the hour it falls in — so a
                        # finish moved to 17:30 "covered" 17:00 while the
                        # required headcount was still one short until
                        # 17:30. Measured on this shop: the solver was
                        # over-counting ~25 hours a week against the
                        # manager's own 12, and ending shifts on a half
                        # hour 11% of the time where the manager does it
                        # 0.2% of the time. Those were shapes the shop
                        # does not write and the manager would rewrite.
                        #
                        # Covering an hour means being there for ALL of
                        # it, so the edge lands on the boundary: finish at
                        # (hour+1):00, or start at hour:00. Costs up to
                        # half an hour more than the old stretch, and buys
                        # cover that is real rather than rounded into
                        # existence.
                        if later_finish:
                            candidate = (
                                shift["start"], f"{(hour + 1) % 24:02d}:00",
                            )
                        else:
                            candidate = (f"{hour:02d}:00", shift["end"])

                        # Two things stepping got for free and snapping has
                        # to state outright.
                        #
                        # WRONG WAY. A shift running 18:00-20:00 asked to
                        # reach hour 17 by its FINISH gives (18:00, 18:00),
                        # an empty shift. Stepping could not do this because
                        # it always moved outwards.
                        #
                        # TOO FAR. This pass exists for a CHANGEOVER hour —
                        # "somebody finishing at 16:00 instead of 15:00".
                        # Stepping was bounded to 30 or 60 minutes by
                        # construction. An unbounded snap is not: a shift
                        # ending 14:00 asked to cover hour 15 snaps to 16:00,
                        # a TWO HOUR extension. That is not a changeover
                        # adjustment, it is a missing shift — and covering it
                        # by quietly making somebody's day two hours longer
                        # is precisely the edit the manager then has to undo.
                        #
                        # Caught by test_an_occasional_coverer_does_not_
                        # outrank_contract_need, which noticed an owned
                        # 06:00-14:00 had silently become 06:00-16:00.
                        # Measured against the shape the shift STARTED with,
                        # not its current one. A shift short at 15:00, then
                        # 16:00, then 17:00 was being stretched an hour at a
                        # time — each step a legitimate changeover
                        # adjustment, the total a four-hour extension that
                        # nobody agreed to. (Pre-existing: the old 30-minute
                        # stepping accumulated the same way. It only became
                        # visible once the advisories were collapsed to report
                        # original-shape-to-final, which is the argument for
                        # having collapsed them.)
                        #
                        # Four consecutive short hours is a missing shift.
                        # Leaving it short says so; hiding it inside somebody
                        # else's day does not.
                        started_as = stretched.get(
                            (shift["employee_id"], shift["day"]), {}
                        ).get("was")
                        base = (tuple(started_as.split("-")) if started_as
                                else (shift["start"], shift["end"]))
                        grew = (shift_duration_minutes(*candidate)
                                - shift_duration_minutes(*base))
                        if not 0 < grew <= self._FIT_STEP_MINUTES * 2:
                            continue

                        reaches = (day, hour) in set(self.hours_covered(
                            shift["day"], candidate[0], candidate[1],
                            wrap_week=self.wrap_week,
                        ))
                        if not reaches or not self._may_lengthen(
                            shift, candidate[0], candidate[1]
                        ):
                            continue

                        who = self.employees_by_id.get(
                            shift["employee_id"], {}
                        ).get("name", shift["employee_id"])
                        was = f"{shift['start']}-{shift['end']}"
                        self._reshape_shift(shift, candidate[1], candidate[0])

                        key = (shift["employee_id"], shift["day"])
                        record = stretched.get(key)
                        if record is None:
                            # First stretch of this shift: remember the
                            # shape the generator originally drew, which is
                            # the only one the manager ever saw.
                            stretched[key] = {
                                "who": who, "was": was,
                                "shift": shift, "hours": [(day, hour)],
                            }
                        else:
                            record["hours"].append((day, hour))
                        break
                    if self.on_duty[day][hour] >= required:
                        break

        for record in stretched.values():
            shift = record["shift"]
            now = f"{shift['start']}-{shift['end']}"
            if now == record["was"]:
                continue  # stretched and then trimmed back; nothing to say
            hours = record["hours"]
            # "to cover mon 12:00" for one, "to cover mon 12:00-14:00" for a
            # run. The end is the LAST hour + 1: covering 12:00 and 13:00 means
            # being there until 14:00, and saying "12:00-13:00" would describe
            # an hour less than was actually needed.
            if len(hours) == 1:
                covering = f"{hours[0][0]} {hours[0][1]:02d}:00"
            else:
                first, last = hours[0], hours[-1]
                covering = (f"{first[0]} {first[1]:02d}:00-{last[1] + 1:02d}:00"
                            if first[0] == last[0]
                            else f"{first[0]} {first[1]:02d}:00 and "
                                 f"{last[0]} {last[1]:02d}:00")
            self.result.issues.append(
                f"{record['who']}'s {shift['day']} shift was changed from "
                f"{record['was']} to {now} to cover {covering}."
            )

    def _can_shorten_to(self, shift: Dict[str, Any], new_end: str) -> bool:
        """Whether trimming a finish would leave an hour under-staffed."""
        if not self.demand:
            return True
        dropped = set(
            self.hours_covered(shift["day"], shift["start"], shift["end"],
                               wrap_week=self.wrap_week)
        ) - set(
            self.hours_covered(shift["day"], shift["start"], new_end,
                               wrap_week=self.wrap_week)
        )
        for day, hour in dropped:
            if self.on_duty[day][hour] - 1 < self.demand.required(day, hour):
                return False
        return True

    def _fit_contract_hours(self) -> None:
        """Flex salaried staff's finish times until their week lands in band.

        A contract is a number of hours, not a set of shift shapes. Reusing
        the shop's historical patterns unchanged meant somebody on four
        ten-hour shifts sat at 40h and could not move: a fifth shift of any
        available length overshoots 42.5, so 41 was unreachable and the
        roster reported them short every week.

        A manager solves that by finishing them at 15:30 instead of 16:00, or
        stretching a shift to 9 hours. The start time is left alone — that is
        what the day's shape needs and what the person is used to — and only
        the finish moves.

        Limits are never traded away for hours: the absolute ceiling, the
        shop's own maximum, the curfew and the demand curve all still hold.
        """
        if not self.span_bands:
            return

        min_shift = float(self.shop.get("min_shift_hours") or 0)
        max_shift = min(
            float(self.shop.get("max_shift_hours") or ABSOLUTE_MAX_SHIFT_HOURS),
            ABSOLUTE_MAX_SHIFT_HOURS,
        )
        step = self._FIT_STEP_MINUTES

        for employee in hierarchy.sort_employees(self.employees, self.shop):
            employee_id = employee["employee_id"]
            band = self.span_bands.get(employee_id)
            if not band or not avail.is_active(employee):
                continue
            if self.employee_off_dates.get(employee_id):
                continue  # a week broken by leave cannot reach the band

            minimum, maximum = band
            mine = [
                s for s in self.result.shifts
                if s["employee_id"] == employee_id and s.get("start") and s.get("end")
                and not s.get("pinned")  # a pinned shift is not ours to resize
                # Nor is a shift on a day we were told not to touch.
                and self.only_day in (None, s.get("day"))
                and not (s.get("paid_holiday") or s.get("unpaid_holiday") or s.get("sick"))
            ]
            if not mine:
                continue

            # Longest first when trimming, shortest first when stretching, so
            # the change lands where it least distorts the day.
            for _ in range(40):  # bounded; each pass moves at least one shift
                used = self.span_used.get(employee_id, 0.0)
                if minimum - 0.01 <= used <= maximum + 0.01:
                    break

                short_by = minimum - used
                over_by = used - maximum
                moved = False

                order = sorted(
                    mine,
                    key=lambda s: s.get("span_hours", 0),
                    reverse=over_by > 0,
                )
                for shift in order:
                    span = shift_duration_minutes(shift["start"], shift["end"]) / 60
                    if short_by > 0:
                        room = min(
                            max_shift - span,
                            maximum - used,
                            short_by if short_by > step / 60 else step / 60,
                        )
                    else:
                        room = -min(
                            span - min_shift,
                            over_by if over_by > step / 60 else step / 60,
                        )
                    if abs(room) < step / 60 - 1e-6:
                        continue

                    delta = (int(room * 60) // step) * step
                    if delta == 0:
                        continue
                    new_end_m = (to_minutes(shift["end"]) + delta) % (24 * 60)
                    new_end = f"{new_end_m // 60:02d}:{new_end_m % 60:02d}"

                    if violates_minor_curfew(employee, shift["start"], new_end):
                        continue
                    if delta < 0 and not self._can_shorten_to(shift, new_end):
                        continue
                    # A CONTRACT IS NOT A REASON TO BREAK A STATUTORY REST
                    # PERIOD.
                    #
                    # This pass pushes a finish later to land a salaried
                    # employee inside their band, and checked only the
                    # curfew. Measured on the reference shop it left eight
                    # hours before the next morning's shift — worse than the
                    # ten `_close_short_hours` produced, because a band can
                    # ask for a bigger extension than a changeover hour can.
                    #
                    # The hours the contract cannot reach this way are
                    # reported by `under_contract` instead, which is what
                    # that report is for.
                    if delta > 0 and self._rest_breach(
                        employee_id, shift["day"], shift["start"], new_end
                    ) is not None:
                        continue

                    self._reshape_shift(shift, new_end)
                    moved = True
                    break

                if not moved:
                    break

    def _report_thin_days(self) -> None:
        """Flag a day staffed by fewer people than the shop normally uses.

        The hourly curve can be satisfied by a handful of long shifts while
        the day still feels wrong on the floor — cover at 13:00 says nothing
        about how many bodies a Sunday actually takes. This compares against
        the average headcount per day over the learned window, which is the
        number a manager recognises.
        """
        if not self.demand:
            return

        for day in DAYS:
            target = self.demand.staff_target(day)
            if target <= 0:
                continue
            actual = len({
                s["employee_id"] for s in self.result.shifts
                if s["day"] == day and not (
                    s.get("paid_holiday") or s.get("unpaid_holiday") or s.get("sick")
                )
            })
            if actual >= target:
                continue

            self.result.thin_days.append({
                "day": day,
                "rostered": actual,
                "usual": target,
                "short_by": target - actual,
            })
            self.result.issues.append(
                f"{day}: {actual} staff rostered, but this shop normally runs "
                f"{target} on a {day}. {target - actual} short."
            )

    def _collapse_repeated_issues(self) -> None:
        """Fold per-day repeats into one line each.

        Somebody on leave for four days produced four identical sentences,
        and an hour short across a whole day produced one per hour. Sixty
        lines of near-identical text is not a report a manager reads — the
        important ones drown.
        """
        skipped: Dict[str, List[str]] = {}
        short_hours: Dict[str, List[str]] = {}
        kept: List[str] = []

        for issue in self.result.issues:
            fixed = re.match(r"^(.+?) has a fixed shift on (\w+) but is on leave", issue)
            if fixed:
                skipped.setdefault(fixed.group(1), []).append(fixed.group(2))
                continue
            short = re.match(r"^(\w{3}) (\d{2}:\d{2}-\d{2}:\d{2}): (\d+)/(\d+) staffed", issue)
            if short:
                short_hours.setdefault(short.group(1), []).append(short.group(2))
                continue
            kept.append(issue)

        for name, days in skipped.items():
            kept.append(
                f"{name}'s fixed shift was skipped on {', '.join(days)} — on leave."
            )
        for day, windows in short_hours.items():
            kept.append(
                f"{day}: one short of the usual cover for {len(windows)} hour(s) "
                f"({windows[0].split('-')[0]}–{windows[-1].split('-')[1]})."
            )

        self.result.issues = kept

    def _report_inactive_rules(self) -> None:
        if not self.inactive_rules:
            return
        names = ", ".join(f'"{t}"' for t in self.inactive_rules[:4])
        more = (
            f" and {len(self.inactive_rules) - 4} more"
            if len(self.inactive_rules) > 4 else ""
        )
        self.result.issues.append(
            f"{len(self.inactive_rules)} custom rule(s) were NOT applied to this "
            f"roster because they could not be read: {names}{more}. "
            f"Reword them more plainly, e.g. \"Sarah never works Sundays\"."
        )

    def _report_understaffed(self) -> None:
        """One headline when the week could never have been covered.

        The per-hour lines already say so, but sixty-six of them scroll the
        cause off the screen. This puts the arithmetic first, and states the
        remedy in the manager's terms — more people, or longer hours for the
        ones they have.
        """
        shortfall = self._capacity_shortfall()
        if not shortfall:
            return

        team = [e for e in self.employees if avail.is_active(e)]
        gap = shortfall["needed"] - shortfall["available"]
        self.result.critical_issues.insert(0, (
            f"NOT ENOUGH STAFF: this week needs {shortfall['needed']:.0f}h of cover "
            f"and your {len(team)} available staff can work at most "
            f"{shortfall['available']:.0f}h — short by {gap:.0f}h. "
            f"No roster can cover the shop until you add people or raise "
            f"weekly hour limits."
        ))

    def _finalise(self) -> None:
        self._report_unrostered()
        self._describe_gaps()
        self._report_under_contract()
        self._report_understaffed()
        self._report_thin_days()
        self._collapse_repeated_issues()
        self._report_inactive_rules()
        self._order_shifts_for_display()
        rates = {e["employee_id"]: e.get("hourly_rate", 0) for e in self.employees}
        self.result.labor_cost = sum(
            shift_paid_hours(s) * rates.get(s["employee_id"], 0)
            for s in self.result.shifts
        )
        self.result.total_hours = sum(self.hours_used.values())
        self.result.per_employee_hours = dict(self.hours_used)

        # Against the caps in force this week (a student's summer ceiling
        # differs from their term-time one), and only for active staff.
        capacity = sum(
            self.hour_caps.get(e["employee_id"], 0)
            for e in self.employees if avail.is_active(e)
        ) or 1
        self.result.utilization = (self.result.total_hours / capacity) * 100

        self.result.compliance_score = self._score()

    def _score(self) -> int:
        """How well the week is covered, 0-100.

        Measured against the size of the week rather than by counting
        messages. A flat penalty per issue saturates almost immediately —
        at 25 points each, four uncovered hours and four hundred scored the
        same zero, so the number could not tell "one bad night" from "no
        roster at all", which is the only thing it is for.

        Uncovered hours dominate because an unattended shop is a broken
        guarantee; being one person below target is a planning note.
        """
        open_hours = sum(len(self._open_hours(day)) for day in DAYS) or 1

        uncovered = sum(
            1 for day in DAYS for hour in self._open_hours(day)
            if self.on_duty[day][hour] == 0
        )
        understaffed = sum(
            1 for day in DAYS for hour in self._open_hours(day)
            if self.on_duty[day][hour] > 0
            and self.demand is not None
            and self.on_duty[day][hour] < self.demand.required(day, hour)
        )

        # An unattended hour costs ~7x an understaffed one: the first breaks
        # a rule, the second misses a target.
        penalty = 100 * (uncovered * 1.0 + understaffed * 0.15) / open_hours

        # Problems that are not about coverage at all — a fixed shift that
        # had to be skipped, a day with no supervisor — still matter, but
        # cannot on their own drive a well-covered week to zero.
        other = len(self.result.critical_issues) - uncovered
        penalty += max(0, other) * 3

        return int(max(0, min(100, round(100 - penalty))))


def solve_roster(
    shop: Dict[str, Any],
    employees: List[Dict[str, Any]],
    holidays: List[Dict[str, Any]],
    fixed_shifts: List[Dict[str, Any]],
    ai_rules: List[Dict[str, Any]],
    week_start: str,
    weights: Optional[Dict[str, Any]] = None,
    demand: Optional[Any] = None,
    history_rosters: Optional[List[Dict[str, Any]]] = None,
    locked_shifts: Optional[List[Dict[str, Any]]] = None,
    seed: Optional[int] = None,
    only_day: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a week's roster. Pure function — same inputs, same output.

    `seed` varies the choices that are genuinely arbitrary: who takes a slot
    nobody owns, when several people are equally entitled to it. The same seed
    always gives the same roster, so a version can be reproduced. Settled
    shifts do not move whatever the seed is.

    `demand` is an optional DemandProfile. With one, the solver fills to a
    learned hourly staffing curve using the shop's own shift patterns. Without
    one it falls back to block-based coverage, which is what a shop with too
    little history gets.
    """
    builder = _RosterBuilder(
        shop, employees, holidays, fixed_shifts, ai_rules, week_start,
        weights or {}, demand, history_rosters, locked_shifts, seed, only_day,
    )
    return builder.solve().to_dict()
