"""How close is the generated week to the one the manager actually wrote?

    python ml/compare_to_manager.py --email you@example.com --week 2026-08-24
    python ml/compare_to_manager.py --email you@example.com          # newest

WHY THIS IS THE ONE THAT COUNTS
-------------------------------
Every other measurement in `ml/` compares the solver against a number the
solver itself produced — coverage against its own demand curve, hours against
an average computed the same way. Those can all agree while the roster is
still wrong, because they share the model's assumptions.

The manager's own approved week does not. He knows things the app cannot see,
and what he wrote is the only external statement of what a right week looks
like for this shop. Where the solver disagrees with him, the solver is
probably wrong.

WHAT IT SHOWS
-------------
The two weeks side by side, then the differences split four ways, because
they mean completely different things:

  SAME          person, day and times all match — nothing to learn
  WRONG PERSON  the shift exists at the right time, somebody else has it
  WRONG TIMES   the right person that day, different hours
  MISSING       he rostered it, the solver did not produce it at all
  INVENTED      the solver produced it, he did not

WRONG PERSON is an ownership or ranking problem. WRONG TIMES is a shape
problem — `day_slots`, stretching, contract fitting. MISSING and INVENTED
together mean the day's shape is wrong rather than its staffing.

The week is held out of its own history, so the solver is never graded on a
week it learned from.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services.demand import build_profile               # noqa: E402
from app.services.hierarchy import sort_employees           # noqa: E402
from app.services.learning import compute_weights, latest_per_week  # noqa: E402
from app.services.scheduler import DAYS, paid_hours, solve_roster  # noqa: E402

Shift = Tuple[str, str, str, str]        # (day, employee_id, start, end)


def _shifts(roster) -> List[Shift]:
    return [
        (s["day"], s["employee_id"], s["start"], s["end"])
        for s in roster.get("shifts") or []
        if s.get("day") and s.get("start") and s.get("end")
        and not (s.get("paid_holiday") or s.get("unpaid_holiday"))
    ]


async def run(email: str, week: str | None) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")
    shop_id = shop["shop_id"]

    approved = latest_per_week(await db.rosters.find(
        {"shop_id": shop_id, "approved": True}, {"_id": 0}).to_list(500))
    if not approved:
        sys.exit("No approved rosters to compare against.")

    if week:
        target = next((r for r in approved if r.get("week_start") == week), None)
        if not target:
            sys.exit(f"No approved roster for {week}. Available: "
                     f"{', '.join(sorted(r['week_start'] for r in approved))}")
    else:
        target = max(approved, key=lambda r: r["week_start"])
        week = target["week_start"]

    employees = await db.employees.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    names = {e["employee_id"]: e.get("name") or e["employee_id"] for e in employees}
    holidays = await db.holidays.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    fixed = await db.fixed_shifts.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    rules = await db.ai_rules.find(
        {"shop_id": shop_id, "enabled": True}, {"_id": 0}).to_list(200)

    history = [r for r in approved if r.get("week_start") != week]
    if len(history) < 4:
        sys.exit("Not enough other approved weeks to solve this one.")

    profile = build_profile(
        shop, history,
        {e["employee_id"]: e.get("role", "") for e in employees},
        for_week=week,
    )
    generated = solve_roster(
        shop, sort_employees(employees, shop), holidays, fixed, rules, week,
        compute_weights(history), profile, history_rosters=history,
    )

    his = _shifts(target)
    ours = _shifts(generated)
    breaks_paid = bool(shop.get("breaks_are_paid"))

    print(f"\n{shop.get('name', '?')} — week of {week}")
    print(f"  manager: {len(his)} shifts   solver: {len(ours)} shifts")

    # ---- the two weeks, side by side --------------------------------------
    print(f"\n{'=' * 78}\nHIS WEEK vs THE SOLVER'S\n{'=' * 78}")
    for day in DAYS:
        theirs = sorted((s for s in his if s[0] == day), key=lambda s: s[2])
        mine = sorted((s for s in ours if s[0] == day), key=lambda s: s[2])
        print(f"\n  {day.upper()}")
        for i in range(max(len(theirs), len(mine))):
            left = (f"{theirs[i][2]}-{theirs[i][3]} "
                    f"{names.get(theirs[i][1], '?')[:14]}" if i < len(theirs)
                    else "")
            right = (f"{mine[i][2]}-{mine[i][3]} "
                     f"{names.get(mine[i][1], '?')[:14]}" if i < len(mine)
                     else "")
            same = "  " if left == right else "≠ "
            print(f"    {same}{left:32}{right}")

    # ---- where they differ, and what kind of difference -------------------
    same = set(his) & set(ours)
    his_left = [s for s in his if s not in same]
    our_left = [s for s in ours if s not in same]

    # Right time, wrong person: the shape exists on the day in both.
    by_shape_his: Dict[tuple, list] = defaultdict(list)
    for day, employee_id, start, end in his_left:
        by_shape_his[(day, start, end)].append(employee_id)
    wrong_person = []
    still_ours = []
    for day, employee_id, start, end in our_left:
        pool = by_shape_his.get((day, start, end))
        if pool:
            wrong_person.append((day, start, end, pool.pop(0), employee_id))
            if not pool:
                by_shape_his.pop((day, start, end))
        else:
            still_ours.append((day, employee_id, start, end))

    # Right person that day, wrong hours.
    his_by_person = defaultdict(list)
    for (day, start, end), people in by_shape_his.items():
        for employee_id in people:
            his_by_person[(day, employee_id)].append((start, end))
    wrong_times = []
    invented = []
    for day, employee_id, start, end in still_ours:
        theirs = his_by_person.get((day, employee_id))
        if theirs:
            was = theirs.pop(0)
            wrong_times.append((day, employee_id, was, (start, end)))
            if not theirs:
                his_by_person.pop((day, employee_id))
        else:
            invented.append((day, employee_id, start, end))
    missing = [(day, employee_id, s, e)
               for (day, employee_id), rest in his_by_person.items()
               for s, e in rest]

    print(f"\n{'=' * 78}\nWHERE THEY DIFFER\n{'=' * 78}")
    total = max(1, len(his))
    print(f"  SAME          {len(same):3}  ({len(same) / total:.0%} of his week)")
    print(f"  WRONG PERSON  {len(wrong_person):3}  right shift, somebody else on it")
    print(f"  WRONG TIMES   {len(wrong_times):3}  right person that day, other hours")
    print(f"  MISSING       {len(missing):3}  he rostered it, the solver did not")
    print(f"  INVENTED      {len(invented):3}  the solver added it, he did not")

    if wrong_person:
        print("\n  WRONG PERSON — an ownership or ranking question:")
        for day, start, end, his_who, our_who in sorted(wrong_person)[:12]:
            print(f"    {day} {start}-{end:8} he had {names.get(his_who,'?')[:14]:16}"
                  f"solver put {names.get(our_who,'?')}")
    if wrong_times:
        print("\n  WRONG TIMES — a shape question (day_slots, stretching, "
              "contract fitting):")
        for day, employee_id, was, now in sorted(wrong_times)[:12]:
            print(f"    {day} {names.get(employee_id,'?')[:14]:16}"
                  f"he had {was[0]}-{was[1]:8} solver {now[0]}-{now[1]}")
    if missing:
        print("\n  MISSING — he rostered these and the solver did not:")
        for day, employee_id, start, end in sorted(missing)[:12]:
            print(f"    {day} {start}-{end:8} {names.get(employee_id,'?')}")
    if invented:
        print("\n  INVENTED — the solver added these and he did not:")
        for day, employee_id, start, end in sorted(invented)[:12]:
            print(f"    {day} {start}-{end:8} {names.get(employee_id,'?')}")

    hours_his = sum(paid_hours(s, e, breaks_paid=breaks_paid)
                    for _, _, s, e in his)
    hours_ours = sum(paid_hours(s, e, breaks_paid=breaks_paid)
                     for _, _, s, e in ours)
    print(f"\n  hours    he wrote {hours_his:6.1f}   solver {hours_ours:6.1f}"
          f"   ({hours_ours - hours_his:+.1f})")

    print(f"\n{'=' * 78}\nWHAT TO READ INTO IT\n{'=' * 78}")
    if len(same) / total >= 0.8:
        print("  The solver reproduces most of his week. What is left is worth")
        print("  looking at one by one rather than as a pattern.")
    elif wrong_person and len(wrong_person) >= len(wrong_times):
        print("  Mostly WRONG PERSON: the shifts are right and the people on")
        print("  them are not. That is ownership and ranking — §2b — not the")
        print("  demand profile.")
    elif wrong_times and len(wrong_times) > len(wrong_person):
        print("  Mostly WRONG TIMES: the right people on the wrong hours. That")
        print("  is the shape of the day — `day_slots`, the stretching pass,")
        print("  contract fitting — not who gets picked.")
    else:
        print("  Mostly MISSING and INVENTED: the days are the wrong SHAPE")
        print("  rather than staffed by the wrong people. Start at")
        print("  check_demand_consistency.py.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--week", help="Monday YYYY-MM-DD; newest if omitted")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.week))


if __name__ == "__main__":
    main()
