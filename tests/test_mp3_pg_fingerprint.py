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


def test_a_derived_table_whose_column_list_changed_is_never_excused():
    """A reference taken by another code version (another column list) proves nothing about the rows."""
    reference = {"requisicoes": dict(_entry(1, columns=("id", "status")), sha256="1" * 64)}
    current = {"requisicoes": dict(_entry(1, columns=("id", "observacao")), sha256="2" * 64)}
    verdict = fp._classify(reference, current, {"requisicoes": []})
    assert verdict["refusal"] == "SHAPE_CHANGED" and verdict["derived_classes"] == []


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


# ---- the fixed derived-write classes (R3 remediation, finding 2) -------------------------------------


def _prepare(url, *statements):
    conn = adapter(url)
    try:
        from app.db import ensure_app_settings_schema

        ensure_app_settings_schema(conn)  # the defaults a running deployment seeded long before the opening
        conn.execute("INSERT INTO configuracoes_app(chave, valor) VALUES('auto_indefer_devolvida', '1')"
                     " ON CONFLICT (chave) DO UPDATE SET valor = '1'")
        conn.execute("INSERT INTO usuario_credenciais(usuario_id, estado) VALUES(1, 'personal')"
                     " ON CONFLICT DO NOTHING")
        for statement in statements:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


def _act(url, action):
    conn = adapter(url)
    try:
        action(conn)
        conn.commit()
    finally:
        conn.close()


def _classify(url, reference):
    conn = adapter(url).raw_connection
    try:
        conn.autocommit = True
        return fp.classify(conn, reference)
    finally:
        conn.close()


_RETURNED = ("UPDATE requisicoes SET status = 'Devolvida', observacao = 'Corrigir o certificado.',"
             " data_processamento = '2020-01-01 00:00:00' WHERE id = 1")
_NOTIFIED = "UPDATE requisicoes SET aluno_update_notified_at = '2026-10-01 10:00:00', aluno_update_seen_at = NULL WHERE id = 1"


def _auto_reject(conn):
    from app.requisitions import auto_indefer_devolvidas

    assert auto_indefer_devolvidas(conn) == 1


def _seen(conn):
    from app.requisitions import mark_student_request_updates_seen

    mark_student_request_updates_seen(conn, [1])


@NEEDS_PG
def test_nothing_changed_is_identical_and_names_no_class(database):
    _prepare(database)
    verdict = _classify(database, _snapshot(database))
    assert verdict["identical"] is True and verdict["refusal"] is None and verdict["derived_classes"] == []


@NEEDS_PG
@pytest.mark.parametrize("setup,actions,classes", [
    ((_RETURNED,), (_auto_reject,), ["REQUISICOES_AUTO_REJECTION"]),
    (("UPDATE requisicoes SET status = 'Devolvida', observacao = NULL,"
      " data_processamento = '2020-01-01 00:00:00' WHERE id = 1",), (_auto_reject,), ["REQUISICOES_AUTO_REJECTION"]),
    ((_NOTIFIED,), (_seen,), ["REQUISICOES_STUDENT_SEEN"]),
    ((_RETURNED, _NOTIFIED), (_seen, _auto_reject), ["REQUISICOES_AUTO_REJECTION", "REQUISICOES_STUDENT_SEEN"]),
])
def test_the_real_derived_writes_are_classified_exactly(database, setup, actions, classes):
    _prepare(database, *setup)
    reference = _snapshot(database)
    for action in actions:
        _act(database, action)
    verdict = _classify(database, reference)
    assert verdict["refusal"] is None, verdict
    assert verdict["identical"] is False and verdict["derived_classes"] == classes
    assert verdict["changed_tables"] == ["REQUISICOES"]


@NEEDS_PG
@pytest.mark.parametrize("setup,write,refusal", [
    # a human rejection: the status alone, or with the processing columns -- not the derived shape
    ((_RETURNED,), "UPDATE requisicoes SET status = 'Indeferida' WHERE id = 1", "COLUMNS_NOT_DERIVED"),
    ((_RETURNED,), "UPDATE requisicoes SET status = 'Indeferida', observacao = 'Sem documento.',"
                   " data_processamento = '2026-11-01 10:00:00', admin_id = 1 WHERE id = 1", "COLUMNS_NOT_DERIVED"),
    # the right columns, but the note is not the reference note plus the automatic marker
    ((_RETURNED,), "UPDATE requisicoes SET status = 'Indeferida', observacao = 'Outra coisa.' || chr(10) ||"
                   " '[Indeferida automaticamente: prazo de adequa\u00e7\u00e3o de 30 dias expirado.]' WHERE id = 1",
     "DERIVED_VALUE_NOT_REPRODUCED"),
    # the reference note already holds a marker; the change replaces nothing with the marker but appends
    # other text of the marker's length: only an end-anchored marker after the reference note is derived
    (("UPDATE requisicoes SET status = 'Devolvida', data_processamento = '2020-01-01 00:00:00', observacao ="
      " '[Indeferida automaticamente: prazo de adequa\u00e7\u00e3o de 30 dias expirado.]' WHERE id = 1",),
     "UPDATE requisicoes SET status = 'Indeferida', observacao = observacao || chr(10) ||"
     " repeat('x', char_length(observacao)) WHERE id = 1", "DERIVED_VALUE_NOT_REPRODUCED"),
    # the marker, but the request was never a returned one
    ((), "UPDATE requisicoes SET status = 'Indeferida', observacao = '[Indeferida automaticamente: prazo de"
         " adequa\u00e7\u00e3o de 30 dias expirado.]' WHERE id = 1", "DERIVED_VALUE_NOT_REPRODUCED"),
    # a seen mark rewritten (it was already set): not the empty-to-set transition
    (("UPDATE requisicoes SET aluno_update_seen_at = '2026-10-02 10:00:00' WHERE id = 1",),
     "UPDATE requisicoes SET aluno_update_seen_at = '2026-11-02 10:00:00' WHERE id = 1", "DERIVED_VALUE_NOT_REPRODUCED"),
    # a seen mark cleared: a human action (new notification), not the student's view
    ((_NOTIFIED, "UPDATE requisicoes SET aluno_update_seen_at = '2026-10-02 10:00:00' WHERE id = 1"),
     "UPDATE requisicoes SET aluno_update_seen_at = NULL WHERE id = 1", "DERIVED_VALUE_NOT_REPRODUCED"),
    # an added request, a removed one, any other table
    ((), "INSERT INTO requisicoes(id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,"
         "status,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot) SELECT 7,aluno_id,atividade_versao_id,"
         "data_solicitacao,data_evento,horas_solicitadas,status,regra_snapshot_json,turma_id_snapshot,"
         "turma_codigo_snapshot FROM requisicoes WHERE id = 1", "ROWS_ADDED_OR_REMOVED"),
    ((), "UPDATE alunos SET nome = 'Outro Nome' WHERE id = 1", "NOT_A_DERIVED_TABLE"),
    ((), "UPDATE usuario_credenciais SET auth_version = auth_version + 1, atualizado_em = '2026-11-01 10:00:00'"
         " WHERE usuario_id = 1", "NOT_A_DERIVED_TABLE"),
])
def test_anything_else_is_not_derived_and_says_why(database, setup, write, refusal):
    _prepare(database, *setup)
    reference = _snapshot(database)
    _act(database, lambda conn: conn.execute(write))
    verdict = _classify(database, reference)
    assert verdict["refusal"] == refusal, verdict
    assert verdict["derived_classes"] == []


@NEEDS_PG
def test_a_password_rehash_is_never_derived_it_is_indistinguishable_from_a_password_change(database):
    from app.user_accounts import rehash_usuario_password

    _prepare(database)
    reference = _snapshot(database)
    _act(database, lambda conn: rehash_usuario_password(conn, 1, "pbkdf2:sha256:600000$abc$def"))
    assert _classify(database, reference)["refusal"] == "NOT_A_DERIVED_TABLE"


@NEEDS_PG
def test_the_database_identity_is_stable_and_names_the_database(database, registry):
    from tools import pg_backup

    def identity(url):
        conn = pg_backup.connect(url)
        try:
            return fp.database_identity_sha256(conn)
        finally:
            conn.close()

    first = identity(database)
    assert first == identity(database) and len(first) == 64
    other_name, other = registry.create(template=registry.template)
    try:
        assert identity(other) != first  # a copy is another database
    finally:
        registry.drop(other_name)
