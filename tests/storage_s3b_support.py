"""Shared STORAGE S3-B (admin ARQUIVOS on canonical storage) RED fixtures -- TEST ONLY.

S3-B switches NEW / REPLACED admin ARQUIVOS documents to canonical Supabase
Storage, reusing the published S3-A direct-upload machinery.  Nothing here is
production code: these are the contract constants the S3-B RED suites encode
(SQLite: ``tests/test_storage_s3b_arquivos.py``; real PostgreSQL:
``tests/test_storage_s3b_real_pg.py``), the strengthened Google tripwire and
the engine-neutral seeders (``?`` placeholders work on SQLite and through the
PostgreSQL adapter).

APPLICATION CONTRACT ENCODED BY THE RED (supervisor-adjudicated S3-B)
    * the SAME routes as S3-A, dispatched on ``purpose``:
        ``POST /storage/upload-intents``                 purpose ``admin_arquivo``
        ``POST /storage/upload-intents/<id>/finalize``   the intent's own purpose
      (no admin-specific upload-intent route; no route-inventory delta);
    * ``GET /admin/arquivos`` (and ``?edit_arquivo=<id>``) renders a
      server-issued, session-bound ``arquivos_submission_id`` (128-bit hex) in
      its OWN session namespace (never the comprovantes one);
    * operation identity ``<submission_id>:<upload_slot_id>`` (opaque 128-bit
      slot; never an index or a filename); the consumed intent's
      ``operation_id`` becomes the business ``operation_key`` -- the legacy
      hidden form ``operation_key`` is NOT authoritative and is not rendered
      by the direct-upload form (a posted value is ignored);
    * issue payload: ``purpose``, ``submission_id``, ``upload_slot_id``,
      ``filename``, ``mime_type``, ``size_bytes``, ``sha256`` and, for a
      replacement only, ``admin_arquivo_id`` (create target = NULL);
    * the business POSTs (``/admin/arquivos/adicionar``,
      ``/admin/arquivos/<id>/editar``) carry the metadata fields plus
      ``arquivos_submission_id`` and exactly ONE ``arquivos_intent_ids`` value
      for a new file -- never file bytes (any multipart file part is refused
      before a business write);
    * a replacement is bound at intent issue to the content custody the row
      had then (canonical: ``storage_object_id``; Google: provider +
      ``remote_file_id``; local: provider + ``filename``); attach refuses a
      stale custody without mutating anything;
    * canonical reads: 302 to a 60-second signed private URL (``no-store``,
      ``no-referrer``); inline for admin visualizar / aluno ver, named for
      aluno download;
    * canonical delete: retire the object, delete the row -- refused only
      while a target ``admin_arquivo`` intent is LIVE (issued / verified and
      unexpired); rejected / expired / consumed intents and issued / verified
      intents past ``expires_at`` never block (no scheduler or sweeper needed);
    * the browser form (``admin-arquivo-form``) is ``data-direct-upload`` with
      ``data-direct-upload-purpose="admin_arquivo"``,
      ``data-direct-upload-single``,
      ``data-direct-upload-submission-field="arquivos_submission_id"``,
      ``data-direct-upload-intent-field="arquivos_intent_ids"`` and, on the
      edit render only, ``data-admin-arquivo-id="<id>"``.
"""

from __future__ import annotations

import os
import struct
import zlib

from tests.storage_s3a_support import (
    BUCKET,
    PDF,
    INTENT_TTL_SECONDS,
    GoogleTouched,
    arm_google_tripwires,
    sha256,
)

# ---------------------------------------------------------------------------
# contract constants
# ---------------------------------------------------------------------------

PURPOSE = "admin_arquivo"
TARGET_FIELD = "admin_arquivo_id"
ARQUIVOS_SUBMISSION_FIELD = "arquivos_submission_id"
ARQUIVOS_INTENT_IDS_FIELD = "arquivos_intent_ids"
LEGACY_ARQUIVO_FILE_FIELD = "arquivo"
ARQUIVO_KEY_RE = r"arquivos/\d{4}/\d{2}/[0-9a-f]{32}"
ADMIN_PAGE = "/admin/arquivos"
CREATE_URL = "/admin/arquivos/adicionar"
EDIT_URL = "/admin/arquivos/{id}/editar"
VIEW_URL = "/admin/arquivos/{id}/visualizar"
DELETE_URL = "/admin/arquivos/{id}/deletar"
STUDENT_VIEW_URL = "/aluno/arquivos/ver/{id}"
STUDENT_DOWNLOAD_URL = "/aluno/arquivos/download/{id}"

FORM_PURPOSE_ATTR = "data-direct-upload-purpose"
FORM_SINGLE_ATTR = "data-direct-upload-single"
FORM_SUBMISSION_FIELD_ATTR = "data-direct-upload-submission-field"
FORM_INTENT_FIELD_ATTR = "data-direct-upload-intent-field"
FORM_TARGET_ATTR = "data-admin-arquivo-id"

#: Opaque 128-bit slots for ARQUIVOS operations (never positional).
ARQUIVO_SLOTS = (
    "a1b2c3d4e5f60718293a4b5c6d7e8f90", "0a9b8c7d6e5f40312213243546576879",
    "f0e1d2c3b4a5968778695a4b3c2d1e0f", "3c5e7a9b1d2f4e6a8c0b2d4f6a8e0c1b",
)

#: The legacy Google helpers S3-B must RETAIN (unrouted for new work, kept for S5).
LEGACY_GOOGLE_HELPERS = (
    "resolve_arquivo_storage", "_ensure_arquivos_root", "_upload_google_arquivo",
    "_reserve_replacement_operation", "_promote_replacement", "retry_arquivo_cleanup",
    "_cleanup_locator", "_delete_locatorless_google_row",
)

#: Legacy states a canonical replacement must REFUSE (no auto-heal; S5 / S6
#: remediation).  Each entry: (label, provider, row overrides).  Every one is
#: a legal v15 legacy row.
NON_STEADY_LEGACY_STATES = (
    ("google-pending", "google", dict(storage_status="pending", remote_file_id=None, remote_parent_id=None)),
    ("google-failed", "google", dict(storage_status="failed", failure_code="STORAGE_ERROR",
                                    remote_file_id=None, remote_parent_id=None)),
    ("google-reconciliation-required", "google", dict(storage_status="reconciliation_required",
                                                      failure_code="ACTIVATION_DB_PENDING")),
    ("google-replacement-cleanup-pending", "google", dict(
        storage_status="replacement_cleanup_pending", prior_provider="google", prior_locator="drv-older-1",
        cleanup_started_at="2026-10-08 11:00:00")),
    ("google-deletion-pending", "google", dict(storage_status="deletion_pending",
                                               cleanup_started_at="2026-10-08 11:00:00")),
    ("google-active-replacement-reserved", "google", dict(
        failure_code="REPLACEMENT_UPLOAD_PENDING", replacement_mime_type="application/pdf",
        replacement_size_bytes=10, replacement_sha256="e" * 64)),
    ("local-replacement-reserved", "local_legacy", dict(
        operation_key="legacy-reserved-op", failure_code="REPLACEMENT_UPLOAD_PENDING",
        replacement_mime_type="application/pdf", replacement_size_bytes=10, replacement_sha256="e" * 64)),
    ("local-deletion-pending", "local_legacy", dict(storage_status="deletion_pending",
                                                    cleanup_started_at="2026-10-08 11:00:00")),
)

#: The delete gate (supervisor adjudication): a target ``admin_arquivo``
#: intent blocks a canonical delete only while it is LIVE -- state issued /
#: verified AND ``expires_at`` not yet passed.  Live replacement work may still
#: upload / attach, so its tracking must not vanish through the FK cascade.
LIVE_TARGET_INTENT_STATES = ("issued", "verified")
#: Non-live target intents never block a delete: terminal states, and live
#: states whose window already closed (no scheduler / sweeper is required;
#: terminal rows are not cleanup ownership -- orphan bytes are S5 / S6 scope).
NON_LIVE_TARGET_INTENT_CASES = ("rejected", "expired", "issued-past-expiry", "verified-past-expiry")


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_with_dimensions(width: int, height: int) -> bytes:
    """A PNG whose header declares ``width`` x ``height`` (image-limit vectors)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


# ---------------------------------------------------------------------------
# Google tripwires -- the ACTUAL ARQUIVOS bindings
# ---------------------------------------------------------------------------


class ArquivoTripwireStorage:
    """Stands in for ``arquivo_storage``: any use is a Drive dependency."""

    provider = "google"

    def __init__(self, calls: list) -> None:
        self._calls = calls

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def touched(*_args, **_kwargs):
            self._calls.append(f"arquivo_storage.{name}")
            raise GoogleTouched(f"arquivo_storage.{name}")

        return touched


def arm_arquivos_google_tripwires(monkeypatch, app) -> list:
    """S3-A tripwires PLUS the ARQUIVOS bindings S3-A does not reach.

    ``app.arquivos`` binds ``resolve_google_managed_storage`` by from-import,
    and its ``arquivo_storage`` extension override short-circuits every
    lower-level wire (an injected fake is returned without touching
    ``cloud_connections``).  Both are wired here, as are the legacy Google
    helpers, so a canonical ARQUIVOS path that reaches Drive in ANY way is
    recorded -- even if the error is caught and ignored.
    """
    import app.arquivos as arquivos

    calls = arm_google_tripwires(monkeypatch, app)

    def wire(name):
        def touched(*_args, **_kwargs):
            calls.append(name)
            raise GoogleTouched(name)

        return touched

    for name in ("resolve_google_managed_storage", "resolve_arquivo_storage",
                 "_ensure_arquivos_root", "_upload_google_arquivo"):
        monkeypatch.setattr(arquivos, name, wire(f"app.arquivos.{name}"))
    monkeypatch.setitem(app.extensions, "arquivo_storage", ArquivoTripwireStorage(calls))
    return calls


# ---------------------------------------------------------------------------
# engine-neutral seeders (``?`` placeholders; the caller commits)
# ---------------------------------------------------------------------------


def seed_object(conn, *, key: str, content: bytes, mime: str, uploader: int, now: str) -> int:
    return int(conn.execute(
        "INSERT INTO storage_objects(storage_backend,storage_bucket,storage_key,sha256,size_bytes,mime_type,"
        "uploader_user_id,origin,content_verified_at,created_at) VALUES('supabase',?,?,?,?,?,?,"
        "'direct_upload',?,?) RETURNING id",
        (BUCKET, key, sha256(content), len(content), mime, int(uploader), now, now),
    ).fetchone()[0])


def seed_canonical_arquivo(conn, store, *, uploader: int, now: str, key: str, content: bytes = PDF,
                           mime: str = "application/pdf", original: str = "manual.pdf",
                           titulo: str = "Manual canonico", visivel: int = 1, residue: dict | None = None,
                           operation_key: str = "seed-canonical-op") -> tuple[int, int]:
    """A committed-shape canonical ARQUIVOS row + its object (the fake holds the bytes)."""
    object_id = seed_object(conn, key=key, content=content, mime=mime, uploader=uploader, now=now)
    residue = residue or {}
    row_id = int(conn.execute(
        "INSERT INTO admin_arquivos(titulo,filename,original_filename,visivel,provider,mime_type,size_bytes,"
        "sha256,uploaded_at,uploader_user_id,operation_key,storage_status,storage_object_id,prior_provider,"
        "prior_locator) VALUES(?,?,?,?,'supabase',?,?,?,?,?,?,'active',?,?,?) RETURNING id",
        (titulo, f"ARQ-{operation_key[:12]}-{original}", original, int(visivel), mime, len(content),
         sha256(content), now, int(uploader), operation_key, object_id, residue.get("prior_provider"),
         residue.get("prior_locator")),
    ).fetchone()[0])
    if store is not None:
        store.objects[(BUCKET, key)] = (content, mime)
    return row_id, object_id


def seed_google_arquivo(conn, *, uploader: int, now: str, content: bytes = PDF, remote_file_id: str = "drv-a1",
                        titulo: str = "Manual Google", visivel: int = 1, operation_key: str = "seed-google-op",
                        **overrides) -> int:
    row = dict(
        titulo=titulo, filename=f"ARQ-{operation_key[:12]}-manual.pdf", original_filename="manual.pdf",
        visivel=int(visivel), provider="google", storage_status="active", remote_file_id=remote_file_id,
        remote_parent_id="drv-parent-1", mime_type="application/pdf", size_bytes=len(content),
        sha256=sha256(content), uploaded_at=now, uploader_user_id=int(uploader), operation_key=operation_key,
    )
    row.update(overrides)
    columns = ",".join(row)
    marks = ",".join("?" for _ in row)
    return int(conn.execute(
        f"INSERT INTO admin_arquivos({columns}) VALUES({marks}) RETURNING id", tuple(row.values())
    ).fetchone()[0])


def seed_local_arquivo(conn, upload_root, *, content: bytes = PDF, filename: str = "arquivos/manual-legado.pdf",
                       titulo: str = "Manual local", visivel: int = 1, write_file: bool = True,
                       **overrides) -> int:
    if write_file:
        path = os.path.join(str(upload_root), *filename.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(content)
    row = dict(titulo=titulo, filename=filename, original_filename=os.path.basename(filename),
               visivel=int(visivel))
    row.update(overrides)
    columns = ",".join(row)
    marks = ",".join("?" for _ in row)
    return int(conn.execute(
        f"INSERT INTO admin_arquivos({columns}) VALUES({marks}) RETURNING id", tuple(row.values())
    ).fetchone()[0])


def seed_admin_intent(conn, store, *, actor: int, submission_id: str, slot: str, content: bytes, now: str,
                      mime: str = "application/pdf", filename: str = "novo.pdf",
                      admin_arquivo_id: int | None = None, verify: bool = True, upload: bool = True):
    """Issue (and verify) an ``admin_arquivo`` intent with the S2 primitives, bypassing HTTP."""
    from app.db import write_transaction
    from app.storage import upload_intents as intents

    with write_transaction(conn):
        intent = intents.issue_intent(
            conn, actor_user_id=int(actor), purpose=PURPOSE, operation_id=f"{submission_id}:{slot}",
            bucket=BUCKET, declared_mime_type=mime, declared_size_bytes=len(content),
            declared_sha256=sha256(content), now=now, original_filename=filename,
            admin_arquivo_id=admin_arquivo_id, ttl_seconds=INTENT_TTL_SECONDS,
        )
    if upload and store is not None:
        store.objects[(BUCKET, intent.storage_key)] = (content, mime)
    if verify:
        with write_transaction(conn):
            intents.mark_verified(conn, intent_id=intent.id, actor_user_id=int(actor),
                                  observed_size_bytes=len(content), observed_sha256=sha256(content), now=now)
    return intent


def assert_canonical_steady(row: dict) -> None:
    """The adjudicated canonical ARQUIVOS steady state (B)."""
    assert row["provider"] == "supabase", row
    assert row["storage_status"] == "active", row
    assert row["storage_object_id"] is not None, row
    assert row["remote_file_id"] is None and row["remote_parent_id"] is None, row
    assert row["cleanup_started_at"] is None, row
    assert not str(row["failure_code"] or "").startswith("REPLACEMENT_"), row
    assert (row["replacement_mime_type"], row["replacement_size_bytes"], row["replacement_sha256"]) == (
        None, None, None), row
    assert (row["prior_provider"] is None) == (row["prior_locator"] is None), row


__all__ = [
    "ADMIN_PAGE", "ARQUIVOS_INTENT_IDS_FIELD", "ARQUIVOS_SUBMISSION_FIELD", "ARQUIVO_KEY_RE", "ARQUIVO_SLOTS",
    "ArquivoTripwireStorage", "CREATE_URL", "DELETE_URL", "EDIT_URL", "FORM_INTENT_FIELD_ATTR",
    "FORM_PURPOSE_ATTR", "FORM_SINGLE_ATTR", "FORM_SUBMISSION_FIELD_ATTR", "FORM_TARGET_ATTR",
    "LEGACY_ARQUIVO_FILE_FIELD", "LEGACY_GOOGLE_HELPERS", "LIVE_TARGET_INTENT_STATES",
    "NON_LIVE_TARGET_INTENT_CASES", "NON_STEADY_LEGACY_STATES", "PURPOSE",
    "STUDENT_DOWNLOAD_URL", "STUDENT_VIEW_URL", "TARGET_FIELD", "VIEW_URL",
    "arm_arquivos_google_tripwires", "assert_canonical_steady", "png_with_dimensions", "seed_admin_intent",
    "seed_canonical_arquivo", "seed_google_arquivo", "seed_local_arquivo", "seed_object",
]
