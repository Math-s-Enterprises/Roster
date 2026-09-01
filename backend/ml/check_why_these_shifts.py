"""Did people get their shifts because they OWN them, or by tie-break?

    python ml/check_why_these_shifts.py --email you@example.com --week 2026-09-14

WHY THIS MATTERS BEFORE CHANGING HOW HOURS ARE SHARED OUT
----------------------------------------------------------
Hourly staff came out badly uneven on the reference shop — most well under
the hours they normally work, one nearly ten hours over. That has two causes
and only one of them is a fault:

  * OWNERSHIP (§2b) — somebody who has worked a slot 60% of the weeks it ran
    gets it. If the person who is "over" simply owns a lot of slots, the
    roster is correct and evening their hours out would take settled shifts
    off the people who always work them. That is the edit burden the
    ownership rules exist to prevent.

  * TIE-BREAK — `_contract_need` returns 0.0 for every hourly employee
    (`scheduler.py:1523`, and its own docstring says so), so among people
    with no claim they are perfectly tied and the tie falls to coverage
    preference and role. Somebody already on 25h ranks the same as somebody
    on 5h. Nothing knows they have had enough.

The first must be left alone. The second is the thing to fix. Telling them
apart is the whole point of this script — because a fix aimed at the first
would reproduce a bug this codebase has already had once, documented at
`scheduler.py:1738`, where contract need outranked owners and four settled
shifts changed hands in a single day.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import availability as avail              # noqa: E402
from app.services import slot_owners                        # noqa: E402
from app.services.demand import (                           # noqa: E402
    _week_start_date, build_profile,
)
from app.services.hierarchy import sort_employees           # noqa: E402
from app.services.learning import compute_weights           # noqa: E402
from app.services.scheduler import paid_hours, solve_roster  # noqa: E402

ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


async def run(email: str, week: str) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")
    shop_id = shop["shop_id"]

    employees = await db.employees.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    names = {e["employee_id"]: e.get("name") or e["employee_id"] for e in employees}
    holidays = await db.holidays.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    fixed = await db.fixed_shifts.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    rules = await db.ai_rules.find(
        {"shop_id": shop_id, "enabled": True}, {"_id": 0}).to_list(200)
    approved = await db.rosters.find(
        {"shop_id": shop_id, "approved": True}, {"_id": 0}).to_list(500)
    approved = [r for r in approved if r.get("week_start") != week]

    breaks_paid = bool(shop.get("breaks_are_paid"))
    profile = build_profile(
        shop, approved,
        {e["employee_id"]: e.get("role", "") for e in employees},
        for_week=week,
    )
    ordered = sort_employees(employees, shop)
    roster = solve_roster(
        shop, ordered, holidays, fixed, rules, week,
        compute_weights(approved), profile, history_rosters=approved,
    )

    # Built exactly as the solver builds it, leavers dropped, so the answer
    # is about the same ownership map the solve actually used.
    owners = slot_owners.build_owners(
        approved, {e["employee_id"] for e in employees if avail.is_active(e)})

    def regulars_of(day: str, start: str, end: str) -> set:
        """EVERYBODY with a settled claim on this shape, not just the top one.

        `owner_of` returns a single person, which is right for "who takes
        this instance" and wrong for "whose shift is this". A shape that runs
        TWICE has two regulars, and SlotHistory says so in its own docstring:
        "Tuesday runs 06:00-16:00 twice; over 23 weeks Megan has 21 and John
        17, so both clear the bar and own one instance each."

        Using `owner_of` here reported the second regular as having stolen
        the first one's shift — eight times on the reference shop, including
        Megan and John apparently taking each other's identical 06:00-16:00.
        The solver was never confused: once Megan is assigned that day she
        leaves the eligible set, so the second instance falls to
        `preference_order` and John's record wins it at rank 1.

        This was a fault in the measurement, and the kind §9b warns about —
        a script that had only ever met slots running once a day.
        """
        history = owners.get((day, start, end))
        if not history or history.weeks < slot_owners.MIN_OCCURRENCES:
            return set()
        return {
            employee_id for employee_id, count in history.people
            if count / history.weeks >= slot_owners.OWNERSHIP_SHARE
        }

    owned_hours: Dict[str, float] = defaultdict(float)
    tiebreak_hours: Dict[str, float] = defaultdict(float)
    owned_count: Dict[str, int] = defaultdict(int)
    tiebreak_count: Dict[str, int] = defaultdict(int)
    took_from: Dict[str, list] = defaultdict(list)
    displaced: list = []

    for shift in roster.get("shifts") or []:
        if shift.get("paid_holiday") or shift.get("unpaid_holiday"):
            continue
        employee_id = shift["employee_id"]
        hours = paid_hours(shift["start"], shift["end"],
                           breaks_paid=breaks_paid)
        regulars = regulars_of(shift["day"], shift["start"], shift["end"])
        if employee_id in regulars:
            owned_hours[employee_id] += hours
            owned_count[employee_id] += 1
        else:
            tiebreak_hours[employee_id] += hours
            tiebreak_count[employee_id] += 1
            # Only a displacement if a regular did not get one of the
            # instances — a shape running twice has room for two of them.
            got_it = {
                s["employee_id"] for s in roster.get("shifts") or []
                if (s["day"], s["start"], s["end"])
                == (shift["day"], shift["start"], shift["end"])
            }
            for regular in regulars - got_it:
                took_from[employee_id].append(
                    f"{shift['day']} {shift['start']}")
                displaced.append(
                    (regular, shift["day"], shift["start"], employee_id))

    salaried = {e["employee_id"] for e in employees
                if avail.is_full_time_contract(e)}

    print(f"\n{shop.get('name', '?')} — week of {week}")
    print("=" * 78)
    print("  Hours somebody OWNS are theirs by §2b and must not be evened")
    print("  out. Hours won on a TIE-BREAK are where nothing knows whether")
    print("  they have had enough already.\n")
    print(f"  {'who':20}{'paid':>7}{'owned':>8}{'tie-break':>11}   note")
    print("  " + "-" * 74)

    everyone = sorted(
        set(owned_hours) | set(tiebreak_hours),
        key=lambda e: -(owned_hours[e] + tiebreak_hours[e]),
    )
    for employee_id in everyone:
        owned = owned_hours[employee_id]
        tie = tiebreak_hours[employee_id]
        note = "salaried" if employee_id in salaried else ""
        if employee_id not in salaried and tie > owned:
            note = "mostly tie-break"
        print(f"  {names.get(employee_id, employee_id)[:19]:20}"
              f"{owned + tie:7.1f}{owned:8.1f}"
              f"{tie:11.1f}   {note}")

    print(f"\n{'=' * 78}\nWHAT THIS MEANS FOR THE FIX\n{'=' * 78}")
    hourly = [e for e in everyone if e not in salaried]
    tie_total = sum(tiebreak_hours[e] for e in hourly)
    owned_total = sum(owned_hours[e] for e in hourly)
    print(f"  hourly hours settled by ownership: {owned_total:7.1f}h")
    print(f"  hourly hours settled by tie-break: {tie_total:7.1f}h")
    if owned_total + tie_total:
        share = tie_total / (owned_total + tie_total) * 100
        print(f"  tie-break decides {share:.0f}% of hourly hours")
    print()
    if tie_total > owned_total:
        print("  The tie-break decides most hourly hours, so teaching it")
        print("  about hours worked will change the roster materially —")
        print("  and it can do so WITHOUT touching an owned shift.")
    else:
        print("  Ownership already decides most hourly hours. An hours rule")
        print("  would have little left to influence, and forcing it to")
        print("  would mean overriding ownership — which is the bug at")
        print("  scheduler.py:1738, not a fix.")

    # An owner CAN lawfully lose a slot — §2b lists exactly when: leave, the
    # curfew, their cap, the 11-hour rest gap, or a fifth day. Senior cover
    # (Pass 0b) may also displace them, deliberately, because a shop cannot
    # open without somebody senior.
    #
    # So a non-empty list is not itself a bug. What matters is whether the
    # owner had a REASON. An owner who was free and still lost their slot is
    # the bug at scheduler.py:1738 wearing a different hat.
    if not displaced:
        print("\n  No owner lost a slot. Ownership is being respected.")
        return

    print(f"\n{'=' * 78}\nOWNERS WHO LOST THEIR SLOT — WITH OR WITHOUT A REASON"
          f"\n{'=' * 78}")
    monday = _week_start_date(week)
    off_dates: Dict[str, set] = defaultdict(set)
    for holiday in holidays:
        if holiday.get("scope") not in ("employee", "unavailable", "sick"):
            continue
        start = holiday.get("date")
        if holiday.get("employee_id") and start:
            end = holiday.get("end_date") or start
            for offset in range(7):
                date_iso = (monday + timedelta(days=offset)).isoformat()
                if start <= date_iso <= end:
                    off_dates[holiday["employee_id"]].add(ORDER[offset])

    worked_days: Dict[str, set] = defaultdict(set)
    hours_by_person: Dict[str, float] = defaultdict(float)
    for shift in roster.get("shifts") or []:
        worked_days[shift["employee_id"]].add(shift["day"])
        if not (shift.get("paid_holiday") or shift.get("unpaid_holiday")):
            hours_by_person[shift["employee_id"]] += paid_hours(
                shift["start"], shift["end"], breaks_paid=breaks_paid)

    by_id = {e["employee_id"]: e for e in employees}
    unexplained = 0
    for owner_id, day, start, taker_id in sorted(set(displaced)):
        owner = by_id.get(owner_id, {})
        cap = avail.weekly_hour_cap(owner, week)
        used = hours_by_person.get(owner_id, 0.0)
        if day in off_dates.get(owner_id, set()):
            reason = "on leave that day"
        elif day in worked_days.get(owner_id, set()):
            reason = "already working that day"
        elif len(worked_days.get(owner_id, set())) >= 5:
            reason = "already on 5 days"
        elif used + 4 > cap:
            reason = f"near their cap ({used:.1f}/{cap:g}h)"
        elif avail.is_full_time_contract(by_id.get(taker_id, {})):
            reason = "taken by senior cover (Pass 0b) — by design"
        else:
            reason = "*** NO REASON — owner appears free ***"
            unexplained += 1
        print(f"    {names.get(owner_id, owner_id)[:16]:18}lost {day} {start} "
              f"to {names.get(taker_id, taker_id)[:14]:16}{reason}")

    print()
    if unexplained:
        print(f"  {unexplained} slot(s) left their owner for NO STATED REASON.")
        print("  Fix that before adding anything else to the ranking — an")
        print("  hours term sitting next to a leaky ownership check would")
        print("  make the leak worse and be blamed for it.")
    else:
        print("  Every displacement has a lawful reason. Ownership is sound,")
        print("  so an hours term can be added safely below it.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--week", required=True, help="Monday, YYYY-MM-DD")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.week))


if __name__ == "__main__":
    main()
