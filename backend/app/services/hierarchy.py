"""Configurable job hierarchy.

One ordered list of roles, defined per shop, used for every purpose that
needs to rank or sort people:

  * who is considered first when allocating hours (scheduler)
  * the order rows appear in the roster grid, print view and exports
  * grouping in reports

Configurable rather than hard-coded because job titles differ per business —
one shop's "Duty Manager" is another's "Shift Lead", and a shop with no
supervisors at all should not have a phantom rung in its ladder.

A role not present in the configured list sorts last rather than raising, so
adding an employee with a new job title never breaks roster generation. The
shop owner can then position it whenever they get round to it.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

# Used when a shop has not configured its own. Ordered most senior first.
DEFAULT_HIERARCHY: List[str] = [
    "Assistant Manager",
    "Customer Service Manager",
    "Ambient Manager",
    "Duty Manager",
    "Manager",
    "Supervisor",
    "Goods Inwards",
    "Cashier",
    "Floor Assistant",
    "Night Shift",
    "Stocker",
]

# Roles that count as supervisory cover, derived from position rather than
# named explicitly: anything in the top third of the ladder.
SUPERVISORY_FRACTION = 1 / 3

UNRANKED = 9_999


def get_hierarchy(shop: Optional[Dict[str, Any]] = None) -> List[str]:
    """The shop's role order, falling back to the default."""
    if shop:
        configured = shop.get("role_hierarchy")
        if configured:
            return [str(r) for r in configured if str(r).strip()]
    return list(DEFAULT_HIERARCHY)


def effective_hierarchy(
    shop: Optional[Dict[str, Any]] = None,
    roles_in_use: Optional[Iterable[str]] = None,
) -> List[str]:
    """The ladder as it actually applies, including titles nobody has placed.

    A role that exists on an employee but not in the configured list ranks
    last, which is safe but invisible — the owner has no way to notice they
    need to position it. Appending those roles here means the settings screen
    shows them at the bottom, where they can be dragged up.
    """
    ordered = get_hierarchy(shop)
    ranks = {role: index for index, role in enumerate(ordered)}
    for role in roles_in_use or []:
        title = str(role).strip()
        if title and rank_of(title, ranks) == UNRANKED and title not in ordered:
            ordered.append(title)
    return ordered


def match_role(raw: Optional[str], shop: Optional[Dict[str, Any]] = None) -> str:
    """Resolve a job title read from a file against the shop's own ladder.

    The shop's spelling wins where it matches — "duty mgr" on a sheet becomes
    the shop's "Duty Manager" — so imported staff sort correctly instead of
    landing at the bottom on a punctuation difference.

    A title the shop does not have is kept exactly as written. It then shows
    up at the end of `effective_hierarchy`, where the owner can position it.

    Deliberately does NOT collapse titles into broader ones. An earlier
    version of the import mapped "Duty Manager", "Assistant Manager" and
    "Customer Service Manager" all onto "Manager", and "Night Shift" and
    "Goods Inwards" onto "Stocker" — flattening five rungs of this very
    ladder into one and inventing roles the shop had never configured.
    Distinctions the manager drew in their own roster are theirs to keep.
    """
    text = (raw or "").strip()
    if not text:
        return ""

    ladder = get_hierarchy(shop)

    for role in ladder:
        if _normalise(role) == _normalise(text):
            return role

    # Aliases the shop has taught us. Needed because loose matching forgives
    # "Mgr" for "Manager" but cannot know that this shop's "Ass Manager" is
    # the sheet's "Assistant Manager", or that "Shop Floor" is their "Floor
    # Assistant". Guessing at that is what the old ROLE_MAP did wrong; being
    # told is different.
    for alias, role in (shop or {}).get("role_aliases", {}).items():
        if _normalise(alias) == _normalise(text):
            # Only honour an alias that points at a role the shop still has,
            # so renaming a rung cannot leave an alias aimed at nothing.
            for configured in ladder:
                if _normalise(configured) == _normalise(role):
                    return configured

    return text


def rank_map(shop: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """role -> rank, lower is more senior."""
    return {role: index for index, role in enumerate(get_hierarchy(shop))}


def rank_of(role: Optional[str], ranks: Dict[str, int]) -> int:
    """Rank a role, tolerating case and punctuation differences.

    Imported data carries titles like 'Duty Mgr.' where the configured list
    says 'Duty Manager'; matching loosely avoids every such employee silently
    sorting last.
    """
    if not role:
        return UNRANKED
    if role in ranks:
        return ranks[role]

    normalised = _normalise(role)
    for configured, index in ranks.items():
        if _normalise(configured) == normalised:
            return index
    return UNRANKED


def _normalise(role: str) -> str:
    text = role.strip().lower().rstrip(".")
    for long, short in (("manager", "mgr"), ("supervisor", "sup")):
        text = text.replace(long, short)
    return "".join(ch for ch in text if ch.isalnum())


def sort_employees(
    employees: Iterable[Dict[str, Any]],
    shop: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Order people by hierarchy, then by name.

    The name tie-break keeps the order stable: without it, two employees of
    the same rank could swap places between one page load and the next, which
    looks like the roster changed when it did not.
    """
    ranks = rank_map(shop)
    return sorted(
        employees,
        key=lambda e: (rank_of(e.get("role"), ranks), (e.get("name") or "").lower()),
    )


def display_order(
    employees: Iterable[Dict[str, Any]],
    shop: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Row order for anything a human reads — grid, exports, print, email.

    Deliberately separate from `sort_employees`, which decides who is
    considered first when handing out hours. That order follows the job
    ladder and is one of the rules that cannot be changed; this one is just
    how the manager likes the sheet laid out. Grouping the night staff
    together to read the rota more easily must not quietly promote them.

    Falls back to the ladder when the shop has never reordered anything, so
    the default stays sensible rather than arbitrary.

    Someone hired after the last reorder is not in the stored list. They sort
    after everyone who is, by seniority — appearing at the bottom is
    noticeable and easy to fix, whereas silently slotting them mid-list would
    look like the saved order had drifted on its own.
    """
    manual = (shop or {}).get("employee_order") or []
    if not manual:
        return sort_employees(employees, shop)

    position = {employee_id: index for index, employee_id in enumerate(manual)}
    ranks = rank_map(shop)
    return sorted(
        employees,
        key=lambda e: (
            position.get(e["employee_id"], len(position)),
            rank_of(e.get("role"), ranks),
            (e.get("name") or "").lower(),
        ),
    )


# Job titles that are supervisory whatever the ladder says. Position alone
# was not enough: the default ladder has eleven rungs, so the top third
# stopped at Duty Manager and a person whose title is literally "Supervisor"
# did not count as supervisory cover. Every roster then reported days with no
# senior on them while a supervisor was standing there.
SUPERVISORY_WORDS = (
    "manager", "mgr", "supervisor", "duty", "lead", "senior",
    "keyholder", "key holder", "charge",
)


def is_supervisory(role: Optional[str], shop: Optional[Dict[str, Any]] = None) -> bool:
    """Whether a role counts as management cover for a shift.

    Two ways to qualify. A title that says so — anything containing
    "manager", "supervisor", "duty", "lead" and so on — always counts. Beyond
    that, position in the ladder still applies, so a shop using its own
    vocabulary ("Shift Captain") keeps working without configuring anything.
    """
    if role:
        lowered = role.lower()
        if any(word in lowered for word in SUPERVISORY_WORDS):
            return True

    hierarchy = get_hierarchy(shop)
    if not hierarchy:
        return False
    cutoff = max(1, round(len(hierarchy) * SUPERVISORY_FRACTION))
    return rank_of(role, rank_map(shop)) < cutoff
