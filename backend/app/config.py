"""Central configuration.

Every environment variable the app reads is declared here, in one place,
with an explicit note about whether it is REQUIRED (app refuses to boot
without it) or OPTIONAL (feature degrades gracefully when absent).

Design rule: the app must boot with only MONGO_URL, DB_NAME and JWT_SECRET
set. Every third-party integration (Anthropic, Resend, Google, Stripe) is
optional, and the feature that depends on it returns a clear 503 instead of
crashing the server or failing at import time. That is what makes the
project runnable by a new developer on day one.
"""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
load_dotenv(BASE_DIR / ".env")


class _Missing:
    """Sentinel so we can tell 'not set' apart from 'set to empty string'."""


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Required environment variable {name!r} is not set. "
            f"Copy backend/.env.example to backend/.env and fill it in."
        )
    return val


def _clean(value: str) -> str:
    """Trim whitespace and any quotes the value was pasted with.

    A client ID copied out of a console often arrives as `"123-abc.apps..."`
    or with a trailing space. Left as-is those fail deep inside a library
    with a message about an audience mismatch, which points nowhere near the
    real cause.
    """
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def _optional(name: str, default: str = "") -> str:
    return _clean(os.environ.get(name, "")) or default


# ---------------------------------------------------------------------------
# REQUIRED
# ---------------------------------------------------------------------------
MONGO_URL = _require("MONGO_URL")
DB_NAME = _require("DB_NAME")

# In development we generate an ephemeral secret rather than hard-failing, so
# a new dev can boot immediately. It is regenerated on every restart, which
# invalidates existing tokens — acceptable locally, fatal in production, so
# production explicitly requires it to be set.
ENV = _optional("ENV", "development").lower()
IS_PRODUCTION = ENV in ("production", "prod")

if IS_PRODUCTION:
    JWT_SECRET = _require("JWT_SECRET")
else:
    JWT_SECRET = _optional("JWT_SECRET") or secrets.token_hex(32)

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = int(_optional("JWT_EXPIRY_DAYS", "7"))


# ---------------------------------------------------------------------------
# OPTIONAL — LLM (roster summary, roster-photo OCR, rule compilation)
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = _optional("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _optional("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
LLM_ENABLED = bool(ANTHROPIC_API_KEY)


# ---------------------------------------------------------------------------
# OPTIONAL — transactional email (roster dispatch to staff)
# ---------------------------------------------------------------------------
RESEND_API_KEY = _optional("RESEND_API_KEY")
EMAIL_FROM = _optional("EMAIL_FROM", "Roster <onboarding@resend.dev>")
EMAIL_ENABLED = bool(RESEND_API_KEY)


# ---------------------------------------------------------------------------
# Frontend origin — used to build links inside outgoing emails (password
# reset). Not the same as CORS_ORIGINS: that's a security allowlist, this is
# just where a human clicking the link should land.
# ---------------------------------------------------------------------------
FRONTEND_URL = _optional("FRONTEND_URL", "http://localhost:3000").rstrip("/")

PASSWORD_RESET_EXPIRY_MINUTES = int(_optional("PASSWORD_RESET_EXPIRY_MINUTES", "60"))


# ---------------------------------------------------------------------------
# OPTIONAL — Google sign-in
# The client ID is public (it also ships to the browser). No client secret is
# needed: we use Google Identity Services on the frontend to obtain an ID
# token, then verify that token's signature here.
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID = _optional("GOOGLE_CLIENT_ID")
GOOGLE_ENABLED = bool(GOOGLE_CLIENT_ID)


# ---------------------------------------------------------------------------
# OPTIONAL — Stripe billing
# ---------------------------------------------------------------------------
STRIPE_SECRET_KEY = _optional("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = _optional("STRIPE_WEBHOOK_SECRET")
STRIPE_ENABLED = bool(STRIPE_SECRET_KEY)

# When True, roster generation is capped for users without an active
# subscription. Off by default so local development is unrestricted.
BILLING_ENFORCED = _optional("BILLING_ENFORCED", "false").lower() == "true"
FREE_PLAN_ROSTER_LIMIT = int(_optional("FREE_PLAN_ROSTER_LIMIT", "4"))


# ---------------------------------------------------------------------------
# OPTIONAL — CORS / dev tooling
# ---------------------------------------------------------------------------
_cors = _optional("CORS_ORIGINS", "http://localhost:3000")
CORS_ORIGINS = [o.strip() for o in _cors.split(",") if o.strip()]

# Destructive helper routes (/dev/reset, /seed-demo). Hard-disabled in
# production regardless of this flag.
DEV_ROUTES_ENABLED = (
    not IS_PRODUCTION and _optional("DEV_ROUTES_ENABLED", "true").lower() == "true"
)
