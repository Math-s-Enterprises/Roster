"""Deleting your own account closes it at once and erases it thirty days later.

The tests are written around the ways this could go wrong: leaving data behind, taking
somebody else's, being triggered by the wrong person, erasing too soon (before the thirty days)
or never, deleting data while a subscription keeps charging, a closed account still being
usable, a person who changed their mind not being able to come back, and being left half-done
by a failure.
"""
import asyncio
import contextlib
import json
import types
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_api import EMPLOYEE, auth, register   # sets the test environment first

from app import db
from app.services import account_deletion as ad
from app.services import google_auth

# Every collection in db.py, read before any fixture swaps the handles for in-memory ones.
ALL = sorted(
    name for name, value in vars(db).items()
    if not name.startswith("_") and type(value).__name__ == "AsyncIOMotorCollection"
)
PASSWORD = "password123"


def run(coro):
    return asyncio.run(coro)


def docs(name):
    async def read():
        return await getattr(db, name).find({}, {"_id": 0}).to_list(None)
    return run(read())


def everything():
    return {name: docs(name) for name in ALL}


# For use from INSIDE code that is already running in the event loop (a callback fired
# during deletion), where asyncio.run() cannot start a second one. The in-memory
# collection wraps a plain synchronous one, which can simply be read.
def now_count(name, query=None):
    # NOT `.delegate`: that is a different, empty object, and a count taken from it is
    # always zero, which made tests built on it pass for the wrong reason.
    return getattr(db, name)._AsyncMongoMockCollection__collection.count_documents(query or {})


def now_everything_except(*skip):
    return {n: now_count(n) for n in ALL if n not in skip}



def total(snapshot):
    return sum(
        len(rows)
        for name, rows in snapshot.items()
        if name not in ad.NON_ACCOUNT_COLLECTIONS
    )


def me(client, token):
    return client.get("/api/auth/me", headers=auth(token))


def ids(client, token):
    user_id = me(client, token).json()["user_id"]
    shop_id = client.get("/api/shop", headers=auth(token)).json()["shop_id"]
    return user_id, shop_id


def populate(client, token, label="a"):
    """A realistically full account: staff made through the real API, then a row in every
    other collection too, so none can be skipped by accident."""
    for number in range(3):
        made = client.post("/api/employees", headers=auth(token),
                           json={**EMPLOYEE, "name": f"Staff {label}{number}", "email": f"staff{label}{number}@example.com"})
        assert made.status_code == 201, made.text
    user_id, shop_id = ids(client, token)

    async def fill():
        for name in ad.SHOP_SCOPED:
            collection = getattr(db, name)
            if not await collection.find_one({"shop_id": shop_id}):
                await collection.insert_one({"shop_id": shop_id, "marker": f"{label}-{name}"})
        await db.user_sessions.insert_one({"session_token": f"tok-{label}", "user_id": user_id, "expires_at": "2999-01-01T00:00:00+00:00"})
        await db.password_resets.insert_one({"token_hash": f"hash-{label}", "user_id": user_id})
        await db.payment_transactions.insert_one({"session_id": f"cs_{label}", "user_id": user_id, "status": "completed", "payment_status": "paid", "amount": 1000})
    run(fill())
    return user_id, shop_id


def belonging_to(snapshot, user_id, shop_id):
    """Every row anywhere that is tied to this account, by id."""
    found = {}
    for name, rows in snapshot.items():
        mine = [r for r in rows if r.get("user_id") == user_id or r.get("owner_id") == user_id or r.get("shop_id") == shop_id]
        if mine:
            found[name] = len(mine)
    return found


def purge(days=31):
    """Run the clean-up as if `days` had gone by since now. Returns the ids it erased."""
    return run(ad.purge_due(now=datetime.now(timezone.utc) + timedelta(days=days)))


def user_row(user_id):
    return [u for u in docs("users") if u["user_id"] == user_id][0]


def login(client, email="owner@example.com", password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def set_user(user_id, **fields):
    async def write():
        await db.users.update_one({"user_id": user_id}, {"$set": fields})
    run(write())


def delete(client, token, email="owner@example.com", password=PASSWORD, **extra):
    body = {"confirm_email": email, **({"password": password} if password is not None else {}), **extra}
    return client.post("/api/auth/delete-account", json=body, headers=auth(token))


# --- nothing can be forgotten -------------------------------------------------------------
class TestTheTestHelpersCanSeeData:
    """Two tests once passed for the wrong reason because a helper read an empty copy of the
    database. These make that impossible to repeat unnoticed."""

    def test_the_in_loop_counter_sees_real_rows(self, client):
        token = register(client)
        populate(client, token)
        assert now_count("employees") == 3
        assert now_count("users") == 1
        assert now_everything_except("users")["employees"] == 3

    def test_it_agrees_with_the_async_reader(self, client):
        token = register(client)
        populate(client, token)
        for name in ALL:
            assert now_count(name) == len(docs(name)), name


class TestEveryCollectionIsAccountedFor:
    def test_the_erasure_plan_covers_exactly_the_collections_in_db_py(self):
        assert set(ALL) == set(ad.ERASURE_PLAN), (
            "A collection was added to (or removed from) db.py without deciding how an "
            "account's rows in it are erased. Add it to account_deletion.py. "
            f"In db.py only: {sorted(set(ALL) - set(ad.ERASURE_PLAN))}. "
            f"In the plan only: {sorted(set(ad.ERASURE_PLAN) - set(ALL))}."
        )

    def test_each_collection_has_one_rule_not_two(self):
        groups = [
            set(ad.SHOP_SCOPED),
            set(ad.USER_SCOPED),
            {ad.SHOPS},
            {ad.USERS},
            set(ad.NON_ACCOUNT_COLLECTIONS),
        ]
        assert sum(len(g) for g in groups) == len(ad.ERASURE_PLAN)


# --- step one: the request closes the account and keeps the data ------------------------------
class TestRequestingDeletion:
    def test_it_needs_you_to_be_signed_in(self, client):
        response = client.post("/api/auth/delete-account", json={"confirm_email": "a@b.ie", "password": "x"})
        assert response.status_code == 401

    def test_it_says_when_everything_will_be_erased(self, client):
        token = register(client)
        response = delete(client, token)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["scheduled"] is True and body["days"] == 30
        when = datetime.fromisoformat(body["delete_on"])
        assert abs((when - datetime.now(timezone.utc)) - timedelta(days=30)) < timedelta(minutes=1)
        assert "deleted" not in body, "nothing has been deleted yet, and the answer must not say it has"

    def test_nothing_is_erased_yet(self, client):
        token = register(client)
        user_id, shop_id = populate(client, token)
        before = everything()

        expected = set(ALL) - set(ad.NON_ACCOUNT_COLLECTIONS)
        assert set(belonging_to(before, user_id, shop_id)) == expected, (
            "the test must start with a row in every account-owned collection"
        )


        delete(client, token)

        after = everything()
        untouched = [n for n in ALL if n not in ("users", "user_sessions", *ad.NON_ACCOUNT_COLLECTIONS)]
        assert {n: after[n] for n in untouched} == {n: before[n] for n in untouched}, "data was changed or removed at the request"
        assert [r for r in after["users"] if r["user_id"] == user_id], "the user record must stay for the thirty days"

    def test_the_record_carries_the_two_dates(self, client):
        token = register(client)
        user_id, _ = ids(client, token)
        delete(client, token)
        row = user_row(user_id)
        requested = datetime.fromisoformat(row["deletion_requested_at"])
        scheduled = datetime.fromisoformat(row["deletion_scheduled_for"])
        assert abs(requested - datetime.now(timezone.utc)) < timedelta(minutes=1)
        assert scheduled - requested == timedelta(days=ad.GRACE_DAYS) == timedelta(days=30)

    def test_the_paid_plan_is_switched_off_so_coming_back_does_not_keep_it_for_free(self, client):
        token = register(client)
        user_id, _ = ids(client, token)
        set_user(user_id, pro=True, pro_since="2026-01-01T00:00:00+00:00")
        delete(client, token)
        row = user_row(user_id)
        assert row["pro"] is False and "pro_since" not in row

    def test_every_sign_in_stops_working_at_once_on_every_device(self, client):
        token = register(client)
        delete(client, token)
        assert me(client, token).status_code == 401
        assert client.get("/api/employees", headers=auth(token)).status_code == 401
        assert client.get("/api/shop", headers=auth(token)).status_code == 401

    def test_sessions_are_removed(self, client):
        token = register(client)
        user_id, shop_id = populate(client, token)
        delete(client, token)
        assert [r for r in docs("user_sessions") if r["user_id"] == user_id] == []

    def test_the_session_cookie_is_cleared(self, client):
        token = register(client)
        response = delete(client, token)
        assert "session_token=" in response.headers.get("set-cookie", "")

    def test_a_second_request_with_the_old_token_is_refused_and_does_not_crash(self, client):
        token = register(client)
        delete(client, token)
        assert delete(client, token).status_code == 401

    def test_asking_twice_keeps_the_original_date(self, client):
        token = register(client)
        user_id, _ = ids(client, token)
        delete(client, token)
        first = user_row(user_id)["deletion_scheduled_for"]
        run(ad.request_deletion(user_row(user_id)))
        assert user_row(user_id)["deletion_scheduled_for"] == first

    def test_a_wrong_answer_schedules_nothing(self, client):
        token = register(client)
        user_id, _ = ids(client, token)
        delete(client, token, password="nope")
        assert "deletion_scheduled_for" not in user_row(user_id)


# --- the thirty days -------------------------------------------------------------------------
class TestThirtyDays:
    def request(self, client, label="a"):
        token = register(client)
        user_id, shop_id = populate(client, token, label)
        delete(client, token)
        return token, user_id, shop_id

    def test_nothing_is_erased_before_the_date(self, client):
        token, user_id, shop_id = self.request(client)
        before = everything()
        assert purge(days=29.9) == []
        assert everything() == before

    def test_it_is_erased_once_the_date_has_passed(self, client):
        token, user_id, shop_id = self.request(client)
        assert purge(days=30.1) == [user_id]
        after = everything()
        assert belonging_to(after, user_id, shop_id) == {}
        assert total(after) == 0, f"left behind: { {k: v for k, v in after.items() if v} }"

    def test_the_date_itself_counts_as_the_day(self, client):
        token, user_id, shop_id = self.request(client)
        due = ad.parse_when(user_row(user_id)["deletion_scheduled_for"])
        assert run(ad.purge_due(now=due - timedelta(seconds=1))) == []
        assert run(ad.purge_due(now=due)) == [user_id]

    def test_no_trace_of_the_person_or_their_staff_is_left_in_any_text(self, client):
        token, user_id, shop_id = self.request(client)
        purge()
        leftovers = json.dumps(everything(), default=str)
        for needle in ("owner@example.com", user_id, shop_id, "Staff a0", "staffa1@example.com"):
            assert needle not in leftovers

    def test_the_account_is_gone_from_the_users_table_specifically(self, client):
        token, user_id, _ = self.request(client)
        purge()
        assert not [u for u in docs("users") if u["user_id"] == user_id]

    def test_the_same_email_can_start_again_once_it_is_gone_with_nothing_carried_over(self, client):
        """The point of it: leave one company, begin at another on the same address."""
        token, user_id, shop_id = self.request(client)
        purge()
        fresh = register(client)                        # same email, same password
        assert client.get("/api/employees", headers=auth(fresh)).json() == []
        assert client.get("/api/shop", headers=auth(fresh)).json()["onboarded"] is False
        assert ids(client, fresh)[0] != user_id

    def test_the_password_no_longer_signs_in_once_it_is_gone(self, client):
        self.request(client)
        purge()
        response = login(client)
        # Erasure must not reveal whether this address used to have an account.
        assert response.status_code == 401 and response.json()["detail"] == "Invalid email or password"

    def test_running_the_clean_up_again_finds_nothing_and_is_harmless(self, client):
        token, user_id, _ = self.request(client)
        assert purge() == [user_id]
        assert purge() == []
        assert total(everything()) == 0

    def test_an_account_that_never_asked_is_never_erased_however_old(self, client):
        token = register(client)
        populate(client, token)
        before = everything()
        assert purge(days=100000) == []
        assert everything() == before

    def test_only_the_account_that_asked_is_erased(self, client):
        a = register(client, email="a@example.com")
        b = register(client, email="b@example.com")
        a_user, a_shop = populate(client, a, "a")
        b_user, b_shop = populate(client, b, "b")
        delete(client, a, email="a@example.com")
        assert purge() == [a_user]
        after = everything()
        assert belonging_to(after, a_user, a_shop) == {}
        assert set(belonging_to(after, b_user, b_shop)) == set(ALL) - set(ad.NON_ACCOUNT_COLLECTIONS)

    def test_every_account_that_is_due_is_erased_in_one_run(self, client):
        users = []
        for number in range(3):
            email = f"due{number}@example.com"
            token = register(client, email=email)
            users.append(populate(client, token, f"d{number}")[0])
            delete(client, token, email=email)
        assert sorted(purge()) == sorted(users)
        assert total(everything()) == 0

    def test_one_account_failing_does_not_stop_the_others_and_it_is_tried_again(self, client, monkeypatch):
        first = register(client, email="first@example.com"); second = register(client, email="second@example.com")
        first_id, _ = populate(client, first, "f"); second_id, _ = populate(client, second, "s")
        delete(client, first, email="first@example.com"); delete(client, second, email="second@example.com")
        real = ad.erase

        async def fails_for_the_first(user):
            if user["user_id"] == first_id:
                raise RuntimeError("the database went away")
            return await real(user)

        monkeypatch.setattr(ad, "erase", fails_for_the_first)
        assert purge() == [second_id]
        assert [u for u in docs("users") if u["user_id"] == first_id], "the failed account must remain to be retried"
        monkeypatch.setattr(ad, "erase", real)
        assert purge() == [first_id]
        assert total(everything()) == 0


    def test_shared_security_data_is_not_erased_with_an_account(self, client):
        """auth_rate_limits is not account data: it is kept, on purpose, whoever is erased."""
        token, user_id, shop_id = self.request(client)
        async def add():
            await db.auth_rate_limits.insert_one({"key": "shared-limit", "hits": 3})
        run(add())
        assert purge() == [user_id]
        assert [r["key"] for r in docs("auth_rate_limits") if r.get("key") == "shared-limit"] == ["shared-limit"]


class TestTheHourlyJob:
    def due_account(self, client):
        token = register(client)
        user_id, _ = populate(client, token)
        delete(client, token)
        set_user(user_id, deletion_scheduled_for=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
        return user_id

    def run_loop(self, seconds, **kwargs):
        async def go():
            task = asyncio.create_task(ad.purge_loop(**kwargs))
            await asyncio.sleep(seconds)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        run(go())

    def test_it_erases_what_is_due(self, client):
        self.due_account(client)
        self.run_loop(0.3, first_run_after=0, every=0.05)
        assert total(everything()) == 0

    def test_it_waits_before_its_first_run(self, client):
        self.due_account(client)
        before = everything()
        self.run_loop(0.2, first_run_after=60, every=60)
        assert everything() == before

    def test_an_error_in_one_run_does_not_stop_it(self, client, monkeypatch):
        self.due_account(client)
        real = ad.purge_due
        calls = {"n": 0}

        async def flaky(now=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("a hiccup")
            return await real(now)

        monkeypatch.setattr(ad, "purge_due", flaky)
        self.run_loop(0.4, first_run_after=0, every=0.05)
        assert calls["n"] >= 2
        assert total(everything()) == 0

    def test_the_server_starts_it_and_stops_it_on_shutdown(self, client, monkeypatch):
        from fastapi.testclient import TestClient
        from app.main import app
        events = []

        async def stand_in():
            events.append("started")
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                events.append("cancelled")
                raise

        async def record_close():
            events.append("database closed")

        monkeypatch.setattr(ad, "purge_loop", stand_in)
        monkeypatch.setattr(db, "close", record_close)
        with TestClient(app):
            pass
        # Stopped by the server's own shutdown code, and before the database goes away: the
        # test framework would cancel a forgotten task too, but only afterwards.
        assert events == ["started", "cancelled", "database closed"]

    def test_the_real_job_defaults_are_a_minute_then_hourly(self):
        assert ad.PURGE_FIRST_RUN_SECONDS == 60 and ad.PURGE_EVERY_SECONDS == 3600


# --- changing your mind ----------------------------------------------------------------------
class TestComingBack:
    def closed(self, client):
        token = register(client)
        user_id, shop_id = populate(client, token)
        delete(client, token)
        return token, user_id, shop_id

    def test_signing_in_within_the_thirty_days_cancels_the_deletion(self, client):
        old, user_id, shop_id = self.closed(client)
        response = login(client)
        assert response.status_code == 200, response.text
        assert response.json()["restored"] is True
        row = user_row(user_id)
        assert "deletion_scheduled_for" not in row and "deletion_requested_at" not in row

    def test_everything_is_as_it_was_left(self, client):
        old, user_id, shop_id = self.closed(client)
        token = login(client).json()["token"]
        names = sorted(e["name"] for e in client.get("/api/employees", headers=auth(token)).json())
        assert names == ["Staff a0", "Staff a1", "Staff a2"]
        assert me(client, token).status_code == 200

    def test_an_ordinary_sign_in_does_not_say_restored(self, client):
        register(client)
        assert "restored" not in login(client).json()

    def test_the_old_sign_ins_stay_dead_only_the_new_one_works(self, client):
        old, user_id, shop_id = self.closed(client)
        new = login(client).json()["token"]
        assert me(client, old).status_code == 401
        assert me(client, new).status_code == 200

    def test_the_paid_plan_does_not_come_back_with_it(self, client):
        token = register(client)
        user_id, _ = ids(client, token)
        set_user(user_id, pro=True)
        delete(client, token)
        response = login(client)
        assert response.json()["user"]["pro"] is False
        assert user_row(user_id)["pro"] is False

    def test_after_coming_back_the_clean_up_leaves_it_alone(self, client):
        old, user_id, shop_id = self.closed(client)
        login(client)
        assert purge(days=400) == []
        # Every collection still holds its row. Only the sessions are gone: they were removed
        # when the account was closed, and a JWT sign-in does not make one.
        assert set(belonging_to(everything(), user_id, shop_id)) == set(ALL) - {"user_sessions"} - set(ad.NON_ACCOUNT_COLLECTIONS)
        assert user_row(user_id)

    def test_deleting_again_starts_a_fresh_thirty_days(self, client):
        old, user_id, shop_id = self.closed(client)
        first = user_row(user_id)["deletion_scheduled_for"]
        token = login(client).json()["token"]
        assert delete(client, token).status_code == 200
        assert user_row(user_id)["deletion_scheduled_for"] >= first

    def test_the_wrong_password_does_not_bring_it_back(self, client):
        old, user_id, shop_id = self.closed(client)
        assert login(client, password="wrong").status_code == 401
        assert user_row(user_id)["deletion_scheduled_for"]

    def test_after_the_date_it_cannot_come_back_even_before_the_clean_up_runs(self, client):
        old, user_id, shop_id = self.closed(client)
        set_user(user_id, deletion_scheduled_for=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
        response = login(client)
        assert response.status_code == 401
        assert user_row(user_id).get("deletion_scheduled_for"), "an expired account must not be restored by a late sign-in"
        assert purge(days=0) == [user_id]

    def test_google_sign_in_brings_it_back_too(self, client, monkeypatch):
        profile = {"email": "gina@gmail.com", "google_sub": "sub-gina", "name": "Gina G", "picture": ""}
        monkeypatch.setattr(google_auth, "verify_id_token", lambda c: dict(profile))
        first = client.post("/api/auth/google", json={"credential": "x"}).json()
        assert "restored" not in first
        sent = client.post("/api/auth/delete-account", headers=auth(first["token"]),
                           json={"confirm_email": "gina@gmail.com", "google_credential": "fresh"})
        assert sent.status_code == 200
        back = client.post("/api/auth/google", json={"credential": "x"})
        assert back.status_code == 200 and back.json()["restored"] is True
        assert me(client, back.json()["token"]).status_code == 200

    def test_google_sign_in_after_the_date_is_refused(self, client, monkeypatch):
        profile = {"email": "gina@gmail.com", "google_sub": "sub-gina", "name": "Gina G", "picture": ""}
        monkeypatch.setattr(google_auth, "verify_id_token", lambda c: dict(profile))
        first = client.post("/api/auth/google", json={"credential": "x"}).json()
        client.post("/api/auth/delete-account", headers=auth(first["token"]),
                    json={"confirm_email": "gina@gmail.com", "google_credential": "fresh"})
        user_id = [u for u in docs("users")][0]["user_id"]
        set_user(user_id, deletion_scheduled_for=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
        assert client.post("/api/auth/google", json={"credential": "x"}).status_code == 401


# --- a closed account cannot be used --------------------------------------------------------
class TestWhileItWaits:
    def test_a_sign_in_that_slipped_through_still_cannot_use_a_closed_account(self, client):
        """Close it WITHOUT bumping the token version, so the old token still matches."""
        token = register(client)
        user_id, _ = ids(client, token)
        set_user(user_id, deletion_scheduled_for="2999-01-01T00:00:00+00:00")
        assert me(client, token).status_code == 401
        assert client.get("/api/employees", headers=auth(token)).status_code == 401

    def test_a_cookie_session_cannot_use_a_closed_account_either(self, client):
        token = register(client)
        user_id, _ = ids(client, token)
        async def make():
            await db.user_sessions.insert_one({"session_token": "cookie-tok", "user_id": user_id, "expires_at": "2999-01-01T00:00:00+00:00"})
        run(make())
        assert client.get("/api/auth/me", cookies={"session_token": "cookie-tok"}).status_code == 200
        set_user(user_id, deletion_scheduled_for="2999-01-01T00:00:00+00:00")
        assert client.get("/api/auth/me", cookies={"session_token": "cookie-tok"}).status_code == 401

    def test_other_accounts_are_not_locked_out(self, client):
        a = register(client, email="a@example.com"); b = register(client, email="b@example.com")
        delete(client, a, email="a@example.com")
        assert me(client, b).status_code == 200


class TestSigningUpAgainEarly:
    def test_the_address_of_a_waiting_account_says_what_to_do(self, client):
        token = register(client)
        delete(client, token)
        response = client.post("/api/auth/signup", json={"email": "owner@example.com", "password": PASSWORD, "name": "N", "shop_name": "S"})
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "scheduled for deletion" in detail and "Sign in to cancel the deletion" in detail
        assert str((datetime.now(timezone.utc) + timedelta(days=30)).year) in detail

    def test_an_ordinary_taken_address_keeps_the_old_message(self, client):
        register(client)
        response = client.post("/api/auth/signup", json={"email": "owner@example.com", "password": PASSWORD, "name": "N", "shop_name": "S"})
        assert response.status_code == 409 and response.json()["detail"] == "That email is already registered"

    def test_nothing_is_created_by_the_refused_sign_up(self, client):
        token = register(client)
        delete(client, token)
        def owned(snapshot):
            return {name: rows for name, rows in snapshot.items() if name not in ad.NON_ACCOUNT_COLLECTIONS}

        before = owned(everything())
        client.post("/api/auth/signup", json={"email": "owner@example.com", "password": PASSWORD, "name": "N", "shop_name": "S"})
        assert owned(everything()) == before


# --- it must be you, and you must mean it ---------------------------------------------------
class TestConfirmation:
    def intact(self, client, token, user_id, shop_id):
        assert me(client, token).status_code == 200
        assert belonging_to(everything(), user_id, shop_id), "nothing may have been deleted"

    def test_the_wrong_email_deletes_nothing(self, client):
        token = register(client)
        user_id, shop_id = populate(client, token)
        response = delete(client, token, email="someone.else@example.com")
        assert response.status_code == 400
        assert "email address" in response.json()["detail"]
        self.intact(client, token, user_id, shop_id)

    def test_a_blank_email_deletes_nothing(self, client):
        token = register(client)
        user_id, shop_id = populate(client, token)
        assert delete(client, token, email="").status_code == 400
        self.intact(client, token, user_id, shop_id)

    @pytest.mark.parametrize("typed", ["OWNER@EXAMPLE.COM", "  owner@example.com  ", "Owner@Example.com"])
    def test_capitals_and_stray_spaces_in_the_email_are_forgiven(self, client, typed):
        token = register(client)
        assert delete(client, token, email=typed).status_code == 200

    def test_no_password_deletes_nothing(self, client):
        token = register(client)
        user_id, shop_id = populate(client, token)
        response = delete(client, token, password=None)
        assert response.status_code == 403
        self.intact(client, token, user_id, shop_id)

    @pytest.mark.parametrize("wrong", ["", "wrong-password", PASSWORD + " ", PASSWORD.upper()])
    def test_the_wrong_password_deletes_nothing(self, client, wrong):
        token = register(client)
        user_id, shop_id = populate(client, token)
        response = delete(client, token, password=wrong)
        assert response.status_code == 403
        assert response.json()["detail"] == "That is not your password."
        self.intact(client, token, user_id, shop_id)

    def test_a_wrong_password_is_403_never_401_so_a_typo_cannot_sign_you_out(self, client):
        """The screen clears the sign-in on any 401. A mistyped password must not do that."""
        token = register(client)
        status = delete(client, token, password="nope").status_code
        assert status == 403 and status != 401

    def test_the_right_email_alone_is_not_enough(self, client):
        token = register(client)
        user_id, shop_id = populate(client, token)
        assert delete(client, token, password="").status_code == 403
        self.intact(client, token, user_id, shop_id)

    def test_a_google_credential_cannot_stand_in_for_a_password_that_exists(self, client, monkeypatch):
        token = register(client)
        user_id, shop_id = populate(client, token)
        monkeypatch.setattr(google_auth, "verify_id_token", lambda c: {"email": "owner@example.com", "google_sub": "g1", "name": "O", "picture": ""})
        response = delete(client, token, password=None, google_credential="anything")
        assert response.status_code == 403
        self.intact(client, token, user_id, shop_id)

    def test_somebody_elses_token_cannot_delete_this_account_with_this_accounts_email(self, client):
        mine = register(client, email="mine@example.com")
        theirs = register(client, email="theirs@example.com")
        user_id, shop_id = populate(client, mine, "m")
        # They try to delete 'mine' while signed in as themselves: the email they type must be THEIRS.
        response = delete(client, theirs, email="mine@example.com")
        assert response.status_code == 400
        assert me(client, mine).status_code == 200 and belonging_to(everything(), user_id, shop_id)


# --- the other accounts are none of its business ---------------------------------------------
class TestOtherAccountsAreUntouched:
    def test_deleting_one_account_leaves_another_exactly_as_it_was(self, client):
        a = register(client, email="a@example.com")
        b = register(client, email="b@example.com")
        a_user, a_shop = populate(client, a, "a")
        b_user, b_shop = populate(client, b, "b")
        before = everything()
        b_before = {name: sorted(json.dumps(r, sort_keys=True, default=str) for r in rows
                                 if r.get("user_id") == b_user or r.get("owner_id") == b_user or r.get("shop_id") == b_shop)
                    for name, rows in before.items()}

        assert delete(client, a, email="a@example.com").status_code == 200
        assert purge() == [a_user]

        after = everything()
        assert belonging_to(after, a_user, a_shop) == {}
        b_after = {name: sorted(json.dumps(r, sort_keys=True, default=str) for r in rows
                                if r.get("user_id") == b_user or r.get("owner_id") == b_user or r.get("shop_id") == b_shop)
                   for name, rows in after.items()}
        assert b_after == b_before, "another account's rows changed"

    def test_the_other_account_still_works(self, client):
        a = register(client, email="a@example.com")
        b = register(client, email="b@example.com")
        populate(client, a, "a")
        populate(client, b, "b")
        delete(client, a, email="a@example.com")
        assert me(client, b).status_code == 200
        purge()
        names = sorted(e["name"] for e in client.get("/api/employees", headers=auth(b)).json())
        assert names == ["Staff b0", "Staff b1", "Staff b2"]
        assert client.post("/api/auth/login", json={"email": "b@example.com", "password": PASSWORD}).status_code == 200

    def test_staff_with_the_same_names_in_two_shops_are_not_confused(self, client):
        a = register(client, email="a@example.com")
        b = register(client, email="b@example.com")
        for token in (a, b):
            client.post("/api/employees", headers=auth(token), json={**EMPLOYEE, "name": "Sam Same", "email": "sam@example.com"})
        delete(client, a, email="a@example.com")
        assert [e["name"] for e in client.get("/api/employees", headers=auth(b)).json()] == ["Sam Same"]

    def test_an_account_with_a_similar_email_is_not_affected(self, client):
        a = register(client, email="pat@example.com")
        b = register(client, email="pat@example.co")
        populate(client, b, "b")
        delete(client, a, email="pat@example.com")
        assert me(client, b).status_code == 200


# --- accounts that sign in with Google -------------------------------------------------------
class TestGoogleAccounts:
    PROFILE = {"email": "gina@gmail.com", "google_sub": "sub-gina", "name": "Gina G", "picture": "http://x/p.png"}

    @pytest.fixture()
    def gina(self, client, monkeypatch):
        monkeypatch.setattr(google_auth, "verify_id_token", lambda credential: dict(self.PROFILE))
        signed_in = client.post("/api/auth/google", json={"credential": "first-sign-in"})
        assert signed_in.status_code == 200, signed_in.text
        return signed_in.json()["token"], signed_in.json()["user"]

    def go(self, client, token, credential="fresh", email="gina@gmail.com"):
        return client.post("/api/auth/delete-account", headers=auth(token),
                           json={"confirm_email": email, **({"google_credential": credential} if credential is not None else {})})

    def test_the_screen_is_told_there_is_no_password_to_ask_for(self, gina):
        _, user = gina
        assert user["has_password"] is False

    def test_a_google_account_closes_with_a_fresh_google_confirmation(self, client, gina):
        token, user = gina
        client.post("/api/employees", headers=auth(token), json={**EMPLOYEE, "email": "g@example.com"})
        response = self.go(client, token)
        assert response.status_code == 200, response.text
        assert response.json()["scheduled"] is True
        assert total(everything()) > 0, "nothing is erased until the thirty days are up"
        assert me(client, token).status_code == 401
        assert purge() == [user["user_id"]]
        assert total(everything()) == 0

    def test_without_the_google_confirmation_nothing_is_deleted(self, client, gina):
        token, user = gina
        response = self.go(client, token, credential=None)
        assert response.status_code == 403 and "Google" in response.json()["detail"]
        assert me(client, token).status_code == 200

    def test_the_typed_email_is_still_required(self, client, gina):
        token, user = gina
        assert self.go(client, token, email="not.gina@gmail.com").status_code == 400
        assert me(client, token).status_code == 200

    def test_a_different_google_account_cannot_confirm_it(self, client, gina, monkeypatch):
        token, user = gina
        monkeypatch.setattr(google_auth, "verify_id_token", lambda c: {**self.PROFILE, "email": "mallory@gmail.com", "google_sub": "sub-mallory"})
        response = self.go(client, token)
        assert response.status_code == 403
        assert me(client, token).status_code == 200

    def test_the_same_google_identity_but_a_different_address_cannot_confirm_it(self, client, gina, monkeypatch):
        """The identity matches and only the address differs, so only the address check can refuse it."""
        token, user = gina
        monkeypatch.setattr(google_auth, "verify_id_token", lambda c: {**self.PROFILE, "email": "someone.else@gmail.com"})
        assert self.go(client, token).status_code == 403
        assert me(client, token).status_code == 200

    def test_the_same_address_but_a_different_google_identity_cannot_confirm_it(self, client, gina, monkeypatch):
        token, user = gina
        monkeypatch.setattr(google_auth, "verify_id_token", lambda c: {**self.PROFILE, "google_sub": "a-different-sub"})
        assert self.go(client, token).status_code == 403
        assert me(client, token).status_code == 200

    def test_an_invalid_google_credential_is_refused_as_403_not_401(self, client, gina, monkeypatch):
        token, user = gina
        def reject(credential):
            raise google_auth.GoogleAuthInvalid("That Google sign-in is not valid.")
        monkeypatch.setattr(google_auth, "verify_id_token", reject)
        response = self.go(client, token)
        assert response.status_code == 403
        assert me(client, token).status_code == 200

    def test_google_being_unavailable_says_so_and_deletes_nothing(self, client, gina, monkeypatch):
        token, user = gina
        def down(credential):
            raise google_auth.GoogleAuthUnavailable("Google sign-in is not configured.")
        monkeypatch.setattr(google_auth, "verify_id_token", down)
        assert self.go(client, token).status_code == 503
        assert me(client, token).status_code == 200

    def test_the_email_check_ignores_capitals_in_the_googles_address_too(self, client, gina, monkeypatch):
        token, user = gina
        monkeypatch.setattr(google_auth, "verify_id_token", lambda c: {**self.PROFILE, "email": "GINA@Gmail.com"})
        assert self.go(client, token).status_code == 200


class TestWhatTheScreenIsToldAboutThePassword:
    def test_a_password_account_is_marked_as_having_one(self, client):
        token = register(client)
        assert me(client, token).json()["has_password"] is True

    def test_signup_and_login_say_so_too(self, client):
        signup = client.post("/api/auth/signup", json={"email": "new@example.com", "password": PASSWORD, "name": "New", "shop_name": "S"})
        assert signup.json()["user"]["has_password"] is True
        login = client.post("/api/auth/login", json={"email": "new@example.com", "password": PASSWORD})
        assert login.json()["user"]["has_password"] is True

    def test_the_hash_itself_is_never_sent(self, client):
        token = register(client)
        body = json.dumps(me(client, token).json())
        assert "password_hash" not in body and "$2" not in body


# --- billing ---------------------------------------------------------------------------------
class FakeStripeError(Exception):
    def __init__(self, message="boom", code=None):
        super().__init__(message)
        self.code = code


class FakeStripe:
    """Stands in for the Stripe library and writes down everything it is asked to do."""
    StripeError = FakeStripeError

    def __init__(self):
        self.calls = []
        self.on_call = None
        self.cancel_error = None
        self.sessions = {}
        outer = self

        class Subscription:
            @staticmethod
            def cancel(subscription_id):
                outer.calls.append(("cancel", subscription_id))
                if outer.on_call:
                    outer.on_call("cancel", subscription_id)
                if outer.cancel_error:
                    raise outer.cancel_error
                return {"id": subscription_id, "status": "canceled"}

        class Session:
            @staticmethod
            def retrieve(session_id):
                outer.calls.append(("retrieve", session_id))
                if session_id not in outer.sessions:
                    raise FakeStripeError("No such session", code="resource_missing")
                return dict(outer.sessions[session_id])

            @staticmethod
            def expire(session_id):
                outer.calls.append(("expire", session_id))
                if outer.on_call:
                    outer.on_call("expire", session_id)
                return {"id": session_id, "status": "expired"}

        self.Subscription = Subscription
        self.checkout = types.SimpleNamespace(Session=Session)


class TestBillingIsCancelledFirst:
    @pytest.fixture()
    def stripe(self, monkeypatch):
        fake = FakeStripe()
        monkeypatch.setattr(ad, "stripe", fake)
        monkeypatch.setattr(ad.config, "STRIPE_ENABLED", True)
        return fake

    def pay(self, client, token, **record):
        user_id, _ = ids(client, token)
        async def add():
            await db.payment_transactions.insert_one({"user_id": user_id, "status": "completed", "payment_status": "paid", **record})
        run(add())
        return user_id

    def test_no_payments_means_stripe_is_never_called(self, client, stripe):
        token = register(client)
        assert delete(client, token).status_code == 200
        assert stripe.calls == []

    def test_a_subscription_is_cancelled_at_once_and_the_data_goes_after_thirty_days(self, client, stripe):
        token = register(client)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id="sub_1")
        assert delete(client, token).status_code == 200
        assert stripe.calls == [("cancel", "sub_1")]
        assert total(everything()) > 0, "the data stays for the thirty days"
        purge()
        assert total(everything()) == 0
        assert stripe.calls == [("cancel", "sub_1")], "the clean-up must never wait for, or call, Stripe"

    def test_every_subscription_is_cancelled(self, client, stripe):
        token = register(client)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id="sub_1")
        self.pay(client, token, session_id="cs_2", stripe_subscription_id="sub_2")
        delete(client, token)
        assert sorted(c for c in stripe.calls) == [("cancel", "sub_1"), ("cancel", "sub_2")]

    def test_the_subscription_is_cancelled_while_the_data_still_exists(self, client, stripe):
        """Billing first, so a failure there can stop the deletion."""
        token = register(client)
        populate(client, token)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id="sub_1")
        seen = {}
        stripe.on_call = lambda kind, ref: seen.update(employees=now_count("employees"), users=now_count("users"))
        delete(client, token)
        assert seen == {"employees": 3, "users": 1}

    def test_a_one_off_payment_needs_no_cancelling(self, client, stripe):
        token = register(client)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id=None)
        delete(client, token)
        assert stripe.calls == []

    @pytest.mark.parametrize("state", ["expired", "failed"])
    def test_finished_or_failed_payments_need_nothing(self, client, stripe, state):
        token = register(client)
        self.pay(client, token, session_id="cs_1", status=state, payment_status=state)
        delete(client, token)
        assert stripe.calls == []

    def test_an_unfinished_checkout_is_expired_so_it_cannot_be_paid_after_the_account_is_gone(self, client, stripe):
        token = register(client)
        self.pay(client, token, session_id="cs_open", status="initiated", payment_status="pending")
        stripe.sessions["cs_open"] = {"status": "open"}
        assert delete(client, token).status_code == 200
        assert stripe.calls == [("retrieve", "cs_open"), ("expire", "cs_open")]

    def test_a_checkout_that_finished_without_us_hearing_has_its_subscription_cancelled(self, client, stripe):
        token = register(client)
        self.pay(client, token, session_id="cs_late", status="initiated", payment_status="pending")
        stripe.sessions["cs_late"] = {"status": "complete", "subscription": "sub_late"}
        delete(client, token)
        assert stripe.calls == [("retrieve", "cs_late"), ("cancel", "sub_late")]

    def test_a_pending_checkout_stripe_has_never_heard_of_is_not_a_problem(self, client, stripe):
        token = register(client)
        self.pay(client, token, session_id="cs_gone", status="initiated", payment_status="pending")
        assert delete(client, token).status_code == 200

    def test_a_subscription_already_gone_at_stripe_counts_as_cancelled(self, client, stripe):
        token = register(client)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id="sub_1")
        stripe.cancel_error = FakeStripeError("No such subscription", code="resource_missing")
        assert delete(client, token).status_code == 200

    def test_if_stripe_will_not_cancel_the_account_is_not_closed_and_nothing_is_deleted(self, client, stripe):
        token = register(client)
        user_id, shop_id = populate(client, token)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id="sub_1")
        stripe.cancel_error = FakeStripeError("Stripe is down", code="api_connection_error")
        before = everything()

        response = delete(client, token)

        assert response.status_code == 502
        assert "has not been deleted" in response.json()["detail"]
        assert everything() == before, "a failed cancellation must leave every row in place, and schedule nothing"
        assert me(client, token).status_code == 200

    def test_the_message_does_not_leak_the_providers_internals(self, client, stripe):
        token = register(client)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id="sub_1")
        stripe.cancel_error = FakeStripeError("sk_live_SECRET key rejected", code="authentication_error")
        assert "sk_live" not in delete(client, token).json()["detail"]

    def test_trying_again_after_a_failure_works(self, client, stripe):
        token = register(client)
        populate(client, token)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id="sub_1")
        stripe.cancel_error = FakeStripeError("Stripe is down", code="api_connection_error")
        assert delete(client, token).status_code == 502
        stripe.cancel_error = None
        assert delete(client, token).status_code == 200
        assert stripe.calls.count(("cancel", "sub_1")) == 2
        assert total(everything()) > 0
        purge()
        assert total(everything()) == 0

    def test_a_subscription_with_billing_unavailable_is_refused_not_stranded(self, client, monkeypatch):
        fake = FakeStripe()
        monkeypatch.setattr(ad, "stripe", fake)               # one that would happily cancel, if asked
        monkeypatch.setattr(ad.config, "STRIPE_ENABLED", False)
        token = register(client)
        populate(client, token)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id="sub_1")
        before = everything()
        response = delete(client, token)
        assert response.status_code == 502
        assert everything() == before
        assert fake.calls == [], "billing is switched off: Stripe must not be contacted at all"

    def test_with_billing_unavailable_and_nothing_to_cancel_deletion_goes_ahead(self, client, monkeypatch):
        monkeypatch.setattr(ad.config, "STRIPE_ENABLED", False)
        token = register(client)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id=None)
        assert delete(client, token).status_code == 200

    def test_other_peoples_subscriptions_are_never_cancelled(self, client, stripe):
        a = register(client, email="a@example.com")
        b = register(client, email="b@example.com")
        self.pay(client, a, session_id="cs_a", stripe_subscription_id="sub_a")
        self.pay(client, b, session_id="cs_b", stripe_subscription_id="sub_b")
        delete(client, a, email="a@example.com")
        assert stripe.calls == [("cancel", "sub_a")]
        assert sorted(r["session_id"] for r in docs("payment_transactions")) == ["cs_a", "cs_b"]
        purge()
        assert [r["session_id"] for r in docs("payment_transactions")] == ["cs_b"]


# --- it survives being interrupted --------------------------------------------------------------
class TestFailuresAndRaces:
    def test_a_failure_part_way_leaves_the_account_so_it_can_be_retried(self, client, monkeypatch):
        token = register(client)
        user_id, shop_id = populate(client, token)
        user = [u for u in docs("users") if u["user_id"] == user_id][0]
        real = db.rosters.delete_many
        attempts = {"n": 0}

        async def flaky(*args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("the database went away")
            return await real(*args, **kwargs)

        monkeypatch.setattr(db.rosters, "delete_many", flaky)
        with pytest.raises(RuntimeError):
            run(ad.erase(user))

        assert [u for u in docs("users") if u["user_id"] == user_id], "the account must survive a failed attempt"
        assert me(client, token).status_code == 200

        run(ad.erase(user))                                   # the retry
        assert belonging_to(everything(), user_id, shop_id) == {}

    def test_running_it_twice_is_harmless(self, client):
        token = register(client)
        user_id, shop_id = populate(client, token)
        user = [u for u in docs("users") if u["user_id"] == user_id][0]
        run(ad.erase(user))
        run(ad.erase(user))
        assert total(everything()) == 0

    def test_a_row_written_by_a_request_already_in_flight_is_swept_up(self, client, monkeypatch):
        """Another tab was mid-save when deletion began. Its write lands after the first pass."""
        token = register(client)
        user_id, shop_id = populate(client, token)
        user = [u for u in docs("users") if u["user_id"] == user_id][0]
        real = db.users.delete_one

        async def delete_then_a_late_write(*args, **kwargs):
            result = await real(*args, **kwargs)
            await db.rosters.insert_one({"shop_id": shop_id, "late": True})
            await db.employees.insert_one({"shop_id": shop_id, "name": "Late Arrival"})
            return result

        monkeypatch.setattr(db.users, "delete_one", delete_then_a_late_write)
        run(ad.erase(user))
        assert total(everything()) == 0, "a late write survived the second pass"

    def test_a_shop_created_by_a_request_in_flight_is_swept_up_too(self, client, monkeypatch):
        """The app makes a shop on first use, so a straggler could create a brand new one."""
        token = register(client)
        user_id, shop_id = populate(client, token)
        user = [u for u in docs("users") if u["user_id"] == user_id][0]
        real = db.users.delete_one

        async def delete_then_a_new_shop(*args, **kwargs):
            result = await real(*args, **kwargs)
            await db.shops.insert_one({"shop_id": "shop_reborn", "owner_id": user_id})
            await db.rosters.insert_one({"shop_id": "shop_reborn"})
            await db.ai_rules.insert_one({"shop_id": "shop_reborn", "title": "seeded again"})
            return result

        monkeypatch.setattr(db.users, "delete_one", delete_then_a_new_shop)
        run(ad.erase(user))
        assert total(everything()) == 0

    def test_the_user_record_is_removed_last(self, client, monkeypatch):
        token = register(client)
        user_id, shop_id = populate(client, token)
        user = [u for u in docs("users") if u["user_id"] == user_id][0]
        real = db.users.delete_one
        seen = {}

        async def look(*args, **kwargs):
            seen["others_gone_when_the_user_goes"] = sum(now_everything_except("users", *ad.NON_ACCOUNT_COLLECTIONS).values()) == 0
            return await real(*args, **kwargs)

        monkeypatch.setattr(db.users, "delete_one", look)
        run(ad.erase(user))
        assert seen == {"others_gone_when_the_user_goes": True}

    def test_a_shop_with_no_data_at_all_is_fine(self, client):
        token = register(client)
        assert delete(client, token).status_code == 200
        purge()
        assert total(everything()) == 0

    def test_the_counts_say_what_was_removed(self, client):
        token = register(client)
        user_id, _ = populate(client, token)
        user = [u for u in docs("users") if u["user_id"] == user_id][0]
        counts = run(ad.erase(user))
        assert counts["employees"] == 3 and counts["users"] == 1 and counts["shops"] == 1
