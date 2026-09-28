"""Roster groups learn separately while employee limits remain shop-wide."""
from datetime import date, timedelta

from app.services.departments import rules_for
from app.services.scheduler import DAYS, shift_paid_hours, solve_roster
from tests.test_api import auth, register


WEEK = "2026-09-14"


def test_custom_rules_can_be_scoped_without_hiding_global_or_locked_rules():
    rules = [
        {"rule_id": "global", "departments": []},
        {"rule_id": "deli", "departments": ["Deli"]},
        {"rule_id": "floor", "departments": ["Shop Floor"]},
        {"rule_id": "system", "locked": True, "departments": ["Deli"]},
    ]
    assert [rule["rule_id"] for rule in rules_for(rules, "Shop Floor")] == [
        "global", "floor", "system",
    ]


def test_each_group_has_its_own_settings_and_employee_role(client):
    token = register(client, email="group-settings@example.com")
    primary_headers = auth(token)
    deli_headers = {**primary_headers, "X-Roster-Group": "Deli"}

    configured = client.put("/api/shop", json={
        "departments": ["Shop Floor", "Deli"],
        "role_hierarchy": ["Store Manager", "Store Assistant"],
    }, headers=primary_headers)
    assert configured.status_code == 200, configured.text

    deli_hours = [
        {"day": day, "open": "07:00", "close": "15:00", "closed": day == "sun"}
        for day in DAYS
    ]
    deli_settings = client.put("/api/shop", json={
        "hours": deli_hours,
        "min_shift_hours": 3,
        "max_shift_hours": 7,
        "role_hierarchy": ["Deli Manager", "Deli Assistant"],
        "supervisory_roles": ["Deli Manager"],
    }, headers=deli_headers)
    assert deli_settings.status_code == 200, deli_settings.text
    assert deli_settings.json()["current_department"] == "Deli"
    assert deli_settings.json()["role_hierarchy"] == ["Deli Manager", "Deli Assistant"]
    assert deli_settings.json()["hours"] == deli_hours

    floor_settings = client.get("/api/shop", headers=primary_headers).json()
    assert floor_settings["current_department"] == "Shop Floor"
    assert floor_settings["role_hierarchy"] == ["Store Manager", "Store Assistant"]
    assert floor_settings["hours"] != deli_hours

    floor_employee = _employee_payload("Shared Manager", ["Shop Floor", "Deli"])
    floor_employee["role"] = "Store Manager"
    employee = client.post(
        "/api/employees", json=floor_employee, headers=primary_headers,
    ).json()
    deli_employee = {**floor_employee, "role": "Deli Manager"}
    changed = client.put(
        f"/api/employees/{employee['employee_id']}",
        json=deli_employee, headers=deli_headers,
    )
    assert changed.status_code == 200, changed.text

    floor_people = client.get("/api/employees", headers=primary_headers).json()
    deli_people = client.get("/api/employees", headers=deli_headers).json()
    assert floor_people[0]["role"] == "Store Manager"
    assert deli_people[0]["role"] == "Deli Manager"


def test_group_reports_are_scoped_but_dashboard_activity_spans_groups(client):
    token = register(client, email="group-reports@example.com")
    floor_headers = auth(token)
    deli_headers = {**floor_headers, "X-Roster-Group": "Deli"}
    client.put("/api/shop", json={
        "departments": ["Shop Floor", "Deli"],
    }, headers=floor_headers)

    floor_person = client.post(
        "/api/employees",
        json=_employee_payload("Floor Person", ["Shop Floor"]),
        headers=floor_headers,
    ).json()
    deli_person = client.post(
        "/api/employees",
        json=_employee_payload("Deli Person", ["Deli"]),
        headers=deli_headers,
    ).json()

    floor_balances = client.get(
        "/api/holiday-balance", headers=floor_headers,
    ).json()
    deli_balances = client.get(
        "/api/holiday-balance", headers=deli_headers,
    ).json()
    assert {row["employee_id"] for row in floor_balances} == {
        floor_person["employee_id"],
    }
    assert {row["employee_id"] for row in deli_balances} == {
        deli_person["employee_id"],
    }

    first_week = date.fromisoformat(_future_monday())
    for offset, department, headers in (
        (0, "Shop Floor", floor_headers), (7, "Deli", deli_headers),
    ):
        week = (first_week + timedelta(days=offset)).isoformat()
        generated = client.post(
            "/api/roster/generate",
            json={"week_start": week, "department": department},
            headers=headers,
        )
        assert generated.status_code == 200, generated.text
        approved = client.post(
            f"/api/rosters/{generated.json()['roster_id']}/approve",
            params={"acknowledge_gaps": True}, headers=headers,
        )
        assert approved.status_code == 200, approved.text

    floor_report = client.get(
        "/api/reports/corrections", headers=floor_headers,
    ).json()
    deli_report = client.get(
        "/api/reports/corrections", headers=deli_headers,
    ).json()
    assert floor_report["weeks_measured"] == 1
    assert deli_report["weeks_measured"] == 1

    activity = client.get("/api/activity", headers=floor_headers).json()
    details = [item["detail"] for item in activity]
    assert any(detail.startswith("Shop Floor:") for detail in details)
    assert any(detail.startswith("Deli:") for detail in details)

def _shop():
    return {
        "hours": [
            {"day": day, "open": "09:00", "close": "17:00", "closed": day != "tue"}
            for day in DAYS
        ],
        "min_shift_hours": 4,
        "max_shift_hours": 8,
        "max_working_days": 5,
        "strict_days_off": True,
        "role_hierarchy": ["Assistant"],
    }


def _employee(employee_id, departments):
    return {
        "employee_id": employee_id,
        "name": employee_id.title(),
        "role": "Assistant",
        "age": 25,
        "hourly_rate": 15,
        "max_weekly_hours": 8,
        "preferred_days_off": [],
        "departments": departments,
        "is_active": True,
        "employment_type": "hourly",
    }


def test_other_department_shift_uses_weekly_cap_but_not_department_coverage():
    shared = _employee("shared", ["Shop Floor", "Deli"])
    floor_only = _employee("floor", ["Shop Floor"])

    result = solve_roster(
        _shop(), [shared, floor_only], [], [], [], WEEK,
        external_shifts=[{
            "employee_id": "shared", "day": "mon", "start": "09:00", "end": "17:00",
            "department": "Deli",
        }],
    )

    assert not any(s["employee_id"] == "shared" for s in result["shifts"])
    assert any(s["employee_id"] == "floor" and s["day"] == "tue" for s in result["shifts"])
    assert result["per_employee_hours"]["shared"] == round(shift_paid_hours(
        {"start": "09:00", "end": "17:00"},
    ), 1)
    assert all("department" not in s for s in result["shifts"])


def _future_monday():
    today = date.today()
    return (today + timedelta(days=(7 - today.weekday()) + 7)).isoformat()


def _employee_payload(name, departments):
    return {
        "name": name,
        "email": None,
        "role": "Cashier",
        "age": 25,
        "hourly_rate": 15,
        "max_weekly_hours": 40,
        "preferred_days_off": [],
        "departments": departments,
    }


def test_manual_shift_is_refused_when_employee_works_in_another_group(client):
    token = register(client)
    headers = auth(token)
    configured = client.put("/api/shop", json={
        "departments": ["Shop Floor", "Deli"],
    }, headers=headers)
    assert configured.status_code == 200, configured.text
    assert configured.json()["multi_department"] is True

    shared = client.post("/api/employees", json=_employee_payload(
        "Shared Person", ["Shop Floor", "Deli"],
    ), headers=headers).json()
    client.post("/api/employees", json=_employee_payload(
        "Floor Person", ["Shop Floor"],
    ), headers=headers)

    week = _future_monday()
    deli = client.post("/api/roster/generate", json={
        "week_start": week, "department": "Deli",
    }, headers=headers)
    assert deli.status_code == 200, deli.text
    deli_shift = next(s for s in deli.json()["shifts"]
                      if s["employee_id"] == shared["employee_id"] and s.get("start"))

    floor = client.post("/api/roster/generate", json={
        "week_start": week, "department": "Shop Floor",
    }, headers=headers)
    assert floor.status_code == 200, floor.text
    body = floor.json()
    assert any(s["employee_id"] == shared["employee_id"]
               and s["department"] == "Deli" for s in body["external_shifts"])

    floor_list = client.get("/api/rosters", headers=headers).json()
    all_groups = client.get(
        "/api/rosters", params={"all_departments": True}, headers=headers,
    ).json()
    assert {r["department"] for r in floor_list} == {"Shop Floor"}
    assert {r["department"] for r in all_groups} == {"Shop Floor", "Deli"}

    shifts = [
        {key: shift.get(key, False if key.endswith("holiday") or key == "sick" else "")
         for key in ("employee_id", "day", "start", "end", "paid_holiday",
                     "unpaid_holiday", "sick")}
        for shift in body["shifts"]
        if not (shift["employee_id"] == shared["employee_id"]
                and shift["day"] == deli_shift["day"])
    ]
    shifts.append({
        "employee_id": shared["employee_id"], "day": deli_shift["day"],
        "start": "09:00", "end": "17:00", "paid_holiday": False,
        "unpaid_holiday": False, "sick": False,
    })
    refused = client.put(
        f"/api/rosters/{body['roster_id']}", json={"shifts": shifts}, headers=headers,
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "other_department_shift"
    assert "Deli" in refused.text


def test_a_roster_group_in_use_cannot_be_removed(client):
    token = register(client, email="used-group@example.com")
    headers = auth(token)
    configured = client.put("/api/shop", json={
        "departments": ["Shop Floor", "Deli"],
    }, headers=headers)
    assert configured.status_code == 200, configured.text
    created = client.post("/api/employees", json=_employee_payload(
        "Deli Person", ["Deli"],
    ), headers=headers)
    assert created.status_code == 201, created.text

    removed = client.put("/api/shop", json={
        "departments": ["Shop Floor"],
    }, headers=headers)
    assert removed.status_code == 409, removed.text
    assert "Deli" in removed.text


def test_same_import_week_is_allowed_once_per_group(client):
    token = register(client, email="imports@example.com")
    headers = auth(token)
    client.put("/api/shop", json={
        "departments": ["Shop Floor", "Deli"],
    }, headers=headers)
    csv = b"Name,Mon,Tue,Wed,Thu,Fri,Sat,Sun\nStaff,,,,,,,\nJane,09.00-17.00 (8),,,,,,\n"

    for department in ("Shop Floor", "Deli"):
        upload = client.post(
            "/api/imports",
            files={"file": (f"{department}.csv", csv, "text/csv")},
            data={"week_start": WEEK, "department": department},
            headers=headers,
        )
        assert upload.status_code == 201, upload.text
        committed = client.post(
            f"/api/imports/{upload.json()['import_id']}/commit",
            json={"skip_unmapped": False}, headers=headers,
        )
        assert committed.status_code == 200, committed.text
        assert committed.json()["weeks_imported"] == 1

    history = client.get("/api/imports/history", headers=headers).json()
    assert {(row["week_start"], row["department"]) for row in history} == {
        (WEEK, "Shop Floor"), (WEEK, "Deli"),
    }


def test_import_mapping_adds_existing_employee_without_duplication(client):
    token = register(client, email="shared-import@example.com")
    floor_headers = auth(token)
    deli_headers = {**floor_headers, "X-Roster-Group": "Deli"}
    client.put("/api/shop", json={
        "departments": ["Shop Floor", "Deli"],
    }, headers=floor_headers)
    client.put("/api/shop", json={
        "role_hierarchy": ["Deli Manager", "Deli Assistant"],
        "roles": ["Deli Manager", "Deli Assistant"],
    }, headers=deli_headers)
    jane = client.post(
        "/api/employees", json=_employee_payload("Jane", ["Shop Floor"]),
        headers=floor_headers,
    ).json()

    csv = b"Name,Mon,Tue,Wed,Thu,Fri,Sat,Sun\nStaff,,,,,,,\nJane,09.00-17.00 (8),,,,,,\n"
    upload = client.post(
        "/api/imports",
        files={"file": ("deli.csv", csv, "text/csv")},
        data={"week_start": WEEK, "department": "Deli"},
        headers=deli_headers,
    )
    assert upload.status_code == 201, upload.text
    committed = client.post(
        f"/api/imports/{upload.json()['import_id']}/commit",
        json={
            "skip_unmapped": False,
            "employee_map": {"Jane": jane["employee_id"]},
        },
        headers=deli_headers,
    )
    assert committed.status_code == 200, committed.text

    deli_people = client.get("/api/employees", headers=deli_headers).json()
    assert [person["employee_id"] for person in deli_people] == [jane["employee_id"]]
    # This CSV carries no role, so preserve the known title rather than
    # inventing a Deli title merely because it ranks in that workspace.
    assert deli_people[0]["role"] == "Cashier"
    all_people = client.get(
        "/api/employees", params={"all_departments": True}, headers=floor_headers,
    ).json()
    assert [person["employee_id"] for person in all_people] == [jane["employee_id"]]


def test_other_group_import_is_not_used_as_learning_history(client):
    token = register(client, email="learning-groups@example.com")
    headers = auth(token)
    client.put("/api/shop", json={
        "departments": ["Shop Floor", "Deli"],
    }, headers=headers)
    client.post("/api/employees", json=_employee_payload(
        "Floor Person", ["Shop Floor"],
    ), headers=headers)

    csv = b"Name,Mon,Tue,Wed,Thu,Fri,Sat,Sun\nStaff,,,,,,,\nDeli Person,09.00-17.00 (8),,,,,,\n"
    upload = client.post(
        "/api/imports",
        files={"file": ("deli.csv", csv, "text/csv")},
        data={"week_start": WEEK, "department": "Deli"},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    committed = client.post(
        f"/api/imports/{upload.json()['import_id']}/commit",
        json={"skip_unmapped": False}, headers=headers,
    )
    assert committed.status_code == 200, committed.text

    generated = client.post("/api/roster/generate", json={
        "week_start": _future_monday(), "department": "Shop Floor",
    }, headers=headers)
    assert generated.status_code == 200, generated.text
    assert generated.json()["training_context"]["history_sources"] == []
