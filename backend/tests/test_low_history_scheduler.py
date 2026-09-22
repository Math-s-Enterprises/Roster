"""Regression tests for generation before demand has four approved weeks."""

import pytest

from app.services.demand import build_profile
from app.services.scheduler import DAYS, _RosterBuilder, solve_roster, to_minutes

TARGET_WEEK = "2026-09-14"


def shop(open_time="06:00", close_time="22:00", *, max_hours=9,
         monday_only=False, templates=None, supervisory=False):
    value = {
        "shop_id": "low_history",
        "hours": [
            {
                "day": day,
                "open": open_time,
                "close": close_time,
                "closed": monday_only and day != "mon",
            }
            for day in DAYS
        ],
        "min_shift_hours": 4,
        "max_shift_hours": max_hours,
        "strict_days_off": False,
        "shift_templates": templates or [],
        "role_hierarchy": ["Manager", "Floor Assistant"],
    }
    if supervisory:
        value["supervisory_roles"] = ["Manager"]
    return value


def employee(index, role="Floor Assistant", *, full_time=False, max_hours=40):
    value = {
        "employee_id": f"e{index}",
        "name": f"E{index}",
        "role": role,
        "age": 25,
        "hourly_rate": 15,
        "max_weekly_hours": max_hours,
        "preferred_days_off": [],
        "departments": ["Shop Floor"],
        "employment_type": "hourly",
        "is_active": True,
    }
    if full_time:
        value.update(
            employment_type="full_time_contract",
            contract_span_hours=42.5,
            contract_span_tolerance=1.5,
            max_weekly_hours=42.5,
        )
    return value


def approved(week, shapes):
    return {
        "week_start": week,
        "created_at": week,
        "approved": True,
        "shifts": [
            {"employee_id": f"e{i}", "day": "mon", "start": start, "end": end}
            for i, (start, end) in enumerate(shapes)
        ],
    }


def finishes_after(shift, close="22:00"):
    start = to_minutes(shift["start"])
    end = to_minutes(shift["end"])
    if end <= start:
        end += 24 * 60
    return end > to_minutes(close)


def roles(team):
    return {person["employee_id"]: person["role"] for person in team}


def test_zero_history_ignores_a_post_close_template():
    current_shop = shop(
        templates=[{"name": "Late", "start": "14:00", "end": "23:00", "min_staff": 1}],
        supervisory=True,
    )
    team = [employee(0, "Manager", full_time=True), employee(1, "Manager")]
    team += [employee(i) for i in range(2, 10)]

    profile = build_profile(current_shop, [], roles(team), for_week=TARGET_WEEK)
    result = solve_roster(
        current_shop, team, [], [], [], TARGET_WEEK,
        demand=profile, history_rosters=[],
    )

    assert ("14:00", "23:00") not in [
        (pattern.start, pattern.end) for pattern in profile.patterns
    ]
    assert not [shift for shift in result["shifts"] if finishes_after(shift)]


def test_zero_history_contract_fitting_stops_at_close():
    current_shop = shop(supervisory=True)
    team = [employee(0, "Manager", full_time=True), employee(1, "Manager")]
    team += [employee(i) for i in range(2, 10)]

    profile = build_profile(current_shop, [], roles(team), for_week=TARGET_WEEK)
    result = solve_roster(
        current_shop, team, [], [], [], TARGET_WEEK,
        demand=profile, history_rosters=[],
    )

    assert not [shift for shift in result["shifts"] if finishes_after(shift)]


@pytest.mark.parametrize("use_arrivals", [False, True])
def test_four_weeks_support_and_snap_a_post_close_shape(monkeypatch, use_arrivals):
    monkeypatch.setattr(_RosterBuilder, "USE_ARRIVALS", use_arrivals)
    current_shop = shop(monday_only=True)
    team = [employee(i) for i in range(6)]
    shapes = [
        ("06:00", "14:00"), ("06:00", "14:00"),
        ("14:00", "22:00"), ("14:00", "22:00"),
        ("14:00", "22:00"), ("22:45", "23:45"),
    ]
    history = [approved(week, shapes) for week in (
        "2026-08-17", "2026-08-24", "2026-08-31", "2026-09-07",
    )]

    profile = build_profile(current_shop, history, roles(team), for_week=TARGET_WEEK)
    result = solve_roster(
        current_shop, team, [], [], [], TARGET_WEEK,
        demand=profile, history_rosters=history,
    )
    post_close = [shift for shift in result["shifts"] if finishes_after(shift)]

    assert profile.supports_post_close("mon", "22:30", "23:30")
    assert [(shift["start"], shift["end"]) for shift in post_close] == [
        ("22:30", "23:30")
    ]


def test_post_close_shape_needs_four_occurrences_not_just_four_total_weeks():
    current_shop = shop(monday_only=True)
    team = [employee(i) for i in range(6)]
    shapes = [
        ("06:00", "14:00"), ("06:00", "14:00"),
        ("14:00", "22:00"), ("14:00", "22:00"),
        ("14:00", "22:00"), ("22:45", "23:45"),
    ]
    history = [
        approved("2026-08-17", shapes[:-1]),
        *[
            approved(week, shapes) for week in (
                "2026-08-24", "2026-08-31", "2026-09-07",
            )
        ],
    ]

    profile = build_profile(current_shop, history, roles(team), for_week=TARGET_WEEK)
    result = solve_roster(
        current_shop, team, [], [], [], TARGET_WEEK,
        demand=profile, history_rosters=history,
    )

    assert profile.post_close_slots == {}
    assert not [shift for shift in result["shifts"] if finishes_after(shift)]


def test_one_prior_week_keeps_its_headcount_but_not_its_exact_shapes():
    current_shop = shop(
        "04:00", "22:00", max_hours=6, monday_only=True,
    )
    team = [employee(i, max_hours=12) for i in range(7)]
    shapes = (
        [("04:00", "10:00")] * 3
        + [("10:00", "16:00")] * 2
        + [("16:00", "22:00")] * 2
    )
    prior = approved("2026-09-07", shapes)
    future = approved("2026-09-21", [("04:00", "10:00")] * 7)

    profile = build_profile(
        current_shop, [prior, future], roles(team), for_week=TARGET_WEEK,
    )
    result = solve_roster(
        current_shop, team, [], [], [], TARGET_WEEK,
        demand=profile, history_rosters=[prior, future],
    )
    monday = [shift for shift in result["shifts"] if shift["day"] == "mon"]

    assert profile.source == "partial_history"
    assert profile.weeks_observed == 1  # the future week was not read backwards
    assert profile.staff_target("mon") == 7
    assert profile.slots_for("mon") == []  # four-week bar still protects shapes
    assert len(monday) == 7
