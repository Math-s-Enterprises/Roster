"""Stripe checkout and webhook handling.

Two independent paths confirm a payment:

  * the webhook — Stripe calls us server-to-server; authoritative, and
    arrives even if the customer closes the tab;
  * status polling — the browser asks us after redirect, and we re-check
    with Stripe directly if our record still looks unpaid.

Both are idempotent and guarded so that whichever lands first wins and the
second is a no-op. Belt and braces is deliberate: webhooks can be delayed,
and a customer who has paid must not be left without access.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict

import stripe
from fastapi import APIRouter, HTTPException, Request, status

from app import config, db
from app.models import CheckoutRequest
from app.security import CurrentUser
from app.tenancy import ShopScope, CurrentScope

log = logging.getLogger("roster.payments")
router = APIRouter(tags=["payments"])

if config.STRIPE_ENABLED:
    stripe.api_key = config.STRIPE_SECRET_KEY


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_stripe() -> None:
    if not config.STRIPE_ENABLED:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Billing is not configured. Set STRIPE_SECRET_KEY in backend/.env.",
        )


async def _grant_pro(user_id: str) -> None:
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"pro": True, "pro_since": _now()}},
    )


@router.post("/payments/checkout")
async def create_checkout(payload: CheckoutRequest, scope: ShopScope = CurrentScope):
    _require_stripe()

    prices = stripe.Price.list(lookup_keys=[payload.lookup_key], active=True, limit=1).data
    if not prices:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No active price found for '{payload.lookup_key}'. Run setup_stripe.py first.",
        )
    price = prices[0]

    # Only the path is taken from the client; the origin is not trusted for
    # anything except returning the user to their own app.
    session_args: Dict[str, Any] = {
        "line_items": [{"price": price.id, "quantity": payload.quantity}],
        "mode": "subscription" if price.recurring else "payment",
        "success_url": f"{payload.origin_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{payload.origin_url}/payment/cancel",
        "metadata": {"user_id": scope.user["user_id"], "lookup_key": payload.lookup_key},
    }

    try:
        session = stripe.checkout.Session.create(
            **session_args, automatic_tax={"enabled": True},
            billing_address_collection="required",
        )
    except stripe.error.StripeError as exc:
        log.error("Stripe checkout failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not start checkout: {exc}")

    await db.payment_transactions.insert_one({
        "session_id": session.id,
        "user_id": scope.user["user_id"],
        "lookup_key": payload.lookup_key,
        "amount": (price.unit_amount or 0) * payload.quantity,
        "currency": price.currency,
        "status": "initiated",
        "payment_status": "pending",
        "created_at": _now(),
        "updated_at": _now(),
    })
    return {"checkout_url": session.url, "session_id": session.id}


@router.get("/payments/status/{session_id}")
async def payment_status(session_id: str, user=CurrentUser):
    record = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not record:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment session not found")

    # Only the payer may read a session's status — otherwise anyone holding
    # a session ID could probe another customer's payment state.
    if record.get("user_id") != user["user_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your payment session")

    if record.get("payment_status") != "paid" and config.STRIPE_ENABLED:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == "paid" or session.status == "complete":
                updated = await db.payment_transactions.update_one(
                    {"session_id": session_id, "payment_status": {"$ne": "paid"}},
                    {"$set": {
                        "status": "completed",
                        "payment_status": "paid",
                        "stripe_subscription_id": session.subscription,
                        "stripe_payment_intent_id": session.payment_intent,
                        "updated_at": _now(),
                    }},
                )
                if updated.modified_count and record.get("user_id"):
                    await _grant_pro(record["user_id"])
                record = await db.payment_transactions.find_one(
                    {"session_id": session_id}, {"_id": 0}
                )
        except stripe.error.StripeError as exc:
            log.warning("Could not refresh session %s: %s", session_id, exc)

    return {
        "session_id": record["session_id"],
        "status": record["status"],
        "payment_status": record["payment_status"],
    }


@router.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    """Stripe's server-to-server payment notifications.

    Unauthenticated by necessity — Stripe cannot present a user's token — so
    the signature check IS the authentication. Without a configured
    STRIPE_WEBHOOK_SECRET this endpoint is refused outright rather than
    trusting unsigned input.
    """
    if not config.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Webhook secret is not configured"
        )

    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, config.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature")

    obj, event_type = event["data"]["object"], event["type"]
    session_id = obj.get("id")

    if event_type == "checkout.session.completed":
        # The filter doubles as the idempotency guard: a replayed webhook
        # modifies nothing, so Pro is never granted twice.
        updated = await db.payment_transactions.update_one(
            {"session_id": session_id, "payment_status": {"$ne": "paid"}},
            {"$set": {
                "status": "completed",
                "payment_status": obj.get("payment_status", "paid"),
                "stripe_subscription_id": obj.get("subscription"),
                "stripe_payment_intent_id": obj.get("payment_intent"),
                "updated_at": _now(),
            }},
        )
        if updated.modified_count:
            record = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
            if record and record.get("user_id"):
                await _grant_pro(record["user_id"])

    elif event_type == "checkout.session.async_payment_succeeded":
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"payment_status": "paid", "updated_at": _now()}},
        )

    elif event_type in ("checkout.session.async_payment_failed", "checkout.session.expired"):
        state = "failed" if event_type.endswith("failed") else "expired"
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"status": state, "payment_status": state, "updated_at": _now()}},
        )

    return {"status": "ok"}
