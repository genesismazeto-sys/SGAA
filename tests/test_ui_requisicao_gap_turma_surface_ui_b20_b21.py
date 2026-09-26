"""UI-B20 / UI-B21.

* UI-B20 Requisições: an empty ``#m_comprovantes_container`` no longer costs a
  second ``.form-cards-narrow`` row-gap between Comprovantes and Observação.
* UI-B21 Adicionar / Editar turma: the "Alunos da turma" list is one shared
  component (``static/css/components/turma-alunos.css``) whose tokens resolve
  to global DS tokens -- header and the area around the rows on
  ``var(--surface)``, each student line on ``var(--bg)``.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def _declarations(source: str, selector: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    assert match, selector
    return " ".join(match.group(1).split())


# ------------------------------------------------------------------ UI-B20


def test_empty_comprovantes_container_leaves_the_form_grid():
    source = _read("templates/admin_requisicoes.html")
    assert _declarations(source, "#m_comprovantes_container:empty") == "display:none;"
    # Still a grid with the standard gap once it holds existing comprovantes.
    assert _declarations(source, "#m_comprovantes_container") == "display:grid; row-gap: 12px;"
    assert re.search(r"\n\s*\.form-cards-narrow\{[^}]*display: grid; row-gap: 12px; \}", source)


def test_container_is_empty_markup_between_comprovantes_and_observacao():
    source = _read("templates/admin_requisicoes.html")
    # Literally empty (no whitespace), so :empty matches before any JS runs.
    assert re.search(
        r'id="m_upload_row">.*?</div>\s*</div>\s*'
        r'<div id="m_comprovantes_container"></div>\s*'
        r'<div class="form-row">\s*<label class="row-label">Observação \(opcional\)</label>',
        source,
        re.S,
    )
    # Every JS reset clears it with innerHTML = '' -- no stray text node.
    assert "anexosContainer.innerHTML = '';" in source
    assert "container.innerHTML = '';" in source


# ------------------------------------------------------------------ UI-B21

COMPONENT = "static/css/components/turma-alunos.css"
CONSUMERS = ("templates/admin_adicionar_turma.html", "templates/admin_editar_turma.html")
LINK = "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='css/components/turma-alunos.css') }}\">"


def test_both_turma_pages_link_the_one_shared_component():
    for page in CONSUMERS:
        source = _read(page)
        head = source.split("{% block extra_head %}", 1)[1].split("{% endblock %}", 1)[0]
        assert head.count(LINK) == 1, page
        # Linked before the page's own <style>, so page overrides still win.
        assert head.index(LINK) < head.index("<style>"), page


def test_no_turma_student_list_rule_is_left_in_a_template():
    for page in CONSUMERS:
        css = "".join(re.findall(r"<style[^>]*>(.*?)</style>", _read(page), re.S))
        for selector in (".alunos-wide", ".turma-alunos-", ".turma-aluno-", "#btn-remover-aluno"):
            assert selector not in css, (page, selector)


def test_turma_component_tokens_resolve_to_global_tokens():
    css = _read(COMPONENT)
    root = _declarations(css, ".alunos-wide")
    assert "--turma-alunos-header-bg: var(--surface);" in root
    assert "--turma-alunos-content-bg: var(--surface);" in root
    assert "--turma-aluno-row-shell-bg: var(--bg);" in root
    tokens = _read("static/css/foundation/tokens.css")
    assert re.search(r"--surface:#ffffff;", tokens)
    assert re.search(r"--bg:#f3f4f6;", tokens)
    # The component decides no colour of its own: the only literal left is the
    # fallback of the (undefined) --danger token, untouched by this change.
    code = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    literals = re.findall(r"#[0-9a-fA-F]{3,8}(?![0-9a-zA-Z])|rgba?\(|hsla?\(", code)
    assert literals == ["#b91c1c", "#b91c1c"], literals
    assert code.count("var(--danger, #b91c1c)") == 2


def test_turma_card_surfaces_come_from_the_component_tokens():
    css = _read(COMPONENT)
    assert "background: var(--turma-alunos-header-bg);" in _declarations(css, ".turma-alunos-header")
    assert "background: var(--turma-alunos-content-bg);" in _declarations(css, ".turma-alunos-content")
    assert "background: var(--turma-aluno-row-shell-bg);" in _declarations(
        css, ".alunos-wide .turma-aluno-row:not(.header) .turma-aluno-row-shell"
    )
    # The line's chip and inner band read the row colour, not the white content.
    assert re.search(
        r"\.alunos-wide \.turma-aluno-row:not\(\.header\) \.turma-aluno-chip,\s*"
        r"\.alunos-wide \.turma-aluno-row:not\(\.header\) \.turma-aluno-row-inner"
        r"\{ background: var\(--turma-aluno-row-shell-bg\); \}",
        css,
    )
    # Input cells stay white.
    assert (
        ".alunos-wide .turma-aluno-row:not(.header) .turma-aluno-card"
        "{ background: var(--surface) !important; }"
    ) in css
