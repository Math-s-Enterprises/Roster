"""What a new shop still has to do, derived from its data.

WHY DERIVED RATHER THAN STORED
------------------------------
The obvious implementation is a `setup_step_3_done: true` flag per step. It
starts lying immediately: delete your staff and step 2 still claims to be
finished; remove an imported week and the app still says the scheduler has
history to learn from.

Every step here is a question asked of the data at the moment it is rendered,
so the list is always true and repairs itself. It costs a handful of counts.

WHY THIS EXISTS AT ALL
----------------------
The onboarding wizard covers the shop — hours, roles, shift limits — and then
sets `onboarded: true`, at which point the dashboard used to announce
"Everything is set up. Generate this week's roster in one click." A brand new
shop reaching that line has no employees, no history and no fixed shifts, so
the one click produces an empty week with no explanation. Being told you are
finished when you have barely started is worse than being told nothing.

The `why` on each step is part of the feature, not decoration. A manager who
does not know that importing history is what makes rosters resemble their own
will skip it, and then conclude the product is bad at its job.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.services import availability as avail

# What the importer writes when the spreadsheet does not say. Anyone still
# carrying all three is a placeholder rather than a real pay record.
IMPORT_DEFAULT_RATE = 13.0
IMPORT_DEFAULT_AGE = 25
IMPORT_DEFAULT_MAX_HOURS = 40.0


def _name_list(people: List[Dict[str, Any]], limit: int = 4) -> str:
    """"Jane, Steve and 2 others" — a step you can act on without hunting."""
    names = [p.get("name") or "?" for p in people]
    if len(names) <= limit:
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " and " + names[-1]
    shown = ", ".join(names[:limit])
    return f"{shown} and {len(names) - limit} more"


def _on_import_defaults(employee: Dict[str, Any]) -> bool:
    """Whether this record still holds values nobody has looked at.

    A saved edit sets `details_confirmed`, and that settles it. Comparing
    values is only a fallback for records written before the flag existed:
    it cannot distinguish a placeholder from somebody who genuinely is 25, on
    the default rate, working 40 hours — and for them the step could never be
    completed, which is a checklist that lies to the person following it.
    """
    if employee.get("details_confirmed"):
        return False
    return (
        float(employee.get("hourly_rate") or 0) == IMPORT_DEFAULT_RATE
        and int(employee.get("age") or 0) == IMPORT_DEFAULT_AGE
        and float(employee.get("max_weekly_hours") or 0) == IMPORT_DEFAULT_MAX_HOURS
    )


def build_steps(
    shop: Dict[str, Any],
    employees: List[Dict[str, Any]],
    learning: Dict[str, Any],
    fixed_shifts: List[Dict[str, Any]],
    holidays: List[Dict[str, Any]],
    rosters: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """The checklist, in the order that makes each step useful to the next.

    Importing comes second, before adding staff by hand, because the import
    creates everyone named on the sheet — doing it first turns "add your
    team" from twenty-four forms into filling in whoever it missed.

    Setting employment types comes before generating, because it decides
    contracted hours, and a roster built on the wrong contract has to be
    thrown away rather than corrected.
    """
    # Leavers kept only to own imported history are not staff to be reviewed.
    team = [e for e in employees if not e.get("past_staff")]
    active = [e for e in team if avail.is_active(e)]

    placeholders = [e for e in active if _on_import_defaults(e)]
    untyped = [e for e in active if not e.get("employment_type")]
    # Imported history is excluded from both counts. It is not a roster this
    # manager produced, and counting it would tick a step they never did — or
    # report "4 drafts" to somebody who has generated nothing.
    own = [r for r in rosters if not r.get("historical")]
    approved = [r for r in own if r.get("approved")]
    drafts = [r for r in own if not r.get("approved") and not r.get("archived")]

    weeks_in = int(learning.get("weeks_in_window") or 0)
    weeks_needed = int(learning.get("weeks_needed") or 0)

    steps: List[Dict[str, Any]] = [
        {
            "id": "shop",
            "title": "Set up your shop",
            "why": "Opening hours, shift lengths and the order roles get hours in. "
                   "Everything else is built on these.",
            "done": bool(shop.get("onboarded")),
            "detail": "Done" if shop.get("onboarded") else "Not started",
            "action": {"label": "Open setup", "path": "/onboarding"},
        },
        {
            "id": "history",
            "title": "Import past rosters",
            "why": "This is what makes a generated week look like one you would have "
                   "written. Without it the scheduler falls back to generic blocks: "
                   "legal and covered, but not yours. It also creates your staff "
                   "from the names on the sheet, so most of the next step is done "
                   "for you.",
            "done": weeks_in >= weeks_needed and weeks_needed > 0,
            "detail": (
                f"{weeks_in} week{'' if weeks_in == 1 else 's'} in use"
                + (f" — {weeks_needed} needed" if weeks_in < weeks_needed else "")
            ),
            "action": {"label": "Import rosters", "path": "/import"},
        },
        {
            "id": "team",
            "title": "Add anyone the import missed",
            "why": "New starters who have never appeared on a roster, and anyone "
                   "whose name the sheet spelled differently. Nothing can be "
                   "scheduled until somebody exists.",
            "done": len(active) > 0,
            "detail": (
                f"{len(active)} " + ("person" if len(active) == 1 else "people")
                if active else "Nobody added yet"
            ),
            "action": {"label": "Add people", "path": "/employees"},
        },
        {
            "id": "details",
            "title": "Check pay and ages",
            "why": "A spreadsheet has no wages or dates of birth, so imported staff "
                   "start on placeholders. Age decides what the law allows; pay "
                   "decides whether the cost on each roster means anything.",
            "done": len(active) > 0 and not placeholders,
            # An empty team must not read "All reviewed" — technically true of
            # nobody, and it would tell a new shop it had finished a step it
            # has not begun.
            # NAMED, not counted. "4 still on placeholder values" against a
            # team of 25 means opening records one at a time to find them,
            # and a step that cannot be acted on is a step that does not get
            # done. Four names is the whole job.
            "detail": (
                "Nobody to review yet" if not active
                else _name_list(placeholders) + " still on placeholder pay and age"
                if placeholders else "All reviewed"
            ),
            "who": [
                {"employee_id": e["employee_id"], "name": e.get("name", "?")}
                for e in placeholders
            ],
            "action": {"label": "Review team", "path": "/employees"},
        },
        {
            "id": "employment",
            "title": "Set employment types",
            "why": "Full-time contract, student or hourly — under Advanced options on "
                   "each person. A contract means 42.5 hours are owed whatever the "
                   "week looks like, so getting this wrong makes every roster wrong.",
            "done": len(active) > 0 and not untyped,
            "who": [
                {"employee_id": e["employee_id"], "name": e.get("name", "?")}
                for e in untyped
            ],
            "detail": (
                "Nobody to set yet" if not active
                else _name_list(untyped) + " without a type" if untyped else "All set"
            ),
            "action": {"label": "Set types", "path": "/employees"},
        },
        {
            "id": "constraints",
            "title": "Fixed shifts and booked leave",
            "why": "Anyone who always works the same slot, and any holiday already "
                   "agreed. The scheduler treats both as immovable, so adding them "
                   "now saves correcting rosters later.",
            "done": bool(fixed_shifts) or bool(holidays),
            "detail": (
                f"{len(fixed_shifts)} fixed shift(s), {len(holidays)} holiday(s)"
                if (fixed_shifts or holidays) else "None yet"
            ),
            "action": {"label": "Add fixed shifts", "path": "/fixed-shifts"},
            "optional": True,
        },
        {
            "id": "roster",
            "title": "Generate and approve a week",
            "why": "Approving is what makes a roster real: it becomes the schedule "
                   "people work, and it joins what the scheduler learns from.",
            "done": bool(approved),
            "detail": (
                f"{len(approved)} week(s) approved" if approved
                else f"{len(drafts)} draft(s), none approved" if drafts
                else "No roster yet"
            ),
            "action": {"label": "Open roster", "path": "/roster"},
        },
    ]

    required = [s for s in steps if not s.get("optional")]
    done = [s for s in required if s["done"]]
    nxt = next((s for s in steps if not s["done"]), None)

    return {
        "steps": steps,
        "done": len(done),
        "total": len(required),
        "complete": len(done) == len(required),
        "next_step_id": nxt["id"] if nxt else None,
    }
