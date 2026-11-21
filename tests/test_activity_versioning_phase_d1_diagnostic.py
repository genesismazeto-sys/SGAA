"""Read-only diagnostics over the canonical Activity Version model."""
from __future__ import annotations

import re

import pytest

import main
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


# -- Lookups the resolver cannot resolve ------------------------------------
#
# The resolver reports an identifier that names no Turma or Matriz as a status
# (``not_found`` with a reason), never as an exception. Both routes once read
# such a result as resolved and answered HTTP 500; they now answer 404 with the
# reason, and the page shows it in its red alert. A Turma without a linked
# Matriz is an ordinary state, not an error: a neutral note, HTTP 200. Ordinary
# empty results (the index, a Matriz without versions) stay neutral.

TURMA_SEM_MATRIZ_ID = 50
MATRIZ_VAZIA_ID = 3
TURMA_NAO_ENCONTRADA = "Turma não encontrada para leitura diagnóstica."
MATRIZ_NAO_ENCONTRADA = "Matriz não encontrada para leitura diagnóstica."
TURMA_SEM_MATRIZ = "Turma PPA-T50: sem matriz vinculada."
INDICE = "Informe turma_id, turma_codigo ou matriz_id para carregar a visualização diagnóstica."
VIEW = "/admin/diagnostico/atividades-versionadas/view"
JSON = "/admin/diagnostico/atividades-versionadas"

UNRESOLVABLE = (
    ("turma_id=99999", TURMA_NAO_ENCONTRADA),
    ("turma_id=-3", TURMA_NAO_ENCONTRADA),
    (f"turma_id={2**63}", TURMA_NAO_ENCONTRADA),
    ("turma_codigo=NAO-EXISTE", TURMA_NAO_ENCONTRADA),
    ("matriz_id=99999", MATRIZ_NAO_ENCONTRADA),
    (f"matriz_id={2**63}", MATRIZ_NAO_ENCONTRADA),
)
TURMA_SEM_MATRIZ_QUERIES = (
    (f"turma_id={TURMA_SEM_MATRIZ_ID}", {"modo": "turma", "turma_id": TURMA_SEM_MATRIZ_ID, "matriz_id": None}),
    ("turma_codigo=PPA-T50", {
        "modo": "turma_codigo", "turma_codigo": "PPA-T50", "turma_id": TURMA_SEM_MATRIZ_ID, "matriz_id": None,
    }),
)

# The page message paragraph; the intro notes open with whitespace.
_MESSAGE = re.compile(r'<p class="(diag-alert|diag-note)">(\S[^<]*)</p>')


@pytest.fixture()
def lookup_client(tmp_path):
    with isolated_versioned_app_env(tmp_path, "diagnostic_lookup.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "INSERT INTO turmas (id, nome, turno, status, numero, curso_id, matriz_id,"
                " ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)"
                " VALUES (?, 'PPA-T50', 'Manhã', 'Ativa', 50, 1, NULL, 2026, 1, 2029, 2, 'PPA-T50')",
                (TURMA_SEM_MATRIZ_ID,),
            )
            conn.execute(
                "INSERT INTO matrizes_atividades (id, curso_id, nome, status,"
                " horas_aac_obrigatorias, horas_extensao_obrigatorias)"
                " VALUES (?, 1, 'Matriz PPA', 'rascunho', 200, 100)",
                (MATRIZ_VAZIA_ID,),
            )
            conn.commit()
        client = env["client"]
        with client.session_transaction() as session:
            session.update(user_id=1, user_type="admin", user_name="Admin")
            stamp_auth_version(session)
        yield client


@pytest.mark.parametrize("query,message", UNRESOLVABLE)
def test_view_answers_an_unresolvable_lookup_with_404_and_the_red_alert(lookup_client, query, message):
    response = lookup_client.get(f"{VIEW}?{query}")
    html = response.get_data(as_text=True)
    assert response.status_code == 404
    assert _MESSAGE.findall(html) == [("diag-alert", message)]
    assert 'id="diagnostico-versionado"' not in html


@pytest.mark.parametrize("query,message", UNRESOLVABLE)
def test_json_answers_an_unresolvable_lookup_with_404(lookup_client, query, message):
    response = lookup_client.get(f"{JSON}?{query}")
    assert response.status_code == 404
    assert response.get_json() == {"ok": False, "message": message}


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


@pytest.mark.parametrize("query", ["", "turma_id=abc", "turma_id=0"])
def test_index_and_non_numeric_ids_stay_a_neutral_prompt(lookup_client, query):
    response = lookup_client.get(f"{VIEW}?{query}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert _MESSAGE.findall(html) == [("diag-note", INDICE)]
    assert 'class="diag-alert"' not in html


def test_a_matrix_without_versions_is_a_neutral_empty_result(lookup_client):
    response = lookup_client.get(f"{VIEW}?matriz_id={MATRIZ_VAZIA_ID}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-total-geral="0"' in html
    assert html.count('<p class="diag-empty">Sem atividades para este eixo na consulta atual.</p>') == 2
    assert _MESSAGE.findall(html) == []
    assert 'class="diag-alert"' not in html


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
    return client


@pytest.mark.parametrize("path", [VIEW, JSON])
@pytest.mark.parametrize("actor", ["anonimo", "aluno", "admin sem atividades"])
def test_an_unauthorized_actor_is_refused_before_any_lookup(tmp_path, path, actor):
    with isolated_versioned_app_env(tmp_path, "diagnostic_denied.db") as env:
        client = _denied_client(env, actor)
        response = client.get(f"{path}?turma_id=99999")
        body = response.get_data(as_text=True)
    assert response.status_code in {302, 403}
    if actor != "admin sem atividades":
        assert response.status_code == 302 and "/login" in response.headers["Location"]
    assert TURMA_NAO_ENCONTRADA not in body
