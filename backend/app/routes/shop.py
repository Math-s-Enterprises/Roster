"""Shop settings and employee/holiday/fixed-shift management."""
import uuid
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, HTTPException, Query, status

from app import db
from app.models import EmployeeIn, FixedShiftIn, HolidayIn, LeaveRequest, ShopUpdate
from app.services.scheduler import DAYS
from app.services import holiday_balance
from app.services import hierarchy as hierarchy_service
from app.services import payroll_report
from app.services import setup_status as setup_status_service
from app.services.hierarchy import sort_employees
from app.services.learning import training_summary
from app.services.shop_service import apply_24h_defaults
from app.tenancy import ShopScope, CurrentScope

router = APIRouter(tags=["shop"])

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
            if hierarchy_service.is_supervisory(role, {"role_hierarchy": hierarchy})
        ],
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
    modified = await scope.employees.update_one(
        {"employee_id": employee_id}, payload.model_dump()
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
# Holidays / leave
# ---------------------------------------------------------------------------
@router.get("/holidays")
async def list_holidays(scope: ShopScope = CurrentScope):
    return await scope.holidays.find(sort=[("date", -1)])


@router.post("/holidays", status_code=status.HTTP_201_CREATED)
async def create_holiday(payload: HolidayIn, scope: ShopScope = CurrentScope):
    data = payload.model_dump()
    if data["scope"] in ("employee", "sick") and not data.get("employee_id"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"An employee must be selected for {data['scope']} leave.",
        )
    if data.get("end_date") and data["end_date"] < data["date"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "End date cannot precede the start date.")

    return await scope.holidays.insert({
        "holiday_id": f"hol_{uuid.uuid4().hex[:10]}", **data
    })


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
    balance = holiday_balance.compute_balance(employee, approved, shop=scope.shop)
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

    # Replace any existing leave in this range, so re-booking corrects rather
    # than duplicates.
    await scope.holidays.delete_many({
        "employee_id": payload.employee_id,
        "date": {"$in": all_dates},
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
    }


@router.delete("/holidays/{holiday_id}")
async def delete_holiday(holiday_id: str, scope: ShopScope = CurrentScope):
    if not await scope.holidays.delete_one({"holiday_id": holiday_id}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found")
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
