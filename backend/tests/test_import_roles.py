"""Import review distinguishes a job title from a roster-group membership."""
import pytest

from tests.test_api import auth, register


def upload(client, headers, role="", name="Alex"):
    csv = ("Role,Name,Mon,Tue,Wed,Thu,Fri,Sat,Sun\n"
           f"{role},{name},09:00-17:00,,,,,,\n")
    response = client.post("/api/imports", headers=headers,
        files={"file": ("roles.csv", csv.encode(), "text/csv")},
        data={"week_start": "2026-10-26",
              "department": headers.get("X-Roster-Group", "Shop Floor")})
    assert response.status_code == 201, response.text
    return response.json()


def setup(client):
    headers = auth(register(client))
    response = client.put("/api/shop", headers=headers, json={
        "role_hierarchy": ["Customer Service", "Shop Assistant"],
        "role_aliases": {"Cust service": "Customer Service"},
    })
    assert response.status_code == 200, response.text
    return headers


def test_missing_file_role_is_not_invented_in_preview_or_created_employee(client):
    headers = setup(client)
    preview = upload(client, headers)
    assert preview["people"][0]["role"] == ""
    assert preview["people"][0]["role_in_file"] is None
    assert preview["role_options"] == ["Customer Service", "Shop Assistant"]
    result = client.post(f"/api/imports/{preview['import_id']}/commit", headers=headers,
                         json={"employee_map": {"Alex": ""}})
    assert result.status_code == 200, result.text
    person = client.get("/api/employees", headers=headers).json()[0]
    assert person["role"] == ""
    assert person["department_roles"] == {"Shop Floor": ""}


@pytest.mark.parametrize("file_role,selected", [
    ("Cust service", "Customer Service"),
    ("Customer counter", "Shop Assistant"),
    ("", "Customer Service"),
    ("Customer counter", ""),
])
def test_reviewed_role_is_used_when_creating_the_employee(client, file_role, selected):
    headers = setup(client)
    preview = upload(client, headers, file_role)
    if file_role == "Cust service":
        assert preview["people"][0]["role"] == "Customer Service"
    result = client.post(f"/api/imports/{preview['import_id']}/commit", headers=headers,
        json={"employee_map": {"Alex": ""}, "role_map": {"Alex": selected}})
    assert result.status_code == 200, result.text
    person = client.get("/api/employees", headers=headers).json()[0]
    assert person["role"] == selected
    assert person["department_roles"]["Shop Floor"] == selected


def test_an_unconfigured_reviewed_role_is_refused_before_any_employee_or_history_write(client):
    headers = setup(client)
    preview = upload(client, headers, "Cust service")
    result = client.post(f"/api/imports/{preview['import_id']}/commit", headers=headers,
        json={"employee_map": {"Alex": ""}, "role_map": {"Alex": "Not configured"}})
    assert result.status_code == 422
    assert "Shop Settings" in result.text
    assert client.get("/api/employees", headers=headers).json() == []
    assert client.get("/api/imports/history", headers=headers).json() == []
    # Refusing a review must leave the upload available to correct and retry.
    retry = client.post(f"/api/imports/{preview['import_id']}/commit", headers=headers,
        json={"employee_map": {"Alex": ""}, "role_map": {"Alex": "Customer Service"}})
    assert retry.status_code == 200, retry.text


def test_existing_employee_role_is_shown_and_preserved_when_file_disagrees(client):
    headers = setup(client)
    employee = client.post("/api/employees", headers=headers, json={
        "name": "Alex", "role": "Customer Service", "age": 25,
        "hourly_rate": 13, "max_weekly_hours": 40,
    }).json()
    preview = upload(client, headers, "Shop Assistant")
    assert preview["people"][0]["role"] == "Customer Service"
    assert preview["people"][0]["role_in_file"] == "Shop Assistant"
    result = client.post(f"/api/imports/{preview['import_id']}/commit", headers=headers,
        json={"employee_map": {"Alex": employee["employee_id"]}})
    assert result.status_code == 200, result.text
    assert client.get("/api/employees", headers=headers).json()[0]["role"] == "Customer Service"


def test_mapping_cannot_attach_another_shops_employee_to_imported_shifts(client):
    headers = setup(client)
    other = auth(register(client, email="other@example.com"))
    employee = client.post("/api/employees", headers=other, json={
        "name": "Alex", "role": "Customer Service", "age": 25,
        "hourly_rate": 13, "max_weekly_hours": 40,
    }).json()
    preview = upload(client, headers)
    result = client.post(f"/api/imports/{preview['import_id']}/commit", headers=headers,
        json={"employee_map": {"Alex": employee["employee_id"]}})
    assert result.status_code == 422
    assert client.get("/api/employees", headers=headers).json() == []
    assert client.get("/api/imports/history", headers=headers).json() == []


def test_reviewed_group_role_does_not_change_employee_role_in_another_group(client):
    headers = setup(client)
    client.put("/api/shop", headers=headers, json={"departments": ["Shop Floor", "Deli"]})
    employee = client.post("/api/employees", headers=headers, json={
        "name": "Alex", "role": "Customer Service", "age": 25,
        "hourly_rate": 13, "max_weekly_hours": 40,
    }).json()
    deli = {**headers, "X-Roster-Group": "Deli"}
    client.put("/api/shop", headers=deli, json={"role_hierarchy": ["Deli Assistant"]})
    preview = upload(client, deli, "Counter")
    assert preview["role_options"] == ["Deli Assistant"]
    result = client.post(f"/api/imports/{preview['import_id']}/commit", headers=deli,
        json={"employee_map": {"Alex": employee["employee_id"]},
              "role_map": {"Alex": "Deli Assistant"}})
    assert result.status_code == 200, result.text
    assert client.get("/api/employees", headers=deli).json()[0]["role"] == "Deli Assistant"
    assert client.get("/api/employees", headers=headers).json()[0]["role"] == "Customer Service"
