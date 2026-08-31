"""Fill in staff email addresses from a CSV.

    python ml/set_emails.py --email you@example.com --csv staff.csv          # dry run
    python ml/set_emails.py --email you@example.com --csv staff.csv --commit

    name,email
    Emma,emma.doyle@example.ie
    Megan Doyle,megan@example.ie

WHY THIS EXISTS
---------------
§9: imports never fabricate an email address, so a shop set up from a
spreadsheet has none. Roster dispatch is then correctly configured and still
reaches nobody. Twenty-three people typed one at a time through the Employees
page is tedious and, more to the point, a typo produces a silent
non-delivery — the address looks fine and the rota simply never arrives.

MATCHING IS DELIBERATELY STRICT
-------------------------------
An email sent to the wrong person is worse than one not sent: it hands one
member of staff another's working pattern. So a row is applied only when it
matches EXACTLY ONE active employee, case- and accent-insensitively, on either
the full name or the first name. Anything ambiguous is reported and skipped —
never guessed at, never "closest match".

"Roisín" and "Roisin" are the same person. "Aj" typed as "AJ" is too. Two
people called Emma are not, and that row is refused until you use both names.

AN EXISTING ADDRESS IS NEVER OVERWRITTEN WITHOUT --replace
----------------------------------------------------------
Re-running this after adding one person should not quietly rewrite the other
twenty-four, and a stale CSV should not undo a correction made in the UI since.

NOTHING IS WRITTEN WITHOUT --commit. The dry run prints exactly what would
change, and is the same code path as the real thing minus the write.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.services import availability as avail              # noqa: E402

# Same shape check the readiness report uses. Loose on purpose: rejecting a
# real address is worse than passing a bad one, which dispatch reports anyway.
LOOKS_LIKE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _key(name: str) -> str:
    """Compare names without being defeated by an accent or a capital.

    Roisín and Roisin are one person. Decomposing to NFKD and dropping the
    combining marks means the CSV can be typed on any keyboard.
    """
    stripped = unicodedata.normalize("NFKD", (name or "").strip())
    return "".join(c for c in stripped if not unicodedata.combining(c)).lower()


async def run(account: str, csv_path: str, commit: bool, replace: bool) -> None:
    user = await db.users.find_one({"email": account.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {account}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")

    path = Path(csv_path)
    if not path.exists():
        sys.exit(f"No such file: {path}")

    employees = [
        e for e in await db.employees.find(
            {"shop_id": shop["shop_id"]}, {"_id": 0}).to_list(1000)
        if avail.is_active(e)
    ]

    # Two indexes, full name and first name, each mapping to EVERY employee
    # that answers to it — so a duplicate is visible rather than silently
    # resolved to whichever was read first.
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for employee in employees:
        full = _key(employee.get("name", ""))
        if not full:
            continue
        by_name.setdefault(full, []).append(employee)
        first = full.split()[0]
        if first != full:
            by_name.setdefault(first, []).append(employee)

    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        sys.exit("That CSV has no rows.")
    missing = {"name", "email"} - {(c or "").strip().lower() for c in rows[0]}
    if missing:
        sys.exit(f"The CSV needs a header row with: name,email (missing {missing})")

    planned, skipped = [], []
    seen_emails: Dict[str, str] = {}

    for line, row in enumerate(rows, start=2):
        clean = {(k or "").strip().lower(): (v or "").strip()
                 for k, v in row.items()}
        name, address = clean.get("name", ""), clean.get("email", "")
        if not name and not address:
            continue

        if not LOOKS_LIKE_EMAIL.match(address):
            skipped.append((line, name, address, "not an email address"))
            continue

        matches = by_name.get(_key(name), [])
        if not matches:
            skipped.append((line, name, address, "no active employee by that name"))
            continue
        if len(matches) > 1:
            others = ", ".join(m.get("name", "?") for m in matches)
            skipped.append((line, name, address,
                            f"matches {len(matches)} people ({others}) — "
                            f"use the full name"))
            continue

        employee = matches[0]
        # One address, one person. Two people sharing an inbox means one of
        # them reads the other's hours, and it is far more likely a
        # copy-paste slip in the CSV than a real arrangement.
        if address.lower() in seen_emails:
            skipped.append((line, name, address,
                            f"already used for {seen_emails[address.lower()]}"))
            continue
        seen_emails[address.lower()] = employee.get("name", "?")

        current = (employee.get("email") or "").strip()
        if current and not replace:
            note = "same" if current.lower() == address.lower() else f"has {current}"
            skipped.append((line, name, address, f"{note} — pass --replace to change"))
            continue

        planned.append((employee, current, address))

    print(f"\n{shop['name']} — {len(employees)} active staff, "
          f"{len(rows)} row(s) in {path.name}\n")

    if planned:
        print(f"WOULD SET {len(planned)} address(es):" if not commit
              else f"SETTING {len(planned)} address(es):")
        for employee, current, address in planned:
            arrow = f"{current} -> " if current else ""
            print(f"    {employee.get('name', '?'):22} {arrow}{address}")
    else:
        print("Nothing to change.")

    if skipped:
        print(f"\nSKIPPED {len(skipped)}:")
        for line, name, address, why in skipped:
            print(f"    line {line}: {name or '(no name)'} <{address}> — {why}")

    # Anyone the CSV never mentioned is still unreachable, and saying so here
    # avoids a second round trip to the readiness report.
    named = {_key(e.get("name", "")) for e, _, _ in planned}
    still_missing = [
        e.get("name", "?") for e in employees
        if not (e.get("email") or "").strip() and _key(e.get("name", "")) not in named
    ]
    if still_missing:
        print(f"\nSTILL WITHOUT AN ADDRESS ({len(still_missing)}):")
        print("    " + ", ".join(sorted(still_missing)))

    if not commit:
        print("\nDry run — nothing written. Re-run with --commit to apply.")
        return

    for employee, _, address in planned:
        await db.employees.update_one(
            {"employee_id": employee["employee_id"], "shop_id": shop["shop_id"]},
            {"$set": {"email": address}},
        )
    print(f"\nDone. {len(planned)} updated.")
    print("Re-run ml/check_email_ready.py to confirm what dispatch would reach.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="your account email")
    parser.add_argument("--csv", required=True, help="name,email")
    parser.add_argument("--commit", action="store_true",
                        help="actually write (default is a dry run)")
    parser.add_argument("--replace", action="store_true",
                        help="also overwrite addresses that are already set")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.csv, args.commit, args.replace))


if __name__ == "__main__":
    main()
