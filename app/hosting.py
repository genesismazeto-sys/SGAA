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
import re
import tempfile
from dataclasses import dataclass

RUNTIME_ENV = "SGAA_RUNTIME"
MODE_HOSTED = "hosted"
MODE_LOCAL = "local"
PROXY_TRUST_ENV = "TRUST_PROXY_XFF"
LOG_DIR_ENV = "APP_LOG_DIR"
#: Vercel Cron's own variable name; the scheduler front reads it (never a query string).
CRON_SECRET_ENV = "CRON_SECRET"
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
    ignored; any non-empty ASCII value is accepted (an HTTP header cannot carry
    anything else faithfully).
    """
    secret = str(_environ(environ).get(CRON_SECRET_ENV) or "").strip()
    return secret if secret and secret.isascii() else None


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


# ---------------------------------------------------------------------------
# what code runs: the runtime code identity (MP-3 A17)
# ---------------------------------------------------------------------------

#: The deployed files that ARE the application, as they arrive in the function unchanged.  The
#: deployment allowlist (``tools/deploy_audit``) adds the descriptors the platform reads, rewrites or
#: generates at build (observed on the rehearsal project, MP-3 A17: ``vercel.json`` arrives rewritten and
#: the Python builder adds ``pyproject.toml`` and ``uv.lock``; ``public`` is a build output and
#: ``.vercelignore`` no code).
CODE_PATHS = (
    "app", "services", "utils", "templates", "static", "main.py", "presets_api.py", "presets_data.json",
    "requirements.txt", ".python-version",
)
#: Every hosted response names the code that produced it (``app.web.admission_gate``).
CODE_HEADER = "X-SGAA-Code"
#: ... and the platform deployment that serves it, as the platform names it to the process.
DEPLOYMENT_HEADER = "X-SGAA-Deployment"


def git_blob_id(data: bytes) -> str:
    """The git object id of a file's bytes: what a commit names and what the export re-proves."""
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\x00" + data).hexdigest()


def is_code_path(relative: str) -> bool:
    parts = relative.split("/")
    return parts[0] in CODE_PATHS and "__pycache__" not in parts and not relative.endswith(".pyc")


def code_sha256(files) -> str:
    """SHA-256 of the sorted ``path NUL blob`` list of the code paths among ``files`` ({path: blob id})."""
    digest = hashlib.sha256()
    for path in sorted(path for path in files if is_code_path(path)):
        digest.update(path.encode("utf-8", "surrogatepass") + b"\x00" + files[path].encode("ascii") + b"\n")
    return digest.hexdigest()


def runtime_code_sha256(root=None) -> str:
    """The code identity of the files this process runs from (the directory holding ``app``).

    The same value ``deploy_audit`` computes from the reviewed export: the platform delivers the
    uploaded code paths byte for byte (proven on the rehearsal project, MP-3 A17).  Compiled caches
    are not code; a link is never followed.
    """
    from pathlib import Path

    base = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    files: dict[str, str] = {}
    for name in CODE_PATHS:
        top = base / name
        candidates = [top] if top.is_file() else sorted(top.rglob("*")) if top.is_dir() else []
        for path in candidates:
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(base).as_posix()
            if is_code_path(relative):
                files[relative] = git_blob_id(path.read_bytes())
    return code_sha256(files)


# ---------------------------------------------------------------------------
# the opening authorization (MP-3 A17)
# ---------------------------------------------------------------------------

#: An ``open`` production deployment admits users only while the PROD database holds an authorization
#: for its opening reference and its code, written by the cutover ledger when it records the reference
#: (and, after the point of no return, for a forward fix).  The row carries the ledger entry itself, so
#: the deployment re-derives the reference from it rather than trusting a well-formed value.  The
#: control schema is outside ``public``: no Layer-2 set, fingerprint or schema contract includes it.
OPENING_SCHEMA = "sgaa_cutover"
OPENING_DDL = (
    "CREATE SCHEMA IF NOT EXISTS sgaa_cutover",
    "REVOKE ALL ON SCHEMA sgaa_cutover FROM PUBLIC",
    "CREATE TABLE IF NOT EXISTS sgaa_cutover.opening ("
    " reference_sha256 text NOT NULL, code_sha256 text NOT NULL, entry text NOT NULL,"
    " created_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz,"
    " PRIMARY KEY (reference_sha256, code_sha256))",
    "REVOKE ALL ON sgaa_cutover.opening FROM PUBLIC",
)
OPENING_EXISTS_SQL = "SELECT to_regclass('sgaa_cutover.opening') IS NOT NULL"
OPENING_ROWS_SQL = "SELECT count(*) FROM sgaa_cutover.opening"
OPENING_INSERT_SQL = "INSERT INTO sgaa_cutover.opening (reference_sha256, code_sha256, entry) VALUES (%s, %s, %s)"
OPENING_SELECT_SQL = (
    "SELECT entry FROM sgaa_cutover.opening WHERE reference_sha256 = %s AND code_sha256 = %s AND revoked_at IS NULL"
)
OPENING_REVOKE_SQL = "UPDATE sgaa_cutover.opening SET revoked_at = now() WHERE revoked_at IS NULL"
OPENING_RESTORE_SQL = "UPDATE sgaa_cutover.opening SET revoked_at = NULL WHERE reference_sha256 = %s"
#: MP-3 A19 R3 M2: only the code the ledger currently authorizes may admit.  A new authorization (or a
#: product-contract amendment) revokes every other code of the reference; a resume restores only it.
OPENING_SUPERSEDE_SQL = (
    "UPDATE sgaa_cutover.opening SET revoked_at = now()"
    " WHERE reference_sha256 = %s AND code_sha256 <> %s AND revoked_at IS NULL"
)
OPENING_RESTORE_CODE_SQL = (
    "UPDATE sgaa_cutover.opening SET revoked_at = NULL WHERE reference_sha256 = %s AND code_sha256 = %s"
)
#: MP-3 A19 (17), the rereview of b83b5fc: an authorized CODE no longer admits by itself.  Every platform
#: deployment of that code -- a late or duplicate upload, one the ledger never recorded -- would inherit
#: it.  A deployment admits users only while PROD also holds an admission for ITS OWN platform identity,
#: written by the ledger for one recorded deployment (``admit-deployment`` before the point of no return,
#: ``authorize-code`` for a forward fix): an intact ledger entry naming the reference, this database, the
#: code, the project and the deployment.
ADMISSION_DDL = (
    "CREATE TABLE IF NOT EXISTS sgaa_cutover.admission ("
    " reference_sha256 text NOT NULL, deployment_id text NOT NULL, entry text NOT NULL,"
    " created_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz,"
    " PRIMARY KEY (reference_sha256, deployment_id))",
    "REVOKE ALL ON sgaa_cutover.admission FROM PUBLIC",
)
ADMISSION_INSERT_SQL = "INSERT INTO sgaa_cutover.admission (reference_sha256, deployment_id, entry) VALUES (%s, %s, %s)"
ADMISSION_SELECT_SQL = (
    "SELECT entry FROM sgaa_cutover.admission WHERE reference_sha256 = %s AND deployment_id = %s"
    " AND revoked_at IS NULL"
)
ADMISSION_EXISTS_SQL = "SELECT to_regclass('sgaa_cutover.admission') IS NOT NULL"
VERCEL_PROJECT_ENV = "VERCEL_PROJECT_ID"
#: The platform's own name for the deployment a process belongs to (a system variable, set at build and at
#: runtime, ``dpl_...``); an upload cannot choose it.
VERCEL_DEPLOYMENT_ENV = "VERCEL_DEPLOYMENT_ID"
_DEPLOYMENT_ID = re.compile(r"dpl_[A-Za-z0-9]{8,64}")


def ledger_canonical(entry: dict) -> bytes:
    """The cutover ledger's canonical bytes of an entry (``tools/cutover_ledger`` hashes these)."""
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def ledger_entry_hash(body: dict) -> str:
    return hashlib.sha256(ledger_canonical(body)).hexdigest()


def vercel_project_sha256(environ=None) -> str | None:
    """The platform project this process belongs to (the platform sets ``VERCEL_PROJECT_ID``)."""
    project = str(_environ(environ).get(VERCEL_PROJECT_ENV) or "").strip()
    return hashlib.sha256(project.encode("utf-8")).hexdigest() if project else None


def deployment_id(environ=None) -> str | None:
    """The platform deployment this process belongs to (``VERCEL_DEPLOYMENT_ID``), else None."""
    raw = str(_environ(environ).get(VERCEL_DEPLOYMENT_ENV) or "").strip()
    return raw if _DEPLOYMENT_ID.fullmatch(raw) else None


_AUTHORIZING_TYPES = frozenset({"reference", "authorization"})
_ADMITTING_TYPES = frozenset({"admission", "authorization"})


def opening_entry_authorizes(entry_text, *, reference: str, database_identity, code: str, project) -> bool:
    """Whether a stored ledger entry authorizes THIS process to admit users under ``reference``.

    The entry must be intact (its own hash), be the reference itself or a forward-fix authorization
    naming it, and name this database (its live identity), this code and this platform project.
    Anything else -- a value from another ledger, another reference, another database, another
    candidate or a hand-made row that is not a ledger entry -- authorizes nothing.
    """
    if not (reference and database_identity and code and project):
        return False
    try:
        entry = json.loads(entry_text)
        claimed = entry.pop("hash")
        intact = isinstance(claimed, str) and ledger_entry_hash(entry) == claimed
    except (TypeError, ValueError, KeyError, AttributeError):
        return False
    if not intact or entry.get("type") not in _AUTHORIZING_TYPES:
        return False
    names_reference = claimed == reference if entry["type"] == "reference" else \
        entry.get("opening_reference") == reference
    return (names_reference and entry.get("database_identity_sha256") == database_identity
            and entry.get("code_sha256") == code and entry.get("vercel_project_sha256") == project)


def deployment_entry_admits(entry_text, *, reference: str, database_identity, code: str, project,
                            deployment) -> bool:
    """Whether a stored ledger entry admits users at THIS deployment under ``reference`` (A19 (17)).

    The entry must be intact (its own hash), be an ``admission`` or a forward-fix ``authorization``
    naming the reference, and name this database, this code, this project and this platform deployment.
    No deployment identity -- a process the platform did not name -- is admitted by nothing.
    """
    if not (reference and database_identity and code and project and deployment):
        return False
    try:
        entry = json.loads(entry_text)
        claimed = entry.pop("hash")
        intact = isinstance(claimed, str) and ledger_entry_hash(entry) == claimed
    except (TypeError, ValueError, KeyError, AttributeError):
        return False
    return (intact and entry.get("type") in _ADMITTING_TYPES and entry.get("opening_reference") == reference
            and entry.get("database_identity_sha256") == database_identity and entry.get("code_sha256") == code
            and entry.get("vercel_project_sha256") == project and entry.get("deployment_id") == deployment)


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
    "SUPABASE_POOLER_SUFFIX",
    "SUPABASE_TRANSACTION_PORT",
    "connection_kind",
    "ADMISSION_DDL",
    "CODE_HEADER",
    "CODE_PATHS",
    "DEPLOYMENT_HEADER",
    "deployment_entry_admits",
    "deployment_id",
    "OPENING_DDL",
    "OPENING_SCHEMA",
    "code_sha256",
    "git_blob_id",
    "is_code_path",
    "ledger_canonical",
    "ledger_entry_hash",
    "opening_entry_authorizes",
    "runtime_code_sha256",
    "vercel_project_sha256",
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
