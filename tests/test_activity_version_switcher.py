"""
ACTIVITY-VERSION-CLONE-EDIT-UX — R2 VERSION SWITCHER focused coverage.

Proves:
  1. exact-version edit/view screen receives all versions of the same base;
  2. current version is selected;
  3. versions are ordered by numero_versao;
  4. switching v1 -> v2 targets exact v2;
  5. switching v2 -> v1 targets exact v1;
  6. draft version opens editable;
  7. immutable/non-editable version opens read-only;
  8. navigation itself creates no database mutation;
  9. version selector never exposes versions from another atividade_base;
 10. Create new version from selected vN clones that exact vN;
 11. existing dirty-state/no-op clone contract remains green.
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main


@pytest.fixture()
def client():
    app = main.app
    with app.app_context():
        main.init_db()
        yield app.test_client()


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def _seed_base(client) -> dict:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        nome_base = f"Base Switcher {token}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_base, "Descrição Switcher", "ativo"),
        )
        base_id = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?",
            (nome_base,),
        ).fetchone()["id"]
        conn.commit()
    return {"base_id": base_id}


def _insert_versao(
    client,
    *,
    base_id: int,
    eixo: str = "AAC",
    numero_versao: int | None = None,
    status: str = "rascunho",
    grupo: str | None = None,
    ch_por_evento=None,
) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        if numero_versao is None:
            numero_versao = conn.execute(
                "SELECT COALESCE(MAX(numero_versao), 0) + 1 FROM atividade_versao"
                " WHERE atividade_base_id = ?",
                (base_id,),
            ).fetchone()[0]
        cur = conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, eixo, grupo, status,
                ch_por_evento, numero_versao
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (base_id, eixo, grupo, status, ch_por_evento, numero_versao),
        )
        versao_id = cur.lastrowid
        conn.commit()
    return versao_id


def _editar_url(base_id: int, versao_id: int) -> str:
    return f"/admin/catalogo-versoes/{base_id}/versoes/{versao_id}/editar"


def _switcher_options(html: str) -> list[tuple[str, str, str]]:
    """Retorna [(option_value, label, selected_bool)] do seletor de versões."""
    match = re.search(r'<select id="versao-switcher"[^>]*>(.*?)</select>', html, re.S)
    assert match, "seletor versao-switcher não encontrado no HTML"
    return re.findall(
        r'<option value="([^"]*)"([^>]*)>\s*(.*?)\s*</option>', match.group(1), re.S
    )


def _switcher_option_values(html: str) -> list[str]:
    return [value for value, _attrs, _label in _switcher_options(html)]


def _switcher_selected(html: str) -> list[str]:
    return [
        value
        for value, attrs, _label in _switcher_options(html)
        if "selected" in attrs
    ]


def _switcher_labels(html: str) -> list[str]:
    return [label.strip() for _v, _a, label in _switcher_options(html)]


def _input_value(html: str, field_id: str) -> str:
    if field_id == "grupo":
        field_id = "grupo_hidden"
    match = re.search(rf'id="{field_id}"[^>]*value="([^"]*)"', html)
    assert match, f"campo id={field_id} não encontrado no HTML"
    return match.group(1)


def _textarea_value(html: str, field_id: str) -> str:
    match = re.search(rf'id="{field_id}"[^>]*>([^<]*)</textarea>', html)
    assert match, f"textarea id={field_id} não encontrado no HTML"
    return match.group(1)


def _snapshot_json(html: str) -> dict:
    match = re.search(
        r'<script id="versao-form-snapshot" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    assert match, "snapshot de clone não encontrado no HTML"
    return json.loads(match.group(1))


def _db_fingerprint() -> str:
    with main.app.app_context():
        rows = main.get_db_connection().execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(id),0) AS s FROM atividade_versao"
        ).fetchone()
        return f"{rows['n']}:{rows['s']}"


def _post_nova_versao(client, base_id: int, data: dict):
    with main.app.app_context():
        conn = main.get_db_connection()
        base = conn.execute("SELECT nome_conceito,descricao FROM atividade_base WHERE id=?", (base_id,)).fetchone()
        predecessor = conn.execute(
            "SELECT * FROM atividade_versao WHERE id=?", (data.get("versao_anterior_id"),)
        ).fetchone() if data.get("versao_anterior_id") else None
    eixo = data.get("eixo", predecessor["eixo"] if predecessor else "AAC")
    payload = {
        "tipo_atividade": "Extensão Universitária" if eixo == "AEU" else "Acadêmica Complementar",
        "grupo": data.get("grupo", predecessor["grupo"] if predecessor else ""),
        "nome": base["nome_conceito"],
        "descricao": base["descricao"] or "",
        "ch_por_evento": data.get("ch_por_evento", predecessor["ch_por_evento"] if predecessor else ""),
        "tipo_limitacao": "",
        "limite_valor": "",
        "observacoes": "",
        "versao_anterior_id": data.get("versao_anterior_id", ""),
    }
    return client.post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao",
        data=payload,
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# 1. Edit/view screen receives all versions of the same base
# ---------------------------------------------------------------------------

def test_edit_view_screen_lists_all_same_base_versions(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, grupo="v1")
    v2 = _insert_versao(client, base_id=seed["base_id"], numero_versao=2, grupo="v2")
    v3 = _insert_versao(client, base_id=seed["base_id"], numero_versao=3, grupo="v3")

    r = client.get(_editar_url(seed["base_id"], v2))
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    values = _switcher_option_values(html)
    assert set(values) == {str(v1), str(v2), str(v3)}


# ---------------------------------------------------------------------------
# 2. Current version is selected
# ---------------------------------------------------------------------------

def test_current_version_is_selected(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1)
    v2 = _insert_versao(client, base_id=seed["base_id"], numero_versao=2)
    v3 = _insert_versao(client, base_id=seed["base_id"], numero_versao=3)

    r2 = client.get(_editar_url(seed["base_id"], v2))
    assert _switcher_selected(r2.get_data(as_text=True)) == [str(v2)]

    r3 = client.get(_editar_url(seed["base_id"], v3))
    assert _switcher_selected(r3.get_data(as_text=True)) == [str(v3)]


# ---------------------------------------------------------------------------
# 3. Versions ordered by numero_versao
# ---------------------------------------------------------------------------

def test_switcher_ordered_by_numero_versao(client):
    _login_admin(client)
    seed = _seed_base(client)
    _insert_versao(client, base_id=seed["base_id"], numero_versao=10, grupo="v10")
    _insert_versao(client, base_id=seed["base_id"], numero_versao=2, grupo="v2")
    _insert_versao(client, base_id=seed["base_id"], numero_versao=1, grupo="v1")

    r = client.get(_editar_url(seed["base_id"], 0))
    # editar com id inexistente redireciona; obtenha a primeira versão real
    with main.app.app_context():
        ids = [
            row["id"]
            for row in main.get_db_connection().execute(
                "SELECT id FROM atividade_versao WHERE atividade_base_id = ?"
                " ORDER BY numero_versao, id",
                (seed["base_id"],),
            ).fetchall()
        ]
    r = client.get(_editar_url(seed["base_id"], ids[0]))
    html = r.get_data(as_text=True)
    values = _switcher_option_values(html)
    assert values == [str(i) for i in ids], (
        f"ordem do seletor deve seguir numero_versao, obtido {values}"
    )
    labels = _switcher_labels(html)
    assert labels[0].startswith("v1")
    assert labels[1].startswith("v2")
    assert labels[2].startswith("v10")


# ---------------------------------------------------------------------------
# 4. Switching v1 -> v2 targets exact v2
# ---------------------------------------------------------------------------

def test_switch_v1_to_v2_targets_exact_v2(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, grupo="Grupo v1", ch_por_evento=4)
    v2 = _insert_versao(client, base_id=seed["base_id"], numero_versao=2, grupo="Grupo v2", ch_por_evento=8)

    r_v1 = client.get(_editar_url(seed["base_id"], v1))
    assert _input_value(r_v1.get_data(as_text=True), "grupo") == "Grupo v1"

    r_v2 = client.get(_editar_url(seed["base_id"], v2))
    html_v2 = r_v2.get_data(as_text=True)
    assert _switcher_selected(html_v2) == [str(v2)]
    assert _input_value(html_v2, "grupo") == "Grupo v2"
    assert _input_value(html_v2, "ch_por_evento") == "8"


# ---------------------------------------------------------------------------
# 5. Switching v2 -> v1 targets exact v1
# ---------------------------------------------------------------------------

def test_switch_v2_to_v1_targets_exact_v1(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, grupo="Grupo v1", ch_por_evento=4)
    v2 = _insert_versao(client, base_id=seed["base_id"], numero_versao=2, grupo="Grupo v2", ch_por_evento=8)

    r_v2 = client.get(_editar_url(seed["base_id"], v2))
    assert _input_value(r_v2.get_data(as_text=True), "grupo") == "Grupo v2"

    r_v1 = client.get(_editar_url(seed["base_id"], v1))
    html_v1 = r_v1.get_data(as_text=True)
    assert _switcher_selected(html_v1) == [str(v1)]
    assert _input_value(html_v1, "grupo") == "Grupo v1"
    assert _input_value(html_v1, "ch_por_evento") == "4"


# ---------------------------------------------------------------------------
# 6. Draft version opens editable
# ---------------------------------------------------------------------------

def test_draft_version_opens_editable(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, status="rascunho")

    r = client.get(_editar_url(seed["base_id"], v1))
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="btn-salvar-versao"' in html
    assert 'class="btn primary"' in html
    assert "Salvar alterações" in html
    assert 'id="versao-switcher"' in html


# ---------------------------------------------------------------------------
# 7. Immutable/non-editable version opens read-only
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["ativa", "inativa", "descontinuada", "substituida"])
def test_immutable_version_opens_readonly(client, status):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, status=status, grupo="Grupo v1")

    r = client.get(_editar_url(seed["base_id"], v1))
    assert r.status_code == 200, f"status={status} deveria abrir somente-leitura"
    html = r.get_data(as_text=True)
    assert 'id="btn-salvar-versao"' not in html, f"status={status} não deve ter Salvar"
    assert 'class="btn primary"' not in html, f"status={status} não deve ter botão primário"
    assert 'name="grupo"' in html
    assert 'readonly' in html


# ---------------------------------------------------------------------------
# 8. Navigation creates no database mutation
# ---------------------------------------------------------------------------

def test_switcher_navigation_no_db_mutation(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, status="rascunho")
    v2 = _insert_versao(client, base_id=seed["base_id"], numero_versao=2, status="rascunho")
    v3 = _insert_versao(client, base_id=seed["base_id"], numero_versao=3, status="ativa")

    before = _db_fingerprint()
    for versao_id in (v1, v2, v3, v1):
        r = client.get(_editar_url(seed["base_id"], versao_id))
        assert r.status_code == 200
    assert _db_fingerprint() == before, "navegar entre versões não deve mutar o banco"


# ---------------------------------------------------------------------------
# 9. Selector never exposes versions from another atividade_base
# ---------------------------------------------------------------------------

def test_switcher_excludes_other_base_versions(client):
    _login_admin(client)
    base_a = _seed_base(client)
    base_b = _seed_base(client)
    a1 = _insert_versao(client, base_id=base_a["base_id"], numero_versao=1)
    a2 = _insert_versao(client, base_id=base_a["base_id"], numero_versao=2)
    b1 = _insert_versao(client, base_id=base_b["base_id"], numero_versao=1)
    b2 = _insert_versao(client, base_id=base_b["base_id"], numero_versao=2)

    r = client.get(_editar_url(base_a["base_id"], a1))
    html = r.get_data(as_text=True)
    values = _switcher_option_values(html)
    assert str(b1) not in values
    assert str(b2) not in values
    assert str(a2) in values


# ---------------------------------------------------------------------------
# 10. Create new version from selected vN clones that exact vN
# ---------------------------------------------------------------------------

def test_create_new_version_from_selected_v2_clones_v2(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(
        client, base_id=seed["base_id"], numero_versao=1, status="ativa",
        grupo="Grupo v1", ch_por_evento=4,
    )
    v2 = _insert_versao(
        client, base_id=seed["base_id"], numero_versao=2, status="rascunho",
        grupo="Grupo v2", ch_por_evento=8,
    )

    # A partir da tela de v2, o link "Criar nova versão" aponta para ?from=v2.
    r = client.get(_editar_url(seed["base_id"], v2))
    html = r.get_data(as_text=True)
    nova_versao_href = re.search(r'href="([^"]*nova-versao[^"]*)"', html)
    assert nova_versao_href, "link Criar nova versão ausente"
    assert f"from={v2}" in nova_versao_href.group(1), (
        f"link deve clonar a versão selecionada (v2), obtido {nova_versao_href.group(1)}"
    )

    r_form = client.get(f"/admin/catalogo-versoes/{seed['base_id']}/nova-versao?from={v2}")
    form_html = r_form.get_data(as_text=True)
    snapshot = _snapshot_json(form_html)
    assert snapshot["grupo"] == "Grupo v2"
    assert snapshot["ch_por_evento"] == 8.0

    # Salvar com uma alteração efetiva cria v3 com predecessor v2.
    resp = _post_nova_versao(client, seed["base_id"], {
        "eixo": "AAC",
        "grupo": "Grupo v2 atualizado",
        "ch_por_evento": "8",
        "versao_anterior_id": str(v2),
    })
    assert resp.status_code == 302
    with main.app.app_context():
        v3 = main.get_db_connection().execute(
            "SELECT numero_versao, versao_anterior_id, status, grupo"
            " FROM atividade_versao WHERE atividade_base_id = ? AND id != ? AND id != ?"
            " ORDER BY numero_versao DESC LIMIT 1",
            (seed["base_id"], v1, v2),
        ).fetchone()
    assert v3 is not None
    assert v3["numero_versao"] == 3
    assert v3["versao_anterior_id"] == v2
    assert v3["status"] == "rascunho"
    assert v3["grupo"] == "Grupo v2 atualizado"


# ---------------------------------------------------------------------------
# 11. Existing dirty-state / no-op clone contract remains green
# ---------------------------------------------------------------------------

def test_unchanged_clone_post_still_rejected(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(
        client, base_id=seed["base_id"], numero_versao=1, status="rascunho",
        grupo="Grupo v1", ch_por_evento=4,
    )
    before = _db_fingerprint()

    r = _post_nova_versao(client, seed["base_id"], {
        "eixo": "AAC",
        "grupo": "Grupo v1",
        "ch_por_evento": "4",
        "versao_anterior_id": str(v1),
    })
    assert r.status_code == 200
    assert "Nenhuma alteração efetiva" in r.get_data(as_text=True)
    assert _db_fingerprint() == before, "no-op não deve criar v2"

    r2 = _post_nova_versao(client, seed["base_id"], {
        "eixo": "AAC",
        "grupo": "Grupo v1 atualizado",
        "ch_por_evento": "4",
        "versao_anterior_id": str(v1),
    })
    assert r2.status_code == 302
    with main.app.app_context():
        count = main.get_db_connection().execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE atividade_base_id = ?",
            (seed["base_id"],),
        ).fetchone()[0]
    assert count == 2
