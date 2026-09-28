"""UI-C05: Atividades hub and Ver versão expose no mutation to view-only users.

Permission and state are two independent dimensions:

* permission -- ``atividades:view`` reads the hub and every version;
  ``atividades:edit`` is required for every WRITE (Criar/Nova versão, Editar,
  Ativar, Inativar, Descontinuar, Substituir, Excluir). A view-only user gets
  the read actions only: nothing rendered disabled, no hidden form, no modal,
  no write URL left in the DOM.
* state -- which of those writes an editor sees keeps following the version
  status (drafts: Editar/Ativar; active: Inativar/Descontinuar/Substituir),
  unchanged here. State-driven read-only Editar pages stay UI-C08.

The version switcher keeps the mode it was opened in: Ver stays on
``/visualizar``, Editar stays on ``/editar``.
"""

from __future__ import annotations

import re
import uuid

import pytest

import main
from app.auth import get_admin_permission_requirement
from app.user_accounts import create_usuario_with_access_level
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

WRITE_ACTIONS = ("edit", "activate", "suspend", "substitute", "discontinue", "delete")
WRITE_FORM_CLASSES = (
    "vc-activate-form",
    "vc-delete-form",
    "vc-inativar-form",
    "vc-descontinuar-form",
    "vc-substituir-form",
)
WRITE_ENDPOINT_SUFFIXES = ("/ativar", "/inativar", "/descontinuar", "/substituir", "/excluir", "/editar", "/nova-versao")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _create_actor(access_level: str, *, deny_resources=()) -> int:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        user_id = int(
            create_usuario_with_access_level(
                conn,
                f"UI-C05 {access_level} {token}",
                f"ui-c05-{access_level}-{token}@example.invalid",
                main.hash_password("ui-c05"),
                "admin",
                access_level,
                credential_state="personal",
            ).lastrowid
        )
        for resource in deny_resources:
            conn.execute(
                "INSERT INTO usuarios_permissoes_acesso(usuario_id,recurso,escopo)"
                " VALUES (?,?,'none')",
                (user_id, resource),
            )
        conn.commit()
    return user_id


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=user_id, user_type="admin", user_name="UI-C05 actor")
        stamp_auth_version(session, user_id)


def _seed() -> dict[str, int]:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = int(
            conn.execute(
                "INSERT INTO atividade_base(nome_conceito,descricao,status) VALUES (?,?,'ativo')",
                (f"Atividade UI-C05 {token}", "Descrição UI-C05"),
            ).lastrowid
        )
        active_id = int(
            conn.execute(
                "INSERT INTO atividade_versao(atividade_base_id,eixo,grupo,status,ch_por_evento,numero_versao)"
                " VALUES (?,?,?,'ativa',?,1)",
                (base_id, "AAC", "1 - Grupo UI-C05", 2),
            ).lastrowid
        )
        draft_id = int(
            conn.execute(
                "INSERT INTO atividade_versao(atividade_base_id,eixo,grupo,status,ch_por_evento,numero_versao,versao_anterior_id)"
                " VALUES (?,?,?,'rascunho',?,2,?)",
                (base_id, "AAC", "1 - Grupo UI-C05", 3, active_id),
            ).lastrowid
        )
        conn.commit()
    return {"base": base_id, "active": active_id, "draft": draft_id}


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c05.db") as environment:
        ids = _seed()
        yield {
            "client": environment["client"],
            "ids": ids,
            "viewer": _create_actor("consultivo"),
            "editor": _create_actor("administrativo"),
            "denied": _create_actor("administrativo", deny_resources=("atividades",)),
        }


def _as(env, actor):
    _login(env["client"], env[actor])
    return env["client"]


def _hub(ids) -> str:
    return f"/admin/catalogo-versoes/{ids['base']}"


def _version(ids, which, mode) -> str:
    return f"/admin/catalogo-versoes/{ids['base']}/versoes/{ids[which]}/{mode}"


def _version_form(html: str) -> str:
    """The version page's own <form> (base.html carries unrelated global forms)."""
    match = re.search(r'(<form[^>]*autocomplete="off">.*?</form>)', html, re.S)
    assert match, "the version page lost its form"
    return match.group(1)


def _switcher_target(html: str) -> str:
    match = re.search(r'const baseUrl = "([^"]+)";', html)
    assert match, "the version switcher lost its navigation script"
    return match.group(1)


def _toolbar(html: str) -> str:
    match = re.search(r"bar\.innerHTML = `(.*?)`;", html, re.S)
    assert match, "the hub lost its row-action toolbar"
    return match.group(1)


def _state(ids) -> list[tuple]:
    with main.app.app_context():
        conn = main.get_db_connection()
        return [
            tuple(row)
            for row in conn.execute(
                "SELECT id,status,grupo,ch_por_evento FROM atividade_versao WHERE atividade_base_id=? ORDER BY id",
                (ids["base"],),
            )
        ] + [
            (
                "count",
                conn.execute(
                    "SELECT COUNT(*) FROM atividade_versao WHERE atividade_base_id=?", (ids["base"],)
                ).fetchone()[0],
            )
        ]


def _denied(response) -> None:
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/dashboard")


# ==========================================================================
# Versions hub
# ==========================================================================


def test_view_only_hub_renders_reads_and_no_write_affordance(env):
    ids = env["ids"]
    response = _as(env, "viewer").get(_hub(ids))
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    for which in ("active", "draft"):
        assert f'data-version-view-url="{_version(ids, which, "visualizar")}"' in html
    toolbar = _toolbar(html)
    assert 'data-action="view"' in toolbar
    for action in WRITE_ACTIONS:
        assert f'data-action="{action}"' not in toolbar, action

    assert "Criar versão" not in html
    assert "/nova-versao" not in html
    assert "data-version-edit-url" not in html
    for form_class in WRITE_FORM_CLASSES:
        assert not re.search(r'<form[^>]*class="[^"]*\b' + form_class + r'\b', html), form_class
    assert not re.search(r"<select[^>]*data-substitution-options", html)
    assert 'id="version-substitute-modal"' not in html
    for suffix in WRITE_ENDPOINT_SUFFIXES:
        assert not re.search(r'action="[^"]*' + re.escape(suffix) + '"', html), suffix
    assert "const canEdit = false;" in html
    # A view-only user reads drafts too (editors open drafts in Editar instead).
    assert "setVisible('view', !isEditable || !canEdit);" in html


def test_editor_hub_keeps_state_based_write_actions(env):
    ids = env["ids"]
    html = _as(env, "editor").get(_hub(ids)).get_data(as_text=True)

    assert "Criar versão" in html
    assert f"/admin/catalogo-versoes/{ids['base']}/nova-versao" in html
    toolbar = _toolbar(html)
    for action in ("view",) + WRITE_ACTIONS:
        assert f'data-action="{action}"' in toolbar, action
    assert "const canEdit = true;" in html
    assert 'id="version-substitute-modal"' in html
    # UI-C08: only a version that can be edited in place (the unreferenced
    # draft) carries an edit URL; the active one is read through Ver.
    assert f'data-version-edit-url="{_version(ids, "draft", "editar")}"' in html
    assert f'data-version-edit-url="{_version(ids, "active", "editar")}"' not in html

    def form_for(action_suffix, which):
        return f'action="{_version(ids, which, action_suffix.strip("/"))}"' in html

    # State still decides: Ativar only for the draft, lifecycle only for the active.
    assert form_for("/ativar", "draft") and not form_for("/ativar", "active")
    for suffix in ("/inativar", "/descontinuar", "/substituir"):
        assert form_for(suffix, "active") and not form_for(suffix, "draft"), suffix
    assert form_for("/excluir", "active") and form_for("/excluir", "draft")
    # Unchanged editor rule: drafts open in Editar, not Ver.
    assert "setVisible('edit', isEditable);" in html


def test_no_permission_is_refused_as_before(env):
    ids = env["ids"]
    client = _as(env, "denied")
    _denied(client.get(_hub(ids)))
    _denied(client.get(_version(ids, "active", "visualizar")))


# ==========================================================================
# Ver versão / Editar versão
# ==========================================================================


@pytest.mark.parametrize("which", ["active", "draft"])
def test_view_only_ver_versao_has_no_mutation_and_switcher_stays_in_ver(env, which):
    ids = env["ids"]
    response = _as(env, "viewer").get(_version(ids, which, "visualizar"))
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="versao-switcher"' in html
    assert "Nova versão" not in html and "/nova-versao" not in html
    assert 'type="submit"' not in html and "Salvar" not in html
    form = _version_form(html)
    form_tag = form.split(">", 1)[0]
    assert "action=" not in form_tag and "method=" not in form_tag, form_tag
    assert 'name="csrf_token"' not in form
    assert _switcher_target(html) == f"/admin/catalogo-versoes/{ids['base']}/versoes/0/visualizar"
    assert "/versoes/0/editar" not in html
    assert not re.search(
        r'="/admin/catalogo-versoes/\d+/versoes/\d+/(editar|ativar|inativar|descontinuar|substituir|excluir)"',
        html,
    )


def test_editor_ver_versao_also_stays_in_ver_and_keeps_nova_versao(env):
    ids = env["ids"]
    html = _as(env, "editor").get(_version(ids, "draft", "visualizar")).get_data(as_text=True)

    assert _switcher_target(html) == f"/admin/catalogo-versoes/{ids['base']}/versoes/0/visualizar"
    assert "Nova versão" in html
    assert "action=" not in _version_form(html).split(">", 1)[0]
    assert 'type="submit"' not in html


def test_editor_editar_keeps_edit_navigation_and_save(env):
    ids = env["ids"]
    html = _as(env, "editor").get(_version(ids, "draft", "editar")).get_data(as_text=True)

    assert _switcher_target(html) == f"/admin/catalogo-versoes/{ids['base']}/versoes/0/editar"
    assert "Nova versão" in html
    assert f'action="{_version(ids, "draft", "editar")}"' in html
    assert 'method="post"' in html
    assert 'type="submit"' in html


def test_state_locked_editar_renders_as_ver(env):
    """UI-C08: an active version cannot be edited in place, so its /editar URL
    renders the Ver page -- no save target, switcher in Ver mode."""
    ids = env["ids"]
    html = _as(env, "editor").get(_version(ids, "active", "editar")).get_data(as_text=True)

    assert _switcher_target(html) == f"/admin/catalogo-versoes/{ids['base']}/versoes/0/visualizar"
    assert "action=" not in _version_form(html).split(">", 1)[0]
    assert 'type="submit"' not in html


# ==========================================================================
# Backend authority is unchanged
# ==========================================================================


def test_permission_registry_keeps_writes_on_edit_and_ver_on_view():
    assert get_admin_permission_requirement("admin_catalogo_versao_detalhe", "GET") == ("atividades", "view")
    assert get_admin_permission_requirement("admin_catalogo_visualizar_versao", "GET") == ("atividades", "view")
    for endpoint, methods in (
        ("admin_catalogo_nova_versao", ("GET", "POST")),
        ("admin_catalogo_editar_versao", ("GET", "POST")),
        ("admin_catalogo_ativar_versao", ("POST",)),
        ("admin_catalogo_inativar_versao", ("POST",)),
        ("admin_catalogo_descontinuar_versao", ("POST",)),
        ("admin_catalogo_substituir_versao", ("POST",)),
        ("admin_catalogo_excluir_versao", ("POST",)),
    ):
        for method in methods:
            assert get_admin_permission_requirement(endpoint, method) == ("atividades", "edit"), (endpoint, method)


def test_view_only_crafted_writes_are_refused_and_change_nothing(env):
    ids = env["ids"]
    client = _as(env, "viewer")
    before = _state(ids)

    _denied(client.get(f"{_hub(ids)}/nova-versao?from={ids['active']}"))
    _denied(client.post(f"{_hub(ids)}/nova-versao", data={"nome": "x"}))
    _denied(client.get(_version(ids, "draft", "editar")))
    _denied(client.post(_version(ids, "draft", "editar"), data={"nome": "x", "grupo": "1 - x"}))
    _denied(client.post(_version(ids, "draft", "ativar")))
    _denied(client.post(_version(ids, "active", "inativar")))
    _denied(client.post(_version(ids, "active", "descontinuar")))
    _denied(client.post(_version(ids, "active", "substituir"), data={"to_versao_id": ids["draft"]}))
    _denied(client.post(_version(ids, "draft", "excluir")))

    assert _state(ids) == before
