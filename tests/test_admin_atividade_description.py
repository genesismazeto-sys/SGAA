import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def test_description_edit_persists_on_canonical_base(tmp_path):
    with isolated_versioned_app_env(tmp_path, "activity-description.db") as env:
        login_admin(env["client"])
        response = env["client"].post(
            "/admin/editar_atividade/29",
            data={"nome": "Updated canonical activity", "descricao": "Updated description",
                  "grupo": "1 - AAC vigente", "tipo_atividade": "Acadêmica Complementar",
                  "limite_horas": "", "tem_limitacao": "0"},
        )
        assert response.status_code == 302
        with main.app.app_context():
            row = main.get_db_connection().execute(
                "SELECT b.nome_conceito,b.descricao FROM atividade_base b JOIN atividade_versao v ON v.atividade_base_id=b.id WHERE v.id=29"
            ).fetchone()
            assert dict(row) == {"nome_conceito": "Updated canonical activity", "descricao": "Updated description"}
