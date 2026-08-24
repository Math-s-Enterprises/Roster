"""Finding cover for a sick shift, and paid sick entitlement.

The solver refuses to break a rule, which is right when building a week from
nothing. At 6am with one person off and the shop opening in an hour it is
useless: the manager's question is which rule to bend and who to ask. These
tests are about giving them that answer rather than "nobody is available".
"""
import pytest

from app.services.sick_balance import compute_sick_balance, paid_sick_days
from app.services.sick_cover import rank_cover

WEEK = "2026-03-02"
SHOP = {"shop_id": "s", "role_hierarchy": ["Manager", "Supervisor", "Stocker",
                                           "Floor Assistant"]}


def employee(eid, name=None, role="Floor Assistant", **extra):
    return {
        "employee_id": eid, "name": name or eid.title(), "role": role,
        "age": 30, "hourly_rate": 13.0, "max_weekly_hours": 40,
        "preferred_days_off": [], "departments": ["Shop Floor"],
        "is_active": True, **extra,
    }


def shift(eid, day="mon", start="06:00", end="14:00"):
    span = 8.0
    return {
        "employee_id": eid, "day": day, "start": start, "end": end,
        "span_hours": span, "break_minutes": 30, "paid_hours": span - 0.5,
    }


def cover(employees, shifts, absent="sick_one", day="thu", **kw):
    return rank_cover(
        shop=kw.pop("shop", SHOP),
        employees=employees,
        roster={"week_start": WEEK, "shifts": shifts},
        absent_id=absent, day=day, start="06:00", end="14:00",
        week_start=WEEK, **kw,
    )


class TestNeverEmpty:
    """The whole point: it always names somebody while anyone could do it."""

    def test_somebody_clean_is_offered_first(self):
        out = cover(
            [employee("sick_one"), employee("jane")],
            [shift("sick_one", "thu")],
        )
        assert [c["name"] for c in out["candidates"]] == ["Jane"]
        assert out["candidates"][0]["clean"] is True
        assert out["clean"]

    def test_a_rule_breaker_is_still_offered_when_nobody_is_clean(self):
        """"Nobody is available" is never the answer if somebody could."""
        maxed = employee("tired", max_weekly_hours=8)
        out = cover(
            [employee("sick_one"), maxed],
            [shift("sick_one", "thu"), shift("tired", "mon")],
        )
        assert [c["name"] for c in out["candidates"]] == ["Tired"]
        assert out["candidates"][0]["clean"] is False
        assert out["clean"] == []

    def test_each_break_says_which_rule_and_by_how_much(self):
        out = cover(
            [employee("sick_one"), employee("tired", max_weekly_hours=8)],
            [shift("sick_one", "thu"), shift("tired", "mon")],
        )
        breaks = out["candidates"][0]["breaks"]
        assert [b["rule"] for b in breaks] == ["weekly_hours"]
        assert "over their 8h limit" in breaks[0]["detail"]

    def test_a_sixth_day_is_offered_and_labelled(self):
        busy = employee("busy")
        out = cover(
            [employee("sick_one"), busy],
            [shift("sick_one", "thu")] + [
                shift("busy", d) for d in ("mon", "tue", "wed", "fri", "sat")
            ],
        )
        rules = [b["rule"] for b in out["candidates"][0]["breaks"]]
        assert "days" in rules


class TestHardFloor:
    """Four things are never offered, however short the shop is."""

    def test_a_minor_is_never_offered_a_curfew_shift(self):
        out = cover(
            [employee("sick_one"), employee("kid", age=15)],
            [shift("sick_one", "thu")],
        )
        assert out["candidates"] == []

    def test_somebody_on_booked_leave_is_never_offered(self):
        out = cover(
            [employee("sick_one"), employee("jane")],
            [shift("sick_one", "thu")],
            leave_dates={"jane": {"2026-03-05"}}, date_iso="2026-03-05",
        )
        assert out["candidates"] == []

    def test_overlapping_hours_are_never_offered(self):
        """Nobody can be in two places — this is physics, not policy."""
        out = cover(
            [employee("sick_one"), employee("jane")],
            [shift("sick_one", "thu"), shift("jane", "thu", "05:00", "13:00")],
        )
        assert out["candidates"] == []

    def test_a_leaver_is_never_offered(self):
        out = cover(
            [employee("sick_one"), employee("gone", is_active=False)],
            [shift("sick_one", "thu")],
        )
        assert out["candidates"] == []


class TestSameDayIsAllowed:
    """Working later that day is a long day, not an impossibility."""

    def test_a_split_shift_is_allowed(self):
        """Morning off sick, covered by someone doing the evening rush.

        They go home in between, so this is two shifts rather than one long
        one — ordinary in retail and wrong to refuse.
        """
        out = cover(
            [employee("sick_one"), employee("tiago")],
            [shift("sick_one", "thu"), shift("tiago", "thu", "18:00", "22:00")],
        )
        assert [c["name"] for c in out["candidates"]] == ["Tiago"]

    def test_back_to_back_shifts_are_one_stint_and_are_capped(self):
        """06:00-14:00 followed by 14:00-22:00 is sixteen hours on the floor,
        however it is written down."""
        out = cover(
            [employee("sick_one"), employee("tiago")],
            [shift("sick_one", "thu"), shift("tiago", "thu", "14:00", "22:00")],
        )
        assert out["candidates"] == []

    def test_a_token_gap_does_not_make_it_a_split_shift(self):
        out = cover(
            [employee("sick_one"), employee("tiago")],
            [shift("sick_one", "thu"), shift("tiago", "thu", "14:05", "22:00")],
        )
        assert out["candidates"] == []


class TestRanking:
    def test_the_closest_role_comes_first(self):
        out = cover(
            [
                employee("sick_one", role="Stocker"),
                employee("jane", role="Floor Assistant"),
                employee("tiago", role="Stocker"),
            ],
            [shift("sick_one", "thu")],
        )
        assert [c["name"] for c in out["candidates"]][0] == "Tiago"

    def test_having_worked_that_exact_shift_wins_a_tie(self):
        history = [{
            "week_start": "2026-02-23", "approved": True,
            "shifts": [shift("jane", "thu", "06:00", "14:00")],
        }]
        out = cover(
            [employee("sick_one"), employee("jane"), employee("tiago")],
            [shift("sick_one", "thu")],
            history_rosters=history,
        )
        assert out["candidates"][0]["name"] == "Jane"
        assert "worked this exact shift" in out["candidates"][0]["why"]

    def test_somebody_with_more_room_left_comes_first(self):
        out = cover(
            [employee("sick_one"), employee("jane"), employee("tiago")],
            [shift("sick_one", "thu"), shift("jane", "mon"), shift("jane", "tue")],
        )
        assert out["candidates"][0]["name"] == "Tiago"

    def test_clean_candidates_always_outrank_rule_breakers(self):
        out = cover(
            [
                employee("sick_one", role="Stocker"),
                employee("perfect_fit", role="Stocker", max_weekly_hours=8),
                employee("jane", role="Floor Assistant"),
            ],
            [shift("sick_one", "thu"), shift("perfect_fit", "mon")],
        )
        assert out["candidates"][0]["name"] == "Jane", (
            "a worse role fit with nothing broken beats a perfect fit over cap"
        )

    def test_every_candidate_explains_itself(self):
        """A bare name makes the manager open three other screens."""
        out = cover(
            [employee("sick_one"), employee("jane")],
            [shift("sick_one", "thu")],
        )
        assert out["candidates"][0]["why"]


class TestSickBalance:
    """Set in days, spent in hours."""

    def test_the_default_matches_the_irish_statutory_entitlement(self):
        assert paid_sick_days({}) == 5

    def test_a_shop_can_set_its_own(self):
        assert paid_sick_days({"paid_sick_days": 10}) == 10

    def test_a_day_is_converted_from_what_they_actually_work(self):
        """A part-timer's day is not a full-timer's day."""
        part = [{"week_start": "2026-03-02", "approved": True, "shifts": [
            {"employee_id": "p", "day": d, "start": "10:00", "end": "14:00",
             "paid_hours": 4.0} for d in ("sat", "sun")
        ]}]
        full = [{"week_start": "2026-03-02", "approved": True, "shifts": [
            {"employee_id": "f", "day": d, "start": "08:00", "end": "18:00",
             "paid_hours": 10.0} for d in ("mon", "tue")
        ]}]

        p = compute_sick_balance(employee("p"), part, shop={})
        f = compute_sick_balance(employee("f"), full, shop={})

        assert p["usual_day_hours"] == 4.0
        assert f["usual_day_hours"] == 10.0
        assert p["entitlement_hours"] == 20.0
        assert f["entitlement_hours"] == 50.0

    def test_sick_hours_are_drawn_down(self):
        rosters = [{"week_start": "2026-03-02", "approved": True, "shifts": [
            {"employee_id": "e1", "day": "mon", "start": "09:00", "end": "17:00",
             "paid_hours": 8.0},
            {"employee_id": "e1", "day": "tue", "sick": True, "paid_hours": 8.0},
        ]}]
        out = compute_sick_balance(employee("e1"), rosters, shop={}, today=None)

        assert out["used_hours"] == 8.0
        assert out["remaining_hours"] == 32.0
        assert out["remaining_days"] == 4.0
        assert out["exhausted"] is False

    def test_illness_past_the_entitlement_is_recorded_as_unpaid(self):
        """People do not stop being ill because an allowance ran out."""
        shifts = [
            {"employee_id": "e1", "day": "mon", "start": "09:00", "end": "17:00",
             "paid_hours": 8.0},
        ] + [
            {"employee_id": "e1", "day": d, "sick": True, "paid_hours": 8.0}
            for d in ("tue", "wed", "thu", "fri", "sat", "sun")
        ]
        out = compute_sick_balance(
            employee("e1"),
            [{"week_start": "2026-03-02", "approved": True, "shifts": shifts}],
            shop={"paid_sick_days": 5},
        )

        assert out["exhausted"] is True
        assert out["remaining_hours"] == 0.0
        paid = [o for o in out["occurrences"] if o["paid"]]
        assert len(paid) == 5, "five days paid, the sixth is not"
        assert out["occurrences"][-1]["paid"] is False
