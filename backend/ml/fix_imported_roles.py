"""Repair job titles on staff created by an earlier import.

WHY THIS EXISTS
---------------
Imports used to rewrite the sheet's job titles onto a fixed vocabulary before
saving them. Every kind of manager became "Manager"; both "Night Shift" and
"Goods Inwards" became "Stocker". The table consulted nothing about the shop,
so a manager who had configured their real job titles during setup got them
replaced by roles they had never chosen — and five distinct rungs of the
hierarchy collapsed into one, flattening the seniority order the scheduler
allocates hours by.

The import is fixed. This corrects the records it already wrote, by re-reading
the roles from the original workbook and matching them against the shop's
configured ladder — the same `hierarchy.match_role` the import now uses, so
the two cannot disagree.

ONLY the `role` field is touched. Rosters, shifts, hours and holiday balances
are left alone.

USAGE
-----
    python ml/fix_imported_roles.py "path/to/new roster 26.xlsx"
    python ml/fix_imported_roles.py "path/to/new roster 26.xlsx" --commit

Dry run by default: it prints what it would change and writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import hierarchy                          # noqa: E402
from app.services.roster_import import (                    # noqa: E402
    parse_workbook_rows,
    read_xlsx,
)


async def main(
    path: Path,
    email: str | None,
    commit: bool,
    shop_id: str | None = None,
    aliases: list[str] | None = None,
    allow_demotions: bool = False,
) -> int:
    if not path.exists():
        print(f"No such file: {path}")
        return 1

    # -- which shop --------------------------------------------------------
    # The link runs shop -> user, not the other way: a shop carries owner_id,
    # a user carries no shop_id at all.
    query = {}
    if shop_id:
        query = {"shop_id": shop_id.strip()}
    elif email:
        user = await db.users.find_one({"email": email.strip().lower()})
        if not user:
            print(f"No account for {email}")
            return 1
        query = {"owner_id": user["user_id"]}

    shops = await db.shops.find(query, {"_id": 0}).to_list(10)
    if not shops:
        print("No shop found.")
        return 1
    if len(shops) > 1:
        print(f"{len(shops)} shops found — pass --shop-id or --email to choose one:")
        for s in shops:
            print(f"    --shop-id {s['shop_id']}    {s.get('name')}")
        return 1

    shop = shops[0]
    ladder = hierarchy.get_hierarchy(shop)
    print(f"Shop: {shop.get('name')} ({shop['shop_id']})")
    print(f"Configured roles: {', '.join(ladder)}")
    if not shop.get("role_hierarchy"):
        print("  (no ladder configured — using the built-in default)")

    # -- aliases -----------------------------------------------------------
    # Applied to the in-memory shop first so the dry run shows exactly what a
    # commit would do. Only written to the database on --commit.
    stored = dict(shop.get("role_aliases") or {})
    added: dict[str, str] = {}
    for pair in aliases or []:
        if "=" not in pair:
            print(f"\nAlias needs the form \"sheet wording=your role\": {pair!r}")
            return 1
        sheet_word, our_role = (part.strip() for part in pair.split("=", 1))
        if not hierarchy.match_role(our_role, shop) in ladder:
            print(f"\n{our_role!r} is not one of your configured roles.")
            print(f"Choose from: {', '.join(ladder)}")
            return 1
        added[sheet_word] = our_role

    if added:
        stored.update(added)
        shop = {**shop, "role_aliases": stored}
        print("\nAliases in use:")
        for sheet_word, our_role in sorted(stored.items()):
            mark = "  (new)" if sheet_word in added else ""
            print(f"    sheet \"{sheet_word}\" means \"{our_role}\"{mark}")
    elif stored:
        print(f"\n{len(stored)} alias(es) already saved on this shop.")

    # -- what the sheet actually says --------------------------------------
    # The LATEST week a person appears in wins, not the earliest. A workbook
    # spanning January to August records promotions inside itself: reading
    # someone's January section and calling it their role today would undo
    # every move they made during the year.
    weeks = sorted(
        parse_workbook_rows(read_xlsx(str(path))),
        key=lambda w: w.week_start or "",
    )

    from_sheet: dict[str, str] = {}
    seen_roles: dict[str, list[tuple[str, str]]] = {}
    for week in weeks:
        for name, role in week.employees.items():
            if not role:
                continue
            from_sheet[name] = role
            history = seen_roles.setdefault(name, [])
            if not history or history[-1][1] != role:
                history.append((week.week_start or "?", role))

    print(f"\nRead {len(from_sheet)} named people from {path.name}")

    moved = {n: h for n, h in seen_roles.items() if len(h) > 1}
    if moved:
        print(f"\n{len(moved)} person/people changed section during the workbook — "
              f"using their most recent:\n")
        for name in sorted(moved):
            trail = "  →  ".join(f"{role} (from {when})" for when, role in moved[name])
            print(f"    {name}: {trail}")

    # -- compare against what is stored ------------------------------------
    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}
    ).to_list(1000)
    by_name = {e["name"].strip().lower(): e for e in employees}

    ranks = hierarchy.rank_map(shop)

    changes: list[tuple[str, str, str, str]] = []
    unmatched: list[str] = []
    demotions: list[tuple[str, str, str]] = []
    unknown: dict[str, str] = {}

    for name, sheet_role in sorted(from_sheet.items()):
        employee = by_name.get(name.strip().lower())
        if not employee:
            unmatched.append(name)
            continue

        correct = hierarchy.match_role(sheet_role, shop)
        was = employee.get("role", "")
        if not correct or correct == was:
            continue

        # A title the shop does not have would land at the bottom of the
        # ladder, below every real rung. Refusing to write those is the whole
        # reason this script has a dry run: applying them would have ranked
        # the most senior manager below the night staff.
        if hierarchy.rank_of(correct, ranks) == hierarchy.UNRANKED:
            unknown[sheet_role] = correct
            continue

        # Someone promoted since the sheet was written must not be knocked
        # back down by their own old roster.
        if not allow_demotions and (
            hierarchy.rank_of(correct, ranks) > hierarchy.rank_of(was, ranks)
        ):
            demotions.append((name, was, correct))
            continue

        changes.append((employee["employee_id"], name, was, correct))

    if unmatched:
        print(f"\n{len(unmatched)} name(s) in the sheet with no employee record "
              f"(renamed, or never imported): {', '.join(unmatched[:8])}"
              + (" …" if len(unmatched) > 8 else ""))

    if unknown:
        print(f"\n{len(unknown)} role(s) in the sheet are not in your ladder — SKIPPED:\n")
        width = max(len(k) for k in unknown)
        for sheet_role in sorted(unknown):
            print(f"    sheet says {sheet_role:{width}}   → no matching role configured")
        print("\nTeach the shop what these mean, then re-run. For example:")
        example = sorted(unknown)[0]
        print(f'    --alias "{example}={ladder[0]}"')
        print("Aliases are saved on the shop, so imports match from then on.")

    if demotions:
        print(f"\n{len(demotions)} change(s) would move someone DOWN the ladder — SKIPPED:\n")
        width = max(len(n) for n, _, _ in demotions)
        for name, was, now in demotions:
            print(f"    {name:{width}}  {was}  →  {now}")
        print("\nLikely promoted since the sheet was written. Pass --allow-demotions "
              "to apply them anyway.")

    if not changes:
        print("\nNothing safe to change.")
        return 0

    width = max(len(name) for _, name, _, _ in changes)
    print(f"\n{len(changes)} role(s) to correct:\n")
    for _, name, was, now in changes:
        print(f"    {name:{width}}  {was or '(none)':>24}  →  {now}")

    if not commit:
        print("\n" + "=" * 62)
        print("DRY RUN — nothing written. Re-run with --commit to apply.")
        print("=" * 62)
        return 0

    if added:
        await db.shops.update_one(
            {"shop_id": shop["shop_id"]}, {"$set": {"role_aliases": stored}}
        )
        print(f"\nSaved {len(added)} alias(es) — future imports will use them.")

    for employee_id, _, _, now in changes:
        await db.employees.update_one(
            {"employee_id": employee_id, "shop_id": shop["shop_id"]},
            {"$set": {"role": now}},
        )
    print(f"Updated {len(changes)} employee(s).")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path, help="the .xlsx the staff were imported from")
    parser.add_argument("--email", help="account email, if the database holds more than one shop")
    parser.add_argument("--shop-id", help="shop to fix, instead of --email")
    parser.add_argument(
        "--alias", action="append", metavar='"SHEET=YOUR ROLE"',
        help='what a sheet word means here, e.g. --alias "Shop Floor=Floor Assistant". '
             "Repeatable. Saved on the shop when committed.",
    )
    parser.add_argument(
        "--allow-demotions", action="store_true",
        help="also apply changes that move somebody down the ladder",
    )
    parser.add_argument("--commit", action="store_true", help="write the changes")
    args = parser.parse_args()

    raise SystemExit(asyncio.run(main(
        args.workbook, args.email, args.commit, args.shop_id,
        args.alias, args.allow_demotions,
    )))
