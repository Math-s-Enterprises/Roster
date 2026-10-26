"""Deleting an account, and everything it owns - in two steps, thirty days apart.

THE TWO STEPS

  1. THE REQUEST (request_deletion). The person confirms, and from that moment the account
     is closed: the subscription is cancelled, the paid-plan flag is switched off, every
     sign-in stops working, and nobody can use or see the account. NOTHING IS DELETED YET.
     A date GRACE_DAYS ahead is written on the user record.
  2. THE ERASE (purge_due, run hourly by purge_loop). When that date has passed, everything
     the account owns is permanently deleted by erase(), described below.

  In between, signing in again with the right password (or Google) cancels the deletion and
  brings the account back (restore_if_pending). That is what the thirty days are for: a
  second chance. After the date it cannot be restored, even in the hour or so before the
  next clean-up run gets to it (AccountExpired).

  Billing is cancelled at the REQUEST, not at the erase. The erase never waits for Stripe,
  so an outage there cannot hold up deleting somebody's data.

WHAT "EVERYTHING" MEANS HERE

An account owns one shop, and the shop owns the rest. Rows are tied to it two ways:

  by shop_id   employees, holidays, fixed_shifts, ai_rules, rosters, activity_logs,
               roster_imports, correction_dismissals
  by user_id   user_sessions, password_resets, payment_transactions
  and the two records that identify them: the shop (owner_id) and the user itself.

That is every collection in db.py, and a test fails if one is ever added without being
listed here (see ERASURE_PLAN). That test is the point of the list: personal data left
behind in a table nobody remembered is the usual way erasure fails, and it fails silently.

THE ORDER OF THE ERASE, AND WHY

  1. The shop's data, then the shop, then sessions, reset links and payment rows.
  2. The user record LAST. Mongo cannot do this across collections in one transaction, so
     a failure part-way leaves some of it deleted. Keeping the user record until the end
     means the next hourly run finds the account still due and finishes the job, and every
     step is safe to repeat (deleting what is already gone is not an error).
  3. A second sweep. A request already in flight when we started can write after the first
     pass, and the app creates a shop on first use, so one could even appear anew. Once the
     user record is gone nothing new can start; the second pass catches what was in the air.

WHAT THIS CANNOT REACH

  * Stripe keeps its own payment records, which the law makes it keep. The subscription is
    cancelled; the records are not ours to delete.
  * Backups of the database taken by whoever hosts it, and email delivery logs at the email
    provider, are outside this code. They age out on their own schedule.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import stripe
from pydantic import BaseModel

from app import config, db

log = logging.getLogger("roster.account_deletion")

# How long a closed account is kept, in case the person changes their mind, before everything
# in it is permanently deleted. The screen and the policies quote this number.
GRACE_DAYS = 30

# The clean-up job waits a minute after the server starts (so it never competes with start-up
# or with tests), then runs every hour. An account is therefore gone within an hour of its date.
PURGE_FIRST_RUN_SECONDS = 60
PURGE_EVERY_SECONDS = 60 * 60

# What the request writes on the user record, and what signing back in removes.
PENDING_FIELDS = ("deletion_requested_at", "deletion_scheduled_for")

SHOP_SCOPED = (
    "employees", "holidays", "fixed_shifts", "ai_rules", "rosters",
    "activity_logs", "roster_imports", "correction_dismissals",
)
USER_SCOPED = ("user_sessions", "password_resets", "payment_transactions")
SHOPS = "shops"      # found by owner_id
USERS = "users"
# Shared security data, not owned by an individual account.
# Keep it accounted for, but do not erase it with a user's account.
NON_ACCOUNT_COLLECTIONS = ("auth_rate_limits", "email_verifications")
# (email_verifications holds sign-ups still waiting for their emailed link. There is no account
# yet, so there is nothing to erase with one, and each record deletes itself within 24 hours.)

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
    """The subscription could not be cancelled, so the account was not closed."""


class AccountExpired(Exception):
    """The thirty days are over: the account is waiting for the clean-up and cannot come back."""


def _stripe_error():
    return getattr(stripe, "StripeError", None) or stripe.error.StripeError


def _already_gone(exc: Exception) -> bool:
    """A subscription or session that no longer exists needs no cancelling."""
    return getattr(exc, "code", None) == "resource_missing"


async def cancel_billing(user_id: str) -> List[str]:
    """Cancel every live subscription and expire every unfinished checkout.

    Returns what was done, for the log. Raises BillingCleanupFailed if anything that needs
    cancelling could not be, which stops the account being closed at all.

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
            "and your account has not been deleted. Please try again later."
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
        log.error("Could not cancel billing while closing an account: %s", exc)
        raise BillingCleanupFailed(
            "We could not cancel your subscription with our payment provider, so your account "
            "has not been deleted. Please try again in a few minutes."
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_when(value: Any) -> Optional[datetime]:
    """An ISO date as written on the user record, or None if there is none or it is unreadable."""
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def pending_message(user: Dict[str, Any]) -> str:
    """Said to somebody who tries to sign up with an address whose account is waiting."""
    when = parse_when(user.get("deletion_scheduled_for"))
    on = f" on {when.day} {when:%B %Y}" if when else ""
    return (
        f"That email belongs to an account that is scheduled for deletion{on}. "
        "Sign in to cancel the deletion, or sign up again after that date."
    )


async def request_deletion(user: Dict[str, Any]) -> datetime:
    """Close the account now and schedule everything in it to be erased GRACE_DAYS from now.

    Billing goes first, so that if it cannot be cancelled (BillingCleanupFailed) the account
    is left exactly as it was. Then, in one update: the date is written, the paid-plan flag is
    switched off (cancelling the subscription does not do that, and without it a person who
    came back would keep the paid plan for nothing), and the token version is bumped so every
    sign-in issued before now stops working. Cookie sessions are removed too.

    Asking twice keeps the original date; it does not push it back.
    """
    user_id = user["user_id"]
    await cancel_billing(user_id)
    now = _now()
    scheduled = parse_when(user.get("deletion_scheduled_for")) or now + timedelta(days=GRACE_DAYS)
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "deletion_requested_at": user.get("deletion_requested_at") or now.isoformat(),
                "deletion_scheduled_for": scheduled.isoformat(),
                "pro": False,
            },
            "$unset": {"pro_since": ""},
            "$inc": {"token_version": 1},
        },
    )
    await db.user_sessions.delete_many({"user_id": user_id})
    # No id, email or name is logged: log files outlive the account, which is meant to be erased for good.
    log.info("Closed an account; erasure scheduled for %s", scheduled.isoformat())
    return scheduled


async def restore_if_pending(user: Dict[str, Any], now: Optional[datetime] = None) -> Tuple[Dict[str, Any], bool]:
    """Called once somebody has proved who they are by signing in.

    An account that is not waiting is returned as it is. One that is waiting, and whose date
    has not come, has the deletion cancelled and is returned as restored. One whose date has
    passed raises AccountExpired: the clean-up is about to remove it, and the promise was
    thirty days, so it is not given a second chance by being a little late.
    """
    if not user.get("deletion_scheduled_for"):
        return user, False
    due = parse_when(user["deletion_scheduled_for"])
    if due is not None and due <= (now or _now()):
        raise AccountExpired()
    await db.users.update_one({"user_id": user["user_id"]}, {"$unset": {field: "" for field in PENDING_FIELDS}})
    log.info("An account signed back in; its deletion was cancelled")
    return {k: v for k, v in user.items() if k not in PENDING_FIELDS}, True


async def purge_due(now: Optional[datetime] = None) -> List[str]:
    """Erase every account whose thirty days are over. Returns the ids it erased.

    One account failing does not stop the others, and it is simply tried again on the next
    run, because its user record is only removed at the very end of erase().
    """
    now = now or _now()
    waiting = await db.users.find({"deletion_scheduled_for": {"$exists": True}}, {"_id": 0}).to_list(None)
    erased: List[str] = []
    for user in waiting:
        due = parse_when(user.get("deletion_scheduled_for"))
        if due is None or due > now:
            continue
        try:
            counts = await erase(user)
        except Exception:  # noqa: BLE001 - one bad account must not stop the rest
            log.exception("Could not erase an account; it will be tried again")
            continue
        log.info("Erased an account: %s", counts)
        erased.append(user["user_id"])
    return erased


async def purge_loop(first_run_after: float = PURGE_FIRST_RUN_SECONDS, every: float = PURGE_EVERY_SECONDS) -> None:
    """Run purge_due for as long as the server is up. Cancelled on shutdown."""
    await asyncio.sleep(first_run_after)
    while True:
        try:
            await purge_due()
        except Exception:  # noqa: BLE001 - the loop must survive anything a single run throws
            log.exception("Account clean-up run failed; will try again")
        await asyncio.sleep(every)
