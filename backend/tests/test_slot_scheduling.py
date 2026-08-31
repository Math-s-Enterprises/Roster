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
from app.services.scheduler import (
    DAYS,
    _RosterBuilder,
    shift_duration_minutes,
    solve_roster,
)

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

    def test_a_stretch_lands_on_the_hour(self):
        """Covering an hour means being there for all of it.

        The stretch used to move an edge 30 minutes and then ask
        `hours_covered` whether the hour was covered. It always said yes,
        because that function floors a shift's start to the hour it falls in —
        so a finish moved to 17:30 "covered" 17:00 while the shop was still a
        body short until 17:30.

        Measured on the reference shop: the solver ended shifts on a half hour
        11.2% of the time where the manager does it 0.2% of the time, and
        over-counted twice as many hours per week as the manager's own rota.
        Those were shapes the shop does not write.
        """
        for was, now in self._stretches(self._gapped()[0]):
            moved = [i for i in range(2) if was[i] != now[i]]
            assert moved, f"an advisory reported no change at all: {was} {now}"
            for i in moved:
                assert now[i].endswith(":00"), (
                    f"a stretched edge kept a half hour: "
                    f"{was[0]}-{was[1]} became {now[0]}-{now[1]}"
                )

    def test_a_stretch_stays_a_changeover_adjustment(self):
        """At most an hour. Beyond that it is a missing shift, not a
        changeover, and lengthening somebody's day by two hours to hide one
        is an edit the manager has to undo."""
        for was, now in self._stretches(self._gapped()[0]):
            grew = (shift_duration_minutes(*now)
                    - shift_duration_minutes(*was))
            assert 0 < grew <= 60, (
                f"{was[0]}-{was[1]} became {now[0]}-{now[1]}, "
                f"{grew} minutes longer"
            )

    @staticmethod
    def _stretches(result):
        """(before, after) for every shift THIS pass reshaped.

        Read from the advisories rather than from the final shifts, because
        other passes lengthen shifts too — _fit_contract_hours had turned a
        09:00-15:00 into 09:00-19:00 and an earlier version of this test
        blamed the stretch for it.
        """
        out = []
        for issue in result["issues"]:
            if "was changed from" not in issue:
                continue
            body = issue.split("was changed from ")[1]
            was, _, rest = body.partition(" to ")
            now = rest.split(" to cover ")[0]
            out.append((tuple(was.split("-")), tuple(now.strip().split("-"))))
        assert out, "no stretch was reported — this fixture must produce one"
        return out

    def _two_hour_gap(self):
        """A day short at 15:00 AND 16:00, so one shift is stretched twice."""
        from app.services.demand import DemandProfile, ShiftPattern

        curve = [0] * 24
        for hour in range(9, 22):
            curve[hour] = 2

        profile = DemandProfile(
            headcount={d: list(curve) for d in DAYS},
            role_mix={d: {"Floor Assistant": [float(c) for c in curve]} for d in DAYS},
            patterns=[
                ShiftPattern("09:00", "15:00", 50, 6),
                ShiftPattern("17:00", "22:00", 50, 6),
            ],
            weeks_observed=24,
            staff_per_day={d: 4 for d in DAYS},
            day_slots={
                d: [["09:00", "15:00"], ["09:00", "15:00"],
                    ["17:00", "22:00"], ["17:00", "22:00"]]
                for d in DAYS
            },
        )
        shop = make_shop(hours=[
            {"day": d, "open": "06:00", "close": "22:00", "closed": False}
            for d in DAYS
        ])
        history = [{
            "week_start": "2026-08-10", "approved": True,
            "shifts": [
                {"employee_id": f"e{i}", "day": d, "start": s, "end": e}
                for d in DAYS
                for i, (s, e) in enumerate([
                    ("09:00", "15:00"), ("09:00", "15:00"),
                    ("17:00", "22:00"), ("17:00", "22:00"),
                ])
            ],
        }]
        return solve_roster(
            shop, make_team(size=6), [], [], [], WEEK, None, profile,
            history_rosters=history,
        )

    def test_a_shift_stretched_twice_is_reported_once(self):
        """Two consecutive short hours take two passes to close, and reporting
        each pass separately read as two unrelated events:

            Emma's mon shift was changed from 06:00-12:00 to 06:00-12:30 ...
            Emma's mon shift was changed from 06:00-12:30 to 06:00-13:30 ...

        The manager does not care how many passes it took. One line per shift,
        original shape to final shape.
        """
        result = self._two_hour_gap()
        changes = [i for i in result["issues"] if "was changed from" in i]

        # Each (person, day) may appear at most once.
        seen = [i.split("'s ")[0] + i.split(" shift")[0][-4:] for i in changes]
        assert len(seen) == len(set(seen)), (
            "the same shift is reported more than once:\n  "
            + "\n  ".join(changes)
        )

    def test_a_collapsed_advisory_names_the_shape_the_generator_drew(self):
        """The 'from' must be the ORIGINAL shape, not the intermediate one
        produced by the first pass — that shape never existed on screen."""
        result = self._two_hour_gap()
        changes = [i for i in result["issues"] if "was changed from" in i]
        assert changes, "expected at least one stretch to be reported"
        for line in changes:
            was = line.split("from ")[1].split(" to ")[0]
            assert was in ("09:00-15:00", "17:00-22:00"), (
                f"reported a shape the generator never produced: {was}\n  {line}"
            )


class TestContractTopUp:
    def test_a_salaried_employee_reaches_their_contracted_hours(self):
        """Their payslip is the same either way, so a short week is hours the
        shop has already bought and not used.

        This used to assert the salaried employee had MORE hours than anybody
        else. That was a proxy for the real rule and slot ownership broke it
        legitimately: once a full-timer is inside their band, a long slot
        going to the person who normally works it is correct, not a failure.
        What must never happen is the full-timer falling short.
        """
        from app.services.availability import contract_span_band

        team = salaried_team()
        result, _ = generate(team=team)
        low, high = contract_span_band(team[0])
        salaried = span_of(result, "e0")

        assert low <= salaried <= high, (
            f"salaried employee on {salaried}h, contracted band {low}-{high}h"
        )

    def test_a_contract_trim_leaves_the_finish_on_the_hour(self):
        """A 42.5h band is 8.5h a day, and the half-hour used to land on the
        FINISH — 10:00-18:30. Measured across 8 solved weeks at the reference
        shop that accounted for 42 of 42 manufactured half-hour finishes, all
        on salaried staff, against a manager who writes one in 555 shifts.

        The shop puts its half-hours on the START (07:30-16:00, 23:30-07:00)
        and keeps finishes whole. Moving starts to match was rejected —
        familiarity is keyed on start time — so the trim rounds down to a
        whole hour instead.
        """
        team = salaried_team()
        result, _ = generate(team=team)
        theirs = [s for s in result["shifts"] if s["employee_id"] == "e0"]
        assert theirs, "the salaried employee got no shifts at all"
        for shift in theirs:
            assert shift["end"].endswith(":00"), (
                f"a contract trim left a half-hour finish: "
                f"{shift['day']} {shift['start']}-{shift['end']}"
            )

    def test_rounding_the_trim_down_does_not_starve_the_contract(self):
        """The risk the change above introduces, stated as its own test.

        Rounding 8.5h down to 8h gives back half an hour per shift — 2.5h
        across a five-day week — and if nothing made that up the salaried
        employee would quietly finish under their band every week. That is
        what _top_up_contracts is for, and this is the test that would notice
        if it stopped being enough.
        """
        from app.services.availability import contract_span_band

        team = salaried_team()
        result, _ = generate(team=team)
        low, high = contract_span_band(team[0])
        assert low <= span_of(result, "e0") <= high, (
            f"on {span_of(result, 'e0')}h against a {low}-{high}h band — "
            f"the trim gave back hours nothing put back"
        )
        assert not result["under_contract"], result["under_contract"]

    def test_slot_ownership_cannot_shut_out_a_full_timer(self):
        """The worst case for owner-first: somebody else owns EVERY slot.

        Owners now win their own slot ahead of contract need, so this is the
        arrangement that could starve a salaried employee — and it must not.
        The guarantee does not come from out-ranking the owner; it comes from
        there being more slots than one person can work (five days, twelve
        hours) and from _top_up_contracts running afterwards for anyone still
        short. A week the shop pays for is a week somebody works.

        (Note salaried shifts are sized to the contract, 42.5/5 = 8.5h, so
        they deliberately do not take the longest slot available. Reaching
        the band is the guarantee, not winning every slot.)
        """
        from app.services.availability import contract_span_band

        team = salaried_team()
        # e1 works every slot, every week — as strong an ownership claim as
        # the data can express.
        hist = []
        for w in range(24):
            hist.append({
                "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
                "approved": True,
                "shifts": [
                    {"employee_id": "e1", "day": d, "start": s, "end": e}
                    for d in DAYS
                    for s, e in (SUNDAY if d == "sun" else WEEKDAY)
                ],
            })

        result, _ = generate(team=team, hist=hist)
        low, high = contract_span_band(team[0])
        salaried = span_of(result, "e0")

        assert low <= salaried <= high, (
            f"ownership starved the full-timer: {salaried}h against a "
            f"{low}-{high}h contract"
        )

    def test_an_owner_keeps_their_shift_against_a_full_timer(self):
        """The bug this was written for.

        _contract_need returns a negative number for a salaried employee below
        their band and zero for everybody else, so while a full-timer was
        short they outranked the owner on every slot. Monday is built first,
        when the shortfall is still the whole contract, so Monday lost the
        most: against the reference shop four settled shifts changed hands on
        one day, including a 06:00 opening its owner had worked for 14 of the
        24 observed weeks.

        The contract is not what was wrong — 41 hours can be reached from many
        combinations of shifts, and _top_up_contracts fills any gap afterwards.
        Taking THAT slot bought the contract nothing and cost the manager an
        edit.
        """
        team = salaried_team()          # e0 is the full-timer
        # Everyone EXCEPT e0 has history, so e0 owns nothing anywhere and the
        # only thing that can win them a slot is contract need.
        hist = []
        for w in range(24):
            hist.append({
                "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
                "approved": True,
                "shifts": [
                    {"employee_id": f"e{i + 1}", "day": d, "start": s, "end": e}
                    for d in DAYS
                    for i, (s, e) in enumerate(SUNDAY if d == "sun" else WEEKDAY)
                ],
            })

        result, _ = generate(team=team, hist=hist)
        # Keyed on the PAIR: Monday runs both 06:00-16:00 and 06:00-14:00, and
        # keying on start alone silently drops one of them.
        monday = {
            (s["start"], s["end"]): s["employee_id"]
            for s in result["shifts"] if s["day"] == "mon" and s.get("start")
        }

        for index, shape in enumerate(WEEKDAY):
            assert monday.get(shape) == f"e{index + 1}", (
                f"mon {shape[0]}-{shape[1]} went to {monday.get(shape)}, but "
                f"e{index + 1} has worked it every week for 24 weeks"
            )

    def test_an_owner_is_not_spent_on_an_earlier_slot(self):
        """Martin's case at the reference shop.

        Slots fill earliest first, so somebody can be placed on an earlier
        slot before their own comes up. Martin owned 10:00-19:00; 06:00-14:00
        was offered first, its usual owner was on leave that week, and Martin
        was the best of who was left — so he took it, and by the time his own
        slot came round he was already working that day.

        Reordering the slots would fix this and break something worse: the
        opener is the hardest slot to fill and has to keep first refusal. So
        the person is reserved instead, and the order is left alone.
        """
        team = make_team(size=14)
        early, late = ("06:00", "14:00"), ("10:00", "19:00")
        others = [("06:00", "16:00"), ("16:00", "00:00"), ("23:30", "07:00")]

        hist = []
        for w in range(24):
            shifts = []
            for day in DAYS:
                # e1 usually opens (18 of 24 weeks, so they own it), and e2
                # covers it the rest of the time. That second part is what
                # makes this test bite: e2 is the obvious replacement when e1
                # is away, which is exactly how Martin ended up on a slot that
                # was not his.
                shifts.append({
                    "employee_id": "e1" if w % 4 else "e2",
                    "day": day, "start": early[0], "end": early[1],
                })
                # e2 owns the late slot outright.
                shifts.append({
                    "employee_id": "e2", "day": day,
                    "start": late[0], "end": late[1],
                })
                for i, (s, e) in enumerate(others):
                    shifts.append({
                        "employee_id": f"e{i + 3}", "day": day, "start": s, "end": e,
                    })
            hist.append({
                "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
                "approved": True, "shifts": shifts,
            })

        from app.services import slot_owners

        owners = slot_owners.build_owners(hist)
        assert slot_owners.owner_of(owners, "mon", *early) == "e1"
        assert slot_owners.owner_of(owners, "mon", *late) == "e2"

        # e1, who owns the early slot, is away — the situation that sent the
        # early slot looking for somebody else.
        team[1]["is_active"] = False

        result, _ = generate(team=team, hist=hist)
        monday = {
            (s["start"], s["end"]): s["employee_id"]
            for s in result["shifts"] if s["day"] == "mon" and s.get("start")
        }

        assert monday.get(late) == "e2", (
            f"mon {late[0]}-{late[1]} went to {monday.get(late)}; e2 owns it "
            f"and must not be spent on the earlier slot first"
        )
        assert monday.get(early) not in (None, "e2"), (
            "the early slot still has to be covered by somebody"
        )

    def test_cover_still_wins_when_reserving_would_empty_a_slot(self):
        """A reservation ranks candidates; it never leaves a shift empty.

        If the only person who can work the opening is also the owner of a
        later slot, they open the shop. Rule 1 is not traded for rule 2b.
        """
        team = make_team(size=2)
        early, late = ("06:00", "14:00"), ("14:00", "22:00")
        hist = []
        for w in range(24):
            hist.append({
                "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
                "approved": True,
                "shifts": [
                    {"employee_id": "e0", "day": d, "start": early[0], "end": early[1]}
                    for d in DAYS
                ] + [
                    {"employee_id": "e0", "day": d, "start": late[0], "end": late[1]}
                    for d in DAYS
                ],
            })

        result, _ = generate(team=team, hist=hist)
        opened = [
            s for s in result["shifts"]
            if s["day"] == "mon" and s.get("start") == early[0]
        ]
        assert opened, "the shop was left unopened to protect a reservation"

    def test_the_full_timer_still_gets_their_hours_from_what_is_left(self):
        """Owner-first must not be paid for out of the contract.

        The same arrangement as above: e0 owns nothing, so every slot with a
        settled owner goes elsewhere. They must still reach their band from
        the rest of the week, or be named in under_contract.
        """
        from app.services.availability import contract_span_band

        team = salaried_team()
        hist = []
        for w in range(24):
            hist.append({
                "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
                "approved": True,
                "shifts": [
                    {"employee_id": f"e{i + 1}", "day": d, "start": s, "end": e}
                    for d in DAYS
                    for i, (s, e) in enumerate(SUNDAY if d == "sun" else WEEKDAY)
                ],
            })

        result, _ = generate(team=team, hist=hist)
        low, high = contract_span_band(team[0])
        span = span_of(result, "e0")

        assert span <= high, f"{span}h exceeds the contracted maximum {high}h"
        if span < low:
            assert any(u["employee_id"] == "e0" for u in result["under_contract"]), (
                f"e0 left on {span}h against a {low}h minimum with no mention "
                f"of it — an unpaid-for gap the manager cannot see"
            )

    def test_an_occasional_coverer_does_not_outrank_contract_need(self):
        """Only the owner jumps the contract, not everybody with history.

        Ownership is 60% over at least 4 occurrences. Somebody who has covered
        a slot a handful of times has a preference, not a claim, and a
        full-timer's contracted hours come first.
        """
        team = salaried_team()
        start, end = WEEKDAY[0]
        # The slot must keep RUNNING every week — ownership is a share of the
        # weeks the slot ran, so removing it from the other weeks would shrink
        # the denominator and make an occasional coverer a 100% owner.
        # Instead it runs every week, shared five ways: nobody reaches 60%.
        coverers = ["e1", "e7", "e8", "e9", "e10"]
        hist = []
        for w in range(24):
            shifts = [
                {"employee_id": f"e{i + 1}", "day": d, "start": s, "end": e2}
                for d in DAYS
                for i, (s, e2) in enumerate(SUNDAY if d == "sun" else WEEKDAY)
                if not (d == "mon" and i == 0)
            ]
            shifts.append({
                "employee_id": coverers[w % len(coverers)],
                "day": "mon", "start": start, "end": end,
            })
            hist.append({
                "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
                "approved": True, "shifts": shifts,
            })

        from app.services import slot_owners

        owners = slot_owners.build_owners(hist)
        assert slot_owners.owner_of(owners, "mon", start, end) is None, (
            "fixture is wrong: nobody should clear the ownership bar here"
        )

        result, _ = generate(team=team, hist=hist)
        # Asserted on the START only. A salaried shift is resized to the
        # contract — 42.5/5 = 8.5h — so e0 takes this slot as 06:00-14:30
        # rather than the full 06:00-16:00. Winning the slot is the point
        # here; its length is a separate rule with its own tests.
        mine = [
            s for s in result["shifts"]
            if s["day"] == "mon" and s["employee_id"] == "e0" and s.get("start")
        ]
        assert mine and mine[0]["start"] == start, (
            f"mon {start} has no owner, so the full-timer's contract should "
            f"decide it — e0 got "
            f"{mine[0]['start'] + '-' + mine[0]['end'] if mine else 'nothing'}"
        )
        # And the slot that DOES have an owner still went to them.
        others = {
            (s["start"], s["end"]): s["employee_id"] for s in result["shifts"]
            if s["day"] == "mon" and s.get("start")
        }
        assert others.get(WEEKDAY[1]) == "e2", (
            "the owned 06:00-14:00 slot should be unaffected by any of this"
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


class TestPinnedShiftsConsumeTheirSlot:
    """A pin is somebody already on the floor. It must cancel a slot.

    The reported bug: a roster was generated without Emma, Emma was added by
    hand to Monday 06:00 and pinned, and Rebalance produced Emma, Megan AND
    Martin on a morning that runs two.

    Cause: a placed shift only cancelled a demand slot when its times matched
    EXACTLY. Monday's list holds 06:00-16:00; a pinned 06:00-14:00 matched
    nothing, so the slot still read as unfilled and a third person was sent to
    it. The manager then deleted the person the solver had added because of
    their own pin.
    """

    def _monday(self, result):
        return [s for s in result["shifts"] if s["day"] == "mon"]

    def _starting_at(self, result, clock):
        return [s for s in self._monday(result) if s["start"] == clock]

    def test_a_pin_with_a_different_finish_still_cancels_its_slot(self):
        team = make_team()
        # 15:00 deliberately matches no learned slot: 06:00-14:00 IS one of
        # them here, so it would have cancelled correctly by accident.
        pinned = {
            "employee_id": "e0", "day": "mon", "start": "06:00", "end": "15:00",
        }
        shop, hist = make_shop(), history()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile,
            history_rosters=hist, locked_shifts=[pinned],
        )

        # The learned Monday runs two 06:00 starts. The pin is one of them.
        expected = sum(
            1 for s, _ in profile.slots_for("mon") if s == "06:00"
        )
        assert len(self._starting_at(result, "06:00")) == expected, (
            "a pinned opener must not sit on top of a full slot list"
        )

    def test_the_pinned_person_is_the_one_kept(self):
        team = make_team()
        pinned = {
            "employee_id": "e9", "day": "mon", "start": "06:00", "end": "15:00",
        }
        shop, hist = make_shop(), history()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile,
            history_rosters=hist, locked_shifts=[pinned],
        )

        openers = self._starting_at(result, "06:00")
        assert "e9" in [s["employee_id"] for s in openers]
        assert next(s for s in openers if s["employee_id"] == "e9")["end"] == "15:00", (
            "the pin keeps its own hours, not the slot's"
        )

    def test_an_exact_match_still_works(self):
        """The behaviour that already worked must not regress."""
        team = make_team()
        pinned = {
            "employee_id": "e0", "day": "mon", "start": "06:00", "end": "16:00",
        }
        shop, hist = make_shop(), history()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile,
            history_rosters=hist, locked_shifts=[pinned],
        )
        expected = sum(1 for s, _ in profile.slots_for("mon") if s == "06:00")
        assert len(self._starting_at(result, "06:00")) == expected

    def test_two_pins_cancel_two_slots_not_one(self):
        """Each placed shift cancels at most one slot, so a genuine
        double-up is still filled."""
        team = make_team()
        pins = [
            {"employee_id": "e0", "day": "mon", "start": "06:00", "end": "14:00"},
            {"employee_id": "e1", "day": "mon", "start": "06:00", "end": "15:00"},
        ]
        shop, hist = make_shop(), history()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile,
            history_rosters=hist, locked_shifts=pins,
        )
        expected = sum(1 for s, _ in profile.slots_for("mon") if s == "06:00")
        assert len(self._starting_at(result, "06:00")) == expected

    def test_a_pin_at_an_unrelated_time_does_not_cancel_a_morning_slot(self):
        """Somebody pinned to the afternoon must not stop the shop opening."""
        team = make_team()
        pinned = {
            "employee_id": "e0", "day": "mon", "start": "13:00", "end": "21:00",
        }
        shop, hist = make_shop(), history()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile,
            history_rosters=hist, locked_shifts=[pinned],
        )
        expected = sum(1 for s, _ in profile.slots_for("mon") if s == "06:00")
        assert len(self._starting_at(result, "06:00")) == expected


class TestTheShiftBelongsToWhoeverWorksIt:
    """A slot with a settled owner is not put out to role seniority.

    The reported behaviour: Emma opens Monday 06:00 every week, but the
    roster kept handing it to a manager. Familiarity did not stop it —
    the manager HAS worked early starts, so he passed the check and then won
    on seniority. The question is not who can work the shift but who does.
    """

    SLOT = ("06:00", "16:00")

    def _history(self, owner="emma", weeks_count=24):
        """`owner` opens every Monday; everybody else shifts down one.

        The manager (e0) therefore owns a Monday shape of his own. Without
        that the fixture would have six slots, six owners and a manager who
        must also be on the day — seven people for six shifts — and senior
        cover would have to displace somebody no matter what the rules said.
        A real shop does not look like that.
        """
        out = []
        for w in range(weeks_count):
            shifts = []
            for d in DAYS:
                slots = SUNDAY if d == "sun" else WEEKDAY
                if d == "mon":
                    who_for = [owner] + [f"e{i}" for i in range(len(slots) - 1)]
                else:
                    who_for = [f"e{i}" for i in range(len(slots))]
                for (s, e), who in zip(slots, who_for):
                    shifts.append(
                        {"employee_id": who, "day": d, "start": s, "end": e}
                    )
            out.append({
                "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
                "approved": True, "shifts": shifts,
            })
        return out

    def _team(self):
        team = make_team(size=14)
        team.append({
            "employee_id": "emma", "name": "Emma", "role": "Floor Assistant",
            "age": 30, "hourly_rate": 15.0, "max_weekly_hours": 40,
            "preferred_days_off": [], "departments": ["Shop Floor"],
            "is_active": True,
        })
        # A senior manager who would otherwise win the slot on rank. He is
        # e0 in the history, so he has his OWN regular shape — which is what
        # a real shop looks like, and what gives senior cover somewhere to go
        # that is not somebody else's shift.
        team[0].update({"employee_id": "e0", "name": "Martin", "role": "Manager"})
        return team

    def _opener(self, result):
        """Who has the LONGER of Monday's two 06:00 shifts.

        Matched on start plus longest span rather than exact times, because
        the gap-closing pass may stretch a finish by half an hour and an
        exact match would then find nothing.
        """
        openers = [
            s for s in result["shifts"]
            if s["day"] == "mon" and s.get("start") == "06:00"
        ]
        if not openers:
            return None
        return max(openers, key=lambda s: s.get("span_hours", 0))["employee_id"]

    def test_the_usual_opener_keeps_their_shift(self):
        shop = make_shop(role_hierarchy=["Manager", "Floor Assistant"])
        result, _ = generate(team=self._team(), shop=shop, hist=self._history())
        assert self._opener(result) == "emma"

    def test_seniority_does_not_take_it(self):
        """The manager outranks her and must still not be given it."""
        shop = make_shop(role_hierarchy=["Manager", "Floor Assistant"])
        result, _ = generate(team=self._team(), shop=shop, hist=self._history())
        assert self._opener(result) != "e0"

    def test_when_the_owner_is_on_leave_it_goes_to_the_usual_cover(self):
        """Not back to seniority — to whoever actually covers for her."""
        history = self._history()
        # Kyle covers Monday's opening whenever Emma is off.
        for roster in history[:6]:
            for shift in roster["shifts"]:
                if shift["day"] == "mon" and (shift["start"], shift["end"]) == self.SLOT:
                    shift["employee_id"] = "kyle"

        team = self._team()
        team.append({
            "employee_id": "kyle", "name": "Kyle", "role": "Floor Assistant",
            "age": 30, "hourly_rate": 15.0, "max_weekly_hours": 40,
            "preferred_days_off": [], "departments": ["Shop Floor"],
            "is_active": True,
        })
        holidays = [{
            "date": WEEK, "end_date": WEEK, "scope": "employee",
            "employee_id": "emma", "label": "Holiday",
        }]

        shop = make_shop(role_hierarchy=["Manager", "Floor Assistant"])
        profile = build_profile(
            shop, history, {e["employee_id"]: e["role"] for e in team}
        )
        result = solve_roster(
            shop, team, holidays, [], [], WEEK, None, profile,
            history_rosters=history,
        )
        assert self._opener(result) == "kyle"

    def test_a_slot_with_no_settled_owner_still_follows_seniority(self):
        """Ownership narrows rule 3; it does not retire it."""
        team = self._team()
        # Nobody works Monday's opening consistently.
        history = self._history()
        rotation = ["e2", "e3", "e4", "e5", "e6"]
        for i, roster in enumerate(history):
            for shift in roster["shifts"]:
                if shift["day"] == "mon" and (shift["start"], shift["end"]) == self.SLOT:
                    shift["employee_id"] = rotation[i % len(rotation)]

        shop = make_shop(role_hierarchy=["Manager", "Floor Assistant"])
        result, _ = generate(team=team, shop=shop, hist=history)
        assert self._opener(result) is not None, "the slot must still be filled"


class TestRegenerateOffersAlternatives:
    """Regenerate has to visibly do something, without undoing settled work.

    Sixteen presses used to produce sixteen identical weeks, because the
    solver is deterministic — so the button looked broken. But reshuffling
    everything is worse than doing nothing: it hands back the 06:00 opening
    somebody has worked for months, and every one of those is an edit the
    manager has to undo.
    """

    def _history_with_an_unowned_slot(self):
        """One slot shared four ways, so nobody owns it; the rest settled."""
        spare = ("16:00", "23:00")
        coverers = ["e7", "e8", "e9", "e10"]
        hist = []
        for w in range(24):
            shifts = [
                {"employee_id": f"e{i}", "day": d, "start": s, "end": e}
                for d in DAYS
                for i, (s, e) in enumerate(SUNDAY if d == "sun" else WEEKDAY)
            ]
            shifts += [
                {"employee_id": coverers[w % 4], "day": d,
                 "start": spare[0], "end": spare[1]}
                for d in DAYS
            ]
            hist.append({
                "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
                "approved": True, "shifts": shifts,
            })
        return hist, spare

    def _solve(self, hist, seed):
        shop, team = make_shop(), make_team(size=16)
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )
        return solve_roster(
            shop, team, [], [], [], WEEK, None, profile,
            history_rosters=hist, seed=seed,
        )

    def test_without_a_seed_nothing_changes(self):
        """Rebalance must stay reproducible: it rearranges the week around a
        decision just made, and anything else it moves is noise."""
        hist, _ = self._history_with_an_unowned_slot()
        first = self._solve(hist, None)
        again = self._solve(hist, None)

        key = lambda r: sorted(  # noqa: E731
            (s["employee_id"], s["day"], s.get("start"), s.get("end"))
            for s in r["shifts"]
        )
        assert key(first) == key(again)

    def test_a_seed_reproduces_its_own_roster(self):
        """A version nobody can reproduce cannot be explained when the
        manager asks why somebody got a shift."""
        hist, _ = self._history_with_an_unowned_slot()
        key = lambda r: sorted(  # noqa: E731
            (s["employee_id"], s["day"], s.get("start"), s.get("end"))
            for s in r["shifts"]
        )
        assert key(self._solve(hist, 4242)) == key(self._solve(hist, 4242))

    def test_settled_shifts_survive_every_regeneration(self):
        """The whole point: re-rolling never disturbs a slot with an owner.

        Asserted against the UNSEEDED roster rather than against the owner
        directly, because an owner does not always get their slot and should
        not: on the fifth day they are already working they are out on the
        five-day rule, exactly as they would be on leave or inside the rest
        window. What must hold is that the seed changes nothing about it —
        whoever an owned slot goes to, it goes to the same person every time.
        """
        from app.services import slot_owners

        hist, _ = self._history_with_an_unowned_slot()
        owners = slot_owners.build_owners(hist)

        def held_by_their_owner(result):
            """Only slots the owner ACTUALLY got.

            A slot whose owner was unavailable falls to somebody else, and who
            that somebody is can legitimately shift between seeds: varying an
            unowned slot changes who is already working that day, which changes
            who is left. Nobody loses a shift they had — the owner was never
            getting this one. What must never move is a shift its owner did get.
            """
            out = {}
            for shift in result["shifts"]:
                if not shift.get("start"):
                    continue
                key = (shift["day"], shift["start"], shift["end"])
                owner = slot_owners.owner_of(owners, *key)
                if owner is not None and shift["employee_id"] == owner:
                    out[key] = owner
            return out

        baseline = held_by_their_owner(self._solve(hist, None))
        assert baseline, "fixture has no settled shifts, so this proves nothing"

        for seed in range(12):
            settled = held_by_their_owner(self._solve(hist, seed))
            missing = set(baseline) - set(settled)
            assert not missing, (
                f"seed {seed} took {sorted(missing)} away from the person who "
                f"owns it — every one of those is an edit the manager has to undo"
            )

    def test_the_unowned_slot_actually_varies(self):
        """Otherwise the button still does nothing and this is theatre."""
        hist, spare = self._history_with_an_unowned_slot()
        seen = set()
        for seed in range(25):
            result = self._solve(hist, seed)
            # Matched on the WHOLE shape. Monday runs 16:00-00:00 as well as
            # the unowned 16:00-23:00, so matching on the start alone collects
            # two people whatever the seed does — and the test passes without
            # anything varying at all.
            who = [
                s["employee_id"] for s in result["shifts"]
                if s["day"] == "mon" and (s.get("start"), s.get("end")) == spare
            ]
            seen.update(who)

        assert len(seen) > 1, (
            f"25 regenerations all gave mon {spare[0]} to {seen} — Regenerate "
            f"is still a button that does nothing"
        )


class TestExtraStaffAreOnTop:
    """Extra is the exact inverse of pinned, and that is the whole design.

        pinned  "THIS person fills that slot"      consumes a slot
        extra   "this person AS WELL AS the slots"  consumes nothing

    That single bit is what makes the manager's two cases come out
    differently with no special-casing anywhere.
    """

    def _locked(self, **flags):
        return [{
            "employee_id": "e9", "day": "mon",
            "start": "06:00", "end": "12:00", **flags,
        }]

    def test_a_pinned_shift_fills_one_of_the_openings(self):
        """Monday runs two 06:00 slots. Somebody pinned onto one leaves one."""
        hist = history()
        shop, team = make_shop(), make_team(size=14)
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile, history_rosters=hist,
            locked_shifts=self._locked(pinned=True),
        )
        opening = [
            s for s in result["shifts"]
            if s["day"] == "mon" and s.get("start") == "06:00"
        ]
        assert len(opening) == 2, (
            f"the pin should fill one of Monday's two 06:00 slots, leaving "
            f"two people at 06:00 in total — got {len(opening)}"
        )

    def test_an_extra_shift_is_on_top_of_them(self):
        """The same person, marked extra, adds to the openings instead."""
        hist = history()
        shop, team = make_shop(), make_team(size=14)
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile, history_rosters=hist,
            locked_shifts=self._locked(pinned=True, extra=True),
        )
        opening = [
            s for s in result["shifts"]
            if s["day"] == "mon" and s.get("start") == "06:00"
        ]
        assert len(opening) == 3, (
            f"an extra must not cancel a slot — both openings should still be "
            f"filled with the extra person on top, got {len(opening)}"
        )
        assert any(s.get("extra") for s in opening), (
            "the extra flag has to survive the round trip, or a rebalance "
            "turns 'as well as' into 'instead of'"
        )

    def test_extra_hours_still_count_against_the_week(self):
        """They are really working. An extra shift that quietly created a
        sixth working day, or free hours, would be a trap."""
        hist = history()
        shop, team = make_shop(), make_team(size=14)
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile, history_rosters=hist,
            locked_shifts=self._locked(pinned=True, extra=True),
        )
        days = {
            s["day"] for s in result["shifts"]
            if s["employee_id"] == "e9" and s.get("start")
        }
        assert len(days) <= 5, f"e9 ended up on {len(days)} days"
        assert "mon" in days


class TestRebalanceOneDay:
    """"Two people are off on Wednesday" does not want the whole week moved.

    Every other day that changes is something the manager has to read,
    understand, and mostly undo.
    """

    def _week(self):
        hist = history()
        shop, team = make_shop(), make_team(size=14)
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )
        first = solve_roster(
            shop, team, [], [], [], WEEK, None, profile, history_rosters=hist,
        )
        return hist, shop, team, profile, first

    def test_no_other_day_moves(self):
        hist, shop, team, profile, first = self._week()
        # Everything outside Wednesday is handed back as locked, which is what
        # the route does for a single-day rebalance.
        locked = [
            s for s in first["shifts"]
            if s["day"] != "wed" and s.get("start") and s.get("end")
        ]
        again = solve_roster(
            shop, team, [], [], [], WEEK, None, profile, history_rosters=hist,
            locked_shifts=locked, only_day="wed",
        )

        def other_days(result):
            return sorted(
                (s["employee_id"], s["day"], s["start"], s["end"])
                for s in result["shifts"]
                if s["day"] != "wed" and s.get("start")
            )

        assert other_days(again) == other_days(first), (
            "a single-day rebalance changed another day — the one thing it "
            "promises not to do"
        )

    def test_another_day_is_not_refilled(self):
        """The case that actually needs the freeze.

        Locking the other days is not enough on its own — if the fill passes
        still run over them, a day that is SHORT gets quietly restaffed. The
        manager asked about Wednesday; Thursday having two fewer people is
        either deliberate or something they are dealing with separately, and
        either way it is not this button's business.
        """
        hist, shop, team, profile, first = self._week()
        thursday = [
            s for s in first["shifts"] if s["day"] == "thu" and s.get("start")
        ]
        assert len(thursday) > 2, "fixture needs a Thursday to thin out"
        dropped = {s["shift_id"] for s in thursday[:2]}

        locked = [
            s for s in first["shifts"]
            if s["day"] != "wed" and s.get("start") and s.get("end")
            and s["shift_id"] not in dropped
        ]
        again = solve_roster(
            shop, team, [], [], [], WEEK, None, profile, history_rosters=hist,
            locked_shifts=locked, only_day="wed",
        )

        still_on = [s for s in again["shifts"] if s["day"] == "thu" and s.get("start")]
        assert len(still_on) == len(thursday) - 2, (
            f"Thursday was restaffed during a Wednesday rebalance: expected "
            f"{len(thursday) - 2} people, found {len(still_on)}"
        )

    def test_the_target_day_is_still_staffed(self):
        hist, shop, team, profile, first = self._week()
        locked = [
            s for s in first["shifts"]
            if s["day"] != "wed" and s.get("start") and s.get("end")
        ]
        again = solve_roster(
            shop, team, [], [], [], WEEK, None, profile, history_rosters=hist,
            locked_shifts=locked, only_day="wed",
        )
        wednesday = [s for s in again["shifts"] if s["day"] == "wed" and s.get("start")]
        assert len(wednesday) == len(profile.slots_for("wed"))

    def test_the_frozen_days_still_count_against_hours(self):
        """Locking rather than ignoring. Otherwise Wednesday would be solved
        as if everybody had a clear week, and push people over their cap."""
        hist, shop, team, profile, first = self._week()
        locked = [
            s for s in first["shifts"]
            if s["day"] != "wed" and s.get("start") and s.get("end")
        ]
        again = solve_roster(
            shop, team, [], [], [], WEEK, None, profile, history_rosters=hist,
            locked_shifts=locked, only_day="wed",
        )
        days = {}
        for shift in again["shifts"]:
            if shift.get("start"):
                days.setdefault(shift["employee_id"], set()).add(shift["day"])
        assert max(len(d) for d in days.values()) <= 5, (
            "somebody ended up on six days — the frozen days were not counted"
        )


class TestNobodyIsPlacedTwiceOnADay:
    """The bug a single-day rebalance exposed.

    Fixed shifts were applied without checking whether the person was already
    placed that day. Normally nothing else has placed them yet, so it never
    showed. Rebalance Day hands the other six days in as LOCKED shifts, which
    are laid down first — so everyone with a fixed shift got a second one on
    top, and their week was counted twice.

    It was invisible in the grid, which draws one cell per person per day: the
    roster read 40h while the stored total said 60h.
    """

    def _shop_with_a_fixed_shift(self):
        """The person needs HEADROOM under their cap for this to bite.

        _apply_fixed_shifts also refuses a shift that would exceed the weekly
        cap, so on a 40h cap the duplicate was rejected by that check instead
        and the bug stayed hidden. It only appears for somebody whose cap
        leaves room for the second copy — which is exactly why it showed up
        for two people at the reference shop and nobody else.
        """
        # The reference shop's exact conditions, which is what it took to
        # reproduce: breaks paid, a salaried 40h contract, and a
        # max_weekly_hours well above it. The cap is what limits the damage —
        # Megan ended on 60h, six shifts of ten, because the seventh would
        # have exceeded 60 and was refused by the cap check instead.
        shop = make_shop(breaks_are_paid=True)
        team = make_team(size=10)
        team[0].update({
            "employment_type": "full_time_contract",
            "contract_span_hours": 40,
            "max_weekly_hours": 60,
        })
        fixed = [{
            "employee_id": "e0", "day": d, "start": "06:00", "end": "16:00",
        } for d in ("mon", "tue", "wed", "thu")]
        return shop, team, fixed

    def test_a_locked_day_does_not_re_add_the_fixed_shift(self):
        shop, team, fixed = self._shop_with_a_fixed_shift()
        hist = history()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )

        first = solve_roster(
            shop, team, [], fixed, [], WEEK, None, profile, history_rosters=hist,
        )
        # Exactly what the Rebalance Day route hands back in.
        locked = [
            s for s in first["shifts"]
            if s["day"] != "sat" and s.get("start") and s.get("end")
        ]
        again = solve_roster(
            shop, team, [], fixed, [], WEEK, None, profile, history_rosters=hist,
            locked_shifts=locked, only_day="sat",
        )

        seen = {}
        for shift in again["shifts"]:
            if not shift.get("start"):
                continue
            key = (shift["employee_id"], shift["day"])
            seen[key] = seen.get(key, 0) + 1

        doubled = [k for k, count in seen.items() if count > 1]
        assert not doubled, f"placed twice on the same day: {doubled}"

    def test_the_reported_hours_match_the_shifts_shown(self):
        """The symptom as the manager met it: the grid said 40h, the total
        said 60h. One cell per person per day is what the grid can draw, so a
        duplicate is invisible there and only the total gives it away."""
        shop, team, fixed = self._shop_with_a_fixed_shift()
        hist = history()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team}
        )
        first = solve_roster(
            shop, team, [], fixed, [], WEEK, None, profile, history_rosters=hist,
        )
        locked = [
            s for s in first["shifts"]
            if s["day"] != "sat" and s.get("start") and s.get("end")
        ]
        again = solve_roster(
            shop, team, [], fixed, [], WEEK, None, profile, history_rosters=hist,
            locked_shifts=locked, only_day="sat",
        )

        mine = [s for s in again["shifts"] if s["employee_id"] == "e0" and s.get("start")]
        # What the grid can show: one shift per day.
        visible = len({s["day"] for s in mine})
        assert len(mine) == visible, (
            f"e0 has {len(mine)} shifts across {visible} days — the extra ones "
            f"are invisible in the grid but counted in the total"
        )
