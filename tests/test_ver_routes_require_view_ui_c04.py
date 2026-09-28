"""UI-C04: Ver has view authority; Editar and every write keep edit/full authority."""
from __future__ import annotations

import uuid
from pathlib import Path

import main
from app.auth import get_admin_permission_requirement
from app.user_accounts import create_usuario_with_access_level
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env


ROOT = Path(__file__).resolve().parents[1]


def _create_actor(access_level: str, *, deny_resources=()) -> int:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        user_id = int(
            create_usuario_with_access_level(
                conn,
                f"UI-C04 {access_level} {token}",
                f"ui-c04-{access_level}-{token}@example.invalid",
                main.hash_password("ui-c04"),
                "admin",
                access_level,
                credential_state="personal",
            ).lastrowid
        )
        for resource in deny_resources:
            conn.execute(
                "INSERT INTO usuarios_permissoes_acesso(usuario_id,recurso,escopo)"
                " VALUES (?,?,'none')",
                (user_id, resource),
            )
        conn.commit()
    return user_id


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session.clear()
        session.update(
            user_id=user_id,
            user_type="admin",
            user_name="UI-C04 actor",
        )
        stamp_auth_version(session, user_id)


def _seed_targets() -> dict[str, int | str]:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        course_code = "UIC-TEST"
        course_id = int(
            conn.execute(
                "INSERT INTO cursos(nome,codigo,duracao_periodos,status)"
                " VALUES (?,?,4,'ativo')",
                (f"Curso UI-C04 {token}", course_code),
            ).lastrowid
        )

        student_email = f"ui-c04-student-{token}@example.invalid"
        student_user_id = int(
            create_usuario_with_access_level(
                conn,
                f"Aluno UI-C04 {token}",
                student_email,
                main.hash_password("student"),
                "aluno",
                "usuario",
                credential_state="personal",
            ).lastrowid
        )
        conn.execute(
            "INSERT INTO alunos(usuario_id,nome,matricula,email,turma_id,matriz_id,status)"
            " VALUES (?,?,?,?,NULL,NULL,'Ativo')",
            (
                student_user_id,
                f"Aluno UI-C04 {token}",
                f"UIC04-{token[:6].upper()}",
                student_email,
            ),
        )

        base_id = int(
            conn.execute(
                "INSERT INTO atividade_base(nome_conceito,descricao,status)"
                " VALUES (?,?,'ativo')",
                (f"Atividade UI-C04 {token}", "Descrição UI-C04"),
            ).lastrowid
        )
        version_id = int(
            conn.execute(
                "INSERT INTO atividade_versao(atividade_base_id,eixo,grupo,status,"
                "ch_por_evento,numero_versao) VALUES (?,?,?,'rascunho',?,1)",
                (base_id, "AAC", "1 - Grupo UI-C04", 2),
            ).lastrowid
        )
        conn.commit()
    return {
        "course_id": course_id,
        "course_code": course_code,
        "student_user_id": student_user_id,
        "student_email": student_email,
        "base_id": base_id,
        "version_id": version_id,
    }


def _snapshot(targets) -> dict[str, tuple]:
    with main.app.app_context():
        conn = main.get_db_connection()
        course = conn.execute(
            "SELECT nome,codigo,duracao_periodos,status FROM cursos WHERE id=?",
            (targets["course_id"],),
        ).fetchone()
        student = conn.execute(
            "SELECT u.nome,u.email,a.matricula,a.turma_id,a.matriz_id,a.status"
            " FROM usuarios u JOIN alunos a ON a.usuario_id=u.id WHERE u.id=?",
            (targets["student_user_id"],),
        ).fetchone()
        version = conn.execute(
            "SELECT b.nome_conceito,b.descricao,v.eixo,v.grupo,v.status,v.ch_por_evento,"
            "v.limite_semestre,v.limite_total,v.versao_anterior_id"
            " FROM atividade_base b JOIN atividade_versao v ON v.atividade_base_id=b.id"
            " WHERE v.id=?",
            (targets["version_id"],),
        ).fetchone()
        return {
            "course": tuple(course) if course else (),
            "student": tuple(student) if student else (),
            "version": tuple(version) if version else (),
        }


def _urls(targets) -> dict[str, dict[str, str]]:
    course_id = targets["course_id"]
    student_user_id = targets["student_user_id"]
    base_id = targets["base_id"]
    version_id = targets["version_id"]
    return {
        "course": {
            "view": f"/admin/cursos/{course_id}/visualizar",
            "edit": f"/admin/cursos/{course_id}/editar",
            "mutation": f"/admin/deletar_curso/{course_id}",
        },
        "student": {
            "view": f"/admin/visualizar_aluno/{student_user_id}",
            "edit": f"/admin/editar_aluno/{student_user_id}",
            "mutation": f"/admin/deletar_aluno/{student_user_id}",
        },
        "version": {
            "view": f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/visualizar",
            "edit": f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar",
            "mutation": f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/ativar",
        },
    }


def _course_payload(targets, *, name="Curso UI-C04 editado") -> dict[str, str]:
    return {
        "nome": name,
        "codigo": str(targets["course_code"]),
        "duracao_periodos": "6",
        "status": "ativo",
    }


def _student_payload(targets, *, name="Aluno UI-C04 editado") -> dict[str, str]:
    return {
        "nome": name,
        "email": str(targets["student_email"]),
        "matricula": f"UIC04-{uuid.uuid4().hex[:6].upper()}",
        "turma_id": "",
        "matriz_id": "",
        "status": "Ativo",
        "senha": "",
    }


def _version_payload(*, name="Atividade UI-C04 editada") -> dict[str, str]:
    return {
        "tipo_atividade": "Acadêmica Complementar",
        "grupo": "1 - Grupo UI-C04 editado",
        "nome": name,
        "descricao": "Descrição editada",
        "tipo_limitacao": "semestral",
        "limite_valor": "40",
        "ch_por_evento": "4",
        "observacoes": "Observação editada",
        "versao_anterior_id": "",
    }


def _assert_denied(response) -> None:
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/dashboard")


def test_permission_registry_splits_view_and_edit_routes():
    assert get_admin_permission_requirement("admin_visualizar_curso", "GET") == ("cursos", "view")
    assert get_admin_permission_requirement("admin_editar_curso", "GET") == ("cursos", "edit")
    assert get_admin_permission_requirement("admin_editar_curso", "POST") == ("cursos", "edit")
    assert get_admin_permission_requirement("admin_visualizar_aluno", "GET") == ("alunos", "view")
    assert get_admin_permission_requirement("admin_editar_aluno", "GET") == ("alunos", "edit")
    assert get_admin_permission_requirement("admin_editar_aluno", "POST") == ("alunos", "edit")
    assert get_admin_permission_requirement("admin_catalogo_visualizar_versao", "GET") == ("atividades", "view")
    assert get_admin_permission_requirement("admin_catalogo_editar_versao", "GET") == ("atividades", "edit")
    assert get_admin_permission_requirement("admin_catalogo_editar_versao", "POST") == ("atividades", "edit")


def test_view_only_can_open_ver_but_not_edit_or_mutate(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c04-view.db") as env:
        client = env["client"]
        targets = _seed_targets()
        urls = _urls(targets)
        view_only_id = _create_actor("consultivo")
        _login(client, view_only_id)
        before = _snapshot(targets)

        for surface in ("course", "student", "version"):
            page = client.get(urls[surface]["view"])
            assert page.status_code == 200, surface
            html = page.get_data(as_text=True)
            assert 'type="submit"' not in html, surface
            assert "Salvar" not in html, surface
            assert client.post(urls[surface]["view"], data={}).status_code == 405, surface
            _assert_denied(client.get(urls[surface]["edit"]))

        _assert_denied(client.post(urls["course"]["edit"], data=_course_payload(targets)))
        _assert_denied(client.post(urls["course"]["mutation"]))
        _assert_denied(client.post(urls["student"]["edit"], data=_student_payload(targets)))
        _assert_denied(client.post(urls["student"]["mutation"]))
        _assert_denied(client.post(urls["version"]["edit"], data=_version_payload()))
        _assert_denied(client.post(urls["version"]["mutation"]))
        assert _snapshot(targets) == before


def test_editor_keeps_view_readonly_and_edit_mutations_work(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c04-editor.db") as env:
        client = env["client"]
        targets = _seed_targets()
        urls = _urls(targets)
        editor_id = _create_actor("administrativo")
        _login(client, editor_id)

        for surface in ("course", "student", "version"):
            view_page = client.get(urls[surface]["view"])
            assert view_page.status_code == 200, surface
            assert 'type="submit"' not in view_page.get_data(as_text=True), surface
            edit_page = client.get(urls[surface]["edit"])
            assert edit_page.status_code == 200, surface
            assert 'type="submit"' in edit_page.get_data(as_text=True), surface

        assert client.post(urls["course"]["edit"], data=_course_payload(targets)).status_code == 302
        assert client.post(urls["student"]["edit"], data=_student_payload(targets)).status_code == 302
        assert client.post(urls["version"]["edit"], data=_version_payload()).status_code == 302
        after = _snapshot(targets)
        assert after["course"][0] == "Curso UI-C04 editado"
        assert after["student"][0] == "Aluno UI-C04 editado"
        assert after["version"][0] == "Atividade UI-C04 editada"


def test_no_permission_account_cannot_open_ver_or_edit(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-c04-none.db") as env:
        client = env["client"]
        targets = _seed_targets()
        urls = _urls(targets)
        denied_id = _create_actor(
            "consultivo",
            deny_resources=("cursos", "alunos", "atividades"),
        )
        _login(client, denied_id)

        for surface in ("course", "student", "version"):
            _assert_denied(client.get(urls[surface]["view"]))
            _assert_denied(client.get(urls[surface]["edit"]))


def test_all_advertised_ver_actions_target_view_authority_routes():
    assert "admin_visualizar_curso" in (ROOT / "templates/admin_cursos.html").read_text(encoding="utf-8")
    assert "admin_visualizar_aluno" in (ROOT / "templates/admin_alunos.html").read_text(encoding="utf-8")
    assert "admin_visualizar_aluno" in (ROOT / "templates/admin_detalhes_turma.html").read_text(encoding="utf-8")
    version_source = (ROOT / "templates/admin_catalogo_versao_detalhe.html").read_text(encoding="utf-8")
    assert "admin_catalogo_visualizar_versao" in version_source
    assert "dataset.versionViewUrl" in version_source
    assert "dataset.versionEditUrl" in version_source
