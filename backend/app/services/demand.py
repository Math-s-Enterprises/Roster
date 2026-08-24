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
            day_slots={
                d: [list(s) for s in slots]
                for d, slots in (data.get("day_slots") or {}).items()
            },
            source=data.get("source", "learned"),
        )


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------
def _recent_rosters(
    rosters: Sequence[Dict[str, Any]], lookback_weeks: int
) -> List[Dict[str, Any]]:
    """The most recent N weeks, newest first, one roster per week.

    Deduplicating by week matters: a week that was regenerated several times
    before approval would otherwise be counted several times and skew the
    curve toward whatever that week happened to look like.
    """
    return latest_per_week(list(rosters))[:lookback_weeks]


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
) -> DemandProfile:
    """Measure staffing shape from approved rosters.

    `employee_roles` maps employee_id -> role, needed because rosters store
    only IDs but the role mix is what makes role-saturation possible.
    """
    recent = _recent_rosters(rosters, lookback_weeks)
    if not recent:
        return DemandProfile(source="none")

    weeks = len(recent)
    headcount_totals = {d: [0] * HOURS_PER_DAY for d in DAYS}
    role_totals: Dict[str, Dict[str, List[int]]] = {
        d: defaultdict(lambda: [0] * HOURS_PER_DAY) for d in DAYS
    }
    pattern_counts: Counter = Counter()
    # Hours we could not attribute to a role at all (staff who left before
    # their role was recorded on the shift). Used to scale the role mix so it
    # still adds up to the headcount.
    departed_hours = {d: [0] * HOURS_PER_DAY for d in DAYS}
    # Distinct people the shop put on each day. Counted per roster and then
    # averaged, so it is "how many bodies does a Sunday take", not a sum.
    staff_totals = {d: 0 for d in DAYS}
    # How often each exact shift ran on each day, so the day's shape can be
    # rebuilt rather than inferred.
    slot_counts: Dict[str, Counter] = {d: Counter() for d in DAYS}

    for roster in recent:
        on_day: Dict[str, set] = {d: set() for d in DAYS}
        for shift in roster.get("shifts", []):
            if not _is_worked(shift):
                continue
            day = shift.get("day")
            start, end = shift.get("start"), shift.get("end")
            if day not in headcount_totals or not (start and end):
                continue
            on_day[day].add(shift.get("employee_id", ""))

            # Shifts worked by people who have since left still tell us how
            # many bodies the shop needed, so they count toward headcount.
            # They have no current role though, so without the fallback below
            # they would be missing from the role mix — making role targets
            # sum to less than the headcount and weakening the saturation
            # rule. The role recorded on the shift itself covers that case.
            employee_id = shift.get("employee_id", "")
            role = employee_roles.get(employee_id) or shift.get("role") or ""

            for hour in _hours_covered(start, end):
                headcount_totals[day][hour] += 1
                if role:
                    role_totals[day][role][hour] += 1
                else:
                    departed_hours[day][hour] += 1

            pattern_counts[(start, end)] += 1
            slot_counts[day][(start, end)] += 1

        for day, people in on_day.items():
            staff_totals[day] += len(people)

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
        weeks_observed=weeks,
        staff_per_day=staff_per_day,
        day_slots=_build_day_slots(slot_counts, weeks, staff_per_day),
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

    learned = learn_demand(rosters, employee_roles, lookback_weeks=lookback_weeks)
    if learned.is_usable and learned.patterns:
        return learned
    return profile_from_shop_hours(shop)
