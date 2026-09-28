"""UI-C09: an omitted ``observacao`` must not erase the stored observação.

``admin_editar_requisicao`` used to parse ``observacao`` with
``(request.form.get("observacao") or "").strip() or None`` and always write it,
so a valid edit POST that simply omitted the field cleared the observação --
the same NULL an explicit empty submission writes.

Contract now (three distinct states):
* field **missing**   -> the stored observação is preserved (column not written);
* field **empty**     -> explicit clear (stored as NULL, as before);
* field **with text** -> replaced by the submitted text (trimmed, as before).

The UI-C03 guards (``edit_target_id`` must name the request in the URL; stale or
missing targets write nothing) and permissions are unchanged.
"""

from __future__ import annotations

import uuid

import pytest

import main
from app.user_accounts import create_usuario_with_access_level
from tests.canonical_request_test_support import create_admin_request, login_admin
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c09.db") as environment:
        client = environment["client"]
        login_admin(client)
        _response, first = create_admin_request(client, name=f"C09 R1 {uuid.uuid4().hex[:6]}")
        _response, second = create_admin_request(client, name=f"C09 R2 {uuid.uuid4().hex[:6]}")
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE requisicoes SET observacao='ABC' WHERE id=?", (first["id"],))
            conn.execute("UPDATE requisicoes SET observacao='OBS R2' WHERE id=?", (second["id"],))
            conn.commit()
        yield client, first["id"], second["id"]


def _row(req_id: int) -> dict:
    with main.app.app_context():
        return dict(main.get_db_connection().execute(
            "SELECT nome_evento,horas_solicitadas,data_evento,observacao FROM requisicoes WHERE id=?",
            (req_id,),
        ).fetchone())


def _all_rows() -> list[tuple]:
    with main.app.app_context():
        return [tuple(r) for r in main.get_db_connection().execute("SELECT * FROM requisicoes ORDER BY id")]


def _edit(client, req_id: int, *, target=..., **fields):
    data = {"nome_evento": "Evento editado C09", "horas_solicitadas": "4", "data_evento": "2026-06-01"}
    data.update(fields)
    if target is ...:
        target = req_id
    if target is not None:
        data["edit_target_id"] = str(target)
    return client.post(f"/admin/requisicoes/{req_id}/editar", data=data, follow_redirects=False)


# --------------------------------------------------------------------------
# The three states
# --------------------------------------------------------------------------


def test_omitted_observacao_is_preserved_and_other_fields_still_update(env):
    client, req_id, _other = env
    response = _edit(client, req_id)
    assert response.status_code == 302
    assert _row(req_id) == {
        "nome_evento": "Evento editado C09", "horas_solicitadas": 4.0,
        "data_evento": "2026-06-01", "observacao": "ABC",
    }


@pytest.mark.parametrize("submitted", ["", "   "])
def test_submitted_empty_observacao_is_an_explicit_clear(env, submitted):
    client, req_id, _other = env
    _edit(client, req_id, observacao=submitted)
    assert _row(req_id)["observacao"] is None


def test_submitted_text_replaces_the_observacao(env):
    client, req_id, _other = env
    _edit(client, req_id, observacao="  XYZ  ")
    assert _row(req_id)["observacao"] == "XYZ"
    assert _row(req_id)["nome_evento"] == "Evento editado C09"


def test_the_edit_only_touches_its_own_request(env):
    client, req_id, other = env
    before = _row(other)
    _edit(client, req_id)
    _edit(client, req_id, observacao="XYZ")
    assert _row(other) == before


# --------------------------------------------------------------------------
# UI-C03 guards and permissions still write nothing
# --------------------------------------------------------------------------


@pytest.mark.parametrize("target", [None, "", "OTHER"])
@pytest.mark.parametrize("with_observacao", [False, True])
def test_stale_missing_or_wrong_target_writes_nothing(env, target, with_observacao):
    client, req_id, other = env
    before = _all_rows()
    fields = {"observacao": "nao deve gravar"} if with_observacao else {}
    response = client.post(
        f"/admin/requisicoes/{req_id}/editar",
        data={"nome_evento": "vazou", "horas_solicitadas": "9", "data_evento": "2026-06-02",
              **fields, **({"edit_target_id": str(other) if target == "OTHER" else target} if target is not None else {})},
        follow_redirects=True,
    )
    assert "Falha ao atualizar requisição." in response.get_data(as_text=True)
    assert _all_rows() == before


def test_view_only_user_writes_nothing(env):
    client, req_id, _other = env
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = int(create_usuario_with_access_level(
            conn, f"C09 viewer {token}", f"c09-viewer-{token}@example.invalid",
            main.hash_password("c09"), "admin", "consultivo", credential_state="personal",
        ).lastrowid)
        conn.commit()
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=uid, user_type="admin", user_name="C09 viewer")
        stamp_auth_version(session, uid)
    before = _all_rows()
    for fields in ({}, {"observacao": ""}, {"observacao": "XYZ"}):
        response = _edit(client, req_id, **fields)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/admin/dashboard")
    assert _all_rows() == before


@pytest.mark.parametrize(
    "broken",
    [{"nome_evento": ""}, {"horas_solicitadas": "abc"}, {"data_evento": ""}],
)
@pytest.mark.parametrize("with_observacao", [False, True])
def test_failed_validation_writes_nothing(env, broken, with_observacao):
    client, req_id, _other = env
    before = _all_rows()
    fields = dict(broken)
    if with_observacao:
        fields["observacao"] = ""
    _edit(client, req_id, **fields)
    assert _all_rows() == before
    assert _row(req_id)["observacao"] == "ABC"
