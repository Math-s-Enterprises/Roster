"""What the manager changed about a generated roster.

WHY THIS EXISTS
---------------
The scheduler learns from approved rosters — weeks that worked. But the
highest-signal data is the CORRECTION: the manager looked at what the solver
proposed and changed it. That is them saying "you got this wrong, here is
right", and it is worth more than another example of a week that was fine.

Until now that signal was destroyed. Editing overwrites `shifts` in place, so
the moment a manager touched a roster, what the solver had proposed was gone.

WHAT IS COMPARED
----------------
`generated_shifts` — a frozen copy of the solver's output, written once at
generation and never touched by edits — against the final `shifts` at the
moment of approval. The difference is exactly what the manager decided to
change, and nothing else.

FOUR KINDS
----------
    swap     solver put Kelvin on Wed 06:00-14:00; the manager used Jane
    moved    the manager changed Megan's Tuesday from 09:00 to 10:00
    removed  the manager took Andi off Thursday entirely
    added    the manager put Kyle on Saturday

The distinction between `swap` and a separate remove-plus-add matters: a swap
says something about BOTH people for that slot, which a pair of unrelated
events does not.

WHAT THIS DOES NOT DO
---------------------
It does not judge. Whether a correction means anything is decided later, and
only after the same one has appeared several times — see
`docs/CORRECTIONS_LEARNING.md`. A single edit is an event, not a preference.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# A shift is identified by who works it and on what day. That pairing is
# unique within a roster — the validator refuses to roster anybody twice on
# one day — which is what makes a diff possible at all.
Key = Tuple[str, str]


def _is_leave(shift: Dict[str, Any]) -> bool:
    return bool(
        shift.get("paid_holiday") or shift.get("unpaid_holiday") or shift.get("sick")
    )


def _worked(shifts: List[Dict[str, Any]]) -> Dict[Key, Dict[str, Any]]:
    """Working shifts only, keyed by (employee, day).

    Leave is excluded throughout. Somebody being off sick is not the manager
    correcting the scheduler — it is the world happening — and counting it
    would teach the roster to avoid people who had been ill.
    """
    out: Dict[Key, Dict[str, Any]] = {}
    for shift in shifts or []:
        employee_id, day = shift.get("employee_id"), shift.get("day")
        if not employee_id or not day or _is_leave(shift):
            continue
        if not (shift.get("start") and shift.get("end")):
            continue
        out[(employee_id, day)] = shift
    return out


def _slot(shift: Dict[str, Any]) -> str:
    return f"{shift.get('start')}-{shift.get('end')}"


def diff_roster(
    generated: List[Dict[str, Any]],
    final: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """What the manager changed, as a list of corrections.

    Empty means they approved the roster exactly as proposed — which is the
    outcome the whole product is aiming at, and worth recording as such.
    """
    before, after = _worked(generated), _worked(final)
    corrections: List[Dict[str, Any]] = []

    # Same person, same day, different hours.
    for key in before.keys() & after.keys():
        was, now = before[key], after[key]
        if _slot(was) == _slot(now):
            continue
        employee_id, day = key
        corrections.append({
            "kind": "moved",
            "day": day,
            "employee_id": employee_id,
            "from_slot": _slot(was),
            "to_slot": _slot(now),
        })

    dropped = {k: before[k] for k in before.keys() - after.keys()}
    gained = {k: after[k] for k in after.keys() - before.keys()}

    # A swap is one decision about a slot, not two unrelated ones: somebody
    # taken off a day and somebody else put on the SAME hours that day. It
    # says something about both people, which remove+add would lose.
    for (out_id, day), was in list(dropped.items()):
        match = next(
            (
                (in_id, d) for (in_id, d), now in gained.items()
                if d == day and _slot(now) == _slot(was)
            ),
            None,
        )
        if not match:
            continue
        in_id, _ = match
        corrections.append({
            "kind": "swap",
            "day": day,
            "slot": _slot(was),
            "employee_id": in_id,          # who the manager chose
            "replaced_employee_id": out_id,  # who the solver had chosen
        })
        dropped.pop((out_id, day), None)
        gained.pop(match, None)

    for (employee_id, day), was in dropped.items():
        corrections.append({
            "kind": "removed",
            "day": day,
            "employee_id": employee_id,
            "slot": _slot(was),
        })

    for (employee_id, day), now in gained.items():
        corrections.append({
            "kind": "added",
            "day": day,
            "employee_id": employee_id,
            "slot": _slot(now),
        })

    # Stable order so two runs over the same roster agree, and so a stored
    # list can be compared in a test without sorting at every call site.
    corrections.sort(key=lambda c: (c["kind"], c["day"], c["employee_id"]))
    return corrections


def edit_count(corrections: Optional[List[Dict[str, Any]]]) -> int:
    """How many changes the manager made. The number the product must reduce."""
    return len(corrections or [])


# ---------------------------------------------------------------------------
# Reading the signal back
# ---------------------------------------------------------------------------
# How many approved weeks are looked at. Long enough for a habit to show,
# short enough that a rota which changed two months ago is not still being
# quoted back at the manager.
CORRECTION_WINDOW = 12

# How many times the SAME correction must appear before it is called a
# pattern. Two is a coincidence; the third time is the manager telling you
# something. Deliberately low, because every repeat is an edit they had to
# make by hand and the whole point is to stop asking.
MIN_REPEATS = 3


def signature(correction: Dict[str, Any]) -> str:
    """A stable id for "the same correction happening again".

    Deliberately includes the day and the slot. Moving Megan off Tuesday
    06:00 is a different decision from moving her off Saturday 06:00 — in the
    manager's head those are different shifts, and collapsing them would
    invent a preference neither of them holds.
    """
    kind = correction.get("kind")
    day = correction.get("day", "")
    who = correction.get("employee_id", "")
    if kind == "swap":
        return f"swap:{day}:{correction.get('slot', '')}:{who}:" \
               f"{correction.get('replaced_employee_id', '')}"
    if kind == "moved":
        return f"moved:{day}:{who}:{correction.get('from_slot', '')}:" \
               f"{correction.get('to_slot', '')}"
    return f"{kind}:{day}:{who}:{correction.get('slot', '')}"


def _approved_first(rosters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Approved weeks, newest first, one per week.

    Only approved rosters count. A draft the manager is still working on is
    not them telling you anything yet — they may be halfway through an edit.
    """
    from app.services.learning import latest_per_week

    weeks = [r for r in latest_per_week(list(rosters)) if r.get("approved")]
    return sorted(weeks, key=lambda r: r.get("week_start", ""), reverse=True)


def edit_trend(rosters: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """The last few weeks and how many edits each needed, oldest first.

    This is the product proving its worth, or failing to. A falling number
    means the scheduler is learning this shop; a flat one means it is not, and
    that is worth knowing early rather than after a year of manual fixing.

    Weeks approved before corrections were captured are marked unmeasurable
    rather than reported as zero edits, which would be a flattering lie.
    """
    recent = _approved_first(rosters)[:limit]
    out = []
    for roster in reversed(recent):
        # An empty proposal is still a measured proposal.  Presence of the
        # snapshot distinguishes it from a roster created before capture.
        measurable = "generated_shifts" in roster
        out.append({
            "week_start": roster.get("week_start"),
            "version": roster.get("version"),
            "edit_count": edit_count(roster.get("corrections")) if measurable else None,
            "measurable": measurable,
        })
    return out


def summarise(rosters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every correction in the window, tallied by what it actually was.

    Returns raw counts with no judgement attached. Deciding which of these
    deserves to become a setting is `suggestions()`, and it is kept separate
    so the manager can look at the evidence without being sold a conclusion.
    """
    window = _approved_first(rosters)[:CORRECTION_WINDOW]
    measurable = [r for r in window if "generated_shifts" in r]

    by_kind: Dict[str, int] = {}
    grouped: Dict[str, Dict[str, Any]] = {}

    for roster in measurable:
        for correction in roster.get("corrections") or []:
            kind = correction.get("kind", "?")
            by_kind[kind] = by_kind.get(kind, 0) + 1

            key = signature(correction)
            entry = grouped.setdefault(key, {
                "signature": key, "count": 0, "weeks": [], **correction,
            })
            entry["count"] += 1
            entry["weeks"].append(roster.get("week_start"))

    total = sum(by_kind.values())
    return {
        "weeks_measured": len(measurable),
        "weeks_in_window": len(window),
        "total_corrections": total,
        "average_per_week": round(total / len(measurable), 1) if measurable else None,
        "by_kind": by_kind,
        # Most repeated first: that ordering is the whole point of the screen.
        "patterns": sorted(
            grouped.values(), key=lambda p: (-p["count"], p["signature"]),
        ),
        "clean_weeks": sum(
            1 for r in measurable if not (r.get("corrections") or [])
        ),
    }


# ---------------------------------------------------------------------------
# Turning a repeated correction into a setting you can see
# ---------------------------------------------------------------------------
# THE DESIGN DECISION THAT MATTERS
#
# The obvious implementation is a hidden weight: notice the manager keeps
# putting Jane on Monday, quietly bias towards Jane, done. It is less code and
# it is wrong. A hidden weight cannot be inspected, cannot be argued with, and
# when it concludes something false the manager finds out from a bad roster
# rather than from a screen.
#
# So a repeated correction becomes a SUGGESTION to change a setting that
# already exists and is already editable — a fixed shift, a preferred day off,
# an availability window. Nothing is applied without being accepted. After
# that it lives in the ordinary UI, where it can be seen and undone by
# somebody who has never read this file.
#
# The suggestion is a sentence about the shop, not a number about a model.

def _suggest_from(pattern: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One suggestion for one repeated correction, or None if it says nothing.

    Only corrections with an obvious, reversible setting behind them are
    turned into anything. A repeated `swap` is deliberately NOT one of them:
    the shop's own approved rosters already teach that through slot ownership
    (see slot_owners.py), so suggesting a fixed shift on top would be a second
    switch for the same fact — and two switches that can disagree is one too
    many.
    """
    kind = pattern.get("kind")
    day, who = pattern.get("day"), pattern.get("employee_id")

    if kind == "added":
        # The manager keeps adding somebody the solver did not roster. That is
        # a shift the shop runs and the history has not learned.
        start, _, end = (pattern.get("slot") or "").partition("-")
        if not (start and end):
            return None
        return {
            "signature": pattern["signature"],
            "count": pattern["count"],
            "action": "fixed_shift",
            "employee_id": who,
            "day": day,
            "start": start,
            "end": end,
            "headline": "Make this a fixed shift",
            "because": (
                f"You have added this shift by hand {pattern['count']} times."
            ),
            "effect": (
                "It will be placed automatically every week, before anything "
                "else is decided."
            ),
        }

    if kind == "removed":
        # Repeatedly taking somebody OFF a day is the clearest statement of a
        # day they do not work.
        return {
            "signature": pattern["signature"],
            "count": pattern["count"],
            "action": "day_off",
            "employee_id": who,
            "day": day,
            "headline": f"Stop rostering them on {day}",
            "because": (
                f"You have taken them off {day} {pattern['count']} times."
            ),
            "effect": (
                f"{day} is added to their preferred days off. Nothing else "
                f"for you to do — it appears on their employee record, where "
                f"you can undo it."
            ),
        }

    if kind == "moved":
        # A start time that keeps being pushed later is an availability
        # window. Only the START is read for THIS one: a finish time is just
        # when somebody goes home, but a start is what the shift IS to them.
        #
        # Anything else the manager reshapes the same way three weeks running
        # falls through to the fixed shift below. That used to return None,
        # which threw away the commonest edit of all — lengthening a shift,
        # 06:00-10:00 becoming 06:00-12:00 — because the start had not
        # changed. A finish time says little about the PERSON but a great
        # deal about the shift, and the manager redrawing the same one every
        # week is the clearest statement there is that it has the wrong shape.
        was_start, _, was_end = (pattern.get("from_slot") or "").partition("-")
        now_start, _, now_end = (pattern.get("to_slot") or "").partition("-")
        if not (was_start and now_start and was_end and now_end):
            return None

        if now_start == was_start and now_end != was_end:
            # SAME start, different finish — the shift is the wrong length.
            #
            # Deliberately not widened to "any reshape". An EARLIER start is
            # already decided the other way (see the test named for it): being
            # pulled in early says the person was free all along, which is not
            # a setting. Answering it with a fixed shift instead would
            # overturn that decision as a side effect of adding this one.
            return {
                "signature": pattern["signature"],
                "count": pattern["count"],
                "action": "fixed_shift",
                "employee_id": who,
                "day": day,
                "start": now_start,
                "end": now_end,
                "headline": "Make this a fixed shift",
                "because": (
                    f"You have changed this from {pattern['from_slot']} to "
                    f"{pattern['to_slot']} {pattern['count']} times."
                ),
                "effect": (
                    f"{day} {now_start}-{now_end} is placed automatically "
                    f"every week. It becomes an ordinary fixed shift you can "
                    f"remove at any time."
                ),
            }

        if now_start <= was_start:
            # An EARLIER start, which is not a limit: being pulled in early
            # says the person was free all along. Kept as an explicit guard
            # rather than falling through, because without it this block
            # would happily set an availability floor EARLIER than the one
            # they already have.
            return None

        return {
            "signature": pattern["signature"],
            "count": pattern["count"],
            "action": "earliest_start",
            "employee_id": who,
            "day": day,
            "start": now_start,
            "headline": f"They cannot start before {now_start}",
            "because": (
                f"You have moved their start from {was_start} to {now_start} "
                f"{pattern['count']} times."
            ),
            "effect": (
                f"Their availability is set to start no earlier than "
                f"{now_start}. Nothing else for you to do — it appears on "
                f"their employee record, where you can undo it."
            ),
        }

    return None


def suggestions(
    rosters: List[Dict[str, Any]],
    dismissed: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Repeated corrections worth offering as a settings change.

    A single edit is an event, not a preference — MIN_REPEATS is what
    separates the two. Anything the manager has already said no to stays said
    no to, because asking again is how a helpful suggestion becomes nagging.
    """
    ignored = set(dismissed or [])
    out = []
    for pattern in summarise(rosters)["patterns"]:
        if pattern["count"] < MIN_REPEATS or pattern["signature"] in ignored:
            continue
        suggestion = _suggest_from(pattern)
        if suggestion:
            out.append(suggestion)
    return out
