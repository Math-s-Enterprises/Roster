"""Failed sign-in responses must not disclose whether an address is registered."""
from tests.test_api import client, register  # noqa: F401 - the shared fixtures

INVALID_CREDENTIALS = "Invalid email or password"


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


class TestAnAddressWithNoAccount:
    def test_it_gets_the_same_generic_credentials_error(self, client):
        register(client)
        response = login(client, "xyz@gmail.com", "whatever-password")
        assert response.status_code == 401
        assert response.json()["detail"] == INVALID_CREDENTIALS

    def test_whatever_the_password_it_says_the_same(self, client):
        for password in ("x", "password123", "a much longer password than anyone has"):
            assert login(client, "xyz@gmail.com", password).json()["detail"] == INVALID_CREDENTIALS

    def test_capital_letters_do_not_matter(self, client):
        register(client)
        assert login(client, "XYZ@Gmail.com", "pw-123456").json()["detail"] == INVALID_CREDENTIALS

    def test_nothing_is_issued(self, client):
        response = login(client, "xyz@gmail.com", "pw-123456")
        assert "token" not in response.text and "user" not in response.json()


class TestARealAddressWithTheWrongPassword:
    def test_it_gets_the_existing_answer(self, client):
        register(client)
        response = login(client, "owner@example.com", "wrong-password")
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"

    def test_capital_letters_in_the_address_still_find_the_account(self, client):
        register(client)
        response = login(client, "OWNER@Example.com", "wrong-password")
        assert response.status_code == 401 and response.json()["detail"] == "Invalid email or password"

    def test_the_right_password_still_signs_in(self, client):
        register(client)
        response = login(client, "owner@example.com", "password123")
        assert response.status_code == 200 and response.json()["token"]

    def test_an_account_with_no_password_is_a_real_address_too(self, client):
        """A Google-only account has an email but no password: that is 'does not match', not 'no such email'."""
        import asyncio
        from app import db

        async def add():
            await db.users.insert_one({"user_id": "user_google_only", "email": "gina@gmail.com", "name": "Gina", "google_sub": "sub-1"})
        asyncio.run(add())
        response = login(client, "gina@gmail.com", "any-password")
        assert response.status_code == 401 and response.json()["detail"] == "Invalid email or password"


class TestTheTwoAnswersAreIdentical:
    def test_an_unknown_and_a_wrong_password_do_not_disclose_account_existence(self, client):
        register(client)
        unknown = login(client, "xyz@gmail.com", "password123")
        wrong = login(client, "owner@example.com", "wrong-password")
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json()

    def test_a_malformed_request_is_still_a_validation_error(self, client):
        assert client.post("/api/auth/login", json={"email": "not-an-email", "password": "x"}).status_code == 422
        assert client.post("/api/auth/login", json={}).status_code == 422
