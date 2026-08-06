"""Verify paid_holiday shifts are excluded from total_hours but still counted in labor_cost."""
import os, requests, pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://roster-engine-6.preview.emergentagent.com").rstrip("/")
EMAIL = "aneeshthimmapurmath@gmail.com"
PASSWORD = "demo1234"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def employee(client):
    r = client.get(f"{BASE}/api/employees")
    assert r.status_code == 200
    emps = r.json()
    if emps:
        return emps[0]
    # Create one
    payload = {"name": "TEST_Emp", "role": "staff", "hourly_rate": 20.0,
               "max_hours_per_week": 40, "min_hours_per_week": 0,
               "availability": {d: [{"start": "08:00", "end": "20:00"}] for d in
                                ["mon","tue","wed","thu","fri","sat","sun"]}}
    r = client.post(f"{BASE}/api/employees", json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.fixture(scope="module")
def roster_id(client, employee):
    # Find a Monday
    from datetime import date, timedelta
    d = date.today()
    while d.weekday() != 0:
        d += timedelta(days=1)
    r = client.post(f"{BASE}/api/roster/generate", json={"week_start": d.isoformat()})
    assert r.status_code == 200, r.text
    data = r.json()
    rid = data.get("roster_id") or data.get("id")
    assert rid, data
    return rid


def _put(client, rid, emp_id, flags):
    shift = {"employee_id": emp_id, "day": "mon", "start": "09:00", "end": "17:00", **flags}
    return client.put(f"{BASE}/api/rosters/{rid}", json={"shifts": [shift]})


def test_paid_holiday_excluded_from_total_hours(client, roster_id, employee):
    r = _put(client, roster_id, employee["employee_id"], {"paid_holiday": True})
    assert r.status_code == 200, r.text
    data = r.json()
    print("paid_holiday response:", {"total_hours": data.get("total_hours"), "labor_cost": data.get("labor_cost")})
    assert data["total_hours"] == 0.0, f"paid_holiday should NOT count toward total_hours; got {data['total_hours']}"
    assert data["labor_cost"] > 0, f"paid_holiday should still incur labor_cost; got {data['labor_cost']}"


def test_unpaid_holiday_excluded_from_both(client, roster_id, employee):
    r = _put(client, roster_id, employee["employee_id"], {"unpaid_holiday": True})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_hours"] == 0.0
    assert data["labor_cost"] == 0.0


def test_sick_excluded_from_total_hours(client, roster_id, employee):
    r = _put(client, roster_id, employee["employee_id"], {"sick": True})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_hours"] == 0.0
    # sick still incurs labor_cost per current logic (not unpaid)
    assert data["labor_cost"] > 0


def test_plain_shift_counts_normally(client, roster_id, employee):
    r = _put(client, roster_id, employee["employee_id"], {})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_hours"] == 8.0
    assert data["labor_cost"] > 0
