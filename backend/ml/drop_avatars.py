"""Remove the `avatar` field from stored employee records.

    python ml/drop_avatars.py                    # every shop, dry run
    python ml/drop_avatars.py --commit           # every shop, apply
    python ml/drop_avatars.py --email you@example.com --commit   # one shop

Employees are identified by name alone now. The prototype assigned each new
starter one of four stock Unsplash portraits on a rotating index, so a fifth
employee wore the same stranger's face as the first — actively misleading on
a roster grid, where the picture is what the eye lands on first.

The field is gone from the API and the UI; this clears it out of documents
that were written before that change, so nothing is carrying a dead URL to a
photo of someone who does not work there.

--email is optional because this is a pure cleanup with no per-shop
decisions to make, and requiring it meant guessing which address the account
was created with. Safe to run more than once: employees without the field
are not matched.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402


async def _shops_for(email: Optional[str]) -> List[Dict[str, Any]]:
    """The shops to clean, and a useful error if the email matches nothing."""
    if not email:
        return await db.shops.find({}, {"_id": 0}).to_list(500)

    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        known = await db.users.find({}, {"_id": 0, "email": 1}).to_list(50)
        print(f"No account for {email}.")
        if known:
            print("\nAccounts in this database:")
            for account in known:
                print(f"  {account.get('email')}")
            print("\nOr drop --email to clean every shop at once.")
        else:
            print("\nThis database has no accounts at all — check MONGO_URL "
                  "in backend/.env points at the right server.")
        sys.exit(1)

    shops = await db.shops.find({"owner_id": user["user_id"]}, {"_id": 0}).to_list(50)
    if not shops:
        sys.exit(f"{email} has no shop yet.")
    return shops


async def run(email: Optional[str], commit: bool) -> None:
    shops = await _shops_for(email)
    if not shops:
        sys.exit("No shops found. Check MONGO_URL in backend/.env.")

    total = 0
    for shop in shops:
        query = {"shop_id": shop["shop_id"], "avatar": {"$exists": True}}
        affected = await db.employees.find(query, {"_id": 0}).to_list(1000)

        print(f"\n{shop.get('name') or shop['shop_id']}")
        if not affected:
            print("  nothing to clear")
            continue

        print(f"  {len(affected)} employee record(s) still carry an avatar field")
        for employee in affected[:10]:
            print(f"    {employee.get('name', employee['employee_id'])}")
        if len(affected) > 10:
            print(f"    ... and {len(affected) - 10} more")

        if commit:
            result = await db.employees.update_many(query, {"$unset": {"avatar": ""}})
            total += result.modified_count
        else:
            total += len(affected)

    if total == 0:
        print("\nNothing to clear — already done.")
    elif commit:
        print(f"\nCleared the avatar field from {total} employee(s).")
    else:
        print(f"\nDRY RUN — {total} record(s) would be cleared. "
              "Re-run with --commit to apply.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", help="Limit to one owner. Omit for all shops.")
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.commit))


if __name__ == "__main__":
    main()
