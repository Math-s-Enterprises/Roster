"""How much coverage the hour-rounding is inventing.

    python ml/check_partial_hours.py --email you@example.com

WHY
---
`hours_covered` walks a shift in 60-minute steps FROM ITS START MINUTE and
floors each step to an hour:

    for minute in range(start_m, end_m, 60):
        covered.add((day, (minute // 60) % 24))

So a shift beginning 17:30 is credited with hour 17 — the whole 17:00-18:00
block — on the strength of being there for half of it. That is how a
gap-closing stretch from 18:00 to 17:30 "covers wed 17:00" while the shop is
genuinely empty from 17:00 to 17:30.

Rule 1 is that somebody is on the floor from open to close, and §1 says never
to invent coverage that cannot be staffed. This measures how much is being
invented before anybody changes the model, because the fix is only worth its
risk if the number is real.

WHAT IT MEASURES
----------------
Two different things, deliberately kept apart:

  MODEL      what the solver believes, via hours_covered
  REALITY    minute-by-minute headcount, built from the same shifts

An hour is INVENTED when the model calls it covered and reality has at least
one minute in it with nobody in the shop. That is the only figure that
matters: an hour credited to a 17:30 start is harmless if a colleague is
standing there 17:00-17:30, and it is a real hole if not.

Reported per week and totalled, alongside how many shifts even start or end
off the hour — if that is near zero the whole question is theoretical for
this shop.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services.learning import latest_per_week           # noqa: E402
from app.services.scheduler import (                        # noqa: E402
    DAYS,
    _RosterBuilder,
    to_minutes,
)

WEEK_MINUTES = 7 * 24 * 60


def _is_leave(shift: Dict[str, Any]) -> bool:
    return bool(shift.get("paid_holiday") or shift.get("unpaid_holiday")
                or shift.get("sick"))


def _headcount_by_minute(shifts: List[Dict[str, Any]]) -> List[int]:
    """People in the shop for every minute of the week.

    The ground truth this whole script compares against. Overnight shifts wrap
    into the next day and Sunday night wraps to Monday, matching
    hours_covered(wrap_week=True) so the two are measuring the same week.
    """
    minutes = [0] * WEEK_MINUTES
    for shift in shifts:
        if _is_leave(shift) or not (shift.get("start") and shift.get("end")):
            continue
        try:
            day_index = DAYS.index(shift["day"])
        except ValueError:
            continue
        start = day_index * 1440 + to_minutes(shift["start"])
        end = day_index * 1440 + to_minutes(shift["end"])
        if end <= start:
            end += 1440
        for m in range(start, end):
            minutes[m % WEEK_MINUTES] += 1
    return minutes


def _open_minutes(shop: Dict[str, Any]) -> List[bool]:
    """Which minutes the shop is trading. Everything else cannot have a gap."""
    if shop.get("open_24h"):
        return [True] * WEEK_MINUTES
    open_flags = [False] * WEEK_MINUTES
    by_day = {h.get("day"): h for h in shop.get("hours") or []}
    for index, day in enumerate(DAYS):
        hours = by_day.get(day)
        if not hours or hours.get("closed"):
            continue
        start = index * 1440 + to_minutes(hours.get("open") or "00:00")
        end = index * 1440 + to_minutes(hours.get("close") or "00:00")
        if end <= start:
            end += 1440
        for m in range(start, end):
            open_flags[m % WEEK_MINUTES] = True
    return open_flags


async def run(email: str, weeks: int) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")

    rosters = await db.rosters.find(
        {"shop_id": shop["shop_id"], "approved": True}, {"_id": 0}
    ).to_list(500)
    rosters = sorted(latest_per_week(rosters),
                     key=lambda r: r.get("week_start", ""), reverse=True)[:weeks]
    if not rosters:
        sys.exit("No approved rosters to measure.")

    open_flags = _open_minutes(shop)
    print(f"\n{shop['name']} — {len(rosters)} approved week(s), "
          f"{'open 24h' if shop.get('open_24h') else 'using shop hours'}\n")

    # ---- is this even a live question for this shop? --------------------
    edges: Counter = Counter()
    total_shifts = 0
    for roster in rosters:
        for shift in roster.get("shifts", []):
            if _is_leave(shift) or not (shift.get("start") and shift.get("end")):
                continue
            total_shifts += 1
            edges["start off the hour"] += to_minutes(shift["start"]) % 60 != 0
            edges["end off the hour"] += to_minutes(shift["end"]) % 60 != 0
    print(f"{total_shifts} worked shifts")
    for label, count in edges.items():
        share = 100 * count / total_shifts if total_shifts else 0
        print(f"  {count:5} ({share:4.1f}%) {label}")
    if not any(edges.values()):
        print("\nEvery shift sits on the hour, so the rounding invents nothing")
        print("here and option A would change nothing. Stop.")
        return
    print()

    # ---- model vs reality ------------------------------------------------
    print(f"{'week':12}{'open hrs':>9}{'model says':>12}{'really OK':>11}"
          f"{'INVENTED':>10}{'unattended':>12}")
    grand_invented = grand_minutes = grand_open = 0
    worst: List[tuple] = []

    for roster in rosters:
        shifts = roster.get("shifts", [])
        minutes = _headcount_by_minute(shifts)

        covered_by_model = set()
        for shift in shifts:
            if _is_leave(shift) or not (shift.get("start") and shift.get("end")):
                continue
            covered_by_model.update(_RosterBuilder.hours_covered(
                shift["day"], shift["start"], shift["end"], wrap_week=True,
            ))

        open_hours = invented = fully_ok = unattended_minutes = 0
        for index, day in enumerate(DAYS):
            for hour in range(24):
                base = index * 1440 + hour * 60
                block = range(base, base + 60)
                if not any(open_flags[m % WEEK_MINUTES] for m in block):
                    continue
                open_hours += 1
                empty = sum(
                    1 for m in block
                    if open_flags[m % WEEK_MINUTES]
                    and minutes[m % WEEK_MINUTES] == 0
                )
                unattended_minutes += empty
                if empty == 0:
                    fully_ok += 1
                elif (day, hour) in covered_by_model:
                    # The model calls it staffed; part of it is not.
                    invented += 1
                    worst.append((empty, roster.get("week_start"), day, hour))

        print(f"{roster.get('week_start', '?'):12}{open_hours:>9}"
              f"{len(covered_by_model):>12}{fully_ok:>11}{invented:>10}"
              f"{unattended_minutes:>10}m")
        grand_invented += invented
        grand_minutes += unattended_minutes
        grand_open += open_hours

    print()
    print("=" * 68)
    print(f"{grand_invented} hour(s) across {len(rosters)} week(s) are called "
          f"covered while the shop\nis actually empty for part of them — "
          f"{100 * grand_invented / grand_open:.2f}% of all open hours.")
    print(f"Average {grand_minutes / len(rosters):.0f} unattended minutes per "
          f"week in total\n(including hours the model already reports as a gap).")

    if worst:
        print("\nWorst offenders — minutes with nobody in, in an hour the")
        print("model believes is staffed:")
        for empty, week, day, hour in sorted(worst, reverse=True)[:10]:
            print(f"    {week}  {day} {hour:02d}:00   {empty} min empty")

    print()
    if grand_invented == 0:
        print("VERDICT: the rounding is not inventing coverage in practice.")
        print("Option A would be correct in principle and change nothing real.")
        print("Fix the stretch (option C) and leave the model alone.")
    else:
        print("VERDICT: real holes are being reported as covered. Option A is")
        print("a correction, not a refinement — but expect it to surface these")
        print(f"{grand_invented} hours as gaps in weeks that currently look clean.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--weeks", type=int, default=24)
    args = parser.parse_args()
    asyncio.run(run(args.email, args.weeks))


if __name__ == "__main__":
    main()
