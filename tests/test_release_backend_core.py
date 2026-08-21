from tests.canonical_matrix_test_support import login_admin
from tests.canonical_request_test_support import login_student
from tests.versioned_test_support import isolated_versioned_app_env


def test_release_core_student_and_admin_pages(tmp_path):
    with isolated_versioned_app_env(tmp_path, "release-core.db") as env:
        login_student(env["client"])
        assert env["client"].get("/aluno/dashboard").status_code == 200
        assert env["client"].get("/aluno/nova-requisicao").status_code == 200
        login_admin(env["client"])
        for path in ("/admin/dashboard", "/admin/turmas", "/admin/requisicoes"):
            assert env["client"].get(path).status_code == 200
