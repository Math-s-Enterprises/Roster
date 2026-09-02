"""A settled shift that changes hands for no reason says so.

Every ownership fault at the reference shop was found by the MANAGER reading
a roster and asking about it — a Monday 06:00 given away because the code
asked `owner_of` (one person) about a shape that runs twice and has two
regulars. The check that would have caught it existed only in a diagnostic
nobody runs unless something already looks wrong.

So the solver reports it itself. §2b lists when an owner may lawfully lose a
slot — leave, the curfew, their cap, the rest gap, a fifth day — and senior
cover displaces them by design. All of those stay silent. What is left is a
bug, and it should announce itself the week it happens rather than three
rosters later.

The pass moves nothing and blocks nothing. Its worst failure is a wrong
sentence, not a wrong roster.
"""
from datetime import date, timedelta

from app.services.demand import build_profile
from app.services.scheduler import DAYS, _RosterBuilder

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


def history(pattern, count=12):
    """`pattern` maps employee_id -> the days they work, every week."""
    out = []
    for w in range(count):
        out.append({
            "week_start": (date(2026, 6, 22)
                           + timedelta(weeks=w)).isoformat(),
            "approved": True, "created_at": f"{w:03d}",
            "shifts": [
                {"employee_id": e, "day": d,
                 "start": SHAPE[0], "end": SHAPE[1]}
                for e, days in pattern.items() for d in days
            ],
        })
    return out


def builder_for(pattern, team=None, holidays=None):
    team = team or [person(e) for e in pattern]
    hist = history(pattern)
    shop = make_shop()
    profile = build_profile(
        shop, hist, {e["employee_id"]: e["role"] for e in team})
    return _RosterBuilder(
        shop, team, holidays or [], [], [], WEEK, {}, profile, hist,
        None, None, None,
    ), profile


def notes(builder):
    return [i for i in builder.result.issues
            if "nothing was stopping them" in i]


class TestItSpeaksWhenSomethingIsWrong:
    def test_an_owner_who_lost_their_shift_for_no_reason_is_named(self):
        """Emma's case: she owns Monday, somebody else has it, and nothing
        about her prevented it."""
        b, _ = builder_for({"emma": ["mon"], "other": ["tue"]})
        b._record_shift("other", "mon", *SHAPE)
        b.assigned_by_day.setdefault("mon", set()).add("other")
        b._report_displaced_owners()

        assert len(notes(b)) == 1, notes(b)
        note = notes(b)[0]
        assert "Emma" in note and "Other" in note, note
        assert "mon 09:00-17:00" in note, note

    def test_the_second_regular_losing_out_is_still_reported(self):
        """Emma's exact case, and the only one that pins `regulars_of`.

        Monday runs twice and `emma` and `first` both work it every week. If
        `first` keeps one instance and an outsider takes the other, Emma has
        lost a settled shift — but `owner_of` names only the top claimant, so
        a check built on it sees "the owner got one" and says nothing.

        The sibling test where BOTH regulars keep an instance passes either
        way, which is why it cannot be the only one.
        """
        from app.services import slot_owners
        # Emma must be the SECOND claimant, not the first. With equal counts
        # `people[0]` falls back to sorting by id, and "emma" wins that — so
        # an earlier version of this fixture had her as the owner and passed
        # under `owner_of` too, catching nothing.
        hist = history({"first": ["mon"], "other": ["tue"]})
        for i, roster in enumerate(hist):
            if i >= 3:                       # 9 of 12 weeks — a clear regular
                roster["shifts"].append({
                    "employee_id": "emma", "day": "mon",
                    "start": SHAPE[0], "end": SHAPE[1]})
        team = [person(e) for e in ("emma", "first", "other")]
        shop = make_shop()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team})
        b = _RosterBuilder(shop, team, [], [], [], WEEK, {}, profile, hist,
                           None, None, None)

        assert len(profile.slots_for("mon")) >= 2, "fixture: not a doubled slot"
        assert slot_owners.owner_of(b.slot_owners, "mon", *SHAPE) == "first", (
            "fixture: emma must be the SECOND claimant or this passes under "
            "owner_of as well and pins nothing"
        )
        assert "emma" in slot_owners.regulars_of(b.slot_owners, "mon", *SHAPE)

        b._record_shift("first", "mon", *SHAPE)
        b._record_shift("other", "mon", *SHAPE)
        b.assigned_by_day.setdefault("mon", set()).update({"first", "other"})
        b._report_displaced_owners()

        assert any("Emma" in n for n in notes(b)), (
            f"the second regular lost their Monday and nothing was said: "
            f"{notes(b)}"
        )

    def test_the_note_says_how_settled_the_shift_was(self):
        """"14 of 24 weeks" is what makes it worth reading — a shape somebody
        worked twice is not the same complaint."""
        b, _ = builder_for({"emma": ["mon"], "other": ["tue"]})
        b._record_shift("other", "mon", *SHAPE)
        b.assigned_by_day.setdefault("mon", set()).add("other")
        b._report_displaced_owners()
        assert "% of weeks" in notes(b)[0], notes(b)[0]


class TestItStaysSilentWhenThereIsALawfulReason:
    def _displaced(self, pattern, **kwargs):
        b, _ = builder_for(pattern, **kwargs)
        b._record_shift("other", "mon", *SHAPE)
        b.assigned_by_day.setdefault("mon", set()).add("other")
        b._report_displaced_owners()
        return notes(b)

    def test_nothing_is_said_when_the_owner_is_on_leave(self):
        monday = date(2026, 9, 14).isoformat()
        holidays = [{"scope": "employee", "employee_id": "emma",
                     "date": monday, "end_date": monday}]
        assert self._displaced({"emma": ["mon"], "other": ["tue"]},
                               holidays=holidays) == []

    def test_nothing_is_said_when_the_owner_is_already_working_that_day(self):
        b, _ = builder_for({"emma": ["mon"], "other": ["tue"]})
        b._record_shift("other", "mon", *SHAPE)
        b.assigned_by_day.setdefault("mon", set()).add("other")
        # Emma is on the day, just not on that shape.
        b._record_shift("emma", "mon", "09:00", "13:00")
        b.assigned_by_day["mon"].add("emma")
        b._report_displaced_owners()
        assert notes(b) == []

    def test_nothing_is_said_when_the_owner_is_at_their_weekly_limit(self):
        team = [person("emma", max_weekly_hours=4), person("other")]
        assert self._displaced({"emma": ["mon"], "other": ["tue"]},
                               team=team) == []

    def test_nothing_is_said_when_the_owner_has_left(self):
        team = [person("emma", is_active=False), person("other")]
        assert self._displaced({"emma": ["mon"], "other": ["tue"]},
                               team=team) == []

    def test_nothing_is_said_when_the_owner_is_unavailable(self):
        """The real schema is `availability.available_days`, a list of the
        days they can work — not a per-day flag, which is what this test
        guessed at first and why it failed."""
        team = [person("emma", availability={
            "available_days": ["tue", "wed", "thu", "fri"]}),
            person("other")]
        assert self._displaced({"emma": ["mon"], "other": ["tue"]},
                               team=team) == []


class TestItIsSilentOnAHealthyWeek:
    def test_a_week_where_everybody_got_their_own_shift_says_nothing(self):
        """The cost of this check on a normal week must be zero lines."""
        b, _ = builder_for({"emma": ["mon"], "other": ["tue"]})
        b._record_shift("emma", "mon", *SHAPE)
        b.assigned_by_day.setdefault("mon", set()).add("emma")
        b._record_shift("other", "tue", *SHAPE)
        b.assigned_by_day.setdefault("tue", set()).add("other")
        b._report_displaced_owners()
        assert notes(b) == []

    def test_the_second_regular_on_a_doubled_slot_is_not_reported(self):
        """The bug that started all this, from the reporting side.

        Two people work the same Monday shape every week, so it runs twice
        and both are regulars. Each getting one instance is correct, and
        neither has lost anything — a check built on `owner_of` would call
        the second one displaced every single week.
        """
        b, profile = builder_for({"first": ["mon"], "second": ["mon"],
                                  "other": ["tue"]})
        assert len(profile.slots_for("mon")) >= 2, (
            f"fixture: Monday must run twice, got {profile.slots_for('mon')}"
        )
        b._record_shift("first", "mon", *SHAPE)
        b._record_shift("second", "mon", *SHAPE)
        b.assigned_by_day.setdefault("mon", set()).update({"first", "second"})
        b._report_displaced_owners()
        assert notes(b) == []

    def test_a_shape_nobody_owns_is_not_reported(self):
        """Somebody who covers a slot occasionally has a preference, not a
        claim (§2b), and losing it is not news."""
        pattern = {"a": ["mon"], "b": ["tue"]}
        hist = history(pattern)
        # Break the habit: `a` only works Monday in a third of the weeks.
        for i, roster in enumerate(hist):
            if i % 3:
                roster["shifts"] = [s for s in roster["shifts"]
                                    if not (s["employee_id"] == "a"
                                            and s["day"] == "mon")]
        team = [person("a"), person("b")]
        shop = make_shop()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team})
        b = _RosterBuilder(
            shop, team, [], [], [], WEEK, {}, profile, hist,
            None, None, None,
        )
        b._record_shift("b", "mon", *SHAPE)
        b.assigned_by_day.setdefault("mon", set()).add("b")
        b._report_displaced_owners()
        assert notes(b) == []
