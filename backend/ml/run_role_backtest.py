"""Read-only historical simulations; writes local reports, never live rosters.

From backend: python ml/run_role_backtest.py --shop-id ID --output NEW_DIRECTORY
Optional: --reference-csv FILE --reference-week YYYY-MM-DD
NumPy is needed only for this offline experiment.
"""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db
from app.tenancy import ShopScope, ScopedCollection
from app.services import compliance
from app.services.demand import build_profile
from app.services.hierarchy import sort_employees
from app.services.learning import compute_weights
from app.services.scheduler import _RosterBuilder, DAYS
from app.services.training_evidence import digest
from ml.role_experiment import (ChoiceModel, ModelBuilder, canonical_role,
                                clean_history, earlier_weeks, role_metrics, role_rows)


def read_reference(path, aliases):
    from app.models import _validate_hhmm
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            day = row["Day"].strip().lower()
            if day not in DAYS or not row["Role"].strip():
                raise ValueError("Reference CSV contains an invalid day or empty role")
            rows.append({"day": day, "role": canonical_role(row["Role"], aliases),
                         "start": _validate_hhmm(row["Start"]),
                         "end": _validate_hhmm(row["End"])})
    if not rows:
        raise ValueError("Reference CSV has no shifts")
    return rows


def read_workbook_reference(path, week, aliases):
    from app.services.roster_import import parse_workbook_rows, read_xlsx
    weeks = parse_workbook_rows(read_xlsx(str(path)))
    matches = [w for w in weeks if w.week_start == week]
    if len(matches) != 1 or not matches[0].is_usable or matches[0].unparsed_cells:
        raise ValueError("Workbook reference week is missing, duplicated or contains unparsed cells")
    target = matches[0]
    rows = [{"day": s.day, "role": canonical_role(s.role or "unknown", aliases),
             "start": s.start, "end": s.end} for s in target.shifts]
    audit = {"file": path.name, "sheet_count": len(weeks),
             "target_warning_count": len(target.warnings),
             "target_unparsed_cells": len(target.unparsed_cells),
             "duplicate_dates": {d: n for d, n in Counter(w.week_start for w in weeks if w.week_start).items() if n > 1},
             "undated_sheets": sum(not w.week_start for w in weeks),
             "weeks_with_unparsed_cells": [{"week": w.week_start, "cells": len(w.unparsed_cells)} for w in weeks if w.unparsed_cells]}
    return rows, audit


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")


def render_report(report, output):
    lines = ["# Role-based historical simulations and first fitted model", "",
             f"Shop: {report['shop']}. No employee-name matching and no live roster writes.", "",
             "## How to read this", "",
             "Both methods receive only earlier clean roster weeks. The baseline is the existing solver; the experiment replaces non-owner historical ranking with fitted day/start employee-choice scores. Ownership, contracts, eligibility and downstream scheduling passes remain in force.", "",
             "These are CURRENT-CONTEXT SIMULATIONS, not faithful historical replays. Current employee roles, active status, availability, holiday records, summer-break settings, fixed shifts and shop rules may differ from the settings used by the manager then. Roles stored on shifts take precedence; otherwise current employee roles supply the label. Neither method sees target-week assignments as inputs.", "",
             "Lower role-count distance means closer daily staffing counts. Role-presence distance sums missing and extra person-hours by role at exact minute intervals. It measures difference from a reference, not proof that the reference is the only workable roster. Exact role/time matches ignore names and preserve duplicate shift counts. Both uncovered-hour diagnostics use the actual previous approved Sunday when it exists, matching the repaired scheduler and approval paths. No full custom-rule approval certification is implied.", "",
             "## Per-week results", "",
             "| Week / reference | Reference shifts | Baseline shifts | ML shifts | Role count distance: baseline → ML | Role presence distance (h): baseline → ML | Exact role/time matches: baseline → ML |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for run in report["weeks"]:
        b, m = run["baseline"], run["model"]
        lines.append(f"| {run['week']} / {run['reference_source']} | {b['reference_shifts']} | {b['generated_shifts']} | {m['generated_shifts']} | {b['day_role_count_distance']} → {m['day_role_count_distance']} | {b['role_presence_distance_hours']:.1f} → {m['role_presence_distance_hours']:.1f} | {b['exact_role_time_matches']} → {m['exact_role_time_matches']} |")
    lines += ["", "## Aggregate comparison", "",
              "Compare role counts and time coverage together; lower count error alone can hide worse coverage.", "",
              "| Measure | Existing solver | Fitted model |", "|---|---:|---:|"]
    totals = report["aggregate"] if not (report.get("external_reference") or {}).get("roles_without_employee_mapping") else report["aggregate_stored_references_only"]
    for key, label in (("day_role_count_distance", "Daily role-count difference"),
                       ("arrival_count_distance", "Arrival-hour count difference, all roles"),
                       ("role_arrival_count_distance", "Role/start-hour count difference"),
                       ("role_presence_distance_hours", "Role-at-time difference (person-hours)"),
                       ("exact_role_time_matches", "Matching role and exact shift times"),
                       ("uncovered_hours", "Solver uncovered hours, previous-week carry-in included")):
        lines.append(f"| {label} | {totals['baseline'][key]:.1f} | {totals['model'][key]:.1f} |")
    lines += ["", "## Constraint diagnostics", "",
              "| Week | Baseline uncovered hours | ML uncovered hours | Baseline audit breaches | ML audit breaches | ML ranking calls changed |",
              "|---|---:|---:|---|---|---:|"]
    for run in report["weeks"]:
        b, m = run["baseline"], run["model"]
        lines.append(f"| {run['week']} | {b['uncovered_hours']} | {m['uncovered_hours']} | {b['audit_breaches']} | {m['audit_breaches']} | {run['ranking_changes']} |")
    external = report.get("external_reference")
    lines += ["", "## Attached reference", ""]
    if external:
        lines += [f"{external['week']}: attached reference {external['csv_shifts']} shifts; stored reference {external['stored_shifts']} shifts.", "",
                  "Roles without an employee-role mapping: " + ", ".join(external['roles_without_employee_mapping']), "",
                  "| Role | Attached reference shifts | Stored shifts |", "|---|---:|---:|"]
        for role in sorted(external['csv_role_counts'].keys() | external['stored_role_counts'].keys()):
            lines.append(f"| {role} | {external['csv_role_counts'].get(role, 0)} | {external['stored_role_counts'].get(role, 0)} |")
    lines += ["",
              "The supplied reference is compared with the stored week for that date; neither was imported or overwritten. Unknown role labels remain explicit rather than being guessed into the shop hierarchy.", "",
              "## Data and model limits", "", "```json", json.dumps(report["data_summary"], indent=2), "```", "",
              "Quarantined weeks: " + json.dumps(report["quarantined_weeks"]), "",
              "One fixed model configuration was used without selecting parameters on the held-out weeks. Its training loss is only an optimisation check. The model learns observed worker choices, not historical unavailability, and its scores are not calibrated suitability probabilities. Preserving owners means it can influence only part of the roster. Model artefacts are local research output, not deployed models.", "",
              "Compare the baseline and model against each reference, then judge whether changes are operationally useful. Aggregate reference similarity alone does not establish better scheduling or correction learning."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run(args):
    # Registry lookup is scoped too: no global tenant enumeration is needed.
    shop = await ScopedCollection(db.shops, args.shop_id).find_one()
    if not shop:
        raise ValueError("Shop not found")
    scope = ShopScope(shop, {})
    employees = [e async for e in scope.employees.stream()]
    holidays = [h async for h in scope.holidays.stream()]
    fixed = [f async for f in scope.fixed_shifts.stream()]
    rules = [r async for r in scope.ai_rules.stream({"enabled": True})]
    approved = [r async for r in scope.rosters.stream({"approved": True})]
    clean, rejected = clean_history(approved, {e["employee_id"] for e in employees})
    targets = [r for r in clean if len(earlier_weeks(clean, r["week_start"])) >= 8][-args.weeks:]
    external = read_reference(args.reference_csv, shop.get("role_aliases")) if args.reference_csv else None
    workbook_audit = None
    if args.reference_xlsx:
        external, workbook_audit = read_workbook_reference(args.reference_xlsx, args.reference_week, shop.get("role_aliases"))
    if external and not any(r["week_start"] == args.reference_week for r in targets):
        target = next((r for r in clean if r["week_start"] == args.reference_week), None)
        if target is None or len(earlier_weeks(clean, args.reference_week)) < 8:
            raise ValueError("Reference week has no clean stored target or insufficient earlier history")
        targets.append(target)
    targets.sort(key=lambda r: r["week_start"])
    if not targets:
        raise ValueError("No target weeks with at least eight earlier clean weeks")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"shop": shop.get("name"), "input_hash": digest([shop, employees, holidays, fixed, rules, approved]),
              "quarantined_weeks": rejected, "weeks": [], "external_reference": None,
              "workbook_audit": workbook_audit,
              "data_summary": {"clean_weeks": len(clean), "evaluated_weeks": len(targets),
                               "employee_records": len(employees),
                               "currently_active": sum(e.get("is_active", True) is not False for e in employees),
                               "student_records": sum(e.get("is_student") or e.get("employment_type") == "student" for e in employees),
                               "summer_break_records": sum(bool(e.get("summer_break")) for e in employees),
                               "availability_records": sum(bool(e.get("availability")) for e in employees),
                               "holiday_records": len(holidays), "fixed_shifts": len(fixed), "enabled_rules": len(rules),
                               "seed": None, "context_mode": "current_settings_and_recorded_holidays"}}
    aliases = shop.get("role_aliases")
    for target in targets:
        week = target["week_start"]
        history = earlier_weeks(clean, week)
        model = ChoiceModel().fit(history)
        reference = role_rows(target["shifts"], employees, aliases)
        use_external = external is not None and week == args.reference_week
        stored_reference = reference
        if use_external:
            reference = external
            configured = {canonical_role(e.get("role", "unknown"), aliases) for e in employees}
            report["external_reference"] = {"week": week, "csv_shifts": len(external),
                "stored_shifts": len(stored_reference), "csv_role_counts": dict(Counter(s["role"] for s in external)),
                "stored_role_counts": dict(Counter(s["role"] for s in stored_reference)),
                "roles_without_employee_mapping": sorted({s["role"] for s in external} - configured),
                "csv_vs_stored": role_metrics(external, stored_reference)}
        record = {"week": week, "reference_source": ("attached workbook" if args.reference_xlsx else "attached CSV") if use_external else "stored approved",
                  "training_weeks": len(history), "training_last_week": history[-1]["week_start"],
                  "training_rows": model.metadata["rows"], "training_loss": model.final_loss}
        for label, cls in (("baseline", _RosterBuilder), ("model", ModelBuilder)):
            profile = build_profile(shop, history, {e["employee_id"]: e.get("role", "") for e in employees}, for_week=week)
            builder = cls(deepcopy(shop), sort_employees(deepcopy(employees), shop), deepcopy(holidays),
                          deepcopy(fixed), deepcopy(rules), week, compute_weights(history), profile,
                          history_rosters=deepcopy(history), seed=None,
                          **({"choice_model": model} if label == "model" else {}))
            generated = builder.solve().to_dict()
            rows = role_rows(generated["shifts"], employees, aliases)
            metrics = role_metrics(reference, rows)
            compliance_gaps = compliance.uncovered_hours(
                generated["shifts"], shop=shop, week_start=week,
                history_rosters=history,
            )
            solver_gaps = [
                {"day": day, "hour": hour,
                 "window": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00"}
                for day, _, _, _ in builder._trading_days()
                for hour in builder._open_hours(day)
                if builder.on_duty[day][hour] == 0
            ]
            breaches = compliance.audit(
                generated["shifts"], shop=shop, employees=employees,
                holidays=holidays, week_start=week,
            )
            metrics["approval_reported_uncovered_hours"] = len(compliance_gaps)
            metrics["compliance_uncovered_hours"] = len(compliance_gaps)
            metrics["compliance_uncovered_hour_details"] = compliance_gaps
            metrics["uncovered_hours"] = len(solver_gaps)
            metrics["uncovered_hour_details"] = solver_gaps
            metrics["audit_breaches"] = dict(Counter(b["rule"] for b in breaches))
            metrics["audit_breach_details"] = breaches
            metrics["under_contract"] = generated.get("under_contract", [])
            metrics["under_contract_count"] = len(metrics["under_contract"])
            record[label] = metrics
            if use_external:
                record[label + "_vs_stored"] = role_metrics(stored_reference, rows)
            if label == "model":
                record["ranking_changes"] = builder.ranking_changes
            with (args.output / f"{week}-{label}-roles.csv").open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["day", "role", "start", "end"])
                writer.writeheader(); writer.writerows(rows)
        write_json(args.output / f"{week}-model.json", model.artifact())
        report["weeks"].append(record)
        print(json.dumps({"week": week, "training_weeks": len(history),
                          "baseline_role_hours_distance": record["baseline"]["role_presence_distance_hours"],
                          "model_role_hours_distance": record["model"]["role_presence_distance_hours"]}), flush=True)
    totals = {}
    for label in ("baseline", "model"):
        totals[label] = {key: sum(r[label][key] for r in report["weeks"]) for key in (
            "reference_shifts", "generated_shifts", "day_role_count_distance", "arrival_count_distance",
            "role_arrival_count_distance",
            "exact_role_time_matches", "role_presence_distance_hours", "uncovered_hours", "under_contract_count")}
    report["aggregate"] = totals
    # Keep the user-supplied outlier visible rather than letting it silently
    # dominate all other weeks in a single aggregate number.
    report["aggregate_stored_references_only"] = {label: {
        key: sum(r[label][key] for r in report["weeks"] if r["reference_source"] == "stored approved")
        for key in totals[label]} for label in totals}
    write_json(args.output / "results.json", report)
    render_report(report, args.output)
    return report


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--weeks", type=int, default=8)
    parser.add_argument("--reference-csv", type=Path)
    parser.add_argument("--reference-xlsx", type=Path)
    parser.add_argument("--reference-week")
    args = parser.parse_args()
    if args.weeks < 1 or bool(args.reference_csv or args.reference_xlsx) != bool(args.reference_week) or (args.reference_csv and args.reference_xlsx):
        parser.error("Use positive --weeks and supply both reference options together")
    try:
        await run(args)
    finally:
        db.client.close()


if __name__ == "__main__":
    asyncio.run(main())
