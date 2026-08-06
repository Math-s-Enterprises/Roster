"""
Tests for 24-hour store templates + training-stats increment feature.
Covers:
  - HOURS regression (00:00-00:00 -> 400, /dev/reset restores defaults)
  - 24H mode auto-creates 3 templates + fully-open hours
  - Roster generation with templates spreads employees across Morning/Afternoon/Night
  - Custom template edits are reflected in next roster
  - /rosters/{id}/approve increments /ai/training-stats
  - Soft preference: employees tend to keep their template on regen
  - compute_weights covers dict path is exercised without exception
"""
import os
import pytest
import requests
from collections import Counter, defaultdict

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for ln in f:
            if ln.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = ln.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"
CREDS = {"email": "aneeshthimmapurmath@gmail.com", "password": "demo1234"}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@pytest.fixture(scope="module")
def h():
    r = requests.post(f"{API}/auth/login", json=CREDS, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    tok = r.json()["token"]
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def _reset_before_module(h):
    # Start clean: reset + seed demo employees + restore default hours
    requests.post(f"{API}/dev/reset", headers=h, timeout=60)
    yield
    # Cleanup: leave shop in usable state (non-24h with default hours)
    requests.put(f"{API}/shop", headers=h, json={
        "open_24h": False,
        "shift_templates": [],
        "hours": [{"day": d, "open": "09:00", "close": "21:00", "closed": False} for d in DAYS[:6]]
                 + [{"day": "sun", "open": "10:00", "close": "18:00", "closed": False}],
    }, timeout=30)


def _ensure_employees(h, min_count=5):
    emps = requests.get(f"{API}/employees", headers=h, timeout=30).json()
    if len(emps) < min_count:
        requests.post(f"{API}/seed-demo", headers=h, timeout=30)
        emps = requests.get(f"{API}/employees", headers=h, timeout=30).json()
    return emps


# ---------- HOURS REGRESSION ----------

def test_01_zero_hours_returns_400(h):
    zero = [{"day": d, "open": "00:00", "close": "00:00", "closed": False} for d in DAYS]
    r = requests.put(f"{API}/shop", headers=h, json={"open_24h": False, "shift_templates": [], "hours": zero}, timeout=30)
    assert r.status_code == 200, r.text
    _ensure_employees(h)
    r = requests.post(f"{API}/roster/generate", headers=h, json={"week_start": "2026-08-03"}, timeout=60)
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
    detail = r.json().get("detail", "")
    assert "Shop hours are not set" in detail, detail


def test_02_reset_restores_default_hours(h):
    r = requests.post(f"{API}/dev/reset", headers=h, timeout=60)
    assert r.status_code == 200
    shop = requests.get(f"{API}/shop", headers=h, timeout=30).json()
    hours = shop["hours"]
    by_day = {x["day"]: x for x in hours}
    for d in DAYS[:6]:
        assert by_day[d]["open"] == "09:00" and by_day[d]["close"] == "21:00", by_day[d]
    assert by_day["sun"]["open"] == "10:00" and by_day["sun"]["close"] == "18:00"


# ---------- 24H MODE ----------

def test_03_enable_24h_auto_creates_templates_and_hours(h):
    # Ensure no templates first
    requests.put(f"{API}/shop", headers=h, json={"shift_templates": [], "open_24h": False}, timeout=30)
    r = requests.put(f"{API}/shop", headers=h, json={"open_24h": True}, timeout=30)
    assert r.status_code == 200, r.text
    shop = r.json()
    tpls = shop.get("shift_templates") or []
    assert len(tpls) == 3, f"Expected 3 templates, got {len(tpls)}: {tpls}"
    by_name = {t["name"]: t for t in tpls}
    assert set(by_name.keys()) == {"Morning", "Afternoon", "Night"}
    assert by_name["Morning"]["start"] == "07:00" and by_name["Morning"]["end"] == "15:00" and by_name["Morning"]["min_staff"] == 2
    assert by_name["Afternoon"]["start"] == "15:00" and by_name["Afternoon"]["end"] == "23:00" and by_name["Afternoon"]["min_staff"] == 2
    assert by_name["Night"]["start"] == "23:00" and by_name["Night"]["end"] == "07:00" and by_name["Night"]["min_staff"] == 1
    # Hours should be fully-open every day
    for hr in shop["hours"]:
        assert hr["open"] == "00:00" and hr["close"] == "23:59" and not hr.get("closed"), hr


def test_04_roster_generation_spreads_across_templates(h):
    _ensure_employees(h, min_count=5)
    # Ensure 24h enabled
    requests.put(f"{API}/shop", headers=h, json={"open_24h": True}, timeout=30)
    r = requests.post(f"{API}/roster/generate", headers=h, json={"week_start": "2026-08-10"}, timeout=120)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    data = r.json()
    shifts = data.get("shifts") or []
    assert len(shifts) > 0, "No shifts generated"
    tpl_names = [sh.get("template_name") for sh in shifts]
    # All shifts should carry a template_name in the set
    assert all(n in {"Morning", "Afternoon", "Night"} for n in tpl_names), f"Unexpected template names: {set(tpl_names)}"
    counts = Counter(tpl_names)
    assert set(counts.keys()) == {"Morning", "Afternoon", "Night"}, f"Missing template coverage: {counts}"
    # No single template should have ALL employees
    total_emps_per_tpl = {n: len({sh["employee_id"] for sh in shifts if sh.get("template_name") == n}) for n in counts}
    all_emps = {sh["employee_id"] for sh in shifts}
    for n, cnt in total_emps_per_tpl.items():
        assert cnt < len(all_emps), f"Template {n} has ALL employees ({cnt}/{len(all_emps)})"


def test_05_custom_template_reflected_in_roster(h):
    _ensure_employees(h, min_count=5)
    custom = [
        {"template_id": "tpl_early", "name": "Early", "start": "05:00", "end": "13:00", "min_staff": 1},
        {"template_id": "tpl_late", "name": "Late", "start": "13:00", "end": "21:00", "min_staff": 1},
    ]
    r = requests.put(f"{API}/shop", headers=h, json={"open_24h": True, "shift_templates": custom}, timeout=30)
    assert r.status_code == 200, r.text
    assert len(r.json().get("shift_templates") or []) == 2

    r = requests.post(f"{API}/roster/generate", headers=h, json={"week_start": "2026-08-17"}, timeout=120)
    assert r.status_code == 200, r.text
    shifts = r.json().get("shifts") or []
    assert len(shifts) > 0
    names = {sh.get("template_name") for sh in shifts}
    assert names.issubset({"Early", "Late"}), f"Unexpected templates in roster: {names}"
    # Times should match
    for sh in shifts:
        if sh.get("template_name") == "Early":
            assert sh["start"] == "05:00" and sh["end"] == "13:00", sh
        elif sh.get("template_name") == "Late":
            assert sh["start"] == "13:00" and sh["end"] == "21:00", sh


# ---------- TRAINING ----------

def test_06_approve_increments_training_stats(h):
    # Reset to a clean baseline for stat counting
    requests.post(f"{API}/dev/reset", headers=h, timeout=60)
    _ensure_employees(h, min_count=5)
    # Switch to 24h to guarantee shifts
    requests.put(f"{API}/shop", headers=h, json={"open_24h": True, "shift_templates": []}, timeout=30)

    before = requests.get(f"{API}/ai/training-stats", headers=h, timeout=30).json()

    gen = requests.post(f"{API}/roster/generate", headers=h, json={"week_start": "2026-09-07"}, timeout=120)
    assert gen.status_code == 200, gen.text
    roster = gen.json()
    rid = roster["roster_id"]
    n_shifts = len(roster.get("shifts") or [])
    assert n_shifts > 0

    ap = requests.post(f"{API}/rosters/{rid}/approve", headers=h, timeout=30)
    assert ap.status_code == 200, ap.text

    after = requests.get(f"{API}/ai/training-stats", headers=h, timeout=30).json()
    assert after["total_shifts_learned"] > before["total_shifts_learned"], (before, after)
    assert after["employees_learned"] >= before["employees_learned"]
    assert after["approved_rosters"] >= before["approved_rosters"] + 1


def test_07_soft_preference_employees_keep_template_on_regen(h):
    """Best-effort: after approving a roster, regenerating a similar week should
    reuse each employee's dominant template for at least half of them."""
    _ensure_employees(h, min_count=5)
    # 24h with defaults
    requests.put(f"{API}/shop", headers=h, json={"open_24h": True, "shift_templates": []}, timeout=30)

    # Generate + approve week A
    g1 = requests.post(f"{API}/roster/generate", headers=h, json={"week_start": "2026-09-14"}, timeout=120)
    assert g1.status_code == 200, g1.text
    r1 = g1.json()
    ap = requests.post(f"{API}/rosters/{r1['roster_id']}/approve", headers=h, timeout=30)
    assert ap.status_code == 200

    # Compute each employee's dominant template from r1
    dom = {}
    per_emp = defaultdict(Counter)
    for sh in r1.get("shifts") or []:
        per_emp[sh["employee_id"]][sh.get("template_name")] += 1
    for emp, c in per_emp.items():
        dom[emp] = c.most_common(1)[0][0]
    assert dom, "No shifts in first roster"

    # Regenerate week B
    g2 = requests.post(f"{API}/roster/generate", headers=h, json={"week_start": "2026-09-21"}, timeout=120)
    assert g2.status_code == 200, g2.text
    r2 = g2.json()
    per_emp2 = defaultdict(Counter)
    for sh in r2.get("shifts") or []:
        per_emp2[sh["employee_id"]][sh.get("template_name")] += 1

    kept = 0
    considered = 0
    for emp, prior_tpl in dom.items():
        if emp in per_emp2:
            considered += 1
            new_dom = per_emp2[emp].most_common(1)[0][0]
            if new_dom == prior_tpl:
                kept += 1
    assert considered > 0, "No employees carried over into regen roster"
    ratio = kept / considered
    print(f"Soft-preference retention: {kept}/{considered} = {ratio:.2f}")
    # Acceptance: at least half keep their prior template
    assert ratio >= 0.5, f"Only {kept}/{considered} employees retained prior template (<50%)"


def test_08_training_stats_stable_after_multiple_approves(h):
    """Exercises compute_weights covers-dict path indirectly by regenerating
    and approving several rosters and ensuring stats endpoint doesn't throw."""
    _ensure_employees(h, min_count=5)
    requests.put(f"{API}/shop", headers=h, json={"open_24h": True, "shift_templates": []}, timeout=30)
    for ws in ["2026-10-05", "2026-10-12", "2026-10-19"]:
        g = requests.post(f"{API}/roster/generate", headers=h, json={"week_start": ws}, timeout=120)
        assert g.status_code == 200, g.text
        rid = g.json()["roster_id"]
        ap = requests.post(f"{API}/rosters/{rid}/approve", headers=h, timeout=30)
        assert ap.status_code == 200
    stats = requests.get(f"{API}/ai/training-stats", headers=h, timeout=30)
    assert stats.status_code == 200
    body = stats.json()
    for k in ("approved_rosters", "historical_rosters", "total_shifts_learned", "employees_learned"):
        assert k in body, body
        assert isinstance(body[k], int)


# ---------- HAPPY-PATH REGRESSION ----------

def test_09_non_24h_happy_path(h):
    # Turn off 24h + default hours + clear templates
    requests.post(f"{API}/dev/reset", headers=h, timeout=60)
    # /dev/reset restores hours but does NOT clear open_24h/templates — force non-24h explicitly
    requests.put(f"{API}/shop", headers=h, json={
        "open_24h": False,
        "shift_templates": [],
        "hours": [{"day": d, "open": "09:00", "close": "21:00", "closed": False} for d in DAYS[:6]]
                 + [{"day": "sun", "open": "10:00", "close": "18:00", "closed": False}],
    }, timeout=30)
    _ensure_employees(h, min_count=5)
    shop = requests.get(f"{API}/shop", headers=h, timeout=30).json()
    assert not shop.get("open_24h")
    r = requests.post(f"{API}/roster/generate", headers=h, json={"week_start": "2026-11-02"}, timeout=120)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data.get("shifts") or []) > 0
    assert data.get("total_hours", 0) > 0
