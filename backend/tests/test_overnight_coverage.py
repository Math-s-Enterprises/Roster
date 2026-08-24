"""Overnight coverage, gap reporting and the compliance score.

Every test here corresponds to a defect found in a real generated roster
(week of 2026-08-10) where a 24-hour shop reported Sunday 00:00-06:00 as
unattended, listed each gap twice, and scored 0/100 for it.
"""
from datetime import date, timedelta

from app.services.demand import build_profile
from app.services.scheduler import DAYS, _RosterBuilder, solve_roster

WEEK = "2026-08-10"  # a Monday

NIGHT_ROTA = [("06:00", "14:00"), ("14:00", "22:00"), ("22:00", "06:00")]


def make_24h_shop(close="00:00", **overrides):
    shop = {
        "shop_id": "shop_test",
        "open_24h": True,
        "hours": [
            {"day": d, "open": "00:00", "close": close, "closed": False} for d in DAYS
        ],
        "min_shift_hours": 4,
        "max_shift_hours": 9,
        "shift_templates": [],
        "strict_days_off": True,
    }
    shop.update(overrides)
    return shop


def make_employee(eid, **overrides):
    employee = {
        "employee_id": eid,
        "name": f"E{eid}",
        "role": "Floor Assistant",
        "age": 30,
        "hourly_rate": 13.0,
        "max_weekly_hours": 40,
        "preferred_days_off": [],
        "departments": ["Shop Floor"],
        "is_active": True,
    }
    employee.update(overrides)
    return employee


def round_the_clock_history(weeks=8):
    """Enough history for the demand profile to describe a 24-hour shop."""
    history, start = [], date(2026, 6, 15)
    for week in range(weeks):
        shifts = [
            {"employee_id": f"e{i + 1}", "day": day, "start": start_t, "end": end_t}
            for day in DAYS
            for i, (start_t, end_t) in enumerate(NIGHT_ROTA)
        ]
        history.append({
            "week_start": (start + timedelta(weeks=week)).isoformat(),
            "approved": True,
            "shifts": shifts,
        })
    return history


def generate(staff=8, shop=None, employees=None):
    shop = shop or make_24h_shop()
    employees = employees or [make_employee(f"e{i}") for i in range(1, staff + 1)]
    history = round_the_clock_history()
    demand = build_profile(
        shop, history, {e["employee_id"]: e["role"] for e in employees}
    )
    return solve_roster(
        shop, employees, [], [], [], WEEK, None, demand, history_rosters=history
    )


def coverage(result):
    """Rebuild the hourly coverage grid from the shifts actually produced."""
    grid = {d: [0] * 24 for d in DAYS}
    for shift in result["shifts"]:
        for day, hour in _RosterBuilder.hours_covered(
            shift["day"], shift["start"], shift["end"]
        ):
            grid[day][hour] += 1
    return grid


# ---------------------------------------------------------------------------
# Which day does an overnight shift actually cover?
# ---------------------------------------------------------------------------
class TestHoursCovered:
    def test_night_shift_lands_on_the_following_day(self):
        """Saturday 22:00-06:00 puts somebody in the shop on SUNDAY morning.

        Counting clock hours alone credited all eight to Saturday, so the
        solver believed Saturday morning was staffed by the shift that ended
        it, and that Sunday morning was empty while a person stood there.
        """
        covered = _RosterBuilder.hours_covered("sat", "22:00", "06:00")
        assert ("sat", 22) in covered and ("sat", 23) in covered
        assert all(("sun", h) in covered for h in range(6))
        assert not any(day == "sat" and hour < 6 for day, hour in covered)

    def test_the_week_wraps(self):
        """A weekly rota repeats, so Sunday night covers Monday morning.

        Without the wrap every roster would report a phantom gap at the
        start of Monday, every single week.
        """
        covered = _RosterBuilder.hours_covered("sun", "22:00", "06:00")
        assert all(("mon", h) in covered for h in range(6))

    def test_day_shift_stays_on_its_own_day(self):
        covered = _RosterBuilder.hours_covered("wed", "09:00", "17:00")
        assert {day for day, _ in covered} == {"wed"}

    def test_holiday_entry_covers_nothing(self):
        assert _RosterBuilder.hours_covered("mon", "", "") == []


# ---------------------------------------------------------------------------
# The bug as the user saw it
# ---------------------------------------------------------------------------
class TestNoPhantomOvernightGap:
    def test_a_24h_shop_with_enough_staff_has_no_uncovered_hour(self):
        result = generate(staff=8)
        grid = coverage(result)
        uncovered = [
            (day, hour) for day in DAYS for hour in range(24) if grid[day][hour] == 0
        ]
        assert uncovered == [], f"shop unattended at {uncovered}"
        assert result["critical_issues"] == []

    def test_sunday_small_hours_are_covered_by_saturday_night(self):
        grid = coverage(generate(staff=8))
        assert all(grid["sun"][hour] > 0 for hour in range(6))

    def test_no_run_of_identical_night_shifts_on_one_day(self):
        """The solver used to place a Monday 22:00-06:00 shift, see Monday
        00:00 still empty (those hours had landed on Tuesday), and place
        another — eight in a row, until it ran out of people."""
        result = generate(staff=8)
        for day in DAYS:
            starts = [s["start"] for s in result["shifts"] if s["day"] == day]
            assert len(starts) == len(set(starts)) or len(starts) <= 3, (
                f"{day} got duplicated shift shapes: {sorted(starts)}"
            )

    def test_nobody_is_rostered_twice_on_the_same_day(self):
        """The coverage pass may place a shift on the previous day, which
        must still respect one shift per person per day."""
        result = generate(staff=8)
        seen = [(s["employee_id"], s["day"]) for s in result["shifts"]]
        assert len(seen) == len(set(seen))


# ---------------------------------------------------------------------------
# Coverage carried in from the previous week
# ---------------------------------------------------------------------------
class TestCarryInFromLastWeek:
    """Somebody working 22:00-06:00 last Sunday is in the shop until 06:00
    this Monday. Reporting those hours as unattended is a false alarm, and it
    sends the solver hunting for staff to fill a slot that is not empty."""

    def _history_with_week_before(self, shifts=None):
        """Trailing history where the week immediately before is exactly what
        the test says it is.

        The generated history already contains that week, and the solver
        takes the first roster matching the date — so it has to be replaced
        rather than appended, or the fixture is silently ignored.
        """
        previous = (date.fromisoformat(WEEK) - timedelta(days=7)).isoformat()
        history = [
            r for r in round_the_clock_history() if r["week_start"] != previous
        ]
        history.append({
            "week_start": previous,
            "approved": True,
            "shifts": shifts if shifts is not None else [
                {"employee_id": "e1", "day": "sun", "start": "22:00", "end": "06:00"},
            ],
        })
        return history

    def _no_sunday_shop(self):
        """A shop shut on Sunday, so this week cannot cover Monday itself.

        Isolates the carry-in: with no Sunday of its own to lean on, any
        Monday coverage before 06:00 must have come from last week.
        """
        shop = make_24h_shop()
        for day in shop["hours"]:
            if day["day"] == "sun":
                day["closed"] = True
        return shop

    def test_last_sundays_night_shift_covers_this_monday(self):
        shop = self._no_sunday_shop()
        employees = [make_employee(f"e{i}") for i in range(1, 9)]
        history = self._history_with_week_before()
        demand = build_profile(
            shop, history, {e["employee_id"]: e["role"] for e in employees}
        )
        result = solve_roster(
            shop, employees, [], [], [], WEEK, None, demand, history_rosters=history
        )
        pre_dawn = [
            i for i in result["critical_issues"] if i.startswith("CRITICAL: mon 0")
        ]
        assert pre_dawn == [], f"Monday reported uncovered despite last week: {pre_dawn[:1]}"

    def test_without_a_previous_week_the_rota_is_assumed_to_repeat(self):
        """A brand-new shop has no history to carry in. Falling back to the
        repeating-rota assumption keeps the first week from reporting a
        phantom gap before Monday opening."""
        result = generate(staff=8)
        pre_dawn = [
            i for i in result["critical_issues"] if i.startswith("CRITICAL: mon 0")
        ]
        assert pre_dawn == []

    def test_holiday_and_sick_entries_carry_nothing_in(self):
        """Someone on leave last Sunday is not in the shop this Monday."""
        shop = self._no_sunday_shop()
        employees = [make_employee(f"e{i}") for i in range(1, 9)]
        history = self._history_with_week_before(shifts=[
            {"employee_id": "e1", "day": "sun", "start": "", "end": "",
             "paid_holiday": True},
            {"employee_id": "e2", "day": "sun", "start": "22:00", "end": "06:00",
             "sick": True},
        ])
        demand = build_profile(
            shop, history, {e["employee_id"]: e["role"] for e in employees}
        )
        result = solve_roster(
            shop, employees, [], [], [], WEEK, None, demand, history_rosters=history
        )
        assert [
            i for i in result["critical_issues"] if i.startswith("CRITICAL: mon 0")
        ], "leave was treated as coverage"

    def test_this_weeks_sunday_night_is_not_double_counted(self):
        """With a real previous week, this week's Sunday night belongs to
        NEXT Monday. Counting it here too would hide a genuine gap."""
        covered = _RosterBuilder.hours_covered("sun", "22:00", "06:00", wrap_week=False)
        assert {day for day, _ in covered} == {"sun"}
        assert covered == [("sun", 22), ("sun", 23)]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
class TestGapsAreReportedOnce:
    def test_no_duplicate_critical_issues(self):
        """The demand loop and the coverage-floor pass both reached the same
        hour, so every gap was listed — and penalised — twice."""
        # Two people cannot staff a 24-hour shop, so gaps are guaranteed.
        result = generate(staff=2)
        assert result["critical_issues"], "expected an under-staffed week"
        assert len(result["critical_issues"]) == len(set(result["critical_issues"]))

    def test_no_duplicate_advisories(self):
        result = generate(staff=3)
        assert len(result["issues"]) == len(set(result["issues"]))

    def test_days_off_are_only_blamed_when_they_are_the_real_blocker(self):
        """Naming someone whose hours are already spent points the manager at
        a renegotiation that would not have helped."""
        employees = [make_employee(f"e{i}") for i in range(1, 4)]
        # Marked off on Sunday, but with no hours to give anyway.
        employees.append(make_employee("spent", preferred_days_off=["sun"],
                                       max_weekly_hours=0.5))
        result = generate(employees=employees)
        blamed = [
            i for i in result["critical_issues"] + result["issues"]
            if "requested this day off" in i and "Espent" in i
        ]
        assert blamed == [], f"blamed someone who had no hours left: {blamed[:1]}"


# ---------------------------------------------------------------------------
# Contracted hours are owed, not merely permitted
# ---------------------------------------------------------------------------
def full_timer(eid, **overrides):
    """A salaried employee: 42.5 hours on the floor, fixed weekly pay."""
    return make_employee(
        eid, employment_type="full_time_contract", max_weekly_hours=42.5, **overrides
    )


class TestUnderContract:
    def test_everyone_salaried_reaches_the_band_when_the_work_exists(self):
        """Shift lengths are sized to the contract, so a full-timer should
        land inside 41-42.5 rather than stalling on whatever the historical
        shapes happened to add up to."""
        employees = [full_timer(f"e{i}") for i in range(1, 13)]
        result = generate(employees=employees)

        span = {}
        for shift in result["shifts"]:
            span[shift["employee_id"]] = (
                span.get(shift["employee_id"], 0.0) + shift.get("span_hours", 0.0)
            )
        assert span, "nobody was rostered at all"
        for employee_id, hours in span.items():
            assert 41.0 - 0.01 <= hours <= 42.5 + 0.01, f"{employee_id} on {hours}h"
        assert result["under_contract"] == []

    def test_somebody_who_cannot_reach_the_band_is_named(self):
        """A full-timer available three days a week cannot reach 41 hours
        however the shifts are sized — three tens is thirty. The manager has
        to be told rather than the roster quietly settling for less."""
        employees = [
            full_timer("e1", availability={"available_days": ["mon", "tue", "wed"]}),
            full_timer("e2"),
            full_timer("e3"),
        ]
        result = generate(employees=employees)

        short = {u["employee_id"] for u in result["under_contract"]}
        assert "e1" in short, "the three-day employee was not flagged"
        entry = next(u for u in result["under_contract"] if u["employee_id"] == "e1")
        assert entry["short_hours"] > 0
        assert entry["rostered_hours"] < entry["minimum_hours"]
        assert any("below" in i and "minimum hours" in i for i in result["issues"])

    def test_nobody_is_pushed_past_the_contracted_maximum(self):
        """Fitting hours must never buy the minimum by breaking the ceiling."""
        employees = [full_timer(f"e{i}") for i in range(1, 13)]
        result = generate(employees=employees)

        span = {}
        for shift in result["shifts"]:
            span[shift["employee_id"]] = (
                span.get(shift["employee_id"], 0.0) + shift.get("span_hours", 0.0)
            )
        assert all(hours <= 42.5 + 0.01 for hours in span.values()), span

    def test_hourly_staff_are_never_reported_short(self):
        """An hourly contract is a ceiling, not a floor. Reporting everybody
        under their maximum flagged the whole team every single week —
        including for the 30 unpaid minutes of their own break."""
        employees = [make_employee(f"e{i}", max_weekly_hours=8) for i in range(1, 25)]
        result = generate(employees=employees)
        assert result["under_contract"] == []

    def test_the_band_is_measured_on_the_floor_not_on_the_payslip(self):
        """42.5 is clock in to clock out. Comparing it against paid hours
        would show every full-timer short by the length of their breaks."""
        employees = [full_timer(f"e{i}") for i in range(1, 4)]
        result = generate(employees=employees)

        for entry in result["under_contract"]:
            assert entry["contracted_hours"] == 42.5
            assert entry["minimum_hours"] == 41.0

    def test_somebody_on_leave_that_week_is_not_reported(self):
        """A week broken by holiday cannot reach the band, and saying so every
        time would bury the cases where the shop just did not roster them."""
        from app.services.scheduler import _RosterBuilder

        employees = [full_timer("e1"), full_timer("e2")]
        history = round_the_clock_history()
        demand = build_profile(
            make_24h_shop(), history,
            {e["employee_id"]: e["role"] for e in employees},
        )
        holidays = [{
            "scope": "employee", "employee_id": "e1",
            "date": WEEK, "label": "Holiday",
        }]
        builder = _RosterBuilder(
            make_24h_shop(), employees, holidays, [], [], WEEK, {}, demand, history,
        )
        builder._report_under_contract()

        short = {u["employee_id"] for u in builder.result.under_contract}
        assert "e1" not in short, "somebody on leave was reported short"
        assert "e2" in short, "the employee with no leave should still be flagged"


# ---------------------------------------------------------------------------
# Compliance score
# ---------------------------------------------------------------------------
class TestComplianceScore:
    def test_a_fully_covered_week_scores_100(self):
        assert generate(staff=8)["compliance_score"] == 100

    def test_the_score_distinguishes_a_bad_night_from_no_roster(self):
        """At a flat 25 points per issue the score hit zero after four
        problems, so one uncovered night and a blank week scored the same."""
        one_bad_night = generate(staff=6)["compliance_score"]
        barely_staffed = generate(staff=1)["compliance_score"]
        assert one_bad_night > barely_staffed, (
            f"score cannot tell them apart: {one_bad_night} vs {barely_staffed}"
        )

    def test_the_score_stays_in_range(self):
        for staff in (1, 2, 4, 8, 16):
            score = generate(staff=staff)["compliance_score"]
            assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# 24-hour opening hours
# ---------------------------------------------------------------------------
class TestRoundTheClockHours:
    def test_midnight_to_midnight_is_a_full_day_not_a_zero_length_one(self):
        """`close - open <= 0` skipped the day entirely, so a 24-hour shop
        configured the obvious way got no roster and no explanation."""
        result = generate(staff=8, shop=make_24h_shop(close="00:00"))
        assert result["shifts"], "00:00-00:00 produced an empty roster"

    def test_both_ways_of_writing_a_24h_day_agree(self):
        midnight = generate(staff=8, shop=make_24h_shop(close="00:00"))
        one_to_midnight = generate(staff=8, shop=make_24h_shop(close="23:59"))
        assert len(midnight["shifts"]) == len(one_to_midnight["shifts"])
        assert midnight["compliance_score"] == one_to_midnight["compliance_score"]
