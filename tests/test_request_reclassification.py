"""Correcting the activity of an editable request (schema v17).

A student who picked the wrong activity corrects it on the edit form while the
request is Pendente, or Devolvida inside its return deadline; an administrator
corrects a Pendente one from the Requisições modal. The request keeps its id,
documents and history; it gets a fresh snapshot from the versioning service
and both columns change together (``app.request_reclassification``). Decided
and expired requests stay frozen, in the application and in the database
trigger (``app.prod1_request_reclassification_ddl``).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re

import pytest

import main
from app.db import write_transaction
from app.request_reclassification import (
    HISTORY_KEY,
    ReclassificationConflict,
    apply_reclassification,
    prepare_reclassification,
)
from app.settings import save_return_response_settings
from app.versioning.snapshots import (
    SnapshotProcessingAuthority,
    read_requisicao_snapshot_for_processing,
)
from tests.storage_s3a_support import INTENT_IDS_FIELD, PDF, SUBMISSION_FIELD, UPLOAD_SLOTS, hidden_value
from tests.test_storage_s3a_request_documents import (
    _as_admin,
    _as_student,
    _attachments,
    _db,
    _setup,
    _student,
    _submission,
    _upload,
)
from tests.versioned_test_support import isolated_versioned_app_env

# The seeded student's effective Matrix offers AAC 29..54 and AEU 55..59;
# version 1 is active but outside it.
A, B, AEU, OUTSIDE = 29, 30, 55, 1
NAMES = {A: "Visitas técnicas ou culturais", B: "Curso de curta duração em aviação",
         AEU: "Participação em projetos de extensão"}
AAC_TYPE, AEU_TYPE = "Acadêmica Complementar", "Extensão Universitária"
REASON = "Atividade classificada no grupo errado."
EDIT_CLOSED = (
    "Esta requisição não pode ser editada: a edição só é permitida enquanto "
    "ela está pendente ou devolvida para retificação, dentro do prazo."
)
NOT_IN_MATRIX = "A atividade selecionada não está disponível para a matriz da sua turma."
CHANGED_MEANWHILE = (
    "A atividade desta requisição foi alterada enquanto o formulário estava aberto. "
    "Confira a atividade registrada e salve novamente."
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "reclassification.db") as base:
        store, clock, calls = _setup(tmp_path, monkeypatch)
        with main.app.app_context():
            conn = main.get_db_connection()
            student = dict(_student(conn))
            admin = dict(conn.execute(
                "SELECT id,nivel_acesso FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
            ).fetchone())
        yield {**base, "store": store, "clock": clock, "google_calls": calls,
               "student": student, "admin": admin}


def _row(request_id):
    with main.app.app_context():
        return dict(_db().execute("SELECT * FROM requisicoes WHERE id=?", (request_id,)).fetchone())


def _versions_digest():
    with main.app.app_context():
        rows = _db().execute("SELECT * FROM atividade_versao ORDER BY id").fetchall()
        return hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()


def _flashes(env):
    with env["client"].session_transaction() as sess:
        return list(sess.pop("_flashes", []))


def _create(env, name, version=A, *, document=True):
    """A Pendente request created through the student's route, with one comprovante."""
    _as_student(env)
    fields = {"atividade_versao_id": str(version), "nome_evento": name,
              "data_evento": "2026-09-06", "horas_solicitadas": "2"}
    if document:
        submission = _submission(env)
        fields[SUBMISSION_FIELD] = submission
        fields[INTENT_IDS_FIELD] = [_upload(env, submission, UPLOAD_SLOTS[0], PDF, "comprovante.pdf")]
    assert env["client"].post("/aluno/nova-requisicao", data=fields).status_code == 302
    _flashes(env)
    with main.app.app_context():
        return _db().execute("SELECT id FROM requisicoes WHERE nome_evento=?", (name,)).fetchone()[0]


def _set_state(request_id, status, *, age=datetime.timedelta(hours=1), observacao=REASON):
    stamp = (datetime.datetime.now() - age).strftime("%Y-%m-%d %H:%M:%S")
    with main.app.app_context():
        conn = _db()
        conn.execute("UPDATE requisicoes SET status=?, data_processamento=?, observacao=? WHERE id=?",
                     (status, stamp, observacao, request_id))
        conn.commit()


def _edit(env, request_id, version, *, registered="stored", tipo=None, **fields):
    """POST the student's edit form as the browser does."""
    row = _row(request_id)
    data = {"nome_evento": row["nome_evento"], "data_evento": row["data_evento"],
            "horas_solicitadas": str(row["horas_solicitadas"]), "observacao": "",
            "atividade_versao_id": str(version),
            "tipo_atividade": tipo or (AEU_TYPE if version == AEU else AAC_TYPE)}
    if registered == "stored":
        data["atividade_versao_id_registrada"] = str(row["atividade_versao_id"])
    elif registered is not None:
        data["atividade_versao_id_registrada"] = str(registered)
    data.update(fields)
    _as_student(env)
    return env["client"].post(f"/aluno/requisicoes/{request_id}", data=data)


def _authority(row):
    read = read_requisicao_snapshot_for_processing(row)
    assert read.authority is SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT, read.reason
    return read


# ===========================================================================
# 1. the student corrects the activity of an editable request
# ===========================================================================


def test_the_edit_form_offers_both_types_and_names_the_stored_classification(env):
    request_id = _create(env, "R form", document=False)
    page = env["client"].get(f"/aluno/requisicoes/{request_id}?edit=1")
    assert page.status_code == 200
    assert hidden_value(page.data, "atividade_versao_id_registrada") == str(A)
    select = page.get_data(as_text=True).split('id="atividade_versao_id_select"', 1)[1].split("</select>", 1)[0]
    for version in (A, B, AEU):
        assert f'value="{version}"' in select, version
    # Read-only views carry no classification to change.
    view = env["client"].get(f"/aluno/requisicoes/{request_id}?view=1")
    assert hidden_value(view.data, "atividade_versao_id_registrada") is None


def test_a_pending_request_moves_to_another_activity_of_the_same_matrix(env):
    request_id = _create(env, "R1 errada")
    before, docs_before, versions_before = _row(request_id), _attachments(request_id), _versions_digest()

    response = _edit(env, request_id, B, nome_evento="R1 corrigida")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/aluno/requisicoes")
    assert ("success", "Requisição atualizada.") in _flashes(env)

    row = _row(request_id)
    assert (row["id"], row["atividade_versao_id"], row["status"], row["nome_evento"]) == (
        request_id, B, "Pendente", "R1 corrigida")
    for column in ("aluno_id", "data_solicitacao", "turma_id_snapshot", "turma_codigo_snapshot"):
        assert row[column] == before[column], column
    read = _authority(row)
    assert (read.rule.atividade_versao_id, read.rule.eixo) == (B, "AAC")
    assert read.payload["nome_exibivel"] == NAMES[B]
    assert read.payload["flow_origin"] == "aluno_reclassify"
    [entry] = read.payload[HISTORY_KEY]
    assert entry["from"]["atividade_versao_id"] == A
    assert entry["from"]["nome_exibivel"] == NAMES[A]
    assert entry["from"]["flow_origin"] == "aluno_create"
    assert entry["from"]["snapshot_written_at"] == json.loads(before["regra_snapshot_json"])["snapshot_written_at"]
    assert entry["to_atividade_versao_id"] == B
    assert entry["actor"] == {"role": "aluno", "usuario_id": env["student"]["usuario_id"]}
    assert entry["request_status"] == "Pendente"
    # Same documents, same custody; no academic version row was written.
    assert _attachments(request_id) == docs_before
    assert _versions_digest() == versions_before

    # The administrator reads the corrected classification.
    _as_admin(env)
    api = env["client"].get(f"/admin/api/requisicao/{request_id}").get_json()
    assert (api["atividade_versao_id"], api["atividade_nome"], api["tipo_atividade"]) == (B, NAMES[B], AAC_TYPE)
    processing = env["client"].get(f"/admin/processar_requisicao/{request_id}")
    assert processing.status_code == 200 and NAMES[B] in processing.get_data(as_text=True)


def test_a_correction_may_cross_axes_and_each_correction_is_kept(env):
    request_id = _create(env, "R2 eixo")
    assert _edit(env, request_id, AEU).status_code == 302
    row = _row(request_id)
    read = _authority(row)
    assert (row["atividade_versao_id"], read.rule.eixo, read.payload["tipo_atividade"]) == (AEU, "AEU", AEU_TYPE)

    assert _edit(env, request_id, B).status_code == 302
    history = _authority(_row(request_id)).payload[HISTORY_KEY]
    assert [(item["from"]["atividade_versao_id"], item["to_atividade_versao_id"]) for item in history] == [
        (A, AEU), (AEU, B)]
    assert history[1]["from"]["flow_origin"] == "aluno_reclassify"


def test_an_edit_that_keeps_the_activity_keeps_the_snapshot_byte_for_byte(env):
    request_id = _create(env, "R3 mesma")
    before = _row(request_id)
    assert _edit(env, request_id, A, nome_evento="R3 renomeada").status_code == 302
    row = _row(request_id)
    assert row["nome_evento"] == "R3 renomeada"
    assert (row["atividade_versao_id"], row["regra_snapshot_json"]) == (
        before["atividade_versao_id"], before["regra_snapshot_json"])


def test_a_returned_request_is_corrected_and_resubmitted_with_the_reason_kept(env):
    _set_days(7)
    request_id = _create(env, "R4 devolvida")
    _set_state(request_id, "Devolvida")
    response = _edit(env, request_id, B, observacao="Troquei para a atividade correta.")
    assert response.status_code == 302
    assert ("success", "Requisição reenviada para análise.") in _flashes(env)
    row = _row(request_id)
    assert (row["status"], row["data_processamento"], row["atividade_versao_id"]) == ("Pendente", None, B)
    assert row["observacao"] == f"[Motivo da devolução: {REASON}]\nTroquei para a atividade correta."
    assert _authority(row).payload[HISTORY_KEY][-1]["request_status"] == "Devolvida"


# ===========================================================================
# 2. refusals: nothing is written, and a correctable one keeps the form
# ===========================================================================


@pytest.mark.parametrize("case", ["outside_matrix", "inactive", "type_contradiction"])
def test_an_unacceptable_activity_is_refused_with_the_entered_values_kept(env, case):
    request_id = _create(env, f"R5 {case}")
    target, tipo = OUTSIDE, None
    if case == "inactive":
        target = B
        with main.app.app_context():
            conn = _db()
            conn.execute("UPDATE atividade_versao SET status='inativa' WHERE id=?", (B,))
            conn.commit()
    elif case == "type_contradiction":
        target, tipo = B, AEU_TYPE
    before = _row(request_id)
    response = _edit(env, request_id, target, tipo=tipo, nome_evento="Valor digitado")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert NOT_IN_MATRIX in page
    assert "Editar Requisição" in page and 'value="Valor digitado"' in page
    assert hidden_value(response.data, "atividade_versao_id_registrada") == str(A)
    assert _row(request_id) == before


@pytest.mark.parametrize("status", ["Deferida", "Deferida Parcialmente", "Indeferida", "Encerrada"])
def test_a_decided_request_cannot_be_reclassified(env, status):
    request_id = _create(env, f"R6 {status}", document=False)
    _set_state(request_id, status)
    before = _row(request_id)
    response = _edit(env, request_id, B)
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/aluno/requisicoes/{request_id}?view=1")
    assert ("error", EDIT_CLOSED) in _flashes(env)
    assert _row(request_id) == before
    # The form is not offered either.
    assert env["client"].get(f"/aluno/requisicoes/{request_id}?edit=1").status_code == 302


def test_an_expired_return_cannot_be_reclassified(env):
    _set_days(7)
    request_id = _create(env, "R7 expirada", document=False)
    _set_state(request_id, "Devolvida", age=datetime.timedelta(days=7, minutes=1))
    before = _row(request_id)
    assert _edit(env, request_id, B).status_code == 302
    assert ("error", EDIT_CLOSED) in _flashes(env)
    assert _row(request_id) == before


def test_a_form_filled_before_another_correction_cannot_undo_it(env):
    request_id = _create(env, "R8 corrida", document=False)
    # The administrator corrects A -> B while the student's form still says A.
    _as_admin(env)
    admin = env["client"].post(f"/admin/requisicoes/{request_id}/editar", data={
        "edit_target_id": str(request_id), "atividade_versao_id": str(B),
        "atividade_versao_id_registrada": str(A), "tipo_atividade": AAC_TYPE,
        "nome_evento": "R8 corrida", "data_evento": "2026-09-06", "horas_solicitadas": "2",
    })
    assert admin.status_code == 302 and _row(request_id)["atividade_versao_id"] == B
    _flashes(env)
    after_admin = _row(request_id)

    response = _edit(env, request_id, AEU, registered=A, nome_evento="R8 aluno")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert CHANGED_MEANWHILE in page and 'value="R8 aluno"' in page
    # The form comes back on the classification now stored.
    assert hidden_value(response.data, "atividade_versao_id_registrada") == str(B)
    assert re.search(rf'<option value="{B}"[^>]*selected', page)
    assert _row(request_id) == after_admin
    # Without any registered classification a change is refused the same way.
    assert CHANGED_MEANWHILE in _edit(env, request_id, AEU, registered=None).get_data(as_text=True)
    assert _row(request_id) == after_admin


def test_a_decision_landing_after_the_check_refuses_the_correction(env):
    request_id = _create(env, "R9 decisão", document=False)
    with main.app.app_context():
        conn = _db()
        stale = dict(conn.execute("SELECT * FROM requisicoes WHERE id=?", (request_id,)).fetchone())
        prepared = prepare_reclassification(
            conn, request_row=stale, aluno_id=stale["aluno_id"], new_version_id=B, form_version_id=A,
            declared_tipo=AAC_TYPE, flow_origin="aluno_reclassify", actor_role="aluno", actor_user_id=1,
        )
        conn.rollback()
    _as_admin(env)
    assert env["client"].post(f"/admin/processar_requisicao/{request_id}", data={
        "status": "Deferida", "horas_deferidas": "2", "observacao": "ok"}).status_code == 302
    decided = _row(request_id)
    assert decided["status"] == "Deferida"
    with main.app.app_context():
        conn = _db()
        with pytest.raises(ReclassificationConflict):
            with write_transaction(conn):
                apply_reclassification(conn, prepared)
    assert _row(request_id) == decided


def test_a_correction_prepared_before_a_round_trip_never_erases_its_history(env):
    # Someone moves A -> B -> A between this read and this write: the activity
    # matches again, but the snapshot (and its history) is not the one read.
    request_id = _create(env, "R9b ida e volta", document=False)

    def prepare(row, target):
        with main.app.app_context():
            conn = _db()
            prepared = prepare_reclassification(
                conn, request_row=row, aluno_id=row["aluno_id"], new_version_id=target,
                form_version_id=row["atividade_versao_id"], declared_tipo=None,
                flow_origin="aluno_reclassify", actor_role="aluno", actor_user_id=1,
            )
            conn.rollback()
            return prepared

    def apply(prepared):
        with main.app.app_context():
            conn = _db()
            with write_transaction(conn):
                apply_reclassification(conn, prepared)

    stale = prepare(_row(request_id), AEU)
    apply(prepare(_row(request_id), B))
    apply(prepare(_row(request_id), A))
    round_trip = _row(request_id)
    assert round_trip["atividade_versao_id"] == A
    with pytest.raises(ReclassificationConflict):
        apply(stale)
    assert _row(request_id) == round_trip
    assert len(json.loads(round_trip["regra_snapshot_json"])[HISTORY_KEY]) == 2


# ===========================================================================
# 3. the administrator's pending-request edit follows the same rules
# ===========================================================================


def test_the_admin_modal_offers_the_matrix_only_for_a_pending_request(env):
    request_id = _create(env, "R10 modal", document=False)
    _as_admin(env)
    api = env["client"].get(f"/admin/api/requisicao/{request_id}").get_json()
    offer = api["reclassification"]
    assert offer["activities"][0]["id"] == A  # the historical option stays first
    ids = [item["id"] for item in offer["activities"]]
    assert {A, B, AEU} <= set(ids) and OUTSIDE not in ids and len(ids) == len(set(ids))
    assert {A, B, AEU} <= set(offer["allowed_activity_ids"])
    # The view contract is unchanged: one historical option.
    assert [item["id"] for item in api["activities"]] == [A]

    _set_state(request_id, "Deferida")
    assert env["client"].get(f"/admin/api/requisicao/{request_id}").get_json()["reclassification"] is None


def test_the_admin_corrects_a_pending_request(env):
    request_id = _create(env, "R11 admin")
    docs = _attachments(request_id)
    _as_admin(env)
    fields = {"edit_target_id": str(request_id), "atividade_versao_id_registrada": str(A),
              "nome_evento": "R11 admin", "data_evento": "2026-09-06", "horas_solicitadas": "2"}

    refused = env["client"].post(f"/admin/requisicoes/{request_id}/editar",
                                 data={**fields, "atividade_versao_id": str(OUTSIDE)})
    assert "open_edit=1" in refused.headers["Location"]
    assert ("error", "A atividade selecionada não pertence à matriz efetiva da turma do aluno.") in _flashes(env)
    assert _row(request_id)["atividade_versao_id"] == A

    response = env["client"].post(f"/admin/requisicoes/{request_id}/editar",
                                  data={**fields, "atividade_versao_id": str(AEU), "tipo_atividade": AEU_TYPE})
    assert response.status_code == 302 and response.headers["Location"].endswith("/admin/requisicoes")
    row = _row(request_id)
    read = _authority(row)
    assert (row["atividade_versao_id"], read.payload["flow_origin"]) == (AEU, "admin_reclassify")
    entry = read.payload[HISTORY_KEY][-1]
    assert entry["actor"] == {"role": "admin", "usuario_id": env["admin"]["id"]}
    assert entry["from"]["atividade_versao_id"] == A
    assert _attachments(request_id) == docs


@pytest.mark.parametrize("target", [A, B], ids=["fields_only", "with_correction"])
def test_the_admin_edit_refuses_a_request_decided_while_it_was_being_saved(env, monkeypatch, target):
    # The decision lands after the route read the request and before it writes.
    from app.views.admin import requisicoes as admin_requisicoes

    request_id = _create(env, f"R12 admin corrida {target}", document=False)
    original = admin_requisicoes.prepare_reclassification

    def decided_meanwhile(conn, **kwargs):
        prepared = original(conn, **kwargs)
        conn.execute("UPDATE requisicoes SET status='Deferida' WHERE id=?", (request_id,))
        conn.commit()
        return prepared

    monkeypatch.setattr(admin_requisicoes, "prepare_reclassification", decided_meanwhile)
    _as_admin(env)
    response = env["client"].post(f"/admin/requisicoes/{request_id}/editar", data={
        "edit_target_id": str(request_id), "atividade_versao_id": str(target),
        "atividade_versao_id_registrada": str(A), "nome_evento": "nunca gravado",
        "data_evento": "2026-09-06", "horas_solicitadas": "2",
    })
    assert response.status_code == 302 and response.headers["Location"].endswith("/admin/requisicoes")
    assert ("error", "Esta requisição foi alterada enquanto o formulário estava aberto. "
                     "Reabra a requisição e confira os dados antes de salvar.") in _flashes(env)
    row = _row(request_id)
    assert (row["status"], row["atividade_versao_id"], row["nome_evento"]) == (
        "Deferida", A, f"R12 admin corrida {target}")


ADMIN_CHANGED_MEANWHILE = CHANGED_MEANWHILE


def test_a_decision_is_refused_on_a_classification_the_administrator_did_not_see(env):
    request_id = _create(env, "R13 decisão velha", document=False)
    assert _edit(env, request_id, B).status_code == 302  # the student corrects A -> B
    corrected = _row(request_id)
    _as_admin(env)
    response = env["client"].post(f"/admin/processar_requisicao/{request_id}", data={
        "status": "Deferida", "atividade_versao_id_registrada": str(A)})
    assert response.headers["Location"].endswith(f"/admin/processar_requisicao/{request_id}")
    assert ("error", ADMIN_CHANGED_MEANWHILE) in _flashes(env)
    assert _row(request_id) == corrected
    # The page now shows B, and the decision on B goes through.
    page = env["client"].get(f"/admin/processar_requisicao/{request_id}").get_data(as_text=True)
    assert f'name="atividade_versao_id_registrada" value="{B}"' in page
    assert env["client"].post(f"/admin/processar_requisicao/{request_id}", data={
        "status": "Deferida", "atividade_versao_id_registrada": str(B)}).status_code == 302
    assert _row(request_id)["status"] == "Deferida"


def test_a_correction_committed_during_the_decision_refuses_it(env, monkeypatch):
    # Inside one POST: the limits were checked on A, then A became B.
    from app.views.admin import requisicoes as admin_requisicoes

    request_id = _create(env, "R14 decisão em voo", document=False)
    row = _row(request_id)
    original = admin_requisicoes.list_approved_request_history

    def corrected_meanwhile(conn, **kwargs):
        history = original(conn, **kwargs)
        conn.execute("UPDATE requisicoes SET atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
                     (B, _snapshot_naming(B, row["regra_snapshot_json"]), request_id))
        conn.commit()
        return history

    monkeypatch.setattr(admin_requisicoes, "list_approved_request_history", corrected_meanwhile)
    _as_admin(env)
    response = env["client"].post(f"/admin/processar_requisicao/{request_id}", data={"status": "Deferida"})
    assert response.headers["Location"].endswith(f"/admin/processar_requisicao/{request_id}")
    assert ("error", ADMIN_CHANGED_MEANWHILE) in _flashes(env)
    after = _row(request_id)
    assert (after["status"], after["atividade_versao_id"], after["data_processamento"]) == ("Pendente", B, None)


# ===========================================================================
# 4. the database itself (SQLite v17 trigger)
# ===========================================================================


def _snapshot_naming(version_id, base):
    payload = json.loads(base)
    payload["atividade_versao_id"] = version_id
    return json.dumps(payload)


@pytest.mark.parametrize("status", ["Deferida", "Deferida Parcialmente", "Indeferida", "Encerrada"])
def test_the_database_keeps_a_decided_request_frozen(env, status):
    request_id = _create(env, f"T1 {status}", document=False)
    _set_state(request_id, status)
    row = _row(request_id)
    with main.app.app_context():
        conn = _db()
        with pytest.raises(Exception, match="request snapshot authority is immutable"):
            conn.execute("UPDATE requisicoes SET atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
                         (B, _snapshot_naming(B, row["regra_snapshot_json"]), request_id))
        conn.rollback()
    assert _row(request_id) == row


@pytest.mark.parametrize("change, message", [
    ("activity_only", "must replace the activity and its snapshot together"),
    ("snapshot_only", "must replace the activity and its snapshot together"),
    ("snapshot_names_another_version", "request snapshot must name its activity version"),
    ("snapshot_names_it_as_text", "request snapshot must name its activity version"),
    ("decided_in_the_same_statement", "request snapshot authority is immutable"),
])
def test_the_database_refuses_a_partial_or_mismatched_reclassification(env, change, message):
    request_id = _create(env, f"T2 {change}", document=False)
    row = _row(request_id)
    snapshot_b = _snapshot_naming(B, row["regra_snapshot_json"])
    statement, params = {
        "activity_only": ("UPDATE requisicoes SET atividade_versao_id=? WHERE id=?", (B, request_id)),
        "snapshot_only": ("UPDATE requisicoes SET regra_snapshot_json=? WHERE id=?",
                          (_snapshot_naming(A, snapshot_b) + " ", request_id)),
        "snapshot_names_another_version": (
            "UPDATE requisicoes SET atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
            (B, _snapshot_naming(AEU, row["regra_snapshot_json"]), request_id)),
        "snapshot_names_it_as_text": (
            "UPDATE requisicoes SET atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
            (B, _snapshot_naming(str(B), row["regra_snapshot_json"]), request_id)),
        "decided_in_the_same_statement": (
            "UPDATE requisicoes SET status='Deferida', atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
            (B, snapshot_b, request_id)),
    }[change]
    with main.app.app_context():
        conn = _db()
        with pytest.raises(Exception, match=message):
            conn.execute(statement, params)
        conn.rollback()
    assert _row(request_id) == row


@pytest.mark.parametrize("status", ["Pendente", "Devolvida"])
def test_the_database_accepts_a_paired_reclassification_while_editable(env, status):
    request_id = _create(env, f"T3 {status}", document=False)
    _set_state(request_id, status)
    row = _row(request_id)
    snapshot_b = _snapshot_naming(B, row["regra_snapshot_json"])
    with main.app.app_context():
        conn = _db()
        conn.execute("UPDATE requisicoes SET atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
                     (B, snapshot_b, request_id))
        conn.commit()
    assert (_row(request_id)["atividade_versao_id"], _row(request_id)["regra_snapshot_json"]) == (B, snapshot_b)


def _set_days(days):
    with main.app.app_context():
        conn = _db()
        save_return_response_settings(conn, {"return_response_days": str(days), "auto_indefer_devolvida": "0"})
        conn.commit()


# ===========================================================================
# 5. the real forms in a browser (headless Chromium over the test client)
# ===========================================================================

from tests.cdp_browser_support import BrowserSession, find_chromium  # noqa: E402

CHROMIUM = find_chromium()
browser = pytest.mark.skipif(CHROMIUM is None, reason="no headless Chromium available")

_CHOOSE = """(() => {
  const pick = (id, value) => { const el = document.getElementById(id); el.value = value;
                                el.dispatchEvent(new Event('change', {bubbles: true})); return el; };
  pick(%(tipo)s, %(tipo_value)s); pick(%(grupo)s, %(grupo_value)s);
  const activity = pick(%(atividade)s, %(atividade_value)s);
  return JSON.stringify({value: activity.value, disabled: activity.disabled,
                         label: activity.selectedOptions[0] && activity.selectedOptions[0].textContent});
})()"""


def _choose(session, prefix, tipo, grupo, version):
    ids = {"tipo": f"{prefix}tipo_atividade_select", "grupo": f"{prefix}grupo_num",
           "atividade": f"{prefix}atividade_versao_id_select"}
    script = _CHOOSE % {**{key: json.dumps(value) for key, value in ids.items()},
                        "tipo_value": json.dumps(tipo), "grupo_value": json.dumps(grupo),
                        "atividade_value": json.dumps(str(version))}
    return json.loads(session.evaluate(script))


@browser
def test_a_student_corrects_the_activity_on_the_real_edit_form(env):
    request_id = _create(env, "B1 navegador")
    docs = _attachments(request_id)
    _as_student(env)
    session = BrowserSession(env["client"], CHROMIUM)
    try:
        session.goto(f"/aluno/requisicoes/{request_id}?edit=1")
        assert session.evaluate("document.getElementById('atividade_versao_id_select').value") == str(A)
        chosen = _choose(session, "", AEU_TYPE, "2", AEU)
        assert chosen == {"value": str(AEU), "disabled": False, "label": NAMES[AEU]}
        session.click('form[data-direct-upload] button[type="submit"]')
        session.wait_for("location.pathname === '/aluno/requisicoes'")
        assert "Requisição atualizada." in session.evaluate("document.body.innerText")
    finally:
        session.close()
    row = _row(request_id)
    assert (row["atividade_versao_id"], _authority(row).rule.eixo) == (AEU, "AEU")
    assert _attachments(request_id) == docs


@browser
def test_the_administrator_corrects_the_activity_in_the_requisicoes_modal(env):
    request_id = _create(env, "B2 modal", document=False)
    _as_admin(env)
    session = BrowserSession(env["client"], CHROMIUM)
    try:
        session.goto(f"/admin/requisicoes?open_edit=1&req_id={request_id}")
        session.wait_for("document.getElementById('m_atividade_versao_id_registrada').value === '%d'" % A)
        chosen = _choose(session, "m_", AAC_TYPE, "1", B)
        assert chosen == {"value": str(B), "disabled": False, "label": NAMES[B]}
        session.evaluate("window.__beforeSubmit = true")
        session.click("#m_create_submit")
        session.wait_for("document.readyState === 'complete' && !window.__beforeSubmit")
        posted = [r for r in session.requests if r[0] == "POST"]
    finally:
        session.close()
    assert posted and posted[-1][1].endswith(f"/admin/requisicoes/{request_id}/editar"), posted
    row = _row(request_id)
    assert (row["atividade_versao_id"], _authority(row).payload["flow_origin"]) == (B, "admin_reclassify")
