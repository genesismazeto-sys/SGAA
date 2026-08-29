from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "main.py"
ACADEMICS_PATH = PROJECT_ROOT / "app" / "academics.py"
USER_ACCOUNTS_PATH = PROJECT_ROOT / "app" / "user_accounts.py"
WEB_REQUEST_PATH = PROJECT_ROOT / "app" / "web" / "request.py"
CORE_PATH = PROJECT_ROOT / "app" / "views" / "core.py"
AUTH_PATH = PROJECT_ROOT / "app" / "auth.py"
DB_MAINT_PATH = PROJECT_ROOT / "app" / "db_maintenance.py"


ACADEMICS_OWNED = {
    "build_turma_aluno_matricula",
    "resequence_turma_aluno_matriculas",
    "resequence_turma_aluno_matriculas_for_ids",
}
USER_ACCOUNTS_OWNED = {
    "_access_defaults_map",
    "_default_password_for_user_type",
    "create_usuario_with_default_access",
    "create_usuario_with_default_password",
    "normalize_usuario_access_for_user_type",
}
WEB_REQUEST_OWNED = {
    "_is_ajax_request",
}
NINE_SYMBOLS = ACADEMICS_OWNED | USER_ACCOUNTS_OWNED | WEB_REQUEST_OWNED


def _top_level_functions(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _lazy_return_keys(function):
    tree = ast.parse(inspect.getsource(function))
    returns = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
    ]
    assert len(returns) == 1
    return {
        key.value
        for key in returns[0].value.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _import_aliases(path: Path, module_name: str) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    names = set()
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != module_name:
            continue
        for alias in node.names:
            names.add(alias.asname or alias.name)
    return names


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _no_main_import(path: Path) -> bool:
    return "import main" not in _source(path)


# ---- Ownership / identity contract ----


def test_exact_nine_symbol_move_and_owners():
    assert len(ACADEMICS_OWNED) == 3
    assert len(USER_ACCOUNTS_OWNED) == 5
    assert len(WEB_REQUEST_OWNED) == 1
    assert len(NINE_SYMBOLS) == 9

    assert ACADEMICS_OWNED <= _top_level_functions(ACADEMICS_PATH)
    assert USER_ACCOUNTS_OWNED <= _top_level_functions(USER_ACCOUNTS_PATH)
    assert WEB_REQUEST_OWNED <= _top_level_functions(WEB_REQUEST_PATH)

    assert not NINE_SYMBOLS & _top_level_functions(MAIN_PATH)


def test_no_local_main_function_for_the_nine():
    assert not NINE_SYMBOLS & _top_level_functions(MAIN_PATH)


def test_periodo_corrente_ownership_state_aware():
    # UT-13 seam: periodo_corrente moved to app.views.admin.dashboard once the
    # target exists; before extraction it stays main-local.  Expected state
    # derives from REAL target availability.
    dashboard_path = PROJECT_ROOT / "app" / "views" / "admin" / "dashboard.py"
    assert "periodo_corrente" not in _top_level_functions(ACADEMICS_PATH)
    assert "periodo_corrente" not in _top_level_functions(USER_ACCOUNTS_PATH)
    assert "periodo_corrente" not in _top_level_functions(WEB_REQUEST_PATH)
    if dashboard_path.exists():
        assert "periodo_corrente" in _top_level_functions(dashboard_path)
        assert "periodo_corrente" not in _top_level_functions(MAIN_PATH)
        import importlib
        import main

        dashboard = importlib.import_module("app.views.admin.dashboard")
        assert main.periodo_corrente is dashboard.periodo_corrente, (
            "main.periodo_corrente must identity-re-export "
            "dashboard.periodo_corrente"
        )
    else:
        assert "periodo_corrente" in _top_level_functions(MAIN_PATH)
        assert "periodo_corrente" not in _top_level_functions(dashboard_path)


def test_main_reexports_all_nine_by_identity():
    import main
    from app import academics, user_accounts
    from app.web import request as web_request

    owners = {
        "build_turma_aluno_matricula": academics,
        "resequence_turma_aluno_matriculas": academics,
        "resequence_turma_aluno_matriculas_for_ids": academics,
        "_access_defaults_map": user_accounts,
        "_default_password_for_user_type": user_accounts,
        "create_usuario_with_default_access": user_accounts,
        "create_usuario_with_default_password": user_accounts,
        "normalize_usuario_access_for_user_type": user_accounts,
        "_is_ajax_request": web_request,
    }
    for name, owner in owners.items():
        assert getattr(main, name) is getattr(owner, name)


def test_main_imports_all_nine_from_owners():
    assert ACADEMICS_OWNED <= _import_aliases(MAIN_PATH, "app.academics")
    assert USER_ACCOUNTS_OWNED <= _import_aliases(MAIN_PATH, "app.user_accounts")
    assert WEB_REQUEST_OWNED <= _import_aliases(MAIN_PATH, "app.web.request")


def test_new_owners_import_isolated_from_main_and_no_cycle():
    code = (
        "import importlib, sys; "
        "assert 'main' not in sys.modules; "
        "[importlib.import_module(name) for name in "
        "('app.academics', 'app.user_accounts', 'app.web.request')]; "
        "assert 'main' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr


def test_owners_do_not_import_main_and_auth_db_do_not_import_user_accounts():
    for path in (ACADEMICS_PATH, USER_ACCOUNTS_PATH, WEB_REQUEST_PATH):
        assert _no_main_import(path)
    assert "import user_accounts" not in _source(AUTH_PATH)
    assert "import user_accounts" not in _source(DB_MAINT_PATH)


def test_owner_modules_satisfy_allowed_dependency_constraints():
    academics_source = _source(ACADEMICS_PATH)
    assert "import secrets" in academics_source
    assert "ptbr_text_sort_key" in academics_source

    user_accounts_source = _source(USER_ACCOUNTS_PATH)
    assert "ensure_usuario_access_schema" in user_accounts_source
    assert "hash_password" in user_accounts_source
    assert "DEFAULT_ACCESS_PASSWORDS" in user_accounts_source
    assert "canonicalize_access_level" in user_accounts_source
    assert "default_access_level_for_user_type" in user_accounts_source

    web_request_source = _source(WEB_REQUEST_PATH)
    assert "X-Requested-With" in web_request_source
    assert "xmlhttprequest" in web_request_source.lower()
    assert "import main" not in web_request_source


def test_b6_module_consumes_accepted_owners_directly_and_stays_canonical():
    from app import academics, user_accounts
    from app.views.admin import alunos_turmas_cursos as b6
    from app.web import request as web_request

    assert b6.__name__ == "app.views.admin.alunos_turmas_cursos"
    owners = {name: academics for name in ACADEMICS_OWNED}
    owners.update({name: user_accounts for name in USER_ACCOUNTS_OWNED})
    owners.update({name: web_request for name in WEB_REQUEST_OWNED})
    for name, owner in owners.items():
        assert getattr(b6, name) is getattr(owner, name)

    b6_path = PROJECT_ROOT / "app" / "views" / "admin" / "alunos_turmas_cursos.py"
    assert ACADEMICS_OWNED <= _import_aliases(b6_path, "app.academics")
    assert USER_ACCOUNTS_OWNED <= _import_aliases(b6_path, "app.user_accounts")
    assert WEB_REQUEST_OWNED <= _import_aliases(b6_path, "app.web.request")
    assert _no_main_import(b6_path)
    assert "sys.modules" not in _source(b6_path)
    assert "importlib" not in _source(b6_path)


def test_owner_bodies_preserved_without_transaction_ownership():
    from app import user_accounts

    for name in USER_ACCOUNTS_OWNED:
        source = inspect.getsource(getattr(user_accounts, name)).upper()
        assert ".COMMIT(" not in source
        assert ".ROLLBACK(" not in source


# ---- Core lazy map residual contract ----


def test_core_lazy_keys_residual_exact_set():
    import app.views.core as core_views

    keys = _lazy_return_keys(core_views._get_main_helpers)
    assert keys == {"aluno_url", "get_db_connection", "logger"}


def test_core_login_uses_direct_import_and_preserves_order():
    import app.views.core as core_views

    assert "normalize_usuario_access_for_user_type" in _import_aliases(
        CORE_PATH, "app.user_accounts"
    )
    source = inspect.getsource(core_views.login)
    normalization = 'normalize_usuario_access_for_user_type(conn, user["id"])'
    assert normalization in source
    assert source.index(normalization) < source.index("conn.commit()", source.index(normalization))
    assert "refreshed = conn.execute" in source


# ---- Central AJAX helper contract ----


def test_central_admin_access_denied_uses_canonical_ajax_helper():
    import main

    source = inspect.getsource(main._admin_access_denied_response)
    assert "_is_ajax_request()" in source


def test_admin_access_denied_response_future_canonical_owner_is_authz_gate():
    """UT-3 RED: main._admin_access_denied_response's canonical owner becomes
    app.web.authz_gate._admin_access_denied_response, by direct object
    identity (no wrapper/body duplication). At RED stage app.web.authz_gate
    does not exist, so this import is the intended failure.
    """
    import importlib

    import main

    authz_gate = importlib.import_module("app.web.authz_gate")
    assert main._admin_access_denied_response is authz_gate._admin_access_denied_response


# ---- Behavior preservation / consumer resolution ----


def test_consumer_identity_resolution():
    import main

    assert main._is_ajax_request is not None


def test_academics_matricula_behavior_preserved():
    from app.academics import build_turma_aluno_matricula

    assert build_turma_aluno_matricula("ADS", 1, 30) == "ADS.001"
    assert build_turma_aluno_matricula("ADS", 30, 30) == "ADS.030"
    assert build_turma_aluno_matricula("ADS", 7, 700) == "ADS.007"
    assert build_turma_aluno_matricula("ADS", 77, 700) == "ADS.077"
    try:
        build_turma_aluno_matricula("", 1, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for empty turma codigo")


def test_admin_add_aluno_import_isolation_unchanged():
    import main
    from app.user_accounts import create_usuario_with_default_access

    assert main.create_usuario_with_default_access is create_usuario_with_default_access


def test_academic_owner_remains_in_canonical_message_catalog():
    from utils import messages

    messages._message_catalog.cache_clear()
    catalog = messages._message_catalog()

    assert len(catalog) == 537
    entry = catalog["msg_4642b1608cf6a126"]
    assert entry["default_text"] == "Turma sem código para gerar matrícula."
    assert any(
        usage["source_path"] == "app/academics.py"
        and usage["source_function"] == "build_turma_aluno_matricula"
        and usage["kind"] == "exception"
        for usage in entry["usages"]
    )
