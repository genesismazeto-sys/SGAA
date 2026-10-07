# coding: utf-8
"""STORAGE S1: one-shot importer of legacy image files (``app.image_import``).

Every database is a private temporary prod-1/v13 SQLite file with synthetic
rows; every source file lives under pytest's tmp_path.  The operational
``database.db`` and the real upload roots are never touched.
"""
from __future__ import annotations

import hashlib
import io
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from app import image_import
from app.image_validation import normalize_profile_photo
from app.prod1_schema import bootstrap_prod1_schema

ADMIN_NAME = "Administradora Sigilosa"
STUDENT_NAME = "Estudante Sigiloso"


def _image(fmt="PNG", color=(10, 200, 30), size=(80, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Installation:
    """A v13 database plus upload/documents roots holding legacy files."""

    def __init__(self, root: Path):
        self.db = root / "legacy.db"
        self.uploads = root / "uploads"
        self.documents = root / "documentos_alunos"
        self.uploads.mkdir()
        self.documents.mkdir()
        conn = sqlite3.connect(self.db)
        conn.execute("PRAGMA foreign_keys=ON")
        bootstrap_prod1_schema(conn)
        conn.execute(
            "INSERT INTO usuarios(id,nome,email,senha,tipo,nivel_acesso)"
            " VALUES(4,?,'admin.legado@example.invalid','x','admin','admin_total')",
            (ADMIN_NAME,),
        )
        conn.execute(
            "INSERT INTO usuarios(id,nome,email,senha,tipo,nivel_acesso)"
            " VALUES(9,?,'aluno.legado@example.invalid','x','aluno','usuario')",
            (STUDENT_NAME,),
        )
        conn.execute("INSERT INTO alunos(id,usuario_id,nome,matricula) VALUES(12,9,?,'LEG-12')", (STUDENT_NAME,))
        conn.execute("INSERT INTO reportes(id,aluno_id,titulo,descricao) VALUES(30,12,'Bug','Descricao')")
        conn.execute("INSERT INTO reportes(id,aluno_id,titulo,descricao) VALUES(31,12,'Sem captura','D')")
        conn.commit()
        conn.close()
        self.admin_rel = "avatars/usuario_4/avatar-20250101-abcd-minha-foto.png"
        self.student_rel = "aluno_12 - estudante-sigiloso/perfil/foto-perfil-eu.jpg"
        self.shot_rel = "aluno_12 - estudante-sigiloso/reportes/reporte12-tela.webp"
        self.files = {
            self.uploads / self.admin_rel: _image("PNG"),
            self.documents / self.student_rel: _image("JPEG", color=(250, 10, 10)),
            self.documents / self.shot_rel: _image("WEBP", color=(1, 2, 250), size=(300, 200)),
        }
        for path, content in self.files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.set_references()

    def set_references(self, admin=None, student=None, shot=None):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE usuarios SET foto_perfil=? WHERE id=4", (admin or self.admin_rel,))
        conn.execute("UPDATE alunos SET foto_perfil=? WHERE id=12", (student or self.student_rel,))
        conn.execute("UPDATE reportes SET screenshot_filename=? WHERE id=30", (shot or self.shot_rel,))
        conn.commit()
        conn.close()

    def query(self, sql, params=()):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def files_unchanged(self) -> bool:
        return all(path.read_bytes() == content for path, content in self.files.items())

    def run(self, *, apply=True, **overrides):
        options = {"upload_root": self.uploads, "documents_root": self.documents, "apply": apply}
        options.update(overrides)
        return image_import.run_import(self.db, **options)

    def cli(self, capsys, *extra):
        code = image_import.main([
            "--database", str(self.db), "--upload-root", str(self.uploads),
            "--documents-root", str(self.documents), *extra,
        ])
        captured = capsys.readouterr()
        return code, captured.out + captured.err


@pytest.fixture
def inst(tmp_path):
    return Installation(tmp_path)


def _results(report):
    return {(table, owner): code for table, owner, code in report.results}


def test_dry_run_counts_only_and_writes_nothing(inst, capsys):
    before = inst.db.read_bytes()
    report = inst.run(apply=False)
    assert not report.applied and report.results == []
    assert {t: c.legacy_references for t, c in report.census.items()} == {
        "usuarios_foto": 1, "alunos_foto": 1, "reportes_captura": 1,
    }
    assert all(c.database_images == 0 for c in report.census.values())
    assert inst.db.read_bytes() == before
    code, output = inst.cli(capsys)
    assert code == 0 and "result: DRY RUN" in output
    assert inst.db.read_bytes() == before


def test_apply_moves_every_reference_into_its_row_in_one_transaction_each(inst):
    report = inst.run()
    assert _results(report) == {
        ("usuarios_foto", 4): "MIGRATED",
        ("alunos_foto", 12): "MIGRATED",
        ("reportes_captura", 30): "MIGRATED",
    }
    assert inst.query("SELECT foto_perfil FROM usuarios WHERE id=4") == [(None,)]
    assert inst.query("SELECT foto_perfil FROM alunos WHERE id=12") == [(None,)]
    assert inst.query("SELECT screenshot_filename FROM reportes WHERE id=30") == [(None,)]
    # Profile photos are normalized exactly like a new upload; screenshots kept as-is.
    admin = normalize_profile_photo(inst.files[inst.uploads / inst.admin_rel])
    assert inst.query("SELECT sha256, conteudo FROM usuarios_foto WHERE usuario_id=4") == [(admin.sha256, admin.content)]
    shot = inst.files[inst.documents / inst.shot_rel]
    assert inst.query("SELECT mime_type, sha256, conteudo FROM reportes_captura WHERE reporte_id=30") == [
        ("image/webp", _sha(shot), shot)
    ]
    assert inst.files_unchanged()
    census = report.census
    assert all(c.legacy_references == 0 and c.already_migrated == 1 for c in census.values())


def test_rerun_is_idempotent(inst):
    inst.run()
    snapshot = inst.query("SELECT usuario_id, sha256 FROM usuarios_foto")
    again = inst.run()
    assert again.results == [] and again.refused == 0
    assert inst.query("SELECT usuario_id, sha256 FROM usuarios_foto") == snapshot


def test_missing_file_is_refused_and_the_record_left_intact(inst):
    (inst.documents / inst.student_rel).unlink()
    del inst.files[inst.documents / inst.student_rel]
    report = inst.run()
    assert _results(report)[("alunos_foto", 12)] == "FILE_MISSING"
    assert inst.query("SELECT foto_perfil FROM alunos WHERE id=12") == [(inst.student_rel,)]
    assert inst.query("SELECT count(*) FROM alunos_foto") == [(0,)]
    assert _results(report)[("usuarios_foto", 4)] == "MIGRATED"  # the others still move
    assert report.refused == 1


def test_a_reference_present_under_both_roots_is_ambiguous(inst):
    twin = inst.uploads / inst.student_rel
    twin.parent.mkdir(parents=True)
    twin.write_bytes(_image("JPEG", color=(0, 0, 0)))
    report = inst.run()
    assert _results(report)[("alunos_foto", 12)] == "PATH_AMBIGUOUS"
    assert inst.query("SELECT foto_perfil FROM alunos WHERE id=12") == [(inst.student_rel,)]


@pytest.mark.parametrize(
    ("content", "code"),
    [(b"<html>not an image</html>", "UNSUPPORTED_FORMAT"), (b"\x89PNG\r\n\x1a\ntruncated", "INVALID_IMAGE")],
)
def test_invalid_content_is_refused(inst, content, code):
    (inst.uploads / inst.admin_rel).write_bytes(content)
    inst.files[inst.uploads / inst.admin_rel] = content
    report = inst.run()
    assert _results(report)[("usuarios_foto", 4)] == code
    assert inst.query("SELECT count(*) FROM usuarios_foto") == [(0,)]
    assert inst.query("SELECT foto_perfil FROM usuarios WHERE id=4") == [(inst.admin_rel,)]
    assert inst.files_unchanged()


def test_escaping_reference_is_refused(inst):
    inst.set_references(shot="../../fora/da/raiz.png")
    report = inst.run()
    assert _results(report)[("reportes_captura", 30)] == "PATH_INVALID"


def test_existing_row_with_the_same_image_only_clears_the_path(inst):
    image = normalize_profile_photo(inst.files[inst.uploads / inst.admin_rel])
    conn = sqlite3.connect(inst.db)
    conn.execute(
        "INSERT INTO usuarios_foto(usuario_id,mime_type,size_bytes,sha256,width,height,conteudo)"
        " VALUES(4,?,?,?,?,?,?)",
        (image.mime_type, image.size_bytes, image.sha256, image.width, image.height, image.content),
    )
    conn.commit()
    conn.close()
    report = inst.run()
    assert _results(report)[("usuarios_foto", 4)] == "ALREADY_PRESENT_IDENTICAL"
    assert inst.query("SELECT foto_perfil FROM usuarios WHERE id=4") == [(None,)]
    assert inst.query("SELECT count(*), sha256 FROM usuarios_foto") == [(1, image.sha256)]


def test_existing_row_with_a_different_image_is_a_conflict_never_overwritten(inst):
    other = _image("JPEG", color=(1, 1, 1))
    conn = sqlite3.connect(inst.db)
    conn.execute(
        "INSERT INTO alunos_foto(aluno_id,mime_type,size_bytes,sha256,width,height,conteudo)"
        " VALUES(12,'image/jpeg',?,?,80,60,?)",
        (len(other), _sha(other), other),
    )
    conn.commit()
    conn.close()
    report = inst.run()
    assert _results(report)[("alunos_foto", 12)] == "CONFLICT_DIFFERENT_IMAGE"
    assert inst.query("SELECT sha256 FROM alunos_foto WHERE aluno_id=12") == [(_sha(other),)]
    assert inst.query("SELECT foto_perfil FROM alunos WHERE id=12") == [(inst.student_rel,)]


def test_output_is_value_free(inst, capsys):
    (inst.documents / inst.student_rel).unlink()
    del inst.files[inst.documents / inst.student_rel]
    code, output = inst.cli(capsys, "--apply")
    assert code == 1
    assert "alunos_foto id=12 status=FILE_MISSING" in output
    assert "usuarios_foto id=4 status=MIGRATED" in output
    assert "result: APPLIED_WITH_REFUSALS refused=1" in output
    for secret in (
        ADMIN_NAME, STUDENT_NAME, "estudante-sigiloso", "minha-foto", "avatars/", "aluno_12",
        str(inst.uploads), str(inst.documents), "example.invalid",
    ):
        assert secret not in output, secret
    assert not any(ord(ch) > 127 or (ord(ch) < 32 and ch not in "\n\t") for ch in output)


def test_refusals_before_any_record(tmp_path, capsys):
    assert image_import.main([]) == 2
    assert image_import.main(["--database", str(tmp_path / "absent.db")]) == 1
    assert "DATABASE_MISSING" in capsys.readouterr().err
    stale = tmp_path / "v12.db"
    conn = sqlite3.connect(stale)
    bootstrap_prod1_schema(conn)
    from tests.prod1_v13_support import revert_prod1_v13_to_v12

    revert_prod1_v13_to_v12(conn)
    conn.close()
    assert image_import.main(["--database", str(stale), "--apply"]) == 1
    assert "SCHEMA_NOT_CURRENT" in capsys.readouterr().err
