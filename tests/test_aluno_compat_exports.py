import ast
import inspect
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app.views import aluno as aluno_views


ALUNO_EXPORT_NAMES = (
    "aluno_dashboard",
    "aluno_meus_dados",
    "aluno_nova_requisicao",
    "aluno_minhas_requisicoes",
    "aluno_requisicao_detalhe",
    "aluno_arquivos",
    "aluno_visualizar_arquivo",
    "aluno_baixar_arquivo",
)

LEGACY_FUNC_NAMES = (
    "aluno_dashboard",
    "aluno_meus_dados",
    "aluno_nova_requisicao",
    "aluno_minhas_requisicoes",
    "aluno_requisicao_detalhe",
    "aluno_arquivos",
)


def _main_source():
    fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "main.py")
    with open(fpath, "rb") as f:
        return f.read()


def _collect_target_names(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.List, ast.Tuple)):
        result = []
        for elt in node.elts:
            result.extend(_collect_target_names(elt))
        return result
    if isinstance(node, ast.Starred):
        return _collect_target_names(node.value)
    return []


def test_legacy_aluno_bodies_and_noop_registration_are_absent():
    source = _main_source()
    tree = ast.parse(source)

    func_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for name in LEGACY_FUNC_NAMES:
        assert name not in func_names, f"FunctionDef {name} should be absent from main.py"
    assert "_noop_route" not in func_names, "FunctionDef _noop_route should be absent from main.py"

    target_lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                for name in _collect_target_names(t):
                    if name == "aluno_runtime_route":
                        target_lines.append(node.lineno)
        elif isinstance(node, ast.AnnAssign):
            for name in _collect_target_names(node.target):
                if name == "aluno_runtime_route":
                    target_lines.append(node.lineno)
        elif isinstance(node, ast.AugAssign):
            for name in _collect_target_names(node.target):
                if name == "aluno_runtime_route":
                    target_lines.append(node.lineno)
    assert not target_lines, f"aluno_runtime_route assignment still present at lines {target_lines}"

    decorator_refs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "aluno_runtime_route":
                    decorator_refs.append((node.name, node.lineno))
                elif isinstance(dec, ast.Attribute) and isinstance(dec.value, ast.Name) and dec.value.id == "aluno_runtime_route":
                    decorator_refs.append((node.name, node.lineno))
                elif isinstance(dec, ast.Call):
                    resolved = dec.func
                    if isinstance(resolved, ast.Name) and resolved.id == "aluno_runtime_route":
                        decorator_refs.append((node.name, node.lineno))
                    elif isinstance(resolved, ast.Attribute) and isinstance(resolved.value, ast.Name) and resolved.value.id == "aluno_runtime_route":
                        decorator_refs.append((node.name, node.lineno))
    assert not decorator_refs, f"Decorators referencing aluno_runtime_route found: {decorator_refs}"


def test_main_aluno_compat_exports_match_active_blueprint():
    for name in ALUNO_EXPORT_NAMES:
        assert hasattr(main, name), f"main.{name} does not exist"
        assert hasattr(aluno_views, name), f"aluno_views.{name} does not exist"

        main_obj = getattr(main, name)
        views_obj = getattr(aluno_views, name)

        assert callable(main_obj), f"main.{name} is not callable"
        assert callable(views_obj), f"aluno_views.{name} is not callable"

        assert main_obj is views_obj, f"main.{name} is not the same object as aluno_views.{name}"

        assert main_obj.__name__ == name, f"main.{name}.__name__ is {main_obj.__name__}"
        assert views_obj.__name__ == name, f"aluno_views.{name}.__name__ is {views_obj.__name__}"

        assert main_obj.__module__ == "app.views.aluno", f"main.{name}.__module__ is {main_obj.__module__}"
        assert views_obj.__module__ == "app.views.aluno", f"aluno_views.{name}.__module__ is {views_obj.__module__}"

        assert inspect.signature(main_obj) == inspect.signature(views_obj), (
            f"signature mismatch for {name}: main={inspect.signature(main_obj)} vs views={inspect.signature(views_obj)}"
        )


def test_aluno_rebind_is_idempotent_and_urls_are_stable():
    before = {name: getattr(main, name) for name in ALUNO_EXPORT_NAMES}

    main._rebind_legacy_aluno_exports()

    after = {name: getattr(main, name) for name in ALUNO_EXPORT_NAMES}
    for name in ALUNO_EXPORT_NAMES:
        assert before[name] is after[name], (
            f"main.{name} identity changed after second _rebind_legacy_aluno_exports()"
        )

    url_specs = [
        ("aluno_dashboard", {}, "/aluno/dashboard"),
        ("aluno_meus_dados", {}, "/aluno/meus_dados"),
        ("aluno_nova_requisicao", {}, "/aluno/nova_requisicao"),
        ("aluno_minhas_requisicoes", {}, "/aluno/requisicoes"),
        ("aluno_requisicao_detalhe", {"req_id": 17}, "/aluno/requisicoes/17"),
        ("aluno_arquivos", {}, "/aluno/arquivos"),
        ("aluno_visualizar_arquivo", {"arquivo_id": 23}, "/aluno/arquivos/ver/23"),
        ("aluno_baixar_arquivo", {"arquivo_id": 23}, "/aluno/arquivos/download/23"),
    ]

    import flask
    with main.app.test_request_context():
        for endpoint, kwargs, expected_url in url_specs:
            url_from_for = flask.url_for(f"aluno.{endpoint}", **kwargs)
            url_from_aluno_url = main.aluno_url(endpoint, **kwargs)
            assert url_from_for == url_from_aluno_url, (
                f"flask.url_for('aluno.{endpoint}') != main.aluno_url('{endpoint}'): "
                f"{url_from_for} != {url_from_aluno_url}"
            )
            assert url_from_for == expected_url, (
                f"flask.url_for('aluno.{endpoint}') expected {expected_url} got {url_from_for}"
            )
