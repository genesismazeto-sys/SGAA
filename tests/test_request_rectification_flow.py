"""Return for correction vs. definitive rejection, and the student's rectification.

Indeferir offers two outcomes through one dialog (Requisições modal and the
processing page): Devolvida sends the request back to the student, Indeferida
is final. Both require a justification, enforced by the server. A Devolvida
request inside the configured return deadline (Configurações → Prazo de
adequação; ``app.requisition_policy``) is listed under Para Retificar, opens
in the editable form and is resubmitted for analysis
(``app.student_request_edit``). Indeferida and an expired return are
read-only on every route. The dashboard, the edit permission and the automatic
expiry read the same deadline.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest

import main
from app import requisition_policy
from app.db import write_transaction
from app.requisitions import auto_indefer_devolvidas
from app.settings import save_return_response_settings
from app.student_request_edit import (
    StudentEditConflict,
    StudentRequestEdit,
    save_student_request_edit,
)
from tests.storage_s3a_support import (
    INTENT_IDS_FIELD,
    ISSUE_URL,
    PDF,
    PNG,
    SUBMISSION_FIELD,
    UPLOAD_SLOTS,
    declaration,
    hidden_value,
)
from tests.test_storage_s3a_request_documents import (
    _active_version,
    _as_admin,
    _as_student,
    _attachments,
    _db,
    _no_file_request,
    _setup,
    _student,
    _submission,
    _upload,
)
from tests.versioned_test_support import isolated_versioned_app_env

ROOT = Path(__file__).resolve().parents[1]
REASON = "Falta o certificado assinado."
JUSTIFICATION_REQUIRED = "Informe a justificativa para indeferir ou devolver a requisição."
EDIT_CLOSED = (
    "Esta requisição não pode ser editada: a edição só é permitida enquanto "
    "ela está pendente ou devolvida para retificação, dentro do prazo."
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "rectification.db") as base:
        store, clock, calls = _setup(tmp_path, monkeypatch)
        with main.app.app_context():
            conn = main.get_db_connection()
            student = dict(_student(conn))
            version_id = _active_version(conn, student)
            admin = dict(conn.execute(
                "SELECT id,nivel_acesso FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
            ).fetchone())
        yield {**base, "store": store, "clock": clock, "google_calls": calls,
               "student": student, "version_id": version_id, "admin": admin}


def _row(request_id):
    with main.app.app_context():
        return dict(_db().execute("SELECT * FROM requisicoes WHERE id=?", (request_id,)).fetchone())


def _events(request_id):
    with main.app.app_context():
        return [dict(r) for r in _db().execute(
            "SELECT status_decisao, estado FROM requisicao_email_eventos WHERE requisicao_id=? ORDER BY id",
            (request_id,),
        )]


def _process(env, request_id, **fields):
    _as_admin(env)
    return env["client"].post(f"/admin/processar_requisicao/{request_id}", data=fields)


def _flashes(env):
    """The flashes queued since the last call (consumed, so each check is fresh)."""
    with env["client"].session_transaction() as sess:
        return list(sess.pop("_flashes", []))


def _set_days(days, *, auto=False):
    with main.app.app_context():
        conn = _db()
        save_return_response_settings(
            conn, {"return_response_days": str(days), "auto_indefer_devolvida": "1" if auto else "0"}
        )
        conn.commit()


def _returned(request_id, *, age, status="Devolvida"):
    """Put the request in ``status``, processed ``age`` ago, with REASON stored."""
    stamp = (datetime.datetime.now() - age).strftime("%Y-%m-%d %H:%M:%S")
    with main.app.app_context():
        conn = _db()
        conn.execute(
            "UPDATE requisicoes SET status=?, data_processamento=?, observacao=? WHERE id=?",
            (status, stamp, REASON, request_id),
        )
        conn.commit()
    return stamp


def _dashboard(env):
    _as_student(env)
    response = env["client"].get("/aluno/dashboard")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _edit_link(request_id):
    return f'href="/aluno/requisicoes/{request_id}?edit=1"'


# ===========================================================================
# 1. the administrator chooses: correction or definitive rejection
# ===========================================================================


def test_sending_for_correction_returns_the_request_without_a_final_decision(env):
    request_id = _no_file_request(env, "R1 correction")
    response = _process(env, request_id, status="Devolvida", observacao=REASON)
    assert response.status_code == 302 and response.headers["Location"].endswith("/admin/requisicoes")
    row = _row(request_id)
    assert (row["status"], row["observacao"], row["admin_id"]) == ("Devolvida", REASON, env["admin"]["id"])
    assert row["data_processamento"] and row["aluno_update_notified_at"]
    assert _events(request_id) == []  # a return is never recorded as a final rejection


def test_definitive_rejection_is_the_final_decision(env):
    request_id = _no_file_request(env, "R1 definitive")
    assert _process(env, request_id, status="Indeferida", observacao=REASON).status_code == 302
    assert _row(request_id)["status"] == "Indeferida"
    assert _events(request_id) == [{"status_decisao": "Indeferida", "estado": "pending"}]


@pytest.mark.parametrize("status", ["Indeferida", "Devolvida"])
@pytest.mark.parametrize("observacao", [None, "", "   "])
def test_both_outcomes_require_a_justification(env, status, observacao):
    request_id = _no_file_request(env, "R1 sem motivo")
    before = _row(request_id)
    fields = {"status": status}
    if observacao is not None:
        fields["observacao"] = observacao
    response = _process(env, request_id, **fields)
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/admin/processar_requisicao/{request_id}")
    assert _row(request_id) == before
    assert _events(request_id) == []
    assert ("error", JUSTIFICATION_REQUIRED) in _flashes(env)


def test_returning_a_decided_request_withdraws_its_pending_rejection_email(env):
    request_id = _no_file_request(env, "R1 decided then returned")
    _process(env, request_id, status="Indeferida", observacao="Primeira análise.")
    _process(env, request_id, status="Devolvida", observacao=REASON)
    assert _row(request_id)["status"] == "Devolvida"
    assert _events(request_id) == [{"status_decisao": "Indeferida", "estado": "superseded"}]


def test_modal_and_processing_page_ask_through_the_same_dialog(env):
    request_id = _no_file_request(env, "R1 dialog")
    _set_days(5)
    _as_admin(env)
    for path in ("/admin/requisicoes", f"/admin/processar_requisicao/{request_id}"):
        html = env["client"].get(path).get_data(as_text=True)
        assert html.count('id="rejection-decision-dialog"') == 1, path
        assert 'class="modal-overlay rejection-decision" hidden' in html, path
        assert 'class="modal-card" role="dialog" aria-modal="true"' in html, path
        assert "css/components/modal.css" in html and "js/rejection-decision.js" in html, path
        for choice, label, family in (
            ("Devolvida", "Enviar para retificação", "btn-parcial"),
            ("Indeferida", "Indeferir definitivamente", "btn-indeferir"),
        ):
            assert re.search(
                rf'class="btn btn-action-ghost {family}" data-rejection-choice="{choice}">.*?{label}', html
            ), (path, choice)
        assert 'data-rejection-choice="">Cancelar</button>' in html, path
        assert "em até 5 dias" in html, path  # the configured deadline, not a constant
    modal = (ROOT / "templates" / "admin_requisicoes.html").read_text(encoding="utf-8")
    assert "if (pendingAction === 'indeferir'){" in modal
    assert "const outcome = await window.chooseRejectionOutcome?.();" in modal
    assert "if (outcome !== 'Devolvida' && outcome !== 'Indeferida') return;" in modal
    page = (ROOT / "templates" / "admin_processar_requisicao.html").read_text(encoding="utf-8")
    assert "if (!statusInput || statusInput.value !== 'Indeferida') return;" in page
    assert "if (outcome !== 'Devolvida' && outcome !== 'Indeferida') return;" in page
    script = (ROOT / "static" / "js" / "rejection-decision.js").read_text(encoding="utf-8")
    assert "resolve(choice || null);" in script  # Cancelar / Escape / backdrop send nothing


# ===========================================================================
# 2. the student rectifies and resubmits, documents included
# ===========================================================================


def test_student_rectifies_and_resubmits_a_returned_request(env):
    _as_student(env)
    submission = _submission(env)
    original = _upload(env, submission, UPLOAD_SLOTS[0], PDF, "original.pdf")
    response = env["client"].post("/aluno/nova-requisicao", data={
        "atividade_versao_id": str(env["version_id"]), "nome_evento": "R2 original",
        "data_evento": "2026-09-06", "horas_solicitadas": "2",
        SUBMISSION_FIELD: submission, INTENT_IDS_FIELD: [original],
    })
    assert response.status_code == 302
    with main.app.app_context():
        request_id = _db().execute(
            "SELECT id FROM requisicoes WHERE nome_evento='R2 original'"
        ).fetchone()[0]
    [old_doc] = _attachments(request_id)
    before = _row(request_id)
    assert _process(env, request_id, status="Devolvida", observacao=REASON).status_code == 302

    assert _edit_link(request_id) in _dashboard(env)
    form = env["client"].get(f"/aluno/requisicoes/{request_id}?edit=1")
    assert form.status_code == 200
    page = form.get_data(as_text=True)
    assert "Retificar Requisição" in page and REASON in page and "Reenviar para análise" in page
    for field in (r'name="nome_evento"[^>]*', r'name="horas_solicitadas"[^>]*', r'name="data_evento"[^>]*',
                  r'<textarea[^>]*name="observacao"[^>]*'):
        tag = re.search(field, page)
        assert tag and "readonly" not in tag.group(0), field
    assert "data-direct-upload-input" in page  # the documents can be changed too

    submission = hidden_value(form.data, SUBMISSION_FIELD)
    new_doc = _upload(env, submission, UPLOAD_SLOTS[0], PNG, "certificado.png", "image/png",
                      requisicao_id=request_id)
    response = env["client"].post(f"/aluno/requisicoes/{request_id}", data={
        "atividade_versao_id": str(env["version_id"]),
        "nome_evento": "R2 corrigido", "data_evento": "2026-09-10", "horas_solicitadas": "3",
        "observacao": "Segue o certificado assinado.",
        SUBMISSION_FIELD: submission, INTENT_IDS_FIELD: [new_doc],
        "remover_comprovantes": [str(old_doc["id"])],
    })
    assert response.status_code == 302
    assert ("success", "Requisição reenviada para análise.") in _flashes(env)

    row = _row(request_id)
    assert (row["status"], row["data_processamento"], row["admin_id"], row["horas_deferidas"]) == (
        "Pendente", None, None, None)
    assert (row["aluno_update_notified_at"], row["aluno_update_seen_at"]) == (None, None)
    assert (row["nome_evento"], row["data_evento"], row["horas_solicitadas"]) == ("R2 corrigido", "2026-09-10", 3.0)
    # The administrator's reason survives above the student's reply.
    assert row["observacao"] == f"[Motivo da devolução: {REASON}]\nSegue o certificado assinado."
    # The immutable activity-version snapshot and the request's origin are untouched.
    for column in ("atividade_versao_id", "regra_snapshot_json", "data_solicitacao", "aluno_id"):
        assert row[column] == before[column], column
    docs = {doc["id"]: doc for doc in _attachments(request_id)}
    assert docs[old_doc["id"]]["storage_status"] == "trashed"
    [active] = [doc for doc in docs.values() if doc["storage_status"] == "active"]
    assert (active["provider"], active["original_filename"]) == ("supabase", "certificado.png")
    assert env["google_calls"] == []
    assert _events(request_id) == []

    # Out of Para Retificar, and back in administrative review.
    assert _edit_link(request_id) not in _dashboard(env)
    assert _process(env, request_id, status="Encerrada").status_code == 302
    assert _row(request_id)["status"] == "Encerrada"


def test_an_empty_reply_still_keeps_the_reason(env):
    request_id = _no_file_request(env, "R2 sem resposta")
    _returned(request_id, age=datetime.timedelta(hours=1))
    _as_student(env)
    response = env["client"].post(f"/aluno/requisicoes/{request_id}", data={"observacao": ""})
    assert response.status_code == 302
    row = _row(request_id)
    assert (row["status"], row["observacao"]) == ("Pendente", f"[Motivo da devolução: {REASON}]")


@pytest.mark.parametrize("read_state", ["Devolvida", "Pendente"])
def test_a_decision_landing_after_the_check_refuses_the_edit(env, read_state):
    request_id = _no_file_request(env, "R2 race")
    if read_state == "Devolvida":
        _returned(request_id, age=datetime.timedelta(hours=1))
    stale = _row(request_id)  # what the student's request read before the admin decided
    _process(env, request_id, status="Indeferida", observacao="Decidido.")
    with main.app.app_context():
        conn = _db()
        with pytest.raises(StudentEditConflict):
            with write_transaction(conn):
                save_student_request_edit(
                    conn, request_id=request_id, aluno_id=stale["aluno_id"], status=stale["status"],
                    data_processamento=stale["data_processamento"], stored_observacao=stale["observacao"],
                    edit=StudentRequestEdit(nome_evento="tarde demais"),
                )
    row = _row(request_id)
    assert (row["status"], row["nome_evento"], row["observacao"]) == ("Indeferida", "R2 race", "Decidido.")


# ===========================================================================
# 3. a definitive rejection and an expired return stay protected
# ===========================================================================


@pytest.mark.parametrize("state", ["indeferida", "devolvida_expirada"])
def test_rejected_and_expired_requests_are_read_only_everywhere(env, state):
    _set_days(7)
    request_id = _no_file_request(env, f"R3 {state}")
    if state == "indeferida":
        _returned(request_id, age=datetime.timedelta(hours=1), status="Indeferida")
    else:
        _returned(request_id, age=datetime.timedelta(days=7, minutes=1))
    before = _row(request_id)

    html = _dashboard(env)
    assert _edit_link(request_id) not in html
    listing = env["client"].get("/aluno/requisicoes").get_data(as_text=True)
    assert re.search(rf'data-req-id="{request_id}"[^>]*data-can-edit="0"[^>]*data-can-delete="0"', listing)
    detail = env["client"].get(f"/aluno/requisicoes/{request_id}").get_data(as_text=True)
    assert "?edit=1" not in detail

    response = env["client"].get(f"/aluno/requisicoes/{request_id}?edit=1")
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/aluno/requisicoes/{request_id}?view=1")
    assert ("error", EDIT_CLOSED) in _flashes(env)

    env["client"].post(f"/aluno/requisicoes/{request_id}",
                       data={"nome_evento": "alterado", "horas_solicitadas": "99", "observacao": "x"})
    assert ("error", EDIT_CLOSED) in _flashes(env)
    env["client"].post(f"/aluno/requisicoes/{request_id}?delete=1")
    submission = _submission(env, f"/aluno/requisicoes/{request_id}?view=1")
    issued = env["client"].post(ISSUE_URL, json={
        "purpose": "comprovante", "submission_id": submission, "upload_slot_id": UPLOAD_SLOTS[0],
        "requisicao_id": request_id, **declaration(PDF, "x.pdf", "application/pdf"),
    })
    assert issued.status_code == 403
    assert _row(request_id) == before
    assert _attachments(request_id) == []


# ===========================================================================
# 4. one deadline: dashboard, edit permission and automatic expiry agree
# ===========================================================================


def test_dashboard_edit_permission_and_expiry_share_the_configured_deadline(env):
    _set_days(3, auto=True)
    inside = _no_file_request(env, "R4 dentro")
    outside = _no_file_request(env, "R4 fora")
    rejected = _no_file_request(env, "R4 indeferida")
    processed = _returned(inside, age=datetime.timedelta(days=1))
    # Past the deadline by more than any UTC offset: the expiry compares on the
    # database clock (UTC), the stored processing time is the app's clock.
    _returned(outside, age=datetime.timedelta(days=3, hours=15))
    _returned(rejected, age=datetime.timedelta(hours=1), status="Indeferida")

    html = _dashboard(env)
    assert _edit_link(inside) in html
    assert _edit_link(outside) not in html and _edit_link(rejected) not in html
    expires = datetime.datetime.strptime(processed, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(days=3)
    assert f"Expira em {expires:%d/%m/%Y}" in html
    assert ">2/3<" in html  # whole days left over the configured total, never a constant
    kpi = re.search(r'<span class="value">(\d+)</span>\s*<span class="label"><i class="lucide" '
                    r'data-lucide="edit"></i>Corrigíveis</span>', html)
    assert kpi and kpi.group(1) == "1"

    # The backend accepts exactly what the dashboard offers.
    assert env["client"].get(f"/aluno/requisicoes/{inside}?edit=1").status_code == 200
    assert env["client"].get(f"/aluno/requisicoes/{outside}?edit=1").status_code == 302

    # The automatic expiry reads the same deadline and expires exactly the rest.
    with main.app.app_context():
        assert auto_indefer_devolvidas(_db()) == 1
    assert (_row(inside)["status"], _row(outside)["status"]) == ("Devolvida", "Indeferida")


def test_changing_the_configured_deadline_moves_every_check(env):
    request_id = _no_file_request(env, "R4 prazo")
    _returned(request_id, age=datetime.timedelta(days=10))
    _set_days(7)
    assert _edit_link(request_id) not in _dashboard(env)
    assert env["client"].get(f"/aluno/requisicoes/{request_id}?edit=1").status_code == 302
    _set_days(14)
    html = _dashboard(env)
    assert _edit_link(request_id) in html and ">4/14<" in html
    assert env["client"].get(f"/aluno/requisicoes/{request_id}?edit=1").status_code == 200
    _set_days(0)  # 0: no deadline
    html = _dashboard(env)
    assert _edit_link(request_id) in html and "Sem prazo" in html
    assert env["client"].get(f"/aluno/requisicoes/{request_id}?edit=1").status_code == 200


class _Frozen(datetime.datetime):
    current = datetime.datetime(2026, 7, 24, 12, 0, 0)

    @classmethod
    def now(cls, tz=None):
        assert tz is None
        return cls.current


def test_return_window_boundary_and_remaining_days(monkeypatch):
    monkeypatch.setattr(requisition_policy.datetime, "datetime", _Frozen)
    window = requisition_policy.open_return_window
    last_second = window("Devolvida", "2026-07-21 12:00:01", 3)
    assert (last_second.remaining_days, last_second.deadline) == (1, datetime.datetime(2026, 7, 24, 12, 0, 1))
    assert window("Devolvida", "2026-07-21 12:00:00", 3) is None  # now == deadline: closed, as the expiry
    assert window("Devolvida", "2026-07-24 12:00:00", 3).remaining_days == 3
    assert window("Devolvida", "2026-07-23 00:00:00", 3).remaining_days == 2  # 1.5 days left rounds up
    assert window("Devolvida", "2020-01-01", 0) == requisition_policy.ReturnWindow(0, None, None)
    for status in ("Indeferida", "Deferida", "Deferida Parcialmente", "Encerrada", "Pendente", None):
        assert window(status, "2026-07-24 11:00:00", 3) is None, status
    assert window("Devolvida", None, 3) is None
    assert window("Devolvida", "malformed", 0) is None


# ===========================================================================
# 5. visual consistency: the shared progress component, the shared dialog
# ===========================================================================


def test_the_deadline_meter_is_the_shared_progress_component(env):
    source = (ROOT / "templates" / "aluno_dashboard.html").read_text(encoding="utf-8")
    for legacy in ("days-bar", "#2ecc71", "#27ae60", "#f1c40f", "#e74c3c", "linear-gradient",
                   "border-radius:5px", "system-ui"):
        assert legacy not in source, legacy
    css = (ROOT / "static" / "css" / "modern-style.css").read_text(encoding="utf-8")
    assert ".progress.is-deadline,\n.progress.is-deadline > .progress-bar{ border-radius:var(--radius); }" in css
    for tone in ("positive", "caution", "negative"):
        assert (f".progress.is-deadline.status-{tone} > .progress-bar"
                f"{{ background:var(--status-{tone}-dot); }}") in css, tone
    assert ".rejection-decision .modal-card{" in css

    # The original thresholds: more than 10 days positive, more than 5 caution.
    _set_days(30)
    for remaining, (name, age) in {
        11: ("R5 onze", datetime.timedelta(days=19, hours=1)),
        10: ("R5 dez", datetime.timedelta(days=20, hours=1)),
        6: ("R5 seis", datetime.timedelta(days=24, hours=1)),
        5: ("R5 cinco", datetime.timedelta(days=25, hours=1)),
    }.items():
        _returned(_no_file_request(env, name), age=age)
    html = _dashboard(env)
    meters = re.findall(r'<div class="progress is-deadline status-(\w+)" data-pct="(\d+)"', html)
    assert sorted(meters, key=lambda m: int(m[1])) == [
        ("negative", "16"), ("caution", "20"), ("caution", "33"), ("positive", "36"),
    ]
    for remaining in (11, 10, 6, 5):
        assert f">{remaining}/30<" in html
