"""Focused contracts for the Activities floating row-action toolbar."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin_atividades.html"
FLOAT_CSS = ROOT / "static" / "css" / "components" / "actions-float.css"
TOOLBAR_JS = ROOT / "static" / "js" / "toolbar-filters.js"
TEMPLATES = ROOT / "templates"

CANONICAL_FLOATING_EDIT_BARS = (
    "admin_acesso.html",
    "admin_alertas.html",
    "admin_alunos.html",
    "admin_arquivos.html",
    "admin_atividades.html",
    "admin_cursos.html",
    "admin_detalhes_turma.html",
    "admin_matrizes.html",
    "admin_requisicoes.html",
    "admin_turmas.html",
    "aluno_minhas_requisicoes.html",
)


def _toolbar_script() -> str:
    source = TEMPLATE.read_text(encoding="utf-8")
    return source.split("// Barra flutuante de ações na lista de Atividades", 1)[1]


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
    assert '.atividades-actions-float .act-btn[data-action="edit"] svg' in css
    assert "transform:scale(.875)" in css


def test_activity_delete_action_keeps_permission_url_and_confirmation_contract():
    source = TEMPLATE.read_text(encoding="utf-8")
    script = _toolbar_script()
    markup = script.split("bar.innerHTML = `", 1)[1].split("`;", 1)[0]

    full_guard = "{% if auth_can('atividades', 'full') %}"
    guarded_markup = markup.split(full_guard, 1)[1].split("{% endif %}", 1)[0]
    assert 'data-action="delete"' in guarded_markup
    assert 'data-lucide="trash-2"' in guarded_markup
    assert 'data-delete-url="{{ url_for(\'admin_deletar_atividade\', atividade_id=a.id) }}"' in source
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
    assert '.act-btn[data-action="delete"] i{ color:#dc2626; }' in css


def test_canonical_floating_edit_actions_use_the_design_system_edit_icon():
    semantic_edit_button = re.compile(
        r'<button\b[^>]*class="[^"]*\bact-btn\b[^"]*"[^>]*'
        r'data-action="edit"[^>]*>\s*<i\b[^>]*data-lucide="([^"]+)"',
    )

    found = {}
    for template_name in CANONICAL_FLOATING_EDIT_BARS:
        source = (TEMPLATES / template_name).read_text(encoding="utf-8").replace('\\"', '"')
        icons = semantic_edit_button.findall(source)
        assert icons, f"No semantic floating Edit action found in {template_name}"
        found[template_name] = icons

    assert found == {name: ["edit"] for name in CANONICAL_FLOATING_EDIT_BARS}
