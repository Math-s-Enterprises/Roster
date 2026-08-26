"""MongoDB connection and index management.

Everything that touches the database goes through the collection handles
exported here, so there is exactly one client for the whole process.

Why indexes matter here: several correctness guarantees in this app cannot
be enforced by application code alone. The classic example is "one account
per email" — an application-level `find_one` check followed by an `insert`
is not atomic, so two simultaneous signups can both pass the check. Only a
unique index makes that impossible. See ensure_indexes() below.
"""
import logging

from motor.motor_asyncio import AsyncIOMotorClient

from app import config

log = logging.getLogger("roster.db")

client = AsyncIOMotorClient(config.MONGO_URL)
db = client[config.DB_NAME]

# Collection handles — import these rather than reaching through `db`, so
# a typo'd collection name fails at import instead of silently creating an
# empty collection at runtime (MongoDB creates collections on first write).
users = db.users
user_sessions = db.user_sessions
password_resets = db.password_resets
shops = db.shops
employees = db.employees
holidays = db.holidays
fixed_shifts = db.fixed_shifts
ai_rules = db.ai_rules
rosters = db.rosters
activity_logs = db.activity_logs
payment_transactions = db.payment_transactions
roster_imports = db.roster_imports
# Suggestions the manager has said no to, or already applied. A
# decision is not derivable from the data that prompted it, so unlike
# almost everything else in this app it is stored.
correction_dismissals = db.correction_dismissals


async def _dedupe_system_rules() -> None:
    """Remove duplicate locked rules left by the old seeding race.

    Runs before the unique index is created, because MongoDB refuses to build
    a unique index over data that already violates it — and a shop that hit
    the race would otherwise be unable to start the app at all.

    Keeps the oldest of each set, so whichever copy the manager may already
    have looked at is the one that survives.
    """
    try:
        groups = await ai_rules.aggregate([
            {"$match": {"locked": True}},
            {"$group": {
                "_id": {"shop_id": "$shop_id", "title": "$title"},
                "ids": {"$push": "$_id"},
                "count": {"$sum": 1},
            }},
            {"$match": {"count": {"$gt": 1}}},
        ]).to_list(500)
    except Exception as exc:                              # pragma: no cover
        log.warning("Could not check for duplicate system rules: %s", exc)
        return

    removed = 0
    for group in groups:
        for _id in group["ids"][1:]:
            await ai_rules.delete_one({"_id": _id})
            removed += 1
    if removed:
        log.info("Removed %d duplicate system rule(s)", removed)


async def ensure_indexes() -> None:
    """Create indexes if absent. Safe and cheap to run on every startup."""
    # Uniqueness that application code cannot guarantee on its own.
    await users.create_index("email", unique=True, name="uniq_email")
    await users.create_index("user_id", unique=True, name="uniq_user_id")

    # Every tenant-scoped query filters on shop_id, so index it everywhere.
    for coll, name in (
        (employees, "employees"),
        (holidays, "holidays"),
        (fixed_shifts, "fixed_shifts"),
        (ai_rules, "ai_rules"),
        (activity_logs, "activity_logs"),
        (roster_imports, "roster_imports"),
        (correction_dismissals, "correction_dismissals"),
    ):
        await coll.create_index("shop_id", name=f"idx_{name}_shop")

    await _dedupe_system_rules()
    # One LOCKED rule per title per shop. seed_system_rules runs on every
    # authenticated request, and the browser makes several in parallel on page
    # load — without this, two could both find a newly added rule missing and
    # both insert it. The upsert there converges on its own; this makes the
    # duplicate impossible rather than merely unlikely.
    #
    # Partial, so it applies only to system rules. Two custom rules sharing a
    # title is the owner's business, and a unique index over all of them would
    # refuse writes they are entitled to make.
    try:
        await ai_rules.create_index(
            [("shop_id", 1), ("title", 1)],
            unique=True,
            partialFilterExpression={"locked": True},
            name="uniq_system_rule_per_shop",
        )
    except Exception as exc:                              # pragma: no cover
        # Never let an index stop the app booting. The upsert above already
        # prevents new duplicates; this is the belt to its braces.
        log.warning("Could not create uniq_system_rule_per_shop: %s", exc)

    await shops.create_index("owner_id", name="idx_shops_owner")
    await shops.create_index("shop_id", unique=True, name="uniq_shop_id")

    # Roster lookups are always "this shop, this week, newest first".
    await rosters.create_index(
        [("shop_id", 1), ("week_start", -1), ("created_at", -1)],
        name="idx_rosters_shop_week",
    )

    # Session tokens are looked up on every cookie-authenticated request, and
    # expire themselves via a TTL index so dead sessions don't accumulate.
    await user_sessions.create_index("session_token", unique=True, name="uniq_session_token")
    await user_sessions.create_index("expires_at", expireAfterSeconds=0, name="ttl_sessions")

    # Reset tokens are looked up by their hash and self-expire the same way
    # sessions do, so a stale or already-used request row never lingers.
    await password_resets.create_index("token_hash", unique=True, name="uniq_reset_token_hash")
    await password_resets.create_index("expires_at", expireAfterSeconds=0, name="ttl_password_resets")

    await payment_transactions.create_index("session_id", unique=True, name="uniq_stripe_session")

    log.info("MongoDB indexes ensured")


async def close() -> None:
    client.close()
