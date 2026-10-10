# coding: utf-8
"""MP-3 slice 6: the DEV dress rehearsal of the cutover state machine (opt-in, live).

Enabled only with ``SGAA_MP3_REHEARSAL=1``, ``SGAA_PG_TEST_URL`` (PostgreSQL of the
production major, the stand-in for PROD) and the DEV Storage credential file
(``SGAA_DEV_ENV_FILE``, default ``~/.sgaa/s3a-rehearsal.env``).  It uses a
synthetic production-shaped source, the REAL Supabase DEV Storage (one private
run-owned bucket, deleted at the end) and a disposable PostgreSQL database; the
Drive is the deterministic fake because no DEV Google exists.  Every state of the
SPEC's section 3.3 is driven through ``tools/cutover_ledger.py``; evidence is
produced by the tools, not typed.

Outputs are searched for the sentinel planted inside the document bytes.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests import mp3_rehearsal_support as rs
from tests.mp2_pg_support import PG_URL, Registry

pytestmark = pytest.mark.skipif(
    not (rs.enabled() and PG_URL),
    reason="the dress rehearsal needs SGAA_MP3_REHEARSAL=1, SGAA_PG_TEST_URL and the DEV Storage credential file",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "ZZLEAK-MP3-REHEARSAL-7f3a91"
GATES_BEFORE_OPEN = ["GP0", "GP1", "GP2", "GR0", "GR1", "GR2", "GR3", "GB1", "GD1", "GG1", "GG2", "GD2", "GO"]


@pytest.fixture(scope="module")
def dev_bucket():
    bucket = rs.RunBucket(rs.load_dev_env())
    bucket.create()
    try:
        yield bucket
    finally:
        bucket.purge_and_delete()


@pytest.fixture(scope="module")
def registry():
    registry = Registry("rehearsal")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


def _norm(text: str) -> str:
    return text.upper().replace(":", "_").replace("-", "_")


def _unconverged(census, *, include_eligible: bool = False) -> list:
    """The accepted-exception list from a census: the blocked classes with their counts."""
    classes: dict[str, int] = {}
    for table, report in census["documents"].items():
        for name, count in report["blocked"].items():
            key = _norm(f"{table.upper()}_{name}")
            classes[key] = classes.get(key, 0) + int(count)
        # An eligible row that is still unconverged (a conflict, a failed upload) is never an accepted class.
        for provider, count in report["eligible"].items():
            if include_eligible and int(count):
                key = _norm(f"{table.upper()}_{provider}_ELIGIBLE_UNCONVERGED")
                classes[key] = classes.get(key, 0) + int(count)
    return [{"class": name, "count": count} for name, count in sorted(classes.items())]


def test_the_cutover_state_machine_runs_c0_to_c14_on_dev(tmp_path, monkeypatch, dev_bucket, registry):
    from app import pg_migrate_from_sqlite as pathb
    from app.storage import legacy_convergence, object_backup, storage_audit
    from tools import cutover_ledger as ledger
    from tools import deploy_audit, pg_backup, pg_fingerprint

    custody = tmp_path / "custody"
    source = rs.build_source(tmp_path / "workstation", SENTINEL)
    ledger_dir = tmp_path / "ledger"
    ledger.init(ledger_dir)
    for index, gate in enumerate(GATES_BEFORE_OPEN + ["GP3"]):
        ledger.grant(ledger_dir, gate, f"rehearsal-{index}")

    head = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    ledger.advance(ledger_dir, "C0", {
        "commit": head, "runbook_sha256": rs.sha256_file(REPO_ROOT / "docs" / "PRODUCTION_CUTOVER_RUNBOOK.md"),
        "rehearsal_index_sha256": "0" * 63 + "1", "review_verdict": "PASS",
    })

    # ---- C1: the target is qualified empty ---------------------------------------------------
    target_name, target_url = registry.create(template=registry.template)
    with rs.application(database_url=target_url, store=dev_bucket.store) as target:
        from app import pg_schema

        assert pg_schema.validate_pg_schema(target.conn.raw_connection)["table_count"] > 0
        # The provisioner seeds its own migration markers; "empty" is what Path-B itself requires.
        rows = sum(count for table, count in pathb._application_row_counts(target.conn.raw_connection).items()
                   if table != "schema_migrations")
        major = int(target.conn.execute("SHOW server_version_num").fetchone()[0]) // 10000
        target.conn.rollback()
    listed = dev_bucket.store.list_objects(dev_bucket.name, "", max_objects=100)
    ledger.advance(ledger_dir, "C1", {
        "pg_major": major, "schema_current": True, "rows": rows, "objects": len(listed),
        "data_api_toggle_off": True, "data_api_probe": "NOT_SERVED", "api_exposure_clean": True,
        "capacity_ok": True,
    })

    # ---- C2: census of a snapshot copy -------------------------------------------------------
    snapshot = custody / "snapshot.db"
    custody.mkdir()
    with sqlite3.connect(f"file:{source.database}?mode=ro", uri=True) as src, sqlite3.connect(snapshot) as dst:
        src.backup(dst)
    with rs.application(database=snapshot, store=dev_bucket.store, drive=source.drive,
                        documentos=source.documentos, uploads=source.uploads) as snap:
        census = storage_audit.census(snap.conn)
    ledger.advance(ledger_dir, "C2", {
        "database_bytes": snapshot.stat().st_size, "document_bytes": 1,
        "census": {_norm(f"{t}_{k}"): int(v) for t, r in census["documents"].items()
                   for k, v in r["eligible"].items()},
    })

    # ---- C3: freeze --------------------------------------------------------------------------
    frozen = custody / "frozen.db"
    shutil.copyfile(source.database, frozen)
    frozen_sha = rs.sha256_file(frozen)
    ledger.advance(ledger_dir, "C3", {"source_size": frozen.stat().st_size, "source_sha256": frozen_sha,
                                      "wal_bytes": 0})

    # ---- C4: prepare the copy ----------------------------------------------------------------
    prepared = custody / "prepared.db"
    shutil.copyfile(frozen, prepared)
    check = sqlite3.connect(prepared)
    integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    fk_violations = len(check.execute("PRAGMA foreign_key_check").fetchall())
    check.close()
    with rs.application(database=prepared, store=dev_bucket.store, drive=source.drive,
                        documentos=source.documentos, uploads=source.uploads) as prep:
        prepared_census = storage_audit.census(prep.conn)
    accepted = _unconverged(prepared_census)
    assert accepted == [{"class": "REQUISICAO_ARQUIVOS_GOOGLE_TRASHED", "count": 1}], accepted
    ledger.advance(ledger_dir, "C4", {
        "source_sha256": frozen_sha, "prepared_sha256": rs.sha256_file(prepared), "integrity_ok": integrity == "ok",
        "fk_violations": fk_violations, "schema_version": 16, "accepted_exceptions": accepted,
        "accepted_by_user": True,
    })

    # ---- C5: converge into the real DEV bucket -----------------------------------------------
    prepared_sha = rs.sha256_file(prepared)
    from app.storage import drive_mirror

    with rs.application(database=prepared, store=dev_bucket.store, drive=source.drive,
                        documentos=source.documentos, uploads=source.uploads) as prep:
        dry = legacy_convergence.converge(
            prep.conn, apply=False, limit=100, tables=legacy_convergence.TABLES, store=None, bucket=None,
            drive=drive_mirror.active_drive(prep.conn), roots=source.roots,
        )
        assert dry.clean
        report = legacy_convergence.converge(
            prep.conn, apply=True, limit=100, tables=legacy_convergence.TABLES, store=dev_bucket.store,
            bucket=dev_bucket.name, drive=drive_mirror.active_drive(prep.conn), roots=source.roots,
        )
        prep.conn.commit()
        after = storage_audit.census(prep.conn)
    expected_rows = sum(source.counts.values())
    converged_rows = sum(sum(r["converged"].values()) for r in after["documents"].values())
    assert converged_rows == expected_rows
    ledger.advance(ledger_dir, "C5", {
        "prepared_sha256": prepared_sha, "converged_rows": converged_rows,
        "unconverged": _unconverged(after, include_eligible=True), "legacy_bytes_touched": 0,
    })
    assert rs.sha256_file(prepared) != prepared_sha  # the COPY gained links; legacy bytes were only read

    # ---- C6: cross-check the converged copy against the real bucket --------------------------
    with rs.application(database=prepared, store=dev_bucket.store, drive=source.drive,
                        documentos=source.documentos, uploads=source.uploads) as prep:
        cross = storage_audit.cross_check(prep.conn, store=dev_bucket.store, deep=True, listing=True,
                                          buckets=(dev_bucket.name,))
    assert cross["verdict"]["references_consistent"] and cross["verdict"]["storage_consistent"] is True
    converged_sha = rs.sha256_file(prepared)
    ledger.advance(ledger_dir, "C6", {
        "prepared_sha256": prepared_sha, "reference_digest": cross["reference_digest"], "verdict": "CLEAN",
    })
    # The ledger's C7 identity is the prepared copy's identity at C4 (what was carried forward).

    # ---- C7: Path-B into the PostgreSQL stand-in ---------------------------------------------
    monkeypatch.setenv("DATABASE_URL", target_url)
    dry_report = pathb.migrate(str(prepared), converged_sha, database_url=target_url, apply=False)
    assert dry_report is not None
    pathb.migrate(str(prepared), converged_sha, database_url=target_url, apply=True)
    ledger.advance(ledger_dir, "C7", {"prepared_sha256": prepared_sha, "pathb_exit": 0,
                                      "commit_resolved_by_inspection": False, "commit_outcome": "COMMITTED"})

    # ---- C8: the target reproduces the digest; baseline, object set, restore drill -----------
    with rs.application(database_url=target_url, store=dev_bucket.store) as target:
        target_cross = storage_audit.cross_check(target.conn, store=dev_bucket.store, deep=True, listing=True,
                                                 buckets=(dev_bucket.name,))
        target.conn.rollback()
        assert target_cross["reference_digest"] == cross["reference_digest"]
        object_dir = custody / "objects"
        objects = object_backup.backup(target.conn, dev_bucket.store, str(object_dir), label="rehearsal")
        assert objects.ok
        verified = object_backup.verify_set(str(object_dir), conn=target.conn)
        assert verified.ok
        target.conn.rollback()
    monkeypatch.setenv(pg_backup.SOURCE_URL_ENV, target_url)
    monkeypatch.delenv(pg_backup.TARGET_URL_ENV, raising=False)
    sets = custody / "layer2"
    sets.mkdir()
    backup = pg_backup.backup(str(sets), "cutover-baseline")
    manifest = next(sets.glob("*.manifest.json"))
    scratch_name, scratch_url = registry.create()
    pg_backup.restore(str(manifest), target_url=scratch_url)
    loaded = pg_backup.verify_artifact(str(manifest))
    pg_backup.verify_database(loaded.manifest, scratch_url)
    registry.drop(scratch_name)
    ledger.advance(ledger_dir, "C8", {
        "reference_digest": target_cross["reference_digest"], "census_equal": True,
        "baseline_manifest_sha256": rs.sha256_file(manifest), "object_set_digest": backup.manifest["artifact"]["sha256"],
        "restore_drill": "OK", "verify_backup": "OK", "admin_bootstrap": "NOT_NEEDED",
    })

    # ---- C9: the deployment source -----------------------------------------------------------
    export_dir = tmp_path / "upload"
    exported = deploy_audit.export(head, export_dir)
    assert deploy_audit.audit(export_dir, sentinels=[SENTINEL.encode()])["findings"] == []
    ledger.advance(ledger_dir, "C9", {"commit": head, "readiness": "READY", "bundle_audit": "CLEAN",
                                      "scheduler_front": "DISABLED"})
    assert exported["files"] > 50

    # ---- C10: the smoke's write set is proven by a before/after fingerprint -------------------
    monkeypatch.setenv("DATABASE_URL", target_url)
    before_smoke = custody / "before-smoke.json"
    assert pg_fingerprint.main(["snapshot", "--out", str(before_smoke)]) == 0
    # (the public smoke itself runs against the real application in test_mp3_smoke_real_app; the
    # rehearsal pins the ledger-side contract: identical fingerprints are what write_set_ok means)
    after_smoke = custody / "after-smoke.json"
    assert pg_fingerprint.main(["snapshot", "--out", str(after_smoke)]) == 0
    assert pg_fingerprint.compare(json.loads(before_smoke.read_text()), json.loads(after_smoke.read_text()))[
        "identical"] is True
    ledger.advance(ledger_dir, "C10", {"smoke": "PASS", "write_set_ok": True})
    ledger.advance(ledger_dir, "C11", {"account_key_match": True, "mirror_passes": 1,
                                       "reconciliation_required": 0, "scheduler_front": "ENABLED"})
    reference = custody / "reference.json"
    assert pg_fingerprint.main(["snapshot", "--out", str(reference)]) == 0
    ref_sha = json.loads(reference.read_text())["fingerprint_sha256"]
    ledger.advance(ledger_dir, "C12", {"reference_fingerprint_sha256": ref_sha, "opened_at": "2026-11-01T09:00:00Z"})

    # A non-operator business write (a request hour count changed) is detected and recorded.
    with rs.application(database_url=target_url) as target:
        target.conn.execute("UPDATE requisicoes SET horas_solicitadas = horas_solicitadas + 1 WHERE id = 1")
        target.conn.commit()
    now = custody / "now.json"
    assert pg_fingerprint.main(["snapshot", "--out", str(now)]) == 0
    delta = pg_fingerprint.compare(json.loads(reference.read_text()), json.loads(now.read_text()))
    assert delta["identical"] is False and delta["changed_tables"] == ["REQUISICOES"]
    assert delta["detail"]["REQUISICOES"]["changed_columns"] == ["horas_solicitadas"]
    now_sha = json.loads(now.read_text())["fingerprint_sha256"]
    assert now_sha != ref_sha
    # A rollback from C12 with the changed fingerprint is refused: the write is the point of no return.
    with pytest.raises(ledger.Refused) as caught:
        ledger.rollback(ledger_dir, "CHANGED_MY_MIND", current_fingerprint=now_sha)
    assert caught.value.code == "FINGERPRINT_CHANGED"
    ledger.advance(ledger_dir, "C13", {"write_class": "REQUISICOES", "detected_at": "2026-11-01T10:30:00Z",
                                       "current_fingerprint_sha256": now_sha, "adjudicated_by_operator": True})
    with pytest.raises(ledger.Refused) as caught:
        ledger.rollback(ledger_dir, "TOO_LATE")
    assert caught.value.code == "PONR_RECORDED"
    ledger.advance(ledger_dir, "C14", {"window_days": 30, "second_generation_restore": "OK",
                                       "unresolved_reconciliation": 0, "object_set_verified": True})

    # ---- leak audit: the sentinel is in document bytes only, never in any record -------------
    for artifact in (ledger_dir / ledger.LEDGER_FILE, reference, now, *sets.glob("*.manifest.json"),
                     object_dir / "MANIFEST.json"):
        assert SENTINEL.encode() not in Path(artifact).read_bytes(), artifact.name
    assert ledger.status(ledger_dir)["state"] == "C14"


# ---- fault injection (the same live parts, broken on purpose) ---------------------------------


@pytest.fixture
def fault_bucket():
    bucket = rs.RunBucket(rs.load_dev_env())
    bucket.create()
    try:
        yield bucket
    finally:
        bucket.purge_and_delete()


def _frozen_copy(tmp_path, name, *, v15=False):
    """A production-shaped source and a byte copy of it (the frozen/prepared pair of C3-C4)."""
    source = rs.build_source(tmp_path / name, SENTINEL)
    if v15:
        from tests.prod1_v16_support import revert_prod1_v16_to_v15

        conn = sqlite3.connect(source.database)
        conn.execute("PRAGMA foreign_keys=ON")
        revert_prod1_v16_to_v15(conn)
        conn.close()
    prepared = tmp_path / f"{name}-prepared.db"
    shutil.copyfile(source.database, prepared)
    return source, prepared


def test_a_v15_workstation_copy_is_upgraded_offline_and_the_frozen_source_never_changes(tmp_path):
    """C4's upgrade: the same migration entry point the application runs at start, on the COPY only."""
    from app.prod1_schema import validate_prod1_schema

    source, prepared = _frozen_copy(tmp_path, "ws15", v15=True)
    frozen_before = rs.sha256_file(source.database)
    check = sqlite3.connect(prepared)
    assert check.execute("PRAGMA user_version").fetchone()[0] == 15
    rows_before = {t: check.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                   for t in ("usuarios", "requisicoes", "requisicao_arquivos", "admin_arquivos")}
    check.close()
    script = (
        "import sqlite3, sys; from app.db_maintenance import apply_schema_migrations as migrate;"
        "c = sqlite3.connect(sys.argv[1]); c.row_factory = sqlite3.Row; c.execute('PRAGMA foreign_keys=ON');"
        "print(migrate(c)['schema_version']); c.commit()"
    )
    env = {k: v for k, v in os.environ.items() if k in ("SYSTEMROOT", "PATH", "TEMP", "TMP", "USERPROFILE")}
    done = subprocess.run([sys.executable, "-c", script, str(prepared)], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 0 and done.stdout.strip() == "16", done.stderr[-300:]
    upgraded = sqlite3.connect(prepared)
    upgraded.row_factory = sqlite3.Row
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == 16
    validate_prod1_schema(upgraded)
    assert {t: upgraded.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in rows_before} == rows_before
    upgraded.close()
    assert rs.sha256_file(source.database) == frozen_before  # the frozen source is only ever copied


def _converge(conn, source, bucket, *, apply=True):
    from app.storage import drive_mirror, legacy_convergence

    return legacy_convergence.converge(
        conn, apply=apply, limit=100, tables=legacy_convergence.TABLES,
        store=bucket.store if apply else None, bucket=bucket.name if apply else None,
        drive=drive_mirror.active_drive(conn), roots=source.roots,
    )


def test_a_killed_converge_resumes_and_a_foreign_object_at_a_key_is_never_overwritten(tmp_path, fault_bucket):
    from app.storage import legacy_convergence, storage_audit

    source, prepared = _frozen_copy(tmp_path, "kill")

    class _Killed(BaseException):
        pass

    with rs.application(database=prepared, store=fault_bucket.store, drive=source.drive,
                        documentos=source.documentos, uploads=source.uploads) as prep:
        real_link = legacy_convergence._link
        seen = []

        def die_on_the_third_row(conn, candidate, **kwargs):
            seen.append(candidate.row_id)
            if len(seen) == 3:
                raise _Killed()
            return real_link(conn, candidate, **kwargs)

        legacy_convergence._link = die_on_the_third_row
        try:
            with pytest.raises(_Killed):
                _converge(prep.conn, source, fault_bucket)
        finally:
            legacy_convergence._link = real_link
        prep.conn.rollback()
        # Bytes were put in the real bucket for a row that never got its link.
        assert len(fault_bucket.store.list_objects(fault_bucket.name, "", max_objects=100)) >= 3
        resumed = _converge(prep.conn, source, fault_bucket)
        prep.conn.commit()
        assert resumed.clean and resumed.adopted_targets >= 1
        census = storage_audit.census(prep.conn)
        assert _unconverged(census, include_eligible=True) == [
            {"class": "REQUISICAO_ARQUIVOS_GOOGLE_TRASHED", "count": 1}]
        cross = storage_audit.cross_check(prep.conn, store=fault_bucket.store, deep=True, listing=True,
                                          buckets=(fault_bucket.name,))
        assert cross["verdict"]["references_consistent"] and cross["verdict"]["storage_consistent"] is True


def test_different_bytes_already_at_a_key_make_the_row_a_conflict_the_ledger_will_not_accept(tmp_path, fault_bucket):
    from app.storage import storage_audit
    from tools import cutover_ledger as ledger

    source, prepared = _frozen_copy(tmp_path, "conflict")
    with rs.application(database=prepared, store=fault_bucket.store, drive=source.drive,
                        documentos=source.documentos, uploads=source.uploads) as prep:
        row = prep.conn.execute(
            "SELECT id FROM admin_arquivos WHERE COALESCE(provider, 'local_legacy') = 'local_legacy' "
            "ORDER BY id LIMIT 1").fetchone()
        key = f"legacy/arquivos/{int(row[0])}"
        foreign = b"%PDF-1.4 foreign bytes that are not the legacy source"
        fault_bucket.store.upload(fault_bucket.name, key, foreign, mime_type="application/pdf")
        report = _converge(prep.conn, source, fault_bucket)
        prep.conn.commit()
        assert not report.clean and report.as_dict()["totals"].get("TARGET_CONFLICT") == 1
        assert fault_bucket.store.read(fault_bucket.name, key, max_bytes=1024) == foreign  # never overwritten
        census = storage_audit.census(prep.conn)
    unconverged = _unconverged(census, include_eligible=True)
    accepted = [{"class": "REQUISICAO_ARQUIVOS_GOOGLE_TRASHED", "count": 1}]
    assert unconverged != accepted, unconverged  # the conflict row is an extra unconverged row
    # The ledger accepts only the classes the user accepted at C4; an extra unconverged row is refused.
    ledger_dir = tmp_path / "ledger"
    ledger.init(ledger_dir)
    for index, gate in enumerate(GATES_BEFORE_OPEN):
        ledger.grant(ledger_dir, gate, f"rehearsal-{index}")
    head = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    h = lambda ch: ch * 64  # noqa: E731
    ledger.advance(ledger_dir, "C0", {"commit": head, "runbook_sha256": h("a"), "rehearsal_index_sha256": h("b"),
                                      "review_verdict": "PASS"})
    ledger.advance(ledger_dir, "C1", {"pg_major": 17, "schema_current": True, "rows": 0, "objects": 0,
                                      "data_api_toggle_off": True, "data_api_probe": "NOT_SERVED",
                                      "api_exposure_clean": True, "capacity_ok": True})
    ledger.advance(ledger_dir, "C2", {"database_bytes": 1, "document_bytes": 1, "census": {"ROWS": 1}})
    ledger.advance(ledger_dir, "C3", {"source_size": 1, "source_sha256": h("c"), "wal_bytes": 0})
    ledger.advance(ledger_dir, "C4", {"source_sha256": h("c"), "prepared_sha256": h("d"), "integrity_ok": True,
                                      "fk_violations": 0, "schema_version": 16, "accepted_exceptions": accepted,
                                      "accepted_by_user": True})
    with pytest.raises(ledger.Refused) as caught:
        ledger.advance(ledger_dir, "C5", {"prepared_sha256": h("d"), "converged_rows": 1,
                                          "unconverged": unconverged, "legacy_bytes_touched": 0})
    assert caught.value.code == "UNCONVERGED_ROWS_NOT_ACCEPTED"


def test_a_corrupted_backup_is_refused_by_verify_and_by_restore_and_nothing_is_written(
        tmp_path, registry, monkeypatch):
    from tools import pg_backup

    name, url = registry.create(template=registry.template)
    scratch_name, scratch_url = registry.create()
    try:
        monkeypatch.setenv(pg_backup.SOURCE_URL_ENV, url)
        sets = tmp_path / "layer2"
        sets.mkdir()
        pg_backup.backup(str(sets), "fault-drill")
        manifest = next(sets.glob("*.manifest.json"))
        pg_backup.verify_artifact(str(manifest))  # control: the intact set verifies
        dump = next(sets.glob("*.dump"))
        data = bytearray(dump.read_bytes())
        data[len(data) // 2] ^= 0xFF
        dump.write_bytes(bytes(data))
        with pytest.raises(pg_backup.Refused) as caught:
            pg_backup.verify_artifact(str(manifest))
        assert caught.value.code == "ARTIFACT_SHA_MISMATCH"
        with pytest.raises(pg_backup.Refused):
            pg_backup.restore(str(manifest), target_url=scratch_url)
        # The scratch target is still empty: a refused restore wrote nothing.
        conn = pg_backup.connect(scratch_url)
        try:
            tables = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'").fetchone()[0]
        finally:
            conn.close()
        assert tables == 0
    finally:
        registry.drop(scratch_name)
        registry.drop(name)
