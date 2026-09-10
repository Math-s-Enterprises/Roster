"""Offline role-based comparison and fitted employee-choice experiment.

No application routes import this module. Model scores never bypass eligibility,
ownership or contract priority. Historical choices are observations, not proof
that an unchosen person was unsuitable.
"""
from collections import Counter
from copy import deepcopy
from datetime import date
import math
import re

import numpy as np

from app.services.scheduler import DAYS, _RosterBuilder, to_minutes


def working(shifts):
    return [s for s in shifts if s.get("start") and s.get("end") and not any(
        s.get(k) for k in ("sick", "paid_holiday", "unpaid_holiday", "temp_override"))]


def clean_history(rosters, employee_ids):
    """Quarantine whole ambiguous weeks so deleting a row cannot lower demand."""
    approved = [r for r in rosters if r.get("approved") and not r.get("exclude_from_ai")]
    counts = Counter(r.get("week_start") for r in approved)
    clean, rejected = [], []
    for r in approved:
        reasons = []
        week = r.get("week_start")
        try:
            if date.fromisoformat(week).weekday() != 0:
                reasons.append("not_monday")
        except (ValueError, TypeError):
            reasons.append("invalid_week")
        if counts[week] > 1:
            reasons.append("duplicate_week")
        if r.get("force_approved"):
            reasons.append("force_approved")
        rows = (r.get("training_approval") or {}).get("shifts", r.get("shifts", []))
        keys = Counter((s.get("employee_id"), s.get("day")) for s in working(rows))
        if any(n > 1 for n in keys.values()):
            reasons.append("duplicate_employee_day")
        for s in working(rows):
            if s.get("employee_id") not in employee_ids or s.get("day") not in DAYS:
                reasons.append("unknown_employee_or_day")
            if any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(s.get(k, ""))) for k in ("start", "end")):
                reasons.append("invalid_time")
        if reasons:
            rejected.append({"week": week, "reasons": sorted(set(reasons))})
        else:
            copy = deepcopy(r)
            copy["shifts"] = deepcopy(rows)
            clean.append(copy)
    return sorted(clean, key=lambda r: r["week_start"]), rejected


def earlier_weeks(rosters, week):
    return [r for r in rosters if r["week_start"] < week]


def tokens(day, start):
    hour = to_minutes(start) // 60
    return ("bias", f"day:{day}", f"hour:{hour}", f"start:{start}", f"day_hour:{day}:{hour}")


class ChoiceModel:
    """Regularised multinomial logistic model fitted with full-batch gradients.

    Predicts the observed worker conditional on day/start. Multiple workers
    sharing a start contribute multiple observations; outputs are not calibrated
    suitability probabilities or availability predictions. No target-week data
    enters the feature vocabulary, parameters or employee classes.
    """
    def fit(self, history, steps=350, learning_rate=0.5, regularization=0.01):
        rows = [s for r in history for s in working(r.get("shifts", []))]
        if not rows:
            raise ValueError("No training shifts")
        self.classes = sorted({s["employee_id"] for s in rows})
        self.features = sorted({t for s in rows for t in tokens(s["day"], s["start"])})
        self.feature_index = {f: i for i, f in enumerate(self.features)}
        indices = {e: i for i, e in enumerate(self.classes)}
        x = np.zeros((len(rows), len(self.features)))
        for i, s in enumerate(rows):
            for t in tokens(s["day"], s["start"]):
                x[i, self.feature_index[t]] = 1
        y = np.array([indices[s["employee_id"]] for s in rows])
        self.weights = np.zeros((len(self.features), len(self.classes)))
        self.initial_loss = math.log(len(self.classes))
        for _ in range(steps):
            z = x @ self.weights
            z -= z.max(axis=1, keepdims=True)
            p = np.exp(z)
            p /= p.sum(axis=1, keepdims=True)
            p[np.arange(len(y)), y] -= 1
            self.weights -= learning_rate * (x.T @ p / len(y) + regularization * self.weights)
        z = x @ self.weights
        z -= z.max(axis=1, keepdims=True)
        log_probs = z - np.log(np.exp(z).sum(axis=1, keepdims=True))
        self.final_loss = float(-log_probs[np.arange(len(y)), y].mean())
        self.metadata = {"training_weeks": [r["week_start"] for r in history],
                         "rows": len(rows), "steps": steps, "regularization": regularization,
                         "learning_rate": learning_rate, "initial_loss": self.initial_loss,
                         "final_loss": self.final_loss}
        self.cache = {}
        return self

    def scores(self, day, start):
        key = (day, start)
        if key not in self.cache:
            indices = [self.feature_index[t] for t in tokens(day, start) if t in self.feature_index]
            z = self.weights[indices].sum(axis=0)
            self.cache[key] = dict(zip(self.classes, map(float, z)))
        return self.cache[key]

    def artifact(self):
        return {"type": "multinomial_logistic_day_start_v1", "classes": self.classes,
                "features": self.features, "weights": self.weights.tolist(), **self.metadata}


class ModelBuilder(_RosterBuilder):
    def __init__(self, *args, choice_model, **kwargs):
        self.choice_model = choice_model
        self.ranking_changes = 0
        super().__init__(*args, **kwargs)

    def _history_rank(self, eligible, day, start, end):
        original = super()._history_rank(eligible, day, start, end)
        scores = self.choice_model.scores(day, start)
        # Owners retain rank zero. Unknown/new staff retain the existing
        # behaviour by falling back for this comparison, rather than inventing
        # a learned preference for or against them.
        if any(e["employee_id"] not in scores for e in eligible):
            return original
        owners = {e for e, rank in original.items() if rank == 0}
        rest = [e["employee_id"] for e in eligible if e["employee_id"] not in owners]
        ordered = sorted(rest, key=lambda e: (-scores[e], original.get(e, 999), e))
        baseline = sorted(rest, key=lambda e: (original.get(e, 999), e))
        self.ranking_changes += ordered != baseline
        return {**{e: 0 for e in owners}, **{e: i + 1 for i, e in enumerate(ordered)}}


def canonical_role(role, aliases=None):
    mapped = {k.strip().casefold(): v for k, v in (aliases or {}).items()}
    return mapped.get(str(role).strip().casefold(), str(role)).strip().casefold()


def role_rows(shifts, employees, aliases=None):
    roles = {e["employee_id"]: e.get("role", "unknown") for e in employees}
    return [{"day": s["day"], "start": s["start"], "end": s["end"],
             "role": canonical_role(s.get("role") or roles.get(s.get("employee_id"), "unknown"), aliases)}
            for s in working(shifts)]


def role_metrics(reference, generated):
    """Exact minute intervals, with overnight time attached to its start day.

    The eighth day retains Sunday carry-out. No employee names/IDs are scored.
    Counter intersection retains multiple identical shifts.
    """
    def quantities(rows):
        counts, arrivals, all_arrivals, shapes = Counter(), Counter(), Counter(), Counter()
        presence = {}
        for s in rows:
            role, day = s["role"], s["day"]
            start, end = to_minutes(s["start"]), to_minutes(s["end"])
            if end <= start:
                end += 1440
            base = DAYS.index(day) * 1440
            presence.setdefault(role, np.zeros(8 * 1440, dtype=int))[base + start:base + end] += 1
            counts[day, role] += 1
            arrivals[day, role, start // 60] += 1
            all_arrivals[day, start // 60] += 1
            shapes[day, role, s["start"], s["end"]] += 1
        return counts, arrivals, all_arrivals, shapes, presence
    rc, ra, raa, rs, rp = quantities(reference)
    gc, ga, gaa, gs, gp = quantities(generated)
    distance = lambda a, b: sum(abs(a[k] - b[k]) for k in a.keys() | b.keys())
    day_order = {day: index for index, day in enumerate(DAYS)}

    day_role_counts = [
        {
            "day": day,
            "role": role,
            "reference": rc.get((day, role), 0),
            "generated": gc.get((day, role), 0),
            "difference": gc.get((day, role), 0) - rc.get((day, role), 0),
        }
        for day, role in sorted(
            rc.keys() | gc.keys(), key=lambda item: (day_order[item[0]], item[1])
        )
    ]
    arrival_counts = [
        {
            "day": day,
            "role": role,
            "hour": hour,
            "window": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
            "reference": ra.get((day, role, hour), 0),
            "generated": ga.get((day, role, hour), 0),
            "difference": ga.get((day, role, hour), 0)
            - ra.get((day, role, hour), 0),
        }
        for day, role, hour in sorted(
            ra.keys() | ga.keys(),
            key=lambda item: (day_order[item[0]], item[2], item[1]),
        )
    ]
    day_arrival_counts = [
        {
            "day": day,
            "hour": hour,
            "window": f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
            "reference": raa.get((day, hour), 0),
            "generated": gaa.get((day, hour), 0),
            "difference": gaa.get((day, hour), 0) - raa.get((day, hour), 0),
        }
        for day, hour in sorted(
            raa.keys() | gaa.keys(), key=lambda item: (day_order[item[0]], item[1])
        )
    ]
    shift_shape_counts = [
        {
            "day": day,
            "role": role,
            "start": start,
            "end": end,
            "reference": rs.get((day, role, start, end), 0),
            "generated": gs.get((day, role, start, end), 0),
            "difference": gs.get((day, role, start, end), 0)
            - rs.get((day, role, start, end), 0),
        }
        for day, role, start, end in sorted(
            rs.keys() | gs.keys(),
            key=lambda item: (day_order[item[0]], item[2], item[3], item[1]),
        )
    ]
    missing = extra = 0
    by_role = []
    for role in sorted(rp.keys() | gp.keys()):
        actual = rp.get(role, np.zeros(8 * 1440))
        proposed = gp.get(role, np.zeros(8 * 1440))
        under = float(np.maximum(actual - proposed, 0).sum() / 60)
        over = float(np.maximum(proposed - actual, 0).sum() / 60)
        missing += under; extra += over
        by_role.append({"role": role, "reference_shifts": sum(v for (d, r), v in rc.items() if r == role),
                        "generated_shifts": sum(v for (d, r), v in gc.items() if r == role),
                        "reference_span_hours": float(actual.sum() / 60),
                        "generated_span_hours": float(proposed.sum() / 60),
                        "under_reference_role_hours": under, "over_reference_role_hours": over})
    return {"reference_shifts": len(reference), "generated_shifts": len(generated),
            "day_role_count_distance": distance(rc, gc),
            "arrival_count_distance": distance(raa, gaa),
            "role_arrival_count_distance": distance(ra, ga),
            "exact_role_time_matches": sum((rs & gs).values()),
            "under_reference_role_hours": missing, "over_reference_role_hours": extra,
            "role_presence_distance_hours": missing + extra, "by_role": by_role,
            "day_role_counts": day_role_counts,
            "day_role_differences": [row for row in day_role_counts if row["difference"]],
            "arrival_counts": arrival_counts,
            "arrival_differences": [row for row in arrival_counts if row["difference"]],
            "day_arrival_counts": day_arrival_counts,
            "day_arrival_differences": [row for row in day_arrival_counts if row["difference"]],
            "shift_shape_counts": shift_shape_counts,
            "shift_shape_differences": [row for row in shift_shape_counts if row["difference"]]}
