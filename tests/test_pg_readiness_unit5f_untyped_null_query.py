# coding: utf-8
"""PostgreSQL-readiness Unit 5-F: untyped-NULL query portability (finding R3).

``admin_acesso_salvar`` checks e-mail uniqueness with::

    SELECT id FROM usuarios WHERE LOWER(email) = LOWER(?) AND (? IS NULL OR id <> ?)

bound as ``(email, usuario_id, usuario_id)``.  On CREATE ``usuario_id`` is
``None``.  psycopg 3 sends ``None`` with no type OID, and the second
placeholder's only SQL context is ``$n IS NULL`` -- PostgreSQL cannot infer a
type for it and rejects the statement with SQLSTATE 42P18 ("could not determine
data type of parameter $2").  On EDIT the value is a Python ``int``, which
psycopg sends typed, so the same text is accepted.

Business contract frozen here (independent of the SQL spelling):

* CREATE -- the e-mail must be unique against EVERY existing ``usuarios`` row;
  no exclusion predicate applies and no parameter is bound to decide that.
* EDIT -- the e-mail must be unique against every row EXCEPT the one being
  edited (``id <> <edited id>``, bound as the integer id).

The fix must remove the untyped NULL parameter position itself, so its
correctness does not depend on observing 42P18 live.  Casts, ``COALESCE``
tricks, dummy integers and engine-specific duplicated queries are not the
contract; the assertions below pin semantics over the relevant fragment and
parameters, never the whole SQL string.

Evidence classes (TEP section 4): the PostgreSQL-shaped cases are NOT
PostgreSQL proof.  The test-local double translates the runtime SQL with the
production ``adapt_sql_for_postgres`` and raises a 42P18-shaped error exactly
where PostgreSQL would for this defect class (a ``%s IS [NOT] NULL``
placeholder bound to ``None``); everything else runs on the wrapped SQLite
engine.  REAL-PG EVIDENCE: ABSENT (route-level smoke owed to E-PG1).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import main  # noqa: F401  (canonical runtime; conftest redirects APP_DATABASE)
from app import db as app_db
from app.db import adapt_sql_for_postgres
from tests.canonical_request_test_support import login_admin
from tests.pg_shaped_support import PostgresShapedConnection
from tests.versioned_test_support import isolated_versioned_app_env

REPO_ROOT = Path(__file__).resolve().parents[1]
SAVE_ROUTE = "/admin/acesso/salvar"
DUPLICATE_EMAIL_MESSAGE = "Já existe um usuário com este e-mail."

#: A placeholder whose only SQL context is ``IS [NOT] NULL``.
_UNTYPED_NULL_CONTEXT_RE = re.compile(r"\s*\)?\s*IS\s+(?:NOT\s+)?NULL\b", re.IGNORECASE)
#: The row-exclusion predicate on the ``usuarios`` primary key.
_ID_EXCLUSION_RE = re.compile(r"(?<![\w.])(?:\w+\.)?id\s*(?:<>|!=)\s*$", re.IGNORECASE)
_ANY_ID_EXCLUSION_RE = re.compile(r"(?<![\w.])(?:\w+\.)?id\s*(?:<>|!=)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# PostgreSQL-shaped double
# ---------------------------------------------------------------------------


class PgUndeterminedParameterType(Exception):
    """Emulates psycopg ``IndeterminateDatatype`` (SQLSTATE 42P18)."""

    sqlstate = "42P18"


def _placeholders(pg_sql):
    """Yield ``(ordinal, end_offset)`` of every ``%s`` in psycopg pyformat SQL."""
    ordinal = 0
    index = 0
    length = len(pg_sql)
    while index < length:
        if pg_sql.startswith("%%", index):
            index += 2
            continue
        if pg_sql.startswith("%s", index):
            yield ordinal, index, index + 2
            ordinal += 1
            index += 2
            continue
        index += 1


def untyped_null_positions(pg_sql, params):
    """Ordinals of placeholders PostgreSQL could not type (42P18 class).

    A placeholder is untyped when its only context is ``%s IS [NOT] NULL`` and
    the bound value is ``None`` (psycopg sends ``None`` without a type OID).
    """
    values = tuple(params or ())
    positions = []
    for ordinal, _start, end in _placeholders(pg_sql):
        if not _UNTYPED_NULL_CONTEXT_RE.match(pg_sql, end):
            continue
        if ordinal < len(values) and values[ordinal] is None:
            positions.append(ordinal)
    return positions


def is_null_placeholder_positions(pg_sql):
    """Ordinals of placeholders used as ``%s IS [NOT] NULL`` whatever the value."""
    return [
        ordinal
        for ordinal, _start, end in _placeholders(pg_sql)
        if _UNTYPED_NULL_CONTEXT_RE.match(pg_sql, end)
    ]


def id_exclusion_ordinals(pg_sql):
    """Ordinals of placeholders compared as ``[alias.]id <> %s``."""
    return [
        ordinal
        for ordinal, start, _end in _placeholders(pg_sql)
        if _ID_EXCLUSION_RE.search(pg_sql[:start])
    ]


class PgShapedUntypedNullConnection(PostgresShapedConnection):
    """PG-shaped double that rejects untyped NULL parameters like PostgreSQL.

    ``strict=False`` records violations without raising, which lets a control
    prove that the untyped NULL is the ONLY PostgreSQL-shaped obstacle on the
    route (login, RBAC, fixtures and the rest of the save path all run).
    """

    def __init__(self, real, *, strict=True, **kwargs):
        super().__init__(real, **kwargs)
        self.strict = strict
        self.pg_statements = []
        self.untyped_null = []

    def execute(self, sql, params=None):
        text = str(sql)
        pg_sql = adapt_sql_for_postgres(text)
        self.pg_statements.append((pg_sql, tuple(params) if params is not None else None))
        if "pg_catalog.pg_class" in text and "relname" in text:
            self._status = "INTRANS"
            return self._real.execute(
                "SELECT name AS relname FROM sqlite_master WHERE type='table'"
            )
        positions = untyped_null_positions(pg_sql, params)
        if positions:
            self.untyped_null.append((pg_sql, tuple(params or ()), positions))
            if self.strict and self._status != "INERROR":
                self._status = "INERROR"
                raise PgUndeterminedParameterType(
                    f"42P18 could not determine data type of parameter "
                    f"${positions[0] + 1}: {pg_sql}"
                )
        return super().execute(sql, params)


# ---------------------------------------------------------------------------
# Fixture and route helpers
# ---------------------------------------------------------------------------

EDIT_TARGET_EMAIL = "u5f.edit.alvo@example.test"
OTHER_EMAIL = "u5f.outro@example.test"


def _seed(conn):
    from app.user_accounts import create_usuario_with_access_level

    password_hash = main.hash_password("u5f-senha")
    ids = {}
    for key, nome, email in (
        ("target", "U5F Alvo", EDIT_TARGET_EMAIL),
        ("other", "U5F Outro", OTHER_EMAIL),
    ):
        cursor = create_usuario_with_access_level(
            conn, nome, email, password_hash, "admin", "admin_total",
            credential_state="personal",
        )
        ids[key] = int(cursor.usuario_id)
    conn.commit()
    return ids


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "u5f-untyped-null.db") as environment:
        with main.app.app_context():
            environment["ids"] = _seed(main.get_db_connection())
            main.close_db_connection(None)
        login_admin(environment["client"])
        yield environment


def _usuarios_by_email(email):
    with main.app.app_context():
        try:
            rows = main.get_db_connection().execute(
                "SELECT id, nome FROM usuarios WHERE LOWER(email) = LOWER(?) ORDER BY id",
                (email,),
            ).fetchall()
            return [(int(row["id"]), row["nome"]) for row in rows]
        finally:
            main.close_db_connection(None)


def _usuario(usuario_id):
    with main.app.app_context():
        try:
            row = main.get_db_connection().execute(
                "SELECT nome, email FROM usuarios WHERE id = ?", (usuario_id,)
            ).fetchone()
            return (row["nome"], row["email"]) if row else None
        finally:
            main.close_db_connection(None)


def _usuarios_count():
    with main.app.app_context():
        try:
            return main.get_db_connection().execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        finally:
            main.close_db_connection(None)


def _form(nome, email, usuario_id=None):
    data = {"nome": nome, "email": email, "nivel_acesso": "admin_total", "senha": ""}
    if usuario_id is not None:
        data["usuario_id"] = str(usuario_id)
    return data


def _post_on_pg_shaped_path(environment, monkeypatch, data, *, strict=True):
    """POST the save route with every request connection on the PG-shaped double."""
    import app.views.admin.acesso as acesso

    client = environment["client"]
    with main.app.app_context():
        main.close_db_connection(None)
        real = main.get_db_connection()
        pg = PgShapedUntypedNullConnection(real, strict=strict)

        def provider():
            from flask import g

            g.db = pg
            return pg

        with monkeypatch.context() as patch:
            patch.setattr(app_db, "get_db_connection", provider)
            patch.setattr(acesso, "get_db_connection", provider)
            error = None
            response = None
            try:
                response = client.post(SAVE_ROUTE, data=data)
            except Exception as exc:  # TESTING propagates handler exceptions
                error = exc
            finally:
                main.close_db_connection(None)
    return pg, response, error


def _email_uniqueness_statements(pg, email):
    """The ``usuarios`` e-mail uniqueness probe(s) the save route executed.

    Located semantically: a single-table ``SELECT`` over ``usuarios`` whose
    WHERE compares ``email`` and which binds the submitted e-mail.  The
    revoked-identity lookup (a JOIN) and the root-admin probes (other e-mail
    values) are not matched.
    """
    found = []
    for pg_sql, params in pg.pg_statements:
        if not re.match(r"\s*SELECT\b", pg_sql, re.IGNORECASE):
            continue
        if not re.search(r"\bFROM\s+usuarios\b", pg_sql, re.IGNORECASE):
            continue
        if re.search(r"\bJOIN\b", pg_sql, re.IGNORECASE):
            continue
        where = re.split(r"\bWHERE\b", pg_sql, maxsplit=1, flags=re.IGNORECASE)
        if len(where) < 2 or "email" not in where[1].lower():
            continue
        if email not in tuple(params or ()):
            continue
        found.append((pg_sql, tuple(params or ())))
    return found


def _describe(pg):
    return [(sql[:200], params) for sql, params in pg.pg_statements]


# ---------------------------------------------------------------------------
# Harness discrimination controls (GREEN today, GREEN after U5-F)
# ---------------------------------------------------------------------------


def test_detector_discriminates_bad_and_good_shapes():
    bad = adapt_sql_for_postgres(
        "SELECT id FROM usuarios WHERE LOWER(email) = LOWER(?) AND (? IS NULL OR id <> ?)"
    )
    good_create = adapt_sql_for_postgres(
        "SELECT id FROM usuarios WHERE LOWER(email) = LOWER(?)"
    )
    good_edit = adapt_sql_for_postgres(
        "SELECT id FROM usuarios WHERE LOWER(email) = LOWER(?) AND id <> ?"
    )
    # BAD: None bound to a placeholder whose only context is IS NULL.
    assert untyped_null_positions(bad, ("a@x.test", None, None)) == [1]
    # The same text is typed when the value is an int (why EDIT survives today).
    assert untyped_null_positions(bad, ("a@x.test", 7, 7)) == []
    assert is_null_placeholder_positions(bad) == [1]
    # GOOD CREATE / GOOD EDIT.
    assert untyped_null_positions(good_create, ("a@x.test",)) == []
    assert is_null_placeholder_positions(good_create) == []
    assert id_exclusion_ordinals(good_create) == []
    assert id_exclusion_ordinals(good_edit) == [1]
    assert id_exclusion_ordinals(bad) == [2]
    # A column IS NULL (typed by the column) is not the defect class.
    typed = adapt_sql_for_postgres(
        "SELECT id FROM alunos WHERE matricula = ? AND (usuario_id IS NULL OR usuario_id <> ?)"
    )
    assert untyped_null_positions(typed, ("M1", None)) == []
    assert is_null_placeholder_positions(typed) == []
    # Literal percent and quoted '?' are not placeholders.
    quoted = adapt_sql_for_postgres("SELECT '? IS NULL', 'a%' WHERE x = ?")
    assert list(_placeholders(quoted)) == [(0, quoted.rindex("%s"), len(quoted))]


def test_pg_shaped_create_path_has_no_other_obstacle(env, monkeypatch):
    """Record-only mode: the route completes on the PG-shaped path.

    Proves login, RBAC, the fixture, the ensure/schema probes and the rest of
    the CREATE write path all run on the double, so a strict-mode failure can
    only be the untyped NULL.  Today the recorder sees exactly the uniqueness
    probe; after U5-F it sees nothing.
    """
    email = "u5f.novo.controle@example.test"
    pg, response, error = _post_on_pg_shaped_path(
        env, monkeypatch, _form("U5F Controle", email), strict=False
    )
    assert error is None, repr(error)
    assert response is not None and response.status_code == 302
    assert len(_usuarios_by_email(email)) == 1
    uniqueness = _email_uniqueness_statements(pg, email)
    assert len(uniqueness) == 1, _describe(pg)
    assert all(sql == uniqueness[0][0] for sql, _params, _pos in pg.untyped_null)


# ---------------------------------------------------------------------------
# RED -- PostgreSQL-shaped CREATE path
# ---------------------------------------------------------------------------


def test_pg_shaped_create_binds_no_untyped_null(env, monkeypatch):
    email = "u5f.novo@example.test"
    pg, response, error = _post_on_pg_shaped_path(env, monkeypatch, _form("U5F Novo", email))

    uniqueness = _email_uniqueness_statements(pg, email)
    assert len(uniqueness) == 1, ("CREATE must reach the uniqueness probe once", _describe(pg))
    pg_sql, params = uniqueness[0]

    # No placeholder exists only to be tested with IS [NOT] NULL ...
    assert is_null_placeholder_positions(pg_sql) == [], pg_sql
    # ... and None is never bound to select whether the exclusion applies.
    assert None not in params, (pg_sql, params)
    # CREATE checks every existing row: no row-exclusion predicate at all.
    assert not _ANY_ID_EXCLUSION_RE.search(pg_sql), pg_sql
    assert len(list(_placeholders(pg_sql))) == len(params), (pg_sql, params)
    # Nothing on the route reached PostgreSQL with an untyped NULL.
    assert pg.untyped_null == [], pg.untyped_null

    assert error is None, repr(error)
    assert response is not None and response.status_code == 302
    assert len(_usuarios_by_email(email)) == 1


def test_pg_shaped_create_still_rejects_duplicate_email(env, monkeypatch):
    before = _usuarios_count()
    pg, response, error = _post_on_pg_shaped_path(
        env, monkeypatch, _form("U5F Duplicado", OTHER_EMAIL.upper())
    )

    uniqueness = _email_uniqueness_statements(pg, OTHER_EMAIL)
    assert len(uniqueness) == 1, _describe(pg)
    assert pg.untyped_null == [], pg.untyped_null
    assert error is None, repr(error)
    assert response is not None and response.status_code == 302
    assert _usuarios_count() == before
    with env["client"].session_transaction() as session:
        flashes = [message for _category, message in session.get("_flashes", [])]
    assert DUPLICATE_EMAIL_MESSAGE in flashes, flashes


# ---------------------------------------------------------------------------
# EDIT control (PostgreSQL-shaped; GREEN today)
# ---------------------------------------------------------------------------


def test_pg_shaped_edit_excludes_only_the_edited_row(env, monkeypatch):
    target = env["ids"]["target"]
    pg, response, error = _post_on_pg_shaped_path(
        env, monkeypatch, _form("U5F Alvo Editado", EDIT_TARGET_EMAIL, usuario_id=target)
    )

    uniqueness = _email_uniqueness_statements(pg, EDIT_TARGET_EMAIL)
    assert len(uniqueness) == 1, _describe(pg)
    pg_sql, params = uniqueness[0]
    exclusion = id_exclusion_ordinals(pg_sql)
    assert exclusion, ("EDIT must exclude the edited row", pg_sql)
    for ordinal in exclusion:
        assert type(params[ordinal]) is int and params[ordinal] == target, (pg_sql, params)
    assert None not in params, (pg_sql, params)
    assert pg.untyped_null == [], pg.untyped_null

    assert error is None, repr(error)
    assert response is not None and response.status_code == 302
    assert _usuario(target) == ("U5F Alvo Editado", EDIT_TARGET_EMAIL)


def test_pg_shaped_edit_still_rejects_another_users_email(env, monkeypatch):
    target = env["ids"]["target"]
    pg, response, error = _post_on_pg_shaped_path(
        env, monkeypatch, _form("U5F Alvo Colisao", OTHER_EMAIL, usuario_id=target)
    )
    assert len(_email_uniqueness_statements(pg, OTHER_EMAIL)) == 1, _describe(pg)
    assert pg.untyped_null == [], pg.untyped_null
    assert error is None, repr(error)
    assert response is not None and response.status_code == 302
    assert _usuario(target) == ("U5F Alvo", EDIT_TARGET_EMAIL)


# ---------------------------------------------------------------------------
# SQLite controls (the canonical engine's business behaviour is preserved)
#
# CREATE-duplicate on SQLite is owned by
# tests/test_ut9_acesso_blueprint.py::test_access_save_rejects_duplicate_email_atomically.
# No existing owner pins the EDIT pair on the save route, so it lives here.
# ---------------------------------------------------------------------------


def test_sqlite_edit_keeping_own_email_is_accepted(env):
    target = env["ids"]["target"]
    response = env["client"].post(
        SAVE_ROUTE, data=_form("U5F Alvo SQLite", EDIT_TARGET_EMAIL, usuario_id=target)
    )
    assert response.status_code == 302
    assert _usuario(target) == ("U5F Alvo SQLite", EDIT_TARGET_EMAIL)


def test_sqlite_edit_to_another_users_email_is_rejected(env):
    target = env["ids"]["target"]
    response = env["client"].post(
        SAVE_ROUTE,
        data=_form("U5F Alvo Colisao", OTHER_EMAIL, usuario_id=target),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert DUPLICATE_EMAIL_MESSAGE in response.get_data(as_text=True)
    assert _usuario(target) == ("U5F Alvo", EDIT_TARGET_EMAIL)


# ---------------------------------------------------------------------------
# RED -- production SQL carries no ``? IS [NOT] NULL`` placeholder
# ---------------------------------------------------------------------------


def _production_sql_literals():
    for path in sorted((REPO_ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                yield path.relative_to(REPO_ROOT).as_posix(), node.lineno, node.value


def test_production_sql_has_no_placeholder_is_null_predicate():
    offenders = [
        (path, lineno, " ".join(text.split())[:160])
        for path, lineno, text in _production_sql_literals()
        if is_null_placeholder_positions(adapt_sql_for_postgres(text))
    ]
    assert offenders == [], offenders
