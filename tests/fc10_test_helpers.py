"""Small test-only builders for normal request snapshot authority."""

from __future__ import annotations

import uuid


def add_exact_snapshot_authority(conn, *, matriz_id: int, atividade_id: int, prefix: str) -> int:
    """Attach one active, exact Matrix-linked version to a legacy activity."""
    token = uuid.uuid4().hex[:10]
    base_id = conn.execute(
        """
        INSERT INTO atividade_base (nome_conceito, descricao, status)
        VALUES (?, ?, 'ativo') RETURNING id
        """,
        (f"{prefix} base {token}", f"{prefix} snapshot base"),
    ).fetchone()["id"]
    version_id = conn.execute(
        """
        INSERT INTO atividade_versao (
            atividade_base_id, eixo, grupo,
            ch_por_evento, limite_semestre, limite_total,
            observacao_aluno, observacao_admin, documentos_json,
            numero_versao, status
        ) VALUES (?, 'AAC', '1 - FC10', 4, 40, 100, ?, ?, NULL, 1, 'ativa')
        RETURNING id
        """,
        (
            base_id,
            f"Aluno rule {token}",
            f"Admin rule {token}",
        ),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO matriz_atividade_versao_item "
        "(matriz_id, atividade_base_id, atividade_versao_id) VALUES (?, ?, ?)",
        (matriz_id, base_id, version_id),
    )
    return int(version_id)
