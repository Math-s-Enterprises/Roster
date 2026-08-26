"""Print a roster as a text grid, straight from the database.

    python ml/show_roster.py --email you@example.com

Reads Mongo directly, so there is no login or token to deal with. Useful for
comparing what the solver produced against what a human would have written,
and for pasting into a conversation when something looks wrong.

    --week 2026-08-24   a specific week (default: the most recent roster)
    --historical        show an imported week instead of a generated one
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.services import availability as avail  # noqa: E402
from app.services.scheduler import DAYS, paid_hours, shift_duration_minutes  # noqa: E402

COLUMN = 16


async def run(email: str, week: str | None, historical: bool) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")

    query = {"shop_id": shop["shop_id"]}
    if week:
        query["week_start"] = week
    if historical:
        query["historical"] = True
    else:
        query["historical"] = {"$ne": True}

    roster = await db.rosters.find_one(query, {"_id": 0}, sort=[("created_at", -1)])
    if not roster:
        sys.exit(
            "No matching roster found. Generate one in the app first, "
            "or pass --historical to view an imported week."
        )

    employees = {
        e["employee_id"]: e
        for e in await db.employees.find({"shop_id": shop["shop_id"]}, {"_id": 0}).to_list(1000)
    }

    print(f"\n{shop['name']} — week of {roster['week_start']}  ({roster.get('version')})")
    print(f"compliance {roster.get('compliance_score')}/100 · "
          f"{len(roster.get('shifts', []))} shifts · "
          f"{roster.get('total_hours')}h · "
          f"cost {roster.get('labor_cost')}")
    print(f"approved={roster.get('approved', False)}\n")

    by_employee: dict[str, dict[str, str]] = {}
    for shift in roster.get("shifts", []):
        cell = f"{shift['start']}-{shift['end']}"
        flags = "".join([
            "S" if shift.get("sick") else "",
            "H" if shift.get("paid_holiday") else "",
            "F" if shift.get("fixed") else "",
            "*" if shift.get("coverage_fallback") else "",
        ])
        by_employee.setdefault(shift["employee_id"], {})[shift["day"]] = cell + flags

    # Order by the scheduler's own role priority so the grid reads the way the
    # solver thinks: senior roles first.
    from app.services.scheduler import ROLE_PRIORITY

    def sort_key(employee_id: str):
        employee = employees.get(employee_id, {})
        return (ROLE_PRIORITY.get(employee.get("role"), 99), employee.get("name", ""))

    header = f"{'':18}{'':4}" + "".join(d.upper().ljust(COLUMN) for d in DAYS)
    print(header)
    print("-" * len(header))

    for employee_id in sorted(by_employee, key=sort_key):
        employee = employees.get(employee_id, {})
        name = (employee.get("name") or employee_id)[:17]
        role = (employee.get("role") or "?")[:3]
        row = "".join(by_employee[employee_id].get(d, "·").ljust(COLUMN) for d in DAYS)
        # Leave entries carry no times — somebody on holiday has no span —
        # so they are excluded before any arithmetic. Including them crashed
        # this script on an empty string.
        mine = [
            s for s in roster["shifts"]
            if s["employee_id"] == employee_id and s.get("start") and s.get("end")
        ]
        span = sum(shift_duration_minutes(s["start"], s["end"]) / 60 for s in mine)
        # Paid hours are what count against a contract; span is clock time.
        # Older rosters predate the split, so fall back to the span.
        paid = sum(s.get("paid_hours", paid_hours(s["start"], s["end"])) for s in mine)
        # The cap the SOLVER enforces for this week, not the raw contract
        # field. A student on summer break has a higher ceiling, and showing
        # the term-time number made a legal 30.5h week read as 152% of 20 —
        # a breach that was not happening.
        contract = avail.weekly_hour_cap(employee, roster.get("week_start", ""))
        fill = f"{paid / contract:4.0%}" if contract else "   -"
        print(f"{name:18}{role:4}{row}{paid:6.1f}p{span:6.1f}s{fill}")

    idle = [e["name"] for eid, e in employees.items() if eid not in by_employee]
    if idle:
        print(f"\nNot scheduled ({len(idle)}): {', '.join(sorted(idle))}")

    approved = await db.rosters.find(
        {"shop_id": shop["shop_id"], "approved": True}, {"_id": 0}
    ).to_list(500)
    _print_coverage(roster, shop, employees, approved)

    critical = roster.get("critical_issues") or []
    if critical:
        print(f"\nCRITICAL ({len(critical)}) — the shop would be unattended:")
        for issue in critical:
            print(f"  ! {issue}")

    issues = roster.get("issues") or []
    if issues:
        print(f"\nAdvisories ({len(issues)}):")
        for issue in issues[:15]:
            print(f"  - {issue}")
        if len(issues) > 15:
            print(f"  ... and {len(issues) - 15} more")

    if roster.get("ai_summary"):
        print(f"\nAI summary: {roster['ai_summary']}")

    print("\nlegend: F=fixed shift  *=preference relaxed to keep cover  "
          "H=paid holiday  S=sick  ·=not scheduled")


def _print_coverage(roster, shop, employees, approved_rosters) -> None:
    """Hourly staffing against the learned demand curve.

    The single most useful view when a roster looks wrong: it shows whether
    the solver missed the target, or the target itself is off.
    """
    from app.services.demand import build_profile
    from app.services.scheduler import _RosterBuilder

    profile = build_profile(
        shop, approved_rosters, {eid: e.get("role", "") for eid, e in employees.items()}
    )
    print(f"\ndemand profile: {profile.source}, "
          f"learned from {profile.weeks_observed} weeks, "
          f"{len(profile.patterns)} shift patterns")

    actual = {d: [0] * 24 for d in DAYS}
    for shift in roster.get("shifts", []):
        for hour in _RosterBuilder.hours_spanned(shift["start"], shift["end"]):
            actual[shift["day"]][hour] += 1

    print("\nCOVERAGE — actual / target per hour")
    print("      " + "".join(f"{h:>5}" for h in range(0, 24, 2)))
    for day in DAYS:
        cells = []
        for hour in range(0, 24, 2):
            want = profile.required(day, hour)
            have = actual[day][hour]
            mark = " " if have >= want else "!"
            cells.append(f"{have}/{want}{mark}".rjust(5))
        print(f"{day.upper():5} " + "".join(cells))
    print("      (! = below target)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--week", help="week start, YYYY-MM-DD (Monday)")
    parser.add_argument("--historical", action="store_true",
                        help="show an imported week rather than a generated one")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.week, args.historical))


if __name__ == "__main__":
    main()
