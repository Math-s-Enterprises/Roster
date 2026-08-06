"""Regression tests for roster hours fix (zero-window shop hours bug)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback: read from frontend/.env
    with open("/app/frontend/.env") as f:
        for ln in f:
            if ln.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = ln.split("=", 1)[1].strip().rstrip("/")

API = f"{BASE_URL}/api"
CREDS = {"email": "aneeshthimmapurmath@gmail.com", "password": "demo1234"}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_HOURS = [{"day": d, "open": "09:00", "close": "21:00", "closed": False} for d in DAYS[:6]] + \
                [{"day": "sun", "open": "10:00", "close": "18:00", "closed": False}]


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json=CREDS, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _seed_employee(h):
    """Ensure at least one employee exists."""
    emps = requests.get(f"{API}/employees", headers=h, timeout=30).json()
    if emps:
        return
    # Trigger demo seed via reset (which also restores hours)
    requests.post(f"{API}/dev/reset", headers=h, timeout=30)


def test_01_reset_restores_default_hours(h):
    """REGRESSION FIX #2: /dev/reset should restore DEFAULT_HOURS."""
    r = requests.post(f"{API}/dev/reset", headers=h, timeout=60)
    assert r.status_code == 200, r.text

    shop = requests.get(f"{API}/shop", headers=h, timeout=30).json()
    hours = shop.get("hours") or []
    assert len(hours) == 7, f"Expected 7 days, got {len(hours)}: {hours}"

    # Check no zero-length days
    for hr in hours:
        # Compute minutes
        oh, om = map(int, hr["open"].split(":"))
        ch, cm = map(int, hr["close"].split(":"))
        span = (ch * 60 + cm) - (oh * 60 + om)
        assert span > 0, f"Day {hr['day']} has zero window: {hr}"

    # Mon-Sat should be 09:00-21:00 and Sun 10:00-18:00
    by_day = {x["day"]: x for x in hours}
    for d in ["mon", "tue", "wed", "thu", "fri", "sat"]:
        assert by_day[d]["open"] == "09:00" and by_day[d]["close"] == "21:00", by_day[d]
    assert by_day["sun"]["open"] == "10:00" and by_day["sun"]["close"] == "18:00", by_day["sun"]
    assert shop.get("min_shift_hours") == 4
    assert shop.get("max_shift_hours") == 9


def test_02_zero_hours_returns_400(h):
    """REGRESSION FIX #1: All-zero hours must return 400 with descriptive message."""
    zero_hours = [{"day": d, "open": "00:00", "close": "00:00", "closed": False} for d in DAYS]
    r = requests.put(f"{API}/shop", headers=h, json={"hours": zero_hours}, timeout=30)
    assert r.status_code == 200, r.text

    # Ensure employees exist so we don't short-circuit on "Add employees first"
    _seed_employee(h)

    r = requests.post(f"{API}/roster/generate", headers=h,
                      json={"week_start": "2026-08-03"}, timeout=60)
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    assert "Shop hours are not set" in detail, f"Unexpected detail: {detail}"
    assert "onboarding" in detail.lower() or "configure" in detail.lower()


def test_03_all_closed_returns_400(h):
    """All days marked closed should also return 400."""
    all_closed = [{"day": d, "open": "09:00", "close": "21:00", "closed": True} for d in DAYS]
    r = requests.put(f"{API}/shop", headers=h, json={"hours": all_closed}, timeout=30)
    assert r.status_code == 200, r.text

    _seed_employee(h)
    r = requests.post(f"{API}/roster/generate", headers=h,
                      json={"week_start": "2026-08-03"}, timeout=60)
    assert r.status_code == 400
    assert "Shop hours are not set" in r.json().get("detail", "")


def test_04_happy_path_generates_shifts(h):
    """REGRESSION FIX #3: Reset + valid hours + employees → shifts>0, hours>0."""
    # Reset restores DEFAULT_HOURS and seeds demo employees
    r = requests.post(f"{API}/dev/reset", headers=h, timeout=60)
    assert r.status_code == 200, r.text

    emps = requests.get(f"{API}/employees", headers=h, timeout=30).json()
    assert len(emps) > 0, "Reset should seed demo employees"

    shop = requests.get(f"{API}/shop", headers=h, timeout=30).json()
    open_spans = []
    for hr in shop["hours"]:
        oh, om = map(int, hr["open"].split(":"))
        ch, cm = map(int, hr["close"].split(":"))
        open_spans.append((ch * 60 + cm) - (oh * 60 + om))
    assert any(s > 0 for s in open_spans), f"No open days after reset: {shop['hours']}"

    r = requests.post(f"{API}/roster/generate", headers=h,
                      json={"week_start": "2026-08-03"}, timeout=120)
    assert r.status_code == 200, f"Generate failed: {r.status_code} {r.text}"
    data = r.json()
    shifts = data.get("shifts") or []
    total_hours = data.get("total_hours", 0)
    assert len(shifts) > 0, f"Expected shifts>0, got {len(shifts)}. Response: {data}"
    assert total_hours > 0, f"Expected total_hours>0, got {total_hours}"


def test_05_leaves_shop_in_working_state(h):
    """Cleanup: ensure hours are valid at end of run."""
    shop = requests.get(f"{API}/shop", headers=h, timeout=30).json()
    ok = False
    for hr in shop.get("hours", []):
        oh, om = map(int, hr["open"].split(":"))
        ch, cm = map(int, hr["close"].split(":"))
        if not hr.get("closed") and (ch * 60 + cm) - (oh * 60 + om) > 0:
            ok = True
            break
    if not ok:
        # Restore explicitly
        requests.put(f"{API}/shop", headers=h, json={"hours": DEFAULT_HOURS}, timeout=30)
        shop = requests.get(f"{API}/shop", headers=h, timeout=30).json()
    assert any((not hr.get("closed")) for hr in shop["hours"])
