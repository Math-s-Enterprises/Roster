"""Remove shifts that put the same person on the same day twice.

    python ml/fix_duplicate_shifts.py --email you@example.com            # dry run
    python ml/fix_duplicate_shifts.py --email you@example.com --commit

A duplicate is invisible in the grid, which draws one cell per person per day,
and wrong in every total that counts rows — two people at the reference shop
came out on 60h against a 40h contract, with four real shifts and two copies.

The solver now drops these at the end of every solve, but rosters already
saved still carry them. This repairs those. The LONGER shift is kept: a
duplicate is either the same shift twice, in which case they are identical, or
a real shift plus a fragment, in which case the real one is the one to keep.

Totals are recomputed from what is left, so hours and cost stop disagreeing
with the grid.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services.scheduler import (                        # noqa: E402
    shift_duration_minutes,
    shift_paid_hours,
)


async def run(email: str, commit: bool) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})

    employees = {
        e["employee_id"]: e.get("name", e["employee_id"])
        for e in await db.employees.find(
            {"shop_id": shop["shop_id"]}, {"_id": 0}
        ).to_list(1000)
    }
    rates = {
        e["employee_id"]: e.get("hourly_rate", 0)
        for e in await db.employees.find(
            {"shop_id": shop["shop_id"]}, {"_id": 0}
        ).to_list(1000)
    }

    rosters = await db.rosters.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}
    ).to_list(2000)

    total_removed = 0
    for roster in rosters:
        keep, removed = {}, []
        for shift in roster.get("shifts", []):
            if not (shift.get("start") and shift.get("end")):
                keep[id(shift)] = shift
                continue
            key = (shift["employee_id"], shift["day"])
            existing = keep.get(key)
            if existing is None:
                keep[key] = shift
                continue
            winner, loser = sorted(
                (existing, shift),
                key=lambda s: -shift_duration_minutes(s["start"], s["end"]),
            )
            keep[key] = winner
            removed.append(loser)

        if not removed:
            continue

        total_removed += len(removed)
        cleaned = [s for s in roster.get("shifts", []) if s not in removed]
        print(f"\n{roster.get('week_start')} ({roster.get('version')}) — "
              f"{len(removed)} duplicate(s)")
        for shift in removed:
            print(f"    {employees.get(shift['employee_id'], '?'):16}"
                  f"{shift['day']}  {shift['start']}-{shift['end']}")
        print(f"    hours {roster.get('total_hours')} -> "
              f"{round(sum(shift_paid_hours(s) for s in cleaned if not (s.get('unpaid_holiday') or s.get('sick') or s.get('paid_holiday'))), 2)}")

        if commit:
            await db.rosters.update_one(
                {"roster_id": roster["roster_id"]},
                {"$set": {
                    "shifts": cleaned,
                    "total_hours": sum(
                        shift_paid_hours(s) for s in cleaned
                        if not (s.get("unpaid_holiday") or s.get("sick")
                                or s.get("paid_holiday"))
                    ),
                    "labor_cost": sum(
                        shift_paid_hours(s) * rates.get(s["employee_id"], 0)
                        for s in cleaned
                        if not (s.get("unpaid_holiday") or s.get("sick"))
                    ),
                }},
            )

    if not total_removed:
        print("\nNo duplicates found.")
        return
    print(f"\n{total_removed} duplicate shift(s) across "
          f"{len(rosters)} roster(s).")
    if not commit:
        print("Dry run — nothing changed. Re-run with --commit to apply.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--commit", action="store_true",
                        help="actually write the changes")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.commit))


if __name__ == "__main__":
    main()
