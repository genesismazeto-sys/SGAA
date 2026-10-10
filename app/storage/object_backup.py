"""Operator object backup of the canonical documents: backup / verify / restore.

The Layer-2 database backup holds rows, never object bytes.  This module is the
other half: a self-checking *set* of every canonical object, written by an
operator to storage they control and encrypt, and the tools to prove and use it.

SET LAYOUT (a directory, outside the repository)

    MANIFEST.json                    sealed description of the set (written last)
    objects/<sha256[:2]>/<sha256>    one file per distinct content

MANIFEST.json holds, per ``storage_objects`` row: id, bucket, key, size, SHA-256,
MIME type and lifecycle state; the counts; the ``objects_digest`` (SHA-256 of the
canonical row list) and the ``seal`` (SHA-256 of everything else).  The seal
detects corruption and truncation; it is an integrity check, not authenticity --
the set's confidentiality and tamper-resistance are the storage's job.

GUARANTEES
    * ``backup`` only READS: every object is read back through the verified read
      (size and SHA-256 against the database row), each from its recorded bucket.
      Any unreadable object aborts the backup and no set is promoted, so a
      promoted set is always complete.
    * A set is written to a staging directory and promoted by rename only when
      complete; an existing destination is never replaced; a destination inside
      the repository -- by its path or through a link or junction -- is refused.
    * ``verify_set`` is offline (no database, no store): the seal, the counts,
      every file's size and SHA-256 and the absence of unexpected entries.  With
      a connection it also compares the set with the database rows.
    * ``restore`` verifies the set first, never overwrites or deletes: an object
      already present is adopted only when its size, SHA-256 and MIME type match,
      otherwise it is a conflict; everything it uploaded is read back.

Reports carry counts, integer ids and fixed codes -- never a key, URL, file name
or byte.  The manifest necessarily holds the opaque storage keys (restore needs
them) and no name or file name.  A killed run can leave ``<destination>.partial-*``
holding the bytes of the objects read so far: it is personal data, delete it.
Only operators run this module (``app.storage.cli``); no web module imports it
(MP-1 invariant I3).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from app.prod1_storage_ddl import (
    BUSINESS_DOCUMENT_MAX_BYTES,
    BUSINESS_DOCUMENT_MIME_TYPES,
    LIFECYCLE_STATES,
)
from app.storage import custody_common
from app.storage.object_store import (
    STORAGE_ALREADY_EXISTS,
    STORAGE_INTEGRITY_MISMATCH,
    STORAGE_OBJECT_TOO_LARGE,
    CanonicalObjectStore,
    CanonicalStoreError,
    read_verified,
    verify_existing,
)
from app.storage.supabase_store import check_locator

FORMAT = 1
KIND = "sgaa-object-backup"
MANIFEST_NAME = "MANIFEST.json"
OBJECTS_DIR = "objects"
MAX_OBJECTS = 100_000
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
LIST_LIMIT = 50  # ids named per discrepancy class in a report (counts are always complete)
_CHUNK = 1024 * 1024
_LINK_REPARSE_TAGS = frozenset(
    {getattr(stat, "IO_REPARSE_TAG_SYMLINK", -1), getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)}
)

RESULT_OK = "OK"
DESTINATION_EXISTS = "DESTINATION_EXISTS"
DESTINATION_INVALID = "DESTINATION_INVALID"
DESTINATION_INSIDE_REPOSITORY = "DESTINATION_INSIDE_REPOSITORY"
INSUFFICIENT_SPACE = "INSUFFICIENT_SPACE"
LABEL_INVALID = "LABEL_INVALID"
TOO_MANY_OBJECTS = "TOO_MANY_OBJECTS"
UNREADABLE_OBJECTS = "UNREADABLE_OBJECTS"
PROMOTE_FAILED = "PROMOTE_FAILED"
SET_INVALID = "SET_INVALID"
SET_NOT_FOUND = "SET_NOT_FOUND"
TARGET_BUCKET_INVALID = "TARGET_BUCKET_INVALID"
TARGET_CONFLICT = "TARGET_CONFLICT"
STORE_FAILURE = "STORE_FAILURE"
READBACK_MISMATCH = "READBACK_MISMATCH"

_LABEL_RE = re.compile(r"^[A-Za-z0-9._-]{0,64}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SHARD_RE = re.compile(r"^[0-9a-f]{2}$")
_TOP_KEYS = {"format", "kind", "label", "created_at", "counts", "objects", "objects_digest", "seal"}
_ROW_KEYS = {"id", "bucket", "key", "size", "sha256", "mime", "lifecycle"}
_COUNT_KEYS = {"objects", "contents", "bytes", "active", "retired"}
_REPO_ROOT = Path(__file__).resolve().parents[2]


class SetInvalid(ValueError):
    """The set (or its manifest) is not what a backup writes; ``code`` is fixed."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------


@dataclass
class BackupReport:
    result_code: str = RESULT_OK
    objects: int = 0
    contents: int = 0
    bytes: int = 0
    objects_digest: str | None = None
    unreadable: dict = field(default_factory=dict)  # error code -> row ids (bounded)
    unreadable_count: int = 0
    staged_as: str | None = None  # the kept staging directory's name when promotion failed

    @property
    def ok(self) -> bool:
        return self.result_code == RESULT_OK

    def as_dict(self) -> dict:
        return {
            "result_code": self.result_code,
            "objects": self.objects,
            "contents": self.contents,
            "bytes": self.bytes,
            "objects_digest": self.objects_digest,
            "unreadable_count": self.unreadable_count,
            "unreadable": {code: ids for code, ids in sorted(self.unreadable.items())},
            "staged_as": self.staged_as,
        }


@dataclass
class VerifyReport:
    result_code: str = RESULT_OK
    sealed: bool = False
    objects: int = 0
    contents: int = 0
    bytes: int = 0
    objects_digest: str | None = None
    missing: int = 0
    corrupt: int = 0
    unexpected: int = 0
    database: dict | None = None  # None: not compared

    @property
    def ok(self) -> bool:
        database_clean = self.database is None or all(
            self.database[name] == 0 for name in ("missing", "extra", "changed")
        )
        return self.result_code == RESULT_OK and database_clean

    def as_dict(self) -> dict:
        return {
            "result_code": self.result_code,
            "sealed": self.sealed,
            "objects": self.objects,
            "contents": self.contents,
            "bytes": self.bytes,
            "objects_digest": self.objects_digest,
            "missing": self.missing,
            "corrupt": self.corrupt,
            "unexpected": self.unexpected,
            "database": self.database,
        }


@dataclass
class RestoreReport:
    result_code: str = RESULT_OK
    objects: int = 0
    restored: int = 0
    adopted: int = 0
    conflicts: int = 0
    failed: int = 0
    readback_failed: int = 0
    stopped: bool = False
    ids: dict = field(default_factory=dict)  # class -> row ids (bounded)

    @property
    def ok(self) -> bool:
        return (
            self.result_code == RESULT_OK
            and not (self.conflicts or self.failed or self.readback_failed or self.stopped)
        )

    def as_dict(self) -> dict:
        return {
            "result_code": self.result_code,
            "objects": self.objects,
            "restored": self.restored,
            "adopted": self.adopted,
            "conflicts": self.conflicts,
            "failed": self.failed,
            "readback_failed": self.readback_failed,
            "stopped": self.stopped,
            "ids": {name: ids for name, ids in sorted(self.ids.items())},
        }


# ---------------------------------------------------------------------------
# canonical forms
# ---------------------------------------------------------------------------


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def objects_digest(rows: list[dict]) -> str:
    """SHA-256 of the canonical, id-ordered row list (the set's identity of what it protects)."""
    return _sha256(_canonical(sorted(rows, key=lambda row: row["id"])))


def _seal(manifest: dict) -> str:
    return _sha256(_canonical({key: value for key, value in manifest.items() if key != "seal"}))


def _object_relpath(sha256: str) -> str:
    return os.path.join(OBJECTS_DIR, sha256[:2], sha256)


def _bounded(ids: list[int]) -> list[int]:
    return ids[:LIST_LIMIT]


def _is_link(path: str) -> bool:
    """A symbolic link, or on Windows a symlink or junction reparse point.

    Only those tags: other reparse points (app-execution aliases, cloud placeholders,
    deduplicated files) are ordinary files and directories for this purpose.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) in _LINK_REPARSE_TAGS


def _is_plain_dir(path: str) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not _is_link(path)


# ---------------------------------------------------------------------------
# database rows
# ---------------------------------------------------------------------------


def current_rows(conn) -> list[dict]:
    """Every ``storage_objects`` row (active and retired), in the manifest's row shape."""
    rows = conn.execute(
        "SELECT id, storage_bucket, storage_key, size_bytes, sha256, mime_type, lifecycle_state"
        " FROM storage_objects ORDER BY id"
    ).fetchall()
    return [
        {"id": int(r[0]), "bucket": str(r[1]), "key": str(r[2]), "size": int(r[3]),
         "sha256": str(r[4]), "mime": str(r[5]), "lifecycle": str(r[6])}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(root)]) == os.path.normcase(root)
    except ValueError:  # another drive
        return False


def _inside_repository(path: str, repo_root: Path) -> bool:
    """By its path, or once every link and junction on the way is resolved."""
    root = str(repo_root)
    if _inside(path, root) or _inside(path, os.path.realpath(root)):
        return True
    resolved = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
    return _inside(resolved, os.path.realpath(root))


def _resolve_destination(destination: str, repo_root: Path) -> str:
    if not str(destination or "").strip():
        raise SetInvalid(DESTINATION_INVALID)
    path = os.path.abspath(str(destination))
    if _inside_repository(path, repo_root):
        raise SetInvalid(DESTINATION_INSIDE_REPOSITORY)
    if os.path.lexists(path):
        raise SetInvalid(DESTINATION_EXISTS)
    if not os.path.isdir(os.path.dirname(path)):
        raise SetInvalid(DESTINATION_INVALID)
    return path


def backup(
    conn,
    store: CanonicalObjectStore,
    destination: str,
    *,
    label: str = "",
    repo_root: Path | None = None,
) -> BackupReport:
    """Write a complete, sealed set of every canonical object to a NEW directory.

    ``conn`` must carry no uncommitted work: the rows are read once and the read
    transaction is ended (``rollback``) before the objects are copied, so a long
    copy never holds a lock on ``storage_objects``.
    """
    if not _LABEL_RE.fullmatch(label or ""):
        raise SetInvalid(LABEL_INVALID)
    target = _resolve_destination(destination, repo_root or _REPO_ROOT)
    rows = current_rows(conn)
    # The rows are a read-only snapshot: end the read transaction now so a long copy never
    # holds a lock on ``storage_objects`` (PostgreSQL keeps ACCESS SHARE until it ends).
    conn.rollback()
    report = BackupReport(objects=len(rows))
    if len(rows) > MAX_OBJECTS:
        report.result_code = TOO_MANY_OBJECTS
        return report
    distinct: dict[str, int] = {}
    for row in rows:
        distinct.setdefault(row["sha256"], row["size"])
    report.contents = len(distinct)
    report.bytes = sum(distinct.values())
    parent = os.path.dirname(target)
    if shutil.disk_usage(parent).free < report.bytes * 1.05 + 1024 * 1024:
        report.result_code = INSUFFICIENT_SPACE
        return report

    staging = f"{target}.partial-{secrets.token_hex(6)}"
    os.mkdir(staging)
    try:
        written: set[str] = set()
        failures: dict[str, list[int]] = {}
        for row in rows:
            try:
                content, _stat = read_verified(
                    store, row["bucket"], row["key"], expected_size=row["size"],
                    expected_sha256=row["sha256"], max_bytes=BUSINESS_DOCUMENT_MAX_BYTES,
                )
            except CanonicalStoreError as exc:
                failures.setdefault(exc.code, []).append(row["id"])
                continue
            if row["sha256"] not in written:
                _write_content(staging, row["sha256"], content)
                written.add(row["sha256"])
        if failures:
            report.result_code = UNREADABLE_OBJECTS
            report.unreadable_count = sum(len(ids) for ids in failures.values())
            report.unreadable = {code: _bounded(ids) for code, ids in failures.items()}
            return report
        digest = objects_digest(rows)
        manifest = {
            "format": FORMAT,
            "kind": KIND,
            "label": label or "",
            "created_at": custody_common.utc_now_text(),
            "counts": {
                "objects": len(rows),
                "contents": len(distinct),
                "bytes": report.bytes,
                "active": sum(1 for row in rows if row["lifecycle"] == "active"),
                "retired": sum(1 for row in rows if row["lifecycle"] != "active"),
            },
            "objects": rows,
            "objects_digest": digest,
        }
        manifest["seal"] = _seal(manifest)
        _write_file(os.path.join(staging, MANIFEST_NAME), json.dumps(manifest, indent=1, sort_keys=True).encode("ascii"))
        try:
            os.rename(staging, target)
        except FileExistsError:
            report.result_code = DESTINATION_EXISTS
            return report
        except OSError:
            # A complete set that could not be renamed (a lock, a permission): keep it, name it.
            report.result_code = PROMOTE_FAILED
            report.staged_as = os.path.basename(staging)
            staging = ""
            return report
        staging = ""
        report.objects_digest = digest
        return report
    finally:
        if staging and os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)


def _write_file(path: str, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _write_content(root: str, sha256: str, content: bytes) -> None:
    shard = os.path.join(root, OBJECTS_DIR, sha256[:2])
    os.makedirs(shard, exist_ok=True)
    _write_file(os.path.join(root, _object_relpath(sha256)), content)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def _read_manifest(set_dir: str) -> dict:
    path = os.path.join(set_dir, MANIFEST_NAME)
    try:
        info = os.lstat(path)
    except OSError:
        raise SetInvalid(SET_INVALID, "manifest missing") from None
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_MANIFEST_BYTES:  # S_ISREG: never a link
        raise SetInvalid(SET_INVALID, "manifest")
    with open(path, "rb") as handle:
        raw = handle.read(MAX_MANIFEST_BYTES + 1)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):  # not UTF-8, not JSON, nested too deep, a number too long
        raise SetInvalid(SET_INVALID, "manifest not JSON") from None
    return _validate_manifest(manifest)


def _validate_manifest(manifest) -> dict:
    if not isinstance(manifest, dict) or set(manifest) != _TOP_KEYS:
        raise SetInvalid(SET_INVALID, "manifest shape")
    if manifest["format"] != FORMAT or manifest["kind"] != KIND:
        raise SetInvalid(SET_INVALID, "manifest format")
    if not isinstance(manifest["label"], str) or not _LABEL_RE.fullmatch(manifest["label"]):
        raise SetInvalid(SET_INVALID, "label")
    if not isinstance(manifest["created_at"], str):
        raise SetInvalid(SET_INVALID, "created_at")
    try:
        custody_common.require_utc_text(manifest["created_at"])
    except ValueError:
        raise SetInvalid(SET_INVALID, "created_at") from None
    rows = manifest["objects"]
    if not isinstance(rows, list) or len(rows) > MAX_OBJECTS:
        raise SetInvalid(SET_INVALID, "objects")
    previous = 0
    sizes: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            raise SetInvalid(SET_INVALID, "row shape")
        row_id, size, sha = row["id"], row["size"], row["sha256"]
        if isinstance(row_id, bool) or not isinstance(row_id, int) or row_id <= previous:
            raise SetInvalid(SET_INVALID, "row ids")
        previous = row_id
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= BUSINESS_DOCUMENT_MAX_BYTES:
            raise SetInvalid(SET_INVALID, "row size")
        if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
            raise SetInvalid(SET_INVALID, "row digest")
        if sizes.setdefault(sha, size) != size:
            raise SetInvalid(SET_INVALID, "one digest, two sizes")
        if row["mime"] not in BUSINESS_DOCUMENT_MIME_TYPES or row["lifecycle"] not in LIFECYCLE_STATES:
            raise SetInvalid(SET_INVALID, "row class")
        try:
            check_locator(row["bucket"], row["key"])
        except (CanonicalStoreError, TypeError):
            raise SetInvalid(SET_INVALID, "row locator") from None
    counts = manifest["counts"]
    expected = {
        "objects": len(rows),
        "contents": len(sizes),
        "bytes": sum(sizes.values()),
        "active": sum(1 for row in rows if row["lifecycle"] == "active"),
        "retired": sum(1 for row in rows if row["lifecycle"] != "active"),
    }
    if not isinstance(counts, dict) or set(counts) != _COUNT_KEYS or counts != expected:
        raise SetInvalid(SET_INVALID, "counts")
    if manifest["objects_digest"] != objects_digest(rows):
        raise SetInvalid(SET_INVALID, "objects digest")
    if manifest["seal"] != _seal(manifest):
        raise SetInvalid(SET_INVALID, "seal")
    return manifest


def _file_sha256(path: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def verify_set(set_dir: str, *, conn=None) -> VerifyReport:
    """Offline proof of a set; with ``conn``, also its comparison with the database rows."""
    report = VerifyReport()
    if not os.path.isdir(set_dir):
        report.result_code = SET_NOT_FOUND
        return report
    try:
        manifest = _read_manifest(set_dir)
    except SetInvalid as exc:
        report.result_code = exc.code
        return report
    report.sealed = True
    rows = manifest["objects"]
    report.objects = len(rows)
    sizes = {row["sha256"]: row["size"] for row in rows}
    report.contents = len(sizes)
    report.bytes = sum(sizes.values())
    report.objects_digest = manifest["objects_digest"]
    objects_root = os.path.join(set_dir, OBJECTS_DIR)
    root_is_plain = _is_plain_dir(objects_root)
    plain_shards: dict[str, bool] = {}
    for sha, size in sizes.items():
        shard = sha[:2]
        if shard not in plain_shards:
            plain_shards[shard] = root_is_plain and _is_plain_dir(os.path.join(objects_root, shard))
        if not plain_shards[shard]:  # never read through a link or junction
            report.missing += 1
            continue
        path = os.path.join(set_dir, _object_relpath(sha))
        try:
            info = os.lstat(path)
        except OSError:
            report.missing += 1
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:  # S_ISREG: never a link
            report.corrupt += 1
            continue
        actual_size, actual = _file_sha256(path)
        if actual_size != size or actual != sha:
            report.corrupt += 1
    report.unexpected = _unexpected_entries(set_dir, set(sizes))
    if report.missing or report.corrupt or report.unexpected:
        report.result_code = SET_INVALID
    if conn is not None:
        report.database = _compare_database(rows, current_rows(conn))
    return report


def _unexpected_entries(set_dir: str, known: set[str]) -> int:
    """Everything in the set that a backup does not write (a link, an empty directory, a stray file)."""
    count = sum(1 for name in os.listdir(set_dir) if name not in (MANIFEST_NAME, OBJECTS_DIR))
    objects = os.path.join(set_dir, OBJECTS_DIR)
    if not os.path.lexists(objects):
        return count
    if not _is_plain_dir(objects):
        return count + 1
    for shard in os.listdir(objects):
        shard_path = os.path.join(objects, shard)
        if not _SHARD_RE.fullmatch(shard) or not _is_plain_dir(shard_path):
            count += 1
            continue
        for name in os.listdir(shard_path):
            if name not in known or name[:2] != shard:
                count += 1
    return count


def _compare_database(set_rows: list[dict], db_rows: list[dict]) -> dict:
    in_set = {row["id"]: row for row in set_rows}
    in_db = {row["id"]: row for row in db_rows}
    missing = sorted(set(in_db) - set(in_set))
    extra = sorted(set(in_set) - set(in_db))
    changed = sorted(i for i in set(in_set) & set(in_db) if in_set[i] != in_db[i])
    return {
        "missing": len(missing), "extra": len(extra), "changed": len(changed),
        "missing_ids": _bounded(missing), "extra_ids": _bounded(extra), "changed_ids": _bounded(changed),
    }


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def _note(report: RestoreReport, name: str, row_id: int) -> None:
    ids = report.ids.setdefault(name, [])
    if len(ids) < LIST_LIMIT:
        ids.append(row_id)


def restore(set_dir: str, store: CanonicalObjectStore, *, bucket: str | None = None) -> RestoreReport:
    """Put the set's objects into ``bucket`` (default: each object's recorded bucket).

    Never overwrites and never deletes.  An existing object is adopted only when
    its size, SHA-256 and MIME type match; everything uploaded is read back.
    """
    report = RestoreReport()
    verified = verify_set(set_dir)
    if not (verified.ok and verified.sealed):
        report.result_code = verified.result_code if verified.result_code != RESULT_OK else SET_INVALID
        return report
    manifest = _read_manifest(set_dir)
    rows = manifest["objects"]
    report.objects = len(rows)
    if bucket is not None:
        try:
            check_locator(bucket, "x")
        except CanonicalStoreError:
            report.result_code = TARGET_BUCKET_INVALID
            return report
    uploaded: list[dict] = []  # rows this run wrote: the read-back proves the bytes landed
    invalid = False
    for row in rows:
        target = bucket or row["bucket"]
        try:
            content = _read_set_content(set_dir, row)
            outcome = _place(store, target, row, content)
        except SetInvalid:
            # A file changed after the set was verified: place nothing more, still read back what was.
            invalid = True
            report.stopped = True
            break
        except CanonicalStoreError as exc:
            report.failed += 1
            report.stopped = True
            _note(report, exc.code, row["id"])
            break
        if outcome == "conflict":
            report.conflicts += 1
            _note(report, TARGET_CONFLICT, row["id"])
        elif outcome == "adopted":
            report.adopted += 1
        else:
            report.restored += 1
            uploaded.append({**row, "target": target})
    for row in uploaded:
        try:
            read_verified(store, row["target"], row["key"], expected_size=row["size"],
                          expected_sha256=row["sha256"], max_bytes=BUSINESS_DOCUMENT_MAX_BYTES)
        except CanonicalStoreError:
            report.readback_failed += 1
            _note(report, READBACK_MISMATCH, row["id"])
    if invalid:
        report.result_code = SET_INVALID
    elif report.conflicts:
        report.result_code = TARGET_CONFLICT
    elif report.readback_failed:
        report.result_code = READBACK_MISMATCH
    elif report.failed:
        report.result_code = STORE_FAILURE
    return report


def _read_set_content(set_dir: str, row: dict) -> bytes:
    path = os.path.join(set_dir, _object_relpath(row["sha256"]))
    try:
        with open(path, "rb") as handle:
            content = handle.read(BUSINESS_DOCUMENT_MAX_BYTES + 1)
    except OSError:
        raise SetInvalid(SET_INVALID, "object file") from None
    if len(content) != row["size"] or _sha256(content) != row["sha256"]:
        raise SetInvalid(SET_INVALID, "object changed since verification")
    return content


def _place(store: CanonicalObjectStore, target: str, row: dict, content: bytes) -> str:
    """``restored`` | ``adopted`` | ``conflict`` for one object (provider errors propagate)."""
    if store.object_exists(target, row["key"]):
        return _adopt(store, target, row)
    try:
        store.upload(target, row["key"], content, mime_type=row["mime"])
    except CanonicalStoreError as exc:
        if exc.code != STORAGE_ALREADY_EXISTS:
            raise
        return _adopt(store, target, row)  # lost a race to a writer of the same key
    return "restored"


def _adopt(store: CanonicalObjectStore, target: str, row: dict) -> str:
    try:
        verify_existing(store, target, row["key"], expected_size=row["size"], expected_sha256=row["sha256"],
                        expected_mime_type=row["mime"], max_bytes=BUSINESS_DOCUMENT_MAX_BYTES)
    except CanonicalStoreError as exc:
        if exc.code in (STORAGE_INTEGRITY_MISMATCH, STORAGE_OBJECT_TOO_LARGE):
            return "conflict"
        raise
    return "adopted"


__all__ = [
    "BackupReport",
    "RestoreReport",
    "SetInvalid",
    "VerifyReport",
    "backup",
    "current_rows",
    "objects_digest",
    "restore",
    "verify_set",
]
