import pytest
from flask import Flask, template_rendered
import main
from tests.canonical_request_test_support import create_admin_request, login_admin, login_student
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def pagination_client(tmp_path):
    with isolated_versioned_app_env(tmp_path, "pagination.db") as env:
        yield env["client"]


def test_admin_requisicoes_paginated(pagination_client):
    app: Flask = main.app
    login_admin(pagination_client)
    r = pagination_client.get("/admin/requisicoes?page=1&per_page=1")
    assert r.status_code == 200


def test_admin_alunos_turmas_paginated(pagination_client):
    app: Flask = main.app
    login_admin(pagination_client)
    r1 = pagination_client.get("/admin/alunos?page=1&per_page=2")
    r2 = pagination_client.get("/admin/turmas?page=1&per_page=2")
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_aluno_minhas_requisicoes_paginated(pagination_client):
    login_student(pagination_client)
    r = pagination_client.get("/aluno/requisicoes?page=1&per_page=5")
    assert r.status_code == 200


def test_aluno_request_uses_canonical_version_identifier_and_fits_long_status(pagination_client):
    login_admin(pagination_client)
    _, request_row = create_admin_request(
        pagination_client,
        "request-grid-design-system",
        version_id=29,
    )
    assert request_row is not None

    with main.app.app_context():
        connection = main.get_db_connection()
        connection.execute(
            """
            UPDATE requisicoes
               SET status = ?, horas_deferidas = ?, data_processamento = ?
             WHERE id = ?
            """,
            ("Deferida Parcialmente", 4, "2026-08-30", request_row["id"]),
        )
        connection.commit()

    login_student(pagination_client)
    response = pagination_client.get("/aluno/requisicoes")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'class="version-identifier aluno-snapshot-chip"' in html
    assert 'class="aluno-activity-name"' in html
    assert "Deferida Parcialmente" in html
    assert "minmax(164px, var(--col-status))" in html
    assert "border-radius:999px; background:var(--surface)" not in html


def test_historical_filter_is_applied_before_count_and_pagination_is_stable(pagination_client):
    login_admin(pagination_client)
    _, first = create_admin_request(pagination_client, "pagination-first", version_id=29)
    _, second = create_admin_request(pagination_client, "pagination-second", version_id=29)
    create_admin_request(pagination_client, "pagination-outside-filter", version_id=30)
    with main.app.app_context():
        activity_name = main.get_db_connection().execute(
            """SELECT b.nome_conceito FROM atividade_versao v
                 JOIN atividade_base b ON b.id=v.atividade_base_id WHERE v.id=29"""
        ).fetchone()[0]
    login_student(pagination_client)

    captured = []

    def receiver(_sender, template, context, **_extra):
        if template.name == "aluno_minhas_requisicoes.html":
            captured.append(context)

    template_rendered.connect(receiver, main.app)
    try:
        page_one = pagination_client.get(
            "/aluno/requisicoes",
            query_string={
                "atividade": activity_name,
                "page": 1,
                "per_page": 1,
                "sort": "data_evento",
                "dir": "asc",
            },
        )
        context_one = captured[-1]
        page_two = pagination_client.get(
            "/aluno/requisicoes",
            query_string={
                "atividade": activity_name,
                "page": 2,
                "per_page": 1,
                "sort": "data_evento",
                "dir": "asc",
            },
        )
        context_two = captured[-1]
    finally:
        template_rendered.disconnect(receiver, main.app)

    assert page_one.status_code == page_two.status_code == 200
    assert context_one["total"] == context_two["total"] == 2
    assert context_one["total_pages"] == context_two["total_pages"] == 2
    assert [row["id"] for row in context_one["requisicoes"]] == [second["id"]]
    assert [row["id"] for row in context_two["requisicoes"]] == [first["id"]]
