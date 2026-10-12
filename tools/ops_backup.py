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

THE GOVERNED RUN (``--ledger-dir``; MP-3 SPEC amendments A15, A16, A17)
    The cutover counts only generations whose provenance was established WHILE they were
    taken, never from a manifest on disk (which anyone can copy and reseal).  With
    ``--ledger-dir`` the run itself is the evidence: before any step it refuses any libpq
    routing input and observes, through the verified connection (``tools/prod_source``:
    TLS verified against the pinned provider CA), that ``DATABASE_URL`` is the database the
    ledger qualified, and that ``SUPABASE_URL`` is the PROD project's store; the children
    connect through the same verified address; after the last step it observes the
    database again.  It then re-verifies from disk the generation THIS run created (its
    Layer-2 manifest and dump, its object set) and hands the ledger a receipt binding those
    digests to the identity it observed and the run's own time window
    (``cutover_ledger.record_generation``).  ``--baseline`` takes the cutover baseline (C7,
    GB1) the same way, into a root of its own, never rotated.

THE RESTORE DRILL (``drill``)
    Restores a generation the ledger recorded into a NEW, empty scratch PostgreSQL of the
    PROD major (``SGAA_RESTORE_TARGET_URL``; ``DATABASE_URL`` must be unset), verifies the
    restored database against the manifest (``pg_backup verify --restored``), verifies the
    object set (seal, every file, its digest as recorded) and that it holds the bytes of every
    restored ``storage_objects`` row, and hands the ledger a receipt
    (``cutover_ledger.record_restore``) naming the generation, its source and the target.
    C8 (the baseline) and C14 (a generation of the window) accept nothing else.

THE POSTURE THE PRODUCT SHOWS (``publish``; MP-3 SPEC A19)
    The Banco de dados page shows the protection posture from records it can read
    (``app.backup.pg_posture``).  A governed run publishes the ledger's ``backup`` and ``restore``
    entries -- the drills' included -- verbatim into the database it backed up, with the retention
    it observed; a run outside the ledger's window publishes its own self-hashed receipt.  A
    refused publication never undoes a generation (``posture`` in the output names the code).
    ``publish --ledger-dir`` re-publishes the ledger's records into the qualified PROD database
    (for a drill, which runs without ``DATABASE_URL``, and for records made before A19).

WHAT IT MAY DELETE
    Only sets listed in the registry file the tool itself writes
    (``ops_backup_registry.json`` in each directory).  A set made by hand, a
    foreign file and the cutover baseline are never candidates, whatever they
    are called; the baseline label is refused as a label, and a scheduled run
    never shares a root with the baseline.

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
# Run as ``python tools/ops_backup.py``: the repository root must be importable (``app``, ``tools``).
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

AUTO_PREFIX = "auto"
BASELINE_PREFIX = "cutover-baseline"
MIN_GENERATIONS = 2
REGISTRY_FILE = "ops_backup_registry.json"
LOCK_FILE = ".ops_backup.lock"
LABEL_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
DATABASE_SET = re.compile(r"sgaa-pg-\d{8}T\d{6}Z-(?:auto-[a-z0-9-]{1,40}|cutover-baseline)")
OBJECT_SET = re.compile(r"\d{8}T\d{6}Z-(?:auto-[a-z0-9-]{1,40}|cutover-baseline)")
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


def _run(command: list[str], env: dict | None = None) -> int:
    """One child tool; its output is discarded (each tool prints its own value-free report)."""
    result = subprocess.run(
        command, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=STEP_TIMEOUT_SECONDS, env=env,
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
        if any(BASELINE_PREFIX in name for name in names):
            raise Refused("BASELINE_ROOT", "the cutover baseline is never rotated")
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
    python: str | None = None, clock=None, baseline: bool = False, child_env: dict | None = None,
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
    registries = [_read_registry(directory) for directory in (root, off_platform)]  # a damaged one stops the run
    holds_baseline = any(BASELINE_PREFIX in name for registry in registries for names in registry.values()
                         for name in names)
    if baseline and any(names for registry in registries for names in registry.values()):
        raise Refused("BASELINE_ROOT_NOT_EMPTY", "the cutover baseline is taken once, into directories of its own")
    if not baseline and holds_baseline:
        raise Refused("BASELINE_ROOT", "scheduled generations never share the baseline's directories")
    if baseline and not objects:
        raise Refused("BASELINE_NEEDS_OBJECTS")
    stamp = (clock() if clock else datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    full_label = BASELINE_PREFIX if baseline else f"{AUTO_PREFIX}-{label}"
    layer2, object_root = root / "layer2", root / "objects"
    steps: list[dict] = []

    def step(name: str, command: list[str]) -> None:
        code = runner(command) if child_env is None else runner(command, env=child_env)
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
            object_root.mkdir(parents=True, exist_ok=True)  # the object tool refuses a missing parent
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
        if baseline:  # the baseline is kept until a later generation passed a restore validation (runbook §E)
            rotation_primary = rotation_off = {"kept": 1 + bool(object_name), "deleted": 0}
        else:
            rotation_primary = rotate(root, generations, layer2=layer2, objects=object_root)
            rotation_off = rotate(off_platform, generations, layer2=off_platform / "layer2",
                                  objects=off_platform / "objects")
    return {
        "result": "GENERATION_COMPLETE",
        "steps": steps,
        "files_copied_verified": copied,
        "rotation": {"primary": rotation_primary, "off_platform": rotation_off},
        "off_platform_encryption": "OPERATOR_RESPONSIBILITY",
        "database_set": base,
        "object_set": object_name,
    }


def verify_generation(root: Path, off_platform: Path, *, conn=None) -> dict:
    """The newest registered generation, re-verified from disk; value-free.

    The Layer-2 set (sidecar, size, SHA-256 and archive listing, through ``pg_backup``), the newest
    registered object set (offline; with ``conn``, also against the live ``storage_objects`` rows), and
    every file of both against its off-platform copy.  Refuses with a fixed code on any difference.
    """
    from tools import pg_backup

    root, off_platform = Path(root), Path(off_platform)
    registry, off_registry = _read_registry(root), _read_registry(off_platform)
    if not registry["database"]:
        raise Refused("NO_GENERATION")
    base = registry["database"][-1]
    if base not in off_registry["database"]:
        raise Refused("OFF_PLATFORM_COPY_MISSING")
    files = [root / "layer2" / (base + suffix) for suffix in (".manifest.json", ".dump", ".dump.sha256")]
    try:
        pg_backup.verify_artifact(str(files[0]))
    except pg_backup.BackupToolError:
        raise Refused("DATABASE_SET_INVALID") from None
    for item in files:
        copy = off_platform / "layer2" / item.name
        if not copy.is_file() or _sha256(item) != _sha256(copy):
            raise Refused("OFF_PLATFORM_COPY_MISMATCH")
    try:
        layer2 = json.loads(files[0].read_text(encoding="utf-8"))
        created_at, database_source = layer2["created_at"], layer2["source"]
        dump_sha256 = layer2["artifact"]["sha256"]  # verify_artifact proved the dump has it
    except (OSError, ValueError, KeyError, TypeError):
        raise Refused("DATABASE_SET_INVALID") from None
    # The sources are reported as recorded by the tools that read the database and the store; the
    # cutover ledger derives their identity (``app.hosting``) and refuses any but production's.
    result = {"database_set": base, "manifest_sha256": _sha256(files[0]), "manifest_path": str(files[0]),
              "dump_sha256": dump_sha256, "created_at": created_at, "database_source": database_source,
              "object_set": None, "object_set_digest": None, "object_source": None,
              "object_manifest_sha256": None, "object_set_path": None}
    if registry["objects"]:
        from app.storage import object_backup

        name = registry["objects"][-1]
        if name not in off_registry["objects"]:
            raise Refused("OFF_PLATFORM_COPY_MISSING")
        set_dir = root / "objects" / name
        report = object_backup.verify_set(str(set_dir), conn=conn)
        if not report.ok:
            raise Refused("OBJECT_SET_INVALID" if report.database is None or report.result_code != object_backup.RESULT_OK
                          else "OBJECT_SET_NOT_CURRENT")
        for item in sorted(p for p in set_dir.rglob("*") if p.is_file()):
            copy = off_platform / "objects" / name / item.relative_to(set_dir)
            if not copy.is_file() or _sha256(item) != _sha256(copy):
                raise Refused("OFF_PLATFORM_COPY_MISMATCH")
        manifest_file = set_dir / object_backup.MANIFEST_NAME
        try:
            object_source = json.loads(manifest_file.read_text(encoding="utf-8")).get("source")
        except (OSError, ValueError):
            raise Refused("OBJECT_SET_INVALID") from None
        result.update(object_set=name, object_set_digest=report.objects_digest, object_source=object_source,
                      object_manifest_sha256=_sha256(manifest_file), object_set_path=str(set_dir))
    return result


# ---------------------------------------------------------------------------
# the governed run and the restore drill (MP-3 SPEC A17)
# ---------------------------------------------------------------------------


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class VerifiedSource:
    """The PROD database as the governed run reaches it: verified TLS, no routing input (``prod_source``)."""

    def __init__(self, url: str) -> None:
        from tools import prod_source

        try:
            self.child_url = prod_source.verified_url(url)
        except prod_source.Refused as refusal:
            raise Refused(refusal.code) from None
        self.url = url

    def connect(self):
        from tools import prod_source

        return prod_source.connect(self.url)


def _ledger_call(call, *args, attempts: int = 5, **kwargs):
    from tools import cutover_ledger

    for attempt in range(attempts):
        try:
            return call(*args, **kwargs)
        except cutover_ledger.Refused as refusal:
            if refusal.code != "LEDGER_BUSY" or attempt == attempts - 1:
                raise Refused(f"LEDGER_{refusal.code}") from None
            time.sleep(2)
    raise Refused("LEDGER_LEDGER_BUSY")  # pragma: no cover - the loop returns or raises


def run_governed(ledger_dir: Path, root: Path, off_platform: Path, *, label: str = "scheduled",
                 generations: int = MIN_GENERATIONS, objects: bool, baseline: bool = False, runner=_run,
                 source=None, environ=None, clock=None, python: str | None = None, observer=None) -> dict:
    """Take a generation from the verified PROD source and record it with the provenance of THIS run.

    ``source`` and ``observer`` default to the verified PROD connection (``tools/prod_source``); the
    tests' loopback lanes replace them with a disposable local server.
    """
    from tools import cutover_ledger, prod_source

    env = dict(os.environ if environ is None else environ)
    kind = "BASELINE" if baseline else "GENERATION"
    now = clock or (lambda: datetime.now(timezone.utc))
    try:
        expected = _ledger_call(cutover_ledger.backup_preconditions, Path(ledger_dir), kind)
        prod_source.refuse_routing_environment(env)
    except prod_source.Refused as refusal:
        raise Refused(refusal.code) from None
    source = source or VerifiedSource(env.get("DATABASE_URL") or "")
    observer = observer or cutover_ledger.Observer(database_url=source.url, environ=env,
                                                   source_connector=lambda _url: source.connect())
    try:
        before = observer.source()
        store_project = observer.store_project_sha256() if objects else None
    except cutover_ledger.Refused as refusal:
        raise Refused(refusal.code) from None
    if before.identity != expected["database_identity_sha256"]:
        raise Refused("SOURCE_NOT_THE_QUALIFIED_DATABASE", "DATABASE_URL is not the database the ledger qualified")
    if objects and store_project != expected["prod_project_sha256"]:
        raise Refused("STORE_NOT_THE_PROD_PROJECT", "SUPABASE_URL is not the PROD project's store")
    child_env = dict(env, DATABASE_URL=source.child_url)
    started = now()
    result = run_generation(Path(root), label=label, generations=generations, objects=objects,
                            off_platform=Path(off_platform), runner=runner, python=python, clock=clock,
                            baseline=baseline, child_env=child_env)
    try:
        after = observer.source()
    except cutover_ledger.Refused as refusal:
        raise Refused(refusal.code) from None
    finished = now()
    on_disk = verify_generation(Path(root), Path(off_platform))
    if (on_disk["database_set"], on_disk["object_set"]) != (result["database_set"], result["object_set"]):
        raise Refused("GENERATION_NOT_THIS_RUNS")
    receipt = {
        "kind": kind, "manifest_sha256": on_disk["manifest_sha256"], "dump_sha256": on_disk["dump_sha256"],
        "object_set": on_disk["object_set"], "object_set_digest": on_disk["object_set_digest"],
        "object_manifest_sha256": on_disk["object_manifest_sha256"],
        "source_identity_sha256": before.identity, "source_identity_after_sha256": after.identity,
        "store_project_sha256": store_project, "generation_at": on_disk["created_at"],
        "run_started_at": _stamp(started), "run_finished_at": _stamp(finished),
    }
    entry = _ledger_call(cutover_ledger.record_generation, Path(ledger_dir), receipt, Path(root), Path(off_platform),
                         observer=observer)
    # The digests C8 (the baseline) and the restore drill name; value-free.
    result["ledger"] = {"recorded": True, "kind": kind, "head": entry["hash"],
                        "manifest_sha256": entry["manifest_sha256"], "object_set_digest": entry["object_set_digest"]}
    # The product's view of the posture (SPEC A19): the ledger's own entries, published verbatim into the
    # database this run backed up.  The generation is recorded whatever happens here; a refusal is reported.
    result["posture"] = _publish_quietly(lambda: publish_ledger(
        Path(ledger_dir), source.connect, annotations={entry["hash"]: _retention(Path(root), Path(off_platform),
                                                                                  generations)}))
    return result


# ---------------------------------------------------------------------------
# the posture the product shows (MP-3 SPEC A19)
# ---------------------------------------------------------------------------


def _retention(root: Path, off_platform: Path, generations: int) -> dict:
    """Value-free: the generations each directory keeps after this run's rotation, and the policy."""
    kept = {}
    for name, directory in (("primary", root), ("off_platform", off_platform)):
        registry = _read_registry(directory)
        kept[name] = {"database": len(registry["database"]), "objects": len(registry["objects"])}
    return {"generations_policy": generations, "kept": kept}


def _publish_quietly(call) -> dict:
    """Run a publication; its refusal never undoes the generation, it is reported with a fixed code."""
    from app.backup import pg_posture

    try:
        return dict(call(), result="PUBLISHED")
    except pg_posture.PostureError as error:
        return {"result": "NOT_PUBLISHED", "code": error.code}
    except Refused as refusal:
        return {"result": "NOT_PUBLISHED", "code": refusal.code}
    except Exception as error:  # a database refusal (the write barrier included) or an unreachable source
        return {"result": "NOT_PUBLISHED", "code": type(error).__name__.upper()}


def publish_ledger(ledger_dir: Path, connect, *, annotations: dict | None = None) -> dict:
    """Publish every ``backup`` and ``restore`` entry of the ledger (the drills' included) into the
    database ``connect()`` opens; entries published before are left as they are."""
    from app.backup import pg_posture
    from tools import cutover_ledger

    try:
        entries = cutover_ledger.read_ledger(Path(ledger_dir))
    except cutover_ledger.Refused as refusal:
        raise Refused(f"LEDGER_{refusal.code}") from None
    records = [entry for entry in entries if entry.get("type") in ("backup", "restore")]
    conn = connect()
    try:
        return pg_posture.publish(conn, records, annotations=annotations)
    finally:
        conn.close()


def publish(ledger_dir: Path, *, environ=None, source=None, observer=None) -> dict:
    """``ops_backup publish``: project the ledger's records into the qualified PROD database only.

    For the records made before A19 and for drills (which run without ``DATABASE_URL``).  The
    connection is the verified one; the database must be the one the ledger qualified.
    """
    from tools import cutover_ledger, prod_source

    env = dict(os.environ if environ is None else environ)
    try:
        prod_source.refuse_routing_environment(env)
        summary = cutover_ledger._summary(cutover_ledger.read_ledger(Path(ledger_dir)))
    except prod_source.Refused as refusal:
        raise Refused(refusal.code) from None
    except cutover_ledger.Refused as refusal:
        raise Refused(f"LEDGER_{refusal.code}") from None
    if summary["qualification"] is None:
        raise Refused("LEDGER_QUALIFICATION_REQUIRED")
    source = source or VerifiedSource(env.get("DATABASE_URL") or "")
    observer = observer or cutover_ledger.Observer(database_url=source.url, environ=env,
                                                   source_connector=lambda _url: source.connect())
    try:
        observed = observer.source()
    except cutover_ledger.Refused as refusal:
        raise Refused(refusal.code) from None
    if observed.identity != summary["qualification"]["database_identity_sha256"]:
        raise Refused("SOURCE_NOT_THE_QUALIFIED_DATABASE", "DATABASE_URL is not the database the ledger qualified")
    try:
        published = publish_ledger(Path(ledger_dir), source.connect)
    except Exception as error:
        from app.backup import pg_posture

        if isinstance(error, (Refused, pg_posture.PostureError)):
            raise Refused(error.code) from None
        raise Refused("PUBLISH_REFUSED", type(error).__name__) from None
    return dict(published, result="PUBLISHED")


def _publish_run(root: Path, off_platform: Path, generations: int, started: datetime, finished: datetime,
                 environ=None) -> dict:
    """A run outside the ledger's window publishes its own receipt into the database it backed up."""
    from app import hosting
    from app.backup import pg_posture
    from tools import pg_backup

    env = os.environ if environ is None else environ
    url = str(env.get(pg_backup.SOURCE_URL_ENV) or "").strip()
    if not url.startswith(("postgres://", "postgresql://")):
        raise pg_posture.PostureError("NO_DATABASE_URL")
    on_disk = verify_generation(root, off_platform)
    identity = hosting.source_identity_sha256(on_disk["database_source"])
    if identity is None:
        raise pg_posture.PostureError("DATABASE_IDENTITY_UNPROVEN")
    record = pg_posture.run_record(
        generation_at=on_disk["created_at"], manifest_sha256=on_disk["manifest_sha256"],
        dump_sha256=on_disk["dump_sha256"], source_identity_sha256=identity, object_set_name=on_disk["object_set"],
        object_set_digest=on_disk["object_set_digest"], object_manifest_sha256=on_disk["object_manifest_sha256"],
        run_seconds=int((finished - started).total_seconds()), at=_stamp(finished))

    conn = pg_backup.connect(url)
    try:
        return pg_posture.publish(conn, [record], annotations={
            record["hash"]: _retention(root, off_platform, generations)})
    finally:
        conn.close()


def _find_generation_files(root: Path, off_platform: Path, entry: dict) -> tuple[Path, Path]:
    """The Layer-2 manifest and the object set a recorded generation names, both copies byte-equal."""
    layer2 = root / "layer2"
    matches = [path for path in sorted(layer2.glob("*.manifest.json")) if _sha256(path) == entry["manifest_sha256"]]
    if len(matches) != 1:
        raise Refused("GENERATION_NOT_FOUND", "the recorded Layer-2 set is not in the primary directory")
    manifest = matches[0]
    base = manifest.name[: -len(".manifest.json")]
    for suffix in (".manifest.json", ".dump", ".dump.sha256"):
        item, copy = layer2 / (base + suffix), off_platform / "layer2" / (base + suffix)
        if not item.is_file() or not copy.is_file() or _sha256(item) != _sha256(copy):
            raise Refused("OFF_PLATFORM_COPY_MISMATCH")
    if entry["object_set_name"] == "NONE":
        raise Refused("GENERATION_WITHOUT_OBJECT_SET", "a restore validation needs the object set of the generation")
    set_dir = root / "objects" / entry["object_set_name"]
    for item in sorted(p for p in set_dir.rglob("*") if p.is_file()):
        copy = off_platform / "objects" / entry["object_set_name"] / item.relative_to(set_dir)
        if not copy.is_file() or _sha256(item) != _sha256(copy):
            raise Refused("OFF_PLATFORM_COPY_MISMATCH")
    return manifest, set_dir


def drill(ledger_dir: Path, root: Path, off_platform: Path, manifest_sha256: str, *, environ=None,
          target_url: str | None = None) -> dict:
    """Restore a recorded generation into a new scratch database, verify it all, record the receipt."""
    from app import hosting
    from app.storage import object_backup
    from tools import cutover_ledger, pg_backup, prod_source

    env = os.environ if environ is None else environ
    try:
        prod_source.refuse_routing_environment(env)
    except prod_source.Refused as refusal:
        raise Refused(refusal.code) from None
    if str(env.get(pg_backup.SOURCE_URL_ENV) or "").strip():
        raise Refused("DRILL_SOURCE_URL_SET", "run the drill in its own terminal, with DATABASE_URL unset")
    try:
        entries = cutover_ledger.read_ledger(Path(ledger_dir))
    except cutover_ledger.Refused as refusal:
        raise Refused(f"LEDGER_{refusal.code}") from None
    recorded = [e for e in entries if e["type"] == "backup" and e["manifest_sha256"] == manifest_sha256]
    if not recorded:
        raise Refused("GENERATION_NOT_RECORDED", "only a generation the ledger recorded is drilled")
    entry = recorded[-1]
    manifest, set_dir = _find_generation_files(Path(root), Path(off_platform), entry)
    try:
        loaded = pg_backup.verify_artifact(str(manifest))
        url = pg_backup.require_url(target_url if target_url is not None else env.get(pg_backup.TARGET_URL_ENV),
                                    pg_backup.TARGET_URL_ENV)
    except pg_backup.BackupToolError as exc:
        raise Refused(exc.code) from None
    if loaded.manifest["artifact"]["sha256"] != entry["dump_sha256"]:
        raise Refused("GENERATION_NOT_THE_RECORDED_ONE")
    report = object_backup.verify_set(str(set_dir))
    if not report.ok or report.objects_digest != entry["object_set_digest"] or \
            _sha256(set_dir / object_backup.MANIFEST_NAME) != entry["object_manifest_sha256"]:
        raise Refused("OBJECT_SET_NOT_THE_RECORDED_ONE")

    def target_identity():
        conn = pg_backup.connect(url)
        try:
            source = hosting.database_source(conn)
            major = int(conn.execute("SHOW server_version_num").fetchone()[0]) // 10000
            return source, major
        finally:
            conn.close()

    target, major = target_identity()
    if hosting.supabase_project_ref(target["host"], target["login_user"]) is not None:
        raise Refused("TARGET_NOT_SCRATCH", "the drill restores into scratch PostgreSQL, never a managed project")
    if hosting.source_identity_sha256(target) is None:
        raise Refused("TARGET_IDENTITY_UNPROVEN", "the scratch server must prove its cluster (system identifier)")
    try:
        state = pg_backup.restore(str(manifest), target_url=url, profile="plain")
    except pg_backup.BackupToolError as exc:
        raise Refused(f"RESTORE_{exc.code}") from None
    after, _major = target_identity()
    if hosting.source_identity_sha256(after) != hosting.source_identity_sha256(target):
        raise Refused("TARGET_CHANGED", "the database verified is not the one restored into")
    conn = pg_backup.connect(url)
    try:
        restored_rows = {(row["id"], row["sha256"]) for row in object_backup.current_rows(conn)}
    finally:
        conn.close()
    set_rows = {(row["id"], row["sha256"]) for row in json.loads(
        (set_dir / object_backup.MANIFEST_NAME).read_text(encoding="utf-8"))["objects"]}
    receipt = {
        "manifest_sha256": entry["manifest_sha256"], "dump_sha256": loaded.manifest["artifact"]["sha256"],
        "source_identity_sha256": entry["source_identity_sha256"], "object_set_digest": report.objects_digest,
        "object_set": "VERIFIED", "objects_verified": report.objects,
        "objects_cover_restored_rows": restored_rows <= set_rows,
        "restored": "VERIFIED", "tables_verified": len(state.tables),
        "target_identity_sha256": hosting.source_identity_sha256(target), "target_scratch": True,
        "target_major": major,
    }
    recorded_entry = _ledger_call(cutover_ledger.record_restore, Path(ledger_dir), receipt)
    return {"result": "DRILL_VERIFIED", "tables_verified": receipt["tables_verified"],
            "objects_verified": receipt["objects_verified"], "ledger": {"recorded": True, "head": recorded_entry["hash"]}}


def main(argv=None, *, out=None, err=None, runner=_run, source=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    argv = list(sys.argv[1:] if argv is None else argv)
    drilling = bool(argv) and argv[0] == "drill"
    publishing = bool(argv) and argv[0] == "publish"
    if publishing:
        parser = argparse.ArgumentParser(prog="ops_backup publish", allow_abbrev=False)
        parser.add_argument("--ledger-dir", required=True, help="the cutover ledger whose records are published")
        try:
            args = parser.parse_args(argv[1:])
        except SystemExit as exc:
            return 0 if exc.code == 0 else 2
        try:
            result = publish(Path(args.ledger_dir), source=source)
        except Refused as refusal:
            detail = f" ({refusal.detail})" if refusal.detail else ""
            err.write(f"ops-backup: refused: {refusal.code}{detail}\n")
            return 1
        json.dump(result, out, sort_keys=True)
        out.write("\n")
        return 0
    parser = argparse.ArgumentParser(prog="ops_backup drill" if drilling else "ops_backup", allow_abbrev=False)
    parser.add_argument("--root", required=True, help="primary backup directory (encrypted, outside the repository)")
    parser.add_argument("--off-platform", dest="off_platform", required=True,
                        help="a second, independently controlled directory (encrypted)")
    if drilling:
        parser.add_argument("--ledger-dir", required=True, help="the cutover ledger the generation is recorded in")
        parser.add_argument("--generation", required=True, help="the recorded generation's manifest SHA-256")
    else:
        parser.add_argument("--label", default="scheduled", help="[a-z0-9-], at most 32; never the baseline label")
        parser.add_argument("--generations", type=int, default=MIN_GENERATIONS)
        parser.add_argument("--objects", action="store_true", help="also take the object-byte set")
        parser.add_argument("--baseline", action="store_true",
                            help="the cutover baseline (C7, GB1): its own directories, objects, never rotated")
        parser.add_argument("--ledger-dir", default=None,
                            help="the cutover ledger: take the generation from the verified PROD source and "
                                 "record it with this run's provenance (MP-3)")
    try:
        args = parser.parse_args(argv[1:] if drilling else argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    try:
        if drilling:
            result = drill(Path(args.ledger_dir), Path(args.root), Path(args.off_platform), args.generation)
        elif args.ledger_dir:
            result = run_governed(Path(args.ledger_dir), Path(args.root), Path(args.off_platform), label=args.label,
                                  generations=args.generations, objects=args.objects or args.baseline,
                                  baseline=args.baseline, runner=runner, source=source)
        elif args.baseline:
            raise Refused("BASELINE_NEEDS_THE_LEDGER", "the cutover baseline is recorded by the governed run")
        else:
            started = datetime.now(timezone.utc)
            result = run_generation(
                Path(args.root), label=args.label, generations=args.generations, objects=args.objects,
                off_platform=Path(args.off_platform), runner=runner,
            )
            result["posture"] = _publish_quietly(lambda: _publish_run(
                Path(args.root), Path(args.off_platform), args.generations, started, datetime.now(timezone.utc)))
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
