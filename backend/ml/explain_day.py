"""Where one day's shift list comes from, and what got left out.

    python ml/explain_day.py --email you@example.com --day mon

A roster can only place somebody on a shift the day's plan contains. So when
a shift you expect is missing, there are two very different causes and the
roster looks the same either way:

  * the slot IS in the plan and somebody else won it — a ranking question
  * the slot is NOT in the plan at all — an apportionment question, and no
    amount of tuning who-beats-whom will ever put it back

This prints the day's learned patterns with the arithmetic that decided each
one: how many of the observed weeks ran it, the quota that gives, and whether
it survived into the plan. Slots that missed the cut are listed with what
they lost to.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import availability as avail               # noqa: E402
from app.services import slot_owners                        # noqa: E402
from app.services.demand import build_profile                # noqa: E402
from app.services.learning import latest_per_week            # noqa: E402


async def run(email: str, day: str) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")

    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}
    ).to_list(1000)
    names = {e["employee_id"]: e.get("name", e["employee_id"]) for e in employees}

    approved = await db.rosters.find(
        {"shop_id": shop["shop_id"], "approved": True}, {"_id": 0}
    ).to_list(500)
    profile = build_profile(
        shop, approved, {e["employee_id"]: e.get("role", "") for e in employees}
    )

    weeks = latest_per_week(approved)
    print(f"\n{shop['name']} — {day.upper()}")
    print(f"profile: {profile.source}, {profile.weeks_observed} weeks observed, "
          f"{len(weeks)} approved rosters after de-duplication\n")

    if profile.source != "learned":
        print("This day is on FALLBACK block coverage, not the shop's own")
        print("history — so the slot list is generic. Approve at least 4")
        print("weeks to switch it over.")
        return

    # Count the day's shapes the same way the profile does, so the numbers
    # printed here are the numbers that decided the plan.
    counts: Counter = Counter()
    for roster in weeks:
        for shift in roster.get("shifts", []):
            if shift.get("day") != day:
                continue
            start, end = shift.get("start"), shift.get("end")
            if start and end and not (
                shift.get("sick") or shift.get("paid_holiday")
                or shift.get("unpaid_holiday") or shift.get("temp_override")
            ):
                counts[(start, end)] += 1

    target = profile.staff_per_day.get(day, 0)
    planned = Counter(tuple(s) for s in profile.slots_for(day))
    observed = profile.weeks_observed or 1
    owners = slot_owners.build_owners(
        weeks,
        {e['employee_id'] for e in employees if avail.is_active(e)},
    )

    print(f"the shop runs about {target} people on a {day.upper()}, "
          f"so the plan holds {sum(planned.values())} slots\n")
    print(f"  {'shift':<14}{'weeks ran':>10}{'quota':>8}{'in plan':>9}   owner")
    print("  " + "-" * 62)

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    for (start, end), seen in ranked:
        quota = seen / observed
        in_plan = planned.get((start, end), 0)
        owner_id = slot_owners.owner_of(owners, day, start, end)
        owner = names.get(owner_id, "") if owner_id else "—"
        mark = str(in_plan) if in_plan else "NO"
        print(f"  {start}-{end:<8}{seen:>7}/{observed:<3}{quota:>7.2f}"
              f"{mark:>9}   {owner}")

    cut = [(s, e) for (s, e), n in ranked if not planned.get((s, e))]
    if cut:
        print(f"\n  {len(cut)} shape(s) did not make the plan.")
        print("  A shape is only kept if its whole-number quota is at least 1,")
        print(f"  or its fraction is large enough to win one of the remaining")
        print(f"  places up to {target}. Everything below that is a shift the")
        print("  shop ran sometimes, not a shift it runs weekly.")
        for start, end in cut:
            owner_id = slot_owners.owner_of(owners, day, start, end)
            if owner_id:
                print(f"    ! {start}-{end} is owned by "
                      f"{names.get(owner_id, owner_id)} but is not in the plan, "
                      f"so nobody can be placed on it.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--day", required=True, help="mon..sun")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.day.lower()))


if __name__ == "__main__":
    main()
