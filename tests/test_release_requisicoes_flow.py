import io
import os
import sys
import uuid

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
import main


@pytest.fixture()
def isolated_client(tmp_path):
    app = main.app
    temp_database = tmp_path / "release_requisicoes_flow.db"
    temp_uploads = tmp_path / "uploads"
    temp_documents = tmp_path / "documentos_alunos"
    os.makedirs(temp_uploads, exist_ok=True)
    os.makedirs(temp_documents, exist_ok=True)

    original_database = main.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")
    original_upload_folder = app.config.get("UPLOAD_FOLDER")
    original_documents_folder = app.config.get("DOCUMENTOS_ALUNOS_FOLDER")

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["UPLOAD_FOLDER"] = str(temp_uploads)
    app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(temp_documents)
    app.config["TESTING"] = True

    with app.app_context():
        try:
            main.close_db_connection(None)
        except Exception:
            pass
        main.init_db()

    client = app.test_client()

    try:
        yield client, str(temp_uploads), str(temp_documents)
    finally:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass

        main.DATABASE = original_database
        app_db_module.DATABASE = original_database
        if original_config_database_path is None:
            app.config.pop("DATABASE_PATH", None)
        else:
            app.config["DATABASE_PATH"] = original_config_database_path
        if original_upload_folder is None:
            app.config.pop("UPLOAD_FOLDER", None)
        else:
            app.config["UPLOAD_FOLDER"] = original_upload_folder
        if original_documents_folder is None:
            app.config.pop("DOCUMENTOS_ALUNOS_FOLDER", None)
        else:
            app.config["DOCUMENTOS_ALUNOS_FOLDER"] = original_documents_folder

        if original_env_database is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = original_env_database


def _login(client, email, senha):
    response = client.post(
        "/login",
        data={"email": email, "senha": senha},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def _seed_base_data():
    suffix = uuid.uuid4().hex[:8]
    curso_codigo = f"REQ-{suffix}"
    turma_codigo = f"{curso_codigo}-T01"
    aluno_email = f"release.req.aluno.{suffix}@teste.local"
    aluno_senha = "aluno123"
    atividade_nome = f"Atividade Release Req {suffix}"

    with main.app.app_context():
        conn = main.get_db_connection()

        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
            ("Curso Release Requisições", curso_codigo, 8, "ativo"),
        )
        curso_id = conn.execute(
            "SELECT id FROM cursos WHERE codigo = ?",
            (curso_codigo,),
        ).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO turmas (nome, ano, semestre, turno, status, numero, curso_id, codigo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("Turma Release Requisições", 2026, 1, "Manha", "Ativa", 1, curso_id, turma_codigo),
        )
        turma_id = conn.execute(
            "SELECT id FROM turmas WHERE codigo = ?",
            (turma_codigo,),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Aluno Release Req", aluno_email, main.hash_password(aluno_senha), "aluno", "usuario"),
        )
        aluno_usuario_id = conn.execute(
            "SELECT id FROM usuarios WHERE email = ?",
            (aluno_email,),
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (aluno_usuario_id, "Aluno Release Req", f"{turma_codigo}.001", aluno_email, turma_id, "Ativo"),
        )
        aluno_id = conn.execute(
            "SELECT id FROM alunos WHERE usuario_id = ?",
            (aluno_usuario_id,),
        ).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("1 - Grupo Release", atividade_nome, "Fluxo release", 60, "Acadêmica Complementar", 0),
        )
        atividade_id = conn.execute(
            "SELECT id FROM atividades WHERE nome = ?",
            (atividade_nome,),
        ).fetchone()["id"]

        conn.commit()

    return {
        "aluno_email": aluno_email,
        "aluno_senha": aluno_senha,
        "aluno_id": aluno_id,
        "atividade_id": atividade_id,
        "atividade_nome": atividade_nome,
    }


def test_release_requisicoes_flow_happy_path_without_attachment(isolated_client):
    client, _, _ = isolated_client
    base = _seed_base_data()

    _login(client, base["aluno_email"], base["aluno_senha"])

    create_response = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": str(base["atividade_id"]),
            "nome_evento": "Evento Release Sem Anexo",
            "data_evento": "2026-05-10",
            "horas_solicitadas": "12",
            "observacao": "Criada pelo aluno",
        },
        follow_redirects=False,
    )
    assert create_response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        req = conn.execute(
            """
            SELECT id, status, horas_solicitadas, horas_deferidas, observacao, nome_evento
              FROM requisicoes
             WHERE aluno_id = ? AND nome_evento = ?
             ORDER BY id DESC
             LIMIT 1
            """,
            (base["aluno_id"], "Evento Release Sem Anexo"),
        ).fetchone()
    assert req is not None
    req_id = req["id"]
    assert req["status"] == "Pendente"
    assert float(req["horas_solicitadas"]) == 12.0

    aluno_list = client.get("/aluno/requisicoes")
    assert aluno_list.status_code == 200
    assert base["atividade_nome"] in aluno_list.get_data(as_text=True)

    aluno_detail = client.get(f"/aluno/requisicoes/{req_id}?view=1")
    assert aluno_detail.status_code == 200
    detail_html = aluno_detail.get_data(as_text=True)
    assert "Evento Release Sem Anexo" in detail_html

    aluno_edit = client.post(
        f"/aluno/requisicoes/{req_id}?edit=1",
        data={
            "atividade_id": str(base["atividade_id"]),
            "nome_evento": "Evento Release Sem Anexo Editado",
            "horas_solicitadas": "14",
            "data_evento": "2026-05-11",
            "observacao": "Editada pelo aluno",
        },
        follow_redirects=False,
    )
    assert aluno_edit.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        req_edit = conn.execute(
            """
            SELECT nome_evento, horas_solicitadas, data_evento, observacao, status
              FROM requisicoes
             WHERE id = ?
            """,
            (req_id,),
        ).fetchone()
    assert req_edit is not None
    assert req_edit["nome_evento"] == "Evento Release Sem Anexo Editado"
    assert float(req_edit["horas_solicitadas"]) == 14.0
    assert req_edit["data_evento"] == "2026-05-11"
    assert req_edit["observacao"] == "Editada pelo aluno"
    assert req_edit["status"] == "Pendente"

    _login(client, "admin@ej.edu.br", "admin123")

    admin_list = client.get("/admin/requisicoes")
    assert admin_list.status_code == 200
    assert "Evento Release Sem Anexo Editado" in admin_list.get_data(as_text=True)

    admin_process_page = client.get(f"/admin/processar_requisicao/{req_id}")
    assert admin_process_page.status_code == 200

    admin_process = client.post(
        f"/admin/processar_requisicao/{req_id}",
        data={
            "status": "Deferida Parcialmente",
            "horas_deferidas": "6",
            "observacao": "Processada no release",
        },
        follow_redirects=False,
    )
    assert admin_process.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        req_after_process = conn.execute(
            """
            SELECT status, horas_deferidas, observacao, data_processamento, admin_id
              FROM requisicoes
             WHERE id = ?
            """,
            (req_id,),
        ).fetchone()
    assert req_after_process is not None
    assert req_after_process["status"] == "Deferida Parcialmente"
    assert float(req_after_process["horas_deferidas"]) == 6.0
    assert req_after_process["observacao"] == "Processada no release"
    assert req_after_process["data_processamento"] is not None
    assert req_after_process["admin_id"] is not None

    admin_delete = client.post(f"/admin/requisicoes/{req_id}/excluir")
    assert admin_delete.status_code == 204

    with main.app.app_context():
        conn = main.get_db_connection()
        deleted_req = conn.execute("SELECT id FROM requisicoes WHERE id = ?", (req_id,)).fetchone()
        deleted_files = conn.execute(
            "SELECT COUNT(*) FROM requisicao_arquivos WHERE requisicao_id = ?",
            (req_id,),
        ).fetchone()[0]
    assert deleted_req is None
    assert deleted_files == 0


def test_release_requisicoes_flow_with_attachment(isolated_client):
    client, upload_root, documents_root = isolated_client
    base = _seed_base_data()

    _login(client, base["aluno_email"], base["aluno_senha"])

    create_with_file = client.post(
        "/aluno/nova-requisicao",
        data={
            "atividade_id": str(base["atividade_id"]),
            "nome_evento": "Evento Release Com Anexo",
            "data_evento": "2026-06-12",
            "horas_solicitadas": "10",
            "observacao": "Com comprovante",
            "comprovantes_files": (io.BytesIO(b"%PDF-1.4\nrelease-test\n"), "comprovante-release.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert create_with_file.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        req = conn.execute(
            """
            SELECT id, arquivo_comprovante
              FROM requisicoes
             WHERE aluno_id = ? AND nome_evento = ?
             ORDER BY id DESC
             LIMIT 1
            """,
            (base["aluno_id"], "Evento Release Com Anexo"),
        ).fetchone()
        assert req is not None
        req_id = req["id"]
        assert req["arquivo_comprovante"]

        anexos = conn.execute(
            "SELECT filename FROM requisicao_arquivos WHERE requisicao_id = ? ORDER BY id",
            (req_id,),
        ).fetchall()

    assert len(anexos) >= 1
    saved_relpath = anexos[0]["filename"]
    saved_docs_abspath = os.path.join(documents_root, saved_relpath)
    saved_upload_abspath = os.path.join(upload_root, saved_relpath)
    assert os.path.isfile(saved_docs_abspath)
    assert not os.path.exists(saved_upload_abspath)

    uploaded_response = client.get(f"/uploads/{saved_relpath}", follow_redirects=False)
    assert uploaded_response.status_code == 200


def test_release_requisicoes_flow_reads_legacy_attachment_from_uploads(isolated_client):
    client, upload_root, _documents_root = isolated_client
    base = _seed_base_data()

    _login(client, base["aluno_email"], base["aluno_senha"])

    legacy_relpath = f"aluno_{base['aluno_id']}/req_legado/comprovante-legado.pdf"
    legacy_abspath = os.path.join(upload_root, legacy_relpath)
    os.makedirs(os.path.dirname(legacy_abspath), exist_ok=True)
    with open(legacy_abspath, "wb") as handle:
        handle.write(b"%PDF-1.4\nlegacy-upload\n")

    legacy_response = client.get(f"/uploads/{legacy_relpath}", follow_redirects=False)

    assert legacy_response.status_code == 200
