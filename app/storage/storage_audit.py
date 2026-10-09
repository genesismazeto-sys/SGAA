"""Value-free census and cross-check of business-document custody.

Two operator questions, answered without exposing a single row value:

``census(conn)``
    How many documents sit in each custody class (canonical, converged
    legacy, eligible legacy, blocked legacy by provider / status), how many
    canonical objects per lifecycle, origin and Drive-mirror state, how many
    upload intents per state, and the mirror worker's health.

``cross_check(conn, ...)``
    Do the database references, the canonical Storage objects and the Drive
    mirrors CONVERGE?  Each check reports discrepancy CLASSES with counts:

    references  (database only)
        LIVE_ROW_OBJECT_RETIRED    a live business row points at a retired object
        TRASHED_ROW_OBJECT_ACTIVE  a removed comprovante's object is still active
        ACTIVE_OBJECT_UNOWNED      an active object no business row references
        ORIGIN_MISMATCH            the object's origin contradicts the row's
                                   provider (supabase <-> direct_upload,
                                   google <-> migrated_google,
                                   local_legacy <-> migrated_local_legacy)
        METADATA_MISMATCH          recorded SHA-256 / size / MIME differ
    storage     (canonical store; ``deep`` also hashes every object's bytes)
        OBJECT_MISSING, OBJECT_SIZE_MISMATCH, OBJECT_CONTENT_MISMATCH,
        STORAGE_CHECK_FAILED
    bucket      (``listing``: every stored object must be known)
        UNREFERENCED_INTENT_OBJECT  uploaded for an intent never consumed
        UNREFERENCED_OBJECT         unknown to the database
    mirror      (``drive``: synced mirrors of the active account)
        MIRROR_VERIFIED (intact), MIRROR_MISSING, MIRROR_DIVERGENT,
        MIRROR_CHECK_FAILED, MIRROR_ACCOUNT_INACTIVE (bound to another
        account: not verifiable here)

    ``mirrors_verified`` is True only when EVERY synced mirror was verified
    intact, False on any missing / divergent / failed check, None when some
    could not be verified (another account) and nothing failed.
    ``mirror_complete`` (database only) says whether every active object is
    ``synced`` -- a backlog is lag, not damage.

    ``reference_digest`` is the SHA-256 of the sorted reference set
    (``table|row|object|sha256|size|lifecycle``): two environments -- the
    SQLite source and the PostgreSQL target of a cutover -- hold the same
    references to the same canonical bytes exactly when their digests are
    equal (provider, status, origin and mirror state are not part of it).  Integer ids appear only on request
    (``show_ids``); names, file names, locators, keys, URLs and account keys
    never appear.

Read-only, except ``requeue_missing_mirrors``: a synced object whose Drive copy
is missing or divergent goes back to ``pending`` (``mirror_outbox.reset_missing_mirror``),
so the next mirror pass recreates it -- the mirror recovery.
"""

from __future__ import annotations

import hashlib

from app.db import write_transaction
from app.prod1_storage_ddl import (
    BUSINESS_DOCUMENT_MAX_BYTES,
    DRIVE_SYNC_STATES,
    INTENT_STATES,
    LIFECYCLE_STATES,
    STORAGE_ORIGINS,
)
from app.storage import custody_common
from app.storage import drive_mirror
from app.storage import legacy_convergence as convergence
from app.storage import mirror_outbox as outbox
from app.storage.contracts import StorageError
from app.storage.object_store import STORAGE_OBJECT_MISSING, CanonicalStoreError

MAX_LISTED_OBJECTS = 200_000
MAX_IDS_PER_CLASS = 1000

REFERENCE_CLASSES = (
    "LIVE_ROW_OBJECT_RETIRED", "TRASHED_ROW_OBJECT_ACTIVE", "ACTIVE_OBJECT_UNOWNED",
    "ORIGIN_MISMATCH", "METADATA_MISMATCH",
)
STORAGE_CLASSES = ("OBJECT_MISSING", "OBJECT_SIZE_MISMATCH", "OBJECT_CONTENT_MISMATCH", "STORAGE_CHECK_FAILED")
BUCKET_CLASSES = ("UNREFERENCED_INTENT_OBJECT", "UNREFERENCED_OBJECT")
MIRROR_CLASSES = (
    "MIRROR_VERIFIED", "MIRROR_MISSING", "MIRROR_DIVERGENT", "MIRROR_CHECK_FAILED", "MIRROR_ACCOUNT_INACTIVE",
)

_TABLE_ROW_STATE = {
    # A business row is LIVE when its document is current (a trashed
    # comprovante is kept as evidence; every ARQUIVOS row is live).
    "requisicao_arquivos": "r.storage_status IN ('active','legacy_active')",
    "admin_arquivos": "1 = 1",
}
assert set(_TABLE_ROW_STATE) == set(convergence.TABLES)
_ORIGIN_MISMATCH = " OR ".join(
    f"(r.provider = '{provider}' AND o.origin <> '{origin}')"
    for provider, origin in sorted(convergence.ORIGIN_BY_PROVIDER.items())
)
_METADATA_MISMATCH = (
    "(r.sha256 IS NOT NULL AND lower(r.sha256) <> o.sha256)"
    " OR (r.size_bytes IS NOT NULL AND r.size_bytes <> o.size_bytes)"
    " OR (r.mime_type IS NOT NULL AND r.mime_type <> o.mime_type)"
)


def _counts(conn, sql: str, keys) -> dict:
    found = {str(row[0]): int(row[1]) for row in conn.execute(sql).fetchall()}
    return {key: found.get(key, 0) for key in keys} | {k: v for k, v in found.items() if k not in keys}


def census(conn) -> dict:
    """Counts of every custody class; see the module docstring."""
    mirror = _counts(
        conn,
        "SELECT drive_sync_state, count(*) FROM storage_objects WHERE lifecycle_state = 'active'"
        " GROUP BY drive_sync_state",
        DRIVE_SYNC_STATES,
    )
    active = sum(mirror.values())
    return {
        "documents": {table: convergence.legacy_census(conn, table) for table in convergence.TABLES},
        "objects": {
            "lifecycle": _counts(
                conn, "SELECT lifecycle_state, count(*) FROM storage_objects GROUP BY lifecycle_state",
                LIFECYCLE_STATES,
            ),
            "origin": _counts(
                conn, "SELECT origin, count(*) FROM storage_objects GROUP BY origin", STORAGE_ORIGINS
            ),
            "mirror": mirror,
            "mirror_complete": mirror["synced"] == active,
        },
        "intents": _counts(
            conn, "SELECT state, count(*) FROM storage_upload_intents GROUP BY state", INTENT_STATES
        ),
        "worker": outbox.read_worker_status(conn),
    }


# ---------------------------------------------------------------------------
# cross-check
# ---------------------------------------------------------------------------


class _Findings:
    def __init__(self, classes, show_ids: bool) -> None:
        self.counts = {name: 0 for name in classes}
        self.ids: dict[str, list] = {}
        self._show = show_ids

    def add(self, name: str, ident) -> None:
        self.counts[name] += 1
        if self._show and len(self.ids.setdefault(name, [])) < MAX_IDS_PER_CLASS:
            self.ids[name].append(ident)

    @property
    def clean(self) -> bool:
        return not any(self.counts.values())


def _reference_findings(conn, findings: _Findings) -> None:
    for table, live in _TABLE_ROW_STATE.items():
        joined = f"FROM {table} r JOIN storage_objects o ON o.id = r.storage_object_id"
        for name, predicate in (
            ("LIVE_ROW_OBJECT_RETIRED", f"{live} AND o.lifecycle_state <> 'active'"),
            ("ORIGIN_MISMATCH", _ORIGIN_MISMATCH),
            ("METADATA_MISMATCH", _METADATA_MISMATCH),
        ):
            for row in conn.execute(f"SELECT r.id {joined} WHERE {predicate} ORDER BY r.id").fetchall():
                findings.add(name, f"{table}:{int(row[0])}")
    for row in conn.execute(
        "SELECT r.id FROM requisicao_arquivos r JOIN storage_objects o ON o.id = r.storage_object_id"
        " WHERE r.storage_status = 'trashed' AND o.lifecycle_state = 'active' ORDER BY r.id"
    ).fetchall():
        findings.add("TRASHED_ROW_OBJECT_ACTIVE", f"requisicao_arquivos:{int(row[0])}")
    unowned = " AND ".join(
        f"NOT EXISTS (SELECT 1 FROM {table} r WHERE r.storage_object_id = o.id)" for table in convergence.TABLES
    )
    for row in conn.execute(
        f"SELECT o.id FROM storage_objects o WHERE o.lifecycle_state = 'active' AND {unowned} ORDER BY o.id"
    ).fetchall():
        findings.add("ACTIVE_OBJECT_UNOWNED", f"storage_objects:{int(row[0])}")


def census_mirror_complete(conn) -> bool:
    """Whether every ACTIVE canonical object is ``synced`` (no mirror backlog)."""
    return conn.execute(
        "SELECT count(*) FROM storage_objects WHERE lifecycle_state = 'active' AND drive_sync_state <> 'synced'"
    ).fetchone()[0] == 0


def reference_digest(conn) -> str:
    """SHA-256 of the sorted business-row -> canonical-object reference set."""
    lines = []
    for table in convergence.TABLES:
        for row in conn.execute(
            f"SELECT r.id, o.id, o.sha256, o.size_bytes, o.lifecycle_state FROM {table} r"
            " JOIN storage_objects o ON o.id = r.storage_object_id"
        ).fetchall():
            lines.append(f"{table}|{int(row[0])}|{int(row[1])}|{row[2]}|{int(row[3])}|{row[4]}")
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def _objects(conn) -> list:
    return conn.execute(
        "SELECT id, storage_bucket, storage_key, size_bytes, sha256 FROM storage_objects ORDER BY id"
    ).fetchall()


def _storage_findings(store, objects, listed: dict | None, deep: bool, findings: _Findings) -> None:
    for row in objects:
        object_id, bucket, key, size, digest = int(row[0]), str(row[1]), str(row[2]), int(row[3]), str(row[4])
        ident = f"storage_objects:{object_id}"
        try:
            if listed is not None:
                if (bucket, key) not in listed:
                    findings.add("OBJECT_MISSING", ident)
                    continue
                observed = listed[(bucket, key)]
                if observed is None:
                    observed = store.stat(bucket, key).size_bytes
            else:
                observed = store.stat(bucket, key).size_bytes
            if observed != size:
                findings.add("OBJECT_SIZE_MISMATCH", ident)
                continue
            if deep:
                content = store.read(bucket, key, max_bytes=BUSINESS_DOCUMENT_MAX_BYTES)
                if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                    findings.add("OBJECT_CONTENT_MISMATCH", ident)
        except CanonicalStoreError as exc:
            findings.add("OBJECT_MISSING" if exc.code == STORAGE_OBJECT_MISSING else "STORAGE_CHECK_FAILED", ident)


def _bucket_findings(conn, listed: dict, objects, findings: _Findings) -> None:
    known = {(str(row[1]), str(row[2])) for row in objects}
    intents = {
        (str(row[0]), str(row[1]))
        for row in conn.execute(
            "SELECT storage_bucket, storage_key FROM storage_upload_intents WHERE state <> 'consumed'"
        ).fetchall()
    }
    for locator in sorted(listed):
        if locator in known:
            continue
        # Bucket keys are never echoed; an unreferenced object is reported by count only.
        findings.add("UNREFERENCED_INTENT_OBJECT" if locator in intents else "UNREFERENCED_OBJECT", None)


def _mirror_findings(conn, drive, findings: _Findings, requeue: bool, now: str) -> int:
    requeued = 0
    rows = conn.execute(
        "SELECT id, drive_file_id, drive_account_key, size_bytes, sha256, lifecycle_state FROM storage_objects"
        " WHERE drive_sync_state = 'synced' ORDER BY id"
    ).fetchall()
    for row in rows:
        object_id, file_id, account = int(row[0]), str(row[1]), str(row[2])
        ident = f"storage_objects:{object_id}"
        if account != drive.account_key:
            findings.add("MIRROR_ACCOUNT_INACTIVE", ident)
            continue
        try:
            remote = drive.storage.describe_file(file_id)
        except StorageError:
            findings.add("MIRROR_CHECK_FAILED", ident)
            continue
        if remote is None:
            name = "MIRROR_MISSING"
        elif int(remote.size) != int(row[3]) or str(remote.sha256 or "").lower() != str(row[4]):
            name = "MIRROR_DIVERGENT"
        else:
            findings.add("MIRROR_VERIFIED", None)
            continue
        if not drive_mirror.still_active(conn, drive):
            # A refresh may have switched accounts: the file was looked up in
            # another Drive, so its absence proves nothing here.
            findings.add("MIRROR_CHECK_FAILED", ident)
            continue
        findings.add(name, ident)
        if requeue and row[5] == "active":
            with write_transaction(conn):
                requeued += outbox.reset_missing_mirror(
                    conn, object_id=object_id, drive_file_id=file_id, error_code=name, now=now
                )
    return requeued


def _listing(store, buckets) -> dict:
    listed = {}
    for bucket in sorted(buckets):
        for item in store.list_objects(bucket, "", max_objects=MAX_LISTED_OBJECTS):
            listed[(bucket, item.key)] = item.size_bytes
    return listed


def cross_check(
    conn,
    *,
    store=None,
    deep: bool = False,
    listing: bool = True,
    buckets=(),
    drive=None,
    requeue_missing_mirrors: bool = False,
    show_ids: bool = False,
) -> dict:
    """The convergence verdict; see the module docstring.

    ``store`` None skips the storage and bucket checks (their verdicts are
    ``None``, and ``converged`` cannot be true); ``drive`` None skips the
    mirror verification.  ``buckets`` adds configured buckets to the ones the
    database names, so an empty database still sees a polluted bucket.
    """
    references = _Findings(REFERENCE_CLASSES, show_ids)
    _reference_findings(conn, references)
    report: dict = {"references": references.counts}
    verdict = {"references_consistent": references.clean, "storage_consistent": None, "bucket_clean": None,
               "mirrors_verified": None}
    ids: dict = dict(references.ids)
    objects = _objects(conn)
    if store is not None:
        listed = None
        if listing:
            listed = _listing(store, {str(row[1]) for row in objects} | set(buckets))
        storage = _Findings(STORAGE_CLASSES, show_ids)
        _storage_findings(store, objects, listed, deep, storage)
        report["storage"] = storage.counts | {"checked": len(objects), "deep": bool(deep)}
        verdict["storage_consistent"] = storage.clean
        ids.update(storage.ids)
        if listed is not None:
            bucket = _Findings(BUCKET_CLASSES, False)
            _bucket_findings(conn, listed, objects, bucket)
            report["bucket"] = bucket.counts | {"listed": len(listed)}
            verdict["bucket_clean"] = bucket.clean
    if drive is not None:
        mirror = _Findings(MIRROR_CLASSES, show_ids)
        requeued = _mirror_findings(conn, drive, mirror, requeue_missing_mirrors, custody_common.utc_now_text())
        report["mirror"] = mirror.counts | {"requeued": requeued}
        if any(mirror.counts[name] for name in ("MIRROR_MISSING", "MIRROR_DIVERGENT", "MIRROR_CHECK_FAILED")):
            verdict["mirrors_verified"] = False
        else:
            verdict["mirrors_verified"] = None if mirror.counts["MIRROR_ACCOUNT_INACTIVE"] else True
        ids.update({name: found for name, found in mirror.ids.items() if name != "MIRROR_VERIFIED"})
    legacy_remaining = sum(
        convergence.legacy_census(conn, table)["unconverged"] for table in convergence.TABLES
    )
    verdict["legacy_converged"] = legacy_remaining == 0
    verdict["mirror_complete"] = bool(census_mirror_complete(conn))
    verdict["converged"] = bool(
        verdict["references_consistent"] and verdict["storage_consistent"] is True and verdict["legacy_converged"]
    )
    report.update(legacy_remaining=legacy_remaining, reference_digest=reference_digest(conn), verdict=verdict)
    if show_ids:
        report["ids"] = ids
    return report


__all__ = [
    "BUCKET_CLASSES",
    "MIRROR_CLASSES",
    "REFERENCE_CLASSES",
    "STORAGE_CLASSES",
    "census",
    "cross_check",
    "reference_digest",
]
