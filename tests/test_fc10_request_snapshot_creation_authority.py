"""FC10 — mandatory request-time snapshot creation authority.

The tests in this file are intentionally discriminating.  They exercise the
two normal creation paths, the historical importer boundary, exact turma
matrix resolution, immutable snapshot identity, and fail-closed atomicity.
"""
from __future__ import annotations

import io
import json
import os
import sys
import uuid

import openpyxl
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app.versioning import resolver as versioning_resolver
from app.student_documents import resolve_student_document_path
from app.views import aluno as aluno_view
from app.views.admin import requisicoes as admin_requisicoes_view
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def fc10_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc10_request_snapshot.db") as env:
        yield env


def _student_seed():
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            """
            SELECT a.id AS aluno_id, a.usuario_id, a.turma_id, t.matriz_id
              FROM alunos a
              JOIN turmas t ON t.id = a.turma_id
             WHERE a.matricula = 'PPA.TESTE.0001'
            """
        ).fetchone()
        assert row is not None
        return dict(row)


def _login_student(client, student):
    with client.session_transaction() as session:
        session["user_id"] = student["usuario_id"]
        session["user_type"] = "aluno"
        session["user_name"] = "Aluno FC10"


def _login_admin(client):
    with main.app.app_context():
        admin_id = main.get_db_connection().execute(
            "SELECT id FROM usuarios WHERE tipo = 'admin' ORDER BY id LIMIT 1"
        ).fetchone()["id"]
    with client.session_transaction() as session:
        session["user_id"] = admin_id
        session["user_type"] = "admin"
        session["user_name"] = "Administrador FC10"


def _request_by_name(name):
    with main.app.app_context():
        return main.get_db_connection().execute(
            """
            SELECT id, aluno_id, atividade_id, atividade_versao_id,
                   regra_snapshot_json, codigo_normativo_snapshot, nome_evento,
                   horas_solicitadas, data_evento
              FROM requisicoes
             WHERE nome_evento = ?
            """,
            (name,),
        ).fetchone()


def _post_student(client, student, name, *, activity_id=1, files=None):
    _login_student(client, student)
    data = {
        "atividade_id": str(activity_id),
        "nome_evento": name,
        "data_evento": "2030-05-10",
        "horas_solicitadas": "4",
        "observacao": "FC10 request",
    }
    if files:
        data.update(files)
    return client.post("/aluno/nova-requisicao", data=data, follow_redirects=False)


def _snapshot(row):
    assert row is not None
    assert row["atividade_versao_id"] is not None
    assert row["codigo_normativo_snapshot"]
    assert row["regra_snapshot_json"]
    return json.loads(row["regra_snapshot_json"])


def _attachment_count():
    with main.app.app_context():
        conn = main.get_db_connection()
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'requisicao_arquivos'"
        ).fetchone()
        if not exists:
            return 0
        return conn.execute("SELECT COUNT(*) AS count FROM requisicao_arquivos").fetchone()["count"]


def _post_admin(client, student, name, *, activity_id=1, files=None):
    _login_admin(client)
    data = {
        "aluno_id": str(student["aluno_id"]),
        "atividade_id": str(activity_id),
        "nome_evento": name,
        "data_evento": "2030-05-10",
        "horas_solicitadas": "4",
        "observacao": "FC10 admin request",
    }
    if files:
        data.update(files)
    return client.post("/admin/requisicoes/nova", data=data, follow_redirects=False)


def _add_active_version(
    conn,
    *,
    base_id=1,
    matrix_id=None,
    prefix="fc10",
    documentos_json=None,
):
    token = uuid.uuid4().hex[:8]
    code = f"AAC-{prefix}-{token}"
    conn.execute(
        "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) VALUES (?, 'AAC', ?, ?, 'ativa')",
        (code, token, f"Norma {code}"),
    )
    norma_id = conn.execute(
        "SELECT id FROM norma_atividade WHERE codigo = ?", (code,)
    ).fetchone()["id"]
    numero = conn.execute(
        "SELECT COALESCE(MAX(numero_versao), 0) + 1 AS next_number FROM atividade_versao WHERE atividade_base_id = ?",
        (base_id,),
    ).fetchone()["next_number"]
    version_id = conn.execute(
        """
        INSERT INTO atividade_versao
            (atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
            numero_versao, status, observacao_aluno, observacao_admin,
            documentos_json)
        VALUES (?, ?, ?, 'AAC', '1 - FC10', ?, 'ativa', ?, ?, ?)
        RETURNING id
        """,
        (
            base_id,
            norma_id,
            code,
            numero,
            f"Aluno rule {code}",
            f"Admin rule {code}",
            documentos_json,
        ),
    ).fetchone()["id"]
    if matrix_id is not None:
        conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)", (matrix_id, norma_id))
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)",
            (matrix_id, version_id),
        )
    return version_id, norma_id, code


def _add_student_in_turma(conn, turma_id, suffix):
    email = f"fc10-{suffix}-{uuid.uuid4().hex[:8]}@example.test"
    usuario_id = conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, 'aluno') RETURNING id",
        (f"Aluno {suffix}", email, main.hash_password("aluno123")),
    ).fetchone()["id"]
    aluno_id = conn.execute(
        """
        INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status)
        VALUES (?, ?, ?, ?, ?, 'Ativo')
        RETURNING id
        """,
        (usuario_id, f"Aluno {suffix}", f"FC10-{suffix}-{uuid.uuid4().hex[:6]}", email, turma_id),
    ).fetchone()["id"]
    return {"aluno_id": aluno_id, "usuario_id": usuario_id, "turma_id": turma_id}


def test_t01_student_normal_creation_persists_exact_matrix_snapshot(fc10_env):
    student = _student_seed()
    name = f"FC10 T01 {uuid.uuid4().hex}"
    response = _post_student(fc10_env["client"], student, name)
    assert response.status_code in (302, 303)
    row = _request_by_name(name)
    payload = _snapshot(row)
    assert row["aluno_id"] == student["aluno_id"]
    assert row["atividade_versao_id"] == 29
    assert payload["matriz_id_efetiva"] == 2
    assert payload["atividade_versao_id"] == 29
    assert payload["norma_id"] == 2


def test_t02_admin_normal_creation_uses_the_same_creation_authority(fc10_env):
    student = _student_seed()
    name = f"FC10 T02 {uuid.uuid4().hex}"
    response = _post_admin(fc10_env["client"], student, name)
    assert response.status_code in (302, 303)
    row = _request_by_name(name)
    payload = _snapshot(row)
    assert payload["flow_origin"] == "admin_create"
    assert payload["matriz_id_efetiva"] == 2
    assert row["atividade_versao_id"] == 29


def test_t03_removed_write_switch_cannot_disable_student_snapshot(fc10_env, monkeypatch):
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "0")
    name = f"FC10 T03 {uuid.uuid4().hex}"
    response = _post_student(fc10_env["client"], _student_seed(), name)
    assert response.status_code in (302, 303)
    assert _snapshot(_request_by_name(name))["atividade_versao_id"] == 29


def test_t04_removed_write_switch_cannot_disable_admin_snapshot(fc10_env, monkeypatch):
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "false")
    name = f"FC10 T04 {uuid.uuid4().hex}"
    response = _post_admin(fc10_env["client"], _student_seed(), name)
    assert response.status_code in (302, 303)
    assert _snapshot(_request_by_name(name))["atividade_versao_id"] == 29


def test_t05_null_turma_matrix_fails_closed_without_row(fc10_env):
    student = _student_seed()
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE turmas SET matriz_id = NULL WHERE id = ?", (student["turma_id"],))
        conn.commit()
    name = f"FC10 T05 {uuid.uuid4().hex}"
    response = _post_student(fc10_env["client"], student, name)
    assert response.status_code == 200
    assert _request_by_name(name) is None


def test_t06_invalid_turma_matrix_fails_closed_without_row(fc10_env):
    student = _student_seed()
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE turmas SET matriz_id = 999999 WHERE id = ?", (student["turma_id"],))
        conn.commit()
    name = f"FC10 T06 {uuid.uuid4().hex}"
    response = _post_student(fc10_env["client"], student, name)
    assert response.status_code == 200
    assert _request_by_name(name) is None


def test_t07_activity_outside_exact_matrix_is_rejected_without_row(fc10_env):
    name = f"FC10 T07 {uuid.uuid4().hex}"
    response = _post_student(fc10_env["client"], _student_seed(), name, activity_id=6)
    assert response.status_code == 200
    assert _request_by_name(name) is None


def test_t08_missing_matrix_version_link_fails_closed_without_row(fc10_env):
    student = _student_seed()
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "DELETE FROM matriz_atividade_versao_item WHERE matriz_id = 2 AND atividade_versao_id = 29"
        )
        conn.commit()
    name = f"FC10 T08 {uuid.uuid4().hex}"
    response = _post_student(fc10_env["client"], student, name)
    assert response.status_code == 200
    assert _request_by_name(name) is None


def test_t09_ambiguous_active_versions_fail_closed_without_row(fc10_env):
    student = _student_seed()
    with main.app.app_context():
        conn = main.get_db_connection()
        _add_active_version(conn, matrix_id=2, prefix="amb")
        conn.commit()
    name = f"FC10 T09 {uuid.uuid4().hex}"
    response = _post_student(fc10_env["client"], student, name)
    assert response.status_code == 200
    assert _request_by_name(name) is None


def test_t10_matrix_norma_removal_fails_closed_without_row(fc10_env):
    student = _student_seed()
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM norma_atividade WHERE id = 2")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
    name = f"FC10 T10 {uuid.uuid4().hex}"
    response = _post_student(fc10_env["client"], student, name)
    assert response.status_code == 200
    assert _request_by_name(name) is None


def test_t11_inactive_selected_version_fails_closed_without_row(fc10_env):
    student = _student_seed()
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE atividade_versao SET status = 'inativa' WHERE id = 29")
        conn.commit()
    name = f"FC10 T11 {uuid.uuid4().hex}"
    response = _post_student(fc10_env["client"], student, name)
    assert response.status_code == 200
    assert _request_by_name(name) is None


def test_t12_snapshot_carries_the_exact_activity_version_number(fc10_env):
    name = f"FC10 T12 {uuid.uuid4().hex}"
    _post_student(fc10_env["client"], _student_seed(), name)
    row = _request_by_name(name)
    payload = _snapshot(row)
    with main.app.app_context():
        live = main.get_db_connection().execute(
            "SELECT numero_versao FROM atividade_versao WHERE id = 29"
        ).fetchone()
    assert payload["atividade_versao_numero"] == live["numero_versao"]


def test_t13_snapshot_carries_rule_bearing_fields_and_display_identity(fc10_env):
    v1_documents = f'{{"source":"V1-{uuid.uuid4().hex}"}}'
    v2_documents = f'{{"source":"V2-{uuid.uuid4().hex}"}}'
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE atividade_versao SET documentos_json = ? WHERE id = 29", (v1_documents,))
        _add_active_version(conn, prefix="fc10-v2", documentos_json=v2_documents)
        conn.commit()
    name = f"FC10 T13 {uuid.uuid4().hex}"
    _post_student(fc10_env["client"], _student_seed(), name)
    payload = _snapshot(_request_by_name(name))
    with main.app.app_context():
        live = main.get_db_connection().execute(
            """
            SELECT av.norma_id, av.codigo_normativo, av.eixo, av.grupo,
                   av.ch_por_evento, av.limite_semestre, av.limite_total,
                   av.observacao_aluno, av.observacao_admin,
                   av.documentos_json, av.vigencia_inicio, av.vigencia_fim, av.status,
                   av.numero_versao, ab.nome_conceito
              FROM atividade_versao av
              JOIN atividade_base ab ON ab.id = av.atividade_base_id
             WHERE av.id = 29
            """
        ).fetchone()
    assert payload["norma_id"] == live["norma_id"]
    assert payload["codigo_normativo"] == live["codigo_normativo"]
    assert payload["eixo"] == live["eixo"]
    assert payload["grupo"] == live["grupo"]
    assert payload["ch_por_evento"] == live["ch_por_evento"]
    assert payload["limite_semestre"] == live["limite_semestre"]
    assert payload["limite_total"] == live["limite_total"]
    assert payload["observacao_aluno"] == live["observacao_aluno"]
    assert payload["observacao_admin"] == live["observacao_admin"]
    assert payload["documentos_json"] == v1_documents == live["documentos_json"]
    assert payload["vigencia_inicio"] == live["vigencia_inicio"]
    assert payload["vigencia_fim"] == live["vigencia_fim"]
    assert payload["versao_status"] == live["status"]
    assert payload["atividade_versao_numero"] == live["numero_versao"]
    assert payload["nome_exibivel"]
    assert payload["nome_legacy"]
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE atividade_versao SET documentos_json = ? WHERE id = 29", ("V1-mutated",))
        conn.commit()
    assert _snapshot(_request_by_name(name))["documentos_json"] == v1_documents


def test_t14_snapshot_columns_and_json_identity_are_consistent(fc10_env, monkeypatch):
    name = f"FC10 T14 {uuid.uuid4().hex}"
    _post_student(fc10_env["client"], _student_seed(), name)
    row = _request_by_name(name)
    payload = _snapshot(row)
    assert row["atividade_versao_id"] == payload["atividade_versao_id"]
    assert row["codigo_normativo_snapshot"] == payload["codigo_normativo"]
    assert payload["atividade_id_legacy"] == row["atividade_id"]
    assert payload["legacy_scope_ok"] is True
    assert payload["atividade_versao_id"] == 29
    with main.app.app_context():
        live_version = main.get_db_connection().execute(
            "SELECT numero_versao FROM atividade_versao WHERE id = 29"
        ).fetchone()["numero_versao"]
    assert payload["atividade_versao_numero"] == live_version
    assert row["codigo_normativo_snapshot"] == payload["codigo_normativo"]
    assert payload["norma_id"] == 2
    assert payload["eixo"] == "AAC"
    assert payload["matriz_id_efetiva"] == 2

    original_resolver = versioning_resolver.resolver_versao_por_aluno

    def mixed_identity_resolver(*args, **kwargs):
        result = dict(original_resolver(*args, **kwargs))
        result["codigo_normativo"] = "FOREIGN-V2-CODE"
        result["eixo"] = "AEU"
        return result

    monkeypatch.setattr(
        versioning_resolver,
        "resolver_versao_por_aluno",
        mixed_identity_resolver,
    )
    mixed_name = f"FC10 T14 mixed {uuid.uuid4().hex}"
    response = _post_student(fc10_env["client"], _student_seed(), mixed_name)
    assert response.status_code == 200
    assert _request_by_name(mixed_name) is None


def test_t15_student_nonstructural_edit_preserves_snapshot_bytes(fc10_env):
    student = _student_seed()
    name = f"FC10 T15 {uuid.uuid4().hex}"
    _post_student(fc10_env["client"], student, name)
    before = _request_by_name(name)
    before_values = (before["atividade_versao_id"], before["codigo_normativo_snapshot"], before["regra_snapshot_json"])
    _login_student(fc10_env["client"], student)
    response = fc10_env["client"].post(
        f"/aluno/requisicoes/{before['id']}?edit=1",
        data={
            "atividade_id": "1",
            "nome_evento": f"{name} edit",
            "data_evento": "2030-05-11",
            "horas_solicitadas": "9",
            "observacao": "updated metadata",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    after = _request_by_name(f"{name} edit")
    assert (after["atividade_versao_id"], after["codigo_normativo_snapshot"], after["regra_snapshot_json"]) == before_values


def test_t16_student_activity_change_is_rejected_after_snapshot(fc10_env):
    student = _student_seed()
    name = f"FC10 T16 {uuid.uuid4().hex}"
    _post_student(fc10_env["client"], student, name)
    before = _request_by_name(name)
    _login_student(fc10_env["client"], student)
    response = fc10_env["client"].post(
        f"/aluno/requisicoes/{before['id']}?edit=1",
        data={
            "atividade_id": "2",
            "nome_evento": f"{name} attempted",
            "data_evento": "2030-05-11",
            "horas_solicitadas": "5",
            "observacao": "must reject",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "já possui versão normativa registrada" in response.get_data(as_text=True)
    after = _request_by_name(name)
    assert after["atividade_id"] == 1
    assert after["regra_snapshot_json"] == before["regra_snapshot_json"]


def test_t17_admin_activity_change_is_rejected_after_snapshot(fc10_env):
    student = _student_seed()
    name = f"FC10 T17 {uuid.uuid4().hex}"
    _post_admin(fc10_env["client"], student, name)
    before = _request_by_name(name)
    _login_admin(fc10_env["client"])
    response = fc10_env["client"].post(
        f"/admin/requisicoes/{before['id']}/editar",
        data={
            "atividade_id": "2",
            "nome_evento": f"{name} attempted",
            "data_evento": "2030-05-11",
            "horas_solicitadas": "5",
            "observacao": "must reject",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "já possui versão normativa registrada" in response.get_data(as_text=True)
    after = _request_by_name(name)
    assert after["atividade_id"] == 1
    assert after["regra_snapshot_json"] == before["regra_snapshot_json"]


def test_t18_later_unlinked_version_does_not_rewrite_existing_snapshot(fc10_env):
    student = _student_seed()
    name = f"FC10 T18 {uuid.uuid4().hex}"
    _post_student(fc10_env["client"], student, name)
    before = _request_by_name(name)
    with main.app.app_context():
        conn = main.get_db_connection()
        _add_active_version(conn, prefix="later")
        conn.commit()
    after = _request_by_name(name)
    assert after["atividade_versao_id"] == before["atividade_versao_id"]
    assert after["regra_snapshot_json"] == before["regra_snapshot_json"]


def test_t19_resolver_exception_rolls_back_student_creation(fc10_env, monkeypatch):
    def raising_resolver(*args, **kwargs):
        raise RuntimeError("resolver unavailable")

    monkeypatch.setattr(versioning_resolver, "resolver_versao_por_aluno", raising_resolver)
    name = f"FC10 T19 {uuid.uuid4().hex}"
    response = _post_student(fc10_env["client"], _student_seed(), name)
    assert response.status_code == 200
    assert _request_by_name(name) is None


class _ConnectionProxy:
    def __init__(self, conn, *, fail_commit=False, fail_attachment_insert=False, marker=None):
        self._conn = conn
        self._fail_commit = fail_commit
        self._fail_attachment_insert = fail_attachment_insert
        self._marker = marker or {}

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, parameters=()):
        if self._fail_attachment_insert and "INSERT INTO requisicao_arquivos" in str(sql):
            assert self._marker["file_existed"]
            raise RuntimeError("forced attachment registration failure")
        return self._conn.execute(sql, parameters)

    def commit(self):
        if self._fail_commit:
            assert self._marker["file_existed"]
            raise RuntimeError("forced post-file commit failure")
        return self._conn.commit()


def _force_post_file_failure(monkeypatch, view_module, fc10_env, *, fail_commit=False, fail_attachment_insert=False):
    marker = {"file_existed": False}
    original_getter = view_module.get_db_connection
    original_save = view_module.save_student_document

    def tracked_save(*args, **kwargs):
        saved = original_save(*args, **kwargs)
        if saved:
            path = resolve_student_document_path(kwargs["root_folder"], saved)
            marker["file_existed"] = os.path.isfile(path)
        return saved

    def proxy_getter():
        return _ConnectionProxy(
            original_getter(),
            fail_commit=fail_commit,
            fail_attachment_insert=fail_attachment_insert,
            marker=marker,
        )

    monkeypatch.setattr(view_module, "save_student_document", tracked_save)
    monkeypatch.setattr(view_module, "get_db_connection", proxy_getter)
    return marker


def test_t20_student_post_file_pre_commit_failure_compensates_everything(fc10_env, monkeypatch):
    name = f"FC10 T20 {uuid.uuid4().hex}"
    marker = _force_post_file_failure(monkeypatch, aluno_view, fc10_env, fail_commit=True)
    response = _post_student(
        fc10_env["client"],
        _student_seed(),
        name,
        files={"arquivo_comprovante": (io.BytesIO(b"should-not-be-saved"), "proof.pdf")},
    )
    assert response.status_code == 200
    assert marker["file_existed"]
    assert _request_by_name(name) is None
    assert _attachment_count() == 0
    assert not any(path.is_file() for path in fc10_env["documents_path"].rglob("*"))


def test_t20_admin_post_file_pre_commit_failure_compensates_everything(fc10_env, monkeypatch):
    student = _student_seed()
    name = f"FC10 T20 admin {uuid.uuid4().hex}"
    marker = _force_post_file_failure(monkeypatch, admin_requisicoes_view, fc10_env, fail_commit=True)
    response = _post_admin(
        fc10_env["client"],
        student,
        name,
        files={"comprovantes_files": (io.BytesIO(b"admin proof"), "proof.pdf")},
    )
    assert response.status_code in (302, 303)
    assert marker["file_existed"]
    assert _request_by_name(name) is None
    assert _attachment_count() == 0
    assert not any(path.is_file() for path in fc10_env["documents_path"].rglob("*"))


def test_t20b_attachment_registration_failure_compensates_file(fc10_env, monkeypatch):
    student = _student_seed()
    name = f"FC10 T20b {uuid.uuid4().hex}"
    marker = _force_post_file_failure(
        monkeypatch,
        admin_requisicoes_view,
        fc10_env,
        fail_attachment_insert=True,
    )
    response = _post_admin(
        fc10_env["client"],
        student,
        name,
        files={"comprovantes_files": (io.BytesIO(b"registration proof"), "proof.pdf")},
    )
    assert response.status_code in (302, 303)
    assert marker["file_existed"]
    assert _request_by_name(name) is None
    assert _attachment_count() == 0
    assert not any(path.is_file() for path in fc10_env["documents_path"].rglob("*"))


def test_t21_historical_null_owner_row_remains_without_snapshot(fc10_env):
    name = f"FC10 T21 {uuid.uuid4().hex}"
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            """
            INSERT INTO requisicoes
                (aluno_id, atividade_id, data_solicitacao, data_evento,
                 horas_solicitadas, nome_evento, status)
            VALUES (NULL, 1, '2030-05-01', '2030-05-02', 4, ?, 'Pendente')
            """,
            (name,),
        )
        conn.commit()
    _login_admin(fc10_env["client"])
    assert fc10_env["client"].get("/admin/requisicoes").status_code == 200
    row = _request_by_name(name)
    assert row["aluno_id"] is None
    assert row["atividade_versao_id"] is None
    assert row["regra_snapshot_json"] is None
    assert row["codigo_normativo_snapshot"] is None


def test_t22_historical_importer_keeps_null_owner_and_no_snapshot(fc10_env, monkeypatch):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Requisições"
    sheet.cell(row=3, column=6).value = "Visitas técnicas ou culturais"
    sheet.cell(row=3, column=7).value = 4
    sheet.cell(row=3, column=8).value = "2030-05-02"
    sheet.cell(row=3, column=9).value = "Pendente"
    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)

    def forbidden_resolver(*args, **kwargs):
        raise AssertionError("historical importer must not resolve a snapshot")

    monkeypatch.setattr(versioning_resolver, "resolver_versao_por_aluno", forbidden_resolver)
    _login_admin(fc10_env["client"])
    response = fc10_env["client"].post(
        "/admin/importar_requisicoes",
        data={"arquivo_excel": (stream, "fc10-history.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute(
            """
            SELECT aluno_id, atividade_versao_id, regra_snapshot_json,
                   codigo_normativo_snapshot
              FROM requisicoes
             WHERE observacao LIKE 'Importado da planilha linha 3'
             ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    assert row is not None
    assert row["aluno_id"] is None
    assert row["atividade_versao_id"] is None
    assert row["regra_snapshot_json"] is None
    assert row["codigo_normativo_snapshot"] is None


def test_t23_exact_matrix_beats_preferred_or_newest_candidates(fc10_env):
    with main.app.app_context():
        conn = main.get_db_connection()
        t10 = conn.execute("SELECT id FROM turmas WHERE codigo = 'PPA-T10'").fetchone()
        t10_student = _add_student_in_turma(conn, t10["id"], "T23-T10")
        conn.commit()
    name_t10 = f"FC10 T23 T10 {uuid.uuid4().hex}"
    _post_student(fc10_env["client"], t10_student, name_t10)
    row_t10 = _request_by_name(name_t10)
    payload_t10 = _snapshot(row_t10)
    assert payload_t10["matriz_id_efetiva"] == 1
    assert row_t10["atividade_versao_id"] == 2

    name_t11 = f"FC10 T23 T11 {uuid.uuid4().hex}"
    _post_student(fc10_env["client"], _student_seed(), name_t11)
    row_t11 = _request_by_name(name_t11)
    payload_t11 = _snapshot(row_t11)
    assert payload_t11["matriz_id_efetiva"] == 2
    assert row_t11["atividade_versao_id"] == 29
    assert row_t10["atividade_versao_id"] != row_t11["atividade_versao_id"]


def test_t24_student_and_admin_share_snapshot_identity_owner(fc10_env):
    student = _student_seed()
    student_name = f"FC10 T24 student {uuid.uuid4().hex}"
    admin_name = f"FC10 T24 admin {uuid.uuid4().hex}"
    _post_student(fc10_env["client"], student, student_name)
    _post_admin(fc10_env["client"], student, admin_name)
    student_payload = _snapshot(_request_by_name(student_name))
    admin_payload = _snapshot(_request_by_name(admin_name))
    assert student_payload["atividade_versao_id"] == admin_payload["atividade_versao_id"] == 29
    assert student_payload["matriz_id_efetiva"] == admin_payload["matriz_id_efetiva"] == 2
    for key in (
        "atividade_base_id",
        "atividade_id_legacy",
        "atividade_versao_numero",
        "codigo_normativo",
        "eixo",
        "grupo",
        "norma_id",
        "ch_por_evento",
        "limite_semestre",
        "limite_total",
        "observacao_aluno",
        "observacao_admin",
        "vigencia_inicio",
        "vigencia_fim",
        "versao_status",
        "nome_exibivel",
        "nome_legacy",
    ):
        assert student_payload[key] == admin_payload[key], key
