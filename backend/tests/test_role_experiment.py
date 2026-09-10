import pytest

np = pytest.importorskip("numpy")

from ml.role_experiment import (ChoiceModel, ModelBuilder, canonical_role, clean_history,
                                earlier_weeks, role_metrics, role_rows)
from app.services.scheduler import _RosterBuilder


def shift(employee="a", day="mon", start="09:00", end="17:00"):
    return dict(employee_id=employee, day=day, start=start, end=end)


def test_name_changes_do_not_change_role_scores_and_duplicates_count():
    employees = [{"employee_id": "a", "role": "Cashier"}, {"employee_id": "b", "role": "Cashier"}]
    actual = role_rows([shift(), shift("b")], employees)
    proposed = role_rows([shift("b"), shift()], employees)
    result = role_metrics(actual, proposed)
    assert result["exact_role_time_matches"] == 2
    assert result["day_role_count_distance"] == 0
    assert result["role_presence_distance_hours"] == 0
    assert role_metrics(actual, proposed[:1])["day_role_count_distance"] == 1


def test_half_hour_edges_and_sunday_overnight_are_measured_in_real_minutes():
    ref = [{"role": "cashier", **shift(day="sun", start="23:30", end="07:00")}]
    generated = [{"role": "cashier", **shift(day="sun", start="23:00", end="07:00")}]
    scores = role_metrics(ref, generated)
    assert scores["role_presence_distance_hours"] == 0.5
    assert scores["by_role"][0]["reference_span_hours"] == 7.5
    assert scores["over_reference_role_hours"] == 0.5


def test_role_changes_count_even_when_total_headcount_matches():
    ref = [{"role": "manager", **shift()}]
    generated = [{"role": "cashier", **shift("b")}]
    scores = role_metrics(ref, generated)
    assert scores["day_role_count_distance"] == 2
    assert scores["role_presence_distance_hours"] == 16
    assert scores["exact_role_time_matches"] == 0
    assert scores["day_role_differences"] == [
        {"day": "mon", "role": "cashier", "reference": 0,
         "generated": 1, "difference": 1},
        {"day": "mon", "role": "manager", "reference": 1,
         "generated": 0, "difference": -1},
    ]
    assert scores["arrival_differences"][0]["window"] == "09:00-10:00"
    assert {row["difference"] for row in scores["arrival_differences"]} == {-1, 1}
    assert scores["arrival_count_distance"] == 0
    assert scores["day_arrival_differences"] == []


def test_model_fits_only_earlier_weeks_and_generalises_repeated_day_start_pattern():
    weeks = [{"week_start": "2026-07-06", "shifts": [shift(), shift("b", day="tue")]},
             {"week_start": "2026-07-13", "shifts": [shift(), shift("b", day="tue")]},
             {"week_start": "2026-07-20", "shifts": [shift("future")]},
             {"week_start": "2026-07-27", "shifts": [shift("later")]}]
    model = ChoiceModel().fit(earlier_weeks(weeks, "2026-07-20"))
    assert model.classes == ["a", "b"]
    assert model.final_loss < model.initial_loss / 2
    assert model.scores("mon", "09:00")["a"] > model.scores("mon", "09:00")["b"]
    assert model.scores("tue", "09:00")["b"] > model.scores("tue", "09:00")["a"]


def test_model_preserves_owners_and_falls_back_for_unknown_staff(monkeypatch):
    monkeypatch.setattr(_RosterBuilder, "_history_rank", lambda *a: {"a": 0, "b": 2, "c": 1})
    builder = object.__new__(ModelBuilder)
    class Scores:
        def scores(self, day, start):
            return {"a": -10, "b": 20, "c": 1}
    builder.choice_model = Scores()
    builder.ranking_changes = 0
    ranks = builder._history_rank([{"employee_id": e} for e in ("a", "b", "c")], "mon", "09:00", "17:00")
    assert ranks == {"a": 0, "b": 1, "c": 2}
    ranks = builder._history_rank([{"employee_id": "new"}], "mon", "09:00", "17:00")
    assert ranks == {"a": 0, "b": 2, "c": 1}


def test_ambiguous_weeks_are_excluded_without_silently_lowering_demand():
    duplicate = {"approved": True, "week_start": "2026-07-06", "shifts": [shift()]}
    broken = {"approved": True, "week_start": "2026-07-13", "shifts": [shift(), shift()]}
    clean, rejected = clean_history([duplicate, duplicate.copy(), broken], {"a"})
    assert clean == []
    assert len(rejected) == 3
    assert canonical_role("SUP", {"sup": "Supervisor"}) == "supervisor"
    assert canonical_role("Unknown role") == "unknown role"


def test_workbook_reference_requires_one_complete_week(monkeypatch, tmp_path):
    from app.services import roster_import
    from ml.run_role_backtest import read_workbook_reference
    parsed = roster_import.ParsedWeek("July", "2026-07-27", None)
    parsed.shifts = [roster_import.ParsedShift("Private name", "Supervisor", "mon", "09:00", "17:00", 8)]
    monkeypatch.setattr(roster_import, "read_xlsx", lambda _: [])
    monkeypatch.setattr(roster_import, "parse_workbook_rows", lambda _: [parsed])
    rows, audit = read_workbook_reference(tmp_path / "source.xlsx", "2026-07-27", {})
    assert rows == [{"day": "mon", "role": "supervisor", "start": "09:00", "end": "17:00"}]
    assert audit["target_unparsed_cells"] == 0
    parsed.unparsed_cells = [{"cell": "ambiguous"}]
    with pytest.raises(ValueError, match="unparsed"):
        read_workbook_reference(tmp_path / "source.xlsx", "2026-07-27", {})
    parsed.unparsed_cells = []
    monkeypatch.setattr(roster_import, "parse_workbook_rows", lambda _: [parsed, parsed])
    with pytest.raises(ValueError, match="duplicated"):
        read_workbook_reference(tmp_path / "source.xlsx", "2026-07-27", {})
