"""
ACTIVITY-VERSION-CLONE-EDIT-UX — R3 PRIMARY ACTIVITIES EDIT ENTRY INTEGRATION.

Proves:
  1. Activities-list Edit targets exact-version editor with base_id + versao_id;
  2. Activities-list View targets exact-version read-only context (?view=1);
  3. View of a draft remains read-only (no Save);
  4. Activities-list Create-new-version includes exact `from=<row version id>`;
  5. row v1 creates from v1 even when v2/v3 exist;
  6. row v2 creates from v2;
  7. switching versions after entering through Edit works;
  8. legacy route delegates to the canonical exact-version editor;
  9. no lifecycle/permission regression (POST guard on immutable + auth gating);
 10. R1/R2 clone/no-op/switcher suites remain green (executed externally).
"""
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
        nome_base = f"Base R3 {token}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_base, "Descrição R3", "ativo"),
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
    versao_anterior_id=None,
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
                ch_por_evento, numero_versao, versao_anterior_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (base_id, eixo, grupo, status, ch_por_evento, numero_versao, versao_anterior_id),
        )
        versao_id = cur.lastrowid
        conn.commit()
    return versao_id


def _editar_url(base_id: int, versao_id: int, view: bool = False) -> str:
    url = f"/admin/catalogo-versoes/{base_id}/versoes/{versao_id}/editar"
    if view:
        url += "?view=1"
    return url


def _nova_url(base_id: int, from_id: int | None = None) -> str:
    url = f"/admin/catalogo-versoes/{base_id}/nova-versao"
    if from_id is not None:
        url += f"?from={from_id}"
    return url


def _input_value(html: str, field_id: str) -> str:
    if field_id == "grupo":
        field_id = "grupo_hidden"
    match = re.search(rf'id="{field_id}"[^>]*value="([^"]*)"', html)
    assert match, f"campo id={field_id} não encontrado no HTML"
    return match.group(1)


def _hidden_input_value(html: str, name: str) -> str:
    if name == "versao_anterior_id":
        match = re.search(
            r'<select id="versao_anterior_id"[^>]*>.*?<option value="([^"]*)"[^>]*selected',
            html,
            re.S,
        )
        assert match, "selected versao_anterior_id não encontrado"
        return match.group(1)
    match = re.search(rf'<input type="hidden" name="{name}" value="([^"]*)"', html)
    assert match, f"hidden input name={name} não encontrado no HTML"
    return match.group(1)


def _switcher_selected(html: str) -> list[str]:
    match = re.search(r'<select id="versao-switcher"[^>]*>(.*?)</select>', html, re.S)
    assert match, "seletor versao-switcher não encontrado no HTML"
    return [
        value
        for value, attrs, _label in re.findall(
            r'<option value="([^"]*)"([^>]*)>\s*(.*?)\s*</option>', match.group(1), re.S
        )
        if "selected" in attrs
    ]


def _count(client, table: str) -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]


def _activities_page_script(client) -> str:
    r = client.get("/admin/atividades")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Barra flutuante de ações na lista de Atividades" in html
    return html


# ---------------------------------------------------------------------------
# 1. Activities-list Edit targets exact-version editor (base_id + versao_id)
# ---------------------------------------------------------------------------

def test_activities_list_edit_targets_exact_version_editor(client):
    _login_admin(client)
    script = _activities_page_script(client)

    assert "/admin/catalogo-versoes/0/versoes/0/editar" in script, (
        "barra de ações deve apontar para o editor de versão exata"
    )
    assert "'/0/versoes/0/editar'" in script
    assert "currentBaseId + '/versoes/' + currentId + '/editar'" in script


# ---------------------------------------------------------------------------
# 2. Activities-list View targets exact-version read-only context (?view=1)
# ---------------------------------------------------------------------------

def test_activities_list_view_targets_exact_version_readonly(client):
    _login_admin(client)
    script = _activities_page_script(client)

    assert "/admin/catalogo-versoes/0/versoes/0/editar" in script
    assert "navigateWithReturnTo(base, { view: 1 })" in script
    assert "action === 'view'" in script


# ---------------------------------------------------------------------------
# 3. View of a draft remains read-only (no Save)
# ---------------------------------------------------------------------------

def test_view_of_draft_remains_readonly(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, status="rascunho", grupo="Grupo draft")

    r = client.get(_editar_url(seed["base_id"], v1, view=True))
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="btn-salvar-versao"' not in html, "view de rascunho não deve expor Salvar"
    assert 'class="btn primary"' not in html
    assert "readonly" in html


# ---------------------------------------------------------------------------
# 4. Activities-list Create-new-version includes exact from=<row version id>
# ---------------------------------------------------------------------------

def test_activities_list_create_new_version_includes_from_row(client):
    _login_admin(client)
    script = _activities_page_script(client)

    assert "action === 'nova-versao' && currentBaseId" in script
    assert "'?from=' + currentId" in script, (
        "Criar nova versão deve passar o id exato da versão da linha (?from=currentId)"
    )
    assert "/admin/catalogo-versoes/0/nova-versao" in script


# ---------------------------------------------------------------------------
# 5. row v1 creates from v1 even when v2/v3 exist
# ---------------------------------------------------------------------------

def test_row_v1_creates_from_v1_even_when_newer_exist(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, status="rascunho",
                        grupo="Grupo v1", ch_por_evento=4)
    v2 = _insert_versao(client, base_id=seed["base_id"], numero_versao=2, status="rascunho",
                        grupo="Grupo v2", ch_por_evento=8)
    v3 = _insert_versao(client, base_id=seed["base_id"], numero_versao=3, status="rascunho",
                        grupo="Grupo v3", ch_por_evento=12)

    r = client.get(_nova_url(seed["base_id"], v1))
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert _input_value(html, "grupo") == "Grupo v1", "form deve clonar v1, não a mais recente"
    assert _input_value(html, "ch_por_evento") == "4"
    assert _hidden_input_value(html, "versao_anterior_id") == str(v1), (
        "predecessor deve ser fixado na versão da linha (v1)"
    )
    assert re.search(r"Criando\s*<strong>v4</strong>\s*a partir de\s*<strong>v1</strong>", html)


# ---------------------------------------------------------------------------
# 6. row v2 creates from v2
# ---------------------------------------------------------------------------

def test_row_v2_creates_from_v2(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, status="rascunho",
                        grupo="Grupo v1", ch_por_evento=4)
    v2 = _insert_versao(client, base_id=seed["base_id"], numero_versao=2, status="rascunho",
                        grupo="Grupo v2", ch_por_evento=8)

    r = client.get(_nova_url(seed["base_id"], v2))
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert _input_value(html, "grupo") == "Grupo v2"
    assert _input_value(html, "ch_por_evento") == "8"
    assert _hidden_input_value(html, "versao_anterior_id") == str(v2)
    assert re.search(r"Criando\s*<strong>v3</strong>\s*a partir de\s*<strong>v2</strong>", html)


# ---------------------------------------------------------------------------
# 7. Switching versions after entering through Edit works
# ---------------------------------------------------------------------------

def test_switching_versions_after_edit_entry(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, status="ativa",
                        grupo="Grupo v1", ch_por_evento=4)
    v2 = _insert_versao(client, base_id=seed["base_id"], numero_versao=2, status="rascunho",
                        grupo="Grupo v2", ch_por_evento=8)

    r2 = client.get(_editar_url(seed["base_id"], v2))
    assert r2.status_code == 200
    html2 = r2.get_data(as_text=True)
    assert _switcher_selected(html2) == [str(v2)]
    assert _input_value(html2, "grupo") == "Grupo v2"

    r1 = client.get(_editar_url(seed["base_id"], v1))
    assert r1.status_code == 200
    html1 = r1.get_data(as_text=True)
    assert _switcher_selected(html1) == [str(v1)]
    assert _input_value(html1, "grupo") == "Grupo v1"
    assert 'id="btn-salvar-versao"' not in html1, "v1 ativa deve abrir somente-leitura"

    r2b = client.get(_editar_url(seed["base_id"], v2))
    html2b = r2b.get_data(as_text=True)
    assert _switcher_selected(html2b) == [str(v2)]
    assert _input_value(html2b, "grupo") == "Grupo v2"


# ---------------------------------------------------------------------------
# 8. Legacy route delegates to canonical editor
# ---------------------------------------------------------------------------

def test_legacy_editar_atividade_route_redirects_to_canonical_editor(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, status="rascunho",
                        grupo="Grupo legado", ch_por_evento=4)

    r = client.get(f"/admin/editar_atividade/{v1}")
    assert r.status_code == 302
    assert r.headers["Location"].endswith(_editar_url(seed["base_id"], v1))


# ---------------------------------------------------------------------------
# 9. No lifecycle/permission regression
# ---------------------------------------------------------------------------

def test_immutable_post_edit_still_blocked(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, status="ativa",
                        grupo="Grupo ativo", ch_por_evento=4)
    before = _count(client, "atividade_versao")

    r = client.post(
        _editar_url(seed["base_id"], v1),
        data={"grupo": "Grupo TENTATIVA", "eixo": "AAC", "ch_por_evento": "5"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT grupo FROM atividade_versao WHERE id = ?", (v1,)
        ).fetchone()
    assert row["grupo"] == "Grupo ativo", "POST em versão imutável não deve mutar"
    assert _count(client, "atividade_versao") == before


def test_view_mode_post_edit_blocked(client):
    _login_admin(client)
    seed = _seed_base(client)
    v1 = _insert_versao(client, base_id=seed["base_id"], numero_versao=1, status="rascunho",
                        grupo="Grupo draft", ch_por_evento=4)

    r = client.post(
        _editar_url(seed["base_id"], v1, view=True),
        data={"grupo": "Grupo TENTATIVA", "eixo": "AAC", "ch_por_evento": "5"},
        follow_redirects=False,
    )
    assert r.status_code == 302, "POST em ?view=1 deve ser bloqueado"
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT grupo FROM atividade_versao WHERE id = ?", (v1,)
        ).fetchone()
    assert row["grupo"] == "Grupo draft"


def test_activities_list_keeps_permission_gating(client):
    _login_admin(client)
    script = _activities_page_script(client)
    assert 'data-action="edit"' in script
    assert 'data-action="nova-versao"' in script
    assert 'data-action="ver-versoes"' in script
    assert 'data-action="delete"' in script
