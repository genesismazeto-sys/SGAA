from __future__ import annotations

import re
import uuid

import pytest

import main
from app.views.admin import activity_version_delete as delete_view
from tests.versioned_test_support import isolated_versioned_app_env
from utils import messages


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


def _seed_base_with_versions(*statuses: str, numbers=None):
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
            version_ids.append(
                conn.execute(
                    "INSERT INTO atividade_versao"
                    "(atividade_base_id,eixo,grupo,numero_versao,status) "
                    "VALUES(?,'AAC','1 - Safe delete',?,?) RETURNING id",
                    (base_id, number, status),
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


def _response_text(response):
    return response.get_data(as_text=True)


def test_unreferenced_draft_v2_with_surviving_v1_is_deleted(env):
    client = env["client"]
    _login(client)
    base_id, (v1, v2) = _seed_base_with_versions("ativa", "rascunho")

    response = _post_delete(client, base_id, v2)

    assert response.status_code == 200
    assert _version(v2) is None
    assert _version(v1) is not None
    assert "Versão excluída definitivamente com sucesso." in _response_text(response)


def test_unreferenced_inactive_v2_is_deleted(env):
    client = env["client"]
    _login(client)
    base_id, (_, v2) = _seed_base_with_versions("ativa", "inativa")

    _post_delete(client, base_id, v2)

    assert _version(v2) is None


@pytest.mark.parametrize("status", ["ativa", "descontinuada", "substituida"])
def test_lifecycle_frozen_statuses_are_blocked(env, status):
    client = env["client"]
    _login(client)
    base_id, (_, target) = _seed_base_with_versions("rascunho", status)

    response = _post_delete(client, base_id, target)

    assert _version(target) is not None
    if status == "ativa":
        assert "Inative-a antes de tentar novamente" in _response_text(response)
    else:
        assert "Somente versões em rascunho ou inativas" in _response_text(response)


def _insert_matrix_reference(base_id, version_id):
    token = uuid.uuid4().hex[:8]
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
            (course_id, f"Matrix {token}"),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item"
            "(matriz_id,atividade_base_id,atividade_versao_id) VALUES(?,?,?)",
            (matrix_id, base_id, version_id),
        )
        conn.commit()


def _insert_request_reference(version_id):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO requisicoes"
            "(atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,status,regra_snapshot_json) "
            "VALUES(?,'2026-09-07','2026-09-07',1,'Pendente','{}')",
            (version_id,),
        )
        conn.commit()


@pytest.mark.parametrize("direction", ["origin", "destination"])
def test_transition_origin_and_destination_references_are_blocked(env, direction):
    client = env["client"]
    _login(client)
    base_id, (other, target) = _seed_base_with_versions("rascunho", "inativa")
    with main.app.app_context():
        conn = main.get_db_connection()
        origin, destination = (target, other) if direction == "origin" else (other, target)
        conn.execute(
            "INSERT INTO atividade_transicao"
            "(from_atividade_versao_id,to_atividade_versao_id,tipo_transicao) "
            "VALUES(?,?,'mesmo_eixo')",
            (origin, destination),
        )
        conn.commit()

    response = _post_delete(client, base_id, target)

    assert _version(target) is not None
    assert f"transição como {direction.replace('origin', 'origem').replace('destination', 'destino')}" in _response_text(response)


@pytest.mark.parametrize(
    "reference_factory,expected_reason",
    [
        (_insert_matrix_reference, "referência(s) em Matriz"),
        (lambda _base_id, version_id: _insert_request_reference(version_id), "referência(s) em requisição"),
    ],
)
def test_matrix_and_request_references_are_blocked(env, reference_factory, expected_reason):
    client = env["client"]
    _login(client)
    base_id, (_, target) = _seed_base_with_versions("rascunho", "inativa")
    reference_factory(base_id, target)

    response = _post_delete(client, base_id, target)

    assert _version(target) is not None
    assert expected_reason in _response_text(response)


def test_successor_predecessor_reference_is_reported_and_blocked(env):
    client = env["client"]
    _login(client)
    base_id, (v1, target) = _seed_base_with_versions("rascunho", "inativa")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "INSERT INTO atividade_versao"
            "(atividade_base_id,eixo,grupo,numero_versao,status,versao_anterior_id) "
            "VALUES(?,'AAC','1 - Successor',3,'rascunho',?)",
            (base_id, target),
        )
        conn.commit()

    response = _post_delete(client, base_id, target)

    assert _version(target) is not None
    assert _version(v1) is not None
    assert "versão sucessora como predecessora" in _response_text(response)


def test_sole_version_is_blocked(env):
    client = env["client"]
    _login(client)
    base_id, (target,) = _seed_base_with_versions("rascunho")

    response = _post_delete(client, base_id, target)

    assert _version(target) is not None
    assert "A única versão" in _response_text(response)


def test_wrong_base_version_pair_is_blocked(env):
    client = env["client"]
    _login(client)
    source_base, (_, target) = _seed_base_with_versions("rascunho", "inativa")
    wrong_base, _ = _seed_base_with_versions("rascunho")

    response = _post_delete(client, wrong_base, target)

    assert source_base != wrong_base
    assert _version(target) is not None
    assert "Versão não encontrada para esta atividade-base" in _response_text(response)


def test_success_removes_only_selected_version_and_does_not_renumber(env):
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
        base_before = dict(conn.execute("SELECT * FROM atividade_base WHERE id=?", (base_id,)).fetchone())
        survivors_before = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM atividade_versao WHERE id IN (?,?) ORDER BY id", (v1, v4)
            ).fetchall()
        ]
        related_before = {
            "matrix": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM matriz_atividade_versao_item WHERE atividade_base_id=?",
                    (base_id,),
                ).fetchall()
            ],
            "requests": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM requisicoes WHERE atividade_versao_id IN (?,?) ORDER BY id",
                    (v1, v4),
                ).fetchall()
            ],
            "transitions": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM atividade_transicao "
                    "WHERE from_atividade_versao_id IN (?,?) OR to_atividade_versao_id IN (?,?) "
                    "ORDER BY id",
                    (v1, v4, v1, v4),
                ).fetchall()
            ],
        }

    _post_delete(client, base_id, selected)

    with main.app.app_context():
        conn = main.get_db_connection()
        assert dict(conn.execute("SELECT * FROM atividade_base WHERE id=?", (base_id,)).fetchone()) == base_before
        survivors_after = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM atividade_versao WHERE id IN (?,?) ORDER BY id", (v1, v4)
            ).fetchall()
        ]
        assert survivors_after == survivors_before
        assert [row["numero_versao"] for row in survivors_after] == [1, 4]
        related_after = {
            "matrix": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM matriz_atividade_versao_item WHERE atividade_base_id=?",
                    (base_id,),
                ).fetchall()
            ],
            "requests": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM requisicoes WHERE atividade_versao_id IN (?,?) ORDER BY id",
                    (v1, v4),
                ).fetchall()
            ],
            "transitions": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM atividade_transicao "
                    "WHERE from_atividade_versao_id IN (?,?) OR to_atividade_versao_id IN (?,?) "
                    "ORDER BY id",
                    (v1, v4, v1, v4),
                ).fetchall()
            ],
        }
        assert related_after == related_before


def test_ui_offers_permanent_delete_only_for_potentially_deletable_statuses(env):
    client = env["client"]
    _login(client)
    base_id, version_ids = _seed_base_with_versions(
        "rascunho", "inativa", "ativa", "descontinuada", "substituida"
    )

    html = _response_text(client.get(f"/admin/catalogo-versoes/{base_id}"))
    delete_forms = re.findall(r'<form hidden class="vc-delete-form".*?</form>', html, re.S)

    assert len(delete_forms) == 2
    rendered_delete_ids = {
        int(re.search(r'data-version-id="(\d+)"', form).group(1))
        for form in delete_forms
    }
    assert rendered_delete_ids == {version_ids[0], version_ids[1]}
    assert "Excluir definitivamente a versão v1? Esta exclusão é permanente." in html
    assert 'data-action="delete" aria-label="Excluir versão"' in html
    assert 'data-action="discontinue" aria-label="Descontinuar versão"' in html


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


def test_fk_integrity_conflict_rolls_back_with_safe_error(env, monkeypatch):
    client = env["client"]
    _login(client)
    base_id, (_, target) = _seed_base_with_versions("rascunho", "inativa")
    with main.app.app_context():
        conn = main.get_db_connection()
        successor = conn.execute(
            "INSERT INTO atividade_versao"
            "(atividade_base_id,eixo,grupo,numero_versao,status,versao_anterior_id) "
            "VALUES(?,'AAC','1 - Successor',3,'rascunho',?) RETURNING id",
            (base_id, target),
        ).fetchone()[0]
        conn.commit()

    monkeypatch.setattr(
        delete_view,
        "assert_activity_version_can_be_safely_deleted",
        lambda *_args, **_kwargs: object(),
    )
    response = _post_delete(client, base_id, target)

    assert _version(target) is not None
    assert _version(successor) is not None
    assert "uma referência protegida ainda existe" in _response_text(response)


def test_safe_delete_user_messages_are_owned_by_the_message_catalog():
    messages._message_catalog.cache_clear()
    defaults = {
        item["default_text"] for item in messages._message_catalog().values()
    }

    assert "Versão excluída definitivamente com sucesso." in defaults
    assert (
        "Versão ativa não pode ser excluída. Inative-a antes de tentar novamente."
        in defaults
    )
    assert (
        "Não é possível excluir: a versão possui {value_1} "
        "referência(s) em {value_2}."
        in defaults
    )
    assert (
        "Excluir definitivamente a versão v{{ v.numero_versao }}? "
        "Esta exclusão é permanente."
        in defaults
    )
