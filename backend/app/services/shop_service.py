"""Shop lifecycle, defaults, and the immutable system rules."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app import db
from app.services.scheduler import ABSOLUTE_MAX_SHIFT_HOURS, DAYS, MIN_REST_HOURS

DEFAULT_HOURS: List[Dict[str, Any]] = [
    {"day": day, "open": "09:00", "close": "21:00", "closed": False}
    for day in ("mon", "tue", "wed", "thu", "fri", "sat")
] + [{"day": "sun", "open": "10:00", "close": "18:00", "closed": False}]

DEFAULT_ROLES = ["Manager", "Supervisor", "Cashier", "Floor Assistant", "Stocker"]
DEFAULT_DEPARTMENTS = ["Shop Floor", "Deli"]

DEFAULT_24H_TEMPLATES = [
    {"template_id": "tpl_morning", "name": "Morning", "start": "07:00", "end": "15:00", "min_staff": 2},
    {"template_id": "tpl_afternoon", "name": "Afternoon", "start": "15:00", "end": "23:00", "min_staff": 2},
    {"template_id": "tpl_night", "name": "Night", "start": "23:00", "end": "07:00", "min_staff": 1},
]

# `locked: True` rules cannot be edited, disabled or deleted through the API.
# They encode guarantees the product makes about every roster it produces, so
# a shop owner must not be able to switch them off. Enforcement lives in the
# ai_rules routes; this is the source of truth for what is locked.
SYSTEM_RULES: List[Dict[str, Any]] = [
    {
        "title": "Under-16 curfew",
        "description": "Employees under 16 cannot work before 08:00 or past 19:00, and never overnight.",
        "category": "legal", "enabled": True, "locked": True,
    },
    {
        "title": "Weekly hour cap",
        "description": "No employee may exceed their configured maximum weekly hours.",
        "category": "legal", "enabled": True, "locked": True,
    },
    {
        "title": "Maximum shift length",
        # Built from the constant the solver enforces. Written out by hand it
        # said "11 hours" long after the limit had changed — a locked rule
        # that misstates what the product actually does is worse than none.
        "description": f"No single shift may exceed {ABSOLUTE_MAX_SHIFT_HOURS} hours.",
        "category": "legal", "enabled": True, "locked": True,
    },
    {
        "title": "Rest between shifts",
        "description": (
            f"At least {MIN_REST_HOURS:g} consecutive hours off between "
            f"finishing one shift and starting the next."
        ),
        "category": "legal", "enabled": True, "locked": True,
    },
    {
        "title": "Continuous shop coverage",
        "description": "At least one employee is scheduled for every minute the shop is open — no gaps between opening and closing.",
        "category": "safety", "enabled": True, "locked": True,
    },
    {
        "title": "24-hour minimum staffing",
        "description": "For 24-hour shops, at least one employee is scheduled at all times, including overnight.",
        "category": "safety", "enabled": True, "locked": True,
    },
    {
        "title": "Role-based hour priority",
        "description": "Higher-priority roles are always considered first when hours are allocated.",
        "category": "safety", "enabled": True, "locked": True,
    },
]

SYSTEM_RULE_TITLES = [rule["title"] for rule in SYSTEM_RULES]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def seed_system_rules(shop_id: str) -> None:
    """Make sure the shop has exactly one copy of each locked rule.

    Runs on EVERY authenticated request, via ensure_shop. That matters: the
    browser fires several API calls in parallel on page load, so an earlier
    read-then-insert version raced itself. Two requests both found a new rule
    missing, both inserted it, and the shop ended up with the rule listed
    twice — which happened the first time anybody loaded the page after a
    rule was added.

    One upsert per rule instead. Concurrent callers converge on the same
    document rather than each creating their own, and the unique index in
    db.ensure_indexes makes a duplicate impossible even if this is wrong.

    Wording is refreshed rather than written once, because these rules
    describe guarantees the solver enforces in code; a shop seeded under an
    older wording would otherwise display a number the product no longer uses.
    """
    for rule in SYSTEM_RULES:
        await db.ai_rules.update_one(
            {"shop_id": shop_id, "title": rule["title"]},
            {
                "$set": {
                    "description": rule["description"],
                    "category": rule["category"],
                    "enabled": True,
                    "locked": True,
                },
                "$setOnInsert": {
                    "rule_id": f"rule_{uuid.uuid4().hex[:12]}",
                    "shop_id": shop_id,
                    "title": rule["title"],
                },
            },
            upsert=True,
        )


async def ensure_shop(user: Dict[str, Any]) -> Dict[str, Any]:
    """Return the caller's shop, creating it with defaults on first access."""
    existing = await db.shops.find_one({"owner_id": user["user_id"]}, {"_id": 0})
    if existing:
        await seed_system_rules(existing["shop_id"])
        return existing

    owner_first_name = (user.get("name") or "My").split()[0]
    shop = {
        "shop_id": f"shop_{uuid.uuid4().hex[:12]}",
        "owner_id": user["user_id"],
        "name": user.get("shop_name") or f"{owner_first_name}'s Shop",
        "hours": DEFAULT_HOURS,
        "min_shift_hours": 4,
        "max_shift_hours": 9,
        "roles": DEFAULT_ROLES,
        "departments": DEFAULT_DEPARTMENTS,
        "multi_department": False,
        "open_24h": False,
        # A requested day off is honoured absolutely by default. Turning this
        # off lets the solver override one rather than leave an hour uncovered.
        "strict_days_off": True,
        "shift_templates": [],
        "onboarded": False,
        "created_at": _now(),
    }
    await db.shops.insert_one(dict(shop))
    await seed_system_rules(shop["shop_id"])
    return shop


def apply_24h_defaults(update: Dict[str, Any], current_shop: Dict[str, Any]) -> Dict[str, Any]:
    """When a shop is switched to 24-hour operation, give it working defaults.

    Two independent things happen here, and they used to be wrongly coupled:

      hours      a 24-hour shop is open 00:00-23:59, always. This is not
                 optional and does not depend on anything else.
      templates  a starting set of morning/afternoon/night shapes, only for
                 a shop that has none.

    Both used to sit behind "has no templates". So a shop that already had
    templates could be switched to 24h and keep 09:00-21:00 opening hours —
    which is exactly the state the docstring warned about. Worse, the
    coverage floor then only checked 09:00-21:00, so the small hours were
    unstaffed AND unreported.
    """
    # The flag AFTER this update, not just what the update mentions.
    #
    # Updates are partial (exclude_unset), so a save that changes anything
    # else carries no `open_24h` at all. Reading only the payload meant a
    # 24-hour shop reverted to whatever `hours` the settings form happened to
    # be holding — usually 09:00-21:00 — every time something unrelated was
    # saved. It appeared to work when the switch itself was toggled and to
    # undo itself at random afterwards, which is the worst way for a setting
    # to fail: the manager cannot tell what they did to cause it.
    #
    # `False` explicitly turns it off; absent means unchanged.
    open_24h = update.get("open_24h", current_shop.get("open_24h"))
    if not open_24h:
        return update

    # Always. A 24-hour shop that is not open 24 hours is a contradiction.
    update["hours"] = [
        {"day": day, "open": "00:00", "close": "23:59", "closed": False}
        for day in DAYS
    ]

    if not (current_shop.get("shift_templates") or update.get("shift_templates")):
        update["shift_templates"] = [dict(t) for t in DEFAULT_24H_TEMPLATES]

    return update


async def log_activity(shop_id: str, action: str, detail: str) -> None:
    await db.activity_logs.insert_one({
        "log_id": f"log_{uuid.uuid4().hex[:10]}",
        "shop_id": shop_id,
        "action": action,
        "detail": detail,
        "created_at": _now(),
    })
