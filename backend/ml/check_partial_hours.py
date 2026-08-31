"""How much coverage the hour-rounding is inventing.

    python ml/check_partial_hours.py --email you@example.com

WHY
---
`hours_covered` walks a shift in 60-minute steps FROM ITS START MINUTE and
floors each step to an hour:

    for minute in range(start_m, end_m, 60):
        covered.add((day, (minute // 60) % 24))

So a shift beginning 17:30 is credited with hour 17 — the whole 17:00-18:00
block — on the strength of being there for half of it. That is how a
gap-closing stretch from 18:00 to 17:30 "covers wed 17:00" while the shop is
genuinely empty from 17:00 to 17:30.

Rule 1 is that somebody is on the floor from open to close, and §1 says never
to invent coverage that cannot be staffed. This measures how much is being
invented before anybody changes the model, because the fix is only worth its
risk if the number is real.

WHAT IT MEASURES
----------------
Two different things, deliberately kept apart:

  MODEL      what the solver believes, via hours_covered
  REALITY    minute-by-minute headcount, built from the same shifts

An hour is INVENTED when the model calls it covered and reality has at least
one minute in it with nobody in the shop. That is the only figure that
matters: an hour credited to a 17:30 start is harmless if a colleague is
standing there 17:00-17:30, and it is a real hole if not.

Reported per week and totalled, alongside how many shifts even start or end
off the hour — if that is near zero the whole question is theoretical for
this shop.

MEASURE THE RIGHT ROSTERS
-------------------------
The first version of this script defaulted to APPROVED weeks and reported a
confident zero. That answer was worthless, and the shop owner spotted why:
approved weeks at the reference shop are the manager's own hand-built rota,
which is continuous by construction. There were no holes to invent, so zero
was guaranteed before the script ran.

The rounding is only exploited by the SOLVER — `_close_short_hours` is what
stretches a finish by thirty minutes and then believes the hour is covered.
So `--source` decides what is measured, and the default is the solver:

    generated   drafts the solver produced (default)
    approved    the manager's own rota — the control, expected to be clean
    solve       re-solve each week from scratch and measure that

`solve` is the strongest: it measures today's code rather than whatever
version produced a stored draft.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services.learning import latest_per_week           # noqa: E402
from app.services.scheduler import (                        # noqa: E402
    DAYS,
    _RosterBuilder,
    to_minutes,
)

WEEK_MINUTES = 7 * 24 * 60


def _is_leave(shift: Dict[str, Any]) -> bool:
    return bool(shift.get("paid_holiday") or shift.get("unpaid_holiday")
                or shift.get("sick"))


def _headcount_by_minute(shifts: List[Dict[str, Any]]) -> List[int]:
    """People in the shop for every minute of the week.

    The ground truth this whole script compares against. Overnight shifts wrap
    into the next day and Sunday night wraps to Monday, matching
    hours_covered(wrap_week=True) so the two are measuring the same week.
    """
    minutes = [0] * WEEK_MINUTES
    for shift in shifts:
        if _is_leave(shift) or not (shift.get("start") and shift.get("end")):
            continue
        try:
            day_index = DAYS.index(shift["day"])
        except ValueError:
            continue
        start = day_index * 1440 + to_minutes(shift["start"])
        end = day_index * 1440 + to_minutes(shift["end"])
        if end <= start:
            end += 1440
        for m in range(start, end):
            minutes[m % WEEK_MINUTES] += 1
    return minutes


def _open_minutes(shop: Dict[str, Any]) -> List[bool]:
    """Which minutes the shop is trading. Everything else cannot have a gap."""
    if shop.get("open_24h"):
        return [True] * WEEK_MINUTES
    open_flags = [False] * WEEK_MINUTES
    by_day = {h.get("day"): h for h in shop.get("hours") or []}
    for index, day in enumerate(DAYS):
        hours = by_day.get(day)
        if not hours or hours.get("closed"):
            continue
        start = index * 1440 + to_minutes(hours.get("open") or "00:00")
        end = index * 1440 + to_minutes(hours.get("close") or "00:00")
        if end <= start:
            end += 1440
        for m in range(start, end):
            open_flags[m % WEEK_MINUTES] = True
    return open_flags


async def _solve_recent(shop, approved, weeks):
    """Re-solve the most recent weeks with today's code and return the output.

    The strongest source: a stored draft was produced by whatever version of
    the solver was running that day, and the question is about the solver as
    it stands now.
    """
    from app.services.demand import build_profile
    from app.services.hierarchy import sort_employees
    from app.services.learning import compute_weights
    from app.services.scheduler import solve_roster

    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}).to_list(1000)
    ids = {e["employee_id"] for e in employees}
    holidays = await db.holidays.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}).to_list(1000)
    fixed = [f for f in await db.fixed_shifts.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}).to_list(1000)
        if f["employee_id"] in ids]
    rules = await db.ai_rules.find(
        {"shop_id": shop["shop_id"], "enabled": True}, {"_id": 0}).to_list(200)
    ordered = sort_employees(employees, shop)
    weights = compute_weights(approved)

    out = []
    targets = sorted({r["week_start"] for r in approved}, reverse=True)[:weeks]
    for week in targets:
        # History EXCLUDING the week being rebuilt, so the solver is not
        # handed the answer it is being asked to produce.
        history = [r for r in approved if r.get("week_start") != week]
        profile = build_profile(
            shop, history,
            {e["employee_id"]: e.get("role", "") for e in employees},
            for_week=week,
        )
        result = solve_roster(
            shop, ordered, holidays, fixed, rules, week,
            weights, profile, history_rosters=history, seed=1234,
        )
        out.append({"week_start": week, "shifts": result["shifts"]})
        print(f"  solved {week} — {len(result['shifts'])} shifts", flush=True)
    return out


async def run(email: str, weeks: int, source: str) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")

    approved = await db.rosters.find(
        {"shop_id": shop["shop_id"], "approved": True}, {"_id": 0}
    ).to_list(500)

    if source == "approved":
        rosters = sorted(latest_per_week(approved),
                         key=lambda r: r.get("week_start", ""), reverse=True)[:weeks]
        label = ("the manager's own rota — the CONTROL. A hand-built rota on a "
                 "24h shop\nis continuous by construction, so a clean result "
                 "here proves nothing about\nthe solver.")
    elif source == "solve":
        print("Re-solving with today's code — this takes a moment.")
        rosters = await _solve_recent(shop, approved, weeks)
        label = "freshly solved by TODAY's code — the real question"
    else:
        drafts = await db.rosters.find(
            {"shop_id": shop["shop_id"], "approved": {"$ne": True},
             "historical": {"$ne": True}}, {"_id": 0}
        ).to_list(500)
        rosters = sorted(drafts, key=lambda r: (r.get("week_start", ""),
                                                r.get("created_at", "")),
                         reverse=True)[:weeks]
        label = "drafts the SOLVER produced — what we actually want to know"

    if not rosters:
        sys.exit(f"No rosters to measure for --source {source}.")

    open_flags = _open_minutes(shop)
    print(f"\n{shop['name']} — {len(rosters)} week(s), "
          f"{'open 24h' if shop.get('open_24h') else 'using shop hours'}")
    print(f"source: {label}\n")

    # ---- is this even a live question for this shop? --------------------
    edges: Counter = Counter()
    total_shifts = 0
    for roster in rosters:
        for shift in roster.get("shifts", []):
            if _is_leave(shift) or not (shift.get("start") and shift.get("end")):
                continue
            total_shifts += 1
            edges["start off the hour"] += to_minutes(shift["start"]) % 60 != 0
            edges["end off the hour"] += to_minutes(shift["end"]) % 60 != 0
    print(f"{total_shifts} worked shifts")
    for label, count in edges.items():
        share = 100 * count / total_shifts if total_shifts else 0
        print(f"  {count:5} ({share:4.1f}%) {label}")
    if not any(edges.values()):
        print("\nEvery shift sits on the hour, so the rounding invents nothing")
        print("here and option A would change nothing. Stop.")
        return
    print()

    # ---- model vs reality ------------------------------------------------
    print(f"{'week':12}{'open hrs':>9}{'EMPTY-HOLE':>12}{'OVER-COUNT':>12}"
          f"{'short mins':>12}")
    grand_invented = grand_over = grand_short = grand_open = 0
    worst: List[tuple] = []

    for roster in rosters:
        shifts = roster.get("shifts", [])
        minutes = _headcount_by_minute(shifts)

        covered_by_model = set()
        for shift in shifts:
            if _is_leave(shift) or not (shift.get("start") and shift.get("end")):
                continue
            covered_by_model.update(_RosterBuilder.hours_covered(
                shift["day"], shift["start"], shift["end"], wrap_week=True,
            ))

        # How many people the MODEL believes are on, per hour. This is the
        # figure the solver checks against `required`, so it is the one that
        # decides whether a gap looks closed.
        model_heads: Dict[tuple, int] = {}
        for shift in shifts:
            if _is_leave(shift) or not (shift.get("start") and shift.get("end")):
                continue
            for pair in _RosterBuilder.hours_covered(
                shift["day"], shift["start"], shift["end"], wrap_week=True,
            ):
                model_heads[pair] = model_heads.get(pair, 0) + 1

        open_hours = invented = over = short_minutes = 0
        for index, day in enumerate(DAYS):
            for hour in range(24):
                base = index * 1440 + hour * 60
                block = [m % WEEK_MINUTES for m in range(base, base + 60)]
                if not any(open_flags[m] for m in block):
                    continue
                open_hours += 1
                heads = [minutes[m] for m in block if open_flags[m]]
                empty = sum(1 for h in heads if h == 0)

                # (1) the shop is EMPTY for part of an hour the model calls
                #     staffed. The severe case, and rare on a 24h shop.
                if empty and (day, hour) in covered_by_model:
                    invented += 1
                    worst.append((empty, roster.get("week_start"), day, hour,
                                  "empty"))

                # (2) the model counts MORE people than are ever there at
                #     once. This is the case the advisory shows: a 17:30
                #     start credited with the whole 17:00 hour, so the model
                #     reads three on when two are standing there. Nobody is
                #     missing, so (1) sees nothing — but the required
                #     headcount is short and the solver cannot tell.
                said = model_heads.get((day, hour), 0)
                floor = min(heads) if heads else 0
                if said > floor:
                    over += 1
                    dip = sum(1 for h in heads if h < said)
                    short_minutes += dip
                    worst.append((dip, roster.get("week_start"), day, hour,
                                  f"{said} claimed, {floor} actually"))

        print(f"{roster.get('week_start', '?'):12}{open_hours:>9}"
              f"{invented:>12}{over:>12}{short_minutes:>10}m")
        grand_invented += invented
        grand_over += over
        grand_short += short_minutes
        grand_open += open_hours

    print()
    print("=" * 68)
    print(f"EMPTY-HOLE  {grand_invented} hour(s) called covered while the shop "
          f"is actually empty\n            for part of them — "
          f"{100 * grand_invented / grand_open:.2f}% of {grand_open} open hours.")
    print(f"OVER-COUNT  {grand_over} hour(s) where the model counts more people "
          f"than are ever\n            there at once — "
          f"{100 * grand_over / grand_open:.2f}%. "
          f"{grand_short} shortfall-minutes in total,\n"
          f"            {grand_short / len(rosters):.0f} per week.")

    if worst:
        print("\nWorst offenders:")
        for dip, week, day, hour, why in sorted(worst, reverse=True)[:10]:
            print(f"    {week}  {day} {hour:02d}:00   {dip} min   ({why})")

    print()
    decisive = grand_invented + grand_over
    if decisive == 0 and source == "approved":
        print("VERDICT: none — but this was the CONTROL. A hand-built rota on")
        print("a 24h shop never has a hole, so zero here was guaranteed before")
        print("the script ran. Re-run with --source solve for the real answer.")
    elif decisive == 0:
        print("VERDICT: the rounding is not inventing coverage in practice,")
        print("in rosters the SOLVER produced. Option A would be correct in")
        print("principle and change nothing real — fix the stretch (option C)")
        print("and leave the coverage model alone.")
    else:
        print("VERDICT: the model is claiming cover it does not have. Option A")
        print("is a correction, not a refinement — but expect it to surface")
        print(f"these {decisive} hours as gaps in weeks that look clean today.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--weeks", type=int, default=24)
    parser.add_argument(
        "--source", default="generated",
        choices=("generated", "approved", "solve"),
        help="generated = solver drafts (default); approved = the manager's "
             "own rota, a control that proves nothing on its own; "
             "solve = re-solve with today's code, the strongest answer",
    )
    args = parser.parse_args()
    asyncio.run(run(args.email, args.weeks, args.source))


if __name__ == "__main__":
    main()
