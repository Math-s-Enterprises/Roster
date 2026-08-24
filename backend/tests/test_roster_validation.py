"""Rules applied to hand-edited rosters.

Before this existed, the save route checked only shift length and
double-booking. Every other rule the generator enforces — curfew, hour caps,
availability, leave — could be walked straight past by dragging a cell.
"""
from app.services.roster_validation import validate_shifts

WEEK = "2026-08-10"   # a Monday


def make_shop(**overrides):
    shop = {"shop_id": "s", "min_shift_hours": 4, "max_shift_hours": 9}
    shop.update(overrides)
    return shop


def make_employee(eid="e1", **overrides):
    employee = {
        "employee_id": eid, "name": eid.title(), "role": "Floor Assistant",
        "age": 30, "hourly_rate": 13.0, "max_weekly_hours": 40,
        "preferred_days_off": [], "departments": ["Shop Floor"], "is_active": True,
    }
    employee.update(overrides)
    return employee


def shift(eid="e1", day="mon", start="09:00", end="17:00", **extra):
    return {"employee_id": eid, "day": day, "start": start, "end": end, **extra}


def check(shifts, employees=None, holidays=None, **kwargs):
    return validate_shifts(
        shifts,
        shop=make_shop(),
        employees=employees or [make_employee()],
        holidays=holidays or [],
        week_start=WEEK,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Refused outright
# ---------------------------------------------------------------------------
class TestBlocking:
    def test_a_clean_shift_passes(self):
        verdict = check([shift()])
        assert verdict.ok
        assert verdict.blocking == []

    def test_under_16_curfew_is_refused(self):
        """The rule the whole tool exists to enforce. A drag could put a
        fifteen-year-old on a 23:00 shift and it saved silently."""
        verdict = check(
            [shift(start="16:00", end="23:00")],
            employees=[make_employee(age=15)],
        )
        assert not verdict.ok
        assert "curfew" in verdict.blocking[0]

    def test_over_the_legal_maximum_is_refused(self):
        verdict = check([shift(start="06:00", end="20:00")])
        assert not verdict.ok
        assert "maximum shift length" in verdict.blocking[0]

    def test_rostering_somebody_on_booked_leave_is_refused(self):
        verdict = check(
            [shift(day="wed")],
            holidays=[{"scope": "employee", "employee_id": "e1",
                       "date": "2026-08-12", "label": "Holiday"}],
        )
        assert not verdict.ok
        assert "booked leave" in verdict.blocking[0]

    def test_a_leave_entry_on_a_leave_day_is_fine(self):
        """The holiday itself must not be refused for coinciding with the
        holiday that created it."""
        verdict = check(
            [shift(day="wed", start="", end="", paid_holiday=True)],
            holidays=[{"scope": "employee", "employee_id": "e1",
                       "date": "2026-08-12", "label": "Holiday"}],
        )
        assert verdict.ok

    def test_double_booking_is_refused(self):
        verdict = check([shift(), shift(start="18:00", end="22:00")])
        assert not verdict.ok
        assert "twice" in verdict.blocking[0]

    def test_a_shift_for_a_deleted_employee_is_refused(self):
        verdict = check([shift(eid="ghost")])
        assert not verdict.ok
        assert "no longer exists" in verdict.blocking[0]

    def test_a_sixth_working_day_is_refused(self):
        """Everybody gets two days off. A global rule, and one the solver had
        no notion of — it would give somebody all seven if the hours fitted."""
        shifts = [
            shift(day=d, start="09:00", end="14:00")
            for d in ("mon", "tue", "wed", "thu", "fri", "sat")
        ]
        verdict = check(shifts)
        assert not verdict.ok
        assert any("6 days" in b and "2 days off" in b for b in verdict.blocking)

    def test_five_days_is_fine(self):
        shifts = [
            shift(day=d, start="09:00", end="14:00")
            for d in ("mon", "tue", "wed", "thu", "fri")
        ]
        assert check(shifts).ok

    def test_going_over_contracted_hours_is_refused(self):
        """Contracted hours are what the employee agreed to and what payroll
        pays against — exceeding them is discovered at the till, not a call
        for the manager to wave through."""
        shifts = [
            shift(day=d, start="08:00", end="18:00")
            for d in ("mon", "tue", "wed", "thu", "fri")
        ]
        verdict = check(shifts, employees=[make_employee(max_weekly_hours=20)])
        assert not verdict.ok
        assert "against a 20h contract" in verdict.blocking[0]

    def test_a_42_5_hour_contract_is_the_ceiling(self):
        """Full-time is 42.5 PAID hours. Time on the floor is longer, because
        unpaid breaks sit on top — the check must compare paid against paid."""
        # Five 9h30 spans = 43.75h paid. Five days, so the two-days-off rule
        # is not what trips it — the hours are.
        shifts = [
            shift(day=d, start="09:00", end="18:30")
            for d in ("mon", "tue", "wed", "thu", "fri")
        ]
        verdict = check(shifts, employees=[make_employee(max_weekly_hours=42.5)])
        assert not verdict.ok
        assert any("42.5h contract" in b for b in verdict.blocking)

    def test_exactly_on_contract_is_allowed(self):
        """The limit is a ceiling to reach, not one to stay under."""
        # 8.75h span with a 45-minute break is exactly 8h paid.
        shifts = [
            shift(day=d, start="09:00", end="17:45")
            for d in ("mon", "tue", "wed", "thu", "fri")
        ]
        verdict = check(shifts, employees=[make_employee(max_weekly_hours=40)])
        assert verdict.ok, verdict.blocking

    def test_an_unfamiliar_shift_is_refused(self):
        """A night worker should not be handed a 06:00 start by a drag."""
        history = [{
            "week_start": "2026-08-03", "approved": True,
            "shifts": [{"employee_id": "e1", "day": "mon",
                        "start": "18:00", "end": "23:00"} for _ in range(10)],
        }]
        verdict = check([shift(start="06:00", end="14:00")], history_rosters=history)
        assert not verdict.ok
        assert "no previous" in verdict.blocking[0]

    def test_a_new_starter_can_be_rostered_anywhere(self):
        """Blocking unfamiliar shifts must not make a new hire unrosterable.
        With no history there is nothing for a shift to be unlike."""
        verdict = check([shift(start="06:00", end="14:00")], history_rosters=[])
        assert verdict.ok, verdict.blocking


# ---------------------------------------------------------------------------
# Salaried full-time contracts, measured on the floor
# ---------------------------------------------------------------------------
def full_timer(eid="e1", **overrides):
    return make_employee(
        eid, employment_type="full_time_contract", max_weekly_hours=42.5, **overrides
    )


def span_week(hours_per_day, days=("mon", "tue", "wed", "thu", "fri")):
    """Shifts of a given span, so totals are easy to reason about."""
    end_hour = 9 + int(hours_per_day)
    minutes = int(round((hours_per_day % 1) * 60))
    return [
        shift(day=d, start="09:00", end=f"{end_hour:02d}:{minutes:02d}")
        for d in days
    ]


class TestFullTimeContract:
    def test_over_42_5_on_the_floor_is_refused(self):
        # 5 x 9h = 45h on the floor, within the five-day limit.
        verdict = check(span_week(9), employees=[full_timer()])
        assert not verdict.ok
        assert any("42.5h contract" in b and "over" in b for b in verdict.blocking)

    def test_a_week_inside_the_band_is_accepted(self):
        # 5 x 8.5h = 42.5h exactly.
        verdict = check(span_week(8.5), employees=[full_timer()])
        assert verdict.ok, verdict.blocking

    def test_the_band_is_span_not_paid(self):
        """42.5h on the floor is roughly 38.75h paid once breaks come out.
        Judging the contract on paid hours would wave this straight through
        and then under-roster them every week."""
        verdict = check(span_week(8.5), employees=[full_timer()])
        assert verdict.ok
        # One more hour tips it over on span, though paid hours are still low.
        verdict = check(span_week(8.5) + [shift(day="sat", start="09:00", end="10:30")],
                        employees=[full_timer()])
        assert not verdict.ok

    def test_falling_short_of_the_minimum_is_refused(self):
        """They are paid the same either way, so a short week is hours the
        shop bought and did not use."""
        verdict = check(span_week(7), employees=[full_timer()])   # 35h
        assert not verdict.ok
        assert "short of the 41h minimum" in verdict.blocking[0]

    def test_a_week_broken_by_leave_may_come_in_short(self):
        """The one exception you asked for: holiday or sickness makes the
        band unreachable, and that is not the manager's fault."""
        verdict = check(
            span_week(7, ("mon", "tue", "wed")),
            employees=[full_timer()],
            holidays=[{"scope": "employee", "employee_id": "e1",
                       "date": "2026-08-13", "end_date": "2026-08-14",
                       "label": "Holiday"}],
        )
        assert verdict.ok, verdict.blocking

    def test_hourly_staff_are_not_held_to_a_minimum(self):
        """An hourly contract is a ceiling. Working under it is normal."""
        verdict = check(span_week(4), employees=[make_employee(max_weekly_hours=40)])
        assert verdict.ok, verdict.blocking


# ---------------------------------------------------------------------------
# Allowed, but recorded
# ---------------------------------------------------------------------------
class TestWarnings:
    def test_working_outside_a_stated_availability_window_warns(self):
        verdict = check(
            [shift(start="06:00", end="14:00")],
            employees=[make_employee(availability={"earliest_start": "10:00"})],
        )
        assert verdict.ok
        assert any("06:00" in w or "earliest" in w.lower() for w in verdict.warnings)

    def test_an_inactive_employee_warns(self):
        verdict = check([shift()], employees=[make_employee(is_active=False)])
        assert verdict.ok
        assert any("inactive" in w for w in verdict.warnings)

    def test_warnings_do_not_stop_other_shifts_being_checked(self):
        """A warning on one shift must not mask a blocking problem later."""
        verdict = check(
            [shift(eid="e1"), shift(eid="e2", day="tue", start="16:00", end="23:00")],
            employees=[make_employee("e1", is_active=False),
                       make_employee("e2", age=15)],
        )
        assert not verdict.ok
        assert any("curfew" in b for b in verdict.blocking)
        assert any("inactive" in w for w in verdict.warnings)


class TestMaximumShiftLength:
    """The cap is 12 hours.

    Asserted against the number, not just against ABSOLUTE_MAX_SHIFT_HOURS —
    a test written in terms of the constant passes whatever the constant
    happens to be, which is no protection against changing it by accident.
    """

    def test_the_cap_is_twelve_hours(self):
        from app.services.scheduler import ABSOLUTE_MAX_SHIFT_HOURS

        assert ABSOLUTE_MAX_SHIFT_HOURS == 12

    def test_twelve_hours_is_allowed(self):
        verdict = check([shift(start="08:00", end="20:00")])
        assert not [b for b in verdict.blocking if "maximum shift length" in b]

    def test_over_twelve_hours_is_refused(self):
        verdict = check([shift(start="08:00", end="20:30")])
        assert any("maximum shift length" in b for b in verdict.blocking)

    def test_the_locked_rule_states_the_real_number(self):
        """A rule that misstates what the product does is worse than none."""
        from app.services.shop_service import SYSTEM_RULES

        rule = next(r for r in SYSTEM_RULES if r["title"] == "Maximum shift length")
        assert "12 hours" in rule["description"]


class TestRestBetweenShifts:
    """Eleven consecutive hours off between finishing and starting again.

    Measured in real time, not clock time. A night finishing 07:00 Tuesday
    followed by a 17:00 Tuesday start is a TEN hour turnaround; comparing
    bare clock values would read it as thirty-four and wave through exactly
    the case the rule exists to catch.
    """

    def test_a_short_turnaround_is_refused(self):
        verdict = check([
            shift(day="mon", start="14:00", end="22:00"),
            shift(day="tue", start="06:00", end="14:00"),
        ])
        assert any("rest" in b for b in verdict.blocking)
        assert any("8.0h rest" in b for b in verdict.blocking)

    def test_a_full_rest_period_is_fine(self):
        verdict = check([
            shift(day="mon", start="09:00", end="17:00"),
            shift(day="tue", start="09:00", end="17:00"),
        ])
        assert not [b for b in verdict.blocking if "rest" in b]

    def test_exactly_eleven_hours_is_allowed(self):
        """The rule is 'at least', so the boundary itself passes."""
        verdict = check([
            shift(day="mon", start="12:00", end="20:00"),
            shift(day="tue", start="07:00", end="15:00"),
        ])
        assert not [b for b in verdict.blocking if "rest" in b]

    def test_an_overnight_shift_is_measured_from_when_it_really_ends(self):
        """23:30-07:00 Monday finishes on TUESDAY. A 17:00 Tuesday start is
        ten hours later, not thirty-four."""
        verdict = check([
            shift(day="mon", start="23:30", end="07:00"),
            shift(day="tue", start="17:00", end="23:00"),
        ])
        assert any("9.5h rest" in b or "10.0h rest" in b for b in verdict.blocking)

    def test_a_midnight_finish_then_a_morning_start_is_caught(self):
        """The commonest breach in the real rosters: close at midnight, back
        at 09:00 or 10:00."""
        verdict = check([
            shift(day="mon", start="16:00", end="00:00"),
            shift(day="tue", start="09:00", end="17:00"),
        ])
        assert any("9.0h rest" in b for b in verdict.blocking)

    def test_a_split_shift_is_not_a_rest_problem(self):
        """Two entries on one day are a double-booking, with its own message.
        Reporting '1h rest' would bury the real problem."""
        verdict = check([
            shift(day="mon", start="09:00", end="13:00"),
            shift(day="mon", start="14:00", end="18:00"),
        ])
        assert any("twice" in b for b in verdict.blocking)
        assert not [b for b in verdict.blocking if "rest" in b]

    def test_leave_does_not_count_as_a_shift(self):
        verdict = check([
            shift(day="mon", start="16:00", end="00:00"),
            {"employee_id": "e1", "day": "tue", "sick": True},
        ])
        assert not [b for b in verdict.blocking if "rest" in b]

    def test_two_people_do_not_interfere(self):
        verdict = check(
            [
                shift("e1", day="mon", start="14:00", end="22:00"),
                shift("e2", day="tue", start="06:00", end="14:00"),
            ],
            employees=[make_employee("e1"), make_employee("e2")],
        )
        assert not [b for b in verdict.blocking if "rest" in b]
