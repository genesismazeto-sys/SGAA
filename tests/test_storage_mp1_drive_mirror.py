# coding: utf-8
"""MP-1 slice 1: the Drive mirror worker (SQLite lane, deterministic fakes).

Contract (``docs/specs/MP-1-storage-convergence.md`` §3, D2-D5): one bounded
pass places every due ACTIVE canonical object on the EXISTING managed Drive
conventions, copies the verified canonical bytes idempotently (find by
``sgaaOperation`` first), verifies the Drive result and completes under the
lease fence; retries back off and exhaust into ``reconciliation_required``;
unusable Drive defers without claiming; nothing canonical is ever deleted or
overwritten and nothing in Drive is ever trashed.
"""

from __future__ import annotations

import io
import json

import pytest

from app.db import write_transaction
from app.storage import custody_common
from app.storage import drive_mirror
from app.storage import mirror_outbox as outbox
from app.storage.cli import EXIT_NOT_RUNNABLE, EXIT_OK, EXIT_USAGE, main as cli_main
from app.storage.contracts import (
    StorageAuthorizationError,
    StorageConflictError,
    StorageTransientError,
)
from tests.storage_mp1_support import (
    ACCOUNT_KEY,
    BUCKET,
    OTHER_ACCOUNT_KEY,
    T0,
    GuardedStore,
    Tripwire,
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
EXTRA_KEY = "comprovantes/2026/10/" + "3" * 32


@pytest.fixture
def env(tmp_path, monkeypatch):
    # Every canonical write / delete and every Drive trash / delete is a
    # recording tripwire (I2): the mirror only reads canonical bytes.
    with sqlite_storage_env(tmp_path, monkeypatch, store=GuardedStore()) as context:
        yield context


def _commit(conn):
    conn.commit()


def _run(env, **kwargs):
    return drive_mirror.run_mirror_pass(env.conn, **kwargs)


def _worker(conn):
    return outbox.read_worker_status(conn)


# ---------------------------------------------------------------------------
# happy path, conventions, idempotency
# ---------------------------------------------------------------------------


def test_pass_mirrors_request_and_arquivo_on_the_existing_conventions(env):
    req_row, req_obj = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    arq_row, arq_obj = seed_canonical_arquivo(env.conn, env.store, key=ARQ_KEY, content=PNG, mime="image/png")
    _commit(env.conn)

    result = _run(env)

    assert (result.result_code, result.claimed, result.synced) == ("OK", 2, 2)
    files = {item["properties"]["sgaaKind"]: item for item in env.drive.files.values()}
    request_file, arquivo_file = files["comprovante"], files["arquivo"]
    assert request_file["content"] == PDF and arquivo_file["content"] == PNG
    assert request_file["properties"] == {
        "sgaaManaged": "true", "sgaaKind": "comprovante", "sgaaOperation": "sub:slot",
        "sgaaRequest": "1", "sgaaAttachment": str(req_row),
    }
    assert arquivo_file["properties"]["sgaaArquivo"] == str(arq_row)
    assert request_file["name"] == "REQ-000001__Conceito.pdf"
    chain = {key[1:]: folder for key, folder in env.drive.folders.items()}
    assert ("product_root", "sgaa") in chain and ("domain_root", "comprovantes") in chain
    assert ("turma", "1") in chain and ("request_axis", "AAC") in chain and ("student", "1") in chain
    assert ("domain_root", "arquivos") in chain
    assert request_file["parent_id"] == chain[("student", "1")]
    assert arquivo_file["parent_id"] == chain[("domain_root", "arquivos")]
    for object_id, item in ((req_obj, request_file), (arq_obj, arquivo_file)):
        state = object_state(env.conn, object_id)
        assert state["state"] == "synced" and state["file_id"] == item["id"]
        assert state["parent_id"] == item["parent_id"] and state["account_key"] == ACCOUNT_KEY
        assert state["lease"] is None and state["error"] is None and state["attempts"] == 1
    status = _worker(env.conn)
    assert status["last_result_code"] == "OK"
    assert (status["last_claimed_count"], status["last_synced_count"], status["last_retry_count"]) == (2, 2, 0)
    assert status["last_finished_at"] is not None


def test_rerun_claims_nothing_and_never_writes_drive_again(env):
    seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _commit(env.conn)
    _run(env)
    uploads = env.drive.calls.count("upload")

    again = _run(env)

    assert (again.claimed, again.synced) == (0, 0)
    assert env.drive.calls.count("upload") == uploads
    assert len(env.drive.files) == 1


def test_folders_are_looked_up_once_per_pass(env):
    for index in range(3):
        seed_canonical_request_document(
            env.conn, env.store, key=f"comprovantes/2026/10/{index:032d}", content=PDF + bytes([index]),
            operation_key=f"sub:slot{index}",
        )
    _commit(env.conn)

    assert _run(env).synced == 3
    assert env.drive.calls.count("ensure_folder") == 5


def test_legacy_drive_file_on_the_same_conventions_is_adopted_not_duplicated(env):
    row_id, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF,
                                                        operation_key="legacy-op-1")
    _commit(env.conn)
    folders = drive_mirror._FolderMemo(env.drive)
    from app.comprovante_hierarchy import ensure_request_hierarchy
    from app.comprovantes import _request_context

    request_row, payload, turma_id, turma_code = _request_context(env.conn, 1)
    env.conn.rollback()
    parent = ensure_request_hierarchy(folders, request_row=request_row, snapshot_payload=payload,
                                      turma_id=turma_id, turma_code=turma_code)
    planted = env.drive.add_file(parent_id=parent, name="legacy.pdf", content=PDF, operation_key="legacy-op-1",
                                 object_kind="comprovante")

    assert _run(env).synced == 1
    assert len(env.drive.files) == 1
    assert object_state(env.conn, object_id)["file_id"] == planted


def test_divergent_drive_file_is_refused_and_left_untouched(env):
    _row, object_id = seed_canonical_arquivo(env.conn, env.store, key=ARQ_KEY, content=PDF, operation_key="op-x")
    _commit(env.conn)
    root = env.drive.ensure_folder(parent_id="root", kind="product_root", semantic_id="sgaa", display_name="SGAA")
    parent = env.drive.ensure_folder(parent_id=root, kind="domain_root", semantic_id="arquivos", display_name="A")
    planted = env.drive.add_file(parent_id=parent, name="other.pdf", content=b"%PDF-other", operation_key="op-x",
                                 object_kind="arquivo")

    result = _run(env)

    assert (result.synced, result.reconciliation) == (0, 1)
    state = object_state(env.conn, object_id)
    assert (state["state"], state["error"], state["file_id"]) == (
        "reconciliation_required", "MIRROR_INTEGRITY_MISMATCH", None)
    assert env.drive.files[planted]["content"] == b"%PDF-other" and not env.drive.files[planted]["trashed"]


def test_legacy_row_without_operation_key_uses_a_derived_stable_key(env):
    object_id = insert_object(env.conn, key="legacy/arquivos/7", content=PDF, origin="migrated_local_legacy",
                              uploader=None)
    env.conn.execute(
        "INSERT INTO admin_arquivos(id,titulo,filename,original_filename,provider,storage_status,storage_object_id)"
        " VALUES(7,'Antigo','arquivos/pasta/antigo.pdf','antigo.pdf','local_legacy','legacy_active',?)",
        (object_id,),
    )
    env.store.objects[(BUCKET, "legacy/arquivos/7")] = (PDF, "application/pdf")
    _commit(env.conn)

    assert _run(env).synced == 1
    item = next(iter(env.drive.files.values()))
    expected = drive_mirror.mirror_operation_key(None, bucket=BUCKET, key="legacy/arquivos/7")
    assert item["properties"]["sgaaOperation"] == expected
    assert expected.startswith("sgaa-object-") and len(expected) == len("sgaa-object-") + 40
    assert item["name"] == "antigo.pdf"


def test_first_placement_freezes_a_missing_turma_snapshot_once(env):
    env.conn.execute("DELETE FROM requisicoes WHERE id=1")
    from tests.storage_mp1_support import request_snapshot

    env.conn.execute(
        "INSERT INTO requisicoes(id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,"
        "status,regra_snapshot_json) VALUES(1,1,1,'2026-09-05','2026-09-05',2,'Pendente',?)",
        (request_snapshot(),),
    )
    seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _commit(env.conn)

    assert _run(env).synced == 1
    frozen = env.conn.execute("SELECT turma_id_snapshot,turma_codigo_snapshot FROM requisicoes WHERE id=1").fetchone()
    assert tuple(frozen) == (1, "T-2026-1")


# ---------------------------------------------------------------------------
# crash / stale worker / lease safety
# ---------------------------------------------------------------------------


class _Death(BaseException):
    """Process death right after the Drive write (not an Exception: nothing catches it)."""


def test_death_after_drive_write_is_resumed_by_adoption_without_duplicate(env, monkeypatch):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _commit(env.conn)
    real_complete = outbox.complete_synced

    def die(*_args, **_kwargs):
        raise _Death()

    monkeypatch.setattr(outbox, "complete_synced", die)
    with pytest.raises(_Death):
        _run(env)
    env.conn.rollback()
    assert object_state(env.conn, object_id)["state"] == "syncing"
    assert _worker(env.conn)["last_finished_at"] is None  # durable trace of the interrupted pass

    monkeypatch.setattr(outbox, "complete_synced", real_complete)
    env.clock.advance(outbox.DEFAULT_LEASE_SECONDS + 1)
    result = _run(env)

    assert (result.released, result.synced) == (1, 1)
    assert len(env.drive.files) == 1
    assert object_state(env.conn, object_id)["state"] == "synced"


def test_stale_worker_loses_its_lease_and_the_new_owner_completes(env):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _commit(env.conn)
    original_upload = env.drive.upload
    rival = {}

    def slow_upload(**payload):
        remote = original_upload(**payload)
        # The lease expires while this worker is still busy; a rival reclaims it.
        env.clock.advance(outbox.DEFAULT_LEASE_SECONDS + 1)
        env.drive.upload = original_upload
        rival["result"] = drive_mirror.run_mirror_pass(env.conn)
        return remote

    env.drive.upload = slow_upload
    first = _run(env)

    assert first.lost == 1 and first.synced == 0
    assert rival["result"].synced == 1
    assert len(env.drive.files) == 1
    assert object_state(env.conn, object_id)["state"] == "synced"


def test_nearly_expired_lease_is_left_to_expire(env):
    seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF, operation_key="op-a")
    seed_canonical_request_document(env.conn, env.store, key=EXTRA_KEY, content=PDF + b"x", operation_key="op-b")
    _commit(env.conn)
    original_upload = env.drive.upload

    def slow_upload(**payload):
        env.clock.advance(outbox.DEFAULT_LEASE_SECONDS - drive_mirror.LEASE_SAFETY_SECONDS)
        return original_upload(**payload)

    env.drive.upload = slow_upload
    result = _run(env)

    assert (result.synced, result.skipped, result.deferred) == (1, 1, 0)
    assert env.drive.calls.count("upload") == 1
    skipped = env.conn.execute(
        "SELECT id FROM storage_objects WHERE drive_sync_state <> 'synced'").fetchone()[0]
    state = object_state(env.conn, skipped)
    # Handed back at once, its attempt returned -- not left leased until expiry.
    assert (state["state"], state["error"], state["attempts"], state["lease"]) == (
        "pending", "LEASE_SAFETY_MARGIN", 0, None)
    assert state["next_attempt"] == env.clock.now
    env.drive.upload = original_upload
    assert _run(env).synced == 1


# ---------------------------------------------------------------------------
# retry policy and unsafe outcomes
# ---------------------------------------------------------------------------


def test_backoff_doubles_from_one_minute_and_caps_at_six_hours():
    assert [drive_mirror.backoff_seconds(n) for n in (1, 2, 3, 4)] == [60, 120, 240, 480]
    assert drive_mirror.backoff_seconds(30) == 6 * 60 * 60


def test_transient_failures_back_off_and_exhaust_into_reconciliation(env):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _commit(env.conn)
    for attempt in range(1, drive_mirror.MAX_ATTEMPTS + 1):
        env.drive.fail_next("upload", StorageTransientError("drive busy"))
        result = _run(env)
        state = object_state(env.conn, object_id)
        assert state["attempts"] == attempt
        if attempt < drive_mirror.MAX_ATTEMPTS:
            assert (state["state"], state["error"]) == ("retry", "STORAGE_TRANSIENT")
            assert state["next_attempt"] == custody_common.add_seconds(
                env.clock.now, drive_mirror.backoff_seconds(attempt))
            assert _run(env).claimed == 0  # not due yet
            env.clock.advance(drive_mirror.backoff_seconds(attempt))
        else:
            assert result.reconciliation == 1
            assert (state["state"], state["error"]) == ("reconciliation_required", "MIRROR_RETRY_EXHAUSTED")
    env.clock.advance(drive_mirror.BACKOFF_CAP_SECONDS)
    assert _run(env).claimed == 0


def _unsafe_conflict(env, object_id):
    env.drive.fail_next("upload", StorageConflictError("two files"))


def _unsafe_canonical_missing(env, object_id):
    env.store.objects.pop((BUCKET, REQ_KEY))


def _unsafe_canonical_divergent(env, object_id):
    env.store.objects[(BUCKET, REQ_KEY)] = (PDF + b"tampered", "application/pdf")


def _unsafe_drive_corrupt(env, object_id):
    env.drive.corrupt_next_upload = True


def _unsafe_owner_missing(env, object_id):
    env.conn.execute("UPDATE requisicao_arquivos SET storage_object_id=NULL,provider='google',"
                     "remote_file_id='x1',remote_parent_id='p1' WHERE storage_object_id=?", (object_id,))
    env.conn.commit()


def _unsafe_invalid_snapshot(env, object_id):
    # The processing snapshot is immutable: a second request carries the bad one.
    env.conn.execute(
        "INSERT INTO requisicoes(id,aluno_id,atividade_versao_id,data_solicitacao,data_evento,horas_solicitadas,"
        "status,regra_snapshot_json,turma_id_snapshot,turma_codigo_snapshot)"
        " VALUES(2,1,1,'2026-09-05','2026-09-05',2,'Pendente','{}',1,'T-2026-1')")
    env.conn.execute("UPDATE requisicao_arquivos SET requisicao_id=2 WHERE storage_object_id=?", (object_id,))
    env.conn.commit()


@pytest.mark.parametrize("arrange, code", [
    (_unsafe_conflict, "REMOTE_SEMANTIC_CONFLICT"),
    (_unsafe_canonical_missing, "CANONICAL_OBJECT_MISSING"),
    (_unsafe_canonical_divergent, "CANONICAL_INTEGRITY_MISMATCH"),
    (_unsafe_drive_corrupt, "MIRROR_INTEGRITY_MISMATCH"),
    (_unsafe_owner_missing, "MIRROR_OWNER_MISSING"),
    (_unsafe_invalid_snapshot, "INVALID_REQUEST_SNAPSHOT"),
])
def test_unsafe_outcomes_go_straight_to_reconciliation(env, arrange, code):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _commit(env.conn)
    arrange(env, object_id)

    result = _run(env)

    state = object_state(env.conn, object_id)
    assert (state["state"], state["error"], state["attempts"]) == ("reconciliation_required", code, 1)
    assert result.reconciliation == 1 and result.synced == 0


def test_unexpected_item_error_is_isolated_and_retried(env):
    _bad_row, bad = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF,
                                                    operation_key="op-bad")
    _ok_row, good = seed_canonical_request_document(env.conn, env.store, key=EXTRA_KEY, content=PNG,
                                                    mime="image/png", operation_key="op-ok")
    _commit(env.conn)
    env.drive.fail_next("upload", ValueError("unexpected"))

    result = _run(env)

    assert (result.retried, result.synced) == (1, 1)
    assert object_state(env.conn, bad)["error"] == "MIRROR_UNEXPECTED_ERROR"
    assert object_state(env.conn, good)["state"] == "synced"


# ---------------------------------------------------------------------------
# Drive availability and account binding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("arrange, code", [
    ("UPDATE cloud_accounts SET active=0", "DRIVE_NOT_CONNECTED"),
    ("UPDATE cloud_accounts SET provider_account_key=NULL", "DRIVE_ACCOUNT_UNKNOWN"),
])
def test_unusable_drive_claims_nothing(env, arrange, code):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    env.conn.execute(arrange)
    _commit(env.conn)

    result = _run(env)

    assert (result.result_code, result.claimed) == (code, 0)
    state = object_state(env.conn, object_id)
    assert (state["state"], state["attempts"]) == ("pending", 0)
    assert env.drive.calls == []
    assert _worker(env.conn)["last_result_code"] == code


def test_unconfigured_canonical_store_claims_nothing(env):
    env.app.extensions.pop("canonical_object_store")
    seed_canonical_request_document(env.conn, None, key=REQ_KEY, content=PDF)
    _commit(env.conn)

    result = _run(env)

    assert (result.result_code, result.claimed) == ("STORAGE_CONFIG_MISSING", 0)


def test_account_replaced_during_resolution_claims_nothing(env, monkeypatch):
    seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _commit(env.conn)
    original = drive_mirror.resolve_google_managed_storage

    def swap_account(conn, **kwargs):
        conn.execute("UPDATE cloud_accounts SET active=0")
        conn.execute("INSERT INTO cloud_accounts(provider,token_json,active,provider_account_key)"
                     " VALUES('google','{}',1,?)", (OTHER_ACCOUNT_KEY,))
        conn.commit()
        return original(conn, **kwargs)

    monkeypatch.setattr(drive_mirror, "resolve_google_managed_storage", swap_account)

    assert _run(env).result_code == "DRIVE_ACCOUNT_CHANGED"


def test_canonical_authorization_failure_defers_the_pass(env):
    ids = [seed_canonical_request_document(env.conn, env.store, key=key, content=PDF + key.encode(),
                                           operation_key=f"op-{index}")[1]
           for index, key in enumerate((REQ_KEY, EXTRA_KEY))]
    _commit(env.conn)
    env.store.fail_next("STORAGE_AUTH_FAILURE")

    result = _run(env)

    assert (result.result_code, result.deferred, result.retried) == ("STORAGE_AUTH_FAILURE", 2, 0)
    assert {object_state(env.conn, object_id)["attempts"] for object_id in ids} == {0}
    assert "upload" not in env.drive.calls


def test_account_switched_during_the_upload_is_never_bound(env):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _later, later_id = seed_canonical_request_document(env.conn, env.store, key=EXTRA_KEY, content=PNG,
                                                       mime="image/png", operation_key="op-later")
    _commit(env.conn)
    original_upload = env.drive.upload

    def switch_then_upload(**payload):
        # A 401 refresh resolves whatever account is active NOW.
        env.conn.execute("UPDATE cloud_accounts SET active=0")
        env.conn.execute("INSERT INTO cloud_accounts(provider,token_json,active,provider_account_key)"
                         " VALUES('google','{}',1,?)", (OTHER_ACCOUNT_KEY,))
        env.conn.commit()
        env.drive.upload = original_upload
        return original_upload(**payload)

    env.drive.upload = switch_then_upload
    result = _run(env)

    assert (result.result_code, result.synced, result.deferred) == ("DRIVE_ACCOUNT_CHANGED", 0, 2)
    for oid in (object_id, later_id):
        state = object_state(env.conn, oid)
        assert (state["state"], state["account_key"], state["file_id"], state["attempts"]) == (
            "pending", None, None, 0)
    env.clock.advance(drive_mirror.UNAVAILABLE_DELAY_SECONDS)
    again = _run(env)  # the new account adopts the copy by its operation key
    assert again.synced == 2 and len(env.drive.files) == 2
    assert object_state(env.conn, object_id)["account_key"] == OTHER_ACCOUNT_KEY


def test_object_bound_elsewhere_while_copying_hands_its_lease_back(env):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _commit(env.conn)
    original_upload = env.drive.upload

    def bind_elsewhere(**payload):
        remote = original_upload(**payload)
        env.conn.execute("UPDATE storage_objects SET drive_account_key=? WHERE id=?", (OTHER_ACCOUNT_KEY, object_id))
        env.conn.commit()
        return remote

    env.drive.upload = bind_elsewhere
    result = _run(env)

    assert (result.synced, result.deferred, result.lost) == (0, 1, 0)
    state = object_state(env.conn, object_id)
    assert (state["state"], state["error"], state["lease"], state["account_key"]) == (
        "pending", "DRIVE_ACCOUNT_UNAVAILABLE", None, OTHER_ACCOUNT_KEY)


def test_ambiguous_owner_goes_to_reconciliation(env):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    # The schema forbids a shared object; the worker must still refuse one.
    env.conn.execute("DROP TRIGGER trg_admin_arquivos_storage_object_insert")
    env.conn.execute("INSERT INTO admin_arquivos(titulo,filename,provider,storage_status,storage_object_id)"
                     " VALUES('Dup','dup.pdf','local_legacy','legacy_active',?)", (object_id,))
    _commit(env.conn)

    # (Asserted at the owner lookup: the altered schema fails the pass's
    # schema validation before any claim.)
    with pytest.raises(drive_mirror._Refusal) as refused:
        drive_mirror._owner(env.conn, object_id)
    assert refused.value.code == "MIRROR_OWNER_AMBIGUOUS"
    assert drive_mirror._classify(refused.value) == ("reconcile", "MIRROR_OWNER_AMBIGUOUS")


def test_drive_authorization_failure_defers_the_rest_of_the_batch(env):
    ids = []
    for index in range(3):
        ids.append(seed_canonical_request_document(
            env.conn, env.store, key=f"comprovantes/2026/10/{index:032d}", content=PDF + bytes([index]),
            operation_key=f"op-{index}")[1])
    _commit(env.conn)
    env.drive.fail_next("upload", StorageAuthorizationError("reconnect"))

    result = _run(env)

    assert (result.result_code, result.deferred, result.synced) == ("DRIVE_AUTH_UNAVAILABLE", 3, 0)
    assert env.drive.calls.count("upload") == 1
    for object_id in ids:
        state = object_state(env.conn, object_id)
        assert (state["state"], state["error"], state["attempts"]) == ("pending", "DRIVE_AUTH_UNAVAILABLE", 0)
        assert state["next_attempt"] == custody_common.add_seconds(T0, drive_mirror.UNAVAILABLE_DELAY_SECONDS)


def test_object_bound_to_another_account_waits_pending(env):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    env.conn.execute("UPDATE storage_objects SET drive_account_key=? WHERE id=?", (OTHER_ACCOUNT_KEY, object_id))
    _commit(env.conn)

    result = _run(env)

    state = object_state(env.conn, object_id)
    assert (state["state"], state["error"], state["account_key"], state["attempts"]) == (
        "pending", "DRIVE_ACCOUNT_UNAVAILABLE", OTHER_ACCOUNT_KEY, 0)
    assert result.deferred == 1 and "upload" not in env.drive.calls
    for _ in range(drive_mirror.MAX_ATTEMPTS + 2):  # waiting never exhausts the retry budget
        env.clock.advance(drive_mirror.UNAVAILABLE_DELAY_SECONDS)
        _run(env)
    assert object_state(env.conn, object_id)["state"] == "pending"
    assert object_state(env.conn, object_id)["attempts"] == 0


def test_retired_objects_are_never_mirrored(env):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _commit(env.conn)
    with write_transaction(env.conn):
        outbox.retire_object(env.conn, object_id=object_id, now=T0)

    assert _run(env).claimed == 0
    assert env.drive.files == {}


def test_object_retired_after_claim_is_released_without_a_drive_write(env, monkeypatch):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _commit(env.conn)
    original_claim = outbox.claim_due_mirror_work

    def claim_then_retire(conn, **kwargs):
        claimed = original_claim(conn, **kwargs)
        outbox.retire_object(conn, object_id=object_id, now=T0)
        return claimed

    monkeypatch.setattr(outbox, "claim_due_mirror_work", claim_then_retire)

    result = _run(env)

    state = object_state(env.conn, object_id)
    assert (state["state"], state["error"], state["lifecycle"]) == ("pending", "OBJECT_RETIRED", "retired")
    assert result.deferred == 1 and env.drive.files == {}


# ---------------------------------------------------------------------------
# operator recovery
# ---------------------------------------------------------------------------


def _reconciled(env, key, code):
    _row, object_id = seed_canonical_request_document(env.conn, env.store, key=key, content=PDF + key.encode(),
                                                      operation_key=f"op-{key[-4:]}")
    env.conn.execute(
        "UPDATE storage_objects SET drive_sync_state='reconciliation_required',drive_last_error_code=?,"
        "drive_attempts=10 WHERE id=?", (code, object_id))
    return object_id


def test_requeue_resets_attempts_and_honours_the_code_filter(env):
    exhausted = _reconciled(env, REQ_KEY, "MIRROR_RETRY_EXHAUSTED")
    conflict = _reconciled(env, EXTRA_KEY, "REMOTE_SEMANTIC_CONFLICT")
    _commit(env.conn)

    with write_transaction(env.conn):
        assert outbox.requeue_for_mirror(env.conn, now=T0, limit=10, error_code="MIRROR_RETRY_EXHAUSTED") == 1
    state = object_state(env.conn, exhausted)
    assert (state["state"], state["attempts"], state["error"]) == ("pending", 0, "OPERATOR_REQUEUED")
    assert object_state(env.conn, conflict)["state"] == "reconciliation_required"

    assert _run(env).synced == 1
    with write_transaction(env.conn):
        assert outbox.requeue_for_mirror(env.conn, now=T0, limit=10) == 1
    assert _run(env).synced == 1


def test_requeue_refuses_an_unsanitized_code_and_skips_retired(env):
    retired = _reconciled(env, REQ_KEY, "MIRROR_RETRY_EXHAUSTED")
    env.conn.execute("UPDATE storage_objects SET lifecycle_state='retired',retired_at=? WHERE id=?", (T0, retired))
    _commit(env.conn)
    with write_transaction(env.conn):
        with pytest.raises(ValueError):
            outbox.requeue_for_mirror(env.conn, now=T0, limit=10, error_code="bad code")
    with write_transaction(env.conn):
        assert outbox.requeue_for_mirror(env.conn, now=T0, limit=10) == 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(env, *argv):
    out = io.StringIO()
    env.conn.commit()
    code = cli_main(list(argv), app=env.app, out=out)
    return code, (json.loads(out.getvalue()) if out.getvalue() else None)


def test_cli_mirror_run_reports_value_free_counts(env):
    seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    seed_canonical_arquivo(env.conn, env.store, key=ARQ_KEY, content=PNG, mime="image/png")
    _commit(env.conn)

    code, report = _cli(env, "mirror-run", "--passes", "5", "--limit", "1")

    assert code == EXIT_OK
    assert [item["synced"] for item in report["passes"]] == [1, 1, 0]
    text = json.dumps(report)
    for forbidden in (REQ_KEY, ARQ_KEY, "REQ-000001", "ARQ-abc", "Aluno", ACCOUNT_KEY, "sub:slot", BUCKET):
        assert forbidden not in text


def test_cli_mirror_run_is_not_runnable_without_drive(env):
    env.conn.execute("UPDATE cloud_accounts SET active=0")
    code, report = _cli(env, "mirror-run")

    assert code == EXIT_NOT_RUNNABLE
    assert report["passes"][0]["result_code"] == "DRIVE_NOT_CONNECTED"


def test_cli_mirror_requeue_and_usage_errors(env):
    object_id = _reconciled(env, REQ_KEY, "MIRROR_RETRY_EXHAUSTED")

    assert _cli(env, "mirror-requeue", "--code", "bad code") == (EXIT_USAGE, None)
    assert _cli(env, "mirror-run", "--limit", "0") == (EXIT_USAGE, None)
    assert _cli(env, "mirror-requeue") == (EXIT_OK, {"command": "mirror-requeue", "requeued": 1})
    assert object_state(env.conn, object_id)["state"] == "pending"


# ---------------------------------------------------------------------------
# I2: the mirror never trashes Drive files nor writes canonical objects
# ---------------------------------------------------------------------------


def test_no_mirror_outcome_trashes_drive_or_writes_canonical(env):
    seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    seed_canonical_arquivo(env.conn, env.store, key=ARQ_KEY, content=PNG, mime="image/png")
    _commit(env.conn)
    env.drive.corrupt_next_upload = True

    _run(env)
    env.clock.advance(3600)
    _run(env)

    assert not {"trash", "untrash", "delete"} & set(env.drive.calls)
    assert set(env.store.calls) <= {"read", "stat"}
    assert sha256(env.store.objects[(BUCKET, REQ_KEY)][0]) == sha256(PDF)


def test_tripwires_cannot_be_swallowed_by_the_item_isolation(env, monkeypatch):
    """Negative control of the I2 tripwire: a mirror that deleted would fail loudly."""
    seed_canonical_request_document(env.conn, env.store, key=REQ_KEY, content=PDF)
    _commit(env.conn)
    original = drive_mirror._verified_remote

    def verify_then_delete(work, placement, remote):
        original(work, placement, remote)
        env.store.delete(work.storage_bucket, work.storage_key)

    monkeypatch.setattr(drive_mirror, "_verified_remote", verify_then_delete)
    with pytest.raises(Tripwire):
        _run(env)
    assert "delete" in env.store.calls
