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
    assert set(recent[0]) == {"generation_at", "baseline", "objects", "off_platform", "governed", "manifest_short"}
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
    assert policy["pg_database_cadence_hours"] == 24 and policy["configured"] is True
    assert policy["updated_at"] == "2026-10-12 10:00:00"  # only accepted values date the policy
    assert pg_posture.policy_from_rows([]) == dict(pg_posture.default_policy(), configured=False, updated_at=None)


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
    forged = dict(reference, backup_cadence_hours=1)  # a row that is not the ledger's entry decides nothing
    conn.execute("UPDATE sgaa_cutover.opening SET entry = %s", (json.dumps(forged, sort_keys=True),))
    assert pg_posture.read(conn)["ceiling_hours"] is None and pg_posture.opening_ceiling(conn) is None


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
