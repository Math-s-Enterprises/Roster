"""Where a person's hour total comes from, figure by figure.

    python ml/check_hours.py --email you@example.com --week 2026-08-31

"The grid says 40 but the total says 60" has several possible causes and they
are indistinguishable from the screen:

  * two shifts stored for one person on one day — the grid draws one cell per
    person per day, so the second is invisible but counts in every total
  * a stored `paid_hours` that disagrees with the times on the shift, left
    behind by an edit that changed the times without recomputing
  * `breaks_are_paid` differing between whoever wrote the number and whoever
    is reading it — a 10-hour shift is 10h or 9.5h depending on that flag
  * an overnight shift counted on both the day it starts and the day it ends

So this prints every shift with BOTH numbers — what is stored, and what the
times actually come to — and totals them separately. Wherever the two columns
diverge is the answer.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import compliance                         # noqa: E402
from app.services.scheduler import (                        # noqa: E402
    paid_hours,
    shift_duration_minutes,
)


async def run(email: str, week: str, who: str) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})

    query = {"shop_id": shop["shop_id"], "historical": {"$ne": True}}
    if week:
        query["week_start"] = week
    roster = await db.rosters.find_one(query, {"_id": 0}, sort=[("created_at", -1)])
    if not roster:
        sys.exit("No roster for that week.")

    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}
    ).to_list(1000)
    names = {e["employee_id"]: e.get("name", e["employee_id"]) for e in employees}
    breaks_paid = bool(shop.get("breaks_are_paid"))

    print(f"\n{shop['name']} — week of {roster['week_start']} ({roster.get('version')})")
    print(f"breaks_are_paid = {breaks_paid}")
    print(f"roster.total_hours = {roster.get('total_hours')}\n")

    # Two shifts for one person on one day is the first thing to rule out.
    counted = Counter(
        (s["employee_id"], s["day"])
        for s in roster.get("shifts", []) if s.get("start")
    )
    doubled = {k: v for k, v in counted.items() if v > 1}
    if doubled:
        print("!! SAME PERSON TWICE ON ONE DAY — invisible in the grid, "
              "counted in every total:")
        for (employee_id, day), count in doubled.items():
            print(f"     {names.get(employee_id, employee_id)} · {day} × {count}")
        print()
    else:
        print("no duplicate (person, day) rows — the totals disagree for "
              "another reason\n")

    mine = {}
    for shift in roster.get("shifts", []):
        if shift.get("start") and shift.get("end"):
            mine.setdefault(shift["employee_id"], []).append(shift)

    wanted = [
        eid for eid in mine
        if not who or who.lower() in names.get(eid, "").lower()
    ]
    for employee_id in sorted(wanted, key=lambda e: names.get(e, "")):
        shifts = sorted(mine[employee_id], key=lambda s: (s["day"], s["start"]))
        print(f"{names.get(employee_id, employee_id)}")
        print(f"  {'day':5}{'shift':16}{'stored':>9}{'from times':>12}{'span':>8}")
        stored_total = recomputed_total = span_total = 0.0
        for shift in shifts:
            stored = float(shift.get("paid_hours") or 0)
            recomputed = paid_hours(shift["start"], shift["end"],
                                    breaks_paid=breaks_paid)
            span = shift_duration_minutes(shift["start"], shift["end"]) / 60
            stored_total += stored
            recomputed_total += recomputed
            span_total += span
            flag = "  <-- disagree" if abs(stored - recomputed) > 0.02 else ""
            print(f"  {shift['day']:5}"
                  f"{shift['start'] + '-' + shift['end']:16}"
                  f"{stored:>9.2f}{recomputed:>12.2f}{span:>8.2f}{flag}")
        print(f"  {'':5}{'TOTAL':16}{stored_total:>9.2f}"
              f"{recomputed_total:>12.2f}{span_total:>8.2f}")

        employee = next(
            (e for e in employees if e["employee_id"] == employee_id), {}
        )
        # WHY a person gets no hours warning is usually this line, not a bug.
        # A contract band gives both a floor and a ceiling; an hourly cap
        # gives only a ceiling, so "short by 4h" cannot exist for them —
        # there is nothing they are short OF.
        from app.services import availability as avail
        kind = avail.employment_type(employee)
        band = avail.contract_span_band(employee)
        cap = avail.weekly_hour_cap(employee, roster["week_start"])
        print(f"  employment: {kind}"
              + (f"   contract band {band[0]:.1f}-{band[1]:.1f}h (span)"
                 if band else f"   cap {cap:.1f}h (paid) — CEILING ONLY,"
                              f" so a short week is never flagged"))
        breaches = compliance.audit(
            roster.get("shifts", []), shop=shop, employees=[employee],
            week_start=roster["week_start"],
            holidays=await db.holidays.find(
                {"shop_id": shop["shop_id"]}, {"_id": 0}
            ).to_list(1000),
        )
        for breach in breaches:
            print(f"    audit says: {breach['message']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--week", default="", help="Monday, YYYY-MM-DD")
    parser.add_argument("--who", default="",
                        help="only this person (partial name matches)")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.week, args.who))


if __name__ == "__main__":
    main()
