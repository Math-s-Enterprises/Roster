"""Show exactly what the solver was given and what it did with it.

    python ml/diagnose.py --email you@example.com --week 2026-08-24
    python ml/diagnose.py --email you@example.com --week 2026-08-24 --dry-run

Without --dry-run this reports on the LAST SAVED roster, which is whatever
the solver produced the last time it ran. Straight after a rule change that
is misleading: the figures look untouched because nothing re-ran. --dry-run
solves the week fresh in memory with the current code and reports on that,
writing nothing.

Prints the inputs (shop hours, employees, fixed shifts, leave, demand curve)
alongside the resulting roster, and flags specific rule violations:

  * a fixed shift that was not honoured
  * a preferred day off that was overridden
  * an employee shown as unavailable and the record that caused it

Use this when a roster looks wrong. Guessing at the cause from the grid alone
is slow; this shows the actual state the solver saw.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.services.demand import build_profile  # noqa: E402
from app.services.scheduler import DAYS  # noqa: E402


async def run(email: str, week: str, dry_run: bool = False) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    shop_id = shop["shop_id"]

    employees = await db.employees.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    fixed = await db.fixed_shifts.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    holidays = await db.holidays.find({"shop_id": shop_id}, {"_id": 0}).to_list(1000)
    rules = await db.ai_rules.find(
        {"shop_id": shop_id, "enabled": True}, {"_id": 0}
    ).to_list(200)
    approved = await db.rosters.find(
        {"shop_id": shop_id, "approved": True}, {"_id": 0}
    ).to_list(500)

    if dry_run:
        # Build a fresh roster in memory with the CURRENT code and report on
        # that. Reading the stored one shows whatever the solver produced the
        # last time it ran, which is misleading immediately after a rule
        # change — the numbers look unchanged because nothing re-ran.
        from app.services.hierarchy import sort_employees
        from app.services.learning import compute_weights
        from app.services.scheduler import solve_roster

        demand_profile = build_profile(
            shop, approved, {e["employee_id"]: e.get("role", "") for e in employees}
        )
        roster = solve_roster(
            shop, sort_employees(employees, shop), holidays, fixed, rules, week,
            compute_weights(approved), demand_profile, history_rosters=approved,
        )
        roster["version"] = "dry-run (not saved)"
    else:
        roster = await db.rosters.find_one(
            {"shop_id": shop_id, "week_start": week, "historical": {"$ne": True}},
            {"_id": 0}, sort=[("created_at", -1)],
        )

    by_id = {e["employee_id"]: e for e in employees}
    monday = datetime.strptime(week, "%Y-%m-%d").date()
    dates = {d: (monday + timedelta(days=i)).isoformat() for i, d in enumerate(DAYS)}

    # ---- shop -----------------------------------------------------------
    print(f"\n{'=' * 70}\nSHOP: {shop['name']}\n{'=' * 70}")
    for hours in shop.get("hours", []):
        state = "CLOSED" if hours.get("closed") else f"{hours['open']}-{hours['close']}"
        print(f"  {hours['day']}: {state}")
    print(f"  min/max shift: {shop.get('min_shift_hours')}h / {shop.get('max_shift_hours')}h")
    print(f"  24h mode: {shop.get('open_24h')}   templates: {len(shop.get('shift_templates') or [])}")

    open_all_day = all(
        not h.get("closed") and (h["open"] == "00:00" and h["close"] >= "23:00")
        for h in shop.get("hours", [])
    )
    if open_all_day:
        print("\n  NOTE: the shop is open 24/7, so the coverage floor requires at least")
        print("  one person in EVERY hour of EVERY day. Preferred days off are relaxed")
        print("  whenever that is the only way to keep the shop attended.")

    # ---- fixed shifts ---------------------------------------------------
    print(f"\n{'=' * 70}\nFIXED SHIFTS ({len(fixed)})\n{'=' * 70}")
    if not fixed:
        print("  none configured")
    for f in fixed:
        name = by_id.get(f["employee_id"], {}).get("name", f["employee_id"])
        print(f"  {name:16} {','.join(f['days']):24} {f['start']}-{f['end']}")

    # ---- leave in this week --------------------------------------------
    week_dates = set(dates.values())
    relevant = [
        h for h in holidays
        if any(d in week_dates for d in _expand(h))
    ]
    print(f"\n{'=' * 70}\nLEAVE AFFECTING {week} ({len(relevant)} records)\n{'=' * 70}")
    if not relevant:
        print("  nobody is on leave this week")
    for h in relevant:
        who = by_id.get(h.get("employee_id"), {}).get("name", "WHOLE SHOP")
        span = h["date"] if not h.get("end_date") or h["end_date"] == h["date"] else f"{h['date']}..{h['end_date']}"
        flag = "  <-- CLOSES THE SHOP" if h.get("scope") == "shop" else ""
        print(f"  {who:16} {h.get('scope'):10} {span:24} {h.get('label', '')}{flag}")

    # ---- employees ------------------------------------------------------
    print(f"\n{'=' * 70}\nEMPLOYEES ({len(employees)})\n{'=' * 70}")
    print(f"  {'name':16}{'role':18}{'max/wk':>7}{'  preferred days off'}")
    for e in sorted(employees, key=lambda x: x["name"]):
        off = ",".join(e.get("preferred_days_off") or []) or "-"
        print(f"  {e['name'][:15]:16}{(e.get('role') or '?')[:17]:18}{e.get('max_weekly_hours', 0):7.0f}  {off}")

    # ---- demand ---------------------------------------------------------
    profile = build_profile(shop, approved, {e["employee_id"]: e.get("role", "") for e in employees})
    print(f"\n{'=' * 70}\nDEMAND PROFILE\n{'=' * 70}")
    print(f"  source: {profile.source}   weeks learned: {profile.weeks_observed}   "
          f"patterns: {len(profile.patterns)}")
    if profile.patterns:
        print("  patterns offered to the solver:")
        for p in profile.patterns[:10]:
            print(f"    {p.start}-{p.end}  (used {p.count}x historically)")

    # ---- the roster -----------------------------------------------------
    if not roster:
        print(f"\nNo generated roster found for {week}. Generate one in the app first.")
        return

    print(f"\n{'=' * 70}\nRULE CHECKS on {roster.get('version')}\n{'=' * 70}")
    shifts = roster.get("shifts", [])
    placed = {(s["employee_id"], s["day"]): s for s in shifts}

    # fixed shifts honoured?
    problems = 0
    for f in fixed:
        for day in f["days"]:
            name = by_id.get(f["employee_id"], {}).get("name", f["employee_id"])
            actual = placed.get((f["employee_id"], day))
            on_leave = any(
                h.get("employee_id") == f["employee_id"] and dates[day] in _expand(h)
                for h in holidays
            )
            if actual and actual["start"] == f["start"] and actual["end"] == f["end"]:
                continue
            if on_leave:
                print(f"  ok   {name} has no fixed shift on {day} — they are on leave")
                continue
            problems += 1
            got = f"{actual['start']}-{actual['end']}" if actual else "NOT SCHEDULED"
            print(f"  FAIL {name} {day}: expected {f['start']}-{f['end']}, got {got}")

    # preferred days off honoured?
    overridden = 0
    for e in employees:
        for day in e.get("preferred_days_off") or []:
            shift = placed.get((e["employee_id"], day))
            if shift:
                overridden += 1
                reason = "coverage floor" if shift.get("coverage_fallback") else "demand shortfall"
                print(f"  WARN {e['name']} worked {day} despite preferring it off ({reason})")

    if not problems and not overridden:
        print("  all fixed shifts honoured, all preferred days off respected")

    print(f"\n  {len(shifts)} shifts, {roster.get('total_hours')}h, "
          f"{len({s['employee_id'] for s in shifts})} of {len(employees)} staff used")
    print(f"  compliance: {roster.get('compliance_score')}")
    print(f"  critical issues: {len(roster.get('critical_issues') or [])}")
    print(f"  unfamiliar shifts: {len(roster.get('confirmations') or [])} "
          f"(should be 0 — they are refused, not warned about)")

    # Where the week's hours went. Front-loading is the usual reason a
    # Saturday or Sunday ends up thin: everyone's weekly allowance is spent
    # by Thursday, so the hardest days to staff are reached last.
    by_day = {d: 0 for d in DAYS}
    for shift in shifts:
        if shift.get("day") in by_day and not shift.get("paid_holiday"):
            by_day[shift["day"]] += 1
    print("  shifts per day: " + "  ".join(f"{d} {n}" for d, n in by_day.items()))

    # Days each person works, so the two-days-off rule is visible.
    days_by_person: dict = {}
    for shift in shifts:
        if shift.get("paid_holiday"):
            continue
        days_by_person.setdefault(shift["employee_id"], set()).add(shift.get("day"))
    overworked = {
        by_id.get(eid, {}).get("name", eid): len(days)
        for eid, days in days_by_person.items() if len(days) > 5
    }
    print(f"  working more than 5 days: {len(overworked)}"
          + (f"  {overworked}" if overworked else ""))

    short = roster.get("under_contract") or []
    if short:
        print(f"  below contracted hours: {len(short)}")
        for entry in short[:5]:
            print(f"    {entry['name']:15} {entry['rostered_hours']}h "
                  f"of {entry.get('minimum_hours', entry['contracted_hours'])}h minimum")

    # Who is actually in the shop, hour by hour. Answers "the shop opens at
    # 06:00 but nobody is rostered" — an overnight shift from the day before
    # is often still there, which the grid does not make obvious.
    print(f"\n{'=' * 70}\nHOURLY COVER\n{'=' * 70}")
    from app.services.scheduler import _RosterBuilder  # noqa: E402

    cover = {d: [[] for _ in range(24)] for d in DAYS}
    for shift in shifts:
        if not (shift.get("start") and shift.get("end")):
            continue
        name = by_id.get(shift["employee_id"], {}).get("name", "?")
        for cday, chour in _RosterBuilder.hours_covered(
            shift["day"], shift["start"], shift["end"]
        ):
            cover[cday][chour].append(name)
    for d in DAYS:
        counts = "".join(
            str(min(9, len(cover[d][h]))) if cover[d][h] else "."
            for h in range(24)
        )
        print(f"  {d}  {counts}   (00 -> 23; '.' = nobody)")
    early = ", ".join(cover["sun"][6]) or "NOBODY"
    print(f"\n  sunday 06:00 is covered by: {early}")

    for issue in (roster.get("critical_issues") or [])[:5]:
        print(f"    ! {issue[:110]}")


def _expand(holiday) -> set:
    start = datetime.strptime(holiday["date"], "%Y-%m-%d").date()
    end = datetime.strptime(holiday.get("end_date") or holiday["date"], "%Y-%m-%d").date()
    out, cursor = set(), start
    while cursor <= end:
        out.add(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--week", required=True, help="week start, YYYY-MM-DD (a Monday)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Solve the week fresh with the current code instead of reading "
             "the last saved roster. Nothing is written.",
    )
    args = parser.parse_args()
    asyncio.run(run(args.email, args.week, args.dry_run))


if __name__ == "__main__":
    main()
