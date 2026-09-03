"""Change a rule or a contract, and THIS week reflects it — without regenerating.

The shop owner asked for this twice: "if I go back and change shop rules or
employee contract or something, that should reflect on the roster which I'm
working on currently. Refresh just for the rules, not for the roster."

Regenerate already answers it and is the wrong answer — it throws away every
edit the manager has made, which is why they stopped pressing it. So the
figures that DESCRIBE THE WEEK are derived on read (§5) rather than stored at
generation, and the page refetches them on demand.

What is derived, and what is not:

  derived   coverage gaps, rule breaches, "against the usual", who is below
            their contracted hours, which custom rules cannot be read
  stored    what the SOLVER DID — "Martin's shift was changed from X to Y".
            That is a record of a past action. Recomputing it would be
            fiction, and it is not what goes stale.

These tests are about the first row. They go through the HTTP API rather than
calling the services, because the bug was never in the arithmetic — it was
that the page was reading a stored copy.
"""
from tests.test_api import EMPLOYEE, auth, register

# The `client` fixture comes from tests/conftest.py.


WEEK = "2026-10-05"


def _shop_open_all_week(client, token):
    client.put(
        "/api/shop",
        json={"hours": [
            {"day": d, "open": "09:00", "close": "17:00", "closed": False}
            for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        ]},
        headers=auth(token),
    )


def _generate(client, token):
    response = client.post(
        "/api/roster/generate", json={"week_start": WEEK}, headers=auth(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _audit(client, token, roster_id):
    response = client.get(
        f"/api/rosters/{roster_id}/audit", headers=auth(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestRaisingAContractShowsUpWithoutRegenerating:
    """The case the owner described. Somebody's contract goes up; the week
    they are looking at is now short, and they must be told before they
    approve it."""

    def test_the_audit_reports_the_shortfall_the_moment_the_contract_changes(
        self, client
    ):
        token = register(client)
        _shop_open_all_week(client, token)
        created = client.post(
            "/api/employees",
            json={**EMPLOYEE, "max_weekly_hours": 20},
            headers=auth(token),
        )
        assert created.status_code == 201, created.text
        employee_id = created.json()["employee_id"]

        roster = _generate(client, token)
        before = _audit(client, token, roster["roster_id"])
        assert not any(
            u["employee_id"] == employee_id
            for u in before.get("under_contract", [])
        ), "an hourly employee has a ceiling, not a floor, and must not be flagged"

        # The manager puts them on a salaried contract, in another screen,
        # without touching the roster.
        updated = client.put(
            f"/api/employees/{employee_id}",
            json={
                **EMPLOYEE,
                "max_weekly_hours": 20,
                "employment_type": "full_time_contract",
                "contract_span_hours": 42.5,
            },
            headers=auth(token),
        )
        assert updated.status_code == 200, updated.text

        after = _audit(client, token, roster["roster_id"])
        assert any(
            u["employee_id"] == employee_id
            for u in after.get("under_contract", [])
        ), (
            "the contract went to 42.5h and this week does not reach it, so "
            "the roster page must say so without the manager regenerating "
            f"and losing their edits — got {after.get('under_contract')}"
        )


class TestARuleThatCannotBeReadIsReportedLive:
    """§9: an unparseable rule is reported, not guessed at. Writing a rule,
    seeing it listed as Enabled and getting a roster that breaks it is worse
    than not offering the feature at all."""

    def test_adding_an_unreadable_rule_shows_up_on_the_existing_week(self, client):
        token = register(client)
        _shop_open_all_week(client, token)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))

        roster = _generate(client, token)
        assert _audit(client, token, roster["roster_id"])["inactive_rules"] == []

        created = client.post(
            "/api/ai-rules",
            json={
                "title": "Vibes only",
                "description": "make the roster feel nicer somehow",
                "enabled": True,
            },
            headers=auth(token),
        )
        assert created.status_code in (200, 201), created.text

        after = _audit(client, token, roster["roster_id"])
        assert "Vibes only" in after["inactive_rules"], (
            "a rule that cannot be compiled does nothing, and the week the "
            f"manager is looking at must say so — got {after['inactive_rules']}"
        )

    def test_a_readable_rule_is_not_reported(self, client):
        token = register(client)
        _shop_open_all_week(client, token)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        roster = _generate(client, token)

        client.post(
            "/api/ai-rules",
            json={
                "title": "No more than 3 people on a Monday",
                "description": "No more than 3 people on a Monday",
                "enabled": True,
            },
            headers=auth(token),
        )
        after = _audit(client, token, roster["roster_id"])
        assert after["inactive_rules"] == [], (
            f"this one parses, so nothing should be flagged — got "
            f"{after['inactive_rules']}"
        )


def test_looking_does_not_change_the_week(client):
    """Re-checking is a read. If it rewrote the roster it would be an edit
    with none of an edit's protections, and `updated_at` would move every
    time the manager opened the page."""
    token = register(client)
    _shop_open_all_week(client, token)
    client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
    roster = _generate(client, token)

    first = client.get(
        f"/api/rosters/{roster['roster_id']}", headers=auth(token),
    ).json()
    _audit(client, token, roster["roster_id"])
    second = client.get(
        f"/api/rosters/{roster['roster_id']}", headers=auth(token),
    ).json()

    assert first.get("updated_at") == second.get("updated_at")
    assert [
        (s["employee_id"], s["day"], s.get("start"), s.get("end"))
        for s in first["shifts"]
    ] == [
        (s["employee_id"], s["day"], s.get("start"), s.get("end"))
        for s in second["shifts"]
    ]
