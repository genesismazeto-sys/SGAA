"""Request version display: operational badge = linked atividade_versao.numero_versao.

The frozen ``regra_snapshot_json["atividade_versao_numero"]`` is history. It may
appear only under the explicit "Versão da atividade registrada" label.
"""
from __future__ import annotations

import json
import re

import pytest

import main
from tests.canonical_request_test_support import create_admin_request, login_student
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "request-version-display.db") as value:
        yield value


def _insert_request_with_frozen_ordinal(template_row, *, version_id, frozen_number):
    """Insert a request whose frozen snapshot ordinal differs from the catalogue."""
    payload = json.loads(template_row["regra_snapshot_json"])
    payload["atividade_versao_id"] = version_id
    payload["atividade_versao_numero"] = frozen_number
    snapshot = json.dumps(payload, ensure_ascii=False)
    with main.app.app_context():
        conn = main.get_db_connection()
        request_id = conn.execute(
            "INSERT INTO requisicoes(aluno_id,atividade_versao_id,data_solicitacao,data_evento,"
            "horas_solicitadas,status,nome_evento,regra_snapshot_json,turma_id_snapshot,"
            "turma_codigo_snapshot) VALUES(?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (
                template_row["aluno_id"], version_id, template_row["data_solicitacao"],
                template_row["data_evento"], 4, "Pendente", "Frozen snapshot ordinal",
                snapshot, template_row["turma_id_snapshot"], template_row["turma_codigo_snapshot"],
            ),
        ).fetchone()[0]
        conn.commit()
    return request_id, snapshot


def _request(request_id):
    with main.app.app_context():
        return dict(
            main.get_db_connection().execute(
                "SELECT * FROM requisicoes WHERE id=?", (request_id,)
            ).fetchone()
        )


def _canonical_number(version_id):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT numero_versao FROM atividade_versao WHERE id=?", (version_id,)
        ).fetchone()[0]


def _list_chips(html):
    chips = {}
    for block in re.findall(r'data-req-id="(\d+)"(.*?)(?=data-req-id="|\Z)', html, re.S):
        found = re.findall(r'aluno-snapshot-chip"[^>]*>(v\d+)<', block[1])
        chips[int(block[0])] = found
    return chips


@pytest.mark.parametrize(
    "version_id,frozen_number",
    [(2, 3), (29, 4)],
    ids=["canonical-v1-snapshot-v3", "canonical-v2-snapshot-v4"],
)
def test_operational_badge_uses_linked_version_and_snapshot_stays_history(
    env, version_id, frozen_number
):
    client = env["client"]
    from tests.canonical_request_test_support import login_admin

    login_admin(client)
    _, template = create_admin_request(client, "Template request")
    canonical = _canonical_number(version_id)
    assert (canonical, frozen_number) in {(1, 3), (2, 4)}
    request_id, snapshot = _insert_request_with_frozen_ordinal(
        template, version_id=version_id, frozen_number=frozen_number
    )
    before = _request(request_id)

    login_student(client)
    listing = client.get("/aluno/requisicoes").get_data(as_text=True)
    detail = client.get(f"/aluno/requisicoes/{request_id}").get_data(as_text=True)

    # Operational list: the linked version's canonical number, never the frozen one.
    assert _list_chips(listing)[request_id] == [f"v{canonical}"]
    assert f">v{frozen_number}<" not in listing
    assert f"Versão da atividade registrada: v{frozen_number}" not in listing

    # Detail: the frozen ordinal appears only inside the explicit historical card.
    card = re.search(
        r'<div class="content-block-header">Versão da atividade registrada</div>(.*?)</div>\s*</div>',
        detail,
        re.S,
    )
    assert card is not None
    assert f"v{frozen_number}" in card.group(1)
    outside = detail.replace(card.group(0), "")
    assert f"v{frozen_number}" not in outside

    # Nothing was written: snapshot byte-identical, same linked version.
    after = _request(request_id)
    assert after["regra_snapshot_json"] == snapshot == before["regra_snapshot_json"]
    assert after["atividade_versao_id"] == version_id
    assert after == before
    assert _canonical_number(version_id) == canonical
