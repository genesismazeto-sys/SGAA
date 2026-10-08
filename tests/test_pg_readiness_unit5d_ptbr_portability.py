# coding: utf-8
"""PostgreSQL-readiness Unit 5-D: PTBR / NOCASE / technical-LIKE portability.

U5-B left the human-text surfaces SQLite-only on purpose.  On PostgreSQL every
one of them is a hard error today:

* ``<expr> COLLATE PTBR_NOACCENT`` (40 ORDER BY terms, 8 view modules) -- the
  collation exists only as a SQLite ``create_collation`` registration;
* ``INSTR(PTBR_FOLD(<expr>), ?) > 0`` (``app/web/filters.py``) -- neither
  ``instr`` nor ``ptbr_fold`` exists on PostgreSQL;
* ``<expr> COLLATE NOCASE`` (5 terms, ``admin_atividades``);
* technical-token ``LIKE ?`` -- SQLite LIKE is ASCII case-insensitive with no
  escape character; PostgreSQL LIKE is case-sensitive and treats ``\\`` as the
  default escape (a pattern ending in ``\\`` raises SQLSTATE 22025).

This module is the U5-D contract.  It is written RED-first: the RED cases fail
against published production (``091ba4b``) because the U5-D owners do not
exist yet; the GREEN controls prove the oracle, the legacy SQLite semantics and
the test support itself are discriminating, so a RED failure cannot be an
artifact of collection or of the harness.

Ratified decisions reflected here:

* D-1 -- ``sgaa_human_text_key`` is provisioned by the U5-A schema authority
  (helper statement + contract digest), the validator requires
  ``server_encoding = UTF8``; no table/column/constraint/index/version change
  and no ``unaccent`` (the U5-A current-state authority digest is pinned).
* D-2 -- the PostgreSQL fold reproduces ``app.text.human_text_key`` from a
  frozen mapping that records its Unicode version; drift fails loudly, the data
  is a literal (never regenerated at import), and it is re-derivable.
* D-3 -- the inventoried technical LIKE sites keep SQLite semantics on
  PostgreSQL (ASCII-only case folding, no escape character).
* D-4 -- after U5-D the migrated view/query surfaces carry no raw
  ``COLLATE PTBR_*`` / ``PTBR_FOLD(`` / ``INSTR(`` / ``COLLATE NOCASE``.  The
  U5-B/U5-C boundary pins that deferred U5-D are NOT touched by this RED; they
  are adjudicated during implementation.
* D-5 -- every dialect-sensitive helper receives the caller-owned connection
  explicitly; the engine is derived from that connection, never from Flask
  request state, ``get_db_connection()`` or the ambient backend.
* D-6 -- plain/default-collation ordering of technical fields (``LOWER(u.email)``,
  ``t.codigo``, ``grupo`` as a plain term ...) is OUT of U5-D and remains
  recorded portability debt F-1; nothing here migrates or pins it.

Evidence classes (TEP §4): the PostgreSQL-shaped cases below are NOT
PostgreSQL proof.  The test-local double rejects the SQLite-only tokens exactly
where PostgreSQL would, and emulates only engine-independent PostgreSQL
builtins (``strpos``, ``chr``, ``translate``, UTF-8 ``lower``/``upper``,
PostgreSQL ``LIKE`` escape semantics, the ``"C"`` collation = code-point
order) plus the D-2 helper *as its oracle*.  PostgreSQL ORDER BY is modelled as
its documented defaults (ASC NULLS LAST, DESC NULLS FIRST) over code-point
comparison.  No locale collation is simulated.  Real semantics are the gated
E-PG1 section at the end (``SGAA_PG_TEST_URL``); without it they skip and the
unit records REAL-PG EVIDENCE: ABSENT.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import html as html_module
import importlib
import inspect
import json
import os
import re
import secrets
import sqlite3
import textwrap
import types
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

import main  # noqa: F401  (canonical runtime; conftest redirects APP_DATABASE)
from app import db as app_db
from app import pg_schema, sql_dialect
from app.text import human_text_key, register_human_text_sql
from app.web import filters as web_filters
from tests.canonical_request_test_support import login_admin
from tests.pg_shaped_support import PostgresShapedConnection
from tests.versioned_test_support import isolated_versioned_app_env

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# U5-D contract names.  This table is the ONLY place the test fixes production
# names; a rename during implementation edits this table and is recorded.
# ---------------------------------------------------------------------------

DIALECT_OWNERS = {
    "human_order": "human_text_order",
    "human_contains": "human_text_contains",
    "nocase_order": "ascii_nocase_order",
    "technical_like": "ascii_ci_like",
}
FILTER_HELPERS = (
    "human_text_contains_sql",
    "append_human_text_contains_condition",
    "append_text_contains_condition",
)
CONNECTION_PARAMETER_NAMES = ("connection", "conn")
PG_HELPER_FUNCTION = "sgaa_human_text_key"
PG_REQUIRED_SERVER_ENCODING = "UTF8"
FOLD_OWNER_MODULE = "app.human_text_fold"
#: unicodedata version the inventory derived the fold tables from (Python 3.12.10).
FROZEN_UNICODE_VERSION = "15.0.0"

#: The U5-A helpers that existed before U5-D (must survive unchanged).
U5A_HELPERS = (
    "sgaa_utcnow_text",
    "sgaa_datetime_text_valid",
    "sgaa_json_is_valid",
    "sgaa_json_is_object",
)
#: sha256 of the U5-A current-state contract sections at 091ba4b (everything in
#: ``pg_contract_payload()`` except ``helpers``).  D-1 forbids table, column,
#: constraint, index, trigger, seed and version changes.
U5A_CURRENT_STATE_KEYS = (
    "epoch",
    "version",
    "business_rule_sqlstate",
    "tables",
    "indexes",
    "triggers",
    "schema_meta",
    "schema_migrations_baseline",
)
U5A_CURRENT_STATE_SHA256 = "dc66f9b0b4c20eaa45d922f657bd4d3972ccea57e0515fa2494356fb6cab2866"
#: Later, separately authorized schema units whose additive delta is removed
#: before the U5-A digest is recomputed: STORAGE S1 (prod-1/v13) added exactly
#: these three image tables and baseline row 13, and moved the version to 13;
#: STORAGE S2 (prod-1/v14) added the three canonical-storage tables, one
#: nullable ``storage_object_id`` column + FK on each business file table, the
#: nullable ``cloud_accounts.provider_account_key`` column + CHECK, seven
#: indexes, six triggers and baseline row 14; STORAGE S3-A (prod-1/v15) added
#: the canonical ``supabase`` provider to the ``admin_arquivos`` provider CHECK
#: (restored below to its declared U5-A expression; the custody trigger
#: FUNCTION bodies are not a U5-A section) and baseline row 15.  Everything
#: else in the U5-A sections must still be byte-identical.
LATER_ADDED_TABLES = (
    "usuarios_foto", "alunos_foto", "reportes_captura",
    "storage_objects", "storage_upload_intents", "storage_worker_status",
)
#: ``table: (column, foreign key or None, check or None)``.
LATER_ADDED_COLUMNS = {
    "requisicao_arquivos": ("storage_object_id", "fk_requisicao_arquivos_storage_object_id", None),
    "admin_arquivos": ("storage_object_id", "fk_admin_arquivos_storage_object_id", None),
    "cloud_accounts": ("provider_account_key", None, "ck_cloud_accounts_provider_account_key"),
}
LATER_ADDED_INDEXES = (
    "idx_storage_objects_drive_due", "idx_storage_objects_uploader", "ux_storage_objects_drive_file",
    "idx_storage_upload_intents_state_expires", "ux_req_arquivos_storage_object",
    "ux_admin_arquivos_storage_object", "idx_cloud_accounts_provider_account_key",
)
LATER_ADDED_TRIGGERS = (
    "trg_requisicao_arquivos_storage_object_insert", "trg_requisicao_arquivos_storage_object_update",
    "trg_admin_arquivos_storage_object_insert", "trg_admin_arquivos_storage_object_update",
    "trg_storage_upload_intents_transition", "trg_storage_objects_drive_account_bound",
)
LATER_ADDED_BASELINE_VERSIONS = (13, 14, 15)
#: ``(table, check name): (U5-A expression, later expression)`` -- a later unit's
#: declared change of an existing CHECK, reverted before the digest.
LATER_CHANGED_CHECKS = {
    ("admin_arquivos", "ck_admin_arquivos_provider"): (
        "provider IN ('local_legacy','google')",
        "provider IN ('local_legacy','google','supabase')",
    ),
}
U5A_SCHEMA_VERSION = 12

# ---------------------------------------------------------------------------
# Inventoried call-site expressions (read-only inventory at 091ba4b).  The
# owners must accept exactly-validated application expressions; if GREEN
# restructures a call site, this inventory is updated with the justification.
# ---------------------------------------------------------------------------

HUMAN_ORDER_EXPRESSIONS = (
    "COALESCE(u.nome, '')",
    "LOWER(COALESCE(titulo, mensagem))",
    "COALESCE(c.nome, '')",
    "COALESCE(a.matricula, '')",
    "COALESCE(u.email, '')",
    "COALESCE(t.codigo, t.nome, '')",
    "COALESCE(a.status, '')",
    "COALESCE(tm.nome, '')",
    "COALESCE(nome, '')",
    "COALESCE(m.nome, '')",
    "COALESCE(a.nome, '')",
    "LOWER(rep.titulo)",
    "titulo",
    "descricao",
    "nome",
    "b.nome_conceito",
    "a.nome",
    "aluno_nome",
)
HUMAN_CONTAINS_EXPRESSIONS = (
    "u.nome",
    "titulo",
    "mensagem",
    "COALESCE(titulo, mensagem)",
    "c.nome",
    "tm.nome",
    "nome",
    "m.nome",
    "rep.titulo",
    "rep.descricao",
    "a.nome",
    "descricao",
)
NOCASE_EXPRESSIONS = ("tipo_atividade", "grupo")
TECHNICAL_LIKE_EXPRESSIONS = (
    "u.email",
    "a.matricula",
    "c.codigo",
    "t.codigo",
    "original_filename",
    "COALESCE(a.matricula, '')",
    "COALESCE(t.codigo, t.nome, '')",
)
FAMILY_EXPRESSIONS = {
    "human_order": HUMAN_ORDER_EXPRESSIONS,
    "human_contains": HUMAN_CONTAINS_EXPRESSIONS,
    "nocase_order": NOCASE_EXPRESSIONS,
    "technical_like": TECHNICAL_LIKE_EXPRESSIONS,
}

HOSTILE_EXPRESSIONS = (
    "",
    " ",
    "?",
    "u.nome) OR (1=1",
    "u.nome; DROP TABLE usuarios",
    "u.nome -- comment",
    "(SELECT senha FROM usuarios LIMIT 1)",
    "u.nome COLLATE PTBR_NOACCENT",
    "PTBR_FOLD(u.nome)",
    "u.nome' || '",
    " u.nome",
    "u.nome ",
)

#: View/query surfaces U5-D migrates (D-4 ratchet).  ``app/sql_dialect.py`` is
#: the sole owner allowed to spell the SQLite fragments.
MIGRATED_SURFACES = (
    "app/views/admin/acesso.py",
    "app/views/admin/alertas.py",
    "app/views/admin/alunos_turmas_cursos.py",
    "app/views/admin/arquivos.py",
    "app/views/admin/atividades.py",
    "app/views/admin/matrizes.py",
    "app/views/admin/reportes.py",
    "app/views/admin/requisicoes.py",
    "app/web/filters.py",
)

#: SQLite-only human-text tokens.  PostgreSQL rejects each one (42704/42883).
SQLITE_ONLY_TOKENS = (
    ("COLLATE PTBR_*", re.compile(r"COLLATE\s+\"?PTBR_\w+", re.IGNORECASE)),
    ("PTBR_FOLD(", re.compile(r"\bPTBR_FOLD\s*\(", re.IGNORECASE)),
    ("INSTR(", re.compile(r"\bINSTR\s*\(", re.IGNORECASE)),
    ("COLLATE NOCASE", re.compile(r"COLLATE\s+\"?NOCASE\b", re.IGNORECASE)),
)

_COLLATE_C_RE = re.compile(r'COLLATE\s+"C"')
_LOCALE_CASE_FUNCTION_RE = re.compile(r"\b(?:lower|upper|initcap)\s*\(", re.IGNORECASE)
_ILIKE_RE = re.compile(r"\bILIKE\b", re.IGNORECASE)
_LIKE_RE = re.compile(r"\bLIKE\b", re.IGNORECASE)
_ESCAPE_EMPTY_RE = re.compile(r"\bESCAPE\s+''", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Fixtures of the semantic contract (expected values are the observed SQLite
# behaviour at 091ba4b, pinned by the GREEN controls below).
# ---------------------------------------------------------------------------

#: (input, folded key) -- app.text.human_text_key is the oracle.
ORACLE_KEYS = (
    ("Á", "a"),
    ("á", "a"),
    ("A", "a"),
    ("Ç", "c"),
    ("São", "sao"),
    ("SÃO", "sao"),
    ("Sao", "sao"),
    ("AÇÃO", "acao"),
    ("Éverto", "everto"),
    ("  Maria \t  Silva ", "maria silva"),
    ("Maria-Silva", "maria-silva"),
    ("Maria_Silva", "maria_silva"),
    ("O'Neil", "o'neil"),
    ("1º Período", "1o periodo"),
    ("2ª", "2a"),
    ("ﬁo", "fio"),
    ("Ｆｕｌｌ", "full"),
    ("a b", "a b"),
    ("x y", "x y"),
    ("Weiß", "weiss"),
    ("Øyvind", "øyvind"),
    ("İstanbul", "istanbul"),
    ("é", "e"),
    ("́", ""),
    ("", ""),
    (None, ""),
)

#: Insertion order matters: the empty string precedes NULL so a fragment that
#: collapses NULL into '' (tie broken by id) cannot reproduce SQLite NULL-first.
ORDER_FIXTURE = (
    "",
    None,
    "  ",
    "Éverto",
    "everto",
    "EVERTO",
    "Felipe",
    "Wandrew",
    "ana maria",
    "anabela",
    "a_b",
    "a1",
    "a~",
    "Øyvind",
    "oz",
    "Zé",
    "zeta",
    "Ana",
    "ÁNA",
)
EXPECTED_HUMAN_ORDER = {
    ("a.nome", "ASC"): [
        None, "", "  ", "a1", "a_b", "Ana", "ÁNA", "ana maria", "anabela", "a~",
        "Éverto", "everto", "EVERTO", "Felipe", "oz", "Wandrew", "Zé", "zeta", "Øyvind",
    ],
    ("a.nome", "DESC"): [
        "Øyvind", "zeta", "Zé", "Wandrew", "oz", "Felipe", "Éverto", "everto", "EVERTO",
        "a~", "anabela", "ana maria", "Ana", "ÁNA", "a_b", "a1", "", "  ", None,
    ],
    ("COALESCE(a.nome, '')", "ASC"): [
        "", None, "  ", "a1", "a_b", "Ana", "ÁNA", "ana maria", "anabela", "a~",
        "Éverto", "everto", "EVERTO", "Felipe", "oz", "Wandrew", "Zé", "zeta", "Øyvind",
    ],
    ("COALESCE(a.nome, '')", "DESC"): [
        "Øyvind", "zeta", "Zé", "Wandrew", "oz", "Felipe", "Éverto", "everto", "EVERTO",
        "a~", "anabela", "ana maria", "Ana", "ÁNA", "a_b", "a1", "", None, "  ",
    ],
}

#: 'b' before 'B' and 'é' before 'É' by insertion: ASCII-only NOCASE ties b/B
#: (id decides) but keeps É (U+00C9) before é (U+00E9); a Unicode fold would
#: tie É/é and let the id put é first.
NOCASE_FIXTURE = ("b", "B", "a", "é", "É", "Z", "_x", None)
EXPECTED_NOCASE_ORDER = {
    "ASC": [None, "_x", "a", "b", "B", "Z", "É", "é"],
    "DESC": ["é", "É", "Z", "b", "B", "a", "_x", None],
}

#: (haystack, raw user query, SQLite outcome).  Callers bind
#: ``human_text_key(query)``; the q-paths bind it even when it folds to ''.
CONTAINS_CASES = (
    ("São Paulo", "sao", True),
    ("SAO PAULO", "são", True),
    ("Ação Complementar", "ACAO", True),
    ("Éverto Luza", "EVERTO", True),
    ("Weiß", "weiss", True),
    ("Øyvind", "oyvind", False),
    ("Øyvind", "ØYVIND", True),
    ("Maria Silva", "maria   silva", True),
    ("Maria-Silva", "maria silva", False),
    ("100% Ação", "0% aç", True),
    ("abc", "a%c", False),
    ("abc", "a_c", False),
    ("a_c", "a_c", True),
    ("a\\b", "a\\b", True),
    ("ab", "a\\b", False),
    ("ab\\", "b\\", True),
    (None, "a", False),
    (None, "́", True),
    ("qualquer", "́", True),
)

LIKE_VALUES = ("Ana@X.com", "ana@x.com", "ÉVA@x", "éva@x", "a_b", "axb", "a%b", "a\\b", "xa\\", None)
#: Patterns as the callers build them (``%value%``) plus the boundary shapes.
LIKE_PATTERNS = ("%ana@%", "%ANA@%", "%éva%", "%ÉVA%", "a_b", "a%b", "%\\%", "%a\\", "%a\\%", "a\\_b")


# ---------------------------------------------------------------------------
# Test-local PostgreSQL-shaped support
# ---------------------------------------------------------------------------


class PgRejectedSQL(Exception):
    """PostgreSQL would reject this statement (undefined collation/function)."""

    def __init__(self, token, sql):
        super().__init__(f"PostgreSQL rejects {token!r}: {sql[:200]}")
        self.token = token
        self.sql = sql
        self.sqlstate = "42883" if token.endswith("(") else "42704"


class PgInvalidEscapeSequence(Exception):
    """SQLSTATE 22025: LIKE pattern must not end with escape character."""

    sqlstate = "22025"


def _sqlite_only_tokens(sql):
    return [label for label, pattern in SQLITE_ONLY_TOKENS if pattern.search(str(sql))]


class _PgEmulation:
    """Engine-independent PostgreSQL builtins registered on a SQLite engine."""

    def __init__(self):
        self.errors = []

    @staticmethod
    def strpos(haystack, needle):
        if haystack is None or needle is None:
            return None
        return str(haystack).find(str(needle)) + 1

    @staticmethod
    def chr(code):
        return None if code is None else chr(int(code))

    @staticmethod
    def translate(value, source, target):
        if value is None or source is None or target is None:
            return None
        source, target = str(source), str(target)
        mapping = {}
        for index, char in enumerate(source):
            if char not in mapping:
                mapping[char] = target[index] if index < len(target) else ""
        return "".join(mapping.get(char, char) for char in str(value))

    @staticmethod
    def lower(value):
        # PostgreSQL lower() on a UTF8 database with a real locale is Unicode
        # aware ('É' -> 'é'); SQLite's builtin is ASCII-only.
        return None if value is None else str(value).lower()

    @staticmethod
    def upper(value):
        return None if value is None else str(value).upper()

    def like(self, pattern, value, escape="\\"):
        """PostgreSQL LIKE: case-sensitive, default escape '\\'."""
        if pattern is None or value is None or escape is None:
            return None
        pattern, escape = str(pattern), str(escape)
        if len(escape) > 1:
            raise ValueError("invalid escape string")
        parts = []
        index = 0
        while index < len(pattern):
            char = pattern[index]
            if escape and char == escape:
                if index + 1 >= len(pattern):
                    error = PgInvalidEscapeSequence(
                        "LIKE pattern must not end with escape character"
                    )
                    self.errors.append(error)
                    raise error
                parts.append(re.escape(pattern[index + 1]))
                index += 2
                continue
            parts.append(".*" if char == "%" else "." if char == "_" else re.escape(char))
            index += 1
        return 1 if re.fullmatch("".join(parts), str(value), re.DOTALL) else 0

    def install(self, real):
        real.create_function(PG_HELPER_FUNCTION, 1, human_text_key, deterministic=True)
        real.create_function("strpos", 2, self.strpos, deterministic=True)
        real.create_function("chr", 1, self.chr, deterministic=True)
        real.create_function("translate", 3, self.translate, deterministic=True)
        real.create_function("lower", 1, self.lower, deterministic=True)
        real.create_function("upper", 1, self.upper, deterministic=True)
        real.create_function("like", 2, self.like, deterministic=True)
        real.create_function("like", 3, self.like, deterministic=True)
        # PostgreSQL "C" on UTF8 is bytewise == code-point order == Python str.
        real.create_collation("C", lambda a, b: (a > b) - (a < b))


class PgShapedPtbrConnection(PostgresShapedConnection):
    """PG-shaped double that refuses the SQLite-only human-text tokens.

    The real SQLite engine underneath still runs everything else (the U5-B
    PostgreSQL fragments used by the selected routes are SQLite-compatible);
    PostgreSQL catalog probes of the read-only runtime ensure paths are answered
    from ``sqlite_master``.
    """

    def __init__(self, real, *, reject_sqlite_only=True, **kwargs):
        super().__init__(real, **kwargs)
        self.emulation = _PgEmulation()
        self.emulation.install(real)
        self.reject_sqlite_only = reject_sqlite_only
        self.rejected = []
        self.pg_statements = []

    def execute(self, sql, params=None):
        text = str(sql)
        self.pg_statements.append((text, params))
        tokens = _sqlite_only_tokens(text)
        if tokens:
            self.rejected.append((tokens, text))
            if self.reject_sqlite_only:
                self._status = "INERROR"
                raise PgRejectedSQL(tokens[0], text)
        if "pg_catalog.pg_class" in text and "relname" in text:
            self._status = "INTRANS"
            return self._real.execute(
                "SELECT name AS relname FROM sqlite_master WHERE type='table'"
            )
        return super().execute(sql, params)


class _RecordingPgConnection:
    """Minimal psycopg-shaped object: identifies as PostgreSQL, runs nothing."""

    def __init__(self):
        self.info = types.SimpleNamespace(
            transaction_status=types.SimpleNamespace(name="IDLE")
        )
        self.statements = []

    def execute(self, sql, params=None):  # pragma: no cover - never expected
        self.statements.append((sql, params))
        raise AssertionError("a dialect fragment builder must not execute SQL")


def _sqlite_memory():
    conn = sqlite3.connect(":memory:")
    register_human_text_sql(conn)
    return conn


def _pg_memory():
    return PgShapedPtbrConnection(sqlite3.connect(":memory:"))


def _seed_source(conn, values):
    conn.execute("CREATE TABLE src (id INTEGER PRIMARY KEY, v TEXT)")
    for index, value in enumerate(values, start=1):
        conn.execute("INSERT INTO src (id, v) VALUES (?, ?)", (index, value))


def _pg_order(rows, direction):
    """PostgreSQL ORDER BY <key> <direction>, id over ``(id, key)`` rows.

    Documented defaults: ASC NULLS LAST, DESC NULLS FIRST; non-NULL keys under
    ``"C"`` compare by code point (Python ``str``).  The caller-owned ``id``
    tie-break is ascending.
    """
    present = sorted((row for row in rows if row[1] is not None), key=lambda row: row[0])
    present.sort(key=lambda row: row[1], reverse=direction == "DESC")
    nulls = sorted((row for row in rows if row[1] is None), key=lambda row: row[0])
    return present + nulls if direction == "ASC" else nulls + present


# -- contract accessors ------------------------------------------------------


def _owner(family):
    name = DIALECT_OWNERS[family]
    owner = getattr(sql_dialect, name, None)
    assert callable(owner), (
        f"U5-D dialect owner app.sql_dialect.{name} ({family}) does not exist yet"
    )
    return owner


def _connection_parameter(fn):
    signature = inspect.signature(fn)
    found = [p for p in signature.parameters.values() if p.name in CONNECTION_PARAMETER_NAMES]
    assert found, (
        f"{fn.__module__}.{fn.__qualname__} takes no explicit caller-owned "
        f"connection parameter {CONNECTION_PARAMETER_NAMES!r} (D-5)"
    )
    return found[0]


def _invoke(fn, connection, *args):
    """Call ``fn`` passing ``connection`` by name and ``args`` to the remaining
    positional parameters, whatever position the connection parameter takes."""
    conn_param = _connection_parameter(fn)
    others = [
        p
        for p in inspect.signature(fn).parameters.values()
        if p is not conn_param
        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    kwargs = {param.name: value for param, value in zip(others, args)}
    kwargs[conn_param.name] = connection
    return fn(**kwargs)


_AMBIENT_ENGINE_LOOKUPS = (
    re.compile(r"\bget_db_connection\b"),
    re.compile(r"\bflask\b"),
    re.compile(r"\bg\.(?:db|get)\b"),
    re.compile(r"\brequest\b"),
    re.compile(r"\bcurrent_app\b"),
    re.compile(r"\bdatabase_backend\s*\("),
    re.compile(r"\bos\.environ\b"),
    re.compile(r"\bDATABASE_URL\b"),
)


def _ambient_engine_lookups(fn):
    """Names of ambient engine/connection discovery used by ``fn``'s body."""
    try:
        source = inspect.getsource(fn)
    except (OSError, TypeError):
        return ["<source unavailable>"]
    tree = ast.parse(textwrap.dedent(source))
    body = tree.body[0]
    if isinstance(body, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(body):
        body.body = body.body[1:]
    code = ast.unparse(body)
    return [pattern.pattern for pattern in _AMBIENT_ENGINE_LOOKUPS if pattern.search(code)]


def _docstring_nodes(tree):
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    nodes.add(id(body[0].value))
    return nodes


def _raw_token_hits(source, label="<source>"):
    """SQLite-only tokens in executable string literals (docstrings excluded)."""
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    hits = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            for token in _sqlite_only_tokens(node.value):
                hits.append((label, getattr(node, "lineno", 0), token))
    return hits


def _fold_owner():
    try:
        return importlib.import_module(FOLD_OWNER_MODULE)
    except ModuleNotFoundError as exc:
        pytest.fail(f"U5-D frozen fold owner {FOLD_OWNER_MODULE} does not exist yet: {exc}")


def _helper_statement():
    pattern = re.compile(
        rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+{PG_HELPER_FUNCTION}\s*\(", re.IGNORECASE
    )
    matches = [s for s in pg_schema.PG_SCHEMA_STATEMENTS if pattern.search(s)]
    assert len(matches) == 1, (
        f"the U5-A authority must provision exactly one {PG_HELPER_FUNCTION} "
        f"helper statement (D-1); found {len(matches)}"
    )
    return matches[0]


# ===========================================================================
# GREEN controls -- the oracle, legacy SQLite semantics and the test support
# ===========================================================================


@pytest.mark.parametrize(("value", "expected"), ORACLE_KEYS)
def test_control_oracle_human_text_key(value, expected):
    assert human_text_key(value) == expected


def test_control_oracle_discriminations():
    key = human_text_key
    assert key("Á") == key("á") == key("A")
    assert key("São") == key("SÃO") == key("Sao")
    assert key("Øyvind") != key("oyvind")
    assert key("oyvind") not in key("Øyvind")
    assert key("Maria-Silva") != key("Maria Silva")
    assert key("Weiß") == key("WEISS")


@pytest.mark.parametrize(("expression", "direction"), sorted(EXPECTED_HUMAN_ORDER))
def test_control_sqlite_ptbr_order_is_pinned(expression, direction):
    conn = _sqlite_memory()
    try:
        _seed_source(conn, ORDER_FIXTURE)
        rows = conn.execute(
            f"SELECT a.nome FROM (SELECT id, v AS nome FROM src) AS a "
            f"ORDER BY {expression} COLLATE PTBR_NOACCENT {direction}, id"
        ).fetchall()
    finally:
        conn.close()
    assert [row[0] for row in rows] == EXPECTED_HUMAN_ORDER[(expression, direction)]


@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_control_sqlite_nocase_order_is_pinned(direction):
    conn = _sqlite_memory()
    try:
        _seed_source(conn, NOCASE_FIXTURE)
        rows = conn.execute(
            "SELECT g.grupo FROM (SELECT id, v AS grupo FROM src) AS g "
            f"ORDER BY grupo COLLATE NOCASE {direction}, id"
        ).fetchall()
    finally:
        conn.close()
    assert [row[0] for row in rows] == EXPECTED_NOCASE_ORDER[direction]


@pytest.mark.parametrize(("haystack", "query", "expected"), CONTAINS_CASES)
def test_control_sqlite_human_contains_is_pinned(haystack, query, expected):
    conn = _sqlite_memory()
    try:
        value = conn.execute(
            "SELECT INSTR(PTBR_FOLD(a.nome), ?) > 0 FROM (SELECT ? AS nome) AS a",
            (human_text_key(query), haystack),
        ).fetchone()[0]
    finally:
        conn.close()
    assert bool(value) is expected


def _legacy_sqlite_like(value, pattern):
    conn = sqlite3.connect(":memory:")
    try:
        result = conn.execute(
            "SELECT u.email LIKE ? FROM (SELECT ? AS email) AS u", (pattern, value)
        ).fetchone()[0]
    finally:
        conn.close()
    return bool(result)


def test_control_sqlite_technical_like_is_pinned():
    assert _legacy_sqlite_like("Ana@X.com", "%ana@%") is True  # ASCII case-insensitive
    assert _legacy_sqlite_like("ÉVA@x", "%éva%") is False  # non-ASCII is NOT folded
    assert _legacy_sqlite_like("a%b", "a\\_b") is False  # no escape character
    assert _legacy_sqlite_like("a\\Xb", "a\\_b") is True  # '\\' literal, '_' wildcard
    assert _legacy_sqlite_like("xa\\", "%a\\") is True  # trailing '\\' is literal
    assert _legacy_sqlite_like("axb", "a_b") is True  # wildcards stay wildcards
    assert _legacy_sqlite_like(None, "%") is False


def test_control_pg_shaped_double_rejects_sqlite_only_tokens_and_runs_pg_builtins():
    pg = _pg_memory()
    try:
        for sql in (
            "SELECT 'a' COLLATE PTBR_NOACCENT",
            "SELECT PTBR_FOLD('a')",
            "SELECT INSTR('a', 'a')",
            "SELECT 'a' COLLATE NOCASE",
        ):
            with pytest.raises(PgRejectedSQL):
                pg.execute(sql)
            pg.rollback()
        assert len(pg.rejected) == 4
        assert pg.execute("SELECT strpos('abc', 'c'), strpos('', ''), chr(1)").fetchone() == (3, 1, "\x01")
        assert pg.execute("SELECT translate('ABCé', 'ABC', 'ab')").fetchone()[0] == "abé"
        assert pg.execute("SELECT lower('ÉA'), sgaa_human_text_key(NULL)").fetchone() == ("éa", "")
        assert pg.execute('SELECT \'B\' < \'a\' COLLATE "C", \'É\' < \'é\' COLLATE "C"').fetchone() == (1, 1)
        # PostgreSQL LIKE: case-sensitive, '\\' escapes by default, ESCAPE '' disables.
        assert pg.execute("SELECT 'Ana' LIKE 'ana', 'a%b' LIKE 'a\\%b', 'axb' LIKE 'a\\%b'").fetchone() == (0, 1, 0)
        assert pg.execute("SELECT 'a\\%b' LIKE 'a\\%b' ESCAPE ''").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            pg.execute("SELECT 'xa\\' LIKE '%a\\'")
        assert isinstance(pg.emulation.errors[-1], PgInvalidEscapeSequence)
        pg.rollback()
        assert pg.execute("SELECT 'xa\\' LIKE '%a\\' ESCAPE ''").fetchone()[0] == 1
    finally:
        pg.close()


def test_control_pg_order_model_honours_documented_null_defaults():
    rows = [(1, "b"), (2, None), (3, "a"), (4, "a")]
    assert _pg_order(rows, "ASC") == [(3, "a"), (4, "a"), (1, "b"), (2, None)]
    assert _pg_order(rows, "DESC") == [(2, None), (1, "b"), (3, "a"), (4, "a")]


# -- evaluators shared by the RED semantic cases and their negative controls --


def _pg_order_of(fragment):
    pg = _pg_memory()
    try:
        _seed_source(pg, ORDER_FIXTURE if "nome" in fragment else NOCASE_FIXTURE)
        column = "nome" if "nome" in fragment else "grupo"
        alias = "a" if column == "nome" else "g"
        rows = pg.execute(
            f"SELECT id, {fragment} FROM (SELECT id, v AS {column} FROM src) AS {alias}"
        ).fetchall()
        values = dict(pg.execute("SELECT id, v FROM src").fetchall())
    finally:
        pg.close()
    keyed = [(row[0], row[1]) for row in rows]
    return {
        direction: [values[row_id] for row_id, _key in _pg_order(keyed, direction)]
        for direction in ("ASC", "DESC")
    }


def _pg_contains_of(fragment, haystack, needle):
    pg = _pg_memory()
    try:
        _seed_source(pg, [haystack])
        value = pg.execute(
            f"SELECT {fragment} FROM (SELECT id, v AS nome FROM src) AS a", (needle,)
        ).fetchone()[0]
    finally:
        pg.close()
    return bool(value)


def _pg_like_of(fragment, value, pattern):
    pg = _pg_memory()
    try:
        _seed_source(pg, [value])
        result = pg.execute(
            f"SELECT {fragment} FROM (SELECT id, v AS email FROM src) AS u", (pattern,)
        ).fetchone()[0]
    finally:
        pg.close()
    return bool(result)


def _contains_mismatches(fragment):
    mismatches = []
    for haystack, query, expected in CONTAINS_CASES:
        try:
            got = _pg_contains_of(fragment, haystack, human_text_key(query))
        except Exception as exc:  # a fragment the double rejects is a mismatch
            got = repr(exc)
        if got is not expected:
            mismatches.append((haystack, query, expected, got))
    return mismatches


def _like_mismatches(fragment):
    mismatches = []
    for value in LIKE_VALUES:
        for pattern in LIKE_PATTERNS:
            expected = _legacy_sqlite_like(value, pattern)
            try:
                got = _pg_like_of(fragment, value, pattern)
            except Exception as exc:
                got = repr(exc)
            if got is not expected:
                mismatches.append((value, pattern, expected, got))
    return mismatches


def test_control_semantic_evaluators_reject_plausible_wrong_translations():
    """Negative controls: each naive PostgreSQL translation fails the contract."""
    expected_nome = {d: EXPECTED_HUMAN_ORDER[("a.nome", d)] for d in ("ASC", "DESC")}
    # Plain key: NULL collapses into '' (the '' row precedes NULL by id).
    assert _pg_order_of(f'{PG_HELPER_FUNCTION}(a.nome) COLLATE "C"') != expected_nome
    # STRICT-style key: NULL stays NULL -> PostgreSQL ASC puts it last.
    assert _pg_order_of(
        f'(CASE WHEN a.nome IS NULL THEN NULL ELSE {PG_HELPER_FUNCTION}(a.nome) END) COLLATE "C"'
    ) != expected_nome
    # Unicode lower instead of ASCII NOCASE: É and é tie.
    assert _pg_order_of('lower(grupo) COLLATE "C"') != EXPECTED_NOCASE_ORDER
    # Plain column ("C" without folding): 'B'/'Z' before 'a'.
    assert _pg_order_of('grupo COLLATE "C"') != EXPECTED_NOCASE_ORDER
    # Wildcard LIKE over lower(): accents decide and '%'/'_' are wildcards.
    assert _contains_mismatches("lower(a.nome) LIKE '%' || lower(?) || '%'")
    # PostgreSQL default LIKE: case-sensitive and '\\' escapes.
    assert _like_mismatches("u.email LIKE ?")
    # Unicode lower() broadens non-ASCII matches beyond SQLite LIKE.
    assert _like_mismatches("lower(u.email) LIKE lower(?) ESCAPE ''")


def test_control_d5_detector_discriminates():
    def ambient_helper(expression):
        from app.db import get_db_connection

        return expression if get_db_connection() else expression

    def explicit_helper(expression, *, connection):
        """Mentions request and get_db_connection only in its docstring."""
        return expression if connection else expression

    assert _ambient_engine_lookups(ambient_helper)
    assert _ambient_engine_lookups(explicit_helper) == []
    assert _connection_parameter(explicit_helper).name == "connection"
    with pytest.raises(AssertionError):
        _connection_parameter(ambient_helper)


def test_control_ratchet_scanner_discriminates():
    source = '''
"""Docstring may mention COLLATE PTBR_NOACCENT and INSTR(PTBR_FOLD(x))."""
# comment: COLLATE NOCASE
ORDER = "COALESCE(u.nome, '') COLLATE PTBR_NOACCENT"
CONTAINS = f"INSTR(PTBR_FOLD({1}), ?) > 0"
NOCASE = " ORDER BY grupo collate nocase ASC"
TECHNICAL = "LOWER(u.email)"  # D-6: plain technical ordering is not a U5-D token
'''
    hits = {token for _label, _line, token in _raw_token_hits(source)}
    assert hits == {"COLLATE PTBR_*", "INSTR(", "PTBR_FOLD(", "COLLATE NOCASE"}
    assert not _raw_token_hits('"""COLLATE PTBR_NOACCENT"""\nX = "LOWER(u.email)"\n')


def _u5a_sections(payload):
    """The U5-A contract sections with only the declared later deltas removed."""
    sections = copy.deepcopy({key: payload[key] for key in U5A_CURRENT_STATE_KEYS})
    assert set(LATER_ADDED_TABLES) <= set(sections["tables"]), "declared later tables missing"
    for table in LATER_ADDED_TABLES:
        del sections["tables"][table]
    for table, (column, foreign_key, check) in LATER_ADDED_COLUMNS.items():
        spec = sections["tables"][table]
        assert spec["columns"][-1]["name"] == column, "declared later column must be the last one"
        spec["columns"].pop()
        if foreign_key is not None:
            [declared] = [fk for fk in spec["foreign_keys"] if fk["name"] == foreign_key]
            spec["foreign_keys"].remove(declared)
        if check is not None:
            [declared] = [ck for ck in spec["checks"] if ck["name"] == check]
            spec["checks"].remove(declared)
    for (table, check), (u5a_expression, later_expression) in LATER_CHANGED_CHECKS.items():
        [declared] = [ck for ck in sections["tables"][table]["checks"] if ck["name"] == check]
        assert declared["expression"] == later_expression, "declared later CHECK change missing"
        declared["expression"] = u5a_expression
    for name in LATER_ADDED_INDEXES:
        del sections["indexes"][name]
    for name in LATER_ADDED_TRIGGERS:
        del sections["triggers"][name]
    baseline = sections["schema_migrations_baseline"]
    assert [row["version"] for row in baseline][-len(LATER_ADDED_BASELINE_VERSIONS):] == list(
        LATER_ADDED_BASELINE_VERSIONS
    )
    sections["schema_migrations_baseline"] = baseline[: -len(LATER_ADDED_BASELINE_VERSIONS)]
    assert sections["version"] == sections["schema_meta"]["version"] == U5A_SCHEMA_VERSION + len(
        LATER_ADDED_BASELINE_VERSIONS
    )
    sections["version"] = sections["schema_meta"]["version"] = U5A_SCHEMA_VERSION
    return sections


def _sections_digest(sections):
    return hashlib.sha256(
        json.dumps(sections, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_control_u5a_current_state_authority_untouched():
    payload = pg_schema.pg_contract_payload()
    digest = _sections_digest(_u5a_sections(payload))
    assert digest == U5A_CURRENT_STATE_SHA256, "D-1 forbids U5-A table/index/trigger/version change"
    assert tuple(pg_schema.PG_HELPERS[: len(U5A_HELPERS)]) == U5A_HELPERS
    assert pg_schema.PG_SCHEMA_VERSION == U5A_SCHEMA_VERSION + len(LATER_ADDED_BASELINE_VERSIONS)


def test_control_u5a_guard_still_detects_an_undeclared_change():
    """Negative control: removing the declared S1 delta must not hide any other edit."""
    payload = copy.deepcopy(pg_schema.pg_contract_payload())
    payload["tables"]["reportes"]["columns"][0]["not_null"] = False
    assert _sections_digest(_u5a_sections(payload)) != U5A_CURRENT_STATE_SHA256
    payload = copy.deepcopy(pg_schema.pg_contract_payload())
    payload["tables"]["usuarios_foto_extra"] = payload["tables"]["usuarios_foto"]
    assert _sections_digest(_u5a_sections(payload)) != U5A_CURRENT_STATE_SHA256


def test_control_no_unaccent_or_extension_dependency():
    text = pg_schema.PG_SCHEMA_SQL_TEXT
    assert not re.search(r"\bunaccent\b", text, re.IGNORECASE)
    assert not re.search(r"CREATE\s+EXTENSION", text, re.IGNORECASE)


def test_control_host_unicodedata_matches_frozen_fold_version():
    """D-2 drift detector: a different host Unicode database must fail loudly.

    The frozen fold tables were derived from unicodedata 15.0.0.  On a host
    with another version the frozen data is NOT regenerated; the contract must
    be re-derived deliberately (new version recorded, PostgreSQL contract
    digest changes, E-PG1 rerun).
    """
    assert unicodedata.unidata_version == FROZEN_UNICODE_VERSION, (
        f"host unicodedata {unicodedata.unidata_version} != frozen "
        f"{FROZEN_UNICODE_VERSION}: human_text_key and the frozen PostgreSQL fold "
        "may now disagree -- re-derive and re-record the fold contract"
    )


# ===========================================================================
# RED -- dialect authority (D-5, closed inputs, SQLite preservation)
# ===========================================================================


@pytest.mark.parametrize("family", sorted(DIALECT_OWNERS))
def test_dialect_owner_exists_with_explicit_required_connection(family):
    owner = _owner(family)
    param = _connection_parameter(owner)
    assert param.default is inspect.Parameter.empty, (
        f"{owner.__name__}: the caller-owned connection must be required (D-5)"
    )
    assert _ambient_engine_lookups(owner) == [], (
        f"{owner.__name__} discovers the engine from ambient state (D-5)"
    )
    assert owner.__name__ in sql_dialect.__all__


@pytest.mark.parametrize("family", sorted(DIALECT_OWNERS))
def test_dialect_engine_comes_only_from_the_given_connection(family, monkeypatch):
    owner = _owner(family)
    expression = FAMILY_EXPRESSIONS[family][0]

    def forbidden_lookup():
        raise AssertionError("dialect fragment looked up the request connection (D-5)")

    monkeypatch.setattr(app_db, "get_db_connection", forbidden_lookup)
    # Ambient backend says PostgreSQL, the caller's connection is SQLite.
    monkeypatch.setattr(app_db, "database_backend", lambda: "postgres")
    sqlite_conn = sqlite3.connect(":memory:")
    try:
        sqlite_fragment = _invoke(owner, sqlite_conn, expression)
    finally:
        sqlite_conn.close()
    # Ambient backend says SQLite, the caller's connection is PostgreSQL.
    monkeypatch.setattr(app_db, "database_backend", lambda: "sqlite")
    pg_fragment = _invoke(owner, _RecordingPgConnection(), expression)

    assert sqlite_fragment != pg_fragment
    assert _sqlite_only_tokens(pg_fragment) == []
    if family != "technical_like":
        assert _sqlite_only_tokens(sqlite_fragment)


@pytest.mark.parametrize(
    ("family", "expression"),
    [(family, expression) for family in sorted(FAMILY_EXPRESSIONS) for expression in FAMILY_EXPRESSIONS[family]],
)
def test_dialect_sqlite_branch_reproduces_historical_sql(family, expression):
    owner = _owner(family)
    conn = sqlite3.connect(":memory:")
    try:
        fragment = _invoke(owner, conn, expression)
    finally:
        conn.close()
    historical = {
        "human_order": f"{expression} COLLATE PTBR_NOACCENT",
        "human_contains": f"INSTR(PTBR_FOLD({expression}), ?) > 0",
        "nocase_order": f"{expression} COLLATE NOCASE",
    }
    if family in historical:
        assert fragment == historical[family]
    else:
        # Technical LIKE: SQLite keeps native LIKE semantics (one bound pattern).
        assert fragment.count("?") == 1 and _LIKE_RE.search(fragment)
        assert not _ILIKE_RE.search(fragment)


def test_dialect_sqlite_technical_like_preserves_native_semantics():
    owner = _owner("technical_like")
    conn = sqlite3.connect(":memory:")
    try:
        fragment = _invoke(owner, conn, "u.email")
        for value in LIKE_VALUES:
            for pattern in LIKE_PATTERNS:
                got = conn.execute(
                    f"SELECT {fragment} FROM (SELECT ? AS email) AS u", (pattern, value)
                ).fetchone()[0]
                assert bool(got) is _legacy_sqlite_like(value, pattern), (value, pattern)
    finally:
        conn.close()


@pytest.mark.parametrize("family", sorted(DIALECT_OWNERS))
@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_dialect_rejects_unvalidated_expressions(family, engine):
    owner = _owner(family)
    connection = sqlite3.connect(":memory:") if engine == "sqlite" else _RecordingPgConnection()
    try:
        for hostile in HOSTILE_EXPRESSIONS:
            with pytest.raises(ValueError):
                _invoke(owner, connection, hostile)
    finally:
        if engine == "sqlite":
            connection.close()


@pytest.mark.parametrize("family", sorted(DIALECT_OWNERS))
def test_dialect_pg_fragments_are_postgres_shaped(family):
    owner = _owner(family)
    for expression in FAMILY_EXPRESSIONS[family]:
        fragment = _invoke(owner, _RecordingPgConnection(), expression)
        assert _sqlite_only_tokens(fragment) == [], (expression, fragment)
        if family in ("human_order", "nocase_order"):
            # Database-default collation would reorder punctuation/spaces.
            assert _COLLATE_C_RE.search(fragment), fragment
            assert "?" not in fragment
        if family == "human_order":
            assert PG_HELPER_FUNCTION in fragment
        if family == "nocase_order":
            assert not _LOCALE_CASE_FUNCTION_RE.search(fragment), fragment
        if family == "human_contains":
            assert PG_HELPER_FUNCTION in fragment
            assert fragment.count("?") == 1
            assert not _LIKE_RE.search(fragment) and not _ILIKE_RE.search(fragment)
        if family == "technical_like":
            assert fragment.count("?") == 1
            assert not _ILIKE_RE.search(fragment)
            assert not _LOCALE_CASE_FUNCTION_RE.search(fragment), fragment
            assert _ESCAPE_EMPTY_RE.search(fragment), fragment


# ===========================================================================
# RED -- PostgreSQL-shaped semantics of the owners
# ===========================================================================


@pytest.mark.parametrize("expression", ["a.nome", "COALESCE(a.nome, '')"])
def test_pg_human_order_reproduces_sqlite_ptbr_order(expression):
    fragment = _invoke(_owner("human_order"), _RecordingPgConnection(), expression)
    got = _pg_order_of(fragment)
    assert got == {d: EXPECTED_HUMAN_ORDER[(expression, d)] for d in ("ASC", "DESC")}


def test_pg_nocase_order_reproduces_sqlite_nocase():
    fragment = _invoke(_owner("nocase_order"), _RecordingPgConnection(), "grupo")
    assert _pg_order_of(fragment) == EXPECTED_NOCASE_ORDER


def test_pg_human_contains_reproduces_sqlite_instr():
    fragment = _invoke(_owner("human_contains"), _RecordingPgConnection(), "a.nome")
    assert _contains_mismatches(fragment) == []


def test_pg_technical_like_reproduces_sqlite_like_without_22025():
    fragment = _invoke(_owner("technical_like"), _RecordingPgConnection(), "u.email")
    assert _like_mismatches(fragment) == []


# ===========================================================================
# RED -- request filter helpers take the connection explicitly (D-5)
# ===========================================================================


@pytest.mark.parametrize("name", FILTER_HELPERS)
def test_filter_helper_requires_explicit_connection(name):
    helper = getattr(web_filters, name)
    param = _connection_parameter(helper)
    assert param.default is inspect.Parameter.empty, f"{name}: connection must be required"
    assert _ambient_engine_lookups(helper) == [], f"{name} uses ambient engine lookup"


def test_filter_helpers_emit_postgres_fragments_for_a_postgres_connection():
    pg = _RecordingPgConnection()
    conditions, params = [], []
    _invoke(web_filters.append_human_text_contains_condition, pg, conditions, params, "u.nome", "  ÉVERTO ")
    _invoke(web_filters.append_human_text_contains_condition, pg, conditions, params, "u.nome", "́")
    _invoke(web_filters.append_text_contains_condition, pg, conditions, params, "u.email", "Ana\\")
    assert len(conditions) == 2, "an empty folded needle is still skipped by the append helper"
    assert params == ["everto", "%ana\\%"]
    for condition in conditions:
        assert _sqlite_only_tokens(condition) == [], condition
    assert _ESCAPE_EMPTY_RE.search(conditions[1])
    direct = _invoke(web_filters.human_text_contains_sql, pg, "titulo")
    assert _sqlite_only_tokens(direct) == [] and direct.count("?") == 1


def test_filter_helpers_keep_sqlite_sql_for_a_sqlite_connection():
    conn = sqlite3.connect(":memory:")
    try:
        conditions, params = [], []
        _invoke(web_filters.append_human_text_contains_condition, conn, conditions, params, "u.nome", "Éverto")
        assert conditions == ["INSTR(PTBR_FOLD(u.nome), ?) > 0"] and params == ["everto"]
        assert _invoke(web_filters.human_text_contains_sql, conn, "titulo") == "INSTR(PTBR_FOLD(titulo), ?) > 0"
    finally:
        conn.close()


# ===========================================================================
# RED -- D-1 schema seam
# ===========================================================================


def test_d1_helper_is_part_of_the_pg_helper_contract():
    assert PG_HELPER_FUNCTION in pg_schema.PG_HELPERS
    assert PG_HELPER_FUNCTION in pg_schema.pg_contract_payload()["helpers"]


def test_d1_helper_statement_is_immutable_null_tolerant_and_locale_free():
    statement = _helper_statement()
    assert re.search(r"RETURNS\s+text", statement, re.IGNORECASE)
    assert re.search(r"\bIMMUTABLE\b", statement, re.IGNORECASE)
    assert re.search(r"PARALLEL\s+SAFE", statement, re.IGNORECASE)
    # human_text_key(None) == '': the helper must not be STRICT.
    assert not re.search(r"\bSTRICT\b|RETURNS\s+NULL\s+ON\s+NULL\s+INPUT", statement, re.IGNORECASE)
    # U5-D Unicode-portability correction: the helper must not consult the
    # server's normalization tables (PostgreSQL 15 = Unicode 14, 16 = 15.0,
    # 17 = 15.1); it applies the frozen Unicode 15.0.0 mapping itself.
    assert not re.search(r"\bnormalize\s*\(", statement, re.IGNORECASE)
    assert "NFKD" not in statement.upper()
    assert not _LOCALE_CASE_FUNCTION_RE.search(statement)
    assert not re.search(r"\bunaccent\b|\bILIKE\b", statement, re.IGNORECASE)
    assert "PTBR_NOACCENT" not in statement.upper()  # U5-A DDL guard stays satisfied


def test_d1_utf8_server_encoding_is_required_and_validated_first():
    assert getattr(pg_schema, "PG_REQUIRED_SERVER_ENCODING", None) == PG_REQUIRED_SERVER_ENCODING

    class _CatalogQueryAfterEncoding(Exception):
        pass

    class _EncodingOnlyConnection:
        def __init__(self, encoding):
            self.encoding = encoding

        def execute(self, sql, params=None):
            text = str(sql).lower()
            if "encoding" in text:
                return types.SimpleNamespace(
                    fetchall=lambda: [(self.encoding,)], fetchone=lambda: (self.encoding,)
                )
            raise _CatalogQueryAfterEncoding(sql)

    with pytest.raises(pg_schema.PostgresSchemaError, match="(?i)encoding"):
        pg_schema.validate_pg_schema(_EncodingOnlyConnection("SQL_ASCII"))
    # UTF8 passes the precondition and proceeds to the catalog census.
    with pytest.raises(_CatalogQueryAfterEncoding):
        pg_schema.validate_pg_schema(_EncodingOnlyConnection("UTF8"))


# ===========================================================================
# RED -- D-2 frozen fold mapping
# ===========================================================================


def test_d2_frozen_mapping_records_its_unicode_version():
    owner = _fold_owner()
    assert owner.UNICODE_VERSION == FROZEN_UNICODE_VERSION


def test_d2_frozen_mapping_is_literal_data_not_generated_at_import():
    owner = _fold_owner()
    tree = ast.parse(Path(owner.__file__).read_text(encoding="utf-8"))
    literal_names = {"UNICODE_VERSION", "MAPPING_SHA256"}
    seen = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in literal_names:
                    seen.add(target.id)
                    assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str), (
                        f"{target.id} must be a literal recorded value"
                    )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                func = inner.func
                name = getattr(func, "id", None) or getattr(func, "attr", "")
                assert not name.startswith("derive"), "the frozen mapping must not be derived at import"
                assert not (isinstance(func, ast.Attribute) and getattr(func.value, "id", "") == "unicodedata"), (
                    "module import must not consult the host unicodedata"
                )
    assert seen == literal_names


def test_d2_frozen_mapping_digest_is_self_consistent():
    owner = _fold_owner()
    assert re.fullmatch(r"[0-9a-f]{64}", owner.MAPPING_SHA256)
    assert owner.mapping_sha256() == owner.MAPPING_SHA256


def test_d2_frozen_mapping_is_rederivable_from_its_recorded_version():
    owner = _fold_owner()
    assert unicodedata.unidata_version == owner.UNICODE_VERSION  # see drift control
    assert owner.derive_mapping_sha256(unicodedata) == owner.MAPPING_SHA256


def test_d2_derivation_refuses_a_different_unicode_version():
    owner = _fold_owner()
    other = types.SimpleNamespace(
        unidata_version="99.0.0",
        normalize=unicodedata.normalize,
        category=unicodedata.category,
    )
    with pytest.raises((ValueError, RuntimeError)):
        owner.derive_mapping_sha256(other)


def test_d2_pg_contract_digest_covers_the_frozen_mapping():
    owner = _fold_owner()
    payload = json.dumps(pg_schema.pg_contract_payload(), ensure_ascii=False, sort_keys=True)
    assert owner.MAPPING_SHA256 in payload
    assert owner.UNICODE_VERSION in payload


def _fold_corpus():
    values = [value for value, _key in ORACLE_KEYS]
    values += list(ORDER_FIXTURE) + list(NOCASE_FIXTURE)
    values += [haystack for haystack, _q, _e in CONTAINS_CASES] + [q for _h, q, _e in CONTAINS_CASES]
    values += ["  Ação   Ética \tÔNIBUS  ", "ẞ ß ﬀ Ǆ ǈ", "Ⅻ ① ㎏", "ΣΑΣ σας", "Ⓐⓑ"]
    values += UNICODE_DISCRIMINATORS
    return values


#: Multi-character discriminators for the frozen Unicode 15.0.0 fold.
UNICODE_DISCRIMINATORS = [
    "\u0390 \u1fb3 \u1fbc \u1f50 \u0130 \u01f0",  # Greek/Latin folds whose decomposition carries marks
    "\ufb03 \ufb06 \ufdfa \u2475 \u3371",  # ligatures and long compatibility expansions
    "a\U000E0100b c\U000E01EFd",  # supplementary variation-selector marks
    "\U0001D400\U0001D41A \U0001F130 \U0002F800",  # supplementary 1:1 mappings
    "\U0001E030\U0001E06D",  # Unicode 15.0 additions (absent from PostgreSQL 15's tables)
    "\uac00\uac01\ud7a3 \u1100",  # Hangul syllables (arithmetic) and a conjoining jamo
    "D\u2019\u00c1vila \u2013 \u201cA\u00e7\u00e3o\u201d\u2003\u2026",  # typographic punctuation tier
    "\u00df\u1e9e  \t\u3000x\u0085y",  # 1:n casefolds and Unicode whitespace
]


def test_d2_model_fold_preserves_human_text_key_on_discriminating_corpus():
    owner = _fold_owner()
    mismatches = [(v, owner.fold(v), human_text_key(v)) for v in _fold_corpus() if owner.fold(v) != human_text_key(v)]
    assert mismatches == []


def test_d2_model_fold_preserves_human_text_key_on_every_assigned_code_point():
    owner = _fold_owner()
    mismatches = []
    for code_point in range(0x110000):
        char = chr(code_point)
        if unicodedata.category(char) in ("Cn", "Cs"):
            continue
        if owner.fold(char) != human_text_key(char):
            mismatches.append(hex(code_point))
            if len(mismatches) > 20:
                break
    assert mismatches == []


# -- Unicode portability: no runtime Unicode database, PG body == fold --------


def _pg_plan_model(owner):
    """Python model of the emitted PostgreSQL body, built from the same plan.

    PostgreSQL semantics reproduced: ``translate`` (first occurrence wins,
    characters beyond ``to`` deleted), tier choice by the tier's ranges, the
    guarded per-character pass (array lookup + Hangul arithmetic), then
    ``regexp_replace(' {2,}', ' ')`` and ``btrim(' ')``.
    """
    plan = owner.pg_function_plan()
    tables = []
    for ranges, source, target in plan["tiers"]:
        table = {}
        for index, char in enumerate(source):
            table.setdefault(char, target[index] if index < len(target) else "")
        tables.append((ranges, table))
    expansions = dict(plan["expansions"])
    per_char = plan["per_char_ranges"]
    first, last = plan["hangul"]

    def in_ranges(char, ranges):
        return any(lo <= ord(char) <= hi for lo, hi in ranges)

    def hangul(code_point):
        index = code_point - first
        trail = index % 28
        return (
            chr(0x1100 + index // 588)
            + chr(0x1161 + (index % 588) // 28)
            + (chr(0x11A7 + trail) if trail else "")
        )

    def model(value):
        text = "" if value is None else str(value)
        table = next(t for ranges, t in tables if all(in_ranges(c, ranges) for c in text))
        text = "".join(table.get(c, c) for c in text)
        if any(in_ranges(c, per_char) for c in text):
            text = "".join(
                hangul(ord(c)) if first <= ord(c) <= last else expansions.get(c, c) for c in text
            )
        return re.sub(" {2,}", " ", text).strip(" ")

    return model


def test_d2_fold_does_not_consult_a_unicode_database(monkeypatch):
    owner = _fold_owner()
    source = Path(owner.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_imports = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } | {node.module for node in tree.body if isinstance(node, ast.ImportFrom)}
    assert "unicodedata" not in module_imports, "unicodedata must not be a runtime dependency"
    assert "unicodedata" not in inspect.getsource(owner.fold)
    assert "normalize" not in inspect.getsource(owner.fold)

    def refuse(*_args, **_kwargs):
        raise AssertionError("the fold consulted the host Unicode database")

    # Scoped: pytest's own reporting uses unicodedata, so restore immediately.
    with monkeypatch.context() as patch:
        patch.setattr(unicodedata, "normalize", refuse)
        patch.setattr(unicodedata, "category", refuse)
        folded = owner.fold("  ÉVERTO   Ação ﬁ\U0001E030 가 ")
    assert folded == "everto acao fiа 가"


def test_d2_frozen_fold_pins_unicode_15_discriminators():
    owner = _fold_owner()
    # U+1E030 gained its compatibility decomposition in Unicode 15.0, so a
    # fold computed from PostgreSQL 15's normalization tables (Unicode 14)
    # would leave it unchanged.
    assert owner.fold("\U0001E030") == "а"
    assert owner.fold("a\U000E0100b\U000E01EFc") == "abc"
    assert owner.fold("각") == "각"
    assert owner.fold("ΐ") == "ι"
    assert owner.fold("ﷺ") == human_text_key("ﷺ") and len(owner.fold("ﷺ")) == 18


def test_d2_pg_body_model_reproduces_fold_on_every_assigned_code_point():
    owner = _fold_owner()
    model = _pg_plan_model(owner)
    mismatches = []
    for code_point in range(1, 0x110000):
        char = chr(code_point)
        if unicodedata.category(char) in ("Cn", "Cs"):
            continue
        if model(char) != owner.fold(char):
            mismatches.append(hex(code_point))
            if len(mismatches) > 20:
                break
    assert mismatches == []


def test_d2_pg_body_model_reproduces_fold_on_multi_character_strings():
    import random

    owner = _fold_owner()
    model = _pg_plan_model(owner)
    corpus = [v for v in _fold_corpus() if v is not None]
    rng = random.Random(20261006)
    pool = [ord(c) for v in corpus for c in str(v)] + list(range(0x20, 0x250)) + [
        0x2003, 0x2019, 0x2026, 0x3000, 0x1F80, 0xFB03, 0xFDFA, 0x1E030, 0xE0100, 0xAC00, 0xD7A3,
    ]
    corpus += ["".join(chr(rng.choice(pool)) for _ in range(rng.randint(0, 12))) for _ in range(20000)]
    assert [(v, model(v), owner.fold(v)) for v in corpus if model(v) != owner.fold(v)] == []
    assert model(None) == owner.fold(None) == ""


def test_d1_helper_ddl_renders_the_frozen_plan():
    owner = _fold_owner()
    statement = _helper_statement()
    plan = owner.pg_function_plan()
    for _ranges, source, target in plan["tiers"]:
        assert f"E'{owner._pg_escape(source)}'" in statement
        assert f"E'{owner._pg_escape(target)}'" in statement
    for source, target in plan["expansions"]:
        assert f"E'{owner._pg_escape(source)}'" in statement
        assert f"E'{owner._pg_escape(target)}'" in statement
    assert owner._pg_class(plan["per_char_ranges"]) in statement
    assert statement.strip() == owner.pg_function_sql(PG_HELPER_FUNCTION).strip()


# ===========================================================================
# RED -- D-4 ratchet over the migrated surfaces
# ===========================================================================


def test_d4_migrated_surfaces_carry_no_raw_sqlite_human_text_tokens():
    hits = []
    for relative in MIGRATED_SURFACES:
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        hits.extend(_raw_token_hits(source, relative))
    assert hits == [], f"raw SQLite-only human-text SQL outside app/sql_dialect.py: {hits!r}"


# ===========================================================================
# RED -- route-level reproduction on the PostgreSQL-shaped path
# ===========================================================================

ROUTE_NAMES = (
    "Wandrew Ordem",
    "Felipe Ordem",
    "Éverto Ordem",
    "Victor Ordem",
    "Eduardo Ordem",
    "João Ordem",
)
EXPECTED_ROUTE_ORDER = [
    "Eduardo Ordem", "Éverto Ordem", "Felipe Ordem", "João Ordem", "Victor Ordem", "Wandrew Ordem",
]
CURSOS = (("ZZ1", "Ética Aeronáutica"), ("ZZ2", "Engenharia"), ("ZZ3", "Física"), ("A\\B9", "Barra Invertida"))


def _admin_names(page):
    return [html_module.unescape(n) for n in re.findall(r'data-user-nome="([^"]*)"', page)]


def _list_cells(page, list_id, index):
    body = page.split(f'id="{list_id}"', 1)[1].split("<script", 1)[0]
    rows = re.split(r'<div class="impresso-card[^"]*"\s+role="listitem"', body)[1:]
    texts = []
    for row in rows:
        cells = re.findall(r'<div class="cell[^"]*"[^>]*>(.*?)</div>', row, re.S)
        texts.append(html_module.unescape(re.sub(r"<[^>]+>", "", cells[index]).strip()))
    return texts


_PASSWORD_HASH = []


def _password_hash():
    if not _PASSWORD_HASH:
        _PASSWORD_HASH.append(main.hash_password("x"))
    return _PASSWORD_HASH[0]


def _seed_route_fixture(conn):
    from app.user_accounts import create_usuario_with_access_level

    for index, nome in enumerate(ROUTE_NAMES):
        create_usuario_with_access_level(
            conn, nome, f"u5d.{index}@example.test", _password_hash(),
            "admin", "admin_total", credential_state="personal",
        )
    for codigo, nome in CURSOS:
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, periodo, status) "
            "VALUES (?, ?, 4, 'integral', 'ativo')",
            (nome, codigo),
        )
    conn.commit()


@pytest.fixture
def route_env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "u5d-routes.db") as environment:
        with main.app.app_context():
            _seed_route_fixture(main.get_db_connection())
            main.close_db_connection(None)
        login_admin(environment["client"])
        yield environment


def _view_modules():
    import app.views.admin.acesso as acesso
    import app.views.admin.alunos_turmas_cursos as alunos_turmas_cursos
    import app.views.admin.atividades as atividades

    return (acesso, alunos_turmas_cursos, atividades)


def _get_on_pg_shaped_path(env, monkeypatch, path, query, *, reject_sqlite_only=True):
    """GET ``path`` with every request connection replaced by the PG-shaped double."""
    client = env["client"]
    with main.app.app_context():
        main.close_db_connection(None)
        real = main.get_db_connection()
        pg = PgShapedPtbrConnection(real, reject_sqlite_only=reject_sqlite_only)

        def provider():
            from flask import g

            g.db = pg
            return pg

        with monkeypatch.context() as patch:
            patch.setattr(app_db, "get_db_connection", provider)
            for module in _view_modules():
                patch.setattr(module, "get_db_connection", provider)
            error = None
            response = None
            try:
                response = client.get(path, query_string=query)
            except Exception as exc:  # TESTING propagates handler exceptions
                error = exc
            finally:
                main.close_db_connection(None)
    return pg, response, error


def _assert_pg_route_clean(pg, response, error):
    assert pg.rejected == [], [
        (tokens, sql[:160]) for tokens, sql in pg.rejected
    ]
    assert error is None, repr(error)
    assert response is not None and response.status_code == 200


def test_control_routes_render_on_the_sqlite_path(route_env):
    client = route_env["client"]

    def page(path, **query):
        response = client.get(path, query_string=query)
        assert response.status_code == 200, (path, query)
        return response.get_data(as_text=True)

    names = [n for n in _admin_names(page("/admin/acesso", s="nome")) if n in ROUTE_NAMES]
    assert names == EXPECTED_ROUTE_ORDER
    assert _admin_names(page("/admin/acesso", q="EVERTO")) == ["Éverto Ordem"]
    assert _list_cells(page("/admin/cursos", nome="etica"), "cursos-list", 1) == ["Ética Aeronáutica"]
    # Technical LIKE keeps SQLite semantics: '\\' is literal, case is ASCII-folded.
    assert _list_cells(page("/admin/cursos", codigo="A\\", s="codigo"), "cursos-list", 1) == ["Barra Invertida"]
    page("/admin/atividades", s="grupo")


#: Representative routes and the canonical U5-D families each must execute on
#: the PostgreSQL path, as ``(family, call-site expression)``.  The expected
#: SQL signature is generated by the owner itself (never re-spelled here).
#:
#: Adjudication record (TEP class B): the RED-time version of this control
#: proved traversal through ``pg.rejected`` (raw SQLite tokens reaching the
#: PostgreSQL path) -- the pre-U5-D failure mechanism, which correct U5-D
#: production necessarily removes.  That pre-GREEN reproduction (all four
#: route REDs failing on raw COLLATE PTBR_* / INSTR(PTBR_FOLD / COLLATE NOCASE
#: and on PostgreSQL LIKE escaping) is recorded in the unit record; the live
#: control states the enduring post-U5-D invariant below.
ROUTE_CASES = (
    ("/admin/acesso", {"s": "nome"}, (("human_order", "COALESCE(u.nome, '')"),)),
    (
        "/admin/acesso",
        {"q": "EVERTO"},
        (
            ("human_contains", "u.nome"),
            ("technical_like", "u.email"),
            ("human_order", "COALESCE(u.nome, '')"),
        ),
    ),
    (
        "/admin/cursos",
        {"nome": "etica"},
        (("human_contains", "c.nome"), ("human_order", "COALESCE(c.nome, '')")),
    ),
    (
        "/admin/cursos",
        {"codigo": "A\\", "s": "codigo"},
        (("technical_like", "LOWER(COALESCE(c.codigo, ''))"),),
    ),
    (
        "/admin/atividades",
        {"s": "grupo"},
        (("nocase_order", "grupo"), ("human_order", "nome")),
    ),
)


def _missing_u5d_families(pg, expected):
    """Expected canonical fragments that no PostgreSQL-path statement contains."""
    executed = [sql for sql, _params in pg.pg_statements]
    missing = []
    for family, expression in expected:
        fragment = _invoke(_owner(family), _RecordingPgConnection(), expression)
        assert not _sqlite_only_tokens(fragment)
        if not any(fragment in sql for sql in executed):
            missing.append((family, expression, fragment))
    return missing


def test_control_pg_shaped_route_harness_blocks_only_on_u5d_tokens(route_env, monkeypatch):
    """Post-U5-D invariant for every representative route on the PG-shaped
    path (SQLite-only tokens rejected exactly as PostgreSQL rejects them):

    A. the request completes (200, no error);
    B. no prohibited SQLite human-text token reaches the path;
    C. the route executes the canonical U5-D family expected for it.
    """
    for path, query, expected in ROUTE_CASES:
        pg, response, error = _get_on_pg_shaped_path(route_env, monkeypatch, path, query)
        assert error is None, (path, query, repr(error))
        assert response.status_code == 200, (path, query)
        assert pg.rejected == [], (path, query, pg.rejected)
        assert _missing_u5d_families(pg, expected) == [], (path, query)


def test_control_route_family_check_is_not_vacuous(route_env, monkeypatch):
    """A route that answers 200 with nothing rejected but never executes the
    expected family must be reported: ``/admin/acesso?s=email`` orders by the
    technical ``LOWER(u.email)`` (D-6), not by the human-text name key."""
    expected = (("human_order", "COALESCE(u.nome, '')"),)
    pg, response, error = _get_on_pg_shaped_path(
        route_env, monkeypatch, "/admin/acesso", {"s": "email"}
    )
    assert error is None and response.status_code == 200
    assert pg.rejected == []
    assert [item[:2] for item in _missing_u5d_families(pg, expected)] == [
        ("human_order", "COALESCE(u.nome, '')")
    ]
    # The same check is satisfied by the route that does execute the family.
    pg, response, error = _get_on_pg_shaped_path(
        route_env, monkeypatch, "/admin/acesso", {"s": "nome"}
    )
    assert error is None and _missing_u5d_families(pg, expected) == []


def test_route_acesso_ptbr_order_and_contains_on_pg_shaped_path(route_env, monkeypatch):
    pg, response, error = _get_on_pg_shaped_path(route_env, monkeypatch, "/admin/acesso", {"s": "nome"})
    _assert_pg_route_clean(pg, response, error)
    names = [n for n in _admin_names(response.get_data(as_text=True)) if n in ROUTE_NAMES]
    assert names == EXPECTED_ROUTE_ORDER

    pg, response, error = _get_on_pg_shaped_path(route_env, monkeypatch, "/admin/acesso", {"q": "EVERTO"})
    _assert_pg_route_clean(pg, response, error)
    assert _admin_names(response.get_data(as_text=True)) == ["Éverto Ordem"]


def test_route_cursos_append_contains_and_order_on_pg_shaped_path(route_env, monkeypatch):
    pg, response, error = _get_on_pg_shaped_path(route_env, monkeypatch, "/admin/cursos", {"nome": "etica"})
    _assert_pg_route_clean(pg, response, error)
    assert _list_cells(response.get_data(as_text=True), "cursos-list", 1) == ["Ética Aeronáutica"]


def test_route_cursos_technical_like_on_pg_shaped_path(route_env, monkeypatch):
    pg, response, error = _get_on_pg_shaped_path(
        route_env, monkeypatch, "/admin/cursos", {"codigo": "A\\", "s": "codigo"}
    )
    _assert_pg_route_clean(pg, response, error)
    assert pg.emulation.errors == []
    assert _list_cells(response.get_data(as_text=True), "cursos-list", 1) == ["Barra Invertida"]


def test_route_atividades_nocase_order_on_pg_shaped_path(route_env, monkeypatch):
    pg, response, error = _get_on_pg_shaped_path(route_env, monkeypatch, "/admin/atividades", {"s": "grupo"})
    _assert_pg_route_clean(pg, response, error)


# ===========================================================================
# E-PG1 -- real PostgreSQL (skips without SGAA_PG_TEST_URL)
# ===========================================================================

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()
real_pg = pytest.mark.skipif(
    not PG_URL,
    reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT",
)
DISPOSABLE_DATABASE_PREFIX = "sgaa_u5d_test_"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1"})
NON_C_LOCALES = ("en_US.UTF-8", "en_US.utf8", "pt_BR.UTF-8", "pt_BR.utf8")


def _database_url(database):
    parts = urlsplit(PG_URL)
    return urlunsplit((parts.scheme, parts.netloc, "/" + database, "", ""))


@pytest.fixture
def real_pg_connection():
    psycopg = pytest.importorskip("psycopg")
    admin = psycopg.connect(PG_URL, prepare_threshold=None, autocommit=True)
    database = f"{DISPOSABLE_DATABASE_PREFIX}{secrets.token_hex(6)}"
    created = False
    raw = None
    try:
        for locale in NON_C_LOCALES + (None,):
            clause = f" LC_COLLATE '{locale}' LC_CTYPE '{locale}'" if locale else ""
            try:
                admin.execute(f"CREATE DATABASE \"{database}\" TEMPLATE template0 ENCODING 'UTF8'{clause}")
                created = True
                break
            except psycopg.Error:
                continue
        if not created:
            pytest.skip("cannot create a disposable UTF8 database with SGAA_PG_TEST_URL")
        raw = psycopg.connect(_database_url(database), prepare_threshold=None, autocommit=False)
        raw.execute("CREATE SCHEMA u5d")
        raw.execute("SET search_path TO u5d")
        pg_schema.provision_pg_schema(raw)
        raw.commit()
        yield app_db._PostgresConnectionAdapter(raw)
    finally:
        if raw is not None:
            raw.close()
        if created:
            assert database.startswith(DISPOSABLE_DATABASE_PREFIX)
            assert database not in PROTECTED_DATABASES
            admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        admin.close()


@real_pg
def test_epg1_helper_is_immutable_non_strict_and_validated(real_pg_connection):
    conn = real_pg_connection
    assert conn.execute("SHOW server_encoding").fetchone()[0] == "UTF8"
    volatility, strict = conn.execute(
        "SELECT provolatile, proisstrict FROM pg_catalog.pg_proc WHERE proname = ?",
        (PG_HELPER_FUNCTION,),
    ).fetchone()
    assert (volatility, strict) == ("i", False)
    pg_schema.validate_pg_schema(conn)


@real_pg
def test_epg1_helper_equals_human_text_key(real_pg_connection):
    conn = real_pg_connection
    # The whole frozen domain (every assigned code point up to U+10FFFF, incl.
    # supplementary marks such as U+E0100-U+E01EF), batched: ~58 round trips.
    values = [v for v in _fold_corpus() if v is None or "\x00" not in v]
    values += [chr(cp) for cp in range(1, 0x110000) if unicodedata.category(chr(cp)) not in ("Cn", "Cs")]
    mismatches = []
    for start in range(0, len(values), 5000):
        batch = values[start:start + 5000]
        rows = conn.execute(
            f"SELECT {PG_HELPER_FUNCTION}(v) FROM unnest(CAST(? AS text[])) WITH ORDINALITY AS x(v, n) ORDER BY n",
            (batch,),
        ).fetchall()
        mismatches += [(v, row[0]) for v, row in zip(batch, rows) if row[0] != human_text_key(v)]
    assert mismatches[:20] == []


@real_pg
def test_epg1_helper_supplementary_and_multi_character_discriminators(real_pg_connection):
    """Targeted real-PG cases that a truncated or server-normalized helper
    would get wrong: supplementary marks inside words, supplementary 1:1
    mappings, Unicode 15.0 additions, Hangul, long expansions, NULL."""
    conn = real_pg_connection
    cases = list(UNICODE_DISCRIMINATORS) + [
        "a" + "".join(chr(cp) for cp in range(0xE0100, 0xE01F0)) + "b",
        "x\U0001D7CE\U0001D7FFy",
    ]
    for value in cases:
        got = conn.execute(f"SELECT {PG_HELPER_FUNCTION}(?)", (value,)).fetchone()[0]
        assert got == human_text_key(value), ascii(value)
    assert conn.execute(f"SELECT {PG_HELPER_FUNCTION}(NULL)").fetchone()[0] == ""


def _real_pg_table(conn, values, column):
    conn.execute(f"CREATE TEMP TABLE IF NOT EXISTS u5d_src (id integer PRIMARY KEY, {column} text)")
    conn.execute("TRUNCATE u5d_src")
    for index, value in enumerate(values, start=1):
        conn.execute(f"INSERT INTO u5d_src (id, {column}) VALUES (?, ?)", (index, value))


@real_pg
@pytest.mark.parametrize(("expression", "direction"), sorted(EXPECTED_HUMAN_ORDER))
def test_epg1_human_order_equals_sqlite(real_pg_connection, expression, direction):
    conn = real_pg_connection
    _real_pg_table(conn, ORDER_FIXTURE, "nome")
    fragment = _invoke(_owner("human_order"), conn, expression)
    rows = conn.execute(f"SELECT nome FROM u5d_src AS a ORDER BY {fragment} {direction}, id").fetchall()
    assert [row[0] for row in rows] == EXPECTED_HUMAN_ORDER[(expression, direction)]


@real_pg
def test_epg1_database_collation_is_not_c_for_the_order_proof(real_pg_connection):
    collate = real_pg_connection.execute(
        "SELECT datcollate FROM pg_catalog.pg_database WHERE datname = current_database()"
    ).fetchone()[0]
    if collate in ("C", "POSIX", "C.UTF-8", "C.utf8"):
        pytest.skip(f"server offers no non-C locale ({collate}); default-collation independence unproven")
    rows = real_pg_connection.execute(
        "SELECT x FROM unnest(ARRAY['anabela', 'ana maria']) AS t(x) ORDER BY x"
    ).fetchall()
    # Precondition: the default collation really differs from code-point order.
    assert [r[0] for r in rows] != ["ana maria", "anabela"], collate


@real_pg
@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_epg1_nocase_order_equals_sqlite(real_pg_connection, direction):
    conn = real_pg_connection
    _real_pg_table(conn, NOCASE_FIXTURE, "grupo")
    fragment = _invoke(_owner("nocase_order"), conn, "grupo")
    rows = conn.execute(f"SELECT grupo FROM u5d_src ORDER BY {fragment} {direction}, id").fetchall()
    assert [row[0] for row in rows] == EXPECTED_NOCASE_ORDER[direction]


@real_pg
def test_epg1_human_contains_equals_sqlite(real_pg_connection):
    conn = real_pg_connection
    fragment = _invoke(_owner("human_contains"), conn, "a.nome")
    for haystack, query, expected in CONTAINS_CASES:
        _real_pg_table(conn, [haystack], "nome")
        got = conn.execute(f"SELECT {fragment} FROM u5d_src AS a", (human_text_key(query),)).fetchone()[0]
        assert bool(got) is expected, (haystack, query)


@real_pg
def test_epg1_technical_like_equals_sqlite(real_pg_connection):
    conn = real_pg_connection
    fragment = _invoke(_owner("technical_like"), conn, "u.email")
    for value in LIKE_VALUES:
        _real_pg_table(conn, [value], "email")
        for pattern in LIKE_PATTERNS:
            got = conn.execute(f"SELECT {fragment} FROM u5d_src AS u", (pattern,)).fetchone()[0]
            assert bool(got) is _legacy_sqlite_like(value, pattern), (value, pattern)
