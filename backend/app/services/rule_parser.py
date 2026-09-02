"""Turn a written scheduling rule into a constraint, without an LLM.

A custom rule only reached the solver if it carried a `compiled` constraint,
and compiling went through the language model. With no ANTHROPIC_API_KEY the
compile step fails, so the rule saved, displayed as enabled, and did nothing
— silently. Writing a rule and having it quietly ignored is worse than not
offering the feature.

Most real rules are a handful of shapes:

    "Sarah never works Sundays"
    "Tom can't do closes"
    "Priya shouldn't open"
    "No more than 3 people on a Monday"
    "Ben and Alice must not work together"

Those are recognised here deterministically, which means they work offline,
give the same answer every time, and can be explained back to the manager.
Anything not recognised is reported as unparsed rather than dropped, so the
manager knows to reword it — and the LLM path still exists for shops that
have a key configured.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

DAY_WORDS = {
    "mon": "mon", "monday": "mon", "mondays": "mon",
    "tue": "tue", "tues": "tue", "tuesday": "tue", "tuesdays": "tue",
    "wed": "wed", "weds": "wed", "wednesday": "wed", "wednesdays": "wed",
    "thu": "thu", "thur": "thu", "thurs": "thu", "thursday": "thu", "thursdays": "thu",
    "fri": "fri", "friday": "fri", "fridays": "fri",
    "sat": "sat", "saturday": "sat", "saturdays": "sat",
    "sun": "sun", "sunday": "sun", "sundays": "sun",
}

# Phrases that mean "must not", so a rule reads as a prohibition rather than
# an instruction. Without this, "Sarah works Sundays" and "Sarah never works
# Sundays" would compile to the same thing.
NEGATIONS = (
    "never", "not", "n't", "cannot", "can not", "no ", "avoid", "exclude",
    "shouldn", "won", "unable", "off on", "doesn",
)

CLOSE_WORDS = ("close", "closing", "closes", "late shift", "lates", "night")
OPEN_WORDS = ("open", "opening", "opens", "early shift", "earlies", "morning")


def _find_days(text: str) -> List[str]:
    found = []
    for word in re.findall(r"[a-z]+", text):
        day = DAY_WORDS.get(word)
        if day and day not in found:
            found.append(day)
    return found


def _find_employees(text: str, employees: List[Dict[str, Any]]) -> List[str]:
    """Match names mentioned in the rule, longest first.

    Longest first so "Mark B" wins over "Mark" when both are on the team.
    """
    matched = []
    ordered = sorted(
        employees, key=lambda e: len(e.get("name") or ""), reverse=True
    )
    for employee in ordered:
        name = (employee.get("name") or "").strip().lower()
        if not name:
            continue
        first = name.split()[0]
        if re.search(rf"\b{re.escape(name)}\b", text) or re.search(rf"\b{re.escape(first)}\b", text):
            if employee["employee_id"] not in matched:
                matched.append(employee["employee_id"])
    return matched


def _is_negated(text: str) -> bool:
    return any(word in text for word in NEGATIONS)


def parse_rule(
    title: str,
    description: str,
    employees: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """A constraint the solver understands, or None if unrecognised.

    Returns the same shape the LLM path produces, so the solver does not
    care which route a rule arrived by.
    """
    text = f"{title} {description}".lower().strip()
    if not text:
        return None

    people = _find_employees(text, employees)
    days = _find_days(text)
    negated = _is_negated(text)

    # "There must always be a manager or supervisor on shift"
    #
    # Written as a requirement rather than a prohibition, so it is checked
    # before the negation test below — which would otherwise read "must not
    # be left without" as an ordinary ban and compile it wrongly.
    if re.search(r"\b(manager|supervisor|duty|senior|keyholder)\b", text):
        wants_cover = any(
            phrase in text for phrase in (
                "always", "at all times", "every shift", "on shift", "on duty",
                "must be", "should be", "at least one", "one of", "cover",
                "never without", "not be left",
            )
        )
        if wants_cover:
            return {
                "type": "supervisor_required",
                "days": days,
                "description": "A manager or supervisor on the floor at all times",
            }

    # "No more than 3 people on a Monday"
    cap = re.search(r"(?:no more than|maximum of|max|at most)\s+(\d+)", text)
    if cap:
        return {
            "type": "max_staff",
            "value": int(cap.group(1)),
            "days": days,
            "description": f"At most {cap.group(1)} staff" + (f" on {', '.join(days)}" if days else ""),
        }

    # "Martin, Corey and Jithin take turns having the weekend off"
    #
    # The first rule that depends on PREVIOUS weeks: whose turn it is comes
    # from history, not from the week being built. Everything else here is
    # answerable from the week alone.
    #
    # Checked before `not_together` because "take turns" and "rotate" name
    # several people and would otherwise be read as a co-working rule.
    #
    # No cycle length is stored. "Whoever has gone longest without a turn"
    # works for a group of two or seven, and for any set of days, so there is
    # no number here calibrated on one shop (§10b).
    if len(people) >= 2 and any(
        phrase in text for phrase in (
            "take turns", "takes turns", "taking turns", "in turn",
            "rotate", "rotates", "rotating", "rotation",
            "one at a time", "alternate", "alternates", "alternating",
        )
    ):
        # Which days the turn is FOR. "the weekend" is the common phrasing
        # and is not a day name, so it is expanded here rather than left to
        # `_find_days`, which looks for weekday words.
        turn_days = days
        if not turn_days and "weekend" in text:
            turn_days = ["sat", "sun"]
        if turn_days:
            return {
                "type": "rotating_day_off",
                "employee_ids": people,
                "days": turn_days,
                "description": (
                    f"{len(people)} people take turns having "
                    f"{', '.join(turn_days)} off"
                ),
            }

    # "Ben and Alice must not work together"
    if len(people) >= 2 and ("together" in text or "same shift" in text or "same time" in text):
        return {
            "type": "not_together" if negated else "required_together",
            "employee_ids": people,
            "days": days,
            "description": ("Must not" if negated else "Must") + " work at the same time",
        }

    if not negated:
        # Everything below is a prohibition. Without a negation there is
        # nothing to enforce, and guessing would be worse than saying so.
        return None

    if any(word in text for word in CLOSE_WORDS):
        return {
            "type": "no_close", "employee_ids": people, "days": days,
            "description": "Does not work closing shifts",
        }

    if any(word in text for word in OPEN_WORDS):
        return {
            "type": "no_open", "employee_ids": people, "days": days,
            "description": "Does not work opening shifts",
        }

    if days:
        return {
            "type": "no_day", "employee_ids": people, "days": days,
            "description": f"Does not work {', '.join(days)}",
        }

    return None


def describe(constraint: Dict[str, Any]) -> str:
    """Plain wording for a compiled constraint, for showing back."""
    return constraint.get("description") or constraint.get("type", "custom rule")
