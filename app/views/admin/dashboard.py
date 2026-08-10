# coding: utf-8
"""UT-13: dono canonico do cohort "Dashboard".

10 simbolos relocados de main.py por MOVE-VERBATIM (1 rota e 9 helpers).
Nenhuma importacao de main; registra apenas rotas legadas via
LegacyRouteSpec.
"""

from __future__ import annotations

import datetime
import time
from datetime import date

from flask import (
    Blueprint,
    g,
    render_template,
    session,
    url_for,
)

from app.academics import (
    DEFAULT_CURSO_TOTAL_HORAS_AAC,
    DEFAULT_CURSO_TOTAL_HORAS_AEU,
)
from app.admin_alerts import list_active_admin_alertas
from app.auth import (
    admin_required,
    canonicalize_access_level,
    default_access_level_for_user_type,
)
from app.db import (
    ensure_turmas_matriz_schema,
    get_db_connection,
)
from app.db_maintenance import ensure_requisicao_alert_receipts_table
from app.matrix_scope import get_effective_matriz_for_turma
from app.requisition_policy import _parse_optional_processing_datetime
from app.requisitions import (
    AUTO_ALERT_YELLOW_BG,
    AUTO_ALERT_YELLOW_BORDER,
    auto_indefer_devolvidas,
)
from app.settings import get_response_time_settings
from app.views.admin import LegacyRouteSpec, configure_legacy_routes
from utils.messages import resolve_user_message


def _calculate_pending_response_metrics(conn, *, goal_days: int, reset_at: str = "") -> tuple[float, int]:
    rows = conn.execute(
        """
        SELECT data_solicitacao
          FROM requisicoes
         WHERE status = 'Pendente'
           AND data_solicitacao IS NOT NULL
        """
    ).fetchall()

    reset_dt = None
    if reset_at:
        try:
            reset_dt = datetime.datetime.strptime(reset_at, "%Y-%m-%d")
        except ValueError:
            reset_dt = None

    now_dt = datetime.datetime.now()
    ages = []
    overdue_count = 0
    for row in rows:
        requested_at = _parse_optional_processing_datetime(row["data_solicitacao"])
        if not requested_at:
            continue
        effective_start = reset_dt if reset_dt and requested_at < reset_dt else requested_at
        age_days = max(0.0, (now_dt - effective_start).total_seconds() / 86400.0)
        ages.append(age_days)
        if age_days > goal_days:
            overdue_count += 1

    avg_days = (sum(ages) / len(ages)) if ages else 0.0
    return avg_days, overdue_count


def _admin_request_alert_kind(access_level: str | None) -> str | None:
    normalized = canonicalize_access_level(access_level, default_access_level_for_user_type("admin"))
    if normalized == "admin_total":
        return "admin_new_request"
    if normalized == "administrativo":
        return "coordinator_new_request"
    return None


def get_admin_new_request_alert(conn, usuario_id: int | None, access_level: str | None):
    alert_kind = _admin_request_alert_kind(access_level)
    if not usuario_id or not alert_kind:
        return None

    ensure_requisicao_alert_receipts_table(conn)
    rows = conn.execute(
        """
        SELECT r.id
          FROM requisicoes r
         WHERE r.status = 'Pendente'
           AND NOT EXISTS (
                SELECT 1
                  FROM requisicao_alerta_receipts receipts
                 WHERE receipts.requisicao_id = r.id
                   AND receipts.usuario_id = ?
                   AND receipts.alert_kind = ?
           )
      ORDER BY COALESCE(r.data_solicitacao, '') DESC,
               r.id DESC
        """,
        (usuario_id, alert_kind),
    ).fetchall()
    if not rows:
        return None

    return {
        "requisicao_ids": [row["id"] for row in rows],
        "alerta": {
            "mensagem": resolve_user_message("Há novas solicitações aguardando análise."),
            "bg_color": AUTO_ALERT_YELLOW_BG,
            "border_color": AUTO_ALERT_YELLOW_BORDER,
            "href": url_for("admin_requisicoes"),
        },
    }


def mark_admin_new_request_alert_seen(
    conn,
    requisicao_ids: list[int] | None,
    usuario_id: int | None,
    access_level: str | None,
):
    alert_kind = _admin_request_alert_kind(access_level)
    if not requisicao_ids or not usuario_id or not alert_kind:
        return

    ensure_requisicao_alert_receipts_table(conn)
    seen_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.executemany(
        """
        INSERT OR IGNORE INTO requisicao_alerta_receipts (requisicao_id, usuario_id, alert_kind, seen_at)
        VALUES (?, ?, ?, ?)
        """,
        [(requisicao_id, usuario_id, alert_kind, seen_at) for requisicao_id in requisicao_ids],
    )


def periodo_corrente(ano_inicio: int | None, semestre_inicio: int | None, ref: date | None = None) -> int:
    """Período da turma contando a partir do (ano_inicio, semestre_inicio). Começa em 1."""
    if not ano_inicio or not semestre_inicio:
        return 1
    if ref is None:
        ref = date.today()
    sem_ref = 1 if ref.month <= 6 else 2
    delta = (ref.year - int(ano_inicio)) * 2 + (sem_ref - int(semestre_inicio))
    return max(1, delta + 1)


def _format_dashboard_hours(value) -> str:
    total = float(value or 0)
    if total.is_integer():
        return str(int(total))
    return f"{total:.1f}".rstrip("0").rstrip(".")


def _format_dashboard_average(value) -> str:
    return f"{float(value or 0):.1f}".replace(".", ",")


def _format_dashboard_days(value) -> str:
    total = float(value or 0)
    if total.is_integer():
        return str(int(total))
    return f"{total:.1f}".replace(".", ",")


def _build_admin_dashboard_turma_cards(conn):
    ensure_turmas_matriz_schema(conn)

    attainment_bucket_specs = (
        {"label": "100%", "color": "#003366"},
        {"label": "75 a 100%", "color": "#2f6fa3"},
        {"label": "50 a 75%", "color": "#4d8cb5"},
        {"label": "25 a 50%", "color": "#d08b2f"},
        {"label": "0 a 25%", "color": "#cbd5e1"},
    )

    turma_rows = conn.execute(
        """
        SELECT t.id,
               t.nome,
               t.codigo,
               t.status,
               t.curso_id,
               t.matriz_id,
               t.ano_inicio,
               t.semestre_inicio,
               COUNT(a.id) AS total_alunos
               ,COALESCE(SUM(CASE WHEN a.status = 'Ativo' THEN 1 ELSE 0 END), 0) AS total_alunos_ativos
          FROM turmas t
          LEFT JOIN alunos a ON a.turma_id = t.id
      GROUP BY t.id, t.nome, t.codigo, t.status, t.curso_id, t.matriz_id, t.ano_inicio, t.semestre_inicio
      ORDER BY LOWER(COALESCE(t.codigo, t.nome, '')) ASC,
               t.id ASC
        """
    ).fetchall()

    if not turma_rows:
        return [], None, {
            "total_turmas": 0,
            "total_turmas_ativas": 0,
            "turmas_com_aac": 0,
            "turmas_com_aeu": 0,
            "media_alunos_por_turma_fmt": _format_dashboard_average(0),
        }

    pendentes_por_turma = {
        row["turma_id"]: int(row["pendentes"] or 0)
        for row in conn.execute(
            """
            SELECT a.turma_id, COUNT(*) AS pendentes
              FROM requisicoes r
              JOIN alunos a ON a.id = r.aluno_id
             WHERE a.turma_id IS NOT NULL
               AND r.status = 'Pendente'
          GROUP BY a.turma_id
            """
        ).fetchall()
    }

    horas_por_turma = {}
    for row in conn.execute(
        """
        SELECT a.turma_id,
               act.tipo_atividade,
               SUM(COALESCE(r.horas_deferidas, r.horas_solicitadas, 0)) AS total_horas
          FROM requisicoes r
          JOIN alunos a ON a.id = r.aluno_id
          JOIN atividades act ON act.id = r.atividade_id
         WHERE a.turma_id IS NOT NULL
           AND r.status IN ('Deferida', 'Deferida Parcialmente')
      GROUP BY a.turma_id, act.tipo_atividade
        """
    ).fetchall():
        turma_metrics = horas_por_turma.setdefault(
            row["turma_id"],
            {"aac_hours": 0.0, "aeu_hours": 0.0},
        )
        if row["tipo_atividade"] == "Acadêmica Complementar":
            turma_metrics["aac_hours"] = float(row["total_horas"] or 0)
        elif row["tipo_atividade"] == "Extensão Universitária":
            turma_metrics["aeu_hours"] = float(row["total_horas"] or 0)

    active_student_ids_by_turma = {}
    for row in conn.execute(
        """
        SELECT id, turma_id
          FROM alunos
         WHERE turma_id IS NOT NULL
           AND status = 'Ativo'
        """
    ).fetchall():
        active_student_ids_by_turma.setdefault(row["turma_id"], []).append(row["id"])

    horas_por_aluno = {}
    for row in conn.execute(
        """
        SELECT r.aluno_id,
               act.tipo_atividade,
               SUM(COALESCE(r.horas_deferidas, r.horas_solicitadas, 0)) AS total_horas
          FROM requisicoes r
          JOIN atividades act ON act.id = r.atividade_id
          JOIN alunos a ON a.id = r.aluno_id
         WHERE a.turma_id IS NOT NULL
           AND a.status = 'Ativo'
           AND r.status IN ('Deferida', 'Deferida Parcialmente')
      GROUP BY r.aluno_id, act.tipo_atividade
        """
    ).fetchall():
        aluno_metrics = horas_por_aluno.setdefault(
            row["aluno_id"],
            {"aac_hours": 0.0, "aeu_hours": 0.0},
        )
        if row["tipo_atividade"] == "Acadêmica Complementar":
            aluno_metrics["aac_hours"] = float(row["total_horas"] or 0)
        elif row["tipo_atividade"] == "Extensão Universitária":
            aluno_metrics["aeu_hours"] = float(row["total_horas"] or 0)

    turma_cards = []
    total_alunos = 0
    total_pendentes = 0
    total_ch = 0.0
    total_aac_denominador = 0.0
    total_aeu_denominador = 0.0
    total_aac_hours = 0.0
    total_aeu_hours = 0.0
    total_turmas = len(turma_rows)
    total_turmas_ativas = 0
    turmas_com_aac = 0
    turmas_com_aeu = 0
    total_aac_applicables = 0
    total_aeu_applicables = 0

    for row in turma_rows:
        turma_id = row["id"]
        turma_label = (row["codigo"] or row["nome"] or "").strip() or f"Turma {turma_id}"
        turma_alunos = int(row["total_alunos"] or 0)
        turma_alunos_ativos = int(row["total_alunos_ativos"] or 0)
        turma_horas = horas_por_turma.get(turma_id, {})
        aac_hours = float(turma_horas.get("aac_hours", 0) or 0)
        aeu_hours = float(turma_horas.get("aeu_hours", 0) or 0)
        ch_total = aac_hours + aeu_hours
        pendentes = int(pendentes_por_turma.get(turma_id, 0) or 0)
        periodo_atual_label = "-"
        if row["ano_inicio"] and row["semestre_inicio"]:
            periodo_atual_label = f"{periodo_corrente(row['ano_inicio'], row['semestre_inicio'])}º período"

        matriz = get_effective_matriz_for_turma(conn, row["curso_id"], row["matriz_id"])
        meta_aac = float(
            matriz["horas_aac_obrigatorias"]
            if matriz and matriz["horas_aac_obrigatorias"] is not None
            else DEFAULT_CURSO_TOTAL_HORAS_AAC
        )
        meta_aeu = float(
            matriz["horas_extensao_obrigatorias"]
            if matriz and matriz["horas_extensao_obrigatorias"] is not None
            else DEFAULT_CURSO_TOTAL_HORAS_AEU
        )
        aac_applicable = meta_aac > 0
        aeu_applicable = meta_aeu > 0
        meta_aac_total = meta_aac * turma_alunos
        meta_aeu_total = meta_aeu * turma_alunos
        aac_pct = int((aac_hours * 100) // meta_aac_total) if aac_applicable and meta_aac_total > 0 else 0
        aeu_pct = int((aeu_hours * 100) // meta_aeu_total) if aeu_applicable and meta_aeu_total > 0 else 0
        meta_total_por_aluno = (meta_aac if aac_applicable else 0.0) + (meta_aeu if aeu_applicable else 0.0)
        meta_total_turma = meta_total_por_aluno * turma_alunos
        total_applicable = meta_total_por_aluno > 0
        total_pct = int((ch_total * 100) // meta_total_turma) if total_applicable and meta_total_turma > 0 else 0

        attainment_buckets = [
            {"label": bucket["label"], "color": bucket["color"], "count": 0, "share_pct": 0}
            for bucket in attainment_bucket_specs
        ]
        attainment_pct_total = 0.0
        active_student_ids = active_student_ids_by_turma.get(turma_id, [])
        for aluno_id in active_student_ids:
            aluno_horas = horas_por_aluno.get(aluno_id, {})
            aluno_total_horas = float(aluno_horas.get("aac_hours", 0) or 0) + float(aluno_horas.get("aeu_hours", 0) or 0)
            aluno_pct_total = min(100.0, (aluno_total_horas * 100.0) / meta_total_por_aluno) if meta_total_por_aluno > 0 else 0.0
            attainment_pct_total += aluno_pct_total

            if aluno_pct_total >= 100:
                bucket_index = 0
            elif aluno_pct_total >= 75:
                bucket_index = 1
            elif aluno_pct_total >= 50:
                bucket_index = 2
            elif aluno_pct_total >= 25:
                bucket_index = 3
            else:
                bucket_index = 4
            attainment_buckets[bucket_index]["count"] += 1

        attainment_avg_pct = int(round(attainment_pct_total / turma_alunos_ativos)) if turma_alunos_ativos else 0
        donut_gradient_parts = []
        if turma_alunos_ativos:
            start_pct = 0.0
            for bucket in attainment_buckets:
                bucket["share_pct"] = int(round((bucket["count"] * 100.0) / turma_alunos_ativos))
                if bucket["count"] <= 0:
                    continue
                sweep_pct = (bucket["count"] * 100.0) / turma_alunos_ativos
                end_pct = start_pct + sweep_pct
                donut_gradient_parts.append(f"{bucket['color']} {start_pct:.2f}% {end_pct:.2f}%")
                start_pct = end_pct
            if start_pct < 100.0:
                donut_gradient_parts.append(f"#e8edf3 {start_pct:.2f}% 100%")
        else:
            donut_gradient_parts.append("#e8edf3 0% 100%")
        attainment_donut_gradient = f"conic-gradient({', '.join(donut_gradient_parts)})"

        turma_cards.append(
            {
                "id": turma_id,
                "label": turma_label,
                "total_alunos": turma_alunos,
                "total_alunos_ativos": turma_alunos_ativos,
                "periodo_atual_label": periodo_atual_label,
                "aac_hours_fmt": _format_dashboard_hours(aac_hours),
                "aeu_hours_fmt": _format_dashboard_hours(aeu_hours),
                "ch_total_fmt": _format_dashboard_hours(ch_total),
                "aac_applicable": aac_applicable,
                "aeu_applicable": aeu_applicable,
                "aac_pct": min(100, aac_pct),
                "aeu_pct": min(100, aeu_pct),
                "total_applicable": total_applicable,
                "total_pct": min(100, total_pct),
                "attainment_buckets": attainment_buckets,
                "attainment_avg_pct_label": f"{attainment_avg_pct}%",
                "attainment_donut_gradient": attainment_donut_gradient,
                "pendentes": pendentes,
            }
        )

        total_alunos += turma_alunos
        total_pendentes += pendentes
        total_ch += ch_total
        if aac_applicable:
            total_aac_hours += aac_hours
            total_aac_denominador += meta_aac_total
            total_aac_applicables += 1
        if aeu_applicable:
            total_aeu_hours += aeu_hours
            total_aeu_denominador += meta_aeu_total
            total_aeu_applicables += 1

        if (row["status"] or "") == "Ativa":
            total_turmas_ativas += 1
            if aac_applicable:
                turmas_com_aac += 1
            if aeu_applicable:
                turmas_com_aeu += 1

    total_geral = None
    if len(turma_cards) % 2 == 1:
        total_geral = {
            "label": "Total Geral",
            "total_alunos": total_alunos,
            "aac_applicable": total_aac_applicables > 0,
            "aeu_applicable": total_aeu_applicables > 0,
            "aac_pct": min(100, int((total_aac_hours * 100) // total_aac_denominador)) if total_aac_denominador > 0 else 0,
            "aeu_pct": min(100, int((total_aeu_hours * 100) // total_aeu_denominador)) if total_aeu_denominador > 0 else 0,
            "ch_total_fmt": _format_dashboard_hours(total_ch),
            "pendentes": total_pendentes,
        }

    return turma_cards, total_geral, {
        "total_turmas": total_turmas,
        "total_turmas_ativas": total_turmas_ativas,
        "turmas_com_aac": turmas_com_aac,
        "turmas_com_aeu": turmas_com_aeu,
        "media_alunos_por_turma_fmt": _format_dashboard_average(total_alunos / total_turmas if total_turmas else 0),
    }


@admin_required
def admin_dashboard():
    conn = get_db_connection()
    ensure_requisicao_alert_receipts_table(conn)
    response_time_settings = get_response_time_settings(conn)
    auto_indefer_devolvidas(conn)
    usuario_id = session.get("user_id")
    access_level = session.get("access_level")
    if usuario_id:
        usuario = conn.execute("SELECT nivel_acesso FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if usuario:
            access_level = usuario["nivel_acesso"]
    alertas_ativos = list(list_active_admin_alertas(conn))
    new_request_alert = get_admin_new_request_alert(conn, usuario_id, access_level)
    if new_request_alert:
        alertas_ativos.insert(0, new_request_alert["alerta"])
        mark_admin_new_request_alert_seen(conn, new_request_alert["requisicao_ids"], usuario_id, access_level)
        conn.commit()
    now = time.time()
    metrics = getattr(g, '_adm_dash_metrics', None)
    ts = getattr(g, '_adm_dash_ts', 0)
    if not metrics or now - ts >= 30:
        metrics = {}
        metrics['total_alunos'] = conn.execute("SELECT COUNT(*) FROM alunos").fetchone()[0]
        metrics['total_atividades_academicas'] = conn.execute("SELECT COUNT(*) FROM atividades WHERE tipo_atividade = 'Acadêmica Complementar'").fetchone()[0]
        metrics['total_atividades_extensao'] = conn.execute("SELECT COUNT(*) FROM atividades WHERE tipo_atividade = 'Extensão Universitária'").fetchone()[0]
        metrics['total_atividades'] = metrics['total_atividades_academicas'] + metrics['total_atividades_extensao']
        metrics['total_requisicoes'] = conn.execute("SELECT COUNT(*) FROM requisicoes").fetchone()[0]
        metrics['requisicoes_pendentes'] = conn.execute("SELECT COUNT(*) FROM requisicoes WHERE status = 'Pendente'").fetchone()[0]
        avg_pending_response_days, overdue_pending_count = _calculate_pending_response_metrics(
            conn,
            goal_days=response_time_settings["response_goal_days"],
            reset_at=str(response_time_settings["response_metrics_reset_at"] or ""),
        )
        metrics['tempo_medio_resposta_dias'] = avg_pending_response_days
        metrics['tempo_medio_resposta_dias_fmt'] = _format_dashboard_days(avg_pending_response_days)
        metrics['tempo_medio_resposta_meta_dias'] = response_time_settings["response_goal_days"]
        metrics['tempo_medio_resposta_apuracao_inicio'] = response_time_settings["response_metrics_reset_at"]
        metrics['tempo_medio_resposta_apuracao_inicio_fmt'] = response_time_settings["response_metrics_reset_at_fmt"]
        metrics['tempo_medio_resposta_meta_excedida'] = avg_pending_response_days > response_time_settings["response_goal_days"]
        metrics['requisicoes_devolvidas_abertas'] = conn.execute("SELECT COUNT(*) FROM requisicoes WHERE status = 'Devolvida'").fetchone()[0]
        metrics['requisicoes_atrasadas_meta_dias'] = overdue_pending_count
        metrics['requisicoes_academicas'] = conn.execute("SELECT COUNT(*) FROM requisicoes r JOIN atividades a ON r.atividade_id = a.id WHERE a.tipo_atividade = 'Acadêmica Complementar'").fetchone()[0]
        metrics['requisicoes_extensao'] = conn.execute("SELECT COUNT(*) FROM requisicoes r JOIN atividades a ON r.atividade_id = a.id WHERE a.tipo_atividade = 'Extensão Universitária'").fetchone()[0]
        metrics['turma_cards'], metrics['dashboard_total_geral'], turma_summary = _build_admin_dashboard_turma_cards(conn)
        metrics.update(turma_summary)
        g._adm_dash_metrics = metrics
        g._adm_dash_ts = now

    return render_template("admin_dashboard.html",
                           total_alunos=metrics['total_alunos'],
                           total_atividades=metrics['total_atividades'],
                           total_atividades_academicas=metrics['total_atividades_academicas'],
                           total_atividades_extensao=metrics['total_atividades_extensao'],
                           total_requisicoes=metrics['total_requisicoes'],
                           requisicoes_pendentes=metrics['requisicoes_pendentes'],
                           tempo_medio_resposta_dias=metrics['tempo_medio_resposta_dias'],
                           tempo_medio_resposta_dias_fmt=metrics['tempo_medio_resposta_dias_fmt'],
                           tempo_medio_resposta_meta_dias=metrics['tempo_medio_resposta_meta_dias'],
                           tempo_medio_resposta_apuracao_inicio=metrics['tempo_medio_resposta_apuracao_inicio'],
                           tempo_medio_resposta_apuracao_inicio_fmt=metrics['tempo_medio_resposta_apuracao_inicio_fmt'],
                           tempo_medio_resposta_meta_excedida=metrics['tempo_medio_resposta_meta_excedida'],
                           requisicoes_devolvidas_abertas=metrics['requisicoes_devolvidas_abertas'],
                           requisicoes_atrasadas_meta_dias=metrics['requisicoes_atrasadas_meta_dias'],
                           requisicoes_academicas=metrics['requisicoes_academicas'],
                           requisicoes_extensao=metrics['requisicoes_extensao'],
                           total_turmas=metrics['total_turmas'],
                           total_turmas_ativas=metrics['total_turmas_ativas'],
                           turmas_com_aac=metrics['turmas_com_aac'],
                           turmas_com_aeu=metrics['turmas_com_aeu'],
                           media_alunos_por_turma_fmt=metrics['media_alunos_por_turma_fmt'],
                           turma_cards=metrics['turma_cards'],
                           dashboard_total_geral=metrics['dashboard_total_geral'],
                           alertas_ativos=alertas_ativos)


bp_admin_dashboard = Blueprint(
    "admin_dashboard_blueprint",
    __name__,
)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_dashboard,
    (
        LegacyRouteSpec(
            "/admin/dashboard",
            "admin_dashboard",
            admin_dashboard,
            ("GET",),
        ),
    ),
)
