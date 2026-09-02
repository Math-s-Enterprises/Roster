"""Staffing demand learned from a shop's own approved rosters.

Answers three questions the scheduler cannot answer on its own:

  1. How many people are needed, per day, per hour?   -> DemandProfile.headcount
  2. Which roles make up that headcount?              -> DemandProfile.role_mix
  3. Which shift shapes does this shop actually use?  -> DemandProfile.patterns

All three are measured from history rather than configured, because a shop
owner can rarely write down their own staffing curve accurately, but their
last three months of rosters describe it exactly.

Pure and synchronous: callers fetch the rosters, this transforms them. That
keeps it unit-testable without a database and cacheable by the caller.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.learning import latest_per_week
from app.services.scheduler import DAYS, to_minutes

HOURS_PER_DAY = 24

# Learn from a trailing window rather than all history, so the curve follows
# seasonal change instead of averaging a whole year into a flat line. Twenty-
# four weeks is half a year: long enough that one unusual fortnight cannot
# distort the shape, short enough to still track a season.
DEFAULT_LOOKBACK_WEEKS = 24

# Below this much history a learned curve is noise, and the caller should fall
# back to the simpler block-based behaviour.
MIN_WEEKS_FOR_DEMAND = 4

# Only patterns that appear at least this often are offered to the solver. One
# odd shift somebody worked once should not become a template.
MIN_PATTERN_OCCURRENCES = 3
MAX_PATTERNS = 25


@dataclass
class ShiftPattern:
    start: str
    end: str
    count: int
    hours: float

    @property
    def key(self) -> str:
        return f"{self.start}-{self.end}"

    def covers(self) -> List[int]:
        """Hours of the day this pattern is on the floor for.

        Overnight patterns wrap, so 23:30-07:00 yields [23, 0, 1, ... 6].
        """
        start_m, end_m = to_minutes(self.start), to_minutes(self.end)
        if end_m <= start_m:
            end_m += 24 * 60
        return sorted({(m // 60) % 24 for m in range(start_m, end_m, 60)})


@dataclass
class DemandProfile:
    """A shop's staffing shape. All grids are [day][hour]."""

    headcount: Dict[str, List[int]] = field(default_factory=dict)
    role_mix: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)
    patterns: List[ShiftPattern] = field(default_factory=list)
    weeks_observed: int = 0
    source: str = "learned"
    # How many people the shop actually put on each day, averaged over the
    # window. The hourly curve says how many are needed at 13:00; this says
    # how many bodies the day takes altogether, which is the number a manager
    # recognises and the one that shows a thin Sunday at a glance.
    staff_per_day: Dict[str, int] = field(default_factory=dict)
    # The shape of a day, as the shop actually runs it: which shifts start,
    # and how many of each. {"mon": [("06:00","16:00"), ("06:00","16:00"),
    # ("23:30","07:00")]} means two people open and one covers the night.
    #
    # This is the thing a manager writes. Learning it directly reproduces
    # the rota rather than inferring it from an hourly headcount and hoping
    # the shapes come back out — which is how a night shift still on the
    # floor at 06:00 ended up being counted twice, once in the curve and
    # again as a body added on top.
    day_slots: Dict[str, List[List[str]]] = field(default_factory=dict)
    # How many weeks from about a year ago fed into this. Zero until a shop
    # has a year of history — and while it is zero, nothing here knows
    # anything about Christmas. Reported so the UI can say that rather than
    # implying a yearly pattern that has never been observed.
    seasonal_weeks: int = 0
    # The granularity this shop writes its shift FINISHES on, in minutes.
    #
    # Top Oil ends a shift on a half hour once in 555 shifts, so rounding a
    # contract trim down to a whole hour matches what its manager writes. A
    # shop that genuinely finishes at 10:30 and 12:30 would be badly served by
    # the same rule — every trim would drift its rota toward a convention it
    # does not use, which is precisely the §10b trap of taking one shop's
    # numbers for everyone's.
    #
    # So it is learned rather than assumed. See `finish_granularity`.
    edge_minutes: int = 60

    @property
    def is_usable(self) -> bool:
        return bool(self.headcount) and self.weeks_observed >= MIN_WEEKS_FOR_DEMAND

    def required(self, day: str, hour: int) -> int:
        return self.headcount.get(day, [0] * HOURS_PER_DAY)[hour]

    def staff_target(self, day: str) -> int:
        """People expected on the floor across the whole day."""
        return self.staff_per_day.get(day, 0)

    def slots_for(self, day: str) -> List[Tuple[str, str]]:
        """The shifts this day normally runs, earliest start first."""
        return [tuple(slot) for slot in self.day_slots.get(day, [])]

    def role_target(self, day: str, hour: int, role: str) -> float:
        return self.role_mix.get(day, {}).get(role, [0.0] * HOURS_PER_DAY)[hour]

    def total_required(self, day: str) -> int:
        return sum(self.headcount.get(day, []))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "headcount": self.headcount,
            "role_mix": {d: {r: [round(v, 2) for v in vals] for r, vals in roles.items()}
                         for d, roles in self.role_mix.items()},
            "patterns": [
                {"start": p.start, "end": p.end, "count": p.count, "hours": p.hours}
                for p in self.patterns
            ],
            "weeks_observed": self.weeks_observed,
            "staff_per_day": self.staff_per_day,
            "seasonal_weeks": self.seasonal_weeks,
            "edge_minutes": self.edge_minutes,
            "day_slots": self.day_slots,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DemandProfile":
        return cls(
            headcount={d: list(v) for d, v in (data.get("headcount") or {}).items()},
            role_mix={
                d: {r: list(vals) for r, vals in roles.items()}
                for d, roles in (data.get("role_mix") or {}).items()
            },
            patterns=[
                ShiftPattern(p["start"], p["end"], p.get("count", 1), p.get("hours", 0.0))
                for p in (data.get("patterns") or [])
            ],
            weeks_observed=data.get("weeks_observed", 0),
            staff_per_day=dict(data.get("staff_per_day") or {}),
            seasonal_weeks=int(data.get("seasonal_weeks") or 0),
            edge_minutes=int(data.get("edge_minutes") or 60),
            day_slots={
                d: [list(s) for s in slots]
                for d, slots in (data.get("day_slots") or {}).items()
            },
            source=data.get("source", "learned"),
        )


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------
# How quickly an old week stops mattering. At an 8-week half-life, last
# month counts about 4/5 of this week, three months ago about a third, six
# months ago about a fifth.
#
# WHY WEIGHTING AT ALL: every week used to count the same, so a deliberate
# change took the full lookback to be believed. Cut two people from the
# evening and three months later the profile still says five — it still
# BUILDS rosters with five, and the manager deletes two every week. That is
# the edit burden this product exists to reduce, caused by the product.
#
# Eight weeks is a judgement, not a measurement (see CLAUDE.md 10b). Long
# enough that one odd week does not move the shape, short enough that a real
# change is followed within about a month.
RECENCY_HALF_LIFE_WEEKS = 8.0

# Christmas is not drift. A shop that runs extra staff in December looks, to
# a recency-weighted average, exactly like a shop that has permanently grown
# — and then looks like one that has permanently shrunk in January.
#
# The defence is last year: a week roughly 52 weeks before the one being
# built is given a weight floor, so it still carries even though recency
# alone would have reduced it to nothing (0.5^(52/8) is about 0.01).
#
# This does NOTHING until a shop has a year of history. It cannot: you cannot
# know December is busy without having seen a December. `seasonal_weeks` on
# the profile reports whether it found any, so the UI can say so rather than
# implying a yearly pattern it has never seen.
SEASONAL_ECHO_WEEKS = 52
SEASONAL_ECHO_TOLERANCE = 2      # a fortnight either side of "same week"
SEASONAL_ECHO_WEIGHT = 0.6       # what last year's same week is worth


def _week_start_date(week_start: Any):
    try:
        return datetime.strptime(str(week_start), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _weighted_rosters(
    rosters: Sequence[Dict[str, Any]],
    lookback_weeks: int,
    for_week: Optional[str] = None,
) -> List[Tuple[Dict[str, Any], float]]:
    """Each week to learn from, paired with how much it counts.

    Deduplicating by week matters: a week regenerated several times before
    approval would otherwise be counted several times and skew the curve
    toward whatever that week happened to look like.

    Newer weeks count more (RECENCY_HALF_LIFE_WEEKS). A week about a year
    before the target keeps a floor (SEASONAL_ECHO_WEIGHT) so last December
    still describes this December.
    """
    weeks = latest_per_week(list(rosters))
    if not weeks:
        return []

    anchor = _week_start_date(for_week) if for_week else None
    if anchor is None:
        # No target week given — measure age from the newest week we have, so
        # the most recent roster is always full weight.
        anchor = max(
            (d for d in (_week_start_date(r.get("week_start")) for r in weeks) if d),
            default=None,
        )
    if anchor is None:
        # Unparseable dates everywhere: fall back to the old flat behaviour
        # rather than silently weighting everything to zero.
        return [(r, 1.0) for r in weeks[:lookback_weeks]]

    out: List[Tuple[Dict[str, Any], float]] = []
    for roster in weeks:
        started = _week_start_date(roster.get("week_start"))
        if started is None:
            continue
        age = (anchor - started).days / 7.0
        if age < 0:
            continue        # a future week is not evidence of anything yet

        seasonal = abs(age - SEASONAL_ECHO_WEEKS) <= SEASONAL_ECHO_TOLERANCE
        if age >= lookback_weeks and not seasonal:
            continue

        weight = 0.5 ** (age / RECENCY_HALF_LIFE_WEEKS)
        if seasonal:
            weight = max(weight, SEASONAL_ECHO_WEIGHT)
        out.append((roster, weight))
    return out


def _recent_rosters(
    rosters: Sequence[Dict[str, Any]], lookback_weeks: int
) -> List[Dict[str, Any]]:
    """Kept for callers that want the weeks without the weights."""
    return [r for r, _ in _weighted_rosters(rosters, lookback_weeks)]


# A shop has to write enough shifts before its habits mean anything. Below
# this, the default stands.
_MIN_SHIFTS_FOR_GRANULARITY = 50
# What fraction of finishes must land on a step before it counts as the shop's
# convention. High, because the cost of guessing too fine is only that trims
# stay where they are, while guessing too coarse rewrites the shop's rota.
_GRANULARITY_SHARE = 0.9


def finish_granularity(rosters: List[Dict[str, Any]]) -> int:
    """The step this shop writes its shift FINISHES on, in minutes.

    Returns the COARSEST of 60, 30, 15 that at least 90% of finishes are a
    multiple of, defaulting to 60 when there is not enough history to tell.

    Coarsest-that-fits, rather than the most common single value, because the
    question being asked is "what may a trim round to without inventing a shape
    this shop does not write". A shop whose finishes are 99.8% on the hour
    answers 60. A shop that mixes 12:00 and 12:30 answers 30 — half its
    finishes are not multiples of 60, so 60 would be wrong for it even though
    60 is its single most common step.

    Only finishes. Starts are not rounded by anything (familiarity is keyed on
    them, §2), so their granularity is not a question anybody asks.
    """
    minutes = [
        to_minutes(shift["end"]) % 60
        for roster in rosters or []
        for shift in roster.get("shifts", [])
        if shift.get("start") and shift.get("end")
        and not (shift.get("paid_holiday") or shift.get("unpaid_holiday")
                 or shift.get("sick"))
    ]
    if len(minutes) < _MIN_SHIFTS_FOR_GRANULARITY:
        return 60
    for step in (60, 30, 15):
        on_step = sum(1 for m in minutes if m % step == 0)
        if on_step >= _GRANULARITY_SHARE * len(minutes):
            return step
    return 15


def _hours_covered(start: str, end: str) -> List[int]:
    start_m, end_m = to_minutes(start), to_minutes(end)
    if end_m <= start_m:
        end_m += 24 * 60
    return [(m // 60) % 24 for m in range(start_m, end_m, 60)]


def _is_worked(shift: Dict[str, Any]) -> bool:
    """Leave and one-off overrides describe absence, not staffing need."""
    return not (
        shift.get("sick")
        or shift.get("paid_holiday")
        or shift.get("unpaid_holiday")
        or shift.get("temp_override")
    )


def _build_day_slots(
    slot_counts: Dict[str, Counter],
    weeks: int,
    staff_targets: Dict[str, int],
) -> Dict[str, List[List[str]]]:
    """The shifts each day normally runs, from how often each one appeared.

    Rounding each pattern on its own loses the total. A shop that runs ten
    people every Monday across a dozen varying shapes has most of those
    shapes appearing on well under half the weeks, so each rounds to zero and
    the day comes out with six slots instead of ten — leaving the roster
    permanently a body short at every hour, and blaming it on whoever had the
    day off.

    So the whole-number part is taken first, then the remaining places are
    handed to the shapes with the largest fractions until the day matches the
    headcount the shop actually runs. Same method as apportioning seats: the
    parts round, but the total is preserved.
    """
    day_slots: Dict[str, List[List[str]]] = {}

    for day, counts in slot_counts.items():
        target = staff_targets.get(day, 0)
        quotas = [
            (pattern, seen / weeks) for pattern, seen in counts.items() if seen
        ]
        if not quotas:
            day_slots[day] = []
            continue

        slots: List[List[str]] = []
        for (start, end), quota in quotas:
            for _ in range(int(quota)):
                slots.append([start, end])

        # Hand out what rounding dropped, biggest fraction first.
        remainders = sorted(
            ((quota - int(quota), pattern) for pattern, quota in quotas),
            key=lambda item: (-item[0], item[1]),
        )
        index = 0
        while len(slots) < target and index < len(remainders):
            fraction, (start, end) = remainders[index]
            if fraction <= 0:
                break
            slots.append([start, end])
            index += 1

        # Earliest start first, longest first on a tie: the opener is the
        # slot most likely to be hard to fill, so it is offered a candidate
        # while the most people are still available.
        slots.sort(key=lambda s: (to_minutes(s[0]), -_span_minutes(s[0], s[1])))
        day_slots[day] = slots

    return day_slots


def _span_minutes(start: str, end: str) -> int:
    start_m, end_m = to_minutes(start), to_minutes(end)
    return (end_m - start_m) % (24 * 60) or 24 * 60


def learn_demand(
    rosters: Sequence[Dict[str, Any]],
    employee_roles: Dict[str, str],
    *,
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
    for_week: Optional[str] = None,
) -> DemandProfile:
    """Measure staffing shape from approved rosters.

    `employee_roles` maps employee_id -> role, needed because rosters store
    only IDs but the role mix is what makes role-saturation possible.

    `for_week` is the week being built. It anchors both the recency weighting
    and the search for the same week last year; without it, ages are measured
    from the newest roster instead, which is right for a report and slightly
    wrong for a roster being built weeks ahead.
    """
    weighted = _weighted_rosters(rosters, lookback_weeks, for_week)
    if not weighted:
        return DemandProfile(source="none")

    recent = [r for r, _ in weighted]
    # The DIVISOR is the sum of the weights, not the number of weeks. Dividing
    # weighted counts by a plain count would report a shop as quieter than it
    # is, by exactly the amount the old weeks were discounted.
    weeks = sum(w for _, w in weighted) or 1.0
    # Reported separately: "learned from 24 weeks" is what a manager
    # understands, and it is a count of weeks, not a sum of weights.
    observed = len(weighted)
    seasonal_weeks = sum(
        1 for r, _ in weighted
        if _week_start_date(r.get("week_start")) is not None
        and abs(
            ((_week_start_date(for_week) or _week_start_date(recent[0].get("week_start")))
             - _week_start_date(r.get("week_start"))).days / 7.0
            - SEASONAL_ECHO_WEEKS
        ) <= SEASONAL_ECHO_TOLERANCE
    ) if recent else 0
    headcount_totals = {d: [0.0] * HOURS_PER_DAY for d in DAYS}
    role_totals: Dict[str, Dict[str, List[float]]] = {
        d: defaultdict(lambda: [0.0] * HOURS_PER_DAY) for d in DAYS
    }
    pattern_counts: Counter = Counter()
    # Hours we could not attribute to a role at all (staff who left before
    # their role was recorded on the shift). Used to scale the role mix so it
    # still adds up to the headcount.
    departed_hours = {d: [0.0] * HOURS_PER_DAY for d in DAYS}
    # Distinct people the shop put on each day. Counted per roster and then
    # averaged, so it is "how many bodies does a Sunday take", not a sum.
    staff_totals = {d: 0.0 for d in DAYS}
    # How often each exact shift ran on each day, so the day's shape can be
    # rebuilt rather than inferred.
    slot_counts: Dict[str, Counter] = {d: Counter() for d in DAYS}

    for roster, weight in weighted:
        on_day: Dict[str, set] = {d: set() for d in DAYS}
        for shift in roster.get("shifts", []):
            if not _is_worked(shift):
                continue
            day = shift.get("day")
            start, end = shift.get("start"), shift.get("end")
            if day not in headcount_totals or not (start and end):
                continue

            # AN EXTRA TEACHES THE SHAPE, NOT THE STAFFING LEVEL.
            #
            # `extra` means "this person AS WELL AS the usual cover" (§2d) —
            # a deliberate addition for one week, not a statement that the
            # shop needs another body on Fridays for ever. Counting it toward
            # the headcount made every extra permanently raise the level, so
            # a manager who added somebody once was asked for that person
            # again every week afterwards.
            #
            # The SHAPE is different. If the same 17:00-21:00 is added ten
            # weeks running, that is a shift this shop runs, and it belongs
            # in the vocabulary — where it competes with every other shape on
            # frequency and earns a slot or does not. So `slot_counts` still
            # sees it while `headcount_totals`, `role_totals` and
            # `staff_totals` do not.
            counts_toward_level = not shift.get("extra")
            if counts_toward_level:
                on_day[day].add(shift.get("employee_id", ""))

            # Shifts worked by people who have since left still tell us how
            # many bodies the shop needed, so they count toward headcount.
            # They have no current role though, so without the fallback below
            # they would be missing from the role mix — making role targets
            # sum to less than the headcount and weakening the saturation
            # rule. The role recorded on the shift itself covers that case.
            employee_id = shift.get("employee_id", "")
            role = employee_roles.get(employee_id) or shift.get("role") or ""

            if counts_toward_level:
                for hour in _hours_covered(start, end):
                    headcount_totals[day][hour] += weight
                    if role:
                        role_totals[day][role][hour] += weight
                    else:
                        departed_hours[day][hour] += weight

            pattern_counts[(start, end)] += 1
            slot_counts[day][(start, end)] += weight

        for day, people in on_day.items():
            staff_totals[day] += len(people) * weight

    # Round to nearest, not up. Rounding up looks safer but compounds across
    # 168 hours: measured against the reference shop it inflated the weekly
    # requirement by 21% (608h asked vs 556h actually worked). Nearest
    # reproduces the real total almost exactly (554h vs 556h).
    headcount = {
        day: [int(round(total / weeks)) if total else 0 for total in hours]
        for day, hours in headcount_totals.items()
    }

    # Scale the mix up to cover unattributed hours, so role targets still sum
    # to the headcount even when part of the history was worked by people who
    # have since left.
    role_mix = {}
    for day, roles in role_totals.items():
        attributed = [
            sum(hours[hour] for hours in roles.values()) for hour in range(HOURS_PER_DAY)
        ]
        scale = [
            ((attributed[h] + departed_hours[day][h]) / attributed[h]) if attributed[h] else 1.0
            for h in range(HOURS_PER_DAY)
        ]
        role_mix[day] = {
            role: [hours[h] * scale[h] / weeks for h in range(HOURS_PER_DAY)]
            for role, hours in roles.items()
        }

    patterns = [
        ShiftPattern(
            start=start,
            end=end,
            count=count,
            hours=len(_hours_covered(start, end)),
        )
        for (start, end), count in pattern_counts.most_common(MAX_PATTERNS)
        if count >= MIN_PATTERN_OCCURRENCES
    ]

    staff_per_day = {
        day: int(round(total / weeks)) if total else 0
        for day, total in staff_totals.items()
    }

    return DemandProfile(
        headcount=headcount,
        role_mix=role_mix,
        patterns=patterns,
        weeks_observed=observed,
        staff_per_day=staff_per_day,
        day_slots=_build_day_slots(slot_counts, weeks, staff_per_day),
        seasonal_weeks=seasonal_weeks,
        # From the SAME weeks the shapes came from, so the convention and the
        # shapes cannot disagree about the shop.
        edge_minutes=finish_granularity([r for r, _ in weighted]),
        source="learned",
    )


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------
def profile_from_shop_hours(shop: Dict[str, Any]) -> DemandProfile:
    """A minimal profile for shops with too little history to learn from.

    Requires one person whenever the shop is open, and offers shift patterns
    derived from opening hours. Equivalent to the old block behaviour, but
    expressed in the new model so the solver has only one code path.
    """
    from app.services.scheduler import build_segments

    hours_by_day = {h["day"]: h for h in shop.get("hours", [])}
    headcount: Dict[str, List[int]] = {}
    pattern_counts: Counter = Counter()

    for day in DAYS:
        row = [0] * HOURS_PER_DAY
        hours = hours_by_day.get(day)
        if hours and not hours.get("closed"):
            open_m, close_m = to_minutes(hours["open"]), to_minutes(hours["close"])
            if close_m > open_m:
                for hour in _hours_covered(hours["open"], hours["close"]):
                    row[hour] = 1
                for segment in build_segments(shop, open_m, close_m):
                    pattern_counts[(segment.start, segment.end)] += 1
        headcount[day] = row

    templates = shop.get("shift_templates") or []
    for template in templates:
        pattern_counts[(template["start"], template["end"])] += 1

    patterns = [
        ShiftPattern(start, end, count, len(_hours_covered(start, end)))
        for (start, end), count in pattern_counts.most_common(MAX_PATTERNS)
    ]

    return DemandProfile(
        headcount=headcount,
        role_mix={},
        patterns=patterns,
        weeks_observed=0,
        source="shop_hours",
    )


def build_profile(
    shop: Dict[str, Any],
    rosters: Sequence[Dict[str, Any]],
    employee_roles: Dict[str, str],
    *,
    lookback_weeks: int = DEFAULT_LOOKBACK_WEEKS,
    for_week: Optional[str] = None,
) -> DemandProfile:
    """Learned profile when there is enough history, otherwise the fallback.

    A manual override stored on the shop always wins — an owner who has edited
    their curve should not have it silently relearned out from under them.
    """
    override = shop.get("demand_profile")
    if override:
        profile = DemandProfile.from_dict(override)
        profile.source = "manual"
        if not profile.patterns:
            profile.patterns = profile_from_shop_hours(shop).patterns
        return profile

    learned = learn_demand(
        rosters, employee_roles,
        lookback_weeks=lookback_weeks, for_week=for_week,
    )
    if learned.is_usable and learned.patterns:
        return learned
    return profile_from_shop_hours(shop)


# ---------------------------------------------------------------------------
# Comparing a week against what the shop usually runs
# ---------------------------------------------------------------------------
# Below this, a difference is not worth a sentence. One body short for a
# single hour at a changeover is normal and already handled by stretching a
# neighbouring shift; saying so as well would bury the hour that matters
# under twenty that do not.
MIN_HOURS_WORTH_MENTIONING = 2


def compare_to_usual(
    shifts: Sequence[Dict[str, Any]],
    profile: "DemandProfile",
    *,
    open_hours: Optional[Dict[str, List[int]]] = None,
) -> List[Dict[str, Any]]:
    """Where this week departs from the shape the shop normally runs.

    Information, never a refusal. Running leaner is a business decision and
    the manager is allowed to make it — what they are not allowed to do is
    make it by accident, which is what happens when nothing says the evening
    normally has three people in it.

    Consecutive hours with the same shortfall are reported as one span. Hour
    by hour it would be twenty lines a day and nobody would read the one that
    mattered.
    """
    if not profile or profile.source == "none":
        return []

    on_duty = {day: [0] * HOURS_PER_DAY for day in DAYS}
    for shift in shifts:
        day, start, end = shift.get("day"), shift.get("start"), shift.get("end")
        if day not in on_duty or not (start and end):
            continue
        if shift.get("paid_holiday") or shift.get("unpaid_holiday") or shift.get("sick"):
            continue
        # An overnight shift covers hours on the following day too, and those
        # hours are exactly the ones nobody thinks to check.
        cursor = DAYS.index(day)
        for offset, hour in enumerate(_hours_covered(start, end)):
            index = cursor + (1 if offset and hour < _hours_covered(start, end)[0] else 0)
            on_duty[DAYS[index % 7]][hour] += 1

    notes: List[Dict[str, Any]] = []
    for day in DAYS:
        hours = (open_hours or {}).get(day)
        run: Optional[Dict[str, Any]] = None

        for hour in range(HOURS_PER_DAY):
            if hours is not None and hour not in hours:
                usual = 0
            else:
                usual = profile.required(day, hour)
            have = on_duty[day][hour]
            gap = usual - have

            if usual <= 0 or gap <= 0:
                if run and run["hours"] >= MIN_HOURS_WORTH_MENTIONING:
                    notes.append(run)
                run = None
                continue

            if run and run["short_by"] == gap and run["to_hour"] == hour:
                run["to_hour"] = hour + 1
                run["hours"] += 1
            else:
                if run and run["hours"] >= MIN_HOURS_WORTH_MENTIONING:
                    notes.append(run)
                run = {
                    "day": day, "from_hour": hour, "to_hour": hour + 1,
                    "hours": 1, "have": have, "usual": usual, "short_by": gap,
                }

        if run and run["hours"] >= MIN_HOURS_WORTH_MENTIONING:
            notes.append(run)

    for note in notes:
        note["message"] = (
            f"{note['day']} {note['from_hour']:02d}:00–{note['to_hour']:02d}:00 — "
            f"{note['have']} on, this shop usually runs {note['usual']}."
        )
    return notes
