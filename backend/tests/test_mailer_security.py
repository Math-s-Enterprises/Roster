"""Email failures stay useful without putting private data in logs."""
import asyncio
import logging

import httpx

from app.services import mailer


RECIPIENT = "private.person@example.com"
PRIVATE_DETAIL = "provider echoed private.person@example.com and message content"


class RejectedHTTP:
    async def post(self, *_args, **_kwargs):
        request = httpx.Request("POST", mailer.RESEND_ENDPOINT)
        return httpx.Response(422, request=request, text=PRIVATE_DETAIL)


class BrokenHTTP:
    async def post(self, *_args, **_kwargs):
        raise RuntimeError(PRIVATE_DETAIL)


def _send(http):
    return asyncio.run(mailer._send_one(
        http,
        asyncio.Semaphore(1),
        RECIPIENT,
        "Private roster",
        "<p>Private roster contents</p>",
    ))


def test_provider_rejection_logs_only_the_status(caplog):
    caplog.set_level(logging.WARNING, logger="roster.mailer")

    error = _send(RejectedHTTP())

    assert "422" in caplog.text
    assert "422" in error
    assert RECIPIENT not in caplog.text
    assert PRIVATE_DETAIL not in caplog.text
    assert RECIPIENT not in error
    assert PRIVATE_DETAIL not in error


def test_network_failure_logs_only_the_exception_type(caplog):
    caplog.set_level(logging.WARNING, logger="roster.mailer")

    error = _send(BrokenHTTP())

    assert "RuntimeError" in caplog.text
    assert "RuntimeError" in error
    assert RECIPIENT not in caplog.text
    assert PRIVATE_DETAIL not in caplog.text
    assert RECIPIENT not in error
    assert PRIVATE_DETAIL not in error


def test_disabled_password_reset_does_not_log_the_address(caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger="roster.mailer")
    monkeypatch.setattr(mailer, "enabled", False)

    error = asyncio.run(mailer.send_password_reset_email(
        RECIPIENT, "Private Person", "https://example.test/reset?token=secret", 15,
    ))

    assert "not configured" in caplog.text
    assert RECIPIENT not in caplog.text
    assert "secret" not in caplog.text
    assert "not configured" in error
