"""Does a group of people take turns having the weekend off?

    python ml/check_rotation.py --email you@example.com \
        --group "Martin,Corey,Jithin"

WHY
---
The manager, asked how he rosters:

    "If Martin is off for the weekend, then Corey and Jithin will be
     working. If Corey is off, then Martin and Jithin will be working. If
     Jithin is off, Corey and Martin will be working, and it goes on week
     after week. There is a combination to give a weekend off because they
     are on contract. They deserve this."

The app has no way to express that. `preferred_days_off` is static, and every
custom rule (`max_staff`, `not_together`, `no_open`, ...) is answerable from
the week being built. A rotation depends on PREVIOUS weeks — whose turn it is
comes from history — so it would be the first cross-week constraint.

Before building one, the question is whether the pattern is real. What the
manager describes may be what he intends rather than what he does, and those
need different answers: a detected rule can be proposed to him, an intended
one has to be configured.

WHAT A NON-ZERO ANSWER LOOKS LIKE, STATED BEFORE RUNNING
--------------------------------------------------------
The rotation HOLDS if most weekends have exactly one of the group off, and
the person off changes from weekend to weekend in a way that gives each of
them a turn.

It does NOT hold if weekends routinely have two off or none off, or if the
same person is off most weekends — that is a fixed arrangement, not a
rotation, and `preferred_days_off` already covers it.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services.learning import latest_per_week           # noqa: E402


async def run(email: str, names: List[str], days: List[str]) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")

    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}).to_list(1000)
    by_name = {(e.get("name") or "").lower(): e for e in employees}
    group = []
    for name in names:
        match = by_name.get(name.strip().lower())
        if not match:
            sys.exit(f"No employee called {name!r}. "
                     f"Names: {', '.join(sorted(e.get('name', '?') for e in employees))}")
        group.append(match)
    ids = {e["employee_id"]: e.get("name") for e in group}

    approved = latest_per_week(await db.rosters.find(
        {"shop_id": shop["shop_id"], "approved": True}, {"_id": 0}
    ).to_list(500))
    weeks = sorted(approved, key=lambda r: r.get("week_start") or "")
    if not weeks:
        sys.exit("No approved rosters to look at.")

    print(f"\n{shop.get('name', '?')} — {len(weeks)} approved weeks")
    print(f"Group: {', '.join(ids.values())}   weekend = {', '.join(days)}\n")
    print(f"  {'week':12}" + "".join(f"{n[:9]:>11}" for n in ids.values())
          + "   who was off")
    print("  " + "-" * (12 + 11 * len(ids) + 16))

    off_counts: Counter = Counter()
    pattern: List[str] = []
    exactly_one = 0
    counted = 0
    for roster in weeks:
        shifts = roster.get("shifts") or []

        # A WEEK ONLY COUNTS IF ALL OF THEM WERE THERE.
        #
        # Somebody who had not joined yet appears as "off" every weekend,
        # and the first version of this counted that as them taking their
        # turn: Jithin showed 13 weekends off against Corey's 3, purely
        # because he was hired in June. The same applies to a full week of
        # leave. Neither is a turn in a rotation.
        present = {
            employee_id: any(
                s.get("employee_id") == employee_id
                and s.get("start") and s.get("end")
                for s in shifts
            )
            for employee_id in ids
        }
        if not all(present.values()):
            absent = [ids[e] for e, p in present.items() if not p]
            print(f"  {roster.get('week_start', '?'):12}"
                  + "".join(f"{'—':>11}" for _ in ids)
                  + f"   skipped: {', '.join(absent)} not working this week")
            continue
        counted += 1

        worked: Dict[str, bool] = {}
        for employee_id in ids:
            worked[employee_id] = any(
                s.get("employee_id") == employee_id
                and s.get("day") in days
                and s.get("start") and s.get("end")
                and not (s.get("paid_holiday") or s.get("unpaid_holiday"))
                for s in shifts
            )
        off = [ids[e] for e, w in worked.items() if not w]
        if len(off) == 1:
            exactly_one += 1
            off_counts[off[0]] += 1
            pattern.append(off[0])
        cells = "".join(
            f"{('work' if worked[e] else 'OFF'):>11}" for e in ids)
        note = ", ".join(off) if off else "nobody"
        print(f"  {roster.get('week_start', '?'):12}{cells}   {note}")

    print(f"\n{'=' * 70}\nVERDICT\n{'=' * 70}")
    skipped = len(weeks) - counted
    if skipped:
        print(f"  {skipped} week(s) skipped — not all of them were working "
              f"yet, so those\n  weekends say nothing about whose turn it "
              f"was.")
    if not counted:
        print("  No week has all of them working. Nothing to measure.")
        return
    print(f"  weekends with exactly one of them off: "
          f"{exactly_one} of {counted}")
    for name, count in off_counts.most_common():
        print(f"      {name:12}{count:>3} weekends off")

    print()
    if exactly_one < counted * 0.6:
        print("  NOT A ROTATION. Most weekends do not have exactly one of")
        print("  them off, so what the manager described is what he intends")
        print("  rather than what the rosters show. A rule for it would have")
        print("  to be CONFIGURED by him, not detected — which is fine, but")
        print("  it cannot be proposed from evidence.")
    elif len(off_counts) < len(ids):
        missing = [n for n in ids.values() if n not in off_counts]
        print(f"  PARTIAL. One of them is off most weekends, but "
              f"{', '.join(missing)} never")
        print("  gets a turn. That is a fixed arrangement rather than a")
        print("  rotation, and `preferred_days_off` already expresses it.")
    else:
        spread = max(off_counts.values()) - min(off_counts.values())
        print("  IT HOLDS. Exactly one of them is off on most weekends and")
        print("  every one of them gets turns.")
        print(f"  Turns are spread within {spread} weekend(s) of each other.")
        print()
        print("  So the rule can be DETECTED and proposed to him rather than")
        print("  configured from scratch — the same flow as 'make this a")
        print("  fixed shift'. Whose turn it is next: whoever has gone")
        print("  longest without one, derived from history each solve.")
        if len(pattern) >= 6:
            print(f"\n  Recent order: {' -> '.join(pattern[-6:])}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--group", required=True,
                        help="comma-separated names, e.g. 'Martin,Corey,Jithin'")
    parser.add_argument("--days", default="sat,sun",
                        help="which days count as the weekend")
    args = parser.parse_args()
    asyncio.run(run(
        args.email,
        [n for n in args.group.split(",") if n.strip()],
        [d.strip().lower()[:3] for d in args.days.split(",") if d.strip()],
    ))


if __name__ == "__main__":
    main()
