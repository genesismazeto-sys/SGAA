"""Hardening of the explicit student Matrix assignment surface (UT-AM2H).

UT-AM2 made ``alunos.matriz_id`` assignable from the admin Edit Aluno form and
gave the field three meanings: absent (no intent), empty ("Sem matriz") and a
chosen Matrix.  Reading it with ``request.form.get("matriz_id", type=int)``
collapsed the third case into the second whenever the submitted value was
non-empty garbage, so a handcrafted authenticated POST could clear the academic
authority while looking like an ordinary edit.  This module pins the backend as
authoritative over that parse, and adds the dedicated regression for the
out-of-set current-Matrix preselection branch that keeps a corrupt pairing
visible and correctable instead of silently substituted.
"""
import os
import sqlite3
import sys

import pytest
from flask import request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app import db as app_db_module
from app.prod1_schema import bootstrap_prod1_schema
from app.student_matrix import StudentMatrixError, parse_submitted_matriz_id


MALFORMED = ("abc", "1a", "a1", "1.5", "1,5", "  ", "null", "None", "NaN", "-", "1e3")


# --------------------------------------------------------------------------
# Unit level: the submitted-value parser
# --------------------------------------------------------------------------


def test_empty_submission_is_the_explicit_clear():
    assert parse_submitted_matriz_id("") is None
    assert parse_submitted_matriz_id(None) is None


def test_valid_integer_submission_is_parsed():
    assert parse_submitted_matriz_id("7") == 7
    # O espaco em volta do valor do select nao e conteudo.
    assert parse_submitted_matriz_id(" 7 ") == 7


@pytest.mark.parametrize("raw", [value for value in MALFORMED if value.strip()])
def test_malformed_non_empty_submission_is_rejected(raw):
    with pytest.raises(StudentMatrixError):
        parse_submitted_matriz_id(raw)


def test_whitespace_only_submission_is_still_the_explicit_clear():
    # Um campo so com espacos e um campo vazio, nao lixo.
    assert parse_submitted_matriz_id("  ") is None


def test_parser_does_not_accept_what_int_would_silently_coerce():
    """``int()`` is laxer than the form contract, so the parser is not ``int()``."""
    # Provas de que int() aceitaria estes valores...
    assert int("1_0") == 10
    assert int("١٢") == 12  # digitos arabico-indianos
    assert int("+5") == 5
    # ... e de que o contrato do formulario nao os aceita.
    for raw in ("1_0", "١٢", "+5"):
        with pytest.raises(StudentMatrixError):
            parse_submitted_matriz_id(raw)


# --------------------------------------------------------------------------
# Mutation probe: the pre-fix read conflated garbage with the explicit clear
# --------------------------------------------------------------------------


def test_probe_pre_fix_type_int_read_would_have_cleared_on_malformed_input():
    """Without the fix, "abc" and "" are indistinguishable at the read site.

    This reproduces the retired expression against a real request context. It
    fails closed only because the route no longer uses it.
    """
    for raw in ("abc", ""):
        with main.app.test_request_context(
            "/admin/editar_aluno/1", method="POST", data={"matriz_id": raw}
        ):
            # Campo presente nos dois casos...
            assert "matriz_id" in request.form
            # ... e a leitura antiga devolve None nos dois, ou seja, "limpar".
            assert request.form.get("matriz_id", type=int) is None

    # A leitura endurecida separa os dois casos.
    assert parse_submitted_matriz_id("") is None
    with pytest.raises(StudentMatrixError):
        parse_submitted_matriz_id("abc")


# --------------------------------------------------------------------------
# Route fixture (private prod-1 database; never touches any runtime database)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    app = main.app
    temp_root = tmp_path_factory.mktemp("am2h_matrix_hardening")
    temp_database = temp_root / "am2h.db"

    previous = {
        "env": os.environ.get("APP_DATABASE"),
        "main": main.DATABASE,
        "module": app_db_module.DATABASE,
        "config": app.config.get("DATABASE_PATH"),
        "testing": app.config.get("TESTING"),
        "uploads": app.config.get("UPLOAD_FOLDER"),
    }
    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["TESTING"] = True
    app.config["UPLOAD_FOLDER"] = str(temp_root / "uploads")

    try:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass
            main.init_db()
        with app.test_client() as test_client:
            yield test_client
    finally:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass
        if previous["env"] is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = previous["env"]
        main.DATABASE = previous["main"]
        app_db_module.DATABASE = previous["module"]
        app.config["DATABASE_PATH"] = previous["config"]
        app.config["TESTING"] = previous["testing"]
        app.config["UPLOAD_FOLDER"] = previous["uploads"]


def _login_admin(test_client):
    with test_client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"
        sess["access_level"] = "admin_total"
        sess["perfil"] = "Admin"


def _seed_route_fixture(suffix):
    """Two Cursos, three Matrizes, two Turmas and one Aluno bound to T1/M1."""
    with main.app.app_context():
        conn = main.get_db_connection()
        ids = {}
        for chave, codigo in (("c1", f"H2A{suffix}"), ("c2", f"H2B{suffix}")):
            ids[chave] = conn.execute(
                "INSERT INTO cursos (nome, codigo, duracao_periodos, status) "
                "VALUES (?,?,?,?) RETURNING id",
                (f"Curso {codigo}", codigo, 8, "ativo"),
            ).fetchone()["id"]
        for chave, curso, nome in (
            ("m1", "c1", f"Matriz A1 {suffix}"),
            ("m2", "c1", f"Matriz A2 {suffix}"),
            ("other", "c2", f"Matriz B1 {suffix}"),
        ):
            ids[chave] = conn.execute(
                "INSERT INTO matrizes_atividades (curso_id, nome, status, "
                "horas_aac_obrigatorias, horas_extensao_obrigatorias) "
                "VALUES (?,?,?,?,?) RETURNING id",
                (ids[curso], nome, "vigente", 120, 60),
            ).fetchone()["id"]
        for chave, curso, matriz, codigo in (
            ("t1", "c1", "m1", f"H2T1{suffix}"),
            ("t4", "c2", "other", f"H2T4{suffix}"),
        ):
            ids[chave] = conn.execute(
                "INSERT INTO turmas (nome, status, numero, curso_id, matriz_id, "
                "ano_inicio, semestre_inicio, codigo) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
                (codigo, "Ativa", 1, ids[curso], ids[matriz], 2026, 1, codigo),
            ).fetchone()["id"]
        email = f"am2h.{suffix}@teste.local"
        ids["usuario"] = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?,?,?,?) RETURNING id",
            (f"Aluno AM2H {suffix}", email, main.hash_password("aluno12345"), "aluno"),
        ).fetchone()["id"]
        ids["aluno"] = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, matriz_id, status) "
            "VALUES (?,?,?,?,?,?,?) RETURNING id",
            (
                ids["usuario"],
                f"Aluno AM2H {suffix}",
                f"AM2H-{suffix}",
                email,
                ids["t1"],
                ids["m1"],
                "Ativo",
            ),
        ).fetchone()["id"]
        conn.commit()
        return ids


def _corrupt_to_out_of_set_matrix(ids):
    """Point the student at a Matrix of the other Curso.

    Write validation prevents reaching this state through the product, so it is
    installed directly, exactly as UT-AM2's corrupt-pairing regression does.
    """
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE alunos SET matriz_id=? WHERE usuario_id=?",
            (ids["other"], ids["usuario"]),
        )
        conn.commit()


def _aluno_state(usuario_id):
    with main.app.app_context():
        conn = main.get_db_connection()
        return conn.execute(
            "SELECT nome, email, matricula, turma_id, matriz_id, status "
            "FROM alunos WHERE usuario_id=?",
            (usuario_id,),
        ).fetchone()


def _usuario_state(usuario_id):
    with main.app.app_context():
        conn = main.get_db_connection()
        return conn.execute(
            "SELECT nome, email FROM usuarios WHERE id=?", (usuario_id,)
        ).fetchone()


def _turma_default(turma_id):
    with main.app.app_context():
        conn = main.get_db_connection()
        return conn.execute(
            "SELECT matriz_id FROM turmas WHERE id=?", (turma_id,)
        ).fetchone()[0]


def _matriz_select(html):
    """Isolate the ``matriz_id`` select.

    ``turmas`` and ``matrizes_atividades`` have independent id sequences, so a
    Turma option can carry the same numeric value as a Matrix option. Assertions
    about preselection are only discriminating inside the right control.
    """
    inicio = html.index('name="matriz_id"')
    fim = html.index("</select>", inicio)
    return html[inicio:fim]


def _post_editar(test_client, ids, **overrides):
    payload = {
        "nome": f"Aluno AM2H {ids['usuario']}",
        "email": f"am2h.{ids['usuario']}@teste.local",
        "matricula": f"AM2H-{ids['usuario']}",
        "turma_id": str(ids["t1"]),
        "status": "Ativo",
    }
    payload.update(overrides)
    return test_client.post(
        f"/admin/editar_aluno/{ids['usuario']}", data=payload, follow_redirects=True
    )


# --------------------------------------------------------------------------
# 1-3. Malformed non-empty matriz_id at the route
# --------------------------------------------------------------------------


def test_route_rejects_malformed_matrix_and_preserves_the_previous_one(client):
    _login_admin(client)
    ids = _seed_route_fixture("M1")

    response = _post_editar(client, ids, matriz_id="abc")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Erro controlado de validacao, e nao um sucesso silencioso.
    assert "Aluno atualizado com sucesso" not in html
    assert "matriz acadêmica selecionada é inválida" in html
    # A autoridade anterior sobreviveu: nao virou NULL.
    estado = _aluno_state(ids["usuario"])
    assert estado["matriz_id"] == ids["m1"]
    assert estado["matriz_id"] is not None


@pytest.mark.parametrize(
    "indice,raw",
    [(i, value) for i, value in enumerate(MALFORMED) if value.strip()],
)
def test_route_never_clears_the_matrix_on_any_malformed_value(client, indice, raw):
    _login_admin(client)
    ids = _seed_route_fixture(f"M2{indice}")

    _post_editar(client, ids, matriz_id=raw)

    assert _aluno_state(ids["usuario"])["matriz_id"] == ids["m1"]


def test_malformed_matrix_rolls_back_concurrent_edit_aluno_fields(client):
    _login_admin(client)
    ids = _seed_route_fixture("M3")
    antes_aluno = _aluno_state(ids["usuario"])
    antes_usuario = _usuario_state(ids["usuario"])

    response = _post_editar(
        client,
        ids,
        nome="Nome Que Nao Deve Persistir",
        email="rejeitado.am2h@teste.local",
        matricula="AM2H-REJEITADA",
        status="Inativo",
        turma_id="",
        matriz_id="abc",
    )
    assert response.status_code == 200

    depois_aluno = _aluno_state(ids["usuario"])
    depois_usuario = _usuario_state(ids["usuario"])
    # Nenhuma das edicoes simultaneas foi parcialmente gravada.
    assert tuple(depois_aluno) == tuple(antes_aluno)
    assert tuple(depois_usuario) == tuple(antes_usuario)
    assert depois_usuario["nome"] != "Nome Que Nao Deve Persistir"
    assert depois_aluno["turma_id"] == ids["t1"]
    # E o padrao da Turma continua intocado.
    assert _turma_default(ids["t1"]) == ids["m1"]


# --------------------------------------------------------------------------
# 4-5. The two legitimate readings still behave as UT-AM2 specified
# --------------------------------------------------------------------------


def test_explicit_empty_matrix_still_clears_to_null(client):
    _login_admin(client)
    ids = _seed_route_fixture("M4")

    response = _post_editar(client, ids, matriz_id="")
    assert response.status_code == 200

    assert _aluno_state(ids["usuario"])["matriz_id"] is None


def test_absent_matrix_field_still_preserves_the_current_matrix(client):
    _login_admin(client)
    ids = _seed_route_fixture("M5")

    response = _post_editar(client, ids)
    assert response.status_code == 200

    assert _aluno_state(ids["usuario"])["matriz_id"] == ids["m1"]


# --------------------------------------------------------------------------
# 6-9. Out-of-set current-Matrix preselection (corrupt/incompatible pairing)
# --------------------------------------------------------------------------


def test_out_of_set_current_matrix_is_rendered_and_selected(client):
    """The persisted authority stays visible even outside the compatible list."""
    _login_admin(client)
    ids = _seed_route_fixture("O1")
    _corrupt_to_out_of_set_matrix(ids)

    response = client.get(f"/admin/editar_aluno/{ids['usuario']}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # A lista compativel e escopada pelo Curso da Turma, entao exclui a vigente.
    with main.app.app_context():
        from app.student_matrix import list_assignable_matrices_for_student

        conn = main.get_db_connection()
        selecionaveis = {
            row["id"] for row in list_assignable_matrices_for_student(conn, ids["t1"])
        }
    assert selecionaveis == {ids["m1"], ids["m2"]}
    assert ids["other"] not in selecionaveis

    select = _matriz_select(html)
    # Ainda assim a matriz vigente e renderizada e marcada como selecionada.
    assert f'<option value="{ids["other"]}" selected>' in select
    # Nenhuma matriz compativel foi preselecionada no lugar dela.
    assert f'<option value="{ids["m1"]}" selected>' not in select
    assert f'<option value="{ids["m2"]}" selected>' not in select
    # E "Sem matriz" tambem nao foi marcada, porque a autoridade existe.
    assert '<option value="" selected>' not in select
    # Exatamente uma opcao selecionada no controle de matriz.
    assert select.count(" selected>") == 1


def test_absent_submit_preserves_the_out_of_set_current_matrix(client):
    """Scenario A: no intent over the Matrix must not resolve the corruption."""
    _login_admin(client)
    ids = _seed_route_fixture("O2")
    _corrupt_to_out_of_set_matrix(ids)

    response = _post_editar(client, ids)
    assert response.status_code == 200

    estado = _aluno_state(ids["usuario"])
    # A matriz persistida continua sendo a vigente, corrompida e tudo.
    assert estado["matriz_id"] == ids["other"]
    # Nenhuma substituicao silenciosa por uma matriz compativel.
    assert estado["matriz_id"] not in (ids["m1"], ids["m2"])
    # O par incompativel falha fechado em vez de ser gravado como valido.
    html = response.get_data(as_text=True)
    assert "Aluno atualizado com sucesso" not in html
    assert "não pertence ao curso da turma de destino" in html


def test_explicit_compatible_matrix_corrects_the_out_of_set_pairing(client):
    """Scenario B: the admin can fix the corruption by choosing explicitly."""
    _login_admin(client)
    ids = _seed_route_fixture("O3")
    _corrupt_to_out_of_set_matrix(ids)

    response = _post_editar(client, ids, matriz_id=str(ids["m2"]))
    assert response.status_code == 200
    assert "Aluno atualizado com sucesso" in response.get_data(as_text=True)

    estado = _aluno_state(ids["usuario"])
    assert estado["matriz_id"] == ids["m2"]
    assert estado["turma_id"] == ids["t1"]
    assert _turma_default(ids["t1"]) == ids["m1"]


def test_resubmitting_the_incompatible_current_matrix_fails_closed(client):
    """Scenario C: re-affirming the corrupt choice is rejected, not accepted."""
    _login_admin(client)
    ids = _seed_route_fixture("O4")
    _corrupt_to_out_of_set_matrix(ids)

    response = _post_editar(client, ids, nome="Nome Rejeitado", matriz_id=str(ids["other"]))
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Aluno atualizado com sucesso" not in html
    assert "não pertence ao curso da turma do aluno" in html

    estado = _aluno_state(ids["usuario"])
    # Sem substituicao silenciosa e sem limpeza: o estado anterior permanece.
    assert estado["matriz_id"] == ids["other"]
    assert estado["nome"] != "Nome Rejeitado"


# --------------------------------------------------------------------------
# Domain-level guard: the parser is not a second copy of the Matrix rules
# --------------------------------------------------------------------------


def test_parser_delegates_compatibility_to_the_existing_authority():
    """A syntactically valid id is parsed, then validated by student_matrix."""
    from app.student_matrix import validate_student_matrix_for_turma

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    curso = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('C','C',8) RETURNING id"
    ).fetchone()["id"]
    outro = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos) VALUES('D','D',8) RETURNING id"
    ).fetchone()["id"]
    matriz = conn.execute(
        "INSERT INTO matrizes_atividades(curso_id,nome) VALUES(?,'M') RETURNING id", (curso,)
    ).fetchone()["id"]
    turma = conn.execute(
        "INSERT INTO turmas(nome,numero,curso_id,ano_inicio,semestre_inicio,codigo) "
        "VALUES('T',1,?,2026,1,'T') RETURNING id",
        (outro,),
    ).fetchone()["id"]

    # O parser aceita a sintaxe...
    parsed = parse_submitted_matriz_id(str(matriz))
    assert parsed == matriz
    # ... e a incompatibilidade continua sendo decidida por student_matrix.
    with pytest.raises(StudentMatrixError):
        validate_student_matrix_for_turma(conn, matriz_id=parsed, turma_id=turma)
    # Um id inexistente tambem e recusado la, nao aqui.
    assert parse_submitted_matriz_id("99999") == 99999
    with pytest.raises(StudentMatrixError):
        validate_student_matrix_for_turma(conn, matriz_id=99999, turma_id=None)
