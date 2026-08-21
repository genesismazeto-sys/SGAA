from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import fc13_semantic_scanner as scanner


ROOT = Path(__file__).resolve().parents[1]
RETIRED_LAUNCHERS = ("run_shadow_read.bat", "tools/preflight_shadow_read.py")


def _facts(path: str, name: str) -> scanner.FunctionFacts:
    source = (ROOT / path).read_text(encoding="utf-8-sig")
    matches = [facts for facts in scanner.source_facts(source) if facts.name == name]
    assert len(matches) == 1
    return matches[0]


def _call_sites(symbol: str) -> set[tuple[str, str]]:
    result = set()
    for path in scanner.production_paths():
        relative = path.relative_to(ROOT).as_posix()
        for facts in scanner.source_facts(path.read_text(encoding="utf-8-sig")):
            if symbol in facts.calls:
                result.add((relative, facts.name))
    return result


def test_repository_has_zero_prohibited_semantic_findings():
    assert scanner.analyze_sources(scanner.repository_sources()) == set()


def test_prior_f1_f3_repairs_and_exact_resolver_ownership_remain():
    assert [path for path in RETIRED_LAUNCHERS if (ROOT / path).exists()] == []
    app_db = (ROOT / "app/db.py").read_text(encoding="utf-8-sig")
    assert "get_preferred_matriz_for_curso" not in app_db
    assert "turmas_sem_matriz" not in _facts("app/db.py", "init_db").source
    resolver_source = (ROOT / "app/versioning/resolver.py").read_text(encoding="utf-8-sig")
    names = {facts.name for facts in scanner.source_facts(resolver_source)}
    exports = scanner.explicit_exports(resolver_source)
    assert "resolver_versao" not in names | exports
    assert exports == {
        "listar_atividades_versionadas_por_matriz",
        "listar_atividades_versionadas_por_turma",
        "resolver_versao_por_aluno",
        "resolver_versao_por_matriz",
    }
    assert _call_sites("resolver_versao_por_aluno") == {
        ("app/versioning/snapshots.py", "prepare_versioned_requisicao_snapshot")
    }
    assert _call_sites("resolver_versao_por_matriz") == {
        ("app/versioning/resolver.py", "resolver_versao_por_aluno")
    }


def test_no_test_only_main_or_package_resolver_reexport_bridge():
    for relative in ("main.py", "app/versioning/__init__.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8-sig"))
        imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                   and node.module == "app.versioning.resolver" for alias in node.names]
        assert imports == []


def test_only_presentation_display_flag_remains_in_production_versioning_env_access():
    keys = {key for source in scanner.repository_sources().values()
            for facts in scanner.source_facts(source) for key in facts.env_keys
            if key.startswith("SGAA_VERSION")}
    assert keys == {scanner.DISPLAY_FLAG}


@pytest.mark.parametrize("read", [
    'flag = os.getenv("SGAA_VERSION_CANARY")',
    'flag = os.environ.get("ENABLE_BLUE_PATH")',
    'flag = os.environ["SECONDARY_EXECUTION_MODE"]',
])
def test_alternate_authority_flags_are_detected_by_control_flow(read):
    source = f'''
import os
from app.versioning import resolver as engine
def prepare_versioned_requisicao_snapshot(conn, aluno_id):
    {read}
    if flag == "1":
        return engine.resolver_versao_por_aluno(conn, aluno_id=aluno_id)
'''
    categories = {category for _, category in scanner.source_findings(source, "app/versioning/snapshots.py")}
    assert "alternate_authority_flag" in categories


@pytest.mark.parametrize("query", [
    '"SELECT * FROM atividade_versao ORDER BY numero_versao DESC LIMIT 1"',
    '"SELECT * FROM atividade_" + "versao ORDER BY id DESC LIMIT 1"',
    'f"SELECT * FROM atividade_versao WHERE atividade_base_id = {base_id} ORDER BY created_at DESC LIMIT 1"',
    '"SELECT MAX(numero_versao) FROM atividade_versao WHERE atividade_base_id = ?"',
])
def test_inline_latest_version_sql_static_forms_are_detected(query):
    source = f'''def choose(conn, base_id):
    return conn.execute({query}).fetchone()
'''
    categories = {category for _, category in scanner.source_findings(source, "app/choice.py")}
    assert "inline_latest_version_sql" in categories


def test_renamed_wrapper_reaching_inline_latest_selection_is_detected():
    source = '''
def pick(conn):
    return conn.execute("SELECT id FROM atividade_versao ORDER BY id DESC LIMIT 1").fetchone()
def route_choice(conn):
    return pick(conn)
'''
    assert ("route_choice", "resolve_time_preferred_latest_fallback") in scanner.source_findings(source, "app/choice.py")


def test_cross_module_latest_version_write_authority_is_detected():
    sources = {
        "app/activity_catalog.py": '''
def get_latest(conn, base_id):
    return conn.execute("SELECT id FROM atividade_versao WHERE atividade_base_id=? ORDER BY numero_versao DESC LIMIT 1", (base_id,)).fetchone()
''',
        "app/views/importer.py": '''
from app.activity_catalog import get_latest
def confirm(conn, base_id):
    version = get_latest(conn, base_id)
    conn.execute("UPDATE atividade_versao SET grupo=? WHERE id=?", ("2", version["id"]))
''',
    }
    assert (
        "app/views/importer.py",
        "confirm",
        "cross_module_latest_version_write_authority",
    ) in scanner.analyze_sources(sources)


def test_python_tool_launcher_resurrection_is_detected():
    sources = {"tools/new_probe.py": '''
from app.versioning import shadow_reads as history_engine
def main():
    return history_engine._read_versioned_shadow_read_events()
if __name__ == "__main__":
    main()
'''}
    categories = {category for _, _, category in scanner.analyze_sources(sources)}
    assert "python_tool_launcher_resurrection" in categories


def test_zero_caller_non_resolver_exported_facade_is_detected():
    sources = {"app/versioning/compat.py": '''
__all__ = ["compatibility_facade"]
def compatibility_facade(conn):
    return exact_or_legacy_resolver(conn)
'''}
    assert scanner.export_findings(sources) == {
        ("app/versioning/compat.py", "compatibility_facade", "zero_caller_exported_facade")
    }


def test_renamed_shadow_append_writer_is_detected():
    source = '''
from app.versioning import resolver as engine
def collect_versioned_probe(conn, aluno_id):
    value = engine.resolver_versao_por_aluno(conn, aluno_id=aluno_id)
    with open("canary.log", "a") as sink:
        sink.write(str(value))
'''
    categories = {category for _, category in scanner.source_findings(source, "app/probe.py")}
    assert {"shadow_append_writer", "unexpected_resolver_execution_bridge"} <= categories


def test_creation_flow_bridge_into_shadow_comparison_is_detected():
    source = '''
from app.versioning import shadow_reads as telemetry
def admin_nova_requisicao(conn):
    return telemetry._read_versioned_shadow_read_events()
'''
    categories = {category for _, category in scanner.source_findings(source, "app/views/admin/requisicoes.py")}
    assert "unexpected_shadow_execution_bridge" in categories


def test_old_retired_names_are_not_required_for_semantic_detection():
    source = '''
import os
def pick(conn):
    toggle = os.environ["BLUE_PATH"]
    if toggle:
        return conn.execute("SELECT id FROM atividade_versao ORDER BY id DESC LIMIT 1").fetchone()
'''
    retired = ("maybe_run_versioned_resolver_shadow_read", "resolver_versao",
               "get_preferred_matriz_for_curso", "SGAA_VERSIONED_RESOLVER_SHADOW_READ")
    assert all(name not in source for name in retired)
    assert ("pick", "inline_latest_version_sql") in scanner.source_findings(source, "app/choice.py")


def test_presentation_display_flag_control_passes():
    source = '''
import os
def show_snapshot_metadata():
    return os.getenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", "0") == "1"
'''
    assert scanner.source_findings(source, "app/presentation.py") == set()


def test_catalogue_descending_listing_without_single_authority_passes():
    source = '''
def list_versions(conn):
    return conn.execute("SELECT * FROM atividade_versao ORDER BY numero_versao DESC").fetchall()
'''
    assert scanner.source_findings(source, "app/catalogue.py") == set()


def test_harmless_python_tool_passes():
    sources = {"tools/format_report.py": '''
def main():
    print("report")
if __name__ == "__main__":
    main()
'''}
    assert scanner.analyze_sources(sources) == set()


def test_exported_callable_with_concrete_production_caller_passes():
    sources = {
        "app/versioning/api.py": '__all__ = ["exact_lookup"]\ndef exact_lookup(conn, item_id):\n    return conn.get(item_id)\n',
        "app/consumer.py": 'from app.versioning.api import exact_lookup\ndef use(conn):\n    return exact_lookup(conn, 1)\n',
    }
    assert scanner.export_findings(sources) == set()


@pytest.mark.parametrize(
    ("path", "statement", "binding", "target"),
    [
        ("app/versioning/__init__.py", "from .some_module import arbitrary_name", "arbitrary_name", "app.versioning.some_module.arbitrary_name"),
        ("app/versioning/__init__.py", "from . import some_module", "some_module", "app.versioning.some_module"),
        ("app/versioning/sub/__init__.py", "from ..other import x", "x", "app.versioning.other.x"),
        ("app/versioning/__init__.py", "from .some_module import arbitrary_name as facade", "facade", "app.versioning.some_module.arbitrary_name"),
    ],
)
def test_relative_imports_follow_python_package_depth(path, statement, binding, target):
    assert scanner.imports(ast.parse(statement), path)[binding] == target


def test_package_relative_reexport_zero_caller_arbitrary_facade_is_detected():
    sources = {
        "app/versioning/some_module.py": "def arbitrary_name(conn):\n    return some_exact_authority(conn)\n",
        "app/versioning/__init__.py": 'from .some_module import arbitrary_name\n__all__ = ["arbitrary_name"]\n',
    }
    assert scanner.export_findings(sources) == {
        ("app/versioning/__init__.py", "arbitrary_name", "zero_caller_exported_facade")
    }


def test_package_relative_reexport_chain_zero_caller_is_detected():
    sources = {
        "app/versioning/leaf.py": "def calculate(conn):\n    return exact_authority(conn)\n",
        "app/versioning/bridge.py": "from .leaf import calculate\n",
        "app/versioning/__init__.py": 'from .bridge import calculate\n__all__ = ["calculate"]\n',
    }
    assert scanner.export_findings(sources) == {
        ("app/versioning/__init__.py", "calculate", "zero_caller_exported_facade")
    }


def test_package_reexport_constants_exceptions_and_types_pass():
    sources = {
        "app/versioning/types.py": '''
from dataclasses import dataclass
LIMIT = 10
class DomainError(Exception):
    pass
@dataclass
class SnapshotType:
    value: int
''',
        "app/versioning/__init__.py": '''
from .types import LIMIT, DomainError, SnapshotType
__all__ = ["LIMIT", "DomainError", "SnapshotType"]
''',
    }
    assert scanner.export_findings(sources) == set()


def test_package_reexport_callable_with_active_production_caller_passes():
    sources = {
        "app/versioning/engine.py": "def calculate(conn):\n    return conn.get(1)\n",
        "app/versioning/__init__.py": 'from .engine import calculate\n__all__ = ["calculate"]\n',
        "app/consumer.py": "from app.versioning import calculate\ndef use(conn):\n    return calculate(conn)\n",
    }
    assert scanner.export_findings(sources) == set()


def test_package_reexport_diagnostic_callable_with_active_route_passes():
    sources = {
        "app/versioning/diagnostics.py": "def collect(conn):\n    return conn.rows()\n",
        "app/versioning/__init__.py": 'from .diagnostics import collect\n__all__ = ["collect"]\n',
        "app/views/admin/diagnostics.py": "from app.versioning import collect\ndef route(conn):\n    return collect(conn)\n",
    }
    assert scanner.export_findings(sources) == set()


@pytest.mark.parametrize(
    "tool_source",
    [
        "from app.versioning.resolver import resolver_versao_por_aluno\nresolver_versao_por_aluno(None)\n",
        'from app.versioning.resolver import resolver_versao_por_aluno\nif __name__ == "__main__":\n    resolver_versao_por_aluno(None)\n',
        "from app.versioning.resolver import resolver_versao_por_aluno as execute\nexecute(None)\n",
        "import app.versioning.resolver as engine\nengine.resolver_versao_por_aluno(None)\n",
    ],
)
def test_direct_imported_tool_authority_variants_are_detected(tool_source):
    findings = scanner.tool_findings({"tools/run.py": tool_source})
    assert {category for _, _, category in findings} >= {
        "python_tool_direct_authority_execution",
        "python_tool_launcher_resurrection",
    }


def test_tool_call_through_package_reexport_is_detected():
    sources = {
        "app/versioning/resolver.py": "def calculate(conn):\n    return conn.get(1)\n",
        "app/versioning/__init__.py": 'from .resolver import calculate\n__all__ = ["calculate"]\n',
        "tools/run.py": "from app.versioning import calculate\ncalculate(None)\n",
    }
    categories = {category for _, _, category in scanner.tool_findings(sources)}
    assert "python_tool_direct_authority_execution" in categories


def test_direct_tool_false_positive_controls_pass():
    cases = (
        {"tools/report.py": "from app.versioning.snapshots import DISPLAY_FLAG\n"},
        {"tools/report.py": "from app.versioning.resolver import resolver_versao_por_aluno\n"},
        {"tools/report.py": 'def main():\n    print("ok")\nif __name__ == "__main__":\n    main()\n'},
        {"tools/report.py": "from app.utils import format_text\nformat_text('ok')\n"},
    )
    assert all(scanner.tool_findings(sources) == set() for sources in cases)


def test_tool_authority_detection_does_not_require_historical_names():
    sources = {
        "app/versioning/engine.py": '''
def choose(conn):
    return conn.execute("SELECT id FROM atividade_versao ORDER BY id DESC LIMIT 1").fetchone()
''',
        "tools/run.py": "from app.versioning.engine import choose\nchoose(None)\n",
    }
    forbidden = ("shadow", "resolver", "legacy", "preferred", "latest", "versioned", "probe")
    assert all(term not in "choose run" for term in forbidden)
    categories = {category for _, _, category in scanner.tool_findings(sources)}
    assert "python_tool_direct_authority_execution" in categories


def _w19_export_sources() -> dict[str, str]:
    return {
        "app/versioning/source.py": "def arbitrary_name(conn):\n    return authority(conn)\n",
        "app/versioning/__init__.py": 'from .source import arbitrary_name\n__all__ = ["arbitrary_name"]\n',
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"tests/test_consumer.py": "from app.versioning import arbitrary_name\ndef test_x():\n    return arbitrary_name(None)\n"},
        {"app/unrelated.py": "def arbitrary_name():\n    return 123\ndef use_it():\n    return arbitrary_name()\n"},
        {
            "app/other_source.py": "def arbitrary_name():\n    return 123\n",
            "app/consumer.py": "from app.other_source import arbitrary_name\ndef use_it():\n    return arbitrary_name()\n",
        },
        {
            "tests/test_consumer.py": "from app.versioning import arbitrary_name\ndef test_x():\n    return arbitrary_name(None)\n",
            "app/unrelated.py": "def arbitrary_name():\n    return 123\ndef use_it():\n    return arbitrary_name()\n",
        },
    ],
)
def test_w19_tests_and_same_name_collisions_do_not_justify_export(extra):
    sources = {**_w19_export_sources(), **extra}
    assert scanner.export_findings(sources) == {
        ("app/versioning/__init__.py", "arbitrary_name", "zero_caller_exported_facade")
    }


def test_w19_chained_reexport_with_tests_only_caller_is_rejected():
    sources = {
        "app/versioning/source.py": "def calculate(conn):\n    return authority(conn)\n",
        "app/versioning/api.py": "from .source import calculate\n",
        "app/versioning/__init__.py": 'from .api import calculate\n__all__ = ["calculate"]\n',
        "tests/test_consumer.py": "from app.versioning import calculate\ndef test_x():\n    return calculate(None)\n",
    }
    assert scanner.export_findings(sources) == {
        ("app/versioning/__init__.py", "calculate", "zero_caller_exported_facade")
    }


def test_w19_unresolved_same_tail_has_no_positive_fallback():
    sources = {
        **_w19_export_sources(),
        "app/consumer.py": "def use_it():\n    return arbitrary_name()\n",
    }
    assert scanner.export_findings(sources) == {
        ("app/versioning/__init__.py", "arbitrary_name", "zero_caller_exported_facade")
    }


@pytest.mark.parametrize(
    "consumer",
    [
        "from app.versioning import arbitrary_name\ndef active(conn):\n    return arbitrary_name(conn)\n",
        "from app.versioning import arbitrary_name as execute\ndef active(conn):\n    return execute(conn)\n",
        "import app.versioning as api\ndef active(conn):\n    return api.arbitrary_name(conn)\n",
    ],
)
def test_w19_qualified_production_call_variants_are_accepted(consumer):
    sources = {**_w19_export_sources(), "app/views/admin/example.py": consumer}
    assert scanner.export_findings(sources) == set()


def test_w19_qualified_caller_survives_reexport_chain():
    sources = {
        "app/versioning/source.py": "def calculate(conn):\n    return authority(conn)\n",
        "app/versioning/api.py": "from .source import calculate\n",
        "app/versioning/__init__.py": 'from .api import calculate\n__all__ = ["calculate"]\n',
        "app/views/admin/example.py": "from app.versioning import calculate\ndef active(conn):\n    return calculate(conn)\n",
    }
    assert scanner.export_findings(sources) == set()
    assert (
        ("app.views.admin.example", "active"),
        ("app.versioning.source", "calculate"),
    ) in scanner.qualified_calls(sources)


def test_w19_active_diagnostic_qualified_caller_is_preserved():
    sources = {
        "app/versioning/source.py": "def collect(conn):\n    return conn.rows()\n",
        "app/versioning/__init__.py": 'from .source import collect\n__all__ = ["collect"]\n',
        "app/views/admin/diagnostics.py": "from app.versioning import collect\ndef active_diagnostic(conn):\n    return collect(conn)\n",
    }
    assert scanner.export_findings(sources) == set()
