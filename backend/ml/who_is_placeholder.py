"""Count staff the setup checklist still flags for review.

    python ml/who_is_placeholder.py --email you@example.com

Review individual records from the Employees page.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import availability as avail              # noqa: E402
from app.services.setup_status import _on_import_defaults    # noqa: E402


async def run(email: str) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit("Account not found.")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"shop_id": 1, "_id": 0})
    if not shop:
        sys.exit("Shop not found.")

    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}
    ).to_list(1000)
    active = [e for e in employees if not e.get("past_staff") and avail.is_active(e)]
    flagged = sum(_on_import_defaults(e) for e in active)

    print(f"{len(active)} active staff. {flagged} flagged for review.")
    if flagged:
        print("Open Employees to review individual records.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.email))


if __name__ == "__main__":
    main()
