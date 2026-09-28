"""UI-C06: Aluno Ver/Editar and Turma detail use the shared detail header.

Before: Ver/Editar Aluno had a plain ``h1.main-title`` and a generic bottom
"Voltar" (Ver) beside the Cancelar/Salvar form footer (Editar); the Turma
detail page built its own ``.turma-topbar`` with a generic "Voltar" and styled
its empty roster with an inline raw ``#6b7280``.

After: ``components/detail_header.html`` owns title + page-level Back on all
three. Back names its destination and keeps the existing targets
(``return_to`` or the Alunos list; the Turmas list). Ver has no footer; Editar
keeps Cancelar + Salvar; the roster, its actions and the turma picker are
unchanged.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

import main
from app.user_accounts import create_usuario_with_access_level
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
RAW_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")


def _actor(level: str) -> int:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = int(
            create_usuario_with_access_level(
                conn, f"UI-C06 {level} {token}", f"ui-c06-{level}-{token}@example.invalid",
                main.hash_password("ui-c06"), "admin", level, credential_state="personal",
            ).lastrowid
        )
        conn.commit()
    return uid


def _login(client, uid: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session.update(user_id=uid, user_type="admin", user_name="UI-C06 actor")
        stamp_auth_version(session, uid)


def _seed() -> dict[str, int]:
    token = uuid.uuid4().hex[:6].upper()
    with main.app.app_context():
        conn = main.get_db_connection()
        course = int(conn.execute(
            "INSERT INTO cursos(nome,codigo,duracao_periodos,status) VALUES (?,?,4,'ativo')",
            (f"Curso UI-C06 {token}", f"C06{token}"),
        ).lastrowid)
        turma = int(conn.execute(
            "INSERT INTO turmas (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)"
            " VALUES (?,?,?,?,?,?,?,?,NULL)",
            (f"Turma UI-C06 {token}", "Noturno", "Ativa", 1, course, 2026, 1, f"T-C06-{token}"),
        ).lastrowid)
        empty_turma = int(conn.execute(
            "INSERT INTO turmas (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)"
            " VALUES (?,?,?,?,?,?,?,?,NULL)",
            (f"Turma vazia UI-C06 {token}", "Noturno", "Ativa", 2, course, 2026, 1, f"T-C06E-{token}"),
        ).lastrowid)
        student = int(create_usuario_with_access_level(
            conn, f"Aluno UI-C06 {token}", f"ui-c06-aluno-{token.lower()}@example.invalid",
            main.hash_password("aluno"), "aluno", "usuario", credential_state="personal",
        ).lastrowid)
        conn.execute(
            "INSERT INTO alunos(usuario_id,nome,matricula,email,turma_id,matriz_id,status)"
            " VALUES (?,?,?,?,?,NULL,'Ativo')",
            (student, f"Aluno UI-C06 {token}", f"C06-{token}", f"ui-c06-aluno-{token.lower()}@example.invalid", turma),
        )
        conn.commit()
    return {"turma": turma, "empty_turma": empty_turma, "student": student}


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c06.db") as environment:
        ids = _seed()
        yield {
            "client": environment["client"],
            "ids": ids,
            "viewer": _actor("consultivo"),
            "editor": _actor("administrativo"),
        }


def _get(env, actor, path) -> str:
    _login(env["client"], env[actor])
    response = env["client"].get(path)
    assert response.status_code == 200, (path, response.status_code)
    return response.get_data(as_text=True)


def _header(html: str) -> str:
    match = re.search(r'<header class="detail-header">(.*?)</header>', html, re.S)
    assert match, "the shared detail header is missing"
    return match.group(1)


def _back(html: str) -> tuple[str, str]:
    match = re.search(
        r'<a class="btn detail-header__back" href="([^"]*)">.*?<span class="btn-label">([^<]*)</span>',
        _header(html), re.S,
    )
    assert match, "the header lost its Back action"
    return match.group(1).replace("&amp;", "&"), match.group(2).strip()


def _content(html: str) -> str:
    return html.split('<header class="detail-header">', 1)[1]


# ==========================================================================
# Aluno — Ver
# ==========================================================================


def test_ver_aluno_uses_the_shared_header_and_has_no_footer(env):
    uid = env["ids"]["student"]
    html = _get(env, "viewer", f"/admin/visualizar_aluno/{uid}")

    assert 'class="main-title detail-header__title">Ver Aluno</h1>' in _header(html)
    assert _back(html) == ("/admin/alunos", "Alunos")
    content = _content(html)
    assert "Voltar" not in content
    assert 'class="form-actions' not in content
    assert 'type="submit"' not in content and "Salvar" not in content
    # Read-only behaviour unchanged (UI-B DS-7 read-only, not disabled).
    assert len(re.findall(r'readonly aria-readonly="true"', content)) >= 3
    assert '<h1 class="main-title">' not in html


def test_ver_aluno_back_is_contextual(env):
    uid, turma = env["ids"]["student"], env["ids"]["turma"]
    from_roster = _get(env, "viewer", f"/admin/visualizar_aluno/{uid}?return_to=/admin/turma/{turma}")
    assert _back(from_roster) == (f"/admin/turma/{turma}", "Turma")

    from_list = _get(env, "viewer", f"/admin/visualizar_aluno/{uid}?return_to=/admin/alunos%3Fq%3Dx")
    assert _back(from_list) == ("/admin/alunos?q=x", "Alunos")


# ==========================================================================
# Aluno — Editar
# ==========================================================================


def test_editar_aluno_uses_the_shared_header_and_keeps_cancel_save(env):
    uid, turma = env["ids"]["student"], env["ids"]["turma"]
    html = _get(env, "editor", f"/admin/editar_aluno/{uid}?return_to=/admin/turma/{turma}")

    assert 'class="main-title detail-header__title">Editar Aluno</h1>' in _header(html)
    assert _back(html) == (f"/admin/turma/{turma}", "Turma")
    content = _content(html)
    footer = re.search(r'<div class="form-actions center">(.*?)</div>', content, re.S)
    assert footer, "Editar lost its form footer"
    assert f'<a class="btn" href="/admin/turma/{turma}">Cancelar</a>' in footer.group(1)
    assert 'class="btn primary" type="submit"' in footer.group(1) and "Salvar" in footer.group(1)
    assert "Voltar" not in content
    assert re.search(r'<input class="control" type="text" name="nome" value="[^"]*" required\s*>', content)
    assert '<form method="POST">' in content


# ==========================================================================
# Turma detail
# ==========================================================================


def test_turma_detail_uses_the_shared_header_with_its_picker(env):
    turma = env["ids"]["turma"]
    html = _get(env, "viewer", f"/admin/turma/{turma}")

    header = _header(html)
    assert 'class="main-title detail-header__title">Turma</h1>' in header
    assert _back(html) == ("/admin/turmas", "Turmas")
    assert 'id="turma-global-select"' in header
    assert f'value="/admin/turma/{turma}" selected' in header
    assert "turma-topbar" not in html
    assert "Voltar" not in _content(html)


def test_turma_roster_and_actions_are_unchanged(env):
    turma, uid = env["ids"]["turma"], env["ids"]["student"]
    html = _get(env, "editor", f"/admin/turma/{turma}")
    assert 'id="turma-detalhes-toolbar"' in html
    assert re.search(r'data-[a-z-]*="%d"' % uid, html), "the roster lost its student row"
    assert 'data-action="view"' in html
    assert "\"/admin/visualizar_aluno/0\"" in html


def test_empty_roster_uses_the_shared_empty_state(env):
    html = _get(env, "viewer", f"/admin/turma/{env['ids']['empty_turma']}")
    assert '<div class="table-empty">Nenhum aluno vinculado a esta turma.</div>' in html


def test_touched_templates_carry_no_raw_header_colour():
    turma = (ROOT / "templates" / "admin_detalhes_turma.html").read_text(encoding="utf-8")
    aluno = (ROOT / "templates" / "admin_editar_aluno.html").read_text(encoding="utf-8")
    assert "#6b7280" not in turma
    assert ".turma-topbar" not in turma
    for text in (turma, aluno):
        assert "detail_header(" in text
    assert '<h1 class="main-title">' not in aluno and '<h1 class="main-title">' not in turma
    assert not RAW_COLOUR.findall(re.sub(r"(?s)<style.*?</style>", "", aluno))
