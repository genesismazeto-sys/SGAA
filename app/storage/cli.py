"""Operator command line for canonical document storage: ``python -m app.storage.cli``.

Subcommands (each prints ONE value-free JSON report on stdout; logs go to
stderr; no secret, URL, locator, file name or person data is ever printed):

    mirror-run       run bounded Drive mirror passes (``app.storage.drive_mirror``)
    mirror-requeue   operator recovery: ``reconciliation_required`` -> ``pending``
    census           custody-class counts (``app.storage.storage_audit``)
    verify           the convergence cross-check of database references,
                     canonical objects, the bucket and (``--drive``) Drive mirrors
    converge         legacy -> canonical convergence (``app.storage.legacy_convergence``);
                     a dry run unless ``--apply``
    backup-objects   write a sealed, self-checking set of every canonical object to a
                     NEW directory (``app.storage.object_backup``); read-only on storage
    verify-backup    prove a set offline (seal, counts, every file); with ``--database``
                     also compare it with the current object rows
    restore-objects  put a set's objects into a bucket without overwriting or deleting;
                     adopts matching objects, reports conflicts, reads everything back

The commands run under an application context of ``create_app()`` -- the
``python -m app.backup.sync`` precedent -- and never under a request.  This
module parses, calls the owner and reports; the logic lives in the owners.
``verify-backup`` (offline) and ``restore-objects`` need neither the database nor
the application: they start nothing and read only the set and the storage
environment (``SUPABASE_URL``, ``SUPABASE_SECRET_KEY``, ``SGAA_STORAGE_BUCKET``).

Exit codes:
    0  done (including "nothing to do")
    1  runtime failure after the application started
    2  usage error or application startup failure
    3  not runnable: the canonical store or the Drive connection is unavailable
    4  verify: a check failed (not converged, unclean bucket or unverified mirrors);
       converge: some row did not converge (its outcome class says why);
       backup-objects: an object was unreadable, the space or object bound was
       exceeded, or the finished set could not be promoted (no set was promoted
       except a failed promotion, whose directory is named in the report);
       verify-backup: the set is invalid or differs from the database;
       restore-objects: a conflict, a failure or a read-back mismatch
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

EXIT_OK = 0
EXIT_RUNTIME_FAILURE = 1
EXIT_USAGE = 2
EXIT_NOT_RUNNABLE = 3
EXIT_NOT_CONVERGED = 4

logger = logging.getLogger(__name__)


def _bounded_int(low: int, high: int):
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError("expected an integer") from None
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"expected {low}..{high}")
        return value

    return parse


def _parser() -> argparse.ArgumentParser:
    from app.storage import drive_mirror
    from app.storage import mirror_outbox

    parser = argparse.ArgumentParser(prog="python -m app.storage.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("mirror-run", help="run bounded Drive mirror passes")
    run.add_argument("--limit", type=_bounded_int(1, mirror_outbox.MAX_CLAIM_BATCH),
                     default=drive_mirror.DEFAULT_BATCH, help="objects claimed per pass")
    run.add_argument("--passes", type=_bounded_int(1, 1000), default=1,
                     help="maximum passes; stops early when a pass claims nothing")
    run.add_argument("--lease-seconds", type=_bounded_int(2 * drive_mirror.LEASE_SAFETY_SECONDS,
                                                          mirror_outbox.MAX_LEASE_SECONDS),
                     default=mirror_outbox.DEFAULT_LEASE_SECONDS)

    requeue = commands.add_parser("mirror-requeue", help="requeue reconciliation_required objects")
    requeue.add_argument("--code", default=None, help="only objects whose last error has this code")
    requeue.add_argument("--limit", type=_bounded_int(1, mirror_outbox.MAX_REQUEUE_BATCH), default=100)

    commands.add_parser("census", help="value-free custody-class counts")

    verify = commands.add_parser("verify", help="the convergence cross-check")
    verify.add_argument("--deep", action="store_true", help="hash every canonical object's bytes")
    verify.add_argument("--no-listing", action="store_true", help="skip the bucket listing")
    verify.add_argument("--drive", action="store_true", help="verify synced Drive mirrors (needs Drive)")
    verify.add_argument("--requeue-missing-mirrors", action="store_true",
                        help="with --drive: send missing / divergent mirrors back to pending")
    verify.add_argument("--show-ids", action="store_true", help="list integer ids per discrepancy class")

    from app.storage import legacy_convergence

    converge = commands.add_parser("converge", help="legacy -> canonical convergence (dry run by default)")
    converge.add_argument("--apply", action="store_true", help="write: upload, verify and link")
    converge.add_argument("--limit", type=_bounded_int(1, legacy_convergence.MAX_CONVERGE_BATCH), default=100,
                          help="rows per table in this run")
    converge.add_argument("--table", choices=legacy_convergence.TABLES, default=None)
    converge.add_argument("--after-id", type=_bounded_int(0, 2**62), default=0,
                          help="with --table: start after this row id (a previous report's last_row_id)")
    backup_objects = commands.add_parser(
        "backup-objects", help="write a sealed set of every canonical object to a new directory"
    )
    backup_objects.add_argument("--destination", required=True,
                                help="a directory that does not exist yet, outside the repository")
    backup_objects.add_argument("--label", default="", help="operator label ([A-Za-z0-9._-], at most 64)")

    verify_backup = commands.add_parser("verify-backup", help="prove an object backup set")
    verify_backup.add_argument("--set", dest="set_dir", required=True, help="the set directory")
    verify_backup.add_argument("--database", action="store_true",
                               help="also compare the set with the database's object rows")

    restore_objects = commands.add_parser(
        "restore-objects", help="restore a set into a bucket (never overwrites or deletes)"
    )
    restore_objects.add_argument("--set", dest="set_dir", required=True, help="the set directory")
    restore_objects.add_argument("--bucket", default=None,
                                 help="target bucket (default: each object's recorded bucket)")
    return parser


def _mirror_run(conn, args) -> tuple[int, dict]:
    from app.storage import drive_mirror

    passes = []
    for _ in range(args.passes):
        result = drive_mirror.run_mirror_pass(conn, limit=args.limit, lease_seconds=args.lease_seconds)
        passes.append(result.as_dict())
        if result.result_code != drive_mirror.RESULT_OK:
            return EXIT_NOT_RUNNABLE, {"passes": passes}
        if result.claimed == 0:
            break
    return EXIT_OK, {"passes": passes}


def _mirror_requeue(conn, args) -> tuple[int, dict]:
    from app.db import write_transaction
    from app.storage import custody_common
    from app.storage import mirror_outbox

    if args.code is not None and custody_common.sanitize_error_code(args.code) != args.code:
        raise _UsageError("--code must be an error code ([A-Z0-9_])")
    with write_transaction(conn):
        count = mirror_outbox.requeue_for_mirror(
            conn, now=custody_common.utc_now_text(), limit=args.limit, error_code=args.code
        )
    return EXIT_OK, {"requeued": count}


def _census(conn, args) -> tuple[int, dict]:
    from app.storage import storage_audit

    return EXIT_OK, storage_audit.census(conn)


def _verify(conn, args) -> tuple[int, dict]:
    from app.storage import drive_mirror
    from app.storage import request_documents
    from app.storage import storage_audit
    from app.storage.object_store import CanonicalStoreError

    if args.requeue_missing_mirrors and not args.drive:
        raise _UsageError("--requeue-missing-mirrors needs --drive")
    try:
        store = request_documents.canonical_store()
    except CanonicalStoreError as exc:
        return EXIT_NOT_RUNNABLE, {"result_code": exc.code}
    # The configured bucket is listed even when the database names none.
    buckets = (store.bucket,) if getattr(store, "bucket", None) else ()
    drive = None
    if args.drive:
        try:
            drive = drive_mirror.active_drive(conn)
        except drive_mirror.DriveUnavailable as exc:
            return EXIT_NOT_RUNNABLE, {"result_code": exc.code}
    report = storage_audit.cross_check(
        conn, store=store, deep=args.deep, listing=not args.no_listing, buckets=buckets, drive=drive,
        requeue_missing_mirrors=args.requeue_missing_mirrors, show_ids=args.show_ids,
    )
    verdict = report["verdict"]
    clean = verdict["converged"] and verdict["bucket_clean"] is not False
    if args.drive:
        clean = clean and verdict["mirrors_verified"] is True and verdict["mirror_complete"]
    return (EXIT_OK if clean else EXIT_NOT_CONVERGED), report


def _converge(conn, args) -> tuple[int, dict]:
    from flask import current_app

    from app.comprovantes import request_document_roots
    from app.storage import drive_mirror
    from app.storage import legacy_convergence
    from app.storage import request_documents
    from app.storage.object_store import CanonicalStoreError
    from app.storage.supabase_store import configured_bucket

    if args.after_id and not args.table:
        raise _UsageError("--after-id needs --table")
    store = bucket = None
    if args.apply:
        try:
            store = request_documents.canonical_store()
            bucket = getattr(store, "bucket", None) or configured_bucket()
        except CanonicalStoreError as exc:
            return EXIT_NOT_RUNNABLE, {"result_code": exc.code}
    try:
        drive = drive_mirror.active_drive(conn)
    except drive_mirror.DriveUnavailable:
        drive = None  # Google rows report DRIVE_UNAVAILABLE; local rows still converge
    roots = {
        "requisicao_arquivos": request_document_roots(current_app.config),
        "admin_arquivos": (current_app.config.get("UPLOAD_FOLDER"),),
    }
    report = legacy_convergence.converge(
        conn, apply=args.apply, limit=args.limit,
        tables=(args.table,) if args.table else legacy_convergence.TABLES,
        store=store, bucket=bucket, drive=drive, roots=roots, after_id=args.after_id,
    )
    return (EXIT_OK if report.clean else EXIT_NOT_CONVERGED), report.as_dict()


def _store():
    """The canonical store: the injected one under an application, else the environment's."""
    from flask import has_app_context

    from app.storage import request_documents
    from app.storage.supabase_store import SupabaseObjectStore

    if has_app_context():
        return request_documents.canonical_store()
    return SupabaseObjectStore.from_environment()


def _backup_objects(conn, args) -> tuple[int, dict]:
    from app.storage import object_backup
    from app.storage.object_store import CanonicalStoreError

    try:
        store = _store()
    except CanonicalStoreError as exc:
        return EXIT_NOT_RUNNABLE, {"result_code": exc.code}
    try:
        report = object_backup.backup(conn, store, args.destination, label=args.label)
    except object_backup.SetInvalid as exc:
        raise _UsageError(exc.code) from None
    return (EXIT_OK if report.ok else EXIT_NOT_CONVERGED), report.as_dict()


def _verify_backup(conn, args) -> tuple[int, dict]:
    from app.storage import object_backup

    report = object_backup.verify_set(args.set_dir, conn=conn if args.database else None)
    return (EXIT_OK if report.ok else EXIT_NOT_CONVERGED), report.as_dict()


def _restore_objects(conn, args) -> tuple[int, dict]:
    from app.storage import object_backup
    from app.storage.object_store import CanonicalStoreError

    try:
        store = _store()
    except CanonicalStoreError as exc:
        return EXIT_NOT_RUNNABLE, {"result_code": exc.code}
    report = object_backup.restore(args.set_dir, store, bucket=args.bucket)
    return (EXIT_OK if report.ok else EXIT_NOT_CONVERGED), report.as_dict()


#: Commands that need neither the application nor a database connection (unless ``--database``).
_OFFLINE = {
    "verify-backup": lambda args: not args.database,
    "restore-objects": lambda args: True,
}

_COMMANDS = {
    "backup-objects": _backup_objects,
    "verify-backup": _verify_backup,
    "restore-objects": _restore_objects,
    "mirror-run": _mirror_run,
    "mirror-requeue": _mirror_requeue,
    "census": _census,
    "verify": _verify,
    "converge": _converge,
}


class _UsageError(ValueError):
    pass


def main(argv=None, *, app=None, out=None) -> int:
    """Entry point; ``app`` injects an application (tests), else ``create_app()``."""
    out = out or sys.stdout
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_USAGE
    offline = app is None and _OFFLINE.get(args.command, lambda _args: False)(args)
    if offline:
        # No application, no database: the set and the storage environment only.
        try:
            code, report = _COMMANDS[args.command](None, args)
        except _UsageError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except Exception as exc:
            logger.error("storage command %s failed (%s)", args.command, type(exc).__name__)
            return EXIT_RUNTIME_FAILURE
        json.dump({"command": args.command, **report}, out, sort_keys=True)
        out.write("\n")
        return code
    if app is None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        try:
            from app import create_app

            app = create_app()
        except Exception as exc:
            print(f"error: application startup failed ({type(exc).__name__})", file=sys.stderr)
            return EXIT_USAGE
    from app.db import close_db_connection, get_db_connection

    with app.app_context():
        try:
            code, report = _COMMANDS[args.command](get_db_connection(), args)
        except _UsageError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except Exception as exc:
            logger.error("storage command %s failed (%s)", args.command, type(exc).__name__)
            return EXIT_RUNTIME_FAILURE
        finally:
            close_db_connection(None)
    json.dump({"command": args.command, **report}, out, sort_keys=True)
    out.write("\n")
    return code


__all__ = ["EXIT_NOT_CONVERGED", "EXIT_NOT_RUNNABLE", "EXIT_OK", "EXIT_RUNTIME_FAILURE", "EXIT_USAGE", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
