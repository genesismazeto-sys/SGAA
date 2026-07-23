import ast
import difflib
import inspect
import io
import json
import os
import re
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import db as app_db_module
import main
from utils.messages import message_key_for_default


MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ALLOWED_STATUSES = {
    "ok_rendered_form_token",
    "ok_fetch_token",
    "ok_dynamic_form_token",
    "ok_specific_regression_test",
    "ok_api_csrf_contract",
    "ok_logout_or_safe_exception",
    "not_applicable_documented",
    "fixed",
    "blocked_real_risk",
}
FORM_BLOCK_RE = re.compile(
    r"(<form\b(?P<attrs>[^>]*)>(?P<body>.*?)</form>)",
    re.IGNORECASE | re.DOTALL,
)
FORM_METHOD_RE = re.compile(r"\bmethod\s*=\s*['\"]?([a-zA-Z]+)['\"]?", re.IGNORECASE)
FORM_ACTION_RE = re.compile(r"\baction\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
CSRF_INPUT_RE = re.compile(r"name\s*=\s*['\"]csrf_token['\"]", re.IGNORECASE)
ATTR_URL_RE = re.compile(
    r"(?P<attr>action|formaction|data-[a-z0-9_-]+-url)\s*=\s*['\"](?P<url>[^'\"]+)['\"]",
    re.IGNORECASE,
)
PATH_LITERAL_RE = re.compile(r"(?P<quote>['\"`])(?P<value>/[^'\"`]*)(?P=quote)")
TOKEN_HINT_RE = re.compile(
    r"X-CSRFToken|csrf-token|csrf_token|buildPostHeaders|getCsrfToken|ensureFormCsrfToken|appendCsrfToken|requestJson",
    re.IGNORECASE,
)
RULE_PLACEHOLDER_RE = re.compile(r"<[^>]+>")
JS_TEMPLATE_SLOT_RE = re.compile(r"\$\{[^}]+\}")

SPECIFIC_REGRESSION_TESTS = {
    "/admin/acesso/<int:usuario_id>/resetar-senha": [
        "tests/test_admin_add_aluno_csrf.py::test_admin_acesso_resetar_senha_requires_csrf_and_sets_default_password",
    ],
    "/admin/acesso/definir-senha": [
        "tests/test_admin_add_aluno_csrf.py::test_admin_acesso_definir_senha_requires_csrf_and_allows_student_login",
        "tests/test_csrf_admin_flows.py::test_admin_redefine_student_password_and_student_login",
    ],
    "/admin/alertas/<int:alerta_id>/alternar": [
        "tests/test_release_admin_actions_csrf.py::test_release_admin_post_actions_require_active_csrf_token",
        "tests/test_csrf_admin_flows.py::test_admin_fetch_mutation_requires_csrf_header",
    ],
    "/admin/alertas/<int:alerta_id>/deletar": [
        "tests/test_release_admin_actions_csrf.py::test_release_admin_post_actions_require_active_csrf_token",
    ],
    "/admin/api/presets": [
        "tests/test_csrf_admin_flows.py::test_admin_api_presets_requires_and_accepts_csrf",
    ],
    "/admin/banco-dados/restaurar/upload": [
        "tests/test_release_admin_actions_csrf.py::test_release_admin_post_actions_require_active_csrf_token",
    ],
    "/admin/banco-dados/retencao": [
        "tests/test_release_admin_actions_csrf.py::test_release_admin_post_actions_require_active_csrf_token",
    ],
    "/admin/importar_requisicoes": [
        "tests/test_csrf_admin_flows.py::test_admin_importar_requisicoes_page_and_post_require_csrf",
    ],
    "/admin/matrizes/<int:matriz_id>/atividades/<int:atividade_id>/nova-versao": [
        "tests/test_admin_matriz_nova_versao_card.py::test_post_requires_csrf",
    ],
    "/admin/matrizes/<int:matriz_id>/atividades/nova/<string:active_tab>": [
        "tests/test_admin_matrix_new_activity.py::test_modal_form_contains_csrf_and_post_requires_it",
    ],
    "/admin/meus_dados": [
        "tests/test_csrf_admin_flows.py::test_admin_meus_dados_password_change_requires_and_accepts_csrf",
    ],
    "/admin/requisicoes/<int:req_id>/editar": [
        "tests/test_csrf_admin_flows.py::test_admin_requisicao_edit_requires_and_accepts_csrf",
    ],
    "/admin/requisicoes/<int:req_id>/excluir": [
        "tests/test_release_admin_actions_csrf.py::test_release_admin_post_actions_require_active_csrf_token",
    ],
    "/admin/reportes/<int:reporte_id>/deletar": [
        "tests/test_release_admin_actions_csrf.py::test_release_admin_post_actions_require_active_csrf_token",
    ],
    "/admin/reportes/<int:reporte_id>/status": [
        "tests/test_release_admin_actions_csrf.py::test_release_admin_post_actions_require_active_csrf_token",
    ],
    "/admin/turmas/importar": [
        "tests/test_release_backend_core.py::test_release_backend_core_turmas_import_get_redirect_and_post_csrf",
    ],
    "/logout": [
        "tests/test_csrf_admin_flows.py::test_logout_get_is_safe_and_post_requires_csrf",
    ],
}
STATUS_OVERRIDE_BY_ROUTE = {
    "/admin/api/presets": "ok_api_csrf_contract",
    "/logout": "ok_logout_or_safe_exception",
}
NOT_APPLICABLE_DOCUMENTED = {
    "/login": "POST publico intencionalmente exemptado em app/__init__.py para o primeiro login sem sessao.",
    "/admin/alterar_status_alunos": "Endpoint legado sem referencia em formularios, modais ou JavaScript ativos das telas renderizadas do admin.",
}


def _call_name(node) -> str:
    if isinstance(node, list):
        return ""
    if node is None:
        return ""
    if isinstance(node, tuple):
        return ""
    if hasattr(node, "id"):
        return getattr(node, "id")
    if hasattr(node, "attr"):
        return getattr(node, "attr")
    if hasattr(node, "func"):
        return _call_name(node.func)
    return ""


def _module_name_from_path(project_root: Path, py_path: Path) -> str:
    rel = py_path.relative_to(project_root).with_suffix("")
    return ".".join(rel.parts)


def _collect_route_source_metadata(project_root: Path) -> dict[tuple[str, str], dict]:
    candidates = [
        project_root / "main.py",
        project_root / "app" / "views" / "aluno.py",
        project_root / "app" / "views" / "core.py",
    ]
    metadata: dict[tuple[str, str], dict] = {}
    for file_path in candidates:
        if not file_path.exists():
            continue
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
        module_name = _module_name_from_path(project_root, file_path)
        for node in getattr(tree, "body", []):
            if node.__class__.__name__ != "FunctionDef":
                continue
            decorators = {_call_name(deco) for deco in getattr(node, "decorator_list", []) if _call_name(deco)}
            templates: list[str] = []
            for inner in _walk_ast(node):
                if inner.__class__.__name__ != "Call":
                    continue
                if _call_name(getattr(inner, "func", None)) != "render_template":
                    continue
                args = getattr(inner, "args", [])
                if args and getattr(args[0], "value", None) and isinstance(args[0].value, str):
                    templates.append(args[0].value)
            metadata[(module_name, node.name)] = {
                "decorators": sorted(decorators),
                "templates": sorted(set(templates)),
            }
    return metadata


def _walk_ast(node):
    yield node
    for field_name in getattr(node, "_fields", []):
        value = getattr(node, field_name)
        if isinstance(value, list):
            for item in value:
                if hasattr(item, "_fields"):
                    yield from _walk_ast(item)
        elif hasattr(value, "_fields"):
            yield from _walk_ast(value)


def _route_to_regex(rule: str) -> re.Pattern[str]:
    pattern = ""
    last = 0
    for match in RULE_PLACEHOLDER_RE.finditer(rule):
        pattern += re.escape(rule[last:match.start()]) + r"[^/]+"
        last = match.end()
    pattern += re.escape(rule[last:])
    return re.compile("^" + pattern + "$")


def _static_prefix(rule: str) -> str:
    return rule.split("<", 1)[0]


def _materialize_rule_path(rule: str, values: dict[str, int]) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        inner = raw[1:-1]
        name = inner.split(":", 1)[-1]
        return str(values[name])

    return RULE_PLACEHOLDER_RE.sub(replace, rule)


def _normalize_path_expr(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized.startswith(("http://", "https://")):
        normalized = urlsplit(normalized).path or ""
    else:
        normalized = urlsplit(normalized).path or normalized
    normalized = JS_TEMPLATE_SLOT_RE.sub("slot", normalized)
    normalized = normalized.split("#", 1)[0]
    normalized = normalized.rstrip() or normalized
    return normalized


def _build_route_matchers(app) -> list[dict]:
    rows = []
    for rule in app.url_map.iter_rules():
        methods = sorted(set(rule.methods or []) & MUTATING_METHODS)
        if not methods:
            continue
        rows.append(
            {
                "route": rule.rule,
                "endpoint": rule.endpoint,
                "methods": methods,
                "regex": _route_to_regex(rule.rule),
                "prefix": _static_prefix(rule.rule),
            }
        )
    return rows


def _match_route_rule(path_expr: str, method: str, matchers: list[dict]) -> str | None:
    normalized = _normalize_path_expr(path_expr)
    if not normalized:
        return None

    exact_matches = []
    for matcher in matchers:
        if method not in matcher["methods"]:
            continue
        if matcher["regex"].match(normalized):
            exact_matches.append(matcher["route"])
    if len(exact_matches) == 1:
        return exact_matches[0]

    prefix_matches = []
    for matcher in matchers:
        if method not in matcher["methods"]:
            continue
        prefix = matcher["prefix"]
        if prefix and (normalized == prefix or normalized.startswith(prefix)):
            prefix_matches.append((len(prefix), matcher["route"]))
    if prefix_matches:
        prefix_matches.sort(reverse=True)
        top_length = prefix_matches[0][0]
        top_routes = [route for length, route in prefix_matches if length == top_length]
        if len(top_routes) == 1:
            return top_routes[0]
    return None


def _infer_login_requirement(route_rule: str, decorators: set[str]) -> str:
    if "admin_required" in decorators:
        return "admin"
    if "aluno_required" in decorators:
        return "aluno"
    if route_rule.startswith("/admin"):
        return "admin_inferred"
    if route_rule.startswith("/aluno"):
        return "aluno_inferred"
    if route_rule in {"/login", "/logout"}:
        return "public"
    return "unknown"


def _count_csrf_tokens(html_block: str) -> int:
    return len(CSRF_INPUT_RE.findall(html_block or ""))


def _extract_post_forms(html: str) -> list[dict]:
    forms = []
    for match in FORM_BLOCK_RE.finditer(html or ""):
        attrs = match.group("attrs") or ""
        method_match = FORM_METHOD_RE.search(attrs)
        method = (method_match.group(1) if method_match else "get").strip().upper()
        if method != "POST":
            continue
        action_match = FORM_ACTION_RE.search(attrs)
        forms.append(
            {
                "attrs": attrs,
                "html": match.group(0),
                "action": (action_match.group(1).strip() if action_match else ""),
                "token_count": _count_csrf_tokens(match.group(0)),
            }
        )
    return forms


def _extract_csrf_token_from_first_post_form(html: str) -> str:
    for form in _extract_post_forms(html):
        token_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', form["html"])
        if token_match:
            return str(token_match.group(1))
    raise AssertionError("Nenhum csrf_token encontrado no HTML renderizado")


def _add_evidence(store: dict[str, list[dict]], route: str, evidence: dict) -> None:
    entries = store.setdefault(route, [])
    if evidence not in entries:
        entries.append(evidence)


def _analyze_page_html(page_label: str, current_path: str, html: str, matchers: list[dict]) -> dict[str, list[dict]]:
    evidences: dict[str, list[dict]] = {}
    page_has_csrf_shim = "csrf-shim.js" in (html or "")
    page_has_toolbar_helper = "toolbar-filters.js" in (html or "")
    page_has_dynamic_form_helper = bool(
        "ensureFormCsrfToken" in (html or "")
        or "appendCsrfToken" in (html or "")
        or "setSaveButton" in (html or "")
    )
    has_single_token_form = any(form["token_count"] == 1 for form in _extract_post_forms(html))

    for form in _extract_post_forms(html):
        action_expr = form["action"] or current_path
        route_rule = _match_route_rule(action_expr, "POST", matchers)
        if route_rule:
            _add_evidence(
                evidences,
                route_rule,
                {
                    "kind": "rendered_form",
                    "page": page_label,
                    "action": _normalize_path_expr(action_expr) or current_path,
                    "token_count": int(form["token_count"]),
                },
            )
        for submit_action in re.findall(r"\bformaction\s*=\s*['\"]([^'\"]+)['\"]", form["html"], re.IGNORECASE):
            submit_route = _match_route_rule(submit_action, "POST", matchers)
            if not submit_route:
                continue
            _add_evidence(
                evidences,
                submit_route,
                {
                    "kind": "rendered_form",
                    "page": page_label,
                    "action": _normalize_path_expr(submit_action),
                    "token_count": int(form["token_count"]),
                },
            )

    for attr_match in ATTR_URL_RE.finditer(html or ""):
        attr = str(attr_match.group("attr") or "").lower()
        url = str(attr_match.group("url") or "").strip()
        route_rule = _match_route_rule(url, "POST", matchers)
        if not route_rule:
            continue
        snippet = (html or "")[max(0, attr_match.start() - 600) : min(len(html or ""), attr_match.end() + 900)]
        if page_has_dynamic_form_helper and (
            attr in {"data-delete-url", "data-reset-url"}
            or "createElement('form')" in snippet
            or 'createElement("form")' in snippet
            or "setSaveButton" in snippet
        ):
            _add_evidence(
                evidences,
                route_rule,
                {
                    "kind": "dynamic_form",
                    "page": page_label,
                    "attr": attr,
                    "action": _normalize_path_expr(url),
                    "token_mode": "helper_or_hidden",
                },
            )
            continue
        if attr.startswith("data-") and page_has_toolbar_helper and page_has_csrf_shim:
            _add_evidence(
                evidences,
                route_rule,
                {
                    "kind": "fetch",
                    "page": page_label,
                    "attr": attr,
                    "action": _normalize_path_expr(url),
                    "token_mode": "global_csrf_shim",
                },
            )

    for path_match in PATH_LITERAL_RE.finditer(html or ""):
        value = str(path_match.group("value") or "")
        route_rule = _match_route_rule(value, "POST", matchers)
        if not route_rule:
            continue
        snippet = (html or "")[max(0, path_match.start() - 350) : min(len(html or ""), path_match.end() + 650)]
        if ("fetch(" in snippet or "requestJson(" in snippet or "buildPostHeaders" in snippet) and (
            TOKEN_HINT_RE.search(snippet) or page_has_csrf_shim
        ):
            _add_evidence(
                evidences,
                route_rule,
                {
                    "kind": "fetch",
                    "page": page_label,
                    "action": _normalize_path_expr(value),
                    "token_mode": "inline_hint" if TOKEN_HINT_RE.search(snippet) else "global_csrf_shim",
                },
            )
        if has_single_token_form and page_has_dynamic_form_helper and (
            "createElement('form')" in snippet
            or 'createElement("form")' in snippet
            or "setSaveButton" in snippet
        ):
            _add_evidence(
                evidences,
                route_rule,
                {
                    "kind": "dynamic_form",
                    "page": page_label,
                    "action": _normalize_path_expr(value),
                    "token_mode": "helper_or_hidden",
                },
            )
    return evidences


def _create_support_turma(conn, suffix: str) -> dict[str, int]:
    main.ensure_turmas_matriz_schema(conn)
    main.ensure_matrizes_atividades_table(conn)

    curso_codigo = f"CSRF-AUD-{suffix}"
    conn.execute(
        "INSERT INTO cursos (nome, codigo, duracao_periodos, status) VALUES (?, ?, ?, ?)",
        (f"Curso Inventory {suffix}", curso_codigo, 8, "ativo"),
    )
    curso_id = int(
        conn.execute(
            "SELECT id FROM cursos WHERE codigo = ?",
            (curso_codigo,),
        ).fetchone()["id"]
    )

    matriz_id = int(
        conn.execute(
            """
            INSERT INTO matrizes_atividades (
                curso_id, nome, versao, status, data_inicio_vigencia,
                horas_aac_obrigatorias, horas_extensao_obrigatorias, descricao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                curso_id,
                f"Matriz Inventory {suffix}",
                "2026.2",
                "vigente",
                "2026-07-01",
                120,
                60,
                "Matriz para inventario de CSRF",
            ),
        ).fetchone()["id"]
    )

    turma_codigo = main.gerar_codigo_turma(curso_codigo, 1)
    turma_id = int(
        conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                turma_codigo,
                None,
                None,
                "Manha",
                "Ativa",
                1,
                curso_id,
                matriz_id,
                2026,
                1,
                2029,
                2,
                turma_codigo,
            ),
        ).fetchone()["id"]
    )
    conn.commit()
    return {"curso_id": curso_id, "matriz_id": matriz_id, "turma_id": turma_id}


def _setup_isolated_csrf_clients(tmp_path: Path):
    app = main.app
    temp_database = tmp_path / "csrf_inventory_audit.db"
    temp_uploads = tmp_path / "uploads"
    temp_uploads.mkdir(parents=True, exist_ok=True)

    original_database = main.DATABASE
    original_env_database = os.environ.get("APP_DATABASE")
    original_config_database_path = app.config.get("DATABASE_PATH")
    original_upload_folder = app.config.get("UPLOAD_FOLDER")
    original_documents_folder = app.config.get("DOCUMENTOS_ALUNOS_FOLDER")
    original_local_backup_dir = app.config.get("LOCAL_BACKUP_DIR")
    original_cloud_backup_dir = app.config.get("CLOUD_BACKUP_DIR")
    original_cloud_sync_interval = app.config.get("CLOUD_SYNC_INTERVAL_SECONDS")
    original_external_backup_enabled = app.config.get("EXTERNAL_BACKUP_ENABLED")
    original_testing = app.config.get("TESTING")
    original_wtf_csrf_enabled = app.config.get("WTF_CSRF_ENABLED")
    original_wtf_csrf_check_default = app.config.get("WTF_CSRF_CHECK_DEFAULT")

    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["TESTING"] = True
    app.config["UPLOAD_FOLDER"] = str(temp_uploads)
    app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(tmp_path / "documentos_alunos")
    app.config["LOCAL_BACKUP_DIR"] = str(tmp_path / "backups" / "local")
    app.config["CLOUD_BACKUP_DIR"] = ""
    app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = 0
    app.config["EXTERNAL_BACKUP_ENABLED"] = False
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_CHECK_DEFAULT"] = True

    with app.app_context():
        try:
            main.close_db_connection(None)
        except Exception:
            pass
        main.init_db()
        conn = main.get_db_connection()
        main.ensure_usuario_access_schema(conn)
        main.ensure_admin_alertas_table(conn)
        main.ensure_reportes_table(conn)
        main.ensure_admin_arquivos_table(conn)

        suffix = uuid.uuid4().hex[:8]
        support = _create_support_turma(conn, suffix)

        admin_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            (
                f"Admin Inventory {suffix}",
                f"admin.inventory.{suffix}@teste.local",
                main.hash_password("admin12345"),
                "admin",
                "admin_total",
            ),
        ).lastrowid
        aluno_user_id = main.create_usuario_with_default_access(
            conn,
            f"Aluno Inventory {suffix}",
            f"aluno.inventory.{suffix}@teste.local",
            main.hash_password("aluno12345"),
            "aluno",
        ).lastrowid
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?)",
            (
                int(aluno_user_id),
                f"Aluno Inventory {suffix}",
                f"MAT-{suffix}".upper(),
                f"aluno.inventory.{suffix}@teste.local",
                int(support["turma_id"]),
                "Ativo",
            ),
        ).lastrowid
        atividade_id = conn.execute(
            """
            INSERT INTO atividades (grupo, nome, descricao, limite_horas, tipo_atividade, tem_limitacao)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                "1 - Grupo Inventory",
                f"Atividade Inventory {suffix}",
                "Atividade para inventario",
                40,
                "Acadêmica Complementar",
            ),
        ).lastrowid
        req_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento,
                horas_solicitadas, nome_evento, status, observacao
            ) VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?)
            """,
            (
                int(aluno_id),
                int(atividade_id),
                "2028-09-12",
                6,
                f"Requisicao Inventory {suffix}",
                "Pendente",
                "Criada para inventario",
            ),
        ).lastrowid
        alerta_id = conn.execute(
            """
            INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                f"Alerta Inventory {suffix}",
                "Mensagem de alerta para inventario",
                "#e3eefd",
                "#7e95b2",
                1,
            ),
        ).lastrowid
        reporte_id = conn.execute(
            """
            INSERT INTO reportes (aluno_id, titulo, descricao, categoria, status, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                int(aluno_id),
                f"Reporte Inventory {suffix}",
                "Reporte para inventario",
                "Outro",
                "Novo",
            ),
        ).lastrowid
        arquivo_id = conn.execute(
            """
            INSERT INTO admin_arquivos (titulo, descricao, filename, original_filename, visivel)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                f"Arquivo Inventory {suffix}",
                "Arquivo para inventario",
                "inventario/arquivo.pdf",
                "arquivo.pdf",
                1,
            ),
        ).lastrowid
        main.ensure_cloud_backup_schema(conn)
        conn.execute(
            """
            INSERT INTO cloud_accounts (provider, account_email, token_json, connected_at, updated_at, active)
            VALUES (?, ?, ?, datetime('now'), datetime('now'), 1)
            """,
            ("google", f"google.inventory.{suffix}@teste.local", "{}"),
        )
        conn.execute(
            """
            INSERT INTO cloud_accounts (provider, account_email, token_json, connected_at, updated_at, active)
            VALUES (?, ?, ?, datetime('now'), datetime('now'), 1)
            """,
            ("onedrive", f"onedrive.inventory.{suffix}@teste.local", "{}"),
        )
        conn.execute(
            """
            INSERT INTO cloud_drive_settings (provider, folder_id, folder_name, folder_path_label, drive_id, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(provider) DO UPDATE SET
                folder_id = excluded.folder_id,
                folder_name = excluded.folder_name,
                folder_path_label = excluded.folder_path_label,
                drive_id = excluded.drive_id,
                updated_at = datetime('now')
            """,
            ("google", "folder-google", "Backups", "Backups/sistema", ""),
        )
        conn.execute(
            """
            INSERT INTO cloud_drive_settings (provider, folder_id, folder_name, folder_path_label, drive_id, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(provider) DO UPDATE SET
                folder_id = excluded.folder_id,
                folder_name = excluded.folder_name,
                folder_path_label = excluded.folder_path_label,
                drive_id = excluded.drive_id,
                updated_at = datetime('now')
            """,
            ("onedrive", "folder-onedrive", "SGAA - Backups", "SGAA - Backups", ""),
        )
        # ---------------------------------------------------------------------------
        # Seed para evidência CSRF de /admin/catalogo-versoes/<base_id>(/<...>).
        #
        # O crawler materializa cada regra GET com `sample_values` para renderizar a
        # página. Para o detail da atividade-base e para as rotas de criação,
        # edição e ativação de atividade_versao serem alcançáveis pelo inventário
        # CSRF, é preciso que `base_id` (e `versao_id`) existam no sample e que a
        # página de detalhe renderize pelo menos uma versão em rascunho (único
        # status em que o form "Ativar" e o link "Editar" são exibidos). Sem
        # essa seed, as 3 rotas mutating do catálogo de versões caem em
        # blocked_real_risk / no_rendered_or_test_evidence porque a evidência
        # real (form POST com csrf_token renderizado) nunca é alcançada.
        # ---------------------------------------------------------------------------
        main.ensure_atividade_versioning_schema(conn)
        nome_conceito_base = f"Atividade Inventory Catalog {suffix}"
        conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, ?)",
            (nome_conceito_base, "Base para inventário CSRF do catálogo", "ativo"),
        )
        base_id = int(
            conn.execute(
                "SELECT id FROM atividade_base WHERE nome_conceito = ?",
                (nome_conceito_base,),
            ).fetchone()["id"]
        )
        cod_norma = f"NRM-INV-{suffix}"
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (cod_norma, "AAC", "rev1", "Norma Inventory Catalog", "ativa"),
        )
        norma_id = int(
            conn.execute(
                "SELECT id FROM norma_atividade WHERE codigo = ?",
                (cod_norma,),
            ).fetchone()["id"]
        )
        conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (base_id, norma_id, cod_norma, "AAC", "1 - Grupo Inventory CSRF", "rascunho"),
        )
        versao_id = int(
            conn.execute(
                "SELECT id FROM atividade_versao "
                "WHERE atividade_base_id = ? AND norma_id = ?",
                (base_id, norma_id),
            ).fetchone()["id"]
        )
        # ---------------------------------------------------------------------------
        # Seed D7.2B4: vínculo matriz→versão — evidência real para as rotas
        # admin_matriz_versoes_definir e admin_matriz_versoes_remover.
        # Precisamos de: norma ativa, versão ativa, atividade_legacy_map,
        # matrizes_atividades_itens, matriz_norma e matriz_atividade_versao_item
        # para que o GET admin/matrizes/<id>/versoes renderize os formulários POST.
        # ---------------------------------------------------------------------------
        cod_norma_lnk = f"NRM-LNK-{suffix}"
        conn.execute(
            "INSERT INTO norma_atividade (codigo, eixo, revisao, nome, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (cod_norma_lnk, "AAC", "rev2", "Norma Inventory Link", "ativa"),
        )
        norma_lnk_id = int(
            conn.execute(
                "SELECT id FROM norma_atividade WHERE codigo = ?",
                (cod_norma_lnk,),
            ).fetchone()["id"]
        )
        conn.execute(
            """
            INSERT INTO atividade_versao (
                atividade_base_id, norma_id, codigo_normativo, eixo, grupo, status, numero_versao
            ) VALUES (?, ?, ?, ?, ?, ?, 2)
            """,
            (base_id, norma_lnk_id, cod_norma_lnk, "AAC", "1 - Grupo Inventory Link", "ativa"),
        )
        versao_lnk_id = int(
            conn.execute(
                "SELECT id FROM atividade_versao "
                "WHERE atividade_base_id = ? AND norma_id = ?",
                (base_id, norma_lnk_id),
            ).fetchone()["id"]
        )
        conn.execute(
            "INSERT INTO atividade_legacy_map"
            " (atividade_id_legacy, atividade_base_id, status) VALUES (?, ?, ?)",
            (int(atividade_id), base_id, "mapeada"),
        )
        conn.execute(
            "INSERT INTO matrizes_atividades_itens (matriz_id, atividade_id) VALUES (?, ?)",
            (int(support["matriz_id"]), int(atividade_id)),
        )
        conn.execute(
            "INSERT INTO matriz_norma (matriz_id, norma_id) VALUES (?, ?)",
            (int(support["matriz_id"]), norma_lnk_id),
        )
        conn.execute(
            "INSERT INTO matriz_atividade_versao_item (matriz_id, atividade_versao_id)"
            " VALUES (?, ?)",
            (int(support["matriz_id"]), versao_lnk_id),
        )
        conn.commit()
        main.create_database_snapshot(
            str(temp_database),
            str(app.config["LOCAL_BACKUP_DIR"]),
            schema_status=main.get_schema_status(conn),
            reason="manual-backup",
            origin="local",
            logger=main.logger,
            extra_metadata={"requested_by": int(admin_id)},
        )

    state = {
        "app": app,
        "ids": {
            "admin_id": int(admin_id),
            "aluno_user_id": int(aluno_user_id),
            "aluno_id": int(aluno_id),
            "atividade_id": int(atividade_id),
            "alerta_id": int(alerta_id),
            "arquivo_id": int(arquivo_id),
            "base_id": int(base_id),
            "versao_id": int(versao_id),
            "curso_id": int(support["curso_id"]),
            "matriz_id": int(support["matriz_id"]),
            "reporte_id": int(reporte_id),
            "req_id": int(req_id),
            "turma_id": int(support["turma_id"]),
        },
        "restore": {
            "main_database": original_database,
            "env_database": original_env_database,
            "config_database_path": original_config_database_path,
            "upload_folder": original_upload_folder,
            "documents_folder": original_documents_folder,
            "local_backup_dir": original_local_backup_dir,
            "cloud_backup_dir": original_cloud_backup_dir,
            "cloud_sync_interval": original_cloud_sync_interval,
            "external_backup_enabled": original_external_backup_enabled,
            "testing": original_testing,
            "wtf_csrf_enabled": original_wtf_csrf_enabled,
            "wtf_csrf_check_default": original_wtf_csrf_check_default,
        },
    }
    return state


def _teardown_isolated_csrf_clients(state: dict) -> None:
    app = state["app"]
    restore = state["restore"]

    with app.app_context():
        try:
            main.close_db_connection(None)
        except Exception:
            pass

    main.DATABASE = restore["main_database"]
    app_db_module.DATABASE = restore["main_database"]
    if restore["config_database_path"] is None:
        app.config.pop("DATABASE_PATH", None)
    else:
        app.config["DATABASE_PATH"] = restore["config_database_path"]
    app.config["UPLOAD_FOLDER"] = restore["upload_folder"]
    app.config["DOCUMENTOS_ALUNOS_FOLDER"] = restore["documents_folder"]
    app.config["LOCAL_BACKUP_DIR"] = restore["local_backup_dir"]
    app.config["CLOUD_BACKUP_DIR"] = restore["cloud_backup_dir"]
    app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = restore["cloud_sync_interval"]
    app.config["EXTERNAL_BACKUP_ENABLED"] = restore["external_backup_enabled"]
    app.config["TESTING"] = restore["testing"]
    app.config["WTF_CSRF_ENABLED"] = restore["wtf_csrf_enabled"]
    app.config["WTF_CSRF_CHECK_DEFAULT"] = restore["wtf_csrf_check_default"]

    env_database = restore["env_database"]
    if env_database is None:
        os.environ.pop("APP_DATABASE", None)
    else:
        os.environ["APP_DATABASE"] = env_database


def _build_authed_client(app, role: str, ids: dict) -> object:
    client = app.test_client()
    with client.session_transaction() as sess:
        if role == "admin":
            sess["user_id"] = int(ids["admin_id"])
            sess["user_type"] = "admin"
            sess["user_name"] = "Admin Inventory"
            sess["access_level"] = "admin_total"
            sess["perfil"] = "Admin"
        elif role == "aluno":
            sess["user_id"] = int(ids["aluno_user_id"])
            sess["user_type"] = "aluno"
            sess["user_name"] = "Aluno Inventory"
    return client


def _build_page_requests(app, ids: dict) -> list[dict]:
    requests = []
    sample_values = {
        "arquivo_id": int(ids["arquivo_id"]),
        "atividade_id": int(ids["atividade_id"]),
        "base_id": int(ids["base_id"]),
        "curso_id": int(ids["curso_id"]),
        "matriz_id": int(ids["matriz_id"]),
        "req_id": int(ids["req_id"]),
        "turma_id": int(ids["turma_id"]),
        "usuario_id": int(ids["aluno_user_id"]),
        "versao_id": int(ids["versao_id"]),
    }

    with app.test_request_context():
        for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
            methods = set(rule.methods or [])
            if "GET" not in methods:
                continue
            if not (
                rule.rule.startswith("/admin")
                or rule.rule.startswith("/aluno")
                or rule.rule in {"/login", "/logout"}
            ):
                continue
            build_values = {}
            for arg in sorted(rule.arguments):
                if arg not in sample_values:
                    build_values = None
                    break
                build_values[arg] = sample_values[arg]
            if build_values is None:
                continue
            path = _materialize_rule_path(rule.rule, build_values)
            if rule.rule.startswith("/admin"):
                role = "admin"
            elif rule.rule.startswith("/aluno"):
                role = "aluno"
            else:
                role = "public"
            requests.append({"label": rule.rule, "path": path, "role": role})

    requests.extend(
        [
            {
                "label": "/admin/arquivos?edit_arquivo",
                "path": f"/admin/arquivos?edit_arquivo={ids['arquivo_id']}",
                "role": "admin",
            },
        ]
    )

    deduped = []
    seen = set()
    for item in requests:
        key = (item["label"], item["path"], item["role"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _render_page(app, ids: dict, role: str, path: str) -> dict:
    if role == "admin":
        client = _build_authed_client(app, "admin", ids)
    elif role == "aluno":
        client = _build_authed_client(app, "aluno", ids)
    else:
        client = app.test_client()
    try:
        response = client.get(path, follow_redirects=False)
        return {
            "status_code": int(response.status_code),
            "html": response.get_data(as_text=True) if response.status_code == 200 else "",
        }
    except Exception as exc:
        return {
            "status_code": 500,
            "html": "",
            "error": str(exc),
        }


def _render_atividades_import_preview_scenario(app, ids: dict) -> dict:
    client = _build_authed_client(app, "admin", ids)
    page = client.get("/admin/atividades/importar/preview", follow_redirects=False)
    if page.status_code != 200:
        return {"status_code": int(page.status_code), "html": ""}
    page_html = page.get_data(as_text=True)
    csrf_token = _extract_csrf_token_from_first_post_form(page_html)
    csv_content = (
        "nome;tipo_atividade;grupo_numero;grupo_descricao;tem_limitacao;tipo_limitacao;"
        "limite_horas_total;limite_horas_semestral\n"
        "Palestras;Acadêmica Complementar;1;Grupo Demo;nao;;;\n"
    )
    preview = client.post(
        "/admin/atividades/importar/preview",
        data={
            "mode": "create_only",
            "csrf_token": csrf_token,
            "csv_arquivo": (io.BytesIO(csv_content.encode("utf-8")), "atividades.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    return {
        "status_code": int(preview.status_code),
        "html": preview.get_data(as_text=True) if preview.status_code == 200 else "",
    }


def _build_csrf_inventory(tmp_path: Path) -> dict:
    state = _setup_isolated_csrf_clients(tmp_path)
    app = state["app"]
    ids = state["ids"]
    project_root = Path(BASE)

    try:
        source_metadata = _collect_route_source_metadata(project_root)
        matchers = _build_route_matchers(app)
        page_results = []
        page_evidences: dict[str, list[dict]] = defaultdict(list)

        for request_meta in _build_page_requests(app, ids):
            rendered = _render_page(app, ids, request_meta["role"], request_meta["path"])
            page_results.append(
                {
                    "label": request_meta["label"],
                    "path": request_meta["path"],
                    "role": request_meta["role"],
                    "status_code": rendered["status_code"],
                }
            )
            if rendered["status_code"] == 200:
                for route, evidences in _analyze_page_html(
                    request_meta["label"],
                    request_meta["path"],
                    rendered["html"],
                    matchers,
                ).items():
                    for evidence in evidences:
                        _add_evidence(page_evidences, route, evidence)

        preview_page = _render_atividades_import_preview_scenario(app, ids)
        page_results.append(
            {
                "label": "/admin/atividades/importar/preview#preview",
                "path": "/admin/atividades/importar/preview",
                "role": "admin",
                "status_code": preview_page["status_code"],
            }
        )
        if preview_page["status_code"] == 200:
            for route, evidences in _analyze_page_html(
                "/admin/atividades/importar/preview#preview",
                "/admin/atividades/importar/preview",
                preview_page["html"],
                matchers,
            ).items():
                for evidence in evidences:
                    _add_evidence(page_evidences, route, evidence)

        rows = []
        for rule in sorted(
            [item for item in app.url_map.iter_rules() if set(item.methods or []) & MUTATING_METHODS],
            key=lambda item: (item.rule, item.endpoint),
        ):
            methods = sorted(set(rule.methods or []) & MUTATING_METHODS)
            view_func = app.view_functions.get(rule.endpoint)
            unwrapped = inspect.unwrap(view_func) if view_func else None
            module_name = unwrapped.__module__ if unwrapped else ""
            func_name = unwrapped.__name__ if unwrapped else rule.endpoint
            meta = source_metadata.get((module_name, func_name), {"decorators": [], "templates": []})
            decorators = set(meta.get("decorators", []))
            route_evidences = list(page_evidences.get(rule.rule, []))

            risk: list[str] = []
            notes: list[str] = []

            if rule.rule in NOT_APPLICABLE_DOCUMENTED:
                status = "not_applicable_documented"
                notes.append(NOT_APPLICABLE_DOCUMENTED[rule.rule])
            else:
                form_evidences = [ev for ev in route_evidences if ev["kind"] == "rendered_form"]
                dynamic_evidences = [ev for ev in route_evidences if ev["kind"] == "dynamic_form"]
                fetch_evidences = [ev for ev in route_evidences if ev["kind"] == "fetch"]

                zero_token_form = next((ev for ev in form_evidences if int(ev["token_count"]) == 0), None)
                duplicate_token_form = next((ev for ev in form_evidences if int(ev["token_count"]) > 1), None)
                if zero_token_form:
                    status = "blocked_real_risk"
                    risk.append(f"form_without_csrf:{zero_token_form['page']}")
                elif duplicate_token_form:
                    status = "blocked_real_risk"
                    risk.append(f"form_with_duplicate_csrf:{duplicate_token_form['page']}")
                elif rule.rule in STATUS_OVERRIDE_BY_ROUTE and rule.rule in SPECIFIC_REGRESSION_TESTS:
                    status = STATUS_OVERRIDE_BY_ROUTE[rule.rule]
                    notes.extend(SPECIFIC_REGRESSION_TESTS[rule.rule])
                elif form_evidences:
                    status = "ok_rendered_form_token"
                elif dynamic_evidences:
                    status = "ok_dynamic_form_token"
                elif fetch_evidences:
                    status = "ok_fetch_token"
                elif rule.rule in SPECIFIC_REGRESSION_TESTS:
                    status = "ok_specific_regression_test"
                    notes.extend(SPECIFIC_REGRESSION_TESTS[rule.rule])
                else:
                    status = "blocked_real_risk"
                    risk.append("no_rendered_or_test_evidence")

            row = {
                "route": rule.rule,
                "method": ",".join(methods),
                "view_function": f"{module_name}.{func_name}" if module_name else func_name,
                "template_related": list(meta.get("templates", [])),
                "requires_login": _infer_login_requirement(rule.rule, decorators),
                "has_post_form": any(ev["kind"] == "rendered_form" for ev in route_evidences),
                "csrf_in_html": None
                if not any(ev["kind"] == "rendered_form" for ev in route_evidences)
                else all(int(ev.get("token_count", 0)) == 1 for ev in route_evidences if ev["kind"] == "rendered_form"),
                "token_counts_per_form": [
                    {
                        "page": ev["page"],
                        "action": ev["action"],
                        "token_counts": [int(ev["token_count"])],
                    }
                    for ev in route_evidences
                    if ev["kind"] == "rendered_form"
                ],
                "has_fetch_post": any(ev["kind"] == "fetch" for ev in route_evidences),
                "fetch_sends_token": None
                if not any(ev["kind"] == "fetch" for ev in route_evidences)
                else True,
                "has_dynamic_form": any(ev["kind"] == "dynamic_form" for ev in route_evidences),
                "risk": risk,
                "notes": notes,
                "evidence": route_evidences,
                "status": status,
            }
            rows.append(row)

        summary = {
            "total_mutating_routes": len(rows),
            "status_counts": {},
            "high_risk_routes": 0,
            "page_statuses": page_results,
        }
        for row in rows:
            summary["status_counts"][row["status"]] = summary["status_counts"].get(row["status"], 0) + 1
        summary["high_risk_routes"] = sum(1 for row in rows if row["status"] == "blocked_real_risk")

        return {"summary": summary, "rows": rows}
    finally:
        _teardown_isolated_csrf_clients(state)


@pytest.mark.parametrize("shadow_read_flag", [None, "1"])
def test_csrf_inventory_audit_generates_report_and_closes_route_matrix(request, tmp_path, monkeypatch, shadow_read_flag):
    if shadow_read_flag is None:
        monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    else:
        monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", shadow_read_flag)

    update_snapshots = request.config.getoption("--update-csrf-snapshots", default=False)

    artifacts_dir = Path(BASE) / "tests" / "_artifacts"
    suffix = "shadow_on" if shadow_read_flag else "shadow_off"
    canonical_path = artifacts_dir / f"csrf_inventory_{suffix}.json"

    if not update_snapshots and not canonical_path.exists():
        raise AssertionError(
            f"Canonical snapshot missing, run with --update-csrf-snapshots to create: "
            f"{canonical_path}"
        )
    can_before_stat = canonical_path.stat() if canonical_path.exists() else None
    can_before_bytes = canonical_path.read_bytes() if canonical_path.exists() else None

    report = _build_csrf_inventory(tmp_path)
    rows = report["rows"]
    summary = report["summary"]

    assert rows, "Inventario CSRF vazio"
    assert set(summary["status_counts"]).issubset(ALLOWED_STATUSES)

    observed_json = json.dumps(report, ensure_ascii=False, indent=2)
    if can_before_bytes is None:
        snapshot_newline = os.linesep
    elif bytes((13, 10)) in can_before_bytes:
        snapshot_newline = chr(13) + chr(10)
    else:
        snapshot_newline = chr(10)
    observed_snapshot_json = observed_json.replace(chr(10), snapshot_newline)
    observed_bytes = observed_snapshot_json.encode("utf-8")

    if update_snapshots:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        new_bytes = observed_bytes
        if can_before_bytes == new_bytes:
            print(f"CSRF inventory snapshot unchanged (identical bytes): {canonical_path}")
            updated_count = 0
            unchanged_count = 1
        else:
            canonical_path.write_bytes(new_bytes)
            can_after_bytes = canonical_path.read_bytes()
            assert can_after_bytes == new_bytes, (
                f"Byte-idempotency failure: written bytes differ for {canonical_path}"
            )
            print(f"CSRF inventory snapshot updated: {canonical_path}")
            updated_count = 1
            unchanged_count = 0
        assert updated_count + unchanged_count == 1
        print(
            f"Update summary for {suffix}: "
            f"{updated_count} updated, {unchanged_count} unchanged"
        )
    else:
        tmp_report_path = tmp_path / f"csrf_inventory_{suffix}.json"
        tmp_report_path.write_bytes(observed_bytes)

        if can_before_bytes is not None:
            canonical_json = can_before_bytes.decode("utf-8")
            if observed_snapshot_json != canonical_json:
                diff = list(
                    difflib.unified_diff(
                        canonical_json.splitlines(keepends=True),
                        observed_snapshot_json.splitlines(keepends=True),
                        fromfile=str(canonical_path),
                        tofile=str(tmp_report_path),
                    )
                )
                diff_text = "".join(diff)
                raise AssertionError(
                    f"CSRF inventory snapshot mismatch for {suffix}:\n{diff_text}"
                )

        can_after_stat = canonical_path.stat()
        can_after_bytes = canonical_path.read_bytes()
        assert can_before_stat is not None, f"Canonical snapshot missing: {canonical_path}"
        assert can_before_stat.st_mtime_ns == can_after_stat.st_mtime_ns, (
            f"Canonical snapshot mtime changed: {canonical_path}"
        )
        assert can_before_stat.st_size == can_after_stat.st_size, (
            f"Canonical snapshot size changed: {canonical_path}"
        )
        assert can_before_bytes == can_after_bytes, (
            f"Canonical snapshot content changed: {canonical_path}"
        )

        print(f"CSRF inventory observed written to: {tmp_report_path}")

    print(json.dumps(summary, ensure_ascii=True))
    for row in rows:
        print(
            " | ".join(
                [
                    row["status"],
                    row["method"],
                    row["route"],
                    row["view_function"],
                    ",".join(row["template_related"]) if row["template_related"] else "-",
                ]
            )
        )

    blocked_rows = [row for row in rows if row["status"] == "blocked_real_risk"]
    assert not blocked_rows, (
        "Foram encontrados riscos CSRF bloqueantes: "
        + json.dumps(
            [
                {
                    "route": row["route"],
                    "status": row["status"],
                    "risk": row["risk"],
                    "notes": row["notes"],
                }
                for row in blocked_rows
            ],
            ensure_ascii=True,
        )
    )

    assert (
        message_key_for_default(
            "Apenas versões ativas podem ser selecionadas para esta matriz."
        )
        == "msg_ea6b5b4169b5a6d6"
    )
    assert (
        message_key_for_default(
            "A norma desta versão não está vinculada à matriz."
        )
        == "msg_fb42c99933531b0e"
    )
    assert (
        message_key_for_default(
            "Esta solicitação já possui versão normativa registrada. "
            "Para trocar a atividade, crie uma nova solicitação."
        )
        == "msg_ee9900f9eb19b308"
    )
