from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_admin_filterable_surfaces_render_with_canonical_dataset(tmp_path):
    with isolated_versioned_app_env(tmp_path, "admin-filters.db") as env:
        login_admin(env["client"])
        for path in ("/admin/alunos?status=Ativo", "/admin/turmas?status=Ativa", "/admin/atividades?tipo=Acadêmica+Complementar"):
            response = env["client"].get(path)
            assert response.status_code == 200
            assert 'filter' in response.get_data(as_text=True).lower()
