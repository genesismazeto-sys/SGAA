import inspect
import os
import subprocess
import sys

import pytest
from flask import Flask

from app.web.filters import (
    append_conditions_sql,
    append_text_contains_condition,
    get_date_range_query,
    get_int_multi_query_values,
    get_multi_query_values,
    get_number_range_query,
    get_text_query_value,
)
from app.web.pagination import get_pagination, wants_pagination


app = Flask(__name__)


@pytest.mark.parametrize(
    ("query_string", "kwargs", "expected", "requested"),
    [
        ("", {}, (1, 20, 0), False),
        ("page=&per_page=", {}, (1, 20, 0), True),
        ("page=-2&per_page=0", {}, (1, 1, 0), True),
        ("page=3&per_page=500", {}, (3, 100, 200), True),
        ("page=2.5&per_page=bad", {}, (1, 20, 0), True),
        ("", {"default_per_page": 25, "max_per_page": 50}, (1, 25, 0), False),
        ("page=2&per_page=5", {}, (2, 5, 5), True),
    ],
)
def test_pagination_contract(query_string, kwargs, expected, requested):
    with app.test_request_context("/", query_string=query_string):
        assert get_pagination(**kwargs) == expected
        assert wants_pagination() is requested


def test_multi_query_values_split_trim_deduplicate_and_preserve_order():
    query = [("status", " Ativo "), ("status", "Pendente; Ativo,Cancelado"), ("status", "")]
    with app.test_request_context("/", query_string=query):
        assert get_multi_query_values("status") == ["Ativo", "Pendente", "Cancelado"]


def test_text_and_integer_query_coercion_contract():
    query = [("nome", "  Ana\t Maria  "), ("id", "1;bad"), ("id", "02"), ("id", "1")]
    with app.test_request_context("/", query_string=query):
        assert get_text_query_value("nome") == "Ana Maria"
        assert get_text_query_value("ausente") == ""
        assert get_int_multi_query_values("id") == [1, 2]


def test_number_range_contract_preserves_caster_and_invalid_behavior():
    with app.test_request_context("/", query_string="score_min=0&score_max=2.5"):
        assert get_number_range_query("score") == (0, None)
        assert get_number_range_query("score", caster=float) == (0.0, 2.5)
        assert get_number_range_query("missing") == (None, None)


def test_date_range_contract_preserves_prefix_and_invalid_behavior():
    query = "created_min=2026-07-26T23:59:00&created_max=2026-02-30"
    with app.test_request_context("/", query_string=query):
        assert get_date_range_query("created") == ("2026-07-26", None)
        assert get_date_range_query("missing") == (None, None)


def test_sql_helper_contract_preserves_exact_fragments_and_parameter_shape():
    assert append_conditions_sql(False, []) == ""
    assert append_conditions_sql(False, ["a = ?", "b = ?"]) == " WHERE a = ? AND b = ?"
    assert append_conditions_sql(True, ["a = ?", "b = ?"], joiner=" OR ") == " AND a = ? OR b = ?"

    conditions = []
    params = []
    append_text_contains_condition(conditions, params, "u.nome", "Ana")
    append_text_contains_condition(conditions, params, "u.email", "")
    assert conditions == ["LOWER(COALESCE(u.nome, '')) LIKE ?"]
    assert params == ["%ana%"]


def test_main_compatibility_exports_are_the_shared_callables():
    import main

    assert main.get_pagination is get_pagination
    assert main.wants_pagination is wants_pagination
    assert main.append_conditions_sql is append_conditions_sql
    assert main.get_multi_query_values is get_multi_query_values
    assert main.get_text_query_value is get_text_query_value
    assert main.get_int_multi_query_values is get_int_multi_query_values
    assert main.get_number_range_query is get_number_range_query
    assert main.get_date_range_query is get_date_range_query
    assert main.append_text_contains_condition is append_text_contains_condition


def test_aluno_consumers_use_shared_modules_without_lazy_main_edges():
    from app.views import aluno

    assert aluno.get_pagination is get_pagination
    assert aluno.wants_pagination is wants_pagination
    assert aluno.get_multi_query_values is get_multi_query_values
    assert aluno.get_text_query_value is get_text_query_value
    assert aluno.get_number_range_query is get_number_range_query
    assert aluno.get_date_range_query is get_date_range_query

    lazy_source = inspect.getsource(aluno._get_main_helpers)
    for symbol in (
        "get_pagination",
        "wants_pagination",
        "get_multi_query_values",
        "get_text_query_value",
        "get_number_range_query",
        "get_date_range_query",
    ):
        assert symbol not in lazy_source


def test_shared_modules_import_without_importing_main():
    env = os.environ.copy()
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            (
                "import sys; "
                "assert 'main' not in sys.modules; "
                "import app.web.pagination, app.web.filters; "
                "assert 'main' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
