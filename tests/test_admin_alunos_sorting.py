import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main


def test_admin_alunos_sort_nome_is_accent_insensitive():
    conn = sqlite3.connect(":memory:")
    conn.create_collation("PTBR_NOACCENT", main.ptbr_sqlite_collation)
    conn.execute("CREATE TABLE alunos_tmp (nome TEXT)")
    conn.executemany(
        "INSERT INTO alunos_tmp (nome) VALUES (?)",
        [
            ("Zeta Ordenacao Acento",),
            ("Éverto Ordenacao Acento",),
            ("Everaldo Ordenacao Acento",),
        ],
    )
    rows = conn.execute(
        "SELECT nome FROM alunos_tmp ORDER BY COALESCE(nome, '') COLLATE PTBR_NOACCENT ASC"
    ).fetchall()
    conn.close()

    names = [row[0] for row in rows]
    assert names == [
        "Everaldo Ordenacao Acento",
        "Éverto Ordenacao Acento",
        "Zeta Ordenacao Acento",
    ]
