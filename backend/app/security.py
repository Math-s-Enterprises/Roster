"""Authentication primitives and the request-scoped auth dependencies.

Two credential mechanisms are supported, and `get_current_user` accepts
either:

  1. `Authorization: Bearer <jwt>` — issued by email/password login and by
     Google sign-in. Self-contained and self-expiring.
  2. `session_token` cookie — a server-side session row. Kept because it is
     httpOnly (JavaScript on the page cannot read it), which makes it
     resistant to token theft via XSS.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt
from fastapi import Cookie, Depends, Header, HTTPException, status

from app import config, db

log = logging.getLogger("roster.security")


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(raw: str) -> str:
    """bcrypt with a per-password random salt.

    A fresh salt each time is why hashing the same password twice yields
    different output — that is what defeats precomputed (rainbow table)
    attacks.
    """
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: Optional[str]) -> bool:
    """Constant-time compare. False (never an exception) on any bad input.

    `hashed` is Optional because Google-only accounts have no password at
    all; those must fail closed rather than crash.
    """
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Password reset tokens
# ---------------------------------------------------------------------------
def generate_reset_token() -> str:
    """A high-entropy, URL-safe token to email to the user.

    Only its hash is ever stored (see hash_reset_token), the same reasoning
    as bcrypt for passwords: a database leak must not hand out anything a
    reader could use directly to reset an account.
    """
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    """SHA-256 is fine here (unlike passwords) because the token itself is
    already 256 bits of randomness, not a human-guessable secret — there is
    no brute-forceable keyspace for a slow hash to defend against."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
def create_access_token(user_id: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=config.JWT_EXPIRY_DAYS)
    return jwt.encode(
        {"user_id": user_id, "exp": expires},
        config.JWT_SECRET,
        algorithm=config.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> Optional[str]:
    """Return the user_id, or None if the token is invalid/expired.

    jwt.decode verifies the signature AND the `exp` claim, so an expired or
    tampered token raises rather than returning stale data.
    """
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
        return payload.get("user_id")
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
) -> Dict[str, Any]:
    """Resolve the caller to a user document, or raise 401.

    Injected into routes via `Depends(get_current_user)`, so authentication
    is declared once per route instead of reimplemented in each handler.
    """
    if authorization and authorization.startswith("Bearer "):
        user_id = decode_access_token(authorization[7:])
        if user_id:
            user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
            if user:
                return user

    if session_token:
        session = await db.user_sessions.find_one({"session_token": session_token}, {"_id": 0})
        if session and _session_is_live(session):
            user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
            if user:
                return user

    raise _UNAUTHENTICATED


def _session_is_live(session: Dict[str, Any]) -> bool:
    expires = session.get("expires_at")
    if isinstance(expires, str):
        try:
            expires = datetime.fromisoformat(expires)
        except ValueError:
            return False
    if not isinstance(expires, datetime):
        return False
    # Mongo round-trips can drop tzinfo; comparing naive to aware raises.
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires >= datetime.now(timezone.utc)


CurrentUser = Depends(get_current_user)
