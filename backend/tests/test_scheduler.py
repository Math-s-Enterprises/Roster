"""Tests for the roster solver.

The solver is a pure function, so these run with no database, no network
and no server — fast enough to run on every save.

The first four classes each pin one of the four non-negotiable rules. If a
future change breaks one of those guarantees, one of these fails.
"""
import pytest

from app.services.scheduler import (
    break_minutes,
    paid_hours,
    ABSOLUTE_MAX_SHIFT_HOURS,
    build_segments,
    shift_duration_minutes,
    solve_roster,
    to_minutes,
    violates_minor_curfew,
)

WEEK = "2026-08-10"  # a Monday
ALL_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def make_shop(open_time="09:00", close_time="21:00", *, min_h=4, max_h=9, templates=None):
    return {
        "shop_id": "shop_test",
        "hours": [
            {"day": d, "open": open_time, "close": close_time, "closed": False}
            for d in ALL_DAYS
        ],
        "min_shift_hours": min_h,
        "max_shift_hours": max_h,
        "shift_templates": templates or [],
    }


def make_employee(eid, role="Cashier", *, age=25, max_hours=40, days_off=None, rate=15.0):
    return {
        "employee_id": eid,
        "name": f"Employee {eid}",
        "email": f"{eid}@example.com",
        "role": role,
        "age": age,
        "hourly_rate": rate,
        "max_weekly_hours": max_hours,
        "preferred_days_off": days_off or [],
        "departments": ["Shop Floor"],
    }


def big_team(count=8):
    """Enough people that hour caps are not the binding constraint."""
    roles = ["Manager", "Supervisor", "Cashier", "Cashier",
             "Floor Assistant", "Floor Assistant", "Stocker", "Cashier"]
    return [make_employee(f"e{i}", roles[i % len(roles)]) for i in range(count)]


def coverage_gaps(shifts, day, open_time, close_time):
    """Minutes within opening hours that nobody is scheduled for."""
    intervals = sorted(
        (to_minutes(s["start"]), to_minutes(s["end"]))
        for s in shifts if s["day"] == day
    )
    gaps, cursor = [], to_minutes(open_time)
    close_m = to_minutes(close_time)
    for start, end in intervals:
        if end <= start:      # overnight shift — covers to end of day
            end = 24 * 60
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < close_m:
        gaps.append((cursor, close_m))
    return gaps


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
class TestBreaks:
    """Breaks are unpaid, so a contract is in paid hours and the roster must
    span longer to deliver them. Getting this wrong under-pays everyone by
    roughly 10%."""

    @pytest.mark.parametrize("span,minutes", [
        (4.0, 0), (4.9, 0),
        (5.0, 15), (5.5, 15),
        (6.0, 30), (7.9, 30),
        (8.0, 45), (9.5, 45),
        (10.0, 60), (11.0, 60),
    ])
    def test_break_schedule(self, span, minutes):
        assert break_minutes(span) == minutes

    @pytest.mark.parametrize("start,end,expected", [
        ("09:00", "13:00", 4.0),     # under 5h, no break
        ("09:00", "14:00", 4.75),    # 5h minus 15m
        ("09:00", "15:00", 5.5),     # 6h minus 30m
        ("06:00", "14:00", 7.25),    # 8h minus 45m
        ("06:00", "16:00", 9.0),     # 10h minus 1h
        ("23:30", "07:00", 7.0),     # overnight 7.5h -> 6h tier, minus 30m
    ])
    def test_paid_hours(self, start, end, expected):
        assert paid_hours(start, end) == pytest.approx(expected)

    def test_contract_is_paid_hours_so_span_runs_longer(self):
        """Five 10-hour shifts span 50h but pay 45h — a 40h contract can
        legitimately be rostered for more than 40 hours of clock time."""
        employees = [make_employee("e1", max_hours=40)]
        shop = make_shop("06:00", "16:00", max_h=10)
        result = solve_roster(shop, employees, [], [], [], WEEK)

        paid = result["per_employee_hours"]["e1"]
        span = sum(
            shift_duration_minutes(s["start"], s["end"]) / 60
            for s in result["shifts"] if s["employee_id"] == "e1"
        )
        assert paid <= 40, "paid hours must respect the contract"
        assert span > paid, "clock time should exceed paid time once breaks are removed"

    def test_shift_records_span_break_and_paid(self):
        result = solve_roster(
            make_shop("06:00", "16:00", max_h=10), [make_employee("e1")], [], [], [], WEEK
        )
        shift = result["shifts"][0]
        assert shift["span_hours"] == pytest.approx(10.0)
        assert shift["break_minutes"] == 60
        assert shift["paid_hours"] == pytest.approx(9.0)


class TestTimeHelpers:
    def test_normal_shift(self):
        assert shift_duration_minutes("09:00", "17:00") == 480

    def test_overnight_shift_wraps(self):
        assert shift_duration_minutes("23:00", "07:00") == 480

    def test_zero_length_is_zero_not_a_full_day(self):
        # Almost certainly a data-entry error; 24h would be a dangerous read.
        assert shift_duration_minutes("09:00", "09:00") == 0


# ---------------------------------------------------------------------------
# RULE 1 — role priority
# ---------------------------------------------------------------------------
class TestRuleOneRolePriority:
    def test_manager_scheduled_before_stocker(self):
        employees = [make_employee("stocker", "Stocker"), make_employee("mgr", "Manager")]
        result = solve_roster(make_shop("09:00", "17:00"), employees, [], [], [], WEEK)
        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        assert monday[0]["employee_id"] == "mgr"

    def test_priority_beats_learned_preference(self):
        """Role order must not be outweighed by historical affinity."""
        employees = [make_employee("stocker", "Stocker"), make_employee("mgr", "Manager")]
        weights = {"day": {"stocker": {"mon": 999}}}  # strong habit for the stocker
        result = solve_roster(
            make_shop("09:00", "17:00"), employees, [], [], [], WEEK, weights
        )
        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        assert monday[0]["employee_id"] == "mgr"


# ---------------------------------------------------------------------------
# RULE 2 — continuous coverage
# ---------------------------------------------------------------------------
class TestRuleTwoContinuousCoverage:
    def test_no_gaps_when_day_exceeds_max_shift(self):
        """A 12h day with a 9h cap must still be covered end to end."""
        shop = make_shop("09:00", "21:00", max_h=9)
        result = solve_roster(shop, big_team(), [], [], [], WEEK)
        for day in ALL_DAYS:
            assert coverage_gaps(result["shifts"], day, "09:00", "21:00") == [], \
                f"{day} has an uncovered gap"

    def test_no_shift_exceeds_the_cap_while_covering(self):
        shop = make_shop("09:00", "21:00", max_h=9)
        result = solve_roster(shop, big_team(), [], [], [], WEEK)
        for shift in result["shifts"]:
            hours = shift_duration_minutes(shift["start"], shift["end"]) / 60
            assert hours <= ABSOLUTE_MAX_SHIFT_HOURS

    def test_long_day_is_split_evenly_not_into_a_remainder(self):
        """12h / 9h cap -> 2x6h. Never 9h + 3h, which would break the cap
        or leave a sliver uncovered."""
        segments = build_segments(make_shop(max_h=9), to_minutes("09:00"), to_minutes("21:00"))
        assert len(segments) == 2
        assert [(s.start, s.end) for s in segments] == [("09:00", "15:00"), ("15:00", "21:00")]

    def test_short_day_stays_one_segment(self):
        segments = build_segments(make_shop(max_h=9), to_minutes("09:00"), to_minutes("17:00"))
        assert [(s.start, s.end) for s in segments] == [("09:00", "17:00")]

    def test_closed_day_is_skipped_entirely(self):
        shop = make_shop()
        shop["hours"][6] = {"day": "sun", "open": "00:00", "close": "00:00", "closed": True}
        result = solve_roster(shop, big_team(), [], [], [], WEEK)
        assert not [s for s in result["shifts"] if s["day"] == "sun"]


# ---------------------------------------------------------------------------
# RULE 3 — 24-hour staffing
# ---------------------------------------------------------------------------
TEMPLATES_24H = [
    {"template_id": "tpl_morning", "name": "Morning", "start": "07:00", "end": "15:00", "min_staff": 2},
    {"template_id": "tpl_afternoon", "name": "Afternoon", "start": "15:00", "end": "23:00", "min_staff": 2},
    {"template_id": "tpl_night", "name": "Night", "start": "23:00", "end": "07:00", "min_staff": 1},
]


class TestRuleThreeTwentyFourHour:
    def test_every_block_including_night_is_staffed(self):
        shop = make_shop("00:00", "23:59", templates=TEMPLATES_24H)
        result = solve_roster(shop, big_team(12), [], [], [], WEEK)
        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        assert {s["template_name"] for s in monday} == {"Morning", "Afternoon", "Night"}

    def test_empty_block_is_reported_as_critical(self):
        shop = make_shop("00:00", "23:59", templates=TEMPLATES_24H)
        result = solve_roster(shop, [make_employee("solo")], [], [], [], WEEK)
        criticals = [i for i in result["critical_issues"] if "mon" in i]
        assert criticals, "an unstaffed block must be flagged CRITICAL"
        assert any("Night" in i for i in criticals)

    def test_understaffed_but_covered_is_not_critical(self):
        """1 of 2 wanted still means the shop is attended — advisory, not critical.

        Scoped to Monday deliberately: by Saturday the single employee has
        exhausted their weekly hours, so Morning really is uncovered then and
        being flagged critical there is correct.
        """
        shop = make_shop("00:00", "23:59", templates=TEMPLATES_24H)
        result = solve_roster(shop, [make_employee("solo")], [], [], [], WEEK)
        assert any("Morning on mon" in i and "1/2" in i for i in result["issues"])
        assert not any("Morning on mon" in i for i in result["critical_issues"])


# ---------------------------------------------------------------------------
# RULE 4 — legal limits are never relaxed
# ---------------------------------------------------------------------------
class TestRuleFourLegalLimits:
    def test_minor_curfew_boundaries(self):
        minor = make_employee("kid", age=15)
        adult = make_employee("adult", age=30)
        assert violates_minor_curfew(minor, "07:00", "12:00") is True   # too early
        assert violates_minor_curfew(minor, "14:00", "20:00") is True   # too late
        assert violates_minor_curfew(minor, "23:00", "07:00") is True   # overnight
        assert violates_minor_curfew(minor, "09:00", "17:00") is False  # fine
        assert violates_minor_curfew(adult, "23:00", "07:00") is False  # n/a to adults

    def test_minor_never_scheduled_outside_curfew(self):
        shop = make_shop("06:00", "23:00", max_h=8)
        employees = [make_employee("kid", age=15)] + big_team(6)
        result = solve_roster(shop, employees, [], [], [], WEEK)
        for shift in result["shifts"]:
            if shift["employee_id"] == "kid":
                assert to_minutes(shift["start"]) >= to_minutes("08:00")
                assert to_minutes(shift["end"]) <= to_minutes("19:00")

    def test_weekly_hour_cap_is_respected(self):
        employees = [make_employee(f"e{i}", max_hours=10) for i in range(6)]
        result = solve_roster(make_shop("09:00", "17:00"), employees, [], [], [], WEEK)
        for employee_id, hours in result["per_employee_hours"].items():
            assert hours <= 10, f"{employee_id} exceeded their cap"

    def test_coverage_never_overrides_the_law(self):
        """A minor must not be pulled into a late slot even to fill a gap."""
        shop = make_shop("09:00", "22:00", max_h=7)
        result = solve_roster(shop, [make_employee("kid", age=15)], [], [], [], WEEK)
        assert result["shifts"] == [] or all(
            to_minutes(s["end"]) <= to_minutes("19:00") for s in result["shifts"]
        )
        assert result["critical_issues"], "the unfillable gap must be reported"


# ---------------------------------------------------------------------------
# Preferences and fallback
# ---------------------------------------------------------------------------
class TestPreferenceHandling:
    def test_preferred_day_off_respected_when_others_available(self):
        employees = [make_employee("picky", days_off=["mon"])] + big_team(6)
        result = solve_roster(make_shop("09:00", "17:00"), employees, [], [], [], WEEK)
        monday = [s["employee_id"] for s in result["shifts"] if s["day"] == "mon"]
        assert "picky" not in monday

    def test_strict_days_off_beats_coverage_by_default(self):
        """A requested day off is absolute unless the shop opts out.

        This deliberately outranks the coverage floor: the shop would rather
        show a visible gap for a manager to resolve than quietly roster
        somebody who asked not to work.
        """
        employees = [make_employee("only", days_off=["mon"])]
        result = solve_roster(make_shop("09:00", "17:00"), employees, [], [], [], WEEK)
        assert not [s for s in result["shifts"] if s["day"] == "mon"]
        assert any("mon" in i for i in result["critical_issues"])

    def test_preference_relaxed_when_strict_mode_is_off(self):
        """With strict_days_off disabled, coverage wins and it is flagged."""
        shop = make_shop("09:00", "17:00")
        shop["strict_days_off"] = False
        employees = [make_employee("only", days_off=["mon"])]

        result = solve_roster(shop, employees, [], [], [], WEEK)
        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        assert monday, "coverage should win once strict mode is off"
        assert monday[0].get("coverage_fallback") is True

    def test_leave_is_never_relaxed(self):
        """Unlike preferences, actual leave holds even if cover is lost.

        The person still appears on the roster — as paid holiday, not as a
        shift — so the manager can see why the day is short.
        """
        employees = [make_employee("away")]
        holidays = [{"date": WEEK, "end_date": WEEK, "label": "Holiday",
                     "scope": "employee", "employee_id": "away"}]
        result = solve_roster(make_shop("09:00", "17:00"), employees, holidays, [], [], WEEK)

        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        assert not [s for s in monday if not s.get("paid_holiday")], "no work should be assigned"
        assert all(s.get("paid_holiday") for s in monday)
        assert any("mon" in i for i in result["critical_issues"])


# ---------------------------------------------------------------------------
# Fixed shifts
# ---------------------------------------------------------------------------
class TestFixedShifts:
    def test_fixed_shift_is_honoured(self):
        fixed = [{"employee_id": "e0", "days": ["mon"], "start": "10:00", "end": "16:00"}]
        result = solve_roster(make_shop(), big_team(), [], fixed, [], WEEK)
        assert any(
            s["employee_id"] == "e0" and s["day"] == "mon" and s.get("fixed")
            for s in result["shifts"]
        )

    def test_fixed_shifts_apply_to_24h_shops_too(self):
        """Regression: the prototype ignored fixed shifts when templates existed."""
        shop = make_shop("00:00", "23:59", templates=TEMPLATES_24H)
        fixed = [{"employee_id": "e0", "days": ["mon"], "start": "09:00", "end": "17:00"}]
        result = solve_roster(shop, big_team(12), [], fixed, [], WEEK)
        assert any(
            s["employee_id"] == "e0" and s["day"] == "mon" and s.get("fixed")
            for s in result["shifts"]
        )

    def test_fixed_shift_skipped_when_on_leave(self):
        fixed = [{"employee_id": "e0", "days": ["mon"], "start": "10:00", "end": "16:00"}]
        holidays = [{"date": WEEK, "end_date": WEEK, "label": "Leave",
                     "scope": "employee", "employee_id": "e0"}]
        result = solve_roster(make_shop(), big_team(), holidays, fixed, [], WEEK)
        assert not any(
            s["employee_id"] == "e0" and s["day"] == "mon" and not s.get("paid_holiday")
            for s in result["shifts"]
        ), "the fixed shift must not be worked while on leave"
        assert any("on leave" in i for i in result["issues"])


# ---------------------------------------------------------------------------
# Holidays and metrics
# ---------------------------------------------------------------------------
class TestHolidaysAndMetrics:
    def test_shop_holiday_clears_the_day(self):
        holidays = [{"date": WEEK, "end_date": WEEK, "label": "Bank holiday", "scope": "shop"}]
        result = solve_roster(make_shop(), big_team(), holidays, [], [], WEEK)
        assert not [s for s in result["shifts"] if s["day"] == "mon"]

    def test_multi_day_holiday_range_is_expanded(self):
        holidays = [{"date": "2026-08-10", "end_date": "2026-08-12",
                     "label": "Closed", "scope": "shop"}]
        result = solve_roster(make_shop(), big_team(), holidays, [], [], WEEK)
        scheduled_days = {s["day"] for s in result["shifts"]}
        assert not scheduled_days & {"mon", "tue", "wed"}

    def test_labor_cost_is_never_negative_for_overnight_shifts(self):
        """Regression: subtracting raw times made overnight shifts cost < 0."""
        shop = make_shop("00:00", "23:59", templates=TEMPLATES_24H)
        result = solve_roster(shop, big_team(12), [], [], [], WEEK)
        assert result["labor_cost"] > 0

    def test_critical_issues_hurt_the_score_more_than_advisories(self):
        covered = solve_roster(make_shop("09:00", "17:00"), big_team(), [], [], [], WEEK)
        uncovered = solve_roster(make_shop("09:00", "17:00"), [], [], [], [], WEEK)
        assert covered["compliance_score"] > uncovered["compliance_score"]

    def test_empty_roster_does_not_crash(self):
        result = solve_roster(make_shop(), [], [], [], [], WEEK)
        assert result["shifts"] == []
        assert result["utilization"] == 0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def test_solver_is_deterministic():
    """Same inputs, same assignments — only shift_ids differ (they're random)."""
    shop, team = make_shop(), big_team()
    first = solve_roster(shop, team, [], [], [], WEEK)
    second = solve_roster(shop, team, [], [], [], WEEK)

    def fingerprint(result):
        return sorted(
            (s["employee_id"], s["day"], s["start"], s["end"]) for s in result["shifts"]
        )

    assert fingerprint(first) == fingerprint(second)
