"""What does one person actually have a claim on, and what nearly counts?

    python ml/who_owns.py --email you@example.com --employee Emma

WHY
---
Reported twice: "Emma usually works every Monday at 6:00 am, but she was not
rostered at 6:00 at all." Both times `check_why_these_shifts.py` reported
ownership as sound and named no displacement.

Both can be true, because ownership is keyed on the EXACT shape — the tuple
(day, start, end). Somebody who opens at 06:00 every Monday but finishes at
14:00 some weeks and 16:00 others has two half-claims and no whole one, so
`regulars_of` returns nobody and the slot is decided by tie-break. Nothing is
"lost" because nothing was ever owned, and every displacement report stays
silent while the manager watches a settled shift change hands.

Familiarity is keyed on START TIME with a tolerance (§2) precisely because a
person is either there to open or they are not. Ownership is not, and this
script exists to show the difference on real data before anything is changed
about it.

WHAT IT PRINTS
--------------
Every shape this person has worked, with the share that decides ownership,
and then the same counts REGROUPED BY START TIME. If the second table shows
a clear claim where the first does not, that is the gap.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import slot_owners                        # noqa: E402
from app.services.learning import latest_per_week           # noqa: E402


async def run(email: str, who: str, day_filter: str | None) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")

    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}).to_list(1000)
    # An exact name wins outright. Substring matching alone made "Emma"
    # ambiguous with "Emmanuel" and refused to run at all, which is a silly
    # reason to be unable to answer a question about Emma.
    exact = [e for e in employees
             if (e.get("name") or "").lower() == who.lower()]
    match = exact or [e for e in employees
                      if who.lower() in (e.get("name") or "").lower()]
    if not match:
        sys.exit(f"Nobody matching {who!r}. "
                 f"Names: {', '.join(sorted(e.get('name', '?') for e in employees))}")
    if len(match) > 1:
        sys.exit(f"{who!r} matches {len(match)}: "
                 f"{', '.join(e['name'] for e in match)}")
    employee = match[0]
    employee_id = employee["employee_id"]

    approved = await db.rosters.find(
        {"shop_id": shop["shop_id"], "approved": True}, {"_id": 0}).to_list(500)
    weeks = latest_per_week(list(approved))

    # How often each exact shape ran at all, and how often this person was on
    # it — the same two numbers `owner_of` divides.
    ran: Dict[tuple, set] = defaultdict(set)
    theirs: Dict[tuple, int] = defaultdict(int)
    for roster in weeks:
        week = roster.get("week_start")
        for shift in roster.get("shifts") or []:
            if not (shift.get("start") and shift.get("end")
                    and shift.get("day")):
                continue
            if shift.get("paid_holiday") or shift.get("unpaid_holiday") \
                    or shift.get("sick"):
                continue
            key = (shift["day"], shift["start"], shift["end"])
            if day_filter and shift["day"] != day_filter:
                continue
            ran[key].add(week)
            if shift["employee_id"] == employee_id:
                theirs[key] += 1

    print(f"\n{employee['name']} at {shop.get('name', '?')} — "
          f"{len(weeks)} approved weeks"
          + (f", {day_filter} only" if day_filter else ""))

    print(f"\n{'=' * 72}\nBY EXACT SHAPE — this is what ownership uses\n{'=' * 72}")
    print(f"  {'shape':26}{'they worked':>12}{'slot ran':>10}{'share':>8}  owns?")
    rows = sorted(
        ((k, v) for k, v in theirs.items() if v),
        key=lambda kv: (kv[0][0], kv[0][1]),
    )
    if not rows:
        print("  (they have never worked any shape in this window)")
    for (day, start, end), count in rows:
        total = len(ran[(day, start, end)])
        share = count / total if total else 0
        owns = (share >= slot_owners.OWNERSHIP_SHARE
                and total >= slot_owners.MIN_OCCURRENCES)
        print(f"  {day} {start}-{end:14}{count:>12}{total:>10}"
              f"{share:>7.0%}  {'YES' if owns else 'no'}")

    # Regrouped by start time only. Familiarity already works this way (§2)
    # because a person is either there to open or they are not.
    print(f"\n{'=' * 72}\nBY START TIME — what a human would call 'her shift'"
          f"\n{'=' * 72}")
    by_start_ran: Dict[tuple, set] = defaultdict(set)
    by_start_theirs: Dict[tuple, int] = defaultdict(int)
    for (day, start, end), whens in ran.items():
        by_start_ran[(day, start)] |= whens
    for (day, start, end), count in theirs.items():
        by_start_theirs[(day, start)] += count

    print(f"  {'day + start':26}{'they worked':>12}{'ran':>10}{'share':>8}"
          f"  would own?")
    changed = []
    for (day, start), count in sorted(
        ((k, v) for k, v in by_start_theirs.items() if v),
        key=lambda kv: (kv[0][0], kv[0][1]),
    ):
        total = len(by_start_ran[(day, start)])
        share = count / total if total else 0
        would = (share >= slot_owners.OWNERSHIP_SHARE
                 and total >= slot_owners.MIN_OCCURRENCES)
        owns_exact = any(
            c / len(ran[(d, s, e)]) >= slot_owners.OWNERSHIP_SHARE
            and len(ran[(d, s, e)]) >= slot_owners.MIN_OCCURRENCES
            for (d, s, e), c in theirs.items()
            if (d, s) == (day, start) and c
        )
        flag = ""
        if would and not owns_exact:
            flag = "   <<< claim only visible by start time"
            changed.append(f"{day} {start}")
        print(f"  {day} {start:20}{count:>12}{total:>10}{share:>7.0%}"
              f"  {'YES' if would else 'no'}{flag}")

    print(f"\n{'=' * 72}\nVERDICT\n{'=' * 72}")
    if changed:
        print(f"  {len(changed)} shift(s) this person would own if ownership")
        print("  were keyed on START TIME rather than the exact shape:")
        for entry in changed:
            print(f"      {entry}")
        print()
        print("  Their finish varies, so no single shape reaches the bar and")
        print("  `regulars_of` returns nobody. The slot then falls to")
        print("  tie-break, nothing is reported as displaced because nothing")
        print("  was owned, and the manager watches a settled shift change")
        print("  hands while every check says ownership is sound.")
    else:
        print("  Ownership by exact shape and by start time agree for this")
        print("  person. If a shift of theirs still changed hands, the cause")
        print("  is elsewhere — check_why_these_shifts.py names displacements")
        print("  and their reasons.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--employee", required=True, help="name, or part of it")
    parser.add_argument("--day", help="mon..sun, to narrow the output")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.employee,
                    args.day.lower()[:3] if args.day else None))


if __name__ == "__main__":
    main()
