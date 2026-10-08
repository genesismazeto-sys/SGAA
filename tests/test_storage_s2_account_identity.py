# coding: utf-8
"""STORAGE S2: logical Google-account identity (provider-namespaced SHA-256 of OIDC ``sub``).

A. key derivation contract: exact canonicalization, namespace, refusal instead
   of normalization, the raw ``sub`` never emitted;
B. the ID token of the authorization-code exchange: issuer / audience / expiry
   checks, value-free refusals;
C. the connect path persists the key; same-account reconnect, e-mail change,
   different account; ``test_connection`` backfills a NULL key from a trusted
   userinfo ``sub`` and refuses a different account;
D. credential resolution by logical key: disconnected -> ``None``, two active
   rows for one account -> fail closed.

No Google or Supabase request is made: every provider boundary is stubbed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import sqlite3
import time

import pytest
from cryptography.fernet import Fernet
from flask import Flask

from app import cloud_connections
from app.cloud_account_identity import (
    AccountIdentityError,
    google_account_key,
    google_subject_from_id_token,
    is_provider_account_key,
    provider_account_key,
)
from app.prod1_schema import bootstrap_prod1_schema
from app.services import google_drive_service

SUB_A = "108555000111222333444"
SUB_B = "117000999888777666555"
CLIENT = "client-1.apps.googleusercontent.com"


def _id_token(**claims):
    payload = {"iss": "https://accounts.google.com", "aud": CLIENT, "sub": SUB_A, "exp": time.time() + 3600}
    payload.update(claims)
    payload = {k: v for k, v in payload.items() if v is not None}

    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256', 'kid': 'k'})}.{part(payload)}.c2lnbmF0dXJl"


# --- A. derivation ---------------------------------------------------------------------


def test_key_is_the_provider_namespaced_sha256_of_the_exact_subject():
    key = google_account_key(SUB_A)
    assert key == hashlib.sha256(b"google\x00" + SUB_A.encode("ascii")).hexdigest()
    assert is_provider_account_key(key) and key == key.lower() and len(key) == 64
    assert google_account_key(SUB_A) == key  # deterministic: same account, same key
    assert google_account_key(SUB_B) != key
    assert key != hashlib.sha256(SUB_A.encode()).hexdigest()  # the namespace participates
    assert key != hashlib.sha256(b"google" + SUB_A.encode()).hexdigest()  # the NUL separator participates
    assert google_account_key("AbC") != google_account_key("abc")  # case-sensitive, never folded
    assert SUB_A not in key


@pytest.mark.parametrize("subject", ["", " 1085", "1085 ", "10 85", "1085\n", "1085\x00", "subé", "1" * 256,
                                     None, 1085])
def test_subjects_needing_normalization_are_refused_not_repaired(subject):
    with pytest.raises(AccountIdentityError) as caught:
        google_account_key(subject)
    assert caught.value.code == "ACCOUNT_IDENTITY_SUBJECT_INVALID"
    assert str(subject) not in str(caught.value) or subject in ("",)


def test_only_supported_providers_have_keys():
    with pytest.raises(AccountIdentityError) as caught:
        provider_account_key("onedrive", SUB_A)
    assert caught.value.code == "ACCOUNT_IDENTITY_PROVIDER_UNSUPPORTED"


# --- B. ID token -----------------------------------------------------------------------


def test_id_token_subject_is_accepted_only_for_google_our_audience_and_unexpired():
    assert google_subject_from_id_token(_id_token(), audience=CLIENT) == SUB_A
    assert google_subject_from_id_token(_id_token(iss="accounts.google.com", aud=[CLIENT, "x"]),
                                        audience=CLIENT) == SUB_A
    assert google_subject_from_id_token(_id_token(azp=CLIENT), audience=CLIENT) == SUB_A
    cases = {
        "ACCOUNT_IDENTITY_ISSUER_INVALID": _id_token(iss="https://evil.example"),
        "ACCOUNT_IDENTITY_AUDIENCE_INVALID": _id_token(aud="someone-else"),
        "ACCOUNT_IDENTITY_AUTHORIZED_PARTY_INVALID": _id_token(aud=[CLIENT, "x"], azp="x"),
        "ACCOUNT_IDENTITY_TOKEN_EXPIRED": _id_token(exp=time.time() - 3600),
        "ACCOUNT_IDENTITY_SUBJECT_INVALID": _id_token(sub=" " + SUB_A),
        "ACCOUNT_IDENTITY_TOKEN_INVALID": "a.!!!notbase64.c",
        "ACCOUNT_IDENTITY_TOKEN_MISSING": None,
    }
    for code, token in cases.items():
        with pytest.raises(AccountIdentityError) as caught:
            google_subject_from_id_token(token, audience=CLIENT)
        assert caught.value.code == code
        assert SUB_A not in str(caught.value) and SUB_A not in repr(caught.value)
    with pytest.raises(AccountIdentityError) as caught:
        google_subject_from_id_token(_id_token(), audience="")
    assert caught.value.code == "ACCOUNT_IDENTITY_AUDIENCE_INVALID"


def test_id_token_extractor_is_used_only_by_the_server_side_code_exchange():
    """IAsup binding: the signature-free path is valid only for the direct token-endpoint response."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    callers = sorted(
        path.relative_to(root).as_posix()
        for base in ("app", "services", "tools")
        for path in (root / base).rglob("*.py")
        if "google_subject_from_id_token(" in path.read_text(encoding="utf-8", errors="replace")
        and path.name != "cloud_account_identity.py"
    )
    assert callers == ["app/services/google_drive_service.py"]
    source = (root / "app/services/google_drive_service.py").read_text(encoding="utf-8-sig")
    exchange = source.split("def exchange_code_for_token(", 1)[1].split("\ndef ", 1)[0]
    assert "google_subject_from_id_token(" in exchange and "flow.fetch_token(code=code)" in exchange
    assert source.count("google_subject_from_id_token(") == 1
    # No nonce is sent by the authorization request, so none is (or may be) required.
    assert "nonce" not in source


def _stub_exchange(monkeypatch, credentials_id_token):
    class FakeCredentials:
        token = "access-value"
        refresh_token = "refresh-value"
        token_uri = "https://oauth2.googleapis.com/token"
        scopes = ["scope-a"]
        expiry = None
        id_token = credentials_id_token

    class FakeFlow:
        credentials = FakeCredentials()

        @classmethod
        def from_client_config(cls, config, scopes, **kwargs):
            return cls()

        def fetch_token(self, *, code):
            return None

    monkeypatch.setattr(google_drive_service, "_import_google_dependencies",
                        lambda: (object, object, FakeFlow, object, object))
    monkeypatch.setattr(google_drive_service, "_build_client_config", lambda uri: {"web": {"client_id": CLIENT}})
    monkeypatch.setattr(google_drive_service, "_get_scopes", lambda: ["scope-a"])
    monkeypatch.setattr(google_drive_service, "get_redirect_uri", lambda default_uri=None: "http://localhost/cb")
    monkeypatch.setattr(google_drive_service, "_fetch_email", lambda credentials: "admin@example.com")


def test_exchange_returns_the_key_and_refuses_a_connect_without_identity(monkeypatch, caplog):
    _stub_exchange(monkeypatch, _id_token())
    token_json, email, key = google_drive_service.exchange_code_for_token(code="c", code_verifier="v",
                                                                         is_debug=True)
    assert (email, key) == ("admin@example.com", google_account_key(SUB_A))
    assert SUB_A not in token_json and "id_token" not in json.loads(token_json)
    for bad in (None, _id_token(aud="other-client")):
        _stub_exchange(monkeypatch, bad)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(google_drive_service.GoogleDriveServiceError) as caught:
                google_drive_service.exchange_code_for_token(code="c", code_verifier="v", is_debug=True)
        assert caught.value.debug_code.startswith("ACCOUNT_IDENTITY_")
        assert caught.value.__cause__ is None
        assert SUB_A not in str(caught.value) and SUB_A not in caplog.text


# --- C/D. persistence and resolution ---------------------------------------------------


@pytest.fixture
def cloud(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, APP_ENV="testing")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setattr(cloud_connections, "ensure_cloud_backup_schema", lambda conn: None)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)  # the real v14 cloud_accounts
    with app.app_context():
        yield conn


def _rows(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT id, account_email, active, provider_account_key FROM cloud_accounts ORDER BY id")]


def test_connect_persists_key_reconnect_and_email_change_keep_it_other_account_differs(cloud):
    key_a, key_b = google_account_key(SUB_A), google_account_key(SUB_B)
    cloud_connections.set_active_cloud_account(cloud, "google", "a@example.com", '{"t":1}', provider_account_key=key_a)
    cloud_connections.set_active_cloud_account(cloud, "google", "a@example.com", '{"t":2}', provider_account_key=key_a)
    cloud_connections.set_active_cloud_account(cloud, "google", "renamed@example.com", '{"t":3}',
                                               provider_account_key=key_a)
    assert _rows(cloud) == [(1, "a@example.com", 0, key_a), (2, "a@example.com", 0, key_a),
                            (3, "renamed@example.com", 1, key_a)]
    # Reconnect = new credential row, same LOGICAL identity -> resolves to the newest row.
    assert cloud_connections.resolve_active_account_id_by_key(cloud, "google", key_a) == 3
    cloud_connections.set_active_cloud_account(cloud, "google", "b@example.com", '{"t":4}', provider_account_key=key_b)
    assert _rows(cloud)[-1] == (4, "b@example.com", 1, key_b)
    # Account A is now disconnected: no credential, nothing wrong with its objects.
    assert cloud_connections.resolve_active_account_id_by_key(cloud, "google", key_a) is None
    assert cloud_connections.resolve_active_account_id_by_key(cloud, "google", key_b) == 4
    # The key is never derived from an e-mail; legacy rows stay NULL.
    cloud_connections.set_active_cloud_account(cloud, "onedrive", "x@example.com", '{"t":5}')
    assert _rows(cloud)[-1][3] is None
    for provider, key in (("onedrive", key_a), ("google", "A" * 64), ("google", SUB_A)):
        with pytest.raises(cloud_connections.CloudConnectionError) as caught:
            cloud_connections.set_active_cloud_account(cloud, provider, "x", '{"t":6}', provider_account_key=key)
        assert caught.value.debug_code.startswith("ACCOUNT_IDENTITY_") and SUB_A not in str(caught.value)


def test_two_active_rows_for_one_logical_account_fail_closed(cloud):
    key_a = google_account_key(SUB_A)
    cloud_connections.set_active_cloud_account(cloud, "google", "a@example.com", '{"t":1}', provider_account_key=key_a)
    cloud.execute("INSERT INTO cloud_accounts(provider, token_json, active, provider_account_key) "
                  "VALUES ('google', 'x', 1, ?)", (key_a,))
    with pytest.raises(cloud_connections.CloudConnectionError) as caught:
        cloud_connections.resolve_active_account_id_by_key(cloud, "google", key_a)
    assert caught.value.debug_code == "ACCOUNT_IDENTITY_AMBIGUOUS"
    with pytest.raises(cloud_connections.CloudConnectionError):
        cloud_connections.resolve_active_account_id_by_key(cloud, "google", "not-a-key")


def _stub_userinfo(monkeypatch, userinfo):
    monkeypatch.setattr(cloud_connections, "get_authenticated_access_token",
                        lambda conn, provider: ("access", "a@example.com"))
    monkeypatch.setattr(cloud_connections.low_level_cloud, "google_userinfo", lambda token: dict(userinfo))


def test_test_connection_backfills_a_legacy_null_key_and_refuses_another_account(cloud, monkeypatch):
    cloud_connections.set_active_cloud_account(cloud, "google", "a@example.com", '{"t":1}')  # legacy: no key
    _stub_userinfo(monkeypatch, {"email": "a@example.com"})  # no sub -> nothing established, no failure
    cloud_connections.test_connection(cloud, "google")
    assert _rows(cloud)[-1][3] is None
    _stub_userinfo(monkeypatch, {"email": "a@example.com", "sub": SUB_A})
    cloud_connections.test_connection(cloud, "google")
    assert _rows(cloud)[-1][3] == google_account_key(SUB_A)
    _stub_userinfo(monkeypatch, {"email": "a@example.com", "sub": SUB_B})
    with pytest.raises(cloud_connections.CloudConnectionError) as caught:
        cloud_connections.test_connection(cloud, "google")
    assert caught.value.debug_code == "ACCOUNT_IDENTITY_MISMATCH"
    assert SUB_B not in str(caught.value) and SUB_A not in str(caught.value)
    assert _rows(cloud)[-1][3] == google_account_key(SUB_A)  # never silently re-pointed
