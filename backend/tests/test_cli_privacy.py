"""Diagnostic output is shareable without copying staff identities into logs."""
import asyncio
import importlib
from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import db


@pytest.fixture
def records(monkeypatch):
    database = AsyncMongoMockClient()["cli_test"]
    for collection in ("users", "shops", "employees", "fixed_shifts", "holidays", "ai_rules", "rosters"):
        monkeypatch.setattr(db, collection, database[collection])

    async def seed():
        await db.users.insert_one({"user_id": "owner", "email": "private-owner@example.com"})
        await db.shops.insert_one({"shop_id": "shop", "owner_id": "owner", "name": "Private Shop",
                                  "hours": [{"day": "mon", "open": "06:00", "close": "23:00"}]})
        await db.employees.insert_many([
            {"employee_id": "a", "shop_id": "shop", "name": "Private Alice", "role": "Staff",
             "max_weekly_hours": 40, "preferred_days_off": ["mon"]},
            {"employee_id": "b", "shop_id": "shop", "name": "Private Bob", "role": "Staff",
             "max_weekly_hours": 40},
        ])
    asyncio.run(seed())
    return database


@pytest.mark.parametrize("script", ["set_emails", "diagnose", "who_owns"])
def test_scripts_compile_without_running_or_connecting(script):
    path = Path(__file__).parents[1] / "ml" / f"{script}.py"
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


@pytest.mark.parametrize("commit", [False, True])
def test_email_import_reports_csv_lines_not_names_or_addresses(records, tmp_path, capsys, commit):
    script = importlib.import_module("ml.set_emails")
    csv = tmp_path / "private-owner@example.com.csv"
    csv.write_text("name,email\nPrivate Alice,private-alice@example.com\n"
                   "Private Bob,private-alice@example.com\nPrivate,private-ambiguous@example.com\n"
                   "Private Missing,not-an-email\n", encoding="utf-8")
    asyncio.run(script.run("private-owner@example.com", str(csv), commit, False))
    output = capsys.readouterr().out
    assert "Private" not in output and "private-" not in output
    assert "line 2" in output and "line 3" in output and "line 4" in output and "line 5" in output
    assert "matches 2" in output and "already used" in output
    alice = asyncio.run(db.employees.find_one({"employee_id": "a"}))
    assert alice["name"] == "Private Alice"
    assert alice.get("email") == ("private-alice@example.com" if commit else None)
    assert not asyncio.run(db.employees.find_one({"employee_id": "b"})).get("email")


def test_email_import_preserves_existing_addresses_and_requires_replace(records, tmp_path, capsys):
    script = importlib.import_module("ml.set_emails")
    asyncio.run(db.employees.update_one({"employee_id": "a"}, {"$set": {"email": "private-old@example.com"}}))
    csv = tmp_path / "staff.csv"
    csv.write_text("name,email\nPrivate Alice,private-new@example.com\n", encoding="utf-8")
    asyncio.run(script.run("private-owner@example.com", str(csv), True, False))
    assert asyncio.run(db.employees.find_one({"employee_id": "a"}))["email"] == "private-old@example.com"
    asyncio.run(script.run("private-owner@example.com", str(csv), True, True))
    assert asyncio.run(db.employees.find_one({"employee_id": "a"}))["email"] == "private-new@example.com"
    output = capsys.readouterr().out
    assert "Private" not in output and "private-" not in output


def test_diagnosis_uses_consistent_labels_in_all_staff_tables(records, capsys):
    script = importlib.import_module("ml.diagnose")

    async def seed():
        await db.fixed_shifts.insert_many([
            {"shop_id": "shop", "employee_id": "a", "days": ["tue"], "start": "06:00", "end": "12:00"},
            {"shop_id": "shop", "employee_id": "b", "days": ["mon"], "start": "06:00", "end": "12:00"},
        ])
        await db.holidays.insert_one({"shop_id": "shop", "employee_id": "a", "scope": "employee",
                                     "date": "2026-10-06", "label": "Private Alice private-note@example.com"})
        shifts = [{"employee_id": "a", "day": day, "start": "06:00", "end": "12:00"}
                  for day in ("mon", "wed", "thu", "fri", "sat", "sun")]
        await db.rosters.insert_one({"shop_id": "shop", "week_start": "2026-10-05", "shifts": shifts,
                                     "under_contract": [{"employee_id": "b", "name": "Private Bob",
                                                         "rostered_hours": 0, "contracted_hours": 40}],
                                     "critical_issues": ["Private Alice private-note@example.com"], "version": 1})
        for week in ("2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28"):
            await db.rosters.insert_one({"shop_id": "shop", "week_start": week, "shifts": shifts, "approved": True})
    asyncio.run(seed())
    asyncio.run(script.run("private-owner@example.com", "2026-10-05"))
    output = capsys.readouterr().out
    assert "Private" not in output and "private-" not in output
    assert "Employee 1" in output and "Employee 2" in output
    assert "ok   Employee 1" in output and "FAIL Employee 2" in output
    assert "WARN Employee 1" in output and "below contracted hours: 1" in output
    assert "critical issues: 1" in output and "working more than 5 days: 1" in output
    assert "sunday 06:00 is covered by: Employee 1" in output
    assert asyncio.run(db.employees.find_one({"employee_id": "a"}))["name"] == "Private Alice"


def test_ownership_keeps_the_requested_analysis_without_printing_identity(records, capsys):
    script = importlib.import_module("ml.who_owns")
    asyncio.run(db.rosters.insert_one({"shop_id": "shop", "week_start": "2026-10-05", "approved": True,
                                      "shifts": [{"employee_id": "a", "day": "mon", "start": "06:00", "end": "12:00"}]}))
    asyncio.run(script.run("private-owner@example.com", "Private Alice", "mon"))
    output = capsys.readouterr().out
    assert "Private" not in output and "private-" not in output
    assert "1 approved weeks" in output and "mon 06:00" in output


def test_diagnosis_labels_roles_and_only_emits_canonical_weekdays(records, capsys):
    """Raw database strings must not escape through roles or preference warnings."""
    script = importlib.import_module("ml.diagnose")
    private_role = "private-role@example.com"
    private_day = "private-day@example.com"
    preferences = ["wed", "mon", private_day]

    async def seed():
        await db.employees.update_many({}, {"$set": {"role": private_role}})
        await db.employees.update_one({"employee_id": "a"}, {"$set": {"preferred_days_off": preferences}})
        await db.employees.insert_one({"employee_id": "c", "shop_id": "shop", "name": "Private Carol",
                                       "role": "private-other-role@example.com", "max_weekly_hours": 40})
        await db.rosters.insert_one({"shop_id": "shop", "week_start": "2026-10-05", "version": 1,
                                     "shifts": [
                                         {"employee_id": "a", "day": "mon", "start": "06:00", "end": "12:00"},
                                         {"employee_id": "a", "day": "wed", "start": "06:00", "end": "12:00"},
                                         # Legacy/corrupt records can bypass API validation.
                                         {"employee_id": "a", "day": private_day},
                                     ]})
    asyncio.run(seed())
    asyncio.run(script.run("private-owner@example.com", "2026-10-05"))
    output = capsys.readouterr().out
    assert "private-" not in output and "Private" not in output
    assert output.count("Role 1") == 2 and output.count("Role 2") == 1
    assert "mon,wed" in output
    assert "WARN Employee 1 worked mon" in output and "WARN Employee 1 worked wed" in output
    employee = asyncio.run(db.employees.find_one({"employee_id": "a"}))
    assert employee["role"] == private_role and employee["preferred_days_off"] == preferences


@pytest.mark.parametrize("who", ["Private Missing", "Private"])
def test_ownership_lookup_errors_do_not_list_staff_or_echo_input(records, capsys, who):
    script = importlib.import_module("ml.who_owns")
    with pytest.raises(SystemExit) as error:
        asyncio.run(script.run("private-owner@example.com", who, None))
    output = str(error.value) + capsys.readouterr().out
    assert "Private" not in output and "private-" not in output


@pytest.mark.parametrize("script,args", [("set_emails", ["unused.csv", False, False]),
                                         ("diagnose", ["2026-10-05"]), ("who_owns", ["Private Alice", None])])
def test_missing_account_errors_do_not_echo_the_email(records, script, args):
    module = importlib.import_module(f"ml.{script}")
    with pytest.raises(SystemExit) as error:
        asyncio.run(module.run("missing-private@example.com", *args))
    assert "missing-private" not in str(error.value)
