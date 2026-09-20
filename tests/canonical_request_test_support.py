"""Shared builders for prod-1 request tests."""
from __future__ import annotations

import main
from app.user_accounts import get_usuario_auth_version
from tests.session_support import stamp_auth_version


def student_identity():
    with main.app.app_context():
        return dict(main.get_db_connection().execute(
            "SELECT a.id AS aluno_id,a.usuario_id FROM alunos a WHERE a.matricula='PPA.TESTE.0001'"
        ).fetchone())


def login_admin(client):
    with main.app.app_context():
        conn = main.get_db_connection()
        admin_id = conn.execute(
            "SELECT id FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        auth_version = get_usuario_auth_version(conn, admin_id)
    with client.session_transaction() as session:
        session.update(
            user_id=admin_id,
            user_type="admin",
            user_name="Admin",
            auth_version=auth_version,
        )


def login_student(client):
    identity = student_identity()
    with client.session_transaction() as session:
        session.update(
            user_id=identity["usuario_id"],
            user_type="aluno",
            user_name="Aluno",
        )
        stamp_auth_version(session)
    return identity


def create_admin_request(client, name="Canonical admin request", version_id=29):
    identity = student_identity()
    response = client.post("/admin/requisicoes/nova", data={
        "aluno_id": str(identity["aluno_id"]), "atividade_versao_id": str(version_id),
        "nome_evento": name, "data_evento": "2026-05-01",
        "horas_solicitadas": "4", "observacao": "canonical",
    })
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM requisicoes WHERE nome_evento=?", (name,)
        ).fetchone()
        return response, dict(row) if row else None
