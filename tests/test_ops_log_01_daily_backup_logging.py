"""OPS-LOG-01: nobody reading the daily governed backup's log can break the run or hide its outcome.

``tools/daily_governed_backup.ps1`` is the wrapper the Windows scheduled task runs with Windows
PowerShell 5.1 (``-NonInteractive -File``).  These tests run that script as shipped -- only its path
and identity constants are re-pointed at a sandbox, and the sandbox copy is checked to differ in
nothing else -- with fakes for its Python children (ledger status, the two key probes,
``ops_backup``), so no test can reach a provider or a production database.  Every observer is a
real handle held by a real process for the whole run, as an operator's ``tail -F``,
``Get-Content -Wait``, editor or scanner holds it (continuously or at every poll).
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "daily_governed_backup.ps1"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
GIT_TAIL = Path(r"C:\Program Files\Git\usr\bin\tail.exe")
# The scheduled task's own command line (Task Scheduler action), minus the script path.
TASK_FLAGS = ("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden")
# Constants the sandbox re-points; every other byte of the script runs as shipped.
REPOINTED = ("Ref", "Pooler", "Bucket", "Wt", "Py", "Ledger", "Log", "RollRoot", "RollOff", "PgBin",
             "Secrets", "StoreProbe", "DriveProbe")
# The variables the script sets and removes ($Names); a run must start without any of them.
SCRIPT_ENV = frozenset({"PGPASSWORD", "PGPASSFILE", "DATABASE_URL", "APP_ENV", "SGAA_RUNTIME", "TRUST_PROXY_XFF",
                        "SUPABASE_URL", "SGAA_STORAGE_BUCKET", "SGAA_PG_BIN_DIR", "APP_SECRET_KEY",
                        "TOKEN_ENCRYPTION_KEY", "SGAA_ADMISSION", "SGAA_OPENING_REFERENCE", "APP_PUBLIC_BASE_URL",
                        "SUPABASE_SECRET_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"})
SECRET_NAMES = ("prod_db_password", "prod_storage_key", "prod_token_encryption_key", "prod_google_client_id",
                "prod_google_client_secret")
SEED_LINE = "#### an earlier run (sandbox seed)"
SEED_DEADLINE = "2026-11-20T08:00:00Z"  # the seeded generation (2026-11-18T20:00:00Z) + 36 h

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not POWERSHELL.is_file(),
    reason="needs Windows PowerShell 5.1, the interpreter of the scheduled task",
)

FAKE_LEDGER_STATUS = r'''
import json, sys
assert sys.argv[1] == "status", sys.argv
print(json.dumps({"chain": "OK", "unresolved_operation": None}))
'''

FAKE_OPS_BACKUP = r'''
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
SANDBOX = Path(__file__).resolve().parents[2]
config = json.loads((SANDBOX / "fake.json").read_text(encoding="utf-8"))
with (SANDBOX / "ops_calls.jsonl").open("a", encoding="utf-8") as calls:
    calls.write(json.dumps(sys.argv[1:]) + "\n")
print("ops_backup: database set verified", flush=True)
print("ops_backup: object set verified", file=sys.stderr, flush=True)
if config.get("handshake"):
    (SANDBOX / "ops_started").write_text("1")
    deadline = time.monotonic() + 90
    while not (SANDBOX / "ops_continue").exists():
        if time.monotonic() > deadline:
            sys.exit(9)
        time.sleep(0.05)
code = int(config.get("ops_exit", 0))
if code == 0:
    ledger = Path(sys.argv[sys.argv.index("--ledger-dir") + 1]) / "ledger.jsonl"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "backup", "generation_at": stamp}) + "\n")
    print("ops_backup: generation recorded", flush=True)
sys.exit(code)
'''

FAKE_PROBE = r'''
import json
from pathlib import Path
config = json.loads((Path(__file__).resolve().parents[1] / "fake.json").read_text(encoding="utf-8"))
print(config["{key}"])
'''


# ---------------------------------------------------------------- handles --------------------------------------

_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None
if _KERNEL32 is not None:
    _KERNEL32.CreateFileW.restype = ctypes.c_void_p
    _KERNEL32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                      ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    _KERNEL32.CloseHandle.argtypes = [ctypes.c_void_p]
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_ERROR_SHARING_VIOLATION = 32


def _someone_holds(path: Path) -> bool:
    """True when any handle is open on ``path``: an open that shares nothing is refused."""
    handle = _KERNEL32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0, None)  # GENERIC_READ, OPEN_EXISTING
    if handle == _INVALID_HANDLE:
        error = ctypes.get_last_error()
        assert error == _ERROR_SHARING_VIOLATION, f"unexpected CreateFileW error {error} on {path}"
        return True
    _KERNEL32.CloseHandle(handle)
    return False


def _wait_until(predicate, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.05)


class Observer:
    """A process (or this test process) holding the log open the way an operator's tool does."""

    def __init__(self, kind: str, log: Path):
        self.kind, self.log = kind, log
        self._handle = None
        self._win32_handle = None
        self._process = None

    def start(self) -> "Observer":
        quoted = str(self.log).replace("'", "''")
        holder = ("$h = [IO.File]::Open('{0}', 'Open', 'Read', '{1}'); [void][Console]::In.ReadLine(); "
                  "$h.Dispose()")
        argv = {
            # the open mode of PowerShell readers (Get-Content -Wait opens it at every poll, so it is held here)
            "dotnet-share-readwrite": [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command",
                                       holder.format(quoted, "ReadWrite")],
            "git-tail-F":[str(GIT_TAIL), "-n", "0", "-F", self.log.as_posix()],
            "dotnet-share-read": [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command",
                                  holder.format(quoted, "Read")],
            "dotnet-share-none": [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command",
                                  holder.format(quoted, "None")],
        }
        if self.kind == "python-open":
            self._handle = open(self.log, "rb")  # the CRT shares read and write, like most readers
        elif self.kind == "win32-delete-access":
            # read plus DELETE access, sharing everything, as a log rotator or an indexer holds a file
            handle = _KERNEL32.CreateFileW(str(self.log), 0x80000000 | 0x00010000, 7, None, 3, 0, None)
            assert handle != _INVALID_HANDLE, ctypes.get_last_error()
            self._win32_handle = handle
        else:
            if self.kind == "git-tail-F" and not GIT_TAIL.is_file():
                pytest.skip("Git for Windows tail.exe (the observer of the GF1-V19 run-1 incident) is absent")
            self._process = subprocess.Popen(argv[self.kind], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
        try:
            _wait_until(lambda: _someone_holds(self.log), 30, f"{self.kind} to hold the log")
        except BaseException:
            self.release()  # the caller never receives this observer, so nothing else would end its process
            raise
        return self

    def release(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        if self._win32_handle is not None:
            _KERNEL32.CloseHandle(self._win32_handle)
            self._win32_handle = None
        if self._process is not None:
            if self._process.poll() is None:
                try:
                    self._process.stdin.write(b"\n")
                    self._process.stdin.flush()
                    self._process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    pass  # tail ignores stdin; it is killed below
            if self._process.poll() is None:
                self._process.kill()
            self._process.wait(timeout=10)
            self._process = None


# ---------------------------------------------------------------- sandbox --------------------------------------

@dataclass
class Sandbox:
    root: Path
    script: Path
    wt: Path
    ledger: Path
    log: Path

    def configure(self, **values) -> None:
        config = {"ops_exit": 0, "store_probe": "KEY_OK", "drive_probe": "KEY_OK app_credentials=CONFIGURED"}
        config.update(values)
        (self.root / "fake.json").write_text(json.dumps(config), encoding="utf-8")

    def ops_calls(self) -> list[list[str]]:
        path = self.root / "ops_calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def ledger_rows(self) -> list[dict]:
        text = (self.ledger / "ledger.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def primary_lines(self) -> list[str]:
        lines = self.log.read_text(encoding="utf-8-sig").splitlines()
        assert lines[0] == SEED_LINE, "the earlier runs' lines must stay as they were"
        return lines[1:]

    def fallbacks(self) -> list[Path]:
        return sorted(self.log.parent.glob("daily_governed_backup.fallback-*.log"))

    def task_command(self) -> list[str]:
        return [str(POWERSHELL), *TASK_FLAGS, "-File", str(self.script)]

    def task_env(self) -> dict[str, str]:
        env = {name: value for name, value in os.environ.items() if name.upper() not in SCRIPT_ENV}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def run(self, timeout: float = 180) -> subprocess.CompletedProcess:
        return subprocess.run(self.task_command(), cwd=self.wt, env=self.task_env(), capture_output=True,
                              timeout=timeout)


def _repointed(text: str, values: dict[str, str]) -> str:
    pattern = re.compile(r"^(?P<lead>\$(?P<name>" + "|".join(REPOINTED) + r")[ \t]*=[ \t]*)'[^']*'[ \t]*$", re.M)
    found = [match.group("name") for match in pattern.finditer(text)]
    assert sorted(found) == sorted(REPOINTED), f"each re-pointed constant must be defined exactly once: {found}"
    result = pattern.sub(lambda match: f"{match.group('lead')}'{values[match.group('name')]}'", text)
    changed = [pair for pair in zip(text.splitlines(), result.splitlines()) if pair[0] != pair[1]]
    assert len(changed) == len(REPOINTED) and len(text.splitlines()) == len(result.splitlines())
    return result


@pytest.fixture(scope="module")
def protected_secrets(tmp_path_factory) -> Path:
    """DPAPI files holding a dummy value, for this Windows user, as the task's secrets directory holds."""
    folder = tmp_path_factory.mktemp("ops_log_01_secrets")
    names = ",".join(f"'{name}'" for name in SECRET_NAMES)
    command = (f"$ErrorActionPreference = 'Stop'; foreach ($n in @({names})) {{ "
               f"'sandbox-value-not-a-secret' | ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString "
               f"| Set-Content -LiteralPath (Join-Path '{folder}' ($n + '.dpapi')) -Encoding ASCII }}")
    subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", command], check=True,
                   capture_output=True, timeout=60)
    return folder


@pytest.fixture
def sandbox(tmp_path, protected_secrets) -> Sandbox:
    wt, ledger, logs, probes = (tmp_path / name for name in ("wt", "ledger", "logs", "probes"))
    for folder in (wt / "tools", ledger, logs, probes, tmp_path / "rolling", tmp_path / "rolling-off"):
        folder.mkdir(parents=True)
    (wt / "tools" / "cutover_ledger.py").write_text(FAKE_LEDGER_STATUS, encoding="utf-8")
    (wt / "tools" / "ops_backup.py").write_text(FAKE_OPS_BACKUP, encoding="utf-8")
    (probes / "storage_key_probe.py").write_text(FAKE_PROBE.replace("{key}", "store_probe"), encoding="utf-8")
    (probes / "drive_read_key_probe.py").write_text(FAKE_PROBE.replace("{key}", "drive_probe"), encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(wt)], check=True, capture_output=True, timeout=60)
    (wt / ".git" / "info" / "exclude").write_text("*\n", encoding="utf-8")  # a clean worktree, as the task requires
    shutil.copytree(protected_secrets, tmp_path / "secrets")
    (ledger / "ledger.jsonl").write_text(
        json.dumps({"type": "backup", "generation_at": "2026-11-18T20:00:00Z"}) + "\n"
        + json.dumps({"type": "restore", "restored_at": "2026-11-18T21:00:00Z"}) + "\n", encoding="utf-8")
    log = logs / "daily_governed_backup.log"
    log.write_bytes((SEED_LINE + "\r\n").encode("ascii"))
    values = {"Ref": "sandboxref", "Pooler": "pooler.sandbox.invalid", "Bucket": "sandbox-bucket", "Wt": str(wt),
              "Py": sys.executable, "Ledger": str(ledger), "Log": str(log), "RollRoot": str(tmp_path / "rolling"),
              "RollOff": str(tmp_path / "rolling-off"), "PgBin": str(tmp_path / "pgbin"),
              "Secrets": str(tmp_path / "secrets"), "StoreProbe": str(probes / "storage_key_probe.py"),
              "DriveProbe": str(probes / "drive_read_key_probe.py")}
    script = tmp_path / "daily_governed_backup.ps1"
    script.write_text(_repointed(SCRIPT.read_text(encoding="utf-8"), values), encoding="utf-8")
    box = Sandbox(root=tmp_path, script=script, wt=wt, ledger=ledger, log=log)
    box.configure()
    return box


# ---------------------------------------------------------------- expectations ---------------------------------

SUCCESS_SHAPE = (
    r"#### daily governed generation start \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d",
    r"storage key probe: KEY_OK",
    r"drive read probe: KEY_OK app_credentials=CONFIGURED",
    r"== full generation \(database \+ documents\) \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d",
)
OPS_OUTPUT = {"ops_backup: database set verified", "ops_backup: object set verified", "ops_backup: generation recorded"}
RESULT_LINE = r"#### RESULT: generation recorded \(database \+ documents\)\. Next cadence deadline \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\."


def _assert_whole_success_log(lines: list[str]) -> None:
    assert len(lines) == len(SUCCESS_SHAPE) + len(OPS_OUTPUT) + 1, lines
    for pattern, line in zip(SUCCESS_SHAPE, lines):
        assert re.fullmatch(pattern, line), (pattern, line)
    assert set(lines[len(SUCCESS_SHAPE):-1]) == OPS_OUTPUT, lines
    assert re.fullmatch(RESULT_LINE, lines[-1]), lines[-1]


def _assert_one_generation(box: Sandbox, completed: subprocess.CompletedProcess) -> None:
    assert completed.returncode == 0, completed.stdout.decode("ascii", "replace")
    assert box.ops_calls() == [[
        "--root", str(box.root / "rolling"), "--off-platform", str(box.root / "rolling-off"), "--generations", "3",
        "--label", "daily", "--ledger-dir", str(box.ledger), "--objects",
    ]]
    assert [row["type"] for row in box.ledger_rows()] == ["backup", "restore", "backup"]


def _fallback_lines(box: Sandbox) -> list[str]:
    fallbacks = box.fallbacks()
    assert len(fallbacks) == 1, fallbacks
    lines = fallbacks[0].read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == f"== {box.log} refused writes from here on; this file continues it", lines[0]
    return lines[1:]


SHARING_OBSERVERS = ("python-open", "dotnet-share-readwrite", "git-tail-F", "win32-delete-access")
WRITE_DENYING_OBSERVERS = ("dotnet-share-read", "dotnet-share-none")


# ---------------------------------------------------------------- tests ----------------------------------------

def test_the_script_stays_ascii_so_windows_powershell_reads_it_as_written():
    # PowerShell 5.1 reads a BOM-less script in the ANSI code page: any non-ASCII byte changes its strings.
    assert SCRIPT.read_bytes().isascii()


@pytest.mark.parametrize("kind", SHARING_OBSERVERS + WRITE_DENYING_OBSERVERS)
def test_control_each_observer_defeats_a_plain_add_content(sandbox, kind):
    """The harness's observers are real: each one makes PS 5.1 Add-Content lose a line, as in GF1-V19 run 1."""
    before = sandbox.log.read_bytes()
    observer = Observer(kind, sandbox.log).start()
    try:
        quoted = str(sandbox.log).replace("'", "''")
        probe = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command",
                                f"$ErrorActionPreference = 'Continue'; Add-Content -LiteralPath '{quoted}' "
                                f"-Value 'control line' -Encoding UTF8"], capture_output=True, timeout=60)
        assert _someone_holds(sandbox.log)
    finally:
        observer.release()
    assert b"IOException" in probe.stderr, probe.stderr.decode("ascii", "replace")
    assert sandbox.log.read_bytes() == before


def test_the_unobserved_run_records_one_generation_and_logs_it_whole(sandbox):
    completed = sandbox.run()
    _assert_one_generation(sandbox, completed)
    _assert_whole_success_log(sandbox.primary_lines())
    assert sandbox.fallbacks() == []


@pytest.mark.parametrize("kind", SHARING_OBSERVERS)
def test_a_reader_holding_the_log_open_changes_nothing(sandbox, kind):
    observer = Observer(kind, sandbox.log).start()
    try:
        completed = sandbox.run()
        assert _someone_holds(sandbox.log), "the observer must hold the log through the whole run"
    finally:
        observer.release()
    _assert_one_generation(sandbox, completed)
    _assert_whole_success_log(sandbox.primary_lines())
    assert sandbox.fallbacks() == []


@pytest.mark.parametrize("kind", WRITE_DENYING_OBSERVERS)
def test_a_lock_that_refuses_writers_moves_the_run_into_a_fallback_log(sandbox, kind):
    observer = Observer(kind, sandbox.log).start()
    try:
        completed = sandbox.run()
        assert _someone_holds(sandbox.log)
    finally:
        observer.release()
    _assert_one_generation(sandbox, completed)
    assert sandbox.primary_lines() == []
    _assert_whole_success_log(_fallback_lines(sandbox))
    console = completed.stdout.decode("ascii", "replace")
    assert f"this run continues its log in {sandbox.fallbacks()[0]}" in console


def _start_task(box: Sandbox) -> subprocess.Popen:
    return subprocess.Popen(box.task_command(), cwd=box.wt, env=box.task_env(), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)


def test_once_the_lock_is_gone_the_log_names_where_the_run_continued(sandbox):
    sandbox.configure(handshake=True)
    observer = Observer("dotnet-share-none", sandbox.log).start()
    try:
        process = _start_task(sandbox)
    except BaseException:
        observer.release()
        raise
    try:
        _wait_until(lambda: (sandbox.root / "ops_started").exists(), 120, "the generation to start")
        observer.release()
        assert not _someone_holds(sandbox.log)
        (sandbox.root / "ops_continue").write_text("1", encoding="utf-8")
        stdout, _ = process.communicate(timeout=120)
    finally:
        observer.release()
        if process.poll() is None:
            process.kill()
    _assert_one_generation(sandbox, subprocess.CompletedProcess(process.args, process.returncode, stdout, b""))
    fallback = sandbox.fallbacks()
    _assert_whole_success_log(_fallback_lines(sandbox))
    assert sandbox.primary_lines() == [f"#### this run's log continued in {fallback[0]}"]


def test_a_lock_briefer_than_the_retry_window_is_waited_out_without_a_fallback(sandbox):
    sandbox.configure(handshake=True)
    process = _start_task(sandbox)
    observer = None
    try:
        _wait_until(lambda: (sandbox.root / "ops_started").exists(), 120, "the generation to start")
        observer = Observer("dotnet-share-none", sandbox.log).start()
        (sandbox.root / "ops_continue").write_text("1", encoding="utf-8")
        time.sleep(2)  # the wrapper logs ops_backup's first line into the lock and retries (5 s window)
        observer.release()
        stdout, _ = process.communicate(timeout=120)
    finally:
        if observer is not None:
            observer.release()
        if process.poll() is None:
            process.kill()
    _assert_one_generation(sandbox, subprocess.CompletedProcess(process.args, process.returncode, stdout, b""))
    _assert_whole_success_log(sandbox.primary_lines())
    assert sandbox.fallbacks() == []


def test_a_log_lost_after_the_generation_started_never_changes_its_exit_code(sandbox):
    sandbox.configure(handshake=True)
    process = _start_task(sandbox)
    moved = sandbox.root / "logs-moved"
    try:
        _wait_until(lambda: (sandbox.root / "ops_started").exists(), 120, "the generation to start")
        sandbox.log.parent.rename(moved)  # from here on neither the log nor a fallback beside it can be written
        (sandbox.root / "ops_continue").write_text("1", encoding="utf-8")
        stdout, _ = process.communicate(timeout=180)
    finally:
        if process.poll() is None:
            process.kill()
    _assert_one_generation(sandbox, subprocess.CompletedProcess(process.args, process.returncode, stdout, b""))
    assert not sandbox.log.parent.exists()
    lines = (moved / sandbox.log.name).read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == SEED_LINE and len(lines) == 1 + len(SUCCESS_SHAPE)
    for pattern, line in zip(SUCCESS_SHAPE, lines[1:]):
        assert re.fullmatch(pattern, line), (pattern, line)
    assert re.search(RESULT_LINE, stdout.decode("ascii", "replace"))


@pytest.mark.parametrize("kind", ("python-open", "dotnet-share-none"))
def test_a_failed_generation_stays_visible_while_the_log_is_held(sandbox, kind):
    sandbox.configure(ops_exit=1)
    observer = Observer(kind, sandbox.log).start()
    try:
        completed = sandbox.run()
    finally:
        observer.release()
    assert completed.returncode == 1
    assert len(sandbox.ops_calls()) == 1
    assert [row["type"] for row in sandbox.ledger_rows()] == ["backup", "restore"]
    lines = sandbox.primary_lines() if kind == "python-open" else _fallback_lines(sandbox)
    assert lines[-2:] == [
        f"NO GENERATION RECORDED: the documents generation failed (exit 1). Cadence deadline {SEED_DEADLINE}.",
        "#### stopped: GENERATION",
    ]


def test_a_refused_storage_key_never_starts_the_generation(sandbox):
    sandbox.configure(store_probe="KEY_REFUSED 401")
    observer = Observer("git-tail-F" if GIT_TAIL.is_file() else "python-open", sandbox.log).start()
    try:
        completed = sandbox.run()
    finally:
        observer.release()
    assert completed.returncode == 1
    assert sandbox.ops_calls() == []
    assert sandbox.primary_lines()[1:] == [
        "storage key probe: KEY_REFUSED 401",
        f"NO GENERATION RECORDED: the storage key was not accepted. Cadence deadline {SEED_DEADLINE}.",
        "#### stopped: GENERATION",
    ]


def test_a_run_whose_lines_no_file_takes_stops_before_the_generation(sandbox):
    shutil.rmtree(sandbox.log.parent)
    completed = sandbox.run()
    assert completed.returncode == 1
    assert sandbox.ops_calls() == []
    assert [row["type"] for row in sandbox.ledger_rows()] == ["backup", "restore"]
    assert not sandbox.log.parent.exists()
    assert "#### stopped: LOG_UNWRITABLE" in completed.stdout.decode("ascii", "replace")
