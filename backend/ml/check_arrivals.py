"""Would counting ARRIVALS describe this shop better than counting shapes?

    python ml/check_arrivals.py --email you@example.com

WHAT IS BEING TESTED
--------------------
`demand.py` learns the shop's shift SHAPES and apportions the most common
ones to a per-day headcount target. That scores each shape independently, so
it does not know that `06:00-16:00`, `06:00-14:00` and `06:00-11:00` compete
for the same job — all three look common, all three get picked, and Saturday
comes out with three people starting at 06:00 where the shop runs two.

The shop owner asked for something different from the start: "at 6:00 two
people are coming in, and it should schedule two people." That is ARRIVALS
per hour, not bodies present and not shapes.

It matters that arrivals are not what the solver used to do either. The
original model counted bodies PRESENT each hour and was dropped because it
double-counted changeover — a night worker still on the floor at 06:00 was
in the curve, so filling 06:00 "to target" put a fourth body on an hour that
always had three. Counting arrivals cannot make that mistake: somebody still
on the floor at 06:00 did not START at 06:00.

WHAT THIS PRINTS
----------------
For each day and hour, three numbers:

    manager   how many people actually started then, averaged over history
    shapes    how many the current shape list would start then
    diff      shapes minus manager

WHAT A NON-ZERO ANSWER LOOKS LIKE, STATED BEFORE RUNNING
--------------------------------------------------------
The change is WORTH MAKING if `shapes` differs from `manager` at a
meaningful number of hours — that difference is exactly what an arrivals
model would remove, because it would fit those numbers by construction.

It is NOT worth making if the two already agree almost everywhere. Then the
shape list is reproducing arrivals well enough and Saturday is an isolated
case to be fixed some other way.

Recency-weighted the same way `demand.py` weighs everything, so a shop that
has changed recently is described as it is now.

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
from app.services.demand import (                           # noqa: E402
    RECENCY_HALF_LIFE_WEEKS, _week_start_date, build_profile,
)
from app.services.learning import latest_per_week           # noqa: E402
from app.services.scheduler import DAYS, to_minutes         # noqa: E402


async def run(email: str, day_filter: str | None) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")

    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}).to_list(1000)
    approved = latest_per_week(await db.rosters.find(
        {"shop_id": shop["shop_id"], "approved": True}, {"_id": 0}
    ).to_list(500))
    if not approved:
        sys.exit("No approved rosters to learn from.")

    newest = max(_week_start_date(r["week_start"]) for r in approved
                 if _week_start_date(r.get("week_start")))

    # ARRIVALS THE MANAGER ACTUALLY WRITES, recency-weighted exactly as
    # demand.py weighs everything else.
    arrivals: Dict[str, Dict[int, float]] = {
        d: defaultdict(float) for d in DAYS}
    weight_total = 0.0
    for roster in approved:
        started = _week_start_date(roster.get("week_start"))
        if started is None:
            continue
        age = max(0.0, (newest - started).days / 7.0)
        weight = 0.5 ** (age / RECENCY_HALF_LIFE_WEEKS)
        weight_total += weight
        for shift in roster.get("shifts") or []:
            if shift.get("paid_holiday") or shift.get("unpaid_holiday") \
                    or shift.get("sick"):
                continue
            day, start = shift.get("day"), shift.get("start")
            if day in arrivals and start:
                arrivals[day][to_minutes(start) // 60] += weight
    if not weight_total:
        sys.exit("No datable weeks.")

    # WHAT THE CURRENT SHAPE LIST WOULD START each hour.
    profile = build_profile(
        shop, approved,
        {e["employee_id"]: e.get("role", "") for e in employees})
    shapes: Dict[str, Dict[int, int]] = {d: defaultdict(int) for d in DAYS}
    for day in DAYS:
        for start, _end in (profile.slots_for(day) or []):
            shapes[day][to_minutes(start) // 60] += 1

    print(f"\n{shop.get('name', '?')} — {len(approved)} approved weeks")
    print("How many people START each hour: what the manager writes, against "
          "what\nthe current shape list would produce.\n")

    total_diff = 0.0
    worst: list = []
    for day in DAYS:
        if day_filter and day != day_filter:
            continue
        hours = sorted(set(arrivals[day]) | set(shapes[day]))
        if not hours:
            continue
        print(f"  {day}")
        for hour in hours:
            his = arrivals[day][hour] / weight_total
            ours = shapes[day][hour]
            if his < 0.05 and ours == 0:
                continue
            diff = ours - his
            flag = ""
            if abs(diff) >= 0.5:
                flag = "   <<<"
                worst.append((abs(diff), day, hour, his, ours))
            total_diff += abs(diff)
            print(f"      {hour:02d}:00   manager {his:5.2f}   "
                  f"shapes {ours:>2}   {diff:+5.2f}{flag}")

    print(f"\n{'=' * 72}\nVERDICT\n{'=' * 72}")
    print(f"  total absolute difference across the week: {total_diff:.1f} "
          f"people-starts")
    print(f"  hours out by half a person or more:        {len(worst)}")
    if worst:
        print("\n  Worst:")
        for _, day, hour, his, ours in sorted(worst, reverse=True)[:8]:
            print(f"      {day} {hour:02d}:00   he starts {his:.2f}, "
                  f"the shape list starts {ours}")
    print()
    if len(worst) >= 5:
        print("  WORTH BUILDING. The shape list starts materially different")
        print("  numbers of people from the manager at several hours, and an")
        print("  arrivals model would fit those numbers by construction —")
        print("  it is the quantity it would be learning.")
        print()
        print("  Note what this does NOT settle: how long each of them stays.")
        print("  Arrivals fix 'how many come in at 06:00'. The finish would")
        print("  come from what each person actually works (§2b), which is")
        print("  where Emma's 06:00-12:00 and Jane's 10:00-17:00 live.")
    else:
        print("  NOT WORTH BUILDING. The shape list already starts about the")
        print("  right number of people at each hour, so Saturday is an")
        print("  isolated case rather than a structural fault, and should be")
        print("  fixed some other way.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--day", help="mon..sun, to narrow the output")
    args = parser.parse_args()
    asyncio.run(run(args.email,
                    args.day.lower()[:3] if args.day else None))


if __name__ == "__main__":
    main()
