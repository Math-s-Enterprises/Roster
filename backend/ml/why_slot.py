"""Who was in the running for one slot, and what decided it.

    python ml/why_slot.py --email you@example.com --day mon --slot 06:00-12:00

The solver ranks candidates in this order: the owner first, then contract
need, then who else covers the slot, then demand fit. Contract need is
computed mid-solve and depends on how many hours a person already has, so it
cannot be reproduced exactly here. What CAN be shown is the input that drives
it — whether somebody is on a salaried contract at all — alongside the
ownership standing, which is fixed.

That is enough to answer the question this exists for: when an owner loses
their own shift, was it to a hard constraint, to a contract, or to something
that should not have beaten them.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import availability as avail              # noqa: E402
from app.services import slot_owners                        # noqa: E402
from app.services.learning import latest_per_week           # noqa: E402


async def run(email: str, day: str, slot: str) -> None:
    start, _, end = slot.partition("-")
    if not (start and end):
        sys.exit("Slot must look like 06:00-12:00")

    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})

    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}
    ).to_list(1000)
    approved = await db.rosters.find(
        {"shop_id": shop["shop_id"], "approved": True}, {"_id": 0}
    ).to_list(500)
    weeks = latest_per_week(approved)

    owners = slot_owners.build_owners(
        weeks,
        {e['employee_id'] for e in employees if avail.is_active(e)},
    )
    owner_id = slot_owners.owner_of(owners, day, start, end)
    order = slot_owners.preference_order(owners, day, start, end)
    history = owners.get((day, start, end))

    names = {e["employee_id"]: e.get("name", e["employee_id"]) for e in employees}
    print(f"\n{day.upper()} {start}-{end}")
    if history:
        print(f"ran in {history.weeks} of the observed weeks")
        print(f"owner: {names.get(owner_id, '— nobody at 60% over 4+ weeks')}")
    else:
        print("no history for this exact shape — ownership does not apply")

    print(f"\n  {'who':<16}{'employment':<20}{'band':<12}{'claim':<8}worked it")
    print("  " + "-" * 68)

    ranks = {eid: i for i, eid in enumerate(order)}
    people = history.people if history else []
    worked = dict(people)

    def sort_key(e):
        return (ranks.get(e["employee_id"], 9_999), e.get("name", ""))

    for e in sorted(employees, key=sort_key):
        eid = e["employee_id"]
        if eid not in ranks and not avail.is_full_time_contract(e):
            continue        # never worked it and no contract pull — not a factor
        kind = avail.employment_type(e)
        band = avail.contract_span_band(e)
        band_text = f"{band[0]:.1f}-{band[1]:.1f}h" if band else "—"
        claim = "OWNER" if eid == owner_id else (
            str(ranks[eid] + 1) if eid in ranks else "none")
        times = worked.get(eid, 0)
        flag = "" if avail.is_active(e) else "  (INACTIVE)"
        print(f"  {names.get(eid, eid)[:15]:<16}{kind:<20}{band_text:<12}"
              f"{claim:<8}{times}{flag}")

    print("\n  The owner takes the slot ahead of contract need, so a salaried")
    print("  colleague short of their band no longer displaces them. Among")
    print("  people with NO claim, contract need still decides first.")
    print("  An owner can still lose the slot to a hard constraint: leave,")
    print("  curfew, the hour cap, the 11-hour rest gap, or a fifth day.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--day", required=True)
    parser.add_argument("--slot", required=True, help="e.g. 06:00-12:00")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.day.lower(), args.slot))


if __name__ == "__main__":
    main()
