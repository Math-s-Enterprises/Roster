"""Deleting an account, and everything it owns.

WHAT "EVERYTHING" MEANS HERE

An account owns one shop, and the shop owns the rest. Rows are tied to it two ways:

  by shop_id   employees, holidays, fixed_shifts, ai_rules, rosters, activity_logs,
               roster_imports, correction_dismissals
  by user_id   user_sessions, password_resets, payment_transactions
  and the two records that identify them: the shop (owner_id) and the user itself.

That is every collection in db.py, and a test fails if one is ever added without being
listed here (see ERASURE_PLAN). That test is the point of the list: personal data left
behind in a table nobody remembered is the usual way erasure fails, and it fails silently.

THE ORDER, AND WHY

  1. Billing first. A subscription deleted from our records but not cancelled keeps
     charging someone who no longer has an account, and we would no longer know its id to
     cancel it. If billing cannot be cancelled, NOTHING is deleted and the person is told.
  2. The shop's data, then the shop, then sessions, reset links and payment rows.
  3. The user record LAST. Mongo cannot do this across collections in one transaction, so
     a failure part-way leaves some of it deleted. Keeping the account until the end means
     the person can still sign in and press the button again, and every step is safe to
     repeat (deleting what is already gone is not an error, and cancelling an already
     cancelled subscription is treated as done).
  4. A second sweep. A request already in flight when we started can write after the first
     pass, and the app creates a shop on first use, so one could even appear anew. Once the
     user record is gone nothing new can start; the second pass catches what was in the air.

WHAT THIS CANNOT REACH

  * Stripe keeps its own payment records, which the law makes it keep. The subscription is
    cancelled; the records are not ours to delete.
  * Backups of the database taken by whoever hosts it, and email delivery logs at the email
    provider, are outside this code. They age out on their own schedule.
"""
import logging
from typing import Any, Dict, List, Optional, Set

import stripe
from pydantic import BaseModel

from app import config, db

log = logging.getLogger("roster.account_deletion")

SHOP_SCOPED = (
    "employees", "holidays", "fixed_shifts", "ai_rules", "rosters",
    "activity_logs", "roster_imports", "correction_dismissals",
)
USER_SCOPED = ("user_sessions", "password_resets", "payment_transactions")
SHOPS = "shops"      # found by owner_id
USERS = "users"
# Shared security data, not owned by an individual account.
# Keep it accounted for, but do not erase it with a user's account.
NON_ACCOUNT_COLLECTIONS = ("auth_rate_limits",)

# Every collection in db.py must be accounted for. A test compares this to db.py itself.
ERASURE_PLAN = (
    frozenset(SHOP_SCOPED)
    | frozenset(USER_SCOPED)
    | {SHOPS, USERS}
    | frozenset(NON_ACCOUNT_COLLECTIONS)
)


class DeleteAccountReq(BaseModel):
    """What the person sends to prove they mean it.

    The typed email is always needed. On top of it: the password for an account that has
    one, or a fresh Google credential for an account that signs in with Google only.
    """
    confirm_email: str
    password: Optional[str] = None
    google_credential: Optional[str] = None


class BillingCleanupFailed(Exception):
    """The subscription could not be cancelled, so nothing was deleted."""


def _stripe_error():
    return getattr(stripe, "StripeError", None) or stripe.error.StripeError


def _already_gone(exc: Exception) -> bool:
    """A subscription or session that no longer exists needs no cancelling."""
    return getattr(exc, "code", None) == "resource_missing"


async def cancel_billing(user_id: str) -> List[str]:
    """Cancel every live subscription and expire every unfinished checkout.

    Returns what was done, for the log. Raises BillingCleanupFailed if anything that needs
    cancelling could not be, which stops the deletion before it starts.

    Three situations, per payment record:
      * it has a subscription id: cancel that subscription;
      * it is still pending: the checkout page may be open in another tab, and paying
        after the account is gone would charge someone for nothing. Expire it; or, if it
        completed without us hearing about it yet, cancel the subscription it made;
      * anything else (paid one-off, failed, expired): nothing to do.
    """
    records = await db.payment_transactions.find({"user_id": user_id}, {"_id": 0}).to_list(None)
    needs_action = [
        r for r in records
        if r.get("stripe_subscription_id") or r.get("payment_status") == "pending"
    ]
    if not needs_action:
        return []

    if not config.STRIPE_ENABLED:
        # We cannot cancel what we cannot reach. Deleting anyway would strand a live charge.
        raise BillingCleanupFailed(
            "Billing is not available right now, so your subscription cannot be cancelled "
            "and nothing has been deleted. Please try again later."
        )

    error = _stripe_error()
    done: List[str] = []

    def cancel(subscription_id: str) -> None:
        try:
            stripe.Subscription.cancel(subscription_id)
            done.append(f"cancelled {subscription_id}")
        except error as exc:
            if not _already_gone(exc):
                raise

    try:
        for record in needs_action:
            subscription_id = record.get("stripe_subscription_id")
            if subscription_id:
                cancel(subscription_id)
                continue
            session_id = record.get("session_id")
            if not session_id:
                continue
            try:
                session = stripe.checkout.Session.retrieve(session_id)
            except error as exc:
                if _already_gone(exc):
                    continue
                raise
            state = session.get("status") if hasattr(session, "get") else getattr(session, "status", None)
            if state == "open":
                try:
                    stripe.checkout.Session.expire(session_id)
                    done.append(f"expired {session_id}")
                except error as exc:
                    if not _already_gone(exc):
                        raise
            elif state == "complete":
                made = session.get("subscription") if hasattr(session, "get") else getattr(session, "subscription", None)
                if made:
                    cancel(made)
    except error as exc:
        log.error("Could not cancel billing while deleting account %s: %s", user_id, exc)
        raise BillingCleanupFailed(
            "We could not cancel your subscription with our payment provider, so nothing "
            "has been deleted. Please try again in a few minutes."
        ) from exc
    return done


async def _sweep(user_id: str, counts: Dict[str, int], shop_ids: Set[str]) -> None:
    """One pass over everything the account owns except the user record itself.

    `shop_ids` is shared between the passes and only ever grows. The shops are looked up
    afresh each time, because a request in flight can create a new one between passes; and
    the ids already seen are kept, because the first pass deletes the shop record, and
    without its id the second pass could not find a row a straggler wrote for it afterwards.
    """
    found = await db.shops.find({"owner_id": user_id}, {"_id": 0, "shop_id": 1}).to_list(None)
    shop_ids.update(s["shop_id"] for s in found if s.get("shop_id"))
    if shop_ids:
        for name in SHOP_SCOPED:
            result = await getattr(db, name).delete_many({"shop_id": {"$in": sorted(shop_ids)}})
            counts[name] = counts.get(name, 0) + result.deleted_count
    result = await db.shops.delete_many({"owner_id": user_id})
    counts[SHOPS] = counts.get(SHOPS, 0) + result.deleted_count
    for name in USER_SCOPED:
        result = await getattr(db, name).delete_many({"user_id": user_id})
        counts[name] = counts.get(name, 0) + result.deleted_count


async def erase(user: Dict[str, Any]) -> Dict[str, int]:
    """Delete everything the account owns, the user record last. Safe to run twice."""
    user_id = user["user_id"]
    counts: Dict[str, int] = {}
    shop_ids: Set[str] = set()
    await _sweep(user_id, counts, shop_ids)             # everything but the account itself
    result = await db.users.delete_one({"user_id": user_id})
    counts[USERS] = counts.get(USERS, 0) + result.deleted_count
    await _sweep(user_id, counts, shop_ids)             # whatever was in flight meanwhile
    return counts


async def delete_account(user: Dict[str, Any]) -> Dict[str, int]:
    """Cancel billing, then erase. Raises BillingCleanupFailed before touching any data."""
    await cancel_billing(user["user_id"])
    counts = await erase(user)
    # The user id is a random token, not personal data. No email or name is logged.
    log.info("Deleted account %s: %s", user["user_id"], counts)
    return counts
