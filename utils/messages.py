from __future__ import annotations

import ast
import hashlib
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import flash as flask_flash
from flask import g, has_request_context


__all__ = [
    "flash",
    "frontend_message_templates",
    "list_editable_messages",
    "message_key_for_default",
    "reset_message_override",
    "resolve_user_message",
    "save_message_override",
]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MESSAGE_TABLE_NAME = "mensagens_editaveis"
PLACEHOLDER_RE = re.compile(r"\{(value_\d+)\}")
JS_LITERAL_RE = re.compile(r"`(?:[^`\\]|\\.)*`|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", re.DOTALL)
TEMPLATE_MESSAGE_CALL_PATTERNS = (
    re.compile(
        r"\buser_message\(\s*(?P<literal>`(?:[^`\\]|\\.)*`|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")\s*\)",
        re.DOTALL,
    ),
)

FRONTEND_CALL_PATTERNS = (
    (re.compile(r"(?:window\.)?alert\(", re.DOTALL), "alert"),
    (re.compile(r"(?:window\.)?confirm\(", re.DOTALL), "confirm"),
    (re.compile(r"(?:window\.)?showToast\?\.\(", re.DOTALL), "toast"),
    (re.compile(r"(?:window\.)?showToast\(", re.DOTALL), "toast"),
)
FRONTEND_MESSAGE_BLOCK_PATTERNS = (
    (re.compile(r"\b(?:const|let|var)\s+message\s*=\s*(?P<body>.*?);", re.DOTALL), "confirm"),
)
FRONTEND_LINE_KEYS = ("deleteMessageSingle", "deleteMessageMultiple")
BACKEND_VALUE_ERROR_TYPES = {"ValueError", "RuntimeError"}
BACKEND_SINK_NAMES = {"flash", "flash_error", "flash_success", "flash_info", "resolve_user_message"}
PAYLOAD_KEYS = {"message", "mensagem", "titulo", "title"}
EXCLUDED_FRONTEND_NAME_PARTS = ("backup", "copia", "krthinkpad", "demo")

ROUTE_AREA_LABELS = {
    "acesso": "Acesso",
    "alertas": "Alertas",
    "alunos": "Alunos",
    "arquivos": "Arquivos",
    "atividades": "Atividades",
    "banco-dados": "Banco de dados",
    "backup": "Banco de dados",
    "configuracoes": "Configurações",
    "core": "Autenticação",
    "cursos": "Cursos",
    "dashboard": "Dashboard",
    "login": "Autenticação",
    "logout": "Autenticação",
    "matrizes": "Matrizes",
    "mensagens": "Mensagens",
    "meus_dados": "Conta",
    "processar_requisicao": "Requisições",
    "reportes": "Reportes",
    "requisicao": "Requisições",
    "requisicoes": "Requisições",
    "turmas": "Turmas",
}

FILE_AREA_LABELS = {
    "admin_acesso": "Acesso",
    "admin_alertas": "Alertas",
    "admin_alunos": "Alunos",
    "admin_arquivos": "Arquivos",
    "admin_atividades": "Atividades",
    "admin_banco_dados": "Banco de dados",
    "admin_cursos": "Cursos",
    "admin_mensagens": "Mensagens",
    "admin_matrizes": "Matrizes",
    "admin_requisicoes": "Requisições",
    "admin_turmas": "Turmas",
    "aluno_minhas_requisicoes": "Requisições",
}

FLOW_VERB_LABELS = {
    "adicionar": "Criar",
    "nova": "Criar",
    "novo": "Criar",
    "criar": "Criar",
    "editar": "Editar",
    "deletar": "Excluir",
    "excluir": "Excluir",
    "remover": "Excluir",
    "importar": "Importar",
    "exportar": "Exportar",
    "processar": "Processar",
    "salvar": "Salvar",
    "resetar": "Resetar",
    "restaurar": "Restaurar",
    "download": "Baixar",
    "upload": "Enviar",
    "connect": "Conectar",
    "disconnect": "Desconectar",
    "oauth": "Conectar",
}


def _sanitize_message_text(text: object) -> str:
    return str(text or "").replace("\r\n", "\n").strip()


def _tokenize_identifier(value: str) -> list[str]:
    return [token for token in re.split(r"[_\-/]+", str(value or "").strip()) if token]


def _humanize_identifier(value: str) -> str:
    acronyms = {
        "aac": "AAC",
        "api": "API",
        "csv": "CSV",
        "db": "DB",
        "id": "ID",
        "oauth": "OAuth",
        "ui": "UI",
    }
    words = []
    for token in _tokenize_identifier(value):
        lower = token.casefold()
        words.append(acronyms.get(lower, token.capitalize()))
    return " ".join(words)


def _to_flow_target(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return ""
    return text[:1].lower() + text[1:]


def _to_header_segment(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return ""

    first_token_match = re.match(r"[A-Za-zÀ-ÿ0-9]+", text)
    if first_token_match:
        token = first_token_match.group(0)
        # Preserva inícios que parecem nome próprio/acrônimo (ex.: OAuth, API).
        if (len(token) > 1 and token.isupper()) or any(char.isupper() for char in token[1:]):
            return text

    return text[:1].lower() + text[1:]


def _singularize_pt(label: str) -> str:
    word = str(label or "").strip()
    lowered = word.casefold()
    if lowered.endswith("ões"):
        return word[:-3] + "ão"
    if lowered.endswith("aes"):
        return word[:-3] + "ao"
    if lowered.endswith("s") and len(word) > 3:
        return word[:-1]
    return word


def _route_area_label(route: str | None) -> str:
    route_text = str(route or "").strip()
    if not route_text.startswith("/"):
        return ""
    parts = [segment for segment in route_text.strip("/").split("/") if segment and not segment.startswith("<")]
    if not parts:
        return ""
    if parts[0] in {"admin", "aluno"}:
        parts = parts[1:]
    if parts and parts[0] == "api":
        parts = parts[1:]
    if not parts:
        return ""
    key = parts[0]
    return ROUTE_AREA_LABELS.get(key, _humanize_identifier(key))


def _source_area_label(usage: dict[str, Any]) -> str:
    route_area = _route_area_label(usage.get("source_route"))
    if route_area:
        return route_area

    source_path = str(usage.get("source_path") or "")
    if source_path.startswith("templates/") or source_path.startswith("static/js/"):
        stem = Path(source_path).stem
        label = FILE_AREA_LABELS.get(stem)
        if label:
            return label
        base = stem
        if base.startswith("admin_"):
            base = base[len("admin_") :]
        elif base.startswith("aluno_"):
            base = base[len("aluno_") :]
        if base in {"base", "base_aluno"}:
            return "Interface"
        return ROUTE_AREA_LABELS.get(base, _humanize_identifier(base))

    if source_path == "main.py":
        return "Sistema"
    if source_path.startswith("app/views/aluno"):
        return "Aluno"
    if source_path.startswith("app/views/core"):
        return "Autenticação"
    if source_path.startswith("app/auth"):
        return "Acesso"
    if source_path.startswith("app/db_maintenance"):
        return "Banco de dados"
    return "Sistema"


def _flow_from_function_name(function_name: str | None) -> str:
    raw_name = str(function_name or "").strip()
    if not raw_name:
        return ""
    normalized = raw_name
    for prefix in ("admin_", "aluno_"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break

    tokens = [token for token in normalized.split("_") if token]
    if not tokens:
        return ""

    if tokens[0] == "api":
        tokens = tokens[1:]
    if not tokens:
        return ""

    if tokens[0] not in FLOW_VERB_LABELS:
        verb_index = next((index for index, token in enumerate(tokens[1:], start=1) if token in FLOW_VERB_LABELS), None)
        if verb_index is not None:
            context_tokens = [token for token in tokens[:verb_index] if token not in {"admin", "aluno", "api"}]
            action = FLOW_VERB_LABELS[tokens[verb_index]]
            tail_tokens = [token for token in tokens[verb_index + 1 :] if token not in {"admin", "aluno", "api"}]
            if tail_tokens:
                action_target = _to_flow_target(_humanize_identifier("_".join(tail_tokens)))
                action = f"{action} {action_target}".strip()
            context_label = _humanize_identifier("_".join(context_tokens)) if context_tokens else ""
            if context_label:
                return f"{context_label} · {action}"
            return action

    verb = tokens[0]
    action = FLOW_VERB_LABELS.get(verb)
    if action:
        target_tokens = [token for token in tokens[1:] if token not in {"admin", "aluno", "api"}]
        if not target_tokens:
            return action
        target = _to_flow_target(_humanize_identifier("_".join(target_tokens)))
        return f"{action} {target}".strip()

    if tokens[0] == "dashboard":
        return "Visualizar painel"

    noun = _to_flow_target(_humanize_identifier("_".join(tokens)))
    return f"Gerir {noun}".strip()


def _flow_from_message_text(default_text: str) -> str:
    text = str(default_text or "").strip()
    if not text:
        return ""
    lowered = text.casefold()
    if "excluir" in lowered or "remover" in lowered:
        match = re.search(
            r"(?:excluir|remover)\s+(?:o|a|os|as)\s+(?:\{value_\d+\}\s+)?([A-Za-zÀ-ÿ]+)",
            text,
            re.IGNORECASE,
        )
        if match:
            target = _singularize_pt(match.group(1).casefold())
            return f"Excluir {target}".strip()
    return ""


def _flow_label_for_usage(entry: dict[str, Any], usage: dict[str, Any]) -> str:
    text_flow = _flow_from_message_text(entry["default_text"])
    if text_flow:
        return text_flow

    area = _source_area_label(usage)

    function_flow = _flow_from_function_name(usage.get("source_function"))
    if function_flow:
        if area:
            area_prefix = f"{area} · "
            if function_flow.startswith(area_prefix):
                return function_flow[len(area_prefix) :]
        return function_flow

    route = str(usage.get("source_route") or "")
    if route:
        parts = [segment for segment in route.strip("/").split("/") if segment and not segment.startswith("<")]
        if parts and parts[0] in {"admin", "aluno"}:
            parts = parts[1:]
        if parts and parts[0] == "api":
            parts = parts[1:]
        if len(parts) >= 2:
            action = FLOW_VERB_LABELS.get(parts[-1])
            if action:
                target = _to_flow_target(_humanize_identifier(parts[-2]))
                return f"{action} {target}".strip()

    if area in {"Aluno", "Sistema"}:
        return "Fluxo principal"
    return f"Gerir {_to_flow_target(area)}"


def _state_label_for_entry(entry: dict[str, Any]) -> str:
    default_text = str(entry["default_text"] or "")
    lowered = default_text.casefold()
    kinds = {str(kind) for kind in entry.get("kinds", ())}

    if "confirm" in kinds:
        return "confirmação"
    if "desconect" in lowered:
        return "desconexão"
    if "conect" in lowered:
        return "conexão"
    if "sucesso" in lowered:
        return "sucesso"
    if "erro" in lowered or "falha" in lowered:
        return "erro"
    if "não encontrado" in lowered or "nao encontrado" in lowered:
        return "não encontrado"
    if "já existe" in lowered or "ja existe" in lowered or "duplic" in lowered:
        return "duplicado"
    if "obrigat" in lowered or lowered.startswith("informe ") or lowered.startswith("selecione "):
        return "campo obrigatório"
    if "inválid" in lowered or "inval" in lowered:
        return "valor inválido"
    if "exclu" in lowered:
        return "exclusão"
    if "atualiz" in lowered:
        return "atualização"
    if "restaur" in lowered or "reset" in lowered:
        return "restauração"
    if "deferid" in lowered or "indeferid" in lowered or "pendente" in lowered:
        return "processamento"
    return "mensagem"


def _display_context_for_entry(entry: dict[str, Any]) -> dict[str, str]:
    areas = []
    flows = []
    for usage in entry.get("usages", []):
        area = _source_area_label(usage)
        flow = _flow_label_for_usage(entry, usage)
        if area:
            areas.append(area)
        if flow:
            flows.append(flow)

    unique_areas = sorted(set(areas))
    unique_flows = sorted(set(flows))

    if len(unique_areas) == 1:
        display_area = unique_areas[0]
    elif len(unique_areas) > 1:
        display_area = "Múltiplas origens"
    else:
        display_area = "Sistema"

    if len(unique_flows) == 1:
        display_flow = unique_flows[0]
    elif len(unique_flows) > 1:
        display_flow = "Fluxo compartilhado"
    else:
        display_flow = "Fluxo principal"

    display_state = _state_label_for_entry(entry)
    return {
        "display_area": display_area,
        "display_flow": display_flow,
        "display_state": display_state,
        "display_title": f"{display_area} > {_to_header_segment(display_flow)} > {_to_header_segment(display_state)}",
    }


def message_key_for_default(default_text: str) -> str:
    normalized = _sanitize_message_text(default_text)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    return f"msg_{digest}"


def _placeholder_names(text: str) -> list[str]:
    return list(dict.fromkeys(PLACEHOLDER_RE.findall(text)))


def _safe_format(template: str, values: dict[str, object]) -> str:
    class _SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return str(template).format_map(_SafeDict({key: "" if value is None else str(value) for key, value in values.items()}))


def _should_keep_frontend_literal(text: str) -> bool:
    cleaned = _sanitize_message_text(text)
    if not cleaned:
        return False
    lowered = cleaned.casefold()
    if lowered in {"ok", "error", "warning", "success", "info", "post", "get", "patch", "delete"}:
        return False
    if not re.search(r"[A-Za-zÀ-ÿ]", cleaned):
        return False
    if len(cleaned) < 8 and " " not in cleaned and not any(token in cleaned for token in "?!.:"):
        return False
    if "/" in cleaned and " " not in cleaned:
        return False
    if cleaned.startswith("#") or cleaned.startswith("."):
        return False
    return True


def _iter_backend_files() -> list[Path]:
    files = [
        PROJECT_ROOT / "main.py",
        PROJECT_ROOT / "app" / "academics.py",
        PROJECT_ROOT / "app" / "auth.py",
        PROJECT_ROOT / "app" / "db_maintenance.py",
        PROJECT_ROOT / "app" / "settings.py",
        PROJECT_ROOT / "app" / "uploads.py",
        # UT-3: novos donos canonicos de sinks de mensagem movidos de main.py
        # (_admin_access_denied_response -> authz_gate, handle_large_upload -> errors).
        PROJECT_ROOT / "app" / "web" / "authz_gate.py",
        PROJECT_ROOT / "app" / "web" / "errors.py",
    ]
    views_dir = PROJECT_ROOT / "app" / "views"
    if views_dir.is_dir():
        files.extend(
            path
            for path in views_dir.rglob("*.py")
            if "__pycache__" not in path.relative_to(PROJECT_ROOT).parts
        )

    unique_files = {
        path.relative_to(PROJECT_ROOT).as_posix(): path
        for path in files
        if path.is_file()
    }
    return [unique_files[key] for key in sorted(unique_files)]


def _iter_frontend_files() -> list[Path]:
    files: list[Path] = []
    templates_dir = PROJECT_ROOT / "templates"
    if templates_dir.is_dir():
        files.extend(sorted(templates_dir.rglob("*.html")))
    js_dir = PROJECT_ROOT / "static" / "js"
    if js_dir.is_dir():
        files.extend(sorted(js_dir.rglob("*.js")))

    filtered = []
    for path in files:
        lowered_name = path.name.casefold()
        if any(part in lowered_name for part in EXCLUDED_FRONTEND_NAME_PARTS):
            continue
        filtered.append(path)
    return filtered


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _rel_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _extract_python_template(node: ast.AST, source: str) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        text = _sanitize_message_text(node.value)
        return text or None

    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        placeholder_index = 0
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if isinstance(value, ast.FormattedValue):
                placeholder_index += 1
                parts.append(f"{{value_{placeholder_index}}}")
        text = _sanitize_message_text("".join(parts))
        return text or None

    if isinstance(node, ast.Call) and _call_name(node.func) == "str" and node.args:
        return None

    return None


def _decode_js_literal(literal: str) -> str:
    if not literal:
        return ""
    if literal.startswith("`") and literal.endswith("`"):
        content = literal[1:-1]
        placeholder_index = 0

        def replace_placeholder(_match: re.Match[str]) -> str:
            nonlocal placeholder_index
            placeholder_index += 1
            return f"{{value_{placeholder_index}}}"

        content = re.sub(r"\$\{.*?\}", replace_placeholder, content)
        return _sanitize_message_text(content.replace("\\`", "`").replace("\\n", "\n"))

    if literal[0] in {"'", '"'} and literal[-1] == literal[0]:
        quote = literal[0]
        content = literal[1:-1]
        content = content.replace(f"\\{quote}", quote).replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r").replace("\\\\", "\\")
        return _sanitize_message_text(content)

    return _sanitize_message_text(literal)


def _register_catalog_usage(
    catalog: dict[str, dict[str, Any]],
    *,
    default_text: str,
    source_path: str,
    source_line: int,
    kind: str,
    source_function: str | None = None,
    source_route: str | None = None,
    source_key: str | None = None,
) -> None:
    cleaned = _sanitize_message_text(default_text)
    if not cleaned:
        return
    key = message_key_for_default(cleaned)
    entry = catalog.setdefault(
        key,
        {
            "key": key,
            "default_text": cleaned,
            "usages": [],
            "kinds": set(),
        },
    )
    usage_marker = (source_path, source_line, kind, source_function or "", source_route or "", source_key or "")
    if usage_marker in {
        (
            usage["source_path"],
            usage["source_line"],
            usage["kind"],
            usage.get("source_function", ""),
            usage.get("source_route", ""),
            usage.get("source_key", ""),
        )
        for usage in entry["usages"]
    }:
        return
    entry["usages"].append(
        {
            "source_path": source_path,
            "source_line": source_line,
            "kind": kind,
            "source_function": source_function or "",
            "source_route": source_route or "",
            "source_key": source_key or "",
        }
    )
    entry["kinds"].add(kind)


def _route_path_from_decorators(decorators: list[ast.expr], source: str) -> str | None:
    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            continue
        if _call_name(decorator.func) not in {"route", "aluno_runtime_route"}:
            continue
        if not decorator.args:
            continue
        value = _extract_python_template(decorator.args[0], source)
        if value and value.startswith("/"):
            return value
    return None


def _legacy_route_paths(tree: ast.AST, source: str) -> dict[str, str]:
    routes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "LegacyRouteSpec":
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        rule_node = keywords.get("rule") or (node.args[0] if node.args else None)
        view_func = keywords.get("view_func") or (node.args[2] if len(node.args) >= 3 else None)
        rule = _extract_python_template(rule_node, source)
        if rule and rule.startswith("/") and isinstance(view_func, ast.Name):
            routes[view_func.id] = rule
    return routes


class _BackendMessageVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        catalog: dict[str, dict[str, Any]],
        source: str,
        source_path: str,
        legacy_route_paths: dict[str, str] | None = None,
    ):
        self.catalog = catalog
        self.source = source
        self.source_path = source_path
        self.legacy_route_paths = legacy_route_paths or {}
        self.scope_stack: list[dict[str, str]] = []

    def _current_scope(self) -> dict[str, str]:
        if self.scope_stack:
            return self.scope_stack[-1]
        return {"function": "", "route": ""}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        scope = {
            "function": node.name,
            "route": (
                _route_path_from_decorators(node.decorator_list, self.source)
                or self.legacy_route_paths.get(node.name, "")
            ),
        }
        self.scope_stack.append(scope)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        scope = {
            "function": node.name,
            "route": (
                _route_path_from_decorators(node.decorator_list, self.source)
                or self.legacy_route_paths.get(node.name, "")
            ),
        }
        self.scope_stack.append(scope)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        scope = self._current_scope()
        call_name = _call_name(node.func)
        if call_name in BACKEND_SINK_NAMES and node.args:
            template = _extract_python_template(node.args[0], self.source)
            if template:
                kind = "flash" if call_name.startswith("flash") else "payload"
                _register_catalog_usage(
                    self.catalog,
                    default_text=template,
                    source_path=self.source_path,
                    source_line=node.lineno,
                    kind=kind,
                    source_function=scope["function"],
                    source_route=scope["route"],
                )

        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        scope = self._current_scope()
        for key_node, value_node in zip(node.keys, node.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue
            if key_node.value not in PAYLOAD_KEYS:
                continue
            template = _extract_python_template(value_node, self.source)
            if not template:
                continue
            _register_catalog_usage(
                self.catalog,
                default_text=template,
                source_path=self.source_path,
                source_line=node.lineno,
                kind="payload",
                source_function=scope["function"],
                source_route=scope["route"],
            )
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        scope = self._current_scope()
        if not isinstance(node.exc, ast.Call):
            self.generic_visit(node)
            return
        exc_name = _call_name(node.exc.func)
        if exc_name not in BACKEND_VALUE_ERROR_TYPES or not node.exc.args:
            self.generic_visit(node)
            return
        template = _extract_python_template(node.exc.args[0], self.source)
        if template:
            _register_catalog_usage(
                self.catalog,
                default_text=template,
                source_path=self.source_path,
                source_line=node.lineno,
                kind="exception",
                source_function=scope["function"],
                source_route=scope["route"],
            )
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        scope = self._current_scope()
        value = node.value
        if not isinstance(value, ast.Tuple) or len(value.elts) != 2:
            self.generic_visit(node)
            return

        for element in value.elts:
            template = _extract_python_template(element, self.source)
            if not template:
                continue
            _register_catalog_usage(
                self.catalog,
                default_text=template,
                source_path=self.source_path,
                source_line=node.lineno,
                kind="return-message",
                source_function=scope["function"],
                source_route=scope["route"],
            )

        self.generic_visit(node)


def _scan_backend_catalog(catalog: dict[str, dict[str, Any]]) -> None:
    for path in _iter_backend_files():
        source = _read_text(path)
        tree = ast.parse(source)
        visitor = _BackendMessageVisitor(
            catalog=catalog,
            source=source,
            source_path=_rel_path(path),
            legacy_route_paths=_legacy_route_paths(tree, source),
        )
        visitor.visit(tree)


def _extract_frontend_literals(body: str) -> list[str]:
    values = []
    for literal_match in JS_LITERAL_RE.finditer(body):
        decoded = _decode_js_literal(literal_match.group(0))
        if _should_keep_frontend_literal(decoded):
            values.append(decoded)
    return values


def _extract_frontend_call_body(source: str, open_paren_index: int) -> str | None:
    depth = 0
    in_quote: str | None = None
    escaped = False

    for index in range(open_paren_index, len(source)):
        char = source[index]

        if in_quote is not None:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == in_quote:
                in_quote = None
            continue

        if char in {"'", '"', "`"}:
            in_quote = char
            continue

        if char == "(":
            depth += 1
            continue

        if char == ")":
            depth -= 1
            if depth == 0:
                return source[open_paren_index + 1:index]

    return None


def _scan_frontend_catalog(catalog: dict[str, dict[str, Any]]) -> None:
    for path in _iter_frontend_files():
        source = _read_text(path)
        source_path = _rel_path(path)

        if path.suffix.lower() == ".html":
            for pattern in TEMPLATE_MESSAGE_CALL_PATTERNS:
                for match in pattern.finditer(source):
                    decoded = _decode_js_literal(match.group("literal"))
                    if not decoded:
                        continue
                    source_line = source.count("\n", 0, match.start()) + 1
                    _register_catalog_usage(
                        catalog,
                        default_text=decoded,
                        source_path=source_path,
                        source_line=source_line,
                        kind="template",
                    )

        for pattern, kind in FRONTEND_CALL_PATTERNS:
            for match in pattern.finditer(source):
                body = _extract_frontend_call_body(source, match.end() - 1)
                if body is None:
                    continue
                for decoded in _extract_frontend_literals(body):
                    source_line = source.count("\n", 0, match.start()) + 1
                    _register_catalog_usage(
                        catalog,
                        default_text=decoded,
                        source_path=source_path,
                        source_line=source_line,
                        kind=kind,
                    )

        for pattern, kind in FRONTEND_MESSAGE_BLOCK_PATTERNS:
            for match in pattern.finditer(source):
                body = match.group("body") or ""
                for decoded in _extract_frontend_literals(body):
                    source_line = source.count("\n", 0, match.start()) + 1
                    _register_catalog_usage(
                        catalog,
                        default_text=decoded,
                        source_path=source_path,
                        source_line=source_line,
                        kind=kind,
                    )

        for line_number, line in enumerate(source.splitlines(), start=1):
            line_key = next((key for key in FRONTEND_LINE_KEYS if key in line), "")
            if not line_key:
                continue
            for decoded in _extract_frontend_literals(line):
                _register_catalog_usage(
                    catalog,
                    default_text=decoded,
                    source_path=source_path,
                    source_line=line_number,
                    kind="confirm",
                    source_key=line_key,
                )


@lru_cache(maxsize=1)
def _message_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    _scan_backend_catalog(catalog)
    _scan_frontend_catalog(catalog)
    for entry in catalog.values():
        entry["usages"].sort(key=lambda item: (item["source_path"], item["source_line"], item["kind"]))
        entry["kinds"] = tuple(sorted(entry["kinds"]))
        entry["placeholders"] = tuple(_placeholder_names(entry["default_text"]))
    return catalog


@lru_cache(maxsize=1)
def _exact_lookup() -> dict[str, dict[str, Any]]:
    return {entry["default_text"]: entry for entry in _message_catalog().values() if not entry["placeholders"]}


@lru_cache(maxsize=1)
def _dynamic_lookup() -> tuple[tuple[re.Pattern[str], dict[str, Any]], ...]:
    compiled: list[tuple[re.Pattern[str], dict[str, Any]]] = []
    for entry in _message_catalog().values():
        if not entry["placeholders"]:
            continue
        chunks: list[str] = []
        cursor = 0
        for match in PLACEHOLDER_RE.finditer(entry["default_text"]):
            chunks.append(re.escape(entry["default_text"][cursor:match.start()]))
            chunks.append(f"(?P<{match.group(1)}>.+?)")
            cursor = match.end()
        chunks.append(re.escape(entry["default_text"][cursor:]))
        compiled.append((re.compile("^" + "".join(chunks) + "$", re.DOTALL), entry))
    compiled.sort(key=lambda item: len(item[1]["default_text"]), reverse=True)
    return tuple(compiled)


def ensure_message_overrides_schema(conn) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MESSAGE_TABLE_NAME} (
            chave TEXT PRIMARY KEY,
            texto TEXT NOT NULL,
            atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def _get_runtime_db_connection():
    main_module = sys.modules.get("main")
    if main_module is not None and hasattr(main_module, "get_db_connection"):
        return main_module.get_db_connection()

    from app.db import get_db_connection as _get_db_connection

    return _get_db_connection()


def _get_overrides(conn=None) -> dict[str, str]:
    if has_request_context() and hasattr(g, "_message_overrides_cache"):
        return dict(g._message_overrides_cache)

    current_conn = conn or _get_runtime_db_connection()
    ensure_message_overrides_schema(current_conn)
    rows = current_conn.execute(f"SELECT chave, texto FROM {MESSAGE_TABLE_NAME}").fetchall()
    overrides = {str(row["chave"]): str(row["texto"]) for row in rows}

    if has_request_context():
        g._message_overrides_cache = dict(overrides)

    return overrides


def _clear_override_caches() -> None:
    if has_request_context():
        g.pop("_message_overrides_cache", None)
        g.pop("_frontend_message_templates_cache", None)


def _current_template_for_entry(entry: dict[str, Any], conn=None) -> str:
    overrides = _get_overrides(conn)
    return overrides.get(entry["key"], entry["default_text"])


def resolve_user_message(message: object, *, conn=None) -> str:
    raw_text = _sanitize_message_text(message)
    if not raw_text:
        return raw_text

    exact_entry = _exact_lookup().get(raw_text)
    if exact_entry is not None:
        return _current_template_for_entry(exact_entry, conn)

    for pattern, entry in _dynamic_lookup():
        match = pattern.match(raw_text)
        if not match:
            continue
        template = _current_template_for_entry(entry, conn)
        return _safe_format(template, match.groupdict())

    return raw_text


def flash(message: object, category: str = "message") -> None:
    flask_flash(resolve_user_message(message), category)


def save_message_override(conn, message_key: str, message_text: str) -> None:
    key = str(message_key or "").strip()
    text = _sanitize_message_text(message_text)
    if not key:
        raise ValueError("Informe a mensagem que deve ser atualizada.")
    if key not in _message_catalog():
        raise ValueError("A mensagem selecionada não existe mais no catálogo atual.")
    if not text:
        raise ValueError("Informe um texto válido para a mensagem.")

    default_text = _message_catalog()[key]["default_text"]
    if text == default_text:
        reset_message_override(conn, key)
        return

    ensure_message_overrides_schema(conn)
    conn.execute(
        f"""
        INSERT INTO {MESSAGE_TABLE_NAME} (chave, texto, atualizado_em)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(chave) DO UPDATE SET texto = excluded.texto, atualizado_em = datetime('now')
        """,
        (key, text),
    )
    _clear_override_caches()


def reset_message_override(conn, message_key: str) -> None:
    key = str(message_key or "").strip()
    if not key:
        raise ValueError("Informe a mensagem que deve ser resetada.")
    ensure_message_overrides_schema(conn)
    conn.execute(f"DELETE FROM {MESSAGE_TABLE_NAME} WHERE chave = ?", (key,))
    _clear_override_caches()


def list_editable_messages(conn=None) -> list[dict[str, Any]]:
    catalog = _message_catalog()
    overrides = _get_overrides(conn)
    items: list[dict[str, Any]] = []
    decorated_entries = [
        (entry, _display_context_for_entry(entry)) for entry in catalog.values()
    ]
    for entry, display in sorted(
        decorated_entries,
        key=lambda item: (item[1]["display_title"].casefold(), item[0]["default_text"].casefold()),
    ):
        items.append(
            {
                "key": entry["key"],
                "default_text": entry["default_text"],
                "current_text": overrides.get(entry["key"], entry["default_text"]),
                "is_overridden": entry["key"] in overrides,
                "kinds": list(entry["kinds"]),
                "placeholders": list(entry["placeholders"]),
                "usage_count": len(entry["usages"]),
                "usages": list(entry["usages"]),
                "display_area": display["display_area"],
                "display_flow": display["display_flow"],
                "display_state": display["display_state"],
                "display_title": display["display_title"],
            }
        )
    return items


def frontend_message_templates(conn=None) -> dict[str, str]:
    if has_request_context() and hasattr(g, "_frontend_message_templates_cache"):
        return dict(g._frontend_message_templates_cache)

    templates: dict[str, str] = {}
    for entry in list_editable_messages(conn):
        if not any(kind in {"alert", "confirm", "toast"} for kind in entry["kinds"]):
            continue
        templates[entry["default_text"]] = entry["current_text"]

    if has_request_context():
        g._frontend_message_templates_cache = dict(templates)

    return templates