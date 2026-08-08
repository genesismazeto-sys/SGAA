from __future__ import annotations

import datetime

from app.db import DEFAULT_RETURN_RESPONSE_DAYS
from app.settings import get_response_time_settings
from app.web.urls import aluno_url
from utils.messages import resolve_user_message

# UT-6: cores do alerta automático de requisições, movidas de main.py sem
# alteração de valor.  O alerta administrativo continua em main.py.
AUTO_ALERT_YELLOW_BG = "#fef4c0"
AUTO_ALERT_YELLOW_BORDER = "#c9a227"


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


def get_student_request_update_alert(conn, aluno_id: int | None):
    if not aluno_id:
        return None

    rows = conn.execute(
        """
        SELECT id
          FROM requisicoes
         WHERE aluno_id = ?
           AND aluno_update_notified_at IS NOT NULL
           AND aluno_update_seen_at IS NULL
      ORDER BY COALESCE(aluno_update_notified_at, data_processamento, data_solicitacao) DESC,
               id DESC
        """,
        (aluno_id,),
    ).fetchall()
    if not rows:
        return None

    return {
        "requisicao_ids": [row["id"] for row in rows],
        "alerta": {
            "mensagem": resolve_user_message("Houve atualizações nas suas solicitações."),
            "bg_color": AUTO_ALERT_YELLOW_BG,
            "border_color": AUTO_ALERT_YELLOW_BORDER,
            "href": aluno_url("aluno_minhas_requisicoes"),
        },
    }


def mark_student_request_updates_seen(conn, requisicao_ids: list[int] | None):
    if not requisicao_ids:
        return

    placeholders = ", ".join("?" for _ in requisicao_ids)
    seen_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        f"UPDATE requisicoes SET aluno_update_seen_at = ? WHERE id IN ({placeholders})",
        (seen_at, *requisicao_ids),
    )


__all__ = [
    "AUTO_ALERT_YELLOW_BG",
    "AUTO_ALERT_YELLOW_BORDER",
    "auto_indefer_devolvidas",
    "get_student_request_update_alert",
    "mark_student_request_updates_seen",
]
