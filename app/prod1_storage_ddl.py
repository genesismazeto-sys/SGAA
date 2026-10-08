"""Canonical prod-1/v14 canonical-storage schema objects.

v14 prepares business-document custody on a canonical object store
(Supabase Storage) with Google Drive as an asynchronous secondary mirror.  It
is purely additive and changes no runtime behaviour: nothing in the request
or ARQUIVOS flows writes these objects yet (that is STORAGE S3).

    storage_objects          one canonical stored object (bucket + key), its
                             verified content metadata, lifecycle and the
                             durable Drive-mirror outbox state with its lease
    storage_upload_intents   short-lived, server-issued upload authorizations
                             (ephemeral: never migrated, never restored)
    storage_worker_status    at most one row (id 1) of mirror-worker health;
                             no row means "never ran" (target-side state)

    requisicao_arquivos.storage_object_id   nullable FK, NULL until S3/S5
    admin_arquivos.storage_object_id        nullable FK, NULL until S3/S5

THE CONTRACT
    * ``storage_backend`` is only ``supabase``: Google Drive is never a
      canonical backend.  ``(storage_bucket, storage_key)`` is unique; keys
      are server-generated, relative and drawn from a fixed alphabet.
    * Content metadata pins what the business-document validator accepts
      today: PDF / PNG / JPEG (``app.file_validation``), at most 16 MiB (the
      request cap), lowercase hex SHA-256.  ``content_verified_at`` is
      mandatory: a row exists only once its bytes were verified.
    * Lifecycle ``active`` / ``retired``.  ``purge_after`` is inert future
      metadata: nothing purges a canonical object in v14.
    * Drive mirror: ``pending`` / ``syncing`` / ``synced`` / ``retry`` /
      ``reconciliation_required``.  ``synced`` carries the Drive file id, the
      LOGICAL Google account (``drive_account_key``, see below) and
      ``drive_synced_at``;
      ``syncing`` and only ``syncing`` carries a lease; ``retry`` and
      ``reconciliation_required`` carry a sanitized error code
      (``[A-Z0-9_]``, at most 64 characters -- never exception text).
    * Timestamps are ``YYYY-MM-DD HH:MM:SS`` UTC text, exactly, so lease and
      due-time comparisons are plain text comparisons on both engines.
    * Drive account identity is LOGICAL, never a credential row:
      ``drive_account_key`` = ``cloud_accounts.provider_account_key`` =
      SHA-256(b"google" + NUL + Google OIDC ``sub``), 64 lowercase hex
      (``app.cloud_account_identity``).  There is deliberately NO foreign key
      to ``cloud_accounts``: a reconnect creates a new credential row, and
      Path B recreates ``cloud_accounts`` target-side, while the mirror's
      account must survive both.  Once bound, an object's Drive account never
      changes silently (trigger); S4 decides how an intentional account change
      opens a new generation.
    * ``cloud_accounts.provider_account_key`` (nullable: rows whose identity
      was never established keep NULL; it is never derived from an e-mail)
      is added by v14; ``cloud_accounts.id`` stays the credential-instance id.
    * A canonical object is owned by at most one business file row: a partial
      UNIQUE index per table plus a cross-table trigger.
    * An upload intent changes only along issued -> verified -> consumed (or
      -> rejected / expired); its identity, binding and declared metadata never
      change, and a terminal intent is frozen except ``sweep_after``.

WHY ``ALTER TABLE ... ADD COLUMN`` IN THE BOOTSTRAP TOO
    The business tables keep their v4/v5 DDL; SQLite records an added column
    by editing the stored ``CREATE TABLE`` text.  The fresh bootstrap runs the
    very same ``ALTER`` statements as the migration, so a migrated database and
    a fresh one store identical DDL and reach the same physical signature.

The PostgreSQL authority (``app.pg_schema``) declares the same logical objects.
"""

from __future__ import annotations


#: Hard cap for one business document: the request limit (``MAX_CONTENT_LENGTH``)
#: and the comprovante / ARQUIVOS validators' 16 MiB.
BUSINESS_DOCUMENT_MAX_BYTES = 16 * 1024 * 1024
#: Exactly the types ``app.file_validation.detect_supported_mime`` accepts.
BUSINESS_DOCUMENT_MIME_TYPES = ("application/pdf", "image/png", "image/jpeg")

STORAGE_BACKENDS = ("supabase",)
STORAGE_ORIGINS = ("direct_upload", "migrated_local_legacy", "migrated_google")
LIFECYCLE_STATES = ("active", "retired")
DRIVE_SYNC_STATES = ("pending", "syncing", "synced", "retry", "reconciliation_required")
INTENT_PURPOSES = ("comprovante", "admin_arquivo")
INTENT_STATES = ("issued", "verified", "consumed", "rejected", "expired")
INTENT_NONTERMINAL_STATES = ("issued", "verified")
INTENT_TERMINAL_STATES = ("consumed", "rejected", "expired")

STORAGE_BUCKET_MAX_LENGTH = 63
STORAGE_KEY_MAX_LENGTH = 256
OPERATION_ID_MAX_LENGTH = 124  # the existing operation_key bound (Drive appProperties)
ERROR_CODE_MAX_LENGTH = 64
DRIVE_ID_MAX_LENGTH = 256
ORIGINAL_FILENAME_MAX_LENGTH = 255
LEASE_TOKEN_LENGTH = 32
INTENT_ID_LENGTH = 32

STORAGE_V14_TABLES = ("storage_objects", "storage_upload_intents", "storage_worker_status")
STORAGE_OBJECT_REFERENCE_TABLES = ("requisicao_arquivos", "admin_arquivos")


def _in(values) -> str:
    return ",".join(f"'{value}'" for value in values)


def _ts(column: str) -> str:
    """Exact canonical ``YYYY-MM-DD HH:MM:SS`` text that is also a real date-time.

    ``datetime(col) IS col`` -- never ``=``: ``datetime()`` is NULL for an
    impossible value (``2024-13-45 99:99:99``, second 60), and a CHECK that
    evaluates to NULL PASSES in SQLite.  ``IS`` turns that NULL into a refusal,
    and a value SQLite would normalize (``2024-02-30`` -> ``2024-03-01``) also
    differs from its canonical form.  Hour 24 and year 0000, which SQLite's
    ``datetime()`` echoes back unchanged, are refused explicitly.  The same
    rule as the PostgreSQL ``_ts_check`` -- one verdict on both engines.
    """
    return (
        f"({column} GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'"
        f" AND substr({column},1,4)<>'0000' AND substr({column},12,2)<='23'"
        f" AND datetime({column}) IS {column})"
    )


def _opt_ts(column: str) -> str:
    return f"({column} IS NULL OR {_ts(column)})"


def _code(column: str) -> str:
    return (
        f"({column} IS NULL OR (length({column}) BETWEEN 1 AND {ERROR_CODE_MAX_LENGTH}"
        f" AND {column} NOT GLOB '*[^A-Z0-9_]*'))"
    )


def _hex(column: str, length: int) -> str:
    return f"(length({column})={length} AND {column} NOT GLOB '*[^0-9a-f]*')"


def _bucket(column: str) -> str:
    return (
        f"(length({column}) BETWEEN 1 AND {STORAGE_BUCKET_MAX_LENGTH}"
        f" AND {column} NOT GLOB '*[^a-z0-9._-]*')"
    )


def _key(column: str) -> str:
    return (
        f"(length({column}) BETWEEN 1 AND {STORAGE_KEY_MAX_LENGTH}"
        f" AND {column} NOT GLOB '*[^A-Za-z0-9/_.-]*'"
        f" AND substr({column},1,1)<>'/' AND instr({column},'..')=0)"
    )


def _drive_id(column: str) -> str:
    return (
        f"({column} IS NULL OR (length({column}) BETWEEN 1 AND {DRIVE_ID_MAX_LENGTH}"
        f" AND {column} NOT GLOB '*[^A-Za-z0-9_-]*'))"
    )


STORAGE_OBJECTS_V14_TABLE_SQL = f"""CREATE TABLE storage_objects (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 storage_backend TEXT NOT NULL CHECK(storage_backend IN ({_in(STORAGE_BACKENDS)})),
 storage_bucket TEXT NOT NULL CHECK{_bucket('storage_bucket')},
 storage_key TEXT NOT NULL CHECK{_key('storage_key')},
 sha256 TEXT NOT NULL CHECK{_hex('sha256', 64)},
 size_bytes INTEGER NOT NULL CHECK(size_bytes>0 AND size_bytes<={BUSINESS_DOCUMENT_MAX_BYTES}),
 mime_type TEXT NOT NULL CHECK(mime_type IN ({_in(BUSINESS_DOCUMENT_MIME_TYPES)})),
 uploader_user_id INTEGER,
 origin TEXT NOT NULL CHECK(origin IN ({_in(STORAGE_ORIGINS)})),
 content_verified_at TEXT NOT NULL CHECK{_ts('content_verified_at')},
 created_at TEXT NOT NULL DEFAULT (datetime('now')) CHECK{_ts('created_at')},
 lifecycle_state TEXT NOT NULL DEFAULT 'active' CHECK(lifecycle_state IN ({_in(LIFECYCLE_STATES)})),
 retired_at TEXT CHECK{_opt_ts('retired_at')},
 purge_after TEXT CHECK{_opt_ts('purge_after')},
 drive_sync_state TEXT NOT NULL DEFAULT 'pending' CHECK(drive_sync_state IN ({_in(DRIVE_SYNC_STATES)})),
 drive_generation INTEGER NOT NULL DEFAULT 0 CHECK(drive_generation>=0),
 drive_file_id TEXT CHECK{_drive_id('drive_file_id')},
 drive_parent_id TEXT CHECK{_drive_id('drive_parent_id')},
 drive_account_key TEXT CHECK(drive_account_key IS NULL OR {_hex('drive_account_key', 64)}),
 drive_attempts INTEGER NOT NULL DEFAULT 0 CHECK(drive_attempts>=0),
 drive_next_attempt_at TEXT CHECK{_opt_ts('drive_next_attempt_at')},
 drive_last_attempt_at TEXT CHECK{_opt_ts('drive_last_attempt_at')},
 drive_last_error_code TEXT CHECK{_code('drive_last_error_code')},
 drive_synced_at TEXT CHECK{_opt_ts('drive_synced_at')},
 lease_token TEXT CHECK(lease_token IS NULL OR {_hex('lease_token', LEASE_TOKEN_LENGTH)}),
 lease_expires_at TEXT CHECK{_opt_ts('lease_expires_at')},
 FOREIGN KEY(uploader_user_id) REFERENCES usuarios(id) ON DELETE RESTRICT ON UPDATE CASCADE,
 UNIQUE(storage_bucket,storage_key),
 CHECK(origin<>'direct_upload' OR uploader_user_id IS NOT NULL),
 CHECK((lifecycle_state='active' AND retired_at IS NULL AND purge_after IS NULL)
    OR (lifecycle_state='retired' AND retired_at IS NOT NULL)),
 CHECK((drive_sync_state='syncing') = (lease_token IS NOT NULL)),
 CHECK((lease_token IS NULL) = (lease_expires_at IS NULL)),
 CHECK(drive_sync_state<>'synced' OR (drive_file_id IS NOT NULL AND drive_account_key IS NOT NULL
    AND drive_synced_at IS NOT NULL)),
 CHECK(drive_sync_state NOT IN ('retry','reconciliation_required') OR drive_last_error_code IS NOT NULL),
 CHECK(drive_sync_state<>'retry' OR drive_next_attempt_at IS NOT NULL),
 CHECK(drive_file_id IS NULL OR drive_account_key IS NOT NULL)
)"""

STORAGE_UPLOAD_INTENTS_V14_TABLE_SQL = f"""CREATE TABLE storage_upload_intents (
 id TEXT NOT NULL PRIMARY KEY CHECK{_hex('id', INTENT_ID_LENGTH)},
 actor_user_id INTEGER NOT NULL,
 purpose TEXT NOT NULL CHECK(purpose IN ({_in(INTENT_PURPOSES)})),
 operation_id TEXT NOT NULL CHECK(length(operation_id) BETWEEN 1 AND {OPERATION_ID_MAX_LENGTH}
    AND operation_id NOT GLOB '*[^A-Za-z0-9_.:-]*'),
 storage_bucket TEXT NOT NULL CHECK{_bucket('storage_bucket')},
 storage_key TEXT NOT NULL CHECK{_key('storage_key')},
 requisicao_id INTEGER,
 admin_arquivo_id INTEGER,
 original_filename TEXT CHECK(original_filename IS NULL
    OR length(original_filename) BETWEEN 1 AND {ORIGINAL_FILENAME_MAX_LENGTH}),
 declared_mime_type TEXT NOT NULL CHECK(declared_mime_type IN ({_in(BUSINESS_DOCUMENT_MIME_TYPES)})),
 declared_size_bytes INTEGER NOT NULL CHECK(declared_size_bytes>0
    AND declared_size_bytes<={BUSINESS_DOCUMENT_MAX_BYTES}),
 declared_sha256 TEXT NOT NULL CHECK{_hex('declared_sha256', 64)},
 state TEXT NOT NULL DEFAULT 'issued' CHECK(state IN ({_in(INTENT_STATES)})),
 rejection_code TEXT CHECK{_code('rejection_code')},
 issued_at TEXT NOT NULL CHECK{_ts('issued_at')},
 expires_at TEXT NOT NULL CHECK{_ts('expires_at')},
 sweep_after TEXT NOT NULL CHECK{_ts('sweep_after')},
 verified_at TEXT CHECK{_opt_ts('verified_at')},
 consumed_at TEXT CHECK{_opt_ts('consumed_at')},
 storage_object_id INTEGER,
 FOREIGN KEY(actor_user_id) REFERENCES usuarios(id) ON DELETE CASCADE,
 FOREIGN KEY(requisicao_id) REFERENCES requisicoes(id) ON DELETE CASCADE,
 FOREIGN KEY(admin_arquivo_id) REFERENCES admin_arquivos(id) ON DELETE CASCADE,
 FOREIGN KEY(storage_object_id) REFERENCES storage_objects(id) ON DELETE RESTRICT,
 UNIQUE(storage_bucket,storage_key),
 UNIQUE(actor_user_id,purpose,operation_id),
 UNIQUE(storage_object_id),
 CHECK(expires_at>issued_at AND sweep_after>=expires_at),
 CHECK(purpose='comprovante' OR requisicao_id IS NULL),
 CHECK(purpose='admin_arquivo' OR admin_arquivo_id IS NULL),
 CHECK((state='rejected') = (rejection_code IS NOT NULL)),
 CHECK((state IN ('verified','consumed')) = (verified_at IS NOT NULL) OR state IN ('rejected','expired')),
 CHECK((state='consumed') = (consumed_at IS NOT NULL AND storage_object_id IS NOT NULL)),
 CHECK(state='consumed' OR (consumed_at IS NULL AND storage_object_id IS NULL))
)"""

STORAGE_WORKER_STATUS_V14_TABLE_SQL = f"""CREATE TABLE storage_worker_status (
 id INTEGER PRIMARY KEY CHECK(id=1),
 last_started_at TEXT NOT NULL CHECK{_ts('last_started_at')},
 last_finished_at TEXT CHECK{_opt_ts('last_finished_at')},
 last_result_code TEXT CHECK{_code('last_result_code')},
 last_claimed_count INTEGER NOT NULL DEFAULT 0 CHECK(last_claimed_count>=0),
 last_synced_count INTEGER NOT NULL DEFAULT 0 CHECK(last_synced_count>=0),
 last_retry_count INTEGER NOT NULL DEFAULT 0 CHECK(last_retry_count>=0),
 CHECK((last_finished_at IS NULL) = (last_result_code IS NULL)),
 CHECK(last_finished_at IS NULL OR last_finished_at>=last_started_at)
)"""

#: The business tables gain their canonical reference.  The bootstrap runs
#: these exact statements after creating the v4/v5 tables (see module doc).
#: The logical provider-account identity on the credential rows (nullable).
CLOUD_ACCOUNTS_PROVIDER_KEY_COLUMN_SQL = (
    "ALTER TABLE cloud_accounts ADD COLUMN provider_account_key TEXT"
    f" CHECK(provider_account_key IS NULL OR {_hex('provider_account_key', 64)})"
)

BUSINESS_STORAGE_OBJECT_COLUMN_SQL = tuple(
    f"ALTER TABLE {table} ADD COLUMN storage_object_id INTEGER"
    " REFERENCES storage_objects(id) ON DELETE RESTRICT"
    for table in STORAGE_OBJECT_REFERENCE_TABLES
)

_EXCLUSIVE_TRIGGER_SQL = """CREATE TRIGGER trg_{table}_storage_object_{event_name}
BEFORE {event} ON {table} FOR EACH ROW
WHEN NEW.storage_object_id IS NOT NULL
  AND EXISTS(SELECT 1 FROM {other} WHERE storage_object_id=NEW.storage_object_id)
BEGIN SELECT RAISE(ABORT,'storage object already owned by another business file'); END"""


def _exclusive_triggers():
    statements = []
    for table, other in (
        ("requisicao_arquivos", "admin_arquivos"),
        ("admin_arquivos", "requisicao_arquivos"),
    ):
        for event_name, event in (("insert", "INSERT"), ("update", "UPDATE OF storage_object_id")):
            statements.append(
                _EXCLUSIVE_TRIGGER_SQL.format(table=table, other=other, event=event, event_name=event_name)
            )
    return tuple(statements)


#: Columns fixed at issue time, whatever the state.
INTENT_IMMUTABLE_COLUMNS = (
    "id", "actor_user_id", "purpose", "operation_id", "storage_bucket", "storage_key",
    "requisicao_id", "admin_arquivo_id", "original_filename", "declared_mime_type",
    "declared_size_bytes", "declared_sha256", "issued_at", "expires_at",
)
#: Columns a terminal intent never changes again (``sweep_after`` stays mutable).
INTENT_TERMINAL_FROZEN_COLUMNS = (
    "state", "rejection_code", "verified_at", "consumed_at", "storage_object_id",
)
#: Legal state changes; anything else is refused by the trigger.
INTENT_TRANSITIONS = (
    ("issued", "verified"), ("issued", "rejected"), ("issued", "expired"),
    ("verified", "consumed"), ("verified", "rejected"), ("verified", "expired"),
)


def _intent_transition_trigger() -> str:
    changed = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in INTENT_IMMUTABLE_COLUMNS)
    frozen = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in INTENT_TERMINAL_FROZEN_COLUMNS)
    legal = " OR ".join(f"(OLD.state='{a}' AND NEW.state='{b}')" for a, b in INTENT_TRANSITIONS)
    return f"""CREATE TRIGGER trg_storage_upload_intents_transition
BEFORE UPDATE ON storage_upload_intents FOR EACH ROW
WHEN {changed}
  OR (OLD.state IN ({_in(INTENT_TERMINAL_STATES)}) AND ({frozen}))
  OR (NEW.state IS NOT OLD.state AND NOT ({legal}))
BEGIN SELECT RAISE(ABORT,'invalid storage upload intent transition'); END"""


STORAGE_V14_TABLE_SQL = (
    STORAGE_OBJECTS_V14_TABLE_SQL,
    STORAGE_UPLOAD_INTENTS_V14_TABLE_SQL,
    STORAGE_WORKER_STATUS_V14_TABLE_SQL,
)

STORAGE_V14_INDEX_SQL = (
    "CREATE INDEX idx_storage_objects_drive_due ON storage_objects(drive_sync_state,drive_next_attempt_at)",
    "CREATE INDEX idx_storage_objects_uploader ON storage_objects(uploader_user_id)",
    "CREATE UNIQUE INDEX ux_storage_objects_drive_file ON storage_objects(drive_account_key,drive_file_id)"
    " WHERE drive_file_id IS NOT NULL",
    "CREATE INDEX idx_storage_upload_intents_state_expires ON storage_upload_intents(state,expires_at)",
    # Credential resolution: drive_account_key -> active row of that logical account.
    "CREATE INDEX idx_cloud_accounts_provider_account_key ON cloud_accounts(provider,provider_account_key,active)",
    "CREATE UNIQUE INDEX ux_req_arquivos_storage_object ON requisicao_arquivos(storage_object_id)"
    " WHERE storage_object_id IS NOT NULL",
    "CREATE UNIQUE INDEX ux_admin_arquivos_storage_object ON admin_arquivos(storage_object_id)"
    " WHERE storage_object_id IS NOT NULL",
)

#: An object's Drive account, once bound, is never silently replaced or dropped.
DRIVE_ACCOUNT_BOUND_TRIGGER_SQL = """CREATE TRIGGER trg_storage_objects_drive_account_bound
BEFORE UPDATE OF drive_account_key ON storage_objects FOR EACH ROW
WHEN OLD.drive_account_key IS NOT NULL AND NEW.drive_account_key IS NOT OLD.drive_account_key
BEGIN SELECT RAISE(ABORT,'storage object Drive account is already bound'); END"""

STORAGE_V14_TRIGGER_SQL = _exclusive_triggers() + (_intent_transition_trigger(), DRIVE_ACCOUNT_BOUND_TRIGGER_SQL)

#: Every v14 statement in execution order (tables, business columns, indexes,
#: triggers) -- shared verbatim by the bootstrap and the v13 -> v14 migration.
STORAGE_V14_STATEMENTS = (
    STORAGE_V14_TABLE_SQL
    + (CLOUD_ACCOUNTS_PROVIDER_KEY_COLUMN_SQL,)
    + BUSINESS_STORAGE_OBJECT_COLUMN_SQL
    + STORAGE_V14_INDEX_SQL
    + STORAGE_V14_TRIGGER_SQL
)
STORAGE_V14_SCHEMA_OBJECTS_SQL = ";\n".join(STORAGE_V14_STATEMENTS) + ";"


__all__ = [
    "BUSINESS_DOCUMENT_MAX_BYTES",
    "BUSINESS_DOCUMENT_MIME_TYPES",
    "BUSINESS_STORAGE_OBJECT_COLUMN_SQL",
    "CLOUD_ACCOUNTS_PROVIDER_KEY_COLUMN_SQL",
    "DRIVE_ID_MAX_LENGTH",
    "DRIVE_SYNC_STATES",
    "ERROR_CODE_MAX_LENGTH",
    "INTENT_ID_LENGTH",
    "INTENT_IMMUTABLE_COLUMNS",
    "INTENT_NONTERMINAL_STATES",
    "INTENT_PURPOSES",
    "INTENT_STATES",
    "INTENT_TERMINAL_FROZEN_COLUMNS",
    "INTENT_TERMINAL_STATES",
    "INTENT_TRANSITIONS",
    "LEASE_TOKEN_LENGTH",
    "LIFECYCLE_STATES",
    "OPERATION_ID_MAX_LENGTH",
    "ORIGINAL_FILENAME_MAX_LENGTH",
    "STORAGE_BACKENDS",
    "STORAGE_BUCKET_MAX_LENGTH",
    "STORAGE_KEY_MAX_LENGTH",
    "STORAGE_OBJECT_REFERENCE_TABLES",
    "STORAGE_ORIGINS",
    "STORAGE_V14_SCHEMA_OBJECTS_SQL",
    "STORAGE_V14_STATEMENTS",
    "STORAGE_V14_TABLES",
    "STORAGE_V14_TABLE_SQL",
]
