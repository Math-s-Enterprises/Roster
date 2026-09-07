"""What owner-first ranking actually costs the contracted staff.

    python ml/check_contract_cost.py --email you@example.com --week 2026-08-31

WHY THIS EXISTS
---------------
CLAUDE.md §2b put the owner of a slot above contract need. That was the right
call for the reason recorded there — a full-timer below their band outranked
every owner on every slot they were eligible for, so Monday, built first while
the shortfall was still the whole contract, took the worst of it.

But it has a predicted cost: somebody could now finish the week short BECAUSE
an owner kept their shift. `_top_up_contracts` is supposed to catch that
afterwards, and `under_contract` reports whoever it cannot reach. Whether it
actually does is a question about this shop's data, not about the design.

"Is anybody in `under_contract`?" does NOT answer it. A person can be short
for reasons no ranking rule can fix — 25 staff and not enough trading hours to
go round, leave, a curfew, a five-day limit. Reading a shortfall as proof that
owners caused it is exactly the mistake this script exists to prevent.

WHAT IT DOES
------------
Solves the same week twice, changing one thing:

    run A   OWNER_BEATS_CONTRACT = True    (production)
    run B   OWNER_BEATS_CONTRACT = False   (the old order)

Then compares. Both runs use the same seed, so nothing varies except the
ordering decision under test.

  * short in A but NOT in B  -> owner-first caused it. Evidence for a
                                look-ahead before displacing an owner.
  * short in BOTH            -> the hours are not there. A look-ahead changes
                                nothing for them; do not build one for this.
  * short in B but not in A  -> owner-first HELPED, which is worth knowing.

It also counts how many shifts change hands between the two runs. That is the
price the old order charged: every one of those is a settled shift moving, and
a manager edit to move it back.

NOTHING IS WRITTEN. It reads the shop's data, solves in memory, and prints.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import availability as avail               # noqa: E402
from app.services.demand import build_profile               # noqa: E402
from app.services.hierarchy import sort_employees           # noqa: E402
from app.services.learning import compute_weights           # noqa: E402
from app.services.scheduler import _RosterBuilder, solve_roster   # noqa: E402


def _by_person(result: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {u["employee_id"]: u for u in result.get("under_contract", [])}


def _placements(result: Dict[str, Any]) -> set:
    """Every (day, start, end, person) the roster contains.

    Compared as a set rather than paired up shift-by-shift: two people on one
    shape, and a shape that runs a different number of times between the runs,
    both make pairing ambiguous. Set difference asks a question with an exact
    answer — "which placements does this roster have that the other does not".
    """
    return {
        (s["day"], s["start"], s["end"], s["employee_id"])
        for s in result.get("shifts", [])
        if s.get("start") and s.get("end")
    }


async def run(email: str, week: str) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")

    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}
    ).to_list(1000)
    employee_ids = {e["employee_id"] for e in employees}
    holidays = await db.holidays.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}
    ).to_list(1000)
    fixed_shifts = [
        f for f in await db.fixed_shifts.find(
            {"shop_id": shop["shop_id"]}, {"_id": 0}
        ).to_list(1000)
        if f["employee_id"] in employee_ids
    ]
    rules = await db.ai_rules.find(
        {"shop_id": shop["shop_id"], "enabled": True}, {"_id": 0}
    ).to_list(200)
    approved = await db.rosters.find(
        {"shop_id": shop["shop_id"], "approved": True}, {"_id": 0}
    ).to_list(500)

    weights = compute_weights(approved)
    demand = build_profile(
        shop, approved,
        {e["employee_id"]: e.get("role", "") for e in employees},
        for_week=week,
    )
    employees = sort_employees(employees, shop)

    print(f"\n{shop['name']} — week of {week}")
    print(f"{len(employees)} employees, {len(approved)} approved rosters, "
          f"demand profile: {demand.source}")

    # HOW MANY PEOPLE COULD EVEN BE FLAGGED.
    #
    # Only salaried staff with a contract band are checked: an hourly or
    # student contract is a ceiling, not a floor, so "short of it" does not
    # exist for them. Without this line, "nobody is below their minimum" is
    # ambiguous between "the solver reached everybody's contract" and "there
    # was nobody to reach", and those two readings lead opposite ways.
    banded = [
        e for e in employees
        if avail.is_active(e) and avail.contract_span_band(e)
    ]
    print(f"{len(banded)} of them are salaried with a contract band — "
          f"the only people\nwho can be reported short:")
    for employee in banded:
        low, high = avail.contract_span_band(employee)
        print(f"    {employee.get('name', '?')[:24]:26}"
              f"{low:.1f}-{high:.1f}h span")
    if not banded:
        print("    (none — this check has nothing to measure, and a clean")
        print("     result below means nothing at all)")
    print()

    # The SAME seed both times. Without this, unowned slots would vary between
    # the runs and the diff would include noise that has nothing to do with
    # the rule under test.
    seed = 1234

    def solve_with(owner_first: bool) -> Dict[str, Any]:
        original = _RosterBuilder.OWNER_BEATS_CONTRACT
        _RosterBuilder.OWNER_BEATS_CONTRACT = owner_first
        try:
            return solve_roster(
                shop, employees, holidays, fixed_shifts, rules, week,
                weights, demand, history_rosters=approved, seed=seed,
            )
        finally:
            # Restored even if the solve raises. A diagnostic that leaves a
            # production constant flipped is worse than no diagnostic.
            _RosterBuilder.OWNER_BEATS_CONTRACT = original

    with_owners = solve_with(True)
    without_owners = solve_with(False)

    assert _RosterBuilder.OWNER_BEATS_CONTRACT is True, \
        "the flag was not restored — do not trust anything after this"

    a, b = _by_person(with_owners), _by_person(without_owners)

    print("=" * 68)
    print("CONTRACTED STAFF BELOW THEIR MINIMUM")
    print("=" * 68)
    if not a and not b:
        print("\nNobody, either way. Owner-first is costing this shop nothing")
        print("in contracted hours. There is no problem for a look-ahead to")
        print("solve — building one now would be tuning for a shop that does")
        print("not exist yet (CLAUDE.md §10b).\n")
    else:
        print(f"\n{'name':22}{'contract':>10}{'with owners':>14}"
              f"{'without':>10}{'verdict':>0}")
        for employee_id in sorted(set(a) | set(b),
                                  key=lambda i: (a.get(i) or b[i])["name"]):
            short_a = a.get(employee_id, {}).get("short_hours", 0.0)
            short_b = b.get(employee_id, {}).get("short_hours", 0.0)
            row = a.get(employee_id) or b[employee_id]
            if short_a > short_b + 0.01:
                verdict = f"  <-- owner-first costs {short_a - short_b:.1f}h"
            elif short_b > short_a + 0.01:
                verdict = f"      owner-first SAVED {short_b - short_a:.1f}h"
            else:
                verdict = "      hours are not there — a look-ahead cannot help"
            print(f"{row['name'][:21]:22}{row['minimum_hours']:>9.1f}h"
                  f"{short_a:>12.1f}h{short_b:>9.1f}h{verdict}")

    caused = [
        i for i in a
        if a[i]["short_hours"] > b.get(i, {}).get("short_hours", 0.0) + 0.01
    ]

    # What the old order charged for those hours.
    here, there = _placements(with_owners), _placements(without_owners)
    lost = here - there          # in the real roster, gone under the old order
    changed_people = {key[3] for key in (here ^ there)}

    print("\n" + "=" * 68)
    print("WHAT TURNING IT OFF WOULD COST")
    print("=" * 68)
    print(f"\n{len(lost)} placement(s) in the current roster would not survive "
          f"the old\norder, across {len(changed_people)} people.")
    print("Each is somebody standing on a shift they would lose, and an edit")
    print("for the manager if they disagree.\n")

    print("=" * 68)
    print("VERDICT")
    print("=" * 68)
    if caused:
        names = ", ".join(sorted(a[i]["name"] for i in caused))
        total = sum(a[i]["short_hours"] - b.get(i, {}).get("short_hours", 0.0)
                    for i in caused)
        print(f"\nOwner-first IS costing contracted hours: {names}")
        print(f"({total:.1f}h in total this week).")
        print("\nThat is the evidence for option B — a look-ahead that checks")
        print("whether the contract can be met from OTHER slots before")
        print("displacing an owner. Worth building.\n")
    elif a:
        print("\nPeople are short, but NOT because of owner-first — the same")
        print("shortfall appears with the rule turned off. The hours are not")
        print("there to give. A look-ahead would move settled shifts around")
        print("and reach the same total.")
        print("\nDo not build option B for this. Look at contracted hours")
        print("against trading hours instead.\n")
    else:
        print("\nNo shortfall to explain. Leave it alone.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--week", required=True, help="Monday, YYYY-MM-DD")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.week))


if __name__ == "__main__":
    main()


