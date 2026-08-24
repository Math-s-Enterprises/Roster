"""Import a roster spreadsheet into a shop.

    python ml/import_workbook.py "new roster 26.xlsx" --email you@example.com

Creates any employees the sheet mentions but the shop doesn't have, then writes
one approved historical roster per week. Those rosters are exactly what
compute_weights() learns from, so the app has real history immediately instead
of starting empty.

This is the command-line half of Stage A in docs/ML_PLAN.md — the same logic
the upload UI will eventually call, minus the review screen. Because there is
no human review step here, it defaults to a dry run: you see what *would*
happen and must pass --commit to actually write.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.services.roster_import import (  # noqa: E402
    parse_workbook_rows,
    read_xlsx,
    summarise,
)
from app.services.scheduler import shift_duration_minutes  # noqa: E402
from app.services import hierarchy  # noqa: E402
from app.services.shop_service import ensure_shop  # noqa: E402

DEFAULT_RATE = 13.0
DEFAULT_MAX_WEEKLY_HOURS = 40.0
DEFAULT_AGE = 25


def map_role(raw: str | None, shop: dict | None = None) -> str:
    """A sheet's job title, as this shop spells it.

    Was a second copy of the API's ROLE_MAP, with the same fault and slightly
    different contents — so the same workbook could produce different roles
    depending on which route imported it. Both now defer to the shop's
    configured ladder.
    """
    matched = hierarchy.match_role(raw, shop)
    if matched:
        return matched
    ladder = hierarchy.get_hierarchy(shop)
    return ladder[-1] if ladder else "Floor Assistant"


def placeholder_email(name: str, shop_id: str) -> str:
    """Imported staff have no email in the spreadsheet.

    A unique placeholder keeps the employee record valid without inventing a
    real address that dispatch would then try to email.

    The shop_id is stripped of punctuation: it contains an underscore, which
    is not legal in a domain, and the resulting address failed the validation
    every employee save runs through — making imported staff uneditable.
    """
    slug = "".join(ch.lower() for ch in name if ch.isalnum()) or "staff"
    tenant = "".join(ch for ch in shop_id.lower() if ch.isalnum())[:12] or "shop"
    return f"{slug}@imported.{tenant}.local"


async def run(path: str, email: str, commit: bool, year: int) -> None:
    weeks = parse_workbook_rows(read_xlsx(path), year)
    usable = [w for w in weeks if w.is_usable]
    stats = summarise(weeks)

    print(f"\nParsed {path}")
    print(f"  weeks usable      {stats['weeks_usable']} of {stats['sheets_seen']} sheets")
    print(f"  employees         {stats['employees']}")
    print(f"  shifts            {stats['total_shifts']}")
    print(f"  absences          {stats['total_absences']}")
    print(f"  events            {stats.get('events', 0)}")
    print(f"  needs review      {stats['unparsed_cells']} cells")
    if stats["date_range"]:
        print(f"  date range        {stats['date_range'][0]} to {stats['date_range'][1]}")

    if not usable:
        sys.exit("\nNothing usable to import.")

    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(
            f"\nNo account found for {email}.\n"
            "Sign up in the app first, then re-run this command."
        )
    shop = await ensure_shop(user)
    shop_id = shop["shop_id"]
    print(f"\nTarget shop: {shop['name']} ({shop_id})")

    # -- employees ---------------------------------------------------------
    existing = {
        e["name"].strip().lower(): e
        for e in await db.employees.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    }
    roles = stats["employee_roles"]
    to_create = [n for n in roles if n.strip().lower() not in existing]

    print(f"\nEmployees: {len(roles)} in sheet, "
          f"{len(roles) - len(to_create)} already exist, {len(to_create)} to create")
    for name in to_create[:40]:
        print(f"    + {name:16} {map_role(roles[name], shop)}")

    # -- weeks -------------------------------------------------------------
    already = {
        r["week_start"]
        for r in await db.rosters.find(
            {"shop_id": shop_id, "historical": True}, {"_id": 0, "week_start": 1}
        ).to_list(500)
    }
    new_weeks = [w for w in usable if w.week_start not in already]
    print(f"\nWeeks: {len(new_weeks)} new, {len(usable) - len(new_weeks)} already imported")

    warnings = [x for w in usable for x in w.warnings]
    if warnings:
        print(f"\n{len(warnings)} data warnings (likely typos in the sheet):")
        for line in warnings[:8]:
            print(f"    - {line}")
        if len(warnings) > 8:
            print(f"    ... and {len(warnings) - 8} more")

    unparsed = [u for w in usable for u in w.unparsed_cells]
    if unparsed:
        print(f"\n{len(unparsed)} cells could not be read and will be skipped:")
        for cell in unparsed[:8]:
            print(f"    - {cell['employee_name']} {cell['day']}: {cell['value']!r}")

    if not commit:
        print("\n" + "=" * 60)
        print("DRY RUN — nothing written. Re-run with --commit to import.")
        print("=" * 60)
        return

    # -- write -------------------------------------------------------------
    name_to_id = {name.lower(): emp["employee_id"] for name, emp in existing.items()}

    for name in to_create:
        employee_id = f"emp_{uuid.uuid4().hex[:12]}"
        await db.employees.insert_one({
            "employee_id": employee_id,
            "shop_id": shop_id,
            "name": name,
            "email": placeholder_email(name, shop_id),
            "role": map_role(roles[name], shop),
            "age": DEFAULT_AGE,
            "hourly_rate": DEFAULT_RATE,
            "max_weekly_hours": DEFAULT_MAX_WEEKLY_HOURS,
            "preferred_days_off": [],
            "departments": ["Shop Floor"],
            "imported": True,
        })
        name_to_id[name.lower()] = employee_id

    imported = skipped = 0
    for week in new_weeks:
        shifts: List[Dict[str, Any]] = []
        for shift in week.shifts:
            employee_id = name_to_id.get(shift.employee_name.lower())
            if not employee_id:
                skipped += 1
                continue
            shifts.append({
                "shift_id": f"sh_{uuid.uuid4().hex[:8]}",
                "employee_id": employee_id,
                "day": shift.day,
                "start": shift.start,
                "end": shift.end,
                "fixed": False,
            })
        if not shifts:
            continue

        total_hours = sum(
            shift_duration_minutes(s["start"], s["end"]) / 60 for s in shifts
        )
        await db.rosters.insert_one({
            "roster_id": f"hist_{uuid.uuid4().hex[:12]}",
            "shop_id": shop_id,
            "week_start": week.week_start,
            "version": "v1.0-hist",
            "shifts": shifts,
            "issues": [],
            "critical_issues": [],
            "compliance_score": 100,
            "labor_cost": 0,
            "total_hours": round(total_hours, 1),
            "utilization": 0,
            "per_employee_hours": {},
            "approved": True,
            "historical": True,
            "source_sheet": week.sheet_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        imported += 1

    # Absences become holiday records so the solver knows about real leave.
    #
    # NOTE: bank_holiday is per-EMPLOYEE, not shop-wide. A 'b/hol' cell sits in
    # one person's row and means that person took the bank holiday as paid
    # leave — the shop stayed open. Mapping it to scope='shop' closed the whole
    # business for everyone on those dates, which silently produced rosters
    # with entire days missing.
    absence_map = {"holiday": "employee", "sick": "sick", "bank_holiday": "employee"}
    absences_written = 0
    for week in new_weeks:
        week_start = datetime.strptime(week.week_start, "%Y-%m-%d").date()
        day_index = {d: i for i, d in enumerate(
            ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        )}
        for absence in week.absences:
            scope = absence_map.get(absence.kind)
            if not scope:
                continue  # 'off' and 'unavailable' are not leave records
            employee_id = name_to_id.get(absence.employee_name.lower())
            if not employee_id and scope != "shop":
                continue
            from datetime import timedelta
            date_iso = (week_start + timedelta(days=day_index[absence.day])).isoformat()
            await db.holidays.insert_one({
                "holiday_id": f"hol_{uuid.uuid4().hex[:10]}",
                "shop_id": shop_id,
                "date": date_iso,
                "end_date": date_iso,
                "label": absence.kind.replace("_", " ").title(),
                "scope": scope,
                "employee_id": employee_id,
                "imported": True,
            })
            absences_written += 1

    print(f"\nImported {imported} weeks, {len(to_create)} new employees, "
          f"{absences_written} leave records.")
    if skipped:
        print(f"Skipped {skipped} shifts for unmatched employees.")
    print("\nOpen the app — Past Rosters and AI Training should now show real data.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", help="path to the .xlsx roster file")
    parser.add_argument("--email", required=True, help="the account to import into")
    parser.add_argument("--commit", action="store_true",
                        help="actually write (default is a dry run)")
    parser.add_argument("--year", type=int, default=2026,
                        help="year to assume when a sheet name omits it")
    args = parser.parse_args()

    if not Path(args.workbook).exists():
        sys.exit(f"File not found: {args.workbook}")

    asyncio.run(run(args.workbook, args.email, args.commit, args.year))


if __name__ == "__main__":
    main()
