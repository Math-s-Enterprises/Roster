"""Hourly staff finish the week near the hours they have been working.

The week used to come out with the right TOTAL hours going to the wrong
people. Measured on a real 25-person shop: the week was within 2% of normal
size, and 11 of 18 hourly staff were more than 2h from what they had been
working — Jane on 13h against a recent 32, Roisín on 31h against a recent 21.

Two earlier attempts to fix this inside the per-slot ranking changed nothing,
and could not have: a sort answers "who takes THIS shift", while "Jane should
finish near 32 hours" is a property of the whole week. So this is a pass that
runs after the week is built and compares totals.

The rule it must never break is the one at `scheduler.py:1738`: somebody short
of hours must not take a shift off the person who actually works it.
"""
from datetime import date, timedelta

from app.services import hours_target
from app.services.demand import build_profile
from app.services.scheduler import DAYS, _RosterBuilder, solve_roster

WEEK = "2026-09-14"
SHAPE = ("09:00", "17:00")


def make_shop(**overrides):
    shop = {
        "shop_id": "s", "min_shift_hours": 4, "max_shift_hours": 9,
        "hours": [
            {"day": d, "open": "09:00", "close": "17:00", "closed": False}
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


def history(pattern, count=12, start=date(2026, 6, 22)):
    """`pattern` maps employee_id -> the days they work each week."""
    out = []
    for w in range(count):
        out.append({
            "week_start": (start + timedelta(weeks=w)).isoformat(),
            "approved": True, "created_at": f"{w:03d}",
            "shifts": [
                {"employee_id": employee_id, "day": day,
                 "start": SHAPE[0], "end": SHAPE[1]}
                for employee_id, days in pattern.items() for day in days
            ],
        })
    return out


def hours_for(result, employee_id):
    return sum(s.get("paid_hours", 0) for s in result["shifts"]
               if s["employee_id"] == employee_id)


def generate(team, hist, shop=None, **kwargs):
    shop = shop or make_shop()
    profile = build_profile(
        shop, hist, {e["employee_id"]: e["role"] for e in team})
    return solve_roster(
        shop, team, [], [], [], WEEK, None, profile,
        history_rosters=hist, **kwargs)


class TestTheTargetTracksWhatTheyWorkNow:
    def test_a_rising_pattern_is_not_dragged_down_by_old_weeks(self):
        """Jane's real shape: months of light weeks, then a steady climb.

        A decayed average over everything said 28.5h while she was working
        31-36. The window has to describe who she is now.
        """
        light = history({"a": ["mon", "tue"]}, count=14,
                        start=date(2026, 2, 2))
        heavy = history({"a": ["mon", "tue", "wed", "thu"]}, count=8,
                        start=date(2026, 7, 20))
        usual = hours_target.usual_hours(light + heavy, WEEK)
        four_days = 4 * 7.25
        assert abs(usual["a"] - four_days) < 0.01, (
            f"still carrying the old two-day pattern: {usual['a']:.1f}h"
        )

    def test_one_odd_week_does_not_reset_somebodys_normal(self):
        """Covering a colleague's holiday once is not a new baseline."""
        weeks = history({"a": ["mon", "tue"]}, count=8)
        weeks[-1]["shifts"] += [
            {"employee_id": "a", "day": d, "start": SHAPE[0], "end": SHAPE[1]}
            for d in ("wed", "thu", "fri")
        ]
        usual = hours_target.usual_hours(weeks, WEEK)
        assert abs(usual["a"] - 2 * 7.25) < 0.01, (
            f"a single big week moved the baseline to {usual['a']:.1f}h"
        )

    def test_only_the_window_counts(self):
        """Anything older than the window says nothing about now."""
        old = history({"a": ["mon", "tue", "wed", "thu", "fri"]}, count=20,
                      start=date(2026, 1, 5))
        new = history({"a": ["mon"]}, count=8, start=date(2026, 7, 20))
        usual = hours_target.usual_hours(old + new, WEEK)
        assert abs(usual["a"] - 7.25) < 0.01, (
            f"weeks outside the window are still counted: {usual['a']:.1f}h"
        )


class TestTheAccountingStaysExact:
    """`_unrecord_shift` is the inverse of `_record_shift`, and the safety of
    the pass rests on it. A counter left un-reversed does not fail loudly — it
    quietly inflates somebody's hours for the rest of the week."""

    def _builder(self):
        team = [person("a"), person("b")]
        hist = history({"a": ["mon", "tue"], "b": ["wed"]})
        shop = make_shop()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team})
        return _RosterBuilder(
            shop, team, [], [], [], WEEK, {}, profile, hist,
            None, None, None,
        )

    def test_recording_then_unrecording_a_shift_leaves_no_trace(self):
        builder = self._builder()
        before = (
            dict(builder.hours_used), dict(builder.span_used),
            {d: list(v) for d, v in builder.on_duty.items()},
            len(builder.result.shifts),
        )
        builder._record_shift("a", "mon", *SHAPE)
        builder._unrecord_shift(builder.result.shifts[-1])
        assert dict(builder.hours_used) == before[0]
        assert dict(builder.span_used) == before[1]
        assert {d: list(v) for d, v in builder.on_duty.items()} == before[2], (
            "coverage counters did not come back"
        )
        assert len(builder.result.shifts) == before[3]

    def test_a_day_is_only_given_back_when_nothing_of_theirs_remains(self):
        """Two shifts in one day is a split shift, ordinary in retail (§8)."""
        builder = self._builder()
        builder._record_shift("a", "mon", "09:00", "12:00")
        builder._record_shift("a", "mon", "13:00", "17:00")
        builder._unrecord_shift(builder.result.shifts[-1])
        assert "mon" in builder.days_worked["a"]


def test_an_unrostered_employee_gets_an_existing_minimum_length_shift():
    shop = make_shop(min_shift_hours=4)
    team = [person("donor"), person("new")]
    builder = _RosterBuilder(
        shop, team, [], [], [], WEEK, {}, None, history_rosters=[]
    )
    for day in ("mon", "tue"):
        builder._record_shift("donor", day, "09:00", "17:00")
        builder.assigned_by_day.setdefault(day, set()).add("donor")

    before = len(builder.result.shifts)
    builder._include_unrostered()

    assert len(builder.result.shifts) == before
    assert {s["employee_id"] for s in builder.result.shifts} == {"donor", "new"}
    assert all(
        s["span_hours"] >= shop["min_shift_hours"]
        for s in builder.result.shifts
    )


class TestItActuallyEvensThemOut:
    def _lopsided(self):
        """`hog` has been working four days, `spare` one — and the shop runs
        five identical shifts a day, so nobody owns anything."""
        return history({"hog": ["mon", "tue", "wed", "thu"],
                        "spare": ["fri"]}, count=10)

    def test_somebody_well_under_their_usual_gains_hours(self):
        hist = self._lopsided()
        team = [person("hog"), person("spare")]
        before = generate(team, hist)
        assert hours_for(before, "spare") > 0

    def test_the_week_is_never_made_worse(self):
        """The pass's actual contract: it only ever moves totals closer.

        Asserted by solving the same week twice, once with `_rebalance_hours`
        stubbed out. Anything else is guesswork — an early version of this
        test asserted somebody would land within 12h of their usual, which
        failed on a two-person shop where covering seven days simply requires
        more hours than either of them normally works. Coverage beats the
        hours target, correctly, and a test that does not know that is
        measuring the wrong thing.
        """
        from app.services import scheduler as sched
        hist = self._lopsided()
        team = [person("hog"), person("spare")]
        aim = hours_target.usual_hours(hist, WEEK)

        with_pass = generate(team, hist)
        original = sched._RosterBuilder._rebalance_hours
        sched._RosterBuilder._rebalance_hours = lambda self: None
        try:
            without_pass = generate(team, hist)
        finally:
            sched._RosterBuilder._rebalance_hours = original

        def distance(result):
            return sum(abs(hours_for(result, e) - target)
                       for e, target in aim.items())

        assert distance(with_pass) <= distance(without_pass), (
            f"the pass made the week less fair: "
            f"{distance(without_pass):.1f}h -> {distance(with_pass):.1f}h"
        )

    def test_nobody_is_pushed_over_their_cap(self):
        hist = self._lopsided()
        team = [person("hog"), person("spare", max_weekly_hours=8)]
        result = generate(team, hist)
        assert hours_for(result, "spare") <= 8.0

    def test_nobody_gains_a_sixth_day(self):
        hist = history({"a": ["mon", "tue", "wed", "thu", "fri"],
                        "b": ["sat"]}, count=10)
        team = [person("a"), person("b")]
        result = generate(team, hist)
        for employee_id in ("a", "b"):
            days = {s["day"] for s in result["shifts"]
                    if s["employee_id"] == employee_id}
            assert len(days) <= 5


def lopsided_builder(placed, hist, **kwargs):
    """A builder with shifts already laid down, to exercise the pass directly.

    WHY NOT END-TO-END: on small synthetic shops the solver reproduces history
    closely, so nobody ends up under their usual hours and the pass correctly
    does nothing. Every guard written as a full solve therefore passed no
    matter what I broke — sabotaging the owned-shift check, the pinned check,
    the single-day check and the fairness guard all left the suite green,
    because the pass was never running.

    So the imbalance is constructed here instead: `placed` maps employee_id ->
    the days they hold, and the aims come from `hist`. Give somebody four days
    when their history says one and the pass has something real to fix.
    """
    team = [person(e) for e in sorted({*placed, *_people_in(hist)})]
    shop = make_shop()
    profile = build_profile(
        shop, hist, {e["employee_id"]: e["role"] for e in team})
    builder = _RosterBuilder(
        shop, team, [], [], [], WEEK, {}, profile, hist,
        kwargs.get("locked_shifts"), None, kwargs.get("only_day"),
    )
    for employee_id, days in placed.items():
        for day in days:
            builder._record_shift(
                employee_id, day, *SHAPE,
                **({"pinned": True} if day in kwargs.get("pinned", ()) else {}),
            )
            builder.assigned_by_day.setdefault(day, set()).add(employee_id)
    return builder


def _people_in(hist):
    return {s["employee_id"] for r in hist for s in r["shifts"]}


def held_by(builder, employee_id):
    return {s["day"] for s in builder.result.shifts
            if s["employee_id"] == employee_id}


class TestTheRulesItMustNeverBreak:
    # History: `hog` normally works ONE day, `spare` normally works four.
    # Placed the other way round, so the pass has a real imbalance to fix.
    HIST = None

    def setup_method(self):
        self.HIST = history({"hog": ["mon"],
                             "spare": ["tue", "wed", "thu", "fri"]}, count=10)

    def test_the_pass_actually_fires_on_this_fixture(self):
        """Guard for the guards. Every test below is worthless if the pass
        does nothing here — which is exactly how the first version of this
        file passed six sabotages in a row."""
        builder = lopsided_builder(
            {"hog": ["mon", "tue", "wed", "thu"], "spare": ["fri"]}, self.HIST)
        assert builder.hours_aim["hog"] < builder.hours_aim["spare"], (
            "the fixture does not create an imbalance to fix"
        )
        before = held_by(builder, "spare")
        builder._rebalance_hours()
        assert held_by(builder, "spare") != before, (
            "the pass moved nothing — every guard in this class is vacuous"
        )

    def test_a_settled_shift_is_never_moved_to_even_out_hours(self):
        """The bug at scheduler.py:1738 in its newest possible form.

        `hog` owns Monday outright — he has worked it every week. He is also
        well over his usual hours, so the pass wants to take work off him. It
        must take something else.
        """
        builder = lopsided_builder(
            {"hog": ["mon", "tue", "wed", "thu"], "spare": ["fri"]}, self.HIST)
        from app.services import slot_owners
        assert slot_owners.owner_of(
            builder.slot_owners, "mon", *SHAPE) == "hog", (
            "fixture is wrong: hog does not own Monday"
        )
        builder._rebalance_hours()
        assert "mon" in held_by(builder, "hog"), (
            "hog's settled Monday was moved to even out hours — exactly the "
            "regression scheduler.py:1738 warns about"
        )

    def test_the_second_regular_on_a_doubled_slot_keeps_their_shift(self):
        """Reported from the reference shop: "Emma usually works every Monday
        at 6:00 am, but in the new roster she was not rostered at 6:00 at
        all."

        A shape that runs TWICE has two regulars (SlotHistory says so), but
        `owner_of` returns only the top one. The rebalance pass used it, so
        the second regular's shift read as unowned and could be handed to
        somebody short of hours. `regulars_of` returns the whole set.

        Here `first` and `second` both work Monday 06:00-14:00 every week —
        the slot runs twice — and `second` is over their usual hours, which
        makes them the obvious donor. Their Monday must still not move.
        """
        from app.services import slot_owners
        hist = []
        for w in range(12):
            hist.append({
                "week_start": (date(2026, 6, 22)
                               + timedelta(weeks=w)).isoformat(),
                "approved": True, "created_at": f"{w:03d}",
                "shifts": [
                    {"employee_id": "first", "day": "mon",
                     "start": SHAPE[0], "end": SHAPE[1]},
                    {"employee_id": "second", "day": "mon",
                     "start": SHAPE[0], "end": SHAPE[1]},
                    {"employee_id": "spare", "day": "fri",
                     "start": SHAPE[0], "end": SHAPE[1]},
                ],
            })

        builder = lopsided_builder(
            {"second": ["mon", "tue", "wed", "thu"], "spare": ["fri"]}, hist)
        owners = builder.slot_owners
        assert slot_owners.owner_of(owners, "mon", *SHAPE) != "second", (
            "fixture is wrong: `second` must NOT be the top claimant, or "
            "this passes without exercising the bug"
        )
        assert "second" in slot_owners.regulars_of(owners, "mon", *SHAPE), (
            "fixture is wrong: `second` must be a regular on the shape"
        )

        builder._rebalance_hours()
        assert "mon" in held_by(builder, "second"), (
            "the second regular on a doubled slot lost the Monday they work "
            "every week"
        )

    def test_a_salaried_employee_can_never_receive_a_rebalanced_shift(self):
        """Asked directly: "Emma's shift was given to Corey — did you cause
        that?"

        Corey is salaried. This pass only moves work between people paid by
        the hour: `_build_hours_aim` skips anybody with a contract band, and
        both donors and receivers are drawn from that map. So it could not
        have been this, whatever else it was.

        Written as a test rather than left as reasoning, because "I checked
        and it cannot be us" is worth nothing the next time somebody asks.
        """
        salaried = person("corey", employment_type="full_time_contract",
                          contract_span_hours=40)
        hist = history({"emma": ["mon", "tue"],
                        "corey": ["wed", "thu", "fri"]})
        shop = make_shop()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"]
                         for e in [person("emma"), salaried]})
        builder = _RosterBuilder(
            shop, [person("emma"), salaried], [], [], [], WEEK, {}, profile,
            hist, None, None, None,
        )
        assert "corey" not in builder.hours_aim, (
            "a salaried employee is in the rebalance map, so this pass could "
            "hand them somebody else's settled shift"
        )
        assert builder.hours_aim, "the fixture has nobody hourly to balance"

    def test_a_pinned_shift_is_never_moved(self):
        builder = lopsided_builder(
            {"hog": ["mon", "tue", "wed", "thu"], "spare": ["fri"]},
            self.HIST, pinned=("wed",))
        builder._rebalance_hours()
        assert "wed" in held_by(builder, "hog"), (
            "a pinned shift was moved to even out hours"
        )

    def test_a_single_day_rebalance_moves_nothing(self):
        """The manager asked about Wednesday. Reshaping the rest of the week
        to even out a weekly total is not an answer to that (§2e)."""
        builder = lopsided_builder(
            {"hog": ["mon", "tue", "wed", "thu"], "spare": ["fri"]},
            self.HIST, only_day="wed")
        before = sorted((s["employee_id"], s["day"]) for s in
                        builder.result.shifts)
        builder._rebalance_hours()
        assert sorted((s["employee_id"], s["day"]) for s in
                      builder.result.shifts) == before

    def test_every_move_leaves_the_week_strictly_fairer(self):
        """Handing a long shift to somebody two hours short just moves the
        unfairness onto them, so the pass must refuse it.

        Asserted as total distance-from-usual before and after, which is the
        quantity the guard actually protects. An earlier version asserted a
        loose per-person bound and stayed green when the guard was deleted —
        it was measuring something the sabotage did not affect.
        """
        builder = lopsided_builder(
            {"hog": ["mon", "tue", "wed", "thu"], "spare": ["fri"]}, self.HIST)

        def distance():
            return sum(
                abs(builder.hours_used[employee_id] - aim)
                for employee_id, aim in builder.hours_aim.items()
            )

        before = distance()
        # One move at a time, so a single bad move cannot be hidden by a
        # good one that follows it.
        while builder._one_rebalance_move():
            after = distance()
            assert after < before, (
                f"a move made the week less fair: {before:.2f} -> {after:.2f}"
            )
            before = after

    def test_a_long_shift_is_not_dumped_on_somebody_barely_short(self):
        """The case the fairness guard exists for, and the only one that can
        show it working.

        With every shift the same length, every available move happens to be
        fair and deleting the guard changes nothing — which is why the
        earlier version of this test stayed green under sabotage. The guard
        only bites when a LONG shift could go to somebody only slightly
        short: both of them end further from a normal week than they started.
        """
        builder = lopsided_builder({"hog": ["mon"], "spare": ["fri"]},
                                   self.HIST)
        # A ten-hour Tuesday, and two people each about 2.5h off their usual.
        builder._record_shift("hog", "tue", "08:00", "18:00")
        builder.assigned_by_day.setdefault("tue", set()).add("hog")
        builder.hours_aim["hog"] = builder.hours_used["hog"] - 2.5
        builder.hours_aim["spare"] = builder.hours_used["spare"] + 2.5

        before = sorted((s["employee_id"], s["day"]) for s in
                        builder.result.shifts)
        assert builder._one_rebalance_move() is False, (
            "a 10-hour shift was moved to somebody 2.5 hours short, leaving "
            "both of them further from a normal week than before"
        )
        assert sorted((s["employee_id"], s["day"]) for s in
                      builder.result.shifts) == before

    def test_a_donor_is_never_pushed_below_their_own_usual_week(self):
        """Taking too much is the same complaint from the other direction.

        Total distance falling is not enough on its own: stripping 16 hours
        off somebody who was 10 hours over improves the total while leaving
        them 6 short. Roisín went +9.8h -> -6.2h at the reference shop before
        this guard existed.

        Constructed so the move IMPROVES the total and still crosses the
        donor over — otherwise the fairness guard already blocks it and this
        test would pass for the wrong reason. Donor 5h over holding a 10h
        shift, receiver 20h under: total 25 -> 15, so it looks like a win
        right up until you notice the donor is now 5h short.
        """
        builder = lopsided_builder({"hog": ["mon"], "spare": ["fri"]},
                                   self.HIST)
        builder._record_shift("hog", "tue", "08:00", "18:00")
        builder.assigned_by_day.setdefault("tue", set()).add("hog")
        builder.hours_aim["hog"] = builder.hours_used["hog"] - 5.0
        builder.hours_aim["spare"] = builder.hours_used["spare"] + 20.0

        moved = builder._one_rebalance_move()
        used, aim = builder.hours_used["hog"], builder.hours_aim["hog"]
        assert used >= aim - 0.01, (
            f"hog was 5h over their usual week and has been pushed to "
            f"{used:.1f}h against {aim:.1f}h — taking too much is the same "
            f"complaint from the other direction"
        )
        assert not moved or used >= aim

    def test_hours_are_moved_never_deleted(self):
        """Somebody over their usual week KEEPS those hours if nobody else
        can take them.

        The shifts exist because the shop needs them. Dropping one to tidy up
        a total would leave an hour with nobody on the floor, which §1
        forbids outright — so the pass moves work between people and never
        removes it from the roster.
        """
        builder = lopsided_builder(
            {"hog": ["mon", "tue", "wed", "thu"], "spare": ["fri"]}, self.HIST)
        # Everybody else is exactly where they should be, so there is nobody
        # to receive: only `hog` is off, and he is OVER.
        for employee_id in builder.hours_aim:
            builder.hours_aim[employee_id] = builder.hours_used[employee_id]
        builder.hours_aim["hog"] = builder.hours_used["hog"] - 8.0

        before = sorted((s["employee_id"], s["day"]) for s in
                        builder.result.shifts)
        builder._rebalance_hours()
        after = sorted((s["employee_id"], s["day"]) for s in
                       builder.result.shifts)
        assert after == before, "a shift was moved with nobody needing hours"
        assert len(after) == len(before), "a shift was dropped from the roster"

    def test_a_refused_move_puts_the_shift_back(self):
        """The path where a shift could actually vanish.

        `_try_move_shift` lifts the donor's shift BEFORE testing the
        receiver, because the receiver's own hours would otherwise count
        against them. If the receiver turns out to be ineligible, the shift
        has to go back — and nothing else in this file exercises that,
        because in every other fixture the receiver is eligible and the move
        succeeds. Sabotaging the restore left the suite green.

        Here `spare` already works Monday, so he cannot take Monday's shift
        from `hog`, and the refusal path runs for real.
        """
        builder = lopsided_builder(
            {"hog": ["mon", "tue"], "spare": ["mon"]}, self.HIST)
        monday = next(s for s in builder.result.shifts
                      if s["employee_id"] == "hog" and s["day"] == "mon")
        spare = builder.employees_by_id["spare"]

        before_shifts = len(builder.result.shifts)
        before_hours = builder.hours_used["hog"]

        assert builder._try_move_shift(monday, spare) is False, (
            "spare already works Monday and cannot have taken it"
        )
        assert len(builder.result.shifts) == before_shifts, (
            "the shift was lifted and never put back"
        )
        assert abs(builder.hours_used["hog"] - before_hours) < 0.01, (
            "the donor's hours were not restored"
        )
        assert any(
            s["employee_id"] == "hog" and s["day"] == "mon"
            for s in builder.result.shifts
        ), "the donor no longer holds the shift that was refused"

    def test_the_total_hours_on_the_roster_never_change(self):
        """Whatever moves, the week still contains the same work."""
        builder = lopsided_builder(
            {"hog": ["mon", "tue", "wed", "thu"], "spare": ["fri"]}, self.HIST)
        before = sum(s["paid_hours"] for s in builder.result.shifts)
        builder._rebalance_hours()
        after = sum(s["paid_hours"] for s in builder.result.shifts)
        assert abs(after - before) < 0.01, (
            f"the week lost or gained hours: {before:.2f} -> {after:.2f}"
        )

    def test_the_accounting_survives_a_real_move(self):
        """Hours, days and coverage must all still agree after shifts move."""
        builder = lopsided_builder(
            {"hog": ["mon", "tue", "wed", "thu"], "spare": ["fri"]}, self.HIST)
        builder._rebalance_hours()
        for employee_id in ("hog", "spare"):
            from_shifts = sum(
                s["paid_hours"] for s in builder.result.shifts
                if s["employee_id"] == employee_id)
            assert abs(builder.hours_used[employee_id] - from_shifts) < 0.01, (
                f"{employee_id}: counter says "
                f"{builder.hours_used[employee_id]}, shifts say {from_shifts}"
            )
            assert builder.days_worked[employee_id] == held_by(
                builder, employee_id)


class TestEndToEnd:
    def test_a_settled_shift_is_never_moved_to_even_out_hours(self):
        """The bug at scheduler.py:1738 in its newest possible form.

        `owner` works Monday every single week and owns it outright.
        `hungry` is far below a normal week and would benefit — and must
        still not be given it.
        """
        hist = history({"owner": ["mon", "tue", "wed", "thu"],
                        "hungry": ["fri"]}, count=12)
        team = [person("owner"), person("hungry")]
        result = generate(team, hist)
        monday = [s["employee_id"] for s in result["shifts"]
                  if s["day"] == "mon"]
        assert "owner" in monday, (
            "a settled Monday was moved to even out hours — exactly the "
            "regression scheduler.py:1738 warns about"
        )

    def test_a_pinned_shift_is_never_moved(self):
        hist = history({"hog": ["mon", "tue", "wed", "thu"],
                        "spare": ["fri"]}, count=10)
        team = [person("hog"), person("spare")]
        locked = [{"employee_id": "hog", "day": "fri",
                   "start": SHAPE[0], "end": SHAPE[1]}]
        result = generate(team, hist, locked_shifts=locked)
        assert any(
            s["employee_id"] == "hog" and s["day"] == "fri"
            for s in result["shifts"]
        ), "a pinned shift was moved to even out hours"

    def test_a_single_day_rebalance_does_not_touch_other_days(self):
        """The manager asked about Wednesday. Reshaping Monday to even out a
        weekly total is not an answer to that (§2e)."""
        hist = history({"hog": ["mon", "tue", "wed", "thu"],
                        "spare": ["fri"]}, count=10)
        team = [person("hog"), person("spare")]
        full = generate(team, hist)
        locked = [s for s in full["shifts"] if s["day"] != "wed"]
        one_day = generate(team, hist, locked_shifts=locked, only_day="wed")
        for day in ("mon", "tue", "thu", "fri"):
            before = sorted((s["employee_id"], s["start"])
                            for s in full["shifts"] if s["day"] == day)
            after = sorted((s["employee_id"], s["start"])
                           for s in one_day["shifts"] if s["day"] == day)
            assert before == after, f"{day} changed during a Wednesday rebalance"

    def test_coverage_is_never_reduced(self):
        """Moving hours around must not leave an hour with nobody on it."""
        hist = history({"hog": ["mon", "tue", "wed", "thu"],
                        "spare": ["fri"]}, count=10)
        team = [person("hog"), person("spare")]
        result = generate(team, hist)
        staffed = {s["day"] for s in result["shifts"]}
        assert len(staffed) >= 5, f"only {len(staffed)} days are staffed"

    def test_the_same_week_rebalances_the_same_way_every_time(self):
        """Repair, not variety — a version nobody can reproduce cannot be
        explained (§2c)."""
        hist = history({"hog": ["mon", "tue", "wed", "thu"],
                        "spare": ["fri"]}, count=10)
        team = [person("hog"), person("spare")]
        first = generate(team, hist)
        for _ in range(3):
            again = generate(team, hist)
            assert (sorted((s["employee_id"], s["day"], s["start"])
                           for s in again["shifts"])
                    == sorted((s["employee_id"], s["day"], s["start"])
                              for s in first["shifts"]))

    def test_a_move_is_reported(self):
        hist = history({"hog": ["mon", "tue", "wed", "thu"],
                        "spare": ["fri"]}, count=10)
        team = [person("hog"), person("spare")]
        result = generate(team, hist)
        notes = " ".join(result.get("issues") or [])
        if "moved from" in notes:
            assert "hours they have each been working" in notes
