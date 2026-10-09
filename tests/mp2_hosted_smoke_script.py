"""Subprocess body of the hosted real-PostgreSQL smoke -- TEST ONLY.

Run as ``python -m tests.mp2_hosted_smoke_script`` from the repository root with
the environment a WSGI host would provide.  It installs the write tripwire
FIRST, then imports ``main`` exactly as ``gunicorn main:app`` would, serves a
few requests with Flask's test client and prints ONE JSON report line.  The
parent test asserts on that line; nothing here decides pass or fail.

Environment: ``MP2_SCRATCH`` (the only writable root), ``MP2_ADMIN_EMAIL`` /
``MP2_ADMIN_PASSWORD`` (a seeded administrator).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback

from tests.hosting_tripwire import FilesystemTripwire


def _step(response):
    body = response.get_json(silent=True)
    return {"status": response.status_code, "json": body if isinstance(body, dict) else None}


def main() -> int:
    report: dict = {"import_error": None, "steps": {}}
    # Python resolves (and write-probes) the platform temp directory lazily on first
    # use.  That probe belongs to the interpreter, not to SGAA: resolve it up front.
    tempfile.gettempdir()
    with FilesystemTripwire(allowed_roots=(os.environ["MP2_SCRATCH"],)) as tripwire:
        try:
            import main as sgaa_main

            flask_app = sgaa_main.app
        except BaseException as exc:  # the report must still be printed
            report["import_error"] = type(exc).__name__
            report["import_traceback"] = traceback.format_exc()[-1500:]
            flask_app = None
        if flask_app is not None:
            client = flask_app.test_client()
            steps = report["steps"]
            steps["health"] = _step(client.get("/health"))
            steps["login_page"] = _step(client.get("/login"))
            login = client.post(
                "/login",
                data={"email": os.environ["MP2_ADMIN_EMAIL"], "senha": os.environ["MP2_ADMIN_PASSWORD"]},
            )
            steps["login"] = {"status": login.status_code, "location": login.headers.get("Location", "")}
            steps["csrf_token"] = _step(client.get("/csrf-token"))
            steps["admin_dashboard"] = _step(client.get("/admin/dashboard"))
            steps["banco_dados"] = _step(client.get("/admin/banco-dados"))
            steps["favicon"] = {"status": client.get("/favicon.ico").status_code}
            report["upload_folder"] = flask_app.config["UPLOAD_FOLDER"]
            report["hosted"] = bool(os.environ.get("SGAA_RUNTIME") == "hosted")
    report["attempts"] = tripwire.attempts
    sys.stdout.write("\n" + json.dumps(report, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
