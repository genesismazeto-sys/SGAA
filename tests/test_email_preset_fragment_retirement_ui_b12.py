"""UI-B12 (decision B): grammatical fragment placeholders leave the authoring contract.

``{requisicao.possessivo}``, ``{requisicao.substantivo}`` and
``{requisicao.processamento}`` are each correct alone, but a preset has to glue
literal words around them -- "Suas {requisicao.substantivo}" -- which is how
broken agreement reaches a student.  ``{requisicao.frase}`` (whole body
sentence) and ``{atividade.substantivo}`` (subject noun phrase, used by the
canonical default) stay.

Contract:

* the retired fragments are not offered (help, editor chips) and are rejected on
  any new or edited save, server-side;
* a stored model that predates the retirement is not rewritten: it round-trips
  through the all-models save untouched and still renders exactly as before;
* preview and send share one renderer (``build_plan``), so both honour the same
  contract;
* administrator free text is stored verbatim -- no heuristic rewriting.
"""

from __future__ import annotations

import sqlite3

import pytest

import main
import presets_api
from app.request_email_dispatch import build_plan
from app.request_email_render import (
    DEFAULT_BODY_TEMPLATE,
    DEFAULT_SUBJECT_TEMPLATE,
    PLACEHOLDER_HELP,
    RETIRED_PLACEHOLDERS,
    SCALAR_PLACEHOLDERS,
    PlaceholderError,
    render_student_email,
    validate_template,
)
from tests.request_email_support import decide, new_v7_connection, seed_activity, seed_request, seed_student
from tests.test_aluno_turma_header_ui_c06 import _actor, _login
from tests.versioned_test_support import isolated_versioned_app_env

RETIRED_TOKENS = ("{requisicao.possessivo}", "{requisicao.substantivo}", "{requisicao.processamento}")


def _plan(dates, template):
    conn = new_v7_connection()
    versao = seed_activity(conn)
    aluno = seed_student(conn, nome="Aluno Teste", matricula="1", email="a@x.com")
    ids = []
    for day in dates:
        req = seed_request(conn, aluno_id=aluno, versao_id=versao, data_solicitacao=day)
        decide(conn, req, status="Deferida")
        ids.append(req)
    return build_plan(conn, ids, template)


# --------------------------------------------------------------- vocabulary

def test_retired_set_is_exactly_the_three_request_fragments():
    assert RETIRED_PLACEHOLDERS == (
        "requisicao.possessivo",
        "requisicao.substantivo",
        "requisicao.processamento",
    )
    assert not set(RETIRED_PLACEHOLDERS) & set(SCALAR_PLACEHOLDERS)
    assert {"requisicao.frase", "atividade.substantivo", "data.periodo"} <= set(SCALAR_PLACEHOLDERS)


def test_retired_fragments_are_absent_from_the_help_and_every_offered_token_is_supported():
    offered = [token for token, _help in PLACEHOLDER_HELP]
    for token in RETIRED_TOKENS:
        assert token not in offered
    for token in offered:
        validate_template(token, allow_block=True)  # every chip is saveable


@pytest.mark.parametrize("token", RETIRED_TOKENS)
def test_retired_fragment_is_rejected_for_new_authoring_in_subject_and_body(token):
    with pytest.raises(PlaceholderError, match="descontinuado"):
        validate_template(f"Suas {token}", allow_block=True)
    with pytest.raises(PlaceholderError, match="descontinuado"):
        validate_template(f"Assunto {token}", allow_block=False)


def test_the_canonical_default_model_uses_only_supported_tokens():
    validate_template(DEFAULT_SUBJECT_TEMPLATE, allow_block=False)
    validate_template(DEFAULT_BODY_TEMPLATE, allow_block=True)
    assert DEFAULT_SUBJECT_TEMPLATE == "Processamento de {atividade.substantivo}"
    assert "{requisicao.frase}" in DEFAULT_BODY_TEMPLATE


# ---------------------------------------------------- safe tokens, 1 vs 2+

def test_safe_tokens_agree_in_number_through_the_shared_plan():
    template = {"assunto": DEFAULT_SUBJECT_TEMPLATE, "texto": DEFAULT_BODY_TEMPLATE}
    [one] = _plan(["2026-09-15"], template)
    [two] = _plan(["2026-09-15", "2026-09-18"], template)
    assert one["assunto"] == "Processamento de atividade acadêmica"
    assert "Sua requisição do dia 15/09/2026 foi processada." in one["corpo"]
    assert two["assunto"] == "Processamento de atividades acadêmicas"
    assert "Suas requisições de 15/09/2026 a 18/09/2026 foram processadas." in two["corpo"]
    assert not one["blocked"] and not two["blocked"]


def test_a_stored_legacy_model_still_renders_the_same_in_preview_and_send():
    """Render-only compatibility: nothing already stored stops sending."""
    legacy = {
        "assunto": "Aviso",
        "texto": "{requisicao.possessivo} {requisicao.substantivo} {requisicao.processamento}.",
    }
    [one] = _plan(["2026-09-15"], legacy)
    [two] = _plan(["2026-09-15", "2026-09-15"], legacy)
    assert one["corpo"] == "Sua solicitação foi processada." and not one["blocked"]
    assert two["corpo"] == "Suas solicitações foram processadas." and not two["blocked"]
    # build_plan is the single renderer behind both the preview and the send.
    subject, body = render_student_email(
        assunto=legacy["assunto"], corpo=legacy["texto"], events=[{
            "requisicao_id": 1, "data_solicitacao": "2026-09-15", "atividade_nome": "", "nome_evento": "",
            "status_decisao": "Deferida", "horas_solicitadas": 1, "horas_deferidas": None, "justificativa": "",
        }], aluno_nome="Aluno", aluno_matricula="1",
    )
    assert (subject, body) == ("Aviso", one["corpo"])


# ------------------------------------------------------------ server save

@pytest.fixture
def admin_client(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-b12.db") as env:
        client = env["client"]
        _login(client, _actor("admin_total"))
        yield client


def _stored_emails():
    conn = sqlite3.connect(main.DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        return {
            int(row["preset_id"]): (row["titulo"], row["assunto"], row["texto"])
            for row in conn.execute(
                f"SELECT preset_id, titulo, assunto, texto FROM {presets_api.PRESETS_TABLE} WHERE tipo='emails'"
            )
        }
    finally:
        conn.close()


def _insert_legacy(preset_id, assunto, texto):
    conn = sqlite3.connect(main.DATABASE)
    try:
        presets_api.ensure_presets_schema(conn)
        conn.execute(
            f"INSERT INTO {presets_api.PRESETS_TABLE}(tipo,preset_id,titulo,texto,atualizado_em,assunto,is_default)"
            " VALUES ('emails',?,?,?,datetime('now'),?,0)",
            (preset_id, "Legado", texto, assunto),
        )
        conn.commit()
    finally:
        conn.close()


def _email(preset_id, texto, assunto="Assunto", titulo="Modelo"):
    return {"id": preset_id, "titulo": titulo, "assunto": assunto, "texto": texto, "is_default": False}


@pytest.mark.parametrize("token", RETIRED_TOKENS)
def test_new_save_with_a_retired_fragment_is_refused_by_the_server(admin_client, token):
    before = _stored_emails()
    response = admin_client.post("/admin/api/presets", json={"respostas": [], "emails": [_email(5, f"Suas {token}")]})
    assert response.status_code == 400
    assert "descontinuado" in (response.get_json() or {}).get("detail", "")
    assert _stored_emails() == before


def test_editing_a_legacy_model_must_drop_the_retired_fragment(admin_client):
    legacy_body = "{requisicao.possessivo} {requisicao.substantivo} foi recebida."
    _insert_legacy(9, "Aviso", legacy_body)
    edited = admin_client.post("/admin/api/presets", json={
        "respostas": [], "emails": [_email(9, legacy_body + " Obrigado.", assunto="Aviso", titulo="Legado")],
    })
    assert edited.status_code == 400 and "descontinuado" in edited.get_json()["detail"]
    moved = admin_client.post("/admin/api/presets", json={
        "respostas": [], "emails": [_email(10, legacy_body, assunto="Aviso", titulo="Cópia")],
    })
    assert moved.status_code == 400, "a retired fragment cannot be copied into a different model"
    assert _stored_emails()[9] == ("Legado", "Aviso", legacy_body)


def test_an_untouched_legacy_model_round_trips_while_another_model_is_saved(admin_client):
    legacy_body = "{requisicao.possessivo} {requisicao.substantivo} foi recebida."
    _insert_legacy(9, "Aviso", legacy_body)
    response = admin_client.post("/admin/api/presets", json={
        "respostas": [],
        "emails": [
            _email(9, legacy_body, assunto="Aviso", titulo="Legado"),
            _email(11, "{saudacao}, {aluno.primeironome}.\n\n{requisicao.frase}"),
        ],
    })
    assert response.status_code == 200, response.get_json()
    stored = _stored_emails()
    assert stored[9] == ("Legado", "Aviso", legacy_body)  # not rewritten
    assert stored[11][2] == "{saudacao}, {aluno.primeironome}.\n\n{requisicao.frase}"


def test_administrator_free_text_is_stored_verbatim(admin_client):
    prose = "Suas requisição do dia {data.inicio} foi processada. Acesse o SGAA para conferir."
    response = admin_client.post("/admin/api/presets", json={
        "respostas": [], "emails": [_email(3, prose, assunto="Processamento de atividades acadêmicas")],
    })
    assert response.status_code == 200
    assert _stored_emails()[3][1:] == ("Processamento de atividades acadêmicas", prose)


def test_the_editor_offers_no_retired_fragment(admin_client):
    page = admin_client.get("/admin/requisicoes").get_data(as_text=True)
    assert 'data-token="{requisicao.frase}"' in page
    assert 'data-token="{atividade.substantivo}"' in page
    for token in RETIRED_TOKENS:
        assert token not in page
