"""Authentication routes: signup, login, Google sign-in, session, logout."""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pymongo.errors import DuplicateKeyError

from app import config, db
from app.models import (
    ChangePassword,
    ForgotPasswordReq,
    GoogleAuthReq,
    LoginReq,
    ResetPasswordReq,
    SignupReq,
)
from app.security import (
    create_access_token,
    generate_reset_token,
    get_current_user,
    hash_password,
    hash_reset_token,
    verify_password,
)
from app.services import google_auth
from app.services.mailer import send_password_reset_email
from app.services.shop_service import ensure_shop

log = logging.getLogger("roster.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
)


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Everything safe to send to the browser — never the password hash."""
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user.get("name"),
        "picture": user.get("picture"),
        "pro": bool(user.get("pro", False)),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupReq):
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    document = {
        "user_id": user_id,
        "email": payload.email.lower(),
        "name": payload.name,
        "password_hash": hash_password(payload.password),
        "shop_name": payload.shop_name,
        "pro": False,
        "created_at": _now(),
    }

    try:
        await db.users.insert_one(dict(document))
    except DuplicateKeyError:
        # The unique index on `email` is the real guarantee here. A prior
        # "does this email exist?" lookup would not be atomic — two
        # simultaneous signups could both pass it — so we let the database
        # arbitrate and translate its error.
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already registered")

    await ensure_shop(document)
    return {
        "token": create_access_token(user_id, document.get("token_version", 0)),
        "user": _public_user(document),
    }


@router.post("/login")
async def login(payload: LoginReq):
    user = await db.users.find_one({"email": payload.email.lower()}, {"_id": 0})
    if not user or not verify_password(payload.password, user.get("password_hash")):
        # Deliberately identical response for "no such user" and "wrong
        # password" so the endpoint cannot be used to enumerate accounts.
        raise _INVALID_CREDENTIALS

    await ensure_shop(user)
    return {
        "token": create_access_token(
            user["user_id"], user.get("token_version", 0),
        ),
        "user": _public_user(user),
    }


@router.post("/google")
async def google_sign_in(payload: GoogleAuthReq):
    """Exchange a verified Google ID token for our own access token."""
    try:
        profile = google_auth.verify_id_token(payload.credential)
    except google_auth.GoogleAuthUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    except google_auth.GoogleAuthInvalid as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc))

    user = await db.users.find_one({"email": profile["email"]}, {"_id": 0})
    if user:
        # Link the Google identity to the existing local account and refresh
        # the profile picture, but never overwrite an existing password.
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"google_sub": profile["google_sub"], "picture": profile["picture"]}},
        )
        user = {**user, "picture": profile["picture"]}
    else:
        user = {
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": profile["email"],
            "name": profile["name"],
            "picture": profile["picture"],
            "google_sub": profile["google_sub"],
            "pro": False,
            "created_at": _now(),
        }
        try:
            await db.users.insert_one(dict(user))
        except DuplicateKeyError:
            # Lost a race with a concurrent signup for the same address.
            user = await db.users.find_one({"email": profile["email"]}, {"_id": 0})
            if not user:
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create account")

    await ensure_shop(user)
    return {
        "token": create_access_token(
            user["user_id"], user.get("token_version", 0),
        ),
        "user": _public_user(user),
    }


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordReq):
    """Start a password reset. Always looks the same to the caller.

    Returning a different response for "no such account" than for "email
    sent" would let this endpoint enumerate registered addresses, so the
    response is identical either way — the real work happens only if a
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
        log.warning("Password reset email to %s failed: %s", user["email"], error)

    return generic


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordReq):
    record = await db.password_resets.find_one({"token_hash": hash_reset_token(payload.token)})
    if not record or record.get("used") or not _reset_is_live(record):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That reset link is invalid or has expired.")

    # Marked used immediately (not deleted) so a replayed request — the same
    # link submitted twice, e.g. via a double click or an email link
    # prefetcher — fails instead of silently resetting the password again.
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
    became a real gap when force approval started asking for this password —
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
