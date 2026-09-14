"""LLM integration — official Anthropic SDK (replaces the Emergent proxy).

Three narrow, stateless jobs:
  1. a short narrative summary of a generated roster;
  2. OCR of a photographed/scanned roster into structured shifts;
  3. compiling a free-text scheduling rule into a JSON constraint.

The LLM deliberately does NOT decide who works when. That is
services/scheduler.py, which is deterministic, debuggable and auditable —
important when the output must satisfy labour law.

If ANTHROPIC_API_KEY is unset, `enabled` is False and each function raises
LLMUnavailable, which routes translate into a clear 503. The app still runs;
only these three features are inert.
"""
import base64
import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from app import config
from app.services.rule_parser import validate_constraint

log = logging.getLogger("roster.llm")

enabled = config.LLM_ENABLED


class LLMUnavailable(RuntimeError):
    """Raised when an LLM feature is used without a configured API key."""


_client: Optional[Any] = None


def _get_client():
    """Lazily construct the SDK client.

    Lazy so that importing this module never fails, and so a missing or
    broken `anthropic` install only affects the three AI features rather
    than preventing the server from booting.
    """
    global _client
    if not enabled:
        raise LLMUnavailable(
            "AI features are disabled. Set ANTHROPIC_API_KEY in backend/.env to enable them."
        )
    if _client is None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise LLMUnavailable(
                "The 'anthropic' package is not installed. Run: pip install -r requirements.txt"
            ) from exc
        _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


async def _complete(
    system: str,
    content: Any,
    *,
    max_tokens: int = 1024,
    output_schema: Optional[Dict[str, Any]] = None,
) -> str:
    client = _get_client()
    options = {}
    if output_schema:
        options["output_config"] = {
            "format": {"type": "json_schema", "schema": output_schema}
        }
    message = await client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        **options,
    )
    return "".join(block.text for block in message.content if block.type == "text")


def _extract_json(raw: str) -> Dict[str, Any]:
    """Pull the first JSON object out of a model response.

    Models often wrap JSON in prose or a ```json fence despite instructions,
    so we locate the outermost braces rather than trusting the whole string
    to parse.
    """
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError(f"No JSON object found in model response: {raw[:200]}")
    return json.loads(match.group(0))


# ---------------------------------------------------------------------------
# 1. Roster summary
# ---------------------------------------------------------------------------
async def summarise_roster(
    week_start: str,
    shift_count: int,
    compliance_score: int,
    labor_cost: float,
    issues: List[str],
) -> str:
    system = (
        "You are an expert retail workforce planner. Reply in exactly two short "
        "sentences: one assessment, one concrete optimisation tip. No preamble."
    )
    prompt = (
        f"Week starting {week_start}. {shift_count} shifts scheduled. "
        f"Compliance score {compliance_score}/100. Labour cost €{labor_cost:.2f}. "
        f"Outstanding issues: {issues[:5] or 'none'}."
    )
    return (await _complete(system, prompt, max_tokens=300)).strip()


# ---------------------------------------------------------------------------
# 2. Roster OCR
# ---------------------------------------------------------------------------
_OCR_SYSTEM = (
    "You extract weekly retail rosters from images. Return STRICT JSON only, no prose. "
    'Schema: {"week_start":"YYYY-MM-DD (the Monday)","shifts":[{"employee_name":"...",'
    '"day":"mon|tue|wed|thu|fri|sat|sun","start":"HH:MM","end":"HH:MM","role":"...",'
    '"note":"holiday|sick|off|"}]}. '
    "Use 24-hour times. Match names to the known employee list where possible; "
    "otherwise reproduce the name as shown."
)

_MEDIA_TYPES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
    b"GIF8": "image/gif",
    b"RIFF": "image/webp",
}


def _sniff_media_type(data: bytes) -> str:
    for signature, media_type in _MEDIA_TYPES.items():
        if data.startswith(signature):
            return media_type
    return "image/jpeg"


#async def ocr_roster_image(image_url: str, known_employee_names: List[str]) -> Dict[str, Any]:
#    """Read a roster image from a URL."""
#    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
#        response = await http.get(image_url)
#        response.raise_for_status()
#    return await ocr_roster_bytes(response.content, known_employee_names)


async def ocr_roster_bytes(
    image_bytes: bytes, known_employee_names: List[str]
) -> Dict[str, Any]:
    """Read a roster image already in memory.

    The uploaded-file path never has a URL to fetch, and writing the bytes to
    a temporary public location just to read them back would be slower and
    would expose staff data unnecessarily.
    """
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _sniff_media_type(image_bytes),
                "data": base64.b64encode(image_bytes).decode(),
            },
        },
        {
            "type": "text",
            "text": (
                f"Known employees at this shop: {known_employee_names}. "
                "Extract the roster as strict JSON per the schema."
            ),
        },
    ]
    raw = await _complete(_OCR_SYSTEM, content, max_tokens=4096)
    return _extract_json(raw)


# ---------------------------------------------------------------------------
# 3. Rule compilation
# ---------------------------------------------------------------------------
ROSTER_RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "rule_type": {
            "type": "string",
            "enum": [
                "ROLE_REQUIREMENT", "NO_CLOSE", "NO_OPEN", "NO_DAY",
                "MAX_STAFF", "NOT_TOGETHER", "ROTATING_DAY_OFF",
            ],
        },
        "target_roles": {"type": "array", "items": {"type": "string"}},
        "time_slot": {"type": "string", "enum": ["CLOSING"]},
        "min_count": {"type": "integer"},
        "condition": {"type": "string", "enum": ["AT_LEAST"]},
        "employee_ids": {"type": "array", "items": {"type": "string"}},
        "days": {
            "type": "array",
            "items": {"type": "string", "enum": [
                "mon", "tue", "wed", "thu", "fri", "sat", "sun",
            ]},
        },
        "value": {"type": "integer"},
        "description": {"type": "string"},
    },
    "required": ["rule_type"],
    "additionalProperties": False,
}

_RULE_SYSTEM = (
    "You are a rule compiler for a deterministic workforce scheduler. "
    "For a closing requirement use ROLE_REQUIREMENT with target_roles, "
    "time_slot CLOSING, min_count 1 and condition AT_LEAST. Use the other "
    "rule types only for their literal meaning. Omit days to mean every "
    "trading day. Closing means the final interval before the shop's "
    "configured closing time; never invent a clock time. Only reference "
    "employee IDs from the supplied list."
)


async def compile_rule(
    title: str,
    description: str,
    employees: List[Dict[str, Any]],
) -> Dict[str, Any]:
    roster = [
        {"id": e["employee_id"], "name": e["name"], "role": e.get("role")}
        for e in employees
    ]
    prompt = f"Known employees: {roster}\n\nRule: {title} — {description}"
    raw = await _complete(
        _RULE_SYSTEM, prompt, max_tokens=1024, output_schema=ROSTER_RULE_SCHEMA
    )
    return validate_constraint(
        _extract_json(raw), {employee["id"] for employee in roster}
    )
