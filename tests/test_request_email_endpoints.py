"""HTTP contract for the preview/send endpoints.

The transport is faked in every test; nothing here contacts Microsoft Graph.
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest

import main
import app.request_email_dispatch as dispatch_module
from tests.session_support import stamp_auth_version



@pytest.fixture(scope="module")
def client():
    """Reuse the shared session app and close its connection on teardown.

    Mirrors tests/test_security.py: a per-test ``create_app()`` leaves the
    runtime database handle open and the session cannot remove its temp root.
    """
    app = main.app
    with app.app_context():
        main.init_db()
        try:
            main.close_db_connection(None)
        except Exception:
            pass

    with app.test_client() as test_client:
        yield test_client

    with app.app_context():
        try:
            main.close_db_connection(None)
        except Exception:
            pass


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"
        stamp_auth_version(sess)


def _conn():
    conn = sqlite3.connect(main.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _seed_decided_request(conn, *, email="aluno@example.com"):
    from tests.request_email_support import seed_activity, seed_request, seed_student

    versao = seed_activity(conn, nome=f"Atividade {uuid.uuid4()}")
    matricula = uuid.uuid4().hex[:12]
    aluno = seed_student(conn, nome="Aluno Teste", matricula=matricula, email=email)
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    conn.execute(
        "UPDATE requisicoes SET status='Deferida', data_processamento='2026-04-01 09:00:00'"
        " WHERE id=?",
        (req,),
    )
    from app.request_email_notifications import record_final_decision_event

    record_final_decision_event(conn, requisicao_id=req)
    conn.commit()
    return req


def _install_default_preset(conn):
    conn.execute("DELETE FROM configuracoes_presets WHERE tipo='emails'")
    conn.execute(
        "INSERT INTO configuracoes_presets"
        "(tipo,preset_id,titulo,texto,assunto,is_default)"
        " VALUES('emails',1,'Padrao','{saudacao}, {aluno.primeironome}.\n\n{requisicoes}',"
        "'Resultado das suas requisicoes',1)"
    )
    conn.commit()


def test_preview_requires_authentication(client):
    response = client.post("/admin/requisicoes/email/preview", json={"requisicao_ids": [1]})
    assert response.status_code in (302, 401, 403)


def test_send_requires_authentication(client):
    response = client.post("/admin/requisicoes/email/enviar", json={"requisicao_ids": [1]})
    assert response.status_code in (302, 401, 403)


def test_preview_rejects_empty_selection(client):
    _login_admin(client)
    response = client.post("/admin/requisicoes/email/preview", json={"requisicao_ids": []})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_preview_rejects_selection_with_non_pending_request(client):
    _login_admin(client)
    conn = _conn()
    try:
        _install_default_preset(conn)
        pending = _seed_decided_request(conn, email="p1@example.com")
        from tests.request_email_support import seed_activity, seed_request, seed_student

        versao = seed_activity(conn, nome=f"Atividade {uuid.uuid4()}")
        aluno = seed_student(conn, nome="Outro", matricula=uuid.uuid4().hex[:12],
                             email=f"o-{uuid.uuid4().hex[:6]}@example.com")
        nao_pendente = seed_request(conn, aluno_id=aluno, versao_id=versao)
        conn.commit()
    finally:
        conn.close()

    response = client.post(
        "/admin/requisicoes/email/preview",
        json={"requisicao_ids": [pending, nao_pendente]},
    )
    assert response.status_code == 409
    body = response.get_json()
    assert body["ok"] is False
    assert nao_pendente in body["nao_pendentes"]


def test_preview_reports_counts_without_sending(client, monkeypatch):
    _login_admin(client)
    conn = _conn()
    try:
        _install_default_preset(conn)
        first = _seed_decided_request(conn, email="a1@example.com")
        second = _seed_decided_request(conn, email="a2@example.com")
    finally:
        conn.close()

    sent: list = []
    monkeypatch.setattr(
        dispatch_module, "send_text_email", lambda *a, **k: sent.append(a) or {}
    )

    response = client.post(
        "/admin/requisicoes/email/preview", json={"requisicao_ids": [first, second]}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["requisicoes"] == 2
    assert body["alunos"] == 2
    assert body["emails"] == 2
    assert body["modelo"]["titulo"] == "Padrao"
    # Preview must never send.
    assert sent == []


def test_preview_never_leaks_provider_internals(client):
    _login_admin(client)
    conn = _conn()
    try:
        _install_default_preset(conn)
        req = _seed_decided_request(conn, email="leak@example.com")
    finally:
        conn.close()

    response = client.post(
        "/admin/requisicoes/email/preview", json={"requisicao_ids": [req]}
    )
    payload = response.get_data(as_text=True)
    for forbidden in ("access_token", "refresh_token", "client_secret", "Bearer ", "msal_cache"):
        assert forbidden not in payload


def test_send_marks_events_sent_with_faked_transport(client, monkeypatch):
    _login_admin(client)
    conn = _conn()
    try:
        _install_default_preset(conn)
        req = _seed_decided_request(conn, email="ok@example.com")
    finally:
        conn.close()

    monkeypatch.setattr(
        dispatch_module,
        "send_text_email",
        lambda conn_, message: {"status": "sent", "http_status": 202},
    )

    response = client.post(
        "/admin/requisicoes/email/enviar", json={"requisicao_ids": [req]}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["enviados"] == 1

    verify = _conn()
    try:
        assert verify.execute(
            "SELECT estado FROM requisicao_email_eventos WHERE requisicao_id=?", (req,)
        ).fetchone()[0] == "sent"
    finally:
        verify.close()


def test_duplicate_post_does_not_send_twice(client, monkeypatch):
    _login_admin(client)
    conn = _conn()
    try:
        _install_default_preset(conn)
        req = _seed_decided_request(conn, email="dup@example.com")
    finally:
        conn.close()

    calls: list = []

    def _fake(conn_, message):
        calls.append(message.to_address)
        return {"status": "sent", "http_status": 202}

    monkeypatch.setattr(dispatch_module, "send_text_email", _fake)

    first = client.post("/admin/requisicoes/email/enviar", json={"requisicao_ids": [req]})
    second = client.post("/admin/requisicoes/email/enviar", json={"requisicao_ids": [req]})

    assert first.get_json()["enviados"] == 1
    # The second POST finds no pending event at all, so it cannot resend.
    assert second.status_code == 409 or second.get_json().get("enviados") == 0
    assert len(calls) == 1


def test_send_without_default_template_is_refused(client):
    _login_admin(client)
    conn = _conn()
    try:
        conn.execute("UPDATE configuracoes_presets SET is_default=0 WHERE tipo='emails'")
        req = _seed_decided_request(conn, email="nodefault@example.com")
    finally:
        conn.close()

    response = client.post(
        "/admin/requisicoes/email/enviar", json={"requisicao_ids": [req]}
    )
    assert response.status_code == 400
    assert "padrão" in response.get_json()["error"].lower()
