"""An hour left one short says WHY, because the two causes need opposite fixes.

"wed: one short of the usual cover for 7 hour(s) (16:00-23:00)" is a
statement of fact that tells the manager nothing about what to do. There are
two quite different reasons an hour ends up like that:

  NOBODY COULD BE STRETCHED   somebody finishing nearby could have covered it
                              and none of them legally could — the 12-hour
                              cap, the rest gap, a curfew, a weekly limit.
                              A rota problem: move somebody's day.

  NO STRETCH WAS TRIED        the run is longer than a changeover, so the
                              pass deliberately left it alone rather than
                              smear a missing shift across three people's
                              finish times (§7d). Needs another person.

The manager asked both questions in the same breath — "why is the solver not
adding an extra person for the six and seven hour gaps, and on Thursday just
for one hour why can't it extend someone's shift" — which is exactly the
distinction the advisory was failing to draw.
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


def person(employee_id, **overrides):
    employee = {
        "employee_id": employee_id, "name": employee_id.title(),
        "role": "Floor Assistant", "age": 30, "hourly_rate": 15.0,
        "max_weekly_hours": 48, "preferred_days_off": [],
        "departments": ["Shop Floor"], "is_active": True,
    }
    employee.update(overrides)
    return employee


def weeks_of(per_week, count=24):
    return [
        {
            "week_start": (date(2026, 3, 2) + timedelta(weeks=w)).isoformat(),
            "approved": True,
            "shifts": per_week(w),
        }
        for w in range(count)
    ]


def short_lines(result):
    return [i for i in result["issues"] if "one short of the usual" in i]


class TestALongRunSaysItIsAMissingShift:
    """The 7-hour hole. No stretch is attempted, on purpose."""

    def _shop_with_an_evening_nobody_can_staff(self):
        """The shop normally runs two people all evening. Only one of the
        two is still employed, so the roster can only ever put one on — a
        run of short hours far longer than a changeover.
        """
        def week(w):
            shifts = []
            for day in DAYS:
                shifts += [
                    {"employee_id": "opener", "day": day,
                     "start": "06:00", "end": "16:00"},
                    {"employee_id": "eve_a", "day": day,
                     "start": "16:00", "end": "23:00"},
                    {"employee_id": "eve_b", "day": day,
                     "start": "16:00", "end": "23:00"},
                    {"employee_id": "night", "day": day,
                     "start": "23:00", "end": "06:00"},
                ]
            return shifts

        team = [
            person("opener"), person("eve_a"),
            # eve_b has left, so the evening can only ever be one deep.
            person("eve_b", is_active=False),
            person("night"),
        ]
        return weeks_of(week), team

    def test_the_advisory_says_it_is_a_missing_shift(self):
        history, team = self._shop_with_an_evening_nobody_can_staff()
        shop = make_shop()
        profile = build_profile(
            shop, history, {e["employee_id"]: e["role"] for e in team})
        result = solve_roster(
            shop, team, [], [], [], WEEK, None, profile,
            history_rosters=history)

        lines = short_lines(result)
        assert lines, (
            "this shop cannot staff its evening two-deep, so some hours must "
            f"be reported one short — got {result['issues']}"
        )
        assert any("missing shift" in line for line in lines), (
            "a run far longer than a changeover is a missing shift and the "
            "advisory should say so, rather than leaving the manager to "
            f"guess whether the solver even tried — got {lines}"
        )


# THE OTHER BRANCH — "nobody could be extended into it" — HAS NO TEST HERE,
# and that is a gap worth stating rather than papering over.
#
# It needs a short run of one or two hours that a neighbouring shift could
# reach and is refused on every candidate: the 12-hour cap, the rest gap, a
# curfew, a weekly limit. Several fixtures were tried and none produced one,
# because in a shop small enough to write as a fixture `required` drops at
# exactly the hour the constraint would bite — the same reason the presence
# cap has no unit test (see TestPresenceCapsArrivals).
#
# It is not hypothetical: the reference shop hits it every week. Thursday
# 18:00-19:00 came back one short with a stretch already spent on 20:00, and
# that is the case this branch exists to explain. Verified against a real
# generated roster rather than here.
#
# A first vacuous attempt lived here and was deleted: it asserted a line
# could not carry both reasons at once, which passed with the whole feature
# removed. An absent test is better than one that looks like coverage.
