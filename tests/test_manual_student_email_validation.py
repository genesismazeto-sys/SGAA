"""Manually typed e-mails are validated by the server, not only the browser.

File imports already refused an e-mail that is not an e-mail, but every manual
path wrote whatever the request carried: Turma roster rows (Nova/Editar Turma),
Novo Aluno, Editar Aluno, Acesso and both "Meus dados" screens. Only the
browser's ``type=email`` stood in the way, and a direct POST skips it (it also
accepts ``a@b``, which the SGAA's rule does not). Every one of those paths now
applies the SGAA's one e-mail rule -- ``is_valid_email``, the check file
imports and every outbound mail already use -- and a rejected request writes
nothing: no Turma change, no student, no e-mail update, no roster removal, no
credential or token change.
"""
from __future__ import annotations

import pytest

import main
from app.password_tokens import PURPOSE_FIRST_ACCESS, issue_password_token
from app.services.mail_service import is_valid_email
from app.student_import import StudentImportError, normalize_student_import_values
from app.user_accounts import create_usuario_pending
from tests.canonical_matrix_test_support import login_admin
from tests.canonical_request_test_support import login_student
from tests.test_student_import_row_validation import EMAIL_CORPUS
from tests.versioned_test_support import isolated_versioned_app_env


TURMA_ID = 1  # seeded PPA-T10
MALFORMED = ("terceira@example", "terceira@@example.com", "terceira.example.com", "terceira @example.com")
TABLES = ("alunos", "usuarios", "usuario_credenciais", "senha_tokens", "turmas")


def _seed_existing_student() -> int:
    """A pending student in the Turma, holding a live first-access link."""
    with main.app.app_context():
        conn = main.get_db_connection()
        usuario_id = create_usuario_pending(
            conn, "Aluna Existente", "existente@example.com", "aluno"
        ).lastrowid
        conn.execute(
            "INSERT INTO alunos (usuario_id,nome,email,matricula,turma_id,status)"
            " VALUES (?,?,?,?,?,'Ativo')",
            (usuario_id, "Aluna Existente", "existente@example.com", "EX-0001", TURMA_ID),
        )
        issue_password_token(conn, usuario_id, PURPOSE_FIRST_ACCESS)
        conn.commit()
        return int(usuario_id)


def _database_state():
    with main.app.app_context():
        conn = main.get_db_connection()
        return {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in TABLES
        }


def _flashes(client):
    with client.session_transaction() as session:
        return list(session.get("_flashes", []))


def _curso_id() -> int:
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT curso_id FROM turmas WHERE id=?", (TURMA_ID,)
        ).fetchone()["curso_id"]


def _turma_form(numero: int, rows) -> dict:
    return {
        "curso_id": str(_curso_id()),
        "numero_turma": str(numero),
        "ano_inicio": "2025",
        "semestre_inicio": "2",
        "turno": "Noite",  # would change if anything were committed
        "status": "Ativa",
        "matriz_id": "",
        "aluno_nome[]": [row[0] for row in rows],
        "aluno_email[]": [row[1] for row in rows],
        "aluno_matricula[]": [row[2] for row in rows],
        "aluno_situacao[]": ["ATIVO"] * len(rows),
        "aluno_importado[]": ["0"] * len(rows),
    }


def _rows_with_bad(position: str, bad_email: str):
    """Row 1 updates the existing student's e-mail and row 2 creates one;
    the malformed row sits first or last. Nothing of the valid rows may
    survive."""
    valid = [
        ("Aluna Existente", "existente.nova@example.com", "EX-0001"),
        ("Nova Pessoa", "nova@example.com", "NEW-0001"),
    ]
    bad = ("Terceira Pessoa", bad_email, "T-0003")
    if position == "first":
        return [bad, *valid], 1
    return [*valid, bad], 3


# --- Turma roster rows ------------------------------------------------------


@pytest.mark.parametrize("bad_email", MALFORMED)
@pytest.mark.parametrize("position", ("first", "last"))
def test_editar_turma_rejects_a_malformed_manual_email_and_writes_nothing(tmp_path, position, bad_email):
    with isolated_versioned_app_env(tmp_path, "manual-editar.db") as env:
        _seed_existing_student()
        login_admin(env["client"])
        rows, line = _rows_with_bad(position, bad_email)
        before = _database_state()

        response = env["client"].post(f"/admin/editar_turma/{TURMA_ID}", data=_turma_form(10, rows))

        assert response.status_code == 200
        assert (
            f"Erro ao atualizar turma: Linha {line} (Terceira Pessoa): e-mail inválido."
            in response.get_data(as_text=True)
        )
        # Turma metadata (turno), the e-mail update, the new student, the
        # roster unlink of anyone left out, credentials and the live token.
        assert _database_state() == before


@pytest.mark.parametrize("position", ("first", "last"))
def test_nova_turma_with_a_malformed_manual_email_creates_no_turma(tmp_path, position):
    with isolated_versioned_app_env(tmp_path, "manual-nova.db") as env:
        _seed_existing_student()
        login_admin(env["client"])
        rows, line = _rows_with_bad(position, "terceira@example")
        before = _database_state()

        response = env["client"].post("/admin/adicionar_turma", data=_turma_form(77, rows))

        assert response.status_code == 200
        assert (
            f"Erro ao criar turma: Linha {line} (Terceira Pessoa): e-mail inválido."
            in response.get_data(as_text=True)
        )
        assert _database_state() == before
        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT 1 FROM turmas WHERE numero=77"
            ).fetchone() is None


def test_valid_manual_rows_still_save_unchanged(tmp_path):
    with isolated_versioned_app_env(tmp_path, "manual-valid.db") as env:
        _seed_existing_student()
        login_admin(env["client"])
        rows = [
            ("Aluna Existente", "existente.nova@example.com", "EX-0001"),
            ("Nova Pessoa", "Nova.Pessoa+tag@sub.example.com.br", "001234"),
        ]

        response = env["client"].post(f"/admin/editar_turma/{TURMA_ID}", data=_turma_form(10, rows))

        assert response.status_code == 302
        with main.app.app_context():
            conn = main.get_db_connection()
            found = {
                row["matricula"]: row["email"]
                for row in conn.execute("SELECT matricula,email FROM alunos WHERE turma_id=?", (TURMA_ID,))
            }
            assert conn.execute("SELECT turno FROM turmas WHERE id=?", (TURMA_ID,)).fetchone()[0] == "Noite"
        assert found == {
            "EX-0001": "existente.nova@example.com",
            "001234": "Nova.Pessoa+tag@sub.example.com.br",
        }


def test_manual_rows_and_file_rows_use_the_same_rule():
    """No second regex: the manual verdict is exactly ``is_valid_email``'s,
    and the file-row message is untouched."""
    assert any(is_valid_email(e) for e in EMAIL_CORPUS)
    assert not all(is_valid_email(e) for e in EMAIL_CORPUS)
    for index, email in enumerate(EMAIL_CORPUS):
        values = [("Pessoa", email, f"M-{index}")]
        if is_valid_email(email):
            assert [row.email for row in normalize_student_import_values(values)] == [email]
        else:
            with pytest.raises(StudentImportError, match=r"^Linha 1 \(Pessoa\): e-mail inválido\.$"):
                normalize_student_import_values(values)


# --- single-student forms ---------------------------------------------------


def _assert_rejected(env, response, before):
    # A redirect carries the flash; a re-rendered form has already shown it.
    if response.status_code == 302:
        assert ("error", "E-mail inválido.") in _flashes(env["client"])
    else:
        assert "E-mail inválido." in response.get_data(as_text=True)
    assert _database_state() == before


@pytest.mark.parametrize("bad_email", MALFORMED)
def test_novo_aluno_rejects_a_malformed_email(tmp_path, bad_email):
    with isolated_versioned_app_env(tmp_path, "manual-novo.db") as env:
        _seed_existing_student()
        login_admin(env["client"])
        before = _database_state()

        response = env["client"].post(
            "/admin/adicionar_aluno",
            data={
                "nome": "Nova Pessoa",
                "email": bad_email,
                "senha": "",
                "matricula": "NEW-0001",
                "turma_id": str(TURMA_ID),
                "status": "Ativo",
            },
        )

        assert response.status_code == 200
        _assert_rejected(env, response, before)


@pytest.mark.parametrize("with_password", (False, True), ids=("no-password", "with-password"))
def test_editar_aluno_rejects_a_malformed_email(tmp_path, with_password):
    with isolated_versioned_app_env(tmp_path, "manual-editar-aluno.db") as env:
        usuario_id = _seed_existing_student()
        login_admin(env["client"])
        before = _database_state()

        response = env["client"].post(
            f"/admin/editar_aluno/{usuario_id}",
            data={
                "nome": "Aluna Renomeada",
                "email": "existente@example",
                "matricula": "EX-0001",
                "turma_id": str(TURMA_ID),
                "status": "Ativo",
                "senha": "NovaSenha#2026" if with_password else "",
            },
        )

        assert response.status_code == 200
        _assert_rejected(env, response, before)


@pytest.mark.parametrize("target", ("new", "existing"))
def test_acesso_rejects_a_malformed_email(tmp_path, target):
    with isolated_versioned_app_env(tmp_path, "manual-acesso.db") as env:
        usuario_id = _seed_existing_student()
        login_admin(env["client"])
        before = _database_state()

        form = {
            "nome": "Aluna Existente",
            "email": "existente@example",
            "nivel_acesso": "usuario",
            "senha": "",
            "matricula": "EX-0001" if target == "existing" else "NEW-0001",
            "status": "Ativo",
            "turma_id": str(TURMA_ID),
        }
        if target == "existing":
            form["usuario_id"] = str(usuario_id)
        response = env["client"].post("/admin/acesso/salvar", data=form)

        assert response.status_code == 302
        _assert_rejected(env, response, before)


def test_aluno_meus_dados_rejects_a_malformed_email(tmp_path):
    with isolated_versioned_app_env(tmp_path, "manual-aluno-dados.db") as env:
        login_student(env["client"])
        before = _database_state()

        response = env["client"].post(
            "/aluno/meus_dados",
            data={
                "nome": "Aluno Base Versionado",
                "email": "aluno.base@example",
                "matricula": "PPA.TESTE.0001",
                "senha": "",
            },
        )

        assert response.status_code == 200
        _assert_rejected(env, response, before)


def test_admin_meus_dados_rejects_a_malformed_email(tmp_path):
    with isolated_versioned_app_env(tmp_path, "manual-admin-dados.db") as env:
        login_admin(env["client"])
        before = _database_state()

        response = env["client"].post(
            "/admin/meus_dados",
            data={"nome": "Administrador", "email": "admin@example", "senha": ""},
        )

        assert response.status_code == 200
        _assert_rejected(env, response, before)


def test_valid_emails_on_single_student_forms_still_save(tmp_path):
    with isolated_versioned_app_env(tmp_path, "manual-single-valid.db") as env:
        usuario_id = _seed_existing_student()
        login_admin(env["client"])

        created = env["client"].post(
            "/admin/adicionar_aluno",
            data={
                "nome": "Nova Pessoa",
                "email": "nova@example.com",
                "senha": "",
                "matricula": "NEW-0001",
                "turma_id": str(TURMA_ID),
                "status": "Ativo",
            },
        )
        edited = env["client"].post(
            f"/admin/editar_aluno/{usuario_id}",
            data={
                "nome": "Aluna Existente",
                "email": "existente.nova@example.com",
                "matricula": "EX-0001",
                "turma_id": str(TURMA_ID),
                "status": "Ativo",
                "senha": "",
            },
        )

        assert created.status_code == 302
        assert edited.status_code == 302
        with main.app.app_context():
            conn = main.get_db_connection()
            emails = {
                row["matricula"]: row["email"]
                for row in conn.execute("SELECT matricula,email FROM alunos WHERE turma_id=?", (TURMA_ID,))
            }
        assert emails["NEW-0001"] == "nova@example.com"
        assert emails["EX-0001"] == "existente.nova@example.com"
