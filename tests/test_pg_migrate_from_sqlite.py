# coding: utf-8
"""Path-B migration owner (``app.pg_migrate_from_sqlite``).

A. static/refusal nodes (no PostgreSQL): the policy manifest covers every
   source and target table, the load order puts parents first, and the source
   and target preconditions refuse before anything is written.
B. synthetic real-PostgreSQL nodes (``SGAA_PG_TEST_URL``): a hand-built
   prod-1/v13 SQLite source with sparse ids, ``sqlite_sequence`` above
   ``max(id)``, a forward self-reference, excluded secrets, one local file and
   v13 image rows (BLOB -> bytea) is migrated into a freshly provisioned clone; failures after the first
   write roll back rows, identity sequences and copied files.
C. the actual-source rehearsal, opt-in through ``SGAA_PATHB_SOURCE`` /
   ``SGAA_PATHB_SOURCE_SHA256`` / ``SGAA_PATHB_SOURCE_UPLOAD_ROOT``: a frozen
   copy is migrated, validated independently, its pending full administrator
   is activated through the R5 CLI and logs in through ``POST /login``.  Only
   aggregate, non-personal evidence is printed.

Synthetic sources are private copies of the pytest session database (built by
the production ``init_db``), emptied and refilled with synthetic rows; the
operational ``database.db`` is never read.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

from app import pg_migrate_from_sqlite as pathb
from app import pg_schema

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()
REHEARSAL_SOURCE = os.environ.get("SGAA_PATHB_SOURCE", "").strip()
REHEARSAL_SHA256 = os.environ.get("SGAA_PATHB_SOURCE_SHA256", "").strip()
REHEARSAL_UPLOAD_ROOT = os.environ.get("SGAA_PATHB_SOURCE_UPLOAD_ROOT", "").strip()

needs_pg = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

RUN_PREFIX = f"sgaa_pathb_test_{secrets.token_hex(4)}_"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})
CONNECT_TIMEOUT_SECONDS = 10
UNUSED_PG_URL = "postgresql://nobody@127.0.0.1:1/never_connected"

ADMIN_EMAIL = "pathb.admin@example.test"
STUDENT_EMAIL = "pathb.aluno@example.test"
SECRET_TOKEN_JSON = '{"refresh_token":"pathb-synthetic-secret"}'
ASSET_RELATIVE = "pathb_docs/manual.pdf"
ASSET_BYTES = b"%PDF-1.4\n% pathb synthetic manual\n%%EOF\n"
TS = "2026-01-02 03:04:05"
#: v13 image content; the marker must never reach any output.
BLOB_MARKER = b"PATHB-BLOB-MARKER"
IMAGE_ROWS = {
    "usuarios_foto": ("usuario_id", 3, "image/png", b"\x89PNG\r\n\x1a\n" + BLOB_MARKER * 6 + bytes(range(256))),
    "alunos_foto": ("aluno_id", 11, "image/jpeg", b"\xff\xd8\xff" + BLOB_MARKER * 4 + b"\x00\xff" * 200),
    "reportes_captura": ("reporte_id", 4, "image/webp", b"RIFF\x00\x00\x00\x00WEBP" + BLOB_MARKER + bytes(2048)),
}

#: Synthetic ``sqlite_sequence`` high-waters, all above the rows' max(id).
HIGH_WATER = {
    "usuarios": 12,
    "senha_tokens": 6,
    "cloud_accounts": 4,
    "cloud_drive_settings": 1,
    "cursos": 3,
    "matrizes_atividades": 5,
    "turmas": 9,
    "alunos": 15,
    "atividade_base": 23,
    "atividade_versao": 80,
    "atividade_transicao": 2,
    "matriz_atividade_versao_item": 14,
    "requisicoes": 25,
    "requisicao_arquivos": 6,
    "requisicao_alerta_receipts": 2,
    "reportes": 4,
    "admin_arquivos": 4,
    "admin_alertas": 1,
    "email_envios": 3,
    "requisicao_email_eventos": 2,
}


# ---------------------------------------------------------------------------
# synthetic source
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _insert(conn, table, **values):
    columns = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(values.values()))


def build_synthetic_source(directory: Path, *, tentativas=1, extra_sql=()) -> tuple[Path, str]:
    """A frozen prod-1/v13 SQLite file holding synthetic data only."""
    path = directory / "pathb_source.db"
    session = sqlite3.connect(os.environ["APP_DATABASE"])
    conn = sqlite3.connect(path)
    try:
        session.backup(conn)
    finally:
        session.close()
    conn.execute("PRAGMA foreign_keys = OFF")
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        conn.execute(f'DELETE FROM "{table}"')
    i = _insert
    i(conn, "usuarios", id=3, nome="Admin Sintetico", email=ADMIN_EMAIL, senha="pbkdf2:synthetic",
      tipo="admin", nivel_acesso="admin_total")
    i(conn, "usuarios", id=7, nome="Aluno Sintetico", email=STUDENT_EMAIL, senha="pbkdf2:synthetic2",
      tipo="aluno", nivel_acesso="usuario")
    i(conn, "usuario_credenciais", usuario_id=3, estado="pending", auth_version=2, atualizado_em=TS, acesso_ativo=1)
    i(conn, "usuario_credenciais", usuario_id=7, estado="default", auth_version=1, atualizado_em=TS, acesso_ativo=1)
    i(conn, "configuracoes_acesso", nivel_acesso="admin_total", senha_padrao="synthetic-profile-default")
    i(conn, "configuracoes_app", chave="response_goal_days", valor="12", atualizado_em=TS)
    i(conn, "configuracoes_presets", tipo="emails", preset_id=1, titulo="T", texto="Corpo", atualizado_em=TS,
      assunto="A", is_default=1)
    i(conn, "configuracoes_backup", chave="local_backup_dir", valor="C:/synthetic/backups", atualizado_em=TS)
    i(conn, "cloud_accounts", id=4, provider="google", account_email="drive@example.test",
      token_json=SECRET_TOKEN_JSON, connected_at=TS, updated_at=TS, active=1)
    i(conn, "cloud_drive_settings", id=1, provider="google", folder_id="synthetic-folder",
      folder_name="Backups", folder_path_label="Backups", drive_id=None, updated_at=TS)
    i(conn, "senha_tokens", id=5, usuario_id=7, purpose="first_access", token_hash="b" * 64,
      created_at=TS, expires_at="2099-01-01 00:00:00")
    i(conn, "cursos", id=2, nome="Curso", codigo="C1", duracao_periodos=8, total_horas_aac=160,
      total_horas_aeu=160, periodo="diurno", status="ativo")
    i(conn, "matrizes_atividades", id=5, curso_id=2, nome="Matriz", status="vigente",
      horas_aac_obrigatorias=160, horas_extensao_obrigatorias=160, created_at=TS)
    i(conn, "turmas", id=9, nome="Turma 1", turno="noite", status="Ativa", numero=1, curso_id=2,
      ano_inicio=2024, semestre_inicio=1, codigo="T1", matriz_id=5)
    i(conn, "alunos", id=11, usuario_id=7, nome="Aluno Sintetico", matricula="M-11", email=STUDENT_EMAIL,
      turma_id=9, matriz_id=5, status="Ativo")
    for base_id, nome in ((20, "Conceito A"), (21, "Conceito B"), (22, "Conceito C")):
        i(conn, "atividade_base", id=base_id, nome_conceito=nome, status="ativo", created_at=TS)
    versions = (
        dict(id=30, atividade_base_id=20, eixo="AAC", numero_versao=1, status="substituida", ch_por_evento=2.5),
        dict(id=45, atividade_base_id=20, eixo="AAC", numero_versao=2, status="ativa",
             versao_anterior_id=30, limite_total=40.0, documentos_json='["certificado"]'),
        dict(id=50, atividade_base_id=21, eixo="AEU", numero_versao=1, status="ativa", limite_semestre=10),
        # Forward self-reference: the predecessor has the higher id.
        dict(id=70, atividade_base_id=22, eixo="AAC", numero_versao=1, status="substituida"),
        dict(id=12, atividade_base_id=22, eixo="AAC", numero_versao=2, status="ativa", versao_anterior_id=70),
    )
    for version in versions:
        i(conn, "atividade_versao", created_at=TS, **version)
    i(conn, "atividade_transicao", id=2, from_atividade_versao_id=45, to_atividade_versao_id=50,
      tipo_transicao="aac_para_aeu", justificativa="Normativa", created_at=TS)
    i(conn, "matriz_atividade_versao_item", id=8, matriz_id=5, atividade_base_id=20, atividade_versao_id=45, created_at=TS)
    i(conn, "matriz_atividade_versao_item", id=13, matriz_id=5, atividade_base_id=21, atividade_versao_id=50, created_at=TS)
    i(conn, "requisicoes", id=17, aluno_id=11, atividade_versao_id=45, data_solicitacao=TS, data_evento="2026-01-01",
      horas_solicitadas=10.5, nome_evento="Evento", status="Deferida", horas_deferidas=10.0, admin_id=3,
      regra_snapshot_json='{"ch_por_evento":2.5}', turma_id_snapshot=9, turma_codigo_snapshot="T1")
    i(conn, "requisicoes", id=18, aluno_id=11, atividade_versao_id=50, data_solicitacao=TS, data_evento="2026-01-01",
      horas_solicitadas=4, status="Pendente", regra_snapshot_json="{}")
    i(conn, "requisicao_arquivos", id=6, requisicao_id=17, filename="comprovante.pdf", criado_em=TS, provider="google",
      remote_file_id="remote-file", remote_parent_id="remote-parent", original_filename="c.pdf",
      mime_type="application/pdf", size_bytes=100, sha256="c" * 64, uploaded_at=TS, uploader_user_id=3,
      operation_key="op-1", storage_status="active")
    i(conn, "requisicao_alerta_receipts", id=2, requisicao_id=17, usuario_id=3, alert_kind="nova", seen_at=TS)
    i(conn, "admin_arquivos", id=4, titulo="Manual", filename=ASSET_RELATIVE, original_filename="manual.pdf",
      visivel=1, criado_em=TS, provider="local_legacy", storage_status="legacy_active")
    i(conn, "admin_alertas", id=1, titulo="Aviso", mensagem="Mensagem", visivel=1, criado_em=TS)
    i(conn, "email_envios", id=3, aluno_id=11, destinatario=STUDENT_EMAIL, assunto="A", corpo="C", status="sent",
      tentativas=tentativas, idempotency_key="k-1", criado_em=TS, enviado_em=TS)
    i(conn, "reportes", id=4, aluno_id=11, titulo="Reporte", descricao="Descricao", categoria="Outro",
      status="Novo", criado_em=TS, atualizado_em=TS)
    for table, (owner_column, owner_id, mime_type, content) in IMAGE_ROWS.items():
        i(conn, table, **{owner_column: owner_id}, mime_type=mime_type, size_bytes=len(content),
          sha256=_sha256(content), width=64, height=48, conteudo=content, atualizado_em=TS)
    from app.pg_schema import PG_SCHEMA_EPOCH, PG_SCHEMA_MIGRATIONS_SEED

    for version, name, details in PG_SCHEMA_MIGRATIONS_SEED:
        i(conn, "schema_migrations", version=version, name=name, schema_epoch=PG_SCHEMA_EPOCH,
          applied_at=TS, details_json=details)
    for table, seq in HIGH_WATER.items():
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, seq))
    for sql in extra_sql:
        conn.execute(sql)
    conn.commit()
    conn.execute(f"PRAGMA user_version = {pg_schema.PG_SCHEMA_VERSION}")
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.close()
    return path, _sha256(path.read_bytes())


def _upload_root(directory: Path) -> Path:
    root = directory / "source_uploads"
    (root / "pathb_docs").mkdir(parents=True)
    (root / ASSET_RELATIVE).write_bytes(ASSET_BYTES)
    return root


# ---------------------------------------------------------------------------
# A. static / refusal nodes
# ---------------------------------------------------------------------------


def test_policy_manifest_covers_every_table_exactly_once():
    assert pathb.policy_manifest_problems() == []
    source = set(pathb.SOURCE_TABLE_POLICIES)
    assert source == set(pg_schema.PG_APPLICATION_TABLES) | {"sqlite_sequence"}
    assert set(pathb.TARGET_ONLY_TABLE_POLICIES) == set(pg_schema.PG_SCHEMA_TABLES) - set(
        pg_schema.PG_APPLICATION_TABLES
    )
    excluded = {t for t, p in pathb.SOURCE_TABLE_POLICIES.items() if p.policy != pathb.MIGRATE_EXACT}
    assert excluded == {
        "schema_migrations", "senha_tokens", "configuracoes_backup", "cloud_accounts",
        "backup_logs", "cloud_drive_settings", "sqlite_sequence",
    }


def test_load_order_puts_every_parent_first():
    order = pathb.load_order()
    assert sorted(order) == sorted(pg_schema.PG_APPLICATION_TABLES)
    for table in order:
        for fk in pg_schema.PG_TABLE_SPECS[table]["foreign_keys"]:
            if fk["references_table"] != table:
                assert order.index(fk["references_table"]) < order.index(table), (table, fk["name"])
    assert pathb.self_reference_columns("atividade_versao") == ("versao_anterior_id",)


def _refusal(code, *args, **kwargs):
    with pytest.raises(pathb.MigrationRefused) as caught:
        pathb.migrate(*args, **kwargs)
    assert caught.value.code == code, str(caught.value)


def test_source_refusals_happen_before_any_connection(tmp_path, monkeypatch):
    source, digest = build_synthetic_source(tmp_path)
    before = source.read_bytes()
    monkeypatch.setenv("DATABASE_URL", UNUSED_PG_URL)
    _refusal("SOURCE_HASH_MISMATCH", source, "0" * 64)
    _refusal("SOURCE_HASH_REQUIRED", source, "")
    _refusal("SOURCE_MISSING", tmp_path / "absent.db", digest)
    wal = Path(str(source) + "-wal")
    wal.write_bytes(b"x")
    _refusal("SOURCE_NOT_FROZEN", source, digest)
    wal.unlink()
    monkeypatch.setenv("APP_DATABASE", str(source))
    _refusal("SOURCE_IS_RUNTIME_DATABASE", source, digest)
    assert source.read_bytes() == before


def test_unsupported_source_schema_and_assets_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", UNUSED_PG_URL)
    (tmp_path / "a").mkdir()
    source, digest = build_synthetic_source(tmp_path / "a", extra_sql=["CREATE TABLE stray (id INTEGER)"])
    _refusal("SOURCE_SCHEMA_UNSUPPORTED", source, digest)
    for label, sql in (
        ("b", "UPDATE usuarios SET foto_perfil = 'fotos/x.png' WHERE id = 7"),
        ("b2", "UPDATE alunos SET foto_perfil = 'aluno_11 - x/perfil/x.png' WHERE id = 11"),
        ("b3", "UPDATE reportes SET screenshot_filename = 'aluno_11 - x/reportes/x.png' WHERE id = 4"),
    ):
        (tmp_path / label).mkdir()
        source, digest = build_synthetic_source(tmp_path / label, extra_sql=[sql])
        _refusal("UNSUPPORTED_LOCAL_ASSET", source, digest)
    (tmp_path / "c").mkdir()
    source, digest = build_synthetic_source(tmp_path / "c")
    _refusal("ASSET_ROOTS_REQUIRED", source, digest)
    _refusal("ASSET_MISSING", source, digest, source_upload_root=tmp_path / "empty", target_upload_root=tmp_path / "t")


def test_target_must_be_postgresql_from_environment(tmp_path, monkeypatch, capsys):
    source, digest = build_synthetic_source(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _refusal("TARGET_REQUIRED", source, digest)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'target.db'}")
    _refusal("TARGET_NOT_POSTGRESQL", source, digest)
    assert not (tmp_path / "target.db").exists()
    # No option carries a database URL or a password.
    for flag in ("--database-url", "--password", "--force"):
        assert pathb.main(["--source", str(source), "--expected-source-sha256", digest, flag, "x"]) == 2
    assert pathb.main(["--source", str(source)]) == 2
    capsys.readouterr()


# ---------------------------------------------------------------------------
# A2. local file staging / promotion (no PostgreSQL)
# ---------------------------------------------------------------------------


def _asset_case(tmp_path):
    """One ``local_legacy`` admin file planned from a minimal snapshot."""
    source_root = _upload_root(tmp_path)
    target_root = tmp_path / "target_uploads"
    columns = pathb._columns("admin_arquivos")
    row = [None] * len(columns)
    for name, value in (("id", 4), ("filename", ASSET_RELATIVE), ("provider", "local_legacy"),
                        ("storage_status", "legacy_active")):
        row[columns.index(name)] = value
    snapshot = pathb.SourceSnapshot(tmp_path / "unused.db", 0, "", 0, 12, rows={"admin_arquivos": [tuple(row)]})
    final = target_root / ASSET_RELATIVE
    return snapshot, source_root, target_root, final, pathb.staging_path(final)


def test_asset_copy_stages_verifies_then_promotes_and_rerun_reuses_it(tmp_path):
    snapshot, source_root, target_root, final, staging = _asset_case(tmp_path)
    assert staging.name == "manual.pdf.sgaa-pathb-staging" and staging.parent == final.parent
    [asset] = pathb.plan_local_assets(snapshot, source_root, target_root)
    pathb._AssetWriter(source_root, target_root).write(asset)
    assert asset.status == "copied"
    assert final.read_bytes() == ASSET_BYTES
    assert not staging.exists()
    # Rerun after a kill between promotion and COMMIT: the identical final file is reused.
    [again] = pathb.plan_local_assets(snapshot, source_root, target_root)
    assert again.status == "present_identical"
    pathb._AssetWriter(source_root, target_root).write(again)
    assert final.read_bytes() == ASSET_BYTES and not staging.exists()


def test_asset_failure_before_promotion_never_leaves_a_final_file(tmp_path, monkeypatch):
    snapshot, source_root, target_root, final, staging = _asset_case(tmp_path)
    [asset] = pathb.plan_local_assets(snapshot, source_root, target_root)
    seen = {}

    def fsync_fails(fd):
        # Crash point: every byte is in the staging file, nothing is promoted.
        seen["staging_bytes"] = staging.read_bytes() if staging.exists() else None
        seen["final_exists"] = final.exists()
        raise OSError("simulated device failure")

    monkeypatch.setattr(pathb.os, "fsync", fsync_fails)
    writer = pathb._AssetWriter(source_root, target_root)
    with pytest.raises(OSError):
        writer.write(asset)
    monkeypatch.undo()
    assert seen == {"staging_bytes": ASSET_BYTES, "final_exists": False}
    assert not final.exists() and not staging.exists()
    writer.undo()
    assert not target_root.exists()

    # A source that changes after the preflight is caught before promotion too.
    [asset] = pathb.plan_local_assets(snapshot, source_root, target_root)
    (source_root / ASSET_RELATIVE).write_bytes(ASSET_BYTES + b"changed")
    with pytest.raises(pathb.MigrationFailed) as caught:
        pathb._AssetWriter(source_root, target_root).write(asset)
    assert caught.value.code == "ASSET_SOURCE_CHANGED"
    assert not final.exists() and not staging.exists()


def test_asset_promotion_never_replaces_a_different_final_file(tmp_path):
    snapshot, source_root, target_root, final, staging = _asset_case(tmp_path)
    [asset] = pathb.plan_local_assets(snapshot, source_root, target_root)
    # A different file takes the final name after the preflight.
    final.parent.mkdir(parents=True)
    final.write_bytes(b"other")
    with pytest.raises(pathb.MigrationFailed) as caught:
        pathb._AssetWriter(source_root, target_root).write(asset)
    assert caught.value.code == "ASSET_DESTINATION_CONFLICT"
    assert final.read_bytes() == b"other"
    assert not staging.exists()


_HARD_KILL_SCRIPT = """
import os, sys
from pathlib import Path
from app import pg_migrate_from_sqlite as pathb

source_root, target_root, relative, size, sha256 = sys.argv[1:6]

def killed(fd):
    os._exit(9)  # no except/finally/atexit runs: a hard kill before promotion

pathb.os.fsync = killed
asset = pathb.LocalAsset("admin_arquivos", 4, relative, int(size), sha256, True)
pathb._AssetWriter(Path(source_root), Path(target_root)).write(asset)
os._exit(0)
"""


def test_hard_kill_leaves_only_a_recognised_staging_file_and_rerun_is_deterministic(tmp_path):
    snapshot, source_root, target_root, final, staging = _asset_case(tmp_path)
    [asset] = pathb.plan_local_assets(snapshot, source_root, target_root)
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    environment.pop("DATABASE_URL", None)
    killed = subprocess.run(
        [sys.executable, "-c", _HARD_KILL_SCRIPT, str(source_root), str(target_root),
         asset.relative_path, str(asset.size), asset.sha256],
        cwd=str(pathb.PROJECT_ROOT), env=environment, capture_output=True, timeout=120,
    )
    assert killed.returncode == 9, killed.stderr.decode("utf-8", "replace")[-2000:]
    assert not final.exists()
    assert staging.is_file()

    # The rerun preflight refuses the leftover explicitly and never deletes it.
    with pytest.raises(pathb.MigrationRefused) as caught:
        pathb.plan_local_assets(snapshot, source_root, target_root)
    assert caught.value.code == "ASSET_STAGING_LEFTOVER"
    assert "admin_arquivos id=4" in str(caught.value)
    assert staging.is_file() and not final.exists()
    # A stale staging file that appears after the preflight is refused, not reused.
    staging.unlink()
    [asset] = pathb.plan_local_assets(snapshot, source_root, target_root)
    staging.write_bytes(b"%PDF-")
    with pytest.raises(pathb.MigrationFailed) as late:
        pathb._AssetWriter(source_root, target_root).write(asset)
    assert late.value.code == "ASSET_STAGING_LEFTOVER"
    assert staging.read_bytes() == b"%PDF-" and not final.exists()
    # Operator removes the recognised staging file: the rerun copies normally.
    staging.unlink()
    [asset] = pathb.plan_local_assets(snapshot, source_root, target_root)
    pathb._AssetWriter(source_root, target_root).write(asset)
    assert final.read_bytes() == ASSET_BYTES and not staging.exists()


# ---------------------------------------------------------------------------
# real PostgreSQL harness
# ---------------------------------------------------------------------------


def _database_url(database):
    parts = urlsplit(PG_URL)
    return urlunsplit(
        (parts.scheme, parts.netloc, "/" + database, f"connect_timeout={CONNECT_TIMEOUT_SECONDS}", "")
    )


def _raw_connect(url, *, autocommit=False):
    import psycopg

    return psycopg.connect(url, prepare_threshold=None, autocommit=autocommit, connect_timeout=CONNECT_TIMEOUT_SECONDS)


class _RunDatabaseRegistry:
    """Sole creator and destroyer of this run's disposable databases."""

    def __init__(self):
        self._admin = None
        self._owned = set()

    def admin(self):
        if self._admin is None or self._admin.closed:
            self._admin = _raw_connect(PG_URL, autocommit=True)
        return self._admin

    def create(self, label, *, template=None):
        database = f"{RUN_PREFIX}{label}_{secrets.token_hex(4)}"
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
        for database in sorted(self._owned, key=lambda name: "_template_" in name):
            try:
                self.drop(database)
            except Exception as exc:  # pragma: no cover - teardown reporting
                failures.append((database, repr(exc)))
        leftovers = self.leftovers() if not failures else []
        if self._admin is not None and not self._admin.closed:
            self._admin.close()
        assert not failures, f"could not drop run-owned databases: {failures!r}"
        assert not leftovers, f"run-owned databases left behind: {leftovers!r}"


@pytest.fixture(scope="module")
def registry():
    psycopg = pytest.importorskip("psycopg")
    registry = _RunDatabaseRegistry()
    try:
        try:
            registry.admin()
        except psycopg.Error as exc:
            pytest.skip(f"SGAA_PG_TEST_URL is not a usable PostgreSQL connection: {exc}")
        template, url = registry.create("template")
        connection = _raw_connect(url)
        try:
            assert pg_schema.provision_pg_schema(connection)["status"] == "provisioned"
            connection.commit()
        finally:
            connection.close()
        registry.template = template
        yield registry
    finally:
        registry.close()


@pytest.fixture
def target(registry, request, monkeypatch):
    """A freshly provisioned clone named by DATABASE_URL, plus an observer."""
    database, url = registry.create(request.node.name[5:17].strip("_[").lower(), template=registry.template)
    monkeypatch.setenv("DATABASE_URL", url)
    observer = _raw_connect(url, autocommit=True)
    try:
        yield database, url, observer
    finally:
        observer.close()
        registry.drop(database)


def _counts(observer):
    return {
        table: observer.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in pg_schema.PG_APPLICATION_TABLES
    }


def _identity_states(observer):
    return {
        table: pathb.read_identity_state(observer, table)
        for table in pg_schema.PG_APPLICATION_TABLES
        if pathb._identity_column(table)
    }


def _assert_untouched(observer, provisioned_identities):
    counts = _counts(observer)
    assert counts.pop("schema_migrations") == len(pg_schema.PG_SCHEMA_MIGRATIONS_SEED)
    assert set(counts.values()) == {0}, counts
    assert _identity_states(observer) == provisioned_identities


# ---------------------------------------------------------------------------
# B. synthetic real-PostgreSQL nodes
# ---------------------------------------------------------------------------


@needs_pg
def test_synthetic_migration_preserves_ids_lineage_and_high_water(tmp_path, target, capsys):
    database, url, observer = target
    source, digest = build_synthetic_source(tmp_path)
    upload_root, asset_root = _upload_root(tmp_path), tmp_path / "target_uploads"
    provisioned = _identity_states(observer)
    argv = ["--source", str(source), "--expected-source-sha256", digest,
            "--source-upload-root", str(upload_root), "--target-upload-root", str(asset_root)]

    # Dry run: verified, nothing written.
    assert pathb.main(argv) == 0
    out = capsys.readouterr().out
    assert "result: DRY RUN" in out and f"database={database}" in out
    _assert_untouched(observer, provisioned)
    assert not asset_root.exists()

    assert pathb.main(argv + ["--apply"]) == 0
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "result: MIGRATED" in out and "verified_after=yes" in out
    for secret in (ADMIN_EMAIL, STUDENT_EMAIL, "pbkdf2", "pathb-synthetic-secret", "synthetic-profile-default",
                   "C:/synthetic", "remote-file", PG_URL, url, BLOB_MARKER.decode(), BLOB_MARKER.hex()):
        assert secret not in out
    assert out.index("target: backend=postgresql") < out.index("copied:")
    assert "prerequisite: GOOGLE_DRIVE_RECONNECT_REQUIRED" in out
    assert "excluded: cloud_accounts rows=1 policy=RECREATE_TARGET_SIDE reasons=SCRUBBED_SECRET,REQUIRES_EXTERNAL_RECONNECT" in out
    assert "note: 1 unexpired password link(s) dropped" in out

    # Explicit sparse ids and the forward self-reference survive.
    assert [r[0] for r in observer.execute("SELECT id FROM usuarios ORDER BY id")] == [3, 7]
    lineage = dict(observer.execute("SELECT id, versao_anterior_id FROM atividade_versao").fetchall())
    assert lineage == {12: 70, 30: None, 45: 30, 50: None, 70: None}
    # Excluded and scrubbed tables are empty; the provisioner seed is intact.
    for table in ("cloud_accounts", "configuracoes_backup", "cloud_drive_settings", "senha_tokens", "backup_logs"):
        assert observer.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert observer.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 13
    # v13 image rows arrive byte for byte; no local file is involved.
    for table, (owner_column, owner_id, mime_type, content) in IMAGE_ROWS.items():
        row = observer.execute(
            f"SELECT {owner_column}, mime_type, size_bytes, sha256, conteudo FROM {table}"
        ).fetchall()
        assert len(row) == 1 and tuple(row[0][:4]) == (owner_id, mime_type, len(content), _sha256(content)), table
        assert bytes(row[0][4]) == content, table
    # Every exact table equals the source, row by row.
    source_conn = pathb.open_source_readonly(source)
    try:
        for table in pathb.migrated_tables():
            columns = ", ".join(pathb._columns(table))
            assert pathb.normalize_rows(table, source_conn.execute(f"SELECT {columns} FROM {table}").fetchall()) == \
                pathb.normalize_rows(table, observer.execute(f"SELECT {columns} FROM {table}").fetchall()), table
    finally:
        source_conn.close()
    # Identity: next value is above the sqlite_sequence high-water, not max(id).
    for table, high_water in HIGH_WATER.items():
        assert pathb.next_identity_value(observer, table) == high_water + 1, table
    assert pathb.next_identity_value(observer, "backup_logs") == 1
    new_id = observer.execute(
        "INSERT INTO admin_alertas (mensagem) VALUES ('nova') RETURNING id"
    ).fetchone()[0]
    assert new_id == HIGH_WATER["admin_alertas"] + 1
    # The local file was copied byte-exactly to the target root; no staging left.
    assert (asset_root / ASSET_RELATIVE).read_bytes() == ASSET_BYTES
    assert not pathb.staging_path(asset_root / ASSET_RELATIVE).exists()
    assert set(pathb.run_domain_checks(observer).values()) == {0}
    # The source was only read.
    assert _sha256(source.read_bytes()) == digest

    # A second run refuses the now non-empty target; there is no --force.
    assert pathb.main(argv + ["--apply"]) == 1
    assert "TARGET_NOT_EMPTY" in capsys.readouterr().err


def test_binary_values_normalize_to_length_and_digest_only():
    content = b"\x89PNG" + BLOB_MARKER
    normalized = pathb.normalize_value(content, "bytea")
    assert normalized == ("bytea", len(content), _sha256(content))
    assert pathb.normalize_value(memoryview(content), "bytea") == normalized
    with pytest.raises(TypeError) as caught:
        pathb.normalize_value(content.decode("latin-1"), "bytea")
    assert str(caught.value) == "bytea"
    # A one-byte difference is a value mismatch reported without any byte.
    table = "alunos_foto"
    columns = pathb._columns(table)
    row = [None] * len(columns)
    for name, value in (("aluno_id", 11), ("mime_type", "image/png"), ("size_bytes", len(content)),
                        ("sha256", _sha256(content)), ("width", 1), ("height", 1), ("conteudo", content),
                        ("atualizado_em", TS)):
        row[columns.index(name)] = value
    other = list(row)
    other[columns.index("conteudo")] = content[:-1] + b"X"
    source = pathb.normalize_rows(table, [tuple(row)])
    target = pathb.normalize_rows(table, [tuple(other)])
    [mismatch] = pathb.compare_rows(table, source, target)
    assert (mismatch.table, mismatch.primary_key, mismatch.column, mismatch.category) == (
        table, (11,), "conteudo", "VALUE_DIFFERS"
    )
    assert pathb.table_digest(table, source) != pathb.table_digest(table, target)
    for text in (repr(mismatch), repr(source), pathb.table_digest(table, source)):
        assert BLOB_MARKER.decode() not in text and BLOB_MARKER.hex() not in text


@needs_pg
def test_binary_corruption_during_load_is_detected_value_free_and_rolled_back(
    tmp_path, target, monkeypatch, capsys
):
    database, url, observer = target
    source, digest = build_synthetic_source(tmp_path)
    upload_root, asset_root = _upload_root(tmp_path), tmp_path / "target_uploads"
    provisioned = _identity_states(observer)
    original = pathb._to_parameter

    def corrupt(value, pg_type):
        value = original(value, pg_type)
        if pg_type == "bytea" and value == IMAGE_ROWS["alunos_foto"][3]:
            return value[:-1] + bytes([value[-1] ^ 0xFF])  # same length: passes every constraint
        return value

    monkeypatch.setattr(pathb, "_to_parameter", corrupt)
    code = pathb.main(["--source", str(source), "--expected-source-sha256", digest,
                       "--source-upload-root", str(upload_root), "--target-upload-root", str(asset_root),
                       "--apply"])
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert code == 1
    assert "mismatch table=alunos_foto key=(11,) column=conteudo category=VALUE_DIFFERS" in out
    assert "VALUE_VALIDATION_FAILED" in out
    assert BLOB_MARKER.decode() not in out and BLOB_MARKER.hex() not in out
    _assert_untouched(observer, provisioned)
    assert not asset_root.exists()
    assert _sha256(source.read_bytes()) == digest


@needs_pg
def test_target_rejection_after_writes_rolls_back_everything(tmp_path, target):
    """``2**31`` is a valid SQLite INTEGER but out of range for PG ``integer``."""
    database, url, observer = target
    source, digest = build_synthetic_source(tmp_path, tentativas=2**31)
    upload_root, asset_root = _upload_root(tmp_path), tmp_path / "target_uploads"
    provisioned = _identity_states(observer)
    with pytest.raises(pathb.MigrationFailed) as caught:
        pathb.migrate(source, digest, source_upload_root=upload_root, target_upload_root=asset_root, apply=True)
    assert caught.value.code == "TARGET_REJECTED_DATA"
    assert "sqlstate=22003" in str(caught.value)
    # email_envios loads after usuarios..admin_alertas: all of it rolled back.
    _assert_untouched(observer, provisioned)
    assert not asset_root.exists()
    assert _sha256(source.read_bytes()) == digest


@needs_pg
def test_validation_failure_rolls_back_rows_sequences_and_files(tmp_path, target, monkeypatch):
    database, url, observer = target
    source, digest = build_synthetic_source(tmp_path)
    upload_root, asset_root = _upload_root(tmp_path), tmp_path / "target_uploads"
    provisioned = _identity_states(observer)

    # Failpoint after every write and every identity restart.
    monkeypatch.setitem(pathb.DOMAIN_CHECKS, "test_failpoint", "SELECT 1")
    with pytest.raises(pathb.MigrationFailed) as caught:
        pathb.migrate(source, digest, source_upload_root=upload_root, target_upload_root=asset_root, apply=True)
    assert caught.value.code == "DOMAIN_VALIDATION_FAILED"
    _assert_untouched(observer, provisioned)
    monkeypatch.delitem(pathb.DOMAIN_CHECKS, "test_failpoint")

    # Failpoint after the file was written: the file and its new directories go too.
    original_write = pathb._AssetWriter.write

    def write_then_fail(self, asset):
        original_write(self, asset)
        assert (asset_root / ASSET_RELATIVE).is_file()
        raise pathb.MigrationFailed("TEST_FAILPOINT")

    monkeypatch.setattr(pathb._AssetWriter, "write", write_then_fail)
    with pytest.raises(pathb.MigrationFailed):
        pathb.migrate(source, digest, source_upload_root=upload_root, target_upload_root=asset_root, apply=True)
    _assert_untouched(observer, provisioned)
    assert not asset_root.exists()
    monkeypatch.setattr(pathb._AssetWriter, "write", original_write)

    # A different file at the destination is never overwritten.
    (asset_root / "pathb_docs").mkdir(parents=True)
    (asset_root / ASSET_RELATIVE).write_bytes(b"other")
    with pytest.raises(pathb.MigrationRefused) as refused:
        pathb.migrate(source, digest, source_upload_root=upload_root, target_upload_root=asset_root, apply=True)
    assert refused.value.code == "ASSET_DESTINATION_CONFLICT"
    assert (asset_root / ASSET_RELATIVE).read_bytes() == b"other"
    _assert_untouched(observer, provisioned)

    # The rolled-back target is still a valid fresh target.
    (asset_root / ASSET_RELATIVE).unlink()
    report = pathb.migrate(source, digest, source_upload_root=upload_root, target_upload_root=asset_root, apply=True)
    assert report.applied and report.source_hash_verified_after


@needs_pg
def test_unprovisioned_target_is_refused(tmp_path, registry, monkeypatch):
    database, url = registry.create("bare")
    try:
        monkeypatch.setenv("DATABASE_URL", url)
        source, digest = build_synthetic_source(tmp_path)
        with pytest.raises(pathb.MigrationRefused) as caught:
            pathb.migrate(source, digest, source_upload_root=_upload_root(tmp_path),
                          target_upload_root=tmp_path / "t", apply=True)
        assert caught.value.code == "TARGET_SCHEMA_NOT_CURRENT"
    finally:
        registry.drop(database)


class _CommitFault:
    """The real target connection; only ``commit()`` runs a test-only fault."""

    def __init__(self, connection, fault):
        self._connection = connection
        self._fault = fault

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def commit(self):
        self._fault(self._connection)


def _inject_commit_fault(monkeypatch, fault):
    real_connect = pathb.connect_target
    monkeypatch.setattr(pathb, "connect_target", lambda url: _CommitFault(real_connect(url), fault))
    return real_connect


def _cli_argv(source, digest, upload_root, asset_root):
    return ["--source", str(source), "--expected-source-sha256", digest, "--source-upload-root",
            str(upload_root), "--target-upload-root", str(asset_root), "--apply"]


@needs_pg
def test_commit_lost_before_the_server_keeps_files_and_rerun_reuses_them(tmp_path, target, monkeypatch, capsys):
    import psycopg

    database, url, observer = target
    source, digest = build_synthetic_source(tmp_path)
    upload_root, asset_root = _upload_root(tmp_path), tmp_path / "target_uploads"
    final = asset_root / ASSET_RELATIVE
    provisioned = _identity_states(observer)

    def lost_before_server(connection):
        connection.rollback()  # the server never committed
        raise psycopg.OperationalError("simulated: connection lost while committing")

    real_connect = _inject_commit_fault(monkeypatch, lost_before_server)
    assert pathb.main(_cli_argv(source, digest, upload_root, asset_root)) == pathb.EXIT_COMMIT_UNCERTAIN
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "COMMIT OUTCOME UNCERTAIN" in out and "COMMIT_OUTCOME_UNCERTAIN" in out
    assert "FAILED and rolled back" not in out and "result: MIGRATED" not in out
    # The copied file is kept, not undone; the target is still fresh.
    assert final.read_bytes() == ASSET_BYTES and not pathb.staging_path(final).exists()
    _assert_untouched(observer, provisioned)

    # Rerun: the empty target migrates and the identical copied file is reused.
    monkeypatch.setattr(pathb, "connect_target", real_connect)
    report = pathb.migrate(source, digest, source_upload_root=upload_root, target_upload_root=asset_root, apply=True)
    assert report.applied and report.source_hash_verified_after
    assert [asset.status for asset in report.assets] == ["present_identical"]
    assert final.read_bytes() == ASSET_BYTES


@needs_pg
def test_interrupt_after_server_commit_keeps_files_and_rerun_is_refused(tmp_path, target, monkeypatch, capsys):
    database, url, observer = target
    source, digest = build_synthetic_source(tmp_path)
    upload_root, asset_root = _upload_root(tmp_path), tmp_path / "target_uploads"
    final = asset_root / ASSET_RELATIVE

    def interrupted_after_server_commit(connection):
        connection.commit()  # the server committed; the client never learns it
        raise KeyboardInterrupt

    real_connect = _inject_commit_fault(monkeypatch, interrupted_after_server_commit)
    with pytest.raises(pathb.MigrationCommitUncertain) as caught:
        pathb.migrate(source, digest, source_upload_root=upload_root, target_upload_root=asset_root, apply=True)
    assert caught.value.code == "COMMIT_OUTCOME_UNCERTAIN"
    assert isinstance(caught.value.__cause__, KeyboardInterrupt)
    assert not isinstance(caught.value, pathb.MigrationFailed)
    # DB committed and the durable asset is still there: no destructive undo.
    assert observer.execute("SELECT count(*) FROM usuarios").fetchone()[0] == 2
    assert final.read_bytes() == ASSET_BYTES and not pathb.staging_path(final).exists()

    # Rerun: the committed target is refused as non-empty; the file is untouched.
    monkeypatch.setattr(pathb, "connect_target", real_connect)
    assert pathb.main(_cli_argv(source, digest, upload_root, asset_root)) == 1
    assert "TARGET_NOT_EMPTY" in capsys.readouterr().err
    assert final.read_bytes() == ASSET_BYTES


@needs_pg
def test_source_divergence_after_commit_is_nonzero_and_not_rolled_back(tmp_path, target, monkeypatch, capsys):
    database, url, observer = target
    source, digest = build_synthetic_source(tmp_path)
    upload_root, asset_root = _upload_root(tmp_path), tmp_path / "target_uploads"

    def commit_then_source_changes(connection):
        connection.commit()
        with open(source, "ab") as handle:  # an outside writer touches the copy
            handle.write(b"\0")

    _inject_commit_fault(monkeypatch, commit_then_source_changes)
    code = pathb.main(_cli_argv(source, digest, upload_root, asset_root))
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert code == pathb.EXIT_COMMITTED_SOURCE_UNVERIFIED
    assert "verified_after=NO" in out
    assert "result: COMMITTED_SOURCE_UNVERIFIED" in out and "the target commit completed" in out
    assert "result: MIGRATED" not in out and "FAILED and rolled back" not in out
    # The committed target and its file are left in place for investigation.
    assert observer.execute("SELECT count(*) FROM usuarios").fetchone()[0] == 2
    assert (asset_root / ASSET_RELATIVE).read_bytes() == ASSET_BYTES


# ---------------------------------------------------------------------------
# C. actual-source rehearsal (opt-in)
# ---------------------------------------------------------------------------


class _Prompt:
    def __init__(self, *answers):
        self.answers = list(answers)

    def __call__(self, text):
        return self.answers.pop(0)


@needs_pg
@pytest.mark.skipif(
    not (REHEARSAL_SOURCE and REHEARSAL_SHA256 and REHEARSAL_UPLOAD_ROOT),
    reason="SGAA_PATHB_SOURCE / _SHA256 / _UPLOAD_ROOT not set -- actual-source rehearsal not requested",
)
def test_actual_source_rehearsal_cutover_chain(tmp_path, target, monkeypatch, capsys):
    """PROVISION -> MIGRATE -> VALIDATE -> ACTIVATE ADMIN -> LOGIN."""
    import main
    from app import admin_bootstrap
    from app import db as app_db
    from app.security.passwords import check_password

    database, url, observer = target
    source = Path(REHEARSAL_SOURCE)
    asset_root = tmp_path / "rehearsal_assets"
    evidence = []

    # MIGRATE (through the CLI).
    code = pathb.main(["--source", str(source), "--expected-source-sha256", REHEARSAL_SHA256,
                       "--source-upload-root", REHEARSAL_UPLOAD_ROOT,
                       "--target-upload-root", str(asset_root), "--apply"])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert code == 0, captured.err
    # Booleans only: a failing assertion must never render personal or secret values.
    clean = "@" not in output and "pbkdf2" not in output and url not in output
    assert clean
    evidence += [line for line in captured.out.splitlines()]

    # VALIDATE independently: re-read the frozen copy and the target.
    source_conn = pathb.open_source_readonly(source)
    try:
        source_rows = {
            table: source_conn.execute(
                f"SELECT {', '.join(pathb._columns(table))} FROM {table}"
            ).fetchall()
            for table in pg_schema.PG_APPLICATION_TABLES
        }
        source_sequences = dict(source_conn.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
    finally:
        source_conn.close()
    pg_schema.validate_pg_schema(observer)
    counts = _counts(observer)
    for table in pg_schema.PG_APPLICATION_TABLES:
        policy = pathb.SOURCE_TABLE_POLICIES[table].policy
        if policy == pathb.MIGRATE_EXACT:
            columns = ", ".join(pathb._columns(table))
            expected = pathb.normalize_rows(table, source_rows[table])
            actual = pathb.normalize_rows(table, observer.execute(f"SELECT {columns} FROM {table}").fetchall())
            # Count only: assertion introspection must never render row keys or values.
            differences = len(pathb.compare_rows(table, expected, actual))
            assert differences == 0, table
            evidence.append(
                f"independent: {table} source={len(expected)} target={counts[table]} "
                f"sha256={pathb.table_digest(table, actual)}"
            )
        elif table == "schema_migrations":
            assert counts[table] == len(pg_schema.PG_SCHEMA_MIGRATIONS_SEED)
        else:
            assert counts[table] == 0, table
            evidence.append(f"independent: {table} source={len(source_rows[table])} target=0 ({policy})")
    for table in pg_schema.PG_APPLICATION_TABLES:
        column = pathb._identity_column(table)
        if not column:
            continue
        ids = [row[pathb._columns(table).index(column)] for row in source_rows[table]]
        floor = source_sequences.get(table, 0)
        if pathb.SOURCE_TABLE_POLICIES[table].policy == pathb.MIGRATE_EXACT and ids:
            floor = max(floor, max(ids))
        last_value, is_called = pathb.read_identity_state(observer, table)
        assert (last_value, is_called) == ((floor + 1, False) if floor else (1, False)), table
        evidence.append(f"identity: {table} sqlite_sequence={source_sequences.get(table, '-')} "
                        f"max_id={max(ids) if ids else '-'} next={floor + 1 if floor else 1}")
    domain = pathb.run_domain_checks(observer)
    assert set(domain.values()) == {0}, domain
    evidence.append(f"domain checks: {len(domain)} run, all zero")

    # Drive-backed request files keep their non-secret references.
    drive = observer.execute(
        "SELECT count(*) FROM requisicao_arquivos WHERE provider='google' AND storage_status='active' "
        "AND remote_file_id IS NOT NULL AND remote_parent_id IS NOT NULL AND sha256 IS NOT NULL"
    ).fetchone()[0]
    evidence.append(f"drive files with references preserved: {drive}; google accounts on target: "
                    f"{observer.execute('SELECT count(*) FROM cloud_accounts').fetchone()[0]}")

    # ACTIVATE ADMIN through the R5 CLI.
    monkeypatch.setattr(app_db, "DATABASE_URL", url)
    monkeypatch.setitem(main.app.config, "TESTING", True)
    monkeypatch.setitem(main.app.config, "UPLOAD_FOLDER", str(asset_root))
    candidates = observer.execute(
        "SELECT u.id, u.email FROM usuarios u JOIN usuario_credenciais c ON c.usuario_id = u.id "
        "WHERE u.tipo='admin' AND u.nivel_acesso='admin_total' AND c.estado='pending' AND c.acesso_ativo=1"
    ).fetchall()
    pending_full_admins = len(candidates)
    assert pending_full_admins == 1
    admin_id, admin_email = candidates[0]
    users_before = counts["usuarios"]
    admins_before = observer.execute("SELECT count(*) FROM usuarios WHERE tipo='admin'").fetchone()[0]
    password = secrets.token_urlsafe(24)
    try:
        code = admin_bootstrap.main(["--email", admin_email], prompt=_Prompt(password, password))
        captured = capsys.readouterr()
        succeeded = code == 0
        assert succeeded
        leaked = password in captured.out + captured.err
        assert not leaked
        row = observer.execute(
            "SELECT u.senha, c.estado, c.acesso_ativo FROM usuarios u JOIN usuario_credenciais c "
            "ON c.usuario_id = u.id WHERE u.id = %s", (admin_id,)
        ).fetchone()
        activated = row[1] == "personal" and row[2] == 1 and check_password(row[0], password)
        assert activated
        assert observer.execute("SELECT count(*) FROM usuarios").fetchone()[0] == users_before
        assert observer.execute("SELECT count(*) FROM usuarios WHERE tipo='admin'").fetchone()[0] == admins_before
        evidence.append(f"R5: activated pending full admin in place (same usuarios.id), "
                        f"users {users_before}->{users_before}, admins {admins_before}->{admins_before}")

        # LOGIN through the production route; reach a full-admin-only page.
        client = main.app.test_client()
        response = client.post("/login", data={"email": admin_email, "senha": password})
        assert response.status_code == 302, response.status_code
        assert client.get("/admin/acesso").status_code == 200
        evidence.append("login: POST /login 302, GET /admin/acesso 200")
        for (asset_id,) in observer.execute(
            "SELECT id FROM admin_arquivos WHERE provider='local_legacy' ORDER BY id"
        ).fetchall():
            page = client.get(f"/admin/arquivos/{asset_id}/visualizar")
            assert page.status_code == 200, page.status_code
            evidence.append(f"asset served from rehearsal root: admin_arquivos id={asset_id} "
                            f"bytes={len(page.data)} sha256={_sha256(page.data)}")
    finally:
        with main.app.app_context():
            app_db.close_db_connection(None)
        del password

    assert _sha256(source.read_bytes()) == REHEARSAL_SHA256.lower()
    with capsys.disabled():
        print("\n=== PATH-B REHEARSAL EVIDENCE ===")
        for line in evidence:
            print(line)
