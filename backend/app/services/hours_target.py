"""What each person is currently working, so hours can be shared out fairly.

WHY A WINDOW AND NOT AN AVERAGE OF EVERYTHING
---------------------------------------------
The first version of this decayed every week a person had ever worked, halving
every 8 weeks. It always lagged anybody who was CHANGING, which is exactly the
people a fair share-out is for:

    Jane, real weeks:   14 14  7  · 25 13 19 24 29 10 10  7 20 29 27 26 22 28
                        30 30 32 33 27 28 33 28 34 36.5 35 30.5
    decayed average:    28.5h        <- still carrying her January 7h weeks
    last 8 weeks:       31.5h
    last 4 weeks:       34.0h
    she was given:      13.0h

She has climbed steadily for months. A number that says 28.5 describes a person
she stopped being in the spring. Aneesh is the same in reverse — he dropped to
weekends, and the decayed figure kept insisting on his old full weeks.

So: the LAST N WEEKS THEY ACTUALLY APPEAR IN, and nothing older. The shop owner
chose 8, which is also RECENCY_HALF_LIFE_WEEKS in `demand.py` — one idea about
how fast a shop changes rather than two competing ones.

WHY THE MEDIAN
--------------
One odd week must not reset somebody's normal. Cover a colleague's holiday and
work 40 hours once, and a mean would quietly promote that to your new baseline
for the next two months. The median ignores it. It also ignores an unusually
quiet week in the other direction, which matters just as much — a light week
after somebody returns from leave is not them asking for fewer hours.

WHAT THIS NUMBER IS NOT
-----------------------
It is not a target on its own. Somebody who has dropped to weekends cannot be
given a full week however recently they worked one, so the caller bounds it —
see `scheduler._build_hours_aim`, which takes the smallest of this, what their
availability can physically hold, leave booked in the target week, and their
weekly cap. The window tracks a trend; availability catches a sharp change the
moment it is entered, without waiting for eight weeks of evidence.
"""
from __future__ import annotations

from statistics import median
from typing import Any, Dict, Sequence

from app.services.learning import latest_per_week

# How many recent weeks describe what somebody is working now. Chosen by the
# shop owner, and equal to demand.RECENCY_HALF_LIFE_WEEKS on purpose.
#
# Not calibrated — a judgement, like the half-life it matches (§7b). Shorter
# tracks a change faster and lets a single odd fortnight move somebody's
# baseline; longer is steadier and keeps describing who they used to be. If a
# shop complains that the roster is chasing an old pattern, this is the number
# to look at first, and it should probably become a per-shop setting rather
# than a different global default (§10b).
TREND_WEEKS = 8


def usual_hours(
    rosters: Sequence[Dict[str, Any]],
    week_start: str,
    *,
    breaks_paid: bool = False,
    window: int = TREND_WEEKS,
) -> Dict[str, float]:
    """employee_id -> the hours they have been working lately.

    Empty for anybody with no history at all, and the caller must read that as
    "no opinion" rather than zero: a new starter has never worked a week here,
    which is not the same as normally working none.
    """
    # Imported here rather than at module scope. `scheduler` imports this
    # module and `demand` imports `scheduler`, so a module-level import of
    # either would close the loop and fail on a partially initialised module.
    from app.services.demand import _week_start_date
    from app.services.scheduler import paid_hours

    target = _week_start_date(week_start)
    if target is None:
        return {}

    # Keyed by week so somebody absent has no entry rather than a zero — a
    # fortnight's leave is not evidence they want fewer hours. Deduplicated,
    # because a week with two approved rosters would otherwise count twice.
    per_week: Dict[str, Dict[str, float]] = {}
    for roster in latest_per_week(list(rosters)):
        if roster.get("exclude_from_ai"):
            continue
        week = roster.get("week_start")
        started = _week_start_date(week)
        if started is None or (target - started).days < 0:
            continue        # a future week is not evidence of anything yet
        for shift in roster.get("shifts") or []:
            if shift.get("paid_holiday") or shift.get("unpaid_holiday"):
                continue
            if not (shift.get("start") and shift.get("end")):
                continue
            employee_id = shift.get("employee_id")
            if not employee_id:
                continue
            weeks = per_week.setdefault(employee_id, {})
            weeks[week] = weeks.get(week, 0.0) + paid_hours(
                shift["start"], shift["end"], breaks_paid=breaks_paid)

    out: Dict[str, float] = {}
    for employee_id, weeks in per_week.items():
        # Newest first, then the most recent `window` they actually appear in.
        recent = [worked for _, worked in
                  sorted(weeks.items(), reverse=True)[:window]]
        if recent:
            out[employee_id] = float(median(recent))
    return out
