"""FC-12 RED contract for historical approved-hour read authority."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import main
from app.versioning.snapshots import prepare_versioned_requisicao_snapshot
from app.views import aluno as aluno_view
from app.views.admin import alunos_turmas_cursos as cohort_view
from app.views.admin import dashboard as dashboard_view
from app.views.admin import requisicoes as admin_request_view
from tests.versioned_test_support import isolated_versioned_app_env


AAC = "Acadêmica Complementar"
AEU = "Extensão Universitária"


@pytest.fixture()
def fc12_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "fc12_historical_reads.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            student = dict(
                conn.execute(
                    """
                    SELECT a.id AS aluno_id, a.usuario_id, a.turma_id,
                           t.matriz_id, t.curso_id
                      FROM alunos a
                      JOIN turmas t ON t.id = a.turma_id
                     WHERE a.matricula = 'PPA.TESTE.0001'
                    """
                ).fetchone()
            )
        env["student"] = student
        yield env


def _insert_request(
    conn,
    student,
    *,
    activity_id=1,
    status="Deferida",
    requested=8,
    deferred=None,
    event_date="2026-05-10",
    snapshot=True,
    name="FC12 historical request",
):
    prepared = None
    if snapshot:
        prepared = prepare_versioned_requisicao_snapshot(
            conn,
            flow_origin="student_create",
            aluno_id=student["aluno_id"],
            atividade_id_legacy=activity_id,
        )
    req_id = conn.execute(
        """
        INSERT INTO requisicoes (
            aluno_id, atividade_id, nome_evento, data_evento,
            horas_solicitadas, horas_deferidas, status, data_solicitacao,
            atividade_versao_id, codigo_normativo_snapshot, regra_snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            student["aluno_id"],
            activity_id,
            name,
            event_date,
            requested,
            deferred,
            status,
            f"{event_date} 10:00:00",
            prepared.atividade_versao_id if prepared else None,
            prepared.codigo_normativo if prepared else None,
            prepared.snapshot_json if prepared else None,
        ),
    ).fetchone()["id"]
    return int(req_id), prepared


def _mutate_live_activity(conn, activity_id=1):
    conn.execute(
        """
        UPDATE atividades
           SET nome = 'LIVE MUTATED NAME',
               tipo_atividade = ?,
               grupo = '99 - LIVE MUTATED GROUP',
               tem_limitacao = 1,
               tipo_limitacao = 'total',
               limite_horas_total = 999,
               limite_horas_semestral = NULL
         WHERE id = ?
        """,
        (AEU, activity_id),
    )


def _replace_live_identity(conn, activity_id, *, activity_type, name, group):
    conn.execute(
        """
        UPDATE atividades
           SET nome = ?, tipo_atividade = ?, grupo = ?
         WHERE id = ?
        """,
        (name, activity_type, group, activity_id),
    )


def _login_student(client, student):
    with client.session_transaction() as session:
        session["user_id"] = student["usuario_id"]
        session["user_type"] = "aluno"
        session["user_name"] = "Aluno FC12"


def _login_admin(client):
    with main.app.app_context():
        admin_id = main.get_db_connection().execute(
            "SELECT id FROM usuarios WHERE tipo = 'admin' ORDER BY id LIMIT 1"
        ).fetchone()["id"]
    with client.session_transaction() as session:
        session["user_id"] = admin_id
        session["user_type"] = "admin"
        session["user_name"] = "Administrador FC12"


def _capture_request_list(client, monkeypatch, *, admin, query):
    captured = {}
    module = admin_request_view if admin else aluno_view
    route = "/admin/requisicoes" if admin else "/aluno/requisicoes"

    def fake_render(template, **context):
        captured.update(context)
        return "ok"

    monkeypatch.setattr(module, "render_template", fake_render)
    response = client.get(route, query_string=query)
    return response, captured


def _mixed_filter_requests(conn, student):
    frozen_aac, aac_snapshot = _insert_request(
        conn, student, activity_id=1, name="R1 frozen AAC", event_date="2026-05-10"
    )
    frozen_aeu, aeu_snapshot = _insert_request(
        conn, student, activity_id=29, name="R2 frozen AEU", event_date="2026-05-11"
    )
    legacy_aac, _ = _insert_request(
        conn,
        student,
        activity_id=2,
        snapshot=False,
        name="R3 legacy AAC",
        event_date="2026-05-12",
    )
    legacy_aeu, _ = _insert_request(
        conn,
        student,
        activity_id=30,
        snapshot=False,
        name="R4 legacy AEU",
        event_date="2026-05-13",
    )
    _replace_live_identity(
        conn,
        1,
        activity_type=AEU,
        name="R1 LIVE AEU",
        group="R1 LIVE AEU GROUP",
    )
    _replace_live_identity(
        conn,
        29,
        activity_type=AAC,
        name="R2 LIVE AAC",
        group="R2 LIVE AAC GROUP",
    )
    return {
        "frozen_aac": frozen_aac,
        "frozen_aeu": frozen_aeu,
        "legacy_aac": legacy_aac,
        "legacy_aeu": legacy_aeu,
        "aac_payload": json.loads(aac_snapshot.snapshot_json),
        "aeu_payload": json.loads(aeu_snapshot.snapshot_json),
    }


def _progress_payload(student):
    with main.app.app_context():
        return aluno_view._build_aluno_progresso_payload(
            main.get_db_connection(), student["usuario_id"]
        )


def _progress_rows_by_total(payload, expected_total):
    return [row for row in payload["atividades"] if row["total"] == expected_total]


def test_t01_t02_t03_t04_historical_progress_uses_frozen_name_axis_group_and_rule(fc12_env):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        _, prepared = _insert_request(conn, student)
        frozen = json.loads(prepared.snapshot_json)
        _mutate_live_activity(conn)
        conn.commit()

    rows = _progress_rows_by_total(_progress_payload(student), 8.0)
    assert len(rows) == 1
    row = rows[0]
    assert row["nome"] == frozen["nome_exibivel"]
    assert row["tipo_atividade"] == AAC
    assert row["grupo"] == "1"
    assert row["limite"] != "999h total"


def test_t05_t06_current_catalogue_uses_exact_matrix_selected_version(fc12_env):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        _mutate_live_activity(conn)
        conn.execute(
            "UPDATE atividade_versao SET grupo = '7 - EXACT V1', limite_total = 37 WHERE id = 29"
        )
        conn.commit()

    payload = _progress_payload(student)
    exact = [row for row in payload["atividades"] if row["atividade_id"] == 1]
    assert len(exact) == 1
    assert exact[0]["tipo_atividade"] == AAC
    assert exact[0]["grupo"] == "7"
    assert exact[0]["limite"] == "37h total"


def test_t07_t08_t09_t10_student_aggregates_use_snapshot_and_partial_hours(fc12_env):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        _insert_request(conn, student, requested=10, deferred=3, status="Deferida Parcialmente")
        _mutate_live_activity(conn)
        conn.commit()

    _login_student(fc12_env["client"], student)
    response = fc12_env["client"].get("/aluno/dashboard")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "3/200 h" in html
    assert "LIVE MUTATED NAME" not in html

    payload = _progress_payload(student)
    row = _progress_rows_by_total(payload, 3.0)[0]
    assert row["tipo_atividade"] == AAC
    assert row["grupo"] == "1"
    assert row["semestres"]["2026/1"] == 3.0


def test_t11_t12_t13_admin_dashboard_uses_snapshot_numerator_and_matrix_target(fc12_env):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        _insert_request(conn, student, requested=20)
        _mutate_live_activity(conn)
        conn.commit()
        cards, _, _ = dashboard_view._build_admin_dashboard_turma_cards(conn)

    card = next(row for row in cards if row["id"] == student["turma_id"])
    assert card["aac_hours_fmt"] == "20"
    assert card["aeu_hours_fmt"] == "0"
    assert card["aac_pct"] == 10
    assert card["attainment_avg_pct_label"] == "7%"


def test_t14_t15_old_and_new_cohorts_keep_exact_targets_and_frozen_axes(fc12_env):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE matrizes_atividades SET horas_aac_obrigatorias = 220 WHERE id = 1")
        conn.execute("UPDATE matrizes_atividades SET horas_aac_obrigatorias = 310 WHERE id = 2")
        _insert_request(conn, student, requested=31)
        _mutate_live_activity(conn)
        conn.commit()
        cards, _, _ = dashboard_view._build_admin_dashboard_turma_cards(conn)

    old_card = next(row for row in cards if row["id"] == 1)
    new_card = next(row for row in cards if row["id"] == 2)
    assert old_card["aac_applicable"] is True
    assert old_card["aac_hours_fmt"] == "0"
    assert new_card["aac_hours_fmt"] == "31"
    assert new_card["aac_pct"] == 10


def test_t16_true_no_snapshot_retains_legacy_read_compatibility(fc12_env):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        _insert_request(conn, student, requested=6, snapshot=False)
        conn.commit()

    row = _progress_rows_by_total(_progress_payload(student), 6.0)[0]
    assert row["tipo_atividade"] == AAC
    assert row["grupo"] == "1"


@pytest.mark.parametrize("raw", ["{not-json", json.dumps({"schema_version": "future-v2"})])
def test_t17_t18_invalid_snapshot_never_falls_back_to_live_progress(fc12_env, raw):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        req_id, _ = _insert_request(conn, student)
        conn.execute("UPDATE requisicoes SET regra_snapshot_json = ? WHERE id = ?", (raw, req_id))
        _mutate_live_activity(conn)
        conn.commit()

    with pytest.raises(RuntimeError, match="historical.*authority|snapshot",):
        _progress_payload(student)
    _login_student(fc12_env["client"], student)
    assert fc12_env["client"].get("/aluno/progresso?format=json").status_code == 409
    assert fc12_env["client"].get("/aluno/dashboard").status_code == 409


def test_t19_t20_read_surfaces_do_not_mutate_snapshot(fc12_env):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        req_id, prepared = _insert_request(conn, student)
        before = prepared.snapshot_json
        conn.commit()

    _progress_payload(student)
    _login_student(fc12_env["client"], student)
    assert fc12_env["client"].get("/aluno/dashboard").status_code == 200
    with main.app.app_context():
        after = main.get_db_connection().execute(
            "SELECT regra_snapshot_json FROM requisicoes WHERE id = ?", (req_id,)
        ).fetchone()["regra_snapshot_json"]
    assert after == before


def test_t21_same_legacy_activity_versions_do_not_collapse_into_live_rule(fc12_env):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        _insert_request(conn, student, requested=4, name="V1 request")
        payload = json.loads(
            conn.execute(
                "SELECT regra_snapshot_json FROM requisicoes WHERE nome_evento = 'V1 request'"
            ).fetchone()["regra_snapshot_json"]
        )
        payload.update(
            atividade_versao_id=999,
            atividade_versao_numero=99,
            grupo="8 - HISTORICAL V2",
            limite_total=88,
            nome_exibivel="Historical V2 name",
        )
        conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, nome_evento, data_evento, horas_solicitadas,
                status, data_solicitacao, atividade_versao_id,
                codigo_normativo_snapshot, regra_snapshot_json
            ) VALUES (?, 1, 'V2 request', '2026-05-11', 5, 'Deferida',
                      '2026-05-11 10:00:00', 999, ?, ?)
            """,
            (student["aluno_id"], payload["codigo_normativo"], json.dumps(payload)),
        )
        conn.commit()

    rows = [row for row in _progress_payload(student)["atividades"] if row["total"] > 0]
    assert sorted(row["total"] for row in rows) == [4.0, 5.0]
    assert len({row["limite"] for row in rows}) == 2


def test_t22_t23_snapshot_name_and_outside_catalogue_remain_visible(fc12_env):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        _, prepared = _insert_request(conn, student, requested=9)
        frozen_name = json.loads(prepared.snapshot_json)["nome_exibivel"]
        conn.execute("DELETE FROM matriz_atividade_versao_item WHERE matriz_id = 2 AND atividade_versao_id = 29")
        _mutate_live_activity(conn)
        conn.commit()

    row = _progress_rows_by_total(_progress_payload(student), 9.0)[0]
    assert row["nome"] == frozen_name
    assert row["tipo_atividade"] == AAC
    _login_student(fc12_env["client"], student)
    student_list = fc12_env["client"].get("/aluno/requisicoes").get_data(as_text=True)
    assert frozen_name in student_list
    assert "LIVE MUTATED NAME" not in student_list
    _login_admin(fc12_env["client"])
    admin_list = fc12_env["client"].get("/admin/requisicoes").get_data(as_text=True)
    assert frozen_name in admin_list


def test_t24_display_flag_cannot_change_academic_authority(fc12_env, monkeypatch):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        _insert_request(conn, student, requested=7)
        _mutate_live_activity(conn)
        conn.commit()
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", "0")
    off = _progress_payload(student)
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", "1")
    on = _progress_payload(student)
    assert off == on
    assert _progress_rows_by_total(on, 7.0)[0]["tipo_atividade"] == AAC


def test_t25_t26_t27_created_snapshot_reaches_all_three_read_surfaces(fc12_env):
    student = fc12_env["student"]
    _login_student(fc12_env["client"], student)
    response = fc12_env["client"].post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": "1",
            "nome_evento": "FC12 E2E",
            "data_evento": "2026-05-12",
            "horas_solicitadas": "12",
            "observacao": "FC12",
        },
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        req_id = conn.execute(
            "SELECT id FROM requisicoes WHERE nome_evento = 'FC12 E2E'"
        ).fetchone()["id"]
        conn.commit()
    _login_admin(fc12_env["client"])
    processed = fc12_env["client"].post(
        f"/admin/processar_requisicao/{req_id}",
        data={"status": "Deferida", "observacao": "FC12 E2E"},
    )
    assert processed.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        _mutate_live_activity(conn)
        conn.commit()
        cards, _, _ = dashboard_view._build_admin_dashboard_turma_cards(conn)
    assert _progress_rows_by_total(_progress_payload(student), 12.0)[0]["tipo_atividade"] == AAC
    _login_student(fc12_env["client"], student)
    assert fc12_env["client"].get("/aluno/dashboard").status_code == 200
    assert next(row for row in cards if row["id"] == student["turma_id"])["aac_hours_fmt"] == "12"


def test_t28_t29_mixed_snapshot_and_legacy_rows_aggregate_without_conversion(fc12_env):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        _insert_request(conn, student, requested=4)
        _insert_request(conn, student, requested=6, snapshot=False, name="legacy")
        conn.commit()
    rows = [row for row in _progress_payload(student)["atividades"] if row["total"] > 0]
    assert sum(row["total"] for row in rows) == 10


def test_admin_cohort_student_totals_use_historical_snapshot(fc12_env, monkeypatch):
    student = fc12_env["student"]
    captured = {}
    with main.app.app_context():
        conn = main.get_db_connection()
        _insert_request(conn, student, requested=13)
        _mutate_live_activity(conn)
        conn.commit()

    def fake_render(template, **context):
        captured.update(context)
        return "ok"

    monkeypatch.setattr(cohort_view, "render_template", fake_render)
    _login_admin(fc12_env["client"])
    response = fc12_env["client"].get(f"/admin/turma/{student['turma_id']}")
    assert response.status_code == 200
    target = next(row for row in captured["alunos"] if row["usuario_id"] == student["usuario_id"])
    assert target["total_aac"] == 13
    assert target["total_ae"] == 0


@pytest.mark.parametrize("admin", [False, True], ids=["student", "admin"])
def test_r01_r06_r10_request_filters_use_effective_historical_identity(
    fc12_env, monkeypatch, admin
):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        request_ids = _mixed_filter_requests(conn, student)
        conn.commit()

    if admin:
        _login_admin(fc12_env["client"])
    else:
        _login_student(fc12_env["client"], student)

    expected = {
        AAC: {request_ids["frozen_aac"], request_ids["legacy_aac"]},
        AEU: {request_ids["frozen_aeu"], request_ids["legacy_aeu"]},
    }
    for activity_type, expected_ids in expected.items():
        response, context = _capture_request_list(
            fc12_env["client"],
            monkeypatch,
            admin=admin,
            query={"tipo": activity_type},
        )
        assert response.status_code == 200
        actual_ids = [row["id"] for row in context["requisicoes"]]
        assert set(actual_ids) == expected_ids
        assert len(actual_ids) == len(expected_ids)
        assert context["total"] == len(expected_ids)

    response, context = _capture_request_list(
        fc12_env["client"], monkeypatch, admin=admin, query={}
    )
    assert response.status_code == 200
    assert {row["id"] for row in context["requisicoes"]} == {
        request_ids["frozen_aac"],
        request_ids["frozen_aeu"],
        request_ids["legacy_aac"],
        request_ids["legacy_aeu"],
    }
    assert context["total"] == 4

    sort_param = "s" if admin else "sort"
    response, context = _capture_request_list(
        fc12_env["client"],
        monkeypatch,
        admin=admin,
        query={sort_param: "tipo_atividade", "dir": "asc"},
    )
    assert response.status_code == 200
    assert [row["tipo_atividade"] for row in context["requisicoes"]] == [
        AAC,
        AAC,
        AEU,
        AEU,
    ]


@pytest.mark.parametrize("admin", [False, True], ids=["student", "admin"])
def test_r07_invalid_approved_snapshot_never_uses_live_filter_type(
    fc12_env, monkeypatch, admin
):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        req_id, _ = _insert_request(conn, student, activity_id=1)
        conn.execute(
            "UPDATE requisicoes SET regra_snapshot_json = '{not-json' WHERE id = ?",
            (req_id,),
        )
        _replace_live_identity(
            conn,
            1,
            activity_type=AEU,
            name="INVALID LIVE AEU",
            group="INVALID LIVE AEU GROUP",
        )
        conn.commit()

    if admin:
        _login_admin(fc12_env["client"])
    else:
        _login_student(fc12_env["client"], student)

    for activity_type in (AAC, AEU):
        response, _ = _capture_request_list(
            fc12_env["client"],
            monkeypatch,
            admin=admin,
            query={"tipo": activity_type},
        )
        assert response.status_code == 409


@pytest.mark.parametrize("admin", [False, True], ids=["student", "admin"])
def test_r08_historical_filter_precedes_pagination_and_count(fc12_env, monkeypatch, admin):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        request_ids = _mixed_filter_requests(conn, student)
        conn.commit()

    if admin:
        _login_admin(fc12_env["client"])
    else:
        _login_student(fc12_env["client"], student)

    expected_pages = (request_ids["legacy_aac"], request_ids["frozen_aac"])
    for page, expected_id in enumerate(expected_pages, start=1):
        response, context = _capture_request_list(
            fc12_env["client"],
            monkeypatch,
            admin=admin,
            query={"tipo": AAC, "page": str(page), "per_page": "1"},
        )
        assert response.status_code == 200
        assert [row["id"] for row in context["requisicoes"]] == [expected_id]
        assert context["total"] == 2
        assert context["total_pages"] == 2


@pytest.mark.parametrize("admin", [False, True], ids=["student", "admin"])
def test_r09_frozen_group_name_and_search_drive_academic_filters(
    fc12_env, monkeypatch, admin
):
    student = fc12_env["student"]
    with main.app.app_context():
        conn = main.get_db_connection()
        req_id, prepared = _insert_request(conn, student, activity_id=1)
        frozen = json.loads(prepared.snapshot_json)
        _replace_live_identity(
            conn,
            1,
            activity_type=AEU,
            name="R9 LIVE NAME",
            group="R9 LIVE GROUP",
        )
        conn.commit()

    if admin:
        _login_admin(fc12_env["client"])
    else:
        _login_student(fc12_env["client"], student)

    for query in (
        {"grupo": frozen["grupo"]},
        {"atividade": frozen["nome_exibivel"]},
        {"q": frozen["nome_exibivel"]},
    ):
        response, context = _capture_request_list(
            fc12_env["client"], monkeypatch, admin=admin, query=query
        )
        assert response.status_code == 200
        assert [row["id"] for row in context["requisicoes"]] == [req_id]
        assert context["total"] == 1


def test_t30_structural_census_classifies_every_request_activity_sql_owner():
    academic_terms = (
        "tipo_atividade",
        "grupo",
        "nome",
        "limite_horas",
        "tem_limitacao",
        "tipo_limitacao",
    )
    expected = {
        ("app/activity_catalog.py", "get_legacy_map_list"): "CURRENT_CATALOGUE_INPUT",
        ("app/auth.py", "get_admin_permission_requirement"): "NON_ACADEMIC",
        ("app/db.py", "init_db"): "NON_ACADEMIC",
        ("app/versioning/request_history.py", "list_approved_request_history"): "VALID_SNAPSHOT_HISTORICAL_AUTHORITY",
        ("app/views/admin/atividades.py", "admin_deletar_atividade"): "NON_ACADEMIC",
        ("app/views/admin/dashboard.py", "admin_dashboard"): "NON_ACADEMIC",
        ("app/views/admin/requisicoes.py", "admin_importar_requisicoes"): "CURRENT_CATALOGUE_INPUT",
        ("app/views/admin/requisicoes.py", "admin_requisicoes"): "VALID_SNAPSHOT_HISTORICAL_AUTHORITY",
        ("app/views/admin/requisicoes.py", "admin_nova_requisicao"): "CURRENT_CATALOGUE_INPUT",
        ("app/views/admin/requisicoes.py", "admin_editar_requisicao"): "CURRENT_CATALOGUE_INPUT",
        ("app/views/admin/requisicoes.py", "admin_detalhes_requisicao"): "PRESENTATION_ONLY",
        ("app/views/admin/requisicoes.py", "admin_api_requisicao"): "PRESENTATION_ONLY",
        ("app/views/admin/requisicoes.py", "admin_processar_requisicao"): "VALID_SNAPSHOT_HISTORICAL_AUTHORITY",
        ("app/views/aluno.py", "_build_aluno_progresso_payload"): "VALID_SNAPSHOT_HISTORICAL_AUTHORITY",
        ("app/views/aluno.py", "aluno_dashboard"): "VALID_SNAPSHOT_HISTORICAL_AUTHORITY",
        ("app/views/aluno.py", "aluno_minhas_requisicoes"): "VALID_SNAPSHOT_HISTORICAL_AUTHORITY",
        ("app/views/aluno.py", "aluno_requisicao_detalhe"): "PRESENTATION_ONLY",
    }
    discovered = {}
    calls_by_owner = {}

    for path in sorted(Path("app").rglob("*.py")):
        relative = path.as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            string_literals = [
                item.value
                for item in ast.walk(node)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            request_activity_text = "\n".join(string_literals).casefold()
            if (
                "requisicoes" not in request_activity_text
                or "atividades" not in request_activity_text
                or not any(term in request_activity_text for term in academic_terms)
            ):
                continue
            key = (relative, node.name)
            discovered[key] = expected.get(key, "UNCLASSIFIED")
            calls_by_owner[key] = {
                item.func.id
                if isinstance(item.func, ast.Name)
                else item.func.attr
                for item in ast.walk(node)
                if isinstance(item, ast.Call)
                and isinstance(item.func, (ast.Name, ast.Attribute))
            }

    assert discovered == expected
    assert "filter_historical_request_rows" in calls_by_owner[
        ("app/views/aluno.py", "aluno_minhas_requisicoes")
    ]
    assert "filter_historical_request_rows" in calls_by_owner[
        ("app/views/admin/requisicoes.py", "admin_requisicoes")
    ]
    assert "read_requisicao_snapshot_for_processing" in calls_by_owner[
        ("app/views/admin/requisicoes.py", "admin_processar_requisicao")
    ]
