"""Reproduce out-of-week leave effects without a database or application writes.

Run from backend: python ml/verify_scheduler_findings.py
This reports current behaviour; it is not a passing regression test for a fix.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.scheduler import _RosterBuilder, DAYS
from app.services.demand import build_profile


def probe():
    shop = {"hours": [{"day": day, "open": "09:00", "close": "21:00", "closed": i > 4}
                      for i, day in enumerate(DAYS)]}
    employee = {"employee_id": "e1", "name": "Example", "role": "Supervisor",
                "age": 30, "hourly_rate": 0, "employment_type": "full_time_contract",
                "contract_span_hours": 40, "max_weekly_hours": 48, "is_active": True,
                "preferred_days_off": []}
    history = [{"week_start": week, "approved": True, "shifts": [
        {"employee_id": "e1", "day": day, "start": "09:00", "end": "17:00"}
        for day in DAYS[:4]]} for week in ("2026-07-20", "2026-07-27", "2026-08-03", "2026-08-10")]
    results = {}
    for scenario, holidays in (
        ("no_leave", []),
        ("leave_in_december", [{"scope": "employee", "employee_id": "e1", "date": "2026-12-01"}]),
    ):
        results[scenario] = {}
        for phase in ("add_shifts", "extend_shifts"):
            profile = build_profile(shop, history, {"e1": "Supervisor"}, for_week="2026-08-17")
            builder = _RosterBuilder(shop, [employee], holidays, [], [], "2026-08-17", {}, profile,
                                     history_rosters=history)
            if phase == "add_shifts":
                builder._top_up_contracts(builder._trading_days())
            else:
                for day in DAYS[:4]:
                    builder._record_shift("e1", day, "09:00", "17:00")
                builder._fit_contract_hours()
            results[scenario][phase] = {
                "final_span_hours": builder.span_used.get("e1", 0),
                "leave_dates_in_target_week": sorted(
                    set(builder.employee_off_dates.get("e1", [])) & set(builder.date_for_day.values())),
            }
    return results


if __name__ == "__main__":
    print(json.dumps(probe(), indent=2))
