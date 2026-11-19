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
- Logical schema `prod-1` v19 in the repository on SQLite and PostgreSQL (v17 permits activity
  correction; v18 expands the notification decision CHECK to include Devolvida, with no backfill;
  v19 adds the DOCX fill-in templates of activity versions, purely additive).
  The processing repairs and controlled recovery are documented in `docs/request-processing-corrections.md`;
  the activity documentation guidance and templates in `docs/activity-document-guidance.md`.
  PROD PostgreSQL is v18: the GF1 of `5b989cd` (2026-10-20, ledger seq 190-199) upgraded it
  from v17, and the GF1 of `a5b912a` (seq 202-209, the code in production) kept it; the daily
  governed generations, which validate the exact version, run from the v18 worktree of
  `5b989cd`. v19 reaches PROD only through a separately authorized GF1 that runs
  `python -m app.pg_schema upgrade` (exactly v16, v17 or v18 -> v19) before the v19 code is
  deployed and repins the daily backup worktree in the same session
  (`docs/activity-document-guidance.md`, Publication).
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
  - Supabase Storage receives new request documents and admin ARQUIVOS
    (direct signed TUS) and is their staging copy and durable fallback;
  - Google Drive and OneDrive hold the permanent copies, each mirrored
    independently by the operator CLI `python -m app.storage.cli`
    (`mirror-run [--provider onedrive]`, `mirror-requeue`) or by the deployed
    authenticated scheduler front `app.storage.scheduler:application`, which
    also releases a staging copy once every connected drive's copy is read back
    and proven (`release-run`); reads then come from a verified drive copy.
    The OneDrive copy and staging state live in `sgaa_ops` (PostgreSQL only);
    documents uploaded before the activation keep their Supabase copy until the
    operator's bounded `staging-backfill --apply` enrolls them.
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
- MP-3 A22 (`docs/specs/MP-3-A22-request-reclassification.md`): a student or administrator
  corrects the activity of an editable request in place (schema v17). In PROD since gate G1
  on 2026-10-19 (upgrade to v17, then the GF1 deploy of `f559e3d`, ledger seq 173-181).

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
`tests/test_request_version_display_authority.py`
`[canonical-v1-snapshot-v3]`, non-hermetic (random CSRF token containing `v3`);
`tests/test_ut5_backup_package.py::test_cli_backup_sync_runs_isolated_with_app_context_only`
needs the gitignored `database.db`, so it fails in a clean worktree.

Eight guards fail on the development branch since before the Acesso
corrections of 2026-11-18 (identical on the untouched prior head; not fixed):

- `tests/test_b11_category_a_tokenization.py`:
  `test_field_fills_accent_primary_hover_and_focus_use_their_tokens`,
  `test_surface_layer_fills_use_the_surface_token`,
  `test_info_and_danger_families_are_used_at_their_current_values` -- the
  selectors they read (`#req-presets-modal …`, `.presets-ph:hover`) no longer exist;
- `tests/test_ds_pill_radius.py::test_no_stylesheet_restores_a_fully_rounded_pill`
  -- `.presets-ph` in `static/css/components/request-presets.css` uses `999px`;
- `tests/test_pg_readiness_unit5d_ptbr_portability.py`:
  `test_control_u5a_current_state_authority_untouched` and
  `test_control_u5a_guard_still_detects_an_undeclared_change` -- the baseline
  version list now ends at v19, the guard expects it to end at v17;
- `tests/test_pg_readiness_unit5f_untyped_null_query.py::test_production_sql_has_no_placeholder_is_null_predicate`
  -- `app/storage/copy_registry.py:108` `SELECT to_regclass(?) IS NOT NULL`;
- `tests/test_status_badge_semantics_ui_b02_b03.py::test_b4_shared_tones_are_only_within_one_semantic_category`
  -- it expects the caution tone to hold only Pendente and Encerrada; Devolvida
  now shares it.

A ninth fails identically on `a8922ad`:
`tests/test_ui_corrections_batch3.py::test_form_note_hidden_rule_changes_no_existing_consumer`
-- `admin_acesso.html`'s e-mail batch notes (`#access-email-replace` and one
more) start `hidden`, which the guard expects no consumer to do.

Three real-PostgreSQL tests fail too, identically on the untouched prior head:
`tests/test_storage_s2_real_pg.py::test_fresh_v14_authority_validates_and_is_empty`
and `tests/test_storage_s3a_real_pg.py::test_pg_authority_is_v15` still pin head
v16; `tests/test_mp2_scheduler_real_pg.py::test_overlapping_invocations_mirror_each_object_exactly_once`
gets one HTTP 500 (`InternalError`) among overlapping mirror invocations.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| MP-0 | Spec-driven governance transition | CLOSED |
| MP-1 | Storage convergence — Drive mirror worker (S4); legacy-migration tooling, census, DEV rehearsal (S5); storage reconciliation | CLOSED |
| MP-2 | Hosting readiness — read-only filesystem, environment-only secrets, scheduler trigger (mirror worker included), object-byte backup (S7, part of S6) | CLOSED |
| MP-3 | Production integration / cutover — S8, Phase C, real-data census and convergence, first live mirror run, DR proof, security review | C13 PONR_RECORDED; admission OPEN, A19 deployed, A20 S5 operational with first hosted backup verified; autonomous due wake and C14 pending |
| MP-4 | Legacy contraction after the rollback window — legacy document paths and bytes, SQLite file backup, Windows scheduler, purge policy (rest of S6) | NOT STARTED |
