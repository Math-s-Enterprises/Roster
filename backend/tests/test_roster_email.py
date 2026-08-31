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


class TestTotalHours:
    """The number they will hold against their payslip."""

    def test_the_week_is_totalled(self):
        # 8 + 8 + 7.5 = 23.5 span; with unpaid breaks it is less, and the
        # figure must be the PAID one.
        from app.services.scheduler import paid_hours
        expected = sum(paid_hours(s["start"], s["end"], breaks_paid=False)
                       for s in SHIFTS)
        assert f"{expected:g} hours" in render()

    def test_breaks_being_paid_changes_the_figure(self):
        """§8: `breaks_are_paid` is per shop and moves every wage figure. A
        shop that pays breaks must not be told the smaller number."""
        unpaid = render_roster_email("Emma", "Top Oil", WEEK, SHIFTS, False)
        paid = render_roster_email("Emma", "Top Oil", WEEK, SHIFTS, True)
        assert unpaid != paid, "the setting made no difference to the total"

    def test_leave_adds_no_hours(self):
        one = [{"day": "mon", "start": "09:00", "end": "17:00"}]
        with_leave = one + [
            {"day": "tue", "start": None, "end": None, "paid_holiday": True}]
        from app.services.scheduler import paid_hours
        expected = paid_hours("09:00", "17:00", breaks_paid=False)
        assert f"{expected:g} hours" in render(with_leave)

    def test_a_whole_number_has_no_trailing_zero(self):
        body = render([{"day": "mon", "start": "09:00", "end": "13:00"}])
        assert "4 hours" in body and "4.0 hours" not in body


class TestLeaveIsShownNotDropped:
    """Somebody scanning their week needs to see the Tuesday they booked
    off, not a gap they have to interpret."""

    def test_a_holiday_appears_with_no_times(self):
        body = render([{"day": "tue", "start": None, "end": None,
                        "paid_holiday": True}])
        assert "Tuesday 1 Sep" in body and "Holiday" in body

    def test_sick_and_unpaid_are_named_too(self):
        assert "Sick" in render([{"day": "wed", "start": None, "end": None,
                                  "sick": True}])
        assert "Unpaid leave" in render([{"day": "wed", "start": None,
                                          "end": None, "unpaid_holiday": True}])

    def test_leave_beside_real_shifts_does_not_crash_the_send(self):
        """THE BUG THIS FOUND.

        `shift["end"] <= shift["start"]` — the overnight test — compared None
        with None and raised TypeError. The render happens while BUILDING the
        gather list rather than inside it, so it was not caught per recipient:
        one person on leave cost the ENTIRE TEAM their rota.

        (My first explanation blamed the sort. It was wrong — two shifts only
        reach the start-time tiebreak on the same day, so a holiday and a
        working shift on different days never compared. Checked before the
        comment went in.)
        """
        body = render([
            {"day": "mon", "start": "06:00", "end": "14:00"},
            {"day": "tue", "start": None, "end": None, "paid_holiday": True},
            {"day": "wed", "start": "13:00", "end": "21:00"},
        ])
        assert "Holiday" in body
        assert "06:00" in body and "13:00" in body


    def test_leave_on_the_same_day_as_a_shift_is_safe_too(self):
        """The case the sort guard is actually for: same day, so the start
        times DO get compared."""
        body = render([
            {"day": "mon", "start": "06:00", "end": "14:00"},
            {"day": "mon", "start": None, "end": None, "sick": True},
        ])
        assert "Sick" in body and "06:00" in body


class TestTheWholeShopEmail:
    """What somebody who does not work in the shop is sent.

    An area manager or owner wants what the printed rota gives: everyone,
    every day, at a glance. Twenty-five separate emails would leave them
    reassembling the week themselves.
    """

    PEOPLE = [
        {"name": "Emma", "shifts": [
            {"day": "mon", "start": "06:00", "end": "14:00"},
            {"day": "tue", "start": None, "end": None, "paid_holiday": True},
        ]},
        {"name": "Martin", "shifts": [
            {"day": "mon", "start": "13:00", "end": "21:00"},
        ]},
    ]

    def whole(self, people=None, week=WEEK, shop="Top Oil"):
        from app.services.mailer import render_shop_roster_email
        return render_shop_roster_email(
            shop, week, self.PEOPLE if people is None else people)

    def test_everybody_appears(self):
        body = self.whole()
        assert "Emma" in body and "Martin" in body

    def test_every_day_is_a_column_with_its_date(self):
        body = self.whole()
        for label in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            assert label in body
        assert "31 Aug" in body and "6 Sep" in body

    def test_each_person_is_totalled_and_so_is_the_shop(self):
        from app.services.scheduler import paid_hours
        emma = paid_hours("06:00", "14:00", breaks_paid=False)
        martin = paid_hours("13:00", "21:00", breaks_paid=False)
        body = self.whole()
        assert f"{emma:g}h" in body and f"{emma + martin:g}h" in body

    def test_leave_shows_without_adding_hours(self):
        from app.services.scheduler import paid_hours
        body = self.whole([self.PEOPLE[0]])
        assert "Holiday" in body
        assert f"{paid_hours('06:00', '14:00', breaks_paid=False):g}h" in body

    def test_a_name_cannot_inject_html(self):
        body = self.whole([{"name": "<script>x</script>", "shifts": []}])
        assert "<script>" not in body

    def test_an_empty_week_says_so(self):
        assert "Nobody is rostered" in self.whole([])

    def test_it_counts_the_people_on_the_rota(self):
        assert "2 on the rota" in self.whole()
