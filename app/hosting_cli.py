"""Operator command line for the hosted runtime: ``python -m app.hosting_cli check``.

``check [--database]`` reports whether a process with the CURRENT environment
would start and, with ``--database``, whether the connected PostgreSQL schema is
the code's target.  One value-free JSON line on stdout: the mode, the blockers
by code and variable name (or the class of an unexpected startup error), the
scheduler state, and the schema versions.  It builds the application exactly as
a start does, so a local-mode check creates the local directories a local start
creates; it opens no SQLite file: ``--database`` needs PostgreSQL
(``DATABASE_REQUIRES_POSTGRES``).

Exit codes: 0 ready, 1 not ready, 2 usage (including ``--database`` without
PostgreSQL).  The web runtime never imports this module.
"""

from __future__ import annotations

import argparse
import json
import sys

from app import hosting


def _database_report(app_db) -> dict:
    from app.db_maintenance import get_schema_status

    conn = app_db.get_db_connection()
    try:
        status = get_schema_status(conn)
        version, target = int(status["schema_version"]), int(status["target_schema_version"])
        return {"backend": "postgres", "schema_version": version,
                "target_schema_version": target, "current": version == target}
    finally:
        conn.rollback()
        app_db.close_db_connection(None)


def _postgres_configured() -> bool:
    from app import db as app_db

    try:
        return app_db.database_backend() == "postgres"
    except ValueError:
        return False


def check(*, database: bool) -> tuple[int, dict]:
    report: dict = {"mode": None, "scheduler": "enabled" if hosting.scheduler_secret_configured() else "disabled"}
    if database and not _postgres_configured():
        # Refused before anything is built: a SQLite file is never opened by this command.
        report["error"] = "DATABASE_REQUIRES_POSTGRES"
        return 2, report
    try:
        report["mode"] = hosting.declared_mode() or hosting.MODE_LOCAL
        from app import create_app

        flask_app = create_app()
    except hosting.HostingConfigurationError as exc:
        report["startup"] = "REFUSED"
        report["blockers"] = [{"code": b.code, "names": list(b.names)} for b in exc.blockers]
        return 1, report
    except Exception as exc:
        # The message of an arbitrary startup error may quote a value (an address,
        # a path); only its class is reported.
        report["startup"] = "REFUSED"
        report["error_type"] = type(exc).__name__
        return 1, report
    report["startup"] = "OK"
    report["production"] = bool(flask_app.config.get("IS_PRODUCTION"))
    if not database:
        return 0, report
    from app import db as app_db

    with flask_app.app_context():
        try:
            report["database"] = _database_report(app_db)
        except Exception as exc:
            report["database"] = {"error_type": type(exc).__name__}
            return 1, report
    return (0 if report["database"]["current"] else 1), report


def main(argv=None, *, out=None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="python -m app.hosting_cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="would this process start; with --database, is the schema current").add_argument(
        "--database", action="store_true"
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    code, report = check(database=args.database)
    json.dump({"command": "check", **report}, out, sort_keys=True)
    out.write("\n")
    return code


__all__ = ["check", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
