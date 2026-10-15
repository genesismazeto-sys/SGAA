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
import secrets
import tempfile
import time

from app import cloud_connections as _cloud_connections
from app import cloud_drives as _cd
from app.backup import pg_posture
from app.backup.orchestrator import _save_drive_config
from app.db import ensure_cloud_backup_schema, get_db_connection

logger = logging.getLogger("main")

#: The folder every hosted backup lands in when the administrator chose none ("Selecionar pasta").
PG_SNAPSHOT_DEFAULT_FOLDER = "SGAA - Backups"
#: The sealed object set archive: exactly the names the background builder writes (``object_sets``).
OBJECTS_ARCHIVE_PREFIX = "sgaa-pg-objetos-"
OBJECTS_ARCHIVE_NAME = re.compile(r"sgaa-pg-objetos-\d{8}T\d{6}Z-[0-9a-f]{12}-[0-9a-f]{16}\.zip")
#: One lock row per database, with a lease (M2): the production runtime uses the transaction
#: pooler, which keeps no session state -- a session-level advisory lock is not valid there (a
#: later statement may run on another backend).  The row is taken and released atomically in short
#: transactions; an expired lease is stolen by the next attempt, so a killed run can never leave a
#: persistent false-busy state.
LOCK_LEASE_SECONDS = 10 * 60
LOCK_HOLDER_LOCAL = "LOCAL"  # a non-PostgreSQL backend takes no lock (SQLite has its own cycle lock)
LOCK_DDL = (
    *pg_posture.SCHEMA_DDL,
    "CREATE TABLE IF NOT EXISTS sgaa_ops.backup_lock ("
    " lock_key smallint PRIMARY KEY, holder text NOT NULL,"
    " acquired_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL)",
    "REVOKE ALL ON sgaa_ops.backup_lock FROM PUBLIC",
)
LOCK_ACQUIRE_SQL = (
    "INSERT INTO sgaa_ops.backup_lock (lock_key, holder, expires_at)"
    " VALUES (1, %s, now() + make_interval(secs => %s))"
    " ON CONFLICT (lock_key) DO UPDATE SET holder = excluded.holder, acquired_at = now(),"
    " expires_at = excluded.expires_at"
    " WHERE sgaa_ops.backup_lock.expires_at <= now()"
    " RETURNING holder"
)
LOCK_RELEASE_SQL = "DELETE FROM sgaa_ops.backup_lock WHERE lock_key = 1 AND holder = %s"

#: M4 (deadline scheduling): the pass runs when the deadline would otherwise fall before the NEXT
#: expected wake.  The interval is the just-elapsed time between wakes (a static window cannot serve
#: both a daily cron and a sub-daily trigger: a generation whose phase sits later than the wake -- a
#: manual backup at 07:00 vs a 04:47 cron -- made the next wake skip and pushed the following one
#: ~46 h out).  Unknown: the platform's documented daily floor.
DEFAULT_WAKE_SECONDS = 24 * 60 * 60
#: Under a minute the elapsed time is a duplicate delivery, not an interval; the same minute guards
#: the decision so a duplicated wake never re-runs a fresh generation.
WAKE_MIN_SECONDS = 60
WAKE_MAX_SECONDS = 7 * 24 * 60 * 60
SCHEDULE_DDL = (
    *pg_posture.SCHEMA_DDL,
    "CREATE TABLE IF NOT EXISTS sgaa_ops.backup_schedule ("
    " schedule_key smallint PRIMARY KEY, last_wake_at timestamptz NOT NULL,"
    " last_interval_seconds integer NOT NULL)",
    "REVOKE ALL ON sgaa_ops.backup_schedule FROM PUBLIC",
)
SCHEDULE_SELECT_SQL = (
    "SELECT last_wake_at, last_interval_seconds FROM sgaa_ops.backup_schedule WHERE schedule_key = 1"
)
SCHEDULE_INSERT_SQL = "INSERT INTO sgaa_ops.backup_schedule (schedule_key, last_wake_at, last_interval_seconds)" \
                      " VALUES (1, %s, %s)"
SCHEDULE_UPDATE_SQL = "UPDATE sgaa_ops.backup_schedule SET last_wake_at = %s, last_interval_seconds = %s" \
                      " WHERE schedule_key = 1"

RESULT_OK = "OK"
RESULT_NOT_DUE = "NOT_DUE"
RESULT_NOT_POSTGRES = "NOT_POSTGRES"
RESULT_SKIPPED_BUSY = "SKIPPED_BUSY"
RESULT_POLICY_INVALID = "POLICY_INVALID"
RESULT_POLICY_UNREADABLE = "POLICY_UNREADABLE"
RESULT_DATABASE_UNREADABLE = "DATABASE_UNREADABLE"
RESULT_NO_DRIVE = "NO_DRIVE"
RESULT_SNAPSHOT_FAILED = "SNAPSHOT_FAILED"
RESULT_SNAPSHOT_NOT_RECORDED = "SNAPSHOT_NOT_RECORDED"
RESULT_DELIVERY_INCOMPLETE = "DELIVERY_INCOMPLETE"
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
# the backup lock (scheduled pass, manual button and restore share it)
# ---------------------------------------------------------------------------


def backup_lock(conn):
    """Take the database's backup lock; returns the holder token, or ``None`` when another run
    holds an unexpired lease.  Non-PostgreSQL backends take no lock (the SQLite path has its own
    cycle lock) and return ``LOCK_HOLDER_LOCAL``.

    The acquire is committed on its own before it returns: on the request paths the connection may
    already be inside an ambient transaction (the auth hooks read the database first), and a lock
    taken there would live in a savepoint -- invisible to every other backend while the protected
    operation runs (M2, genuine transaction boundaries).
    """
    raw = getattr(conn, "raw_connection", None)
    if raw is None:
        return LOCK_HOLDER_LOCAL
    holder = secrets.token_hex(16)
    raw.commit()  # end any ambient transaction: the lease must be visible to every other backend
    pg_posture.run_ddl(raw, LOCK_DDL)
    with raw.transaction():
        row = raw.execute(LOCK_ACQUIRE_SQL, (holder, LOCK_LEASE_SECONDS)).fetchone()
    return str(row[0]) if row else None


def backup_unlock(conn, holder) -> None:
    """Release the lock this run holds; a lease stolen meanwhile is never released by mistake.

    The release is committed on its own, so a finished run never leaves a persistent false-busy row.
    """
    raw = getattr(conn, "raw_connection", None)
    if raw is None or holder in (None, LOCK_HOLDER_LOCAL):
        return
    try:
        raw.commit()  # the release must be visible immediately, not inside an ambient transaction
        with raw.transaction():
            raw.execute(LOCK_RELEASE_SQL, (holder,))
    except Exception:  # a connection already gone leaves the lease to expire; nothing else is lost
        pass


# ---------------------------------------------------------------------------
# the delivery (snapshot + registers [+ object set] -> every connected drive -> receipt -> prune)
# ---------------------------------------------------------------------------


def _deliver(*, prune: bool, with_objects: bool, store=None, build_objects=None) -> dict:
    """One delivery attempt; see ``send_snapshot`` for the manual contract.

    Returns a value-free dict: ``targets`` (connected providers), ``sent`` (``None`` when the
    snapshot could not be made), ``failed`` / ``registers_failed`` / ``objects_failed`` labels,
    ``delivery_complete`` (every connected drive received every required artifact of this wake),
    ``manifest`` (the snapshot's SHA-256 once it reached a drive AND its receipt was recorded),
    ``set_error`` (a fixed code when the object set was due but could not be built), and the
    object-set receipt fields.  ``build_objects`` is the background builder (``app.backup.object_sets``);
    without it a due object set refuses loudly instead of shipping nothing silently.

    The receipt is ALWAYS recorded when at least one drive received the snapshot, carrying the
    truth: its ``complete`` marker says whether every connected drive received the snapshot, the
    registers and (when due) the sealed set (M1).  A partial receipt owns its files (retention
    rotates them, so a failing drive cannot grow the healthy one without bound) but never advances
    the protection clock, the due dates or the page's status -- those read only complete receipts.
    """
    conn = get_db_connection()
    raw = getattr(conn, "raw_connection", None)
    # lazy, like the view's original body: the SQLite runtime must not load the PG schema chain
    from app.backup import pg_snapshot

    result = {
        "targets": [], "sent": None, "failed": [], "registers_failed": [], "objects_failed": [],
        "delivery_complete": False, "manifest": None, "set_error": None,
        "object_set_name": None, "object_set_digest": None, "object_manifest_sha256": None,
        "object_files": {},
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
            try:
                chosen = cloud_drive_folder_setting(conn, provider)
                folder_id = str(chosen.get("folder_id") or "").strip() or None
                drive_id = str(chosen.get("drive_id") or "").strip() or None
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
    # M1: completeness covers every connected drive and every artifact of this wake; the receipt
    # records it, and the read side (page, due-ness) counts only complete receipts.
    requires_objects = built["archive"] is not None
    complete = bool(targets) and len(sent) == len(targets) and all(
        provider in uploaded and provider in exported and (not requires_objects or provider in object_files)
        for provider in targets)
    result["delivery_complete"] = complete
    # a set is claimed (recorded) when it was built and at least one drive received its archive;
    # a partial receipt owns those files for retention but never advances the clocks
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
            object_files=object_files if object_files else None, complete=complete,
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
    kind.  Complete generations and partial runs rotate separately (M1): a failing drive can never
    push the newest complete generation out of its own retention window, and a long failure cannot
    grow the healthy drive without bound (at most ``keep`` of each class per kind)."""
    from app.backup import pg_snapshot

    try:
        owned = pg_posture.owned_files(raw)
        owned_complete = pg_posture.owned_files(raw, complete=True)
    except Exception as exc:
        logger.warning("event=pg_snapshot_retention_skipped error=%s", type(exc).__name__)
        return  # receipts that cannot be read prove nothing: delete nothing
    for provider in sent:
        label = _label(provider)
        landed, folder_id, drive_id = folders[provider]
        mine = pg_posture.owned_in(owned, provider, drive_id)
        complete_ids = pg_posture.owned_in(owned_complete, provider, drive_id)
        partial_ids = mine - complete_ids
        if provider == "onedrive" and not drive_id:
            logger.warning("event=pg_snapshot_retention_skipped provider=onedrive error=DRIVE_UNKNOWN")
            continue
        kinds = [(pg_snapshot.SNAPSHOT_PREFIX, pg_snapshot.SNAPSHOT_NAME)]
        if label not in registers_skip:
            kinds.append((pg_snapshot.REGISTERS_PREFIX, pg_snapshot.REGISTERS_NAME))
        # the sealed object-set archives (A20): a third kind; the ownership filter below keeps the
        # deletion contract -- ids not named by this database's receipts are never candidates
        kinds.append((OBJECTS_ARCHIVE_PREFIX, OBJECTS_ARCHIVE_NAME))

        def _rotate(candidates, delete_one, pattern):
            pg_snapshot.prune([f for f in candidates if f.get("id") in complete_ids], keep, delete_one,
                              pattern=pattern)
            pg_snapshot.prune([f for f in candidates if f.get("id") in partial_ids], keep, delete_one,
                              pattern=pattern)

        try:
            token, _account = _cloud_connections.get_authenticated_access_token(conn, provider)
            if provider == "google":
                for prefix_name, pattern in kinds:
                    listed = _cd.google_list_folder_files(token, landed, prefix_name) if landed else []
                    _rotate(listed, lambda file_id: _cd.google_delete_file(token, file_id), pattern)
            else:
                listed = _cd.onedrive_list_folder_children(token, folder_id=folder_id, drive_id=drive_id,
                                                           folder_path=PG_SNAPSHOT_DEFAULT_FOLDER)
                for _prefix_name, pattern in kinds:
                    _rotate(listed,
                            lambda item_id: _cd.onedrive_delete_item(token, item_id, drive_id=drive_id),
                            pattern)
        except Exception as exc:
            logger.warning("event=pg_snapshot_retention_failed provider=%s error=%s", provider, type(exc).__name__)


# ---------------------------------------------------------------------------
# the scheduled pass (MP-3 A20): policy-driven, cadence-agnostic
# ---------------------------------------------------------------------------


def note_wake(raw, now) -> int:
    """Record this wake and return the interval to the next expected one (M4 deadline scheduling).

    One transaction: the first wake stores the platform's documented daily floor; later wakes learn
    the just-elapsed time between wakes (clamped to [1 min, 7 days]) — a duplicate delivery (under a
    minute) keeps the stored regular interval.  Runs under the backup lock, so the row has a single
    writer.
    """
    pg_posture.run_ddl(raw, SCHEDULE_DDL)
    with raw.transaction():
        row = raw.execute(SCHEDULE_SELECT_SQL).fetchone()
        if row is None:
            interval = DEFAULT_WAKE_SECONDS
            raw.execute(SCHEDULE_INSERT_SQL, (now, interval))
            return interval
        last, stored = row[0], int(row[1])
        elapsed = (now - last).total_seconds()
        interval = min(max(int(elapsed), WAKE_MIN_SECONDS), WAKE_MAX_SECONDS) \
            if elapsed >= WAKE_MIN_SECONDS else stored
        raw.execute(SCHEDULE_UPDATE_SQL, (now, interval))
        return interval


def run_backup_pass(*, store=None, build_objects=None) -> dict:
    """One wake of the scheduled backup: decide, then run only what the policy has due.

    The wake interval is not contract; every wake reads the administrator's policy strictly (M3:
    an unreadable or unverifiable policy refuses the run, never a substituted default) and the
    receipts, records itself and runs on the deadline rule (M4/A4, A6: run when the deadline could
    not be met by the next expected wake, `age >= cadence - interval`, the interval learned from the
    just-elapsed time between wakes; the residual is the waker's spacing spread).  A receipt is only
    published when every connected drive received every required artifact (M1).  ``build_objects``
    is the background object-set builder the scheduler service injects (``app.backup.object_sets``).
    Returns a value-free dict with ``result_code`` (``OK``, ``NOT_DUE``, ``SKIPPED_BUSY``,
    ``POLICY_INVALID``, ``POLICY_UNREADABLE``, ``DATABASE_UNREADABLE``, ``NO_DRIVE``,
    ``DELIVERY_INCOMPLETE``, ``SNAPSHOT_*``, ``SET_*``) and what ran.
    """
    conn = get_db_connection()
    raw = getattr(conn, "raw_connection", None)
    if raw is None:
        return {"result_code": RESULT_NOT_POSTGRES}
    holder = backup_lock(conn)
    if holder is None:
        return {"result_code": RESULT_SKIPPED_BUSY}
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            # M4: record this wake and learn the interval to the next one; the deadline rule needs
            # it to decide.  A failure here refuses the pass (nothing runs on a schedule it cannot
            # reason about).
            interval_seconds = note_wake(raw, now)
        except Exception:
            return {"result_code": RESULT_DATABASE_UNREADABLE}
        posture = pg_posture.read(raw)
        if posture.get("state") == "UNREADABLE":
            return {"result_code": RESULT_DATABASE_UNREADABLE}
        try:
            # M3: the decision reads the policy strictly -- a missing, partial or invalid stored
            # policy raises here instead of silently becoming the defaults.  An empty table is a
            # provably unset policy and its documented defaults are the policy.
            policy = pg_posture.read_policy(raw, strict=True)
        except pg_posture.PolicyError:
            return {"result_code": RESULT_POLICY_INVALID}
        except Exception:
            return {"result_code": RESULT_POLICY_UNREADABLE}
        cadence_hours = int(policy["pg_database_cadence_hours"])
        ceiling = posture.get("ceiling_hours")
        if ceiling is not None and ceiling < cadence_hours:
            cadence_hours = ceiling
        object_hours = int(policy["pg_object_cadence_days"]) * 24
        latest = posture["latest_generation_at"]
        latest_objects = posture["latest_object_set_at"]
        # M4/A6: run when the deadline could not be met by the next expected wake -- the deadline
        # falls at or before the next wake at the just-observed spacing (`age >= cadence - interval`)
        # -- so the edge wake runs and a delayed next wake can never stretch the gap past the cadence
        # by a design guard; the residual is the waker's own spacing spread (estimate vs actual).
        # The one-minute conjunct only suppresses a duplicate delivery of the same wake (a sub-minute
        # age); it never delays a legitimate run.
        age_database = None if latest is None else (now - latest).total_seconds()
        age_objects = None if latest_objects is None else (now - latest_objects).total_seconds()
        due_database = age_database is None or (age_database >= cadence_hours * 3600 - interval_seconds
                                                and age_database >= WAKE_MIN_SECONDS)
        due_objects = age_objects is None or (age_objects >= object_hours * 3600 - interval_seconds
                                              and age_objects >= WAKE_MIN_SECONDS)
        if not due_database and not due_objects:
            return {"result_code": RESULT_NOT_DUE, "database_due": False, "objects_due": False,
                    "interval_seconds": interval_seconds}
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
        if not result["delivery_complete"]:
            # M1: some connected drive is missing a required artifact.  The receipt was recorded with
            # its completeness marker (it owns its files), but the protection clock, the due dates and
            # the page's status read only complete receipts -- so nothing looks protected and the same
            # work stays due for the next wake.
            return {"result_code": RESULT_DELIVERY_INCOMPLETE, "action": "NONE",
                    "database_due": due_database, "objects_due": due_objects,
                    "sent": list(result["sent"]), "failed": list(result["failed"]),
                    "registers_failed": list(result["registers_failed"]),
                    "objects_failed": list(result["objects_failed"])}
        report = {
            "result_code": RESULT_OK, "database_due": due_database, "objects_due": due_objects,
            "action": action, "sent": list(result["sent"]), "failed": list(result["failed"]),
            "registers_failed": list(result["registers_failed"]), "objects_failed": list(result["objects_failed"]),
        }
        if result["manifest"] is None:
            return {"result_code": RESULT_SNAPSHOT_NOT_RECORDED, "action": action,
                    "sent": report["sent"], "failed": report["failed"]}
        return report
    finally:
        backup_unlock(conn, holder)


__all__ = [
    "DEFAULT_WAKE_SECONDS", "LOCK_HOLDER_LOCAL", "LOCK_LEASE_SECONDS", "OBJECTS_ARCHIVE_NAME",
    "OBJECTS_ARCHIVE_PREFIX", "PG_SNAPSHOT_DEFAULT_FOLDER", "RESULT_DATABASE_UNREADABLE",
    "RESULT_DELIVERY_INCOMPLETE", "RESULT_NOT_DUE", "RESULT_NOT_POSTGRES", "RESULT_NO_DRIVE", "RESULT_OK",
    "RESULT_POLICY_INVALID", "RESULT_POLICY_UNREADABLE", "RESULT_SKIPPED_BUSY", "RESULT_SNAPSHOT_FAILED",
    "RESULT_SNAPSHOT_NOT_RECORDED", "RESULT_UPLOAD_FAILED", "SCHEDULE_DDL", "SCHEDULE_INSERT_SQL",
    "SCHEDULE_SELECT_SQL", "SCHEDULE_UPDATE_SQL", "WAKE_MAX_SECONDS", "WAKE_MIN_SECONDS",
    "active_cloud_account", "backup_lock", "backup_unlock", "cloud_drive_folder_setting", "note_wake",
    "prune_owned", "run_backup_pass", "send_snapshot",
]
