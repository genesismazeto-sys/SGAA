from __future__ import annotations

import os
import re
import sys
import uuid

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def versioned_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d75c_new_activity.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            curso_id = conn.execute(
                "SELECT curso_id FROM matrizes_atividades WHERE id = 1"
            ).fetchone()[0]
            aac_matrix_id = conn.execute(
                """
                INSERT INTO matrizes_atividades
                    (curso_id, nome, versao, status, horas_aac_obrigatorias, horas_extensao_obrigatorias)
                VALUES (?, 'FC09 test AAC Matrix', 'test-aac', 'rascunho', 100, 50)
                RETURNING id
                """,
                (curso_id,),
            ).fetchone()["id"]
            aeu_matrix_id = conn.execute(
                """
                INSERT INTO matrizes_atividades
                    (curso_id, nome, versao, status, horas_aac_obrigatorias, horas_extensao_obrigatorias)
                VALUES (?, 'FC09 test AEU Matrix', 'test-aeu', 'rascunho', 100, 50)
                RETURNING id
                """,
                (curso_id,),
            ).fetchone()["id"]
            conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, 1)", (aac_matrix_id,))
            conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, 3)", (aeu_matrix_id,))
            conn.commit()
        env.update({"aac_matrix_id": aac_matrix_id, "aeu_matrix_id": aeu_matrix_id})
        yield env


@pytest.fixture()
def versioned_env_csrf(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d75c_new_activity_csrf.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            curso_id = conn.execute(
                "SELECT curso_id FROM matrizes_atividades WHERE id = 1"
            ).fetchone()[0]
            aac_matrix_id = conn.execute(
                """
                INSERT INTO matrizes_atividades
                    (curso_id, nome, versao, status, horas_aac_obrigatorias, horas_extensao_obrigatorias)
                VALUES (?, 'FC09 CSRF AAC Matrix', 'test-aac', 'rascunho', 100, 50)
                RETURNING id
                """,
                (curso_id,),
            ).fetchone()["id"]
            conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, 1)", (aac_matrix_id,))
            conn.commit()
        env["aac_matrix_id"] = aac_matrix_id
        original_enabled = main.app.config.get("WTF_CSRF_ENABLED")
        original_check_default = main.app.config.get("WTF_CSRF_CHECK_DEFAULT")
        main.app.config["WTF_CSRF_ENABLED"] = True
        main.app.config["WTF_CSRF_CHECK_DEFAULT"] = True
        try:
            yield env
        finally:
            main.app.config["WTF_CSRF_ENABLED"] = original_enabled
            main.app.config["WTF_CSRF_CHECK_DEFAULT"] = original_check_default


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def _unique_name(prefix: str) -> str:
    token = uuid.uuid4().hex[:8]
    return f"{prefix} {token}"


def _table_counts(conn) -> dict[str, int]:
    return {
        "atividades": conn.execute("SELECT COUNT(*) AS c FROM atividades").fetchone()["c"],
        "atividade_base": conn.execute("SELECT COUNT(*) AS c FROM atividade_base").fetchone()["c"],
        "atividade_legacy_map": conn.execute("SELECT COUNT(*) AS c FROM atividade_legacy_map").fetchone()["c"],
        "atividade_versao": conn.execute("SELECT COUNT(*) AS c FROM atividade_versao").fetchone()["c"],
        "matrizes_atividades_itens": conn.execute("SELECT COUNT(*) AS c FROM matrizes_atividades_itens").fetchone()["c"],
        "matriz_atividade_versao_item": conn.execute("SELECT COUNT(*) AS c FROM matriz_atividade_versao_item").fetchone()["c"],
    }


def _extract_modal_form(html: str) -> str:
    match = re.search(r'<form[^>]+id="matriz-new-activity-form"[^>]*>.*?</form>', html, re.S)
    assert match is not None, "Formulario modal de nova atividade nao encontrado"
    return match.group(0)


def _extract_csrf_token(form_html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', form_html)
    assert match is not None, "csrf_token ausente no formulario modal"
    return match.group(1)


def test_get_matrix_aac_page_renders_new_activity_button_in_left_header(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    matrix_id = versioned_env["aac_matrix_id"]

    response = client.get(f"/admin/editar_matriz/{matrix_id}?tab=aac")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert re.search(r'aria-labelledby="transfer-available-heading".*?\+ Nova atividade', html, re.S)
    assert f'action="/admin/matrizes/{matrix_id}/atividades/nova/aac"' in html


def test_get_matrix_aeu_page_renders_new_activity_button(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    matrix_id = versioned_env["aeu_matrix_id"]

    response = client.get(f"/admin/editar_matriz/{matrix_id}?tab=aea")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert "+ Nova atividade" in html
    assert f'action="/admin/matrizes/{matrix_id}/atividades/nova/aea"' in html


def test_post_new_aac_activity_creates_base_version_and_matrix_links(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    matrix_id = versioned_env["aac_matrix_id"]
    activity_name = _unique_name("Matrix AAC")

    response = client.post(
        f"/admin/matrizes/{matrix_id}/atividades/nova/aac",
        data={
            "nome": activity_name,
            "grupo_numero": "7",
            "grupo_descricao": "Grupo piloto AAC",
            "add_to_matrix": "1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert activity_name in response.get_data(as_text=True)

    with main.app.app_context():
        conn = main.get_db_connection()
        atividade = conn.execute("SELECT * FROM atividades WHERE nome = ?", (activity_name,)).fetchone()
        assert atividade is not None
        assert atividade["tipo_atividade"] == "Acadêmica Complementar"
        assert atividade["grupo"] == "7 - Grupo piloto AAC"

        base = conn.execute("SELECT * FROM atividade_base WHERE nome_conceito = ?", (activity_name,)).fetchone()
        assert base is not None

        legacy_map = conn.execute(
            """
            SELECT *
              FROM atividade_legacy_map
             WHERE atividade_id_legacy = ?
            """,
            (atividade["id"],),
        ).fetchone()
        assert legacy_map is not None
        assert legacy_map["atividade_base_id"] == base["id"]

        versao = conn.execute(
            "SELECT * FROM atividade_versao WHERE atividade_base_id = ?",
            (base["id"],),
        ).fetchone()
        assert versao is not None
        assert versao["atividade_base_id"] == base["id"]
        assert versao["norma_id"] == 1
        assert versao["codigo_normativo"] == "AAC-rev5"
        assert versao["eixo"] == "AAC"
        assert versao["grupo"] == "7 - Grupo piloto AAC"
        assert versao["status"] == "ativa"

        legacy_scope_link = conn.execute(
            """
            SELECT COUNT(*) AS c
              FROM matrizes_atividades_itens
             WHERE matriz_id = ? AND atividade_id = ?
            """,
            (matrix_id, atividade["id"]),
        ).fetchone()["c"]
        assert legacy_scope_link == 1

        matrix_version_link = conn.execute(
            """
            SELECT COUNT(*) AS c
              FROM matriz_atividade_versao_item
              WHERE matriz_id = ? AND atividade_versao_id = ?
            """,
            (matrix_id, versao["id"]),
        ).fetchone()["c"]
        assert matrix_version_link == 1

    reopened = client.get(f"/admin/editar_matriz/{matrix_id}?tab=aac")
    assert reopened.status_code == 200
    assert activity_name in reopened.get_data(as_text=True)


def test_post_new_aeu_activity_creates_aeu_context(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    matrix_id = versioned_env["aeu_matrix_id"]
    activity_name = _unique_name("Matrix AEU")

    response = client.post(
        f"/admin/matrizes/{matrix_id}/atividades/nova/aea",
        data={
            "nome": activity_name,
            "add_to_matrix": "1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with main.app.app_context():
        conn = main.get_db_connection()
        atividade = conn.execute("SELECT * FROM atividades WHERE nome = ?", (activity_name,)).fetchone()
        assert atividade is not None
        assert atividade["tipo_atividade"] == "Extensão Universitária"
        assert atividade["grupo"] == "NA"

        base = conn.execute("SELECT * FROM atividade_base WHERE nome_conceito = ?", (activity_name,)).fetchone()
        assert base is not None

        versao = conn.execute(
            "SELECT * FROM atividade_versao WHERE atividade_base_id = ?",
            (base["id"],),
        ).fetchone()
        assert versao is not None
        assert versao["atividade_base_id"] == base["id"]
        assert versao["norma_id"] == 3
        assert versao["codigo_normativo"] == "AEU-rev1"
        assert versao["eixo"] == "AEU"
        assert versao["grupo"] == "NA"
        assert versao["status"] == "ativa"


def test_post_new_activity_blocks_matrix_without_compatible_norm(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    matrix_id = versioned_env["aac_matrix_id"]
    activity_name = _unique_name("Blocked AEU")

    response = client.post(
        f"/admin/matrizes/{matrix_id}/atividades/nova/aea",
        data={
            "nome": activity_name,
            "add_to_matrix": "1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert "norma ativa de AEU" in html

    with main.app.app_context():
        conn = main.get_db_connection()
        atividade = conn.execute("SELECT id FROM atividades WHERE nome = ?", (activity_name,)).fetchone()
        base = conn.execute("SELECT id FROM atividade_base WHERE nome_conceito = ?", (activity_name,)).fetchone()
    assert atividade is None
    assert base is None


def test_post_new_activity_requires_explicit_norm_when_multiple_compatible_norms(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    matrix_id = versioned_env["aac_matrix_id"]
    activity_name = _unique_name("Multiple AAC")

    with main.app.app_context():
        conn = main.get_db_connection()
        norma_id = conn.execute(
            """
            INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)
            VALUES (?, 'AAC', 'rev-extra', ?, 'ativa')
            """,
            (_unique_name("AAC-rev-extra"), "Norma AAC extra"),
        ).lastrowid
        conn.execute("INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)", (matrix_id, norma_id))
        conn.commit()

    response = client.post(
        f"/admin/matrizes/{matrix_id}/atividades/nova/aac",
        data={
            "nome": activity_name,
            "grupo_numero": "9",
            "grupo_descricao": "Precisa escolher norma",
            "add_to_matrix": "1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Selecione explicitamente a norma/regulamento base" in response.get_data(as_text=True)

    with main.app.app_context():
        conn = main.get_db_connection()
        atividade = conn.execute("SELECT id FROM atividades WHERE nome = ?", (activity_name,)).fetchone()
        base = conn.execute("SELECT id FROM atividade_base WHERE nome_conceito = ?", (activity_name,)).fetchone()
    assert atividade is None
    assert base is None


def test_post_new_activity_rolls_back_on_intermediate_error(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    matrix_id = versioned_env["aac_matrix_id"]
    activity_name = _unique_name("Rollback AAC")

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, 'Base preexistente', 'ativo')",
            (activity_name,),
        )
        conn.commit()
        before_counts = _table_counts(conn)

    response = client.post(
        f"/admin/matrizes/{matrix_id}/atividades/nova/aac",
        data={
            "nome": activity_name,
            "grupo_numero": "10",
            "grupo_descricao": "Conflito base",
            "add_to_matrix": "1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Já existe atividade-base com este nome." in response.get_data(as_text=True)

    with main.app.app_context():
        conn = main.get_db_connection()
        after_counts = _table_counts(conn)
        atividade = conn.execute("SELECT id FROM atividades WHERE nome = ?", (activity_name,)).fetchone()
        version_rows = conn.execute(
            """
            SELECT COUNT(*) AS c
              FROM atividade_versao av
              JOIN atividade_base ab ON ab.id = av.atividade_base_id
             WHERE ab.nome_conceito = ?
            """,
            (activity_name,),
        ).fetchone()["c"]
    assert after_counts == before_counts
    assert atividade is None
    assert version_rows == 0


def test_modal_form_contains_csrf_and_post_requires_it(versioned_env_csrf):
    client = versioned_env_csrf["client"]
    _login_admin(client)
    matrix_id = versioned_env_csrf["aac_matrix_id"]

    page = client.get(f"/admin/editar_matriz/{matrix_id}?tab=aac")
    assert page.status_code == 200

    form_html = _extract_modal_form(page.get_data(as_text=True))
    csrf_token = _extract_csrf_token(form_html)
    activity_name = _unique_name("CSRF AAC")

    missing = client.post(
        f"/admin/matrizes/{matrix_id}/atividades/nova/aac",
        data={
            "nome": activity_name,
            "grupo_numero": "11",
            "grupo_descricao": "CSRF test",
            "add_to_matrix": "1",
        },
        follow_redirects=False,
    )
    assert missing.status_code == 400

    created = client.post(
        f"/admin/matrizes/{matrix_id}/atividades/nova/aac",
        data={
            "nome": activity_name,
            "grupo_numero": "11",
            "grupo_descricao": "CSRF test",
            "add_to_matrix": "1",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert created.status_code in (302, 303)
    assert f"/admin/editar_matriz/{matrix_id}?tab=aac" in (created.headers.get("Location") or "")

    with main.app.app_context():
        conn = main.get_db_connection()
        atividade = conn.execute("SELECT id FROM atividades WHERE nome = ?", (activity_name,)).fetchone()
    assert atividade is not None
