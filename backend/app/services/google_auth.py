"""Google sign-in (replaces the Emergent OAuth proxy).

FLOW
----
The browser renders Google Identity Services, the user picks an account, and
Google hands the page a signed ID token (a JWT). The frontend POSTs that
token here; we verify its signature against Google's public keys and read
the verified email/name/picture from it.

Why this flow rather than the classic authorization-code exchange: no client
secret is needed, there is no redirect round-trip to manage, and it suits a
single-page app. The client ID is public by design — it ships in the
frontend bundle.

Verification is not optional. An unverified ID token is just attacker-
supplied JSON; without checking the signature, issuer and audience, anyone
could claim to be any user.
"""
import logging
from typing import Any, Dict

from app import config

log = logging.getLogger("roster.google")

enabled = config.GOOGLE_ENABLED

_VALID_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class GoogleAuthUnavailable(RuntimeError):
    """Raised when Google sign-in is used without GOOGLE_CLIENT_ID set."""


class GoogleAuthInvalid(ValueError):
    """Raised when a supplied credential fails verification."""


def _request():
    try:
        from google.auth.transport import requests as google_requests
    except ImportError as exc:
        raise GoogleAuthUnavailable(
            "The 'google-auth' package is not installed. Run: pip install -r requirements.txt"
        ) from exc
    return google_requests.Request()


def verify_id_token(credential: str) -> Dict[str, Any]:
    """Verify a Google ID token and return the caller's profile.

    Raises GoogleAuthInvalid if the token is forged, expired, issued by
    someone else, or intended for a different application.
    """
    if not enabled:
        raise GoogleAuthUnavailable(
            "Google sign-in is disabled. Set GOOGLE_CLIENT_ID in backend/.env to enable it."
        )

    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.exceptions import GoogleAuthError, TransportError
    except ImportError as exc:
        raise GoogleAuthUnavailable(
            "The 'google-auth' package is not installed. Run: pip install -r requirements.txt"
        ) from exc

    try:
        # Checks the signature against Google's rotating public keys, the
        # expiry, and that `aud` matches our client ID.
        claims = google_id_token.verify_oauth2_token(
            credential, _request(), config.GOOGLE_CLIENT_ID, clock_skew_in_seconds=5
        )
    except TransportError as exc:
        raise GoogleAuthUnavailable("Google sign-in is temporarily unavailable. Please try again later.") from exc
    except (ValueError, GoogleAuthError) as exc:
        raise GoogleAuthInvalid("Google sign-in could not be verified. Please try again.") from exc

    if claims.get("iss") not in _VALID_ISSUERS:
        raise GoogleAuthInvalid("Unexpected token issuer.")

    email = claims.get("email")
    if not email:
        raise GoogleAuthInvalid("Google account has no email address.")

    # Verified email alone does not establish current ownership outside Gmail/Workspace.
    if not claims.get("email_verified"):
        raise GoogleAuthInvalid("This Google account's email address is not verified.")

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise GoogleAuthInvalid("Google account has no valid identity.")

    return {
        "email": email.lower(),
        "name": claims.get("name") or email.split("@")[0],
        "picture": claims.get("picture"),
        "google_sub": subject,
        "email_authoritative": email.lower().endswith("@gmail.com") or bool(claims.get("hd")),
    }
