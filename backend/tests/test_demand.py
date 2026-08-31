"""Tests for demand learning and demand-driven scheduling.

The scheduler's four non-negotiable rules are covered in test_scheduler.py and
are unaffected by any of this — a demand curve is a target, never a licence to
break a constraint. The tests at the bottom of this file prove that.
"""
import pytest

from app.services.demand import (
    DEFAULT_LOOKBACK_WEEKS,
    MIN_WEEKS_FOR_DEMAND,
    DemandProfile,
    ShiftPattern,
    build_profile,
    learn_demand,
    profile_from_shop_hours,
)
from app.services.scheduler import DAYS, solve_roster, to_minutes

WEEK = "2026-08-24"


def make_shop(open_time="00:00", close_time="23:59", **overrides):
    shop = {
        "shop_id": "shop_test",
        "hours": [
            {"day": d, "open": open_time, "close": close_time, "closed": False}
            for d in DAYS
        ],
        "min_shift_hours": 4,
        "max_shift_hours": 11,
        "shift_templates": [],
    }
    shop.update(overrides)
    return shop


def make_employee(eid, role="Floor Assistant", *, age=25, max_hours=40, days_off=None):
    return {
        "employee_id": eid,
        "name": f"Employee {eid}",
        "role": role,
        "age": age,
        "hourly_rate": 13.0,
        "max_weekly_hours": max_hours,
        "preferred_days_off": days_off or [],
        "departments": ["Shop Floor"],
    }


def roster(week_start, shifts):
    return {
        "week_start": week_start,
        "created_at": week_start,
        "approved": True,
        "shifts": [
            {"employee_id": e, "day": d, "start": s, "end": t}
            for e, d, s, t in shifts
        ],
    }


def weekly_history(weeks, shifts_per_week, end="2026-06-29"):
    """`weeks` identical weeks, ending at `end` and going backwards.

    Genuinely seven days apart. They used to be one DAY apart — thirty
    "weeks" that between them spanned a month — which was invisible while the
    lookback was applied by position. Once weeks were weighted by age it
    mattered immediately: everything was the same age, so nothing aged out.
    """
    from datetime import datetime as _dt, timedelta as _td

    last = _dt.strptime(end, "%Y-%m-%d").date()
    return [
        roster((last - _td(weeks=i)).isoformat(), shifts_per_week)
        for i in range(weeks)
    ]


# ---------------------------------------------------------------------------
# Learning the curve
# ---------------------------------------------------------------------------
class TestLearnDemand:
    def test_headcount_matches_a_consistent_history(self):
        history = weekly_history(6, [
            ("e1", "mon", "09:00", "17:00"),
            ("e2", "mon", "09:00", "17:00"),
        ])
        profile = learn_demand(history, {"e1": "Floor Assistant", "e2": "Floor Assistant"})
        # Two people 09:00-17:00 every week -> 2 required for each of those hours.
        assert profile.headcount["mon"][9] == 2
        assert profile.headcount["mon"][16] == 2
        assert profile.headcount["mon"][17] == 0   # end is exclusive
        assert profile.headcount["mon"][8] == 0

    def test_rounds_to_nearest_not_up(self):
        """Rounding up compounds over 168 hours and overstaffs the week.

        Three weeks of one person and one week of two averages 1.25, which
        must round to 1. Ceiling would say 2 — a 60% overstaff on that hour.
        """
        history = (
            weekly_history(3, [("e1", "mon", "09:00", "10:00")])
            + [roster("2026-03-01", [
                ("e1", "mon", "09:00", "10:00"),
                ("e2", "mon", "09:00", "10:00"),
            ])]
        )
        profile = learn_demand(history, {"e1": "Floor Assistant", "e2": "Floor Assistant"})
        assert profile.headcount["mon"][9] == 1

    def test_overnight_shift_counted_on_both_sides_of_midnight(self):
        history = weekly_history(4, [("e1", "mon", "23:00", "03:00")])
        profile = learn_demand(history, {"e1": "Stocker"})
        assert profile.headcount["mon"][23] == 1
        assert profile.headcount["mon"][0] == 1
        assert profile.headcount["mon"][2] == 1
        assert profile.headcount["mon"][3] == 0

    def test_leave_does_not_create_demand(self):
        """A shift marked as holiday or sick describes absence, not need."""
        history = [
            {"week_start": "2026-01-05", "created_at": "2026-01-05", "approved": True,
             "shifts": [
                 {"employee_id": "e1", "day": "mon", "start": "09:00", "end": "17:00"},
                 {"employee_id": "e2", "day": "mon", "start": "09:00", "end": "17:00",
                  "paid_holiday": True},
             ]},
        ] * 5
        profile = learn_demand(history, {"e1": "Floor Assistant", "e2": "Floor Assistant"})
        assert profile.headcount["mon"][10] == 1

    def test_regenerated_weeks_counted_once(self):
        """A week rostered three times before approval must not weigh triple."""
        drafts = [
            {"week_start": "2026-01-05", "created_at": f"2026-01-0{n}", "approved": True,
             "shifts": [{"employee_id": "e1", "day": "mon", "start": "09:00", "end": "17:00"}]}
            for n in (1, 2, 3)
        ]
        profile = learn_demand(drafts, {"e1": "Floor Assistant"})
        assert profile.weeks_observed == 1
        assert profile.headcount["mon"][10] == 1

    def test_lookback_window_limits_history(self):
        history = weekly_history(30, [("e1", "mon", "09:00", "17:00")])
        profile = learn_demand(history, {"e1": "Floor Assistant"}, lookback_weeks=12)
        assert profile.weeks_observed == 12

    def test_default_lookback_is_half_a_year(self):
        """Long enough that one odd fortnight cannot distort the shape,
        short enough to still follow a season."""
        assert DEFAULT_LOOKBACK_WEEKS == 24

    def test_patterns_learned_and_rare_ones_dropped(self):
        history = weekly_history(6, [
            ("e1", "mon", "09:00", "17:00"),
            ("e2", "tue", "09:00", "17:00"),
        ]) + [roster("2026-04-01", [("e3", "wed", "03:00", "05:00")])]  # a one-off
        profile = learn_demand(history, {})
        keys = {p.key for p in profile.patterns}
        assert "09:00-17:00" in keys
        assert "03:00-05:00" not in keys

    def test_role_mix_recorded(self):
        history = weekly_history(4, [
            ("mgr", "mon", "09:00", "17:00"),
            ("flr", "mon", "09:00", "17:00"),
            ("flr2", "mon", "09:00", "17:00"),
        ])
        profile = learn_demand(history, {
            "mgr": "Manager", "flr": "Floor Assistant", "flr2": "Floor Assistant",
        })
        assert profile.role_target("mon", 10, "Manager") == pytest.approx(1.0)
        assert profile.role_target("mon", 10, "Floor Assistant") == pytest.approx(2.0)

    def test_empty_history_is_unusable(self):
        assert learn_demand([], {}).is_usable is False


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------
class TestFallback:
    def test_too_little_history_falls_back_to_shop_hours(self):
        history = weekly_history(MIN_WEEKS_FOR_DEMAND - 1, [
            ("e1", "mon", "09:00", "17:00"),
        ])
        profile = build_profile(make_shop("09:00", "17:00"), history, {"e1": "Floor Assistant"})
        assert profile.source == "shop_hours"

    def test_enough_history_uses_the_learned_curve(self):
        history = weekly_history(MIN_WEEKS_FOR_DEMAND + 2, [
            ("e1", "mon", "09:00", "17:00"),
        ])
        profile = build_profile(make_shop("09:00", "17:00"), history, {"e1": "Floor Assistant"})
        assert profile.source == "learned"

    def test_fallback_requires_one_person_while_open(self):
        profile = profile_from_shop_hours(make_shop("09:00", "17:00"))
        assert profile.headcount["mon"][9] == 1
        assert profile.headcount["mon"][16] == 1
        assert profile.headcount["mon"][3] == 0

    def test_manual_override_beats_learning(self):
        """An owner who edits their curve keeps it."""
        override = {
            "headcount": {d: [2] * 24 for d in DAYS},
            "patterns": [{"start": "09:00", "end": "17:00", "count": 5, "hours": 8}],
            "weeks_observed": 0,
        }
        history = weekly_history(20, [("e1", "mon", "09:00", "17:00")])
        profile = build_profile(
            make_shop(**{"demand_profile": override}), history, {"e1": "Floor Assistant"}
        )
        assert profile.source == "manual"
        assert profile.required("mon", 3) == 2


# ---------------------------------------------------------------------------
# Demand-driven solving
# ---------------------------------------------------------------------------
def profile_with(headcount_by_hour, patterns, role_mix=None):
    return DemandProfile(
        headcount={d: list(headcount_by_hour) for d in DAYS},
        role_mix={d: (role_mix or {}) for d in DAYS},
        patterns=[ShiftPattern(s, e, c, 0) for s, e, c in patterns],
        weeks_observed=12,
    )


class TestDemandDrivenSolving:
    def test_staffs_up_to_the_curve(self):
        """Three people wanted 09:00-17:00 should produce three shifts."""
        curve = [0] * 24
        for h in range(9, 17):
            curve[h] = 3
        profile = profile_with(curve, [("09:00", "17:00", 50)])
        employees = [make_employee(f"e{i}") for i in range(8)]

        result = solve_roster(
            make_shop("09:00", "17:00"), employees, [], [], [], WEEK, {}, profile
        )
        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        assert len(monday) == 3

    def test_produces_overlapping_shifts(self):
        """The old block model could not do this at all."""
        curve = [0] * 24
        for h in range(6, 22):
            curve[h] = 2
        profile = profile_with(
            curve, [("06:00", "14:00", 40), ("13:00", "21:00", 30), ("14:00", "22:00", 20)]
        )
        employees = [make_employee(f"e{i}") for i in range(12)]

        result = solve_roster(make_shop(), employees, [], [], [], WEEK, {}, profile)
        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        starts = {s["start"] for s in monday}
        assert len(starts) > 1, "expected staggered start times"

    def test_only_starts_at_times_the_shop_actually_works(self):
        """No inventing a 00:00 start the shop has never worked.

        Start times are held to the learned patterns because a start time is
        what a shift IS to the person working it. Finishes are allowed to
        move — closing a one-hour gap at changeover by keeping somebody until
        16:00 is what a manager does, and far better than rostering a whole
        extra person for that hour.
        """
        curve = [0] * 24
        for h in range(6, 22):
            curve[h] = 2
        allowed = {("06:00", "16:00"), ("13:00", "21:00")}
        profile = profile_with(curve, [(s, e, 40) for s, e in allowed])
        employees = [make_employee(f"e{i}") for i in range(12)]

        result = solve_roster(make_shop(), employees, [], [], [], WEEK, {}, profile)
        known_starts = {start for start, _ in allowed}
        for shift in result["shifts"]:
            assert shift["start"] in known_starts, shift

    def test_a_stretched_finish_stays_within_the_shift_limit(self):
        curve = [0] * 24
        for h in range(6, 22):
            curve[h] = 2
        profile = profile_with(
            curve, [("06:00", "16:00", 40), ("13:00", "21:00", 40)]
        )
        employees = [make_employee(f"e{i}") for i in range(12)]

        shop = make_shop()
        result = solve_roster(shop, employees, [], [], [], WEEK, {}, profile)
        for shift in result["shifts"]:
            span = shift.get("span_hours", 0)
            assert span <= shop["max_shift_hours"] + 0.01, shift

    def test_role_saturation_prefers_the_under_target_role(self):
        """The rule: two managers and a supervisor already on means the next
        slot goes to a floor assistant, not a third senior."""
        curve = [0] * 24
        for h in range(9, 17):
            curve[h] = 4
        role_mix = {
            "Manager": [2.0] * 24,
            "Supervisor": [1.0] * 24,
            "Floor Assistant": [1.0] * 24,
        }
        profile = profile_with(curve, [("09:00", "17:00", 50)], role_mix)

        employees = [
            make_employee("m1", "Manager"), make_employee("m2", "Manager"),
            make_employee("m3", "Manager"), make_employee("m4", "Manager"),
            make_employee("s1", "Supervisor"), make_employee("s2", "Supervisor"),
            make_employee("f1", "Floor Assistant"), make_employee("f2", "Floor Assistant"),
        ]
        result = solve_roster(
            make_shop("09:00", "17:00"), employees, [], [], [], WEEK, {}, profile
        )
        monday = {s["employee_id"] for s in result["shifts"] if s["day"] == "mon"}
        roles = [e["role"] for e in employees if e["employee_id"] in monday]

        assert roles.count("Manager") == 2, "should not stack a third manager"
        assert roles.count("Supervisor") == 1, "should not stack a second supervisor"
        assert roles.count("Floor Assistant") == 1

    def test_preference_not_relaxed_while_another_pattern_would_work(self):
        """Relaxation must be a last resort across ALL patterns, not the first.

        The earlier ordering tried relax=False then relax=True on each pattern
        in turn, so it would override somebody's day off on pattern one even
        when pattern two had a willing employee.
        """
        curve = [0] * 24
        for h in range(9, 17):
            curve[h] = 1
        profile = profile_with(curve, [("09:00", "17:00", 99), ("09:00", "13:00", 50)])
        employees = [make_employee("picky", days_off=["mon"]), make_employee("willing")]

        result = solve_roster(
            make_shop("09:00", "17:00"), employees, [], [], [], WEEK, {}, profile
        )
        monday = {s["employee_id"] for s in result["shifts"] if s["day"] == "mon"}
        assert "picky" not in monday

    def test_strict_days_off_leaves_a_reported_gap(self):
        """Strict is the default: the day off holds and the gap is explained.

        The message must name who blocked it, so the manager knows whose day
        off to renegotiate rather than being told "nobody is available".
        """
        curve = [0] * 24
        for h in range(9, 17):
            curve[h] = 1
        profile = profile_with(curve, [("09:00", "17:00", 99)])
        employees = [make_employee("only", days_off=["mon"])]

        result = solve_roster(
            make_shop("09:00", "17:00"), employees, [], [], [], WEEK, {}, profile
        )
        assert not [s for s in result["shifts"] if s["day"] == "mon"]
        criticals = [i for i in result["critical_issues"] if "mon" in i]
        assert criticals
        assert any("Employee only" in i and "strict" in i for i in criticals)

    def test_overridden_preference_is_reported_when_not_strict(self):
        """With strict off, the override happens but must stay visible."""
        curve = [0] * 24
        for h in range(9, 17):
            curve[h] = 1
        profile = profile_with(curve, [("09:00", "17:00", 99)])
        shop = make_shop("09:00", "17:00")
        shop["strict_days_off"] = False
        employees = [make_employee("only", days_off=["mon"])]

        result = solve_roster(shop, employees, [], [], [], WEEK, {}, profile)
        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        assert monday, "coverage still has to happen when strict is off"
        assert any("requesting it off" in i for i in result["issues"])

    def test_oversubscribed_day_warned_upfront(self):
        """Most of the team wanting the same day off is a rota problem the
        manager should hear about, not discover from the finished roster."""
        curve = [0] * 24
        for h in range(9, 17):
            curve[h] = 4
        profile = profile_with(curve, [("09:00", "17:00", 99)])
        employees = [make_employee(f"e{i}", days_off=["mon"]) for i in range(5)] + [
            make_employee("free")
        ]

        result = solve_roster(
            make_shop("09:00", "17:00"), employees, [], [], [], WEEK, {}, profile
        )
        assert any("requested the day off" in i for i in result["issues"])

    def test_hours_are_spread_rather_than_maxing_out_a_few(self):
        """Greedy assignment without a fairness term pins its favourites at
        their cap and leaves everyone else idle. Measured on the reference
        shop that produced 5 people at 40h and 11 with no shifts at all."""
        curve = [0] * 24
        for h in range(6, 22):
            curve[h] = 3
        profile = profile_with(
            curve, [("06:00", "14:00", 40), ("13:00", "21:00", 35), ("14:00", "22:00", 30)]
        )
        employees = [make_employee(f"e{i}") for i in range(12)]

        result = solve_roster(make_shop(), employees, [], [], [], WEEK, {}, profile)
        hours = result["per_employee_hours"]
        idle = [e for e, h in hours.items() if h == 0]
        maxed = [e for e, h in hours.items() if h >= 39]

        assert not maxed, "nobody should be pinned at their cap while others sit idle"
        assert len(idle) <= 2, f"work should be spread; {len(idle)} people got nothing"

    def test_fairness_does_not_override_seniority_within_a_band(self):
        """Fill ratio is banded so a rounding difference cannot outrank
        seniority. Two people with no hours yet are in the same band, so
        RULE 1 decides between them."""
        curve = [0] * 24
        for h in range(9, 17):
            curve[h] = 1
        profile = profile_with(curve, [("09:00", "17:00", 50)], {})
        employees = [make_employee("floor", "Floor Assistant"), make_employee("mgr", "Manager")]

        result = solve_roster(
            make_shop("09:00", "17:00"), employees, [], [], [], WEEK, {}, profile
        )
        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        assert monday[0]["employee_id"] == "mgr"

    def test_part_timers_are_not_overloaded_relative_to_contract(self):
        """Fairness is measured against each person's own contracted hours,
        not absolute hours — otherwise part-timers look permanently 'owed'
        work and absorb shifts they are not contracted for."""
        curve = [0] * 24
        for h in range(6, 22):
            curve[h] = 2
        profile = profile_with(curve, [("06:00", "14:00", 40), ("14:00", "22:00", 30)])
        employees = [
            make_employee("full1", max_hours=40),
            make_employee("full2", max_hours=40),
            make_employee("part", max_hours=16),
        ]

        result = solve_roster(make_shop(), employees, [], [], [], WEEK, {}, profile)
        assert result["per_employee_hours"]["part"] <= 16

    def test_seniority_still_wins_when_roles_are_equally_short(self):
        """RULE 1 survives: role deficit decides the role, seniority the person."""
        curve = [0] * 24
        for h in range(9, 17):
            curve[h] = 1
        profile = profile_with(curve, [("09:00", "17:00", 50)], {})  # no role targets
        employees = [make_employee("floor", "Floor Assistant"), make_employee("mgr", "Manager")]

        result = solve_roster(
            make_shop("09:00", "17:00"), employees, [], [], [], WEEK, {}, profile
        )
        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        assert monday[0]["employee_id"] == "mgr"

    def test_understaffing_reported_not_hidden(self):
        curve = [0] * 24
        for h in range(9, 17):
            curve[h] = 5
        profile = profile_with(curve, [("09:00", "17:00", 50)])
        employees = [make_employee("e1")]  # only one person for a demand of five

        result = solve_roster(
            make_shop("09:00", "17:00"), employees, [], [], [], WEEK, {}, profile
        )
        assert result["issues"], "shortfall against the curve must be visible"

    def test_no_curve_no_shifts_but_floor_still_enforced(self):
        """A zero curve must not leave the shop unattended — the coverage
        floor is a separate, non-negotiable guarantee."""
        profile = profile_with([0] * 24, [("09:00", "17:00", 50)])
        employees = [make_employee("e1")]

        result = solve_roster(
            make_shop("09:00", "17:00"), employees, [], [], [], WEEK, {}, profile
        )
        monday = [s for s in result["shifts"] if s["day"] == "mon"]
        assert monday, "coverage floor should place someone even with zero demand"


# ---------------------------------------------------------------------------
# Constraints are never traded away for demand
# ---------------------------------------------------------------------------
class TestConstraintsHoldUnderDemand:
    def test_hour_caps_respected(self):
        curve = [0] * 24
        for h in range(6, 22):
            curve[h] = 4
        profile = profile_with(curve, [("06:00", "16:00", 40), ("13:00", "21:00", 30)])
        employees = [make_employee(f"e{i}", max_hours=16) for i in range(6)]

        result = solve_roster(make_shop(), employees, [], [], [], WEEK, {}, profile)
        for employee_id, hours in result["per_employee_hours"].items():
            assert hours <= 16, f"{employee_id} exceeded their cap"

    def test_minor_curfew_respected(self):
        curve = [0] * 24
        for h in range(24):
            curve[h] = 3
        profile = profile_with(curve, [("06:00", "16:00", 40), ("16:00", "00:00", 30)])
        employees = [make_employee("kid", age=15)] + [make_employee(f"e{i}") for i in range(6)]

        result = solve_roster(make_shop(), employees, [], [], [], WEEK, {}, profile)
        for shift in result["shifts"]:
            if shift["employee_id"] == "kid":
                assert to_minutes(shift["start"]) >= to_minutes("08:00")
                assert to_minutes(shift["end"]) <= to_minutes("19:00")

    def test_leave_respected(self):
        curve = [0] * 24
        for h in range(9, 17):
            curve[h] = 2
        profile = profile_with(curve, [("09:00", "17:00", 50)])
        employees = [make_employee("away"), make_employee("here")]
        holidays = [{"date": WEEK, "end_date": WEEK, "label": "Holiday",
                     "scope": "employee", "employee_id": "away"}]

        result = solve_roster(
            make_shop("09:00", "17:00"), employees, holidays, [], [], WEEK, {}, profile
        )
        # They appear as paid holiday, but must not be given work.
        working = {
            s["employee_id"] for s in result["shifts"]
            if s["day"] == "mon" and not s.get("paid_holiday")
        }
        assert "away" not in working

    def test_nobody_double_booked_in_a_day(self):
        curve = [0] * 24
        for h in range(6, 22):
            curve[h] = 3
        profile = profile_with(curve, [("06:00", "14:00", 40), ("14:00", "22:00", 30)])
        employees = [make_employee(f"e{i}") for i in range(10)]

        result = solve_roster(make_shop(), employees, [], [], [], WEEK, {}, profile)
        seen = set()
        for shift in result["shifts"]:
            key = (shift["employee_id"], shift["day"])
            assert key not in seen, f"{key} rostered twice in one day"
            seen.add(key)

    def test_shop_holiday_still_clears_the_day(self):
        curve = [0] * 24
        for h in range(9, 17):
            curve[h] = 3
        profile = profile_with(curve, [("09:00", "17:00", 50)])
        employees = [make_employee(f"e{i}") for i in range(5)]
        holidays = [{"date": WEEK, "end_date": WEEK, "label": "Closed", "scope": "shop"}]

        result = solve_roster(
            make_shop("09:00", "17:00"), employees, holidays, [], [], WEEK, {}, profile
        )
        assert not [s for s in result["shifts"] if s["day"] == "mon"]

    def test_terminates_when_demand_is_unsatisfiable(self):
        """Everyone unavailable must end the loop, not spin it."""
        curve = [0] * 24
        for h in range(24):
            curve[h] = 10
        profile = profile_with(curve, [("06:00", "16:00", 40)])
        employees = [make_employee("kid", age=15, max_hours=4)]

        result = solve_roster(make_shop(), employees, [], [], [], WEEK, {}, profile)
        assert isinstance(result["shifts"], list)
        assert result["critical_issues"]


# ---------------------------------------------------------------------------
# One roster per week
# ---------------------------------------------------------------------------
class TestOneRosterPerWeek:
    """A week counted twice pulls twice as hard on everything learned.

    The API refuses to leave two approved rosters on one week, but the maths
    is deduplicated too — a duplicate that arrives some other way (an import
    landing on a week that was already generated and approved) must not skew
    the result.
    """

    @staticmethod
    def _roster(week, created_at, shifts):
        return {
            "week_start": week, "created_at": created_at, "approved": True,
            "shifts": [
                {"employee_id": e, "day": d, "start": s, "end": t}
                for e, d, s, t in shifts
            ],
        }

    def test_a_duplicated_week_is_counted_once(self):
        from app.services.learning import compute_weights

        week = self._roster("2026-06-01", "2026-06-02T10:00", [("e1", "mon", "09:00", "17:00")])
        once = compute_weights([week])
        twice = compute_weights([week, dict(week)])

        assert once == twice, "the same week listed twice must not double the counts"
        assert once["day"]["e1"]["mon"] == 1

    def test_the_newest_roster_for_a_week_wins(self):
        from app.services.learning import latest_per_week

        old = self._roster("2026-06-01", "2026-06-01T09:00", [("e1", "mon", "09:00", "17:00")])
        new = self._roster("2026-06-01", "2026-06-05T09:00", [("e2", "mon", "06:00", "14:00")])

        assert latest_per_week([old, new]) == [new]
        assert latest_per_week([new, old]) == [new]

    def test_distinct_weeks_are_all_kept(self):
        from app.services.learning import latest_per_week

        weeks = [
            self._roster("2026-06-01", "x", []),
            self._roster("2026-06-08", "x", []),
            self._roster("2026-06-15", "x", []),
        ]
        assert len(latest_per_week(weeks)) == 3

    def test_a_roster_with_no_week_is_ignored(self):
        from app.services.learning import latest_per_week

        assert latest_per_week([{"shifts": [], "created_at": "x"}]) == []


# ---------------------------------------------------------------------------
# Not enough staff
# ---------------------------------------------------------------------------
class TestUnderstaffed:
    """Running out of people is a cause the old messages could not name.

    A shop needing 109 hours of cover from 60 hours of staff was told
    "everyone is on leave, at their hour cap, or curfew-restricted" sixty-six
    times — sending the manager hunting for holidays and under-16s that did
    not exist, when the answer was simply that they had two employees.
    """

    def _solve(self, staff, open_at="06:00", close_at="23:00"):
        curve = [0] * 24
        for h in range(int(open_at[:2]), int(close_at[:2])):
            curve[h] = 1
        profile = profile_with(curve, [(open_at, close_at, 99)])
        return solve_roster(
            make_shop(open_at, close_at), staff, [], [], [], WEEK, {}, profile
        )

    def test_the_shortfall_is_stated_once_up_front(self):
        result = self._solve([make_employee("solo", max_hours=20)])
        headline = result["critical_issues"][0]

        assert headline.startswith("NOT ENOUGH STAFF")
        assert "119h" in headline, "17h a day, seven days"
        assert "20h" in headline
        assert "short by 99h" in headline

    def test_it_names_headcount_rather_than_blaming_leave(self):
        result = self._solve([make_employee("solo", max_hours=20)])
        hourly = [i for i in result["critical_issues"] if i.startswith("CRITICAL")]

        assert hourly
        assert all("not enough staff hours" in i for i in hourly)
        assert not any("on leave" in i for i in hourly), (
            "nobody is on leave — saying so sends the manager somewhere useless"
        )

    def test_a_week_that_adds_up_says_nothing_about_staffing(self):
        """It must not cry wolf on a merely tight week."""
        staff = [make_employee(f"e{i}", max_hours=40) for i in range(5)]
        result = self._solve(staff)

        assert not [
            i for i in result["critical_issues"] if i.startswith("NOT ENOUGH STAFF")
        ]

    def test_a_named_day_off_still_wins_over_the_arithmetic(self):
        """Whose day off to renegotiate is more actionable than a total."""
        result = self._solve([make_employee("only", days_off=["mon"], max_hours=20)])
        monday = [i for i in result["critical_issues"] if "mon " in i]

        assert any("strict" in i for i in monday)

    def test_inactive_staff_do_not_count_towards_capacity(self):
        staff = [make_employee(f"e{i}", max_hours=40) for i in range(5)]
        for employee in staff[1:]:
            employee["is_active"] = False
        result = self._solve(staff)

        assert result["critical_issues"][0].startswith("NOT ENOUGH STAFF")


class TestRestBetweenShiftsInGeneration:
    """The solver must never produce a roster that breaks the rest rule.

    Checked against 30 weeks of the manager's real rosters before this was
    made a constraint: 99.6% of consecutive pairs already left the full
    eleven hours, so enforcing it does not stop the solver reproducing the
    history it learns from.
    """

    def _solve(self, staff, open_at="06:00", close_at="23:00"):
        curve = [0] * 24
        for h in range(int(open_at[:2]), int(close_at[:2])):
            curve[h] = 1
        profile = profile_with(curve, [(open_at, close_at, 99)])
        return solve_roster(
            make_shop(open_at, close_at), staff, [], [], [], WEEK, {}, profile
        )

    @staticmethod
    def _spans(result):
        """Every shift as minutes from Monday, per employee."""
        from app.services.scheduler import DAYS, to_minutes
        out = {}
        for s in result["shifts"]:
            if not (s.get("start") and s.get("end")):
                continue
            base = DAYS.index(s["day"]) * 24 * 60
            first, last = base + to_minutes(s["start"]), base + to_minutes(s["end"])
            if last <= first:
                last += 24 * 60
            out.setdefault(s["employee_id"], []).append((first, last))
        return out

    def test_no_generated_roster_leaves_under_eleven_hours(self):
        from app.services.scheduler import MIN_REST_HOURS

        staff = [make_employee(f"e{i}", max_hours=40) for i in range(8)]
        result = self._solve(staff)

        for employee_id, spans in self._spans(result).items():
            spans.sort()
            for (_, ends), (starts, _) in zip(spans, spans[1:]):
                gap = (starts - ends) / 60
                assert gap >= MIN_REST_HOURS, (
                    f"{employee_id} got {gap:.1f}h rest"
                )

    def test_it_holds_when_the_shop_is_open_around_the_clock(self):
        """Overnight shifts are where a clock-time comparison goes wrong."""
        from app.services.scheduler import MIN_REST_HOURS

        curve = [1] * 24
        profile = profile_with(curve, [("22:00", "06:00", 40), ("06:00", "14:00", 40),
                                       ("14:00", "22:00", 40)])
        staff = [make_employee(f"e{i}", max_hours=40) for i in range(10)]
        result = solve_roster(
            make_shop("00:00", "23:59"), staff, [], [], [], WEEK, {}, profile
        )

        for employee_id, spans in self._spans(result).items():
            spans.sort()
            for (_, ends), (starts, _) in zip(spans, spans[1:]):
                assert (starts - ends) / 60 >= MIN_REST_HOURS, employee_id

    def test_a_shop_may_set_a_longer_rest_period(self):
        shop = make_shop("06:00", "23:00")
        shop["min_rest_hours"] = 13
        curve = [0] * 24
        for h in range(6, 23):
            curve[h] = 1
        profile = profile_with(curve, [("06:00", "23:00", 99)])
        staff = [make_employee(f"e{i}", max_hours=40) for i in range(8)]
        result = solve_roster(shop, staff, [], [], [], WEEK, {}, profile)

        for employee_id, spans in self._spans(result).items():
            spans.sort()
            for (_, ends), (starts, _) in zip(spans, spans[1:]):
                assert (starts - ends) / 60 >= 13, employee_id


class TestADeliberateChangeIsFollowed:
    """The scenario the manager described.

    Cut two people from the evening and keep rostering it that way. Under a
    flat average every week counted the same, so three months later the
    profile still said five — and still BUILT rosters with five, so two
    shifts were deleted every week. The product was generating its own edit
    burden.
    """

    def _weeks(self, count, people, end):
        """`count` weeks ending at `end`, with `people` on Monday evening."""
        from datetime import datetime as dt, timedelta as td

        last = dt.strptime(end, "%Y-%m-%d").date()
        out = []
        for i in range(count):
            week = (last - td(weeks=i)).isoformat()
            out.append(roster(week, [
                (f"e{n}", "mon", "17:00", "21:00") for n in range(people)
            ]))
        return out

    def test_the_recent_pattern_wins_within_about_four_months(self):
        """Sixteen weeks of the new pattern settles it.

        NOT eight — that was the first assertion here and it failed. With an
        8-week half-life, eight weeks of three against sixteen of five comes
        to 3.86, which rounds to 4, the same as a flat average. Halving the
        half-life to four weeks would have passed it, and would also have let
        a single odd week move the shape (the next test). So the honest
        number is four months, not two, and the constant stays where the
        stability test wants it.
        """
        recent = self._weeks(16, 3, "2026-06-29")
        older = self._weeks(16, 5, "2026-03-09")

        profile = learn_demand(recent + older, {}, for_week="2026-07-06")
        assert profile.required("mon", 18) == 3

    def test_one_odd_week_does_not_move_the_shape(self):
        """The other half. Recency must not mean the last week wins."""
        odd = self._weeks(1, 9, "2026-06-29")
        normal = self._weeks(20, 4, "2026-06-22")

        profile = learn_demand(odd + normal, {}, for_week="2026-07-06")
        assert profile.required("mon", 18) == 4

    def test_it_moves_towards_the_new_pattern_immediately(self):
        """Even before it flips the rounded number, it is moving.

        Asserted against the flat average of the same data, so this measures
        the CHANGE rather than restating today's output — the number a flat
        average would give is the thing being fixed.
        """
        recent = self._weeks(16, 3, "2026-06-29")
        older = self._weeks(16, 5, "2026-03-09")

        flat = (16 * 3 + 16 * 5) / 32          # 4.0
        weighted = learn_demand(recent + older, {}, for_week="2026-07-06")
        assert weighted.required("mon", 18) < flat


class TestLastYearIsNotDrift:
    """Christmas is not a permanent change, and must not be read as one.

    A recency-weighted average sees a busy December as growth, then sees
    January as collapse. The defence is that the same week last year keeps a
    weight floor.
    """

    def _week(self, week_start, people):
        return roster(week_start, [
            (f"e{n}", "mon", "17:00", "21:00") for n in range(people)
        ])

    def test_the_same_week_last_year_still_counts(self):
        from datetime import datetime as dt, timedelta as td

        target = "2026-12-21"
        last_year = (dt.strptime(target, "%Y-%m-%d").date() - td(weeks=52)).isoformat()

        # Quiet all autumn, but last December ran seven.
        history = [
            self._week(
                (dt.strptime(target, "%Y-%m-%d").date() - td(weeks=i)).isoformat(), 3,
            )
            for i in range(1, 13)
        ] + [self._week(last_year, 7)]

        profile = learn_demand(history, {}, for_week=target)
        assert profile.seasonal_weeks == 1, (
            "last year's matching week was not found, so nothing here knows "
            "about Christmas"
        )

        # It is FOUND and it counts, but one week from last year does not
        # outvote twelve recent ones — and should not. A single observation
        # is not a season. This is why the panel reports last year's figure
        # to the manager instead of the profile silently adjusting for it:
        # with one year of history there is exactly one data point, and the
        # person who ran the shop last December knows more about it than an
        # average of one.
        with_echo = profile.required("mon", 18)
        without = learn_demand(
            [r for r in history if r["week_start"] != last_year], {},
            for_week=target,
        ).required("mon", 18)
        assert with_echo >= without

    def test_no_yearly_history_means_no_seasonal_claim(self):
        """A shop with six months cannot know anything about December, and
        must not imply that it does."""
        history = weekly_history(12, [("e1", "mon", "09:00", "17:00")])
        profile = learn_demand(history, {}, for_week="2026-12-21")
        assert profile.seasonal_weeks == 0


class TestComparingAWeekToUsual:
    """The panel beside Advisories: what is different, and by how much.

    Never a refusal. Running leaner is a decision the manager is entitled to
    make — what they should not do is make it by accident, which is what
    happens when nothing mentions that the evening normally has three people.
    """

    def _profile(self, people=3):
        from datetime import datetime as dt, timedelta as td

        last = dt.strptime("2026-06-29", "%Y-%m-%d").date()
        history = [
            roster((last - td(weeks=i)).isoformat(), [
                (f"e{n}", "mon", "17:00", "21:00") for n in range(people)
            ])
            for i in range(12)
        ]
        return learn_demand(history, {}, for_week="2026-07-06")

    def test_a_thinner_evening_is_reported_with_both_numbers(self):
        from app.services.demand import compare_to_usual

        notes = compare_to_usual(
            [{"employee_id": "e0", "day": "mon", "start": "17:00", "end": "21:00"}],
            self._profile(3),
        )
        evening = [n for n in notes if n["day"] == "mon"]
        assert evening, "one person against a usual three said nothing"
        assert evening[0]["have"] == 1
        assert evening[0]["usual"] == 3
        assert "usually runs 3" in evening[0]["message"]

    def test_matching_the_usual_shape_says_nothing(self):
        """Silence is the normal case, and a panel that always has something
        in it is a panel nobody reads."""
        from app.services.demand import compare_to_usual

        full = [
            {"employee_id": f"e{n}", "day": "mon", "start": "17:00", "end": "21:00"}
            for n in range(3)
        ]
        assert compare_to_usual(full, self._profile(3)) == []

    def test_consecutive_hours_become_one_note(self):
        """Hour by hour it would be four lines for one evening, and twenty a
        day across the week — the one that mattered would be buried."""
        from app.services.demand import compare_to_usual

        notes = compare_to_usual(
            [{"employee_id": "e0", "day": "mon", "start": "17:00", "end": "21:00"}],
            self._profile(3),
        )
        assert len(notes) == 1
        assert notes[0]["from_hour"] == 17 and notes[0]["to_hour"] == 21

    def test_a_single_short_hour_is_not_worth_a_sentence(self):
        """A changeover hour is already handled by stretching a neighbouring
        shift. Reporting it too buries the real gaps."""
        from app.services.demand import compare_to_usual

        covered = [
            {"employee_id": "e0", "day": "mon", "start": "17:00", "end": "20:00"},
            {"employee_id": "e1", "day": "mon", "start": "17:00", "end": "20:00"},
            {"employee_id": "e2", "day": "mon", "start": "17:00", "end": "20:00"},
        ]
        # Everyone leaves an hour early, so only 20:00-21:00 is short.
        assert compare_to_usual(covered, self._profile(3)) == []

    def test_no_history_means_no_opinion(self):
        from app.services.demand import DemandProfile, compare_to_usual

        assert compare_to_usual(
            [{"employee_id": "e0", "day": "mon", "start": "09:00", "end": "17:00"}],
            DemandProfile(source="none"),
        ) == []


# ---------------------------------------------------------------------------
# The shop's own convention for where a shift finishes
# ---------------------------------------------------------------------------
class TestFinishGranularity:
    """Rounding a contract trim to a whole hour is right for a shop that ends
    shifts on the hour and wrong for one that does not.

    Top Oil ends a shift on a half hour once in 555 shifts, so whole hours
    match what its manager writes. Hardcoding that would have quietly dragged
    every other shop's rota toward a convention it does not use — the §10b
    trap of treating one shop's numbers as everyone's.
    """

    @staticmethod
    def _shifts(ends, count=60):
        """`count` shifts cycling through `ends`, in one roster."""
        return [{
            "week_start": "2026-06-29", "approved": True,
            "shifts": [
                {"employee_id": f"e{i}", "day": "mon",
                 "start": "06:00", "end": ends[i % len(ends)]}
                for i in range(count)
            ],
        }]

    def test_a_shop_that_finishes_on_the_hour_gets_whole_hours(self):
        from app.services.demand import finish_granularity

        assert finish_granularity(self._shifts(["14:00", "16:00", "22:00"])) == 60

    def test_a_shop_that_finishes_on_half_hours_keeps_them(self):
        """The case that made this necessary — 10:30 and 12:30 finishes."""
        from app.services.demand import finish_granularity

        assert finish_granularity(self._shifts(["10:30", "12:30", "14:00"])) == 30

    def test_one_odd_half_hour_does_not_move_the_convention(self):
        """A shop is not on half hours because of a single exception. Top Oil
        has exactly one in 555 and must still answer 60."""
        from app.services.demand import finish_granularity

        rosters = self._shifts(["14:00"], count=99)
        rosters[0]["shifts"].append(
            {"employee_id": "x", "day": "mon", "start": "06:00", "end": "14:30"}
        )
        assert finish_granularity(rosters) == 60

    def test_quarter_hours_are_recognised_too(self):
        from app.services.demand import finish_granularity

        assert finish_granularity(self._shifts(["14:15", "16:45", "22:00"])) == 15

    def test_too_little_history_falls_back_to_whole_hours(self):
        """Not enough shifts to have a habit. The default must not be inferred
        from a handful of them."""
        from app.services.demand import finish_granularity

        assert finish_granularity(self._shifts(["10:30"], count=6)) == 60
        assert finish_granularity([]) == 60

    def test_the_profile_carries_it(self):
        from app.services.demand import build_profile

        from app.services.scheduler import DAYS

        history = weekly_history(8, [
            (f"e{i}", day, start, end)
            for day in DAYS
            for i, (start, end) in enumerate(
                [("06:00", "14:30"), ("14:30", "22:30")])
        ])
        profile = build_profile(make_shop(), history, {})
        assert profile.edge_minutes == 30, (
            "a shop whose every shift ends on a half hour should not be told "
            "its convention is whole hours"
        )

    def test_it_survives_a_round_trip(self):
        from app.services.demand import DemandProfile

        assert DemandProfile.from_dict(
            DemandProfile(edge_minutes=30).to_dict()
        ).edge_minutes == 30
