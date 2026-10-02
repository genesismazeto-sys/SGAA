# Pytest custody × external writers (scheduler, runtime, preflight)

Bounded test/process custody cohort, 2026-10-02, branch
`refactor/design-system-foundation` on top of `2f117a7`.

This document is the operational contract behind the full-suite custody gate in
`tests/conftest.py` and the focused proof in
`tests/test_pytest_custody_external_writer.py`. It exists so the state a final
full-suite run requires is not carried in human memory.

## 1. Custody model

Before any test runs, `tests/conftest.py` fingerprints the real repository
runtime scopes and asserts them unchanged at `pytest_sessionfinish`. Every
`APP_*` runtime path — including `APP_LOG_DIR` — is routed into a session-owned
temporary root (`sgaa_pytest_runtime_*`), which is removed at teardown with an
ownership marker check.

| Scope | Treatment |
|---|---|
| `database.db` | Strictly protected: size + SHA-256 + mtime. Canonical business data. |
| `database.db-wal` | Strictly protected **by content class**: a WAL with committed frames is an uncheckpointed canonical write and fails. A zero-length/header-only WAL is a benign sidecar. |
| `database.db-shm` | Structural sidecar: coordination index, stores no database content of its own; presence/bytes never fail. A WAL that does hold content fails on its own scope. |
| `logs/` | Strictly protected, **except** the narrow family `backup-automatico.log` + `.1`/`.2`/`.3`, exempt by file identity (inode) only, never by name glob. `logs/` directory mtime is forgiven only when that identity changed (create/rotation). |
| `uploads/`, `documentos_alunos/`, `backups/` | Strictly protected recursively (children size + SHA-256 + mtime, directory mtimes). |
| `.pytest_cache/` | Excluded by design; pytest routes its own cache under the session runtime root. |
| Repository root, `__pycache__`, docs/tools | Not monitored. |

No `logs/*`, `*.log`, `*.db` or whole-directory exemption exists.

## 2. External writers

| Process | May write | Legitimate during pytest? | Controlled by pytest? | Guard treatment |
|---|---|---|---|---|
| Windows task `SGAA - Backup automatico` (`pythonw -m app.backup.sync --scheduled`, every 5 min, cwd = repo) | `<repo>/logs/backup-automatico.log` (+ rotations); `D:\SGAA_BACKUPS\.sgaa-automatic-backup-state`, snapshots (outside repo); opens the canonical DB read-only-digest | Yes | No | Run-log family exempt by identity; DB access proven read-only (digest/backup APIs) |
| Canonical runtime (`run.bat` → preflight + `python main.py`, port 5000) | `<repo>/logs/app.log` (loggers `main`, `app`, `app.startup_preflight`), `database.db`, uploads/documents | No | No | Must be stopped before the full suite; failure names the writer |
| Startup preflight (`python -m app.startup_preflight`) | `<repo>/logs/app.log` when run inside the runtime logging configuration | No | No | Same as runtime |
| Acceptance runtime (`run_acceptance.bat` → port 5000) | Its own `APP_DATABASE` outside the repo; `<repo>/logs/app.log` | No | No | Refused while 5000 is occupied; same as runtime |
| Manual backup/restore (UI) | Runtime scope + snapshot dir | No | No | Needs the runtime stopped |
| pytest itself | Only `PYTEST_RUNTIME_ROOT` (DB, logs, uploads, docs, backups, cache) | Yes | Yes | Isolated by construction; per-test log handler |

Evidence for the scheduler's write set: `app/backup/automatic.py`
(`configure_run_log`, `read_state`/`_write_state`, `database_content_digest`),
`app/backup/sync.py`, `app/db_maintenance.py` (`_read_backup_schema_status`
uses `mode=ro&immutable=1`). Runtime app.log ownership: `main.py:653-663`
(rotating handler, `APP_LOG_DIR/app.log`) and `app/__init__.py:435-452`.

## 3. WAL/SHM policy

Reproduced with disposable SQLite copies (2026-10-02):

* A read-only URI open (`mode=ro`) leaves a **zero-length** `-wal` and a 32 KiB
  `-shm` behind on Windows; `database.db` is byte-identical.
* A read-write open that writes nothing removes both on clean close.
* A committed transaction with `wal_autocheckpoint=0` leaves a WAL whose commit
  frames carry a non-zero "database size after commit" field; the main DB file
  is unchanged until checkpoint.

The guard therefore fails only on committed frames (or on an unreadable/not-WAL
payload in the sidecar slot), and tolerates a missing/absent, zero-length or
header-only WAL plus any `-shm`. A WAL that disappears without touching
`database.db` is benign; a checkpoint that persists a committed WAL changes
`database.db` and fails there.

## 4. Supported full-suite state

```powershell
# from the repository root
& "$env:LOCALAPPDATA\SGAA\venv\Scripts\python.exe" -m pytest -q
```

* Canonical runtime: **stopped** (port 5000 free). `pytest_configure` warns if
  port 5000 is listening; `tools/run_release_checks.py --with-full-pytest`
  refuses to start the full suite in that state.
* Automatic backup scheduler: **may stay enabled**. Ordinary wakes append only
  the exempt run log; with nothing due the canonical database is untouched; a
  legitimate due backup writes outside the repository. If the canonical DB
  changed outside pytest, the following wake may back it up — the suite must
  not misclassify that as its own mutation, and it does not: the DB comparison
  still fails if the canonical content changed while the suite ran, and the
  exempt log cannot hide it.
* Isolated pytest database: `%TEMP%\sgaa_pytest_runtime_*\...` only.
* Expected logs: pytest logs under the session runtime root; the only expected
  repository log write is the scheduler's exempt family.
* Teardown verifies: canonical scopes and sidecars unchanged, runtime root
  ownership-proved and removed, no custody diff left unreported.

## 5. Failure diagnosis

`assert_canonical_root_unchanged` raises a report that names: the changed
scope(s), the external writer classes for that scope, the supported pre-suite
state, port-5000 state, and any live operational process (PID + command line,
via a failure-path-only process probe). A change to `logs/app.log` is
attributed to the canonical runtime/preflight, never exempted; a committed WAL
is labeled an uncheckpointed canonical write.

## 6. Scheduler coexistence — proof

* Ordinary wake: append/rotation of the exempt family never trips the guard
  (focused tests A lane; the real task wrote every 5 minutes during the final
  full-suite run).
* Due backup: if the canonical DB changed outside pytest, the wake's snapshot
  goes to `D:\SGAA_BACKUPS` (outside the repository), and any canonical content
  change is still failed by the DB comparison.
* The exempt family is exactly `RUN_LOG_FILENAME` and the rotations the
  production `RotatingFileHandler(backupCount=3)` can create; `.4`, `.bak`,
  sibling names and any other log remain failures.

## 7. Focused tests

`tests/test_pytest_custody_external_writer.py`:

* A — scheduler appends/rotations/first-run log dir: pass; without the
  exclusion the same append is caught.
* B — pytest-owned canonical DB mutation fails; `app.log` changes fail even
  during rotation; other scopes unaffected by the exclusion.
* C — new/unexpected log files and transient files fail.
* D — the guard never touches the real scheduler; exemption is exactly the
  run-log family.
* E — committed-frame detection (synthetic + real SQLite), benign zero-length
  WAL/`-shm`, benign disappearance, non-WAL payload fails.
* F — the real runtime writer (`import main`) appends a disposable `app.log`
  and is caught; failure message names writer, PID, port state and required
  state; scheduler activity cannot hide a DB change.
* G — session runtime root writes are outside canonical custody.

## 8. Residual status

PYTEST × SCHEDULER CUSTODY / EXTERNAL-WRITER ISOLATION: **DONE**. Deterministic
coexistence with the scheduler is achieved without pausing it; no canonical
business-data mutation is tolerated by any exemption.
