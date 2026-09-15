"""The previous week and unrelated leave must not change this week's truth."""
from datetime import date, timedelta

import pytest

from app.services import compliance
from app.services.demand import build_profile
from app.services.scheduler import DAYS, _RosterBuilder
from tests.test_api import register, auth, _future_monday


WEEK = "2026-08-17"


def builder(holidays=None, history=None):
    shop = {"hours": [{"day": d, "open": "09:00", "close": "21:00", "closed": i > 4}
                      for i, d in enumerate(DAYS)]}
    employee = {"employee_id": "e", "name": "Example", "role": "Supervisor", "age": 30,
                "hourly_rate": 0, "employment_type": "full_time_contract", "contract_span_hours": 40,
                "max_weekly_hours": 48, "is_active": True, "preferred_days_off": []}
    if history is None:
        history = [{"week_start": w, "approved": True, "shifts": [
            {"employee_id": "e", "day": d, "start": "09:00", "end": "17:00"} for d in DAYS[:4]]}
            for w in ("2026-07-20", "2026-07-27", "2026-08-03", "2026-08-10")]
    profile = build_profile(shop, history, {"e": "Supervisor"}, for_week=WEEK)
    return _RosterBuilder(shop, [employee], holidays or [], [], [], WEEK, {}, profile, history_rosters=history)


@pytest.mark.parametrize("on", ["2026-01-01", "2026-12-01"])
def test_leave_outside_week_does_not_disable_either_contract_pass(on):
    holidays = [{"scope": "employee", "employee_id": "e", "date": on}]
    top_up = builder(holidays)
    top_up._top_up_contracts(top_up._trading_days())
    assert top_up.span_used["e"] == 40
    fitting = builder(holidays)
    for day in DAYS[:4]:
        fitting._record_shift("e", day, "09:00", "17:00")
    fitting._fit_contract_hours()
    assert fitting.span_used["e"] == 38.5


@pytest.mark.parametrize("start,end", [("2026-08-18", "2026-08-18"), ("2026-08-16", "2026-08-17")])
def test_leave_overlapping_week_still_skips_both_contract_passes(start, end):
    holidays = [{"scope": "employee", "employee_id": "e", "date": start, "end_date": end}]
    top_up = builder(holidays)
    top_up._top_up_contracts(top_up._trading_days())
    assert top_up.span_used.get("e", 0) == 0
    fitting = builder(holidays)
    for day in DAYS[:4]:
        fitting._record_shift("e", day, "09:00", "17:00")
    fitting._fit_contract_hours()
    assert fitting.span_used["e"] == 32


def test_final_tidy_removes_a_contract_extension_made_redundant_by_coverage():
    fitting = builder()
    fitting.span_bands["e"] = (41, 42.5)
    for day, start, end in (
        ("sun", "16:00", "00:00"),
        ("mon", "09:00", "17:00"),
        ("tue", "09:00", "17:00"),
        ("wed", "07:30", "16:00"),
        ("thu", "09:00", "17:00"),
    ):
        fitting._record_shift("e", day, start, end)

    fitting._fit_contract_hours()
    sunday = next(s for s in fitting.result.shifts if s["day"] == "sun")
    assert sunday["end"] == "00:30"  # the contract initially needed 0.5h

    tuesday = next(s for s in fitting.result.shifts if s["day"] == "tue")
    fitting._reshape_shift(tuesday, "18:00")  # later coverage supplied 1h
    fitting._trim_redundant_contract_extensions()

    assert sunday["end"] == "00:00"
    assert fitting.span_used["e"] == 41.5


def night(**extra):
    return {"employee_id": "e", "day": "sun", "start": "22:00", "end": "06:00", **extra}


def previous(shifts, **extra):
    return {"week_start": "2026-08-10", "approved": True, "shifts": shifts, **extra}


MONDAY = {"hours": [{"day": "mon", "open": "00:00", "close": "06:00"}]}


def gaps(shifts, history):
    return compliance.uncovered_hours(shifts, shop=MONDAY, week_start=WEEK, history_rosters=history)


def test_actual_previous_sunday_covers_monday_without_this_sundays_shift():
    assert gaps([], [previous([night()])]) == []


def test_known_previous_week_without_night_cannot_borrow_next_sunday():
    assert [g["hour"] for g in gaps([night()], [previous([])])] == list(range(6))
    assert builder(history=[previous([])]).wrap_week is False


def test_missing_or_unapproved_history_keeps_repeating_rota_fallback():
    assert gaps([night()], []) == []
    assert gaps([night()], [previous([], approved=False)]) == []
    assert builder(history=[]).wrap_week is True


def test_previous_leave_and_unrelated_weeks_cannot_supply_carry_in():
    history = [previous([night(sick=True)]), previous([night()], week_start="2026-08-03")]
    assert len(gaps([], history)) == 6


def test_duplicate_previous_week_uses_newest_record_for_both_checks():
    history = [previous([night()], created_at="2026-08-01"), previous([], created_at="2026-08-02")]
    assert len(gaps([night()], history)) == 6
    b = builder(history=history)
    assert b.carried_in == 0 and b.wrap_week is False


@pytest.mark.parametrize("has_carry", [True, False])
def test_read_edit_and_approval_share_previous_week_context(client, has_carry):
    # Seed only this account's shop in the fixture database. The other shop's
    # previous roster must not affect the result.
    import asyncio
    from app import db
    token = register(client)
    other = register(client, email="other@example.com")
    week = _future_monday()
    prior = (date.fromisoformat(week) - timedelta(days=7)).isoformat()
    async def seed():
        shops = await db.shops.find({}).to_list(10)
        shop = shops[0]
        await db.shops.update_one({"shop_id": shop["shop_id"]}, {"$set": MONDAY})
        await db.rosters.insert_one({"shop_id": shop["shop_id"], "roster_id": "prior",
                                    "week_start": prior, "approved": True, "shifts": [night()] if has_carry else []})
        await db.rosters.insert_one({"shop_id": shops[1]["shop_id"], "roster_id": "other-prior",
                                    "week_start": prior, "approved": True, "shifts": [] if has_carry else [night()]})
        await db.rosters.insert_one({"shop_id": shop["shop_id"], "roster_id": "target",
                                    "week_start": week, "version": "v1.0", "approved": False, "shifts": []})
    asyncio.run(seed())
    read = client.get("/api/rosters/target", headers=auth(token))
    assert read.status_code == 200
    assert len(read.json()["gaps"]) == (0 if has_carry else 6)
    edited = client.put("/api/rosters/target", headers=auth(token), json={"shifts": []})
    assert edited.status_code == 200, edited.text
    assert len(edited.json()["gaps"]) == (0 if has_carry else 6)
    approval = client.post("/api/rosters/target/approve", headers=auth(token))
    assert approval.status_code == (200 if has_carry else 409), approval.text
    assert client.get("/api/rosters/target", headers=auth(other)).status_code == 404
