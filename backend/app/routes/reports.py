"""Reports: sick leave and holiday accrual."""
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status

from app.services import sick_balance
from app.services.scheduler import shift_paid_hours
from app.tenancy import ShopScope, CurrentScope

router = APIRouter(tags=["reports"])

# Statutory holiday accrual: 12.07% of hours worked, the standard UK figure
# for staff without fixed hours (5.6 weeks' leave / 46.4 working weeks).
# Named and sourced here so it is not mistaken for an arbitrary constant.
HOLIDAY_ACCRUAL_RATE = 0.1207


@router.get("/reports/sick-balance")
async def sick_balance_report(scope: ShopScope = CurrentScope):
    """Paid sick entitlement, used and remaining, per employee.

    Entitlement is set in days and spent in hours: a day is not a fixed
    quantity, and charging a part-timer's four-hour Saturday as a whole day
    would quietly take more from them than from a full-timer.
    """
    approved = [r async for r in scope.rosters.stream({"approved": True})]
    employees = await scope.employees.find(limit=1000)

    rows = [
        sick_balance.compute_sick_balance(e, approved, shop=scope.shop)
        for e in employees if not e.get("past_staff")
    ]
    return {
        "entitlement_days": sick_balance.paid_sick_days(scope.shop),
        "leave_year": rows[0]["leave_year"] if rows else None,
        # Only people who have actually been off, so the page is a report
        # rather than a roll-call of everybody at full entitlement.
        "rows": sorted(
            [r for r in rows if r["used_hours"] > 0],
            key=lambda r: r["used_hours"], reverse=True,
        ),
        "team_size": len(rows),
        "exhausted": [r["name"] for r in rows if r["exhausted"]],
    }


@router.get("/reports/sick-leave")
async def sick_leave_report(scope: ShopScope = CurrentScope):
    """Sick leave per employee. HR reporting only — never training signal."""
    absences = await scope.holidays.find({"scope": "sick"}, limit=1000)
    employees = {
        e["employee_id"]: e for e in await scope.employees.find(limit=1000)
    }

    by_employee: Dict[str, Dict[str, Any]] = {}
    for absence in absences:
        employee_id = absence.get("employee_id")
        if not employee_id:
            continue

        employee = employees.get(employee_id, {})
        entry = by_employee.setdefault(employee_id, {
            "employee_id": employee_id,
            "name": employee.get("name", "Unknown"),
            "role": employee.get("role", ""),
            "days": 0,
            "occurrences": [],
        })

        start = datetime.strptime(absence["date"], "%Y-%m-%d").date()
        end = datetime.strptime(absence.get("end_date") or absence["date"], "%Y-%m-%d").date()
        days = (end - start).days + 1

        entry["days"] += days
        entry["occurrences"].append({
            "start": absence["date"],
            "end": absence.get("end_date") or absence["date"],
            "days": days,
            "label": absence.get("label"),
        })

    records = sorted(by_employee.values(), key=lambda r: r["days"], reverse=True)
    return {
        "by_employee": records,
        "total_days": sum(r["days"] for r in records),
        "total_incidents": sum(len(r["occurrences"]) for r in records),
    }


async def _accrual_totals(scope: ShopScope) -> Dict[str, Dict[str, float]]:
    """Hours worked and paid holiday taken, per employee, in one pass.

    The prototype re-read every approved roster once per employee, so cost
    grew with employees x rosters. This scans the rosters once and buckets
    by employee, which matters as history accumulates.
    """
    totals: Dict[str, Dict[str, float]] = {}

    async for roster in scope.rosters.stream({"approved": True}):
        for shift in roster.get("shifts", []):
            employee_id = shift.get("employee_id")
            if not employee_id:
                continue
            # Sick days and unpaid leave neither earn nor spend entitlement.
            if shift.get("sick") or shift.get("unpaid_holiday"):
                continue

            bucket = totals.setdefault(employee_id, {"worked": 0.0, "used": 0.0})
            hours = shift_paid_hours(shift)
            if shift.get("paid_holiday"):
                bucket["used"] += hours
            else:
                bucket["worked"] += hours

    return totals


def _balance(worked: float, used: float) -> Dict[str, float]:
    accrued = worked * HOLIDAY_ACCRUAL_RATE
    return {
        "hours_worked": round(worked, 1),
        "accrued_holiday_hours": round(accrued, 2),
        "used_paid_holiday": round(used, 1),
        "balance": round(accrued - used, 2),
    }


@router.get("/employees/holiday-balances")
async def all_holiday_balances(scope: ShopScope = CurrentScope):
    totals = await _accrual_totals(scope)
    employees = await scope.employees.find(limit=1000)
    return [
        {
            "employee_id": e["employee_id"],
            "name": e["name"],
            "role": e.get("role"),
            **_balance(
                totals.get(e["employee_id"], {}).get("worked", 0.0),
                totals.get(e["employee_id"], {}).get("used", 0.0),
            ),
        }
        for e in employees
    ]


# Declared after the literal "/employees/holiday-balances" path so that
# route wins; otherwise "{employee_id}" would capture "holiday-balances".
@router.get("/employees/{employee_id}/holiday-balance")
async def employee_holiday_balance(employee_id: str, scope: ShopScope = CurrentScope):
    if not await scope.employees.find_one({"employee_id": employee_id}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")

    totals = await _accrual_totals(scope)
    bucket = totals.get(employee_id, {"worked": 0.0, "used": 0.0})
    return {"employee_id": employee_id, **_balance(bucket["worked"], bucket["used"])}
