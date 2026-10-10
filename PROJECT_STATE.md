# PROJECT_STATE — present state

Rewritten, never appended, when a phase closes. Process: `docs/OPERATING_MODEL.md`.
History: Git, closed SPECs (`docs/specs/`) and the verbatim pre-MP0 archive
`docs/history/PROJECT_STATE_PRE_MP0_2026-10-09.md`, which also holds the carried
non-blocking findings of closed fronts (each SPEC imports those in its scope).

## Repository

- `origin` = `github.com/genesismazeto-sys/SGAA`. Development branch:
  `refactor/design-system-foundation` (HEAD: `git rev-parse HEAD`).
- Protected, no action without explicit user authorization: `main` (`340fc7c`)
  and `clean-baseline` (pull-request base).

## Architecture

- Flask; composition root `app/__init__.py::create_app`; `main.py` is a frozen
  compatibility facade. Structural refactor complete.
- Logical schema `prod-1` v16 on SQLite and PostgreSQL (v16 adds two empty, ephemeral
  tables: `auth_throttle_events`, `admin_import_previews`).
- PostgreSQL schema authority, runtime dialect and transaction semantics are in
  place. Two tools are qualified on local PostgreSQL 15 but not cut over: the
  Path-B cutover tool (which accepts converged legacy rows) and the Layer-2
  backup/restore tool (`tools/pg_backup.py`).
- Runtimes (`docs/HOSTED_RUNTIME.md` is the operator contract):
  - `local` (default): the Windows workstation, development, tests — unchanged;
  - `hosted` (`SGAA_RUNTIME=hosted`, declared, never inferred): PostgreSQL only,
    scratch-only disk, environment-only secrets (the DPAPI store is never read or
    written), fixed-code startup blockers, durable login/recovery throttling and
    import previews in the database, and a PostgreSQL-coherent Banco de dados page.
    Readiness: `python -m app.hosting_cli check [--database]`.
- Storage:
  - images live in the database;
  - Supabase Storage is canonical for new request documents and admin ARQUIVOS
    (direct signed TUS);
  - Google Drive is the asynchronous mirror, run by the operator CLI
    `python -m app.storage.cli` (`mirror-run`, `mirror-requeue`) or by the
    authenticated scheduler front `app.storage.scheduler:application`
    (`CRON_SECRET`; its own function, nothing deploys it yet);
  - the same CLI provides `census`, `verify` (cross-check of references,
    canonical objects, bucket and mirrors), `converge` (legacy Google / local →
    canonical, dry run by default) and the object-byte backup
    (`backup-objects`, `verify-backup`, `restore-objects`: sealed set, offline
    verification, restore that never overwrites or deletes);
  - a legacy row with a canonical reference is canonical custody in every
    runtime path; legacy local documents are unavailable when hosted until
    converged.

## Status

- Refactor, PostgreSQL readiness and real-PG qualification fronts: closed.
- STORAGE S1–S3: CLOSED_AND_PUBLISHED. MP-0 (governance): CLOSED.
- MP-1 storage convergence: CLOSED (`docs/specs/MP-1-storage-convergence.md`).
- MP-2 hosting readiness: CLOSED (`docs/specs/MP-2-hosting-readiness.md`).
- MP-3 production integration / cutover: ACTIVE, SPEC FROZEN
  (`docs/specs/MP-3-production-integration.md`), awaiting the R3 SPEC acknowledgement.
  No implementation and no PROD action before it.

## Production readiness: NOT_READY_FOR_PRODUCTION_INTEGRATION

- Operational runtime: the local Windows workstation on SQLite `database.db`
  (canonical, real student data — never in prompts); SQLite file backups
  scheduled by Windows Task Scheduler; Google is the active cloud connection,
  OneDrive deferred.
- Production web runtime: DEFERRED. The application is hosting-ready in code and
  rehearsed on DEV; nothing is deployed.
- Open before production, assigned in the roadmap (MP-3 unless stated):
  - Vercel project and descriptor files, environment wiring, region and
    `maxDuration`, the cron entry, platform rate limiting / WAF in front of the
    login (a flood of distinct keys still writes a throttle row per request);
  - Supabase PostgreSQL version and empty-target qualification, Layer-1 backup /
    PITR, cross-environment backup/restore proof, `SUPABASE_DATA_API_DISABLED`;
  - real-data census and legacy convergence, including decisions on terminal
    legacy rows and unsupported legacy content;
  - a first supervised live Drive mirror run (no DEV Google environment exists);
  - scheduled object backup and an independent off-platform object copy (the
    operator set is the only copy beyond the provider's);
  - public HTTPS URL, `APP_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, production
    preflight and smoke, administrator bootstrap;
  - pre-go-live security review.
- Residuals recorded by MP-2 (no hosting impact today): `main.py` still attaches
  a file handler when its directory is writable; the scratch path is predictable
  on a shared POSIX temp directory; a report `descricao` is bounded only by the
  request size (a cap needs a catalogued message and a baseline ledger term).
- Agreed outside MP-1…MP-4, no recorded execution: reconcile/import the
  official deferred-hours spreadsheet.

## Environment facts

- Supabase DEV `sgaa-dev` (`pkwtgqsiulzeqkqlsdou`): rehearsals use run-owned
  resources only, and there is no persistent bucket. Its bucket `/empty` is
  asynchronous: delete objects before the bucket.
- Supabase PROD `sgaa-prod` (`uckadhcwfknklmdktuyi`) is untouched; every action on
  it is a user gate.
- The DEV rehearsal credential is still active outside the repository; the user
  revokes it when rehearsals end.
- Real-PG lanes need `SGAA_PG_TEST_URL` (local PostgreSQL 15); without it they
  skip and real-PG evidence is ABSENT. Full suite: ~5,000 tests, ~36 min; run
  detached with ≥5 GB free RAM, from a clean checkout (the project-root
  isolation guard fails the session when another process writes there).

## Known test debt (not blockers)

Baseline full suite is not green: six `xlwt` collection errors plus
`tests/test_pytest_runtime_isolation.py::TestSentinelSurvival` (same cause);
`tests/test_ut_mx3_matrix_validation_debt_closure.py::test_student_matrix_error_catalog_delta_is_exact_and_bounded`
(549 vs 548); `tests/test_request_version_display_authority.py`
`[canonical-v1-snapshot-v3]`, non-hermetic (random CSRF token containing `v3`);
`tests/test_ut5_backup_package.py::test_cli_backup_sync_runs_isolated_with_app_context_only`
needs the gitignored `database.db`, so it fails in a clean worktree.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| MP-0 | Spec-driven governance transition | CLOSED |
| MP-1 | Storage convergence — Drive mirror worker (S4); legacy-migration tooling, census, DEV rehearsal (S5); storage reconciliation | CLOSED |
| MP-2 | Hosting readiness — read-only filesystem, environment-only secrets, scheduler trigger (mirror worker included), object-byte backup (S7, part of S6) | CLOSED |
| MP-3 | Production integration / cutover — S8, Phase C, real-data census and convergence, first live mirror run, DR proof, security review | ACTIVE — SPEC FROZEN, awaiting acknowledgement |
| MP-4 | Legacy contraction after the rollback window — legacy document paths and bytes, SQLite file backup, Windows scheduler, purge policy (rest of S6) | NOT STARTED |
