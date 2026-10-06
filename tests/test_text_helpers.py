import os
import sqlite3
import subprocess
import sys

import pytest

from app.text import normalize_header, ptbr_sqlite_collation, ptbr_text_sort_key


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  ÓRGÃO\tPúblico  ", "orgao publico"),
        ("AÇÃO   COMPLEMENTAR", "acao complementar"),
        (None, "none"),
        ("", ""),
        (0, "0"),
        (123, "123"),
    ],
)
def test_normalize_header_contract(value, expected):
    assert normalize_header(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  Árvore   Azul ", (False, "arvore azul", "  Árvore   Azul ")),
        ("ÁRVORE azul", (False, "arvore azul", "ÁRVORE azul")),
        (12, (False, "12", "12")),
        (None, (True, "", "")),
        ("", (True, "", "")),
        (0, (True, "", "")),
        (False, (True, "", "")),
    ],
)
def test_ptbr_text_sort_key_contract(value, expected):
    assert ptbr_text_sort_key(value) == expected


def test_ptbr_text_sort_key_is_stable_and_places_empty_values_last():
    values = ["  Érica", "erica", None, "", "Álvaro", 0]
    assert sorted(values, key=ptbr_text_sort_key) == ["Álvaro", "  Érica", "erica", None, "", 0]


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("ação", "ACAO", 0),
        ("  Maria   Silva ", "maria silva", 0),
        (None, "", 0),
        (0, False, 0),
        ("Álvaro", "Bruno", -1),
        ("zeta", "Érica", 1),
    ],
)
def test_ptbr_sqlite_collation_contract(left, right, expected):
    assert ptbr_sqlite_collation(left, right) == expected
    assert ptbr_sqlite_collation(right, left) == -expected


def test_ptbr_sqlite_collation_orders_an_in_memory_database():
    conn = sqlite3.connect(":memory:")
    try:
        conn.create_collation("PTBR_NOACCENT", ptbr_sqlite_collation)
        conn.execute("CREATE TABLE values_tmp (value TEXT)")
        conn.executemany(
            "INSERT INTO values_tmp (value) VALUES (?)",
            [("Zeta",), ("Éverto",), ("Everaldo",)],
        )
        rows = conn.execute(
            "SELECT value FROM values_tmp ORDER BY COALESCE(value, '') COLLATE PTBR_NOACCENT ASC"
        ).fetchall()
    finally:
        conn.close()

    assert [row[0] for row in rows] == ["Everaldo", "Éverto", "Zeta"]


def test_main_compatibility_exports_are_the_shared_callables():
    import main

    assert main.normalize_header is normalize_header
    assert main.ptbr_text_sort_key is ptbr_text_sort_key
    assert main.ptbr_sqlite_collation is ptbr_sqlite_collation


def test_app_text_import_does_not_import_main():
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            (
                "import sys; "
                "assert 'main' not in sys.modules; "
                "import app.text; "
                "assert 'main' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr


#: PG-READINESS-U5-D: sha256 of ``human_text_key`` over every assigned code
#: point (unicodedata 15.0.0), recorded from the historical per-character
#: implementation at 091ba4b *before* the key was consolidated onto the frozen
#: fold in ``app.human_text_fold``.  It is an independent regression pin: the
#: consolidation makes ``human_text_key == fold`` true by construction.
HISTORICAL_HUMAN_TEXT_KEY_FINGERPRINT = (
    286719,
    "aaead8f8ea2b43befb5bf3de9edf007ebe9e1bacfec303edaca9acfb8e506db2",
)


def test_human_text_key_matches_the_historical_fingerprint_on_every_code_point():
    import hashlib
    import unicodedata

    from app.text import human_text_key

    assert unicodedata.unidata_version == "15.0.0", "re-record deliberately on a new Unicode version"
    digest = hashlib.sha256()
    count = 0
    for code_point in range(0x110000):
        char = chr(code_point)
        if unicodedata.category(char) in ("Cn", "Cs"):
            continue
        digest.update(f"{code_point:x}\t{human_text_key(char)}\n".encode("utf-8"))
        count += 1
    assert (count, digest.hexdigest()) == HISTORICAL_HUMAN_TEXT_KEY_FINGERPRINT
