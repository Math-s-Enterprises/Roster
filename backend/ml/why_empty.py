"""Why nobody could be put on a day, in the solver's own words.

    python ml/why_empty.py --email you@example.com --week 2026-09-07 --day fri

WHY THIS EXISTS
---------------
`why_slot.py` answers a different question — who OWNED a slot and what beat
them — and on a day where a slot went unfilled it prints an empty table,
which reads as "no answer" rather than "wrong question". That happened, and
it cost a round trip.

The solver already knows. `_is_eligible` checks each rule in order and calls
`_note_exclusion` with a sentence whenever somebody is turned away. Those
sentences are collected per PERSON for the unrostered list, so by the end of
the week they say whatever the LAST rejection was — not the one that mattered
on Friday. This keeps every rejection tagged with the day it happened on.

THE SPY ALONE IS NOT ENOUGH, AND THAT WAS MEASURED
--------------------------------------------------
Two gaps, both found by checking the instrumentation could return a non-zero
answer before trusting a zero:

  * `_is_eligible` returns False with NO note for "already on a shift today"
    and "their preferred day off" — so those are re-derived from its own
    arguments when a silent False comes back.
  * Somebody on approved leave never reaches `_is_eligible` at all. The
    candidate lists filter on `employee_off_dates` first, so a spy on the
    eligibility check reports nothing whatsoever about the person who is on
    holiday — which is the likeliest reason a day is short in the first
    place.

So the report is built from the roster outwards: every active person who was
not placed is accounted for, with the solver's own sentence where there is
one and a derived reason where there is not. Nobody is left off.

THE QUESTION IT SETTLES
-----------------------
When a slot cannot be filled there are two very different causes, needing
opposite fixes:

  * somebody COULD work it but the week had already spent their hours by the
    time the solver arrived — the fill is forward-only and never revisits an
    earlier day, so a swap-to-unlock pass would fix it
  * somebody is blocked for a reason freeing hours would not change —
    familiarity, leave, a curfew, a custom rule — and no reshuffling helps

Answer the first before building anything.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import availability as avail              # noqa: E402
from app.services import scheduler as sched                 # noqa: E402
from app.services.demand import build_profile               # noqa: E402
from app.services.hierarchy import sort_employees           # noqa: E402
from app.services.learning import compute_weights           # noqa: E402

ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Which rejections a reshuffle could do something about. Matched on the
# distinctive fragment of each message in `_is_eligible`, not on loose
# keywords — "hours" appears in half of them and means nothing on its own.
FREEABLE = (
    "would exceed their",             # contracted band or weekly cap
    "rest since their last shift",    # 11-hour gap, caused by what came before
    "already working",                # five-day limit
)


async def run(email: str, week: str, day: str) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")
    shop_id = shop["shop_id"]

    employees = await db.employees.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    ids = {e["employee_id"] for e in employees}
    names = {e["employee_id"]: e.get("name") or e["employee_id"] for e in employees}
    holidays = await db.holidays.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    fixed = [f for f in await db.fixed_shifts.find(
        {"shop_id": shop_id}, {"_id": 0}).to_list(1000)
        if f["employee_id"] in ids]
    rules = await db.ai_rules.find(
        {"shop_id": shop_id, "enabled": True}, {"_id": 0}).to_list(200)
    approved = await db.rosters.find(
        {"shop_id": shop_id, "approved": True}, {"_id": 0}).to_list(500)

    profile = build_profile(
        shop, approved,
        {e["employee_id"]: e.get("role", "") for e in employees},
        for_week=week,
    )

    # (day, employee_id, reason), in the order the solver decided them.
    log: List[Tuple[str, str, str]] = []
    depth = {"day": "?", "notes": 0}

    original_note = sched._RosterBuilder._note_exclusion
    original_eligible = sched._RosterBuilder._is_eligible

    def note_spy(self, employee_id, reason):
        log.append((depth["day"], employee_id, reason))
        depth["notes"] += 1
        return original_note(self, employee_id, reason)

    def eligible_spy(self, employee, segment, day, date_iso, assigned_today,
                     open_m, close_m, *, relax_preferences):
        depth["day"] = day
        before = depth["notes"]
        ok = original_eligible(
            self, employee, segment, day, date_iso, assigned_today,
            open_m, close_m, relax_preferences=relax_preferences,
        )
        if not ok and depth["notes"] == before:
            # A silent False. Re-derived in the same order the real checks
            # run in, so the reason reported is the one that actually bit.
            eid = employee["employee_id"]
            if eid in assigned_today:
                reason = "Already on a shift that day."
            elif date_iso in self.employee_off_dates.get(eid, set()):
                reason = "On approved leave."
            elif day in (employee.get("preferred_days_off") or []):
                reason = "Their preferred day off."
            else:
                reason = "Rejected without a stated reason."
            log.append((day, eid, reason))
        return ok

    sched._RosterBuilder._note_exclusion = note_spy
    sched._RosterBuilder._is_eligible = eligible_spy
    try:
        roster = sched.solve_roster(
            shop, sort_employees(employees, shop), holidays, fixed, rules,
            week, compute_weights(approved), profile,
            history_rosters=approved, seed=1234,
        )
    finally:
        sched._RosterBuilder._note_exclusion = original_note
        sched._RosterBuilder._is_eligible = original_eligible

    shifts = [s for s in roster.get("shifts") or []
              if not (s.get("paid_holiday") or s.get("unpaid_holiday"))]
    date_iso = _date_for(week, day)

    print(f"\n{shop.get('name', '?')} — week of {week}, "
          f"{day.upper()} {date_iso}")
    print(f"{len(employees)} employees · demand profile: {profile.source}")

    placed = [s for s in shifts if s.get("day") == day]
    print(f"\n{len(placed)} shifts were placed on {day}:")
    for s in sorted(placed, key=lambda s: s.get("start", "")):
        print(f"    {s.get('start')}-{s.get('end')}  "
              f"{names.get(s.get('employee_id'), '?')}")

    # The shape of the whole week. A day that is short is usually short
    # because of how the six days before it were spent, and that is not
    # visible from the day on its own.
    print(f"\n{'=' * 72}\nTHE WEEK AS SOLVED\n{'=' * 72}")
    print(f"  {'':22}" + "".join(f"{d:>11}" for d in ORDER))
    for e in sorted(employees, key=lambda e: (e.get("name") or "").lower()):
        row = []
        for d in ORDER:
            todays = [s for s in shifts
                      if s["employee_id"] == e["employee_id"] and s["day"] == d]
            row.append(todays[0]["start"] if todays else "·")
        if any(c != "·" for c in row):
            print(f"  {(e.get('name') or '')[:20]:22}"
                  + "".join(f"{c:>11}" for c in row))

    # What the demand profile even ASKED for on this day. A day with no
    # slots is never filled at all — the coverage check notices the gap
    # afterwards, so it presents identically to a day nobody could work.
    # Two opposite causes, and this is what tells them apart.
    asked = profile.day_slots.get(day) or []
    print(f"\n{'=' * 72}\nWHAT THE PROFILE ASKED FOR ON {day.upper()}"
          f"\n{'=' * 72}")
    if asked:
        for slot in asked:
            print(f"    {slot[0]}-{slot[1]}")
    else:
        print("    NOTHING. The learned profile has no slots for this day,")
        print("    so no pass ever tried to fill it. The gap is reported")
        print("    afterwards by the coverage check, which is why it looks")
        print("    like nobody could work — the question was never asked.")
    for other in ORDER:
        if other != day:
            print(f"    ({other}: {len(profile.day_slots.get(other) or [])} slots)")

    # EVERY distinct reason, not just the first. The passes run twice — once
    # strict, once with preferences relaxed — so the first rejection is
    # routinely a preferred day off that the second pass then forgave. Keeping
    # only the first reported exactly that and hid the one that bit.
    spoken: Dict[str, List[str]] = defaultdict(list)
    for logged_day, employee_id, reason in log:
        if logged_day == day and reason not in spoken[employee_id]:
            spoken[employee_id].append(reason)

    # What the week had already spent on each person before this day.
    hours: Dict[str, float] = defaultdict(float)
    days_worked: Dict[str, set] = defaultdict(set)
    for s in shifts:
        hours[s["employee_id"]] += sched.shift_duration_minutes(
            s["start"], s["end"]) / 60
        days_worked[s["employee_id"]].add(s["day"])

    on_leave = {
        h.get("employee_id") for h in holidays
        if h.get("scope") in ("employee", "unavailable", "sick")
        and (h.get("date") or "") <= date_iso <= (h.get("end_date")
                                                  or h.get("date") or "")
    }
    max_days = int(shop.get("max_working_days") or sched.MAX_WORKING_DAYS)
    on_today = {s["employee_id"] for s in placed}

    print(f"\n{'=' * 72}\nWHY EVERYONE ELSE WAS NOT ON {day.upper()}"
          f"\n{'=' * 72}")
    freeable, blocked, freeable_ids = [], [], []
    for e in sorted(employees, key=lambda e: (e.get("name") or "").lower()):
        eid = e["employee_id"]
        if eid in on_today or e.get("status") in ("inactive", "archived"):
            continue
        cap = float(e.get("max_weekly_hours") or 0)
        used = hours.get(eid, 0.0)
        room = cap - used

        # Derived reasons first, in the order the solver applies them —
        # these are the ones it never gets far enough to say out loud.
        if eid in on_leave:
            reason, freeing_helps = "On approved leave.", False
        elif len(days_worked.get(eid, ())) >= max_days:
            reason = (f"Already on {len(days_worked[eid])} days — "
                      f"the limit is {max_days}.")
            freeing_helps = True
        elif spoken.get(eid):
            reason = " / ".join(spoken[eid])
            freeing_helps = any(f in reason.lower() for f in FREEABLE)
        elif room < 4:
            reason = f"Week already at {used:g}h of their {cap:g}h."
            freeing_helps = True
        else:
            reason = (f"Never considered — {room:g}h still spare. "
                      f"The day was judged covered.")
            freeing_helps = False

        print(f"  {(e.get('name') or eid)[:20]:22}{used:5.1f}/{cap:<5.0f}h  "
              f"{reason}")
        (freeable if freeing_helps else blocked).append(e.get("name") or eid)
        if freeing_helps:
            freeable_ids.append(eid)

    print(f"\n{'=' * 72}\nWOULD RESHUFFLING EARLIER DAYS HELP?\n{'=' * 72}")
    if freeable:
        print(f"  YES, for: {', '.join(freeable)}")
        print("    Nothing about them is unsuitable. The week had already")
        print("    spent them before it reached this day, and the fill is")
        print("    forward-only — moving one of their earlier shifts to a")
        print("    colleague would free them, which it cannot do.")
    else:
        print("  NO. Nobody was short of room.")
    if blocked:
        print(f"\n  Would change nothing for: {', '.join(blocked)}")
        print("    Leave, familiarity, a curfew or a rule is not capacity.")

    _where_could_it_land(
        freeable_ids, employees, names, shifts, approved, day, on_leave,
    )


def _where_could_it_land(freeable_ids, employees, names, shifts, approved,
                         day, on_leave) -> None:
    """Is there anywhere for a freed-up shift to GO?

    "Reshuffling would help" is only half an answer. Freeing Teja means
    handing one of his earlier shifts to somebody else, and if nobody else
    can take any of them, a swap pass would run every week and change
    nothing. That is the difference between a fix and wasted work, so it is
    measured rather than assumed.

    Only the state-INDEPENDENT blocks are checked — availability, familiarity
    and the curfew. Those cannot be argued with by rearranging the week. Hours
    and days can, and are exactly what the swap would be freeing, so counting
    them here would rule out the very thing being tested.
    """
    history = avail.build_shift_history(approved)
    print(f"\n{'=' * 72}\nWHERE COULD A FREED SHIFT GO?\n{'=' * 72}")
    if not freeable_ids:
        print("  Nothing to free.")
        return

    takers = [
        e for e in employees
        if e["employee_id"] not in freeable_ids
        and e["employee_id"] not in on_leave
        and e.get("status") not in ("inactive", "archived")
    ]
    landed = False
    for eid in freeable_ids:
        theirs = sorted(
            (s for s in shifts if s["employee_id"] == eid and s["day"] != day),
            key=lambda s: (ORDER.index(s["day"]), s["start"]),
        )
        print(f"\n  {names.get(eid, eid)}'s other shifts:")
        for s in theirs:
            options = []
            for e in takers:
                verdict = avail.check_availability(
                    e, s["day"], s["start"], s["end"])
                if not verdict.allowed:
                    continue
                if avail.check_familiarity(
                        e, s["start"], s["end"], history).warning:
                    continue
                if sched.violates_minor_curfew(e, s["start"], s["end"]):
                    continue
                options.append(e.get("name") or e["employee_id"])
            if options:
                landed = True
            print(f"    {s['day']} {s['start']}-{s['end']:9} "
                  + (f"could go to: {', '.join(options)}"
                     if options else "nobody else can take it"))

    print()
    if landed:
        print("  A swap has somewhere to land. Freeing the day is worth doing.")
    else:
        print("  Nowhere to land. A swap pass would run and change nothing —")
        print("  the shortage is people who can work these shapes, not the")
        print("  order the week was filled in.")


def _date_for(week_start: str, day: str) -> str:
    from datetime import datetime, timedelta
    monday = datetime.strptime(week_start, "%Y-%m-%d").date()
    return (monday + timedelta(days=ORDER.index(day))).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--week", required=True, help="Monday, YYYY-MM-DD")
    parser.add_argument("--day", required=True, help="mon..sun")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.week, args.day.lower()[:3]))


if __name__ == "__main__":
    main()
