"""Sign-up email verification.

A new account is created only after the person clicks the link emailed to them. These tests cover the
whole journey: nothing exists after sign-up, the link creates the account and signs the person in,
every way a link can be wrong, the one-minute gap between emails, and what happens when the email
service refuses to send (as it will until a sending domain is verified).
"""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from app import config, db
from app.routes import auth as auth_routes
from app.security import verify_password
from app.services import account_deletion, mailer
from tests.test_api import client  # noqa: F401 - the shared fixture

run = asyncio.run


@pytest.fixture
def mail(monkeypatch):
    """Verification switched ON, and the email service replaced by one that records what it is asked to send."""
    sent, outcome = [], {"error": None}

    async def fake(to, name, url, hours):
        sent.append({"to": to, "name": name, "url": url, "hours": hours})
        return outcome["error"]

    monkeypatch.setattr(config, "EMAIL_VERIFICATION_REQUIRED", True)
    monkeypatch.setattr(auth_routes, "send_verification_email", fake)
    return SimpleNamespace(sent=sent, outcome=outcome)


def sign_up(client, email="newshop@gmail.com", password="a-long-password", name="Aoife", shop="Main Street Deli"):
    return client.post("/api/auth/signup", json={"email": email, "password": password, "name": name, "shop_name": shop})


def token_from(message):
    return parse_qs(urlparse(message["url"]).query)["token"][0]


def verify(client, token):
    return client.post("/api/auth/verify-email", json={"token": token})


def pending(email="newshop@gmail.com"):
    return run(db.email_verifications.find_one({"email": email}))


def user_with(email):
    return run(db.users.find_one({"email": email}))


def age(email, **ago):
    """Make a pending sign-up look older: its last email, and optionally when its link runs out."""
    run(db.email_verifications.update_one({"email": email}, {"$set": {"last_sent_at": datetime.now(timezone.utc) - timedelta(**ago)}}))


def expire(email):
    """Make a sign-up's link run out. The database deletes expired records on its own, but only about once a
    minute, so for a little while an expired one can still be found: that gap is what the code's own check is for."""
    try:
        run(db.email_verifications.drop_index("ttl_email_verifications"))
    except Exception:  # noqa: BLE001 - no such index here: nothing to switch off
        pass
    run(db.email_verifications.update_one({"email": email}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}}))


class TestSigningUpSendsALinkAndCreatesNothing:
    def test_it_is_accepted_not_created(self, client, mail):
        response = sign_up(client)
        assert response.status_code == 202
        assert response.json() == {"verification_sent": True, "email": "newshop@gmail.com", "expires_in_hours": 24}

    def test_no_account_and_no_sign_in_token(self, client, mail):
        response = sign_up(client)
        assert "token" not in response.json() and "user" not in response.json()
        assert user_with("newshop@gmail.com") is None
        assert run(db.shops.count_documents({})) == 0

    def test_one_email_goes_to_that_address_with_a_link_back_to_the_site(self, client, mail):
        sign_up(client, email="NewShop@Gmail.com", name="Aoife")
        assert len(mail.sent) == 1
        message = mail.sent[0]
        assert message["to"] == "newshop@gmail.com" and message["name"] == "Aoife" and message["hours"] == 24
        assert message["url"].startswith(f"{config.FRONTEND_URL}/verify-email?token=")
        assert len(token_from(message)) >= 32

    def test_the_wait_is_kept_in_its_own_collection_with_the_link_stored_only_as_a_hash(self, client, mail):
        sign_up(client)
        record = pending()
        token = token_from(mail.sent[0])
        assert record["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
        assert token not in str(record)

    def test_the_password_is_stored_scrambled_never_as_typed(self, client, mail):
        sign_up(client, password="correct horse battery")
        record = pending()
        assert "correct horse battery" not in str(record)
        assert verify_password("correct horse battery", record["password_hash"])

    def test_the_link_runs_out_in_a_day(self, client, mail):
        sign_up(client)
        left = pending()["expires_at"]
        left = left.replace(tzinfo=timezone.utc) if left.tzinfo is None else left
        assert timedelta(hours=23, minutes=55) < left - datetime.now(timezone.utc) <= timedelta(hours=24)

    def test_cannot_sign_in_before_confirming(self, client, mail):
        sign_up(client)
        response = client.post("/api/auth/login", json={"email": "newshop@gmail.com", "password": "a-long-password"})
        # Refused either way: 401 (wrong details) or 404 where the sign-in screen names unknown addresses.
        assert response.status_code in (401, 404)
        assert "token" not in response.json()
        assert user_with("newshop@gmail.com") is None

    def test_bad_details_are_still_refused_and_nothing_is_sent(self, client, mail):
        assert sign_up(client, password="short").status_code == 422
        assert sign_up(client, email="not-an-email").status_code == 422
        assert mail.sent == [] and pending() is None


class TestClickingTheLinkCreatesTheAccount:
    def confirm(self, client, mail):
        sign_up(client)
        return verify(client, token_from(mail.sent[0]))

    def test_it_creates_the_account_and_signs_the_person_in(self, client, mail):
        response = self.confirm(client, mail)
        assert response.status_code == 201
        body = response.json()
        assert body["token"] and body["user"]["email"] == "newshop@gmail.com" and body["user"]["name"] == "Aoife"
        assert user_with("newshop@gmail.com") is not None

    def test_the_shop_is_set_up_with_the_name_they_gave(self, client, mail):
        self.confirm(client, mail)
        shop = run(db.shops.find_one({}))
        assert shop is not None and shop["name"] == "Main Street Deli"

    def test_the_token_it_returns_works(self, client, mail):
        body = self.confirm(client, mail).json()
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
        assert me.status_code == 200 and me.json()["email"] == "newshop@gmail.com"

    def test_the_password_they_chose_signs_them_in_afterwards(self, client, mail):
        self.confirm(client, mail)
        again = client.post("/api/auth/login", json={"email": "newshop@gmail.com", "password": "a-long-password"})
        assert again.status_code == 200

    def test_the_waiting_record_is_gone(self, client, mail):
        self.confirm(client, mail)
        assert pending() is None

    def test_no_password_or_hash_is_ever_sent_back(self, client, mail):
        text = self.confirm(client, mail).text
        assert "a-long-password" not in text and "password_hash" not in text

    def test_a_new_account_is_not_a_pro_account(self, client, mail):
        self.confirm(client, mail)
        assert user_with("newshop@gmail.com")["pro"] is False

    def test_using_the_same_link_twice_creates_one_account(self, client, mail):
        sign_up(client)
        token = token_from(mail.sent[0])
        assert verify(client, token).status_code == 201
        second = verify(client, token)
        assert second.status_code == 400
        assert run(db.users.count_documents({"email": "newshop@gmail.com"})) == 1

    def test_the_two_links_clicked_at_once_create_one_account(self, client, mail):
        sign_up(client)
        token = token_from(mail.sent[0])
        results = [verify(client, token).status_code for _ in range(3)]
        assert results.count(201) == 1 and run(db.users.count_documents({"email": "newshop@gmail.com"})) == 1


class TestTwoClicksAtTheSameInstant:
    def test_the_one_that_loses_the_race_creates_nothing_and_is_told_the_link_was_used(self, client, mail, monkeypatch):
        """Both look the link up and find it; only one of them manages to delete it. The other must stop."""
        sign_up(client)
        token = token_from(mail.sent[0])
        original = db.email_verifications.delete_one

        async def somebody_else_got_there_first(*args, **kwargs):
            await original(*args, **kwargs)
            return SimpleNamespace(deleted_count=0)

        monkeypatch.setattr(db.email_verifications, "delete_one", somebody_else_got_there_first)
        response = verify(client, token)
        assert response.status_code == 400 and "already been used" in response.json()["detail"]
        assert user_with("newshop@gmail.com") is None


class TestALinkThatIsWrong:
    @pytest.mark.parametrize("token", ["", "nonsense", "a" * 43, "../../etc/passwd", "x' || '1'=='1"])
    def test_an_unknown_link_is_refused_and_creates_nothing(self, client, mail, token):
        sign_up(client)
        response = verify(client, token)
        assert response.status_code == 400 and "not valid any more" in response.json()["detail"]
        assert user_with("newshop@gmail.com") is None

    def test_an_expired_link_is_refused(self, client, mail):
        sign_up(client)
        expire("newshop@gmail.com")
        response = verify(client, token_from(mail.sent[0]))
        assert response.status_code == 400 and user_with("newshop@gmail.com") is None

    def test_a_missing_token_is_a_validation_error(self, client, mail):
        assert client.post("/api/auth/verify-email", json={}).status_code == 422

    def test_a_link_for_someone_elses_sign_up_does_not_work_for_a_different_address(self, client, mail):
        sign_up(client, email="one@gmail.com")
        sign_up(client, email="two@gmail.com")
        verify(client, token_from(mail.sent[1]))
        assert user_with("two@gmail.com") is not None and user_with("one@gmail.com") is None

    def test_if_the_address_got_an_account_meanwhile_it_says_so_and_makes_no_second_one(self, client, mail):
        sign_up(client)
        token = token_from(mail.sent[0])
        run(db.users.insert_one({"user_id": "user_other", "email": "newshop@gmail.com", "name": "Someone"}))
        response = verify(client, token)
        assert response.status_code == 409 and "already registered" in response.json()["detail"]
        assert run(db.users.count_documents({"email": "newshop@gmail.com"})) == 1


class TestAnAddressThatIsAlreadyInUse:
    def test_a_registered_address_is_refused_and_no_email_is_sent(self, client, mail):
        run(db.users.insert_one({"user_id": "user_a", "email": "newshop@gmail.com", "name": "Old"}))
        response = sign_up(client)
        assert response.status_code == 409 and response.json()["detail"] == "That email is already registered"
        assert mail.sent == [] and pending() is None

    def test_capital_letters_do_not_get_round_it(self, client, mail):
        run(db.users.insert_one({"user_id": "user_a", "email": "newshop@gmail.com", "name": "Old"}))
        assert sign_up(client, email="NEWSHOP@GMAIL.COM").status_code == 409

    def test_an_account_waiting_to_be_deleted_gets_the_explanation_not_just_already_registered(self, client, mail):
        when = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
        run(db.users.insert_one({"user_id": "user_a", "email": "newshop@gmail.com", "name": "Old", "deletion_scheduled_for": when}))
        response = sign_up(client)
        assert response.status_code == 409 and response.json()["detail"] != "That email is already registered"
        assert mail.sent == []


class TestAskingAgain:
    def test_a_second_sign_up_straight_away_waits_and_sends_nothing(self, client, mail):
        sign_up(client)
        response = sign_up(client)
        assert response.status_code == 429 and "wait a minute" in response.json()["detail"]
        assert response.headers["retry-after"] == "60" and len(mail.sent) == 1

    def test_after_a_minute_a_second_sign_up_replaces_the_first(self, client, mail):
        sign_up(client, password="first-password-1", name="First")
        age("newshop@gmail.com", minutes=2)
        assert sign_up(client, password="second-password-2", name="Second").status_code == 202
        assert len(mail.sent) == 2 and run(db.email_verifications.count_documents({})) == 1
        assert verify(client, token_from(mail.sent[0])).status_code == 400
        assert verify(client, token_from(mail.sent[1])).status_code == 201
        assert client.post("/api/auth/login", json={"email": "newshop@gmail.com", "password": "second-password-2"}).status_code == 200
        assert client.post("/api/auth/login", json={"email": "newshop@gmail.com", "password": "first-password-1"}).status_code == 401

    def test_resend_sends_a_new_link_and_the_old_one_stops_working(self, client, mail):
        sign_up(client)
        age("newshop@gmail.com", minutes=2)
        response = client.post("/api/auth/resend-verification", json={"email": "newshop@gmail.com"})
        assert response.status_code == 200 and response.json()["verification_sent"] is True
        assert len(mail.sent) == 2 and token_from(mail.sent[0]) != token_from(mail.sent[1])
        assert verify(client, token_from(mail.sent[0])).status_code == 400
        assert verify(client, token_from(mail.sent[1])).status_code == 201

    def test_resend_too_soon_waits_and_sends_nothing(self, client, mail):
        sign_up(client)
        response = client.post("/api/auth/resend-verification", json={"email": "newshop@gmail.com"})
        assert response.status_code == 429 and len(mail.sent) == 1
        assert verify(client, token_from(mail.sent[0])).status_code == 201

    def test_resend_with_the_address_in_capitals_still_finds_it(self, client, mail):
        sign_up(client)
        age("newshop@gmail.com", minutes=2)
        assert client.post("/api/auth/resend-verification", json={"email": "NewShop@GMAIL.com"}).status_code == 200

    def test_resend_for_an_address_that_never_signed_up_is_refused_and_sends_nothing(self, client, mail):
        response = client.post("/api/auth/resend-verification", json={"email": "never@gmail.com"})
        assert response.status_code == 400 and "expired" in response.json()["detail"] and mail.sent == []

    def test_resend_after_the_sign_up_expired_is_refused(self, client, mail):
        sign_up(client)
        expire("newshop@gmail.com")
        age("newshop@gmail.com", minutes=2)
        response = client.post("/api/auth/resend-verification", json={"email": "newshop@gmail.com"})
        assert response.status_code == 400 and len(mail.sent) == 1

    def test_resend_keeps_the_original_name_and_password(self, client, mail):
        sign_up(client, name="Aoife", password="original-password")
        age("newshop@gmail.com", minutes=2)
        client.post("/api/auth/resend-verification", json={"email": "newshop@gmail.com"})
        assert mail.sent[1]["name"] == "Aoife"
        verify(client, token_from(mail.sent[1]))
        assert client.post("/api/auth/login", json={"email": "newshop@gmail.com", "password": "original-password"}).status_code == 200


class TestWhenTheEmailCannotBeSent:
    """Until a sending domain is verified in Resend, the provider refuses to send to anyone but the account owner."""

    def test_sign_up_says_so_and_nothing_is_stored(self, client, mail):
        mail.outcome["error"] = "Email provider rejected delivery (403)."
        response = sign_up(client)
        assert response.status_code == 503 and "could not send" in response.json()["detail"]
        assert pending() is None and user_with("newshop@gmail.com") is None

    def test_the_provider_s_reason_is_not_shown_to_the_person(self, client, mail):
        mail.outcome["error"] = "Email provider rejected delivery (403)."
        text = sign_up(client).text
        assert "403" not in text and "provider" not in text.lower() and "resend" not in text.lower()

    def test_email_not_configured_is_refused_the_same_way_and_nothing_is_created(self, client, mail):
        mail.outcome["error"] = "Email is not configured (RESEND_API_KEY is unset)."
        assert sign_up(client).status_code == 503 and user_with("newshop@gmail.com") is None

    def test_a_failed_send_does_not_wipe_an_earlier_waiting_sign_up(self, client, mail):
        sign_up(client)
        first = token_from(mail.sent[0])
        age("newshop@gmail.com", minutes=2)
        mail.outcome["error"] = "Email provider rejected delivery (403)."
        assert sign_up(client).status_code == 503
        assert verify(client, first).status_code == 201

    def test_a_failed_resend_keeps_the_old_link_working(self, client, mail):
        sign_up(client)
        age("newshop@gmail.com", minutes=2)
        mail.outcome["error"] = "Email delivery failed (ConnectError)."
        assert client.post("/api/auth/resend-verification", json={"email": "newshop@gmail.com"}).status_code == 503
        assert verify(client, token_from(mail.sent[0])).status_code == 201

    def test_after_a_failed_send_they_can_try_again_at_once(self, client, mail):
        mail.outcome["error"] = "Email provider rejected delivery (403)."
        sign_up(client)
        mail.outcome["error"] = None
        assert sign_up(client).status_code == 202


class TestSwitchedOff:
    def test_with_verification_off_sign_up_works_as_it_always_did(self, client, monkeypatch):
        monkeypatch.setattr(config, "EMAIL_VERIFICATION_REQUIRED", False)
        response = sign_up(client)
        assert response.status_code == 201 and response.json()["token"] and user_with("newshop@gmail.com") is not None
        assert pending() is None

    def test_the_test_environment_has_it_off_by_default(self):
        assert config.ENV == "test" and config.EMAIL_VERIFICATION_REQUIRED is False

    @pytest.mark.parametrize("is_production,email_on,env,expected", [
        (True, False, "production", True),      # live, with or without a key: required
        (True, True, "production", True),
        (False, True, "development", True),     # a developer who has set up email: required
        (False, False, "development", False),   # a developer with no email service: off, so the app still runs
        (True, True, "test", False),            # the test suite never needs a mailbox
        (False, True, "test", False),
    ])
    def test_the_default(self, is_production, email_on, env, expected):
        assert config._verification_default(is_production, email_on, env) is expected


class TestThePendingRecords:
    def test_they_are_unique_per_address_and_per_link_and_expire_by_themselves(self, client):
        run(db.ensure_indexes())
        info = run(db.email_verifications.index_information())
        assert {"uniq_verify_email", "uniq_verify_token_hash", "ttl_email_verifications"} <= set(info)
        assert info["ttl_email_verifications"]["expireAfterSeconds"] == 0
        assert info["uniq_verify_email"]["unique"] and info["uniq_verify_token_hash"]["unique"]

    def test_erasing_an_account_leaves_other_peoples_waiting_sign_ups_alone(self, client, mail):
        sign_up(client, email="waiting@gmail.com")
        run(db.users.insert_one({"user_id": "user_leaver", "email": "leaver@shop.ie", "name": "Leaver"}))
        run(account_deletion.erase(user_with("leaver@shop.ie")))
        assert pending("waiting@gmail.com") is not None

    def test_it_is_declared_as_not_belonging_to_an_account(self):
        assert "email_verifications" in account_deletion.NON_ACCOUNT_COLLECTIONS
        assert "email_verifications" in account_deletion.ERASURE_PLAN


class TestTheEmail:
    def test_it_has_the_link_the_hours_and_the_button_words(self):
        page = mailer.render_verification_email("Aoife", "https://roster.test/verify-email?token=abc", 24)
        assert 'href="https://roster.test/verify-email?token=abc"' in page
        assert "24 hours" in page and "Confirm my email" in page and "Hi Aoife," in page

    def test_the_name_is_made_safe(self):
        page = mailer.render_verification_email('<script>alert(1)</script>', "https://x.test/v?token=t", 24)
        assert "<script>" not in page and "&lt;script&gt;" in page

    def test_an_empty_name_still_reads_properly(self):
        assert "Hi there," in mailer.render_verification_email("", "https://x.test/v?token=t", 24)

    def test_it_says_what_to_do_if_you_did_not_sign_up(self):
        assert "didn't sign up" in mailer.render_verification_email("A", "https://x.test/v?token=t", 24)

    def test_with_no_email_service_it_reports_that_and_sends_nothing(self, monkeypatch):
        monkeypatch.setattr(mailer, "enabled", False)
        error = run(mailer.send_verification_email("a@b.ie", "A", "https://x.test/v?token=t", 24))
        assert error and "not configured" in error

    def test_with_an_email_service_it_sends_one_message_with_the_right_subject_to_the_right_person(self, monkeypatch):
        calls = []

        async def fake_send(http, semaphore, to, subject, body_html, attachments=None):
            calls.append((to, subject, body_html))
            return None

        monkeypatch.setattr(mailer, "enabled", True)
        monkeypatch.setattr(mailer, "_send_one", fake_send)
        assert run(mailer.send_verification_email("a@b.ie", "Aoife", "https://x.test/v?token=t", 24)) is None
        assert len(calls) == 1 and calls[0][0] == "a@b.ie" and calls[0][1] == "Confirm your email for Roster"
        assert "https://x.test/v?token=t" in calls[0][2]

    def test_a_refusal_from_the_provider_comes_back_as_an_error(self, monkeypatch):
        async def refuse(*args, **kwargs):
            return "Email provider rejected delivery (403)."

        monkeypatch.setattr(mailer, "enabled", True)
        monkeypatch.setattr(mailer, "_send_one", refuse)
        assert "403" in run(mailer.send_verification_email("a@b.ie", "A", "https://x.test/v?token=t", 24))
