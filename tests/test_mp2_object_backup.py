# coding: utf-8
"""MP-2 slice 5: the operator object backup (``app.storage.object_backup`` and its CLI).

The database is a real (SQLite) v16 file and the canonical store the in-memory
fake.  Every guarantee has its discriminating negative control: a corrupted
byte, a deleted file, an extra file, a truncated or re-sealed-but-inconsistent
manifest, a missing / changed database row, a target conflict, a provider
failure, an invalid bucket -- each must be detected, and none may write.
"""

from __future__ import annotations

import io
import json
import os
import shutil
from pathlib import Path

import pytest

from app.storage import cli, object_backup
from app.storage.object_store import STORAGE_INTEGRITY_MISMATCH, STORAGE_OBJECT_MISSING
from tests.canonical_store_fake import InMemoryObjectStore
from tests.storage_mp1_support import BUCKET, insert_object, sqlite_storage_env

REPO = Path(__file__).resolve().parents[1]
PDF = b"%PDF-1.4\n" + b"0123456789abcdef" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"fedcba9876543210" * 40


@pytest.fixture
def env(tmp_path, monkeypatch):
    with sqlite_storage_env(tmp_path, monkeypatch) as storage:
        yield storage


def _object(env, name: str, content: bytes, mime: str = "application/pdf", **columns) -> int:
    key = f"comprovantes/2026/10/{name}"
    object_id = insert_object(env.conn, key=key, content=content, mime=mime, **columns)
    env.store.objects[(BUCKET, key)] = (content, mime)
    return object_id


def _seed(env) -> list[int]:
    ids = [
        _object(env, "a" * 32, PDF),
        _object(env, "b" * 32, PNG, "image/png"),
        _object(env, "c" * 32, PDF + b"2"),
        _object(env, "d" * 32, PDF),  # the same bytes as the first: one content file, two rows
    ]
    env.conn.commit()
    return ids


@pytest.fixture
def made(env, tmp_path):
    ids = _seed(env)
    target = tmp_path / "set-1"
    report = object_backup.backup(env.conn, env.store, str(target), label="rehearsal")
    assert report.ok, report.as_dict()
    return env, target, ids, report


def _copy(src: Path, tmp_path: Path, name: str) -> Path:
    dest = tmp_path / name
    shutil.copytree(src, dest)
    return dest


def _content_file(set_dir: Path, content: bytes) -> Path:
    import hashlib

    sha = hashlib.sha256(content).hexdigest()
    return set_dir / "objects" / sha[:2] / sha


def _rewrite_manifest(set_dir: Path, mutate, *, reseal: bool) -> None:
    path = set_dir / "MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="ascii"))
    mutate(manifest)
    if reseal:
        manifest["seal"] = object_backup._seal(manifest)
    path.write_text(json.dumps(manifest), encoding="ascii")


# --- backup -------------------------------------------------------------------------


def test_backup_writes_a_complete_sealed_set_and_only_reads_the_store(made):
    env, target, ids, report = made
    assert (report.objects, report.contents) == (4, 3)
    assert report.bytes == len(PDF) + len(PNG) + len(PDF) + 1
    assert report.objects_digest == object_backup.objects_digest(object_backup.current_rows(env.conn))
    assert sorted(os.listdir(target)) == ["MANIFEST.json", "objects"]
    assert set(env.store.calls) <= {"stat", "read"}  # never an upload or a delete
    manifest = json.loads((target / "MANIFEST.json").read_text(encoding="ascii"))
    assert manifest["counts"] == {"objects": 4, "contents": 3, "bytes": report.bytes, "active": 4, "retired": 0}
    assert manifest["label"] == "rehearsal"
    assert [row["id"] for row in manifest["objects"]] == ids
    verified = object_backup.verify_set(str(target), conn=env.conn)
    assert verified.ok and verified.sealed
    assert verified.database == {"missing": 0, "extra": 0, "changed": 0,
                                 "missing_ids": [], "extra_ids": [], "changed_ids": []}


def test_retired_objects_are_part_of_the_set(env, tmp_path):
    kept = _object(env, "a" * 32, PDF)
    gone = _object(env, "b" * 32, PNG, "image/png")
    env.conn.execute(
        "UPDATE storage_objects SET lifecycle_state='retired', retired_at='2026-10-09 12:00:00' WHERE id=?", (gone,)
    )
    env.conn.commit()
    report = object_backup.backup(env.conn, env.store, str(tmp_path / "set"))
    assert report.ok and report.objects == 2
    manifest = json.loads((tmp_path / "set" / "MANIFEST.json").read_text(encoding="ascii"))
    assert manifest["counts"]["active"] == 1 and manifest["counts"]["retired"] == 1
    assert {row["id"]: row["lifecycle"] for row in manifest["objects"]} == {kept: "active", gone: "retired"}


def test_an_empty_database_gives_a_valid_empty_set(env, tmp_path):
    report = object_backup.backup(env.conn, env.store, str(tmp_path / "empty"))
    assert report.ok and (report.objects, report.contents, report.bytes) == (0, 0, 0)
    assert object_backup.verify_set(str(tmp_path / "empty"), conn=env.conn).ok


def test_an_existing_destination_is_never_replaced(made, tmp_path):
    env, target, _ids, _report = made
    before = (target / "MANIFEST.json").read_bytes()
    with pytest.raises(object_backup.SetInvalid) as refused:
        object_backup.backup(env.conn, env.store, str(target))
    assert refused.value.code == object_backup.DESTINATION_EXISTS
    assert (target / "MANIFEST.json").read_bytes() == before
    assert not list(tmp_path.glob("set-1.partial-*"))


def test_the_default_repository_root_is_the_real_one_and_refuses_without_writing():
    """Pure check against the real repository: a regressed guard returns a path, creating nothing."""
    assert object_backup._REPO_ROOT == REPO
    for inside in (REPO / "backup-set", REPO / "app" / "backup-set", REPO):
        with pytest.raises(object_backup.SetInvalid) as refused:
            object_backup._resolve_destination(str(inside), object_backup._REPO_ROOT)
        assert refused.value.code in (
            object_backup.DESTINATION_INSIDE_REPOSITORY, object_backup.DESTINATION_EXISTS
        )


@pytest.mark.parametrize("inside", ["set", "nested/set", "NESTED/set"])
def test_a_destination_inside_the_repository_is_refused_before_anything_is_written(env, tmp_path, inside):
    fake_repo = tmp_path / "fake-repo"
    (fake_repo / "nested").mkdir(parents=True)
    destination = fake_repo / inside
    with pytest.raises(object_backup.SetInvalid) as refused:
        object_backup.backup(env.conn, env.store, str(destination), repo_root=fake_repo)
    assert refused.value.code == object_backup.DESTINATION_INSIDE_REPOSITORY
    assert not destination.exists() and env.store.calls == []
    assert [path.name for path in fake_repo.iterdir()] == ["nested"]


def _link_directory(link: Path, target: Path) -> bool:
    """A directory symlink, or a junction on Windows (no privilege needed); False if neither works."""
    import subprocess

    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        return done.returncode == 0 and link.exists()
    return False


def test_a_link_or_junction_into_the_repository_is_refused_too(env, tmp_path):
    fake_repo = tmp_path / "fake-repo"
    fake_repo.mkdir()
    alias = tmp_path / "alias"
    if not _link_directory(alias, fake_repo):
        pytest.skip("this platform/user cannot create a directory link")
    with pytest.raises(object_backup.SetInvalid) as refused:
        object_backup.backup(env.conn, env.store, str(alias / "set"), repo_root=fake_repo)
    assert refused.value.code == object_backup.DESTINATION_INSIDE_REPOSITORY
    assert list(fake_repo.iterdir()) == [] and env.store.calls == []


@pytest.mark.parametrize("label", ["a b", "é", "x" * 65, "../up"])
def test_a_label_outside_the_alphabet_is_refused(env, tmp_path, label):
    with pytest.raises(object_backup.SetInvalid) as refused:
        object_backup.backup(env.conn, env.store, str(tmp_path / "set"), label=label)
    assert refused.value.code == object_backup.LABEL_INVALID
    assert not (tmp_path / "set").exists()


def test_a_missing_parent_is_refused(env, tmp_path):
    with pytest.raises(object_backup.SetInvalid) as refused:
        object_backup.backup(env.conn, env.store, str(tmp_path / "no-such" / "set"))
    assert refused.value.code == object_backup.DESTINATION_INVALID


def test_one_unreadable_object_aborts_and_leaves_nothing(env, tmp_path):
    ids = _seed(env)
    del env.store.objects[(BUCKET, "comprovantes/2026/10/" + "b" * 32)]
    report = object_backup.backup(env.conn, env.store, str(tmp_path / "set"))
    assert report.result_code == object_backup.UNREADABLE_OBJECTS
    assert report.unreadable == {STORAGE_OBJECT_MISSING: [ids[1]]} and report.unreadable_count == 1
    assert not (tmp_path / "set").exists() and not list(tmp_path.glob("set.partial-*"))


def test_a_corrupted_object_is_reported_not_copied(env, tmp_path):
    ids = _seed(env)
    key = (BUCKET, "comprovantes/2026/10/" + "c" * 32)
    content, mime = env.store.objects[key]
    env.store.objects[key] = (b"X" * len(content), mime)  # same size, other bytes
    report = object_backup.backup(env.conn, env.store, str(tmp_path / "set"))
    assert report.result_code == object_backup.UNREADABLE_OBJECTS
    assert report.unreadable == {STORAGE_INTEGRITY_MISMATCH: [ids[2]]}
    assert not (tmp_path / "set").exists()


def test_reports_carry_no_locator_and_no_name(made):
    _env, _target, _ids, report = made
    text = json.dumps(report.as_dict())
    assert BUCKET not in text and "comprovantes" not in text and "pdf" not in text.lower()


# --- verify: every control is detected -----------------------------------------------


def test_a_corrupted_byte_is_detected(made, tmp_path):
    _env, target, _ids, _r = made
    copy = _copy(target, tmp_path, "corrupt")
    path = _content_file(copy, PNG)
    data = bytearray(path.read_bytes())
    data[10] ^= 0xFF
    path.write_bytes(bytes(data))
    report = object_backup.verify_set(str(copy))
    assert (report.corrupt, report.missing, report.ok) == (1, 0, False)


def test_a_truncated_content_file_is_detected(made, tmp_path):
    copy = _copy(made[1], tmp_path, "short")
    path = _content_file(copy, PDF + b"2")
    path.write_bytes(path.read_bytes()[:-1])
    assert object_backup.verify_set(str(copy)).corrupt == 1


def test_a_deleted_content_file_is_detected(made, tmp_path):
    copy = _copy(made[1], tmp_path, "gone")
    _content_file(copy, PNG).unlink()
    report = object_backup.verify_set(str(copy))
    assert (report.missing, report.ok) == (1, False)


def test_an_unexpected_file_is_detected(made, tmp_path):
    copy = _copy(made[1], tmp_path, "extra")
    (copy / "objects" / "ff").mkdir()
    (copy / "objects" / "ff" / ("f" * 64)).write_bytes(b"stowaway")
    (copy / "notes.txt").write_text("hello")
    report = object_backup.verify_set(str(copy))
    assert (report.unexpected, report.ok) == (2, False)


def test_a_truncated_manifest_is_invalid(made, tmp_path):
    copy = _copy(made[1], tmp_path, "cut")
    path = copy / "MANIFEST.json"
    path.write_bytes(path.read_bytes()[:200])
    report = object_backup.verify_set(str(copy))
    assert report.result_code == object_backup.SET_INVALID and not report.sealed


def test_a_tampered_manifest_fails_the_seal(made, tmp_path):
    copy = _copy(made[1], tmp_path, "tampered")
    _rewrite_manifest(copy, lambda m: m.update(label="forged"), reseal=False)
    assert object_backup.verify_set(str(copy)).result_code == object_backup.SET_INVALID


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m["counts"].update(objects=99),
        lambda m: m["objects"][0].update(size=m["objects"][0]["size"] + 1),
        lambda m: m["objects"].pop(),
        lambda m: m["objects"][0].update(sha256="Z" * 64),
        lambda m: m["objects"][0].update(key="../escape"),
        lambda m: m.update(format=2),
        lambda m: m.update(extra="field"),
        lambda m: m.update(objects_digest="0" * 64),
        lambda m: m["objects"][0].update(mime="text/plain"),
        lambda m: m["objects"][0].update(lifecycle="gone"),
        lambda m: m["objects"][0].update(id=True),
        lambda m: m["objects"][1].update(id=m["objects"][0]["id"]),
        lambda m: m.update(created_at="yesterday"),
        lambda m: m.update(label="a b"),
        lambda m: m["objects"][0].update(bucket="UPPER"),
    ],
    ids=["counts", "size", "dropped-row", "digest-shape", "locator", "format", "unknown-field",
         "objects-digest", "mime", "lifecycle", "id-is-bool", "id-order", "created-at", "label", "bucket"],
)
def test_a_resealed_but_inconsistent_manifest_is_still_refused(made, tmp_path, mutate):
    copy = _copy(made[1], tmp_path, "inconsistent")
    _rewrite_manifest(copy, mutate, reseal=True)
    assert object_backup.verify_set(str(copy)).result_code == object_backup.SET_INVALID


def test_a_missing_set_is_reported(tmp_path):
    assert object_backup.verify_set(str(tmp_path / "nope")).result_code == object_backup.SET_NOT_FOUND


def test_database_comparison_names_missing_extra_and_changed(made):
    env, target, ids, _r = made
    env.conn.execute("DELETE FROM storage_objects WHERE id=?", (ids[0],))
    env.conn.execute("UPDATE storage_objects SET mime_type='image/png' WHERE id=?", (ids[2],))
    newcomer = _object(env, "e" * 32, PDF + b"3")
    env.conn.commit()
    report = object_backup.verify_set(str(target), conn=env.conn)
    assert not report.ok and report.result_code == object_backup.RESULT_OK  # the set itself is sound
    assert report.database["missing"] == 1 and report.database["missing_ids"] == [newcomer]
    assert report.database["extra"] == 1 and report.database["extra_ids"] == [ids[0]]
    assert report.database["changed"] == 1 and report.database["changed_ids"] == [ids[2]]


# --- restore -------------------------------------------------------------------------


def test_restore_fills_an_empty_bucket_and_reads_everything_back(made):
    _env, target, _ids, _r = made
    fresh = InMemoryObjectStore()
    report = object_backup.restore(str(target), fresh)
    assert report.ok and (report.restored, report.adopted) == (4, 0)
    assert len(fresh.objects) == 4
    assert "delete" not in fresh.calls
    assert fresh.calls.count("upload") == 4 and fresh.calls.count("read") >= 4  # read back
    for (bucket, key), (content, mime) in fresh.objects.items():
        assert _env.store.objects[(bucket, key)] == (content, mime)


def test_restore_into_another_bucket_keeps_the_keys(made):
    _env, target, _ids, _r = made
    fresh = InMemoryObjectStore()
    report = object_backup.restore(str(target), fresh, bucket="sgaa-restore-target")
    assert report.ok
    assert {bucket for bucket, _key in fresh.objects} == {"sgaa-restore-target"}
    assert {key for _bucket, key in fresh.objects} == {key for _b, key in _env.store.objects}


def test_a_second_restore_adopts_instead_of_uploading(made):
    _env, target, _ids, _r = made
    fresh = InMemoryObjectStore()
    object_backup.restore(str(target), fresh)
    uploads = fresh.calls.count("upload")
    again = object_backup.restore(str(target), fresh)
    assert again.ok and (again.restored, again.adopted) == (0, 4)
    assert fresh.calls.count("upload") == uploads


def test_a_conflicting_object_is_never_overwritten(made):
    env, target, ids, _r = made
    fresh = InMemoryObjectStore()
    conflict_key = (BUCKET, "comprovantes/2026/10/" + "b" * 32)
    fresh.objects[conflict_key] = (b"someone else's bytes", "application/pdf")
    report = object_backup.restore(str(target), fresh)
    assert report.result_code == object_backup.TARGET_CONFLICT and not report.ok
    assert report.conflicts == 1 and report.ids[object_backup.TARGET_CONFLICT] == [ids[1]]
    assert fresh.objects[conflict_key] == (b"someone else's bytes", "application/pdf")  # untouched
    assert report.restored == 3 and len(fresh.objects) == 4
    assert "delete" not in fresh.calls


def test_an_invalid_set_never_reaches_the_store(made, tmp_path):
    copy = _copy(made[1], tmp_path, "bad")
    path = _content_file(copy, PDF)
    path.write_bytes(path.read_bytes()[::-1])
    fresh = InMemoryObjectStore()
    report = object_backup.restore(str(copy), fresh)
    assert report.result_code == object_backup.SET_INVALID and not report.ok
    assert fresh.calls == [] and fresh.objects == {}


@pytest.mark.parametrize("bucket", ["Upper", "has space", "", "x" * 80, "../b"])
def test_an_invalid_target_bucket_is_refused_before_any_call(made, bucket):
    fresh = InMemoryObjectStore()
    report = object_backup.restore(str(made[1]), fresh, bucket=bucket)
    assert report.result_code == object_backup.TARGET_BUCKET_INVALID
    assert fresh.calls == []


def test_a_provider_failure_stops_the_restore_and_is_reported(made):
    fresh = InMemoryObjectStore()
    original = fresh.upload
    state = {"n": 0}

    def flaky(bucket, key, content, *, mime_type):
        state["n"] += 1
        if state["n"] == 2:
            fresh.fail_next("STORAGE_PROVIDER_UNAVAILABLE")
        return original(bucket, key, content, mime_type=mime_type)

    fresh.upload = flaky
    report = object_backup.restore(str(made[1]), fresh)
    assert report.stopped and report.failed == 1 and not report.ok
    assert report.result_code == object_backup.STORE_FAILURE
    assert len(fresh.objects) == 1  # what was placed stays; nothing is rolled back or deleted
    assert "delete" not in fresh.calls


def test_a_restore_that_does_not_read_back_the_bytes_is_caught(made):
    fresh = InMemoryObjectStore()
    original = fresh.read
    state = {"seen": 0}

    def lossy(bucket, key, *, max_bytes):
        content = original(bucket, key, max_bytes=max_bytes)
        state["seen"] += 1
        return content[:-1]  # the storage returns less than was stored

    fresh.read = lossy
    report = object_backup.restore(str(made[1]), fresh)
    assert report.readback_failed == 4 and report.result_code == object_backup.READBACK_MISMATCH


# --- CLI -----------------------------------------------------------------------------


def _run(argv, *, app=None):
    out = io.StringIO()
    code = cli.main(argv, app=app, out=out)
    return code, (json.loads(out.getvalue()) if out.getvalue().strip() else None), out.getvalue()


def test_cli_backup_verify_restore_round_trip_and_reports_are_value_free(env, tmp_path, monkeypatch):
    _seed(env)
    target = str(tmp_path / "cli-set")
    code, report, raw = _run(["backup-objects", "--destination", target, "--label", "cli"], app=env.app)
    assert code == cli.EXIT_OK and report["result_code"] == "OK" and report["objects"] == 4
    assert "comprovantes" not in raw and BUCKET not in raw

    # Offline verification starts no application and opens no database.
    import app as app_package
    import app.db as app_db

    def boom(*_a, **_k):
        raise AssertionError("an offline command started the application or opened the database")

    monkeypatch.setattr(app_package, "create_app", boom)
    monkeypatch.setattr(app_db, "get_db_connection", boom)
    code, report, _raw = _run(["verify-backup", "--set", target])
    assert code == cli.EXIT_OK and report["sealed"] is True and report["database"] is None

    fresh = InMemoryObjectStore()
    from app.storage.supabase_store import SupabaseObjectStore

    # The fixture keeps an application context open; an operator's shell has none.
    monkeypatch.setattr("flask.has_app_context", lambda: False)
    monkeypatch.setattr(SupabaseObjectStore, "from_environment", classmethod(lambda cls, *a, **k: fresh))
    code, report, raw = _run(["restore-objects", "--set", target, "--bucket", "sgaa-cli-restore"])
    assert code == cli.EXIT_OK and report["restored"] == 4
    assert "comprovantes" not in raw and "sgaa-cli-restore" not in raw


def test_cli_exit_codes_for_each_failure_class(env, tmp_path, monkeypatch):
    _seed(env)
    target = str(tmp_path / "set")
    assert _run(["backup-objects", "--destination", target], app=env.app)[0] == cli.EXIT_OK
    # the destination exists now: a usage error, not a crash
    assert _run(["backup-objects", "--destination", target], app=env.app)[0] == cli.EXIT_USAGE
    # a corrupted set: exit 4
    path = _content_file(Path(target), PNG)
    path.write_bytes(path.read_bytes()[::-1])
    code, report, _raw = _run(["verify-backup", "--set", target])
    assert code == cli.EXIT_NOT_CONVERGED and report["corrupt"] == 1
    # no storage configuration: not runnable (3)
    monkeypatch.setattr("flask.has_app_context", lambda: False)
    for name in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "SGAA_STORAGE_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    code, report, _raw = _run(["restore-objects", "--set", target])
    assert code == cli.EXIT_NOT_RUNNABLE and report["result_code"] == "STORAGE_CONFIG_MISSING"


def test_cli_verify_with_database_compares_the_rows(env, tmp_path):
    ids = _seed(env)
    target = str(tmp_path / "set")
    assert _run(["backup-objects", "--destination", target], app=env.app)[0] == cli.EXIT_OK
    assert _run(["verify-backup", "--set", target, "--database"], app=env.app)[0] == cli.EXIT_OK
    env.conn.execute("DELETE FROM storage_objects WHERE id=?", (ids[0],))
    env.conn.commit()
    code, report, _raw = _run(["verify-backup", "--set", target, "--database"], app=env.app)
    assert code == cli.EXIT_NOT_CONVERGED and report["database"]["extra"] == 1


# --- review controls: bounds, damaged manifests, links, races, promotion ----------------------


def test_the_object_bound_and_the_space_check_refuse_before_writing(env, tmp_path, monkeypatch):
    _seed(env)
    monkeypatch.setattr(object_backup, "MAX_OBJECTS", 2)
    report = object_backup.backup(env.conn, env.store, str(tmp_path / "many"))
    assert report.result_code == object_backup.TOO_MANY_OBJECTS and not (tmp_path / "many").exists()
    monkeypatch.setattr(object_backup, "MAX_OBJECTS", 100_000)
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(object_backup.shutil, "disk_usage", lambda _p: usage(10, 10, 0))
    report = object_backup.backup(env.conn, env.store, str(tmp_path / "full"))
    assert report.result_code == object_backup.INSUFFICIENT_SPACE and not (tmp_path / "full").exists()
    assert env.store.calls == []


def test_a_damaged_manifest_is_a_set_invalid_report_never_an_exception(made, tmp_path):
    for name, payload in (
        ("nested", b"[" * 100_000 + b"]" * 100_000),
        ("bignum", b'{"format": ' + b"9" * 6000 + b"}"),
        ("binary", bytes(range(256))),
        ("empty", b""),
        ("scalar", b"7"),
    ):
        copy = _copy(made[1], tmp_path, f"damaged-{name}")
        (copy / "MANIFEST.json").write_bytes(payload)
        assert object_backup.verify_set(str(copy)).result_code == object_backup.SET_INVALID, name
        fresh = InMemoryObjectStore()
        assert object_backup.restore(str(copy), fresh).result_code == object_backup.SET_INVALID
        assert fresh.calls == []


def test_tampering_with_any_sealed_field_is_detected(made, tmp_path):
    for index, mutate in enumerate((
        lambda m: m.update(created_at="2001-01-01 00:00:00"),
        lambda m: m["objects"][0].update(mime="image/png"),
        lambda m: m["objects"][0].update(key="comprovantes/2026/10/" + "9" * 32),
        lambda m: m.update(label="x"),
    )):
        copy = _copy(made[1], tmp_path, f"seal-{index}")
        _rewrite_manifest(copy, mutate, reseal=False)
        assert object_backup.verify_set(str(copy)).result_code == object_backup.SET_INVALID, index


def test_stray_directories_and_a_linked_objects_directory_are_unexpected(made, tmp_path):
    copy = _copy(made[1], tmp_path, "strays")
    (copy / "objects" / "zz").mkdir()          # an invalid shard name, empty
    (copy / "objects" / "ab" / "nested").mkdir(parents=True)  # a directory where a file belongs
    (copy / "objects" / "abc").mkdir()         # a three-character shard
    report = object_backup.verify_set(str(copy))
    assert report.unexpected == 3 and not report.ok

    linked = _copy(made[1], tmp_path, "linked")
    outside = tmp_path / "outside-objects"
    shutil.move(str(linked / "objects"), str(outside))
    if not _link_directory(linked / "objects", outside):
        pytest.skip("this platform/user cannot create a directory link")
    report = object_backup.verify_set(str(linked))
    assert not report.ok and report.unexpected >= 1 and report.missing == 3  # never read through the link


def test_a_linked_shard_is_not_read_through(made, tmp_path):
    copy = _copy(made[1], tmp_path, "shard-link")
    shard = _content_file(copy, PNG).parent
    outside = tmp_path / "outside-shard"
    shutil.move(str(shard), str(outside))
    if not _link_directory(shard, outside):
        pytest.skip("this platform/user cannot create a directory link")
    report = object_backup.verify_set(str(copy))
    assert not report.ok and report.missing >= 1 and report.unexpected >= 1


def test_a_failed_promotion_keeps_the_complete_set_and_says_where(env, tmp_path, monkeypatch):
    _seed(env)
    real_rename = os.rename

    def locked(src, dst):
        raise PermissionError("the file is in use")

    monkeypatch.setattr(object_backup.os, "rename", locked)
    report = object_backup.backup(env.conn, env.store, str(tmp_path / "set"))
    monkeypatch.setattr(object_backup.os, "rename", real_rename)
    assert report.result_code == object_backup.PROMOTE_FAILED and report.staged_as
    staged = tmp_path / report.staged_as
    assert object_backup.verify_set(str(staged), conn=env.conn).ok  # complete and usable as is
    assert not (tmp_path / "set").exists()


def test_a_restore_that_meets_a_changed_file_stops_but_still_reads_back_what_it_placed(made, tmp_path, monkeypatch):
    _env, target, _ids, _r = made
    copy = _copy(target, tmp_path, "changing")
    fresh = InMemoryObjectStore()
    real_verify = object_backup.verify_set
    victim = _content_file(copy, PDF + b"2")  # the third distinct content, restored after two uploads

    def verify_then_change(set_dir, **kwargs):
        report = real_verify(set_dir, **kwargs)
        victim.write_bytes(b"changed after the set was verified")
        return report

    monkeypatch.setattr(object_backup, "verify_set", verify_then_change)
    report = object_backup.restore(str(copy), fresh)
    assert report.result_code == object_backup.SET_INVALID and report.stopped
    assert report.restored == 2 and report.readback_failed == 0
    assert fresh.calls.count("read") >= 2  # what had been placed was still proven
    assert all(content != b"changed after the set was verified" for content, _m in fresh.objects.values())


def test_an_existing_object_is_adopted_only_when_size_digest_and_type_all_match(made):
    env, target, ids, _r = made
    key = (BUCKET, "comprovantes/2026/10/" + "a" * 32)
    content, mime = env.store.objects[key]
    # same size, other bytes: not adoptable (a size-only comparison would adopt it)
    other = InMemoryObjectStore()
    other.objects[key] = (b"Z" * len(content), mime)
    report = object_backup.restore(str(target), other)
    assert report.conflicts >= 1 and report.ids[object_backup.TARGET_CONFLICT][0] == ids[0]
    assert other.objects[key][0] == b"Z" * len(content)
    # same bytes, other media type: a conflict too
    typed = InMemoryObjectStore()
    typed.objects[key] = (content, "image/png")
    report = object_backup.restore(str(target), typed)
    assert report.conflicts >= 1 and typed.objects[key][1] == "image/png"


def test_losing_the_upload_race_adopts_identical_bytes_and_flags_different_ones(made):
    env, target, _ids, _r = made
    key = (BUCKET, "comprovantes/2026/10/" + "c" * 32)
    content, mime = env.store.objects[key]
    for bytes_there, expected in ((content, "adopted"), (b"Y" * len(content), "conflict")):
        racing = InMemoryObjectStore()
        original = racing.upload

        def upload(bucket, k, data, *, mime_type, _orig=original, _there=bytes_there, _store=racing):
            if (bucket, k) == key and (bucket, k) not in _store.objects:
                _store.objects[(bucket, k)] = (_there, mime)  # another writer wins between exists and upload
            return _orig(bucket, k, data, mime_type=mime_type)

        racing.upload = upload
        report = object_backup.restore(str(target), racing)
        assert racing.objects[key][0] == bytes_there  # never overwritten
        if expected == "adopted":
            assert report.ok and report.adopted == 1
        else:
            assert report.conflicts == 1 and not report.ok


def test_the_read_back_compares_bytes_not_just_length(made):
    fresh = InMemoryObjectStore()
    original = fresh.read

    def same_length_other_bytes(bucket, key, *, max_bytes):
        content = original(bucket, key, max_bytes=max_bytes)
        return bytes([content[0] ^ 1]) + content[1:]

    fresh.read = same_length_other_bytes
    report = object_backup.restore(str(made[1]), fresh)
    assert report.readback_failed == 4 and report.result_code == object_backup.READBACK_MISMATCH


def test_adopted_objects_are_not_read_a_second_time(made):
    fresh = InMemoryObjectStore()
    object_backup.restore(str(made[1]), fresh)
    reads_after_first = fresh.calls.count("read")
    again = object_backup.restore(str(made[1]), fresh)
    assert again.adopted == 4
    assert fresh.calls.count("read") - reads_after_first == 4  # one verification read per adopted object
