"""Availability, hierarchy, student rules and holiday balance.

Each class covers one of the requested requirements, named so a failure
points straight at the rule it broke.
"""
from datetime import date as _date, timedelta as _td

import pytest

from app.services import availability as avail
from app.services import hierarchy, holiday_balance
from app.services.scheduler import DAYS, _RosterBuilder, solve_roster

WEEK = "2026-08-10"          # a Monday
SUMMER_WEEK = "2026-07-06"   # inside the sample break period


def make_shop(open_time="06:00", close_time="23:00", **overrides):
    shop = {
        "shop_id": "shop_test",
        "hours": [
            {"day": d, "open": open_time, "close": close_time, "closed": False}
            for d in DAYS
        ],
        "min_shift_hours": 4,
        "max_shift_hours": 10,
        "shift_templates": [],
        "strict_days_off": False,
    }
    shop.update(overrides)
    return shop


def make_employee(eid, role="Floor Assistant", **overrides):
    employee = {
        "employee_id": eid,
        "name": f"Employee {eid}",
        "role": role,
        "age": 25,
        "hourly_rate": 13.0,
        "max_weekly_hours": 40,
        "preferred_days_off": [],
        "departments": ["Shop Floor"],
        "is_active": True,
    }
    employee.update(overrides)
    return employee


# ---------------------------------------------------------------------------
# 1. Configurable hierarchy
# ---------------------------------------------------------------------------
class TestHierarchy:
    def test_default_order_is_most_senior_first(self):
        people = [
            make_employee("c", "Floor Assistant"),
            make_employee("a", "Assistant Manager"),
            make_employee("b", "Supervisor"),
        ]
        assert [e["employee_id"] for e in hierarchy.sort_employees(people)] == ["a", "b", "c"]

    def test_shop_can_configure_its_own_ladder(self):
        """A business must be able to reorder its job titles without a code
        change — that is the whole point of it being configurable."""
        shop = {"role_hierarchy": ["Barista", "Baker", "Manager"]}
        people = [
            make_employee("m", "Manager"),
            make_employee("b", "Barista"),
        ]
        assert [e["employee_id"] for e in hierarchy.sort_employees(people, shop)] == ["b", "m"]

    def test_unknown_role_sorts_last_rather_than_failing(self):
        people = [make_employee("x", "Sommelier"), make_employee("m", "Manager")]
        assert [e["employee_id"] for e in hierarchy.sort_employees(people)] == ["m", "x"]

    def test_titles_match_loosely(self):
        """Imported data says 'Duty Mgr.' where the ladder says 'Duty
        Manager'; without loose matching every such person sorts last."""
        ranks = hierarchy.rank_map()
        assert hierarchy.rank_of("Duty Mgr.", ranks) == hierarchy.rank_of("Duty Manager", ranks)
        assert hierarchy.rank_of("duty manager", ranks) != hierarchy.UNRANKED

    def test_same_role_breaks_ties_by_name(self):
        people = [
            make_employee("z", "Supervisor", name="Zoe"),
            make_employee("a", "Supervisor", name="Adam"),
        ]
        assert [e["name"] for e in hierarchy.sort_employees(people)] == ["Adam", "Zoe"]

    def test_generated_roster_is_ordered_by_hierarchy(self):
        employees = [
            make_employee("floor", "Floor Assistant"),
            make_employee("mgr", "Assistant Manager"),
            make_employee("sup", "Supervisor"),
        ]
        result = solve_roster(make_shop("09:00", "17:00"), employees, [], [], [], WEEK)
        first_appearance = []
        for shift in result["shifts"]:
            if shift["employee_id"] not in first_appearance:
                first_appearance.append(shift["employee_id"])
        assert first_appearance[0] == "mgr"


# ---------------------------------------------------------------------------
# 2. Every active employee accounted for
# ---------------------------------------------------------------------------
class TestEveryEmployeeConsidered:
    def test_unrostered_staff_are_listed_with_a_reason(self):
        employees = [make_employee(f"e{i}") for i in range(6)]
        result = solve_roster(make_shop("09:00", "13:00"), employees, [], [], [], WEEK)

        rostered = {s["employee_id"] for s in result["shifts"]}
        idle = [e["employee_id"] for e in employees if e["employee_id"] not in rostered]
        reported = {u["employee_id"] for u in result["unrostered"]}
        assert set(idle) == reported, "everyone without shifts must be accounted for"
        assert all(u["reason"] for u in result["unrostered"])

    def test_new_employee_with_no_history_is_still_considered(self):
        """The case that matters most: a new starter has no shift history, and
        must not be skipped for lack of it."""
        newcomer = make_employee("newbie")
        history = [{
            "week_start": "2026-08-03", "approved": True,
            "shifts": [{"employee_id": "veteran", "day": "mon",
                        "start": "09:00", "end": "17:00"}],
        }]
        result = solve_roster(
            make_shop("09:00", "17:00"), [newcomer], [], [], [], WEEK,
            history_rosters=history,
        )
        assert [s for s in result["shifts"] if s["employee_id"] == "newbie"]

    def test_inactive_employee_is_excluded_and_not_reported_as_missing(self):
        employees = [
            make_employee("active"),
            make_employee("leaver", is_active=False),
        ]
        result = solve_roster(make_shop("09:00", "17:00"), employees, [], [], [], WEEK)
        assert not [s for s in result["shifts"] if s["employee_id"] == "leaver"]
        # They left; they are not an unfilled slot needing explanation.
        assert "leaver" not in {u["employee_id"] for u in result["unrostered"]}


# ---------------------------------------------------------------------------
# 3. Unfamiliar shifts warn rather than pass silently
# ---------------------------------------------------------------------------
class TestUnfamiliarShifts:
    def _history(self, employee_id, patterns):
        return [{
            "week_start": "2026-08-03", "approved": True,
            "shifts": [
                {"employee_id": employee_id, "day": "mon", "start": s, "end": e}
                for s, e in patterns
            ],
        }]

    def test_warns_on_a_start_time_never_worked(self):
        """The Andi case: never worked 06:00, rostered 06:00 on a Saturday."""
        history = self._history("andi", [("23:30", "07:00")] * 10)
        employee = make_employee("andi", name="Andi")
        verdict = avail.check_familiarity(
            employee, "06:00", "16:00", avail.build_shift_history(history)
        )
        assert verdict.allowed, "a warning, not a block"
        assert "no previous 06:00 start" in verdict.warning
        assert "confirm" in verdict.warning.lower()

    def test_no_warning_for_a_pattern_they_regularly_work(self):
        history = self._history("andi", [("23:30", "07:00")] * 10)
        verdict = avail.check_familiarity(
            make_employee("andi"), "23:30", "07:00", avail.build_shift_history(history)
        )
        assert verdict.warning is None

    def test_small_differences_are_not_flagged(self):
        """07:00 versus 07:30 is the same shift to a human."""
        history = self._history("aj", [("07:30", "16:00")] * 10)
        verdict = avail.check_familiarity(
            make_employee("aj"), "07:00", "15:00", avail.build_shift_history(history)
        )
        assert verdict.warning is None

    def test_no_history_means_no_warning(self):
        """Everything is unfamiliar to a new starter; warning on all of it
        would be noise, and blocking would make them unrosterable."""
        verdict = avail.check_familiarity(make_employee("new"), "06:00", "16:00", {})
        assert verdict.allowed and verdict.warning is None

    def test_the_solver_refuses_rather_than_warning(self):
        """An unfamiliar shift is not offered at all, even when that is the
        only way to fill the hour.

        The real roster showed why: night staff were being handed 06:00
        starts to keep Sunday covered, while the manager's own sheet gives
        every 06:00 to somebody who works 06:00. An uncovered hour the
        manager can see and fix beats a shift that will not happen.
        """
        history = [{
            "week_start": "2026-08-03", "approved": True,
            "shifts": [{"employee_id": "andi", "day": "mon",
                        "start": "18:00", "end": "23:00"} for _ in range(10)],
        }]
        result = solve_roster(
            make_shop("06:00", "16:00"), [make_employee("andi", name="Andi")],
            [], [], [], WEEK, history_rosters=history,
        )
        assert result["confirmations"] == [], "no unfamiliar shift should exist"
        assert result["shifts"] == [], "Andi works evenings, not 06:00-16:00"
        assert result["critical_issues"], "the uncovered hours must be reported"

    def test_somebody_who_works_the_shift_is_still_rostered(self):
        """The block must not be so broad that nobody can be scheduled."""
        history = [{
            "week_start": "2026-08-03", "approved": True,
            "shifts": [{"employee_id": "dawn", "day": "mon",
                        "start": "06:00", "end": "16:00"} for _ in range(10)],
        }]
        result = solve_roster(
            make_shop("06:00", "16:00"), [make_employee("dawn", name="Dawn")],
            [], [], [], WEEK, history_rosters=history,
        )
        assert result["shifts"], "a 06:00 worker should get the 06:00 shift"
        assert result["confirmations"] == []


class TestNightStaffStayOnNights:
    """Taken from the real approved roster for Top Oil South Link.

    The manager gives every 06:00 start to Jane, Kyle, Megan, John, Emma or
    Steve. The night team — Andi, Kelvin, Azaryia — never start before 17:00,
    on any day, including the Sunday the solver kept getting wrong.
    """

    MORNING = [("jane", "06:00", "14:00"), ("kyle", "06:00", "16:00")]
    NIGHT = [("kelvin", "23:30", "07:00"), ("azaryia", "18:00", "00:00")]

    def _generate(self):
        from app.services.demand import build_profile

        shop = {
            "shop_id": "s", "min_shift_hours": 4, "max_shift_hours": 10,
            "hours": [
                {"day": d, "open": "00:00", "close": "23:59", "closed": False}
                for d in DAYS
            ],
            "strict_days_off": False,
        }
        people = [
            make_employee(
                eid,
                role="Night Shift" if eid in ("kelvin", "azaryia") else "Floor Assistant",
                max_weekly_hours=30,
            )
            for eid, _, _ in self.MORNING + self.NIGHT
        ]
        history = [{
            # Seven days apart, and computed rather than spelled out: the
            # hand-written version rolled the month every four weeks and was
            # one day short each time it did.
            "week_start": (
                _date(2026, 5, 4) + _td(weeks=w)
            ).isoformat(),
            "approved": True,
            "shifts": [
                {"employee_id": eid, "day": d, "start": s, "end": e}
                for d in DAYS for eid, s, e in self.MORNING + self.NIGHT
            ],
        } for w in range(8)]

        demand = build_profile(
            shop, history, {p["employee_id"]: p["role"] for p in people}
        )
        return solve_roster(
            shop, people, [], [], [], WEEK, None, demand, history_rosters=history,
        )

    def test_a_night_worker_never_gets_a_morning_start(self):
        result = self._generate()
        offenders = [
            s for s in result["shifts"]
            if s["employee_id"] in ("kelvin", "azaryia")
            and "07:30" < s["start"] < "17:00"
        ]
        assert offenders == [], f"night staff put on days: {offenders[:2]}"

    def test_the_roster_carries_no_unfamiliar_shifts_at_all(self):
        """Not a warning to confirm — they simply are not created."""
        assert self._generate()["confirmations"] == []

    def test_morning_staff_still_get_their_morning_shifts(self):
        result = self._generate()
        mornings = [s for s in result["shifts"] if s["employee_id"] in ("jane", "kyle")]
        assert mornings, "the 06:00 workers should still be rostered"
        assert all(s["start"] in ("06:00", "23:30") or s["start"] < "12:00"
                   for s in mornings)


class TestFamiliarityInfluencesTheChoice:
    """Familiarity used to be checked only AFTER somebody was picked, so it
    could not prevent anything. Two equally-ranked candidates tied exactly,
    and the tie was broken by list order — which is how a night worker ends
    up opening the shop at 06:00."""

    def _builder(self, employees):
        history = [{
            "week_start": "2026-06-15", "approved": True,
            "shifts":
                [{"employee_id": "morning", "day": d, "start": "06:00", "end": "14:00"}
                 for d in DAYS] * 5 +
                [{"employee_id": "night", "day": d, "start": "22:00", "end": "06:00"}
                 for d in DAYS] * 5,
        }]
        return _RosterBuilder(
            make_shop("06:00", "22:00"), employees, [], [], [], WEEK, {}, None, history,
        )

    def test_the_familiar_candidate_wins_an_otherwise_equal_tie(self):
        morning = make_employee("morning")
        night = make_employee("night")
        builder = self._builder([morning, night])

        hours = list(range(6, 14))
        morning_key = builder._rank_for_demand(morning, "06:00-14:00", "mon", hours)
        night_key = builder._rank_for_demand(night, "06:00-14:00", "mon", hours)

        assert morning_key < night_key, "the 06:00 shift should go to the 06:00 worker"
        # Everything except the familiarity term is identical — that is what
        # made the old ordering arbitrary.
        assert morning_key[0] == night_key[0]
        assert morning_key[2:] == night_key[2:]

    def test_a_new_starter_is_not_penalised(self):
        """No history is not evidence of unsuitability. Scoring it as
        unfamiliar would put a new employee last in every queue."""
        newcomer = make_employee("newcomer")
        builder = self._builder([make_employee("morning"), newcomer])
        assert builder._unfamiliarity(newcomer, "06:00-14:00") == 0

    def test_coverage_still_outranks_comfort(self):
        """Familiarity breaks ties; it must not overrule getting the right
        role onto an hour that needs it."""
        builder = self._builder([make_employee("morning"), make_employee("night")])
        familiar = builder._rank_for_demand(
            make_employee("morning"), "06:00-14:00", "mon", list(range(6, 14)),
        )
        assert familiar[1] == 0
        # Role deficit occupies position 0, ahead of familiarity at 1.
        assert len(familiar) == 5


# ---------------------------------------------------------------------------
# 5. Advanced availability
# ---------------------------------------------------------------------------
class TestAdvancedAvailability:
    def test_cannot_start_before_their_earliest(self):
        """The student example: available from 10:00, so never 06:00-14:00."""
        employee = make_employee("student", availability={"earliest_start": "10:00"})
        verdict = avail.check_availability(employee, "mon", "06:00", "14:00")
        assert not verdict.allowed
        assert "cannot start before 10:00" in verdict.reason

    def test_can_work_within_their_window(self):
        employee = make_employee("student", availability={
            "earliest_start": "10:00", "latest_finish": "23:00",
        })
        assert avail.check_availability(employee, "mon", "10:00", "18:00").allowed
        assert avail.check_availability(employee, "mon", "15:00", "23:00").allowed

    def test_cannot_finish_after_their_latest(self):
        employee = make_employee("e", availability={"latest_finish": "21:00"})
        verdict = avail.check_availability(employee, "mon", "14:00", "23:00")
        assert not verdict.allowed
        assert "cannot work past 21:00" in verdict.reason

    def test_unavailable_days_are_refused(self):
        employee = make_employee("e", availability={"available_days": ["sat", "sun"]})
        assert not avail.check_availability(employee, "mon", "09:00", "17:00").allowed
        assert avail.check_availability(employee, "sat", "09:00", "17:00").allowed

    def test_overnight_can_be_ruled_out(self):
        employee = make_employee("e", availability={"can_work_overnight": False})
        assert not avail.check_availability(employee, "mon", "23:00", "07:00").allowed

    def test_preferred_band_warns_but_does_not_block(self):
        """A preference must never cost the shop its cover."""
        employee = make_employee("e", availability={"preferred_shift": "morning"})
        verdict = avail.check_availability(employee, "mon", "18:00", "23:00")
        assert verdict.allowed
        assert "prefers morning" in verdict.warning

    def test_the_solver_respects_the_window(self):
        """End to end: a 10:00-start employee is never given the 06:00 shift."""
        employees = [
            make_employee("student", availability={
                "earliest_start": "10:00", "latest_finish": "23:00",
            }),
            make_employee("anyone"),
        ]
        result = solve_roster(make_shop("06:00", "23:00"), employees, [], [], [], WEEK)
        for shift in result["shifts"]:
            if shift["employee_id"] == "student":
                assert shift["start"] >= "10:00", f"got {shift['start']}"
                assert shift["end"] <= "23:00" or shift["end"] == "00:00"


# ---------------------------------------------------------------------------
# 7 & 8. Students and summer break
# ---------------------------------------------------------------------------
class TestStudents:
    def _student(self, **overrides):
        return make_employee("stu", is_student=True, max_weekly_hours=40,
                             term_time_max_hours=16,
                             summer_break={
                                 "start_date": "2026-06-01",
                                 "end_date": "2026-08-31",
                                 "max_weekly_hours": 40,
                             }, **overrides)

    def test_term_time_cap_applies_outside_the_break(self):
        assert avail.weekly_hour_cap(self._student(), "2026-02-02") == 16

    def test_break_cap_applies_inside_it(self):
        assert avail.weekly_hour_cap(self._student(), SUMMER_WEEK) == 40

    def test_non_students_are_unaffected(self):
        employee = make_employee("e", max_weekly_hours=40, term_time_max_hours=16)
        assert avail.weekly_hour_cap(employee, "2026-02-02") == 40

    def test_student_without_a_break_configured_uses_their_term_cap(self):
        student = make_employee("s", is_student=True, max_weekly_hours=40,
                                term_time_max_hours=16)
        assert avail.weekly_hour_cap(student, SUMMER_WEEK) == 16

    def test_solver_honours_the_term_time_cap(self):
        result = solve_roster(
            make_shop("09:00", "21:00"), [self._student()], [], [], [], "2026-02-02"
        )
        assert result["per_employee_hours"].get("stu", 0) <= 16

    def test_solver_allows_more_during_the_break(self):
        """The point of the feature: extra cover when someone else is away."""
        term = solve_roster(
            make_shop("06:00", "23:00"), [self._student()], [], [], [], "2026-02-02"
        )["per_employee_hours"].get("stu", 0)
        summer = solve_roster(
            make_shop("06:00", "23:00"), [self._student()], [], [], [], SUMMER_WEEK
        )["per_employee_hours"].get("stu", 0)
        assert summer > term


# ---------------------------------------------------------------------------
# 4 & 6. Holiday balance
# ---------------------------------------------------------------------------
class TestHolidayBalance:
    def _rosters(self, employee_id, worked_hours=0.0, holiday_hours=0.0):
        shifts = []
        if worked_hours:
            shifts.append({"employee_id": employee_id, "day": "mon",
                           "start": "09:00", "end": "17:00",
                           "paid_hours": worked_hours})
        if holiday_hours:
            shifts.append({"employee_id": employee_id, "day": "tue",
                           "start": "", "end": "", "paid_holiday": True,
                           "paid_hours": holiday_hours})
        return [{"week_start": "2026-08-03", "approved": True, "shifts": shifts}]

    def test_opening_balance_carries_in(self):
        employee = make_employee("e", opening_holiday_hours=42.5)
        balance = holiday_balance.compute_balance(employee, [])
        assert balance["opening_hours"] == 42.5
        assert balance["available_hours"] == 42.5

    def test_hours_accrue_from_work(self):
        employee = make_employee("e")
        balance = holiday_balance.compute_balance(employee, self._rosters("e", worked_hours=100))
        assert balance["accrued_hours"] == pytest.approx(12.07, abs=0.01)

    def test_paid_holiday_draws_the_balance_down(self):
        employee = make_employee("e", opening_holiday_hours=20)
        balance = holiday_balance.compute_balance(
            employee, self._rosters("e", holiday_hours=8)
        )
        assert balance["used_hours"] == 8
        assert balance["available_hours"] == pytest.approx(12)

    def test_booked_paid_holiday_reserves_the_balance_before_approval(self):
        employee = make_employee("e", opening_holiday_hours=20,
                                 max_weekly_hours=40)
        booking = {
            "holiday_id": "h1", "scope": "employee", "employee_id": "e",
            "date": "2026-08-04", "hours_per_day": 8,
        }
        balance = holiday_balance.compute_balance(
            employee, [], holidays=[booking],
        )
        assert balance["used_hours"] == 0
        assert balance["booked_hours"] == 8
        assert balance["available_hours"] == pytest.approx(12)

    def test_approved_holiday_moves_from_booked_to_used_without_double_charge(self):
        employee = make_employee("e", opening_holiday_hours=20,
                                 max_weekly_hours=40)
        booking = {
            "holiday_id": "h1", "scope": "employee", "employee_id": "e",
            "date": "2026-08-05", "hours_per_day": 8,
        }
        approved = [{"week_start": "2026-08-03", "approved": True, "shifts": [{
            "employee_id": "e", "day": "wed", "start": "", "end": "",
            "paid_holiday": True, "paid_hours": 8,
        }]}]
        balance = holiday_balance.compute_balance(
            employee, approved, holidays=[booking],
        )
        assert balance["used_hours"] == 8
        assert balance["booked_hours"] == 0
        assert balance["available_hours"] == pytest.approx(12)

    def test_rebooking_can_release_the_entries_it_replaces(self):
        employee = make_employee("e", opening_holiday_hours=8,
                                 max_weekly_hours=40)
        booking = {
            "holiday_id": "h1", "scope": "employee", "employee_id": "e",
            "date": "2026-08-04", "hours_per_day": 8,
        }
        balance = holiday_balance.compute_balance(
            employee, [], holidays=[booking], excluded_holiday_ids={"h1"},
        )
        assert balance["booked_hours"] == 0
        assert balance["available_hours"] == 8

    def test_booking_within_the_balance_is_allowed(self):
        balance = holiday_balance.compute_balance(
            make_employee("e", opening_holiday_hours=10), []
        )
        assert holiday_balance.check_can_book(balance, 8)["allowed"]

    def test_booking_beyond_the_balance_is_refused(self):
        """The stated case: 10 hours available, days worth 4 hours each — the
        third day must not be markable."""
        balance = holiday_balance.compute_balance(
            make_employee("e", opening_holiday_hours=10), []
        )
        assert holiday_balance.max_payable_days(balance, 4) == 2
        verdict = holiday_balance.check_can_book(balance, 12)
        assert not verdict["allowed"]
        assert verdict["shortfall_hours"] == pytest.approx(2)

    def test_adjustments_move_the_balance_and_keep_their_reason(self):
        adjustment = holiday_balance.make_adjustment(5, "Goodwill after cover")
        employee = make_employee("e", opening_holiday_hours=10,
                                 holiday_adjustments=[adjustment])
        balance = holiday_balance.compute_balance(employee, [])
        assert balance["available_hours"] == pytest.approx(15)
        assert balance["adjustments"][0]["reason"] == "Goodwill after cover"
        assert balance["adjustments"][0]["created_at"]

    def test_sick_leave_neither_earns_nor_spends(self):
        rosters = [{"week_start": "2026-08-03", "approved": True, "shifts": [
            {"employee_id": "e", "day": "mon", "start": "09:00", "end": "17:00",
             "sick": True, "paid_hours": 8},
        ]}]
        balance = holiday_balance.compute_balance(make_employee("e"), rosters)
        assert balance["hours_worked"] == 0
        assert balance["used_hours"] == 0


# ---------------------------------------------------------------------------
# Job titles read from a file
# ---------------------------------------------------------------------------
class TestMatchRole:
    """Imported titles must resolve against the shop's ladder, not a fixed one.

    The import used to rewrite every kind of manager to "Manager" and both
    "Night Shift" and "Goods Inwards" to "Stocker", consulting nothing about
    the shop. A manager who had configured their real job titles during setup
    got them replaced by roles they had never chosen.
    """

    SHOP = {"role_hierarchy": [
        "Duty Manager", "Manager", "Supervisor", "Goods Inwards", "Night Shift",
    ]}

    def test_a_configured_role_keeps_the_shops_spelling(self):
        from app.services.hierarchy import match_role

        assert match_role("duty manager", self.SHOP) == "Duty Manager"
        assert match_role("DUTY MGR.", self.SHOP) == "Duty Manager"

    def test_distinct_titles_are_not_collapsed(self):
        """The bug in one assertion."""
        from app.services.hierarchy import match_role

        assert match_role("Duty Manager", self.SHOP) != "Manager"
        assert match_role("Night Shift", self.SHOP) != "Stocker"
        assert match_role("Goods Inwards", self.SHOP) == "Goods Inwards"

    def test_an_unknown_title_is_kept_verbatim(self):
        """Nothing is invented — the owner positions it later."""
        from app.services.hierarchy import match_role

        assert match_role("Bakery Lead", self.SHOP) == "Bakery Lead"

    def test_an_unknown_title_reaches_the_settings_ladder(self):
        from app.services.hierarchy import effective_hierarchy, match_role

        role = match_role("Bakery Lead", self.SHOP)
        assert role in effective_hierarchy(self.SHOP, [role])

    def test_nothing_at_all_resolves_to_nothing(self):
        from app.services.hierarchy import match_role

        assert match_role(None, self.SHOP) == ""
        assert match_role("   ", self.SHOP) == ""

    def test_a_shop_with_no_ladder_keeps_the_sheets_wording(self):
        from app.services.hierarchy import match_role

        assert match_role("Night Shift", {}) == "Night Shift"


class TestRoleAliases:
    """Abbreviations only this shop uses have to be told, not guessed.

    Loose matching forgives "Mgr" for "Manager", but it cannot know that
    "Ass Manager" is the sheet's "Assistant Manager" or that "Shop Floor" is
    this shop's "Floor Assistant". Without aliases those arrive as brand-new
    roles that sort BELOW every real rung — which would have ranked the most
    senior manager under the night staff.
    """

    SHOP = {
        "role_hierarchy": ["Ass Manager", "Duty Manager", "Floor Assistant"],
        "role_aliases": {
            "Assistant Manager": "Ass Manager",
            "Shop Floor": "Floor Assistant",
        },
    }

    def test_an_alias_resolves_to_the_shops_own_wording(self):
        from app.services.hierarchy import match_role

        assert match_role("Assistant Manager", self.SHOP) == "Ass Manager"
        assert match_role("Shop Floor", self.SHOP) == "Floor Assistant"

    def test_an_aliased_role_ranks_properly(self):
        """The failure this prevents, stated as seniority rather than spelling."""
        from app.services.hierarchy import match_role, rank_map, rank_of

        ranks = rank_map(self.SHOP)
        senior = rank_of(match_role("Assistant Manager", self.SHOP), ranks)
        junior = rank_of(match_role("Shop Floor", self.SHOP), ranks)
        assert senior < junior

    def test_without_the_alias_it_would_have_sorted_last(self):
        from app.services.hierarchy import UNRANKED, match_role, rank_map, rank_of

        bare = {"role_hierarchy": self.SHOP["role_hierarchy"]}
        ranks = rank_map(bare)
        assert rank_of(match_role("Assistant Manager", bare), ranks) == UNRANKED

    def test_aliases_are_matched_loosely_too(self):
        from app.services.hierarchy import match_role

        assert match_role("assistant mgr", self.SHOP) == "Ass Manager"

    def test_an_alias_pointing_at_a_deleted_role_is_ignored(self):
        """Renaming a rung must not leave an alias aimed at nothing."""
        from app.services.hierarchy import match_role

        shop = {
            "role_hierarchy": ["Manager"],
            "role_aliases": {"Shop Floor": "Floor Assistant"},
        }
        assert match_role("Shop Floor", shop) == "Shop Floor"

    def test_the_ladder_still_wins_over_an_alias(self):
        from app.services.hierarchy import match_role

        shop = {
            "role_hierarchy": ["Shop Floor", "Floor Assistant"],
            "role_aliases": {"Shop Floor": "Floor Assistant"},
        }
        assert match_role("Shop Floor", shop) == "Shop Floor"


class TestSummerBreakIsRecognised:
    """A student's cap lifts during their break — whichever field says so.

    `on_summer_break` used to read the legacy `is_student` flag while the
    Employees screen writes `employment_type`. So a student set up through
    the current interface kept their term-time cap all year, and nothing
    reported it: a cap that fails to lift produces a smaller roster, not an
    error.
    """

    BREAK = {"start_date": "2026-06-01", "end_date": "2026-09-15",
             "max_weekly_hours": 35}

    def _student(self, **extra):
        return {
            "employee_id": "conor", "name": "Conor", "max_weekly_hours": 20,
            "term_time_max_hours": 20, "summer_break": dict(self.BREAK), **extra,
        }

    def test_the_modern_field_lifts_the_cap(self):
        from app.services.availability import weekly_hour_cap

        student = self._student(employment_type="student")
        assert weekly_hour_cap(student, "2026-08-31") == 35

    def test_the_legacy_flag_still_works(self):
        """Records written before employment_type existed must not break."""
        from app.services.availability import weekly_hour_cap

        assert weekly_hour_cap(self._student(is_student=True), "2026-08-31") == 35

    def test_outside_the_break_the_term_cap_applies(self):
        from app.services.availability import weekly_hour_cap

        student = self._student(employment_type="student")
        assert weekly_hour_cap(student, "2026-10-05") == 20

    def test_an_hourly_employee_has_no_break(self):
        from app.services.availability import on_summer_break
        from datetime import date

        hourly = self._student(employment_type="hourly")
        assert on_summer_break(hourly, date(2026, 8, 31)) is False

    def test_a_legal_summer_week_is_not_a_breach(self):
        """The case that started this: 30.5h against a 20h term-time cap
        looked like 152%, when the real ceiling that week was 35."""
        from app.services.availability import weekly_hour_cap

        cap = weekly_hour_cap(self._student(employment_type="student"), "2026-08-31")
        assert 30.5 <= cap
