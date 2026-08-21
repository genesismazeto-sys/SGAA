from __future__ import annotations


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
        parts.append(_MATRIZ_STATUS_LABELS.get(str(row["status"]).lower(), str(row["status"])))
    return " | ".join(parts)


def _versioning_periodo_label_for_turma_row(turma) -> str:
    inicio = None
    fim = None
    if turma["semestre_inicio"] and turma["ano_inicio"]:
        inicio = f"{turma['semestre_inicio']}S-{turma['ano_inicio']}"
    if turma["semestre_fim"] and turma["ano_fim"]:
        fim = f"{turma['semestre_fim']}S-{turma['ano_fim']}"
    if inicio and fim:
        return f"{inicio} a {fim}"
    return inicio or fim or "-"


def _serialize(row) -> dict[str, object]:
    return {
        "atividade_base_id": int(row["atividade_base_id"]),
        "atividade_base_nome": row["atividade_base_nome"],
        "nome_exibivel": row["atividade_base_nome"],
        "atividade_versao_id": int(row["atividade_versao_id"]),
        "atividade_versao_numero": int(row["atividade_versao_numero"]),
        "norma_id": int(row["norma_id"]),
        "codigo_normativo": row["codigo_normativo"],
        "norma": row["codigo_normativo"],
        "eixo": row["eixo"],
        "grupo": row["grupo"],
        "ch_por_evento": row["ch_por_evento"],
        "limite_semestre": row["limite_semestre"],
        "limite_total": row["limite_total"],
        "documentos_json": row["documentos_json"],
        "observacao_aluno": row["observacao_aluno"],
        "observacao_admin": row["observacao_admin"],
        "status": row["versao_status"],
    }


def listar_atividades_versionadas_por_matriz(conn, matriz_id: int) -> dict[str, object]:
    matriz = conn.execute("SELECT * FROM matrizes_atividades WHERE id=?", (matriz_id,)).fetchone()
    if not matriz:
        return {"status": "not_found", "matriz": None, "atividades": []}
    rows = conn.execute(
        """
        SELECT selected.atividade_base_id, selected.atividade_versao_id,
               base.nome_conceito AS atividade_base_nome,
               version.numero_versao AS atividade_versao_numero,
               version.norma_id, version.codigo_normativo, version.eixo,
               version.grupo, version.ch_por_evento, version.limite_semestre,
               version.limite_total, version.documentos_json,
               version.observacao_aluno, version.observacao_admin,
               version.status AS versao_status
          FROM matriz_atividade_versao_item selected
          JOIN atividade_base base ON base.id=selected.atividade_base_id
          JOIN atividade_versao version ON version.id=selected.atividade_versao_id
         WHERE selected.matriz_id=?
      ORDER BY version.eixo, version.grupo, base.nome_conceito
        """,
        (matriz_id,),
    ).fetchall()
    activities = [_serialize(row) for row in rows]
    by_axis = {"AAC": [], "AEU": []}
    for activity in activities:
        by_axis.setdefault(str(activity["eixo"]), []).append(activity)
    norms = []
    seen_norms = set()
    for activity in activities:
        key = (activity["norma_id"], activity["codigo_normativo"], activity["eixo"])
        if key not in seen_norms:
            seen_norms.add(key)
            norms.append({"id": key[0], "codigo": key[1], "eixo": key[2]})
    return {
        "status": "resolved",
        "matriz": {"id": int(matriz["id"]), "label": _versioning_matriz_option_label(matriz)},
        "normas": norms,
        "totais": {"geral": len(activities), "por_eixo": {k: len(v) for k, v in by_axis.items()}},
        "atividades": activities,
        "por_eixo": by_axis,
    }


def listar_atividades_versionadas_por_turma(conn, turma_id: int) -> dict[str, object]:
    turma = conn.execute(
        """
        SELECT t.*, m.nome AS matriz_nome, m.versao AS matriz_versao,
               m.status AS matriz_status
          FROM turmas t LEFT JOIN matrizes_atividades m ON m.id=t.matriz_id
         WHERE t.id=?
        """,
        (turma_id,),
    ).fetchone()
    if not turma or not turma["matriz_id"]:
        return {"status": "not_found", "turma": None, "matriz": None, "atividades": []}
    result = listar_atividades_versionadas_por_matriz(conn, int(turma["matriz_id"]))
    result["turma"] = {
        "id": int(turma["id"]), "nome": turma["nome"], "codigo": turma["codigo"]
    }
    return result


def resolver_versao_por_matriz(conn, *, matriz_id, atividade_versao_id):
    if not matriz_id or not atividade_versao_id:
        return {"status": "not_found", "reason": "exact version is required"}
    row = conn.execute(
        """
        SELECT selected.matriz_id, selected.atividade_base_id,
               version.id AS atividade_versao_id, version.numero_versao,
               version.norma_id, version.codigo_normativo, version.eixo,
               version.status AS versao_status
          FROM matriz_atividade_versao_item selected
          JOIN atividade_versao version ON version.id=selected.atividade_versao_id
         WHERE selected.matriz_id=? AND selected.atividade_versao_id=?
        """,
        (matriz_id, atividade_versao_id),
    ).fetchone()
    if not row:
        return {"status": "not_found", "reason": "version is not selected by matrix"}
    if row["versao_status"] != "ativa":
        return {"status": "inactive", "reason": "selected version is not active"}
    return {
        "status": "resolved",
        "matriz_id_efetiva": int(row["matriz_id"]),
        "atividade_base_id": int(row["atividade_base_id"]),
        "atividade_versao_id": int(row["atividade_versao_id"]),
        "atividade_versao_numero": int(row["numero_versao"]),
        "norma_id": int(row["norma_id"]),
        "codigo_normativo": row["codigo_normativo"],
        "eixo": row["eixo"],
        "warnings": [],
    }


def resolver_versao_por_aluno(conn, *, aluno_id, atividade_versao_id):
    row = conn.execute(
        """
        SELECT t.matriz_id
          FROM alunos aluno JOIN turmas t ON t.id=aluno.turma_id
         WHERE aluno.id=?
        """,
        (aluno_id,),
    ).fetchone()
    if not row or not row["matriz_id"]:
        return {"status": "not_found", "reason": "student has no effective matrix"}
    return resolver_versao_por_matriz(
        conn, matriz_id=row["matriz_id"], atividade_versao_id=atividade_versao_id
    )


__all__ = [
    "listar_atividades_versionadas_por_matriz",
    "listar_atividades_versionadas_por_turma",
    "resolver_versao_por_aluno",
    "resolver_versao_por_matriz",
]
