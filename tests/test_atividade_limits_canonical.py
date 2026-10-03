"""Canonical per-activity limitation authority (SGAA limitations front).

The observed bug "5 - Atividades especiais (semestral) 170/20" came from the
student dashboard summing approved hours of a whole group and dividing them by
a single limit picked from one catalogue row of that group. The contract fixed
here: a limitation always belongs to one Activity rule (activity + axis +
limits); a semester limit counts only the event's semester; an activity without
a limit never produces a limitation line; admin deferment uses exactly the same
authority.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

import main
from app.versioning.request_history import list_exact_matrix_activity_catalogue
from app.versioning.request_limits import (
    approved_hours_for_activity_rule,
    build_atividade_rule_summary,
)
from tests.canonical_request_test_support import login_admin
from tests.session_support import stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

GROUP5 = "5 - Atividades especiais"
MATRIX1_GROUP = "1 - AAC histórico"


def _row(
    rid,
    base,
    hours,
    *,
    nome=None,
    grupo=GROUP5,
    eixo="AAC",
    status="Deferida",
    data="2026-01-10",
    ls=None,
    lt=None,
):
    return SimpleNamespace(
        request_id=rid,
        atividade_base_id=base,
        atividade_versao_id=base,
        eixo=eixo,
        grupo=grupo,
        nome=nome or f"Atividade {base}",
        status=status,
        approved_hours=hours,
        data_evento=data,
        limite_semestre=ls,
        limite_total=lt,
    )


# --------------------------------------------------------------------- unit


def test_two_different_activities_same_group_never_aggregate():
    rows = [
        _row(1, 100, 15, nome="Visitas técnicas", ls=20),
        _row(2, 200, 30, nome="Prova de inglês ICAO", ls=20),
    ]
    lines = build_atividade_rule_summary(rows, semester_label="2026/1")
    assert {(line.nome, line.consumido, line.limite) for line in lines} == {
        ("Visitas técnicas", 15.0, 20.0),
        ("Prova de inglês ICAO", 30.0, 20.0),
    }
    assert all(line.consumido != 45 for line in lines)


def test_unlimited_activity_never_feeds_a_limited_numerator():
    rows = [
        _row(1, 100, 10, nome="Limitada", ls=20),
        _row(2, 200, 500, nome="Ilimitada", ls=None, lt=None),
    ]
    lines = build_atividade_rule_summary(rows, semester_label="2026/1")
    assert [
        (line.nome, line.consumido, line.limite, line.periodicidade)
        for line in lines
    ] == [("Limitada", 10.0, 20.0, "semestral")]


def test_group5_with_170h_never_becomes_170_over_20():
    rows = [
        _row(1, 1, 40, nome="Cursos de formação profissional", ls=40),
        _row(2, 2, 5, nome="Atividades integrativas", ls=40),
        _row(3, 3, 70, nome="Horas de voo em escola ANAC", ls=None, lt=None),
        _row(4, 4, 30, nome="Estágio extracurricular", ls=None, lt=80),
        _row(5, 5, 25, nome="Visitas técnicas ou cursos coordenados", ls=20),
    ]
    assert sum(row.approved_hours for row in rows) == 170
    lines = build_atividade_rule_summary(rows, semester_label="2026/1")
    assert lines
    assert not any(line.limite == 20 and line.consumido == 170 for line in lines)
    assert not any("Atividades especiais" in line.nome for line in lines)
    assert {(line.nome, line.consumido, line.limite) for line in lines} == {
        ("Cursos de formação profissional", 40.0, 40.0),
        ("Atividades integrativas", 5.0, 40.0),
        ("Estágio extracurricular", 30.0, 80.0),
        ("Visitas técnicas ou cursos coordenados", 25.0, 20.0),
    }


def test_semester_limit_counts_only_the_requested_semester():
    rows = [
        _row(1, 10, 5, nome="ICAO", ls=20, data="2026-03-10"),
        _row(2, 10, 15, nome="ICAO", ls=20, data="2026-08-10"),
        _row(3, 10, 7, nome="ICAO", ls=20, data="2025-09-10"),
    ]
    def consumo(label):
        return [
            (line.consumido, line.limite)
            for line in build_atividade_rule_summary(rows, semester_label=label)
        ]

    assert consumo("2026/2") == [(15.0, 20.0)]
    assert consumo("2026/1") == [(5.0, 20.0)]
    assert consumo("2025/2") == [(7.0, 20.0)]


def test_total_limit_sums_across_semesters():
    rows = [
        _row(1, 20, 10, nome="Estágio", lt=80, data="2025-09-10"),
        _row(2, 20, 15, nome="Estágio", lt=80, data="2026-03-10"),
        _row(3, 20, 5, nome="Estágio", lt=80, data="2026-08-10"),
    ]
    lines = build_atividade_rule_summary(rows, semester_label="2026/2")
    assert [(line.periodicidade, line.consumido, line.limite) for line in lines] == [
        ("total", 30.0, 80.0)
    ]


def test_aac_and_aeu_never_mix_even_for_the_same_base():
    rows = [
        _row(1, 28, 40, nome="Projetos de extensão", eixo="AAC", ls=40, grupo=MATRIX1_GROUP),
        _row(2, 28, 30, nome="Projetos de extensão", eixo="AEU", ls=40, grupo="Extensão"),
    ]
    lines = build_atividade_rule_summary(rows, semester_label="2026/1")
    assert {(line.eixo, line.consumido, line.limite) for line in lines} == {
        ("AAC", 40.0, 40.0),
        ("AEU", 30.0, 40.0),
    }


def test_historical_rule_is_never_replaced_by_the_current_rule():
    rows = [
        _row(1, 50, 10, nome="Trabalho voluntário", lt=40, data="2025-03-10"),
        _row(2, 50, 30, nome="Trabalho voluntário", ls=40, data="2026-08-10"),
    ]
    lines = build_atividade_rule_summary(rows, semester_label="2026/2")
    assert {(line.periodicidade, line.consumido, line.limite) for line in lines} == {
        ("total", 10.0, 40.0),
        ("semestral", 30.0, 40.0),
    }


def test_activity_without_limit_never_appears():
    rows = [
        _row(1, 60, 70, nome="Horas de voo ANAC", ls=None, lt=None),
        _row(2, 61, 80, nome="Filmes/cinema", ls=None, lt=None, status="Deferida Parcialmente"),
    ]
    assert build_atividade_rule_summary(rows, semester_label="2026/1") == []


def test_overflow_keeps_the_real_numerator_and_a_honest_percentage():
    line = build_atividade_rule_summary(
        [_row(1, 70, 25, nome="ICAO", ls=20)], semester_label="2026/1"
    )[0]
    assert (line.consumido, line.limite, line.pct) == (25.0, 20.0, 125)


def test_enforcement_helper_uses_exact_rule_and_event_semester():
    rows = [
        _row(1, 70, 15, nome="ICAO", ls=20, data="2026-03-10"),
        _row(2, 70, 10, nome="ICAO", ls=20, data="2026-02-10", status="Deferida Parcialmente"),
        _row(3, 70, 99, nome="ICAO", ls=20, data="2026-08-10"),
        _row(4, 71, 99, nome="Outra", ls=20, data="2026-03-10"),
        _row(5, 70, 99, nome="ICAO", ls=40, data="2026-03-10"),
        _row(6, 70, 99, nome="ICAO", ls=20, data="2026-03-10", status="Indeferida"),
    ]
    params = dict(atividade_base_id=70, eixo="AAC", limite_semestre=20, limite_total=None)
    assert approved_hours_for_activity_rule(
        rows, **params, semester_label="2026/1"
    ) == 25.0
    assert approved_hours_for_activity_rule(rows, **params) == 124.0
    assert approved_hours_for_activity_rule(
        rows, **params, semester_label="2026/1", exclude_request_id=1
    ) == 10.0


# -------------------------------------------------------------- integration


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "atividade-limits.db") as value:
        login_admin(value["client"])
        yield value


def _student_in_matrix1():
    with main.app.app_context():
        conn = main.get_db_connection()
        email = "aluno.matriz1@example.com"
        conn.execute(
            "INSERT INTO usuarios (nome,email,senha,tipo) VALUES (?,?,?,?)",
            ("Aluno Matriz 1", email, main.hash_password("aluno123"), "aluno"),
        )
        usuario_id = conn.execute(
            "SELECT id FROM usuarios WHERE email=?", (email,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alunos (usuario_id,nome,matricula,email,turma_id,matriz_id,status)"
            " VALUES (?,?,?,?,?,?,?)",
            (usuario_id, "Aluno Matriz 1", "PPA.TESTE.M1", email, 1, 1, "Ativo"),
        )
        aluno_id = conn.execute(
            "SELECT id FROM alunos WHERE usuario_id=?", (usuario_id,)
        ).fetchone()["id"]
        conn.commit()
        return {"usuario_id": usuario_id, "aluno_id": aluno_id}


def _login_student(client, usuario_id):
    with client.session_transaction() as session:
        session.update(user_id=usuario_id, user_type="aluno", user_name="Aluno Matriz 1")
        stamp_auth_version(session)


def _current_semester_date(day=15):
    today = datetime.date.today()
    month = 3 if today.month <= 6 else 9
    return f"{today.year}-{month:02d}-{day:02d}"


def _other_past_semester_date(day=15):
    today = datetime.date.today()
    return f"{today.year - 1}-09-{day:02d}" if today.month <= 6 else f"{today.year - 1}-03-{day:02d}"


def _create_request(client, aluno_id, version_id, nome, data_evento, horas):
    response = client.post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": str(aluno_id),
            "atividade_versao_id": str(version_id),
            "nome_evento": nome,
            "data_evento": data_evento,
            "horas_solicitadas": str(horas),
            "observacao": "limites",
        },
    )
    assert response.status_code == 302
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM requisicoes WHERE nome_evento=?", (nome,)
        ).fetchone()
    assert row is not None
    return dict(row)


def _approve_direct(req_id, horas=None):
    """Historical/admin approval without re-entering the deferment guard."""
    with main.app.app_context():
        conn = main.get_db_connection()
        if horas is None:
            conn.execute(
                "UPDATE requisicoes SET status='Deferida', horas_deferidas=NULL,"
                " data_processamento=datetime('now') WHERE id=?",
                (req_id,),
            )
        else:
            conn.execute(
                "UPDATE requisicoes SET status='Deferida Parcialmente', horas_deferidas=?,"
                " data_processamento=datetime('now') WHERE id=?",
                (horas, req_id),
            )
        conn.commit()


def _process(client, req_id, *, status="Deferida", horas=None):
    data = {"status": status}
    if horas is not None:
        data["horas_deferidas"] = str(horas)
    return client.post(f"/admin/processar_requisicao/{req_id}", data=data)


def _status(req_id):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT status FROM requisicoes WHERE id=?", (req_id,)
        ).fetchone()["status"]


def _limits_section(html, heading):
    assert heading in html, heading
    return html.split(heading, 1)[1].split("</section>", 1)[0]


def test_dashboard_renders_one_line_per_activity_rule(env):
    client = env["client"]
    student = _student_in_matrix1()
    today = _current_semester_date()
    acad_heading = "Limitações - Acadêmicas Complementares"

    v1 = _create_request(client, student["aluno_id"], 1, "LIM v1 overflow", today, 45)
    _approve_direct(v1["id"])
    v3 = _create_request(client, student["aluno_id"], 3, "LIM v3", today, 10)
    _approve_direct(v3["id"])
    v2 = _create_request(client, student["aluno_id"], 2, "LIM v2 total", today, 30)
    _approve_direct(v2["id"])

    _login_student(client, student["usuario_id"])
    html = client.get("/aluno/dashboard").get_data(as_text=True)
    section = _limits_section(html, acad_heading)

    assert "Curso de curta duração em aviação (semestral)" in section
    assert "45/40" in section
    assert "Participação em eventos técnico-científicos (semestral)" in section
    assert "10/20" in section
    assert "Visitas técnicas ou culturais (total)" in section
    assert "30/100" in section
    assert MATRIX1_GROUP not in section
    assert "data-pct=\"112\"" in section


def test_dashboard_group5_170h_regression_has_no_aggregate_line(env):
    client = env["client"]
    student = _student_in_matrix1()
    today = _current_semester_date()
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE atividade_versao SET grupo=? WHERE id IN (1,2,3)", (GROUP5,))
        conn.commit()

    r1 = _create_request(client, student["aluno_id"], 1, "G5 v1", today, 45)
    r3 = _create_request(client, student["aluno_id"], 3, "G5 v3", today, 25)
    r2 = _create_request(client, student["aluno_id"], 2, "G5 v2", today, 100)
    for row in (r1, r3, r2):
        _approve_direct(row["id"])
    with main.app.app_context():
        total = main.get_db_connection().execute(
            "SELECT SUM(CASE WHEN status='Deferida' THEN horas_solicitadas"
            " WHEN status='Deferida Parcialmente' THEN horas_deferidas ELSE 0 END)"
            " FROM requisicoes WHERE aluno_id=?",
            (student["aluno_id"],),
        ).fetchone()[0]
    assert total == 170.0

    _login_student(client, student["usuario_id"])
    html = client.get("/aluno/dashboard").get_data(as_text=True)
    section = _limits_section(html, "Limitações - Acadêmicas Complementares")

    assert "170/20" not in section
    assert GROUP5 not in html
    assert "45/40" in section
    assert "25/20" in section
    assert "100/100" in section
    assert "data-pct=\"125\"" in section


def test_dashboard_hides_activities_without_limits(env):
    client = env["client"]
    student = _student_in_matrix1()
    today = _current_semester_date()
    unlimited = _create_request(client, student["aluno_id"], 4, "SEM limite", today, 50)
    _approve_direct(unlimited["id"])

    _login_student(client, student["usuario_id"])
    html = client.get("/aluno/dashboard").get_data(as_text=True)
    section = _limits_section(html, "Limitações - Acadêmicas Complementares")
    assert "Monitoria acadêmica supervisionada" not in section


def test_admin_deferment_enforces_the_same_activity_semester_cap(env):
    client = env["client"]
    student = _student_in_matrix1()
    today = _current_semester_date()

    first = _create_request(client, student["aluno_id"], 3, "CAP first", today, 15)
    assert _process(client, first["id"]).status_code == 302
    assert _status(first["id"]) == "Deferida"

    second = _create_request(client, student["aluno_id"], 3, "CAP second", today, 10)
    assert _process(client, second["id"]).status_code == 302
    assert _status(second["id"]) == "Pendente"


def test_admin_deferment_never_counts_another_activity_of_the_group(env):
    client = env["client"]
    student = _student_in_matrix1()
    today = _current_semester_date()

    big = _create_request(client, student["aluno_id"], 2, "GRP big", today, 90)
    assert _process(client, big["id"]).status_code == 302
    assert _status(big["id"]) == "Deferida"

    small = _create_request(client, student["aluno_id"], 3, "GRP small", today, 18)
    assert _process(client, small["id"]).status_code == 302
    assert _status(small["id"]) == "Deferida"


def test_admin_deferment_semester_is_the_event_semester_not_today(env):
    client = env["client"]
    student = _student_in_matrix1()
    current = _current_semester_date()
    past = _other_past_semester_date()

    past_first = _create_request(client, student["aluno_id"], 3, "SEM past 1", past, 15)
    assert _process(client, past_first["id"]).status_code == 302
    assert _status(past_first["id"]) == "Deferida"

    current_req = _create_request(client, student["aluno_id"], 3, "SEM current", current, 10)
    assert _process(client, current_req["id"]).status_code == 302
    assert _status(current_req["id"]) == "Deferida"

    past_second = _create_request(client, student["aluno_id"], 3, "SEM past 2", past, 10)
    assert _process(client, past_second["id"]).status_code == 302
    assert _status(past_second["id"]) == "Pendente"


def test_admin_deferment_uses_frozen_rule_not_live_version(env):
    client = env["client"]
    student = _student_in_matrix1()
    today = _current_semester_date()

    req = _create_request(client, student["aluno_id"], 3, "FROZEN", today, 25)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE atividade_versao SET limite_semestre=999 WHERE id=3")
        conn.commit()

    assert _process(client, req["id"]).status_code == 302
    assert _status(req["id"]) == "Pendente"


def test_admin_processing_page_shows_the_frozen_limitation_banner(env):
    client = env["client"]
    student = _student_in_matrix1()
    limited = _create_request(client, student["aluno_id"], 3, "BANNER limited", _current_semester_date(), 10)
    unlimited = _create_request(client, student["aluno_id"], 4, "BANNER free", _current_semester_date(), 10)

    limited_html = client.get(f"/admin/processar_requisicao/{limited['id']}").get_data(as_text=True)
    assert "Esta atividade tem limitação" in limited_html
    assert "limite = 20.0h/semestre" in limited_html

    unlimited_html = client.get(f"/admin/processar_requisicao/{unlimited['id']}").get_data(as_text=True)
    assert "Esta atividade tem limitação" not in unlimited_html


def test_matrices_resolve_their_own_frozen_rules(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        matrix1 = {
            row["atividade_base_id"]: row
            for row in list_exact_matrix_activity_catalogue(conn, 1)
        }
        matrix2 = {
            row["atividade_base_id"]: row
            for row in list_exact_matrix_activity_catalogue(conn, 2)
        }
    assert matrix1[1]["atividade_versao_id"] == 2
    assert (matrix1[1]["limite_horas_total"], matrix1[1]["limite_horas_semestral"]) == (100.0, None)
    assert matrix2[1]["atividade_versao_id"] == 29
    assert (matrix2[1]["limite_horas_total"], matrix2[1]["limite_horas_semestral"]) == (None, None)
    assert (matrix1[2]["limite_horas_semestral"], matrix1[2]["limite_horas_total"]) == (40.0, None)
    assert (matrix1[3]["limite_horas_semestral"], matrix1[3]["limite_horas_total"]) == (20.0, None)
