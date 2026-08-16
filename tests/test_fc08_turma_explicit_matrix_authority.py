import os
import re
import sys
import uuid
from html.parser import HTMLParser

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app.matrix_scope import (
    get_allowed_activity_ids_for_turma_matrix,
    get_effective_matriz_for_turma,
    is_activity_allowed_for_turma_matrix,
)
from app.views import aluno as aluno_views
from app.views.admin import dashboard as admin_dashboard_views
from app.views.admin.alunos_turmas_cursos import _resolve_turma_matriz_id


@pytest.fixture(scope="module")
def client():
    with main.app.test_client() as test_client:
        yield test_client


def _login(client, user_type, user_id=1):
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["user_type"] = user_type
        session["user_name"] = "FC08"


@pytest.fixture()
def authority_data():
    suffix = uuid.uuid4().hex[:10]
    course_code = f"FC08{suffix.upper()}"
    turma_code = f"{course_code}-T01"
    email = f"fc08-{suffix}@example.test"
    with main.app.app_context():
        conn = main.get_db_connection()
        course_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?) RETURNING id",
            (f"Curso FC08 {suffix}", course_code, 8, "ativo"),
        ).fetchone()["id"]
        matriz_m1 = conn.execute(
            """
            INSERT INTO matrizes_atividades
                (curso_id, nome, versao, status, data_inicio_vigencia,
                 horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (course_id, f"FC08 M1 {suffix}", "1", "encerrada", "2024-01-01", 1, 1, "M1"),
        ).fetchone()["id"]
        matriz_m2 = conn.execute(
            """
            INSERT INTO matrizes_atividades
                (curso_id, nome, versao, status, data_inicio_vigencia,
                 horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (course_id, f"FC08 M2 {suffix}", "2", "vigente", "2030-01-01", 2, 2, "M2"),
        ).fetchone()["id"]
        activity_m1 = conn.execute(
            """
            INSERT INTO atividades
                (grupo, nome, limite_horas, tipo_atividade, tem_limitacao,
                 tipo_limitacao, limite_horas_total, limite_horas_semestral, documentos_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("FC08", f"FC08 atividade M1 {suffix}", None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        activity_m2 = conn.execute(
            """
            INSERT INTO atividades
                (grupo, nome, limite_horas, tipo_atividade, tem_limitacao,
                 tipo_limitacao, limite_horas_total, limite_horas_semestral, documentos_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            ("FC08", f"FC08 atividade M2 {suffix}", None, "Acadêmica Complementar", 0, None, None, None, None),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_m1, activity_m1),
        )
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (matriz_m2, activity_m2),
        )
        turma_id = conn.execute(
            """
            INSERT INTO turmas
                (nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                 ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turma_code, None, None, "Noite", "Ativa", 1, course_id, matriz_m1, 2024, 1, 2027, 2, turma_code),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            ("Aluno FC08", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            """
            INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status)
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (usuario_id, "Aluno FC08", f"FC08-{suffix}", email, turma_id, "Ativo"),
        ).fetchone()["id"]
        conn.commit()

        data = {
            "course_id": course_id,
            "turma_id": turma_id,
            "matriz_m1": matriz_m1,
            "matriz_m2": matriz_m2,
            "activity_m1": activity_m1,
            "activity_m2": activity_m2,
            "aluno_id": aluno_id,
            "usuario_id": usuario_id,
            "turma_code": turma_code,
            "email": email,
        }
    try:
        yield data
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM requisicoes WHERE aluno_id = ?", (data["aluno_id"],))
            conn.execute("DELETE FROM alunos WHERE id = ?", (data["aluno_id"],))
            conn.execute("DELETE FROM usuarios WHERE id = ?", (data["usuario_id"],))
            conn.execute("DELETE FROM turmas WHERE id = ?", (data["turma_id"],))
            conn.execute(
                "DELETE FROM matrizes_atividades_itens WHERE matriz_id IN (?, ?)",
                (data["matriz_m1"], data["matriz_m2"]),
            )
            conn.execute(
                "DELETE FROM matrizes_atividades WHERE id IN (?, ?)",
                (data["matriz_m1"], data["matriz_m2"]),
            )
            conn.execute(
                "DELETE FROM requisicoes WHERE atividade_id IN (?, ?)",
                (data["activity_m1"], data["activity_m2"]),
            )
            conn.execute(
                "DELETE FROM atividades WHERE id IN (?, ?)",
                (data["activity_m1"], data["activity_m2"]),
            )
            conn.execute("DELETE FROM cursos WHERE id = ?", (data["course_id"],))
            conn.commit()


def _insert_pending_request(data, atividade_id, name, aluno_id=None):
    with main.app.app_context():
        conn = main.get_db_connection()
        req_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento,
                horas_solicitadas, nome_evento, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                data["aluno_id"] if aluno_id is None else aluno_id,
                atividade_id,
                "2030-05-01 10:00:00",
                "2030-05-10",
                4,
                name,
                "Pendente",
            ),
        ).fetchone()["id"]
        conn.commit()
        return req_id


class _DashboardKpiParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = {}
        self._depth = 0
        self._card_kind = None
        self._card_depth = None
        self._card_text = []
        self._progress_data = None
        self._progress_children = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self._card_kind is None and tag == "div" and "kpi-card" in classes:
            kind = attributes.get("data-kind")
            if kind in {"acad", "ext"}:
                self._card_kind = kind
                self._card_depth = self._depth
                self._card_text = []
                self._progress_data = None
                self._progress_children = 0
        elif self._card_kind is not None and tag == "div":
            if "progress" in classes and "is-bar" in classes:
                self._progress_data = attributes.get("data-pct")
            if "progress-bar" in classes:
                self._progress_children += 1
        self._depth += 1

    def handle_endtag(self, tag):
        if (
            self._card_kind is not None
            and tag == "div"
            and self._depth == self._card_depth + 1
        ):
            self.cards[self._card_kind] = {
                "text": " ".join("".join(self._card_text).split()),
                "progress_data": self._progress_data,
                "progress_children": self._progress_children,
            }
            self._card_kind = None
            self._card_depth = None
            self._card_text = []
            self._progress_data = None
            self._progress_children = 0
        self._depth -= 1

    def handle_data(self, data):
        if self._card_kind is not None:
            self._card_text.append(data)


def _dashboard_kpis(html):
    parser = _DashboardKpiParser()
    parser.feed(html)
    return parser.cards


def _assert_malformed_cohort_processing_denied(
    client,
    data,
    req_id,
    *,
    expected_aluno_id,
    expected_turma_id,
    expected_aluno_turma_id=None,
):
    for status, extra in (
        ("Deferida", {}),
        ("Deferida Parcialmente", {"horas_deferidas": "2"}),
    ):
        processed = client.post(
            f"/admin/processar_requisicao/{req_id}",
            data={"status": status, "observacao": "malformed cohort", **extra},
            follow_redirects=False,
        )
        assert processed.status_code in (302, 303)
        with main.app.app_context():
            conn = main.get_db_connection()
            row = conn.execute(
                """
                SELECT aluno_id, atividade_id, status, data_processamento, admin_id,
                       horas_deferidas, atividade_versao_id, regra_snapshot_json,
                       codigo_normativo_snapshot
                  FROM requisicoes
                 WHERE id = ?
                """,
                (req_id,),
            ).fetchone()
            assert row["status"] not in {"Deferida", "Deferida Parcialmente"}
            assert row["status"] == "Pendente"
            assert row["aluno_id"] == expected_aluno_id
            assert row["atividade_id"] == data["activity_m1"]
            assert row["data_processamento"] is None
            assert row["admin_id"] is None
            assert row["horas_deferidas"] is None
            assert row["atividade_versao_id"] is None
            assert row["regra_snapshot_json"] is None
            assert row["codigo_normativo_snapshot"] is None
            aluno = conn.execute(
                "SELECT turma_id FROM alunos WHERE id = ?",
                (data["aluno_id"],),
            ).fetchone()
            if expected_aluno_id is None:
                assert aluno is None
            else:
                assert aluno["turma_id"] == expected_aluno_turma_id
            turma = conn.execute(
                "SELECT id, matriz_id FROM turmas WHERE id = ?",
                (data["turma_id"],),
            ).fetchone()
            assert turma["id"] == expected_turma_id
            assert turma["matriz_id"] == data["matriz_m1"]


def test_m1_aluno_without_turma_cannot_process_positive_status(client, authority_data):
    req_id = _insert_pending_request(authority_data, authority_data["activity_m1"], "FC08 M1 sem turma")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE alunos SET turma_id = NULL WHERE id = ?", (authority_data["aluno_id"],))
        conn.commit()
    _login(client, "admin")
    try:
        _assert_malformed_cohort_processing_denied(
            client,
            authority_data,
            req_id,
            expected_aluno_id=authority_data["aluno_id"],
            expected_turma_id=authority_data["turma_id"],
            expected_aluno_turma_id=None,
        )
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE alunos SET turma_id = ? WHERE id = ?", (authority_data["turma_id"], authority_data["aluno_id"]))
            conn.commit()


def test_m2_dangling_aluno_turma_cannot_process_positive_status(client, authority_data):
    req_id = _insert_pending_request(authority_data, authority_data["activity_m1"], "FC08 M2 turma dangling")
    dangling_turma_id = 987654321
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE alunos SET turma_id = ? WHERE id = ?", (dangling_turma_id, authority_data["aluno_id"]))
        conn.commit()
    _login(client, "admin")
    try:
        _assert_malformed_cohort_processing_denied(
            client,
            authority_data,
            req_id,
            expected_aluno_id=authority_data["aluno_id"],
            expected_turma_id=authority_data["turma_id"],
            expected_aluno_turma_id=dangling_turma_id,
        )
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE alunos SET turma_id = ? WHERE id = ?", (authority_data["turma_id"], authority_data["aluno_id"]))
            conn.commit()


def test_m3_unresolved_aluno_set_null_cannot_process_positive_status(client, authority_data):
    req_id = _insert_pending_request(authority_data, authority_data["activity_m1"], "FC08 M3 aluno resolvido")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM alunos WHERE id = ?", (authority_data["aluno_id"],))
        conn.commit()
    _login(client, "admin")
    try:
        _assert_malformed_cohort_processing_denied(
            client,
            authority_data,
            req_id,
            expected_aluno_id=None,
            expected_turma_id=authority_data["turma_id"],
        )
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM requisicoes WHERE id = ?", (req_id,))
            conn.commit()


def test_t1_create_without_matrix_rejects_and_does_not_persist_preferred(client, authority_data):
    _login(client, "admin")
    response = client.post(
        "/admin/adicionar_turma",
        data={"curso_id": authority_data["course_id"], "numero_turma": 2},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        assert conn.execute(
            "SELECT 1 FROM turmas WHERE curso_id = ? AND numero = ?",
            (authority_data["course_id"], 2),
        ).fetchone() is None


def test_t2_edit_without_matrix_does_not_replace_explicit_matrix(client, authority_data):
    _login(client, "admin")
    response = client.post(
        f"/admin/editar_turma/{authority_data['turma_id']}",
        data={
            "curso_id": authority_data["course_id"],
            "numero_turma": 1,
            "turno": "Integral",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Selecione uma matriz para a turma." in response.get_data(as_text=True)
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT matriz_id, turno FROM turmas WHERE id = ?", (authority_data["turma_id"],)
        ).fetchone()
        assert row["matriz_id"] == authority_data["matriz_m1"]
        assert row["turno"] == "Noite"


def test_t2_valid_explicit_matrix_change_is_deliberate(client, authority_data):
    _login(client, "admin")
    response = client.post(
        f"/admin/editar_turma/{authority_data['turma_id']}",
        data={
            "curso_id": authority_data["course_id"],
            "numero_turma": 1,
            "matriz_id": authority_data["matriz_m2"],
            "turno": "Integral",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT matriz_id, turno FROM turmas WHERE id = ?", (authority_data["turma_id"],)
        ).fetchone()
        assert row["matriz_id"] == authority_data["matriz_m2"]
        assert row["turno"] == "Integral"


def test_t3_foreign_course_matrix_is_rejected(client, authority_data):
    with main.app.app_context():
        conn = main.get_db_connection()
        foreign_course_id = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?) RETURNING id",
            ("Curso FC08 estrangeiro", f"FOREIGN{uuid.uuid4().hex[:8]}", 8, "ativo"),
        ).fetchone()["id"]
        foreign_matrix_id = conn.execute(
            """
            INSERT INTO matrizes_atividades
                (curso_id, nome, versao, status, data_inicio_vigencia, descricao)
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (foreign_course_id, f"FC08 foreign {uuid.uuid4().hex[:8]}", "1", "vigente", "2030-01-01", "foreign"),
        ).fetchone()["id"]
        conn.commit()
    try:
        _login(client, "admin")
        response = client.post(
            "/admin/adicionar_turma",
            data={"curso_id": authority_data["course_id"], "numero_turma": 3, "matriz_id": foreign_matrix_id},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)
        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute(
                "SELECT 1 FROM turmas WHERE curso_id = ? AND numero = ?",
                (authority_data["course_id"], 3),
            ).fetchone() is None
    finally:
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (foreign_matrix_id,))
            conn.execute("DELETE FROM cursos WHERE id = ?", (foreign_course_id,))
            conn.commit()


def test_t4_and_t11_explicit_m1_is_stable_when_m2_is_preferred(authority_data):
    with main.app.app_context():
        conn = main.get_db_connection()
        before = get_effective_matriz_for_turma(conn, authority_data["course_id"], authority_data["matriz_m1"])
        conn.execute("UPDATE matrizes_atividades SET status = 'ativa' WHERE id = ?", (authority_data["matriz_m2"],))
        conn.commit()
        after = get_effective_matriz_for_turma(conn, authority_data["course_id"], authority_data["matriz_m1"])
        assert before["id"] == authority_data["matriz_m1"]
        assert after["id"] == authority_data["matriz_m1"]


def test_t5_null_matrix_does_not_resolve_to_preferred(authority_data):
    with main.app.app_context():
        conn = main.get_db_connection()
        assert get_effective_matriz_for_turma(conn, authority_data["course_id"], None) is None


def test_t6_null_matrix_cannot_allow_activity(authority_data):
    with main.app.app_context():
        conn = main.get_db_connection()
        assert not is_activity_allowed_for_turma_matrix(
            conn, authority_data["activity_m2"], authority_data["course_id"], None
        )


def test_t7_null_matrix_allowed_ids_are_empty_and_not_unrestricted(authority_data):
    with main.app.app_context():
        conn = main.get_db_connection()
        allowed_ids, matriz = get_allowed_activity_ids_for_turma_matrix(
            conn, authority_data["course_id"], None
        )
        assert allowed_ids == set()
        assert matriz is None


def test_t8_student_catalogue_uses_exact_turma_matrix(authority_data):
    with main.app.app_context():
        conn = main.get_db_connection()
        _, matriz, activities = aluno_views._list_atividades_for_usuario(
            conn, authority_data["usuario_id"], "Todas"
        )
        assert matriz["id"] == authority_data["matriz_m1"]
        assert {row["id"] for row in activities} == {authority_data["activity_m1"]}


def test_t9_admin_request_creation_fails_closed_for_null_matrix(client, authority_data):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE turmas SET matriz_id = NULL WHERE id = ?", (authority_data["turma_id"],))
        conn.commit()
    _login(client, "admin")
    response = client.post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": authority_data["aluno_id"],
            "atividade_id": authority_data["activity_m2"],
            "nome_evento": "Evento FC08",
            "data_evento": "2030-05-10",
            "horas_solicitadas": "2",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        assert main.get_db_connection().execute(
            "SELECT 1 FROM requisicoes WHERE aluno_id = ?", (authority_data["aluno_id"],)
        ).fetchone() is None


def test_t10_edit_get_does_not_backfill_null_matrix(client, authority_data):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE turmas SET matriz_id = NULL WHERE id = ?", (authority_data["turma_id"],))
        conn.commit()
    _login(client, "admin")
    response = client.get(f"/admin/editar_turma/{authority_data['turma_id']}")
    assert response.status_code == 200
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT matriz_id FROM turmas WHERE id = ?", (authority_data["turma_id"],)
        ).fetchone()
        assert row["matriz_id"] is None


def test_t12_preferred_matrix_is_not_used_by_turma_write_resolver(authority_data):
    with main.app.app_context():
        conn = main.get_db_connection()
        matriz_id, error = _resolve_turma_matriz_id(conn, authority_data["course_id"], None)
        assert matriz_id is None
        assert error


# False-green guard: a permissive Matrix helper would deny the historical request.
def test_t13_historical_null_matrix_request_can_be_deferred_but_new_scope_is_denied(client, authority_data):
    request_name = "FC08 historical deferida"
    req_id = _insert_pending_request(authority_data, authority_data["activity_m2"], request_name)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE turmas SET matriz_id = NULL WHERE id = ?", (authority_data["turma_id"],))
        conn.commit()

    _login(client, "admin")
    processed = client.post(
        f"/admin/processar_requisicao/{req_id}",
        data={"status": "Deferida", "observacao": "historical"},
        follow_redirects=False,
    )
    assert processed.status_code in (302, 303)
    created = client.post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": authority_data["aluno_id"],
            "atividade_id": authority_data["activity_m2"],
            "nome_evento": "FC08 new denied",
            "data_evento": "2030-05-11",
            "horas_solicitadas": "2",
        },
        follow_redirects=False,
    )
    assert created.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        request_row = conn.execute(
            "SELECT status FROM requisicoes WHERE id = ?", (req_id,)
        ).fetchone()
        assert request_row["status"] == "Deferida"
        assert conn.execute(
            "SELECT 1 FROM requisicoes WHERE nome_evento = 'FC08 new denied'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT matriz_id FROM turmas WHERE id = ?", (authority_data["turma_id"],)
        ).fetchone()["matriz_id"] is None


# False-green guard: a permissive Matrix helper would deny the historical request.
def test_t14_historical_null_matrix_request_can_be_partially_deferred_but_new_scope_is_denied(client, authority_data):
    request_name = "FC08 historical partial"
    req_id = _insert_pending_request(authority_data, authority_data["activity_m2"], request_name)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE turmas SET matriz_id = NULL WHERE id = ?", (authority_data["turma_id"],))
        conn.commit()

    _login(client, "admin")
    processed = client.post(
        f"/admin/processar_requisicao/{req_id}",
        data={
            "status": "Deferida Parcialmente",
            "horas_deferidas": "2",
            "observacao": "historical partial",
        },
        follow_redirects=False,
    )
    assert processed.status_code in (302, 303)
    created = client.post(
        "/admin/requisicoes/nova",
        data={
            "aluno_id": authority_data["aluno_id"],
            "atividade_id": authority_data["activity_m2"],
            "nome_evento": "FC08 new partial denied",
            "data_evento": "2030-05-11",
            "horas_solicitadas": "2",
        },
        follow_redirects=False,
    )
    assert created.status_code in (302, 303)
    with main.app.app_context():
        conn = main.get_db_connection()
        request_row = conn.execute(
            "SELECT status, horas_deferidas FROM requisicoes WHERE id = ?", (req_id,)
        ).fetchone()
        assert request_row["status"] == "Deferida Parcialmente"
        assert float(request_row["horas_deferidas"]) == 2
        assert conn.execute(
            "SELECT 1 FROM requisicoes WHERE nome_evento = 'FC08 new partial denied'"
        ).fetchone() is None


# False-green guard: a broad historical bypass would allow this new request.
def test_t15_same_null_matrix_turma_cannot_create_new_student_request(client, authority_data):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE turmas SET matriz_id = NULL WHERE id = ?", (authority_data["turma_id"],))
        conn.commit()
    _login(client, "aluno", authority_data["usuario_id"])
    response = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": authority_data["activity_m2"],
            "nome_evento": "FC08 student new denied",
            "data_evento": "2030-05-11",
            "horas_solicitadas": "2",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    with main.app.app_context():
        assert main.get_db_connection().execute(
            "SELECT 1 FROM requisicoes WHERE nome_evento = 'FC08 student new denied'"
        ).fetchone() is None


# False-green guard: a broad compatibility bypass would approve an out-of-scope activity.
def test_t16_explicit_matrix_historical_request_still_enforces_exact_scope(client, authority_data):
    req_id = _insert_pending_request(authority_data, authority_data["activity_m2"], "FC08 explicit out of scope")
    _login(client, "admin")
    response = client.post(
        f"/admin/processar_requisicao/{req_id}",
        data={"status": "Deferida", "observacao": "must deny"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT r.status, t.matriz_id FROM requisicoes r JOIN alunos a ON a.id = r.aluno_id JOIN turmas t ON t.id = a.turma_id WHERE r.id = ?",
            (req_id,),
        ).fetchone()
        assert row["status"] == "Pendente"
        assert row["matriz_id"] == authority_data["matriz_m1"]


# False-green guard: fallback to sentinel defaults would expose fabricated targets.
def test_t17_student_dashboard_null_matrix_keeps_hours_but_no_default_target(client, authority_data, monkeypatch):
    monkeypatch.setattr(aluno_views, "DEFAULT_CURSO_TOTAL_HORAS_AAC", 9911)
    monkeypatch.setattr(aluno_views, "DEFAULT_CURSO_TOTAL_HORAS_AEU", 9922)
    _insert_pending_request(authority_data, authority_data["activity_m1"], "FC08 dashboard hours")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE requisicoes SET status = 'Deferida' WHERE nome_evento = 'FC08 dashboard hours'"
        )
        conn.execute("UPDATE turmas SET matriz_id = NULL WHERE id = ?", (authority_data["turma_id"],))
        conn.commit()
    _login(client, "aluno", authority_data["usuario_id"])
    response = client.get("/aluno/dashboard")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "9911" not in html and "9922" not in html
    assert "4/- h" in html
    kpis = _dashboard_kpis(html)
    assert set(kpis) >= {"acad", "ext"}
    assert "4/- h" in kpis["acad"]["text"]
    assert "0/- h" in kpis["ext"]["text"]
    for kind in ("acad", "ext"):
        assert "cumprido" not in kpis[kind]["text"]
        assert kpis[kind]["progress_data"] is None
        assert kpis[kind]["progress_children"] == 0


# False-green guard: fallback to sentinel defaults would create applicable denominators.
def test_t18_admin_dashboard_null_matrix_has_no_default_denominator(authority_data, monkeypatch):
    monkeypatch.setattr(admin_dashboard_views, "DEFAULT_CURSO_TOTAL_HORAS_AAC", 9933)
    monkeypatch.setattr(admin_dashboard_views, "DEFAULT_CURSO_TOTAL_HORAS_AEU", 9944)
    _insert_pending_request(authority_data, authority_data["activity_m1"], "FC08 admin dashboard hours")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE requisicoes SET status = 'Deferida' WHERE nome_evento = 'FC08 admin dashboard hours'"
        )
        conn.execute("UPDATE turmas SET matriz_id = NULL WHERE id = ?", (authority_data["turma_id"],))
        conn.commit()
        cards, _total, _summary = admin_dashboard_views._build_admin_dashboard_turma_cards(conn)
    card = next(card for card in cards if card["id"] == authority_data["turma_id"])
    assert card["aac_hours_fmt"] == "4"
    assert card["aac_applicable"] is False
    assert card["aac_pct"] is None
    assert card["total_applicable"] is False
    assert card["total_pct"] is None


# False-green guard: fallback to sentinel defaults would hide the explicit 7-hour target.
def test_t19_explicit_matrix_non_default_targets_are_used_exactly(client, authority_data, monkeypatch):
    monkeypatch.setattr(aluno_views, "DEFAULT_CURSO_TOTAL_HORAS_AAC", 9955)
    monkeypatch.setattr(aluno_views, "DEFAULT_CURSO_TOTAL_HORAS_AEU", 9966)
    _insert_pending_request(authority_data, authority_data["activity_m1"], "FC08 explicit dashboard hours")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE requisicoes SET status = 'Deferida' WHERE nome_evento = 'FC08 explicit dashboard hours'"
        )
        conn.execute(
            "UPDATE matrizes_atividades SET horas_aac_obrigatorias = 7, horas_extensao_obrigatorias = 11 WHERE id = ?",
            (authority_data["matriz_m1"],),
        )
        conn.commit()
        cards, _total, _summary = admin_dashboard_views._build_admin_dashboard_turma_cards(conn)
    card = next(card for card in cards if card["id"] == authority_data["turma_id"])
    assert card["aac_applicable"] is True
    assert card["aac_pct"] == 57
    _login(client, "aluno", authority_data["usuario_id"])
    html = client.get("/aluno/dashboard").get_data(as_text=True)
    assert "4/7 h" in html
    assert 'data-kind="acad"' in html
    assert 'data-kind="ext"' in html
    assert 'data-pct="57' in html
    assert 'data-pct="0"' in html
    assert "9955" not in html and "9966" not in html


def _student_kpi_fragment(html, kind):
    next_kind = "pend-acad" if kind == "acad" else "pend-ext"
    match = re.search(
        rf'<div class="kpi-card kpi-primary" data-kind="{kind}">(.*?)'
        rf'<div class="kpi-card" data-kind="{next_kind}">',
        html,
        re.DOTALL,
    )
    assert match, f"missing student KPI fragment for {kind}"
    return match.group(1)


def test_t17_student_dashboard_unavailable_kpis_have_no_progress_semantics(client, authority_data, monkeypatch):
    monkeypatch.setattr(aluno_views, "DEFAULT_CURSO_TOTAL_HORAS_AAC", 9977)
    monkeypatch.setattr(aluno_views, "DEFAULT_CURSO_TOTAL_HORAS_AEU", 9988)
    _insert_pending_request(authority_data, authority_data["activity_m1"], "FC08 dashboard scoped hours")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE requisicoes SET status = 'Deferida' WHERE nome_evento = 'FC08 dashboard scoped hours'"
        )
        conn.execute("UPDATE turmas SET matriz_id = NULL WHERE id = ?", (authority_data["turma_id"],))
        conn.commit()
    _login(client, "aluno", authority_data["usuario_id"])
    html = client.get("/aluno/dashboard").get_data(as_text=True)
    acad = _student_kpi_fragment(html, "acad")
    ext = _student_kpi_fragment(html, "ext")
    for fragment, hours in ((acad, "4/- h"), (ext, "0/- h")):
        assert hours in fragment
        assert '<div class="kpi-sub">-</div>' in fragment
        assert "cumprido" not in fragment
        assert 'class="progress is-bar"' not in fragment
        assert "data-pct=" not in fragment
        assert "9977" not in fragment and "9988" not in fragment
    assert 'class="resume-total-bar"' not in html


# False-green guard: turma_matriz_id NULL alone must not bypass a missing Turma.
def test_t20_missing_aluno_turma_cannot_use_historical_bypass(client, authority_data):
    req_id = _insert_pending_request(authority_data, authority_data["activity_m2"], "FC08 missing turma")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE alunos SET turma_id = NULL WHERE id = ?", (authority_data["aluno_id"],))
        conn.commit()
    _login(client, "admin")
    client.post(
        f"/admin/processar_requisicao/{req_id}",
        data={"status": "Deferida", "observacao": "must deny"},
        follow_redirects=False,
    )
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, atividade_versao_id, regra_snapshot_json FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert row["status"] == "Pendente"
        assert row["atividade_versao_id"] is None
        assert row["regra_snapshot_json"] is None


# False-green guard: a dangling aluno.turma_id must not become historical compatibility.
def test_t21_dangling_aluno_turma_cannot_use_historical_bypass(client, authority_data):
    req_id = _insert_pending_request(authority_data, authority_data["activity_m2"], "FC08 dangling turma")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE alunos SET turma_id = 999999 WHERE id = ?", (authority_data["aluno_id"],))
        conn.commit()
    _login(client, "admin")
    client.post(
        f"/admin/processar_requisicao/{req_id}",
        data={"status": "Deferida Parcialmente", "horas_deferidas": "2"},
        follow_redirects=False,
    )
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, atividade_versao_id, regra_snapshot_json FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert row["status"] == "Pendente"
        assert row["atividade_versao_id"] is None
        assert row["regra_snapshot_json"] is None


# False-green guard: a NULL request aluno_id must not acquire positive adjudication.
def test_t22_missing_aluno_cannot_use_historical_bypass(client, authority_data):
    req_id = _insert_pending_request(
        authority_data,
        authority_data["activity_m2"],
        "FC08 missing aluno",
        aluno_id=None,
    )
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE requisicoes SET aluno_id = NULL WHERE id = ?", (req_id,))
        conn.commit()
    _login(client, "admin")
    client.post(
        f"/admin/processar_requisicao/{req_id}",
        data={"status": "Deferida", "observacao": "must deny"},
        follow_redirects=False,
    )
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, atividade_versao_id, regra_snapshot_json FROM requisicoes WHERE id = ?",
            (req_id,),
        ).fetchone()
        assert row["status"] == "Pendente"
        assert row["atividade_versao_id"] is None
        assert row["regra_snapshot_json"] is None
