"""Modelos para preenchimento -- DOCX templates of an activity version (schema v19).

Covers the validator, the lifecycle on a draft (add, replace, withdraw, with
history and preserved bytes), the freeze policy (a frozen version refuses
every change; a new version and a semantic successor copy the active
templates), the database immutability triggers, the admin download and the
route authorization.
"""
from __future__ import annotations

import hashlib
import io
import re
import sqlite3

import pytest

import main
from app.activity_catalog import apply_activity_version_semantic_changes
from app.activity_document_templates import (
    DocumentTemplateRefused,
    TemplateUpload,
    add_template,
    copy_active_templates,
    list_version_templates,
    read_template_upload,
)
from app.db import write_transaction
from app.docx_validation import DocxRejected, validate_docx
from app.prod1_document_templates_ddl import DOCUMENT_TEMPLATE_MAX_BYTES, DOCX_MIME_TYPE
from tests.canonical_matrix_test_support import login_admin
from tests.docx_test_support import ANEXO_3_TITULO, MACRO_MAIN, TEMPLATE_MAIN, corrupt_crc, make_docx
from tests.versioned_test_support import isolated_versioned_app_env

ANEXO_3 = make_docx("Anexo 3 — Leitura de livro/filme (arquivo sintético de teste)")
ANEXO_5 = make_docx(
    "Anexo 5 — Atividades de monitoria, apoio institucional e visitas técnicas (arquivo sintético de teste)"
)


# --------------------------------------------------------------- validator


@pytest.mark.parametrize("content", [
    make_docx(), make_docx(external_hyperlink=True), make_docx(printer_settings=True),
    # Word records the author's local template for a document made from it.
    make_docx(external_template=True, template_target="file:///C:/Users/autor/Modelos/Declaracao.dotx"),
    make_docx(external_template=True, template_target="C:\\Modelos\\Declaracao.dotx"),
])
def test_a_plain_word_document_is_accepted(content):
    validate_docx(content)


@pytest.mark.parametrize("target", [
    "https://example.test/modelo.dotm", "http://10.0.0.1/m.dotm", "\\\\servidor\\modelos\\m.dotm",
    "file://servidor/modelos/m.dotm", "ftp://example.test/m.dotm", "//servidor/m.dotm",
])
def test_a_template_attached_from_the_network_is_refused(target):
    with pytest.raises(DocxRejected) as refused:
        validate_docx(make_docx(external_template=True, template_target=target))
    assert refused.value.code == "EXTERNAL_RELATIONSHIP"


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"%PDF-1.7\n%fake", "NOT_ZIP"),
        (b"MZ\x90\x00" + b"\x00" * 64, "NOT_ZIP"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, "NOT_ZIP"),  # .doc / encrypted Office
        (make_docx(main_type=MACRO_MAIN), "ACTIVE_CONTENT"),
        (make_docx(main_type=TEMPLATE_MAIN), "ACTIVE_CONTENT"),
        (make_docx(vba_project=True), "ACTIVE_CONTENT"),
        (make_docx(embedded_exe=True), "ACTIVE_CONTENT"),
        (make_docx(external_template=True), "EXTERNAL_RELATIONSHIP"),
        (make_docx(doctype=True), "XML_DTD"),
        (corrupt_crc(make_docx()), "ZIP_DAMAGED"),
    ],
)
def test_hostile_or_broken_packages_are_refused(content, code):
    with pytest.raises(DocxRejected) as refused:
        validate_docx(content)
    assert refused.value.code == code
    assert refused.value.user_message


def test_a_decompression_bomb_is_refused_before_it_is_expanded():
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(make_docx())) as source, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bomb:
        for info in source.infolist():
            bomb.writestr(info, source.read(info))
        bomb.writestr("word/media/huge.png", b"\x89PNG" + b"\x00" * (3 * 1024 * 1024))
    with pytest.raises(DocxRejected) as refused:
        validate_docx(buffer.getvalue())
    assert refused.value.code == "ZIP_BOMB"


class _Upload:
    def __init__(self, filename, content):
        self.filename = filename
        self.stream = io.BytesIO(content)


def test_the_upload_reader_bounds_the_size_checks_the_extension_and_keeps_an_inert_name():
    upload = read_template_upload(_Upload("C:\\pasta\\Anexo 5  —  visitas técnicas.docx", ANEXO_3))
    assert upload.filename == "Anexo 5 — visitas técnicas.docx"
    assert upload.content == ANEXO_3
    for filename, content, code in (
        ("modelo.pdf", ANEXO_3, "EXTENSION"),
        ("modelo.docx", b"", "FILE_EMPTY"),
        ("modelo.docx", b"PK\x03\x04" + b"\x00" * DOCUMENT_TEMPLATE_MAX_BYTES, "FILE_TOO_LARGE"),
        ("modelo.docx", make_docx(vba_project=True), "ACTIVE_CONTENT"),
        ("", ANEXO_3, "FILE_REQUIRED"),
    ):
        with pytest.raises(DocumentTemplateRefused) as refused:
            read_template_upload(_Upload(filename, content))
        assert refused.value.code == code
    assert read_template_upload(_Upload('../../<x>:"y".DOCX', ANEXO_3)).filename == "xy.docx"


# ------------------------------------------------------------------ routes


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "document-templates.db") as environment:
        login_admin(environment["client"])
        yield environment


_SEEDED = iter(range(1, 1000))


def _seed(*, status="rascunho", name="Atividade com modelos"):
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, 'x', 'ativo') RETURNING id",
            (f"{name} {next(_SEEDED)}",),
        ).fetchone()[0]
        version_id = conn.execute(
            """INSERT INTO atividade_versao (atividade_base_id, eixo, grupo, ch_por_evento, documentos_json,
                   numero_versao, status) VALUES (?, 'AAC', '1 - Eventos', 2, '[]', 1, ?) RETURNING id""",
            (base_id, status),
        ).fetchone()[0]
        conn.commit()
    return base_id, version_id


def _rows(version_id):
    with main.app.app_context():
        return [
            dict(row) for row in main.get_db_connection().execute(
                "SELECT * FROM atividade_versao_modelos WHERE atividade_versao_id = ? ORDER BY id", (version_id,)
            )
        ]


def _url(base_id, version_id, suffix=""):
    return f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/modelos{suffix}"


def _add(client, base_id, version_id, title, content, filename="modelo.docx"):
    return client.post(
        _url(base_id, version_id),
        data={"modelo_titulo": title, "modelo_arquivo": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )


def _flashes(client, path):
    return client.get(path).get_data(as_text=True)


def test_two_templates_are_listed_in_order_and_each_download_returns_its_own_bytes(env):
    client = env["client"]
    base_id, version_id = _seed()
    assert _add(client, base_id, version_id, ANEXO_3_TITULO, ANEXO_3, "Anexo 3.docx").status_code == 302
    assert _add(client, base_id, version_id, "", ANEXO_5, "Anexo 5.docx").status_code == 302
    rows = _rows(version_id)
    assert [(r["titulo"], r["nome_arquivo"], r["ordem"], r["status"]) for r in rows] == [
        (ANEXO_3_TITULO, "Anexo 3.docx", 1, "ativo"),
        ("Anexo 5", "Anexo 5.docx", 2, "ativo"),  # blank title -> file name
    ]
    page = client.get(f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar").get_data(as_text=True)
    assert re.findall(r'class="doc-template-title">([^<]*)<', page) == [ANEXO_3_TITULO, "Anexo 5"]
    for row, content in zip(rows, (ANEXO_3, ANEXO_5)):
        response = client.get(_url(base_id, version_id, f"/{row['id']}/baixar"))
        assert response.status_code == 200
        assert response.data == content
        assert response.mimetype == DOCX_MIME_TYPE
        assert "attachment" in response.headers["Content-Disposition"]
        assert response.headers["Cache-Control"] == "private, no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_a_refused_file_stores_nothing_and_says_why(env):
    client = env["client"]
    base_id, version_id = _seed()
    response = _add(client, base_id, version_id, "Com macro", make_docx(vba_project=True))
    assert response.status_code == 302
    assert "macros" in _flashes(client, response.headers["Location"])
    assert _rows(version_id) == []
    with main.app.app_context():
        assert main.get_db_connection().execute("SELECT count(*) FROM modelo_documento_arquivos").fetchone()[0] == 0


def test_replace_keeps_the_slot_and_the_old_bytes_and_withdraw_ends_the_association(env):
    client = env["client"]
    base_id, version_id = _seed()
    _add(client, base_id, version_id, "Anexo 3", ANEXO_3)
    original = _rows(version_id)[0]
    response = client.post(
        _url(base_id, version_id, f"/{original['id']}/atualizar"),
        data={"modelo_titulo": ANEXO_3_TITULO, "modelo_arquivo": (io.BytesIO(ANEXO_5), "nova.docx")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    old, new = _rows(version_id)
    assert (old["id"], old["status"]) == (original["id"], "substituido") and old["encerrado_em"]
    assert (new["status"], new["ordem"], new["titulo"], new["nome_arquivo"]) == (
        "ativo", 1, ANEXO_3_TITULO, "nova.docx")
    # The replaced bytes are still the ones the old association downloads.
    assert client.get(_url(base_id, version_id, f"/{old['id']}/baixar")).data == ANEXO_3
    assert client.get(_url(base_id, version_id, f"/{new['id']}/baixar")).data == ANEXO_5
    # A title-only change is a replacement too; an unchanged one is refused.
    client.post(_url(base_id, version_id, f"/{new['id']}/atualizar"), data={"modelo_titulo": ANEXO_3_TITULO})
    assert len(_rows(version_id)) == 2
    assert client.post(
        _url(base_id, version_id, f"/{new['id']}/retirar")
    ).status_code == 302
    assert [row["status"] for row in _rows(version_id)] == ["substituido", "retirado"]
    page = client.get(f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar").get_data(as_text=True)
    assert "Histórico de modelos (2)" in page and "Nenhum modelo para preenchimento cadastrado." in page
    with main.app.app_context():
        assert main.get_db_connection().execute("SELECT count(*) FROM modelo_documento_arquivos").fetchone()[0] == 2


def test_a_frozen_version_refuses_every_template_change(env):
    client = env["client"]
    base_id, version_id = _seed()
    _add(client, base_id, version_id, "Anexo 3", ANEXO_3)
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE atividade_versao SET status = 'ativa' WHERE id = ?", (version_id,))
        conn.commit()
    template_id = _rows(version_id)[0]["id"]
    for attempt in (
        lambda: _add(client, base_id, version_id, "Outro", ANEXO_5),
        lambda: client.post(_url(base_id, version_id, f"/{template_id}/atualizar"), data={"modelo_titulo": "Novo título"}),
        lambda: client.post(_url(base_id, version_id, f"/{template_id}/retirar")),
    ):
        response = attempt()
        assert response.status_code == 302
        assert "Crie uma nova versão" in _flashes(client, response.headers["Location"])
    assert [(row["status"], row["titulo"]) for row in _rows(version_id)] == [("ativo", "Anexo 3")]
    page = client.get(f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar").get_data(as_text=True)
    assert 'form="modelo-retirar-' not in page and "Esta versão está ativa ou em uso" in page
    # It still downloads.
    assert client.get(_url(base_id, version_id, f"/{template_id}/baixar")).data == ANEXO_3


def test_a_new_version_starts_with_the_active_templates_and_the_old_one_keeps_its_own(env):
    client = env["client"]
    base_id, version_id = _seed()
    _add(client, base_id, version_id, "Anexo 3", ANEXO_3)
    _add(client, base_id, version_id, "Anexo 5", ANEXO_5)
    retired = _rows(version_id)[1]["id"]
    client.post(_url(base_id, version_id, f"/{retired}/retirar"))
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE atividade_versao SET status = 'ativa' WHERE id = ?", (version_id,))
        conn.commit()
    form = client.get(f"/admin/catalogo-versoes/{base_id}/nova-versao?from={version_id}").get_data(as_text=True)
    nome = re.search(r'id="nome" name="nome" required value="([^"]*)"', form).group(1)
    assert "serão vinculados à nova versão" in form
    response = client.post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao?from={version_id}",
        data={
            "tipo_atividade": "Acadêmica Complementar", "grupo": "1 - Eventos", "nome": nome,
            "descricao": "x", "ch_por_evento_mode": "enabled", "ch_por_evento": "4",
            "versao_anterior_id": str(version_id),
        },
    )
    assert response.status_code == 302
    with main.app.app_context():
        successor_id = main.get_db_connection().execute(
            "SELECT id FROM atividade_versao WHERE versao_anterior_id = ?", (version_id,)
        ).fetchone()[0]
    copied = _rows(successor_id)
    assert [(row["titulo"], row["ordem"], row["status"]) for row in copied] == [("Anexo 3", 1, "ativo")]
    assert copied[0]["arquivo_id"] == _rows(version_id)[0]["arquivo_id"]
    assert [row["status"] for row in _rows(version_id)] == ["ativo", "retirado"]


def test_a_semantic_successor_copies_the_active_templates(env):
    base_id, version_id = _seed(status="ativa")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE atividade_versao SET status = 'rascunho' WHERE id = ?", (version_id,))
        conn.commit()
        add_template(
            conn, base_id=base_id, versao_id=version_id, titulo="Anexo 3",
            upload=TemplateUpload("d.docx", ANEXO_3), actor_user_id=1,
        )
        conn.execute("UPDATE atividade_versao SET status = 'ativa' WHERE id = ?", (version_id,))
        conn.commit()
        with write_transaction(conn):
            result = apply_activity_version_semantic_changes(conn, version_id, {"ch_por_evento": 6.0})
        assert result["mode"] == "successor"
        assert [m["titulo"] for m in list_version_templates(conn, result["version_id"])] == ["Anexo 3"]


def test_the_database_keeps_template_content_and_history_immutable(env):
    base_id, version_id = _seed()
    _add(env["client"], base_id, version_id, "Anexo 3", ANEXO_3)
    env["client"].post(_url(base_id, version_id, f"/{_rows(version_id)[0]['id']}/retirar"))
    with main.app.app_context():
        conn = main.get_db_connection()
        for statement in (
            "UPDATE modelo_documento_arquivos SET size_bytes = size_bytes",
            "DELETE FROM modelo_documento_arquivos",
            "UPDATE atividade_versao_modelos SET status = 'ativo', encerrado_em = NULL",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement)
            conn.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO modelo_documento_arquivos (sha256, mime_type, size_bytes, conteudo) VALUES (?, ?, ?, ?)",
                (hashlib.sha256(b"%PDF").hexdigest(), DOCX_MIME_TYPE, 4, b"%PDF"),
            )
        conn.rollback()


def test_the_same_bytes_are_stored_once(env):
    client = env["client"]
    base_id, version_id = _seed()
    _add(client, base_id, version_id, "Um", ANEXO_3)
    _add(client, base_id, version_id, "Dois", ANEXO_3)
    rows = _rows(version_id)
    assert rows[0]["arquivo_id"] == rows[1]["arquivo_id"]


def test_template_routes_require_the_activity_permissions(env):
    from app.auth import get_admin_permission_requirement as requirement

    for endpoint in ("admin_catalogo_adicionar_modelo", "admin_catalogo_atualizar_modelo", "admin_catalogo_retirar_modelo"):
        assert requirement(endpoint, "POST") == ("atividades", "edit")
    assert requirement("admin_catalogo_baixar_modelo", "GET") == ("atividades", "view")
    base_id, version_id = _seed()
    _add(env["client"], base_id, version_id, "Anexo 3", ANEXO_3)
    template_id = _rows(version_id)[0]["id"]
    # Another version's id never reaches the file.
    other_base, other_version = _seed()
    assert env["client"].get(_url(other_base, other_version, f"/{template_id}/baixar")).status_code == 404
    anonymous = main.app.test_client()
    response = anonymous.get(_url(base_id, version_id, f"/{template_id}/baixar"))
    assert response.status_code == 302 and response.data != ANEXO_3


def test_copy_of_a_version_without_templates_is_a_no_op(env):
    base_id, version_id = _seed()
    with main.app.app_context():
        conn = main.get_db_connection()
        with write_transaction(conn):
            assert copy_active_templates(conn, from_versao_id=version_id, to_versao_id=version_id) == 0
