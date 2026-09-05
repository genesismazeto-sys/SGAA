from __future__ import annotations

import html as html_module
import re

import pytest

import main
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def versioned_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ds_versions_detail.db") as env:
        yield env


def _login_admin(client):
    with client.session_transaction() as session:
        session["user_id"] = 1
        session["user_type"] = "admin"
        session["user_name"] = "Administrador"


def _seed_detail_scenarios():
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            """
            INSERT INTO atividade_base (nome_conceito, descricao, status)
            VALUES (?, ?, 'ativo')
            """,
            (
                "Atividade com nome deliberadamente longo para validar a composição responsiva do detalhe de versões",
                "Descrição útil da atividade para o resumo administrativo.",
            ),
        ).lastrowid

        versions = [
            ("AAC", "1 - Base", None, None, None, 1, "ativa"),
            ("AEU", "NA", 2, 10, None, 2, "rascunho"),
            ("AAC", "2 - Total", 3.5, None, 40, 3, "inativa"),
            ("AAC", "3 - Encerrada", 1, None, None, 4, "descontinuada"),
            ("AAC", "4 - Substituída", 4, None, None, 5, "substituida"),
        ]
        version_ids = []
        for eixo, grupo, sugestao, limite_semestre, limite_total, numero, status in versions:
            version_ids.append(
                conn.execute(
                    """
                    INSERT INTO atividade_versao (
                        atividade_base_id, eixo, grupo, ch_por_evento,
                        limite_semestre, limite_total, numero_versao, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        base_id,
                        eixo,
                        grupo,
                        sugestao,
                        limite_semestre,
                        limite_total,
                        numero,
                        status,
                    ),
                ).lastrowid
            )

        conn.execute(
            """
            INSERT INTO matriz_atividade_versao_item (
                matriz_id, atividade_base_id, atividade_versao_id
            ) VALUES (1, ?, ?)
            """,
            (base_id, version_ids[0]),
        )
        conn.execute(
            """
            INSERT INTO atividade_transicao (
                from_atividade_versao_id, to_atividade_versao_id,
                tipo_transicao, justificativa, created_at
            ) VALUES (?, ?, 'aac_para_aeu', ?, '2026-08-30 18:30:00')
            """,
            (version_ids[0], version_ids[1], "Mudança de enquadramento aprovada"),
        )
        conn.commit()
        return base_id, version_ids


def test_detail_normalizes_language_values_status_usage_actions_and_exact_source(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    base_id, version_ids = _seed_detail_scenarios()

    response = client.get(f"/admin/catalogo-versoes/{base_id}")

    assert response.status_code == 200
    rendered = html_module.unescape(response.get_data(as_text=True))
    assert 'href="/admin/atividades"' in rendered
    assert '<span class="btn-label">Atividades</span>' in rendered
    assert "Catálogo de versões" not in rendered
    assert "Atividade com nome deliberadamente longo" in rendered
    assert ">Ativo<" not in rendered
    assert ">Eixo<" not in rendered
    assert "Acadêmica Complementar" in rendered
    assert "Extensão Universitária" in rendered
    assert "Sem sugestão" in rendered
    assert "2 h" in rendered
    assert "3.5 h" in rendered
    assert "Sem limitação" in rendered
    assert "Semestral · 10 h" in rendered
    assert "Total · 40 h" in rendered
    for status in ("Ativa", "Rascunho", "Inativa", "Descontinuada", "Substituída"):
        assert f">{status}<" in rendered
    assert re.search(
        r'aria-label="Uso em Matrizes: 1">\s*<i[^>]+></i>\s*1\s*</span>',
        rendered,
    )
    assert "css/components/actions-float.css" in rendered
    assert ">Ações<" not in rendered
    assert rendered.count('class="vc-activate-form"') == 1
    assert rendered.count('class="vc-lifecycle-form vc-inativar-form"') == 1
    assert rendered.count('class="vc-lifecycle-form vc-descontinuar-form"') == 1
    assert rendered.count('class="vc-substituir-form"') == 1
    assert f"/nova-versao?from={version_ids[-1]}" in rendered


def test_detail_omits_inactive_base_status_without_hiding_version_statuses(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    base_id, _ = _seed_detail_scenarios()

    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE atividade_base SET status = 'inativo' WHERE id = ?",
            (base_id,),
        )
        conn.commit()

    rendered = html_module.unescape(
        client.get(f"/admin/catalogo-versoes/{base_id}").get_data(as_text=True)
    )

    assert ">Inativo<" not in rendered
    for status in ("Ativa", "Rascunho", "Inativa", "Descontinuada", "Substituída"):
        assert f">{status}<" in rendered


def test_detail_preserves_human_transition_provenance_and_empty_state(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    base_id, _ = _seed_detail_scenarios()

    populated = html_module.unescape(
        client.get(f"/admin/catalogo-versoes/{base_id}").get_data(as_text=True)
    )
    assert "Mudança de Tipo" in populated
    assert "Acadêmica Complementar → Extensão Universitária" in populated
    assert "Mudança de enquadramento aprovada" in populated
    assert "30/08/2026" in populated
    assert "2026-08-30 18:30:00" not in populated

    with main.app.app_context():
        conn = main.get_db_connection()
        empty_base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, status) VALUES (?, 'ativo')",
            ("Atividade sem histórico",),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, eixo, grupo, numero_versao, status
            ) VALUES (?, 'AAC', '1 - Sem histórico', 1, 'rascunho')
            """,
            (empty_base_id,),
        )
        conn.commit()

    empty = client.get(f"/admin/catalogo-versoes/{empty_base_id}").get_data(as_text=True)
    assert "Nenhuma transição registrada" in empty
    assert 'class="table-empty">Nenhuma transição registrada.' in empty


def test_detail_get_is_read_only_for_normalized_scenarios(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    base_id, _ = _seed_detail_scenarios()

    with main.app.app_context():
        conn = main.get_db_connection()
        before = conn.total_changes
        response = client.get(f"/admin/catalogo-versoes/{base_id}")
        after = conn.total_changes

    assert response.status_code == 200
    assert after == before
