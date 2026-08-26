"""The under-16 curfew is not the manager's to override.

Everything else in a roster is a judgement about the business: contracted
hours, a six-day week, a short turnaround. The manager carries the
consequence, so the manager gets the decision.

Rostering a child outside 08:00-19:00 is not that. It is criminal law, and a
signed-off record of it with somebody's password against it is discoverable.
So it is refused with or without the password — and the refusal says so
plainly, rather than implying the right credentials would help.
"""
from app.services.compliance import HARD_FLOOR, audit, blocking, group_by_employee

SHOP = {"shop_id": "s", "max_working_days": 5}
WEEK = "2026-10-05"


def _team(**extra):
    return [{
        "employee_id": "e1", "name": "Kayla", "role": "Floor Assistant",
        "age": 30, "hourly_rate": 13.0, "max_weekly_hours": 40, **extra,
    }]


class TestTheHardFloor:
    def test_an_under_16_outside_the_curfew_cannot_be_overridden(self):
        shifts = [{"employee_id": "e1", "day": "mon",
                   "start": "06:00", "end": "12:00"}]
        breaches = audit(shifts, shop=SHOP, employees=_team(age=15),
                         week_start=WEEK)

        curfew = [b for b in breaches if b["rule"] == "minor_curfew"]
        assert curfew, "a 15-year-old starting at 06:00 must be caught"
        assert curfew[0]["overridable"] is False
        assert curfew[0] in blocking(breaches), (
            "a hard-floor breach must appear in blocking(), which is what"
            " the approve endpoint refuses on"
        )

    def test_a_16_year_old_is_not_curfewed(self):
        """The rule is under-16, and an off-by-one here is somebody losing
        shifts they are legally entitled to work."""
        shifts = [{"employee_id": "e1", "day": "mon",
                   "start": "06:00", "end": "12:00"}]
        breaches = audit(shifts, shop=SHOP, employees=_team(age=16),
                         week_start=WEEK)
        assert not [b for b in breaches if b["rule"] == "minor_curfew"]

    def test_everything_else_is_the_managers_call(self):
        """Six days, over the cap, a short turnaround — all overridable."""
        shifts = [
            {"employee_id": "e1", "day": d, "start": "09:00", "end": "21:00"}
            for d in ("mon", "tue", "wed", "thu", "fri", "sat")
        ]
        breaches = audit(shifts, shop=SHOP, employees=_team(), week_start=WEEK)

        assert breaches, "72h over six days has to be flagged"
        assert all(b["overridable"] for b in breaches), (
            f"only {HARD_FLOOR} may be unoverridable, got "
            f"{[b['rule'] for b in breaches if not b['overridable']]}"
        )
        assert blocking(breaches) == []


class TestTheMessagesAreReadable:
    def test_a_breach_names_the_numbers(self):
        """"Rostered 48h against a 40h limit" tells them what to change.
        "weekly_hours_exceeded" does not."""
        shifts = [
            {"employee_id": "e1", "day": d, "start": "09:00", "end": "21:00"}
            for d in ("mon", "tue", "wed", "thu", "fri")
        ]
        breaches = audit(shifts, shop=SHOP, employees=_team(), week_start=WEEK)
        hours = next(b for b in breaches if b["rule"] == "weekly_hours")

        assert "Kayla" in hours["message"]
        assert "40" in hours["message"]

    def test_breaches_are_grouped_by_person_for_the_grid(self):
        shifts = [
            {"employee_id": "e1", "day": d, "start": "09:00", "end": "22:00"}
            for d in ("mon", "tue", "wed", "thu", "fri", "sat")
        ]
        people = group_by_employee(
            audit(shifts, shop=SHOP, employees=_team(), week_start=WEEK)
        )
        assert len(people) == 1
        assert people[0]["name"] == "Kayla"
        assert len(people[0]["breaches"]) > 1


class TestRealTimeNotClockTime:
    def test_an_overnight_turnaround_is_measured_correctly(self):
        """23:30 Monday to 07:00 Tuesday is 7.5 hours, not 16.5 backwards."""
        shifts = [
            {"employee_id": "e1", "day": "mon", "start": "23:30", "end": "07:00"},
            {"employee_id": "e1", "day": "tue", "start": "17:00", "end": "22:00"},
        ]
        breaches = audit(shifts, shop=SHOP, employees=_team(), week_start=WEEK)
        # Finishes 07:00 Tuesday, starts 17:00 Tuesday — ten hours, so short.
        assert any(b["rule"] == "rest_gap" for b in breaches)

    def test_a_full_turnaround_is_not_flagged(self):
        shifts = [
            {"employee_id": "e1", "day": "mon", "start": "09:00", "end": "17:00"},
            {"employee_id": "e1", "day": "tue", "start": "09:00", "end": "17:00"},
        ]
        breaches = audit(shifts, shop=SHOP, employees=_team(), week_start=WEEK)
        assert not [b for b in breaches if b["rule"] == "rest_gap"]


class TestLeaveExplainsShortHours:
    """Somebody on holiday is short by definition, and it is not a fault.

    They are PAID for the holiday, so the contract is honoured even though the
    hours on the roster do not add up to it. Flagging it sent the manager
    hunting for a problem on the one week where the answer is already on the
    screen, two cells to the left.
    """

    def _salaried(self):
        return [{
            "employee_id": "e1", "name": "Steve", "role": "Floor Assistant",
            "age": 30, "hourly_rate": 15.0, "max_weekly_hours": 45,
            "employment_type": "full_time_contract", "contract_span_hours": 40,
        }]

    def test_a_short_week_is_flagged_when_nothing_explains_it(self):
        shifts = [
            {"employee_id": "e1", "day": d, "start": "09:00", "end": "17:00"}
            for d in ("mon", "tue", "wed")           # 24h against 40
        ]
        breaches = audit(shifts, shop=SHOP, employees=self._salaried(),
                         week_start=WEEK)
        assert any(b["rule"] == "contract_under" for b in breaches)

    def test_booked_holiday_removes_the_short_hours_warning(self):
        shifts = [
            {"employee_id": "e1", "day": d, "start": "09:00", "end": "17:00"}
            for d in ("mon", "tue", "wed")
        ] + [
            {"employee_id": "e1", "day": "thu", "start": "", "end": "",
             "paid_holiday": True},
            {"employee_id": "e1", "day": "fri", "start": "", "end": "",
             "paid_holiday": True},
        ]
        breaches = audit(shifts, shop=SHOP, employees=self._salaried(),
                         week_start=WEEK)
        assert not [b for b in breaches if b["rule"] == "contract_under"], (
            "Steve is on holiday — being short is what holiday means"
        )

    def test_sickness_does_the_same(self):
        shifts = [
            {"employee_id": "e1", "day": d, "start": "09:00", "end": "17:00"}
            for d in ("mon", "tue", "wed")
        ] + [
            {"employee_id": "e1", "day": "thu", "start": "09:00", "end": "17:00",
             "sick": True},
        ]
        breaches = audit(shifts, shop=SHOP, employees=self._salaried(),
                         week_start=WEEK)
        assert not [b for b in breaches if b["rule"] == "contract_under"]

    def test_leave_booked_on_the_calendar_counts_too(self):
        """Leave lives in two places — an entry on the roster, and a holiday
        record. Only reading the first would miss a week booked off before
        the roster was generated."""
        shifts = [
            {"employee_id": "e1", "day": d, "start": "09:00", "end": "17:00"}
            for d in ("mon", "tue", "wed")
        ]
        holidays = [{
            "scope": "employee", "employee_id": "e1",
            "date": "2026-10-08", "end_date": "2026-10-09",
        }]
        breaches = audit(shifts, shop=SHOP, employees=self._salaried(),
                         week_start=WEEK, holidays=holidays)
        assert not [b for b in breaches if b["rule"] == "contract_under"]

    def test_leave_does_not_excuse_anything_else(self):
        """Only the SHORT-hours check is suppressed. Six days around a
        holiday is still six days."""
        shifts = [
            {"employee_id": "e1", "day": d, "start": "09:00", "end": "17:00"}
            for d in ("mon", "tue", "wed", "thu", "fri", "sat")
        ] + [
            {"employee_id": "e1", "day": "sun", "start": "", "end": "",
             "paid_holiday": True},
        ]
        breaches = audit(shifts, shop=SHOP, employees=self._salaried(),
                         week_start=WEEK)
        assert any(b["rule"] == "days_worked" for b in breaches)
