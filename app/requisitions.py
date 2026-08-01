from __future__ import annotations

from app.db import DEFAULT_RETURN_RESPONSE_DAYS
from app.settings import get_response_time_settings


def auto_indefer_devolvidas(conn) -> int:
    """Indeferir automaticamente requisições Devolvidas cujo prazo de adequação expirou.

    Retorna o número de requisições alteradas.
    """
    settings = get_response_time_settings(conn)
    if not settings.get("auto_indefer_devolvida"):
        return 0
    days = int(settings.get("return_response_days") or DEFAULT_RETURN_RESPONSE_DAYS)
    if days <= 0:
        return 0

    result = conn.execute(
        """
        UPDATE requisicoes
           SET status = 'Indeferida',
               observacao = CASE
                   WHEN observacao IS NULL OR observacao = ''
                       THEN '[Indeferida automaticamente: prazo de adequação de ' || ? || ' dias expirado.]'
                   ELSE observacao || char(10) || '[Indeferida automaticamente: prazo de adequação de ' || ? || ' dias expirado.]'
               END
         WHERE status = 'Devolvida'
           AND data_processamento IS NOT NULL
           AND datetime(data_processamento) <= datetime('now', '-' || ? || ' days')
        """,
        (days, days, days),
    )
    count = result.rowcount
    if count:
        conn.commit()
    return count


__all__ = ["auto_indefer_devolvidas"]
