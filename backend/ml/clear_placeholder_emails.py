"""Clear the invented email addresses on imported staff.

WHY
---
The importer used to fabricate an address for staff read from a spreadsheet:
"jane@imported.shop_645.local". It failed the app's own employee validation
twice over — an underscore is illegal in a domain, and ".local" is a reserved
name — so anyone imported could be created and then never edited. Opening one,
changing their pay and saving returned a validation error about an address the
manager had never typed and could not see.

Imports no longer invent addresses. This clears the ones already stored, so
those records become editable and dispatch reports them as unreachable rather
than appearing to send.

Only the `email` field is touched, and only where it matches the pattern the
importer generated. A real address somebody has since typed in is left alone.

USAGE
-----
    python ml/clear_placeholder_emails.py
    python ml/clear_placeholder_emails.py --commit
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402

# What the old importer produced. Anchored so a real address that merely
# mentions "imported" is not caught.
PLACEHOLDER = re.compile(r"^[a-z0-9]+@imported\.[a-z0-9_]+\.local$", re.IGNORECASE)


async def main(shop_id: str | None, commit: bool) -> int:
    scope: dict = {}
    if shop_id:
        scope["shop_id"] = shop_id.strip()

    # Every employee in scope, not just those with an address. Filtering in
    # the query made "nothing to do" and "nobody here" print the same line —
    # "Checked 0 employee(s)" is equally true of a healthy shop and of a
    # mistyped shop id, which is exactly when you need to tell them apart.
    everyone = await db.employees.find(scope, {"_id": 0}).to_list(2000)
    with_address = [e for e in everyone if e.get("email")]
    stale = [
        e for e in with_address
        if isinstance(e["email"], str) and PLACEHOLDER.match(e["email"])
    ]

    if not everyone:
        print("No employees found" + (f" for {shop_id}." if shop_id else "."))
        print("Check the shop id — this is not the same as 'nothing to fix'.")
        return 1

    if not stale:
        print(
            f"{len(everyone)} employee(s) in scope, {len(with_address)} with an "
            f"address. No invented ones found — nothing to do."
        )
        return 0

    by_shop: dict[str, list[dict]] = {}
    for employee in stale:
        by_shop.setdefault(employee.get("shop_id", "?"), []).append(employee)

    print(f"{len(stale)} employee(s) carrying an invented address:\n")
    for shop, people in by_shop.items():
        print(f"  {shop}")
        width = max(len(p["name"]) for p in people)
        for person in sorted(people, key=lambda p: p["name"]):
            print(f"      {person['name']:{width}}   {person['email']}")

    print("\nClearing these makes the records editable again. Nothing else changes.")

    if not commit:
        print("\n" + "=" * 62)
        print("DRY RUN — nothing written. Re-run with --commit to apply.")
        print("=" * 62)
        return 0

    for employee in stale:
        await db.employees.update_one(
            {"employee_id": employee["employee_id"], "shop_id": employee["shop_id"]},
            {"$set": {"email": None}},
        )
    print(f"\nCleared {len(stale)} address(es).")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", help="limit to one shop")
    parser.add_argument("--commit", action="store_true", help="write the changes")
    args = parser.parse_args()

    raise SystemExit(asyncio.run(main(args.shop_id, args.commit)))
