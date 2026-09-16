"""Shop settings and employee/holiday/fixed-shift management."""
import uuid
from datetime import date, datetime, timedelta
from typing import Dict, List, Set

from fastapi import (
    APIRouter, File, Form, HTTPException, Query, UploadFile, status,
)

from app import db
from app.models import (
    ContactApply, EmployeeIn, FixedShiftIn, HolidayIn, LeaveRequest, ShopUpdate,
)
from app.services.scheduler import (
    DAYS, shift_paid_hours, shop_breaks_paid, violates_minor_curfew,
)
from app.services import availability as avail
from app.services import contact_import
from app.services import demand as demand_service
from app.services import holiday_balance
from app.services import hierarchy as hierarchy_service
from app.services import payroll_report
from app.services import setup_status as setup_status_service
from app.services.hierarchy import sort_employees
from app.services.learning import training_summary
from app.services.shop_service import apply_24h_defaults
from app.tenancy import ShopScope, CurrentScope

router = APIRouter(tags=["shop"])


def _record_dates(record: Dict) -> Set[str]:
    """Every date covered by one holiday record, tolerating old bad rows."""
    try:
        start = date.fromisoformat(record["date"])
        end = date.fromisoformat(record.get("end_date") or record["date"])
    except (KeyError, TypeError, ValueError):
        return set()
    if end < start:
        return set()
    return {
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    }


def _overlapping_absences(
    bookings: List[Dict], employee_id: str, requested_dates: Set[str],
    *, exclude_ids: Set[str] | None = None,
) -> List[Dict]:
    """Existing employee absences touching any requested calendar date."""
    excluded = exclude_ids or set()
    return [
        booking for booking in bookings
        if booking.get("holiday_id") not in excluded
        and booking.get("employee_id") == employee_id
        and booking.get("scope") in ("employee", "unavailable", "sick")
        and bool(_record_dates(booking) & requested_dates)
    ]


def _overlap_detail(conflicts: List[Dict]) -> str:
    dates = sorted({day for booking in conflicts for day in _record_dates(booking)})
    shown = ", ".join(dates[:5])
    if len(dates) > 5:
        shown += f" and {len(dates) - 5} more"
    return (
        f"Leave is already booked for this employee on {shown}. "
        "Open the existing booking and use Edit instead."
    )


def _monday(on: date) -> date:
    return on - timedelta(days=on.weekday())


def _leave_staffing_warnings(
    shop: Dict,
    employees: List[Dict],
    approved_rosters: List[Dict],
    bookings: List[Dict],
    employee_id: str,
    requested_dates: Set[str],
    *,
    replace_ids: Set[str] | None = None,
) -> List[str]:
    """Warn only when this booking creates or worsens a daily shortage."""
    replacement_ids = replace_ids or set()
    active = [employee for employee in employees if avail.is_active(employee)]
    roles = {employee["employee_id"]: employee.get("role", "") for employee in active}

    currently_off: Dict[str, Set[str]] = {}
    proposed_off: Dict[str, Set[str]] = {}
    for booking in bookings:
        if booking.get("scope") not in ("employee", "unavailable", "sick"):
            continue
        booked_employee = booking.get("employee_id")
        if not booked_employee:
            continue
        for day_iso in _record_dates(booking):
            currently_off.setdefault(day_iso, set()).add(booked_employee)
            if booking.get("holiday_id") not in replacement_ids:
                proposed_off.setdefault(day_iso, set()).add(booked_employee)
    for day_iso in requested_dates:
        proposed_off.setdefault(day_iso, set()).add(employee_id)

    profile_cache: Dict[str, object] = {}
    history_cache: Dict[str, Dict] = {}
    warnings: List[str] = []
    for day_iso in sorted(requested_dates):
        on = date.fromisoformat(day_iso)
        day = DAYS[on.weekday()]
        week = _monday(on).isoformat()
        if week not in profile_cache:
            earlier = [
                roster for roster in approved_rosters
                if str(roster.get("week_start") or "") < week
            ]
            profile_cache[week] = demand_service.build_profile(
                shop, earlier, roles, for_week=week,
            )
            history_cache[week] = avail.build_shift_history(earlier)
        profile = profile_cache[week]
        slots = profile.slots_for(day)
        target = profile.staff_target(day)
        if target <= 0 or not slots:
            continue

        history = history_cache[week]

        def can_work(employee: Dict, off: Set[str]) -> bool:
            if employee["employee_id"] in off:
                return False
            if shop.get("strict_days_off", True) and day in (
                employee.get("preferred_days_off") or []
            ):
                return False
            cap = avail.weekly_hour_cap(employee, week)
            for start, end in slots:
                if not avail.check_availability(employee, day, start, end).allowed:
                    continue
                if avail.check_familiarity(employee, start, end, history).warning:
                    continue
                if violates_minor_curfew(employee, start, end):
                    continue
                if shift_paid_hours(
                    {"start": start, "end": end},
                    breaks_paid=shop_breaks_paid(shop),
                ) > cap + 1e-6:
                    continue
                return True
            return False

        before = sum(can_work(employee, currently_off.get(day_iso, set())) for employee in active)
        after = sum(can_work(employee, proposed_off.get(day_iso, set())) for employee in active)
        before_short = max(0, target - before)
        after_short = max(0, target - after)
        if after_short <= before_short:
            continue
        label = on.strftime("%A %d %B").replace(" 0", " ")
        warnings.append(
            f"{label}: {after} eligible staff would remain, but the roster "
            f"normally needs {target} ({after_short} short)."
        )
    return warnings


def _raise_staffing_warning(warnings: List[str]) -> None:
    if warnings:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "leave_staffing_shortage",
            "message": "This holiday would leave too few staff to generate the usual roster.",
            "warnings": warnings,
        })


async def _sync_employee_leave_to_drafts(
    scope: ShopScope, employee_id: str, *, replace_dates: Set[str] | None = None,
) -> None:
    """Make open roster cells reflect the employee's current leave bookings.

    Booking or moving leave wins over shifts already present on those dates.
    On later syncs, an ordinary work cell is retained: it represents the
    manager deliberately scheduling the person after seeing the leave warning.
    Approved rosters are records and are never rewritten here.
    """
    replace_dates = replace_dates or set()
    bookings = [
        booking async for booking in scope.holidays.stream({
            "employee_id": employee_id,
            "scope": {"$in": ["employee", "unavailable", "sick"]},
        })
    ]
    booked_by_date: Dict[str, Dict] = {}
    for booking in bookings:
        for booked_date in _record_dates(booking):
            booked_by_date[booked_date] = booking

    employees = await scope.employees.find(limit=1000)
    rates = {
        employee["employee_id"]: employee.get("hourly_rate", 0)
        for employee in employees
    }
    breaks_paid = shop_breaks_paid(scope.shop)

    async for roster in scope.rosters.stream({"approved": {"$ne": True}}):
        try:
            monday = date.fromisoformat(roster["week_start"])
        except (KeyError, TypeError, ValueError):
            continue
        day_for_date = {
            (monday + timedelta(days=index)).isoformat(): day
            for index, day in enumerate(DAYS)
        }

        shifts = []
        for shift in roster.get("shifts", []):
            same_employee = shift.get("employee_id") == employee_id
            shift_date = (
                (monday + timedelta(days=DAYS.index(shift["day"]))).isoformat()
                if shift.get("day") in DAYS else ""
            )
            is_leave = bool(
                shift.get("paid_holiday") or shift.get("unpaid_holiday")
                or shift.get("sick")
            )
            # All stored leave cells are derived again from the booking rows.
            # A newly booked/moved date also replaces any older work cell.
            if same_employee and (is_leave or shift_date in replace_dates):
                continue
            shifts.append(dict(shift))

        occupied = {
            (shift.get("employee_id"), shift.get("day")) for shift in shifts
        }
        for booked_date, booking in booked_by_date.items():
            day = day_for_date.get(booked_date)
            if not day or (employee_id, day) in occupied:
                continue
            is_paid = booking.get("scope") == "employee"
            is_sick = booking.get("scope") == "sick"
            hours = float(booking.get("hours_per_day") or 0) if is_paid else 0.0
            shifts.append({
                "shift_id": f"sh_{uuid.uuid4().hex[:8]}",
                "employee_id": employee_id,
                "day": day,
                "start": "",
                "end": "",
                "fixed": False,
                "paid_holiday": is_paid,
                "unpaid_holiday": not is_paid and not is_sick,
                "sick": is_sick,
                "label": booking.get("label") or (
                    "Holiday" if is_paid else "Sick" if is_sick else "N/A"
                ),
                "span_hours": 0.0,
                "break_minutes": 0,
                "paid_hours": round(hours, 2),
            })

        work_hours: Dict[str, float] = {
            employee["employee_id"]: 0.0 for employee in employees
        }
        total_hours = labor_cost = 0.0
        for shift in shifts:
            hours = shift_paid_hours(shift, breaks_paid=breaks_paid)
            if not (
                shift.get("paid_holiday")
                or shift.get("unpaid_holiday")
                or shift.get("sick")
            ):
                total_hours += hours
                work_hours[shift["employee_id"]] = (
                    work_hours.get(shift["employee_id"], 0.0) + hours
                )
            if not (shift.get("unpaid_holiday") or shift.get("sick")):
                labor_cost += hours * rates.get(shift.get("employee_id"), 0)

        await scope.rosters.update_one({"roster_id": roster["roster_id"]}, {
            "shifts": shifts,
            "total_hours": round(total_hours, 1),
            "labor_cost": round(labor_cost, 2),
            "per_employee_hours": {
                key: round(value, 1) for key, value in work_hours.items()
            },
        })

# Employees are identified by name alone. The prototype assigned each new
# starter one of four stock Unsplash portraits on a rotating index, so a
# fifth employee wore the same stranger's face as the first — actively
# confusing on a roster grid, where the picture is the thing the eye lands on.


# ---------------------------------------------------------------------------
# Shop
# ---------------------------------------------------------------------------
@router.get("/shop")
async def get_shop(scope: ShopScope = CurrentScope):
    return scope.shop


@router.put("/shop")
async def update_shop(payload: ShopUpdate, scope: ShopScope = CurrentScope):
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        return scope.shop

    # Pydantic sub-models arrive as objects; Mongo needs plain dicts.
    if "hours" in changes:
        changes["hours"] = [dict(h) for h in changes["hours"]]
    if "shift_templates" in changes:
        changes["shift_templates"] = [dict(t) for t in changes["shift_templates"]]

    changes = apply_24h_defaults(changes, scope.shop)

    min_hours = changes.get("min_shift_hours", scope.shop.get("min_shift_hours", 4))
    max_hours = changes.get("max_shift_hours", scope.shop.get("max_shift_hours", 9))
    if min_hours > max_hours:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Minimum shift length ({min_hours}h) cannot exceed the maximum ({max_hours}h).",
        )

    await db.shops.update_one({"shop_id": scope.shop_id}, {"$set": changes})
    return await db.shops.find_one({"shop_id": scope.shop_id}, {"_id": 0})


@router.get("/shop/hierarchy")
async def get_role_hierarchy(scope: ShopScope = CurrentScope):
    """The seniority ladder as it currently applies.

    Served rather than reconstructed in the browser so the settings screen
    and the solver can never disagree about the order, and so job titles
    that exist on staff but were never positioned show up instead of
    silently ranking last.
    """
    employees = await scope.employees.find(limit=1000)
    roles_in_use = [e.get("role") for e in employees if e.get("role")]
    hierarchy = hierarchy_service.effective_hierarchy(scope.shop, roles_in_use)
    configured = bool(scope.shop.get("role_hierarchy"))

    counts: dict = {}
    ranks = {role: index for index, role in enumerate(hierarchy)}
    for role in roles_in_use:
        placed = hierarchy_service.rank_of(role, ranks)
        if placed != hierarchy_service.UNRANKED:
            counts[hierarchy[placed]] = counts.get(hierarchy[placed], 0) + 1

    return {
        "hierarchy": hierarchy,
        "is_customised": configured,
        "employee_counts": counts,
        "supervisory": [
            role for role in hierarchy
            if hierarchy_service.is_supervisory(
                role, {**scope.shop, "role_hierarchy": hierarchy}
            )
        ],
        "supervisory_roles": (
            scope.shop.get("supervisory_roles")
            if "supervisory_roles" in scope.shop else None
        ),
    }


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
@router.get("/employees")
async def list_employees(
    scope: ShopScope = CurrentScope,
    limit: int = Query(500, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    include_past: bool = Query(
        False,
        description="Include people who exist only to own imported history.",
    ),
):
    """Everyone, in the order the shop wants to read them.

    That is the manual arrangement if one has been saved, and the job ladder
    otherwise. The roster grid, the printed sheet and the exports all read
    from here so they cannot disagree. Sorted in Python rather than Mongo
    because the order comes from the shop document, not from anything stored
    on the employee.

    People marked `past_staff` are left out. They are leavers who appeared in
    an imported roster: their shifts have to keep an owner or the history
    would show a thinner shop than really worked, but they are not staff any
    more and do not belong in a list the manager reads or picks from.
    """
    query = None if include_past else {"past_staff": {"$ne": True}}
    employees = await scope.employees.find(query, limit=limit, skip=skip)
    return hierarchy_service.display_order(employees, scope.shop)


@router.post("/employees", status_code=status.HTTP_201_CREATED)
async def create_employee(payload: EmployeeIn, scope: ShopScope = CurrentScope):
    return await scope.employees.insert({
        "employee_id": f"emp_{uuid.uuid4().hex[:12]}",
        **payload.model_dump(),
    })


@router.put("/employees/{employee_id}")
async def update_employee(
    employee_id: str, payload: EmployeeIn, scope: ShopScope = CurrentScope
):
    # Saving an employee records that somebody looked at this record.
    #
    # The setup checklist used to work out whether pay and age had been
    # reviewed by comparing them against the importer's defaults. That cannot
    # tell a placeholder from somebody who really is 25, really is on the
    # default rate and really does work 40 hours — so their step could never
    # be ticked, however many times it was edited. Provenance answers the
    # actual question; the values never could.
    modified = await scope.employees.update_one(
        {"employee_id": employee_id},
        {**payload.model_dump(), "details_confirmed": True},
    )
    if modified == 0 and not await scope.employees.find_one({"employee_id": employee_id}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return await scope.employees.find_one({"employee_id": employee_id})


@router.delete("/employees/{employee_id}")
async def delete_employee(employee_id: str, scope: ShopScope = CurrentScope):
    if not await scope.employees.delete_one({"employee_id": employee_id}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    # Fixed shifts reference an employee; leaving them behind would make the
    # solver try to roster somebody who no longer exists.
    await scope.fixed_shifts.delete_many({"employee_id": employee_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Contact details from a shared spreadsheet
#
# The workflow: the manager shares a sheet, the staff type their own name and
# email into it, the manager uploads the result. Nobody types twenty-five
# addresses into a form, and a typo there fails SILENTLY — the address looks
# fine and the rota simply never arrives.
#
# Two steps on purpose. The preview is what makes this safe: matching a name
# to the wrong person emails one member of staff another's working pattern,
# so a human sees every match before anything is written.
# ---------------------------------------------------------------------------
@router.post("/employees/contacts/preview")
async def preview_contacts(
    file: UploadFile = File(...),
    replace: bool = Form(False),
    scope: ShopScope = CurrentScope,
):
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That file is empty.")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That file is larger than 5MB — this expects a list of names, not "
            "a document.",
        )
    try:
        rows = contact_import.parse(data, file.filename or "")
    except contact_import.UnreadableFile as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    if not rows:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No email addresses found in that file. Every row needs a name and "
            "an address — a column heading on its own is not enough.",
        )

    # Active only: an address belonging to somebody who has left is not a
    # match, it is a mistake.
    employees = [e for e in await scope.employees.find(limit=1000)
                 if avail.is_active(e)]
    return contact_import.match(rows, employees, allow_replace=replace).to_dict()


@router.post("/employees/contacts/apply")
async def apply_contacts(
    payload: ContactApply, scope: ShopScope = CurrentScope,
):
    """Write the addresses the manager confirmed in the preview.

    Takes the resolved (employee, email) pairs rather than the file, so what
    is written is exactly what was on screen — re-parsing here would let the
    result differ from the preview that was approved.
    """
    known = {
        e["employee_id"] for e in await scope.employees.find(limit=1000)
        if avail.is_active(e)
    }
    written, skipped = [], []
    for entry in payload.entries:
        if entry.employee_id not in known:
            skipped.append(entry.employee_id)
            continue
        if not contact_import.EMAIL.match(entry.email.strip()):
            skipped.append(entry.employee_id)
            continue
        await scope.employees.update_one(
            {"employee_id": entry.employee_id},
            {"email": entry.email.strip()},
        )
        written.append(entry.employee_id)

    return {"updated": len(written), "skipped": len(skipped)}


# ---------------------------------------------------------------------------
# Holidays / leave
# ---------------------------------------------------------------------------
@router.get("/holidays")
async def list_holidays(scope: ShopScope = CurrentScope):
    return await scope.holidays.find(sort=[("date", -1)])


@router.post("/holidays", status_code=status.HTTP_201_CREATED)
async def create_holiday(payload: HolidayIn, scope: ShopScope = CurrentScope):
    data = payload.model_dump()
    confirmed_shortage = data.pop("confirm_staffing_shortage")
    if data["scope"] in ("employee", "unavailable", "sick") and not data.get("employee_id"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"An employee must be selected for {data['scope']} leave.",
        )
    if data.get("end_date") and data["end_date"] < data["date"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "End date cannot precede the start date.")

    requested_dates = _record_dates(data)
    if data.get("employee_id"):
        bookings = [booking async for booking in scope.holidays.stream()]
        conflicts = _overlapping_absences(
            bookings, data["employee_id"], requested_dates,
        )
        if conflicts:
            raise HTTPException(status.HTTP_409_CONFLICT, _overlap_detail(conflicts))
        if data["scope"] in ("employee", "unavailable") and not confirmed_shortage:
            _raise_staffing_warning(_leave_staffing_warnings(
                scope.shop,
                await scope.employees.find(limit=1000),
                [roster async for roster in scope.rosters.stream({"approved": True})],
                bookings,
                data["employee_id"],
                requested_dates,
            ))

    created = await scope.holidays.insert({
        "holiday_id": f"hol_{uuid.uuid4().hex[:10]}", **data
    })
    if data.get("employee_id"):
        await _sync_employee_leave_to_drafts(
            scope, data["employee_id"], replace_dates=requested_dates,
        )
    return created


MAX_LEAVE_DAYS = 190   # roughly six months; guards against a typo'd year


@router.post("/holidays/leave", status_code=status.HTTP_201_CREATED)
async def book_leave(payload: LeaveRequest, scope: ShopScope = CurrentScope):
    """Book leave over a date range, marking which days are paid.

    Only days inside the range are written — two days off leaves the rest of
    that week untouched, so the employee still works normally around it.
    Within the range, ticked dates become paid holiday and everything else
    becomes unavailable: unpaid, and not rostered.
    """
    employee = await scope.employees.find_one({"employee_id": payload.employee_id})
    if not employee:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")

    def parse(value: str, field: str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{field} '{value}' is not a valid date (expected YYYY-MM-DD)",
            )

    start = parse(payload.start_date, "start_date")
    end = parse(payload.end_date, "end_date")
    if end < start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The end date is before the start date.")

    span_days = (end - start).days + 1
    if span_days > MAX_LEAVE_DAYS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"That is {span_days} days of leave — check the dates.",
        )

    all_dates = [(start + timedelta(days=i)).isoformat() for i in range(span_days)]
    date_set = set(all_dates)

    # Reject paid dates outside the range rather than silently dropping them:
    # it almost always means the form and the range have drifted apart.
    stray = [d for d in payload.paid_dates if d not in date_set]
    if stray:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"These paid dates fall outside the leave range: {', '.join(sorted(stray)[:5])}",
        )
    paid_dates = set(payload.paid_dates)

    # Holiday pay is a normal day's pay, so default to their contract spread
    # across five days rather than an arbitrary 8 hours.
    hours = payload.hours_per_day
    if hours is None:
        contract = employee.get("max_weekly_hours") or 0
        hours = round(contract / 5, 2) if contract else 8.0

    # Booking more paid holiday than someone has earned is blocked, not
    # warned about: the alternative is finding out at payroll, after the
    # person has been told they are off.
    approved = [r async for r in scope.rosters.stream({"approved": True})]
    bookings = [h async for h in scope.holidays.stream()]

    # Edit sends the exact records it is replacing. Release those reservations
    # for the capacity check, otherwise somebody with a fully-used balance
    # cannot move or shorten an existing booking. Every id is still checked
    # inside this shop and against this employee before anything is deleted.
    replace_ids = set(payload.replace_holiday_ids)
    replacement_rows = [
        holiday for holiday in bookings
        if holiday.get("holiday_id") in replace_ids
    ]
    found_ids = {holiday.get("holiday_id") for holiday in replacement_rows}
    if found_ids != replace_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "One or more leave entries being replaced no longer exist. Refresh and try again.",
        )
    if any(
        holiday.get("employee_id") != payload.employee_id
        or holiday.get("scope") not in ("employee", "unavailable")
        for holiday in replacement_rows
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only this employee's existing holiday entries can be replaced.",
        )

    conflicts = _overlapping_absences(
        bookings, payload.employee_id, date_set, exclude_ids=replace_ids,
    )
    if conflicts:
        raise HTTPException(status.HTTP_409_CONFLICT, _overlap_detail(conflicts))

    # Only Edit may release an existing reservation. A new booking that
    # happens to overlap must not silently become an edit.
    balance = holiday_balance.compute_balance(
        employee, approved, shop=scope.shop, holidays=bookings,
        excluded_holiday_ids=replace_ids,
    )
    requested_hours = hours * len(paid_dates)
    verdict = holiday_balance.check_can_book(balance, requested_hours)
    if not verdict["allowed"]:
        affordable = holiday_balance.max_payable_days(balance, hours)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{employee['name']} has {verdict['available_hours']:g}h of holiday "
            f"available, which covers {affordable} day(s) at {hours:g}h each. "
            f"You marked {len(paid_dates)} paid day(s) = {requested_hours:g}h "
            f"({verdict['shortfall_hours']:g}h short). Mark the extra days as "
            f"unpaid, or adjust their balance.",
        )

    if not payload.confirm_staffing_shortage:
        _raise_staffing_warning(_leave_staffing_warnings(
            scope.shop,
            await scope.employees.find(limit=1000),
            approved,
            bookings,
            payload.employee_id,
            date_set,
            replace_ids=replace_ids,
        ))

    # Replace only the exact records named by Edit, including old dates outside
    # the new range. Add never supplies these ids, so it can never overwrite a
    # booking merely because the dates happen to match.
    if replace_ids:
        await scope.holidays.delete_many({
            "holiday_id": {"$in": sorted(replace_ids)},
            "employee_id": payload.employee_id,
            "scope": {"$in": ["employee", "unavailable"]},
        })

    for date_iso in all_dates:
        is_paid = date_iso in paid_dates
        await scope.holidays.insert({
            "holiday_id": f"hol_{uuid.uuid4().hex[:10]}",
            "date": date_iso,
            "end_date": date_iso,
            "label": payload.label if is_paid else f"{payload.label} (unpaid)",
            "scope": "employee" if is_paid else "unavailable",
            "employee_id": payload.employee_id,
            **({"hours_per_day": hours} if is_paid else {}),
        })

    # Booking and editing leave immediately changes every open roster week it
    # touches. This is what turns unticked days inside the range into visible
    # N/A cells instead of leaving stale shifts or empty '+' cells behind.
    await _sync_employee_leave_to_drafts(
        scope, payload.employee_id, replace_dates=date_set,
    )

    return {
        "ok": True,
        "employee": employee["name"],
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "total_days": span_days,
        "paid_days": len(paid_dates),
        "unpaid_days": span_days - len(paid_dates),
        "paid_hours_total": round(hours * len(paid_dates), 2),
        "hours_per_day": hours,
        "replaced_entries": len(replacement_rows),
    }


@router.put("/holidays/{holiday_id}")
async def update_holiday(
    holiday_id: str, payload: HolidayIn, scope: ShopScope = CurrentScope
):
    """Correct an existing leave entry in place.

    Added for the redesigned Holidays page, where every row has an Edit that
    opens the booking form pre-filled. Before this the only way to fix a
    mistyped date was to delete the entry and add it again, which is fine
    until somebody deletes the wrong one — the reason the bare per-row trash
    icon was removed.

    The same validation as `create_holiday`, deliberately: an entry that
    could not be created should not be reachable by editing into it.
    """
    data = payload.model_dump()
    confirmed_shortage = data.pop("confirm_staffing_shortage")
    if data["scope"] in ("employee", "unavailable", "sick") and not data.get("employee_id"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"An employee must be selected for {data['scope']} leave.",
        )
    if data.get("end_date") and data["end_date"] < data["date"]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "End date cannot precede the start date.",
        )

    # Existence is checked separately because `update_one` reports how many
    # documents it CHANGED, and re-saving a booking without touching a field
    # changes none — which would 404 an edit that opened the form, altered
    # nothing and pressed Save. Not hypothetical: that is the commonest way
    # to leave an edit dialog.
    existing = await scope.holidays.find_one({"holiday_id": holiday_id})
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found")

    requested_dates = _record_dates(data)
    if data.get("employee_id"):
        bookings = [booking async for booking in scope.holidays.stream()]
        conflicts = _overlapping_absences(
            bookings, data["employee_id"], requested_dates,
            exclude_ids={holiday_id},
        )
        if conflicts:
            raise HTTPException(status.HTTP_409_CONFLICT, _overlap_detail(conflicts))
        if data["scope"] in ("employee", "unavailable") and not confirmed_shortage:
            _raise_staffing_warning(_leave_staffing_warnings(
                scope.shop,
                await scope.employees.find(limit=1000),
                [roster async for roster in scope.rosters.stream({"approved": True})],
                bookings,
                data["employee_id"],
                requested_dates,
                replace_ids={holiday_id},
            ))

    await scope.holidays.update_one({"holiday_id": holiday_id}, data)
    old_employee_id = existing.get("employee_id")
    if old_employee_id and old_employee_id != data.get("employee_id"):
        await _sync_employee_leave_to_drafts(scope, old_employee_id)
    if data.get("employee_id"):
        await _sync_employee_leave_to_drafts(
            scope, data["employee_id"], replace_dates=requested_dates,
        )
    return await scope.holidays.find_one({"holiday_id": holiday_id})


@router.delete("/holidays/{holiday_id}")
async def delete_holiday(holiday_id: str, scope: ShopScope = CurrentScope):
    existing = await scope.holidays.find_one({"holiday_id": holiday_id})
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found")
    if not await scope.holidays.delete_one({"holiday_id": holiday_id}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found")
    if existing.get("employee_id"):
        await _sync_employee_leave_to_drafts(scope, existing["employee_id"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Fixed shifts
# ---------------------------------------------------------------------------
@router.get("/fixed-shifts")
async def list_fixed_shifts(scope: ShopScope = CurrentScope):
    return await scope.fixed_shifts.find()


@router.post("/fixed-shifts", status_code=status.HTTP_201_CREATED)
async def create_fixed_shift(payload: FixedShiftIn, scope: ShopScope = CurrentScope):
    if not await scope.employees.find_one({"employee_id": payload.employee_id}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return await scope.fixed_shifts.insert({
        "fixed_id": f"fs_{uuid.uuid4().hex[:10]}", **payload.model_dump()
    })


@router.delete("/fixed-shifts/{fixed_id}")
async def delete_fixed_shift(fixed_id: str, scope: ShopScope = CurrentScope):
    if not await scope.fixed_shifts.delete_one({"fixed_id": fixed_id}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fixed shift not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------
@router.get("/activity")
async def list_activity(
    scope: ShopScope = CurrentScope,
    limit: int = Query(100, ge=1, le=500),
):
    return await scope.activity_logs.find(limit=limit, sort=[("created_at", -1)])


# ---------------------------------------------------------------------------
# Hours and wages
# ---------------------------------------------------------------------------
@router.get("/reports/hours")
async def hours_report(
    start: str = Query(..., description="First day, YYYY-MM-DD"),
    end: str = Query(..., description="Last day, inclusive, YYYY-MM-DD"),
    scope: ShopScope = CurrentScope,
):
    """Hours, breaks and wages per employee for a date range.

    Streams every approved roster rather than paging: a report that quietly
    dropped a week would understate somebody's wages, and be believed.
    """
    approved = [r async for r in scope.rosters.stream({"approved": True})]
    try:
        return payroll_report.build_report(
            shop=scope.shop,
            # Includes leavers and past staff — they worked the hours and are
            # owed for them, whatever their status is now.
            employees=await scope.employees.find(limit=1000),
            rosters=approved,
            start=start,
            end=end,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# ---------------------------------------------------------------------------
# Getting started
# ---------------------------------------------------------------------------
@router.get("/setup-status")
async def setup_status(scope: ShopScope = CurrentScope):
    """What is still outstanding before this shop can roster properly.

    Answered here rather than in the browser so "done" has one definition.
    The dashboard asking six endpoints and applying its own rules would drift
    from what the scheduler actually requires the moment either changed.
    """
    approved = [r async for r in scope.rosters.stream({"approved": True})]
    return setup_status_service.build_steps(
        shop=scope.shop,
        employees=await scope.employees.find(limit=1000),
        learning=training_summary(approved),
        fixed_shifts=await scope.fixed_shifts.find(limit=1000),
        holidays=await scope.holidays.find(limit=1000),
        rosters=await scope.rosters.find(limit=500),
    )
