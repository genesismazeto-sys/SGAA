# coding: utf-8
"""SGAA PostgreSQL logical backup -> restore -> verify (Layer 2, operator tool).

WHY THIS EXISTS
    Provider backups / PITR (Layer 1) are not under SGAA's control.  This tool
    is the mandatory, operator-run Layer 2: a logical archive of the SGAA-owned
    objects in the ``public`` schema, retained independently of the provider,
    plus a non-sensitive manifest that a restore is verified against.  It is
    an operational command, never part of the web application: nothing in
    ``app/`` imports it and no route reaches it.

    python tools/pg_backup.py backup  --output-dir DIR --label LABEL
    python tools/pg_backup.py verify  --manifest FILE [--restored]
    python tools/pg_backup.py restore --manifest FILE

    Source: ``DATABASE_URL``.  Restore / verified target:
    ``SGAA_RESTORE_TARGET_URL``.  Native binaries: ``SGAA_PG_BIN_DIR`` when
    set, otherwise ``PATH``.  No option carries a URL or a password and there
    is no ``--force``.

SECRETS
    A URL holding a password or another secret-valued libpq parameter
    (userinfo, ``password=``, ``sslpassword=``, ``oauth_client_secret=``,
    ``scram_client_key=``, ``scram_server_key=``) is refused unread.
    Credentials come from libpq's pgpass file, or from ``PGPASSWORD`` already
    present in the operator's environment (inherited by the native tools,
    never placed on a command line).  Output names the database by a
    sanitized identity only; native-tool stderr is never forwarded -- it is
    reduced to an exit status and a fixed classification code.  A usage
    error never echoes the offending argument (it may be a pasted URL).

BACKUP
    Preconditions: PostgreSQL, ``current_schema() = public``, client majors
    >= server major, ``validate_pg_schema`` CURRENT (contract digest), the
    provisioner ``schema_migrations`` baseline, every contract trigger enabled,
    no extension objects in ``public`` and every Path-B domain check green.
    One ``REPEATABLE READ READ ONLY`` transaction exports its snapshot; the
    manifest's relational state is read in it and ``pg_dump --snapshot`` dumps
    the same snapshot while it stays open.  The source is never written.
    Identity sequences are not MVCC: pg_dump records their value when it reads
    them, which may be later (never lower) than the snapshot's view.  The
    manifest therefore records the archived value (what a restore yields)
    next to the in-snapshot observation and refuses an archive whose next id
    would not be above every row id in the snapshot.
    The archive's own TOC (``pg_restore --list``) must equal the SGAA contract
    exactly -- any other schema, object class, role/ACL entry or object is
    refused; the scope is proven from the artifact, not from the command line.

TABLE DATA POLICY (prod-1/v14)
    Every contract table is archived with its schema.  Two tables are
    archived SCHEMA ONLY (``pg_dump --exclude-table-data``) and their absence
    of TABLE DATA is part of the TOC contract, so it is proven from the
    artifact rather than assumed from "probably empty" tables:

    * ``storage_upload_intents`` -- EPHEMERAL_OMITTED: signed-upload workflow
      state is never restored; a restored database has no live intent.
    * ``storage_worker_status`` -- TARGET_SIDE_RECREATED: stale scheduler
      health is never restored; no row is the authoritative "never ran" state.

    ``storage_objects`` and the business ``storage_object_id`` references are
    archived in full.  The manifest adds a value-free canonical-storage census
    (counts by lifecycle / mirror state, total size, a reference digest over
    id/bucket/key/sha256/size -- no filename, no person).  Object BYTES live in
    the canonical bucket and are NOT part of this logical backup.

ARTIFACTS
    ``<base>.dump`` + ``<base>.dump.sha256`` + ``<base>.manifest.json`` are
    built under ``.sgaa-pgbackup-staging`` names (exclusive create, fsync),
    verified, and promoted without replacing anything, manifest last.  A
    failure before promotion removes only this run's files.  A hard kill can
    leave staging files (refused by the next backup into that directory until
    the operator removes them) or a set without its manifest (refused by
    verify/restore); never a partial file under a final name.

RESTORE
    Into a NEW, EMPTY PostgreSQL database only: UTF8, not the source, not the
    configured application database, not ``postgres``/``template0``/
    ``template1``/``sgaa_qual`` or a template, no non-system schema and no
    object in ``public``.  ``pg_restore --exit-on-error --single-transaction
    --no-owner --no-privileges`` with a filtered TOC list that skips only the
    public-schema entries (the target already has ``public``).  The target
    URL must route to exactly one host, port and database as libpq parses it
    (no multi-host list, no ``host`` / ``hostaddr`` / ``port`` / ``dbname`` /
    ``service`` / ``servicefile`` query override), so the preflight
    connection and pg_restore's own connection name the same target, and
    pg_restore is pinned to the numeric server address of the checked
    preflight connection (``PGHOSTADDR`` overwritten, ``PGSERVICE`` refused,
    service variables removed; the URL keeps the host name for TLS and
    pgpass) -- no second DNS lookup.  A failure rolls back; the tool then proves the target is still empty.  Once
    pg_restore has returned successfully the target holds the restored data:
    it is verified read-only against the manifest, and any verification
    failure, error or interruption from then on is ``RESTORE_VERIFY_FAILED``
    (exit 3), never a rollback.

EXIT
    0 ok; 1 refused / failed with nothing created or restored (or a verify
    mismatch); 2 usage; 3 restore needs reconciliation (pg_restore was
    interrupted, or it committed and the restored contents failed or could
    not complete verification: do not use or retry into that target; drop it
    and restore into a fresh one).
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app import pg_migrate_from_sqlite as pathb  # noqa: E402
from app import pg_schema  # noqa: E402

MANIFEST_FORMAT = "sgaa-pg-logical-backup"
MANIFEST_FORMAT_VERSION = 2
TOOL_VERSION = 2
SOURCE_URL_ENV = "DATABASE_URL"
TARGET_URL_ENV = "SGAA_RESTORE_TARGET_URL"
BIN_DIR_ENV = "SGAA_PG_BIN_DIR"
CONNECT_TIMEOUT_SECONDS = 15
NATIVE_QUERY_TIMEOUT_SECONDS = 300

DUMP_SUFFIX = ".dump"
SIDECAR_SUFFIX = ".dump.sha256"
MANIFEST_SUFFIX = ".manifest.json"
STAGING_SUFFIX = ".sgaa-pgbackup-staging"

PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})
#: Tables archived schema-only, with the manifest policy recorded for each.
SCHEMA_ONLY_TABLE_POLICIES = {
    "storage_upload_intents": "EPHEMERAL_OMITTED",
    "storage_worker_status": "TARGET_SIDE_RECREATED",
}
PG_DUMP_OPTIONS = (
    "--format=custom", "--schema=public", "--no-owner", "--no-privileges",
    *(f"--exclude-table-data=public.{table}" for table in SCHEMA_ONLY_TABLE_POLICIES),
)
PG_RESTORE_OPTIONS = ("--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_RECONCILE = 3

_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"\(PostgreSQL\)\s+(\d+)(?:\.(\d+))?")
_TOC_ENTRY_RE = re.compile(r"^(\d+); (\d+) (\d+) (.*)$")
_SETVAL_RE = re.compile(r"pg_catalog\.setval\('public\.([a-z0-9_]+)', (\d+), (true|false)\);")

IDENTITY_SEMANTICS = (
    "rows are the exported snapshot; identity sequences are read by pg_dump outside MVCC "
    "and may be ahead of the snapshot (never behind); a restore yields the archived "
    "sequence state, whose next id is above every archived row id"
)


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------


class BackupToolError(Exception):
    """Value-free failure: a fixed code plus a detail that never holds secrets."""

    exit_code = EXIT_FAILED
    verdict = "failed"

    def __init__(self, code: str, detail: str = "", mismatches=()) -> None:
        self.code = code
        self.detail = detail
        self.mismatches = list(mismatches)
        super().__init__(f"{code}: {detail}" if detail else code)


class Refused(BackupToolError):
    """A precondition failed; nothing was created, restored or changed."""

    verdict = "refused"


class Failed(BackupToolError):
    """The operation started and was undone (staging removed / restore rolled back)."""


class NeedsReconciliation(BackupToolError):
    """A restore may have committed, or committed contents that fail or escape verification."""

    exit_code = EXIT_RECONCILE
    verdict = "NEEDS RECONCILIATION"


class NativeToolError(BackupToolError):
    """A pg_dump / pg_restore run failed; stderr is classified, never forwarded."""


# ---------------------------------------------------------------------------
# connection strings and identities
# ---------------------------------------------------------------------------


#: libpq parameters whose value is itself a credential: the ones libpq marks
#: as password fields (dispchar ``*``) plus the SCRAM keys, which
#: authenticate on their own.  None may reach a native tool's argv.
SECRET_CONNINFO_KEYS = frozenset(
    {"password", "sslpassword", "oauth_client_secret", "scram_client_key", "scram_server_key"}
)
#: Query parameters that would route a connection away from the URL's one
#: visible host / port / database (or through a service-file entry).
ROUTING_QUERY_KEYS = frozenset({"host", "hostaddr", "port", "dbname", "service", "servicefile"})


def _query_keys(parts) -> set:
    return {key.lower() for key, _ in parse_qsl(parts.query, keep_blank_values=True)}


def _libpq_params(url, role, env_name) -> dict:
    """The parameters exactly as libpq parses ``url``; the URL is never echoed."""
    from psycopg.conninfo import conninfo_to_dict

    try:
        return conninfo_to_dict(url)
    except Exception:
        raise Refused(f"{role}_URL_INVALID", f"{env_name} cannot be parsed") from None


def require_url(value, env_name) -> str:
    """The PostgreSQL URL from ``env_name``; refused (unread) if it holds a secret."""
    role = "SOURCE" if env_name == SOURCE_URL_ENV else "TARGET"
    url = (value if value is not None else os.environ.get(env_name) or "").strip()
    if not url:
        raise Refused(f"{role}_REQUIRED", f"{env_name} must name the PostgreSQL database")
    if not url.startswith(("postgres://", "postgresql://")):
        raise Refused(f"{role}_NOT_POSTGRESQL", f"{env_name} is not a PostgreSQL URL")
    try:
        parts = urlsplit(url)
        password = parts.password
        query_keys = _query_keys(parts)
    except ValueError:
        raise Refused(f"{role}_URL_INVALID", f"{env_name} cannot be parsed") from None
    secret = password is not None or bool(query_keys & SECRET_CONNINFO_KEYS)
    if not secret:
        secret = bool(set(_libpq_params(url, role, env_name)) & SECRET_CONNINFO_KEYS)
    if secret:
        raise Refused(
            f"{role}_URL_CONTAINS_PASSWORD",
            f"{env_name} must not carry a password or other secret; use the libpq pgpass file "
            "(or PGPASSWORD in the environment)",
        )
    if not unquote(parts.path.lstrip("/")):
        raise Refused(f"{role}_URL_INVALID", f"{env_name} must name a database explicitly")
    return url


def require_single_target_route(url) -> None:
    """Refuse a restore target whose libpq routing is ambiguous.

    The preflight connection and pg_restore's own connection each open
    ``url``; both must reach the one host / port / database the URL shows.
    libpq's parse must therefore hold a single host and port, no ``hostaddr``
    or ``service``, and agree with the URL's visible endpoint (which also
    catches an encoded comma or any query override).  A name that resolves
    differently between the two connections (DNS) is closed separately:
    restore pins pg_restore to the checked connection's address.
    """
    detail = (
        f"{TARGET_URL_ENV} must name exactly one host, port and database "
        "(no multi-host list and no host/hostaddr/port/dbname/service/servicefile query parameter)"
    )
    params = _libpq_params(url, "TARGET", TARGET_URL_ENV)
    try:
        parts = urlsplit(url)
        visible = (unquote(parts.hostname or ""), str(parts.port or ""), url_database(url))
        overridden = bool(_query_keys(parts) & ROUTING_QUERY_KEYS)
    except ValueError:
        raise Refused("TARGET_URL_AMBIGUOUS", detail) from None
    resolved = (params.get("host", "").lower(), params.get("port", ""), params.get("dbname", ""))
    multiple = any("," in params.get(key, "") for key in ("host", "hostaddr", "port"))
    if overridden or multiple or "hostaddr" in params or "service" in params or visible != resolved:
        raise Refused("TARGET_URL_AMBIGUOUS", detail)


def url_database(url) -> str:
    return unquote(urlsplit(url).path.lstrip("/"))


def _url_endpoint(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        port = str(parts.port or 5432)
    except ValueError:
        port = "?"
    return (_normalize_host(host), port, url_database(url))


def _normalize_host(host) -> str:
    host = str(host or "").strip().lower()
    return "loopback" if host in {"localhost", "127.0.0.1", "::1", ""} else host


@dataclass(frozen=True)
class TargetIdentity:
    """Sanitized database identity: no password, no URL, no query parameters."""

    backend: str
    host: str
    port: str
    database: str
    user: str
    server_version: str
    system_identifier: str | None = None

    def label(self) -> str:
        return (
            f"backend={self.backend} host={self.host} port={self.port} "
            f"database={self.database} user={self.user} server_version={self.server_version}"
        )

    def as_dict(self) -> dict:
        return {
            "backend": self.backend,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "server_version": self.server_version,
            "system_identifier": self.system_identifier,
        }

    @classmethod
    def from_dict(cls, data) -> "TargetIdentity":
        return cls(**{name: data.get(name) for name in cls.__dataclass_fields__})


def same_database(left: TargetIdentity, right: TargetIdentity) -> bool:
    """Same cluster (system identifier) and database; endpoint fallback."""
    if left.system_identifier and right.system_identifier:
        return left.system_identifier == right.system_identifier and left.database == right.database
    return (_normalize_host(left.host), str(left.port), left.database) == (
        _normalize_host(right.host),
        str(right.port),
        right.database,
    )


def connect(url):
    import psycopg

    return psycopg.connect(
        url, prepare_threshold=None, autocommit=True, connect_timeout=CONNECT_TIMEOUT_SECONDS
    )


def _server_version_num(conn) -> int:
    return int(conn.execute("SHOW server_version_num").fetchone()[0])


def _format_version(version_num) -> str:
    return f"{version_num // 10000}.{version_num % 10000}"


def database_identity(conn) -> TargetIdentity:
    """Read on an autocommit connection, outside any transaction."""
    import psycopg

    version_num = _server_version_num(conn)
    database, user = conn.execute("SELECT current_database(), current_user").fetchone()
    try:
        system_identifier = str(conn.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0])
    except psycopg.Error:
        system_identifier = None
    info = conn.info
    return TargetIdentity(
        "postgresql", str(info.host), str(info.port), str(database), str(user),
        _format_version(version_num), system_identifier,
    )


# ---------------------------------------------------------------------------
# native tools
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NativeTool:
    name: str
    path: str
    version: str
    major: int


def _locate(name) -> str:
    bin_dir = (os.environ.get(BIN_DIR_ENV) or "").strip()
    if bin_dir:
        for candidate in (Path(bin_dir) / name, Path(bin_dir) / f"{name}.exe"):
            if candidate.is_file():
                return str(candidate)
        raise Refused("NATIVE_TOOL_MISSING", f"{name} not found in {BIN_DIR_ENV}")
    found = shutil.which(name)
    if not found:
        raise Refused("NATIVE_TOOL_MISSING", f"{name} not found on PATH (or set {BIN_DIR_ENV})")
    return found


#: Inherited libpq variables that could add hidden routing defaults to a
#: pinned restore; credential (PGPASSWORD / PGPASSFILE) and TLS (PGSSL*)
#: variables are deliberately kept.
SERVICE_ROUTING_ENV = ("PGSERVICE", "PGSERVICEFILE")


def _child_environment(pinned_hostaddr=None) -> dict:
    """The operator's environment for libpq (pgpass / PGPASSWORD), minus our URLs.

    With ``pinned_hostaddr`` (restore only) the connection's network address
    is the one the checked preflight connection used: ``PGHOSTADDR`` is
    overwritten, never inherited, and service-file routing is removed.  The
    URL keeps its host name for TLS verification and pgpass matching.
    """
    environment = dict(os.environ)
    environment.pop(SOURCE_URL_ENV, None)
    environment.pop(TARGET_URL_ENV, None)
    environment.setdefault("PGCONNECT_TIMEOUT", str(CONNECT_TIMEOUT_SECONDS))
    environment["PGAPPNAME"] = "sgaa-pg-backup"
    if pinned_hostaddr is not None:
        for name in SERVICE_ROUTING_ENV:
            environment.pop(name, None)
        environment["PGHOSTADDR"] = pinned_hostaddr
    return environment


_STDERR_CLASSES = (
    ("server version mismatch", "SERVER_VERSION_MISMATCH"),
    ("password authentication failed", "AUTHENTICATION_FAILED"),
    ("no password supplied", "AUTHENTICATION_FAILED"),
    ("authentication", "AUTHENTICATION_FAILED"),
    ("permission denied", "PERMISSION_DENIED"),
    ("already exists", "OBJECT_EXISTS"),
    ("snapshot", "SNAPSHOT_REJECTED"),
    ("does not appear to be a valid archive", "ARCHIVE_INVALID"),
    ("unsupported version", "ARCHIVE_INVALID"),
    ("could not read input file", "ARCHIVE_INVALID"),
    ("unexpected end of file", "ARCHIVE_INVALID"),
    ("could not open input file", "ARCHIVE_UNREADABLE"),
    ("could not connect", "CONNECTION_FAILED"),
    ("connection to server", "CONNECTION_FAILED"),
    ("could not translate host name", "CONNECTION_FAILED"),
    ("does not exist", "OBJECT_MISSING"),
)


def classify_stderr(stderr) -> str:
    text = (stderr or b"").decode("utf-8", "replace").lower() if isinstance(stderr, bytes) else str(stderr or "").lower()
    for needle, code in _STDERR_CLASSES:
        if needle in text:
            return code
    return "UNCLASSIFIED"


def run_native(argv, *, timeout=None, tool_name=None, pinned_hostaddr=None) -> subprocess.CompletedProcess:
    """Run a native PostgreSQL tool; never echoes its stderr or environment."""
    name = tool_name or Path(argv[0]).stem
    try:
        completed = subprocess.run(
            [str(part) for part in argv],
            env=_child_environment(pinned_hostaddr),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise Refused("NATIVE_TOOL_MISSING", f"{name} could not be started") from exc
    except subprocess.TimeoutExpired as exc:
        raise NativeToolError("NATIVE_TOOL_TIMEOUT", f"{name} did not finish in {timeout}s") from exc
    except OSError as exc:
        raise Refused("NATIVE_TOOL_UNUSABLE", f"{name}: {exc.__class__.__name__}") from exc
    if completed.returncode != 0:
        raise NativeToolError(
            "NATIVE_TOOL_FAILED",
            f"{name} exit={completed.returncode} class={classify_stderr(completed.stderr)}",
        )
    return completed


def parse_tool_version(text) -> tuple[str, int]:
    match = _VERSION_RE.search(text or "")
    if not match:
        raise Refused("NATIVE_TOOL_VERSION_UNKNOWN", "cannot read the native tool version")
    major = int(match.group(1))
    minor = match.group(2)
    return (f"{major}.{minor}" if minor is not None else str(major)), major


def _tool_version(path) -> tuple[str, int]:
    completed = run_native([path, "--version"], timeout=60)
    return parse_tool_version(completed.stdout.decode("utf-8", "replace"))


def discover_native_tools() -> dict:
    tools = {}
    for name in ("pg_dump", "pg_restore"):
        path = _locate(name)
        version, major = _tool_version(path)
        tools[name] = NativeTool(name, path, version, major)
    return tools


def require_client_not_older(tools, server_major) -> None:
    """pg_dump/pg_restore older than the server cannot represent it safely."""
    for name in ("pg_dump", "pg_restore"):
        if tools[name].major < server_major:
            raise Refused(
                "CLIENT_OLDER_THAN_SERVER",
                f"{name} {tools[name].version} is older than server major {server_major}",
            )


# ---------------------------------------------------------------------------
# archive table of contents
# ---------------------------------------------------------------------------

#: Every object class an SGAA archive may hold.  Anything else -- another
#: schema, an extension, an ACL / role / ownership entry, a view, a comment on
#: an object -- is refused.
TOC_CLASSES = (
    "FK CONSTRAINT",
    "SEQUENCE SET",
    "TABLE DATA",
    "CONSTRAINT",
    "FUNCTION",
    "SEQUENCE",
    "TRIGGER",
    "COMMENT",
    "SCHEMA",
    "INDEX",
    "TABLE",
)
#: The public schema itself: the target already has it, so restore skips them.
PUBLIC_SCHEMA_ENTRIES = frozenset({("SCHEMA", "-", "public"), ("COMMENT", "-", "SCHEMA public")})


@dataclass(frozen=True)
class TocEntry:
    raw: str
    dump_id: int
    desc: str
    namespace: str
    tag: str

    @property
    def key(self):
        return (self.desc, self.namespace, self.tag)


def parse_toc(listing: str) -> list[TocEntry]:
    entries = []
    for line in listing.splitlines():
        if not line.strip() or line.startswith(";"):
            continue
        match = _TOC_ENTRY_RE.match(line)
        if not match:
            raise Refused("TOC_UNREADABLE", "an archive TOC line has an unknown shape")
        rest = match.group(4)
        desc = next((name for name in TOC_CLASSES if rest.startswith(name + " ")), None)
        if desc is None:
            leading = " ".join(token for token in rest.split(" ")[:3] if token.isupper())
            raise Refused("TOC_UNEXPECTED_OBJECT_CLASS", f"archive holds a {leading or '?'} entry")
        namespace, _, tail = rest[len(desc) + 1:].partition(" ")
        tag = tail.rsplit(" ", 1)[0] if " " in tail else tail
        entries.append(TocEntry(line, int(match.group(1)), desc, namespace, tag))
    return entries


def _function_name(tag) -> str:
    return tag.split("(", 1)[0]


def expected_toc(sequence_names) -> dict:
    """``{class: set of tags}`` of the SGAA contract (functions by name)."""
    specs = pg_schema.PG_TABLE_SPECS
    tables = set(pg_schema.PG_SCHEMA_TABLES)
    sequences = set(sequence_names)
    return {
        "FUNCTION": set(pg_schema.PG_HELPERS) | {t["function"] for t in pg_schema.PG_TRIGGERS},
        "TABLE": tables,
        "TABLE DATA": tables - set(SCHEMA_ONLY_TABLE_POLICIES),
        "SEQUENCE": sequences,
        "SEQUENCE SET": sequences,
        "CONSTRAINT": {
            f"{table} {constraint['name']}"
            for table in tables
            for constraint in [specs[table]["primary_key"], *specs[table]["uniques"]]
        },
        "FK CONSTRAINT": {
            f"{table} {fk['name']}" for table in tables for fk in specs[table]["foreign_keys"]
        },
        "INDEX": set(pg_schema.PG_EXPLICIT_INDEXES),
        "TRIGGER": {f"{t['table']} {t['name']}" for t in pg_schema.PG_TRIGGERS},
    }


def _names(names, limit=5) -> str:
    names = sorted(names)
    return ", ".join(names[:limit]) + (f" (+{len(names) - limit})" if len(names) > limit else "")


def validate_toc(entries, sequence_names) -> dict:
    """Refuse anything outside the SGAA contract; return a non-sensitive census."""
    expected = expected_toc(sequence_names)
    seen = set()
    actual = {name: set() for name in expected}
    public_entries = 0
    for entry in entries:
        if entry.key in seen:
            raise Refused("TOC_DUPLICATE_ENTRY", f"{entry.desc} {entry.tag}")
        seen.add(entry.key)
        if entry.key in PUBLIC_SCHEMA_ENTRIES:
            public_entries += 1
            continue
        if entry.desc == "SCHEMA" or entry.namespace != "public":
            schema = entry.tag if entry.desc == "SCHEMA" else entry.namespace
            raise Refused("TOC_UNEXPECTED_SCHEMA", f"archive holds schema {schema!r}")
        if entry.desc == "COMMENT":
            raise Refused("TOC_UNEXPECTED_OBJECT", f"archive holds COMMENT {entry.tag}")
        tag = _function_name(entry.tag) if entry.desc == "FUNCTION" else entry.tag
        if entry.desc == "FUNCTION" and tag in actual["FUNCTION"]:
            raise Refused("TOC_DUPLICATE_ENTRY", f"FUNCTION {tag}")
        actual[entry.desc].add(tag)
    for name in expected:
        extra = actual[name] - expected[name]
        if extra:
            raise Refused("TOC_UNEXPECTED_OBJECT", f"{name}: {_names(extra)}")
        missing = expected[name] - actual[name]
        if missing:
            raise Refused("TOC_INCOMPLETE", f"{name} missing: {_names(missing)}")
    digest = hashlib.sha256(
        "\n".join(sorted(f"{e.desc}|{e.namespace}|{e.tag}" for e in entries)).encode("utf-8")
    ).hexdigest()
    return {
        "entries": len(entries),
        "classes": {name: len(actual[name]) for name in sorted(actual)},
        "public_schema_entries": public_entries,
        "sha256": digest,
    }


def read_toc(tools, dump_path) -> tuple[str, list[TocEntry]]:
    completed = run_native(
        [tools["pg_restore"].path, "--list", str(dump_path)], timeout=NATIVE_QUERY_TIMEOUT_SECONDS
    )
    listing = completed.stdout.decode("utf-8", "replace")
    return listing, parse_toc(listing)


def read_archived_identities(tools, dump_path, entries) -> dict:
    """``{sequence: (last_value, is_called)}`` exactly as a restore will set them."""
    lines = [entry.raw for entry in entries if entry.desc == "SEQUENCE SET"]
    with tempfile.TemporaryDirectory(prefix="sgaa-pgbackup-") as directory:
        list_path = Path(directory) / "sequences.list"
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        completed = run_native(
            [tools["pg_restore"].path, "--use-list", str(list_path), "--file", "-", str(dump_path)],
            timeout=NATIVE_QUERY_TIMEOUT_SECONDS,
        )
    text = completed.stdout.decode("utf-8", "replace")
    states = {}
    for name, value, called in _SETVAL_RE.findall(text):
        if name in states:
            raise Refused("TOC_DUPLICATE_ENTRY", f"SEQUENCE SET {name}")
        states[name] = (int(value), called == "true")
    if set(states) != {entry.tag for entry in entries if entry.desc == "SEQUENCE SET"}:
        raise Refused("ARCHIVE_SEQUENCES_UNREADABLE", "archived identity states do not match the TOC")
    return states


def restore_list(listing) -> str:
    """The archive listing with only the public-schema entries commented out."""
    lines = []
    for line in listing.splitlines():
        entries = parse_toc(line) if line.strip() and not line.startswith(";") else []
        if entries and entries[0].key in PUBLIC_SCHEMA_ENTRIES:
            line = ";" + line
        lines.append(line)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# relational state (read-only)
# ---------------------------------------------------------------------------

IDENTITY_TABLES = tuple(t for t in pg_schema.PG_SCHEMA_TABLES if pathb._identity_column(t))

_EXTENSION_OBJECTS_IN_PUBLIC = (
    "SELECT count(*) FROM pg_depend d "
    "JOIN pg_proc p ON d.classid = 'pg_proc'::regclass AND p.oid = d.objid "
    "WHERE d.deptype = 'e' AND p.pronamespace = 'public'::regnamespace"
)
_EXTENSION_RELATIONS_IN_PUBLIC = (
    "SELECT count(*) FROM pg_depend d "
    "JOIN pg_class c ON d.classid = 'pg_class'::regclass AND c.oid = d.objid "
    "WHERE d.deptype = 'e' AND c.relnamespace = 'public'::regnamespace"
)


def _sequence_tag(conn, table) -> str:
    name = pathb._sequence_name(conn, table, pathb._identity_column(table))
    return str(name).split(".", 1)[1] if "." in str(name) else str(name)


def _enabled_triggers(conn) -> int:
    rows = conn.execute(
        "SELECT t.tgname, t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE c.relnamespace = 'public'::regnamespace AND NOT t.tgisinternal"
    ).fetchall()
    expected = {trigger["name"] for trigger in pg_schema.PG_TRIGGERS}
    return sum(1 for name, enabled in rows if name in expected and enabled == "O")


def _accounts(conn) -> dict:
    one = lambda sql: int(conn.execute(sql).fetchone()[0])  # noqa: E731
    return {
        "usuarios": one("SELECT count(*) FROM usuarios"),
        "usuario_credenciais": one("SELECT count(*) FROM usuario_credenciais"),
        "admins": one("SELECT count(*) FROM usuarios WHERE tipo = 'admin'"),
        "full_admins": one(
            "SELECT count(*) FROM usuarios WHERE tipo = 'admin' AND nivel_acesso = 'admin_total'"
        ),
        "active_credentials": one("SELECT count(*) FROM usuario_credenciais WHERE acesso_ativo = 1"),
        "credential_states": {
            str(state): int(count)
            for state, count in conn.execute(
                "SELECT estado, count(*) FROM usuario_credenciais GROUP BY estado ORDER BY estado"
            ).fetchall()
        },
    }


def _storage_census(conn) -> dict:
    """Value-free canonical-storage census: counts, total size, reference digests."""
    def grouped(column):
        return {
            str(k): int(v)
            for k, v in conn.execute(
                f"SELECT {column}, count(*) FROM storage_objects GROUP BY {column} ORDER BY {column}"
            ).fetchall()
        }

    rows, total = conn.execute("SELECT count(*), COALESCE(sum(size_bytes), 0) FROM storage_objects").fetchone()
    objects = hashlib.sha256()
    for row in conn.execute(
        "SELECT id, storage_bucket, storage_key, sha256, size_bytes FROM storage_objects ORDER BY id"
    ).fetchall():
        objects.update(json.dumps([int(row[0]), str(row[1]), str(row[2]), str(row[3]), int(row[4])],
                                  separators=(",", ":")).encode("utf-8") + b"\n")
    references = hashlib.sha256()
    counts = {}
    for table in ("requisicao_arquivos", "admin_arquivos"):
        found = conn.execute(
            f"SELECT id, storage_object_id FROM {table} WHERE storage_object_id IS NOT NULL ORDER BY id"
        ).fetchall()
        counts[table] = len(found)
        for row in found:
            references.update(f"{table}:{int(row[0])}:{int(row[1])}\n".encode("utf-8"))
    return {
        "objects": int(rows),
        "total_size_bytes": int(total),
        "by_lifecycle_state": grouped("lifecycle_state"),
        "by_drive_sync_state": grouped("drive_sync_state"),
        "objects_digest": objects.hexdigest(),
        "business_references": counts,
        "business_references_digest": references.hexdigest(),
        "object_bytes": "NOT_INCLUDED_CANONICAL_BUCKET",
    }


@dataclass
class DatabaseState:
    schema: dict = field(default_factory=dict)
    database: dict = field(default_factory=dict)
    tables: dict = field(default_factory=dict)  # table -> {"rows", "sha256"}
    max_ids: dict = field(default_factory=dict)  # table -> max id or 0
    identities: dict = field(default_factory=dict)  # table -> {"sequence", "last_value", ...}
    domain: dict = field(default_factory=dict)
    triggers_enabled: int = 0
    accounts: dict = field(default_factory=dict)
    storage: dict = field(default_factory=dict)
    schema_only_sources: dict = field(default_factory=dict)  # table -> value-free source census


def read_state(conn) -> DatabaseState:
    """Everything the manifest describes, read with SELECTs only.

    Raises :class:`Refused` when the database is not the SGAA contract; domain
    results are returned for the caller to judge.
    """
    try:
        summary = pg_schema.validate_pg_schema(conn)
    except pg_schema.PostgresSchemaError as exc:
        raise Refused("SCHEMA_NOT_CURRENT", str(exc)) from exc
    if str(conn.execute("SELECT current_schema()").fetchone()[0]) != "public":
        raise Refused("SCHEMA_NOT_PUBLIC", "the SGAA contract must live in schema public")
    markers = [
        (int(v), str(n), str(e), str(d))
        for v, n, e, d in conn.execute(
            "SELECT version, name, schema_epoch, details_json FROM schema_migrations ORDER BY version"
        ).fetchall()
    ]
    seed = [(v, n, pg_schema.PG_SCHEMA_EPOCH, d) for v, n, d in pg_schema.PG_SCHEMA_MIGRATIONS_SEED]
    if markers != seed:
        raise Refused("SCHEMA_MIGRATIONS_NOT_BASELINE", "schema_migrations is not the prod-1/v14 baseline")
    epoch, version, contract = conn.execute(
        f"SELECT schema_epoch, schema_version, contract_sha256 FROM {pg_schema.PG_SCHEMA_META_TABLE}"
    ).fetchone()
    state = DatabaseState()
    state.schema = {
        "epoch": str(epoch),
        "version": int(version),
        "contract_sha256": str(contract),
        "latest_migration": {"version": markers[-1][0], "name": markers[-1][1]},
        "schema_migrations_rows": len(markers),
        "validated": {k: summary[k] for k in ("table_count", "constraint_count", "index_count", "trigger_count")},
    }
    encoding, collate, ctype = conn.execute(
        "SELECT pg_encoding_to_char(encoding), datcollate, datctype FROM pg_database "
        "WHERE datname = current_database()"
    ).fetchone()
    state.database = {"encoding": str(encoding), "collate": str(collate), "ctype": str(ctype)}
    extension_objects = int(conn.execute(_EXTENSION_OBJECTS_IN_PUBLIC).fetchone()[0]) + int(
        conn.execute(_EXTENSION_RELATIONS_IN_PUBLIC).fetchone()[0]
    )
    if extension_objects:
        raise Refused("EXTENSION_OBJECTS_IN_PUBLIC", f"{extension_objects} extension-owned object(s) in public")

    for table in pg_schema.PG_SCHEMA_TABLES:
        normalized = pathb.normalize_rows(table, pathb.read_target_rows(conn, table))
        state.tables[table] = {"rows": len(normalized), "sha256": pathb.table_digest(table, normalized)}
        column = pathb._identity_column(table)
        if column:
            position = pathb._columns(table).index(column)
            state.max_ids[table] = max((row[position] for row in normalized.values()), default=0)
    for table in IDENTITY_TABLES:
        last_value, is_called = pathb.read_identity_state(conn, table)
        state.identities[table] = {
            "column": pathb._identity_column(table),
            "sequence": _sequence_tag(conn, table),
            "last_value": last_value,
            "is_called": is_called,
            "predicted_next_id": last_value + 1 if is_called else last_value,
        }
    state.domain = pathb.run_domain_checks(conn)
    state.triggers_enabled = _enabled_triggers(conn)
    if state.triggers_enabled != len(pg_schema.PG_TRIGGERS):
        raise Refused(
            "TRIGGERS_NOT_ENABLED",
            f"{state.triggers_enabled} of {len(pg_schema.PG_TRIGGERS)} contract triggers enabled",
        )
    state.accounts = _accounts(conn)
    state.storage = _storage_census(conn)
    state.schema_only_sources = {
        "storage_upload_intents": {
            "rows_by_state": {
                str(k): int(v)
                for k, v in conn.execute(
                    "SELECT state, count(*) FROM storage_upload_intents GROUP BY state ORDER BY state"
                ).fetchall()
            }
        },
        "storage_worker_status": {
            "rows": int(conn.execute("SELECT count(*) FROM storage_worker_status").fetchone()[0])
        },
    }
    return state


def _begin_snapshot(conn) -> None:
    conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")


def _end_transaction(conn) -> None:
    try:
        conn.execute("ROLLBACK")
    except Exception:  # pragma: no cover - a broken connection ends the transaction anyway
        pass


# ---------------------------------------------------------------------------
# artifact files
# ---------------------------------------------------------------------------


def file_sha256(path) -> tuple[int, str]:
    return pathb.file_sha256(path)


def _canonical(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def seal_manifest(manifest: dict) -> dict:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return {**body, "manifest_sha256": hashlib.sha256(_canonical(body)).hexdigest()}


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sidecar_bytes(sha256, dump_name) -> bytes:
    return f"{sha256}  {dump_name}\n".encode("ascii")


def _inside_repository(path) -> bool:
    try:
        Path(path).resolve().relative_to(REPOSITORY_ROOT)
        return True
    except ValueError:
        return False


@dataclass
class ArtifactPaths:
    directory: Path
    base: str

    @property
    def dump(self) -> Path:
        return self.directory / (self.base + DUMP_SUFFIX)

    @property
    def sidecar(self) -> Path:
        return self.directory / (self.base + SIDECAR_SUFFIX)

    @property
    def manifest(self) -> Path:
        return self.directory / (self.base + MANIFEST_SUFFIX)

    def finals(self):
        return (self.dump, self.sidecar, self.manifest)

    @staticmethod
    def staging(final: Path) -> Path:
        return final.with_name(final.name + STAGING_SUFFIX)


def check_output_directory(output_dir) -> Path:
    directory = Path(output_dir)
    if not directory.is_dir():
        raise Refused("OUTPUT_DIR_MISSING", "the output directory does not exist")
    if _inside_repository(directory):
        raise Refused(
            "OUTPUT_INSIDE_REPOSITORY", "backups hold application data; write them outside the repository"
        )
    leftovers = sorted(path.name for path in directory.iterdir() if path.name.endswith(STAGING_SUFFIX))
    if leftovers:
        raise Refused(
            "STAGING_LEFTOVER",
            f"an interrupted run left {_names(leftovers, 3)}; staging files are never a "
            "backup -- remove them and rerun",
        )
    return directory


class _StagedSet:
    """Writes the three artifacts under staging names; promotes without replacing."""

    def __init__(self, paths: ArtifactPaths):
        self.paths = paths
        self.created = []  # staging files this run created
        self.promoted = []  # final names this run created

    def claim(self, final: Path) -> Path:
        staging = ArtifactPaths.staging(final)
        try:
            handle = open(staging, "xb")
        except FileExistsError as exc:
            raise Failed("STAGING_LEFTOVER", f"{staging.name} appeared during the run") from exc
        handle.close()
        self.created.append(staging)
        return staging

    def write(self, final: Path, data: bytes) -> Path:
        staging = self.claim(final)
        with open(staging, "r+b") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return staging

    @staticmethod
    def sync(path: Path) -> None:
        with open(path, "r+b") as handle:
            os.fsync(handle.fileno())

    def promote(self) -> None:
        for final in self.paths.finals():  # manifest last: it marks a complete set
            staging = ArtifactPaths.staging(final)
            try:
                pathb._promote_without_replacing(staging, final)
            except FileExistsError as exc:
                raise Failed("ARTIFACT_EXISTS", f"{final.name} already exists; nothing replaced") from exc
            self.created.remove(staging)
            self.promoted.append(final)

    def undo(self) -> None:
        for path in reversed(self.promoted + self.created):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        self.promoted, self.created = [], []


def _git_sha() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(REPOSITORY_ROOT), capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    sha = completed.stdout.decode("ascii", "replace").strip()
    return sha if completed.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", sha) else None


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


@dataclass
class BackupResult:
    paths: ArtifactPaths
    manifest: dict


def _check_identities(state: DatabaseState, archived: dict) -> dict:
    """Archived identity state per table; refuses a collision risk or a regression."""
    identities = {}
    for table in IDENTITY_TABLES:
        observed = state.identities[table]
        if observed["sequence"] not in archived:
            raise Refused("ARCHIVE_SEQUENCES_UNREADABLE", f"no archived state for {table}")
        last_value, is_called = archived[observed["sequence"]]
        predicted = last_value + 1 if is_called else last_value
        if predicted < observed["predicted_next_id"]:
            raise Refused("SEQUENCE_REGRESSED", f"{table} identity moved backwards during the dump")
        if predicted <= state.max_ids[table]:
            raise Refused("IDENTITY_BELOW_ROWS", f"{table} next id would collide with an existing row")
        identities[table] = {
            "column": observed["column"],
            "sequence": observed["sequence"],
            "last_value": last_value,
            "is_called": is_called,
            "predicted_next_id": predicted,
            "max_id": state.max_ids[table],
            "observed_in_snapshot_transaction": {
                "last_value": observed["last_value"],
                "is_called": observed["is_called"],
                "predicted_next_id": observed["predicted_next_id"],
            },
        }
    return identities


#: A schema-only table restores empty: its manifest entry is that state.
_EMPTY_TABLE = {
    table: {"rows": 0, "sha256": pathb.table_digest(table, {})} for table in SCHEMA_ONLY_TABLE_POLICIES
}


def build_manifest(*, created_at, label, identity, server_num, tools, paths, size, sha256, state,
                   identities, census) -> dict:
    failing = sorted(name for name, count in state.domain.items() if count)
    manifest = {
        "format": MANIFEST_FORMAT,
        "format_version": MANIFEST_FORMAT_VERSION,
        "result": "ok",
        "created_at": created_at,
        "label": label,
        "scope": {
            "kind": "SGAA application backup (public schema only; not a cluster or provider dump)",
            "schema": "public",
            "pg_dump_options": list(PG_DUMP_OPTIONS),
        },
        "source": identity.as_dict(),
        "server": {"version": _format_version(server_num), "version_num": server_num,
                   "major": server_num // 10000, **state.database},
        "native_tools": {name: {"version": tool.version, "major": tool.major} for name, tool in tools.items()},
        "artifact": {"file": paths.dump.name, "sidecar": paths.sidecar.name, "format": "custom",
                     "size": size, "sha256": sha256},
        "consistency": {"mode": "exported_snapshot", "transaction": "REPEATABLE READ READ ONLY",
                        "identity_semantics": IDENTITY_SEMANTICS},
        "schema": state.schema,
        "tables": {
            table: (_EMPTY_TABLE[table] if table in SCHEMA_ONLY_TABLE_POLICIES else summary)
            for table, summary in state.tables.items()
        },
        "table_data_policy": {
            table: {"policy": policy, "restored_rows": 0, "source": state.schema_only_sources[table]}
            for table, policy in SCHEMA_ONLY_TABLE_POLICIES.items()
        },
        "storage": state.storage,
        "identities": identities,
        "toc": census,
        "domain_validation": {"checks": len(state.domain), "failing": len(failing), "results": state.domain},
        "triggers": {"expected": len(pg_schema.PG_TRIGGERS), "enabled": state.triggers_enabled},
        "accounts": state.accounts,
        "tool": {"name": "tools/pg_backup.py", "version": TOOL_VERSION, "git_sha": _git_sha(),
                 "sha256": file_sha256(Path(__file__))[1]},
    }
    return seal_manifest(manifest)


def backup(output_dir, label, *, database_url=None, announce=lambda line: None,
           after_snapshot_export=None, now=None) -> BackupResult:
    """Validate the source, dump one exported snapshot, verify, then promote."""
    url = require_url(database_url, SOURCE_URL_ENV)
    if not _LABEL_RE.match(str(label or "")):
        raise Refused("LABEL_INVALID", "label: 1-40 of a-z 0-9 '-', starting alphanumeric")
    directory = check_output_directory(output_dir)
    tools = discover_native_tools()
    moment = now or datetime.now(timezone.utc)
    created_at = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    paths = ArtifactPaths(directory, f"sgaa-pg-{moment.strftime('%Y%m%dT%H%M%SZ')}-{label}")
    for final in paths.finals():
        if os.path.lexists(final) or os.path.lexists(ArtifactPaths.staging(final)):
            raise Refused("ARTIFACT_EXISTS", f"{final.name} already exists; nothing replaced")

    conn = connect(url)
    staged = _StagedSet(paths)
    try:
        identity = database_identity(conn)
        announce(f"source: {identity.label()}")
        announce(f"native: pg_dump={tools['pg_dump'].version} pg_restore={tools['pg_restore'].version}")
        server_num = _server_version_num(conn)
        require_client_not_older(tools, server_num // 10000)

        _begin_snapshot(conn)
        snapshot = str(conn.execute("SELECT pg_export_snapshot()").fetchone()[0])
        if after_snapshot_export is not None:
            after_snapshot_export()
        state = read_state(conn)
        failing = sorted(name for name, count in state.domain.items() if count)
        if failing:
            raise Refused("DOMAIN_CHECKS_FAILED", _names(failing))
        announce(
            f"snapshot: exported; schema {state.schema['epoch']}/v{state.schema['version']} "
            f"CURRENT; domain checks {len(state.domain)} green"
        )
        try:
            staging_dump = staged.claim(paths.dump)
            run_native([tools["pg_dump"].path, *PG_DUMP_OPTIONS, "--no-password",
                        f"--snapshot={snapshot}", "--file", str(staging_dump), "--dbname", url])
        finally:
            _end_transaction(conn)  # the snapshot is held exactly until pg_dump returns
        conn.close()

        _StagedSet.sync(staging_dump)
        size, sha256 = file_sha256(staging_dump)
        _listing, entries = read_toc(tools, staging_dump)
        census = validate_toc(entries, [i["sequence"] for i in state.identities.values()])
        identities = _check_identities(state, read_archived_identities(tools, staging_dump, entries))
        manifest = build_manifest(
            created_at=created_at, label=label, identity=identity, server_num=server_num, tools=tools,
            paths=paths, size=size, sha256=sha256, state=state, identities=identities, census=census,
        )
        if file_sha256(staging_dump) != (size, sha256):
            raise Failed("ARTIFACT_CHANGED", "the staged dump changed while it was being verified")
        staged.write(paths.sidecar, sidecar_bytes(sha256, paths.dump.name))
        staged.write(paths.manifest, manifest_bytes(manifest))
        staged.promote()
    except BaseException:
        staged.undo()
        raise
    finally:
        if not conn.closed:
            conn.close()
    return BackupResult(paths, manifest)


# ---------------------------------------------------------------------------
# artifact verification
# ---------------------------------------------------------------------------


@dataclass
class LoadedArtifact:
    manifest_path: Path
    dump_path: Path
    manifest: dict
    listing: str
    entries: list
    tools: dict


def load_manifest(manifest_path) -> dict:
    path = Path(manifest_path)
    if not path.name.endswith(MANIFEST_SUFFIX) or not path.is_file():
        raise Refused("MANIFEST_MISSING", "no <base>.manifest.json at the given path")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise Refused("MANIFEST_INVALID", "the manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != MANIFEST_FORMAT:
        raise Refused("MANIFEST_INVALID", "not an SGAA PostgreSQL backup manifest")
    if manifest.get("format_version") != MANIFEST_FORMAT_VERSION:
        raise Refused("MANIFEST_INVALID", "unsupported manifest format_version")
    if seal_manifest(manifest).get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise Refused("MANIFEST_DIGEST_MISMATCH", "the manifest was altered after it was written")
    if manifest.get("result") != "ok":
        raise Refused("MANIFEST_INVALID", "the manifest does not record a successful backup")
    try:
        artifact = manifest["artifact"]
        base = path.name[: -len(MANIFEST_SUFFIX)]
        if artifact["file"] != base + DUMP_SUFFIX or artifact["sidecar"] != base + SIDECAR_SUFFIX:
            raise Refused("MANIFEST_INVALID", "artifact names do not match the manifest name")
        if not _SHA256_RE.match(str(artifact["sha256"])) or not isinstance(artifact["size"], int):
            raise Refused("MANIFEST_INVALID", "artifact size/sha256 malformed")
        if set(manifest["identities"]) != set(IDENTITY_TABLES):
            raise Refused("MANIFEST_INVALID", "identity table set differs from the contract")
        if set(manifest["tables"]) != set(pg_schema.PG_SCHEMA_TABLES):
            raise Refused("MANIFEST_INVALID", "table set differs from the contract")
        policies = {t: entry["policy"] for t, entry in manifest["table_data_policy"].items()}
        if policies != SCHEMA_ONLY_TABLE_POLICIES:
            raise Refused("MANIFEST_INVALID", "table data policy differs from the contract")
        for table in SCHEMA_ONLY_TABLE_POLICIES:
            if manifest["tables"][table] != _EMPTY_TABLE[table]:
                raise Refused("MANIFEST_INVALID", f"{table} must be recorded as restored empty")
        if not isinstance(manifest["storage"], dict):
            raise Refused("MANIFEST_INVALID", "storage census missing")
    except (KeyError, TypeError) as exc:
        raise Refused("MANIFEST_INVALID", "required manifest fields are missing") from exc
    return manifest


def verify_artifact(manifest_path, *, announce=lambda line: None) -> LoadedArtifact:
    """Manifest seal, sidecar, artifact hash and archive TOC -- no database."""
    manifest = load_manifest(manifest_path)
    directory = Path(manifest_path).parent
    dump_path = directory / manifest["artifact"]["file"]
    sidecar_path = directory / manifest["artifact"]["sidecar"]
    if not dump_path.is_file():
        raise Refused("ARTIFACT_MISSING", f"{dump_path.name} is missing")
    if not sidecar_path.is_file():
        raise Refused("SIDECAR_MISSING", f"{sidecar_path.name} is missing")
    expected = manifest["artifact"]["sha256"]
    if sidecar_path.read_bytes() != sidecar_bytes(expected, dump_path.name):
        raise Refused("SIDECAR_MISMATCH", "the .sha256 sidecar disagrees with the manifest")
    if file_sha256(dump_path) != (manifest["artifact"]["size"], expected):
        raise Refused("ARTIFACT_SHA_MISMATCH", "the dump does not match its recorded size/SHA-256")
    tools = discover_native_tools()
    listing, entries = read_toc(tools, dump_path)
    sequences = [manifest["identities"][t]["sequence"] for t in IDENTITY_TABLES]
    census = validate_toc(entries, sequences)
    if census != manifest["toc"]:
        raise Refused("TOC_MISMATCH", "the archive TOC differs from the manifest census")
    archived = read_archived_identities(tools, dump_path, entries)
    for table in IDENTITY_TABLES:
        recorded = manifest["identities"][table]
        if archived.get(recorded["sequence"]) != (recorded["last_value"], recorded["is_called"]):
            raise Refused("ARCHIVE_IDENTITY_MISMATCH", f"{table} archived identity differs from the manifest")
    announce(f"artifact: {dump_path.name} size={manifest['artifact']['size']} sha256={expected} verified")
    announce(f"toc: {census['entries']} entries, SGAA contract only, sha256={census['sha256']}")
    return LoadedArtifact(Path(manifest_path), dump_path, manifest, listing, entries, tools)


# ---------------------------------------------------------------------------
# restored-database verification
# ---------------------------------------------------------------------------


def compare_state(manifest, state: DatabaseState) -> list[tuple[str, str]]:
    """Value-free ``(category, object)`` differences between manifest and database."""
    mismatches = []
    schema = manifest["schema"]
    for key in ("epoch", "version", "contract_sha256", "latest_migration", "schema_migrations_rows"):
        if state.schema.get(key) != schema.get(key):
            mismatches.append(("SCHEMA_META_MISMATCH", key))
    for table in pg_schema.PG_SCHEMA_TABLES:
        recorded, actual = manifest["tables"][table], state.tables[table]
        if actual["rows"] != recorded["rows"]:
            mismatches.append(("ROW_COUNT_MISMATCH", table))
        elif actual["sha256"] != recorded["sha256"]:
            mismatches.append(("ROW_DIGEST_MISMATCH", table))
    for table in IDENTITY_TABLES:
        recorded, actual = manifest["identities"][table], state.identities[table]
        if (actual["sequence"], actual["last_value"], actual["is_called"], actual["predicted_next_id"]) != (
            recorded["sequence"], recorded["last_value"], recorded["is_called"], recorded["predicted_next_id"]
        ):
            mismatches.append(("IDENTITY_MISMATCH", table))
        if actual["predicted_next_id"] <= state.max_ids[table]:
            mismatches.append(("IDENTITY_COLLISION_RISK", table))
    for name, count in sorted(state.domain.items()):
        if count:
            mismatches.append(("DOMAIN_CHECK_FAILED", name))
    if set(state.domain) != set(manifest["domain_validation"]["results"]):
        mismatches.append(("DOMAIN_CHECK_SET_MISMATCH", "*"))
    if state.triggers_enabled != manifest["triggers"]["enabled"]:
        mismatches.append(("TRIGGERS_MISMATCH", "*"))
    if state.accounts != manifest["accounts"]:
        mismatches.append(("ACCOUNT_CARDINALITY_MISMATCH", "usuarios/usuario_credenciais"))
    if state.storage != manifest["storage"]:
        mismatches.append(("STORAGE_CENSUS_MISMATCH", "storage_objects"))
    for table in SCHEMA_ONLY_TABLE_POLICIES:
        if state.tables[table]["rows"]:
            mismatches.append(("SCHEMA_ONLY_TABLE_NOT_EMPTY", table))
    return mismatches


def verify_database(manifest, url, *, announce=lambda line: None) -> DatabaseState:
    """Read-only comparison of a database against the manifest; consumes nothing."""
    conn = connect(url)
    try:
        identity = database_identity(conn)
        announce(f"verified database: {identity.label()}")
        _begin_snapshot(conn)
        try:
            state = read_state(conn)
        finally:
            _end_transaction(conn)
    finally:
        conn.close()
    mismatches = compare_state(manifest, state)
    if mismatches:
        raise Failed("VERIFY_FAILED", f"{len(mismatches)} difference(s) from the manifest", mismatches)
    announce(
        f"verified: schema CURRENT; {len(state.tables)} tables rows+digests equal; "
        f"{len(state.identities)} identities equal; {len(state.domain)} domain checks green; "
        f"{state.triggers_enabled} triggers enabled; accounts equal; storage census equal; "
        f"schema-only tables empty ({', '.join(sorted(SCHEMA_ONLY_TABLE_POLICIES))})"
    )
    return state


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

#: A plain-PostgreSQL target is EMPTY when every count is zero: no schema but
#: the system ones and ``public``, and nothing in ``public`` that a restore
#: could collide with (no extension but plpgsql, no event trigger).
EMPTY_TARGET_CHECKS = {
    "schemas": (
        "SELECT count(*) FROM pg_namespace WHERE nspname NOT IN "
        "('public', 'pg_catalog', 'information_schema', 'pg_toast') "
        "AND nspname !~ '^pg_(toast_)?temp_[0-9]+$'"
    ),
    "relations": "SELECT count(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace",
    "routines": "SELECT count(*) FROM pg_proc WHERE pronamespace = 'public'::regnamespace",
    "types": "SELECT count(*) FROM pg_type WHERE typnamespace = 'public'::regnamespace",
    "collations": "SELECT count(*) FROM pg_collation WHERE collnamespace = 'public'::regnamespace",
    "operators": "SELECT count(*) FROM pg_operator WHERE oprnamespace = 'public'::regnamespace",
    "extensions": "SELECT count(*) FROM pg_extension WHERE extname <> 'plpgsql'",
    "event_triggers": "SELECT count(*) FROM pg_event_trigger",
}


def target_occupancy(conn) -> dict:
    if conn.execute("SELECT to_regnamespace('public')").fetchone()[0] is None:
        raise Refused("TARGET_PUBLIC_SCHEMA_MISSING", "the target has no public schema")
    return {name: int(conn.execute(sql).fetchone()[0]) for name, sql in EMPTY_TARGET_CHECKS.items()}


def _check_target(conn, manifest, tools) -> TargetIdentity:
    identity = database_identity(conn)
    if identity.database in PROTECTED_DATABASES:
        raise Refused("TARGET_PROTECTED", f"never restore into {identity.database!r}")
    if conn.execute("SELECT datistemplate FROM pg_database WHERE datname = current_database()").fetchone()[0]:
        raise Refused("TARGET_PROTECTED", "the target is a template database")
    if same_database(identity, TargetIdentity.from_dict(manifest["source"])):
        raise Refused("TARGET_IS_SOURCE", "the target is the database this backup was taken from")
    encoding = str(conn.execute("SHOW server_encoding").fetchone()[0])
    if encoding != pg_schema.PG_REQUIRED_SERVER_ENCODING:
        raise Refused("TARGET_ENCODING_UNSUPPORTED", f"server_encoding {encoding}, UTF8 required")
    target_major = _server_version_num(conn) // 10000
    if target_major < int(manifest["server"]["major"]):
        raise Refused("TARGET_OLDER_THAN_SOURCE", f"target major {target_major} < source major "
                      f"{manifest['server']['major']}")
    if tools["pg_restore"].major < int(manifest["native_tools"]["pg_dump"]["major"]):
        raise Refused("CLIENT_OLDER_THAN_ARCHIVE", "pg_restore is older than the pg_dump that wrote the archive")
    require_client_not_older(tools, target_major)
    if not conn.execute("SELECT has_schema_privilege('public', 'CREATE')").fetchone()[0]:
        raise Refused("TARGET_PUBLIC_NOT_WRITABLE", "the restoring role cannot create objects in public")
    occupied = {name: count for name, count in target_occupancy(conn).items() if count}
    if occupied:
        raise Refused(
            "TARGET_NOT_EMPTY",
            "restore only into a new empty database; found " + ", ".join(f"{k}={v}" for k, v in sorted(occupied.items())),
        )
    return identity


def checked_hostaddr(conn) -> str:
    """The numeric address the checked target connection actually uses.

    Refused when libpq reports none (or anything but one IPv4 / IPv6
    address): pg_restore is never left to resolve the host name again.
    """
    try:
        return str(ipaddress.ip_address(str(conn.info.hostaddr or "").strip()))
    except Exception:
        raise Refused(
            "TARGET_HOSTADDR_UNAVAILABLE",
            "the checked target connection reports no numeric server address to pin pg_restore to",
        ) from None


def _refuse_service_routing() -> None:
    """PGSERVICE would add service-file defaults to the preflight connection
    that the pinned pg_restore no longer sees: refuse rather than diverge."""
    if (os.environ.get("PGSERVICE") or "").strip():
        raise Refused(
            "TARGET_ENV_ROUTING",
            f"PGSERVICE is set; unset it and name the restore target only by {TARGET_URL_ENV}",
        )


def _refuse_before_connecting(url) -> None:
    database = url_database(url)
    if database in PROTECTED_DATABASES:
        raise Refused("TARGET_PROTECTED", f"never restore into {database!r}")
    configured = (os.environ.get(SOURCE_URL_ENV) or "").strip()
    if configured.startswith(("postgres://", "postgresql://")):
        try:
            if _url_endpoint(configured) == _url_endpoint(url):
                raise Refused("TARGET_IS_SOURCE", f"the target is the database named by {SOURCE_URL_ENV}")
        except ValueError:
            pass


def _target_still_empty(url) -> bool | None:
    try:
        conn = connect(url)
    except Exception:
        return None
    try:
        return not any(target_occupancy(conn).values())
    except Exception:
        return None
    finally:
        conn.close()


def _restored_but_unverified(exc: BaseException) -> NeedsReconciliation:
    """pg_restore committed; verification then failed, errored or was interrupted."""
    if isinstance(exc, BackupToolError):
        reason, mismatches = str(exc), exc.mismatches
    else:  # psycopg / OS error or interruption: class and SQLSTATE only
        state = getattr(exc, "sqlstate", None)
        reason, mismatches = exc.__class__.__name__ + (f" sqlstate={state}" if state else ""), ()
    return NeedsReconciliation(
        "RESTORE_VERIFY_FAILED",
        f"pg_restore completed and committed, but verification failed or could not complete ({reason}); "
        "the target holds restored data -- do not use it and do not restore into it again; after "
        "investigation drop it and restore into a freshly created database",
        mismatches,
    )


def restore(manifest_path, *, target_url=None, announce=lambda line: None) -> DatabaseState:
    loaded = verify_artifact(manifest_path, announce=announce)
    manifest = loaded.manifest
    url = require_url(target_url, TARGET_URL_ENV)
    require_single_target_route(url)
    _refuse_service_routing()
    _refuse_before_connecting(url)
    conn = connect(url)
    try:
        identity = _check_target(conn, manifest, loaded.tools)
        hostaddr = checked_hostaddr(conn)
    finally:
        conn.close()
    announce(f"target: {identity.label()} (empty, UTF8, not the source)")

    committed = False
    try:
        with tempfile.TemporaryDirectory(prefix="sgaa-pgrestore-") as directory:
            list_path = Path(directory) / "restore.list"
            list_path.write_text(restore_list(loaded.listing), encoding="utf-8")
            try:
                run_native([loaded.tools["pg_restore"].path, *PG_RESTORE_OPTIONS, "--no-password",
                            "--use-list", str(list_path), "--dbname", url, str(loaded.dump_path)],
                           pinned_hostaddr=hostaddr)
                committed = True
            except NativeToolError as exc:
                # pg_restore ended on its own: its single transaction never committed.
                if _target_still_empty(url):
                    raise Failed("RESTORE_FAILED", f"{exc.detail}; single transaction rolled back, "
                                 "target verified still empty") from exc
                raise NeedsReconciliation("RESTORE_OUTCOME_UNCERTAIN", f"{exc.detail}; the target is "
                                          "not provably empty -- drop it and restore into a new database") from exc
            except BaseException as exc:
                # Interrupted: COMMIT may already be on its way; claim nothing.
                raise NeedsReconciliation(
                    "RESTORE_OUTCOME_UNCERTAIN",
                    f"{exc.__class__.__name__} during pg_restore; drop the target and restore into a new database",
                ) from exc
        announce("restore: pg_restore completed and committed (single transaction)")
        return verify_database(manifest, url, announce=announce)
    except BaseException as exc:
        # From the moment pg_restore returned 0 the target is RESTORED: no
        # later failure or interruption may be reported as a rollback.
        if not committed or isinstance(exc, NeedsReconciliation):
            raise
        raise _restored_but_unverified(exc) from exc


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------


class _NoEchoArgumentParser(argparse.ArgumentParser):
    """argparse whose errors never repeat the offending token (it may be a URL)."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(
            EXIT_USAGE,
            "pg-backup: usage error: unknown, missing or malformed arguments "
            "(arguments are never echoed; see --help)\n",
        )


def _parser() -> argparse.ArgumentParser:
    parser = _NoEchoArgumentParser(
        prog="python tools/pg_backup.py",
        allow_abbrev=False,
        description=(
            "SGAA PostgreSQL logical backup / restore / verify. Source: DATABASE_URL; "
            "restore target: SGAA_RESTORE_TARGET_URL; credentials via pgpass. "
            "No URL or password options and no --force."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    backup_parser = commands.add_parser("backup", allow_abbrev=False, help="dump DATABASE_URL")
    backup_parser.add_argument("--output-dir", required=True)
    backup_parser.add_argument("--label", required=True)
    restore_parser = commands.add_parser(
        "restore", allow_abbrev=False, help="restore into the new empty SGAA_RESTORE_TARGET_URL"
    )
    restore_parser.add_argument("--manifest", required=True)
    verify_parser = commands.add_parser("verify", allow_abbrev=False, help="verify an artifact set")
    verify_parser.add_argument("--manifest", required=True)
    verify_parser.add_argument(
        "--restored", action="store_true", help="also compare SGAA_RESTORE_TARGET_URL (read-only)"
    )
    return parser


def _report_error(exc: BackupToolError) -> None:
    for category, name in exc.mismatches[:50]:
        print(f"pg-backup: mismatch category={category} object={name}", file=sys.stderr)
    print(f"pg-backup: {exc.verdict}: {exc}", file=sys.stderr)


def main(argv=None) -> int:
    try:
        options = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_USAGE
    announce = lambda line: print(f"pg-backup: {line}")  # noqa: E731
    try:
        if options.command == "backup":
            result = backup(options.output_dir, options.label, announce=announce)
            manifest = result.manifest
            for path in result.paths.finals():
                announce(f"wrote: {path}")
            announce(f"artifact: size={manifest['artifact']['size']} sha256={manifest['artifact']['sha256']}")
            announce(f"toc: {manifest['toc']['entries']} entries, SGAA contract only")
            announce(f"identities: {len(manifest['identities'])} recorded; tables: {len(manifest['tables'])}")
            announce("result: BACKUP_OK")
        elif options.command == "verify":
            loaded = verify_artifact(options.manifest, announce=announce)
            if options.restored:
                url = require_url(None, TARGET_URL_ENV)
                verify_database(loaded.manifest, url, announce=announce)
                announce("result: VERIFY_OK (artifact + database)")
            else:
                announce("result: VERIFY_OK (artifact)")
        else:
            restore(options.manifest, announce=announce)
            announce("result: RESTORE_OK")
        return EXIT_OK
    except BackupToolError as exc:
        _report_error(exc)
        return exc.exit_code
    except KeyboardInterrupt:
        print("pg-backup: interrupted; nothing was promoted", file=sys.stderr)
        return EXIT_FAILED
    except Exception as exc:  # psycopg / OS failures: class and SQLSTATE only
        state = getattr(exc, "sqlstate", None)
        print(f"pg-backup: error: {exc.__class__.__name__}" + (f" sqlstate={state}" if state else ""),
              file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
