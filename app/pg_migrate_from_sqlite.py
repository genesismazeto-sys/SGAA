# coding: utf-8
"""Path-B cutover: copy a frozen SQLite prod-1 (v15) database into PostgreSQL.

WHY THIS EXISTS
    Path B keeps the business records of the running SQLite installation when
    production moves to PostgreSQL.  ``python -m app.pg_schema provision``
    creates the empty prod-1 (v15) PostgreSQL baseline; this module is the one
    supported, offline way to fill it from a FROZEN COPY of the SQLite file.
    Nothing in the application runtime imports or runs it.

WHAT IT COPIES -- AND WHAT IT REFUSES TO COPY
    Every SQLite table has exactly one policy in ``SOURCE_TABLE_POLICIES``.
    Business identity, catalog, operational history and business
    configuration are copied exactly, with their source ids.  Machine state is
    not: schema metadata is owned by the provisioner, password links are
    single-use and must not be revived, backup settings hold machine paths and
    token slots, and cloud accounts hold OAuth tokens encrypted under a
    machine-local key.  Those tables stay empty on the target and are reported
    by table, row count and reason -- never by value.  ``sqlite_sequence`` is
    not copied either; it is the identity high-water evidence.

    v15 canonical document custody: a canonical request row
    (``provider = 'supabase'``, its ``storage_object_id``, status and custody
    metadata) is copied exactly like every other business row; it needs no
    Google credential, connection or Drive account (only a Google-custody row
    or a Drive-bound mirror raises GOOGLE_DRIVE_RECONNECT_REQUIRED).

    v14 canonical storage: ``storage_objects`` and the business rows'
    ``storage_object_id`` are copied exactly (metadata only -- object bytes
    live in the canonical bucket and are never moved by Path B).  Upload
    intents are ephemeral and never copied: the cutover requires a source with
    NO live (issued / verified) intent, so no in-flight upload is silently
    invalidated.  Worker health is recreated target-side (empty = never ran).
    A mirror lease (in-flight worker state) is refused.  The mirror's Drive
    account travels as ``storage_objects.drive_account_key`` -- the LOGICAL
    account key, not a credential row -- so it survives the target-side
    recreation of ``cloud_accounts``; no active credential is needed for the
    cutover, and reconnecting the same Google account reproduces the key.

SAFETY MODEL
    * Source: required path and expected SHA-256 (checked before opening and
      again before commit); a non-empty ``-wal`` sidecar is refused, because the
      immutable read-only open would silently ignore it; the configured runtime
      SQLite database is refused -- migrate a copy.  The file is opened
      ``mode=ro&immutable=1`` and only read: user_version, integrity_check,
      foreign_key_check, then SELECTs.
    * Target: ``DATABASE_URL`` only (never a CLI argument), PostgreSQL >= 15,
      the full ``validate_pg_schema`` census, ``schema_migrations`` equal to the
      provisioner seed, and every application table empty -- re-checked under
      ``ACCESS EXCLUSIVE`` locks inside the write transaction.  There is no
      ``--force``.  Without ``--apply`` nothing is written.
    * One PostgreSQL transaction: load in FK order, restore self-references in
      a second pass (the real lineage trigger validates them), advance identity
      sequences with the transactional ``ALTER TABLE ... RESTART``, compare
      every copied row against the source, run the domain checks, then commit.
      Any failure before COMMIT rolls the whole database migration back.  No
      trigger or constraint is disabled.
    * Local files referenced by copied rows are preflighted before the
      transaction.  Each is streamed into ``<final>.sgaa-pathb-staging`` next
      to its final name (exclusive create), fsynced, verified by size and
      SHA-256, and only then promoted to the final name without replacing
      anything (an existing different file is never overwritten).  A failure
      before COMMIT removes the files this run created.
    * Once COMMIT has been sent its result is unknown if it raises or is
      interrupted: the run ends COMMIT_OUTCOME_UNCERTAIN (exit 3), claims no
      rollback and keeps the copied files.  Rerun: a migrated target is refused
      as non-empty; an empty one reuses the identical copied files.
    * A source that no longer matches after COMMIT ends
      COMMITTED_SOURCE_UNVERIFIED (exit 4): the target is committed, nothing
      is rolled back, and the copy must be investigated before go-live.

RECOVERY AFTER A HARD KILL
    A kill can leave only a ``.sgaa-pathb-staging`` file, never a partial file
    under a final name.  The preflight refuses it (ASSET_STAGING_LEFTOVER) and
    names the row; it is never business data and the operator removes it.
    A final file that is already identical to the source is reused.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app import pg_schema

# ---------------------------------------------------------------------------
# policy manifest
# ---------------------------------------------------------------------------

MIGRATE_EXACT = "MIGRATE_EXACT"
MIGRATE_TRANSFORM = "MIGRATE_TRANSFORM"
RECREATE_TARGET_SIDE = "RECREATE_TARGET_SIDE"
OMIT_EPHEMERAL = "OMIT_EPHEMERAL"
TARGET_ONLY_EXPECT_EMPTY = "TARGET_ONLY_EXPECT_EMPTY"
TARGET_SIDE_INITIALIZATION = "TARGET_SIDE_INITIALIZATION"

OMITTED_EPHEMERAL = "OMITTED_EPHEMERAL"
OMITTED_TARGET_SCHEMA_METADATA = "OMITTED_TARGET_SCHEMA_METADATA"
OMITTED_SQLITE_INTERNAL = "OMITTED_SQLITE_INTERNAL"
RESET_ENVIRONMENT_CONFIGURATION = "RESET_ENVIRONMENT_CONFIGURATION"
SCRUBBED_SECRET = "SCRUBBED_SECRET"
REQUIRES_EXTERNAL_RECONNECT = "REQUIRES_EXTERNAL_RECONNECT"
RESET_OPERATIONAL_STATE = "RESET_OPERATIONAL_STATE"

GOOGLE_DRIVE_RECONNECT_REQUIRED = "GOOGLE_DRIVE_RECONNECT_REQUIRED"
ONEDRIVE_RECONNECT_REQUIRED = "ONEDRIVE_RECONNECT_REQUIRED"
BACKUP_CONFIGURATION_REQUIRED = "BACKUP_CONFIGURATION_REQUIRED"
LOCAL_ASSETS_REQUIRED_IN_UPLOAD_ROOT = "LOCAL_ASSETS_REQUIRED_IN_UPLOAD_ROOT"
CANONICAL_STORAGE_BUCKET_REQUIRED = "CANONICAL_STORAGE_BUCKET_REQUIRED"

SQLITE_SEQUENCE_TABLE = "sqlite_sequence"


@dataclass(frozen=True)
class TablePolicy:
    policy: str
    reasons: tuple[str, ...] = ()


_EXACT = TablePolicy(MIGRATE_EXACT)

SOURCE_TABLE_POLICIES = {
    # The provisioner seeds rows 1..14; the source rows must equal that seed.
    "schema_migrations": TablePolicy(RECREATE_TARGET_SIDE, (OMITTED_TARGET_SCHEMA_METADATA,)),
    "usuarios": _EXACT,
    # Admin-chosen profile defaults; without them the product falls back to
    # the historical hard-coded values it says never to use in production.
    "configuracoes_acesso": _EXACT,
    "usuarios_permissoes_acesso": _EXACT,
    "configuracoes_app": _EXACT,
    "usuario_credenciais": _EXACT,
    # Single-use first-access/reset links: the cutover never revives them.
    "senha_tokens": TablePolicy(OMIT_EPHEMERAL, (OMITTED_EPHEMERAL,)),
    # Machine paths, backup token slots and last-run state of the SQLite backup.
    "configuracoes_backup": TablePolicy(
        RECREATE_TARGET_SIDE, (RESET_ENVIRONMENT_CONFIGURATION, SCRUBBED_SECRET)
    ),
    "configuracoes_presets": _EXACT,
    # OAuth tokens encrypted under a machine-local key; nothing references the
    # rows.  Production reconnects through the OAuth flow.
    "cloud_accounts": TablePolicy(
        RECREATE_TARGET_SIDE, (SCRUBBED_SECRET, REQUIRES_EXTERNAL_RECONNECT)
    ),
    "backup_logs": TablePolicy(OMIT_EPHEMERAL, (OMITTED_EPHEMERAL,)),
    # Backup destination folder only; comprovante storage does not read it.
    "cloud_drive_settings": TablePolicy(
        RECREATE_TARGET_SIDE, (RESET_ENVIRONMENT_CONFIGURATION,)
    ),
    "mensagens_editaveis": _EXACT,
    "cursos": _EXACT,
    "matrizes_atividades": _EXACT,
    "turmas": _EXACT,
    "alunos": _EXACT,
    "grupos_def": _EXACT,
    "atividade_base": _EXACT,
    "atividade_versao": _EXACT,
    "atividade_transicao": _EXACT,
    "matriz_atividade_versao_item": _EXACT,
    "requisicoes": _EXACT,
    "requisicao_arquivos": _EXACT,
    "requisicao_alerta_receipts": _EXACT,
    "reportes": _EXACT,
    "admin_arquivos": _EXACT,
    "admin_alertas": _EXACT,
    "email_envios": _EXACT,
    "requisicao_email_eventos": _EXACT,
    # v13 database-backed images: verified bytes travel with their row, so no
    # local file is needed on the target.
    "usuarios_foto": _EXACT,
    "alunos_foto": _EXACT,
    "reportes_captura": _EXACT,
    # v14 canonical custody: object metadata travels exactly; the bytes stay in
    # the canonical bucket (see CANONICAL_STORAGE_BUCKET_REQUIRED).
    "storage_objects": _EXACT,
    # Server-issued upload authorizations: the source must hold no live one
    # (LIVE_UPLOAD_INTENTS); terminal history is not business data.
    "storage_upload_intents": TablePolicy(OMIT_EPHEMERAL, (OMITTED_EPHEMERAL,)),
    # Mirror-worker health of the source machine; empty target = never ran.
    "storage_worker_status": TablePolicy(RECREATE_TARGET_SIDE, (RESET_OPERATIONAL_STATE,)),
    # v16 short-lived cross-request state (throttle windows, pending previews):
    # meaningless after a cutover, so the target starts with both empty.
    "auth_throttle_events": TablePolicy(OMIT_EPHEMERAL, (OMITTED_EPHEMERAL,)),
    "admin_import_previews": TablePolicy(OMIT_EPHEMERAL, (OMITTED_EPHEMERAL,)),
    SQLITE_SEQUENCE_TABLE: TablePolicy(OMIT_EPHEMERAL, (OMITTED_SQLITE_INTERNAL,)),
}

#: PostgreSQL tables with no SQLite counterpart.
TARGET_ONLY_TABLE_POLICIES = {
    pg_schema.PG_SCHEMA_META_TABLE: TARGET_SIDE_INITIALIZATION,
}

#: Columns that reference local files under an upload root.  Only the
#: ``admin_arquivos`` legacy files have a supported copy contract; any other
#: populated reference is refused rather than silently left dangling.  A
#: CONVERGED legacy row (``storage_object_id`` set) is canonical custody: its
#: bytes are in canonical storage, so its local file is neither required nor
#: copied.  The
#: legacy image path columns stay here: the source must have been normalized
#: by ``python -m app.image_import`` (images moved into the v13 tables, paths
#: NULL) before the cutover.
_UNSUPPORTED_LOCAL_REFERENCES = (
    ("requisicao_arquivos",
     "SELECT count(*) FROM requisicao_arquivos WHERE provider = 'local_legacy' AND storage_object_id IS NULL"),
    ("usuarios", "SELECT count(*) FROM usuarios WHERE COALESCE(foto_perfil, '') <> ''"),
    ("alunos", "SELECT count(*) FROM alunos WHERE COALESCE(foto_perfil, '') <> ''"),
    ("reportes", "SELECT count(*) FROM reportes WHERE COALESCE(screenshot_filename, '') <> ''"),
)

#: v14 cutover freeze: ``(refusal code, SQLite count, value-free detail)``.
#: Live upload intents would be invalidated by the cutover (intents are never
#: copied); a lease is in-flight worker state.  The logical Drive account key
#: needs no credential row, so an account-bound mirror is NOT refused.
CUTOVER_STORAGE_PRECONDITIONS = (
    (
        "LIVE_UPLOAD_INTENTS",
        "SELECT count(*) FROM storage_upload_intents WHERE state IN ('issued','verified')",
        "live upload intent(s); drain or expire them before the freeze",
    ),
    (
        "STORAGE_MIRROR_LEASE_ACTIVE",
        "SELECT count(*) FROM storage_objects WHERE drive_sync_state = 'syncing' "
        "OR lease_token IS NOT NULL",
        "storage object(s) leased by a mirror worker; stop the worker and let leases end",
    ),
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SQLITE_CLASSES = {
    "text": {"text"},
    "integer": {"integer"},
    "double precision": {"real", "integer"},
    "bytea": {"blob"},
}
CONNECT_TIMEOUT_SECONDS = 15
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def policy_manifest_problems() -> list[str]:
    """Empty when every source and target table has exactly one policy."""
    problems = []
    source = set(SOURCE_TABLE_POLICIES) - {SQLITE_SEQUENCE_TABLE}
    target = set(pg_schema.PG_APPLICATION_TABLES)
    problems += [f"source table without target: {name}" for name in sorted(source - target)]
    problems += [f"target table without policy: {name}" for name in sorted(target - source)]
    for name in set(TARGET_ONLY_TABLE_POLICIES) - set(pg_schema.PG_SCHEMA_TABLES):
        problems.append(f"target-only policy for unknown table: {name}")
    for name in set(pg_schema.PG_SCHEMA_TABLES) - target - set(TARGET_ONLY_TABLE_POLICIES):
        problems.append(f"target-only table without policy: {name}")
    known = {MIGRATE_EXACT, MIGRATE_TRANSFORM, RECREATE_TARGET_SIDE, OMIT_EPHEMERAL}
    for name, policy in SOURCE_TABLE_POLICIES.items():
        if policy.policy not in known:
            problems.append(f"unknown policy for {name}: {policy.policy}")
        if policy.policy != MIGRATE_EXACT and not policy.reasons:
            problems.append(f"excluded table without reason: {name}")
    return problems


def migrated_tables() -> tuple[str, ...]:
    return tuple(
        name for name in load_order() if SOURCE_TABLE_POLICIES[name].policy == MIGRATE_EXACT
    )


def load_order() -> tuple[str, ...]:
    """Every application table, parents before children (self-edges ignored).

    Derived from the PostgreSQL contract's foreign keys; ties keep the
    contract's table order, so the result is deterministic.
    """
    tables = list(pg_schema.PG_APPLICATION_TABLES)
    parents = {
        table: {
            fk["references_table"]
            for fk in pg_schema.PG_TABLE_SPECS[table]["foreign_keys"]
            if fk["references_table"] != table
        }
        for table in tables
    }
    ordered = []
    while len(ordered) < len(tables):
        ready = [t for t in tables if t not in ordered and parents[t] <= set(ordered)]
        if not ready:
            raise MigrationRefused("SCHEMA_CYCLE", "foreign-key cycle in the target contract")
        ordered.append(ready[0])
    return tuple(ordered)


def self_reference_columns(table) -> tuple[str, ...]:
    columns = []
    for fk in pg_schema.PG_TABLE_SPECS[table]["foreign_keys"]:
        if fk["references_table"] == table:
            if len(fk["columns"]) != 1:
                raise MigrationRefused("SCHEMA_UNSUPPORTED", f"composite self-reference on {table}")
            columns.append(fk["columns"][0])
    return tuple(columns)


def _columns(table):
    return [column["name"] for column in pg_schema.PG_TABLE_SPECS[table]["columns"]]


def _column_types(table):
    return {column["name"]: column["type"] for column in pg_schema.PG_TABLE_SPECS[table]["columns"]}


def _primary_key(table):
    return list(pg_schema.PG_TABLE_SPECS[table]["primary_key"]["columns"])


def _identity_column(table):
    for column in pg_schema.PG_TABLE_SPECS[table]["columns"]:
        if column["identity"]:
            return column["name"]
    return None


# ---------------------------------------------------------------------------
# errors and results
# ---------------------------------------------------------------------------


class MigrationRefused(Exception):
    """A precondition failed; nothing was written."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


class MigrationFailed(Exception):
    """The migration started and was rolled back; the target is unchanged."""

    def __init__(self, code: str, detail: str = "", mismatches=()) -> None:
        self.code = code
        self.mismatches = list(mismatches)
        super().__init__(f"{code}: {detail}" if detail else code)


class MigrationCommitUncertain(Exception):
    """COMMIT was sent and did not confirm: the target may or may not be migrated.

    Nothing is rolled back and copied files are kept, so either outcome stays
    recoverable by a rerun (non-empty target refused, empty target retried).
    """

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class Mismatch:
    """A value-free description of one validation difference."""

    table: str
    primary_key: tuple
    column: str
    category: str


@dataclass
class LocalAsset:
    table: str
    row_id: int
    relative_path: str
    size: int
    sha256: str
    required: bool
    status: str = "planned"


@dataclass
class SourceSnapshot:
    path: Path
    size: int
    sha256: str
    mtime_ns: int
    user_version: int
    rows: dict = field(default_factory=dict)
    sequences: dict = field(default_factory=dict)
    live_password_tokens: int = 0


@dataclass
class TargetIdentity:
    host: str
    port: str
    database: str
    user: str

    def label(self) -> str:
        return (
            f"backend=postgresql host={self.host} port={self.port} "
            f"database={self.database} user={self.user}"
        )


@dataclass
class MigrationReport:
    applied: bool = False
    source_sha256: str = ""
    source_size: int = 0
    source_user_version: int = 0
    source_hash_verified_after: bool = False
    target: TargetIdentity | None = None
    server_version_num: int = 0
    load_order: tuple = ()
    copied: dict = field(default_factory=dict)  # table -> rows
    excluded: dict = field(default_factory=dict)  # table -> (rows, policy, reasons)
    digests: dict = field(default_factory=dict)  # table -> sha256
    sequences: dict = field(default_factory=dict)  # table -> (high_water, next_value)
    self_references_restored: dict = field(default_factory=dict)
    domain_checks: dict = field(default_factory=dict)
    assets: list = field(default_factory=list)
    prerequisites: list = field(default_factory=list)
    live_password_tokens_dropped: int = 0

    @property
    def committed_source_unverified(self) -> bool:
        """The target committed, but the source changed after the last check."""
        return self.applied and not self.source_hash_verified_after


# ---------------------------------------------------------------------------
# normalization and digests
# ---------------------------------------------------------------------------


def normalize_value(value, pg_type):
    """One backend-neutral representation per contract type.

    Binary content (SQLite BLOB / PostgreSQL bytea) is represented by
    ``("bytea", length, sha256)``: comparisons and table digests cover every
    byte, while a mismatch report or digest input never carries the bytes.
    """
    if value is None:
        return None
    if pg_type == "bytea":
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("bytea")
        content = bytes(value)
        return ("bytea", len(content), hashlib.sha256(content).hexdigest())
    if pg_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("integer")
        return int(value)
    if pg_type == "double precision":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("double precision")
        return float(value)
    if pg_type == "text":
        if not isinstance(value, str):
            raise TypeError("text")
        return value
    raise TypeError(pg_type)


def normalize_rows(table, rows):
    """``{primary key: normalized row}`` for rows in contract column order."""
    columns = _columns(table)
    types = _column_types(table)
    key_positions = [columns.index(name) for name in _primary_key(table)]
    normalized = {}
    for row in rows:
        values = tuple(normalize_value(value, types[name]) for name, value in zip(columns, row))
        normalized[tuple(values[i] for i in key_positions)] = values
    return normalized


def table_digest(table, normalized) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps([table, _columns(table)], separators=(",", ":")).encode("utf-8"))
    for key in sorted(normalized):
        digest.update(b"\n")
        digest.update(
            json.dumps(list(normalized[key]), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    return digest.hexdigest()


def compare_rows(table, source, target) -> list[Mismatch]:
    columns = _columns(table)
    mismatches = []
    for key in sorted(set(source) - set(target)):
        mismatches.append(Mismatch(table, key, "*", "MISSING_IN_TARGET"))
    for key in sorted(set(target) - set(source)):
        mismatches.append(Mismatch(table, key, "*", "UNEXPECTED_IN_TARGET"))
    for key in sorted(set(source) & set(target)):
        for name, left, right in zip(columns, source[key], target[key]):
            if left == right:
                continue
            if (left is None) != (right is None):
                category = "NULL_DIFFERS"
            elif type(left) is not type(right):
                category = "TYPE_DIFFERS"
            else:
                category = "VALUE_DIFFERS"
            mismatches.append(Mismatch(table, key, name, category))
    return mismatches


# ---------------------------------------------------------------------------
# source
# ---------------------------------------------------------------------------


def file_sha256(path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _runtime_sqlite_paths():
    configured = (os.environ.get("APP_DATABASE") or "").strip()
    paths = [PROJECT_ROOT / "database.db"]
    if configured:
        paths.append(Path(configured))
    return paths


def _same_file(left, right) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def open_source_readonly(path) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def _check_source_file(path, expected_sha256):
    path = Path(path)
    if not path.is_file():
        raise MigrationRefused("SOURCE_MISSING", "the source path is not a file")
    for runtime in _runtime_sqlite_paths():
        if _same_file(path, runtime):
            raise MigrationRefused(
                "SOURCE_IS_RUNTIME_DATABASE",
                "migrate a frozen copy, never the configured application database",
            )
    wal = Path(str(path) + "-wal")
    if wal.exists() and wal.stat().st_size > 0:
        raise MigrationRefused(
            "SOURCE_NOT_FROZEN", "the source has a non-empty -wal file; checkpoint before copying"
        )
    expected = str(expected_sha256 or "").strip().lower()
    if not _SHA256_RE.match(expected):
        raise MigrationRefused("SOURCE_HASH_REQUIRED", "a 64-hex expected SHA-256 is required")
    stat = path.stat()
    size, actual = file_sha256(path)
    if actual != expected:
        raise MigrationRefused("SOURCE_HASH_MISMATCH", "the source file does not match the expected SHA-256")
    return size, actual, stat.st_mtime_ns


def read_source(path, expected_sha256) -> SourceSnapshot:
    """Verify and read the whole frozen source through SELECT/read-only pragmas."""
    size, actual, mtime_ns = _check_source_file(path, expected_sha256)
    conn = open_source_readonly(path)
    try:
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if user_version != pg_schema.PG_SCHEMA_VERSION:
            raise MigrationRefused(
                "SOURCE_SCHEMA_UNSUPPORTED",
                f"user_version {user_version}, expected {pg_schema.PG_SCHEMA_VERSION}",
            )
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
        if integrity != ["ok"]:
            raise MigrationRefused("SOURCE_INTEGRITY_FAILED", "integrity_check is not ok")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise MigrationRefused("SOURCE_INTEGRITY_FAILED", "foreign_key_check reports violations")

        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        unknown = sorted(tables - set(SOURCE_TABLE_POLICIES))
        missing = sorted(set(SOURCE_TABLE_POLICIES) - tables - {SQLITE_SEQUENCE_TABLE})
        if unknown or missing:
            raise MigrationRefused(
                "SOURCE_SCHEMA_UNSUPPORTED", f"unknown tables {unknown}, missing tables {missing}"
            )
        for table in pg_schema.PG_APPLICATION_TABLES:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
            if columns != _columns(table):
                raise MigrationRefused(
                    "SOURCE_SCHEMA_UNSUPPORTED", f"{table} columns differ from the target contract"
                )

        markers = [
            (int(row[0]), str(row[1]), str(row[2]))
            for row in conn.execute(
                "SELECT version, name, schema_epoch FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        seed = [
            (version, name, pg_schema.PG_SCHEMA_EPOCH)
            for version, name, _details in pg_schema.PG_SCHEMA_MIGRATIONS_SEED
        ]
        if markers != seed:
            raise MigrationRefused(
                "SOURCE_SCHEMA_UNSUPPORTED", "schema_migrations does not match the prod-1 baseline"
            )

        for table in pg_schema.PG_APPLICATION_TABLES:
            if SOURCE_TABLE_POLICIES[table].policy != MIGRATE_EXACT:
                continue
            for name, pg_type in _column_types(table).items():
                classes = {
                    row[0]
                    for row in conn.execute(f'SELECT DISTINCT typeof("{name}") FROM "{table}"').fetchall()
                } - {"null"}
                if classes - _SQLITE_CLASSES[pg_type]:
                    raise MigrationRefused(
                        "SOURCE_DATA_INCOMPATIBLE",
                        f"{table}.{name} holds {sorted(classes)} for {pg_type}",
                    )

        for table, sql in _UNSUPPORTED_LOCAL_REFERENCES:
            if int(conn.execute(sql).fetchone()[0]):
                raise MigrationRefused(
                    "UNSUPPORTED_LOCAL_ASSET", f"{table} references local files without a copy contract"
                )
        for code, sql, detail in CUTOVER_STORAGE_PRECONDITIONS:
            count = int(conn.execute(sql).fetchone()[0])
            if count:
                raise MigrationRefused(code, f"{count} {detail}")

        snapshot = SourceSnapshot(Path(path), size, actual, mtime_ns, user_version)
        for table in pg_schema.PG_APPLICATION_TABLES:
            column_list = ", ".join(f'"{name}"' for name in _columns(table))
            snapshot.rows[table] = conn.execute(f'SELECT {column_list} FROM "{table}"').fetchall()
        if SQLITE_SEQUENCE_TABLE in tables:
            snapshot.sequences = {
                str(name): int(seq)
                for name, seq in conn.execute("SELECT name, seq FROM sqlite_sequence").fetchall()
            }
        snapshot.live_password_tokens = int(
            conn.execute(
                "SELECT count(*) FROM senha_tokens WHERE consumed_at IS NULL "
                "AND invalidated_at IS NULL AND expires_at > strftime('%Y-%m-%d %H:%M:%S','now')"
            ).fetchone()[0]
        )
        return snapshot
    finally:
        conn.close()


def _source_unchanged(snapshot) -> bool:
    try:
        stat = snapshot.path.stat()
        size, actual = file_sha256(snapshot.path)
    except OSError:
        return False
    return size == snapshot.size and actual == snapshot.sha256 and stat.st_mtime_ns == snapshot.mtime_ns


# ---------------------------------------------------------------------------
# local assets
# ---------------------------------------------------------------------------


def _resolve_under(root, relative):
    from app.student_documents import resolve_student_document_path

    try:
        return Path(resolve_student_document_path(str(root), str(relative)))
    except ValueError as exc:
        raise MigrationRefused("ASSET_PATH_INVALID", "a local file path escapes its root") from exc


def plan_local_assets(snapshot, source_root, target_root) -> list[LocalAsset]:
    columns = _columns("admin_arquivos")
    position = {name: columns.index(name) for name in ("id", "filename", "provider", "storage_status",
                                                         "storage_object_id")}
    rows = [
        row for row in snapshot.rows["admin_arquivos"]
        if row[position["provider"]] == "local_legacy" and row[position["storage_object_id"]] is None
    ]
    if not rows:
        return []
    if not source_root or not target_root:
        raise MigrationRefused(
            "ASSET_ROOTS_REQUIRED",
            "local files are referenced; pass --source-upload-root and --target-upload-root",
        )
    plan = []
    for row in sorted(rows, key=lambda r: r[position["id"]]):
        relative = str(row[position["filename"]])
        required = row[position["storage_status"]] == "legacy_active"
        source_path = _resolve_under(source_root, relative)
        if not source_path.is_file():
            if required:
                raise MigrationRefused("ASSET_MISSING", f"admin_arquivos id={row[position['id']]}")
            continue
        size, digest = file_sha256(source_path)
        asset = LocalAsset("admin_arquivos", int(row[position["id"]]), relative, size, digest, required)
        destination = _resolve_under(target_root, relative)
        if os.path.lexists(staging_path(destination)):
            raise MigrationRefused(
                "ASSET_STAGING_LEFTOVER",
                f"admin_arquivos id={asset.row_id}: an interrupted run left its "
                f"{STAGING_SUFFIX} file next to the destination; it is never a business "
                "file -- remove it and rerun",
            )
        if destination.exists():
            if not destination.is_file() or file_sha256(destination) != (size, digest):
                raise MigrationRefused(
                    "ASSET_DESTINATION_CONFLICT",
                    f"admin_arquivos id={asset.row_id}: a different file already exists",
                )
            asset.status = "present_identical"
        plan.append(asset)
    return plan


#: Suffix of the one staging name per destination; a final name never holds
#: partial bytes, and a leftover staging file is recognisable and refused.
STAGING_SUFFIX = ".sgaa-pathb-staging"


def staging_path(destination) -> Path:
    destination = Path(destination)
    return destination.with_name(destination.name + STAGING_SUFFIX)


def _promote_without_replacing(staging, destination):
    """Give ``staging`` the final name; ``FileExistsError`` if it is taken.

    Windows ``os.rename`` never replaces an existing file.  POSIX ``rename``
    would, so there the final name is created by ``link`` (which refuses an
    existing name) and the staging name is dropped afterwards.
    """
    if os.name == "nt":
        os.rename(staging, destination)
        return
    os.link(staging, destination)
    os.unlink(staging)
    directory = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class _AssetWriter:
    """Writes planned assets; ``undo`` removes only what this run created."""

    def __init__(self, source_root, target_root):
        self.source_root = source_root
        self.target_root = target_root
        self.created_files = []
        self.created_dirs = []

    def _makedirs(self, directory):
        missing = []
        while not directory.exists():
            missing.append(directory)
            directory = directory.parent
        for path in reversed(missing):
            path.mkdir()
            self.created_dirs.append(path)

    def write(self, asset):
        """Stage, verify, then promote; the final name only ever gets verified bytes."""
        if asset.status == "present_identical":
            return
        source = _resolve_under(self.source_root, asset.relative_path)
        destination = _resolve_under(self.target_root, asset.relative_path)
        staging = staging_path(destination)
        self._makedirs(destination.parent)
        try:
            handle = open(staging, "xb")
        except FileExistsError as exc:
            # Not ours: appeared after the preflight; refuse and leave it.
            raise MigrationFailed("ASSET_STAGING_LEFTOVER", f"admin_arquivos id={asset.row_id}") from exc
        try:
            digest = hashlib.sha256()
            size = 0
            with handle, open(source, "rb") as reader:
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    size += len(chunk)
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if (size, digest.hexdigest()) != (asset.size, asset.sha256):
                raise MigrationFailed("ASSET_SOURCE_CHANGED", f"admin_arquivos id={asset.row_id}")
            if file_sha256(staging) != (asset.size, asset.sha256):
                raise MigrationFailed("ASSET_VERIFY_FAILED", f"admin_arquivos id={asset.row_id}")
            try:
                _promote_without_replacing(staging, destination)
            except FileExistsError as exc:
                raise MigrationFailed(
                    "ASSET_DESTINATION_CONFLICT", f"admin_arquivos id={asset.row_id}"
                ) from exc
        except BaseException:
            try:
                staging.unlink()
            except FileNotFoundError:
                pass
            raise
        self.created_files.append(destination)
        asset.status = "copied"

    def undo(self):
        for path in reversed(self.created_files):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        for path in reversed(self.created_dirs):
            try:
                path.rmdir()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# target
# ---------------------------------------------------------------------------


def require_target_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise MigrationRefused("TARGET_REQUIRED", "DATABASE_URL must name the PostgreSQL target")
    if not url.startswith(("postgres://", "postgresql://")):
        raise MigrationRefused("TARGET_NOT_POSTGRESQL", "DATABASE_URL is not a PostgreSQL URL")
    return url


def connect_target(url):
    import psycopg

    return psycopg.connect(
        url, prepare_threshold=None, autocommit=False, connect_timeout=CONNECT_TIMEOUT_SECONDS
    )


def target_identity(conn) -> TargetIdentity:
    info = conn.info
    return TargetIdentity(str(info.host), str(info.port), str(info.dbname), str(info.user))


def _application_row_counts(conn) -> dict:
    return {
        table: int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        for table in pg_schema.PG_APPLICATION_TABLES
    }


def check_target(conn) -> int:
    """Read-only target precondition; returns ``server_version_num``."""
    version = int(conn.execute("SHOW server_version_num").fetchone()[0])
    if version < 150000:
        raise MigrationRefused("TARGET_VERSION_UNSUPPORTED", f"server_version_num {version} < 150000")
    try:
        pg_schema.validate_pg_schema(conn)
    except pg_schema.PostgresSchemaError as exc:
        raise MigrationRefused("TARGET_SCHEMA_NOT_CURRENT", str(exc)) from exc
    markers = [
        (int(row[0]), str(row[1]), str(row[2]), str(row[3]))
        for row in conn.execute(
            "SELECT version, name, schema_epoch, details_json FROM schema_migrations ORDER BY version"
        ).fetchall()
    ]
    seed = [
        (version, name, pg_schema.PG_SCHEMA_EPOCH, details)
        for version, name, details in pg_schema.PG_SCHEMA_MIGRATIONS_SEED
    ]
    if markers != seed:
        raise MigrationRefused("TARGET_SCHEMA_NOT_CURRENT", "schema_migrations is not the provisioner seed")
    _require_empty_target(conn)
    return version


def _require_empty_target(conn):
    occupied = sorted(
        table
        for table, count in _application_row_counts(conn).items()
        if count and table != "schema_migrations"
    )
    if occupied:
        raise MigrationRefused(
            "TARGET_NOT_EMPTY", f"application tables already hold rows: {', '.join(occupied)}"
        )


def _lock_target(conn):
    tables = ", ".join(pg_schema.PG_SCHEMA_TABLES)
    conn.execute(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE")


def _to_parameter(value, pg_type):
    if value is not None and pg_type == "double precision":
        return float(value)
    if value is not None and pg_type == "bytea":
        return bytes(value)
    return value


def _load_table(conn, table, rows, report):
    columns = _columns(table)
    types = [_column_types(table)[name] for name in columns]
    deferred = self_reference_columns(table)
    deferred_positions = [columns.index(name) for name in deferred]
    not_null = {c["name"] for c in pg_schema.PG_TABLE_SPECS[table]["columns"] if c["not_null"]}
    if set(deferred) & not_null:
        raise MigrationRefused("SCHEMA_UNSUPPORTED", f"{table} self-reference is NOT NULL")
    parameters = []
    for row in rows:
        values = [_to_parameter(value, pg_type) for value, pg_type in zip(row, types)]
        for position in deferred_positions:
            values[position] = None
        parameters.append(values)
    if parameters:
        placeholders = ", ".join(["%s"] * len(columns))
        with conn.cursor() as cursor:
            cursor.executemany(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", parameters
            )
    if deferred:
        key = _primary_key(table)
        if len(key) != 1:
            raise MigrationRefused("SCHEMA_UNSUPPORTED", f"{table} self-reference needs a single-column key")
        key_position = columns.index(key[0])
        for name, position in zip(deferred, deferred_positions):
            updates = sorted(
                (row[key_position], row[position]) for row in rows if row[position] is not None
            )
            with conn.cursor() as cursor:
                # Second pass: the real lineage trigger fires on every UPDATE.
                cursor.executemany(
                    f"UPDATE {table} SET {name} = %s WHERE {key[0]} = %s",
                    [(reference, row_id) for row_id, reference in updates],
                )
            report.self_references_restored[f"{table}.{name}"] = len(updates)


def _sequence_name(conn, table, column):
    return conn.execute("SELECT pg_get_serial_sequence(%s, %s)", (table, column)).fetchone()[0]


def _advance_identities(conn, snapshot, report):
    """Next generated id > max(sqlite_sequence high-water, max migrated id).

    ``ALTER TABLE ... RESTART`` is transactional, unlike ``setval``: a rolled
    back migration leaves the provisioned sequences untouched.
    """
    for table in pg_schema.PG_APPLICATION_TABLES:
        column = _identity_column(table)
        if column is None:
            continue
        high_water = snapshot.sequences.get(table, 0)
        if SOURCE_TABLE_POLICIES[table].policy == MIGRATE_EXACT and snapshot.rows[table]:
            position = _columns(table).index(column)
            high_water = max(high_water, max(int(row[position]) for row in snapshot.rows[table]))
        if high_water > 0:
            conn.execute(f"ALTER TABLE {table} ALTER COLUMN {column} RESTART WITH {high_water + 1}")
        report.sequences[table] = (high_water, high_water + 1)


def read_identity_state(conn, table) -> tuple[int, bool]:
    """``(last_value, is_called)`` of the identity sequence; consumes nothing."""
    sequence = _sequence_name(conn, table, _identity_column(table))
    row = conn.execute(f"SELECT last_value, is_called FROM {sequence}").fetchone()
    return int(row[0]), bool(row[1])


def next_identity_value(conn, table) -> int:
    last_value, is_called = read_identity_state(conn, table)
    return last_value + 1 if is_called else last_value


def read_target_rows(conn, table):
    columns = ", ".join(_columns(table))
    return conn.execute(f"SELECT {columns} FROM {table}").fetchall()


#: Domain invariants, each a count that must be zero on the target.
DOMAIN_CHECKS = {
    "activity_lineage_axis_breaks": (
        "SELECT count(*) FROM atividade_versao v JOIN atividade_versao p "
        "ON p.id = v.versao_anterior_id WHERE p.eixo <> v.eixo"
    ),
    "activity_lineage_cross_base": (
        "SELECT count(*) FROM atividade_versao v JOIN atividade_versao p "
        "ON p.id = v.versao_anterior_id WHERE p.atividade_base_id <> v.atividade_base_id"
    ),
    "matrix_items_without_version_of_base": (
        "SELECT count(*) FROM matriz_atividade_versao_item i LEFT JOIN atividade_versao v "
        "ON v.id = i.atividade_versao_id AND v.atividade_base_id = i.atividade_base_id "
        "WHERE v.id IS NULL"
    ),
    "requests_incomplete_turma_snapshot": (
        "SELECT count(*) FROM requisicoes WHERE (turma_id_snapshot IS NULL) <> "
        "(turma_codigo_snapshot IS NULL) OR TRIM(turma_codigo_snapshot) = ''"
    ),
    "requests_rule_snapshot_not_object": (
        "SELECT count(*) FROM requisicoes WHERE NOT sgaa_json_is_object(regra_snapshot_json)"
    ),
    "users_without_credential": (
        "SELECT count(*) FROM usuarios u LEFT JOIN usuario_credenciais c "
        "ON c.usuario_id = u.id WHERE c.usuario_id IS NULL"
    ),
    "transitions_aac_para_aeu_wrong_axis": (
        "SELECT count(*) FROM atividade_transicao t "
        "JOIN atividade_versao f ON f.id = t.from_atividade_versao_id "
        "JOIN atividade_versao o ON o.id = t.to_atividade_versao_id "
        "WHERE t.tipo_transicao = 'aac_para_aeu' AND (f.eixo <> 'AAC' OR o.eixo <> 'AEU')"
    ),
}

#: v13 image tables: ``(table, owner table, owner column, legacy path column,
#: allowed MIME types)``.  One row per owner is the primary key itself.
IMAGE_TABLES = (
    ("usuarios_foto", "usuarios", "usuario_id", "foto_perfil", ("image/jpeg", "image/png")),
    ("alunos_foto", "alunos", "aluno_id", "foto_perfil", ("image/jpeg", "image/png")),
    (
        "reportes_captura", "reportes", "reporte_id", "screenshot_filename",
        ("image/jpeg", "image/png", "image/webp"),
    ),
)


def _image_domain_checks():
    checks = {}
    for table, owner, owner_column, legacy_column, mime_types in IMAGE_TABLES:
        mime_list = ", ".join(f"'{mime}'" for mime in mime_types)
        checks[f"{table}_metadata_invalid"] = (
            f"SELECT count(*) FROM {table} WHERE mime_type NOT IN ({mime_list}) "
            "OR size_bytes <= 0 OR width <= 0 OR height <= 0 "
            "OR sha256 !~ '^[0-9a-f]{64}$'"
        )
        # Length and content digest against the recorded metadata; a value-free count.
        checks[f"{table}_content_mismatch"] = (
            f"SELECT count(*) FROM {table} WHERE octet_length(conteudo) <> size_bytes "
            "OR encode(sha256(conteudo), 'hex') <> sha256"
        )
        # A database image supersedes its owner's legacy file path: new writes
        # and the importer clear the path in the same transaction.
        checks[f"{table}_with_legacy_path"] = (
            f"SELECT count(*) FROM {table} i JOIN {owner} o ON o.id = i.{owner_column} "
            f"WHERE COALESCE(o.{legacy_column}, '') <> ''"
        )
    return checks


DOMAIN_CHECKS.update(_image_domain_checks())

#: v14 canonical-custody invariants (counts that must be zero).  They restate
#: the table CHECKs as an independent post-load / backup proof, plus the
#: cross-row rules no single-row CHECK can express.
STORAGE_DOMAIN_CHECKS = {
    "storage_objects_metadata_invalid": (
        "SELECT count(*) FROM storage_objects WHERE storage_backend <> 'supabase' "
        "OR sha256 !~ '^[0-9a-f]{64}$' OR size_bytes <= 0 OR size_bytes > 16777216 "
        "OR mime_type NOT IN ('application/pdf','image/png','image/jpeg') "
        "OR content_verified_at IS NULL OR btrim(storage_bucket) = '' OR btrim(storage_key) = ''"
    ),
    "storage_objects_lifecycle_invalid": (
        "SELECT count(*) FROM storage_objects WHERE NOT ("
        "(lifecycle_state = 'active' AND retired_at IS NULL AND purge_after IS NULL) "
        "OR (lifecycle_state = 'retired' AND retired_at IS NOT NULL))"
    ),
    "storage_objects_mirror_state_invalid": (
        "SELECT count(*) FROM storage_objects WHERE "
        "(drive_sync_state = 'synced' AND (drive_file_id IS NULL OR drive_account_key IS NULL "
        "OR drive_synced_at IS NULL)) "
        "OR (drive_sync_state IN ('retry','reconciliation_required') AND drive_last_error_code IS NULL) "
        "OR (drive_file_id IS NOT NULL AND drive_account_key IS NULL) "
        "OR drive_account_key !~ '^[0-9a-f]{64}$' "
        "OR drive_last_error_code !~ '^[A-Z0-9_]{1,64}$'"
    ),
    "storage_objects_lease_invalid": (
        "SELECT count(*) FROM storage_objects WHERE "
        "(drive_sync_state = 'syncing') <> (lease_token IS NOT NULL) "
        "OR (lease_token IS NULL) <> (lease_expires_at IS NULL)"
    ),
    "storage_objects_shared_by_business_rows": (
        "SELECT count(*) FROM requisicao_arquivos r JOIN admin_arquivos a "
        "ON a.storage_object_id = r.storage_object_id"
    ),
    "storage_upload_intents_state_invalid": (
        "SELECT count(*) FROM storage_upload_intents WHERE "
        "(state = 'consumed') <> (consumed_at IS NOT NULL AND storage_object_id IS NOT NULL) "
        "OR (state <> 'consumed' AND (consumed_at IS NOT NULL OR storage_object_id IS NOT NULL)) "
        "OR (state = 'rejected') <> (rejection_code IS NOT NULL) "
        "OR (state IN ('verified','consumed') AND verified_at IS NULL) "
        "OR (state = 'issued' AND verified_at IS NOT NULL) "
        "OR expires_at <= issued_at OR sweep_after < expires_at"
    ),
    "storage_upload_intents_object_mismatch": (
        "SELECT count(*) FROM storage_upload_intents i JOIN storage_objects o "
        "ON o.id = i.storage_object_id WHERE o.storage_bucket <> i.storage_bucket "
        "OR o.storage_key <> i.storage_key OR o.sha256 <> i.declared_sha256 "
        "OR o.size_bytes <> i.declared_size_bytes OR o.mime_type <> i.declared_mime_type"
    ),
}
DOMAIN_CHECKS.update(STORAGE_DOMAIN_CHECKS)


def foreign_key_orphan_checks():
    """One anti-join per contract foreign key: ``{name: sql}``."""
    checks = {}
    for table in pg_schema.PG_APPLICATION_TABLES:
        for fk in pg_schema.PG_TABLE_SPECS[table]["foreign_keys"]:
            join = " AND ".join(
                f"p.{parent} = c.{child}"
                for child, parent in zip(fk["columns"], fk["references_columns"])
            )
            present = " AND ".join(f"c.{child} IS NOT NULL" for child in fk["columns"])
            checks[fk["name"]] = (
                f"SELECT count(*) FROM {table} c WHERE {present} AND NOT EXISTS "
                f"(SELECT 1 FROM {fk['references_table']} p WHERE {join})"
            )
    return checks


def run_domain_checks(conn) -> dict:
    results = {}
    for name, sql in {**DOMAIN_CHECKS, **foreign_key_orphan_checks()}.items():
        results[name] = int(conn.execute(sql).fetchone()[0])
    return results


def _validate_loaded(conn, snapshot, report):
    mismatches = []
    for table in pg_schema.PG_APPLICATION_TABLES:
        policy = SOURCE_TABLE_POLICIES[table].policy
        target_rows = read_target_rows(conn, table)
        if policy == MIGRATE_EXACT:
            source = normalize_rows(table, snapshot.rows[table])
            target = normalize_rows(table, target_rows)
            found = compare_rows(table, source, target)
            mismatches += found
            if not found:
                report.digests[table] = table_digest(table, target)
        elif table == "schema_migrations":
            if len(target_rows) != len(pg_schema.PG_SCHEMA_MIGRATIONS_SEED):
                mismatches.append(Mismatch(table, (), "*", "SEED_CHANGED"))
        elif target_rows:
            mismatches.append(Mismatch(table, (), "*", "EXCLUDED_TABLE_NOT_EMPTY"))
    if mismatches:
        raise MigrationFailed("VALUE_VALIDATION_FAILED", f"{len(mismatches)} difference(s)", mismatches)

    for table, (high_water, expected_next) in report.sequences.items():
        if next_identity_value(conn, table) != expected_next:
            raise MigrationFailed("SEQUENCE_VALIDATION_FAILED", table)

    report.domain_checks = run_domain_checks(conn)
    broken = sorted(name for name, count in report.domain_checks.items() if count)
    if broken:
        raise MigrationFailed("DOMAIN_VALIDATION_FAILED", ", ".join(broken))
    try:
        pg_schema.validate_pg_schema(conn)
    except pg_schema.PostgresSchemaError as exc:
        raise MigrationFailed("TARGET_SCHEMA_CHANGED", str(exc)) from exc


def _prerequisites(snapshot, assets):
    prerequisites = []
    providers = {
        row[_columns("cloud_accounts").index("provider")] for row in snapshot.rows["cloud_accounts"]
    }
    google_files = any(
        row[_columns(table).index("provider")] == "google"
        for table in ("requisicao_arquivos", "admin_arquivos")
        for row in snapshot.rows[table]
    )
    mirror_bound = any(
        row[_columns("storage_objects").index("drive_account_key")] is not None
        for row in snapshot.rows["storage_objects"]
    )
    if google_files or "google" in providers or mirror_bound:
        prerequisites.append(GOOGLE_DRIVE_RECONNECT_REQUIRED)
    if "onedrive" in providers:
        prerequisites.append(ONEDRIVE_RECONNECT_REQUIRED)
    if snapshot.rows["configuracoes_backup"] or snapshot.rows["cloud_drive_settings"]:
        prerequisites.append(BACKUP_CONFIGURATION_REQUIRED)
    if assets:
        prerequisites.append(LOCAL_ASSETS_REQUIRED_IN_UPLOAD_ROOT)
    if snapshot.rows["storage_objects"]:
        prerequisites.append(CANONICAL_STORAGE_BUCKET_REQUIRED)
    return prerequisites


def _excluded(snapshot):
    excluded = {}
    for table, policy in SOURCE_TABLE_POLICIES.items():
        if policy.policy == MIGRATE_EXACT:
            continue
        if table == SQLITE_SEQUENCE_TABLE:
            rows = len(snapshot.sequences)
        else:
            rows = len(snapshot.rows[table])
        excluded[table] = (rows, policy.policy, policy.reasons)
    return excluded


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def migrate(
    source_path,
    expected_sha256,
    *,
    database_url=None,
    source_upload_root=None,
    target_upload_root=None,
    apply=False,
    announce=lambda line: None,
) -> MigrationReport:
    """Verify everything, then (only with ``apply``) migrate in one transaction."""
    report = MigrationReport(load_order=load_order())
    problems = policy_manifest_problems()
    if problems:
        raise MigrationRefused("POLICY_MANIFEST_INCOMPLETE", "; ".join(problems))
    url = database_url or require_target_url()
    if not url.startswith(("postgres://", "postgresql://")):
        raise MigrationRefused("TARGET_NOT_POSTGRESQL", "the target is not a PostgreSQL URL")

    snapshot = read_source(source_path, expected_sha256)
    report.source_sha256 = snapshot.sha256
    report.source_size = snapshot.size
    report.source_user_version = snapshot.user_version
    report.excluded = _excluded(snapshot)
    report.live_password_tokens_dropped = snapshot.live_password_tokens
    assets = plan_local_assets(snapshot, source_upload_root, target_upload_root)
    report.assets = assets
    report.prerequisites = _prerequisites(snapshot, assets)

    conn = connect_target(url)
    writer = _AssetWriter(source_upload_root, target_upload_root)
    try:
        report.target = target_identity(conn)
        announce(f"target: {report.target.label()}")
        report.server_version_num = check_target(conn)
        conn.rollback()
        if not apply:
            report.copied = {t: len(snapshot.rows[t]) for t in migrated_tables()}
            return report

        commit_sent = False
        try:
            _lock_target(conn)
            _require_empty_target(conn)
            for table in report.load_order:
                if SOURCE_TABLE_POLICIES[table].policy == MIGRATE_EXACT:
                    _load_table(conn, table, snapshot.rows[table], report)
                    report.copied[table] = len(snapshot.rows[table])
            _advance_identities(conn, snapshot, report)
            _validate_loaded(conn, snapshot, report)
            if not _source_unchanged(snapshot):
                raise MigrationFailed("SOURCE_CHANGED", "the source changed during the migration")
            for asset in assets:
                writer.write(asset)
            # Commit boundary: from here a failure no longer proves a rollback.
            commit_sent = True
            conn.commit()
        except BaseException as exc:
            if commit_sent:
                # The server may have committed: keep every copied file and
                # claim nothing; a rerun resolves either outcome safely.
                raise MigrationCommitUncertain(
                    "COMMIT_OUTCOME_UNCERTAIN",
                    f"{exc.__class__.__name__} while committing; nothing was rolled back "
                    "by this tool and copied files were kept",
                ) from exc
            conn.rollback()
            writer.undo()
            for asset in assets:
                if asset.status == "copied":
                    asset.status = "rolled_back"
            if isinstance(exc, (MigrationFailed, MigrationRefused)):
                raise
            import psycopg

            if isinstance(exc, psycopg.Error):
                state = getattr(exc, "sqlstate", None) or "?"
                raise MigrationFailed(
                    "TARGET_REJECTED_DATA", f"{exc.__class__.__name__} sqlstate={state}"
                ) from exc
            raise
        report.applied = True
    finally:
        conn.close()
    report.source_hash_verified_after = _source_unchanged(snapshot)
    return report


# ---------------------------------------------------------------------------
# report and command line
# ---------------------------------------------------------------------------


def format_report(report: MigrationReport) -> list[str]:
    lines = [
        f"source: sha256={report.source_sha256} size={report.source_size} "
        f"user_version={report.source_user_version} verified_before=yes "
        f"verified_after={'yes' if report.source_hash_verified_after else 'n/a' if not report.applied else 'NO'}",
    ]
    if report.target is not None:
        lines.append(f"target: {report.target.label()} server_version_num={report.server_version_num}")
    lines.append("load order: " + " -> ".join(t for t in report.load_order if t in report.copied))
    for table, rows in report.copied.items():
        digest = report.digests.get(table, "")
        lines.append(f"copied: {table} rows={rows}" + (f" sha256={digest}" if digest else ""))
    for table, (rows, policy, reasons) in sorted(report.excluded.items()):
        lines.append(f"excluded: {table} rows={rows} policy={policy} reasons={','.join(reasons)}")
    if report.live_password_tokens_dropped:
        lines.append(f"note: {report.live_password_tokens_dropped} unexpired password link(s) dropped")
    for name, count in report.self_references_restored.items():
        lines.append(f"self-reference restored: {name} rows={count}")
    for table, (high_water, next_value) in sorted(report.sequences.items()):
        lines.append(f"identity: {table} high_water={high_water} next={next_value}")
    if report.domain_checks:
        broken = sum(1 for count in report.domain_checks.values() if count)
        lines.append(f"domain checks: {len(report.domain_checks)} run, {broken} failing")
    for asset in report.assets:
        lines.append(
            f"asset: {asset.table} id={asset.row_id} size={asset.size} "
            f"sha256={asset.sha256} status={asset.status}"
        )
    for prerequisite in report.prerequisites:
        lines.append(f"prerequisite: {prerequisite}")
    if report.committed_source_unverified:
        lines.append(
            "result: COMMITTED_SOURCE_UNVERIFIED -- the target commit completed, but after it "
            "the source copy no longer matched the verified SHA-256; nothing was rolled back. "
            "Investigate the source copy and reconcile before using the target."
        )
    elif report.applied:
        lines.append("result: MIGRATED")
    else:
        lines.append("result: DRY RUN -- nothing written (pass --apply)")
    return lines


_USAGE = (
    "usage: python -m app.pg_migrate_from_sqlite --source FROZEN_COPY\n"
    "         --expected-source-sha256 HEX\n"
    "         [--source-upload-root DIR --target-upload-root DIR] [--apply]\n"
    "\n"
    "Path-B cutover: copies a frozen copy of the SQLite prod-1 (v15) database into\n"
    "the freshly provisioned, empty PostgreSQL database named by DATABASE_URL, in\n"
    "one transaction. Without --apply it only verifies source, target and local\n"
    "files. It refuses a non-empty or non-current target; there is no --force.\n"
    "\n"
    "exit: 0 migrated / dry run; 1 refused, or failed and rolled back; 2 usage;\n"
    "      3 COMMIT_OUTCOME_UNCERTAIN (check the target: rows => committed,\n"
    "        empty => rerun); 4 COMMITTED_SOURCE_UNVERIFIED (investigate).\n"
)

EXIT_COMMIT_UNCERTAIN = 3
EXIT_COMMITTED_SOURCE_UNVERIFIED = 4

_OPTIONS = {
    "--source": "source",
    "--expected-source-sha256": "expected",
    "--source-upload-root": "source_root",
    "--target-upload-root": "target_root",
}


class _UsageError(Exception):
    pass


def _parse_arguments(arguments):
    values = {"apply": False}
    pending = list(arguments)
    while pending:
        flag = pending.pop(0)
        if flag == "--apply":
            values["apply"] = True
            continue
        if flag not in _OPTIONS or not pending or _OPTIONS[flag] in values:
            raise _UsageError(flag)
        values[_OPTIONS[flag]] = pending.pop(0)
    if not values.get("source") or not values.get("expected"):
        raise _UsageError("--source/--expected-source-sha256")
    return values


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"-h", "--help"}:
        print(_USAGE)
        return 0
    try:
        options = _parse_arguments(arguments)
    except _UsageError:
        print(_USAGE, file=sys.stderr)
        return 2
    try:
        report = migrate(
            options["source"],
            options["expected"],
            source_upload_root=options.get("source_root"),
            target_upload_root=options.get("target_root"),
            apply=options["apply"],
            announce=print,
        )
    except MigrationRefused as exc:
        print(f"pg-migrate: refused: {exc}", file=sys.stderr)
        return 1
    except MigrationCommitUncertain as exc:
        print(f"pg-migrate: COMMIT OUTCOME UNCERTAIN: {exc}", file=sys.stderr)
        print(
            "pg-migrate: check the target before anything else: application rows present "
            "=> the migration committed (a rerun is refused); empty => rerun, identical "
            "copied files are reused",
            file=sys.stderr,
        )
        return EXIT_COMMIT_UNCERTAIN
    except MigrationFailed as exc:
        for mismatch in exc.mismatches[:50]:
            print(
                f"pg-migrate: mismatch table={mismatch.table} key={mismatch.primary_key} "
                f"column={mismatch.column} category={mismatch.category}",
                file=sys.stderr,
            )
        print(f"pg-migrate: FAILED and rolled back: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"pg-migrate: error: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    for line in format_report(report):
        print(line)
    if report.committed_source_unverified:
        return EXIT_COMMITTED_SOURCE_UNVERIFIED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MigrationCommitUncertain",
    "MigrationFailed",
    "MigrationRefused",
    "MigrationReport",
    "SOURCE_TABLE_POLICIES",
    "TARGET_ONLY_TABLE_POLICIES",
    "load_order",
    "main",
    "migrate",
]
