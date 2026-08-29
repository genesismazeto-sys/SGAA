import main
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def _unselected_version(conn):
    base = conn.execute("INSERT INTO atividade_base(nome_conceito,status) VALUES ('Delete candidate','ativo') RETURNING id").fetchone()["id"]
    version = conn.execute(
        """INSERT INTO atividade_versao
             (atividade_base_id,eixo,numero_versao,status)
             VALUES (?,'AAC',1,'ativa') RETURNING id""", (base,)
    ).fetchone()["id"]
    conn.commit()
    return base, version


def test_unreferenced_exact_version_can_be_deleted(tmp_path):
    with isolated_versioned_app_env(tmp_path, "activity-delete.db") as env:
        with main.app.app_context():
            base, version = _unselected_version(main.get_db_connection())
        login_admin(env["client"])
        assert env["client"].post(f"/admin/deletar_atividade/{version}").status_code == 302
        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute("SELECT 1 FROM atividade_versao WHERE id=?", (version,)).fetchone() is None
            assert conn.execute("SELECT 1 FROM atividade_base WHERE id=?", (base,)).fetchone() is None


def test_selected_exact_version_delete_is_rejected(tmp_path):
    with isolated_versioned_app_env(tmp_path, "activity-delete-block.db") as env:
        login_admin(env["client"])
        env["client"].post("/admin/deletar_atividade/1")
        with main.app.app_context():
            assert main.get_db_connection().execute("SELECT 1 FROM atividade_versao WHERE id=1").fetchone()
