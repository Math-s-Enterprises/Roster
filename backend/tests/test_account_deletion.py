"""Deleting your own account erases everything it owns, and nothing else.

This is irreversible, so the tests are written around the ways it could go wrong: leaving
data behind, taking somebody else's, being triggered by the wrong person, deleting data
while a subscription keeps charging, and being left half-done by a failure.
"""
import asyncio
import json
import types

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
    return sum(len(rows) for rows in snapshot.values())


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
        groups = [set(ad.SHOP_SCOPED), set(ad.USER_SCOPED), {ad.SHOPS}, {ad.USERS}]
        assert sum(len(g) for g in groups) == len(ad.ERASURE_PLAN)


# --- the thing itself ---------------------------------------------------------------------
class TestDeletingAnAccount:
    def test_it_needs_you_to_be_signed_in(self, client):
        response = client.post("/api/auth/delete-account", json={"confirm_email": "a@b.ie", "password": "x"})
        assert response.status_code == 401

    def test_everything_goes(self, client):
        token = register(client)
        user_id, shop_id = populate(client, token)
        before = everything()
        assert set(belonging_to(before, user_id, shop_id)) == set(ALL), "the test must start with a row in every collection"

        response = delete(client, token)

        assert response.status_code == 200, response.text
        assert response.json() == {"deleted": True}
        after = everything()
        assert belonging_to(after, user_id, shop_id) == {}
        assert total(after) == 0, f"left behind: { {k: v for k, v in after.items() if v} }"

    def test_no_trace_of_the_person_or_their_staff_is_left_in_any_text(self, client):
        token = register(client)
        user_id, shop_id = populate(client, token)
        delete(client, token)
        leftovers = json.dumps(everything(), default=str)
        for needle in ("owner@example.com", user_id, shop_id, "Staff a0", "stafffa1@example.com", "staffa1@example.com"):
            assert needle not in leftovers

    def test_the_sign_in_stops_working_at_once_on_every_device(self, client):
        token = register(client)
        delete(client, token)
        assert me(client, token).status_code == 401
        assert client.get("/api/employees", headers=auth(token)).status_code == 401
        assert client.get("/api/shop", headers=auth(token)).status_code == 401

    def test_the_password_no_longer_signs_in(self, client):
        token = register(client)
        delete(client, token)
        login = client.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
        assert login.status_code == 401

    def test_the_same_email_can_start_again_with_nothing_carried_over(self, client):
        """The point of it: leave one company, begin at another on the same address."""
        token = register(client)
        populate(client, token)
        delete(client, token)

        fresh = register(client)                        # same email, same password
        assert client.get("/api/employees", headers=auth(fresh)).json() == []
        assert client.get("/api/shop", headers=auth(fresh)).json()["onboarded"] is False
        user_id, shop_id = ids(client, fresh)
        assert user_id != "" and shop_id != ""

    def test_a_second_attempt_finds_nothing_to_delete_and_does_not_crash(self, client):
        token = register(client)
        delete(client, token)
        again = delete(client, token)
        assert again.status_code == 401

    def test_the_session_cookie_is_cleared(self, client):
        token = register(client)
        response = delete(client, token)
        assert "session_token=" in response.headers.get("set-cookie", "")

    def test_the_account_is_gone_from_the_users_table_specifically(self, client):
        token = register(client)
        user_id, _ = ids(client, token)
        delete(client, token)
        assert not [u for u in docs("users") if u["user_id"] == user_id]


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

    def test_a_google_account_deletes_with_a_fresh_google_confirmation(self, client, gina):
        token, user = gina
        client.post("/api/employees", headers=auth(token), json={**EMPLOYEE, "email": "g@example.com"})
        response = self.go(client, token)
        assert response.status_code == 200, response.text
        assert total(everything()) == 0
        assert me(client, token).status_code == 401

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

    def test_a_subscription_is_cancelled_and_then_the_data_goes(self, client, stripe):
        token = register(client)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id="sub_1")
        assert delete(client, token).status_code == 200
        assert stripe.calls == [("cancel", "sub_1")]
        assert total(everything()) == 0

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

    def test_if_stripe_will_not_cancel_nothing_at_all_is_deleted(self, client, stripe):
        token = register(client)
        user_id, shop_id = populate(client, token)
        self.pay(client, token, session_id="cs_1", stripe_subscription_id="sub_1")
        stripe.cancel_error = FakeStripeError("Stripe is down", code="api_connection_error")
        before = everything()

        response = delete(client, token)

        assert response.status_code == 502
        assert "nothing" in response.json()["detail"].lower()
        assert everything() == before, "a failed cancellation must leave every row in place"
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
        assert total(everything()) == 0
        assert stripe.calls.count(("cancel", "sub_1")) == 2

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
            seen["others_gone_when_the_user_goes"] = sum(now_everything_except("users").values()) == 0
            return await real(*args, **kwargs)

        monkeypatch.setattr(db.users, "delete_one", look)
        run(ad.erase(user))
        assert seen == {"others_gone_when_the_user_goes": True}

    def test_a_shop_with_no_data_at_all_is_fine(self, client):
        token = register(client)
        assert delete(client, token).status_code == 200
        assert total(everything()) == 0

    def test_the_counts_say_what_was_removed(self, client):
        token = register(client)
        user_id, _ = populate(client, token)
        user = [u for u in docs("users") if u["user_id"] == user_id][0]
        counts = run(ad.erase(user))
        assert counts["employees"] == 3 and counts["users"] == 1 and counts["shops"] == 1
