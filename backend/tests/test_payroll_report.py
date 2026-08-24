"""Hours and wages report.

Every test here is about a number a manager would hand to payroll, so they
assert exact figures rather than "greater than zero". A report that is
plausible but wrong is worse than one that is obviously broken — it gets
believed.
"""
import pytest

from app.services.payroll_report import build_report, shift_date

SHOP = {"shop_id": "s", "breaks_are_paid": False}
SHOP_PAID_BREAKS = {"shop_id": "s", "breaks_are_paid": True}


def employee(eid="e1", name="Jane", rate=13.0, **extra):
    return {
        "employee_id": eid, "name": name, "role": "Floor Assistant",
        "age": 30, "hourly_rate": rate, "max_weekly_hours": 40, **extra,
    }


def shift(eid="e1", day="mon", start="09:00", end="17:00", **extra):
    """A stored shift as the solver writes it — 8h span, 30m break."""
    return {
        "employee_id": eid, "day": day, "start": start, "end": end,
        "span_hours": 8.0, "break_minutes": 30, "paid_hours": 7.5, **extra,
    }


def roster(week_start, shifts, approved=True):
    return {"week_start": week_start, "approved": approved, "shifts": shifts}


def report(rosters, start, end, shop=SHOP, employees=None):
    return build_report(
        shop=shop, employees=employees or [employee()],
        rosters=rosters, start=start, end=end,
    )


# ---------------------------------------------------------------------------
# Dating a shift
# ---------------------------------------------------------------------------
class TestShiftDate:
    def test_each_day_gets_its_own_date(self):
        assert shift_date("2026-01-26", "mon").isoformat() == "2026-01-26"
        assert shift_date("2026-01-26", "sun").isoformat() == "2026-02-01"

    def test_a_bad_week_or_day_is_not_guessed(self):
        assert shift_date("not-a-date", "mon") is None
        assert shift_date("2026-01-26", "funday") is None


# ---------------------------------------------------------------------------
# Month boundaries
# ---------------------------------------------------------------------------
class TestMonthBoundary:
    """The week of 26 January runs into February.

    Counting the whole week into January would put days in a month they were
    not worked, and the total would not reconcile against a payslip.
    """

    WEEK = roster("2026-01-26", [
        shift(day=d) for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    ])

    def test_january_gets_only_its_own_days(self):
        out = report([self.WEEK], "2026-01-01", "2026-01-31")
        assert out["rows"][0]["days_worked"] == 6      # mon-sat
        assert out["rows"][0]["paid_hours"] == 45.0    # 6 x 7.5

    def test_february_gets_the_rest(self):
        out = report([self.WEEK], "2026-02-01", "2026-02-28")
        assert out["rows"][0]["days_worked"] == 1      # sun
        assert out["rows"][0]["paid_hours"] == 7.5

    def test_the_two_months_add_back_to_the_week(self):
        jan = report([self.WEEK], "2026-01-01", "2026-01-31")["totals"]
        feb = report([self.WEEK], "2026-02-01", "2026-02-28")["totals"]
        assert jan["paid_hours"] + feb["paid_hours"] == 52.5

    def test_the_range_is_inclusive_at_both_ends(self):
        out = report([self.WEEK], "2026-01-26", "2026-01-26")
        assert out["rows"][0]["days_worked"] == 1


# ---------------------------------------------------------------------------
# Breaks
# ---------------------------------------------------------------------------
class TestBreaks:
    """One shop setting moves every wage in the report."""

    WEEK = roster("2026-03-02", [shift(day="mon"), shift(day="tue")])

    def test_unpaid_breaks_are_deducted_and_shown(self):
        out = report([self.WEEK], "2026-03-02", "2026-03-08")
        row = out["rows"][0]
        assert out["breaks_are_paid"] is False
        assert row["span_hours"] == 16.0
        assert row["paid_hours"] == 15.0
        assert row["break_hours"] == 1.0
        assert row["cost"] == pytest.approx(15.0 * 13.0)

    def test_paid_breaks_pay_the_whole_span(self):
        out = report([self.WEEK], "2026-03-02", "2026-03-08", shop=SHOP_PAID_BREAKS)
        row = out["rows"][0]
        assert out["breaks_are_paid"] is True
        assert row["paid_hours"] == 16.0
        assert row["break_hours"] == 0.0
        assert row["cost"] == pytest.approx(16.0 * 13.0)

    def test_the_setting_changes_the_wage_bill(self):
        unpaid = report([self.WEEK], "2026-03-02", "2026-03-08")["totals"]["cost"]
        paid = report(
            [self.WEEK], "2026-03-02", "2026-03-08", shop=SHOP_PAID_BREAKS
        )["totals"]["cost"]
        assert paid > unpaid


# ---------------------------------------------------------------------------
# Only approved work is payable
# ---------------------------------------------------------------------------
class TestApprovedOnly:
    def test_a_draft_is_not_payable(self):
        """It would bill for hours nobody was told to work."""
        out = report(
            [roster("2026-03-02", [shift()], approved=False)],
            "2026-03-02", "2026-03-08",
        )
        assert out["rows"] == []
        assert out["totals"]["cost"] == 0

    def test_approving_makes_it_count(self):
        out = report([roster("2026-03-02", [shift()])], "2026-03-02", "2026-03-08")
        assert out["totals"]["paid_hours"] == 7.5


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------
class TestLeave:
    def test_paid_holiday_costs_wages(self):
        """Leaving it out understates the bill."""
        out = report(
            [roster("2026-03-02", [
                {"employee_id": "e1", "day": "mon", "paid_holiday": True,
                 "paid_hours": 8.0},
            ])],
            "2026-03-02", "2026-03-08",
        )
        row = out["rows"][0]
        assert row["paid_holiday_days"] == 1
        assert row["paid_holiday_hours"] == 8.0
        assert row["cost"] == pytest.approx(8.0 * 13.0)
        assert row["days_worked"] == 0, "a holiday is not a day worked"

    def test_unpaid_leave_and_sickness_cost_nothing(self):
        out = report(
            [roster("2026-03-02", [
                {"employee_id": "e1", "day": "mon", "unpaid_holiday": True},
                {"employee_id": "e1", "day": "tue", "sick": True},
            ])],
            "2026-03-02", "2026-03-08",
        )
        row = out["rows"][0]
        assert row["unpaid_holiday_days"] == 1
        assert row["sick_days"] == 1
        assert row["cost"] == 0
        assert row["span_hours"] == 0

    def test_somebody_with_nothing_is_left_out(self):
        out = report(
            [roster("2026-03-02", [shift()])], "2026-03-02", "2026-03-08",
            employees=[employee(), employee("e2", "Absent Al")],
        )
        assert [r["name"] for r in out["rows"]] == ["Jane"]


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------
class TestContractVariance:
    """A contract is a weekly promise, so it is judged weekly."""

    SALARIED = employee("e1", "Megan", employment_type="full_time_contract")

    def _week(self, week_start, hours_per_day):
        return roster(week_start, [
            {"employee_id": "e1", "day": d, "start": "09:00", "end": "17:00",
             "span_hours": hours_per_day, "paid_hours": hours_per_day - 0.5}
            for d in ("mon", "tue", "wed", "thu", "fri")
        ])

    def test_a_short_week_is_flagged(self):
        out = report(
            [self._week("2026-03-02", 8.0)],       # 40h, contract is 42.5
            "2026-03-02", "2026-03-08", employees=[self.SALARIED],
        )
        row = out["rows"][0]
        assert row["contract_hours"] == 42.5
        assert row["contract_expected"] == 42.5
        assert row["contract_variance"] == pytest.approx(-2.5)
        assert row["short_weeks"] == ["2026-03-02"]

    def test_a_week_inside_tolerance_is_not_short(self):
        out = report(
            [self._week("2026-03-02", 8.3)],       # 41.5h, within 1.5 of 42.5
            "2026-03-02", "2026-03-08", employees=[self.SALARIED],
        )
        assert out["rows"][0]["short_weeks"] == []

    def test_one_long_week_does_not_hide_one_short_week(self):
        """The reason this is weekly rather than a monthly average.

        38h then 47h averages to exactly the contracted 42.5. A monthly
        figure would report a clean nil variance and say nothing at all —
        but the person was two-and-a-half hours short one week and four and
        a half over the next, which is two separate problems.
        """
        out = report(
            [self._week("2026-03-02", 7.6), self._week("2026-03-09", 9.4)],
            "2026-03-02", "2026-03-15", employees=[self.SALARIED],
        )
        row = out["rows"][0]
        assert row["contract_expected"] == 85.0
        assert row["contract_variance"] == pytest.approx(0.0), "the average looks fine"
        assert row["short_weeks"] == ["2026-03-02"], "the short week still shows"

    def test_a_partial_week_is_not_judged(self):
        """Half a week is short by definition — flagging it cries wolf at
        every month boundary."""
        out = report(
            [self._week("2026-03-02", 8.5)],
            "2026-03-04", "2026-03-08", employees=[self.SALARIED],
        )
        row = out["rows"][0]
        assert row["contract_expected"] is None
        assert row["short_weeks"] == []

    def test_hourly_staff_have_no_contract_figures(self):
        out = report([self._week("2026-03-02", 8.0)], "2026-03-02", "2026-03-08")
        assert out["rows"][0]["contract_hours"] is None


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------
class TestTotals:
    def test_totals_match_the_rows(self):
        out = report(
            [roster("2026-03-02", [shift(), shift("e2", day="tue")])],
            "2026-03-02", "2026-03-08",
            employees=[employee(), employee("e2", "Kyle", rate=15.0)],
        )
        assert out["totals"]["people"] == 2
        assert out["totals"]["paid_hours"] == pytest.approx(
            sum(r["paid_hours"] for r in out["rows"])
        )
        assert out["totals"]["cost"] == pytest.approx(7.5 * 13.0 + 7.5 * 15.0)

    def test_a_backwards_range_is_read_the_right_way_round(self):
        out = report([roster("2026-03-02", [shift()])], "2026-03-08", "2026-03-02")
        assert out["start"] == "2026-03-02"
        assert out["totals"]["paid_hours"] == 7.5

    def test_a_malformed_date_is_refused_not_guessed(self):
        with pytest.raises(ValueError):
            report([], "March", "2026-03-08")
