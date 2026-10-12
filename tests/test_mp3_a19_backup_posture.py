# coding: utf-8
"""MP-3 SPEC A19: the PostgreSQL backup posture the product shows (``app.backup.pg_posture``).

The record of a backup stays where it is made (the cutover ledger's entries, or an ``ops_backup``
run's own receipt); the run publishes that SAME entry into the database it backed up and the
Banco de dados page reads it back.  Each test names the defect it would catch.  The unit lanes run
everywhere; the real-PostgreSQL lanes need ``SGAA_PG_TEST_URL`` (REAL-PG EVIDENCE: ABSENT otherwise).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app import hosting
from app.backup import pg_posture

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
IDENTITY = "a" * 64
OTHER_IDENTITY = "b" * 64


def _stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _generation(hours_ago, *, identity=IDENTITY, objects=True, kind="GENERATION", manifest=None):
    made = NOW - timedelta(hours=hours_ago)
    body = {"type": "backup", "kind": kind, "at": _stamp(made + timedelta(minutes=2)),
            "generation_at": _stamp(made), "manifest_sha256": manifest or ("%064x" % int(hours_ago * 1000 + 1)),
            "dump_sha256": "d" * 64, "source_identity_sha256": identity,
            "object_set_name": "20261012T000000Z-auto-x" if objects else "NONE",
            "object_set_digest": "e" * 64 if objects else "NONE",
            "object_manifest_sha256": "f" * 64 if objects else "NONE",
            "off_platform": "VERIFIED", "provenance": "LIVE_RUN", "run_seconds": 60, "seq": 1, "prev": "0" * 64}
    return dict(body, hash=hosting.ledger_entry_hash(body))


def _restore(of, hours_ago, *, identity=IDENTITY):
    body = {"type": "restore", "at": _stamp(NOW - timedelta(hours=hours_ago)), "manifest_sha256": of["manifest_sha256"],
            "dump_sha256": of["dump_sha256"], "source_identity_sha256": identity, "object_set_digest": "e" * 64,
            "target_identity_sha256": "c" * 64, "target_major": 17, "tables_verified": 39, "objects_verified": 2,
            "restored": "VERIFIED", "object_set": "VERIFIED", "seq": 2, "prev": "1" * 64}
    return dict(body, hash=hosting.ledger_entry_hash(body))


def _rows(*entries, note=None):
    return [(json.dumps(entry, sort_keys=True), json.dumps(note) if note else None) for entry in entries]


def _summary(rows, *, identity=IDENTITY, cadence=24, ceiling=None, **policy):
    return pg_posture.summarize(rows, identity=identity, policy=dict(pg_database_cadence_hours=cadence, **policy),
                                ceiling_hours=ceiling, now=NOW)


# ---- the reading ----------------------------------------------------------------------------------


def test_no_record_is_shown_as_no_protection_never_as_protected():
    posture = _summary([])
    assert posture["state"] == "EMPTY"
    assert posture["database_status"] == "NONE" and posture["objects_status"] == "NONE"
    assert posture["validation"] is None and posture["recent"] == []


def test_a_generation_within_the_cadence_is_current_and_a_late_one_is_late():
    assert _summary(_rows(_generation(30)))["database_status"] == "CURRENT"  # 30 h <= 1.5 x 24 h
    assert _summary(_rows(_generation(37)))["database_status"] == "LATE"  # beyond the tolerance
    assert _summary(_rows(_generation(5)), cadence=2)["database_status"] == "LATE"  # the recorded cadence binds


def test_the_object_set_has_its_own_weekly_cadence():
    posture = _summary(_rows(_generation(2, objects=False), _generation(24 * 9)))
    assert posture["database_status"] == "CURRENT"
    assert posture["objects_status"] == "CURRENT"  # 9 days <= 1.5 weeks
    posture = _summary(_rows(_generation(2, objects=False), _generation(24 * 11)))
    assert posture["objects_status"] == "LATE"
    assert _summary(_rows(_generation(2, objects=False)))["objects_status"] == "NONE"


def test_a_foreign_or_altered_record_is_ignored_and_counted_never_shown_as_protection():
    foreign = _generation(1, identity=OTHER_IDENTITY)
    altered = dict(_generation(2), generation_at=_stamp(NOW))  # the hash no longer matches
    handmade = {"type": "backup", "generation_at": _stamp(NOW)}  # not a ledger entry at all
    posture = _summary(_rows(foreign, altered, handmade) + [("not json", None)])
    assert posture["state"] == "EMPTY" and posture["database_status"] == "NONE"
    assert posture["ignored"] == 4
    # without a proven identity of this database nothing can be attributed to it
    assert _summary(_rows(_generation(1)), identity=None)["state"] == "EMPTY"


def test_the_newest_restore_validation_names_the_generation_it_validated():
    old, new = _generation(48, manifest="1" * 64), _generation(2, manifest="2" * 64)
    posture = _summary(_rows(old, new, _restore(old, 40)))
    assert posture["validation"]["generation_at"] == NOW - timedelta(hours=48)
    assert posture["validation"]["tables_verified"] == 39 and posture["validation"]["objects_verified"] == 2
    assert posture["latest_generation_at"] == NOW - timedelta(hours=2)


def test_the_recent_list_is_newest_first_bounded_and_value_free():
    entries = [_generation(hours) for hours in (1, 30, 5, 70, 9, 100, 3)]
    recent = _summary(_rows(*entries))["recent"]
    assert [item["generation_at"] for item in recent] == sorted((NOW - timedelta(hours=h) for h in (1, 3, 5, 9, 30)),
                                                                reverse=True)
    assert set(recent[0]) == {"generation_at", "baseline", "snapshot", "manifest", "files", "exports", "drives",
                              "destinations", "objects", "off_platform", "governed", "manifest_short"}
    assert len(recent[0]["manifest_short"]) == 12


def test_retention_is_only_the_newest_generations_own_observation_in_its_exact_shape():
    note = {"generations_policy": 2, "kept": {"primary": {"database": 2, "objects": 1},
                                              "off_platform": {"database": 2, "objects": 1}}}
    assert _summary(_rows(_generation(1), note=note) + _rows(_generation(30)))["retention"] == note
    # an older run's counts are never shown as the current rotation
    assert _summary(_rows(_generation(1)) + _rows(_generation(30), note=note))["retention"] is None
    for bad in ({"generations_policy": 2}, dict(note, extra=1), {"generations_policy": "2", "kept": note["kept"]},
                {"generations_policy": 2, "kept": {"primary": {"database": -1, "objects": 0},
                                                   "off_platform": {"database": 2, "objects": 0}}}):
        assert _summary(_rows(_generation(1), note=bad))["retention"] is None, bad
    assert _summary([(_rows(_generation(1))[0][0], "not json")])["retention"] is None


def test_a_self_hashed_row_in_another_shape_is_ignored_never_an_error():
    def hashed(body):
        return dict(body, hash=hosting.ledger_entry_hash(body))

    rows = _rows(
        hashed({"type": "backup", "source_identity_sha256": IDENTITY, "generation_at": _stamp(NOW)}),  # no manifest
        hashed({"type": "backup", "source_identity_sha256": IDENTITY, "manifest_sha256": "1" * 64,
                "generation_at": _stamp(NOW), "object_set_name": 7}),
        hashed({"type": "restore", "source_identity_sha256": IDENTITY, "manifest_sha256": "1" * 64,
                "at": _stamp(NOW), "tables_verified": "many", "objects_verified": 1}),
        hashed({"type": "restore", "source_identity_sha256": IDENTITY, "manifest_sha256": "1" * 64,
                "at": "yesterday", "tables_verified": 1, "objects_verified": 1}),
    )
    posture = _summary(rows)
    assert posture["state"] == "EMPTY" and posture["validation"] is None and posture["ignored"] == 4


def test_an_operator_run_outside_the_window_is_a_self_hashed_receipt_of_the_same_shape():
    record = pg_posture.run_record(generation_at=_stamp(NOW), manifest_sha256="1" * 64, dump_sha256="2" * 64,
                                   source_identity_sha256=IDENTITY, object_set_name=None, object_set_digest=None,
                                   object_manifest_sha256=None, run_seconds=12, at=_stamp(NOW))
    body = dict(record)
    assert hosting.ledger_entry_hash({k: v for k, v in body.items() if k != "hash"}) == record["hash"]
    assert record["provenance"] == pg_posture.RUN_PROVENANCE and record["object_set_name"] == "NONE"
    posture = _summary(_rows(record))
    assert posture["database_status"] == "CURRENT" and posture["recent"][0]["governed"] is False


# ---- the administrator's policy --------------------------------------------------------------------


def test_the_policy_is_validated_field_by_field_and_capped_by_an_open_cutover():
    good = {"pg_database_cadence_hours": "12", "pg_object_cadence_days": "3", "pg_retention_generations": "5",
            "pg_restore_test_days": "14"}
    assert pg_posture.validate_policy(good) == {k: int(v) for k, v in good.items()}
    for key, bad in (("pg_database_cadence_hours", "0"), ("pg_database_cadence_hours", "25"),
                     ("pg_object_cadence_days", "8"), ("pg_retention_generations", "1"),
                     ("pg_retention_generations", "31"), ("pg_restore_test_days", "6"),
                     ("pg_restore_test_days", "x"), ("pg_restore_test_days", "")):
        with pytest.raises(pg_posture.PolicyError) as caught:
            pg_posture.validate_policy(dict(good, **{key: bad}))
        assert "Valor inválido para" in str(caught.value), (key, bad)
    with pytest.raises(pg_posture.PolicyError) as caught:
        pg_posture.validate_policy(good, ceiling_hours=6)
    assert "não pode passar de 6 h" in str(caught.value)
    assert pg_posture.validate_policy(dict(good, pg_database_cadence_hours="6"), ceiling_hours=6)


def test_stored_policy_values_out_of_bounds_fall_back_to_their_defaults():
    policy = pg_posture.policy_from_rows([("pg_retention_generations", "7", "2026-10-12 10:00:00"),
                                          ("pg_restore_test_days", "999", "2026-10-12 11:00:00"),
                                          ("pg_database_cadence_hours", "abc", None)])
    assert policy["pg_retention_generations"] == 7 and policy["pg_restore_test_days"] == 30
    assert policy["pg_database_cadence_hours"] == 24 and policy["configured"] is False  # for display only
    assert policy["invalid"] == ["pg_database_cadence_hours", "pg_restore_test_days"]
    assert policy["updated_at"] == "2026-10-12 10:00:00"  # only accepted values date the policy
    assert pg_posture.policy_from_rows([]) == dict(pg_posture.default_policy(), configured=False, updated_at=None,
                                                   invalid=[])


@pytest.mark.parametrize("stored", ["1", "0", "-5", "abc", "999", "31", "", None, "2.5", "\u0667", " 7x"])
def test_a_run_never_deletes_by_an_invalid_stored_retention(stored):
    """A19 R3 M7: an invalid stored value refuses in strict mode, so the runs keep every generation."""
    from tools import ops_backup

    rows = [(key, str(value), None) for key, value in pg_posture.default_policy().items()]
    rows = [(key, stored if key == "pg_retention_generations" else value, None) for key, value, _ in rows]
    with pytest.raises(pg_posture.PolicyError):
        pg_posture.policy_from_rows(rows, strict=True)

    class Conn:
        def transaction(self):
            import contextlib
            return contextlib.nullcontext()

        def cursor(self, **_kwargs):
            outer = self

            class Cursor:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def execute(self, _sql):
                    return self

                def fetchall(self):
                    return rows
            return Cursor()

        def close(self):
            pass

    assert ops_backup._policy_generations(lambda: Conn(), None) == ops_backup.KEEP_EVERY_GENERATION


def test_a_partly_stored_policy_is_refused_in_strict_mode():
    with pytest.raises(pg_posture.PolicyError):
        pg_posture.policy_from_rows([("pg_retention_generations", "5", None)], strict=True)
    full = [(key, str(value), None) for key, value in pg_posture.default_policy().items()]
    assert pg_posture.policy_from_rows(full, strict=True)["pg_retention_generations"] == 2


def test_the_posture_is_judged_against_the_administrators_policy():
    rows = _rows(_generation(10), _generation(24 * 4))
    assert _summary(rows)["database_status"] == "CURRENT"
    assert _summary(rows, cadence=6)["database_status"] == "LATE"  # 10 h > 1.5 x 6 h
    assert _summary(rows, pg_object_cadence_days=1)["objects_status"] == "CURRENT"  # 10 h <= 1.5 x 1 day
    assert _summary(_rows(_generation(10, objects=False), _generation(24 * 4)),
                    pg_object_cadence_days=2)["objects_status"] == "LATE"  # 4 days > 1.5 x 2 days
    posture = _summary(rows, cadence=12)
    assert posture["next_generation_due"] == NOW - timedelta(hours=10) + timedelta(hours=12)
    assert posture["rpo_hours"] == 12 and posture["retention_generations"] == 2
    # an open cutover's recorded cadence is a ceiling the posture applies
    assert _summary(rows, cadence=24, ceiling=6)["cadence_hours"] == 6


def test_a_restore_validation_older_than_the_policy_interval_is_late():
    old = _generation(24 * 40, manifest="1" * 64)
    rows = _rows(_generation(2), old, _restore(old, 24 * 35))
    assert _summary(rows)["validation_status"] == "LATE"  # 35 days > 30 by default
    assert _summary(rows, pg_restore_test_days=60)["validation_status"] == "CURRENT"
    assert _summary(_rows(_generation(2)))["validation_status"] == "NONE"
    posture = _summary(rows, pg_restore_test_days=60)
    assert posture["next_restore_test_due"] == NOW - timedelta(hours=24 * 35) + timedelta(days=60)


def test_publishing_refuses_a_record_that_is_not_intact_before_touching_the_database():
    class Refusing:
        def transaction(self):
            raise AssertionError("the database must not be touched")

    altered = dict(_generation(1), run_seconds=99)
    with pytest.raises(pg_posture.PostureError) as caught:
        pg_posture.publish(Refusing(), [altered])
    assert caught.value.code == "RECORD_NOT_INTACT"
    with pytest.raises(pg_posture.PostureError):
        pg_posture.publish(Refusing(), [{"type": "advance", "hash": "0" * 64}])


def test_an_unreadable_database_is_the_unreadable_posture_never_an_error():
    class Broken:
        def transaction(self):
            raise RuntimeError("down")

    assert pg_posture.read(Broken()) == {"state": "UNREADABLE"}


# ---- the real PostgreSQL lanes ---------------------------------------------------------------------

from tests.mp2_pg_support import PG_URL  # noqa: E402

real_pg = pytest.mark.skipif(not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT")


@pytest.fixture
def pg_database():
    from tests.mp2_pg_support import Registry, raw_connection

    registry = Registry("a19posture")
    try:
        registry.provision_template()
        name, url = registry.create(template=registry.template)
        conn = raw_connection(url, autocommit=True)
        try:
            yield conn
        finally:
            conn.close()
    finally:
        assert registry.close() == 0


def _identity(conn):
    return hosting.source_identity_sha256(hosting.database_source(conn))


@real_pg
def test_real_pg_published_records_are_read_back_outside_public_and_without_changing_the_business_fingerprint(
        pg_database):
    from tools import pg_fingerprint

    conn = pg_database
    identity = _identity(conn)
    assert identity is not None, "the local cluster must prove its identity for this lane"
    before = pg_fingerprint.snapshot(conn)["fingerprint_sha256"]
    first, second = _generation(1, identity=identity, manifest="3" * 64), _generation(30, identity=identity)
    note = {"generations_policy": 2, "kept": {"primary": {"database": 2, "objects": 2},
                                              "off_platform": {"database": 2, "objects": 2}}}
    assert pg_posture.publish(conn, [first, second], annotations={first["hash"]: note}) == {"published": 2, "already": 0}
    assert pg_posture.publish(conn, [first, second, _restore(first, 0.5, identity=identity)]) == \
        {"published": 1, "already": 2}
    assert pg_fingerprint.snapshot(conn)["fingerprint_sha256"] == before  # not a business write
    assert conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
                        " AND table_name = 'backup_records'").fetchone()[0] == 0
    privileges = conn.execute("SELECT has_table_privilege('public', 'sgaa_ops.backup_records', 'SELECT')").fetchone()[0]
    assert privileges is False
    posture = pg_posture.read(conn, now=datetime.now(timezone.utc))
    assert posture["state"] == "RECORDED" and posture["generations_recorded"] == 2
    assert posture["retention"] == note and posture["validation"]["tables_verified"] == 39
    assert posture["ceiling_hours"] is None and posture["cadence_hours"] == pg_posture.DEFAULT_CADENCE_HOURS


@real_pg
def test_real_pg_the_cadence_is_the_one_the_opening_recorded(pg_database):
    conn = pg_database
    reference = {"type": "reference", "backup_cadence_hours": 6, "rpo_hours": 6, "seq": 45, "prev": "0" * 64,
                 "database_identity_sha256": OTHER_IDENTITY}
    reference["hash"] = hosting.ledger_entry_hash(reference)
    for statement in hosting.OPENING_DDL:
        conn.execute(statement)
    conn.execute(hosting.OPENING_INSERT_SQL, (reference["hash"], "7" * 64, json.dumps(reference, sort_keys=True)))
    assert pg_posture.read(conn)["ceiling_hours"] is None  # another database's opening decides nothing
    conn.execute("DELETE FROM sgaa_cutover.opening")
    reference = dict({k: v for k, v in reference.items() if k != "hash"}, database_identity_sha256=_identity(conn))
    reference["hash"] = hosting.ledger_entry_hash(reference)
    for statement in hosting.OPENING_DDL:
        conn.execute(statement)
    conn.execute(hosting.OPENING_INSERT_SQL, (reference["hash"], "7" * 64, json.dumps(reference, sort_keys=True)))
    posture = pg_posture.read(conn)
    assert (posture["cadence_hours"], posture["ceiling_hours"], posture["rpo_hours"]) == (6, 6, 6)
    assert pg_posture.opening_ceiling(conn) == 6
    forged = dict(reference, backup_cadence_hours=1)  # a row that is not the ledger's entry: unverifiable
    conn.execute("UPDATE sgaa_cutover.opening SET entry = %s", (json.dumps(forged, sort_keys=True),))
    with pytest.raises(pg_posture.CeilingUnverifiable):
        pg_posture.opening_ceiling(conn)
    posture = pg_posture.read(conn)
    assert posture["ceiling_unverified"] is True and posture["database_status"] != "CURRENT"
    conn.execute("UPDATE sgaa_cutover.opening SET entry = %s", ("not json",))
    with pytest.raises(pg_posture.CeilingUnverifiable):
        pg_posture.opening_ceiling(conn)


@real_pg
def test_real_pg_the_reading_never_disturbs_the_callers_transaction(pg_database):
    from tests.mp2_pg_support import raw_connection

    url = pg_database.info.dsn
    conn = raw_connection(url)  # not autocommit: a request's transaction is open
    try:
        conn.execute("SELECT 1")
        conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")  # any statement of the request
        assert pg_posture.read(conn)["state"] == "EMPTY"
        conn.execute("CREATE SCHEMA sgaa_ops")
        conn.execute("CREATE TABLE sgaa_ops.backup_records (entry_hash text)")  # an unreadable shape
        assert pg_posture.read(conn) == {"state": "UNREADABLE"}
        assert conn.execute("SELECT 2").fetchone()[0] == 2  # the caller's transaction is still usable
    finally:
        conn.rollback()
        conn.close()


@real_pg
def test_real_pg_a_read_only_database_refuses_the_publication(pg_database):
    import psycopg

    conn = pg_database
    conn.execute("SET default_transaction_read_only = on")  # what the C12 write barrier sets for the role
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        pg_posture.publish(conn, [_generation(1, identity=_identity(conn))])


def test_a_run_that_cannot_read_the_policy_keeps_every_generation():
    """Review (A19 (8)): a deletion is never decided by a policy the run could not read."""
    from tools import ops_backup

    def broken():
        raise RuntimeError("unreachable")

    assert ops_backup._policy_generations(broken, None) == ops_backup.KEEP_EVERY_GENERATION
    assert ops_backup._policy_generations(broken, 3) == ops_backup.KEEP_EVERY_GENERATION

    class Refusing:
        def transaction(self):
            raise RuntimeError("refused")

        def close(self):
            pass

    assert ops_backup._policy_generations(Refusing, None) == ops_backup.KEEP_EVERY_GENERATION
    with pytest.raises(RuntimeError):
        pg_posture.read_policy(Refusing(), strict=True)
    assert pg_posture.read_policy(Refusing())["pg_retention_generations"] == pg_posture.MIN_GENERATIONS


# ---- "Gerar backup agora" under PostgreSQL (app.backup.pg_snapshot) ----------------------------------


def test_pruning_only_ever_deletes_sgaa_snapshots_and_keeps_the_newest():
    from app.backup import pg_snapshot

    listed = [{"id": "a", "name": "sgaa-pg-snapshot-20261010T000000Z.db"},
              {"id": "b", "name": "sgaa-pg-snapshot-20261012T000000Z.db"},
              {"id": "c", "name": "sgaa-pg-snapshot-20261011T000000Z.db"},
              {"id": "d", "name": "sgaa_backup_20240101.db"},  # a legacy SQLite backup in the same folder
              {"id": "e", "name": "sgaa-pg-snapshot-20261009T000000Z.db.part"},
              {"id": "f", "name": "sgaa-pg-snapshot-manual.db"},  # a renamed copy: never a candidate
              {"id": "g", "name": "sgaa-pg-snapshot-zzzz.db"},  # would sort above every stamp
              {"id": None, "name": "sgaa-pg-snapshot-20261008T000000Z.db"}]
    deleted = []
    assert pg_snapshot.prune(listed, 2, deleted.append) == ["sgaa-pg-snapshot-20261010T000000Z.db"]
    assert deleted == ["a"]  # the new snapshot and the newest older one stay; nothing else is touched
    registers = [{"id": "r1", "name": "sgaa-registros-20261010T000000Z.zip"},
                 {"id": "r2", "name": "sgaa-registros-20261012T000000Z.zip"},
                 {"id": "r3", "name": "sgaa-pg-snapshot-20261009T000000Z.db"}]
    removed = []
    assert pg_snapshot.prune(registers, 1, removed.append, pattern=pg_snapshot.REGISTERS_NAME) == \
        ["sgaa-registros-20261010T000000Z.zip"] and removed == ["r1"]  # each kind prunes only its own
    deleted.clear()
    assert pg_snapshot.prune(listed, 0, deleted.append) == ["sgaa-pg-snapshot-20261011T000000Z.db",
                                                           "sgaa-pg-snapshot-20261010T000000Z.db"]  # never below one


@pytest.fixture
def business_database():
    from tests.storage_mp1_pg_support import Registry

    registry = Registry("a19snap")
    try:
        registry.provision_template()
        source = registry.create(template=registry.template)
        target = registry.create()
        yield source[1], target[1]
    finally:
        assert registry.close() == 0


@real_pg
def test_real_pg_a_snapshot_is_proven_equal_and_restores_through_path_b(business_database, tmp_path):
    import sqlite3

    from app import pg_migrate_from_sqlite as pathb
    from app import pg_schema
    from app.backup import pg_snapshot
    from tests.mp2_pg_support import raw_connection
    from tools import pg_fingerprint

    source_url, target_url = business_database
    seeded = raw_connection(source_url, autocommit=True)
    try:  # a production account always carries its credential row (Path-B's domain check)
        seeded.execute("INSERT INTO usuario_credenciais(usuario_id, estado) SELECT id, 'personal' FROM usuarios"
                       " ON CONFLICT DO NOTHING")
    finally:
        seeded.close()
    snap = pg_snapshot.create(tmp_path, connect=lambda: raw_connection(source_url))
    assert snap["file_name"].startswith(pg_snapshot.SNAPSHOT_PREFIX) and snap["rows"] > 0
    # the readable registers: one CSV per register, from the same snapshot, never a secret
    import csv
    import io
    import zipfile

    assert pg_snapshot.REGISTERS_NAME.fullmatch(snap["registers_file_name"])
    with zipfile.ZipFile(snap["registers_path"]) as archive:
        names = set(archive.namelist())
        assert {"alunos.csv", "turmas.csv", "matrizes_atividades.csv", "requisicoes.csv", "LEIA-ME.txt"} <= names
        assert not names & {"usuario_credenciais.csv", "cloud_accounts.csv", "senha_tokens.csv", "usuarios_foto.csv"}
        text = archive.read("usuarios.csv").decode("utf-8")
        assert text.startswith("\ufeff")
        header = next(csv.reader(io.StringIO(text.lstrip("\ufeff")), delimiter=";"))
        assert "senha" not in header and "email" in header
        counted = raw_connection(source_url, autocommit=True)
        try:
            for table in ("alunos", "requisicoes", "turmas"):
                body = archive.read(f"{table}.csv").decode("utf-8").lstrip("\ufeff")
                rows = list(csv.reader(io.StringIO(body), delimiter=";"))
                assert len(rows) - 1 == counted.execute(f"SELECT count(*) FROM {table}").fetchone()[0], table
        finally:
            counted.close()
    lite = sqlite3.connect(snap["path"])
    try:
        assert lite.execute("PRAGMA user_version").fetchone()[0] == 16
        counters = dict(lite.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
    finally:
        lite.close()
    # the next-id counters travel with the snapshot: never below what the source has issued
    check = raw_connection(source_url, autocommit=True)
    try:
        for table, seq in counters.items():
            column = pathb._identity_column(table)
            if column is None:
                continue
            sequence = check.execute("SELECT pg_get_serial_sequence(%s, %s)", (table, column)).fetchone()[0]
            last, called = check.execute(f"SELECT last_value, is_called FROM {sequence}").fetchone()
            assert seq >= (last if called else last - 1), table
    finally:
        check.close()
    source = raw_connection(source_url, autocommit=True)
    assert snap["source_identity_sha256"] == hosting.source_identity_sha256(hosting.database_source(source))
    # restore: the qualified Path-B tool loads the snapshot into an empty provisioned database
    target = raw_connection(target_url)
    pg_schema.provision_pg_schema(target)
    target.commit()
    target.close()
    pathb.migrate(snap["path"], snap["sha256"], database_url=target_url, apply=True)
    target = raw_connection(target_url, autocommit=True)
    try:
        assert pg_fingerprint.snapshot(target)["fingerprint_sha256"] == \
            pg_fingerprint.snapshot(source)["fingerprint_sha256"]
    finally:
        target.close()
        source.close()


@real_pg
def test_real_pg_a_snapshot_that_does_not_equal_its_source_is_refused_and_removed(business_database, tmp_path,
                                                                                    monkeypatch):
    from app.backup import pg_snapshot

    import sqlite3

    from tests.mp2_pg_support import raw_connection

    source_url, _target = business_database
    real_read = pg_snapshot.pathb.read_target_rows

    def lossy(conn, table):  # the file loses one row of one table on its way to disk
        rows = real_read(conn, table)
        return rows[1:] if isinstance(conn, sqlite3.Connection) and table == "usuarios" and rows else rows

    monkeypatch.setattr(pg_snapshot.pathb, "read_target_rows", lossy)
    with pytest.raises(pg_snapshot.SnapshotError) as caught:
        pg_snapshot.create(tmp_path, connect=lambda: raw_connection(source_url))
    assert caught.value.code == "SNAPSHOT_TABLE_DIFFERS"
    assert list(tmp_path.iterdir()) == []


def test_listings_follow_every_page_and_onedrive_addresses_the_receipts_drive(monkeypatch):
    """A19 R3 N3 and M5."""
    from app import cloud_drives

    calls = []

    def api(url, token=None, **_kwargs):
        calls.append(url)
        if "googleapis" in url:
            if "pageToken=" not in url:
                return {"files": [{"id": "g1", "name": "sgaa-pg-snapshot-20261002T000000Z.db"}], "nextPageToken": "p2"}
            return {"files": [{"id": "g2", "name": "sgaa-pg-snapshot-20261001T000000Z.db"}]}
        if url.endswith("&page=2"):
            return {"value": [{"id": "o2", "name": "b"}], "@odata.nextLink": "https://evil.example.invalid/next"}
        if "children" in url:
            return {"value": [{"id": "o1", "name": "a"}],
                    "@odata.nextLink": cloud_drives._GRAPH + "/me/drive/root/children?$top=200&page=2"}
        return {"@microsoft.graph.downloadUrl": "https://download.example.invalid/x"}

    monkeypatch.setattr(cloud_drives, "_api", api)
    assert [f["id"] for f in cloud_drives.google_list_folder_files("t", "folder", "sgaa-pg-snapshot-")] == ["g1", "g2"]
    listed = cloud_drives.onedrive_list_folder_children("t", folder_id=None, drive_id=None, folder_path="SGAA")
    assert [f["id"] for f in listed] == ["o1", "o2"]  # a continuation outside Graph is never followed
    assert not any("evil" in url for url in calls)
    cloud_drives.onedrive_download_url("t", "ITEM", drive_id="b!DRIVE")
    assert "/drives/b%21DRIVE/items/ITEM" in calls[-1]
    cloud_drives.onedrive_download_url("t", "ITEM")
    assert "/me/drive/items/ITEM" in calls[-1]


def test_a_receipt_names_the_drive_and_ownership_reads_every_receipt():
    record = pg_posture.run_record(
        generation_at="2026-10-12T10:00:00Z", manifest_sha256="a" * 64, dump_sha256="a" * 64,
        source_identity_sha256=IDENTITY, object_set_name=None, object_set_digest=None,
        object_manifest_sha256=None, run_seconds=3, at="2026-10-12T10:00:00Z", kind=pg_posture.SNAPSHOT_KIND,
        provenance=pg_posture.HOSTED_PROVENANCE, destinations=("onedrive",), files={"onedrive": "ITEM1"},
        exports={"onedrive": "ITEM2"}, drives={"onedrive": "b!DRIVE"})
    posture = pg_posture.summarize([(json.dumps(record), None)], identity=IDENTITY, now=NOW)
    assert posture["recent"][0]["drives"] == {"onedrive": "b!DRIVE"}


def test_the_google_listing_filters_names_itself_and_builds_a_valid_url(monkeypatch):
    """Review (A19 (9)): Drive's word-based ``contains`` is not trusted to select snapshot names."""
    from app import cloud_drives

    calls = []
    monkeypatch.setattr(cloud_drives, "_api", lambda url, token=None, **_k: calls.append(url) or {"files": [
        {"id": "1", "name": "sgaa-pg-snapshot-20261012T000000Z.db"}, {"id": "2", "name": "sgaa_backup_old.db"},
        {"id": "3", "name": "copia sgaa-pg-snapshot-20261011T000000Z.db"}]})
    listed = cloud_drives.google_list_folder_files("tok", "FOLDER", "sgaa-pg-snapshot-")
    assert [f["id"] for f in listed] == ["1"]
    assert " " not in calls[0] and "contains" not in calls[0] and "FOLDER" in calls[0]


# ---- "Recuperar banco de dados" under PostgreSQL (app.backup.pg_restore) -------------------------------


def _with_credentials(url):
    from tests.mp2_pg_support import raw_connection

    conn = raw_connection(url, autocommit=True)
    try:  # a production account always carries its credential row (Path-B's domain check)
        conn.execute("INSERT INTO usuario_credenciais(usuario_id, estado) SELECT id, 'personal' FROM usuarios"
                     " ON CONFLICT DO NOTHING")
    finally:
        conn.close()


@real_pg
def test_real_pg_a_restore_brings_the_registers_back_exactly_and_never_reuses_an_id(business_database, tmp_path):
    from app.backup import pg_restore, pg_snapshot
    from app import pg_migrate_from_sqlite as pathb
    from tests.mp2_pg_support import raw_connection
    from tools import pg_fingerprint

    url, _target = business_database
    _with_credentials(url)
    connect = lambda: raw_connection(url)  # noqa: E731
    snap = pg_snapshot.create(tmp_path, connect=connect)
    # an upload abandoned before the backup (still 'issued', long expired) does not make the file
    # unrestorable: the cutover freeze check is not a restore's, and the restore clears intents
    import sqlite3

    lite = sqlite3.connect(snap["path"])
    try:
        actor = lite.execute("SELECT min(id) FROM usuarios").fetchone()[0]
        lite.execute(
            "INSERT INTO storage_upload_intents (id, actor_user_id, purpose, operation_id, storage_bucket, "
            "storage_key, declared_mime_type, declared_size_bytes, declared_sha256, state, issued_at, expires_at, "
            "sweep_after) VALUES (?, ?, 'comprovante', 'op-abandoned', 'sgaa-documentos', ?, 'application/pdf', 5, ?, "
            "'issued', '2020-01-02 03:04:05', '2020-01-02 03:19:05', '2020-01-03 00:00:00')",
            ("3" * 32, actor, "comprovantes/2020/01/" + "9" * 32, "a" * 64))
        lite.commit()
    finally:
        lite.close()
    with pytest.raises(pg_restore.RestoreError) as caught:  # not the chosen generation: refused
        pg_restore.read(snap["path"], expected_sha256="0" * 64)
    assert caught.value.code == "SNAPSHOT_NOT_THE_GENERATION"
    conn = raw_connection(url, autocommit=True)
    try:
        expected = pg_fingerprint.snapshot(conn)["fingerprint_sha256"]
        # life goes on after the backup: a register changes, a new one appears (it takes an id)
        conn.execute("UPDATE turmas SET nome = nome || ' (alterada)'")
        conn.execute("INSERT INTO cursos (codigo, nome, duracao_periodos) VALUES ('DEPOIS-1', 'Curso depois do backup', 8)")
        issued = pathb.next_identity_value(conn, "cursos") - 1
        assert pg_fingerprint.snapshot(conn)["fingerprint_sha256"] != expected
        result = pg_restore.restore(pg_restore.read(snap["path"]), connect=connect, before=lambda: True)
        assert result["rows"] > 0
        assert pg_fingerprint.snapshot(conn)["fingerprint_sha256"] == expected  # exactly the backup's registers
        assert pathb.next_identity_value(conn, "cursos") > issued  # the id issued after the backup is never reused
        assert conn.execute("SELECT count(*) FROM storage_upload_intents").fetchone()[0] == 0
    finally:
        conn.close()


@real_pg
def test_real_pg_no_write_falls_between_the_safety_copy_and_the_replacement(business_database, tmp_path):
    """A19 R3 M3: the registers are locked against writes before the safety copy is made."""
    import threading

    import psycopg

    from app.backup import pg_restore, pg_snapshot
    from tests.mp2_pg_support import raw_connection

    url, _target = business_database
    _with_credentials(url)
    connect = lambda: raw_connection(url)  # noqa: E731
    snap = pg_snapshot.create(tmp_path, connect=connect)
    snapshot = pg_restore.read(snap["path"])
    outcome = {}

    def writer():
        other = raw_connection(url, autocommit=True)
        try:
            other.execute("SET lock_timeout = '1s'")
            other.execute("UPDATE turmas SET nome = nome || ' (durante)'")
            outcome["written"] = True
        except psycopg.errors.LockNotAvailable:
            outcome["written"] = False
        finally:
            other.close()

    def safety_copy():
        thread = threading.Thread(target=writer)
        thread.start()
        thread.join()
        safety = pg_snapshot.create(tmp_path / "safety", connect=connect)  # reads go on under the lock
        outcome["copied"] = bool(safety["rows"])
        return True

    (tmp_path / "safety").mkdir()
    pg_restore.restore(snapshot, connect=connect, before=safety_copy)
    assert outcome == {"written": False, "copied": True}  # the write could not slip in between


@real_pg
def test_real_pg_a_restore_that_cannot_be_proven_changes_nothing(business_database, tmp_path, monkeypatch):
    import sqlite3

    from app.backup import pg_restore, pg_snapshot
    from tests.mp2_pg_support import raw_connection
    from tools import pg_fingerprint

    url, _target = business_database
    _with_credentials(url)
    connect = lambda: raw_connection(url)  # noqa: E731
    snap = pg_snapshot.create(tmp_path, connect=connect)
    conn = raw_connection(url, autocommit=True)
    try:
        conn.execute("UPDATE turmas SET nome = nome || ' (depois)'")
        before = pg_fingerprint.snapshot(conn)["fingerprint_sha256"]
        snapshot = pg_restore.read(snap["path"])
        real_read = pg_restore.pathb.read_target_rows
        monkeypatch.setattr(pg_restore.pathb, "read_target_rows",  # the proof sees a lost row
                            lambda c, table: real_read(c, table)[1:] if table == "turmas" else real_read(c, table))
        with pytest.raises(pg_restore.RestoreError) as caught:
            pg_restore.restore(snapshot, connect=connect, before=lambda: True)
        assert caught.value.code == "RESTORE_TABLE_DIFFERS"
        monkeypatch.undo()
        with pytest.raises(pg_restore.RestoreError) as caught:  # no safety copy: nothing changes
            pg_restore.restore(snapshot, connect=connect, before=lambda: False)
        assert caught.value.code == "SAFETY_COPY_NOT_SENT"
        assert pg_fingerprint.snapshot(conn)["fingerprint_sha256"] == before
        monkeypatch.undo()
        assert pg_fingerprint.snapshot(conn)["fingerprint_sha256"] == before  # rolled back: nothing changed
        broken = tmp_path / "broken.db"
        broken.write_bytes(b"not a database")
        with pytest.raises(pg_restore.RestoreError):
            pg_restore.read(broken)
        lite = sqlite3.connect(snap["path"])
        try:
            lite.execute("PRAGMA user_version = 15")
            lite.commit()
        finally:
            lite.close()
        with pytest.raises(pg_restore.RestoreError) as caught:
            pg_restore.read(snap["path"])
        assert caught.value.code == "SOURCE_SCHEMA_UNSUPPORTED"
    finally:
        conn.close()
