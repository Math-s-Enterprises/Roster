"""Whether email will actually reach anybody, before you trust that it does.

    python ml/check_email_ready.py --email you@example.com
    python ml/check_email_ready.py --email you@example.com --send-test you@example.com

WHY
---
Three separate things have to be true before a roster reaches a member of
staff, and when it silently does not, they are indistinguishable from each
other and from "the app is broken":

  1. RESEND_API_KEY is set, so the mailer is enabled at all
  2. EMAIL_FROM is on a domain VERIFIED with Resend. The default,
     onboarding@resend.dev, delivers ONLY to the address that owns the Resend
     account — so dispatch to a team appears configured and fails for
     everybody except you
  3. the staff have email addresses. §9 is explicit that imports never
     fabricate one, so a shop set up from a spreadsheet may have none at all,
     and dispatch is then a no-op no matter how well configured it is

This reports all three, and can send one real message to prove the path
end to end.

THE KEY IS NEVER PRINTED. Only whether it is set and how long it is.

NOTHING IS WRITTEN.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config                                      # noqa: E402
from app import db                                          # noqa: E402
from app.services import availability as avail              # noqa: E402
from app.services import mailer                             # noqa: E402

# Deliberately loose. The job here is to spot "obviously not an address" and
# placeholders, not to adjudicate RFC 5322 — a real address that this rejected
# would be a worse outcome than a bad one it let through, because dispatch
# reports its own failures anyway.
LOOKS_LIKE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Addresses that exist to fill a column rather than to reach a person.
PLACEHOLDER_HINTS = ("example.com", "example.org", "test.com", "noemail",
                     "none@", "n/a", "placeholder", "@local", ".local")


def _domain(sender: str) -> str:
    match = re.search(r"<([^>]+)>", sender or "")
    address = match.group(1) if match else (sender or "")
    return address.split("@")[-1].strip().lower()


async def run(email: str, send_test: str) -> None:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        sys.exit(f"No account for {email}")
    shop = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if not shop:
        sys.exit("That account has no shop yet.")

    print("\n" + "=" * 68)
    print("1. IS THE MAILER SWITCHED ON")
    print("=" * 68)
    key = config.RESEND_API_KEY or ""
    print(f"  RESEND_API_KEY   {'set, ' + str(len(key)) + ' chars' if key else 'EMPTY'}")
    print(f"  EMAIL_ENABLED    {config.EMAIL_ENABLED}")
    print(f"  EMAIL_FROM       {config.EMAIL_FROM}")
    print(f"  FRONTEND_URL     {config.FRONTEND_URL}   (password-reset links)")
    if not key:
        print("\n  Nothing below matters until this is set. Put it in")
        print("  backend/.env as RESEND_API_KEY=re_... and restart the backend.")
        return

    print()
    print("=" * 68)
    print("2. CAN IT REACH ANYONE BUT YOU")
    print("=" * 68)
    domain = _domain(config.EMAIL_FROM)
    if domain == "resend.dev":
        print("  EMAIL_FROM is still Resend's TEST sender.")
        print("  It delivers ONLY to the address that owns the Resend account.")
        print("  Password reset to yourself will work; dispatch to staff will")
        print("  fail for every one of them. Verify your own domain and set")
        print("  EMAIL_FROM to something on it, e.g. Roster <rota@yourshop.ie>.")
    else:
        print(f"  Sending as a domain you control: {domain}")
        print("  Resend must show this domain as VERIFIED, or every send is")
        print("  rejected. Check resend.com/domains — the API key being valid")
        print("  is a different thing and does not imply it.")

    print()
    print("=" * 68)
    print("3. DO THE STAFF HAVE ADDRESSES")
    print("=" * 68)
    employees = await db.employees.find(
        {"shop_id": shop["shop_id"]}, {"_id": 0}).to_list(1000)
    active = [e for e in employees if avail.is_active(e)]

    reachable, missing, suspicious = [], [], []
    for employee in active:
        address = (employee.get("email") or "").strip()
        name = employee.get("name", employee.get("employee_id"))
        if not address:
            missing.append(name)
        elif not LOOKS_LIKE_EMAIL.match(address):
            suspicious.append(f"{name} <{address}>")
        elif any(hint in address.lower() for hint in PLACEHOLDER_HINTS):
            suspicious.append(f"{name} <{address}>  looks like a placeholder")
        else:
            reachable.append(name)

    print(f"  {len(active)} active staff")
    print(f"    {len(reachable):3} reachable")
    print(f"    {len(missing):3} no address stored")
    print(f"    {len(suspicious):3} address looks wrong or fabricated")
    for label, names in (("no address", missing), ("questionable", suspicious)):
        if names:
            print(f"\n  {label}:")
            for name in sorted(names)[:20]:
                print(f"    {name}")
            if len(names) > 20:
                print(f"    ... and {len(names) - 20} more")

    print()
    print("=" * 68)
    print("VERDICT")
    print("=" * 68)
    if not reachable:
        print("Dispatch would reach NOBODY. The mailer being configured does")
        print("not help — §9 means the import never invented addresses, so")
        print("they have to be entered before this feature does anything.")
    elif missing or suspicious:
        print(f"Dispatch would reach {len(reachable)} of {len(active)}. The rest")
        print("are reported by name after every send rather than failing")
        print("silently, but they are still not getting their rota.")
    else:
        print(f"All {len(reachable)} active staff have an address.")

    if send_test:
        print()
        print("=" * 68)
        print(f"4. LIVE TEST SEND -> {send_test}")
        print("=" * 68)
        # The real send path, not a mock. A test that exercises different code
        # from the feature proves nothing about the feature.
        error = await mailer.send_password_reset_email(
            send_test, user.get("name", "there"),
            f"{config.FRONTEND_URL}/reset-password?token=TEST-NOT-A-REAL-TOKEN",
            config.PASSWORD_RESET_EXPIRY_MINUTES,
        )
        if error:
            print(f"  FAILED: {error}")
            print("\n  Common causes, in the order they usually bite:")
            print("   * the domain in EMAIL_FROM is not verified with Resend")
            print("   * still on onboarding@resend.dev and the recipient is")
            print("     not the Resend account owner")
            print("   * the key is from a different Resend account")
        else:
            print("  Accepted by Resend. Check the inbox — and the spam folder,")
            print("  which is where a newly verified domain usually lands at")
            print("  first. The link in it is deliberately not a real token.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="your account email")
    parser.add_argument("--send-test", default="",
                        help="send one real message to this address")
    args = parser.parse_args()
    asyncio.run(run(args.email, args.send_test))


if __name__ == "__main__":
    main()
