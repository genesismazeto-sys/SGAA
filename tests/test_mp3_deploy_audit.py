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


# ---- verify: the upload directory IS the reviewed export (R3 remediation, finding 3) ----------------


@pytest.fixture
def fresh_export(tmp_path):
    out = tmp_path / "upload"
    da.export(_head(), out)
    return out


def test_an_untouched_export_verifies_identical_with_a_stable_tree_digest(fresh_export, tmp_path):
    first = da.verify(fresh_export, _head())
    assert first["result"] == "IDENTICAL" and first["commit"] == _head() and first["files"] > 50
    again = tmp_path / "again"
    da.export(_head(), again)
    assert da.verify(again, _head())["deploy_tree_sha256"] == first["deploy_tree_sha256"]


def test_the_platform_link_files_are_the_only_allowed_difference(fresh_export):
    vercel = fresh_export / ".vercel"
    vercel.mkdir()
    (vercel / "project.json").write_text('{"projectId":"prj_x"}')
    (vercel / "README.txt").write_text("linked")
    result = da.verify(fresh_export, _head())
    assert result["result"] == "IDENTICAL" and result["platform_metadata_files"] == 2


@pytest.mark.parametrize("tamper", [
    lambda d: (d / ".env.local").write_text("VERCEL_OIDC_TOKEN=x"),         # what `vercel link` also writes
    lambda d: (d / ".gitignore").write_text(".env*"),
    lambda d: (d / ".vercel").mkdir() or (d / ".vercel" / "output.json").write_text("{}"),
    lambda d: (d / "app" / "extra.py").write_text("print('added')"),          # an added deployable file
    lambda d: (d / "main.py").unlink(),                                        # a removed one
    lambda d: (d / "vercel.json").write_text((d / "vercel.json").read_text().replace("17 4", "17 15")),  # changed
    lambda d: (d / "main.py").write_bytes((d / "main.py").read_bytes().replace(b"\n", b"\r\n")),  # line endings
])
def test_any_added_removed_or_changed_file_refuses_the_upload(fresh_export, tamper):
    tamper(fresh_export)
    with pytest.raises(da.Refused) as caught:
        da.verify(fresh_export, _head())
    assert caught.value.code == "DEPLOY_TREE_DIFFERS"


def test_a_link_in_the_upload_directory_refuses_and_a_missing_directory_or_commit_is_refused(fresh_export, tmp_path):
    try:
        os.symlink(fresh_export / "main.py", fresh_export / "app" / "alias.py")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available to this account")
    with pytest.raises(da.Refused) as caught:
        da.verify(fresh_export, _head())
    assert caught.value.code == "LINK_IN_UPLOAD"


@pytest.mark.parametrize("alias", ["main.py", "templates"])  # a file alias, a directory junction
def test_an_alias_in_the_upload_directory_refuses_even_without_the_symlink_privilege(fresh_export, monkeypatch, alias):
    monkeypatch.setattr(da, "_is_reparse_point", lambda path: path.name == alias and path.parent.name == "upload")
    with pytest.raises(da.Refused) as caught:
        da.verify(fresh_export, _head())
    assert caught.value.code == "LINK_IN_UPLOAD"


def test_a_commit_with_nothing_deployable_verifies_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(da, "_committed_blobs", lambda resolved, repo: {"docs/readme.md": "0" * 40})
    (tmp_path / "empty").mkdir()
    with pytest.raises(da.Refused) as caught:
        da.verify(tmp_path / "empty", _head())
    assert caught.value.code == "NOTHING_EXPORTED"


def test_verify_refuses_a_missing_directory_an_unknown_commit_and_an_empty_one(tmp_path):
    with pytest.raises(da.Refused) as caught:
        da.verify(tmp_path / "missing", _head())
    assert caught.value.code == "DIRECTORY_MISSING"
    (tmp_path / "empty").mkdir()
    with pytest.raises(da.Refused) as caught:
        da.verify(tmp_path / "empty", "0" * 40)
    assert caught.value.code == "COMMIT_NOT_FOUND"
    with pytest.raises(da.Refused) as caught:
        da.verify(tmp_path / "empty", _head())
    assert caught.value.code == "DEPLOY_TREE_DIFFERS"  # every committed file is missing


def test_the_command_line_reports_the_identity_or_the_difference_by_counts_only(fresh_export):
    out = io.StringIO()
    assert da.main(["verify", "--dir", str(fresh_export), "--commit", _head()], out=out, err=io.StringIO()) == 0
    assert json.loads(out.getvalue())["result"] == "IDENTICAL"
    (fresh_export / "app" / "student-file.py").write_text("x")
    err = io.StringIO()
    assert da.main(["verify", "--dir", str(fresh_export), "--commit", _head()], out=io.StringIO(), err=err) == 1
    assert "DEPLOY_TREE_DIFFERS (added=1 removed=0 changed=0)" in err.getvalue()
    assert "student-file" not in err.getvalue()


# ---- deploy and promote: one controlled operation, bound to what the platform received (MP-3 A17) ----------


class _Platform:
    """A scripted platform: it 'receives' the directory the tool uploads, naming files as the real one does."""

    def __init__(self, *, tamper=None, state="READY", alias_follows=True):
        from tests.mp3_ledger_support import PROJECT_ID

        self.project_id = PROJECT_ID
        self.tamper, self.state, self.alias_follows = tamper, state, alias_follows
        self.received: dict[str, dict] = {}
        self.removed: list[str] = []
        self.promoted: list[str] = []
        self.envs: list[dict] = []
        self.alias = None

    def deploy(self, directory, env):
        from tools import vercel_provider

        self.envs.append(dict(env))
        if self.tamper:
            self.tamper(Path(directory))  # something changed the directory after the verification
        identifier = f"dpl_{len(self.received) + 1:024d}"
        files = {}
        for current, _dirs, names in os.walk(directory):
            for name in names:
                full = Path(current) / name
                files[full.relative_to(directory).as_posix()] = vercel_provider.content_sha1(full.read_bytes())
        self.received[identifier] = files
        return self.deployment(identifier)

    def deployment(self, identifier):
        return {"id": identifier, "url": identifier.lower() + ".example.test", "state": self.state,
                "target": "production", "project": self.project_id, "aliased": False}

    def files(self, identifier):
        return dict(self.received[identifier])

    def promote(self, identifier):
        self.promoted.append(identifier)
        if self.alias_follows:
            self.alias = identifier

    def alias_target(self, host):
        return self.alias

    def remove(self, identifier):
        self.removed.append(identifier)


_HEAD_CODE: list[str] = []


def _code_of_head() -> str:
    """The code identity of HEAD's export: what an honest deployment of it announces."""
    if not _HEAD_CODE:
        from app import hosting

        blobs = {path: blob for path, blob in da._committed_blobs(_head(), REPO_ROOT).items() if da._allowed(path)}
        _HEAD_CODE.append(hosting.code_sha256(blobs))
    return _HEAD_CODE[0]


@pytest.fixture
def at_c8(tmp_path, monkeypatch):
    """A ledger at C8 whose rehearsed commit is this repository's HEAD; the address probes answer as told."""
    import time
    from datetime import datetime, timezone

    from tests import mp3_ledger_support as ls
    from tools import cutover_ledger as ledger

    ls.install_clock(monkeypatch, datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc))
    directory = tmp_path / "ledger"
    ledger.init(directory)
    for index, gate in enumerate(ls.ALL_GATES):
        ledger.grant(directory, gate, f"m-{index}")
    ls.drive(directory, "C8", ls.FakeObserver(), {"C0": {"commit": _head()}})
    answers = {"admission": "closed", "code": None}
    monkeypatch.setattr(da, "_observed", lambda url, *, allow_insecure: (
        answers["admission"], _code_of_head() if answers["code"] is None else answers["code"]))
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    return {"directory": directory, "answers": answers}


def _deployments(directory):
    from tools import cutover_ledger as ledger

    return [e for e in ledger.read_ledger(directory) if e["type"] == "deployment"]


def test_a_deployment_is_recorded_only_after_the_platform_confirms_it_received_the_verified_export(at_c8):
    from tools import vercel_provider

    platform = _Platform()
    result = da.deploy(_head(), ledger_dir=at_c8["directory"], provider=platform, admission="operator")
    [entry] = _deployments(at_c8["directory"])
    assert result["result"] == "DEPLOYED" and entry["deployment_id"] == result["deployment_id"]
    assert entry["commit"] == _head() and entry["code_sha256"] == _code_of_head() == result["code_sha256"]
    assert entry["admission"] == "OPERATOR" and entry["observed_admission"] == "CLOSED"
    assert entry["files_sha256"] == vercel_provider.files_sha256(platform.received[entry["deployment_id"]])
    assert platform.envs == [{"SGAA_ADMISSION": "operator"}] and platform.removed == []


@pytest.mark.parametrize("tamper", [
    lambda d: (d / "main.py").write_bytes((d / "main.py").read_bytes() + b"\n# changed after verify\n"),
    lambda d: (d / "app" / "extra_after_verify.py").write_text("x = 1\n"),
    lambda d: (d / "presets_data.json").unlink(),
])
def test_anything_that_changed_between_the_verification_and_the_upload_is_never_served(at_c8, tamper):
    platform = _Platform(tamper=tamper)
    with pytest.raises(da.Refused) as caught:
        da.deploy(_head(), ledger_dir=at_c8["directory"], provider=platform, admission="operator")
    assert caught.value.code == "DEPLOYED_FILES_DIFFER"
    assert platform.removed == list(platform.received) and _deployments(at_c8["directory"]) == []


@pytest.mark.parametrize("answers,code", [
    ({"code": "9" * 64}, "DEPLOYMENT_CODE_NOT_OBSERVED"),     # it runs other code than the export's
    ({"code": ""}, "DEPLOYMENT_CODE_NOT_OBSERVED"),           # a protection page, or nothing announced
    ({"admission": "open"}, "LEDGER_DEPLOYMENT_NOT_CLOSED"),  # an operator deployment that admits users
    ({"admission": "unknown"}, "LEDGER_DEPLOYMENT_NOT_CLOSED"),
])
def test_a_deployment_that_does_not_run_and_refuse_as_recorded_is_removed_not_recorded(at_c8, answers, code):
    at_c8["answers"].update(answers)
    platform = _Platform()
    with pytest.raises(da.Refused) as caught:
        da.deploy(_head(), ledger_dir=at_c8["directory"], provider=platform, admission="operator")
    assert caught.value.code == code
    assert platform.removed == list(platform.received) and _deployments(at_c8["directory"]) == []


def test_nothing_is_uploaded_before_the_ledger_allows_the_deployment(tmp_path):
    from tools import cutover_ledger as ledger

    directory = tmp_path / "ledger"
    ledger.init(directory)
    platform = _Platform()
    for admission, kwargs, code in (("operator", {}, "LEDGER_OUT_OF_ORDER"),
                                    ("open", {"opening_reference": "a" * 64}, "LEDGER_OUT_OF_ORDER"),
                                    ("closed", {}, "ADMISSION_INVALID")):
        with pytest.raises(da.Refused) as caught:
            da.deploy(_head(), ledger_dir=directory, provider=platform, admission=admission, **kwargs)
        assert caught.value.code == code
    assert platform.received == {}


def test_an_open_deployment_needs_the_recorded_reference(at_c8):
    platform = _Platform()
    with pytest.raises(da.Refused) as caught:
        da.deploy(_head(), ledger_dir=at_c8["directory"], provider=platform, admission="open",
                  opening_reference="a" * 64)
    assert caught.value.code == "LEDGER_OPEN_WITHOUT_THE_REFERENCE" and platform.received == {}


def test_a_sentinel_in_the_commit_stops_the_deployment_before_the_upload(at_c8):
    platform = _Platform()
    token = b"from __future__"  # present in committed application files: a planted sentinel's stand-in
    with pytest.raises(da.Refused) as caught:
        da.deploy(_head(), ledger_dir=at_c8["directory"], provider=platform, admission="operator", sentinels=[token])
    assert caught.value.code == "BUNDLE_AUDIT_FINDINGS" and platform.received == {}


def test_a_deployment_the_platform_did_not_finish_is_removed(at_c8):
    platform = _Platform(state="ERROR")
    with pytest.raises(da.Refused) as caught:
        da.deploy(_head(), ledger_dir=at_c8["directory"], provider=platform, admission="operator")
    assert caught.value.code == "DEPLOYMENT_NOT_READY" and platform.removed == list(platform.received)


def test_promotion_points_the_public_address_at_a_recorded_deployment_and_records_what_it_serves(at_c8, monkeypatch):
    from tools import hosted_smoke

    platform = _Platform()
    deployed = da.deploy(_head(), ledger_dir=at_c8["directory"], provider=platform, admission="operator")
    served = {"code": _code_of_head()}
    monkeypatch.setattr(hosted_smoke, "probe_code", lambda url, allow_insecure=False: served["code"])
    public = "https://sgaa.example.test"
    with pytest.raises(da.Refused) as caught:
        da.promote("dpl_" + "Z" * 24, ledger_dir=at_c8["directory"], provider=platform, public_url=public)
    assert caught.value.code == "LEDGER_DEPLOYMENT_NOT_RECORDED" and platform.promoted == []
    identifier = deployed["deployment_id"]
    original = platform.received[identifier]
    platform.received[identifier] = {**original, "main.py": "0" * 40}  # the platform now holds other files
    with pytest.raises(da.Refused) as caught:
        da.promote(identifier, ledger_dir=at_c8["directory"], provider=platform, public_url=public)
    assert caught.value.code == "DEPLOYMENT_NOT_THE_RECORDED_ONE" and platform.promoted == []
    platform.received[identifier] = original
    from tools import cutover_ledger

    def reconciled(provider):  # the promotion stayed unresolved: `reconcile` observes the alias and the platform
        observer = type("Platform", (), {
            "alias_deployment": lambda self: provider.alias_target("sgaa.example.test"),
            "provider_deployments": lambda self: [{"id": key, "url": "", "state": provider.state}
                                                  for key in provider.received if key not in provider.removed]})()
        try:
            return cutover_ledger.reconcile(at_c8["directory"], observer=observer)["result"]
        except cutover_ledger.Refused as refusal:
            return refusal.code

    served["code"] = "9" * 64  # the address serves something else
    with pytest.raises(da.Refused) as caught:
        da.promote(identifier, ledger_dir=at_c8["directory"], provider=platform, public_url=public)
    assert caught.value.code == "LEDGER_DEPLOYMENT_NOT_THE_RECORDED_ONE"
    with pytest.raises(da.Refused) as caught:  # nothing proceeds while its outcome is unknown
        da.promote(identifier, ledger_dir=at_c8["directory"], provider=platform, public_url=public)
    assert caught.value.code == "LEDGER_OPERATION_UNRESOLVED"
    assert reconciled(platform) == "COMMITTED"  # the alias did move
    served["code"] = _code_of_head()
    stuck = _Platform(alias_follows=False)
    stuck.received = platform.received
    with pytest.raises(da.Refused) as caught:
        da.promote(identifier, ledger_dir=at_c8["directory"], provider=stuck, public_url=public)
    assert caught.value.code == "LEDGER_ALIAS_NOT_THE_DEPLOYMENT"
    assert reconciled(stuck) == "PROMOTION_PENDING"  # accepted, not applied yet: it may still land
    stuck.alias = identifier  # the platform applied it late
    assert reconciled(stuck) == "COMMITTED"
    result = da.promote(identifier, ledger_dir=at_c8["directory"], provider=platform, public_url=public)
    assert result["result"] == "PROMOTED" and result["public_host_sha256"] == hosted_smoke.host_digest(public)


def test_the_command_line_deploys_and_promotes_only_through_the_named_project(tmp_path):
    for args in (["deploy", "--ledger-dir", str(tmp_path), "--vercel-team", "ej-883a", "--vercel-project", "prj_x",
                  "--commit", "HEAD", "--admission", "operator"],
                 ["promote", "--ledger-dir", str(tmp_path), "--vercel-team", "team_" + "T" * 24,
                  "--vercel-project", "sgaa-mp3", "--deployment", "dpl_x", "--public-url", "https://x"]):
        err = io.StringIO()
        assert da.main(args, out=io.StringIO(), err=err) == 1
        assert "PROVIDER_PROJECT_INVALID" in err.getvalue()
    assert da.main(["deploy", "--ledger-dir", str(tmp_path)], out=io.StringIO(), err=io.StringIO()) == 2


# ---- the rereview of 1245bf2: platform acts serialized with the ledger and reserved before they happen --------
# Adapted from the independent reviewer's reproductions (each failed on 1245bf2): the ledger and the deploy /
# promote control flow are real; the Git export, the provider and the HTTP observations are scripted.


@pytest.fixture
def at_ponr(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from tests import mp3_ledger_support as ls
    from tools import cutover_ledger

    ls.install_clock(monkeypatch, datetime(2026, 11, 1, 8, tzinfo=timezone.utc))
    directory = tmp_path / "ledger"
    cutover_ledger.init(directory)
    for index, gate in enumerate(ls.ALL_GATES):
        cutover_ledger.grant(directory, gate, f"REVIEW-{index}")
    observer = ls.FakeObserver()
    ls.drive(directory, "C13", observer)
    return directory, observer


def _scripted_export(monkeypatch, code):
    from app import hosting
    from tests import mp3_ledger_support as ls
    from tools import hosted_smoke, vercel_provider as vp

    blobs = {"app/synthetic.py": hosting.git_blob_id(b"synthetic")}
    files = {"app/synthetic.py": vp.content_sha1(b"synthetic")}
    monkeypatch.setattr(da, "_resolve_commit", lambda *args: ls.OTHER_COMMIT)
    monkeypatch.setattr(da, "export", lambda *args, **kwargs: None)
    monkeypatch.setattr(da, "audit", lambda *args, **kwargs: {"findings": []})
    monkeypatch.setattr(da, "verify", lambda *args, **kwargs: {"deploy_tree_sha256": da.tree_digest(blobs), "files": 1})
    monkeypatch.setattr(da, "_exported_files", lambda *args: (blobs, files))
    monkeypatch.setattr(hosting, "code_sha256", lambda found: code)
    monkeypatch.setattr(hosted_smoke, "probe_code", lambda *args, **kwargs: code)
    monkeypatch.setattr(hosted_smoke, "probe_admission", lambda *args, **kwargs: "open")
    monkeypatch.setattr(hosted_smoke, "host_digest", lambda address: ls.PUBLIC_HOST)
    return files


def test_m1_no_other_ledger_act_interleaves_a_promotion_between_its_precheck_and_the_alias_move(at_ponr, monkeypatch):
    """Rereview of 1245bf2 M1: while `promote` holds the ledger, another act (a supersession here) is refused
    LEDGER_BUSY; the only act open when the alias moves is the promotion itself, written before it."""
    from tests import mp3_ledger_support as ls
    from tools import cutover_ledger, hosted_smoke, vercel_provider as vp

    directory, observer = at_ponr
    observer.alias = ls.DEPLOYMENT
    seen = {}

    class Provider:
        alias = ls.DEPLOYMENT

        def deployment(self, identity):
            with pytest.raises(cutover_ledger.Refused) as caught:  # another command, started meanwhile
                cutover_ledger.supersede(directory, observer=observer)
            seen["interleaved"] = caught.value.code
            return {"state": "READY"}

        def files(self, identity):
            return {"app/synthetic.py": "a" * 40}

        def promote(self, identity):
            pending = cutover_ledger._unresolved(cutover_ledger.read_ledger(directory))
            seen["open_when_promoted"] = pending["type"] if pending else None
            self.alias = identity

        def alias_target(self, host):
            return self.alias

    monkeypatch.setattr(vp, "files_sha256", lambda files: ls.FILES)
    monkeypatch.setattr(hosted_smoke, "probe_code", lambda *args, **kwargs: ls.CODE)
    monkeypatch.setattr(hosted_smoke, "host_digest", lambda address: ls.PUBLIC_HOST)
    supersessions = len(cutover_ledger._summary(cutover_ledger.read_ledger(directory))["supersessions"])
    result = da.promote(ls.LIFT, ledger_dir=directory, provider=Provider(), public_url="https://synthetic.invalid")
    assert seen == {"interleaved": "LEDGER_BUSY", "open_when_promoted": "promotion"}
    assert result["result"] == "PROMOTED" and cutover_ledger.status(directory)["unresolved_operation"] is None
    assert len(cutover_ledger._summary(cutover_ledger.read_ledger(directory))["supersessions"]) == supersessions


def test_m2_a_gf1_is_reserved_before_the_upload_so_an_overlapping_deploy_never_reaches_the_platform(
        at_ponr, monkeypatch):
    from tests import mp3_ledger_support as ls
    from tools import cutover_ledger

    directory, observer = at_ponr
    reference = cutover_ledger.status(directory)["opening_reference"]
    cutover_ledger.grant(directory, "GF1", "REVIEW-GF1-ONE")
    files = _scripted_export(monkeypatch, ls.OTHER_CODE)  # a forward fix: a code not yet authorized
    ready, nested = [], {}

    class Provider:
        project_id = ls.PROJECT_ID

        def deploy(self, upload, env):
            if not nested:  # a second command overlapping at the upload
                with pytest.raises(da.Refused) as caught:
                    da.deploy(ls.OTHER_COMMIT, ledger_dir=directory, provider=self, admission="open",
                              opening_reference=reference, forward_fix_ref="REVIEW-GF1-ONE")
                nested["code"] = caught.value.code
            identity = "dpl_" + "X" * 24
            ready.append(identity)
            return {"id": identity, "state": "READY", "target": "production", "url": "synthetic.invalid",
                    "aliased": False}

        def files(self, identity):
            return files

        def remove(self, identity):
            raise AssertionError("nothing to remove")

    da.deploy(ls.OTHER_COMMIT, ledger_dir=directory, provider=Provider(), admission="open",
              opening_reference=reference, forward_fix_ref="REVIEW-GF1-ONE")
    assert nested["code"] in {"LEDGER_BUSY", "LEDGER_OPERATION_UNRESOLVED"} and ready == ["dpl_" + "X" * 24]
    with pytest.raises(da.Refused) as caught:  # the grant is spent: refused before any upload
        da.deploy(ls.OTHER_COMMIT, ledger_dir=directory, provider=Provider(), admission="open",
                  opening_reference=reference, forward_fix_ref="REVIEW-GF1-ONE")
    assert caught.value.code == "LEDGER_FORWARD_FIX_GATE_REQUIRED" and len(ready) == 1


def test_m2_a_lost_upload_answer_blocks_everything_until_the_platform_is_reconciled(at_ponr, monkeypatch):
    from tests import mp3_ledger_support as ls
    from tools import cutover_ledger, vercel_provider as vp

    directory, observer = at_ponr
    reference = cutover_ledger.status(directory)["opening_reference"]
    cutover_ledger.grant(directory, "GF1", "REVIEW-GF1-LOST")
    files = _scripted_export(monkeypatch, ls.OTHER_CODE)

    class Provider:
        project_id = ls.PROJECT_ID
        ready = []

        def deploy(self, upload, env):
            identity = "dpl_" + ("X" if not self.ready else "Y") * 24
            self.ready.append(identity)
            observer.platform[identity] = {"url": "https://x.invalid", "state": "READY", "files": ls.FILES,
                                           "admission": "open", "code": ls.OTHER_CODE}
            if len(self.ready) == 1:  # the platform made it; its answer was lost
                raise vp.Refused("PROVIDER_UNAVAILABLE")
            return {"id": identity, "state": "READY", "target": "production", "url": "synthetic.invalid",
                    "aliased": False}

        def files(self, identity):
            return files

        def remove(self, identity):
            raise AssertionError("no identity was returned")

    provider = Provider()
    with pytest.raises(da.Refused) as caught:
        da.deploy(ls.OTHER_COMMIT, ledger_dir=directory, provider=provider, admission="open",
                  opening_reference=reference, forward_fix_ref="REVIEW-GF1-LOST")
    assert caught.value.code == "PROVIDER_UNAVAILABLE"
    pending = cutover_ledger.status(directory)["unresolved_operation"]
    assert pending is not None  # the attempt stays open
    with pytest.raises(da.Refused) as caught:  # no retry, no other act, until reconciled
        da.deploy(ls.OTHER_COMMIT, ledger_dir=directory, provider=provider, admission="open",
                  opening_reference=reference, forward_fix_ref="REVIEW-GF1-LOST")
    assert caught.value.code == "LEDGER_OPERATION_UNRESOLVED" and len(provider.ready) == 1
    with pytest.raises(cutover_ledger.Refused) as caught:  # the platform holds what the ledger never recorded
        cutover_ledger.reconcile(directory, observer=observer)
    assert caught.value.code == "UNRECORDED_DEPLOYMENT"
    del observer.platform["dpl_" + "X" * 24]  # removed by hand (`vercel remove`)
    outcome = cutover_ledger.reconcile(directory, observer=observer)
    assert outcome["of"] == pending and outcome["result"] == "ABORTED"
    with pytest.raises(da.Refused) as caught:  # the attempt consumed its GF1, whatever its outcome
        da.deploy(ls.OTHER_COMMIT, ledger_dir=directory, provider=provider, admission="open",
                  opening_reference=reference, forward_fix_ref="REVIEW-GF1-LOST")
    assert caught.value.code == "LEDGER_FORWARD_FIX_GATE_REQUIRED" and len(provider.ready) == 1
    cutover_ledger.grant(directory, "GF1", "REVIEW-GF1-NEXT")
    with pytest.raises(da.Refused) as caught:  # a copy of that upload may still appear: its code never opens
        da.deploy(ls.OTHER_COMMIT, ledger_dir=directory, provider=provider, admission="open",
                  opening_reference=reference, forward_fix_ref="REVIEW-GF1-NEXT")
    assert caught.value.code == "LEDGER_CODE_OF_AN_UNPROVEN_UPLOAD" and len(provider.ready) == 1
    _scripted_export(monkeypatch, "8" * 64)  # another commit: another code
    done = da.deploy(ls.OTHER_COMMIT, ledger_dir=directory, provider=provider, admission="open",
                     opening_reference=reference, forward_fix_ref="REVIEW-GF1-NEXT")
    assert done["deployment_id"] == "dpl_" + "Y" * 24 and cutover_ledger.status(directory)["unresolved_operation"] is None


def test_m2_after_the_ponr_an_authorized_code_is_never_redeployed_open(at_ponr, monkeypatch):
    """An open upload of the authorized code would admit users at its own address before it is recorded."""
    from tests import mp3_ledger_support as ls
    from tools import cutover_ledger

    directory, observer = at_ponr
    reference = cutover_ledger.status(directory)["opening_reference"]
    cutover_ledger.grant(directory, "GF1", "REVIEW-GF1-SAME")
    _scripted_export(monkeypatch, ls.CODE)  # the code the ledger authorizes now

    class Provider:
        project_id = ls.PROJECT_ID

        def deploy(self, upload, env):
            raise AssertionError("nothing may be uploaded")

    with pytest.raises(da.Refused) as caught:
        da.deploy(ls.OTHER_COMMIT, ledger_dir=directory, provider=Provider(), admission="open",
                  opening_reference=reference, forward_fix_ref="REVIEW-GF1-SAME")
    assert caught.value.code == "LEDGER_AUTHORIZED_CODE_NOT_REDEPLOYED_OPEN"
    assert cutover_ledger.status(directory)["unresolved_operation"] is None  # refused before the reservation
