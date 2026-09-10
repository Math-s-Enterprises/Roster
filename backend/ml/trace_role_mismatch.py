"""Read-only stage and candidate trace for one historical simulation."""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db
from app.tenancy import ShopScope, ScopedCollection
from app.services import compliance, availability
from app.services.demand import build_profile
from app.services.hierarchy import sort_employees
from app.services.learning import compute_weights
from app.services.scheduler import _RosterBuilder
from ml.role_experiment import clean_history, earlier_weeks, working


class TraceBuilder(_RosterBuilder):
    def __init__(self, *args, **kwargs):
        self.trace = []
        self.choices = []
        super().__init__(*args, **kwargs)

    def view(self, shifts):
        return [{"employee": self.employees_by_id[s["employee_id"]].get("name"),
                 "role": self.employees_by_id[s["employee_id"]].get("role"),
                 "day": s["day"], "start": s["start"], "end": s["end"],
                 "fixed": s.get("fixed", False), "contract_top_up": s.get("contract_top_up", False)}
                for s in working(shifts)]

    def _pick_for_slot(self, eligible, rank_of, day, start, end):
        chosen = super()._pick_for_slot(eligible, rank_of, day, start, end)
        self.choices.append({"day": day, "start": start, "end": end,
                             "selected": chosen.get("name"),
                             "candidates": [{"employee": e.get("name"), "role": e.get("role"),
                                             "rank": rank_of(e), "span_used": self.span_used.get(e["employee_id"], 0)}
                                            for e in sorted(eligible, key=rank_of)]})
        return chosen


def traced(method):
    def wrapper(self, *args, **kwargs):
        before = self.view(self.result.shifts)
        result = method(self, *args, **kwargs)
        after = self.view(self.result.shifts)
        removed = list(before)
        added = []
        for row in after:
            if row in removed:
                removed.remove(row)
            else:
                added.append(row)
        if added or removed:
            self.trace.append({"pass": method.__name__, "added": added, "removed": removed,
                               "role_counts_after": dict(Counter(s["role"] for s in after))})
        return result
    return wrapper


for name in ("_apply_fixed_shifts", "_ensure_supervisory_cover", "_staff_by_slots",
             "_enforce_coverage_floor", "_top_up_contracts", "_fit_contract_hours",
             "_close_short_hours", "_rebalance_hours", "_drop_duplicate_days"):
    setattr(TraceBuilder, name, traced(getattr(_RosterBuilder, name)))


async def run(shop_id, week, output):
    shop = await ScopedCollection(db.shops, shop_id).find_one()
    if not shop:
        raise ValueError("Unknown shop")
    scope = ShopScope(shop, {})
    employees = [e async for e in scope.employees.stream()]
    holidays = [h async for h in scope.holidays.stream()]
    fixed = [f async for f in scope.fixed_shifts.stream()]
    rules = [r async for r in scope.ai_rules.stream({"enabled": True})]
    approved = [r async for r in scope.rosters.stream({"approved": True})]
    clean, _ = clean_history(approved, {e["employee_id"] for e in employees})
    target = next(r for r in clean if r["week_start"] == week)
    history = earlier_weeks(clean, week)
    profile = build_profile(shop, history, {e["employee_id"]: e.get("role", "") for e in employees}, for_week=week)
    builder = TraceBuilder(shop, sort_employees(employees, shop), holidays, fixed, rules, week,
                           compute_weights(history), profile, history_rosters=history)
    result = builder.solve().to_dict()
    reference = builder.view(target["shifts"])
    generated = builder.view(result["shifts"])
    report = {"week": week, "history_weeks": len(history), "stages": builder.trace,
              "choices": builder.choices, "reference": reference, "generated": generated,
              "solver_empty_hours": [[d, h] for d in builder.on_duty for h in builder._open_hours(d) if builder.on_duty[d][h] == 0],
              "approval_empty_hours": compliance.uncovered_hours(result["shifts"], shop=shop),
              "carried_in": builder.carried_in, "wrap_week": builder.wrap_week,
              "issues": result.get("issues"), "critical_issues": result.get("critical_issues"),
              "slots": {d: builder._slots_for_day(d) for d in builder.on_duty},
              "staff": [{"name": e.get("name"), "role": e.get("role"), "active": availability.is_active(e),
                         "availability": e.get("availability"), "employment_type": e.get("employment_type"),
                         "cap": builder.hour_caps[e["employee_id"]], "contract_band": builder.span_bands[e["employee_id"]],
                         "leave_this_week": sorted(d for d in builder.employee_off_dates.get(e["employee_id"], []) if d in builder.date_for_day.values()),
                         "leave_dates_total": len(builder.employee_off_dates.get(e["employee_id"], [])),
                         "exclusion": builder.exclusions.get(e["employee_id"]),
                         "reference_days": [s["day"] for s in reference if s["employee"] == e.get("name")],
                         "generated_days": [s["day"] for s in generated if s["employee"] == e.get("name")]}
                        for e in employees],
              "role_history": [{"week": r["week_start"], "counts": dict(Counter(s["role"] for s in builder.view(r["shifts"])))} for r in history[-8:]]}
    with output.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(json.dumps({"week": week, "reference": dict(Counter(s["role"] for s in reference)),
                      "generated": dict(Counter(s["role"] for s in generated)),
                      "solver_empty_hours": report["solver_empty_hours"],
                      "approval_empty_hours": report["approval_empty_hours"]}, indent=2))


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", required=True)
    parser.add_argument("--week", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        await run(args.shop_id, args.week, args.output)
    finally:
        db.client.close()


if __name__ == "__main__":
    asyncio.run(main())
