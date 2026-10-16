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
  place. The production database is hosted in Supabase PostgreSQL 17; Path-B
  migration, governed Layer-2 backup/restore and the production cutover are recorded.
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
    deployed authenticated scheduler front `app.storage.scheduler:application`.
    The backup endpoint is also called by Supabase Cron every 15 minutes;
    Vercel Hobby supplies the daily mirror and backup fallback.
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
- MP-3 production integration / cutover: IN PRODUCTION, **C13 PONR_RECORDED**
  (`docs/specs/MP-3-production-integration.md`; governed ledger outside the repository).
  Public admission is OPEN, with no write barrier or unresolved ledger act.
  C14 remains UNRECORDED, with A21's exceptional restitution window ACTIVE
  (the historical `BACKUP_CADENCE_BROKEN` is permanently preserved).
  The historical seq 89 (2026-10-13T15:07:54Z) to seq 94
  (2026-10-15T20:07:04Z) gap is 52 h 59 m 10 s, exceeding C12's 36 h
  allowed interval. The owner authorized GX2; per the operator's verified
  local-ledger execution report, grant seq 110 and the single
  `cadence_exception` seq 111 are recorded with classification
  `NOT_COMPLIANT_HISTORICAL`, 111 entries, chain OK and final head
  `f90b62598491d9244030d529b817c9ffffb72f609331023d6d44813132526e25`.
  C13 remains at seq 83 with no unresolved operations. The 30-day prospective
  qualifying window is derived from the last healed breach at
  2026-10-15T20:07:04Z; the earliest possible completion is
  2026-11-14T20:07:04Z, conditional on uninterrupted governed cadence,
  a post-window generation/restore drill and the separate C14 authorization.
  The post-C13 prior drill (seq 109) passed but cannot substitute for a fresh
  post-window drill. No GX2 grant or exception was created from this documentation
  update. MP-4 remains blocked until an actual C14 entry.
- A19 is deployed (operator-visible PostgreSQL backup posture and Microsoft integration).
  A20 hosted automation is in PROD: commit `ffa2749`, deployment
  `dpl_Att7FUkPuzyj63yk12kE3Zp79L3E`, smoke 11/11. Supabase Cron calls the
  bearer-authenticated backup endpoint every 15 minutes. One triggered due pass
  produced a complete hosted snapshot to Google Drive and OneDrive on 2026-10-15
  22:05 UTC (two snapshot and two CSV file receipts, zero delivery failures).
  The first subsequently scheduled DUE pass is still awaiting observation;
  a no-op scheduled wake returned HTTP 200/NOT_DUE. The configured policy is the
  default 24 h database / 7 d objects / 2 retained / 30 d restoration drill.

## Production

- Web runtime: Vercel Hobby project `sgaa` (`https://sgaa.vercel.app`), Supabase Free PROD
  `sgaa-prod` (`uckadhcwfknklmdktuyi`) holding the migrated data, canonical storage bucket and the
  Google Drive mirror (proven at C11). Every PROD action follows the runbook and the ledger.
- Backups: the production A20 scheduler runs on the hosted platform; it records
  complete deliveries to every connected drive. The separate operator-run governed
  Layer-2 generations (`tools/ops_backup.py --ledger-dir`) and off-platform copies
  remain mandatory through C14 and are not replaced by the A20 receipts.
  The governed post-C13 generation from 2026-10-15T20:07:04Z was restored
  into a new isolated PostgreSQL 17 scratch database on 2026-10-15: 39 tables
  and 2 objects verified; the restore was recorded as cutover ledger seq 109
  (DRILL_VERIFIED, head 668b0ab7...). Scratch was removed after verification;
  PROD data and configuration were untouched. This was a governed Layer-2
  generation, NOT the separate A20-generated hosted snapshot. The drill
  receipt is in the cutover ledger; its publication to the PROD Banco de dados
  posture remains pending via the governed `ops_backup publish` procedure.
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
| MP-3 | Production integration / cutover — S8, Phase C, real-data census and convergence, first live mirror run, DR proof, security review | C13 PONR_RECORDED; admission OPEN, A19 deployed, A20 S5 operational with first hosted backup verified; autonomous due wake and C14 pending |
| MP-4 | Legacy contraction after the rollback window — legacy document paths and bytes, SQLite file backup, Windows scheduler, purge policy (rest of S6) | NOT STARTED |
