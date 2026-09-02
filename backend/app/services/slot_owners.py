"""Who normally works a given shift.

WHY
---
The solver filled slots by role priority: most senior role first, with learned
affinity only as a late tie-breaker. So an Ambient Manager could be handed the
Monday 06:00 opening ahead of the floor assistant who has opened it every week
for months.

Familiarity does not prevent that. It only asks "has this person ever worked a
shift starting near this time" — and a manager who covered a few early starts
passes, then wins on seniority. The question that matters is not who *can*
work the shift but who *normally does*.

THE RULE
--------
A slot has an OWNER when one person worked it in at least `OWNERSHIP_SHARE`
of the WEEKS it ran, across at least `MIN_OCCURRENCES` such weeks. Both
thresholds earn their place:

    share alone      1 of 1 is 100% and means nothing
    count alone      4 of 20 is frequent and still not ownership

The denominator is weeks, not shifts. Measured against shifts, Megan opening
Monday in 81% of weeks came out at 53% — because a colleague sometimes worked
the same shape and their shifts inflated the total.

Ownership is per (day, slot). Emma may own Monday 06:00-16:00 without owning
Saturday 06:00-16:00 — in the manager's head those are different shifts, and
they are different here too.

HOW IT IS USED
--------------
When the solver fills a slot it asks for the owner first. If they are
available, the slot is theirs and normal ranking is skipped. If not, it falls
back to the next most frequent person for that same slot, and only then to
role priority.

WHAT IT NEVER DOES
------------------
Ownership is a preference between people who are all allowed to work the
shift. It never beats a hard constraint: an owner on leave, curfewed, at their
hour cap, inside the 11-hour rest window or already on five days does not get
the slot. The fallback applies, exactly as if they had no claim.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Set, Tuple

from app.services.learning import latest_per_week

# Share of a slot's occurrences one person must hold to own it.
OWNERSHIP_SHARE = 0.6

# How many times the slot must have run before ownership means anything.
# Three of four is a habit; one of one is an accident.
MIN_OCCURRENCES = 4

Slot = Tuple[str, str]        # (start, end)
DaySlot = Tuple[str, str, str]  # (day, start, end)


class SlotHistory(NamedTuple):
    """Who has worked a slot, and how many weeks it ran at all.

    `weeks` is the denominator, and getting it wrong was the original bug.
    Dividing by total SHIFTS punishes somebody whenever a colleague also
    worked their shape: Megan opens Monday in 81% of the weeks it runs, but
    counted against every shift of that shape she came out at 53% — under the
    bar — purely because a second person sometimes worked it too.

    Weeks is also what makes a doubled slot work. Tuesday runs 06:00-16:00
    twice; over 23 weeks Megan has 21 and John 17, so both clear the bar and
    own one instance each.
    """
    people: List[Tuple[str, int]]   # (employee_id, times worked), most first
    weeks: int                      # weeks in which the slot ran at all


def _is_signal(
    shift: Dict[str, Any], known_shapes: Optional[Set[DaySlot]] = None
) -> bool:
    """Leave and one-off overrides say nothing about who owns a shift.

    EXTRAS ARE A SPECIAL CASE, and the rule is "once the shape is real".

    An `extra` is "this person AS WELL AS the usual cover" (§2d), so counting
    every one of them would let somebody added four times become the OWNER of
    a slot the shop does not run — and the solver would then place them there
    as ordinary cover, turning "as well as" into "instead of". That is the
    precise thing §2d exists to prevent.

    But a shift added ten weeks running IS a shift this shop runs, and the
    manager should not have to keep re-adding it while the app refuses to
    notice whose it is. `demand.py` already settles that question: a shape
    that recurs often enough earns a place in `day_slots` on its own
    frequency, and extras no longer inflate the staffing level, so it has to
    earn it honestly.

    So an extra counts toward ownership only for a shape that is ALREADY a
    real slot. `known_shapes` is that set. Passed None — as the diagnostics
    do — extras are ignored entirely, which is the old, safe behaviour.
    """
    if (shift.get("sick") or shift.get("temp_override")
            or shift.get("unpaid_holiday") or shift.get("paid_holiday")):
        return False
    if shift.get("extra"):
        if known_shapes is None:
            return False
        return (shift.get("day"), shift.get("start"),
                shift.get("end")) in known_shapes
    return True


def build_owners(
    approved_rosters: Sequence[Dict[str, Any]],
    active_ids: Optional[Set[str]] = None,
    known_shapes: Optional[Set[DaySlot]] = None,
) -> Dict[DaySlot, SlotHistory]:
    """(day, start, end) -> who has worked it, and how many weeks it ran.

    `known_shapes` is the set of (day, start, end) the demand profile has
    settled on as real slots for this shop. Extras count toward ownership
    only on those — see `_is_signal`. Omit it and extras are ignored, which
    is the old behaviour and what the diagnostics want.

    One roster per week, newest wins — a duplicated week would let one week's
    staffing look like a settled habit.

    `active_ids` drops people who have left. Their history is real and stays
    in the demand profile — the shop did run those shifts — but a leaver
    cannot own a shift. Left in, they win the slot on every generation, are
    found ineligible, and it falls through to whoever is second, so the person
    who now actually works it never becomes its owner and the diagnostics name
    somebody who resigned.

    The WEEKS denominator deliberately still counts weeks the leaver worked,
    because the slot did run in those weeks. Recomputing it over only the
    remaining weeks would turn four occasional covers into a 100% owner, and
    four covers is not a habit.
    """
    counts: Dict[DaySlot, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    weeks: Dict[DaySlot, set] = defaultdict(set)

    for roster in latest_per_week(list(approved_rosters)):
        if roster.get("exclude_from_ai"):
            continue
        week_start = roster.get("week_start")
        for shift in roster.get("shifts", []):
            if not _is_signal(shift, known_shapes):
                continue
            employee_id = shift.get("employee_id")
            day, start, end = shift.get("day"), shift.get("start"), shift.get("end")
            if not (employee_id and day and start and end):
                continue
            key = (day, start, end)
            # The week counts either way: the slot ran, whoever worked it.
            weeks[key].add(week_start)
            if active_ids is not None and employee_id not in active_ids:
                continue
            counts[key][employee_id] += 1

    return {
        key: SlotHistory(
            people=sorted(people.items(), key=lambda kv: (-kv[1], kv[0])),
            weeks=len(weeks[key]),
        )
        for key, people in counts.items()
    }


def owner_of(
    owners: Dict[DaySlot, SlotHistory],
    day: str,
    start: str,
    end: str,
) -> Optional[str]:
    """Who owns this slot, or None if nobody has a settled claim.

    Share is measured against the WEEKS the slot ran, not the shifts worked.
    See SlotHistory for why: a colleague occasionally working the same shape
    otherwise drags the regular below the bar.
    """
    history = owners.get((day, start, end))
    if not history or history.weeks < MIN_OCCURRENCES:
        return None

    employee_id, count = history.people[0]
    return employee_id if count / history.weeks >= OWNERSHIP_SHARE else None


def regulars_of(
    owners: Dict[DaySlot, SlotHistory],
    day: str,
    start: str,
    end: str,
) -> Set[str]:
    """EVERYBODY with a settled claim on this shape, not just the top one.

    `owner_of` answers "who takes this instance", which is right when filling
    one slot and wrong when asking "whose shift is this". A shape that runs
    TWICE has two regulars — see SlotHistory: "Tuesday runs 06:00-16:00
    twice; over 23 weeks Megan has 21 and John 17, so both clear the bar and
    own one instance each."

    Anything that asks "may I move this shift" must use this rather than
    `owner_of`, or the SECOND regular's shift reads as unowned and can be
    given away. That happened: the rebalance pass used `owner_of` and took a
    Monday 06:00 off somebody who had worked it every week, because a
    colleague on the other instance of the same shape ranked first.

    The same mistake was made in a diagnostic first, found, and then repeated
    in the solver an hour later — which is why the check lives here now
    instead of being written out at each call site.
    """
    history = owners.get((day, start, end))
    if not history or history.weeks < MIN_OCCURRENCES:
        return set()
    return {
        employee_id for employee_id, count in history.people
        if count / history.weeks >= OWNERSHIP_SHARE
    }


def ownership_strength(
    owners: Dict[DaySlot, SlotHistory],
    day: str,
    start: str,
    end: str,
) -> float:
    """How settled this slot's ownership is, 0.0 when nobody owns it.

    Used when something with a harder claim — senior cover, which a shop
    cannot open without — has to displace somebody. Taking the shift with the
    weakest claim means the person who has opened every week for months is
    the last to lose theirs.
    """
    history = owners.get((day, start, end))
    if not history or history.weeks < MIN_OCCURRENCES:
        return 0.0
    share = min(1.0, history.people[0][1] / history.weeks)
    return share if share >= OWNERSHIP_SHARE else 0.0


def preference_order(
    owners: Dict[DaySlot, SlotHistory],
    day: str,
    start: str,
    end: str,
) -> List[str]:
    """Everybody who has worked this slot, most frequent first.

    Used when the owner cannot take it. Falling back to role seniority would
    hand a 06:00 opening to whoever ranks highest rather than to the person
    who actually covers it when the usual opener is off — which is what the
    manager does.
    """
    history = owners.get((day, start, end))
    return [employee_id for employee_id, _ in history.people] if history else []
