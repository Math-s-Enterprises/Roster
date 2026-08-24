"""Feasibility experiment: can we learn this shop's rostering decisions?

Run:
    cd backend
    pip install scikit-learn openpyxl
    python ml/experiment_baseline.py "path/to/roster.xlsx"

Two questions are asked separately, because they are different problems:

  1. ATTENDANCE  — will this person work on this day?      (binary)
  2. PATTERN     — given they work, which shift do they get? (multi-class)

METHODOLOGY NOTE — why the split is by date, not random
-------------------------------------------------------
Rosters are a time series. A random train/test split would let the model see
week 30 while predicting week 12, and every historical feature would be
computed partly from the future. Accuracy would look far better than it is.
Here the model trains on the earliest weeks and is tested on later ones it
has never seen, and every history feature is built only from weeks strictly
before the row being predicted. The numbers below are therefore honest
estimates of performance on next week's roster.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.roster_import import parse_workbook_rows, read_xlsx  # noqa: E402

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Absence kinds meaning the person could not have been chosen. These rows are
# dropped rather than counted as negatives: "on holiday" says nothing about
# whether the manager would have picked them.
UNAVAILABLE = {"holiday", "unavailable", "sick", "bank_holiday", "bereavement"}

TRAIN_FRACTION = 0.7
TOP_N_PATTERNS = 20


def load_weeks(path: str):
    weeks = [w for w in parse_workbook_rows(read_xlsx(path), 2026) if w.is_usable]
    weeks.sort(key=lambda w: w.week_start)
    return weeks


def infer_roles(weeks) -> Dict[str, str]:
    roles: Dict[str, str] = {}
    for week in weeks:
        for name, role in week.employees.items():
            if role and name not in roles:
                roles[name] = role
    return roles


def build_attendance_dataset(weeks, employee_roles):
    """One row per (week, employee, day) the manager actually had a choice about."""
    role_values = sorted(set(employee_roles.values()))
    day_history: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    shift_totals: collections.Counter = collections.Counter()
    weeks_seen: collections.Counter = collections.Counter()

    features, labels, week_of = [], [], []

    for week_index, week in enumerate(weeks):
        worked = {(s.employee_name, s.day) for s in week.shifts}
        unavailable = {
            (a.employee_name, a.day) for a in week.absences if a.kind in UNAVAILABLE
        }

        for name in week.employees:
            for day_index, day in enumerate(DAYS):
                if (name, day) in unavailable:
                    continue
                total = shift_totals[name]
                features.append([
                    day_index,
                    role_values.index(employee_roles.get(name, role_values[0])),
                    day_history[name][day] / total if total else 0.0,
                    total / max(1, weeks_seen[name]),
                    weeks_seen[name],
                ])
                labels.append(1 if (name, day) in worked else 0)
                week_of.append(week.week_start)

        # History updates happen only after the week has been emitted, so no
        # row is ever described using information from its own week or later.
        for name in week.employees:
            weeks_seen[name] += 1
        for name, day in worked:
            day_history[name][day] += 1
            shift_totals[name] += 1

    return np.array(features, float), np.array(labels), np.array(week_of)


def build_pattern_dataset(weeks, employee_roles):
    """One row per worked shift, predicting which start-end pattern it was."""
    role_values = sorted(set(employee_roles.values()))
    counts = collections.Counter(
        f"{s.start}-{s.end}" for w in weeks for s in w.shifts
    )
    patterns = [p for p, _ in counts.most_common(TOP_N_PATTERNS)]
    pattern_index = {p: i for i, p in enumerate(patterns)}

    pattern_history: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    day_history: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    totals: collections.Counter = collections.Counter()

    features, labels, week_of = [], [], []

    for week in weeks:
        for shift in week.shifts:
            key = f"{shift.start}-{shift.end}"
            if key not in pattern_index:
                continue
            name = shift.employee_name
            total = totals[name]
            history = pattern_history[name]
            usual = history.most_common(1)[0][0] if history else ""

            features.append([
                DAYS.index(shift.day),
                role_values.index(employee_roles.get(name, role_values[0])),
                pattern_index.get(usual, -1),
                history[key] / total if total else 0.0,
                day_history[name][shift.day] / total if total else 0.0,
                total,
            ])
            labels.append(pattern_index[key])
            week_of.append(week.week_start)

        for shift in week.shifts:
            pattern_history[shift.employee_name][f"{shift.start}-{shift.end}"] += 1
            day_history[shift.employee_name][shift.day] += 1
            totals[shift.employee_name] += 1

    return np.array(features, float), np.array(labels), np.array(week_of), patterns


def temporal_split(week_of: np.ndarray, weeks) -> np.ndarray:
    cutoff = weeks[int(len(weeks) * TRAIN_FRACTION)].week_start
    return week_of < cutoff


def main(path: str) -> None:
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import (accuracy_score, f1_score, roc_auc_score,
                                 top_k_accuracy_score)

    weeks = load_weeks(path)
    roles = infer_roles(weeks)
    print(f"Loaded {len(weeks)} weeks, {len(roles)} employees, "
          f"{sum(len(w.shifts) for w in weeks)} shifts")
    print(f"Range: {weeks[0].week_start} to {weeks[-1].week_start}\n")

    # -- 1. attendance ------------------------------------------------------
    X, y, week_of = build_attendance_dataset(weeks, roles)
    train = temporal_split(week_of, weeks)
    print("1) ATTENDANCE — will this person work this day?")
    print(f"   {len(y)} decisions   {y.mean():.1%} positive")
    print(f"   train {train.sum()} / test {(~train).sum()}")

    baseline = DummyClassifier(strategy="most_frequent").fit(X[train], y[train])
    model = HistGradientBoostingClassifier(
        max_iter=250, learning_rate=0.08, max_depth=5, random_state=0
    ).fit(X[train], y[train])

    for label, fitted in (("always-majority", baseline), ("learned model", model)):
        predicted = fitted.predict(X[~train])
        scores = fitted.predict_proba(X[~train])[:, 1]
        print(f"   {label:16} accuracy={accuracy_score(y[~train], predicted):.3f}  "
              f"f1={f1_score(y[~train], predicted):.3f}  "
              f"auc={roc_auc_score(y[~train], scores):.3f}")

    # -- 2. pattern ---------------------------------------------------------
    Xp, yp, week_of_p, patterns = build_pattern_dataset(weeks, roles)
    train_p = temporal_split(week_of_p, weeks)
    print(f"\n2) SHIFT PATTERN — which of the top {len(patterns)} shifts?")
    print(f"   train {train_p.sum()} / test {(~train_p).sum()}")

    usual = Xp[~train_p][:, 2].astype(int)
    print(f"   {'their usual shift':16} top-1={accuracy_score(yp[~train_p], usual):.3f}")

    pattern_model = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.08, max_depth=6, random_state=0
    ).fit(Xp[train_p], yp[train_p])
    proba = pattern_model.predict_proba(Xp[~train_p])
    labels = np.arange(len(patterns))
    print(f"   {'learned model':16} "
          f"top-1={accuracy_score(yp[~train_p], pattern_model.predict(Xp[~train_p])):.3f}  "
          f"top-3={top_k_accuracy_score(yp[~train_p], proba, k=3, labels=labels):.3f}  "
          f"top-5={top_k_accuracy_score(yp[~train_p], proba, k=5, labels=labels):.3f}")

    print("\nInterpretation: top-3 is the number that matters for the product. "
          "The solver needs a good shortlist to choose from, not a single "
          "guaranteed answer — a human approves the result either way.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python ml/experiment_baseline.py <roster.xlsx>")
    main(sys.argv[1])
