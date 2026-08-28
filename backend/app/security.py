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
def create_access_token(user_id: str, token_version: int = 0) -> str:
    """A bearer token for this user, stamped with their token version.

    The version is what makes "changing your password signs you out
    everywhere" true. Deleting server-side sessions is not enough: a bearer
    token cannot be revoked, so every one already issued keeps working until
    it expires — up to JWT_EXPIRY_DAYS of somebody else still logged in as
    you, which is exactly what you change a password to stop.

    A COUNTER rather than a timestamp, and that was not the first attempt.
    Comparing against "the password last changed at" fails on sub-second
    precision: a JWT `iat` is whole seconds, so the token issued by the very
    request that set the cutoff looks older than it. Rounding the cutoff down
    fixes that and opens a one-second window where an old token still passes.
    A counter has no windows and no clock in it — the number either matches
    or it does not.
    """
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=config.JWT_EXPIRY_DAYS)
    return jwt.encode(
        {"user_id": user_id, "exp": expires, "iat": now, "ver": token_version},
        config.JWT_SECRET,
        algorithm=config.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> Optional[str]:
    """Return the user_id, or None if the token is invalid/expired.

    jwt.decode verifies the signature AND the `exp` claim, so an expired or
    tampered token raises rather than returning stale data.
    """
    claims = decode_access_claims(token)
    return claims.get("user_id") if claims else None


def decode_access_claims(token: str) -> Optional[Dict[str, Any]]:
    """The whole payload, for callers that need `iat` as well as the user."""
    try:
        return jwt.decode(
            token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM],
        )
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
        claims = decode_access_claims(authorization[7:])
        if claims and claims.get("user_id"):
            user = await db.users.find_one(
                {"user_id": claims["user_id"]}, {"_id": 0},
            )
            if user and _token_still_valid(claims, user):
                return user

    if session_token:
        session = await db.user_sessions.find_one({"session_token": session_token}, {"_id": 0})
        if session and _session_is_live(session):
            user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
            if user:
                return user

    raise _UNAUTHENTICATED


def _token_still_valid(claims: Dict[str, Any], user: Dict[str, Any]) -> bool:
    """False for a token issued before the user's version was last bumped.

    A JWT cannot be revoked — that is the trade for not looking the session up
    on every request. So the user document carries a counter, the token
    carries the value it was issued under, and they have to agree.

    Both default to 0, so tokens issued before this existed keep working on
    accounts that have never changed a password. The first change bumps the
    counter to 1 and every older token stops matching at once.
    """
    return int(claims.get("ver") or 0) == int(user.get("token_version") or 0)


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
