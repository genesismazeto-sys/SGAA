# coding: utf-8
"""The hosted backup owner (MP-3 A19/A20): a verified database snapshot and, when due, a sealed
object set — sent to the connected cloud drives, recorded in the posture, pruned by the policy.

WHY THIS EXISTS
    "Gerar backup agora" (MP-3 A19) and the scheduled pass (MP-3 A20) are the same capability:
    copy the live PostgreSQL database into the product's snapshot format (proven table by table),
    send it together with the readable registers to every connected drive, keep the newest
    generations the policy sets, and publish a self-hashed receipt the Banco de dados page reads.
    A20 adds the sealed object set (every ``storage_objects`` row's bytes, deduplicated and
    verified) and the policy-driven wake-up: ``run_backup_pass`` no-ops unless the database cadence
    or the object cadence is due, so any scheduler can wake it as often as it likes.

WHAT THIS MODULE OWNS
    ``send_snapshot`` / ``prune_owned`` (moved here from the view, behaviour-preserving),
    ``run_backup_pass`` (the scheduled decision + run), ``cloud_drive_folder_setting`` (the read of
    the chosen destination folder), and the advisory lock shared with the manual route.

WHAT IT NEVER DOES
    It never deletes a file the receipts do not name, never publishes a receipt for a run whose
    snapshot or set did not verify, never reads or writes a secret (the platform's own connection,
    storage key and drive tokens only), and never touches the cutover ledger or a business table.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import tempfile
import time

from app import cloud_connections as _cloud_connections
from app import cloud_drives as _cd
from app.backup import pg_posture
from app.backup import pg_snapshot
from app.backup.orchestrator import _save_drive_config
from app.db import ensure_cloud_backup_schema, get_db_connection

logger = logging.getLogger("main")

#: The folder every hosted backup lands in when the administrator chose none ("Selecionar pasta").
PG_SNAPSHOT_DEFAULT_FOLDER = "SGAA - Backups"
#: The sealed object set archive: exactly the names the background builder writes (``object_sets``).
OBJECTS_ARCHIVE_PREFIX = "sgaa-pg-objetos-"
OBJECTS_ARCHIVE_NAME = re.compile(r"sgaa-pg-objetos-\d{8}T\d{6}Z-[0-9a-f]{12}-[0-9a-f]{16}\.zip")
#: One advisory lock per database: the scheduled pass and the manual route never run together.
BACKUP_LOCK_KEY = 723_904_117_455

RESULT_OK = "OK"
RESULT_NOT_DUE = "NOT_DUE"
RESULT_NOT_POSTGRES = "NOT_POSTGRES"
RESULT_SKIPPED_BUSY = "SKIPPED_BUSY"
RESULT_POLICY_INVALID = "POLICY_INVALID"
RESULT_DATABASE_UNREADABLE = "DATABASE_UNREADABLE"
RESULT_NO_DRIVE = "NO_DRIVE"
RESULT_SNAPSHOT_FAILED = "SNAPSHOT_FAILED"
RESULT_SNAPSHOT_NOT_RECORDED = "SNAPSHOT_NOT_RECORDED"
RESULT_OBJECTS_NOT_DELIVERED = "OBJECTS_NOT_DELIVERED"
RESULT_UPLOAD_FAILED = "UPLOAD_FAILED"

_PROVIDERS = ("google", "onedrive")


def _label(provider: str) -> str:
    return "Google Drive" if provider == "google" else "OneDrive"


# ---------------------------------------------------------------------------
# the collaborators (single owners)
# ---------------------------------------------------------------------------


def active_cloud_account(conn, provider: str):
    """The connected account of ``provider`` on this installation, else ``None``."""
    return _cloud_connections.get_active_cloud_account(conn, provider)


def cloud_drive_folder_setting(conn, provider: str) -> dict[str, str]:
    """The chosen destination folder of ``provider`` (empty fields when none was chosen).

    Callers validate the provider on their side; this read serves the snapshot, the object-set
    archive and the view's folder modal.
    """
    ensure_cloud_backup_schema(conn)
    row = conn.execute(
        """
        SELECT provider, folder_id, folder_name, folder_path_label, drive_id, updated_at
          FROM cloud_drive_settings
         WHERE provider = ?
         LIMIT 1
        """,
        (provider,),
    ).fetchone()
    if not row:
        return {
            "provider": provider, "folder_id": "", "folder_name": "",
            "folder_path_label": "", "drive_id": "", "updated_at": "",
        }
    return {
        "provider": str(row["provider"] or provider),
        "folder_id": str(row["folder_id"] or ""),
        "folder_name": str(row["folder_name"] or ""),
        "folder_path_label": str(row["folder_path_label"] or ""),
        "drive_id": str(row["drive_id"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


# ---------------------------------------------------------------------------
# the advisory lock (scheduled pass and manual route share it)
# ---------------------------------------------------------------------------


def backup_lock(conn) -> bool:
    """Take the database's backup lock; ``True`` when taken (always on a non-PostgreSQL backend)."""
    raw = getattr(conn, "raw_connection", None)
    if raw is None:
        return True
    row = raw.execute("SELECT pg_try_advisory_lock(%s)", (BACKUP_LOCK_KEY,)).fetchone()
    return bool(row and row[0])


def backup_unlock(conn) -> None:
    raw = getattr(conn, "raw_connection", None)
    if raw is None:
        return
    try:
        raw.execute("SELECT pg_advisory_unlock(%s)", (BACKUP_LOCK_KEY,))
    except Exception:  # a connection already gone releases the lock with its session
        pass


# ---------------------------------------------------------------------------
# the delivery (snapshot + registers [+ object set] -> every connected drive -> receipt -> prune)
# ---------------------------------------------------------------------------


def _deliver(*, prune: bool, with_objects: bool, store=None, build_objects=None) -> dict:
    """One delivery attempt; see ``send_snapshot`` for the manual contract.

    Returns a value-free dict: ``targets`` (connected providers), ``sent`` (``None`` when the
    snapshot could not be made), ``failed`` / ``registers_failed`` / ``objects_failed`` labels,
    ``manifest`` (the snapshot's SHA-256 once it reached a drive AND its receipt was recorded),
    ``set_error`` (a fixed code when the object set was due but could not be built), and the
    object-set receipt fields.  ``build_objects`` is the background builder (``app.backup.object_sets``);
    without it a due object set refuses loudly instead of shipping nothing silently.
    """
    conn = get_db_connection()
    raw = getattr(conn, "raw_connection", None)
    result = {
        "targets": [], "sent": None, "failed": [], "registers_failed": [], "objects_failed": [],
        "manifest": None, "set_error": None, "object_set_name": None, "object_set_digest": None,
        "object_manifest_sha256": None, "object_files": {},
    }
    try:
        keep = pg_posture.read_policy(raw, strict=True)["pg_retention_generations"] if raw is not None else None
    except Exception:
        keep = None  # a deletion is never decided by a policy that could not be read
    targets = [provider for provider in _PROVIDERS if active_cloud_account(conn, provider)]
    result["targets"] = targets
    if not targets:
        # nothing to send: not a failed snapshot (the caller distinguishes NO_DRIVE from it)
        result["sent"] = []
        return result
    started = time.monotonic()
    sent, failed, uploaded, exported, drives, registers_failed, folders = [], [], {}, {}, {}, [], {}
    object_files = {}
    with tempfile.TemporaryDirectory(prefix="sgaa-pg-snapshot-") as scratch:
        try:
            snapshot = pg_snapshot.create(scratch)
        except Exception as exc:
            logger.warning("event=pg_snapshot_failed code=%s", getattr(exc, "code", type(exc).__name__))
            return result
        built = {"archive": None, "report": None, "manifest_sha256": None, "set_name": None, "code": None}
        if with_objects:
            if build_objects is None:
                # the scheduled path always injects the builder; anything else fails closed
                logger.warning("event=pg_object_set_failed code=%s", "SET_BUILDER_UNAVAILABLE")
                result["set_error"] = "SET_BUILDER_UNAVAILABLE"
                return result
            built = build_objects(conn, scratch, snapshot, store=store)
            if built["code"] is not None:
                # the set did not verify: nothing is uploaded and no receipt is published (A20 §5)
                logger.warning("event=pg_object_set_failed code=%s", built["code"])
                result["set_error"] = built["code"]
                return result
        for provider in targets:
            prefix = "gdrive" if provider == "google" else "onedrive"
            label = _label(provider)
            chosen = cloud_drive_folder_setting(conn, provider)
            folder_id = str(chosen.get("folder_id") or "").strip() or None
            drive_id = str(chosen.get("drive_id") or "").strip() or None
            try:
                upload = _cloud_connections.upload_backup_zip(
                    conn, provider, zip_path=snapshot["path"], file_name=snapshot["file_name"],
                    folder_name=PG_SNAPSHOT_DEFAULT_FOLDER, folder_id=folder_id, drive_id=drive_id, replace=False,
                )
                if upload.get("file_id"):
                    uploaded[provider] = str(upload["file_id"])
                # the drive the file landed in, as Graph reports it: OneDrive item ids are scoped to it
                landed_drive = str(upload.get("drive_id") or drive_id or "") if provider == "onedrive" else ""
                if landed_drive:
                    drives[provider] = landed_drive
                folders[provider] = (str(upload.get("folder_id") or folder_id or ""), folder_id, landed_drive)
                try:  # the readable registers travel beside the database copy, into the same folder
                    registers = _cloud_connections.upload_backup_zip(
                        conn, provider, zip_path=snapshot["registers_path"],
                        file_name=snapshot["registers_file_name"], folder_name=PG_SNAPSHOT_DEFAULT_FOLDER,
                        folder_id=folder_id, drive_id=drive_id, replace=False,
                    )
                    if registers.get("file_id"):
                        exported[provider] = str(registers["file_id"])
                except Exception as exc:
                    logger.warning("event=pg_registers_upload_failed provider=%s error=%s", provider, type(exc).__name__)
                if provider not in exported:
                    registers_failed.append(label)
                if built["archive"] is not None:
                    try:  # the sealed object set travels with the snapshot it belongs to
                        archived = _cloud_connections.upload_backup_zip(
                            conn, provider, zip_path=built["archive"], file_name=os.path.basename(built["archive"]),
                            folder_name=PG_SNAPSHOT_DEFAULT_FOLDER, folder_id=folder_id, drive_id=drive_id, replace=False,
                        )
                        if archived.get("file_id"):
                            object_files[provider] = str(archived["file_id"])
                    except Exception as exc:
                        logger.warning("event=pg_object_set_upload_failed provider=%s error=%s",
                                       provider, type(exc).__name__)
                    if provider not in object_files:
                        result["objects_failed"].append(label)
            except Exception as exc:
                logger.warning("event=pg_snapshot_upload_failed provider=%s error=%s", provider, type(exc).__name__)
                failed.append(label)
                _save_drive_config(conn, {f"{prefix}_last_upload_error": "Falha no envio do backup do banco."})
                conn.commit()
                continue
            sent.append(provider)
            _save_drive_config(conn, {
                f"{prefix}_last_upload_at": snapshot["generation_at"],
                f"{prefix}_last_upload_error": "" if provider in exported else "Falha no envio dos registros (CSV).",
            })
            conn.commit()
    result.update(sent=sent, failed=failed, registers_failed=registers_failed)
    # A set is only claimed when at least one drive actually received its archive (M1): an upload
    # failure leaves the object layer unclaimed and due, so the next wake retries it (never silent).
    claimed_objects = built["report"] is not None and bool(object_files)
    published = False
    if sent and raw is not None:
        receipt = pg_posture.run_record(
            generation_at=snapshot["generation_at"], manifest_sha256=snapshot["sha256"],
            dump_sha256=snapshot["sha256"], source_identity_sha256=snapshot["source_identity_sha256"],
            object_set_name=built["set_name"] if claimed_objects else None,
            object_set_digest=(built["report"].objects_digest if claimed_objects else None),
            object_manifest_sha256=built["manifest_sha256"] if claimed_objects else None,
            run_seconds=int(time.monotonic() - started), at=snapshot["generation_at"],
            kind=pg_posture.SNAPSHOT_KIND, provenance=pg_posture.HOSTED_PROVENANCE, destinations=tuple(sent),
            files=uploaded, exports=exported, drives=drives,
            object_files=object_files if object_files else None,
        )
        try:
            pg_posture.publish(raw, [receipt])
            published = True
        except Exception as exc:
            logger.warning("event=pg_snapshot_record_failed error=%s", type(exc).__name__)
    if prune and published and keep is not None:
        prune_owned(conn, raw, sent, folders, keep, registers_skip=registers_failed)
    result["manifest"] = snapshot["sha256"] if published else None
    result["object_files"] = dict(object_files)
    if claimed_objects:
        result["object_set_name"] = built["set_name"]
        result["object_set_digest"] = built["report"].objects_digest
        result["object_manifest_sha256"] = built["manifest_sha256"]
    return result


def send_snapshot(*, prune: bool = True):
    """The snapshot sent to the connected drives (manual route contract, MP-3 A19).

    Returns ``(targets, sent, failed, registers_failed, manifest)``: the connected drives, the ones that
    received it (``None`` when the snapshot could not be made), the labels of the ones that failed, the
    labels of the ones that did not receive the registers (CSV), and the snapshot's SHA-256 once it
    reached a drive AND its receipt was recorded (else ``None``).  ``prune=False`` (the safety copy
    before a restore) deletes nothing.
    """
    result = _deliver(prune=prune, with_objects=False)
    return (result["targets"], result["sent"], result["failed"], result["registers_failed"],
            result["manifest"])


def prune_owned(conn, raw, sent, folders, keep, *, registers_skip):
    """Retention in each drive: the newest ``keep`` of SGAA's own files, deleting only files this
    database's receipts name -- never a same-named file of another installation (A19 R3 M4).  On OneDrive
    only in the drive the upload landed in (``folders[provider][2]``) and only items owned in THAT drive;
    an unknown drive deletes nothing (rereview R4).  The sealed object-set archives (A20) are a third
    kind, pruned the same way and only when their ids are in the receipts."""
    try:
        owned = pg_posture.owned_files(raw)
    except Exception as exc:
        logger.warning("event=pg_snapshot_retention_skipped error=%s", type(exc).__name__)
        return  # receipts that cannot be read prove nothing: delete nothing
    for provider in sent:
        label = _label(provider)
        landed, folder_id, drive_id = folders[provider]
        mine = pg_posture.owned_in(owned, provider, drive_id)
        if provider == "onedrive" and not drive_id:
            logger.warning("event=pg_snapshot_retention_skipped provider=onedrive error=DRIVE_UNKNOWN")
            continue
        kinds = [(pg_snapshot.SNAPSHOT_PREFIX, pg_snapshot.SNAPSHOT_NAME)]
        if label not in registers_skip:
            kinds.append((pg_snapshot.REGISTERS_PREFIX, pg_snapshot.REGISTERS_NAME))
        # the sealed object-set archives (A20): a third kind; the ownership filter below keeps the
        # deletion contract -- ids not named by this database's receipts are never candidates
        kinds.append((OBJECTS_ARCHIVE_PREFIX, OBJECTS_ARCHIVE_NAME))
        try:
            token, _account = _cloud_connections.get_authenticated_access_token(conn, provider)
            if provider == "google":
                for prefix_name, pattern in kinds:
                    listed = _cd.google_list_folder_files(token, landed, prefix_name) if landed else []
                    pg_snapshot.prune([f for f in listed if f.get("id") in mine], keep,
                                      lambda file_id: _cd.google_delete_file(token, file_id), pattern=pattern)
            else:
                listed = _cd.onedrive_list_folder_children(token, folder_id=folder_id, drive_id=drive_id,
                                                           folder_path=PG_SNAPSHOT_DEFAULT_FOLDER)
                for _prefix_name, pattern in kinds:
                    pg_snapshot.prune([f for f in listed if f.get("id") in mine], keep,
                                      lambda item_id: _cd.onedrive_delete_item(token, item_id, drive_id=drive_id),
                                      pattern=pattern)
        except Exception as exc:
            logger.warning("event=pg_snapshot_retention_failed provider=%s error=%s", provider, type(exc).__name__)


# ---------------------------------------------------------------------------
# the scheduled pass (MP-3 A20): policy-driven, cadence-agnostic
# ---------------------------------------------------------------------------


def run_backup_pass(*, store=None, build_objects=None) -> dict:
    """One wake of the scheduled backup: decide, then run only what the policy has due.

    The wake interval is not contract; every wake reads the administrator's policy and the receipts
    and no-ops unless due.  ``build_objects`` is the background object-set builder the scheduler
    service injects (``app.backup.object_sets``).  Returns a value-free dict with ``result_code``
    (``OK``, ``NOT_DUE``, ``SKIPPED_BUSY``, ``POLICY_INVALID``, ``DATABASE_UNREADABLE``, ``NO_DRIVE``,
    ``SNAPSHOT_*``, ``SET_*``, ``UPLOAD_FAILED``) and what ran.
    """
    conn = get_db_connection()
    raw = getattr(conn, "raw_connection", None)
    if raw is None:
        return {"result_code": RESULT_NOT_POSTGRES}
    if not backup_lock(conn):
        return {"result_code": RESULT_SKIPPED_BUSY}
    try:
        posture = pg_posture.read(raw)
        if posture.get("state") == "UNREADABLE":
            return {"result_code": RESULT_DATABASE_UNREADABLE}
        policy = posture["policy"]
        if policy.get("invalid"):
            return {"result_code": RESULT_POLICY_INVALID, "invalid": list(policy["invalid"])}
        now = datetime.datetime.now(datetime.timezone.utc)
        cadence_hours = int(posture["cadence_hours"])
        object_hours = int(policy["pg_object_cadence_days"]) * 24
        latest = posture["latest_generation_at"]
        latest_objects = posture["latest_object_set_at"]
        due_database = latest is None or (now - latest) >= datetime.timedelta(hours=cadence_hours)
        due_objects = latest_objects is None or (now - latest_objects) >= datetime.timedelta(hours=object_hours)
        if not due_database and not due_objects:
            return {"result_code": RESULT_NOT_DUE, "database_due": False, "objects_due": False}
        result = _deliver(prune=True, with_objects=due_objects, store=store, build_objects=build_objects)
        action = "SNAPSHOT+OBJECTS" if due_objects else "SNAPSHOT"
        if result["set_error"] is not None:
            return {"result_code": result["set_error"], "database_due": due_database,
                    "objects_due": due_objects, "action": "NONE"}
        if result["sent"] is None:
            return {"result_code": RESULT_SNAPSHOT_FAILED, "action": "NONE"}
        if not result["sent"]:
            return {"result_code": RESULT_NO_DRIVE, "action": "NONE",
                    "database_due": due_database, "objects_due": due_objects}
        report = {
            "result_code": RESULT_OK, "database_due": due_database, "objects_due": due_objects,
            "action": action, "sent": list(result["sent"]), "failed": list(result["failed"]),
            "registers_failed": list(result["registers_failed"]), "objects_failed": list(result["objects_failed"]),
        }
        if result["manifest"] is None:
            return {"result_code": RESULT_SNAPSHOT_NOT_RECORDED, "action": action,
                    "sent": report["sent"], "failed": report["failed"]}
        if due_objects and not result["object_files"]:
            # the sealed set reached no drive: the database copy stays recorded (its own layer),
            # the object layer is NOT claimed and stays due for the next wake
            return {"result_code": RESULT_OBJECTS_NOT_DELIVERED, "action": "SNAPSHOT",
                    "database_due": due_database, "objects_due": due_objects,
                    "sent": report["sent"], "failed": report["failed"],
                    "objects_failed": report["objects_failed"]}
        return report
    finally:
        backup_unlock(conn)


__all__ = [
    "BACKUP_LOCK_KEY", "OBJECTS_ARCHIVE_NAME", "OBJECTS_ARCHIVE_PREFIX", "PG_SNAPSHOT_DEFAULT_FOLDER",
    "RESULT_DATABASE_UNREADABLE", "RESULT_NOT_DUE", "RESULT_NOT_POSTGRES", "RESULT_NO_DRIVE", "RESULT_OBJECTS_NOT_DELIVERED",
    "RESULT_OK", "RESULT_POLICY_INVALID", "RESULT_SKIPPED_BUSY", "RESULT_SNAPSHOT_FAILED", "RESULT_SNAPSHOT_NOT_RECORDED",
    "RESULT_UPLOAD_FAILED", "active_cloud_account", "backup_lock", "backup_unlock", "cloud_drive_folder_setting",
    "prune_owned", "run_backup_pass", "send_snapshot",
]
