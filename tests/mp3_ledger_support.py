# coding: utf-8
"""TEST ONLY: value-free evidence a clean MP-3 cutover would carry, state by state (C12 is never typed:
``open`` writes it from the ledger's own observations).  Shared by the ledger tests and the real-application
opening lane."""

from __future__ import annotations

import hashlib

H = {"a": "a" * 64, "b": "b" * 64, "c": "c" * 64, "d": "d" * 64, "e": "e" * 64, "f": "f" * 64,
     "g": "1" * 64, "h": "2" * 64, "i": "3" * 64, "j": "4" * 64, "k": "5" * 64,
     "m": "6" * 64}  # distinct 64-hex digests
COMMIT = "c" * 40
OTHER_COMMIT = "d" * 40


def manifest_digest(day: int) -> str:
    return hashlib.sha256(f"generation-{day}".encode()).hexdigest()


# Evidence a clean cutover would carry, state by state (C12 is written by ``open`` only).
GOOD = {
    "C0": {"commit": COMMIT, "runbook_sha256": H["a"], "rehearsal_index_sha256": H["b"], "review_verdict": "PASS",
           "prod_project_sha256": H["k"]},
    "C1": {"pg_major": 17, "schema_current": True, "rows": 0, "objects": 0, "data_api_toggle_off": True,
           "data_api_override": "APPLIED", "data_api_probe": "NOT_SERVED", "data_api_project_sha256": H["k"],
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
    "C8": {"reference_digest": H["e"], "census_equal": True, "baseline_manifest_sha256": H["f"],
           "object_set_digest": H["g"], "restore_drill": "OK", "verify_backup": "OK",
           "admin_bootstrap": "NOT_NEEDED"},
    "C9": {"commit": COMMIT, "readiness": "READY", "bundle_audit": "CLEAN", "deploy_verify": "IDENTICAL",
           "deploy_tree_sha256": H["h"], "scheduler_front": "DISABLED", "admission": "CLOSED"},
    "C10": {"smoke": "PASS", "write_set_ok": True, "admission": "CLOSED", "data_api_project_sha256": H["k"],
            "public_host_sha256": H["m"]},
    "C11": {"account_key_match": True, "mirror_passes": 2, "reconciliation_required": 0,
            "scheduler_front": "ENABLED", "admission": "CLOSED"},
    "C13": {"write_class": "REQUISICOES", "detected_at": "2026-11-01T10:30:00Z",
            "current_fingerprint_sha256": H["i"], "adjudicated_by_operator": True},
    "C14": {"restore_validated_manifest_sha256": manifest_digest(30), "restore_drill": "OK",
            "unresolved_reconciliation": 0, "object_set_verified": True},
}
# Gates in the order a cutover needs them (GP3 only when the bootstrap runs).
ALL_GATES = ["GP0", "GP1", "GP2", "GR0", "GR1", "GR2", "GR3", "GB1", "GD1", "GG1", "GG2", "GD2", "GO"]


__all__ = ["ALL_GATES", "COMMIT", "GOOD", "H", "OTHER_COMMIT", "manifest_digest"]
