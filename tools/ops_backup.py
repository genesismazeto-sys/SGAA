# coding: utf-8
"""Scheduled operator backup: Layer-2 database set, object set, rotation, off-platform copy.

WHY THIS EXISTS
    The Free plans give no provider backup and no point-in-time recovery, so
    the operator's own sets are the only recovery assets
    (``docs/PG_BACKUP_RESTORE_RUNBOOK.md`` section E).  This tool sequences the
    existing tools -- it adds no backup logic of its own -- so one command on
    the operator's machine produces a generation that is complete, verified,
    copied off-platform and rotated, or stops loudly before anything is deleted.

SEQUENCE (any failure stops the run; nothing is rotated unless every step passed)
    1. ``tools/pg_backup.py backup``  then ``verify``                (database)
    2. ``app.storage.cli backup-objects`` then ``verify-backup --database``
       (``--objects``; objects are personal data too)
    3. copy the new generation to the off-platform directory and compare every
       file's SHA-256 with the original
    4. rotate: keep the newest ``--generations`` (at least 2) generations THIS
       TOOL registered, in both places.

WHAT IT MAY DELETE
    Only sets listed in the registry file the tool itself writes
    (``ops_backup_registry.json`` in each directory).  A set made by hand, a
    foreign file and the cutover baseline are never candidates, whatever they
    are called; the baseline label is refused outright.

The off-platform directory must be storage the operator encrypts and controls
(the sets are personal data and the seal is an integrity check, not
authenticity); the tool cannot verify that and says so in its output.  Output
is value-free: counts, fixed codes, exit numbers.

Exit codes: 0 generation complete, 1 a step failed or was refused, 2 usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTO_PREFIX = "auto"
BASELINE_PREFIX = "cutover-baseline"
MIN_GENERATIONS = 2
REGISTRY_FILE = "ops_backup_registry.json"
LOCK_FILE = ".ops_backup.lock"
LABEL_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
DATABASE_SET = re.compile(r"sgaa-pg-\d{8}T\d{6}Z-auto-[a-z0-9-]{1,40}")
OBJECT_SET = re.compile(r"\d{8}T\d{6}Z-auto-[a-z0-9-]{1,40}")
STEP_TIMEOUT_SECONDS = 3 * 60 * 60
#: Longer than any run can last (four steps, each bounded by its timeout); a lock this old belongs to a
#: run that was killed.
LOCK_STALE_SECONDS = 4 * STEP_TIMEOUT_SECONDS + 60 * 60


class Refused(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _outside_repository(path: Path) -> bool:
    resolved, root = path.resolve(), REPO_ROOT.resolve()
    return not (resolved == root or root in resolved.parents)


def _nested(inner: Path, outer: Path) -> bool:
    inner, outer = inner.resolve(), outer.resolve()
    return inner == outer or outer in inner.parents


def _run(command: list[str]) -> int:
    """One child tool; its output is discarded (each tool prints its own value-free report)."""
    result = subprocess.run(
        command, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=STEP_TIMEOUT_SECONDS,
    )
    return result.returncode


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(source: Path, destination: Path) -> int:
    """Copy a file or a directory tree; every file is compared by SHA-256. Returns the file count."""
    files = [source] if source.is_file() else sorted(p for p in source.rglob("*") if p.is_file())
    copied = 0
    for item in files:
        target = destination / item.name if source.is_file() else destination / item.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise Refused("OFF_PLATFORM_FILE_EXISTS")
        shutil.copyfile(item, target)
        if _sha256(item) != _sha256(target):
            raise Refused("OFF_PLATFORM_COPY_MISMATCH")
        copied += 1
    return copied


# ---------------------------------------------------------------------------
# the registry: the only sets rotation may delete
# ---------------------------------------------------------------------------


def _read_registry(directory: Path) -> dict:
    """The registry, or empty when there is none yet; a damaged one is refused, never rewritten."""
    path = directory / REGISTRY_FILE
    if not path.exists():
        return {"database": [], "objects": []}
    try:
        data = json.loads(path.read_text(encoding="ascii"))
        registry = {"database": data["database"], "objects": data["objects"]}
        valid = (
            isinstance(data, dict) and set(data) == {"database", "objects"}
            and all(isinstance(n, str) and DATABASE_SET.fullmatch(n) for n in registry["database"])
            and all(isinstance(n, str) and OBJECT_SET.fullmatch(n) for n in registry["objects"])
        )
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise Refused("REGISTRY_INVALID", "the generation registry is unreadable or edited; repair or remove it")
    return registry


def _write_registry(directory: Path, registry: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / (REGISTRY_FILE + ".tmp")
    temporary.write_text(json.dumps(registry, sort_keys=True), encoding="ascii")
    os.replace(temporary, directory / REGISTRY_FILE)


def _register(directory: Path, kind: str, name: str) -> None:
    registry = _read_registry(directory)
    if name not in registry[kind]:
        registry[kind].append(name)
    _write_registry(directory, registry)


def _delete_database_set(directory: Path, base: str) -> None:
    # The manifest goes first: a set without its manifest is, by the tool's own contract, not a backup.
    for suffix in (".manifest.json", ".dump.sha256", ".dump"):
        candidate = directory / (base + suffix)
        if candidate.is_file() and not candidate.is_symlink():
            candidate.unlink()


def rotate(directory: Path, generations: int, *, layer2: Path, objects: Path) -> dict:
    """Delete the oldest REGISTERED generations beyond ``generations``; returns counts."""
    registry = _read_registry(directory)
    deleted = 0
    for kind, location in (("database", layer2), ("objects", objects)):
        names = registry[kind]  # registration order = creation order, whatever the clock says
        excess = names[:-generations] if len(names) > generations else []
        for name in excess:
            if kind == "database":
                _delete_database_set(location, name)
            else:
                target = location / name
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
            deleted += 1
        registry[kind] = names[len(excess):]
    _write_registry(directory, registry)
    return {"kept": len(registry["database"]) + len(registry["objects"]), "deleted": deleted}


class _RunLock:
    """One run at a time per primary directory."""

    def __init__(self, directory: Path) -> None:
        self._path = directory / LOCK_FILE

    def __enter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (1, 2):
            try:
                descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    stale = time.time() - self._path.stat().st_mtime > LOCK_STALE_SECONDS
                except OSError:
                    stale = False
                if attempt == 1 and stale:
                    # A run killed hard leaves its lock behind; no run lasts this long.
                    try:
                        self._path.unlink()
                    except OSError:
                        pass
                    continue
                raise Refused("RUN_IN_PROGRESS") from None
            os.close(descriptor)
            return self
        raise Refused("RUN_IN_PROGRESS")

    def __exit__(self, *exc):
        try:
            self._path.unlink()
        except OSError:
            pass


def run_generation(
    root: Path, *, label: str, generations: int, objects: bool, off_platform: Path | None, runner=_run,
    python: str | None = None, clock=None,
) -> dict:
    python = python or sys.executable
    if generations < MIN_GENERATIONS:
        raise Refused("GENERATIONS_BELOW_MINIMUM")
    if not LABEL_PATTERN.fullmatch(label) or BASELINE_PREFIX in label:
        raise Refused("LABEL_INVALID")
    if off_platform is None:
        raise Refused("OFF_PLATFORM_REQUIRED")
    if not _outside_repository(root) or not _outside_repository(off_platform):
        raise Refused("PATH_INSIDE_REPOSITORY")
    if _nested(root, off_platform) or _nested(off_platform, root):
        raise Refused("OFF_PLATFORM_SAME_AS_PRIMARY")
    for directory in (root, off_platform):
        _read_registry(directory)  # a damaged registry stops the run before any step takes a backup
    stamp = (clock() if clock else datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    full_label = f"{AUTO_PREFIX}-{label}"
    layer2, object_root = root / "layer2", root / "objects"
    steps: list[dict] = []

    def step(name: str, command: list[str]) -> None:
        code = runner(command)
        steps.append({"step": name, "exit": code})
        if code != 0:
            raise Refused(f"STEP_FAILED_{name}", f"exit {code}")

    with _RunLock(root):
        layer2.mkdir(parents=True, exist_ok=True)
        before = set(layer2.glob("*.manifest.json"))
        step("DATABASE_BACKUP", [python, str(REPO_ROOT / "tools" / "pg_backup.py"), "backup",
                                 "--output-dir", str(layer2), "--label", full_label])
        created = sorted(set(layer2.glob("*.manifest.json")) - before)
        if len(created) != 1:
            raise Refused("DATABASE_SET_NOT_FOUND")
        manifest = created[0]
        base = manifest.name[: -len(".manifest.json")]
        if not DATABASE_SET.fullmatch(base):
            raise Refused("DATABASE_SET_NOT_FOUND")
        step("DATABASE_VERIFY", [python, str(REPO_ROOT / "tools" / "pg_backup.py"), "verify",
                                 "--manifest", str(manifest)])
        to_copy: list[tuple[Path, Path]] = [(manifest, off_platform / "layer2")]
        to_copy += [(manifest.with_name(base + s), off_platform / "layer2") for s in (".dump", ".dump.sha256")]
        object_name = None
        if objects:
            object_name = f"{stamp}-{full_label}"
            if not OBJECT_SET.fullmatch(object_name):
                raise Refused("LABEL_INVALID")
            object_set = object_root / object_name
            if object_set.exists():
                raise Refused("OBJECT_SET_EXISTS")
            step("OBJECT_BACKUP", [python, "-m", "app.storage.cli", "backup-objects", "--destination",
                                   str(object_set), "--label", full_label])
            step("OBJECT_VERIFY", [python, "-m", "app.storage.cli", "verify-backup", "--set", str(object_set),
                                   "--database"])
            to_copy.append((object_set, off_platform / "objects" / object_name))
        copied = sum(_copy_verified(source, destination) for source, destination in to_copy)
        # Registered only after everything above passed: a set that failed any step is never a generation
        # (and so never a rotation candidate or a reason to delete an older, good one).
        for directory in (root, off_platform):
            _register(directory, "database", base)
            if object_name:
                _register(directory, "objects", object_name)
        rotation_primary = rotate(root, generations, layer2=layer2, objects=object_root)
        rotation_off = rotate(off_platform, generations, layer2=off_platform / "layer2",
                              objects=off_platform / "objects")
    return {
        "result": "GENERATION_COMPLETE",
        "steps": steps,
        "files_copied_verified": copied,
        "rotation": {"primary": rotation_primary, "off_platform": rotation_off},
        "off_platform_encryption": "OPERATOR_RESPONSIBILITY",
    }


def main(argv=None, *, out=None, err=None, runner=_run) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="ops_backup", allow_abbrev=False)
    parser.add_argument("--root", required=True, help="primary backup directory (encrypted, outside the repository)")
    parser.add_argument("--off-platform", dest="off_platform", required=True,
                        help="a second, independently controlled directory (encrypted)")
    parser.add_argument("--label", default="scheduled", help="[a-z0-9-], at most 32; never the baseline label")
    parser.add_argument("--generations", type=int, default=MIN_GENERATIONS)
    parser.add_argument("--objects", action="store_true", help="also take the object-byte set")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    try:
        result = run_generation(
            Path(args.root), label=args.label, generations=args.generations, objects=args.objects,
            off_platform=Path(args.off_platform), runner=runner,
        )
    except Refused as refusal:
        detail = f" ({refusal.detail})" if refusal.detail else ""
        err.write(f"ops-backup: refused: {refusal.code}{detail}\n")
        return 1
    except (subprocess.SubprocessError, OSError):
        err.write("ops-backup: refused: STEP_UNAVAILABLE\n")
        return 1
    json.dump(result, out, sort_keys=True)
    out.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
