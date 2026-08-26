"""Who normally works a given shift.

The thresholds are the whole design here, so they are asserted by number
rather than by constant: a test written as `>= OWNERSHIP_SHARE` passes
whatever that value happens to be, which is no protection against changing it
by accident.
"""
from app.services.slot_owners import (
    MIN_OCCURRENCES,
    OWNERSHIP_SHARE,
    build_owners,
    owner_of,
    preference_order,
)


def week(week_start, *shifts):
    return {
        "week_start": week_start, "approved": True,
        "shifts": [
            {"employee_id": e, "day": d, "start": s, "end": t}
            for e, d, s, t in shifts
        ],
    }


def weeks(pattern, count=10, day="mon", slot=("06:00", "16:00")):
    """`pattern` is a list of employee ids, cycled to build history."""
    out = []
    for i in range(count):
        out.append(week(
            f"2026-0{1 + i // 28}-{1 + i % 28:02d}",
            (pattern[i % len(pattern)], day, *slot),
        ))
    return out


class TestThresholds:
    def test_the_share_and_the_count_are_what_they_say(self):
        assert OWNERSHIP_SHARE == 0.6
        assert MIN_OCCURRENCES == 4

    def test_one_appearance_is_not_ownership(self):
        """100% of one time means nothing."""
        owners = build_owners([week("2026-01-05", ("emma", "mon", "06:00", "16:00"))])
        assert owner_of(owners, "mon", "06:00", "16:00") is None

    def test_three_of_three_is_still_too_few(self):
        owners = build_owners(weeks(["emma"], count=3))
        assert owner_of(owners, "mon", "06:00", "16:00") is None

    def test_four_of_four_is_ownership(self):
        owners = build_owners(weeks(["emma"], count=4))
        assert owner_of(owners, "mon", "06:00", "16:00") == "emma"

    def test_a_frequent_but_minority_worker_owns_nothing(self):
        """4 of 20 is frequent and still not ownership."""
        owners = build_owners(weeks(["emma", "a", "b", "c", "d"], count=20))
        assert owner_of(owners, "mon", "06:00", "16:00") is None

    def test_the_share_boundary(self):
        # 6 of 10 = 60%, exactly the threshold, so it counts.
        history = weeks(["emma"], count=6) + [
            week(f"2026-05-{d:02d}", ("other", "mon", "06:00", "16:00"))
            for d in range(1, 5)
        ]
        owners = build_owners(history)
        assert owner_of(owners, "mon", "06:00", "16:00") == "emma"

    def test_just_under_the_share_is_not_ownership(self):
        # 5 of 10 = 50%.
        history = weeks(["emma"], count=5) + [
            week(f"2026-05-{d:02d}", ("other", "mon", "06:00", "16:00"))
            for d in range(1, 6)
        ]
        owners = build_owners(history)
        assert owner_of(owners, "mon", "06:00", "16:00") is None


class TestOwnershipIsPerDayAndSlot:
    def test_owning_monday_is_not_owning_saturday(self):
        """In the manager's head these are different shifts.

        Both shifts go in the SAME weeks — building them as separate weeks
        would collide on week_start and latest_per_week would keep only one,
        which says nothing about ownership.
        """
        history = [
            week(f"2026-01-{d:02d}",
                 ("emma", "mon", "06:00", "16:00"),
                 ("kyle", "sat", "06:00", "16:00"))
            for d in range(1, 7)
        ]
        owners = build_owners(history)
        assert owner_of(owners, "mon", "06:00", "16:00") == "emma"
        assert owner_of(owners, "sat", "06:00", "16:00") == "kyle"

    def test_owning_the_morning_is_not_owning_the_evening(self):
        history = [
            week(f"2026-01-{d:02d}",
                 ("emma", "mon", "06:00", "16:00"),
                 ("tara", "mon", "16:00", "00:00"))
            for d in range(1, 7)
        ]
        owners = build_owners(history)
        assert owner_of(owners, "mon", "06:00", "16:00") == "emma"
        assert owner_of(owners, "mon", "16:00", "00:00") == "tara"

    def test_an_unknown_slot_has_no_owner(self):
        owners = build_owners(weeks(["emma"], count=6))
        assert owner_of(owners, "mon", "13:00", "21:00") is None


class TestFallbackOrder:
    def test_the_second_choice_is_who_actually_covers(self):
        history = weeks(["emma", "emma", "emma", "kyle", "emma", "tara"], count=12)
        owners = build_owners(history)
        order = preference_order(owners, "mon", "06:00", "16:00")

        assert order[0] == "emma"
        assert order[1] == "kyle", "kyle covers more often than tara"
        assert set(order) == {"emma", "kyle", "tara"}

    def test_a_slot_nobody_has_worked_has_no_order(self):
        owners = build_owners(weeks(["emma"], count=6))
        assert preference_order(owners, "sun", "23:30", "07:00") == []


class TestWhatIsNotSignal:
    def test_leave_does_not_build_ownership(self):
        history = [
            {"week_start": f"2026-01-{d:02d}", "approved": True, "shifts": [
                {"employee_id": "emma", "day": "mon", "start": "06:00",
                 "end": "16:00", "paid_holiday": True},
            ]}
            for d in range(1, 9)
        ]
        assert owner_of(build_owners(history), "mon", "06:00", "16:00") is None

    def test_extra_shifts_do_not_build_ownership(self):
        """Extra staff are deliberately above the requirement — being added
        for a busy spell does not make the shift yours."""
        history = [
            {"week_start": f"2026-01-{d:02d}", "approved": True, "shifts": [
                {"employee_id": "emma", "day": "mon", "start": "06:00",
                 "end": "16:00", "extra": True},
            ]}
            for d in range(1, 9)
        ]
        assert owner_of(build_owners(history), "mon", "06:00", "16:00") is None

    def test_a_duplicated_week_cannot_manufacture_a_habit(self):
        """Two rosters for one week would let a single week look settled."""
        one = week("2026-01-05", ("emma", "mon", "06:00", "16:00"))
        duplicated = [one, dict(one), dict(one), dict(one), dict(one)]
        assert owner_of(build_owners(duplicated), "mon", "06:00", "16:00") is None

    def test_an_excluded_roster_is_ignored(self):
        history = weeks(["emma"], count=6)
        for roster in history:
            roster["exclude_from_ai"] = True
        assert build_owners(history) == {}


class TestTheDenominatorIsWeeksNotShifts:
    """From real data. Megan opens Monday 06:00-16:00 in 81% of the weeks it
    runs — she plainly owns it. But counted against every SHIFT of that shape
    she came out at 53%, under the bar, purely because a colleague sometimes
    worked it too. Their shifts inflated her denominator.

    The same denominator is what makes a doubled slot work: Tuesday runs
    06:00-16:00 twice, and over 23 weeks Megan has 21 and John 17, so both
    clear the bar and own one instance each.
    """

    def _monday(self):
        """21 weeks. Megan 17, Emma 9, Kevin 2, Conor 2 — 32 shifts."""
        extras = (["emma"] * 9 + ["kevin"] * 2 + ["conor"] * 2)
        out = []
        for i in range(21):
            shifts = [{"employee_id": "megan", "day": "mon",
                       "start": "06:00", "end": "16:00"}] if i < 17 else []
            if i < len(extras):
                shifts.append({"employee_id": extras[i], "day": "mon",
                               "start": "06:00", "end": "16:00"})
            out.append({
                "week_start": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}",
                "approved": True, "shifts": shifts,
            })
        return out

    def test_the_regular_owns_it(self):
        owners = build_owners(self._monday())
        assert owner_of(owners, "mon", "06:00", "16:00") == "megan"

    def test_measuring_against_shifts_would_have_failed(self):
        """The arithmetic that caused the bug, kept as the reason."""
        owners = build_owners(self._monday())
        history = owners[("mon", "06:00", "16:00")]
        shifts = sum(c for _, c in history.people)

        assert history.people[0][1] / shifts < OWNERSHIP_SHARE, (
            "as a share of shifts the regular is under the bar"
        )
        assert history.people[0][1] / history.weeks >= OWNERSHIP_SHARE, (
            "as a share of weeks she is clearly the owner"
        )

    def test_an_occasional_colleague_does_not_become_the_owner(self):
        owners = build_owners(self._monday())
        assert preference_order(owners, "mon", "06:00", "16:00")[0] == "megan"

    def test_a_slot_run_twice_a_week_can_have_two_regulars(self):
        """Tuesday: Megan 21 and John 17 across 23 weeks."""
        out = []
        for i in range(23):
            shifts = [{"employee_id": "megan", "day": "tue",
                       "start": "06:00", "end": "16:00"}] if i < 21 else []
            if i < 17:
                shifts.append({"employee_id": "john", "day": "tue",
                               "start": "06:00", "end": "16:00"})
            out.append({
                "week_start": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}",
                "approved": True, "shifts": shifts,
            })

        owners = build_owners(out)
        history = owners[("tue", "06:00", "16:00")]

        assert owner_of(owners, "tue", "06:00", "16:00") == "megan"
        assert history.people[1][1] / history.weeks >= OWNERSHIP_SHARE, (
            "the second regular also clears the bar for their own instance"
        )
        assert preference_order(owners, "tue", "06:00", "16:00")[:2] == [
            "megan", "john",
        ]

    def test_weeks_is_what_the_minimum_counts(self):
        """Four shifts across two weeks is not four weeks of evidence."""
        out = [
            {"week_start": f"2026-01-{d:02d}", "approved": True, "shifts": [
                {"employee_id": "megan", "day": "tue",
                 "start": "06:00", "end": "16:00"},
                {"employee_id": "john", "day": "tue",
                 "start": "06:00", "end": "16:00"},
            ]}
            for d in (5, 12)
        ]
        assert owner_of(build_owners(out), "tue", "06:00", "16:00") is None


class TestALeaverCannotOwnAShift:
    """Tintu resigned, and still owned Monday 18:00-00:00.

    Her history is real and stays in the demand profile — the shop did run
    that shift. But left in the ownership map she wins the slot on every
    generation, is found ineligible, and it falls through to second place, so
    whoever actually works it now never becomes its owner. The diagnostics
    also name somebody who has left, which sends the manager looking for a
    person who is not there.
    """

    def _weeks(self, worker_by_week):
        from datetime import date, timedelta

        return [
            {
                "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
                "approved": True,
                "shifts": [{
                    "employee_id": who, "day": "mon",
                    "start": "18:00", "end": "00:00",
                }],
            }
            for w, who in enumerate(worker_by_week)
        ]

    def test_a_leaver_is_not_the_owner(self):
        from app.services.slot_owners import build_owners, owner_of

        weeks = self._weeks(["tintu"] * 20 + ["ebyn"] * 4)
        assert owner_of(build_owners(weeks), "mon", "18:00", "00:00") == "tintu"

        active = {"ebyn"}
        owners = build_owners(weeks, active)
        assert owner_of(owners, "mon", "18:00", "00:00") is None

    def test_the_denominator_still_counts_the_weeks_the_slot_ran(self):
        """Ebyn covered it 4 times out of 24 — that is not a habit.

        Recomputing the share over only the remaining weeks would make it
        4 of 4 and hand him a shift he has barely worked.
        """
        from app.services.slot_owners import build_owners

        weeks = self._weeks(["tintu"] * 20 + ["ebyn"] * 4)
        history = build_owners(weeks, {"ebyn"})[("mon", "18:00", "00:00")]

        assert history.weeks == 24, "the slot ran 24 weeks regardless of who worked it"
        assert history.people == [("ebyn", 4)]

    def test_a_successor_who_really_has_taken_it_over_does_own_it(self):
        from app.services.slot_owners import build_owners, owner_of

        # Tintu for the first 6 weeks, Ebyn for the last 18.
        weeks = self._weeks(["tintu"] * 6 + ["ebyn"] * 18)
        owners = build_owners(weeks, {"ebyn"})
        assert owner_of(owners, "mon", "18:00", "00:00") == "ebyn"

    def test_omitting_active_ids_keeps_the_old_behaviour(self):
        """Callers that do not know who is active must not silently lose
        every owner."""
        from app.services.slot_owners import build_owners, owner_of

        weeks = self._weeks(["tintu"] * 20 + ["ebyn"] * 4)
        assert owner_of(build_owners(weeks), "mon", "18:00", "00:00") == "tintu"
