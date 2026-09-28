"""UI-C08 (Versão): "Editar" is offered only where an in-place edit is real.

Authoritative rule (``app.activity_catalog.can_activity_version_be_mutated_in_place``):
only a *draft* (``rascunho``) that nothing references -- no requisição, no
transition in or out, no successor, not in an assigned Matriz -- can be edited
in place. Every other version is fully locked; the legitimate change is a new
version (successor), a separate action.

UI contract:
* versions hub and Atividades list offer Editar only for such a version and
  Ver otherwise (drafts included);
* a locked version's ``/editar`` renders the Ver page (same pattern as
  ``/visualizar`` and ``?view=1``): no save target, no Save, switcher in Ver;
* from an editable draft's Editar, the switcher opens a locked target in Ver;
* backend refusal of a POST to a locked version is unchanged.
"""

from __future__ import annotations

import re
import uuid

import pytest

import main
from app.activity_catalog import can_activity_version_be_mutated_in_place
from app.user_accounts import create_usuario_with_access_level
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env


def _seed() -> dict[str, int]:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        base = int(conn.execute(
            "INSERT INTO atividade_base(nome_conceito,descricao,status) VALUES (?,?,'ativo')",
            (f"Atividade UI-C08 {token}", "Descrição UI-C08"),
        ).lastrowid)

        def version(number, status, previous=None):
            return int(conn.execute(
                "INSERT INTO atividade_versao(atividade_base_id,eixo,grupo,status,ch_por_evento,numero_versao,versao_anterior_id)"
                " VALUES (?,?,?,?,?,?,?)",
                (base, "AAC", "1 - Grupo UI-C08", status, 2, number, previous),
            ).lastrowid)

        active = version(1, "ativa")
        locked_draft = version(2, "rascunho", active)
        editable_draft = version(3, "rascunho", locked_draft)  # makes v2 a predecessor
        conn.commit()
        assert not can_activity_version_be_mutated_in_place(conn, active)
        assert not can_activity_version_be_mutated_in_place(conn, locked_draft)
        assert can_activity_version_be_mutated_in_place(conn, editable_draft)
    return {"base": base, "active": active, "locked_draft": locked_draft, "editable": editable_draft}


def _editor() -> int:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = int(create_usuario_with_access_level(
            conn, f"UI-C08 {token}", f"ui-c08-{token}@example.invalid",
            main.hash_password("ui-c08"), "admin", "administrativo", credential_state="personal",
        ).lastrowid)
        conn.commit()
    return uid


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c08-versions.db") as environment:
        ids = _seed()
        client = environment["client"]
        uid = _editor()
        with client.session_transaction() as session:
            session.clear()
            session.update(user_id=uid, user_type="admin", user_name="UI-C08")
            stamp_auth_version(session, uid)
        yield client, ids


def _url(ids, which, mode):
    return f"/admin/catalogo-versoes/{ids['base']}/versoes/{ids[which]}/{mode}"


def _form_tag(html: str) -> str:
    start = html.index('autocomplete="off">', html.index("<form"))
    return html[html.rindex("<form", 0, start): start]


def _version_form(html: str) -> str:
    start = html.rindex("<form", 0, html.index('autocomplete="off">', html.index("<form")))
    return html[start: html.index("</form>", start)]


def _switcher_target(html: str) -> str:
    return re.search(r'const baseUrl = "([^"]+)";', html).group(1)


def _state(ids) -> list[tuple]:
    with main.app.app_context():
        conn = main.get_db_connection()
        return [tuple(r) for r in conn.execute(
            "SELECT id,status,grupo,ch_por_evento,limite_semestre FROM atividade_versao"
            " WHERE atividade_base_id=? ORDER BY id", (ids["base"],))]


def _payload(grupo="1 - Grupo UI-C08 editado"):
    return {
        "tipo_atividade": "Acadêmica Complementar", "grupo": grupo, "nome": "Atividade UI-C08",
        "descricao": "Descrição UI-C08", "tipo_limitacao": "semestral", "limite_valor": "40",
        "ch_por_evento": "4", "observacoes": "", "versao_anterior_id": "",
    }


# --------------------------------------------------------------------------
# Hub
# --------------------------------------------------------------------------


def test_hub_offers_editar_only_for_the_editable_draft(env):
    client, ids = env
    html = client.get(f"/admin/catalogo-versoes/{ids['base']}").get_data(as_text=True)

    for which, expected in (("active", "0"), ("locked_draft", "0"), ("editable", "1")):
        card = re.search(r'<div class="impresso-card"[^>]*data-version-id="%d"[^>]*>' % ids[which], html, re.S)
        assert card, which
        assert f'data-version-editable="{expected}"' in card.group(0), which
        has_edit_url = f'data-version-edit-url="{_url(ids, which, "editar")}"' in card.group(0)
        assert has_edit_url is (expected == "1"), which
    assert "setVisible('edit', isEditable);" in html
    assert "setVisible('view', !isEditable || !canEdit);" in html


# --------------------------------------------------------------------------
# Atividades list
# --------------------------------------------------------------------------


def test_list_rows_carry_the_canonical_editability(env):
    client, ids = env
    html = client.get("/admin/atividades?per_page=all").get_data(as_text=True)
    rows = re.findall(r'data-atividade-id="(\d+)"[^>]*data-base-id="(\d*)" data-editable="([01])"', html)
    assert rows, "list rows lost their editability flag"
    with main.app.app_context():
        conn = main.get_db_connection()
        for version_id, base_id, flag in rows:
            expected = bool(base_id) and can_activity_version_be_mutated_in_place(conn, int(version_id))
            assert flag == ("1" if expected else "0"), version_id
    assert "editBtn.hidden = hasBase && currentCard?.getAttribute('data-editable') !== '1';" in html


# --------------------------------------------------------------------------
# Direct /editar
# --------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["active", "locked_draft"])
def test_locked_editar_url_renders_ver_with_no_save_target(env, which):
    client, ids = env
    response = client.get(_url(ids, which, "editar"))
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Ver versão" in html and "Editar versão" not in html
    tag = _form_tag(html)
    assert "action=" not in tag and "method=" not in tag
    assert 'name="csrf_token"' not in _version_form(html)
    assert 'type="submit"' not in html and "Salvar alterações" not in html
    assert 'disabled aria-readonly="true"' in html
    assert _switcher_target(html).endswith("/versoes/0/visualizar")


def test_editable_draft_editar_is_unchanged_and_switches_locked_targets_to_ver(env):
    client, ids = env
    html = client.get(_url(ids, "editable", "editar")).get_data(as_text=True)

    assert "Editar versão" in html
    tag = _form_tag(html)
    assert f'action="{_url(ids, "editable", "editar")}"' in tag and 'method="post"' in tag
    assert 'type="submit"' in html
    assert _switcher_target(html).endswith("/versoes/0/editar")
    for which, flag in (("active", "0"), ("locked_draft", "0"), ("editable", "1")):
        assert re.search(r'<option value="%d" data-editable="%s"' % (ids[which], flag), html), which
    assert "option.dataset.editable === '0' ? viewUrl : baseUrl" in html


# --------------------------------------------------------------------------
# Backend authority unchanged
# --------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["active", "locked_draft"])
def test_post_to_a_locked_version_is_still_refused(env, which):
    client, ids = env
    before = _state(ids)
    response = client.post(_url(ids, which, "editar"), data=_payload(), follow_redirects=False)
    assert response.status_code in (302, 303)
    assert response.headers["Location"].endswith(f"/admin/catalogo-versoes/{ids['base']}")
    assert _state(ids) == before


def test_editable_draft_still_saves(env):
    client, ids = env
    response = client.post(_url(ids, "editable", "editar"), data=_payload("2 - Grupo UI-C08 salvo"), follow_redirects=False)
    assert response.status_code in (302, 303)
    after = {row[0]: row for row in _state(ids)}
    assert after[ids["editable"]][2] == "2 - Grupo UI-C08 salvo"
