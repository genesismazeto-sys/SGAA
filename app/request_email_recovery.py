"""Opt-in, single-decision recovery of legacy return notifications.

Never imported by listing routes. The operator must identify both a request
and its exact decision timestamp. Existing event history is never backfilled.
"""
from __future__ import annotations

import argparse

from app.db import write_transaction
from app.requisition_policy import open_return_window
from app.request_email_notifications import record_final_decision_event
from app.settings import get_return_response_days


def recover_return_notification(conn, *, request_id: int, decided_at: str, apply=False) -> str:
    """Return a fixed result code; apply rechecks eligibility under a row lock.

    An engine-neutral no-op UPDATE acquires the request lock on PostgreSQL;
    write_transaction provides SQLite's write lock. A concurrent resubmission,
    expiry or another recovery cannot race the eligibility check and snapshot.
    """
    def eligible():
        row = conn.execute(
            "SELECT status, data_processamento, admin_id, aluno_id, observacao "
            "FROM requisicoes WHERE id=?", (request_id,),
        ).fetchone()
        if (row is None or row["status"] != "Devolvida"
                or row["data_processamento"] != decided_at or row["admin_id"] is None
                or row["aluno_id"] is None or not str(row["observacao"] or "").strip()):
            return False
        if open_return_window(row["status"], decided_at, get_return_response_days(conn)) is None:
            return False
        return conn.execute(
            "SELECT id FROM requisicao_email_eventos WHERE requisicao_id=? LIMIT 1",
            (request_id,),
        ).fetchone() is None

    if not apply:
        return "eligible" if eligible() else "ineligible"
    with write_transaction(conn):
        locked = conn.execute(
            "UPDATE requisicoes SET id=id WHERE id=? AND status='Devolvida' "
            "AND data_processamento=? RETURNING id", (request_id, decided_at),
        ).fetchone()
        if locked is None or not eligible():
            return "ineligible"
        event_id = record_final_decision_event(conn, requisicao_id=request_id, decided_at=decided_at)
        if event_id is None:
            raise RuntimeError("return notification recovery produced no event")
    return "recovered"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", type=int, required=True)
    parser.add_argument("--decided-at", required=True)
    parser.add_argument("--apply", action="store_true", help="Persist one pending event; default is read-only")
    args = parser.parse_args(argv)
    if args.request_id <= 0:
        parser.error("--request-id must be positive")
    from app import create_app
    from app.db import get_db_connection

    with create_app().app_context():
        result = recover_return_notification(
            get_db_connection(), request_id=args.request_id,
            decided_at=args.decided_at, apply=args.apply,
        )
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
