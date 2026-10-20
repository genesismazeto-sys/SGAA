"""prod-1/v17: an editable request may replace its activity and snapshot together.

v17 replaces one trigger, ``trg_requisicoes_snapshot_immutable``.  The proofs:
a fresh v17 equals a v16 database migrated forward (same physical digest, rows
preserved), the migration rolls back whole on failure, the frozen v16 trigger
refuses what v17 accepts while both refuse what must stay frozen, and the
PostgreSQL contract states the same rule.  The route-level workflow is in
``tests/test_request_reclassification.py``; real PostgreSQL in
``tests/test_request_reclassification_real_pg.py``.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app import pg_schema, prod1_schema
from app.prod1_request_reclassification_ddl import (
    RECLASSIFIABLE_REQUEST_STATUSES,
    REQUEST_RECLASSIFICATION_V17_SCHEMA_OBJECTS_SQL,
    SNAPSHOT_IDENTITY_MESSAGE,
    SNAPSHOT_IMMUTABLE_MESSAGE,
    SNAPSHOT_PAIRING_MESSAGE,
)
from app.prod1_schema import (
    Prod1SchemaError,
    _physical_schema_digest,
    bootstrap_prod1_schema,
    canonical_prod1_pre_v17_object_sql,
    validate_prod1_schema,
)
from tests.prod1_v17_support import revert_prod1_v17_to_v16


def _snapshot(version_id: int) -> str:
    return json.dumps({"atividade_versao_id": version_id, "eixo": "AAC", "schema_version": "prod-1-request-v2"})


def _fresh() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _seed(conn) -> None:
    conn.executescript(
        "INSERT INTO atividade_base(id,nome_conceito) VALUES(1,'Conceito A');"
        "INSERT INTO atividade_base(id,nome_conceito) VALUES(2,'Conceito B');"
        "INSERT INTO atividade_versao(id,atividade_base_id,eixo,numero_versao,status) VALUES(1,1,'AAC',1,'ativa');"
        "INSERT INTO atividade_versao(id,atividade_base_id,eixo,numero_versao,status) VALUES(2,2,'AEU',1,'ativa');"
    )
    for request_id, status in enumerate(prod1_schema.REQUEST_STATUSES, start=1):
        conn.execute(
            "INSERT INTO requisicoes(id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,"
            "status,regra_snapshot_json) VALUES(?,1,'2026-09-05','2026-09-05',2,?,?)",
            (request_id, status, _snapshot(1)),
        )
    conn.commit()


def _request_id(status: str) -> int:
    return prod1_schema.REQUEST_STATUSES.index(status) + 1


def _refusal(conn, sql, params=()) -> str | None:
    """The trigger's message when it refuses, else ``None``; never keeps the write."""
    conn.execute("SAVEPOINT probe")
    try:
        conn.execute(sql, params)
        return None
    except sqlite3.IntegrityError as exc:
        return str(exc)
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT probe")
        conn.execute("RELEASE SAVEPOINT probe")


_PAIR = "UPDATE requisicoes SET atividade_versao_id=?, regra_snapshot_json=? WHERE id=?"


def _v16_copy() -> sqlite3.Connection:
    conn = _fresh()
    _seed(conn)
    revert_prod1_v17_to_v16(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 16
    return conn


# --- version gate -----------------------------------------------------------------


def test_v17_is_preserved_on_both_authorities():
    assert prod1_schema.SCHEMA_VERSION == 18 == pg_schema.PG_SCHEMA_VERSION
    assert prod1_schema.LATEST_MIGRATION_MARKER == "return_notifications"
    seed = {version: name for version, name, _details in pg_schema.PG_SCHEMA_MIGRATIONS_SEED}
    assert seed[17] == "request_reclassification"


def test_the_reclassifiable_statuses_are_exactly_the_editable_ones():
    assert RECLASSIFIABLE_REQUEST_STATUSES == ("Pendente", "Devolvida")
    assert set(RECLASSIFIABLE_REQUEST_STATUSES) < set(prod1_schema.REQUEST_STATUSES)


# --- migration --------------------------------------------------------------------


def test_a_v16_database_migrates_to_the_same_physical_schema_as_a_fresh_v17():
    migrated = _v16_copy()
    before = [tuple(r) for r in migrated.execute("SELECT * FROM requisicoes ORDER BY id")]
    result = prod1_schema.bootstrap_prod1_schema(migrated)
    assert result["schema_version"] == 18 and result["request_reclassification"] == "pending_or_returned"
    assert result["rows_preserved"]["requisicoes"] == len(prod1_schema.REQUEST_STATUSES)
    assert _physical_schema_digest(migrated) == _physical_schema_digest(_fresh())
    assert [tuple(r) for r in migrated.execute("SELECT * FROM requisicoes ORDER BY id")] == before
    row = migrated.execute("SELECT name, schema_epoch FROM schema_migrations WHERE version=17").fetchone()
    assert tuple(row) == ("request_reclassification", "prod-1")


def test_the_frozen_v16_predecessor_is_recognised_and_a_tampered_one_is_not():
    conn = _v16_copy()
    prod1_schema._validate_prod1_v16_schema(conn)
    conn.execute("CREATE TABLE sneaky(x)")
    with pytest.raises(Prod1SchemaError):
        prod1_schema._validate_prod1_v16_schema(conn)
    with pytest.raises(Prod1SchemaError):
        prod1_schema.migrate_prod1_v16_to_v17(conn)


def test_a_failed_migration_rolls_back_schema_data_and_version(monkeypatch):
    import app.prod1_request_reclassification_v17 as migration

    conn = _v16_copy()
    before = _physical_schema_digest(conn)
    monkeypatch.setattr(
        migration, "REQUEST_RECLASSIFICATION_V17_STATEMENTS",
        migration.REQUEST_RECLASSIFICATION_V17_STATEMENTS[:1] + ("CREATE TRIGGER definitely not sql",),
    )
    with pytest.raises(sqlite3.Error):
        prod1_schema.migrate_prod1_v16_to_v17(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 16
    assert _physical_schema_digest(conn) == before  # the v16 trigger is back
    assert not conn.in_transaction
    assert conn.execute("SELECT count(*) FROM schema_migrations WHERE version=17").fetchone()[0] == 0


def test_the_pre_v17_probe_returns_the_frozen_v16_trigger():
    v16 = canonical_prod1_pre_v17_object_sql("trigger", "trg_requisicoes_snapshot_immutable")
    head = prod1_schema.canonical_prod1_object_sql("trigger", "trg_requisicoes_snapshot_immutable")
    assert "RAISE(ABORT,'request snapshot authority is immutable')" in v16 and "Pendente" not in v16
    assert "'Pendente','Devolvida'" in head and SNAPSHOT_PAIRING_MESSAGE in head
    assert REQUEST_RECLASSIFICATION_V17_SCHEMA_OBJECTS_SQL.startswith("DROP TRIGGER trg_requisicoes_snapshot_immutable;")


# --- the rule, v16 against v17 ----------------------------------------------------


def test_v16_froze_a_pending_request_and_v17_lets_it_change_its_pair():
    conn = _v16_copy()
    pending = _request_id("Pendente")
    assert SNAPSHOT_IMMUTABLE_MESSAGE in _refusal(conn, _PAIR, (2, _snapshot(2), pending))
    bootstrap_prod1_schema(conn)
    assert _refusal(conn, _PAIR, (2, _snapshot(2), pending)) is None


@pytest.mark.parametrize("status", ["Pendente", "Devolvida"])
def test_an_editable_request_changes_activity_and_snapshot_together(status):
    conn = _fresh()
    _seed(conn)
    request_id = _request_id(status)
    assert _refusal(conn, _PAIR, (2, _snapshot(2), request_id)) is None
    # A resubmission may change status and pair in one statement (Devolvida -> Pendente).
    assert _refusal(
        conn, "UPDATE requisicoes SET status='Pendente', atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
        (2, _snapshot(2), request_id)) is None
    # Ordinary edits never touch the rule.
    assert _refusal(conn, "UPDATE requisicoes SET nome_evento='x' WHERE id=?", (request_id,)) is None


@pytest.mark.parametrize("status", ["Deferida", "Deferida Parcialmente", "Indeferida", "Encerrada"])
def test_a_decided_request_stays_frozen(status):
    conn = _fresh()
    _seed(conn)
    message = _refusal(conn, _PAIR, (2, _snapshot(2), _request_id(status)))
    assert message is not None and SNAPSHOT_IMMUTABLE_MESSAGE in message
    # Its other fields keep their v16 behaviour.
    assert _refusal(conn, "UPDATE requisicoes SET observacao='x' WHERE id=?", (_request_id(status),)) is None


@pytest.mark.parametrize("sql, params, message", [
    ("UPDATE requisicoes SET atividade_versao_id=2 WHERE id=?", (), SNAPSHOT_PAIRING_MESSAGE),
    ("UPDATE requisicoes SET regra_snapshot_json=? WHERE id=?", (json.dumps({"atividade_versao_id": 1}),),
     SNAPSHOT_PAIRING_MESSAGE),
    # a new snapshot that still names the old version
    (_PAIR, (2, json.dumps({"atividade_versao_id": 1, "eixo": "AEU"})), SNAPSHOT_IDENTITY_MESSAGE),
    (_PAIR, (2, json.dumps({"atividade_versao_id": "2"})), SNAPSHOT_IDENTITY_MESSAGE),
    (_PAIR, (2, json.dumps({"atividade_versao_id": 2.5})), SNAPSHOT_IDENTITY_MESSAGE),
    (_PAIR, (2, json.dumps({"other": 2})), SNAPSHOT_IDENTITY_MESSAGE),
    (_PAIR, (2, json.dumps([2])), SNAPSHOT_IDENTITY_MESSAGE),
    (_PAIR, (2, "not json"), SNAPSHOT_IDENTITY_MESSAGE),
    ("UPDATE requisicoes SET status='Deferida', atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
     (2, _snapshot(2)), SNAPSHOT_IMMUTABLE_MESSAGE),
])
def test_a_partial_or_mismatched_pair_is_refused_even_while_editable(sql, params, message):
    conn = _fresh()
    _seed(conn)
    refusal = _refusal(conn, sql, (*params, _request_id("Pendente")))
    assert refusal is not None and message in refusal, refusal


# --- PostgreSQL contract ----------------------------------------------------------


def test_the_postgresql_function_states_the_same_rule():
    body = pg_schema.PG_TRIGGER_FUNCTIONS["fn_requisicoes_snapshot_immutable"]
    for status in RECLASSIFIABLE_REQUEST_STATUSES:
        assert f"'{status}'" in body
    for message in (SNAPSHOT_IMMUTABLE_MESSAGE, SNAPSHOT_PAIRING_MESSAGE, SNAPSHOT_IDENTITY_MESSAGE):
        assert f"RAISE EXCEPTION '{message}'" in body
    assert "fn_requisicoes_snapshot_immutable" in pg_schema.PG_UPGRADED_FUNCTIONS
    # The declaration is unchanged: same columns, same timing.
    [trigger] = [t for t in pg_schema.PG_TRIGGERS if t["name"] == "trg_requisicoes_snapshot_immutable"]
    assert trigger["columns"] == ["atividade_versao_id", "regra_snapshot_json"]
    # The upgrade starts only from the frozen v16 body, which is not the v17 one.
    assert pg_schema._PG_V16_SNAPSHOT_FUNCTION_BODY != pg_schema._function_body(body)
    assert pg_schema._PG_V16_CONTRACT_SHA256 != pg_schema.PG_CONTRACT_SHA256


def test_v17_adds_no_table_so_path_b_and_layer2_policies_are_unchanged():
    from app import pg_migrate_from_sqlite as path_b

    assert set(prod1_schema.EXPECTED_TABLES) == set(pg_schema.PG_APPLICATION_TABLES)
    assert path_b.SOURCE_TABLE_POLICIES["requisicoes"].policy == path_b.MIGRATE_EXACT
    validate_prod1_schema(_fresh())


def test_every_status_the_edit_policy_opens_is_reclassifiable_in_the_database():
    # app.requisition_policy owns the edit window; the trigger must never be
    # narrower than it, or an allowed correction would fail in the database.
    import datetime

    from app.requisition_policy import can_student_edit_requisition

    just_now = (datetime.datetime.now() - datetime.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    opened = {status for status in prod1_schema.REQUEST_STATUSES
              if can_student_edit_requisition(status, just_now, return_days=7)}
    assert opened == set(RECLASSIFIABLE_REQUEST_STATUSES)
