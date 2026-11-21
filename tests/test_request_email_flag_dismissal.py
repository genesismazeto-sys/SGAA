"""UI-B47: an administrator withdraws the pending-email flag of a decision.

Owner contract (``dismiss_pending_events``) on a disposable in-memory schema,
then the route on an isolated application database. The transport is faked
and records every call: no test may reach a provider, and none may send.
"""
from __future__ import annotations

import re

import pytest

import main
import app.request_email_dispatch as dispatch_module
from app.request_email_dispatch import build_plan
from app.request_email_notifications import (
    EmailFlagDismissalStale,
    attach_events_to_send,
    dismiss_pending_events,
    failed_request_ids,
    pending_event_ids,
    pending_request_ids,
)
from app.user_accounts import create_usuario_with_access_level, get_usuario_auth_version
from tests.canonical_matrix_test_support import login_admin
from tests.canonical_request_test_support import create_admin_request
from tests.request_email_support import (
    decide,
    install_email_preset,
    new_v7_connection,
    reopen,
    seed_activity,
    seed_request,
    seed_student,
)
from tests.versioned_test_support import isolated_versioned_app_env

URL = "/admin/requisicoes/email/desmarcar"


# --- owner -------------------------------------------------------------------

@pytest.fixture
def conn():
    connection = new_v7_connection()
    try:
        yield connection
    finally:
        connection.close()


ACTIVITIES = ("Congresso", "Monitoria", "Curso de extensão", "Visita técnica")


def _decided(conn, *, email="mariana.costa@example.test", status="Deferida"):
    count = conn.execute("SELECT COUNT(*) FROM alunos").fetchone()[0]
    versao = seed_activity(conn, nome=ACTIVITIES[count])
    aluno = seed_student(conn, nome="Mariana Costa Ribeiro", matricula=f"2026{count:04d}", email=email)
    req = seed_request(conn, aluno_id=aluno, versao_id=versao)
    event = decide(conn, req, status=status)
    conn.commit()
    return req, event


def _snapshot(conn, req):
    request_row = dict(conn.execute("SELECT * FROM requisicoes WHERE id=?", (req,)).fetchone())
    events = [dict(row) for row in conn.execute(
        "SELECT * FROM requisicao_email_eventos WHERE requisicao_id=? ORDER BY id", (req,))]
    envios = [dict(row) for row in conn.execute("SELECT * FROM email_envios ORDER BY id")]
    return request_row, events, envios


def test_pending_event_ids_names_each_requests_current_generation(conn):
    first, first_event = _decided(conn)
    second, second_event = _decided(conn, email="rafael.souza@example.test")
    assert pending_event_ids(conn) == {first: first_event, second: second_event}
    assert pending_event_ids(conn, [second]) == {second: second_event}
    assert pending_event_ids(conn, []) == {}
    assert pending_request_ids(conn) == {first, second}


def test_dismissal_closes_only_that_generation_and_writes_nothing_else(conn):
    req, event = _decided(conn)
    other, other_event = _decided(conn, email="rafael.souza@example.test")
    request_before, _events, envios_before = _snapshot(conn, req)

    assert dismiss_pending_events(conn, {req: event}) == 1

    request_after, events_after, envios_after = _snapshot(conn, req)
    assert request_after == request_before          # decision, status, hours, dates unchanged
    assert envios_after == envios_before == []      # no delivery fabricated
    [row] = events_after                            # the generation is kept, not deleted
    assert (row["id"], row["estado"], row["enviado_em"]) == (event, "superseded", None)
    assert row["superseded_em"]
    assert pending_event_ids(conn) == {other: other_event}


def test_a_failed_attempt_keeps_its_record_and_link(conn):
    req, event = _decided(conn)
    envio = conn.execute(
        "INSERT INTO email_envios(aluno_id,destinatario,assunto,corpo,status,tentativas,"
        "ultimo_erro,idempotency_key) SELECT aluno_id,'mariana.costa@example.test','Resultado',"
        "'Corpo','failed',1,'Falha simulada.','k-failed' FROM requisicoes WHERE id=? RETURNING id",
        (req,),
    ).fetchone()[0]
    attach_events_to_send(conn, event_ids=[event], email_envio_id=envio)
    conn.commit()
    assert failed_request_ids(conn, [req]) == {req}
    _request, _events, envios_before = _snapshot(conn, req)

    dismiss_pending_events(conn, {req: event})

    _request, [row], envios_after = _snapshot(conn, req)
    assert failed_request_ids(conn, [req]) == set() and pending_request_ids(conn) == set()
    assert envios_after == envios_before            # the failed attempt stays failed
    assert row["email_envio_id"] == envio           # and stays attributed to this decision


@pytest.mark.parametrize("change", ["new_decision", "sent", "reopened"])
def test_a_generation_that_moved_is_refused_and_nothing_changes(conn, change):
    req, event = _decided(conn)
    if change == "new_decision":
        decide(conn, req, status="Indeferida", observacao="Comprovante ilegível.")
    elif change == "sent":
        conn.execute("UPDATE requisicao_email_eventos SET estado='sent' WHERE id=?", (event,))
    else:
        reopen(conn, req)
    conn.commit()
    before = _snapshot(conn, req)

    with pytest.raises(EmailFlagDismissalStale) as refused:
        dismiss_pending_events(conn, {req: event})

    assert refused.value.requisicao_ids == [req]
    assert _snapshot(conn, req) == before


def test_a_generation_of_another_request_is_refused(conn):
    req, event = _decided(conn)
    other, other_event = _decided(conn, email="rafael.souza@example.test")
    with pytest.raises(EmailFlagDismissalStale) as refused:
        dismiss_pending_events(conn, {req: other_event})
    assert refused.value.requisicao_ids == [req]
    assert pending_event_ids(conn) == {req: event, other: other_event}


def test_a_partly_stale_batch_changes_nothing(conn):
    fresh, fresh_event = _decided(conn)
    moved, moved_event = _decided(conn, email="rafael.souza@example.test")
    newer = decide(conn, moved, status="Deferida Parcialmente", horas_deferidas=4, observacao="Parcial.")
    conn.commit()

    with pytest.raises(EmailFlagDismissalStale) as refused:
        dismiss_pending_events(conn, {fresh: fresh_event, moved: moved_event})

    assert refused.value.requisicao_ids == [moved]
    assert pending_event_ids(conn) == {fresh: fresh_event, moved: newer}


def test_a_batch_is_dismissed_together(conn):
    first, first_event = _decided(conn)
    second, second_event = _decided(conn, email="rafael.souza@example.test")
    assert dismiss_pending_events(conn, {first: first_event, second: second_event}) == 2
    assert pending_event_ids(conn) == {}


def test_a_later_decision_raises_its_own_flag_and_can_be_sent(conn):
    req, event = _decided(conn)
    dismiss_pending_events(conn, {req: event})
    reopen(conn, req)
    newer = decide(conn, req, status="Indeferida", observacao="Evento fora do período do curso.")
    conn.commit()

    assert newer != event and pending_event_ids(conn) == {req: newer}
    template = install_email_preset(conn)
    [entry] = build_plan(conn, [req], template)
    assert entry["event_ids"] == [newer] and not entry["blocked"]


# --- route -------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(dispatch_module, "send_text_email",
                        lambda conn_, message: sent.append(message) or {"http_status": 202})
    with isolated_versioned_app_env(tmp_path, "email-flag-dismissal.db") as environment:
        login_admin(environment["client"])
        environment["sent"] = sent
        yield environment


def _decided_request(client, name):
    _response, row = create_admin_request(client, name=name)
    assert client.post(f"/admin/processar_requisicao/{row['id']}",
                       data={"status": "Deferida"}).status_code == 302
    with main.app.app_context():
        conn = main.get_db_connection()
        return row["id"], pending_event_ids(conn, [row["id"]])[row["id"]]


def _pending(req_ids):
    with main.app.app_context():
        return pending_event_ids(main.get_db_connection(), req_ids)


def _row_attrs(page, req_id):
    match = re.search(r'<div[^>]*data-req-id="%d"[^>]*>' % req_id, page)
    assert match, req_id
    return match.group(0)


def test_the_list_carries_the_generation_and_offers_the_item(env):
    client = env["client"]
    req, event = _decided_request(client, "Semana acadêmica de saúde coletiva")
    page = client.get("/admin/requisicoes").get_data(as_text=True)
    row = _row_attrs(page, req)
    assert 'data-email-pending="1"' in row and f'data-email-event-id="{event}"' in row
    # Born hidden: the script offers it only for a fully flagged selection.
    assert 'id="req-action-email-dismiss" disabled hidden' in page and "Desmarcar sinalização de e-mail" in page


def test_dismissal_clears_the_flag_persistently_and_sends_nothing(env):
    client = env["client"]
    req, event = _decided_request(client, "Congresso brasileiro de enfermagem")
    kept, kept_event = _decided_request(client, "Curso de primeiros socorros")

    response = client.post(URL, json={"sinalizacoes": [{"requisicao_id": req, "evento_id": event}]})

    assert response.status_code == 200 and response.get_json() == {"ok": True, "desmarcadas": 1}
    assert env["sent"] == []
    page = client.get("/admin/requisicoes").get_data(as_text=True)
    assert "Sinalização de e-mail removida. Nenhum e-mail foi enviado." in page   # flash, once
    assert 'data-email-pending="0"' in _row_attrs(page, req)
    assert 'data-email-pending="1"' in _row_attrs(page, kept)
    again = client.get("/admin/requisicoes").get_data(as_text=True)
    assert "Sinalização de e-mail removida" not in again
    assert 'data-email-pending="0"' in _row_attrs(again, req)
    assert _pending([req, kept]) == {kept: kept_event}
    with main.app.app_context():
        status = main.get_db_connection().execute(
            "SELECT status FROM requisicoes WHERE id=?", (req,)).fetchone()[0]
    assert status == "Deferida"
    # Enviar e-mail no longer accepts the request: it has nothing pending.
    preview = client.post("/admin/requisicoes/email/preview", json={"requisicao_ids": [req]})
    assert preview.status_code in (400, 409)


def test_a_stale_dismissal_is_409_and_keeps_the_newer_flag(env):
    client = env["client"]
    req, event = _decided_request(client, "Monitoria de anatomia humana")
    assert client.post(f"/admin/processar_requisicao/{req}", data={"status": "Pendente"}).status_code == 302
    assert client.post(f"/admin/processar_requisicao/{req}", data={"status": "Deferida"}).status_code == 302
    newer = _pending([req])[req]

    response = client.post(URL, json={"sinalizacoes": [{"requisicao_id": req, "evento_id": event}]})

    assert response.status_code == 409
    assert response.get_json() == {"ok": False, "motivo": "desatualizada", "desatualizadas": [req]}
    assert _pending([req]) == {req: newer}


@pytest.mark.parametrize("body", [
    None,
    {},
    {"sinalizacoes": []},
    {"sinalizacoes": {"1": 1}},
    {"sinalizacoes": [1]},
    {"sinalizacoes": [{"requisicao_id": 1}]},
    {"sinalizacoes": [{"requisicao_id": "1", "evento_id": 1}]},
    {"sinalizacoes": [{"requisicao_id": True, "evento_id": 1}]},
    {"sinalizacoes": [{"requisicao_id": -1, "evento_id": 1}]},
    {"sinalizacoes": [{"requisicao_id": 1, "evento_id": 0}]},
    {"sinalizacoes": [{"requisicao_id": 2**63, "evento_id": 1}]},
    {"sinalizacoes": [{"requisicao_id": 1, "evento_id": 1}, {"requisicao_id": 1, "evento_id": 2}]},
    {"sinalizacoes": [{"requisicao_id": 1, "evento_id": 1}, {"requisicao_id": 2, "evento_id": 1}]},
    {"sinalizacoes": [{"requisicao_id": n, "evento_id": n} for n in range(1, 502)]},
])
def test_an_ambiguous_selection_is_refused_whole(env, body):
    req, event = _decided_request(env["client"], "Jornada de iniciação científica")
    response = env["client"].post(URL, json=body) if body is not None else env["client"].post(URL, data="x")
    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "motivo": "selecao_invalida"}
    assert _pending([req]) == {req: event}


def test_anonymous_and_view_only_administrators_are_refused(env):
    client = env["client"]
    req, event = _decided_request(client, "Palestra sobre ética profissional")
    body = {"sinalizacoes": [{"requisicao_id": req, "evento_id": event}]}
    with main.app.app_context():
        conn = main.get_db_connection()
        consultor = int(create_usuario_with_access_level(
            conn, "Consultor da coordenação", "consultor@example.test", "test-hash", "admin", "consultivo",
            credential_state="personal").lastrowid)
        conn.commit()
        auth_version = get_usuario_auth_version(conn, consultor)

    anonymous = main.app.test_client()
    assert anonymous.post(URL, json=body).status_code in (302, 401, 403)
    with client.session_transaction() as session:
        session.update(user_id=consultor, user_type="admin", user_name="Consultor", auth_version=auth_version)
    # The page's fetch is refused with 403; any other POST is sent back to the dashboard.
    denied = client.post(URL, json=body, headers={"X-Requested-With": "XMLHttpRequest"})
    assert denied.status_code == 403 and denied.get_json()["required_scope"] == "edit"
    assert client.post(URL, json=body).status_code == 302
    assert _pending([req]) == {req: event}
    # The list still renders for this profile, and its script never offers the item.
    page = client.get("/admin/requisicoes").get_data(as_text=True)
    assert "const canRequisicoesEdit = false;" in page


def test_the_route_requires_the_csrf_token(env, monkeypatch):
    client = env["client"]
    req, event = _decided_request(client, "Oficina de escrita acadêmica")
    monkeypatch.setitem(main.app.config, "WTF_CSRF_ENABLED", True)
    monkeypatch.setitem(main.app.config, "WTF_CSRF_CHECK_DEFAULT", True)
    body = {"sinalizacoes": [{"requisicao_id": req, "evento_id": event}]}
    for headers in ({}, {"X-CSRFToken": "forged"}):
        assert client.post(URL, json=body, headers=headers).status_code == 400
    assert _pending([req]) == {req: event}
    page = client.get("/admin/requisicoes").get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page) or re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"', page)
    response = client.post(URL, json=body, headers={"X-CSRFToken": token.group(1)})
    assert response.status_code == 200 and _pending([req]) == {}
