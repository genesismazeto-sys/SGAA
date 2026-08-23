from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_DATABASE = (PROJECT_ROOT / "database.db").resolve()
APPROVED_MANIFEST_SHA256 = "eb26e213295ddb48299a843efbd274959dcf155281569cbf3ee25214616b0164"
EXPECTED_MANIFEST_TYPE = "sgaa_aac_native_reconstruction_final_v1"
EXPECTED_TARGET_COUNT = 27
EXPECTED_NORMA_CODE = "AAC-rev6"
EXPECTED_SOURCE_DOCUMENT = "ACC-rev7.docx"
EXPECTED_SOURCE_SHA256 = "cf9fbf5c36900aa7e01db150051bd81b2e4822764e946cbc188b0a91cbb635e6"
EXPECTED_GIT_SHA = "f3b155b31dcf1e06705aafd6825e1aa380fd04ac"
EXPECTED_RENUMBERING_DECISION = (
    "Source document: ACC-rev7.docx; registered internally in SGAA as AAC-rev6 "
    "by explicit human decision."
)
SPECIAL_VISITAS = "Visitas técnicas ou cursos coordenados pelos professores do curso"
SPECIAL_FILMES = "Filmes, cinema e peças de teatro"
FORBIDDEN_EXACT_NAMES = {
    "teste",
    "horas de voo em simulador",
}
FORBIDDEN_PREFIXES = ("runtime base",)
REQUIRED_EXCLUSION_MARKERS = {
    "Teste",
    "Runtime Base",
    "Runtime Base 5c96604e",
    "Runtime Base 2cb9b503",
    "Horas de voo em simulador",
    "AEU rows",
    "Matrix links",
    "requests/history",
    "legacy maps",
    "development-era version history",
}
EMPTY_SCOPE_TABLES = (
    "atividade_transicao",
    "matriz_norma",
    "matriz_atividade_versao_item",
    "matrizes_atividades",
    "requisicoes",
)
DESTINATION_VERSION_FIELDS = (
    "codigo_normativo",
    "eixo",
    "grupo",
    "ch_por_evento",
    "limite_semestre",
    "limite_total",
    "observacao_aluno",
    "observacao_admin",
    "documentos_json",
    "vigencia_inicio",
    "vigencia_fim",
    "numero_versao",
    "status",
    "versao_anterior_id",
)
REQUIRED_PROVENANCE_FIELDS = {
    "atividade_base.nome_conceito",
    "atividade_base.descricao",
    "atividade_base.status",
    "atividade_versao.norma_ref",
    *(f"atividade_versao.{field}" for field in DESTINATION_VERSION_FIELDS),
}


class ReconstructionError(RuntimeError):
    """Base error for the bounded AAC reconstruction."""


class GuardRailError(ReconstructionError):
    """The explicit database target is unsafe."""


class ManifestError(ReconstructionError):
    """The external reconstruction manifest violates the locked contract."""


class ManifestIdentityError(ManifestError):
    """The manifest bytes are not the one approved reconstruction authority."""


class PreStateError(ReconstructionError):
    """The target is neither clean nor an exact prior reconstruction."""


class PostValidationError(ReconstructionError):
    """The atomic write did not produce the exact declared state."""


def _load_prod1_schema_module():
    """Load only the canonical schema owner, without importing the Flask app."""
    module_path = PROJECT_ROOT / "app" / "prod1_schema.py"
    spec = importlib.util.spec_from_file_location("_aac_prod1_schema", module_path)
    if spec is None or spec.loader is None:
        raise ReconstructionError(f"Unable to load canonical schema owner: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(normalized.casefold().split())


def _mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{context} must be a JSON object")
    return value


def _list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ManifestError(f"{context} must be a JSON array")
    return value


def _string(value: Any, context: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{context} must be a non-empty string")
    return value


def _nullable_number(value: Any, context: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{context} must be a non-negative number or null")
    if value < 0:
        raise ManifestError(f"{context} must be non-negative")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sqlite_sidecars(db_path: Path) -> list[Path]:
    return [
        sidecar
        for suffix in ("-wal", "-shm", "-journal")
        if (sidecar := Path(f"{db_path}{suffix}")).exists()
    ]


def authorize_database_target(
    db_path: Path,
    *,
    allow_active_prod1: bool = False,
    expected_active_sha256: str | None = None,
    _canonical_active_database: Path | None = None,
) -> dict[str, Any]:
    """Authorize a target using filesystem checks only, before SQLite open.

    ``_canonical_active_database`` is an internal pure-function test seam. The
    CLI cannot set it, so production identity is always repository/database.db.
    """
    original_db_path = Path(db_path)
    original_is_absolute = original_db_path.is_absolute()
    resolved = original_db_path.expanduser().resolve(strict=False)
    canonical_active = (
        _canonical_active_database.resolve(strict=False)
        if _canonical_active_database is not None
        else ACTIVE_DATABASE
    )
    is_active = resolved == canonical_active

    if is_active:
        if not original_is_absolute:
            raise GuardRailError(
                "active canonical PROD-1 requires the original --db path to be absolute"
            )
        if not allow_active_prod1:
            raise GuardRailError(
                "active canonical PROD-1 target requires --allow-active-prod1"
            )
        if expected_active_sha256 is None:
            raise GuardRailError(
                "active canonical PROD-1 target requires --expected-active-sha256"
            )
        if re.fullmatch(r"[0-9a-fA-F]{64}", expected_active_sha256) is None:
            raise GuardRailError("--expected-active-sha256 must be exactly 64 hexadecimal characters")
        if not resolved.exists() or not resolved.is_file():
            raise GuardRailError(f"active canonical PROD-1 target is not an existing file: {resolved}")
        actual_sha256 = _sha256_file(resolved)
        if actual_sha256 != expected_active_sha256.casefold():
            raise GuardRailError(
                "active canonical PROD-1 SHA-256 mismatch before SQLite open: "
                f"expected={expected_active_sha256.casefold()} actual={actual_sha256}"
            )
        sidecars = _sqlite_sidecars(resolved)
        if sidecars:
            raise GuardRailError(
                "active canonical PROD-1 sidecar detected before SQLite open: "
                + ", ".join(str(path) for path in sidecars)
            )
        return {
            "path": resolved,
            "db_pre_sha256": actual_sha256,
            "active_authorization_mode": "authorized_active_prod1",
            "sidecar_preflight": [],
        }

    if resolved.name.casefold() == "database.db":
        raise GuardRailError(
            "unrelated database.db target refused; active authorization applies only "
            "to resolved repository/database.db: "
            f"{resolved}"
        )
    if allow_active_prod1 or expected_active_sha256 is not None:
        raise GuardRailError(
            "active PROD-1 authorization options are invalid for a disposable target"
        )
    if not resolved.exists() or not resolved.is_file():
        raise GuardRailError(
            "target must be an existing disposable database bootstrapped with the "
            f"canonical PROD-1 schema: {resolved}"
        )
    return {
        "path": resolved,
        "db_pre_sha256": _sha256_file(resolved),
        "active_authorization_mode": "disposable",
        "sidecar_preflight": [str(path) for path in _sqlite_sidecars(resolved)],
    }


def _validate_manifest_activity(
    raw: Any,
    index: int,
    seen_names: set[str],
) -> dict[str, Any]:
    activity = _mapping(raw, f"activities[{index}]")
    _string(activity.get("aac_ref"), f"activities[{index}].aac_ref")
    _mapping(activity.get("traceability"), f"activities[{index}].traceability")
    provenance = _mapping(
        activity.get("field_provenance"),
        f"activities[{index}].field_provenance",
    )
    missing_provenance = sorted(REQUIRED_PROVENANCE_FIELDS - provenance.keys())
    if missing_provenance:
        raise ManifestError(
            f"activities[{index}].field_provenance missing: {missing_provenance}"
        )
    for field in REQUIRED_PROVENANCE_FIELDS:
        _string(provenance[field], f"activities[{index}].field_provenance.{field}")
    rule_semantics = _mapping(
        activity.get("rule_semantics"),
        f"activities[{index}].rule_semantics",
    )
    _string(
        rule_semantics.get("calculation_rule"),
        f"activities[{index}].rule_semantics.calculation_rule",
    )

    base = _mapping(activity.get("atividade_base"), f"activities[{index}].atividade_base")
    name = _string(base.get("nome_conceito"), f"activities[{index}].atividade_base.nome_conceito")
    assert isinstance(name, str)
    normalized_name = _normalize_text(name)
    if normalized_name in seen_names:
        raise ManifestError(f"duplicate canonical activity name: {name}")
    seen_names.add(normalized_name)
    if normalized_name in FORBIDDEN_EXACT_NAMES or normalized_name.startswith(FORBIDDEN_PREFIXES):
        raise ManifestError(f"excluded activity present in manifest: {name}")
    _string(base.get("descricao"), f"activities[{index}].atividade_base.descricao", nullable=True)
    if base.get("status") != "ativo":
        raise ManifestError(f"{name}: atividade_base.status must be ativo")

    version = _mapping(
        activity.get("atividade_versao"),
        f"activities[{index}].atividade_versao",
    )
    missing_fields = [
        field
        for field in ("norma_ref", *DESTINATION_VERSION_FIELDS)
        if field not in version
    ]
    if missing_fields:
        raise ManifestError(f"{name}: missing destination fields: {missing_fields}")
    if version["norma_ref"] != EXPECTED_NORMA_CODE:
        raise ManifestError(f"{name}: norma_ref must be {EXPECTED_NORMA_CODE}")
    if version["codigo_normativo"] != EXPECTED_NORMA_CODE:
        raise ManifestError(f"{name}: codigo_normativo must be {EXPECTED_NORMA_CODE}")
    if version["eixo"] != "AAC":
        raise ManifestError(f"{name}: eixo must be AAC")
    _string(version["grupo"], f"{name}.grupo")
    for field in ("ch_por_evento", "limite_semestre", "limite_total"):
        _nullable_number(version[field], f"{name}.{field}")
    for field in ("observacao_aluno", "observacao_admin", "vigencia_inicio", "vigencia_fim"):
        _string(version[field], f"{name}.{field}", nullable=True)
    documents = version["documentos_json"]
    if documents is not None:
        if not isinstance(documents, str):
            raise ManifestError(f"{name}.documentos_json must be a JSON string or null")
        try:
            json.loads(documents)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{name}.documentos_json is invalid JSON") from exc
    if version["numero_versao"] != 1:
        raise ManifestError(f"{name}: numero_versao must be 1")
    if version["status"] != "ativa":
        raise ManifestError(f"{name}: initial version status must be ativa")
    if version["versao_anterior_id"] is not None:
        raise ManifestError(f"{name}: versao_anterior_id must be null")
    return activity


def _validate_special_rules(activities: list[dict[str, Any]]) -> None:
    by_name = {
        item["atividade_base"]["nome_conceito"]: item
        for item in activities
    }
    visitas = by_name.get(SPECIAL_VISITAS)
    if visitas is None:
        raise ManifestError(f"required human-approved activity is absent: {SPECIAL_VISITAS}")
    visitas_version = visitas["atividade_versao"]
    visitas_text = _normalize_text(
        " ".join(
            str(visitas_version.get(field) or "")
            for field in ("observacao_aluno", "observacao_admin")
        )
    )
    if visitas_version["ch_por_evento"] is not None:
        raise ManifestError("Visitas conditional rule cannot be flattened into ch_por_evento")
    if visitas_version["limite_semestre"] != 20:
        raise ManifestError("Visitas limite_semestre must be 20")
    if not all(token in visitas_text for token in ("curso", "carga horaria", "5h", "visita")):
        raise ManifestError(
            "Visitas observations must preserve actual course hours and 5h-per-visit branches"
        )

    filmes = by_name.get(SPECIAL_FILMES)
    if filmes is None:
        raise ManifestError(f"required reconciled activity is absent: {SPECIAL_FILMES}")
    filmes_version = filmes["atividade_versao"]
    if filmes_version["ch_por_evento"] != 5 or filmes_version["limite_semestre"] != 50:
        raise ManifestError("Filmes must retain ch_por_evento=5 and limite_semestre=50")


def _validate_manifest_data(data: Any) -> dict[str, Any]:
    manifest = _mapping(data, "manifest")
    if manifest.get("manifest_type") != EXPECTED_MANIFEST_TYPE:
        raise ManifestError(f"manifest_type must be {EXPECTED_MANIFEST_TYPE}")
    if manifest.get("target_real_aac_count") != EXPECTED_TARGET_COUNT:
        raise ManifestError(f"target_real_aac_count must be {EXPECTED_TARGET_COUNT}")
    if manifest.get("internal_norma_code") != EXPECTED_NORMA_CODE:
        raise ManifestError(f"internal_norma_code must be {EXPECTED_NORMA_CODE}")
    if manifest.get("source_document_revision") != EXPECTED_SOURCE_DOCUMENT:
        raise ManifestError(f"source_document_revision must be {EXPECTED_SOURCE_DOCUMENT}")
    if manifest.get("renumbering_decision") != EXPECTED_RENUMBERING_DECISION:
        raise ManifestError("human-approved rev7-to-rev6 provenance statement mismatch")
    if manifest.get("git_sha") != EXPECTED_GIT_SHA:
        raise ManifestError(f"git_sha must be the locked source HEAD {EXPECTED_GIT_SHA}")

    source = _mapping(manifest.get("source"), "source")
    _string(source.get("historical_db_path"), "source.historical_db_path")
    if source.get("historical_db_sha256") != EXPECTED_SOURCE_SHA256:
        raise ManifestError("approved historical source SHA-256 mismatch")

    exclusions = set(_list(manifest.get("exclusions"), "exclusions"))
    missing_exclusions = sorted(REQUIRED_EXCLUSION_MARKERS - exclusions)
    if missing_exclusions:
        raise ManifestError(f"locked exclusions missing from manifest: {missing_exclusions}")

    norma = _mapping(manifest.get("norma"), "norma")
    expected_norma = {
        "codigo": EXPECTED_NORMA_CODE,
        "eixo": "AAC",
        "revisao": "rev6",
        "nome": "AAC regulamento novo",
        "descricao": None,
        "status": "ativa",
    }
    if norma != expected_norma:
        raise ManifestError(f"Norma destination mismatch: expected {expected_norma!r}")

    raw_activities = _list(manifest.get("activities"), "activities")
    if len(raw_activities) != EXPECTED_TARGET_COUNT:
        raise ManifestError(f"activities must contain exactly {EXPECTED_TARGET_COUNT} rows")
    seen_names: set[str] = set()
    activities = [
        _validate_manifest_activity(raw, index, seen_names)
        for index, raw in enumerate(raw_activities, start=1)
    ]
    refs = [item["aac_ref"] for item in activities]
    if len(set(refs)) != EXPECTED_TARGET_COUNT:
        raise ManifestError("aac_ref values must be unique")
    _validate_special_rules(activities)
    manifest["activities"] = activities
    return manifest


def load_and_validate_manifest(
    manifest_path: Path,
) -> tuple[dict[str, Any], str, Path]:
    resolved = manifest_path.expanduser().resolve(strict=False)
    try:
        raw_bytes = resolved.read_bytes()
    except OSError as exc:
        raise ManifestError(f"unable to read approved JSON manifest: {resolved}") from exc
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha256 != APPROVED_MANIFEST_SHA256:
        raise ManifestIdentityError(
            "approved manifest SHA-256 mismatch before JSON parse and SQLite open: "
            f"expected={APPROVED_MANIFEST_SHA256} actual={actual_sha256}"
        )
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"approved manifest bytes are not valid UTF-8 JSON: {resolved}") from exc
    return _validate_manifest_data(data), actual_sha256, resolved


def _connect(
    path: Path,
    *,
    read_only: bool,
    immutable: bool = False,
) -> sqlite3.Connection:
    if immutable and not read_only:
        raise ValueError("immutable SQLite mode is valid only for read-only connections")
    mode = "ro" if read_only else "rw"
    uri = path.as_uri() + f"?mode={mode}"
    if immutable:
        uri += "&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if read_only:
        conn.execute("PRAGMA query_only=ON")
    return conn


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "norma_atividade",
        "atividade_base",
        "atividade_versao",
        *EMPTY_SCOPE_TABLES,
    )
    return {
        table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables
    }


def _assert_scope_empty(conn: sqlite3.Connection, counts: dict[str, int]) -> None:
    unexpected = {table: counts[table] for table in EMPTY_SCOPE_TABLES if counts[table] != 0}
    aeu = int(conn.execute("SELECT COUNT(*) FROM atividade_versao WHERE eixo='AEU'").fetchone()[0])
    if aeu:
        unexpected["atividade_versao_AEU"] = aeu
    if unexpected:
        raise PreStateError(f"unexpected out-of-scope business rows: {unexpected}")


def _runtime_rows(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """SELECT b.nome_conceito,b.descricao AS base_descricao,b.status AS base_status,
                  n.codigo AS norma_ref,v.codigo_normativo,v.eixo,v.grupo,
                  v.ch_por_evento,v.limite_semestre,v.limite_total,
                  v.observacao_aluno,v.observacao_admin,v.documentos_json,
                  v.vigencia_inicio,v.vigencia_fim,v.numero_versao,
                  v.status,v.versao_anterior_id
             FROM atividade_base b
             JOIN atividade_versao v ON v.atividade_base_id=b.id
             JOIN norma_atividade n ON n.id=v.norma_id
         ORDER BY b.nome_conceito"""
    ).fetchall()
    return {str(row["nome_conceito"]): dict(row) for row in rows}


def _expected_runtime_rows(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    expected: dict[str, dict[str, Any]] = {}
    for activity in manifest["activities"]:
        base = activity["atividade_base"]
        version = activity["atividade_versao"]
        expected[base["nome_conceito"]] = {
            "nome_conceito": base["nome_conceito"],
            "base_descricao": base["descricao"],
            "base_status": base["status"],
            "norma_ref": version["norma_ref"],
            **{field: version[field] for field in DESTINATION_VERSION_FIELDS},
        }
    return expected


def _validate_exact_reconstruction(
    conn: sqlite3.Connection,
    manifest: dict[str, Any],
    schema_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema_module = _load_prod1_schema_module()
    schema_status = schema_status or schema_module.validate_prod1_schema(conn)
    counts = _counts(conn)
    expected_counts = {
        "norma_atividade": 1,
        "atividade_base": EXPECTED_TARGET_COUNT,
        "atividade_versao": EXPECTED_TARGET_COUNT,
        **{table: 0 for table in EMPTY_SCOPE_TABLES},
    }
    if counts != expected_counts:
        raise PostValidationError(f"post-write count mismatch: {counts!r}")
    norma_row = conn.execute(
        "SELECT codigo,eixo,revisao,nome,descricao,status FROM norma_atividade"
    ).fetchone()
    if norma_row is None or dict(norma_row) != manifest["norma"]:
        raise PostValidationError("runtime Norma is not the exact manifest Norma")
    actual_rows = _runtime_rows(conn)
    expected_rows = _expected_runtime_rows(manifest)
    if actual_rows != expected_rows:
        missing = sorted(set(expected_rows) - set(actual_rows))
        unexpected = sorted(set(actual_rows) - set(expected_rows))
        mismatched = sorted(
            name
            for name in set(actual_rows) & set(expected_rows)
            if actual_rows[name] != expected_rows[name]
        )
        raise PostValidationError(
            "27/27 field validation mismatch: "
            f"missing={missing!r} unexpected={unexpected!r} mismatched={mismatched!r}"
        )
    integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    if integrity != "ok" or foreign_keys:
        raise PostValidationError(
            f"SQLite structural validation failed: integrity={integrity!r} foreign_keys={foreign_keys!r}"
        )
    return {
        "schema": schema_status,
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
        "field_validation": f"{EXPECTED_TARGET_COUNT}/{EXPECTED_TARGET_COUNT}",
        "counts": counts,
    }


def _classify_pre_state(
    conn: sqlite3.Connection,
    manifest: dict[str, Any],
) -> tuple[str, dict[str, int], dict[str, Any]]:
    schema_module = _load_prod1_schema_module()
    schema_status = schema_module.validate_prod1_schema(conn)
    counts = _counts(conn)
    _assert_scope_empty(conn, counts)
    core = (
        counts["norma_atividade"],
        counts["atividade_base"],
        counts["atividade_versao"],
    )
    if core == (0, 0, 0):
        return "clean", counts, schema_status
    if core == (1, EXPECTED_TARGET_COUNT, EXPECTED_TARGET_COUNT):
        _validate_exact_reconstruction(conn, manifest, schema_status)
        return "already_reconstructed", counts, schema_status
    raise PreStateError(
        "unexpected existing Norma/activity state; expected (0,0,0) or exact "
        f"(1,{EXPECTED_TARGET_COUNT},{EXPECTED_TARGET_COUNT}), got {core}"
    )


def _insert_activity(
    conn: sqlite3.Connection,
    activity: dict[str, Any],
    norma_id: int,
) -> None:
    base = activity["atividade_base"]
    version = activity["atividade_versao"]
    cursor = conn.execute(
        "INSERT INTO atividade_base(nome_conceito,descricao,status) VALUES(?,?,?)",
        (base["nome_conceito"], base["descricao"], base["status"]),
    )
    base_id = int(cursor.lastrowid)
    columns = (
        "atividade_base_id",
        "norma_id",
        *DESTINATION_VERSION_FIELDS,
    )
    values = (
        base_id,
        norma_id,
        *(version[field] for field in DESTINATION_VERSION_FIELDS),
    )
    placeholders = ",".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO atividade_versao({','.join(columns)}) VALUES({placeholders})",
        values,
    )


def reconstruct(
    db_path: Path,
    manifest_path: Path,
    *,
    dry_run: bool,
    allow_active_prod1: bool = False,
    expected_active_sha256: str | None = None,
    _canonical_active_database: Path | None = None,
) -> dict[str, Any]:
    manifest, manifest_sha256, resolved_manifest = load_and_validate_manifest(manifest_path)
    target_authorization = authorize_database_target(
        db_path,
        allow_active_prod1=allow_active_prod1,
        expected_active_sha256=expected_active_sha256,
        _canonical_active_database=_canonical_active_database,
    )
    safe_db = target_authorization["path"]
    active_dry_run = (
        dry_run
        and target_authorization["active_authorization_mode"] == "authorized_active_prod1"
    )
    conn = _connect(safe_db, read_only=dry_run, immutable=active_dry_run)
    try:
        pre_state, pre_counts, schema_status = _classify_pre_state(conn, manifest)
        base_report = {
            "database": str(safe_db),
            "dry_run": dry_run,
            "manifest": str(resolved_manifest),
            "manifest_sha256": manifest_sha256,
            "db_pre_sha256": target_authorization["db_pre_sha256"],
            "active_authorization_mode": target_authorization["active_authorization_mode"],
            "sidecar_preflight": target_authorization["sidecar_preflight"],
            "internal_norma": EXPECTED_NORMA_CODE,
            "source_document": EXPECTED_SOURCE_DOCUMENT,
            "target_aac": EXPECTED_TARGET_COUNT,
            "pre_state": pre_state,
            "pre_counts": pre_counts,
        }
        if pre_state == "already_reconstructed":
            validation = _validate_exact_reconstruction(conn, manifest, schema_status)
            return {
                **base_report,
                "status": "already_reconstructed",
                "planned": {"normas": 0, "atividade_base": 0, "atividade_versao": 0},
                "created": {"normas": 0, "atividade_base": 0, "atividade_versao": 0},
                "validation": validation,
            }
        if dry_run:
            return {
                **base_report,
                "status": "dry_run_ready",
                "planned": {
                    "normas": 1,
                    "atividade_base": EXPECTED_TARGET_COUNT,
                    "atividade_versao": EXPECTED_TARGET_COUNT,
                },
                "created": {"normas": 0, "atividade_base": 0, "atividade_versao": 0},
                "validation": {"schema": schema_status},
            }

        try:
            conn.execute("BEGIN IMMEDIATE")
            norma = manifest["norma"]
            cursor = conn.execute(
                """INSERT INTO norma_atividade(codigo,eixo,revisao,nome,descricao,status)
                   VALUES(?,?,?,?,?,?)""",
                tuple(norma[field] for field in ("codigo", "eixo", "revisao", "nome", "descricao", "status")),
            )
            norma_id = int(cursor.lastrowid)
            for activity in manifest["activities"]:
                _insert_activity(conn, activity, norma_id)
            validation = _validate_exact_reconstruction(conn, manifest)
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        return {
            **base_report,
            "status": "reconstructed",
            "planned": {
                "normas": 1,
                "atividade_base": EXPECTED_TARGET_COUNT,
                "atividade_versao": EXPECTED_TARGET_COUNT,
            },
            "created": {
                "normas": 1,
                "atividade_base": EXPECTED_TARGET_COUNT,
                "atividade_versao": EXPECTED_TARGET_COUNT,
            },
            "validation": validation,
        }
    finally:
        conn.close()


def _text_report(report: dict[str, Any]) -> str:
    planned = report["planned"]
    created = report["created"]
    lines = [
        f"Status: {report['status']}",
        f"Database: {report['database']}",
        f"Dry-run: {report['dry_run']}",
        f"Manifest SHA-256: {report['manifest_sha256']}",
        f"DB pre-SHA-256: {report['db_pre_sha256']}",
        f"Active authorization: {report['active_authorization_mode']}",
        f"Sidecar preflight: {report['sidecar_preflight']}",
        f"Norma: {report['internal_norma']}",
        f"Source document: {report['source_document']}",
        f"AAC target: {report['target_aac']}",
        f"Pre-state: {report['pre_state']} {report['pre_counts']}",
        f"Planned: Norma={planned['normas']} bases={planned['atividade_base']} versions={planned['atividade_versao']}",
        f"Created: Norma={created['normas']} bases={created['atividade_base']} versions={created['atividade_versao']}",
    ]
    validation = report.get("validation", {})
    if "field_validation" in validation:
        lines.append(f"Field validation: {validation['field_validation']}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded one-time native reconstruction of the approved 27 AAC set."
    )
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Explicit existing PROD-1 target; the canonical active target is additionally gated",
    )
    parser.add_argument("--manifest", type=Path, required=True, help="Explicit final reconstruction JSON manifest")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without mutation")
    parser.add_argument(
        "--allow-active-prod1",
        action="store_true",
        help="Explicitly authorize only the resolved repository database.db target",
    )
    parser.add_argument(
        "--expected-active-sha256",
        help="Required 64-hex immediate custody hash when --allow-active-prod1 is used",
    )
    parser.add_argument("--report", choices=("text", "json"), default="text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = reconstruct(
            args.db,
            args.manifest,
            dry_run=args.dry_run,
            allow_active_prod1=args.allow_active_prod1,
            expected_active_sha256=args.expected_active_sha256,
        )
    except ReconstructionError as exc:
        error = {"status": "refused", "error_type": type(exc).__name__, "error": str(exc)}
        if args.report == "json":
            print(json.dumps(error, ensure_ascii=False, sort_keys=True))
        else:
            print(f"REFUSED [{type(exc).__name__}]: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        error = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
        if args.report == "json":
            print(json.dumps(error, ensure_ascii=False, sort_keys=True))
        else:
            print(f"FAILED [{type(exc).__name__}]: {exc}", file=sys.stderr)
        return 3
    if args.report == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_text_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
