"""A full-time contract is paid a weekly or a monthly salary.

The Employees screen asks for one figure and which it is per - week or month -
instead of an hourly rate. Every cost in the app is hours x hourly_rate, so the
server turns the salary into that rate when the employee is saved. These tests
pin the arithmetic, the rules about which fields go together, and that the rate
it produces really does cost a contracted week at exactly the salary through the
Hours and Wages report.
"""
import itertools

import pytest
from pydantic import ValidationError

from app.models import EmployeeIn
from app.services import contract_pay
from app.services.payroll_report import build_report
from tests.test_api import EMPLOYEE, auth, register

BOTH_OR_NEITHER = "Contract pay needs both a period (weekly or monthly) and a salary, or neither."

CONTRACT = {
    "name": "Aoife Manager", "role": "Manager", "age": 30, "hourly_rate": 15.0,
    "max_weekly_hours": 40, "employment_type": "full_time_contract",
}


def employee(**extra):
    return EmployeeIn(**{**CONTRACT, **extra})


# --- the arithmetic ---------------------------------------------------------------------
class TestArithmetic:
    def test_a_weekly_salary_is_already_a_week(self):
        assert contract_pay.weekly_equivalent("weekly", 700) == 700

    def test_a_month_is_52_twelfths_of_a_year_of_weeks_not_four_weeks(self):
        # 3000 / 4 = 750 would overstate the week by about 8%.
        assert contract_pay.weekly_equivalent("monthly", 3000) == pytest.approx(692.3077, abs=1e-4)
        assert contract_pay.weekly_equivalent("monthly", 4000) == pytest.approx(923.0769, abs=1e-4)

    def test_twelve_months_are_the_same_as_fifty_two_weeks(self):
        yearly_from_months = 12 * 3000
        yearly_from_weeks = 52 * contract_pay.weekly_equivalent("monthly", 3000)
        assert yearly_from_weeks == pytest.approx(yearly_from_months)

    def test_the_hourly_equivalents_for_the_two_examples(self):
        assert contract_pay.hourly_equivalent("weekly", 700, 40) == 17.5
        assert contract_pay.hourly_equivalent("monthly", 3000, 40) == 17.3077

    @pytest.mark.parametrize(
        "period,salary,hours",
        list(itertools.product(
            ["weekly", "monthly"], [1, 99.99, 700, 1234.56, 3000, 12000], [10, 37.5, 39, 40, 42.5, 48],
        )),
    )
    def test_a_full_contracted_week_costs_exactly_the_salary(self, period, salary, hours):
        rate = contract_pay.hourly_equivalent(period, salary, hours)
        weekly = contract_pay.weekly_equivalent(period, salary)
        assert rate * hours == pytest.approx(weekly, abs=0.005)

    def test_an_unknown_period_is_refused_not_guessed(self):
        with pytest.raises(ValueError):
            contract_pay.weekly_equivalent("daily", 100)
        with pytest.raises(ValueError):
            contract_pay.weekly_equivalent("", 100)

    @pytest.mark.parametrize("hours", [0, -5, None])
    def test_no_hours_cannot_be_divided_by(self, hours):
        with pytest.raises(ValueError):
            contract_pay.hourly_equivalent("weekly", 700, hours)


# --- the model -------------------------------------------------------------------------
class TestWhatIsKept:
    def test_a_monthly_contract_keeps_its_figures_and_gets_a_derived_rate(self):
        e = employee(contract_pay_period="monthly", contract_salary=3000)
        assert (e.contract_pay_period, e.contract_salary) == ("monthly", 3000)
        assert e.hourly_rate == 17.3077

    def test_a_weekly_contract(self):
        e = employee(contract_pay_period="weekly", contract_salary=700)
        assert (e.contract_pay_period, e.contract_salary) == ("weekly", 700)
        assert e.hourly_rate == 17.5

    def test_cents_are_kept(self):
        e = employee(contract_pay_period="monthly", contract_salary=2999.99)
        assert e.contract_salary == 2999.99

    def test_the_rate_follows_the_contracted_hours(self):
        assert employee(contract_pay_period="weekly", contract_salary=700, max_weekly_hours=37.5).hourly_rate == 18.6667
        assert employee(contract_pay_period="weekly", contract_salary=700, max_weekly_hours=35).hourly_rate == 20.0

    def test_omitted_hours_use_the_default_of_forty(self):
        payload = {k: v for k, v in CONTRACT.items() if k != "max_weekly_hours"}
        e = EmployeeIn(**payload, contract_pay_period="weekly", contract_salary=700)
        assert e.hourly_rate == 17.5

    def test_a_salary_replaces_whatever_hourly_rate_was_sent(self):
        for sent in (0, 1, 15, 99):
            e = employee(hourly_rate=sent, contract_pay_period="weekly", contract_salary=700)
            assert e.hourly_rate == 17.5

    def test_the_hourly_rate_is_still_a_required_field(self):
        """The screen sends it even for a salaried contract (and it is replaced), so
        this documents that an API client must too, rather than changing the contract."""
        payload = {k: v for k, v in CONTRACT.items() if k != "hourly_rate"}
        with pytest.raises(ValidationError) as caught:
            EmployeeIn(**payload, contract_pay_period="weekly", contract_salary=700)
        assert "hourly_rate" in str(caught.value)


class TestRecordsFromBeforeThisExisted:
    def test_a_contract_with_no_pay_keeps_its_hourly_rate(self):
        e = employee(hourly_rate=16.25)
        assert e.hourly_rate == 16.25
        assert (e.contract_pay_period, e.contract_salary) == (None, None)

    def test_hourly_and_student_staff_are_unaffected(self):
        for kind in ("hourly", "student"):
            e = EmployeeIn(**{**CONTRACT, "employment_type": kind, "hourly_rate": 12.5})
            assert e.hourly_rate == 12.5
            assert (e.contract_pay_period, e.contract_salary) == (None, None)


class TestOnlyAContractHasASalary:
    @pytest.mark.parametrize("kind", ["hourly", "student"])
    def test_a_salary_sent_for_somebody_else_is_cleared_not_kept(self, kind):
        e = EmployeeIn(**{**CONTRACT, "employment_type": kind, "hourly_rate": 12.5,
                          "contract_pay_period": "monthly", "contract_salary": 3000})
        assert (e.contract_pay_period, e.contract_salary) == (None, None)
        assert e.hourly_rate == 12.5            # and never derived for them

    def test_a_half_filled_pair_for_somebody_else_is_cleared_too(self):
        e = EmployeeIn(**{**CONTRACT, "employment_type": "hourly", "contract_pay_period": "weekly"})
        assert (e.contract_pay_period, e.contract_salary) == (None, None)


class TestBothOrNeither:
    def test_a_period_with_no_salary_is_refused(self):
        with pytest.raises(ValidationError) as caught:
            employee(contract_pay_period="weekly")
        assert BOTH_OR_NEITHER in str(caught.value)

    def test_a_salary_with_no_period_is_refused(self):
        with pytest.raises(ValidationError) as caught:
            employee(contract_salary=700)
        assert BOTH_OR_NEITHER in str(caught.value)

    def test_the_message_is_a_plain_sentence_without_a_value_error_prefix(self):
        with pytest.raises(ValidationError) as caught:
            employee(contract_salary=700)
        assert caught.value.errors()[0]["msg"] == BOTH_OR_NEITHER


class TestBadFigures:
    @pytest.mark.parametrize("salary", [0, -1, -3000])
    def test_a_salary_must_be_more_than_nothing(self, salary):
        with pytest.raises(ValidationError) as caught:
            employee(contract_pay_period="monthly", contract_salary=salary)
        assert "contract_salary" in {part for err in caught.value.errors() for part in err["loc"]}

    def test_a_salary_has_a_ceiling_that_catches_a_slipped_decimal(self):
        employee(contract_pay_period="monthly", contract_salary=1_000_000)
        with pytest.raises(ValidationError):
            employee(contract_pay_period="monthly", contract_salary=1_000_001)

    @pytest.mark.parametrize("period", ["daily", "yearly", "", "Weekly", "week"])
    def test_only_weekly_and_monthly_are_periods(self, period):
        with pytest.raises(ValidationError) as caught:
            employee(contract_pay_period=period, contract_salary=700)
        assert "contract_pay_period" in {part for err in caught.value.errors() for part in err["loc"]}

    def test_a_salary_that_is_not_a_number_is_refused(self):
        with pytest.raises(ValidationError):
            employee(contract_pay_period="weekly", contract_salary="a lot")


# --- through the API -------------------------------------------------------------------
class TestApi:
    def make(self, client, token, **extra):
        return client.post("/api/employees", json={**EMPLOYEE, "employment_type": "full_time_contract", **extra},
                           headers=auth(token))

    def test_a_monthly_contract_is_saved_and_listed(self, client):
        token = register(client)
        created = self.make(client, token, contract_pay_period="monthly", contract_salary=3000)
        assert created.status_code == 201, created.text
        body = created.json()
        assert (body["contract_pay_period"], body["contract_salary"]) == ("monthly", 3000)
        assert body["hourly_rate"] == 17.3077
        listed = client.get("/api/employees", headers=auth(token)).json()
        assert listed[0]["contract_salary"] == 3000 and listed[0]["contract_pay_period"] == "monthly"

    def test_a_weekly_contract_is_saved(self, client):
        token = register(client)
        body = self.make(client, token, contract_pay_period="weekly", contract_salary=700).json()
        assert (body["contract_pay_period"], body["contract_salary"], body["hourly_rate"]) == ("weekly", 700, 17.5)

    def test_changing_the_salary_changes_the_rate(self, client):
        token = register(client)
        employee_id = self.make(client, token, contract_pay_period="weekly", contract_salary=700).json()["employee_id"]
        updated = client.put(
            f"/api/employees/{employee_id}",
            json={**EMPLOYEE, "employment_type": "full_time_contract",
                  "contract_pay_period": "monthly", "contract_salary": 3000},
            headers=auth(token),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["hourly_rate"] == 17.3077
        assert updated.json()["contract_pay_period"] == "monthly"

    def test_changing_the_contracted_hours_changes_the_rate(self, client):
        token = register(client)
        employee_id = self.make(client, token, contract_pay_period="weekly", contract_salary=700).json()["employee_id"]
        updated = client.put(
            f"/api/employees/{employee_id}",
            json={**EMPLOYEE, "employment_type": "full_time_contract", "max_weekly_hours": 35,
                  "contract_pay_period": "weekly", "contract_salary": 700},
            headers=auth(token),
        )
        assert updated.json()["hourly_rate"] == 20.0

    def test_moving_somebody_off_a_contract_clears_the_salary_and_uses_the_hourly_rate_sent(self, client):
        token = register(client)
        employee_id = self.make(client, token, contract_pay_period="monthly", contract_salary=3000).json()["employee_id"]
        updated = client.put(
            f"/api/employees/{employee_id}",
            json={**EMPLOYEE, "employment_type": "hourly", "hourly_rate": 14.0},
            headers=auth(token),
        )
        body = updated.json()
        assert updated.status_code == 200, updated.text
        assert (body["contract_pay_period"], body["contract_salary"], body["hourly_rate"]) == (None, None, 14.0)
        stored = client.get("/api/employees", headers=auth(token)).json()[0]
        assert stored["contract_salary"] is None

    def test_a_contract_with_no_pay_is_still_accepted(self, client):
        """Records from before this existed must stay editable without being forced to
        invent a salary. The screen asks; the API does not insist."""
        token = register(client)
        created = self.make(client, token, hourly_rate=16.0)
        assert created.status_code == 201, created.text
        assert created.json()["hourly_rate"] == 16.0

    @pytest.mark.parametrize("half", [{"contract_pay_period": "weekly"}, {"contract_salary": 700}])
    def test_a_half_filled_pair_is_refused_with_a_clear_message(self, client, half):
        token = register(client)
        response = self.make(client, token, **half)
        assert response.status_code == 422
        assert any(BOTH_OR_NEITHER == d["msg"] for d in response.json()["detail"]), response.json()

    def test_a_bad_salary_names_the_field(self, client):
        token = register(client)
        response = self.make(client, token, contract_pay_period="weekly", contract_salary=0)
        assert response.status_code == 422
        assert any("contract_salary" in (d.get("loc") or []) for d in response.json()["detail"])

    def test_one_owners_staff_pay_is_not_visible_to_another(self, client):
        mine = register(client, email="mine@example.com")
        self.make(client, mine, contract_pay_period="monthly", contract_salary=3000)
        theirs = register(client, email="theirs@example.com")
        assert client.get("/api/employees", headers=auth(theirs)).json() == []


# --- the costs ---------------------------------------------------------------------------
class TestCostsFollowTheSalary:
    SHOP = {"breaks_are_paid": True}
    WEEK = "2026-10-05"    # a Monday

    def report(self, person, days):
        person = {**person.model_dump(), "employee_id": "e1"}
        shifts = [{"employee_id": "e1", "day": d, "start": "09:00", "end": "17:00"} for d in days]
        return build_report(
            shop=self.SHOP, employees=[person],
            rosters=[{"approved": True, "week_start": self.WEEK, "shifts": shifts}],
            start=self.WEEK, end="2026-10-11",
        )["rows"][0]

    def test_a_full_contracted_week_on_a_monthly_salary_costs_the_weekly_equivalent(self):
        row = self.report(employee(contract_pay_period="monthly", contract_salary=3000),
                          ["mon", "tue", "wed", "thu", "fri"])
        assert row["paid_hours"] == 40
        assert row["cost"] == pytest.approx(692.31, abs=0.01)

    def test_a_full_contracted_week_on_a_weekly_salary_costs_exactly_it(self):
        row = self.report(employee(contract_pay_period="weekly", contract_salary=700),
                          ["mon", "tue", "wed", "thu", "fri"])
        assert row["cost"] == pytest.approx(700, abs=0.01)

    def test_a_short_week_costs_proportionally_less_which_is_the_known_approximation(self):
        """Pinned so it is a stated limit rather than a surprise. A salary would not shrink."""
        row = self.report(employee(contract_pay_period="weekly", contract_salary=700), ["mon", "tue", "wed", "thu"])
        assert row["cost"] == pytest.approx(560, abs=0.01)

    def test_a_contract_with_no_salary_is_costed_exactly_as_before(self):
        row = self.report(employee(hourly_rate=16.0), ["mon", "tue", "wed", "thu", "fri"])
        assert row["cost"] == pytest.approx(640, abs=0.01)
