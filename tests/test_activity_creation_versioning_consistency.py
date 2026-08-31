"""Focused contract for Activity creation/version/request consistency."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest

import main
from app.views.admin.atividades import _normalized_version_form_payload
from app.versioning.resolver import resolver_versao_por_aluno
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "activity_consistency.db") as value:
        yield value


def test_composed_field_cards_keep_mode_selectors_interactive():
    root = Path(__file__).resolve().parents[1]
    css = (root / "static/css/components/form.css").read_text(encoding="utf-8")
    add_form = (root / "templates/admin_adicionar_atividade.html").read_text(
        encoding="utf-8"
    )
    version_form = (root / "templates/admin_catalogo_versao_form.html").read_text(
        encoding="utf-8"
    )

    assert ".field-card:has(.control:disabled){" not in css
    assert ".field-card:has(.control:disabled) .control{" not in css
    assert ".field-card .control:disabled{" in css
    assert css.count(
        ".field-card:has(.control:disabled):not(:has(.control:not(:disabled)))"
    ) == 2

    for template in (add_form, version_form):
        limitation_select = re.search(
            r'<select class="control" id="tipo_limit_card"[^>]*>', template
        ).group(0)
        suggested_select = re.search(
            r'<select class="control" id="ch_por_evento_mode"[^>]*>', template
        ).group(0)
        assert "disabled" not in limitation_select
        assert "disabled" not in suggested_select
        assert "limitValue.disabled = true" in template
        assert "limitValue.disabled = false" in template
        assert "suggestedValue.disabled = true" in template
        assert "suggestedValue.disabled = false" in template

    assert '<fieldset class="form-fieldset" {% if readonly %}disabled' in version_form


def test_suggested_hours_mode_is_part_of_dirty_snapshot_normalization():
    disabled = _normalized_version_form_payload(
        {"ch_por_evento_mode": "", "ch_por_evento": "999"}
    )
    enabled_empty = _normalized_version_form_payload(
        {"ch_por_evento_mode": "enabled", "ch_por_evento": ""}
    )

    assert disabled["ch_por_evento_mode"] == "disabled"
    assert disabled["ch_por_evento"] is None
    assert enabled_empty["ch_por_evento_mode"] == "enabled"
    assert enabled_empty["ch_por_evento"] is None

    version_form = (
        Path(__file__).resolve().parents[1]
        / "templates/admin_catalogo_versao_form.html"
    ).read_text(encoding="utf-8")
    assert (
        "ch_por_evento_mode: suggestedMode?.value === 'enabled' ? 'enabled' : 'disabled'"
        in version_form
    )
    assert "suggestedMode?.addEventListener('change'" in version_form


def _login_admin(client):
    with client.session_transaction() as session:
        session.update(
            user_id=1,
            user_type="admin",
            user_name="Administrador",
        )


def _student(conn):
    return conn.execute(
        "SELECT id AS aluno_id,usuario_id FROM alunos WHERE matricula='PPA.TESTE.0001'"
    ).fetchone()


def _login_student(client, student):
    with client.session_transaction() as session:
        session.update(
            user_id=student["usuario_id"],
            user_type="aluno",
            user_name="Aluno",
        )


def _add_payload(name: str, **changes):
    payload = {
        "tipo_atividade": "Acadêmica Complementar",
        "grupo": "1 - Grupo consistente",
        "nome": name,
        "descricao": "Descrição consistente",
        "tipo_limitacao": "semestral",
        "limite_valor": "24",
        "ch_por_evento_mode": "enabled",
        "ch_por_evento": "4",
        "observacoes": "Observações consistentes",
    }
    payload.update(changes)
    return payload


def _created(conn, name: str):
    row = conn.execute(
        """SELECT b.id AS base_id,b.nome_conceito,b.descricao,b.status AS base_status,
                  v.*
             FROM atividade_base b
             JOIN atividade_versao v ON v.atividade_base_id=b.id
            WHERE b.nome_conceito=?
         ORDER BY v.numero_versao""",
        (name,),
    ).fetchall()
    return [dict(item) for item in row]


def _post_add(client, **changes):
    name = changes.pop("name", f"Activity consistency {uuid.uuid4().hex}")
    response = client.post(
        "/admin/adicionar_atividade",
        data=_add_payload(name, **changes),
        follow_redirects=False,
    )
    return name, response


def _version_payload(source: dict, name: str, **changes):
    payload = {
        "tipo_atividade": "Acadêmica Complementar",
        "grupo": source["grupo"],
        "nome": name,
        "descricao": "Descrição consistente",
        "tipo_limitacao": (
            "semestral"
            if source["limite_semestre"] is not None
            else "total" if source["limite_total"] is not None else ""
        ),
        "limite_valor": (
            source["limite_semestre"]
            if source["limite_semestre"] is not None
            else source["limite_total"] if source["limite_total"] is not None else ""
        ),
        "ch_por_evento_mode": (
            "enabled" if source["ch_por_evento"] is not None else ""
        ),
        "ch_por_evento": (
            source["ch_por_evento"] if source["ch_por_evento"] is not None else ""
        ),
        "observacoes": source["observacao_admin"] or source["observacao_aluno"] or "",
        "versao_anterior_id": str(source["id"]),
    }
    payload.update(changes)
    return payload


def test_add_activity_uses_version_form_family_and_no_base_only_creator(env):
    client = env["client"]
    _login_admin(client)
    html = client.get("/admin/adicionar_atividade").get_data(as_text=True)
    assert re.findall(r'data-visible-field="([^"]+)"', html) == [
        "tipo",
        "grupo",
        "nome",
        "descricao",
        "limitacao",
        "ch_por_evento",
        "observacoes",
    ]
    assert "form-cards-narrow form-cards-narrow--wide" in html
    assert 'name="ch_por_evento_mode"' in html
    assert "Sem sugestão" in html and "Usar sugestão" in html
    assert html.count('name="observacoes"') == 1
    for forbidden in (
        'name="eixo"',
        'name="vigencia_inicio"',
        'name="vigencia_fim"',
        "Observação para aluno",
        "Observação administrativa",
    ):
        assert forbidden not in html

    old_creator = client.get("/admin/catalogo-versoes/nova-base")
    assert old_creator.status_code == 302
    assert old_creator.headers["Location"].endswith("/admin/adicionar_atividade")


@pytest.mark.parametrize(
    ("tipo_limitacao", "limite_valor", "expected_semester", "expected_total"),
    [
        ("", "", None, None),
        ("semestral", "31.5", 31.5, None),
        ("total", "88", None, 88.0),
    ],
)
def test_add_activity_persists_complete_active_v1(
    env, tipo_limitacao, limite_valor, expected_semester, expected_total
):
    client = env["client"]
    _login_admin(client)
    name, response = _post_add(
        client,
        tipo_limitacao=tipo_limitacao,
        limite_valor=limite_valor,
        ch_por_evento_mode="enabled",
        ch_por_evento="6.5",
    )
    assert response.status_code == 302
    with main.app.app_context():
        rows = _created(main.get_db_connection(), name)
    assert len(rows) == 1
    row = rows[0]
    assert row["base_status"] == "ativo"
    assert (row["numero_versao"], row["status"]) == (1, "ativa")
    assert (row["eixo"], row["grupo"]) == ("AAC", "1 - Grupo consistente")
    assert row["ch_por_evento"] == 6.5
    assert row["limite_semestre"] == expected_semester
    assert row["limite_total"] == expected_total
    assert row["observacao_aluno"] == row["observacao_admin"] == "Observações consistentes"
    assert row["versao_anterior_id"] is None


def test_suggested_hours_disabled_is_null_and_enabled_requires_value(env):
    client = env["client"]
    _login_admin(client)
    disabled_name, response = _post_add(
        client,
        ch_por_evento_mode="",
        ch_por_evento="999",
    )
    assert response.status_code == 302
    with main.app.app_context():
        assert _created(main.get_db_connection(), disabled_name)[0]["ch_por_evento"] is None

    missing_name, rejected = _post_add(
        client,
        ch_por_evento_mode="enabled",
        ch_por_evento="",
    )
    assert rejected.status_code == 200
    assert "Informe a Carga horária por evento" in rejected.get_data(as_text=True)
    with main.app.app_context():
        assert _created(main.get_db_connection(), missing_name) == []


def test_matrix_inline_creator_uses_same_complete_initial_version_contract(env):
    client = env["client"]
    _login_admin(client)
    with main.app.app_context():
        matrix_id = main.get_db_connection().execute(
            "SELECT id FROM matrizes_atividades ORDER BY id LIMIT 1"
        ).fetchone()[0]

    form_html = client.get(
        f"/admin/editar_matriz/{matrix_id}?tab=aac"
    ).get_data(as_text=True)
    modal = re.search(
        r'<form[^>]+id="matriz-new-activity-form"[^>]*>.*?</form>',
        form_html,
        re.S,
    ).group(0)
    for field in (
        "nome",
        "grupo_numero",
        "grupo_descricao",
        "descricao",
        "tipo_limitacao",
        "limite_valor",
        "ch_por_evento_mode",
        "ch_por_evento",
        "observacoes",
    ):
        assert f'name="{field}"' in modal

    name = f"Matrix consistency {uuid.uuid4().hex}"
    response = client.post(
        f"/admin/matrizes/{matrix_id}/atividades/nova/aac",
        data={
            "nome": name,
            "grupo_numero": "1",
            "grupo_descricao": "Grupo consistente",
            "descricao": "Descrição via matriz",
            "tipo_limitacao": "total",
            "limite_valor": "40",
            "ch_por_evento_mode": "enabled",
            "ch_por_evento": "5.5",
            "observacoes": "Observações via matriz",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    with main.app.app_context():
        row = _created(main.get_db_connection(), name)[0]
    assert (row["numero_versao"], row["status"]) == (1, "ativa")
    assert row["descricao"] == "Descrição via matriz"
    assert row["ch_por_evento"] == 5.5
    assert (row["limite_semestre"], row["limite_total"]) == (None, 40.0)
    assert row["observacao_aluno"] == row["observacao_admin"] == "Observações via matriz"


def test_legacy_edit_entrypoint_redirects_without_limite_horas_alias_write(env):
    client = env["client"]
    _login_admin(client)
    with main.app.app_context():
        before = dict(
            main.get_db_connection().execute(
                "SELECT * FROM atividade_versao WHERE id=29"
            ).fetchone()
        )

    response = client.post(
        "/admin/editar_atividade/29",
        data={"limite_horas": "999", "ch_por_evento": "888"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(
        f"/admin/catalogo-versoes/{before['atividade_base_id']}/versoes/29/editar"
    )
    with main.app.app_context():
        after = dict(
            main.get_db_connection().execute(
                "SELECT * FROM atividade_versao WHERE id=29"
            ).fetchone()
        )
    assert after == before


def test_successor_and_draft_edit_support_suggestion_and_all_limit_states(env):
    client = env["client"]
    _login_admin(client)
    name, created = _post_add(client)
    assert created.status_code == 302
    with main.app.app_context():
        source = _created(main.get_db_connection(), name)[0]

    clone_html = client.get(
        f"/admin/catalogo-versoes/{source['base_id']}/nova-versao?from={source['id']}"
    ).get_data(as_text=True)
    assert re.search(
        r'<select[^>]*id="ch_por_evento_mode"[^>]*>.*?value="enabled"[^>]*selected',
        clone_html,
        re.S,
    )
    assert re.search(r'id="ch_por_evento"[^>]*value="4"', clone_html)

    successor = _version_payload(
        source,
        name,
        ch_por_evento="7",
        tipo_limitacao="total",
        limite_valor="70",
    )
    response = client.post(
        f"/admin/catalogo-versoes/{source['base_id']}/nova-versao",
        data=successor,
        follow_redirects=False,
    )
    assert response.status_code == 302
    with main.app.app_context():
        rows = _created(main.get_db_connection(), name)
    assert len(rows) == 2
    draft = rows[1]
    assert (draft["status"], draft["versao_anterior_id"]) == ("rascunho", source["id"])
    assert (draft["ch_por_evento"], draft["limite_total"], draft["limite_semestre"]) == (
        7.0,
        70.0,
        None,
    )

    states = [
        ("", "", None, None),
        ("semestral", "19", 19.0, None),
        ("total", "45", None, 45.0),
    ]
    current = draft
    for index, (mode, value, semester, total) in enumerate(states):
        payload = _version_payload(
            current,
            name,
            tipo_limitacao=mode,
            limite_valor=value,
            ch_por_evento_mode="" if index == 0 else "enabled",
            ch_por_evento="999" if index == 0 else str(8 + index),
            versao_anterior_id=str(current["versao_anterior_id"]),
        )
        response = client.post(
            f"/admin/catalogo-versoes/{source['base_id']}/versoes/{draft['id']}/editar",
            data=payload,
            follow_redirects=False,
        )
        assert response.status_code == 302, response.get_data(as_text=True)
        with main.app.app_context():
            current = dict(
                main.get_db_connection().execute(
                    "SELECT * FROM atividade_versao WHERE id=?", (draft["id"],)
                ).fetchone()
            )
        assert (current["limite_semestre"], current["limite_total"]) == (semester, total)
        assert current["ch_por_evento"] == (None if index == 0 else float(8 + index))

    frozen_before = source.copy()
    rejected = client.post(
        f"/admin/catalogo-versoes/{source['base_id']}/versoes/{source['id']}/editar",
        data=_version_payload(source, name, ch_por_evento="99"),
        follow_redirects=False,
    )
    assert rejected.status_code == 302
    with main.app.app_context():
        frozen_after = dict(
            main.get_db_connection().execute(
                "SELECT * FROM atividade_versao WHERE id=?", (source["id"],)
            ).fetchone()
        )
    assert frozen_after == {key: frozen_before[key] for key in frozen_after}


def test_exact_request_catalogue_exposes_default_but_submitted_hours_win(env):
    client = env["client"]
    with main.app.app_context():
        conn = main.get_db_connection()
        student = dict(_student(conn))
        conn.execute(
            "UPDATE atividade_versao SET ch_por_evento=1,limite_semestre=NULL,limite_total=NULL WHERE id=29"
        )
        conn.commit()

    _login_student(client, student)
    student_html = client.get("/aluno/nova-requisicao").get_data(as_text=True)
    assert re.search(r'<option value="29"[^>]*data-default-hours="1(?:\.0)?"', student_html)
    assert "applySuggestedHours" in student_html

    student_event = f"Student override {uuid.uuid4().hex}"
    response = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_versao_id": "29",
            "nome_evento": student_event,
            "data_evento": "2026-08-30",
            "horas_solicitadas": "7.5",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    _login_admin(client)
    scope = client.get(
        f"/admin/api/aluno/{student['aluno_id']}/requisicao-scope"
    ).get_json()
    exact = next(item for item in scope["activities"] if item["id"] == 29)
    assert exact["ch_por_evento"] == 1

    admin_event = f"Admin override {uuid.uuid4().hex}"
    response = client.post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": str(student["aluno_id"]),
            "atividade_versao_id": "29",
            "nome_evento": admin_event,
            "data_evento": "2026-08-30",
            "horas_solicitadas": "9.25",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with main.app.app_context():
        conn = main.get_db_connection()
        student_request = conn.execute(
            "SELECT * FROM requisicoes WHERE nome_evento=?", (student_event,)
        ).fetchone()
        admin_request = conn.execute(
            "SELECT * FROM requisicoes WHERE nome_evento=?", (admin_event,)
        ).fetchone()
        assert student_request["horas_solicitadas"] == 7.5
        assert admin_request["horas_solicitadas"] == 9.25
        assert json.loads(student_request["regra_snapshot_json"])["ch_por_evento"] == 1
        assert json.loads(admin_request["regra_snapshot_json"])["ch_por_evento"] == 1

    processed = client.post(
        f"/admin/processar_requisicao/{admin_request['id']}",
        data={"status": "Deferida", "observacao": "default is not a ceiling"},
        follow_redirects=False,
    )
    assert processed.status_code == 302
    with main.app.app_context():
        saved = main.get_db_connection().execute(
            "SELECT status,horas_solicitadas,regra_snapshot_json FROM requisicoes WHERE id=?",
            (admin_request["id"],),
        ).fetchone()
    assert (saved["status"], saved["horas_solicitadas"]) == ("Deferida", 9.25)
    assert json.loads(saved["regra_snapshot_json"])["ch_por_evento"] == 1


def test_multiple_active_versions_preserve_exact_assigned_matrix_authority(env):
    client = env["client"]
    _login_admin(client)
    name, response = _post_add(client)
    assert response.status_code == 302
    with main.app.app_context():
        conn = main.get_db_connection()
        source = _created(conn, name)[0]
        student = dict(_student(conn))
        matrix_id = conn.execute(
            "SELECT t.matriz_id FROM alunos a JOIN turmas t ON t.id=a.turma_id WHERE a.id=?",
            (student["aluno_id"],),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item(matriz_id,atividade_base_id,atividade_versao_id) VALUES(?,?,?)",
            (matrix_id, source["base_id"], source["id"]),
        )
        conn.commit()

    successor_payload = _version_payload(source, name, ch_por_evento="5")
    assert client.post(
        f"/admin/catalogo-versoes/{source['base_id']}/nova-versao",
        data=successor_payload,
    ).status_code == 302
    with main.app.app_context():
        conn = main.get_db_connection()
        successor = _created(conn, name)[1]
    assert client.post(
        f"/admin/catalogo-versoes/{source['base_id']}/versoes/{successor['id']}/ativar"
    ).status_code == 302

    with main.app.app_context():
        conn = main.get_db_connection()
        statuses = conn.execute(
            "SELECT id,status FROM atividade_versao WHERE atividade_base_id=? ORDER BY numero_versao",
            (source["base_id"],),
        ).fetchall()
        selected = conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id=? AND atividade_base_id=?",
            (matrix_id, source["base_id"]),
        ).fetchone()[0]
        resolved = resolver_versao_por_aluno(
            conn,
            aluno_id=student["aluno_id"],
            atividade_versao_id=source["id"],
        )
    assert [(row["id"], row["status"]) for row in statuses] == [
        (source["id"], "ativa"),
        (successor["id"], "ativa"),
    ]
    assert selected == source["id"]
    assert resolved["status"] == "resolved"
    assert resolved["atividade_versao_id"] == source["id"]
