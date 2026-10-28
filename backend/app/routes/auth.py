"""Authentication routes: signup, login, Google sign-in, session, logout."""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pymongo.errors import DuplicateKeyError

from app import config, db
from app.models import (
    ChangePassword,
    ForgotPasswordReq,
    GoogleAuthReq,
    LoginReq,
    ResendVerificationReq,
    ResetPasswordReq,
    SignupReq,
    VerifyEmailReq,
)
from app.security import (
    create_access_token,
    generate_reset_token,
    get_current_user,
    hash_password,
    hash_reset_token,
    verify_password,
)
from app.services import account_deletion, google_auth
from app.services.auth_rate_limit import check_auth_rate_limit
from app.services.mailer import send_password_reset_email, send_verification_email
from app.services.shop_service import ensure_shop

log = logging.getLogger("roster.auth")
router = APIRouter(prefix="/auth", tags=["auth"],
                   dependencies=[Depends(check_auth_rate_limit)])

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
)

def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Everything safe to send to the browser - never the password hash."""
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user.get("name"),
        "picture": user.get("picture"),
        "pro": bool(user.get("pro", False)),
        # Whether there is a password to ask for. An account that signs in with Google
        # only has none, and the delete-account dialog needs to know which to ask.
        "has_password": bool(user.get("password_hash")),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _register(email: str, name: str, password_hash: str, shop_name: Optional[str]) -> Dict[str, Any]:
    """Create the account and its shop, and sign the person in.

    Used when an address has been confirmed from the emailed link, and straight away where
    confirmation is switched off (tests, and a local setup with no email service).
    """
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    document = {
        "user_id": user_id,
        "email": email,
        "name": name,
        "password_hash": password_hash,
        "shop_name": shop_name,
        "pro": False,
        "created_at": _now(),
    }

    try:
        await db.users.insert_one(dict(document))
    except DuplicateKeyError:
        # The unique index on `email` is the real guarantee here. A prior
        # "does this email exist?" lookup would not be atomic - two
        # simultaneous signups could both pass it - so we let the database
        # arbitrate and translate its error.
        raise _already_registered(await db.users.find_one(
            {"email": email}, {"_id": 0, "deletion_scheduled_for": 1},
        ))

    await ensure_shop(document)
    return {
        "token": create_access_token(user_id, document.get("token_version", 0)),
        "user": _public_user(document),
    }


def _already_registered(existing: Optional[Dict[str, Any]]) -> HTTPException:
    if existing and existing.get("deletion_scheduled_for"):
        # Not "already registered": that would leave somebody who just deleted their
        # account, and came straight back, with no idea what to do.
        return HTTPException(status.HTTP_409_CONFLICT, account_deletion.pending_message(existing))
    return HTTPException(status.HTTP_409_CONFLICT, "That email is already registered")


def _verify_link(token: str) -> str:
    return f"{config.FRONTEND_URL}/verify-email?token={token}"


def _too_soon(record: Optional[Dict[str, Any]]) -> bool:
    """True if a confirmation email for this sign-up went out less than a minute ago."""
    sent = (record or {}).get("last_sent_at")
    if not isinstance(sent, datetime):
        return False
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - sent).total_seconds() < config.EMAIL_VERIFY_RESEND_SECONDS


def _wait_a_minute() -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "We have just sent you an email. Please wait a minute before asking for another.",
        headers={"Retry-After": str(config.EMAIL_VERIFY_RESEND_SECONDS)},
    )


def _could_not_send() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "We could not send the confirmation email just now. Please check the address is correct "
        "and try again in a few minutes.",
    )


async def _send_confirmation(email: str, name: str) -> Dict[str, Any]:
    """Email a fresh link. Returns the record to store, or raises 503 if the email did not go."""
    token = generate_reset_token()
    now = datetime.now(timezone.utc)
    error = await send_verification_email(
        email, name, _verify_link(token), config.EMAIL_VERIFY_EXPIRY_HOURS,
    )
    if error:
        # The reason is already logged by the mailer (the provider's status, never the address).
        raise _could_not_send()
    return {
        "token_hash": hash_reset_token(token),
        "expires_at": now + timedelta(hours=config.EMAIL_VERIFY_EXPIRY_HOURS),
        "last_sent_at": now,
    }


def _verification_sent(email: str) -> Dict[str, Any]:
    return {"verification_sent": True, "email": email, "expires_in_hours": config.EMAIL_VERIFY_EXPIRY_HOURS}


async def _begin_email_verification(payload: SignupReq) -> Dict[str, Any]:
    """Sign-up step one: keep the details for a day and email a link. No account exists yet."""
    email = payload.email.lower()
    existing = await db.users.find_one({"email": email}, {"_id": 0, "deletion_scheduled_for": 1})
    if existing is not None:      # (an ordinary user comes back as an empty record, which is falsy)
        raise _already_registered(existing)

    pending = await db.email_verifications.find_one({"email": email}, {"_id": 0, "last_sent_at": 1})
    if _too_soon(pending):
        raise _wait_a_minute()

    sent = await _send_confirmation(email, payload.name)
    await db.email_verifications.replace_one(
        {"email": email},
        {
            **sent,
            "email": email,
            "name": payload.name,
            "password_hash": hash_password(payload.password),
            "shop_name": payload.shop_name,
            "created_at": _now(),
        },
        upsert=True,
    )
    return _verification_sent(email)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupReq, response: Response):
    if config.EMAIL_VERIFICATION_REQUIRED:
        # 202, not 201: nothing has been created yet. The account appears when the link is clicked.
        response.status_code = status.HTTP_202_ACCEPTED
        return await _begin_email_verification(payload)
    return await _register(
        payload.email.lower(), payload.name, hash_password(payload.password), payload.shop_name,
    )


@router.post("/verify-email", status_code=status.HTTP_201_CREATED)
async def verify_email(payload: VerifyEmailReq):
    """Sign-up step two: the emailed link was clicked. Create the account and sign the person in."""
    record = await db.email_verifications.find_one({"token_hash": hash_reset_token(payload.token)}, {"_id": 0})
    if not record or not _reset_is_live(record):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That link is not valid any more. If you already confirmed your email, sign in. "
            "Otherwise please sign up again to get a new link.",
        )
    # Deleted before the account is made, so the same link used twice (a double click, or an
    # email scanner that opens links) can only ever create one account.
    removed = await db.email_verifications.delete_one({"token_hash": record["token_hash"]})
    if removed.deleted_count == 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That link has already been used. If you confirmed your email, sign in.",
        )
    return await _register(record["email"], record["name"], record["password_hash"], record.get("shop_name"))


@router.post("/resend-verification")
async def resend_verification(payload: ResendVerificationReq):
    """Send the confirmation link again for a sign-up that is still waiting. The old link stops working."""
    email = payload.email.lower()
    record = await db.email_verifications.find_one({"email": email}, {"_id": 0})
    if not record or not _reset_is_live(record):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That sign-up has expired. Please fill in the form again.",
        )
    if _too_soon(record):
        raise _wait_a_minute()

    sent = await _send_confirmation(email, record.get("name", ""))
    await db.email_verifications.update_one({"email": email}, {"$set": sent})
    return _verification_sent(email)


@router.post("/login")
async def login(payload: LoginReq):
    user = await db.users.find_one({"email": payload.email.lower()}, {"_id": 0})
    if not user or not verify_password(payload.password, user.get("password_hash")):
        # Do not disclose registered addresses through different error responses.
        raise _INVALID_CREDENTIALS

    # The right password for an account that is waiting to be deleted cancels the deletion.
    # After its date it does not: the clean-up is about to remove it, so it looks as if it
    # were already gone.
    try:
        user, restored = await account_deletion.restore_if_pending(user)
    except account_deletion.AccountExpired:
        raise _INVALID_CREDENTIALS

    await ensure_shop(user)
    body = {
        "token": create_access_token(
            user["user_id"], user.get("token_version", 0),
        ),
        "user": _public_user(user),
    }
    if restored:
        body["restored"] = True        # the screen says so; absent otherwise
    return body


@router.post("/google")
async def google_sign_in(payload: GoogleAuthReq):
    """Exchange a verified Google ID token for our own access token."""
    try:
        profile = google_auth.verify_id_token(payload.credential)
    except google_auth.GoogleAuthUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    except google_auth.GoogleAuthInvalid as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc))

    user = await db.users.find_one({"google_sub": profile["google_sub"]}, {"_id": 0})
    if not user:
        user = await db.users.find_one({"email": profile["email"]}, {"_id": 0})
    restored = False
    if user:
        user = await _link_google_profile(user, profile)
        # Only now, once the Google identity has been checked: a different Google account
        # with the same email must not be able to bring a closed account back.
        try:
            user, restored = await account_deletion.restore_if_pending(user)
        except account_deletion.AccountExpired:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "That account is no longer available.")
    else:
        # Verify Google again on submission; an abandoned form creates no account.
        if payload.password is None:
            return {"password_required": True, "email": profile["email"]}
        user = {
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": profile["email"],
            "name": profile["name"],
            "picture": profile["picture"],
            "google_sub": profile["google_sub"],
            "password_hash": hash_password(payload.password),
            "pro": False,
            "created_at": _now(),
        }
        try:
            await db.users.insert_one(dict(user))
        except DuplicateKeyError:
            # Lost a race with a concurrent signup for the same address.
            user = await db.users.find_one({"google_sub": profile["google_sub"]}, {"_id": 0})
            if not user:
                user = await db.users.find_one({"email": profile["email"]}, {"_id": 0})
            if not user:
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create account")
            user = await _link_google_profile(user, profile)

    await ensure_shop(user)
    body = {
        "token": create_access_token(
            user["user_id"], user.get("token_version", 0),
        ),
        "user": _public_user(user),
    }
    if restored:
        body["restored"] = True
    return body


async def _link_google_profile(user, profile):
    subject = user.get("google_sub")
    if subject and subject != profile["google_sub"]:
        raise HTTPException(401, "This account is linked to a different Google identity.")
    if not subject and not profile["email_authoritative"]:
        raise HTTPException(401, "Please sign in with your password to access this existing account.")
    # Compare-and-set prevents concurrent linking from replacing an identity.
    updated = await db.users.update_one(
        {"user_id": user["user_id"], "google_sub": subject},
        {"$set": {"google_sub": profile["google_sub"], "picture": profile["picture"]}},
    )
    if not updated.matched_count:
        raise HTTPException(409, "Account sign-in changed. Please try again.")
    return {**user, "picture": profile["picture"]}


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordReq):
    """Start a password reset. Always looks the same to the caller.

    Returning a different response for "no such account" than for "email
    sent" would let this endpoint enumerate registered addresses, so the
    response is identical either way - the real work happens only if a
    matching, password-capable account exists.
    """
    generic = {"message": "If an account exists for that email, a reset link has been sent."}

    user = await db.users.find_one({"email": payload.email.lower()}, {"_id": 0})
    if not user:
        return generic

    token = generate_reset_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=config.PASSWORD_RESET_EXPIRY_MINUTES)
    await db.password_resets.insert_one({
        "token_hash": hash_reset_token(token),
        "user_id": user["user_id"],
        "expires_at": expires_at,
        "used": False,
        "created_at": _now(),
    })

    reset_url = f"{config.FRONTEND_URL}/reset-password?token={token}"
    error = await send_password_reset_email(
        user["email"], user.get("name", ""), reset_url, config.PASSWORD_RESET_EXPIRY_MINUTES,
    )
    if error:
        log.warning("Password reset email could not be sent; the email service logged why")

    return generic


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordReq):
    record = await db.password_resets.find_one({"token_hash": hash_reset_token(payload.token)})
    if not record or record.get("used") or not _reset_is_live(record):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That reset link is invalid or has expired.")

    # Marked used immediately (not deleted) so a replayed request - the same
    # link submitted twice, e.g. via a double click or an email link
    # prefetcher - fails instead of silently resetting the password again.
    result = await db.password_resets.update_one(
        {"_id": record["_id"], "used": False},
        {"$set": {"used": True}},
    )
    if result.modified_count == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That reset link is invalid or has expired.")

    owner = await db.users.find_one({"user_id": record["user_id"]}, {"_id": 0})
    await db.users.update_one(
        {"user_id": record["user_id"]},
        {"$set": {
            "password_hash": hash_password(payload.password),
            "password_changed_at": datetime.now(timezone.utc).isoformat(),
            # Closes what the comment below used to concede: bearer tokens
            # issued before a reset kept working until they expired, so
            # somebody resetting a password BECAUSE it was compromised left
            # the other party logged in for up to JWT_EXPIRY_DAYS. That is
            # the one situation where a reset most needs to mean something.
            "token_version": int((owner or {}).get("token_version") or 0) + 1,
        }},
    )
    # Server-side sessions go too, so a stolen cookie stops working.
    await db.user_sessions.delete_many({"user_id": record["user_id"]})

    return {"message": "Your password has been reset. You can now log in."}


def _reset_is_live(record: Dict[str, Any]) -> bool:
    expires = record.get("expires_at")
    if isinstance(expires, str):
        try:
            expires = datetime.fromisoformat(expires)
        except ValueError:
            return False
    if not isinstance(expires, datetime):
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires >= datetime.now(timezone.utc)


@router.post("/change-password")
async def change_password(
    payload: ChangePassword,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Change your own password, and sign out everywhere else.

    Until now there was no way to do this at all. `forgot-password` emails a
    reset link, which needs email configured, and there was nothing for
    somebody who simply knows their password and wants a different one. That
    became a real gap when force approval started asking for this password -
    it went from something typed once at signup to something used regularly.

    Everything else is signed out, deliberately. If the reason for changing it
    is that somebody else knows it, leaving their session alive defeats the
    point. Two mechanisms, because there are two kinds of credential:

      * server-side sessions are deleted outright
      * bearer tokens cannot be revoked, so `sessions_valid_from` records the
        moment older ones stopped counting and get_current_user checks it

    The second half is what makes the promise true. Deleting sessions alone
    leaves every issued token working until it expires.
    """
    if not verify_password(payload.current_password, user.get("password_hash")):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "That is not your current password.",
        )

    # Rejected rather than quietly accepted: somebody typing the same value
    # twice has misunderstood what the form does, and telling them costs
    # nothing.
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The new password is the same as the old one.",
        )

    version = int(user.get("token_version") or 0) + 1
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "password_hash": hash_password(payload.new_password),
            "password_changed_at": datetime.now(timezone.utc).isoformat(),
            # Every token issued under the old number stops matching at once.
            "token_version": version,
        }},
    )
    await db.user_sessions.delete_many({"user_id": user["user_id"]})

    # A fresh token for THIS device, issued after the cutoff. Without it the
    # person who just changed their password would be signed out too, which
    # reads as the change having failed.
    return {
        "message": "Password changed. Other devices have been signed out.",
        "token": create_access_token(user["user_id"], version),
    }


@router.get("/me")
async def me(user: Dict[str, Any] = Depends(get_current_user)):
    return _public_user(user)


@router.get("/providers")
async def providers():
    """Which sign-in methods this deployment has configured.

    Lets the frontend hide the Google button when it would not work, instead
    of showing a control that fails on click.
    """
    return {
        "password": True,
        "google": google_auth.enabled,
        "google_client_id": config.GOOGLE_CLIENT_ID or None,
    }


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


@router.post("/delete-account")
async def delete_account(
    payload: account_deletion.DeleteAccountReq,
    response: Response,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Close your own account now, and have everything in it permanently deleted in 30 days.

    The account is closed at once (signed out everywhere, subscription cancelled) but nothing
    is erased until the 30 days are up, and signing in again before then brings it back. It
    asks for two things a mis-click or a borrowed laptop cannot supply: the account's email
    typed out, and proof of who is typing it. The proof is the password, or - for an account
    that signs in with Google and has no password - a fresh Google sign-in, checked here
    against the same Google account.

    WRONG ANSWERS ARE 403, NOT 401. The screen reads a 401 as "your session has expired" and
    drops the sign-in token, so a mistyped password answered with 401 would sign the person
    out instead of letting them try again. The session is fine; what failed is the
    confirmation, which is a refusal, not a failure to authenticate.

    Billing is cancelled first; if that cannot be done, the account is left exactly as it
    was (502). See services/account_deletion.py for the two steps and why.
    """
    if payload.confirm_email.strip().lower() != user["email"].strip().lower():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That is not the email address on this account.",
        )

    if user.get("password_hash"):
        if not payload.password or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "That is not your password.")
    else:
        if not payload.google_credential:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Confirm with Google to delete this account.",
            )
        try:
            profile = google_auth.verify_id_token(payload.google_credential)
        except google_auth.GoogleAuthUnavailable as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
        except google_auth.GoogleAuthInvalid as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
        same_address = profile["email"].strip().lower() == user["email"].strip().lower()
        same_identity = not user.get("google_sub") or profile["google_sub"] == user["google_sub"]
        if not (same_address and same_identity):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "That Google account is not the one this account uses.",
            )

    try:
        scheduled = await account_deletion.request_deletion(user)
    except account_deletion.BillingCleanupFailed as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))

    response.delete_cookie("session_token", path="/")
    return {
        "scheduled": True,
        "delete_on": scheduled.isoformat(),
        "days": account_deletion.GRACE_DAYS,
    }
