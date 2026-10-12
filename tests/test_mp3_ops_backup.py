# coding: utf-8
"""MP-3 slice 4: the scheduled operator backup sequencer (``tools/ops_backup.py``) -- no database.

The children (``pg_backup``, the object-backup commands) are scripted: the tool's
own contract is what is tested -- the order of steps, that nothing is rotated or
deleted unless every step passed, that the off-platform copy is compared byte
for byte, and that rotation can only ever delete a generation the tool itself
registered (never a hand-made set, a foreign file or the cutover baseline).
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools import ops_backup as ob

DUMP_SUFFIXES = (".dump", ".dump.sha256", ".manifest.json")


class _Children:
    """Scripted ``pg_backup`` / object-backup children that create the files the real ones do."""

    def __init__(self, fail_at: str | None = None, created_at: str | None = None) -> None:
        self.created_at = created_at
        self.calls: list[list[str]] = []
        self.envs: list[dict | None] = []
        self.fail_at = fail_at
        self.counter = 0

    def __call__(self, command: list[str], env: dict | None = None) -> int:
        self.calls.append(command)
        self.envs.append(env)
        text = " ".join(command)
        if "pg_backup.py" in text and " backup " in f" {text} ":
            if self.fail_at == "DATABASE_BACKUP":
                return 4
            self.counter += 1
            directory = Path(command[command.index("--output-dir") + 1])
            label = command[command.index("--label") + 1]
            base = f"sgaa-pg-20261010T0000{self.counter:02d}Z-{label}"
            directory.mkdir(parents=True, exist_ok=True)
            for suffix in DUMP_SUFFIXES:
                (directory / (base + suffix)).write_bytes(f"{base}{suffix}".encode())
            # The real manifest carries its creation time (the ledger measures the cadence by it) and the
            # digest of the dump it describes.
            dump = (directory / (base + ".dump")).read_bytes()
            (directory / (base + ".manifest.json")).write_text(
                json.dumps({"set": base, "created_at": self.created_at or f"2026-10-10T00:00:{self.counter:02d}Z",
                            "source": {"database": "postgres", "system_identifier": "1"},
                            "artifact": {"sha256": hashlib.sha256(dump).hexdigest()}}), encoding="utf-8")
            return 0
        if "pg_backup.py" in text and " verify " in f" {text} ":
            return 3 if self.fail_at == "DATABASE_VERIFY" else 0
        if "backup-objects" in text:
            if self.fail_at == "OBJECT_BACKUP":
                return 4
            destination = Path(command[command.index("--destination") + 1])
            if not destination.parent.is_dir() or destination.exists():
                return 2  # the real tool: DESTINATION_INVALID / DESTINATION_EXISTS (it never creates parents)
            (destination / "objects" / "ab").mkdir(parents=True)
            # The real set seals its source (the database read, the store's host) and its creation time.
            (destination / "MANIFEST.json").write_bytes(
                json.dumps({"source": {"database": None, "store_host": "fake-store"},
                            "created_at": "2026-10-09 23:59:58"}).encode("ascii"))
            (destination / "objects" / "ab" / "abcd").write_bytes(b"bytes")
            return 0
        if "verify-backup" in text:
            return 3 if self.fail_at == "OBJECT_VERIFY" else 0
        raise AssertionError(f"unexpected child: {text[:80]}")


@pytest.fixture
def dirs(tmp_path):
    return tmp_path / "primary", tmp_path / "off-platform"


_TICK = {"n": 0}


def _clock():
    """One second later on every call, so object-set names (second resolution) never collide."""
    _TICK["n"] += 1
    return datetime(2026, 10, 10, 0, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=_TICK["n"])


def _generation(dirs, children, **kwargs):
    root, off = dirs
    options = dict(label="scheduled", generations=2, objects=False, off_platform=off, runner=children,
                   clock=_clock)
    options.update(kwargs)
    return ob.run_generation(root, **options)


def _manifests(directory: Path):
    return sorted(p.name for p in directory.glob("*.manifest.json"))


def _hand_made_set(directory: Path, base: str):
    directory.mkdir(parents=True, exist_ok=True)
    for suffix in DUMP_SUFFIXES:
        (directory / (base + suffix)).write_bytes(b"made by hand")


def test_a_generation_runs_every_step_in_order_and_copies_it_off_platform_verified(dirs):
    children = _Children()
    result = _generation(dirs, children, objects=True)
    assert result["result"] == "GENERATION_COMPLETE"
    assert [s["step"] for s in result["steps"]] == [
        "DATABASE_BACKUP", "DATABASE_VERIFY", "OBJECT_BACKUP", "OBJECT_VERIFY"]
    root, off = dirs
    assert len(_manifests(root / "layer2")) == 1 and len(_manifests(off / "layer2")) == 1
    object_sets = list((off / "objects").iterdir())
    assert len(object_sets) == 1 and (object_sets[0] / "objects" / "ab" / "abcd").read_bytes() == b"bytes"
    assert result["files_copied_verified"] == 3 + 2  # three database files, two object-set files
    assert result["off_platform_encryption"] == "OPERATOR_RESPONSIBILITY"
    assert any("verify-backup" in " ".join(c) and "--database" in c for c in children.calls)


def test_rotation_keeps_the_newest_registered_generations_in_both_places(dirs):
    children = _Children()
    for _ in range(4):
        _generation(dirs, children)
    root, off = dirs
    assert len(_manifests(root / "layer2")) == 2 and len(_manifests(off / "layer2")) == 2
    assert _manifests(root / "layer2")[-1].startswith("sgaa-pg-20261010T000004Z")
    assert not list((root / "layer2").glob("*T000001Z*"))


def test_only_generations_the_tool_registered_are_ever_deleted(dirs):
    """A set made by hand with an ``auto`` in its label, the baseline and a foreign file all survive."""
    root, off = dirs
    for directory in (root / "layer2", off / "layer2"):
        _hand_made_set(directory, "sgaa-pg-20260901T000000Z-before-auto-migration")
        _hand_made_set(directory, "sgaa-pg-20261001T000000Z-cutover-baseline")
        _hand_made_set(directory, "sgaa-pg-20260902T000000Z-auto-handmade")  # looks exactly like a tool set
        (directory / "notes-from-the-operator.txt").write_text("keep")
    for directory in (root / "objects", off / "objects"):
        (directory / "20260901T000000Z-auto-handmade").mkdir(parents=True)
        (directory / "20260901T000000Z-auto-handmade" / "x").write_bytes(b"keep")
    children = _Children()
    for _ in range(5):
        _generation(dirs, children, objects=True)
    for directory in (root, off):
        layer2 = directory / "layer2"
        for kept in ("sgaa-pg-20260901T000000Z-before-auto-migration", "sgaa-pg-20261001T000000Z-cutover-baseline",
                     "sgaa-pg-20260902T000000Z-auto-handmade"):
            assert (layer2 / f"{kept}.manifest.json").exists(), kept
        assert (layer2 / "notes-from-the-operator.txt").exists()
        assert (directory / "objects" / "20260901T000000Z-auto-handmade" / "x").exists()
        generated = [n for n in _manifests(layer2) if "scheduled" in n]
        assert len(generated) == 2


def test_the_baseline_label_is_refused_outright(dirs):
    children = _Children()
    for label in ("cutover-baseline", "x-cutover-baseline-y"):
        with pytest.raises(ob.Refused) as caught:
            _generation(dirs, children, label=label)
        assert caught.value.code == "LABEL_INVALID"
    assert children.calls == []


def test_rotation_follows_creation_order_not_the_clock(dirs):
    """A clock that jumps backwards must not make the newest generation the oldest."""
    children = _Children()
    times = iter([datetime(2026, 10, 12, tzinfo=timezone.utc), datetime(2026, 10, 11, tzinfo=timezone.utc),
                  datetime(2026, 10, 10, tzinfo=timezone.utc)])
    for _ in range(3):
        _generation(dirs, children, objects=True, clock=lambda: next(times))
    root, _off = dirs
    # Three generations, two kept: the first created is the one removed, though its stamp is the latest.
    names = sorted(p.name for p in (root / "objects").iterdir())
    assert names == ["20261010T000000Z-auto-scheduled", "20261011T000000Z-auto-scheduled"]


@pytest.mark.parametrize("failing", ["DATABASE_BACKUP", "DATABASE_VERIFY", "OBJECT_BACKUP", "OBJECT_VERIFY"])
def test_a_failed_step_stops_the_run_and_nothing_is_rotated_or_copied(dirs, failing):
    root, off = dirs
    healthy = _Children()
    for _ in range(3):
        _generation(dirs, healthy, objects=True)
    before = (sorted(p.name for p in root.rglob("*")), sorted(p.name for p in off.rglob("*")))
    with pytest.raises(ob.Refused) as caught:
        _generation(dirs, _Children(fail_at=failing), objects=True)
    assert caught.value.code == f"STEP_FAILED_{failing}" and caught.value.detail.startswith("exit ")
    after = (sorted(p.name for p in root.rglob("*")), sorted(p.name for p in off.rglob("*")))
    # Nothing was deleted and nothing reached the off-platform copy (a failed step may leave its
    # own staging output in the primary directory; it is never "a generation").
    assert set(before[0]) <= set(after[0]) and before[1] == after[1]
    assert not (root / ob.LOCK_FILE).exists()  # the run lock is released on failure


def test_an_off_platform_copy_that_differs_is_refused_before_any_rotation(dirs, monkeypatch):
    healthy = _Children()
    _generation(dirs, healthy)
    _generation(dirs, healthy)
    root, off = dirs
    before = sorted(p.name for p in root.rglob("*"))
    original = ob._sha256
    calls = {"n": 0}

    def flaky(path):
        calls["n"] += 1
        return original(path) if calls["n"] % 2 else "0" * 64  # every copy compares unequal

    monkeypatch.setattr(ob, "_sha256", flaky)
    with pytest.raises(ob.Refused) as caught:
        _generation(dirs, healthy)
    assert caught.value.code == "OFF_PLATFORM_COPY_MISMATCH"
    assert set(before) <= {p.name for p in root.rglob("*")}  # nothing deleted from the primary


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"generations": 1}, "GENERATIONS_BELOW_MINIMUM"),
        ({"label": "Has Spaces"}, "LABEL_INVALID"),
        ({"label": "../x"}, "LABEL_INVALID"),
        ({"off_platform": None}, "OFF_PLATFORM_REQUIRED"),
    ],
)
def test_refusals_happen_before_any_child_runs(dirs, kwargs, code):
    children = _Children()
    with pytest.raises(ob.Refused) as caught:
        _generation(dirs, children, **kwargs)
    assert caught.value.code == code and children.calls == []


def test_paths_inside_the_repository_and_overlapping_directories_are_refused(tmp_path):
    inside = Path(ob.__file__).resolve().parents[1] / "ops-backup-should-not-exist"
    children = _Children()
    cases = [
        (inside, tmp_path / "o", "PATH_INSIDE_REPOSITORY"),
        (tmp_path / "same", tmp_path / "same", "OFF_PLATFORM_SAME_AS_PRIMARY"),
        (tmp_path / "p", tmp_path / "p" / "inner", "OFF_PLATFORM_SAME_AS_PRIMARY"),
        (tmp_path / "p" / "inner", tmp_path / "p", "OFF_PLATFORM_SAME_AS_PRIMARY"),
    ]
    for root, off, code in cases:
        with pytest.raises(ob.Refused) as caught:
            ob.run_generation(root, label="x", generations=2, objects=False, off_platform=off, runner=children)
        assert caught.value.code == code
    assert children.calls == [] and not inside.exists()


def test_a_second_run_in_the_same_directory_is_refused_while_one_is_in_progress(dirs):
    root, _off = dirs
    root.mkdir(parents=True)
    (root / ob.LOCK_FILE).write_text("")
    children = _Children()
    with pytest.raises(ob.Refused) as caught:
        _generation(dirs, children)
    assert caught.value.code == "RUN_IN_PROGRESS" and children.calls == []


def test_the_command_line_is_value_free_and_reports_refusals_by_code(tmp_path):
    out, err = io.StringIO(), io.StringIO()
    code = ob.main(["--root", str(tmp_path / "p"), "--off-platform", str(tmp_path / "o")],
                   out=out, err=err, runner=_Children())
    assert code == 0
    text = out.getvalue()
    assert str(tmp_path) not in text and json.loads(text)["result"] == "GENERATION_COMPLETE"
    err = io.StringIO()
    assert ob.main(["--root", str(tmp_path / "p"), "--off-platform", str(tmp_path / "o"), "--generations", "1"],
                   out=io.StringIO(), err=err, runner=_Children()) == 1
    assert "GENERATIONS_BELOW_MINIMUM" in err.getvalue()
    assert ob.main(["--root", str(tmp_path / "p")], out=io.StringIO(), err=io.StringIO()) == 2


def test_an_existing_off_platform_file_is_never_overwritten_and_the_generation_fails(dirs):
    children = _Children()
    root, off = dirs
    foreign = off / "layer2" / "sgaa-pg-20261010T000001Z-auto-scheduled.dump"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"a copy that is already there")
    with pytest.raises(ob.Refused) as caught:
        _generation(dirs, children)
    assert caught.value.code == "OFF_PLATFORM_FILE_EXISTS"
    assert foreign.read_bytes() == b"a copy that is already there"


def test_a_damaged_or_edited_registry_is_refused_not_treated_as_empty(dirs):
    """Treating it as empty would let the next write forget every older generation (never rotated)."""
    children = _Children()
    _generation(dirs, children)
    root, _off = dirs
    registry = root / ob.REGISTRY_FILE
    good = registry.read_text(encoding="ascii")
    for damaged in ("{not json", "[]", '{"database": [], "objects": "x"}', '{"database": ["../../etc"], "objects": []}',
                    '{"database": [], "objects": [], "extra": 1}'):
        registry.write_text(damaged, encoding="ascii")
        with pytest.raises(ob.Refused) as caught:
            _generation(dirs, children)
        assert caught.value.code == "REGISTRY_INVALID", damaged
        assert registry.read_text(encoding="ascii") == damaged  # never rewritten
    registry.write_text(good, encoding="ascii")
    calls_before = len(children.calls)
    _generation(dirs, children)  # and a healthy one works again
    assert len(children.calls) > calls_before


def test_a_lock_left_by_a_killed_run_goes_stale_but_a_fresh_one_still_blocks(dirs):
    import os
    import time

    root, _off = dirs
    root.mkdir(parents=True)
    lock = root / ob.LOCK_FILE
    lock.write_text("")
    with pytest.raises(ob.Refused) as caught:
        _generation(dirs, _Children())
    assert caught.value.code == "RUN_IN_PROGRESS"
    old = time.time() - ob.LOCK_STALE_SECONDS - 60
    os.utime(lock, (old, old))
    children = _Children()
    assert _generation(dirs, children)["result"] == "GENERATION_COMPLETE" and children.calls
    assert not lock.exists()  # released by the run that took it


# ---- verify_generation and the ledger record (R3 remediation, finding 4) -----------------------------


class _Report:
    def __init__(self, ok=True, result_code="OK", database=None, digest="9" * 64):
        self.ok, self.result_code, self.database, self.objects_digest = ok, result_code, database, digest


@pytest.fixture
def verifiable(dirs, monkeypatch):
    """One complete generation with objects; the Layer-2 and object verifiers scripted."""
    from app.storage import object_backup
    from tools import pg_backup

    calls = {"artifact": [], "objects": []}
    monkeypatch.setattr(pg_backup, "verify_artifact", lambda path, **k: calls["artifact"].append(path))
    report = {"value": _Report()}

    def verify_set(path, conn=None):
        calls["objects"].append(conn)
        return report["value"]

    monkeypatch.setattr(object_backup, "verify_set", verify_set)
    _generation(dirs, _Children(), objects=True)
    return dirs, calls, report


def test_the_newest_generation_is_reverified_from_disk_including_its_off_platform_copy(verifiable):
    (root, off), calls, _report = verifiable
    result = ob.verify_generation(root, off)
    assert result["database_set"].startswith("sgaa-pg-") and len(result["manifest_sha256"]) == 64
    assert result["object_set"] and result["object_set_digest"] == "9" * 64
    recorded = json.loads(Path(result["manifest_path"]).read_text())
    assert result["created_at"] == recorded["created_at"]
    # Both sources are reported exactly as the tools recorded them; the ledger judges them (A16).
    assert result["database_source"] == recorded["source"]
    object_manifest = next(root.glob("objects/*/MANIFEST.json"))
    assert result["object_source"] == json.loads(object_manifest.read_text())["source"] ==         {"database": None, "store_host": "fake-store"}
    assert len(calls["artifact"]) == 1 and calls["objects"] == [None]
    # the object set's own creation time, in the ledger's form (A19 R3 rereview R6)
    assert result["object_created_at"] == "2026-10-09T23:59:58Z"
    marker = object()
    ob.verify_generation(root, off, conn=marker)
    assert calls["objects"][-1] is marker  # with a connection the object set is compared with the live rows


def _drop_from_off_registry(off, kind):
    registry = json.loads((off / ob.REGISTRY_FILE).read_text(encoding="ascii"))
    registry[kind] = registry[kind][:-1]
    (off / ob.REGISTRY_FILE).write_text(json.dumps(registry), encoding="ascii")


@pytest.mark.parametrize("damage,code", [
    (lambda root, off: next((off / "layer2").glob("*.dump")).write_bytes(b"other"), "OFF_PLATFORM_COPY_MISMATCH"),
    (lambda root, off: next((off / "layer2").glob("*.dump")).unlink(), "OFF_PLATFORM_COPY_MISMATCH"),
    (lambda root, off: next((off / "objects").rglob("abcd")).write_bytes(b"other"), "OFF_PLATFORM_COPY_MISMATCH"),
    (lambda root, off: (off / ob.REGISTRY_FILE).write_text('{"database": [], "objects": []}'),
     "OFF_PLATFORM_COPY_MISSING"),
    (lambda root, off: _drop_from_off_registry(off, "database"), "OFF_PLATFORM_COPY_MISSING"),  # the set only
    (lambda root, off: _drop_from_off_registry(off, "objects"), "OFF_PLATFORM_COPY_MISSING"),   # the objects only
])
def test_a_missing_or_different_off_platform_copy_is_refused(verifiable, damage, code):
    (root, off), _calls, _report = verifiable
    damage(root, off)
    with pytest.raises(ob.Refused) as caught:
        ob.verify_generation(root, off)
    assert caught.value.code == code


def test_an_invalid_layer2_set_or_object_set_is_refused(verifiable, monkeypatch):
    from tools import pg_backup

    (root, off), _calls, report = verifiable
    report["value"] = _Report(ok=False, result_code="SET_INVALID")
    with pytest.raises(ob.Refused) as caught:
        ob.verify_generation(root, off)
    assert caught.value.code == "OBJECT_SET_INVALID"
    report["value"] = _Report(ok=False, database={"missing": 1, "extra": 0, "changed": 0})
    with pytest.raises(ob.Refused) as caught:
        ob.verify_generation(root, off, conn=object())
    assert caught.value.code == "OBJECT_SET_NOT_CURRENT"
    report["value"] = _Report()

    def broken(path, **kwargs):
        raise pg_backup.Refused("ARTIFACT_SHA_MISMATCH", "x")

    monkeypatch.setattr(pg_backup, "verify_artifact", broken)
    with pytest.raises(ob.Refused) as caught:
        ob.verify_generation(root, off)
    assert caught.value.code == "DATABASE_SET_INVALID"


@pytest.mark.parametrize("content", [{"set": "x", "source": {}}, {"set": "x", "created_at": "2026-10-10T00:00:01Z"}])
def test_a_layer2_manifest_without_its_creation_time_or_its_source_is_refused(verifiable, content):
    (root, off), _calls, _report = verifiable
    manifest = next((root / "layer2").glob("*.manifest.json"))
    manifest.write_text(json.dumps(content), encoding="utf-8")
    copy = off / "layer2" / manifest.name
    copy.write_bytes(manifest.read_bytes())
    with pytest.raises(ob.Refused) as caught:
        ob.verify_generation(root, off)
    assert caught.value.code == "DATABASE_SET_INVALID"


def test_no_generation_yet_is_refused(dirs):
    root, off = dirs
    with pytest.raises(ob.Refused) as caught:
        ob.verify_generation(root, off)
    assert caught.value.code == "NO_GENERATION"


# ---- the governed run: provenance established while the generation is taken (A17 finding 4) -----------------


class _Seen:
    """What a verified connection proves, scripted: one identity per observation."""

    def __init__(self, identities, project="p" * 64):
        self.identities = list(identities)
        self.project = project
        self.observations = 0

    def source(self):
        from tools import prod_source

        identity = self.identities[min(self.observations, len(self.identities) - 1)]
        self.observations += 1
        return prod_source.VerifiedSource(identity=identity, project_sha256="q" * 64, source={})

    def store_project_sha256(self):
        return self.project


class _Source:
    url = "postgresql://postgres.abcdefghijklmnopqrst@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
    child_url = url + "?sslmode=verify-full&sslrootcert=pinned"

    def connect(self):  # pragma: no cover - the scripted observer never connects
        raise AssertionError("no connection in the unit lane")


@pytest.fixture
def governed(tmp_path, monkeypatch):
    """A ledger that expects identity I and project P; the observer and the record scripted."""
    from tools import cutover_ledger

    state = {"seen": _Seen(["i" * 64]), "receipts": [], "refuse": [], "expected": {
        "database_identity_sha256": "i" * 64, "prod_project_sha256": "p" * 64}}
    monkeypatch.setattr(cutover_ledger, "backup_preconditions", lambda directory, kind: dict(state["expected"]))
    monkeypatch.setattr(cutover_ledger, "Observer", lambda **kwargs: state["seen"])

    def record(directory, receipt, root, off_platform, observer=None):
        if state["refuse"]:
            raise cutover_ledger.Refused(state["refuse"].pop(0))
        state["receipts"].append(receipt)
        return {"hash": "h" * 64, "manifest_sha256": receipt["manifest_sha256"],
                "object_set_digest": receipt["object_set_digest"] or "NONE"}

    monkeypatch.setattr(cutover_ledger, "record_generation", record)
    monkeypatch.setattr(ob.time, "sleep", lambda seconds: None)
    from app.storage import object_backup
    from tools import pg_backup

    monkeypatch.setattr(pg_backup, "verify_artifact", lambda path, **kwargs: None)
    monkeypatch.setattr(object_backup, "verify_set", lambda path, conn=None: _Report())
    return state


def _governed(tmp_path, children, **kwargs):
    options = dict(objects=True, runner=children, source=_Source(), clock=_clock, environ={})
    options.update(kwargs)
    return ob.run_governed(tmp_path / "ledger", tmp_path / "p", tmp_path / "o", **options)


def test_the_governed_run_hands_the_ledger_the_receipt_of_what_it_just_took_from_the_verified_source(
        tmp_path, governed):
    children = _Children(created_at="2026-10-10T00:00:01Z")
    result = _governed(tmp_path, children)
    assert result["ledger"]["recorded"] is True and result["ledger"]["kind"] == "GENERATION"
    assert result["ledger"]["head"] == "h" * 64
    # Every child connected through the verified address, never the operator's raw one.
    assert children.envs and all(env["DATABASE_URL"] == _Source.child_url for env in children.envs)
    [receipt] = governed["receipts"]
    manifest = next((tmp_path / "p" / "layer2").glob("*.manifest.json"))
    assert receipt["manifest_sha256"] == ob._sha256(manifest)
    assert receipt["dump_sha256"] == json.loads(manifest.read_text())["artifact"]["sha256"]
    assert receipt["object_set"] == result["object_set"] and receipt["kind"] == "GENERATION"
    assert receipt["source_identity_sha256"] == receipt["source_identity_after_sha256"] == "i" * 64
    assert receipt["store_project_sha256"] == "p" * 64 and governed["seen"].observations == 2
    assert receipt["generation_at"] == "2026-10-10T00:00:01Z"  # the snapshot's own time, judged by the ledger


@pytest.mark.parametrize("setup,code", [
    (lambda s: s.__setitem__("seen", _Seen(["x" * 64])), "SOURCE_NOT_THE_QUALIFIED_DATABASE"),
    (lambda s: s.__setitem__("seen", _Seen(["i" * 64], project="o" * 64)), "STORE_NOT_THE_PROD_PROJECT"),
])
def test_the_governed_run_refuses_before_any_step_when_the_source_is_not_production(tmp_path, governed, setup, code):
    setup(governed)
    children = _Children()
    with pytest.raises(ob.Refused) as caught:
        _governed(tmp_path, children)
    assert caught.value.code == code and children.calls == [] and governed["receipts"] == []


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGHOST", "PGSERVICE", "PGSERVICEFILE", "PGPORT", "PGSSLMODE"])
def test_the_governed_run_refuses_any_hidden_routing_input_before_any_step(tmp_path, governed, name):
    children = _Children()
    with pytest.raises(ob.Refused) as caught:
        _governed(tmp_path, children, environ={name: "x"})
    assert caught.value.code == "SOURCE_ENV_ROUTING" and children.calls == []


def test_a_source_that_changed_during_the_run_is_reported_to_the_ledger_as_observed(tmp_path, governed):
    governed["seen"] = _Seen(["i" * 64, "z" * 64])
    _governed(tmp_path, _Children())
    [receipt] = governed["receipts"]
    assert receipt["source_identity_after_sha256"] == "z" * 64  # the ledger refuses it (test_mp3_cutover_ledger)


def test_the_receipt_names_only_the_generation_this_run_created(tmp_path, governed, monkeypatch):
    real = ob.verify_generation
    monkeypatch.setattr(ob, "verify_generation", lambda root, off, conn=None: dict(real(root, off),
                                                                                    database_set="sgaa-pg-planted"))
    with pytest.raises(ob.Refused) as caught:
        _governed(tmp_path, _Children())
    assert caught.value.code == "GENERATION_NOT_THIS_RUNS" and governed["receipts"] == []


def test_a_busy_ledger_is_retried_and_a_refusal_fails_the_run_by_code(tmp_path, governed):
    governed["refuse"] = ["LEDGER_BUSY"]
    assert _governed(tmp_path, _Children())["ledger"]["recorded"] is True
    governed["refuse"] = ["OUT_OF_ORDER"]
    with pytest.raises(ob.Refused) as caught:
        _governed(tmp_path / "second", _Children())
    assert caught.value.code == "LEDGER_OUT_OF_ORDER"


def test_the_baseline_takes_its_own_directories_once_with_objects_and_is_never_rotated(tmp_path, governed):
    children = _Children()
    result = _governed(tmp_path, children, baseline=True)
    assert result["ledger"]["kind"] == "BASELINE" and "cutover-baseline" in result["database_set"]
    assert result["rotation"]["primary"]["deleted"] == 0
    with pytest.raises(ob.Refused) as caught:
        _governed(tmp_path, children, baseline=True)
    assert caught.value.code == "BASELINE_ROOT_NOT_EMPTY"
    with pytest.raises(ob.Refused) as caught:  # a scheduled generation never shares the baseline's root
        _governed(tmp_path, children)
    assert caught.value.code == "BASELINE_ROOT"
    with pytest.raises(ob.Refused) as caught:
        _governed(tmp_path / "other", children, baseline=True, objects=False)
    assert caught.value.code == "BASELINE_NEEDS_OBJECTS"


def test_the_command_line_takes_the_baseline_only_through_the_ledger_and_drills_as_its_own_command(tmp_path):
    err = io.StringIO()
    assert ob.main(["--root", str(tmp_path / "p"), "--off-platform", str(tmp_path / "o"), "--baseline"],
                   out=io.StringIO(), err=err, runner=_Children()) == 1
    assert "BASELINE_NEEDS_THE_LEDGER" in err.getvalue()
    assert ob.main(["drill", "--root", str(tmp_path / "p"), "--off-platform", str(tmp_path / "o")],
                   out=io.StringIO(), err=io.StringIO()) == 2  # the ledger and the generation are required


def test_the_drill_runs_in_its_own_terminal_and_only_for_a_recorded_generation(tmp_path, monkeypatch):
    from tools import cutover_ledger

    ledger_dir = tmp_path / "ledger"
    cutover_ledger.init(ledger_dir)
    for name, value, code in (("DATABASE_URL", "postgresql://x@h/db", "DRILL_SOURCE_URL_SET"),
                              ("PGHOSTADDR", "127.0.0.1", "SOURCE_ENV_ROUTING")):
        with pytest.raises(ob.Refused) as caught:
            ob.drill(ledger_dir, tmp_path / "p", tmp_path / "o", "a" * 64, environ={name: value})
        assert caught.value.code == code
    with pytest.raises(ob.Refused) as caught:
        ob.drill(ledger_dir, tmp_path / "p", tmp_path / "o", "a" * 64, environ={})
    assert caught.value.code == "GENERATION_NOT_RECORDED"


def test_an_object_set_without_a_readable_creation_time_is_refused(verifiable):
    """A19 R3 rereview R6: the re-opening judges the object set by its own creation time; none is no proof."""
    (root, off), _calls, _report = verifiable
    for manifest in (next(root.glob("objects/*/MANIFEST.json")), next(off.glob("objects/*/MANIFEST.json"))):
        manifest.write_text(json.dumps({"source": {"database": None, "store_host": "fake-store"},
                                        "created_at": "yesterday"}), encoding="ascii")
    with pytest.raises(ob.Refused) as caught:
        ob.verify_generation(root, off)
    assert caught.value.code == "OBJECT_SET_INVALID"
