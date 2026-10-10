"""MP-3 dress-rehearsal fixtures -- TEST ONLY, opt-in (``SGAA_MP3_REHEARSAL=1``).

A production-shaped SYNTHETIC source (every person-like value is a placeholder; a
sentinel rides inside document bytes so a leak audit can search outputs), a
run-owned private DEV bucket on the real Supabase DEV project, and the helpers the
rehearsal driver needs.  The credential is read from an environment file outside
the repository and never printed or stored.  Real data is never used here.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

ENABLED_ENV = "SGAA_MP3_REHEARSAL"
ENV_FILE_ENV = "SGAA_DEV_ENV_FILE"
DEFAULT_ENV_FILE = Path.home() / ".sgaa" / "s3a-rehearsal.env"


def env_file() -> Path:
    return Path(os.environ.get(ENV_FILE_ENV) or DEFAULT_ENV_FILE)


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV) == "1" and env_file().is_file()


def load_dev_env() -> dict:
    """``SUPABASE_URL`` and ``SUPABASE_SECRET_KEY`` from the file; nothing else is read or kept."""
    values = {}
    for line in env_file().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return {name: values[name] for name in ("SUPABASE_URL", "SUPABASE_SECRET_KEY") if name in values}


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RunBucket:
    """One private bucket owned by this run; objects are deleted before the bucket."""

    def __init__(self, dev_env: dict) -> None:
        from app.storage.supabase_store import SupabaseObjectStore, SupabaseStorageConfig

        self.name = f"sgaa-mp3-{secrets.token_hex(4)}"
        self._url = dev_env["SUPABASE_URL"].rstrip("/")
        self._key = dev_env["SUPABASE_SECRET_KEY"]
        self.store = SupabaseObjectStore(
            SupabaseStorageConfig(url=self._url, bucket=self.name, secret_key=self._key)
        )

    def _headers(self) -> dict:
        return {"apikey": self._key, "Authorization": f"Bearer {self._key}"}

    def create(self) -> None:
        import requests

        response = requests.post(
            f"{self._url}/storage/v1/bucket",
            json={"id": self.name, "name": self.name, "public": False},
            headers=self._headers(), timeout=30, allow_redirects=False,
        )
        response.raise_for_status()

    def purge_and_delete(self) -> int:
        """Delete every object, then the bucket; returns the number of objects removed."""
        import requests

        removed = 0
        for _ in range(3):  # the listing is eventually consistent after deletes
            listed = self.store.list_objects(self.name, "", max_objects=5000)
            if not listed:
                break
            for item in listed:
                self.store.delete(self.name, item.key)
                removed += 1
        response = requests.delete(
            f"{self._url}/storage/v1/bucket/{self.name}", headers=self._headers(), timeout=30,
            allow_redirects=False,
        )
        if response.status_code not in (200, 404):
            raise RuntimeError(f"bucket removal answered {response.status_code}")
        return removed


def build_source(base: Path, sentinel: str, *, drive=None) -> SimpleNamespace:
    """A v16 SQLite source with legacy local and Google documents, one terminal row and one request.

    Counts are production-shaped, not production-sized.  Returns the paths, the fake
    Drive holding the Google bytes, and the expected classes.
    """
    from app.prod1_schema import bootstrap_prod1_schema
    from tests.storage_mp1_support import ADMIN_ID, FakeDrive, T0, seed_business, sha256
    from tests.storage_s3a_support import PDF, PNG

    base.mkdir(parents=True, exist_ok=True)
    documentos, uploads = base / "documentos", base / "uploads"
    documentos.mkdir(exist_ok=True)
    uploads.mkdir(exist_ok=True)
    database = base / "database.db"
    raw = sqlite3.connect(database)
    raw.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(raw)
    seed_business(raw)
    # Production accounts carry a credential row; Path-B validates that every user has one.
    raw.execute("INSERT OR IGNORE INTO usuario_credenciais(usuario_id, estado) SELECT id, 'personal' FROM usuarios")
    drive = FakeDrive() if drive is None else drive
    drive.files.clear()
    tag = sentinel.encode("ascii")

    def write(root: Path, relative: str, content: bytes) -> None:
        target = root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    counts = {"local_request": 5, "local_arquivo": 2, "google_request": 3, "google_arquivo": 1}
    for index in range(counts["local_request"]):
        relative = f"aluno-1/comprovantes/doc-{index}.pdf"
        write(documentos, relative, PDF + b"%local-" + str(index).encode() + b"-" + tag)
        raw.execute("INSERT INTO requisicao_arquivos(requisicao_id, filename) VALUES(1, ?)", (relative,))
    for index in range(counts["local_arquivo"]):
        relative = f"arquivos/manual-{index}.pdf"
        write(uploads, relative, PDF + b"%arq-" + str(index).encode() + b"-" + tag)
        raw.execute(
            "INSERT INTO admin_arquivos(titulo, filename, original_filename) VALUES(?, ?, 'manual.pdf')",
            (f"Manual {index}", relative),
        )
    for index in range(counts["google_request"]):
        content = PDF + b"%goog-" + str(index).encode() + b"-" + tag
        file_id = f"drvlegacy{index}"
        drive.add_file(parent_id="drvparent1", name=f"REQ-legacy-{index}.pdf", content=content,
                       operation_key=f"op-{file_id}", object_kind="comprovante", file_id=file_id)
        raw.execute(
            "INSERT INTO requisicao_arquivos(requisicao_id,filename,provider,storage_status,remote_file_id,"
            "remote_parent_id,original_filename,mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,"
            "operation_key) VALUES(1,?, 'google','active',?, 'drvparent1','prova.pdf','application/pdf',?,?,"
            "'2026-09-01T10:00:00Z',?,?)",
            (f"REQ-000001__legado-{index}.pdf", file_id, len(content), sha256(content), ADMIN_ID, f"op-{file_id}"),
        )
    content = PNG + b"\x00" + tag
    drive.add_file(parent_id="drvparent2", name="ARQ-legacy.png", content=content, operation_key="op-drvarq",
                   object_kind="arquivo", file_id="drvarq")
    raw.execute(
        "INSERT INTO admin_arquivos(titulo,filename,original_filename,provider,storage_status,remote_file_id,"
        "remote_parent_id,mime_type,size_bytes,sha256,uploaded_at,uploader_user_id,operation_key)"
        " VALUES('Manual G','ARQ-legacy.png','manual.png','google','active','drvarq','drvparent2','image/png',"
        "?,?,?,?,'op-drvarq')",
        (len(content), sha256(content), T0, ADMIN_ID),
    )
    # One terminal legacy row: a trashed Google file the application would never serve.
    raw.execute(
        "INSERT INTO requisicao_arquivos(requisicao_id,filename,provider,storage_status,remote_file_id,"
        "remote_parent_id,original_filename,delete_previous_status,delete_started_at)"
        " VALUES(1,'REQ-000001__lixeira.pdf','google','trashed','drvtrash','drvparent1','lixeira.pdf',"
        "'active','2026-09-02T10:00:00Z')"
    )
    raw.commit()
    raw.close()
    return SimpleNamespace(
        database=database, documentos=documentos, uploads=uploads, drive=drive, counts=counts,
        roots={"requisicao_arquivos": (str(documentos), str(uploads)), "admin_arquivos": (str(uploads),)},
    )


@contextmanager
def application(*, database=None, database_url=None, store=None, drive=None, documentos=None, uploads=None):
    """A bare Flask application context over a SQLite file or a PostgreSQL URL."""
    from flask import Flask

    import app.db as app_db
    from app.storage.drive_mirror import DRIVE_STORAGE_EXTENSION

    saved = (app_db.DATABASE, app_db.DATABASE_URL)
    try:
        if database is not None:
            app_db.DATABASE, app_db.DATABASE_URL = str(database), ""
        else:
            app_db.DATABASE_URL = database_url
        flask_app = Flask("mp3_rehearsal")
        flask_app.config["TESTING"] = True
        flask_app.config["DOCUMENTOS_ALUNOS_FOLDER"] = str(documentos) if documentos else None
        flask_app.config["UPLOAD_FOLDER"] = str(uploads) if uploads else None
        if store is not None:
            flask_app.extensions["canonical_object_store"] = store
        if drive is not None:
            flask_app.extensions[DRIVE_STORAGE_EXTENSION] = drive
        with flask_app.app_context():
            conn = app_db.get_db_connection()
            try:
                yield SimpleNamespace(app=flask_app, conn=conn)
            finally:
                app_db.close_db_connection(None)
    finally:
        app_db.DATABASE, app_db.DATABASE_URL = saved
