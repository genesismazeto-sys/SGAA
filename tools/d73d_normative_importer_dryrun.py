from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

import yaml


APPROVED_CH_RULES = {
    None,
    "equivalente_curso",
    "equivalente_horas",
    "tempo_declarado_ou_limite",
    "carga_declarada_ou_limite_evento",
    "tier_documental",
    "horas_por_evento",
    "horas_por_banca",
    "regra_especial_ivao",
    "exige_decisao_humana",
}

ALLOWED_EIXOS = {"AAC", "AEU"}
ALLOWED_NORMA_STATUS = {"ativa", "inativa"}
ALLOWED_VERSAO_STATUS = {"rascunho", "ativa", "inativa", "descontinuada", "substituida"}
ALLOWED_TRANSITION_TYPES = {"mesmo_eixo", "aac_para_aeu", "nova_aeu", "descontinuada", "sem_transicao"}
REAL_DB_BASENAME = "database.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS atividade_base (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_conceito TEXT NOT NULL UNIQUE,
    descricao TEXT,
    status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo', 'inativo')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS norma_atividade (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    eixo TEXT NOT NULL CHECK(eixo IN ('AAC', 'AEU')),
    revisao TEXT NOT NULL,
    nome TEXT,
    descricao TEXT,
    status TEXT NOT NULL DEFAULT 'ativa' CHECK(status IN ('ativa', 'inativa')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS atividade_versao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    atividade_base_id INTEGER NOT NULL,
    norma_id INTEGER NOT NULL,
    codigo_normativo TEXT NOT NULL,
    eixo TEXT NOT NULL CHECK(eixo IN ('AAC', 'AEU')),
    grupo TEXT,
    ch_por_evento REAL,
    limite_semestre REAL,
    limite_total REAL,
    observacao_aluno TEXT,
    observacao_admin TEXT,
    documentos_json TEXT,
    vigencia_inicio TEXT,
    vigencia_fim TEXT,
    status TEXT NOT NULL DEFAULT 'rascunho' CHECK(status IN ('rascunho', 'ativa', 'inativa', 'descontinuada', 'substituida')),
    versao_anterior_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(atividade_base_id) REFERENCES atividade_base(id) ON DELETE RESTRICT,
    FOREIGN KEY(norma_id) REFERENCES norma_atividade(id) ON DELETE RESTRICT,
    FOREIGN KEY(versao_anterior_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
    UNIQUE(atividade_base_id, norma_id)
);

CREATE TABLE IF NOT EXISTS atividade_transicao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_atividade_versao_id INTEGER,
    to_atividade_versao_id INTEGER,
    tipo_transicao TEXT NOT NULL CHECK(tipo_transicao IN ('mesmo_eixo', 'aac_para_aeu', 'nova_aeu', 'descontinuada', 'sem_transicao')),
    justificativa TEXT,
    observacao_admin TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(from_atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
    FOREIGN KEY(to_atividade_versao_id) REFERENCES atividade_versao(id) ON DELETE RESTRICT,
    CHECK(from_atividade_versao_id IS NOT NULL OR to_atividade_versao_id IS NOT NULL),
    CHECK(from_atividade_versao_id IS NULL OR to_atividade_versao_id IS NULL OR from_atividade_versao_id <> to_atividade_versao_id)
);

CREATE TRIGGER IF NOT EXISTS trg_atividade_versao_eixo_norma_insert
BEFORE INSERT ON atividade_versao
FOR EACH ROW
WHEN NEW.norma_id IS NOT NULL
     AND EXISTS(SELECT 1 FROM norma_atividade n WHERE n.id = NEW.norma_id AND n.eixo <> NEW.eixo)
BEGIN
    SELECT RAISE(ABORT, 'atividade_versao.eixo incompatível com norma_atividade.eixo');
END;

CREATE TRIGGER IF NOT EXISTS trg_atividade_versao_eixo_norma_update
BEFORE UPDATE OF norma_id, eixo ON atividade_versao
FOR EACH ROW
WHEN NEW.norma_id IS NOT NULL
     AND EXISTS(SELECT 1 FROM norma_atividade n WHERE n.id = NEW.norma_id AND n.eixo <> NEW.eixo)
BEGIN
    SELECT RAISE(ABORT, 'atividade_versao.eixo incompatível com norma_atividade.eixo');
END;

CREATE TRIGGER IF NOT EXISTS trg_atividade_versao_prev_same_eixo_insert
BEFORE INSERT ON atividade_versao
FOR EACH ROW
WHEN NEW.versao_anterior_id IS NOT NULL
     AND EXISTS(
         SELECT 1
           FROM atividade_versao prev
          WHERE prev.id = NEW.versao_anterior_id
            AND prev.eixo <> NEW.eixo
     )
BEGIN
    SELECT RAISE(ABORT, 'Mudança de eixo não pode ocorrer via versao_anterior_id; registre em atividade_transicao');
END;

CREATE TRIGGER IF NOT EXISTS trg_atividade_versao_prev_same_eixo_update
BEFORE UPDATE OF versao_anterior_id, eixo ON atividade_versao
FOR EACH ROW
WHEN NEW.versao_anterior_id IS NOT NULL
     AND EXISTS(
         SELECT 1
           FROM atividade_versao prev
          WHERE prev.id = NEW.versao_anterior_id
            AND prev.eixo <> NEW.eixo
     )
BEGIN
    SELECT RAISE(ABORT, 'Mudança de eixo não pode ocorrer via versao_anterior_id; registre em atividade_transicao');
END;

CREATE TRIGGER IF NOT EXISTS trg_atividade_transicao_aac_para_aeu_insert
BEFORE INSERT ON atividade_transicao
FOR EACH ROW
WHEN NEW.tipo_transicao = 'aac_para_aeu'
BEGIN
    SELECT CASE
        WHEN NEW.justificativa IS NULL OR TRIM(NEW.justificativa) = ''
        THEN RAISE(ABORT, 'Transição aac_para_aeu exige justificativa')
    END;
    SELECT CASE
        WHEN NEW.from_atividade_versao_id IS NULL OR NEW.to_atividade_versao_id IS NULL
        THEN RAISE(ABORT, 'Transição aac_para_aeu exige from/to atividade_versao')
    END;
    SELECT CASE
        WHEN (SELECT eixo FROM atividade_versao WHERE id = NEW.from_atividade_versao_id) <> 'AAC'
             OR (SELECT eixo FROM atividade_versao WHERE id = NEW.to_atividade_versao_id) <> 'AEU'
        THEN RAISE(ABORT, 'Transição aac_para_aeu exige eixo AAC -> AEU')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_atividade_transicao_aac_para_aeu_update
BEFORE UPDATE OF tipo_transicao, justificativa, from_atividade_versao_id, to_atividade_versao_id
ON atividade_transicao
FOR EACH ROW
WHEN NEW.tipo_transicao = 'aac_para_aeu'
BEGIN
    SELECT CASE
        WHEN NEW.justificativa IS NULL OR TRIM(NEW.justificativa) = ''
        THEN RAISE(ABORT, 'Transição aac_para_aeu exige justificativa')
    END;
    SELECT CASE
        WHEN NEW.from_atividade_versao_id IS NULL OR NEW.to_atividade_versao_id IS NULL
        THEN RAISE(ABORT, 'Transição aac_para_aeu exige from/to atividade_versao')
    END;
    SELECT CASE
        WHEN (SELECT eixo FROM atividade_versao WHERE id = NEW.from_atividade_versao_id) <> 'AAC'
             OR (SELECT eixo FROM atividade_versao WHERE id = NEW.to_atividade_versao_id) <> 'AEU'
        THEN RAISE(ABORT, 'Transição aac_para_aeu exige eixo AAC -> AEU')
    END;
END;
"""


class DryRunImporterError(Exception):
    """Base error for the dry-run importer."""


class FixtureValidationError(DryRunImporterError):
    """Raised when the fixture is invalid."""


class GuardRailError(DryRunImporterError):
    """Raised when the dry-run is pointed at a forbidden database target."""


def _normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(normalized.casefold().split())


def _has_human_decision_marker(value: str | None) -> bool:
    return "exige decisao humana" in _normalize_text(value)


def _require_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FixtureValidationError(f"{context} deve ser um objeto YAML.")
    return value


def _require_list(value: Any, *, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise FixtureValidationError(f"{context} deve ser uma lista YAML.")
    return value


def _require_non_empty_string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureValidationError(f"{context} deve ser uma string não vazia.")
    return value.strip()


def _ensure_safe_db_path(db_path: Path) -> None:
    if db_path.name.casefold() == REAL_DB_BASENAME:
        raise GuardRailError(
            f"Dry-run recusado: --db não pode apontar para '{REAL_DB_BASENAME}'. "
            f"Recebido: {db_path}"
        )


def _load_fixture(fixture_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not fixture_path.exists():
        raise FixtureValidationError(f"Fixture não encontrada: {fixture_path}")

    try:
        raw_data = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FixtureValidationError(f"Falha ao fazer parse do YAML: {exc}") from exc

    data = _require_mapping(raw_data, context="Top-level da fixture")
    required_top_level = {"meta", "normas", "atividades"}
    missing = sorted(required_top_level - data.keys())
    if missing:
        raise FixtureValidationError(
            "Top-level da fixture deve conter as chaves obrigatórias: "
            + ", ".join(required_top_level)
            + f". Ausentes: {', '.join(missing)}."
        )

    _require_mapping(data["meta"], context="meta")
    normas = _require_list(data["normas"], context="normas")
    atividades = _require_list(data["atividades"], context="atividades")

    norma_by_code: dict[str, dict[str, Any]] = {}
    for index, raw_norma in enumerate(normas, start=1):
        norma = _require_mapping(raw_norma, context=f"normas[{index}]")
        codigo = _require_non_empty_string(norma.get("codigo"), context=f"normas[{index}].codigo")
        if codigo in norma_by_code:
            raise FixtureValidationError(f"normas[].codigo duplicado: {codigo}")
        eixo = _require_non_empty_string(norma.get("eixo"), context=f"normas[{index}].eixo")
        if eixo not in ALLOWED_EIXOS:
            raise FixtureValidationError(f"normas[{index}].eixo inválido: {eixo}")
        revisao = _require_non_empty_string(norma.get("revisao"), context=f"normas[{index}].revisao")
        nome = _require_non_empty_string(norma.get("nome"), context=f"normas[{index}].nome")
        status = _require_non_empty_string(norma.get("status"), context=f"normas[{index}].status")
        if status not in ALLOWED_NORMA_STATUS:
            raise FixtureValidationError(f"normas[{index}].status inválido: {status}")
        norma_by_code[codigo] = {
            "codigo": codigo,
            "eixo": eixo,
            "revisao": revisao,
            "nome": nome,
            "status": status,
        }

    warnings: list[str] = []
    removed_activities: list[dict[str, Any]] = []
    new_activities: list[dict[str, Any]] = []
    activity_name_keys: set[str] = set()
    activity_code_keys: set[str] = set()

    for activity_index, raw_activity in enumerate(atividades, start=1):
        activity = _require_mapping(raw_activity, context=f"atividades[{activity_index}]")
        codigo_atividade = _require_non_empty_string(
            activity.get("codigo_atividade"),
            context=f"atividades[{activity_index}].codigo_atividade",
        )
        if codigo_atividade in activity_code_keys:
            raise FixtureValidationError(f"atividades[].codigo_atividade duplicado: {codigo_atividade}")
        activity_code_keys.add(codigo_atividade)

        nome_canonico = _require_non_empty_string(
            activity.get("nome_canonico"),
            context=f"atividades[{activity_index}].nome_canonico",
        )
        name_key = _normalize_text(nome_canonico)
        if name_key in activity_name_keys:
            raise FixtureValidationError(
                f"atividades[].nome_canonico duplicado (case-insensitive): {nome_canonico}"
            )
        activity_name_keys.add(name_key)

        _require_non_empty_string(activity.get("grupo"), context=f"atividades[{activity_index}].grupo")
        _require_non_empty_string(activity.get("descricao"), context=f"atividades[{activity_index}].descricao")

        versions = _require_list(activity.get("versoes"), context=f"atividades[{activity_index}].versoes")
        if not versions:
            raise FixtureValidationError(f"atividades[{activity_index}].versoes não pode ser vazia.")

        versions_by_norma: dict[str, dict[str, Any]] = {}
        version_norm_refs: list[str] = []
        for version_index, raw_version in enumerate(versions, start=1):
            version = _require_mapping(
                raw_version,
                context=f"atividades[{activity_index}].versoes[{version_index}]",
            )
            version_context = f"atividades[{activity_index}].versoes[{version_index}]"
            norma_ref = _require_non_empty_string(version.get("norma_ref"), context=f"{version_context}.norma_ref")
            if norma_ref not in norma_by_code:
                raise FixtureValidationError(
                    f"{version_context}.norma_ref referencia norma inexistente: {norma_ref}"
                )
            if norma_ref in versions_by_norma:
                raise FixtureValidationError(
                    f"{version_context}.norma_ref duplicada dentro da atividade {codigo_atividade}: {norma_ref}"
                )
            versions_by_norma[norma_ref] = version
            version_norm_refs.append(norma_ref)

            status_inicial = _require_non_empty_string(
                version.get("status_inicial"),
                context=f"{version_context}.status_inicial",
            )
            if status_inicial not in ALLOWED_VERSAO_STATUS:
                raise FixtureValidationError(f"{version_context}.status_inicial inválido: {status_inicial}")

            rule = version.get("ch_regra_condicional")
            if rule not in APPROVED_CH_RULES:
                raise FixtureValidationError(
                    f"{version_context}.ch_regra_condicional inválido: {rule!r}"
                )

            if "documentacao_exigida" in version and not str(version.get("documentacao_exigida") or "").strip():
                raise FixtureValidationError(f"{version_context}.documentacao_exigida não pode ser vazia.")

            if _has_human_decision_marker(version.get("observacao_admin")):
                warnings.append(
                    f"Atividade {codigo_atividade} / {norma_ref} marcada como exige decisao humana."
                )

        removed_in = activity.get("atividade_removida_em") or []
        removed_in = _require_list(removed_in, context=f"atividades[{activity_index}].atividade_removida_em")
        for norma_code in removed_in:
            norma_code = _require_non_empty_string(
                norma_code,
                context=f"atividades[{activity_index}].atividade_removida_em[]",
            )
            if norma_code not in norma_by_code:
                raise FixtureValidationError(
                    f"atividade_removida_em referencia norma inexistente: {norma_code}"
                )
            if norma_code in versions_by_norma:
                raise FixtureValidationError(
                    f"Atividade {codigo_atividade} foi marcada como removida em {norma_code}, "
                    "mas ainda possui versão nessa norma."
                )

        new_in = activity.get("atividade_nova_em") or []
        new_in = _require_list(new_in, context=f"atividades[{activity_index}].atividade_nova_em")
        new_norms = {
            _require_non_empty_string(
                norma_code,
                context=f"atividades[{activity_index}].atividade_nova_em[]",
            )
            for norma_code in new_in
        }
        for norma_code in new_norms:
            if norma_code not in norma_by_code:
                raise FixtureValidationError(
                    f"atividade_nova_em referencia norma inexistente: {norma_code}"
                )
        if new_norms:
            for norma_ref in version_norm_refs:
                if norma_ref in new_norms:
                    continue
                version = versions_by_norma[norma_ref]
                if not _has_human_decision_marker(version.get("observacao_admin")):
                    raise FixtureValidationError(
                        f"Atividade {codigo_atividade} marcada como nova em {sorted(new_norms)}, "
                        f"mas possui versão adicional em {norma_ref} sem 'exige decisao humana'."
                    )

        transition = activity.get("transicao_proposta")
        if transition is not None:
            transition = _require_mapping(
                transition,
                context=f"atividades[{activity_index}].transicao_proposta",
            )
            de = _require_non_empty_string(
                transition.get("de"),
                context=f"atividades[{activity_index}].transicao_proposta.de",
            )
            para = _require_non_empty_string(
                transition.get("para"),
                context=f"atividades[{activity_index}].transicao_proposta.para",
            )
            tipo = _require_non_empty_string(
                transition.get("tipo"),
                context=f"atividades[{activity_index}].transicao_proposta.tipo",
            )
            justificativa = _require_non_empty_string(
                transition.get("justificativa"),
                context=f"atividades[{activity_index}].transicao_proposta.justificativa",
            )
            if de not in versions_by_norma or para not in versions_by_norma:
                raise FixtureValidationError(
                    f"Transição proposta da atividade {codigo_atividade} aponta para versões inexistentes."
                )
            if tipo not in ALLOWED_TRANSITION_TYPES:
                raise FixtureValidationError(
                    f"Transição proposta da atividade {codigo_atividade} possui tipo inválido: {tipo}"
                )
            if tipo == "aac_para_aeu":
                if norma_by_code[de]["eixo"] != "AAC" or norma_by_code[para]["eixo"] != "AEU":
                    raise FixtureValidationError(
                        f"Transição aac_para_aeu da atividade {codigo_atividade} deve ligar AAC -> AEU."
                    )
            transition["justificativa"] = justificativa

        if removed_in:
            removed_activities.append(
                {
                    "codigo_atividade": codigo_atividade,
                    "nome_canonico": nome_canonico,
                    "normas": sorted(removed_in),
                }
            )
        if new_norms:
            new_activities.append(
                {
                    "codigo_atividade": codigo_atividade,
                    "nome_canonico": nome_canonico,
                    "normas": sorted(new_norms),
                }
            )

    summary = {
        "warnings": warnings,
        "removed_activities": removed_activities,
        "new_activities": new_activities,
        "fixture_counts": {
            "normas": len(normas),
            "atividades": len(atividades),
            "versoes": sum(len(activity.get("versoes", [])) for activity in atividades),
            "transicoes": sum(1 for activity in atividades if activity.get("transicao_proposta")),
        },
    }
    return data, summary


def _connect_sqlite(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def _assert_existing_row_matches(
    row: sqlite3.Row,
    expected: dict[str, Any],
    *,
    table_name: str,
    natural_key: str,
) -> None:
    mismatches: list[str] = []
    for field, expected_value in expected.items():
        actual_value = row[field]
        if actual_value != expected_value:
            mismatches.append(f"{field}={actual_value!r} (esperado {expected_value!r})")
    if mismatches:
        raise DryRunImporterError(
            f"{table_name} já existe com dados divergentes para {natural_key}: "
            + "; ".join(mismatches)
        )


def _upsert_norma(conn: sqlite3.Connection, norma: dict[str, Any]) -> tuple[int, bool]:
    row = conn.execute(
        """
        SELECT id, eixo, revisao, nome, status
          FROM norma_atividade
         WHERE codigo = ?
        """,
        (norma["codigo"],),
    ).fetchone()
    expected = {
        "eixo": norma["eixo"],
        "revisao": norma["revisao"],
        "nome": norma["nome"],
        "status": norma["status"],
    }
    if row is not None:
        _assert_existing_row_matches(
            row,
            expected,
            table_name="norma_atividade",
            natural_key=norma["codigo"],
        )
        return int(row["id"]), False

    cursor = conn.execute(
        """
        INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            norma["codigo"],
            norma["eixo"],
            norma["revisao"],
            norma["nome"],
            norma["status"],
        ),
    )
    return int(cursor.lastrowid), True


def _upsert_base(conn: sqlite3.Connection, activity: dict[str, Any]) -> tuple[int, bool]:
    row = conn.execute(
        """
        SELECT id, descricao, status
          FROM atividade_base
         WHERE nome_conceito = ?
        """,
        (activity["nome_canonico"],),
    ).fetchone()
    expected = {
        "descricao": activity["descricao"],
        "status": "ativo",
    }
    if row is not None:
        _assert_existing_row_matches(
            row,
            expected,
            table_name="atividade_base",
            natural_key=activity["nome_canonico"],
        )
        return int(row["id"]), False

    cursor = conn.execute(
        """
        INSERT INTO atividade_base (nome_conceito, descricao, status)
        VALUES (?, ?, 'ativo')
        """,
        (
            activity["nome_canonico"],
            activity["descricao"],
        ),
    )
    return int(cursor.lastrowid), True


def _build_documentos_json(version: dict[str, Any]) -> str:
    payload = {
        "ch_regra_condicional": version.get("ch_regra_condicional"),
        "documentacao_exigida": version.get("documentacao_exigida"),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _upsert_versao(
    conn: sqlite3.Connection,
    *,
    atividade_base_id: int,
    norma_id: int,
    norma: dict[str, Any],
    activity: dict[str, Any],
    version: dict[str, Any],
) -> tuple[int, bool]:
    row = conn.execute(
        """
        SELECT
            id,
            codigo_normativo,
            eixo,
            grupo,
            ch_por_evento,
            limite_semestre,
            limite_total,
            observacao_aluno,
            observacao_admin,
            documentos_json,
            status,
            versao_anterior_id
          FROM atividade_versao
         WHERE atividade_base_id = ? AND norma_id = ?
        """,
        (atividade_base_id, norma_id),
    ).fetchone()
    documentos_json = _build_documentos_json(version)
    expected = {
        "codigo_normativo": norma["codigo"],
        "eixo": norma["eixo"],
        "grupo": activity["grupo"],
        "ch_por_evento": version.get("ch_por_evento"),
        "limite_semestre": version.get("limite_semestre"),
        "limite_total": version.get("limite_total"),
        "observacao_aluno": version.get("observacao_aluno"),
        "observacao_admin": version.get("observacao_admin"),
        "documentos_json": documentos_json,
        "status": version["status_inicial"],
        "versao_anterior_id": None,
    }
    if row is not None:
        _assert_existing_row_matches(
            row,
            expected,
            table_name="atividade_versao",
            natural_key=f"atividade_base_id={atividade_base_id}, norma_id={norma_id}",
        )
        return int(row["id"]), False

    cursor = conn.execute(
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
            status,
            versao_anterior_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            atividade_base_id,
            norma_id,
            norma["codigo"],
            norma["eixo"],
            activity["grupo"],
            version.get("ch_por_evento"),
            version.get("limite_semestre"),
            version.get("limite_total"),
            version.get("observacao_aluno"),
            version.get("observacao_admin"),
            documentos_json,
            version["status_inicial"],
        ),
    )
    return int(cursor.lastrowid), True


def _upsert_transition(
    conn: sqlite3.Connection,
    *,
    from_versao_id: int,
    to_versao_id: int,
    transition: dict[str, Any],
) -> tuple[int, bool]:
    row = conn.execute(
        """
        SELECT id, justificativa, observacao_admin
          FROM atividade_transicao
         WHERE from_atividade_versao_id = ?
           AND to_atividade_versao_id = ?
           AND tipo_transicao = ?
        """,
        (from_versao_id, to_versao_id, transition["tipo"]),
    ).fetchone()
    expected = {
        "justificativa": transition["justificativa"],
        "observacao_admin": None,
    }
    if row is not None:
        _assert_existing_row_matches(
            row,
            expected,
            table_name="atividade_transicao",
            natural_key=(
                f"from_atividade_versao_id={from_versao_id}, "
                f"to_atividade_versao_id={to_versao_id}, tipo={transition['tipo']}"
            ),
        )
        return int(row["id"]), False

    cursor = conn.execute(
        """
        INSERT INTO atividade_transicao (
            from_atividade_versao_id,
            to_atividade_versao_id,
            tipo_transicao,
            justificativa
        ) VALUES (?, ?, ?, ?)
        """,
        (
            from_versao_id,
            to_versao_id,
            transition["tipo"],
            transition["justificativa"],
        ),
    )
    return int(cursor.lastrowid), True


def _final_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "norma_atividade": int(conn.execute("SELECT COUNT(*) FROM norma_atividade").fetchone()[0]),
        "atividade_base": int(conn.execute("SELECT COUNT(*) FROM atividade_base").fetchone()[0]),
        "atividade_versao": int(conn.execute("SELECT COUNT(*) FROM atividade_versao").fetchone()[0]),
        "atividade_transicao": int(conn.execute("SELECT COUNT(*) FROM atividade_transicao").fetchone()[0]),
    }


def run_import(
    *,
    fixture_path: Path,
    db_path: Path | None,
    report_format: str = "text",
    strict: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    fixture_path = fixture_path.resolve()
    fixture_data, fixture_summary = _load_fixture(fixture_path)
    warnings = list(fixture_summary["warnings"])

    if strict and warnings:
        raise FixtureValidationError(
            "Modo estrito encontrou warnings:\n- " + "\n- ".join(warnings)
        )

    created_temp_db = False
    temp_db_path: Path | None = None
    if db_path is None:
        with tempfile.NamedTemporaryFile(prefix="d73d_dryrun_", suffix=".sqlite3", delete=False) as handle:
            temp_db_path = Path(handle.name)
        target_db_path = temp_db_path
        created_temp_db = True
    else:
        target_db_path = db_path.resolve()
    _ensure_safe_db_path(target_db_path)

    report = {
        "status": "ok",
        "fixture": str(fixture_path),
        "db": {
            "path": str(target_db_path),
            "temporary": created_temp_db,
            "cleaned_up": False,
        },
        "fixture_counts": fixture_summary["fixture_counts"],
        "meta": fixture_data["meta"],
        "inserted": {
            "normas": 0,
            "bases": 0,
            "versoes": 0,
            "transicoes": 0,
        },
        "skipped": {
            "normas": 0,
            "bases": 0,
            "versoes": 0,
            "transicoes": 0,
        },
        "atividades_removidas": fixture_summary["removed_activities"],
        "atividades_novas": fixture_summary["new_activities"],
        "warnings": warnings,
        "errors": [],
        "final_counts": {},
    }

    conn: sqlite3.Connection | None = None
    try:
        conn = _connect_sqlite(target_db_path)
        _ensure_schema(conn)

        norma_ids: dict[str, int] = {}
        version_ids: dict[tuple[str, str], int] = {}
        normas_by_code = {norma["codigo"]: norma for norma in fixture_data["normas"]}

        with conn:
            for norma in fixture_data["normas"]:
                norma_id, inserted = _upsert_norma(conn, norma)
                norma_ids[norma["codigo"]] = norma_id
                report["inserted" if inserted else "skipped"]["normas"] += 1

            for activity in fixture_data["atividades"]:
                base_id, inserted = _upsert_base(conn, activity)
                report["inserted" if inserted else "skipped"]["bases"] += 1
                for version in activity["versoes"]:
                    norma = normas_by_code[version["norma_ref"]]
                    versao_id, versao_inserted = _upsert_versao(
                        conn,
                        atividade_base_id=base_id,
                        norma_id=norma_ids[norma["codigo"]],
                        norma=norma,
                        activity=activity,
                        version=version,
                    )
                    version_ids[(activity["codigo_atividade"], version["norma_ref"])] = versao_id
                    report["inserted" if versao_inserted else "skipped"]["versoes"] += 1

            for activity in fixture_data["atividades"]:
                transition = activity.get("transicao_proposta")
                if not transition:
                    continue
                from_versao_id = version_ids[(activity["codigo_atividade"], transition["de"])]
                to_versao_id = version_ids[(activity["codigo_atividade"], transition["para"])]
                _, transition_inserted = _upsert_transition(
                    conn,
                    from_versao_id=from_versao_id,
                    to_versao_id=to_versao_id,
                    transition=transition,
                )
                report["inserted" if transition_inserted else "skipped"]["transicoes"] += 1

        report["final_counts"] = _final_counts(conn)
        if verbose:
            report["version_keys"] = sorted(
                f"{activity_code}:{norma_ref}" for activity_code, norma_ref in version_ids
            )
        return report
    except sqlite3.IntegrityError as exc:
        raise DryRunImporterError(f"Falha de integridade no banco dry-run: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()
        if created_temp_db and temp_db_path is not None and temp_db_path.exists():
            temp_db_path.unlink()
            report["db"]["cleaned_up"] = True


def _format_text_report(report: dict[str, Any]) -> str:
    removed_codes = ", ".join(item["codigo_atividade"] for item in report["atividades_removidas"]) or "nenhuma"
    new_codes = ", ".join(item["codigo_atividade"] for item in report["atividades_novas"]) or "nenhuma"
    lines = [
        f"Status: {report['status']}",
        f"Fixture: {report['fixture']}",
        (
            "Banco: "
            f"{report['db']['path']} "
            f"(temporario={report['db']['temporary']}, limpo={report['db']['cleaned_up']})"
        ),
        (
            "Fixture counts: "
            f"normas={report['fixture_counts']['normas']}, "
            f"atividades={report['fixture_counts']['atividades']}, "
            f"versoes={report['fixture_counts']['versoes']}, "
            f"transicoes={report['fixture_counts']['transicoes']}"
        ),
        (
            "Normas: "
            f"inseridas={report['inserted']['normas']} "
            f"skipped={report['skipped']['normas']} "
            f"final={report['final_counts'].get('norma_atividade', 0)}"
        ),
        (
            "Bases: "
            f"inseridas={report['inserted']['bases']} "
            f"skipped={report['skipped']['bases']} "
            f"final={report['final_counts'].get('atividade_base', 0)}"
        ),
        (
            "Versoes: "
            f"inseridas={report['inserted']['versoes']} "
            f"skipped={report['skipped']['versoes']} "
            f"final={report['final_counts'].get('atividade_versao', 0)}"
        ),
        (
            "Transicoes: "
            f"inseridas={report['inserted']['transicoes']} "
            f"skipped={report['skipped']['transicoes']} "
            f"final={report['final_counts'].get('atividade_transicao', 0)}"
        ),
        f"Atividades removidas ({len(report['atividades_removidas'])}): {removed_codes}",
        f"Atividades novas ({len(report['atividades_novas'])}): {new_codes}",
    ]
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


def _error_payload(
    *,
    report_format: str,
    fixture_path: Path | None,
    db_path: Path | None,
    message: str,
) -> str:
    if report_format == "json":
        payload = {
            "status": "error",
            "fixture": str(fixture_path.resolve()) if fixture_path is not None else None,
            "db": str(db_path.resolve()) if db_path is not None else None,
            "errors": [message],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    return f"Status: error\nErrors (1):\n- {message}"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Importa a fixture normativa YAML em um banco SQLite isolado "
            "para dry-run controlado."
        )
    )
    parser.add_argument("--fixture", required=True, type=Path, help="Caminho da fixture YAML.")
    parser.add_argument(
        "--db",
        type=Path,
        help="Caminho opcional para banco SQLite isolado. Se omitido, usa arquivo temporario.",
    )
    parser.add_argument(
        "--report",
        choices=("text", "json"),
        default="text",
        help="Formato do relatorio. Default: text.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Trata warnings como erro.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Inclui detalhes adicionais no relatorio.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        report = run_import(
            fixture_path=args.fixture,
            db_path=args.db,
            report_format=args.report,
            strict=args.strict,
            verbose=args.verbose,
        )
    except DryRunImporterError as exc:
        print(
            _error_payload(
                report_format=args.report,
                fixture_path=args.fixture,
                db_path=args.db,
                message=str(exc),
            ),
            file=sys.stderr,
        )
        return 1

    if args.report == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_format_text_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
