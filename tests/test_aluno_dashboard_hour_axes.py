"""Student dashboard hour cards follow the axes the effective Matrix offers.

An axis (AAC, AEU) counts only when the student's effective Matrix links at
least one activity version of it (app.student_hour_progress). An axis it does
not offer reads "NA" / "Não se aplica" with no percentage and no meter, and it
stays out of the total; no effective Matrix is a neutral "Matriz não
definida", never "NA". A positive target on an axis without activities is
reported as an inconsistency and left as it is.
"""
from __future__ import annotations

import logging
import re

import pytest

import main
from app.student_hour_progress import (
    APLICAVEL,
    INDEFINIDO,
    NAO_APLICAVEL,
    read_student_hour_progress,
)
from app.student_matrix import get_effective_matrix_for_student
from tests.canonical_request_test_support import login_student, student_identity
from tests.versioned_test_support import isolated_versioned_app_env

AAC = "Acadêmica Complementar"
AEU = "Extensão Universitária"


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "dashboard-hour-axes.db") as environment:
        login_student(environment["client"])
        yield environment


def _matriz_id():
    with main.app.app_context():
        conn = main.get_db_connection()
        return get_effective_matrix_for_student(conn, student_identity()["aluno_id"])["id"]


def _set_targets(aac, aeu):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE matrizes_atividades SET horas_aac_obrigatorias=?, horas_extensao_obrigatorias=? WHERE id=?",
            (aac, aeu, _matriz_id()),
        )
        conn.commit()


def _drop_axis(eixo):
    """Unlink every activity version of one axis from the student's Matrix."""
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            """DELETE FROM matriz_atividade_versao_item
                WHERE matriz_id=? AND atividade_versao_id IN
                      (SELECT id FROM atividade_versao WHERE eixo=?)""",
            (_matriz_id(), eixo),
        )
        conn.commit()


def _approved(client, eixo, horas):
    """One request created through the student route, then approved for ``horas``."""
    tipo = AAC if eixo == "AAC" else AEU
    with main.app.app_context():
        version = main.get_db_connection().execute(
            """SELECT v.id, v.grupo FROM matriz_atividade_versao_item item
                 JOIN atividade_versao v ON v.id=item.atividade_versao_id
                WHERE item.matriz_id=? AND v.eixo=? AND v.status='ativa' ORDER BY v.id LIMIT 1""",
            (_matriz_id(), eixo),
        ).fetchone()
    nome = f"Horas {eixo} {horas}"
    response = client.post("/aluno/nova-requisicao", data={
        "tipo_atividade": tipo, "grupo": version["grupo"],
        "atividade_versao_id": str(version["id"]), "nome_evento": nome,
        "data_evento": "2026-08-20", "horas_solicitadas": str(horas),
        "comprovantes_operation_id": f"axes-{eixo}-{horas}",
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE requisicoes SET status='Deferida Parcialmente', horas_deferidas=?,"
            " data_processamento=datetime('now') WHERE nome_evento=?",
            (horas, nome),
        )
        conn.commit()


def _text(fragment):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


def _card(html, kind):
    """The rendered hour card of one axis: value, secondary label, meter."""
    body = html.split(f'data-kind="{kind}">', 1)[1].split(f'data-kind="pend-{kind}"', 1)[0]
    value = re.search(r'<div class="kpi-value[^"]*">(.*?)</div>', body, re.S)
    sub = re.search(r'<div class="kpi-sub">(.*?)</div>', body, re.S)
    return {
        "value": _text(value.group(1)),
        "sub": _text(sub.group(1)),
        "meter": 'class="progress' in body,
        "percent": "%" in _text(body),
    }


def _total(html):
    body = html.split('class="dashboard-total-progress"', 1)[1].split("</section>", 1)[0]
    value = re.search(r'<span class="progress-meta-value">(.*?)</span>', body, re.S)
    return {"value": _text(value.group(1)), "meter": 'class="progress"' in body}


def _dashboard(client):
    response = client.get("/aluno/dashboard")
    assert response.status_code == 200
    return response.get_data(as_text=True)


NA = {"value": "NA", "sub": "Não se aplica", "meter": False, "percent": False}


def test_both_axes_show_numbers_and_zero_hours_is_zero_percent_not_na(env):
    _set_targets(160, 80)
    _approved(env["client"], "AAC", 16)
    html = _dashboard(env["client"])

    assert _card(html, "acad") == {"value": "16/160 h", "sub": "10% cumprido", "meter": True, "percent": True}
    # An offered axis with nothing completed yet is 0%, never NA.
    assert _card(html, "ext") == {"value": "0/80 h", "sub": "0% cumprido", "meter": True, "percent": True}
    assert _total(html) == {"value": "16/240 h (6%)", "meter": True}
    assert "Não se aplica" not in html


def test_aac_only_matrix_shows_aeu_as_na(env):
    _set_targets(160, 0)
    _drop_axis("AEU")
    _approved(env["client"], "AAC", 40)
    html = _dashboard(env["client"])

    assert _card(html, "acad") == {"value": "40/160 h", "sub": "25% cumprido", "meter": True, "percent": True}
    assert _card(html, "ext") == NA
    assert _total(html) == {"value": "40/160 h (25%)", "meter": True}


def test_aeu_only_matrix_shows_aac_as_na(env):
    _set_targets(0, 80)
    _drop_axis("AAC")
    _approved(env["client"], "AEU", 20)
    html = _dashboard(env["client"])

    assert _card(html, "acad") == NA
    assert _card(html, "ext") == {"value": "20/80 h", "sub": "25% cumprido", "meter": True, "percent": True}
    assert _total(html) == {"value": "20/80 h (25%)", "meter": True}


def test_total_excludes_the_hours_and_target_of_an_axis_the_matrix_no_longer_offers(env):
    _set_targets(160, 160)
    _approved(env["client"], "AAC", 16)
    _approved(env["client"], "AEU", 64)
    _set_targets(160, 0)
    _drop_axis("AEU")
    html = _dashboard(env["client"])

    assert _card(html, "ext") == NA
    assert _total(html) == {"value": "16/160 h (10%)", "meter": True}
    # The historical Extensão request and its approved hours are untouched.
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT status, horas_deferidas FROM requisicoes WHERE nome_evento='Horas AEU 64'"
        ).fetchone()
    assert (row["status"], row["horas_deferidas"]) == ("Deferida Parcialmente", 64)


def test_no_effective_matrix_is_undefined_not_na(env):
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE turmas SET matriz_id=NULL WHERE id=(SELECT turma_id FROM alunos WHERE id=?)",
                     (student_identity()["aluno_id"],))
        conn.commit()
        assert get_effective_matrix_for_student(conn, student_identity()["aluno_id"]) is None
    html = _dashboard(env["client"])

    undefined = {"value": "-", "sub": "Matriz não definida", "meter": False, "percent": False}
    assert _card(html, "acad") == undefined
    assert _card(html, "ext") == undefined
    assert _total(html) == {"value": "Matriz não definida", "meter": False}
    assert "NA" not in re.findall(r'<div class="kpi-value[^"]*">\s*(\w+)', html)


def test_neither_axis_offered_reads_na_everywhere(env):
    _set_targets(0, 0)
    _drop_axis("AAC")
    _drop_axis("AEU")
    html = _dashboard(env["client"])

    assert _card(html, "acad") == NA
    assert _card(html, "ext") == NA
    assert _total(html) == {"value": "NA", "meter": False}


def test_offered_axis_without_a_target_never_reads_as_complete(env):
    _set_targets(0, 80)
    _approved(env["client"], "AAC", 30)
    html = _dashboard(env["client"])

    assert _card(html, "acad") == {
        "value": "30 h", "sub": "Sem carga horária obrigatória", "meter": False, "percent": False,
    }
    # The axis without a target adds nothing to the goal and cannot inflate it.
    assert _total(html) == {"value": "0/80 h (0%)", "meter": True}


def test_target_without_activities_is_reported_and_left_unchanged(env, caplog):
    _set_targets(160, 120)
    _drop_axis("AEU")
    matriz_id = _matriz_id()
    with caplog.at_level(logging.WARNING, logger="app.student_hour_progress"):
        html = _dashboard(env["client"])
        with main.app.app_context():
            progress = read_student_hour_progress(
                main.get_db_connection(), student_identity()["aluno_id"],
                completed_aac=0, completed_aeu=0,
            )

    assert _card(html, "ext") == NA
    assert _total(html) == {"value": "0/160 h (0%)", "meter": True}
    assert progress.inconsistencies == ("AEU",)
    assert (progress.aac.state, progress.aeu.state) == (APLICAVEL, NAO_APLICAVEL)
    assert any(
        "matrix_axis_target_without_activities" in record.getMessage()
        and f"matriz_id={matriz_id!r}" in record.getMessage()
        and "axis=AEU" in record.getMessage()
        for record in caplog.records
    )
    with main.app.app_context():
        target = main.get_db_connection().execute(
            "SELECT horas_extensao_obrigatorias FROM matrizes_atividades WHERE id=?", (matriz_id,)
        ).fetchone()[0]
    assert target == 120


def test_owner_states_without_a_matrix_and_with_a_consistent_one(env):
    _set_targets(160, 80)
    with main.app.app_context():
        conn = main.get_db_connection()
        aluno_id = student_identity()["aluno_id"]
        consistent = read_student_hour_progress(conn, aluno_id, completed_aac=200, completed_aeu=0)
        conn.execute("UPDATE turmas SET matriz_id=NULL WHERE id=(SELECT turma_id FROM alunos WHERE id=?)",
                     (aluno_id,))
        conn.commit()
        undefined = read_student_hour_progress(conn, aluno_id, completed_aac=200, completed_aeu=0)

    assert consistent.inconsistencies == ()
    assert consistent.aac.pct == 100  # an axis is capped at complete
    assert {undefined.aac.state, undefined.aeu.state, undefined.total.state} == {INDEFINIDO}
    assert undefined.total.pct is None
