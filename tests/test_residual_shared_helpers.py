import ast
import datetime
import inspect
import os
import subprocess
import sys

import pytest

from app import academics, db as app_db, presentation, reporting, requisition_policy, uploads
from app.views import aluno as aluno_views
from app.views import core as core_views
import main


EXPECTED_CATEGORY_A_LAZY_KEYS = {
    "ALLOWED_ATTACHMENTS",
    "ALLOWED_REPORTE_SCREENSHOTS",
    "DEFAULT_CURSO_TOTAL_HORAS_AAC",
    "DEFAULT_CURSO_TOTAL_HORAS_AEU",
    "REPORTE_CATEGORY_OPTIONS",
    "can_student_edit_requisition",
    "can_student_delete_requisition",
    "format_date_ptbr",
    "gerar_codigo_turma",
}
EXPECTED_CATEGORY_E_LAZY_KEYS = {
    "REPORTE_STATUS_OPTIONS",
    "save_upload",
    "app",
    "ensure_usuario_access_schema",
    "ensure_usuario_profile_schema",
}


def _lazy_return_keys(function):
    tree = ast.parse(inspect.getsource(function))
    returns = [node for node in ast.walk(tree) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)]
    assert len(returns) == 1
    return {
        key.value
        for key in returns[0].value.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("  ", ""),
        (datetime.date(2026, 7, 26), "26/07/2026"),
        (datetime.datetime(2026, 7, 26, 23, 59, 58), "26/07/2026"),
        ("2026-07-26", "26/07/2026"),
        ("2026-07-26 23:59:58", "26/07/2026"),
        ("2026-07-26T23:59:58", "26/07/2026"),
        ("  valor inválido  ", "valor inválido"),
        (123, "123"),
    ],
)
def test_presentation_format_date_ptbr_contract(value, expected):
    assert presentation.format_date_ptbr(value) == expected


def test_presentation_accepts_any_object_supporting_strftime():
    class DateLike:
        def strftime(self, pattern):
            assert pattern == "%d/%m/%Y"
            return "31/12/2042"

    assert presentation.format_date_ptbr(DateLike()) == "31/12/2042"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("2026-07-10 12:34:56", datetime.datetime(2026, 7, 10, 12, 34, 56)),
        ("2026-07-10", datetime.datetime(2026, 7, 10)),
        ("2026-07-10T12:34:56", datetime.datetime(2026, 7, 10, 12, 34, 56)),
        ("2026-07-10 trailing", datetime.datetime(2026, 7, 10)),
        ("10/07/2026", None),
        ("malformed", None),
    ],
)
def test_requisition_processing_datetime_formats(raw, expected):
    assert requisition_policy._parse_optional_processing_datetime(raw) == expected


def test_requisition_policy_status_and_fourteen_day_boundary(monkeypatch):
    class FrozenDateTime(datetime.datetime):
        current = datetime.datetime(2026, 7, 24, 12, 0, 0)

        @classmethod
        def now(cls, tz=None):
            assert tz is None
            return cls.current

    monkeypatch.setattr(requisition_policy.datetime, "datetime", FrozenDateTime)

    cases = [
        ("Pendente", None, True),
        (" Pendente ", "malformed", True),
        ("Devolvida", "2026-07-10 12:00:00", True),
        ("Devolvida", "2026-07-10 11:59:59", False),
        ("Devolvida", None, False),
        ("Devolvida", "malformed", False),
        ("Deferida", "2026-07-24 12:00:00", False),
        (None, "2026-07-24 12:00:00", False),
    ]
    for status, processed_at, expected in cases:
        assert requisition_policy.can_student_edit_requisition(status, processed_at) is expected
        assert requisition_policy.can_student_delete_requisition(status, processed_at) is expected


def test_academic_defaults_and_turma_code_contract():
    assert academics.DEFAULT_CURSO_TOTAL_HORAS_AAC == 160
    assert academics.DEFAULT_CURSO_TOTAL_HORAS_AEU == 80
    assert academics.gerar_codigo_turma("ADS", 1) == "ADS-T01"
    assert academics.gerar_codigo_turma("ADS", "09") == "ADS-T09"
    assert academics.gerar_codigo_turma("ADS", 100) == "ADS-T100"
    assert academics.gerar_codigo_turma(" ADS ", 2) == " ADS -T02"
    assert academics.gerar_codigo_turma("ADS", 1.9) == "ADS-T01"



def test_upload_policy_preserves_exact_sets_and_validation_behavior():
    assert uploads.ALLOWED_ATTACHMENTS == {"pdf", "png", "jpg", "jpeg"}
    assert uploads.ALLOWED_REPORTE_SCREENSHOTS == {"png", "jpg", "jpeg", "webp"}
    assert aluno_views._is_allowed_attachment("comprovante.PDF", uploads.ALLOWED_ATTACHMENTS)
    assert aluno_views._is_allowed_attachment("captura.WEBP", uploads.ALLOWED_REPORTE_SCREENSHOTS)
    assert not aluno_views._is_allowed_attachment("arquivo.exe", uploads.ALLOWED_ATTACHMENTS)
    assert not aluno_views._is_allowed_attachment("sem_extensao", uploads.ALLOWED_ATTACHMENTS)



def test_reporting_policy_preserves_exact_order_and_default():
    assert reporting.REPORTE_CATEGORY_OPTIONS == (
        "Bug na plataforma",
        "Problema em dados",
        "Dificuldade de uso",
        "Outro",
    )
    assert reporting.REPORTE_CATEGORY_OPTIONS[0] == "Bug na plataforma"



def test_main_preserves_all_compatibility_exports_by_identity():
    expected_exports = {
        "format_date_ptbr": presentation.format_date_ptbr,
        "_parse_optional_processing_datetime": requisition_policy._parse_optional_processing_datetime,
        "can_student_edit_requisition": requisition_policy.can_student_edit_requisition,
        "can_student_delete_requisition": requisition_policy.can_student_delete_requisition,
        "DEFAULT_CURSO_TOTAL_HORAS_AAC": academics.DEFAULT_CURSO_TOTAL_HORAS_AAC,
        "DEFAULT_CURSO_TOTAL_HORAS_AEU": academics.DEFAULT_CURSO_TOTAL_HORAS_AEU,
        "gerar_codigo_turma": academics.gerar_codigo_turma,
        "ALLOWED_ATTACHMENTS": uploads.ALLOWED_ATTACHMENTS,
        "ALLOWED_REPORTE_SCREENSHOTS": uploads.ALLOWED_REPORTE_SCREENSHOTS,
        "REPORTE_CATEGORY_OPTIONS": reporting.REPORTE_CATEGORY_OPTIONS,
    }
    for name, expected in expected_exports.items():
        assert getattr(main, name) is expected



def test_direct_app_consumers_have_no_category_a_lazy_edges_and_e_keys_are_absent():
    aluno_keys = _lazy_return_keys(aluno_views._get_main_helpers)
    core_keys = _lazy_return_keys(core_views._get_main_helpers)
    db_keys = _lazy_return_keys(app_db._get_main_db_helpers)

    assert not (aluno_keys & EXPECTED_CATEGORY_A_LAZY_KEYS)
    assert not (db_keys & EXPECTED_CATEGORY_A_LAZY_KEYS)
    assert not (aluno_keys & {"REPORTE_STATUS_OPTIONS", "save_upload", "app"})
    assert not (core_keys & {"ensure_usuario_access_schema", "ensure_usuario_profile_schema"})
    assert "ensure_reportes_table" not in aluno_keys
    assert "ensure_reportes_table" not in db_keys

    assert "ensure_usuario_profile_schema" not in aluno_keys
    assert {
        "maybe_run_versioned_resolver_shadow_read",
        "maybe_write_versioned_requisicao_snapshot",
    } <= aluno_keys
    assert {"get_db_connection", "logger", "aluno_url"} <= core_keys
    assert "ensure_usuario_profile_schema" not in db_keys
    assert "ensure_requisicao_alert_receipts_table" not in db_keys
    assert {"ensure_usuario_access_schema", "logger"} <= db_keys



def test_lazy_map_cleanup_preserves_existing_route_bindings():
    expected = {
        "/login": ("login", core_views.login),
        "/aluno/dashboard": ("aluno.aluno_dashboard", aluno_views.aluno_dashboard),
        "/aluno/reportar": ("aluno.aluno_reportar", aluno_views.aluno_reportar),
        "/aluno/requisicoes": ("aluno.aluno_minhas_requisicoes", aluno_views.aluno_minhas_requisicoes),
        "/aluno/requisicoes/<int:req_id>": ("aluno.aluno_requisicao_detalhe", aluno_views.aluno_requisicao_detalhe),
    }
    rules = {rule.rule: rule.endpoint for rule in main.app.url_map.iter_rules()}
    for rule, (endpoint, view_func) in expected.items():
        assert rules[rule] == endpoint
        assert main.app.view_functions[endpoint] is view_func



def test_new_policy_modules_import_without_importing_main():
    module_names = (
        "app.presentation",
        "app.requisition_policy",
        "app.academics",
        "app.uploads",
        "app.reporting",
    )
    code = (
        "import importlib, sys; "
        "assert 'main' not in sys.modules; "
        f"[importlib.import_module(name) for name in {module_names!r}]; "
        "assert 'main' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr
