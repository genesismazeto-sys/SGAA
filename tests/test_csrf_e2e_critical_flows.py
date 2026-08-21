from io import BytesIO

from tests.canonical_request_test_support import login_student
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
    with isolated_versioned_app_env(tmp_path, "csrf-upload.db") as env:
        login_student(env["client"])
        response = env["client"].post("/aluno/nova-requisicao", data={
            "atividade_versao_id": "29", "nome_evento": "Attachment canonical",
            "data_evento": "2026-05-01", "horas_solicitadas": "4",
            "arquivo_comprovante": (BytesIO(b"pdf"), "proof.pdf"),
        }, content_type="multipart/form-data")
        assert response.status_code != 400
