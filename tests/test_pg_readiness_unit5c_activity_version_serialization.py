# coding: utf-8
"""PostgreSQL-readiness Unit 5-C: activity-version MAX+1 serialization.

Unit 4 gave activity-version *deletes* a per-base lock (``lock_activity_base``:
SQLite ``BEGIN IMMEDIATE``, PostgreSQL ``FOR NO KEY UPDATE`` on the parent
``atividade_base`` row).  It deliberately did not couple the automatic version
*creators* to that lock, so two concurrent creators of the same base could both
read ``MAX(numero_versao) = N`` and both try to insert ``N + 1``; a delete and a
create could also interleave their read-check-write around the same version set.

Unit 5-C closes that gap: every normal automatic creator must (1) own a write
transaction, (2) take the same per-base row lock the delete path already takes,
(3) only then read ``MAX(numero_versao)``, and (4) only then insert.  The lock
domain stays per ``atividade_base`` row, so unrelated bases never contend.

For multi-target operations the shared-resource total order is group definition
``(tipo_atividade, int(numero))`` ascending, then all existing base ids ascending,
then version mutations. Payload processing order is deliberately independent.

All PostgreSQL behaviour is modelled by ``tests.pg_shaped_support``: a real
SQLite row engine behind psycopg 3 transaction-state semantics, the PostgreSQL
row-lock conflict matrix and XID assignment.  That double records the statement
order but is NOT a scheduler: it raises instead of waiting, so these tests pin
the ordering of acquisitions, they do not claim real blocking timing.  Real
PostgreSQL blocking/deadlock validation belongs to the consolidated real-PG
pass.
"""
from __future__ import annotations

import inspect
import re
import sqlite3
import sys
import types
import uuid

import pytest

import main
from app import activity_catalog
from app import db as app_db
from app.activity_catalog import (
    apply_activity_version_semantic_changes,
    apply_latest_activity_version_semantic_changes,
    delete_activity_version,
    get_latest_atividade_versao_for_base,
    get_next_numero_versao,
    rename_current_activity_group_versions,
)
from app.prod1_schema import bootstrap_prod1_schema
from tests.pg_shaped_support import (
    MODE_NO_KEY_UPDATE,
    PostgresLockBlocked,
    PostgresShapedConnection,
)
from tests.session_support import existing_admin_user_id, stamp_auth_version
from tests.versioned_test_support import isolated_versioned_app_env

_BASE_LOCK_RE = re.compile(r"FOR\s+NO\s+KEY\s+UPDATE", re.IGNORECASE)
_MAX_RE = re.compile(r"MAX\s*\(\s*NUMERO_VERSAO\s*\)", re.IGNORECASE)
_VERSION_INSERT_RE = re.compile(r"INSERT\s+INTO\s+ATIVIDADE_VERSAO", re.IGNORECASE)
_VERSION_DESTRUCTIVE_RE = re.compile(
    r"(?:UPDATE|DELETE\s+FROM|INSERT\s+INTO)\s+ATIVIDADE_(?:VERSAO|TRANSICAO)",
    re.IGNORECASE,
)
_XID_PROBE_RE = re.compile(r"pg_current_xact_id_if_assigned", re.IGNORECASE)


def _require(name):
    value = getattr(app_db, name, None)
    assert value is not None, f"app.db.{name} is not implemented yet"
    return value


def _bootstrap_connection(tmp_path, name, *, timeout=0):
    conn = sqlite3.connect(tmp_path / name, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _seed_base_with_versions(conn, statuses, numbers=None, *, chained=False):
    """Seed one base; returns ``(base_id, [version_ids])``."""
    statuses = list(statuses)
    numbers = (
        list(numbers)
        if numbers is not None
        else list(range(1, len(statuses) + 1))
    )
    base_id = conn.execute(
        "INSERT INTO atividade_base(nome_conceito,status) VALUES(?,'ativo') RETURNING id",
        (f"U5C Base {uuid.uuid4().hex[:10]}",),
    ).fetchone()[0]
    version_ids = []
    for status, number in zip(statuses, numbers):
        predecessor = version_ids[-1] if chained and version_ids else None
        version_ids.append(
            conn.execute(
                "INSERT INTO atividade_versao"
                "(atividade_base_id,eixo,grupo,numero_versao,status,versao_anterior_id) "
                "VALUES(?,'AAC','1 - U5C',?,?,?) RETURNING id",
                (base_id, number, status, predecessor),
            ).fetchone()[0]
        )
    conn.commit()
    return base_id, version_ids


def _first_index(connection, predicate):
    for index, (sql, _params) in enumerate(connection.statements):
        if predicate(sql):
            return index
    return None


def _last_index_before(connection, predicate, bound):
    found = None
    for index, (sql, _params) in enumerate(connection.statements):
        if index >= bound:
            break
        if predicate(sql):
            found = index
    return found


def _joined(connection):
    return " ".join(sql for sql, _params in connection.statements).upper()


def _is_base_lock(sql):
    return bool(_BASE_LOCK_RE.search(sql))


def _is_max(sql):
    return bool(_MAX_RE.search(sql))


def _is_version_insert(sql):
    return bool(_VERSION_INSERT_RE.search(sql))


def _is_destructive(sql):
    return bool(_VERSION_DESTRUCTIVE_RE.search(sql))


def _login_admin(client):
    with client.session_transaction() as session:
        session.update(
            user_id=existing_admin_user_id(), user_type="admin", user_name="Admin U5C"
        )
        stamp_auth_version(session)


def _install_fake_connection(monkeypatch, fake, *modules):
    def provider():
        from flask import g

        g.db = fake
        return fake

    monkeypatch.setattr(app_db, "get_db_connection", provider)
    for module in modules:
        monkeypatch.setattr(module, "get_db_connection", provider)


def _nova_versao_form(conn, base_id, predecessor_id):
    base = conn.execute(
        "SELECT nome_conceito, descricao FROM atividade_base WHERE id=?", (base_id,)
    ).fetchone()
    return {
        "nome": base["nome_conceito"],
        "descricao": base["descricao"] or "",
        "tipo_atividade": "Acadêmica Complementar",
        "grupo": "1 - Nova versão U5C",
        "tipo_limitacao": "total",
        "limite_valor": "88",
        "ch_por_evento_mode": "enabled",
        "ch_por_evento": "6",
        "observacoes": "Nova versão U5-C",
        "versao_anterior_id": str(predecessor_id),
    }


def _assert_lock_before_allocation(connection, *, base_id):
    """The allocation MAX+1 and INSERT must both follow the base-row lock."""
    lock_index = _first_index(connection, _is_base_lock)
    insert_index = _first_index(connection, _is_version_insert)
    assert lock_index is not None, "creator never took the base-row lock"
    assert insert_index is not None, "creator never inserted a version"
    assert lock_index < insert_index
    # The MAX read that feeds the INSERT is the one under the lock; an earlier
    # display-only MAX read (form title) is allowed to precede the lock.
    max_index = _last_index_before(connection, _is_max, insert_index)
    assert max_index is not None, "creator never computed MAX(numero_versao)"
    assert lock_index < max_index < insert_index
    assert ("atividade_base", base_id) in connection.locks
    assert connection.failed_statements == []
    assert "BEGIN IMMEDIATE" not in _joined(connection)


class _CallbackPostgresConnection(PostgresShapedConnection):
    """Run one scheduler-free assertion immediately before matching SQL."""

    def __init__(self, real, *, predicate, callback, **kwargs):
        super().__init__(real, **kwargs)
        self._predicate = predicate
        self._callback = callback

    def execute(self, sql, params=None):
        callback = self._callback
        if callback is not None and self._predicate(str(sql)):
            self._callback = None
            callback(str(sql))
        return super().execute(sql, params)


class _ActivityLockGraph:
    """First-acquisition edges across transactions; duplicates add no edge."""

    def __init__(self):
        self.edges = set()

    def assert_acyclic(self):
        pending = {}
        for source, target in self.edges:
            pending.setdefault(source, set()).add(target)
            pending.setdefault(target, set())
        while pending:
            leaves = {node for node, successors in pending.items() if not successors}
            assert leaves, f"lock-order cycle: {self.edges!r}"
            pending = {
                node: successors - leaves
                for node, successors in pending.items() if node not in leaves
            }


class _ActivityOrderConnection(PostgresShapedConnection):
    """Record group UPDATE/INSERT locks and base locks on existing test rows.

    This models acquisition order, including implicit DML locks; it doesn't
    simulate deadlock scheduling or reserve missing PostgreSQL rows.
    """

    def __init__(self, real, *, graph, **kwargs):
        super().__init__(real, **kwargs)
        self.graph = graph
        self.events = []
        self._acquisition_order = []

    def _acquire(self, key, mode):
        super()._acquire(key, mode)
        if key not in self._acquisition_order:
            for held in self._acquisition_order:
                self.graph.edges.add((held, key))
            self._acquisition_order.append(key)
            self.events.append(("LOCK", key))

    def _release_locks(self):
        super()._release_locks()
        self._acquisition_order = []

    def execute(self, sql, params=None):
        if re.match(r"\s*UPDATE\s+grupos_def\b", sql, re.I):
            self._acquire(("grupos_def", (params[-2], int(params[-1]))), MODE_NO_KEY_UPDATE)
        elif re.match(r"\s*INSERT\s+INTO\s+grupos_def\b", sql, re.I):
            self._acquire(("grupos_def", (params[0], int(params[1]))), MODE_NO_KEY_UPDATE)
        if _is_destructive(sql):
            self.events.append(("MUTATE_VERSION", None))
        if re.match(r"\s*INSERT\s+INTO\s+atividade_versao\b", sql, re.I):
            self.events.append(("INSERT_VERSION_BASE", int(params[0])))
        return super().execute(sql, params)


def _import_row(base_id, group=1, *, axis="AAC", description="Imported"):
    tipo = "Acadêmica Complementar" if axis == "AAC" else "Extensão Universitária"
    return {
        "action": "update", "existing_id": base_id, "tipo_atividade": tipo,
        "grupo_numero": str(group), "grupo_descricao": description,
        "grupo": f"{group} - {description}",
        "limite_horas_total": 77, "limite_horas_semestral": None,
    }


def _run_order_route(real, monkeypatch, graph, *, rows=None, group=1, axis="AAC"):
    """Exercise the production handler and its transaction, bypassing only auth."""
    import app.views.admin.atividades as atividades_module

    pg = _ActivityOrderConnection(real, graph=graph)
    monkeypatch.setattr(atividades_module, "_ensure_grupos_def_table", lambda _conn: None)
    if rows is not None:
        payload = {"rows": rows, "csv_relpath": None}
        monkeypatch.setattr(atividades_module, "_load_atividades_import_preview", lambda _key: payload)
        monkeypatch.setattr(atividades_module, "_delete_atividades_import_preview", lambda _key: None)
        monkeypatch.setattr(atividades_module, "_delete_upload_relpath", lambda _path: None)
        with main.app.test_request_context(method="POST", data={"preview_key": "order"}):
            _install_fake_connection(monkeypatch, pg, atividades_module)
            response = atividades_module.admin_atividades_importar_confirmar.__wrapped__()
            assert response.status_code in (302, 303)
            assert pg.commits == 1 and pg.rollbacks == 0
    else:
        tipo = "Acadêmica Complementar" if axis == "AAC" else "Extensão Universitária"
        with main.app.test_request_context(
            method="POST", json={"tipo_atividade": tipo, "numero": str(group), "descricao": "Renamed"}
        ):
            _install_fake_connection(monkeypatch, pg, atividades_module)
            response = atividades_module.admin_grupos_renomear.__wrapped__()
            assert response.status_code == 200 and response.get_json()["ok"] is True
            assert pg.commits == 1 and pg.rollbacks == 0
    return pg.events


def _seed_order_database(tmp_path, name, *, groups=(1,), axis="AAC"):
    real = _bootstrap_connection(tmp_path, name)
    a, (_v1,) = _seed_base_with_versions(real, ["ativa"])
    b, (_v2,) = _seed_base_with_versions(real, ["ativa"])
    real.execute("UPDATE atividade_versao SET eixo=?", (axis,))
    tipo = "Acadêmica Complementar" if axis == "AAC" else "Extensão Universitária"
    for group in groups:
        real.execute(
            "INSERT INTO grupos_def(tipo_atividade,numero,descricao) VALUES(?,?,?)",
            (tipo, group, "Original"),
        )
    real.commit()
    return real, a, b


def _locks(events):
    return [key for event, key in events if event == "LOCK"]


def test_opposite_import_payloads_use_same_global_lock_order(tmp_path, monkeypatch):
    graph = _ActivityLockGraph()
    streams = []
    for reverse in (False, True):
        real, a, b = _seed_order_database(tmp_path, f"u5c-order-import-{reverse}.db")
        ids = [b, a] if reverse else [a, b]
        streams.append(_run_order_route(real, monkeypatch, graph, rows=[_import_row(i) for i in ids]))
    graph.assert_acyclic()
    expected = [("grupos_def", ("Acadêmica Complementar", 1)), ("atividade_base", a), ("atividade_base", b)]
    assert _locks(streams[0]) == _locks(streams[1]) == expected
    for events in streams:
        first_mutation = next(i for i, (event, _key) in enumerate(events) if event == "MUTATE_VERSION")
        assert all(events.index(("LOCK", key)) < first_mutation for key in expected)


@pytest.mark.parametrize("single_base", [False, True])
def test_import_and_rename_share_group_then_base_order(tmp_path, monkeypatch, single_base):
    graph = _ActivityLockGraph()
    real, a, b = _seed_order_database(tmp_path, "u5c-order-cross-import.db")
    imported = _run_order_route(
        real, monkeypatch, graph, rows=[_import_row(a)] if single_base else [_import_row(b), _import_row(a)]
    )
    real, _a, _b = _seed_order_database(tmp_path, "u5c-order-cross-rename.db")
    renamed = _run_order_route(real, monkeypatch, graph)
    graph.assert_acyclic()
    expected = [("grupos_def", ("Acadêmica Complementar", 1)), ("atividade_base", a)]
    if not single_base:
        expected.append(("atividade_base", b))
    assert _locks(imported) == [key for key in _locks(renamed) if key in expected] == expected
    first_mutation = next(i for i, (event, _key) in enumerate(renamed) if event == "MUTATE_VERSION")
    assert all(renamed.index(("LOCK", key)) < first_mutation for key in _locks(renamed))


def test_multiple_import_groups_have_stable_key_order(tmp_path, monkeypatch):
    graph = _ActivityLockGraph()
    streams = []
    for reverse in (False, True):
        real, a, b = _seed_order_database(tmp_path, f"u5c-order-groups-{reverse}.db", groups=(1, 2))
        rows = [_import_row(a, 1), _import_row(b, 2)]
        streams.append(_run_order_route(real, monkeypatch, graph, rows=list(reversed(rows)) if reverse else rows))
    graph.assert_acyclic()
    expected = [
        ("grupos_def", ("Acadêmica Complementar", 1)),
        ("grupos_def", ("Acadêmica Complementar", 2)),
        ("atividade_base", a), ("atividade_base", b),
    ]
    assert _locks(streams[0]) == _locks(streams[1]) == expected


def test_graph_rejects_opposite_acquisitions():
    graph = _ActivityLockGraph()
    graph.edges.update({("A", "B"), ("B", "A")})
    with pytest.raises(AssertionError, match="lock-order cycle"):
        graph.assert_acyclic()


def test_nonoverlapping_imports_keep_groups_and_bases_independent(tmp_path, monkeypatch):
    graph = _ActivityLockGraph()
    registry = {}
    streams = []
    connections = []
    import app.views.admin.atividades as atividades_module

    try:
        for index, group in enumerate((1, 2)):
            real, a, b = _seed_order_database(tmp_path, f"u5c-independent-{index}.db", groups=(1, 2))
            pg = _ActivityOrderConnection(real, graph=graph, lock_registry=registry)
            connections.append(pg)
            base_id = a if index == 0 else b
            # Hold the first production import's locks until both have acquired
            # theirs: same registry, disjoint real SQLite engines, no scheduler.
            monkeypatch.setattr(pg, "commit", lambda: None)
            monkeypatch.setattr(atividades_module, "_ensure_grupos_def_table", lambda _conn: None)
            monkeypatch.setattr(atividades_module, "_load_atividades_import_preview",
                                lambda _key, row=_import_row(base_id, group): {"rows": [row]})
            monkeypatch.setattr(atividades_module, "_delete_atividades_import_preview", lambda _key: None)
            monkeypatch.setattr(atividades_module, "_delete_upload_relpath", lambda _path: None)
            with main.app.test_request_context(method="POST", data={"preview_key": "independent"}):
                _install_fake_connection(monkeypatch, pg, atividades_module)
                # Teardown normally closes the owner: retain it for this probe.
                monkeypatch.setattr(pg, "close", lambda: None)
                response = atividades_module.admin_atividades_importar_confirmar.__wrapped__()
                assert response.status_code == 302
            streams.append(_locks(pg.events))
        assert set(streams[0]).isdisjoint(streams[1])
        assert all(key in registry for stream in streams for key in stream)
        graph.assert_acyclic()
    finally:
        for pg in connections:
            pg.rollback()
            pg._real.close()


def test_import_lock_order_preserves_duplicate_payload_order_and_last_description(tmp_path, monkeypatch):
    graph = _ActivityLockGraph()
    name = "u5c-order-duplicates.db"
    real, a, b = _seed_order_database(tmp_path, name, groups=(1, 2))
    rows = [_import_row(b, 2, description="First"),
            _import_row(a, 1, description="Middle"),
            _import_row(b, 2, description="Last")]
    events = _run_order_route(real, monkeypatch, graph, rows=rows)
    graph.assert_acyclic()
    assert _locks(events) == [
        ("grupos_def", ("Acadêmica Complementar", 1)),
        ("grupos_def", ("Acadêmica Complementar", 2)),
        ("atividade_base", a), ("atividade_base", b),
    ]
    # The last duplicate edits the freshly created draft, not another successor.
    assert [base for event, base in events if event == "INSERT_VERSION_BASE"] == [b, a]
    assert sum(event == "MUTATE_VERSION" for event, _key in events) == 3
    with sqlite3.connect(tmp_path / name) as check:
        assert check.execute("SELECT descricao FROM grupos_def WHERE numero=2").fetchone()[0] == "Last"
        assert check.execute(
            "SELECT grupo FROM atividade_versao WHERE atividade_base_id=? ORDER BY numero_versao", (b,)
        ).fetchall() == [("1 - U5C",), ("2 - Last",)]


def test_group_key_order_includes_type_and_integer_number(tmp_path, monkeypatch):
    graph = _ActivityLockGraph()
    real, a, b = _seed_order_database(tmp_path, "u5c-order-composite.db", groups=(2, 10))
    real.execute("UPDATE atividade_versao SET eixo='AEU' WHERE atividade_base_id=?", (b,))
    real.execute("INSERT INTO grupos_def VALUES('Extensão Universitária',1,'Original')")
    real.commit()
    rows = [_import_row(b, 1, axis="AEU"), _import_row(a, 10), _import_row(a, 2)]
    events = _run_order_route(real, monkeypatch, graph, rows=rows)
    graph.assert_acyclic()
    assert _locks(events) == [
        ("grupos_def", ("Acadêmica Complementar", 2)),
        ("grupos_def", ("Acadêmica Complementar", 10)),
        ("grupos_def", ("Extensão Universitária", 1)),
        ("atividade_base", a), ("atividade_base", b),
    ]


def test_import_new_bases_are_created_after_all_shared_locks(tmp_path, monkeypatch):
    graph = _ActivityLockGraph()
    real, a, b = _seed_order_database(tmp_path, "u5c-order-create.db", groups=())
    created = dict(_import_row(None), action="create", nome="New private base")
    events = _run_order_route(real, monkeypatch, graph,
                              rows=[_import_row(b), created, _import_row(a)])
    graph.assert_acyclic()
    assert _locks(events) == [
        ("grupos_def", ("Acadêmica Complementar", 1)),
        ("atividade_base", a), ("atividade_base", b),
    ]
    assert [base for event, base in events if event == "INSERT_VERSION_BASE"] == [b, b + 1, a]
    first_mutation = next(i for i, (event, _key) in enumerate(events) if event == "MUTATE_VERSION")
    assert all(events.index(("LOCK", key)) < first_mutation for key in _locks(events))


def test_real_psycopg_initialization_stays_idle_and_prepares_explicit_begin(monkeypatch):
    """Real driver setter/BEGIN builder, fake libpq transport: no server claim."""
    import psycopg
    from psycopg import pq

    # No SQL/transport methods exist: any attempt to execute SQL must fail.
    transport = types.SimpleNamespace(transaction_status=pq.TransactionStatus.IDLE,
                                      status=pq.ConnStatus.OK, socket=-1, finish=lambda: None)
    raw = psycopg.Connection(transport)
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: raw)
    connection = app_db._connect_postgres()
    try:
        assert raw.isolation_level == psycopg.IsolationLevel.READ_COMMITTED
        assert raw.info.transaction_status == pq.TransactionStatus.IDLE
        assert raw.autocommit is False
        assert raw._get_tx_start_command() == b"BEGIN ISOLATION LEVEL READ COMMITTED"
        assert raw.info.transaction_status == pq.TransactionStatus.IDLE
    finally:
        connection.close()


@pytest.mark.parametrize("factory", ["direct", "application"])
def test_postgres_factory_explicitly_sets_read_committed_while_idle(monkeypatch, factory):
    from psycopg import IsolationLevel

    class IdleRaw:
        def __init__(self):
            self.info = types.SimpleNamespace(transaction_status=types.SimpleNamespace(name="IDLE"))
            self.autocommit = False
            self.server_default = IsolationLevel.REPEATABLE_READ
            self._isolation_level = None
            self.settings = []
            self.query_log = []

        @property
        def isolation_level(self):
            return self._isolation_level

        @isolation_level.setter
        def isolation_level(self, level):
            assert self.info.transaction_status.name == "IDLE"
            self.settings.append(level)
            self._isolation_level = level

        def close(self):
            pass

    opened = []

    def connect(url, **kwargs):
        raw = IdleRaw()
        opened.append((url, kwargs, raw))
        return raw

    fake = types.ModuleType("psycopg")
    fake.connect = connect
    fake.IsolationLevel = IsolationLevel
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    monkeypatch.setattr(app_db, "DATABASE_URL", "postgresql://test.invalid/u5c")
    with main.app.app_context():
        app_db.close_db_connection(None)
        connection = app_db._connect_postgres() if factory == "direct" else app_db.get_db_connection()
        try:
            raw = opened[0][2]
            assert raw.settings == [IsolationLevel.READ_COMMITTED]
            assert raw.isolation_level != raw.server_default
            assert raw.info.transaction_status.name == "IDLE"
            assert raw.query_log == [] and raw.autocommit is False
            # D9 (MP-2): every connection is time-bounded; the default is 10 seconds.
            assert opened[0][1] == {"prepare_threshold": None, "autocommit": False, "connect_timeout": 10}
        finally:
            connection.close()


# ---------------------------------------------------------------------------
# C. successor creator ordering (apply_activity_version_semantic_changes)
# ---------------------------------------------------------------------------


def test_postgres_successor_creator_locks_base_before_max_and_insert(tmp_path):
    write_transaction = _require("write_transaction")
    real = _bootstrap_connection(tmp_path, "u5c-creator-order.db")
    try:
        base_id, (frozen_id,) = _seed_base_with_versions(real, ["ativa"])
        pg = PostgresShapedConnection(real)

        with write_transaction(pg):
            result = apply_activity_version_semantic_changes(
                pg, frozen_id, {"grupo": "1 - Sucessora U5C"}
            )

        assert result["mode"] == "successor"
        _assert_lock_before_allocation(pg, base_id=base_id)
        successor = real.execute(
            "SELECT numero_versao, versao_anterior_id FROM atividade_versao WHERE id=?",
            (result["version_id"],),
        ).fetchone()
        assert (
            int(successor["numero_versao"]),
            int(successor["versao_anterior_id"]),
        ) == (2, frozen_id)
    finally:
        real.close()


def test_postgres_import_and_rename_creators_lock_base_before_successor(tmp_path):
    """The two wrappers that import / rename versions reach the same lock."""
    write_transaction = _require("write_transaction")

    # apply_latest_activity_version_semantic_changes (CSV import update path)
    real = _bootstrap_connection(tmp_path, "u5c-latest.db")
    try:
        base_id, (_frozen_id,) = _seed_base_with_versions(real, ["ativa"])
        pg = PostgresShapedConnection(real)
        with write_transaction(pg):
            result = apply_latest_activity_version_semantic_changes(
                pg, base_id, {"grupo": "1 - Import U5C"}
            )
        assert result["mode"] == "successor"
        _assert_lock_before_allocation(pg, base_id=base_id)
    finally:
        real.close()

    # rename_current_activity_group_versions (group rename path)
    real = _bootstrap_connection(tmp_path, "u5c-rename.db")
    try:
        base_id, (_frozen_id,) = _seed_base_with_versions(real, ["ativa"])
        pg = PostgresShapedConnection(real)
        with write_transaction(pg):
            results = rename_current_activity_group_versions(
                pg, eixo="AAC", group_number="1", new_label="1 - Renamed U5C"
            )
        assert any(item["mode"] == "successor" for item in results)
        _assert_lock_before_allocation(pg, base_id=base_id)
    finally:
        real.close()


def _change_current(connection, base_id, operation):
    if operation == "latest":
        return apply_latest_activity_version_semantic_changes(
            connection, base_id, {"grupo": "1 - Change B"}, expected_axis="AAC"
        )
    results = rename_current_activity_group_versions(
        connection, eixo="AAC", group_number="1", new_label="1 - Change B"
    )
    assert len(results) == 1
    return results[0]


@pytest.mark.parametrize("engine", ["sqlite", "postgres-shaped"])
def test_canonical_latest_owner_global_scoped_absence_and_no_status_filter(tmp_path, engine):
    real = _bootstrap_connection(tmp_path, f"u5c-canonical-axis-{engine}.db")
    try:
        base_id, (aac_id, aeu_id) = _seed_base_with_versions(real, ["ativa", "rascunho"])
        real.execute("UPDATE atividade_versao SET eixo='AEU' WHERE id=?", (aeu_id,))
        other_base, (_other_id,) = _seed_base_with_versions(real, ["ativa"], numbers=[99])
        real.commit()
        conn = real if engine == "sqlite" else PostgresShapedConnection(real)
        assert get_latest_atividade_versao_for_base(conn, base_id)["id"] == aeu_id
        assert get_latest_atividade_versao_for_base(conn, base_id, eixo=None)["id"] == aeu_id
        assert get_latest_atividade_versao_for_base(conn, base_id, eixo="AAC")["id"] == aac_id
        assert get_latest_atividade_versao_for_base(conn, base_id, eixo="AEU")["id"] == aeu_id
        assert get_latest_atividade_versao_for_base(conn, other_base, eixo="AEU") is None
        assert get_latest_atividade_versao_for_base(conn, base_id, eixo="missing") is None
        assert get_latest_atividade_versao_for_base(conn, base_id, eixo="") is None
        assert get_latest_atividade_versao_for_base(conn, -1) is None
        assert get_latest_atividade_versao_for_base(conn, -1, eixo="AAC") is None
    finally:
        real.close()


@pytest.mark.parametrize("axis", [None, "AAC", "AEU"])
def test_canonical_latest_owner_keeps_id_tiebreak_and_null_status(axis):
    # Production enforces unique (base, number). This disposable query fixture
    # deliberately permits ties to pin the existing defensive ORDER BY id rule;
    # it neither changes nor bypasses production schema authority.
    with sqlite3.connect(":memory:") as real:
        real.row_factory = sqlite3.Row
        real.execute("CREATE TABLE atividade_versao "
                     "(id INTEGER PRIMARY KEY,atividade_base_id INTEGER,eixo TEXT,"
                     "numero_versao INTEGER,status TEXT)")
        real.executemany("INSERT INTO atividade_versao VALUES(?,?,?,?,?)", [
            (1, 7, "AAC", 2, "ativa"), (2, 7, "AAC", 2, None),
            (3, 7, "AEU", 2, "ativa"), (4, 7, "AEU", 2, None),
            (5, 8, "AAC", 99, "ativa"),
        ])
        row = get_latest_atividade_versao_for_base(real, 7, eixo=axis)
        assert row["id"] == (2 if axis == "AAC" else 4)
        assert row["status"] is None


def test_rename_delegates_axis_owner_only_after_all_base_locks(tmp_path, monkeypatch):
    real = _bootstrap_connection(tmp_path, "u5c-canonical-rename-order.db")
    try:
        a, (aac_id, aeu_id) = _seed_base_with_versions(real, ["ativa", "rascunho"])
        real.execute("UPDATE atividade_versao SET ch_por_evento=11,limite_total=13 WHERE id=?", (aac_id,))
        real.execute("UPDATE atividade_versao SET eixo='AEU',ch_por_evento=22,limite_total=99 WHERE id=?", (aeu_id,))
        b, (_b_id,) = _seed_base_with_versions(real, ["ativa"])
        real.commit()
        pg = PostgresShapedConnection(real)
        calls = []
        owner = activity_catalog.get_latest_atividade_versao_for_base

        def observed_owner(conn, base_id, *, eixo=None):
            # Every target's actual locking statement must precede even the
            # first owner invocation, not just that target's own mutation.
            acquired = list(dict.fromkeys(
                params[0] for sql, params in conn.statements if _is_base_lock(sql)
            ))
            assert acquired == [a, b]
            assert not any(_is_destructive(sql) for sql, _params in conn.statements) or calls
            calls.append((base_id, eixo))
            return owner(conn, base_id, eixo=eixo)

        monkeypatch.setattr(activity_catalog, "get_latest_atividade_versao_for_base", observed_owner)
        with app_db.write_transaction(pg):
            results = rename_current_activity_group_versions(
                pg, eixo="AAC", group_number="1", new_label="1 - Scoped rename"
            )
        assert calls == [(a, "AAC"), (b, "AAC")]
        successor = real.execute("SELECT * FROM atividade_versao WHERE id=?",
                                 (results[0]["version_id"],)).fetchone()
        assert successor["atividade_base_id"] == a
        assert successor["eixo"] == "AAC"
        assert successor["versao_anterior_id"] == aac_id
        assert successor["numero_versao"] == 3
        assert successor["grupo"] == "1 - Scoped rename"
        assert successor["ch_por_evento"] == 11
        assert successor["limite_total"] == 13
        assert real.execute("SELECT grupo FROM atividade_versao WHERE id=?", (aeu_id,)).fetchone()[0] == "1 - U5C"
    finally:
        real.close()


def test_rename_has_no_inline_latest_sql_and_calls_canonical_owner():
    from tests.fc13_semantic_scanner import source_facts, static_sql, latest_sql

    source = inspect.getsource(rename_current_activity_group_versions)
    assert not any(latest_sql(sql) for sql in static_sql(source))
    assert any(latest_sql(sql) for sql in static_sql(inspect.getsource(get_latest_atividade_versao_for_base)))
    assert "get_latest_atividade_versao_for_base" in source_facts(source)[0].calls
    signature = inspect.signature(get_latest_atividade_versao_for_base)
    assert signature.parameters["eixo"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["eixo"].default is None


@pytest.mark.parametrize("operation", ["latest", "rename"])
def test_current_resolution_follows_base_lock(tmp_path, operation):
    real = _bootstrap_connection(tmp_path, f"u5c-current-order-{operation}.db")
    try:
        base_id, (_v1,) = _seed_base_with_versions(real, ["ativa"])
        pg = PostgresShapedConnection(real)
        with app_db.write_transaction(pg):
            result = _change_current(pg, base_id, operation)
        assert result["mode"] == "successor"
        current_index = _first_index(
            pg,
            lambda sql: bool(
                re.search(r"SELECT\s+\*\s+FROM\s+atividade_versao", sql, re.I)
                and "ORDER BY" in sql.upper()
            ),
        )
        lock_index = _first_index(pg, _is_base_lock)
        assert lock_index is not None and current_index is not None
        assert lock_index < current_index, "current source was selected before lock"
        _assert_lock_before_allocation(pg, base_id=base_id)
    finally:
        real.close()


@pytest.mark.parametrize("operation", ["latest", "rename"])
def test_current_changes_compose_when_prior_creator_commits_at_lock_boundary(
    tmp_path, operation
):
    """Inject a committed owner before lock acquisition; no scheduler claim.

    On the old implementation the waiting operation already cached v1. The
    fixed implementation must read the committed v2 after acquiring the lock.
    v2 is activated to preserve the business policy requiring a successor.
    """
    name = f"u5c-current-compose-{operation}.db"
    first_real = _bootstrap_connection(tmp_path, name)
    second_real = sqlite3.connect(tmp_path / name, timeout=0)
    second_real.row_factory = sqlite3.Row
    second_real.execute("PRAGMA foreign_keys=ON")
    registry = {}
    try:
        base_id, (v1,) = _seed_base_with_versions(first_real, ["ativa"])
        prior = PostgresShapedConnection(
            first_real, lock_registry=registry, owner="prior"
        )
        created = []

        def commit_change_a(_sql):
            with app_db.write_transaction(prior):
                result = apply_latest_activity_version_semantic_changes(
                    prior, base_id, {"limite_total": 77}, expected_axis="AAC"
                )
                created.append(result["version_id"])
                prior.execute(
                    "UPDATE atividade_versao SET status='ativa' WHERE id=?",
                    (created[0],),
                )

        waiting = _CallbackPostgresConnection(
            second_real,
            lock_registry=registry,
            owner="waiting",
            predicate=_is_base_lock,
            callback=commit_change_a,
        )
        with app_db.write_transaction(waiting):
            result = _change_current(waiting, base_id, operation)

        assert len(created) == 1 and result["mode"] == "successor"
        v2 = created[0]
        v3 = result["version_id"]
        rows = second_real.execute(
            "SELECT id, numero_versao, versao_anterior_id, limite_total, grupo "
            "FROM atividade_versao WHERE atividade_base_id=? ORDER BY numero_versao",
            (base_id,),
        ).fetchall()
        assert [(r["id"], r["numero_versao"], r["versao_anterior_id"]) for r in rows] == [
            (v1, 1, None), (v2, 2, v1), (v3, 3, v2)
        ]
        assert rows[1]["limite_total"] == rows[2]["limite_total"] == 77
        assert rows[2]["grupo"] == "1 - Change B"
        assert result["predecessor_id"] == v2
        assert prior.commits == waiting.commits == 1
        assert registry == {}
    finally:
        first_real.close()
        second_real.close()


@pytest.mark.parametrize("operation", ["latest", "rename"])
def test_current_change_on_another_base_proceeds_while_first_base_is_locked(
    tmp_path, operation
):
    name = f"u5c-current-independent-{operation}.db"
    first_real = _bootstrap_connection(tmp_path, name)
    second_real = sqlite3.connect(tmp_path / name, timeout=0)
    second_real.row_factory = sqlite3.Row
    registry = {}
    try:
        first_base, (_v1,) = _seed_base_with_versions(first_real, ["ativa"])
        second_base, (_v2,) = _seed_base_with_versions(first_real, ["ativa"])
        # Rename intentionally touches every candidate base of its axis; the
        # independently locked base belongs to the other axis, outside that set.
        first_real.execute(
            "UPDATE atividade_versao SET eixo='AEU' WHERE atividade_base_id=?",
            (first_base,),
        )
        first_real.commit()
        first = PostgresShapedConnection(first_real, lock_registry=registry, owner="first")
        second = PostgresShapedConnection(second_real, lock_registry=registry, owner="second")
        with app_db.write_transaction(first):
            app_db.lock_activity_base(first, first_base)
            with app_db.write_transaction(second):
                result = _change_current(second, second_base, operation)
                assert set(registry) == {
                    ("atividade_base", first_base), ("atividade_base", second_base)
                }
            assert result["mode"] == "successor"
        _assert_lock_before_allocation(second, base_id=second_base)
    finally:
        first_real.close()
        second_real.close()


@pytest.mark.parametrize("operation", ["latest", "rename"])
def test_current_draft_changes_still_update_in_place_under_base_lock(tmp_path, operation):
    real = _bootstrap_connection(tmp_path, f"u5c-current-draft-{operation}.db")
    try:
        base_id, (draft,) = _seed_base_with_versions(real, ["rascunho"])
        pg = PostgresShapedConnection(real)
        with app_db.write_transaction(pg):
            result = _change_current(pg, base_id, operation)
        assert result == {"mode": "updated", "version_id": draft, "predecessor_id": None}
        lock_index = _first_index(pg, _is_base_lock)
        update_index = _first_index(
            pg, lambda sql: "UPDATE ATIVIDADE_VERSAO" in sql.upper()
        )
        assert lock_index is not None and lock_index < update_index
        assert real.execute(
            "SELECT COUNT(*) FROM atividade_versao WHERE atividade_base_id=?", (base_id,)
        ).fetchone()[0] == 1
    finally:
        real.close()


def test_rename_rechecks_current_group_eligibility_after_base_lock(tmp_path):
    name = "u5c-current-rename-eligibility.db"
    first_real = _bootstrap_connection(tmp_path, name)
    second_real = sqlite3.connect(tmp_path / name, timeout=0)
    second_real.row_factory = sqlite3.Row
    registry = {}
    try:
        base_id, (v1,) = _seed_base_with_versions(first_real, ["ativa"])
        prior = PostgresShapedConnection(first_real, lock_registry=registry, owner="prior")
        committed = []

        def move_current_to_other_group(_sql):
            with app_db.write_transaction(prior):
                committed.append(apply_latest_activity_version_semantic_changes(
                    prior, base_id, {"grupo": "2 - Changed group"}
                )["version_id"])

        rename = _CallbackPostgresConnection(
            second_real,
            lock_registry=registry,
            owner="rename",
            predicate=_is_base_lock,
            callback=move_current_to_other_group,
        )
        with app_db.write_transaction(rename):
            results = rename_current_activity_group_versions(
                rename, eixo="AAC", group_number="1", new_label="1 - Change B"
            )
        assert results == []
        assert not any(_is_destructive(sql) for sql, _params in rename.statements)
        rows = second_real.execute(
            "SELECT id, grupo FROM atividade_versao WHERE atividade_base_id=? "
            "ORDER BY numero_versao", (base_id,)
        ).fetchall()
        assert [(r["id"], r["grupo"]) for r in rows] == [
            (v1, "1 - U5C"), (committed[0], "2 - Changed group")
        ]
    finally:
        first_real.close()
        second_real.close()


@pytest.mark.parametrize("operation", ["latest", "rename"])
def test_sqlite_current_changes_compose_inside_begin_immediate(tmp_path, operation):
    real = _bootstrap_connection(tmp_path, f"u5c-current-sqlite-{operation}.db")
    try:
        base_id, (v1,) = _seed_base_with_versions(real, ["ativa"])
        traced = []
        real.set_trace_callback(traced.append)
        with app_db.write_transaction(real):
            first = apply_latest_activity_version_semantic_changes(
                real, base_id, {"limite_total": 77}
            )
            real.execute(
                "UPDATE atividade_versao SET status='ativa' WHERE id=?",
                (first["version_id"],),
            )
        with app_db.write_transaction(real):
            second = _change_current(real, base_id, operation)
        rows = real.execute(
            "SELECT numero_versao, versao_anterior_id, limite_total, grupo "
            "FROM atividade_versao WHERE atividade_base_id=? ORDER BY numero_versao",
            (base_id,),
        ).fetchall()
        assert [r["numero_versao"] for r in rows] == [1, 2, 3]
        assert [r["versao_anterior_id"] for r in rows] == [None, v1, first["version_id"]]
        assert rows[2]["limite_total"] == 77 and rows[2]["grupo"] == "1 - Change B"
        assert second["predecessor_id"] == first["version_id"]
        assert sum("BEGIN IMMEDIATE" in sql.upper() for sql in traced) == 2
    finally:
        real.close()


def test_postgres_two_creators_of_same_base_serialize_on_the_base_lock(tmp_path):
    write_transaction = _require("write_transaction")
    lock_activity_base = _require("lock_activity_base")
    database = tmp_path / "u5c-create-create.db"
    first_real = _bootstrap_connection(tmp_path, "u5c-create-create.db")
    second_real = sqlite3.connect(database, timeout=0)
    second_real.row_factory = sqlite3.Row
    second_real.execute("PRAGMA foreign_keys=ON")
    registry = {}
    try:
        base_id, (frozen_id,) = _seed_base_with_versions(first_real, ["ativa"])
        first = PostgresShapedConnection(
            first_real, lock_registry=registry, owner="first"
        )
        second = PostgresShapedConnection(
            second_real, lock_registry=registry, owner="second"
        )

        with write_transaction(first):
            apply_activity_version_semantic_changes(
                first, frozen_id, {"grupo": "1 - A"}
            )
            # While the first creator owns the base lock, the second cannot
            # even acquire it, so it can never read MAX or insert.
            with pytest.raises(PostgresLockBlocked):
                lock_activity_base(second, base_id)
            assert not any(_is_destructive(sql) for sql, _ in second.statements)

        second.rollback()
        assert registry == {}

        with write_transaction(second):
            result = apply_activity_version_semantic_changes(
                second, frozen_id, {"grupo": "1 - B"}
            )

        numbers = sorted(
            int(row[0])
            for row in first_real.execute(
                "SELECT numero_versao FROM atividade_versao "
                "WHERE atividade_base_id=?",
                (base_id,),
            )
        )
        assert numbers == [1, 2, 3]
        new_number = first_real.execute(
            "SELECT numero_versao FROM atividade_versao WHERE id=?",
            (result["version_id"],),
        ).fetchone()[0]
        assert int(new_number) == 3
    finally:
        first_real.close()
        second_real.close()


# ---------------------------------------------------------------------------
# D. create x delete share the same per-base lock domain
# ---------------------------------------------------------------------------


def test_postgres_creator_blocks_delete_on_same_base(tmp_path):
    write_transaction = _require("write_transaction")
    database = tmp_path / "u5c-creator-blocks-delete.db"
    first_real = _bootstrap_connection(tmp_path, "u5c-creator-blocks-delete.db")
    second_real = sqlite3.connect(database, timeout=0)
    second_real.row_factory = sqlite3.Row
    second_real.execute("PRAGMA foreign_keys=ON")
    registry = {}
    try:
        base_id, (first_version, second_version) = _seed_base_with_versions(
            first_real, ["ativa", "ativa"], chained=True
        )
        first = PostgresShapedConnection(
            first_real, lock_registry=registry, owner="first"
        )
        second = PostgresShapedConnection(
            second_real, lock_registry=registry, owner="second"
        )

        with write_transaction(first):
            apply_activity_version_semantic_changes(
                first, first_version, {"grupo": "1 - A"}
            )
            with pytest.raises(PostgresLockBlocked):
                delete_activity_version(
                    second, base_id=base_id, versao_id=second_version
                )

        second.rollback()
        assert first_real.execute(
            "SELECT 1 FROM atividade_versao WHERE id=?", (second_version,)
        ).fetchone() is not None
    finally:
        first_real.close()
        second_real.close()


def test_postgres_delete_holds_the_base_lock_against_a_creator(tmp_path):
    """The delete path and the creator path contend on the same base-row lock."""
    write_transaction = _require("write_transaction")
    lock_activity_base = _require("lock_activity_base")
    database = tmp_path / "u5c-delete-blocks-creator.db"
    first_real = _bootstrap_connection(tmp_path, "u5c-delete-blocks-creator.db")
    second_real = sqlite3.connect(database, timeout=0)
    second_real.row_factory = sqlite3.Row
    second_real.execute("PRAGMA foreign_keys=ON")
    registry = {}
    try:
        base_id, (v1, v2) = _seed_base_with_versions(
            first_real, ["ativa", "ativa"], chained=True
        )
        first = PostgresShapedConnection(
            first_real, lock_registry=registry, owner="first"
        )
        second = PostgresShapedConnection(
            second_real, lock_registry=registry, owner="second"
        )

        with write_transaction(first):
            delete_activity_version(first, base_id=base_id, versao_id=v2)
            # The creator-side lock acquisition is blocked while the delete
            # owns the base, before any creator read/insert can happen.
            with pytest.raises(PostgresLockBlocked):
                lock_activity_base(second, base_id)
            assert not any(_is_destructive(sql) for sql, _ in second.statements)

        second.rollback()
        assert first_real.execute(
            "SELECT 1 FROM atividade_versao WHERE id=?", (v2,)
        ).fetchone() is None
        assert first_real.execute(
            "SELECT 1 FROM atividade_versao WHERE id=?", (v1,)
        ).fetchone() is not None
    finally:
        first_real.close()
        second_real.close()


def test_postgres_create_and_delete_locking_is_per_base(tmp_path):
    write_transaction = _require("write_transaction")
    lock_activity_base = _require("lock_activity_base")
    database = tmp_path / "u5c-per-base.db"
    first_real = _bootstrap_connection(tmp_path, "u5c-per-base.db")
    second_real = sqlite3.connect(database, timeout=0)
    second_real.row_factory = sqlite3.Row
    second_real.execute("PRAGMA foreign_keys=ON")
    registry = {}
    try:
        first_base, (_first_v1,) = _seed_base_with_versions(first_real, ["ativa"])
        second_base, (_second_v1,) = _seed_base_with_versions(first_real, ["ativa"])
        first = PostgresShapedConnection(
            first_real, lock_registry=registry, owner="first"
        )
        second = PostgresShapedConnection(
            second_real, lock_registry=registry, owner="second"
        )

        with write_transaction(first):
            assert lock_activity_base(first, first_base) is True
            # A different atividade_base row is a different lock domain.
            assert lock_activity_base(second, second_base) is True
            assert set(registry) == {
                ("atividade_base", first_base),
                ("atividade_base", second_base),
            }
    finally:
        first_real.close()
        second_real.close()


# ---------------------------------------------------------------------------
# E. the production legacy delete route joins the same per-base lock domain
# ---------------------------------------------------------------------------


def test_legacy_delete_cannot_mutate_while_creator_holds_same_base_lock(
    tmp_path, monkeypatch
):
    write_transaction = _require("write_transaction")
    with isolated_versioned_app_env(tmp_path, "u5c-legacy-creator-lock.db") as env:
        client = env["client"]
        _login_admin(client)
        creator_real = sqlite3.connect(env["db_path"], timeout=0)
        creator_real.row_factory = sqlite3.Row
        legacy_real = sqlite3.connect(env["db_path"], timeout=0)
        legacy_real.row_factory = sqlite3.Row
        registry = {}
        try:
            base_id, (v1, target) = _seed_base_with_versions(
                creator_real, ["ativa", "ativa"], chained=True
            )
            creator = PostgresShapedConnection(
                creator_real, lock_registry=registry, owner="creator"
            )
            legacy = PostgresShapedConnection(
                legacy_real, lock_registry=registry, owner="legacy"
            )
            import app.views.admin.atividades as atividades_module

            with main.app.app_context():
                _install_fake_connection(monkeypatch, legacy, atividades_module)
                with write_transaction(creator):
                    apply_activity_version_semantic_changes(
                        creator, v1, {"grupo": "1 - Creator owns lock"}
                    )
                    response = client.post(
                        f"/admin/deletar_atividade/{target}",
                        follow_redirects=False,
                    )
                    assert response.status_code in (302, 303)
                    assert not any(
                        "DELETE FROM ATIVIDADE_VERSAO" in sql.upper()
                        for sql, _params in legacy.statements
                    )

            assert creator_real.execute(
                "SELECT 1 FROM atividade_versao WHERE id=?", (target,)
            ).fetchone() is not None
            assert ("atividade_base", base_id) in legacy.locks
            assert legacy.rollbacks == 1
        finally:
            creator_real.close()
            legacy_real.close()


def test_legacy_delete_lock_stops_same_base_creator_before_max_or_insert(
    tmp_path, monkeypatch
):
    write_transaction = _require("write_transaction")
    with isolated_versioned_app_env(tmp_path, "u5c-legacy-blocks-creator.db") as env:
        client = env["client"]
        _login_admin(client)
        legacy_real = sqlite3.connect(env["db_path"], timeout=0)
        legacy_real.row_factory = sqlite3.Row
        creator_real = sqlite3.connect(env["db_path"], timeout=0)
        creator_real.row_factory = sqlite3.Row
        registry = {}
        try:
            base_id, (predecessor, target) = _seed_base_with_versions(
                legacy_real, ["ativa", "ativa"], chained=True
            )
            creator = PostgresShapedConnection(
                creator_real, lock_registry=registry, owner="creator"
            )
            attempted = []

            def attempt_creator(_sql):
                attempted.append(True)
                with pytest.raises(PostgresLockBlocked):
                    with write_transaction(creator):
                        apply_activity_version_semantic_changes(
                            creator,
                            predecessor,
                            {"grupo": "1 - Must wait for legacy delete"},
                        )

            legacy = _CallbackPostgresConnection(
                legacy_real,
                lock_registry=registry,
                owner="legacy",
                predicate=lambda sql: "DELETE FROM MATRIZ_ATIVIDADE_VERSAO_ITEM"
                in sql.upper(),
                callback=attempt_creator,
            )
            import app.views.admin.atividades as atividades_module

            with main.app.app_context():
                monkeypatch.setattr(
                    atividades_module,
                    "ensure_matriz_atividade_links_table",
                    lambda _conn: None,
                )
                _install_fake_connection(monkeypatch, legacy, atividades_module)
                response = client.post(
                    f"/admin/deletar_atividade/{target}", follow_redirects=False
                )
                assert response.status_code in (302, 303)
                target_exists = legacy_real.execute(
                    "SELECT 1 FROM atividade_versao WHERE id=?", (target,)
                ).fetchone()

            assert attempted == [True]
            assert ("atividade_base", base_id) in legacy.locks
            assert _first_index(legacy, _is_base_lock) < _first_index(
                legacy,
                lambda sql: "DELETE FROM MATRIZ_ATIVIDADE_VERSAO_ITEM" in sql.upper(),
            )
            assert not any(_is_max(sql) for sql, _params in creator.statements)
            assert not any(_is_version_insert(sql) for sql, _params in creator.statements)
            assert target_exists is None
        finally:
            legacy_real.close()
            creator_real.close()


def test_legacy_delete_and_creator_for_different_bases_are_independent(
    tmp_path, monkeypatch
):
    write_transaction = _require("write_transaction")
    with isolated_versioned_app_env(tmp_path, "u5c-legacy-different-base.db") as env:
        client = env["client"]
        _login_admin(client)
        legacy_real = sqlite3.connect(env["db_path"], timeout=0)
        legacy_real.row_factory = sqlite3.Row
        creator_real = sqlite3.connect(env["db_path"], timeout=0)
        creator_real.row_factory = sqlite3.Row
        registry = {}
        try:
            delete_base, (_keep, target) = _seed_base_with_versions(
                legacy_real, ["ativa", "ativa"], chained=True
            )
            create_base, (predecessor,) = _seed_base_with_versions(
                legacy_real, ["ativa"]
            )
            creator = PostgresShapedConnection(
                creator_real, lock_registry=registry, owner="creator"
            )
            created = []

            def create_other_base(_sql):
                with write_transaction(creator):
                    created.append(
                        apply_activity_version_semantic_changes(
                            creator,
                            predecessor,
                            {"grupo": "1 - Independent creator"},
                        )["version_id"]
                    )

            legacy = _CallbackPostgresConnection(
                legacy_real,
                lock_registry=registry,
                owner="legacy",
                predicate=lambda sql: "DELETE FROM MATRIZ_ATIVIDADE_VERSAO_ITEM"
                in sql.upper(),
                callback=create_other_base,
            )
            import app.views.admin.atividades as atividades_module

            with main.app.app_context():
                monkeypatch.setattr(
                    atividades_module,
                    "ensure_matriz_atividade_links_table",
                    lambda _conn: None,
                )
                _install_fake_connection(monkeypatch, legacy, atividades_module)
                response = client.post(
                    f"/admin/deletar_atividade/{target}", follow_redirects=False
                )
                assert response.status_code in (302, 303)

            assert len(created) == 1
            assert ("atividade_base", delete_base) in legacy.locks
            assert ("atividade_base", create_base) in creator.locks
            assert creator_real.execute(
                "SELECT numero_versao FROM atividade_versao WHERE id=?", (created[0],)
            ).fetchone()[0] == 2
        finally:
            legacy_real.close()
            creator_real.close()


def test_sqlite_legacy_delete_uses_begin_immediate_and_keeps_delete_policy(
    tmp_path, monkeypatch
):
    with isolated_versioned_app_env(tmp_path, "u5c-legacy-sqlite.db") as env:
        client = env["client"]
        _login_admin(client)
        with main.app.app_context():
            main.close_db_connection(None)
            real = main.get_db_connection()
            base_id, (target, survivor) = _seed_base_with_versions(
                real, ["ativa", "ativa"]
            )
            traced = []
            real.set_trace_callback(traced.append)
            import app.views.admin.atividades as atividades_module

            _install_fake_connection(monkeypatch, real, atividades_module)
            response = client.post(
                f"/admin/deletar_atividade/{target}", follow_redirects=False
            )
            assert response.status_code in (302, 303)
            assert any("BEGIN IMMEDIATE" in sql.upper() for sql in traced)
            assert real.execute(
                "SELECT 1 FROM atividade_versao WHERE id=?", (target,)
            ).fetchone() is None
            survivor_row = real.execute(
                "SELECT numero_versao FROM atividade_versao WHERE id=?", (survivor,)
            ).fetchone()
            assert int(survivor_row[0]) == 2
            assert real.execute(
                "SELECT 1 FROM atividade_base WHERE id=?", (base_id,)
            ).fetchone() is not None


def test_sqlite_legacy_delete_failure_rolls_back_version_and_base(
    tmp_path, monkeypatch
):
    with isolated_versioned_app_env(tmp_path, "u5c-legacy-rollback.db") as env:
        client = env["client"]
        _login_admin(client)
        with main.app.app_context():
            main.close_db_connection(None)
            real = main.get_db_connection()
            base_id, (target,) = _seed_base_with_versions(real, ["ativa"])
            real.execute(
                "CREATE TRIGGER fail_u5c_legacy_base_delete "
                "BEFORE DELETE ON atividade_base "
                "WHEN OLD.id = %d "
                "BEGIN SELECT RAISE(ABORT, 'simulated base delete failure'); END"
                % base_id
            )
            real.commit()
            import app.views.admin.atividades as atividades_module

            _install_fake_connection(monkeypatch, real, atividades_module)
            response = client.post(
                f"/admin/deletar_atividade/{target}", follow_redirects=False
            )
            assert response.status_code in (302, 303)
            assert real.execute(
                "SELECT 1 FROM atividade_versao WHERE id=?", (target,)
            ).fetchone() is not None
            assert real.execute(
                "SELECT 1 FROM atividade_base WHERE id=?", (base_id,)
            ).fetchone() is not None


# ---------------------------------------------------------------------------
# A/B. the admin creator route owns a write transaction and locks first
# ---------------------------------------------------------------------------


def test_admin_nova_versao_route_uses_write_transaction_and_locks_before_allocation(
    tmp_path, monkeypatch
):
    with isolated_versioned_app_env(tmp_path, "u5c-route-create.db") as env:
        client = env["client"]
        _login_admin(client)
        with main.app.app_context():
            main.close_db_connection(None)
            real = main.get_db_connection()
            base_id, (v1,) = _seed_base_with_versions(real, ["ativa"])
            form = _nova_versao_form(real, base_id, v1)
            pg = PostgresShapedConnection(real)
            import app.views.admin.atividades as atividades_module

            _install_fake_connection(monkeypatch, pg, atividades_module)
            try:
                response = client.post(
                    f"/admin/catalogo-versoes/{base_id}/nova-versao",
                    data=form,
                    follow_redirects=False,
                )
                created = real.execute(
                    "SELECT numero_versao FROM atividade_versao "
                    "WHERE atividade_base_id=? ORDER BY numero_versao",
                    (base_id,),
                ).fetchall()
            finally:
                main.close_db_connection(None)

        assert response.status_code in (302, 303), response.get_data(as_text=True)
        _assert_lock_before_allocation(pg, base_id=base_id)
        # Entering the Unit-4 manager is observable: the PostgreSQL branch
        # probes the assigned XID before taking the base lock.
        probe_index = _first_index(pg, lambda sql: bool(_XID_PROBE_RE.search(sql)))
        lock_index = _first_index(pg, _is_base_lock)
        assert probe_index is not None and probe_index < lock_index
        assert [int(row[0]) for row in created] == [1, 2]


def _run_route_with_sqlite_trace(env, monkeypatch, url, *, post_kwargs):
    """POST a route on the real SQLite connection and return traced SQL."""
    client = env["client"]
    _login_admin(client)
    with main.app.app_context():
        main.close_db_connection(None)
        real = main.get_db_connection()
        traced = []
        real.set_trace_callback(traced.append)
        import app.views.admin.atividades as atividades_module

        _install_fake_connection(monkeypatch, real, atividades_module)
        try:
            response = client.post(url, **post_kwargs)
        finally:
            main.close_db_connection(None)
    return real, response, traced


def test_sqlite_grupos_renomear_route_uses_write_transaction(tmp_path, monkeypatch):
    with isolated_versioned_app_env(tmp_path, "u5c-route-rename.db") as env:
        real, response, traced = _run_route_with_sqlite_trace(
            env,
            monkeypatch,
            "/admin/grupos/renomear",
            post_kwargs={
                "json": {
                    "tipo_atividade": "Acadêmica Complementar",
                    "numero": "1",
                    "descricao": "Renomeado U5C",
                }
            },
        )
        assert response.status_code == 200
        assert response.get_json()["ok"] is True
        assert any("BEGIN IMMEDIATE" in statement.upper() for statement in traced)


def test_sqlite_importar_confirmar_route_uses_write_transaction(
    tmp_path, monkeypatch
):
    with isolated_versioned_app_env(tmp_path, "u5c-route-import.db") as env:
        client = env["client"]
        _login_admin(client)
        import app.views.admin.atividades as atividades_module

        with main.app.app_context():
            main.close_db_connection(None)
            real = main.get_db_connection()
            base_id, (_v1,) = _seed_base_with_versions(real, ["ativa"])
            payload = {
                "rows": [
                    {
                        "action": "update",
                        "existing_id": base_id,
                        "tipo_atividade": "Acadêmica Complementar",
                        "grupo_numero": "1",
                        "grupo_descricao": "Importado U5C",
                        "grupo": "1 - Importado U5C",
                        "limite_horas_total": 77,
                        "limite_horas_semestral": None,
                    }
                ],
                "csv_relpath": None,
            }
            traced = []
            real.set_trace_callback(traced.append)
            monkeypatch.setattr(
                atividades_module,
                "_load_atividades_import_preview",
                lambda key: payload,
            )
            monkeypatch.setattr(
                atividades_module,
                "_delete_atividades_import_preview",
                lambda key: None,
            )
            monkeypatch.setattr(
                atividades_module, "_delete_upload_relpath", lambda relpath: None
            )
            _install_fake_connection(monkeypatch, real, atividades_module)
            try:
                response = client.post(
                    "/admin/atividades/importar/confirmar",
                    data={"preview_key": "u5c"},
                    follow_redirects=False,
                )
                created = real.execute(
                    "SELECT numero_versao FROM atividade_versao "
                    "WHERE atividade_base_id=? ORDER BY numero_versao",
                    (base_id,),
                ).fetchall()
            finally:
                main.close_db_connection(None)

        assert response.status_code in (302, 303), response.get_data(as_text=True)
        assert any("BEGIN IMMEDIATE" in statement.upper() for statement in traced)
        assert [int(row[0]) for row in created] == [1, 2]


# ---------------------------------------------------------------------------
# G/F. SQLite stays the default engine: BEGIN IMMEDIATE + unchanged policy
# ---------------------------------------------------------------------------


def test_sqlite_nova_versao_route_keeps_begin_immediate_and_sequence(
    tmp_path, monkeypatch
):
    with isolated_versioned_app_env(tmp_path, "u5c-sqlite-create.db") as env:
        client = env["client"]
        _login_admin(client)
        with main.app.app_context():
            main.close_db_connection(None)
            real = main.get_db_connection()
            base_id, (v1,) = _seed_base_with_versions(real, ["ativa"])
            form = _nova_versao_form(real, base_id, v1)
            traced = []
            real.set_trace_callback(traced.append)
            import app.views.admin.atividades as atividades_module

            _install_fake_connection(monkeypatch, real, atividades_module)
            try:
                response = client.post(
                    f"/admin/catalogo-versoes/{base_id}/nova-versao",
                    data=form,
                    follow_redirects=False,
                )
                numbers = [
                    int(row[0])
                    for row in real.execute(
                        "SELECT numero_versao FROM atividade_versao "
                        "WHERE atividade_base_id=? ORDER BY numero_versao",
                        (base_id,),
                    )
                ]
            finally:
                main.close_db_connection(None)

        assert response.status_code in (302, 303), response.get_data(as_text=True)
        assert any("BEGIN IMMEDIATE" in statement.upper() for statement in traced)
        assert numbers == [1, 2]


def test_sqlite_delete_then_create_keeps_the_compact_number_policy(tmp_path):
    write_transaction = _require("write_transaction")
    real = _bootstrap_connection(tmp_path, "u5c-sqlite-policy.db")
    try:
        base_id, (v1, v2, v3) = _seed_base_with_versions(
            real, ["ativa", "ativa", "ativa"], chained=True
        )

        with write_transaction(real):
            # Delete a non-latest version; survivors compact to v1..v2.
            delete_activity_version(real, base_id=base_id, versao_id=v2)
            assert get_next_numero_versao(real, base_id) == 3
            # The next automatic version reuses the compacted slot v3.
            new_id = real.execute(
                "INSERT INTO atividade_versao"
                "(atividade_base_id,eixo,grupo,numero_versao,status) "
                "VALUES(?,'AAC','1 - U5C',3,'rascunho') RETURNING id",
                (base_id,),
            ).fetchone()[0]

        rows = real.execute(
            "SELECT id, numero_versao FROM atividade_versao "
            "WHERE atividade_base_id=? ORDER BY numero_versao",
            (base_id,),
        ).fetchall()
        assert [(int(row["id"]), int(row["numero_versao"])) for row in rows] == [
            (v1, 1),
            (v3, 2),
            (new_id, 3),
        ]
    finally:
        real.close()


def test_sqlite_creator_rollback_leaves_no_partial_version(tmp_path):
    write_transaction = _require("write_transaction")
    real = _bootstrap_connection(tmp_path, "u5c-sqlite-rollback.db")
    try:
        base_id, (v1,) = _seed_base_with_versions(real, ["ativa"])
        with pytest.raises(RuntimeError):
            with write_transaction(real):
                apply_activity_version_semantic_changes(
                    real, v1, {"grupo": "1 - X"}
                )
                raise RuntimeError("simulated failure after the successor insert")
        rows = real.execute(
            "SELECT id, numero_versao FROM atividade_versao WHERE atividade_base_id=?",
            (base_id,),
        ).fetchall()
        assert [(int(row["id"]), int(row["numero_versao"])) for row in rows] == [(v1, 1)]
    finally:
        real.close()


# ---------------------------------------------------------------------------
# H/I. scope boundaries: U5-B dialect and U5-D PTBR are untouched
# ---------------------------------------------------------------------------


def test_u5c_scope_boundaries():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    dialect = (root / "app/sql_dialect.py").read_text(encoding="utf-8")
    assert "FOR NO KEY UPDATE" not in dialect
    assert "FOR UPDATE" not in dialect
    schema = (root / "app/pg_schema.py").read_text(encoding="utf-8")
    assert "lock_activity_base" not in schema
    atividades = (root / "app/views/admin/atividades.py").read_text(encoding="utf-8")
    # Pre-U5-D this asserted the raw "COLLATE PTBR_NOACCENT" was still present
    # (U5-C left U5-D's PTBR ordering alone).  U5-D moved that ordering into
    # app.sql_dialect; the enduring boundary is that U5-C's locking stays out
    # of the dialect (above) and atividades orders through the U5-D owners,
    # never through raw SQLite human-text SQL.
    assert "COLLATE PTBR_NOACCENT" not in atividades
    assert "COLLATE NOCASE" not in atividades
    assert "human_text_order(" in atividades
    assert "ascii_nocase_order(" in atividades
