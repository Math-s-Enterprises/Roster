"""Launch boundary regressions using the isolated API fixture."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from tests.test_api import client, register, auth  # noqa: F401


@pytest.mark.parametrize('path,limit', [('login', 20), ('google', 20), ('signup', 5),
                                      ('forgot-password', 5), ('reset-password', 10)])
def test_auth_attempts_are_limited_even_with_invalid_payload(client, path, limit):
    for _ in range(limit):
        assert client.post('/api/auth/' + path, json={}).status_code == 422
    response = client.post('/api/auth/' + path, json={})
    assert response.status_code == 429
    assert int(response.headers['Retry-After']) > 0
    assert client.post('/api/auth/' + path, json={},
                       headers={'X-Forwarded-For': '192.0.2.99'}).status_code == 429


def test_rate_limit_uses_shared_storage_and_expires(client, monkeypatch):
    from app import db
    from app.services import auth_rate_limit as limiter
    start = (int(limiter.time.time()) // 900 + 2) * 900
    monkeypatch.setattr(limiter.time, 'time', lambda: start)
    for _ in range(5):
        client.post('/api/auth/forgot-password', json={'email': 'absent@example.com'})
    assert client.post('/api/auth/forgot-password', json={}).status_code == 429
    row = asyncio.run(db.auth_rate_limits.find_one({}))
    assert 'testclient' not in row['_id']
    assert row['count'] == 6
    monkeypatch.setattr(limiter.time, 'time', lambda: start + 900)
    assert client.post('/api/auth/forgot-password', json={}).status_code == 422


def test_rate_limit_failure_does_not_disable_protection(monkeypatch):
    from app import db
    from app.services.auth_rate_limit import check_auth_rate_limit
    from pymongo.errors import ConnectionFailure
    monkeypatch.setattr(db.auth_rate_limits, 'find_one_and_update',
                        AsyncMock(side_effect=ConnectionFailure()))
    request = Request({'type': 'http', 'method': 'POST', 'path': '/api/auth/login',
                       'client': ('192.0.2.1', 1000), 'headers': []})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(check_auth_rate_limit(request))
    assert exc.value.status_code == 503


def test_concurrent_attempts_share_a_bucket_but_different_clients_do_not(client):
    from app.services.auth_rate_limit import check_auth_rate_limit
    async def attempt(address):
        request = Request({'type': 'http', 'method': 'POST', 'path': '/api/auth/signup',
                           'client': (address, 1000), 'headers': []})
        try:
            await check_auth_rate_limit(request)
            return 200
        except HTTPException as exc:
            return exc.status_code
    async def run():
        results = await asyncio.gather(*(attempt('192.0.2.1') for _ in range(8)))
        assert results.count(200) == 5
        assert results.count(429) == 3
        assert await attempt('192.0.2.2') == 200
    asyncio.run(run())


def google(client, monkeypatch, **changes):
    from app.services import google_auth
    profile = {'email': 'owner@example.com', 'name': 'Owner', 'picture': None,
               'google_sub': 'google-one', 'email_authoritative': False, **changes}
    monkeypatch.setattr(google_auth, 'verify_id_token', lambda _: profile)
    return client.post('/api/auth/google', json={
        'credential': 'verified-by-test', 'password': 'google-signup-password',
    })


def test_third_party_email_cannot_take_over_password_account(client, monkeypatch):
    register(client)
    assert google(client, monkeypatch).status_code == 401
    assert client.post('/api/auth/login', json={
        'email': 'owner@example.com', 'password': 'password123'}).status_code == 200


def test_authoritative_email_links_but_other_subject_cannot_replace_it(client, monkeypatch):
    register(client)
    linked = google(client, monkeypatch, email_authoritative=True)
    assert linked.status_code == 200
    assert google(client, monkeypatch, google_sub='google-other',
                  email_authoritative=True).status_code == 401
    assert google(client, monkeypatch).json()['user']['user_id'] == linked.json()['user']['user_id']


def test_google_subject_remains_identity_when_email_changes(client, monkeypatch):
    first = google(client, monkeypatch)
    assert first.status_code == 200
    second = google(client, monkeypatch, email='changed@example.com')
    assert second.status_code == 200
    assert second.json()['user']['user_id'] == first.json()['user']['user_id']


def test_concurrent_signup_still_requires_safe_google_link(client, monkeypatch):
    from app import db
    from pymongo.errors import DuplicateKeyError
    register(client)
    original = db.users.find_one
    calls = 0
    async def raced_find(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return None
        return await original(*args, **kwargs)
    monkeypatch.setattr(db.users, 'find_one', raced_find)
    monkeypatch.setattr(db.users, 'insert_one', AsyncMock(side_effect=DuplicateKeyError('race')))
    assert google(client, monkeypatch).status_code == 401


def test_google_link_refuses_identity_changed_during_update(client, monkeypatch):
    from app import db
    from pymongo.results import UpdateResult
    register(client)
    monkeypatch.setattr(db.users, 'update_one',
                        AsyncMock(return_value=UpdateResult({'n': 0, 'nModified': 0}, True)))
    assert google(client, monkeypatch, email_authoritative=True).status_code == 409


def test_google_subject_uniqueness_is_enforced_by_database(client):
    from app import db
    from pymongo.errors import DuplicateKeyError
    async def run():
        await db.users.insert_one({'email': 'one@example.com', 'user_id': 'one', 'google_sub': 'same'})
        with pytest.raises(DuplicateKeyError):
            await db.users.insert_one({'email': 'two@example.com', 'user_id': 'two', 'google_sub': 'same'})
    asyncio.run(run())


@pytest.mark.parametrize('claims,expected', [({'email': 'person@gmail.com'}, True),
    ({'email': 'person@shop.ie', 'hd': 'shop.ie'}, True), ({'email': 'person@external.ie'}, False)])
def test_google_authority_comes_from_verified_claims(monkeypatch, claims, expected):
    from app.services import google_auth
    from google.oauth2 import id_token
    monkeypatch.setattr(google_auth, 'enabled', True)
    monkeypatch.setattr(google_auth, '_request', lambda: object())
    monkeypatch.setattr(id_token, 'verify_oauth2_token', lambda *a, **k: {
        'iss': 'https://accounts.google.com', 'sub': 'google-one',
        'email_verified': True, **claims})
    assert google_auth.verify_id_token('token')['email_authoritative'] is expected


def test_google_missing_subject_is_rejected(monkeypatch):
    from app.services import google_auth
    from google.oauth2 import id_token
    monkeypatch.setattr(google_auth, 'enabled', True)
    monkeypatch.setattr(google_auth, '_request', lambda: object())
    monkeypatch.setattr(id_token, 'verify_oauth2_token', lambda *a, **k: {
        'iss': 'https://accounts.google.com', 'email': 'person@gmail.com', 'email_verified': True})
    with pytest.raises(google_auth.GoogleAuthInvalid):
        google_auth.verify_id_token('token')


@pytest.mark.parametrize('path,limit', [('/api/imports', 25 * 1024 * 1024),
    ('/api/employees/contacts/preview', 5 * 1024 * 1024)])
def test_oversized_upload_is_bounded_before_parsing(client, monkeypatch, path, limit):
    from starlette.datastructures import UploadFile
    token = register(client)
    sizes = []
    async def oversized(self, size=-1):
        sizes.append(size)
        return b'x' * (limit + 1)
    monkeypatch.setattr(UploadFile, 'read', oversized)
    response = client.post(path, headers=auth(token), files={'file': ('roster.csv', b'x', 'text/csv')})
    assert response.status_code == 413
    assert sizes == [limit + 1]


