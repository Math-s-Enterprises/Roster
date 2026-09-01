"""Is stretching shifts to match the averaged curve worth what it costs?

    python ml/check_curve_chasing.py --email you@example.com

WHAT IS BEING TESTED
--------------------
`demand.py` learns two things from the same approved rosters:

  * `day_slots(day)` — the shift shapes the shop actually runs
  * `required(day, hour)` — the AVERAGE number of bodies per hour

The solver places the shapes, then compares the result to the curve and
stretches a neighbour over any hour that comes up short. But a discrete set
of ten real shapes cannot reproduce a 24-week average hour by hour. Measured
on the reference shop: the shapes fall 24 hours short of the curve and run 25
hours OVER it. They carry the same total; they are shaped differently.

`_close_short_hours` only corrects upward. It patches all 24 short hours and
leaves all 25 over hours alone, so the week comes out systematically bigger
than the shapes the shop runs — and the manager reads one advisory per patch.
Eighteen in a single week is what prompted this.

The question is whether those stretches buy anything. They are NOT the
coverage floor: §1 rule 1 ("somebody on the floor open to close") is enforced
separately by `_enforce_coverage_floor`, and that is not being touched here.

WHAT A NON-ZERO ANSWER LOOKS LIKE, STATED BEFORE RUNNING
--------------------------------------------------------
REMOVE the curve-chasing if, with it disabled:

  * uncovered hours do not rise — the real floor is unaffected
  * the week gets CLOSER to a normal week's size, not further
  * distance from the manager's own rota for that week does not get worse
  * advisories fall sharply

KEEP it if uncovered hours rise, or the generated week drifts further from
what the manager actually wrote. Then the stretching is doing real work and
the noise is the price of it.

Every approved week is solved twice, itself held out of its own history each
time, so the solver is never graded on a week it memorised.

NOTHING IS WRITTEN.
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
from app.services import compliance                         # noqa: E402
from app.services import scheduler as sched                 # noqa: E402
from app.services.demand import build_profile               # noqa: E402
from app.services.hierarchy import sort_employees           # noqa: E402
from app.services.learning import compute_weights, latest_per_week  # noqa: E402
from app.services.scheduler import DAYS, paid_hours         # noqa: E402


def _hours(roster) -> float:
    return sum(
        paid_hours(s["start"], s["end"])
        for s in roster.get("shifts") or []
        if s.get("start") and s.get("end")
        and not (s.get("paid_holiday") or s.get("unpaid_holiday"))
    )


def _shapes(roster) -> set:
    """(day, start, end) — what the week actually looks like on the wall."""
    return {
        (s["day"], s["start"], s["end"])
        for s in roster.get("shifts") or []
        if s.get("start") and s.get("end")
    }


async def run(email: str, limit: int) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")
    shop_id = shop["shop_id"]

    employees = await db.employees.find(
        {"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    holidays = await db.holidays.find(
        {"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    fixed = await db.fixed_shifts.find(
        {"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    rules = await db.ai_rules.find(
        {"shop_id": shop_id, "enabled": True}, {"_id": 0}).to_list(200)
    approved = latest_per_week(await db.rosters.find(
        {"shop_id": shop_id, "approved": True}, {"_id": 0}).to_list(500))

    # Newest weeks first, and only the ones with enough history behind them
    # to be solved at all.
    weeks = sorted(approved, key=lambda r: r["week_start"], reverse=True)
    weeks = [w for w in weeks if w.get("week_start")][:limit]
    if not weeks:
        sys.exit("No approved weeks to measure.")

    ordered = sort_employees(employees, shop)
    original = sched._RosterBuilder._close_short_hours

    rows: List[Dict[str, Any]] = []
    for target in weeks:
        week = target["week_start"]
        # The week itself is held out: it carries full weight in the profile
        # otherwise, and the solver would be graded on something it memorised.
        history = [r for r in approved if r.get("week_start") != week]
        if len(history) < 4:
            continue
        profile = build_profile(
            shop, history,
            {e["employee_id"]: e.get("role", "") for e in employees},
            for_week=week,
        )
        weights = compute_weights(history)

        def solve():
            return sched.solve_roster(
                shop, ordered, holidays, fixed, rules, week,
                weights, profile, history_rosters=history)

        with_chasing = solve()
        sched._RosterBuilder._close_short_hours = lambda self: None
        try:
            without = solve()
        finally:
            sched._RosterBuilder._close_short_hours = original

        manager = _shapes(target)
        rows.append({
            "week": week,
            "adv_with": len(with_chasing.get("issues") or []),
            "adv_without": len(without.get("issues") or []),
            "gap_with": len(compliance.uncovered_hours(
                with_chasing.get("shifts") or [], shop=shop)),
            "gap_without": len(compliance.uncovered_hours(
                without.get("shifts") or [], shop=shop)),
            "h_with": _hours(with_chasing),
            "h_without": _hours(without),
            "h_manager": _hours(target),
            # How many of the manager's own shifts the solver reproduced
            # exactly — the only external check on whether a week is right.
            "match_with": len(_shapes(with_chasing) & manager),
            "match_without": len(_shapes(without) & manager),
            "manager_shifts": len(manager),
        })

    print(f"\n{shop.get('name', '?')} — {len(rows)} weeks re-solved\n")
    print(f"  {'week':12}{'advisories':>18}{'uncovered':>14}"
          f"{'hours':>18}{'matches manager':>20}")
    print(f"  {'':12}{'with':>9}{'without':>9}{'with':>7}{'without':>7}"
          f"{'with':>7}{'without':>6}{'his':>5}{'with':>9}{'without':>9}")
    print("  " + "-" * 78)
    for r in rows:
        print(f"  {r['week']:12}{r['adv_with']:>9}{r['adv_without']:>9}"
              f"{r['gap_with']:>7}{r['gap_without']:>7}"
              f"{r['h_with']:>7.0f}{r['h_without']:>6.0f}{r['h_manager']:>5.0f}"
              f"{r['match_with']:>9}{r['match_without']:>9}")

    def mean(key):
        return sum(r[key] for r in rows) / len(rows)

    print(f"\n{'=' * 80}\nVERDICT\n{'=' * 80}")
    print(f"  advisories        {mean('adv_with'):6.1f}  ->"
          f" {mean('adv_without'):6.1f}")
    print(f"  uncovered hours   {mean('gap_with'):6.1f}  ->"
          f" {mean('gap_without'):6.1f}   (the real floor)")
    print(f"  week size         {mean('h_with'):6.1f}  ->"
          f" {mean('h_without'):6.1f}   manager: {mean('h_manager'):.1f}")
    print(f"  shifts matching   {mean('match_with'):6.1f}  ->"
          f" {mean('match_without'):6.1f}   of {mean('manager_shifts'):.1f}")
    print()

    floor_held = mean("gap_without") <= mean("gap_with") + 0.5
    closer = (abs(mean("h_without") - mean("h_manager"))
              <= abs(mean("h_with") - mean("h_manager")))
    as_faithful = mean("match_without") >= mean("match_with") - 0.5
    quieter = mean("adv_without") < mean("adv_with")

    if floor_held and closer and as_faithful and quieter:
        print("  REMOVE THE CURVE-CHASING. The floor is unaffected, the week")
        print("  is closer to the size the manager actually writes, the same")
        print("  shifts match his rota, and the advisory list is far shorter.")
        print("  The stretching was correcting a discrete shape list towards")
        print("  an average it can never equal, upwards only.")
    elif not floor_held:
        print("  KEEP IT. Uncovered hours rise without it, so the stretching")
        print("  is holding the floor rather than chasing an average.")
    elif not as_faithful or not closer:
        print("  KEEP IT. Without it the generated week drifts further from")
        print("  what the manager actually wrote, so the stretching is doing")
        print("  real work despite the noise.")
    else:
        print("  UNCLEAR — the measures disagree. Do not change the solver")
        print("  on this evidence; work out which measure is wrong first.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--weeks", type=int, default=8,
                        help="how many recent approved weeks to re-solve")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.weeks))


if __name__ == "__main__":
    main()
