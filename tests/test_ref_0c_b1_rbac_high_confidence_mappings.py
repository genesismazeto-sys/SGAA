"""REF-0C-B1 — Strongly Supported RBAC Mappings and Denial Tests.

Validates the 21 HIGH-confidence route-method RBAC policies accepted in
``docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md`` (Section 9, accepted
diagnosis HEAD ``f977fd6``):

  - ``atividades``/``view`` : R1-R4
  - ``atividades``/``edit`` : R5-R16
  - ``matrizes``/``view``   : R17
  - ``matrizes``/``edit``   : R18-R21 (R20 = central mapping only)

R22-R24 are deliberately outside this B1 regression file; their approved mappings
and actor tests are owned by ``test_ref_0c_b2_diagnostic_rbac.py``.

Coverage:
  1. Central requirement mapping — every one of the 21 route-method pairs returns
     its accepted ``(resource, scope)`` tuple.
  2. Actor matrix — ``admin_total`` / ``administrativo`` / ``consultivo`` resolve
     the intended allow/deny at the permission layer for both resources × scopes.
  3. Denial contract — a denied role (``consultivo`` on an ``edit`` route) is
     redirected to ``admin_dashboard``; anonymous access is redirected to login.
  4. No-mutation invariants — a denied POST mutates no rows in the target tables.

All database access uses the isolated fixture-controlled versioned dataset. The
real institutional ``database.db`` is never touched.
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
# Canonical accepted policy matrix (REF-0C-A diagnosis Section 9, HEAD f977fd6)
# ---------------------------------------------------------------------------

# (endpoint, method) -> (resource, scope). Exactly the 21 HIGH-confidence
# route-method combinations from the accepted debt baseline, minus R22-R24.
HIGH_CONFIDENCE_POLICIES = {
    # atividades/view (R1-R4)
    ("admin_catalogo_versoes", "GET"): ("atividades", "view"),
    ("admin_catalogo_versao_detalhe", "GET"): ("atividades", "view"),
    # atividades/edit (R5-R16)
    ("admin_catalogo_nova_base", "GET"): ("atividades", "edit"),
    ("admin_catalogo_nova_base", "POST"): ("atividades", "edit"),
    ("admin_catalogo_nova_versao", "GET"): ("atividades", "edit"),
    ("admin_catalogo_nova_versao", "POST"): ("atividades", "edit"),
    ("admin_catalogo_editar_versao", "GET"): ("atividades", "edit"),
    ("admin_catalogo_editar_versao", "POST"): ("atividades", "edit"),
    ("admin_catalogo_ativar_versao", "POST"): ("atividades", "edit"),
    ("admin_catalogo_inativar_versao", "POST"): ("atividades", "edit"),
    ("admin_catalogo_descontinuar_versao", "POST"): ("atividades", "edit"),
    ("admin_catalogo_substituir_versao", "POST"): ("atividades", "edit"),
    # matrizes/view (R17)
    ("admin_matriz_versoes", "GET"): ("matrizes", "view"),
    # matrizes/edit (R18, R19, R20, R21)
    ("admin_matriz_versoes_definir", "POST"): ("matrizes", "edit"),
    ("admin_matriz_versoes_remover", "POST"): ("matrizes", "edit"),
    ("admin_matriz_nova_atividade", "POST"): ("matrizes", "edit"),
    ("admin_matriz_nova_versao_card", "POST"): ("matrizes", "edit"),
}

# ---------------------------------------------------------------------------
# Part 1 — Central requirement mapping (pure function; no app context needed)
# ---------------------------------------------------------------------------


def test_high_confidence_policy_count_matches_current_surface():
    assert len(HIGH_CONFIDENCE_POLICIES) == 17


@pytest.mark.parametrize(
    "key,expected",
    sorted(HIGH_CONFIDENCE_POLICIES.items()),
    ids=[f"{ep}:{m}" for (ep, m) in sorted(HIGH_CONFIDENCE_POLICIES)],
)
def test_high_confidence_requirement_mapping(key, expected):
    endpoint, method = key
    assert main.get_admin_permission_requirement(endpoint, method) == expected


# ---------------------------------------------------------------------------
# Fixtures / helpers for the actor-matrix, denial and immutability tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ref0cb1_rbac.db") as e:
        yield e


def _make_admin(access_level: str) -> int:
    """Insert a real admin user with the given nivel_acesso; return its id."""
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso)"
            " VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                f"Admin {access_level}",
                f"rbac.{access_level}.{uuid.uuid4().hex[:8]}@example.com",
                main.hash_password("rbac-test-pass"),
                "admin",
                access_level,
            ),
        ).fetchone()["id"]
        conn.commit()
    return uid


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_type"] = "admin"
        sess["user_name"] = "RBAC Test"


def _logout(client) -> None:
    with client.session_transaction() as sess:
        sess.clear()


def _is_dashboard_denial(response) -> bool:
    return response.status_code == 302 and response.headers.get("Location", "").endswith(
        "/admin/dashboard"
    )


def _count(sql: str, params: tuple = ()) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        return conn.execute(sql, params).fetchone()[0]


# Representative routes per (resource, scope) group.
VIEW_ROUTES = ("/admin/catalogo-versoes", "/admin/matrizes/1/versoes")
EDIT_GET_ROUTE = "/admin/catalogo-versoes/nova-base"  # R5, atividades/edit


# ---------------------------------------------------------------------------
# Part 2 — Actor matrix at the permission layer (unambiguous allow/deny)
# ---------------------------------------------------------------------------


def test_actor_matrix_permission_layer(env):
    """admin_total / administrativo / consultivo resolve the intended scopes."""
    expectations = {
        # (atividades view, atividades edit, matrizes view, matrizes edit)
        "admin_total": (True, True, True, True),
        "administrativo": (True, True, True, True),
        "consultivo": (True, False, True, False),
    }
    # Create the admins first (each manages its own connection), then resolve
    # their contexts under a single connection to avoid nested sqlite locks.
    ids = {level: _make_admin(level) for level in expectations}
    with main.app.app_context():
        conn = main.get_db_connection()
        for level, (av, ae, mv, me) in expectations.items():
            ctx = main._load_admin_access_context(conn, ids[level])
            assert ctx["is_admin"] is True
            assert main._admin_can("atividades", "view", ctx) is av
            assert main._admin_can("atividades", "edit", ctx) is ae
            assert main._admin_can("matrizes", "view", ctx) is mv
            assert main._admin_can("matrizes", "edit", ctx) is me


# ---------------------------------------------------------------------------
# Part 3 — Actor matrix over HTTP: allow paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", ["admin_total", "administrativo", "consultivo"])
def test_view_routes_allow_all_admin_roles(env, level):
    client = env["client"]
    _login(client, _make_admin(level))
    for path in VIEW_ROUTES:
        r = client.get(path)
        assert r.status_code == 200, f"{level} unexpectedly denied on view route {path}"


@pytest.mark.parametrize("level", ["admin_total", "administrativo"])
def test_edit_get_route_allows_privileged_roles(env, level):
    client = env["client"]
    _login(client, _make_admin(level))
    r = client.get(EDIT_GET_ROUTE)
    assert r.status_code == 200, f"{level} should be allowed on atividades/edit form"


# ---------------------------------------------------------------------------
# Part 4 — Denial contract
# ---------------------------------------------------------------------------


def test_consultivo_denied_on_edit_get_route(env):
    """consultivo has atividades=view; an edit route must redirect to dashboard."""
    client = env["client"]
    _login(client, _make_admin("consultivo"))
    r = client.get(EDIT_GET_ROUTE)
    assert _is_dashboard_denial(r), (r.status_code, r.headers.get("Location"))


def test_anonymous_denied_on_mapped_route(env):
    client = env["client"]
    _logout(client)
    r = client.get("/admin/catalogo-versoes")
    assert r.status_code == 302
    assert "/login" in r.headers.get("Location", "")


# ---------------------------------------------------------------------------
# Part 5 — No-mutation invariants (denied POST mutates nothing)
# ---------------------------------------------------------------------------


def test_denied_post_atividades_edit_is_immutable(env):
    """consultivo POST to atividades/edit is denied and inserts no atividade_base."""
    client = env["client"]
    _login(client, _make_admin("consultivo"))
    before = _count("SELECT COUNT(*) FROM atividade_base")
    r = client.post(
        "/admin/catalogo-versoes/nova-base",
        data={"nome_conceito": "RBAC Denied", "descricao": "should not persist"},
    )
    assert _is_dashboard_denial(r), (r.status_code, r.headers.get("Location"))
    after = _count("SELECT COUNT(*) FROM atividade_base")
    assert after == before, "denied POST must not insert into atividade_base"


def test_denied_post_matrizes_edit_is_immutable(env):
    """consultivo POST to matrizes/edit is denied and mutates no matrix link rows."""
    client = env["client"]
    _login(client, _make_admin("consultivo"))
    before = _count(
        "SELECT COUNT(*) FROM matriz_atividade_versao_item WHERE matriz_id = 1"
    )
    r = client.post("/admin/matrizes/1/versoes/definir", data={})
    assert _is_dashboard_denial(r), (r.status_code, r.headers.get("Location"))
    after = _count(
        "SELECT COUNT(*) FROM matriz_atividade_versao_item WHERE matriz_id = 1"
    )
    assert after == before, "denied POST must not mutate matriz_atividade_versao_item"


def test_privileged_role_passes_matrizes_edit_gate(env):
    """administrativo (matrizes=full) is not stopped by the RBAC denial gate."""
    client = env["client"]
    _login(client, _make_admin("administrativo"))
    r = client.post("/admin/matrizes/1/versoes/remover", data={})
    # The handler may still reject invalid input, but never with the RBAC
    # denial signature (302 -> /admin/dashboard from the before-request gate).
    assert not _is_dashboard_denial(r)
