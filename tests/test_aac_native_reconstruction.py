from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tools import aac_native_reconstruction as reconstruction


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "aac_native_reconstruction.py"
ACTIVE_DATABASE = ROOT / "database.db"
APPROVED_MANIFEST = Path(
    r"C:\Users\klebe\OneDrive\Programação\SGAA_DATA_RECONSTRUCTION"
    r"\20260823T182211Z\aac_reconstruction_manifest_final.json"
)


def _version(*, group: str = "1 - Atividades fora da Faculdade") -> dict[str, object]:
    return {
        "norma_ref": "AAC-rev6",
        "codigo_normativo": "AAC-rev6",
        "eixo": "AAC",
        "grupo": group,
        "ch_por_evento": None,
        "limite_semestre": None,
        "limite_total": None,
        "observacao_aluno": "Canonical student-facing rule.",
        "observacao_admin": "Canonical administrative rule.",
        "documentos_json": None,
        "vigencia_inicio": None,
        "vigencia_fim": None,
        "numero_versao": 1,
        "status": "ativa",
        "versao_anterior_id": None,
    }


def _activity(index: int, name: str) -> dict[str, object]:
    return {
        "aac_ref": f"AAC-{index:03d}",
        "traceability": {"historical_base_id": index},
        "field_provenance": {
            field: "focused-test-fixture"
            for field in reconstruction.REQUIRED_PROVENANCE_FIELDS
        },
        "rule_semantics": {"calculation_rule": "textual"},
        "atividade_base": {
            "nome_conceito": name,
            "descricao": None,
            "status": "ativo",
        },
        "atividade_versao": _version(),
    }


def _manifest() -> dict[str, object]:
    activities = [_activity(index, f"Atividade canônica {index:02d}") for index in range(1, 26)]
    visitas = _activity(26, reconstruction.SPECIAL_VISITAS)
    visitas["atividade_versao"] = {
        **_version(group="5 - Atividades especiais"),
        "limite_semestre": 20,
        "observacao_aluno": (
            "Cursos coordenados por professores do curso: carga horária efetivamente "
            "comprovada. Visita técnica: 5h por visita. Limite 20h/semestre."
        ),
        "observacao_admin": (
            "Regra condicional: curso usa carga horária real; visita técnica usa 5h por visita."
        ),
    }
    filmes = _activity(27, reconstruction.SPECIAL_FILMES)
    filmes["atividade_versao"] = {
        **_version(group="5 - Atividades especiais"),
        "ch_por_evento": 5,
        "limite_semestre": 50,
    }
    activities.extend((visitas, filmes))
    return {
        "manifest_type": reconstruction.EXPECTED_MANIFEST_TYPE,
        "target_real_aac_count": 27,
        "internal_norma_code": "AAC-rev6",
        "source_document_revision": "ACC-rev7.docx",
        "renumbering_decision": reconstruction.EXPECTED_RENUMBERING_DECISION,
        "git_sha": reconstruction.EXPECTED_GIT_SHA,
        "source": {
            "historical_db_path": (
                "C:\\Users\\klebe\\OneDrive\\Programação\\SGAA_database_backups\\"
                "database.pre-D8.3A-live-baseline-20260620-205155.db"
            ),
            "historical_db_sha256": reconstruction.EXPECTED_SOURCE_SHA256,
        },
        "exclusions": sorted(reconstruction.REQUIRED_EXCLUSION_MARKERS),
        "norma": {
            "codigo": "AAC-rev6",
            "eixo": "AAC",
            "revisao": "rev6",
            "nome": "AAC regulamento novo",
            "descricao": None,
            "status": "ativa",
        },
        "activities": activities,
    }


def _write_manifest(tmp_path: Path, manifest: dict[str, object] | None = None) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(manifest or _manifest(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _approved_manifest() -> Path:
    assert APPROVED_MANIFEST.is_file()
    assert hashlib.sha256(APPROVED_MANIFEST.read_bytes()).hexdigest() == (
        reconstruction.APPROVED_MANIFEST_SHA256
    )
    return APPROVED_MANIFEST


def _bootstrap(tmp_path: Path) -> Path:
    path = tmp_path / "disposable.sqlite3"
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        reconstruction._load_prod1_schema_module().bootstrap_prod1_schema(conn)
    finally:
        conn.close()
    return path


def _bootstrap_wal_mode(tmp_path: Path) -> Path:
    path = tmp_path / "canonical" / "database.db"
    path.parent.mkdir()
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        reconstruction._load_prod1_schema_module().bootstrap_prod1_schema(conn)
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    assert reconstruction._sqlite_sidecars(path) == []
    return path


def _signature(path: Path) -> tuple[int, str]:
    return path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()


def _counts(path: Path) -> tuple[int, int, int]:
    conn = sqlite3.connect(path)
    try:
        return tuple(
            int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("norma_atividade", "atividade_base", "atividade_versao")
        )
    finally:
        conn.close()


def _run_cli(*args: object) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


def test_dry_run_has_exact_plan_and_zero_mutation(tmp_path: Path):
    db_path = _bootstrap(tmp_path)
    manifest_path = _approved_manifest()
    before = _signature(db_path)

    report = reconstruction.reconstruct(db_path, manifest_path, dry_run=True)

    assert report["status"] == "dry_run_ready"
    assert report["planned"] == {
        "normas": 1,
        "atividade_base": 27,
        "atividade_versao": 27,
    }
    assert report["created"] == {
        "normas": 0,
        "atividade_base": 0,
        "atividade_versao": 0,
    }
    assert report["manifest_sha256"] == reconstruction.APPROVED_MANIFEST_SHA256
    assert report["db_pre_sha256"] == before[1]
    assert report["active_authorization_mode"] == "disposable"
    assert report["sidecar_preflight"] == []
    assert _signature(db_path) == before
    assert _counts(db_path) == (0, 0, 0)


def test_manifest_count_must_be_exactly_27():
    manifest = _manifest()
    manifest["activities"] = manifest["activities"][:-1]

    with pytest.raises(reconstruction.ManifestError, match="exactly 27"):
        reconstruction._validate_manifest_data(manifest)


def test_actual_approved_manifest_bytes_and_hash_are_accepted():
    manifest, digest, resolved = reconstruction.load_and_validate_manifest(
        _approved_manifest()
    )

    assert resolved == APPROVED_MANIFEST.resolve()
    assert digest == reconstruction.APPROVED_MANIFEST_SHA256
    assert len(manifest["activities"]) == 27
    assert manifest["norma"]["codigo"] == "AAC-rev6"


def test_structurally_valid_altered_manifest_is_rejected_before_sqlite_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = _bootstrap(tmp_path)
    before_signature = _signature(db_path)
    before_mtime_ns = db_path.stat().st_mtime_ns
    altered = json.loads(_approved_manifest().read_text(encoding="utf-8"))
    altered["activities"][0]["atividade_versao"]["limite_semestre"] = 999
    reconstruction._validate_manifest_data(altered)
    altered_path = _write_manifest(tmp_path, altered)
    altered_sha256 = hashlib.sha256(altered_path.read_bytes()).hexdigest()
    assert altered_sha256 != reconstruction.APPROVED_MANIFEST_SHA256
    sqlite_open_attempted = False

    def unexpected_sqlite_open(*args, **kwargs):
        nonlocal sqlite_open_attempted
        sqlite_open_attempted = True
        raise AssertionError("SQLite must not open for an altered manifest")

    monkeypatch.setattr(reconstruction, "_connect", unexpected_sqlite_open)

    with pytest.raises(
        reconstruction.ManifestIdentityError,
        match="approved manifest SHA-256 mismatch before JSON parse and SQLite open",
    ):
        reconstruction.reconstruct(db_path, altered_path, dry_run=True)
    assert sqlite_open_attempted is False
    assert _signature(db_path) == before_signature
    assert db_path.stat().st_mtime_ns == before_mtime_ns


def test_cli_requires_explicit_database_path(tmp_path: Path):
    result = _run_cli("--manifest", _approved_manifest(), "--dry-run")

    assert result.returncode == 2
    assert "--db" in result.stderr


def test_active_database_guard_runs_before_sqlite_open(tmp_path: Path):
    before = _signature(ACTIVE_DATABASE)

    result = _run_cli(
        "--db",
        ACTIVE_DATABASE,
        "--manifest",
        _approved_manifest(),
        "--dry-run",
        "--report",
        "json",
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error_type"] == "GuardRailError"
    assert _signature(ACTIVE_DATABASE) == before


def test_relative_active_path_is_refused_even_when_it_resolves_to_canonical_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    simulated_active = tmp_path / "database.db"
    simulated_active.write_bytes(b"simulated active custody")
    expected_hash = hashlib.sha256(simulated_active.read_bytes()).hexdigest()
    before_signature = _signature(simulated_active)
    before_mtime_ns = simulated_active.stat().st_mtime_ns
    sqlite_open_attempted = False

    def unexpected_sqlite_open(*args, **kwargs):
        nonlocal sqlite_open_attempted
        sqlite_open_attempted = True
        raise AssertionError("SQLite must not open for a relative active --db path")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(reconstruction, "_connect", unexpected_sqlite_open)

    with pytest.raises(
        reconstruction.GuardRailError,
        match="original --db path to be absolute",
    ):
        reconstruction.reconstruct(
            Path("database.db"),
            _approved_manifest(),
            dry_run=True,
            allow_active_prod1=True,
            expected_active_sha256=expected_hash,
            _canonical_active_database=simulated_active,
        )
    assert sqlite_open_attempted is False
    assert _signature(simulated_active) == before_signature
    assert simulated_active.stat().st_mtime_ns == before_mtime_ns
    assert reconstruction._sqlite_sidecars(simulated_active) == []


def test_simulated_active_target_without_allow_flag_is_refused(tmp_path: Path):
    simulated_active = tmp_path / "canonical" / "database.db"
    simulated_active.parent.mkdir()
    simulated_active.write_bytes(b"simulated active custody")

    with pytest.raises(reconstruction.GuardRailError, match="--allow-active-prod1"):
        reconstruction.authorize_database_target(
            simulated_active,
            _canonical_active_database=simulated_active,
        )


def test_simulated_active_allow_flag_requires_expected_hash(tmp_path: Path):
    simulated_active = tmp_path / "canonical" / "database.db"
    simulated_active.parent.mkdir()
    simulated_active.write_bytes(b"simulated active custody")

    with pytest.raises(reconstruction.GuardRailError, match="--expected-active-sha256"):
        reconstruction.authorize_database_target(
            simulated_active,
            allow_active_prod1=True,
            _canonical_active_database=simulated_active,
        )


def test_simulated_active_rejects_malformed_expected_hash(tmp_path: Path):
    simulated_active = tmp_path / "canonical" / "database.db"
    simulated_active.parent.mkdir()
    simulated_active.write_bytes(b"simulated active custody")

    with pytest.raises(reconstruction.GuardRailError, match="64 hexadecimal"):
        reconstruction.authorize_database_target(
            simulated_active,
            allow_active_prod1=True,
            expected_active_sha256="not-a-sha256",
            _canonical_active_database=simulated_active,
        )


def test_simulated_active_wrong_hash_is_refused_before_sqlite_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    simulated_active = tmp_path / "canonical" / "database.db"
    simulated_active.parent.mkdir()
    simulated_active.write_bytes(b"simulated active custody")
    sqlite_open_attempted = False

    def unexpected_sqlite_open(*args, **kwargs):
        nonlocal sqlite_open_attempted
        sqlite_open_attempted = True
        raise AssertionError("SQLite must not open after active hash mismatch")

    monkeypatch.setattr(reconstruction, "_connect", unexpected_sqlite_open)

    with pytest.raises(reconstruction.GuardRailError, match="SHA-256 mismatch before SQLite open"):
        reconstruction.reconstruct(
            simulated_active,
            _approved_manifest(),
            dry_run=True,
            allow_active_prod1=True,
            expected_active_sha256="0" * 64,
            _canonical_active_database=simulated_active,
        )
    assert sqlite_open_attempted is False


@pytest.mark.parametrize("sidecar_suffix", ("-wal", "-shm", "-journal"))
def test_simulated_active_sidecar_is_refused_before_sqlite_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sidecar_suffix: str,
):
    simulated_active = tmp_path / "canonical" / "database.db"
    simulated_active.parent.mkdir()
    simulated_active.write_bytes(b"simulated active custody")
    expected_hash = hashlib.sha256(simulated_active.read_bytes()).hexdigest()
    Path(f"{simulated_active}{sidecar_suffix}").write_bytes(b"present")
    sqlite_open_attempted = False

    def unexpected_sqlite_open(*args, **kwargs):
        nonlocal sqlite_open_attempted
        sqlite_open_attempted = True
        raise AssertionError("SQLite must not open while an active sidecar exists")

    monkeypatch.setattr(reconstruction, "_connect", unexpected_sqlite_open)

    with pytest.raises(reconstruction.GuardRailError, match="sidecar detected") as exc_info:
        reconstruction.reconstruct(
            simulated_active,
            _approved_manifest(),
            dry_run=True,
            allow_active_prod1=True,
            expected_active_sha256=expected_hash,
            _canonical_active_database=simulated_active,
        )
    assert sidecar_suffix in str(exc_info.value)
    assert sqlite_open_attempted is False


def test_unrelated_database_db_remains_refused_with_allow_flag(tmp_path: Path):
    simulated_active = tmp_path / "canonical" / "database.db"
    unrelated = tmp_path / "unrelated" / "database.db"
    simulated_active.parent.mkdir()
    unrelated.parent.mkdir()
    simulated_active.write_bytes(b"canonical")
    unrelated.write_bytes(b"unrelated")

    with pytest.raises(reconstruction.GuardRailError, match="unrelated database.db"):
        reconstruction.authorize_database_target(
            unrelated,
            allow_active_prod1=True,
            expected_active_sha256=hashlib.sha256(unrelated.read_bytes()).hexdigest(),
            _canonical_active_database=simulated_active,
        )


def test_simulated_exact_active_authorization_succeeds_with_matching_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    simulated_active = tmp_path / "canonical" / "database.db"
    simulated_active.parent.mkdir()
    simulated_active.write_bytes(b"simulated active custody")
    expected_hash = hashlib.sha256(simulated_active.read_bytes()).hexdigest()
    before_signature = _signature(simulated_active)
    before_mtime_ns = simulated_active.stat().st_mtime_ns

    authorization = reconstruction.authorize_database_target(
        simulated_active,
        allow_active_prod1=True,
        expected_active_sha256=expected_hash,
        _canonical_active_database=simulated_active,
    )

    assert authorization == {
        "path": simulated_active.resolve(),
        "db_pre_sha256": expected_hash,
        "active_authorization_mode": "authorized_active_prod1",
        "sidecar_preflight": [],
    }

    class AuthorizedSQLiteBoundaryReached(Exception):
        pass

    def authorized_sqlite_boundary(path, *, read_only, immutable):
        assert path == simulated_active.resolve()
        assert read_only is True
        assert immutable is True
        raise AuthorizedSQLiteBoundaryReached

    monkeypatch.setattr(reconstruction, "_connect", authorized_sqlite_boundary)

    with pytest.raises(AuthorizedSQLiteBoundaryReached):
        reconstruction.reconstruct(
            simulated_active.resolve(),
            _approved_manifest(),
            dry_run=True,
            allow_active_prod1=True,
            expected_active_sha256=expected_hash,
            _canonical_active_database=simulated_active,
        )
    assert _signature(simulated_active) == before_signature
    assert simulated_active.stat().st_mtime_ns == before_mtime_ns
    assert reconstruction._sqlite_sidecars(simulated_active) == []


def test_wal_mode_active_dry_run_uses_immutable_uri_and_creates_no_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    simulated_active = _bootstrap_wal_mode(tmp_path)
    expected_hash = hashlib.sha256(simulated_active.read_bytes()).hexdigest()
    before_signature = _signature(simulated_active)
    before_mtime_ns = simulated_active.stat().st_mtime_ns
    actual_connect = reconstruction.sqlite3.connect
    connection_calls: list[tuple[str, bool]] = []

    def capture_connect(database, *args, **kwargs):
        connection_calls.append((str(database), kwargs.get("uri", False)))
        return actual_connect(database, *args, **kwargs)

    monkeypatch.setattr(reconstruction.sqlite3, "connect", capture_connect)

    query_only_probe = reconstruction._connect(
        simulated_active.resolve(),
        read_only=True,
        immutable=True,
    )
    try:
        assert query_only_probe.execute("PRAGMA query_only").fetchone()[0] == 1
    finally:
        query_only_probe.close()
    assert reconstruction._sqlite_sidecars(simulated_active) == []
    connection_calls.clear()

    report = reconstruction.reconstruct(
        simulated_active.resolve(),
        _approved_manifest(),
        dry_run=True,
        allow_active_prod1=True,
        expected_active_sha256=expected_hash,
        _canonical_active_database=simulated_active,
    )

    target_connection_calls = [call for call in connection_calls if call[0].startswith("file:")]
    assert target_connection_calls == [
        (simulated_active.resolve().as_uri() + "?mode=ro&immutable=1", True)
    ]
    assert report["status"] == "dry_run_ready"
    assert report["planned"] == {
        "normas": 1,
        "atividade_base": 27,
        "atividade_versao": 27,
    }
    assert report["created"] == {
        "normas": 0,
        "atividade_base": 0,
        "atividade_versao": 0,
    }
    assert report["active_authorization_mode"] == "authorized_active_prod1"
    assert _signature(simulated_active) == before_signature
    assert simulated_active.stat().st_mtime_ns == before_mtime_ns
    assert reconstruction._sqlite_sidecars(simulated_active) == []


def test_active_real_uses_nonimmutable_uri_and_remains_write_capable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    simulated_active = _bootstrap(tmp_path)
    expected_hash = hashlib.sha256(simulated_active.read_bytes()).hexdigest()
    actual_connect = reconstruction.sqlite3.connect
    connection_calls: list[tuple[str, bool]] = []

    def capture_connect(database, *args, **kwargs):
        connection_calls.append((str(database), kwargs.get("uri", False)))
        return actual_connect(database, *args, **kwargs)

    monkeypatch.setattr(reconstruction.sqlite3, "connect", capture_connect)

    report = reconstruction.reconstruct(
        simulated_active.resolve(),
        _approved_manifest(),
        dry_run=False,
        allow_active_prod1=True,
        expected_active_sha256=expected_hash,
        _canonical_active_database=simulated_active,
    )

    target_connection_calls = [call for call in connection_calls if call[0].startswith("file:")]
    assert target_connection_calls == [
        (simulated_active.resolve().as_uri() + "?mode=rw", True)
    ]
    assert "immutable=" not in target_connection_calls[0][0]
    assert report["status"] == "reconstructed"
    assert report["created"] == {
        "normas": 1,
        "atividade_base": 27,
        "atividade_versao": 27,
    }


def test_successful_disposable_reconstruction_is_exact_and_structurally_green(tmp_path: Path):
    db_path = _bootstrap(tmp_path)
    manifest_path = _approved_manifest()

    report = reconstruction.reconstruct(db_path, manifest_path, dry_run=False)

    assert report["status"] == "reconstructed"
    assert report["created"] == {
        "normas": 1,
        "atividade_base": 27,
        "atividade_versao": 27,
    }
    assert report["validation"]["field_validation"] == "27/27"
    assert report["validation"]["integrity_check"] == "ok"
    assert report["validation"]["foreign_key_violations"] == 0
    assert report["validation"]["schema"] == {
        "schema_epoch": "prod-1",
        "schema_version": 1,
        "baseline_marker": "first_production_baseline",
        "table_count": 28,
    }
    assert _counts(db_path) == (1, 27, 27)
    assert not Path(f"{db_path}-wal").exists()
    assert not Path(f"{db_path}-shm").exists()
    assert not Path(f"{db_path}-journal").exists()


def test_anac_flight_hours_preserve_equivalent_hours_without_invented_caps(tmp_path: Path):
    db_path = _bootstrap(tmp_path)
    reconstruction.reconstruct(db_path, _approved_manifest(), dry_run=False)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """SELECT n.codigo AS norma_ref,v.codigo_normativo,v.ch_por_evento,
                      v.limite_semestre,v.limite_total,v.observacao_aluno,
                      v.observacao_admin,v.numero_versao
                 FROM atividade_base b
                 JOIN atividade_versao v ON v.atividade_base_id=b.id
                 JOIN norma_atividade n ON n.id=v.norma_id
                WHERE b.nome_conceito='Horas de voo em escola homologada pela ANAC'"""
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["norma_ref"] == row["codigo_normativo"] == "AAC-rev6"
    assert row["ch_por_evento"] is None
    assert row["limite_semestre"] is None
    assert row["limite_total"] is None
    assert row["numero_versao"] == 1
    observations = reconstruction._normalize_text(
        f"{row['observacao_aluno']} {row['observacao_admin']}"
    )
    assert "horas equivalentes" in observations
    assert "comprova" in observations


def test_disposable_import_creates_no_aeu_target_rows(tmp_path: Path):
    db_path = _bootstrap(tmp_path)
    reconstruction.reconstruct(db_path, _approved_manifest(), dry_run=False)
    conn = sqlite3.connect(db_path)
    try:
        aeu_count = int(
            conn.execute("SELECT COUNT(*) FROM atividade_versao WHERE eixo='AEU'").fetchone()[0]
        )
        excluded_names = int(
            conn.execute(
                """SELECT COUNT(*) FROM atividade_base
                    WHERE lower(nome_conceito)='horas de voo em simulador'
                       OR lower(nome_conceito)='teste'
                       OR lower(nome_conceito) LIKE 'runtime base%'"""
            ).fetchone()[0]
        )
    finally:
        conn.close()

    assert aeu_count == 0
    assert excluded_names == 0


def test_transaction_rolls_back_all_business_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = _bootstrap(tmp_path)
    manifest_path = _approved_manifest()
    original = reconstruction._insert_activity
    calls = 0

    def fail_during_third_insert(conn, activity, norma_id):
        nonlocal calls
        calls += 1
        original(conn, activity, norma_id)
        if calls == 3:
            raise RuntimeError("injected atomicity failure")

    monkeypatch.setattr(reconstruction, "_insert_activity", fail_during_third_insert)

    with pytest.raises(RuntimeError, match="atomicity"):
        reconstruction.reconstruct(db_path, manifest_path, dry_run=False)
    assert _counts(db_path) == (0, 0, 0)


def test_final_post_write_validation_failure_rolls_back_every_insert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = _bootstrap(tmp_path)
    validation_observed_inserted_rows = False

    def fail_final_validation(conn, manifest, schema_status=None):
        nonlocal validation_observed_inserted_rows
        in_transaction_counts = tuple(
            int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("norma_atividade", "atividade_base", "atividade_versao")
        )
        assert in_transaction_counts == (1, 27, 27)
        validation_observed_inserted_rows = True
        raise reconstruction.PostValidationError("injected final validation failure")

    monkeypatch.setattr(
        reconstruction,
        "_validate_exact_reconstruction",
        fail_final_validation,
    )

    with pytest.raises(reconstruction.PostValidationError, match="final validation"):
        reconstruction.reconstruct(db_path, _approved_manifest(), dry_run=False)
    assert validation_observed_inserted_rows is True
    assert _counts(db_path) == (0, 0, 0)
    assert not Path(f"{db_path}-wal").exists()
    assert not Path(f"{db_path}-shm").exists()
    assert not Path(f"{db_path}-journal").exists()


def test_duplicate_collision_fails_closed_without_new_rows(tmp_path: Path):
    db_path = _bootstrap(tmp_path)
    manifest_path = _approved_manifest()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO atividade_base(nome_conceito,descricao,status) VALUES(?,?,?)",
            ("Atividade canônica 01", None, "ativo"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(reconstruction.PreStateError, match="unexpected existing"):
        reconstruction.reconstruct(db_path, manifest_path, dry_run=False)
    assert _counts(db_path) == (0, 1, 0)


def test_unexpected_norma_mismatch_fails_closed(tmp_path: Path):
    db_path = _bootstrap(tmp_path)
    manifest_path = _approved_manifest()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO norma_atividade(codigo,eixo,revisao,nome,descricao,status)
               VALUES('AAC-other','AAC','other','Unexpected',NULL,'ativa')"""
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(reconstruction.PreStateError, match="unexpected existing"):
        reconstruction.reconstruct(db_path, manifest_path, dry_run=False)
    assert _counts(db_path) == (1, 0, 0)


def test_internal_rev6_source_rev7_human_provenance_is_locked():
    manifest = _manifest()
    manifest["source_document_revision"] = "AAC-rev6.docx"
    with pytest.raises(reconstruction.ManifestError, match="ACC-rev7.docx"):
        reconstruction._validate_manifest_data(manifest)

    manifest = _manifest()
    manifest["renumbering_decision"] = "unapproved"
    with pytest.raises(reconstruction.ManifestError, match="provenance"):
        reconstruction._validate_manifest_data(manifest)


def test_special_visitas_rule_remains_conditional_and_semester_20():
    manifest = _manifest()
    visitas = next(
        item
        for item in manifest["activities"]
        if item["atividade_base"]["nome_conceito"] == reconstruction.SPECIAL_VISITAS
    )
    visitas["atividade_versao"]["ch_por_evento"] = 5

    with pytest.raises(reconstruction.ManifestError, match="cannot be flattened"):
        reconstruction._validate_manifest_data(manifest)

    manifest = _manifest()
    visitas = next(
        item
        for item in manifest["activities"]
        if item["atividade_base"]["nome_conceito"] == reconstruction.SPECIAL_VISITAS
    )
    visitas["atividade_versao"]["observacao_aluno"] = "Only 5h per visit."
    visitas["atividade_versao"]["observacao_admin"] = None
    with pytest.raises(reconstruction.ManifestError, match="actual course hours"):
        reconstruction._validate_manifest_data(manifest)


def test_filmes_rule_requires_5_hours_and_semester_50():
    manifest = _manifest()
    filmes = next(
        item
        for item in manifest["activities"]
        if item["atividade_base"]["nome_conceito"] == reconstruction.SPECIAL_FILMES
    )
    filmes["atividade_versao"]["limite_semestre"] = 5

    with pytest.raises(reconstruction.ManifestError, match="ch_por_evento=5"):
        reconstruction._validate_manifest_data(manifest)


@pytest.mark.parametrize(
    "excluded_name",
    ("Teste", "Runtime Base 5c96604e", "Runtime Base 2cb9b503", "Horas de voo em simulador"),
)
def test_locked_activity_exclusions_are_rejected(excluded_name: str):
    manifest = _manifest()
    manifest["activities"][0]["atividade_base"]["nome_conceito"] = excluded_name

    with pytest.raises(reconstruction.ManifestError, match="excluded activity"):
        reconstruction._validate_manifest_data(manifest)


def test_rerun_is_an_exact_safe_noop(tmp_path: Path):
    db_path = _bootstrap(tmp_path)
    manifest_path = _approved_manifest()
    reconstruction.reconstruct(db_path, manifest_path, dry_run=False)
    before = _signature(db_path)

    report = reconstruction.reconstruct(db_path, manifest_path, dry_run=False)

    assert report["status"] == "already_reconstructed"
    assert report["created"] == {
        "normas": 0,
        "atividade_base": 0,
        "atividade_versao": 0,
    }
    assert report["validation"]["field_validation"] == "27/27"
    assert _counts(db_path) == (1, 27, 27)
    assert _signature(db_path) == before


def test_exact_rerun_validation_refuses_drift(tmp_path: Path):
    db_path = _bootstrap(tmp_path)
    manifest_path = _approved_manifest()
    reconstruction.reconstruct(db_path, manifest_path, dry_run=False)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE atividade_versao SET limite_total=1 WHERE id=(SELECT MIN(id) FROM atividade_versao)"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(reconstruction.PostValidationError, match="field validation mismatch"):
        reconstruction.reconstruct(db_path, manifest_path, dry_run=False)
