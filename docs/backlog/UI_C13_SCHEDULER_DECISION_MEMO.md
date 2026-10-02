# UI-C13 — Automatic backup: scheduler architecture (implemented)

**Status:** IMPLEMENTED — PENDING SCHEDULER INSTALLATION ACCEPTANCE (2026-09-28). The mechanism is built and tested; the
real scheduled task has **not** been registered on this machine (the batch did not authorize installation).

> **Correction to the 2026-09-28 overnight audit.** That audit said "no authoritative frequency exists" and asked the
> user for a cadence and a time of day. That was wrong: the SGAA already owns the cadence. It is the existing
> `cloud_sync_interval_seconds` setting (see §1). The audit had listed it only as "context". No cadence or time-of-day
> decision is needed, and the design below adds no second schedule in Windows.

## 1. The existing periodicity model (authority)

| Aspect | Finding |
|---|---|
| UI | Banco de dados → Destinos e sincronização → **"Intervalo de verificação (s)"**, hint "0 = ao alterar" (tooltip "7200 segundos = 2 horas"). |
| Storage | `configuracoes_backup.cloud_sync_interval_seconds` (key/value). Default 600 (`APP_CLOUD_SYNC_INTERVAL_SECONDS`/config). Canonical and acceptance both hold 600 today. |
| Allowed values | Any integer ≥ 0 seconds. `save_backup_settings` rejects non-integers and clamps a negative value to 0. `0` = back up on every change. |
| Kind | Interval-based, **not** clock-based: there is no time-of-day field anywhere. |
| Semantics (history) | Before UT-5 the automatic cycle was `after_request → _maybe_sync_database_snapshot(force=False)`. It ran only when the database had **changed** and at least this interval had passed since the last run. Retention and the Drive/OneDrive uploads ran only after that gate. UT-5 moved the trigger to `python -m app.backup.sync`, and the gate was left behind: it survived only in process memory (`_AUTO_SYNC_STATE`) and only for the cloud folder, and the CLI forced past it. |
| Enable/disable | There is **no global automatic-backup switch** in the SGAA. The local snapshot is always part of the cycle. The cloud folder takes part when it is configured. Google Drive and OneDrive each have their own "Incluir no backup automático" switch (`gdrive_enabled`/`onedrive_enabled`). No switch was invented. |
| Not the cadence | Política de retenção → "Intervalo de captura" decides which snapshots are **kept** per GFS window (`apply_retention_policy`). It never triggers a capture. |

## 2. Architecture chosen — polling task, SGAA decides (pattern 1)

The Windows task wakes the SGAA every **5 minutes**. `python -m app.backup.sync --scheduled` then asks
`app.backup.automatic.evaluate_due` whether a backup is due under the SGAA interval.

**Why pattern 1, not "rewrite the task when the interval changes":**
- The existing semantics are interval *plus change detection*, and `0 = ao alterar` means "on change". A Windows trigger
  cannot express either.
- The gate already existed in the app, so restoring it there keeps one source of truth.
- Changing the interval in the SGAA takes effect on the next wake. There is nothing to reconcile, and no request
  handler ever writes to Task Scheduler.

**Due rule (`evaluate_due`):**
- **First run** (no state for this database): due.
- **Content unchanged** since the last automatic backup: skip.
- **Changed, but less than the interval has passed** (60 s grace for wake jitter): skip.
- **Otherwise:** due.

**Granularity:** the 5-minute wake is a technical constant, not the cadence. Intervals of 5 minutes or more are honoured
within one wake. Intervals below 5 minutes, including `0`, behave as "at most every 5 minutes, only when changed". A
1-minute wake would cost about 1.2 s of app start-up per minute, roughly 29 CPU-minutes a day, measured.

**Change detection:** a logical digest (schema plus rows, read through SQLite, stable across WAL checkpoints). It
excludes the tables the cycle itself writes: `configuracoes_backup`, `cloud_accounts`, `backup_logs`,
`cloud_drive_settings`. Without that exclusion, each backup's own upload timestamps and token refreshes would "change"
the database.

**State file:** `<local_backup_dir>/.sgaa-automatic-backup-state`. It is JSON, keyed by the absolute database path, and
written only under the lock. It lives outside the database on purpose, because a write to the database would change the
very digest that decides "changed?". It has no `.json` extension, so it can never pass for a snapshot manifest.

## 3. Concurrency — `app.backup.lock.backup_cycle_lock`

- **Mechanism:** an OS byte-range lock (`msvcrt.locking`; `fcntl.flock` elsewhere) on `<local_backup_dir>/.sgaa-backup.lock`.
- **Held by:** the CLI (both modes), "Gerar backup agora", and both restore routes (inside `_restore_database_from_source`).
- **Busy:** the loser is refused immediately, with no waiting.
  - A scheduled wake exits 0 and logs the skip.
  - An unconditional CLI run exits 3.
  - The manual backup and the restores flash "Outro backup está em andamento. Aguarde a conclusão e tente novamente."
    (catalog term UI-C13, +1).
- **Crash safety:** the lock belongs to the open handle, so the OS releases it when the process ends, even after a crash.
  There is no stale-lock state to clean. The file itself is only an anchor.
- **Scope:** the lock sits in the local backup folder. Two runtimes sharing that folder (canonical and acceptance both use
  `D:\SGAA_BACKUPS`) are serialised too, which is correct because they also share its retention.
- **Not locked:** the per-provider "Enviar backup agora" buttons. They upload an independent zip and never delete anything,
  locally or remotely, so they cannot race the snapshot series, local retention or remote retention.

## 4. Durable run log

- **File:** `backup-automatico.log`, next to `app.log` (`APP_LOG_DIR` or `<repo>/logs`). Same formatter and
  `RotatingFileHandler` (1 MB × 3), but a separate file, because two processes rotating one file fail on Windows.
- **Contents of each run:**
  - start (trigger `scheduled`/`cli`, configured interval, database);
  - the due decision and its reason (`first_run`/`changed`/`unchanged`/`interval`), or "another cycle is running";
  - the snapshot path;
  - each destination's outcome with its reason code;
  - the retention count;
  - end with the exit code;
  - failures with a traceback.
- **Never logged:** tokens, keys or passwords. A test plants a secret in the settings and asserts it never reaches the log.

## 5. Windows task and installer — `python -m app.backup.task_scheduler`

| Setting | Value |
|---|---|
| Name | `SGAA - Backup automatico` (root folder, ASCII) |
| Action | `%LOCALAPPDATA%\SGAA\venv\Scripts\pythonw.exe -m app.backup.sync --scheduled` (resolved to absolute paths at install; `pythonw` so no console window flashes) |
| Start in | the repository root, resolved from the package location |
| Account | the installing user (SID), `LogonType=InteractiveToken`, `LeastPrivilege`. DPAPI here is CurrentUser scope (`CryptProtectData` with only `UI_FORBIDDEN`), so the task must be this user with the profile loaded. No password is asked for, stored or logged. Backups therefore run while the user is logged on, which is also when the SGAA itself runs. |
| Trigger | time trigger repeating every `PT5M` indefinitely; `StartWhenAvailable` catches up after sleep |
| Instances | `IgnoreNew` ("do not start a new instance") |
| Time limit | `PT30M` |
| Retry | none needed: the next wake 5 minutes later is the retry |
| Environment | none. The task always covers `<repo>/database.db` and never an acceptance database. |
| Secrets in the definition | none (tested) |

Commands:

| Command | What it does |
|---|---|
| `status` | Prints the effective task state. Exits 0 only when active. |
| `install [--dry-run]` | Idempotent `schtasks /Create /XML … /F`. It runs preflight checks first (Windows, user SID, venv interpreter, project layout) and re-verifies after registering. |
| `reconcile [--dry-run]` | The upgrade command. It re-installs only when the task is missing, disabled, stale or under another account. |
| `uninstall [--dry-run]` | `schtasks /Delete /F`. Idempotent. |

## 6. Effective status and header indicator

`task_scheduler.automatic_backup_status(settings, database)` reports **active** only when all of these hold:
- the SGAA configuration is valid (a local folder is set and the interval is an integer ≥ 0);
- the task exists and is enabled, with an enabled trigger;
- its command, arguments and folder are this installation's;
- the venv interpreter still exists;
- it runs as this user;
- the database being viewed is the one the task covers.

Otherwise it reports one of `not_installed`, `disabled`, `stale`, `wrong_account`, `other_database`, `config_invalid` or
`unsupported_platform`.

The Banco de dados title shows **"Backup automático ativo"** only when the status is active. It reuses the same
rectangular blue activity chip as the Google Drive / OneDrive chips (`.db-chip.is-active`), per the user's reference, so
no new colour is introduced. Its tooltip gives the 5-minute wake, the SGAA interval and the last automatic backup, all
from existing data. There is no invented next-run time.

Two situations deliberately show nothing:
- **Acceptance runtime:** it always shows nothing, because the task covers the canonical database.
- **Inactive status:** no warning UI is added. `status` on the command line gives the reason.

## 7. Pending

1. **Real installation** (not authorized in this batch): `python -m app.backup.task_scheduler install` as the user, then
   `status`.
2. Resolved: `apply_retention_policy` never deletes the **newest** `pre-restore-safety` snapshot (the undo point of the
   most recent restore, UI-C18/UI-C21); older safety snapshots follow the same GFS windows as any automatic snapshot.
   `manual-backup` snapshots remain fully exempt.
3. If the database has not changed, a wake does not retry a destination that failed on the last backup. That is the
   historical semantics; the next change retries it.
