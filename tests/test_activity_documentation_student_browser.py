"""Documentação exigida in a real Chromium, student side: the request form shows
the guidance of exactly the selected activity version, downloads its templates,
keeps it through a refused submission, an edit and a rectification, and still
accepts a request without the listed proofs.

The harness (a live server on 127.0.0.1 over an isolated SQLite database,
native downloads, opt-in screenshots) is the administrator file's.
"""
from __future__ import annotations

import datetime
import json

import main
from app.student_matrix import get_effective_matrix_for_student
from tests.canonical_request_test_support import login_student, student_identity
from tests.docx_test_support import ANEXO_3_TITULO, ANEXO_5_TITULO, make_docx
from tests.test_activity_documentation_admin_browser import (
    BINARY,
    EVIDENCE,
    ANEXO_3,
    ANEXO_5,
    Session,
    _js,
    _open,
    _submit_and_wait,
    _type,
    browser_only,
    workspace,  # noqa: F401  (pytest fixture)
)
from tests.test_activity_documentation_student import insert_template



def _seed_student_catalogue():
    with main.app.app_context():
        conn = main.get_db_connection()
        student = student_identity()
        matriz_id = int(get_effective_matrix_for_student(conn, student["aluno_id"])["id"])
        versions = [
            dict(row) for row in conn.execute(
                """SELECT v.id, v.eixo, v.grupo, b.nome_conceito FROM matriz_atividade_versao_item i
                     JOIN atividade_versao v ON v.id = i.atividade_versao_id
                     JOIN atividade_base b ON b.id = v.atividade_base_id
                    WHERE i.matriz_id = ? AND v.eixo = 'AAC' ORDER BY v.grupo, v.id""",
                (matriz_id,),
            )
        ]
        by_group: dict[str, list[dict]] = {}
        for version in versions:
            by_group.setdefault(version["grupo"], []).append(version)
        group = next(g for g, items in by_group.items() if len(items) >= 3)
        with_docs, plain, templates_only = by_group[group][:3]
        conn.execute(
            "UPDATE atividade_versao SET documentos_json = ? WHERE id = ?",
            (json.dumps({"comprovantes_exigidos": ["Relatório da atividade (Anexo 3)", "Cópia do ingresso"]},
                        ensure_ascii=False), with_docs["id"]),
        )
        # What versions held before the list existed: a sentence, never shown as a proof.
        conn.execute(
            "UPDATE atividade_versao SET documentos_json = ? WHERE id = ?",
            (json.dumps(["A validação será feita mediante certificado emitido pela instituição promotora."],
                        ensure_ascii=False), plain["id"]),
        )
        conn.execute("UPDATE atividade_versao SET documentos_json = '[]' WHERE id = ?", (templates_only["id"],))
        insert_template(conn, with_docs["id"], ANEXO_3_TITULO, ANEXO_3, slot=1, filename="Anexo 3.docx")
        insert_template(conn, templates_only["id"], ANEXO_5_TITULO, ANEXO_5, slot=1, filename="Anexo 5.docx")
        conn.commit()
    return {"group": group, "with_docs": with_docs, "plain": plain, "templates_only": templates_only}


def _choose(session, group, version_id):
    session.evaluate(
        "(() => { const tipo = document.getElementById('tipo_atividade_select'); tipo.value = 'Acadêmica Complementar';"
        " tipo.dispatchEvent(new Event('change', {bubbles: true}));"
        " const num = document.getElementById('grupo_num'); num.value = %s;"
        " num.dispatchEvent(new Event('change', {bubbles: true}));"
        " const atv = document.getElementById('atividade_versao_id_select'); atv.value = %s;"
        " atv.dispatchEvent(new Event('change', {bubbles: true})); return true; })()"
        % (_js(str(group).split(" - ", 1)[0].strip()), _js(str(version_id)))
    )
    session.pump(0.1)


def _block(session):
    return session.evaluate(
        "(() => { const b = document.getElementById('orientacao-comprovantes');"
        " return {hidden: b.hidden, versao: b.dataset.versaoId || '',"
        " documentos: Array.from(b.querySelectorAll('[data-guidance-document-list] li')).map(li => li.textContent),"
        " modelos: Array.from(b.querySelectorAll('.doc-guidance-template-title')).map(s => s.textContent),"
        " documentsHidden: b.querySelector('[data-guidance-documents]').hidden,"
        " templatesHidden: b.querySelector('[data-guidance-templates]').hidden}; })()"
    )


def _fill_event(session, name):
    _type(session, "input[name='nome_evento']", name)
    _type(session, "input[name='horas_solicitadas']", "2")
    _type(session, "input[name='data_evento']", "2026-09-06")


@browser_only
def test_student_sees_the_selected_activity_guidance_and_downloads_its_template(workspace):
    catalogue = _seed_student_catalogue()
    login_student(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(session, "/aluno/nova-requisicao")
        assert _block(session)["hidden"] is True  # nothing selected yet
        _choose(session, catalogue["group"], catalogue["with_docs"]["id"])
        block = _block(session)
        assert block == {
            "hidden": False, "versao": str(catalogue["with_docs"]["id"]),
            "documentos": ["Relatório da atividade (Anexo 3)", "Cópia do ingresso"],
            "modelos": [ANEXO_3_TITULO], "documentsHidden": False, "templatesHidden": False,
        }
        # The lead is justified like the field notes above it; a template row is
        # its title and "Baixar modelo", nothing else.
        assert session.evaluate(
            "[getComputedStyle(document.querySelector('.doc-guidance-lead')).textAlign,"
            " getComputedStyle(document.querySelector('#data-evento-orientacao > span')).textAlign]"
        ) == ["justify", "justify"]
        assert session.evaluate(
            "document.querySelector('.doc-guidance-template-text').innerText.trim()"
        ) == ANEXO_3_TITULO
        session.screenshot("aluno-nova-requisicao-orientacao-desktop")
        # Phone width. The student shell keeps its 240 px sidebar at every width
        # (the content track scrolls sideways -- pre-existing, every field alike),
        # so what is asserted is the block's own phone layout inside that track:
        # nothing overflows it, the title wraps and the button takes the row.
        session.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        session.pump(0.4)
        layout = session.evaluate(
            "(() => { const b = document.getElementById('orientacao-comprovantes');"
            " const row = b.querySelector('.doc-guidance-template'); const d = row.querySelector('.doc-guidance-download');"
            " const t = row.querySelector('.doc-guidance-template-title');"
            " const r = row.getBoundingClientRect(), dr = d.getBoundingClientRect();"
            " return {overflow: b.scrollWidth - b.clientWidth, rowOverflow: row.scrollWidth - row.clientWidth,"
            " buttonShare: dr.width / (r.width - 22), buttonBelow: dr.top > t.getBoundingClientRect().bottom,"
            " titleWraps: getComputedStyle(t).whiteSpace}; })()"
        )
        assert layout["overflow"] <= 0 and layout["rowOverflow"] <= 0, layout
        assert layout["buttonBelow"] and layout["buttonShare"] > 0.95, layout
        assert layout["titleWraps"] == "normal", layout
        if EVIDENCE:
            # Evidence only, named as such: the same page with the shell's
            # sidebar hidden, so the block's own phone layout is visible.
            session.screenshot("aluno-nova-requisicao-390-pagina-real", width=390, height=844, full=False)
            session.call("Emulation.setDeviceMetricsOverride",
                         {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
            session.pump(0.4)
            session.evaluate(
                "(() => { document.querySelector('.app-sidebar').style.display = 'none';"
                " const layout = document.querySelector('.app-layout'); layout.style.gridTemplateColumns = '1fr';"
                " layout.style.gridTemplateAreas = '\"header\" \"main\"';"
                " const block = document.getElementById('orientacao-comprovantes');"
                " let scroller = block.parentElement;"
                " while (scroller && scroller.scrollHeight <= scroller.clientHeight) scroller = scroller.parentElement;"
                " (scroller || document.scrollingElement).scrollTop += block.getBoundingClientRect().top - 64;"
                " return true; })()"
            )
            session.pump(0.3)
            session.capture_viewport("aluno-nova-requisicao-390-bloco-sem-menu-lateral")
            _open(session, "/aluno/nova-requisicao")
            _choose(session, catalogue["group"], catalogue["with_docs"]["id"])
        session.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        session.pump(0.3)

        # Another activity of the same group: no guidance, no empty block.
        _choose(session, catalogue["group"], catalogue["plain"]["id"])
        assert _block(session)["hidden"] is True and _block(session)["documentos"] == []
        # Templates only: the documents part stays hidden.
        _choose(session, catalogue["group"], catalogue["templates_only"]["id"])
        block = _block(session)
        assert (block["hidden"], block["documentsHidden"], block["modelos"]) == (False, True, [ANEXO_5_TITULO])
        session.click_in_view(".doc-guidance-download")
        assert session.downloaded("Anexo 5.docx") == ANEXO_5

        # Informative only: the request goes through without any comprovante.
        _choose(session, catalogue["group"], catalogue["with_docs"]["id"])
        _fill_event(session, "Palestra sem comprovantes")
        _submit_and_wait(session, "form[data-direct-upload] button[type='submit']")
        assert "Requisição enviada com sucesso." in session.evaluate("document.body.innerText")
        with main.app.app_context():
            conn = main.get_db_connection()
            request = conn.execute(
                "SELECT id, status, atividade_versao_id FROM requisicoes WHERE nome_evento = 'Palestra sem comprovantes'"
            ).fetchone()
            attachments = conn.execute("SELECT count(*) FROM requisicao_arquivos WHERE requisicao_id = ?",
                                       (request["id"],)).fetchone()[0]
        assert (request["status"], request["atividade_versao_id"], attachments) == (
            "Pendente", catalogue["with_docs"]["id"], 0)

        # A refused submission comes back with the same activity and its guidance.
        _open(session, "/aluno/nova-requisicao")
        _choose(session, catalogue["group"], catalogue["with_docs"]["id"])
        _fill_event(session, "Envio recusado")
        session.evaluate(
            "(() => { const form = document.querySelector('form[data-direct-upload]');"
            " form.querySelector('[name=comprovantes_submission_id]').value = '0'.repeat(32);"
            " const fake = document.createElement('input'); fake.type = 'hidden'; fake.name = 'comprovantes_intent_ids';"
            " fake.value = 'f'.repeat(32); form.appendChild(fake); return true; })()"
        )
        _submit_and_wait(session, "form[data-direct-upload] button[type='submit']")
        assert session.evaluate("document.getElementById('atividade_versao_id_select').value") == str(
            catalogue["with_docs"]["id"])
        assert _block(session)["versao"] == str(catalogue["with_docs"]["id"])

        # Editing the stored request shows its recorded version; a change of activity follows.
        _open(session, f"/aluno/requisicoes/{request['id']}?edit=1")
        assert _block(session)["versao"] == str(catalogue["with_docs"]["id"])
        _choose(session, catalogue["group"], catalogue["templates_only"]["id"])
        assert _block(session)["modelos"] == [ANEXO_5_TITULO]
        # Rectification of the returned request: the recorded version's guidance again.
        stamp = (datetime.datetime.now() - datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE requisicoes SET status='Devolvida', data_processamento=?, observacao=? WHERE id=?",
                         (stamp, "Anexe a declaração assinada.", request["id"]))
            conn.commit()
        _open(session, f"/aluno/requisicoes/{request['id']}?edit=1")
        assert "Retificar Requisição" in session.evaluate("document.body.innerText")
        assert _block(session)["documentos"] == ["Relatório da atividade (Anexo 3)", "Cópia do ingresso"]
        session.screenshot("aluno-retificacao-orientacao")
        assert session.evaluate("window.__errors") == []
    finally:
        session.close()


#: The longest fill-in annex title of the ACC rev6 regulation, as an
#: administrator would give it. The file itself is a synthetic test document.
LONG_ANNEX_TITLE = ANEXO_5_TITULO

_TEMPLATE_ROW_GEOMETRY = (
    "(() => { const row = document.querySelector('#orientacao-comprovantes .doc-guidance-template');"
    " const t = row.querySelector('.doc-guidance-template-title'); const d = row.querySelector('.doc-guidance-download');"
    " const tr = t.getBoundingClientRect(), dr = d.getBoundingClientRect();"
    " return {title: t.textContent, cut: t.scrollWidth - t.clientWidth, rowOverflow: row.scrollWidth - row.clientWidth,"
    " buttonBelow: dr.top >= tr.bottom - 1, buttonBeside: dr.left >= tr.right - 1}; })()"
)


@browser_only
def test_a_template_title_is_never_cut_at_any_width(workspace):
    """The template rows follow the width the list gets, not the window's: from
    768 px up the sidebar is back and leaves the block about as narrow as on a
    phone, where a one-line title used to shrink to its first letter. A title
    wraps instead of being cut, and the button moves below it when the list is
    narrow."""
    catalogue = _seed_student_catalogue()
    with main.app.app_context():
        conn = main.get_db_connection()
        insert_template(conn, catalogue["plain"]["id"], LONG_ANNEX_TITLE,
                        make_docx("Arquivo sintético de teste; não é o formulário oficial do Regulamento."), slot=1)
        conn.commit()
    login_student(workspace["client"])
    session = Session(workspace["client"], BINARY, workspace["downloads"], workspace["base_url"])
    try:
        _open(session, "/aluno/nova-requisicao")
        _choose(session, catalogue["group"], catalogue["plain"]["id"])
        assert _block(session)["modelos"] == [LONG_ANNEX_TITLE]
        for width, height, stacked in ((1440, 900, False), (768, 1024, True), (390, 844, True)):
            session.call("Emulation.setDeviceMetricsOverride",
                         {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 768})
            session.pump(0.4)
            row = session.evaluate(_TEMPLATE_ROW_GEOMETRY)
            assert row["title"] == LONG_ANNEX_TITLE
            assert row["cut"] <= 0 and row["rowOverflow"] <= 0, (width, row)
            assert row["buttonBelow"] is stacked, (width, row)
            assert row["buttonBelow"] or row["buttonBeside"], (width, row)
        assert session.evaluate("window.__errors") == []
    finally:
        session.close()
