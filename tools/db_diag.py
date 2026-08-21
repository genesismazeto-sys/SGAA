"""Read-only diagnostics for an explicitly supplied external prod-1 database."""

import json
import os
import sqlite3
import sys
from pathlib import Path

from app.prod1_schema import get_prod1_schema_status


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tools/db_diag.py EXTERNAL_DATABASE_PATH")
    path = Path(sys.argv[1]).resolve()
    repository_database = (Path(__file__).resolve().parents[1] / "database.db").resolve()
    if path == repository_database or path.name.lower() == "database.db":
        raise SystemExit("refusing repository or ambiguously named database.db")
    uri = f"file:{path.as_posix()}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        status = get_prod1_schema_status(conn)
        groups = [dict(row) for row in conn.execute(
            """SELECT eixo,grupo,COUNT(*) AS version_count
                 FROM atividade_versao GROUP BY eixo,grupo ORDER BY eixo,grupo"""
        )]
        print(json.dumps({"schema": status, "version_groups": groups}, ensure_ascii=False, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
