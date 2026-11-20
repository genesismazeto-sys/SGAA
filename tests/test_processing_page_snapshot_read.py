"""The standalone Processar Requisição page reads the request's frozen record (O1).

``admin_processar_requisicao`` passes the owner's verdict,
``_build_admin_requisicao_snapshot_diagnostic`` -> ``{status, reason, payload}``.
The template still asked for the flat keys the builder returned before the
prod-1 baseline (``diagnostico_disponivel`` ...), so every request -- valid
snapshot or not -- read "Registro da solicitação presente, mas leitura
indisponível.". The page now reads the validated payload; the two fallbacks keep
their meaning (unreadable record / no record). Authorization is unchanged: the
page needs ``requisicoes.edit``, a view-only Consultor is refused, and a GET
writes nothing.
"""

from __future__ import annotations

import json
import re
import uuid

import pytest

import main
from app.user_accounts import create_usuario_with_access_level
from app.views.admin import requisicoes as requisicoes_view
from tests.canonical_request_test_support import create_admin_request, login_admin
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

UNREADABLE = "Registro da solicitação presente, mas leitura indisponível."
NO_RECORD = "Sem registro de versão para esta requisição."
FIELDS = ("atividade_versao_id", "eixo", "grupo", "ch_por_evento", "limite_semestre", "limite_total",
          "flow_origin", "snapshot_written_at")


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "o1-processing-read.db") as environment:
        client = environment["client"]
        login_admin(client)
        _response, created = create_admin_request(client, name=f"O1 {uuid.uuid4().hex[:6]}")
        yield client, created


def _record_block(html: str) -> str:
    start = html.index("Registro da solicitação</div>")
    return html[start:html.index('<form method="post"', start)]


def _pairs(block: str) -> dict[str, str]:
    return {
        key: value.strip()
        for key, value in re.findall(r'<span class="help">([a-z_]+)</span><div>(.*?)</div>', block, re.S)
    }


def _all_rows() -> list[tuple]:
    with main.app.app_context():
        conn = main.get_db_connection()
        return [tuple(r) for r in conn.execute("SELECT * FROM requisicoes ORDER BY id")] + [
            tuple(r) for r in conn.execute("SELECT * FROM requisicao_email_eventos ORDER BY id")
        ]


def test_a_valid_request_shows_its_frozen_record(env):
    client, created = env
    stored = json.loads(created["regra_snapshot_json"])
    before = _all_rows()

    response = client.get(f"/admin/processar_requisicao/{created['id']}")

    assert response.status_code == 200
    block = _record_block(response.get_data(as_text=True))
    assert UNREADABLE not in block and NO_RECORD not in block
    pairs = _pairs(block)
    # The values come from the frozen payload: flow_origin and the write time
    # exist nowhere but in the snapshot. An absent limit (None) is not listed.
    assert pairs == {key: str(stored[key]) for key in FIELDS if stored.get(key) is not None}
    assert pairs["flow_origin"] == "admin_create" and pairs["snapshot_written_at"]
    assert _all_rows() == before


def test_the_optional_comparison_shows_the_frozen_name(env, monkeypatch):
    client, created = env
    stored = json.loads(created["regra_snapshot_json"])
    html = client.get(f"/admin/processar_requisicao/{created['id']}").get_data(as_text=True)
    assert "Versão registrada" not in html  # off by default
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", "1")
    block = _record_block(client.get(f"/admin/processar_requisicao/{created['id']}").get_data(as_text=True))
    recorded = block[block.index("Versão registrada"):]
    assert re.search(r'Nome no momento da solicitação</span><div>\s*' + re.escape(stored["nome_exibivel"]), recorded)


def test_an_unreadable_record_says_so_and_shows_no_field(env):
    client, created = env
    with main.app.app_context():
        conn = main.get_db_connection()
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(requisicoes)") if row["name"] != "id"]
        select = ", ".join("?" if c == "regra_snapshot_json" else c for c in columns)
        payload = json.loads(created["regra_snapshot_json"])
        payload["schema_version"] = "unsupported"
        cursor = conn.execute(
            f"INSERT INTO requisicoes ({', '.join(columns)}) SELECT {select} FROM requisicoes WHERE id=?",
            (json.dumps(payload), created["id"]),
        )
        conn.commit()
        broken_id = cursor.lastrowid

    response = client.get(f"/admin/processar_requisicao/{broken_id}")

    assert response.status_code == 200
    block = _record_block(response.get_data(as_text=True))
    assert UNREADABLE in block
    assert _pairs(block) == {}


def test_a_missing_record_keeps_its_own_message(env, monkeypatch):
    # Unreachable from a prod-1 row (NOT NULL json object), but the verdict
    # exists, so its message must not read as "present but unreadable".
    client, created = env
    monkeypatch.setattr(
        requisicoes_view, "_build_admin_requisicao_snapshot_diagnostic",
        lambda _row: {"status": "invalid", "reason": "mandatory_snapshot_missing", "payload": None},
    )
    block = _record_block(client.get(f"/admin/processar_requisicao/{created['id']}").get_data(as_text=True))
    assert NO_RECORD in block and UNREADABLE not in block


def test_a_view_only_consultor_is_still_refused(env):
    client, created = env
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = int(create_usuario_with_access_level(
            conn, f"O1 viewer {token}", f"o1-viewer-{token}@example.invalid",
            main.hash_password("o1"), "admin", "consultivo", credential_state="personal",
        ).lastrowid)
        conn.commit()
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=uid, user_type="admin", user_name="O1 viewer")
        stamp_auth_version(session, uid)
    before = _all_rows()

    response = client.get(f"/admin/processar_requisicao/{created['id']}")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/dashboard")
    assert client.get(f"/admin/requisicao/{created['id']}").status_code == 200
    assert _all_rows() == before
