"""Shared, atomic authentication limits; no raw client addresses are stored."""
import hashlib
import time
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from app import db

LIMITS = {
    "/api/auth/login": (20, 60),
    "/api/auth/google": (20, 60),
    "/api/auth/signup": (5, 900),
    "/api/auth/forgot-password": (5, 900),
    "/api/auth/reset-password": (10, 60),
}


async def check_auth_rate_limit(request: Request):
    policy = LIMITS.get(request.url.path)
    if request.method != "POST" or not policy:
        return
    limit, seconds = policy
    now = int(time.time())
    window = now // seconds
    # Forwarded headers are only safe when Uvicorn trusts the actual proxy.
    address = request.client.host if request.client else "unknown"
    digest = hashlib.sha256(address.encode()).hexdigest()
    key = f"{request.url.path}:{digest}:{window}"
    try:
        counter = await db.auth_rate_limits.find_one_and_update(
            {"_id": key},
            {"$inc": {"count": 1}, "$setOnInsert": {
                "expires_at": datetime.fromtimestamp((window + 1) * seconds, timezone.utc),
            }},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
    except PyMongoError:
        raise HTTPException(503, "Sign-in is temporarily unavailable. Please try again later.")
    if counter["count"] > limit:
        raise HTTPException(
            429, "Too many attempts. Please wait before trying again.",
            headers={"Retry-After": str((window + 1) * seconds - now)},
        )
