"""Roster generation, editing, approval, dispatch and import."""
import logging
import random
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from collections import Counter

from app import config
from app.models import (
    ExtraShiftReq,
    ForceApproval,
    RosterGenReq,
    RosterUpdate,
    SickReport,
)
from app.services import compliance, corrections, llm, mailer, sick_cover
from app.services import demand as demand_service
from app.services.demand import build_profile
from app.services.hierarchy import sort_employees
from app.services.roster_validation import validate_shifts
from app.services.learning import compute_weights
from app.services.scheduler import (
    ABSOLUTE_MAX_SHIFT_HOURS,
    DAYS,
    MAX_WORKING_DAYS,
    break_minutes,
    paid_hours,
    shift_duration_minutes,
    shift_paid_hours,
    solve_roster,
    violates_minor_curfew,
)
from app.services.shop_service import log_activity
from app.security import verify_password
from app.tenancy import ShopScope, CurrentScope

log = logging.getLogger("roster.rosters")
router = APIRouter(tags=["rosters"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _approved_rosters(scope: ShopScope) -> List[Dict[str, Any]]:
    """Every approved roster — the corpus the preference weights build on.

    Streamed rather than page-limited: a truncated read would silently skew
    the weights instead of failing visibly.
    """
    return [roster async for roster in scope.rosters.stream({"approved": True})]


async def _approved_for_week(
    scope: ShopScope, week_start: str, department: Any, *, exclude: str = ""
) -> Dict[str, Any] | None:
    """The approved roster for a week, if there is one.

    One week has at most one approved roster. Everything downstream assumes
    it: the preference weights, the demand curve and the familiarity history
    all read "every approved roster" and treat each as one week that was
    actually worked.
    """
    query: Dict[str, Any] = {
        "week_start": week_start,
        "department": department,
        "approved": True,
    }
    if exclude:
        query["roster_id"] = {"$ne": exclude}
    return await scope.rosters.find_one(query)


def _date_for_day(week_start: str, day: str) -> str:
    """The calendar date of a weekday within a roster week."""
    try:
        monday = date.fromisoformat(week_start)
    except (TypeError, ValueError):
        return ""
    if day not in DAYS:
        return ""
    return (monday + timedelta(days=DAYS.index(day))).isoformat()


def leave_dates(holidays: List[Dict[str, Any]]) -> Dict[str, set]:
    """employee_id -> dates they cannot be rostered.

    Shared with the validator's view of leave so cover suggestions cannot
    offer somebody the roster would have refused.
    """
    blocked: Dict[str, set] = {}
    for holiday in holidays:
        if holiday.get("scope") not in ("employee", "unavailable", "sick"):
            continue
        employee_id = holiday.get("employee_id")
        if not employee_id:
            continue
        try:
            start = date.fromisoformat(holiday["date"])
            end = date.fromisoformat(holiday.get("end_date") or holiday["date"])
        except (KeyError, TypeError, ValueError):
            continue
        cursor = start
        while cursor <= end:
            blocked.setdefault(employee_id, set()).add(cursor.isoformat())
            cursor += timedelta(days=1)
    return blocked


def _week_has_ended(week_start: str) -> bool:
    """True once the whole week is behind us.

    A week in progress stays editable — somebody calls in sick on Wednesday
    and the rest of the week has to move. Only a finished week is closed,
    because by then it is a record of what happened rather than a plan.
    """
    try:
        last_day = date.fromisoformat(week_start) + timedelta(days=6)
    except ValueError:
        return False
    return last_day < datetime.now(timezone.utc).date()


def _next_version(previous: Dict[str, Any] | None) -> str:
    if not previous:
        return "v1.0"
    try:
        major, minor = str(previous.get("version", "v1.0")).lstrip("v").split(".")
        return f"v{major}.{int(minor) + 1}"
    except (ValueError, AttributeError):
        return "v1.1"


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
@router.post("/roster/generate")
async def generate_roster(payload: RosterGenReq, scope: ShopScope = CurrentScope):
    shop = scope.shop

    if config.BILLING_ENFORCED and not scope.user.get("pro"):
        used = await scope.rosters.count()
        if used >= config.FREE_PLAN_ROSTER_LIMIT:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                f"Free plan limit reached ({config.FREE_PLAN_ROSTER_LIMIT} rosters). "
                "Upgrade to Pro to generate more.",
            )

    # An approved week is closed to both Generate and Rebalance. Both insert a
    # new draft, and the moment that draft is approved the week has two
    # approved rosters — which the solver reads as two weeks that were both
    # worked, doubling that week's pull on every preference weight. Unapprove
    # is the deliberate way back in.
    settled = await _approved_for_week(scope, payload.week_start, payload.department)
    if settled:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": (
                f"Week of {payload.week_start} is approved ({settled.get('version')}). "
                "Unapprove it first if you need to change it."
            ),
            "reasons": [
                "Approving a second roster for the same week would teach the "
                "scheduler that week twice and skew future rosters.",
            ],
            "approved_roster_id": settled["roster_id"],
        })

    employees = await scope.employees.find(limit=1000)
    if payload.department:
        employees = [
            e for e in employees
            if payload.department in (e.get("departments") or ["Shop Floor"])
        ]
    if not employees:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"No employees in {payload.department}." if payload.department
            else "Add employees before generating a roster.",
        )

    open_days = [
        h for h in shop.get("hours", [])
        if not h.get("closed") and h.get("open") != h.get("close")
    ]
    if not open_days:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Opening hours are not configured. Complete onboarding first.",
        )

    # Rebalancing keeps whatever the manager pinned in the current draft and
    # re-solves everyone else around it. Generating fresh keeps nothing.
    locked_shifts = []
    if payload.keep_pinned:
        current = await scope.rosters.find_one({
            "week_start": payload.week_start,
            "department": payload.department,
            "archived": {"$ne": True},
        })
        # Extra shifts are held exactly like pins. They are a decision the
        # manager made for a reason the app cannot see — a delivery, a
        # renovation — and a rebalance that quietly removed them would be
        # removing the very thing they came here to add.
        locked_shifts = [
            s for s in (current or {}).get("shifts", [])
            if (s.get("pinned") or s.get("extra"))
            and s.get("start") and s.get("end")
        ]

        # Rebalancing ONE day freezes the other six by handing every shift on
        # them in as locked. Locking rather than skipping is deliberate:
        # those hours still count against weekly caps, the five-day limit and
        # the rest gap, so two extra hours on Wednesday cannot quietly push
        # somebody over their week.
        if payload.only_day:
            already = {id(s) for s in locked_shifts}
            locked_shifts += [
                s for s in (current or {}).get("shifts", [])
                if s.get("day") != payload.only_day
                and s.get("start") and s.get("end")
                and id(s) not in already
            ]

    employee_ids = {e["employee_id"] for e in employees}
    holidays = await scope.holidays.find(limit=1000)
    fixed_shifts = [
        f for f in await scope.fixed_shifts.find(limit=1000)
        if f["employee_id"] in employee_ids
    ]
    rules = await scope.ai_rules.find({"enabled": True})

    approved = await _approved_rosters(scope)
    weights = compute_weights(approved)

    # Staffing levels are learned from this shop's own recent history: how many
    # people per hour, which roles, and which shift shapes it actually uses.
    # Shops without enough history fall back to block-based coverage.
    demand = build_profile(
        shop, approved, {e["employee_id"]: e.get("role", "") for e in employees},
        # Anchors recency weighting and the same-week-last-year lookup to the
        # week being BUILT, not to whenever the newest roster happens to be.
        # Building four weeks ahead should weigh history from the point of
        # view of that week.
        for_week=payload.week_start,
    )

    # Employees are handed to the solver in hierarchy order, so the ordering
    # is consistent from generation through to display and export.
    employees = sort_employees(employees, shop)

    # A fresh Generate offers a different arrangement each time; a Rebalance
    # does not. Rebalancing exists to rearrange the week around a decision the
    # manager just made, so anything it changes beyond that is noise they have
    # to read past.
    #
    # Only genuinely arbitrary choices vary — a slot somebody owns is theirs
    # whatever the seed. See _pick_for_slot.
    #
    # The seed is stored on the roster: a version that cannot be reproduced
    # cannot be explained when the manager asks why somebody got a shift.
    seed = None if payload.keep_pinned else random.randrange(1_000_000_000)

    result = solve_roster(
        shop, employees, holidays, fixed_shifts, rules, payload.week_start,
        weights, demand, history_rosters=approved,
        locked_shifts=locked_shifts, seed=seed, only_day=payload.only_day,
    )

    # The narrative summary is decoration on a complete result. If the model
    # is unavailable or slow, the roster is still returned — the feature must
    # never be a single point of failure for the core product.
    ai_summary = None
    if llm.enabled:
        try:
            ai_summary = await llm.summarise_roster(
                payload.week_start, len(result["shifts"]),
                result["compliance_score"], result["labor_cost"],
                result["critical_issues"] + result["issues"],
            )
        except Exception as exc:
            log.warning("AI summary skipped: %s", exc)

    previous = await scope.rosters.find_one({"week_start": payload.week_start})
    roster = await scope.rosters.insert({
        "roster_id": f"rst_{uuid.uuid4().hex[:12]}",
        "week_start": payload.week_start,
        "version": _next_version(previous),
        "seed": seed,
        **result,
        # A frozen copy of what the solver proposed, never touched by edits.
        # Editing overwrites `shifts` in place, so without this the manager's
        # corrections are destroyed the moment they touch the roster — and
        # those corrections are the most useful signal the product has.
        "generated_shifts": [dict(s) for s in result["shifts"]],
        "ai_summary": ai_summary,
        "approved": False,
        "department": payload.department,
        "created_at": _now(),
    })

    await log_activity(
        scope.shop_id, "roster_generated",
        f"Generated {roster['version']} for week of {payload.week_start}",
    )
    return roster


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
@router.get("/rosters")
async def list_rosters(
    scope: ShopScope = CurrentScope,
    limit: int = Query(200, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    return await scope.rosters.find(limit=limit, skip=skip, sort=[("created_at", -1)])


@router.get("/rosters/past")
async def list_past_rosters(
    scope: ShopScope = CurrentScope,
    limit: int = Query(200, ge=1, le=500),
):
    today = datetime.now(timezone.utc).date().isoformat()
    return await scope.rosters.find(
        {"week_start": {"$lt": today}}, limit=limit, sort=[("week_start", -1)]
    )


# NOTE: declared after /rosters/past so the literal path wins. FastAPI
# matches in declaration order, and "/rosters/{roster_id}" would otherwise
# swallow "/rosters/past" and try to look up a roster called "past".
@router.get("/rosters/{roster_id}")
async def get_roster(roster_id: str, scope: ShopScope = CurrentScope):
    roster = await scope.rosters.find_one({"roster_id": roster_id})
    if not roster:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roster not found")
    return roster


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------
@router.put("/rosters/{roster_id}")
async def update_roster(
    roster_id: str, payload: RosterUpdate, scope: ShopScope = CurrentScope
):
    existing = await scope.rosters.find_one({"roster_id": roster_id})
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roster not found")
    if existing.get("approved"):
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": (
                "This roster is approved. Unapprove it first if you need to "
                "change it."
            ),
            "reasons": [
                "An approved week is the schedule people were told to work, "
                "and it is part of what the scheduler learns from.",
            ],
            "can_unapprove": not _week_has_ended(existing["week_start"]),
        })

    # The grid sends the whole week back on every edit, but it only knows the
    # seven fields it renders. Derived values — paid_hours, the break, a leave
    # label — are matched back from what is already stored, so editing one
    # shift cannot silently strip the hours off somebody's booked holiday and
    # corrupt their balance.
    stored = {
        (s.get("employee_id"), s.get("day")): s
        for s in existing.get("shifts", [])
    }

    shifts = []
    for shift in payload.shifts:
        data = shift.model_dump()
        previous = stored.get((data["employee_id"], data["day"]), {})
        # A shift the manager changed, or added, is pinned from now on. That
        # is what makes Rebalance safe to press: your decisions are held and
        # everybody else rearranges around them. Sending pinned=false
        # explicitly releases one.
        changed = (
            not previous
            or previous.get("start") != data["start"]
            or previous.get("end") != data["end"]
        )
        if data.get("pinned") is None:
            data["pinned"] = bool(previous.get("pinned")) or changed

        record = {
            **previous,
            **data,
            "shift_id": previous.get("shift_id") or f"sh_{uuid.uuid4().hex[:8]}",
            "fixed": False,
        }
        if not shift.is_leave:
            span = shift_duration_minutes(data["start"], data["end"]) / 60
            record.update({
                "span_hours": round(span, 2),
                "break_minutes": break_minutes(span),
                "paid_hours": round(paid_hours(data["start"], data["end"]), 2),
            })
            # A work shift cannot inherit a leave label from whatever used to
            # occupy this slot.
            record.pop("label", None)
        shifts.append(record)

    # A hand-edited roster is held to the same rules as a generated one, but
    # only for what the edit actually changes.
    #
    # Validating the finished week and refusing on anything found meant a
    # manager swapping one Wednesday shift was blocked by somebody else being
    # under their contract on a different day — a problem that was already
    # there, that the swap did not cause, and that the swap cannot fix. Small
    # tweaks are how a roster gets finished, so the question is "does this
    # make anything worse", not "is everything already perfect".
    employees = await scope.employees.find(limit=1000)
    holidays = await scope.holidays.find(limit=1000)
    approved = await _approved_rosters(scope)

    def check(candidate):
        return validate_shifts(
            candidate,
            shop=scope.shop,
            employees=employees,
            holidays=holidays,
            week_start=existing["week_start"],
            history_rosters=approved,
        )

    before = check(existing.get("shifts", []))
    verdict = check(shifts)

    # Counted rather than set-differenced, so going from one breach to two of
    # the same kind is still caught.
    outstanding = Counter(before.blocking)
    introduced = []
    for problem in verdict.blocking:
        if outstanding[problem]:
            outstanding[problem] -= 1
            continue
        introduced.append(problem)

    # One structural invariant still refuses, and only this one: the same
    # person twice on the same day. It is not a rule about working conditions
    # that a manager could reasonably override — it is a malformed roster.
    # corrections.diff_roster identifies a shift by (employee, day) and says
    # so in its own docstring; two rows with that key make the diff ambiguous
    # and would quietly corrupt the corrections history, which is the most
    # valuable data this product has.
    duplicates = [p for p in verdict.blocking if "rostered twice on" in p]
    if duplicates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {
            "message": "Somebody is rostered twice on the same day.",
            "reasons": duplicates,
        })

    # Every OTHER breach is SAVED, and reported.
    #
    # It used to be refused. That reads as the app knowing better than the
    # manager, and it does not: somebody swapping two shifts at 6am knows
    # things the app cannot see — a swap agreed between two people, an offer
    # to cover, somebody going home early anyway. Refusing made a roster
    # impossible to finish and taught people to work around the edit screen,
    # which is where the corrections signal comes from.
    #
    # Nothing is lost by allowing it. The breach is attached to the person in
    # the grid, and approval — the moment a draft becomes the schedule people
    # are told to work — refuses until it is either fixed or deliberately
    # overridden by somebody who re-enters their password. The decision stays
    # with the manager; the record stays with the roster.
    pre_existing = [p for p in verdict.blocking if p not in introduced]

    rates = {e["employee_id"]: e.get("hourly_rate", 0) for e in employees}
    # Paid hours, matching how the solver costs a roster — breaks are unpaid,
    # and a paid-holiday day still costs a day's wages.
    labor_cost = sum(
        shift_paid_hours(s) * rates.get(s["employee_id"], 0)
        for s in shifts if not (s.get("unpaid_holiday") or s.get("sick"))
    )
    total_hours = sum(
        shift_paid_hours(s)
        for s in shifts
        if not (s.get("unpaid_holiday") or s.get("sick") or s.get("paid_holiday"))
    )

    await scope.rosters.update_one({"roster_id": roster_id}, {
        "shifts": shifts,
        "labor_cost": round(labor_cost, 2),
        "total_hours": round(total_hours, 1),
        "manually_edited": True,
        # Warnings from the edit replace the generator's, which described a
        # roster that no longer exists. Kept so they survive a page reload
        # rather than living only in a toast that has already gone.
        # Everything worth telling them, in one list. `introduced` is kept
        # first and separate in the response below, because "this change did
        # that" is a different sentence from "this was already true".
        "edit_warnings": verdict.warnings + pre_existing,
        "updated_at": _now(),
    })
    saved = await scope.rosters.find_one({"roster_id": roster_id})
    # What THIS edit caused, so the UI can name it rather than showing the
    # week's whole backlog of problems after every keystroke.
    return {**saved, "introduced": introduced}


@router.get("/rosters/{roster_id}/suggestions")
async def suggest_for_gap(
    roster_id: str,
    day: str = Query(..., description="mon..sun"),
    start: str = Query(..., description="HH:MM"),
    end: str = Query(..., description="HH:MM"),
    scope: ShopScope = CurrentScope,
):
    """Who could take this slot, best first, and what is wrong with each.

    The solver refuses to fill an hour rather than give it to somebody
    unsuitable. That is the right default, but it leaves the manager with a
    blank and no help. This ranks everybody for the slot and says plainly
    why each is imperfect — the manager still decides, but does not have to
    hold twenty-four people's constraints in their head to do it.
    """
    roster = await scope.rosters.find_one({"roster_id": roster_id})
    if not roster:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roster not found")

    employees = await scope.employees.find(limit=1000)
    approved = await _approved_rosters(scope)
    week_start = roster["week_start"]

    taken = {
        s["employee_id"] for s in roster.get("shifts", [])
        if s.get("day") == day
    }

    candidates = []
    for employee in sort_employees(employees, scope.shop):
        # Each candidate is scored against the same rules the solver uses,
        # then reported with whatever it would have objected to.
        proposed = [
            s for s in roster.get("shifts", [])
            if not (s.get("employee_id") == employee["employee_id"] and s.get("day") == day)
        ] + [{
            "employee_id": employee["employee_id"], "day": day,
            "start": start, "end": end,
        }]
        verdict = validate_shifts(
            proposed,
            shop=scope.shop,
            employees=employees,
            holidays=await scope.holidays.find(limit=1000),
            week_start=week_start,
            history_rosters=approved,
        )
        mine = [
            m for m in verdict.blocking + verdict.warnings
            if employee.get("name", "") in m or day in m
        ]
        candidates.append({
            "employee_id": employee["employee_id"],
            "name": employee.get("name"),
            "role": employee.get("role"),
            "already_working": employee["employee_id"] in taken,
            "blocked": bool(verdict.blocking),
            "reasons": mine[:3],
        })

    # Anybody clean first, then those with only soft objections, then the
    # rest. Seniority already ordered them within each group.
    candidates.sort(key=lambda c: (
        c["already_working"], c["blocked"], len(c["reasons"])
    ))
    return {"day": day, "start": start, "end": end, "candidates": candidates[:12]}


@router.get("/rosters/{roster_id}/audit")
async def audit_roster(roster_id: str, scope: ShopScope = CurrentScope):
    """Every rule this week breaks, grouped by the person it affects.

    Read by the grid to highlight names, and by the approve dialog to say what
    is being overridden. Recomputed on every request rather than stored: the
    manager is editing while they read it, and a cached answer would be wrong
    the moment they moved a shift.
    """
    roster = await scope.rosters.find_one({"roster_id": roster_id})
    if not roster:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roster not found")

    employees = await scope.employees.find(limit=1000)
    breaches = compliance.audit(
        roster.get("shifts") or [],
        shop=scope.shop,
        employees=employees,
        week_start=roster["week_start"],
        holidays=await scope.holidays.find(limit=1000),
    )

    # How this week compares to the shape the shop normally runs. Separate
    # from breaches on purpose: a rule being broken is a fact about the law
    # or a contract, whereas running two fewer people on a Tuesday evening is
    # a decision. Mixing them would make one look like the other.
    approved = await _approved_rosters(scope)
    profile = build_profile(
        scope.shop, approved,
        {e["employee_id"]: e.get("role", "") for e in employees},
        for_week=roster["week_start"],
    )
    return {
        "roster_id": roster_id,
        "people": compliance.group_by_employee(breaches),
        "total": len(breaches),
        "blocking": compliance.blocking(breaches),
        "can_force": bool(breaches) and not compliance.blocking(breaches),
        "staffing": demand_service.compare_to_usual(
            roster.get("shifts") or [], profile,
        ),
        "learned_from_weeks": profile.weeks_observed,
        # Zero until the shop has a year of history. The UI says so rather
        # than implying a yearly pattern nothing has ever seen.
        "seasonal_weeks": getattr(profile, "seasonal_weeks", 0),
    }


@router.post("/rosters/{roster_id}/approve")
async def approve_roster(
    roster_id: str,
    acknowledge_gaps: bool = Query(
        False,
        description="Approve despite hours where nobody is in the shop. "
                    "Recorded against the roster.",
    ),
    payload: Optional[ForceApproval] = None,
    scope: ShopScope = CurrentScope,
):
    """Approve a roster and retire the other drafts for that week.

    Refuses while the week still has hours nobody is covering. Approving is
    the moment a draft becomes the schedule people are told to work, and it
    was going through silently on rosters that left the shop unattended —
    the one outcome this app exists to prevent. It can still be forced, but
    it has to be a decision rather than a click.

    Superseded drafts are archived rather than deleted, so the decision is
    auditable and the draft-versus-approved difference stays available as
    training signal.
    """
    roster = await scope.rosters.find_one({"roster_id": roster_id})
    if not roster:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roster not found")

    if roster.get("approved"):
        return {"ok": True, "already_approved": True, "archived_drafts": 0,
                "approved_with_gaps": roster.get("approved_with_gaps", 0)}

    # Belt and braces: generation already refuses on an approved week, so this
    # should be unreachable through the UI. It stays because the invariant —
    # one approved roster per week — is what the whole learning corpus rests
    # on, and a second way in would corrupt it silently rather than loudly.
    rival = await _approved_for_week(
        scope, roster["week_start"], roster.get("department"), exclude=roster_id
    )
    if rival:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": (
                f"Week of {roster['week_start']} already has an approved roster "
                f"({rival.get('version')}). Unapprove that one first."
            ),
            "reasons": [
                "A week can only have one approved roster. Two would count as "
                "two worked weeks in everything the scheduler learns from.",
            ],
            "approved_roster_id": rival["roster_id"],
        })

    # ---- rules the finished week breaks -----------------------------------
    #
    # Editing no longer refuses: the manager can build whatever week the shop
    # actually needs, because they know things the app does not. This is where
    # it is accounted for. A week with breaches can still become real, but only
    # deliberately, by somebody who proves who they are — and the log records
    # what they overrode.
    breaches = compliance.audit(
        roster.get("shifts") or [],
        shop=scope.shop,
        employees=await scope.employees.find(limit=1000),
        week_start=roster["week_start"],
        holidays=await scope.holidays.find(limit=1000),
    )
    hard = compliance.blocking(breaches)
    if hard:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": "This roster cannot be approved, with or without a "
                       "password.",
            "reasons": [b["message"] for b in hard],
        })

    forced = bool(payload and payload.force)
    if breaches and not forced:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": f"{len(breaches)} rule(s) are broken in this week.",
            "reasons": [b["message"] for b in breaches[:8]],
            "needs_force": True,
        })

    if forced:
        if not verify_password(payload.password or "", scope.user.get("password_hash")):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "That password is not right. Force approval needs the password "
                "of the account authorising it.",
            )

    critical = roster.get("critical_issues") or []
    if critical and not acknowledge_gaps:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This roster leaves the shop unattended for {len(critical)} hour(s). "
            f"Fill the gaps, or approve again confirming you accept them.",
        )

    superseded = await scope.rosters.find({
        "week_start": roster["week_start"],
        "department": roster.get("department"),
        "roster_id": {"$ne": roster_id},
        "approved": {"$ne": True},
    }, limit=100)

    for draft in superseded:
        await scope.rosters.update_one({"roster_id": draft["roster_id"]}, {
            "superseded_by": roster_id,
            "archived": True,
            "archived_at": _now(),
        })

    # What the manager changed about the solver's proposal. Computed at the
    # moment of approval, because that is when their decisions are final —
    # and stored rather than derived later, so it survives the roster being
    # edited again through the sick-cover route.
    changes = corrections.diff_roster(
        roster.get("generated_shifts") or [], roster.get("shifts") or []
    )

    await scope.rosters.update_one({"roster_id": roster_id}, {
        "approved": True,
        "approved_at": _now(),
        # Recorded on the roster, so a week that went out with known gaps
        # says so afterwards rather than looking like a clean approval.
        "approved_with_gaps": len(critical) if critical else 0,
        "corrections": changes,
        # The number the product exists to reduce. Zero means the manager
        # approved what the solver proposed, unchanged.
        "edit_count": corrections.edit_count(changes),
        # Rosters generated before the snapshot existed cannot be compared,
        # so they are marked rather than counted as a perfect zero.
        "corrections_measurable": bool(roster.get("generated_shifts")),
        # A forced week says so for ever. Whoever reads this roster later —
        # the manager, an inspector, the person who worked six days — sees
        # that somebody decided, who they were, and exactly what was broken.
        "force_approved": forced,
        "force_approved_by": scope.user.get("email") if forced else None,
        "force_approved_reason": (payload.reason if forced and payload else None),
        "overridden_rules": [
            {"employee_id": b["employee_id"], "name": b["name"],
             "rule": b["rule"], "message": b["message"]}
            for b in breaches
        ] if forced else [],
    })
    if forced:
        await log_activity(
            scope.shop_id, "roster_force_approved",
            f"{scope.user.get('email')} force-approved week of "
            f"{roster['week_start']} with {len(breaches)} rule(s) broken"
            + (f" — {payload.reason}" if payload and payload.reason else ""),
        )
    await log_activity(
        scope.shop_id, "roster_approved",
        f"Approved {roster['version']} for week of {roster['week_start']} "
        f"({len(superseded)} draft(s) archived)"
        + (f" — ACCEPTING {len(critical)} uncovered hour(s)" if critical else ""),
    )
    return {
        "ok": True,
        "archived_drafts": len(superseded),
        "approved_with_gaps": len(critical) if critical else 0,
    }


@router.get("/rosters/{roster_id}/cover")
async def cover_options(
    roster_id: str,
    employee_id: str = Query(..., description="Who is off"),
    day: str = Query(..., description="mon..sun"),
    scope: ShopScope = CurrentScope,
):
    """Who could take a shift somebody has called in sick for, best first.

    Never returns an empty list while anybody could physically do it. The
    solver's refusal to break a rule is right when building a week from
    scratch; at 6am with the shop opening in an hour the manager's real
    question is which rule to bend and who to ask.
    """
    roster = await scope.rosters.find_one({"roster_id": roster_id})
    if not roster:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roster not found")

    shift = next(
        (s for s in roster.get("shifts", [])
         if s.get("employee_id") == employee_id and s.get("day") == day),
        None,
    )
    if not shift or not (shift.get("start") and shift.get("end")):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No shift for that person on {day}."
        )

    employees = await scope.employees.find(limit=1000)
    holidays = await scope.holidays.find(limit=1000)
    approved = await _approved_rosters(scope)

    return sick_cover.rank_cover(
        shop=scope.shop,
        employees=employees,
        roster=roster,
        absent_id=employee_id,
        day=day,
        start=shift["start"],
        end=shift["end"],
        week_start=roster["week_start"],
        history_rosters=approved,
        leave_dates=leave_dates(holidays),
        date_iso=_date_for_day(roster["week_start"], day),
    )


@router.post("/rosters/{roster_id}/sick")
async def report_sick(
    roster_id: str, payload: SickReport, scope: ShopScope = CurrentScope
):
    """Mark a shift as sick and optionally hand it to somebody else.

    Works on an APPROVED roster, and deliberately so. Everything else about
    an approved week is locked, because a week people have been told to work
    should not drift. But somebody phoning in at 6am is exactly the case that
    lock cannot serve: unapproving would take the whole week out of what the
    scheduler learns from and let it be regenerated, when all that happened
    is one person is ill.

    So this is a narrow, named, recorded action rather than a general
    "edit anyway" — one shift, one reason, written to the activity log.
    """
    roster = await scope.rosters.find_one({"roster_id": roster_id})
    if not roster:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roster not found")

    shifts = list(roster.get("shifts", []))
    index = next(
        (i for i, s in enumerate(shifts)
         if s.get("employee_id") == payload.employee_id and s.get("day") == payload.day),
        None,
    )
    if index is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No shift for that person on {payload.day}."
        )

    employees = {e["employee_id"]: e for e in await scope.employees.find(limit=1000)}
    absent = employees.get(payload.employee_id, {})
    original = dict(shifts[index])

    # The sick entry keeps the hours they would have worked: the sick-leave
    # balance is spent in hours, and a bare flag would lose that.
    shifts[index] = {
        **original,
        "sick": True,
        "paid_holiday": False,
        "unpaid_holiday": False,
        "pinned": True,
        "sick_reported_at": _now(),
    }

    covered_by = None
    overrides: List[str] = []
    if payload.cover_employee_id:
        cover = employees.get(payload.cover_employee_id)
        if not cover:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such employee to cover.")

        clash = [
            s for s in shifts
            if s.get("employee_id") == payload.cover_employee_id
            and s.get("day") == payload.day
            and s.get("start") and s.get("end")
            and sick_cover._overlaps(
                original["start"], original["end"], s["start"], s["end"]
            )
        ]
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, {
                "message": f"{cover.get('name')} is already working those hours.",
                "reasons": ["Nobody can be in two places at once."],
            })

        span = shift_duration_minutes(original["start"], original["end"]) / 60
        shifts.append({
            "shift_id": f"sh_{uuid.uuid4().hex[:8]}",
            "employee_id": payload.cover_employee_id,
            "day": payload.day,
            "start": original["start"],
            "end": original["end"],
            "span_hours": round(span, 2),
            "break_minutes": break_minutes(span),
            "paid_hours": round(paid_hours(original["start"], original["end"]), 2),
            "fixed": False,
            # Pinned so a later rebalance cannot quietly undo the cover the
            # manager arranged by phone.
            "pinned": True,
            "covering_for": payload.employee_id,
            "overrides": payload.overrides,
        })
        covered_by = cover.get("name")
        overrides = payload.overrides

    rates = {e: emp.get("hourly_rate", 0) for e, emp in employees.items()}
    await scope.rosters.update_one({"roster_id": roster_id}, {
        "shifts": shifts,
        "labor_cost": sum(
            shift_paid_hours(s) * rates.get(s["employee_id"], 0)
            for s in shifts if not (s.get("unpaid_holiday") or s.get("sick"))
        ),
        "total_hours": sum(
            shift_paid_hours(s) for s in shifts
            if not (s.get("unpaid_holiday") or s.get("sick") or s.get("paid_holiday"))
        ),
    })

    # A sick day is an absence in its own right, not only a roster flag, so
    # it shows in the sick report and blocks scheduling for that date.
    date_iso = _date_for_day(roster["week_start"], payload.day)
    if date_iso:
        await scope.holidays.insert({
            "holiday_id": f"hol_{uuid.uuid4().hex[:12]}",
            "date": date_iso,
            "end_date": date_iso,
            "label": payload.reason or "Sick",
            "scope": "sick",
            "employee_id": payload.employee_id,
        })

    await log_activity(
        scope.shop_id, "shift_sick",
        f"{absent.get('name')} off sick {payload.day} "
        f"({original.get('start')}-{original.get('end')})"
        + (f" — covered by {covered_by}" if covered_by else " — NOT COVERED")
        + (f", overriding {', '.join(overrides)}" if overrides else ""),
    )

    return {
        "ok": True,
        "covered_by": covered_by,
        "overrides": overrides,
        "uncovered": covered_by is None,
    }


@router.delete("/rosters/{roster_id}/sick")
async def undo_sick(
    roster_id: str,
    employee_id: str = Query(..., description="Who was marked sick"),
    day: str = Query(..., description="mon..sun"),
    scope: ShopScope = CurrentScope,
):
    """Undo a sick call recorded by mistake.

    Reverses all three things reporting sick did — the flag on the shift, the
    cover that was arranged, and the booked absence. Undoing only the flag
    would leave the shift double-staffed and the person still blocked from
    being rostered that day, which is a worse state than either.

    Cover is removed only if it was added FOR this absence. Somebody who
    happened to be working that day anyway keeps their shift.
    """
    roster = await scope.rosters.find_one({"roster_id": roster_id})
    if not roster:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roster not found")

    shifts = list(roster.get("shifts", []))
    index = next(
        (i for i, s in enumerate(shifts)
         if s.get("employee_id") == employee_id and s.get("day") == day
         and s.get("sick")),
        None,
    )
    if index is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Nobody is marked sick for {day}.",
        )

    employees = {e["employee_id"]: e for e in await scope.employees.find(limit=1000)}
    name = employees.get(employee_id, {}).get("name", employee_id)

    restored = {k: v for k, v in shifts[index].items()
                if k not in ("sick", "sick_reported_at")}
    restored["sick"] = False
    shifts[index] = restored

    dropped = [
        s for s in shifts
        if s.get("covering_for") == employee_id and s.get("day") == day
    ]
    shifts = [s for s in shifts if s not in dropped]

    rates = {e: emp.get("hourly_rate", 0) for e, emp in employees.items()}
    await scope.rosters.update_one({"roster_id": roster_id}, {
        "shifts": shifts,
        "labor_cost": sum(
            shift_paid_hours(s) * rates.get(s["employee_id"], 0)
            for s in shifts if not (s.get("unpaid_holiday") or s.get("sick"))
        ),
        "total_hours": sum(
            shift_paid_hours(s) for s in shifts
            if not (s.get("unpaid_holiday") or s.get("sick") or s.get("paid_holiday"))
        ),
    })

    date_iso = _date_for_day(roster["week_start"], day)
    if date_iso:
        await scope.holidays.delete_one({
            "employee_id": employee_id, "date": date_iso, "scope": "sick",
        })

    covered = ", ".join(
        employees.get(s["employee_id"], {}).get("name", "?") for s in dropped
    )
    await log_activity(
        scope.shop_id, "shift_sick_undone",
        f"Sick call for {name} on {day} removed"
        + (f" — {covered} no longer covering" if covered else ""),
    )
    return {"ok": True, "cover_removed": len(dropped)}


@router.post("/rosters/{roster_id}/extra")
async def add_extra_shift(
    roster_id: str, payload: ExtraShiftReq, scope: ShopScope = CurrentScope
):
    """Roster somebody ABOVE the usual level, deliberately.

    A delivery, a renovation, an unusually busy Saturday. This is the exact
    inverse of pinning: a pin says "*this* person fills that slot", an extra
    says "this person *as well as* the slots". So an extra shift never
    cancels one, and the normal cover is still built underneath it.

    What still applies: the hours are real, so they count against the weekly
    cap, the contract and the five-day limit — an extra shift that quietly
    created a sixth working day would be a trap. The legal limits are not the
    manager's to waive here either; that is what the sick-cover flow is for,
    where an override is named and recorded.
    """
    roster = await scope.rosters.find_one({"roster_id": roster_id})
    if not roster:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such roster.")
    if roster.get("approved"):
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": f"Week of {roster['week_start']} is approved.",
            "reasons": ["Unapprove it first, or use the sick-cover flow for "
                        "a same-day change."],
        })

    employees = {e["employee_id"]: e for e in await scope.employees.find(limit=1000)}
    person = employees.get(payload.employee_id)
    if not person:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such employee.")

    shifts = list(roster.get("shifts", []))
    span = shift_duration_minutes(payload.start, payload.end) / 60
    reasons: List[str] = []

    if violates_minor_curfew(person, payload.start, payload.end):
        reasons.append(
            f"{person['name']} is under 18 — no work before 08:00 or after 19:00."
        )
    if span > ABSOLUTE_MAX_SHIFT_HOURS:
        reasons.append(
            f"{span:.1f}h is over the {ABSOLUTE_MAX_SHIFT_HOURS}h maximum for one shift."
        )
    same_day = [
        s for s in shifts
        if s.get("employee_id") == payload.employee_id
        and s.get("day") == payload.day
    ]
    if any(s.get("paid_holiday") or s.get("unpaid_holiday") for s in same_day):
        reasons.append(f"{person['name']} has booked leave on {payload.day}.")
    clashing = [
        s for s in same_day
        if s.get("start") and s.get("end")
        and sick_cover._overlaps(payload.start, payload.end, s["start"], s["end"])
    ]
    if clashing:
        reasons.append(
            f"{person['name']} is already working "
            f"{clashing[0]['start']}-{clashing[0]['end']} on {payload.day}."
        )

    worked_days = {
        s["day"] for s in shifts
        if s.get("employee_id") == payload.employee_id and s.get("start")
        and not (s.get("paid_holiday") or s.get("unpaid_holiday") or s.get("sick"))
    }
    if payload.day not in worked_days and len(worked_days) >= MAX_WORKING_DAYS:
        reasons.append(
            f"{person['name']} is already on {len(worked_days)} days — a sixth "
            f"would break the five-day limit."
        )

    if reasons:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": f"{person['name']} cannot work {payload.start}-{payload.end} "
                       f"on {payload.day}.",
            "reasons": reasons,
        })

    shifts.append({
        "shift_id": f"sh_{uuid.uuid4().hex[:8]}",
        "employee_id": payload.employee_id,
        "day": payload.day,
        "start": payload.start,
        "end": payload.end,
        "span_hours": round(span, 2),
        "break_minutes": break_minutes(span),
        "paid_hours": round(paid_hours(payload.start, payload.end), 2),
        "fixed": False,
        # Both flags. `extra` keeps it off the demand slots; `pinned` keeps a
        # rebalance from moving the person out from under it.
        "extra": True,
        "pinned": True,
        "extra_reason": payload.reason,
    })

    rates = {e: emp.get("hourly_rate", 0) for e, emp in employees.items()}
    await scope.rosters.update_one({"roster_id": roster_id}, {
        "shifts": shifts,
        "labor_cost": sum(
            shift_paid_hours(s) * rates.get(s["employee_id"], 0)
            for s in shifts if not (s.get("unpaid_holiday") or s.get("sick"))
        ),
        "total_hours": sum(
            shift_paid_hours(s) for s in shifts
            if not (s.get("unpaid_holiday") or s.get("sick") or s.get("paid_holiday"))
        ),
    })
    await log_activity(
        scope.shop_id, "shift_extra_added",
        f"{person['name']} added as extra cover on {payload.day} "
        f"{payload.start}-{payload.end}"
        + (f" — {payload.reason}" if payload.reason else ""),
    )
    return {"ok": True, "shifts": shifts}


@router.post("/rosters/{roster_id}/unapprove")
async def unapprove_roster(roster_id: str, scope: ShopScope = CurrentScope):
    """Reopen an approved roster for editing, and take it back out of learning.

    Approving is what makes a roster real: it becomes the schedule people
    work, and it joins the corpus the scheduler learns this shop's habits
    from. Reopening has to undo both, which is why it is one action rather
    than an "edit anyway" override.

    The unlearning needs no cleanup. Preference weights, the demand curve and
    the familiarity history are all recomputed from `{"approved": True}` at
    the start of every generation and never cached, so clearing the flag
    removes this week from all three the next time a roster is built.

    Superseded drafts stay archived. You are going back to the version you
    approved, not to the ones you rejected.

    A finished week cannot be reopened. By then it is a record of what people
    actually worked, and rewriting it would change the history the scheduler
    has already learned from. A week still in progress stays open, because
    that is exactly when somebody calls in sick.
    """
    roster = await scope.rosters.find_one({"roster_id": roster_id})
    if not roster:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roster not found")

    if not roster.get("approved"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That roster is not approved."
        )

    if _week_has_ended(roster["week_start"]):
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "message": (
                f"Week of {roster['week_start']} has already been worked and "
                "cannot be reopened."
            ),
            "reasons": [
                "Past weeks are the record of what actually happened, and the "
                "scheduler has already learned from them.",
            ],
        })

    await scope.rosters.update_one({"roster_id": roster_id}, {
        "approved": False,
        "unapproved_at": _now(),
        # Cleared with the approval it belonged to, so a reopened roster does
        # not carry a stale "approved accepting 3 uncovered hours" badge.
        "approved_with_gaps": 0,
    })
    await log_activity(
        scope.shop_id, "roster_unapproved",
        f"Unapproved {roster.get('version')} for week of {roster['week_start']} "
        f"— removed from what the scheduler learns from",
    )
    return {
        "ok": True,
        "roster_id": roster_id,
        "week_start": roster["week_start"],
        "unlearned": True,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
@router.post("/roster/{roster_id}/dispatch")
async def dispatch_roster(roster_id: str, scope: ShopScope = CurrentScope):
    roster = await scope.rosters.find_one({"roster_id": roster_id})
    if not roster:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roster not found")

    employees = await scope.employees.find(limit=1000)

    # Imported staff have no email — a spreadsheet does not carry one. They
    # are named back to the manager rather than counted as sent, because a
    # dispatch that reports success while reaching nobody is worse than one
    # that admits who it could not reach.
    addressable = [e for e in employees if e.get("email")]
    no_address = [e["name"] for e in employees if not e.get("email")]

    recipients = [
        {
            "employee_id": e["employee_id"],
            "name": e["name"],
            "email": e["email"],
            "shifts": [s for s in roster.get("shifts", []) if s["employee_id"] == e["employee_id"]],
        }
        for e in addressable
    ]

    outcome = await mailer.send_roster_emails(
        scope.shop.get("name", "Your shop"), roster["week_start"],
        roster.get("version", "v1.0"), recipients,
    )
    outcome["no_email"] = no_address

    await scope.rosters.update_one({"roster_id": roster_id}, {"dispatched_at": _now()})
    await log_activity(
        scope.shop_id, "roster_dispatched",
        f"Dispatched {roster.get('version')} — {len(outcome['sent'])} sent, "
        f"{len(outcome['failed'])} failed",
    )
    return {**outcome, "total": len(recipients)}


# ---------------------------------------------------------------------------
# Historical import / OCR
# ---------------------------------------------------------------------------
