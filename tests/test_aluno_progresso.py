import os
import sqlite3
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
import main


@pytest.fixture()
def client(tmp_path):
    app = main.app
    temp_database = tmp_path / "aluno_progresso_test.db"
    original_database = main.DATABASE
    original_env = os.environ.get("APP_DATABASE")

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)

    with app.app_context():
        try:
            main.close_db_connection(None)
        except Exception:
            pass
        main.init_db()
        yield app.test_client()
        try:
            main.close_db_connection(None)
        except Exception:
            pass

    main.DATABASE = original_database
    app_db_module.DATABASE = original_database
    if original_env is None:
        os.environ.pop("APP_DATABASE", None)
    else:
        os.environ["APP_DATABASE"] = original_env


def _login_aluno(client, usuario_id: int, nome: str):
    with client.session_transaction() as sess:
        sess["user_id"] = usuario_id
        sess["user_type"] = "aluno"
        sess["user_name"] = nome


def _open_test_db():
    conn = sqlite3.connect(main.DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _create_progress_context(conn, *, email: str, matricula: str, matriz_nome: str, turma_numero: int, aluno_nome: str):
    main.ensure_matrizes_atividades_table(conn)
    main.ensure_matriz_atividade_links_table(conn)
    main.ensure_turmas_matriz_schema(conn)

    curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
    assert curso is not None
    turma_codigo = main.gerar_codigo_turma(curso["codigo"], turma_numero)

    matriz_id = conn.execute(
        """
        INSERT INTO matrizes_atividades (
            curso_id, nome, versao, status, data_inicio_vigencia,
            horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (curso["id"], matriz_nome, "2026.1", "vigente", "2026-01-01", 160, 80, "Teste progresso aluno"),
    ).fetchone()["id"]
    turma_id = conn.execute(
        """
        INSERT INTO turmas (
            nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
            ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (turma_codigo, None, None, "Noite", "Ativa", turma_numero, curso["id"], matriz_id, 2026, 1, 2029, 2, turma_codigo),
    ).fetchone()["id"]
    usuario_id = conn.execute(
        "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
        (aluno_nome, email, main.hash_password("aluno123"), "aluno"),
    ).fetchone()["id"]
    aluno_id = conn.execute(
        "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (usuario_id, aluno_nome, matricula, email, turma_id, "Ativo"),
    ).fetchone()["id"]
    return {
        "curso": curso,
        "matriz_id": matriz_id,
        "turma_id": turma_id,
        "usuario_id": usuario_id,
        "aluno_id": aluno_id,
    }


def _insert_atividade(
    conn,
    *,
    grupo: str,
    nome: str,
    tipo_atividade: str,
    tem_limitacao: int = 0,
    tipo_limitacao: str | None = None,
    limite_total: int | None = None,
    limite_semestral: int | None = None,
):
    return conn.execute(
        """
        INSERT INTO atividades (
            grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
            limite_horas_total, limite_horas_semestral, documentos_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (grupo, nome, None, tipo_atividade, tem_limitacao, tipo_limitacao, limite_total, limite_semestral, None),
    ).fetchone()["id"]


def _link_atividade_na_matriz(conn, matriz_id: int, atividade_id: int):
    conn.execute(
        "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
        (matriz_id, atividade_id),
    )


def _insert_requisicao(
    conn,
    *,
    aluno_id: int,
    atividade_id: int,
    data_solicitacao: str,
    data_evento: str,
    horas_solicitadas: float,
    status: str,
    horas_deferidas: float | None = None,
    nome_evento: str = "Evento Teste",
    observacao: str = "Teste",
):
    conn.execute(
        """
        INSERT INTO requisicoes (
            aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas,
            horas_deferidas, status, nome_evento, observacao
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas, horas_deferidas, status, nome_evento, observacao),
    )


def test_aluno_progresso_renderiza_catalogo_e_agrega_semestres(client):
    atividade_aac = "Palestras Progresso Automatizado"
    atividade_ext = "Projeto Extensão Progresso Automatizado"
    atividade_uso = "Monitoria Legado Progresso Automatizado"
    atividade_historica = "Atividade Histórica Fora da Matriz"
    atividade_limite_sem = "Semestral no Limite"
    atividade_limite_total = "Total no Limite"
    email = "aluno.progresso@teste.local"
    matricula = "MAT-PROGRESSO-001"
    matriz_nome = "Matriz Progresso Aluno"

    conn = _open_test_db()
    try:
        context = _create_progress_context(
            conn,
            email=email,
            matricula=matricula,
            matriz_nome=matriz_nome,
            turma_numero=93,
            aluno_nome="Aluno Progresso",
        )
        usuario_id = context["usuario_id"]
        aluno_id = context["aluno_id"]
        matriz_id = context["matriz_id"]

        atividade_aac_id = _insert_atividade(
            conn,
            grupo="1 - Grupo Palestras",
            nome=atividade_aac,
            tipo_atividade="Acadêmica Complementar",
            tem_limitacao=1,
            tipo_limitacao="semestral",
            limite_semestral=10,
        )
        atividade_ext_id = _insert_atividade(
            conn,
            grupo="NA",
            nome=atividade_ext,
            tipo_atividade="Extensão Universitária",
        )
        atividade_uso_id = _insert_atividade(
            conn,
            grupo="2 - Grupo Monitoria",
            nome=atividade_uso,
            tipo_atividade="Acadêmica Complementar",
            tem_limitacao=1,
            tipo_limitacao="total",
            limite_total=20,
        )
        atividade_historica_id = _insert_atividade(
            conn,
            grupo="3 - Grupo Histórico",
            nome=atividade_historica,
            tipo_atividade="Acadêmica Complementar",
        )
        atividade_limite_sem_id = _insert_atividade(
            conn,
            grupo="4 - Grupo Limite Sem",
            nome=atividade_limite_sem,
            tipo_atividade="Acadêmica Complementar",
            tem_limitacao=1,
            tipo_limitacao="semestral",
            limite_semestral=40,
        )
        atividade_limite_total_id = _insert_atividade(
            conn,
            grupo="5 - Grupo Limite Total",
            nome=atividade_limite_total,
            tipo_atividade="Acadêmica Complementar",
            tem_limitacao=1,
            tipo_limitacao="total",
            limite_total=20,
        )
        _link_atividade_na_matriz(conn, matriz_id, atividade_aac_id)
        _link_atividade_na_matriz(conn, matriz_id, atividade_ext_id)
        _link_atividade_na_matriz(conn, matriz_id, atividade_limite_sem_id)
        _link_atividade_na_matriz(conn, matriz_id, atividade_limite_total_id)

        _insert_requisicao(
            conn,
            aluno_id=aluno_id,
            atividade_id=atividade_aac_id,
            data_solicitacao="2025-11-12 10:00:00",
            data_evento="2025-11-12",
            horas_solicitadas=8,
            horas_deferidas=6,
            status="Deferida Parcialmente",
            nome_evento="Palestra 1",
            observacao="Teste parcial",
        )
        _insert_requisicao(
            conn,
            aluno_id=aluno_id,
            atividade_id=atividade_aac_id,
            data_solicitacao="2026-03-18 10:00:00",
            data_evento="2026-03-18",
            horas_solicitadas=4,
            status="Deferida",
            nome_evento="Palestra 2",
            observacao="Teste deferida",
        )
        _insert_requisicao(
            conn,
            aluno_id=aluno_id,
            atividade_id=atividade_aac_id,
            data_solicitacao="2026-09-10 10:00:00",
            data_evento="2026-09-10",
            horas_solicitadas=5,
            status="Deferida",
            nome_evento="Palestra futura",
            observacao="Deve ser ignorada",
        )
        _insert_requisicao(
            conn,
            aluno_id=aluno_id,
            atividade_id=atividade_uso_id,
            data_solicitacao="2025-10-05 10:00:00",
            data_evento="2025-10-05",
            horas_solicitadas=3,
            status="Deferida",
            nome_evento="Monitoria",
            observacao="Uso fora do catálogo atual",
        )
        _insert_requisicao(
            conn,
            aluno_id=aluno_id,
            atividade_id=atividade_historica_id,
            data_solicitacao="2025-08-01 10:00:00",
            data_evento="2025-08-01",
            horas_solicitadas=7,
            status="Pendente",
            nome_evento="Histórico sem deferimento",
            observacao="Deve aparecer com 0h",
        )
        _insert_requisicao(
            conn,
            aluno_id=aluno_id,
            atividade_id=atividade_limite_sem_id,
            data_solicitacao="2025-11-20 09:00:00",
            data_evento="2025-11-20",
            horas_solicitadas=25,
            status="Deferida",
            nome_evento="Semestral 1",
        )
        _insert_requisicao(
            conn,
            aluno_id=aluno_id,
            atividade_id=atividade_limite_sem_id,
            data_solicitacao="2025-12-02 09:00:00",
            data_evento="2025-12-02",
            horas_solicitadas=15,
            status="Deferida",
            nome_evento="Semestral 2",
        )
        _insert_requisicao(
            conn,
            aluno_id=aluno_id,
            atividade_id=atividade_limite_total_id,
            data_solicitacao="2026-02-11 09:00:00",
            data_evento="2026-02-11",
            horas_solicitadas=12,
            status="Deferida",
            nome_evento="Total 1",
        )
        _insert_requisicao(
            conn,
            aluno_id=aluno_id,
            atividade_id=atividade_limite_total_id,
            data_solicitacao="2026-03-09 09:00:00",
            data_evento="2026-03-09",
            horas_solicitadas=8,
            status="Deferida",
            nome_evento="Total 2",
        )
        conn.commit()
    finally:
        conn.close()

    _login_aluno(client, usuario_id, "Aluno Progresso")

    response_json = client.get("/aluno/progresso?format=json")
    assert response_json.status_code == 200
    payload = response_json.get_json()
    assert payload is not None
    assert payload["semestres"] == ["2025/2", "2026/1"]
    assert payload["has_extensao_na_matriz"] is True

    atividades = {item["nome"]: item for item in payload["atividades"]}
    assert atividade_aac in atividades
    assert atividade_ext in atividades
    assert atividade_uso in atividades
    assert atividade_historica in atividades
    assert atividade_limite_sem in atividades
    assert atividade_limite_total in atividades

    aac = atividades[atividade_aac]
    assert aac["grupo"] == "1"
    assert aac["limite"] == "10h/sem"
    assert aac["semestres"]["2025/2"] == 6.0
    assert aac["semestres"]["2026/1"] == 4.0
    assert aac["total"] == 10.0

    extensao = atividades[atividade_ext]
    assert extensao["grupo"] == "-"
    assert extensao["limite"] == "-"
    assert extensao["total"] == 0.0

    legado = atividades[atividade_uso]
    assert legado["grupo"] == "2"
    assert legado["limite"] == "20h total"
    assert legado["semestres"]["2025/2"] == 3.0
    assert legado["total"] == 3.0

    historica = atividades[atividade_historica]
    assert historica["grupo"] == "3"
    assert historica["semestres"]["2025/2"] == 0.0
    assert historica["total"] == 0.0

    limite_sem = atividades[atividade_limite_sem]
    assert limite_sem["semestres"]["2025/2"] == 40.0
    assert limite_sem["semestres_limitados"]["2025/2"] is True
    assert limite_sem["total_limitado"] is False

    limite_total = atividades[atividade_limite_total]
    assert limite_total["semestres"]["2026/1"] == 20.0
    assert limite_total["total"] == 20.0
    assert limite_total["total_limitado"] is True

    response_html = client.get("/aluno/progresso")
    assert response_html.status_code == 200
    html = response_html.get_data(as_text=True)
    assert "table-progresso" in html
    assert "Progresso do aluno" in html
    assert 'id="progresso-tipo"' in html
    assert 'value="aac" selected' in html
    assert ">Tipo<" not in html
    assert "2025/2" in html
    assert "2026/1" in html
    assert 'badge-grupo">1<' in html
    assert "10h/sem" in html
    assert atividade_ext not in html
    assert "progresso-limitado" in html
    assert atividade_limite_sem in html
    assert atividade_limite_total in html

    response_html_ext = client.get("/aluno/progresso?tipo=extensao")
    assert response_html_ext.status_code == 200
    html_ext = response_html_ext.get_data(as_text=True)
    assert 'value="extensao" selected' in html_ext
    assert atividade_ext in html_ext
    assert atividade_aac not in html_ext


def test_aluno_progresso_com_somente_aac(client):
    conn = _open_test_db()
    try:
        context = _create_progress_context(
            conn,
            email="aluno.so.aac@teste.local",
            matricula="MAT-PROGRESSO-AAC-001",
            matriz_nome="Matriz Somente AAC",
            turma_numero=94,
            aluno_nome="Aluno Só AAC",
        )
        atividade_id = _insert_atividade(
            conn,
            grupo="1 - Grupo AAC",
            nome="Atividade Somente AAC",
            tipo_atividade="Acadêmica Complementar",
            tem_limitacao=1,
            tipo_limitacao="semestral",
            limite_semestral=12,
        )
        _link_atividade_na_matriz(conn, context["matriz_id"], atividade_id)
        _insert_requisicao(
            conn,
            aluno_id=context["aluno_id"],
            atividade_id=atividade_id,
            data_solicitacao="2026-04-10 09:00:00",
            data_evento="2026-04-10",
            horas_solicitadas=5,
            status="Deferida",
            nome_evento="AAC",
        )
        conn.commit()
    finally:
        conn.close()

    _login_aluno(client, context["usuario_id"], "Aluno Só AAC")

    payload = client.get("/aluno/progresso?format=json").get_json()
    assert payload is not None
    assert payload["semestres"] == ["2026/1"]
    assert payload["has_extensao_na_matriz"] is False
    assert len(payload["atividades"]) == 1
    assert payload["atividades"][0]["tipo_atividade"] == "Acadêmica Complementar"
    assert payload["atividades"][0]["grupo"] == "1"
    assert payload["atividades"][0]["total"] == 5.0

    html = client.get("/aluno/progresso").get_data(as_text=True)
    assert "Atividade Somente AAC" in html
    assert 'id="progresso-tipo"' not in html
    assert "Nenhuma atividade disponível nesta seção." not in html


def test_aluno_progresso_com_somente_extensao(client):
    conn = _open_test_db()
    try:
        context = _create_progress_context(
            conn,
            email="aluno.so.ext@teste.local",
            matricula="MAT-PROGRESSO-EXT-001",
            matriz_nome="Matriz Somente Extensão",
            turma_numero=95,
            aluno_nome="Aluno Só Extensão",
        )
        atividade_id = _insert_atividade(
            conn,
            grupo="NA",
            nome="Atividade Somente Extensão",
            tipo_atividade="Extensão Universitária",
            tem_limitacao=1,
            tipo_limitacao="total",
            limite_total=30,
        )
        _link_atividade_na_matriz(conn, context["matriz_id"], atividade_id)
        _insert_requisicao(
            conn,
            aluno_id=context["aluno_id"],
            atividade_id=atividade_id,
            data_solicitacao="2025-09-11 09:00:00",
            data_evento="2025-09-11",
            horas_solicitadas=9,
            horas_deferidas=7,
            status="Deferida Parcialmente",
            nome_evento="Extensão",
        )
        conn.commit()
    finally:
        conn.close()

    _login_aluno(client, context["usuario_id"], "Aluno Só Extensão")

    payload = client.get("/aluno/progresso?format=json").get_json()
    assert payload is not None
    assert payload["semestres"] == ["2025/2"]
    assert payload["has_extensao_na_matriz"] is True
    assert len(payload["atividades"]) == 1
    assert payload["atividades"][0]["tipo_atividade"] == "Extensão Universitária"
    assert payload["atividades"][0]["grupo"] == "-"
    assert payload["atividades"][0]["limite"] == "30h total"
    assert payload["atividades"][0]["total"] == 7.0

    html = client.get("/aluno/progresso").get_data(as_text=True)
    assert "Atividade Somente Extensão" in html
    assert 'id="progresso-tipo"' not in html
    assert "badge-grupo" not in html or "G1" not in html
