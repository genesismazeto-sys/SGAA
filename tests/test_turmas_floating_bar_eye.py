"""Turmas list floating action bar: the Alunos/detail action uses the shared Eye
icon, and the bar reads left to right: Eye, Editar, Excluir (Eye first, delete last).

Only the icon changed on that action: same ``data-action="alunos"``, same
route (the Turma detail page), same permissions (no gate, as before), same
aria-label/title; Editar and Excluir keep their gates and icons.
"""

from __future__ import annotations

import re
import uuid

import pytest

import main
from app.user_accounts import create_usuario_with_access_level
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env


def _actor(level: str) -> int:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = int(
            create_usuario_with_access_level(
                conn, f"Turmas bar {level} {token}", f"turmas-bar-{level}-{token}@example.invalid",
                main.hash_password("turmas-bar"), "admin", level, credential_state="personal",
            ).lastrowid
        )
        conn.commit()
    return uid


@pytest.fixture
def client(tmp_path):
    with isolated_versioned_app_env(tmp_path, "turmas-bar.db") as env:
        yield env["client"]


def _page(client, level: str) -> str:
    uid = _actor(level)
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=uid, user_type="admin", user_name="Turmas bar")
        stamp_auth_version(session, uid)
    response = client.get("/admin/turmas")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _bar(html: str) -> list[tuple[str, str]]:
    markup = re.search(r"bar\.innerHTML = `(.*?)`;", html, re.S)
    assert markup, "the Turmas floating bar markup is missing"
    buttons = re.findall(r'<button\b[^>]*data-action=\\?"([^"\\]+)\\?"[^>]*>(.*?)</button>', markup.group(1), re.S)
    return [(action, body) for action, body in buttons]


@pytest.mark.parametrize(
    "level, expected_order",
    [
        ("admin_total", ["alunos", "edit", "delete"]),  # left to right: Eye, Editar, Excluir
        ("consultivo", ["alunos"]),                      # view-only: permissions unchanged
    ],
)
def test_floating_bar_order_and_icons(client, level, expected_order):
    html = _page(client, level)
    bar = _bar(html)

    assert [action for action, _body in bar] == expected_order
    action, body = bar[0]  # Eye is the first button, left to right
    assert action == "alunos"
    assert re.search(r'data-lucide=\\?"eye\\?"', body)
    assert "icon-tabler-school" not in body and "<svg" not in body
    icons = {a: re.search(r'data-lucide=\\?"([^"\\]+)', b).group(1) for a, b in bar}
    if "edit" in icons:
        assert icons["edit"] == "edit"
    if "delete" in icons:
        assert icons["delete"] == "trash-2"


def test_eye_action_keeps_its_label_and_route(client):
    html = _page(client, "admin_total")
    assert re.search(
        r'data-action=\\?"alunos\\?" aria-label=\\?"Alunos da turma\\?" title=\\?"Alunos\\?"', html
    )
    branch = re.search(r"if \(action === 'alunos'\)\{(.*?)\}", html, re.S)
    assert branch, "the alunos action handler is missing"
    assert '"/admin/turma/0".replace(\'/0\', \'/\'+currentTid)' in branch.group(1)
    assert "navigateWithReturnTo" in branch.group(1)
