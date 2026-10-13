# coding: utf-8
"""The sealed object-set archive builder (MP-3 A20) — a BACKGROUND capability.

WHY THIS IS ITS OWN MODULE
    Building an object set downloads every canonical object from the store synchronously
    (``app.storage.object_backup`` is a background tool: MP-1 invariant I3 forbids the web runtime
    from reaching it).  The scheduled pass runs in the scheduler service, which wires this builder
    into ``app.backup.hosted_backup.run_backup_pass``; the web function never loads it, and
    ``hosted_backup`` itself never names any background member.

WHAT IT PRODUCES
    ``build_objects_archive`` builds the set in scratch, seals it (``object_backup.backup``), names
    the archive after the installation identity and a random token, and returns the facts the
    delivery records.  A set that does not fully verify returns a fixed ``SET_*`` code and no
    archive: nothing is ever shipped unproven.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil

from app.backup.hosted_backup import OBJECTS_ARCHIVE_NAME, OBJECTS_ARCHIVE_PREFIX

OBJECTS_LABEL = "hosted"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_store():
    from flask import has_app_context

    from app.storage import request_documents

    if has_app_context():
        return request_documents.canonical_store()
    from app.storage.supabase_store import SupabaseObjectStore

    return SupabaseObjectStore.from_environment()


def build_objects_archive(conn, scratch: str, snapshot: dict, *, store=None) -> dict:
    """Build and seal the object set in scratch, archive it, and return its facts.

    ``{"archive", "report", "manifest_sha256", "set_name", "code"}``; ``archive`` is ``None`` and
    ``code`` names the fixed reason when the set could not be built — a set that does not fully
    verify is never shipped (MP-3 A20 §5).
    """
    from app.storage import object_backup
    from app.storage.object_store import CanonicalStoreError

    blank = {"archive": None, "report": None, "manifest_sha256": None, "set_name": None, "code": None}
    stamp = str(snapshot.get("generation_at") or "").replace("-", "").replace(":", "")
    if not re.fullmatch(r"\d{8}T\d{6}Z", stamp):
        return dict(blank, code="SET_TIMESTAMP_INVALID")
    token = secrets.token_hex(8)
    set_dir = os.path.join(scratch, f"objetos-{stamp}-{token}")
    try:
        store = store or _canonical_store()
    except CanonicalStoreError as exc:
        return dict(blank, code=f"SET_{exc.code}")
    except Exception as exc:
        return dict(blank, code=f"SET_{type(exc).__name__.upper()}")
    try:
        report = object_backup.backup(conn, store, set_dir, label=OBJECTS_LABEL)
    except object_backup.SetInvalid as exc:
        return dict(blank, code=f"SET_{getattr(exc, 'code', 'INVALID')}")
    except Exception as exc:
        return dict(blank, code=f"SET_{type(exc).__name__.upper()}")
    if report.result_code != object_backup.RESULT_OK:
        return dict(blank, code=f"SET_{report.result_code}")
    try:
        manifest_sha256 = _sha256(os.path.join(set_dir, object_backup.MANIFEST_NAME))
    except OSError:
        return dict(blank, code="SET_MANIFEST_UNREADABLE")
    identity = str(snapshot.get("source_identity_sha256") or "")
    archive_stem = os.path.join(scratch, f"{OBJECTS_ARCHIVE_PREFIX}{stamp}-{identity[:12]}-{token}")
    try:
        archive = shutil.make_archive(archive_stem, "zip", root_dir=set_dir)
    except OSError as exc:
        return dict(blank, code=f"SET_ARCHIVE_{type(exc).__name__.upper()}")
    if not OBJECTS_ARCHIVE_NAME.fullmatch(os.path.basename(archive)):
        return dict(blank, code="SET_ARCHIVE_NAME_INVALID")
    return {"archive": archive, "report": report, "manifest_sha256": manifest_sha256,
            "set_name": f"{stamp}-hosted", "code": None}


__all__ = ["OBJECTS_LABEL", "build_objects_archive"]
