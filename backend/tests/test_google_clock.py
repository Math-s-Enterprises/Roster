"""Real signed tokens, Google's verifier, and local certificates only."""
from datetime import datetime, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services import google_auth


@pytest.fixture(scope="module")
def signing_keys():
    return (rsa.generate_private_key(public_exponent=65537, key_size=2048),
            rsa.generate_private_key(public_exponent=65537, key_size=2048))


@pytest.fixture
def token_verifier(monkeypatch, signing_keys):
    from google.auth import _helpers
    from google.oauth2 import id_token
    now = datetime(2026, 10, 10, 12, 0, 0)
    epoch = int(now.replace(tzinfo=timezone.utc).timestamp())
    private, wrong_private = signing_keys
    public = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(_helpers, 'utcnow', lambda: now)
    monkeypatch.setattr(google_auth, 'enabled', True)
    monkeypatch.setattr(google_auth.config, 'GOOGLE_CLIENT_ID', 'our-client')
    monkeypatch.setattr(google_auth, '_request', lambda: object())
    monkeypatch.setattr(id_token, '_fetch_certs', lambda *args: {'test-key': public})

    def token(changes=None, forged=False):
        claims = {'iat': epoch, 'exp': epoch + 3600, 'aud': 'our-client',
                  'iss': 'https://accounts.google.com', 'sub': 'google-one',
                  'email': 'owner@gmail.com', 'email_verified': True, **(changes or {})}
        return jwt.encode(claims, wrong_private if forged else private,
                          algorithm='RS256', headers={'kid': 'test-key'})
    return epoch, token


@pytest.mark.parametrize('ahead', [0, 1, 5])
def test_google_accepts_only_small_clock_difference(token_verifier, ahead):
    epoch, token = token_verifier
    assert google_auth.verify_id_token(token({'iat': epoch + ahead}))['google_sub'] == 'google-one'


@pytest.mark.parametrize('changes', [
    {'iat': 6}, {'iat': 60}, {'exp': -6}, {'exp': -60},
])
def test_google_rejects_times_outside_five_second_tolerance(token_verifier, changes):
    epoch, token = token_verifier
    with pytest.raises(google_auth.GoogleAuthInvalid) as exc:
        google_auth.verify_id_token(token({name: epoch + offset for name, offset in changes.items()}))
    assert str(exc.value) == 'Google sign-in could not be verified. Please try again.'
    assert str(epoch) not in str(exc.value)


@pytest.mark.parametrize('changes,forged', [
    ({'aud': 'another-app'}, False), ({'iss': 'https://attacker.example'}, False),
    ({}, True), ({'email_verified': False}, False),
])
def test_clock_tolerance_does_not_relax_identity_checks(token_verifier, changes, forged):
    _, token = token_verifier
    with pytest.raises(google_auth.GoogleAuthInvalid):
        google_auth.verify_id_token(token(changes, forged))


def test_google_certificate_outage_is_not_reported_as_bad_credentials(token_verifier, monkeypatch):
    from google.auth.exceptions import TransportError
    from google.oauth2 import id_token
    _, token = token_verifier
    def unavailable(*args):
        raise TransportError('private provider detail')
    monkeypatch.setattr(id_token, '_fetch_certs', unavailable)
    with pytest.raises(google_auth.GoogleAuthUnavailable) as exc:
        google_auth.verify_id_token(token())
    assert 'private provider detail' not in str(exc.value)


@pytest.mark.parametrize('ahead,expected', [(1, 200), (60, 401)])
def test_google_clock_result_reaches_sign_in_api(client, token_verifier, ahead, expected):
    epoch, token = token_verifier
    response = client.post('/api/auth/google', json={'credential': token({'iat': epoch + ahead})})
    assert response.status_code == expected
    if expected == 401:
        assert response.json()['detail'] == 'Google sign-in could not be verified. Please try again.'
