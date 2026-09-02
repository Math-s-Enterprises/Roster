"""Arrivals against shapes, on every week the shop has approved.

    python ml/check_arrivals_ab.py --email you@example.com
    python ml/check_arrivals_ab.py --email you@example.com --weeks 8

WHY AN A/B AND NOT A READING
----------------------------
`check_arrivals.py` asks whether the shape list starts the right NUMBER of
people each hour, and answers from the profile alone. It says the model is
worth building; it cannot say the roster got better, because a model can be
more truthful and still produce a week the manager likes less.

So this solves each week twice — once with `_RosterBuilder.USE_ARRIVALS`
on, once off — and scores both against the week the manager actually
approved. Every week is held out of its own history, so neither model is
ever graded on a week it learned from.

THE BAR, STATED BEFORE THE MODEL WAS BUILT
-------------------------------------------
    "arrivals difference falls substantially AND exact matches don't drop.
     If matches fall, revert — a model that is theoretically right and
     reproduces your manager worse is not an improvement."

Both halves are printed, per week and in total, and the verdict below
applies that bar rather than a fresh one invented after seeing the numbers.

WHAT THE COLUMNS MEAN
---------------------
  exact      person, day, start and finish all match the manager
  person     the shift exists at the right time, somebody else has it
  times      the right person that day, different hours
  arrivals   total absolute difference between how many people the manager
             starts each hour and how many the solver does, summed over the
             week. This is the quantity the arrivals model optimises, so it
             is expected to fall — it is reported to show BY HOW MUCH, not
             as evidence on its own.

`exact` is the honest score. Arrivals is the mechanism.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services.demand import build_profile               # noqa: E402
from app.services.hierarchy import sort_employees           # noqa: E402
from app.services.learning import (                         # noqa: E402
    compute_weights, latest_per_week,
)
from app.services.scheduler import (                         # noqa: E402
    _RosterBuilder, solve_roster, to_minutes,
)

Shift = Tuple[str, str, str, str]        # (day, employee_id, start, end)


def _shifts(roster) -> List[Shift]:
    return [
        (s["day"], s["employee_id"], s["start"], s["end"])
        for s in roster.get("shifts") or []
        if s.get("day") and s.get("start") and s.get("end")
        and not (s.get("paid_holiday") or s.get("unpaid_holiday"))
    ]


def _arrivals(shifts: List[Shift]) -> Dict[Tuple[str, int], int]:
    out: Dict[Tuple[str, int], int] = defaultdict(int)
    for day, _who, start, _end in shifts:
        out[(day, to_minutes(start) // 60)] += 1
    return out


def _score(his: List[Shift], ours: List[Shift]) -> Dict[str, int]:
    """Exact / wrong-person / wrong-times, and the arrivals distance."""
    same = set(his) & set(ours)
    his_left = [s for s in his if s not in same]
    our_left = [s for s in ours if s not in same]

    by_shape: Dict[Tuple[str, str, str], List[Shift]] = defaultdict(list)
    for shift in his_left:
        by_shape[(shift[0], shift[2], shift[3])].append(shift)
    wrong_person = 0
    for shift in our_left:
        bucket = by_shape.get((shift[0], shift[2], shift[3]))
        if bucket:
            bucket.pop()
            wrong_person += 1

    by_person: Dict[Tuple[str, str], List[Shift]] = defaultdict(list)
    for shift in his_left:
        if shift not in {s for b in by_shape.values() for s in b}:
            continue
        by_person[(shift[0], shift[1])].append(shift)
    wrong_times = 0
    for shift in our_left:
        bucket = by_person.get((shift[0], shift[1]))
        if bucket:
            bucket.pop()
            wrong_times += 1

    mine, theirs = _arrivals(ours), _arrivals(his)
    distance = sum(
        abs(mine.get(key, 0) - theirs.get(key, 0))
        for key in set(mine) | set(theirs)
    )
    return {
        "exact": len(same), "person": wrong_person, "times": wrong_times,
        "arrivals": distance, "his": len(his), "ours": len(ours),
    }


async def run(email: str, limit: int | None) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")
    shop_id = shop["shop_id"]

    approved = latest_per_week(await db.rosters.find(
        {"shop_id": shop_id, "approved": True}, {"_id": 0}).to_list(500))
    if len(approved) < 6:
        sys.exit("Needs at least 6 approved weeks — one to grade, five to "
                 "learn from.")

    employees = await db.employees.find(
        {"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    holidays = await db.holidays.find(
        {"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    fixed = await db.fixed_shifts.find(
        {"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    rules = await db.ai_rules.find(
        {"shop_id": shop_id, "enabled": True}, {"_id": 0}).to_list(200)
    team = sort_employees(employees, shop)
    roles = {e["employee_id"]: e.get("role", "") for e in employees}

    weeks = sorted(approved, key=lambda r: r["week_start"])
    if limit:
        weeks = weeks[-limit:]

    print(f"\n{shop.get('name', '?')} — {len(weeks)} weeks, each solved twice "
          f"and held out of its own history\n")
    print(f"  {'week':12}  {'manager':>8}   {'ARRIVALS MODEL':>33}"
          f"   {'SHAPE LIST':>33}")
    print(f"  {'':12}  {'shifts':>8}   "
          f"{'shifts':>7}{'exact':>6}{'person':>7}{'times':>6}{'arr':>7}   "
          f"{'shifts':>7}{'exact':>6}{'person':>7}{'times':>6}{'arr':>7}")

    totals: Dict[str, Dict[str, int]] = {
        "arrivals": defaultdict(int), "shapes": defaultdict(int)}
    graded = 0

    for target in weeks:
        week = target["week_start"]
        history = [r for r in approved if r.get("week_start") != week]
        if len(history) < 4:
            continue
        profile = build_profile(shop, history, roles, for_week=week)
        weights = compute_weights(history)
        his = _shifts(target)

        row: Dict[str, Dict[str, int]] = {}
        for name, flag in (("arrivals", True), ("shapes", False)):
            original = _RosterBuilder.USE_ARRIVALS
            _RosterBuilder.USE_ARRIVALS = flag
            try:
                generated = solve_roster(
                    shop, team, holidays, fixed, rules, week, weights,
                    profile, history_rosters=history,
                )
            finally:
                _RosterBuilder.USE_ARRIVALS = original
            row[name] = _score(his, _shifts(generated))
            for key, value in row[name].items():
                totals[name][key] += value

        graded += 1
        a, s = row["arrivals"], row["shapes"]
        print(f"  {week:12}  {a['his']:>8}   "
              f"{a['ours']:>7}{a['exact']:>6}{a['person']:>7}"
              f"{a['times']:>6}{a['arrivals']:>7}   "
              f"{s['ours']:>7}{s['exact']:>6}{s['person']:>7}"
              f"{s['times']:>6}{s['arrivals']:>7}")

    if not graded:
        sys.exit("Nothing gradeable.")

    a, s = totals["arrivals"], totals["shapes"]
    print(f"\n  {'TOTAL':12}  {a['his']:>8}   "
          f"{a['ours']:>7}{a['exact']:>6}{a['person']:>7}{a['times']:>6}"
          f"{a['arrivals']:>7}   "
          f"{s['ours']:>7}{s['exact']:>6}{s['person']:>7}{s['times']:>6}"
          f"{s['arrivals']:>7}")
    print(f"  {graded} weeks")
    print(f"\n  Shifts produced, against the manager's {a['his']}:")
    print(f"    arrivals model {a['ours']}  ({a['ours'] - a['his']:+d})")
    print(f"    shape list     {s['ours']}  ({s['ours'] - a['his']:+d})")
    if abs(a["ours"] - s["ours"]) >= 20:
        print("\n  The two models are building weeks of DIFFERENT SIZES. That")
        print("  is upstream of who gets which shift: compare the day totals")
        print("  with --explain before reading anything into exact matches.")

    print(f"\n{'=' * 78}\nVERDICT — against the bar set before the model was "
          f"built\n{'=' * 78}")
    exact_delta = a["exact"] - s["exact"]
    arr_delta = s["arrivals"] - a["arrivals"]
    arr_pct = (arr_delta / s["arrivals"] * 100) if s["arrivals"] else 0.0

    print(f"  exact matches      {s['exact']} -> {a['exact']}  "
          f"({exact_delta:+d})")
    print(f"  arrivals distance  {s['arrivals']} -> {a['arrivals']}  "
          f"({-arr_delta:+d}, {arr_pct:.0f}% closer)")
    print()
    if exact_delta < 0:
        print("  REVERT. Exact matches fell. The bar was explicit that a model")
        print("  which is theoretically right and reproduces the manager worse")
        print("  is not an improvement. Set USE_ARRIVALS = False and keep the")
        print("  measurement — the model is not wrong, but it is not ready.")
    elif arr_delta <= 0:
        print("  REVERT. The arrivals distance did not fall, which is the one")
        print("  thing this model exists to fix. If it cannot do that on real")
        print("  data, the fault is upstream of the fill — check")
        print("  `check_arrivals.py` and whether the weeks imported cleanly.")
    else:
        print("  KEEP. The distance the model targets fell and the manager is")
        print("  reproduced no worse.")
        if exact_delta == 0:
            print()
            print("  Note honestly: exact matches did NOT rise. The win here is")
            print("  the hourly shape, not closer agreement shift-by-shift.")
            print("  Whether that is worth a model change is a judgement for")
            print("  the shop owner, not for this script.")


async def explain(email: str, week: str) -> None:
    """Hour by hour for one week: learned, placed, and what he wrote.

    The A/B says arrivals reproduces the manager worse AND does not move the
    arrivals distance. The second half is the one that does not add up: the
    day is built by asking how many people start each hour and placing that
    many, so the distance should fall by construction.

    So this prints the chain the number travels along:

      his        how many people the manager started that hour, that week
      learned    what `demand.starting_at` says, from the other 30 weeks
      placed     how many the arrivals fill actually put on
      shapes     how many the shape list put on, for comparison

    `learned` vs `placed` is the diagnostic. If they agree, the model is
    working and simply describes this shop worse than shapes do — a real
    finding, and the end of it. If they DISAGREE, the fill is losing slots it
    asked for, and the fault is a bug rather than a model.
    """
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")
    shop_id = shop["shop_id"]

    approved = latest_per_week(await db.rosters.find(
        {"shop_id": shop_id, "approved": True}, {"_id": 0}).to_list(500))
    target = next((r for r in approved if r.get("week_start") == week), None)
    if not target:
        sys.exit(f"No approved roster for {week}. Available: "
                 f"{', '.join(sorted(r['week_start'] for r in approved))}")

    employees = await db.employees.find(
        {"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    holidays = await db.holidays.find(
        {"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    fixed = await db.fixed_shifts.find(
        {"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    rules = await db.ai_rules.find(
        {"shop_id": shop_id, "enabled": True}, {"_id": 0}).to_list(200)
    team = sort_employees(employees, shop)

    history = [r for r in approved if r.get("week_start") != week]
    profile = build_profile(
        shop, history,
        {e["employee_id"]: e.get("role", "") for e in employees},
        for_week=week)
    weights = compute_weights(history)

    placed = {}
    for name, flag in (("arrivals", True), ("shapes", False)):
        original = _RosterBuilder.USE_ARRIVALS
        _RosterBuilder.USE_ARRIVALS = flag
        try:
            placed[name] = _arrivals(_shifts(solve_roster(
                shop, team, holidays, fixed, rules, week, weights, profile,
                history_rosters=history)))
        finally:
            _RosterBuilder.USE_ARRIVALS = original

    his = _arrivals(_shifts(target))

    print(f"\n{shop.get('name', '?')} — week of {week}")
    print("How many people START each hour.\n")
    print(f"  {'':4}{'hour':>6}{'his':>6}{'learned':>9}{'placed':>8}"
          f"{'shapes':>8}   note")

    mismatched = 0
    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        hours = sorted({h for d, h in set(his) | set(placed["arrivals"])
                        | set(placed["shapes"]) if d == day}
                       | {h for h in range(24)
                          if profile.starting_at(day, h)})
        if not hours:
            continue
        print(f"\n  {day.upper()}")
        for hour in hours:
            learned = profile.starting_at(day, hour)
            mine = placed["arrivals"].get((day, hour), 0)
            theirs = placed["shapes"].get((day, hour), 0)
            wrote = his.get((day, hour), 0)
            note = ""
            if learned != mine:
                note = f"<<< asked for {learned}, placed {mine}"
                mismatched += 1
            print(f"  {'':4}{hour:>4}:00{wrote:>6}{learned:>9}{mine:>8}"
                  f"{theirs:>8}   {note}")

    print(f"\n{'=' * 72}")
    if mismatched:
        print(f"  {mismatched} hours where the fill placed a different number")
        print("  from the one it learned. THAT is the bug — the model is not")
        print("  being asked the question it answers. Fix the fill before")
        print("  judging the model.")
    else:
        print("  The fill placed exactly what it learned, everywhere.")
        print("  So the model is working as designed and simply describes")
        print("  this shop worse than the shape list does. That is a real")
        print("  finding and the end of it: keep USE_ARRIVALS off.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--weeks", type=int,
                        help="grade only the most recent N weeks")
    parser.add_argument("--explain", metavar="YYYY-MM-DD",
                        help="one week, hour by hour: learned vs placed")
    args = parser.parse_args()
    if args.explain:
        asyncio.run(explain(args.email, args.explain))
    else:
        asyncio.run(run(args.email, args.weeks))


if __name__ == "__main__":
    main()
