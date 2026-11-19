"""Real PostgreSQL (E-PG1 / E-PG2): the v19 document-template schema and owner.

* the provisioned head is v19 and validates;
* ``upgrade_pg_schema`` moves an exact frozen v18, v17 or v16 contract to v19
  once (a second run is a validated no-op);
* the owner's lifecycle on PostgreSQL -- bytea round trip, content
  addressing (``ON CONFLICT``), replacement, withdrawal, copy -- and the
  immutability triggers (SQLSTATE SG001);
* E-PG2: a template write and an activation of the same version serialize on
  the version row; an activation committed first makes the waiting write
  refuse, so a frozen version never gains a template.

Run-owned databases only (``tests.storage_mp1_pg_support.Registry``).
"""
from __future__ import annotations

import threading
import time

import pytest

from app import pg_schema
from app.activity_document_templates import (
    DocumentTemplateRefused,
    TemplateUpload,
    add_template,
    copy_active_templates,
    list_version_templates,
    read_template_file,
    retire_template,
    update_template,
)
from app.db import write_transaction
from tests.docx_test_support import make_docx
from tests.prod1_v19_support import drop_pg_v19_objects
from tests.storage_mp1_pg_support import PG_URL, Registry, adapter, raw_connection

pytestmark = pytest.mark.skipif(not PG_URL, reason="SGAA_PG_TEST_URL is required")

DECLARACAO = make_docx("Declaração do responsável")
FREQUENCIA = make_docx("Folha de frequência")


@pytest.fixture(scope="module")
def registry():
    registry = Registry("tmpl19")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def database(registry):
    name, url = registry.create(template=registry.template)
    try:
        yield url
    finally:
        registry.drop(name)


def _meta(url):
    raw = raw_connection(url)
    try:
        return tuple(raw.execute(f"SELECT schema_version, contract_sha256 FROM {pg_schema.PG_SCHEMA_META_TABLE}").fetchone())
    finally:
        raw.close()


def _as_frozen(url, version):
    """A provisioned v19 head turned into the exact frozen v18 / v17 / v16 contract."""
    raw = raw_connection(url)
    try:
        drop_pg_v19_objects(raw)
        if version <= 17:
            check = next(c for c in pg_schema.PG_TABLE_SPECS["requisicao_email_eventos"]["checks"]
                         if c["name"].endswith("status_decisao"))
            old = check["expression"].replace(",'Devolvida'", "")
            raw.execute(f'ALTER TABLE requisicao_email_eventos DROP CONSTRAINT "{check["name"]}", '
                        f'ADD CONSTRAINT "{check["name"]}" CHECK ({old})')
            raw.execute("DELETE FROM schema_migrations WHERE version >= 18")
            raw.execute(f"UPDATE {pg_schema.PG_SCHEMA_META_TABLE} SET schema_version = 17, "
                        f"contract_sha256 = '{pg_schema._PG_V17_CONTRACT_SHA256}'")
        if version == 16:
            definition = pg_schema.PG_TRIGGER_FUNCTIONS["fn_requisicoes_snapshot_immutable"].strip()
            v16 = definition.replace(pg_schema._function_body(definition), pg_schema._PG_V16_SNAPSHOT_FUNCTION_BODY)
            raw.execute(v16.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
            raw.execute("DELETE FROM schema_migrations WHERE version >= 17")
            raw.execute(f"UPDATE {pg_schema.PG_SCHEMA_META_TABLE} SET schema_version = 16, "
                        f"contract_sha256 = '{pg_schema._PG_V16_CONTRACT_SHA256}'")
        raw.commit()
    finally:
        raw.close()


def test_the_provisioned_head_is_v19_and_validates(database):
    status = pg_schema.validate_database(database)
    assert status["schema_version"] == pg_schema.PG_SCHEMA_VERSION == 19
    assert _meta(database) == (19, pg_schema.PG_CONTRACT_SHA256)


@pytest.mark.parametrize("version", [18, 17, 16])
def test_a_frozen_predecessor_is_upgraded_to_v19_once(database, version):
    _as_frozen(database, version)
    assert _meta(database)[0] == version
    result = pg_schema.upgrade_database(database)
    assert (result["status"], result["from_version"], result["schema_version"]) == ("upgraded", version, 19)
    assert _meta(database) == (19, pg_schema.PG_CONTRACT_SHA256)
    assert pg_schema.upgrade_database(database)["status"] == "already_current"
    raw = raw_connection(database)
    try:
        versions = [row[0] for row in raw.execute("SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == list(range(1, 20))
        assert raw.execute("SELECT count(*) FROM atividade_versao_modelos").fetchone()[0] == 0
    finally:
        raw.close()


def test_the_upgrade_refuses_a_tampered_v18_and_writes_nothing(database):
    _as_frozen(database, 18)
    raw = raw_connection(database)
    try:
        raw.execute(f"UPDATE {pg_schema.PG_SCHEMA_META_TABLE} SET contract_sha256 = '{'0' * 64}'")
        raw.commit()
    finally:
        raw.close()
    with pytest.raises(pg_schema.PostgresSchemaIncompatibleError):
        pg_schema.upgrade_database(database)
    assert _meta(database) == (18, "0" * 64)


def _draft(conn, name="Atividade PG com modelos"):
    base_id = conn.execute(
        "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, 'x', 'ativo') RETURNING id", (name,)
    ).fetchone()[0]
    version_id = conn.execute(
        "INSERT INTO atividade_versao (atividade_base_id, eixo, grupo, documentos_json, numero_versao, status)"
        " VALUES (?, 'AAC', '1 - Eventos', '[]', 1, 'rascunho') RETURNING id",
        (base_id,),
    ).fetchone()[0]
    admin_id = conn.execute("SELECT id FROM usuarios WHERE tipo = 'admin' ORDER BY id LIMIT 1").fetchone()[0]
    conn.commit()
    return int(base_id), int(version_id), int(admin_id)


def test_the_template_lifecycle_and_its_triggers_on_postgresql(database):
    conn = adapter(database)
    try:
        base_id, version_id, admin_id = _draft(conn)
        first = add_template(conn, base_id=base_id, versao_id=version_id, titulo="Declaração",
                             upload=TemplateUpload("Declaração.docx", DECLARACAO), actor_user_id=admin_id)
        again = add_template(conn, base_id=base_id, versao_id=version_id, titulo="Cópia",
                             upload=TemplateUpload("copia.docx", DECLARACAO), actor_user_id=admin_id)
        assert conn.execute("SELECT count(*) FROM modelo_documento_arquivos").fetchone()[0] == 1  # ON CONFLICT
        assert read_template_file(conn, first)["conteudo"] == DECLARACAO  # bytea round trip
        replacement = update_template(conn, base_id=base_id, versao_id=version_id, modelo_id=first,
                                      titulo="Declaração 2026", upload=TemplateUpload("d.docx", FREQUENCIA),
                                      actor_user_id=admin_id)
        retire_template(conn, base_id=base_id, versao_id=version_id, modelo_id=again, actor_user_id=admin_id)
        rows = list_version_templates(conn, version_id, include_ended=True)
        assert [(r["id"], r["status"], r["ordem"]) for r in rows] == [
            (first, "substituido", 1), (replacement, "ativo", 1), (again, "retirado", 2),
        ]
        assert read_template_file(conn, first)["conteudo"] == DECLARACAO
        # A successor in the same transaction as its creation gets the active templates only.
        with write_transaction(conn):
            successor = conn.execute(
                "INSERT INTO atividade_versao (atividade_base_id, eixo, grupo, documentos_json, numero_versao, status,"
                " versao_anterior_id) VALUES (?, 'AAC', '1 - Eventos', '[]', 2, 'rascunho', ?) RETURNING id",
                (base_id, version_id),
            ).fetchone()[0]
            assert copy_active_templates(conn, from_versao_id=version_id, to_versao_id=successor) == 1
        for statement, params in (
            ("UPDATE modelo_documento_arquivos SET criado_em = criado_em", ()),
            ("DELETE FROM modelo_documento_arquivos", ()),
            ("UPDATE atividade_versao_modelos SET titulo = 'x' WHERE id = ?", (first,)),
            ("UPDATE atividade_versao_modelos SET ordem = 9 WHERE id = ?", (replacement,)),
        ):
            with pytest.raises(Exception) as refused:
                conn.execute(statement, params)
            # SG001 from the immutability triggers; content an association still
            # references is protected by ON DELETE RESTRICT (foreign_key_violation).
            assert getattr(refused.value, "sqlstate", None) in {"SG001", "23503"}, repr(refused.value)
            conn.rollback()
        conn.execute("UPDATE atividade_versao SET status = 'ativa' WHERE id = ?", (version_id,))
        conn.commit()
        with pytest.raises(DocumentTemplateRefused) as frozen:
            add_template(conn, base_id=base_id, versao_id=version_id, titulo="Tarde demais",
                         upload=TemplateUpload("t.docx", FREQUENCIA), actor_user_id=admin_id)
        assert frozen.value.code == "VERSION_FROZEN"
    finally:
        conn.close()


def _blocked(observer, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        waiting = observer.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'"
        ).fetchone()[0]
        if waiting:
            return True
        time.sleep(0.05)
    return False


def test_an_activation_committed_while_a_template_write_waits_wins(database):
    setup = adapter(database)
    try:
        base_id, version_id, admin_id = _draft(setup, name="Atividade PG concorrente")
    finally:
        setup.close()
    activator = adapter(database)
    writer = adapter(database)
    observer = raw_connection(database, autocommit=True)
    outcome = {}
    try:
        activator.execute("UPDATE atividade_versao SET status = 'ativa' WHERE id = ?", (version_id,))

        def write():
            try:
                add_template(writer, base_id=base_id, versao_id=version_id, titulo="Concorrente",
                             upload=TemplateUpload("c.docx", DECLARACAO), actor_user_id=admin_id)
                outcome["result"] = "added"
            except DocumentTemplateRefused as exc:
                outcome["result"] = exc.code

        thread = threading.Thread(target=write)
        thread.start()
        assert _blocked(observer), "the template write did not wait for the version row"
        activator.commit()
        thread.join(timeout=20)
        assert outcome["result"] == "VERSION_FROZEN"
        assert observer.execute(
            "SELECT count(*) FROM atividade_versao_modelos WHERE atividade_versao_id = %s", (version_id,)
        ).fetchone()[0] == 0
    finally:
        activator.close()
        writer.close()
        observer.close()


def _insert_template(conn, version_id, title, content, *, slot, status="ativo"):
    """Setup only: a template row on any version (the owner itself refuses frozen ones)."""
    import hashlib

    from app.prod1_document_templates_ddl import DOCX_MIME_TYPE

    digest = hashlib.sha256(content).hexdigest()
    conn.execute(
        "INSERT INTO modelo_documento_arquivos (sha256, mime_type, size_bytes, conteudo) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (sha256) DO NOTHING",
        (digest, DOCX_MIME_TYPE, len(content), content),
    )
    content_id = conn.execute("SELECT id FROM modelo_documento_arquivos WHERE sha256 = ?", (digest,)).fetchone()[0]
    ended = "2026-01-01 00:00:00" if status != "ativo" else None
    return int(conn.execute(
        "INSERT INTO atividade_versao_modelos (atividade_versao_id, arquivo_id, titulo, nome_arquivo, ordem, status,"
        " encerrado_em) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (version_id, content_id, title, f"{title}.docx", slot, status, ended),
    ).fetchone()[0])


def test_the_student_read_path_on_postgresql(database):
    """E-PG1: the request form's guidance read model and the student download rule."""
    from app.activity_document_templates import active_templates_by_version, read_template_file, student_may_download
    from app.activity_documentation import student_guidance_by_version
    from tests.storage_mp1_support import STUDENT_USER_ID

    conn = adapter(database)
    try:
        requested = 1  # the seeded student's own request uses version 1
        offered = conn.execute(
            "INSERT INTO atividade_versao (atividade_base_id, eixo, grupo, documentos_json, numero_versao, status)"
            " VALUES (1, 'AAC', '1 - Eventos', '[\"Certificado\"]', 2, 'ativa') RETURNING id"
        ).fetchone()[0]
        foreign_base = conn.execute(
            "INSERT INTO atividade_base (nome_conceito) VALUES ('Fora da matriz') RETURNING id").fetchone()[0]
        foreign = conn.execute(
            "INSERT INTO atividade_versao (atividade_base_id, eixo, numero_versao, status)"
            " VALUES (?, 'AAC', 1, 'ativa') RETURNING id", (foreign_base,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_base_id, atividade_versao_id) VALUES (1, 1, ?)",
            (offered,),
        )
        ids = {
            "offered_2": _insert_template(conn, offered, "Segundo", FREQUENCIA, slot=2),
            "offered_1": _insert_template(conn, offered, "Primeiro", DECLARACAO, slot=1),
            "withdrawn": _insert_template(conn, offered, "Retirado", FREQUENCIA, slot=3, status="retirado"),
            "requested": _insert_template(conn, requested, "Da requisição", DECLARACAO, slot=1),
            "foreign": _insert_template(conn, foreign, "Estrangeiro", DECLARACAO, slot=1),
        }
        conn.commit()

        by_version = active_templates_by_version(conn, [offered, requested, foreign, 999999])
        assert [m["titulo"] for m in by_version[offered]] == ["Primeiro", "Segundo"]  # slot order, active only
        assert [m["id"] for m in by_version[requested]] == [ids["requested"]]
        assert by_version[999999] == []
        guidance = student_guidance_by_version(conn, [
            {"id": offered, "documentos_json": '["Certificado"]'},
            {"id": foreign, "documentos_json": None},
            {"id": 999999, "documentos_json": "[]"},
        ])
        assert guidance[offered]["documentos"] == ["Certificado"]
        assert [m["titulo"] for m in guidance[offered]["modelos"]] == ["Primeiro", "Segundo"]
        assert 999999 not in guidance
        allowed = {name: student_may_download(conn, usuario_id=STUDENT_USER_ID, template=read_template_file(conn, i))
                   for name, i in ids.items()}
        assert allowed == {"offered_2": True, "offered_1": True, "withdrawn": False, "requested": True,
                           "foreign": False}
        assert read_template_file(conn, ids["offered_1"])["conteudo"] == DECLARACAO
    finally:
        conn.close()
