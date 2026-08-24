"""The roster reproduces the shifts the shop actually runs.

Previously the solver learned an hourly headcount and filled hours greedily.
That double-counted the overlap at shift changeover: a night shift still on
the floor at 06:00 is already in the historical curve, so filling 06:00 "to
target" with fresh morning starts and then letting the night shift arrive on
top put a fourth body on an hour that has always had three.

Learning the day's slot list instead — two open at 06:00, one starts at
07:30, one covers the night — cannot double-count, because each shift the
shop runs is placed exactly once.
"""
from datetime import date, timedelta

from app.services.demand import build_profile
from app.services.scheduler import DAYS, _RosterBuilder, solve_roster

WEEK = "2026-08-17"

# The shape from the reference shop's own approved roster.
WEEKDAY = [
    ("06:00", "16:00"), ("06:00", "14:00"), ("07:30", "16:00"),
    ("13:00", "21:00"), ("16:00", "00:00"), ("23:30", "07:00"),
]
# Deliberately gapless, so the coverage floor has nothing to add and the
# generated shape can be compared to the learned one directly.
SUNDAY = [("06:00", "16:00"), ("13:00", "21:00"), ("16:00", "00:00"), ("23:30", "07:00")]


def make_shop(**overrides):
    shop = {
        "shop_id": "s", "min_shift_hours": 4, "max_shift_hours": 10,
        "hours": [
            {"day": d, "open": "00:00", "close": "23:59", "closed": False}
            for d in DAYS
        ],
        "strict_days_off": False,
    }
    shop.update(overrides)
    return shop


def make_team(size=14, **overrides):
    team = []
    for i in range(size):
        employee = {
            "employee_id": f"e{i}", "name": f"E{i}", "role": "Floor Assistant",
            "age": 30, "hourly_rate": 15.0, "max_weekly_hours": 40,
            "preferred_days_off": [], "departments": ["Shop Floor"],
            "is_active": True,
        }
        employee.update(overrides)
        team.append(employee)
    return team


def history(weeks=24):
    out = []
    for w in range(weeks):
        shifts = [
            {"employee_id": f"e{i}", "day": d, "start": s, "end": e}
            for d in DAYS
            for i, (s, e) in enumerate(SUNDAY if d == "sun" else WEEKDAY)
        ]
        out.append({
            "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
            "approved": True, "shifts": shifts,
        })
    return out


def generate(team=None, shop=None, hist=None):
    shop = shop or make_shop()
    team = team or make_team()
    hist = hist if hist is not None else history()
    profile = build_profile(shop, hist, {e["employee_id"]: e["role"] for e in team})
    result = solve_roster(
        shop, team, [], [], [], WEEK, None, profile, history_rosters=hist,
    )
    return result, profile


def coverage(result):
    grid = {d: [0] * 24 for d in DAYS}
    for shift in result["shifts"]:
        if not (shift.get("start") and shift.get("end")):
            continue
        for day, hour in _RosterBuilder.hours_covered(
            shift["day"], shift["start"], shift["end"]
        ):
            grid[day][hour] += 1
    return grid


class TestTheShapeIsReproduced:
    def test_a_weekday_matches_the_learned_slots_exactly(self):
        result, profile = generate()
        got = sorted((s["start"], s["end"]) for s in result["shifts"] if s["day"] == "mon")
        assert got == sorted(profile.slots_for("mon"))

    def test_a_quieter_day_stays_quieter(self):
        """Sunday runs a shorter list here, and must not be levelled up to
        match the weekdays."""
        result, profile = generate()
        sunday = [s for s in result["shifts"] if s["day"] == "sun"]
        assert len(sunday) == len(profile.slots_for("sun"))
        assert len(sunday) < len(profile.slots_for("mon"))

    def test_the_changeover_hour_is_not_double_counted(self):
        """The reported bug. At 06:00 the outgoing night worker is still
        there, which the learned curve already counts — so the roster must
        not add another body on top."""
        result, profile = generate()
        grid = coverage(result)
        for day in DAYS:
            assert grid[day][6] == profile.required(day, 6), (
                f"{day} 06:00 has {grid[day][6]}, history says {profile.required(day, 6)}"
            )

    def test_the_week_does_not_cost_more_than_history(self):
        result, profile = generate()
        grid = coverage(result)
        over = sum(
            max(0, grid[d][h] - profile.required(d, h))
            for d in DAYS for h in range(24) if profile.required(d, h) > 0
        )
        assert over == 0, f"{over} person-hours above what the shop has ever staffed"

    def test_no_unfamiliar_shifts_and_no_gaps(self):
        result, _ = generate()
        assert result["confirmations"] == []
        assert result["critical_issues"] == []


class TestRulesStillHold:
    def test_nobody_works_more_than_five_days(self):
        result, _ = generate()
        days = {}
        for shift in result["shifts"]:
            days.setdefault(shift["employee_id"], set()).add(shift["day"])
        assert max(len(d) for d in days.values()) <= 5

    def test_a_preferred_day_off_is_respected(self):
        team = make_team()
        team[0]["preferred_days_off"] = ["wed"]
        result, _ = generate(team=team, shop=make_shop(strict_days_off=True))
        assert not [
            s for s in result["shifts"]
            if s["employee_id"] == "e0" and s["day"] == "wed"
        ]

    def test_a_slot_nobody_can_take_is_left_blank(self):
        """Left empty and reported, rather than given to somebody the rules
        would not allow."""
        result, _ = generate(team=make_team(size=2))
        assert result["gaps"], "unfillable hours should be reported"
        assert result["confirmations"] == [], "and not papered over"


def salaried_team():
    team = make_team(size=14)
    team[0].update({
        "employment_type": "full_time_contract", "max_weekly_hours": 42.5,
    })
    return team


def span_of(result, employee_id):
    return sum(
        s.get("span_hours", 0) for s in result["shifts"]
        if s["employee_id"] == employee_id
    )


class TestClosingChangeoverGaps:
    """An hour short at a shift changeover does not need another person.

    It needs somebody finishing at 15:30 instead of 15:00, or starting an
    hour earlier. Rostering a whole extra shift for one hour would overstaff
    the rest of the day and cost a shift nobody needed.
    """

    def _gapped(self, staff=6):
        """A day whose shapes leave 15:00 one body short."""
        from app.services.demand import DemandProfile, ShiftPattern

        curve = [0] * 24
        for hour in list(range(9, 15)) + [15] + list(range(16, 22)):
            curve[hour] = 2

        profile = DemandProfile(
            headcount={d: list(curve) for d in DAYS},
            role_mix={d: {"Floor Assistant": [float(c) for c in curve]} for d in DAYS},
            patterns=[
                ShiftPattern("09:00", "15:00", 50, 6),
                ShiftPattern("16:00", "22:00", 50, 6),
            ],
            weeks_observed=24,
            staff_per_day={d: 4 for d in DAYS},
            day_slots={
                d: [["09:00", "15:00"], ["09:00", "15:00"],
                    ["16:00", "22:00"], ["16:00", "22:00"]]
                for d in DAYS
            },
        )
        shop = make_shop(hours=[
            {"day": d, "open": "06:00", "close": "22:00", "closed": False}
            for d in DAYS
        ])
        team = make_team(size=staff)
        history = [{
            "week_start": "2026-08-10", "approved": True,
            "shifts": [
                {"employee_id": f"e{i}", "day": d, "start": s, "end": e}
                for d in DAYS
                for i, (s, e) in enumerate([
                    ("09:00", "15:00"), ("09:00", "15:00"),
                    ("16:00", "22:00"), ("16:00", "22:00"),
                ])
            ],
        }]
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile, history_rosters=history,
        )
        return result, profile

    def test_the_gap_is_closed_by_stretching_a_neighbour(self):
        result, profile = self._gapped()
        grid = coverage(result)
        monday_short = profile.required("mon", 15) - grid["mon"][15]
        assert monday_short <= 0, "15:00 is still short"

    def test_no_extra_shift_was_invented_for_one_hour(self):
        result, _ = self._gapped()
        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        assert len(monday) == 4, f"expected the usual four shifts, got {len(monday)}"

    def test_the_change_is_explained(self):
        result, _ = self._gapped()
        assert any("to cover" in i for i in result["issues"])

    def test_start_times_are_left_alone_where_a_finish_will_do(self):
        """A finish is just when somebody goes home. A start is what the
        shift IS to them, so it is only moved as a last resort."""
        result, _ = self._gapped()
        for shift in result["shifts"]:
            assert shift["start"] in ("09:00", "16:00"), shift

    def test_a_stretch_never_breaks_the_shift_limit(self):
        result, _ = self._gapped()
        for shift in result["shifts"]:
            assert shift.get("span_hours", 0) <= 10.01, shift


class TestContractTopUp:
    def test_a_salaried_employee_gets_the_longest_shifts_going(self):
        """Their payslip is the same either way, so a short week is hours the
        shop has already bought and not used. They should be first in the
        queue for the long slots."""
        result, _ = generate(team=salaried_team())
        salaried = span_of(result, "e0")
        others = [span_of(result, f"e{i}") for i in range(1, 14)]
        assert salaried >= max(others), (
            f"salaried employee on {salaried}h, an hourly colleague on {max(others)}h"
        )

    def test_an_unreachable_band_is_reported_rather_than_broken(self):
        """With five days as the ceiling and no shift under 7.5 hours, 41 is
        arithmetically out of reach here — four tens is 40, and a fifth of
        anything overshoots 42.5. The roster must say so rather than quietly
        break the maximum to satisfy the minimum."""
        result, _ = generate(team=salaried_team())
        span = span_of(result, "e0")

        assert span <= 42.5, "the contracted maximum must never be exceeded"
        if span < 41.0:
            assert any(u["employee_id"] == "e0" for u in result["under_contract"]), (
                f"left on {span}h with no mention of it"
            )

    def test_the_five_day_limit_is_not_traded_away_for_hours(self):
        result, _ = generate(team=salaried_team())
        days = {s["day"] for s in result["shifts"] if s["employee_id"] == "e0"}
        assert len(days) <= 5

    def test_hourly_staff_are_never_topped_up(self):
        """An hourly contract is a ceiling, not a floor."""
        result, _ = generate()
        assert not any("contracted minimum" in i for i in result["issues"])
