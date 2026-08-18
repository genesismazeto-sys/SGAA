from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISPLAY_FLAG = "SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY"
RESOLVER_CALLS = {"resolver_versao_por_aluno", "resolver_versao_por_matriz"}
ALLOWED_RESOLVER_CALLERS = {
    ("app/versioning/resolver.py", "resolver_versao_por_aluno"),
    ("app/versioning/snapshots.py", "prepare_versioned_requisicao_snapshot"),
}
ALLOWED_SHADOW_CALLERS = {
    ("app/views/admin/versioning.py", "admin_diagnostico_versioned_shadow_reads"),
}
ALLOWED_LATEST_SQL = {
    ("app/views/admin/matrizes.py", "_ensure_default_versao_link"),
    ("app/views/admin/matrizes.py", "_save_matriz_activity_links"),
    ("app/db_maintenance.py", "_rebuild_activity_versioning_core_v3"),
    ("app/db_maintenance.py", "_migration_v3_normalize_activity_versioning_core"),
}
SHADOW_TERMS = re.compile(r"(?:shadow|probe|comparison|compare|diverg)", re.I)
VERSION_TERMS = re.compile(r"(?:version|vers[aãa]o|resolver)", re.I)
FALLBACK_TERMS = re.compile(r"(?:preferred|preferid|latest|newest|ultima|[uú]ltima)", re.I)


@dataclass(frozen=True)
class FunctionFacts:
    name: str
    calls: frozenset[str]
    targets: frozenset[str]
    env_keys: frozenset[str]
    args: frozenset[str]
    source: str
    appends_file: bool


def production_paths() -> tuple[Path, ...]:
    paths = [ROOT / "main.py"]
    for directory in ("app", "services", "utils", "tools"):
        paths.extend((ROOT / directory).rglob("*.py"))
    return tuple(sorted(path for path in paths if path.is_file()))


def repository_sources() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8-sig")
        for path in production_paths()
    }


def dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def constant(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def static_string(node: ast.AST | None) -> str | None:
    if (value := constant(node)) is not None:
        return value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = static_string(node.left), static_string(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append(" ? ")
            else:
                return None
        return "".join(parts)
    return None


def module_name(path: str) -> str:
    value = path[:-3].replace("/", ".") if path.endswith(".py") else path.replace("/", ".")
    return value[:-9] if value.endswith(".__init__") else value


def _relative_module(path: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = module_name(path) if path.endswith("/__init__.py") else module_name(path).rpartition(".")[0]
    parts = package.split(".") if package else []
    ascend = node.level - 1
    if ascend > len(parts):
        return ""
    base = parts[: len(parts) - ascend] if ascend else parts
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def imports(tree: ast.Module, path: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                result[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            owner = _relative_module(path, node)
            for alias in node.names:
                target = f"{owner}.{alias.name}" if owner else alias.name
                result[alias.asname or alias.name] = target
    return result


def resolved(name: str, bindings: dict[str, str]) -> str:
    head, *tail = name.split(".")
    return ".".join((bindings.get(head, head), *tail))


def call_tail(node: ast.Call) -> str:
    return (dotted(node.func) or "").rsplit(".", 1)[-1]


def env_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and dotted(node.func) in {"os.getenv", "os.environ.get", "environ.get"}:
        return constant(node.args[0]) if node.args else None
    if isinstance(node, ast.Subscript) and dotted(node.value) in {"os.environ", "environ"}:
        return constant(node.slice)
    return None


def source_facts(source: str, path: str = "") -> tuple[FunctionFacts, ...]:
    tree, result = ast.parse(source), []
    bindings = imports(tree, path)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls, targets, keys = set(), set(), set()
        append = False
        for child in ast.walk(node):
            if key := env_key(child):
                keys.add(key)
            if not isinstance(child, ast.Call):
                continue
            calls.add(call_tail(child))
            if name := dotted(child.func):
                targets.add(resolved(name, bindings))
            if call_tail(child) == "open":
                mode = constant(child.args[1]) if len(child.args) > 1 else None
                mode = next((constant(k.value) for k in child.keywords if k.arg == "mode"), mode)
                append = append or bool(mode and "a" in mode.lower())
        args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        result.append(FunctionFacts(node.name, frozenset(calls), frozenset(targets), frozenset(keys),
                                    frozenset(arg.arg for arg in args), ast.get_source_segment(source, node) or "", append))
    return tuple(result)


def static_sql(source: str) -> tuple[str, ...]:
    tree = ast.parse(source)
    assigned: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if (value := static_string(node.value)) is not None:
                assigned[node.targets[0].id] = value
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or call_tail(node) not in {"execute", "executemany"} or not node.args:
            continue
        value = static_string(node.args[0])
        if value is None and isinstance(node.args[0], ast.Name):
            value = assigned.get(node.args[0].id)
        if value is not None:
            result.append(value)
    return tuple(result)


def latest_sql(sql: str) -> bool:
    value = " ".join(sql.lower().split())
    if not re.search(r"\bfrom\s+atividade_versao(?:\s+\w+)?\b", value):
        return False
    ordered = re.search(r"\border\s+by\s+(?:\w+\.)?(?:numero_versao|created_at|id)\s+desc\b", value)
    maximum = re.search(r"\bmax\s*\(\s*(?:\w+\.)?(?:numero_versao|id)\s*\)", value)
    return bool((ordered and re.search(r"\blimit\s+1\b", value)) or (maximum and "+ 1" not in value and "+1" not in value))


def has_latest_sql(source: str) -> bool:
    return any(latest_sql(sql) for sql in static_sql(source))


def branch_controls_authority(source: str, function_name: str, path: str = "") -> bool:
    tree = ast.parse(source)
    bindings = imports(tree, path)
    node = next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name)
    assigned: dict[str, str] = {}
    for child in ast.walk(node):
        if isinstance(child, ast.Assign) and len(child.targets) == 1 and isinstance(child.targets[0], ast.Name):
            if key := env_key(child.value):
                assigned[child.targets[0].id] = key
    for branch in (child for child in ast.walk(node) if isinstance(child, ast.If)):
        keys = {key for child in ast.walk(branch.test) if (key := env_key(child))}
        names = {child.id for child in ast.walk(branch.test) if isinstance(child, ast.Name)}
        keys.update(assigned[name] for name in names if name in assigned)
        if not keys:
            continue
        targets = {resolved(name, bindings) for statement in (*branch.body, *branch.orelse)
                   for child in ast.walk(statement) if isinstance(child, ast.Call)
                   if (name := dotted(child.func))}
        if any(target.startswith(("app.versioning.resolver.", "app.versioning.shadow_reads.")) for target in targets):
            return True
    return False


def source_findings(source: str, path: str) -> set[tuple[str, str]]:
    findings: set[tuple[str, str]] = set()
    facts_set = source_facts(source, path)
    latest_functions = {facts.name for facts in facts_set if has_latest_sql(facts.source)}
    for facts in facts_set:
        resolver = facts.calls & RESOLVER_CALLS
        shadow_targets = {target for target in facts.targets if target.startswith("app.versioning.shadow_reads.")}
        semantic_shadow = bool(SHADOW_TERMS.search(facts.source))
        fallback = any(FALLBACK_TERMS.search(call) for call in facts.calls)
        if any(SHADOW_TERMS.search(key) and VERSION_TERMS.search(key) for key in facts.env_keys):
            findings.add((facts.name, "runtime_probe_flag"))
        if branch_controls_authority(source, facts.name, path):
            findings.add((facts.name, "alternate_authority_flag"))
        if has_latest_sql(facts.source) and (path, facts.name) not in ALLOWED_LATEST_SQL:
            findings.add((facts.name, "inline_latest_version_sql"))
        if facts.calls & latest_functions and (path, facts.name) not in ALLOWED_LATEST_SQL:
            findings.add((facts.name, "resolve_time_preferred_latest_fallback"))
        if facts.appends_file and (semantic_shadow or resolver):
            findings.add((facts.name, "shadow_append_writer"))
        if resolver and semantic_shadow:
            findings.add((facts.name, "shadow_resolver_execution"))
        if resolver and fallback:
            findings.add((facts.name, "resolve_time_preferred_latest_fallback"))
        if resolver and (path, facts.name) not in ALLOWED_RESOLVER_CALLERS:
            findings.add((facts.name, "unexpected_resolver_execution_bridge"))
        if shadow_targets and (path, facts.name) not in ALLOWED_SHADOW_CALLERS:
            findings.add((facts.name, "unexpected_shadow_execution_bridge"))
        if resolver and len(facts.args & {"aluno_id", "turma_id", "matriz_id"}) > 1:
            findings.add((facts.name, "generic_resolver_dispatch"))
    return findings


def explicit_exports(source: str) -> set[str]:
    result = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets) and isinstance(node.value, (ast.List, ast.Tuple)):
            result.update(value for item in node.value.elts if (value := constant(item)) is not None)
    return result


def _module_path(name: str, sources: dict[str, str]) -> str | None:
    plain = name.replace(".", "/") + ".py"
    package = name.replace(".", "/") + "/__init__.py"
    return plain if plain in sources else package if package in sources else None


def _callable_owner(
    path: str,
    name: str,
    sources: dict[str, str],
    definitions: dict[str, set[str]],
    seen: set[tuple[str, str]] | None = None,
) -> tuple[str, str] | None:
    seen = set() if seen is None else seen
    if (path, name) in seen:
        return None
    seen.add((path, name))
    if name in definitions.get(path, set()):
        return path, name
    source = sources.get(path)
    if source is None:
        return None
    target = imports(ast.parse(source), path).get(name)
    if not target or "." not in target:
        return None
    owner_name, callable_name = target.rsplit(".", 1)
    owner_path = _module_path(owner_name, sources)
    return _callable_owner(owner_path, callable_name, sources, definitions, seen) if owner_path else None


def qualified_calls(
    sources: dict[str, str],
    definitions: dict[str, set[str]] | None = None,
) -> set[tuple[tuple[str, str], tuple[str, str]]]:
    definitions = definitions or {
        path: {facts.name for facts in source_facts(source, path)}
        for path, source in sources.items()
    }
    graph: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    for path, source in sources.items():
        for facts in source_facts(source, path):
            caller = (module_name(path), facts.name)
            for target in facts.targets:
                owner: tuple[str, str] | None = None
                if "." not in target and target in definitions.get(path, set()):
                    owner = path, target
                elif "." in target:
                    owner = _resolved_callable(target, sources, definitions)
                if owner is not None:
                    graph.add((caller, (module_name(owner[0]), owner[1])))
    return graph


def export_findings(sources: dict[str, str]) -> set[tuple[str, str, str]]:
    definitions = {path: {facts.name for facts in source_facts(source, path)} for path, source in sources.items()}
    call_graph = qualified_calls(sources, definitions)
    result = set()
    for path, source in sources.items():
        if not path.startswith("app/versioning/"):
            continue
        for name in explicit_exports(source):
            owner = _callable_owner(path, name, sources, definitions)
            if owner is None:
                continue
            owner_path, callable_name = owner
            exported_symbol = (module_name(owner_path), callable_name)
            active = {
                caller
                for caller, target in call_graph
                if target == exported_symbol
                and not caller[0].startswith("tests.")
                and caller != exported_symbol
            }
            if not active:
                result.add((path, name, "zero_caller_exported_facade"))
    return result


def _resolved_callable(
    target: str,
    sources: dict[str, str],
    definitions: dict[str, set[str]],
) -> tuple[str, str] | None:
    if "." not in target:
        return None
    owner_name, name = target.rsplit(".", 1)
    owner_path = _module_path(owner_name, sources)
    return _callable_owner(owner_path, name, sources, definitions) if owner_path else None


def _authority_callables(
    sources: dict[str, str],
    definitions: dict[str, set[str]],
) -> set[tuple[str, str]]:
    result = {
        (path, name)
        for path in ("app/versioning/resolver.py", "app/versioning/shadow_reads.py")
        for name in definitions.get(path, set())
    }
    result.update(
        (path, facts.name)
        for path, source in sources.items()
        for facts in source_facts(source, path)
        if has_latest_sql(facts.source)
        or (facts.appends_file and bool(SHADOW_TERMS.search(facts.source)))
    )
    return result


def tool_findings(sources: dict[str, str]) -> set[tuple[str, str, str]]:
    result = set()
    definitions = {path: {facts.name for facts in source_facts(source, path)} for path, source in sources.items()}
    authority = _authority_callables(sources, definitions)
    for path, source in sources.items():
        if not path.startswith("tools/") or not path.endswith(".py"):
            continue
        tree = ast.parse(source)
        bindings = imports(tree, path)
        roots = {
            resolved(name, bindings)
            for node in tree.body
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom))
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            if (name := dotted(child.func))
        }
        facts = {item.name: item for item in source_facts(source, path)}
        queue, reached = list(roots), set()
        direct = False
        while queue:
            target = queue.pop()
            if target in reached:
                continue
            reached.add(target)
            if target in facts:
                queue.extend(facts[target].targets)
                continue
            if target.startswith(("app.versioning.resolver.", "app.versioning.shadow_reads.")):
                direct = True
                continue
            owner = _resolved_callable(target, sources, definitions)
            if owner in authority:
                direct = True
        if direct:
            label = ",".join(sorted(roots))
            result.add((path, label, "python_tool_launcher_resurrection"))
            result.add((path, label, "python_tool_direct_authority_execution"))
    return result


def analyze_sources(sources: dict[str, str]) -> set[tuple[str, str, str]]:
    result = {(path, function, category) for path, source in sources.items()
              for function, category in source_findings(source, path)}
    result.update(tool_findings(sources))
    result.update(export_findings(sources))
    return result
