"""A caution names the field the manager has to edit, not just a number.

FOUR different fields can set somebody's weekly ceiling, and the Employees
screen presents all of them as "hours":

    contracted hours        salaried staff (max_weekly_hours is ignored)
    summer-break limit      a student, inside their configured break
    term-time limit         a student, outside it
    weekly limit            everybody else

The bug this protects against is not arithmetic. The shop owner raised a
student's weekly limit from 20 to 25, returned to the roster, pressed
Re-check, and saw the identical caution — because that week fell inside the
student's summer break and the break's own 20h figure was the binding one.
The app was right. It was also silent, so the only available conclusion was
that the page was stale, and the next hour went into looking for a caching
bug that did not exist.

    "Fionn is rostered 22.0h against a 20h limit"

is true and useless. Which 20h is the whole question.
"""
from app.services import availability as avail, compliance

WEEK = "2026-09-07"          # a Monday


def student(**overrides):
    employee = {
        "employee_id": "e1", "name": "Fionn", "role": "Cashier", "age": 19,
        "hourly_rate": 14.0, "employment_type": "student",
        "max_weekly_hours": 25.0, "is_active": True,
        "preferred_days_off": [], "departments": ["Shop Floor"],
    }
    employee.update(overrides)
    return employee


def shifts_totalling_22h(employee_id="e1"):
    """Three days that add up to well over any of the caps here."""
    return [
        {"employee_id": employee_id, "day": day, "start": "09:00", "end": "17:00"}
        for day in ("mon", "tue", "wed")
    ]


def messages(employee):
    breaches = compliance.audit(
        shifts_totalling_22h(), shop={"shop_id": "s"}, employees=[employee],
        week_start=WEEK, holidays=[],
    )
    return [b["message"] for b in breaches if b["rule"] == "weekly_hours"]


class TestTheCapKnowsWhereItCameFrom:
    def test_a_summer_break_limit_is_named_as_one(self):
        who = student(summer_break={
            "start_date": "2026-06-01", "end_date": "2026-09-30",
            "max_weekly_hours": 20.0,
        })
        cap, source = avail.weekly_hour_cap_explained(who, WEEK)

        assert cap == 20.0, (
            f"the break figure is the binding one inside the break — got {cap}"
        )
        assert source == "their summer-break limit", source

    def test_a_term_time_limit_is_named_as_one(self):
        """Same student, a week OUTSIDE the break."""
        who = student(
            term_time_max_hours=12.0,
            summer_break={"start_date": "2026-06-01", "end_date": "2026-08-31",
                          "max_weekly_hours": 20.0},
        )
        cap, source = avail.weekly_hour_cap_explained(who, WEEK)

        assert cap == 12.0, f"term time applies in September — got {cap}"
        assert source == "their term-time limit", source

    def test_an_ordinary_weekly_limit_is_named_plainly(self):
        cap, source = avail.weekly_hour_cap_explained(
            student(employment_type="hourly"), WEEK)
        assert (cap, source) == (25.0, "their weekly limit")

    def test_the_explanation_never_disagrees_with_the_cap(self):
        """`weekly_hour_cap` is this function without the words. If the two
        ever diverge, the caution names a field that did not decide
        anything."""
        for who in (
            student(),
            student(summer_break={"start_date": "2026-06-01",
                                  "end_date": "2026-09-30",
                                  "max_weekly_hours": 20.0}),
            student(term_time_max_hours=12.0),
            student(employment_type="hourly"),
            student(employment_type="full_time_contract",
                    contract_span_hours=42.5),
        ):
            assert (
                avail.weekly_hour_cap(who, WEEK)
                == avail.weekly_hour_cap_explained(who, WEEK)[0]
            ), who


class TestTheCautionSaysWhichFieldToEdit:
    def test_it_names_the_summer_break_and_says_the_weekly_limit_is_moot(self):
        who = student(summer_break={
            "start_date": "2026-06-01", "end_date": "2026-09-30",
            "max_weekly_hours": 20.0,
        })
        lines = messages(who)

        assert lines, "22h against a 20h cap has to be flagged"
        assert "summer-break limit" in lines[0], (
            f"the manager needs to know WHICH limit, because that is the "
            f"field they have to change — got {lines[0]}"
        )
        assert "25h does not apply" in lines[0], (
            f"they had just edited the weekly limit and it did nothing; "
            f"saying so is the difference between a clear answer and an hour "
            f"spent hunting a caching bug — got {lines[0]}"
        )

    def test_an_ordinary_employee_gets_no_confusing_aside(self):
        """The clause only earns its place when two numbers disagree."""
        who = student(employment_type="hourly", max_weekly_hours=20.0)
        lines = messages(who)

        assert lines, "22h against a 20h cap has to be flagged"
        assert "does not apply" not in lines[0], (
            f"there is no second figure here, so explaining one would be "
            f"noise — got {lines[0]}"
        )
        assert "their weekly limit" in lines[0], lines[0]
