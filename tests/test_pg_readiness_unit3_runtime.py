# coding: utf-8
"""PostgreSQL-readiness Unit 3: runtime adapter integration focus gate.

The unit makes ordinary SGAA runtime call sites consume the engine-neutral
facilities introduced in Unit 2 while SQLite stays the default, behaviourally
unchanged engine:

A. runtime paths that depend on ``sqlite3.IntegrityError`` accept an
   engine-neutral integrity exception (psycopg-shaped, no SQLite involved);
B. a unique violation still takes a different branch than a generic integrity
   violation, and the SQLite user-visible message is preserved.  The fake
   injects the project's logical ``table.column`` constraint identity; real
   PostgreSQL constraint-name mapping stays deferred to the schema unit (F-2);
C. ``.in_transaction`` in runtime token consumption becomes the engine-neutral
   transaction-state helper;
D. ``create_usuario_with_access_level`` yields the inserted id through an
   explicit result contract, never through a DB-API ``cursor.lastrowid``;
E. current SQLite behaviour is preserved at the migrated call sites;
F. every remaining direct ``sqlite3.connect`` belongs to the canonical owner,
   migration, backup/restore or tooling -- no request path opens a second
   database;
G. a migrated integrity handler that continues to use the request connection
   (directly or through render-time context processors) rolls the failed
   PostgreSQL transaction back before that use, so INERROR never leaks into
   the page (F-1).

All psycopg behaviour is mocked locally; no network, no Supabase, no schema.
"""
import inspect
import sqlite3
import types
from pathlib import Path

import psycopg.errors
import pytest
from flask import g, session

import main
from app import db as app_db
from app.activity_catalog import delete_activity_version
from app.password_tokens import (
    PURPOSE_FIRST_ACCESS,
    PasswordTokenError,
    consume_password_token_and_set_password,
)
from app.student_import import StudentImportRow, StudentImportError
from app.services import student_import_service
from app.user_accounts import (
    CREDENTIAL_STATE_PENDING,
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_with_access_level,
)
from tests.session_support import existing_admin_user_id, stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Runtime modules that must stop catching/raising SQLite exception classes in
#: this unit; every psycopg-shaped database error must be classified through
#: ``app.db`` instead.
SQLITE_FREE_RUNTIME_MODULES = (
    "app/activity_catalog.py",
    "app/arquivos.py",
    "app/services/student_import_service.py",
    "app/views/aluno.py",
    "app/views/admin/acesso.py",
    "app/views/admin/activity_version_delete.py",
    "app/views/admin/alunos_turmas_cursos.py",
    "app/views/admin/atividades.py",
    "app/views/admin/meus_dados.py",
    "app/views/admin/matrizes.py",
)

#: Every module allowed to open a private ``sqlite3.connect`` directly: the
#: canonical connection owner, schema migration/bootstrap, backup/restore
#: machinery and the restore schema-status fallback.  A request path opening
#: its own database would be a hidden second writer.
DIRECT_SQLITE_CONNECT_OWNERS = frozenset(
    {
        "app/db.py",
        "app/backup/automatic.py",
        "app/backup/orchestrator.py",
        "app/db_maintenance.py",
        "app/prod1_schema.py",
        "app/services/backup_service.py",
        "app/views/admin/banco_dados.py",
    }
)


class _FakeUniqueViolation(psycopg.errors.UniqueViolation):
    """A psycopg unique violation carrying the logical SQLite constraint name.

    This exercises the runtime branch shape engine-neutrally.  It does not
    claim any real PostgreSQL constraint-name mapping: naming stays deferred
    to the PostgreSQL schema/constraint unit (F-2).
    """

    def __init__(self, constraint_name):
        super().__init__(
            f'duplicate key value violates unique constraint "{constraint_name}"'
        )
        self._constraint_name = constraint_name

    @property
    def diag(self):
        return types.SimpleNamespace(constraint_name=self._constraint_name)


class _IntegrityRaisingConnection:
    """Real runtime connection whose canonical INSERTs fail like PostgreSQL."""

    def __init__(self, real, exc, marker="INSERT INTO USUARIOS"):
        self._real = real
        self._exc = exc
        self._marker = marker

    def execute(self, sql, params=None):
        if self._marker in str(sql).upper():
            raise self._exc
        if params is None:
            return self._real.execute(sql)
        return self._real.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _ZeroRowcountDeleteConnection:
    """Proxy turning the exact-version DELETE into a lost-target result."""

    def __init__(self, real):
        self._real = real

    def execute(self, sql, params=None):
        if str(sql).strip().upper().startswith("DELETE FROM ATIVIDADE_VERSAO"):
            return types.SimpleNamespace(rowcount=0)
        if params is None:
            return self._real.execute(sql)
        return self._real.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _FakeEngineCursor:
    def __init__(self):
        self.executed = []
        self.description = None
        self._rows = []
        self.fetchone_calls = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "INSERT INTO usuarios" in sql:
            self.description = [("id",)]
            self._rows = [(4242,)]
        return self

    def fetchone(self):
        self.fetchone_calls += 1
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeEngineConnection:
    def __init__(self):
        self.created = []

    def cursor(self):
        cursor = _FakeEngineCursor()
        self.created.append(cursor)
        return cursor


def _sqlite_connection_with_usuario_schema():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT, email TEXT, senha TEXT, tipo TEXT, nivel_acesso TEXT
        );
        CREATE TABLE usuario_credenciais (
            usuario_id INTEGER PRIMARY KEY,
            estado TEXT,
            auth_version INTEGER NOT NULL DEFAULT 1,
            acesso_ativo INTEGER NOT NULL DEFAULT 1,
            atualizado_em TEXT
        );
        """
    )
    return conn


def _login_admin_as(client, admin_id):
    with client.session_transaction() as session:
        session.update(user_id=admin_id, user_type="admin", user_name="Admin U3")
        stamp_auth_version(session, admin_id)


def _login_admin(client):
    _login_admin_as(client, existing_admin_user_id())


def _post_adicionar_aluno(client, *, email, matricula, turma_id="1"):
    return client.post(
        "/admin/adicionar_aluno",
        data={
            "nome": "Aluna U3",
            "email": email,
            "senha": "",
            "matricula": matricula,
            "turma_id": turma_id,
            "status": "Ativo",
        },
    )


# ---------------------------------------------------------------------------
# D. engine-neutral inserted-id contract
# ---------------------------------------------------------------------------


def test_create_usuario_returns_explicit_insert_result_over_postgres(monkeypatch):
    monkeypatch.setattr(
        "app.user_accounts.ensure_usuario_access_schema", lambda conn: None
    )
    raw = _FakeEngineConnection()
    adapter = app_db._PostgresConnectionAdapter(raw)

    result = create_usuario_with_access_level(
        adapter,
        "Aluna U3",
        "aluna.u3@example.test",
        "hash",
        "aluno",
        "usuario",
        credential_state=CREDENTIAL_STATE_PENDING,
    )

    result_cls = getattr(
        __import__("app.user_accounts", fromlist=["x"]), "UsuarioInsertResult", None
    )
    assert result_cls is not None, "an explicit inserted-id result contract is required"
    assert isinstance(result, result_cls)
    assert getattr(result, "usuario_id", None) == 4242
    assert getattr(result, "lastrowid", None) == 4242

    insert_cursor = next(
        cursor
        for cursor in raw.created
        if any("INSERT INTO usuarios" in statement for statement, _ in cursor.executed)
    )
    assert "RETURNING id" in insert_cursor.executed[0][0]
    assert insert_cursor.fetchone_calls == 1


def test_create_usuario_insert_result_preserves_sqlite_identity(monkeypatch):
    monkeypatch.setattr(
        "app.user_accounts.ensure_usuario_access_schema", lambda conn: None
    )
    conn = _sqlite_connection_with_usuario_schema()
    try:
        result = create_usuario_with_access_level(
            conn,
            "Aluna U3",
            "aluna.u3.sqlite@example.test",
            "hash",
            "aluno",
            "usuario",
            credential_state=CREDENTIAL_STATE_PENDING,
        )
        stored = conn.execute(
            "SELECT id FROM usuarios WHERE email=?",
            ("aluna.u3.sqlite@example.test",),
        ).fetchone()
        assert stored is not None
        assert getattr(result, "usuario_id", None) == int(stored[0])
        assert getattr(result, "lastrowid", None) == int(stored[0])
        credential = conn.execute(
            "SELECT usuario_id FROM usuario_credenciais WHERE usuario_id=?",
            (int(stored[0]),),
        ).fetchone()
        assert credential is not None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# E. neutral classification of the adapter's own errors
# ---------------------------------------------------------------------------


def test_neutral_database_error_classifies_as_itself():
    integrity = app_db.DatabaseIntegrityError("boom", is_unique=False)
    assert app_db.is_integrity_error(integrity) is True
    assert app_db.is_unique_violation(integrity) is False

    unique = app_db.DatabaseIntegrityError("boom", is_unique=True)
    assert app_db.is_integrity_error(unique) is True
    assert app_db.is_unique_violation(unique) is True

    operational = app_db.DatabaseOperationalError("locked")
    assert app_db.is_operational_error(operational) is True
    assert app_db.is_integrity_error(operational) is False


def test_delete_activity_version_raises_neutral_integrity_error():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE atividade_versao (
            id INTEGER PRIMARY KEY,
            atividade_base_id INTEGER,
            versao_anterior_id INTEGER,
            numero_versao INTEGER
        );
        CREATE TABLE atividade_transicao (
            from_atividade_versao_id INTEGER, to_atividade_versao_id INTEGER
        );
        CREATE TABLE requisicoes (id INTEGER PRIMARY KEY, atividade_versao_id INTEGER);
        CREATE TABLE matriz_atividade_versao_item (
            matriz_id INTEGER, atividade_versao_id INTEGER
        );
        CREATE TABLE matrizes_atividades (id INTEGER PRIMARY KEY, nome TEXT);
        INSERT INTO atividade_versao VALUES (1, 10, NULL, 1);
        INSERT INTO atividade_versao VALUES (2, 10, 1, 2);
        """
    )
    try:
        with pytest.raises(app_db.DatabaseIntegrityError) as excinfo:
            delete_activity_version(
                _ZeroRowcountDeleteConnection(conn), base_id=10, versao_id=2
            )
        assert app_db.is_integrity_error(excinfo.value) is True
        assert app_db.is_unique_violation(excinfo.value) is False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# A. engine-neutral integrity failure on an ordinary runtime path
# ---------------------------------------------------------------------------


def test_student_import_converts_engine_neutral_integrity_failure(monkeypatch):
    monkeypatch.setattr(
        "app.user_accounts.ensure_usuario_access_schema", lambda conn: None
    )
    monkeypatch.setattr(
        student_import_service, "prepare_pending_password_hashes", lambda count: []
    )
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE turmas (id INTEGER PRIMARY KEY);
        CREATE TABLE alunos (
            id INTEGER PRIMARY KEY, usuario_id INTEGER, nome TEXT, email TEXT,
            matricula TEXT, turma_id INTEGER, matriz_id INTEGER, status TEXT
        );
        CREATE TABLE usuarios (id INTEGER PRIMARY KEY, tipo TEXT, email TEXT);
        INSERT INTO turmas(id) VALUES (1);
        """
    )
    try:
        proxy = _IntegrityRaisingConnection(
            conn,
            psycopg.errors.UniqueViolation(
                'duplicate key value violates unique constraint "usuarios_email_key"'
            ),
        )
        row = StudentImportRow(
            aluno="Aluna U3",
            email="aluna.u3.import@example.test",
            matricula="U3-IMPORT-1",
            source_row=7,
        )
        with pytest.raises(StudentImportError) as excinfo:
            student_import_service.import_students_into_turma(proxy, 1, [row])
        message = str(excinfo.value)
        assert "Linha 7" in message
        assert "conflito" in message
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# B + E. unique branch versus generic integrity branch, PostgreSQL-shaped
# ---------------------------------------------------------------------------


def test_admin_add_aluno_engine_neutral_unique_email_branch(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "u3-pg-unique.db") as env:
        client = env["client"]
        _login_admin(client)
        import app.views.admin.alunos_turmas_cursos as alunos_module

        with main.app.app_context():
            main.close_db_connection(None)
            real = main.get_db_connection()
            proxy = _IntegrityRaisingConnection(
                real, _FakeUniqueViolation("usuarios.email")
            )
            monkeypatch.setattr(alunos_module, "get_db_connection", lambda: proxy)
            try:
                response = _post_adicionar_aluno(
                    client,
                    email="aluna.u3.pg@example.test",
                    matricula="U3-PG-UNIQUE",
                )
            finally:
                main.close_db_connection(None)

        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Já existe um usuário com este e-mail." in text


def test_admin_add_aluno_engine_neutral_generic_integrity_branch(
    tmp_path, monkeypatch
):
    with isolated_versioned_app_env(tmp_path, "u3-pg-generic.db") as env:
        client = env["client"]
        _login_admin(client)
        import app.views.admin.alunos_turmas_cursos as alunos_module

        with main.app.app_context():
            main.close_db_connection(None)
            real = main.get_db_connection()
            proxy = _IntegrityRaisingConnection(
                real,
                psycopg.errors.CheckViolation(
                    'new row violates check constraint "usuarios_tipo_check"'
                ),
            )
            monkeypatch.setattr(alunos_module, "get_db_connection", lambda: proxy)
            try:
                response = _post_adicionar_aluno(
                    client,
                    email="aluna.u3.pg.generic@example.test",
                    matricula="U3-PG-GENERIC",
                )
            finally:
                main.close_db_connection(None)

        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Erro ao adicionar aluno:" in text
        assert "Erro inesperado" not in text


def test_admin_add_aluno_sqlite_unique_email_message_preserved(tmp_path):
    with isolated_versioned_app_env(tmp_path, "u3-sqlite-dupe.db") as env:
        client = env["client"]
        _login_admin(client)
        response = _post_adicionar_aluno(
            client,
            email="aluno.base.versionado@example.com",
            matricula="U3-SQLITE-DUP-1",
        )
        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Já existe um usuário com este e-mail." in text


# ---------------------------------------------------------------------------
# C + E. transaction-state call sites
# ---------------------------------------------------------------------------


def test_token_consumption_refuses_engine_neutral_open_transaction():
    status = types.SimpleNamespace(name="INTRANS")
    raw = types.SimpleNamespace(
        info=types.SimpleNamespace(transaction_status=status)
    )
    with pytest.raises(PasswordTokenError) as excinfo:
        consume_password_token_and_set_password(
            raw, "raw-token", PURPOSE_FIRST_ACCESS, "hash"
        )
    assert "clean transaction" in str(excinfo.value)


def test_token_consumption_refuses_sqlite_open_transaction():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE t(x)")
        conn.execute("INSERT INTO t VALUES (1)")
        with pytest.raises(PasswordTokenError) as excinfo:
            consume_password_token_and_set_password(
                conn, "raw-token", PURPOSE_FIRST_ACCESS, "hash"
            )
        assert "clean transaction" in str(excinfo.value)
    finally:
        conn.close()


def test_password_tokens_transaction_state_is_engine_neutral():
    from app import password_tokens

    source = inspect.getsource(
        password_tokens.consume_password_token_and_set_password
    )
    assert "connection_in_transaction(conn)" in source
    assert "conn.in_transaction" not in source


# ---------------------------------------------------------------------------
# G (F-1). PostgreSQL failed-transaction (INERROR) enforcement
# ---------------------------------------------------------------------------


class _FailedTransactionError(RuntimeError):
    """PostgreSQL refuses SQL while the transaction is in error."""


class _PostgresErrorStateConnection:
    """Real connection wrapped with psycopg's failed-transaction semantics.

    The injected statement raises the engine-neutral integrity failure and
    leaves the connection INERROR; every later ``execute`` raises until
    ``rollback`` clears the state.  ``violations`` records each attempted use
    while failed, so a test can prove no SQL ran before the rollback.
    """

    def __init__(self, real, exc, marker):
        self._real = real
        self._exc = exc
        self._marker = marker
        self.failed = False
        self.rollbacks = 0
        self.violations = []

    def execute(self, sql, params=None):
        if self.failed:
            self.violations.append(str(sql))
            raise _FailedTransactionError(str(sql))
        if self._marker in str(sql).upper():
            self.failed = True
            raise self._exc
        if params is None:
            return self._real.execute(sql)
        return self._real.execute(sql, params)

    def rollback(self):
        self.failed = False
        self.rollbacks += 1
        return self._real.rollback()

    def commit(self):
        return self._real.commit()

    def __getattr__(self, name):
        return getattr(self._real, name)


def _install_fake_connection(monkeypatch, fake, *modules):
    """Route every canonical connection lookup in the request to one fake."""

    def provider():
        g.db = fake
        return fake

    monkeypatch.setattr(app_db, "get_db_connection", provider)
    for module in modules:
        monkeypatch.setattr(module, "get_db_connection", provider)


def _request_modules(view_module):
    import app.admin_access as admin_access_module
    import app.web.context as web_context

    return view_module, web_context, admin_access_module


def _clear_request_caches():
    g.pop("admin_access_context", None)
    g.pop("_frontend_message_templates_cache", None)


def test_admin_adicionar_aluno_rolls_back_before_render_query(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "u3-f1-aluno.db"):
        import app.views.admin.alunos_turmas_cursos as alunos_module

        modules = _request_modules(alunos_module)
        with main.app.test_request_context(
            "/admin/adicionar_aluno",
            method="POST",
            data={
                "nome": "Aluna F1",
                "email": "aluna.f1@example.test",
                "senha": "",
                "matricula": "U3-F1-1",
                "turma_id": "1",
                "status": "Ativo",
            },
        ):
            session.update(
                user_id=existing_admin_user_id(),
                user_type="admin",
                user_name="Admin U3",
            )
            main.close_db_connection(None)
            real = main.get_db_connection()
            fake = _PostgresErrorStateConnection(
                real,
                _FakeUniqueViolation("usuarios.email"),
                "INSERT INTO USUARIOS",
            )
            _install_fake_connection(monkeypatch, fake, *modules)
            _clear_request_caches()
            try:
                response = main.app.make_response(
                    alunos_module.admin_adicionar_aluno()
                )
            finally:
                main.close_db_connection(None)

        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Já existe um usuário com este e-mail." in text
        assert fake.rollbacks == 1
        assert fake.violations == []


def test_admin_adicionar_curso_rolls_back_before_render(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "u3-f1-curso-add.db"):
        import app.views.admin.alunos_turmas_cursos as alunos_module

        modules = _request_modules(alunos_module)
        with main.app.test_request_context(
            "/admin/adicionar_curso",
            method="POST",
            data={
                "nome": "Curso F1",
                "codigo": "PPA",
                "duracao_periodos": "8",
                "status": "ativo",
            },
        ):
            session.update(
                user_id=existing_admin_user_id(),
                user_type="admin",
                user_name="Admin U3",
            )
            main.close_db_connection(None)
            real = main.get_db_connection()
            fake = _PostgresErrorStateConnection(
                real,
                _FakeUniqueViolation("cursos.codigo"),
                "INSERT INTO CURSOS",
            )
            _install_fake_connection(monkeypatch, fake, *modules)
            _clear_request_caches()
            try:
                response = main.app.make_response(
                    alunos_module.admin_adicionar_curso()
                )
            finally:
                main.close_db_connection(None)

        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Já existe um curso com este código." in text
        assert fake.rollbacks == 1
        assert fake.violations == []


def test_admin_editar_curso_rolls_back_before_render(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "u3-f1-curso-edit.db"):
        import app.views.admin.alunos_turmas_cursos as alunos_module

        modules = _request_modules(alunos_module)
        with main.app.test_request_context(
            "/admin/cursos/1/editar",
            method="POST",
            data={
                "nome": "PPA",
                "codigo": "GERAL",
                "duracao_periodos": "8",
                "status": "ativo",
            },
        ):
            session.update(
                user_id=existing_admin_user_id(),
                user_type="admin",
                user_name="Admin U3",
            )
            main.close_db_connection(None)
            real = main.get_db_connection()
            curso_id = real.execute(
                "SELECT id FROM cursos WHERE codigo='PPA'"
            ).fetchone()[0]
            fake = _PostgresErrorStateConnection(
                real,
                _FakeUniqueViolation("cursos.codigo"),
                "UPDATE CURSOS",
            )
            _install_fake_connection(monkeypatch, fake, *modules)
            _clear_request_caches()
            try:
                response = main.app.make_response(
                    alunos_module.admin_editar_curso(int(curso_id))
                )
            finally:
                main.close_db_connection(None)

        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Já existe um curso com este código." in text
        assert fake.rollbacks == 1
        assert fake.violations == []


def test_admin_meus_dados_rolls_back_before_render(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "u3-f1-meus-dados.db"):
        import app.views.admin.meus_dados as meus_dados_module

        with main.app.app_context():
            main.close_db_connection(None)
            conn = main.get_db_connection()
            admin_id = create_usuario_with_access_level(
                conn,
                "Admin F1",
                "admin.f1@example.test",
                main.hash_password("f1-secret"),
                "admin",
                "admin_total",
                credential_state=CREDENTIAL_STATE_PERSONAL,
            ).usuario_id
            conn.commit()
            main.close_db_connection(None)

        modules = _request_modules(meus_dados_module)
        with main.app.test_request_context(
            "/admin/meus_dados",
            method="POST",
            data={
                "nome": "Admin F1",
                "email": "aluno.base.versionado@example.com",
            },
        ):
            session.update(
                user_id=admin_id, user_type="admin", user_name="Admin F1"
            )
            main.close_db_connection(None)
            real = main.get_db_connection()
            fake = _PostgresErrorStateConnection(
                real,
                _FakeUniqueViolation("usuarios.email"),
                "UPDATE USUARIOS SET EMAIL",
            )
            _install_fake_connection(monkeypatch, fake, *modules)
            _clear_request_caches()
            try:
                response = main.app.make_response(
                    meus_dados_module.admin_meus_dados()
                )
            finally:
                main.close_db_connection(None)

        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Erro: Já existe outro usuário com este e-mail." in text
        assert fake.rollbacks == 1
        assert fake.violations == []


# ---------------------------------------------------------------------------
# G (F-1). SQLite equivalence for the four rollback-protected handlers
# ---------------------------------------------------------------------------


def test_admin_adicionar_curso_sqlite_duplicate_code_message_preserved(tmp_path):
    with isolated_versioned_app_env(tmp_path, "u3-f1-sqlite-curso-add.db") as env:
        client = env["client"]
        _login_admin(client)
        response = client.post(
            "/admin/cursos/adicionar",
            data={
                "nome": "Curso duplicado",
                "codigo": "PPA",
                "duracao_periodos": "8",
                "status": "ativo",
            },
        )
        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Já existe um curso com este código." in text


def test_admin_editar_curso_sqlite_duplicate_code_message_preserved(tmp_path):
    with isolated_versioned_app_env(tmp_path, "u3-f1-sqlite-curso-edit.db") as env:
        client = env["client"]
        _login_admin(client)
        with main.app.app_context():
            main.close_db_connection(None)
            conn = main.get_db_connection()
            curso_id = conn.execute(
                "SELECT id FROM cursos WHERE codigo='PPA'"
            ).fetchone()[0]
            main.close_db_connection(None)
        response = client.post(
            f"/admin/cursos/{int(curso_id)}/editar",
            data={
                "nome": "PPA",
                "codigo": "GERAL",
                "duracao_periodos": "8",
                "status": "ativo",
            },
        )
        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Já existe um curso com este código." in text


def test_admin_meus_dados_sqlite_duplicate_email_message_preserved(tmp_path):
    with isolated_versioned_app_env(tmp_path, "u3-f1-sqlite-meus-dados.db") as env:
        client = env["client"]
        with main.app.app_context():
            main.close_db_connection(None)
            conn = main.get_db_connection()
            admin_id = create_usuario_with_access_level(
                conn,
                "Admin F1",
                "admin.f1.sqlite@example.test",
                main.hash_password("f1-secret"),
                "admin",
                "admin_total",
                credential_state=CREDENTIAL_STATE_PERSONAL,
            ).usuario_id
            conn.commit()
            main.close_db_connection(None)
        _login_admin_as(client, admin_id)
        response = client.post(
            "/admin/meus_dados",
            data={
                "nome": "Admin F1",
                "email": "aluno.base.versionado@example.com",
            },
        )
        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "Erro: Já existe outro usuário com este e-mail." in text


# ---------------------------------------------------------------------------
# Structural gates: coupling inventory
# ---------------------------------------------------------------------------


def test_runtime_exception_call_sites_are_sqlite_free():
    remaining = {
        relative: (REPO_ROOT / relative).read_text(encoding="utf-8")
        for relative in SQLITE_FREE_RUNTIME_MODULES
        if "sqlite3" in (REPO_ROOT / relative).read_text(encoding="utf-8")
    }
    assert remaining == {}


def test_direct_sqlite_connect_owners_are_maintenance_and_tooling():
    found = {}
    for path in (REPO_ROOT / "app").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if "sqlite3.connect(" in path.read_text(encoding="utf-8"):
            found[path.relative_to(REPO_ROOT).as_posix()] = True
    assert frozenset(found) == DIRECT_SQLITE_CONNECT_OWNERS
