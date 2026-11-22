# SPEC OPS-LOG-01 — Governed daily backup logging reliability

Status: CLOSED 2026-11-19 (frozen 2026-11-19); installed 2026-11-21 (local; publication HOLD)
Charter: "Eliminate the logging concurrency defect in the governed daily backup process, ensuring that
simultaneous log observation cannot interrupt a valid backup operation." Local isolated testing only; PROD,
live scheduled tasks, production credentials and deployed scripts unchanged. Publication: HOLD (local commits).
Risk tier: R2 (charter floor: concurrency-related operational change).

## 1. Outcome

- An operator can follow the daily governed backup's log (`tail -F`, `Get-Content -Wait`, an editor) while
  the scheduled task runs; the run, its generation and its log are unaffected.
- A handle that refuses writers moves the run's log into a fallback file beside it, named on the console
  and, once the log takes writes again, at the log's end; no line of the run is lost while a file takes it.
- The outcome of every run stays observable: success, a failed generation and a refusal are logged; the
  exit code stays 0 only for a generation `tools/ops_backup.py` completed, verified and recorded.
- The corrected wrapper is in the repository (`tools/daily_governed_backup.ps1`); the deployed copy is
  unchanged until a separately authorized installation (§9).

## 2. Current facts

- The scheduled task "SGAA daily governed backup" runs `powershell.exe -NoProfile -NonInteractive
  -ExecutionPolicy Bypass -WindowStyle Hidden -File D:\SGAA_CUTOVER\daily_governed_backup.ps1` from the
  pinned worktree, `MultipleInstances` IgnoreNew, a 1 h limit (read, not changed, 2026-11-19).
- The deployed script is not in the repository. Its Git blob is the contract of slice 1:
  `9cac1d478e53567943361011bdd2b60942de5c65`. It differs from its v18 predecessor (kept in the GF1-V19
  folder) only in `$Wt`: a GF1 repin edits that one line.
- `Write-Log` is `Add-Content -Path $Log …; Write-Host` (script line 43) under
  `$ErrorActionPreference = 'Continue'` (line 19). `ops_backup`'s output is logged after it exits
  (`Invoke-Generation`). Exit codes, per its header: 0 generation recorded, 1 nothing recorded.
- Reproduced on Windows PowerShell 5.1.26100: `Add-Content` refuses to append whenever any handle is open
  on the file, even one sharing ReadWrite|Delete (non-terminating `IOException`,
  `GetContentWriterIOError`); `try` does not catch it; execution continues; the line is lost. An append
  opened with `FileShare.ReadWrite|Delete` succeeds beside every reader that shares writes and is refused
  only by a handle that denies writes. `Get-Content -Wait` reopens the file at each poll, so on the old
  script it loses lines intermittently.
- Reproduced on the verbatim deployed script in a sandbox (evidence outside the repository): while a
  reader holds the log, the run records its generation and exits 0 with **none** of its lines in the log;
  a failed generation or a refused key exits 1 with its reason lost; with no writable log at all the
  generation still runs, unlogged. GF1-V19 run 1 died instead because its script ran under 'Stop'; in the
  daily script the defect is silent loss of the audit trail, not interruption.
- `tools/` is outside every deployment export (`tools/deploy_audit.py` `RUNTIME_ALLOWLIST`); no repository
  guard scans `.ps1` files; nothing in the repository references the script.
- The mechanism of the correction is the one GF1-V19 proved in its own scripts (`run_gf1_v19.ps1`,
  `drill_terminal.ps1`, outside the repository).

## 3. Target design

Owner: `tools/daily_governed_backup.ps1` — the unattended daily governed generation the Windows scheduled
task runs (it wraps `tools/ops_backup.py --ledger-dir`); its deployed copy lives outside the repository.

- `Add-LogLine(path, text)` appends one UTF-8 line (no BOM) plus CRLF, opening the file with
  `FileAccess.Write` and `FileShare.ReadWrite|Delete`; up to 20 attempts, 250 ms apart; returns whether
  the line landed; never throws.
- `Write-Log(text, [-NoThrow])` writes the console first, then the log. On the first refusal the rest of
  the run goes to `<log stem>.fallback-<yyyyMMddHHmmss>-<pid>.log` beside it: its first line names the log
  it continues, and the console names it. When no file takes a line, it throws `LOG_UNWRITABLE` unless
  `-NoThrow`.
- `-NoThrow` exactly where the outcome is already decided: the `ops_backup` output lines, the
  `NO GENERATION RECORDED` line (A1), the RESULT line and the stop line in `catch`. So `LOG_UNWRITABLE` can
  stop a run only before `ops_backup` starts, and a log failure never turns a recorded generation into
  exit 1 or anything into exit 0.
- The start line moves inside `try`, so a refusal there is caught, cleans up and exits 1.
- `finally`, after the environment cleanup: when a fallback file exists, one best-effort line is appended
  to the log, `#### this run's log continued in <fallback>`.

- The header names the fallback file (A1; documentation only).

Every other line is byte-identical: constants, preconditions, secrets, probes, the generation call,
the cadence deadline, the exit codes.

## 4. Decisions

- D1 — The repository becomes the wrapper's source: slice 1 imports the deployed bytes unchanged, slice 2
  corrects them, so the correction is one reviewable diff against the bytes in service. Rejected: editing
  the deployed copy (charter); a logging module dot-sourced from the pinned worktree (`gf1_4087eaf` has
  none, and installing it would need a GF1).
- D2 — Shared-mode append, bounded retry, per-run fallback (the GF1-V19 mechanism). Rejected: PowerShell 7
  (a new runtime and a task change); `Out-File`/`Set-Content` (the same 5.1 sharing); a single unretried
  open (a transient lock still loses the line); holding the log open for the whole run (it would itself
  block other tools, and a crash leaves no flushed record).
- D3 — If no file takes a line before `ops_backup` starts, the run stops (exit 1, no generation).
  Rejected: running on unlogged, as the deployed copy does. Observation cannot cause this: it needs the log
  and a fresh, uniquely named file to refuse writes for 5 s each, i.e. a storage fault. A governed
  generation does not start without a record of its run (the GF1-V19 rule).
- D4 — After `ops_backup` ran, a log failure never changes the exit code: its exit code and the ledger
  decide, so "0 = generation recorded, 1 = nothing recorded" stays true in both directions.
- D5 — Tests run the shipped script with only its path and identity constants re-pointed (the test checks
  that nothing else differs), fakes for its Python children and real observer processes; Windows-only.
  Rejected: parameters on the script (they widen the task's interface for a test's sake).

Open decisions (product or architecture): none.

## 5. Phase invariants

- I1 — Exit 0 if and only if `ops_backup` returned 0 in this run; otherwise 1.
- I2 — One `ops_backup` call per run, with the same arguments; the wrapper never writes the ledger, the
  generations or a stored secret beyond what the deployed copy does.
- I3 (restated by A1) — Each line of the run lands in the log until the log first refuses it, and from then
  on in the run's fallback; the run returns to the log only for the closing pointer line. A fallback that
  itself later refuses writes is the accepted edge: before `ops_backup` starts the run stops with exit 1 and
  no generation (`LOG_UNWRITABLE`, or `GENERATION` when the refused line was the refusal reason), after it
  the lines are lost and the exit code stands.
- I4 — A reader that shares writes never moves the run to a fallback.
- I5 — The script stays ASCII: Windows PowerShell 5.1 reads a BOM-less script in the ANSI code page.

Global invariants: `docs/ENGINEERING_STANDARDS.md` and its guards (§11).

## 6. Scope

- Allowed paths: `tools/daily_governed_backup.ps1` (new), `tests/test_ops_log_01_daily_backup_logging.py`
  (new), this SPEC and `docs/specs/README.md`, `PROJECT_STATE.md`, the owner row of
  `docs/ENGINEERING_STANDARDS.md` §2 (a fact the new owner requires).
- Protected: the deployed script, the scheduled task, everything under `D:\SGAA_CUTOVER` (ledger, secrets,
  logs, GF1 folders), every PROD resource, `tools/ops_backup.py`, `app/`; commits `01a1d62` and `63c0ba3`.
- Planned local refactors: none.
- Out of scope: log rotation or size, PowerShell 7, other operator scripts (§15), backup policy, retention,
  schedule, `DisallowStartIfOnBatteries`.

## 7. Data & schema

No schema change, no data migration, no real data. The log's lines and format are unchanged (value-free;
UTF-8, CRLF); only where a line lands changes when the log refuses writes.

## 8. Security & RBAC

No route. Secrets: the same DPAPI files and reads; the environment is still removed in `finally`, before
the pointer line. Tests use dummy DPAPI values in a temporary directory and re-point the PROD project
reference and pooler host to sandbox values; no secret, PROD identity or personal data reaches a fixture
or an output.

## 9. Compatibility / rollout

- The deployed copy keeps running, unchanged, until installed. Installation is not part of this phase and
  needs a separate user authorization: replace `D:\SGAA_CUTOVER\daily_governed_backup.ps1` (blob of §2)
  with the repository file at its landing commit, keeping `$Wt` the then-pinned worktree (both say
  `gf1_4087eaf` today), checked with `git hash-object`; never while the task runs; no task change; keep the
  replaced copy beside it; confirm with one run. Rollback: restore that copy.
- A GF1 repin edits `$Wt` in the deployed copy; the repository copy follows in the same change.
- Until installation, nothing may hold `D:\SGAA_CUTOVER\daily_governed_backup.log` open while the task runs.

## 10. External boundaries / environment permissions

None. Local isolated testing only (sandboxes under `D:\SGAA_tmp`). PROD user gates: none. No provider,
credential, scheduled task or deployed file is read for writing.

## 11. Evidence plan

- T0: slice 1 blob equals the deployed blob; `git diff --check`; ASCII.
- T1: RED→GREEN of `tests/test_ops_log_01_daily_backup_logging.py` — RED against the verbatim script of
  slice 1, GREEN after slice 2. In-suite negative control: every observer defeats a plain 5.1
  `Add-Content`, so a green run cannot come from a weak observer.
- T2: the same file is the owner's whole contract (normal run, sharing readers, write-denying locks, a lock
  released mid-run, failed generation, refused key, unwritable log).
- T3: no dependents in the repository. T4: `tests/test_mp3_deploy_audit.py` (the export stays the runtime
  allowlist with a new file under `tools/`). Collection reconciled for the added tests.
- T5: not triggered (no §5.1 condition). E-PG/E-UI/E-LIVE: not applicable (no database, UI or provider);
  the concurrency evidence is real Windows processes holding real handles under the task's interpreter and
  flags.
- Review: R2, one independent fresh-context review before slice 2 lands; targeted recheck after fixes.

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | Import the deployed wrapper unchanged | `tools/daily_governed_backup.ps1` | blob identity (T0) | DONE |
| 2 | Shared-mode logging with fallback; tests; owner row; state | §6 allowed paths | RED→GREEN, T4, R2 review PASS | DONE |

## 13. Acceptance criteria

- AC1 — A reader that shares writes (Python/CRT `open`, .NET `FileShare.ReadWrite`, Git for Windows
  `tail -F`, a handle with delete access (A1)), held for the whole run: one generation, exit 0, the run's
  whole log in the log → `test_a_reader_holding_the_log_open_changes_nothing`; a write-denying lock briefer
  than the retry window costs no fallback (A1) →
  `test_a_lock_briefer_than_the_retry_window_is_waited_out_without_a_fallback`.
- AC2 — A handle that refuses writers, held for the whole run: one generation, exit 0, the whole log in one
  fallback named on the console, earlier lines intact →
  `test_a_lock_that_refuses_writers_moves_the_run_into_a_fallback_log`.
- AC3 — The lock released mid-run: the log ends with one line naming the fallback →
  `test_once_the_lock_is_gone_the_log_names_where_the_run_continued`.
- AC4 — Failures stay observable while the log is held: a failed generation (exit 1, ledger unchanged) and
  a refused storage key (no generation) log their reason and stop line →
  `test_a_failed_generation_stays_visible_while_the_log_is_held`,
  `test_a_refused_storage_key_never_starts_the_generation`.
- AC5 — A run whose lines no file takes stops before the generation, exit 1, ledger unchanged →
  `test_a_run_whose_lines_no_file_takes_stops_before_the_generation`.
- AC6 — Contracts unchanged: the unobserved run (same `ops_backup` arguments, one ledger row, the same log
  lines) → `test_the_unobserved_run_records_one_generation_and_logs_it_whole`; a log lost after `ops_backup`
  started leaves the recorded generation at exit 0 (A1, D4) →
  `test_a_log_lost_after_the_generation_started_never_changes_its_exit_code`; the slice-2 diff touches only
  §3's items.
- AC7 — The observers are real (`test_control_each_observer_defeats_a_plain_add_content`) and AC1–AC5 fail
  on the slice-1 script.
- AC8 — `docs/ENGINEERING_STANDARDS.md` self-audit (§13) passes.

## 14. Phase-specific hard stops

Any need to change the deployed script, the scheduled task or anything under `D:\SGAA_CUTOVER`; any need to
open the live log while the task can run; a correction that needs PowerShell 7.

## 15. Deferred / known non-blockers

- `D:\SGAA_CUTOVER\store_drive_read_secrets.ps1` logs with the same `Add-Content` pattern; it is an
  interactive one-off operator tool, not the governed daily process (outside the charter).
- Log growth and rotation: not addressed (no evidence of a problem).

## 16. Amendments

- A1 2026-11-19 — After the R2 review (all findings NON_MATERIAL): `-NoThrow` also on the
  `NO GENERATION RECORDED` line, so the stop line names the real cause (exit 1 either way); the header names
  the fallback file; I3 restated to what §3 does (no return to the log after the switch; a fallback that
  later refuses writes is the accepted edge); three tests added that no earlier test discriminated — a log
  lost after `ops_backup` started (D4), a lock briefer than the retry window, a handle with delete access —
  each proven by a mutant it kills; the harness releases an observer whose start fails. Impact: none on any
  outcome. Material: no.

## 17. Closure

CLOSED 2026-11-19, local commits only (publication HOLD: not pushed, not installed).

- Acceptance: AC1–AC8 met. Evidence (outside the repository, `D:\SGAA_tmp\ops_log_01\`): GREEN, the test
  file 21/21 on Windows PowerShell 5.1.26100 with the task's flags; RED, its pre-A1 version against the
  slice-1 script: all ten AC1–AC5 tests fail (every line of an observed run lost; a refused or failed run's
  reason lost; an unlogged generation when no log is writable) while the controls, the ASCII check and the
  unobserved run pass; the A1 tests kill their mutants (no `-NoThrow` on `ops_backup`'s output, no retry,
  no delete sharing). T4: `tests/test_mp3_deploy_audit.py` 81 passed, 1 skipped (the export is still the
  runtime allowlist with the new file under `tools/`). Collection: prior + the file's 21 tests. T5 not
  triggered (TEP §5.1: no condition applies).
- Review: R2, a fresh-context Claude Opus 5.5 session (same family; not an R3 cross-family review):
  PASS, 0 MATERIAL, 7 NON_MATERIAL — four fixed, two recorded by A1, one (documentation timing) reconciled
  in slice 2; targeted recheck of the fixes PASS.
- Slices: 1 imported the deployed blob of §2; 2 is the correction.
- Carried to `PROJECT_STATE.md`: the installation of §9 (owner gate) and, until then, the rule that nothing
  holds the live log open while the task runs; the push of these commits (HOLD).
- Follow-ups: §15.

## 18. Installation (operational, owner-authorized 2026-11-21)

§9 was executed on 2026-11-21, 22:10-22:15 local (2026-11-22T01:10-01:15Z), from repository HEAD
`477e18fd6a67853fa85f2d5956fb1f0de47a9a70`. Installation only; no development slice was reopened and no
qualification was rerun.

- Replaced `D:\SGAA_CUTOVER\daily_governed_backup.ps1`: original blob
  `9cac1d478e53567943361011bdd2b60942de5c65` (SHA-256 `FE0E735887B1DDDBD545C25126FCAFC98FAD26D1CB53D4AC0D265C1B4BA079A4`),
  preserved byte-identically beside it at
  `D:\SGAA_CUTOVER\daily_governed_backup.ps1.pre-ops-log-01.20261121T221040.bak` (same blob and SHA-256),
  and installed the repository file, blob `4d8db12c7daeafe2cd6a781d88e4b6bde724334e`
  (SHA-256 `CCF449E7318C34CAEA64790E9095CBCFB1B31C95FFEBB1C8BA6EEF326AFA7744`). Both checked with
  `git hash-object`; the staged copy was hash-checked before the rename.
- `$Wt` kept at `D:\SGAA_wt\gf1_4087eaf`, the then-pinned worktree and the task's working directory. The
  installed and repository files contain the same value (the same line in both).
- Scheduled task unchanged: the exported definition has SHA-256
  `412590F974C0D01AA6B4D66B285D297B00F38C378918782BA4B2CF24F6926182` before and after; interpreter
  (`powershell.exe`), arguments, working directory, principal (`klebe`, Interactive, Limited),
  `MultipleInstances` IgnoreNew, the 1 h limit and the daily 20:00 trigger are the same. The replacement
  ran with the task `Ready` and no `daily_governed_backup.ps1` process active.
- §9 confirmation run (the task's interpreter and flags, its working directory), 2026-11-21 22:11:19-22:15:33
  local: exit code 0 in 4m14s. `ops_backup` steps DATABASE_BACKUP, DATABASE_VERIFY, OBJECT_BACKUP and
  OBJECT_VERIFY all exit 0; ledger seq 268 (`backup`/`GENERATION`, `2026-11-22T01:11:46Z`), 268 entries,
  chain OK, no unresolved operation, state unchanged at C13; generation
  `sgaa-pg-20261122T011146Z-auto-daily` (402,251 bytes, SHA-256
  `8fcfb731d81d4e682cc72add720f9933ca7b429a968aaf5a4a23b4827b3304e6`, matching its sidecar; manifest
  `result ok`, schema 19, 41 tables, 71/71 domain checks, 19/19 triggers) and objects
  `20261122T011143Z-auto-daily`, with the off-platform copies present and hash-matching. The run's six
  lines are in `daily_governed_backup.log` (278 -> 284) and match the captured console exactly; no fallback
  file was created.
- Rollback: restore the preserved `.bak` over the installed file; no task change is needed.
- Publication of the OPS-LOG-01 commits remains HOLD (local commits only).
