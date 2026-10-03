from __future__ import annotations

import json
import re
import uuid

import pytest

import main
from app import activity_catalog
from app.activity_catalog import describe_activity_version_dependencies
from tests.canonical_request_test_support import create_admin_request
from tests.versioned_test_support import isolated_versioned_app_env
from utils import messages
from tests.session_support import stamp_auth_version


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "activity_version_safe_delete.db") as isolated:
        yield isolated


def _login(client, *, user_id=1, level="admin_total"):
    with main.app.app_context():
        conn = main.get_db_connection()
        existing = conn.execute("SELECT id FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO usuarios (id,nome,email,senha,tipo,nivel_acesso) "
                "VALUES (?,?,?,?,?,?)",
                (
                    user_id,
                    f"Admin {level}",
                    f"safe-delete-{user_id}@example.com",
                    main.hash_password("test-only"),
                    "admin",
                    level,
                ),
            )
            conn.commit()
        else:
            conn.execute(
                "UPDATE usuarios SET tipo='admin', nivel_acesso=? WHERE id=?",
                (level, user_id),
            )
            conn.commit()
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["user_type"] = "admin"
        session["user_name"] = f"Admin {level}"
        stamp_auth_version(session)


def _seed_base_with_versions(*statuses: str, numbers=None, chained=False):
    """Seed one base; ``chained`` links each version to the previous one."""
    token = uuid.uuid4().hex[:10]
    numbers = numbers or range(1, len(statuses) + 1)
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base(nome_conceito,status) VALUES(?,'ativo') RETURNING id",
            (f"Safe delete {token}",),
        ).fetchone()[0]
        version_ids = []
        for status, number in zip(statuses, numbers):
            predecessor = version_ids[-1] if chained and version_ids else None
            version_ids.append(
                conn.execute(
                    "INSERT INTO atividade_versao"
                    "(atividade_base_id,eixo,grupo,numero_versao,status,versao_anterior_id) "
                    "VALUES(?,'AAC','1 - Safe delete',?,?,?) RETURNING id",
                    (base_id, number, status, predecessor),
                ).fetchone()[0]
            )
        conn.commit()
    return base_id, version_ids


def _post_delete(client, base_id, version_id, *, follow=True):
    return client.post(
        f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/excluir",
        follow_redirects=follow,
    )


def _version(version_id):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT * FROM atividade_versao WHERE id=?", (version_id,)
        ).fetchone()


def _lineage(base_id):
    """(id, numero_versao, versao_anterior_id) in canonical order."""
    with main.app.app_context():
        return [
            tuple(row)
            for row in main.get_db_connection().execute(
                "SELECT id, numero_versao, versao_anterior_id FROM atividade_versao "
                "WHERE atividade_base_id=? ORDER BY numero_versao, id",
                (base_id,),
            ).fetchall()
        ]


def _rows_by_id(base_id):
    with main.app.app_context():
        return {
            row["id"]: dict(row)
            for row in main.get_db_connection().execute(
                "SELECT * FROM atividade_versao WHERE atividade_base_id=?", (base_id,)
            ).fetchall()
        }


def _response_text(response):
    return response.get_data(as_text=True)


def _post_new_version(client, base_id, *, observacoes):
    """Create the next version through the real form (source = latest version)."""
    with main.app.app_context():
        base = main.get_db_connection().execute(
            "SELECT nome_conceito FROM atividade_base WHERE id=?", (base_id,)
        ).fetchone()
    return client.post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao",
        data={
            "tipo_atividade": "Acadêmica Complementar",
            "grupo": "1 - Safe delete",
            "nome": base["nome_conceito"],
            "descricao": "",
            "ch_por_evento_mode": "enabled",
            "ch_por_evento": "4",
            "tipo_limitacao": "semestral",
            "limite_valor": "30",
            "observacoes": observacoes,
            "versao_anterior_id": str(_lineage(base_id)[-1][0]),
        },
        follow_redirects=False,
    )


@pytest.mark.parametrize(
    "status",
    ["rascunho", "ativa", "inativa", "descontinuada", "substituida"],
)
def test_unused_version_is_deleted_regardless_of_lifecycle_status(env, status):
    client = env["client"]
    _login(client)
    base_id, (v1, v2) = _seed_base_with_versions("ativa", status)

    response = _post_delete(client, base_id, v2)

    assert response.status_code == 200
    assert _version(v2) is None
    assert _version(v1) is not None
    assert "Versão excluída definitivamente com sucesso." in _response_text(response)


# ---------------------------------------------------------------------------
# Lineage re-anchoring and canonical renumbering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "deleted_index,expected",
    [
        # v1 -> v2 -> v3, delete v1: old v2 becomes the root v1, old v3 is v2.
        (0, lambda ids: [(ids[1], 1, None), (ids[2], 2, ids[1])]),
        # delete v2: old v3 becomes v2 and points straight at v1.
        (1, lambda ids: [(ids[0], 1, None), (ids[2], 2, ids[0])]),
        # delete v3: nothing to re-anchor or renumber.
        (2, lambda ids: [(ids[0], 1, None), (ids[1], 2, ids[0])]),
    ],
    ids=["first", "intermediate", "last"],
)
def test_delete_reanchors_lineage_renumbers_contiguously_and_next_is_n_plus_1(
    env, deleted_index, expected
):
    client = env["client"]
    _login(client)
    base_id, ids = _seed_base_with_versions("ativa", "inativa", "ativa", chained=True)
    assert _lineage(base_id) == [(ids[0], 1, None), (ids[1], 2, ids[0]), (ids[2], 3, ids[1])]
    before = _rows_by_id(base_id)

    response = _post_delete(client, base_id, ids[deleted_index])

    assert "Versão excluída definitivamente com sucesso." in _response_text(response)
    assert _version(ids[deleted_index]) is None
    survivors = expected(ids)
    assert _lineage(base_id) == survivors
    # Same rows, same ids: only numero_versao / versao_anterior_id may move.
    after = _rows_by_id(base_id)
    assert set(after) == {version_id for version_id, _n, _p in survivors}
    lineage_columns = {"numero_versao", "versao_anterior_id"}
    for version_id, row in after.items():
        unchanged = {k: v for k, v in before[version_id].items() if k not in lineage_columns}
        assert {k: v for k, v in row.items() if k not in lineage_columns} == unchanged
    if deleted_index == 2:
        assert after == {version_id: before[version_id] for version_id in after}

    # The catalogue renders the re-anchored chain as v1 -> v2.
    html = _response_text(client.get(f"/admin/catalogo-versoes/{base_id}"))
    chains = re.findall(r'<li class="version-lineage-chain">(.*?)</li>', html, re.S)
    assert [re.findall(r">v(\d+)<", chain) for chain in chains] == [["1", "2"]]

    # The next created version continues the surviving sequence: v3.
    assert _post_new_version(client, base_id, observacoes="Depois da exclusão").status_code == 302
    final = _lineage(base_id)
    assert [numero for _id, numero, _p in final] == [1, 2, 3]
    assert final[:2] == survivors
    assert final[2][2] == survivors[-1][0]


def test_delete_closes_preexisting_gaps_without_touching_related_records(env):
    client = env["client"]
    _login(client)
    base_id, (v1, selected, v4) = _seed_base_with_versions(
        "ativa", "rascunho", "inativa", numbers=(1, 2, 4)
    )
    _insert_matrix_reference(base_id, v1)
    _insert_request_reference(v1)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO atividade_transicao"
            "(from_atividade_versao_id,to_atividade_versao_id,tipo_transicao) "
            "VALUES(?,?,'mesmo_eixo')",
            (v1, v4),
        )
        conn.commit()
    base_before = _base(base_id)
    related_before = _related_records(base_id, (v1, v4))

    response = _post_delete(client, base_id, selected)

    assert "Versão excluída definitivamente com sucesso." in _response_text(response)
    assert _lineage(base_id) == [(v1, 1, None), (v4, 2, None)]
    assert _base(base_id) == base_before
    assert _related_records(base_id, (v1, v4)) == related_before


def test_predecessor_role_alone_never_blocks_a_delete(env):
    client = env["client"]
    _login(client)
    base_id, (v1, target, successor) = _seed_base_with_versions(
        "ativa", "inativa", "rascunho", chained=True
    )

    response = _post_delete(client, base_id, target)

    text = _response_text(response)
    assert "versão anterior por outra versão" not in text
    assert "Versão excluída definitivamente com sucesso." in text
    assert _lineage(base_id) == [(v1, 1, None), (successor, 2, v1)]


def test_every_successor_of_the_deleted_version_is_reanchored(env):
    client = env["client"]
    _login(client)
    base_id, (v1, target, branch_a, branch_b) = _seed_base_with_versions(
        "ativa", "inativa", "rascunho", "rascunho"
    )
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE atividade_versao SET versao_anterior_id=? WHERE id=?", (v1, target))
        conn.execute(
            "UPDATE atividade_versao SET versao_anterior_id=? WHERE id IN (?,?)",
            (target, branch_a, branch_b),
        )
        conn.commit()

    _post_delete(client, base_id, target)

    assert _lineage(base_id) == [(v1, 1, None), (branch_a, 2, v1), (branch_b, 3, v1)]


# ---------------------------------------------------------------------------
# Real business dependencies block, and the refusal names them
# ---------------------------------------------------------------------------


def _insert_matrix_reference(base_id, version_id):
    token = uuid.uuid4().hex[:8]
    name = f"Matrix {token}"
    with main.app.app_context():
        conn = main.get_db_connection()
        course_id = conn.execute(
            "INSERT INTO cursos(nome,codigo,duracao_periodos,status) "
            "VALUES(?,?,8,'ativo') RETURNING id",
            (f"Course {token}", f"SD{token}"),
        ).fetchone()[0]
        matrix_id = conn.execute(
            "INSERT INTO matrizes_atividades(curso_id,nome,status) "
            "VALUES(?,?,'ativa') RETURNING id",
            (course_id, name),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item"
            "(matriz_id,atividade_base_id,atividade_versao_id) VALUES(?,?,?)",
            (matrix_id, base_id, version_id),
        )
        conn.commit()
    return name


def _insert_request_reference(version_id):
    with main.app.app_context():
        conn = main.get_db_connection()
        request_id = conn.execute(
            "INSERT INTO requisicoes"
            "(atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,regra_snapshot_json) "
            "VALUES(?,'2026-09-07','2026-09-07',1,'Pendente','{}') RETURNING id",
            (version_id,),
        ).fetchone()[0]
        conn.commit()
    return request_id


def _base(base_id):
    with main.app.app_context():
        return dict(
            main.get_db_connection().execute(
                "SELECT * FROM atividade_base WHERE id=?", (base_id,)
            ).fetchone()
        )


def _related_records(base_id, version_ids):
    marks = ",".join("?" for _ in version_ids)
    with main.app.app_context():
        conn = main.get_db_connection()
        return {
            "matrix": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM matriz_atividade_versao_item WHERE atividade_base_id=? ORDER BY id",
                    (base_id,),
                ).fetchall()
            ],
            "requests": [
                dict(row)
                for row in conn.execute(
                    f"SELECT * FROM requisicoes WHERE atividade_versao_id IN ({marks}) ORDER BY id",
                    tuple(version_ids),
                ).fetchall()
            ],
            "transitions": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM atividade_transicao "
                    f"WHERE from_atividade_versao_id IN ({marks}) "
                    f"OR to_atividade_versao_id IN ({marks}) ORDER BY id",
                    (*version_ids, *version_ids),
                ).fetchall()
            ],
        }


@pytest.mark.parametrize("position", [0, 1, 2], ids=["first", "intermediate", "last"])
def test_request_reference_blocks_and_names_the_request(env, position):
    client = env["client"]
    _login(client)
    base_id, ids = _seed_base_with_versions("ativa", "inativa", "ativa", chained=True)
    request_id = _insert_request_reference(ids[position])
    before = _rows_by_id(base_id)

    text = _response_text(_post_delete(client, base_id, ids[position]))

    assert (
        f"Não é possível excluir esta versão porque ela é utilizada pela requisição {request_id}."
        in text
    )
    assert "versão anterior por outra versão" not in text
    assert _rows_by_id(base_id) == before


def test_matrix_selection_blocks_and_names_the_matrix(env):
    client = env["client"]
    _login(client)
    base_id, ids = _seed_base_with_versions("ativa", "ativa", chained=True)
    matrix_name = _insert_matrix_reference(base_id, ids[0])
    before = _rows_by_id(base_id)

    text = _response_text(_post_delete(client, base_id, ids[0]))

    assert (
        f"Não é possível excluir esta versão porque ela é utilizada pela matriz {matrix_name}."
        in text
    )
    assert _rows_by_id(base_id) == before


def test_request_and_matrix_together_are_both_named(env):
    client = env["client"]
    _login(client)
    base_id, (_, target) = _seed_base_with_versions("ativa", "inativa")
    first = _insert_request_reference(target)
    second = _insert_request_reference(target)
    matrix_name = _insert_matrix_reference(base_id, target)

    text = _response_text(_post_delete(client, base_id, target))

    assert (
        "Não é possível excluir esta versão porque ela é utilizada "
        f"pelas requisições {first} e {second} e pela matriz {matrix_name}."
        in text
    )
    assert _version(target) is not None


@pytest.mark.parametrize(
    "request_ids,matrix_names,expected",
    [
        ((2,), (), "pela requisição 2"),
        ((2, 5), (), "pelas requisições 2 e 5"),
        ((), ("01.2025",), "pela matriz 01.2025"),
        ((), ("01.2025", "01.2026"), "pelas matrizes 01.2025 e 01.2026"),
        ((25,), ("01.2025",), "pela requisição 25 e pela matriz 01.2025"),
        (
            (1, 2, 3, 4, 5, 6, 7),
            (),
            "pelas requisições 1, 2, 3, 4, 5 e outras 2",
        ),
    ],
)
def test_dependency_description_is_exact(request_ids, matrix_names, expected):
    assert describe_activity_version_dependencies(request_ids, matrix_names) == expected


def test_historical_request_survives_renumbering_of_its_version(env):
    """A real request keeps its row, snapshot and read model when its version moves."""
    client = env["client"]
    _login(client)
    _, request_row = create_admin_request(client, "Historical renumber", version_id=29)
    assert request_row is not None
    frozen = json.loads(request_row["regra_snapshot_json"])
    base_id = frozen["atividade_base_id"]
    (first_id, _, _), (requested_id, requested_number, _) = _lineage(base_id)
    assert requested_id == 29 and requested_number == frozen["atividade_versao_numero"] == 2

    # The requested version and its Matrix block the delete, naming both.
    text = _response_text(_post_delete(client, base_id, requested_id))
    assert (
        "Não é possível excluir esta versão porque ela é utilizada "
        f"pela requisição {request_row['id']} e pela matriz Matriz PPA."
        in text
    )

    # v1 stops being selected by its Matrix, so deleting it is legitimate.
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "DELETE FROM matriz_atividade_versao_item WHERE atividade_versao_id=?", (first_id,)
        )
        conn.commit()
        requests_before = [
            dict(row) for row in conn.execute("SELECT * FROM requisicoes ORDER BY id").fetchall()
        ]
    api_before = client.get(f"/admin/api/requisicao/{request_row['id']}").get_json()

    response = _post_delete(client, base_id, first_id)

    assert "Versão excluída definitivamente com sucesso." in _response_text(response)
    assert _lineage(base_id) == [(requested_id, 1, None)]
    with main.app.app_context():
        requests_after = [
            dict(row)
            for row in main.get_db_connection().execute(
                "SELECT * FROM requisicoes ORDER BY id"
            ).fetchall()
        ]
    assert requests_after == requests_before
    assert json.loads(requests_after[-1]["regra_snapshot_json"])["atividade_versao_numero"] == 2
    assert client.get(f"/admin/api/requisicao/{request_row['id']}").get_json() == api_before


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------


def test_protected_reference_failure_rolls_back_reanchoring(env, monkeypatch):
    client = env["client"]
    _login(client)
    base_id, (v1, target, successor) = _seed_base_with_versions(
        "rascunho", "inativa", "rascunho", chained=True
    )
    _insert_request_reference(target)
    with main.app.app_context():
        conn = main.get_db_connection()
        transition_id = conn.execute(
            "INSERT INTO atividade_transicao"
            "(from_atividade_versao_id,to_atividade_versao_id,tipo_transicao) "
            "VALUES(?,?,'mesmo_eixo') RETURNING id",
            (v1, target),
        ).fetchone()[0]
        conn.commit()
    before = _rows_by_id(base_id)

    # Bypass the policy so the database's own FK is what refuses the delete,
    # after the successor has already been re-anchored in the transaction.
    monkeypatch.setattr(
        activity_catalog,
        "assert_activity_version_can_be_safely_deleted",
        lambda conn, *, base_id, versao_id: conn.execute(
            "SELECT * FROM atividade_versao WHERE id=?", (versao_id,)
        ).fetchone(),
    )
    response = _post_delete(client, base_id, target)

    assert "uma referência protegida ainda existe" in _response_text(response)
    assert _rows_by_id(base_id) == before
    assert _lineage(base_id) == [(v1, 1, None), (target, 2, v1), (successor, 3, target)]
    with main.app.app_context():
        assert main.get_db_connection().execute(
            "SELECT id FROM atividade_transicao WHERE id=?", (transition_id,)
        ).fetchone() is not None


def test_renumbering_failure_rolls_back_the_whole_delete(env, monkeypatch):
    client = env["client"]
    _login(client)
    base_id, ids = _seed_base_with_versions("ativa", "inativa", "ativa", chained=True)
    before = _rows_by_id(base_id)
    real_renumber = activity_catalog.renumber_activity_versions

    def failing_renumber(conn, base_id):
        real_renumber(conn, base_id)
        raise RuntimeError("simulated failure after renumbering")

    monkeypatch.setattr(activity_catalog, "renumber_activity_versions", failing_renumber)
    response = _post_delete(client, base_id, ids[0])

    assert "nenhuma alteração foi aplicada" in _response_text(response)
    assert _rows_by_id(base_id) == before


# ---------------------------------------------------------------------------
# Unchanged guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("direction", ["origin", "destination"])
def test_transition_origin_and_destination_rows_are_deleted_with_version(env, direction):
    client = env["client"]
    _login(client)
    base_id, (other, target) = _seed_base_with_versions("rascunho", "inativa")
    with main.app.app_context():
        conn = main.get_db_connection()
        origin, destination = (target, other) if direction == "origin" else (other, target)
        transition_id = conn.execute(
            "INSERT INTO atividade_transicao"
            "(from_atividade_versao_id,to_atividade_versao_id,tipo_transicao) "
            "VALUES(?,?,'mesmo_eixo') RETURNING id",
            (origin, destination),
        ).fetchone()[0]
        conn.commit()

    _post_delete(client, base_id, target)

    assert _version(target) is None
    assert _version(other) is not None
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute(
            "SELECT id FROM atividade_transicao WHERE id=?", (transition_id,)
        ).fetchone() is None


def test_sole_version_is_blocked(env):
    client = env["client"]
    _login(client)
    base_id, (target,) = _seed_base_with_versions("rascunho")

    response = _post_delete(client, base_id, target)

    assert _version(target) is not None
    assert "única versão da atividade" in _response_text(response)


def test_wrong_base_version_pair_is_blocked(env):
    client = env["client"]
    _login(client)
    source_base, (_, target) = _seed_base_with_versions("rascunho", "inativa")
    wrong_base, _ = _seed_base_with_versions("rascunho")

    response = _post_delete(client, wrong_base, target)

    assert source_base != wrong_base
    assert _version(target) is not None
    assert "Versão não encontrada para esta atividade-base" in _response_text(response)


def test_ui_offers_permanent_delete_for_every_status_when_another_version_survives(env):
    client = env["client"]
    _login(client)
    base_id, version_ids = _seed_base_with_versions(
        "rascunho", "inativa", "ativa", "descontinuada", "substituida"
    )

    html = _response_text(client.get(f"/admin/catalogo-versoes/{base_id}"))
    delete_forms = re.findall(r'<form hidden class="vc-delete-form".*?</form>', html, re.S)

    assert len(delete_forms) == 5
    rendered_delete_ids = {
        int(re.search(r'data-version-id="(\d+)"', form).group(1))
        for form in delete_forms
    }
    assert rendered_delete_ids == set(version_ids)
    assert "Excluir definitivamente a versão v1? Esta ação é permanente." in html
    assert 'data-action="delete" aria-label="Excluir versão"' in html
    assert "setVisible('delete', rows.length > 1);" in html
    assert 'data-action="discontinue" aria-label="Descontinuar versão"' in html

    for version_id in version_ids:
        version_html = _response_text(
            client.get(
                f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar"
            )
        )
        assert 'class="version-delete-form"' not in version_html
        assert ">Excluir versão</span>" not in version_html
        assert ">Excluir</span>" not in version_html


def test_ui_does_not_offer_delete_for_the_sole_version(env):
    client = env["client"]
    _login(client)
    base_id, (target,) = _seed_base_with_versions("ativa")

    html = _response_text(client.get(f"/admin/catalogo-versoes/{base_id}"))
    version_html = _response_text(
        client.get(f"/admin/catalogo-versoes/{base_id}/versoes/{target}/editar")
    )

    assert 'class="vc-delete-form"' not in html
    assert 'class="version-delete-form"' not in version_html


def test_csrf_and_rbac_prevent_delete_without_mutation(env):
    client = env["client"]
    base_id, (_, target) = _seed_base_with_versions("ativa", "rascunho")

    _login(client, user_id=9001, level="consultivo")
    denied = _post_delete(client, base_id, target, follow=False)
    assert denied.status_code == 302
    assert denied.headers["Location"].endswith("/admin/dashboard")
    assert _version(target) is not None

    _login(client, user_id=9002, level="admin_total")
    previous = main.app.config["WTF_CSRF_ENABLED"]
    main.app.config["WTF_CSRF_ENABLED"] = True
    try:
        csrf_denied = _post_delete(client, base_id, target, follow=False)
    finally:
        main.app.config["WTF_CSRF_ENABLED"] = previous
    assert csrf_denied.status_code == 400
    assert _version(target) is not None


def test_safe_delete_user_messages_are_owned_by_the_message_catalog():
    messages._message_catalog.cache_clear()
    defaults = {
        item["default_text"] for item in messages._message_catalog().values()
    }

    assert "Versão excluída definitivamente com sucesso." in defaults
    assert (
        "Não é possível excluir esta versão porque ela é utilizada {value_1}."
        in defaults
    )
    assert "Não é possível excluir: única versão da atividade." in defaults
    assert (
        "Excluir definitivamente a versão v{{ v.numero_versao }}? "
        "Esta ação é permanente."
        in defaults
    )
    for retired in (
        "Não é possível excluir: versão vinculada a Matriz.",
        "Não é possível excluir: versão vinculada a Requisição.",
        "Não é possível excluir: versão utilizada como versão anterior por outra versão.",
    ):
        assert retired not in defaults
