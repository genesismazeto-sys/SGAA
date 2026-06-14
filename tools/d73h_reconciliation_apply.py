from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml


TARGET_ACTIVITY_CODE = "VISITAS_TECNICAS_PROFESSORES"
TARGET_NORMA_CODES = ("AAC-rev5", "AAC-rev6")
LIVE_DB_BASENAME = "database.db"
COUNT_TABLES = (
    "norma_atividade",
    "atividade_base",
    "atividade_versao",
    "atividade_transicao",
    "matriz_atividade_versao_item",
    "requisicoes",
)


class ReconciliationApplyError(Exception):
    """Base exception for the controlled reconciliation script."""


class FixtureValidationError(ReconciliationApplyError):
    """Raised when the fixture is missing or invalid."""


class GuardRailError(ReconciliationApplyError):
    """Raised when a safety guardrail is violated."""


class StateConflictError(ReconciliationApplyError):
    """Raised when the current database state is partial or conflicting."""


class PostconditionError(ReconciliationApplyError):
    """Raised when post-apply validation fails."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Controlled plan/apply script for the future VISITAS_TECNICAS_PROFESSORES "
            "draft creation path."
        )
    )
    parser.add_argument("--fixture", required=True, type=Path, help="Path to the YAML fixture.")
    parser.add_argument(
        "--db-copy",
        required=True,
        type=Path,
        help="Database path to inspect in --plan or mutate in --apply.",
    )
    parser.add_argument(
        "--report",
        choices=("text", "json"),
        default="text",
        help="Report format. Default: text.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--plan", action="store_true", help="Run in read-only planning mode.")
    mode_group.add_argument("--apply", action="store_true", help="Run in controlled apply mode.")
    parser.add_argument("--backup-path", type=Path, help="Existing backup path required for --apply.")
    parser.add_argument(
        "--backup-confirmed",
        action="store_true",
        help="Explicit confirmation that the backup path is valid and ready.",
    )
    parser.add_argument(
        "--allow-create-visitas-professores",
        action="store_true",
        help="Explicit authorization for the only allowed write scope.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors.",
    )
    args = parser.parse_args(argv)
    args.mode = "apply" if args.apply else "plan"
    return args


def normalize_name(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(normalized.casefold().split())


def _normalize_required_string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureValidationError(f"{context} must be a non-empty string.")
    return value.strip()


def _normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sqlite_ro_uri(path: Path) -> str:
    encoded = quote(path.resolve().as_posix(), safe="/:")
    return f"file:{encoded}?mode=ro"


def file_signature(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.exists():
        raise GuardRailError(f"File not found for signature: {resolved}")
    return {
        "path": str(resolved),
        "size": resolved.stat().st_size,
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest().upper(),
    }


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    resolved = db_path.resolve()
    if not resolved.exists():
        raise GuardRailError(f"Read-only target database not found: {resolved}")
    conn = sqlite3.connect(_sqlite_ro_uri(resolved), uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = 1")
    return conn


def connect_apply_copy(db_path: Path, *, live_db_path: Path) -> sqlite3.Connection:
    resolved = db_path.resolve()
    live_resolved = live_db_path.resolve()
    if not resolved.exists():
        raise GuardRailError(f"Apply target database not found: {resolved}")
    if resolved == live_resolved:
        raise GuardRailError(
            f"--apply refused: --db-copy points to the live database: {resolved}"
        )
    if resolved.name.casefold() == LIVE_DB_BASENAME.casefold():
        raise GuardRailError(
            f"--apply refused: basename '{LIVE_DB_BASENAME}' is forbidden for --db-copy: {resolved}"
        )
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def load_fixture(fixture_path: Path) -> dict[str, Any]:
    resolved = fixture_path.resolve()
    if not resolved.exists():
        raise FixtureValidationError(f"Fixture not found: {resolved}")
    try:
        raw_data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FixtureValidationError(f"Failed to parse YAML fixture: {exc}") from exc
    if not isinstance(raw_data, dict):
        raise FixtureValidationError("Fixture top-level must be a YAML mapping.")
    if "atividades" not in raw_data or not isinstance(raw_data["atividades"], list):
        raise FixtureValidationError("Fixture must contain an 'atividades' list.")
    return raw_data


def find_visitas_fixture_entry(fixture_data: dict[str, Any]) -> dict[str, Any]:
    matches = [
        item
        for item in fixture_data["atividades"]
        if isinstance(item, dict) and item.get("codigo_atividade") == TARGET_ACTIVITY_CODE
    ]
    if not matches:
        raise FixtureValidationError(
            f"Fixture does not contain required activity: {TARGET_ACTIVITY_CODE}"
        )
    if len(matches) != 1:
        raise FixtureValidationError(
            f"Fixture contains duplicate entries for activity: {TARGET_ACTIVITY_CODE}"
        )

    entry = matches[0]
    nome_canonico = _normalize_required_string(
        entry.get("nome_canonico"),
        context=f"{TARGET_ACTIVITY_CODE}.nome_canonico",
    )
    descricao = _normalize_required_string(
        entry.get("descricao"),
        context=f"{TARGET_ACTIVITY_CODE}.descricao",
    )
    grupo = _normalize_required_string(
        entry.get("grupo"),
        context=f"{TARGET_ACTIVITY_CODE}.grupo",
    )
    raw_versions = entry.get("versoes")
    if not isinstance(raw_versions, list) or not raw_versions:
        raise FixtureValidationError(f"{TARGET_ACTIVITY_CODE}.versoes must be a non-empty list.")
    if len(raw_versions) != 2:
        raise FixtureValidationError(
            f"{TARGET_ACTIVITY_CODE} must contain exactly 2 versions, found {len(raw_versions)}."
        )

    versions_by_code: dict[str, dict[str, Any]] = {}
    for index, raw_version in enumerate(raw_versions, start=1):
        if not isinstance(raw_version, dict):
            raise FixtureValidationError(
                f"{TARGET_ACTIVITY_CODE}.versoes[{index}] must be a YAML mapping."
            )
        norma_ref = _normalize_required_string(
            raw_version.get("norma_ref"),
            context=f"{TARGET_ACTIVITY_CODE}.versoes[{index}].norma_ref",
        )
        if norma_ref in versions_by_code:
            raise FixtureValidationError(
                f"{TARGET_ACTIVITY_CODE} contains duplicate norma_ref values: {norma_ref}"
            )
        versions_by_code[norma_ref] = {
            "norma_ref": norma_ref,
            "codigo_normativo": norma_ref,
            "status": "rascunho",
            "ch_por_evento": raw_version.get("ch_por_evento"),
            "limite_semestre": raw_version.get("limite_semestre"),
            "limite_total": raw_version.get("limite_total"),
            "observacao_aluno": _normalize_optional_string(raw_version.get("observacao_aluno")),
            "observacao_admin": _normalize_optional_string(raw_version.get("observacao_admin")),
            "documentos_json": None,
            "vigencia_inicio": None,
            "vigencia_fim": None,
            "versao_anterior_id": None,
        }

    expected_codes = set(TARGET_NORMA_CODES)
    if set(versions_by_code) != expected_codes:
        raise FixtureValidationError(
            f"{TARGET_ACTIVITY_CODE} must contain exactly these versions: {sorted(expected_codes)}."
        )

    return {
        "codigo_atividade": TARGET_ACTIVITY_CODE,
        "nome_canonico": nome_canonico,
        "descricao": descricao,
        "status": "ativo",
        "grupo": grupo,
        "versions_by_code": versions_by_code,
    }


def _fetch_rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def _fetch_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        table_name: int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
        for table_name in COUNT_TABLES
    }


def collect_current_state(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "counts": _fetch_counts(conn),
        "normas": _fetch_rows(
            conn,
            """
            SELECT id, codigo, eixo, revisao, nome, descricao, status, created_at
              FROM norma_atividade
             ORDER BY id
            """,
        ),
        "bases": _fetch_rows(
            conn,
            """
            SELECT id, nome_conceito, descricao, status, created_at
              FROM atividade_base
             ORDER BY id
            """,
        ),
        "protected_versions_1_59": _fetch_rows(
            conn,
            """
            SELECT *
              FROM atividade_versao
             WHERE id BETWEEN 1 AND 59
             ORDER BY id
            """,
        ),
        "transicoes": _fetch_rows(
            conn,
            """
            SELECT *
              FROM atividade_transicao
             ORDER BY id
            """,
        ),
        "matrix_links": _fetch_rows(
            conn,
            """
            SELECT *
              FROM matriz_atividade_versao_item
             ORDER BY id
            """,
        ),
        "requisicoes": _fetch_rows(
            conn,
            """
            SELECT *
              FROM requisicoes
             ORDER BY id
            """,
        ),
        "runtime_snapshot": _fetch_rows(
            conn,
            """
            SELECT
                av.id,
                av.atividade_base_id,
                ab.nome_conceito AS base_nome,
                av.norma_id,
                n.codigo AS norma_codigo,
                av.status,
                av.eixo
              FROM atividade_versao av
              JOIN atividade_base ab ON ab.id = av.atividade_base_id
              JOIN norma_atividade n ON n.id = av.norma_id
             WHERE n.codigo LIKE 'NRM-RT%' OR ab.nome_conceito LIKE 'Runtime Base%'
             ORDER BY av.id
            """,
        ),
    }


def _resolve_target_normas(current_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    norms_by_code = {row["codigo"]: row for row in current_state["normas"]}
    resolved: dict[str, dict[str, Any]] = {}
    expected_ids = {"AAC-rev5": 1, "AAC-rev6": 2}
    for code in TARGET_NORMA_CODES:
        row = norms_by_code.get(code)
        if row is None:
            raise StateConflictError(f"Required norm missing in database: {code}")
        if row["status"] != "ativa":
            raise StateConflictError(f"Required norm is not active: {code}")
        if row["eixo"] != "AAC":
            raise StateConflictError(f"Required norm has unexpected eixo for {code}: {row['eixo']}")
        if row["id"] != expected_ids[code]:
            raise StateConflictError(
                f"Required norm {code} has unexpected id {row['id']} (expected {expected_ids[code]})."
            )
        resolved[code] = row
    return resolved


def _find_equivalent_bases(current_state: dict[str, Any], target_name: str) -> list[dict[str, Any]]:
    normalized_target = normalize_name(target_name)
    target_casefold = target_name.casefold()
    matches: list[dict[str, Any]] = []
    for base in current_state["bases"]:
        reasons: list[str] = []
        base_name = base["nome_conceito"]
        if base_name == target_name:
            reasons.append("exact")
        if base_name.casefold() == target_casefold:
            reasons.append("case_insensitive")
        if normalize_name(base_name) == normalized_target:
            reasons.append("normalized")
        if reasons:
            matches.append({**base, "match_types": reasons})
    return matches


def _fetch_versions_for_base(conn: sqlite3.Connection, base_id: int) -> list[dict[str, Any]]:
    return _fetch_rows(
        conn,
        """
        SELECT
            av.id,
            av.atividade_base_id,
            av.norma_id,
            av.codigo_normativo,
            av.eixo,
            av.grupo,
            av.ch_por_evento,
            av.limite_semestre,
            av.limite_total,
            av.observacao_aluno,
            av.observacao_admin,
            av.documentos_json,
            av.vigencia_inicio,
            av.vigencia_fim,
            av.status,
            av.versao_anterior_id,
            av.created_at,
            n.codigo AS norma_codigo
          FROM atividade_versao av
          JOIN norma_atividade n ON n.id = av.norma_id
         WHERE av.atividade_base_id = ?
         ORDER BY av.id
        """,
        (base_id,),
    )


def _build_expected_versions(
    fixture_entry: dict[str, Any],
    resolved_norms: dict[str, dict[str, Any]],
    *,
    base_id: int,
) -> dict[str, dict[str, Any]]:
    expected: dict[str, dict[str, Any]] = {}
    for code in TARGET_NORMA_CODES:
        version_data = fixture_entry["versions_by_code"][code]
        norm_row = resolved_norms[code]
        expected[code] = {
            "atividade_base_id": base_id,
            "norma_id": norm_row["id"],
            "codigo_normativo": code,
            "eixo": norm_row["eixo"],
            "grupo": fixture_entry["grupo"],
            "ch_por_evento": version_data["ch_por_evento"],
            "limite_semestre": version_data["limite_semestre"],
            "limite_total": version_data["limite_total"],
            "observacao_aluno": version_data["observacao_aluno"],
            "observacao_admin": version_data["observacao_admin"],
            "documentos_json": None,
            "vigencia_inicio": None,
            "vigencia_fim": None,
            "status": "rascunho",
            "versao_anterior_id": None,
        }
    return expected


def _validate_existing_versions_exact(
    versions: list[dict[str, Any]],
    expected_versions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if len(versions) != 2:
        raise StateConflictError(
            "Partial/conflicting state detected: target base exists without exactly 2 versions."
        )
    versions_by_code = {row["norma_codigo"]: row for row in versions}
    if set(versions_by_code) != set(TARGET_NORMA_CODES):
        raise StateConflictError(
            "Partial/conflicting state detected: target base versions do not map exactly to AAC-rev5/AAC-rev6."
        )
    for code, expected in expected_versions.items():
        actual = versions_by_code[code]
        for field, expected_value in expected.items():
            if actual[field] != expected_value:
                raise StateConflictError(
                    "Conflicting existing version detected for "
                    f"{code}: field {field}={actual[field]!r} (expected {expected_value!r})."
                )
    return versions_by_code


def build_plan(
    conn: sqlite3.Connection,
    current_state: dict[str, Any],
    fixture_entry: dict[str, Any],
) -> dict[str, Any]:
    resolved_norms = _resolve_target_normas(current_state)
    equivalent_bases = _find_equivalent_bases(current_state, fixture_entry["nome_canonico"])
    warnings: list[str] = []

    prohibited_candidates = {
        base["id"]: base["nome_conceito"]
        for base in current_state["bases"]
        if base["id"] in (6, 7)
    }
    if 6 in prohibited_candidates or 7 in prohibited_candidates:
        warnings.append(
            "base6/base7 exist and were treated as prohibited candidates, never as destination."
        )

    if not equivalent_bases:
        planned_actions = [
            {
                "action": "insert",
                "table": "atividade_base",
                "codigo_atividade": TARGET_ACTIVITY_CODE,
                "payload": {
                    "nome_conceito": fixture_entry["nome_canonico"],
                    "descricao": fixture_entry["descricao"],
                    "status": "ativo",
                },
            }
        ]
        for code in TARGET_NORMA_CODES:
            planned_actions.append(
                {
                    "action": "insert",
                    "table": "atividade_versao",
                    "codigo_atividade": TARGET_ACTIVITY_CODE,
                    "norma_codigo": code,
                    "payload": {
                        "codigo_normativo": code,
                        "eixo": resolved_norms[code]["eixo"],
                        "grupo": fixture_entry["grupo"],
                        "ch_por_evento": fixture_entry["versions_by_code"][code]["ch_por_evento"],
                        "limite_semestre": fixture_entry["versions_by_code"][code]["limite_semestre"],
                        "limite_total": fixture_entry["versions_by_code"][code]["limite_total"],
                        "observacao_aluno": fixture_entry["versions_by_code"][code]["observacao_aluno"],
                        "observacao_admin": fixture_entry["versions_by_code"][code]["observacao_admin"],
                        "status": "rascunho",
                        "documentos_json": None,
                    },
                }
            )
        projected_after_counts = dict(current_state["counts"])
        projected_after_counts["atividade_base"] += 1
        projected_after_counts["atividade_versao"] += 2
        return {
            "disposition": "create",
            "warnings": warnings,
            "resolved_norms": resolved_norms,
            "equivalent_bases": [],
            "planned_actions": planned_actions,
            "planned_counts": {"atividade_base": 1, "atividade_versao": 2},
            "projected_after_counts": projected_after_counts,
        }

    if len(equivalent_bases) != 1:
        raise StateConflictError(
            "Conflicting equivalent bases detected for the target activity: "
            + ", ".join(str(base["id"]) for base in equivalent_bases)
        )

    base = equivalent_bases[0]
    if "exact" not in base["match_types"]:
        raise StateConflictError(
            "Equivalent base exists only by case-insensitive/normalized comparison; refusing to create duplicate."
        )
    if base["descricao"] != fixture_entry["descricao"] or base["status"] != "ativo":
        raise StateConflictError(
            "Existing exact target base is conflicting in description or status."
        )

    versions = _fetch_versions_for_base(conn, base["id"])
    expected_versions = _build_expected_versions(
        fixture_entry,
        resolved_norms,
        base_id=base["id"],
    )
    versions_by_code = _validate_existing_versions_exact(versions, expected_versions)
    return {
        "disposition": "already_exists",
        "warnings": warnings,
        "resolved_norms": resolved_norms,
        "equivalent_bases": equivalent_bases,
        "planned_actions": [],
        "planned_counts": {"atividade_base": 0, "atividade_versao": 0},
        "projected_after_counts": dict(current_state["counts"]),
        "existing_ids": {
            "atividade_base": base["id"],
            "atividade_versao": [versions_by_code[code]["id"] for code in TARGET_NORMA_CODES],
        },
    }


def validate_preconditions(
    *,
    args: argparse.Namespace,
    live_db_path: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    fixture_data = load_fixture(args.fixture)
    fixture_entry = find_visitas_fixture_entry(fixture_data)
    report["file_signatures"]["db_target_before"] = file_signature(args.db_copy)

    if args.mode == "apply":
        if args.backup_path is None:
            raise GuardRailError("--apply refused: --backup-path is required.")
        if not args.backup_confirmed:
            raise GuardRailError("--apply refused: --backup-confirmed is required.")
        if not args.allow_create_visitas_professores:
            raise GuardRailError(
                "--apply refused: --allow-create-visitas-professores is required."
            )
        backup_resolved = args.backup_path.resolve()
        if not backup_resolved.exists():
            raise GuardRailError(f"--apply refused: backup path does not exist: {backup_resolved}")
        if backup_resolved == args.db_copy.resolve():
            raise GuardRailError("--apply refused: --backup-path must differ from --db-copy.")
        report["file_signatures"]["backup"] = file_signature(args.backup_path)
    else:
        report["file_signatures"]["backup"] = None

    conn: sqlite3.Connection | None = None
    try:
        if args.mode == "plan":
            conn = connect_readonly(args.db_copy)
            report["read_only_connection"] = True
        else:
            conn = connect_apply_copy(args.db_copy, live_db_path=live_db_path)
            report["read_only_connection"] = False
        current_state = collect_current_state(conn)
        plan = build_plan(conn, current_state, fixture_entry)
        report["before_counts"] = current_state["counts"]
        report["planned_actions"] = plan["planned_actions"]
        report["planned_counts"] = plan["planned_counts"]
        report["projected_after_counts"] = plan["projected_after_counts"]
        report["warnings"].extend(plan["warnings"])
        if args.strict and report["warnings"]:
            raise GuardRailError("Strict mode refused warnings:\n- " + "\n- ".join(report["warnings"]))
        return {
            "conn": conn,
            "current_state": current_state,
            "fixture_entry": fixture_entry,
            "plan": plan,
        }
    except Exception:
        if conn is not None:
            conn.close()
        raise


def apply_create_draft(
    conn: sqlite3.Connection,
    *,
    fixture_entry: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    if plan["disposition"] == "already_exists":
        return {
            "noop": True,
            "created_ids": {"atividade_base": None, "atividade_versao": []},
            "existing_ids": plan["existing_ids"],
        }

    cursor = conn.execute(
        """
        INSERT INTO atividade_base (nome_conceito, descricao, status)
        VALUES (?, ?, 'ativo')
        """,
        (fixture_entry["nome_canonico"], fixture_entry["descricao"]),
    )
    base_id = int(cursor.lastrowid)
    created_version_ids: list[int] = []
    expected_versions = _build_expected_versions(
        fixture_entry,
        plan["resolved_norms"],
        base_id=base_id,
    )
    for idx, code in enumerate(TARGET_NORMA_CODES, start=1):
        payload = expected_versions[code]
        version_cursor = conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id,
                norma_id,
                codigo_normativo,
                eixo,
                grupo,
                ch_por_evento,
                limite_semestre,
                limite_total,
                observacao_aluno,
                observacao_admin,
                documentos_json,
                vigencia_inicio,
                vigencia_fim,
                numero_versao,
                status,
                versao_anterior_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rascunho', NULL)
            """,
            (
                payload["atividade_base_id"],
                payload["norma_id"],
                payload["codigo_normativo"],
                payload["eixo"],
                payload["grupo"],
                payload["ch_por_evento"],
                payload["limite_semestre"],
                payload["limite_total"],
                payload["observacao_aluno"],
                payload["observacao_admin"],
                payload["documentos_json"],
                payload["vigencia_inicio"],
                payload["vigencia_fim"],
                idx,
            ),
        )
        created_version_ids.append(int(version_cursor.lastrowid))

    return {
        "noop": False,
        "created_ids": {
            "atividade_base": base_id,
            "atividade_versao": created_version_ids,
        },
        "existing_ids": None,
    }


def validate_postconditions(
    *,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    fixture_entry: dict[str, Any],
    plan: dict[str, Any],
    apply_result: dict[str, Any],
) -> None:
    before_counts = before_state["counts"]
    after_counts = after_state["counts"]
    expected_delta = {
        "atividade_base": 0 if apply_result["noop"] else 1,
        "atividade_versao": 0 if apply_result["noop"] else 2,
        "norma_atividade": 0,
        "atividade_transicao": 0,
        "matriz_atividade_versao_item": 0,
        "requisicoes": 0,
    }
    for table_name, before_count in before_counts.items():
        actual_delta = after_counts[table_name] - before_count
        if actual_delta != expected_delta[table_name]:
            raise PostconditionError(
                f"Unexpected delta for {table_name}: {actual_delta} (expected {expected_delta[table_name]})."
            )

    for snapshot_name in (
        "normas",
        "protected_versions_1_59",
        "transicoes",
        "matrix_links",
        "requisicoes",
        "runtime_snapshot",
    ):
        if before_state[snapshot_name] != after_state[snapshot_name]:
            raise PostconditionError(f"Out-of-scope data changed in snapshot: {snapshot_name}")

    target_matches = _find_equivalent_bases(after_state, fixture_entry["nome_canonico"])
    if len(target_matches) != 1:
        raise PostconditionError("Post-apply target base state is invalid or ambiguous.")

    expected_versions = _build_expected_versions(
        fixture_entry,
        plan["resolved_norms"],
        base_id=target_matches[0]["id"],
    )
    versions = _fetch_versions_for_base_from_state(after_state, target_matches[0]["id"])
    versions_by_code = _validate_existing_versions_exact(versions, expected_versions)

    if not apply_result["noop"]:
        created_base_id = apply_result["created_ids"]["atividade_base"]
        created_version_ids = apply_result["created_ids"]["atividade_versao"]
        if target_matches[0]["id"] != created_base_id:
            raise PostconditionError("Created base id does not match the resolved post-apply base.")
        expected_created_version_ids = [versions_by_code[code]["id"] for code in TARGET_NORMA_CODES]
        if expected_created_version_ids != created_version_ids:
            raise PostconditionError("Created version ids do not match the resolved post-apply versions.")


def _fetch_versions_for_base_from_state(current_state: dict[str, Any], base_id: int) -> list[dict[str, Any]]:
    versions = current_state.get("all_versions")
    if versions is None:
        raise PostconditionError("Missing all_versions snapshot in current state.")
    return [row for row in versions if row["atividade_base_id"] == base_id]


def _augment_state_with_all_versions(conn: sqlite3.Connection, state: dict[str, Any]) -> dict[str, Any]:
    state["all_versions"] = _fetch_rows(
        conn,
        """
        SELECT
            av.id,
            av.atividade_base_id,
            av.norma_id,
            av.codigo_normativo,
            av.eixo,
            av.grupo,
            av.ch_por_evento,
            av.limite_semestre,
            av.limite_total,
            av.observacao_aluno,
            av.observacao_admin,
            av.documentos_json,
            av.vigencia_inicio,
            av.vigencia_fim,
            av.status,
            av.versao_anterior_id,
            av.created_at,
            n.codigo AS norma_codigo
          FROM atividade_versao av
          JOIN norma_atividade n ON n.id = av.norma_id
         ORDER BY av.id
        """,
    )
    return state


def emit_text_report(report: dict[str, Any]) -> str:
    created_ids = report.get("created_ids") or {"atividade_base": None, "atividade_versao": []}
    lines = [
        f"Status: {report['status']}",
        f"Mode: {report['mode']}",
        f"Disposition: {report.get('disposition', 'unknown')}",
        f"Fixture: {report['fixture']}",
        f"DB target: {report['db_copy']}",
        f"Read-only connection: {report.get('read_only_connection')}",
        (
            "Planned counts: "
            f"atividade_base={report['planned_counts']['atividade_base']}, "
            f"atividade_versao={report['planned_counts']['atividade_versao']}"
        ),
        f"Before counts: {json.dumps(report['before_counts'], ensure_ascii=False, sort_keys=True)}",
        f"After counts: {json.dumps(report['after_counts'], ensure_ascii=False, sort_keys=True)}",
        f"Created IDs: {json.dumps(created_ids, ensure_ascii=False, sort_keys=True)}",
        f"No-op: {report.get('noop', False)}",
    ]
    if report["planned_actions"]:
        lines.append(f"Planned actions ({len(report['planned_actions'])}):")
        for action in report["planned_actions"]:
            lines.append(
                f"- {action['action']} {action['table']} "
                f"{action.get('norma_codigo', action.get('codigo_atividade', ''))}".strip()
            )
    else:
        lines.append("Planned actions: none")
    if report["warnings"]:
        lines.append(f"Warnings ({len(report['warnings'])}):")
        lines.extend(f"- {warning}" for warning in report["warnings"])
    else:
        lines.append("Warnings: none")
    if report["errors"]:
        lines.append(f"Errors ({len(report['errors'])}):")
        lines.extend(f"- {error}" for error in report["errors"])
    else:
        lines.append("Errors: none")
    return "\n".join(lines)


def emit_json_report(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


def _error_payload(
    *,
    args: argparse.Namespace | None,
    message: str,
) -> str:
    payload = {
        "status": "error",
        "mode": getattr(args, "mode", None),
        "fixture": str(args.fixture.resolve()) if args and getattr(args, "fixture", None) else None,
        "db_copy": str(args.db_copy.resolve()) if args and getattr(args, "db_copy", None) else None,
        "errors": [message],
    }
    if args is not None and args.report == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return "Status: error\nErrors (1):\n- " + message


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    live_db_path = Path(__file__).resolve().parents[1] / LIVE_DB_BASENAME
    report: dict[str, Any] = {
        "status": "ok",
        "mode": args.mode,
        "fixture": str(args.fixture.resolve()),
        "db_copy": str(args.db_copy.resolve()),
        "planned_actions": [],
        "planned_counts": {"atividade_base": 0, "atividade_versao": 0},
        "projected_after_counts": {},
        "disposition": None,
        "created_ids": {"atividade_base": None, "atividade_versao": []},
        "before_counts": {},
        "after_counts": {},
        "final_counts": {},
        "file_signatures": {"db_target_before": None, "db_target_after": None, "backup": None},
        "warnings": [],
        "errors": [],
        "noop": False,
        "read_only_connection": None,
    }

    try:
        validated = validate_preconditions(args=args, live_db_path=live_db_path, report=report)
        conn: sqlite3.Connection = validated["conn"]
        try:
            before_state = _augment_state_with_all_versions(conn, validated["current_state"])
            plan = validated["plan"]
            fixture_entry = validated["fixture_entry"]
            report["disposition"] = plan["disposition"]

            if args.mode == "plan":
                after_state = before_state
                report["after_counts"] = dict(after_state["counts"])
                report["final_counts"] = dict(after_state["counts"])
            else:
                if plan["disposition"] == "already_exists":
                    apply_result = apply_create_draft(conn, fixture_entry=fixture_entry, plan=plan)
                    report["noop"] = True
                    report["created_ids"] = apply_result["created_ids"]
                    after_state = _augment_state_with_all_versions(conn, collect_current_state(conn))
                    validate_postconditions(
                        before_state=before_state,
                        after_state=after_state,
                        fixture_entry=fixture_entry,
                        plan=plan,
                        apply_result=apply_result,
                    )
                    report["after_counts"] = dict(after_state["counts"])
                    report["final_counts"] = dict(after_state["counts"])
                else:
                    try:
                        with conn:
                            apply_result = apply_create_draft(
                                conn,
                                fixture_entry=fixture_entry,
                                plan=plan,
                            )
                            after_state = _augment_state_with_all_versions(
                                conn,
                                collect_current_state(conn),
                            )
                            validate_postconditions(
                                before_state=before_state,
                                after_state=after_state,
                                fixture_entry=fixture_entry,
                                plan=plan,
                                apply_result=apply_result,
                            )
                    except Exception:
                        conn.rollback()
                        raise
                    report["noop"] = apply_result["noop"]
                    report["created_ids"] = apply_result["created_ids"]
                    report["after_counts"] = dict(after_state["counts"])
                    report["final_counts"] = dict(after_state["counts"])
        finally:
            conn.close()

        report["file_signatures"]["db_target_after"] = file_signature(args.db_copy)
        if args.mode == "plan":
            if report["file_signatures"]["db_target_before"] != report["file_signatures"]["db_target_after"]:
                raise PostconditionError("Plan mode altered the inspected database file signature.")
        output = emit_json_report(report) if args.report == "json" else emit_text_report(report)
        print(output)
        return 0
    except ReconciliationApplyError as exc:
        print(_error_payload(args=args, message=str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
