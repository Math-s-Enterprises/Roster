"""A shift is stretched only for an hour with nobody on it.

`required(day, hour)` is a 24-week AVERAGE of bodies per hour. The shifts
placed are a DISCRETE list of the shop's own shapes. Ten real shapes cannot
reproduce an average hour by hour, so the two disagree permanently — measured
on the reference shop, the shapes fall 24 hours short of the curve and run 25
hours OVER it. The same total, distributed differently.

`_close_short_hours` used to correct only the short side, which inflated every
week and produced one advisory per patched hour. Eighteen in a single week,
each one a shift the manager had to read and would not have written himself.

So the trigger is now "nobody is on this hour" (§1 rule 1) rather than "fewer
than average are on this hour". An hour that is thin but staffed is reported
by "Against the usual" (§7c) instead — information rather than a silent
change to somebody's finishing time.
"""
from datetime import date, timedelta

from app.services.demand import build_profile
from app.services.scheduler import DAYS, solve_roster

WEEK = "2026-09-14"


def make_shop(**overrides):
    shop = {
        "shop_id": "s", "min_shift_hours": 4, "max_shift_hours": 12,
        "hours": [
            {"day": d, "open": "08:00", "close": "20:00", "closed": False}
            for d in DAYS
        ],
        "strict_days_off": False,
    }
    shop.update(overrides)
    return shop


def person(employee_id, **overrides):
    employee = {
        "employee_id": employee_id, "name": employee_id.title(),
        "role": "Shop Floor", "age": 30, "hourly_rate": 15.0,
        "max_weekly_hours": 40, "preferred_days_off": [],
        "departments": ["Shop Floor"], "is_active": True,
    }
    employee.update(overrides)
    return employee


def weeks(shift_lists, count=12):
    """`shift_lists` maps week index -> list of (employee, day, start, end)."""
    out = []
    for w in range(count):
        out.append({
            "week_start": (date(2026, 6, 22)
                           + timedelta(weeks=w)).isoformat(),
            "approved": True, "created_at": f"{w:03d}",
            "shifts": [
                {"employee_id": e, "day": d, "start": s, "end": t}
                for e, d, s, t in shift_lists(w)
            ],
        })
    return out


def stretch_notes(result):
    return [i for i in (result.get("issues") or []) if "was changed from" in i]


class TestThinIsReportedAndEmptyIsFixed:
    def test_an_hour_that_is_thin_but_staffed_is_not_stretched(self):
        """The 18-advisory case, tested on the builder directly.

        Written first as a full solve, which did NOT catch reverting to the
        old behaviour: with simple synthetic shapes the curve and the shapes
        agree, so there is nothing to be short of and no stretch either way.
        The disagreement only appears on a real shop's varied rota. So the
        state is constructed instead — the curve wants two people at 13:00
        and one is on — which is precisely the condition that fired eighteen
        times in one week.
        """
        from app.services.scheduler import _RosterBuilder

        def pattern(w):
            # THREE people across 13:00 every week, so the curve wants three
            # — and only two get placed below. Two is not zero, so the hour
            # is thin rather than empty, which is the whole distinction.
            return ([("a", d, "08:00", "14:00") for d in DAYS]
                    + [("b", d, "13:00", "20:00") for d in DAYS]
                    + [("c", d, "12:00", "16:00") for d in DAYS])

        hist = weeks(pattern)
        team = [person("a"), person("b"), person("c")]
        shop = make_shop()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team})
        assert profile.required("mon", 13) >= 3, (
            f"fixture is wrong: the curve wants "
            f"{profile.required('mon', 13)} at 13:00, needs 3+ so that "
            f"placing two leaves it thin but not empty"
        )

        builder = _RosterBuilder(
            shop, team, [], [], [], WEEK, {}, profile, hist,
            None, None, None,
        )
        builder._record_shift("a", "mon", "08:00", "14:00")
        builder.assigned_by_day.setdefault("mon", set()).add("a")
        builder._record_shift("b", "mon", "13:00", "20:00")
        builder.assigned_by_day["mon"].add("b")
        # 13:00 has ONE person and the curve wants two — thin, not empty.
        assert builder.on_duty["mon"][13] == 2
        assert builder.on_duty["mon"][8] == 1
        assert profile.required("mon", 8) <= 1

        before = dict(enumerate(builder.on_duty["mon"]))
        builder._close_short_hours()
        after = dict(enumerate(builder.on_duty["mon"]))

        # Coverage may only have grown where there was NOBODY. Asserting
        # nothing changed at all is wrong: closing a genuinely empty hour is
        # what the pass is for, and an earlier version of this test forbade
        # that too and failed on arrival.
        grew = [h for h in after if after[h] > before[h]]
        assert all(before[h] == 0 for h in grew), (
            f"hours {[h for h in grew if before[h]]} already had somebody on "
            f"them and a shift was stretched anyway — this is the "
            f"average-chasing that produced 18 advisories in one week"
        )

    def test_an_hour_the_curve_wants_and_nobody_holds_is_still_closed(self):
        """The narrowing must not disable the pass.

        Tested directly on the builder, because provoking the case through a
        full solve is fragile: the fill usually places the shapes that cover
        the hour, and the coverage floor gets the rest. Here the state is
        constructed — the curve wants somebody at 13:00 and the placed shifts
        leave it empty — so the pass has exactly the case it exists for.

        An earlier version of this test asserted a hole at an hour the shop's
        history NEVER staffed. `required` is 0 there, so the pass has always
        skipped it and always should: that is the coverage floor's job (§1
        rule 1), not this one's. The test was asserting behaviour that never
        existed and failed on arrival.
        """
        from app.services.scheduler import _RosterBuilder

        def pattern(w):
            shifts = [("a", d, "08:00", "14:00") for d in DAYS]
            shifts += [("b", d, "13:00", "20:00") for d in DAYS]
            return shifts

        hist = weeks(pattern)
        team = [person("a"), person("b")]
        shop = make_shop()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team})
        assert profile.required("mon", 13) > 0, (
            "fixture is wrong: the curve must want somebody at 13:00"
        )

        builder = _RosterBuilder(
            shop, team, [], [], [], WEEK, {}, profile, hist,
            None, None, None,
        )
        # Only the morning shift is placed, so 13:00 is genuinely empty.
        builder._record_shift("a", "mon", "08:00", "13:00")
        builder.assigned_by_day.setdefault("mon", set()).add("a")
        assert builder.on_duty["mon"][13] == 0

        builder._close_short_hours()
        assert builder.on_duty["mon"][13] > 0, (
            "an hour the curve wants, with nobody on it, was left empty"
        )

    def test_the_week_is_not_inflated_past_the_shapes_the_shop_runs(self):
        """Correcting only the short side of an average makes every week
        bigger than the shop's own rota. Measured before this change: +2%
        against a normal week, every week."""
        def pattern(w):
            shifts = [("a", d, "08:00", "14:00") for d in DAYS]
            shifts += [("b", d, "14:00", "20:00") for d in DAYS]
            if w % 4:
                shifts += [("c", d, "10:00", "18:00") for d in DAYS]
            return shifts

        hist = weeks(pattern)
        team = [person("a"), person("b"), person("c")]
        shop = make_shop()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team})
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile,
            history_rosters=hist)

        # Every generated shift should be a shape the shop actually runs.
        known = {(s, e) for d in DAYS for s, e in (profile.slots_for(d) or [])}
        invented = [
            (s["day"], s["start"], s["end"]) for s in result["shifts"]
            if (s["start"], s["end"]) not in known
        ]
        assert not invented, (
            f"shapes the shop does not run were created: {invented[:4]}"
        )
