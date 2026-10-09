# PROJECT_STATE — present state

Rewritten, never appended, when a phase closes. Process: `docs/OPERATING_MODEL.md`.
History: Git, closed SPECs (`docs/specs/`) and the verbatim pre-MP-0 archive
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
- Logical schema `prod-1` v15 on SQLite and PostgreSQL.
- PostgreSQL schema authority, runtime dialect and transaction semantics are in
  place. Two tools are qualified on local PostgreSQL 15 but not cut over: the
  Path-B cutover tool (which accepts converged legacy rows) and the Layer-2
  backup/restore tool (`tools/pg_backup.py`).
- Storage:
  - images live in the database;
  - Supabase Storage is canonical for new request documents and admin ARQUIVOS
    (direct signed TUS);
  - Google Drive is the asynchronous mirror, maintained by the operator CLI
    `python -m app.storage.cli` (`mirror-run`, `mirror-requeue`);
  - the same CLI provides `census`, `verify` (cross-check of references,
    canonical objects, bucket and mirrors) and `converge` (legacy Google /
    local → canonical, dry run by default);
  - a legacy row with a canonical reference is canonical custody in every
    runtime path;
  - nothing runs the worker automatically yet.

## Status

- Refactor, PostgreSQL readiness and real-PG qualification fronts: closed.
- STORAGE S1–S3: CLOSED_AND_PUBLISHED. MP-0 (governance): CLOSED.
- MP-1 storage convergence: CLOSED (`docs/specs/MP-1-storage-convergence.md`).
- Active macro-phase: MP-2 hosting readiness — SPEC FROZEN
  (`docs/specs/MP-2-hosting-readiness.md`).

## Production readiness: NOT_READY_FOR_PRODUCTION_INTEGRATION

- Operational runtime: the local Windows workstation on SQLite `database.db`
  (canonical, real student data — never in prompts); SQLite file backups
  scheduled by Windows Task Scheduler; Google is the active cloud connection,
  OneDrive deferred.
- Production web runtime: DEFERRED (Phase C — public HTTPS URL, `APP_SECRET_KEY`,
  `TOKEN_ENCRYPTION_KEY`, binding/proxy, production preflight and smoke, admin).
- Open before production, assigned in the roadmap:
  - mirror scheduler trigger;
  - persistent upload storage / read-only filesystem;
  - object-byte backup;
  - real-data census and legacy convergence, including decisions on terminal
    legacy rows and unsupported legacy content;
  - a first supervised live Drive mirror run (no DEV Google environment exists);
  - Layer-1 backup / PITR;
  - Supabase PostgreSQL version and empty-target qualification;
  - `SUPABASE_DATA_API_DISABLED`;
  - cross-environment backup/restore proof;
  - Supabase / Vercel integration;
  - pre-go-live security review.
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
  detached with ≥5 GB free RAM.

## Known test debt (not blockers)

Baseline full suite is not green: six `xlwt` collection errors plus
`tests/test_pytest_runtime_isolation.py::TestSentinelSurvival` (same cause);
`tests/test_ut_mx3_matrix_validation_debt_closure.py::test_student_matrix_error_catalog_delta_is_exact_and_bounded`
(549 vs 548); `tests/test_request_version_display_authority.py`
`[canonical-v1-snapshot-v3]`, non-hermetic (random CSRF token containing `v3`).

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| MP-0 | Spec-driven governance transition | CLOSED |
| MP-1 | Storage convergence — Drive mirror worker (S4); legacy-migration tooling, census, DEV rehearsal (S5); storage reconciliation | CLOSED |
| MP-2 | Hosting readiness — read-only filesystem, environment-only secrets, scheduler trigger (mirror worker included), object-byte backup (S7, part of S6) | IN PROGRESS |
| MP-3 | Production integration / cutover — S8, Phase C, real-data census and convergence, first live mirror run, DR proof, security review | NOT STARTED |
| MP-4 | Legacy contraction after the rollback window — legacy document paths and bytes, SQLite file backup, Windows scheduler, purge policy (rest of S6) | NOT STARTED |

Authorities: `docs/OPERATING_MODEL.md` · active SPEC · `docs/ENGINEERING_STANDARDS.md`
· `docs/TEST_EXECUTION_POLICY.md` · index `docs/DOCUMENTATION_INDEX.md`.
