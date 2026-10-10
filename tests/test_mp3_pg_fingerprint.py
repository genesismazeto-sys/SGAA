# coding: utf-8
"""MP-3 slice 5: the business-table fingerprint that detects the point of no return.

Unit part (no database): which tables and columns count, how two fingerprints
compare and what the comparison names.  Real-PostgreSQL part (opt-in,
``SGAA_PG_TEST_URL``): a business write is seen down to the column, and none of
the writes the system makes on its own is (mirror state, throttle windows,
cloud accounts, the password re-hash) -- the property the ledger's PONR needs.
"""

from __future__ import annotations

import io
import json

import pytest

from app import pg_migrate_from_sqlite as pathb
from app import pg_schema
from tests.storage_mp1_pg_support import PG_URL, Registry, adapter
from tools import pg_fingerprint as fp

NEEDS_PG = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)


def _entry(rows, columns=("id", "status"), hashes=None):
    hashes = hashes if hashes is not None else {str(i): [f"h{i}", f"s{i}"] for i in range(1, rows + 1)}
    return {"rows": rows, "sha256": "d" * 64, "columns": list(columns), "row_hashes": hashes}


def _fingerprint(tables):
    return {"format": fp.FORMAT, "tables": tables, "fingerprint_sha256": fp._digest_of(tables)}


def test_the_fingerprint_covers_business_tables_and_none_of_the_machine_state():
    tables = set(fp.business_tables())
    assert {"requisicoes", "requisicao_arquivos", "admin_arquivos", "usuarios", "usuario_credenciais",
            "alunos", "turmas", "reportes", "configuracoes_app"} <= tables
    machine = {"storage_objects", "requisicao_alerta_receipts", "storage_upload_intents", "storage_worker_status",
               "auth_throttle_events", "admin_import_previews", "cloud_accounts", "cloud_drive_settings",
               "configuracoes_backup", "senha_tokens", "backup_logs", "schema_migrations",
               pg_schema.PG_SCHEMA_META_TABLE}
    assert not (tables & machine)
    assert all(pathb.SOURCE_TABLE_POLICIES[t].policy == pathb.MIGRATE_EXACT for t in tables)
    assert fp.EXCLUDED_COLUMNS == {"usuarios": frozenset({"senha"})}


def test_the_table_entry_ignores_the_excluded_column_and_nothing_else():
    columns = pathb._columns("usuarios")
    base = [None] * len(columns)
    base[columns.index("id")] = 1
    base[columns.index("nome")] = "A"
    base[columns.index("senha")] = "hash-old"
    changed_password = list(base)
    changed_password[columns.index("senha")] = "hash-new"
    changed_name = list(base)
    changed_name[columns.index("nome")] = "B"
    # normalize_rows needs typed values; build rows through the contract's own types.
    types = pathb._column_types("usuarios")

    def typed(row):
        return tuple((0 if types[name] == "integer" else "x") if value is None else value
                     for name, value in zip(columns, row))

    rows = lambda *items: [typed(item) for item in items]  # noqa: E731
    first = fp._table_entry("usuarios", rows(base))
    assert "senha" not in first["columns"] and "id" in first["columns"]
    assert fp._table_entry("usuarios", rows(changed_password)) == first            # the re-hash is invisible
    assert fp._table_entry("usuarios", rows(changed_name))["sha256"] != first["sha256"]  # a real change is not


def test_compare_names_tables_and_columns_and_counts_rows_never_values():
    base = {"requisicoes": _entry(3), "alunos": _entry(1, ("id", "nome"))}
    assert fp.compare(_fingerprint(base), _fingerprint(dict(base))) == {
        "identical": True, "changed_tables": [], "detail": {}}
    edited = json.loads(json.dumps(base))
    edited["requisicoes"]["row_hashes"]["2"] = ["h2", "NEW"]
    edited["requisicoes"]["sha256"] = "e" * 64
    verdict = fp.compare(_fingerprint(base), _fingerprint(edited))
    assert verdict["changed_tables"] == ["REQUISICOES"]
    assert verdict["detail"]["REQUISICOES"] == {
        "rows_before": 3, "rows_after": 3, "added": 0, "removed": 0, "changed": 1, "changed_columns": ["status"]}
    grown = dict(base, reportes=_entry(1))
    detail = fp.compare(_fingerprint(base), _fingerprint(grown))["detail"]["REPORTES"]
    assert detail["rows_before"] is None and detail["rows_after"] == 1
    shrunk = json.loads(json.dumps(base))
    del shrunk["requisicoes"]["row_hashes"]["3"]
    shrunk["requisicoes"]["rows"] = 2
    shrunk["requisicoes"]["sha256"] = "f" * 64
    detail = fp.compare(_fingerprint(base), _fingerprint(shrunk))["detail"]["REQUISICOES"]
    assert detail["removed"] == 1 and detail["rows_after"] == 2


def test_a_tampered_or_foreign_fingerprint_is_refused():
    good = _fingerprint({"alunos": _entry(1)})
    tampered = json.loads(json.dumps(good))
    tampered["tables"]["alunos"]["rows"] = 2
    for bad in (tampered, {"format": 1, "tables": {}, "fingerprint_sha256": "x"}, {"tables": {}}, "nope"):
        with pytest.raises(fp.Refused) as caught:
            fp.compare(good, bad)
        assert caught.value.code == "FINGERPRINT_INVALID"


def test_the_command_line_compares_files_and_reports_only_names_and_counts(tmp_path):
    reference = tmp_path / "a.json"
    current = tmp_path / "b.json"
    reference.write_text(json.dumps(_fingerprint({"alunos": _entry(1, ("id", "nome"))})))
    changed = _entry(2, ("id", "nome"))
    current.write_text(json.dumps(_fingerprint({"alunos": changed})))
    out = io.StringIO()
    assert fp.main(["compare", "--reference", str(reference), "--current", str(current)], out=out) == 1
    report = json.loads(out.getvalue())
    assert report["changed_tables"] == ["ALUNOS"] and report["identical"] is False
    assert report["detail"]["ALUNOS"]["added"] == 1
    assert fp.main(["compare", "--reference", str(reference), "--current", str(reference)], out=io.StringIO()) == 0
    assert fp.main(["compare", "--reference", str(reference)], out=io.StringIO(), err=io.StringIO()) == 2
    err = io.StringIO()
    assert fp.main(["compare", "--reference", str(tmp_path / "none.json"), "--current", str(current)],
                   out=io.StringIO(), err=err) == 1
    assert "FINGERPRINT_UNREADABLE" in err.getvalue()


# ---- real PostgreSQL ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registry():
    registry = Registry("fprint")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def database(registry):
    name, url = registry.create(template=registry.template)
    yield url
    registry.drop(name)


def _snapshot(url):
    conn = adapter(url).raw_connection
    try:
        conn.autocommit = True
        return fp.snapshot(conn)
    finally:
        conn.close()


@NEEDS_PG
def test_a_business_write_is_seen_to_the_column_and_the_snapshot_is_stable_without_one(database):
    first = _snapshot(database)
    assert fp.compare(first, _snapshot(database))["identical"] is True
    conn = adapter(database)
    try:
        conn.execute("UPDATE requisicoes SET horas_solicitadas = horas_solicitadas + 1 WHERE id = 1")
        conn.commit()
    finally:
        conn.close()
    verdict = fp.compare(first, _snapshot(database))
    assert verdict["changed_tables"] == ["REQUISICOES"]
    assert verdict["detail"]["REQUISICOES"]["changed"] == 1
    assert verdict["detail"]["REQUISICOES"]["changed_columns"] == ["horas_solicitadas"]


@NEEDS_PG
def test_what_the_system_writes_on_its_own_is_not_a_business_write(database):
    from tests.storage_mp1_support import insert_object

    first = _snapshot(database)
    conn = adapter(database)
    try:
        insert_object(conn, key="fingerprint/probe-object", content=b"x")  # a mirror-visible object row
        conn.execute("UPDATE cloud_accounts SET active = 0 WHERE id = 1")  # a Drive reconnect
        conn.execute(
            "INSERT INTO auth_throttle_events(scope, key_digest, occurred_at) VALUES('login_ip', ?, "
            "'2026-10-09 12:00:00')", ("f" * 64,),
        )
        conn.execute("UPDATE usuarios SET senha = 'rehashed-on-login' WHERE id = 1")  # the login re-hash
        conn.commit()
    finally:
        conn.close()
    assert fp.compare(first, _snapshot(database))["identical"] is True


@NEEDS_PG
def test_the_snapshot_command_writes_a_file_outside_the_repository_and_never_a_row(database, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database)
    target = tmp_path / "reference.json"
    out = io.StringIO()
    assert fp.main(["snapshot", "--out", str(target)], out=out) == 0
    written = json.loads(target.read_text())
    assert written["tables"] and written["fingerprint_sha256"] == json.loads(out.getvalue())["fingerprint_sha256"]
    text = target.read_text()
    assert "Aluno" not in text and "@" not in text  # digests and counts only, no value
    err = io.StringIO()
    assert fp.main(["snapshot", "--out", str(target)], out=io.StringIO(), err=err) == 1
    assert "OUTPUT_EXISTS" in err.getvalue()
