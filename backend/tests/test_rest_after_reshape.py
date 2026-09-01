"""Stretching a shift must not eat into somebody's 11 hours of rest.

Two passes rewrite shift times after the fill: `_close_short_hours` stretches
a neighbour over an hour that is one body short, and `_fit_contract_hours`
flexes a finish to land a salaried employee inside their band. Both check the
12-hour cap, the curfew and the weekly cap. Neither checked the REST GAP.

Reported from the reference shop: "Kyle's fri shift was changed from
10:00-19:00 to 10:00-20:00 to cover fri 19:00", and Kyle then had ten hours
before his next shift. The roster flagged him, which is how it was noticed —
the solver had produced a breach and then warned about its own work.

That is the daily rest entitlement in the Organisation of Working Time Act
(CLAUDE.md §1 rule 6), so it is law rather than preference. §1 is explicit
about the alternative: if keeping the rule means leaving an hour empty, leave
it empty and say so.
"""
from datetime import date, timedelta

import pytest

from app.services.demand import build_profile
from app.services.scheduler import DAYS, MIN_REST_HOURS, _RosterBuilder

WEEK = "2026-09-14"


def make_shop(**overrides):
    shop = {
        "shop_id": "s", "min_shift_hours": 4, "max_shift_hours": 12,
        "hours": [
            {"day": d, "open": "06:00", "close": "23:00", "closed": False}
            for d in DAYS
        ],
        "strict_days_off": False,
    }
    shop.update(overrides)
    return shop


def person(employee_id="kyle", **overrides):
    employee = {
        "employee_id": employee_id, "name": employee_id.title(),
        "role": "Shop Floor", "age": 30, "hourly_rate": 15.0,
        "max_weekly_hours": 40, "preferred_days_off": [],
        "departments": ["Shop Floor"], "is_active": True,
    }
    employee.update(overrides)
    return employee


def history(count=10):
    """Both shapes worked every week, so familiarity is never the blocker."""
    out = []
    for w in range(count):
        out.append({
            "week_start": (date(2026, 6, 22)
                           + timedelta(weeks=w)).isoformat(),
            "approved": True, "created_at": f"{w:03d}",
            "shifts": [
                {"employee_id": "kyle", "day": "fri",
                 "start": "10:00", "end": "19:00"},
                {"employee_id": "kyle", "day": "sat",
                 "start": "06:00", "end": "14:00"},
            ],
        })
    return out


def builder():
    team = [person()]
    hist = history()
    shop = make_shop()
    profile = build_profile(
        shop, hist, {e["employee_id"]: e["role"] for e in team})
    return _RosterBuilder(
        shop, team, [], [], [], WEEK, {}, profile, hist, None, None, None,
    )


class TestAStretchRespectsTheRestGap:
    def test_lengthening_a_finish_into_the_rest_window_is_refused(self):
        """Kyle's exact case.

        Friday 10:00-19:00 and Saturday 06:00-14:00 is an eleven-hour
        turnaround — legal, and only just. Pushing Friday's finish to 20:00
        to cover one short hour leaves ten, and the pass must refuse rather
        than cover the hour.
        """
        b = builder()
        b._record_shift("kyle", "fri", "10:00", "19:00")
        b._record_shift("kyle", "sat", "06:00", "14:00")

        assert b._rest_breach("kyle", "fri", "10:00", "20:00") is not None, (
            "the fixture is wrong: 20:00 to 06:00 should be a breach"
        )
        assert b._may_lengthen(
            b.result.shifts[0], "10:00", "20:00"
        ) is False, (
            "a stretch was allowed that leaves 10 hours before the next "
            "shift — the Organisation of Working Time Act requires 11"
        )

    def test_a_stretch_that_keeps_the_gap_is_still_allowed(self):
        """The guard must not refuse everything — that would silently disable
        the pass and look like a fix."""
        b = builder()
        b._record_shift("kyle", "fri", "10:00", "19:00")
        b._record_shift("kyle", "sat", "16:00", "22:00")
        assert b._may_lengthen(
            b.result.shifts[0], "10:00", "20:00"
        ) is True, "a lawful stretch was refused"

    def test_moving_a_start_earlier_is_checked_too(self):
        """Several advisories move the START back an hour — '16:00-00:00 to
        15:00-00:00'. That eats the gap from the PREVIOUS day, not the next,
        and `_rest_breach` checks both directions for exactly this reason."""
        b = builder()
        b._record_shift("kyle", "thu", "10:00", "23:00")
        b._record_shift("kyle", "fri", "10:00", "19:00")
        friday = b.result.shifts[1]
        assert b._may_lengthen(friday, "09:00", "19:00") is False, (
            "a start was moved earlier into the rest window after a late "
            "finish the day before"
        )

    def test_the_rest_rule_is_the_statutory_one(self):
        """Assert the real number, not the constant (§10)."""
        assert MIN_REST_HOURS == 11


class TestContractFittingRespectsItToo:
    def test_flexing_a_finish_for_a_contract_cannot_break_rest(self):
        """`_fit_contract_hours` extends a finish to land a salaried employee
        inside their band, and checked only the curfew. A contract is not a
        reason to break a statutory rest period."""
        team = [person("kyle", employment_type="full_time_contract",
                       contract_span_hours=40)]
        hist = history()
        shop = make_shop()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team})
        b = _RosterBuilder(
            shop, team, [], [], [], WEEK, {}, profile, hist,
            None, None, None,
        )
        b._record_shift("kyle", "fri", "10:00", "19:00")
        b._record_shift("kyle", "sat", "06:00", "14:00")
        b._fit_contract_hours()

        friday = next(s for s in b.result.shifts if s["day"] == "fri")
        saturday = next(s for s in b.result.shifts if s["day"] == "sat")
        gap = b._rest_breach("kyle", "fri", friday["start"], friday["end"])
        assert gap is None, (
            f"contract fitting left only {gap:.1f}h before "
            f"{saturday['start']} the next day"
        )
