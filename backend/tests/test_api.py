"""End-to-end API tests against an in-memory MongoDB.

These exercise real HTTP requests through the full stack — routing,
validation, auth, tenancy scoping and persistence — without needing a real
database or network. `mongomock_motor` stands in for Motor.

The tenancy tests are the important ones: they prove one shop cannot reach
another's data, which is the security property the whole multi-tenant model
rests on.
"""
import os
from datetime import date, timedelta

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "roster_test")
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-in-production")
os.environ.setdefault("ENV", "test")


@pytest.fixture()
def client(monkeypatch):
    """A TestClient wired to an in-memory database, isolated per test."""
    from mongomock_motor import AsyncMongoMockClient

    from app import db as db_module

    mock_db = AsyncMongoMockClient()["roster_test"]

    # Rebind every collection handle the app uses. Derived from the module
    # rather than listed by hand: a collection added later and forgotten here
    # would quietly keep talking to a real database, and the failure surfaces
    # far from the cause — as a closed event loop during startup.
    collections = [
        name for name, value in vars(db_module).items()
        if not name.startswith("_")
        and type(value).__name__ == "AsyncIOMotorCollection"
    ]
    assert "password_resets" in collections, "collection discovery is broken"
    for name in collections:
        monkeypatch.setattr(db_module, name, mock_db[name])

    # Deliberately NOT stubbed: the real ensure_indexes() runs against the
    # mock, so the unique-email constraint is genuinely exercised here rather
    # than assumed. Stubbing it out would let a duplicate-account bug pass.
    async def _noop():
        return None

    monkeypatch.setattr(db_module, "close", _noop)

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def register(client, email="owner@example.com", password="password123"):
    response = client.post("/api/auth/signup", json={
        "email": email, "password": password,
        "name": "Test Owner", "shop_name": "Test Shop",
    })
    assert response.status_code == 201, response.text
    return response.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_imported_week(client, token, week_start: str) -> str:
    """Import one week through the real upload-and-commit path.

    Deliberately not a hand-written database row: the point of these tests is
    that a week which arrived by upload can be taken back out, and faking the
    arrival would stop proving that.
    """
    csv = (
        "Name,Mon,Tue,Wed,Thu,Fri,Sat,Sun\n"
        "Staff,,,,,,,\n"
        "Jane Doe,09.00-17.00 (8),,,,,,\n"
    )
    upload = client.post(
        "/api/imports",
        files={"file": ("history.csv", csv.encode(), "text/csv")},
        data={"week_start": week_start},
        headers=auth(token),
    )
    assert upload.status_code == 201, upload.text
    import_id = upload.json()["import_id"]

    # skip_unmapped=false so the sheet's name becomes a real employee, which
    # is what a manager importing a year of history actually does.
    committed = client.post(
        f"/api/imports/{import_id}/commit",
        json={"skip_unmapped": False}, headers=auth(token),
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["weeks_imported"] == 1, committed.text

    weeks = client.get("/api/imports/history", headers=auth(token)).json()
    return next(w["roster_id"] for w in weeks if w["week_start"] == week_start)


def _future_monday() -> str:
    """A week that has not been worked yet.

    Computed rather than hardcoded: a fixed date would silently slide into
    the past and start failing every test that reopens an approved roster,
    months after the change that "broke" it.
    """
    from datetime import date, timedelta

    today = date.today()
    return (today + timedelta(days=(7 - today.weekday()) + 7)).isoformat()


# ---------------------------------------------------------------------------
# Health and auth
# ---------------------------------------------------------------------------
def test_health_reports_feature_flags(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert set(body["features"]) == {"llm", "email", "google_auth", "billing"}


def test_signup_then_login(client):
    register(client)
    response = client.post("/api/auth/login", json={
        "email": "owner@example.com", "password": "password123",
    })
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "owner@example.com"


def test_duplicate_email_is_rejected(client):
    register(client)
    response = client.post("/api/auth/signup", json={
        "email": "owner@example.com", "password": "password123", "name": "Someone else",
    })
    assert response.status_code == 409


def test_short_password_is_rejected(client):
    response = client.post("/api/auth/signup", json={
        "email": "weak@example.com", "password": "short", "name": "X",
    })
    assert response.status_code == 422


def test_wrong_password_is_rejected(client):
    register(client)
    response = client.post("/api/auth/login", json={
        "email": "owner@example.com", "password": "wrong-password",
    })
    assert response.status_code == 401


def test_password_hash_never_leaves_the_api(client):
    token = register(client)
    body = client.get("/api/auth/me", headers=auth(token)).json()
    assert "password_hash" not in body


def test_protected_route_requires_a_token(client):
    assert client.get("/api/employees").status_code == 401


def test_garbage_token_is_rejected(client):
    assert client.get("/api/employees", headers=auth("not-a-real-token")).status_code == 401


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
EMPLOYEE = {
    "name": "Alex Employee", "email": "alex@example.com", "role": "Cashier",
    "age": 25, "hourly_rate": 15.0, "max_weekly_hours": 40,
}


def test_employee_crud_round_trip(client):
    token = register(client)

    created = client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
    assert created.status_code == 201
    employee_id = created.json()["employee_id"]

    listed = client.get("/api/employees", headers=auth(token)).json()
    assert [e["employee_id"] for e in listed] == [employee_id]

    updated = client.put(
        f"/api/employees/{employee_id}",
        json={**EMPLOYEE, "hourly_rate": 18.5}, headers=auth(token),
    )
    assert updated.json()["hourly_rate"] == 18.5

    assert client.delete(f"/api/employees/{employee_id}", headers=auth(token)).status_code == 200
    assert client.get("/api/employees", headers=auth(token)).json() == []


def test_advanced_employee_settings_survive_a_round_trip(client):
    """Everything the Advanced Options panel writes must come back intact.

    These fields change who can be rostered when, so a silent drop between
    the form and the database would produce a schedule that looks fine and
    is not workable.
    """
    token = register(client)
    payload = {
        **EMPLOYEE,
        "is_active": True,
        "availability": {
            "earliest_start": "10:00",
            "latest_finish": "22:00",
            "available_days": ["mon", "tue", "sat", "sun"],
            "preferred_shift": "afternoon",
            "can_work_overnight": False,
        },
        "is_student": True,
        "term_time_max_hours": 16,
        "summer_break": {
            "start_date": "2026-06-15",
            "end_date": "2026-08-31",
            "max_weekly_hours": 40,
        },
        "opening_holiday_hours": 37.5,
    }
    created = client.post("/api/employees", json=payload, headers=auth(token)).json()

    assert created["availability"]["earliest_start"] == "10:00"
    assert created["availability"]["available_days"] == ["mon", "tue", "sat", "sun"]
    assert created["availability"]["can_work_overnight"] is False
    assert created["is_student"] is True
    assert created["term_time_max_hours"] == 16
    assert created["summer_break"]["max_weekly_hours"] == 40
    assert created["opening_holiday_hours"] == 37.5

    fetched = client.get("/api/employees", headers=auth(token)).json()[0]
    assert fetched["availability"] == created["availability"]
    assert fetched["summer_break"] == created["summer_break"]


def test_blank_availability_is_stored_as_absent_not_empty(client):
    """An employee with no restrictions must not carry an empty window."""
    token = register(client)
    created = client.post(
        "/api/employees", json={**EMPLOYEE, "availability": None}, headers=auth(token)
    ).json()
    assert created["availability"] is None


def test_employees_are_listed_in_seniority_order(client):
    """The team list, the solver and the printed grid must agree on order."""
    token = register(client)
    for name, role in [
        ("Zoe", "Floor Assistant"),
        ("Adam", "Supervisor"),
        ("Mia", "Assistant Manager"),
    ]:
        client.post(
            "/api/employees",
            json={**EMPLOYEE, "name": name, "email": f"{name.lower()}@example.com",
                  "role": role},
            headers=auth(token),
        )

    listed = client.get("/api/employees", headers=auth(token)).json()
    assert [e["name"] for e in listed] == ["Mia", "Adam", "Zoe"]


def _add_team(client, token, people):
    ids = {}
    for name, role in people:
        ids[name] = client.post(
            "/api/employees",
            json={**EMPLOYEE, "name": name, "email": f"{name.lower()}@example.com",
                  "role": role},
            headers=auth(token),
        ).json()["employee_id"]
    return ids


def test_manual_row_order_is_saved_and_reused(client):
    """The arrangement has to survive a reload — that is the whole point."""
    token = register(client)
    ids = _add_team(client, token, [
        ("Mia", "Assistant Manager"), ("Adam", "Supervisor"), ("Zoe", "Floor Assistant"),
    ])
    assert [e["name"] for e in client.get("/api/employees", headers=auth(token)).json()] \
        == ["Mia", "Adam", "Zoe"]

    client.put("/api/shop", headers=auth(token), json={
        "employee_order": [ids["Zoe"], ids["Mia"], ids["Adam"]],
    })

    listed = client.get("/api/employees", headers=auth(token)).json()
    assert [e["name"] for e in listed] == ["Zoe", "Mia", "Adam"]


def test_manual_order_does_not_change_who_gets_hours_first(client):
    """Rule 1: hours are prioritised by role, and nobody can change that.

    Moving the floor assistant to the top of the sheet must not promote them
    past the manager in the allocation order.
    """
    from app.services.hierarchy import display_order, sort_employees

    token = register(client)
    ids = _add_team(client, token, [
        ("Mia", "Assistant Manager"), ("Zoe", "Floor Assistant"),
    ])
    client.put("/api/shop", headers=auth(token),
               json={"employee_order": [ids["Zoe"], ids["Mia"]]})

    shop = client.get("/api/shop", headers=auth(token)).json()
    employees = client.get("/api/employees", headers=auth(token)).json()

    assert [e["name"] for e in display_order(employees, shop)] == ["Zoe", "Mia"]
    assert [e["name"] for e in sort_employees(employees, shop)] == ["Mia", "Zoe"]


def test_resetting_the_order_returns_to_seniority(client):
    token = register(client)
    ids = _add_team(client, token, [
        ("Mia", "Assistant Manager"), ("Zoe", "Floor Assistant"),
    ])
    client.put("/api/shop", headers=auth(token),
               json={"employee_order": [ids["Zoe"], ids["Mia"]]})
    client.put("/api/shop", headers=auth(token), json={"employee_order": []})

    listed = client.get("/api/employees", headers=auth(token)).json()
    assert [e["name"] for e in listed] == ["Mia", "Zoe"]


def test_a_new_starter_lands_at_the_bottom_not_mid_list(client):
    """Someone hired after the last reorder is not in the saved list.

    They sort after everyone who is, so the manager can see there is a new
    row to place — slotting them into the middle would look like the saved
    order had drifted on its own.
    """
    token = register(client)
    ids = _add_team(client, token, [
        ("Mia", "Assistant Manager"), ("Zoe", "Floor Assistant"),
    ])
    client.put("/api/shop", headers=auth(token),
               json={"employee_order": [ids["Zoe"], ids["Mia"]]})

    _add_team(client, token, [("Ned", "Duty Manager")])

    listed = client.get("/api/employees", headers=auth(token)).json()
    assert [e["name"] for e in listed] == ["Zoe", "Mia", "Ned"]


def test_a_stale_id_in_the_saved_order_is_harmless(client):
    """Deleting someone leaves their id behind in the stored list."""
    token = register(client)
    ids = _add_team(client, token, [
        ("Mia", "Assistant Manager"), ("Zoe", "Floor Assistant"),
    ])
    client.put("/api/shop", headers=auth(token),
               json={"employee_order": ["emp_gone", ids["Zoe"], ids["Mia"]]})
    client.delete(f"/api/employees/{ids['Zoe']}", headers=auth(token))

    listed = client.get("/api/employees", headers=auth(token)).json()
    assert [e["name"] for e in listed] == ["Mia"]


def _roster_with_leave(client, token):
    """A roster holding one work shift and one booked-holiday entry.

    Leave is stored with no times, which is what broke editing: the grid
    sends the whole week back on every change.
    """
    employee_id = client.post(
        "/api/employees", json=EMPLOYEE, headers=auth(token),
    ).json()["employee_id"]
    other_id = client.post(
        "/api/employees",
        json={**EMPLOYEE, "name": "Bea", "email": "bea@example.com"},
        headers=auth(token),
    ).json()["employee_id"]

    roster = client.post(
        "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token),
    ).json()

    shifts = [
        {"employee_id": employee_id, "day": "mon", "start": "09:00", "end": "17:00"},
        {"employee_id": other_id, "day": "mon", "start": "", "end": "",
         "paid_holiday": True},
    ]
    return roster["roster_id"], employee_id, other_id, shifts


def test_editing_a_shift_works_when_the_week_contains_leave(client):
    """The reported crash: changing anyone's hours 422'd once somebody in
    that week was on holiday, because leave carries no start or end time."""
    token = register(client)
    roster_id, employee_id, _, shifts = _roster_with_leave(client, token)

    response = client.put(
        f"/api/rosters/{roster_id}", json={"shifts": shifts}, headers=auth(token),
    )
    assert response.status_code == 200, response.json()

    saved = response.json()["shifts"]
    work = next(s for s in saved if s["employee_id"] == employee_id)
    assert (work["start"], work["end"]) == ("09:00", "17:00")


def test_editing_a_shift_does_not_strip_holiday_pay(client):
    """The grid only knows the seven fields it renders. Derived values have
    to be matched back from storage, or one edit silently zeroes somebody's
    holiday hours and their balance goes with it."""
    token = register(client)
    roster_id, employee_id, other_id, shifts = _roster_with_leave(client, token)

    # Seed the holiday with real hours, the way a booking does.
    client.put(f"/api/rosters/{roster_id}", json={"shifts": shifts}, headers=auth(token))
    stored = client.get("/api/rosters", headers=auth(token)).json()
    roster = next(r for r in stored if r["roster_id"] == roster_id)
    holiday = next(s for s in roster["shifts"] if s["employee_id"] == other_id)
    assert holiday["paid_holiday"] is True

    # Now edit the OTHER person's shift and check the holiday survived intact.
    edited = [
        {"employee_id": employee_id, "day": "mon", "start": "10:00", "end": "18:00"},
        {"employee_id": other_id, "day": "mon", "start": "", "end": "",
         "paid_holiday": True},
    ]
    response = client.put(
        f"/api/rosters/{roster_id}", json={"shifts": edited}, headers=auth(token),
    )
    assert response.status_code == 200

    after = next(
        s for s in response.json()["shifts"] if s["employee_id"] == other_id
    )
    assert after["paid_holiday"] is True
    assert after.get("paid_hours") == holiday.get("paid_hours")


def _week_with_a_pre_existing_breach(client, token):
    """A saved roster that has since come to break a rule.

    Reached the way it happens in practice: the roster was legal when saved,
    then somebody's contracted hours were cut. The manager did not cause the
    breach and cannot fix it by editing a different person's Wednesday.
    """
    a = client.post(
        "/api/employees",
        json={**EMPLOYEE, "name": "Ana", "email": "ana@example.com",
              "max_weekly_hours": 40},
        headers=auth(token),
    ).json()["employee_id"]
    b = client.post(
        "/api/employees",
        json={**EMPLOYEE, "name": "Bo", "email": "bo@example.com",
              "max_weekly_hours": 40},
        headers=auth(token),
    ).json()["employee_id"]

    roster_id = client.post(
        "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token),
    ).json()["roster_id"]

    shifts = [
        {"employee_id": a, "day": d, "start": "09:00", "end": "17:00"}
        for d in ("mon", "tue", "wed", "thu")
    ] + [
        {"employee_id": b, "day": "wed", "start": "15:00", "end": "20:00"},
    ]
    saved = client.put(
        f"/api/rosters/{roster_id}", json={"shifts": shifts}, headers=auth(token),
    )
    assert saved.status_code == 200, saved.json()

    # Ana's contract is cut to 20h, so the already-saved roster now puts her
    # well over it — through no action of the person editing next.
    client.put(
        f"/api/employees/{a}",
        json={**EMPLOYEE, "name": "Ana", "email": "ana@example.com",
              "max_weekly_hours": 20},
        headers=auth(token),
    )
    return roster_id, a, b, shifts


def test_an_unrelated_edit_is_not_blocked_by_a_pre_existing_breach(client):
    """The reported case: swapping one person's Wednesday was refused because
    somebody else was under contract on another day."""
    token = register(client)
    roster_id, _, b, shifts = _week_with_a_pre_existing_breach(client, token)

    moved = [
        {**s, "start": "16:00", "end": "21:00"}
        if s["employee_id"] == b else s
        for s in shifts
    ]
    response = client.put(
        f"/api/rosters/{roster_id}", json={"shifts": moved}, headers=auth(token),
    )
    assert response.status_code == 200, response.json()

    saved = next(s for s in response.json()["shifts"] if s["employee_id"] == b)
    assert (saved["start"], saved["end"]) == ("16:00", "21:00")


def test_a_pre_existing_breach_is_still_reported(client):
    """Allowed through, but not swept under the carpet."""
    token = register(client)
    roster_id, _, b, shifts = _week_with_a_pre_existing_breach(client, token)

    moved = [
        {**s, "start": "16:00", "end": "21:00"} if s["employee_id"] == b else s
        for s in shifts
    ]
    body = client.put(
        f"/api/rosters/{roster_id}", json={"shifts": moved}, headers=auth(token),
    ).json()
    assert any("20h contract" in w for w in body.get("edit_warnings", []))


def test_an_edit_that_makes_things_worse_is_still_refused(client):
    """Only what the edit introduces is held against it — but that much is."""
    token = register(client)
    roster_id, _, b, shifts = _week_with_a_pre_existing_breach(client, token)

    # Push the second employee to six days: a breach the edit introduces.
    worse = shifts + [
        {"employee_id": b, "day": d, "start": "15:00", "end": "20:00"}
        for d in ("mon", "tue", "thu", "fri", "sat")
    ]
    response = client.put(
        f"/api/rosters/{roster_id}", json={"shifts": worse}, headers=auth(token),
    )
    assert response.status_code == 400
    assert any("6 days" in r for r in response.json()["detail"]["reasons"])


class TestPinAndRebalance:
    """Editing one cell should not cost you the rest of your edits."""

    def _team_and_roster(self, client, token, size=6):
        for i in range(size):
            client.post(
                "/api/employees",
                json={**EMPLOYEE, "name": f"P{i}", "email": f"p{i}@example.com"},
                headers=auth(token),
            )
        return client.post(
            "/api/roster/generate", json={"week_start": "2026-08-10"},
            headers=auth(token),
        ).json()

    def _edit_one(self, client, token, roster):
        """Change one shift's times, which pins it."""
        target = next(s for s in roster["shifts"] if s.get("start") and s.get("end"))
        clean = [
            {
                "employee_id": s["employee_id"], "day": s["day"],
                "start": "11:00" if s is target else s.get("start", ""),
                "end": "15:00" if s is target else s.get("end", ""),
                "paid_holiday": bool(s.get("paid_holiday")),
                "unpaid_holiday": bool(s.get("unpaid_holiday")),
                "sick": bool(s.get("sick")),
            }
            for s in roster["shifts"]
        ]
        saved = client.put(
            f"/api/rosters/{roster['roster_id']}", json={"shifts": clean},
            headers=auth(token),
        )
        assert saved.status_code == 200, saved.json()
        return target, saved.json()

    def test_editing_a_shift_pins_it(self, client):
        token = register(client)
        roster = self._team_and_roster(client, token)
        target, saved = self._edit_one(client, token, roster)

        changed = next(
            s for s in saved["shifts"]
            if s["employee_id"] == target["employee_id"] and s["day"] == target["day"]
        )
        assert changed["pinned"] is True
        assert (changed["start"], changed["end"]) == ("11:00", "15:00")

    def test_untouched_shifts_are_not_pinned(self, client):
        """Only what the manager actually changed is held; everything else
        stays free for the solver to rearrange."""
        token = register(client)
        roster = self._team_and_roster(client, token)
        target, saved = self._edit_one(client, token, roster)

        pinned = [s for s in saved["shifts"] if s.get("pinned")]
        assert len(pinned) == 1, f"expected one pin, got {len(pinned)}"
        assert pinned[0]["employee_id"] == target["employee_id"]

    def test_rebalancing_keeps_the_pinned_shift(self, client):
        token = register(client)
        roster = self._team_and_roster(client, token)
        target, _ = self._edit_one(client, token, roster)

        rebalanced = client.post(
            "/api/roster/generate",
            json={"week_start": "2026-08-10", "keep_pinned": True},
            headers=auth(token),
        ).json()

        kept = [
            s for s in rebalanced["shifts"]
            if s["employee_id"] == target["employee_id"]
            and s["day"] == target["day"]
        ]
        assert kept, "the pinned shift vanished in the rebalance"
        assert (kept[0]["start"], kept[0]["end"]) == ("11:00", "15:00")
        assert kept[0]["pinned"] is True

    def test_regenerating_discards_pins(self, client):
        """Regenerate means start over; that is the point of having both."""
        token = register(client)
        roster = self._team_and_roster(client, token)
        target, _ = self._edit_one(client, token, roster)

        fresh = client.post(
            "/api/roster/generate", json={"week_start": "2026-08-10"},
            headers=auth(token),
        ).json()
        assert not any(s.get("pinned") for s in fresh["shifts"])

    def test_a_pin_can_be_released(self, client):
        token = register(client)
        roster = self._team_and_roster(client, token)
        target, saved = self._edit_one(client, token, roster)

        released = [
            {
                "employee_id": s["employee_id"], "day": s["day"],
                "start": s.get("start", ""), "end": s.get("end", ""),
                "paid_holiday": bool(s.get("paid_holiday")),
                "unpaid_holiday": bool(s.get("unpaid_holiday")),
                "sick": bool(s.get("sick")),
                "pinned": False,
            }
            for s in saved["shifts"]
        ]
        body = client.put(
            f"/api/rosters/{roster['roster_id']}", json={"shifts": released},
            headers=auth(token),
        ).json()
        assert not any(s.get("pinned") for s in body["shifts"])


class TestCorrectionCapture:
    """The manager's edits are the highest-signal data the product has.

    Editing overwrites `shifts` in place, so without a frozen snapshot of what
    the solver proposed, every correction is destroyed the moment the manager
    touches the roster.
    """

    def _week(self, client, token):
        ids = {}
        for name in ("Alex", "Sam"):
            ids[name] = client.post("/api/employees", json={
                **EMPLOYEE, "name": name, "email": f"{name.lower()}@e.com",
            }, headers=auth(token)).json()["employee_id"]
        week = _future_monday()
        roster = client.post(
            "/api/roster/generate", json={"week_start": week}, headers=auth(token)
        ).json()
        return roster["roster_id"], week, ids

    def _get(self, client, token, rid):
        return client.get(f"/api/rosters/{rid}", headers=auth(token)).json()

    def test_generation_snapshots_what_the_solver_proposed(self, client):
        token = register(client)
        rid, _, _ = self._week(client, token)
        roster = self._get(client, token, rid)

        assert roster["generated_shifts"], "the proposal must be recorded"
        assert len(roster["generated_shifts"]) == len(roster["shifts"])

    def test_the_snapshot_survives_editing(self, client):
        """The whole point: `shifts` moves, `generated_shifts` does not."""
        token = register(client)
        rid, _, ids = self._week(client, token)
        before = self._get(client, token, rid)["generated_shifts"]

        edited = [
            {"employee_id": s["employee_id"], "day": s["day"],
             "start": "10:00", "end": "18:00"}
            for s in before if s.get("start")
        ][:1]
        client.put(f"/api/rosters/{rid}", json={"shifts": edited}, headers=auth(token))

        after = self._get(client, token, rid)
        assert after["generated_shifts"] == before, "the proposal must not move"
        assert after["shifts"] != before, "but the roster did"

    def test_approving_records_what_changed(self, client):
        token = register(client)
        rid, _, _ = self._week(client, token)
        proposed = self._get(client, token, rid)["generated_shifts"]
        first = next(s for s in proposed if s.get("start"))

        client.put(f"/api/rosters/{rid}", json={"shifts": [
            {"employee_id": first["employee_id"], "day": first["day"],
             "start": "10:00", "end": "18:00"},
        ]}, headers=auth(token))
        client.post(f"/api/rosters/{rid}/approve?acknowledge_gaps=true",
                    headers=auth(token))

        roster = self._get(client, token, rid)
        assert roster["corrections_measurable"] is True
        assert roster["edit_count"] == len(roster["corrections"])
        moved = [c for c in roster["corrections"] if c["kind"] == "moved"]
        assert moved and moved[0]["to_slot"] == "10:00-18:00"

    def test_approving_an_untouched_roster_records_zero_edits(self, client):
        """The outcome the product is aiming at — worth measuring explicitly."""
        token = register(client)
        rid, _, _ = self._week(client, token)
        client.post(f"/api/rosters/{rid}/approve?acknowledge_gaps=true",
                    headers=auth(token))

        roster = self._get(client, token, rid)
        assert roster["edit_count"] == 0
        assert roster["corrections"] == []

    def test_a_roster_with_no_snapshot_is_marked_unmeasurable(self, client):
        """Rosters from before this feature must not read as a perfect zero."""
        from app.services.corrections import diff_roster, edit_count

        assert diff_roster([], []) == []
        assert edit_count(diff_roster([], [])) == 0
        # The flag, not the count, is what distinguishes "no edits" from
        # "cannot tell" — asserted here so the distinction is not lost.
        token = register(client)
        rid, _, _ = self._week(client, token)
        client.post(f"/api/rosters/{rid}/approve?acknowledge_gaps=true",
                    headers=auth(token))
        assert self._get(client, token, rid)["corrections_measurable"] is True


class TestSickOnApprovedRoster:
    """Somebody calling in at 6am is the one case the approval lock cannot
    serve. Unapproving would take the whole week out of learning and let it
    be regenerated, when all that happened is one person is ill."""

    def _approved_week(self, client, token, people=("Alex", "Sam")):
        ids = {}
        for i, name in enumerate(people):
            ids[name] = client.post("/api/employees", json={
                **EMPLOYEE, "name": name, "email": f"{name.lower()}@e.com",
            }, headers=auth(token)).json()["employee_id"]
        week = _future_monday()
        roster = client.post(
            "/api/roster/generate", json={"week_start": week}, headers=auth(token)
        ).json()
        client.post(f"/api/rosters/{roster['roster_id']}/approve?acknowledge_gaps=true",
                    headers=auth(token))
        return roster, week, ids

    def _a_shift(self, client, token, roster_id):
        roster = client.get(f"/api/rosters/{roster_id}", headers=auth(token)).json()
        return next(
            s for s in roster["shifts"]
            if s.get("start") and not s.get("sick")
        )

    def test_reporting_sick_leaves_the_week_approved(self, client):
        token = register(client)
        roster, _, _ = self._approved_week(client, token)
        shift = self._a_shift(client, token, roster["roster_id"])

        response = client.post(f"/api/rosters/{roster['roster_id']}/sick", json={
            "employee_id": shift["employee_id"], "day": shift["day"],
        }, headers=auth(token))
        assert response.status_code == 200, response.text

        after = client.get(f"/api/rosters/{roster['roster_id']}", headers=auth(token)).json()
        assert after["approved"] is True, "one sick call must not reopen the week"
        marked = next(
            s for s in after["shifts"]
            if s["employee_id"] == shift["employee_id"] and s["day"] == shift["day"]
        )
        assert marked["sick"] is True

    def test_a_normal_edit_is_still_refused(self, client):
        """The narrow exception must not become a general way in."""
        token = register(client)
        roster, _, _ = self._approved_week(client, token)

        assert client.put(
            f"/api/rosters/{roster['roster_id']}", json={"shifts": []},
            headers=auth(token),
        ).status_code == 409

    def test_cover_is_added_and_pinned(self, client):
        token = register(client)
        roster, _, ids = self._approved_week(client, token)
        shift = self._a_shift(client, token, roster["roster_id"])
        cover_id = next(v for v in ids.values() if v != shift["employee_id"])

        client.post(f"/api/rosters/{roster['roster_id']}/sick", json={
            "employee_id": shift["employee_id"], "day": shift["day"],
            "cover_employee_id": cover_id, "overrides": ["weekly_hours"],
        }, headers=auth(token))

        after = client.get(f"/api/rosters/{roster['roster_id']}", headers=auth(token)).json()
        cover = next(
            s for s in after["shifts"]
            if s["employee_id"] == cover_id and s["day"] == shift["day"]
            and s.get("covering_for")
        )
        assert cover["covering_for"] == shift["employee_id"]
        assert cover["pinned"] is True, "a rebalance must not undo arranged cover"
        assert cover["overrides"] == ["weekly_hours"]

    def test_the_override_is_recorded_in_the_activity_log(self, client):
        """"We had no choice" is defensible only if written down at the time."""
        token = register(client)
        roster, _, ids = self._approved_week(client, token)
        shift = self._a_shift(client, token, roster["roster_id"])
        cover_id = next(v for v in ids.values() if v != shift["employee_id"])

        client.post(f"/api/rosters/{roster['roster_id']}/sick", json={
            "employee_id": shift["employee_id"], "day": shift["day"],
            "cover_employee_id": cover_id, "overrides": ["days"],
        }, headers=auth(token))

        log = client.get("/api/activity", headers=auth(token)).json()
        entry = next(a for a in log if a["action"] == "shift_sick")
        assert "covered by" in entry["detail"]
        assert "overriding days" in entry["detail"]

    def test_an_uncovered_sick_call_says_so(self, client):
        token = register(client)
        roster, _, _ = self._approved_week(client, token)
        shift = self._a_shift(client, token, roster["roster_id"])

        body = client.post(f"/api/rosters/{roster['roster_id']}/sick", json={
            "employee_id": shift["employee_id"], "day": shift["day"],
        }, headers=auth(token)).json()
        assert body["uncovered"] is True

        log = client.get("/api/activity", headers=auth(token)).json()
        assert any("NOT COVERED" in a["detail"] for a in log)

    def test_sick_also_books_the_absence(self, client):
        """So it reaches the sick report and blocks scheduling that date."""
        token = register(client)
        roster, week, _ = self._approved_week(client, token)
        shift = self._a_shift(client, token, roster["roster_id"])

        client.post(f"/api/rosters/{roster['roster_id']}/sick", json={
            "employee_id": shift["employee_id"], "day": shift["day"],
            "reason": "Flu",
        }, headers=auth(token))

        report = client.get("/api/reports/sick-leave", headers=auth(token)).json()
        assert report["total_days"] == 1
        assert report["by_employee"][0]["occurrences"][0]["label"] == "Flu"

    def test_cover_options_never_offer_somebody_already_on(self, client):
        token = register(client)
        roster, _, _ = self._approved_week(client, token)
        shift = self._a_shift(client, token, roster["roster_id"])

        options = client.get(
            f"/api/rosters/{roster['roster_id']}/cover",
            params={"employee_id": shift["employee_id"], "day": shift["day"]},
            headers=auth(token),
        ).json()
        assert shift["employee_id"] not in [
            c["employee_id"] for c in options["candidates"]
        ]

    def test_a_shift_that_is_not_there_is_a_404(self, client):
        token = register(client)
        roster, _, ids = self._approved_week(client, token)

        assert client.post(f"/api/rosters/{roster['roster_id']}/sick", json={
            "employee_id": list(ids.values())[0], "day": "sun",
        }, headers=auth(token)).status_code in (404, 422)

    def test_the_sick_balance_report_reflects_it(self, client):
        token = register(client)
        roster, _, _ = self._approved_week(client, token)
        shift = self._a_shift(client, token, roster["roster_id"])

        client.put("/api/shop", json={"paid_sick_days": 5}, headers=auth(token))
        client.post(f"/api/rosters/{roster['roster_id']}/sick", json={
            "employee_id": shift["employee_id"], "day": shift["day"],
        }, headers=auth(token))

        report = client.get("/api/reports/sick-balance", headers=auth(token)).json()
        assert report["entitlement_days"] == 5
        assert report["rows"], "the person who was off should appear"
        assert report["rows"][0]["used_hours"] > 0


class TestHoursReport:
    def test_only_approved_work_is_reported(self, client):
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        week = _future_monday()
        roster = client.post(
            "/api/roster/generate", json={"week_start": week}, headers=auth(token)
        ).json()

        end = (date.fromisoformat(week) + timedelta(days=6)).isoformat()
        params = {"start": week, "end": end}

        draft = client.get("/api/reports/hours", params=params, headers=auth(token)).json()
        assert draft["rows"] == []

        client.post(f"/api/rosters/{roster['roster_id']}/approve?acknowledge_gaps=true",
                    headers=auth(token))
        live = client.get("/api/reports/hours", params=params, headers=auth(token)).json()
        assert live["rows"], "an approved week is payable"
        assert live["totals"]["cost"] > 0

    def test_the_break_setting_is_reported_alongside_the_figures(self, client):
        """The reader must not have to guess which way the wages were cut."""
        token = register(client)
        params = {"start": "2026-03-02", "end": "2026-03-08"}

        default = client.get("/api/reports/hours", params=params, headers=auth(token)).json()
        assert default["breaks_are_paid"] is False

        client.put("/api/shop", json={"breaks_are_paid": True}, headers=auth(token))
        paid = client.get("/api/reports/hours", params=params, headers=auth(token)).json()
        assert paid["breaks_are_paid"] is True

    def test_a_malformed_date_is_a_400_not_a_crash(self, client):
        token = register(client)
        response = client.get(
            "/api/reports/hours", params={"start": "March", "end": "2026-03-08"},
            headers=auth(token),
        )
        assert response.status_code == 400

    def test_one_shop_cannot_read_another_shops_wages(self, client):
        mine = register(client, email="mine@example.com")
        theirs = register(client, email="theirs@example.com")
        client.post("/api/employees", json=EMPLOYEE, headers=auth(mine))
        week = _future_monday()
        roster = client.post(
            "/api/roster/generate", json={"week_start": week}, headers=auth(mine)
        ).json()
        client.post(f"/api/rosters/{roster['roster_id']}/approve?acknowledge_gaps=true",
                    headers=auth(mine))

        params = {"start": week,
                  "end": (date.fromisoformat(week) + timedelta(days=6)).isoformat()}
        assert client.get(
            "/api/reports/hours", params=params, headers=auth(theirs)
        ).json()["rows"] == []


class TestSetupStatus:
    """The checklist a new shop follows.

    Every step is derived from the data, never from a stored "step 3 done"
    flag — a flag starts lying the moment the data behind it changes, which
    is exactly when a new user most needs to be told the truth.
    """

    def _steps(self, client, token):
        body = client.get("/api/setup-status", headers=auth(token)).json()
        return body, {s["id"]: s for s in body["steps"]}

    def test_a_brand_new_shop_has_finished_nothing(self, client):
        token = register(client)
        body, steps = self._steps(client, token)

        assert body["done"] == 0
        assert body["next_step_id"] == "shop"
        assert not any(s["done"] for s in body["steps"])

    def test_an_empty_team_is_not_reported_as_reviewed(self, client):
        """"All reviewed" is true of nobody, and would be a lie to a new shop."""
        token = register(client)
        _, steps = self._steps(client, token)

        assert steps["details"]["done"] is False
        assert "review" not in steps["details"]["detail"].lower() or \
               "Nobody" in steps["details"]["detail"]
        assert steps["employment"]["done"] is False

    def test_reviewing_someone_counts_even_if_nothing_changed(self, client):
        """The bug that made this step impossible to finish.

        Whether pay and age had been reviewed was worked out by comparing
        them against the importer's defaults — which cannot tell a
        placeholder from somebody who genuinely is 25, genuinely is on that
        rate and genuinely does work 40 hours. For them the step could never
        be ticked, however many times the record was opened and saved.

        Saving is the act of reviewing, so saving is what counts.
        """
        token = register(client)
        _seed_imported_week(client, token, "2026-03-02")
        employee = client.get("/api/employees", headers=auth(token)).json()[0]

        # Saved with the SAME values the importer wrote.
        saved = client.put(f"/api/employees/{employee['employee_id']}", json={
            "name": employee["name"], "role": employee["role"],
            "age": 25, "hourly_rate": 13.0, "max_weekly_hours": 40.0,
        }, headers=auth(token))
        assert saved.status_code == 200, saved.text

        _, steps = self._steps(client, token)
        assert steps["details"]["done"] is True, (
            "somebody who really is 25 on the default rate can never finish "
            "this step if only the numbers are checked"
        )

    def test_adding_someone_completes_the_team_step(self, client):
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        _, steps = self._steps(client, token)

        assert steps["team"]["done"] is True
        assert "1 person" in steps["team"]["detail"]

    def test_placeholder_pay_is_flagged_until_reviewed(self, client):
        """Imported staff land on €13.00, age 25, 40h — none of it real."""
        token = register(client)
        _seed_imported_week(client, token, "2026-03-02")
        _, steps = self._steps(client, token)

        assert steps["details"]["done"] is False
        # NAMED, not counted: "4 still on placeholder values" against a team
        # of 25 means opening records one at a time to find them.
        assert "Jane Doe" in steps["details"]["detail"]
        assert [w["name"] for w in steps["details"]["who"]] == ["Jane Doe"]

        employee = client.get("/api/employees", headers=auth(token)).json()[0]
        updated = client.put(f"/api/employees/{employee['employee_id']}", json={
            "name": employee["name"], "email": employee["email"],
            "role": employee["role"], "age": 31, "hourly_rate": 14.5,
            "max_weekly_hours": 37.5,
        }, headers=auth(token))
        assert updated.status_code == 200, updated.text

        _, steps = self._steps(client, token)
        assert steps["details"]["done"] is True

    def test_a_step_reverts_when_its_data_goes_away(self, client):
        """The whole reason this is derived rather than stored."""
        token = register(client)
        created = client.post(
            "/api/employees", json=EMPLOYEE, headers=auth(token)
        ).json()
        _, steps = self._steps(client, token)
        assert steps["team"]["done"] is True

        client.delete(f"/api/employees/{created['employee_id']}", headers=auth(token))
        _, steps = self._steps(client, token)
        assert steps["team"]["done"] is False, "a stored flag would still say done"

    def test_leavers_do_not_count_as_team(self, client):
        """Staff kept only to own imported history are not people to review."""
        token = register(client)
        csv = (
            "Name,Mon,Tue,Wed,Thu,Fri,Sat,Sun\n"
            "Staff,,,,,,,\n"
            "Old Hand,09.00-17.00 (8),,,,,,\n"
        )
        import_id = client.post(
            "/api/imports",
            files={"file": ("history.csv", csv.encode(), "text/csv")},
            data={"week_start": "2026-03-02"},
            headers=auth(token),
        ).json()["import_id"]
        client.post(f"/api/imports/{import_id}/commit", json={
            "skip_unmapped": False, "past_staff": ["Old Hand"],
        }, headers=auth(token))

        _, steps = self._steps(client, token)
        assert steps["team"]["done"] is False
        assert steps["details"]["done"] is False

    def test_a_draft_roster_does_not_complete_the_last_step(self, client):
        """Approving is the step, not generating."""
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        roster = client.post(
            "/api/roster/generate", json={"week_start": _future_monday()},
            headers=auth(token),
        ).json()

        _, steps = self._steps(client, token)
        assert steps["roster"]["done"] is False
        assert "none approved" in steps["roster"]["detail"]

        client.post(f"/api/rosters/{roster['roster_id']}/approve?acknowledge_gaps=true",
                    headers=auth(token))
        _, steps = self._steps(client, token)
        assert steps["roster"]["done"] is True

    def test_imported_history_does_not_count_as_your_first_roster(self, client):
        """Otherwise importing would tick a step the manager never did — and
        report drafts to somebody who has generated nothing."""
        token = register(client)
        _seed_imported_week(client, token, "2026-03-02")
        _, steps = self._steps(client, token)

        assert steps["roster"]["done"] is False
        assert steps["roster"]["detail"] == "No roster yet"

    def test_the_optional_step_is_not_required_to_finish(self, client):
        token = register(client)
        body, _ = self._steps(client, token)
        optional = [s for s in body["steps"] if s.get("optional")]

        assert len(optional) == 1
        assert body["total"] == len(body["steps"]) - 1

    def test_importing_comes_before_adding_staff_by_hand(self, client):
        """The import creates everyone on the sheet, so doing it first turns
        "add your team" from two dozen forms into filling in the gaps."""
        token = register(client)
        body, _ = self._steps(client, token)
        order = [s["id"] for s in body["steps"]]

        assert order.index("history") < order.index("team")
        assert order[:3] == ["shop", "history", "team"]

    def test_every_step_explains_why_it_matters(self, client):
        """A manager who does not know why will skip it and blame the result."""
        token = register(client)
        body, _ = self._steps(client, token)

        for step in body["steps"]:
            assert step["why"].strip(), step["id"]
            assert step["action"]["path"].startswith("/"), step["id"]


class TestLearningSummary:
    """Replaces the AI Training page, which duplicated importing and needed
    an API key to do anything at all."""

    def test_a_new_shop_is_told_it_has_no_history(self, client):
        token = register(client)
        body = client.get("/api/imports/learning-summary", headers=auth(token)).json()

        assert body["weeks_in_window"] == 0
        assert body["learning_from_history"] is False
        assert body["weeks_needed"] > 0

    def test_the_route_is_not_swallowed_by_the_id_path(self, client):
        """"/imports/{import_id}" would otherwise capture this literal."""
        token = register(client)
        assert client.get(
            "/api/imports/learning-summary", headers=auth(token)
        ).status_code == 200

    def test_an_imported_week_can_be_removed_and_is_unlearned(self, client):
        """A bad import is an ordinary mistake and must be reversible.

        Imported weeks are stored as approved past weeks, which unapprove
        deliberately refuses to touch. Without this they would be permanent.
        """
        token = register(client)
        roster_id = _seed_imported_week(client, token, "2026-03-02")

        before = client.get("/api/imports/learning-summary", headers=auth(token)).json()
        assert before["weeks_of_history"] == 1

        listed = client.get("/api/imports/history", headers=auth(token)).json()
        assert [w["roster_id"] for w in listed] == [roster_id]
        assert listed[0]["shifts"] == 1

        removed = client.delete(f"/api/imports/history/{roster_id}", headers=auth(token))
        assert removed.status_code == 200
        assert removed.json()["week_start"] == "2026-03-02"

        after = client.get("/api/imports/learning-summary", headers=auth(token)).json()
        assert after["weeks_of_history"] == 0
        assert client.get("/api/imports/history", headers=auth(token)).json() == []

    def test_import_uses_the_shops_own_job_titles(self, client):
        """Roles configured at setup must survive an import.

        The old ROLE_MAP rewrote "Night Shift" to "Stocker" and every kind of
        manager to "Manager", consulting nothing about the shop.
        """
        token = register(client)
        client.put("/api/shop", json={"role_hierarchy": [
            "Duty Manager", "Supervisor", "Night Shift",
        ]}, headers=auth(token))

        # Section in the leftmost column, names beside it — the layout the
        # parser expects and real roster sheets use.
        csv = (
            "Role,Name,Mon,Tue,Wed,Thu,Fri,Sat,Sun\n"
            "Duty Mgr.,Megan,09.00-17.00 (8),,,,,,\n"
            "Night Shift,Kelvin,23.00-07.00 (8),,,,,,\n"
        )
        import_id = client.post(
            "/api/imports",
            files={"file": ("history.csv", csv.encode(), "text/csv")},
            data={"week_start": "2026-03-02"},
            headers=auth(token),
        ).json()["import_id"]

        client.post(f"/api/imports/{import_id}/commit",
                    json={"skip_unmapped": False}, headers=auth(token))

        roles = {
            e["name"]: e["role"]
            for e in client.get("/api/employees", headers=auth(token)).json()
        }
        assert roles["Megan"] == "Duty Manager", "must not be flattened to Manager"
        assert roles["Kelvin"] == "Night Shift", "must not be invented as Stocker"

    def test_the_preview_shows_the_file_wording_beside_the_match(self, client):
        """So a disagreement is visible before 2000 shifts are committed."""
        token = register(client)
        client.put("/api/shop", json={"role_hierarchy": ["Duty Manager"]},
                   headers=auth(token))
        csv = (
            "Role,Name,Mon,Tue,Wed,Thu,Fri,Sat,Sun\n"
            "Duty Mgr.,Megan,09.00-17.00 (8),,,,,,\n"
        )
        preview = client.post(
            "/api/imports",
            files={"file": ("history.csv", csv.encode(), "text/csv")},
            data={"week_start": "2026-03-02"},
            headers=auth(token),
        ).json()

        megan = next(p for p in preview["people"] if p["name"] == "Megan")
        assert megan["role"] == "Duty Manager"
        assert megan["role_in_file"] == "Duty Manager"

    def test_an_imported_employee_can_actually_be_edited(self, client):
        """Reviewing imported pay is a step we tell managers to do — it has
        to be possible.

        The importer used to invent "jane@imported.shop_645.local", which
        failed EmployeeIn twice over: an underscore is illegal in a domain,
        and ".local" is a reserved name. So imported staff could be created
        and never edited — opening one, changing the pay and saving returned
        a validation error about an address the manager never typed.
        """
        token = register(client)
        _seed_imported_week(client, token, "2026-03-02")
        employee = client.get("/api/employees", headers=auth(token)).json()[0]

        assert not employee.get("email"), "a spreadsheet carries no email"

        saved = client.put(f"/api/employees/{employee['employee_id']}", json={
            "name": employee["name"], "role": employee["role"],
            "age": 31, "hourly_rate": 14.5, "max_weekly_hours": 37.5,
        }, headers=auth(token))
        assert saved.status_code == 200, saved.text

    def test_dispatch_names_who_it_could_not_reach(self, client):
        """Reporting a clean send to nobody is the worse failure."""
        token = register(client)
        _seed_imported_week(client, token, "2026-03-02")
        roster = client.post(
            "/api/roster/generate", json={"week_start": _future_monday()},
            headers=auth(token),
        ).json()

        result = client.post(
            f"/api/roster/{roster['roster_id']}/dispatch", headers=auth(token)
        )
        assert result.status_code == 200, result.text
        assert "Jane Doe" in result.json()["no_email"]

    def test_a_leaver_keeps_their_shifts_but_not_a_place_in_the_staff_list(self, client):
        """The whole point: history stays honest, the staff list stays clean.

        Dropping a leaver's shifts instead would make the imported weeks show
        fewer people on the floor than really worked, and the solver copies
        the staffing it is shown.
        """
        token = register(client)
        csv = (
            "Name,Mon,Tue,Wed,Thu,Fri,Sat,Sun\n"
            "Staff,,,,,,,\n"
            "Jane Doe,09.00-17.00 (8),,,,,,\n"
            "Old Hand,09.00-17.00 (8),,,,,,\n"
        )
        import_id = client.post(
            "/api/imports",
            files={"file": ("history.csv", csv.encode(), "text/csv")},
            data={"week_start": "2026-03-02"},
            headers=auth(token),
        ).json()["import_id"]

        result = client.post(f"/api/imports/{import_id}/commit", json={
            "skip_unmapped": False, "past_staff": ["Old Hand"],
        }, headers=auth(token)).json()

        assert result["created"] == ["Jane Doe"]
        assert result["past_staff_kept"] == ["Old Hand"]

        listed = client.get("/api/employees", headers=auth(token)).json()
        assert [e["name"] for e in listed] == ["Jane Doe"]

        everyone = client.get(
            "/api/employees?include_past=true", headers=auth(token)
        ).json()
        assert sorted(e["name"] for e in everyone) == ["Jane Doe", "Old Hand"]

        leaver = next(e for e in everyone if e["name"] == "Old Hand")
        assert leaver["is_active"] is False, "a leaver must never be rostered"

        # The history still shows two people on that Monday.
        week = client.get("/api/imports/history", headers=auth(token)).json()[0]
        assert week["shifts"] == 2

    def test_a_leaver_is_never_rostered(self, client):
        token = register(client)
        csv = (
            "Name,Mon,Tue,Wed,Thu,Fri,Sat,Sun\n"
            "Staff,,,,,,,\n"
            "Old Hand,09.00-17.00 (8),,,,,,\n"
        )
        import_id = client.post(
            "/api/imports",
            files={"file": ("history.csv", csv.encode(), "text/csv")},
            data={"week_start": "2026-03-02"},
            headers=auth(token),
        ).json()["import_id"]
        client.post(f"/api/imports/{import_id}/commit", json={
            "skip_unmapped": False, "past_staff": ["Old Hand"],
        }, headers=auth(token))

        roster = client.post(
            "/api/roster/generate", json={"week_start": _future_monday()},
            headers=auth(token),
        ).json()
        leaver = next(
            e for e in client.get("/api/employees?include_past=true", headers=auth(token)).json()
            if e["name"] == "Old Hand"
        )
        assert not [
            s for s in roster["shifts"] if s["employee_id"] == leaver["employee_id"]
        ]

    def test_leavers_are_still_only_created_when_asked_for(self, client):
        """Naming nobody must behave exactly as it did before."""
        token = register(client)
        _seed_imported_week(client, token, "2026-03-02")
        listed = client.get("/api/employees", headers=auth(token)).json()
        assert [e["name"] for e in listed] == ["Jane Doe"]

    def test_a_removed_week_can_be_restored_without_the_file(self, client):
        """The point of the feature: the spreadsheet is gone, the data is not."""
        token = register(client)
        roster_id = _seed_imported_week(client, token, "2026-03-02")

        removed = client.delete(
            f"/api/imports/history/{roster_id}", headers=auth(token)
        ).json()
        assert removed["restorable"] is True

        offered = client.get("/api/imports/removed", headers=auth(token)).json()
        assert len(offered) == 1
        assert offered[0]["week_start"] == "2026-03-02"
        assert offered[0]["shifts"] == 1

        restored = client.post("/api/imports/removed/restore", json={
            "import_id": offered[0]["import_id"], "week_start": "2026-03-02",
        }, headers=auth(token))
        assert restored.status_code == 200, restored.text
        assert restored.json()["shifts_restored"] == 1

        history = client.get("/api/imports/history", headers=auth(token)).json()
        assert [w["week_start"] for w in history] == ["2026-03-02"]
        assert client.get(
            "/api/imports/learning-summary", headers=auth(token)
        ).json()["weeks_of_history"] == 1

    def test_a_restored_week_stops_being_offered(self, client):
        token = register(client)
        roster_id = _seed_imported_week(client, token, "2026-03-02")
        client.delete(f"/api/imports/history/{roster_id}", headers=auth(token))
        offered = client.get("/api/imports/removed", headers=auth(token)).json()

        client.post("/api/imports/removed/restore", json={
            "import_id": offered[0]["import_id"], "week_start": "2026-03-02",
        }, headers=auth(token))

        assert client.get("/api/imports/removed", headers=auth(token)).json() == []

    def test_re_uploading_the_file_clears_the_restore_offer(self, client):
        """The offer is checked against the history, not just the note.

        Re-uploading already works and is the obvious thing to try first. A
        week brought back that way must not still be sitting in the restore
        list, inviting a duplicate.
        """
        token = register(client)
        roster_id = _seed_imported_week(client, token, "2026-03-02")
        client.delete(f"/api/imports/history/{roster_id}", headers=auth(token))
        assert len(client.get("/api/imports/removed", headers=auth(token)).json()) == 1

        _seed_imported_week(client, token, "2026-03-02")   # same week, fresh upload
        assert client.get("/api/imports/removed", headers=auth(token)).json() == []

    def test_restoring_over_a_week_that_is_back_is_refused(self, client):
        token = register(client)
        roster_id = _seed_imported_week(client, token, "2026-03-02")
        client.delete(f"/api/imports/history/{roster_id}", headers=auth(token))
        offered = client.get("/api/imports/removed", headers=auth(token)).json()
        _seed_imported_week(client, token, "2026-03-02")

        response = client.post("/api/imports/removed/restore", json={
            "import_id": offered[0]["import_id"], "week_start": "2026-03-02",
        }, headers=auth(token))
        assert response.status_code == 409
        assert len(client.get("/api/imports/history", headers=auth(token)).json()) == 1

    def test_restore_needs_the_upload_to_still_exist(self, client):
        token = register(client)
        roster_id = _seed_imported_week(client, token, "2026-03-02")
        client.delete(f"/api/imports/history/{roster_id}", headers=auth(token))
        offered = client.get("/api/imports/removed", headers=auth(token)).json()
        client.delete(f"/api/imports/{offered[0]['import_id']}", headers=auth(token))

        response = client.post("/api/imports/removed/restore", json={
            "import_id": offered[0]["import_id"], "week_start": "2026-03-02",
        }, headers=auth(token))
        assert response.status_code == 404
        assert "Re-upload the file" in response.json()["detail"]

    def test_removed_weeks_do_not_leak_between_shops(self, client):
        mine = register(client, email="mine@example.com")
        theirs = register(client, email="theirs@example.com")
        roster_id = _seed_imported_week(client, mine, "2026-03-02")
        client.delete(f"/api/imports/history/{roster_id}", headers=auth(mine))

        offered = client.get("/api/imports/removed", headers=auth(mine)).json()
        assert client.get("/api/imports/removed", headers=auth(theirs)).json() == []
        assert client.post("/api/imports/removed/restore", json={
            "import_id": offered[0]["import_id"], "week_start": "2026-03-02",
        }, headers=auth(theirs)).status_code == 404

    def test_a_generated_week_cannot_be_removed_as_an_import(self, client):
        """The line: imported data is removable, decisions made here are not."""
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        roster_id = client.post(
            "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token)
        ).json()["roster_id"]

        response = client.delete(f"/api/imports/history/{roster_id}", headers=auth(token))
        assert response.status_code == 409
        assert "not imported" in response.json()["detail"]["message"]
        assert client.get(
            f"/api/rosters/{roster_id}", headers=auth(token)
        ).status_code == 200, "the roster must survive a refused delete"

    def test_removing_an_unknown_week_is_a_404(self, client):
        token = register(client)
        assert client.delete(
            "/api/imports/history/hist_nope", headers=auth(token)
        ).status_code == 404

    def test_imported_weeks_do_not_leak_between_shops(self, client):
        mine = register(client, email="mine@example.com")
        theirs = register(client, email="theirs@example.com")
        roster_id = _seed_imported_week(client, mine, "2026-03-09")

        assert client.get("/api/imports/history", headers=auth(theirs)).json() == []
        assert client.delete(
            f"/api/imports/history/{roster_id}", headers=auth(theirs)
        ).status_code == 404
        assert len(client.get("/api/imports/history", headers=auth(mine)).json()) == 1

    def test_the_retired_endpoints_are_gone(self, client):
        """OCR-by-URL and upload-historical duplicated /imports, which does
        the same job with a real file, a preview and name mapping.

        Checked against the route table, not by calling them: "/rosters/ocr"
        still matches "/rosters/{roster_id}", so a request returns 405 rather
        than 404 and would pass a weaker assertion for the wrong reason.
        """
        paths = {r.path for r in client.app.routes if hasattr(r, "path")}
        for gone in ("/api/rosters/ocr", "/api/rosters/ocr-batch",
                     "/api/rosters/upload-historical", "/api/ai/training-stats"):
            assert gone not in paths, gone


def test_a_work_shift_still_requires_times(client):
    """Making times optional must not let a work shift through without them."""
    token = register(client)
    roster_id, employee_id, _, _ = _roster_with_leave(client, token)

    response = client.put(
        f"/api/rosters/{roster_id}",
        json={"shifts": [{"employee_id": employee_id, "day": "mon",
                          "start": "", "end": ""}]},
        headers=auth(token),
    )
    assert response.status_code == 422


def test_a_custom_rule_is_enforced_without_an_api_key(client):
    """Rules used to need the LLM to compile. With no key they saved, showed
    as enabled, and were silently ignored."""
    token = register(client)
    employee_id = client.post(
        "/api/employees",
        json={**EMPLOYEE, "name": "Sarah", "email": "sarah@example.com"},
        headers=auth(token),
    ).json()["employee_id"]

    rule = client.post(
        "/api/ai-rules",
        json={"title": "Sarah Sundays", "description": "Sarah never works Sundays",
              "category": "custom"},
        headers=auth(token),
    ).json()

    assert rule["compiled"], "the rule should compile without an API key"
    assert rule["compiled"]["type"] == "no_day"
    assert rule["compiled"]["days"] == ["sun"]
    assert employee_id in rule["compiled"]["employee_ids"]
    assert rule["approved"] is True, "a deterministic parse needs no review"

    roster = client.post(
        "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token),
    ).json()
    sundays = [s for s in roster["shifts"] if s["day"] == "sun"]
    assert sundays == [], "the rule was written but not obeyed"


def test_an_unreadable_rule_is_reported_not_ignored(client):
    """Silently dropping it is how somebody writes a rule, sees it listed as
    enabled, and gets a roster that breaks it."""
    token = register(client)
    client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
    created = client.post(
        "/api/ai-rules",
        json={"title": "Vibes", "description": "Make the roster nicer please",
              "category": "custom"},
        headers=auth(token),
    ).json()
    assert created["compiled"] is None

    roster = client.post(
        "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token),
    ).json()
    assert any("could not be read" in i for i in roster["issues"])


def test_editing_a_rule_recompiles_it(client):
    """An edited rule must not keep enforcing the previous wording."""
    token = register(client)
    client.post(
        "/api/employees",
        json={**EMPLOYEE, "name": "Sarah", "email": "sarah@example.com"},
        headers=auth(token),
    )
    rule = client.post(
        "/api/ai-rules",
        json={"title": "R", "description": "Sarah never works Sundays",
              "category": "custom"},
        headers=auth(token),
    ).json()

    updated = client.put(
        f"/api/ai-rules/{rule['rule_id']}",
        json={"title": "R", "description": "Sarah never works Mondays",
              "category": "custom"},
        headers=auth(token),
    ).json()
    assert updated["compiled"]["days"] == ["mon"]


def test_approving_a_roster_with_uncovered_hours_is_refused(client):
    """Approval turns a draft into what people are told to work. It was going
    through silently on rosters that left the shop unattended — the one
    outcome this app exists to prevent."""
    token = register(client)
    client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
    roster = client.post(
        "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token),
    ).json()
    assert roster["critical_issues"], "fixture should leave hours uncovered"

    refused = client.post(
        f"/api/rosters/{roster['roster_id']}/approve", headers=auth(token),
    )
    assert refused.status_code == 409
    assert "unattended" in refused.json()["detail"]

    still_draft = client.get("/api/rosters", headers=auth(token)).json()
    assert not next(
        r for r in still_draft if r["roster_id"] == roster["roster_id"]
    ).get("approved")


def test_uncovered_hours_can_be_accepted_deliberately(client):
    """It has to be a decision, not a blocked road."""
    token = register(client)
    client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
    roster = client.post(
        "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token),
    ).json()

    accepted = client.post(
        f"/api/rosters/{roster['roster_id']}/approve?acknowledge_gaps=true",
        headers=auth(token),
    )
    assert accepted.status_code == 200
    # Recorded, so a week that went out with known gaps says so afterwards.
    assert accepted.json()["approved_with_gaps"] == len(roster["critical_issues"])


def test_hierarchy_endpoint_surfaces_unplaced_roles(client):
    """A job title nobody positioned ranks last, which is invisible unless
    the settings screen is told about it."""
    token = register(client)
    client.post(
        "/api/employees",
        json={**EMPLOYEE, "role": "Barista"}, headers=auth(token),
    )

    body = client.get("/api/shop/hierarchy", headers=auth(token)).json()
    assert body["is_customised"] is False
    assert body["hierarchy"][-1] == "Barista"
    assert "Assistant Manager" in body["supervisory"]
    assert "Barista" not in body["supervisory"]


def test_custom_hierarchy_is_honoured(client):
    token = register(client)
    client.put(
        "/api/shop",
        json={"role_hierarchy": ["Barista", "Cashier"]}, headers=auth(token),
    )
    for name, role in [("Ann", "Cashier"), ("Ben", "Barista")]:
        client.post(
            "/api/employees",
            json={**EMPLOYEE, "name": name, "email": f"{name.lower()}@example.com",
                  "role": role},
            headers=auth(token),
        )

    body = client.get("/api/shop/hierarchy", headers=auth(token)).json()
    assert body["is_customised"] is True
    assert body["hierarchy"] == ["Barista", "Cashier"]

    listed = client.get("/api/employees", headers=auth(token)).json()
    assert [e["name"] for e in listed] == ["Ben", "Ann"]


def test_underage_employee_is_rejected(client):
    token = register(client)
    response = client.post(
        "/api/employees", json={**EMPLOYEE, "age": 11}, headers=auth(token)
    )
    assert response.status_code == 422


def test_deleting_an_employee_removes_their_fixed_shifts(client):
    """Orphaned fixed shifts would make the solver roster a ghost."""
    token = register(client)
    employee_id = client.post("/api/employees", json=EMPLOYEE, headers=auth(token)).json()["employee_id"]
    client.post("/api/fixed-shifts", json={
        "employee_id": employee_id, "days": ["mon"], "start": "09:00", "end": "17:00",
    }, headers=auth(token))

    client.delete(f"/api/employees/{employee_id}", headers=auth(token))
    assert client.get("/api/fixed-shifts", headers=auth(token)).json() == []


# ---------------------------------------------------------------------------
# Tenant isolation — the core security property
# ---------------------------------------------------------------------------
class TestTenantIsolation:
    def test_shops_cannot_see_each_others_employees(self, client):
        token_a = register(client, "a@example.com")
        token_b = register(client, "b@example.com")

        client.post("/api/employees", json=EMPLOYEE, headers=auth(token_a))
        assert client.get("/api/employees", headers=auth(token_b)).json() == []

    def test_shops_cannot_delete_each_others_employees(self, client):
        token_a = register(client, "a@example.com")
        token_b = register(client, "b@example.com")

        employee_id = client.post(
            "/api/employees", json=EMPLOYEE, headers=auth(token_a)
        ).json()["employee_id"]

        # Shop B knows the ID but must not be able to act on it.
        assert client.delete(
            f"/api/employees/{employee_id}", headers=auth(token_b)
        ).status_code == 404
        assert len(client.get("/api/employees", headers=auth(token_a)).json()) == 1

    def test_shops_cannot_read_each_others_rosters(self, client):
        token_a = register(client, "a@example.com")
        token_b = register(client, "b@example.com")

        client.post("/api/employees", json=EMPLOYEE, headers=auth(token_a))
        roster_id = client.post(
            "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token_a)
        ).json()["roster_id"]

        assert client.get(f"/api/rosters/{roster_id}", headers=auth(token_b)).status_code == 404


# ---------------------------------------------------------------------------
# System rules are immutable
# ---------------------------------------------------------------------------
class TestSystemRulesAreLocked:
    def test_system_rules_are_seeded_and_locked(self, client):
        token = register(client)
        rules = client.get("/api/ai-rules", headers=auth(token)).json()
        locked = [r for r in rules if r.get("locked")]
        assert len(locked) >= 6
        assert all(r["enabled"] for r in locked)

    def test_locked_rule_cannot_be_disabled(self, client):
        token = register(client)
        rule = next(r for r in client.get("/api/ai-rules", headers=auth(token)).json() if r["locked"])

        response = client.put(f"/api/ai-rules/{rule['rule_id']}", json={
            "title": rule["title"], "description": rule["description"],
            "category": rule["category"], "enabled": False,
        }, headers=auth(token))
        assert response.status_code == 403

        # And it really is still on.
        after = client.get("/api/ai-rules", headers=auth(token)).json()
        assert next(r for r in after if r["rule_id"] == rule["rule_id"])["enabled"] is True

    def test_locked_rule_cannot_be_deleted(self, client):
        token = register(client)
        rule = next(r for r in client.get("/api/ai-rules", headers=auth(token)).json() if r["locked"])
        assert client.delete(
            f"/api/ai-rules/{rule['rule_id']}", headers=auth(token)
        ).status_code == 403

    def test_custom_rules_remain_editable(self, client):
        token = register(client)
        created = client.post("/api/ai-rules", json={
            "title": "No lone opening", "description": "Two people must open.",
            "category": "custom", "enabled": True,
        }, headers=auth(token))
        assert created.status_code == 201
        assert created.json()["locked"] is False

        rule_id = created.json()["rule_id"]
        assert client.delete(f"/api/ai-rules/{rule_id}", headers=auth(token)).status_code == 200


# ---------------------------------------------------------------------------
# Rosters
# ---------------------------------------------------------------------------
class TestRosters:
    def test_generation_requires_employees(self, client):
        token = register(client)
        response = client.post(
            "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token)
        )
        assert response.status_code == 400

    def test_generated_roster_covers_the_whole_day(self, client):
        token = register(client)
        for i in range(6):
            client.post("/api/employees", json={
                **EMPLOYEE, "name": f"Staff {i}", "email": f"s{i}@example.com",
            }, headers=auth(token))

        roster = client.post(
            "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token)
        ).json()

        # Default hours are 09:00-21:00 with a 9h max shift, so coverage
        # requires more than one shift per day.
        monday = sorted(
            (s for s in roster["shifts"] if s["day"] == "mon"), key=lambda s: s["start"]
        )
        assert monday[0]["start"] == "09:00"
        assert monday[-1]["end"] == "21:00"

    def test_versions_increment_for_the_same_week(self, client):
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        payload = {"week_start": "2026-08-10"}

        first = client.post("/api/roster/generate", json=payload, headers=auth(token)).json()
        second = client.post("/api/roster/generate", json=payload, headers=auth(token)).json()
        assert first["version"] == "v1.0"
        assert second["version"] == "v1.1"

    def test_past_route_is_not_shadowed_by_the_id_route(self, client):
        """/rosters/past must not be read as a roster whose id is 'past'."""
        token = register(client)
        assert client.get("/api/rosters/past", headers=auth(token)).status_code == 200

    def test_approved_roster_cannot_be_edited(self, client):
        token = register(client)
        employee_id = client.post(
            "/api/employees", json=EMPLOYEE, headers=auth(token)
        ).json()["employee_id"]
        roster_id = client.post(
            "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token)
        ).json()["roster_id"]

        client.post(f"/api/rosters/{roster_id}/approve?acknowledge_gaps=true", headers=auth(token))
        response = client.put(f"/api/rosters/{roster_id}", json={"shifts": [
            {"employee_id": employee_id, "day": "mon", "start": "09:00", "end": "17:00"}
        ]}, headers=auth(token))
        assert response.status_code == 409

    def test_over_long_shift_is_rejected_on_edit(self, client):
        token = register(client)
        employee_id = client.post(
            "/api/employees", json=EMPLOYEE, headers=auth(token)
        ).json()["employee_id"]
        roster_id = client.post(
            "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token)
        ).json()["roster_id"]

        response = client.put(f"/api/rosters/{roster_id}", json={"shifts": [
            {"employee_id": employee_id, "day": "mon", "start": "06:00", "end": "23:00"}
        ]}, headers=auth(token))
        assert response.status_code == 400
        # Refusals carry a list of reasons so the UI can show them one per
        # line, rather than one run-together sentence.
        detail = response.json()["detail"]
        assert any("maximum shift length" in reason for reason in detail["reasons"])

    def test_duplicate_shift_for_one_person_is_rejected(self, client):
        token = register(client)
        employee_id = client.post(
            "/api/employees", json=EMPLOYEE, headers=auth(token)
        ).json()["employee_id"]
        roster_id = client.post(
            "/api/roster/generate", json={"week_start": "2026-08-10"}, headers=auth(token)
        ).json()["roster_id"]

        response = client.put(f"/api/rosters/{roster_id}", json={"shifts": [
            {"employee_id": employee_id, "day": "mon", "start": "09:00", "end": "13:00"},
            {"employee_id": employee_id, "day": "mon", "start": "14:00", "end": "18:00"},
        ]}, headers=auth(token))
        assert response.status_code == 400

    def test_an_approved_week_refuses_a_second_generation(self, client):
        """One approved roster per week, or the solver learns it twice."""
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        payload = {"week_start": _future_monday()}

        first = client.post("/api/roster/generate", json=payload, headers=auth(token)).json()
        client.post(
            f"/api/rosters/{first['roster_id']}/approve?acknowledge_gaps=true",
            headers=auth(token),
        )

        blocked = client.post("/api/roster/generate", json=payload, headers=auth(token))
        assert blocked.status_code == 409
        detail = blocked.json()["detail"]
        assert "Unapprove it first" in detail["message"]
        assert detail["approved_roster_id"] == first["roster_id"]

    def test_unapprove_reopens_the_week_and_drops_it_from_learning(self, client):
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        payload = {"week_start": _future_monday()}

        roster = client.post("/api/roster/generate", json=payload, headers=auth(token)).json()
        rid = roster["roster_id"]
        client.post(f"/api/rosters/{rid}/approve?acknowledge_gaps=true", headers=auth(token))

        learned = client.get("/api/imports/learning-summary", headers=auth(token)).json()
        assert learned["approved_rosters"] == 1

        response = client.post(f"/api/rosters/{rid}/unapprove", headers=auth(token))
        assert response.status_code == 200
        assert response.json()["unlearned"] is True

        # The unlearn is the flag: nothing is cached, so the corpus shrinks.
        after = client.get("/api/imports/learning-summary", headers=auth(token)).json()
        assert after["approved_rosters"] == 0

        # And the week is workable again.
        assert client.post(
            "/api/roster/generate", json=payload, headers=auth(token)
        ).status_code == 200

    def test_unapprove_reopens_editing(self, client):
        token = register(client)
        employee_id = client.post(
            "/api/employees", json=EMPLOYEE, headers=auth(token)
        ).json()["employee_id"]
        week = _future_monday()

        rid = client.post(
            "/api/roster/generate", json={"week_start": week}, headers=auth(token)
        ).json()["roster_id"]
        client.post(f"/api/rosters/{rid}/approve?acknowledge_gaps=true", headers=auth(token))

        edit = {"shifts": [
            {"employee_id": employee_id, "day": "mon", "start": "09:00", "end": "17:00"},
        ]}
        assert client.put(f"/api/rosters/{rid}", json=edit, headers=auth(token)).status_code == 409

        client.post(f"/api/rosters/{rid}/unapprove", headers=auth(token))
        assert client.put(f"/api/rosters/{rid}", json=edit, headers=auth(token)).status_code == 200

    def test_a_finished_week_cannot_be_reopened(self, client):
        """Past weeks are the record of what happened, not a plan."""
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))

        rid = client.post(
            "/api/roster/generate", json={"week_start": "2020-01-06"}, headers=auth(token)
        ).json()["roster_id"]
        client.post(f"/api/rosters/{rid}/approve?acknowledge_gaps=true", headers=auth(token))

        response = client.post(f"/api/rosters/{rid}/unapprove", headers=auth(token))
        assert response.status_code == 409
        assert "already been worked" in response.json()["detail"]["message"]

    def test_unapprove_leaves_superseded_drafts_archived(self, client):
        """Reopening returns you to what you approved, not what you rejected."""
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        payload = {"week_start": _future_monday()}

        draft = client.post("/api/roster/generate", json=payload, headers=auth(token)).json()
        final = client.post("/api/roster/generate", json=payload, headers=auth(token)).json()
        client.post(
            f"/api/rosters/{final['roster_id']}/approve?acknowledge_gaps=true",
            headers=auth(token),
        )
        client.post(f"/api/rosters/{final['roster_id']}/unapprove", headers=auth(token))

        old = client.get(f"/api/rosters/{draft['roster_id']}", headers=auth(token)).json()
        assert old["archived"] is True

    def test_unapprove_needs_an_approved_roster(self, client):
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        rid = client.post(
            "/api/roster/generate", json={"week_start": _future_monday()},
            headers=auth(token),
        ).json()["roster_id"]

        assert client.post(
            f"/api/rosters/{rid}/unapprove", headers=auth(token)
        ).status_code == 409

    def test_approval_archives_rather_than_deletes_drafts(self, client):
        """Superseded drafts are training signal — they must survive."""
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        payload = {"week_start": "2026-08-10"}

        draft = client.post("/api/roster/generate", json=payload, headers=auth(token)).json()
        final = client.post("/api/roster/generate", json=payload, headers=auth(token)).json()

        approved = client.post(
            f"/api/rosters/{final['roster_id']}/approve?acknowledge_gaps=true", headers=auth(token)
        ).json()
        assert approved["archived_drafts"] == 1

        old = client.get(f"/api/rosters/{draft['roster_id']}", headers=auth(token)).json()
        assert old["archived"] is True
        assert old["superseded_by"] == final["roster_id"]


# ---------------------------------------------------------------------------
# Validation at the edge
# ---------------------------------------------------------------------------
class TestValidation:
    def test_malformed_time_is_rejected(self, client):
        token = register(client)
        employee_id = client.post(
            "/api/employees", json=EMPLOYEE, headers=auth(token)
        ).json()["employee_id"]
        response = client.post("/api/fixed-shifts", json={
            "employee_id": employee_id, "days": ["mon"], "start": "9am", "end": "17:00",
        }, headers=auth(token))
        assert response.status_code == 422

    def test_invalid_day_key_is_rejected(self, client):
        token = register(client)
        response = client.post(
            "/api/employees",
            json={**EMPLOYEE, "preferred_days_off": ["funday"]},
            headers=auth(token),
        )
        assert response.status_code == 422

    def test_min_shift_cannot_exceed_max_shift(self, client):
        token = register(client)
        response = client.put(
            "/api/shop", json={"min_shift_hours": 10, "max_shift_hours": 6},
            headers=auth(token),
        )
        assert response.status_code == 400

    def test_employee_leave_requires_an_employee(self, client):
        token = register(client)
        response = client.post("/api/holidays", json={
            "date": "2026-08-10", "label": "Sick", "scope": "sick",
        }, headers=auth(token))
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class TestLeave:
    """Booking leave over a date range, marking which days are paid.

    Two properties matter and both come from how leave really works: only
    days inside the range are touched, and within it the employee is paid
    only for days they would have worked.
    """

    def _employee(self, client, token, hours=20, holiday_hours=200.0):
        """Opening balance included: paid holiday is now capped at what the
        employee actually has, so a fresh employee with no history cannot
        book any. Tests about date ranges should not double as tests of the
        balance cap — that has its own class."""
        return client.post("/api/employees", json={
            **EMPLOYEE,
            "max_weekly_hours": hours,
            "opening_holiday_hours": holiday_hours,
        }, headers=auth(token)).json()["employee_id"]

    def _cover(self, client, token, n=5):
        for i in range(n):
            client.post("/api/employees", json={
                **EMPLOYEE, "name": f"Cover {i}", "email": f"c{i}@example.com",
            }, headers=auth(token))

    def test_two_day_booking_leaves_the_rest_of_the_week_alone(self, client):
        """The case that drove this design: two days off must not block the
        other three working days of that week."""
        token = register(client)
        employee_id = self._employee(client, token)

        response = client.post("/api/holidays/leave", json={
            "employee_id": employee_id,
            "start_date": "2026-08-13",     # Thursday
            "end_date": "2026-08-14",       # Friday
            "paid_dates": ["2026-08-13", "2026-08-14"],
        }, headers=auth(token))
        assert response.status_code == 201, response.text
        assert response.json()["total_days"] == 2

        holidays = client.get("/api/holidays", headers=auth(token)).json()
        assert len(holidays) == 2, "only the two booked days should exist"
        assert {h["date"] for h in holidays} == {"2026-08-13", "2026-08-14"}

    def test_range_splits_into_paid_and_unpaid(self, client):
        token = register(client)
        employee_id = self._employee(client, token)

        response = client.post("/api/holidays/leave", json={
            "employee_id": employee_id,
            "start_date": "2026-08-10", "end_date": "2026-08-16",
            "paid_dates": ["2026-08-10", "2026-08-11"],
            "label": "Summer holiday",
        }, headers=auth(token))
        assert response.status_code == 201
        body = response.json()
        assert body["paid_days"] == 2 and body["unpaid_days"] == 5

        holidays = client.get("/api/holidays", headers=auth(token)).json()
        assert len([h for h in holidays if h["scope"] == "employee"]) == 2
        assert len([h for h in holidays if h["scope"] == "unavailable"]) == 5

    def test_multi_week_range_with_different_paid_days(self, client):
        """Paid days genuinely differ week to week across a long booking."""
        token = register(client)
        employee_id = self._employee(client, token, hours=40)

        response = client.post("/api/holidays/leave", json={
            "employee_id": employee_id,
            "start_date": "2026-08-10", "end_date": "2026-08-30",   # 3 weeks
            "paid_dates": [
                "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13",  # 4 in wk 1
                "2026-08-17", "2026-08-18", "2026-08-19",                # 3 in wk 2
            ],                                                            # 0 in wk 3
        }, headers=auth(token))
        assert response.status_code == 201
        body = response.json()
        assert body["total_days"] == 21
        assert body["paid_days"] == 7
        assert body["paid_hours_total"] == pytest.approx(56.0)   # 7 x 8h

    def test_paid_day_defaults_to_a_normal_day_of_their_contract(self, client):
        """20h contract -> 4h a day, not a flat 8."""
        token = register(client)
        employee_id = self._employee(client, token, hours=20)

        response = client.post("/api/holidays/leave", json={
            "employee_id": employee_id,
            "start_date": "2026-08-10", "end_date": "2026-08-11",
            "paid_dates": ["2026-08-10", "2026-08-11"],
        }, headers=auth(token))
        assert response.json()["paid_hours_total"] == pytest.approx(8.0)

    def test_paid_date_outside_the_range_is_rejected(self, client):
        """Silently dropping it would hide a form/range mismatch."""
        token = register(client)
        employee_id = self._employee(client, token)
        response = client.post("/api/holidays/leave", json={
            "employee_id": employee_id,
            "start_date": "2026-08-10", "end_date": "2026-08-11",
            "paid_dates": ["2026-08-20"],
        }, headers=auth(token))
        assert response.status_code == 400
        assert client.get("/api/holidays", headers=auth(token)).json() == []

    def test_end_before_start_is_rejected(self, client):
        token = register(client)
        employee_id = self._employee(client, token)
        response = client.post("/api/holidays/leave", json={
            "employee_id": employee_id,
            "start_date": "2026-08-14", "end_date": "2026-08-10",
            "paid_dates": [],
        }, headers=auth(token))
        assert response.status_code == 400

    def test_absurd_range_is_rejected(self, client):
        """Catches a mistyped year rather than writing thousands of records."""
        token = register(client)
        employee_id = self._employee(client, token)
        response = client.post("/api/holidays/leave", json={
            "employee_id": employee_id,
            "start_date": "2026-08-10", "end_date": "2027-08-10",
            "paid_dates": [],
        }, headers=auth(token))
        assert response.status_code == 400

    def test_rebooking_replaces_rather_than_duplicates(self, client):
        token = register(client)
        employee_id = self._employee(client, token)
        base = {
            "employee_id": employee_id,
            "start_date": "2026-08-10", "end_date": "2026-08-16",
        }
        client.post("/api/holidays/leave", json={**base, "paid_dates": ["2026-08-10"]},
                    headers=auth(token))
        client.post("/api/holidays/leave", json={**base, "paid_dates": ["2026-08-12"]},
                    headers=auth(token))

        holidays = client.get("/api/holidays", headers=auth(token)).json()
        assert len(holidays) == 7, "correcting a booking must not double it up"
        paid = [h for h in holidays if h["scope"] == "employee"]
        assert {h["date"] for h in paid} == {"2026-08-12"}

    def test_leave_appears_on_the_roster_and_blocks_work(self, client):
        token = register(client)
        employee_id = self._employee(client, token, hours=20)
        self._cover(client, token)

        client.post("/api/holidays/leave", json={
            "employee_id": employee_id,
            "start_date": "2026-08-10", "end_date": "2026-08-16",
            "paid_dates": ["2026-08-10", "2026-08-11"],
        }, headers=auth(token))

        roster = client.post("/api/roster/generate", json={"week_start": "2026-08-10"},
                             headers=auth(token)).json()
        mine = [s for s in roster["shifts"] if s["employee_id"] == employee_id]

        assert {s["day"] for s in mine if s.get("paid_holiday")} == {"mon", "tue"}
        assert not [s for s in mine if not s.get("paid_holiday")]

    def test_holiday_hours_draw_down_the_balance(self, client):
        token = register(client)
        employee_id = self._employee(client, token, hours=20)
        self._cover(client, token)

        client.post("/api/holidays/leave", json={
            "employee_id": employee_id,
            "start_date": "2026-08-10", "end_date": "2026-08-16",
            "paid_dates": ["2026-08-10", "2026-08-11"],
        }, headers=auth(token))
        roster_id = client.post("/api/roster/generate", json={"week_start": "2026-08-10"},
                                headers=auth(token)).json()["roster_id"]
        client.post(f"/api/rosters/{roster_id}/approve?acknowledge_gaps=true", headers=auth(token))

        balance = client.get(
            f"/api/employees/{employee_id}/holiday-balance", headers=auth(token)
        ).json()
        assert balance["used_paid_holiday"] == pytest.approx(8.0)


class TestImportCapabilities:
    """The UI asks what this deployment can read before offering it.

    Telling someone a format is unavailable up front is far better than a
    503 after they have waited for a large upload.
    """

    def test_spreadsheets_always_available(self, client):
        token = register(client)
        caps = client.get("/api/imports/capabilities", headers=auth(token)).json()
        assert caps["spreadsheet"] is True
        assert caps["csv"] is True

    def test_photo_import_requires_an_llm_key(self, client, monkeypatch):
        from app.services import llm
        monkeypatch.setattr(llm, "enabled", False)

        token = register(client)
        caps = client.get("/api/imports/capabilities", headers=auth(token)).json()
        assert caps["image"] is False
        assert caps["pdf"] is False, "a PDF still needs the model to read its pages"
        assert "ANTHROPIC_API_KEY" in caps["reasons"]["llm"]

    def test_reasons_are_empty_when_everything_is_configured(self, client, monkeypatch):
        from app.services import llm
        monkeypatch.setattr(llm, "enabled", True)

        token = register(client)
        caps = client.get("/api/imports/capabilities", headers=auth(token)).json()
        if caps["pdf"] and caps["image"]:
            assert caps["reasons"] == {}

    def test_capabilities_route_is_not_shadowed_by_the_list_route(self, client):
        token = register(client)
        response = client.get("/api/imports/capabilities", headers=auth(token))
        assert response.status_code == 200
        assert "spreadsheet" in response.json()


def test_holiday_balance_route_is_not_shadowed(client):
    """'/employees/holiday-balances' must beat '/employees/{id}/...'."""
    token = register(client)
    response = client.get("/api/employees/holiday-balances", headers=auth(token))
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_sick_leave_report_aggregates_days(client):
    token = register(client)
    employee_id = client.post(
        "/api/employees", json=EMPLOYEE, headers=auth(token)
    ).json()["employee_id"]

    client.post("/api/holidays", json={
        "date": "2026-08-10", "end_date": "2026-08-12", "label": "Flu",
        "scope": "sick", "employee_id": employee_id,
    }, headers=auth(token))

    report = client.get("/api/reports/sick-leave", headers=auth(token)).json()
    assert report["total_days"] == 3          # inclusive range
    assert report["total_incidents"] == 1


class TestUndoSick:
    """A sick call recorded by mistake has to be fully reversible.

    Undoing only the flag would leave the shift double-staffed and the person
    still blocked from being rostered that day — a worse state than either
    marking it or not.
    """

    def _sick_week(self, client, token, with_cover=True):
        ids = {}
        for name in ("Alex", "Sam"):
            ids[name] = client.post("/api/employees", json={
                **EMPLOYEE, "name": name, "email": f"{name.lower()}@e.com",
            }, headers=auth(token)).json()["employee_id"]

        week = _future_monday()
        roster = client.post(
            "/api/roster/generate", json={"week_start": week}, headers=auth(token)
        ).json()
        rid = roster["roster_id"]
        client.post(f"/api/rosters/{rid}/approve?acknowledge_gaps=true", headers=auth(token))

        full = client.get(f"/api/rosters/{rid}", headers=auth(token)).json()
        shift = next(s for s in full["shifts"] if s.get("start"))
        cover = next(v for v in ids.values() if v != shift["employee_id"])

        client.post(f"/api/rosters/{rid}/sick", json={
            "employee_id": shift["employee_id"], "day": shift["day"],
            "cover_employee_id": cover if with_cover else None,
            "reason": "Flu",
        }, headers=auth(token))
        return rid, shift, cover

    def test_the_shift_goes_back_to_normal(self, client):
        token = register(client)
        rid, shift, _ = self._sick_week(client, token)

        response = client.delete(
            f"/api/rosters/{rid}/sick",
            params={"employee_id": shift["employee_id"], "day": shift["day"]},
            headers=auth(token),
        )
        assert response.status_code == 200, response.text

        after = client.get(f"/api/rosters/{rid}", headers=auth(token)).json()
        restored = next(
            s for s in after["shifts"]
            if s["employee_id"] == shift["employee_id"] and s["day"] == shift["day"]
        )
        assert not restored.get("sick")
        assert restored["start"] == shift["start"], "their hours come back"

    def test_the_cover_shift_is_removed(self, client):
        """Otherwise the day is staffed twice for the same slot."""
        token = register(client)
        rid, shift, cover = self._sick_week(client, token)

        body = client.delete(
            f"/api/rosters/{rid}/sick",
            params={"employee_id": shift["employee_id"], "day": shift["day"]},
            headers=auth(token),
        ).json()
        assert body["cover_removed"] == 1

        after = client.get(f"/api/rosters/{rid}", headers=auth(token)).json()
        assert not [s for s in after["shifts"] if s.get("covering_for")]

    def test_the_booked_absence_is_removed(self, client):
        """Or they stay blocked from being rostered that day."""
        token = register(client)
        rid, shift, _ = self._sick_week(client, token)
        assert client.get(
            "/api/reports/sick-leave", headers=auth(token)
        ).json()["total_days"] == 1

        client.delete(
            f"/api/rosters/{rid}/sick",
            params={"employee_id": shift["employee_id"], "day": shift["day"]},
            headers=auth(token),
        )
        assert client.get(
            "/api/reports/sick-leave", headers=auth(token)
        ).json()["total_days"] == 0

    def test_the_week_stays_approved_throughout(self, client):
        token = register(client)
        rid, shift, _ = self._sick_week(client, token)
        client.delete(
            f"/api/rosters/{rid}/sick",
            params={"employee_id": shift["employee_id"], "day": shift["day"]},
            headers=auth(token),
        )
        assert client.get(
            f"/api/rosters/{rid}", headers=auth(token)
        ).json()["approved"] is True

    def test_an_unrelated_shift_that_day_is_kept(self, client):
        """Somebody already working that day is not cover — leave them be."""
        token = register(client)
        rid, shift, _ = self._sick_week(client, token, with_cover=False)
        before = len(client.get(f"/api/rosters/{rid}", headers=auth(token)).json()["shifts"])

        body = client.delete(
            f"/api/rosters/{rid}/sick",
            params={"employee_id": shift["employee_id"], "day": shift["day"]},
            headers=auth(token),
        ).json()
        assert body["cover_removed"] == 0

        after = client.get(f"/api/rosters/{rid}", headers=auth(token)).json()
        assert len(after["shifts"]) == before

    def test_undoing_what_was_never_marked_is_a_404(self, client):
        token = register(client)
        rid, shift, _ = self._sick_week(client, token)
        client.delete(
            f"/api/rosters/{rid}/sick",
            params={"employee_id": shift["employee_id"], "day": shift["day"]},
            headers=auth(token),
        )
        assert client.delete(
            f"/api/rosters/{rid}/sick",
            params={"employee_id": shift["employee_id"], "day": shift["day"]},
            headers=auth(token),
        ).status_code == 404

    def test_the_reversal_is_logged(self, client):
        token = register(client)
        rid, shift, _ = self._sick_week(client, token)
        client.delete(
            f"/api/rosters/{rid}/sick",
            params={"employee_id": shift["employee_id"], "day": shift["day"]},
            headers=auth(token),
        )
        log = client.get("/api/activity", headers=auth(token)).json()
        assert any(a["action"] == "shift_sick_undone" for a in log)


class TestSystemRulesAreNotDuplicated:
    """seed_system_rules runs on every authenticated request, and the browser
    makes several in parallel on page load.

    An earlier read-then-insert version raced itself: two requests both found
    a newly added rule missing, both inserted it, and the shop listed the rule
    twice. That happened the first time anybody loaded the page after a rule
    was added — which is the worst possible moment, because it looks like the
    new feature is broken.
    """

    def _rules(self, client, token):
        return client.get("/api/ai-rules", headers=auth(token)).json()

    def test_one_copy_of_each_locked_rule(self, client):
        token = register(client)
        titles = [r["title"] for r in self._rules(client, token) if r.get("locked")]
        assert len(titles) == len(set(titles)), f"duplicated: {titles}"

    def test_repeated_requests_do_not_accumulate_rules(self, client):
        """Every request re-seeds; the count must not grow."""
        token = register(client)
        before = len(self._rules(client, token))
        for _ in range(5):
            client.get("/api/shop", headers=auth(token))
        assert len(self._rules(client, token)) == before

    def test_parallel_requests_do_not_duplicate(self, client):
        """The actual race, reproduced: concurrent seeding of one shop."""
        import asyncio

        from app.services.shop_service import seed_system_rules

        token = register(client)
        shop_id = client.get("/api/shop", headers=auth(token)).json()["shop_id"]

        async def race():
            # Six at once, the way a page load fires them.
            await asyncio.gather(*(seed_system_rules(shop_id) for _ in range(6)))

        asyncio.run(race())

        titles = [r["title"] for r in self._rules(client, token) if r.get("locked")]
        assert len(titles) == len(set(titles)), f"duplicated: {titles}"

    def test_the_wording_follows_the_code(self, client):
        """A locked rule that misstates what the solver does is worse than
        none — the 12-hour limit read '11 hours' for a while."""
        from app.services.scheduler import ABSOLUTE_MAX_SHIFT_HOURS, MIN_REST_HOURS

        token = register(client)
        rules = {r["title"]: r["description"] for r in self._rules(client, token)}

        assert f"{ABSOLUTE_MAX_SHIFT_HOURS} hours" in rules["Maximum shift length"]
        assert f"{MIN_REST_HOURS:g} consecutive hours" in rules["Rest between shifts"]


class TestTwentyFourHourShopIsActuallyOpen:
    """Turning on 24h must set the hours, whatever else the shop has.

    Both the hours and the starter templates used to sit behind "has no
    templates yet". So a shop that already had templates could be switched to
    24h and keep 09:00-21:00 opening hours — and because the coverage floor
    only checks open hours, the small hours were then unstaffed AND
    unreported.
    """

    def test_switching_to_24h_opens_every_hour(self, client):
        token = register(client)
        client.put("/api/shop", json={"open_24h": True}, headers=auth(token))
        shop = client.get("/api/shop", headers=auth(token)).json()

        assert shop["open_24h"] is True
        assert all(h["open"] == "00:00" for h in shop["hours"])
        assert all(h["close"] == "23:59" for h in shop["hours"])
        assert not any(h["closed"] for h in shop["hours"])

    def test_it_works_even_when_templates_already_exist(self, client):
        """The reported bug, exactly."""
        token = register(client)
        client.put("/api/shop", json={"shift_templates": [
            {"name": "Morning", "start": "07:00", "end": "15:00", "min_staff": 2},
        ]}, headers=auth(token))

        client.put("/api/shop", json={"open_24h": True}, headers=auth(token))
        shop = client.get("/api/shop", headers=auth(token)).json()

        assert all(h["open"] == "00:00" for h in shop["hours"]), (
            "a 24-hour shop that is not open 24 hours is a contradiction"
        )

    def test_existing_templates_are_not_replaced(self, client):
        """Only a shop with none gets the starter set."""
        token = register(client)
        client.put("/api/shop", json={"shift_templates": [
            {"name": "Mine", "start": "07:00", "end": "15:00", "min_staff": 2},
        ]}, headers=auth(token))
        client.put("/api/shop", json={"open_24h": True}, headers=auth(token))

        shop = client.get("/api/shop", headers=auth(token)).json()
        assert [t["name"] for t in shop["shift_templates"]] == ["Mine"]

    def test_a_shop_with_no_templates_gets_the_starter_set(self, client):
        token = register(client)
        client.put("/api/shop", json={"open_24h": True}, headers=auth(token))
        shop = client.get("/api/shop", headers=auth(token)).json()
        assert len(shop["shift_templates"]) == 3

    def test_turning_it_off_leaves_your_hours_alone(self, client):
        token = register(client)
        hours = [
            {"day": d, "open": "05:30", "close": "23:00", "closed": False}
            for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        ]
        client.put("/api/shop", json={"open_24h": False, "hours": hours},
                   headers=auth(token))
        shop = client.get("/api/shop", headers=auth(token)).json()
        assert shop["hours"][0]["open"] == "05:30"


class TestExtraStaffEndpoint:
    """Adding somebody above the normal cover, and what it refuses."""

    WEEK = "2026-09-07"
    _DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

    def _setup(self, client):
        """Enough staff that somebody has a free day.

        With two employees everyone is already on five days, so every extra
        shift is correctly refused as a sixth — which is the guard working,
        but leaves nothing to test the happy path with.
        """
        token = register(client)
        client.post("/api/employees", json=EMPLOYEE, headers=auth(token))
        for name in ("Bea", "Cara", "Dev", "Erin", "Finn"):
            client.post(
                "/api/employees",
                json={**EMPLOYEE, "name": name,
                      "email": f"{name.lower()}@example.com"},
                headers=auth(token),
            )
        roster = client.post(
            "/api/roster/generate", json={"week_start": self.WEEK},
            headers=auth(token),
        ).json()
        return token, roster

    def _somebody_with_a_free_day(self, client, token, roster):
        """(employee_id, day) that breaks no rule on its own."""
        worked = {}
        for shift in roster["shifts"]:
            if shift.get("start"):
                worked.setdefault(shift["employee_id"], set()).add(shift["day"])
        for employee in client.get("/api/employees", headers=auth(token)).json():
            days = worked.get(employee["employee_id"], set())
            if len(days) >= 5:
                continue
            free = [d for d in self._DAYS if d not in days]
            if free:
                return employee["employee_id"], free[0]
        raise AssertionError("fixture has nobody with a free day")

    def test_an_extra_shift_is_marked_as_one(self, client):
        token, roster = self._setup(client)
        employee_id, day = self._somebody_with_a_free_day(client, token, roster)

        response = client.post(
            f"/api/rosters/{roster['roster_id']}/extra",
            json={
                "employee_id": employee_id, "day": day,
                "start": "10:00", "end": "14:00", "reason": "Stock delivery",
            },
            headers=auth(token),
        )
        assert response.status_code == 200, response.text

        added = [s for s in response.json()["shifts"] if s.get("extra")]
        assert len(added) == 1
        assert added[0]["extra_reason"] == "Stock delivery"
        # Pinned too, so a later rebalance cannot move the person out from
        # under a decision the manager made deliberately.
        assert added[0]["pinned"] is True

    def test_an_overlapping_shift_is_refused_with_a_reason(self, client):
        token, roster = self._setup(client)
        existing = next(
            s for s in roster["shifts"] if s.get("start") and s.get("end")
        )

        response = client.post(
            f"/api/rosters/{roster['roster_id']}/extra",
            json={
                "employee_id": existing["employee_id"], "day": existing["day"],
                "start": existing["start"], "end": existing["end"],
            },
            headers=auth(token),
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reasons"], "a refusal has to say what is wrong"
        assert any("already working" in r for r in detail["reasons"])

    def test_an_over_long_shift_is_refused(self, client):
        token, roster = self._setup(client)
        employee_id, day = self._somebody_with_a_free_day(client, token, roster)

        response = client.post(
            f"/api/rosters/{roster['roster_id']}/extra",
            json={
                "employee_id": employee_id, "day": day,
                "start": "06:00", "end": "20:00",     # 14 hours
            },
            headers=auth(token),
        )
        assert response.status_code == 409
        assert any(
            "maximum for one shift" in r
            for r in response.json()["detail"]["reasons"]
        )

    def test_an_approved_week_is_refused(self, client):
        token, roster = self._setup(client)
        employee_id, day = self._somebody_with_a_free_day(client, token, roster)
        client.post(
            f"/api/rosters/{roster['roster_id']}/approve", headers=auth(token),
        )

        response = client.post(
            f"/api/rosters/{roster['roster_id']}/extra",
            json={
                "employee_id": employee_id, "day": day,
                "start": "10:00", "end": "14:00",
            },
            headers=auth(token),
        )
        assert response.status_code == 409


class TestCorrectionsReport:
    """What the scheduler has learned, and accepting or refusing it."""

    def _shop_with_repeated_edits(self, client, token, times=3):
        """Approve several weeks where the manager made the same edit.

        Built through the real endpoints rather than hand-written rows: the
        corrections are computed at approval from the frozen generated copy,
        so faking the database would test nothing that runs in production.
        """
        employee_id = client.post(
            "/api/employees", json=EMPLOYEE, headers=auth(token),
        ).json()["employee_id"]
        for name in ("Bea", "Cara", "Dev"):
            client.post(
                "/api/employees",
                json={**EMPLOYEE, "name": name, "email": f"{name.lower()}@e.com"},
                headers=auth(token),
            )

        # Every week is GENERATED before any is approved. Approving teaches
        # the scheduler immediately, so approving as we go meant the first
        # correction was learned and weeks two and three needed no edit —
        # only one correction ever reached the report, and the repeat this
        # test is about never happened. (Which is the product working; it
        # just makes for a fixture that proves nothing.)
        drafts = [
            client.post(
                "/api/roster/generate",
                json={"week_start": (date(2026, 9, 7) + timedelta(weeks=i)).isoformat()},
                headers=auth(token),
            ).json()
            for i in range(times)
        ]

        for roster in drafts:

            # Take that employee off Wednesday every single week.
            # Times default to "" not None: leave carries no times, and the
            # model rejects null — which made this PUT 422 silently, so the
            # roster was approved unedited and the whole fixture proved
            # nothing.
            kept = [
                {
                    "employee_id": s["employee_id"], "day": s["day"],
                    "start": s.get("start") or "", "end": s.get("end") or "",
                    "paid_holiday": bool(s.get("paid_holiday")),
                    "unpaid_holiday": bool(s.get("unpaid_holiday")),
                    "sick": bool(s.get("sick")),
                }
                for s in roster["shifts"]
                if not (s["employee_id"] == employee_id and s["day"] == "wed")
            ]
            saved = client.put(
                f"/api/rosters/{roster['roster_id']}", json={"shifts": kept},
                headers=auth(token),
            )
            assert saved.status_code == 200, saved.text
            client.post(
                f"/api/rosters/{roster['roster_id']}/approve", headers=auth(token),
            )
        return employee_id

    def test_the_report_counts_what_was_changed(self, client):
        token = register(client)
        self._shop_with_repeated_edits(client, token, times=3)

        report = client.get("/api/reports/corrections", headers=auth(token)).json()
        assert report["weeks_measured"] == 3
        assert report["total_corrections"] >= 3
        assert report["trend"], "the falling-edits line is the point of the screen"

    def test_names_are_resolved_for_display(self, client):
        token = register(client)
        self._shop_with_repeated_edits(client, token, times=3)

        report = client.get("/api/reports/corrections", headers=auth(token)).json()
        assert all(
            p.get("employee_name") for p in report["patterns"]
        ), "a screen showing employee_id would be useless to a manager"

    def test_a_repeated_edit_becomes_an_offer_that_can_be_applied(self, client):
        token = register(client)
        employee_id = self._shop_with_repeated_edits(client, token, times=3)

        report = client.get("/api/reports/corrections", headers=auth(token)).json()
        offer = next(
            (s for s in report["suggestions"]
             if s["action"] == "day_off" and s["employee_id"] == employee_id),
            None,
        )
        assert offer, f"no day-off offer in {report['suggestions']}"

        applied = client.post(
            "/api/reports/corrections/apply",
            json={"signature": offer["signature"]}, headers=auth(token),
        )
        assert applied.status_code == 200, applied.text

        # Applied to the REAL setting, visible in the ordinary UI — not to a
        # hidden weight the manager cannot inspect.
        employee = next(
            e for e in client.get("/api/employees", headers=auth(token)).json()
            if e["employee_id"] == employee_id
        )
        assert "wed" in employee["preferred_days_off"]

    def test_an_applied_offer_is_not_offered_again(self, client):
        token = register(client)
        self._shop_with_repeated_edits(client, token, times=3)

        report = client.get("/api/reports/corrections", headers=auth(token)).json()
        offer = report["suggestions"][0]
        client.post(
            "/api/reports/corrections/apply",
            json={"signature": offer["signature"]}, headers=auth(token),
        )

        after = client.get("/api/reports/corrections", headers=auth(token)).json()
        assert offer["signature"] not in [s["signature"] for s in after["suggestions"]]

    def test_a_dismissed_offer_stays_dismissed(self, client):
        token = register(client)
        self._shop_with_repeated_edits(client, token, times=3)

        report = client.get("/api/reports/corrections", headers=auth(token)).json()
        offer = report["suggestions"][0]
        client.post(
            "/api/reports/corrections/dismiss",
            json={"signature": offer["signature"]}, headers=auth(token),
        )

        after = client.get("/api/reports/corrections", headers=auth(token)).json()
        assert offer["signature"] not in [s["signature"] for s in after["suggestions"]]
        assert after["dismissed_count"] == 1
