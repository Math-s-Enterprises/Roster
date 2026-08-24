"""Historical preference weights.

WHAT THIS IS — AND IS NOT
-------------------------
This is not machine learning. No model is trained, nothing is fitted, and
there are no learned parameters in the statistical sense. It counts how
often things happened in previously-approved rosters and feeds those counts
to the solver as a tie-breaker between employees who are all equally
allowed to work a slot.

Called "learning" because that is the product language, but when you come
to improve it, know that you are tuning frequency heuristics.

WHAT IT COUNTS
--------------
    day[employee][weekday]        times this person worked that weekday
    tpl[employee][start-end]      times this person worked that time slot
    coworkers[employee][other]    times these two shared a day
    covers[absent][coverer]       times `coverer` worked a day `absent`
                                  usually works but was off

Only approved rosters count. Shifts marked sick, unpaid leave, or as a
temporary override are excluded — they represent exceptions, and treating
them as preference signal would teach the solver to repeat one-offs.
"""
import logging
from typing import Any, Dict, List

log = logging.getLogger("roster.learning")

EMPTY_WEIGHTS: Dict[str, Dict] = {"day": {}, "tpl": {}, "coworkers": {}, "covers": {}}


def latest_per_week(rosters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One roster per week, newest first, most-recently-created wins.

    A week can end up with two approved rosters — approve, regenerate,
    approve again, or import a historical week that was already generated
    and approved. Counting both teaches the solver that week twice, which
    quietly doubles one week's influence over every preference weight.

    Deduplicating here rather than at each call site means a duplicate is
    harmless to the *maths* even when one slips past the API guards. Those
    guards exist too, in `rosters.py` — this is the second line, not the
    first.
    """
    by_week: Dict[str, Dict[str, Any]] = {}
    for roster in rosters:
        week = roster.get("week_start")
        if not week:
            continue
        current = by_week.get(week)
        if not current or str(roster.get("created_at", "")) > str(current.get("created_at", "")):
            by_week[week] = roster
    return sorted(by_week.values(), key=lambda r: r["week_start"], reverse=True)


def _is_signal(shift: Dict[str, Any]) -> bool:
    """Exclude shifts that represent an exception rather than a preference."""
    return not (
        shift.get("sick")
        or shift.get("temp_override")
        or shift.get("unpaid_holiday")
        or shift.get("paid_holiday")
    )


def compute_weights(approved_rosters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate approved rosters into preference counts.

    Pure and synchronous: the caller fetches the rosters, this transforms
    them. That separation is what makes it unit-testable without a database
    and cacheable by the caller.

    Complexity is O(total shifts + sum of daily-cohort pairs). The prototype
    recomputed cover patterns against the whole accumulated weights table on
    every roster, making it superlinear; here cover detection happens once,
    after the counts are complete.
    """
    day_counts: Dict[str, Dict[str, int]] = {}
    template_counts: Dict[str, Dict[str, int]] = {}
    coworker_counts: Dict[str, Dict[str, int]] = {}
    cover_counts: Dict[str, Dict[str, int]] = {}

    # Retained per roster so cover detection can run after all counts exist.
    rosters_by_day: List[Dict[str, List[str]]] = []

    for roster in latest_per_week(approved_rosters):
        if roster.get("exclude_from_ai"):
            continue

        employees_by_day: Dict[str, List[str]] = {}
        for shift in roster.get("shifts", []):
            if not _is_signal(shift):
                continue
            employee_id = shift.get("employee_id")
            if not employee_id:
                continue

            day = shift.get("day")
            if day:
                day_counts.setdefault(employee_id, {}).setdefault(day, 0)
                day_counts[employee_id][day] += 1
                employees_by_day.setdefault(day, []).append(employee_id)

            slot = f"{shift.get('start', '')}-{shift.get('end', '')}"
            template_counts.setdefault(employee_id, {}).setdefault(slot, 0)
            template_counts[employee_id][slot] += 1

        for day, cohort in employees_by_day.items():
            for person in cohort:
                for other in cohort:
                    if person == other:
                        continue
                    coworker_counts.setdefault(person, {}).setdefault(other, 0)
                    coworker_counts[person][other] += 1

        rosters_by_day.append(employees_by_day)

    # Cover detection, once, against the finished day_counts table.
    for employees_by_day in rosters_by_day:
        worked_this_week = {e for cohort in employees_by_day.values() for e in cohort}
        for employee_id, usual_days in day_counts.items():
            if employee_id in worked_this_week:
                continue  # they worked; nobody covered for them
            for day in usual_days:
                for coverer in employees_by_day.get(day, []):
                    cover_counts.setdefault(employee_id, {}).setdefault(coverer, 0)
                    cover_counts[employee_id][coverer] += 1

    return {
        "day": day_counts,
        "tpl": template_counts,
        "coworkers": coworker_counts,
        "covers": cover_counts,
    }


def training_summary(approved_rosters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What the solver has to learn from, after an import.

    `weeks_in_window` is the number that actually decides roster quality: the
    demand profile learns from a trailing window and needs a minimum before
    it will use a learned shape at all. Counting rosters alone hid that — a
    shop could import fifty rosters spread over three years and still fall
    back to generic block coverage.
    """
    from app.services.demand import (  # imported here to avoid a cycle
        DEFAULT_LOOKBACK_WEEKS, MIN_WEEKS_FOR_DEMAND, _recent_rosters,
    )

    total_shifts = 0
    employees_seen = set()
    historical = 0
    weeks = set()

    # Counted over the deduplicated corpus, so the figures on screen match
    # what the solver actually reads. Showing a raw total that includes a
    # duplicated week would report more history than exists.
    corpus = latest_per_week(approved_rosters)

    for roster in corpus:
        if roster.get("historical"):
            historical += 1
        if roster.get("week_start"):
            weeks.add(roster["week_start"])
        for shift in roster.get("shifts", []):
            if not _is_signal(shift):
                continue
            total_shifts += 1
            if shift.get("employee_id"):
                employees_seen.add(shift["employee_id"])

    in_window = len(_recent_rosters(approved_rosters, DEFAULT_LOOKBACK_WEEKS))

    return {
        "approved_rosters": len(corpus),
        "historical_rosters": historical,
        "total_shifts_learned": total_shifts,
        "employees_learned": len(employees_seen),
        "weeks_of_history": len(weeks),
        "weeks_in_window": in_window,
        "weeks_needed": MIN_WEEKS_FOR_DEMAND,
        "lookback_weeks": DEFAULT_LOOKBACK_WEEKS,
        "learning_from_history": in_window >= MIN_WEEKS_FOR_DEMAND,
    }
