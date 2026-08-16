"""RED contracts for binding published Normas to an existing Matrix surface.

The target write surface is the existing Matrix configuration POST:
``POST /admin/editar_matriz/<matriz_id>`` with ``active_tab=dados``.
"""
from __future__ import annotations

import os
import re
import sys
from html.parser import HTMLParser

import pytest
from flask import template_rendered
from werkzeug.datastructures import MultiDict
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def norma_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "nmb_red.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            suffix = tmp_path.name
            curso_id = conn.execute(
                """
                INSERT INTO cursos (nome, codigo, duracao_periodos, periodo, status)
                VALUES (?, ?, 8, 'integral', 'ativo')
                RETURNING id
                """,
                (f"Curso C1 {suffix}", f"C1-{suffix}"),
            ).fetchone()["id"]

            matriz_id = conn.execute(
                """
                INSERT INTO matrizes_atividades (
                    curso_id, nome, versao, status,
                    horas_aac_obrigatorias, horas_extensao_obrigatorias
                ) VALUES (?, 'M1', 'rev-test', 'rascunho', 160, 80)
                RETURNING id
                """,
                (curso_id,),
            ).fetchone()["id"]
            other_matriz_id = conn.execute(
                """
                INSERT INTO matrizes_atividades (
                    curso_id, nome, versao, status,
                    horas_aac_obrigatorias, horas_extensao_obrigatorias
                ) VALUES (?, 'M2', 'rev-test', 'rascunho', 160, 80)
                RETURNING id
                """,
                (curso_id,),
            ).fetchone()["id"]

            norma_ids = {}
            for codigo, eixo, revisao, status in (
                ("AAC-rev-test-1", "AAC", "rev-test-1", "ativa"),
                ("AEU-rev-test-1", "AEU", "rev-test-1", "ativa"),
                ("AAC-rev-test-3", "AAC", "rev-test-3", "inativa"),
            ):
                norma_ids[codigo] = conn.execute(
                    """
                    INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)
                    VALUES (?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (codigo, eixo, revisao, codigo, status),
                ).fetchone()["id"]

            conn.commit()

        yield {
            **env,
            "curso_id": curso_id,
            "matriz_id": matriz_id,
            "other_matriz_id": other_matriz_id,
            "norma_ids": norma_ids,
        }


def _login_admin(client, user_id=1):
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["user_type"] = "admin"
        session["user_name"] = "NMB test admin"


def _matrix_post_data(norma_ids=(), *, include_norma_payload=True, description=""):
    data = {
        "active_tab": "dados",
        "curso_id": "1",  # replaced by _post_matrix for the isolated course
        "nome": "M1",
        "versao": "rev-test",
        "status": "rascunho",
        "data_inicio_vigencia": "",
        "data_fim_vigencia": "",
        "horas_aac_obrigatorias": "160",
        "horas_extensao_obrigatorias": "80",
        "descricao": description,
    }
    if include_norma_payload:
        data["manage_normas_present"] = "1"
        data["norma_ids"] = [str(value) for value in norma_ids]
    return data


def _post_matrix(client, env, norma_ids=(), *, follow_redirects=False):
    data = _matrix_post_data(norma_ids)
    data["curso_id"] = str(env["curso_id"])
    return client.post(
        f"/admin/editar_matriz/{env['matriz_id']}",
        data=data,
        follow_redirects=follow_redirects,
    )


def _post_legacy_matrix_edit(client, env, *, description):
    data = _matrix_post_data(include_norma_payload=False, description=description)
    data["curso_id"] = str(env["curso_id"])
    return client.post(
        f"/admin/editar_matriz/{env['matriz_id']}",
        data=data,
        follow_redirects=False,
    )


def _effective_form_data(data):
    environ = EnvironBuilder(method="POST", data=data).get_environ()
    return Request(environ).form


def _flash_categories(client):
    with client.session_transaction() as session:
        return list(session.get("_flashes", []))


def _relation_ids(env, matriz_id=None):
    matriz_id = matriz_id or env["matriz_id"]
    with main.app.app_context():
        conn = main.get_db_connection()
        return [
            row["norma_id"]
            for row in conn.execute(
                "SELECT norma_id FROM matriz_norma WHERE matriz_id = ? ORDER BY norma_id",
                (matriz_id,),
            ).fetchall()
        ]


def _add_versioned_activity(env, *, norma_id, link_version=False):
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            """
            INSERT INTO atividade_base (nome_conceito, descricao, status)
            VALUES ('Base A NMB', 'NMB base', 'ativo')
            RETURNING id
            """
        ).fetchone()["id"]
        activity_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, descricao, limite_horas, tipo_atividade,
                tem_limitacao, tipo_limitacao
            ) VALUES ('1 - NMB', 'Activity Base A NMB', 'NMB activity', 40,
                      'Acadêmica Complementar', 0, 'total')
            RETURNING id
            """
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO atividade_legacy_map (atividade_id_legacy, atividade_base_id, status)
            VALUES (?, ?, 'mapeada')
            """,
            (activity_id, base_id),
        )
        version_id = conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                numero_versao, status
            ) VALUES (?, ?, 'AAC-rev-test-1', 'AAC', '1 - NMB', 1, 'ativa')
            RETURNING id
            """,
            (base_id, norma_id),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (env["matriz_id"], activity_id),
        )
        if link_version:
            conn.execute(
                """
                INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id)
                VALUES (?, ?)
                """,
                (env["matriz_id"], version_id),
            )
        conn.commit()
    return {"base_id": base_id, "activity_id": activity_id, "version_id": version_id}


def _assign_turma(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES ('T1', 2026, 1, 'Noite', 'Ativa', 901, ?, ?, 2026, 1, 2029, 2, 'C1-T1')
            RETURNING id
            """,
            (env["curso_id"], env["matriz_id"]),
        ).fetchone()["id"]
        conn.commit()
    return turma_id


def _capture_matrix_context(client, env):
    captured = []

    def receive(sender, template, context, **extra):
        if template.name == "admin_matriz_form.html":
            captured.append(dict(context))

    template_rendered.connect(receive, main.app)
    try:
        response = client.get(f"/admin/editar_matriz/{env['matriz_id']}?tab=dados")
    finally:
        template_rendered.disconnect(receive, main.app)
    assert response.status_code == 200
    assert captured, "Matrix form did not emit a render context"
    return captured[-1]


def test_nmb_01_authorized_admin_binds_one_norma(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    before_other = None
    with main.app.app_context():
        conn = main.get_db_connection()
        before_other = dict(
            conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (norma_env["other_matriz_id"],)).fetchone()
        )

    response = _post_matrix(client, norma_env, [norma_env["norma_ids"]["AAC-rev-test-1"]])
    assert response.status_code in (302, 303)
    assert _relation_ids(norma_env) == [norma_env["norma_ids"]["AAC-rev-test-1"]]
    assert _relation_ids(norma_env, norma_env["other_matriz_id"]) == []
    with main.app.app_context():
        conn = main.get_db_connection()
        after_other = dict(
            conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (norma_env["other_matriz_id"],)).fetchone()
        )
    assert after_other == before_other


def test_nmb_02_matrix_binds_two_unique_normas(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    ids = norma_env["norma_ids"]
    _post_matrix(client, norma_env, [ids["AAC-rev-test-1"], ids["AEU-rev-test-1"]])
    assert _relation_ids(norma_env) == sorted([ids["AAC-rev-test-1"], ids["AEU-rev-test-1"]])


def test_nmb_03_resubmitting_same_binding_is_idempotent(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    norma_id = norma_env["norma_ids"]["AAC-rev-test-1"]
    first = _post_matrix(client, norma_env, [norma_id])
    second = _post_matrix(client, norma_env, [norma_id])
    assert first.status_code in (302, 303)
    assert second.status_code in (302, 303)
    assert _relation_ids(norma_env) == [norma_id]


def test_nmb_04_unused_matrix_removes_deselected_norma(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    ids = norma_env["norma_ids"]
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.executemany(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            [(norma_env["matriz_id"], ids["AAC-rev-test-1"]), (norma_env["matriz_id"], ids["AEU-rev-test-1"])],
        )
        conn.commit()

    response = _post_matrix(client, norma_env, [ids["AAC-rev-test-1"]])
    assert response.status_code in (302, 303)
    assert _relation_ids(norma_env) == [ids["AAC-rev-test-1"]]


def test_nmb_05_cannot_remove_norma_used_by_selected_version_atomically(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    norma_id = norma_env["norma_ids"]["AAC-rev-test-1"]
    activity = _add_versioned_activity(norma_env, norma_id=norma_id, link_version=True)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (norma_env["matriz_id"], norma_id),
        )
        conn.commit()

    empty_management_data = _matrix_post_data([])
    effective_form = _effective_form_data(empty_management_data)
    assert effective_form.get("manage_normas_present") == "1"
    assert effective_form.getlist("norma_ids") == []

    response = _post_matrix(client, norma_env, [])
    assert response.status_code in (302, 303, 400, 409)
    assert any(category == "error" for category, _message in _flash_categories(client))
    assert _relation_ids(norma_env) == [norma_id]
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute(
            "SELECT 1 FROM matriz_atividade_versao_item WHERE matriz_id = ? AND atividade_versao_id = ?",
            (norma_env["matriz_id"], activity["version_id"]),
        ).fetchone() is not None


def test_nmb_06_matrix_freeze_refuses_adding_norma_after_turma_assignment(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    ids = norma_env["norma_ids"]
    _post_matrix(client, norma_env, [ids["AAC-rev-test-1"]])
    _assign_turma(norma_env)
    response = _post_matrix(client, norma_env, [ids["AAC-rev-test-1"], ids["AEU-rev-test-1"]])
    assert response.status_code in (302, 303, 400, 409)
    assert any(category == "error" for category, _message in _flash_categories(client))
    assert _relation_ids(norma_env) == [ids["AAC-rev-test-1"]]


def test_nmb_07_matrix_freeze_refuses_removing_norma_after_turma_assignment(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    norma_id = norma_env["norma_ids"]["AAC-rev-test-1"]
    _post_matrix(client, norma_env, [norma_id])
    _assign_turma(norma_env)
    response = _post_matrix(client, norma_env, [])
    assert response.status_code in (302, 303, 400, 409)
    assert any(category == "error" for category, _message in _flash_categories(client))
    assert _relation_ids(norma_env) == [norma_id]


def test_nmb_08_matrix_without_turma_remains_editable_for_norma_binding(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    norma_id = norma_env["norma_ids"]["AAC-rev-test-1"]
    response = _post_matrix(client, norma_env, [norma_id])
    assert response.status_code in (302, 303)
    assert _relation_ids(norma_env) == [norma_id]


def test_nmb_09_inactive_norma_cannot_be_newly_bound(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    inactive_id = norma_env["norma_ids"]["AAC-rev-test-3"]
    response = _post_matrix(client, norma_env, [inactive_id])
    assert response.status_code in (302, 303, 400, 409)
    assert any(category == "error" for category, _message in _flash_categories(client))
    assert _relation_ids(norma_env) == []


def test_nmb_10_get_does_not_delete_historically_linked_inactive_norma(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    inactive_id = norma_env["norma_ids"]["AAC-rev-test-3"]
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (norma_env["matriz_id"], inactive_id),
        )
        conn.commit()
        before = dict(
            conn.execute(
                "SELECT * FROM matriz_norma WHERE matriz_id = ? AND norma_id = ?",
                (norma_env["matriz_id"], inactive_id),
            ).fetchone()
        )

    response = client.get(f"/admin/editar_matriz/{norma_env['matriz_id']}?tab=dados")
    assert response.status_code == 200
    assert _relation_ids(norma_env) == [inactive_id]
    with main.app.app_context():
        conn = main.get_db_connection()
        after = dict(
            conn.execute(
                "SELECT * FROM matriz_norma WHERE matriz_id = ? AND norma_id = ?",
                (norma_env["matriz_id"], inactive_id),
            ).fetchone()
        )
    assert after == before


def test_nmb_11_unused_matrix_get_exposes_linked_and_selectable_normas(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    ids = norma_env["norma_ids"]
    linked_active_id = ids["AAC-rev-test-1"]
    other_active_id = ids["AEU-rev-test-1"]
    inactive_unlinked_id = ids["AAC-rev-test-3"]
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.executemany(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            [
                (norma_env["matriz_id"], linked_active_id),
                (norma_env["other_matriz_id"], other_active_id),
            ],
        )
        conn.commit()

    context = _capture_matrix_context(client, norma_env)
    linked_ids = {row["id"] for row in context["linked_normas"]}
    selectable_active_ids = {row["id"] for row in context["available_normas"]}
    assert linked_ids == {linked_active_id}
    assert context["linked_norma_ids"] == {linked_active_id}
    assert linked_active_id in selectable_active_ids
    assert other_active_id in selectable_active_ids
    assert inactive_unlinked_id not in selectable_active_ids
    assert context["is_academically_frozen"] is False


def test_nmb_12_used_matrix_get_exposes_normas_and_frozen_state(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    norma_id = norma_env["norma_ids"]["AAC-rev-test-1"]
    _post_matrix(client, norma_env, [norma_id])
    _assign_turma(norma_env)
    context = _capture_matrix_context(client, norma_env)
    assert [row["id"] for row in context["linked_normas"]] == [norma_id]
    assert context["linked_normas"][0]["codigo"] == "AAC-rev-test-1"
    assert context["is_academically_frozen"] is True


def test_nmb_13_norma_binding_is_prerequisite_for_exact_version_eligibility(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    norma_id = norma_env["norma_ids"]["AAC-rev-test-1"]
    activity = _add_versioned_activity(norma_env, norma_id=norma_id)
    with main.app.app_context():
        conn = main.get_db_connection()
        wrong_norma_id = conn.execute(
            """
            INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)
            VALUES ('AAC-rev-test-wrong', 'AAC', 'rev-wrong', 'Wrong AAC', 'ativa')
            RETURNING id
            """
        ).fetchone()["id"]
        wrong_version_id = conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                numero_versao, status
            ) VALUES (?, ?, 'AAC-rev-test-wrong', 'AAC', '1 - NMB', 2, 'ativa')
            RETURNING id
            """,
            (activity["base_id"], wrong_norma_id),
        ).fetchone()["id"]
        conn.commit()
        assert main.get_versoes_ativas_por_base_na_matriz(
            conn, norma_env["matriz_id"], activity["base_id"]
        ) == []

    _post_matrix(client, norma_env, [norma_id])
    with main.app.app_context():
        conn = main.get_db_connection()
        eligible = main.get_versoes_ativas_por_base_na_matriz(
            conn, norma_env["matriz_id"], activity["base_id"]
        )
    assert [row["id"] for row in eligible] == [activity["version_id"]]
    assert wrong_version_id not in {row["id"] for row in eligible}
    assert eligible[0]["norma_id"] == norma_id


def test_nmb_14_admin_without_matrizes_edit_cannot_mutate_binding(norma_env):
    client = norma_env["client"]
    with main.app.app_context():
        conn = main.get_db_connection()
        user_id = conn.execute(
            """
            INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso)
            VALUES ('NMB consultivo', 'nmb-consultivo@example.test', 'hash', 'admin', 'consultivo')
            RETURNING id
            """
        ).fetchone()["id"]
        conn.commit()
    _login_admin(client, user_id=user_id)
    norma_id = norma_env["norma_ids"]["AAC-rev-test-1"]
    response = _post_matrix(client, norma_env, [norma_id])
    assert response.status_code in (302, 303, 403, 400)
    assert _relation_ids(norma_env) == []


def test_nmb_15_matrix_binding_post_obeys_existing_csrf_contract(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    original_enabled = main.app.config.get("WTF_CSRF_ENABLED")
    original_check_default = main.app.config.get("WTF_CSRF_CHECK_DEFAULT")
    main.app.config["WTF_CSRF_ENABLED"] = True
    main.app.config["WTF_CSRF_CHECK_DEFAULT"] = True
    try:
        page = client.get(f"/admin/editar_matriz/{norma_env['matriz_id']}?tab=dados")
        assert page.status_code == 200
        assert re.search(r'name="csrf_token"\s+value="[^"]+"', page.get_data(as_text=True))
        response = _post_matrix(
            client,
            norma_env,
            [norma_env["norma_ids"]["AAC-rev-test-1"]],
        )
        assert response.status_code == 400
        assert _relation_ids(norma_env) == []
    finally:
        main.app.config["WTF_CSRF_ENABLED"] = original_enabled
        main.app.config["WTF_CSRF_CHECK_DEFAULT"] = original_check_default


def test_nmb_16_existing_route_inventory_remains_131_routes_130_endpoints(norma_env):
    rules = list(main.app.url_map.iter_rules())
    assert len(rules) == 131
    assert len(main.app.view_functions) == 130
    target_rules = [rule for rule in rules if rule.endpoint == "admin_editar_matriz"]
    assert len(target_rules) == 1
    assert target_rules[0].rule == "/admin/editar_matriz/<int:matriz_id>"
    assert {"GET", "POST"} <= set(target_rules[0].methods)


def test_nmb_17_legacy_matrix_edit_without_norma_payload_preserves_bindings(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    norma_id = norma_env["norma_ids"]["AAC-rev-test-1"]
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (norma_env["matriz_id"], norma_id),
        )
        conn.commit()

    response = _post_legacy_matrix_edit(
        client,
        norma_env,
        description="Legacy edit without Norma section",
    )
    assert response.status_code in (302, 303)
    assert _relation_ids(norma_env) == [norma_id]
    with main.app.app_context():
        conn = main.get_db_connection()
        matrix = conn.execute(
            "SELECT descricao FROM matrizes_atividades WHERE id = ?",
            (norma_env["matriz_id"],),
        ).fetchone()
    assert matrix["descricao"] == "Legacy edit without Norma section"


def test_nmb_18_frozen_matrix_allows_non_academic_description_edit(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    norma_id = norma_env["norma_ids"]["AAC-rev-test-1"]
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (norma_env["matriz_id"], norma_id),
        )
        conn.commit()
    _assign_turma(norma_env)

    with main.app.app_context():
        conn = main.get_db_connection()
        before_matrix = dict(
            conn.execute(
                """
                SELECT curso_id, status, data_inicio_vigencia, data_fim_vigencia,
                       horas_aac_obrigatorias, horas_extensao_obrigatorias
                  FROM matrizes_atividades
                 WHERE id = ?
                """,
                (norma_env["matriz_id"],),
            ).fetchone()
        )
        before_relations = _relation_ids(norma_env)
        before_activity_links = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT matriz_id, atividade_versao_id
                  FROM matriz_atividade_versao_item
                 WHERE matriz_id = ?
                """,
                (norma_env["matriz_id"],),
            ).fetchall()
        ]

    response = _post_legacy_matrix_edit(
        client,
        norma_env,
        description="Descriptive change after assignment",
    )
    assert response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        after_matrix = dict(
            conn.execute(
                """
                SELECT curso_id, status, data_inicio_vigencia, data_fim_vigencia,
                       horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
                  FROM matrizes_atividades
                 WHERE id = ?
                """,
                (norma_env["matriz_id"],),
            ).fetchone()
        )
        after_activity_links = [
            tuple(row)
            for row in conn.execute(
                """
                SELECT matriz_id, atividade_versao_id
                  FROM matriz_atividade_versao_item
                 WHERE matriz_id = ?
                """,
                (norma_env["matriz_id"],),
            ).fetchall()
        ]

    assert after_matrix["descricao"] == "Descriptive change after assignment"
    assert {key: after_matrix[key] for key in before_matrix} == before_matrix
    assert _relation_ids(norma_env) == before_relations
    assert after_activity_links == before_activity_links


def _matrix_post_forms(html: str, matrix_path: str) -> list[str]:
    forms = re.findall(r"<form\b[^>]*>.*?</form>", html, flags=re.IGNORECASE | re.DOTALL)
    return [
        form
        for form in forms
        if re.search(r"method\s*=\s*['\"]post['\"]", form, flags=re.IGNORECASE)
        and (
            not re.search(r"action\s*=", form, flags=re.IGNORECASE)
            or matrix_path in form
        )
    ]


class _SuccessfulMatrixFormParser(HTMLParser):
    """Collect successful controls from the rendered Matrix POST form."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_form = False
        self.submitted = []
        self.controls = []
        self._textarea = None
        self._select = None
        self._option = None

    @staticmethod
    def _attrs(attributes):
        return {key: value for key, value in attributes}

    def handle_starttag(self, tag, attributes):
        tag = tag.lower()
        attrs = self._attrs(attributes)
        if tag == "form" and not self.in_form:
            self.in_form = attrs.get("method", "").lower() == "post"
            return
        if not self.in_form:
            return
        if tag == "input":
            name = attrs.get("name")
            input_type = attrs.get("type", "text").lower()
            if not name:
                return
            control = {
                "name": name,
                "value": attrs.get("value", ""),
                "type": input_type,
                "disabled": "disabled" in attrs,
                "checked": "checked" in attrs,
            }
            self.controls.append(control)
            if control["disabled"] or input_type in {"submit", "button", "reset", "file"}:
                return
            if input_type in {"checkbox", "radio"} and not control["checked"]:
                return
            self.submitted.append((name, control["value"]))
        elif tag == "textarea":
            self._textarea = {
                "name": attrs.get("name"),
                "disabled": "disabled" in attrs,
                "parts": [],
            }
        elif tag == "select":
            self._select = {
                "name": attrs.get("name"),
                "disabled": "disabled" in attrs,
                "multiple": "multiple" in attrs,
                "options": [],
            }
        elif tag == "option" and self._select is not None:
            self._option = {
                "value": attrs.get("value", ""),
                "selected": "selected" in attrs,
                "parts": [],
            }

    def handle_data(self, data):
        if self._textarea is not None:
            self._textarea["parts"].append(data)
        if self._option is not None:
            self._option["parts"].append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "textarea" and self._textarea is not None:
            control = self._textarea
            self._textarea = None
            if control["name"] and not control["disabled"]:
                self.submitted.append((control["name"], "".join(control["parts"])))
        elif tag == "option" and self._option is not None and self._select is not None:
            self._select["options"].append(self._option)
            self._option = None
        elif tag == "select" and self._select is not None:
            select = self._select
            self._select = None
            if select["name"] and not select["disabled"]:
                selected = [option for option in select["options"] if option["selected"]]
                if not selected and select["options"] and not select["multiple"]:
                    selected = select["options"][:1]
                self.submitted.extend(
                    (select["name"], option["value"])
                    for option in selected
                )
        elif tag == "form" and self.in_form:
            self.in_form = False


def _rendered_matrix_form_data(html: str) -> tuple[MultiDict, list[dict]]:
    parser = _SuccessfulMatrixFormParser()
    parser.feed(_matrix_post_forms(html, "/admin/editar_matriz/")[0])
    return MultiDict(parser.submitted), parser.controls


def test_nmb_19_matrix_admin_ui_exposes_norma_controls_and_freeze_state(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    matrix_path = f"/admin/editar_matriz/{norma_env['matriz_id']}"
    ids = norma_env["norma_ids"]

    response = client.get(f"{matrix_path}?tab=dados")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    forms = _matrix_post_forms(html, matrix_path)
    assert forms, "Existing Matrix POST form was not rendered"
    form = forms[0]
    assert re.search(
        r"<(?:input|select)\b[^>]*\bname\s*=\s*['\"][^'\"]*norma[^'\"]*['\"]",
        form,
        flags=re.IGNORECASE,
    ), "Matrix form has no Norma selection control"
    assert str(ids["AAC-rev-test-1"]) in form
    assert str(ids["AEU-rev-test-1"]) in form
    assert "AAC-rev-test-1" in form and "AEU-rev-test-1" in form
    assert re.search(r"\bAAC\b", form) and re.search(r"\bAEU\b", form)

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (norma_env["matriz_id"], ids["AAC-rev-test-1"]),
        )
        conn.commit()

    response = client.get(f"{matrix_path}?tab=dados")
    linked_form = _matrix_post_forms(response.get_data(as_text=True), matrix_path)[0]
    linked_value_position = linked_form.find(f'value="{ids["AAC-rev-test-1"]}"')
    assert linked_value_position >= 0
    assert re.search(
        r"(?:checked|selected)",
        linked_form[max(0, linked_value_position - 120): linked_value_position + 180],
        flags=re.IGNORECASE,
    ), "Linked Norma is not represented as selected"

    _assign_turma(norma_env)
    response = client.get(f"{matrix_path}?tab=dados")
    frozen_form = _matrix_post_forms(response.get_data(as_text=True), matrix_path)[0]
    frozen_value_position = frozen_form.find(f'value="{ids["AAC-rev-test-1"]}"')
    assert frozen_value_position >= 0
    assert re.search(
        r"(?:disabled|readonly)",
        frozen_form[max(0, frozen_value_position - 120): frozen_value_position + 180],
        flags=re.IGNORECASE,
    ), "Frozen Matrix Norma control remains mutating"


def test_review_shared_norma_is_selectable_through_rendered_matrix_form(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    norma_id = norma_env["norma_ids"]["AAC-rev-test-1"]
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (norma_env["other_matriz_id"], norma_id),
        )
        conn.commit()

    response = client.get(f"/admin/editar_matriz/{norma_env['matriz_id']}?tab=dados")
    assert response.status_code == 200
    form_data, controls = _rendered_matrix_form_data(response.get_data(as_text=True))
    shared_controls = [
        control
        for control in controls
        if control["name"] == "norma_ids" and control["value"] == str(norma_id)
    ]
    assert shared_controls
    assert all(not control["disabled"] for control in shared_controls)
    assert form_data.get("manage_normas_present") == "1"

    form_data.setlist("norma_ids", [str(norma_id)])
    saved = client.post(
        f"/admin/editar_matriz/{norma_env['matriz_id']}",
        data=form_data,
        follow_redirects=False,
    )
    assert saved.status_code in (302, 303)
    assert _relation_ids(norma_env) == [norma_id]
    assert _relation_ids(norma_env, norma_env["other_matriz_id"]) == [norma_id]


def test_review_frozen_rendered_form_round_trip_omits_disabled_norma_controls(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    norma_id = norma_env["norma_ids"]["AAC-rev-test-1"]
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (norma_env["matriz_id"], norma_id),
        )
        conn.commit()
    _assign_turma(norma_env)

    response = client.get(f"/admin/editar_matriz/{norma_env['matriz_id']}?tab=dados")
    assert response.status_code == 200
    form_data, controls = _rendered_matrix_form_data(response.get_data(as_text=True))
    assert "manage_normas_present" not in form_data
    assert form_data.getlist("norma_ids") == []
    assert any(
        control["name"] == "norma_ids"
        and control["value"] == str(norma_id)
        and control["disabled"]
        and control["checked"]
        for control in controls
    )

    form_data["descricao"] = "Rendered frozen round-trip"
    saved = client.post(
        f"/admin/editar_matriz/{norma_env['matriz_id']}",
        data=form_data,
        follow_redirects=False,
    )
    assert saved.status_code in (302, 303)
    assert _relation_ids(norma_env) == [norma_id]
    with main.app.app_context():
        conn = main.get_db_connection()
        description = conn.execute(
            "SELECT descricao FROM matrizes_atividades WHERE id = ?",
            (norma_env["matriz_id"],),
        ).fetchone()["descricao"]
    assert description == "Rendered frozen round-trip"


def test_review_inactive_linked_norma_survives_rendered_form_round_trip(norma_env):
    client = norma_env["client"]
    _login_admin(client)
    inactive_id = norma_env["norma_ids"]["AAC-rev-test-3"]
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (norma_env["matriz_id"], inactive_id),
        )
        conn.commit()

    response = client.get(f"/admin/editar_matriz/{norma_env['matriz_id']}?tab=dados")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "AAC-rev-test-3" in html
    form_data, controls = _rendered_matrix_form_data(html)
    assert form_data.get("manage_normas_present") == "1"
    assert form_data.getlist("norma_ids") == [str(inactive_id)]
    assert any(
        control["name"] == "norma_ids"
        and control["value"] == str(inactive_id)
        and control["disabled"]
        and control["checked"]
        for control in controls
    )
    assert any(
        control["name"] == "norma_ids"
        and control["value"] == str(inactive_id)
        and control["type"] == "hidden"
        and not control["disabled"]
        for control in controls
    )

    form_data["descricao"] = "Inactive Norma round-trip"
    saved = client.post(
        f"/admin/editar_matriz/{norma_env['matriz_id']}",
        data=form_data,
        follow_redirects=False,
    )
    assert saved.status_code in (302, 303)
    assert _relation_ids(norma_env) == [inactive_id]
