# coding: utf-8
"""MP-2 slice 1: the hosted-runtime contract (no database required).

``app.hosting`` declares the mode and its startup blockers; ``create_app``
honours them and touches no disk; the machine secret store is never read or
written when hosted; PostgreSQL connections are time-bounded.  Each node has
a control that fails if the defect it guards returns.
"""

from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.db as app_db
from app import hosting, hosting_cli
from app.hosting import Blocker, HostingConfigurationError
from tests.hosting_tripwire import FilesystemTripwire

REPO_ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "SENTINEL-VALUE-MUST-NEVER-APPEAR-0123456789"
STRONG_KEY = "k" + "7" * 47
_UNSET = (
    "VERCEL", "AWS_LAMBDA_FUNCTION_NAME", "APP_UPLOAD_FOLDER", "APP_DOCUMENTOS_ALUNOS_FOLDER", "APP_LOG_DIR",
    "SGAA_RUNTIME", "CRON_SECRET", "TOKEN_ENCRYPTION_KEY", "SUPABASE_URL", "SUPABASE_SECRET_KEY",
    "SGAA_STORAGE_BUCKET", "APP_PUBLIC_BASE_URL", "FLASK_DEBUG", "DEBUG", "FLASK_SECRET_KEY",
)


@pytest.fixture
def log_channels():
    """The ``app`` / ``main`` channels without a console handler, restored exactly.

    Handlers are removed and re-added individually -- the list object is never
    replaced, so the suite's own per-test log isolation keeps working.
    """
    channels = [logging.getLogger("app"), logging.getLogger("main")]
    removed = []
    for channel in channels:
        for handler in list(channel.handlers):
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                channel.removeHandler(handler)
                removed.append((channel, handler))
    before = {channel: list(channel.handlers) for channel in channels}
    yield channels
    for channel in channels:
        for handler in list(channel.handlers):
            if handler not in before[channel]:
                channel.removeHandler(handler)
                handler.close()
    for channel, handler in removed:
        channel.addHandler(handler)


@pytest.fixture
def hosted_env(monkeypatch, tmp_path, log_channels):
    """A complete, valid hosted environment over a hermetic scratch root."""
    for name in _UNSET:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")
    monkeypatch.setenv("TRUST_PROXY_XFF", "1")
    monkeypatch.setenv("APP_SECRET_KEY", STRONG_KEY)
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    monkeypatch.setattr(app_db, "DATABASE_URL", "postgresql://sgaa@127.0.0.1:1/none")
    return SimpleNamespace(scratch=hosting.scratch_root(), tmp=tmp_path)


@pytest.fixture
def production_env(hosted_env, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://sgaa.example.test")
    monkeypatch.setenv("SUPABASE_URL", "https://abcdefghijklmnop.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_" + "x" * 30)
    monkeypatch.setenv("SGAA_STORAGE_BUCKET", "sgaa-documentos")
    return hosted_env


# ---------------------------------------------------------------------------
# mode declaration
# ---------------------------------------------------------------------------


def test_mode_is_declared_normalized_and_defaults_to_local(monkeypatch):
    monkeypatch.delenv("SGAA_RUNTIME", raising=False)
    assert hosting.declared_mode() is None and hosting.is_hosted() is False
    for raw, expected in (("hosted", True), (" HOSTED ", True), ("local", False), ("Local", False)):
        monkeypatch.setenv("SGAA_RUNTIME", raw)
        assert hosting.is_hosted() is expected


def test_unknown_mode_is_refused_and_the_value_is_not_echoed(monkeypatch):
    monkeypatch.setenv("SGAA_RUNTIME", SENTINEL)
    with pytest.raises(HostingConfigurationError) as raised:
        hosting.declared_mode()
    assert raised.value.blockers == (Blocker("RUNTIME_MODE_INVALID", ("SGAA_RUNTIME",)),)
    assert SENTINEL not in str(raised.value)


@pytest.mark.parametrize("marker", ["VERCEL", "AWS_LAMBDA_FUNCTION_NAME"])
def test_a_serverless_platform_without_a_declaration_refuses_to_start(monkeypatch, marker):
    monkeypatch.delenv("SGAA_RUNTIME", raising=False)
    monkeypatch.setenv(marker, "1")
    with pytest.raises(HostingConfigurationError) as raised:
        hosting.require_declared_runtime()
    assert [b.code for b in raised.value.blockers] == ["RUNTIME_MODE_UNDECLARED"]
    # An explicit declaration is accepted either way: nothing is inferred.
    monkeypatch.setenv("SGAA_RUNTIME", "local")
    assert hosting.require_declared_runtime() is False
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")
    assert hosting.require_declared_runtime() is True


def test_an_ordinary_machine_without_markers_stays_local(monkeypatch):
    for name in ("SGAA_RUNTIME", "VERCEL", "AWS_LAMBDA_FUNCTION_NAME"):
        monkeypatch.delenv(name, raising=False)
    assert hosting.require_declared_runtime() is False


def test_hosted_defaults_point_the_pre_factory_log_directory_at_scratch():
    env = {"SGAA_RUNTIME": "hosted"}
    hosting.apply_hosted_defaults(env)
    assert env["APP_LOG_DIR"] == os.path.join(hosting.scratch_root(), "logs")
    explicit = {"SGAA_RUNTIME": "hosted", "APP_LOG_DIR": "/somewhere/else"}
    hosting.apply_hosted_defaults(explicit)
    assert explicit["APP_LOG_DIR"] == "/somewhere/else"
    local = {"SGAA_RUNTIME": "local"}
    hosting.apply_hosted_defaults(local)
    assert "APP_LOG_DIR" not in local  # control: local mode keeps its own default
    undeclared = {}
    hosting.apply_hosted_defaults(undeclared)
    assert undeclared == {}
    invalid = {"SGAA_RUNTIME": "maybe"}
    hosting.apply_hosted_defaults(invalid)  # does not raise at import: create_app refuses with the code
    assert invalid == {"SGAA_RUNTIME": "maybe"}


# ---------------------------------------------------------------------------
# startup blockers
# ---------------------------------------------------------------------------


def _codes(blockers):
    return [b.code for b in blockers]


def test_postgres_is_required_when_hosted(hosted_env, monkeypatch):
    assert _codes(hosting.startup_blockers(production=False)) == []
    for url in ("", "mysql://u@h/d", "not a url"):
        monkeypatch.setattr(app_db, "DATABASE_URL", url)
        assert _codes(hosting.startup_blockers(production=False)) == ["HOSTED_POSTGRES_REQUIRED"], url


def test_the_proxy_trust_decision_must_be_explicit(hosted_env, monkeypatch):
    for value in ("0", "1", "true", "False"):
        monkeypatch.setenv("TRUST_PROXY_XFF", value)
        assert hosting.startup_blockers(production=False) == ()
    for value in ("", "maybe"):
        monkeypatch.setenv("TRUST_PROXY_XFF", value)
        assert _codes(hosting.startup_blockers(production=False)) == ["HOSTED_PROXY_TRUST_UNDECIDED"]
    monkeypatch.delenv("TRUST_PROXY_XFF")
    assert _codes(hosting.startup_blockers(production=False)) == ["HOSTED_PROXY_TRUST_UNDECIDED"]


def test_production_also_requires_the_canonical_storage_variables(hosted_env, monkeypatch):
    assert hosting.startup_blockers(production=False) == ()
    blockers = hosting.startup_blockers(production=True)
    assert blockers == (
        Blocker("HOSTED_STORAGE_CONFIG_REQUIRED", ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "SGAA_STORAGE_BUCKET")),
    )
    monkeypatch.setenv("SUPABASE_URL", "https://abcdefghijklmnop.supabase.co")
    monkeypatch.setenv("SGAA_STORAGE_BUCKET", "sgaa-documentos")
    only_secret = hosting.startup_blockers(production=True)
    assert only_secret[0].names == ("SUPABASE_SECRET_KEY",)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", SENTINEL)
    assert hosting.startup_blockers(production=True) == ()
    monkeypatch.setenv("SGAA_STORAGE_BUCKET", "NOT A VALID BUCKET")
    assert hosting.startup_blockers(production=True)[0].names == ("SGAA_STORAGE_BUCKET",)
    assert SENTINEL not in repr(hosting.startup_blockers(production=True))


def test_the_scheduler_secret_needs_the_minimum_length(monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert hosting.scheduler_secret_configured() is False
    monkeypatch.setenv("CRON_SECRET", "s" * (hosting.CRON_SECRET_MIN_LENGTH - 1))
    assert hosting.scheduler_secret_configured() is False
    monkeypatch.setenv("CRON_SECRET", "s" * hosting.CRON_SECRET_MIN_LENGTH)
    assert hosting.scheduler_secret_configured() is True


# ---------------------------------------------------------------------------
# create_app, hosted
# ---------------------------------------------------------------------------


def test_hosted_create_app_writes_nothing_and_uses_scratch(hosted_env):
    from app import create_app

    with FilesystemTripwire(allowed_roots=(hosted_env.scratch,)) as tripwire:
        flask_app = create_app()
    assert tripwire.attempts == []
    for key in ("UPLOAD_FOLDER", "DOCUMENTOS_ALUNOS_FOLDER"):
        assert os.path.normcase(flask_app.config[key]).startswith(os.path.normcase(hosted_env.scratch))
        assert not os.path.exists(flask_app.config[key])
    assert not os.path.exists(hosted_env.scratch)


def test_hosted_logging_is_the_platform_stream_on_both_channels(hosted_env):
    """A file handler left by an earlier local app must not satisfy the hosted stream rule."""
    from app import create_app

    leftover = logging.FileHandler(str(hosted_env.tmp / "leftover.log"), delay=True)
    app_channel = logging.getLogger("app")
    app_channel.addHandler(leftover)
    try:
        create_app()
        for channel in ("app", "main"):
            handlers = logging.getLogger(channel).handlers
            console = [h for h in handlers
                       if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]
            assert console, channel
        assert leftover in app_channel.handlers  # nothing was removed, only added
    finally:
        app_channel.removeHandler(leftover)
        leftover.close()


def test_the_tripwire_is_discriminating_local_create_app_is_caught(hosted_env, monkeypatch):
    """Control: the same call in local mode DOES write, and the tripwire sees it."""
    from app import create_app

    monkeypatch.setenv("SGAA_RUNTIME", "local")
    monkeypatch.setenv("APP_UPLOAD_FOLDER", str(hosted_env.tmp / "local-uploads"))
    monkeypatch.setenv("APP_DOCUMENTOS_ALUNOS_FOLDER", str(hosted_env.tmp / "local-docs"))
    monkeypatch.setenv("APP_LOG_DIR", str(hosted_env.tmp / "local-logs"))
    with FilesystemTripwire(allowed_roots=(hosted_env.scratch,)) as tripwire:
        with pytest.raises(OSError):
            create_app()
    assert tripwire.attempts and tripwire.attempts[0][0] in {"os.makedirs", "os.mkdir"}


def test_explicit_folder_overrides_are_honoured_but_still_not_created(hosted_env, monkeypatch):
    from app import create_app

    chosen = hosted_env.tmp / "chosen"
    monkeypatch.setenv("APP_UPLOAD_FOLDER", str(chosen))
    flask_app = create_app()
    assert flask_app.config["UPLOAD_FOLDER"] == str(chosen)
    assert not chosen.exists()


def _refusal(mutation, monkeypatch):
    import traceback

    from app import create_app

    mutation(monkeypatch)
    with pytest.raises(HostingConfigurationError) as raised:
        create_app()
    # The whole traceback is what a platform log captures: the exception CHAIN must not
    # quote the refused value either (a refused address carries userinfo and query).
    chain = "".join(traceback.format_exception(raised.value))
    for value in ("insecure.example.test", "not-a-fernet-key", "change-me", "token=S3CRET"):
        assert value not in chain
    return raised.value


@pytest.mark.parametrize(
    "mutation, code",
    [
        (lambda m: m.setattr(app_db, "DATABASE_URL", ""), "HOSTED_POSTGRES_REQUIRED"),
        (lambda m: m.delenv("TRUST_PROXY_XFF"), "HOSTED_PROXY_TRUST_UNDECIDED"),
        (lambda m: m.delenv("SGAA_RUNTIME") or m.setenv("VERCEL", "1"), "RUNTIME_MODE_UNDECLARED"),
        (lambda m: m.setenv("SGAA_RUNTIME", "maybe"), "RUNTIME_MODE_INVALID"),
        (lambda m: m.setenv("APP_SECRET_KEY", ""), "HOSTED_SECRET_KEY_REQUIRED"),
        (lambda m: m.setenv("APP_SECRET_KEY", "change-me"), "HOSTED_SECRET_KEY_REQUIRED"),
        (lambda m: m.setenv("APP_SECRET_KEY", "short"), "HOSTED_SECRET_KEY_REQUIRED"),
    ],
)
def test_hosted_create_app_refuses_each_blocker_with_a_fixed_code(hosted_env, monkeypatch, mutation, code):
    error = _refusal(mutation, monkeypatch)
    assert code in _codes(error.blockers)
    assert STRONG_KEY not in str(error)


@pytest.mark.parametrize(
    "mutation, code, names",
    [
        (lambda m: m.delenv("SUPABASE_SECRET_KEY"), "HOSTED_STORAGE_CONFIG_REQUIRED", ("SUPABASE_SECRET_KEY",)),
        (lambda m: m.delenv("SGAA_STORAGE_BUCKET"), "HOSTED_STORAGE_CONFIG_REQUIRED", ("SGAA_STORAGE_BUCKET",)),
        (lambda m: m.delenv("TOKEN_ENCRYPTION_KEY"), "HOSTED_TOKEN_KEY_REQUIRED", ("TOKEN_ENCRYPTION_KEY",)),
        (lambda m: m.setenv("TOKEN_ENCRYPTION_KEY", "not-a-fernet-key"), "HOSTED_TOKEN_KEY_REQUIRED", ("TOKEN_ENCRYPTION_KEY",)),
        (lambda m: m.setenv("APP_PUBLIC_BASE_URL", "http://insecure.example.test"), "HOSTED_PUBLIC_URL_INVALID",
         ("APP_PUBLIC_BASE_URL",)),
        (lambda m: m.setenv("APP_PUBLIC_BASE_URL", "http://insecure.example.test/p?token=S3CRET"),
         "HOSTED_PUBLIC_URL_INVALID", ("APP_PUBLIC_BASE_URL",)),
        (lambda m: m.delenv("APP_PUBLIC_BASE_URL"), "HOSTED_PUBLIC_URL_INVALID", ("APP_PUBLIC_BASE_URL",)),
    ],
)
def test_hosted_production_refuses_each_extra_blocker_with_a_fixed_code(production_env, monkeypatch, mutation, code, names):
    error = _refusal(mutation, monkeypatch)
    assert error.blockers[0].code == code and error.blockers[0].names == names
    assert "insecure.example.test" not in str(error) and "not-a-fernet-key" not in str(error)


def test_a_complete_hosted_production_environment_starts_and_writes_nothing(production_env):
    from app import create_app

    with FilesystemTripwire(allowed_roots=(production_env.scratch,)) as tripwire:
        flask_app = create_app()
    assert tripwire.attempts == []
    assert flask_app.config["IS_PRODUCTION"] is True and flask_app.config["SESSION_COOKIE_SECURE"] is True


def test_local_production_keeps_its_plain_runtime_errors(production_env, monkeypatch):
    """Control: the fixed hosted codes are hosted-only; local wording is unchanged."""
    from app import create_app

    monkeypatch.setenv("SGAA_RUNTIME", "local")
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY")
    monkeypatch.setenv("LOCALAPPDATA", str(production_env.tmp / "empty-localappdata"))
    with pytest.raises(RuntimeError) as raised:
        create_app()
    assert not isinstance(raised.value, HostingConfigurationError)


def test_hosted_create_app_needs_a_strong_stable_secret_key(hosted_env, monkeypatch):
    """Control: local (testing) mode would have generated an ephemeral key."""
    from app import create_app

    monkeypatch.setenv("SGAA_RUNTIME", "local")
    monkeypatch.setenv("APP_SECRET_KEY", "")
    monkeypatch.setenv("APP_UPLOAD_FOLDER", str(hosted_env.tmp / "u"))
    monkeypatch.setenv("APP_DOCUMENTOS_ALUNOS_FOLDER", str(hosted_env.tmp / "d"))
    monkeypatch.setenv("APP_LOG_DIR", str(hosted_env.tmp / "l"))
    assert create_app().secret_key


def test_hosted_health_reports_a_dead_database_without_a_traceback(hosted_env):
    from app import create_app

    response = create_app().test_client().get("/health")
    assert response.status_code == 500
    assert json.loads(response.data) == {"status": "error"}


# ---------------------------------------------------------------------------
# the Banco de dados page: credential forms
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_page(monkeypatch, tmp_path):
    import main
    from app import cloud_credentials, machine_secrets
    from tests.session_support import stamp_auth_version

    for name in ("SGAA_RUNTIME", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "MS_CLIENT_ID", "MS_CLIENT_SECRET",
                 "MS_TENANT_ID", "APP_PUBLIC_BASE_URL", "TOKEN_ENCRYPTION_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(machine_secrets, "get_machine_secrets_path", lambda: str(tmp_path / "no-store.dpapi"))
    with main.app.app_context():
        main.init_db()
    client = main.app.test_client()
    with client.session_transaction() as session:
        session.update(user_id=1, user_type="admin", user_name="Administrador", access_level="admin_total")
        stamp_auth_version(session)

    def render(managed: bool) -> str:
        monkeypatch.setattr(cloud_credentials, "credentials_managed_by_environment", lambda: managed)
        response = client.get("/admin/banco-dados")
        assert response.status_code == 200
        return response.get_data(as_text=True)

    return render


def test_credential_forms_are_read_only_when_the_environment_manages_them(admin_page):
    managed = admin_page(True)
    assert "definidos pelo ambiente de hospedagem" in managed
    assert 'name="client_secret"' not in managed and 'name="app_public_base_url"' not in managed


def test_credential_forms_are_editable_locally(admin_page):
    """Control: the same page, same store, with the environment not in charge."""
    local = admin_page(False)
    assert "definidos pelo ambiente de hospedagem" not in local
    assert 'name="client_secret"' in local


# ---------------------------------------------------------------------------
# secrets
# ---------------------------------------------------------------------------


@pytest.fixture
def poisoned_store(monkeypatch, tmp_path):
    """A machine store that cannot be read: any reader that opens it fails."""
    from app import machine_secrets

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    store = machine_secrets.get_machine_secrets_path()
    os.makedirs(os.path.dirname(store))
    with open(store, "wb") as handle:
        handle.write(b"this is not a protected payload")
    return store


def _bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def test_hosted_never_reads_the_machine_store_and_takes_oauth_from_the_environment(
    hosted_env, poisoned_store, monkeypatch
):
    from app import cloud_config, machine_secrets

    before = _bytes(poisoned_store)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id-from-env")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret-from-env")
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://sgaa.example.test")
    assert machine_secrets.load_machine_secrets()["providers"] == {}
    assert cloud_config.get_google_oauth_config()["client_id"] == "client-id-from-env"
    assert cloud_config.get_application_credential_status("google") == {
        "provider": "google", "configured": True, "source": "ENVIRONMENT",
    }
    assert cloud_config.get_public_base_url_setting() == "https://sgaa.example.test"
    assert _bytes(poisoned_store) == before


def test_local_mode_does_read_the_store_which_proves_the_hosted_bypass_is_real(
    hosted_env, poisoned_store, monkeypatch
):
    """Control: the same poisoned store makes the local reader fail closed."""
    from app import cloud_config, machine_secrets

    monkeypatch.setenv("SGAA_RUNTIME", "local")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id-from-env")
    with pytest.raises(machine_secrets.MachineSecretsError):
        cloud_config.get_google_oauth_config()
    assert cloud_config.get_application_credential_status("google")["source"] == "ERROR"


def test_hosted_refuses_every_store_write_and_leaves_it_untouched(hosted_env, poisoned_store):
    from app import cloud_credentials, machine_secrets

    before = _bytes(poisoned_store)
    for call in (
        lambda: machine_secrets.save_machine_secrets({"runtime": {}}),
        lambda: machine_secrets.get_machine_token_encryption_key(create=True),
        lambda: machine_secrets.update_machine_oauth_configuration(provider="google", values={"client_id": "x"}),
        lambda: machine_secrets.ensure_machine_secret_infrastructure(),
    ):
        with pytest.raises(machine_secrets.MachineSecretsError):
            call()
    assert cloud_credentials.credentials_managed_by_environment() is True
    assert _bytes(poisoned_store) == before


def test_the_product_level_guard_refuses_before_the_store_layer_is_reached(hosted_env, monkeypatch):
    """Two layers refuse; this proves the first one fires (the store is never called)."""
    from app import cloud_credentials

    def forbidden(*args, **kwargs):
        raise AssertionError("the store layer was reached")

    for name in ("load_machine_secrets", "save_machine_secrets", "update_machine_oauth_configuration"):
        monkeypatch.setattr(cloud_credentials, name, forbidden)
    monkeypatch.setattr(cloud_credentials, "run_startup_preflight", forbidden)
    for call in (
        lambda: cloud_credentials.save_application_credentials(provider="google", client_id="c", client_secret="s"),
        lambda: cloud_credentials.save_public_base_url("https://sgaa.example.test"),
    ):
        with pytest.raises(cloud_credentials.CloudCredentialsError) as raised:
            call()
        assert "definidos pelo ambiente de hospedagem" in str(raised.value)


def test_the_environment_token_key_is_the_only_key_when_hosted(hosted_env, monkeypatch):
    from app import machine_secrets
    from app.services import token_encryption

    assert machine_secrets.get_machine_token_encryption_key() == ""
    assert token_encryption.get_token_encryption_key() == ""
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "key-from-the-environment")
    assert token_encryption.get_token_encryption_key() == "key-from-the-environment"
    assert machine_secrets.ensure_machine_secret_infrastructure()["status"] == machine_secrets.INFRASTRUCTURE_ENVIRONMENT


# ---------------------------------------------------------------------------
# PostgreSQL connect timeout
# ---------------------------------------------------------------------------


class _RecordingConnection:
    isolation_level = None

    def close(self):  # pragma: no cover - not reached
        pass


@pytest.fixture
def recorded_connect(monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    calls = []

    def fake_connect(conninfo, **kwargs):
        calls.append((conninfo, kwargs))
        return _RecordingConnection()

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    monkeypatch.delenv("SGAA_PG_CONNECT_TIMEOUT", raising=False)
    monkeypatch.delenv("PGCONNECT_TIMEOUT", raising=False)
    return calls


def test_postgres_connections_are_time_bounded_by_default(recorded_connect, monkeypatch):
    monkeypatch.setattr(app_db, "DATABASE_URL", "postgresql://u@h:5432/d")
    app_db._connect_postgres()
    assert recorded_connect[-1][1]["connect_timeout"] == 10
    assert recorded_connect[-1][1]["prepare_threshold"] is None


def test_the_connect_timeout_is_configurable_and_a_bad_value_falls_back(recorded_connect, monkeypatch):
    monkeypatch.setattr(app_db, "DATABASE_URL", "postgresql://u@h:5432/d")
    monkeypatch.setenv("SGAA_PG_CONNECT_TIMEOUT", "3")
    app_db._connect_postgres()
    assert recorded_connect[-1][1]["connect_timeout"] == 3
    for bad in ("0", "-2", "abc", "", "²"):
        monkeypatch.setenv("SGAA_PG_CONNECT_TIMEOUT", bad)
        app_db._connect_postgres()
        assert recorded_connect[-1][1]["connect_timeout"] == 10, bad


def test_a_timeout_in_the_connection_string_or_libpq_environment_wins(recorded_connect, monkeypatch):
    monkeypatch.setattr(app_db, "DATABASE_URL", "postgresql://u@h:5432/d?connect_timeout=2")
    monkeypatch.setenv("SGAA_PG_CONNECT_TIMEOUT", "9")
    app_db._connect_postgres()
    assert "connect_timeout" not in recorded_connect[-1][1]
    monkeypatch.setattr(app_db, "DATABASE_URL", "postgresql://u@h:5432/d")
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "4")
    app_db._connect_postgres()
    assert "connect_timeout" not in recorded_connect[-1][1]


# ---------------------------------------------------------------------------
# operator check
# ---------------------------------------------------------------------------


def _run_check(*argv):
    out = io.StringIO()
    code = hosting_cli.main(["check", *argv], out=out)
    return code, json.loads(out.getvalue())


def test_check_reports_ready_without_printing_a_value(hosted_env, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", SENTINEL * 2)
    code, report = _run_check()
    assert code == 0
    assert report["mode"] == "hosted" and report["startup"] == "OK" and report["scheduler"] == "enabled"
    assert STRONG_KEY not in json.dumps(report) and SENTINEL not in json.dumps(report)


def test_check_reports_blockers_by_code_and_name(hosted_env, monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_XFF")
    monkeypatch.setattr(app_db, "DATABASE_URL", "")
    code, report = _run_check()
    assert code == 1 and report["startup"] == "REFUSED"
    assert {b["code"] for b in report["blockers"]} == {"HOSTED_POSTGRES_REQUIRED", "HOSTED_PROXY_TRUST_UNDECIDED"}


def test_check_reports_a_weak_secret_key_by_its_fixed_code(hosted_env, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "")
    code, report = _run_check()
    assert code == 1
    assert report["blockers"] == [{"code": "HOSTED_SECRET_KEY_REQUIRED", "names": ["APP_SECRET_KEY"]}]


def test_check_reports_an_unexpected_startup_error_by_class_only(hosted_env, monkeypatch):
    import app as app_package

    def boom(*args, **kwargs):
        raise ValueError(f"unexpected {SENTINEL}")

    monkeypatch.setattr(app_package, "create_app", boom)
    code, report = _run_check()
    assert code == 1 and report == {**report, "startup": "REFUSED", "error_type": "ValueError"}
    assert SENTINEL not in json.dumps(report)


def test_check_database_needs_postgres_and_never_opens_sqlite(hosted_env, monkeypatch):
    import sqlite3

    monkeypatch.setattr(app_db, "DATABASE_URL", "")

    def refused(*args, **kwargs):
        raise AssertionError("a SQLite file was opened")

    monkeypatch.setattr(sqlite3, "connect", refused)
    code, report = _run_check("--database")
    assert code == 2 and report["error"] == "DATABASE_REQUIRES_POSTGRES"
    # the function itself is guarded, not only the command line
    assert hosting_cli.check(database=True)[0] == 2


def test_check_usage_error_exits_2():
    assert hosting_cli.main(["check", "--nope"], out=io.StringIO()) == 2


def test_the_command_line_runs_as_a_module_and_reports_blockers():
    """``python -m`` loads the module under its own name: the report must still name the blockers."""
    minimal = {k: os.environ[k] for k in ("SYSTEMROOT", "SystemDrive", "WINDIR", "PATH", "PATHEXT", "OS") if k in os.environ}
    minimal.update({"SGAA_RUNTIME": "hosted", "APP_SECRET_KEY": STRONG_KEY, "APP_ENV": "development",
                    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
                    "TOKEN_ENCRYPTION_KEY": "", "SUPABASE_URL": "", "DATABASE_URL": "", "TRUST_PROXY_XFF": ""})
    result = subprocess.run([sys.executable, "-m", "app.hosting_cli", "check"], cwd=REPO_ROOT, env=minimal,
                            capture_output=True, text=True, timeout=120)
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert result.returncode == 1 and report["startup"] == "REFUSED"
    assert {b["code"] for b in report["blockers"]} == {"HOSTED_POSTGRES_REQUIRED", "HOSTED_PROXY_TRUST_UNDECIDED"}
    assert "RuntimeWarning" not in result.stderr


# ---------------------------------------------------------------------------
# wiring that must not depend on the opt-in database lane
# ---------------------------------------------------------------------------


def _child(code: str, **env) -> subprocess.CompletedProcess:
    minimal = {k: os.environ[k] for k in ("SYSTEMROOT", "SystemDrive", "WINDIR", "PATH", "PATHEXT", "OS") if k in os.environ}
    minimal.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", **env})
    return subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=minimal, capture_output=True,
                          text=True, timeout=120)


def test_importing_the_package_when_hosted_points_the_log_directory_at_scratch():
    result = _child("import os, app; print(os.environ.get('APP_LOG_DIR', ''))", SGAA_RUNTIME="hosted",
                    TEMP=str(REPO_ROOT / ".mp2-no-such-temp"), TMP=str(REPO_ROOT / ".mp2-no-such-temp"))
    assert result.returncode == 0, result.stderr[-500:]
    assert result.stdout.strip().endswith(os.path.join("sgaa-scratch", "logs"))


def test_importing_the_package_locally_leaves_the_log_directory_unset():
    result = _child("import os, app; print(repr(os.environ.get('APP_LOG_DIR')))")
    assert result.returncode == 0 and result.stdout.strip() == "None"


def test_importing_the_package_with_an_invalid_mode_does_not_raise_here():
    """The refusal, with its code, belongs to create_app and the check -- not to a bare import."""
    result = _child("import app; print('imported')", SGAA_RUNTIME="maybe")
    assert result.returncode == 0 and result.stdout.strip() == "imported"


def test_the_retired_module_command_fails_instead_of_passing_a_ci_gate():
    result = subprocess.run([sys.executable, "-m", "app.hosting", "check"], cwd=REPO_ROOT, capture_output=True,
                            text=True, timeout=120, env={**os.environ, "SGAA_RUNTIME": "local"})
    assert result.returncode != 0
    assert "app.hosting_cli" in result.stderr


def test_hosted_health_fails_on_schema_version_skew_without_a_database(hosted_env, monkeypatch):
    import app as app_package
    import app.db_maintenance as db_maintenance
    from app import create_app

    class _Connection:
        def execute(self, sql, *args):
            return self

    class _SkewedSchema(RuntimeError):
        pass

    def skewed(conn):
        raise _SkewedSchema("v15 database, v16 code")

    monkeypatch.setattr(app_package, "get_db_connection", lambda: _Connection())
    monkeypatch.setattr(db_maintenance, "get_schema_status", skewed)
    flask_app = create_app()
    response = flask_app.test_client().get("/health")
    assert response.status_code == 500 and json.loads(response.data) == {"status": "error"}
    # control: a current schema answers ok
    monkeypatch.setattr(db_maintenance, "get_schema_status", lambda conn: {"schema_version": 16})
    assert flask_app.test_client().get("/health").status_code == 200
