# coding: utf-8
"""PostgreSQL-readiness Unit 1: behaviour-neutral focus gate.

The unit keeps SGAA fully SQLite-backed while removing defects that would make
the same code invalid or unsafe on PostgreSQL.  These tests are the
discriminating gate for the six authorized items:

1. the five PG-rejected queries are structurally PostgreSQL-valid while the
   business results/order stay exactly as before;
2. INSERT + cursor.lastrowid is gone from production except at call sites that
   consume the ``create_usuario_with_access_level`` cursor contract;
3. the in-transaction retry runs under SAVEPOINT semantics;
4. presets_api uses the canonical app/db.py connection owner (PTBR registered,
   no second owner, no WAL pragma);
5. ordinary presets requests perform no schema DDL;
6. the fallback connection of the restore schema-status path is closed.

The structural assertions fail on the pre-fix tree; the equivalence assertions
are golden guards that must hold before and after.
"""
import inspect
import re
import sqlite3
import uuid
from pathlib import Path

import pytest

import main
import presets_api
from app.access_onboarding import access_status_map
from app.password_tokens import PURPOSE_PASSWORD_RESET, issue_password_token
from app.user_accounts import (
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_with_access_level,
)
from app.versioning.integrity import validar_integridade_versionamento_atividades
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Unit 3 replaced the cursor-return contract of ``create_usuario_*`` with an
#: explicit inserted-id result built from ``INSERT ... RETURNING id``; the only
#: production ``lastrowid`` reference left is that result's compatibility
#: property in ``app/user_accounts.py``.
RETAINED_LASTROWID_READS = {"app/user_accounts.py": 1}


@pytest.fixture(scope="module")
def client():
    with main.app.app_context():
        main.init_db()
        main.close_db_connection(None)
    yield main.app.test_client()


def _login_admin(client):
    with client.session_transaction() as session:
        session.update(user_id=1, user_type="admin", user_name="Administrador")
        stamp_auth_version(session)


def _capture_get(client, url):
    """Dispatch ``url`` on the runtime connection and keep every statement.

    The Flask test client reuses the top application context, so the request
    runs on the connection whose trace callback is installed here.
    """
    with main.app.app_context():
        main.close_db_connection(None)
        conn = main.get_db_connection()
        captured = []
        conn.set_trace_callback(captured.append)
        try:
            response = client.get(url)
        finally:
            conn.set_trace_callback(None)
            main.close_db_connection(None)
    return response, captured


def _execute_captured(statement):
    with main.app.app_context():
        main.close_db_connection(None)
        conn = main.get_db_connection()
        try:
            return conn.execute(statement).fetchall()
        finally:
            main.close_db_connection(None)


def _seed_mixed_axis_base(token):
    with main.app.app_context():
        main.close_db_connection(None)
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base(nome_conceito) VALUES(?) RETURNING id",
            (f"PGU1 Integridade {token}",),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO atividade_versao
                   (atividade_base_id,eixo,grupo,numero_versao,status)
               VALUES(?,?,?,1,'ativa')""",
            (base_id, "AAC", f"PGU1 Grupo {token}"),
        )
        conn.execute(
            """INSERT INTO atividade_versao
                   (atividade_base_id,eixo,grupo,numero_versao,status)
               VALUES(?,?,?,2,'ativa')""",
            (base_id, "AEU", f"PGU1 Grupo {token}"),
        )
        conn.commit()
        return base_id


def _delete_base(base_id):
    with main.app.app_context():
        main.close_db_connection(None)
        conn = main.get_db_connection()
        conn.execute(
            "DELETE FROM atividade_versao WHERE atividade_base_id=?", (base_id,)
        )
        conn.execute("DELETE FROM atividade_base WHERE id=?", (base_id,))
        conn.commit()
        main.close_db_connection(None)


def test_versioning_integrity_having_is_valid_for_postgres():
    token = uuid.uuid4().hex[:8]
    base_id = _seed_mixed_axis_base(token)
    try:
        with main.app.app_context():
            main.close_db_connection(None)
            conn = main.get_db_connection()
            captured = []
            conn.set_trace_callback(captured.append)
            try:
                issues = validar_integridade_versionamento_atividades(
                    conn, raise_on_error=False
                )
            finally:
                conn.set_trace_callback(None)
                main.close_db_connection(None)

        assert any(str(base_id) in issue for issue in issues), issues

        sql = next(
            s for s in captured if "HAVING" in s and "atividade_versao av" in s
        )
        having = sql.split("HAVING", 1)[1]
        assert "total_aac_ativas" not in having, sql
        assert "total_aeu_ativas" not in having, sql
    finally:
        _delete_base(base_id)


def test_access_status_derived_table_is_aliased():
    with main.app.app_context():
        main.close_db_connection(None)
        conn = main.get_db_connection()
        captured = []
        conn.set_trace_callback(captured.append)
        try:
            access_status_map(conn, [1])
        finally:
            conn.set_trace_callback(None)
            main.close_db_connection(None)

    sql = next(s for s in captured if "FROM (" in s and "sent_at" in s)
    assert re.search(r"\)\s*AS\s+\w+\s+WHERE", sql, re.I), sql


def test_admin_turmas_group_by_covers_joined_columns(client):
    token = uuid.uuid4().hex[:6].upper()
    curso_id = turma_id = None
    with main.app.app_context():
        main.close_db_connection(None)
        conn = main.get_db_connection()
        curso_id = conn.execute(
            "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES(?,?,8) RETURNING id",
            (f"PGU1 Turmas {token}", f"PGU1-TUR-{token}"),
        ).fetchone()[0]
        turma_id = conn.execute(
            """INSERT INTO turmas
                   (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo)
               VALUES(?,?,?,?,?,?,?,?) RETURNING id""",
            (
                f"PGU1 Turma {token}",
                "Noite",
                "Ativa",
                1,
                curso_id,
                2026,
                1,
                f"PGU1-TUR-{token}-T01",
            ),
        ).fetchone()[0]
        conn.commit()
        main.close_db_connection(None)

    _login_admin(client)
    try:
        response, captured = _capture_get(client, "/admin/turmas")
        assert response.status_code == 200
        assert f"PGU1-TUR-{token}-T01" in response.get_data(as_text=True)

        sql = next(
            s
            for s in captured
            if "COUNT(a.id) AS qtd_alunos" in s and "GROUP BY" in s
        )
        group_by = re.search(
            r"GROUP BY(.*?)(?:\s+HAVING|\s+ORDER BY|\s+LIMIT|$)", sql, re.S | re.I
        ).group(1)
        for column in (
            "c.nome",
            "c.codigo",
            "c.duracao_periodos",
            "tm.nome",
            "tm.status",
        ):
            assert column in group_by, (column, group_by)
    finally:
        with main.app.app_context():
            main.close_db_connection(None)
            conn = main.get_db_connection()
            if turma_id is not None:
                conn.execute("DELETE FROM turmas WHERE id=?", (turma_id,))
            if curso_id is not None:
                conn.execute("DELETE FROM cursos WHERE id=?", (curso_id,))
            conn.commit()
            main.close_db_connection(None)


def test_admin_requisicoes_dropdown_queries_are_valid_for_postgres(tmp_path):
    """Hermetic on purpose: the route fail-closes 409 on a dangling snapshot.

    The shared pytest session database can carry a historical request whose
    frozen snapshot is deliberately non-authoritative (a prior-suite artifact),
    so rendering /admin/requisicoes against it cannot assert 200.  This test
    owns a private, fully bootstrapped database with reference data and no
    requisicoes; the real route and its real authority validation stay in
    force, and nothing is monkeypatched.
    """
    with isolated_versioned_app_env(tmp_path, "pg-readiness-requisicoes.db") as env:
        client = env["client"]
        _login_admin(client)
        response, captured = _capture_get(client, "/admin/requisicoes")
        assert response.status_code == 200

        atividades_sql = next(
            s
            for s in captured
            if "matriz_atividade_versao_item mi" in s and "ORDER BY" in s
        )
        assert re.search(r"FROM\s*\(\s*SELECT\s+DISTINCT", atividades_sql, re.I), (
            atividades_sql
        )

        alunos_sql = next(
            s
            for s in captured
            if "COALESCE(NULLIF(TRIM(a.nome), ''), '') AS aluno_nome" in s
        )
        assert re.search(r"FROM\s*\(\s*SELECT\s+DISTINCT", alunos_sql, re.I), alunos_sql

        turmas_sql = next(
            s
            for s in captured
            if "COALESCE(NULLIF(TRIM(COALESCE(t.codigo, t.nome)), ''), '') AS turma_codigo"
            in s
        )
        assert "DISTINCT" not in turmas_sql.upper(), turmas_sql
        assert "GROUP BY" in turmas_sql.upper(), turmas_sql

        assert isinstance(_execute_captured(atividades_sql), list)
        assert isinstance(_execute_captured(alunos_sql), list)
        assert isinstance(_execute_captured(turmas_sql), list)


def test_admin_atividades_group_dropdown_is_valid_for_postgres(client):
    token = uuid.uuid4().hex[:8]
    base_id = _seed_mixed_axis_base(token)
    _login_admin(client)
    try:
        response, captured = _capture_get(client, "/admin/atividades")
        assert response.status_code == 200

        sql = next(
            s for s in captured if "canonical_activity" in s and "AS grupo" in s
        )
        assert "DISTINCT" not in sql.upper(), sql
        assert "GROUP BY" in sql.upper(), sql

        values = [str(row[0]) for row in _execute_captured(sql)]
        assert f"PGU1 Grupo {token}" in values
        assert values == sorted(values, key=lambda value: (value.lower(), value))
    finally:
        _delete_base(base_id)


def test_presets_load_uses_canonical_connection(monkeypatch, tmp_path):
    monkeypatch.setattr(
        presets_api, "PRESETS_PATH", str(tmp_path / "absent-presets.json")
    )
    with main.app.app_context():
        main.close_db_connection(None)
        loaded = presets_api.load_presets()
        assert isinstance(loaded, dict)
        conn = main.get_db_connection()
        assert conn.execute(
            "SELECT 'acao' = 'ação' COLLATE PTBR_NOACCENT"
        ).fetchone()[0] == 1
        main.close_db_connection(None)


def test_presets_module_owns_no_second_connection_and_no_request_ddl():
    source = (REPO_ROOT / "presets_api.py").read_text(encoding="utf-8")
    assert "sqlite3.connect(" not in source
    for name in (
        "load_presets",
        "save_presets",
        "_migrate_legacy_presets_if_needed",
        "_replace_presets_in_db",
    ):
        body = inspect.getsource(getattr(presets_api, name))
        assert "ensure_presets_schema" not in body, name


def test_presets_get_request_issues_no_schema_ddl(client):
    _login_admin(client)
    response, captured = _capture_get(client, "/admin/api/presets")
    assert response.status_code == 200
    joined = " ".join(captured).upper()
    for forbidden in ("CREATE TABLE", "CREATE INDEX", "DROP TABLE", "ALTER TABLE"):
        assert forbidden not in joined, captured


def _letter_token(length=6):
    return "".join(chr(ord("A") + int(char, 16)) for char in uuid.uuid4().hex[:length])


def test_course_code_collision_retries_inside_savepoint(client):
    token = _letter_token()
    code_a = f"PGUA{token}"
    code_b = f"PGUB{token}"
    code_new = f"PGUC{token}"
    colliding_turma_code = f"{code_new}-T01"
    curso_a_id = curso_b_id = turma_a_id = turma_b_id = None
    with main.app.app_context():
        main.close_db_connection(None)
        conn = main.get_db_connection()
        curso_a_id = conn.execute(
            "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES(?,?,8) RETURNING id",
            ("PGU1 Curso A", code_a),
        ).fetchone()[0]
        curso_b_id = conn.execute(
            "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES(?,?,8) RETURNING id",
            ("PGU1 Curso B", code_b),
        ).fetchone()[0]
        turma_a_id = conn.execute(
            """INSERT INTO turmas
                   (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo)
               VALUES(?,?,?,?,?,?,?,?) RETURNING id""",
            ("PGU1 Turma A", "Noite", "Ativa", 1, curso_a_id, 2026, 1, f"{code_a}-T01"),
        ).fetchone()[0]
        turma_b_id = conn.execute(
            """INSERT INTO turmas
                   (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo)
               VALUES(?,?,?,?,?,?,?,?) RETURNING id""",
            ("PGU1 Turma B", "Noite", "Ativa", 1, curso_b_id, 2026, 1, colliding_turma_code),
        ).fetchone()[0]
        conn.commit()
        main.close_db_connection(None)

    _login_admin(client)
    try:
        with main.app.app_context():
            main.close_db_connection(None)
            conn = main.get_db_connection()
            captured = []
            conn.set_trace_callback(captured.append)
            try:
                response = client.post(
                    f"/admin/cursos/{curso_a_id}/editar",
                    data={
                        "nome": "PGU1 Curso A",
                        "codigo": code_new,
                        "duracao_periodos": "8",
                        "status": "ativo",
                    },
                )
            finally:
                conn.set_trace_callback(None)
                main.close_db_connection(None)

        assert response.status_code in (302, 303), "\n".join(captured[-15:])

        with main.app.app_context():
            main.close_db_connection(None)
            conn = main.get_db_connection()
            row = conn.execute(
                "SELECT codigo FROM turmas WHERE id=?", (turma_a_id,)
            ).fetchone()
            assert row[0] == f"{colliding_turma_code}-{turma_a_id}"
            main.close_db_connection(None)

        assert any(
            statement.strip().upper().startswith("SAVEPOINT")
            for statement in captured
        ), captured
    finally:
        with main.app.app_context():
            main.close_db_connection(None)
            conn = main.get_db_connection()
            for turma_id in (turma_a_id, turma_b_id):
                if turma_id is not None:
                    conn.execute("DELETE FROM turmas WHERE id=?", (turma_id,))
            for curso_id in (curso_a_id, curso_b_id):
                if curso_id is not None:
                    conn.execute("DELETE FROM cursos WHERE id=?", (curso_id,))
            conn.commit()
            main.close_db_connection(None)


def test_restore_schema_status_fallback_closes_its_connection(monkeypatch):
    import app.views.admin.banco_dados as banco_dados

    opened = []

    class TrackedConnection(sqlite3.Connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.was_closed = False
            opened.append(self)

        def close(self):
            self.was_closed = True
            return super().close()

    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        kwargs.setdefault("factory", TrackedConnection)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", tracking_connect)
    with main.app.app_context():
        main.close_db_connection(None)
        status = banco_dados._get_current_schema_status_for_restore()

    try:
        assert isinstance(status, dict)
        assert opened, "the fallback path must open a connection"
        assert all(connection.was_closed for connection in opened)
    finally:
        for connection in opened:
            if not connection.was_closed:
                connection.close()


def test_lastrowid_is_confined_to_the_engine_neutral_result_contract():
    found = {}
    for base in ("app", "tools"):
        for path in (REPO_ROOT / base).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            count = path.read_text(encoding="utf-8").count("lastrowid")
            if count:
                found[path.relative_to(REPO_ROOT).as_posix()] = count
    assert found == RETAINED_LASTROWID_READS


def test_returning_conversions_preserve_generated_ids():
    token = uuid.uuid4().hex[:8]
    email = f"pgu1-{token}@example.invalid"
    with main.app.app_context():
        main.close_db_connection(None)
        conn = main.get_db_connection()
        try:
            _raw, token_id = issue_password_token(conn, 1, PURPOSE_PASSWORD_RESET)
            token_row = conn.execute(
                "SELECT id FROM senha_tokens WHERE id=?", (token_id,)
            ).fetchone()
            assert token_row is not None
            assert int(token_row["id"]) == token_id

            cursor = create_usuario_with_access_level(
                conn,
                f"PGU1 {token}",
                email,
                main.hash_password("pgu1-unit-1"),
                "admin",
                "consultivo",
                credential_state=CREDENTIAL_STATE_PERSONAL,
            )
            usuario_id = int(cursor.lastrowid)
            assert conn.execute(
                "SELECT email FROM usuarios WHERE id=?", (usuario_id,)
            ).fetchone()["email"] == email
            assert conn.execute(
                "SELECT 1 FROM usuario_credenciais WHERE usuario_id=?",
                (usuario_id,),
            ).fetchone() is not None
        finally:
            conn.rollback()
            main.close_db_connection(None)
