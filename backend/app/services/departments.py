"""Department boundaries for roster generation and learning.

A department is a roster namespace inside one shop.  Demand, ownership and
shift familiarity are learned inside that namespace; employment limits are
shop-wide because a person does not get a second weekly cap merely by working
in another part of the same business.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_DEPARTMENT = "Shop Floor"

# Settings that describe one scheduling operation rather than the employer.
# Pay, leave balances, recipients and statutory rest remain shop-wide.
SCHEDULING_FIELDS = {
    "hours", "min_shift_hours", "max_shift_hours", "roles",
    "role_hierarchy", "supervisory_roles", "strict_days_off", "open_24h",
    "shift_templates", "overstaff_tolerance", "demand_profile", "role_aliases",
}


def names(shop: Optional[Dict[str, Any]]) -> List[str]:
    configured = [
        str(name).strip() for name in (shop or {}).get("departments") or []
        if str(name).strip()
    ]
    return configured or [DEFAULT_DEPARTMENT]


def primary(shop: Optional[Dict[str, Any]]) -> str:
    return names(shop)[0]


def effective_shop(shop: Dict[str, Any], department: Optional[str]) -> Dict[str, Any]:
    """Overlay one roster group's scheduling settings on the shared shop."""
    selected = department if department in names(shop) else primary(shop)
    effective = deepcopy(shop)
    effective.update(deepcopy((shop.get("department_settings") or {}).get(selected) or {}))
    effective["current_department"] = selected
    effective["primary_department"] = primary(shop)
    return effective


def employee_for(employee: Dict[str, Any], department: str) -> Dict[str, Any]:
    """Employee with the job title they hold in this roster group."""
    result = dict(employee)
    result["role"] = (employee.get("department_roles") or {}).get(
        department, employee.get("role", ""),
    )
    return result


def roster_department(roster: Dict[str, Any], shop: Optional[Dict[str, Any]] = None) -> str:
    """Department for new and legacy roster documents."""
    return str(roster.get("department") or names(shop)[0])


def matches(roster: Dict[str, Any], department: str, shop: Optional[Dict[str, Any]] = None) -> bool:
    return roster_department(roster, shop) == department


def rules_for(rules: Iterable[Dict[str, Any]], department: Optional[str]) -> List[Dict[str, Any]]:
    """System/global rules apply everywhere; scoped rules apply only where named."""
    selected = []
    for rule in rules:
        scoped = rule.get("departments") or []
        if rule.get("locked") or not scoped or department in scoped:
            selected.append(rule)
    return selected
