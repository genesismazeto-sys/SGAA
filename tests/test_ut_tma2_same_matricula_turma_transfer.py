"""Moving a student between Turmas must not demand a new matrícula.

The placeholder pass inside ``resequence_turma_aluno_matriculas`` only covers
the Turma being renumbered. A student who has just left Turma A still holds a
name in A's namespace, so renumbering A's remainder handed that exact matrícula
to somebody else and the transfer died on
``UNIQUE constraint failed: alunos.matricula``.
"""
import sqlite3

import main
from app.academics import (
    resequence_turma_aluno_matriculas,
    resequence_turma_aluno_matriculas_for_ids,
)
from app.prod1_schema import bootstrap_prod1_schema
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


def _database():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _seed(conn):
    curso = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('C','PPA',8)"
    ).lastrowid
    turma_a = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('A',11,?,2026,1,'PPA-T11')",
        (curso,),
    ).lastrowid
    turma_b = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('B',12,?,2026,1,'PPA-T12')",
        (curso,),
    ).lastrowid
    ana = conn.execute(
        "INSERT INTO alunos(nome,matricula,email,turma_id) "
        "VALUES('Ana','PPA-T11.001','ana@x',?)",
        (turma_a,),
    ).lastrowid
    bruno = conn.execute(
        "INSERT INTO alunos(nome,matricula,email,turma_id) "
        "VALUES('Bruno','PPA-T11.002','bruno@x',?)",
        (turma_a,),
    ).lastrowid
    carla = conn.execute(
        "INSERT INTO alunos(nome,matricula,email,turma_id) "
        "VALUES('Carla','PPA-T12.001','carla@x',?)",
        (turma_b,),
    ).lastrowid
    return locals()


def _matricula(conn, aluno_id):
    return conn.execute(
        "SELECT matricula FROM alunos WHERE id=?", (aluno_id,)
    ).fetchone()["matricula"]


def test_resequencing_both_turmas_after_a_move_does_not_collide():
    """The regression: the departed student used to squat on A's namespace."""
    conn = _database()
    d = _seed(conn)
    conn.execute("UPDATE alunos SET turma_id=? WHERE id=?", (d["turma_b"], d["ana"]))

    # Origin first is exactly the order that used to raise.
    resequence_turma_aluno_matriculas_for_ids(conn, d["turma_a"], d["turma_b"])

    assert _matricula(conn, d["bruno"]) == "PPA-T11.001"
    assert _matricula(conn, d["ana"]).startswith("PPA-T12.")
    matriculas = [
        row["matricula"] for row in conn.execute("SELECT matricula FROM alunos")
    ]
    assert len(matriculas) == len(set(matriculas))


def test_resequencing_is_independent_of_the_turma_order():
    conn = _database()
    d = _seed(conn)
    conn.execute("UPDATE alunos SET turma_id=? WHERE id=?", (d["turma_b"], d["ana"]))

    resequence_turma_aluno_matriculas_for_ids(conn, d["turma_b"], d["turma_a"])

    assert _matricula(conn, d["bruno"]) == "PPA-T11.001"
    matriculas = [
        row["matricula"] for row in conn.execute("SELECT matricula FROM alunos")
    ]
    assert len(matriculas) == len(set(matriculas))


def test_single_turma_resequence_is_unchanged():
    conn = _database()
    d = _seed(conn)

    resequence_turma_aluno_matriculas(conn, d["turma_a"])

    assert _matricula(conn, d["ana"]) == "PPA-T11.001"
    assert _matricula(conn, d["bruno"]) == "PPA-T11.002"
    assert _matricula(conn, d["carla"]) == "PPA-T12.001"


# ---------------------------------------------------------------------------
# The route: a plain Turma change, matrícula left exactly as it was
# ---------------------------------------------------------------------------


def _aluno(conn, usuario_id):
    return conn.execute(
        "SELECT id, matricula, turma_id, matriz_id FROM alunos WHERE usuario_id=?",
        (usuario_id,),
    ).fetchone()


def test_admin_moves_a_student_between_turmas_keeping_the_matricula(tmp_path):
    with isolated_versioned_app_env(tmp_path, "tma2-transfer.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            conn = main.get_db_connection()
            row = conn.execute(
                "SELECT a.usuario_id, a.matricula, a.turma_id, u.nome, u.email"
                "  FROM alunos a JOIN usuarios u ON u.id=a.usuario_id"
                " WHERE a.turma_id=1 ORDER BY a.id LIMIT 1"
            ).fetchone()
            if row is None:
                conn.execute("UPDATE alunos SET turma_id=1 WHERE id=1")
                conn.commit()
                row = conn.execute(
                    "SELECT a.usuario_id, a.matricula, a.turma_id, u.nome, u.email"
                    "  FROM alunos a JOIN usuarios u ON u.id=a.usuario_id"
                    " WHERE a.turma_id=1 ORDER BY a.id LIMIT 1"
                ).fetchone()
            usuario_id = row["usuario_id"]
            matricula_original = row["matricula"]

        response = env["client"].post(
            f"/admin/editar_aluno/{usuario_id}",
            data={
                "nome": row["nome"],
                "email": row["email"],
                "matricula": matricula_original,  # unchanged, as the admin left it
                "turma_id": "2",
                "status": "Ativo",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302, response.get_data(as_text=True)[:400]

        with main.app.app_context():
            conn = main.get_db_connection()
            depois = _aluno(conn, usuario_id)
            assert depois["turma_id"] == 2
            assert depois["matricula"] == matricula_original
            # A Turma governa; nenhuma matriz individual foi gravada.
            assert depois["matriz_id"] is None
            duplicadas = conn.execute(
                "SELECT COUNT(*) FROM (SELECT matricula FROM alunos"
                " GROUP BY matricula HAVING COUNT(*) > 1)"
            ).fetchone()[0]
            assert duplicadas == 0


def test_transfer_leaves_previous_requests_and_their_hours_alone(tmp_path):
    with isolated_versioned_app_env(tmp_path, "tma2-transfer-history.db") as env:
        login_admin(env["client"])
        with main.app.app_context():
            conn = main.get_db_connection()
            row = conn.execute(
                "SELECT a.id, a.usuario_id, a.matricula, u.nome, u.email"
                "  FROM alunos a JOIN usuarios u ON u.id=a.usuario_id"
                " WHERE a.matricula='PPA.TESTE.0001'"
            ).fetchone()
            conn.execute("UPDATE alunos SET turma_id=1 WHERE id=?", (row["id"],))
            versao = conn.execute(
                "SELECT atividade_versao_id FROM matriz_atividade_versao_item"
                " WHERE matriz_id=1 ORDER BY atividade_versao_id LIMIT 1"
            ).fetchone()["atividade_versao_id"]
            from app.versioning.snapshots import prepare_versioned_requisicao_snapshot

            prepared = prepare_versioned_requisicao_snapshot(
                conn,
                flow_origin="aluno_create",
                aluno_id=row["id"],
                atividade_versao_id=versao,
            )
            request_id = conn.execute(
                """INSERT INTO requisicoes
                     (aluno_id,atividade_versao_id,data_solicitacao,data_evento,
                      horas_solicitadas,nome_evento,status,horas_deferidas,
                      regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (
                    row["id"], prepared.atividade_versao_id, "2026-01-10 10:00:00",
                    "2026-01-05", 6.0, "SOB MATRIZ A", "Deferida", 6.0,
                    prepared.snapshot_json, 1, "T1",
                ),
            ).fetchone()["id"]
            conn.commit()
            campos = (
                "atividade_versao_id,regra_snapshot_json,horas_solicitadas,"
                "horas_deferidas,status,turma_id_snapshot,turma_codigo_snapshot"
            )
            antes = tuple(
                conn.execute(
                    f"SELECT {campos} FROM requisicoes WHERE id=?", (request_id,)
                ).fetchone()
            )

        response = env["client"].post(
            f"/admin/editar_aluno/{row['usuario_id']}",
            data={
                "nome": row["nome"],
                "email": row["email"],
                "matricula": row["matricula"],
                "turma_id": "2",
                "status": "Ativo",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

        with main.app.app_context():
            conn = main.get_db_connection()
            depois = tuple(
                conn.execute(
                    f"SELECT {campos} FROM requisicoes WHERE id=?", (request_id,)
                ).fetchone()
            )
            assert depois == antes
            assert depois[3] == 6.0
            assert _aluno(conn, row["usuario_id"])["matricula"] == row["matricula"]
