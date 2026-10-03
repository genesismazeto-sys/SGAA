"""Canonical activity version sequence: N+1 creation and truthful lineage UI."""
from __future__ import annotations

import re

import pytest

import main
from tests.canonical_request_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "version-sequence.db") as value:
        yield value


def _versions(base_id):
    with main.app.app_context():
        return [
            dict(row)
            for row in main.get_db_connection().execute(
                "SELECT id, numero_versao, versao_anterior_id, status"
                " FROM atividade_versao WHERE atividade_base_id=?"
                " ORDER BY numero_versao, id",
                (base_id,),
            ).fetchall()
        ]


def _post_new_version(client, base_id, source_id, *, grupo, observacoes):
    with main.app.app_context():
        base = main.get_db_connection().execute(
            "SELECT nome_conceito, descricao FROM atividade_base WHERE id=?", (base_id,)
        ).fetchone()
    return client.post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao",
        data={
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": grupo,
            "nome": base["nome_conceito"],
            "descricao": base["descricao"] or "",
            "ch_por_evento_mode": "enabled",
            "ch_por_evento": "4",
            "tipo_limitacao": "semestral",
            "limite_valor": "30",
            "observacoes": observacoes,
            "versao_anterior_id": str(source_id),
        },
        follow_redirects=False,
    )


def test_created_version_continues_the_surviving_sequence(env):
    client = env["client"]
    login_admin(client)

    # One surviving version: create => v2.
    one = _versions(26)
    assert [v["numero_versao"] for v in one] == [1]
    assert _post_new_version(
        client, 26, one[-1]["id"], grupo="1 - Sequência A", observacoes="Sequência A"
    ).status_code == 302
    after_one = _versions(26)
    assert [v["numero_versao"] for v in after_one] == [1, 2]
    assert after_one[-1]["versao_anterior_id"] == one[-1]["id"]
    assert after_one[-1]["status"] == "rascunho"

    # Two surviving versions: create => v3.
    two = _versions(1)
    assert [v["numero_versao"] for v in two] == [1, 2]
    assert _post_new_version(
        client, 1, two[-1]["id"], grupo="1 - Sequência B", observacoes="Sequência B"
    ).status_code == 302
    after_two = _versions(1)
    assert [v["numero_versao"] for v in after_two] == [1, 2, 3]
    assert after_two[-1]["versao_anterior_id"] == two[-1]["id"]

    # Three surviving versions: create => v4.
    assert _post_new_version(
        client, 1, after_two[-1]["id"], grupo="1 - Sequência C", observacoes="Sequência C"
    ).status_code == 302
    final = _versions(1)
    assert [v["numero_versao"] for v in final] == [1, 2, 3, 4]
    assert final[-1]["versao_anterior_id"] == after_two[-1]["id"]


def test_next_number_derives_from_survivors_never_from_deleted_rows(env):
    client = env["client"]
    login_admin(client)

    baseline = _versions(1)
    assert [v["numero_versao"] for v in baseline] == [1, 2]
    assert _post_new_version(
        client, 1, baseline[-1]["id"], grupo="1 - Descartável", observacoes="Descartável"
    ).status_code == 302
    draft = _versions(1)[-1]
    assert draft["numero_versao"] == 3
    assert client.post(
        f"/admin/catalogo-versoes/1/versoes/{draft['id']}/excluir",
        follow_redirects=True,
    ).status_code == 200
    assert [v["numero_versao"] for v in _versions(1)] == [1, 2]

    assert _post_new_version(
        client, 1, baseline[-1]["id"], grupo="1 - Reuso", observacoes="Reuso"
    ).status_code == 302
    assert [v["numero_versao"] for v in _versions(1)] == [1, 2, 3]


def test_catalogue_lineage_shows_predecessor_chain_without_fabricating_events(env):
    client = env["client"]
    login_admin(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        first = conn.execute(
            "SELECT id FROM atividade_versao WHERE atividade_base_id=1 AND numero_versao=1"
        ).fetchone()["id"]
        conn.execute(
            "UPDATE atividade_versao SET versao_anterior_id=?"
            " WHERE atividade_base_id=1 AND numero_versao=2",
            (first,),
        )
        conn.commit()

    html = client.get("/admin/catalogo-versoes/1").get_data(as_text=True)

    assert "Linhagem de versões" in html
    chain_blocks = re.findall(
        r'<li class="version-lineage-chain">(.*?)</li>', html, re.S
    )
    assert len(chain_blocks) == 1
    identifiers = re.findall(r">v(\d+)<", chain_blocks[0])
    assert identifiers == ["1", "2"]
    assert "&rarr;" in chain_blocks[0]
    # Version lineage is real; lifecycle/transition audit remains empty, not invented.
    assert "Nenhuma transição registrada." in html
