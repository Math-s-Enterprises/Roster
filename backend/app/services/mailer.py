"""Transactional email via Resend (replaces the Emergent email proxy).

Resend's REST API is a single POST, so we call it with httpx rather than
adding another SDK dependency.

Disabled cleanly when RESEND_API_KEY is unset: send_roster_emails reports
every recipient as failed with a clear reason instead of raising, so roster
dispatch degrades to a visible no-op rather than a 500.
"""
import asyncio
import html
import logging
from typing import Any, Dict, List, Optional

import httpx

from app import config

log = logging.getLogger("roster.mailer")

RESEND_ENDPOINT = "https://api.resend.com/emails"
enabled = config.EMAIL_ENABLED

# Resend's published limit is 2 requests/second on the free tier; sending a
# whole team's rosters in parallel would trip it. A small semaphore plus a
# short delay keeps us comfortably under while still beating fully
# sequential sending.
_MAX_CONCURRENT_SENDS = 2
_DAY_LABELS = {
    "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
    "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
}


def render_roster_email(
    employee_name: str,
    shop_name: str,
    week_start: str,
    shifts: List[Dict[str, Any]],
    version: str,
) -> str:
    """Build the HTML for one employee's weekly schedule.

    Every interpolated value is HTML-escaped: employee and shop names are
    user-supplied, so injecting them raw would allow HTML/script injection
    into the email body.
    """
    safe_name = html.escape(employee_name)
    safe_shop = html.escape(shop_name)

    ordered = sorted(shifts, key=lambda s: (list(_DAY_LABELS).index(s["day"]), s["start"]))
    if ordered:
        rows = "".join(
            f'<tr>'
            f'<td style="padding:10px 14px;color:#a1a1aa;font-family:monospace;">'
            f'{html.escape(_DAY_LABELS.get(s["day"], s["day"]))}</td>'
            f'<td style="padding:10px 14px;color:#ffffff;font-family:monospace;">'
            f'{html.escape(s["start"])} – {html.escape(s["end"])}</td>'
            f'</tr>'
            for s in ordered
        )
    else:
        rows = (
            '<tr><td colspan="2" style="padding:14px;color:#a1a1aa;">'
            "No shifts scheduled this week.</td></tr>"
        )

    return f"""<div style="background:#05050A;padding:32px;font-family:Arial,Helvetica,sans-serif;color:#ffffff;">
  <table width="100%" style="max-width:560px;margin:auto;background:#0A0B10;border:1px solid rgba(255,255,255,0.08);border-radius:16px;overflow:hidden;">
    <tr><td style="padding:24px 24px 8px 24px;">
      <div style="color:#00E5FF;font-size:22px;font-weight:700;">{safe_shop}</div>
      <div style="color:#a1a1aa;font-size:13px;margin-top:4px;">Roster {html.escape(version)} · week of {html.escape(week_start)}</div>
    </td></tr>
    <tr><td style="padding:16px 24px;color:#ffffff;">
      <p style="margin:0 0 8px 0;">Hi {safe_name},</p>
      <p style="margin:0;">Your shifts for the upcoming week are below.</p>
    </td></tr>
    <tr><td style="padding:0 24px 24px 24px;">
      <table width="100%" style="background:#05050A;border-radius:12px;border:1px solid rgba(255,255,255,0.08);border-collapse:separate;">{rows}</table>
    </td></tr>
    <tr><td style="padding:0 24px 24px 24px;color:#71717A;font-size:12px;">Sent via Roster</td></tr>
  </table>
</div>"""


async def _send_one(
    http: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    to: str,
    subject: str,
    body_html: str,
) -> Optional[str]:
    """Send a single email. Returns None on success, or an error string."""
    async with semaphore:
        try:
            response = await http.post(
                RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
                json={
                    "from": config.EMAIL_FROM,
                    "to": [to],
                    "subject": subject,
                    "html": body_html,
                },
            )
            response.raise_for_status()
            await asyncio.sleep(0.5)  # stay within the provider's rate limit
            return None
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:200]
            log.warning("Email to %s failed: %s %s", to, exc.response.status_code, detail)
            return f"{exc.response.status_code}: {detail}"
        except Exception as exc:  # network error, timeout, DNS failure...
            log.warning("Email to %s failed: %s", to, exc)
            return str(exc)[:200]


def render_password_reset_email(name: str, reset_url: str, expiry_minutes: int) -> str:
    """Build the HTML for a password-reset email.

    `reset_url` is our own link (built from FRONTEND_URL + a server-generated
    token), never user-supplied, so it does not need escaping. The name does.
    """
    safe_name = html.escape(name or "there")
    return f"""<div style="background:#05050A;padding:32px;font-family:Arial,Helvetica,sans-serif;color:#ffffff;">
  <table width="100%" style="max-width:560px;margin:auto;background:#0A0B10;border:1px solid rgba(255,255,255,0.08);border-radius:16px;overflow:hidden;">
    <tr><td style="padding:24px 24px 8px 24px;">
      <div style="color:#00E5FF;font-size:22px;font-weight:700;">Roster</div>
    </td></tr>
    <tr><td style="padding:16px 24px;color:#ffffff;">
      <p style="margin:0 0 8px 0;">Hi {safe_name},</p>
      <p style="margin:0 0 16px 0;">We received a request to reset your password. This link expires in
      {expiry_minutes} minutes and can only be used once.</p>
      <p style="margin:0 0 24px 0;">
        <a href="{reset_url}" style="display:inline-block;background:#00E5FF;color:#05050A;
           font-weight:700;text-decoration:none;padding:12px 24px;border-radius:999px;">
          Reset your password
        </a>
      </p>
      <p style="margin:0;color:#a1a1aa;font-size:13px;">
        If you didn't request this, you can safely ignore this email — your password will not change.
      </p>
    </td></tr>
    <tr><td style="padding:0 24px 24px 24px;color:#71717A;font-size:12px;">Sent via Roster</td></tr>
  </table>
</div>"""


async def send_password_reset_email(to: str, name: str, reset_url: str, expiry_minutes: int) -> Optional[str]:
    """Send one password-reset email. Returns None on success, or an error string.

    Mirrors send_roster_emails' degrade-not-crash behaviour: when email isn't
    configured, the caller still returns its generic "check your inbox"
    response (so the endpoint never reveals whether the address exists), but
    logs loudly here so a developer notices resets are silently not sending.
    """
    if not enabled:
        log.warning("Password reset requested for %s but email is not configured.", to)
        return "Email is not configured (RESEND_API_KEY is unset)."

    async with httpx.AsyncClient(timeout=30) as http:
        return await _send_one(
            http,
            asyncio.Semaphore(_MAX_CONCURRENT_SENDS),
            to,
            "Reset your Roster password",
            render_password_reset_email(name, reset_url, expiry_minutes),
        )


async def send_roster_emails(
    shop_name: str,
    week_start: str,
    version: str,
    recipients: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Email each recipient their own shifts.

    `recipients` items need: employee_id, name, email, shifts.

    Sends concurrently but rate-limited. Crucially, one failure never
    prevents the remaining recipients from being emailed — every result is
    collected and reported, so a single bad address cannot silently cost the
    rest of the team their schedule.
    """
    if not enabled:
        reason = "Email is not configured (RESEND_API_KEY is unset)."
        return {
            "sent": [],
            "failed": [
                {"employee_id": r["employee_id"], "name": r["name"],
                 "email": r["email"], "error": reason}
                for r in recipients
            ],
        }

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SENDS)
    subject = f"Your schedule · {shop_name} · week of {week_start}"

    async with httpx.AsyncClient(timeout=30) as http:
        outcomes = await asyncio.gather(*[
            _send_one(
                http, semaphore, recipient["email"], subject,
                render_roster_email(
                    recipient["name"], shop_name, week_start,
                    recipient.get("shifts", []), version,
                ),
            )
            for recipient in recipients
        ], return_exceptions=True)

    sent, failed = [], []
    for recipient, outcome in zip(recipients, outcomes):
        entry = {
            "employee_id": recipient["employee_id"],
            "name": recipient["name"],
            "email": recipient["email"],
        }
        if isinstance(outcome, Exception):
            failed.append({**entry, "error": str(outcome)[:200]})
        elif outcome is None:
            sent.append(entry)
        else:
            failed.append({**entry, "error": outcome})

    return {"sent": sent, "failed": failed}
