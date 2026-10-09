"""Operator command line for canonical document storage: ``python -m app.storage.cli``.

Subcommands (each prints ONE value-free JSON report on stdout; logs go to
stderr; no secret, URL, locator, file name or person data is ever printed):

    mirror-run       run bounded Drive mirror passes (``app.storage.drive_mirror``)
    mirror-requeue   operator recovery: ``reconciliation_required`` -> ``pending``

The commands run under an application context of ``create_app()`` -- the
``python -m app.backup.sync`` precedent -- and never under a request.  This
module parses, calls the owner and reports; the logic lives in the owners.

Exit codes:
    0  done (including "nothing to do")
    1  runtime failure after the application started
    2  usage error or application startup failure
    3  not runnable: the canonical store or the Drive connection is unavailable
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


_COMMANDS = {
    "mirror-run": _mirror_run,
    "mirror-requeue": _mirror_requeue,
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


__all__ = ["EXIT_NOT_RUNNABLE", "EXIT_OK", "EXIT_RUNTIME_FAILURE", "EXIT_USAGE", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
