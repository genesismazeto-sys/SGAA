# coding: utf-8
"""MP-3 slice 2: the deployment export and leak audit (``tools/deploy_audit.py``) -- no database.

The controls must fail on the defect they target: a database or dump in the
upload (by name AND by signature, so a renamed file is still caught), a secret
shape, an operator-planted sentinel, a link out of the tree, a path that is not
on the runtime allowlist, and an output that would echo a path.
"""

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools import deploy_audit as da

REPO_ROOT = Path(da.__file__).resolve().parents[1]


def _head() -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("deploy-export") / "upload"
    result = da.export(_head(), out)
    return out, result


def _codes(directory, **kwargs):
    return sorted({f["code"] for f in da.audit(directory, **kwargs)["findings"]})


def test_export_contains_only_the_runtime_allowlist_and_audits_clean(exported):
    out, result = exported
    assert result["files"] > 50 and result["commit"] == _head()
    top = {path.name for path in out.iterdir()}
    assert top <= set(da.RUNTIME_ALLOWLIST), top - set(da.RUNTIME_ALLOWLIST)
    assert {"app", "templates", "main.py", "requirements.txt"} <= top
    for excluded in ("tests", "docs", "tools", "uploads", "documentos_alunos", "logs", ".git", "database.db"):
        assert not (out / excluded).exists()
    assert da.audit(out)["findings"] == []


def test_export_is_the_committed_bytes_whatever_the_operators_line_ending_setting_is(tmp_path, monkeypatch):
    """The reviewed commit is what is deployed.  ``git archive`` under ``core.autocrlf=true``
    (the norm on the workstation) rewrites every text file to CRLF; the tool must not."""
    for index, (key, value) in enumerate((("core.autocrlf", "true"), ("core.eol", "crlf"))):
        monkeypatch.setenv(f"GIT_CONFIG_KEY_{index}", key)
        monkeypatch.setenv(f"GIT_CONFIG_VALUE_{index}", value)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    # Control: plain git under that configuration does produce CRLF for this repository.
    plain = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", "--format=tar", "HEAD", "main.py"],
                           capture_output=True, check=True).stdout
    assert b"\r\n" in plain
    out = tmp_path / "upload"
    da.export(_head(), out)
    committed = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "blob", "HEAD:main.py"],
                               capture_output=True, check=True).stdout
    assert (out / "main.py").read_bytes() == committed
    requirements = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "blob", "HEAD:requirements.txt"],
                                  capture_output=True, check=True).stdout
    assert (out / "requirements.txt").read_bytes() == requirements


def test_a_file_that_is_not_the_committed_blob_is_refused(tmp_path, monkeypatch):
    original = da._blob_id
    monkeypatch.setattr(da, "_blob_id", lambda data: original(data + b"x"))
    with pytest.raises(da.Refused) as caught:
        da.export(_head(), tmp_path / "upload")
    assert caught.value.code == "EXPORT_NOT_THE_COMMIT"


@pytest.mark.parametrize("member,allowed", [
    ("app/x.py", True), ("main.py", True), ("tests/x.py", False), ("docs/x.md", False),
    ("../app/x.py", False), ("app/../tests/x.py", False), ("app\\x.py", False), ("app/x.py:stream", False),
    ("/etc/passwd", False),
])
def test_member_names_are_allowlisted_and_never_unsafe(member, allowed):
    assert da._allowed(member) is allowed


def test_every_first_party_module_the_application_imports_is_in_the_export(exported):
    out, _ = exported
    first_party = {"app", "services", "utils", "presets_api", "main"}
    missing = set()
    for source in list(out.joinpath("app").rglob("*.py")) + [out / "main.py", out / "presets_api.py"]:
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if root in first_party:
                    relative = Path(*name.split("."))
                    if not (out / relative).with_suffix(".py").exists() and not (out / relative).is_dir():
                        # `from app import x` names a module or an attribute; only the package must exist.
                        missing.add(name)
    # Operator tools and tests are deliberately outside the export; no runtime module may import them.
    assert not any(name.split(".")[0] in {"tools", "tests"} for name in missing), missing
    assert not missing, sorted(missing)[:10]


def test_export_refuses_the_repository_a_non_empty_directory_and_an_unknown_commit(tmp_path):
    with pytest.raises(da.Refused) as caught:
        da.export(_head(), REPO_ROOT / "tmp-export-should-not-exist")
    assert caught.value.code == "OUTPUT_INSIDE_REPOSITORY"
    a_file = tmp_path / "plain-file"
    a_file.write_text("x")
    with pytest.raises(da.Refused) as caught:
        da.export(_head(), a_file)
    assert caught.value.code == "OUTPUT_NOT_EMPTY"
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "x").write_text("x")
    with pytest.raises(da.Refused) as caught:
        da.export(_head(), busy)
    assert caught.value.code == "OUTPUT_NOT_EMPTY"
    with pytest.raises(da.Refused) as caught:
        da.export("0" * 40, tmp_path / "fresh")
    assert caught.value.code == "COMMIT_NOT_FOUND"


# ---- audit: each control against its own defect ----------------------------------------------


def test_a_database_is_found_by_name_and_by_signature_even_when_renamed(tmp_path):
    (tmp_path / "database.db").write_bytes(b"anything")
    (tmp_path / "renamed.txt").write_bytes(da.SQLITE_MAGIC + b"\x00" * 100)
    (tmp_path / "x.dat").write_bytes(da.PG_DUMP_MAGIC + b"\x01\x0e")
    codes = _codes(tmp_path)
    assert {"FORBIDDEN_NAME", "SQLITE_SIGNATURE", "POSTGRESQL_DUMP_SIGNATURE"} <= set(codes)


def test_documents_logs_environment_files_and_object_sets_are_forbidden(tmp_path):
    for relative in ("uploads/a.pdf", "documentos_alunos/b.png", "logs/app.log", ".env", ".env.production",
                     "key.pem", "set/MANIFEST.json", "ledger.jsonl", "pkg/x.dump"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    found = {f["path"] for f in da.audit(tmp_path)["findings"]}
    assert {"uploads/a.pdf", "documentos_alunos/b.png", "logs/app.log", ".env", ".env.production", "key.pem",
            "set/MANIFEST.json", "ledger.jsonl", "pkg/x.dump"} <= found


def test_case_variants_of_forbidden_directories_and_names_are_found(tmp_path):
    for relative in ("Uploads/a.pdf", "DOCUMENTOS_ALUNOS/b.png", "Static/DATABASE.DB", "x/.ENV", "Logs/a.txt"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    found = {f["path"] for f in da.audit(tmp_path)["findings"]}
    assert {"Uploads/a.pdf", "DOCUMENTOS_ALUNOS/b.png", "Static/DATABASE.DB", "x/.ENV", "Logs/a.txt"} <= found


def test_other_export_shapes_are_found(tmp_path):
    (tmp_path / "backup.sql").write_bytes(b"x")
    (tmp_path / "production.env").write_bytes(b"x")
    (tmp_path / ".pgpass").write_bytes(b"x")
    (tmp_path / "alunos.csv").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"-- PostgreSQL database dump\nCOPY public.t (a) FROM stdin;\n")
    (tmp_path / "cfg.py").write_bytes(b"U = 'postgresql+psycopg://svc:hunter22@db.example.test/x'")
    found = {f["path"]: f["code"] for f in da.audit(tmp_path)["findings"]}
    assert {"backup.sql", "production.env", ".pgpass", "alunos.csv"} <= set(found)
    assert found["notes.txt"] == "POSTGRESQL_DUMP_TEXT"
    assert found["cfg.py"] == "SECRET_DATABASE_URL_WITH_PASSWORD"


@pytest.mark.parametrize("size", [5 * 1024 * 1024, 15 * 1024 * 1024])
def test_a_secret_or_sentinel_after_the_old_scan_window_is_still_found(tmp_path, size):
    secret = b"x" * size + b"\nDATABASE_URL=postgresql://" + b"svc:" + b"hunter22hunter" + b"@db.example.test/x\n"
    (tmp_path / "big.py").write_bytes(secret)
    (tmp_path / "other.txt").write_bytes(b"y" * size + b"ZZLEAK-AFTER-WINDOW")
    result = da.audit(tmp_path, sentinels=da.load_sentinels(_sentinel_file(tmp_path, "ZZLEAK-AFTER-WINDOW")))
    codes = {(f["path"], f["code"]) for f in result["findings"]}
    assert ("big.py", "SECRET_DATABASE_URL_WITH_PASSWORD") in codes and ("other.txt", "SENTINEL_FOUND") in codes


def test_a_secret_straddling_a_read_boundary_is_found(tmp_path):
    boundary = da.CHUNK_BYTES
    body = b"a" * (boundary - 20) + b"postgresql://" + b"svc:" + b"hunter22hunter" + b"@db.example.test/x"
    (tmp_path / "edge.py").write_bytes(body)
    assert "SECRET_DATABASE_URL_WITH_PASSWORD" in _codes(tmp_path)


def _sentinel_file(directory, *tokens):
    path = directory.parent / f"sentinels-{abs(hash(tokens))}.txt"
    path.write_text("\n".join(tokens), encoding="utf-8")
    return str(path)


def test_sentinels_are_searched_as_utf16_too_and_an_empty_list_is_refused(tmp_path):
    (tmp_path / "w.txt").write_bytes("ZZLEAK-WIDE-1".encode("utf-16-le"))
    result = da.audit(tmp_path, sentinels=da.load_sentinels(_sentinel_file(tmp_path, "ZZLEAK-WIDE-1")))
    assert [f["code"] for f in result["findings"]] == ["SENTINEL_FOUND"] and result["sentinels_applied"] == 1
    with pytest.raises(da.Refused) as caught:
        da.load_sentinels(_sentinel_file(tmp_path, "short", ""))
    assert caught.value.code == "SENTINELS_EMPTY"


def test_the_documented_environment_template_is_not_a_finding(tmp_path):
    (tmp_path / ".env.example").write_text("APP_ENV=development\n")
    assert da.audit(tmp_path)["findings"] == []


@pytest.mark.parametrize(
    "code,payload",
    [
        ("SECRET_DATABASE_URL_WITH_PASSWORD", b"DATABASE_URL=" + b"postgresql://" + b"svc:" + b"hunter22hunter" + b"@db.example.test/x"),
        ("SECRET_PRIVATE_KEY_BLOCK", b"-----BEGIN " + b"PRIVATE KEY-----\nAAAA"),
        ("SECRET_SUPABASE_KEY", b"key = " + b"sb_secret_" + b"A1b2C3d4E5f6G7h8I9j0K1"),
        ("SECRET_JWT", b"t = " + b"eyJ" + b"a" * 20 + b".eyJ" + b"b" * 20 + b"." + b"c" * 20),
        ("SECRET_GOOGLE_CLIENT", b"s=" + b"GOCSPX-" + b"x" * 24),
    ],
)
def test_secret_shaped_values_are_found(tmp_path, code, payload):
    (tmp_path / "settings.py").write_bytes(payload)
    assert code in _codes(tmp_path)


def test_placeholders_without_a_password_are_not_secret_findings(tmp_path):
    (tmp_path / "doc.py").write_text("# DATABASE_URL=postgresql://user@host:5432/db\n")
    assert da.audit(tmp_path)["findings"] == []


def test_a_planted_sentinel_is_found_in_any_file(tmp_path):
    (tmp_path / "template.html").write_text("<p>ZZLEAK-4f9a1c</p>")
    assert da.audit(tmp_path)["findings"] == []
    assert _codes(tmp_path, sentinels=[b"ZZLEAK-4f9a1c"]) == ["SENTINEL_FOUND"]


def test_a_link_in_the_upload_is_a_finding_and_is_never_followed(tmp_path):
    target = tmp_path.parent / "elsewhere"
    target.mkdir(exist_ok=True)
    (target / "database.db").write_bytes(da.SQLITE_MAGIC)
    link = tmp_path / "docs_link"
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        # A Windows junction needs no privilege and is the alias a copy tool is most likely to leave.
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if os.name != "nt" or made.returncode != 0:
            pytest.skip("neither a symbolic link nor a junction can be created here")
    result = da.audit(tmp_path)
    assert [f["code"] for f in result["findings"]] == ["LINK_IN_UPLOAD"]


def test_a_file_alias_is_a_finding_and_is_never_read(tmp_path, monkeypatch):
    """Symbolic links to files need a privilege most Windows accounts lack, so the alias
    detection is exercised by naming the file a reparse point."""
    (tmp_path / "alias.bin").write_bytes(da.SQLITE_MAGIC)  # would be a signature finding if read
    monkeypatch.setattr(da, "_is_reparse_point", lambda path: path.name == "alias.bin")
    assert [f["code"] for f in da.audit(tmp_path)["findings"]] == ["LINK_IN_UPLOAD"]


def test_an_oversized_file_is_a_finding(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "MAX_FILE_BYTES", 10)
    (tmp_path / "big.bin").write_bytes(b"x" * 11)
    assert _codes(tmp_path) == ["FILE_TOO_LARGE"]


def test_the_report_never_echoes_a_path_unless_asked(tmp_path):
    secret_name = "Maria-Silva-historico.pdf"
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / secret_name).write_bytes(b"x")
    out = io.StringIO()
    assert da.main(["audit", "--dir", str(tmp_path)], out=out, err=io.StringIO()) == 1
    assert "Maria" not in out.getvalue() and "uploads" not in out.getvalue()
    report = json.loads(out.getvalue())
    assert report["result"] == "FINDINGS" and report["path_digests"] and "paths" not in report
    shown = io.StringIO()
    da.main(["audit", "--dir", str(tmp_path), "--show-paths"], out=shown, err=io.StringIO())
    assert secret_name in shown.getvalue()


def test_the_command_line_exit_codes(tmp_path):
    (tmp_path / "clean.txt").write_text("fine")
    assert da.main(["audit", "--dir", str(tmp_path)], out=io.StringIO(), err=io.StringIO()) == 0
    err = io.StringIO()
    assert da.main(["audit", "--dir", str(tmp_path / "missing")], out=io.StringIO(), err=err) == 1
    assert "DIRECTORY_MISSING" in err.getvalue()
    assert da.main(["audit"], out=io.StringIO(), err=io.StringIO()) == 2


# ---- export: the refusals a healthy repository never reaches, forced ---------------------------


class _Result:
    def __init__(self, returncode=0, stdout=b""):
        self.returncode, self.stdout = returncode, stdout


def _tar(*members: tuple[str, bytes]) -> bytes:
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _fake_git(monkeypatch, *, tree=None, archive=None):
    """Answer the tool's two git reads with scripted results (``rev-parse`` stays real)."""
    def fake(repo, *arguments, text=True, timeout=300):
        if arguments[0] == "ls-tree":
            return tree
        if arguments[0] == "archive":
            return archive
        raise AssertionError(arguments)

    monkeypatch.setattr(da, "_git", fake)


def _tree_entry(name: str, data: bytes) -> bytes:
    return f"100644 blob {da._blob_id(data)}\t{name}".encode() + b"\x00"


def test_a_failing_git_read_stops_the_export_with_a_fixed_code(tmp_path, monkeypatch):
    _fake_git(monkeypatch, tree=_Result(1))
    with pytest.raises(da.Refused) as caught:
        da.export(_head(), tmp_path / "a")
    assert caught.value.code == "ARCHIVE_FAILED"
    _fake_git(monkeypatch, tree=_Result(0, _tree_entry("main.py", b"x")), archive=_Result(1))
    with pytest.raises(da.Refused) as caught:
        da.export(_head(), tmp_path / "b")
    assert caught.value.code == "ARCHIVE_FAILED"
    assert not (tmp_path / "b").exists()


def test_a_commit_that_resolves_to_something_that_is_not_an_object_id_is_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(da.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "not-a-hash\n"})())
    with pytest.raises(da.Refused) as caught:
        da.export("HEAD", tmp_path / "out")
    assert caught.value.code == "COMMIT_NOT_FOUND"


def test_a_commit_with_nothing_on_the_allowlist_exports_nothing_and_says_so(tmp_path, monkeypatch):
    data = b"notes"
    _fake_git(monkeypatch, tree=_Result(0, _tree_entry("NOTES.txt", data)),
              archive=_Result(0, _tar(("NOTES.txt", data))))
    with pytest.raises(da.Refused) as caught:
        da.export(_head(), tmp_path / "out")
    assert caught.value.code == "NOTHING_EXPORTED"


def test_a_member_that_would_land_outside_the_directory_is_refused_even_if_the_allowlist_is_fooled(
        tmp_path, monkeypatch):
    data = b"payload"
    name = "app/../../evil.py"
    _fake_git(monkeypatch, tree=_Result(0, _tree_entry(name, data)), archive=_Result(0, _tar((name, data))))
    monkeypatch.setattr(da, "_allowed", lambda member: True)
    with pytest.raises(da.Refused) as caught:
        da.export(_head(), tmp_path / "out")
    assert caught.value.code == "ARCHIVE_MEMBER_UNSAFE"
    assert not (tmp_path / "evil.py").exists()


@pytest.mark.parametrize("encoding,bom", [
    ("utf-8", b""), ("utf-8", b"\xef\xbb\xbf"), ("utf-16", b""),  # utf-16 writes its own BOM
])
def test_a_sentinel_file_in_any_encoding_the_windows_shells_write_still_finds_its_first_token(
        tmp_path, encoding, bom):
    """PowerShell 5.1 ``Out-File -Encoding utf8`` writes a BOM, ``>`` writes UTF-16: neither may blind the audit."""
    upload = tmp_path / "upload"
    upload.mkdir()
    (upload / "a.txt").write_text("log ZZLEAK-4f9a1c tail", encoding="utf-8")
    (upload / "b.txt").write_bytes("ZZLEAK-SECOND".encode("utf-16-be"))
    sentinel_file = tmp_path / "sentinels.txt"
    sentinel_file.write_bytes(bom + "ZZLEAK-4f9a1c\nZZLEAK-SECOND\n".encode(encoding))
    sentinels = da.load_sentinels(str(sentinel_file))
    result = da.audit(upload, sentinels=sentinels)
    assert sorted(f["path"] for f in result["findings"] if f["code"] == "SENTINEL_FOUND") == ["a.txt", "b.txt"]
    assert result["sentinels_applied"] == 2


def test_an_undecodable_sentinel_file_is_refused_not_a_traceback(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe\x00")  # a UTF-16 BOM and a truncated code unit
    with pytest.raises(da.Refused) as caught:
        da.load_sentinels(str(bad))
    assert caught.value.code == "SENTINELS_UNREADABLE"
    bad.write_bytes(b"\x80\x81\x82 not utf-8")
    with pytest.raises(da.Refused) as caught:
        da.load_sentinels(str(bad))
    assert caught.value.code == "SENTINELS_UNREADABLE"


def test_a_missing_allowlisted_file_is_an_incomplete_export_not_a_success(tmp_path, monkeypatch):
    """An export-ignore attribute (or any sparse archive) must not silently ship a smaller tree."""
    data_a, data_b = b"print('a')\n", b"print('b')\n"
    tree = _tree_entry("app/a.py", data_a) + _tree_entry("app/b.py", data_b)
    _fake_git(monkeypatch, tree=_Result(0, tree), archive=_Result(0, _tar(("app/a.py", data_a))))
    with pytest.raises(da.Refused) as caught:
        da.export(_head(), tmp_path / "out")
    assert caught.value.code == "EXPORT_INCOMPLETE"


def test_a_committed_link_is_not_expected_in_the_export(tmp_path, monkeypatch):
    data = b"print('a')\n"
    tree = _tree_entry("app/a.py", data) + f"120000 blob {da._blob_id(b'a.py')}\tapp/link.py".encode() + b"\x00"
    _fake_git(monkeypatch, tree=_Result(0, tree), archive=_Result(0, _tar(("app/a.py", data))))
    assert da.export(_head(), tmp_path / "out")["files"] == 1


def test_a_utf16_sentinel_file_without_a_bom_is_refused_not_silently_misread(tmp_path):
    bad = tmp_path / "sentinels-utf16.txt"
    bad.write_bytes("ZZLEAK-NOBOM\n".encode("utf-16-le"))
    with pytest.raises(da.Refused) as caught:
        da.load_sentinels(str(bad))
    assert caught.value.code == "SENTINELS_UNREADABLE"


def test_a_refused_export_leaves_nothing_behind(tmp_path, monkeypatch):
    data_a, data_b = b"print('a')\n", b"print('b')\n"
    tree = _tree_entry("app/a.py", data_a) + _tree_entry("app/b.py", data_b)
    _fake_git(monkeypatch, tree=_Result(0, tree), archive=_Result(0, _tar(("app/a.py", data_a))))
    fresh = tmp_path / "fresh"
    with pytest.raises(da.Refused):
        da.export(_head(), fresh)
    assert not fresh.exists()  # a directory the export created is removed with what it wrote
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(da.Refused):
        da.export(_head(), empty)
    assert empty.is_dir() and list(empty.iterdir()) == []  # a directory the operator made stays, emptied
