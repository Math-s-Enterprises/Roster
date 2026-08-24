"""Repair bank-holiday records imported with the wrong scope.

    python ml/fix_bank_holidays.py --email you@example.com          # dry run
    python ml/fix_bank_holidays.py --email you@example.com --commit

An earlier version of import_workbook.py wrote 'b/hol' cells as shop-wide
closures. They are per-employee paid leave: the shop stays open. The effect
was that any week containing one generated a roster with entire days empty,
because the solver believed the business was shut.

This converts those records to employee scope. Records that already have an
employee_id and shop scope are the ones affected; genuine shop closures have
no employee_id and are left alone.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402


async def run(email: str, commit: bool) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop.")

    query = {
        "shop_id": shop["shop_id"],
        "scope": "shop",
        "imported": True,
        "employee_id": {"$ne": None},
    }
    affected = await db.holidays.find(query, {"_id": 0}).to_list(1000)

    print(f"\n{shop['name']}")
    print(f"  {len(affected)} bank-holiday records wrongly closing the whole shop")
    if affected:
        dates = sorted({h["date"] for h in affected})
        print(f"  dates affected: {', '.join(dates)}")

    if not affected:
        print("\nNothing to fix.")
        return

    if not commit:
        print("\nDRY RUN — nothing changed. Re-run with --commit to fix.")
        return

    result = await db.holidays.update_many(query, {"$set": {"scope": "employee"}})
    print(f"\nConverted {result.modified_count} records to employee-scoped leave.")
    print("Re-generate any roster in an affected week to see the difference.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.commit))


if __name__ == "__main__":
    main()
