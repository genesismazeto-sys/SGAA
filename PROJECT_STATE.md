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
  PROD PostgreSQL 17 is v19 (41 tables): the GF1-V19 of `4087eaf` (2026-11-19, ledger seq
  239-250) upgraded it from v18 with `python -m app.pg_schema upgrade` in one transaction, after
  a preserved, restore-drilled pre-migration generation; earlier, the GF1 of `5b989cd` (seq
  190-199) took it from v17 to v18. The daily governed generations, which validate the exact
  version, run from the v19 worktree of `4087eaf` (`docs/activity-document-guidance.md`,
  Publication).
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
- OPS-LOG-01, governed daily backup logging reliability (R2): CLOSED locally under a publication
  HOLD (local commits, not pushed, not installed).
- MP-3 A22 (`docs/specs/MP-3-A22-request-reclassification.md`): a student or administrator
  corrects the activity of an editable request in place (schema v17). In PROD since gate G1
  on 2026-10-19 (upgrade to v17, then the GF1 deploy of `f559e3d`, ledger seq 173-181).
- GF1-V19 (2026-11-19, owner-authorized, completed and accepted): published `4087eaf`
  (UX-ACCESS-01, SEC-REVOCATION-01, 7-day first-access links, UX-REPORTES-01, COMPROVANTES-01,
  MOBILE-01) with the v18 -> v19 upgrade. Ledger seq 239 pre-migration v18 generation (preserved
  outside rotation), 240 its PostgreSQL 17 restore drill, 241 the GF1 grant, 242 post-migration v19
  generation, 243 daily v19 generation, 244-249 deployment, authorize-code and promotion (both
  COMMITTED), 250 restore drill of the v19 generation 242 (41 tables). Every generation and both
  drills VERIFIED; the strict v19 proof matched the rehearsed catalog. Anonymous production smoke
  (`tools/hosted_smoke.py`) PASS 10/10. The authenticated manual smoke (`SMOKE_V19.md` in the GF1
  folder) is PENDING with the owner. C14 and the historical visual-gate exception (baselines
  stale since 2026-08-14, none re-approved; `docs/design-system/README.md` §8, Harness) are
  unchanged by this operation. Three operational failures, none of them in PROD, are recorded with their
  resolutions in the GF1 folder's README (outside the repository):
  1. Run 1 died silently at the drill wait, before the grant (PROD unchanged): Windows PowerShell
     5.1 `Add-Content` opens a file without sharing reads, an executor's `tail -F` observer held
     `execution.log`, and `Write-Log` threw on the main path and again inside the catch, losing
     the STOPPED line. Resolution: `Write-Log` in `run_gf1_v19.ps1` and `drill_terminal.ps1` appends
     with shared read/write access, retries for 5 s, continues in a fallback file and stops only
     when no file takes the line (validated locally against the observers involved). The anchor
     check admits only backup entries, so the owner re-anchored `$InitialHead` to the head after
     run 1's generation (seq 237) and drill (seq 238); both stay in the ledger and the seq-237
     preserved copy is kept aside, hash-verified.
  2. Run 2 committed the upgrade, validated v19 and took generation 242, then stopped with
     `DAILY_V19_GENERATION_NOT_NEW` before any deployment: the laptop was on battery, the daily
     task has `DisallowStartIfOnBatteries`, so `Start-ScheduledTask` left it Queued, and the wait
     loop took any state but Running for finished. Resolution: a resume script, on AC power, whose
     constants, functions and deploy-to-final-status block are byte copies of `run_gf1_v19.ps1`,
     with a wait that requires state Ready, result 0 and a new verified ledger generation.
  3. Resume 1 stopped with `DAILY_V19_RUN_FAILED` (no deployment): a defect of the resume script
     itself, since PowerShell 5.1 returns a single row as a bare object whose `.Count` is `$null`,
     while the queued task had already produced generation 243. Resolution: the calls wrapped in
     `@(...)`, validated against the real ledger; resume 2 completed.

## Production

- Web runtime: Vercel Hobby project `sgaa` (`https://sgaa.vercel.app`), Supabase Free PROD
  `sgaa-prod` (`uckadhcwfknklmdktuyi`) holding the migrated data, canonical storage bucket and the
  Google Drive mirror (proven at C11). Every PROD action follows the runbook and the ledger.
- Code in production: `4087eaf7353f3d3effff40255c73f8221ce20f74`, deployment
  `dpl_2PX2spzLjgTeNgrN9taFFSM9tsJo` (served code digest `902a0be4…`, verified at the public
  address), schema v19. The Vercel project has no Git connection: pushes deploy nothing; every
  deployment is `tools/deploy_audit.py deploy` under a GF1.
- Cutover ledger (outside the repository): C13, 250 entries, chain OK, head `149e52dc…`, no
  unresolved operation and no write barrier (2026-11-19).
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
- The daily governed backup task (Windows Task Scheduler, 20:00) runs
  `D:\SGAA_CUTOVER\daily_governed_backup.ps1` from the v19 worktree of `4087eaf` since GF1-V19; its
  last run (2026-11-19, generation seq 243, schema 19) succeeded. It does not start on battery
  (`DisallowStartIfOnBatteries`): it waits, queued, for AC power.
- The installed copy still logs with Windows PowerShell 5.1 `Add-Content`, which refuses to append
  while any process holds the log open and, under the script's `Continue`, drops the line silently:
  the run completes, but its log lines -- the failure reason included -- are lost. Until the
  corrected wrapper is installed, nothing may hold `daily_governed_backup.log` open while it runs.
  The correction is OPS-LOG-01 (`docs/specs/OPS-LOG-01-daily-backup-logging.md`): the repository
  now holds the wrapper, `tools/daily_governed_backup.ps1` (shared-mode append, bounded retry, a
  per-run fallback file; backup, ledger and exit-code contracts unchanged). Installing it replaces
  the deployed copy, needs a separate owner authorization and follows the SPEC's §9; it is not part
  of a GF1 (`tools/` is outside the deployment export).
- The workstation SQLite runtime is stopped and frozen: the rollback asset until the window
  closes (C14); its contraction is MP-4.
- Residuals recorded by MP-2 (no hosting impact today): `main.py` still attaches a file handler
  when its directory is writable; the scratch path is predictable on a shared POSIX temp
  directory; a report `descricao` is bounded only by the request size.
- Agreed outside MP-1…MP-4, no recorded execution: reconcile/import the official
  deferred-hours spreadsheet.
- Next GF1 release candidate (owner hold: not deployed, no migration): the development-branch
  head, carrying UI-B46 and DIAG-500 (below), the COMPROVANTES-01 correction (required proofs are
  short names; the older regulation sentence is never listed; model titles and file names wrap
  instead of being cut at any width), UI-B40 (a closed request reads Indeferida), OPS-LOG-01 (not installed) and BL-02
  (UI-B41 the processing page reads the request's frozen record; UI-B42 the request lists keep
  Status in view through the shared DS status column, DS README section 2.6b; UI-B43 the KPI
  cards stack on a phone; UI-B44 a long proof name opens whole while edited; UI-B45 the student
  guidance says what every proof must hold; `docs/backlog/UI_ACCEPTANCE_BACKLOG.md`). The owner
  accepted COMPROVANTES-01 and UI-B40 in VA-01 and the five BL-02 items on 2026-11-20 (isolated
  local runtimes, synthetic data; packages outside the repository, `D:\SGAA_tmp\va01\package` and
  `D:\SGAA_tmp\bl02\package`). Schema stays v19, so its GF1 has no upgrade step; PROD keeps the
  v19 artifact of `4087eaf` until then. Qualification: the full suite at `8c8d8e0` found no
  product regression; BL-02 is delta-qualified against it (TEP section 6: an independent review,
  whose one material finding, a lost touch tap, is fixed; the mechanically selected impact set
  and permanent guards rerun on the final code, failing only the known guards below). Results and
  the GF1 plan are outside the repository (`D:\SGAA_tmp\rc_8c8d8e0`, `D:\SGAA_tmp\bl02\dq` and
  the consolidated report beside them); for that content the served code identity changes from
  `902a0be4…` to `a7cdcfef…` (16 files). That qualification and identity predate UI-B46 and
  DIAG-500: GF1 publication qualification of the integrated head is the next, separate
  milestone, and publication waits for it and the owner's GF1 authorization.
- Still awaiting the owner, separate from the release: the 28 historical UI rows awaiting visual
  confirmation (none has an acceptance on record) and UI-B15 (clean in Chromium; the owner's own
  Chrome decides).
- UI-B46 (AUTH-RECOVERY-01 / UI-LOGIN-ERROR-01), accepted by the owner 2026-11-20 and integrated
  into the development branch with DIAG-500 on 2026-11-21 (not deployed): a dead password link
  renders the DS recovery card (`docs/design-system/README.md`
  §2.6f) and resends through the existing self-service recovery, pre-filling the address only when
  safe; every feedback message of the public auth pages is the shared DS auth alert (§2.6g); the
  owner's Alertas colours are the DS's one alert palette (`--alert-*`, §2.1); Inter has one owner
  for every document; the Requisições e-mail confirmation and the versioned-activities diagnostic
  page are fully on DS tokens and components. Package and evidence outside the repository
  (`D:\SGAA_tmp\auth_recovery01`).
- DIAG-500 (`docs/specs/DIAG-500.md`, CLOSED), accepted by the owner and integrated into the
  development branch on 2026-11-21 (not deployed): the versioned-activities diagnostic routes answer
  an unknown, zero, negative-but-absent, out-of-range or malformed id, or an unknown Turma code,
  with 404 and the UI-B46 red alert instead of HTTP 500; a Turma without a Matriz is a neutral
  note; stored negative ids resolve. Amendment A1 (after the R3 cross-family finding) makes the
  page, its JSON link and its unmodified form read one query. A NUL byte in `turma_codigo` still
  answers 500 on PostgreSQL (backlog).
- DS-CONSISTENCY-01 (`docs/specs/DS-CONSISTENCY-01.md`, CLOSED 2026-11-21), on
  `backlog/ds-consistency-01`, not integrated, not deployed: one section card
  (`components/section-card.css`) and one button contract (`components/actions.css`, DS README §3.1)
  on every screen and modal, chips instead of status pills for labels, the Turma form on a phone;
  guard `tests/test_ds_button_contract.py`. Integration into the development branch waits for the
  owner's acceptance; the qualified GF1 candidate stays `83c378b`.
- TEP v1.2 (2026-11-21, owner workflow correction): a full suite only on a named §5.1 trigger;
  ordinary changes follow §3.8 and are delivered without waiting on unrelated suites.
- Executor observation from UI-B46, not scheduled: 226 raw colours remain in product UI code
  (`MAX_RAW_COLOURS`).

## Environment facts

- Supabase DEV `sgaa-dev` (`pkwtgqsiulzeqkqlsdou`): rehearsals use run-owned
  resources only, and there is no persistent bucket. Its bucket `/empty` is
  asynchronous: delete objects before the bucket.
- Supabase PROD `sgaa-prod` (`uckadhcwfknklmdktuyi`): every action on it is a user gate.
- The DEV rehearsal credential is still active outside the repository; the user
  revokes it when rehearsals end.
- Real-PG lanes need `SGAA_PG_TEST_URL` (local PostgreSQL 15 or 17; the PROD major is 17);
  without it they skip and real-PG evidence is ABSENT. Native client tools: `SGAA_PG_BIN_DIR`.
  The backup/restore lanes (`test_pg_backup_restore_real_pg`, `test_mp3_ops_backup_real_pg`,
  `test_mp3_backup_source`, `test_mp3_opening_real_app`, `test_mp3_restore_profile`) need the PG17
  client tools in `SGAA_PG_BIN_DIR` and a PostgreSQL 17 target (local WSL cluster 127.0.0.1:54317):
  without the tools they fail with `NATIVE_TOOL_MISSING`, and against PostgreSQL 15 the restores fail.
  The live DEV rehearsal is opt-in: `SGAA_MP3_REHEARSAL=1` plus the DEV credential file. Full suite:
  ~6,900 tests, 1 h 18 min with the real-PG lanes on (2026-11-20); run
  detached with ≥5 GB free RAM, from a clean checkout (the project-root
  isolation guard fails the session when another process writes there).

## Known test debt (not blockers)

Baseline full suite is not green (release qualification of 2026-11-20, 6,908 collected):
`tests/test_ut5_backup_package.py::test_cli_backup_sync_runs_isolated_with_app_context_only`
needs the gitignored `database.db`, so it fails in a clean worktree;
`tests/test_phase4_atividades_blueprint.py::test_activity_blueprint_owns_exact_canonical_surface`
pins 20 activity routes, 24 since the template routes of `118796c` (identical in PROD; not fixed).
With `xlwt` in the test environment the former `xlwt` collection errors and
`TestSentinelSurvival` no longer occur; the version-display test no longer reads the CSRF token or
asset URLs.

Eight guards fail on the development branch since before the Acesso
corrections of 2026-11-18 (identical on `a5b912a`, the code in production before GF1-V19; not fixed):

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
Three real-PostgreSQL tests fail too, identically on `a5b912a`:
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
| MP-3 | Production integration / cutover — S8, Phase C, real-data census and convergence, first live mirror run, DR proof, security review | C13 PONR_RECORDED; admission OPEN, A19 deployed, A20 S5 operational with first hosted backup verified; GF1-V19 (`4087eaf`, schema v19) in PROD since 2026-11-19, authenticated manual smoke pending; autonomous due wake and C14 pending |
| MP-4 | Legacy contraction after the rollback window — legacy document paths and bytes, SQLite file backup, Windows scheduler, purge policy (rest of S6) | NOT STARTED |
