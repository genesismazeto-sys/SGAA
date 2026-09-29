"""UI-B27: a rejected Nova requisição comes back with the student's values.

Trace: every rejection branch of ``aluno_nova_requisicao`` (no activity, an
activity outside the student's matrix, an invalid comprovante, a snapshot or
storage error) re-rendered ``aluno_nova_requisicao.html`` without ``init`` --
the only source the template (and its JS prefill of Tipo/Grupo/Atividade)
reads values from -- so the student got an empty form back.

Now the same render carries ``init`` built from the submitted fields only.
The native file input is legitimately empty after the round trip (a page can
never restore local file selections) and nothing pretends otherwise; a failed
submission still creates nothing and stores no file.
"""
from __future__ import annotations

import json
import re
from io import BytesIO

import pytest
from markupsafe import escape

import main
from tests.cdp_browser_support import BrowserSession, find_chromium
from tests.test_comprovantes_google_drive import PDF, PNG, FakeStorage
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-b27.db") as environment:
        storage = FakeStorage()
        original = main.app.extensions.get("comprovante_storage")
        main.app.extensions["comprovante_storage"] = storage
        try:
            yield {**environment, "storage": storage}
        finally:
            if original is None:
                main.app.extensions.pop("comprovante_storage", None)
            else:
                main.app.extensions["comprovante_storage"] = original


def _student():
    with main.app.app_context():
        return dict(main.get_db_connection().execute(
            """SELECT a.id,a.usuario_id,a.turma_id FROM alunos a JOIN usuarios u ON u.id=a.usuario_id
                WHERE u.tipo='aluno' ORDER BY a.id LIMIT 1"""
        ).fetchone())


def _allowed_activity(student):
    with main.app.app_context():
        row = main.get_db_connection().execute(
            """SELECT v.id, v.grupo FROM turmas t
                 JOIN matriz_atividade_versao_item item ON item.matriz_id=t.matriz_id
                 JOIN atividade_versao v ON v.id=item.atividade_versao_id
                WHERE t.id=? AND v.status='ativa' AND v.eixo='AAC' ORDER BY item.id LIMIT 1""",
            (student["turma_id"],),
        ).fetchone()
        return int(row["id"]), str(row["grupo"])


def _foreign_activity(student):
    with main.app.app_context():
        return int(main.get_db_connection().execute(
            """SELECT v.id FROM atividade_versao v
                WHERE v.id NOT IN (SELECT item.atividade_versao_id FROM turmas t
                                    JOIN matriz_atividade_versao_item item ON item.matriz_id=t.matriz_id
                                   WHERE t.id=?)
                ORDER BY v.id LIMIT 1""",
            (student["turma_id"],),
        ).fetchone()[0])


def _login(client):
    student = _student()
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=student["usuario_id"], user_type="aluno")
        stamp_auth_version(session)
    return student


def _form(activity_id, grupo, **overrides):
    data = {
        "comprovantes_operation_id": "b27-op",
        "tipo_atividade": "Acadêmica Complementar",
        "grupo": grupo,
        "atividade_versao_id": str(activity_id) if activity_id else "",
        "nome_evento": "Palestra Segurança B27",
        "data_evento": "2026-08-14",
        "horas_solicitadas": "3.5",
        "observacao": "Observação que não pode se perder",
    }
    data.update(overrides)
    return data


def _post(client, data, files=()):
    payload = dict(data)
    if files:
        payload["comprovantes_files"] = [(BytesIO(content), name) for content, name in files]
    return client.post("/aluno/nova-requisicao", data=payload, content_type="multipart/form-data")


def _init(html):
    raw = re.search(r'<script id="init-form-json" type="application/json">(.*?)</script>', html, re.S)
    assert raw, "the prefill payload is gone"
    return json.loads(raw.group(1))


def _count(name="Palestra Segurança B27"):
    with main.app.app_context():
        conn = main.get_db_connection()
        return (
            conn.execute("SELECT COUNT(*) FROM requisicoes WHERE nome_evento=?", (name,)).fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM requisicao_arquivos").fetchone()[0],
        )


def _assert_fields_rendered(html, data):
    assert f'value="{data["nome_evento"]}"' in html
    assert f'value="{data["data_evento"]}"' in html
    assert f'value="{data["horas_solicitadas"]}"' in html
    assert f'>{data["observacao"]}</textarea>' in html


# ------------------------------------------------------------ server side


def test_missing_activity_keeps_every_typed_value(env):
    client = env["client"]
    student = _login(client)
    _activity, grupo = _allowed_activity(student)
    data = _form(None, grupo)
    response = _post(client, data)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Selecione uma atividade válida." in html
    _assert_fields_rendered(html, data)
    init = _init(html)
    assert init["tipo_atividade"] == "Acadêmica Complementar" and init["grupo"] == grupo
    assert init["atividade_versao_id"] is None
    assert _count() == (0, 0)


def test_an_activity_outside_the_matrix_is_not_echoed_but_the_rest_is(env):
    client = env["client"]
    student = _login(client)
    _activity, grupo = _allowed_activity(student)
    data = _form(_foreign_activity(student), grupo)
    html = _post(client, data).get_data(as_text=True)
    assert "A atividade selecionada não está disponível para a matriz da sua turma." in html
    _assert_fields_rendered(html, data)
    assert _init(html)["atividade_versao_id"] is None
    assert _count() == (0, 0)


def test_an_invalid_file_keeps_the_values_and_claims_no_attachment(env):
    client = env["client"]
    student = _login(client)
    activity, grupo = _allowed_activity(student)
    data = _form(activity, grupo)
    html = _post(client, data, files=[(PDF, "certificado.pdf"), (b"x", "planilha.xlsx")]).get_data(as_text=True)
    assert "planilha.xlsx: envie somente arquivos PDF, PNG ou JPEG." in html
    _assert_fields_rendered(html, data)
    assert _init(html)["atividade_versao_id"] == activity
    # The native input is empty after the round trip and the page says so.
    listing = html.split('id="comprovantes-list"', 1)[1].split("</ul>", 1)[0]
    assert " hidden>" in listing.split("\n", 1)[0] and "file-list-item" not in listing
    assert '<div class="control file-name" data-file-name>Nenhum arquivo selecionado</div>' in html
    assert "certificado.pdf" not in html
    # Nothing was created, stored or uploaded.
    assert _count() == (0, 0)
    assert env["storage"].upload_calls == []


def test_a_corrected_retry_saves_exactly_once(env):
    client = env["client"]
    student = _login(client)
    activity, grupo = _allowed_activity(student)
    data = _form(activity, grupo)
    failed = _post(client, data, files=[(b"x", "planilha.xlsx")]).get_data(as_text=True)
    operation = re.search(r'name="comprovantes_operation_id" value="([^"]+)"', failed).group(1)
    assert operation != "b27-op", "the retry is a new, intentional operation"
    retry = _post(client, {**data, "comprovantes_operation_id": operation}, files=[(PDF, "a.pdf"), (PNG, "b.png")])
    assert retry.status_code == 302
    assert _count() == (1, 2)


def test_echoed_values_stay_inert_markup(env):
    client = env["client"]
    student = _login(client)
    _activity, grupo = _allowed_activity(student)
    hostile = '"><script>alert(1)</script>'
    data = _form(None, grupo, nome_evento=hostile, observacao="</textarea><img src=x onerror=alert(1)>",
                 data_evento="2026-13-99<b>", horas_solicitadas="2")
    html = _post(client, data).get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "<img src=x" not in html
    assert f'value="{escape(hostile)}"' in html
    init = _init(html)
    assert init["nome_evento"] == hostile and init["data_evento"] == ""


def test_the_student_route_stays_student_only(env):
    client = env["client"]
    with main.app.app_context():
        admin = main.get_db_connection().execute("SELECT id FROM usuarios WHERE tipo='admin' LIMIT 1").fetchone()[0]
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=admin, user_type="admin")
        stamp_auth_version(session)
    student = _student()
    activity, grupo = _allowed_activity(student)
    response = _post(client, _form(activity, grupo))
    assert response.status_code == 302 and "/aluno/nova-requisicao" not in response.headers["Location"]
    assert _count() == (0, 0)


# ---------------------------------------------------------------- browser

CHROMIUM = find_chromium()


@pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")
def test_the_rerendered_form_reselects_tipo_grupo_and_activity_in_the_browser(env):
    client = env["client"]
    student = _login(client)
    activity, grupo = _allowed_activity(student)
    data = _form(activity, grupo)
    failed = _post(client, data, files=[(b"x", "planilha.xlsx")]).get_data(as_text=True).encode("utf-8")
    session = BrowserSession(client, CHROMIUM)
    try:
        session.response_rewrites["/aluno/nova-requisicao"] = lambda _payload: failed
        session.goto("/aluno/nova-requisicao")
        state = json.loads(session.evaluate("""JSON.stringify({
          tipo: document.getElementById('tipo_atividade_select').value,
          grupo: document.getElementById('grupo_num').value,
          grupoHidden: document.getElementById('grupo_hidden').value,
          atividade: document.getElementById('atividade_versao_id_select').value,
          nome: document.querySelector('[name=nome_evento]').value,
          data: document.querySelector('[name=data_evento]').value,
          horas: document.querySelector('[name=horas_solicitadas]').value,
          obs: document.querySelector('[name=observacao]').value,
          files: document.getElementById('comprovantes_files').files.length,
          listHidden: document.getElementById('comprovantes-list').hidden,
        })"""))
    finally:
        session.close()
    assert state == {
        "tipo": "Acadêmica Complementar",
        "grupo": grupo.split(" - ")[0].strip() if " - " in grupo else grupo,
        "grupoHidden": grupo,
        "atividade": str(activity),
        "nome": data["nome_evento"],
        "data": data["data_evento"],
        "horas": data["horas_solicitadas"],
        "obs": data["observacao"],
        "files": 0,
        "listHidden": True,
    }
