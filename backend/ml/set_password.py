"""Set an account's password directly.

    python ml/set_password.py --email you@example.com

Prompts for the new password without echoing it, hashes it the same way
signup does, and writes it.

WHY THIS EXISTS
---------------
There is no way to change a password from inside the app. `forgot-password`
emails a reset link, and email is off until RESEND_API_KEY is set — so the
link is generated and never arrives. There is no "change password" screen for
somebody already logged in either.

That matters more since force approval started asking for the account
password: it is now something the manager types regularly rather than once at
signup, and "I want to change it" has no answer in the product.

This is the stopgap, not the fix. The fix is a change-password endpoint and a
screen, which needs the current password re-entered.

Any active sessions keep working — the token was issued before this and is not
invalidated by it. Log out and back in if that matters.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                          # noqa: E402
from app.security import hash_password, verify_password     # noqa: E402

MIN_LENGTH = 8


async def run(email: str) -> int:
    user = await db.users.find_one({"email": email.lower()}, {"_id": 0})
    if not user:
        print(f"No account for {email}")
        # Named rather than guessed at: two accounts have been in play on this
        # machine and picking the wrong one wastes a round trip.
        others = await db.users.find({}, {"_id": 0, "email": 1}).to_list(20)
        if others:
            print("\nAccounts on this database:")
            for other in others:
                print(f"    {other.get('email')}")
        return 1

    print(f"Changing the password for {user.get('email')}"
          f" ({user.get('name', 'no name')})")

    # Says so out loud. getpass shows nothing at all — not even asterisks —
    # and a prompt that looks frozen is indistinguishable from one that is.
    print("(what you type will not appear on screen — that is deliberate)\n")
    first = getpass.getpass("New password: ")
    if len(first) < MIN_LENGTH:
        print(f"Too short — at least {MIN_LENGTH} characters.")
        return 1
    if first != getpass.getpass("Again: "):
        print("They do not match. Nothing changed.")
        return 1

    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"password_hash": hash_password(first)}},
    )

    # Read it back and check. Writing a hash nobody has verified is how you
    # find out at the login screen instead of here.
    updated = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not verify_password(first, updated.get("password_hash")):
        print("The new password did not verify. Nothing is safe to assume — "
              "check the database before logging out.")
        return 1

    print("\nDone, and verified. Existing sessions stay logged in; the new "
          "password applies at the next login.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.email)))


if __name__ == "__main__":
    main()
