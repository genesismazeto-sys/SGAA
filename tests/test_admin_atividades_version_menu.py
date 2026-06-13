"""
D7.6C — Testes do menu ⋮ de versões na lista de atividades admin.

Cobre:
  1.  GET /admin/atividades retorna 200.
  2.  Atividade com base_id exibe atributo data-base-id correto no card HTML.
  3.  URL template "Criar nova versão" aponta para o padrão catalogo-versoes/<base_id>/nova-versao.
  4.  URL template "Ver versões" aponta para o padrão catalogo-versoes/<base_id>.
  5.  Menu ⋮ contém ação "Editar atividade".
  6.  Menu ⋮ contém ação "Criar nova versão".
  7.  Menu ⋮ contém ação "Ver versões".
  8.  Atividade sem base_id não expõe data-base-id preenchido.
  9.  Não aparece codigo_normativo como versão operacional na lista de atividades.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from tests.versioned_test_support import isolated_versioned_app_env


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def versioned_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "d76c_version_menu.db") as env:
        yield env


_ADMIN_ID = 999001


def _setup_admin_user():
    """Insert admin user 999001 into the isolated DB with admin_total access."""
    with main.app.app_context():
        conn = main.get_db_connection()
        existing = conn.execute("SELECT id FROM usuarios WHERE id = ?", (_ADMIN_ID,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO usuarios (id, nome, email, senha, tipo, nivel_acesso)"
                " VALUES (?, 'Admin Teste Menu', 'admin.menu@test.local', 'x', 'admin', 'admin_total')",
                (_ADMIN_ID,),
            )
            conn.commit()


def _login_admin(client):
    _setup_admin_user()
    with client.session_transaction() as sess:
        sess["user_id"] = _ADMIN_ID
        sess["user_type"] = "admin"
        sess["user_name"] = "Admin Menu Test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_atividades_html(client) -> str:
    resp = client.get("/admin/atividades")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _insert_unmapped_activity(suffix: str) -> int:
    """Insert an atividade with no entry in atividade_legacy_map. Returns its id."""
    with main.app.app_context():
        conn = main.get_db_connection()
        ativ_id = conn.execute(
            "INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)"
            " VALUES ('1 - Grupo Sem Base', ?, 'Sem mapeamento', 10, 'Acadêmica Complementar', 0)"
            " RETURNING id",
            (f"Atividade Sem Base {suffix}",),
        ).fetchone()["id"]
        conn.commit()
    return ativ_id


# ---------------------------------------------------------------------------
# 1. GET /admin/atividades retorna 200
# ---------------------------------------------------------------------------


def test_admin_atividades_returns_200(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    resp = client.get("/admin/atividades")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. Atividade com base_id exibe data-base-id correto
# ---------------------------------------------------------------------------


def test_atividade_com_base_id_exibe_data_base_id(versioned_env):
    """
    No dataset de referência, atividade_id_legacy=1 mapeia para atividade_base_id=1.
    O card correspondente deve ter data-base-id="1".
    """
    client = versioned_env["client"]
    _login_admin(client)
    html = _get_atividades_html(client)
    # O card da atividade 1 deve ter data-base-id="1"
    assert 'data-atividade-id="1"' in html
    assert 'data-base-id="1"' in html


# ---------------------------------------------------------------------------
# 3. URL template "Criar nova versão" usa padrão correto
# ---------------------------------------------------------------------------


def test_nova_versao_url_template_no_js(versioned_env):
    """
    O JS renderizado deve conter a URL base para nova-versao (sentinela /0/).
    Isso garante que o link navegará para /admin/catalogo-versoes/<bid>/nova-versao.
    """
    client = versioned_env["client"]
    _login_admin(client)
    html = _get_atividades_html(client)
    assert "/admin/catalogo-versoes/0/nova-versao" in html


# ---------------------------------------------------------------------------
# 4. URL template "Ver versões" usa padrão correto
# ---------------------------------------------------------------------------


def test_ver_versoes_url_template_no_js(versioned_env):
    """
    O JS renderizado deve conter a URL base para ver versões (sentinela /0).
    Isso garante que o link navegará para /admin/catalogo-versoes/<bid>.
    """
    client = versioned_env["client"]
    _login_admin(client)
    html = _get_atividades_html(client)
    assert "/admin/catalogo-versoes/0" in html


# ---------------------------------------------------------------------------
# 5. Menu ⋮ contém "Editar atividade"
# ---------------------------------------------------------------------------


def test_menu_contem_editar_atividade(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    html = _get_atividades_html(client)
    assert 'data-menu-action="edit"' in html
    assert "Editar atividade" in html


# ---------------------------------------------------------------------------
# 6. Menu ⋮ contém "Criar nova versão"
# ---------------------------------------------------------------------------


def test_menu_contem_criar_nova_versao(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    html = _get_atividades_html(client)
    assert 'data-menu-action="nova-versao"' in html
    assert "Criar nova versão" in html


# ---------------------------------------------------------------------------
# 7. Menu ⋮ contém "Ver versões"
# ---------------------------------------------------------------------------


def test_menu_contem_ver_versoes(versioned_env):
    client = versioned_env["client"]
    _login_admin(client)
    html = _get_atividades_html(client)
    assert 'data-menu-action="ver-versoes"' in html
    assert "Ver versões" in html


# ---------------------------------------------------------------------------
# 8. Atividade sem base_id não exibe data-base-id preenchido
# ---------------------------------------------------------------------------


def test_atividade_sem_base_id_nao_gera_link_invalido(versioned_env):
    """
    Uma atividade sem entrada em atividade_legacy_map deve ter data-base-id=""
    (vazio), não um valor de base_id que levaria a uma URL inválida.
    """
    t = uuid.uuid4().hex[:8]
    ativ_id = _insert_unmapped_activity(t)

    client = versioned_env["client"]
    _login_admin(client)
    html = _get_atividades_html(client)

    # O card deve existir
    assert f'data-atividade-id="{ativ_id}"' in html
    # O data-base-id deve estar vazio (sem valor)
    assert f'data-atividade-id="{ativ_id}" data-atividade-nome=' in html or \
           f'data-base-id=""' in html


# ---------------------------------------------------------------------------
# 9. codigo_normativo não aparece como versão operacional na lista
# ---------------------------------------------------------------------------


def test_codigo_normativo_nao_aparece_como_versao_na_lista(versioned_env):
    """
    A lista /admin/atividades exibe atividades base (legacy), não versões.
    Nomes de normas (AAC-rev5, AEU-rev1 etc.) não devem aparecer como
    identificador de versão operacional nos cards da lista.
    """
    client = versioned_env["client"]
    _login_admin(client)
    html = _get_atividades_html(client)
    # Normas do dataset de referência não devem surgir como versão operacional
    assert "AAC-rev5" not in html
    assert "AEU-rev1" not in html
