from __future__ import annotations

import json

from app.db import DatabaseIntegrityError
from app.matrix_scope import is_activity_version_referenced_by_assigned_matrix
from app.presentation import format_date_ptbr
from app.text import normalize_header


ACTIVITY_VERSION_SEMANTIC_FIELDS = frozenset({
    "eixo", "grupo", "ch_por_evento",
    "limite_semestre", "limite_total", "observacao_aluno",
    "observacao_admin", "documentos_json", "vigencia_inicio", "vigencia_fim",
    "versao_anterior_id",
})

# Longer reference lists are summarised ("e outras N") in the refusal text.
_DELETE_DEPENDENCY_LIST_LIMIT = 5


class ActivityVersionDeleteBlocked(ValueError):
    """A version delete refused for a concrete reason.

    ``in_use`` carries the exact Requisições and Matrizes that still read the
    version, so the refusal can name them.
    """

    def __init__(
        self,
        code: str,
        *,
        request_ids: tuple[int, ...] = (),
        matrix_names: tuple[str, ...] = (),
    ):
        super().__init__(code)
        self.code = code
        self.request_ids = tuple(request_ids)
        self.matrix_names = tuple(matrix_names)

    def describe_dependencies(self) -> str:
        return describe_activity_version_dependencies(
            self.request_ids, self.matrix_names
        )


def _join_ptbr(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} e {items[-1]}"


def _dependency_clause(singular: str, plural: str, labels) -> str:
    labels = [str(label) for label in labels]
    if len(labels) == 1:
        return f"pela {singular} {labels[0]}"
    shown = labels[:_DELETE_DEPENDENCY_LIST_LIMIT]
    hidden = len(labels) - len(shown)
    if hidden:
        shown.append(f"outras {hidden}")
    return f"pelas {plural} {_join_ptbr(shown)}"


def describe_activity_version_dependencies(request_ids, matrix_names) -> str:
    """Name the business records, e.g. 'pela requisição 2 e pela matriz 01.2025'."""
    clauses = []
    if request_ids:
        clauses.append(_dependency_clause("requisição", "requisições", request_ids))
    if matrix_names:
        clauses.append(_dependency_clause("matriz", "matrizes", matrix_names))
    return " e ".join(clauses)


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


def _parse_non_negative_form_number(raw, label, *, required=False):
    if raw is None or str(raw).strip() == "":
        if required:
            raise ValueError(f"Informe {label}.")
        return None
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"{label} deve ser um número válido e maior ou igual a zero."
        )
    if parsed < 0:
        raise ValueError(
            f"{label} deve ser um número válido e maior ou igual a zero."
        )
    return parsed


def _build_grupo_label(numero: str, descricao: str) -> str:
    numero = str(numero or "").strip()
    descricao = str(descricao or "").strip()
    return f"{numero} - {descricao}" if descricao else numero


def create_activity_with_initial_version(
    conn,
    *,
    nome: str,
    descricao: str | None,
    eixo: str,
    grupo: str,
    ch_por_evento: float | None,
    limite_semestre: float | None,
    limite_total: float | None,
    observacoes: str | None,
) -> tuple[int, int]:
    """Write the canonical atividade_base + active v1 unit without committing."""
    base_id = conn.execute(
        "INSERT INTO atividade_base(nome_conceito,descricao,status) "
        "VALUES(?,?,'ativo') RETURNING id",
        (nome, descricao),
    ).fetchone()[0]
    versao_id = conn.execute(
        """INSERT INTO atividade_versao
           (atividade_base_id,eixo,grupo,ch_por_evento,
            limite_total,limite_semestre,observacao_aluno,
            observacao_admin,numero_versao,status)
           VALUES(?,?,?,?,?,?,?,?,1,'ativa')
           RETURNING id""",
        (
            base_id,
            eixo,
            grupo,
            ch_por_evento,
            limite_total,
            limite_semestre,
            observacoes,
            observacoes,
        ),
    ).fetchone()[0]
    return base_id, versao_id


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
    (matriz_atividade_versao_item, requisicoes, atividade_transicao e
    sucessoras que apontam para esta versão como predecessora).
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
    versoes_sucessoras = conn.execute(
        "SELECT COUNT(*) FROM atividade_versao WHERE versao_anterior_id = ?",
        (versao_id,),
    ).fetchone()[0]
    return {
        "matriz_atividade_versao_item": matriz_itens,
        "requisicoes": requisicoes,
        "atividade_transicao_origem": transicoes_origem,
        "atividade_transicao_destino": transicoes_destino,
        "atividade_versao_sucessora": versoes_sucessoras,
        "total": (
            matriz_itens
            + requisicoes
            + transicoes_origem
            + transicoes_destino
            + versoes_sucessoras
        ),
    }


def get_activity_version_business_references(
    conn, versao_id: int
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    """Return the Requisição ids and Matriz names that read this exact version."""
    request_ids = tuple(
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM requisicoes WHERE atividade_versao_id = ? ORDER BY id",
            (versao_id,),
        )
    )
    matrix_names = tuple(
        str(row[0])
        for row in conn.execute(
            "SELECT matriz.nome FROM matriz_atividade_versao_item item "
            "JOIN matrizes_atividades matriz ON matriz.id = item.matriz_id "
            "WHERE item.atividade_versao_id = ? ORDER BY matriz.nome, matriz.id",
            (versao_id,),
        )
    )
    return request_ids, matrix_names


def assert_activity_version_can_be_safely_deleted(
    conn,
    *,
    base_id: int,
    versao_id: int,
):
    """Return the exact deletable version or raise the concrete blocking reason.

    Only real business use blocks a delete: a Requisição (immutable history) or
    a Matriz that selects this exact version. Being another version's
    predecessor does not; ``delete_activity_version`` re-anchors that lineage.
    Read-only; the caller must own the write transaction.
    """
    version = conn.execute(
        "SELECT * FROM atividade_versao WHERE id = ? AND atividade_base_id = ?",
        (versao_id, base_id),
    ).fetchone()
    if version is None:
        raise ActivityVersionDeleteBlocked("wrong_base_or_version")

    surviving_count = conn.execute(
        "SELECT COUNT(*) FROM atividade_versao "
        "WHERE atividade_base_id = ? AND id <> ?",
        (base_id, versao_id),
    ).fetchone()[0]
    if int(surviving_count) < 1:
        raise ActivityVersionDeleteBlocked("sole_version")

    request_ids, matrix_names = get_activity_version_business_references(
        conn, versao_id
    )
    if request_ids or matrix_names:
        raise ActivityVersionDeleteBlocked(
            "in_use", request_ids=request_ids, matrix_names=matrix_names
        )
    return version


def renumber_activity_versions(conn, base_id: int) -> None:
    """Compact one base's ``numero_versao`` to the contiguous v1..vN sequence.

    The existing (creation) order is kept: rows are taken by
    ``numero_versao, id`` and only gaps close. Ascending assignment cannot
    collide with UNIQUE(atividade_base_id, numero_versao): each target is at
    most the row's current number, lower targets already belong to earlier
    rows and later rows hold strictly larger numbers.
    """
    rows = conn.execute(
        "SELECT id, numero_versao FROM atividade_versao "
        "WHERE atividade_base_id = ? ORDER BY numero_versao, id",
        (base_id,),
    ).fetchall()
    for position, (version_id, numero_versao) in enumerate(rows, start=1):
        if int(numero_versao) != position:
            conn.execute(
                "UPDATE atividade_versao SET numero_versao = ? WHERE id = ?",
                (position, version_id),
            )


def delete_activity_version(conn, *, base_id: int, versao_id: int) -> None:
    """Hard-delete one version, keeping its base's lineage and numbering canonical.

    Inside the caller's transaction: successors are re-anchored to the deleted
    version's own predecessor (NULL when it was the first), its lifecycle
    transition rows are removed, the row is deleted and the survivors are
    renumbered v1..vN, so the next created version is vN+1. Survivor ids,
    Requisições, their snapshots and Matriz links are never written. On any
    error the caller must roll the whole transaction back.
    """
    version = assert_activity_version_can_be_safely_deleted(
        conn, base_id=base_id, versao_id=versao_id
    )
    conn.execute(
        "UPDATE atividade_versao SET versao_anterior_id = ? "
        "WHERE versao_anterior_id = ?",
        (version["versao_anterior_id"], versao_id),
    )
    conn.execute(
        "DELETE FROM atividade_transicao "
        "WHERE from_atividade_versao_id = ? OR to_atividade_versao_id = ?",
        (versao_id, versao_id),
    )
    deleted = conn.execute(
        "DELETE FROM atividade_versao WHERE id = ? AND atividade_base_id = ?",
        (versao_id, base_id),
    )
    if deleted.rowcount != 1:
        raise DatabaseIntegrityError("exact version delete lost its target")
    renumber_activity_versions(conn, base_id)


# Fields that compute a version's rule. Free text (observações, documentos)
# is guidance whose equivalence the operator asserts before consolidating.
_CONSOLIDATION_RULE_FIELDS = ("eixo", "ch_por_evento", "limite_semestre", "limite_total")


def _grupo_number(grupo) -> str:
    return str(grupo or "").split("-", 1)[0].strip()


def consolidate_equivalent_activity_versions(
    conn, *, base_id: int, keep_versao_id: int, remove_versao_id: int
) -> None:
    """Fold a duplicate version of the same rule into the surviving version.

    Both versions must belong to ``base_id`` and compute the same rule (axis,
    group number, hours, limits). Every Matriz selecting ``remove`` is
    repointed to ``keep`` -- assigned Matrizes included, since the rule they
    apply does not change -- and ``remove`` is then deleted through
    ``delete_activity_version`` (lineage re-anchored, survivors renumbered).
    Requisições are immutable history, so ``remove`` must have none; ``keep``,
    its Requisições and their snapshots are never written. The caller owns
    the transaction and rolls it back on any error.
    """
    if int(keep_versao_id) == int(remove_versao_id):
        raise ValueError("A versão mantida e a removida devem ser diferentes.")
    keep, remove = (
        conn.execute(
            "SELECT * FROM atividade_versao WHERE id = ? AND atividade_base_id = ?",
            (versao_id, base_id),
        ).fetchone()
        for versao_id in (keep_versao_id, remove_versao_id)
    )
    if keep is None or remove is None:
        raise ValueError("Versão não encontrada para esta atividade-base.")
    differing = [
        field for field in _CONSOLIDATION_RULE_FIELDS if keep[field] != remove[field]
    ]
    if _grupo_number(keep["grupo"]) != _grupo_number(remove["grupo"]):
        differing.append("grupo")
    if differing:
        raise ValueError(
            f"As versões não têm a mesma regra: {', '.join(differing)}."
        )
    request_ids, matrix_names = get_activity_version_business_references(
        conn, remove_versao_id
    )
    if request_ids:
        raise ValueError(
            "A versão removida é utilizada "
            f"{describe_activity_version_dependencies(request_ids, ())}."
        )
    if matrix_names and keep["status"] != "ativa":
        raise ValueError("A versão mantida deve estar ativa para ser selecionada por Matriz.")
    conn.execute(
        "UPDATE matriz_atividade_versao_item SET atividade_versao_id = ? "
        "WHERE atividade_versao_id = ? AND atividade_base_id = ?",
        (keep_versao_id, remove_versao_id, base_id),
    )
    delete_activity_version(conn, base_id=base_id, versao_id=remove_versao_id)


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
        or usage["atividade_versao_sucessora"]
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
                "created_at_fmt": format_date_ptbr(row["created_at"]) or "-",
                "eixo": row["from_eixo"] or row["to_eixo"] or "-",
                "eixo_origem": row["from_eixo"] or "-",
                "eixo_destino": row["to_eixo"] or "-",
            }
        )
    return transicoes


__all__ = [
    'parse_documentos_json',
    'ActivityVersionDeleteBlocked',
    '_normalize_atividade_grupo',
    '_canonicalize_tipo_limitacao',
    '_parse_non_negative_form_number',
    '_build_grupo_label',
    'create_activity_with_initial_version',
    'get_atividade_base',
    'get_versoes_por_base',
    'get_versoes_da_base_por_eixo',
    'get_next_numero_versao',
    'get_atividade_versao_by_id',
    'get_atividade_versao_usage_counts',
    'describe_activity_version_dependencies',
    'get_activity_version_business_references',
    'assert_activity_version_can_be_safely_deleted',
    'renumber_activity_versions',
    'delete_activity_version',
    'consolidate_equivalent_activity_versions',
    'can_activity_version_be_mutated_in_place',
    'apply_activity_version_semantic_changes',
    'apply_latest_activity_version_semantic_changes',
    'rename_current_activity_group_versions',
    'get_atividade_transicoes_por_base',
]
