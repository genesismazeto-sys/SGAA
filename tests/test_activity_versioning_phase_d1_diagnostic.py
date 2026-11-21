"""Read-only diagnostics over the canonical Activity Version model."""
from __future__ import annotations

import re
from urllib.parse import urlencode

import pytest

import main
from app.views.admin import versioning as versioning_views
from tests.versioned_test_support import isolated_versioned_app_env
from tests.session_support import stamp_auth_version


@pytest.fixture()
def diagnostic_client(tmp_path):
    with isolated_versioned_app_env(tmp_path, "diagnostic.db") as env:
        client = env["client"]
        with client.session_transaction() as session:
            session.update(user_id=1, user_type="admin", user_name="Admin")
            stamp_auth_version(session)
        yield client


def test_diagnostic_lists_exact_matrix_versions(diagnostic_client):
    response = diagnostic_client.get("/admin/diagnostico/atividades-versionadas?matriz_id=1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["consulta"] == {"modo": "matriz", "matriz_id": 1}
    assert {row["atividade_versao_id"] for row in payload["atividades"]} == set(range(1, 29))


def test_diagnostic_resolves_turma_code_to_exact_matrix(diagnostic_client):
    response = diagnostic_client.get(
        "/admin/diagnostico/atividades-versionadas?turma_codigo=PPA-T10"
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["consulta"]["matriz_id"] == 1
    assert payload["matriz"]["id"] == 1


def test_diagnostic_view_renders_canonical_rows(diagnostic_client):
    response = diagnostic_client.get(
        "/admin/diagnostico/atividades-versionadas/view?matriz_id=2"
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "AAC" in html
    assert "AEU" in html


def test_diagnostic_requires_admin(tmp_path):
    with isolated_versioned_app_env(tmp_path, "diagnostic_auth.db") as env:
        response = env["client"].get("/admin/diagnostico/atividades-versionadas")
    assert response.status_code in {302, 401, 403}


# -- Lookups ------------------------------------------------------------------
#
# The resolver reports an identifier that names no Turma or Matriz as a status
# (``not_found`` with a reason), never as an exception; both routes answer it
# with 404, and the page shows it in its red alert. A Turma without a linked
# Matriz is an ordinary state, not an error: a neutral note, HTTP 200. Ordinary
# empty results (the index, a Matriz without versions) stay neutral.
#
# Only an absent or blank parameter supplies no identifier. A supplied one that
# is malformed, zero or names no row fails the lookup (404): it never reads as
# absent, so it never falls through to the next parameter or to the index. Ids
# are signed: a stored negative id resolves like any other.

TURMA_SEM_MATRIZ_ID = 50
MATRIZ_VAZIA_ID = 3
TURMA_NEGATIVA_ID = -70
MATRIZ_NEGATIVA_ID = -5
TURMA_NAO_ENCONTRADA = "Turma não encontrada para leitura diagnóstica."
MATRIZ_NAO_ENCONTRADA = "Matriz não encontrada para leitura diagnóstica."
TURMA_SEM_MATRIZ = "Turma PPA-T50: sem matriz vinculada."
INDICE = "Informe turma_id, turma_codigo ou matriz_id para carregar a visualização diagnóstica."
INDICE_JSON = "Informe turma_id, turma_codigo ou matriz_id para consultar o modelo versionado em paralelo."
VIEW = "/admin/diagnostico/atividades-versionadas/view"
JSON = "/admin/diagnostico/atividades-versionadas"

# Well-formed identifiers that name no row, negative ones and the bounds of a
# PostgreSQL id included.
UNRESOLVABLE = (
    ("turma_id=99999", TURMA_NAO_ENCONTRADA),
    ("turma_id=-99999", TURMA_NAO_ENCONTRADA),
    (f"turma_id={2**31}", TURMA_NAO_ENCONTRADA),
    ("turma_codigo=NAO-EXISTE", TURMA_NAO_ENCONTRADA),
    ("matriz_id=99999", MATRIZ_NAO_ENCONTRADA),
    ("matriz_id=-99999", MATRIZ_NAO_ENCONTRADA),
    (f"matriz_id={-(2**31) - 1}", MATRIZ_NAO_ENCONTRADA),
)
# Supplied values that can name no row. Flask's ``type=int`` read most of them
# as "no identifier", and "0_1", "+1" and the non-ASCII digit as Turma/Matriz 1.
INVALID_VALUES = (
    pytest.param("abc", id="letters"),
    pytest.param("1.5", id="decimal-point"),
    pytest.param("1e3", id="exponent"),
    pytest.param("0x1F", id="hex"),
    pytest.param("0_1", id="underscore"),
    pytest.param("1 2", id="inner-space"),
    pytest.param("-", id="bare-sign"),
    pytest.param("+1", id="plus-sign"),
    pytest.param("١", id="non-ascii-digit"),
    pytest.param("0", id="zero"),
    pytest.param("-0", id="negative-zero"),
    pytest.param("000", id="zeros"),
    pytest.param(str(2**63), id="above-int64"),
    pytest.param(str(-(2**63) - 1), id="below-int64"),
    pytest.param("9" * 40, id="40-digits"),
    pytest.param("-" + "9" * 40, id="minus-40-digits"),
    pytest.param("1" * 5000, id="beyond-int-conversion"),
    pytest.param("-" + "1" * 5000, id="minus-beyond-int-conversion"),
)
ID_PARAMETERS = (
    pytest.param("turma_id", TURMA_NAO_ENCONTRADA, id="turma_id"),
    pytest.param("matriz_id", MATRIZ_NAO_ENCONTRADA, id="matriz_id"),
)
# Every supplied identifier, and every value of a repeated one, is checked
# before precedence picks one.
INVALID_IN_A_MIXED_QUERY = (
    ("turma_id=abc&matriz_id=2", TURMA_NAO_ENCONTRADA),
    ("turma_id=0&turma_codigo=PPA-T10", TURMA_NAO_ENCONTRADA),
    ("turma_id=abc&matriz_id=0", TURMA_NAO_ENCONTRADA),
    ("turma_id=1&matriz_id=abc", MATRIZ_NAO_ENCONTRADA),
    ("turma_codigo=PPA-T10&matriz_id=0", MATRIZ_NAO_ENCONTRADA),
    ("turma_id=&turma_id=abc", TURMA_NAO_ENCONTRADA),
    ("turma_id=1&turma_id=abc", TURMA_NAO_ENCONTRADA),
    ("matriz_id=2&matriz_id=0", MATRIZ_NAO_ENCONTRADA),
    # An integer no row id can hold is invalid wherever it appears.
    (f"turma_id=1&matriz_id={2**63}", MATRIZ_NAO_ENCONTRADA),
    (f"turma_id=1&matriz_id={-(2**63) - 1}", MATRIZ_NAO_ENCONTRADA),
    (f"turma_codigo=PPA-T10&matriz_id={2**63}", MATRIZ_NAO_ENCONTRADA),
    (f"turma_id=1&turma_id={2**63}", TURMA_NAO_ENCONTRADA),
    (f"matriz_id=1&matriz_id={2**63}", MATRIZ_NAO_ENCONTRADA),
)
# Valid queries keep the precedence turma_id, turma_codigo, matriz_id; a
# lower-precedence identifier is checked but not looked up, and a repeated one
# is read by its first supplied value.
TURMA_1 = {"modo": "turma", "turma_id": 1, "matriz_id": 1}
RESOLVED_BY_PRECEDENCE = (
    ("turma_id=1&matriz_id=2", TURMA_1),
    ("turma_id=1&turma_codigo=NAO-EXISTE", TURMA_1),
    ("turma_id=1&matriz_id=99999", TURMA_1),
    (f"turma_id=1&matriz_id={2**63 - 1}", TURMA_1),
    (f"turma_id=1&matriz_id={-(2**63)}", TURMA_1),
    ("turma_id=%201%20", TURMA_1),
    ("turma_id=1&turma_id=2", TURMA_1),
    ("turma_id=&turma_id=1", TURMA_1),
    ("turma_codigo=PPA-T10&matriz_id=2", {
        "modo": "turma_codigo", "turma_codigo": "PPA-T10", "turma_id": 1, "matriz_id": 1,
    }),
    ("turma_id=&turma_codigo=&matriz_id=2", {"modo": "matriz", "matriz_id": 2}),
    (f"turma_id={TURMA_NEGATIVA_ID}&matriz_id=1", {
        "modo": "turma", "turma_id": TURMA_NEGATIVA_ID, "matriz_id": MATRIZ_NEGATIVA_ID,
    }),
)
STORED_NEGATIVE_IDS = (
    (f"matriz_id={MATRIZ_NEGATIVA_ID}", {"modo": "matriz", "matriz_id": MATRIZ_NEGATIVA_ID}),
    (f"turma_id={TURMA_NEGATIVA_ID}", {
        "modo": "turma", "turma_id": TURMA_NEGATIVA_ID, "matriz_id": MATRIZ_NEGATIVA_ID,
    }),
    ("turma_codigo=PPA-T70", {
        "modo": "turma_codigo", "turma_codigo": "PPA-T70", "turma_id": TURMA_NEGATIVA_ID,
        "matriz_id": MATRIZ_NEGATIVA_ID,
    }),
)
TURMA_SEM_MATRIZ_QUERIES = (
    (f"turma_id={TURMA_SEM_MATRIZ_ID}", {"modo": "turma", "turma_id": TURMA_SEM_MATRIZ_ID, "matriz_id": None}),
    ("turma_codigo=PPA-T50", {
        "modo": "turma_codigo", "turma_codigo": "PPA-T50", "turma_id": TURMA_SEM_MATRIZ_ID, "matriz_id": None,
    }),
)
# No identifier: nothing sent, blank fields (the form sends every field) or a
# Turma code of spaces.
NO_IDENTIFIER = ("", "turma_id=", "turma_id=%20%20", "turma_codigo=%20%20", "turma_codigo=&turma_id=&matriz_id=")

# The page message paragraph; the intro notes open with whitespace.
_MESSAGE = re.compile(r'<p class="(diag-alert|diag-note)">(\S[^<]*)</p>')


def _insert_turma(conn, turma_id, codigo, numero, matriz_id):
    conn.execute(
        "INSERT INTO turmas (id, nome, turno, status, numero, curso_id, matriz_id,"
        " ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)"
        " VALUES (?, ?, 'Manhã', 'Ativa', ?, 1, ?, 2026, 1, 2029, 2, ?)",
        (turma_id, codigo, numero, matriz_id, codigo),
    )


def _insert_matriz(conn, matriz_id, nome):
    conn.execute(
        "INSERT INTO matrizes_atividades (id, curso_id, nome, status,"
        " horas_aac_obrigatorias, horas_extensao_obrigatorias)"
        " VALUES (?, 1, ?, 'rascunho', 200, 100)",
        (matriz_id, nome),
    )


@pytest.fixture()
def lookup_client(tmp_path):
    with isolated_versioned_app_env(tmp_path, "diagnostic_lookup.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            _insert_turma(conn, TURMA_SEM_MATRIZ_ID, "PPA-T50", 50, None)
            _insert_matriz(conn, MATRIZ_VAZIA_ID, "Matriz PPA")
            # A Matriz and a Turma stored under negative ids, as both schemas allow.
            _insert_matriz(conn, MATRIZ_NEGATIVA_ID, "Matriz PPA legada")
            conn.execute(
                "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_base_id, atividade_versao_id)"
                " SELECT ?, atividade_base_id, atividade_versao_id FROM matriz_atividade_versao_item"
                " WHERE matriz_id = 1 ORDER BY atividade_versao_id LIMIT 3",
                (MATRIZ_NEGATIVA_ID,),
            )
            _insert_turma(conn, TURMA_NEGATIVA_ID, "PPA-T70", 70, MATRIZ_NEGATIVA_ID)
            conn.commit()
        client = env["client"]
        with client.session_transaction() as session:
            session.update(user_id=1, user_type="admin", user_name="Admin")
            stamp_auth_version(session)
        yield client


def _assert_failed_lookup(client, query, message):
    view = client.get(f"{VIEW}?{query}")
    html = view.get_data(as_text=True)
    assert view.status_code == 404
    assert _MESSAGE.findall(html) == [("diag-alert", message)]
    assert 'id="diagnostico-versionado"' not in html

    payload = client.get(f"{JSON}?{query}")
    assert payload.status_code == 404
    assert payload.get_json() == {"ok": False, "message": message}


def _assert_resolved(client, query, consulta):
    payload = client.get(f"{JSON}?{query}")
    assert payload.status_code == 200
    body = payload.get_json()
    assert (body["ok"], body["status"], body["consulta"]) == (True, "resolved", consulta)
    assert body["matriz"]["id"] == consulta["matriz_id"]

    view = client.get(f"{VIEW}?{query}")
    html = view.get_data(as_text=True)
    assert view.status_code == 200
    assert f'id="diagnostico-versionado" data-total-geral="{body["totais"]["geral"]}"' in html
    assert _MESSAGE.findall(html) == []
    return body


@pytest.mark.parametrize("query,message", UNRESOLVABLE)
def test_an_identifier_that_names_no_row_is_a_404_red_alert(lookup_client, query, message):
    _assert_failed_lookup(lookup_client, query, message)


@pytest.mark.parametrize("value", INVALID_VALUES)
@pytest.mark.parametrize("name,message", ID_PARAMETERS)
def test_an_explicitly_invalid_identifier_is_a_404_red_alert(lookup_client, name, message, value):
    _assert_failed_lookup(lookup_client, urlencode({name: value}), message)


@pytest.mark.parametrize("query,message", INVALID_IN_A_MIXED_QUERY)
def test_an_invalid_identifier_is_never_passed_over_for_a_later_parameter(lookup_client, query, message):
    _assert_failed_lookup(lookup_client, query, message)


@pytest.mark.parametrize("query,consulta", RESOLVED_BY_PRECEDENCE)
def test_valid_mixed_queries_keep_the_established_precedence(lookup_client, query, consulta):
    _assert_resolved(lookup_client, query, consulta)


@pytest.mark.parametrize("query,consulta", STORED_NEGATIVE_IDS)
def test_stored_negative_ids_resolve(lookup_client, query, consulta):
    body = _assert_resolved(lookup_client, query, consulta)
    assert body["matriz"] == {"id": MATRIZ_NEGATIVA_ID, "label": "Matriz PPA legada | Rascunho"}
    # The fixture's Matriz selects the first three versions of Matriz 1 (1..28).
    assert {row["atividade_versao_id"] for row in body["atividades"]} == {1, 2, 3}
    assert body["totais"]["geral"] == 3
    if consulta["modo"] != "matriz":
        assert body["turma"] == {"id": TURMA_NEGATIVA_ID, "nome": "PPA-T70", "codigo": "PPA-T70"}


def test_zero_is_not_an_identifier_even_where_a_row_holds_it(lookup_client):
    # Both schemas could store a row under id 0, though neither generates one;
    # the routes have never resolved it and treat an explicit 0 as invalid.
    with main.app.app_context():
        conn = main.get_db_connection()
        _insert_matriz(conn, 0, "Matriz PPA importada")
        conn.commit()
    _assert_failed_lookup(lookup_client, "matriz_id=0", MATRIZ_NAO_ENCONTRADA)


@pytest.mark.parametrize("query,_consulta", TURMA_SEM_MATRIZ_QUERIES)
def test_view_shows_a_turma_without_matrix_as_a_neutral_note(lookup_client, query, _consulta):
    response = lookup_client.get(f"{VIEW}?{query}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert _MESSAGE.findall(html) == [("diag-note", TURMA_SEM_MATRIZ)]
    assert 'class="diag-alert"' not in html
    assert 'id="diagnostico-versionado"' not in html


@pytest.mark.parametrize("query,consulta", TURMA_SEM_MATRIZ_QUERIES)
def test_json_answers_a_turma_without_matrix_as_an_empty_listing(lookup_client, query, consulta):
    # The route's 200 shape for a listing that did not resolve: ok, the query,
    # the resolver's status and reason, the Turma, no Matriz, no activities.
    response = lookup_client.get(f"{JSON}?{query}")
    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "consulta": consulta,
        "status": "not_found",
        "reason": "turma has no matrix",
        "turma": {"id": TURMA_SEM_MATRIZ_ID, "nome": "PPA-T50", "codigo": "PPA-T50"},
        "matriz": None,
        "atividades": [],
    }


@pytest.mark.parametrize("query", NO_IDENTIFIER)
def test_no_identifier_is_the_neutral_index(lookup_client, query):
    view = lookup_client.get(f"{VIEW}?{query}")
    html = view.get_data(as_text=True)
    assert view.status_code == 200
    assert _MESSAGE.findall(html) == [("diag-note", INDICE)]
    assert 'class="diag-alert"' not in html

    payload = lookup_client.get(f"{JSON}?{query}")
    assert payload.status_code == 200
    body = payload.get_json()
    assert (body["ok"], body["consulta"], body["message"]) == (True, {"modo": "indice"}, INDICE_JSON)
    assert {"PPA-T10", "PPA-T50", "PPA-T70"} <= {turma["codigo"] for turma in body["turmas_disponiveis"]}


def test_a_matrix_without_versions_is_a_neutral_empty_result(lookup_client):
    response = lookup_client.get(f"{VIEW}?matriz_id={MATRIZ_VAZIA_ID}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-total-geral="0"' in html
    assert html.count('<p class="diag-empty">Sem atividades para este eixo na consulta atual.</p>') == 2
    assert _MESSAGE.findall(html) == []
    assert 'class="diag-alert"' not in html

    payload = lookup_client.get(f"{JSON}?matriz_id={MATRIZ_VAZIA_ID}").get_json()
    assert (payload["status"], payload["atividades"], payload["totais"]["geral"]) == ("resolved", [], 0)


def test_valid_turma_lookups_still_resolve_to_the_exact_matrix(lookup_client):
    view = lookup_client.get(f"{VIEW}?turma_id=1")
    assert view.status_code == 200
    html = view.get_data(as_text=True)
    assert 'id="diagnostico-versionado" data-total-geral="28"' in html
    assert _MESSAGE.findall(html) == []

    payload = lookup_client.get(f"{JSON}?turma_id=1").get_json()
    assert payload["ok"] is True
    assert payload["consulta"] == {"modo": "turma", "turma_id": 1, "matriz_id": 1}
    by_code = lookup_client.get(f"{JSON}?turma_codigo=PPA-T10").get_json()
    assert by_code["consulta"] == {
        "modo": "turma_codigo", "turma_codigo": "PPA-T10", "turma_id": 1, "matriz_id": 1,
    }


def test_the_form_id_fields_take_any_stored_id(lookup_client):
    # A stored id may be negative, so the number fields carry no lower bound.
    html = lookup_client.get(VIEW).get_data(as_text=True)
    for name in ("turma_id", "matriz_id"):
        field = re.search(rf'<input id="{name}"[^>]*>', html).group(0)
        assert 'type="number"' in field
        assert "min=" not in field


# -- Authorization ------------------------------------------------------------


def _denied_client(env, actor):
    client = env["client"]
    if actor == "aluno":
        with client.session_transaction() as session:
            session.update(user_id=2, user_type="aluno", user_name="Aluno")
            stamp_auth_version(session)
    elif actor == "admin sem atividades":
        with main.app.app_context():
            conn = main.get_db_connection()
            user_id = conn.execute(
                "INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso) VALUES(?,?,?,?,?) RETURNING id",
                ("Coordenação", "coordenacao.diag@example.test", main.hash_password("pass"), "admin", "administrativo"),
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO usuarios_permissoes_acesso(usuario_id, recurso, escopo) VALUES(?, 'atividades', 'none')",
                (user_id,),
            )
            conn.commit()
        with client.session_transaction() as session:
            session.update(user_id=user_id, user_type="admin", user_name="Coordenação")
            stamp_auth_version(session)
    elif actor == "admin":
        with client.session_transaction() as session:
            session.update(user_id=1, user_type="admin", user_name="Admin")
            stamp_auth_version(session)
    return client


@pytest.fixture()
def lookup_calls(monkeypatch):
    """Records every diagnostic lookup; the lookup itself answers the index."""
    calls = []

    def _recorded(conn):
        calls.append(conn)
        return {"modo": "indice"}, None

    monkeypatch.setattr(versioning_views, "_consulta_diagnostica", _recorded)
    return calls


@pytest.mark.parametrize("query", ["turma_id=99999", "turma_id=abc"])
@pytest.mark.parametrize("path", [VIEW, JSON])
@pytest.mark.parametrize("actor", ["anonimo", "aluno", "admin sem atividades"])
def test_an_unauthorized_actor_is_refused_before_any_lookup(tmp_path, lookup_calls, path, actor, query):
    with isolated_versioned_app_env(tmp_path, "diagnostic_denied.db") as env:
        client = _denied_client(env, actor)
        response = client.get(f"{path}?{query}")
        body = response.get_data(as_text=True)
    assert response.status_code in {302, 403}
    if actor != "admin sem atividades":
        assert response.status_code == 302 and "/login" in response.headers["Location"]
    assert lookup_calls == []
    assert TURMA_NAO_ENCONTRADA not in body


@pytest.mark.parametrize("path", [VIEW, JSON])
def test_the_lookup_record_sees_an_authorized_request(tmp_path, lookup_calls, path):
    # Control for the refusal test: the recorder is on the routes' call path.
    with isolated_versioned_app_env(tmp_path, "diagnostic_allowed.db") as env:
        response = _denied_client(env, "admin").get(f"{path}?turma_id=abc")
    assert response.status_code == 200
    assert len(lookup_calls) == 1
