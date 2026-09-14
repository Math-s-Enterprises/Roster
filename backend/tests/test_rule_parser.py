"""Custom rules compile without a language model.

A rule the solver cannot read does nothing. Compiling used to go through the
LLM, so a shop with no API key wrote rules that saved, displayed as enabled,
and were silently ignored.
"""
import asyncio

import pytest

from app.services import llm
from app.services.rule_parser import parse_rule, validate_constraint

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
    def test_manager_or_supervisor_at_closing_uses_the_role_schema(self):
        rule = parse(
            "I want either manager or supervisor closing every day. "
            "There should be at least one."
        )
        assert rule == {
            "rule_type": "ROLE_REQUIREMENT",
            "target_roles": ["Manager", "Supervisor"],
            "time_slot": "CLOSING",
            "min_count": 1,
            "condition": "AT_LEAST",
            "days": [],
            "description": "A manager or supervisor must cover closing",
        }

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

    def test_an_unsupported_model_rule_cannot_be_approved(self):
        with pytest.raises(ValueError, match="Unsupported rule type"):
            validate_constraint({"rule_type": "REST_PERIOD", "min_count": 1})


def test_anthropic_requests_schema_enforced_output(monkeypatch):
    captured = {}

    class Messages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {
                "content": [type("Block", (), {
                    "type": "text",
                    "text": '{"rule_type":"ROLE_REQUIREMENT"}',
                })()]
            })()

    monkeypatch.setattr(
        llm, "_get_client", lambda: type("Client", (), {"messages": Messages()})()
    )
    asyncio.run(llm._complete(
        "system", "prompt", output_schema=llm.ROSTER_RULE_SCHEMA
    ))

    assert captured["output_config"] == {
        "format": {"type": "json_schema", "schema": llm.ROSTER_RULE_SCHEMA}
    }


class TestANumberMustBeAboutPeople:
    """"Shop floor shifts are a maximum of 8 hours" compiled to max_staff: 8.

    It showed as Enforced and silently capped the shop at eight staff instead
    of limiting shift length. A rule that quietly does the wrong thing is
    worse than one that refuses — §9: unparseable rules are reported, not
    guessed at.
    """

    def _people(self):
        return [{"employee_id": "e1", "name": "Jane", "role": "Shop Floor"}]

    def test_a_length_in_hours_is_not_a_headcount(self):
        for text in (
            "Shop floor shifts are a maximum of 8 hours",
            "No more than 8 hours per shift",
            "At most 10 hrs in a shift",
        ):
            assert parse_rule("rule", text, self._people()) is None, text

    def test_a_count_of_days_is_not_a_headcount(self):
        assert parse_rule(
            "rule", "At most 3 days a week", self._people()) is None

    def test_a_real_headcount_still_compiles(self):
        for text in (
            "No more than 3 people on a Monday",
            "Maximum of 4 staff on Sunday",
            "No more than 5 on a Saturday",
        ):
            compiled = parse_rule("rule", text, self._people())
            assert compiled and compiled["type"] == "max_staff", text
