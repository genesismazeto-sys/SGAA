"""Hosted-runtime contract: mode declaration, scratch space and startup blockers.

SGAA runs in one of two declared modes.  ``local`` is the Windows workstation
runtime and the default: SQLite or PostgreSQL, a persistent project directory,
a DPAPI secret store.  ``hosted`` (``SGAA_RUNTIME=hosted``) is the serverless
runtime: PostgreSQL only, no durable local disk, every secret from the
environment.  The mode is declared, never inferred, so a changed platform
marker cannot silently switch semantics; the single exception is a refusal --
a serverless platform with no declaration refuses to start, because local
semantics on an ephemeral disk would lose data without a sound.

No module-level import reaches into ``app``: ``app.machine_secrets`` and
``app.create_app`` ask the mode through here without a cycle (the blocker
check imports the database and storage owners lazily, when it runs).
Everything raised names variables and fixed codes, never a value.  The
operator command line is ``app.hosting_cli``; the web runtime never imports it.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass

RUNTIME_ENV = "SGAA_RUNTIME"
MODE_HOSTED = "hosted"
MODE_LOCAL = "local"
PROXY_TRUST_ENV = "TRUST_PROXY_XFF"
LOG_DIR_ENV = "APP_LOG_DIR"
#: Vercel Cron's own variable name; the scheduler front reads it (never a query string).
CRON_SECRET_ENV = "CRON_SECRET"
CRON_SECRET_MIN_LENGTH = 32
SCRATCH_DIRNAME = "sgaa-scratch"
#: Who a hosted process admits.  ``operator``: only requests that present the operator credential
#: (``app.web.admission_gate``); everyone else is refused before any view or database access.
#: ``open``: everyone the application's own authentication admits.  Production must decide
#: explicitly; lifting ``operator`` to ``open`` is the opening (MP-3 gate GO).
ADMISSION_ENV = "SGAA_ADMISSION"
ADMISSION_OPERATOR = "operator"
ADMISSION_OPEN = "open"
OPERATOR_TOKEN_ENV = "SGAA_OPERATOR_TOKEN"
OPERATOR_TOKEN_MIN_LENGTH = 32
#: An ``open`` production deployment names the cutover reference it was lifted with (the hash of the
#: reference entry the ledger printed when it took the reference while admission was closed) and
#: announces a tag of it; the ledger's ``open`` proves the binding (MP-3 A15).
OPENING_REFERENCE_ENV = "SGAA_OPENING_REFERENCE"

_SERVERLESS_MARKERS = ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME")
_BOOLEAN_WORDS = frozenset({"0", "1", "true", "false", "yes", "no", "on", "off"})

RUNTIME_MODE_INVALID = "RUNTIME_MODE_INVALID"
RUNTIME_MODE_UNDECLARED = "RUNTIME_MODE_UNDECLARED"
HOSTED_POSTGRES_REQUIRED = "HOSTED_POSTGRES_REQUIRED"
HOSTED_PROXY_TRUST_UNDECIDED = "HOSTED_PROXY_TRUST_UNDECIDED"
HOSTED_STORAGE_CONFIG_REQUIRED = "HOSTED_STORAGE_CONFIG_REQUIRED"
HOSTED_SECRET_KEY_REQUIRED = "HOSTED_SECRET_KEY_REQUIRED"
HOSTED_TOKEN_KEY_REQUIRED = "HOSTED_TOKEN_KEY_REQUIRED"
HOSTED_PUBLIC_URL_INVALID = "HOSTED_PUBLIC_URL_INVALID"
HOSTED_ADMISSION_UNDECIDED = "HOSTED_ADMISSION_UNDECIDED"
HOSTED_OPERATOR_TOKEN_REQUIRED = "HOSTED_OPERATOR_TOKEN_REQUIRED"
HOSTED_OPENING_REFERENCE_REQUIRED = "HOSTED_OPENING_REFERENCE_REQUIRED"


@dataclass(frozen=True)
class Blocker:
    """One reason the process must not start: a fixed code and variable NAMES."""

    code: str
    names: tuple[str, ...]


class HostingConfigurationError(RuntimeError):
    """The hosted-runtime contract is not met; ``blockers`` says why, value-free."""

    def __init__(self, blockers: tuple[Blocker, ...]) -> None:
        self.blockers = tuple(blockers)
        super().__init__("; ".join(f"{b.code}: {','.join(b.names)}" for b in self.blockers))


def single(code: str, *names: str) -> HostingConfigurationError:
    return HostingConfigurationError((Blocker(code, tuple(names)),))


def _environ(environ):
    return os.environ if environ is None else environ


def declared_mode(environ=None) -> str | None:
    """The declared mode, ``None`` when undeclared; an unknown value is refused."""
    raw = str(_environ(environ).get(RUNTIME_ENV) or "").strip().lower()
    if not raw:
        return None
    if raw not in (MODE_HOSTED, MODE_LOCAL):
        raise single(RUNTIME_MODE_INVALID, RUNTIME_ENV)
    return raw


def serverless_platform(environ=None) -> bool:
    env = _environ(environ)
    return any(str(env.get(name) or "").strip() for name in _SERVERLESS_MARKERS)


def is_hosted(environ=None) -> bool:
    return declared_mode(environ) == MODE_HOSTED


def require_declared_runtime(environ=None) -> bool:
    """Whether the process is hosted; refuses an undeclared serverless platform."""
    mode = declared_mode(environ)
    if mode is None and serverless_platform(environ):
        raise single(RUNTIME_MODE_UNDECLARED, RUNTIME_ENV)
    return mode == MODE_HOSTED


def scratch_root() -> str:
    """The only directory a hosted process may write; created by its consumers, lazily."""
    return os.path.join(tempfile.gettempdir(), SCRATCH_DIRNAME)


def apply_hosted_defaults(environ=None) -> None:
    """Point the one setting read before the application factory runs at scratch.

    ``main`` creates its log directory at import, ahead of ``create_app``; a
    hosted process must not write the project directory even by default, so its
    ``APP_LOG_DIR`` defaults to scratch.  An explicit value is respected.
    Called once, when the ``app`` package is first imported.
    """
    env = os.environ if environ is None else environ
    try:
        hosted = is_hosted(env)
    except HostingConfigurationError:
        return  # an invalid declaration is refused, with its code, by create_app
    if hosted and not str(env.get(LOG_DIR_ENV) or "").strip():
        env[LOG_DIR_ENV] = os.path.join(scratch_root(), "logs")


def cron_secret(environ=None) -> str | None:
    """The scheduler credential, or ``None`` when the front is disabled.

    One rule for the front and the readiness report: surrounding whitespace is
    ignored, at least ``CRON_SECRET_MIN_LENGTH`` characters, ASCII only (an HTTP
    header cannot carry anything else faithfully).
    """
    secret = str(_environ(environ).get(CRON_SECRET_ENV) or "").strip()
    return secret if len(secret) >= CRON_SECRET_MIN_LENGTH and secret.isascii() else None


def scheduler_secret_configured(environ=None) -> bool:
    return cron_secret(environ) is not None


def admission_must_be_decided(environ=None, *, production: bool) -> bool:
    """Production, or any process on a serverless platform (a deployment missing ``APP_ENV`` included)."""
    return production or serverless_platform(environ)


def admission_mode(environ=None, *, production: bool) -> str | None:
    """``operator`` or ``open``; ``None`` when a deployment has not decided (a startup blocker).

    Only a non-production process off any serverless platform (a workstation, a test) takes an
    undeclared value as ``open``.  An unknown value is never guessed in either direction.
    """
    raw = str(_environ(environ).get(ADMISSION_ENV) or "").strip().lower()
    if raw in (ADMISSION_OPERATOR, ADMISSION_OPEN):
        return raw
    if not raw and not admission_must_be_decided(environ, production=production):
        return ADMISSION_OPEN
    return None


def opening_reference(environ=None) -> str | None:
    """The reference entry hash an ``open`` deployment was lifted with: 64 lowercase hex, else None."""
    raw = str(_environ(environ).get(OPENING_REFERENCE_ENV) or "").strip().lower()
    return raw if len(raw) == 64 and all(c in "0123456789abcdef" for c in raw) else None


def opening_tag(reference: str) -> str:
    """What an open deployment announces (``X-SGAA-Opening``) for its reference; the ledger computes it too."""
    return hashlib.sha256(b"sgaa-opening\x00" + reference.encode("ascii")).hexdigest()


def operator_token(environ=None) -> str | None:
    """The operator credential while admission is ``operator``: printable ASCII, at least 32 characters."""
    token = str(_environ(environ).get(OPERATOR_TOKEN_ENV) or "").strip()
    if len(token) < OPERATOR_TOKEN_MIN_LENGTH or not token.isascii() or not token.isprintable():
        return None
    return token


SUPABASE_POOLER_SUFFIX = ".pooler.supabase.com"
SUPABASE_TRANSACTION_PORT = 6543


def connection_kind(url: str) -> str:
    """``direct``, ``pooler_session``, ``pooler_transaction`` or ``unknown`` -- never the host.

    A managed platform's shared pooler serves a transaction-mode port beside a
    session-mode one.  Transaction mode keeps no session state and no prepared
    statements: right for the web and scheduler functions, wrong for a tool that
    needs one session (a snapshot dump, a restore), which accepts only ``direct``
    and ``pooler_session``.  The address is read as libpq reads it (query
    overrides, percent-encoding); a list of hosts is ``unknown``.
    """
    try:
        from psycopg.conninfo import conninfo_to_dict

        info = conninfo_to_dict(str(url or ""))
    except Exception:
        # No parser (or an unparseable value) is never "direct": callers that need
        # one session refuse `unknown`.
        return "unknown"
    host = str(info.get("host") or "").strip().lower().rstrip(".")
    port = str(info.get("port") or "").strip()
    if not host or "," in host or "," in port or "service" in info or "hostaddr" in info:
        # A host taken from the environment, a service file or a pinned address is not
        # the address the URL shows.
        return "unknown"
    if not port and os.environ.get("PGPORT"):
        return "unknown"  # the port would come from the environment, not from the URL
    if port:
        try:
            number = int(port)  # libpq reads ``06543`` and ``+6543`` as 6543
        except ValueError:
            return "unknown"
        if not 1 <= number <= 65535:
            return "unknown"
    else:
        number = 5432
    if not host.endswith(SUPABASE_POOLER_SUFFIX):
        return "direct"
    return "pooler_transaction" if number == SUPABASE_TRANSACTION_PORT else "pooler_session"


# ---------------------------------------------------------------------------
# which database, which Supabase project: the canonical source identity (MP-3 A16)
# ---------------------------------------------------------------------------

_SUPABASE_REF_LENGTH = 20
_SUPABASE_REF_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
_POOLER_TENANT_PREFIX = "postgres."


def _supabase_ref(value) -> str | None:
    value = str(value or "")
    return value if len(value) == _SUPABASE_REF_LENGTH and set(value) <= _SUPABASE_REF_CHARS else None


def supabase_project_ref(host, login_user=None) -> str | None:
    """The Supabase project a database connection or a storage address belongs to, else ``None``.

    A pooler address is shared by every project of a region: the project is the tenant the pooler
    authenticated (the login ``postgres.<ref>``).  A direct database address names it
    (``db.<ref>.supabase.co``), as does the storage API's (``<ref>.supabase.co``).  Anything else --
    a workstation, a scratch server -- belongs to no project.
    """
    host = str(host or "").strip().lower().rstrip(".")
    if host.endswith(SUPABASE_POOLER_SUFFIX):
        login = str(login_user or "")
        return _supabase_ref(login[len(_POOLER_TENANT_PREFIX):]) if login.startswith(_POOLER_TENANT_PREFIX) else None
    labels = host.split(".")
    if len(labels) == 4 and labels[0] == "db" and labels[2:] == ["supabase", "co"]:
        return _supabase_ref(labels[1])
    if len(labels) == 3 and labels[1:] == ["supabase", "co"]:
        return _supabase_ref(labels[0])
    return None


def project_sha256(ref: str) -> str:
    """The value-free name of a Supabase project (the cutover ledger's ``prod_project_sha256``)."""
    return hashlib.sha256(ref.encode("ascii")).hexdigest()


def database_source(conn) -> dict:
    """The raw facts naming the PostgreSQL database behind ``conn`` (a psycopg connection).

    Recorded in backup manifests and read live by the cutover ledger; never a password.  It raises
    nothing for a missing privilege: ``system_identifier`` is ``None`` when ``pg_control_system()`` is
    not executable, and the identity is then unproven.
    """
    from psycopg.rows import tuple_row

    with conn.cursor(row_factory=tuple_row) as cursor:
        database, user, readable = cursor.execute(
            "SELECT current_database(), current_user, "
            "has_function_privilege('pg_control_system()', 'EXECUTE')").fetchone()
        system_identifier = None
        if readable:
            system_identifier = str(cursor.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
    info = conn.info
    return {"database": str(database), "user": str(user), "login_user": str(info.user),
            "host": str(info.host), "port": str(info.port), "system_identifier": system_identifier}


def source_project_sha256(source) -> str | None:
    """The Supabase project of a recorded or live database source (``None``: no project)."""
    if not isinstance(source, dict):
        return None
    ref = supabase_project_ref(source.get("host"), source.get("login_user"))
    return project_sha256(ref) if ref else None


def source_identity_sha256(source) -> str | None:
    """The canonical identity every cutover comparison uses: database, role, cluster and project.

    The same database read live and recorded in a backup manifest gives the same value; another
    database, cluster or project does not.  ``None`` when the source does not prove its cluster.
    """
    if not isinstance(source, dict) or not source.get("system_identifier"):
        return None
    basis = [str(source.get("database")), str(source.get("user")), str(source["system_identifier"]),
             source_project_sha256(source)]
    return hashlib.sha256(json.dumps(basis).encode("utf-8")).hexdigest()


def startup_blockers(environ=None, *, production: bool) -> tuple[Blocker, ...]:
    """Hosted-only conditions that make starting wrong.

    The secret key, the token key and the public address keep their existing
    owners (``create_app`` translates their refusals into the codes above);
    this adds what only a hosted process needs.  The database backend is read
    from ``app.db`` -- the runtime's own view -- and the storage variables
    from the adapter's own configuration reader.
    """
    from app import db as app_db
    from app.storage.object_store import CanonicalStoreError
    from app.storage.supabase_store import SupabaseStorageConfig

    env = _environ(environ)
    found: list[Blocker] = []
    try:
        postgres = app_db.database_backend() == "postgres"
    except ValueError:
        postgres = False
    if not postgres:
        found.append(Blocker(HOSTED_POSTGRES_REQUIRED, ("DATABASE_URL",)))
    if str(env.get(PROXY_TRUST_ENV) or "").strip().lower() not in _BOOLEAN_WORDS:
        found.append(Blocker(HOSTED_PROXY_TRUST_UNDECIDED, (PROXY_TRUST_ENV,)))
    if production:
        try:
            SupabaseStorageConfig.from_environment(env)
        except CanonicalStoreError as exc:
            names = tuple(name for name in exc.detail.split(",") if name)
            found.append(Blocker(HOSTED_STORAGE_CONFIG_REQUIRED, names))
    admission = admission_mode(env, production=production)
    if admission is None:
        found.append(Blocker(HOSTED_ADMISSION_UNDECIDED, (ADMISSION_ENV,)))
    elif admission == ADMISSION_OPERATOR and operator_token(env) is None:
        found.append(Blocker(HOSTED_OPERATOR_TOKEN_REQUIRED, (OPERATOR_TOKEN_ENV,)))
    elif admission == ADMISSION_OPEN and admission_must_be_decided(env, production=production) \
            and opening_reference(env) is None:
        found.append(Blocker(HOSTED_OPENING_REFERENCE_REQUIRED, (OPENING_REFERENCE_ENV,)))
    return tuple(found)


def require_ready(environ=None, *, production: bool) -> None:
    blockers = startup_blockers(environ, production=production)
    if blockers:
        raise HostingConfigurationError(blockers)


if __name__ == "__main__":
    # `python -m app.hosting` once ran the check; a CI gate that still calls it must fail, not pass.
    raise SystemExit("this module has no command line: use `python -m app.hosting_cli check`")


__all__ = [
    "ADMISSION_ENV",
    "ADMISSION_OPEN",
    "ADMISSION_OPERATOR",
    "Blocker",
    "HOSTED_ADMISSION_UNDECIDED",
    "HOSTED_OPENING_REFERENCE_REQUIRED",
    "HOSTED_OPERATOR_TOKEN_REQUIRED",
    "OPENING_REFERENCE_ENV",
    "OPERATOR_TOKEN_ENV",
    "OPERATOR_TOKEN_MIN_LENGTH",
    "admission_mode",
    "admission_must_be_decided",
    "opening_reference",
    "opening_tag",
    "operator_token",
    "CRON_SECRET_ENV",
    "CRON_SECRET_MIN_LENGTH",
    "SUPABASE_POOLER_SUFFIX",
    "SUPABASE_TRANSACTION_PORT",
    "connection_kind",
    "database_source",
    "project_sha256",
    "source_identity_sha256",
    "source_project_sha256",
    "supabase_project_ref",
    "cron_secret",
    "HOSTED_POSTGRES_REQUIRED",
    "HOSTED_PROXY_TRUST_UNDECIDED",
    "HOSTED_PUBLIC_URL_INVALID",
    "HOSTED_SECRET_KEY_REQUIRED",
    "HOSTED_STORAGE_CONFIG_REQUIRED",
    "HOSTED_TOKEN_KEY_REQUIRED",
    "HostingConfigurationError",
    "LOG_DIR_ENV",
    "MODE_HOSTED",
    "MODE_LOCAL",
    "PROXY_TRUST_ENV",
    "RUNTIME_ENV",
    "RUNTIME_MODE_INVALID",
    "RUNTIME_MODE_UNDECLARED",
    "apply_hosted_defaults",
    "declared_mode",
    "is_hosted",
    "require_declared_runtime",
    "require_ready",
    "scheduler_secret_configured",
    "scratch_root",
    "serverless_platform",
    "single",
    "startup_blockers",
]
