import asyncio

from app import db
from app.routes import shop as shop_routes
from app.routes.shop import _leave_staffing_warnings
from tests.test_api import EMPLOYEE, auth, register


def test_warning_only_when_new_leave_pushes_staff_below_learned_need():
    employees = [
        {"employee_id": employee_id, "name": employee_id, "role": "Cashier",
         "age": 25, "is_active": True, "max_weekly_hours": 40}
        for employee_id in ("alice", "bob", "carol")
    ]
    rosters = [
        {
            "week_start": week,
            "approved": True,
            "shifts": [
                {"employee_id": employee_id, "day": "mon", "start": "09:00", "end": "17:00"}
                for employee_id in ("alice", "bob")
            ],
        }
        for week in ("2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26")
    ]
    day = {"2026-02-02"}

    assert _leave_staffing_warnings({}, employees, rosters, [], "alice", day) == []

    alice_off = [{
        "holiday_id": "hol_alice", "employee_id": "alice",
        "scope": "employee", "date": "2026-02-02", "end_date": "2026-02-02",
    }]
    warnings = _leave_staffing_warnings(
        {}, employees, rosters, alice_off, "bob", day,
    )
    assert len(warnings) == 1
    assert "1 eligible staff would remain" in warnings[0]
    assert "normally needs 2" in warnings[0]

    assert _leave_staffing_warnings(
        {}, employees, rosters, alice_off, "alice", day,
        replace_ids={"hol_alice"},
    ) == []


def test_booking_can_be_confirmed_after_staffing_warning(client, monkeypatch):
    token = client.post("/api/auth/signup", json={
        "email": "leave-warning@example.com", "password": "password123",
        "name": "Owner", "shop_name": "Shop",
    }).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    employee_id = client.post("/api/employees", headers=headers, json={
        "name": "Alex", "email": "alex-warning@example.com", "role": "Cashier",
        "age_group": "18_plus", "hourly_rate": 15, "max_weekly_hours": 40,
        "opening_holiday_hours": 40,
    }).json()["employee_id"]
    monkeypatch.setattr(
        shop_routes, "_leave_staffing_warnings",
        lambda *args, **kwargs: ["Monday 2 February: 1 eligible staff would remain, but 2 are needed."],
    )
    payload = {
        "employee_id": employee_id,
        "start_date": "2027-02-01", "end_date": "2027-02-01",
        "paid_dates": ["2027-02-01"],
    }

    warning = client.post("/api/holidays/leave", headers=headers, json=payload)
    assert warning.status_code == 409
    assert warning.json()["detail"]["code"] == "leave_staffing_shortage"
    assert client.get("/api/holidays", headers=headers).json() == []

    saved = client.post("/api/holidays/leave", headers=headers, json={
        **payload, "confirm_staffing_shortage": True,
    })
    assert saved.status_code == 201, saved.text


def test_selected_week_leave_includes_crossing_ranges_beyond_the_general_list_limit(client):
    headers = auth(register(client))
    group_headers = {**headers, "X-Roster-Group": "Deli"}
    shop = client.put("/api/shop", json={"departments": ["Shop Floor", "Deli"]}, headers=headers).json()
    employee = client.post("/api/employees", json={**EMPLOYEE, "departments": ["Deli"]}, headers=headers).json()
    other = client.post("/api/employees", json={**EMPLOYEE, "departments": ["Shop Floor"]}, headers=headers).json()
    records = [
        {"holiday_id": "crossing", "employee_id": employee["employee_id"], "scope": "employee",
         "date": "2026-11-20", "end_date": "2026-11-23"},
        {"holiday_id": "sunday", "employee_id": employee["employee_id"], "scope": "sick",
         "date": "2026-11-29"},
        {"holiday_id": "other_group", "employee_id": other["employee_id"], "scope": "employee",
         "date": "2026-11-23"},
        {"holiday_id": "closure", "scope": "shop", "date": "2026-11-24"},
        *[{"holiday_id": f"later_{i}", "employee_id": employee["employee_id"], "scope": "employee",
           "date": "2026-12-01"} for i in range(500)],
    ]
    asyncio.run(db.holidays.insert_many([{"shop_id": shop["shop_id"], **row} for row in records]))
    result = client.get("/api/holidays", params={"week_start": "2026-11-23"}, headers=group_headers)
    assert result.status_code == 200, result.text
    assert [row["holiday_id"] for row in result.json()] == ["crossing", "closure", "sunday"]
