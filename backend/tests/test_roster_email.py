"""What a member of staff actually reads when their rota arrives.

They cannot click into it, cannot check another screen, and will re-read it
days later. Everything they need has to be in the message.
"""
from app.services.mailer import render_roster_email

WEEK = "2026-08-31"          # a Monday
SHIFTS = [
    {"day": "mon", "start": "06:00", "end": "14:00"},
    {"day": "wed", "start": "13:00", "end": "21:00"},
    {"day": "sat", "start": "23:30", "end": "07:00"},   # overnight
]


def render(shifts=SHIFTS, week=WEEK, name="Emma", shop="Top Oil"):
    return render_roster_email(name, shop, week, shifts)


class TestEveryShiftCarriesItsDate:
    """"Monday, 06:00–14:00" is ambiguous the moment it is read on a
    Wednesday, or forwarded, or found again a fortnight later."""

    def test_the_week_is_shown_as_dates_not_an_iso_string(self):
        body = render()
        assert "Mon 31 Aug" in body and "Sun 6 Sep" in body
        assert "2026" in body
        assert "week of 2026-08-31" not in body

    def test_each_day_carries_its_own_date(self):
        body = render()
        assert "Monday 31 Aug" in body
        assert "Wednesday 2 Sep" in body
        assert "Saturday 5 Sep" in body

    def test_the_day_has_no_leading_zero(self):
        """%-d is not portable and %#d is Windows-only, so this is built by
        hand and therefore worth asserting."""
        body = render([{"day": "tue", "start": "09:00", "end": "17:00"}])
        assert "Tuesday 1 Sep" in body
        assert "01 Sep" not in body

    def test_a_week_spanning_a_month_end_still_reads_correctly(self):
        body = render([{"day": "mon", "start": "09:00", "end": "17:00"}],
                      week="2026-12-28")
        assert "Mon 28 Dec" in body and "Sun 3 Jan" in body
        assert "2027" in body, "the year must follow the END of the week"


class TestOvernightShifts:
    """23:30 – 07:00 on a Saturday reads as finishing Saturday morning. §8."""

    def test_an_overnight_shift_says_where_it_ends(self):
        assert "(finishes Sun)" in render()

    def test_a_daytime_shift_says_nothing_extra(self):
        body = render([{"day": "mon", "start": "06:00", "end": "14:00"}])
        assert "finishes" not in body


class TestWhatIsDeliberatelyAbsent:
    def test_the_version_number_is_not_sent(self):
        """It means something to the manager pressing the button and nothing
        to the person reading it, except that there were 22 earlier goes."""
        body = render()
        assert "v1." not in body
        assert "Roster v" not in body
        assert "version" not in body.lower()


class TestSafety:
    def test_a_shop_name_cannot_inject_html(self):
        body = render(shop="<script>alert(1)</script>")
        assert "<script>" not in body
        assert "&lt;script&gt;" in body

    def test_an_employee_name_cannot_inject_html(self):
        assert "<img" not in render(name='<img src=x onerror=alert(1)>')


class TestEdges:
    def test_no_shifts_says_so_rather_than_showing_an_empty_table(self):
        assert "No shifts scheduled this week" in render([])

    def test_a_broken_week_start_does_not_crash_the_send(self):
        """One bad roster must not cost the whole team their schedule."""
        body = render(week="not-a-date")
        assert "Monday" in body
