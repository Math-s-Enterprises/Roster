"""Owning the START of a shift is a claim, even when the finish moves.

Reported three times: "Emma usually works every Monday at 6:00 am, but she
was not rostered at 6:00 at all." Every ownership check reported sound, and
every one of them was right. Her real Monday, from 31 approved weeks:

    06:00-16:00   worked 10 of 29   34%   no claim
    06:00-14:00   worked  2 of 26    8%   no claim
    06:00-12:00   worked 13 of 14   93%   HERS
    06:00 (any)   worked 25 of 31   81%   HERS

She owns the short opener outright. `day_slots` picks the shop's most COMMON
shapes and drops hers for being rarer than its neighbours, so the solver
never offers it — and she is left competing for a 06:00-16:00 she works a
third of the time, which she loses on the tie-break. She did not lose the
slot she owns. It was never on the board.

So a start time is a claim in its own right, as familiarity has always
treated it (§2): a person is either there to open or they are not, and the
finish is a separate question the contract and hour-fitting passes settle.
"""
from datetime import date, timedelta

from app.services import slot_owners
from app.services.demand import build_profile
from app.services.scheduler import DAYS, solve_roster

WEEK = "2026-09-14"


def make_shop(**overrides):
    shop = {
        "shop_id": "s", "min_shift_hours": 4, "max_shift_hours": 12,
        "hours": [
            {"day": d, "open": "06:00", "close": "22:00", "closed": False}
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


def emmas_mondays(weeks=20):
    """Emma opens at 06:00 nearly every week; her finish varies.

    Deliberately built so no single shape reaches the 60% bar while the
    START does — the shape of the real problem.
    """
    out = []
    for w in range(weeks):
        # Emma opens every week. The LONG opener rotates between two
        # colleagues so neither reaches the bar on it — that shape has to be
        # genuinely unowned, or `owner_of` answers and the start-time branch
        # never runs. A first version had one colleague on it every week,
        # which made the test pass for the wrong reason.
        finish = "12:00" if w % 3 else "16:00"
        shifts = [
            {"employee_id": "emma", "day": "mon",
             "start": "06:00", "end": finish},
            {"employee_id": "ann" if w % 2 else "ben", "day": "mon",
             "start": "06:00", "end": "16:00"},
            {"employee_id": "evening", "day": "mon",
             "start": "14:00", "end": "22:00"},
        ]
        out.append({
            "week_start": (date(2026, 4, 27)
                           + timedelta(weeks=w)).isoformat(),
            "approved": True, "created_at": f"{w:03d}", "shifts": shifts,
        })
    return out


class TestAStartTimeIsAClaim:
    def test_the_fixture_reproduces_the_reported_shape_of_the_problem(self):
        """Guard for the guards, and it is not what I first assumed.

        Emma DOES own her short opener outright — 13 of the 13 weeks it ran,
        exactly as in the real data (93% of 14). The fault is not that she
        owns nothing. It is that the shape she owns is not offered, and she
        has no claim on the one that is. A first version of this test
        asserted she owned nothing and failed immediately, which was the
        fixture being right and the assumption being wrong.
        """
        owners = slot_owners.build_owners(emmas_mondays())
        assert slot_owners.owner_of(
            owners, "mon", "06:00", "12:00") == "emma", (
            "fixture: emma should own her short opener outright"
        )
        assert slot_owners.owner_of(
            owners, "mon", "06:00", "16:00") != "emma", (
            "fixture: emma must NOT own the long opener — that is the shape "
            "the solver offers and the one she keeps losing"
        )
        assert "emma" in slot_owners.regulars_of_start(
            slot_owners.build_start_owners(emmas_mondays()),
            "mon", "06:00"), "fixture: emma must own the 06:00 START"

    def test_the_start_owner_is_ranked_first_for_an_unowned_opening(self):
        """The change itself, tested where it happens.

        Asserted on `_history_rank` rather than through a full solve, because
        whether Emma's own shape survives apportionment into `day_slots`
        varies with the fixture — and it is not what this change is about.
        This is: when the shop offers a 06:00-16:00 that NOBODY owns, the
        person who opens at 06:00 every week is first in the queue for it
        instead of losing on a tie-break.
        """
        from app.services.scheduler import _RosterBuilder
        hist = emmas_mondays()
        team = [person("emma"), person("ann"), person("ben"),
                person("evening")]
        shop = make_shop()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team})
        builder = _RosterBuilder(
            shop, team, [], [], [], WEEK, {}, profile, hist,
            None, None, None,
        )
        assert slot_owners.owner_of(
            builder.slot_owners, "mon", "06:00", "16:00") != "emma"

        ranks = builder._history_rank(team, "mon", "06:00", "16:00")
        assert ranks.get("emma") == 0, (
            f"the person who opens every Monday is not first for an unowned "
            f"06:00 opening: {ranks}"
        )

    def test_an_exact_owner_still_beats_a_start_owner(self):
        """Start-time ownership only speaks where the shape is UNOWNED.

        Somebody who works 06:00-16:00 every single week owns it outright,
        and must keep it against a colleague whose claim is only on the hour.
        """
        hist = []
        for w in range(20):
            hist.append({
                "week_start": (date(2026, 4, 27)
                               + timedelta(weeks=w)).isoformat(),
                "approved": True, "created_at": f"{w:03d}",
                "shifts": [
                    {"employee_id": "exact", "day": "mon",
                     "start": "06:00", "end": "16:00"},
                    # `starter` opens most weeks, but on a moving finish.
                    {"employee_id": "starter", "day": "mon",
                     "start": "06:00", "end": "12:00" if w % 3 else "14:00"},
                    {"employee_id": "evening", "day": "mon",
                     "start": "14:00", "end": "22:00"},
                ],
            })
        owners = slot_owners.build_owners(hist)
        assert slot_owners.owner_of(owners, "mon", "06:00", "16:00") == "exact"

        from app.services.scheduler import _RosterBuilder
        team = [person("exact"), person("starter"), person("evening")]
        shop = make_shop()
        profile = build_profile(
            shop, hist, {e["employee_id"]: e["role"] for e in team})
        builder = _RosterBuilder(
            shop, team, [], [], [], WEEK, {}, profile, hist,
            None, None, None,
        )
        assert "starter" in slot_owners.regulars_of_start(
            builder.start_owners, "mon", "06:00"), (
            "fixture: starter must own the 06:00 start, or this proves "
            "nothing about the two claims competing"
        )

        # Asserted on the ranks, not through a solve. Run end to end, the
        # later tie-breaks rescue the right answer even when both are ranked
        # 0 — so a full-solve version of this test stayed green when the
        # start-time branch was allowed to override an exact owner.
        ranks = builder._history_rank(team, "mon", "06:00", "16:00")
        assert ranks.get("exact") == 0, ranks
        assert ranks.get("starter") != 0, (
            f"a claim on the hour was allowed to rank level with a settled "
            f"claim on the whole shift: {ranks}"
        )


class TestItDoesNotOverreach:
    def test_a_start_worked_occasionally_is_not_a_claim(self):
        """Somebody who covers an opening now and then has a preference, not
        a claim (§2b). The 60% bar applies to start times too."""
        hist = []
        for w in range(20):
            shifts = [{"employee_id": "regular", "day": "mon",
                       "start": "06:00", "end": "16:00"}]
            if w % 4 == 0:                      # 5 of 20 — a quarter
                shifts[0]["employee_id"] = "occasional"
            hist.append({
                "week_start": (date(2026, 4, 27)
                               + timedelta(weeks=w)).isoformat(),
                "approved": True, "created_at": f"{w:03d}", "shifts": shifts,
            })
        owners = slot_owners.build_owners(hist)
        assert "occasional" not in slot_owners.regulars_of_start(
            slot_owners.build_start_owners(hist), "mon", "06:00")
        assert "regular" in slot_owners.regulars_of_start(
            slot_owners.build_start_owners(hist), "mon", "06:00")

    def test_too_few_weeks_is_not_a_habit(self):
        """MIN_OCCURRENCES applies to starts as it does to shapes — three
        openings is not a pattern."""
        hist = [{
            "week_start": (date(2026, 8, 31)
                           + timedelta(weeks=w)).isoformat(),
            "approved": True, "created_at": f"{w:03d}",
            "shifts": [{"employee_id": "newcomer", "day": "mon",
                        "start": "06:00", "end": "16:00"}],
        } for w in range(3)]
        owners = slot_owners.build_owners(hist)
        assert slot_owners.regulars_of_start(
            slot_owners.build_start_owners(hist), "mon", "06:00") == set()

    def test_a_different_day_is_a_different_claim(self):
        """Opening every Monday says nothing about Saturday."""
        owners = slot_owners.build_owners(emmas_mondays())
        assert slot_owners.regulars_of_start(
            slot_owners.build_start_owners(emmas_mondays()),
            "sat", "06:00") == set()


class TestNearbyStartsArePooled:
    """Jane's Saturday, and why an exact start is not enough.

        sat 06:00   12 of 31   39%   no claim
        sat 10:00    7 of 18   39%   no claim
        sat 11:00    8 of 19   42%   no claim

    Nothing clears the bar alone, so she has no claim on any Saturday — while
    plainly being the person who does late-morning Saturdays. Pooling starts
    within an hour gives her one, and leaves her 06:00 separate, four hours
    away. That is the tolerance familiarity has always used (§2).
    """

    def _janes_saturdays(self, weeks=20):
        out = []
        for w in range(weeks):
            # Jane alternates 10:00 and 11:00; a colleague opens at 06:00 and
            # another takes whichever of the two Jane did not.
            jane_start = "10:00" if w % 2 else "11:00"
            other = "11:00" if w % 2 else "10:00"
            out.append({
                "week_start": (date(2026, 4, 27)
                               + timedelta(weeks=w)).isoformat(),
                "approved": True, "created_at": f"{w:03d}",
                "shifts": [
                    {"employee_id": "jane", "day": "sat",
                     "start": jane_start, "end": "17:00"},
                    {"employee_id": "other", "day": "sat",
                     "start": other, "end": "19:00"},
                    {"employee_id": "opener", "day": "sat",
                     "start": "06:00", "end": "14:00"},
                ],
            })
        return out

    def test_neither_start_alone_is_a_claim(self):
        """The fixture must reproduce the problem or the next test proves
        nothing."""
        starts = slot_owners.build_start_owners(self._janes_saturdays())
        for start in ("10:00", "11:00"):
            assert "jane" not in slot_owners.regulars_of_start(
                starts, "sat", start), (
                f"fixture: jane must not clear the bar on {start} alone"
            )

    def test_pooled_within_an_hour_they_are(self):
        starts = slot_owners.build_start_owners(self._janes_saturdays())
        assert "jane" in slot_owners.regulars_of_start(
            starts, "sat", "11:00", tolerance_minutes=60), (
            "10:00 and 11:00 are an hour apart and together are plainly her "
            "shift, but pooling them found no claim"
        )

    def test_a_distant_start_is_not_pooled_in(self):
        """An hour absorbs 10:00 against 11:00. It must not reach 06:00 for
        somebody who never opens."""
        starts = slot_owners.build_start_owners(self._janes_saturdays())
        assert "jane" not in slot_owners.regulars_of_start(
            starts, "sat", "06:00", tolerance_minutes=60)
        assert "opener" in slot_owners.regulars_of_start(
            starts, "sat", "06:00", tolerance_minutes=60)

    def test_the_denominator_is_the_union_not_the_sum(self):
        """The bug most likely to be written here.

        Pooling 10:00 and 11:00 means "weeks either ran". Summing the two
        week counts would double every week in which both ran, halving every
        share and finding no owners at all — or, added the other way, push
        shares over 100% and make everybody an owner of everything.
        """
        starts = slot_owners.build_start_owners(self._janes_saturdays())
        pooled = {
            employee_id
            for employee_id in ("jane", "other", "opener")
            if employee_id in slot_owners.regulars_of_start(
                starts, "sat", "10:00", tolerance_minutes=60)
        }
        # Jane and `other` each do late mornings in every week, on
        # alternating starts, so BOTH are regulars of the pooled window.
        assert pooled == {"jane", "other"}, pooled

    def test_zero_tolerance_is_the_old_behaviour(self):
        """Callers that want an exact start still get one."""
        starts = slot_owners.build_start_owners(self._janes_saturdays())
        assert slot_owners.regulars_of_start(
            starts, "sat", "10:00") == slot_owners.regulars_of_start(
            starts, "sat", "10:00", tolerance_minutes=0)
