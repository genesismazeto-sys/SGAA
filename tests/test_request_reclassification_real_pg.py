"""Real PostgreSQL (E-PG1 / E-PG2): request reclassification and the v16 -> v17 upgrade.

Production runs PostgreSQL, so the v17 trigger function, the owner's
compare-and-set write (``app.request_reclassification``) and the in-place
upgrade (``app.pg_schema.upgrade_pg_schema``) are proven on a real server:
the pair changes only while the request is editable, two writers racing on the
same request never both win, and the upgrade accepts only the frozen v16
contract and serializes with itself.  Skips without ``SGAA_PG_TEST_URL``
(REAL-PG EVIDENCE: ABSENT).  Run-owned databases only, synthetic rows.
"""
from __future__ import annotations

import json
import threading

import pytest

from app import pg_schema
from app.db import write_transaction
from app.prod1_request_reclassification_ddl import (
    SNAPSHOT_IDENTITY_MESSAGE,
    SNAPSHOT_IMMUTABLE_MESSAGE,
    SNAPSHOT_PAIRING_MESSAGE,
)
from app.request_reclassification import (
    HISTORY_KEY,
    ReclassificationConflict,
    apply_reclassification,
    prepare_reclassification,
)
from app.versioning.snapshots import SnapshotProcessingAuthority, read_requisicao_snapshot_for_processing
from tests.storage_mp1_pg_support import PG_URL, Registry, adapter, raw_connection
from tests.storage_mp1_support import REQUEST_ID, STUDENT_ID

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

AAC_TYPE, AEU_TYPE = "Acadêmica Complementar", "Extensão Universitária"
TARGET = 2  # an AEU version the seeded student's Matrix also offers
LOCK_WAIT_SECONDS = 20


@pytest.fixture(scope="module")
def registry():
    registry = Registry("recl")
    try:
        registry.provision_template()
        conn = adapter(f"{PG_URL.rsplit('/', 1)[0]}/{registry.template}")
        try:
            conn.execute("INSERT INTO atividade_base(id,nome_conceito) VALUES(2,'Conceito extensionista')")
            conn.execute("INSERT INTO atividade_versao(id,atividade_base_id,eixo,grupo,numero_versao,status)"
                         " VALUES(2,2,'AEU','2 - Extensão',1,'ativa')")
            conn.execute("INSERT INTO matriz_atividade_versao_item(matriz_id,atividade_base_id,atividade_versao_id)"
                         " VALUES(1,1,1)")
            conn.execute("INSERT INTO matriz_atividade_versao_item(matriz_id,atividade_base_id,atividade_versao_id)"
                         " VALUES(1,2,2)")
            conn.commit()
        finally:
            conn.close()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def database(registry):
    name, url = registry.create(template=registry.template)
    try:
        yield url
    finally:
        registry.drop(name)


@pytest.fixture
def conn(database):
    connection = adapter(database)
    try:
        yield connection
    finally:
        connection.close()


def _row(conn, request_id=REQUEST_ID):
    return dict(conn.execute("SELECT * FROM requisicoes WHERE id=?", (request_id,)).fetchone())


def _prepare(conn, row, target=TARGET, tipo=AEU_TYPE):
    prepared = prepare_reclassification(
        conn, request_row=row, aluno_id=STUDENT_ID, new_version_id=target,
        form_version_id=row["atividade_versao_id"], declared_tipo=tipo,
        flow_origin="aluno_reclassify", actor_role="aluno", actor_user_id=2,
    )
    conn.rollback()
    return prepared


def _set_status(conn, status):
    conn.execute("UPDATE requisicoes SET status=? WHERE id=?", (status, REQUEST_ID))
    conn.commit()


# ===========================================================================
# E-PG1: the owner's write and the trigger
# ===========================================================================


@pytest.mark.parametrize("status", ["Pendente", "Devolvida"])
def test_an_editable_request_is_reclassified_with_a_fresh_valid_snapshot(conn, status):
    _set_status(conn, status)
    before = _row(conn)
    prepared = _prepare(conn, before)
    with write_transaction(conn):
        apply_reclassification(conn, prepared)
    row = _row(conn)
    assert (row["id"], row["atividade_versao_id"], row["status"]) == (REQUEST_ID, TARGET, status)
    read = read_requisicao_snapshot_for_processing(row)
    assert read.authority is SnapshotProcessingAuthority.VALID_AUTHORITATIVE_SNAPSHOT, read.reason
    assert (read.rule.atividade_versao_id, read.rule.eixo, read.rule.matriz_id_efetiva) == (TARGET, "AEU", 1)
    [entry] = read.payload[HISTORY_KEY]
    assert entry["from"]["atividade_versao_id"] == 1 and entry["request_status"] == status
    assert row["data_solicitacao"] == before["data_solicitacao"]


@pytest.mark.parametrize("status", ["Deferida", "Deferida Parcialmente", "Indeferida", "Encerrada"])
def test_a_decided_request_is_refused_by_the_owner_and_the_trigger(conn, status):
    pending = _row(conn)
    prepared = _prepare(conn, pending)
    _set_status(conn, status)
    decided = _row(conn)
    with pytest.raises(ReclassificationConflict):
        with write_transaction(conn):
            apply_reclassification(conn, prepared)
    with pytest.raises(Exception, match=SNAPSHOT_IMMUTABLE_MESSAGE):
        conn.execute("UPDATE requisicoes SET atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
                      (TARGET, prepared.snapshot_json, REQUEST_ID))
    conn.rollback()
    assert _row(conn) == decided


@pytest.mark.parametrize("change, message", [
    ("activity_only", SNAPSHOT_PAIRING_MESSAGE),
    ("snapshot_only", SNAPSHOT_PAIRING_MESSAGE),
    ("snapshot_names_another_version", SNAPSHOT_IDENTITY_MESSAGE),
    ("snapshot_names_it_as_text", SNAPSHOT_IDENTITY_MESSAGE),
    ("snapshot_names_it_as_a_fraction", SNAPSHOT_IDENTITY_MESSAGE),
    ("snapshot_is_not_an_object", SNAPSHOT_IDENTITY_MESSAGE),
    ("decided_in_the_same_statement", SNAPSHOT_IMMUTABLE_MESSAGE),
])
def test_the_trigger_refuses_a_partial_or_mismatched_pair(conn, change, message):
    before = _row(conn)
    snapshot = json.loads(before["regra_snapshot_json"])
    statement, params = {
        "activity_only": ("UPDATE requisicoes SET atividade_versao_id=? WHERE id=?", (TARGET, REQUEST_ID)),
        "snapshot_only": ("UPDATE requisicoes SET regra_snapshot_json=? WHERE id=?",
                          (json.dumps({**snapshot, "eixo": "AEU"}), REQUEST_ID)),
        "snapshot_names_it_as_a_fraction": (
            "UPDATE requisicoes SET atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
            (TARGET, json.dumps({**snapshot, "atividade_versao_id": TARGET + 0.5}), REQUEST_ID)),
        "snapshot_is_not_an_object": (
            "UPDATE requisicoes SET atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
            (TARGET, json.dumps([TARGET]), REQUEST_ID)),
        "snapshot_names_another_version": (
            "UPDATE requisicoes SET atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
            (TARGET, json.dumps({**snapshot, "eixo": "AEU"}), REQUEST_ID)),
        "snapshot_names_it_as_text": (
            "UPDATE requisicoes SET atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
            (TARGET, json.dumps({**snapshot, "atividade_versao_id": str(TARGET)}), REQUEST_ID)),
        "decided_in_the_same_statement": (
            "UPDATE requisicoes SET status='Deferida', atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
            (TARGET, json.dumps({**snapshot, "atividade_versao_id": TARGET}), REQUEST_ID)),
    }[change]
    with pytest.raises(Exception, match=message):
        conn.execute(statement, params)
    conn.rollback()
    assert _row(conn) == before


def test_a_resubmission_may_change_status_and_pair_in_one_statement(conn):
    _set_status(conn, "Devolvida")
    snapshot = {**json.loads(_row(conn)["regra_snapshot_json"]), "atividade_versao_id": TARGET}
    conn.execute("UPDATE requisicoes SET status='Pendente', atividade_versao_id=?, regra_snapshot_json=? WHERE id=?",
                 (TARGET, json.dumps(snapshot), REQUEST_ID))
    conn.commit()
    assert (_row(conn)["status"], _row(conn)["atividade_versao_id"]) == ("Pendente", TARGET)


# ===========================================================================
# E-PG2: two connections on the same request
# ===========================================================================


def _apply_in_thread(url, prepared, outcome):
    other = adapter(url)
    try:
        with write_transaction(other):
            apply_reclassification(other, prepared)
        outcome["result"] = "applied"
    except ReclassificationConflict:
        outcome["result"] = "conflict"
    except Exception as exc:  # pragma: no cover - reported by the assertion below
        outcome["result"] = repr(exc)
    finally:
        other.close()


def _wait_until_blocked(conn, *, relation="requisicoes"):
    for _ in range(200):
        waiting = conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            " AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
        ).fetchone()[0]
        conn.rollback()
        if waiting:
            return
        threading.Event().wait(0.05)
    raise AssertionError(f"the second writer never waited on {relation}")


def test_two_concurrent_corrections_of_the_same_request_never_both_win(database, conn):
    stale = _row(conn)
    first = _prepare(conn, stale, target=TARGET, tipo=AEU_TYPE)
    second = _prepare(conn, stale, target=TARGET, tipo=AEU_TYPE)
    holder = adapter(database)
    try:
        holder.execute("BEGIN")
        apply_reclassification(holder, first)  # row locked, not committed
        outcome = {}
        thread = threading.Thread(target=_apply_in_thread, args=(database, second, outcome))
        thread.start()
        _wait_until_blocked(conn)
        holder.commit()
        thread.join(LOCK_WAIT_SECONDS)
        assert not thread.is_alive()
    finally:
        holder.close()
    # The waiter re-read the row after the commit: the pair it expected is gone.
    assert outcome["result"] == "conflict"
    row = _row(conn)
    assert row["regra_snapshot_json"] == first.snapshot_json
    assert len(json.loads(row["regra_snapshot_json"])[HISTORY_KEY]) == 1


def test_a_decision_committed_while_a_correction_waits_wins(database, conn):
    stale = _row(conn)
    prepared = _prepare(conn, stale)
    holder = adapter(database)
    try:
        holder.execute("BEGIN")
        holder.execute("UPDATE requisicoes SET status='Deferida', horas_deferidas=2 WHERE id=?", (REQUEST_ID,))
        outcome = {}
        thread = threading.Thread(target=_apply_in_thread, args=(database, prepared, outcome))
        thread.start()
        _wait_until_blocked(conn)
        holder.commit()
        thread.join(LOCK_WAIT_SECONDS)
        assert not thread.is_alive()
    finally:
        holder.close()
    assert outcome["result"] == "conflict"
    row = _row(conn)
    assert (row["status"], row["atividade_versao_id"], row["regra_snapshot_json"]) == (
        "Deferida", stale["atividade_versao_id"], stale["regra_snapshot_json"])


# ===========================================================================
# The in-place upgrade v16 -> v17
# ===========================================================================


def _as_frozen_v16(url):
    """Turn a provisioned v17 database into the frozen v16 contract: the only three differences."""
    raw = raw_connection(url)
    try:
        definition = pg_schema.PG_TRIGGER_FUNCTIONS["fn_requisicoes_snapshot_immutable"].strip()
        v16 = definition.replace(pg_schema._function_body(definition), pg_schema._PG_V16_SNAPSHOT_FUNCTION_BODY)
        raw.execute(v16.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
        raw.execute("DELETE FROM schema_migrations WHERE version = 17")
        raw.execute(f"UPDATE {pg_schema.PG_SCHEMA_META_TABLE} SET schema_version = 16, "
                    f"contract_sha256 = '{pg_schema._PG_V16_CONTRACT_SHA256}'")
        raw.commit()
    finally:
        raw.close()


def _meta(url):
    raw = raw_connection(url)
    try:
        return tuple(raw.execute(
            f"SELECT schema_version, contract_sha256 FROM {pg_schema.PG_SCHEMA_META_TABLE}").fetchone())
    finally:
        raw.close()


def test_the_upgrade_moves_the_frozen_v16_contract_to_v17_once(database, conn):
    _as_frozen_v16(database)
    with pytest.raises(pg_schema.PostgresSchemaError):
        pg_schema.validate_database(database)
    # Under v16 the pending request is frozen.
    prepared = _prepare(conn, _row(conn))
    with pytest.raises(Exception, match=SNAPSHOT_IMMUTABLE_MESSAGE):
        with write_transaction(conn):
            apply_reclassification(conn, prepared)

    result = pg_schema.upgrade_database(database)
    assert (result["status"], result["from_version"], result["schema_version"]) == ("upgraded", 16, 17)
    assert _meta(database) == (17, pg_schema.PG_CONTRACT_SHA256)
    assert pg_schema.validate_database(database)["schema_version"] == 17
    assert pg_schema.upgrade_database(database)["status"] == "already_current"
    # The rows are untouched and the new rule is live.
    with write_transaction(conn):
        apply_reclassification(conn, _prepare(conn, _row(conn)))
    assert _row(conn)["atividade_versao_id"] == TARGET


@pytest.mark.parametrize("tamper", ["function_body", "meta_version", "migration_rows"])
def test_the_upgrade_refuses_anything_but_the_frozen_v16_contract_and_writes_nothing(database, tamper):
    _as_frozen_v16(database)
    raw = raw_connection(database)
    try:
        if tamper == "function_body":
            raw.execute("CREATE OR REPLACE FUNCTION fn_requisicoes_snapshot_immutable() RETURNS trigger"
                        " LANGUAGE plpgsql AS $fn$ BEGIN RETURN NEW; END; $fn$")
        elif tamper == "meta_version":
            raw.execute(f"UPDATE {pg_schema.PG_SCHEMA_META_TABLE} SET schema_version = 15")
        else:
            raw.execute("DELETE FROM schema_migrations WHERE version = 16")
        raw.commit()
    finally:
        raw.close()
    before = _meta(database)
    with pytest.raises(pg_schema.PostgresSchemaIncompatibleError):
        pg_schema.upgrade_database(database)
    assert _meta(database) == before


def test_two_concurrent_upgrades_serialize_and_apply_once(database):
    _as_frozen_v16(database)
    holder = raw_connection(database)
    outcome = {}

    def second():
        try:
            outcome["result"] = pg_schema.upgrade_database(database)["status"]
        except Exception as exc:  # pragma: no cover - reported by the assertion below
            outcome["result"] = repr(exc)

    try:
        assert pg_schema.upgrade_pg_schema(holder)["status"] == "upgraded"  # meta row locked
        thread = threading.Thread(target=second)
        thread.start()
        watcher = raw_connection(database, autocommit=True)
        try:
            _wait_until_blocked(_Autocommit(watcher), relation=pg_schema.PG_SCHEMA_META_TABLE)
        finally:
            watcher.close()
        holder.commit()
        thread.join(LOCK_WAIT_SECONDS)
        assert not thread.is_alive()
    finally:
        holder.close()
    assert outcome["result"] == "already_current"
    raw = raw_connection(database)
    try:
        assert raw.execute("SELECT count(*) FROM schema_migrations WHERE version = 17").fetchone()[0] == 1
    finally:
        raw.close()


class _Autocommit:
    """``_wait_until_blocked`` over a raw autocommit connection (rollback is a no-op there)."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        return self._raw.execute(sql, params)

    def rollback(self):
        return None
