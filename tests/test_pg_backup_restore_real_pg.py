# coding: utf-8
"""Layer-2 PostgreSQL logical backup -> restore -> verify on real PostgreSQL.

Needs ``SGAA_PG_TEST_URL`` (role with CREATEDB) and native ``pg_dump`` /
``pg_restore`` (``SGAA_PG_BIN_DIR`` or ``PATH``).  Every database is created
and dropped by this run (prefix ``sgaa_pgbk_test_<run>_``); the maintenance
database is only used to create and drop them.

A. synthetic source A (users/credentials, lineage with a forward reference,
   AAC->AEU transition, matrix items, turma/aluno/request snapshots, local and
   Drive file references, identity high-water above max(id), an empty table
   with historical identity state, prod-1/v13 image rows with binary
   content, prod-1/v14 canonical-storage objects with business references,
   a LIVE upload intent and worker health) is backed up once; the artifact set,
   manifest and TOC census are checked (the two v14 schema-only tables carry
   no TABLE DATA in the archive); A is restored into a new empty B and
   verified read-only (storage objects and references exact, intents and
   worker health empty); disposable clones of B prove identity behaviour, the
   restored triggers, and that a tampered row or sequence fails verification.
B. negative controls: tampered artifact / manifest / sidecar, missing or bad
   manifest, restore into the source, a protected or a non-empty database,
   client older than server, objects outside the contract, disabled
   triggers, an unprovisioned source, a failing native tool, a restore
   that fails after creating objects (single transaction: target stays empty)
   and a restore that commits and then fails verification (mismatch, database
   error, interruption: exit 3, the target keeps the restore, no rollback claim).
C. E-PG2: a writer commits after the snapshot is exported; the manifest, the
   archive and the restore all describe the snapshot, not the writer.
D. the current-data recovery rehearsal, opt-in through the Path-B frozen-copy
   variables ``SGAA_PATHB_SOURCE`` / ``_SHA256`` / ``_UPLOAD_ROOT``:
   SQLITE COPY -> PATH-B -> R5 -> LOGIN A -> BACKUP -> RESTORE B -> VALIDATE ->
   LOGIN B.  Only aggregate evidence is printed; artifacts are deleted.  A
   failure reports value-free codes only (no e-mail, password, URL or row
   DETAIL reaches pytest's assertion, traceback or captured-log output).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

from app import pg_migrate_from_sqlite as pathb
from app import pg_schema
from app.cloud_account_identity import google_account_key
from tools import pg_backup as tool

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()
REHEARSAL_SOURCE = os.environ.get("SGAA_PATHB_SOURCE", "").strip()
REHEARSAL_SHA256 = os.environ.get("SGAA_PATHB_SOURCE_SHA256", "").strip()
REHEARSAL_UPLOAD_ROOT = os.environ.get("SGAA_PATHB_SOURCE_UPLOAD_ROOT", "").strip()

needs_pg = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

RUN_PREFIX = f"sgaa_pgbk_test_{secrets.token_hex(4)}_"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})
CONNECT_TIMEOUT_SECONDS = 10

ADMIN_EMAIL = "pgbk.admin@example.test"
STUDENT_EMAIL = "pgbk.aluno@example.test"
TS = "2026-01-02 03:04:05"
#: Identity high-water per table (all >= max(id)); RESTART WITH value + 1.
HIGH_WATER = {
    "usuarios": 12, "cursos": 3, "matrizes_atividades": 5, "turmas": 9, "alunos": 15,
    "atividade_base": 23, "atividade_versao": 80, "atividade_transicao": 2,
    "matriz_atividade_versao_item": 14, "requisicoes": 25, "requisicao_arquivos": 6,
    "requisicao_alerta_receipts": 2, "admin_arquivos": 4, "admin_alertas": 1, "email_envios": 3,
    "reportes": 5, "storage_objects": 20, "cloud_accounts": 4,
}
#: Synthetic Google OIDC subject: only its logical key may reach the database;
#: the raw value must never appear in any manifest or output.
RAW_GOOGLE_SUB = "109876543210987654321"
DRIVE_ACCOUNT_KEY = google_account_key(RAW_GOOGLE_SUB)
#: v14 storage objects ``(id, key suffix, size, lifecycle, drive state)``.
STORAGE_OBJECTS = (
    (9, "a", 4096, "active", "synced"),
    (14, "b", 77, "retired", "retry"),
    (15, "c", 1000, "active", "pending"),
)
#: ``(last_value, is_called)`` on A: high-water tables restarted, backup_logs
#: consumed one id and is empty again, the rest never used.
EXPECTED_IDENTITIES = {
    **{table: (high_water + 1, False) for table, high_water in HIGH_WATER.items()},
    "backup_logs": (1, True),
    **{t: (1, False) for t in ("senha_tokens", "cloud_drive_settings",
                               "requisicao_email_eventos")},
}
#: v13 image content: a recognisable marker that must never reach any output.
BLOB_MARKER = b"PGBK-BLOB-MARKER"
IMAGE_BLOBS = {
    "usuarios_foto": (3, "image/png", b"\x89PNG\r\n\x1a\n" + BLOB_MARKER * 8 + bytes(range(256))),
    "alunos_foto": (11, "image/jpeg", b"\xff\xd8\xff" + BLOB_MARKER * 5 + b"\x00\xff" * 300),
    "reportes_captura": (5, "image/webp", b"RIFF\x00\x00\x00\x00WEBP" + BLOB_MARKER + bytes(4096)),
}
PII_MARKERS = (
    ADMIN_EMAIL, STUDENT_EMAIL, "pbkdf2", "Admin Sintetico", "Aluno Sintetico", "synthetic-profile-default",
    BLOB_MARKER.decode("ascii"), BLOB_MARKER.hex(),
)


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


def _database_url(database):
    parts = urlsplit(PG_URL)
    return urlunsplit((parts.scheme, parts.netloc, "/" + database, f"connect_timeout={CONNECT_TIMEOUT_SECONDS}", ""))


def _connect(url, *, autocommit=True):
    import psycopg

    return psycopg.connect(url, prepare_threshold=None, autocommit=autocommit, connect_timeout=CONNECT_TIMEOUT_SECONDS)


class _RunDatabaseRegistry:
    """Sole creator and destroyer of this run's disposable databases."""

    def __init__(self):
        self._admin = None
        self._owned = set()

    def admin(self):
        if self._admin is None or self._admin.closed:
            self._admin = _connect(PG_URL)
        return self._admin

    def create(self, label, *, template=None):
        database = f"{RUN_PREFIX}{label}_{secrets.token_hex(3)}"
        clause = f' TEMPLATE "{template}"' if template else ""
        self.admin().execute(f'CREATE DATABASE "{database}"{clause}')
        self._owned.add(database)
        return database, _database_url(database)

    def drop(self, database):
        import psycopg

        if database in PROTECTED_DATABASES or not database.startswith(RUN_PREFIX):
            raise AssertionError(f"refusing to drop {database!r}: not run-owned")
        if database not in self._owned:
            raise AssertionError(f"refusing to drop {database!r}: not created by this run")
        row = self.admin().execute(
            "SELECT pg_get_userbyid(datdba) = current_user FROM pg_database WHERE datname = %s", (database,)
        ).fetchone()
        if row is not None and not row[0]:
            raise AssertionError(f"refusing to drop {database!r}: not owned by this role")
        try:
            self.admin().execute(f'DROP DATABASE IF EXISTS "{database}"')
        except psycopg.errors.ObjectInUse:
            self.admin().execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        self._owned.discard(database)

    def leftovers(self):
        rows = self.admin().execute(
            "SELECT datname FROM pg_database WHERE starts_with(datname, %s)", (RUN_PREFIX,)
        ).fetchall()
        return sorted(row[0] for row in rows)

    def close(self):
        failures = []
        for database in sorted(self._owned):
            try:
                self.drop(database)
            except Exception as exc:  # pragma: no cover - teardown reporting
                failures.append((database, _safe_error(exc)))
        leftovers = self.leftovers() if not failures else []
        if self._admin is not None and not self._admin.closed:
            self._admin.close()
        assert not failures, f"could not drop run-owned databases: {failures!r}"
        assert not leftovers, f"run-owned databases left behind: {leftovers!r}"


def _insert(conn, table, **values):
    marks = ", ".join(["%s"] * len(values))
    conn.execute(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({marks})", tuple(values.values()))


def populate_source(conn):
    """Representative synthetic SGAA data; every trigger and constraint active."""
    i = lambda table, **values: _insert(conn, table, **values)  # noqa: E731
    i("usuarios", id=3, nome="Admin Sintetico", email=ADMIN_EMAIL, senha="pbkdf2:synthetic", tipo="admin",
      nivel_acesso="admin_total")
    i("usuarios", id=7, nome="Aluno Sintetico", email=STUDENT_EMAIL, senha="pbkdf2:synthetic2", tipo="aluno",
      nivel_acesso="usuario")
    i("usuario_credenciais", usuario_id=3, estado="personal", auth_version=2, atualizado_em=TS, acesso_ativo=1)
    i("usuario_credenciais", usuario_id=7, estado="default", auth_version=1, atualizado_em=TS, acesso_ativo=1)
    i("usuarios_permissoes_acesso", usuario_id=3, recurso="requisicoes", escopo="total")
    i("configuracoes_acesso", nivel_acesso="admin_total", senha_padrao="synthetic-profile-default")
    i("configuracoes_app", chave="response_goal_days", valor="12", atualizado_em=TS)
    i("configuracoes_presets", tipo="emails", preset_id=1, titulo="T", texto="Corpo", atualizado_em=TS,
      assunto="A", is_default=1)
    i("cursos", id=2, nome="Curso", codigo="C1", duracao_periodos=8, total_horas_aac=160, total_horas_aeu=160,
      periodo="diurno", status="ativo")
    i("matrizes_atividades", id=5, curso_id=2, nome="Matriz", status="vigente", horas_aac_obrigatorias=160,
      horas_extensao_obrigatorias=160, created_at=TS)
    i("turmas", id=9, nome="Turma 1", turno="noite", status="Ativa", numero=1, curso_id=2, ano_inicio=2024,
      semestre_inicio=1, codigo="T1", matriz_id=5)
    i("alunos", id=11, usuario_id=7, nome="Aluno Sintetico", matricula="M-11", email=STUDENT_EMAIL, turma_id=9,
      matriz_id=5, status="Ativo")
    for base_id, nome in ((20, "Conceito A"), (21, "Conceito B"), (22, "Conceito C")):
        i("atividade_base", id=base_id, nome_conceito=nome, status="ativo", created_at=TS)
    for version in (
        dict(id=30, atividade_base_id=20, eixo="AAC", numero_versao=1, status="substituida", ch_por_evento=2.5),
        dict(id=45, atividade_base_id=20, eixo="AAC", numero_versao=2, status="ativa", versao_anterior_id=30,
             limite_total=40.0, documentos_json='["certificado"]'),
        dict(id=50, atividade_base_id=21, eixo="AEU", numero_versao=1, status="ativa", limite_semestre=10),
        dict(id=70, atividade_base_id=22, eixo="AAC", numero_versao=1, status="substituida"),
        # Forward lineage: the predecessor has the higher id.
        dict(id=12, atividade_base_id=22, eixo="AAC", numero_versao=2, status="ativa", versao_anterior_id=70),
    ):
        i("atividade_versao", created_at=TS, **version)
    i("atividade_transicao", id=2, from_atividade_versao_id=45, to_atividade_versao_id=50,
      tipo_transicao="aac_para_aeu", justificativa="Normativa", created_at=TS)
    i("matriz_atividade_versao_item", id=8, matriz_id=5, atividade_base_id=20, atividade_versao_id=45, created_at=TS)
    i("matriz_atividade_versao_item", id=13, matriz_id=5, atividade_base_id=21, atividade_versao_id=50, created_at=TS)
    i("requisicoes", id=17, aluno_id=11, atividade_versao_id=45, data_solicitacao=TS, data_evento="2026-01-01",
      horas_solicitadas=10.5, nome_evento="Evento", status="Deferida", horas_deferidas=10.0, admin_id=3,
      regra_snapshot_json='{"ch_por_evento":2.5}', turma_id_snapshot=9, turma_codigo_snapshot="T1")
    i("requisicoes", id=18, aluno_id=11, atividade_versao_id=50, data_solicitacao=TS, data_evento="2026-01-01",
      horas_solicitadas=4, status="Pendente", regra_snapshot_json="{}")
    i("requisicao_arquivos", id=6, requisicao_id=17, filename="comprovante.pdf", criado_em=TS, provider="google",
      remote_file_id="remote-file", remote_parent_id="remote-parent", original_filename="c.pdf",
      mime_type="application/pdf", size_bytes=100, sha256="c" * 64, uploaded_at=TS, uploader_user_id=3,
      operation_key="op-1", storage_status="active")
    i("requisicao_alerta_receipts", id=2, requisicao_id=17, usuario_id=3, alert_kind="nova", seen_at=TS)
    i("admin_arquivos", id=4, titulo="Manual", filename="pgbk_docs/manual.pdf", original_filename="manual.pdf",
      visivel=1, criado_em=TS, provider="local_legacy", storage_status="legacy_active")
    i("admin_alertas", id=1, titulo="Aviso", mensagem="Mensagem", visivel=1, criado_em=TS)
    i("email_envios", id=3, aluno_id=11, destinatario=STUDENT_EMAIL, assunto="A", corpo="C", status="sent",
      tentativas=1, idempotency_key="k-1", criado_em=TS, enviado_em=TS)
    i("reportes", id=5, aluno_id=11, titulo="Reporte", descricao="Descricao", categoria="Outro", status="Novo",
      criado_em=TS, atualizado_em=TS)
    for table, (owner_id, mime_type, content) in IMAGE_BLOBS.items():
        owner_column = pg_schema.PG_TABLE_SPECS[table]["primary_key"]["columns"][0]
        _insert(conn, table, **{owner_column: owner_id}, mime_type=mime_type, size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(), width=64, height=48, conteudo=content,
                atualizado_em=TS)
    # v14 canonical custody.  The Drive account row (identity restarted with
    # the other high-waters below) holds no address and no real token.
    i("cloud_accounts", id=4, provider="google", account_email=None, token_json="{}", connected_at=TS,
      updated_at=TS, active=1, provider_account_key=DRIVE_ACCOUNT_KEY)
    for object_id, suffix, size, lifecycle, drive_state in STORAGE_OBJECTS:
        extra = {}
        if lifecycle == "retired":
            extra.update(retired_at=TS)
        if drive_state == "synced":
            extra.update(drive_file_id=f"drv-{object_id}", drive_account_key=DRIVE_ACCOUNT_KEY, drive_synced_at=TS,
                         drive_generation=1)
        if drive_state == "retry":
            extra.update(drive_last_error_code="DRIVE_QUOTA", drive_next_attempt_at=TS, drive_generation=2)
        i("storage_objects", id=object_id, storage_backend="supabase", storage_bucket="sgaa-documentos",
          storage_key=f"comprovantes/2026/01/{suffix * 32}", sha256=suffix * 64, size_bytes=size,
          mime_type="application/pdf", uploader_user_id=3, origin="direct_upload", content_verified_at=TS,
          created_at=TS, lifecycle_state=lifecycle, drive_sync_state=drive_state, **extra)
    conn.execute("UPDATE requisicao_arquivos SET storage_object_id = 9 WHERE id = 6")
    conn.execute("UPDATE admin_arquivos SET storage_object_id = 15 WHERE id = 4")
    i("storage_upload_intents", id="1" * 32, actor_user_id=3, purpose="admin_arquivo", operation_id="op-c",
      storage_bucket="sgaa-documentos", storage_key="comprovantes/2026/01/" + "c" * 32,
      declared_mime_type="application/pdf", declared_size_bytes=1000, declared_sha256="c" * 64, state="consumed",
      issued_at=TS, expires_at="2026-01-02 03:19:05", sweep_after="2026-01-03 03:19:05", verified_at=TS,
      consumed_at=TS, storage_object_id=15)
    # A LIVE intent: a restore must never revive it.
    i("storage_upload_intents", id="2" * 32, actor_user_id=7, purpose="comprovante", operation_id="op-live",
      storage_bucket="sgaa-documentos", storage_key="comprovantes/2026/01/" + "d" * 32,
      declared_mime_type="image/png", declared_size_bytes=10, declared_sha256="d" * 64, state="issued",
      issued_at=TS, expires_at="2099-01-01 00:00:00", sweep_after="2099-01-02 00:00:00")
    i("storage_worker_status", id=1, last_started_at=TS, last_finished_at=TS, last_result_code="OK",
      last_claimed_count=3, last_synced_count=1, last_retry_count=1)
    for table, high_water in HIGH_WATER.items():
        conn.execute(f"ALTER TABLE {table} ALTER COLUMN id RESTART WITH {high_water + 1}")
    # Historical identity state on an empty table.
    consumed = conn.execute("INSERT INTO backup_logs DEFAULT VALUES RETURNING id").fetchone()[0]
    conn.execute("DELETE FROM backup_logs WHERE id = %s", (consumed,))


@pytest.fixture(scope="module")
def registry():
    psycopg = pytest.importorskip("psycopg")
    if not PG_URL:
        pytest.skip("SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT")
    try:
        tool.discover_native_tools()
    except tool.BackupToolError as exc:
        pytest.skip(f"native pg_dump/pg_restore unavailable ({exc.code}) -- REAL-PG BACKUP EVIDENCE: ABSENT")
    registry = _RunDatabaseRegistry()
    try:
        try:
            registry.admin()
        except psycopg.Error as exc:
            pytest.skip(f"SGAA_PG_TEST_URL is not a usable PostgreSQL connection: {exc.__class__.__name__}")
        template, template_url = registry.create("template")
        connection = _connect(template_url, autocommit=False)
        try:
            pg_schema.provision_pg_schema(connection)
            connection.commit()
        finally:
            connection.close()
        registry.template = template
        source, source_url = registry.create("source", template=template)
        connection = _connect(source_url, autocommit=False)
        try:
            populate_source(connection)
            connection.commit()
        finally:
            connection.close()
        registry.source = (source, source_url)
        yield registry
    finally:
        registry.close()


def _state(url) -> tool.DatabaseState:
    conn = tool.connect(url)
    try:
        tool._begin_snapshot(conn)
        try:
            return tool.read_state(conn)
        finally:
            tool._end_transaction(conn)
    finally:
        conn.close()


def _rows(url) -> dict:
    conn = tool.connect(url)
    try:
        return {t: pathb.normalize_rows(t, pathb.read_target_rows(conn, t)) for t in pg_schema.PG_SCHEMA_TABLES}
    finally:
        conn.close()


def _image_contents(url) -> dict:
    conn = tool.connect(url)
    try:
        return {
            table: bytes(conn.execute(f"SELECT conteudo FROM {table}").fetchone()[0])
            for table in IMAGE_BLOBS
        }
    finally:
        conn.close()


def _identity_states(url) -> dict:
    conn = tool.connect(url)
    try:
        return {t: pathb.read_identity_state(conn, t) for t in tool.IDENTITY_TABLES}
    finally:
        conn.close()


def _occupancy(url) -> dict:
    conn = tool.connect(url)
    try:
        return tool.target_occupancy(conn)
    finally:
        conn.close()


def _run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = tool.main(argv)
    return code, out.getvalue() + err.getvalue()


def _no_secrets(output, *urls):
    """Call it into a boolean first: as an assert operand pytest would print its arguments."""
    leaked = [marker for marker in (*PII_MARKERS, *urls, "sgaa_qual@", "password") if marker and marker in output]
    return leaked == []


def _safe_error(exc) -> str:
    """Exception class (+ tool code / SQLSTATE) only -- never its text: a
    PostgreSQL DETAIL can quote row values ("Failing row contains (...)")."""
    code = getattr(exc, "code", None) if isinstance(exc, tool.BackupToolError) else None
    state = getattr(exc, "sqlstate", None)
    return exc.__class__.__name__ + (f" code={code}" if code else "") + (f" sqlstate={state}" if state else "")


def _guarded(step, action):
    """Run ``action()``; an exception becomes a value-free AssertionError.

    pytest would otherwise print the exception text and every frame's
    arguments (URL, e-mail, password, row tuples) on a failure.
    """
    try:
        return action()
    except Exception as exc:
        failure = f"{step} raised {_safe_error(exc)}"
    raise AssertionError(failure)  # outside the except block: no chained original


@pytest.fixture(scope="module")
def backup_set(registry, tmp_path_factory):
    """One CLI backup of the synthetic source A, shared read-only by the module."""
    directory = tmp_path_factory.mktemp("pgbk_artifacts")
    source, source_url = registry.source
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(tool.SOURCE_URL_ENV, source_url)
        patch.delenv(tool.TARGET_URL_ENV, raising=False)
        before = _state(source_url)
        code, output = _run_cli(["backup", "--output-dir", str(directory), "--label", "synthetic"])
        after = _state(source_url)
    assert code == 0, output
    [manifest_path] = directory.glob("*.manifest.json")
    yield {"manifest": manifest_path, "directory": directory, "output": output, "before": before, "after": after}
    shutil.rmtree(directory, ignore_errors=True)


# ---------------------------------------------------------------------------
# A. backup -> restore -> verify
# ---------------------------------------------------------------------------


@needs_pg
def test_backup_writes_exactly_the_artifact_set_and_a_value_free_manifest(registry, backup_set):
    source, source_url = registry.source
    directory, manifest_path = backup_set["directory"], backup_set["manifest"]
    base = manifest_path.name[: -len(tool.MANIFEST_SUFFIX)]
    assert sorted(p.name for p in directory.iterdir()) == sorted(
        [base + tool.DUMP_SUFFIX, base + tool.SIDECAR_SUFFIX, base + tool.MANIFEST_SUFFIX]
    )
    assert base.startswith("sgaa-pg-") and base.endswith("Z-synthetic")
    output = backup_set["output"]
    assert "result: BACKUP_OK" in output and f"database={source}" in output
    output_clean = _no_secrets(output, PG_URL, source_url)
    assert output_clean
    # The source was only read.
    assert backup_set["before"] == backup_set["after"]

    text = manifest_path.read_text(encoding="utf-8")
    manifest_clean = _no_secrets(text, PG_URL, source_url)
    assert manifest_clean
    manifest = json.loads(text)
    assert tool.load_manifest(manifest_path) == manifest
    dump = directory / manifest["artifact"]["file"]
    assert tool.file_sha256(dump) == (manifest["artifact"]["size"], manifest["artifact"]["sha256"])
    assert (directory / manifest["artifact"]["sidecar"]).read_text(encoding="ascii") == \
        f"{manifest['artifact']['sha256']}  {dump.name}\n"
    assert manifest["result"] == "ok" and manifest["format_version"] == 2
    assert manifest["source"]["database"] == source and manifest["source"]["system_identifier"]
    assert set(manifest["source"]) == {"backend", "host", "port", "database", "user", "server_version",
                                       "system_identifier"}
    assert manifest["server"]["major"] == manifest["native_tools"]["pg_dump"]["major"] == 15
    assert manifest["consistency"]["mode"] == "exported_snapshot"
    assert manifest["schema"]["epoch"] == pg_schema.PG_SCHEMA_EPOCH
    assert manifest["schema"]["version"] == pg_schema.PG_SCHEMA_VERSION
    assert manifest["schema"]["contract_sha256"] == pg_schema.PG_CONTRACT_SHA256
    assert manifest["schema"]["latest_migration"]["version"] == 14
    schema_only = set(tool.SCHEMA_ONLY_TABLE_POLICIES)
    assert {t: v for t, v in manifest["tables"].items() if t not in schema_only} == {
        t: v for t, v in backup_set["before"].tables.items() if t not in schema_only
    }
    assert len(manifest["tables"]) == 37
    # v14: schema-only tables are recorded as what a restore yields -- empty --
    # with their policy and a value-free source census.
    for table in schema_only:
        assert manifest["tables"][table] == tool._EMPTY_TABLE[table]
    assert {t: backup_set["before"].tables[t]["rows"] for t in schema_only} == {
        "storage_upload_intents": 2, "storage_worker_status": 1,
    }
    assert manifest["table_data_policy"] == {
        "storage_upload_intents": {"policy": "EPHEMERAL_OMITTED", "restored_rows": 0,
                                   "source": {"rows_by_state": {"consumed": 1, "issued": 1}}},
        "storage_worker_status": {"policy": "TARGET_SIDE_RECREATED", "restored_rows": 0,
                                  "source": {"rows": 1}},
    }
    storage = manifest["storage"]
    assert (storage["objects"], storage["total_size_bytes"]) == (3, 4096 + 77 + 1000)
    assert storage["by_lifecycle_state"] == {"active": 2, "retired": 1}
    assert storage["by_drive_sync_state"] == {"pending": 1, "retry": 1, "synced": 1}
    assert storage["business_references"] == {"requisicao_arquivos": 1, "admin_arquivos": 1}
    assert storage["object_bytes"] == "NOT_INCLUDED_CANONICAL_BUCKET"
    assert "drv-9" not in text and "op-live" not in text
    assert RAW_GOOGLE_SUB not in text and RAW_GOOGLE_SUB not in output
    for table in IMAGE_BLOBS:
        assert manifest["tables"][table]["rows"] == 1, table
    assert manifest["tables"]["usuarios"]["rows"] == 2 and manifest["tables"]["backup_logs"]["rows"] == 0
    identities = {t: (v["last_value"], v["is_called"]) for t, v in manifest["identities"].items()}
    assert identities == EXPECTED_IDENTITIES
    for table, entry in manifest["identities"].items():
        assert entry["predicted_next_id"] > entry["max_id"], table
        assert entry["observed_in_snapshot_transaction"]["predicted_next_id"] == entry["predicted_next_id"]
    assert manifest["identities"]["backup_logs"]["predicted_next_id"] == 2
    assert manifest["identities"]["backup_logs"]["max_id"] == 0
    assert manifest["toc"]["classes"] == {
        "CONSTRAINT": 58, "FK CONSTRAINT": 40, "FUNCTION": 15, "INDEX": 56, "SEQUENCE": 22,
        "SEQUENCE SET": 22, "TABLE": 37, "TABLE DATA": 35, "TRIGGER": 17,
    }
    # The omission is proven from the archive itself.
    _listing, entries = tool.read_toc(tool.discover_native_tools(), dump)
    data_tags = {entry.tag for entry in entries if entry.desc == "TABLE DATA"}
    assert "storage_objects" in data_tags and not data_tags & schema_only
    assert manifest["toc"]["public_schema_entries"] == 2
    assert manifest["domain_validation"]["checks"] == 63 and manifest["domain_validation"]["failing"] == 0
    assert manifest["triggers"] == {"expected": 17, "enabled": 17}
    assert manifest["accounts"]["usuarios"] == 2 and manifest["accounts"]["full_admins"] == 1
    assert manifest["tool"]["sha256"] == tool.file_sha256(Path(tool.__file__))[1]

    code, output = _run_cli(["verify", "--manifest", str(manifest_path)])
    assert code == 0 and "VERIFY_OK (artifact)" in output


@needs_pg
def test_restore_into_a_new_empty_database_matches_manifest_and_source(registry, backup_set, monkeypatch):
    import psycopg

    source, source_url = registry.source
    target, target_url = registry.create("restored")
    manifest_path = str(backup_set["manifest"])
    manifest = json.loads(backup_set["manifest"].read_text(encoding="utf-8"))
    monkeypatch.setenv(tool.SOURCE_URL_ENV, source_url)
    monkeypatch.setenv(tool.TARGET_URL_ENV, target_url)

    code, output = _run_cli(["restore", "--manifest", manifest_path])
    assert code == 0, output
    assert "result: RESTORE_OK" in output and f"database={target}" in output
    output_clean = _no_secrets(output, PG_URL, source_url, target_url)
    assert output_clean
    code, output = _run_cli(["verify", "--manifest", manifest_path, "--restored"])
    assert code == 0 and "VERIFY_OK (artifact + database)" in output
    # The quiescent source equals its manifest except exactly the schema-only
    # tables: the manifest describes what a restore yields, not the source.
    with pytest.raises(tool.Failed) as caught:
        tool.verify_database(manifest, source_url)
    assert set(caught.value.mismatches) == {
        (category, table)
        for table in tool.SCHEMA_ONLY_TABLE_POLICIES
        for category in ("ROW_COUNT_MISMATCH", "SCHEMA_ONLY_TABLE_NOT_EMPTY")
    }

    # Independent comparison: every row of every table, identities, catalog.
    source_rows, target_rows = _rows(source_url), _rows(target_url)
    for table in tool.SCHEMA_ONLY_TABLE_POLICIES:
        assert source_rows.pop(table) and target_rows.pop(table) == {}, table
    rows_equal = source_rows == target_rows
    assert rows_equal
    # Restored custody: objects and references exact; no live intent revived;
    # worker health is the target-side "never ran" state.
    observer = _connect(target_url)
    try:
        assert [tuple(r) for r in observer.execute(
            "SELECT id, lifecycle_state, drive_sync_state FROM storage_objects ORDER BY id"
        ).fetchall()] == [(o, lifecycle, state) for o, _s, _z, lifecycle, state in STORAGE_OBJECTS]
        assert observer.execute(
            "SELECT (SELECT storage_object_id FROM requisicao_arquivos WHERE id = 6), "
            "(SELECT storage_object_id FROM admin_arquivos WHERE id = 4)"
        ).fetchone() == (9, 15)
        # The logical Drive identity is ordinary pseudonymous DB state: restored exactly.
        assert observer.execute(
            "SELECT drive_account_key FROM storage_objects WHERE id = 9").fetchone()[0] == DRIVE_ACCOUNT_KEY
        assert observer.execute("SELECT count(*) FROM storage_upload_intents").fetchone()[0] == 0
        assert observer.execute("SELECT count(*) FROM storage_worker_status").fetchone()[0] == 0
    finally:
        observer.close()
    restored_identities = _identity_states(target_url)
    assert restored_identities == _identity_states(source_url) == EXPECTED_IDENTITIES
    b_before = _state(target_url)
    observer = _connect(target_url)
    try:
        pg_schema.validate_pg_schema(observer)
        fks = observer.execute(
            "SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND connamespace = 'public'::regnamespace"
        ).fetchone()[0]
        checks = observer.execute(
            "SELECT count(*) FROM pg_constraint WHERE contype = 'c' AND connamespace = 'public'::regnamespace"
        ).fetchone()[0]
        enabled = observer.execute(
            "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid WHERE "
            "c.relnamespace = 'public'::regnamespace AND NOT t.tgisinternal AND t.tgenabled = 'O'"
        ).fetchone()[0]
        partial = observer.execute(
            "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relnamespace = 'public'::regnamespace AND i.indpred IS NOT NULL"
        ).fetchone()[0]
    finally:
        observer.close()
    assert fks == 40 and enabled == 17
    # Binary content survives byte for byte, not only by digest.
    assert _image_contents(target_url) == _image_contents(source_url) == {
        table: content for table, (_owner, _mime, content) in IMAGE_BLOBS.items()
    }
    assert checks == sum(len(pg_schema.PG_TABLE_SPECS[t]["checks"]) for t in pg_schema.PG_SCHEMA_TABLES)
    assert partial == sum(1 for index in pg_schema.PG_EXPLICIT_INDEXES.values() if index["predicate"])

    # B_PRIME: identity behaviour and restored triggers, never on B itself.
    clone, clone_url = registry.create("bprime", template=target)
    probe = _connect(clone_url)
    try:
        predicted = {t: v["predicted_next_id"] for t, v in manifest["identities"].items()}
        new_id = probe.execute(
            "INSERT INTO admin_alertas (mensagem) VALUES ('probe') RETURNING id"
        ).fetchone()[0]
        assert new_id == predicted["admin_alertas"] == HIGH_WATER["admin_alertas"] + 1
        assert probe.execute("SELECT count(*) FROM admin_alertas WHERE id = %s", (new_id,)).fetchone()[0] == 1
        for table in tool.IDENTITY_TABLES:
            if table == "admin_alertas":
                continue
            value = probe.execute(
                "SELECT nextval(pg_get_serial_sequence(%s, 'id'))", (table,)
            ).fetchone()[0]
            assert value == predicted[table], table
        rejected = []
        for statement in (
            "UPDATE requisicoes SET regra_snapshot_json = '{\"tampered\":1}' WHERE id = 17",
            "UPDATE requisicoes SET turma_codigo_snapshot = 'T9' WHERE id = 17",
            "UPDATE atividade_versao SET versao_anterior_id = 50 WHERE id = 70",
            "INSERT INTO atividade_transicao (from_atividade_versao_id, to_atividade_versao_id, tipo_transicao, "
            "justificativa) VALUES (50, 45, 'aac_para_aeu', 'x')",
        ):
            with pytest.raises(psycopg.Error) as caught:
                probe.execute(statement)
            rejected.append(caught.value.sqlstate)
        assert rejected == [pg_schema.PG_BUSINESS_RULE_SQLSTATE] * 4
    finally:
        probe.close()
    registry.drop(clone)

    # H: a tampered restored row fails verification (on a clone).
    tampered, tampered_url = registry.create("rowtamper", template=target)
    connection = _connect(tampered_url)
    connection.execute("UPDATE admin_alertas SET mensagem = 'tampered' WHERE id = 1")
    connection.close()
    with pytest.raises(tool.Failed) as caught:
        tool.verify_database(manifest, tampered_url)
    assert caught.value.code == "VERIFY_FAILED"
    assert caught.value.mismatches == [("ROW_DIGEST_MISMATCH", "admin_alertas")]
    monkeypatch.setenv(tool.TARGET_URL_ENV, tampered_url)
    code, output = _run_cli(["verify", "--manifest", manifest_path, "--restored"])
    assert code == 1 and "category=ROW_DIGEST_MISMATCH object=admin_alertas" in output
    assert "tampered" not in output.replace("tampered_", "")
    registry.drop(tampered)

    # H2: one flipped byte of image content fails verification, reported as
    # table + category only -- the content never appears.
    flipped, flipped_url = registry.create("blobtamper", template=target)
    connection = _connect(flipped_url)
    connection.execute(
        "UPDATE alunos_foto SET conteudo = overlay(conteudo placing '\\x00'::bytea from 20 for 1) "
        "WHERE aluno_id = 11"
    )
    connection.close()
    with pytest.raises(tool.Failed) as caught:
        tool.verify_database(manifest, flipped_url)
    assert set(caught.value.mismatches) == {
        ("ROW_DIGEST_MISMATCH", "alunos_foto"), ("DOMAIN_CHECK_FAILED", "alunos_foto_content_mismatch"),
    }
    monkeypatch.setenv(tool.TARGET_URL_ENV, flipped_url)
    code, output = _run_cli(["verify", "--manifest", manifest_path, "--restored"])
    assert code == 1 and "category=ROW_DIGEST_MISMATCH object=alunos_foto" in output
    blob_clean = _no_secrets(output, PG_URL, flipped_url)
    assert blob_clean
    registry.drop(flipped)

    # I: a tampered identity sequence fails verification (on a clone).
    sequenced, sequenced_url = registry.create("seqtamper", template=target)
    connection = _connect(sequenced_url)
    connection.execute("SELECT setval(pg_get_serial_sequence('usuarios', 'id'), 5, true)")
    connection.close()
    with pytest.raises(tool.Failed) as caught:
        tool.verify_database(manifest, sequenced_url)
    assert ("IDENTITY_MISMATCH", "usuarios") in caught.value.mismatches
    assert {category for category, _ in caught.value.mismatches} == {"IDENTITY_MISMATCH", "IDENTITY_COLLISION_RISK"}
    registry.drop(sequenced)

    # Evidence database B was never written or advanced by any verification.
    assert _state(target_url) == b_before
    assert _identity_states(target_url) == EXPECTED_IDENTITIES


# ---------------------------------------------------------------------------
# B. negative controls
# ---------------------------------------------------------------------------


def _copy_set(manifest_path: Path, directory: Path) -> Path:
    directory.mkdir()
    base = manifest_path.name[: -len(tool.MANIFEST_SUFFIX)]
    for suffix in (tool.DUMP_SUFFIX, tool.SIDECAR_SUFFIX, tool.MANIFEST_SUFFIX):
        shutil.copyfile(manifest_path.parent / (base + suffix), directory / (base + suffix))
    return directory / manifest_path.name


@needs_pg
def test_restore_refusals_leave_the_target_empty(registry, backup_set, tmp_path, monkeypatch):
    source, source_url = registry.source
    empty, empty_url = registry.create("empty")
    monkeypatch.delenv(tool.SOURCE_URL_ENV, raising=False)
    monkeypatch.setenv(tool.TARGET_URL_ENV, empty_url)

    def refused(manifest_path, code):
        exit_code, output = _run_cli(["restore", "--manifest", str(manifest_path)])
        assert exit_code == 1 and f"refused: {code}" in output, output
        output_clean = _no_secrets(output, PG_URL, source_url, empty_url)
        assert output_clean

    # A: artifact bytes changed.
    manifest_path = _copy_set(backup_set["manifest"], tmp_path / "a")
    dump = manifest_path.with_name(manifest_path.name.replace(tool.MANIFEST_SUFFIX, tool.DUMP_SUFFIX))
    data = bytearray(dump.read_bytes())
    data[len(data) // 2] ^= 0xFF
    dump.write_bytes(bytes(data))
    refused(manifest_path, "ARTIFACT_SHA_MISMATCH")
    # B: manifest edited / sidecar disagrees.
    manifest_path = _copy_set(backup_set["manifest"], tmp_path / "b")
    edited = json.loads(manifest_path.read_text(encoding="utf-8"))
    edited["tables"]["usuarios"]["rows"] += 1
    manifest_path.write_text(json.dumps(edited), encoding="utf-8")
    refused(manifest_path, "MANIFEST_DIGEST_MISMATCH")
    manifest_path = _copy_set(backup_set["manifest"], tmp_path / "b2")
    sidecar = manifest_path.with_name(manifest_path.name.replace(tool.MANIFEST_SUFFIX, tool.SIDECAR_SUFFIX))
    sidecar.write_text("0" * 64 + "  other.dump\n", encoding="ascii")
    refused(manifest_path, "SIDECAR_MISMATCH")
    # J: missing / malformed manifest.
    manifest_path = _copy_set(backup_set["manifest"], tmp_path / "j")
    manifest_path.unlink()
    refused(manifest_path, "MANIFEST_MISSING")
    manifest_path.write_text("{ not json", encoding="utf-8")
    refused(manifest_path, "MANIFEST_INVALID")
    assert set(_occupancy(empty_url).values()) == {0}

    good = backup_set["manifest"]
    # C: into the source itself -- by cluster identity, and by DATABASE_URL alias.
    monkeypatch.setenv(tool.TARGET_URL_ENV, source_url)
    refused(good, "TARGET_IS_SOURCE")
    monkeypatch.setenv(tool.SOURCE_URL_ENV, source_url)
    alias = urlunsplit(urlsplit(source_url)._replace(netloc=urlsplit(source_url).netloc.replace("127.0.0.1", "localhost")))
    monkeypatch.setenv(tool.TARGET_URL_ENV, alias)
    refused(good, "TARGET_IS_SOURCE")
    monkeypatch.delenv(tool.SOURCE_URL_ENV)
    # D: protected databases.
    for name in ("sgaa_qual", "postgres", "template1"):
        monkeypatch.setenv(tool.TARGET_URL_ENV, _database_url(name))
        refused(good, "TARGET_PROTECTED")
    # E: non-empty targets -- a provisioned SGAA schema, a stray schema, a stray table.
    provisioned, provisioned_url = registry.create("provisioned", template=registry.template)
    stray_schema, stray_schema_url = registry.create("strayschema")
    stray_table, stray_table_url = registry.create("straytable")
    for url, statement in ((stray_schema_url, "CREATE SCHEMA stray"),
                           (stray_table_url, "CREATE TABLE public.notes (id integer)")):
        connection = _connect(url)
        connection.execute(statement)
        connection.close()
    for url in (provisioned_url, stray_schema_url, stray_table_url):
        monkeypatch.setenv(tool.TARGET_URL_ENV, url)
        refused(good, "TARGET_NOT_EMPTY")
    assert _state(provisioned_url).tables["usuarios"]["rows"] == 0  # untouched, not cleaned
    for database in (provisioned, stray_schema, stray_table):
        registry.drop(database)

    assert set(_occupancy(empty_url).values()) == {0}
    assert _state(source_url) == backup_set["before"]
    registry.drop(empty)


@needs_pg
def test_restore_failing_after_creating_objects_rolls_back_completely(registry, backup_set, monkeypatch):
    """The public-schema entry is moved to the END of the list, so pg_restore
    creates every table, row, index and trigger first and only then fails."""
    target, target_url = registry.create("latefail")
    monkeypatch.setenv(tool.TARGET_URL_ENV, target_url)
    original = tool.restore_list
    lists = []

    def fail_last(listing):
        lines = original(listing).splitlines()
        schema = next(line for line in lines if line.startswith(";") and " SCHEMA - public " in line)
        lines.remove(schema)
        lines.append(schema[1:])
        lists.append(lines)
        return "\n".join(lines) + "\n"

    monkeypatch.setattr(tool, "restore_list", fail_last)
    code, output = _run_cli(["restore", "--manifest", str(backup_set["manifest"])])
    assert code == 1, output
    assert "RESTORE_FAILED" in output and "class=OBJECT_EXISTS" in output
    assert "target verified still empty" in output
    assert "already exists" not in output  # native stderr is classified, not forwarded
    entries = [line for line in lists[0] if line and not line.startswith(";")]
    assert entries[-1].endswith("SCHEMA - public pg_database_owner") and len(entries) > 250
    assert set(_occupancy(target_url).values()) == {0}
    registry.drop(target)


VERIFY_DETAIL_SENTINEL = "pgbk-detail-s3ntinel"


@needs_pg
@pytest.mark.parametrize("failure", ["mismatch", "psycopg_error", "interrupt"])
def test_restore_committed_then_verification_fails_needs_reconciliation(registry, backup_set, monkeypatch, failure):
    """pg_restore itself runs and commits; the failpoint sits inside the
    post-restore verification (``read_state``).  From then on the target is
    RESTORED: exit 3, no rollback claim, no exception text or row DETAIL."""
    source, source_url = registry.source
    target, target_url = registry.create(f"verifyfail_{failure}")
    manifest = json.loads(backup_set["manifest"].read_text(encoding="utf-8"))
    monkeypatch.delenv(tool.SOURCE_URL_ENV, raising=False)
    monkeypatch.setenv(tool.TARGET_URL_ENV, target_url)
    real_read_state = tool.read_state
    calls = []

    def failpoint(conn):
        calls.append(failure)
        if failure == "mismatch":  # a real difference committed before verification reads
            writer = _connect(target_url)
            try:
                writer.execute("UPDATE admin_alertas SET mensagem = 'tampered after restore' WHERE id = 1")
            finally:
                writer.close()
            return real_read_state(conn)
        if failure == "psycopg_error":  # a server error whose DETAIL quotes a row
            conn.execute(
                "DO $$ BEGIN RAISE EXCEPTION USING ERRCODE = '23514', "
                "MESSAGE = 'new row for relation \"usuarios\" violates check constraint', "
                f"DETAIL = 'Failing row contains (3, {ADMIN_EMAIL}, {VERIFY_DETAIL_SENTINEL}).'; END $$"
            )
        raise KeyboardInterrupt

    monkeypatch.setattr(tool, "read_state", failpoint)
    code, output = _run_cli(["restore", "--manifest", str(backup_set["manifest"])])
    monkeypatch.setattr(tool, "read_state", real_read_state)

    assert calls == [failure]
    reconciliation = code == tool.EXIT_RECONCILE and "NEEDS RECONCILIATION: RESTORE_VERIFY_FAILED" in output
    restored_message = "pg_restore completed and committed" in output and "do not restore into it again" in output
    false_claims = [claim for claim in ("rolled back", "nothing was restored", "nothing was promoted",
                                        "still empty", "RESTORE_OK") if claim in output]
    leaked = VERIFY_DETAIL_SENTINEL in output or "Failing row" in output or "tampered after" in output
    output_clean = _no_secrets(output, PG_URL, source_url, target_url)
    assert reconciliation and restored_message
    assert false_claims == [] and not leaked and output_clean
    reason = {
        "mismatch": "category=ROW_DIGEST_MISMATCH object=admin_alertas",
        "psycopg_error": "CheckViolation sqlstate=23514",
        "interrupt": "(KeyboardInterrupt)",
    }[failure]
    assert reason in output

    # The tool cleaned nothing up: the target still holds the committed restore.
    occupancy = _occupancy(target_url)
    assert occupancy["relations"] > 0 and occupancy["routines"] > 0
    if failure == "mismatch":
        with pytest.raises(tool.Failed) as caught:
            tool.verify_database(manifest, target_url)
        assert caught.value.mismatches == [("ROW_DIGEST_MISMATCH", "admin_alertas")]
    else:
        tool.verify_database(manifest, target_url)  # complete and equal to the manifest
    registry.drop(target)


@needs_pg
def test_restore_pins_pg_restore_to_the_checked_target_address(registry, backup_set, tmp_path, monkeypatch):
    """The real pg_restore runs with a stale PGHOSTADDR and a bogus PGSERVICE
    in its inherited environment: it can only succeed because the tool pins
    the checked preflight address and strips the service routing."""
    source, source_url = registry.source
    target, target_url = registry.create("pinned")
    monkeypatch.delenv(tool.SOURCE_URL_ENV, raising=False)
    monkeypatch.setenv(tool.TARGET_URL_ENV, target_url)
    observed = {}
    real_checked, real_environment, real_run = tool.checked_hostaddr, tool._child_environment, tool.run_native

    def recording_checked(conn):
        observed["checked_database"] = conn.execute("SELECT current_database()").fetchone()[0]
        observed["checked_hostaddr"] = real_checked(conn)
        return observed["checked_hostaddr"]

    def recording_environment(pinned_hostaddr=None):
        environment = real_environment(pinned_hostaddr)
        if pinned_hostaddr is not None:
            observed["child"] = {name: environment.get(name) for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")}
        return environment

    def stale_inherited_run(argv, **kwargs):
        if "--single-transaction" not in argv:
            return real_run(argv, **kwargs)
        observed["dbname_is_target_url"] = argv[argv.index("--dbname") + 1] == target_url
        with pytest.MonkeyPatch.context() as inherited:
            inherited.setenv("PGHOSTADDR", "198.51.100.99")  # TEST-NET-2: unreachable if used
            inherited.setenv("PGSERVICE", "sgaa-pgbk-no-such-service")  # libpq error if used
            inherited.setenv("PGSERVICEFILE", str(tmp_path / "missing-pg_service.conf"))
            return real_run(argv, **kwargs)

    monkeypatch.setattr(tool, "checked_hostaddr", recording_checked)
    monkeypatch.setattr(tool, "_child_environment", recording_environment)
    monkeypatch.setattr(tool, "run_native", stale_inherited_run)
    code, output = _run_cli(["restore", "--manifest", str(backup_set["manifest"])])
    for name, original in (("checked_hostaddr", real_checked), ("_child_environment", real_environment),
                           ("run_native", real_run)):
        monkeypatch.setattr(tool, name, original)

    restored = code == 0 and "result: RESTORE_OK" in output and f"database={target}" in output
    assert restored
    leaked = "198.51.100.99" in output or "no-such-service" in output
    output_clean = _no_secrets(output, PG_URL, source_url, target_url)
    assert not leaked and output_clean
    # The pin is the checked live connection's address, and that connection was the target.
    independent = _connect(target_url)
    try:
        live_hostaddr = independent.info.hostaddr
    finally:
        independent.close()
    assert observed["checked_database"] == target
    assert observed["checked_hostaddr"] == live_hostaddr
    assert observed["child"] == {"PGHOSTADDR": live_hostaddr, "PGSERVICE": None, "PGSERVICEFILE": None}
    assert observed["dbname_is_target_url"]
    manifest = json.loads(backup_set["manifest"].read_text(encoding="utf-8"))
    tool.verify_database(manifest, target_url)
    registry.drop(target)


@needs_pg
def test_backup_refusals_create_no_artifact_and_never_touch_the_source(registry, tmp_path, monkeypatch):
    source, source_url = registry.source
    before = _state(source_url)

    def refused(url, code, directory, **kwargs):
        directory.mkdir()
        monkeypatch.setenv(tool.SOURCE_URL_ENV, url)
        with pytest.raises(tool.BackupToolError) as caught:
            tool.backup(directory, "neg", **kwargs)
        assert caught.value.code == code, str(caught.value)
        assert list(directory.iterdir()) == []
        return caught.value

    # F: pg_dump older than the server.
    real_version = tool._tool_version
    monkeypatch.setattr(tool, "_tool_version",
                        lambda path: ("14.11", 14) if "pg_dump" in Path(path).name else real_version(path))
    error = refused(source_url, "CLIENT_OLDER_THAN_SERVER", tmp_path / "f")
    assert "pg_dump 14.11" in str(error)
    monkeypatch.setattr(tool, "_tool_version", real_version)

    # G: objects outside the contract are caught in the archive TOC after pg_dump.
    stray_fn, stray_fn_url = registry.create("strayfn", template=registry.source[0])
    stray_view, stray_view_url = registry.create("strayview", template=registry.source[0])
    disabled, disabled_url = registry.create("disabled", template=registry.source[0])
    bare, bare_url = registry.create("bare")
    for url, statement in (
        (stray_fn_url, "CREATE FUNCTION public.stray_fn() RETURNS integer LANGUAGE sql AS 'SELECT 1'"),
        (stray_view_url, "CREATE VIEW public.stray_view AS SELECT id FROM admin_alertas"),
        (disabled_url, "ALTER TABLE requisicoes DISABLE TRIGGER trg_requisicoes_snapshot_immutable"),
    ):
        connection = _connect(url)
        connection.execute(statement)
        connection.close()
    error = refused(stray_fn_url, "TOC_UNEXPECTED_OBJECT", tmp_path / "g1")
    assert "FUNCTION: stray_fn" in str(error)
    error = refused(stray_view_url, "TOC_UNEXPECTED_OBJECT_CLASS", tmp_path / "g2")
    assert "VIEW" in str(error)
    # Structurally invalid sources are refused before any dump.
    refused(disabled_url, "TRIGGERS_NOT_ENABLED", tmp_path / "t")
    refused(bare_url, "SCHEMA_NOT_CURRENT", tmp_path / "s")
    for database in (stray_fn, stray_view, disabled, bare):
        registry.drop(database)

    # K: a failing native tool -> safe code, staging removed, stderr not forwarded.
    real_run = tool.run_native

    def bad_snapshot(argv, **kwargs):
        argv = ["--snapshot=00000003-0000001B-1" if str(a).startswith("--snapshot=") else a for a in argv]
        return real_run(argv, **kwargs)

    monkeypatch.setattr(tool, "run_native", bad_snapshot)
    (tmp_path / "k").mkdir()
    monkeypatch.setenv(tool.SOURCE_URL_ENV, source_url)
    code, output = _run_cli(["backup", "--output-dir", str(tmp_path / "k"), "--label", "neg"])
    assert code == 1 and "NATIVE_TOOL_FAILED: pg_dump exit=1 class=SNAPSHOT_REJECTED" in output
    output_clean = _no_secrets(output, PG_URL, source_url)
    assert "invalid snapshot identifier" not in output and output_clean
    assert list((tmp_path / "k").iterdir()) == []
    monkeypatch.setattr(tool, "run_native", real_run)

    # An existing artifact set is never replaced.
    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    (tmp_path / "dup").mkdir()
    first = tool.backup(tmp_path / "dup", "dup", now=moment)
    snapshot = {p.name: p.read_bytes() for p in (tmp_path / "dup").iterdir()}
    with pytest.raises(tool.Refused) as caught:
        tool.backup(tmp_path / "dup", "dup", now=moment)
    assert caught.value.code == "ARTIFACT_EXISTS"
    assert {p.name: p.read_bytes() for p in (tmp_path / "dup").iterdir()} == snapshot
    assert first.paths.manifest.is_file()

    assert _state(source_url) == before


# ---------------------------------------------------------------------------
# C. E-PG2: online consistency
# ---------------------------------------------------------------------------


def _exporting_sessions(observer, database) -> int:
    return observer.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND state = 'idle in transaction' "
        "AND backend_xmin IS NOT NULL AND pid <> pg_backend_pid()",
        (database,),
    ).fetchone()[0]


@needs_pg
def test_online_backup_captures_the_exported_snapshot_not_a_later_writer(registry, tmp_path, monkeypatch):
    online, online_url = registry.create("online", template=registry.source[0])
    pre = _state(online_url)
    pre_rows = _rows(online_url)
    observer = _connect(online_url)
    events = {}

    def concurrent_writer():
        # Runs after pg_export_snapshot(), before the manifest is read and pg_dump starts.
        events["exporting_before_write"] = _exporting_sessions(observer, online)
        writer = _connect(online_url)
        try:
            events["new_id"] = writer.execute(
                "INSERT INTO admin_alertas (mensagem) VALUES ('after snapshot') RETURNING id"
            ).fetchone()[0]
            writer.execute("UPDATE usuarios SET nome = 'Renamed after snapshot' WHERE id = 3")
        finally:
            writer.close()
        # Observed committed state: a fresh session sees the writer's row.
        fresh = _connect(online_url)
        try:
            events["visible_rows"] = fresh.execute("SELECT count(*) FROM admin_alertas").fetchone()[0]
        finally:
            fresh.close()

    real_run = tool.run_native

    def observing_run(argv, **kwargs):
        if any(str(a).startswith("--snapshot=") for a in argv):
            events["exporting_during_dump"] = _exporting_sessions(observer, online)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(tool, "run_native", observing_run)
    monkeypatch.setenv(tool.SOURCE_URL_ENV, online_url)
    try:
        result = tool.backup(tmp_path, "online", after_snapshot_export=concurrent_writer)
        events["exporting_after"] = _exporting_sessions(observer, online)
    finally:
        observer.close()
    monkeypatch.setattr(tool, "run_native", real_run)

    pre_count = pre.tables["admin_alertas"]["rows"]
    assert events["exporting_before_write"] == 1 and events["exporting_during_dump"] == 1
    assert events["exporting_after"] == 0
    assert events["visible_rows"] == pre_count + 1
    new_id = events["new_id"]
    # The manifest describes the snapshot, not the committed writer (and, for
    # the v14 schema-only tables, the empty state a restore yields).
    expected_tables = {**pre.tables, **tool._EMPTY_TABLE}
    assert result.manifest["tables"] == expected_tables
    post = _state(online_url)
    assert post.tables["admin_alertas"]["rows"] == pre_count + 1
    assert post.tables["usuarios"]["sha256"] != pre.tables["usuarios"]["sha256"]
    # Identity sequences are outside MVCC: the archive carries the advanced
    # value, so a restore skips the writer's id -- above every archived row.
    entry = result.manifest["identities"]["admin_alertas"]
    assert entry["max_id"] == pre.max_ids["admin_alertas"] < new_id
    assert entry["predicted_next_id"] == new_id + 1
    assert entry["observed_in_snapshot_transaction"]["predicted_next_id"] == new_id + 1

    target, target_url = registry.create("onlinerestore")
    monkeypatch.setenv(tool.TARGET_URL_ENV, target_url)
    restored = tool.restore(result.paths.manifest)
    assert restored.tables == expected_tables
    restored_rows = _rows(target_url)
    for table in tool.SCHEMA_ONLY_TABLE_POLICIES:
        assert restored_rows[table] == {}
        restored_rows[table] = pre_rows[table]
    snapshot_rows = restored_rows == pre_rows
    assert snapshot_rows
    connection = _connect(target_url)
    try:
        assert connection.execute("SELECT count(*) FROM admin_alertas WHERE id = %s", (new_id,)).fetchone()[0] == 0
        assert connection.execute("SELECT nome FROM usuarios WHERE id = 3").fetchone()[0] == "Admin Sintetico"
    finally:
        connection.close()
    assert _identity_states(target_url)["admin_alertas"] == (new_id, True)
    for database in (online, target):
        registry.drop(database)


# ---------------------------------------------------------------------------
# D. current-data recovery rehearsal (opt-in)
# ---------------------------------------------------------------------------


class _Prompt:
    def __init__(self, *answers):
        self.answers = list(answers)

    def __call__(self, text):
        return self.answers.pop(0)


def _login_status(main, app_db, url, email, password) -> str:
    """``"ok"`` or a value-free code.  Never raises: this frame holds the
    e-mail and password, which pytest would print with a traceback."""
    try:
        app_db.DATABASE_URL = url
        with main.app.app_context():
            app_db.close_db_connection(None)
        client = main.app.test_client()
        login = client.post("/login", data={"email": email, "senha": password}).status_code
        if login != 302:
            return f"POST /login {login}"
        page = client.get("/admin/acesso").status_code
        return "ok" if page == 200 else f"GET /admin/acesso {page}"
    except Exception as exc:
        return f"login raised {_safe_error(exc)}"
    finally:
        try:
            with main.app.app_context():
                app_db.close_db_connection(None)
        except Exception:
            pass


def _pending_full_admins(url) -> list:
    observer = _connect(url)
    try:
        return [row[0] for row in observer.execute(
            "SELECT u.email FROM usuarios u JOIN usuario_credenciais c ON c.usuario_id = u.id "
            "WHERE u.tipo='admin' AND u.nivel_acesso='admin_total' AND c.estado='pending' AND c.acesso_ativo=1"
        ).fetchall()]
    finally:
        observer.close()


def _rejection_sqlstate(conn, statement, params) -> str:
    """SQLSTATE of the expected rejection (the error text is discarded)."""
    import psycopg

    try:
        conn.execute(statement, params)
    except psycopg.Error as exc:
        return str(exc.sqlstate)
    return "NOT_REJECTED"


def _chain_bprime_probe(clone_url) -> dict:
    """Identity allocation and trigger rejections on a clone of real data; value-free results."""
    probe = _connect(clone_url)
    try:
        allocated = {}
        for table in tool.IDENTITY_TABLES:
            if table == "admin_alertas":
                continue
            allocated[table] = probe.execute(
                "SELECT nextval(pg_get_serial_sequence(%s, 'id'))", (table,)
            ).fetchone()[0]
        allocated["admin_alertas"] = probe.execute(
            "INSERT INTO admin_alertas (mensagem) VALUES ('probe') RETURNING id"
        ).fetchone()[0]
        rejections = []
        request = probe.execute("SELECT min(id) FROM requisicoes").fetchone()[0]
        if request is not None:
            rejections.append(_rejection_sqlstate(
                probe, "UPDATE requisicoes SET regra_snapshot_json = '{\"tampered\":1}' WHERE id = %s", (request,)
            ))
        pair = probe.execute(
            "SELECT a.id, e.id FROM atividade_versao a, atividade_versao e "
            "WHERE a.eixo = 'AAC' AND e.eixo = 'AEU' ORDER BY a.id, e.id LIMIT 1"
        ).fetchone()
        if pair is not None:
            rejections.append(_rejection_sqlstate(
                probe, "UPDATE atividade_versao SET versao_anterior_id = %s WHERE id = %s", (pair[1], pair[0])
            ))
        return {"allocated": allocated, "rejections": rejections}
    finally:
        probe.close()


@needs_pg
@pytest.mark.skipif(
    not (REHEARSAL_SOURCE and REHEARSAL_SHA256 and REHEARSAL_UPLOAD_ROOT),
    reason="SGAA_PATHB_SOURCE / _SHA256 / _UPLOAD_ROOT not set -- current-data rehearsal not requested",
)
def test_current_data_recovery_chain(registry, tmp_path, monkeypatch, capsys):
    """SQLITE COPY -> PATH-B -> R5 -> LOGIN A -> BACKUP -> RESTORE B -> VALIDATE -> LOGIN B.

    Real current data: every assertion operand is a precomputed boolean,
    count or safe code; every data-touching call runs under ``_guarded``;
    logging is disabled so no captured record can quote a row or an e-mail.
    """
    import main
    from app import admin_bootstrap
    from app import db as app_db

    evidence = []
    asset_root = tmp_path / "rehearsal_assets"
    artifacts = tmp_path / "rehearsal_backup"
    artifacts.mkdir()
    a, a_url = registry.create("chain_a", template=registry.template)
    b, b_url = registry.create("chain_b")
    password = secrets.token_urlsafe(24)
    monkeypatch.setitem(main.app.config, "TESTING", True)
    monkeypatch.setitem(main.app.config, "UPLOAD_FOLDER", str(asset_root))
    monkeypatch.setattr(app_db, "DATABASE_URL", app_db.DATABASE_URL)
    logging_disabled_before = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        # PATH-B: frozen copy -> A.
        monkeypatch.setenv("DATABASE_URL", a_url)
        code = _guarded("path-b", lambda: pathb.main([
            "--source", REHEARSAL_SOURCE, "--expected-source-sha256", REHEARSAL_SHA256,
            "--source-upload-root", REHEARSAL_UPLOAD_ROOT, "--target-upload-root", str(asset_root), "--apply",
        ]))
        captured = capsys.readouterr()
        migrated = code == 0 and "result: MIGRATED" in captured.out
        assert migrated
        evidence.append("path-b: MIGRATED into disposable A")

        # VALIDATE A.
        state_a0 = _guarded("read A", lambda: _state(a_url))
        domain_green = set(state_a0.domain.values()) == {0}
        assert domain_green
        evidence.append(f"A: schema CURRENT, {len(state_a0.domain)} domain checks green, "
                        f"{state_a0.triggers_enabled} triggers enabled")

        # R5 on A, then LOGIN A.
        candidates = _guarded("pending admin lookup", lambda: _pending_full_admins(a_url))
        single_pending_admin = len(candidates) == 1
        assert single_pending_admin
        admin_email = candidates[0]
        app_db.DATABASE_URL = a_url
        code = _guarded("R5", lambda: admin_bootstrap.main(["--email", admin_email],
                                                           prompt=_Prompt(password, password)))
        captured = capsys.readouterr()
        activated = code == 0 and password not in captured.out + captured.err
        assert activated
        login_a = _login_status(main, app_db, a_url, admin_email, password)
        assert login_a == "ok"
        evidence.append("R5: pending full admin activated on A; login A: POST /login 302, GET /admin/acesso 200")

        # BACKUP A (CLI).
        monkeypatch.setenv(tool.SOURCE_URL_ENV, a_url)
        state_a = _guarded("read A", lambda: _state(a_url))
        code, output = _run_cli(["backup", "--output-dir", str(artifacts), "--label", "rehearsal"])
        clean = "@" not in output and "pbkdf2" not in output and a_url not in output
        assert code == 0 and clean
        [manifest_path] = artifacts.glob("*.manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_clean = "@" not in json.dumps(manifest) and "pbkdf2" not in json.dumps(manifest)
        assert manifest_clean
        tables_equal = manifest["tables"] == state_a.tables
        assert tables_equal
        evidence.append(f"backup: {manifest['artifact']['size']} bytes sha256={manifest['artifact']['sha256']} "
                        f"toc={manifest['toc']['entries']} entries (SGAA contract only)")

        # RESTORE B (CLI, verifies against the manifest) + independent comparison.
        monkeypatch.setenv(tool.TARGET_URL_ENV, b_url)
        code, output = _run_cli(["restore", "--manifest", str(manifest_path)])
        restored = code == 0 and "result: RESTORE_OK" in output
        assert restored
        _guarded("verify A", lambda: tool.verify_database(manifest, a_url))  # A still equals its manifest
        same_rows = _guarded("compare rows", lambda: _rows(a_url) == _rows(b_url))
        assert same_rows
        manifest_identities = {t: (v["last_value"], v["is_called"]) for t, v in manifest["identities"].items()}
        same_identities = _guarded(
            "compare identities", lambda: _identity_states(b_url) == _identity_states(a_url) == manifest_identities
        )
        assert same_identities
        for table in pg_schema.PG_SCHEMA_TABLES:
            evidence.append(f"table: {table} rows={manifest['tables'][table]['rows']} "
                            f"sha256={manifest['tables'][table]['sha256']} A=manifest=B")
        for table, entry in sorted(manifest["identities"].items()):
            evidence.append(f"identity: {table} last_value={entry['last_value']} is_called={entry['is_called']} "
                            f"next={entry['predicted_next_id']} max_id={entry['max_id']} A=manifest=B")
        evidence.append(f"domain checks on B: {manifest['domain_validation']['checks']} green; "
                        f"triggers {manifest['triggers']['enabled']}/{manifest['triggers']['expected']}; "
                        f"accounts usuarios={manifest['accounts']['usuarios']} "
                        f"credenciais={manifest['accounts']['usuario_credenciais']}")

        # B_PRIME: identity behaviour + restored triggers on real data.
        clone, clone_url = registry.create("chain_bprime", template=b)
        probed = _guarded("B_PRIME probe", lambda: _chain_bprime_probe(clone_url))
        registry.drop(clone)
        predicted = {t: v["predicted_next_id"] for t, v in manifest["identities"].items()}
        allocation_mismatches = sorted(t for t in predicted if probed["allocated"].get(t) != predicted[t])
        assert allocation_mismatches == []
        probes = len(probed["rejections"])
        all_rejected = all(state == pg_schema.PG_BUSINESS_RULE_SQLSTATE for state in probed["rejections"])
        assert all_rejected and probes >= 1
        evidence.append(f"B_PRIME: 21 identities nextval/INSERT == predicted, no collision; "
                        f"{probes} trigger rejection(s) SG001; B_PRIME dropped")

        # LOGIN B with the password activated on A.
        login_b = _login_status(main, app_db, b_url, admin_email, password)
        assert login_b == "ok"
        evidence.append("login B: POST /login 302, GET /admin/acesso 200 (credential restored from backup)")
        source_unchanged = tool.file_sha256(Path(REHEARSAL_SOURCE))[1] == REHEARSAL_SHA256.lower()
        assert source_unchanged
    finally:
        logging.disable(logging_disabled_before)
        with main.app.app_context():
            app_db.close_db_connection(None)
        del password
        shutil.rmtree(artifacts, ignore_errors=True)
        shutil.rmtree(asset_root, ignore_errors=True)
        for database in (a, b):
            registry.drop(database)
    assert not artifacts.exists() and not asset_root.exists()
    with capsys.disabled():
        print("\n=== PG LOGICAL BACKUP CURRENT-DATA REHEARSAL EVIDENCE ===")
        for line in evidence:
            print(line)
