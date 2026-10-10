"""Legacy business-document convergence into canonical storage.

Legacy request documents and admin ARQUIVOS live on Google Drive
(``provider='google'``) or on the local disk (``provider='local_legacy'``).
Convergence copies their bytes into canonical Supabase Storage and LINKS the
legacy row to the new ``storage_objects`` row through ``storage_object_id``;
the row keeps its provider and locator as provenance and legacy residue.  A
row with a canonical reference is canonical custody, whatever its provider.

This module owns the ONE eligibility rule per table and provider -- the
census counts with it, the convergence acts on it -- and the provider ->
``storage_objects.origin`` rule the cross-check verifies.

THE ELIGIBILITY RULE
    A legacy row converges only from its steady state -- the state in which
    its bytes are known and nothing else is in flight:

    requisicao_arquivos  google        ``active`` with a Drive locator
                         local_legacy  ``legacy_active`` with a file name
    admin_arquivos       google        ``active`` with a Drive locator, no
                                       failure, residue or cleanup in flight
                         local_legacy  ``legacy_active`` with a file name, no
                                       replacement reservation or failure

    Every other legacy row is BLOCKED (pending, failed, in reconciliation, in
    deletion, trashed, mid-replacement): the census reports it by provider and
    status, and convergence never touches it.  Eligibility is a steady STATE;
    a locator outside the legal alphabet is classified when the row's bytes
    are read, so an eligible count is an upper bound.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field

from app.db import (
    DatabaseIntegrityError,
    classify_database_error,
    lock_admin_arquivo,
    lock_requisicao_arquivo,
    write_transaction,
)
from app.file_validation import detect_supported_mime
from app.prod1_document_custody_ddl import CANONICAL_PROVIDER, LEGACY_RESIDUE_PROVIDERS
from app.prod1_storage_ddl import (
    BUSINESS_DOCUMENT_MAX_BYTES,
    STORAGE_OBJECT_REFERENCE_TABLES,
    STORAGE_ORIGINS,
)
from app.storage import custody_common
from app.storage import drive_mirror
from app.storage.contracts import StorageError
from app.storage.object_store import (
    STORAGE_ALREADY_EXISTS,
    STORAGE_INTEGRITY_MISMATCH,
    STORAGE_OBJECT_TOO_LARGE,
    CanonicalStoreError,
    verify_existing,
)
from app.student_documents import resolve_student_document_path

logger = logging.getLogger(__name__)

STEADY_REQUEST_GOOGLE = (
    "provider = 'google' AND storage_status = 'active' AND storage_object_id IS NULL"
    " AND COALESCE(TRIM(remote_file_id), '') <> ''"
)
STEADY_REQUEST_LOCAL = (
    "provider = 'local_legacy' AND storage_status = 'legacy_active' AND storage_object_id IS NULL"
    " AND COALESCE(TRIM(filename), '') <> ''"
)
STEADY_ARQUIVO_GOOGLE = (
    "provider = 'google' AND storage_status = 'active' AND storage_object_id IS NULL"
    " AND failure_code IS NULL AND prior_provider IS NULL AND cleanup_started_at IS NULL"
    " AND COALESCE(TRIM(remote_file_id), '') <> ''"
)
STEADY_ARQUIVO_LOCAL = (
    "provider = 'local_legacy' AND storage_status = 'legacy_active' AND storage_object_id IS NULL"
    " AND operation_key IS NULL AND failure_code IS NULL AND COALESCE(TRIM(filename), '') <> ''"
)

TABLES = STORAGE_OBJECT_REFERENCE_TABLES
LEGACY_PROVIDERS = LEGACY_RESIDUE_PROVIDERS
#: The ``storage_objects.origin`` the canonical object of each business
#: provider carries: a direct upload for a canonical row, a migration for a
#: converged legacy row.
ORIGIN_BY_PROVIDER = {
    CANONICAL_PROVIDER: "direct_upload",
    "google": "migrated_google",
    "local_legacy": "migrated_local_legacy",
}
assert set(ORIGIN_BY_PROVIDER.values()) == set(STORAGE_ORIGINS)

_ELIGIBLE = {
    ("requisicao_arquivos", "google"): STEADY_REQUEST_GOOGLE,
    ("requisicao_arquivos", "local_legacy"): STEADY_REQUEST_LOCAL,
    ("admin_arquivos", "google"): STEADY_ARQUIVO_GOOGLE,
    ("admin_arquivos", "local_legacy"): STEADY_ARQUIVO_LOCAL,
}

_LEGACY_IN = "provider IN (" + ", ".join(f"'{provider}'" for provider in LEGACY_PROVIDERS) + ")"
#: Legacy rows not converged yet -- eligible or blocked.
UNCONVERGED_LEGACY = f"{_LEGACY_IN} AND storage_object_id IS NULL"
#: Legacy rows already linked to a canonical object.
CONVERGED_LEGACY = f"{_LEGACY_IN} AND storage_object_id IS NOT NULL"


def eligible_predicate(table: str, provider: str) -> str:
    """The fixed SQL predicate of the rows of ``table`` / ``provider`` that may converge."""
    try:
        return _ELIGIBLE[(table, provider)]
    except KeyError:
        raise ValueError("unknown legacy table or provider") from None


def _table(table: str) -> str:
    if table not in TABLES:
        raise ValueError("unknown legacy table")
    return table


def legacy_census(conn, table: str) -> dict:
    """Value-free counts of one business table's custody classes."""
    table = _table(table)

    def count(predicate: str) -> int:
        return int(conn.execute(f"SELECT count(*) FROM {table} WHERE {predicate}").fetchone()[0])

    eligible = {provider: count(eligible_predicate(table, provider)) for provider in LEGACY_PROVIDERS}
    eligible_any = " OR ".join(f"({eligible_predicate(table, provider)})" for provider in LEGACY_PROVIDERS)
    blocked = {
        f"{row[0]}:{row[1]}": int(row[2])
        for row in conn.execute(
            f"SELECT provider, storage_status, count(*) FROM {table}"
            f" WHERE {UNCONVERGED_LEGACY} AND NOT ({eligible_any})"
            " GROUP BY provider, storage_status ORDER BY provider, storage_status"
        ).fetchall()
    }
    converged = {
        str(row[0]): int(row[1])
        for row in conn.execute(
            f"SELECT provider, count(*) FROM {table} WHERE {CONVERGED_LEGACY} GROUP BY provider ORDER BY provider"
        ).fetchall()
    }
    return {
        "canonical": count("provider = 'supabase'"),
        "converged": converged,
        "eligible": eligible,
        "blocked": blocked,
        "unconverged": count(UNCONVERGED_LEGACY),
    }


# ---------------------------------------------------------------------------
# convergence (dry run / apply)
# ---------------------------------------------------------------------------

#: Deterministic canonical key directory per table: ``<directory>/<row id>``.
KEY_DIRECTORY = {"requisicao_arquivos": "legacy/comprovantes", "admin_arquivos": "legacy/arquivos"}
MAX_CONVERGE_BATCH = 500

WOULD_CONVERGE = "WOULD_CONVERGE"
CONVERGED = "CONVERGED"
SOURCE_LOCATOR_INVALID = "SOURCE_LOCATOR_INVALID"
SOURCE_MISSING = "SOURCE_MISSING"
SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
SOURCE_EMPTY = "SOURCE_EMPTY"
SOURCE_UNSUPPORTED = "SOURCE_UNSUPPORTED"
SOURCE_INTEGRITY_MISMATCH = "SOURCE_INTEGRITY_MISMATCH"
SOURCE_MIME_MISMATCH = "SOURCE_MIME_MISMATCH"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
SOURCE_UNREADABLE = "SOURCE_UNREADABLE"
DRIVE_UNAVAILABLE = "DRIVE_UNAVAILABLE"
TARGET_CONFLICT = "TARGET_CONFLICT"
TARGET_UNAVAILABLE = "TARGET_UNAVAILABLE"
CUSTODY_CHANGED = "CUSTODY_CHANGED"
ALREADY_CONVERGED = "ALREADY_CONVERGED"
LINK_REFUSED = "LINK_REFUSED"
SUCCESS_OUTCOMES = frozenset({WOULD_CONVERGE, CONVERGED, ALREADY_CONVERGED})


class _Skip(RuntimeError):
    """One row that does not converge now; ``code`` is a fixed outcome class."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _Candidate:
    table: str
    row_id: int
    provider: str
    filename: str
    remote_file_id: str | None
    remote_parent_id: str | None
    sha256: str | None
    size_bytes: int | None
    mime_type: str | None
    uploader_user_id: int | None


@dataclass(frozen=True)
class _Source:
    content: bytes
    sha256: str
    mime_type: str


@dataclass
class ConvergenceReport:
    """Value-free outcome counts per ``table:provider`` and in total.

    ``last_row_id`` per table is the cursor of the next run (``after_id``):
    rows that keep failing never fill the window again.
    """

    apply: bool
    outcomes: dict = field(default_factory=dict)
    adopted_targets: int = 0
    synced_mirrors: int = 0
    last_row_id: dict = field(default_factory=dict)

    def add(self, candidate: _Candidate, code: str) -> None:
        bucket = self.outcomes.setdefault(f"{candidate.table}:{candidate.provider}", {})
        bucket[code] = bucket.get(code, 0) + 1
        self.last_row_id[candidate.table] = candidate.row_id

    @property
    def totals(self) -> dict:
        totals: dict = {}
        for counts in self.outcomes.values():
            for code, count in counts.items():
                totals[code] = totals.get(code, 0) + count
        return totals

    @property
    def clean(self) -> bool:
        return set(self.totals) <= SUCCESS_OUTCOMES

    def as_dict(self) -> dict:
        return {"apply": self.apply, "outcomes": self.outcomes, "totals": self.totals,
                "adopted_targets": self.adopted_targets, "synced_mirrors": self.synced_mirrors,
                "last_row_id": self.last_row_id, "clean": self.clean}


_CANDIDATE_COLUMNS = (
    "id, provider, filename, remote_file_id, remote_parent_id, sha256, size_bytes, mime_type, uploader_user_id"
)


def _candidates(conn, table: str, limit: int, after_id: int) -> list[_Candidate]:
    either = " OR ".join(f"({eligible_predicate(table, provider)})" for provider in LEGACY_PROVIDERS)
    # A short transaction: no snapshot stays open while sources are read.
    with write_transaction(conn):
        rows = conn.execute(
            f"SELECT {_CANDIDATE_COLUMNS} FROM {table} WHERE ({either}) AND id > ? ORDER BY id LIMIT ?",
            (int(after_id), int(limit)),
        ).fetchall()
    return [
        _Candidate(table, int(row[0]), str(row[1]), str(row[2] or ""),
                   None if row[3] is None else str(row[3]), None if row[4] is None else str(row[4]),
                   None if row[5] is None else str(row[5]).lower(), None if row[6] is None else int(row[6]),
                   None if row[7] is None else str(row[7]), None if row[8] is None else int(row[8]))
        for row in rows
    ]


def _read_local(candidate: _Candidate, roots) -> bytes:
    for root in roots:
        if not root:
            continue
        try:
            path = resolve_student_document_path(str(root), candidate.filename)
        except ValueError:
            raise _Skip(SOURCE_LOCATOR_INVALID) from None
        if not os.path.isfile(path):
            continue
        try:
            if os.path.getsize(path) > BUSINESS_DOCUMENT_MAX_BYTES:
                raise _Skip(SOURCE_TOO_LARGE)
            with open(path, "rb") as handle:
                content = handle.read(BUSINESS_DOCUMENT_MAX_BYTES + 1)
        except OSError:
            raise _Skip(SOURCE_UNREADABLE) from None
        if len(content) > BUSINESS_DOCUMENT_MAX_BYTES:
            raise _Skip(SOURCE_TOO_LARGE)
        return content
    raise _Skip(SOURCE_MISSING)


def _read_google(candidate: _Candidate, drive) -> bytes:
    if drive is None:
        raise _Skip(DRIVE_UNAVAILABLE)
    if not custody_common.is_drive_id(candidate.remote_file_id):
        raise _Skip(SOURCE_LOCATOR_INVALID)
    if candidate.size_bytes is not None and candidate.size_bytes > BUSINESS_DOCUMENT_MAX_BYTES:
        raise _Skip(SOURCE_TOO_LARGE)
    try:
        content = drive.storage.download(candidate.remote_file_id)
    except StorageError:
        raise _Skip(SOURCE_UNAVAILABLE) from None
    if len(content) > BUSINESS_DOCUMENT_MAX_BYTES:
        raise _Skip(SOURCE_TOO_LARGE)
    return content


def _source(candidate: _Candidate, *, drive, roots) -> _Source:
    """The legacy bytes, proven against what the row recorded (when it recorded anything)."""
    if candidate.provider == "google":
        content = _read_google(candidate, drive)
    else:
        content = _read_local(candidate, roots)
    if not content:
        raise _Skip(SOURCE_EMPTY)
    mime = detect_supported_mime(content)
    if mime is None:
        raise _Skip(SOURCE_UNSUPPORTED)
    digest = hashlib.sha256(content).hexdigest()
    if (candidate.sha256 is not None and candidate.sha256 != digest) or (
        candidate.size_bytes is not None and candidate.size_bytes != len(content)
    ):
        raise _Skip(SOURCE_INTEGRITY_MISMATCH)
    if candidate.mime_type is not None and candidate.mime_type != mime:
        raise _Skip(SOURCE_MIME_MISMATCH)
    return _Source(content, digest, mime)


def canonical_key(table: str, row_id: int) -> str:
    """The deterministic canonical key of one legacy row's bytes."""
    return f"{KEY_DIRECTORY[_table(table)]}/{int(row_id)}"


def _store_target(store, bucket: str, key: str, source: _Source) -> bool:
    """Upload once (no upsert) and prove the stored bytes; ``True`` when an earlier upload is adopted."""
    adopted = False
    try:
        store.upload(bucket, key, source.content, mime_type=source.mime_type)
    except CanonicalStoreError as exc:
        if exc.code != STORAGE_ALREADY_EXISTS:
            raise _Skip(TARGET_UNAVAILABLE) from None
        adopted = True  # an interrupted earlier run's upload, if the bytes prove identical
    try:
        verify_existing(
            store, bucket, key, expected_size=len(source.content), expected_sha256=source.sha256,
            expected_mime_type=source.mime_type, max_bytes=BUSINESS_DOCUMENT_MAX_BYTES,
        )
    except CanonicalStoreError as exc:
        if exc.code in (STORAGE_INTEGRITY_MISMATCH, STORAGE_OBJECT_TOO_LARGE):
            raise _Skip(TARGET_CONFLICT) from None
        raise _Skip(TARGET_UNAVAILABLE) from None
    return adopted


def _custody_unchanged(row, candidate: _Candidate) -> bool:
    return row is not None and (
        str(row[0]), str(row[1] or ""), None if row[2] is None else str(row[2])
    ) == (candidate.provider, candidate.filename, candidate.remote_file_id)


def _link(conn, candidate: _Candidate, *, bucket: str, key: str, source: _Source, drive) -> bool:
    """Create the canonical object and link the row, in one transaction; ``True`` if the mirror is adopted.

    Lock order: the business row FIRST (``app.db.lock_*``), then the
    ``storage_objects`` insert.  The row must still be eligible with the
    custody this run read, so a concurrent removal, deletion, replacement or
    convergence of the same row wins and nothing is linked.
    """
    now = custody_common.utc_now_text()
    lock = lock_requisicao_arquivo if candidate.table == "requisicao_arquivos" else lock_admin_arquivo
    with write_transaction(conn):
        lock(conn, candidate.row_id)
        row = conn.execute(
            f"SELECT provider, filename, remote_file_id FROM {candidate.table}"
            f" WHERE id = ? AND {eligible_predicate(candidate.table, candidate.provider)}",
            (candidate.row_id,),
        ).fetchone()
        if not _custody_unchanged(row, candidate):
            linked = conn.execute(
                f"SELECT o.storage_key FROM {candidate.table} r JOIN storage_objects o"
                " ON o.id = r.storage_object_id WHERE r.id = ? AND o.storage_bucket = ?",
                (candidate.row_id, bucket),
            ).fetchone()
            # A concurrent run of this tool linked the same row to the same key.
            raise _Skip(ALREADY_CONVERGED if linked is not None and linked[0] == key else CUSTODY_CHANGED)
        columns = {
            "storage_backend": "supabase", "storage_bucket": bucket, "storage_key": key, "sha256": source.sha256,
            "size_bytes": len(source.content), "mime_type": source.mime_type,
            "uploader_user_id": candidate.uploader_user_id, "origin": ORIGIN_BY_PROVIDER[candidate.provider],
            "content_verified_at": now, "created_at": now,
        }
        # Adopt only while the account that served the bytes is still THE
        # active connection: a refresh after a 401 resolves whichever account
        # is active now, and a binding can never be changed afterwards.
        adopt_mirror = (
            candidate.provider == "google" and drive is not None
            and custody_common.is_drive_id(candidate.remote_parent_id)
            and drive_mirror.still_active(conn, drive)
        )
        if adopt_mirror:
            # The legacy Drive file IS the mirror: its bytes were just proven.
            columns.update(drive_sync_state="synced", drive_file_id=candidate.remote_file_id,
                           drive_parent_id=candidate.remote_parent_id, drive_account_key=drive.account_key,
                           drive_synced_at=now)
        names = ", ".join(columns)
        marks = ", ".join("?" for _ in columns)
        object_id = int(conn.execute(
            f"INSERT INTO storage_objects ({names}) VALUES ({marks}) RETURNING id", tuple(columns.values())
        ).fetchone()[0])
        linked = conn.execute(
            f"UPDATE {candidate.table} SET storage_object_id = ? WHERE id = ? AND storage_object_id IS NULL"
            " RETURNING id",
            (object_id, candidate.row_id),
        ).fetchone()
        if linked is None:  # pragma: no cover - excluded by the locked re-check above
            raise _Skip(CUSTODY_CHANGED)
    return adopt_mirror


def converge(
    conn,
    *,
    apply: bool,
    limit: int,
    tables=TABLES,
    store=None,
    bucket: str | None = None,
    drive=None,
    roots: dict | None = None,
    after_id: int = 0,
) -> ConvergenceReport:
    """Converge up to ``limit`` eligible legacy rows per table; dry run unless ``apply``.

    ``drive`` is the ACTIVE Drive (``drive_mirror.active_drive``) or None:
    Google rows are then reported ``DRIVE_UNAVAILABLE`` and local rows still
    converge.  ``roots`` maps each table to the upload roots its local files
    live under (the runtime's own: requests ``DOCUMENTOS_ALUNOS_FOLDER`` then
    ``UPLOAD_FOLDER``; ARQUIVOS ``UPLOAD_FOLDER``).  Every row commits on its
    own: an interrupted run is resumed by running again, which skips
    converged rows and adopts its own uploads.  ``after_id`` starts after a
    row id (the previous report's ``last_row_id``).  Legacy bytes are only READ.
    """
    custody_common.positive_limit(limit, MAX_CONVERGE_BATCH)
    if after_id and len(tuple(tables)) != 1:
        raise ValueError("after_id is a cursor of ONE table")
    if apply and (store is None or not bucket):
        raise ValueError("apply needs the canonical store and bucket")
    report = ConvergenceReport(apply=bool(apply))
    roots = roots or {}
    for table in tables:
        for candidate in _candidates(conn, _table(table), limit, after_id):
            try:
                source = _source(candidate, drive=drive, roots=roots.get(table, ()))
                if not apply:
                    report.add(candidate, WOULD_CONVERGE)
                    continue
                key = canonical_key(candidate.table, candidate.row_id)
                if _store_target(store, bucket, key, source):
                    report.adopted_targets += 1
                try:
                    if _link(conn, candidate, bucket=bucket, key=key, source=source, drive=drive):
                        report.synced_mirrors += 1
                except _Skip:
                    raise
                except Exception as exc:
                    # A constraint refusing the link (a Drive file already owned
                    # by another object) is a row outcome; any other database
                    # failure stops the run.
                    if not isinstance(classify_database_error(exc), DatabaseIntegrityError):
                        raise
                    raise _Skip(LINK_REFUSED) from None
                report.add(candidate, CONVERGED)
            except _Skip as skip:
                report.add(candidate, skip.code)
    logger.info("legacy convergence: %s", report.totals)
    return report


__all__ = [
    "ALREADY_CONVERGED",
    "CONVERGED",
    "CONVERGED_LEGACY",
    "ConvergenceReport",
    "KEY_DIRECTORY",
    "MAX_CONVERGE_BATCH",
    "LEGACY_PROVIDERS",
    "ORIGIN_BY_PROVIDER",
    "TABLES",
    "UNCONVERGED_LEGACY",
    "WOULD_CONVERGE",
    "canonical_key",
    "converge",
    "eligible_predicate",
    "legacy_census",
]
