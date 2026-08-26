"""Is the running app using the current solver?

WHY THIS EXISTS
---------------
"I regenerated and nothing changed" has two very different causes, and they
look identical from the screen:

  1. the solver is DETERMINISTIC — same inputs, same roster, every time. Two
     regenerations of an unchanged week are supposed to match.
  2. the app is running stale code, so a fix that works in a fresh process
     never reaches the roster the app writes.

This tells them apart. It solves the week in THIS process with the code on
disk, then compares against the roster the app last saved. Same result means
the app is current; different means it is not, and it prints what changed.

    python ml/check_live_code.py --email you@example.com --week 2026-08-31
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                        # noqa: E402
from app.services.demand import build_profile             # noqa: E402
from app.services.hierarchy import sort_employees         # noqa: E402
from app.services.learning import compute_weights         # noqa: E402
from app.services.scheduler import solve_roster           # noqa: E402


def _key(shifts):
    return sorted(
        (s.get("employee_id"), s.get("day"), s.get("start"), s.get("end"))
        for s in shifts
    )


def _print_day(day: str, saved, fresh, names) -> None:
    """One day from both rosters, side by side.

    A diff shows what moved but not what the day now looks like, and "who
    ended up on this slot instead" is usually the real question.
    """
    if not day:
        return
    print(f"\n{'=' * 62}\n{day.upper()} side by side\n{'=' * 62}")
    for label, shifts in (("SAVED", saved), ("FRESH", fresh)):
        rows = sorted(
            (s for s in shifts if s.get("day") == day and s.get("start")),
            key=lambda s: (s["start"], s["end"]),
        )
        print(f"\n  {label}  ({len(rows)} on)")
        for s in rows:
            flag = " FIXED" if s.get("fixed") else ""
            print(f"    {s['start']}-{s['end']:<6} "
                  f"{names.get(s['employee_id'], s['employee_id'])}{flag}")

    on_day = lambda rows: {  # noqa: E731
        s["employee_id"] for s in rows if s.get("day") == day and s.get("start")
    }
    dropped = on_day(saved) - on_day(fresh)
    if dropped:
        print(f"\n  dropped from {day}: "
              f"{', '.join(sorted(names.get(m, m) for m in dropped))}")


async def main(email: str, week: str, day_filter: str = "") -> int:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        print(f"No account for {email}")
        return 1
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    shop_id = shop["shop_id"]

    stored = await db.rosters.find_one(
        {"shop_id": shop_id, "week_start": week, "historical": {"$ne": True}},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if not stored:
        print(f"No saved roster for {week}. Generate one in the app first.")
        return 1

    employees = await db.employees.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    holidays = await db.holidays.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    fixed = await db.fixed_shifts.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    rules = await db.ai_rules.find(
        {"shop_id": shop_id, "enabled": True}, {"_id": 0}
    ).to_list(200)
    approved = await db.rosters.find(
        {"shop_id": shop_id, "approved": True}, {"_id": 0}
    ).to_list(500)

    fresh = solve_roster(
        shop, sort_employees(employees, shop), holidays, fixed, rules, week,
        compute_weights(approved), build_profile(
            shop, approved, {e["employee_id"]: e.get("role", "") for e in employees}
        ),
        history_rosters=approved,
    )

    names = {e["employee_id"]: e.get("name", e["employee_id"]) for e in employees}
    saved_key, fresh_key = _key(stored.get("shifts", [])), _key(fresh["shifts"])

    print(f"\nsaved   {stored.get('version')}  "
          f"{len(stored.get('shifts', []))} shifts")
    print(f"fresh   this process, current code on disk  "
          f"{len(fresh['shifts'])} shifts\n")

    if saved_key == fresh_key:
        print("IDENTICAL — the app is running the current code.")
        print("Regenerating cannot change this week: the solver is")
        print("deterministic, so the same inputs always give the same roster.")
        print("To change it, change an input — edit a shift and Rebalance,")
        print("or adjust hours, leave, or days off.")
        # --day still prints. Confirming the app is current is usually the
        # start of the question, not the end of it: the next thing asked is
        # always "so why is this day wrong".
        _print_day(day_filter, stored.get("shifts", []), fresh["shifts"], names)
        return 0

    print("DIFFERENT — the app saved a roster the current code would not produce.")
    print("That means the running app is on older code. Stop it fully and")
    print("restart; a warm --reload process does not always pick up a NEW")
    print("module, and slot_owners.py is new.\n")

    only_saved = [s for s in saved_key if s not in set(fresh_key)]
    only_fresh = [s for s in fresh_key if s not in set(saved_key)]

    print(f"in the saved roster but not the fresh one ({len(only_saved)}):")
    for eid, day, start, end in only_saved[:12]:
        print(f"    {names.get(eid, eid):12} {day} {start}-{end}")
    print(f"\nin the fresh roster but not the saved one ({len(only_fresh)}):")
    for eid, day, start, end in only_fresh[:12]:
        print(f"    {names.get(eid, eid):12} {day} {start}-{end}")

    _print_day(day_filter, stored.get("shifts", []), fresh["shifts"], names)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--week", required=True, help="Monday, YYYY-MM-DD")
    parser.add_argument("--day", default="",
                        help="mon..sun — print that day in full from both")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.email, args.week, args.day)))
