from __future__ import annotations

from app.matrix_scope import get_effective_matriz_for_turma


_MATRIZ_STATUS_LABELS = {
    "rascunho": "Rascunho",
    "vigente": "Vigente",
    "encerrada": "Encerrada",
}


def _versioning_matriz_option_label(row) -> str:
    parts = [str(row["nome"] or "Matriz sem nome").strip()]
    if row["versao"]:
        parts.append(str(row["versao"]).strip())
    if row["status"]:
        normalized = str(row["status"] or "rascunho").strip().lower()
        parts.append(_MATRIZ_STATUS_LABELS.get(normalized, "Rascunho"))
    return " | ".join(part for part in parts if part)


def _versioning_periodo_label_for_turma_row(turma) -> str:
    inicio = None
    fim = None
    if turma["semestre_inicio"] and turma["ano_inicio"]:
        inicio = f"{turma['semestre_inicio']}S-{turma['ano_inicio']}"
    if turma["semestre_fim"] and turma["ano_fim"]:
        fim = f"{turma['semestre_fim']}S-{turma['ano_fim']}"
    if inicio and fim:
        return f"{inicio} a {fim}"
    if inicio:
        return inicio
    if fim:
        return fim
    return "-"


def _require_versioning_read_model(conn) -> None:
    required_tables = (
        "atividade_base",
        "norma_atividade",
        "atividade_versao",
        "matriz_norma",
        "matriz_atividade_versao_item",
        "atividade_legacy_map",
        "matrizes_atividades",
        "turmas",
    )
    existing_tables = {
        row["name"]
        for row in conn.execute(
            f"""
            SELECT name
              FROM sqlite_master
             WHERE type = 'table'
               AND name IN ({",".join("?" for _ in required_tables)})
            """,
            required_tables,
        ).fetchall()
    }
    missing = [name for name in required_tables if name not in existing_tables]
    if missing:
        raise RuntimeError(
            "Schema de versionamento indisponível para leitura diagnóstica: faltam as tabelas "
            + ", ".join(missing)
            + "."
        )

def _serialize_versioned_activity_row(row) -> dict[str, object]:
    return {
        "eixo": row["eixo"],
        "norma": row["norma_codigo"],
        "atividade_base": {
            "id": row["atividade_base_id"],
            "nome": row["atividade_base_nome"],
        },
        "atividade_versao_id": row["atividade_versao_id"],
        "nome_exibivel": row["nome_exibivel"],
        "grupo": row["grupo"],
        "ch_por_evento": row["ch_por_evento"],
        "limite_semestre": row["limite_semestre"],
        "limite_total": row["limite_total"],
        "observacao_aluno": row["observacao_aluno"],
        "observacao_admin": row["observacao_admin"],
        "status": row["status"],
        "tem_correspondente_legado": bool(row["tem_correspondente_legado"]),
        "atividade_id_legacy": row["atividade_id_legacy"],
        "nome_legacy": row["nome_legacy"],
        "tipo_atividade_legacy": row["tipo_atividade_legacy"],
    }

def listar_atividades_versionadas_por_matriz(conn, matriz_id: int) -> dict[str, object]:
    _require_versioning_read_model(conn)

    matriz = conn.execute(
        """
        SELECT m.*,
               c.nome AS curso_nome,
               c.codigo AS curso_codigo
          FROM matrizes_atividades m
          LEFT JOIN cursos c ON c.id = m.curso_id
         WHERE m.id = ?
        """,
        (matriz_id,),
    ).fetchone()
    if not matriz:
        raise LookupError("Matriz não encontrada para leitura diagnóstica.")

    turmas_vinculadas = [
        {
            "id": row["id"],
            "codigo": row["codigo"],
            "nome": row["nome"],
            "periodo_label": _versioning_periodo_label_for_turma_row(row),
        }
        for row in conn.execute(
            """
            SELECT id, codigo, nome, ano_inicio, semestre_inicio, ano_fim, semestre_fim
              FROM turmas
             WHERE matriz_id = ?
          ORDER BY COALESCE(codigo, nome, '')
            """,
            (matriz_id,),
        ).fetchall()
    ]

    normas = [
        {
            "id": row["id"],
            "codigo": row["codigo"],
            "eixo": row["eixo"],
            "revisao": row["revisao"],
            "nome": row["nome"],
        }
        for row in conn.execute(
            """
            SELECT n.id, n.codigo, n.eixo, n.revisao, n.nome
              FROM matriz_norma mn
              JOIN norma_atividade n ON n.id = mn.norma_id
             WHERE mn.matriz_id = ?
          ORDER BY n.eixo, n.codigo
            """,
            (matriz_id,),
        ).fetchall()
    ]

    versioned_rows = conn.execute(
        """
        SELECT av.id AS atividade_versao_id,
               av.atividade_base_id,
               ab.nome_conceito AS atividade_base_nome,
               COALESCE(
                   (
                       SELECT a.nome
                         FROM atividade_legacy_map alm
                         JOIN atividades a ON a.id = alm.atividade_id_legacy
                        WHERE alm.atividade_base_id = av.atividade_base_id
                     ORDER BY alm.atividade_id_legacy
                        LIMIT 1
                   ),
                   ab.nome_conceito
               ) AS nome_exibivel,
               av.grupo,
               av.ch_por_evento,
               av.limite_semestre,
               av.limite_total,
               av.observacao_aluno,
               av.observacao_admin,
               av.status,
               av.eixo,
               n.codigo AS norma_codigo,
               EXISTS(
                   SELECT 1
                     FROM atividade_legacy_map alm
                    WHERE alm.atividade_base_id = av.atividade_base_id
               ) AS tem_correspondente_legado,
               (
                   SELECT alm.atividade_id_legacy
                     FROM atividade_legacy_map alm
                    WHERE alm.atividade_base_id = av.atividade_base_id
                 ORDER BY alm.atividade_id_legacy
                    LIMIT 1
               ) AS atividade_id_legacy,
               (
                   SELECT a.nome
                     FROM atividade_legacy_map alm
                     JOIN atividades a ON a.id = alm.atividade_id_legacy
                    WHERE alm.atividade_base_id = av.atividade_base_id
                 ORDER BY alm.atividade_id_legacy
                    LIMIT 1
               ) AS nome_legacy,
               (
                   SELECT a.tipo_atividade
                     FROM atividade_legacy_map alm
                     JOIN atividades a ON a.id = alm.atividade_id_legacy
                    WHERE alm.atividade_base_id = av.atividade_base_id
                 ORDER BY alm.atividade_id_legacy
                    LIMIT 1
               ) AS tipo_atividade_legacy
          FROM matriz_atividade_versao_item mavi
          JOIN atividade_versao av ON av.id = mavi.atividade_versao_id
          JOIN atividade_base ab ON ab.id = av.atividade_base_id
          JOIN norma_atividade n ON n.id = av.norma_id
         WHERE mavi.matriz_id = ?
      ORDER BY CASE av.eixo
                   WHEN 'AAC' THEN 0
                   WHEN 'AEU' THEN 1
                   ELSE 2
               END,
               COALESCE(NULLIF(TRIM(av.grupo), ''), 'zzzz'),
               COALESCE(NULLIF(TRIM(ab.nome_conceito), ''), 'zzzz'),
               av.id
        """,
        (matriz_id,),
    ).fetchall()

    atividades = [_serialize_versioned_activity_row(row) for row in versioned_rows]
    por_eixo: dict[str, list[dict[str, object]]] = {"AAC": [], "AEU": []}
    for item in atividades:
        por_eixo.setdefault(str(item["eixo"]), []).append(item)

    return {
        "turma": None,
        "turmas_vinculadas": turmas_vinculadas,
        "matriz": {
            "id": matriz["id"],
            "nome": matriz["nome"],
            "versao": matriz["versao"],
            "status": matriz["status"],
            "label": _versioning_matriz_option_label(matriz),
            "curso_id": matriz["curso_id"],
            "curso_nome": matriz["curso_nome"],
            "curso_codigo": matriz["curso_codigo"],
        },
        "normas": normas,
        "totais": {
            "geral": len(atividades),
            "por_eixo": {eixo: len(items) for eixo, items in por_eixo.items()},
        },
        "atividades": atividades,
        "por_eixo": por_eixo,
    }

def listar_atividades_versionadas_por_turma(conn, turma_id: int) -> dict[str, object]:
    _require_versioning_read_model(conn)

    turma = conn.execute(
        """
        SELECT t.*,
               c.nome AS curso_nome,
               c.codigo AS curso_codigo
          FROM turmas t
          LEFT JOIN cursos c ON c.id = t.curso_id
         WHERE t.id = ?
        """,
        (turma_id,),
    ).fetchone()
    if not turma:
        raise LookupError("Turma não encontrada para leitura diagnóstica.")

    matriz = get_effective_matriz_for_turma(conn, turma["curso_id"], turma["matriz_id"])
    if not matriz:
        raise LookupError("Turma sem matriz disponível para leitura diagnóstica.")

    payload = listar_atividades_versionadas_por_matriz(conn, matriz["id"])
    payload["turma"] = {
        "id": turma["id"],
        "codigo": turma["codigo"],
        "nome": turma["nome"],
        "curso_id": turma["curso_id"],
        "curso_nome": turma["curso_nome"],
        "curso_codigo": turma["curso_codigo"],
        "periodo_label": _versioning_periodo_label_for_turma_row(turma),
        "matriz_id": matriz["id"],
    }
    return payload

def _resolver_result(
    status: str,
    *,
    atividade_versao_id=None,
    atividade_base_id=None,
    codigo_normativo=None,
    eixo=None,
    matriz_id_efetiva=None,
    legacy_scope_ok=None,
    warnings=None,
    reason=None,
) -> dict[str, object]:
    return {
        "status": status,
        "atividade_versao_id": atividade_versao_id,
        "atividade_base_id": atividade_base_id,
        "codigo_normativo": codigo_normativo,
        "eixo": eixo,
        "matriz_id_efetiva": matriz_id_efetiva,
        "legacy_scope_ok": legacy_scope_ok,
        "warnings": list(warnings or []),
        "reason": reason,
    }

def _atividade_versao_status_ativo(status: str | None) -> bool:
    return str(status or "").strip().lower() in {"ativa", "vigente", "active"}

def resolver_versao_por_matriz(
    conn,
    *,
    matriz_id,
    atividade_id_legacy,
    strict_legacy_scope=True,
) -> dict[str, object]:
    warnings: list[str] = []
    try:
        _require_versioning_read_model(conn)

        if not matriz_id:
            return _resolver_result(
                "error",
                matriz_id_efetiva=matriz_id,
                reason="matriz_id inválido para resolução.",
            )
        if not atividade_id_legacy:
            return _resolver_result(
                "error",
                matriz_id_efetiva=matriz_id,
                reason="atividade_id_legacy inválido para resolução.",
            )

        matriz = conn.execute(
            "SELECT id FROM matrizes_atividades WHERE id = ?",
            (matriz_id,),
        ).fetchone()
        if not matriz:
            return _resolver_result(
                "error",
                matriz_id_efetiva=matriz_id,
                reason="Matriz não encontrada para resolução versionada.",
            )

        legacy_scope_ok = conn.execute(
            """
            SELECT 1
              FROM matrizes_atividades_itens
             WHERE matriz_id = ? AND atividade_id = ?
            """,
            (matriz_id, atividade_id_legacy),
        ).fetchone() is not None

        if not legacy_scope_ok:
            if strict_legacy_scope:
                return _resolver_result(
                    "legacy_activity_not_in_matrix",
                    matriz_id_efetiva=matriz_id,
                    legacy_scope_ok=False,
                    reason="Atividade legado fora do escopo da matriz efetiva no modo estrito.",
                )
            warnings.append("legacy_activity_outside_matrix_scope")

        base_rows = conn.execute(
            """
            SELECT DISTINCT atividade_base_id
              FROM atividade_legacy_map
             WHERE atividade_id_legacy = ?
            """,
            (atividade_id_legacy,),
        ).fetchall()

        base_ids = sorted(
            {
                int(row["atividade_base_id"])
                for row in base_rows
                if row["atividade_base_id"] is not None
            }
        )
        if not base_ids:
            return _resolver_result(
                "legacy_activity_without_base_map",
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason="Atividade legado sem mapeamento para atividade_base.",
            )

        atividade_base_id = base_ids[0] if len(base_ids) == 1 else None
        placeholders = ",".join("?" for _ in base_ids)

        candidate_rows = conn.execute(
            f"""
            SELECT av.id AS atividade_versao_id,
                   av.atividade_base_id,
                   av.norma_id,
                   av.eixo,
                   av.status,
                   n.codigo AS codigo_normativo
              FROM atividade_versao av
              JOIN matriz_atividade_versao_item mavi
                ON mavi.atividade_versao_id = av.id
               AND mavi.matriz_id = ?
              LEFT JOIN norma_atividade n ON n.id = av.norma_id
             WHERE av.atividade_base_id IN ({placeholders})
          ORDER BY av.id
            """,
            [matriz_id, *base_ids],
        ).fetchall()

        if not candidate_rows:
            return _resolver_result(
                "base_without_version_for_matrix",
                atividade_base_id=atividade_base_id,
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason="Atividade base mapeada sem versão associada à matriz.",
            )

        matriz_norma_ids = {
            row["norma_id"]
            for row in conn.execute(
                "SELECT norma_id FROM matriz_norma WHERE matriz_id = ?",
                (matriz_id,),
            ).fetchall()
        }
        if not matriz_norma_ids:
            return _resolver_result(
                "matrix_without_norma",
                atividade_base_id=atividade_base_id,
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason="Matriz sem normas configuradas para validar resolução.",
            )

        norma_candidates = [
            row for row in candidate_rows if row["norma_id"] in matriz_norma_ids
        ]
        if not norma_candidates:
            return _resolver_result(
                "matrix_without_norma",
                atividade_base_id=atividade_base_id,
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason="Versões encontradas sem norma vinculada à matriz.",
            )

        valid_candidates = [
            row for row in norma_candidates if _atividade_versao_status_ativo(row["status"])
        ]
        if not valid_candidates:
            return _resolver_result(
                "version_inactive",
                atividade_base_id=atividade_base_id,
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason="Existe versão para a matriz, mas sem status ativo/vigente.",
            )

        if len(valid_candidates) > 1:
            warnings.append("multiple_valid_candidates")
            return _resolver_result(
                "ambiguous_version",
                atividade_base_id=atividade_base_id,
                matriz_id_efetiva=matriz_id,
                legacy_scope_ok=legacy_scope_ok,
                warnings=warnings,
                reason=(
                    "Mais de uma versão válida encontrada para a mesma atividade base: "
                    + ", ".join(str(row["atividade_versao_id"]) for row in valid_candidates)
                ),
            )

        resolved = valid_candidates[0]
        return _resolver_result(
            "resolved",
            atividade_versao_id=resolved["atividade_versao_id"],
            atividade_base_id=resolved["atividade_base_id"],
            codigo_normativo=resolved["codigo_normativo"],
            eixo=resolved["eixo"],
            matriz_id_efetiva=matriz_id,
            legacy_scope_ok=legacy_scope_ok,
            warnings=warnings,
            reason="Resolução versionada concluída com sucesso.",
        )
    except Exception as exc:
        return _resolver_result(
            "error",
            matriz_id_efetiva=matriz_id,
            reason=f"Falha inesperada no resolvedor versionado: {exc}",
        )

def resolver_versao_por_aluno(
    conn,
    *,
    aluno_id,
    atividade_id_legacy,
    strict_legacy_scope=True,
) -> dict[str, object]:
    try:
        _require_versioning_read_model(conn)

        if not aluno_id:
            return _resolver_result(
                "error",
                reason="aluno_id inválido para resolução.",
            )
        if not atividade_id_legacy:
            return _resolver_result(
                "error",
                reason="atividade_id_legacy inválido para resolução.",
            )

        aluno = conn.execute(
            """
            SELECT a.id AS aluno_id,
                   t.id AS turma_id,
                   t.curso_id AS turma_curso_id,
                   t.matriz_id AS turma_matriz_id
              FROM alunos a
              LEFT JOIN turmas t ON t.id = a.turma_id
             WHERE a.id = ?
            """,
            (aluno_id,),
        ).fetchone()
        if not aluno:
            return _resolver_result(
                "error",
                reason="Aluno não encontrado para resolução.",
            )

        matriz = get_effective_matriz_for_turma(
            conn,
            aluno["turma_curso_id"],
            aluno["turma_matriz_id"],
        )
        if not matriz:
            return _resolver_result(
                "error",
                reason="Aluno sem matriz efetiva para resolução.",
            )

        return resolver_versao_por_matriz(
            conn,
            matriz_id=matriz["id"],
            atividade_id_legacy=atividade_id_legacy,
            strict_legacy_scope=strict_legacy_scope,
        )
    except Exception as exc:
        return _resolver_result(
            "error",
            reason=f"Falha inesperada no resolvedor por aluno: {exc}",
        )

def resolver_versao(
    conn,
    *,
    atividade_id_legacy,
    aluno_id=None,
    turma_id=None,
    matriz_id=None,
    strict_legacy_scope=True,
) -> dict[str, object]:
    try:
        _require_versioning_read_model(conn)

        if matriz_id:
            return resolver_versao_por_matriz(
                conn,
                matriz_id=matriz_id,
                atividade_id_legacy=atividade_id_legacy,
                strict_legacy_scope=strict_legacy_scope,
            )

        if turma_id:
            turma = conn.execute(
                """
                SELECT id, curso_id, matriz_id
                  FROM turmas
                 WHERE id = ?
                """,
                (turma_id,),
            ).fetchone()
            if not turma:
                return _resolver_result(
                    "error",
                    reason="Turma não encontrada para resolução.",
                )

            matriz = get_effective_matriz_for_turma(
                conn,
                turma["curso_id"],
                turma["matriz_id"],
            )
            if not matriz:
                return _resolver_result(
                    "error",
                    reason="Turma sem matriz efetiva para resolução.",
                )

            return resolver_versao_por_matriz(
                conn,
                matriz_id=matriz["id"],
                atividade_id_legacy=atividade_id_legacy,
                strict_legacy_scope=strict_legacy_scope,
            )

        if aluno_id:
            return resolver_versao_por_aluno(
                conn,
                aluno_id=aluno_id,
                atividade_id_legacy=atividade_id_legacy,
                strict_legacy_scope=strict_legacy_scope,
            )

        return _resolver_result(
            "error",
            reason="Informe aluno_id, turma_id ou matriz_id para resolver a versão.",
        )
    except Exception as exc:
        return _resolver_result(
            "error",
            reason=f"Falha inesperada no wrapper do resolvedor: {exc}",
        )

__all__ = [
    "listar_atividades_versionadas_por_matriz",
    "listar_atividades_versionadas_por_turma",
    "resolver_versao",
    "resolver_versao_por_aluno",
    "resolver_versao_por_matriz",
]
