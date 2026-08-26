"""What the manager changed about a generated roster.

These tests are the foundation of the whole corrections feature: if the diff
is wrong, everything built on it learns the wrong lesson. So they assert the
exact correction produced, not merely that something was detected.
"""
from app.services.corrections import diff_roster, edit_count


def shift(eid, day, start="09:00", end="17:00", **extra):
    return {"employee_id": eid, "day": day, "start": start, "end": end, **extra}


class TestNoChange:
    def test_an_untouched_roster_records_nothing(self):
        """The outcome the product is aiming at, and worth recording as such."""
        proposed = [shift("jane", "mon"), shift("kyle", "tue")]
        assert diff_roster(proposed, list(proposed)) == []
        assert edit_count(diff_roster(proposed, list(proposed))) == 0

    def test_reordering_is_not_a_change(self):
        """Shift order in the list is presentation, not meaning."""
        a, b = shift("jane", "mon"), shift("kyle", "tue")
        assert diff_roster([a, b], [b, a]) == []


class TestFourKinds:
    def test_a_time_change_is_moved(self):
        out = diff_roster(
            [shift("megan", "tue", "09:00", "17:00")],
            [shift("megan", "tue", "10:00", "18:00")],
        )
        assert out == [{
            "kind": "moved", "day": "tue", "employee_id": "megan",
            "from_slot": "09:00-17:00", "to_slot": "10:00-18:00",
        }]

    def test_taking_somebody_off_is_removed(self):
        out = diff_roster([shift("andi", "thu")], [])
        assert out == [{
            "kind": "removed", "day": "thu", "employee_id": "andi",
            "slot": "09:00-17:00",
        }]

    def test_putting_somebody_on_is_added(self):
        out = diff_roster([], [shift("kyle", "sat")])
        assert out == [{
            "kind": "added", "day": "sat", "employee_id": "kyle",
            "slot": "09:00-17:00",
        }]

    def test_replacing_one_person_with_another_is_a_swap(self):
        """One decision about a slot, not two unrelated ones.

        A swap says something about BOTH people — the manager preferred Jane
        for these hours AND rejected Kelvin — which remove-plus-add loses.
        """
        out = diff_roster(
            [shift("kelvin", "wed", "06:00", "14:00")],
            [shift("jane", "wed", "06:00", "14:00")],
        )
        assert out == [{
            "kind": "swap", "day": "wed", "slot": "06:00-14:00",
            "employee_id": "jane", "replaced_employee_id": "kelvin",
        }]

    def test_a_swap_is_not_double_counted(self):
        """It must not also appear as a removal and an addition."""
        out = diff_roster(
            [shift("kelvin", "wed", "06:00", "14:00")],
            [shift("jane", "wed", "06:00", "14:00")],
        )
        assert [c["kind"] for c in out] == ["swap"]


class TestNotASwap:
    def test_different_hours_on_the_same_day_are_separate_decisions(self):
        """Kelvin off the morning and Jane onto the evening is two changes,
        not a swap — the manager did not choose Jane *for those hours*."""
        out = diff_roster(
            [shift("kelvin", "wed", "06:00", "14:00")],
            [shift("jane", "wed", "14:00", "22:00")],
        )
        assert sorted(c["kind"] for c in out) == ["added", "removed"]

    def test_the_same_hours_on_a_different_day_are_separate(self):
        out = diff_roster(
            [shift("kelvin", "wed", "06:00", "14:00")],
            [shift("jane", "thu", "06:00", "14:00")],
        )
        assert sorted(c["kind"] for c in out) == ["added", "removed"]


class TestLeaveIsNotACorrection:
    """Somebody being off sick is the world happening, not the manager
    correcting the scheduler. Counting it would teach the roster to avoid
    people who had been ill."""

    def test_a_shift_becoming_sick_leave_is_ignored(self):
        out = diff_roster(
            [shift("jane", "mon")],
            [{"employee_id": "jane", "day": "mon", "sick": True}],
        )
        assert [c["kind"] for c in out] == ["removed"], (
            "the shift did leave the roster, but no leave entry is invented"
        )

    def test_holiday_entries_are_not_compared(self):
        leave = {"employee_id": "jane", "day": "mon", "paid_holiday": True}
        assert diff_roster([leave], [leave]) == []

    def test_a_shift_with_no_times_is_skipped(self):
        assert diff_roster(
            [{"employee_id": "jane", "day": "mon"}],
            [{"employee_id": "jane", "day": "mon"}],
        ) == []


class TestSeveralAtOnce:
    def test_a_realistic_edit_session(self):
        generated = [
            shift("kelvin", "wed", "06:00", "14:00"),
            shift("megan", "tue", "09:00", "17:00"),
            shift("andi", "thu"),
            shift("jane", "mon"),
        ]
        approved = [
            shift("jane", "wed", "06:00", "14:00"),      # swapped in for Kelvin
            shift("megan", "tue", "10:00", "18:00"),     # moved
            shift("kyle", "sat"),                        # added
            shift("jane", "mon"),                        # untouched
        ]
        out = diff_roster(generated, approved)

        assert edit_count(out) == 4
        assert sorted(c["kind"] for c in out) == [
            "added", "moved", "removed", "swap",
        ]

    def test_the_order_is_stable(self):
        """Two runs over the same roster must agree, so stored corrections
        can be compared without re-sorting at every call site."""
        generated = [shift("a", "mon"), shift("b", "tue"), shift("c", "wed")]
        approved = [shift("x", "mon"), shift("b", "tue", "10:00", "18:00")]
        assert diff_roster(generated, approved) == diff_roster(generated, approved)


class TestMissingData:
    def test_no_snapshot_means_no_corrections(self):
        """Rosters generated before this feature have nothing to compare
        against. They contribute nothing rather than being guessed at."""
        assert diff_roster([], [shift("jane", "mon")]) == [{
            "kind": "added", "day": "mon", "employee_id": "jane",
            "slot": "09:00-17:00",
        }]
        assert diff_roster(None, None) == []

    def test_edit_count_handles_nothing(self):
        assert edit_count(None) == 0
        assert edit_count([]) == 0


# ---------------------------------------------------------------------------
# Phase 2 — reading the signal back
# ---------------------------------------------------------------------------
def _week(week_start, corrections_list, generated=True):
    return {
        "week_start": week_start, "approved": True,
        "generated_shifts": [{"employee_id": "x", "day": "mon",
                              "start": "09:00", "end": "17:00"}] if generated else [],
        "corrections": corrections_list,
    }


def _removed(day="wed", who="e1"):
    return {"kind": "removed", "day": day, "employee_id": who, "slot": "09:00-17:00"}


class TestTheEditTrend:
    """The number the whole product exists to reduce."""

    def test_weeks_come_back_oldest_first(self):
        from app.services.corrections import edit_trend

        rosters = [
            _week("2026-08-03", [_removed(), _removed(who="e2")]),
            _week("2026-08-10", [_removed()]),
            _week("2026-08-17", []),
        ]
        trend = edit_trend(rosters)

        assert [t["week_start"] for t in trend] == [
            "2026-08-03", "2026-08-10", "2026-08-17",
        ], "a falling line has to read left to right"
        assert [t["edit_count"] for t in trend] == [2, 1, 0]

    def test_a_week_from_before_capture_is_not_reported_as_clean(self):
        """Zero edits and 'we could not tell' are different facts, and
        conflating them flatters the product."""
        from app.services.corrections import edit_trend

        trend = edit_trend([_week("2026-08-03", [], generated=False)])
        assert trend[0]["edit_count"] is None
        assert trend[0]["measurable"] is False

    def test_drafts_are_ignored(self):
        """A roster somebody is halfway through editing says nothing yet."""
        from app.services.corrections import edit_trend

        draft = {**_week("2026-08-24", [_removed()]), "approved": False}
        assert edit_trend([_week("2026-08-17", []), draft]) == [
            {"week_start": "2026-08-17", "version": None,
             "edit_count": 0, "measurable": True},
        ]


class TestPatternsAreCounted:
    def test_the_same_correction_across_weeks_is_one_pattern(self):
        from app.services.corrections import summarise

        rosters = [_week(f"2026-0{7 + i // 4}-{1 + i:02d}", [_removed()])
                   for i in range(3)]
        summary = summarise(rosters)

        assert len(summary["patterns"]) == 1
        assert summary["patterns"][0]["count"] == 3
        assert summary["total_corrections"] == 3

    def test_the_same_shift_on_a_different_day_is_a_different_pattern(self):
        """In the manager's head those are different shifts."""
        from app.services.corrections import summarise

        rosters = [
            _week("2026-08-03", [_removed(day="wed")]),
            _week("2026-08-10", [_removed(day="sat")]),
        ]
        assert len(summarise(rosters)["patterns"]) == 2


class TestSuggestions:
    """A single edit is an event. The third time is the manager telling you
    something."""

    def _repeated(self, correction, times):
        return [
            _week(f"2026-08-{3 + 7 * i:02d}", [correction]) for i in range(times)
        ]

    def test_two_repeats_is_not_yet_a_pattern(self):
        from app.services.corrections import suggestions

        assert suggestions(self._repeated(_removed(), 2)) == []

    def test_three_repeats_offers_a_day_off(self):
        from app.services.corrections import suggestions

        offers = suggestions(self._repeated(_removed(), 3))
        assert len(offers) == 1
        assert offers[0]["action"] == "day_off"
        assert offers[0]["day"] == "wed"
        assert "3 times" in offers[0]["because"]

    def test_a_repeated_addition_offers_a_fixed_shift(self):
        from app.services.corrections import suggestions

        added = {"kind": "added", "day": "sat", "employee_id": "e4",
                 "slot": "08:00-14:00"}
        offers = suggestions(self._repeated(added, 3))
        assert offers[0]["action"] == "fixed_shift"
        assert (offers[0]["start"], offers[0]["end"]) == ("08:00", "14:00")

    def test_a_later_start_offers_an_availability_window(self):
        from app.services.corrections import suggestions

        moved = {"kind": "moved", "day": "tue", "employee_id": "e5",
                 "from_slot": "06:00-14:00", "to_slot": "10:00-18:00"}
        offers = suggestions(self._repeated(moved, 4))
        assert offers[0]["action"] == "earliest_start"
        assert offers[0]["start"] == "10:00"

    def test_an_earlier_start_suggests_nothing(self):
        """Only a start being pushed LATER is evidence of a limit. Pulling
        somebody earlier says they were free all along, which is not a
        setting."""
        from app.services.corrections import suggestions

        moved = {"kind": "moved", "day": "tue", "employee_id": "e5",
                 "from_slot": "10:00-18:00", "to_slot": "06:00-14:00"}
        assert suggestions(self._repeated(moved, 4)) == []

    def test_a_repeated_swap_is_left_to_slot_ownership(self):
        """Two switches for the same fact is one too many: the shop's own
        approved rosters already teach who works a slot."""
        from app.services.corrections import suggestions

        swap = {"kind": "swap", "day": "mon", "slot": "06:00-14:00",
                "employee_id": "e1", "replaced_employee_id": "e2"}
        assert suggestions(self._repeated(swap, 5)) == []

    def test_a_dismissed_suggestion_is_not_offered_again(self):
        """Asking twice is how a helpful suggestion becomes nagging."""
        from app.services.corrections import signature, suggestions

        rosters = self._repeated(_removed(), 4)
        offered = suggestions(rosters)
        assert offered

        assert suggestions(rosters, dismissed=[offered[0]["signature"]]) == []
        assert offered[0]["signature"] == signature(_removed())
