"""Why is this person still flagged after I changed their hours?

    python ml/why_flagged.py --email you@example.com --who fionn
    python ml/why_flagged.py --email you@example.com --who fionn --week 2026-09-07

WHAT THIS ANSWERS
-----------------
"I fixed their contract, pressed Re-check, and the caution is still there."

There are only a few ways that happens, and they need different fixes:

  1. THE CAP DOES NOT COME FROM THE FIELD YOU EDITED. Which field sets
     somebody's weekly ceiling depends on their employment type:

         full_time_contract  -> contract_span_hours   (max_weekly_hours is IGNORED)
         student             -> max_weekly_hours, or the summer-break figure
                                during their break
         hourly              -> max_weekly_hours

     So raising `max_weekly_hours` on a salaried employee changes nothing,
     and the caution stays exactly as it was. This is the commonest cause.

  2. TWO RECORDS FOR ONE PERSON. The roster references an employee_id, so
     editing the other record leaves the rostered one untouched.

  3. THE EDIT DID NOT SAVE. Rare, but it is worth ruling out before
     assuming the roster page is at fault.

  4. IT REALLY IS STALE. If the stored figure and the live one disagree,
     that is a bug in the app, not in the data — and this says so.

Everything below is read live, the same way the roster page reads it. If
this prints a cap you did not expect, the cap is the problem. If it prints
the cap you DO expect and the page still shows the old one, the page is.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import availability as avail              # noqa: E402
from app.services import compliance                         # noqa: E402
from app.services.scheduler import paid_hours               # noqa: E402


async def run(email: str, who: str, week: str | None) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")
    shop_id = shop["shop_id"]

    employees = await db.employees.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    matches = [e for e in employees if who.lower() in (e.get("name") or "").lower()]
    if not matches:
        sys.exit(f"Nobody matching {who!r}. Names: "
                 f"{', '.join(sorted((e.get('name') or '?') for e in employees))}")

    print(f"\n{shop.get('name', '?')}")
    if len(matches) > 1:
        print(f"\n  *** {len(matches)} RECORDS MATCH {who!r} ***")
        print("  That alone can explain it: the roster points at ONE of these")
        print("  employee_ids, and editing the other changes nothing.\n")

    rosters = await db.rosters.find({"shop_id": shop_id}, {"_id": 0}).to_list(500)
    if week:
        target = [r for r in rosters if r.get("week_start") == week]
    else:
        drafts = [r for r in rosters if not r.get("archived")]
        target = sorted(drafts, key=lambda r: r.get("week_start") or "")[-1:]
    if not target:
        sys.exit(f"No roster for {week}." if week else "No rosters at all.")
    roster = target[0]
    week = roster["week_start"]
    breaks_paid = bool(shop.get("breaks_are_paid"))

    for employee in matches:
        employee_id = employee["employee_id"]
        kind = avail.employment_type(employee)
        cap = avail.weekly_hour_cap(employee, week)
        band = avail.contract_span_band(employee)

        print(f"\n{'=' * 72}")
        print(f"  {employee.get('name')}   [{employee_id}]")
        print(f"{'=' * 72}")
        print(f"  active                : {avail.is_active(employee)}")
        print(f"  employment_type       : {kind}")
        print(f"  max_weekly_hours      : {employee.get('max_weekly_hours')}")
        print(f"  contract_span_hours   : {employee.get('contract_span_hours')}")
        print(f"  contract_span_toleranc: {employee.get('contract_span_tolerance')}")
        print(f"\n  --> the cap actually used for {week}: {cap:g}h")
        if band:
            print(f"  --> contract band            : {band[0]:g}h to {band[1]:g}h")

        # WHICH FIELD IS LOAD-BEARING. This is the whole point of the script.
        if kind == "full_time_contract":
            source = "contract_span_hours"
            ignored = "max_weekly_hours is IGNORED for this employment type"
        elif kind == "student":
            source = "max_weekly_hours (or the summer-break figure in the break)"
            ignored = ""
        else:
            source = "max_weekly_hours"
            ignored = ""
        print(f"\n  The cap comes from: {source}")
        if ignored:
            print(f"  {ignored}")
            print("  If you edited max_weekly_hours and nothing moved, that is why.")

        theirs = [
            s for s in (roster.get("shifts") or [])
            if s.get("employee_id") == employee_id and s.get("start") and s.get("end")
            and not (s.get("paid_holiday") or s.get("unpaid_holiday") or s.get("sick"))
        ]
        worked = sum(
            paid_hours(s["start"], s["end"], breaks_paid=breaks_paid) for s in theirs
        )
        print(f"\n  rostered this week    : {worked:.1f} paid hours "
              f"over {len(theirs)} shift(s)")
        if cap and worked > cap + 0.01:
            print(f"  --> STILL OVER by {worked - cap:.1f}h, so the caution is "
                  f"CORRECT and current.")
            print(f"      Either raise {source}, or take {worked - cap:.1f}h "
                  f"off their week.")
        else:
            print("  --> within the cap. The audit would NOT flag them.")
            print("      If the page still shows a caution, it is stale:")
            print("      hard-refresh, and if it persists that is an app bug.")

    # Is anything actually disagreeing? The live answer against the one the
    # solver stored when the week was generated.
    live = compliance.under_contract(
        roster.get("shifts") or [],
        employees=employees, shop=shop, week_start=week,
        holidays=await db.holidays.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000),
    )
    stored = roster.get("under_contract") or []
    print(f"\n{'=' * 72}")
    print("  BELOW-CONTRACT PANEL — stored at generation vs derived now")
    print(f"{'=' * 72}")
    print(f"  stored : {sorted(u['name'] for u in stored) or 'nobody'}")
    print(f"  live   : {sorted(u['name'] for u in live) or 'nobody'}")
    if {u["employee_id"] for u in stored} != {u["employee_id"] for u in live}:
        print("\n  They differ — which is the point of deriving it on read.")
        print("  The roster page shows the LIVE list.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--who", required=True, help="part of their name")
    parser.add_argument("--week", help="YYYY-MM-DD, defaults to the newest draft")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.who, args.week))


if __name__ == "__main__":
    main()
