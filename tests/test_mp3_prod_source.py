# coding: utf-8
"""MP-3 SPEC A17 finding 3: the one way an operator tool reaches the PROD database (``tools/prod_source.py``).

The ledger and the governed backup decide whether a database IS production from the connection itself;
that is evidence only if the connection reached the provider.  These tests pin every refusal without a
network: hidden libpq routing inputs, URLs that could reach another server, a replaced CA, a connection
that did not verify, a connection that proves no tenant or no cluster, and the second channel (the
project's storage API) the qualification compares against.  The live lane (``test_mp3_live_db``) proves
the same against Supabase DEV.
"""

from __future__ import annotations

import datetime
import hashlib
from urllib.parse import unquote

import pytest

from app import hosting
from tools import prod_source as ps

REF = "abcdefghijklmnopqrst"
POOLER = "aws-0-us-east-1.pooler.supabase.com"
GOOD_URL = f"postgresql://postgres.{REF}@{POOLER}:5432/postgres"


def _code(call, *args, **kwargs):
    with pytest.raises(ps.Refused) as caught:
        call(*args, **kwargs)
    return caught.value.code


# ---- the URL ------------------------------------------------------------------------------------------------


def test_the_verified_url_is_the_operators_endpoint_verified_against_the_pinned_ca():
    from psycopg.conninfo import conninfo_to_dict

    for url in (GOOD_URL, GOOD_URL + "?sslmode=require", GOOD_URL + "?sslmode=verify-full"):
        params = conninfo_to_dict(ps.verified_url(url))
        assert params["host"] == POOLER and params["port"] == "5432" and params["dbname"] == "postgres"
        assert params["user"] == f"postgres.{REF}" and params["sslmode"] == "verify-full"
        assert unquote(params["sslrootcert"]) == str(ps.PINNED_CA_FILE)
        assert "password" not in params


@pytest.mark.parametrize("url,code", [
    ("", "SOURCE_REQUIRED"),
    (None, "SOURCE_REQUIRED"),
    ("mysql://x@h/db", "SOURCE_NOT_POSTGRESQL"),
    (f"postgresql://postgres.{REF}:secret@{POOLER}:5432/postgres", "SOURCE_URL_CONTAINS_PASSWORD"),
    (GOOD_URL + "?password=secret", "SOURCE_URL_CONTAINS_PASSWORD"),
    # every libpq input that could send the same URL elsewhere, or weaken how it is verified
    (GOOD_URL + "?hostaddr=127.0.0.1", "SOURCE_URL_PARAMETER_REFUSED"),
    (GOOD_URL + "?service=prod", "SOURCE_URL_PARAMETER_REFUSED"),
    (GOOD_URL + "?servicefile=x", "SOURCE_URL_INVALID"),  # not even a parameter of this libpq: refused
    (GOOD_URL + "?host=localhost", "SOURCE_NOT_THE_SESSION_POOLER"),
    (GOOD_URL + "?options=-c%20search_path%3Dx", "SOURCE_URL_PARAMETER_REFUSED"),
    (GOOD_URL + "?target_session_attrs=any", "SOURCE_URL_PARAMETER_REFUSED"),
    (GOOD_URL + "?sslrootcert=other.crt", "SOURCE_URL_PARAMETER_REFUSED"),
    (GOOD_URL + "?sslmode=disable", "SOURCE_URL_PARAMETER_REFUSED"),
    (GOOD_URL + "?sslmode=prefer", "SOURCE_URL_PARAMETER_REFUSED"),
    (GOOD_URL + "?sslnegotiation=direct", "SOURCE_URL_PARAMETER_REFUSED"),
    (f"postgresql://postgres.{REF}@{POOLER},evil.example:5432/postgres", "SOURCE_URL_AMBIGUOUS"),
    # not the session pooler of a Supabase region
    (f"postgresql://postgres.{REF}@{POOLER}:6543/postgres", "SOURCE_NOT_THE_SESSION_POOLER"),
    (f"postgresql://postgres.{REF}@{POOLER}/postgres", "SOURCE_NOT_THE_SESSION_POOLER"),
    (f"postgresql://postgres@db.{REF}.supabase.co:5432/postgres", "SOURCE_NOT_THE_SESSION_POOLER"),
    ("postgresql://sgaa@127.0.0.1:5432/scratch", "SOURCE_NOT_THE_SESSION_POOLER"),
    (f"postgresql://postgres.{REF}@pooler.supabase.com.evil.example:5432/postgres", "SOURCE_NOT_THE_SESSION_POOLER"),
    # no tenant: the pooler would not say which project it authenticated
    (f"postgresql://postgres@{POOLER}:5432/postgres", "SOURCE_NO_TENANT"),
    (f"postgresql://postgres.short@{POOLER}:5432/postgres", "SOURCE_NO_TENANT"),
    (f"postgresql://postgres.{REF}@{POOLER}:5432/", "SOURCE_URL_INVALID"),
])
def test_a_url_that_could_reach_another_server_than_it_shows_is_refused(url, code):
    assert _code(ps.verified_url, url) == code


# ---- the environment -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ps.ROUTING_ENVIRONMENT)
def test_every_hidden_libpq_routing_or_tls_input_is_refused_by_name(name):
    with pytest.raises(ps.Refused) as caught:
        ps.refuse_routing_environment({name: "x"})
    assert caught.value.code == "SOURCE_ENV_ROUTING" and caught.value.detail == name


def test_the_routing_list_covers_the_inputs_the_review_named_and_credentials_stay_usable():
    assert {"PGHOSTADDR", "PGHOST", "PGSERVICE", "PGSERVICEFILE", "PGPORT", "PGUSER", "PGDATABASE", "PGOPTIONS",
            "PGSSLMODE", "PGSSLROOTCERT", "PGSYSCONFDIR"} <= set(ps.ROUTING_ENVIRONMENT)
    ps.refuse_routing_environment({"PGPASSWORD": "x", "PGPASSFILE": "y", "PGCONNECT_TIMEOUT": "9", "PGAPPNAME": "z",
                                   "PGHOST": "  "})  # credentials, timeouts and blank values route nothing


def test_connect_refuses_a_routing_variable_before_any_connection(monkeypatch):
    import psycopg

    monkeypatch.setenv("PGHOSTADDR", "127.0.0.1")
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("connected")))
    assert _code(ps.connect, GOOD_URL) == "SOURCE_ENV_ROUTING"


# ---- the pinned CA ---------------------------------------------------------------------------------------------


def test_the_committed_ca_is_the_pinned_supabase_root():
    import ssl

    der = ssl.PEM_cert_to_DER_cert(ps.PINNED_CA_FILE.read_text(encoding="ascii").strip())
    assert hashlib.sha256(der).hexdigest() == ps.PINNED_CA_SHA256 == ps.PINNED_CA_SHA256.lower()
    assert ps.pinned_ca() == ps.PINNED_CA_FILE


def _self_signed_pem() -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Supabase Root 2021 CA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def test_a_replaced_or_extended_ca_file_is_refused(tmp_path, monkeypatch):
    genuine = ps.PINNED_CA_FILE.read_text(encoding="ascii")
    impostor = tmp_path / "ca.crt"
    impostor.write_text(_self_signed_pem(), encoding="ascii")  # same name, another key
    monkeypatch.setattr(ps, "PINNED_CA_FILE", impostor)
    assert _code(ps.pinned_ca) == "SOURCE_CA_PIN_MISMATCH"
    assert _code(ps.verified_url, GOOD_URL) == "SOURCE_CA_PIN_MISMATCH"
    bundle = tmp_path / "bundle.crt"
    bundle.write_text(genuine + _self_signed_pem(), encoding="ascii")  # the pinned root plus another one
    monkeypatch.setattr(ps, "PINNED_CA_FILE", bundle)
    assert _code(ps.pinned_ca) == "SOURCE_CA_UNREADABLE"
    monkeypatch.setattr(ps, "PINNED_CA_FILE", tmp_path / "missing.crt")
    assert _code(ps.pinned_ca) == "SOURCE_CA_UNREADABLE"


# ---- the connection ----------------------------------------------------------------------------------------------


class _Info:
    def __init__(self, settings):
        self._settings = settings

    def get_parameters(self):
        return dict(self._settings)


class _Conn:
    def __init__(self, ssl_in_use=True, settings=None):
        self.pgconn = type("P", (), {"ssl_in_use": ssl_in_use})()
        self.info = _Info(settings if settings is not None else
                          {"sslmode": "verify-full", "sslrootcert": str(ps.PINNED_CA_FILE)})
        self.closed = False

    def close(self):
        self.closed = True


@pytest.mark.parametrize("conn,ok", [
    (_Conn(), True),
    (_Conn(ssl_in_use=False), False),
    (_Conn(settings={"sslmode": "require", "sslrootcert": str(ps.PINNED_CA_FILE)}), False),
    (_Conn(settings={"sslmode": "verify-full", "sslrootcert": "other.crt"}), False),
    (_Conn(settings={"sslmode": "verify-full"}), False),
])
def test_a_connection_is_used_only_when_it_reports_tls_verified_against_the_pinned_ca(monkeypatch, conn, ok):
    import psycopg

    for name in ps.ROUTING_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    seen = {}

    def fake_connect(url, **kwargs):
        seen["url"], seen["kwargs"] = url, kwargs
        return conn

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    if ok:
        assert ps.connect(GOOD_URL) is conn
        assert "sslmode=verify-full" in seen["url"] and seen["kwargs"]["autocommit"] is True
    else:
        assert _code(ps.connect, GOOD_URL) == "SOURCE_TLS_NOT_VERIFIED" and conn.closed


@pytest.mark.parametrize("message,code", [
    ("SSL error: certificate verify failed", "SOURCE_TLS_NOT_VERIFIED"),
    ("server certificate for \"x\" does not match host name", "SOURCE_TLS_NOT_VERIFIED"),
    ("connection refused", "SOURCE_UNREACHABLE"),
])
def test_a_connection_that_does_not_verify_is_refused_by_class_never_by_message(monkeypatch, message, code):
    import psycopg

    for name in ps.ROUTING_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)

    def fail(url, **kwargs):
        raise psycopg.OperationalError(message)

    monkeypatch.setattr(psycopg, "connect", fail)
    with pytest.raises(ps.Refused) as caught:
        ps.connect(GOOD_URL)
    assert caught.value.code == code and message not in str(caught.value)


@pytest.mark.parametrize("facts,code", [
    ({"login_user": "postgres", "host": POOLER}, "SOURCE_NO_TENANT"),
    ({"login_user": "sgaa", "host": "127.0.0.1"}, "SOURCE_NO_TENANT"),
    ({"system_identifier": None}, "DATABASE_IDENTITY_UNPROVEN"),
])
def test_a_verified_connection_must_still_prove_its_tenant_and_its_cluster(monkeypatch, facts, code):
    base = {"database": "postgres", "user": "postgres", "login_user": f"postgres.{REF}", "host": POOLER,
            "port": "5432", "system_identifier": "7400000000000000001"}
    monkeypatch.setattr(hosting, "database_source", lambda conn: dict(base, **facts))
    assert _code(ps.observe, object()) == code
    monkeypatch.setattr(hosting, "database_source", lambda conn: dict(base))
    seen = ps.observe(object())
    assert seen.identity == hosting.source_identity_sha256(base) and seen.project_sha256 == hosting.project_sha256(REF)


# ---- the second channel: the project's own storage API -----------------------------------------------------------


@pytest.mark.parametrize("url,code", [
    (f"https://{REF}.supabase.co", None),
    ("https://storage.example.org", "STORE_NOT_A_PROJECT"),
    (f"https://{REF}.supabase.co:8443", "STORE_NOT_A_PROJECT"),
    ("http://localhost:54321", "STORE_NOT_A_PROJECT"),
    ("", "STORE_NOT_CONFIGURED"),
])
def test_the_store_names_the_project_only_by_its_own_address(url, code):
    environ = {"SUPABASE_URL": url}
    if code is None:
        assert ps.store_project_sha256(environ) == hosting.project_sha256(REF)
    else:
        assert _code(ps.store_project_sha256, environ) == code


class _Session:
    def __init__(self, status, payload):
        self.status, self.payload, self.calls = status, payload, []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        status, payload = self.status, self.payload
        return type("R", (), {"status_code": status, "json": lambda self: payload})()


def test_the_projects_api_lists_its_buckets_with_the_secret_key_and_never_sends_it_as_a_bearer():
    environ = {"SUPABASE_URL": f"https://{REF}.supabase.co", "SUPABASE_SECRET_KEY": "sb_secret_" + "k" * 30,
               "SGAA_STORAGE_BUCKET": "sgaa-documentos"}
    session = _Session(200, [{"id": "sgaa-documentos", "created_at": "2026-10-01T00:00:00.123Z"}])
    assert ps.store_buckets(environ, session=session) == frozenset({("sgaa-documentos", "2026-10-01T00:00:00")})
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("GET", f"https://{REF}.supabase.co/storage/v1/bucket")
    assert "Authorization" not in kwargs["headers"] and kwargs["allow_redirects"] is False
    for status, payload in ((401, {"message": "no"}), (200, {"not": "a list"}), (200, [{"id": "x"}])):
        assert _code(ps.store_buckets, environ, session=_Session(status, payload)) == "STORE_UNREADABLE"


def test_the_databases_buckets_are_compared_by_id_and_creation_second():
    class _Rows:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, sql):
            assert "storage.buckets" in sql
            return self

        def fetchall(self):
            return self.rows

    moment = datetime.datetime(2026, 10, 1, 0, 0, 0, 999999, tzinfo=datetime.timezone.utc)
    assert ps.database_buckets(_Rows([("sgaa-documentos", moment)])) == frozenset(
        {("sgaa-documentos", "2026-10-01T00:00:00")})

    class _Broken:
        def execute(self, sql):
            raise RuntimeError("no storage schema")

    assert _code(ps.database_buckets, _Broken()) == "DATABASE_BUCKETS_UNREADABLE"
