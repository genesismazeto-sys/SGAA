# coding: utf-8
"""TEST ONLY: value-free evidence a clean MP-3 cutover would carry, state by state, and a scripted observer.

C12 is never typed: ``open`` writes it from the ledger's own observations.  What the ledger observes (the
qualified database, the platform's deployments, the write barrier, the opening authorization) or receives
as a governed tool's receipt (backups, restore drills, deployments, promotions) is produced here the way
the real tools produce it, so the ledger tests exercise the same entry points.  Shared by the ledger tests,
the backup-source tests and the real-application opening lane.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from app import hosting

H = {"a": "a" * 64, "b": "b" * 64, "c": "c" * 64, "d": "d" * 64, "e": "e" * 64, "f": "f" * 64,
     "g": "1" * 64, "h": "2" * 64, "i": "3" * 64, "j": "4" * 64, "k": "5" * 64,
     "m": "6" * 64}  # distinct 64-hex digests
COMMIT = "c" * 40
OTHER_COMMIT = "d" * 40
# The PROD project of these fixtures (a well-formed Supabase reference) and another one (DEV, say).
PROD_REF = "abcdefghijklmnopqrst"
OTHER_REF = "zyxwvutsrqponmlkjihg"
PROJECT = hashlib.sha256(PROD_REF.encode("ascii")).hexdigest()
# What the session pooler connection of the PROD project reads (app.hosting.database_source).
SOURCE = {"database": "postgres", "user": "postgres", "login_user": "postgres." + PROD_REF,
          "host": "aws-0-us-east-1.pooler.supabase.com", "port": "5432", "system_identifier": "7400000000000000001"}
OBJECT_SOURCE = {"database": SOURCE, "store_host": PROD_REF + ".supabase.co"}
IDENTITY = hosting.source_identity_sha256(SOURCE)
# The production platform project and the candidate the governed deploy recorded.
TEAM_ID = "team_" + "T" * 24
PROJECT_ID = "prj_" + "P" * 28
PLATFORM_PROJECT = hashlib.sha256(PROJECT_ID.encode("utf-8")).hexdigest()
CODE = "7" * 64
OTHER_CODE = "9" * 64
FILES = "8" * 64
DEPLOYMENT = "dpl_" + "A" * 24
LIFT = "dpl_" + "B" * 24
PUBLIC_HOST = H["m"]  # the public address proven at C10
BUCKETS = frozenset({("sgaa-documentos", "2026-10-01T00:00:00")})
BASELINE_MANIFEST = hashlib.sha256(b"baseline-manifest").hexdigest()
BASELINE_DUMP = hashlib.sha256(b"baseline-dump").hexdigest()
BASELINE_OBJECTS = hashlib.sha256(b"baseline-objects").hexdigest()


def manifest_digest(day: int) -> str:
    return hashlib.sha256(f"generation-{day}".encode()).hexdigest()


def dump_digest(manifest: str) -> str:
    return hashlib.sha256(f"dump-of-{manifest}".encode()).hexdigest()


def object_manifest_digest(digest: str) -> str:
    return hashlib.sha256(f"objects-manifest-{digest}".encode()).hexdigest()


# Evidence a clean cutover would carry, state by state (C12 is written by ``open`` only).
GOOD = {
    "C0": {"commit": COMMIT, "runbook_sha256": H["a"], "rehearsal_index_sha256": H["b"], "review_verdict": "PASS",
           "prod_project_sha256": PROJECT},
    "C1": {"pg_major": 17, "schema_current": True, "rows": 0, "objects": 0, "data_api_toggle_off": True,
           "data_api_override": "APPLIED", "data_api_probe": "NOT_SERVED", "data_api_project_sha256": PROJECT,
           "api_exposure_clean": True, "capacity_ok": True},
    "C2": {"database_bytes": 1000, "document_bytes": 2000, "census": {"GOOGLE_ROWS": 4, "LOCAL_ROWS": 2}},
    "C3": {"source_size": 4096, "source_sha256": H["c"], "wal_bytes": 0},
    "C4": {"source_sha256": H["c"], "prepared_sha256": H["d"], "integrity_ok": True, "fk_violations": 0,
           "schema_version": 16, "accepted_exceptions": [{"class": "TRASHED_LEGACY", "count": 2}],
           "accepted_by_user": True},
    "C5": {"prepared_sha256": H["d"], "converged_rows": 40, "unconverged": [{"class": "TRASHED_LEGACY", "count": 2}],
           "legacy_bytes_touched": 0},
    "C6": {"prepared_sha256": H["d"], "reference_digest": H["e"], "verdict": "CLEAN"},
    "C7": {"prepared_sha256": H["d"], "pathb_exit": 0, "commit_resolved_by_inspection": False,
           "commit_outcome": "COMMITTED"},
    "C8": {"reference_digest": H["e"], "census_equal": True, "baseline_manifest_sha256": BASELINE_MANIFEST,
           "object_set_digest": BASELINE_OBJECTS, "admin_bootstrap": "NOT_NEEDED"},
    "C9": {"commit": COMMIT, "deployment_id": DEPLOYMENT, "readiness": "READY", "scheduler_front": "DISABLED",
           "admission": "CLOSED"},
    "C10": {"smoke": "PASS", "write_set_ok": True, "admission": "CLOSED", "data_api_project_sha256": PROJECT,
            "public_host_sha256": PUBLIC_HOST},
    "C11": {"account_key_match": True, "mirror_passes": 2, "reconciliation_required": 0,
            "scheduler_front": "ENABLED", "admission": "CLOSED"},
    "C13": {"write_class": "REQUISICOES", "detected_at": "2026-11-01T10:30:00Z",
            "current_fingerprint_sha256": H["i"], "adjudicated_by_operator": True},
    # The last weekly generation with an object set in a 30-day window (``window``: days 7, 14, 21, 28).
    "C14": {"restore_validated_manifest_sha256": manifest_digest(28), "unresolved_reconciliation": 0},
}

# Gates in the order a cutover needs them (GP3 only when the bootstrap runs).
ALL_GATES = ["GP0", "GP1", "GP2", "GR0", "GR1", "GR2", "GR3", "GB1", "GD1", "GG1", "GG2", "GD2", "GO"]


def local_server_is_project(monkeypatch, ref: str) -> None:
    """TEST ONLY: the disposable local PostgreSQL stands for the project ``ref`` (it is no Supabase project).

    In-process, for the ledger's derivation (``app.hosting.supabase_project_ref``); the backup tools
    still record the raw facts of what they connected to.  Every other address keeps its real answer.
    """
    real = hosting.supabase_project_ref

    def mapped(host, login_user=None):
        return ref if str(host or "").strip().lower() in {"127.0.0.1", "localhost"} else real(host, login_user)

    monkeypatch.setattr(hosting, "supabase_project_ref", mapped)


# ---------------------------------------------------------------------------
# a scripted observer
# ---------------------------------------------------------------------------


def _fingerprints():
    from tools import pg_fingerprint as fp

    tables = {"alunos": {"rows": 1, "sha256": "d" * 64, "columns": ["id"], "row_hashes": {"1": ["h"]}}}
    changed = {"alunos": {"rows": 1, "sha256": "e" * 64, "columns": ["id"], "row_hashes": {"1": ["i"]}}}
    return ({"format": fp.FORMAT, "tables": tables, "fingerprint_sha256": fp._digest_of(tables)},
            {"format": fp.FORMAT, "tables": changed, "fingerprint_sha256": fp._digest_of(changed)})


REFERENCE, CHANGED = _fingerprints()


class FakeObserver:
    """Scripted eyes: public addresses, the verified PROD source, the platform, the barrier, the backups."""

    def __init__(self):
        self.admission_state = "closed"
        self.scheduler = "enabled"  # production after GD2; a rollback disables it first
        self.jobs = 0
        self.facts = dict(SOURCE)  # what the verified DATABASE_URL connection reads
        self.current = REFERENCE
        self.verdicts: list[dict] = []
        self.generation = generation(0)
        self.matches = True
        self.backup_calls: list[bool] = []
        self.host = PUBLIC_HOST
        self.tag = ""  # set to the reference entry's tag once the deployment is lifted with it
        self.code_seen = CODE  # what the public address announces
        # the store, for the qualification
        self.store_project = PROJECT
        self.api_buckets = BUCKETS
        self.db_buckets = BUCKETS
        # the platform
        self.project_id = PROJECT_ID
        self.platform: dict[str, dict] = {}  # id -> {"url", "state", "files", "admission", "code"}
        self.alias = None
        # the opening authorization rows and the barrier
        self.rows: list[dict] = []
        self.barrier = None  # the state a fresh session observes once applied
        self.lift_works = True
        self.applied_calls = 0

    # -- public addresses
    def admission(self, url=None):
        if url is None:
            return self.admission_state
        return self.platform_by_url(url)["admission"]

    def code(self, url=None):
        if url is None:
            return self.code_seen
        return self.platform_by_url(url)["code"]

    def opening_tag(self):
        return self.tag

    def host_sha256(self):
        return self.host

    def scheduler_front(self):
        return self.scheduler

    # -- the platform
    def platform_by_url(self, url):
        return next(d for d in self.platform.values() if d["url"] == url)

    def provider_project_sha256(self):
        return hashlib.sha256(self.project_id.encode("utf-8")).hexdigest()

    def provider_deployments(self):
        return [{"id": key, "url": value["url"], "state": value["state"]} for key, value in self.platform.items()]

    def alias_deployment(self):
        return self.alias

    def deployment_files_sha256(self, deployment_id):
        return self.platform[deployment_id]["files"]

    # -- the verified source
    def source(self):
        from tools import cutover_ledger as ledger
        from tools import prod_source

        project = hosting.source_project_sha256(self.facts)
        identity = hosting.source_identity_sha256(self.facts)
        if project is None:
            raise ledger.Refused("SOURCE_NO_TENANT")
        if identity is None:
            raise ledger.Refused("DATABASE_IDENTITY_UNPROVEN")
        return prod_source.VerifiedSource(identity=identity, project_sha256=project, source=dict(self.facts))

    def database_identity(self):
        return self.source().identity

    def store_project_sha256(self):
        return self.store_project

    def store_buckets(self):
        return self.api_buckets

    def database_buckets(self):
        return self.db_buckets

    def fingerprint(self):
        return self.current

    def classify(self, reference):
        if self.verdicts:
            return self.verdicts.pop(0)
        return {"identical": True, "derived_classes": [], "refusal": None, "current": reference}

    def external_trigger_jobs(self):
        return self.jobs

    def backup(self, root, off_platform, *, against_database):
        self.backup_calls.append(against_database)
        return dict(self.generation)

    def backup_matches(self, manifest_path, fingerprint):
        return self.matches

    # -- the authorization (a transaction: the row exists only if the ledger write succeeded)
    def opening_rows(self):
        return len(self.rows)

    def authorize(self, reference_sha256, code_sha256, entry, write, *, first):
        from tools import cutover_ledger as ledger

        if first and self.rows:
            raise ledger.Refused("OPENING_AUTHORIZATION_EXISTS")
        write()
        if not first:  # the new code replaces every other one of the reference (A19 R3 M2)
            for row in self.rows:
                if row["reference"] == reference_sha256 and row["code"] != code_sha256:
                    row["revoked"] = True
        self.rows.append({"reference": reference_sha256, "code": code_sha256, "revoked": False,
                          "entry": json.dumps(entry, sort_keys=True, separators=(",", ":"))})

    def supersede(self, reference_sha256, keep_code, write):
        write()
        revoked = 0
        for row in self.rows:
            if row["reference"] == reference_sha256 and row["code"] != keep_code and not row["revoked"]:
                row["revoked"], revoked = True, revoked + 1
        return revoked

    def authorization_valid(self, reference_sha256, code_sha256, project_sha256):
        identity = hosting.source_identity_sha256(self.facts)
        return any(not row["revoked"] and row["reference"] == reference_sha256 and row["code"] == code_sha256
                   and hosting.opening_entry_authorizes(row["entry"], reference=reference_sha256,
                                                        database_identity=identity, code=code_sha256,
                                                        project=project_sha256)
                   for row in self.rows)

    # -- the barrier
    def apply_barrier(self):
        self.applied_calls += 1
        for row in self.rows:
            row["revoked"] = True
        self.barrier = {"setting": True, "fresh_read_only": True, "write_refused": True, "older_sessions": 0,
                        "authorizations_in_force": 0}
        return {"barrier_at": "2026-11-01T08:00:00.000000Z", "terminated": 2}

    def barrier_state(self, barrier_at):
        if self.barrier is None:
            return {"setting": False, "fresh_read_only": False, "write_refused": False, "older_sessions": 0,
                    "authorizations_in_force": sum(not row["revoked"] for row in self.rows)}
        return dict(self.barrier)

    def lift_barrier(self, reference_sha256, code_sha256):
        if not self.lift_works:
            return False
        self.barrier = None
        for row in self.rows:
            if row["reference"] == reference_sha256 and code_sha256 and row["code"] == code_sha256:
                row["revoked"] = False
        return True

    def writable(self):
        return self.barrier is None


# ---------------------------------------------------------------------------
# receipts, as the governed tools produce them
# ---------------------------------------------------------------------------


def generation(day: int, *, objects: str | None = "20261101T000000Z-auto-weekly",
               object_digest: str = H["g"]) -> dict:
    """What ``ops_backup.verify_generation`` reports for a PROD generation (``observer.backup``)."""
    manifest = manifest_digest(day)
    return {"database_set": f"sgaa-pg-{day}", "manifest_sha256": manifest, "manifest_path": "unused",
            "dump_sha256": dump_digest(manifest), "created_at": None, "database_source": dict(SOURCE),
            "object_set": objects, "object_set_digest": object_digest if objects else None,
            "object_manifest_sha256": object_manifest_digest(object_digest) if objects else None,
            "object_source": dict(OBJECT_SOURCE, database=dict(SOURCE)) if objects else None}


def _stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def receipt_for(observer, *, kind="GENERATION", made=None, **overrides) -> dict:
    """The receipt a governed ``ops_backup`` run hands the ledger for ``observer.generation``."""
    from tools import cutover_ledger as ledger

    made = made or ledger._CLOCK()
    on_disk = observer.generation
    identity = hosting.source_identity_sha256(observer.facts)
    receipt = {
        "kind": kind, "manifest_sha256": on_disk["manifest_sha256"], "dump_sha256": on_disk["dump_sha256"],
        "object_set": on_disk["object_set"], "object_set_digest": on_disk["object_set_digest"],
        "object_manifest_sha256": on_disk["object_manifest_sha256"],
        "source_identity_sha256": identity, "source_identity_after_sha256": identity,
        "store_project_sha256": observer.store_project if on_disk["object_set"] else None,
        "generation_at": _stamp(made), "run_started_at": _stamp(made - timedelta(seconds=30)),
        "run_finished_at": _stamp(made + timedelta(seconds=30)),
    }
    receipt.update(overrides)
    return receipt


def record(directory, observer, *, kind="GENERATION", made=None, **overrides):
    from tools import cutover_ledger as ledger

    return ledger.record_generation(directory, receipt_for(observer, kind=kind, made=made, **overrides),
                                    directory.parent, directory.parent, observer=observer)


def drill_receipt(manifest_sha256: str, *, dump=None, objects=H["g"], **overrides) -> dict:
    """The receipt ``ops_backup drill`` hands the ledger after a verified restore into scratch."""
    receipt = {
        "manifest_sha256": manifest_sha256, "dump_sha256": dump or dump_digest(manifest_sha256),
        "source_identity_sha256": IDENTITY, "object_set_digest": objects, "object_set": "VERIFIED",
        "objects_verified": 3, "objects_cover_restored_rows": True, "restored": "VERIFIED", "tables_verified": 34,
        "target_identity_sha256": H["j"], "target_scratch": True, "target_major": 17,
    }
    receipt.update(overrides)
    return receipt


def deployment_receipt(deployment_id=DEPLOYMENT, *, admission="OPERATOR", opening_reference="NONE", code=CODE,
                       commit=COMMIT, forward_fix_ref="NONE", **overrides) -> dict:
    """The receipt ``deploy_audit deploy`` hands the ledger after the platform confirmed the upload."""
    receipt = {
        "deployment_id": deployment_id, "url_sha256": hashlib.sha256(deployment_id.encode()).hexdigest(),
        "vercel_project_sha256": PLATFORM_PROJECT, "commit": commit, "deploy_tree_sha256": H["h"],
        "code_sha256": code, "files_sha256": FILES, "admission": admission, "opening_reference": opening_reference,
        "forward_fix_ref": forward_fix_ref, "observed_admission": "CLOSED" if admission == "OPERATOR" else "OPEN",
        "aliased": False,
    }
    receipt.update(overrides)
    return receipt


def deploy(directory, observer, deployment_id=DEPLOYMENT, **receipt_overrides):
    """A governed deployment: on the platform (as the observer sees it) and recorded in the ledger."""
    from tools import cutover_ledger as ledger

    receipt = deployment_receipt(deployment_id, **receipt_overrides)
    entry = ledger.record_deployment(directory, receipt)
    observer.platform[deployment_id] = {
        "url": f"https://{deployment_id.lower()}.example.test", "state": "READY", "files": receipt["files_sha256"],
        "admission": "closed" if receipt["admission"] == "OPERATOR" else "open", "code": receipt["code_sha256"]}
    return entry


def promote(directory, observer, deployment_id=DEPLOYMENT, *, host=PUBLIC_HOST):
    from tools import cutover_ledger as ledger

    observer.alias = deployment_id
    observer.code_seen = observer.platform[deployment_id]["code"]
    return ledger.record_promotion(directory, {
        "deployment_id": deployment_id, "public_host_sha256": host, "alias_deployment_id": deployment_id,
        "files_sha256": observer.platform[deployment_id]["files"], "observed_code": observer.platform[deployment_id]["code"]})


def baseline(directory, observer):
    """C7 -> C8: the governed baseline and its restore drill, both recorded."""
    from tools import cutover_ledger as ledger

    saved = observer.generation
    observer.generation = dict(generation(-1, objects="20261020T000000Z-cutover-baseline",
                                          object_digest=BASELINE_OBJECTS),
                               manifest_sha256=BASELINE_MANIFEST, dump_sha256=BASELINE_DUMP)
    record(directory, observer, kind="BASELINE")
    ledger.record_restore(directory, drill_receipt(BASELINE_MANIFEST, dump=BASELINE_DUMP, objects=BASELINE_OBJECTS))
    observer.generation = saved


def drive(directory, upto, observer=None, overrides=None):
    """Advance through every state up to and including ``upto``, producing each receipt on the way."""
    from tools import cutover_ledger as ledger

    overrides = overrides or {}
    observer = observer or FakeObserver()
    for state in ledger.STATES[: ledger.STATES.index(upto) + 1]:
        if state == "C1":
            ledger.qualify(directory, observer=observer)
        if state == "C8":
            baseline(directory, observer)
        if state == "C9":
            deploy(directory, observer)
        if state == "C10":
            promote(directory, observer)
        if state == "C12":
            open_production(directory, observer)
            continue
        if state == "C13":
            set_clock(ledger._CLOCK() + timedelta(hours=1))  # a business write some time after the opening
        if state == "C14":
            window(directory, observer, days=30)
        evidence = dict(GOOD[state])
        evidence.update(overrides.get(state, {}))
        ledger.advance(directory, state, evidence)
    return observer


def reference_file(directory, name="reference.json"):
    return directory.parent / name


def take(directory, observer, name="reference.json"):
    from tools import cutover_ledger as ledger

    return ledger.take_reference(directory, reference_file(directory, name), directory.parent, directory.parent,
                                 cadence_hours=24, observer=observer)


def lift(directory, observer, taken, deployment_id=LIFT):
    """GO: the governed open deployment of the candidate, carrying the reference, promoted."""
    deploy(directory, observer, deployment_id, admission="OPEN", opening_reference=taken["hash"])
    promote(directory, observer, deployment_id)
    observer.admission_state = "open"
    observer.tag = hosting.opening_tag(taken["hash"])


def open_production(directory, observer):
    """C11 -> C12 the only way: a post-C11 generation, the reference while closed, the lift, then open."""
    from tools import cutover_ledger as ledger

    set_clock(ledger._CLOCK() + timedelta(minutes=1))  # the generation is made after C11
    record(directory, observer)
    taken = take(directory, observer)
    lift(directory, observer, taken)
    return ledger.open_admission(directory, observer=observer)


def window(directory, observer, days, *, every_hours=24, objects_every_days=7, skip=(), drill=True):
    """Let ``days`` pass after C13: one recorded generation every ``every_hours``, an object set taken by
    every ``objects_every_days``-th day's run, and the restore drill of the last generation with objects
    (C14 consumes it)."""
    from tools import cutover_ledger as ledger

    start = ledger._CLOCK()
    last = None
    for step in range(1, days * 24 // every_hours + 1):
        moment = start + timedelta(hours=step * every_hours)
        set_clock(moment)
        day = step * every_hours // 24
        if day in skip:
            continue
        with_objects = day % objects_every_days == 0
        observer.generation = generation(
            day, objects=f"day-{day}" if with_objects else None,
            object_digest=hashlib.sha256(f"day-{day}".encode()).hexdigest())
        record(directory, observer)
        if with_objects:
            last = observer.generation
    if last is not None and drill:
        ledger.record_restore(directory, drill_receipt(last["manifest_sha256"], objects=last["object_set_digest"]))
    set_clock(start + timedelta(days=days, minutes=1))


# ---------------------------------------------------------------------------
# the loopback lanes: a real database and real served applications, the store and the platform scripted
# ---------------------------------------------------------------------------


def local_connector(url):
    """TEST ONLY: connect to the disposable local server the way ``tools/prod_source`` connects to PROD
    (autocommit, no prepared statements); a loopback test server has no TLS to verify."""
    import psycopg

    return lambda _ignored: psycopg.connect(url, autocommit=True, prepare_threshold=None, connect_timeout=15)


class LocalSource:
    """TEST ONLY: the governed backup's source on a loopback server (the children connect to it as is)."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.child_url = url

    def connect(self):
        return local_connector(self.url)(self.url)


class Platform:
    """TEST ONLY: the production project's deployments as the platform would list them (served apps)."""

    def __init__(self) -> None:
        self.deployments: dict[str, dict] = {}
        self.alias = None
        self.project_id = PROJECT_ID


def _local_observer_class():
    from tools import cutover_ledger as ledger

    class LocalObserver(ledger.Observer):
        """The real Observer on a loopback server: the database, the barrier, the authorization and every
        address are real; the server stands for the PROD project (it has no tenant to prove it), the
        project's storage API and the platform are scripted."""

        def __init__(self, base_url=None, *, database_url, scheduler_url=None, platform=None, project=PROJECT):
            super().__init__(base_url, allow_insecure=True, database_url=database_url, scheduler_url=scheduler_url,
                             source_connector=local_connector(database_url))
            self.platform = platform if platform is not None else Platform()
            self.project = project  # the project this loopback server stands for

        def source(self):
            from tools import prod_source

            with self._connection() as conn:
                facts = hosting.database_source(conn)
            identity = hosting.source_identity_sha256(facts)
            if identity is None:
                raise ledger.Refused("DATABASE_IDENTITY_UNPROVEN")
            return prod_source.VerifiedSource(identity=identity, project_sha256=self.project, source=facts)

        def store_buckets(self):
            return BUCKETS

        def database_buckets(self):
            return BUCKETS

        def provider_project_sha256(self):
            return hashlib.sha256(self.platform.project_id.encode("utf-8")).hexdigest()

        def provider_deployments(self):
            return [{"id": key, "url": value["url"], "state": value["state"]}
                    for key, value in self.platform.deployments.items()]

        def alias_deployment(self):
            return self.platform.alias

        def deployment_files_sha256(self, deployment_id):
            return self.platform.deployments[deployment_id]["files"]

    return LocalObserver


def LocalObserver(*args, **kwargs):  # noqa: N802 - a class, built lazily (it subclasses the ledger's)
    return _local_observer_class()(*args, **kwargs)


def record_served(directory, platform, deployment_id, url, *, code, admission="OPERATOR", opening_reference="NONE",
                  commit=COMMIT):
    """A governed deployment of a served application: on the scripted platform and recorded in the ledger."""
    from tools import cutover_ledger as ledger

    receipt = deployment_receipt(deployment_id, admission=admission, opening_reference=opening_reference, code=code,
                                 commit=commit)
    entry = ledger.record_deployment(directory, receipt)
    platform.deployments[deployment_id] = {"url": url, "state": "READY", "files": receipt["files_sha256"]}
    return entry


def promote_served(directory, platform, deployment_id, *, code, host):
    from tools import cutover_ledger as ledger

    platform.alias = deployment_id
    return ledger.record_promotion(directory, {
        "deployment_id": deployment_id, "public_host_sha256": host, "alias_deployment_id": deployment_id,
        "files_sha256": platform.deployments[deployment_id]["files"], "observed_code": code})


def governed_local(directory, observer, root, *, baseline=False, **kwargs):
    """A real governed ``ops_backup`` run against the loopback server (its store from the environment)."""
    from tools import ops_backup

    return ops_backup.run_governed(directory, root, root.parent / (root.name + "-off"), objects=True,
                                   baseline=baseline, source=LocalSource(observer.database_url), observer=observer,
                                   **kwargs)


def drive_local_to_c11(directory, observer, *, tmp, scratch_url, code=CODE, host=PUBLIC_HOST,
                       deployment_url="https://dark.example.test"):
    """C0..C11 through the real ledger on a loopback server: the ledger's own qualification, a real governed
    baseline restore-drilled into ``scratch_url``, the dark deployment recorded and promoted.  The
    environment names the store (``SUPABASE_URL`` of the PROD project) the object-set child reads."""
    import os

    from tools import cutover_ledger as ledger
    from tools import ops_backup

    ledger.init(directory)
    for index, gate in enumerate(ALL_GATES):
        ledger.grant(directory, gate, f"user-msg-{index}")
    ledger.advance(directory, "C0", GOOD["C0"])
    ledger.qualify(directory, observer=observer)
    for state in ledger.STATES[1:8]:
        ledger.advance(directory, state, GOOD[state])
    governed_local(directory, observer, tmp / "baseline", baseline=True)
    baseline_entry = [e for e in ledger.read_ledger(directory) if e["type"] == "backup"][-1]
    drill_env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    drill_env["SGAA_RESTORE_TARGET_URL"] = scratch_url
    drilled = ops_backup.drill(directory, tmp / "baseline", tmp / "baseline-off", baseline_entry["manifest_sha256"],
                               environ=drill_env)
    assert drilled["result"] == "DRILL_VERIFIED"
    ledger.advance(directory, "C8", dict(GOOD["C8"], baseline_manifest_sha256=baseline_entry["manifest_sha256"],
                                         object_set_digest=baseline_entry["object_set_digest"]))
    record_served(directory, observer.platform, DEPLOYMENT, deployment_url, code=code)
    ledger.advance(directory, "C9", GOOD["C9"])
    promote_served(directory, observer.platform, DEPLOYMENT, code=code, host=host)
    ledger.advance(directory, "C10", dict(GOOD["C10"], public_host_sha256=host))
    ledger.advance(directory, "C11", GOOD["C11"])
    return baseline_entry


_CLOCK_STATE: dict = {}


def set_clock(moment):
    _CLOCK_STATE["now"] = moment


def install_clock(monkeypatch, start):
    """A scripted clock and sleep for the ledger (the state lives here so the helpers can move it)."""
    from tools import cutover_ledger as ledger

    state = {"now": start, "slept": []}
    _CLOCK_STATE.clear()
    _CLOCK_STATE.update(state)

    def sleep(seconds):
        _CLOCK_STATE["slept"].append(seconds)
        _CLOCK_STATE["now"] += timedelta(seconds=seconds)

    monkeypatch.setattr(ledger, "_CLOCK", lambda: _CLOCK_STATE["now"])
    monkeypatch.setattr(ledger, "_SLEEP", sleep)
    return _CLOCK_STATE


__all__ = ["ALL_GATES", "BASELINE_DUMP", "BASELINE_MANIFEST", "BASELINE_OBJECTS", "BUCKETS", "CHANGED", "CODE",
           "COMMIT", "DEPLOYMENT", "FILES", "FakeObserver", "GOOD", "H", "IDENTITY", "LIFT", "LocalObserver",
           "LocalSource", "OBJECT_SOURCE", "Platform", "drive_local_to_c11", "governed_local", "local_connector",
           "promote_served", "record_served",
           "OTHER_CODE", "OTHER_COMMIT", "OTHER_REF", "PLATFORM_PROJECT", "PROD_REF", "PROJECT", "PROJECT_ID",
           "PUBLIC_HOST", "REFERENCE", "SOURCE", "TEAM_ID", "baseline", "deploy", "deployment_receipt", "drill_receipt",
           "drive", "dump_digest", "generation", "install_clock", "lift", "local_server_is_project", "manifest_digest",
           "object_manifest_digest", "open_production", "promote", "receipt_for", "record", "reference_file",
           "set_clock", "take", "window"]
