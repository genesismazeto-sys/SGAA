from __future__ import annotations

import uuid

import pytest

import main
from app.views.admin import atividades as atividades_view
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "activity_list_base_identity.db") as isolated:
        yield isolated


def _login_admin(client):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE usuarios SET tipo='admin', nivel_acesso='admin_total' WHERE id=1"
        )
        conn.commit()
    with client.session_transaction() as session:
        session.update(user_id=1, user_type="admin", user_name="Admin")


def _seed_base(name: str, versions: list[dict]) -> tuple[int, list[int]]:
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base(nome_conceito,descricao,status) "
            "VALUES(?,?,'ativo') RETURNING id",
            (name, f"Descrição de {name}"),
        ).fetchone()[0]
        version_ids = []
        for number, values in enumerate(versions, start=1):
            version_ids.append(
                conn.execute(
                    "INSERT INTO atividade_versao"
                    "(atividade_base_id,eixo,grupo,limite_total,limite_semestre,"
                    "documentos_json,numero_versao,status) VALUES(?,?,?,?,?,?,?,?) "
                    "RETURNING id",
                    (
                        base_id,
                        values.get("eixo", "AAC"),
                        values.get("grupo", "1 - Base identity"),
                        values.get("limite_total"),
                        values.get("limite_semestre"),
                        values.get("documentos_json", "[]"),
                        values.get("numero_versao", number),
                        values.get("status", "ativa"),
                    ),
                ).fetchone()[0]
            )
        conn.commit()
    return base_id, version_ids


def _capture_list(client, monkeypatch, query: str) -> dict:
    captured = {}

    def capture(template_name, **context):
        captured.update(context)
        captured["template_name"] = template_name
        return "captured"

    monkeypatch.setattr(atividades_view, "render_template", capture)
    response = client.get(f"/admin/atividades?{query}")
    assert response.status_code == 200
    assert captured["template_name"] == "admin_atividades.html"
    captured["rows"] = [dict(row) for row in captured["atividades"]]
    return captured


def _rows_for_name(client, monkeypatch, name: str, extra: str = "") -> dict:
    query = f"nome={name.replace(' ', '+')}"
    if extra:
        query += f"&{extra}"
    return _capture_list(client, monkeypatch, query)


def test_catalog_projection_sql_is_base_granular_and_uses_highest_version():
    sql = " ".join(atividades_view._canonical_activity_rows_sql().split()).lower()

    assert "from atividade_base b join atividade_versao v" in sql
    assert "where current.atividade_base_id = b.id" in sql
    assert "order by current.numero_versao desc, current.id desc" in sql
    assert "count(*) from atividade_versao counted" in sql
    assert "distinct" not in sql


def test_one_base_one_version_produces_exactly_one_catalog_row(env, monkeypatch):
    client = env["client"]
    _login_admin(client)
    name = f"Single {uuid.uuid4().hex}"
    base_id, _ = _seed_base(name, [{}])

    result = _rows_for_name(client, monkeypatch, name)

    assert len(result["rows"]) == 1
    assert result["rows"][0]["base_id"] == base_id
    assert result["rows"][0]["total_versoes"] == 1


def test_two_same_axis_versions_produce_one_row_with_count_two(env, monkeypatch):
    client = env["client"]
    _login_admin(client)
    name = f"Same Axis {uuid.uuid4().hex}"
    _seed_base(name, [{"grupo": "1 - Old"}, {"grupo": "2 - Current"}])

    rows = _rows_for_name(client, monkeypatch, name)["rows"]

    assert len(rows) == 1
    assert rows[0]["total_versoes"] == 2
    assert rows[0]["grupo"] == "2 - Current"


def test_conferencias_uses_highest_version_summary_and_detail_keeps_history(
    env, monkeypatch
):
    client = env["client"]
    _login_admin(client)
    name = f"Conferências {uuid.uuid4().hex}"
    base_id, (v1, v2) = _seed_base(
        name,
        [
            {"eixo": "AAC", "grupo": "1 - Histórico", "limite_total": 20},
            {"eixo": "AEU", "grupo": "NA", "limite_semestre": 40},
        ],
    )

    rows = _rows_for_name(client, monkeypatch, name)["rows"]

    assert len(rows) == 1
    assert rows[0]["id"] == v2
    assert rows[0]["base_id"] == base_id
    assert rows[0]["tipo_atividade"] == "Extensão Universitária"
    assert rows[0]["grupo"] == "NA"
    assert rows[0]["total_versoes"] == 2
    assert rows[0]["limite_horas_semestral"] == 40
    assert rows[0]["limite_horas_total"] is None

    monkeypatch.undo()
    detail = client.get(f"/admin/catalogo-versoes/{base_id}").get_data(as_text=True)
    assert f'data-version-id="{v1}"' in detail
    assert f'data-version-id="{v2}"' in detail


def test_multiple_active_versions_do_not_multiply_catalog_rows(env, monkeypatch):
    client = env["client"]
    _login_admin(client)
    name = f"Multiple Active {uuid.uuid4().hex}"
    _seed_base(name, [{"status": "ativa"}, {"status": "ativa"}])

    rows = _rows_for_name(client, monkeypatch, name)["rows"]

    assert len(rows) == 1
    assert rows[0]["total_versoes"] == 2


def test_tipo_filter_matches_latest_summary_not_historical_versions(env, monkeypatch):
    client = env["client"]
    _login_admin(client)
    name = f"Tipo Latest {uuid.uuid4().hex}"
    _seed_base(name, [{"eixo": "AAC"}, {"eixo": "AEU", "grupo": "NA"}])

    aeu = _rows_for_name(
        client, monkeypatch, name, "tipo=Extens%C3%A3o+Universit%C3%A1ria"
    )["rows"]
    aac = _rows_for_name(
        client, monkeypatch, name, "tipo=Acad%C3%AAmica+Complementar"
    )["rows"]

    assert len(aeu) == 1
    assert aac == []


def test_grupo_filter_matches_latest_summary_not_historical_versions(env, monkeypatch):
    client = env["client"]
    _login_admin(client)
    name = f"Grupo Latest {uuid.uuid4().hex}"
    _seed_base(name, [{"grupo": "71 - Old"}, {"grupo": "72 - Current"}])

    current = _rows_for_name(client, monkeypatch, name, "grupo=72+-+Current")["rows"]
    historical = _rows_for_name(client, monkeypatch, name, "grupo=71+-+Old")["rows"]

    assert len(current) == 1
    assert historical == []


def test_name_filter_remains_base_owned(env, monkeypatch):
    client = env["client"]
    _login_admin(client)
    token = uuid.uuid4().hex
    wanted = f"Base Owned {token}"
    _seed_base(wanted, [{"grupo": "Version metadata without search token"}])
    _seed_base(f"Other {uuid.uuid4().hex}", [{"grupo": token}])

    rows = _rows_for_name(client, monkeypatch, wanted)["rows"]

    assert [row["nome"] for row in rows] == [wanted]

    monkeypatch.undo()
    html = client.get(f"/admin/atividades?nome={wanted.replace(' ', '+')}").get_data(
        as_text=True
    )
    assert f'data-search-text="{wanted}"' in html


@pytest.mark.parametrize(
    "sort_field,direction,first_spec,second_spec",
    [
        ("nome", "asc", {"name": "A"}, {"name": "Z"}),
        ("tipo_atividade", "asc", {"eixo": "AAC"}, {"eixo": "AEU", "grupo": "NA"}),
        ("grupo", "asc", {"grupo": "1 - A"}, {"grupo": "9 - Z"}),
        ("versoes", "desc", {"count": 2}, {"count": 1}),
        ("limitacao", "desc", {"limite_total": 50}, {}),
    ],
)
def test_sorting_projected_fields_preserves_one_row_per_base(
    env, monkeypatch, sort_field, direction, first_spec, second_spec
):
    client = env["client"]
    _login_admin(client)
    token = uuid.uuid4().hex

    def create(label, spec):
        versions = [
            {
                "eixo": spec.get("eixo", "AAC"),
                "grupo": spec.get("grupo", "5 - Sort"),
                "limite_total": spec.get("limite_total"),
            }
            for _ in range(spec.get("count", 1))
        ]
        name = f"{token} {spec.get('name', label)}"
        return _seed_base(name, versions)[0]

    first_id = create("First", first_spec)
    second_id = create("Second", second_spec)

    rows = _rows_for_name(
        client, monkeypatch, token, f"s={sort_field}&dir={direction}"
    )["rows"]

    assert [row["base_id"] for row in rows] == [first_id, second_id]
    assert len({row["base_id"] for row in rows}) == 2


def test_pagination_total_counts_filtered_bases_not_versions(env, monkeypatch):
    client = env["client"]
    _login_admin(client)
    token = f"Page Total {uuid.uuid4().hex}"
    _seed_base(f"{token} A", [{}, {}])
    _seed_base(f"{token} B", [{}])

    result = _rows_for_name(client, monkeypatch, token, "page=1&per_page=1&s=nome")

    assert result["total"] == 2
    assert result["total_pages"] == 2
    assert len(result["rows"]) == 1


def test_per_page_one_cannot_split_one_base_across_pages(env, monkeypatch):
    client = env["client"]
    _login_admin(client)
    token = f"Page Identity {uuid.uuid4().hex}"
    base_a, _ = _seed_base(f"{token} A", [{}, {}])
    base_b, _ = _seed_base(f"{token} B", [{}])

    page_1 = _rows_for_name(client, monkeypatch, token, "page=1&per_page=1&s=nome")
    page_2 = _rows_for_name(client, monkeypatch, token, "page=2&per_page=1&s=nome")

    assert [row["base_id"] for row in page_1["rows"]] == [base_a]
    assert [row["base_id"] for row in page_2["rows"]] == [base_b]
    assert page_1["total"] == page_2["total"] == 2


def test_catalog_view_action_targets_base_detail_not_representative_version(env):
    client = env["client"]
    _login_admin(client)
    name = f"Detail Navigation {uuid.uuid4().hex}"
    base_id, _ = _seed_base(name, [{}, {}])

    html = client.get(f"/admin/atividades?nome={name.replace(' ', '+')}").get_data(
        as_text=True
    )

    assert f'data-base-id="{base_id}"' in html
    view_action = html.split("if (action === 'view'){", 1)[1].split(
        "} else if (action === 'edit'){", 1
    )[0]
    assert "window.location.href" in view_action
    assert "/admin/catalogo-versoes/0" in view_action
    assert "/versoes/0/editar" not in view_action


def test_safe_delete_route_updates_single_base_row_count_two_to_one(env, monkeypatch):
    client = env["client"]
    _login_admin(client)
    name = f"Delete Integration {uuid.uuid4().hex}"
    base_id, (v1, v2) = _seed_base(name, [{"status": "ativa"}, {"status": "rascunho"}])
    with main.app.app_context():
        conn = main.get_db_connection()
        v1_before = dict(conn.execute("SELECT * FROM atividade_versao WHERE id=?", (v1,)).fetchone())

    before = _rows_for_name(client, monkeypatch, name)["rows"]
    response = client.post(
        f"/admin/catalogo-versoes/{base_id}/versoes/{v2}/excluir",
        follow_redirects=False,
    )
    after = _rows_for_name(client, monkeypatch, name)["rows"]

    assert response.status_code == 302
    assert len(before) == len(after) == 1
    assert before[0]["total_versoes"] == 2
    assert after[0]["total_versoes"] == 1
    assert after[0]["base_id"] == base_id
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute("SELECT 1 FROM atividade_versao WHERE id=?", (v2,)).fetchone() is None
        assert dict(conn.execute("SELECT * FROM atividade_versao WHERE id=?", (v1,)).fetchone()) == v1_before


def test_deleted_highest_version_number_may_be_reused_by_next_created_version(env):
    client = env["client"]
    _login_admin(client)
    name = f"Number Reuse {uuid.uuid4().hex}"
    base_id, (v1, v2) = _seed_base(name, [{"status": "ativa"}, {"status": "rascunho"}])

    deleted = client.post(
        f"/admin/catalogo-versoes/{base_id}/versoes/{v2}/excluir",
        follow_redirects=False,
    )
    created = client.post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao?from={v1}",
        data={
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "1 - Base identity",
            "nome": name,
            "descricao": f"Descrição de {name}",
            "tipo_limitacao": "",
            "limite_valor": "",
            "ch_por_evento_mode": "",
            "ch_por_evento": "",
            "observacoes": "Nova versão após exclusão",
            "versao_anterior_id": str(v1),
        },
        follow_redirects=False,
    )

    assert deleted.status_code == created.status_code == 302
    with main.app.app_context():
        rows = main.get_db_connection().execute(
            "SELECT id,numero_versao FROM atividade_versao "
            "WHERE atividade_base_id=? ORDER BY numero_versao",
            (base_id,),
        ).fetchall()
    assert len(rows) == 2
    assert (rows[0]["id"], rows[0]["numero_versao"]) == (v1, 1)
    assert rows[1]["id"] != v2
    assert rows[1]["numero_versao"] == 2
