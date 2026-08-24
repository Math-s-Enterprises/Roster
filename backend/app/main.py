"""FastAPI application assembly.

Run it with:
    uvicorn app.main:app --reload --port 8001
"""
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config, db
from app.routes import (
    ai_rules, auth, dev, holidays, imports, payments, reports, rosters, shop,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("roster")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown.

    Replaces the deprecated @app.on_event hooks. Indexes are ensured on
    every boot — cheap when they already exist, and it means a fresh
    database is correctly constrained without a manual migration step.
    """
    await db.ensure_indexes()

    log.info("Roster API starting (env=%s)", config.ENV)
    log.info(
        "  AI features:   %s", "enabled" if config.LLM_ENABLED
        else "DISABLED (set ANTHROPIC_API_KEY)"
    )
    log.info(
        "  Email:         %s", "enabled" if config.EMAIL_ENABLED
        else "DISABLED (set RESEND_API_KEY)"
    )
    log.info(
        "  Google login:  %s", "enabled" if config.GOOGLE_ENABLED
        else "DISABLED (set GOOGLE_CLIENT_ID)"
    )
    log.info(
        "  Billing:       %s", "enabled" if config.STRIPE_ENABLED
        else "DISABLED (set STRIPE_SECRET_KEY)"
    )
    if config.DEV_ROUTES_ENABLED:
        log.warning("  Dev routes are ENABLED (/dev/reset, /seed-demo)")

    yield

    await db.close()
    log.info("Roster API stopped")


app = FastAPI(
    title="Roster API",
    description="AI-assisted staff scheduling for small retail businesses.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS must be permissive enough for the browser app but no more. A wildcard
# origin is incompatible with credentialed requests, so an explicit list is
# required in any deployment that uses cookie auth.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Everything the browser calls lives under /api.
api = APIRouter(prefix="/api")
api.include_router(auth.router)
api.include_router(shop.router)
api.include_router(ai_rules.router)
api.include_router(rosters.router)
api.include_router(imports.router)
api.include_router(holidays.router)
api.include_router(reports.router)
api.include_router(payments.router)

if config.DEV_ROUTES_ENABLED:
    api.include_router(dev.router)

app.include_router(api)


@app.get("/api/health", tags=["meta"])
async def health():
    """Liveness probe, and a quick way to see which integrations are live."""
    return {
        "status": "ok",
        "env": config.ENV,
        "features": {
            "llm": config.LLM_ENABLED,
            "email": config.EMAIL_ENABLED,
            "google_auth": config.GOOGLE_ENABLED,
            "billing": config.STRIPE_ENABLED,
        },
    }


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "Roster API", "docs": "/docs"}
