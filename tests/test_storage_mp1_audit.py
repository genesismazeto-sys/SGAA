# coding: utf-8
"""MP-1 slice 2: value-free census and convergence cross-check (SQLite lane).

Contract (``docs/specs/MP-1-storage-convergence.md`` §3, D11, I5): the census
counts every custody class with the ONE eligibility rule convergence uses;
the cross-check classifies every seeded discrepancy -- database references,
canonical objects (``deep``: bytes), bucket listing, Drive mirrors -- prints
counts and fixed codes only, and its ``reference_digest`` pins the reference
set.  ``requeue_missing_mirrors`` is the mirror recovery.
"""

from __future__ import annotations

import io
import json

import pytest

from app.db import write_transaction
from app.storage import drive_mirror
from app.storage import mirror_outbox as outbox
from app.storage import storage_audit as audit
from app.storage import upload_intents as intents
from app.storage.cli import EXIT_NOT_CONVERGED, EXIT_NOT_RUNNABLE, EXIT_OK, EXIT_RUNTIME_FAILURE, main as cli_main
from app.storage.contracts import StorageTransientError
from app.storage.object_store import ListedObject
from tests.canonical_store_fake import InMemoryObjectStore
from tests.storage_mp1_support import (
    ACCOUNT_KEY,
    ADMIN_ID,
    BUCKET,
    OTHER_ACCOUNT_KEY,
    T0,
    insert_object,
    object_state,
    seed_canonical_arquivo,
    seed_canonical_request_document,
    sha256,
    sqlite_storage_env,
)
from tests.storage_s3a_support import PDF, PNG

REQ_KEY = "comprovantes/2026/10/" + "1" * 32
ARQ_KEY = "arquivos/2026/10/" + "2" * 32


@pytest.fixture
def env(tmp_path, monkeypatch):
    with sqlite_storage_env(tmp_path, monkeypatch) as context:
        yield context


def _legacy_request(conn, *, provider, status, filename="documentos/aluno-1/prova.pdf", **extra):
    row = dict(requisicao_id=1, filename=filename, provider=provider, storage_status=status, **extra)
    names = ",".join(row)
    marks = ",".join("?" for _ in row)
    return int(conn.execute(f"INSERT INTO requisicao_arquivos({names}) VALUES({marks}) RETURNING id",
                            tuple(row.values())).fetchone()[0])


def _google_request(conn, content=PDF, *, status="active", file_id="drvreq1", **extra):
    return _legacy_request(
        conn, provider="google", status=status, filename="REQ-000001__Conceito__v1.pdf",
        remote_file_id=file_id, remote_parent_id="drvparent1", original_filename="prova.pdf",
        mime_type="application/pdf", size_bytes=len(content), sha256=sha256(content),
        uploaded_at="2026-09-01T10:00:00Z", uploader_user_id=ADMIN_ID, operation_key=f"legacy-{file_id}", **extra)


def _seed_mixed(env):
    conn = env.conn
    seed_canonical_request_document(conn, env.store, key=REQ_KEY, content=PDF)
    seed_canonical_arquivo(conn, env.store, key=ARQ_KEY, content=PNG, mime="image/png")
    _google_request(conn)
    _legacy_request(conn, provider="local_legacy", status="legacy_active")
    _google_request(conn, status="pending", file_id=None)
    conn.execute("INSERT INTO admin_arquivos(titulo,filename) VALUES('Antigo','arquivos/antigo.pdf')")
    conn.execute(
        "INSERT INTO admin_arquivos(titulo,filename,operation_key,failure_code,replacement_mime_type,"
        "replacement_size_bytes,replacement_sha256) VALUES('Reservado','arquivos/reservado.pdf','op-r',"
        "'REPLACEMENT_UPLOAD_PENDING','application/pdf',10,?)", ("e" * 64,))
    converged = insert_object(conn, key="legacy/comprovantes/90", content=b"%PDF-converged",
                              origin="migrated_local_legacy", uploader=None)
    env.store.objects[(BUCKET, "legacy/comprovantes/90")] = (b"%PDF-converged", "application/pdf")
    _legacy_request(conn, provider="local_legacy", status="legacy_active", filename="documentos/x.pdf",
                    storage_object_id=converged)
    conn.commit()


# ---------------------------------------------------------------------------
# census
# ---------------------------------------------------------------------------


def test_census_counts_every_custody_class(env):
    _seed_mixed(env)

    report = audit.census(env.conn)

    assert report["documents"]["requisicao_arquivos"] == {
        "canonical": 1, "converged": {"local_legacy": 1}, "eligible": {"google": 1, "local_legacy": 1},
        "blocked": {"google:pending": 1}, "unconverged": 3,
    }
    assert report["documents"]["admin_arquivos"] == {
        "canonical": 1, "converged": {}, "eligible": {"google": 0, "local_legacy": 1},
        "blocked": {"local_legacy:legacy_active": 1}, "unconverged": 2,
    }
    assert report["objects"]["lifecycle"] == {"active": 3, "retired": 0}
    assert report["objects"]["origin"] == {"direct_upload": 2, "migrated_google": 0, "migrated_local_legacy": 1}
    assert report["objects"]["mirror"]["pending"] == 3 and report["objects"]["mirror_complete"] is False
    assert report["worker"] is None


def test_census_and_cross_check_are_value_free(env):
    _seed_mixed(env)
    text = json.dumps([audit.census(env.conn), audit.cross_check(env.conn, store=env.store, deep=True,
                                                                  show_ids=True)])
    for forbidden in (REQ_KEY, ARQ_KEY, "legacy/comprovantes", "REQ-000001", "prova.pdf", "documentos/",
                      "drvreq1", "drvparent1", "Aluno", "Antigo", "sub:slot", ACCOUNT_KEY, BUCKET):
        assert forbidden not in text, forbidden


# ---------------------------------------------------------------------------
# cross-check: references
# ---------------------------------------------------------------------------


def _clean(env):
    seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    seed_canonical_arquivo(env.conn, env.store, key=ARQ_KEY, content=PNG, mime="image/png")
    env.conn.commit()


def test_clean_canonical_state_is_converged(env):
    _clean(env)

    report = audit.cross_check(env.conn, store=env.store, deep=True)

    assert set(report["references"].values()) == {0}
    assert report["storage"] == {"OBJECT_MISSING": 0, "OBJECT_SIZE_MISMATCH": 0, "OBJECT_CONTENT_MISMATCH": 0,
                                 "STORAGE_CHECK_FAILED": 0, "checked": 2, "deep": True}
    assert report["bucket"] == {"UNREFERENCED_INTENT_OBJECT": 0, "UNREFERENCED_OBJECT": 0, "listed": 2}
    assert report["verdict"] == {"references_consistent": True, "storage_consistent": True, "bucket_clean": True,
                                 "mirrors_verified": None, "legacy_converged": True, "mirror_complete": False,
                                 "converged": True}
    assert report["legacy_remaining"] == 0
    assert "ids" not in report


def test_unconverged_legacy_or_unchecked_storage_is_never_converged(env):
    _clean(env)
    assert audit.cross_check(env.conn)["verdict"]["converged"] is False  # storage not checked
    _google_request(env.conn)
    env.conn.commit()
    report = audit.cross_check(env.conn, store=env.store)
    assert (report["legacy_remaining"], report["verdict"]["converged"]) == (1, False)


def _retired_live_row(env):
    object_id = env.conn.execute("SELECT storage_object_id FROM admin_arquivos").fetchone()[0]
    env.conn.execute("UPDATE storage_objects SET lifecycle_state='retired',retired_at=? WHERE id=?", (T0, object_id))
    return "LIVE_ROW_OBJECT_RETIRED", "admin_arquivos"


def _trashed_row_active_object(env):
    env.conn.execute("UPDATE requisicao_arquivos SET storage_status='trashed'")
    return "TRASHED_ROW_OBJECT_ACTIVE", "requisicao_arquivos"


def _unowned_active_object(env):
    insert_object(env.conn, key="comprovantes/2026/10/" + "9" * 32, content=b"%PDF-orphan")
    env.store.objects[(BUCKET, "comprovantes/2026/10/" + "9" * 32)] = (b"%PDF-orphan", "application/pdf")
    return "ACTIVE_OBJECT_UNOWNED", "storage_objects"


def _origin_mismatch(env):
    env.conn.execute("UPDATE storage_objects SET origin='migrated_google' WHERE storage_key=?", (ARQ_KEY,))
    return "ORIGIN_MISMATCH", "admin_arquivos"


def _metadata_mismatch(env):
    env.conn.execute("UPDATE requisicao_arquivos SET size_bytes=size_bytes+1")
    return "METADATA_MISMATCH", "requisicao_arquivos"


def _metadata_sha_mismatch(env):
    env.conn.execute("UPDATE admin_arquivos SET sha256=?", ("c" * 64,))
    return "METADATA_MISMATCH", "admin_arquivos"


def _metadata_mime_mismatch(env):
    env.conn.execute("UPDATE admin_arquivos SET mime_type='application/pdf'")
    return "METADATA_MISMATCH", "admin_arquivos"


def _converged(env, provider, origin):
    key = f"legacy/comprovantes/{provider}"
    object_id = insert_object(env.conn, key=key, content=b"%PDF-c", origin=origin, uploader=None)
    env.store.objects[(BUCKET, key)] = (b"%PDF-c", "application/pdf")
    if provider == "google":
        _google_request(env.conn, b"%PDF-c", file_id="drvconv", storage_object_id=object_id)
    else:
        _legacy_request(env.conn, provider="local_legacy", status="legacy_active", storage_object_id=object_id)


def _google_origin_mismatch(env):
    _converged(env, "google", "migrated_local_legacy")
    return "ORIGIN_MISMATCH", "requisicao_arquivos"


def _local_origin_mismatch(env):
    _converged(env, "local_legacy", "migrated_google")
    return "ORIGIN_MISMATCH", "requisicao_arquivos"


@pytest.mark.parametrize("arrange", [_retired_live_row, _trashed_row_active_object, _unowned_active_object,
                                     _origin_mismatch, _metadata_mismatch, _metadata_sha_mismatch,
                                     _metadata_mime_mismatch, _google_origin_mismatch, _local_origin_mismatch])
def test_each_reference_discrepancy_is_classified(env, arrange):
    _clean(env)
    name, table = arrange(env)
    env.conn.commit()

    report = audit.cross_check(env.conn, store=env.store, show_ids=True)

    assert {key: value for key, value in report["references"].items() if value} == {name: 1}
    assert report["ids"][name][0].startswith(f"{table}:")
    assert report["verdict"]["references_consistent"] is False and report["verdict"]["converged"] is False


@pytest.mark.parametrize("provider, origin", [("google", "migrated_google"),
                                              ("local_legacy", "migrated_local_legacy")])
def test_converged_rows_with_their_own_origin_are_consistent(env, provider, origin):
    _clean(env)
    _converged(env, provider, origin)
    env.conn.commit()
    assert set(audit.cross_check(env.conn, store=env.store)["references"].values()) == {0}


def test_a_normally_removed_comprovante_is_consistent(env):
    """Trashed row + retired object is the canonical removal, not a discrepancy."""
    _clean(env)
    env.conn.execute("UPDATE requisicao_arquivos SET storage_status='trashed'")
    env.conn.execute("UPDATE storage_objects SET lifecycle_state='retired',retired_at=? WHERE storage_key=?",
                     (T0, REQ_KEY))
    env.conn.commit()
    report = audit.cross_check(env.conn, store=env.store, deep=True)
    assert set(report["references"].values()) == {0} and report["verdict"]["converged"] is True


def test_steady_state_eligibility_of_legacy_arquivos(env):
    """Google / local ARQUIVOS rows converge only from their steady state (no failure in flight)."""
    from tests.storage_s3b_support import seed_google_arquivo

    seed_google_arquivo(env.conn, uploader=ADMIN_ID, now=T0, remote_file_id="drvok1", operation_key="g-ok")
    seed_google_arquivo(env.conn, uploader=ADMIN_ID, now=T0, remote_file_id="drvbusy1", operation_key="g-busy",
                        failure_code="STORAGE_TRANSIENT")
    env.conn.execute("INSERT INTO admin_arquivos(titulo,filename) VALUES('Ok','arquivos/ok.pdf')")
    env.conn.execute("INSERT INTO admin_arquivos(titulo,filename,failure_code) VALUES('Falha','arquivos/f.pdf',"
                     "'CLEANUP_FAILED')")
    env.conn.commit()
    census = audit.census(env.conn)["documents"]["admin_arquivos"]
    assert census["eligible"] == {"google": 1, "local_legacy": 1}
    assert census["blocked"] == {"google:active": 1, "local_legacy:legacy_active": 1}


# ---------------------------------------------------------------------------
# cross-check: canonical storage and bucket
# ---------------------------------------------------------------------------


class _SizelessListingStore(InMemoryObjectStore):
    """A provider whose listing reports no sizes: sizes must then come from ``stat``."""

    def list_objects(self, bucket, prefix="", *, max_objects):
        return [ListedObject(item.key, None) for item in super().list_objects(bucket, prefix,
                                                                                max_objects=max_objects)]


def test_an_unlisted_size_is_checked_with_stat_not_assumed(tmp_path, monkeypatch):
    with sqlite_storage_env(tmp_path, monkeypatch, store=_SizelessListingStore()) as context:
        seed_canonical_arquivo(context.conn, context.store, key=ARQ_KEY, content=PNG, mime="image/png")
        context.conn.commit()
        assert audit.cross_check(context.conn, store=context.store)["verdict"]["storage_consistent"] is True
        context.store.objects[(BUCKET, ARQ_KEY)] = (PNG + b"longer", "image/png")
        report = audit.cross_check(context.conn, store=context.store)
        assert report["storage"]["OBJECT_SIZE_MISMATCH"] == 1
        assert "stat" in context.store.calls


def test_missing_object_is_found_by_listing_and_by_stat(env):
    _clean(env)
    env.store.objects.pop((BUCKET, REQ_KEY))
    for listing in (True, False):
        report = audit.cross_check(env.conn, store=env.store, listing=listing)
        assert report["storage"]["OBJECT_MISSING"] == 1
        assert report["verdict"]["storage_consistent"] is False


def test_size_and_content_divergence(env):
    _clean(env)
    env.store.objects[(BUCKET, ARQ_KEY)] = (PNG + b"x", "image/png")
    assert audit.cross_check(env.conn, store=env.store)["storage"]["OBJECT_SIZE_MISMATCH"] == 1
    tampered = bytes([PDF[0] ^ 1]) + PDF[1:]
    env.store.objects[(BUCKET, ARQ_KEY)] = (PNG, "image/png")
    env.store.objects[(BUCKET, REQ_KEY)] = (tampered, "application/pdf")
    shallow = audit.cross_check(env.conn, store=env.store)
    deep = audit.cross_check(env.conn, store=env.store, deep=True)
    assert shallow["verdict"]["storage_consistent"] is True
    assert deep["storage"]["OBJECT_CONTENT_MISMATCH"] == 1 and deep["verdict"]["storage_consistent"] is False


def test_provider_failure_is_a_failed_check_not_a_pass(env):
    _clean(env)
    env.store.fail_next("STORAGE_PROVIDER_UNAVAILABLE")
    report = audit.cross_check(env.conn, store=env.store, listing=False)
    assert report["storage"]["STORAGE_CHECK_FAILED"] == 1
    assert report["verdict"]["storage_consistent"] is False


def test_unreferenced_bucket_objects_are_classified(env):
    _clean(env)
    env.store.objects[(BUCKET, "comprovantes/2026/10/" + "7" * 32)] = (b"%PDF-stray", "application/pdf")
    with write_transaction(env.conn):
        intent = intents.issue_intent(
            env.conn, actor_user_id=ADMIN_ID, purpose="comprovante", operation_id="s:1", bucket=BUCKET,
            declared_mime_type="application/pdf", declared_size_bytes=5, declared_sha256="d" * 64, now=T0,
        )
    env.store.objects[(BUCKET, intent.storage_key)] = (b"%PDF-", "application/pdf")

    report = audit.cross_check(env.conn, store=env.store)

    assert report["bucket"] == {"UNREFERENCED_INTENT_OBJECT": 1, "UNREFERENCED_OBJECT": 1, "listed": 4}
    assert report["verdict"]["bucket_clean"] is False
    assert report["verdict"]["converged"] is True  # garbage in the bucket is not a reference failure


def test_configured_bucket_is_listed_even_when_the_database_names_none(env):
    env.store.objects[("other-bucket", "stray/object")] = (b"x", "application/pdf")
    report = audit.cross_check(env.conn, store=env.store, buckets=("other-bucket",))
    assert report["bucket"]["UNREFERENCED_OBJECT"] == 1


# ---------------------------------------------------------------------------
# cross-check: Drive mirrors and recovery
# ---------------------------------------------------------------------------


def _synced(env):
    _clean(env)
    assert drive_mirror.run_mirror_pass(env.conn).synced == 2
    return drive_mirror.active_drive(env.conn)


def test_synced_mirrors_verify_clean(env):
    drive = _synced(env)
    report = audit.cross_check(env.conn, store=env.store, drive=drive)
    assert report["mirror"] == {"MIRROR_VERIFIED": 2, "MIRROR_MISSING": 0, "MIRROR_DIVERGENT": 0,
                                "MIRROR_CHECK_FAILED": 0, "MIRROR_ACCOUNT_INACTIVE": 0, "requeued": 0}
    assert report["verdict"]["mirrors_verified"] is True and report["verdict"]["mirror_complete"] is True


def test_missing_and_divergent_mirrors_are_found_and_recovered(env):
    drive = _synced(env)
    request_file = next(f for f in env.drive.files.values() if f["properties"]["sgaaKind"] == "comprovante")
    arquivo_file = next(f for f in env.drive.files.values() if f["properties"]["sgaaKind"] == "arquivo")
    request_file["trashed"] = True
    arquivo_file["sha256"] = "0" * 64

    observed = audit.cross_check(env.conn, store=env.store, drive=drive)
    assert (observed["mirror"]["MIRROR_MISSING"], observed["mirror"]["MIRROR_DIVERGENT"]) == (1, 1)
    assert observed["verdict"]["mirrors_verified"] is False
    assert observed["mirror"]["requeued"] == 0

    recovered = audit.cross_check(env.conn, store=env.store, drive=drive, requeue_missing_mirrors=True)
    assert recovered["mirror"]["requeued"] == 2
    states = [object_state(env.conn, row[0]) for row in env.conn.execute("SELECT id FROM storage_objects")]
    assert {(state["state"], state["file_id"], state["account_key"], state["attempts"]) for state in states} == {
        ("pending", None, ACCOUNT_KEY, 0)}
    assert {state["error"] for state in states} == {"MIRROR_MISSING", "MIRROR_DIVERGENT"}

    # The trashed copy is recreated; the divergent copy still claims its
    # operation, so the next pass refuses it (fail closed) for the operator.
    result = drive_mirror.run_mirror_pass(env.conn)
    assert (result.synced, result.reconciliation) == (1, 1)
    arquivo_state = object_state(env.conn, env.conn.execute(
        "SELECT storage_object_id FROM admin_arquivos").fetchone()[0])
    assert (arquivo_state["state"], arquivo_state["error"]) == ("reconciliation_required", "MIRROR_INTEGRITY_MISMATCH")
    assert len(env.drive.files) == 3 and request_file["trashed"]  # a new copy; the trashed one stays trashed


def test_mirror_bound_elsewhere_or_unreadable_is_not_verified(env):
    drive = _synced(env)
    env.conn.execute("UPDATE cloud_accounts SET provider_account_key=?", (OTHER_ACCOUNT_KEY,))
    env.conn.commit()
    other = drive_mirror.active_drive(env.conn)
    report = audit.cross_check(env.conn, store=env.store, drive=other)
    assert report["mirror"]["MIRROR_ACCOUNT_INACTIVE"] == 2
    assert report["verdict"]["mirrors_verified"] is None  # nothing failed, nothing verified

    env.drive.fail_next("describe_file", StorageTransientError("busy"))
    failed = audit.cross_check(env.conn, store=env.store, drive=drive)
    assert failed["mirror"]["MIRROR_CHECK_FAILED"] == 1 and failed["verdict"]["mirrors_verified"] is False


def test_recovery_never_touches_a_changed_mirror(env):
    _synced(env)
    row = env.conn.execute("SELECT id, drive_file_id FROM storage_objects ORDER BY id").fetchone()
    with write_transaction(env.conn):
        assert outbox.reset_missing_mirror(env.conn, object_id=row[0], drive_file_id="someotherfile",
                                           error_code="MIRROR_MISSING", now=T0) == 0
    assert object_state(env.conn, row[0])["state"] == "synced"


def test_recovery_only_resets_synced_active_objects(env):
    """Each condition alone: a non-synced or a retired object is never reset."""
    _synced(env)
    first, second = env.conn.execute("SELECT id, drive_file_id FROM storage_objects ORDER BY id").fetchall()
    env.conn.execute("UPDATE storage_objects SET drive_sync_state='reconciliation_required',"
                     "drive_last_error_code='X',drive_synced_at=drive_synced_at WHERE id=?", (first[0],))
    env.conn.execute("UPDATE storage_objects SET lifecycle_state='retired',retired_at=? WHERE id=?", (T0, second[0]))
    env.conn.commit()
    with write_transaction(env.conn):
        for object_id, file_id in (first, second):
            assert outbox.reset_missing_mirror(env.conn, object_id=object_id, drive_file_id=file_id,
                                               error_code="MIRROR_MISSING", now=T0) == 0
    assert object_state(env.conn, first[0])["file_id"] == first[1]
    assert object_state(env.conn, second[0])["state"] == "synced"


def test_a_lookup_in_a_switched_account_is_a_failed_check_not_a_reset(env, monkeypatch):
    drive = _synced(env)
    next(iter(env.drive.files.values()))["trashed"] = True
    monkeypatch.setattr(drive_mirror, "still_active", lambda _conn, _drive: False)
    report = audit.cross_check(env.conn, store=env.store, drive=drive, requeue_missing_mirrors=True)
    assert (report["mirror"]["MIRROR_MISSING"], report["mirror"]["MIRROR_CHECK_FAILED"]) == (0, 1)
    assert report["mirror"]["requeued"] == 0


# ---------------------------------------------------------------------------
# reference digest
# ---------------------------------------------------------------------------


class _ReversedRows:
    """A connection whose engine returns every result set in the opposite order."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        rows = list(reversed(self._conn.execute(sql, params).fetchall()))
        return type("Cursor", (), {"fetchall": lambda _self: rows})()


def test_reference_digest_pins_the_reference_set(env):
    _clean(env)
    seed_canonical_request_document(env.conn, env.store, key="comprovantes/2026/10/" + "4" * 32, content=PNG,
                                    mime="image/png", operation_key="sub:slot2")
    env.conn.commit()
    first = audit.reference_digest(env.conn)
    assert first == audit.reference_digest(env.conn)
    assert audit.reference_digest(_ReversedRows(env.conn)) == first  # independent of engine row order
    env.conn.execute("UPDATE storage_objects SET lifecycle_state='retired',retired_at=? WHERE storage_key=?",
                     (T0, ARQ_KEY))
    env.conn.commit()
    assert audit.reference_digest(env.conn) != first


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(env, *argv):
    out = io.StringIO()
    env.conn.commit()
    code = cli_main(list(argv), app=env.app, out=out)
    return code, (json.loads(out.getvalue()) if out.getvalue() else None)


def test_cli_census_and_verify(env, monkeypatch):
    _seed_mixed(env)
    monkeypatch.setenv("SGAA_STORAGE_BUCKET", BUCKET)

    code, census = _cli(env, "census")
    assert code == EXIT_OK and census["documents"]["requisicao_arquivos"]["unconverged"] == 3

    code, verify = _cli(env, "verify", "--deep")
    assert code == EXIT_NOT_CONVERGED and verify["verdict"]["converged"] is False  # legacy remains
    assert "ids" not in verify and "mirror" not in verify

    code, verify = _cli(env, "verify", "--drive", "--show-ids", "--no-listing")
    assert code == EXIT_NOT_CONVERGED and verify["mirror"]["MIRROR_MISSING"] == 0 and "bucket" not in verify
    assert verify["ids"] == {}


def test_cli_verify_exit_codes(env, monkeypatch):
    _clean(env)
    assert _cli(env, "verify", "--deep")[0] == EXIT_OK
    assert _cli(env, "verify", "--drive")[0] == EXIT_NOT_CONVERGED  # converged, but the mirror backlog remains
    assert drive_mirror.run_mirror_pass(env.conn).synced == 2
    assert _cli(env, "verify", "--drive")[0] == EXIT_OK
    next(iter(env.drive.files.values()))["trashed"] = True
    assert _cli(env, "verify", "--drive")[0] == EXIT_NOT_CONVERGED  # converged, but a mirror is missing
    env.store.objects[(BUCKET, "comprovantes/2026/10/" + "8" * 32)] = (b"%PDF-stray", "application/pdf")
    code, report = _cli(env, "verify")
    assert code == EXIT_NOT_CONVERGED and report["verdict"]["converged"] is True  # converged, dirty bucket
    env.conn.execute("UPDATE cloud_accounts SET active=0")
    assert _cli(env, "verify", "--drive")[0] == EXIT_NOT_RUNNABLE
    env.app.extensions.pop("canonical_object_store")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert _cli(env, "verify")[0] == EXIT_NOT_RUNNABLE


def test_cli_verify_reports_runtime_failure_without_detail(env, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("provider said: secret-locator")

    monkeypatch.setattr(audit, "cross_check", broken)
    assert _cli(env, "verify") == (EXIT_RUNTIME_FAILURE, None)
