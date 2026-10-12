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
- MP-3 production integration / cutover: IN PRODUCTION, C12 OPEN_PONR_PENDING
  (`docs/specs/MP-3-production-integration.md`; cutover ledger outside the repository). The
  opening was recorded on 2026-10-12; admission is PAUSED (the governed operator-only deployment
  promoted; the opening authorization stands, no write barrier) for the pre-PONR product-contract
  remediation A19: the operator-visible PostgreSQL backup posture and the Microsoft integration
  the mail transport depends on, both removed or deferred during the hosted transition without
  the user's authorization. C13 (PONR) is not recorded; re-opening needs the user's GC2.

## Production

- Web runtime: Vercel Hobby project `sgaa` (`https://sgaa.vercel.app`), Supabase Free PROD
  `sgaa-prod` (`uckadhcwfknklmdktuyi`) holding the migrated data, canonical storage bucket and the
  Google Drive mirror (proven at C11). Every PROD action follows the runbook and the ledger.
- Backups: operator-run governed generations (`tools/ops_backup.py --ledger-dir`) on the cadence
  recorded at the opening, restore drills, an off-platform copy; their records are published into
  PROD for the Banco de dados page (A19).
- The workstation SQLite runtime is stopped and frozen: the rollback asset until the window
  closes (C14); its contraction is MP-4.
- Residuals recorded by MP-2 (no hosting impact today): `main.py` still attaches a file handler
  when its directory is writable; the scratch path is predictable on a shared POSIX temp
  directory; a report `descricao` is bounded only by the request size.
- Agreed outside MP-1…MP-4, no recorded execution: reconcile/import the official
  deferred-hours spreadsheet.

## Environment facts

- Supabase DEV `sgaa-dev` (`pkwtgqsiulzeqkqlsdou`): rehearsals use run-owned
  resources only, and there is no persistent bucket. Its bucket `/empty` is
  asynchronous: delete objects before the bucket.
- Supabase PROD `sgaa-prod` (`uckadhcwfknklmdktuyi`): every action on it is a user gate.
- The DEV rehearsal credential is still active outside the repository; the user
  revokes it when rehearsals end.
- Real-PG lanes need `SGAA_PG_TEST_URL` (local PostgreSQL 15 or 17; the PROD major is 17);
  without it they skip and real-PG evidence is ABSENT. Native client tools: `SGAA_PG_BIN_DIR`.
  The live DEV rehearsal is opt-in: `SGAA_MP3_REHEARSAL=1` plus the DEV credential file. Full suite: ~5,000 tests, ~36 min; run
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
| MP-3 | Production integration / cutover — S8, Phase C, real-data census and convergence, first live mirror run, DR proof, security review | C12 OPEN_PONR_PENDING; admission paused for the pre-PONR remediation A19; C13 and C14 pending |
| MP-4 | Legacy contraction after the rollback window — legacy document paths and bytes, SQLite file backup, Windows scheduler, purge policy (rest of S6) | NOT STARTED |
