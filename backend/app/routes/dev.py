"""Destructive development helpers.

These routes wipe data. The router is only mounted when
config.DEV_ROUTES_ENABLED is true, and that flag is forced off in
production — so in a production deployment these paths do not exist at all
rather than merely being discouraged.
"""
import uuid

from fastapi import APIRouter, status

from app import db
from app.services.shop_service import (
    DEFAULT_HOURS,
    seed_system_rules,
)
from app.tenancy import ShopScope, CurrentScope

router = APIRouter(tags=["dev"])

DEMO_EMPLOYEES = [
    {"name": "Aisha Rahman", "email": "aisha@demo.co", "role": "Manager", "age": 34,
     "hourly_rate": 28.0, "max_weekly_hours": 40, "preferred_days_off": ["sun"]},
    {"name": "Marcus Chen", "email": "marcus@demo.co", "role": "Supervisor", "age": 28,
     "hourly_rate": 22.0, "max_weekly_hours": 40, "preferred_days_off": ["mon"]},
    {"name": "Priya Nair", "email": "priya@demo.co", "role": "Cashier", "age": 22,
     "hourly_rate": 16.0, "max_weekly_hours": 40, "preferred_days_off": ["tue"]},
    {"name": "Jordan Lee", "email": "jordan@demo.co", "role": "Cashier", "age": 19,
     "hourly_rate": 15.5, "max_weekly_hours": 20, "preferred_days_off": ["wed"]},
    {"name": "Sofia Diaz", "email": "sofia@demo.co", "role": "Floor Assistant", "age": 17,
     "hourly_rate": 14.0, "max_weekly_hours": 20, "preferred_days_off": ["thu"]},
    {"name": "Ethan Park", "email": "ethan@demo.co", "role": "Stocker", "age": 24,
     "hourly_rate": 15.0, "max_weekly_hours": 40, "preferred_days_off": ["fri"]},
    {"name": "Lena Volkov", "email": "lena@demo.co", "role": "Floor Assistant", "age": 15,
     "hourly_rate": 12.5, "max_weekly_hours": 20, "preferred_days_off": ["sat"]},
]

@router.post("/seed-demo", status_code=status.HTTP_201_CREATED)
async def seed_demo(scope: ShopScope = CurrentScope):
    """Replace demo staff with a fresh set. Real employees are untouched."""
    await scope.employees.delete_many({"demo": True})
    for employee in DEMO_EMPLOYEES:
        await scope.employees.insert({
            "employee_id": f"emp_{uuid.uuid4().hex[:12]}",
            "departments": ["Shop Floor"],
            "demo": True,
            **employee,
        })
    return {"ok": True, "count": len(DEMO_EMPLOYEES)}


@router.post("/dev/reset")
async def reset_shop(scope: ShopScope = CurrentScope):
    """Delete every record for the caller's shop and restore defaults."""
    await scope.employees.delete_many()
    await scope.holidays.delete_many()
    await scope.fixed_shifts.delete_many()
    await scope.rosters.delete_many()
    await scope.activity_logs.delete_many()
    await scope.ai_rules.delete_many()

    await seed_system_rules(scope.shop_id)
    await db.shops.update_one({"shop_id": scope.shop_id}, {"$set": {
        "onboarded": False,
        "hours": DEFAULT_HOURS,
        "min_shift_hours": 4,
        "max_shift_hours": 9,
        "open_24h": False,
        "shift_templates": [],
    }})
    return {"ok": True, "message": "Shop reset. System rules restored."}
