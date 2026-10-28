"""A verified Google identity is not a completed signup until a password is chosen."""
import asyncio

import pytest

from app import db
from app.services import google_auth
from tests.test_api import auth, register

PROFILE = {"email": "new.google@gmail.com", "google_sub": "new-google-subject",
           "name": "New Google User", "picture": None, "email_authoritative": True}
PASSWORD = "my-roster-password"


@pytest.fixture
def verified_google(monkeypatch):
    calls = []
    def verify(credential):
        calls.append(credential)
        return dict(PROFILE)
    monkeypatch.setattr(google_auth, "verify_id_token", verify)
    return calls


def counts():
    async def read():
        return await db.users.count_documents({}), await db.shops.count_documents({})
    return asyncio.run(read())


def sign_in(client, **fields):
    return client.post("/api/auth/google", json={"credential": "verified-google-token", **fields})


def test_new_google_signin_requests_password_without_account_shop_or_access_token(client, verified_google):
    response = sign_in(client)
    assert response.status_code == 200, response.text
    assert response.json() == {"password_required": True, "email": PROFILE["email"]}
    assert counts() == (0, 0)
    assert client.get("/api/employees", headers=auth("verified-google-token")).status_code == 401
    # Abandoning and starting again must not leave a partial account behind.
    assert sign_in(client).json()["password_required"] is True
    assert counts() == (0, 0)


def test_password_completion_creates_one_account_and_both_signin_methods_work(client, verified_google):
    assert sign_in(client).json()["password_required"] is True
    completed = sign_in(client, password=PASSWORD)
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["user"]["has_password"] is True
    assert "password" not in body and "password_hash" not in body["user"]
    assert counts() == (1, 1)
    assert verified_google == ["verified-google-token", "verified-google-token"]
    assert client.get("/api/employees", headers=auth(body["token"])).status_code == 200
    password_login = client.post("/api/auth/login", json={"email": PROFILE["email"], "password": PASSWORD})
    assert password_login.status_code == 200
    assert password_login.json()["user"]["user_id"] == body["user"]["user_id"]
    google_login = sign_in(client)
    assert google_login.status_code == 200
    assert google_login.json()["user"]["user_id"] == body["user"]["user_id"]
    assert counts() == (1, 1)


@pytest.mark.parametrize("password", ["", "short", "x" * 73, "é" * 40])
def test_invalid_password_does_not_create_google_account(client, verified_google, password):
    response = sign_in(client, password=password)
    assert response.status_code == 422
    assert counts() == (0, 0)


def test_completion_reverifies_google_identity_and_refuses_an_expired_credential(client, verified_google, monkeypatch):
    assert sign_in(client).json()["password_required"] is True
    def expired(_):
        raise google_auth.GoogleAuthInvalid("Google sign-in expired. Please sign in again.")
    monkeypatch.setattr(google_auth, "verify_id_token", expired)
    assert sign_in(client, password=PASSWORD).status_code == 401
    assert counts() == (0, 0)


def test_google_password_submission_never_replaces_an_existing_accounts_password(client, verified_google):
    register(client, email=PROFILE["email"], password="original-password")
    response = sign_in(client, password="different-password")
    assert response.status_code == 200, response.text
    original = client.post("/api/auth/login", json={"email": PROFILE["email"], "password": "original-password"})
    assert original.status_code == 200
    assert client.post("/api/auth/login", json={"email": PROFILE["email"], "password": "different-password"}).status_code == 401
    assert counts() == (1, 1)


def test_an_account_created_between_setup_steps_is_not_overwritten(client, verified_google):
    assert sign_in(client).json()["password_required"] is True
    first = sign_in(client, password=PASSWORD).json()
    second = sign_in(client, password="another-password")
    assert second.status_code == 200
    assert second.json()["user"]["user_id"] == first["user"]["user_id"]
    assert client.post("/api/auth/login", json={"email": PROFILE["email"], "password": PASSWORD}).status_code == 200
    assert counts() == (1, 1)
