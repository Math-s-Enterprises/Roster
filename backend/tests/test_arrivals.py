"""How many people come IN each hour — the quantity the manager rosters by.

The shop owner described the model on day one: "at 6:00 two people are
coming in, and it should schedule two people. At 7:00 there are three people
on the floor. At 8:00 somebody is finishing, so bring two people in."

Three models have been tried and only the last one can express that.

  PRESENCE   count bodies on the floor each hour. Dropped: a night worker
             still in at 06:00 is already in the curve, so filling 06:00 to
             target put a fourth body on an hour that always had three.
  SHAPES     count whole shifts by how often each is worked. Scores every
             shape independently, so it does not know that `06:00-16:00`,
             `06:00-14:00` and `06:00-11:00` compete for the same job —
             all three look common, all three get picked, and Saturday comes
             out with three openers where the shop starts two. Where a band
             is FRAGMENTED the reverse happens and a real shift disappears.
  ARRIVALS   count the people who START each hour. Cannot double-count
             changeover, because somebody still on the floor at 06:00 did
             not start at 06:00; and cannot split a band, because every
             shape starting in the hour is the same arrival.

These tests are the shape of the fault the owner reported, written as
synthetic shops rather than against the reference workbook (§9b, §10b).
"""
from datetime import date, timedelta

from app.services.demand import build_profile
from app.services.scheduler import DAYS, solve_roster

WEEK = "2026-08-17"


def make_shop(**overrides):
    shop = {
        "shop_id": "s", "min_shift_hours": 4, "max_shift_hours": 12,
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


def weeks_of(per_week, count=24):
    """`per_week(w)` returns the shifts for week `w`."""
    return [
        {
            "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
            "approved": True,
            "shifts": per_week(w),
        }
        for w in range(count)
    ]


def solve(history, team=None, **kwargs):
    shop = make_shop()
    team = team if team is not None else make_team()
    profile = build_profile(
        shop, history, {e["employee_id"]: e["role"] for e in team})
    return solve_roster(
        shop, team, [], [], [], WEEK, None, profile,
        history_rosters=history, **kwargs)


def starts_at(result, day, hour):
    return [
        s for s in result["shifts"]
        if s["day"] == day and (s.get("start") or "").startswith(f"{hour:02d}:")
    ]


def fragmented_shop(morning, morning_finishes, evening, evening_finishes):
    """A shop whose bands are steady in SIZE but varied in shape.

    `morning` people open at 06:00 every single day; between them they use
    `morning_finishes`, rotating. Likewise `evening` people start at 16:00.
    A bridge shift and a night shift keep the day gapless, so the coverage
    floor has nothing to add and cannot be mistaken for an extra arrival.

    Nothing here is unusual — it is an ordinary shop where the finish moves
    around and the number of bodies does not. That is the case the shape
    list cannot describe: it scores each shape on its own, so a band split
    four ways has four small numbers where the truth is one big one.

    The two configurations below were found by searching 400 shops of this
    form; the slot list gets 189 of them wrong. They are frozen here as
    fixtures rather than generated, so a failure is reproducible.
    """
    team = ([f"m{k}" for k in range(morning)] + ["b0"]
            + [f"v{k}" for k in range(evening)] + ["n0"])

    def week(w):
        shifts = []
        for day in DAYS:
            for k in range(morning):
                shifts.append({
                    "employee_id": f"m{k}", "day": day, "start": "06:00",
                    "end": morning_finishes[(w + k) % len(morning_finishes)]})
            shifts.append({"employee_id": "b0", "day": day,
                           "start": "11:00", "end": "20:00"})
            for k in range(evening):
                shifts.append({
                    "employee_id": f"v{k}", "day": day, "start": "16:00",
                    "end": evening_finishes[(w + k) % len(evening_finishes)]})
            shifts.append({"employee_id": "n0", "day": day,
                           "start": "20:00", "end": "06:00"})
        return shifts

    people = [
        {"employee_id": eid, "name": eid.upper(), "role": "Floor Assistant",
         "age": 30, "hourly_rate": 15.0, "max_weekly_hours": 48,
         "preferred_days_off": [], "departments": ["Shop Floor"],
         "is_active": True}
        for eid in team
    ] + make_team(size=6)
    return weeks_of(week), people


class TestTheHourStartsAsManyPeopleAsItReallyStarts:
    """The owner's report: "usually on Saturdays it's just two people
    starting at 6:00, but in the new roster it's three."
    """

    def test_a_fragmented_evening_does_not_inflate_the_morning(self):
        """Three open; the slot list starts four.

        The day's rounding shortfall is handed to whichever SHAPE has the
        largest fraction left over, and that has nothing to do with which
        HOUR is short. Here the evening is split three ways so each of its
        shapes looks small, the morning's look big, and the morning collects
        a body the shop has never had.
        """
        history, team = fragmented_shop(
            3, ["15:00", "11:00"],
            4, ["23:00", "20:00", "22:00"])
        result = solve(history, team)
        openers = starts_at(result, "mon", 6)
        assert len(openers) == 3, (
            f"three people open this shop every day and the roster starts "
            f"{len(openers)} — "
            f"{sorted((s['employee_id'], s['end']) for s in openers)}"
        )

    def test_a_band_split_four_ways_is_not_erased(self):
        """Two open; the slot list starts NOBODY.

        Each of the four morning shapes is worked about a quarter of the
        time, so every one of them rounds to zero and loses the leftovers to
        a six-way evening. The shop opens with two people and the roster
        opens with none — which is the same fault as the one above, seen
        from the other side, and the likelier reason a manager says the app
        "ignores who works Mondays".
        """
        history, team = fragmented_shop(
            2, ["11:00", "12:00", "13:00", "15:00"],
            4, ["19:00", "20:00", "00:00", "21:00", "22:00", "23:00"])
        result = solve(history, team)
        openers = starts_at(result, "mon", 6)
        assert len(openers) == 2, (
            f"two people open this shop every day and the roster starts "
            f"{len(openers)} — "
            f"{sorted((s['employee_id'], s['end']) for s in openers)}"
        )

    def test_the_shapes_at_that_hour_are_not_collapsed_into_one(self):
        """Two arrivals must not become two copies of the commonest shift.

        The reference shop runs `16:00-00:00` and `16:00-23:00` in the same
        hour, worked by different people. Handing both slots the first
        erases the second along with everybody who works it — the same "pick
        one shape and hunt for somebody to fit it" fault arrivals exist to
        remove, one layer down.

        The people matter here. Where a band is worked by a pool who all
        work all of its shapes, the placeholder cannot matter, because
        `_usual_finish` falls back to the shop's commonest finish anyway —
        which is why deleting the apportionment once measured as harmless
        across 120 shops of exactly that kind. A shape worked by ONE person
        is the case that catches it.
        """
        def week(w):
            shifts = []
            for day in DAYS:
                shifts.append({"employee_id": "e0", "day": day,
                               "start": "06:00", "end": "14:00"})
                # Same hour, two settled shapes, each with its own person.
                shifts.append({"employee_id": "e1", "day": day,
                               "start": "16:00", "end": "00:00"})
                shifts.append({"employee_id": "e2", "day": day,
                               "start": "16:00", "end": "21:00"})
                shifts.append({"employee_id": "e3", "day": day,
                               "start": "00:00", "end": "06:00"})
            return shifts

        result = solve(weeks_of(week))
        finishes = {s["end"] for s in starts_at(result, "mon", 16)}
        assert finishes == {"00:00", "21:00"}, (
            f"mon 16:00 runs two different shifts and the roster produced "
            f"{sorted(finishes)} — one of the shop's real shapes has been "
            f"erased by giving both slots the commonest finish"
        )


class TestTheFinishComesFromWhoeverGotTheShift:
    """Arrivals fix how many come in, never how long each stays.

    Emma finishes her Monday 06:00 at 12:00 in 13 of the 14 weeks that shape
    ran; Megan finishes hers at 16:00. Both open. Choosing one shape for the
    slot and then looking for somebody to fit it is what left Emma's shift
    owned but never offered (§2b).
    """

    # Three people who could open, each with their OWN finish and no other.
    # Two of them open on any given day, so which pair turns up varies and
    # no single pair of placeholder shapes can be right for everybody.
    OPENERS = [("p0", "11:00"), ("p1", "14:00"), ("p2", "17:00")]

    def _shop(self):
        def week(w):
            shifts = []
            for day in DAYS:
                for k in range(2):
                    employee_id, finish = self.OPENERS[(w + k) % 3]
                    shifts.append({"employee_id": employee_id, "day": day,
                                   "start": "06:00", "end": finish})
                shifts.append({"employee_id": "b0", "day": day,
                               "start": "11:00", "end": "20:00"})
                shifts.append({"employee_id": "n0", "day": day,
                               "start": "20:00", "end": "06:00"})
            return shifts

        people = [
            {"employee_id": eid, "name": eid.upper(),
             "role": "Floor Assistant", "age": 30, "hourly_rate": 15.0,
             "max_weekly_hours": 48, "preferred_days_off": [],
             "departments": ["Shop Floor"], "is_active": True}
            for eid in ("p0", "p1", "p2", "b0", "n0")
        ] + make_team(size=5)
        return weeks_of(week), people

    def test_nobody_is_given_a_finish_they_have_never_worked(self):
        history, team = self._shop()
        result = solve(history, team)
        theirs = dict(self.OPENERS)

        wrong = [
            (s["day"], s["employee_id"], s["end"], theirs[s["employee_id"]])
            for s in result["shifts"]
            if s.get("start") == "06:00" and s["employee_id"] in theirs
            and s["end"] != theirs[s["employee_id"]]
        ]
        assert not wrong, (
            f"an opener was given a finish they have never worked — "
            f"{wrong[:4]} (day, who, given, what they actually work). The "
            f"slot's shape is a placeholder; the person brings the finish."
        )


class TestPresenceCapsArrivals:
    """The owner's second condition, in his words: "if there are two people
    starting at 8:00 and the shop needs just 2 people, and we already have
    them who started at 6:00, then it should not put them at 8:00."

    Arrivals say how many normally come in. Presence says whether the shop
    needs them yet.

    Measured on 60 randomised fragmented shops the cap is consulted 3066
    times and fires 244 — about one slot in twelve. It rarely changes the
    day's headcount, because the day-level rounding in `_build_arrivals`
    already keeps the totals honest. What it changes is what the passes
    AFTER the fill then do with a floor they think is short.
    """

    def test_the_solver_does_not_invent_a_start_the_shop_has_never_used(self):
        """Without the cap, Sunday gains an 05:00 start.

        The stretch and coverage passes react to a floor that looks short
        against the curve. Stacking an arrival onto an hour that is already
        covered shifts the shape of the rest of the day, and the correction
        for it is a shift beginning an hour before this shop has ever opened
        — which familiarity would then have to exclude everybody from (§2).
        """
        history, team = fragmented_shop(
            3, ["14:00", "12:00", "11:00"],
            4, ["00:00", "23:00", "20:00", "19:00", "22:00", "21:00"])
        known = {(s["day"], s["start"])
                 for week in history for s in week["shifts"]}

        result = solve(history, team)
        invented = sorted({
            (s["day"], s["start"]) for s in result["shifts"]
            if s.get("start") and (s["day"], s["start"]) not in known
        })
        assert not invented, (
            f"the roster starts somebody at {invented} and this shop has "
            f"never started anybody then"
        )


class TestTheFloorIsNeverLeftToTheCurve:
    """The coverage floor is exempt from the cap (§1 rule 1).

    A shop that is open must have somebody in it, whatever an averaged
    demand curve rounds to. This is the one place arrivals may be overruled
    upward, and it is why the cap lives in the slot fill rather than in
    `demand.py`, where it would have no way to know.
    """

    def test_every_hour_of_every_day_has_somebody_on_the_floor(self):
        """The night is staffed even though the curve rounds it to nobody.

        This shop is open around the clock but covers the small hours only
        every sixth week, so the recency-weighted curve reports `required`
        of 0 from 22:00 to 06:00, and arrivals report nobody starting then
        either. Both are honest averages and both are beside the point: a
        shop that is open has somebody in it.

        That zero is what makes this the case worth testing. The cap asks
        whether the floor already holds what the curve wants, and at an hour
        wanting nobody an empty floor satisfies it — so a cap applied here
        would read "covered" of a dark shop and leave it dark.
        """
        def week(w):
            shifts = [
                {"employee_id": eid, "day": day, "start": start, "end": end}
                for day in DAYS
                for eid, start, end in (
                    ("e0", "06:00", "14:00"),
                    ("e1", "14:00", "22:00"),
                )
            ]
            if w % 6 == 0:
                shifts += [
                    {"employee_id": "e2", "day": day, "start": "22:00",
                     "end": "06:00"}
                    for day in DAYS
                ]
            return shifts

        result = solve(weeks_of(week))
        for day in DAYS:
            hours = set()
            for shift in result["shifts"]:
                if shift["day"] != day or not shift.get("start"):
                    continue
                first = int(shift["start"][:2])
                last = int(shift["end"][:2]) or 24     # 00:00 means midnight
                if last <= first:                      # runs past midnight
                    last += 24
                hours.update(h % 24 for h in range(first, last))
            assert len(hours) == 24, (
                f"{day} is staffed for only {len(hours)} hours of 24 — the "
                f"coverage floor must not be capped by the demand curve"
            )
