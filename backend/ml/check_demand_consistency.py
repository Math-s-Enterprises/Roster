"""Does the shop's learned SHIFT LIST cover its learned HEADCOUNT CURVE?

    python ml/check_demand_consistency.py --email you@example.com --week 2026-09-14

WHY
---
`demand.py` learns two things from the same approved rosters:

  * `day_slots(day)`  — the shift shapes this shop runs, e.g. 06:00-14:00
  * `required(day, hour)` — how many people it normally has on the floor

The solver places the SHAPES, then checks the result against the CURVE, and
stretches a neighbouring shift over any hour that comes up short. Because
both are learned from the same weeks, laying out every shape should reproduce
the curve almost exactly. Where it does not, the solver spends the rest of
the week patching a hole the model invented — and the manager reads an
advisory for each one:

    Conor's mon shift was changed from 06:00-14:00 to 06:00-15:00 to cover mon 14:00.
    Azaryia's mon shift was changed from 16:00-00:00 to 15:00-00:00 to cover mon 15:00.

Eighteen of those in one week is what prompted this. Conor finishes at 14:00,
Azaryia starts at 16:00, and the curve wants somebody at 14:00 and 15:00 —
so both shifts get stretched towards a gap that no learned shape fills.

WHAT A NON-ZERO ANSWER LOOKS LIKE, STATED BEFORE RUNNING
--------------------------------------------------------
`shortfall` is the curve minus the slots, per hour. If it is zero nearly
everywhere, the model is consistent and the stretches come from the SOLVER
failing to place the shapes (somebody unavailable, at a cap, on leave) —
a different problem, and the fix would be elsewhere.

If shortfall is systematically positive at the same hours every day, the
model is asking for more people than the shapes it knows can provide, and
no amount of solver work will stop the stretching. That is the bug.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services.demand import build_profile               # noqa: E402
from app.services.scheduler import DAYS, _RosterBuilder     # noqa: E402


async def run(email: str, week: str) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")
    shop_id = shop["shop_id"]

    employees = await db.employees.find(
        {"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    approved = await db.rosters.find(
        {"shop_id": shop_id, "approved": True}, {"_id": 0}).to_list(500)
    approved = [r for r in approved if r.get("week_start") != week]

    profile = build_profile(
        shop, approved,
        {e["employee_id"]: e.get("role", "") for e in employees},
        for_week=week,
    )

    print(f"\n{shop.get('name', '?')} — profile source: {profile.source}")
    print("Laying out every learned shape and comparing to the learned curve.")
    print("A positive shortfall is an hour the model wants staffed that none "
          "of\nits own shapes reach — every one of those becomes a stretch.\n")

    # COVERAGE IS ACCUMULATED ACROSS THE WHOLE WEEK BEFORE ANYTHING IS
    # JUDGED, because a night shift covers the NEXT day's small hours.
    #
    # The first version of this counted only `covered_day == day`, which
    # throws away exactly that wrap — and then reported 00:00-05:00 as
    # uncovered on all seven days at a 24-hour shop whose night shift runs
    # 23:30-07:00. Forty-two of the seventy-one "missing" hours were this
    # script, not the model. §7 and §8 both say it: overnight hours belong to
    # the day the shift STARTS, so no day can be judged until every day's
    # shapes are laid down.
    covered: Dict[str, list] = {d: [0] * 24 for d in DAYS}
    for day in DAYS:
        for start, end in (profile.slots_for(day) or []):
            for covered_day, hour in _RosterBuilder.hours_covered(
                day, start, end, wrap_week=True
            ):
                covered[covered_day][hour] += 1

    total_short = 0
    total_over = 0
    worst: Dict[str, int] = {}
    for day in DAYS:
        slots = profile.slots_for(day) or []
        if not slots:
            continue

        gaps = []
        for hour in range(24):
            required = profile.required(day, hour)
            if required <= 0 and covered[day][hour] == 0:
                continue
            short = required - covered[day][hour]
            if short > 0:
                gaps.append((hour, required, covered[day][hour]))
                total_short += short
            elif short < 0:
                total_over += -short

        print(f"  {day}  {len(slots)} shapes")
        if gaps:
            for hour, required, got in gaps:
                print(f"       {hour:02d}:00  curve wants {required}, "
                      f"shapes give {got}   SHORT {required - got}")
            worst[day] = len(gaps)
        else:
            print("       every hour the curve wants is covered by a shape")

    print(f"\n{'=' * 74}\nVERDICT\n{'=' * 74}")
    print(f"  hours where the shapes fall short of the curve: {total_short}")
    print(f"  hours where the shapes exceed the curve:        {total_over}")
    print()
    if total_short == 0:
        print("  CONSISTENT — the shapes cover the curve. Any stretching in a")
        print("  generated week comes from the SOLVER not placing them all")
        print("  (somebody on leave, at a cap, unavailable), not from the")
        print("  model. Look at why_empty.py for the days that stretch.")
    else:
        print(f"  INCONSISTENT — the curve asks for {total_short} hours of")
        print("  cover that none of the shop's own shift shapes reach. The")
        print("  solver closes each of them by stretching a neighbour, which")
        print("  is one advisory per hour, every week, for ever.")
        print()
        print("  These two are learned from the SAME approved rosters, so")
        print("  they should agree. They do not, which means one of them is")
        print("  built wrong — most likely the rounding in hours_covered")
        print("  (CLAUDE.md §7d), which credits a 17:30 start with the whole")
        print("  17:00 hour when the curve is built, and then cannot fill it")
        print("  from shapes that genuinely start at 17:30.")
        if worst:
            top = sorted(worst.items(), key=lambda kv: -kv[1])[:3]
            print("\n  Worst days: " + ", ".join(
                f"{d} ({n} hours)" for d, n in top))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--week", required=True, help="Monday, YYYY-MM-DD")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.week))


if __name__ == "__main__":
    main()
