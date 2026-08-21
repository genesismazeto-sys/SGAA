from tests.canonical_request_test_support import login_student
from tests.versioned_test_support import isolated_versioned_app_env


def test_student_filter_surfaces_render_from_snapshot_history(tmp_path):
    with isolated_versioned_app_env(tmp_path, "student-filters.db") as env:
        login_student(env["client"])
        for path in ("/aluno/requisicoes?status=Pendente", "/aluno/progresso?tipo=Acadêmica+Complementar"):
            response = env["client"].get(path)
            assert response.status_code == 200
            assert 'filter' in response.get_data(as_text=True).lower()
