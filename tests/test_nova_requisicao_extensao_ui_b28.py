"""UI-B28: Nova requisição offers Extensão Universitária activities.

Root cause: ``aluno_nova_requisicao`` built its activity list with
``_list_atividades_for_usuario(conn, usuario_id, request.args.get("tipo",
"Acadêmica Complementar"))``. The matrix catalogue itself returns every
activity of the student's matrix (both eixos, each with its authoritative
type); the helper then kept only ``tipo_atividade == tipo_filtro``. Nothing
links to the page with ``?tipo=``, and the Tipo select only filters
client-side, so "Extensão Universitária" always showed no group and no
activity. That filter enforced nothing else -- eligibility is matrix
membership (POST check) plus an active version (snapshot layer), both unchanged.

Now the page lists the whole matrix and the Tipo select filters it; ``?tipo=``
only preselects the Tipo. The backend stays the authority: an activity outside
the matrix is refused, and a submitted Tipo that contradicts the activity's own
type (a crafted cross-type POST) is refused too.
"""
from __future__ import annotations

import json
import re

import pytest

import main
from tests.canonical_request_documents_support import (
    INTENT_IDS_FIELD,
    SUBMISSION_FIELD,
    canonical_documents,
    form_submission,
    upload_verified,
)
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.session_support import stamp_auth_version
from tests.test_comprovantes_google_drive import PDF, PNG, FakeStorage
from tests.versioned_test_support import isolated_versioned_app_env

AAC = "Acadêmica Complementar"
AEU = "Extensão Universitária"


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-b28.db") as environment:
        storage = FakeStorage()
        original = main.app.extensions.get("comprovante_storage")
        main.app.extensions["comprovante_storage"] = storage
        try:
            _login(environment["client"])
            with canonical_documents(main.app) as canonical:
                yield {**environment, "storage": storage, "canonical": canonical}
        finally:
            if original is None:
                main.app.extensions.pop("comprovante_storage", None)
            else:
                main.app.extensions["comprovante_storage"] = original


def _db():
    return main.get_db_connection()


def _student():
    with main.app.app_context():
        return dict(_db().execute(
            """SELECT a.id,a.usuario_id,a.turma_id,t.matriz_id FROM alunos a
                 JOIN usuarios u ON u.id=a.usuario_id JOIN turmas t ON t.id=a.turma_id
                WHERE u.tipo='aluno' ORDER BY a.id LIMIT 1"""
        ).fetchone())


def _login(client):
    student = _student()
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=student["usuario_id"], user_type="aluno")
        stamp_auth_version(session)


def _matrix_versions(eixo=None):
    student = _student()
    sql = """SELECT v.id, v.eixo, v.grupo FROM matriz_atividade_versao_item item
               JOIN atividade_versao v ON v.id=item.atividade_versao_id
              WHERE item.matriz_id=?"""
    params = [student["matriz_id"]]
    if eixo:
        sql += " AND v.eixo=? AND v.status='ativa'"
        params.append(eixo)
    with main.app.app_context():
        return [dict(row) for row in _db().execute(sql + " ORDER BY v.id", params)]


def _options(html):
    return [
        (int(value), tipo, grupo)
        for value, tipo, grupo in re.findall(
            r'<option value="(\d+)" data-tipo="([^"]+)" data-grupo="([^"]*)"', html
        )
    ]


def _form(activity, tipo, **overrides):
    data = {
        "comprovantes_operation_id": f"b28-{activity['id']}-{tipo[:3]}",
        "tipo_atividade": tipo,
        "grupo": activity["grupo"],
        "atividade_versao_id": str(activity["id"]),
        "nome_evento": f"Evento B28 {activity['id']}",
        "data_evento": "2026-08-20",
        "horas_solicitadas": "6",
        "observacao": "B28",
    }
    data.update(overrides)
    return data


def _post(client, data, files=()):
    """STORAGE S3-A: documents go through the direct-upload protocol; the form
    posts the submission id and the verified intent ids, never file bytes."""
    payload = dict(data)
    if files:
        store = main.app.extensions["canonical_object_store"]
        submission = form_submission(client, "/aluno/nova-requisicao")
        payload[SUBMISSION_FIELD] = submission
        payload[INTENT_IDS_FIELD] = [upload_verified(client, store, submission, content, name)
                                     for content, name in files]
    return client.post("/aluno/nova-requisicao", data=payload)


def _refused_document_post(client, data):
    """A submission carrying a document the server must not attach."""
    submission = form_submission(client, "/aluno/nova-requisicao")
    return client.post("/aluno/nova-requisicao", data={
        **data, SUBMISSION_FIELD: submission, INTENT_IDS_FIELD: ["f" * 32],
    })


def _requests():
    with main.app.app_context():
        return [dict(row) for row in _db().execute("SELECT * FROM requisicoes ORDER BY id")]


# ------------------------------------------------------------------ dataset


def test_the_page_lists_both_families_of_the_student_matrix_and_nothing_else(env):
    html = env["client"].get("/aluno/nova-requisicao").get_data(as_text=True)
    options = _options(html)
    listed = {option_id for option_id, _tipo, _grupo in options}
    assert listed == {row["id"] for row in _matrix_versions()}
    tipos = {tipo for _id, tipo, _grupo in options}
    assert tipos == {AAC, AEU}
    by_id = {row["id"]: row for row in _matrix_versions()}
    for option_id, tipo, _grupo in options:
        assert tipo == (AAC if by_id[option_id]["eixo"] == "AAC" else AEU)
    # The Tipo select still opens on Acadêmica.
    assert re.search(r'<option value="Acadêmica Complementar" selected>', html)


def test_tipo_query_only_preselects_the_tipo(env):
    html = env["client"].get("/aluno/nova-requisicao?tipo=Extensão Universitária").get_data(as_text=True)
    assert re.search(r'<option value="Extensão Universitária" selected>', html)
    assert {tipo for _id, tipo, _grupo in _options(html)} == {AAC, AEU}
    bogus = env["client"].get("/aluno/nova-requisicao?tipo=qualquer").get_data(as_text=True)
    assert re.search(r'<option value="Acadêmica Complementar" selected>', bogus)


# ------------------------------------------------------------------ create


def test_a_valid_academica_request_still_succeeds(env):
    activity = _matrix_versions("AAC")[0]
    response = _post(env["client"], _form(activity, AAC))
    assert response.status_code == 302
    created = _requests()[-1]
    assert created["atividade_versao_id"] == activity["id"]
    assert json.loads(created["regra_snapshot_json"])["eixo"] == "AAC"


def test_a_valid_extensao_request_succeeds_with_two_comprovantes(env):
    activity = _matrix_versions("AEU")[0]
    response = _post(env["client"], _form(activity, AEU), files=[(PDF, "certificado.pdf"), (PNG, "foto.png")])
    assert response.status_code == 302
    created = _requests()[-1]
    snapshot = json.loads(created["regra_snapshot_json"])
    assert created["atividade_versao_id"] == activity["id"]
    assert snapshot["eixo"] == "AEU" and snapshot["tipo_atividade"] == AEU
    assert created["horas_solicitadas"] == 6.0 and created["status"] == "Pendente"
    assert created["nome_evento"] == f"Evento B28 {activity['id']}" and created["data_evento"] == "2026-08-20"
    with main.app.app_context():
        files = _db().execute(
            "SELECT original_filename,storage_status FROM requisicao_arquivos WHERE requisicao_id=? ORDER BY id",
            (created["id"],),
        ).fetchall()
    assert [tuple(row) for row in files] == [("certificado.pdf", "active"), ("foto.png", "active")]
    listing = env["client"].get("/aluno/requisicoes").get_data(as_text=True)
    assert f"Evento B28 {activity['id']}" in listing or str(created["id"]) in listing


@pytest.mark.parametrize("eixo,claimed", [("AEU", AAC), ("AAC", AEU), ("AEU", "Qualquer")])
def test_a_crafted_cross_type_post_is_refused(env, eixo, claimed):
    activity = _matrix_versions(eixo)[0]
    before = _requests()
    response = _post(env["client"], _form(activity, claimed))
    html = response.get_data(as_text=True)
    assert response.status_code == 200 and "Selecione uma atividade válida." in html
    assert _requests() == before
    init = json.loads(re.search(r'<script id="init-form-json" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert init["atividade_versao_id"] is None


def test_an_activity_outside_the_matrix_is_refused(env):
    in_matrix = {row["id"] for row in _matrix_versions()}
    with main.app.app_context():
        outside = dict(_db().execute(
            "SELECT id, eixo, grupo FROM atividade_versao WHERE id NOT IN (%s) ORDER BY id LIMIT 1"
            % ",".join(str(i) for i in in_matrix)
        ).fetchone())
    before = _requests()
    html = _post(env["client"], _form(outside, AEU if outside["eixo"] == "AEU" else AAC)).get_data(as_text=True)
    assert "A atividade selecionada não está disponível para a matriz da sua turma." in html
    assert _requests() == before


def test_a_post_without_tipo_keeps_working(env):
    activity = _matrix_versions("AEU")[0]
    data = _form(activity, AEU)
    data.pop("tipo_atividade")
    assert _post(env["client"], data).status_code == 302
    assert _requests()[-1]["atividade_versao_id"] == activity["id"]


# ---------------------------------------------------------------- browser

CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")

FILTER_STATE = """JSON.stringify((() => {
  const tipo = document.getElementById('tipo_atividade_select');
  const grupo = document.getElementById('grupo_num');
  const atv = document.getElementById('atividade_versao_id_select');
  tipo.value = %s; tipo.dispatchEvent(new Event('change'));
  const grupos = Array.from(grupo.options).map(o => o.value).filter(Boolean);
  const out = {grupos, visible: []};
  for (const g of grupos) {
    grupo.value = g; grupo.dispatchEvent(new Event('change'));
    Array.from(atv.options).filter(o => !o.hidden && o.value).forEach(o => out.visible.push([o.value, o.getAttribute('data-tipo')]));
  }
  return out;
})())"""


@browser
def test_the_tipo_select_filters_each_family(env):
    session = BrowserSession(env["client"], CHROMIUM)
    try:
        session.goto("/aluno/nova-requisicao")
        academic = json.loads(session.evaluate(FILTER_STATE % json.dumps(AAC)))
        extension = json.loads(session.evaluate(FILTER_STATE % json.dumps(AEU)))
    finally:
        session.close()
    aac_ids = {str(row["id"]) for row in _matrix_versions() if row["eixo"] == "AAC"}
    aeu_ids = {str(row["id"]) for row in _matrix_versions() if row["eixo"] == "AEU"}
    assert academic["grupos"] and {tipo for _v, tipo in academic["visible"]} == {AAC}
    assert {value for value, _t in academic["visible"]} == aac_ids
    assert extension["grupos"] and {tipo for _v, tipo in extension["visible"]} == {AEU}
    assert {value for value, _t in extension["visible"]} == aeu_ids


@browser
def test_a_rejected_extensao_request_comes_back_as_extensao(env):
    activity = _matrix_versions("AEU")[0]
    data = _form(activity, AEU)
    failed = _refused_document_post(env["client"], data).get_data(as_text=True)
    assert "Os comprovantes enviados não pertencem a esta requisição." in failed
    assert _requests() == []
    session = BrowserSession(env["client"], CHROMIUM)
    try:
        session.response_rewrites["/aluno/nova-requisicao"] = lambda _payload: failed.encode("utf-8")
        session.goto("/aluno/nova-requisicao")
        state = json.loads(session.evaluate("""JSON.stringify({
          tipo: document.getElementById('tipo_atividade_select').value,
          grupo: document.getElementById('grupo_num').value,
          atividade: document.getElementById('atividade_versao_id_select').value,
          nome: document.querySelector('[name=nome_evento]').value,
          horas: document.querySelector('[name=horas_solicitadas]').value,
          data: document.querySelector('[name=data_evento]').value})"""))
    finally:
        session.close()
    grupo = activity["grupo"].split(" - ")[0].strip() if " - " in activity["grupo"] else activity["grupo"]
    assert state == {
        "tipo": AEU, "grupo": grupo, "atividade": str(activity["id"]),
        "nome": data["nome_evento"], "horas": "6", "data": "2026-08-20",
    }
