# REF-0TF-B — D73H Historical Verification Isolation

## Scope

Test-only isolation of the 17 D73H historical-data-dependent tests on
`refactor/architecture-safety-net`, starting at `d8dab45`.

No production code, template, static asset, schema, database, environment,
dependency, RBAC, or route-modularization change was made.

## Starting state

- Branch: `refactor/architecture-safety-net`
- Starting HEAD: `d8dab4579241c4209c9c3716de85dde36b264427`
- `origin/main...HEAD = 0 5`
- Clean working tree, empty staging, no untracked files.

## Root cause

`tests/test_d73h_reconciliation_apply.py` defined module-level
`REAL_DB_PATH = ROOT / "database.db"`,
`PRE_APPLY_BACKUP_PATH = ROOT / "backups" / "database.pre-d73j-live-apply-20260612-165031.db"`,
and `_resolve_pre_apply_source()` which searched backup globs with a final
fallback to the repository-root `database.db`.  All 17 historical tests
depended on these implicit repository-root artifact paths, making them
non-hermetic and unportable to clean checkouts.

## Implementation

### Marker and CLI options

A dedicated pytest marker `d73h_historical` was registered in `pytest.ini`.

Three new CLI options were added in `tests/conftest.py`:

| Option | Purpose |
|--------|---------|
| `--run-d73h-historical` | Enable the historical lane |
| `--d73h-source-db PATH` | Path to a sanitized source database |
| `--d73h-source-backup PATH` | Path to a sanitized source backup |

### Default deselection

When `--run-d73h-historical` is absent, `pytest_collection_modifyitems`
deselects every test carrying the `d73h_historical` marker via
`config.hook.pytest_deselected(items=deselect)`.  No skip, skipif, xfail,
or xpass mechanism is used.

### Explicit historical contract

When `--run-d73h-historical` is present:

- Both `--d73h-source-db` and `--d73h-source-backup` are mandatory.
- Missing options raise `pytest.UsageError` before any historical test executes.
- Supplied paths are validated once during collection, before historical test setup:
  - Both must exist and be regular files.
  - Neither may be the repository-root `database.db`.
  - Neither may be inside the repository `backups/` directory.
- Validated paths are exposed through the session-scoped `d73h_sources` fixture.

### Changes to tests/test_d73h_reconciliation_apply.py

- Removed: `REAL_DB_PATH`, `PRE_APPLY_BACKUP_PATH`, `_resolve_pre_apply_source()`
- Removed: backup glob fallback, implicit repository-root artifact references
- Changed: `_prepare_copy_and_backup(tmp_path, source_db, source_backup)` takes
  explicit source paths, copies them to `tmp_path`, and invokes
  `_remove_target_from_copy` on both temporary copies (never mutates originals)
- Changed: `_prepare_post_apply_copy_and_backup` takes explicit source paths
- Marked exactly 17 tests with `@pytest.mark.d73h_historical`
- Refactored `test_apply_refuses_live_db_and_forbidden_database_db_basename`:
  uses the tool's `connect_apply_copy` guard function directly on a
  temporary path (not `ROOT/database.db`)
- Refactored `test_cli_refuses_unknown_force_flag_as_out_of_scope_operation`:
  uses `tmp_path` dummy path instead of `REAL_DB_PATH`
- Preserved all 18 existing test names
- Preserved every historical behavioral expectation: no deletion, weakening,
  skip, xfail, or generalization; the live-path guard is exercised directly
  through `connect_apply_copy` with equivalent guard coverage
- `_remove_target_from_copy` executes on both temporary copies with its safety
  assertions intact

### The one hermetic D73H test

`test_cli_refuses_unknown_force_flag_as_out_of_scope_operation` remains
unmarked and part of the standard suite.  It tests argparse failure before
any file access.

## Validation

### Default D73H collection

```
python -m pytest tests/test_d73h_reconciliation_apply.py --collect-only -q
1/18 tests collected (17 deselected)
Exit: 0
```

### Default D73H execution

```
python -m pytest tests/test_d73h_reconciliation_apply.py -q --tb=short
1 passed, 17 deselected in 1.23s
Exit: 0
```

### Negative contract — missing options

```
python -m pytest tests/test_d73h_reconciliation_apply.py --run-d73h-historical -q --tb=short
ERROR: --run-d73h-historical requires --d73h-source-db PATH
--run-d73h-historical requires --d73h-source-backup PATH
no tests ran in 0.05s
Exit: nonzero
```

### Negative contract — nonexistent paths

```
python -m pytest tests/test_d73h_reconciliation_apply.py
  --run-d73h-historical
  --d73h-source-db nonexistent-db.sqlite3
  --d73h-source-backup nonexistent-backup.sqlite3
  -q --tb=short
ERROR: --d73h-source-db path does not exist: ...
no tests ran
Exit: 4
```

### Full collection

```
python -m pytest --collect-only -q
538 discovered, 17 deselected, 521 selected
Exit: 0
```

### Full suite

```
python -m pytest -q --tb=short
521 passed, 17 deselected in 244.52s
Exit: 0
0 failed, 0 errors, 0 skipped, 0 xfailed, 0 xpassed
```

### Positive historical lane

**NOT RUN** — sanitized historical artifacts were unavailable and real
database/backup artifacts were prohibited.

## Disposable worktree

- R1 validation path: `C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0tf-b-r1-validation`
- R1 validation HEAD: `873c168` (temporary amended validation carrier)
- Contents: clean checkout with no `database.db`, `backups/`, `.env`,
  `uploads/`, `documentos_alunos/`, junction, or symlink to the primary workspace
- Side effects before removal: only CSRF inventory JSON artifacts modified
  by test execution (`csrf_inventory_shadow_off.json`,
  `csrf_inventory_shadow_on.json`)
- Removed after evidence capture (permission warning on stale worktree
  metadata is consistent with prior phases)

## No production/database/RBAC/modularization changes

Only the six authorized files were changed.  No production code, database,
RBAC policy, route structure, schema, migration, template, static asset,
environment, or dependency was modified.

## Remaining risk

The historical lane still requires separately approved sanitized artifacts
for positive execution.  This phase only isolates the guard and proves the
standard suite is hermetic without real data access.

## Status

**Implemented and locally validated.**  Pending Codex repository inspection
review.

## No subsequent phase authorized

RBAC remediation, route modularization, and any phase beyond REF-0TF-B
remain prohibited.
