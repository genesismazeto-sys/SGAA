import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from tests.conftest import _remove_owned_runtime_root, assert_canonical_root_unchanged


CANONICAL_PYTHON = sys.executable
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = Path(TESTS_DIR).parent


# ═══════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════


def _git_root():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        return result.stdout.decode("utf-8").strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _disposable_repo_copy(dest):
    git_root = _git_root()
    if git_root is None:
        pytest.skip("Not inside a git repository")
    dest_path = Path(dest) / "SGAA_clean_baseline"

    result = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        check=True,
        cwd=git_root,
    )
    tracked = [f for f in result.stdout.decode("utf-8").strip().split("\0") if f]
    for f in tracked:
        src = os.path.join(git_root, f)
        dst = os.path.join(str(dest_path), f)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

    return dest_path


def _fingerprint_tree(path):
    """Deterministic fingerprint with path type, directory entries, file sizes/hashes."""
    path = Path(path)
    if not path.exists():
        return None
    if path.is_file():
        st = path.stat()
        return {
            "type": "file",
            "size": st.st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    result: dict[str, dict] = {}
    for dirpath, dirnames, filenames in sorted(os.walk(str(path))):
        for dn in sorted(dirnames):
            dpath = Path(dirpath) / dn
            rel = str(dpath.relative_to(path)).replace(os.sep, "/")
            result[rel] = {"type": "dir"}
        for fn in sorted(filenames):
            fpath = Path(dirpath) / fn
            rel = str(fpath.relative_to(path)).replace(os.sep, "/")
            st = fpath.stat()
            result[rel] = {
                "type": "file",
                "size": st.st_size,
                "sha256": hashlib.sha256(fpath.read_bytes()).hexdigest(),
            }
    return result


def _fingerprint_scopes(root, scopes):
    fp = {}
    for name in scopes:
        fp[name] = _fingerprint_tree(Path(root) / name)
    return fp


# ═══════════════════════════════════════════════════════════════════
# Requirement 1 — sentinel survival (collection + execution)
# ═══════════════════════════════════════════════════════════════════

SENTINEL_SCOPES = (
    "uploads",
    "documentos_alunos",
    "backups",
    "logs",
    "database.db",
    ".pytest_cache",
)


class TestSentinelSurvival:
    SENTINEL_BYTES = b"SGAATEST-SENTINEL-CANARY-v1"

    @staticmethod
    def _seed_sentinels(repo):
        for name in SENTINEL_SCOPES:
            target = repo / name
            if name == "database.db":
                target.write_bytes(TestSentinelSurvival.SENTINEL_BYTES)
            elif name == ".pytest_cache":
                target.mkdir(parents=True, exist_ok=True)
                (target / "canary.txt").write_bytes(TestSentinelSurvival.SENTINEL_BYTES)
            else:
                target.mkdir(parents=True, exist_ok=True)
                (target / "canary.txt").write_bytes(TestSentinelSurvival.SENTINEL_BYTES)

    def test_sentinels_survive_collection_and_probe(self, tmp_path):
        repo_copy = _disposable_repo_copy(tmp_path)
        self._seed_sentinels(repo_copy)
        before = _fingerprint_scopes(repo_copy, SENTINEL_SCOPES)

        # Stage 1: --collect-only
        p1 = subprocess.run(
            [CANONICAL_PYTHON, "-B", "-m", "pytest", "--collect-only", "-q"],
            capture_output=True,
            timeout=120,
            cwd=str(repo_copy),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert p1.returncode == 0, f"collect-only failed: {p1.stderr.decode()}"

        after_collect = _fingerprint_scopes(repo_copy, SENTINEL_SCOPES)
        for key in before:
            assert before[key] == after_collect.get(key), (
                f"Scope {key} changed after --collect-only.\n"
                f"before={before[key]}\nafter ={after_collect.get(key)}"
            )

        # Stage 2: write a probe test with cache routing proof
        probe = repo_copy / "tests" / "test_probe.py"
        probe.write_text(textwrap.dedent("""\
import os
from pathlib import Path

def test_cache_routes_to_runtime_root(request):
    cachedir = request.config.cache._cachedir.resolve()
    expected = Path(os.environ["APP_DATABASE"]).resolve().parent / ".pytest_cache"
    assert cachedir == expected, (
        f"Cache dir mismatch: {cachedir} != {expected}"
    )
"""))

        p2 = subprocess.run(
            [CANONICAL_PYTHON, "-B", "-m", "pytest", "tests/test_probe.py", "-q"],
            capture_output=True,
            timeout=120,
            cwd=str(repo_copy),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert p2.returncode == 0, (
            f"probe execution failed.\n"
            f"stdout: {p2.stdout.decode()}\n"
            f"stderr: {p2.stderr.decode()}"
        )

        after_exec = _fingerprint_scopes(repo_copy, SENTINEL_SCOPES)
        for key in before:
            assert before[key] == after_exec.get(key), (
                f"Scope {key} changed after probe execution.\n"
                f"before={before[key]}\nafter ={after_exec.get(key)}"
            )


# ═══════════════════════════════════════════════════════════════════
# Requirement 2 — subprocess import main creates paths in runtime root
# ═══════════════════════════════════════════════════════════════════

class TestSubprocessImportMain:
    SCRIPT = textwrap.dedent("""
import logging, os, shutil, sys
from pathlib import Path
sys.path.insert(0, PROJECT_ROOT_PLACEHOLDER)

main = None
RUNTIME_ROOT = Path(RUNTIME_PLACEHOLDER)
os.environ["APP_DATABASE"] = str(RUNTIME_ROOT / ".pytest_app_database.db")
os.environ["APP_UPLOAD_FOLDER"] = str(RUNTIME_ROOT / "uploads")
os.environ["APP_DOCUMENTOS_ALUNOS_FOLDER"] = str(RUNTIME_ROOT / "documentos_alunos")
os.environ["APP_LOCAL_BACKUP_DIR"] = str(RUNTIME_ROOT / "backups" / "local")
os.environ["APP_CLOUD_BACKUP_DIR"] = str(RUNTIME_ROOT / "backups" / "cloud")
os.environ["APP_LOG_DIR"] = str(RUNTIME_ROOT / "logs")

try:
    import main
    assert os.environ["APP_DATABASE"] == str(RUNTIME_ROOT / ".pytest_app_database.db")
    assert main.app.config["DATABASE_PATH"] == str(RUNTIME_ROOT / ".pytest_app_database.db")
    assert main.app.config["UPLOAD_FOLDER"] == str(RUNTIME_ROOT / "uploads")
    assert main.app.config["DOCUMENTOS_ALUNOS_FOLDER"] == str(RUNTIME_ROOT / "documentos_alunos")
finally:
    if main is not None:
        for lg in [logging.getLogger(), logging.getLogger('app'), getattr(main, 'logger', None)]:
            if lg is not None:
                for handler in list(lg.handlers):
                    if isinstance(handler, logging.FileHandler):
                        handler.close()
    if RUNTIME_ROOT.exists():
        shutil.rmtree(str(RUNTIME_ROOT))
""")

    def test_import_main_uses_runtime_root(self, tmp_path):
        runtime = tmp_path / "sub_import_runtime"
        runtime.mkdir()
        script = tmp_path / "_import_test.py"
        content = self.SCRIPT.replace("PROJECT_ROOT_PLACEHOLDER", repr(str(PROJECT_ROOT)))
        content = content.replace("RUNTIME_PLACEHOLDER", repr(str(runtime)))
        script.write_text(content)
        result = subprocess.run(
            [CANONICAL_PYTHON, "-B", str(script)],
            capture_output=True,
            timeout=120,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, (
            f"Subprocess import main failed.\n"
            f"stdout: {result.stdout.decode()}\n"
            f"stderr: {result.stderr.decode()}"
        )


# ═══════════════════════════════════════════════════════════════════
# Requirement 3 — APP_UPLOAD_FOLDER honored by create_app
# ═══════════════════════════════════════════════════════════════════

class TestAppUploadFolder:
    def test_upload_folder_env_var_honored(self, monkeypatch, tmp_path):
        custom = str(tmp_path / "custom_uploads")
        monkeypatch.setenv("APP_UPLOAD_FOLDER", custom)
        monkeypatch.setenv("APP_ENV", "testing")
        monkeypatch.setenv("APP_SECRET_KEY", "x" * 32)
        from app import create_app
        app = create_app(register_presets_blueprint=False, register_aluno_blueprint=False)
        assert app.config["UPLOAD_FOLDER"] == custom

    def test_upload_folder_default_in_disposable_child(self, tmp_path):
        repo_copy = _disposable_repo_copy(tmp_path)
        script = repo_copy / "_upload_default_test.py"
        script.write_text(textwrap.dedent("""\
import logging, os, shutil, tempfile

RUNTIME = tempfile.mkdtemp()
os.environ.pop("APP_UPLOAD_FOLDER", None)
os.environ["APP_ENV"] = "testing"
os.environ["APP_SECRET_KEY"] = "x" * 32
os.environ["APP_DOCUMENTOS_ALUNOS_FOLDER"] = os.path.join(RUNTIME, "docs")
os.environ["APP_LOG_DIR"] = os.path.join(RUNTIME, "logs")
os.environ["APP_DATABASE"] = os.path.join(RUNTIME, "db.db")

try:
    from app import create_app
    app = create_app(register_presets_blueprint=False, register_aluno_blueprint=False)
    expected = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    assert app.config["UPLOAD_FOLDER"] == expected, (
        f"Default mismatch: {app.config['UPLOAD_FOLDER']} != {expected}"
    )
    print("OK")
finally:
    for handler in list(logging.getLogger('app').handlers):
        if isinstance(handler, logging.FileHandler):
            handler.close()
    shutil.rmtree(RUNTIME)
"""))
        result = subprocess.run(
            [CANONICAL_PYTHON, "-B", str(script)],
            capture_output=True,
            timeout=60,
            cwd=str(repo_copy),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert result.returncode == 0, (
            f"Default UPLOAD_FOLDER test failed.\n"
            f"stdout: {result.stdout.decode()}\n"
            f"stderr: {result.stderr.decode()}"
        )


# ═══════════════════════════════════════════════════════════════════
# Requirement 4 — main.py does not overwrite factory-configured upload path
# ═══════════════════════════════════════════════════════════════════

class TestMainNoOverwrite:
    SCRIPT = textwrap.dedent("""
import logging, os, shutil, sys
from pathlib import Path
sys.path.insert(0, PROJECT_ROOT_PLACEHOLDER)

main = None
RUNTIME_ROOT = Path(RUNTIME_PLACEHOLDER)
os.environ["APP_UPLOAD_FOLDER"] = str(RUNTIME_ROOT / "uploads")
os.environ["APP_ENV"] = "testing"
os.environ["APP_SECRET_KEY"] = "x" * 32
os.environ["APP_LOG_DIR"] = str(RUNTIME_ROOT / "logs")
os.environ["APP_DATABASE"] = str(RUNTIME_ROOT / "db.db")
os.environ["APP_DOCUMENTOS_ALUNOS_FOLDER"] = str(RUNTIME_ROOT / "docs")
os.environ["APP_LOCAL_BACKUP_DIR"] = str(RUNTIME_ROOT / "backups" / "local")
os.environ["APP_CLOUD_BACKUP_DIR"] = str(RUNTIME_ROOT / "backups" / "cloud")

try:
    import main
    assert main.app.config["UPLOAD_FOLDER"] == str(RUNTIME_ROOT / "uploads"), (
        "UPLOAD_FOLDER was overwritten to " + str(main.app.config['UPLOAD_FOLDER'])
    )
finally:
    if main is not None:
        for lg in [logging.getLogger(), logging.getLogger('app'), getattr(main, 'logger', None)]:
            if lg is not None:
                for handler in list(lg.handlers):
                    if isinstance(handler, logging.FileHandler):
                        handler.close()
    if RUNTIME_ROOT.exists():
        shutil.rmtree(str(RUNTIME_ROOT))
""")

    def test_import_main_preserves_upload_folder(self, tmp_path):
        runtime = tmp_path / "sub_no_overwrite_runtime"
        runtime.mkdir()
        script = tmp_path / "_no_overwrite_test.py"
        content = self.SCRIPT.replace("PROJECT_ROOT_PLACEHOLDER", repr(str(PROJECT_ROOT)))
        content = content.replace("RUNTIME_PLACEHOLDER", repr(str(runtime)))
        script.write_text(content)
        result = subprocess.run(
            [CANONICAL_PYTHON, "-B", str(script)],
            capture_output=True,
            timeout=120,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, (
            f"main.py overwrote UPLOAD_FOLDER.\n"
            f"stdout: {result.stdout.decode()}\n"
            f"stderr: {result.stderr.decode()}"
        )


# ═══════════════════════════════════════════════════════════════════
# Requirement 5 — cleanup removes exactly owned runtime root
# ═══════════════════════════════════════════════════════════════════

class TestCleanupOwnedRoot:
    def test_removes_owned_root(self, tmp_path):
        owned = Path(tempfile.mkdtemp(prefix="sgaa_pytest_runtime_"))
        try:
            token = "test_token_abc123"
            (owned / f".sgaa_session_{token}").write_text(token)
            (owned / "some_file").write_bytes(b"data")
            assert owned.exists()
            _remove_owned_runtime_root(owned, token)
            assert not owned.exists()
        finally:
            if owned.exists():
                shutil.rmtree(str(owned))

    def test_leaves_sibling_unowned(self, tmp_path):
        owned = Path(tempfile.mkdtemp(prefix="sgaa_pytest_runtime_"))
        sibling = Path(tempfile.mkdtemp(prefix="sgaa_pytest_runtime_"))
        try:
            token = "test_token_def456"
            (owned / f".sgaa_session_{token}").write_text(token)
            sibling_file = sibling / "should_survive.txt"
            sibling_file.write_bytes(b"survivor")

            _remove_owned_runtime_root(owned, token)

            assert not owned.exists()
            assert sibling.exists()
            assert sibling_file.read_bytes() == b"survivor"
        finally:
            if owned.exists():
                shutil.rmtree(str(owned))
            if sibling.exists():
                shutil.rmtree(str(sibling))

    def test_owned_root_isolation(self, tmp_path):
        owned = Path(tempfile.mkdtemp(prefix="sgaa_pytest_runtime_"))
        other = Path(tempfile.mkdtemp(prefix="not_our_prefix_"))
        try:
            token = "test_token_789xyz"
            (owned / f".sgaa_session_{token}").write_text(token)
            (owned / "data.txt").write_bytes(b"owned")
            (other / "private.txt").write_bytes(b"private")

            _remove_owned_runtime_root(owned, token)

            assert not owned.exists()
            assert other.exists()
            assert (other / "private.txt").read_bytes() == b"private"
        finally:
            if owned.exists():
                shutil.rmtree(str(owned))
            if other.exists():
                shutil.rmtree(str(other))


# ═══════════════════════════════════════════════════════════════════
# Requirement 6 — cleanup failure propagates
# ═══════════════════════════════════════════════════════════════════

class TestCleanupFailurePropagates:
    def test_rmtree_failure_propagates(self, monkeypatch, tmp_path):
        def _broken_rmtree(path, **kwargs):
            raise PermissionError("Simulated rmtree failure")

        monkeypatch.setattr(shutil, "rmtree", _broken_rmtree)

        owned = Path(tempfile.mkdtemp(prefix="sgaa_pytest_runtime_"))
        token = "fail_test_token"
        (owned / f".sgaa_session_{token}").write_text(token)

        try:
            with pytest.raises(PermissionError, match="Simulated rmtree failure"):
                _remove_owned_runtime_root(owned, token)
        finally:
            if owned.exists():
                monkeypatch.undo()
                shutil.rmtree(str(owned))

    def test_root_symlink_rejected_before_resolution(self, monkeypatch, tmp_path):
        owned = Path(tempfile.mkdtemp(prefix="sgaa_pytest_runtime_"))
        try:
            token = "root_symlink_test"
            (owned / f".sgaa_session_{token}").write_text(token)

            orig_islink = os.path.islink
            owned_basename = owned.name
            def _mock_islink(p, _basename=owned_basename, _orig=orig_islink):
                if os.path.basename(os.path.abspath(str(p))) == _basename:
                    return True
                return _orig(p)
            monkeypatch.setattr(os.path, "islink", _mock_islink)

            with pytest.raises(RuntimeError, match="Refusing to remove symlink owned root"):
                _remove_owned_runtime_root(owned, token)
        finally:
            if owned.exists():
                shutil.rmtree(str(owned))

    def test_marker_symlink_rejected(self, monkeypatch, tmp_path):
        owned = Path(tempfile.mkdtemp(prefix="sgaa_pytest_runtime_"))
        try:
            token = "marker_symlink_test"
            (owned / f".sgaa_session_{token}").write_text(token)

            orig_islink = os.path.islink
            marker_name = f".sgaa_session_{token}"
            def _mock_islink(p, _name=marker_name, _orig=orig_islink):
                if os.path.basename(p) == _name:
                    return True
                return _orig(p)
            monkeypatch.setattr(os.path, "islink", _mock_islink)

            with pytest.raises(RuntimeError, match="marker is a symlink"):
                _remove_owned_runtime_root(owned, token)
        finally:
            if owned.exists():
                shutil.rmtree(str(owned))

    def test_marker_text_mismatch_rejected(self, tmp_path):
        owned = Path(tempfile.mkdtemp(prefix="sgaa_pytest_runtime_"))
        try:
            token = "expected_token"
            wrong_token = "wrong_token"
            (owned / f".sgaa_session_{token}").write_text(wrong_token)

            with pytest.raises(RuntimeError, match="marker text mismatch"):
                _remove_owned_runtime_root(owned, token)
        finally:
            if owned.exists():
                shutil.rmtree(str(owned))

    def test_wrong_parent_rejected(self, tmp_path):
        target = tmp_path / "sgaa_pytest_runtime_test"
        target.mkdir()
        token = "parent_test"
        (target / f".sgaa_session_{token}").write_text(token)
        with pytest.raises(RuntimeError, match="parent"):
            _remove_owned_runtime_root(target, token)

    def test_missing_root_is_idempotent(self, tmp_path):
        nonexistent = tmp_path / "sgaa_pytest_runtime_nonexistent"
        _remove_owned_runtime_root(nonexistent, "any_token")


# ═══════════════════════════════════════════════════════════════════
# Requirement 7 — canonical root unchanged (uses conftest baseline)
# ═══════════════════════════════════════════════════════════════════

class TestCanonicalRootUnchanged:
    def test_assert_canonical_root_unchanged_does_not_raise(self):
        assert_canonical_root_unchanged()
