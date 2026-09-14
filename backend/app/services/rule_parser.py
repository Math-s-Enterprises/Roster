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

SUPPORTED_TYPES = {
    "no_close", "no_open", "no_day", "max_staff", "not_together",
    "rotating_day_off", "supervisor_required",
}
VALID_DAYS = set(DAY_WORDS.values())


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


def validate_constraint(
    constraint: Dict[str, Any],
    employee_ids: Optional[set] = None,
) -> Dict[str, Any]:
    """Return the canonical constraint the scheduler supports.

    The model is a translator, not an extension mechanism: JSON naming a
    rule type the deterministic scheduler does not implement must never look
    approved or enforced.
    """
    if not isinstance(constraint, dict):
        raise ValueError("The compiled rule must be a JSON object.")

    if constraint.get("rule_type"):
        rule_type = str(constraint["rule_type"]).strip().upper()
        legacy_type = {
            "NO_CLOSE": "no_close",
            "NO_OPEN": "no_open",
            "NO_DAY": "no_day",
            "MAX_STAFF": "max_staff",
            "NOT_TOGETHER": "not_together",
            "ROTATING_DAY_OFF": "rotating_day_off",
        }.get(rule_type)
        if legacy_type:
            return validate_constraint({
                "type": legacy_type,
                "employee_ids": constraint.get("employee_ids"),
                "days": constraint.get("days"),
                "value": constraint.get("value"),
                "description": constraint.get("description"),
            }, employee_ids)
        if rule_type != "ROLE_REQUIREMENT":
            raise ValueError(f"Unsupported rule type: {rule_type}")
        roles = constraint.get("target_roles")
        if not isinstance(roles, list) or not roles:
            raise ValueError("ROLE_REQUIREMENT requires target_roles.")
        normalised_roles = [str(role).strip().title() for role in roles if str(role).strip()]
        if {role.lower() for role in normalised_roles} != {"manager", "supervisor"}:
            raise ValueError(
                "Closing role requirements currently support Manager or Supervisor."
            )
        time_slot = str(constraint.get("time_slot") or "").strip().upper()
        condition = str(constraint.get("condition") or "").strip().upper()
        min_count = constraint.get("min_count")
        if time_slot != "CLOSING":
            raise ValueError("ROLE_REQUIREMENT currently supports only CLOSING.")
        if condition != "AT_LEAST":
            raise ValueError("ROLE_REQUIREMENT currently supports only AT_LEAST.")
        if isinstance(min_count, bool) or min_count != 1:
            raise ValueError("Closing ROLE_REQUIREMENT currently supports min_count 1.")

        compiled = {
            "rule_type": "ROLE_REQUIREMENT",
            "target_roles": ["Manager", "Supervisor"],
            "time_slot": "CLOSING",
            "min_count": 1,
            "condition": "AT_LEAST",
        }
        raw_days = constraint.get("days") or []
        if not isinstance(raw_days, list):
            raise ValueError("days must be a JSON array.")
        days = []
        for value in raw_days:
            day = str(value).strip().lower()[:3]
            if day not in VALID_DAYS:
                raise ValueError(f"Unknown day: {value}")
            if day not in days:
                days.append(day)
        if days:
            compiled["days"] = days
        description = str(constraint.get("description") or "").strip()
        if description:
            compiled["description"] = description
        return compiled

    rule_type = str(constraint.get("type") or "").strip().lower()
    if rule_type not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported rule type: {rule_type or '(missing)' }")

    raw_days = constraint.get("days") or []
    if not isinstance(raw_days, list):
        raise ValueError("days must be a JSON array.")
    days = []
    for value in raw_days:
        day = str(value).strip().lower()[:3]
        if day not in VALID_DAYS:
            raise ValueError(f"Unknown day: {value}")
        if day not in days:
            days.append(day)

    raw_people = constraint.get("employee_ids") or []
    if not isinstance(raw_people, list):
        raise ValueError("employee_ids must be a JSON array.")
    people = []
    for value in raw_people:
        employee_id = str(value).strip()
        if not employee_id:
            continue
        if employee_ids is not None and employee_id not in employee_ids:
            raise ValueError(f"Unknown employee ID: {employee_id}")
        if employee_id not in people:
            people.append(employee_id)

    compiled: Dict[str, Any] = {"type": rule_type}
    if days:
        compiled["days"] = days
    description = str(constraint.get("description") or "").strip()
    if description:
        compiled["description"] = description

    if rule_type in {"no_close", "no_open", "no_day"}:
        if not people:
            raise ValueError(f"{rule_type} requires at least one employee.")
        compiled["employee_ids"] = people
    elif rule_type == "max_staff":
        value = constraint.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or value < 1:
            raise ValueError("max_staff requires a positive whole-number value.")
        compiled["value"] = int(value)
    elif rule_type in {"not_together", "rotating_day_off"}:
        if len(people) < 2:
            raise ValueError(f"{rule_type} requires at least two employees.")
        if rule_type == "rotating_day_off" and not days:
            raise ValueError("rotating_day_off requires at least one day.")
        compiled["employee_ids"] = people
    elif rule_type == "supervisor_required":
        scope = str(constraint.get("scope") or "").strip().lower()
        if scope in {"close", "closing"}:
            compiled["scope"] = "closing"
        else:
            raise ValueError(
                "supervisor_required currently supports only scope 'closing'."
            )

    return compiled


def is_supported_constraint(constraint: Any) -> bool:
    try:
        validate_constraint(constraint)
        return True
    except ValueError:
        return False


def compiled_constraints(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Approved, enabled constraints that the scheduler can really enforce."""
    compiled = []
    for rule in rules or []:
        if rule.get("enabled", True) is False or rule.get("approved", True) is False:
            continue
        try:
            compiled.append(validate_constraint(rule.get("compiled")))
        except ValueError:
            continue
    return compiled


def closing_supervisor_rules(
    constraints: List[Dict[str, Any]], day: str
) -> List[Dict[str, Any]]:
    return [
        rule for rule in constraints
        if (
            (rule.get("type") == "supervisor_required" and rule.get("scope") == "closing")
            or (
                rule.get("rule_type") == "ROLE_REQUIREMENT"
                and rule.get("time_slot") == "CLOSING"
                and rule.get("condition") == "AT_LEAST"
                and rule.get("min_count") == 1
            )
        )
        and (not rule.get("days") or day in rule["days"])
    ]


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

    # "Either a manager or supervisor must be rostered at closing."
    # Closing is a scope, not a guessed time: the scheduler reads each shop's
    # hours, including a close after midnight.
    if re.search(r"\b(manager|supervisor|duty|senior|keyholder)\b", text) \
            and any(word in text for word in CLOSE_WORDS):
        wants_cover = any(
            phrase in text for phrase in (
                "must", "should", "required", "need", "at least one",
                "one of", "either", "cover", "without",
            )
        )
        if wants_cover and (not negated or "without" in text):
            return {
                "rule_type": "ROLE_REQUIREMENT",
                "target_roles": ["Manager", "Supervisor"],
                "time_slot": "CLOSING",
                "min_count": 1,
                "condition": "AT_LEAST",
                "days": days,
                "description": "A manager or supervisor must cover closing",
            }

    # "No more than 3 people on a Monday"
    #
    # The number must be about PEOPLE. Without that check, "shop floor shifts
    # are a maximum of 8 hours" compiled to `max_staff: 8` — it showed as
    # Enforced and silently capped the shop at eight staff instead of
    # limiting shift length. A rule that quietly does the wrong thing is
    # worse than one that refuses, and §9 says an unparseable rule is
    # reported rather than guessed at.
    cap = re.search(
        r"(?:no more than|maximum of|max|at most)\s+(\d+)\s*"
        r"(?:people|staff|employees|workers|persons?|bodies|on)?",
        text,
    )
    if cap and not re.search(
        r"(?:no more than|maximum of|max|at most)\s+\d+\s*"
        r"(?:hours?|hrs?|h\b|shifts?|days?|minutes?|mins?)",
        text,
    ):
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
    return (
        constraint.get("description")
        or constraint.get("rule_type")
        or constraint.get("type", "custom rule")
    )
