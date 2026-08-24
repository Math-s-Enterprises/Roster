"""Custom rules compile without a language model.

A rule the solver cannot read does nothing. Compiling used to go through the
LLM, so a shop with no API key wrote rules that saved, displayed as enabled,
and were silently ignored.
"""
from app.services.rule_parser import parse_rule

TEAM = [
    {"employee_id": "e1", "name": "Sarah"},
    {"employee_id": "e2", "name": "Tom"},
    {"employee_id": "e3", "name": "Ben"},
    {"employee_id": "e4", "name": "Alice"},
    {"employee_id": "e5", "name": "Mark B"},
]


def parse(text):
    return parse_rule("", text, TEAM)


class TestCommonShapes:
    def test_never_works_a_day(self):
        rule = parse("Sarah never works Sundays")
        assert rule["type"] == "no_day"
        assert rule["days"] == ["sun"]
        assert rule["employee_ids"] == ["e1"]

    def test_several_days_at_once(self):
        rule = parse("Tom is not available on Saturday or Sunday")
        assert rule["type"] == "no_day"
        assert set(rule["days"]) == {"sat", "sun"}

    def test_no_closing_shifts(self):
        assert parse("Tom can't do closes")["type"] == "no_close"

    def test_no_opening_shifts(self):
        assert parse("Sarah shouldn't open")["type"] == "no_open"

    def test_a_cap_on_headcount(self):
        rule = parse("No more than 3 people on a Monday")
        assert rule["type"] == "max_staff"
        assert rule["value"] == 3
        assert rule["days"] == ["mon"]

    def test_two_people_kept_apart(self):
        rule = parse("Ben and Alice must not work together")
        assert rule["type"] == "not_together"
        assert set(rule["employee_ids"]) == {"e3", "e4"}


class TestCareful:
    def test_wording_it_cannot_read_is_not_guessed_at(self):
        """Reported as unparsed so the manager knows to reword it. A wrong
        guess enforced silently is worse than no rule."""
        assert parse("Make the roster nicer please") is None

    def test_a_statement_without_a_negation_is_not_a_prohibition(self):
        """'Sarah works Sundays' and 'Sarah never works Sundays' must not
        compile to the same constraint."""
        assert parse("Sarah works Sundays") is None

    def test_longer_names_win(self):
        """'Mark B' must not be read as 'Mark' when both could match."""
        rule = parse("Mark B never works Fridays")
        assert "e5" in rule["employee_ids"]

    def test_empty_text_is_not_a_rule(self):
        assert parse_rule("", "", TEAM) is None
