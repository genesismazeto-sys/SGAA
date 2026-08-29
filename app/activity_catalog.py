from __future__ import annotations

import json

from app.matrix_scope import is_activity_version_referenced_by_assigned_matrix
from app.text import normalize_header


ACTIVITY_VERSION_SEMANTIC_FIELDS = frozenset({
    "eixo", "grupo", "ch_por_evento",
    "limite_semestre", "limite_total", "observacao_aluno",
    "observacao_admin", "documentos_json", "vigencia_inicio", "vigencia_fim",
    "versao_anterior_id",
})


def parse_documentos_json(raw) -> list[str]:
    """Robustly parse documentos list from various legacy formats.
    Accepts: JSON array (string), JSON-encoded string, Python-like list with single quotes,
    or plain delimited string (comma/semicolon/pipe/newline). Filters placeholders like NA.
    """
    bad = {"na", "n/a", "-", "_", "null", "none", "sem", "vazio"}
    def _normalize_list(arr):
        out = []
        seen = set()
        for x in (arr or []):
            s = str(x or "").strip().strip('"').strip("'")
            if not s:
                continue
            if s.lower() in bad:
                continue
            if s not in seen:
                seen.add(s); out.append(s)
        return out
    if raw is None:
        return []
    # Try JSON directly
    try:
        obj = json.loads(raw)
        if isinstance(obj, list):
            return _normalize_list(obj)
        if isinstance(obj, str):
            try:
                obj2 = json.loads(obj)
                if isinstance(obj2, list):
                    return _normalize_list(obj2)
            except Exception:
                s = obj
        else:
            s = str(obj)
    except Exception:
        s = str(raw)

    t = (s or "").strip()
    # Python-like list with single quotes
    if t.startswith('[') and t.endswith(']'):
        try:
            obj3 = json.loads(t.replace("'", '"'))
            if isinstance(obj3, list):
                return _normalize_list(obj3)
        except Exception:
            # strip brackets and continue to split
            t = t[1:-1]
    # strip surrounding quotes
    t = t.strip().strip('"').strip("'")
    if not t:
        return []
    import re as _re
    parts = _re.split(r"[,;\n\|]+", t)
    return _normalize_list(parts)


def _normalize_atividade_grupo(tipo_atividade: str, grupo: str) -> str:
    if (tipo_atividade or "").strip() == "Extensão Universitária":
        return "NA"
    return (grupo or "").strip()


def _canonicalize_tipo_limitacao(value: str) -> str | None:
    normalized = normalize_header(value).replace("_", " ")
    if normalized == "total":
        return "total"
    if normalized == "semestral":
        return "semestral"
    return None


def _build_grupo_label(numero: str, descricao: str) -> str:
    numero = str(numero or "").strip()
    descricao = str(descricao or "").strip()
    return f"{numero} - {descricao}" if descricao else numero


def get_atividade_base_list(conn) -> list:
    """
    Retorna todas as atividade_base com contagem de versões.
    Estritamente read-only — nenhum INSERT/UPDATE/DELETE.
    """
    return conn.execute(
        """
        SELECT
            ab.id,
            ab.nome_conceito,
            ab.descricao,
            ab.status,
            ab.created_at,
            COUNT(av.id)                                              AS total_versoes,
            SUM(CASE WHEN av.status = 'ativa' THEN 1 ELSE 0 END)     AS versoes_ativas
          FROM atividade_base ab
          LEFT JOIN atividade_versao av ON av.atividade_base_id = ab.id
         GROUP BY ab.id
         ORDER BY LOWER(ab.nome_conceito) ASC
        """
    ).fetchall()


def get_atividade_base(conn, base_id: int):
    """
    Retorna uma atividade_base pelo id, ou None.
    Estritamente read-only.
    """
    return conn.execute(
        "SELECT * FROM atividade_base WHERE id = ?",
        (base_id,),
    ).fetchone()


def get_versoes_por_base(conn, base_id: int) -> list:
    """
    Retorna as atividade_versao vinculadas a uma base e sua contagem de uso.
    """
    return conn.execute(
        """
        SELECT
            av.id,
            av.atividade_base_id,
            av.eixo,
            av.grupo,
            av.ch_por_evento,
            av.limite_semestre,
            av.limite_total,
            av.observacao_aluno,
            av.observacao_admin,
            av.vigencia_inicio,
            av.vigencia_fim,
            av.numero_versao,
            av.status,
            av.versao_anterior_id,
            av.created_at,
            COUNT(DISTINCT mavi.matriz_id) AS uso_em_matrizes
          FROM atividade_versao av
          LEFT JOIN matriz_atividade_versao_item mavi ON mavi.atividade_versao_id = av.id
         WHERE av.atividade_base_id = ?
         GROUP BY av.id
         ORDER BY av.numero_versao DESC
        """,
        (base_id,),
    ).fetchall()


def get_latest_atividade_versao_for_base(conn, base_id: int):
    """Return the highest numbered version for an exact activity base."""
    return conn.execute(
        "SELECT * FROM atividade_versao "
        "WHERE atividade_base_id = ? ORDER BY numero_versao DESC, id DESC LIMIT 1",
        (base_id,),
    ).fetchone()


def get_versoes_da_base_por_eixo(conn, base_id: int, eixo: str) -> list:
    """
    Retorna as atividade_versao da mesma base e eixo, ordenadas por created_at DESC.
    Estritamente read-only — usado para popular versao_anterior_id.
    """
    return conn.execute(
        """
        SELECT id, eixo, status, numero_versao, created_at
          FROM atividade_versao
         WHERE atividade_base_id = ? AND eixo = ?
         ORDER BY created_at DESC
        """,
        (base_id, eixo),
    ).fetchall()


def get_next_numero_versao(conn, base_id: int) -> int:
    """Retorna o próximo numero_versao para uma atividade_base (MAX positivo + 1)."""
    row = conn.execute(
        "SELECT COALESCE(MAX(numero_versao), 0) + 1 AS next_num"
        " FROM atividade_versao"
        " WHERE atividade_base_id = ? AND numero_versao > 0",
        (base_id,),
    ).fetchone()
    return row["next_num"] if row else 1


def get_atividade_versao_by_id(conn, versao_id: int):
    """
    Retorna uma atividade_versao pelo id, ou None se não existir.
    Estritamente read-only — sem fallback ou inferência.
    """
    return conn.execute(
        "SELECT * FROM atividade_versao WHERE id = ?",
        (versao_id,),
    ).fetchone()


def get_atividade_versao_usage_counts(conn, versao_id: int) -> dict:
    """
    Retorna contagens de uso de uma atividade_versao em outras tabelas
    (matriz_atividade_versao_item, requisicoes, atividade_transicao).
    Estritamente read-only — usado para bloquear edição de versões em uso.
    """
    matriz_itens = conn.execute(
        "SELECT COUNT(*) FROM matriz_atividade_versao_item WHERE atividade_versao_id = ?",
        (versao_id,),
    ).fetchone()[0]
    requisicoes = conn.execute(
        "SELECT COUNT(*) FROM requisicoes WHERE atividade_versao_id = ?",
        (versao_id,),
    ).fetchone()[0]
    transicoes_origem = conn.execute(
        "SELECT COUNT(*) FROM atividade_transicao WHERE from_atividade_versao_id = ?",
        (versao_id,),
    ).fetchone()[0]
    transicoes_destino = conn.execute(
        "SELECT COUNT(*) FROM atividade_transicao WHERE to_atividade_versao_id = ?",
        (versao_id,),
    ).fetchone()[0]
    return {
        "matriz_atividade_versao_item": matriz_itens,
        "requisicoes": requisicoes,
        "atividade_transicao_origem": transicoes_origem,
        "atividade_transicao_destino": transicoes_destino,
        "total": matriz_itens + requisicoes + transicoes_origem + transicoes_destino,
    }


def can_activity_version_be_mutated_in_place(conn, versao_id: int) -> bool:
    """Central freeze policy for semantic Activity Version writes.

    Only a genuine, unreferenced draft is editable. Active/lifecycle-frozen
    versions, assigned Matrix versions, request history and transition
    provenance always require a successor.
    """
    version = get_atividade_versao_by_id(conn, versao_id)
    if version is None or version["status"] != "rascunho":
        return False
    usage = get_atividade_versao_usage_counts(conn, versao_id)
    return not (
        usage["requisicoes"]
        or usage["atividade_transicao_origem"]
        or usage["atividade_transicao_destino"]
        or is_activity_version_referenced_by_assigned_matrix(conn, versao_id)
    )


def apply_activity_version_semantic_changes(
    conn,
    versao_id: int,
    changes: dict[str, object],
    *,
    create_successor_if_frozen: bool = True,
) -> dict[str, object]:
    """Apply semantic changes through the sole canonical mutation policy.

    Frozen predecessors are never updated. A same-axis successor is copied in
    full and receives only the intentional delta; Matrix links are untouched.
    The caller owns the surrounding transaction.
    """
    unknown = set(changes) - ACTIVITY_VERSION_SEMANTIC_FIELDS
    if unknown:
        raise ValueError(f"Campos semânticos não autorizados: {sorted(unknown)!r}")
    version = get_atividade_versao_by_id(conn, versao_id)
    if version is None:
        raise ValueError("Versão de atividade não encontrada")
    effective_changes = {
        field: value for field, value in changes.items() if version[field] != value
    }
    if not effective_changes:
        return {"mode": "unchanged", "version_id": int(versao_id), "predecessor_id": None}

    if can_activity_version_be_mutated_in_place(conn, versao_id):
        assignments = ", ".join(f"{field} = ?" for field in effective_changes)
        conn.execute(
            f"UPDATE atividade_versao SET {assignments} WHERE id = ?",
            (*effective_changes.values(), versao_id),
        )
        return {"mode": "updated", "version_id": int(versao_id), "predecessor_id": None}

    if not create_successor_if_frozen:
        raise ValueError("Esta versão já está em uso e não pode mais ser editada.")
    if "eixo" in effective_changes and effective_changes["eixo"] != version["eixo"]:
        raise ValueError("Mudança de eixo exige nova versão e transição explícita")

    payload = {field: version[field] for field in ACTIVITY_VERSION_SEMANTIC_FIELDS}
    payload.update(effective_changes)
    next_number = get_next_numero_versao(conn, int(version["atividade_base_id"]))
    columns = (
        "atividade_base_id", "eixo", "grupo",
        "ch_por_evento", "limite_semestre", "limite_total", "observacao_aluno",
        "observacao_admin", "documentos_json", "vigencia_inicio", "vigencia_fim",
        "numero_versao", "status", "versao_anterior_id",
    )
    values = (
        version["atividade_base_id"], payload["eixo"], payload["grupo"],
        payload["ch_por_evento"], payload["limite_semestre"],
        payload["limite_total"], payload["observacao_aluno"],
        payload["observacao_admin"], payload["documentos_json"],
        payload["vigencia_inicio"], payload["vigencia_fim"], next_number,
        "rascunho", versao_id,
    )
    placeholders = ",".join("?" for _ in columns)
    successor_id = conn.execute(
        f"INSERT INTO atividade_versao ({','.join(columns)}) VALUES ({placeholders}) RETURNING id",
        values,
    ).fetchone()[0]
    return {
        "mode": "successor",
        "version_id": int(successor_id),
        "predecessor_id": int(versao_id),
    }


def apply_latest_activity_version_semantic_changes(
    conn,
    base_id: int,
    changes: dict[str, object],
    *,
    expected_axis: str | None = None,
) -> dict[str, object]:
    """Resolve and mutate the current version inside the canonical owner."""
    version = conn.execute(
        "SELECT * FROM atividade_versao WHERE atividade_base_id = ? "
        "ORDER BY numero_versao DESC, id DESC LIMIT 1",
        (base_id,),
    ).fetchone()
    if version is None:
        raise ValueError("Atividade-base sem versão canônica")
    if expected_axis is not None and version["eixo"] != expected_axis:
        raise ValueError("Import não pode mudar o eixo de uma base existente")
    return apply_activity_version_semantic_changes(conn, int(version["id"]), changes)


def rename_current_activity_group_versions(
    conn,
    *,
    eixo: str,
    group_number: str,
    new_label: str,
) -> list[dict[str, object]]:
    """Rename only each base's current semantic version via the freeze policy."""
    rows = conn.execute(
        "SELECT * FROM atividade_versao WHERE eixo = ? "
        "ORDER BY atividade_base_id, numero_versao DESC, id DESC",
        (eixo,),
    ).fetchall()
    current_by_base = {}
    for row in rows:
        current_by_base.setdefault(int(row["atividade_base_id"]), row)
    results = []
    for row in current_by_base.values():
        raw_group = str(row["grupo"] or "").strip()
        numeric_prefix = raw_group.split("-", 1)[0].strip()
        if numeric_prefix != str(group_number) or raw_group == new_label:
            continue
        results.append(
            apply_activity_version_semantic_changes(
                conn, int(row["id"]), {"grupo": new_label}
            )
        )
    return results


def get_atividade_transicoes_por_base(conn, base_id: int) -> list[dict]:
    """
    Lista o histórico administrativo de atividade_transicao relacionado a uma
    atividade_base, sem mutar dados.
    """
    rows = conn.execute(
        """
        SELECT t.id,
               t.tipo_transicao,
               t.justificativa,
               t.observacao_admin,
               t.created_at,
               src.id AS from_id,
               src.atividade_base_id AS from_base_id,
               src.numero_versao AS from_numero_versao,
               src.eixo AS from_eixo,
               dst.id AS to_id,
               dst.atividade_base_id AS to_base_id,
               dst.numero_versao AS to_numero_versao,
               dst.eixo AS to_eixo
          FROM atividade_transicao t
          LEFT JOIN atividade_versao src ON src.id = t.from_atividade_versao_id
          LEFT JOIN atividade_versao dst ON dst.id = t.to_atividade_versao_id
         WHERE src.atividade_base_id = ?
            OR dst.atividade_base_id = ?
         ORDER BY datetime(t.created_at) DESC, t.id DESC
        """,
        (base_id, base_id),
    ).fetchall()

    transicoes = []
    for row in rows:
        justificativa = (row["justificativa"] or "").strip()
        observacao_admin = (row["observacao_admin"] or "").strip()
        from_label = "-"
        if row["from_id"] is not None:
            from_label = f"v{row['from_numero_versao']}"
        to_label = "-"
        if row["to_id"] is not None:
            to_label = f"v{row['to_numero_versao']}"
        transicoes.append(
            {
                "id": row["id"],
                "versao_origem": from_label,
                "versao_destino": to_label,
                "tipo_transicao": row["tipo_transicao"],
                "motivo": justificativa or observacao_admin or "-",
                "created_at": row["created_at"] or "-",
                "eixo": row["from_eixo"] or row["to_eixo"] or "-",
            }
        )
    return transicoes


__all__ = [
    'parse_documentos_json',
    '_normalize_atividade_grupo',
    '_canonicalize_tipo_limitacao',
    '_build_grupo_label',
    'get_atividade_base_list',
    'get_atividade_base',
    'get_versoes_por_base',
    'get_versoes_da_base_por_eixo',
    'get_next_numero_versao',
    'get_atividade_versao_by_id',
    'get_atividade_versao_usage_counts',
    'can_activity_version_be_mutated_in_place',
    'apply_activity_version_semantic_changes',
    'apply_latest_activity_version_semantic_changes',
    'rename_current_activity_group_versions',
    'get_atividade_transicoes_por_base',
]
