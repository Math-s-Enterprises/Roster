"""An extra teaches the shift's timing and who worked it, not the headcount.

`extra` means "this person AS WELL AS the usual cover" (§2d). The shop owner's
own words on what it should teach:

    "I want it to learn the timings of the shift, not the total number of
    people on the shift, because it's very rare. I want the solver to learn
    the timing of the shift and who worked, so in the future it can learn if
    there is a shift from this time to this."

Before this, the three learners disagreed and none of them did that:

  * `demand.py` counted extras toward the staffing LEVEL, so one extra
    permanently raised how many bodies the day was thought to need
  * `demand.py` counted extras toward the SHAPE vocabulary, which was right
  * `slot_owners.py` ignored extras entirely, so a shift added every week for
    six months never became anybody's

The rule now: extras feed the shape vocabulary and, once a shape has earned a
place in `day_slots` on its own frequency, ownership too. They never raise the
staffing level, so an extra cannot ask for another body next week.
"""
from datetime import date, timedelta

from app.services import slot_owners
from app.services.demand import build_profile
from app.services.scheduler import DAYS

WEEK = "2026-09-14"
SHAPE = ("09:00", "17:00")
LATE = ("17:00", "21:00")


def make_shop(**overrides):
    shop = {
        "shop_id": "s", "min_shift_hours": 4, "max_shift_hours": 12,
        "hours": [
            {"day": d, "open": "09:00", "close": "21:00", "closed": False}
            for d in DAYS
        ],
    }
    shop.update(overrides)
    return shop


ROLES = {"a": "Shop Floor", "b": "Shop Floor", "emma": "Shop Floor"}


def history(count=12, *, extra_weeks=(), extra_person="emma"):
    """`a` works the standard shape every day; extras are added on Mondays."""
    out = []
    for w in range(count):
        shifts = [
            {"employee_id": "a", "day": d, "start": SHAPE[0], "end": SHAPE[1]}
            for d in DAYS
        ]
        if w in extra_weeks:
            shifts.append({
                "employee_id": extra_person, "day": "mon",
                "start": LATE[0], "end": LATE[1], "extra": True,
            })
        out.append({
            "week_start": (date(2026, 6, 22)
                           + timedelta(weeks=w)).isoformat(),
            "approved": True, "created_at": f"{w:03d}", "shifts": shifts,
        })
    return out


class TestAnExtraDoesNotRaiseTheStaffingLevel:
    def test_one_extra_does_not_ask_for_another_body_next_week(self):
        """The complaint this fixes: add somebody once and the shop is
        thought to need an extra person on Mondays for ever."""
        plain = build_profile(make_shop(), history(), ROLES, for_week=WEEK)
        withextra = build_profile(
            make_shop(), history(extra_weeks=(11,)), ROLES, for_week=WEEK)
        assert (withextra.required("mon", 18)
                == plain.required("mon", 18)), (
            "a single extra raised how many people Monday evening needs"
        )

    def test_even_a_repeated_extra_does_not_raise_the_level(self):
        """Ten extras is evidence about the SHAPE, not about how many bodies
        the shop needs at once. If the shop genuinely needs two people at
        18:00 the manager rosters two, and that is a different action."""
        plain = build_profile(make_shop(), history(), ROLES, for_week=WEEK)
        repeated = build_profile(
            make_shop(), history(extra_weeks=tuple(range(12))), ROLES,
            for_week=WEEK)
        assert (repeated.required("mon", 18)
                == plain.required("mon", 18))

    def test_an_ordinary_shift_still_raises_the_level(self):
        """The guard against fixing this by ignoring Mondays altogether."""
        hist = history()
        for roster in hist:
            roster["shifts"].append({
                "employee_id": "b", "day": "mon",
                "start": LATE[0], "end": LATE[1],
            })
        plain = build_profile(make_shop(), history(), ROLES, for_week=WEEK)
        busier = build_profile(make_shop(), hist, ROLES, for_week=WEEK)
        assert busier.required("mon", 18) > plain.required("mon", 18), (
            "a normal recurring shift must still teach the staffing level"
        )


class TestAnExtraTeachesTheShape:
    def test_a_repeated_extra_becomes_a_shift_the_shop_runs(self):
        """"so in the future it can learn if there is a shift from this time
        to this" — the shape enters the vocabulary on its own frequency."""
        profile = build_profile(
            make_shop(), history(extra_weeks=tuple(range(12))), ROLES,
            for_week=WEEK)
        assert LATE in (profile.slots_for("mon") or []), (
            f"a shape added every week for twelve weeks is not in the "
            f"vocabulary: {profile.slots_for('mon')}"
        )


class TestOwnershipFormsOnlyOnRealSlots:
    def _owners(self, hist, profile):
        return slot_owners.build_owners(
            hist, {"a", "b", "emma"},
            known_shapes={
                (day, start, end)
                for day in DAYS
                for start, end in (profile.slots_for(day) or [])
            } or None,
        )

    def test_a_repeated_extra_can_become_its_owner(self):
        """Once the shape is a real slot, the app may learn whose it is."""
        hist = history(extra_weeks=tuple(range(12)))
        profile = build_profile(make_shop(), hist, ROLES, for_week=WEEK)
        assert LATE in (profile.slots_for("mon") or []), "fixture: not a slot"
        owners = self._owners(hist, profile)
        assert slot_owners.owner_of(owners, "mon", *LATE) == "emma", (
            "a shift added every week for twelve weeks never became hers"
        )

    def test_a_one_off_extra_creates_no_owner(self):
        """The §2d trap: an extra that is not a real slot must not make
        somebody its owner, or the solver places them there as ordinary
        cover and 'as well as' silently becomes 'instead of'."""
        hist = history(extra_weeks=(9, 10, 11))
        profile = build_profile(make_shop(), hist, ROLES, for_week=WEEK)
        owners = self._owners(hist, profile)
        if LATE not in (profile.slots_for("mon") or []):
            assert slot_owners.owner_of(owners, "mon", *LATE) is None, (
                "somebody owns a slot the shop does not run"
            )

    def test_extras_are_ignored_when_no_shapes_are_supplied(self):
        """The diagnostics call `build_owners` without a profile. There,
        extras must stay out — the old, safe behaviour."""
        hist = history(extra_weeks=tuple(range(12)))
        owners = slot_owners.build_owners(hist, {"a", "b", "emma"})
        assert slot_owners.owner_of(owners, "mon", *LATE) is None
