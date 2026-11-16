"""Which staff the setup checklist still counts as placeholders, and why.

    python ml/who_is_placeholder.py --email you@example.com

This prints the age group and review status for staff flagged by setup.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import availability as avail              # noqa: E402
from app.services.age_groups import age_group                # noqa: E402
from app.services.setup_status import _on_import_defaults    # noqa: E402


async def run(email: str) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})

    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}
    ).to_list(1000)
    team = [e for e in employees if not e.get("past_staff")]
    active = [e for e in team if avail.is_active(e)]

    print(f"\n{shop['name']} - {len(active)} active staff")

    flagged = [e for e in active if _on_import_defaults(e)]
    if not flagged:
        print("Nobody is flagged. If the checklist still says otherwise, the")
        print("running app is on older code - restart it.")
        return

    print(f"  {'name':18}{'rate':>8}{'age group':>14}{'max/wk':>9}   details")
    print("  " + "-" * 62)
    for employee in sorted(flagged, key=lambda e: e.get("name", "")):
        touched = employee.get("details_confirmed")
        print(f"  {(employee.get('name') or '?')[:17]:18}"
              f"{float(employee.get('hourly_rate') or 0):>8.2f}"
              f"{age_group(employee) or 'unconfirmed':>14}"
              f"{float(employee.get('max_weekly_hours') or 0):>9.1f}"
              f"   {'confirmed' if touched else 'never confirmed'}")

    print(f"\n{len(flagged)} staff need review.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.email))


if __name__ == "__main__":
    main()
