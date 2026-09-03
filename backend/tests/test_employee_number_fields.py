"""An empty number box must not become a zero.

`Number("")` is 0 in JavaScript, and the API rejects 0 for hours and rates
with "Input should be greater than 0". A manager clearing the weekly-hours
box therefore got a refusal that named no field, on a form with a dozen
numbers on it — and reasonably concluded the app was broken rather than that
one box was empty.

The form now omits a blank required number rather than sending 0, so the
model's own default stands. These tests pin the contract that relies on:
the API must accept a payload with the field missing, and must still refuse
a real zero.

Optional numbers keep behaving as they did — blank means null, meaning "not
set", which is a different thing from zero and always was.
"""
from tests.test_api import EMPLOYEE, auth, register


def test_a_missing_weekly_hours_takes_the_documented_default(client):
    """Blank is not zero and not an error: the field has a default of 40."""
    token = register(client)
    payload = {k: v for k, v in EMPLOYEE.items() if k != "max_weekly_hours"}

    created = client.post("/api/employees", json=payload, headers=auth(token))
    assert created.status_code == 201, created.text
    assert created.json()["max_weekly_hours"] == 40


def test_an_explicit_zero_is_still_refused(client):
    """Nobody has a nought-hour week, and silently accepting it would put an
    employee in the roster who can never be scheduled."""
    token = register(client)
    created = client.post(
        "/api/employees", json={**EMPLOYEE, "max_weekly_hours": 0},
        headers=auth(token),
    )
    assert created.status_code == 422, created.text

    # The message the UI turns into "Weekly hours: ...". Without a `loc` there
    # is nothing to name the field with, which was the whole problem.
    detail = created.json()["detail"]
    assert any("max_weekly_hours" in (d.get("loc") or []) for d in detail), detail


def test_optional_hours_may_be_absent_without_becoming_zero(client):
    """A salaried employee has no term-time cap, and saying so must not read
    as a cap of nought."""
    token = register(client)
    created = client.post(
        "/api/employees",
        json={
            **EMPLOYEE,
            "employment_type": "full_time_contract",
            "contract_span_hours": 40,
            "term_time_max_hours": None,
            "summer_break": None,
        },
        headers=auth(token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["contract_span_hours"] == 40
    assert body.get("term_time_max_hours") is None


def test_changing_contracted_hours_to_40_saves(client):
    """The exact edit that failed: a salaried contract set to 40 hours."""
    token = register(client)
    employee_id = client.post(
        "/api/employees", json=EMPLOYEE, headers=auth(token),
    ).json()["employee_id"]

    updated = client.put(
        f"/api/employees/{employee_id}",
        json={
            **EMPLOYEE,
            "employment_type": "full_time_contract",
            "contract_span_hours": 40,
        },
        headers=auth(token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["contract_span_hours"] == 40
