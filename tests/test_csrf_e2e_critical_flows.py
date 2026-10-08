import main
from tests.canonical_request_documents_support import (
    INTENT_IDS_FIELD,
    SUBMISSION_FIELD,
    canonical_documents,
    form_submission,
    upload_verified,
)
from tests.canonical_request_test_support import login_student
from tests.test_comprovantes_google_drive import PDF
from tests.versioned_test_support import isolated_versioned_app_env


def test_student_canonical_request_routes_are_not_rejected_by_global_csrf(tmp_path):
    with isolated_versioned_app_env(tmp_path, "csrf-student.db") as env:
        login_student(env["client"])
        for path, name in (("/aluno/nova-requisicao", "CSRF canonical 1"), ("/aluno/nova_requisicao", "CSRF canonical 2")):
            response = env["client"].post(path, data={
                "atividade_versao_id": "29", "nome_evento": name,
                "data_evento": "2026-05-01", "horas_solicitadas": "4",
            })
            assert response.status_code != 400


def test_student_attachment_flow_uses_exact_version(tmp_path):
    """STORAGE S3-A: the attachment flow is the direct-upload protocol (issue,
    finalize, then a form carrying verified intent ids); no step of it is
    rejected as a CSRF failure."""
    with isolated_versioned_app_env(tmp_path, "csrf-upload.db") as env, canonical_documents(main.app) as store:
        login_student(env["client"])
        submission = form_submission(env["client"], "/aluno/nova-requisicao")
        intent_id = upload_verified(env["client"], store, submission, PDF, "proof.pdf")
        response = env["client"].post("/aluno/nova-requisicao", data={
            "atividade_versao_id": "29", "nome_evento": "Attachment canonical",
            "data_evento": "2026-05-01", "horas_solicitadas": "4",
            SUBMISSION_FIELD: submission, INTENT_IDS_FIELD: [intent_id],
        })
        assert response.status_code != 400
