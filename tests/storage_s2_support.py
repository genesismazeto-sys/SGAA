"""Shared STORAGE S2 (prod-1/v14) fixtures: one constraint vector, both engines.

``OBJECT_CASES`` / ``INTENT_CASES`` / ``WORKER_CASES`` are ``(label, overrides,
accepted)`` triples applied to a valid base row; the SQLite and the real-PG
suites run the same vectors, so the two physical authorities cannot drift.
"""

from __future__ import annotations

TS = "2026-01-02 03:04:05"
LATER = "2026-01-02 03:19:05"
SWEEP = "2026-01-03 03:19:05"
BUCKET = "sgaa-documentos"
MIB16 = 16 * 1024 * 1024


def object_row(**overrides) -> dict:
    row = dict(
        storage_backend="supabase", storage_bucket=BUCKET,
        storage_key="comprovantes/2026/01/" + "a" * 32, sha256="a" * 64, size_bytes=1024,
        mime_type="application/pdf", uploader_user_id=1, origin="direct_upload",
        content_verified_at=TS, created_at=TS, lifecycle_state="active", drive_sync_state="pending",
        drive_generation=0, drive_attempts=0,
    )
    row.update(overrides)
    return row


def intent_row(**overrides) -> dict:
    row = dict(
        id="1" * 32, actor_user_id=1, purpose="comprovante", operation_id="batch-1:0:abcdef",
        storage_bucket=BUCKET, storage_key="comprovantes/2026/01/" + "b" * 32,
        declared_mime_type="application/pdf", declared_size_bytes=1024, declared_sha256="b" * 64,
        state="issued", issued_at=TS, expires_at=LATER, sweep_after=SWEEP,
    )
    row.update(overrides)
    return row


#: Logical Google-account keys (SHA-256 of synthetic subjects; never a credential row).
ACCOUNT_KEY = "a1" * 32
OTHER_ACCOUNT_KEY = "b2" * 32
SYNCED = dict(drive_sync_state="synced", drive_file_id="drv-1", drive_account_key=ACCOUNT_KEY, drive_synced_at=TS)
SYNCING = dict(drive_sync_state="syncing", lease_token="c" * 32, lease_expires_at=LATER)

OBJECT_CASES = (
    ("valid", {}, True),
    ("google is never a canonical backend", dict(storage_backend="google"), False),
    ("empty bucket", dict(storage_bucket=""), False),
    ("bucket alphabet", dict(storage_bucket="Bucket"), False),
    ("empty key", dict(storage_key=""), False),
    ("absolute key", dict(storage_key="/x/y"), False),
    ("traversal key", dict(storage_key="a/../b"), False),
    ("key alphabet", dict(storage_key="a b"), False),
    ("key at the 256 limit", dict(storage_key="k" * 256), True),
    ("key over the limit", dict(storage_key="k" * 257), False),
    ("uppercase sha256", dict(sha256="A" * 64), False),
    ("short sha256", dict(sha256="a" * 63), False),
    ("zero size", dict(size_bytes=0), False),
    ("16 MiB is the cap", dict(size_bytes=MIB16), True),
    ("over 16 MiB", dict(size_bytes=MIB16 + 1), False),
    ("pdf/png/jpeg only", dict(mime_type="image/webp"), False),
    ("png", dict(mime_type="image/png"), True),
    ("unknown origin", dict(origin="upload"), False),
    ("migrated without uploader", dict(origin="migrated_google", uploader_user_id=None), True),
    ("direct upload needs uploader", dict(uploader_user_id=None), False),
    ("verification is mandatory", dict(content_verified_at=None), False),
    ("timestamp shape", dict(content_verified_at="2026-01-02T03:04:05Z"), False),
    ("impossible timestamp", dict(content_verified_at="2026-02-30 03:04:05"), False),
    # Review M1: SQLite datetime() is NULL for these and a NULL CHECK passes;
    # PostgreSQL normalizes second 60 / hour 24.  Both engines must refuse.
    ("impossible month/day/time", dict(content_verified_at="2024-13-45 99:99:99"), False),
    ("leap second", dict(content_verified_at="2024-01-01 23:59:60"), False),
    ("hour 24", dict(content_verified_at="2024-01-01 24:00:00"), False),
    ("minute 60", dict(content_verified_at="2024-01-01 23:60:00"), False),
    ("year zero", dict(content_verified_at="0000-01-01 00:00:00"), False),
    ("29 February of a common year", dict(content_verified_at="2023-02-29 00:00:00"), False),
    ("29 February of a leap year", dict(content_verified_at="2024-02-29 00:00:00"), True),
    ("last second of the year", dict(content_verified_at="2024-12-31 23:59:59"), True),
    ("impossible lease expiry", {**SYNCING, "lease_expires_at": "2026-13-45 99:99:99"}, False),
    ("impossible retired_at", dict(lifecycle_state="retired", retired_at="2024-01-01 23:59:60"), False),
    ("retired needs retired_at", dict(lifecycle_state="retired"), False),
    ("retired", dict(lifecycle_state="retired", retired_at=TS), True),
    ("retired with inert purge_after", dict(lifecycle_state="retired", retired_at=TS, purge_after=SWEEP), True),
    ("active cannot carry purge_after", dict(purge_after=SWEEP), False),
    ("unknown mirror state", dict(drive_sync_state="done"), False),
    ("synced complete", SYNCED, True),
    ("synced without file id", {**SYNCED, "drive_file_id": None}, False),
    ("synced without account", {**SYNCED, "drive_account_key": None}, False),
    ("account key is lowercase hex", {**SYNCED, "drive_account_key": ACCOUNT_KEY.upper()}, False),
    ("account key is 64 chars", {**SYNCED, "drive_account_key": ACCOUNT_KEY[:-1]}, False),
    ("no credential-row FK: any well-formed key", {**SYNCED, "drive_account_key": "0" * 64}, True),
    ("pending before any account is bound", dict(drive_sync_state="pending"), True),
    ("pending keeps a bound account", dict(drive_sync_state="pending", drive_account_key=ACCOUNT_KEY), True),
    ("reconciliation keeps a bound account", dict(drive_sync_state="reconciliation_required",
                                                  drive_last_error_code="X", drive_account_key=ACCOUNT_KEY), True),
    ("synced without time", {**SYNCED, "drive_synced_at": None}, False),
    ("syncing with lease", SYNCING, True),
    ("syncing without lease", dict(drive_sync_state="syncing"), False),
    ("lease outside syncing", dict(lease_token="c" * 32, lease_expires_at=LATER), False),
    ("half lease", {**SYNCING, "lease_expires_at": None}, False),
    ("lease token shape", {**SYNCING, "lease_token": "C" * 32}, False),
    ("retry needs code and due time", dict(drive_sync_state="retry"), False),
    ("retry", dict(drive_sync_state="retry", drive_last_error_code="DRIVE_QUOTA", drive_next_attempt_at=LATER), True),
    ("error code is sanitized", dict(drive_sync_state="retry", drive_last_error_code="quota exceeded!",
                                     drive_next_attempt_at=LATER), False),
    ("error code bound", dict(drive_sync_state="retry", drive_last_error_code="E" * 65,
                              drive_next_attempt_at=LATER), False),
    ("reconciliation needs a code", dict(drive_sync_state="reconciliation_required"), False),
    ("drive file id without account", dict(drive_file_id="drv-2"), False),
    ("drive id alphabet", dict(drive_file_id="drv 2", drive_account_key=ACCOUNT_KEY), False),
    ("negative generation", dict(drive_generation=-1), False),
)

INTENT_CASES = (
    ("valid", {}, True),
    # Review M2: a NULL TEXT PRIMARY KEY was accepted by SQLite.
    ("NULL id", dict(id=None), False),
    ("intent id shape", dict(id="X" * 32), False),
    ("impossible expiry", dict(expires_at="2026-13-45 99:99:99", sweep_after="2026-13-45 99:99:99"), False),
    ("leap-second issue time", dict(issued_at="2026-01-02 03:04:60"), False),
    ("unknown purpose", dict(purpose="avatar"), False),
    ("operation alphabet", dict(operation_id="op 1"), False),
    ("operation bound", dict(operation_id="o" * 125), False),
    ("key is server-shaped", dict(storage_key="../x"), False),
    ("declared type", dict(declared_mime_type="text/html"), False),
    ("declared size cap", dict(declared_size_bytes=MIB16 + 1), False),
    ("declared sha", dict(declared_sha256="B" * 64), False),
    ("window must be open", dict(expires_at=TS), False),
    ("sweep after expiry", dict(sweep_after=TS), False),
    ("comprovante cannot bind ARQUIVOS", dict(admin_arquivo_id=1), False),
    ("ARQUIVOS cannot bind a request", dict(purpose="admin_arquivo", requisicao_id=1), False),
    ("rejected needs a code", dict(state="rejected"), False),
    ("rejected", dict(state="rejected", rejection_code="STORAGE_INTEGRITY_MISMATCH"), True),
    ("code only when rejected", dict(rejection_code="X"), False),
    ("verified needs verified_at", dict(state="verified"), False),
    ("issued cannot be verified", dict(verified_at=TS), False),
    ("consumed needs object", dict(state="consumed", verified_at=TS, consumed_at=TS), False),
    ("object only when consumed", dict(state="verified", verified_at=TS, storage_object_id=1), False),
)

WORKER_CASES = (
    ("valid", {}, True),
    ("impossible start time", dict(last_started_at="2024-13-45 99:99:99"), False),
    ("singleton", dict(id=2), False),
    ("finished needs a result", dict(last_finished_at=LATER), False),
    ("finished", dict(last_finished_at=LATER, last_result_code="OK"), True),
    ("finished before started", dict(last_finished_at="2026-01-01 00:00:00", last_result_code="OK"), False),
    ("result is a code", dict(last_finished_at=LATER, last_result_code="ok: done"), False),
    ("counts are non-negative", dict(last_claimed_count=-1), False),
)


def worker_row(**overrides) -> dict:
    row = dict(id=1, last_started_at=TS)
    row.update(overrides)
    return row


def insert_sql(table: str, row: dict, placeholder: str = "?") -> tuple[str, tuple]:
    columns = ", ".join(row)
    marks = ", ".join(placeholder for _ in row)
    return f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(row.values())


__all__ = [
    "ACCOUNT_KEY", "BUCKET", "INTENT_CASES", "OTHER_ACCOUNT_KEY", "LATER", "MIB16", "OBJECT_CASES", "SWEEP", "SYNCED", "SYNCING", "TS",
    "WORKER_CASES", "insert_sql", "intent_row", "object_row", "worker_row",
]
