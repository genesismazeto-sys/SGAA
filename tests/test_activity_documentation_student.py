"""The student side of Documentação exigida: what the request form is given, and
who may download a template.

The block is rendered in the browser from ``#atividade-orientacoes-json``,
keyed by the exact activity version; these tests pin that data, the download
authorization and the informative-only rule (a request without the listed
proofs is still accepted). The browser behaviour is in
``tests/test_activity_documentation_browser.py``.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re

import pytest

import main
from app.prod1_document_templates_ddl import DOCX_MIME_TYPE
from app.student_matrix import get_effective_matrix_for_student
from tests.canonical_request_test_support import login_student, student_identity
from tests.docx_test_support import ANEXO_3_TITULO, ANEXO_5_TITULO, make_docx
from tests.versioned_test_support import isolated_versioned_app_env

ANEXO_3 = make_docx("Anexo 3 — Leitura de livro/filme (arquivo sintético de teste)")
ANEXO_5 = make_docx(
    "Anexo 5 — Atividades de monitoria, apoio institucional e visitas técnicas (arquivo sintético de teste)"
)
RETIRADO = make_docx("Modelo antigo")
# What versions held before the list existed: a regulation sentence, not a proof.
OLDER_TEXT = "A validação será feita mediante certificado emitido pela instituição promotora do evento."


def insert_template(conn, version_id, title, content, *, slot, status="ativo", filename=None):
    """Seed a template row directly (setup only: the owner refuses frozen versions).

    ``filename`` is the download name; a title may hold a "/" (Anexo 3), a file name not.
    """
    digest = hashlib.sha256(content).hexdigest()
    conn.execute(
        "INSERT INTO modelo_documento_arquivos (sha256, mime_type, size_bytes, conteudo) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (sha256) DO NOTHING",
        (digest, DOCX_MIME_TYPE, len(content), content),
    )
    content_id = conn.execute("SELECT id FROM modelo_documento_arquivos WHERE sha256 = ?", (digest,)).fetchone()[0]
    ended = "datetime('now')" if status != "ativo" else "NULL"
    return conn.execute(
        "INSERT INTO atividade_versao_modelos (atividade_versao_id, arquivo_id, titulo, nome_arquivo, ordem, status,"
        f" encerrado_em) VALUES (?, ?, ?, ?, ?, ?, {ended}) RETURNING id",
        (version_id, content_id, title, filename or f"{title}.docx", slot, status),
    ).fetchone()[0]


def matrix_versions(conn, matriz_id):
    return [
        row[0] for row in conn.execute(
            "SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id = ? ORDER BY atividade_versao_id",
            (matriz_id,),
        )
    ]


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "documentation-student.db") as environment:
        with main.app.app_context():
            conn = main.get_db_connection()
            student = student_identity()
            matriz_id = int(get_effective_matrix_for_student(conn, student["aluno_id"])["id"])
            other_matriz = conn.execute(
                "SELECT id FROM matrizes_atividades WHERE id <> ? ORDER BY id LIMIT 1", (matriz_id,)
            ).fetchone()[0]
            own = matrix_versions(conn, matriz_id)
            foreign = [v for v in matrix_versions(conn, other_matriz) if v not in own]
            with_docs, plain, templates_only = own[0], own[1], own[2]
            conn.execute(
                "UPDATE atividade_versao SET documentos_json = ? WHERE id = ?",
                (json.dumps({"comprovantes_exigidos": ["Certificado de participação",
                                                       "Relatório da atividade (Anexo 3)"]},
                            ensure_ascii=False), with_docs),
            )
            conn.execute(
                "UPDATE atividade_versao SET documentos_json = ? WHERE id = ?",
                (json.dumps([OLDER_TEXT], ensure_ascii=False), plain),
            )
            conn.execute("UPDATE atividade_versao SET documentos_json = '[]' WHERE id = ?", (templates_only,))
            ids = {
                "anexo_3": insert_template(conn, with_docs, ANEXO_3_TITULO, ANEXO_3, slot=1, filename="Anexo 3.docx"),
                "anexo_5": insert_template(conn, with_docs, ANEXO_5_TITULO, ANEXO_5, slot=2),
                "retirado": insert_template(conn, templates_only, "Modelo antigo", RETIRADO, slot=1, status="retirado"),
                "vigente": insert_template(conn, templates_only, "Modelo vigente", ANEXO_5, slot=2),
                "estrangeiro": insert_template(conn, foreign[0], "Outra matriz", ANEXO_3, slot=1),
            }
            conn.commit()
        environment.update(
            student=student, matriz_id=matriz_id, with_docs=with_docs, plain=plain, templates_only=templates_only,
            foreign=foreign[0], templates=ids,
        )
        login_student(environment["client"])
        yield environment


def _guidance(html):
    match = re.search(r'<script id="atividade-orientacoes-json" type="application/json">(.*?)</script>', html, re.S)
    assert match, "the request form carries no guidance data"
    return json.loads(match.group(1))


def _init(html):
    return json.loads(re.search(r'<script id="init-form-json" type="application/json">(.*?)</script>', html, re.S).group(1))


def test_the_form_gets_the_guidance_of_each_version_and_nothing_for_versions_without_it(env):
    html = env["client"].get("/aluno/nova-requisicao").get_data(as_text=True)
    assert 'id="orientacao-comprovantes"' in html
    # Right before Comprovantes, after the activity and event fields.
    assert html.index('id="data-evento-orientacao"') < html.index('id="orientacao-comprovantes"') < html.index(
        '<label class="row-label">Comprovantes</label>'
    )
    guidance = _guidance(html)
    assert set(guidance) == {str(env["with_docs"]), str(env["templates_only"])}
    assert guidance[str(env["with_docs"])]["documentos"] == [
        "Certificado de participação", "Relatório da atividade (Anexo 3)",
    ]
    assert [m["titulo"] for m in guidance[str(env["with_docs"])]["modelos"]] == [
        ANEXO_3_TITULO, ANEXO_5_TITULO,
    ]
    only = guidance[str(env["templates_only"])]
    assert only["documentos"] == [] and [m["id"] for m in only["modelos"]] == [env["templates"]["vigente"]]
    # A foreign matrix's template is never offered, and no bytes travel with the page.
    assert str(env["foreign"]) not in guidance
    assert all(set(m) == {"id", "titulo"} for g in guidance.values() for m in g["modelos"])
    # The older regulation sentence is not a proof name: never listed.
    assert OLDER_TEXT not in html


def test_the_guidance_says_what_every_proof_must_hold(env):
    """UI-B45 (owner's wording): proof names stay short; the lead says once what each proof carries."""
    html = env["client"].get("/aluno/nova-requisicao").get_data(as_text=True)
    lead = re.search(r'<p class="doc-guidance-lead">(.*?)</p>', html, re.S).group(1)
    assert "Os comprovantes deverão conter os dados, informações e assinaturas exigidas no regulamento." in lead


@pytest.mark.parametrize("name", ["anexo_3", "anexo_5", "vigente"])
def test_the_student_downloads_the_exact_bytes_of_an_offered_template(env, name):
    response = env["client"].get(f"/aluno/modelos/{env['templates'][name]}/baixar")
    assert response.status_code == 200
    assert response.data == {"anexo_3": ANEXO_3, "anexo_5": ANEXO_5, "vigente": ANEXO_5}[name]
    assert response.mimetype == DOCX_MIME_TYPE
    assert "attachment" in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("name", ["retirado", "estrangeiro"])
def test_a_withdrawn_or_foreign_template_is_not_found_for_the_student(env, name):
    assert env["client"].get(f"/aluno/modelos/{env['templates'][name]}/baixar").status_code == 404


def test_an_unknown_template_or_an_anonymous_visitor_gets_nothing(env):
    assert env["client"].get("/aluno/modelos/999999/baixar").status_code == 404
    anonymous = main.app.test_client()
    response = anonymous.get(f"/aluno/modelos/{env['templates']['anexo_3']}/baixar")
    assert response.status_code == 302 and response.data != ANEXO_3


def test_a_request_without_the_listed_proofs_is_still_accepted(env):
    response = env["client"].post("/aluno/nova-requisicao", data={
        "tipo_atividade": "", "atividade_versao_id": str(env["with_docs"]), "nome_evento": "Palestra sem anexos",
        "data_evento": "2026-09-06", "horas_solicitadas": "2",
    })
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, atividade_versao_id FROM requisicoes WHERE nome_evento = 'Palestra sem anexos'"
        ).fetchone()
    assert (row["status"], row["atividade_versao_id"]) == ("Pendente", env["with_docs"])


def test_a_refused_submission_keeps_the_chosen_activity_and_its_guidance(env):
    response = env["client"].post("/aluno/nova-requisicao", data={
        "atividade_versao_id": str(env["with_docs"]), "nome_evento": "Com envio expirado",
        "data_evento": "2026-09-06", "horas_solicitadas": "2",
        "comprovantes_submission_id": "0" * 32, "comprovantes_intent_ids": "f" * 32,
    })
    assert response.status_code == 403
    html = response.get_data(as_text=True)
    assert _init(html)["atividade_versao_id"] == env["with_docs"]
    assert str(env["with_docs"]) in _guidance(html)


def test_edit_and_rectification_show_the_recorded_version_even_after_the_matrix_drops_it(env):
    """The view of the same request shows none (preventive guidance is for filling)."""
    client = env["client"]
    client.post("/aluno/nova-requisicao", data={
        "atividade_versao_id": str(env["with_docs"]), "nome_evento": "Editar depois",
        "data_evento": "2026-09-06", "horas_solicitadas": "2",
    })
    with main.app.app_context():
        conn = main.get_db_connection()
        request_id = conn.execute("SELECT id FROM requisicoes WHERE nome_evento = 'Editar depois'").fetchone()[0]
        conn.execute("DELETE FROM matriz_atividade_versao_item WHERE matriz_id = ? AND atividade_versao_id = ?",
                     (env["matriz_id"], env["with_docs"]))
        conn.commit()
    edit = client.get(f"/aluno/requisicoes/{request_id}?edit=1").get_data(as_text=True)
    assert _init(edit)["atividade_versao_id"] == env["with_docs"]
    assert str(env["with_docs"]) in _guidance(edit)
    # The recorded version's templates stay downloadable for this student.
    assert client.get(f"/aluno/modelos/{env['templates']['anexo_3']}/baixar").data == ANEXO_3
    with main.app.app_context():
        conn = main.get_db_connection()
        stamp = (datetime.datetime.now() - datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE requisicoes SET status='Devolvida', data_processamento=?, observacao='Faltou a declaração'"
                     " WHERE id=?", (stamp, request_id))
        conn.commit()
    rectify = client.get(f"/aluno/requisicoes/{request_id}?edit=1").get_data(as_text=True)
    assert "Retificar Requisição" in rectify
    assert str(env["with_docs"]) in _guidance(rectify) and _init(rectify)["atividade_versao_id"] == env["with_docs"]
    # The read-only view carries no guidance at all, like the field guidance (UI-B23).
    view = client.get(f"/aluno/requisicoes/{request_id}?view=1").get_data(as_text=True)
    assert 'id="orientacao-comprovantes"' not in view and 'id="atividade-orientacoes-json"' not in view
