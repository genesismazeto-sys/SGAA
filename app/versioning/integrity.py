# coding: utf-8
"""UT-16: dono canonico do validador de integridade do versionamento.

MOVE, DO NOT CHANGE: corpo extraido verbatim de main.py (fingerprint AST
congelado c6ad435b...). Nenhuma importacao de main; sem DDL; sem commit;
sem bootstrap; sem acoplamento Flask.
"""

from __future__ import annotations

def validar_integridade_versionamento_atividades(conn, *, raise_on_error: bool = True) -> list[str]:
    """Valida consistÃªncia estrutural do versionamento AAC/AEU sem mutar dados."""
    required_tables = ("atividade_base", "atividade_versao", "atividade_transicao")
    existing_tables = {
        row[0]
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
    missing_tables = [name for name in required_tables if name not in existing_tables]

    issues: list[str] = []
    if missing_tables:
        issues.append(
            "Schema de versionamento indisponÃ­vel para validaÃ§Ã£o: faltam as tabelas "
            + ", ".join(missing_tables)
            + "."
        )

    if not missing_tables:
        transition_rows = conn.execute(
            """
            SELECT t.id,
                   COALESCE(TRIM(t.justificativa), '') AS justificativa,
                   src.id AS from_id,
                   src.atividade_base_id AS from_base_id,
                   src.eixo AS from_eixo,
                   dst.id AS to_id,
                   dst.atividade_base_id AS to_base_id,
                   dst.eixo AS to_eixo
              FROM atividade_transicao t
              LEFT JOIN atividade_versao src ON src.id = t.from_atividade_versao_id
              LEFT JOIN atividade_versao dst ON dst.id = t.to_atividade_versao_id
             WHERE t.tipo_transicao = 'aac_para_aeu'
            """
        ).fetchall()
        for row in transition_rows:
            transition_errors = []
            if row["from_id"] is None or row["to_id"] is None:
                transition_errors.append("from/to atividade_versao ausente")
            if not row["justificativa"]:
                transition_errors.append("justificativa ausente")
            if row["from_eixo"] != "AAC" or row["to_eixo"] != "AEU":
                transition_errors.append(
                    f"eixos incompatÃ­veis ({row['from_eixo'] or 'NULL'} -> {row['to_eixo'] or 'NULL'})"
                )
            if row["from_base_id"] is None or row["to_base_id"] is None or row["from_base_id"] != row["to_base_id"]:
                transition_errors.append("atividade_base divergente entre origem e destino")
            if transition_errors:
                issues.append(
                    f"atividade_transicao {row['id']} marcada como aac_para_aeu invÃ¡lida: "
                    + "; ".join(transition_errors)
                    + "."
                )

        mixed_axis_bases = conn.execute(
            """
            SELECT av.atividade_base_id,
                   ab.nome_conceito,
                   SUM(CASE WHEN av.status = 'ativa' AND av.eixo = 'AAC' THEN 1 ELSE 0 END) AS total_aac_ativas,
                   SUM(CASE WHEN av.status = 'ativa' AND av.eixo = 'AEU' THEN 1 ELSE 0 END) AS total_aeu_ativas
              FROM atividade_versao av
              JOIN atividade_base ab ON ab.id = av.atividade_base_id
             GROUP BY av.atividade_base_id, ab.nome_conceito
            HAVING total_aac_ativas > 0
               AND total_aeu_ativas > 0
            """
        ).fetchall()
        for row in mixed_axis_bases:
            valid_transition = conn.execute(
                """
                SELECT t.id
                  FROM atividade_transicao t
                  JOIN atividade_versao src ON src.id = t.from_atividade_versao_id
                  JOIN atividade_versao dst ON dst.id = t.to_atividade_versao_id
                 WHERE t.tipo_transicao = 'aac_para_aeu'
                   AND src.atividade_base_id = ?
                   AND dst.atividade_base_id = ?
                   AND src.status = 'ativa'
                   AND dst.status = 'ativa'
                   AND src.eixo = 'AAC'
                   AND dst.eixo = 'AEU'
                   AND COALESCE(TRIM(t.justificativa), '') <> ''
                 LIMIT 1
                """,
                (row["atividade_base_id"], row["atividade_base_id"]),
            ).fetchone()
            if valid_transition is None:
                issues.append(
                    "atividade_base "
                    f"{row['atividade_base_id']} ({row['nome_conceito']}) possui versÃµes AAC/AEU ativas "
                    "sem transiÃ§Ã£o aac_para_aeu vÃ¡lida e justificada."
                )

    if issues and raise_on_error:
        raise ValueError("Integridade do versionamento de atividades invÃ¡lida:\n- " + "\n- ".join(issues))
    return issues
