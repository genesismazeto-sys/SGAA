"""FC-09 RED/green contracts for usage-based academic graph freezing."""
from __future__ import annotations

import os
import sys
import uuid

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def fc09_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc09_freeze.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            suffix = uuid.uuid4().hex[:8]
            curso_id = conn.execute(
                """
                INSERT INTO cursos (nome, codigo, duracao_periodos, periodo, status)
                VALUES (?, ?, 8, 'integral', 'ativo') RETURNING id
                """,
                (f"Curso FC09 {suffix}", f"FC9{suffix}"),
            ).fetchone()["id"]
            other_curso_id = conn.execute(
                """
                INSERT INTO cursos (nome, codigo, duracao_periodos, periodo, status)
                VALUES (?, ?, 8, 'integral', 'ativo') RETURNING id
                """,
                (f"Outro Curso FC09 {suffix}", f"FCO{suffix}"),
            ).fetchone()["id"]
            unassigned_id = conn.execute(
                """
                INSERT INTO matrizes_atividades (
                    curso_id, nome, versao, status, data_inicio_vigencia,
                    data_fim_vigencia, horas_aac_obrigatorias,
                    horas_extensao_obrigatorias, descricao
                ) VALUES (?, 'Matriz FC09 U1', 'u1', 'rascunho', '2026-01-01',
                          '2029-12-31', 160, 80, 'Unassigned U1')
                RETURNING id
                """,
                (curso_id,),
            ).fetchone()["id"]
            assigned_id = conn.execute(
                """
                INSERT INTO matrizes_atividades (
                    curso_id, nome, versao, status, data_inicio_vigencia,
                    data_fim_vigencia, horas_aac_obrigatorias,
                    horas_extensao_obrigatorias, descricao
                ) VALUES (?, 'Matriz FC09', 'v1', 'vigente', '2026-01-01',
                          '2029-12-31', 160, 80, 'Descrição inicial')
                RETURNING id
                """,
                (curso_id,),
            ).fetchone()["id"]
            u2_id = conn.execute(
                """
                INSERT INTO matrizes_atividades (
                    curso_id, nome, versao, status,
                    horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
                ) VALUES (?, 'Matriz FC09 U2', 'u2', 'rascunho', 100, 50,
                          'Unassigned U2') RETURNING id
                """,
                (curso_id,),
            ).fetchone()["id"]
            turma_id = conn.execute(
                """
                INSERT INTO turmas (
                    nome, ano, semestre, turno, status, numero, curso_id,
                    matriz_id, ano_inicio, semestre_inicio, ano_fim,
                    semestre_fim, codigo
                ) VALUES ('Turma FC09', 2026, 1, 'Noite', 'Ativa', 990, ?, ?,
                          2026, 1, 2029, 2, ?)
                RETURNING id
                """,
                (curso_id, assigned_id, f"FC09-{suffix}"),
            ).fetchone()["id"]

            activities = {}
            for key, activity_type in (
                ("aac", "Acadêmica Complementar"),
                ("aac_other", "Acadêmica Complementar"),
                ("aeu", "Extensão Universitária"),
                ("aeu_other", "Extensão Universitária"),
            ):
                activity_id = conn.execute(
                    """
                    INSERT INTO atividades (
                        grupo, nome, descricao, tipo_atividade,
                        tem_limitacao, tipo_limitacao
                    ) VALUES (?, ?, ?, ?, 0, 'total') RETURNING id
                    """,
                    (
                        "1 - FC09" if activity_type.startswith("Acad") else "NA",
                        f"Atividade {key} {suffix}",
                        f"Descrição {key}",
                        activity_type,
                    ),
                ).fetchone()["id"]
                base_id = conn.execute(
                    """
                    INSERT INTO atividade_base (nome_conceito, descricao, status)
                    VALUES (?, ?, 'ativo') RETURNING id
                    """,
                    (f"Base {key} {suffix}", f"Base {key}"),
                ).fetchone()["id"]
                conn.execute(
                    """
                    INSERT INTO atividade_legacy_map
                        (atividade_id_legacy, atividade_base_id, status)
                    VALUES (?, ?, 'mapeada')
                    """,
                    (activity_id, base_id),
                )
                activities[key] = {"id": activity_id, "base_id": base_id}

            # Two exact versions of one AAC base: V1 is historical, V2 is a
            # future candidate. The same V1 is selected by both matrices.
            v1_id = conn.execute(
                """
                INSERT INTO atividade_versao (
                    atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                    ch_por_evento, limite_semestre, limite_total,
                    observacao_aluno, observacao_admin, vigencia_inicio,
                    vigencia_fim, numero_versao, status
                ) VALUES (?, 1, 'FC09-AAC-1', 'AAC', '1 - FC09', 4, 40, 100,
                          'Aluno V1', 'Admin V1', '2026-01-01', '2029-12-31',
                          1, 'ativa') RETURNING id
                """,
                (activities["aac"]["base_id"],),
            ).fetchone()["id"]
            v2_id = conn.execute(
                """
                INSERT INTO atividade_versao (
                    atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                    ch_por_evento, limite_semestre, limite_total,
                    observacao_aluno, observacao_admin, vigencia_inicio,
                    vigencia_fim, numero_versao, status
                ) VALUES (?, 2, 'FC09-AAC-2', 'AAC', '1 - FC09', 5, 50, 120,
                          'Aluno V2', 'Admin V2', '2027-01-01', '2030-12-31',
                          2, 'ativa') RETURNING id
                """,
                (activities["aac"]["base_id"],),
            ).fetchone()["id"]

            aeu_version_id = conn.execute(
                """
                INSERT INTO atividade_versao (
                    atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                    numero_versao, status
                ) VALUES (?, 3, 'FC09-AEU-1', 'AEU', 'NA', 1, 'ativa')
                RETURNING id
                """,
                (activities["aeu"]["base_id"],),
            ).fetchone()["id"]
            draft_unassigned_id = conn.execute(
                """
                INSERT INTO atividade_versao (
                    atividade_base_id, norma_id, codigo_normativo, eixo, grupo,
                    ch_por_evento, numero_versao, status
                ) VALUES (?, 1, 'FC09-DRAFT', 'AAC', '1 - FC09', 2, 1, 'rascunho')
                RETURNING id
                """,
                (activities["aac_other"]["base_id"],),
            ).fetchone()["id"]

            conn.executemany(
                "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
                [(assigned_id, 1), (assigned_id, 2), (assigned_id, 3),
                 (unassigned_id, 1), (unassigned_id, 2), (unassigned_id, 3)],
            )
            conn.executemany(
                "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
                [
                    (assigned_id, activities["aac"]["id"]),
                    (assigned_id, activities["aeu"]["id"]),
                    (unassigned_id, activities["aac"]["id"]),
                    (unassigned_id, activities["aac_other"]["id"]),
                ],
            )
            conn.executemany(
                "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)",
                [
                    (assigned_id, v1_id),
                    (assigned_id, aeu_version_id),
                    (unassigned_id, v1_id),
                    (unassigned_id, draft_unassigned_id),
                ],
            )
            conn.commit()

        env.update(
            {
                "assigned_id": assigned_id,
                "unassigned_id": unassigned_id,
                "u2_id": u2_id,
                "turma_id": turma_id,
                "other_curso_id": other_curso_id,
                "activities": activities,
                "v1_id": v1_id,
                "v2_id": v2_id,
                "aeu_version_id": aeu_version_id,
                "draft_unassigned_id": draft_unassigned_id,
            }
        )
        yield env


@pytest.fixture()
def startup_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc09_startup_freeze.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "UPDATE matrizes_atividades SET horas_aac_obrigatorias = -7, horas_extensao_obrigatorias = -9 WHERE id = 1"
            )
            curso_id = conn.execute(
                "SELECT curso_id FROM matrizes_atividades WHERE id = 1"
            ).fetchone()[0]
            unassigned_id = conn.execute(
                """
                INSERT INTO matrizes_atividades (
                    curso_id, nome, versao, status,
                    horas_aac_obrigatorias, horas_extensao_obrigatorias
                ) VALUES (?, 'Matriz FC09 Startup Draft', 'draft', 'rascunho', -11, -13)
                RETURNING id
                """,
                (curso_id,),
            ).fetchone()["id"]
            conn.commit()
        env.update({"unassigned_id": unassigned_id})
        yield env


def test_startup_preserves_assigned_targets_and_normalizes_unassigned_targets(startup_env):
    from app.db_maintenance import ensure_matrizes_atividades_table

    with main.app.app_context():
        conn = main.get_db_connection()
        ensure_matrizes_atividades_table(conn)
        assigned = conn.execute(
            """
            SELECT horas_aac_obrigatorias, horas_extensao_obrigatorias
              FROM matrizes_atividades WHERE id = 1
            """
        ).fetchone()
        unassigned = conn.execute(
            """
            SELECT horas_aac_obrigatorias, horas_extensao_obrigatorias
              FROM matrizes_atividades WHERE id = ?
            """,
            (startup_env["unassigned_id"],),
        ).fetchone()
        turma = conn.execute(
            "SELECT matriz_id FROM turmas WHERE id = 1"
        ).fetchone()

    assert tuple(assigned) == (-7, -9)
    assert tuple(unassigned) == (160, 80)
    assert turma["matriz_id"] == 1


def _login_admin(client):
    with client.session_transaction() as session:
        session["user_id"] = 1
        session["user_type"] = "admin"
        session["user_name"] = "FC09 admin"


def _matrix_form(env, *, matrix_id=None, **overrides):
    matrix_id = matrix_id or env["assigned_id"]
    with main.app.app_context():
        row = dict(
            main.get_db_connection()
            .execute("SELECT * FROM matrizes_atividades WHERE id = ?", (matrix_id,))
            .fetchone()
        )
    data = {
        "active_tab": "dados",
        "curso_id": str(row["curso_id"]),
        "nome": row["nome"],
        "versao": row["versao"],
        "status": row["status"],
        "data_inicio_vigencia": row["data_inicio_vigencia"] or "",
        "data_fim_vigencia": row["data_fim_vigencia"] or "",
        "horas_aac_obrigatorias": str(row["horas_aac_obrigatorias"]),
        "horas_extensao_obrigatorias": str(row["horas_extensao_obrigatorias"]),
        "descricao": row["descricao"] or "",
    }
    data.update({key: str(value) for key, value in overrides.items()})
    return data


def _post_matrix(client, env, *, matrix_id=None, follow_redirects=False, **overrides):
    matrix_id = matrix_id or env["assigned_id"]
    return client.post(
        f"/admin/editar_matriz/{matrix_id}",
        data=_matrix_form(env, matrix_id=matrix_id, **overrides),
        follow_redirects=follow_redirects,
    )


def _assignments(conn, matrix_id):
    return {
        "activities": [
            row["atividade_id"]
            for row in conn.execute(
                """
                SELECT atividade_id FROM matrizes_atividades_itens
                 WHERE matriz_id = ? ORDER BY atividade_id
                """,
                (matrix_id,),
            ).fetchall()
        ],
        "versions": [
            row["atividade_versao_id"]
            for row in conn.execute(
                """
                SELECT atividade_versao_id FROM matriz_atividade_versao_item
                 WHERE matriz_id = ? ORDER BY atividade_versao_id
                """,
                (matrix_id,),
            ).fetchall()
        ],
    }


def _post_version_card(client, env, versao_id):
    return client.post(
        f"/admin/matrizes/{env['assigned_id']}/atividades/{env['activities']['aac']['id']}/nova-versao",
        data={"active_tab": "aac", "versao_id": str(versao_id)},
        follow_redirects=False,
    )


def _edit_version_data(versao_id, env):
    with main.app.app_context():
        row = dict(
            main.get_db_connection()
            .execute("SELECT * FROM atividade_versao WHERE id = ?", (versao_id,))
            .fetchone()
        )
    return {
        "norma_id": str(row["norma_id"]),
        "grupo": row["grupo"] or "1 - FC09",
        "ch_por_evento": "9",
        "limite_semestre": "90",
        "limite_total": "190",
        "observacao_aluno": "alterado",
        "observacao_admin": "alterado",
        "vigencia_inicio": row["vigencia_inicio"] or "",
        "vigencia_fim": row["vigencia_fim"] or "",
        "versao_anterior_id": "",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("curso_id", "other_curso_id"),
        ("status", "encerrada"),
        ("data_inicio_vigencia", "2027-01-01"),
        ("data_fim_vigencia", "2030-12-31"),
        ("horas_aac_obrigatorias", 999),
        ("horas_extensao_obrigatorias", 888),
    ],
)
def test_t1_t2_each_assigned_matrix_protected_field_is_frozen_atomically(fc09_env, field, value):
    client = fc09_env["client"]
    _login_admin(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        before = dict(conn.execute("SELECT * FROM matrizes_atividades WHERE id = ?", (fc09_env["assigned_id"],)).fetchone())

    override = fc09_env[value] if field == "curso_id" else value
    response = _post_matrix(client, fc09_env, **{field: override})
    assert response.status_code in (302, 303)

    with main.app.app_context():
        after = dict(
            main.get_db_connection()
            .execute("SELECT * FROM matrizes_atividades WHERE id = ?", (fc09_env["assigned_id"],))
            .fetchone()
        )
    assert after == before


def test_t3_assigned_matrix_descriptive_fields_remain_editable(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    response = _post_matrix(client, fc09_env, nome="Nome descritivo", versao="v-descritiva", descricao="Descrição nova")
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute("SELECT nome, versao, descricao FROM matrizes_atividades WHERE id = ?", (fc09_env["assigned_id"],)).fetchone()
    assert tuple(row) == ("Nome descritivo", "v-descritiva", "Descrição nova")


@pytest.mark.parametrize(
    ("active_tab", "current_key", "other_key"),
    [("aac", "aac", "aac_other"), ("aea", "aeu", "aeu_other")],
)
def test_t4_t5_assigned_matrix_membership_add_is_frozen(fc09_env, active_tab, current_key, other_key):
    client = fc09_env["client"]
    _login_admin(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        before = sorted(
            row["atividade_id"]
            for row in conn.execute(
                """
                SELECT mai.atividade_id
                  FROM matrizes_atividades_itens mai
                  JOIN atividades a ON a.id = mai.atividade_id
                 WHERE mai.matriz_id = ? AND a.tipo_atividade = ?
                """,
                (
                    fc09_env["assigned_id"],
                    "Acadêmica Complementar" if active_tab == "aac" else "Extensão Universitária",
                ),
            ).fetchall()
        )
    response = client.post(
        f"/admin/editar_matriz/{fc09_env['assigned_id']}?tab={active_tab}",
        data={
            "active_tab": active_tab,
            "selected_activity_ids": [
                str(fc09_env["activities"][current_key]["id"]),
                str(fc09_env["activities"][other_key]["id"]),
            ],
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        after = sorted(
            row["atividade_id"]
            for row in conn.execute(
                """
                SELECT mai.atividade_id
                  FROM matrizes_atividades_itens mai
                  JOIN atividades a ON a.id = mai.atividade_id
                 WHERE mai.matriz_id = ? AND a.tipo_atividade = ?
                """,
                (
                    fc09_env["assigned_id"],
                    "Acadêmica Complementar" if active_tab == "aac" else "Extensão Universitária",
                ),
            ).fetchall()
        )
    assert after == before


@pytest.mark.parametrize(
    ("active_tab", "current_key", "other_key"),
    [("aac", "aac", "aac_other"), ("aea", "aeu", "aeu_other")],
)
def test_t4_t5_assigned_matrix_membership_remove_is_frozen(fc09_env, active_tab, current_key, other_key):
    client = fc09_env["client"]
    _login_admin(client)
    activity_type = "Acadêmica Complementar" if active_tab == "aac" else "Extensão Universitária"
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (fc09_env["assigned_id"], fc09_env["activities"][other_key]["id"]),
        )
        conn.commit()
        before = sorted(
            row["atividade_id"]
            for row in conn.execute(
                """
                SELECT mai.atividade_id
                  FROM matrizes_atividades_itens mai
                  JOIN atividades a ON a.id = mai.atividade_id
                 WHERE mai.matriz_id = ? AND a.tipo_atividade = ?
                """,
                (fc09_env["assigned_id"], activity_type),
            ).fetchall()
        )

    response = client.post(
        f"/admin/editar_matriz/{fc09_env['assigned_id']}?tab={active_tab}",
        data={"active_tab": active_tab, "selected_activity_ids": [str(fc09_env["activities"][current_key]["id"])]},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        after = sorted(
            row["atividade_id"]
            for row in conn.execute(
                """
                SELECT mai.atividade_id
                  FROM matrizes_atividades_itens mai
                  JOIN atividades a ON a.id = mai.atividade_id
                 WHERE mai.matriz_id = ? AND a.tipo_atividade = ?
                """,
                (fc09_env["assigned_id"], activity_type),
            ).fetchall()
        )
    assert after == before


@pytest.mark.parametrize(
    ("active_tab", "current_key"),
    [("aac", "aac"), ("aea", "aeu")],
)
def test_t4_t5_assigned_matrix_membership_empty_is_frozen(fc09_env, active_tab, current_key):
    client = fc09_env["client"]
    _login_admin(client)
    activity_type = "Acadêmica Complementar" if active_tab == "aac" else "Extensão Universitária"
    with main.app.app_context():
        before = sorted(
            row["atividade_id"]
            for row in main.get_db_connection().execute(
                """
                SELECT mai.atividade_id
                  FROM matrizes_atividades_itens mai
                  JOIN atividades a ON a.id = mai.atividade_id
                 WHERE mai.matriz_id = ? AND a.tipo_atividade = ?
                """,
                (fc09_env["assigned_id"], activity_type),
            ).fetchall()
        )

    response = client.post(
        f"/admin/editar_matriz/{fc09_env['assigned_id']}?tab={active_tab}",
        data={"active_tab": active_tab},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        after = sorted(
            row["atividade_id"]
            for row in main.get_db_connection().execute(
                """
                SELECT mai.atividade_id
                  FROM matrizes_atividades_itens mai
                  JOIN atividades a ON a.id = mai.atividade_id
                 WHERE mai.matriz_id = ? AND a.tipo_atividade = ?
                """,
                (fc09_env["assigned_id"], activity_type),
            ).fetchall()
        )
    assert after == before


def test_t6_assigned_matrix_exact_version_cannot_relink(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        before_links = [
            row["atividade_versao_id"]
            for row in conn.execute(
                """
                SELECT mavi.atividade_versao_id
                  FROM matriz_atividade_versao_item mavi
                  JOIN atividade_versao av ON av.id = mavi.atividade_versao_id
                 WHERE mavi.matriz_id = ? AND av.atividade_base_id = ?
                 ORDER BY mavi.atividade_versao_id
                """,
                (fc09_env["assigned_id"], fc09_env["activities"]["aac"]["base_id"]),
            ).fetchall()
        ]
    assert before_links == [fc09_env["v1_id"]]

    _post_version_card(client, fc09_env, fc09_env["v2_id"])
    with main.app.app_context():
        conn = main.get_db_connection()
        after_links = [
            row["atividade_versao_id"]
            for row in conn.execute(
                """
                SELECT mavi.atividade_versao_id
                  FROM matriz_atividade_versao_item mavi
                  JOIN atividade_versao av ON av.id = mavi.atividade_versao_id
                 WHERE mavi.matriz_id = ? AND av.atividade_base_id = ?
                 ORDER BY mavi.atividade_versao_id
                """,
                (fc09_env["assigned_id"], fc09_env["activities"]["aac"]["base_id"]),
            ).fetchall()
        ]
    assert after_links == [fc09_env["v1_id"]]
    assert len(after_links) == 1
    assert fc09_env["v2_id"] not in after_links


def test_t7_assigned_matrix_exact_version_cannot_be_removed(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    response = client.post(
        f"/admin/matrizes/{fc09_env['assigned_id']}/versoes/remover",
        data={"base_id": str(fc09_env["activities"]["aac"]["base_id"])},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        assert main.get_db_connection().execute(
            "SELECT 1 FROM matriz_atividade_versao_item WHERE matriz_id = ? AND atividade_versao_id = ?",
            (fc09_env["assigned_id"], fc09_env["v1_id"]),
        ).fetchone() is not None


def test_t8_unassigned_matrix_can_relink_exact_version(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    response = client.post(
        f"/admin/matrizes/{fc09_env['unassigned_id']}/versoes/definir",
        data={"base_id": str(fc09_env["activities"]["aac"]["base_id"]), "versao_id": str(fc09_env["v2_id"])},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute("SELECT atividade_versao_id FROM matriz_atividade_versao_item WHERE matriz_id = ?", (fc09_env["unassigned_id"],)).fetchone()
    assert row["atividade_versao_id"] == fc09_env["v2_id"]


def test_unassigned_matrix_row_and_membership_remain_editable(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    response = _post_matrix(
        client,
        fc09_env,
        matrix_id=fc09_env["unassigned_id"],
        curso_id=fc09_env["other_curso_id"],
        status="vigente",
        horas_aac_obrigatorias=333,
    )
    assert response.status_code in (302, 303)

    response = client.post(
        f"/admin/editar_matriz/{fc09_env['unassigned_id']}?tab=aac",
        data={
            "active_tab": "aac",
            "selected_activity_ids": [
                str(fc09_env["activities"]["aac"]["id"]),
                str(fc09_env["activities"]["aac_other"]["id"]),
            ],
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute("SELECT curso_id, status, horas_aac_obrigatorias FROM matrizes_atividades WHERE id = ?", (fc09_env["unassigned_id"],)).fetchone()
        assert row["curso_id"] == fc09_env["other_curso_id"]
        assert row["status"] == "vigente"
        assert row["horas_aac_obrigatorias"] == 333
        assert conn.execute(
            "SELECT 1 FROM matrizes_atividades_itens WHERE matriz_id = ? AND atividade_id = ?",
            (fc09_env["unassigned_id"], fc09_env["activities"]["aac_other"]["id"]),
        ).fetchone() is not None


def test_assigned_matrix_stays_frozen_until_all_turmas_are_removed(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        second_turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id,
                matriz_id, ano_inicio, semestre_inicio, ano_fim,
                semestre_fim, codigo
            ) VALUES ('Turma FC09 2', 2027, 1, 'Noite', 'Ativa', 991, ?, ?,
                      2027, 1, 2030, 2, 'FC09-2') RETURNING id
            """,
            (conn.execute("SELECT curso_id FROM matrizes_atividades WHERE id = ?", (fc09_env["assigned_id"],)).fetchone()[0], fc09_env["assigned_id"]),
        ).fetchone()["id"]
        conn.commit()

    before = _matrix_form(fc09_env)
    response = _post_matrix(client, fc09_env, horas_aac_obrigatorias=444)
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute("SELECT horas_aac_obrigatorias FROM matrizes_atividades WHERE id = ?", (fc09_env["assigned_id"],)).fetchone()[0] == int(before["horas_aac_obrigatorias"])
        conn.execute("DELETE FROM turmas WHERE id = ?", (fc09_env["turma_id"],))
        conn.commit()

    response = _post_matrix(client, fc09_env, horas_aac_obrigatorias=555)
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute("SELECT horas_aac_obrigatorias FROM matrizes_atividades WHERE id = ?", (fc09_env["assigned_id"],)).fetchone()[0] == int(before["horas_aac_obrigatorias"])
        conn.execute("DELETE FROM turmas WHERE id = ?", (second_turma_id,))
        conn.commit()


def test_t9_assigned_version_rule_edit_is_rejected(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    response = client.post(
        f"/admin/catalogo-versoes/{fc09_env['activities']['aac']['base_id']}/versoes/{fc09_env['v1_id']}/editar",
        data=_edit_version_data(fc09_env["v1_id"], fc09_env),
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute("SELECT ch_por_evento FROM atividade_versao WHERE id = ?", (fc09_env["v1_id"],)).fetchone()
    assert row["ch_por_evento"] == 4


def test_t10_fc07_new_version_from_frozen_predecessor_remains_allowed(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    response = client.post(
        f"/admin/catalogo-versoes/{fc09_env['activities']['aac']['base_id']}/nova-versao?from={fc09_env['v1_id']}",
        data={
            "norma_id": "1",
            "grupo": "1 - FC09",
            "ch_por_evento": "6",
            "limite_semestre": "60",
            "limite_total": "160",
            "observacao_aluno": "new",
            "observacao_admin": "new",
            "vigencia_inicio": "2028-01-01",
            "vigencia_fim": "2031-12-31",
            "versao_anterior_id": str(fc09_env["v1_id"]),
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute("SELECT id, versao_anterior_id FROM atividade_versao WHERE atividade_base_id = ? ORDER BY numero_versao DESC LIMIT 1", (fc09_env["activities"]["aac"]["base_id"],)).fetchone()
    assert row["id"] != fc09_env["v1_id"]
    assert row["versao_anterior_id"] == fc09_env["v1_id"]


def test_t11_unassigned_only_version_remains_editable(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    response = client.post(
        f"/admin/catalogo-versoes/{fc09_env['activities']['aac_other']['base_id']}/versoes/{fc09_env['draft_unassigned_id']}/editar",
        data=_edit_version_data(fc09_env["draft_unassigned_id"], fc09_env),
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute("SELECT ch_por_evento FROM atividade_versao WHERE id = ?", (fc09_env["draft_unassigned_id"],)).fetchone()
    assert row["ch_por_evento"] == 9


def test_t12_shared_version_is_frozen_by_assigned_matrix_even_with_unassigned_matrix(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    response = client.post(
        f"/admin/catalogo-versoes/{fc09_env['activities']['aac']['base_id']}/versoes/{fc09_env['v1_id']}/editar",
        data=_edit_version_data(fc09_env["v1_id"], fc09_env),
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute("SELECT ch_por_evento FROM atividade_versao WHERE id = ?", (fc09_env["v1_id"],)).fetchone()
    assert row["ch_por_evento"] == 4


def test_t13_assigned_matrix_delete_is_refused_and_turma_pointer_survives(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    response = client.post(f"/admin/matrizes/{fc09_env['assigned_id']}/excluir", follow_redirects=False)
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute("SELECT 1 FROM matrizes_atividades WHERE id = ?", (fc09_env["assigned_id"],)).fetchone() is not None
        assert conn.execute("SELECT matriz_id FROM turmas WHERE id = ?", (fc09_env["turma_id"],)).fetchone()["matriz_id"] == fc09_env["assigned_id"]


def test_assigned_activity_delete_is_refused_without_dangling_membership(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    activity_id = fc09_env["activities"]["aac"]["id"]
    response = client.post(f"/admin/deletar_atividade/{activity_id}", follow_redirects=False)
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute("SELECT 1 FROM atividades WHERE id = ?", (activity_id,)).fetchone() is not None
        assert conn.execute(
            "SELECT 1 FROM matrizes_atividades_itens WHERE matriz_id = ? AND atividade_id = ?",
            (fc09_env["assigned_id"], activity_id),
        ).fetchone() is not None


def test_bulk_matrix_delete_preflights_assigned_ids_atomically(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    u1_id = fc09_env["unassigned_id"]
    assigned_id = fc09_env["assigned_id"]
    u2_id = fc09_env["u2_id"]
    assert u1_id < assigned_id < u2_id

    with main.app.app_context():
        conn = main.get_db_connection()
        ref_counts = {
            matrix_id: conn.execute(
                "SELECT COUNT(*) FROM turmas WHERE matriz_id = ?", (matrix_id,)
            ).fetchone()[0]
            for matrix_id in (u1_id, assigned_id, u2_id)
        }
        assert ref_counts[u1_id] == 0
        assert ref_counts[assigned_id] >= 1
        assert ref_counts[u2_id] == 0

    response = client.post(
        "/admin/matrizes/excluir",
        data={
            "matriz_ids": [
                str(u1_id),
                str(assigned_id),
                str(u2_id),
            ]
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        persisted_ids = {
            row["id"]
            for row in conn.execute(
                "SELECT id FROM matrizes_atividades WHERE id IN (?, ?, ?) ORDER BY id",
                (u1_id, assigned_id, u2_id),
            ).fetchall()
        }
        assert persisted_ids == {u1_id, assigned_id, u2_id}
        assert conn.execute(
            "SELECT matriz_id FROM turmas WHERE id = ?", (fc09_env["turma_id"],)
        ).fetchone()["matriz_id"] == assigned_id


def test_assigned_selected_draft_cannot_be_activated_in_place(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id) VALUES (?, ?)",
            (fc09_env["assigned_id"], fc09_env["draft_unassigned_id"]),
        )
        conn.commit()
    response = client.post(
        f"/admin/catalogo-versoes/{fc09_env['activities']['aac_other']['base_id']}/versoes/{fc09_env['draft_unassigned_id']}/ativar",
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        status = main.get_db_connection().execute("SELECT status FROM atividade_versao WHERE id = ?", (fc09_env["draft_unassigned_id"],)).fetchone()[0]
    assert status == "rascunho"


def test_t14_unassigned_matrix_delete_remains_legal(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    response = client.post(f"/admin/matrizes/{fc09_env['unassigned_id']}/excluir", follow_redirects=False)
    assert response.status_code in (302, 303)
    with main.app.app_context():
        assert main.get_db_connection().execute("SELECT 1 FROM matrizes_atividades WHERE id = ?", (fc09_env["unassigned_id"],)).fetchone() is None


def test_t16_illegal_matrix_post_rejects_descriptive_and_norma_changes_atomically(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        before = dict(conn.execute("SELECT nome, descricao, horas_aac_obrigatorias FROM matrizes_atividades WHERE id = ?", (fc09_env["assigned_id"],)).fetchone())
        before_normas = [row["norma_id"] for row in conn.execute("SELECT norma_id FROM matriz_norma WHERE matriz_id = ? ORDER BY norma_id", (fc09_env["assigned_id"],)).fetchall()]
    data = _matrix_form(fc09_env, nome="não persiste", descricao="não persiste", horas_aac_obrigatorias=777)
    data.update({"manage_normas_present": "1", "norma_ids": ["1", "2"]})
    response = client.post(f"/admin/editar_matriz/{fc09_env['assigned_id']}", data=data, follow_redirects=False)
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        after = dict(conn.execute("SELECT nome, descricao, horas_aac_obrigatorias FROM matrizes_atividades WHERE id = ?", (fc09_env["assigned_id"],)).fetchone())
        after_normas = [row["norma_id"] for row in conn.execute("SELECT norma_id FROM matriz_norma WHERE matriz_id = ? ORDER BY norma_id", (fc09_env["assigned_id"],)).fetchall()]
    assert after == before
    assert after_normas == before_normas


def test_t17_assigned_matrix_new_activity_add_is_atomic_and_does_not_extend_graph(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    unassigned_name = f"Nova FC09 unassigned {uuid.uuid4().hex[:8]}"
    valid_payload = {
        "grupo_numero": "8",
        "grupo_descricao": "Nova",
        "norma_id": "1",
        "add_to_matrix": "1",
    }

    unassigned_response = client.post(
        f"/admin/matrizes/{fc09_env['unassigned_id']}/atividades/nova/aac",
        data={"nome": unassigned_name, **valid_payload},
        follow_redirects=False,
    )
    assert unassigned_response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        created_activity = conn.execute(
            "SELECT id FROM atividades WHERE nome = ?", (unassigned_name,)
        ).fetchone()
        assert created_activity is not None
        created_base = conn.execute(
            "SELECT id FROM atividade_base WHERE nome_conceito = ?", (unassigned_name,)
        ).fetchone()
        assert created_base is not None
        assert conn.execute(
            "SELECT 1 FROM matrizes_atividades_itens WHERE matriz_id = ? AND atividade_id = ?",
            (fc09_env["unassigned_id"], created_activity["id"]),
        ).fetchone() is not None

        before_counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "atividades",
                "atividade_base",
                "atividade_versao",
                "atividade_legacy_map",
                "matrizes_atividades_itens",
                "matriz_atividade_versao_item",
            )
        }
        before_assignments = _assignments(conn, fc09_env["assigned_id"])

    assigned_name = f"Nova FC09 assigned {uuid.uuid4().hex[:8]}"
    assigned_response = client.post(
        f"/admin/matrizes/{fc09_env['assigned_id']}/atividades/nova/aac",
        data={"nome": assigned_name, **valid_payload},
        follow_redirects=False,
    )
    assert assigned_response.status_code == 200
    assert "Parâmetros inválidos." in assigned_response.get_data(as_text=True)

    with main.app.app_context():
        conn = main.get_db_connection()
        after_counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in before_counts
        }
        after_assignments = _assignments(conn, fc09_env["assigned_id"])
        assert conn.execute("SELECT 1 FROM atividades WHERE nome = ?", (assigned_name,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM atividade_base WHERE nome_conceito = ?", (assigned_name,)).fetchone() is None
    assert after_counts == before_counts
    assert after_assignments == before_assignments


def test_t18_when_zero_turmas_remain_matrix_edit_resumes(fc09_env):
    client = fc09_env["client"]
    _login_admin(client)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM turmas WHERE matriz_id = ?", (fc09_env["assigned_id"],))
        conn.commit()
    response = _post_matrix(client, fc09_env, horas_aac_obrigatorias=777)
    assert response.status_code in (302, 303)
    with main.app.app_context():
        value = main.get_db_connection().execute("SELECT horas_aac_obrigatorias FROM matrizes_atividades WHERE id = ?", (fc09_env["assigned_id"],)).fetchone()[0]
    assert value == 777
