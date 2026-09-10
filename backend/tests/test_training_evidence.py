from copy import deepcopy

from app.services.training_evidence import (
    approval_evidence,
    context,
    hard_constraints,
    historical_examples,
)
from tests.test_api import (
    TestCorrectionCapture as CaptureHelper,
    _future_monday,
    auth,
    register,
)


def test_context_keeps_constraints_without_contact_details_or_mutable_references():
    employee = {"employee_id": "e", "email": "private@example.com", "name": "Private",
                "hourly_rate": 99, "availability": {"earliest_start": "09:00"},
                "contract_span_hours": 40}
    captured = context({"shop_id": "s", "roster_recipients": [{"email": "private"}]},
                       [employee], [], [{"days": ["mon"], "start": "09:00"}], [])
    employee["availability"]["earliest_start"] = "12:00"
    assert captured["employees"][0] == {"employee_id": "e", "availability": {"earliest_start": "09:00"}, "contract_span_hours": 40}
    assert captured["shop"] == {"shop_id": "s"}
    assert captured["fixed_shifts"][0]["days"] == ["mon"]


def test_context_hash_is_stable_across_capture_time_and_database_order():
    shop = {"shop_id": "s", "min_rest_hours": 10}
    employees = [
        {"employee_id": "b", "max_weekly_hours": 20},
        {"employee_id": "a", "max_weekly_hours": 30},
    ]
    first = context(shop, employees, [], [], [], week_start="2026-09-14")
    second = context(shop, list(reversed(employees)), [], [], [],
                     week_start="2026-09-14")
    assert first["captured_at"] != second["captured_at"]
    assert first["context_hash"] == second["context_hash"]


def test_effective_hard_constraints_include_caps_leave_and_shop_policy():
    constraints = hard_constraints(
        {"max_shift_hours": 14, "max_working_days": 4, "min_rest_hours": 10},
        [{"employee_id": "e", "role": "assistant", "max_weekly_hours": 24}],
        [{"scope": "employee", "employee_id": "e", "date": "2026-09-16"}],
        "2026-09-14",
    )
    policy = constraints["policy"]
    employee = constraints["employees"][0]
    assert policy["effective_max_shift_hours"] == 12
    assert policy["max_working_days"] == 4
    assert policy["min_rest_hours"] == 10
    assert employee["weekly_hour_cap"] == 24
    assert employee["leave_dates"] == ["2026-09-16"]


def test_ambiguous_and_exception_rows_never_become_positive_observations():
    shift = {"employee_id": "e", "day": "mon", "start": "09:00", "end": "17:00"}
    roster = {"approved": True, "week_start": "2026-08-24", "shifts": [shift, deepcopy(shift)]}
    observations = [
        row for row in historical_examples([roster])
        if row["kind"] != "approval_outcome"
    ]
    assert all(row["kind"] == "quarantine" for row in observations)
    assert all(r["reason"] == "missing_or_duplicate_week" for r in historical_examples([roster, deepcopy(roster)]))
    roster["shifts"] = [{**shift, "sick": True}]
    assert list(historical_examples([roster]))[0]["reasons"] == ["exception"]


def test_export_uses_approval_snapshot_after_working_roster_changes():
    approved = {"employee_id": "e", "day": "mon", "start": "09:00", "end": "17:00"}
    row = list(historical_examples([{"approved": True, "week_start": "2026-08-24",
        "training_approval": {"shifts": [approved]}, "shifts": []}]))[0]
    assert row["shift"] == approved
    assert row["eligibility_verified"] is False


def test_clean_swap_is_the_only_pairwise_training_label():
    swap = {"kind": "swap", "day": "mon", "slot": "09:00-17:00",
            "employee_id": "chosen", "replaced_employee_id": "proposed"}
    approval = {
        "shifts": [{"employee_id": "chosen", "day": "mon",
                    "start": "09:00", "end": "17:00"}],
        "ordinary_training_eligible": True,
        "outcome": "edited",
        "corrections": [swap],
        "exclusion_reasons": [],
        "context_unchanged": True,
    }
    rows = list(historical_examples([{
        "approved": True, "week_start": "2026-08-24",
        "training_approval": approval, "generated_shifts": [{
            "employee_id": "proposed", "day": "mon",
            "start": "09:00", "end": "17:00",
        }],
    }]))
    correction = next(row for row in rows if row["kind"] == "manager_correction")
    assert correction["trainable"] is True
    assert correction["training_label"] == "pairwise_preference"


def test_removal_is_recorded_but_not_guessed_to_be_a_preference():
    approval = {
        "shifts": [], "ordinary_training_eligible": True, "outcome": "edited",
        "corrections": [{"kind": "removed", "day": "mon",
                         "employee_id": "e", "slot": "09:00-17:00"}],
        "exclusion_reasons": [], "context_unchanged": True,
    }
    rows = list(historical_examples([{
        "approved": True, "week_start": "2026-08-24",
        "training_approval": approval,
        "generated_shifts": [{"employee_id": "e", "day": "mon",
                              "start": "09:00", "end": "17:00"}],
    }]))
    correction = next(row for row in rows if row["kind"] == "manager_correction")
    assert correction["trainable"] is False
    assert correction["training_label"] is None
    assert "not_a_pairwise_employee_choice" in correction["reasons"]


def test_legacy_correction_is_exported_but_never_backfilled_as_a_label():
    roster = {
        "approved": True, "week_start": "2026-08-24", "shifts": [],
        "corrections": [{"kind": "swap", "day": "mon",
                         "employee_id": "chosen",
                         "replaced_employee_id": "proposed",
                         "slot": "09:00-17:00"}],
    }
    rows = list(historical_examples([roster]))
    correction = next(row for row in rows if row["kind"] == "manager_correction")
    assert correction["trainable"] is False
    assert correction["training_label"] is None
    assert "missing_approval_snapshot" in correction["reasons"]


def test_swap_from_an_ineligible_approval_is_not_a_training_label():
    approval = {
        "shifts": [], "ordinary_training_eligible": False,
        "outcome": "approved_with_gaps",
        "corrections": [{"kind": "swap", "day": "mon",
                         "employee_id": "chosen",
                         "replaced_employee_id": "proposed",
                         "slot": "09:00-17:00"}],
        "exclusion_reasons": ["approved_with_uncovered_hours"],
    }
    rows = list(historical_examples([{
        "approved": True, "week_start": "2026-08-24",
        "training_approval": approval, "generated_shifts": [],
    }]))
    correction = next(row for row in rows if row["kind"] == "manager_correction")
    assert correction["trainable"] is False
    assert "approval_not_training_eligible" in correction["reasons"]


def test_forced_or_gapped_approval_is_explicitly_excluded():
    evidence = approval_evidence(
        approval_context={"context_hash": "same"},
        generation_context={"context_hash": "same"},
        generation_shifts=[], final_shifts=[], corrections=[], forced=True,
        uncovered_hours=[{"day": "mon", "hour": 9}], breaches=[],
        constraint_result={},
    )
    assert evidence["outcome"] == "forced"
    assert evidence["ordinary_training_eligible"] is False
    assert set(evidence["exclusion_reasons"]) == {
        "approved_with_uncovered_hours", "forced_or_breaching_approval",
    }


def test_generation_context_survives_edits_and_approval_records_final_decision(client):
    helper = CaptureHelper()
    token = register(client)
    rid, _, _ = helper._week(client, token)
    original = helper._get(client, token, rid)
    captured = original["training_context"]
    first = original["shifts"][0]
    edited = [{"employee_id": first["employee_id"], "day": first["day"], "start": "10:00", "end": "18:00"}]
    response = client.put(f"/api/rosters/{rid}", json={"shifts": edited}, headers=auth(token))
    assert response.status_code == 200, response.text
    response = client.post(f"/api/rosters/{rid}/approve?acknowledge_gaps=true", headers=auth(token))
    assert response.status_code == 200, response.text
    after = helper._get(client, token, rid)
    assert after["training_context"] == captured
    assert captured["solver_source_hash"] and captured["model_version"] is None
    assert captured["hard_constraints"]["employees"]
    assert captured["demand_profile"] is not None
    assert "arrivals" in captured["demand_profile"]
    assert captured["preference_weights"] is not None
    assert original["training_proposal"]["decisions"]
    assert original["training_proposal"]["constraint_outcome"] is not None
    assert after["training_approval"]["shifts"][0]["start"] == "10:00"
    assert after["training_approval"]["baseline_available"] is True
    assert after["training_approval"]["context"]["employees"]
    assert after["training_approval"]["outcome"] == "approved_with_gaps"
    assert after["training_approval"]["ordinary_training_eligible"] is False


def test_unchanged_clean_approval_is_usable_evidence(client):
    token = register(client)
    hours = [
        {"day": day, "open": "09:00", "close": "13:00", "closed": day != "mon"}
        for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    ]
    assert client.put("/api/shop", json={"hours": hours},
                      headers=auth(token)).status_code == 200
    client.post("/api/employees", json={
        "name": "Alex", "email": "alex@e.com", "role": "Cashier",
        "age": 25, "hourly_rate": 15, "max_weekly_hours": 40,
    }, headers=auth(token))
    generated = client.post(
        "/api/roster/generate", json={"week_start": _future_monday()},
        headers=auth(token),
    )
    assert generated.status_code == 200, generated.text
    rid = generated.json()["roster_id"]
    response = client.post(
        f"/api/rosters/{rid}/approve?acknowledge_gaps=true", headers=auth(token),
    )
    assert response.status_code == 200, response.text
    approval = client.get(
        f"/api/rosters/{rid}", headers=auth(token),
    ).json()["training_approval"]
    assert approval["outcome"] == "unchanged"
    assert approval["context_unchanged"] is True
    assert approval["ordinary_training_eligible"] is True
    assert approval["exclusion_reasons"] == []


def test_empty_generated_snapshot_is_still_measurable():
    from app.services.corrections import edit_trend, summarise

    roster = {
        "approved": True, "week_start": "2026-09-14",
        "generated_shifts": [], "corrections": [],
    }
    assert edit_trend([roster])[0]["measurable"] is True
    assert summarise([roster])["weeks_measured"] == 1
