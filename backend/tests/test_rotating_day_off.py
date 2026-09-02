"""A group can take turns having a day off, and the turn comes from history.

The manager, asked how he rosters:

    "If Martin is off for the weekend, then Corey and Jithin will be
     working. If Corey is off, then Martin and Jithin will be working. If
     Jithin is off, Corey and Martin will be working, and it goes on week
     after week. There is a combination to give a weekend off because they
     are on contract. They deserve this."

Confirmed in his own rosters once weeks before the third man was hired were
excluded: 7 of 11 weekends had exactly one of them off, turns spread within
one weekend of each other, in a clean three-week cycle.

This is the FIRST cross-week constraint. Every other custom rule —
`max_staff`, `not_together`, `no_open` — is answerable from the week being
built. Whose turn it is can only come from previous weeks.

NOTHING HERE IS SPECIFIC TO THAT SHOP. The group and the days come from the
rule the manager writes; the tests below use two-person and four-person
groups, and days other than the weekend, on synthetic shops built from
scratch.
"""
from datetime import date, timedelta

from app.services.rule_parser import parse_rule
from app.services.scheduler import DAYS, _RosterBuilder, solve_roster

WEEK = "2026-09-14"
SHAPE = ("09:00", "17:00")


def make_shop(**overrides):
    shop = {
        "shop_id": "s", "min_shift_hours": 4, "max_shift_hours": 12,
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


def rule(group, days=("sat", "sun")):
    return [{
        "rule_id": "r1", "enabled": True, "approved": True,
        "title": "manager rotation",
        "compiled": {
            "type": "rotating_day_off",
            "employee_ids": list(group),
            "days": list(days),
            "description": f"{len(group)} people take turns having "
                           f"{', '.join(days)} off",
        },
    }]


def history(off_by_week, group, days=("sat", "sun"), weeks=9):
    """`off_by_week` maps week index -> who had the days off that week."""
    out = []
    for w in range(weeks):
        shifts = []
        for employee_id in group:
            for day in DAYS:
                if day in days and off_by_week.get(w) == employee_id:
                    continue
                shifts.append({"employee_id": employee_id, "day": day,
                               "start": SHAPE[0], "end": SHAPE[1]})
        out.append({
            "week_start": (date(2026, 7, 13)
                           + timedelta(weeks=w)).isoformat(),
            "approved": True, "created_at": f"{w:03d}", "shifts": shifts,
        })
    return out


class TestTheWording:
    def test_take_turns_having_the_weekend_off_compiles(self):
        people = [person("martin"), person("corey"), person("jithin")]
        compiled = parse_rule(
            "Manager weekends",
            "Martin, Corey and Jithin take turns having the weekend off",
            people)
        assert compiled is not None, "the rule was not understood at all"
        assert compiled["type"] == "rotating_day_off"
        assert set(compiled["employee_ids"]) == {"martin", "corey", "jithin"}
        assert compiled["days"] == ["sat", "sun"]

    def test_other_wordings_and_other_days(self):
        people = [person("ann"), person("ben")]
        for text, days in [
            ("Ann and Ben rotate their Sunday off", ["sun"]),
            ("Ann and Ben alternate having Monday off", ["mon"]),
            ("Ann and Ben take turns having the weekend off", ["sat", "sun"]),
        ]:
            compiled = parse_rule("rota", text, people)
            assert compiled and compiled["type"] == "rotating_day_off", text
            assert compiled["days"] == days, text

    def test_it_does_not_swallow_a_co_working_rule(self):
        """"take turns" names several people and must not be read as one of
        the existing multi-person rules."""
        people = [person("ann"), person("ben")]
        compiled = parse_rule(
            "pairs", "Ann and Ben must not work together", people)
        assert compiled["type"] == "not_together"

    def test_a_rotation_with_no_days_is_not_guessed_at(self):
        """§9: unparseable rules are reported, not guessed. "They take turns"
        without saying turns at WHAT is not a rule."""
        people = [person("ann"), person("ben")]
        assert parse_rule("vague", "Ann and Ben take turns", people) is None


class TestWhoseTurnItIs:
    def _builder(self, hist, group, days=("sat", "sun"), team=None):
        team = team or [person(e) for e in group]
        shop = make_shop()
        return _RosterBuilder(
            shop, team, [], [], rule(group, days), WEEK, {}, None, hist,
            None, None, None,
        )

    def test_whoever_has_gone_longest_without_one_is_next(self):
        group = ["ann", "ben", "cal"]
        # ann off most recently, then ben; cal has not had one for longest.
        hist = history({6: "cal", 7: "ben", 8: "ann"}, group)
        builder = self._builder(hist, group)
        assert builder.rotation_turns.get("sat") == ["cal"], (
            builder.rotation_turns
        )

    def test_somebody_who_never_had_a_turn_goes_first(self):
        group = ["ann", "ben", "cal"]
        hist = history({7: "ben", 8: "ann"}, group)
        builder = self._builder(hist, group)
        assert builder.rotation_turns.get("sat") == ["cal"]

    def test_a_week_they_were_not_working_is_not_a_turn(self):
        """The measurement error that hid the pattern for twenty weeks.

        Somebody not yet hired appears "off" every weekend. Counting that as
        their turn hands the rota to whoever was hired first — at the
        reference shop a colleague hired in June showed 13 weekends off
        against another's 3, purely from absence.
        """
        group = ["ann", "ben", "cal"]
        # ann and ben had their turns LONG ago; `cal` was hired recently and
        # has never had one. The old turns must be deliberately older than
        # cal's absence, or counting absence gives the same answer by luck
        # and this test proves nothing — which is how it first passed under
        # sabotage.
        hist = history({0: "ann", 1: "ben"}, group)
        for roster in hist[:7]:
            roster["shifts"] = [s for s in roster["shifts"]
                                if s["employee_id"] != "cal"]

        builder = self._builder(hist, group)
        assert builder.rotation_turns.get("sat") == ["cal"], (
            "absence was counted as turns, so the newcomer is treated as "
            "having had seven of them and never gets a real one"
        )

    def test_the_same_history_always_gives_the_same_turn(self):
        """A version nobody can reproduce cannot be explained (§2c)."""
        group = ["ann", "ben", "cal"]
        hist = history({6: "cal", 7: "ben", 8: "ann"}, group)
        first = self._builder(hist, group).rotation_turns
        for _ in range(3):
            assert self._builder(hist, group).rotation_turns == first

    def test_a_group_of_two_works(self):
        group = ["ann", "ben"]
        hist = history({8: "ann"}, group)
        assert self._builder(hist, group).rotation_turns.get("sat") == ["ben"]

    def test_a_group_of_four_works(self):
        group = ["ann", "ben", "cal", "dee"]
        hist = history({6: "cal", 7: "ben", 8: "ann"}, group)
        assert self._builder(hist, group).rotation_turns.get("sat") == ["dee"]

    def test_days_other_than_the_weekend_work(self):
        group = ["ann", "ben"]
        hist = history({8: "ann"}, group, days=("wed",))
        turns = self._builder(hist, group, days=("wed",)).rotation_turns
        assert turns.get("wed") == ["ben"]
        assert "sat" not in turns

    def test_no_rule_means_no_turns(self):
        """A shop that has not written one sees no change whatsoever."""
        team = [person("ann"), person("ben")]
        builder = _RosterBuilder(
            make_shop(), team, [], [], [], WEEK, {}, None,
            history({8: "ann"}, ["ann", "ben"]), None, None, None,
        )
        assert builder.rotation_turns == {}


class TestItIsSoftNotHard:
    def test_the_turn_is_given_when_the_shop_can_spare_them(self):
        group = ["ann", "ben", "cal"]
        hist = history({6: "cal", 7: "ben", 8: "ann"}, group)
        team = [person(e) for e in group] + [person("spare")]
        shop = make_shop()
        result = solve_roster(
            shop, team, [], [], rule(group), WEEK, None, None,
            history_rosters=hist)
        saturday = {s["employee_id"] for s in result["shifts"]
                    if s["day"] == "sat"}
        assert "cal" not in saturday, (
            f"cal was due Saturday off and worked it anyway: {saturday}"
        )

    def test_a_turn_never_leaves_the_shop_short(self):
        """The manager pauses his own rotation on busy weeks — 4 of 11
        weekends at the reference shop had nobody off. A hard rule would
        force a day off he would not have given."""
        group = ["ann", "ben"]
        hist = history({8: "ann"}, group)
        # Only these two exist, so somebody must open on Saturday.
        team = [person(e) for e in group]
        result = solve_roster(
            make_shop(), team, [], [], rule(group), WEEK, None, None,
            history_rosters=hist)
        saturday = [s for s in result["shifts"] if s["day"] == "sat"]
        assert saturday, "the rotation left Saturday unstaffed"

    def test_an_overridden_turn_is_reported(self):
        group = ["ann", "ben"]
        hist = history({8: "ann"}, group)
        result = solve_roster(
            make_shop(), [person(e) for e in group], [], [], rule(group),
            WEEK, None, None, history_rosters=hist)
        notes = " ".join(result.get("issues") or [])
        if any(s["employee_id"] == "ben" and s["day"] == "sat"
               for s in result["shifts"]):
            assert "due sat off" in notes, (
                f"ben worked his turn and nothing said why: {notes}"
            )


class TestOnlyOneOfThemIsOffAtATime:
    """"If Martin is off for the weekend, then Corey and Jithin will be
    working." Somebody already away IS the week's absence — giving another a
    turn on top takes two of the group off at once, which is the arrangement
    the rule exists to prevent.

    Reported from the reference shop after the first version shipped:
    "Jithin and Corey both are off."
    """

    def _turns(self, hist, group, holidays=None, team=None):
        team = team or [person(e) for e in group]
        return _RosterBuilder(
            make_shop(), team, holidays or [], [], rule(group), WEEK, {},
            None, hist, None, None, None,
        ).rotation_turns

    def test_nobody_gets_a_turn_when_one_of_them_is_on_leave(self):
        group = ["ann", "ben", "cal"]
        hist = history({6: "cal", 7: "ben", 8: "ann"}, group)
        saturday = (date(2026, 9, 14) + timedelta(days=5)).isoformat()
        holidays = [{"scope": "employee", "employee_id": "cal",
                     "date": saturday, "end_date": saturday}]
        turns = self._turns(hist, group, holidays=holidays)
        assert "sat" not in turns, (
            "cal is already off on leave that Saturday and somebody else was "
            f"given a turn as well — two of the three off at once: {turns}"
        )
        # Sunday is untouched: they are all available, so the rotation runs.
        assert turns.get("sun") == ["cal"] or "sun" not in turns

    def test_nobody_gets_a_turn_when_one_of_them_has_left(self):
        group = ["ann", "ben", "cal"]
        hist = history({6: "cal", 7: "ben", 8: "ann"}, group)
        team = [person("ann"), person("ben"), person("cal", is_active=False)]
        assert self._turns(hist, group, team=team) == {}

    def test_a_turn_is_still_given_when_they_are_all_available(self):
        """The guard must not switch the rule off altogether."""
        group = ["ann", "ben", "cal"]
        hist = history({6: "cal", 7: "ben", 8: "ann"}, group)
        assert self._turns(hist, group).get("sat") == ["cal"]
