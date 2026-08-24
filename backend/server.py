"""Backwards-compatible entry point.

The application now lives in the `app` package. This shim exists so that
`uvicorn server:app` keeps working alongside the canonical form:

    uvicorn app.main:app --reload --port 8001

Prefer the canonical form in new scripts and deployment configs.
"""
from app.main import app

__all__ = ["app"]
