# coding: utf-8
"""MP-3 slice 4: the scheduled operator backup sequencer (``tools/ops_backup.py``) -- no database.

The children (``pg_backup``, the object-backup commands) are scripted: the tool's
own contract is what is tested -- the order of steps, that nothing is rotated or
deleted unless every step passed, that the off-platform copy is compared byte
for byte, and that rotation can only ever delete a generation the tool itself
registered (never a hand-made set, a foreign file or the cutover baseline).
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools import ops_backup as ob

DUMP_SUFFIXES = (".dump", ".dump.sha256", ".manifest.json")


class _Children:
    """Scripted ``pg_backup`` / object-backup children that create the files the real ones do."""

    def __init__(self, fail_at: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_at = fail_at
        self.counter = 0

    def __call__(self, command: list[str]) -> int:
        self.calls.append(command)
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
            return 0
        if "pg_backup.py" in text and " verify " in f" {text} ":
            return 3 if self.fail_at == "DATABASE_VERIFY" else 0
        if "backup-objects" in text:
            if self.fail_at == "OBJECT_BACKUP":
                return 4
            destination = Path(command[command.index("--destination") + 1])
            (destination / "objects" / "ab").mkdir(parents=True)
            (destination / "MANIFEST.json").write_bytes(b"{}")
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
