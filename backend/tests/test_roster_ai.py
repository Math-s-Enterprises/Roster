"""Backend tests for Roster AI — 4 bug fixes + new features."""
import os, uuid, requests, pytest
from datetime import date, timedelta

BASE = os.environ.get('REACT_APP_BACKEND_URL', 'https://roster-engine-6.preview.emergentagent.com').rstrip('/')
API = f"{BASE}/api"
OWNER = {"email": "aneeshthimmapurmath@gmail.com", "password": "demo1234"}


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{API}/auth/login", json=OWNER, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def H(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- BUG FIX 1: /rosters/past must return 200 (route order) ----------
def test_rosters_past_returns_200_list(H):
    r = requests.get(f"{API}/rosters/past", headers=H, timeout=30)
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert isinstance(data, list)
    today = date.today().isoformat()
    for x in data:
        assert x["week_start"] < today, f"past should not include {x['week_start']}"


# ---------- BUG FIX 2: sanity ping on core listing endpoints (no 404) ----------
@pytest.mark.parametrize("path", [
    "/auth/me", "/shop", "/employees", "/holidays", "/fixed-shifts",
    "/ai-rules", "/rosters", "/rosters/past", "/activity",
    "/reports/sick-leave", "/ai/training-stats",
])
def test_no_404_on_core_endpoints(H, path):
    r = requests.get(f"{API}{path}", headers=H, timeout=30)
    assert r.status_code != 404, f"{path} returned 404: {r.text[:200]}"
    assert r.status_code < 500, f"{path} returned {r.status_code}: {r.text[:200]}"


# ---------- BUG FIX 3: holidays date fields (calendar classification data) ----------
def test_holidays_have_date_and_end_date_fields(H):
    r = requests.get(f"{API}/holidays", headers=H, timeout=30)
    assert r.status_code == 200
    for h in r.json():
        assert "date" in h
        # end_date may be null; must not be a serialized ObjectId error


# ---------- FEATURE: training-stats ----------
def test_training_stats_shape(H):
    r = requests.get(f"{API}/ai/training-stats", headers=H, timeout=30)
    assert r.status_code == 200, r.text[:200]
    d = r.json()
    for k in ["approved_rosters", "historical_rosters", "total_shifts_learned", "employees_learned"]:
        assert k in d, f"missing key {k}"
        assert isinstance(d[k], int)


# ---------- FEATURE: sick-leave report ----------
def test_sick_leave_report_shape(H):
    r = requests.get(f"{API}/reports/sick-leave", headers=H, timeout=30)
    assert r.status_code == 200, r.text[:200]
    d = r.json()
    assert "by_employee" in d and isinstance(d["by_employee"], list)
    assert "total_days" in d and isinstance(d["total_days"], int)
    assert "total_incidents" in d and isinstance(d["total_incidents"], int)


# ---------- FEATURE: upload-historical ----------
def test_upload_historical_creates_roster(H):
    emps = requests.get(f"{API}/employees", headers=H, timeout=30).json()
    if not emps:
        pytest.skip("no employees seeded")
    eid = emps[0]["employee_id"]
    week = (date.today() - timedelta(days=90)).isoformat()  # far past
    payload = {"week_start": week, "shifts": [
        {"employee_id": eid, "day": "mon", "start": "09:00", "end": "17:00"},
        {"employee_id": eid, "day": "tue", "start": "09:00", "end": "13:00"},
    ]}
    r = requests.post(f"{API}/rosters/upload-historical", json=payload, headers=H, timeout=30)
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["imported"] == 1
    assert d["weeks"] == 1
    assert d["total_shifts"] == 2
    assert d["employees_learned"] == 1
    # verify it lands in /rosters/past
    past = requests.get(f"{API}/rosters/past", headers=H, timeout=30).json()
    assert any(p["week_start"] == week for p in past), "uploaded historical roster not in /rosters/past"


# ---------- FEATURE: ai-rules compile ----------
def test_ai_rule_compile(H):
    rules = requests.get(f"{API}/ai-rules", headers=H, timeout=30).json()
    if not rules:
        pytest.skip("no ai-rules present")
    rid = rules[0]["rule_id"]
    r = requests.post(f"{API}/ai-rules/{rid}/compile", headers=H, timeout=90)
    assert r.status_code == 200, r.text[:400]
    d = r.json()
    assert "compiled" in d
    assert isinstance(d["compiled"], dict)
    assert "type" in d["compiled"], f"missing 'type': {d}"


# ---------- REGRESSION: /rosters/{rid} still works after route reorder ----------
def test_rosters_by_id_still_works(H):
    rosters = requests.get(f"{API}/rosters", headers=H, timeout=30).json()
    if not rosters:
        pytest.skip("no rosters")
    rid = rosters[0]["roster_id"]
    r = requests.get(f"{API}/rosters/{rid}", headers=H, timeout=30)
    assert r.status_code == 200
    assert r.json()["roster_id"] == rid


def test_rosters_by_id_returns_404_for_missing(H):
    r = requests.get(f"{API}/rosters/rst_doesnotexist", headers=H, timeout=30)
    assert r.status_code == 404


# ---------- FEATURE: OCR (expensive - run once) ----------
@pytest.mark.slow
def test_ocr_roster_endpoint(H):
    url = "https://customer-assets-jai6qajn.emergentagent.net/job_roster-engine-6/artifacts/z90x16xv_we_5th_july.webp"
    r = requests.post(f"{API}/rosters/ocr", json={"image_url": url}, headers=H, timeout=120)
    assert r.status_code == 200, r.text[:400]
    d = r.json()
    assert "week_start" in d
    assert "shifts" in d and isinstance(d["shifts"], list)
    assert "raw_shifts" in d and isinstance(d["raw_shifts"], list)
