import asyncio

import pytest
from mongomock_motor import AsyncMongoMockClient

from app import db
from app.services.compliance import audit, blocking
from app.services.scheduler import violates_minor_curfew
from ml.migrate_employee_age_groups import migrate
from tests.test_api import EMPLOYEE, auth, register


def test_existing_employee_ages_are_migrated_without_reclassifying_import_defaults():
    async def run():
        collection = AsyncMongoMockClient().test.employees
        await collection.insert_many([
            {"_id": "child", "shop_id": "one", "age": 15},
            {"_id": "sixteen", "shop_id": "one", "age": 16},
            {"_id": "adult", "shop_id": "two", "age": 18},
            {"_id": "imported", "shop_id": "two", "age": 25, "imported": True},
            {"_id": "confirmed", "shop_id": "two", "age": 25, "imported": True, "details_confirmed": True},
            {"_id": "changed", "shop_id": "one", "age": 15, "age_group": "18_plus"},
        ])
        expected = {"under_16": 1, "16_17": 1, "18_plus": 3, "unconfirmed": 1}
        assert await migrate(collection) == expected
        assert await collection.count_documents({"age": {"$exists": True}}) == 6
        assert await migrate(collection, commit=True) == expected
        assert await migrate(collection, commit=True) == {}
        rows = await collection.find({}).to_list(None)
        assert all("age" not in row for row in rows)
        assert {row["_id"]: row["age_group"] for row in rows} == {
            "child": "under_16", "sixteen": "16_17", "adult": "18_plus",
            "imported": None, "confirmed": "18_plus", "changed": "18_plus",
        }

    asyncio.run(run())


def test_legacy_ages_are_hidden_and_removed_when_employee_is_saved(client):
    headers = auth(register(client))
    shop = client.get("/api/shop", headers=headers).json()
    employee = {**EMPLOYEE, "employee_id": "legacy", "shop_id": shop["shop_id"]}
    employee.pop("age_group")
    asyncio.run(db.employees.insert_one({**employee, "age": 17}))
    listed = client.get("/api/employees", headers=headers).json()[0]
    assert listed["age_group"] == "16_17"
    assert "age" not in listed
    updated = client.put("/api/employees/legacy", headers=headers, json={
        **listed, "age_group": "18_plus",
    })
    assert updated.status_code == 200, updated.text
    stored = asyncio.run(db.employees.find_one({"employee_id": "legacy"}))
    assert stored["age_group"] == "18_plus"
    assert "age" not in stored


def test_legacy_exact_ages_in_decision_snapshots_stay_out_of_roster_responses(client):
    headers = auth(register(client))
    shop = client.get("/api/shop", headers=headers).json()
    snapshot = {"employees": [{"employee_id": "legacy", "age": 17}]}
    asyncio.run(db.rosters.insert_one({
        "roster_id": "legacy", "shop_id": shop["shop_id"], "week_start": "2026-11-16",
        "shifts": [], "training_context": snapshot, "training_approval": {"context": snapshot},
    }))
    response = client.get("/api/rosters/legacy", headers=headers)
    assert response.status_code == 200, response.text
    roster = response.json()
    assert roster["training_context"]["employees"] == [{"employee_id": "legacy"}]
    assert roster["training_approval"]["context"]["employees"] == [{"employee_id": "legacy"}]


@pytest.mark.parametrize(("group", "restricted"), [
    ("under_16", True), (None, True), ("16_17", False), ("18_plus", False),
])
def test_generation_and_approval_use_the_same_curfew_for_all_groups(group, restricted):
    employee = {**EMPLOYEE, "employee_id": "e", "age_group": group}
    shift = {"employee_id": "e", "day": "mon", "start": "18:00", "end": "02:00"}
    assert violates_minor_curfew(employee, shift["start"], shift["end"]) == restricted
    assert not violates_minor_curfew(employee, "08:00", "19:00")
    breaches = audit([shift], shop={}, employees=[employee], week_start="2026-11-16")
    curfew = [item for item in blocking(breaches) if item["rule"] == "minor_curfew"]
    assert bool(curfew) == restricted
    if group is None:
        assert "confirm it in Employees" in curfew[0]["message"]
