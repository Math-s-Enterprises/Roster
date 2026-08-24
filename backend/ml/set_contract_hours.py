"""Change contracted weekly hours in bulk.

    python ml/set_contract_hours.py --from 40 --to 42.5           # dry run
    python ml/set_contract_hours.py --from 40 --to 42.5 --commit

Contracted hours are PAID hours — what payroll pays and what the roster owes
somebody. Time on the floor is longer, because unpaid breaks sit on top: at
the shop's break policy a 42.5h contract is roughly 46h of shift time.

Written for the move from a 40h full-time contract to 42.5h. Only employees
currently on exactly the --from value are touched, so part-timers and anyone
already corrected are left alone.

Safe to run more than once: after the first pass nobody matches --from.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402


async def _shops(email: Optional[str]) -> List[Dict[str, Any]]:
    if not email:
        return await db.shops.find({}, {"_id": 0}).to_list(500)
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}. Drop --email to cover every shop.")
    shops = await db.shops.find({"owner_id": user["user_id"]}, {"_id": 0}).to_list(50)
    if not shops:
        sys.exit(f"{email} has no shop yet.")
    return shops


async def run(email: Optional[str], old: float, new: float, commit: bool) -> None:
    shops = await _shops(email)
    total = 0

    for shop in shops:
        query = {"shop_id": shop["shop_id"], "max_weekly_hours": old}
        affected = await db.employees.find(query, {"_id": 0}).to_list(1000)

        print(f"\n{shop.get('name') or shop['shop_id']}")
        if not affected:
            print(f"  nobody is on a {old:g}h contract")
            continue

        print(f"  {len(affected)} employee(s) on {old:g}h -> {new:g}h")
        for employee in affected[:12]:
            print(f"    {employee.get('name', employee['employee_id'])}")
        if len(affected) > 12:
            print(f"    ... and {len(affected) - 12} more")

        if commit:
            result = await db.employees.update_many(
                query, {"$set": {"max_weekly_hours": new}}
            )
            total += result.modified_count
        else:
            total += len(affected)

    if total == 0:
        print("\nNothing to change.")
    elif commit:
        print(f"\nUpdated {total} employee(s) to a {new:g}h contract.")
        print("Re-generate any open roster so the new hours are used.")
    else:
        print(f"\nDRY RUN — {total} employee(s) would change. "
              "Re-run with --commit to apply.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", help="Limit to one owner. Omit for all shops.")
    parser.add_argument("--from", dest="old", type=float, required=True,
                        help="Only employees currently on exactly this many hours.")
    parser.add_argument("--to", dest="new", type=float, required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    if args.new <= 0 or args.new > 168:
        sys.exit("--to must be a sensible weekly figure.")
    asyncio.run(run(args.email, args.old, args.new, args.commit))


if __name__ == "__main__":
    main()
