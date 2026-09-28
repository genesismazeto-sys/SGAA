"""DS-FLOAT-BAR-ORDER: equivalent floating row actions sit in the same slots.

Rule (user decision, left to right): the read/detail action (Eye) first,
Editar second, Excluir last. Domain actions keep their own relative order and
sit between Editar and Excluir -- the placement Atividades, the versions hub
(Ativar / Inativar / Substituir / Descontinuar) and Acesso already used.

Normalized by this item (markup reordered only; data-action, icons, labels,
permission guards and click handlers untouched): Reportes (Excluir, Ver ->
Ver, Excluir), Matrizes (Editar moved ahead of the AAC/AEA list actions) and
Alertas (Ativar/Desativar toggle moved after Editar, as the versions hub places
its state actions).

Left unchanged on purpose -- AMBIGUOUS, awaiting a user decision: Requisições.
"Processar"/"Reabrir" is that list's primary workflow action and sits
leftmost; no other bar has an equivalent to take a placement from, and the bar
is selection-owned with a batch mode. Its current order is pinned so it only
changes deliberately.

Every bar is still hand-written in its own template (there is no shared
macro), so this one guard walks all of them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from jinja2 import Environment

from tests.test_admin_activities_row_action_bar import _discovered_floating_bars, _floating_markup

ROOT = Path(__file__).resolve().parents[1]
LUCIDE = ROOT / "static" / "vendor" / "lucide.min.js"

VIEW_ACTIONS = {"view", "alunos"}  # Turmas' Eye opens "Alunos da turma" (its read/detail action)
CANONICAL_ICON = {"view": "eye", "alunos": "eye", "edit": "edit", "delete": "trash-2"}

AMBIGUOUS = {
    "admin_requisicoes.html": ["process", "edit", "view", "email", "delete"],
}

ROLES = {
    "viewer": {"view"},
    "editor": {"view", "edit"},
    "full": {"view", "edit", "full"},
}

# Visible actions per role for the reference and every surface this item moved.
EXPECTED_BY_ROLE = {
    "admin_turmas.html": {
        "viewer": ["alunos"],
        "editor": ["alunos", "edit"],
        "full": ["alunos", "edit", "delete"],
    },
    "admin_reportes.html": {
        "viewer": ["view"],
        "editor": ["view"],
        "full": ["view", "delete"],
    },
    "admin_matrizes.html": {
        "viewer": ["view"],
        "editor": ["view", "edit", "aac", "aea"],
        "full": ["view", "edit", "aac", "aea", "delete"],
    },
    "admin_alertas.html": {
        "viewer": ["view"],
        "editor": ["view", "edit", "toggle"],
        "full": ["view", "edit", "toggle", "delete"],
    },
}


def _buttons(markup: str) -> list[tuple[str, str]]:
    return re.findall(r'<button[^>]*\bdata-action="([^"]+)"[^>]*>\s*<i data-lucide="([^"]+)"', markup)


def _order_violations(actions: list[str]) -> list[str]:
    problems = []
    views = [i for i, a in enumerate(actions) if a in VIEW_ACTIONS]
    if views and views[0] != 0:
        problems.append(f"Eye at slot {views[0] + 1}, not first")
    if "edit" in actions:
        want = 1 if views else 0
        if actions.index("edit") != want:
            problems.append(f"Editar at slot {actions.index('edit') + 1}, not {want + 1}")
    if "delete" in actions and actions.index("delete") != len(actions) - 1:
        problems.append("Excluir is not last")
    return problems


def _render(template_name: str, role: str) -> str:
    scopes = ROLES[role]
    markup = Environment().from_string(_floating_markup(template_name)).render(
        auth_can=lambda resource, scope="view": scope in scopes,
        can_edit_atividades="edit" in scopes,
        user_message=lambda text, *args, **kwargs: text,
    )

    def flag(match: re.Match) -> str:
        name, button = match.group(1), match.group(2)
        needed = "full" if name.endswith("Full") else "edit"
        return button if needed in scopes else ""

    return re.sub(r"\$\{(can\w+)\s*\?\s*'(.*?)'\s*:\s*''\}", flag, markup, flags=re.S)


def test_every_floating_bar_is_accounted_for():
    assert set(EXPECTED_BY_ROLE) <= _discovered_floating_bars()
    assert set(AMBIGUOUS) <= _discovered_floating_bars()
    assert len(_discovered_floating_bars()) == 14


@pytest.mark.parametrize("template_name", sorted(_discovered_floating_bars()))
def test_standard_actions_take_the_same_slots_on_every_bar(template_name):
    actions = [action for action, _icon in _buttons(_floating_markup(template_name))]
    assert actions, template_name
    if template_name in AMBIGUOUS:
        assert actions == AMBIGUOUS[template_name], (template_name, actions)
        return
    assert _order_violations(actions) == [], (template_name, actions)


@pytest.mark.parametrize("template_name", sorted(_discovered_floating_bars()))
def test_standard_actions_keep_their_canonical_registered_icons(template_name):
    bundle = LUCIDE.read_text(encoding="utf-8")
    for action, icon in _buttons(_floating_markup(template_name)):
        if action in CANONICAL_ICON:
            assert icon == CANONICAL_ICON[action], (template_name, action, icon)
        pascal = "".join(part.capitalize() for part in icon.split("-"))
        assert re.search(r"\b%s:" % re.escape(pascal), bundle), (template_name, icon)


@pytest.mark.parametrize("template_name", sorted(EXPECTED_BY_ROLE))
@pytest.mark.parametrize("role", sorted(ROLES))
def test_permissions_still_decide_which_actions_each_role_sees(template_name, role):
    visible = [action for action, _icon in _buttons(_render(template_name, role))]
    assert visible == EXPECTED_BY_ROLE[template_name][role], (template_name, role, visible)
    assert _order_violations(visible) == [], (template_name, role, visible)


@pytest.mark.parametrize("template_name", sorted(set(EXPECTED_BY_ROLE) - {"admin_turmas.html"}))
def test_every_moved_action_still_has_its_click_handler(template_name):
    source = (ROOT / "templates" / template_name).read_text(encoding="utf-8")
    script = source.split("bar.innerHTML = `", 1)[1]
    for action, _icon in _buttons(_floating_markup(template_name)):
        assert re.search(r"(?:action|getAttribute\('data-action'\))\s*===\s*'%s'" % re.escape(action), script), (
            template_name,
            action,
        )
