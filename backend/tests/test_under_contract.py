"""Who is below their contracted hours — derived, and derived once.

Salaried hours are OWED. The payslip is the same whether somebody works 41
or 42.5, so a short week is money the shop paid for and did not use, and the
manager wants to know before they approve it.

Two things this protects.

DERIVED, NOT STORED (§5). The answer changes when the MANAGER changes a
contract, not when the roster changes. It used to be computed inside the
solver from state that only exists mid-generation, so raising somebody's
contract left the roster page still reporting the figure from whenever the
week was last generated — which is exactly the staleness the Re-check button
is for.

ONE IMPLEMENTATION. The solver calls the same function the roster page does.
Two versions of "who is below their band" is the §11 trap, and a bad one to
get wrong: the generator and the roster page would tell the manager
different things about the same week with no way to know which was right.
"""
from datetime import date, timedelta

from app.services import compliance

WEEK = "2026-08-17"          # a Monday
DAYS_OF = ["mon", "tue", "wed", "thu", "fri"]


def full_timer(employee_id="e1", hours=40, **overrides):
    """A salaried contract written in hours ON THE FLOOR (§8).

    `employment_type` is what decides this, not a job title or a rate —
    `contract_span_band` returns None for anything else, and an employee
    without it is silently never reported. The band is (hours - tolerance,
    hours), so a 40h contract has a 38.5h minimum by default.
    """
    employee = {
        "employee_id": employee_id, "name": employee_id.title(),
        "role": "Supervisor", "age": 30, "hourly_rate": 0.0,
        "employment_type": "full_time_contract", "contract_span_hours": hours,
        "max_weekly_hours": 48, "is_active": True,
        "preferred_days_off": [], "departments": ["Shop Floor"],
    }
    employee.update(overrides)
    return employee


def shift(employee_id, day, start="09:00", end="17:00", **extra):
    entry = {
        "employee_id": employee_id, "day": day, "start": start, "end": end,
    }
    entry.update(extra)
    return entry


def leave(employee_id, on):
    return {"scope": "employee", "employee_id": employee_id, "date": on}


def run(shifts, employees, holidays=None, week=WEEK):
    return compliance.under_contract(
        shifts, employees=employees, shop={"shop_id": "s"},
        week_start=week, holidays=holidays or [])


class TestItReportsAShortWeek:
    def test_a_full_timer_two_days_short_is_named(self):
        who = full_timer(hours=40)
        result = run([shift("e1", d) for d in ("mon", "tue", "wed")], [who])

        assert len(result) == 1, (
            f"three 8-hour days against a 40h contract is 16h short and "
            f"should be reported — got {result}"
        )
        assert result[0]["rostered_hours"] == 24.0
        assert result[0]["short_hours"] > 0

    def test_a_full_week_is_not_reported(self):
        who = full_timer(hours=40)
        assert run([shift("e1", d) for d in DAYS_OF], [who]) == []

    def test_an_hourly_employee_is_never_reported(self):
        """Their contract is a ceiling, not a floor. Reporting against it
        flagged the entire team every week."""
        hourly = full_timer("e2", employment_type="hourly",
                            contract_span_hours=None, hourly_rate=15.0)
        assert run([shift("e2", "mon")], [hourly]) == []


class TestLeaveIsScopedToTheWeekBeingLooked_At:
    """The bug this replaced: the solver skipped anyone with ANY leave date
    on record, because the index it consulted holds every date the shop has
    ever booked for them — not just this week's. Somebody with a holiday
    booked in December was therefore never reported as under contract in
    August, silently, for the rest of the year.

    The docstring always said "anyone with booked leave THAT WEEK".
    """

    def test_leave_in_this_week_excuses_the_short_week(self):
        who = full_timer(hours=40)
        result = run(
            [shift("e1", d) for d in ("mon", "tue", "wed")], [who],
            holidays=[leave("e1", "2026-08-20")],      # the Thursday
        )
        assert result == [], (
            "a week broken by holiday cannot reach the band, and saying so "
            "every time buries the weeks the shop simply did not roster them"
        )

    def test_leave_in_a_DIFFERENT_week_does_not(self):
        who = full_timer(hours=40)
        far_off = (date.fromisoformat(WEEK) + timedelta(days=90)).isoformat()
        result = run(
            [shift("e1", d) for d in ("mon", "tue", "wed")], [who],
            holidays=[leave("e1", far_off)],
        )
        assert len(result) == 1, (
            f"a holiday booked three months away says nothing about THIS "
            f"week, and must not suppress the report — got {result}"
        )


class TestTheSolverAndThePageAgree:
    def test_the_solver_returns_what_compliance_returns(self):
        """Not a mock: the solver is run for real and its stored answer is
        compared against calling the shared function on its own output. If
        the two ever diverge the manager gets two different numbers for one
        week."""
        from app.services.demand import build_profile
        from app.services.scheduler import DAYS, solve_roster

        shop = {
            "shop_id": "s", "min_shift_hours": 4, "max_shift_hours": 12,
            "hours": [{"day": d, "open": "08:00", "close": "20:00",
                       "closed": False} for d in DAYS],
            "strict_days_off": False,
        }
        team = [full_timer("e1", hours=40), full_timer("e2", hours=40),
                full_timer("e3", hours=40)]
        history = [
            {
                "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
                "approved": True,
                "shifts": [shift(f"e{i}", d, "08:00", "16:00")
                           for d in DAYS for i in (1, 2)],
            }
            for w in range(24)
        ]
        profile = build_profile(
            shop, history, {e["employee_id"]: e["role"] for e in team})
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile,
            history_rosters=history)

        recomputed = compliance.under_contract(
            result["shifts"], employees=team, shop=shop,
            week_start=WEEK, holidays=[])

        assert (
            {(u["employee_id"], u["short_hours"]) for u in result["under_contract"]}
            == {(u["employee_id"], u["short_hours"]) for u in recomputed}
        ), (
            f"the solver stored {result['under_contract']} but the roster "
            f"page would show {recomputed} — the same week cannot have two "
            f"answers"
        )
