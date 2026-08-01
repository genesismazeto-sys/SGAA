from __future__ import annotations

import json


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
    Retorna as atividade_versao vinculadas a uma base, enriquecidas com dados da norma
    e contagem de uso em matrizes. Estritamente read-only.
    """
    return conn.execute(
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
            av.vigencia_inicio,
            av.vigencia_fim,
            av.numero_versao,
            av.status,
            av.versao_anterior_id,
            av.created_at,
            n.codigo          AS norma_codigo,
            n.nome            AS norma_nome,
            n.revisao         AS norma_revisao,
            n.status          AS norma_status,
            COUNT(DISTINCT mavi.matriz_id) AS uso_em_matrizes
          FROM atividade_versao av
          JOIN norma_atividade n ON n.id = av.norma_id
          LEFT JOIN matriz_atividade_versao_item mavi ON mavi.atividade_versao_id = av.id
         WHERE av.atividade_base_id = ?
         GROUP BY av.id
         ORDER BY av.numero_versao DESC
        """,
        (base_id,),
    ).fetchall()


def get_norma_list(conn) -> list:
    """
    Retorna todas as norma_atividade com contagem de versões vinculadas.
    Estritamente read-only.
    """
    return conn.execute(
        """
        SELECT
            n.id,
            n.codigo,
            n.eixo,
            n.revisao,
            n.nome,
            n.descricao,
            n.status,
            n.created_at,
            COUNT(av.id)                                              AS total_versoes,
            SUM(CASE WHEN av.status = 'ativa' THEN 1 ELSE 0 END)     AS versoes_ativas
          FROM norma_atividade n
          LEFT JOIN atividade_versao av ON av.norma_id = n.id
         GROUP BY n.id
         ORDER BY n.eixo ASC, LOWER(n.codigo) ASC
        """
    ).fetchall()


def get_norma_by_id(conn, norma_id: int):
    """
    Retorna uma norma_atividade pelo id, ou None.
    Estritamente read-only.
    """
    return conn.execute(
        "SELECT * FROM norma_atividade WHERE id = ?",
        (norma_id,),
    ).fetchone()


def get_versoes_da_base_por_eixo(conn, base_id: int, eixo: str) -> list:
    """
    Retorna as atividade_versao da mesma base e eixo, ordenadas por created_at DESC.
    Estritamente read-only — usado para popular versao_anterior_id.
    """
    return conn.execute(
        """
        SELECT id, codigo_normativo, eixo, status, numero_versao, created_at
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


def get_ultima_versao_ativa_por_base(conn, base_id: int):
    """Retorna a versão ativa de maior numero_versao para uma atividade_base, ou None."""
    return conn.execute(
        """
        SELECT *
          FROM atividade_versao
         WHERE atividade_base_id = ? AND status = 'ativa'
         ORDER BY numero_versao DESC
         LIMIT 1
        """,
        (base_id,),
    ).fetchone()


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
               src.codigo_normativo AS from_codigo_normativo,
               src.eixo AS from_eixo,
               dst.id AS to_id,
               dst.atividade_base_id AS to_base_id,
               dst.codigo_normativo AS to_codigo_normativo,
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
            from_label = row["from_codigo_normativo"] or f"Versão #{row['from_id']}"
        to_label = "-"
        if row["to_id"] is not None:
            to_label = row["to_codigo_normativo"] or f"Versão #{row['to_id']}"
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


def get_legacy_map_list(conn) -> list:
    """
    Retorna as atividades legadas com seus dados de mapeamento
    (LEFT JOIN em atividade_legacy_map) e contagem de requisições existentes.
    Estritamente read-only — não cria nenhuma entrada em atividade_legacy_map.
    """
    return conn.execute(
        """
        SELECT
            a.id                     AS atividade_id,
            a.nome                   AS atividade_nome,
            a.tipo_atividade,
            a.grupo,
            alm.id                   AS mapa_id,
            alm.status               AS mapa_status,
            alm.atividade_base_id    AS base_id,
            ab.nome_conceito         AS base_nome,
            alm.observacao_admin,
            alm.created_at           AS mapa_criado_em,
            COUNT(r.id)              AS qtd_requisicoes
          FROM atividades a
          LEFT JOIN atividade_legacy_map alm ON alm.atividade_id_legacy = a.id
          LEFT JOIN atividade_base ab ON ab.id = alm.atividade_base_id
          LEFT JOIN requisicoes r ON r.atividade_id = a.id
         GROUP BY a.id
         ORDER BY
            CASE COALESCE(alm.status, 'sem_mapa')
                WHEN 'pendente'   THEN 0
                WHEN 'revisar'    THEN 1
                WHEN 'sem_mapa'   THEN 2
                WHEN 'mapeada'    THEN 3
                ELSE 4
            END ASC,
            LOWER(a.nome) ASC
        """
    ).fetchall()


__all__ = [
    'parse_documentos_json',
    '_normalize_atividade_grupo',
    'get_atividade_base_list',
    'get_atividade_base',
    'get_versoes_por_base',
    'get_norma_list',
    'get_norma_by_id',
    'get_versoes_da_base_por_eixo',
    'get_next_numero_versao',
    'get_ultima_versao_ativa_por_base',
    'get_atividade_versao_by_id',
    'get_atividade_versao_usage_counts',
    'get_atividade_transicoes_por_base',
    'get_legacy_map_list',
]
