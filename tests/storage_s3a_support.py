"""Shared STORAGE S3-A (direct request documents) RED fixtures -- TEST ONLY.

S3-A switches NEW ``requisicao_arquivos`` (comprovante) documents to canonical
Supabase Storage with browser -> Supabase signed TUS uploads.  Nothing here is
production code: these are the contract constants the RED suites encode, the
v15 business-row constraint vectors shared by the SQLite and real-PostgreSQL
suites, and the hermetic helpers (Google tripwires, canonical fake upload,
document fixtures) the HTTP suites use.

APPLICATION CONTRACT ENCODED BY THE RED (adjudicated S3 architecture)
    * ``POST /storage/upload-intents``                JSON + CSRF -> capability
    * ``POST /storage/upload-intents/<id>/finalize``  intent id only -> verified
    * the request forms carry ``comprovantes_submission_id`` (server-issued,
      128-bit, session-bound) and ``comprovantes_intent_ids`` -- never bytes;
    * operation identity is ``<submission_id>:<upload_slot_id>`` (opaque
      128-bit slot per selected file; never an index, digest or filename);
    * the canonical store is injected through
      ``app.extensions["canonical_object_store"]`` (as the Drive fakes are
      injected through ``comprovante_storage`` today);
    * "now" comes from ``app.storage.custody_common.utc_now_text`` so tests can
      drive the 2-hour intent / submission window without sleeping.
"""

from __future__ import annotations

import hashlib
import io
import re
import struct
import zlib

from app.prod1_storage_ddl import BUSINESS_DOCUMENT_MAX_BYTES

# ---------------------------------------------------------------------------
# contract constants
# ---------------------------------------------------------------------------

ISSUE_URL = "/storage/upload-intents"
FINALIZE_URL = "/storage/upload-intents/{intent_id}/finalize"
CANONICAL_STORE_EXTENSION = "canonical_object_store"
SUBMISSION_FIELD = "comprovantes_submission_id"
INTENT_IDS_FIELD = "comprovantes_intent_ids"
LEGACY_FILE_FIELD = "comprovantes_files"

PROJECT_REF = "abcdefghijklmnopqrst"
SUPABASE_URL = f"https://{PROJECT_REF}.supabase.co"
STORAGE_ORIGIN = f"https://{PROJECT_REF}.storage.supabase.co"
#: Signed TUS session creation (live-proven): direct host + ``/upload/resumable/sign``.
DIRECT_TUS_ENDPOINT = f"{STORAGE_ORIGIN}/storage/v1/upload/resumable/sign"
TUS_CHUNK_BYTES = 6 * 1024 * 1024
BUCKET = "sgaa-documentos"
#: Synthetic, test-only secret: never a real key.
TEST_SECRET_KEY = "sb_secret_TESTONLY0000000000000000000000"
#: Synthetic, test-only browser-safe publishable key: never a real key.
TEST_PUBLISHABLE_KEY = "sb_publishable_TESTONLY000000000000000000"
INTENT_TTL_SECONDS = 2 * 60 * 60
SIGNED_DOWNLOAD_TTL_SECONDS = 60
MIB16 = BUSINESS_DOCUMENT_MAX_BYTES
TS = "2026-01-02 03:04:05"

#: Operation identity is ``<submission_id>:<upload_slot_id>``.  An upload slot
#: is OPAQUE 128-bit lowercase hex (browser crypto randomness is acceptable):
#: stable across retries of the SAME selected file, new for a deliberately
#: different file, never a positional index, a digest or a filename, and never
#: an authorization by itself.  SHA-256 stays declaration metadata only.
UPLOAD_SLOT_RE = r"[0-9a-f]{32}"
UPLOAD_SLOTS = (
    "5a1d0c3e9b7f4a2e8c6d1b0f3e5a7c9d", "c4e2a0f8d6b4a2c0e8f6d4b2a0c8e6f4", "0f1e2d3c4b5a69788796a5b4c3d2e1f0",
    "9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b", "1b3d5f7a9c2e4f6a8b0d2f4a6c8e0b2d", "7c9e1a3b5d7f9b1d3f5a7c9e1b3d5f7a",
)
SUBMISSION_ID = "2f4e6a8c0b1d3f5e7a9c2b4d6f8e0a1c"


def operation_id(submission_id: str, slot: str) -> str:
    return f"{submission_id}:{slot}"


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------


def _pdf() -> bytes:
    header = b"%PDF-1.4\n"
    objects = (
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] /Resources << >> >>\nendobj\n",
    )
    offsets, payload = [], header
    for obj in objects:
        offsets.append(len(payload))
        payload += obj
    xref = len(payload)
    payload += b"xref\n0 4\n0000000000 65535 f \n"
    payload += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return payload + b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _png() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


PDF = _pdf()
PNG = _png()
_PNG_PRIVATE_CHUNK_OVERHEAD = 12


def padded_png(total_size: int) -> bytes:
    """A structurally valid PNG of EXACTLY ``total_size`` bytes.

    The padding is one private ancillary chunk (``pdAt``) before IDAT, which a
    conforming decoder skips; the image stays 1x1.
    """
    padding = total_size - len(PNG) - _PNG_PRIVATE_CHUNK_OVERHEAD
    if padding < 0:
        raise ValueError("target below the minimal PNG size")
    head = PNG[:33]  # signature + IHDR
    padded = head + _chunk(b"pdAt", b"\x00" * padding) + PNG[33:]
    assert len(padded) == total_size
    return padded


def encrypted_pdf() -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(PDF)).pages:
        writer.add_page(page)
    writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def declaration(content: bytes, filename: str, mime: str, **extra) -> dict:
    return {"filename": filename, "mime_type": mime, "size_bytes": len(content),
            "sha256": sha256(content), **extra}


# ---------------------------------------------------------------------------
# v15 business-row constraint vectors (one definition, both engines)
# ---------------------------------------------------------------------------

#: ``storage_object_id`` placeholder: the suites replace it with a fresh,
#: unshared storage object per case (the per-table unique index would
#: otherwise refuse every case after the first).
NEW_OBJECT = object()


def canonical_request_row(**overrides) -> dict:
    row = dict(
        requisicao_id=1, filename="REQ-000001__conceito__v1__20260102T030405__abcd1234.pdf",
        provider="supabase", storage_status="active", original_filename="comprovante.pdf",
        mime_type="application/pdf", size_bytes=1024, sha256="a" * 64, uploaded_at=TS,
        uploader_user_id=2, operation_key=operation_id(SUBMISSION_ID, UPLOAD_SLOTS[0]),
        storage_object_id=NEW_OBJECT,
    )
    row.update(overrides)
    return row


def legacy_google_request_row(**overrides) -> dict:
    row = dict(
        requisicao_id=1, filename="REQ-000001__legacy.pdf", provider="google", storage_status="active",
        remote_file_id="drv-legacy-1", remote_parent_id="drv-parent-1", original_filename="legado.pdf",
        mime_type="application/pdf", size_bytes=10, sha256="b" * 64, uploaded_at=TS,
        uploader_user_id=2, operation_key="legacy-op:0:bbbbbbbbbbbbbbbb",
    )
    row.update(overrides)
    return row


#: ``(label, row, v15 verdict)``.  The "today" verdict of every
#: ``provider='supabase'`` row is REJECTED (v14 has no such provider); the
#: legacy controls carry the same verdict on v14 and v15.
REQUEST_ROW_CASES = (
    ("canonical active", canonical_request_row(), True),
    ("canonical trashed (request removal keeps evidence)", canonical_request_row(storage_status="trashed"), True),
    ("canonical without storage object", canonical_request_row(storage_object_id=None), False),
    ("canonical carrying a Google file id", canonical_request_row(remote_file_id="drv-1"), False),
    ("canonical carrying a Google parent id", canonical_request_row(remote_parent_id="drv-p"), False),
    ("pending belongs to storage_upload_intents", canonical_request_row(storage_status="pending"), False),
    ("uploaded is a Drive upload state", canonical_request_row(storage_status="uploaded"), False),
    ("legacy_active is not canonical", canonical_request_row(storage_status="legacy_active"), False),
    ("failed belongs to the intent", canonical_request_row(storage_status="failed"), False),
    ("deletion_pending is the Drive delete protocol", canonical_request_row(storage_status="deletion_pending"),
     False),
    ("canonical with Drive delete bookkeeping",
     canonical_request_row(storage_status="trashed", delete_previous_status="active", delete_started_at=TS), False),
    ("canonical needs sha256", canonical_request_row(sha256=None), False),
    ("canonical sha256 is 64 lowercase hex", canonical_request_row(sha256="A" * 64), False),
    ("canonical needs an allowed MIME", canonical_request_row(mime_type="text/html"), False),
    ("canonical needs a positive size", canonical_request_row(size_bytes=0), False),
    ("canonical needs an operation key", canonical_request_row(operation_key=None), False),
    ("canonical needs an uploader", canonical_request_row(uploader_user_id=None), False),
    ("canonical needs the original filename", canonical_request_row(original_filename=None), False),
    ("canonical needs uploaded_at", canonical_request_row(uploaded_at=None), False),
    ("unknown provider stays refused", canonical_request_row(provider="onedrive"), False),
    # legacy controls -- identical verdicts on v14 and v15
    ("legacy local default", dict(requisicao_id=1, filename="aluno_1/legado.pdf"), True),
    ("legacy Google active", legacy_google_request_row(), True),
    ("legacy Google pending", legacy_google_request_row(storage_status="pending", remote_file_id=None,
                                                        remote_parent_id=None), True),
    ("legacy Google active needs its locator", legacy_google_request_row(remote_file_id=None), False),
    ("legacy local cannot carry a Google locator",
     dict(requisicao_id=1, filename="x.pdf", remote_file_id="drv-x"), False),
    # storage_object_id does NOT imply provider='supabase': the S2 / Path-B /
    # Layer-2 compatibility of legacy rows that carry a canonical reference
    # stays exactly as published (the reverse implication is NOT a DB rule).
    ("legacy local carrying a storage object stays legal (S2 compatibility)",
     dict(requisicao_id=1, filename="aluno_1/legado.pdf", storage_object_id=NEW_OBJECT), True),
    ("legacy Google carrying a storage object stays legal (S2 compatibility)",
     legacy_google_request_row(storage_object_id=NEW_OBJECT), True),
)


def canonical_admin_row(**overrides) -> dict:
    row = dict(
        titulo="Manual", filename="ARQ-0123456789ab-manual.pdf", original_filename="manual.pdf", visivel=1,
        provider="supabase", storage_status="active", mime_type="application/pdf", size_bytes=2048,
        sha256="c" * 64, uploaded_at=TS, uploader_user_id=1, operation_key="arq-op-1",
        storage_object_id=NEW_OBJECT,
    )
    row.update(overrides)
    return row


#: Legacy residue of an ARQUIVOS row whose bytes are now canonical: the
#: EXISTING ``prior_provider`` / ``prior_locator`` pair (provider discriminator
#: + Drive file id or upload-relative path) on an ``active`` canonical row.
#: Under ``provider='supabase'`` it means LEGACY RESIDUE PRESERVED FOR S5 --
#: never "cleanup pending", never ``retry_arquivo_cleanup`` ownership -- so
#: ``cleanup_started_at`` stays NULL and ``replacement_cleanup_pending`` is
#: NOT a canonical status (it keeps its Google / legacy meaning unchanged).
GOOGLE_RESIDUE = dict(prior_provider="google", prior_locator="drv-old-1")
LOCAL_RESIDUE = dict(prior_provider="local_legacy", prior_locator="arquivos/manual-antigo.pdf")


def legacy_google_admin_row(**overrides) -> dict:
    row = dict(
        titulo="Manual", filename="ARQ-x-manual.pdf", original_filename="manual.pdf", provider="google",
        storage_status="active", remote_file_id="drv-a", remote_parent_id="drv-pa",
        mime_type="application/pdf", size_bytes=10, sha256="d" * 64, uploaded_at=TS, uploader_user_id=1,
        operation_key="arq-legacy-op",
    )
    row.update(overrides)
    return row


ADMIN_ROW_CASES = (
    ("canonical active", canonical_admin_row(), True),
    ("canonical with Google legacy residue preserved for S5", canonical_admin_row(**GOOGLE_RESIDUE), True),
    ("canonical with local legacy residue preserved for S5", canonical_admin_row(**LOCAL_RESIDUE), True),
    ("canonical without storage object", canonical_admin_row(storage_object_id=None), False),
    ("canonical carrying a Google file id", canonical_admin_row(remote_file_id="drv-1"), False),
    ("canonical pending belongs to the intent", canonical_admin_row(storage_status="pending"), False),
    ("canonical never uses replacement_cleanup_pending",
     canonical_admin_row(storage_status="replacement_cleanup_pending", cleanup_started_at=TS, **GOOGLE_RESIDUE),
     False),
    ("canonical residue never carries cleanup bookkeeping",
     canonical_admin_row(cleanup_started_at=TS, **GOOGLE_RESIDUE), False),
    ("canonical without residue never carries cleanup bookkeeping", canonical_admin_row(cleanup_started_at=TS),
     False),
    ("residue provider without locator", canonical_admin_row(prior_provider="google"), False),
    ("residue locator without provider", canonical_admin_row(prior_locator="drv-old-1"), False),
    ("residue is legacy-only", canonical_admin_row(prior_provider="supabase", prior_locator="drv-old-1"), False),
    ("residue locator is non-empty", canonical_admin_row(prior_provider="google", prior_locator=""), False),
    ("residue locator is not blank", canonical_admin_row(prior_provider="google", prior_locator="   "), False),
    ("Google residue locator is a Drive id",
     canonical_admin_row(prior_provider="google", prior_locator="drv old/1"), False),
    ("local residue locator is relative", canonical_admin_row(prior_provider="local_legacy",
                                                              prior_locator="/etc/arquivos/x.pdf"), False),
    ("local residue locator has no traversal", canonical_admin_row(prior_provider="local_legacy",
                                                                   prior_locator="arquivos/../../x.pdf"), False),
    ("canonical needs sha256", canonical_admin_row(sha256=None), False),
    # legacy controls -- identical verdicts on v14 and v15
    ("legacy local", dict(titulo="Manual", filename="arquivos/manual.pdf"), True),
    ("legacy Google active", legacy_google_admin_row(), True),
    ("legacy Google replacement_cleanup_pending keeps its meaning", legacy_google_admin_row(
        storage_status="replacement_cleanup_pending", prior_provider="google", prior_locator="drv-old-a",
        cleanup_started_at=TS), True),
    ("legacy local carrying a storage object stays legal (S2 compatibility)",
     dict(titulo="Manual", filename="arquivos/manual.pdf", storage_object_id=NEW_OBJECT), True),
)


def materialize(row: dict, object_id) -> dict:
    return {k: (object_id if v is NEW_OBJECT else v) for k, v in row.items()}


def object_row_for(key_suffix: str, **overrides) -> dict:
    row = dict(
        storage_backend="supabase", storage_bucket=BUCKET,
        storage_key=f"comprovantes/2026/01/{key_suffix}", sha256="a" * 64, size_bytes=1024,
        mime_type="application/pdf", uploader_user_id=2, origin="direct_upload",
        content_verified_at=TS, created_at=TS,
    )
    row.update(overrides)
    return row


def insert_sql(table: str, row: dict, placeholder: str = "?") -> tuple[str, tuple]:
    columns = ", ".join(row)
    marks = ", ".join(placeholder for _ in row)
    return f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(row.values())


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_INPUT_RE = re.compile(rb"<input\b[^>]*>", re.IGNORECASE | re.DOTALL)


def hidden_value(html: bytes, name: str) -> str | None:
    """Value of the ``<input name=...>`` named ``name`` in rendered HTML."""
    for tag in _INPUT_RE.findall(html):
        if re.search(rb"""name\s*=\s*["']""" + re.escape(name.encode()) + rb"""["']""", tag):
            value = re.search(rb"""value\s*=\s*["']([^"']*)["']""", tag)
            return value.group(1).decode() if value else ""
    return None


def browser_upload(store, capability: dict, content: bytes, content_type: str) -> None:
    """The browser's direct upload, played against the injected canonical fake.

    Uses the TUS-shaped completion when the S3 fake offers it, otherwise the S2
    signed-PUT completion -- the application observes the same end state.
    """
    resumable = getattr(store, "complete_resumable_upload", None)
    if resumable is not None:
        resumable(
            token=capability["upload_token"], bucket=capability["bucket"],
            object_name=capability["object_name"], content=content, content_type=content_type,
        )
    else:
        store.complete_signed_upload(capability["upload_token"], content, mime_type=content_type)


# ---------------------------------------------------------------------------
# Google tripwires
# ---------------------------------------------------------------------------


class GoogleTouched(AssertionError):
    """A Google entry point was reached on a canonical (Drive-independent) path."""


class TripwireDriveStorage:
    """Stands in for ``comprovante_storage``: any use is a Drive dependency."""

    provider = "google"

    def __init__(self, calls: list) -> None:
        self._calls = calls

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def touched(*_args, **_kwargs):
            self._calls.append(f"comprovante_storage.{name}")
            raise GoogleTouched(f"comprovante_storage.{name}")

        return touched


def arm_google_tripwires(monkeypatch, app) -> list:
    """Make EVERY Google entry point raise ``GoogleTouched`` and record it.

    Account resolution and token acquisition are wrapped so that only the
    Google provider trips (the OneDrive mail path is unrelated).  Returns the
    shared call log; a Drive-independent flow must leave it EMPTY -- an
    ignored, caught Google error would still be recorded here.
    """
    import googleapiclient.discovery

    import app.cloud_connections as cloud_connections
    import app.comprovantes as comprovantes
    import app.services.google_drive_service as drive_service
    import app.storage.google_connection as google_connection
    import app.storage.google_drive as google_drive

    calls: list = []

    def wire(name):
        def touched(*_args, **_kwargs):
            calls.append(name)
            raise GoogleTouched(name)

        return touched

    def provider_wire(name, original):
        def guarded(conn, provider, *args, **kwargs):
            if str(provider).strip().lower() == "google":
                calls.append(name)
                raise GoogleTouched(name)
            return original(conn, provider, *args, **kwargs)

        return guarded

    for name in ("get_active_cloud_account", "get_authenticated_access_token",
                 "recover_authenticated_access_token_after_401"):
        monkeypatch.setattr(cloud_connections, name, provider_wire(name, getattr(cloud_connections, name)))
    monkeypatch.setattr(cloud_connections, "acquire_google_access_token", wire("acquire_google_access_token"))
    monkeypatch.setattr(drive_service, "acquire_access_token", wire("google_drive_service.acquire_access_token"))
    monkeypatch.setattr(drive_service, "_fetch_email", wire("google_drive_service._fetch_email"))
    monkeypatch.setattr(google_connection, "resolve_google_managed_storage",
                        wire("resolve_google_managed_storage"))
    monkeypatch.setattr(comprovantes, "resolve_google_managed_storage", wire("resolve_google_managed_storage"))
    monkeypatch.setattr(comprovantes, "resolve_google_storage", wire("resolve_google_storage"))
    monkeypatch.setattr(googleapiclient.discovery, "build", wire("googleapiclient.build"))
    monkeypatch.setattr(google_drive, "build", wire("google_drive.build"))
    for cls in (google_drive.GoogleDriveComprovanteStorage, google_drive.GoogleDriveManagedObjectStorage):
        for method in ("ensure_folder", "upload", "trash", "untrash", "download"):
            if hasattr(cls, method):
                monkeypatch.setattr(cls, method, wire(f"{cls.__name__}.{method}"))
    monkeypatch.setitem(app.extensions, "comprovante_storage", TripwireDriveStorage(calls))
    return calls


__all__ = [
    "ADMIN_ROW_CASES", "BUCKET", "CANONICAL_STORE_EXTENSION", "DIRECT_TUS_ENDPOINT", "FINALIZE_URL",
    "GOOGLE_RESIDUE", "GoogleTouched", "INTENT_IDS_FIELD", "INTENT_TTL_SECONDS", "ISSUE_URL",
    "LEGACY_FILE_FIELD", "LOCAL_RESIDUE", "MIB16", "NEW_OBJECT", "PDF", "PNG", "PROJECT_REF",
    "REQUEST_ROW_CASES", "SIGNED_DOWNLOAD_TTL_SECONDS", "STORAGE_ORIGIN", "SUBMISSION_FIELD",
    "SUBMISSION_ID", "SUPABASE_URL", "TEST_PUBLISHABLE_KEY", "TEST_SECRET_KEY", "TS", "TUS_CHUNK_BYTES", "TripwireDriveStorage",
    "UPLOAD_SLOTS", "UPLOAD_SLOT_RE", "arm_google_tripwires", "browser_upload", "canonical_admin_row",
    "canonical_request_row", "declaration", "encrypted_pdf", "hidden_value", "insert_sql",
    "legacy_google_admin_row", "legacy_google_request_row", "materialize", "object_row_for",
    "operation_id", "padded_png", "sha256",
]
