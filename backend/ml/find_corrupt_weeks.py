"""Find approved weeks that cannot physically have happened.

    python ml/find_corrupt_weeks.py --email you@example.com            # dry run
    python ml/find_corrupt_weeks.py --email you@example.com --commit   # unapprove

WHY THIS EXISTS
---------------
A multi-week spreadsheet imported before `parse_sheet_weeks` could find more
than one header row arrives as ONE week holding four or five weeks of shifts.
The parser is fixed; the data it already wrote is not, and it stays in the
history where every learned thing reads it:

  * `demand.py` learns the day's shape from it and believes the shop runs
    four times the staff it does
  * `slot_owners.py` counts one week's occurrences several times over
  * `learning.py` weights it as a single recent week, so it pulls hard
  * any hours-per-week average is dragged up by a figure nobody worked

The signature is unmistakable — one person credited with more hours than
there are in a week. At the reference shop: 148.5 hours, which is 21 hours a
day for seven days.

WHAT IT DOES ABOUT IT
---------------------
Unapproves, never deletes. §3 makes that the designed mechanism: approving is
what puts a week into the learning, so clearing the flag IS the unlearn, and
nothing is cached that could survive it. The roster stays in the database and
can be approved again if this script is wrong about it.

The UI cannot do this — a week that has already finished is a record and
cannot be reopened there — which is the only reason this exists as a script.

DRY RUN BY DEFAULT. `--commit` to apply.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services.scheduler import paid_hours               # noqa: E402

# Nobody works more than this in a week. The Organisation of Working Time Act
# caps the average at 48; anything past 60 is not a long week, it is several
# weeks stacked on one date.
IMPOSSIBLE_WEEKLY_HOURS = 60.0
# Seven days is the whole week. More rows than that for one person means the
# same weekday appears twice, which one week cannot contain.
IMPOSSIBLE_DAYS = 7


async def run(email: str, commit: bool) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")

    breaks_paid = bool(shop.get("breaks_are_paid"))
    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}).to_list(1000)
    names = {e["employee_id"]: e.get("name") or e["employee_id"] for e in employees}

    approved = await db.rosters.find(
        {"shop_id": shop["shop_id"], "approved": True}, {"_id": 0}
    ).to_list(500)

    suspect: List[Dict[str, Any]] = []
    for roster in approved:
        hours: Dict[str, float] = defaultdict(float)
        days: Dict[str, List[str]] = defaultdict(list)
        for shift in roster.get("shifts") or []:
            if not (shift.get("start") and shift.get("end")):
                continue
            if shift.get("paid_holiday") or shift.get("unpaid_holiday"):
                continue
            employee_id = shift["employee_id"]
            hours[employee_id] += paid_hours(
                shift["start"], shift["end"], breaks_paid=breaks_paid)
            days[employee_id].append(shift["day"])

        reasons = []
        for employee_id, worked in hours.items():
            if worked > IMPOSSIBLE_WEEKLY_HOURS:
                reasons.append(
                    f"{names.get(employee_id, employee_id)} credited with "
                    f"{worked:.1f}h — more than a week contains")
        for employee_id, worked_days in days.items():
            if len(worked_days) > IMPOSSIBLE_DAYS:
                reasons.append(
                    f"{names.get(employee_id, employee_id)} has "
                    f"{len(worked_days)} shifts across a 7-day week")
        if reasons:
            suspect.append({"roster": roster, "reasons": reasons,
                            "hours": hours})

    print(f"\n{shop.get('name', '?')} — {len(approved)} approved weeks")
    if not suspect:
        print("\n  Nothing impossible found. The history is physically "
              "plausible.")
        print("  Note this checks only what CANNOT have happened — it does")
        print("  not verify that what remains is correct.")
        return

    print(f"\n  {len(suspect)} week(s) could not have happened:\n")
    for entry in suspect:
        roster = entry["roster"]
        print(f"  {roster.get('week_start')}  "
              f"({len(roster.get('shifts') or [])} shifts)")
        for reason in entry["reasons"]:
            print(f"      {reason}")
        biggest = sorted(entry["hours"].items(), key=lambda kv: -kv[1])[:3]
        rough = max(1, round(biggest[0][1] / 35)) if biggest else 1
        print(f"      looks like roughly {rough} weeks stacked on one date")
        print()

    if not commit:
        print("  DRY RUN — nothing changed.")
        print("  Re-run with --commit to unapprove these weeks, which takes")
        print("  them out of the learning without deleting anything. They")
        print("  can be approved again if this is wrong about them.")
        return

    for entry in suspect:
        roster = entry["roster"]
        await db.rosters.update_one(
            {"shop_id": shop["shop_id"], "roster_id": roster["roster_id"]},
            {"$set": {"approved": False,
                      "unapproved_reason": "impossible hours — likely a "
                                           "multi-week import"}},
        )
        print(f"  unapproved {roster.get('week_start')}")
    print(f"\n  {len(suspect)} week(s) unapproved. Nothing was deleted.")
    print("  Re-generate to see the profile learned without them.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--commit", action="store_true",
                        help="apply the change; omit for a dry run")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.commit))


if __name__ == "__main__":
    main()
