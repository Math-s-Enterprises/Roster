"""Shift imported rosters and leave back by six days.

    python ml/fix_week_dates.py --email you@example.com          # dry run
    python ml/fix_week_dates.py --email you@example.com --commit

An earlier version of the importer read a sheet named 'we Aug 23rd 26' as the
week STARTING Aug 23. It is week-ENDING: that sheet holds Mon 17th to Sun
23rd, so the week starts on the 17th.

Everything derived from the week start inherited the error — most visibly the
holiday records, which landed six days late and marked staff as on leave
during weeks they actually worked.

Only records written by the importer (`imported: true`, or roster ids starting
`hist_`) are touched. Anything created in the app is left alone.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402

SHIFT_DAYS = 6


def shift_date(value: str) -> str:
    return (datetime.strptime(value, "%Y-%m-%d").date() - timedelta(days=SHIFT_DAYS)).isoformat()


async def run(email: str, commit: bool) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    shop_id = shop["shop_id"]

    rosters = await db.rosters.find(
        {"shop_id": shop_id, "historical": True}, {"_id": 0}
    ).to_list(500)
    holidays = await db.holidays.find(
        {"shop_id": shop_id, "imported": True}, {"_id": 0}
    ).to_list(2000)

    print(f"\n{shop['name']}")
    print(f"  {len(rosters)} imported rosters")
    print(f"  {len(holidays)} imported leave records")

    if not rosters and not holidays:
        print("\nNothing imported to fix.")
        return

    if rosters:
        weeks = sorted(r["week_start"] for r in rosters)
        print(f"\n  weeks currently span {weeks[0]} .. {weeks[-1]}")
        print(f"  will become           {shift_date(weeks[0])} .. {shift_date(weeks[-1])}")
        for roster in rosters[:3]:
            print(f"    {roster['week_start']} -> {shift_date(roster['week_start'])}"
                  f"   ({roster.get('source_sheet', '')})")

    already_correct = [
        r for r in rosters
        if datetime.strptime(r["week_start"], "%Y-%m-%d").date().weekday() == 0
        and datetime.strptime(shift_date(r["week_start"]), "%Y-%m-%d").date().weekday() != 0
    ]
    if already_correct:
        print(f"\n  WARNING: {len(already_correct)} rosters already start on a Monday.")
        print("  This may have been run before. Shifting again would be wrong — stopping.")
        return

    if not commit:
        print("\nDRY RUN — nothing changed. Re-run with --commit to apply.")
        return

    for roster in rosters:
        await db.rosters.update_one(
            {"roster_id": roster["roster_id"]},
            {"$set": {"week_start": shift_date(roster["week_start"])}},
        )

    for holiday in holidays:
        changes = {"date": shift_date(holiday["date"])}
        if holiday.get("end_date"):
            changes["end_date"] = shift_date(holiday["end_date"])
        await db.holidays.update_one({"holiday_id": holiday["holiday_id"]}, {"$set": changes})

    print(f"\nMoved {len(rosters)} rosters and {len(holidays)} leave records back "
          f"{SHIFT_DAYS} days.")
    print("Regenerate any roster to pick up the corrected history.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.commit))


if __name__ == "__main__":
    main()
