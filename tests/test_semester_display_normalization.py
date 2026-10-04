"""Canonical semester display normalization.

Internal authority stays ``YYYY/N`` and ``1``/``2``; every user-visible
*calendar* semester reads ``NS/YYYY`` through the single helper
``app.presentation.format_semester_label``. Curricular/course periods
(``duracao_periodos``/``periodo_corrente``, ordinals above 2) are a different
concept and must never enter this formatter. These tests pin the conversion,
the unchanged internal values, the ordinal rejection and a grep regression over
the migrated surfaces.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest

import main
from app.presentation import format_semester_label
from app.versioning.request_limits import semester_label_for_date
from app.versioning.resolver import _versioning_periodo_label_for_turma_row
from app.views.admin.alunos_turmas_cursos import _periodo_label_for_turma_row
from app.views.admin.dashboard import periodo_corrente
from tests.canonical_request_test_support import (
    create_admin_request,
    login_admin,
    login_student,
)
from tests.versioned_test_support import isolated_versioned_app_env

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "templates"
APP_DIR = PROJECT_ROOT / "app"

RAW_INTERNAL_RE = re.compile(r"\b(?:19|20)\d{2}/[12]\b")
HYPHEN_LABEL_RE = re.compile(r"\b[12]S-\d{4}\b")
JS_LABEL_RE = re.compile(r"\}S-")
ORDINAL_SEMESTER_RE = re.compile(r"\b[3-9]S[/-]\d{4}\b")


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "semester-display.db") as value:
        yield value


@pytest.mark.parametrize(
    ("internal", "expected"),
    [
        ("2025/1", "1S/2025"),
        ("2025/2", "2S/2025"),
        ("2026/1", "1S/2026"),
        ("2026/2", "2S/2026"),
        (" 2026/2 ", "2S/2026"),
    ],
)
def test_internal_semester_renders_as_human_label(internal, expected):
    assert format_semester_label(internal) == expected


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "",
        "   ",
        "2026/3",
        "2026/4",
        "2026/0",
        "26/2",
        "2026.2",
        "2026-2",
        "2S-2026",
        "3S/2026",
        "4S/2026",
        "0S/2026",
        "2026/1/2",
        "semestre 2",
        "2026/2a",
    ],
)
def test_invalid_or_empty_values_never_invent_a_semester(invalid):
    assert format_semester_label(invalid) == ""


def test_formatter_only_ever_emits_1s_or_2s():
    emitted = re.compile(r"^[12]S/\d{4}$")
    for year in range(1990, 2101):
        for semester in range(0, 10):
            label = format_semester_label(year, semester)
            assert label == "" or emitted.fullmatch(label), (year, semester, label)
            assert not ORDINAL_SEMESTER_RE.search(label)
        for ordinal in ("3", "4", "9"):
            assert format_semester_label(f"{year}/{ordinal}") == ""
            assert format_semester_label(f"{ordinal}S/{year}") == ""


def test_matrix_code_is_never_converted():
    assert format_semester_label("01.2025") == ""
    assert format_semester_label("2026.1") == ""


def test_already_human_label_is_idempotent():
    assert format_semester_label("2S/2026") == "2S/2026"
    assert format_semester_label("1S/2025") == "1S/2025"


def test_year_and_semester_pair_is_supported():
    assert format_semester_label(2026, 2) == "2S/2026"
    assert format_semester_label(2025, 1) == "1S/2025"
    assert format_semester_label(None, 2) == ""
    assert format_semester_label(2026, None) == ""


def test_internal_authority_format_is_unchanged():
    assert semester_label_for_date(datetime.date(2025, 3, 1)) == "2025/1"
    assert semester_label_for_date(datetime.date(2025, 9, 1)) == "2025/2"
    assert semester_label_for_date(datetime.date(2026, 6, 30)) == "2026/1"
    assert semester_label_for_date(datetime.date(2026, 7, 1)) == "2026/2"
    assert semester_label_for_date(None) is None


def test_jinja_filter_is_registered():
    assert "semestre_label" in main.app.jinja_env.filters
    rendered = main.app.jinja_env.from_string("{{ s|semestre_label }}").render(s="2026/2")
    assert rendered == "2S/2026"


def _turma_row(**overrides):
    row = {
        "ano_inicio": 2025,
        "semestre_inicio": 2,
        "ano_fim": 2028,
        "semestre_fim": 1,
    }
    row.update(overrides)
    return row


def test_turma_builders_treat_1_and_2_as_calendar_semester():
    row = _turma_row()
    assert _periodo_label_for_turma_row(row) == "2S/2025 a 1S/2028"
    assert _versioning_periodo_label_for_turma_row(row) == "2S/2025 a 1S/2028"


@pytest.mark.parametrize("ordinal", [0, 3, 4, 9])
def test_turma_builders_never_turn_ordinals_into_semester_labels(ordinal):
    row = _turma_row(semestre_inicio=ordinal, semestre_fim=ordinal)
    for builder in (
        _periodo_label_for_turma_row,
        _versioning_periodo_label_for_turma_row,
    ):
        label = builder(row)
        assert label == "-"
        assert not ORDINAL_SEMESTER_RE.search(label)


def test_turma_builder_ignores_only_the_out_of_range_end():
    row = _turma_row(semestre_fim=4)
    assert _periodo_label_for_turma_row(row) == "2S/2025"
    assert _versioning_periodo_label_for_turma_row(row) == "2S/2025"


def test_curricular_period_is_not_a_calendar_semester():
    assert periodo_corrente(2025, 2, ref=datetime.date(2026, 8, 10)) == 3
    assert periodo_corrente(2024, 1, ref=datetime.date(2026, 8, 10)) == 6
    for ordinal in (3, 4, 6, 9):
        assert format_semester_label(2028, ordinal) == ""
        assert format_semester_label(f"2028/{ordinal}") == ""
        assert format_semester_label(f"{ordinal}S/2028") == ""


def _current_reference_label():
    today = datetime.date.today()
    return f"{1 if today.month <= 6 else 2}S/{today.year}"


def _approve(client, name, version_id=29, hours=4):
    _, row = create_admin_request(client, name, version_id=version_id)
    response = client.post(
        f"/admin/processar_requisicao/{row['id']}",
        data={"status": "Deferida", "horas_deferidas": str(hours), "observacao": "ok"},
    )
    assert response.status_code == 302
    return row["id"]


def test_dashboard_limitation_reference_uses_human_semester(env):
    login_student(env["client"])
    html = env["client"].get("/aluno/dashboard").get_data(as_text=True)
    ref = _current_reference_label()
    assert f"Limitações - Acadêmicas Complementares (ref. {ref})</div>" in html
    assert f"Limitações - Extensão Universitária (ref. {ref})</div>" in html
    assert not RAW_INTERNAL_RE.search(html)
    assert not ORDINAL_SEMESTER_RE.search(html)


def test_progress_headers_use_human_semester_and_json_keeps_internal_keys(env):
    login_admin(env["client"])
    _approve(env["client"], "Semestre progresso")
    login_student(env["client"])

    html = env["client"].get("/aluno/progresso").get_data(as_text=True)
    assert "<th>1S/2026</th>" in html
    assert not re.search(r"<th>\d{4}/[12]</th>", html)
    assert not ORDINAL_SEMESTER_RE.search(html)

    payload = env["client"].get("/aluno/progresso?format=json").get_json()
    assert "2026/1" in payload["semestres"]


def test_admin_turma_period_display_uses_human_semester(env):
    login_admin(env["client"])

    listing = env["client"].get("/admin/turmas").get_data(as_text=True)
    assert "2S/2025" in listing and "1S/2028" in listing
    assert not HYPHEN_LABEL_RE.search(listing)
    assert not ORDINAL_SEMESTER_RE.search(listing)

    detail = env["client"].get("/admin/turma/1").get_data(as_text=True)
    assert "2S/2025 a 1S/2028" in detail
    assert not HYPHEN_LABEL_RE.search(detail)
    assert not ORDINAL_SEMESTER_RE.search(detail)


def test_cursos_duration_display_is_not_a_semester(env):
    login_admin(env["client"])
    html = env["client"].get("/admin/cursos").get_data(as_text=True)
    assert "períodos" in html
    assert not ORDINAL_SEMESTER_RE.search(html)


def test_turma_form_js_preview_uses_slash_format():
    for name in ("admin_adicionar_turma.html", "admin_editar_turma.html"):
        text = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        assert "${sEnd}S/${yEnd}" in text
        assert "${sEnd}S-${yEnd}" not in text


def _template_text_without_attribute_values(path):
    text = path.read_text(encoding="utf-8")
    return re.sub(r'="[^"]*"', '=""', text)


def test_no_template_displays_raw_or_hyphenated_semester():
    offenders = []
    for path in TEMPLATES_DIR.rglob("*.html"):
        text = _template_text_without_attribute_values(path)
        for pattern in (RAW_INTERNAL_RE, HYPHEN_LABEL_RE, JS_LABEL_RE, ORDINAL_SEMESTER_RE):
            match = pattern.search(text)
            if match:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {match.group(0)}")
    assert offenders == []


def test_no_python_module_builds_hyphenated_semester_labels():
    offenders = []
    pattern = re.compile(r"\}S-\{|\}S-\$")
    for path in APP_DIR.rglob("*.py"):
        match = pattern.search(path.read_text(encoding="utf-8"))
        if match:
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {match.group(0)}")
    assert offenders == []
