"""A leave entry can be corrected in place.

Until now the only way to fix a mistyped date was to delete the booking and
add it again. That is fine until somebody deletes the wrong row — which is
why the redesigned Holidays page drops the one-click trash icon from every
row and puts Edit there instead, with delete inside the form.

Editing needs an update endpoint, so this covers it: the correction lands,
the entry keeps its id, the same validation applies as on create, and — the
one that is easy to get wrong — saving without changing anything succeeds.
"""
from tests.test_api import EMPLOYEE, auth, register


def _add(client, token, **overrides):
    payload = {
        "date": "2026-09-02", "end_date": None, "label": "Holiday",
        "scope": "shop", "employee_id": None,
    }
    payload.update(overrides)
    created = client.post("/api/holidays", json=payload, headers=auth(token))
    assert created.status_code == 201, created.text
    return created.json()


def test_a_correction_lands_and_keeps_its_id(client):
    token = register(client)
    entry = _add(client, token, label="Bank holdiay")

    updated = client.put(
        f"/api/holidays/{entry['holiday_id']}",
        json={**{k: entry[k] for k in ("date", "end_date", "scope", "employee_id")},
              "label": "Bank holiday"},
        headers=auth(token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["label"] == "Bank holiday"
    assert updated.json()["holiday_id"] == entry["holiday_id"], (
        "an edit corrects a booking, it does not replace it with a new one"
    )

    listed = client.get("/api/holidays", headers=auth(token)).json()
    assert len(listed) == 1, f"editing must not add a second entry: {listed}"
    assert listed[0]["label"] == "Bank holiday"


def test_saving_without_changing_anything_succeeds(client):
    """The commonest way to leave an edit dialog.

    `update_one` reports how many documents it CHANGED, so a no-op save
    modifies nothing — and treating that as "not found" would 404 an entry
    that is plainly there.
    """
    token = register(client)
    entry = _add(client, token)
    same = {k: entry[k] for k in ("date", "end_date", "label", "scope", "employee_id")}

    again = client.put(
        f"/api/holidays/{entry['holiday_id']}", json=same, headers=auth(token),
    )
    assert again.status_code == 200, again.text


def test_the_dates_are_validated_the_same_way_as_on_create(client):
    """An entry that could not be created must not be reachable by editing
    into it."""
    token = register(client)
    entry = _add(client, token)

    refused = client.put(
        f"/api/holidays/{entry['holiday_id']}",
        json={"date": "2026-09-10", "end_date": "2026-09-02", "label": "Backwards",
              "scope": "shop", "employee_id": None},
        headers=auth(token),
    )
    assert refused.status_code == 400, refused.text


def test_employee_leave_still_needs_an_employee(client):
    token = register(client)
    entry = _add(client, token)

    refused = client.put(
        f"/api/holidays/{entry['holiday_id']}",
        json={"date": "2026-09-02", "end_date": None, "label": "Holiday",
              "scope": "sick", "employee_id": None},
        headers=auth(token),
    )
    assert refused.status_code == 400, refused.text


def test_editing_something_that_does_not_exist_is_a_404(client):
    token = register(client)
    missing = client.put(
        "/api/holidays/hol_doesnotexist",
        json={"date": "2026-09-02", "end_date": None, "label": "x",
              "scope": "shop", "employee_id": None},
        headers=auth(token),
    )
    assert missing.status_code == 404, missing.text


def test_one_shop_cannot_edit_another_shops_leave(client):
    """Every query goes through ScopedCollection (§6). This is the check
    that the new endpoint did not become the one place that forgot."""
    mine = register(client)
    entry = _add(client, mine)

    theirs = register(client, email="other@example.com")
    client.post("/api/employees", json=EMPLOYEE, headers=auth(theirs))

    attempt = client.put(
        f"/api/holidays/{entry['holiday_id']}",
        json={"date": "2026-12-25", "end_date": None, "label": "Stolen",
              "scope": "shop", "employee_id": None},
        headers=auth(theirs),
    )
    assert attempt.status_code == 404, attempt.text

    still = client.get("/api/holidays", headers=auth(mine)).json()
    assert still[0]["label"] == "Holiday", (
        f"another shop edited our leave entry: {still}"
    )
