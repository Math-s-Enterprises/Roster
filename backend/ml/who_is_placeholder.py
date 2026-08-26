"""Which staff the setup checklist still counts as placeholders, and why.

    python ml/who_is_placeholder.py --email you@example.com

"Check pay and ages" is judged by comparing three fields against what the
importer writes when a spreadsheet does not say. That has an obvious failure:
somebody who really is 25, really is on the default rate and really does work
40 hours looks identical to a record nobody has touched — so the step can
never be ticked, however many times it is edited.

This prints the actual values so the difference is visible.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import availability as avail              # noqa: E402
from app.services.setup_status import (                     # noqa: E402
    IMPORT_DEFAULT_AGE,
    IMPORT_DEFAULT_MAX_HOURS,
    IMPORT_DEFAULT_RATE,
    _on_import_defaults,
)


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

    print(f"\n{shop['name']} — {len(active)} active staff")
    print(f"the checklist calls somebody a placeholder when ALL THREE match:")
    print(f"  rate {IMPORT_DEFAULT_RATE}  ·  age {IMPORT_DEFAULT_AGE}  "
          f"·  max hours {IMPORT_DEFAULT_MAX_HOURS}\n")

    flagged = [e for e in active if _on_import_defaults(e)]
    if not flagged:
        print("Nobody is flagged. If the checklist still says otherwise, the")
        print("running app is on older code — restart it.")
        return

    print(f"  {'name':18}{'rate':>8}{'age':>6}{'max/wk':>9}   provenance")
    print("  " + "-" * 62)
    for employee in sorted(flagged, key=lambda e: e.get("name", "")):
        # If the importer left a mark, we KNOW these were never set. Without
        # one, the values are indistinguishable from real ones.
        touched = employee.get("details_confirmed")
        print(f"  {(employee.get('name') or '?')[:17]:18}"
              f"{float(employee.get('hourly_rate') or 0):>8.2f}"
              f"{int(employee.get('age') or 0):>6}"
              f"{float(employee.get('max_weekly_hours') or 0):>9.1f}"
              f"   {'confirmed' if touched else 'never confirmed'}")

    print(f"\n{len(flagged)} flagged. If any of these values are genuinely")
    print("correct, the current check cannot tell — which is the bug.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.email))


if __name__ == "__main__":
    main()
