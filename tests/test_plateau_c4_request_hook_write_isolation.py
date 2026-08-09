"""SGAA-EJ Structural Plateau C4 - RED: request-hook write isolation.

RED creation for the supervisor-accepted C4 vNext semantics:

    Request hooks must not perform durable application-state writes to the
    database or the filesystem, and must not perform outbound network /
    provider writes.  The only permitted persistent side effect is
    diagnostic/audit logging through a local logging subsystem that was
    fully configured BEFORE request dispatch.

    Hook code may emit records through preconfigured handlers.  Hook code may
    NOT create/configure/replace/remove handlers, change the logging
    destination, perform direct filesystem mutation, use network-backed
    logging, perform DB/schema bootstrap or persistent normalization, convert
    the database journal mode persistently, or invoke backup/export/upload /
    provider write paths.

This file intentionally does NOT encode the obsolete literal rule that all
diagnostic log writes fail; synchronous RBAC/CSRF audit logging must remain
GREEN characterization.

RED entry split (current HEAD, exact):

    13 FAILED: 4, 5, 6, 7, 8, 9, 10, 12, 13, 17, 19, 21, 23
    23 PASSED: the remaining 23 tests
    0 errors

Isolation contract:
    - the ONLY static main.init_db() call expression is owned by
      ``_bootstrapped_env`` (exactly one; future manifest entry
      ("tests/test_plateau_c4_request_hook_write_isolation.py",
      ("_bootstrapped_env",)));
    - every database and runtime root is a pytest tmp_path;
    - the canonical repository database is never opened;
    - connection tracing patches ``app.db.sqlite3.connect`` BEFORE
      ``get_db_connection()`` returns;
    - no xfail / skip / expected-error decorators;
    - no network usage (network analysis is purely static).

Failure classes encoded by the RED set:

    F1  request-path access bootstrap (ensure_usuario_access_schema) executes
        write-class SQL during request hooks;
    F2  request-path message-table lazy ensure (mensagens_editaveis) executes
        write-class SQL during request hooks;
    F4  request connections persistently convert journal_mode to WAL;
    detector/static gates  hooks statically reach write-class SQL, filesystem
        mutation and network/provider writes.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import inspect
import logging
import os
import re
import sqlite3
import textwrap
import types
from pathlib import Path

import pytest

import main
import app.db as app_db
from app.admin_access import _load_admin_access_context
from app.auth import (
    DEFAULT_ACCESS_PASSWORDS,
    canonicalize_access_level,
    default_access_level_for_user_type,
)
from app.web import authz_gate, errors
from app.web.authz_gate import enforce_admin_access_control
from app.web.context import (
    inject_admin_access_helpers,
    inject_editable_message_templates,
)
from utils import messages as message_utils

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ═══════════════════════════════════════════════════════════════════════
# C4 write-class SQL classifier (used by every SQL gate in this file)
# ═══════════════════════════════════════════════════════════════════════

_WRITE_FIRST_KEYWORDS = {
    "create",
    "alter",
    "drop",
    "insert",
    "update",
    "delete",
    "replace",
    "begin",
    "commit",
    "rollback",
    "savepoint",
    "release",
    "vacuum",
    "reindex",
    "attach",
    "detach",
    "analyze",
}

_PERSISTENT_PRAGMAS = {
    "user_version",
    "journal_mode",
    "journal_size_limit",
    "wal_autocheckpoint",
    "application_id",
}

_PERSISTENT_PRAGMA_RE = re.compile(r"pragma\s+([a-z_0-9]+)")


def _strip_sql_comments(sql: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", str(sql), flags=re.DOTALL)
    text = re.sub(r"--[^\n]*", " ", text)
    return text


def _is_write_class_sql(sql: str) -> bool:
    """C4 write-class classification for a single SQL statement.

    Write-class covers durable application-state writes: DDL, DML,
    transaction control and persistent PRAGMAs.  Connection-local PRAGMAs
    (foreign_keys, synchronous) are NOT write-class: they are per-connection
    settings, not durable application state.  ``journal_mode`` and
    ``user_version`` ARE write-class because they persist in the database
    header (F4).
    """
    text = _strip_sql_comments(sql)
    text = re.sub(r"\s+", " ", text.strip().lower())
    if not text:
        return False
    if text.startswith("explain"):
        return False
    first = text.split(" ", 1)[0].rstrip(";")
    if first in _WRITE_FIRST_KEYWORDS:
        return True
    if first == "pragma":
        match = _PERSISTENT_PRAGMA_RE.match(text)
        return bool(match and match.group(1) in _PERSISTENT_PRAGMAS)
    return False


def _normalized_sql(text: str) -> str:
    return re.sub(r"\s+", "", _strip_sql_comments(text).upper())


# ═══════════════════════════════════════════════════════════════════════
# Group A corpora - drawn verbatim from the live bootstrap sources
# ═══════════════════════════════════════════════════════════════════════

_ACCESS_BOOTSTRAP_SQL = (
    "SAVEPOINT ensure_usuario_access_schema",
    "PRAGMA table_info(usuarios)",
    (
        "CREATE TABLE IF NOT EXISTS configuracoes_acesso "
        "(nivel_acesso TEXT PRIMARY KEY, senha_padrao TEXT NOT NULL)"
    ),
    (
        "CREATE TABLE IF NOT EXISTS usuarios_permissoes_acesso "
        "(usuario_id INTEGER NOT NULL, recurso TEXT NOT NULL, escopo TEXT NOT NULL, "
        "PRIMARY KEY (usuario_id, recurso), "
        "FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE ON UPDATE CASCADE)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_usuarios_permissoes_usuario ON usuarios_permissoes_acesso(usuario_id)",
) + ("INSERT OR IGNORE INTO configuracoes_acesso (nivel_acesso, senha_padrao) VALUES (?, ?)",) * 5 + (
    "UPDATE usuarios SET nivel_acesso = ? WHERE tipo = 'admin' AND (nivel_acesso IS NULL OR TRIM(nivel_acesso) = '')",
    "UPDATE usuarios SET nivel_acesso = ? WHERE tipo = 'aluno' AND (nivel_acesso IS NULL OR TRIM(nivel_acesso) = '')",
    "UPDATE usuarios SET nivel_acesso = ? WHERE tipo = 'aluno' AND LOWER(TRIM(COALESCE(nivel_acesso, ''))) = 'administrativo'",
    "RELEASE SAVEPOINT ensure_usuario_access_schema",
)

_MESSAGE_BOOTSTRAP_SQL = (
    "CREATE TABLE IF NOT EXISTS {MESSAGE_TABLE_NAME} "
    "(chave TEXT PRIMARY KEY, texto TEXT NOT NULL, "
    "atualizado_em TEXT NOT NULL DEFAULT (datetime('now')))",
)

_WRITE_CLASS_POSITIVE_FORMS = (
    "CREATE TABLE x (id INTEGER)",
    "ALTER TABLE x ADD COLUMN y INTEGER",
    "DROP TABLE x",
    "INSERT INTO x (a) VALUES (1)",
    "INSERT OR IGNORE INTO x (a) VALUES (1)",
    "UPDATE x SET a = 1",
    "DELETE FROM x",
    "REPLACE INTO x (a) VALUES (1)",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "ROLLBACK TO SAVEPOINT sp",
    "SAVEPOINT sp",
    "RELEASE SAVEPOINT sp",
    "VACUUM",
    "REINDEX",
    "ATTACH DATABASE 'x.db' AS other",
    "PRAGMA user_version = 4",
)

_WRITE_CLASS_NEGATIVE_FORMS = (
    "SELECT * FROM x",
    "SELECT 1",
    "EXPLAIN SELECT * FROM x",
    "EXPLAIN QUERY PLAN SELECT * FROM x",
    "PRAGMA table_info(x)",
    "PRAGMA foreign_keys = ON",
    "PRAGMA synchronous = NORMAL",
)


# ═══════════════════════════════════════════════════════════════════════
# SQL connection tracing (patches app.db.sqlite3.connect, not the returned
# connection)
# ═══════════════════════════════════════════════════════════════════════


class _TracingConnection:
    def __init__(self, raw_connection, sink):
        object.__setattr__(self, "_raw", raw_connection)
        object.__setattr__(self, "_sink", sink)

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def __setattr__(self, name, value):
        setattr(self._raw, name, value)

    def execute(self, sql, params=None):
        self._sink.append(str(sql))
        if params is None:
            return self._raw.execute(sql)
        return self._raw.execute(sql, params)

    def executemany(self, sql, sequence):
        self._sink.append(str(sql))
        return self._raw.executemany(sql, sequence)

    def executescript(self, sql):
        self._sink.append(str(sql))
        return self._raw.executescript(sql)


@contextlib.contextmanager
def _sql_tracing():
    sink = []
    original_connect = app_db.sqlite3.connect

    def traced_connect(*args, **kwargs):
        return _TracingConnection(original_connect(*args, **kwargs), sink)

    app_db.sqlite3.connect = traced_connect
    try:
        yield sink
    finally:
        app_db.sqlite3.connect = original_connect


def _traced_dispatch(client, method, path, **kwargs):
    with _sql_tracing() as sink:
        response = getattr(client, method.lower())(path, **kwargs)
    return response, sink


# ═══════════════════════════════════════════════════════════════════════
# Live hook registration + static reachability closure
# ═══════════════════════════════════════════════════════════════════════


def _audited_hooks():
    app = main.app
    hooks = []
    hooks.extend(app.before_request_funcs.get(None, ()))
    hooks.extend(app.after_request_funcs.get(None, ()))
    hooks.extend(app.template_context_processors.get(None, ()))
    for spec in app.error_handler_spec.values():
        for entry in (spec or {}).values():
            if isinstance(entry, dict):
                hooks.extend(fn for fn in entry.values() if fn is not None)
            elif entry is not None:
                hooks.append(entry)
    hooks.extend(app.teardown_request_funcs.get(None, ()))
    hooks.extend(app.teardown_appcontext_funcs)
    return hooks


def _hook_categories():
    app = main.app
    error_handlers = []
    for spec in app.error_handler_spec.values():
        for entry in (spec or {}).values():
            if isinstance(entry, dict):
                error_handlers.extend(fn for fn in entry.values() if fn is not None)
            elif entry is not None:
                error_handlers.append(entry)
    return {
        "before_request": list(app.before_request_funcs.get(None, ())),
        "after_request": list(app.after_request_funcs.get(None, ())),
        "context_processor": list(app.template_context_processors.get(None, ())),
        "errorhandler": error_handlers,
        "teardown_request": list(app.teardown_request_funcs.get(None, ())),
        "teardown_appcontext": list(app.teardown_appcontext_funcs),
    }


_AUDITED_HOOK_SNAPSHOT = frozenset(
    (fn.__name__, fn.__module__) for fn in _audited_hooks()
)


def _is_project_owned(fn) -> bool:
    try:
        srcfile = inspect.getsourcefile(fn)
    except TypeError:
        return False
    if not srcfile:
        return False
    return Path(srcfile).resolve().is_relative_to(PROJECT_ROOT.resolve())


def _reachable_functions(hooks, max_depth=10):
    seen = set()
    ordered = []

    def walk(fn, depth):
        if depth > max_depth or fn in seen or not _is_project_owned(fn):
            return
        try:
            source = inspect.getsource(fn)
        except (TypeError, OSError):
            return
        seen.add(fn)
        ordered.append(fn)
        try:
            tree = ast.parse(textwrap.dedent(source), filename="<closure>")
        except (SyntaxError, IndentationError):
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                target = fn.__globals__.get(node.func.id)
                if inspect.isfunction(target):
                    walk(target, depth + 1)

    for hook in hooks:
        walk(hook, 0)
    return ordered


def _closure_members():
    members = []
    for fn in _reachable_functions(_audited_hooks()):
        source = textwrap.dedent(inspect.getsource(fn))
        members.append((fn.__qualname__, ast.parse(source, filename="<closure>")))
    return members


def _sql_literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return None


def _sql_execute_statements(tree):
    statements = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"execute", "executemany", "executescript"}
        ):
            continue
        if not node.args:
            continue
        text = _sql_literal(node.args[0])
        if text:
            statements.append(text)
    return statements


# ═══════════════════════════════════════════════════════════════════════
# Filesystem mutation detector (Group G)
# ═══════════════════════════════════════════════════════════════════════

_PATH_MUTATING_METHODS = {
    "write_text",
    "write_bytes",
    "mkdir",
    "unlink",
    "touch",
    "rename",
    "replace",
}

_OS_MUTATING_METHODS = {
    "remove",
    "rename",
    "replace",
    "makedirs",
    "mkdir",
    "unlink",
    "truncate",
}

_SHUTIL_MUTATING_METHODS = {
    "copy",
    "copy2",
    "copyfile",
    "copytree",
    "move",
    "rmtree",
    "make_archive",
}

_TEMPFILE_MUTATING_NAMES = {"NamedTemporaryFile"}

_OPEN_WRITE_CHARS = "wax+"


def _fs_mutation_matches(tree):
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            mode_node = None
            if len(node.args) >= 2:
                mode_node = node.args[1]
            else:
                mode_node = next(
                    (kw.value for kw in node.keywords if kw.arg == "mode"), None
                )
            if (
                isinstance(mode_node, ast.Constant)
                and isinstance(mode_node.value, str)
                and any(ch in mode_node.value for ch in _OPEN_WRITE_CHARS)
            ):
                hits.append(f"open(mode={mode_node.value!r})")
            continue
        if not isinstance(func, ast.Attribute):
            continue
        chain = []
        current = func
        while isinstance(current, ast.Attribute):
            chain.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            chain.append(current.id)
        elif isinstance(current, ast.Call):
            inner = current.func
            if isinstance(inner, ast.Name):
                chain.append(inner.id)
        if not chain:
            continue
        chain = list(reversed(chain))
        base, method = chain[0], chain[-1]
        if base == "os" and method in _OS_MUTATING_METHODS:
            hits.append(method)
        elif base == "shutil" and method in _SHUTIL_MUTATING_METHODS:
            hits.append(method)
        elif base == "tempfile" and method in _TEMPFILE_MUTATING_NAMES:
            hits.append(method)
        elif base == "Path" and method in _PATH_MUTATING_METHODS:
            hits.append(method)
    return hits


_FS_POSITIVE_SNIPPETS = {
    "open_write": "open('x', 'w')",
    "open_append": "open('x', 'a')",
    "open_create": "open('x', 'x')",
    "open_update": "open('x', 'r+')",
    "open_write_binary": "open('x', 'wb')",
    "open_append_binary": "open('x', 'ab')",
    "path_write_text": "Path('x').write_text('t')",
    "path_write_bytes": "Path('x').write_bytes(b't')",
    "path_mkdir": "Path('x').mkdir()",
    "path_unlink": "Path('x').unlink()",
    "path_touch": "Path('x').touch()",
    "path_rename": "Path('x').rename('y')",
    "path_replace": "Path('x').replace('y')",
    "os_remove": "os.remove('x')",
    "os_rename": "os.rename('x', 'y')",
    "os_replace": "os.replace('x', 'y')",
    "os_makedirs": "os.makedirs('x')",
    "os_mkdir": "os.mkdir('x')",
    "os_unlink": "os.unlink('x')",
    "os_truncate": "os.truncate('x', 0)",
    "shutil_copy": "shutil.copy('x', 'y')",
    "shutil_copy2": "shutil.copy2('x', 'y')",
    "shutil_copyfile": "shutil.copyfile('x', 'y')",
    "shutil_copytree": "shutil.copytree('x', 'y')",
    "shutil_move": "shutil.move('x', 'y')",
    "shutil_rmtree": "shutil.rmtree('x')",
    "shutil_make_archive": "shutil.make_archive('a', 'zip', 'x')",
    "named_temp_file": "tempfile.NamedTemporaryFile()",
}

_FS_NEGATIVE_SNIPPETS = (
    "open('x', 'r')",
    "open('x', 'rb')",
    "Path('x').read_text()",
    "Path('x').read_bytes()",
    "Path('x').exists()",
    "Path('x').stat()",
    "os.walk('x')",
    "os.listdir('x')",
)


# ═══════════════════════════════════════════════════════════════════════
# Network / provider-write detector (Group I)
# ═══════════════════════════════════════════════════════════════════════

_NETWORK_MODULE_PREFIXES = (
    "urllib.request",
    "urllib3",
    "requests",
    "socket",
    "http.client",
    "httpx",
    "smtplib",
)

_CLOUD_WRITE_NAMES = {
    "upload_zip_backup",
    "upload_zip_backup_with_access_token",
    "upload_snapshot_to_external_server",
    "maybe_sync_database_to_cloud",
    "_maybe_upload_to_drives",
    "_upload_snapshot_if_external_enabled",
    "run_backup_cycle",
}


def _network_or_provider_matches(tree):
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            chain = []
            current = func
            while isinstance(current, ast.Attribute):
                chain.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                chain.append(current.id)
            dotted = ".".join(reversed(chain))
            if any(dotted.startswith(prefix) for prefix in _NETWORK_MODULE_PREFIXES):
                hits.append(dotted)
            elif func.attr in _CLOUD_WRITE_NAMES:
                hits.append(dotted)
        elif isinstance(func, ast.Name) and func.id in _CLOUD_WRITE_NAMES:
            hits.append(func.id)
    return hits


_NETWORK_POSITIVE_SNIPPETS = (
    "urllib.request.urlopen('http://example.invalid')",
    "urllib.request.urlretrieve('http://example.invalid', 'x')",
    "requests.post('http://example.invalid', json={})",
    "requests.get('http://example.invalid')",
    "socket.socket()",
    "socket.create_connection(('example.invalid', 443))",
    "http.client.HTTPConnection('example.invalid')",
    "http.client.HTTPSConnection('example.invalid')",
    "httpx.Client()",
    "httpx.post('http://example.invalid')",
    "smtplib.SMTP('mail.example.invalid')",
    "upload_zip_backup('backup.zip')",
    "upload_zip_backup_with_access_token('backup.zip', 'token')",
    "upload_snapshot_to_external_server('backup.zip')",
    "maybe_sync_database_to_cloud()",
    "_maybe_upload_to_drives()",
    "_upload_snapshot_if_external_enabled()",
    "orchestrator.run_backup_cycle()",
)

_NETWORK_NEGATIVE_SNIPPETS = (
    "main.app.test_client()",
    "jsonify(ok=True)",
    "print('x')",
    "session.get('user_type')",
    "render_template('index.html')",
)


# ═══════════════════════════════════════════════════════════════════════
# Logging handler-construction detector (Group H)
# ═══════════════════════════════════════════════════════════════════════

_LOGGING_HANDLER_APIS = {
    "FileHandler",
    "RotatingFileHandler",
    "StreamHandler",
    "NullHandler",
    "SocketHandler",
    "DatagramHandler",
    "SMTPHandler",
    "HTTPHandler",
    "SysLogHandler",
    "NTEventLogHandler",
    "QueueHandler",
    "QueueListener",
    "addHandler",
    "removeHandler",
    "basicConfig",
    "dictConfig",
    "fileConfig",
}


def _logging_handler_construction_matches(tree):
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else (func.id if isinstance(func, ast.Name) else "")
        )
        if name in _LOGGING_HANDLER_APIS:
            hits.append(name)
    return hits


# ═══════════════════════════════════════════════════════════════════════
# F4 outcome snapshot / detector
# ═══════════════════════════════════════════════════════════════════════


def _snapshot_database_outcome(path):
    path = Path(path)
    if not path.exists():
        return {"exists": False}
    data = path.read_bytes()
    outcome = {
        "exists": True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "header_journal_mode": (data[18], data[19]) if len(data) >= 100 else None,
    }
    conn = sqlite3.connect(str(path))
    try:
        conn.row_factory = sqlite3.Row
        outcome["user_version"] = conn.execute("PRAGMA user_version").fetchone()[0]
        try:
            outcome["schema_migrations"] = tuple(
                tuple(row)
                for row in conn.execute(
                    "SELECT version, name FROM schema_migrations ORDER BY version"
                )
            )
        except sqlite3.OperationalError:
            outcome["schema_migrations"] = None
        try:
            outcome["sqlite_master"] = tuple(
                sorted(
                    tuple(row)
                    for row in conn.execute(
                        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
                    )
                )
            )
        except sqlite3.OperationalError:
            outcome["sqlite_master"] = None
        row_counts = {}
        for table in (
            "configuracoes_acesso",
            "usuarios_permissoes_acesso",
            "mensagens_editaveis",
        ):
            try:
                row_counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                row_counts[table] = None
        outcome["row_counts"] = row_counts
    finally:
        conn.close()
    outcome["sidecars"] = tuple(
        sorted(path.name + suffix for suffix in ("-wal", "-shm", "-journal"))
        if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
        else ()
    )
    return outcome


def _outcome_delta(before, after):
    keys = sorted(set(before) | set(after))
    return [key for key in keys if before.get(key) != after.get(key)]


def _assert_outcome_unchanged(before, after, label="database outcome"):
    delta = _outcome_delta(before, after)
    assert not delta, f"{label} changed after readonly dispatch: {delta}"


# ═══════════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════════


def _header_journal_mode(path):
    with open(path, "rb") as handle:
        data = handle.read(32)
    return (data[18], data[19])


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _journal_mode_of(path):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()


def _login(client, user_id, level):
    with client.session_transaction() as session:
        session.clear()
        session["user_id"] = user_id
        session["user_type"] = "admin"
        session["user_name"] = "C4 Red Admin"
        session["access_level"] = level


def _set_admin_db_level(env, level):
    with main.app.app_context():
        conn = app_db.get_db_connection()
        conn.execute(
            "UPDATE usuarios SET nivel_acesso = ? WHERE id = ?",
            (level, env.admin_id),
        )
        conn.commit()
        main.close_db_connection(None)


def _function_source_text(relative_path, name):
    path = PROJECT_ROOT / relative_path
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    matches = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1, f"expected exactly one {name} in {path}"
    return ast.get_source_segment(source, matches[0])


def _audited_loggers():
    return [
        logging.getLogger("main"),
        logging.getLogger("app"),
        logging.getLogger("flask.app"),
        logging.getLogger(),
    ]


def _canonical_log_path():
    for handler in logging.getLogger("main").handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    raise AssertionError("main logger has no FileHandler configured")


def _flush_file_handlers():
    for logger in _audited_loggers():
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.flush()


def _runtime_tree(root):
    root = Path(root)
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.stat().st_size
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def _bootstrapped_env(tmp_path, monkeypatch):
    runtime_root = tmp_path
    db_path = runtime_root / "app.db"
    log_dir = runtime_root / "logs"
    log_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(app_db, "DATABASE", str(db_path))
    monkeypatch.setattr(main, "DATABASE", str(db_path))
    monkeypatch.setitem(main.app.config, "DATABASE_PATH", str(db_path))
    with main.app.app_context():
        main.close_db_connection(None)
        main.init_db()
    with main.app.app_context():
        conn = app_db.get_db_connection()
        admin = conn.execute(
            "SELECT id FROM usuarios WHERE tipo = 'admin' ORDER BY id LIMIT 1"
        ).fetchone()
        admin_id = int(admin["id"])
        main.close_db_connection(None)
    yield types.SimpleNamespace(
        app=main.app,
        client=main.app.test_client(),
        db_path=db_path,
        runtime_root=runtime_root,
        log_dir=log_dir,
        admin_id=admin_id,
    )
    with main.app.app_context():
        main.close_db_connection(None)


def _register_probe_rule(rule, endpoint, view):
    main.app.url_map.add(rule)
    main.app.view_functions[endpoint] = view


def _unregister_probe_rule(rule, endpoint):
    main.app.view_functions.pop(endpoint, None)
    main.app.url_map._rules.remove(rule)
    main.app.url_map._rules_by_endpoint.pop(endpoint, None)
    main.app.url_map.update()


# ═══════════════════════════════════════════════════════════════════════
# GROUP A - SQL classifier self-proof (3 GREEN)
# ═══════════════════════════════════════════════════════════════════════


def test_write_class_classifier_flags_every_ddl_dml_and_transaction_form():
    variants = (
        lambda sql: sql,
        lambda sql: sql.lower(),
        lambda sql: "   " + sql,
        lambda sql: "-- comment\n" + sql,
        lambda sql: "/* comment */ " + sql,
    )
    for form in _WRITE_CLASS_POSITIVE_FORMS:
        for variant in variants:
            assert _is_write_class_sql(variant(form)), (
                f"classifier failed to flag write-class form {form!r} in variant {variant(form)!r}"
            )
    for form in _WRITE_CLASS_NEGATIVE_FORMS:
        assert not _is_write_class_sql(form), (
            f"classifier flagged read-only form {form!r} as write-class"
        )


def test_classifier_is_not_vacuous_against_the_live_access_bootstrap():
    source = (PROJECT_ROOT / "app" / "db_maintenance.py").read_text(
        encoding="utf-8-sig"
    )
    normalized_source = _normalized_sql(source)
    for statement in set(_ACCESS_BOOTSTRAP_SQL):
        assert _normalized_sql(statement) in normalized_source, (
            f"corpus statement not present in the live access bootstrap: {statement!r}"
        )
    assert len(_ACCESS_BOOTSTRAP_SQL) == 14
    assert sum(_is_write_class_sql(statement) for statement in _ACCESS_BOOTSTRAP_SQL) == 13


def test_classifier_is_not_vacuous_against_the_live_message_bootstrap():
    source = (PROJECT_ROOT / "utils" / "messages.py").read_text(
        encoding="utf-8-sig"
    )
    normalized_source = _normalized_sql(source)
    for statement in set(_MESSAGE_BOOTSTRAP_SQL):
        assert _normalized_sql(statement) in normalized_source, (
            f"corpus statement not present in the live message bootstrap: {statement!r}"
        )
    assert len(_MESSAGE_BOOTSTRAP_SQL) == 1
    assert sum(_is_write_class_sql(statement) for statement in _MESSAGE_BOOTSTRAP_SQL) == 1


# ═══════════════════════════════════════════════════════════════════════
# GROUP B - hook DB read-only (6 RED)
# ═══════════════════════════════════════════════════════════════════════


def test_before_request_gate_executes_zero_write_class_sql_on_allow(_bootstrapped_env):
    """RED (F1): the allow path still runs the request-time access ensure
    (approximately 26 write-class statements from the access bootstrap path,
    plus journal_mode and the message-table lazy ensure)."""
    env = _bootstrapped_env
    _set_admin_db_level(env, "admin_total")
    _login(env.client, env.admin_id, "admin_total")
    response, traced = _traced_dispatch(env.client, "get", "/admin/alunos")
    assert response.status_code == 200
    write_class = [statement for statement in traced if _is_write_class_sql(statement)]
    assert write_class == [], (
        f"before_request allow dispatch executed {len(write_class)} write-class "
        f"statements (F1 access ensure path): {[s[:60] for s in write_class[:8]]}"
    )


def test_before_request_gate_executes_zero_write_class_sql_on_deny(_bootstrapped_env):
    """RED (F1+F2): the deny gate path still runs the access ensure and the
    message-table lazy ensure (approximately 27 write-class statements)."""
    env = _bootstrapped_env
    _set_admin_db_level(env, "consultivo")
    from flask import session

    with main.app.test_request_context("/admin/banco-dados"):
        session["user_id"] = env.admin_id
        session["user_type"] = "admin"
        session["access_level"] = "consultivo"
        with _sql_tracing() as traced:
            outcome = enforce_admin_access_control()
    assert outcome is not None
    assert outcome.status_code == 302
    write_class = [statement for statement in traced if _is_write_class_sql(statement)]
    assert write_class == [], (
        f"before_request deny gate executed {len(write_class)} write-class statements "
        f"(F1 access ensure + F2 message-table lazy ensure): "
        f"{[s[:60] for s in write_class[:8]]}"
    )


def test_admin_access_context_processor_executes_zero_write_class_sql(_bootstrapped_env):
    """RED (F1): the cold-g access context processor still runs the request-time
    access ensure (27 write-class statements measured)."""
    env = _bootstrapped_env
    from flask import session

    with main.app.test_request_context("/admin/alunos"):
        session["user_type"] = "admin"
        session["user_id"] = env.admin_id
        with _sql_tracing() as traced:
            inject_admin_access_helpers()
    write_class = [statement for statement in traced if _is_write_class_sql(statement)]
    assert write_class == [], (
        f"admin_access context processor executed {len(write_class)} write-class "
        f"statements on cold-g (F1 access ensure path): "
        f"{[s[:60] for s in write_class[:8]]}"
    )


def test_editable_message_context_processor_executes_zero_write_class_sql(_bootstrapped_env):
    """RED (F2): the editable-message context processor still lazily ensures the
    mensagens_editaveis table (CREATE TABLE IF NOT EXISTS)."""
    env = _bootstrapped_env
    with main.app.test_request_context("/admin/alunos"):
        with _sql_tracing() as traced:
            inject_editable_message_templates()
    write_class = [statement for statement in traced if _is_write_class_sql(statement)]
    assert write_class == [], (
        f"editable-message context processor executed {len(write_class)} write-class "
        f"statements (F2 CREATE TABLE IF NOT EXISTS mensagens_editaveis): "
        f"{[s[:60] for s in write_class[:8]]}"
    )


def test_error_handlers_execute_zero_write_class_sql(_bootstrapped_env):
    """RED (F1/F2): the 413/404 error-handler paths still run the cold-g access
    ensure and the message-table lazy ensure.  Diagnostic logging itself is NOT
    a failure under C4 vNext; the failure is the write-class SQL."""
    env = _bootstrapped_env
    _login(env.client, env.admin_id, "admin_total")
    response, traced_404 = _traced_dispatch(
        env.client, "get", "/definitely-not-a-route-c4-red", follow_redirects=False
    )
    assert response.status_code == 404
    response, traced_413 = _traced_dispatch(
        env.client, "post", "/login", data={"payload": "x" * (17 * 1024 * 1024)}
    )
    assert response.status_code == 302
    combined = traced_404 + traced_413
    write_class = [statement for statement in combined if _is_write_class_sql(statement)]
    assert write_class == [], (
        f"error-handler dispatch executed {len(write_class)} write-class statements "
        f"(F1 cold-g access ensure / F2 message-table lazy ensure): "
        f"{[s[:60] for s in write_class[:8]]}"
    )


def test_full_denial_dispatch_emits_zero_write_class_sql(_bootstrapped_env):
    """RED (F1+F2): a full denied admin dispatch in which the protected view is
    never entered still mutates the database through request-hook behavior."""
    env = _bootstrapped_env
    _set_admin_db_level(env, "consultivo")
    _login(env.client, env.admin_id, "consultivo")
    response, traced = _traced_dispatch(
        env.client, "get", "/admin/banco-dados", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/admin/dashboard")
    write_class = [statement for statement in traced if _is_write_class_sql(statement)]
    assert write_class == [], (
        f"full denial dispatch executed {len(write_class)} write-class statements "
        f"attributable to request-hook behavior (protected view not entered): "
        f"{[s[:60] for s in write_class[:8]]}"
    )


# ═══════════════════════════════════════════════════════════════════════
# GROUP C - F1/F2 bootstrap ownership (3 RED + 1 GREEN)
# ═══════════════════════════════════════════════════════════════════════


def test_init_db_creates_message_overrides_table_on_fresh_database(_bootstrapped_env):
    """RED (F2): init_db does not own the message-table bootstrap; the table is
    still absent after init_db on a fresh database."""
    env = _bootstrapped_env
    with main.app.app_context():
        conn = app_db.get_db_connection()
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mensagens_editaveis'"
        ).fetchone()
        main.close_db_connection(None)
    assert table is not None, (
        "init_db did not create mensagens_editaveis on a fresh database; "
        "message-table bootstrap is not owned by init_db (F2)"
    )


def test_init_db_creates_access_schema_and_defaults_on_fresh_database(_bootstrapped_env):
    env = _bootstrapped_env
    with main.app.app_context():
        conn = app_db.get_db_connection()
        names = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('configuracoes_acesso', 'usuarios_permissoes_acesso') "
                "ORDER BY name"
            )
        ]
        assert names == ["configuracoes_acesso", "usuarios_permissoes_acesso"]
        rows = conn.execute(
            "SELECT nivel_acesso FROM configuracoes_acesso ORDER BY nivel_acesso"
        ).fetchall()
        levels = [row["nivel_acesso"] for row in rows]
        assert len(levels) == 5
        assert set(levels) == set(DEFAULT_ACCESS_PASSWORDS)
        admin = conn.execute(
            "SELECT nivel_acesso FROM usuarios WHERE id = ?", (env.admin_id,)
        ).fetchone()
        assert admin["nivel_acesso"] == "admin_total"
        columns = [
            row["name"] for row in conn.execute("PRAGMA table_info(usuarios)")
        ]
        assert "nivel_acesso" in columns
        main.close_db_connection(None)


def test_init_db_repairs_legacy_database_missing_access_and_message_artifacts(tmp_path, request):
    """RED (F2): on a legitimate legacy fixture, init_db repairs the access
    artifacts but the missing message-bootstrap ownership remains, so the
    mensagens_editaveis table is still absent."""
    db_path = tmp_path / "app.db"
    raw = sqlite3.connect(str(db_path))
    raw.execute(
        "CREATE TABLE usuarios ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "nome TEXT NOT NULL, "
        "email TEXT UNIQUE NOT NULL, "
        "senha TEXT NOT NULL, "
        "tipo TEXT NOT NULL"
        ")"
    )
    raw.commit()
    raw.close()
    env = request.getfixturevalue("_bootstrapped_env")
    assert env.db_path == db_path
    with main.app.app_context():
        conn = app_db.get_db_connection()
        access = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'configuracoes_acesso'"
        ).fetchone()
        assert access is not None
        count = conn.execute("SELECT COUNT(*) FROM configuracoes_acesso").fetchone()[0]
        assert count == 5
        permissions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'usuarios_permissoes_acesso'"
        ).fetchone()
        assert permissions is not None
        message_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mensagens_editaveis'"
        ).fetchone()
        main.close_db_connection(None)
    assert message_table is not None, (
        "init_db repaired access artifacts on the legacy database but did NOT "
        "bootstrap mensagens_editaveis; the failure is specifically the missing "
        "message-bootstrap ownership (F2)"
    )


def test_request_path_does_not_repair_a_deliberately_stale_database(_bootstrapped_env):
    """RED (F1): the request path still performs persistent repair of a
    deliberately stale database (access defaults re-seeded)."""
    env = _bootstrapped_env
    with main.app.app_context():
        conn = app_db.get_db_connection()
        conn.execute("DELETE FROM configuracoes_acesso")
        conn.execute(
            "UPDATE usuarios SET nivel_acesso = 'lixo' WHERE id = ?", (env.admin_id,)
        )
        conn.commit()
        main.close_db_connection(None)
    _login(env.client, env.admin_id, "lixo")
    env.client.get("/admin/alunos")
    with main.app.app_context():
        conn = app_db.get_db_connection()
        level = conn.execute(
            "SELECT nivel_acesso FROM usuarios WHERE id = ?", (env.admin_id,)
        ).fetchone()["nivel_acesso"]
        count = conn.execute("SELECT COUNT(*) FROM configuracoes_acesso").fetchone()[0]
        main.close_db_connection(None)
    assert level == "lixo"
    assert count == 0, (
        f"request path persistently repaired deliberately stale configuracoes_acesso "
        f"(re-seeded {count} rows); C4 requires bootstrap ownership in init_db with "
        "no request-time persistent repair (F1)"
    )


# ═══════════════════════════════════════════════════════════════════════
# GROUP D - behavior preservation (3 GREEN)
# ═══════════════════════════════════════════════════════════════════════


def test_rbac_allow_and_deny_results_unchanged_after_bootstrap(_bootstrapped_env):
    env = _bootstrapped_env
    _set_admin_db_level(env, "admin_total")
    _login(env.client, env.admin_id, "admin_total")
    assert env.client.get("/admin/alunos").status_code == 200
    _set_admin_db_level(env, "consultivo")
    _login(env.client, env.admin_id, "consultivo")
    response = env.client.get("/admin/banco-dados", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/admin/dashboard")
    ajax = env.client.get(
        "/admin/banco-dados", headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert ajax.status_code == 403
    assert ajax.get_json()["error"] == "forbidden"


def test_stale_access_level_resolves_identically_without_request_time_normalization(_bootstrapped_env):
    env = _bootstrapped_env
    fallback = default_access_level_for_user_type("admin")
    for raw in (None, "", "lixo"):
        assert canonicalize_access_level(raw, fallback) == "admin_total"
    with main.app.app_context():
        conn = app_db.get_db_connection()
        for raw in ("", "lixo"):
            conn.execute(
                "UPDATE usuarios SET nivel_acesso = ? WHERE id = ?", (raw, env.admin_id)
            )
            context = _load_admin_access_context(conn, env.admin_id)
            assert context["access_level"] == "admin_total"
        main.close_db_connection(None)


def test_message_override_lookup_and_save_remain_functional_after_bootstrap(_bootstrapped_env):
    env = _bootstrapped_env
    with main.app.app_context():
        conn = app_db.get_db_connection()
        message_utils.ensure_message_overrides_schema(conn)
        entries = message_utils.list_editable_messages(conn)
        entry = next(
            item
            for item in entries
            if any(kind in item["kinds"] for kind in ("alert", "confirm", "toast"))
        )
        key = entry["key"]
        default_text = entry["default_text"]
        override_text = default_text + " [C4-OVERRIDE]"
        message_utils.save_message_override(conn, key, override_text)
        assert message_utils.resolve_user_message(default_text, conn=conn) == override_text
        templates = message_utils.frontend_message_templates(conn)
        assert templates.get(default_text) == override_text
        message_utils.reset_message_override(conn, key)
        assert message_utils.resolve_user_message(default_text, conn=conn) == default_text
        main.close_db_connection(None)


# ═══════════════════════════════════════════════════════════════════════
# GROUP E - static reachability + live hook set (1 RED + 1 GREEN)
# ═══════════════════════════════════════════════════════════════════════


def test_no_registered_request_hook_reaches_write_class_sql_statically():
    """RED: the live hook closure statically reaches write-class SQL through
    the request-time access ensure, the connection pragmas and the
    message-table lazy ensure.  The root set derives from live registration."""
    hits = []
    for qualname, tree in _closure_members():
        for statement in _sql_execute_statements(tree):
            if _is_write_class_sql(statement):
                hits.append((qualname, " ".join(statement.split())[:90]))
    assert hits == [], (
        f"registered request hooks statically reach {len(hits)} write-class SQL "
        f"statements: {hits[:12]}"
    )


def test_criterion_four_audited_hook_set_equals_live_registration():
    live = frozenset((fn.__name__, fn.__module__) for fn in _audited_hooks())
    assert live == _AUDITED_HOOK_SNAPSHOT
    assert live, "audited hook set must not be empty"
    required = {
        ("enforce_admin_access_control", "app.web.authz_gate"),
        ("inject_admin_access_helpers", "app.web.context"),
        ("inject_editable_message_templates", "app.web.context"),
        ("not_found", "app.web.errors"),
        ("internal_error", "app.web.errors"),
        ("handle_large_upload", "app.web.errors"),
        ("_handle_csrf_error", "app"),
        ("_apply_security_headers", "app"),
        ("close_db_connection", "app.db"),
    }
    assert required <= live, required - live
    categories = _hook_categories()
    assert set(categories) == {
        "before_request",
        "after_request",
        "context_processor",
        "errorhandler",
        "teardown_request",
        "teardown_appcontext",
    }
    for category, functions in categories.items():
        for fn in functions:
            assert (fn.__name__, fn.__module__) in live, (
                f"hook {fn.__name__} from category {category} escaped the audited set"
            )


# ═══════════════════════════════════════════════════════════════════════
# GROUP F - F4 connection-state neutrality (2 RED + 5 GREEN)
# ═══════════════════════════════════════════════════════════════════════


def test_request_connection_does_not_convert_journal_mode_on_a_non_wal_database(_bootstrapped_env):
    """RED (F4): a request connection currently converts a non-WAL database to
    WAL - header (1,1) -> (2,2) and a persistent SHA change."""
    env = _bootstrapped_env
    db = env.db_path
    with main.app.app_context():
        main.close_db_connection(None)
    raw = sqlite3.connect(str(db))
    raw.execute("PRAGMA journal_mode = DELETE")
    raw.close()
    with main.app.app_context():
        main.close_db_connection(None)
    before_header = _header_journal_mode(db)
    before_sha = _sha256_file(db)
    assert before_header == (1, 1)
    _login(env.client, env.admin_id, "admin_total")
    env.client.get("/admin/alunos")
    with main.app.app_context():
        main.close_db_connection(None)
    assert not Path(str(db) + "-wal").exists()
    assert not Path(str(db) + "-shm").exists()
    after_header = _header_journal_mode(db)
    after_sha = _sha256_file(db)
    assert after_header == before_header, (
        f"request connection converted journal mode on a non-WAL database: "
        f"header {before_header} -> {after_header} (F4)"
    )
    assert after_sha == before_sha, (
        "request connection persisted database bytes (journal-mode conversion) "
        "on a non-WAL database (F4)"
    )


def test_init_db_establishes_wal_on_a_non_wal_database(tmp_path, request):
    db_path = tmp_path / "app.db"
    raw = sqlite3.connect(str(db_path))
    raw.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
    raw.execute("PRAGMA journal_mode = DELETE")
    raw.commit()
    raw.close()
    before_header = _header_journal_mode(db_path)
    assert before_header == (1, 1)
    env = request.getfixturevalue("_bootstrapped_env")
    assert env.db_path == db_path
    assert _header_journal_mode(env.db_path) == (2, 2)
    assert _journal_mode_of(env.db_path) == "wal"


def test_get_db_connection_owns_only_connection_local_pragmas_and_init_db_owns_journal_mode():
    """RED (F4): journal_mode is still set inside get_db_connection and not
    explicitly inside init_db."""
    get_connection_source = _function_source_text("app/db.py", "get_db_connection")
    init_db_source = _function_source_text("app/db.py", "init_db")
    assert "PRAGMA foreign_keys" in get_connection_source
    assert "PRAGMA synchronous" in get_connection_source
    assert "PRAGMA journal_mode" not in get_connection_source, (
        "journal_mode must be owned by init_db, not by get_db_connection (F4)"
    )
    assert "PRAGMA journal_mode" in init_db_source, (
        "init_db does not explicitly establish journal_mode (F4)"
    )


def test_pragma_persistence_classification_matches_measured_behavior(tmp_path):
    db = tmp_path / "pragma.db"
    first = sqlite3.connect(str(db))
    first.execute("PRAGMA foreign_keys = ON")
    first.execute("PRAGMA synchronous = NORMAL")
    first.execute("PRAGMA journal_mode = WAL")
    first.close()
    second = sqlite3.connect(str(db))
    foreign_keys = second.execute("PRAGMA foreign_keys").fetchone()[0]
    synchronous = second.execute("PRAGMA synchronous").fetchone()[0]
    journal_mode = second.execute("PRAGMA journal_mode").fetchone()[0]
    second.close()
    assert foreign_keys == 0
    assert synchronous == 2
    assert journal_mode == "wal"
    assert _is_write_class_sql("PRAGMA journal_mode = WAL") is True
    assert _is_write_class_sql("PRAGMA foreign_keys = ON") is False
    assert _is_write_class_sql("PRAGMA synchronous = NORMAL") is False


def test_readonly_hook_dispatch_leaves_database_outcome_unchanged(_bootstrapped_env):
    """RED (F1/F2): the readonly dispatch currently produces a persistent state
    delta (mensagens_editaveis table + sqlite_master + size + SHA)."""
    env = _bootstrapped_env
    with main.app.app_context():
        main.close_db_connection(None)
    before = _snapshot_database_outcome(env.db_path)
    assert before["exists"] is True
    _set_admin_db_level(env, "admin_total")
    _login(env.client, env.admin_id, "admin_total")
    response = env.client.get("/admin/alunos")
    assert response.status_code == 200
    with main.app.app_context():
        main.close_db_connection(None)
    after = _snapshot_database_outcome(env.db_path)
    _assert_outcome_unchanged(
        before,
        after,
        label=f"database outcome ({env.db_path})",
    )


def test_database_outcome_rule_is_not_vacuous_against_deliberate_journal_mode_conversion(tmp_path):
    db = tmp_path / "convert.db"
    raw = sqlite3.connect(str(db))
    raw.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
    raw.execute("PRAGMA journal_mode = DELETE")
    raw.commit()
    raw.close()
    before = _snapshot_database_outcome(db)
    raw = sqlite3.connect(str(db))
    raw.execute("PRAGMA journal_mode = WAL")
    raw.close()
    after = _snapshot_database_outcome(db)
    delta = _outcome_delta(before, after)
    assert "header_journal_mode" in delta, delta
    with pytest.raises(AssertionError):
        _assert_outcome_unchanged(before, after)


def test_request_connection_against_missing_database_is_detected_as_persistent_artifact(tmp_path):
    """Detector-positive characterization: a request connection against a
    missing database creates the database file; the outcome detector flags the
    missing -> present transition as a persistent artifact.  This is a
    detector characterization, not permission for request bootstrap."""
    db = tmp_path / "missing.db"
    before = _snapshot_database_outcome(db)
    assert before["exists"] is False
    raw = sqlite3.connect(str(db))
    raw.close()
    after = _snapshot_database_outcome(db)
    assert after["exists"] is True
    assert _outcome_delta(before, after)
    with pytest.raises(AssertionError):
        _assert_outcome_unchanged(before, after)


# ═══════════════════════════════════════════════════════════════════════
# GROUP G - filesystem application-state writes (3 GREEN)
# ═══════════════════════════════════════════════════════════════════════


def test_filesystem_write_detector_flags_mutating_apis():
    for label, snippet in _FS_POSITIVE_SNIPPETS.items():
        assert _fs_mutation_matches(ast.parse(snippet)), f"detector missed {label}: {snippet}"
    for snippet in _FS_NEGATIVE_SNIPPETS:
        assert _fs_mutation_matches(ast.parse(snippet)) == [], f"false positive: {snippet}"


def test_no_registered_hook_reaches_direct_filesystem_application_state_mutation():
    """Diagnostic logging through preconfigured handlers is NOT a direct
    application-state filesystem API for this test."""
    hits = []
    for qualname, tree in _closure_members():
        for hit in _fs_mutation_matches(tree):
            hits.append((qualname, hit))
    assert hits == [], f"registered request hooks reach filesystem mutation: {hits}"


def test_full_denial_dispatch_creates_no_file_outside_authorized_diagnostic_log(_bootstrapped_env):
    env = _bootstrapped_env
    _set_admin_db_level(env, "consultivo")
    _login(env.client, env.admin_id, "consultivo")
    log_dir = Path(_canonical_log_path()).parent
    runtime_before = _runtime_tree(env.runtime_root)
    log_before = _runtime_tree(log_dir)
    response = env.client.get("/admin/banco-dados", follow_redirects=False)
    assert response.status_code == 302
    _flush_file_handlers()
    runtime_after = _runtime_tree(env.runtime_root)
    log_after = _runtime_tree(log_dir)
    runtime_delta = set(runtime_after) - set(runtime_before)
    log_delta = set(log_after) - set(log_before)
    assert runtime_delta == set(), (
        f"denial dispatch created files outside the authorized diagnostic log: {runtime_delta}"
    )
    assert log_delta <= {"app.log", "app.log.1"}, (
        f"denial dispatch created unexpected log artifacts: {log_delta}"
    )


# ═══════════════════════════════════════════════════════════════════════
# GROUP H - logging allowance boundary (7 GREEN)
# ═══════════════════════════════════════════════════════════════════════


def test_hook_closure_does_not_instantiate_or_configure_logging_handlers():
    hits = []
    for qualname, tree in _closure_members():
        for hit in _logging_handler_construction_matches(tree):
            hits.append((qualname, hit))
    assert hits == [], (
        f"registered request hooks instantiate/configure logging handlers: {hits}"
    )
    assert authz_gate.logger is logging.getLogger("main")
    assert errors.logger is logging.getLogger("main")
    assert any(
        isinstance(handler, logging.FileHandler)
        for handler in logging.getLogger("main").handlers
    )


def test_handler_identities_and_destinations_unchanged_after_representative_dispatches(_bootstrapped_env):
    env = _bootstrapped_env
    from werkzeug.routing import Rule

    csrf_rule = Rule("/admin/c4-csrf-probe-30", endpoint="admin_c4_csrf_probe_30", methods={"POST"})
    _register_probe_rule(csrf_rule, "admin_c4_csrf_probe_30", lambda: ("ok", 200))

    def snapshot():
        entries = []
        for logger in _audited_loggers():
            for handler in logger.handlers:
                destination = getattr(handler, "baseFilename", None)
                entries.append(
                    (
                        logger.name,
                        id(handler),
                        type(handler).__name__,
                        str(Path(destination).resolve()) if destination else None,
                    )
                )
        return sorted(entries)

    before = snapshot()
    try:
        _set_admin_db_level(env, "consultivo")
        _login(env.client, env.admin_id, "consultivo")
        response = env.client.get("/admin/banco-dados", follow_redirects=False)
        assert response.status_code == 302
        assert snapshot() == before
        response = env.client.get("/definitely-not-a-route-c4-30")
        assert response.status_code == 404
        assert snapshot() == before
        response = env.client.post(
            "/login", data={"payload": "x" * (17 * 1024 * 1024)}
        )
        assert response.status_code == 302
        assert snapshot() == before
        env.app.config["WTF_CSRF_ENABLED"] = True
        try:
            with env.client.session_transaction() as session:
                session.clear()
            response = env.client.post("/admin/c4-csrf-probe-30", data={"x": "1"})
            assert response.status_code == 400
        finally:
            env.app.config["WTF_CSRF_ENABLED"] = False
        assert snapshot() == before
    finally:
        _unregister_probe_rule(csrf_rule, "admin_c4_csrf_probe_30")


def test_hook_reachable_logging_resolves_only_to_preconfigured_local_sinks_under_app_log_dir(_bootstrapped_env):
    env = _bootstrapped_env
    log_dir = Path(os.environ["APP_LOG_DIR"]).resolve()
    file_destinations = []
    for logger in _audited_loggers():
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                file_destinations.append(Path(handler.baseFilename).resolve())
    assert file_destinations, "no local file sink configured"
    for destination in file_destinations:
        assert destination.is_relative_to(log_dir), (
            f"file sink {destination} is outside APP_LOG_DIR {log_dir}"
        )
    from werkzeug.routing import Rule

    csrf_rule = Rule("/admin/c4-csrf-probe-31", endpoint="admin_c4_csrf_probe_31", methods={"POST"})
    _register_probe_rule(csrf_rule, "admin_c4_csrf_probe_31", lambda: ("ok", 200))
    try:
        env.app.config["WTF_CSRF_ENABLED"] = True
        try:
            with env.client.session_transaction() as session:
                session.clear()
            response = env.client.post("/admin/c4-csrf-probe-31", data={"x": "1"})
            assert response.status_code == 400
        finally:
            env.app.config["WTF_CSRF_ENABLED"] = False
        _flush_file_handlers()
        canonical_log = _canonical_log_path()
        text = canonical_log.read_text(encoding="utf-8", errors="replace")
        assert "CSRFError method=POST" in text
        assert canonical_log.resolve().is_relative_to(log_dir)
    finally:
        _unregister_probe_rule(csrf_rule, "admin_c4_csrf_probe_31")


def test_synthetic_hook_local_handler_construction_is_rejected_by_detector():
    positives = (
        "logging.FileHandler('app.log')",
        "logging.handlers.RotatingFileHandler('app.log', maxBytes=1, backupCount=1)",
        "logger.addHandler(h)",
        "logging.basicConfig(filename='app.log')",
        "logging.config.dictConfig({'handlers': {}})",
        "logging.getLogger('main').addHandler(logging.NullHandler())",
    )
    for snippet in positives:
        assert _logging_handler_construction_matches(ast.parse(snippet)), snippet
    negatives = (
        "logger.error('message')",
        "logger.exception('boom')",
        "logger.warning('attention')",
        "logger.info('notice')",
    )
    for snippet in negatives:
        assert _logging_handler_construction_matches(ast.parse(snippet)) == [], snippet


def test_network_backed_logging_handlers_are_rejected_and_absent_from_live_chains():
    positives = (
        "logging.handlers.SMTPHandler('mail.example.com', 'from@x', ['to@x'], 'subject')",
        "logging.handlers.HTTPHandler('localhost', '/log', 'POST')",
        "logging.handlers.SysLogHandler(address=('localhost', 514))",
        "logging.handlers.SocketHandler('localhost', 9020)",
        "logging.handlers.DatagramHandler('localhost', 9021)",
    )
    for snippet in positives:
        assert _logging_handler_construction_matches(ast.parse(snippet)), snippet
    for qualname, tree in _closure_members():
        assert _logging_handler_construction_matches(tree) == [], qualname
    remote_types = (
        logging.handlers.SMTPHandler,
        logging.handlers.HTTPHandler,
        logging.handlers.SysLogHandler,
        logging.handlers.SocketHandler,
        logging.handlers.DatagramHandler,
        logging.handlers.NTEventLogHandler,
    )
    for logger in _audited_loggers():
        for handler in logger.handlers:
            assert not isinstance(handler, remote_types), (logger.name, type(handler).__name__)
    assert any(
        isinstance(handler, logging.FileHandler)
        for logger in _audited_loggers()
        for handler in logger.handlers
    )


def test_synchronous_rbac_and_csrf_audit_logging_present_in_canonical_log(_bootstrapped_env, monkeypatch):
    """End-to-end synchronous audit-logging preservation: the RBAC
    missing-configuration shadow audit and the CSRF diagnostic are present in
    the canonical local log immediately after dispatch.  No sleep, no queue,
    no listener."""
    env = _bootstrapped_env
    from werkzeug.routing import Rule

    audit_rule = Rule(
        "/admin/c4-shadow-audit-probe",
        endpoint="admin_c4_shadow_audit_probe",
        methods={"GET"},
    )
    csrf_rule = Rule(
        "/admin/c4-csrf-probe-34",
        endpoint="admin_c4_csrf_probe_34",
        methods={"POST"},
    )
    _register_probe_rule(audit_rule, "admin_c4_shadow_audit_probe", lambda: ("ok", 200))
    _register_probe_rule(csrf_rule, "admin_c4_csrf_probe_34", lambda: ("ok", 200))
    canonical_log = _canonical_log_path()
    try:
        monkeypatch.setitem(main.app.config, "IS_PRODUCTION", True)
        _login(env.client, env.admin_id, "consultivo")
        response = env.client.get("/admin/c4-shadow-audit-probe")
        assert response.status_code == 200
        env.app.config["WTF_CSRF_ENABLED"] = True
        try:
            with env.client.session_transaction() as session:
                session.clear()
            response = env.client.post("/admin/c4-csrf-probe-34", data={"x": "1"})
            assert response.status_code == 400
        finally:
            env.app.config["WTF_CSRF_ENABLED"] = False
        _flush_file_handlers()
        text = canonical_log.read_text(encoding="utf-8", errors="replace")
        assert "event=admin_rbac_missing_configuration" in text, (
            "RBAC missing-configuration shadow audit not present in the canonical "
            "local log after dispatch"
        )
        assert "CSRFError method=POST" in text, (
            "CSRF diagnostic not present in the canonical local log after dispatch"
        )
    finally:
        _unregister_probe_rule(audit_rule, "admin_c4_shadow_audit_probe")
        _unregister_probe_rule(csrf_rule, "admin_c4_csrf_probe_34")


def test_duplicate_500_logging_characterized_as_future_hardening_out_of_scope(_bootstrapped_env):
    """The current duplicate-500 logging behavior is characterized as
    FUTURE_HARDENING / OUT_OF_SCOPE for C4.  This test is GREEN at entry and
    must NOT require a remediation: it asserts the 500 status and that the
    traceback reached the canonical local log at least once.  At entry the
    marker appears multiple times because the traceback is duplicated across
    the app and flask channels; the duplication itself is deliberately out of
    scope and is NOT encoded as a C4 RED."""
    env = _bootstrapped_env
    from werkzeug.routing import Rule

    marker = "C4-500-PROBE-MARKER"
    probe_rule = Rule(
        "/admin/c4-500-probe",
        endpoint="admin_c4_500_probe",
        methods={"GET"},
    )
    _register_probe_rule(probe_rule, "admin_c4_500_probe", lambda: (_ for _ in ()).throw(RuntimeError(marker)))
    canonical_log = _canonical_log_path()
    try:
        response = env.client.get("/admin/c4-500-probe")
        assert response.status_code == 500
        _flush_file_handlers()
        text = canonical_log.read_text(encoding="utf-8", errors="replace")
        assert "Erro interno do servidor" in text
        assert text.count(marker) >= 1
    finally:
        _unregister_probe_rule(probe_rule, "admin_c4_500_probe")


# ═══════════════════════════════════════════════════════════════════════
# GROUP I - network (1 GREEN)
# ═══════════════════════════════════════════════════════════════════════


def test_no_registered_hook_reaches_network_or_provider_write():
    """Static gate: no live-registered request hook reaches network or
    provider write paths.  A positive synthetic reachability control keeps the
    detector honest (no vacuous pass)."""
    hits = []
    for qualname, tree in _closure_members():
        for hit in _network_or_provider_matches(tree):
            hits.append((qualname, hit))
    assert hits == [], (
        f"registered request hooks reach network/provider write paths: {hits}"
    )
    for snippet in _NETWORK_POSITIVE_SNIPPETS:
        assert _network_or_provider_matches(ast.parse(snippet)), f"detector missed: {snippet}"
    for snippet in _NETWORK_NEGATIVE_SNIPPETS:
        assert _network_or_provider_matches(ast.parse(snippet)) == [], (
            f"network detector false positive: {snippet}"
        )
