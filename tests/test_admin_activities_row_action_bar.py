"""Focused contracts for the Activities floating row-action toolbar."""

from pathlib import Path
import re

from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin_atividades.html"
FLOAT_CSS = ROOT / "static" / "css" / "components" / "actions-float.css"
TOOLBAR_JS = ROOT / "static" / "js" / "toolbar-filters.js"
TEMPLATES = ROOT / "templates"

CANONICAL_FLOATING_BARS = {
    "admin_acesso.html": {"edit": "edit", "delete": "trash-2"},
    "admin_alertas.html": {"view": "eye", "edit": "edit", "delete": "trash-2"},
    "admin_alunos.html": {"view": "eye", "edit": "edit", "delete": "trash-2"},
    "admin_arquivos.html": {"view": "eye", "edit": "edit", "delete": "trash-2"},
    "admin_atividades.html": {"view": "eye", "edit": "edit", "delete": "trash-2"},
    "admin_cursos.html": {"view": "eye", "edit": "edit", "delete": "trash-2"},
    "admin_detalhes_turma.html": {"view": "eye", "edit": "edit", "delete": "trash-2"},
    "admin_matrizes.html": {"view": "eye", "edit": "edit", "delete": "trash-2"},
    "admin_reportes.html": {"view": "eye", "delete": "trash-2"},
    "admin_requisicoes.html": {"view": "eye", "edit": "edit", "delete": "trash-2"},
    "admin_turmas.html": {"edit": "edit", "delete": "trash-2"},
    "aluno_arquivos.html": {"view": "eye"},
    "aluno_minhas_requisicoes.html": {"view": "eye", "edit": "edit", "delete": "trash-2"},
}

ADMIN_DELETE_FLOATING_BARS = {
    "admin_acesso.html": "acesso",
    "admin_alertas.html": "alertas",
    "admin_alunos.html": "alunos",
    "admin_arquivos.html": "arquivos",
    "admin_atividades.html": "atividades",
    "admin_cursos.html": "cursos",
    "admin_detalhes_turma.html": "alunos",
    "admin_matrizes.html": "matrizes",
    "admin_reportes.html": "reportes",
    "admin_requisicoes.html": "requisicoes",
    "admin_turmas.html": "turmas",
}


def _toolbar_script() -> str:
    source = TEMPLATE.read_text(encoding="utf-8")
    return source.split("// Barra flutuante de ações na lista de Atividades", 1)[1]


def _floating_markup(template_name: str) -> str:
    source = (TEMPLATES / template_name).read_text(encoding="utf-8").replace('\\"', '"')
    assert "bar.id = 'pedido-actions-float'" in source, template_name
    matches = re.findall(r"bar\.innerHTML\s*=\s*`(.*?)`;", source, re.S)
    assert matches, f"No floating toolbar markup found in {template_name}"
    return "\n".join(matches)


def test_activity_row_toolbar_has_only_the_five_intended_icon_actions():
    script = _toolbar_script()
    markup = script.split("bar.innerHTML = `", 1)[1].split("`;", 1)[0]

    assert re.findall(r'<button[^>]+data-action="([^"]+)"', markup) == [
        "view",
        "edit",
        "nova-versao",
        "ver-versoes",
        "delete",
    ]
    assert re.findall(r'data-lucide="([^"]+)"', markup) == [
        "eye",
        "edit",
        "plus-circle",
        "layers",
        "trash-2",
    ]
    assert 'data-action="more"' not in script
    assert "ativ-more-menu" not in script
    assert "data-menu-action" not in script
    assert "openMoreMenu" not in script
    assert "closeMoreMenu" not in script


def test_activity_version_actions_keep_the_base_id_gate_and_tooltips():
    script = _toolbar_script()

    assert script.count("disabled = !hasBase") == 2
    assert "action === 'nova-versao' && currentBaseId" in script
    assert "action === 'ver-versoes' && currentBaseId" in script
    assert 'aria-label="Criar nova versão" title="Criar nova versão"' in script
    assert 'aria-label="Ver versões" title="Ver versões"' in script
    assert "Esta atividade não possui atividade-base mapeada" in script


def test_activity_toolbar_keeps_compact_shared_button_geometry_and_visible_focus():
    css = FLOAT_CSS.read_text(encoding="utf-8")

    assert "--pedido-float-btn: 26px" in css
    assert "display: flex; gap: 4px" in css
    assert ".atividades-actions-float .act-btn:focus-visible" in css
    assert "outline:2px solid var(--focus-ring-color)" in css
    assert "padding:0;" in css
    assert "#pedido-actions-float .act-btn > svg" in css
    assert "width:16px; height:16px; flex:0 0 16px" in css
    assert "data-action=\"edit\"" not in css
    assert "transform:scale(.875)" not in css


def test_activity_delete_action_keeps_permission_url_and_confirmation_contract():
    source = TEMPLATE.read_text(encoding="utf-8")
    script = _toolbar_script()
    markup = script.split("bar.innerHTML = `", 1)[1].split("`;", 1)[0]

    full_guard = "{% if auth_can('atividades', 'full') %}"
    guarded_markup = markup.split(full_guard, 1)[1].split("{% endif %}", 1)[0]
    assert 'data-action="delete"' in guarded_markup
    assert 'data-lucide="trash-2"' in guarded_markup
    assert 'data-delete-url="{{ url_for(\'admin_deletar_atividade\', atividade_id=a.id) if auth_can(\'atividades\', \'full\') else \'\' }}"' in source
    assert "window.activityRowSelectionApi = rowSelectionApi" in source
    assert "deleteMessageSingle: 'Tem certeza que deseja excluir a atividade selecionada?'" in source

    delete_branch = script.split("} else if (action === 'delete' && currentCard?.getAttribute('data-delete-url')){", 1)[1]
    assert "window.activityRowSelectionApi?.clearSelection();" in delete_branch
    assert "currentCard.click();" in delete_branch
    assert "deleteAction.click();" in delete_branch

    toolbar_js = TOOLBAR_JS.read_text(encoding="utf-8")
    confirmation = "if (!window.confirm(message)) return;"
    deletion = "await postDeleteUrls(deleteUrls);"
    menu_delete_branch = toolbar_js.split("deleteAction.addEventListener('click', async () => {", 1)[1]
    assert confirmation in menu_delete_branch
    assert deletion in menu_delete_branch
    assert menu_delete_branch.index(confirmation) < menu_delete_branch.index(deletion)

    css = FLOAT_CSS.read_text(encoding="utf-8")
    assert '.act-btn[data-action="delete"] > svg{ color:#dc2626; }' in css


def test_census_covers_every_canonical_floating_toolbar():
    actual = sorted(
        path.name
        for path in TEMPLATES.glob("*.html")
        if "bar.id = 'pedido-actions-float'" in path.read_text(encoding="utf-8")
    )
    assert actual == sorted(CANONICAL_FLOATING_BARS)


def test_canonical_floating_semantic_actions_use_the_design_system_icons():
    semantic_edit_button = re.compile(
        r'<button\b(?=[^>]*class="[^"]*\bact-btn\b[^"]*")'
        r'(?=[^>]*data-action="(view|edit|delete)")[^>]*>'
        r'\s*<i\b[^>]*data-lucide="([^"]+)"',
    )

    found = {}
    for template_name, expected in CANONICAL_FLOATING_BARS.items():
        icons = dict(semantic_edit_button.findall(_floating_markup(template_name)))
        found[template_name] = icons
        assert icons == expected, f"Semantic floating action icons drifted in {template_name}"

    assert all(
        icon not in {"pencil", "pencil-line"}
        for actions in found.values()
        for icon in actions.values()
    )


def test_every_deletion_capable_floating_toolbar_keeps_its_full_contract():
    for template_name, permission in ADMIN_DELETE_FLOATING_BARS.items():
        source = (TEMPLATES / template_name).read_text(encoding="utf-8").replace('\\"', '"')
        markup = _floating_markup(template_name)
        assert f"auth_can('{permission}', 'full')" in source or f"can_{permission}_full" in source
        assert 'data-action="delete"' in markup
        assert 'data-lucide="trash-2"' in markup
        assert "data-delete-url" in source

    student_source = (TEMPLATES / "aluno_minhas_requisicoes.html").read_text(encoding="utf-8")
    student_markup = _floating_markup("aluno_minhas_requisicoes.html")
    assert 'data-action="delete"' in student_markup
    assert "data-can-delete" in student_source
    assert "data-delete-url" in student_source
    assert "?delete=1" in student_source


def test_floating_delete_actions_reuse_confirmation_and_csrf_contracts():
    contracts = {
        "admin_arquivos.html": ("if (!confirm('Tem certeza que deseja excluir este arquivo?')) return;", "window.setFormActionWithReturnTo(form"),
        "admin_alertas.html": ("if (!confirm('Tem certeza que deseja excluir este alerta?')) return;", "form.submit();"),
        "admin_reportes.html": ("if (!confirm('Tem certeza que deseja excluir este reporte? Esta ação não pode ser desfeita.')) return;", "fetch(deleteUrl"),
        "admin_detalhes_turma.html": ("if (!confirm(`Excluir ${currentAlunoNome}?`)) return;", "window.ensureFormCsrfToken?.(formEl);"),
        "admin_matrizes.html": ("if (!confirm('Tem certeza que deseja excluir esta matriz?')) return;", "appendCsrfToken(form);"),
    }
    for template_name, (confirmation, mutation) in contracts.items():
        source = (TEMPLATES / template_name).read_text(encoding="utf-8")
        assert confirmation in source
        assert mutation in source

    access_source = (TEMPLATES / "admin_acesso.html").read_text(encoding="utf-8")
    assert "if (!currentData.deleteUrl || currentData.isSelf) return;" in access_source
    assert "window.ensureFormCsrfToken?.(formEl);" in access_source

    for template_name in ("admin_atividades.html", "admin_alunos.html", "admin_cursos.html", "admin_turmas.html", "admin_requisicoes.html"):
        source = (TEMPLATES / template_name).read_text(encoding="utf-8").replace('\\"', '"')
        assert "currentCard.click();" in source
        assert "SelectionActionsApi?.syncMenu();" in source or "ActionsSync?.();" in source
        assert "deleteAction.click();" in source

    source = (TEMPLATES / "aluno_minhas_requisicoes.html").read_text(encoding="utf-8")
    assert "window.alunoReqRowSelectionApi?.clearSelection();" in source
    assert "deleteAction.click();" in source


def test_class_student_toolbar_uses_student_permissions_not_turma_route_permissions():
    source = (TEMPLATES / "admin_detalhes_turma.html").read_text(encoding="utf-8")
    floating_markup = source.split("bar.innerHTML = `", 1)[1].split("`;", 1)[0]
    template = Environment().from_string(floating_markup)

    def render_with_scopes(scopes):
        calls = []

        def auth_can(resource, scope="view"):
            calls.append((resource, scope))
            return scopes.get((resource, scope), False)

        return template.render(auth_can=auth_can), calls

    authorized_markup, authorized_calls = render_with_scopes(
        {
            ("turmas", "view"): True,
            ("turmas", "edit"): False,
            ("alunos", "view"): True,
            ("alunos", "edit"): True,
            ("alunos", "full"): True,
        }
    )
    assert 'data-action="edit"' in authorized_markup
    assert 'data-action="delete"' in authorized_markup
    assert 'data-lucide="trash-2"' in authorized_markup
    assert ("alunos", "edit") in authorized_calls
    assert ("alunos", "full") in authorized_calls
    assert ("turmas", "edit") not in authorized_calls
    assert "hidden" not in authorized_markup
    assert "disabled" not in authorized_markup

    denied_markup, denied_calls = render_with_scopes(
        {
            ("turmas", "view"): True,
            ("turmas", "edit"): False,
            ("alunos", "view"): True,
            ("alunos", "edit"): True,
            ("alunos", "full"): False,
        }
    )
    assert 'data-action="edit"' in denied_markup
    assert 'data-action="delete"' not in denied_markup
    assert ("alunos", "full") in denied_calls

    base_source = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert ".pedido-actions-float .act-btn" not in base_source
    assert ".access-actions-float .act-btn" not in base_source
