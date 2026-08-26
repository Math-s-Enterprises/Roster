"""Which shops exist, and what each one holds.

Every maintenance script wants a --shop-id, and with more than one account in
the database there is no way to know which is which without looking. Guessing
wrong is how a script gets pointed at the wrong shop's data.

    python ml/list_shops.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402


async def main() -> int:
    shops = await db.shops.find({}, {"_id": 0}).to_list(100)
    if not shops:
        print("No shops in this database.")
        return 1

    users = {
        u["user_id"]: u.get("email", "?")
        for u in await db.users.find({}, {"_id": 0}).to_list(500)
    }

    for shop in sorted(shops, key=lambda s: s.get("name", "")):
        shop_id = shop["shop_id"]
        staff = await db.employees.count_documents({"shop_id": shop_id})
        past = await db.employees.count_documents(
            {"shop_id": shop_id, "past_staff": True}
        )
        rosters = await db.rosters.count_documents({"shop_id": shop_id})
        history = await db.rosters.count_documents(
            {"shop_id": shop_id, "historical": True}
        )
        approved = await db.rosters.count_documents(
            {"shop_id": shop_id, "approved": True}
        )

        print(f"\n{shop.get('name', '(unnamed)')}")
        print(f"    --shop-id {shop_id}")
        print(f"    owner        {users.get(shop.get('owner_id'), '?')}")
        print(f"    staff        {staff - past} active"
              + (f", {past} past" if past else ""))
        print(f"    rosters      {rosters} total, {approved} approved,"
              f" {history} imported")
        print(f"    set up       {'yes' if shop.get('onboarded') else 'NO'}"
              f"   24h: {'yes' if shop.get('open_24h') else 'no'}"
              f"   max shift: {shop.get('max_shift_hours')}h")

        ladder = shop.get("role_hierarchy")
        print(f"    role ladder  {', '.join(ladder) if ladder else '(default)'}")
        aliases = shop.get("role_aliases") or {}
        if aliases:
            for sheet_word, our_role in sorted(aliases.items()):
                print(f"                 \"{sheet_word}\" means \"{our_role}\"")
        else:
            print("                 no aliases saved")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
