# SPEC MP-2 — Hosting readiness

Status: FROZEN 2026-10-09
Charter: "Make SGAA able to run correctly without depending on the Windows workstation
or durable local filesystem, preparing the already-decided Vercel + Supabase architecture
for the later production cutover. MP-1 contracts and invariants are binding and must not
be reopened. Local development/runtime compatibility may remain."
Risk tier: R2 (charter floor R2; schema change, provider integration on DEV, concurrency).

Tier determination. Nothing here changes who may do what in the web application: the
route, RBAC, CSRF and session semantics of the web app are untouched, and its route
inventory does not grow (the scheduler is a separate WSGI front, D6). The two security
additions are fail-closed and strengthen existing controls (a login limiter that survives
multiple instances; a machine credential that can only start one bounded, idempotent MP-1
job). No real data is migrated and no PROD action exists. R3 is therefore not triggered;
if IAsup disagrees, the reclassification point is before MP-3.

## 1. Outcome

- An operator declares a hosted runtime (`SGAA_RUNTIME=hosted`). The application then
  refuses to start without PostgreSQL, a stable secret key and a proxy-trust decision. It
  starts and serves without creating a directory or file, takes every secret from the
  environment, and logs to stderr. `python -m app.hosting check` reports readiness
  without printing a value.
- Login and password-recovery throttling is shared by all instances through the database,
  and the activity-import preview survives across instances. Neither touches the disk.
- A scheduler (Vercel Cron or any HTTP caller) runs one bounded MP-1 mirror pass through
  an authenticated front that is not part of the web application.
- With PostgreSQL configured, the Banco de dados page and its routes offer and perform no
  SQLite-file maintenance and describe the real backup posture.
- An operator backs up the canonical object bytes to a sealed set outside the repository,
  verifies it offline and against the database, and restores it into a bucket with
  read-back verification (rehearsed on DEV).

## 2. Current facts

- `create_app` creates the upload and student-document directories at startup
  (`app/__init__.py:245-246`) and a file log handler (`:444-456`, with a stream fallback).
  `main.py` registers the authorization gate and error handlers after `create_app`
  (`main.py:676-700`) and runs `init_db()` only under `__main__` (`main.py:1028-1037`), so
  `main:app` is the full application and a WSGI host never validates the schema.
- Secrets: `load_machine_secrets` needs `LOCALAPPDATA` and DPAPI (`app/machine_secrets.py:52-128`).
  `cloud_config` reads the store first and lets `MachineSecretsError` propagate, so on a
  non-Windows host Google OAuth configuration fails even when the environment holds the
  values (`app/cloud_config.py:11-50`). `TOKEN_ENCRYPTION_KEY` already wins over the store
  (`app/services/token_encryption.py:79-86`); `APP_SECRET_KEY` is already mandatory in
  production (`app/__init__.py:79-91`).
- Throttling is process-local: `app/auth.py:16-17,588-625` and
  `app/password_recovery_limiter.py:6-7`. Existing tests reach those dictionaries directly
  (46 references in 12 files). `_client_ip` honours `X-Forwarded-For` only with
  `TRUST_PROXY_XFF` (`app/auth.py:568-585`); behind a proxy without it every client shares one address.
- The activity-import preview is JSON written to `UPLOAD_FOLDER` by one request and read by
  the next (`app/views/admin/atividades.py:183-215,937-1026`). Other imports save, parse and
  delete inside one request.
- Backup under PostgreSQL: the capability owner already refuses SQLite-file maintenance
  (`app/backup/capability.py`), and five routes call the refusal. These do not:
  `admin_banco_dados_configuracoes` (creates directories, `banco_dados.py:124-165,1514`),
  `_retencao`, `_download`, `_excluir`. The page still renders local-snapshot, directory,
  restore and Windows-task content (`templates/admin_banco_dados.html:583-1330`).
- `_connect_postgres` sets no connect timeout (`app/db.py:802-813`). `pg_schema_status` is a
  read-only, lightweight schema-version check.
- MP-1 I3 forbids any runtime module from importing the storage background tools
  (`tests/test_storage_mp1_web_isolation.py`: a `BACKGROUND` set; the web scan covers
  `app/`, `services/`, `utils/`, `main.py`).
- Vercel (docs read 2026-10-09): cron requests are `GET` with `Authorization: Bearer
  $CRON_SECRET`; delivery is best effort and may be duplicated or overlap; no retry;
  `x-forwarded-for` carries the public client address and is overwritten, not forwarded.
- Layer-2 backup holds database rows only; "object bytes are not in a Layer-2 archive"
  (`docs/PG_BACKUP_RESTORE_RUNBOOK.md` §D2). The canonical adapter and fake already offer
  `read`, `upload` (no upsert), `stat`, `list_objects`.
- Unknowns resolved by the evidence plan: actual Vercel behaviour (no deployment is
  authorized; MP-3), Supabase PostgreSQL specifics (MP-3), real object volume (MP-3 census).

## 3. Target design

Owners (module → single responsibility; `ENGINEERING_STANDARDS.md` §2 is updated in the
slice that creates each):

| Module | Responsibility |
|---|---|
| `app/hosting` (new) | hosted-mode declaration, scratch root, readiness verdict (value-free), `check` CLI. A leaf module: imports nothing from `app` |
| `app/machine_secrets`, `cloud_config`, `cloud_credentials` (extended) | when hosted the DPAPI store is never read or written; credentials resolve from the environment |
| `app/auth_throttle` (new) | durable throttle on `auth_throttle_events` and the hosted/local selector the login and recovery views call |
| `app/import_previews` (new) | short-lived, user-bound, one-shot server-side preview state on `admin_import_previews` |
| `app/prod1_ephemeral_state_ddl` + `app/prod1_ephemeral_state_v16` (new), `app/pg_schema` | schema v16: the two tables above |
| `app/backup/capability` (extended) | adds `backup_posture()`: what protects the data under the configured backend |
| `app/storage/scheduler` (new) | pure-WSGI front for scheduled storage jobs; BACKGROUND module |
| `app/storage/object_backup` (new) | object-bytes backup / verify / restore; BACKGROUND module; fronted by `cli` subcommands |
| `app/db` (extended) | PostgreSQL connect timeout |

Hosted startup (`create_app`): resolve the mode; when hosted run the readiness blockers
(PostgreSQL configured; `APP_SECRET_KEY` strong; `TRUST_PROXY_XFF` set to 0 or 1; in
production also the existing token-key and public-URL checks and the three canonical
storage variables). Skip directory creation and file logging; `UPLOAD_FOLDER` and
`DOCUMENTOS_ALUNOS_FOLDER` default to lazily created scratch paths. `/health` additionally
runs `pg_schema_status` when hosted. A serverless marker (`VERCEL`, `AWS_LAMBDA_FUNCTION_NAME`)
with the mode undeclared refuses to start; `SGAA_RUNTIME=local` overrides.

Throttle: the keys are `HMAC-SHA256(secret key, scope|value)` digests, with scopes
`login_ip`, `login_account`, `recovery_ip`, `recovery_account`. Thresholds and windows are
the existing `LOGIN_*` / `PASSWORD_RESET_*` configuration. A failed attempt appends an event
and prunes that key's expired events and a bounded batch of globally expired ones inside
`write_transaction`; a blocked attempt writes nothing; success clears the key. When not
hosted the views keep using the in-memory limiters unchanged.

Preview: `store` returns a random token (only its SHA-256 is stored) bound to the session
user, kind and a one-hour expiry; `load` requires the same user and an unexpired row;
`discard` is one-shot. `atividades.py` keeps its `_store_/_load_/_delete_atividades_import_preview`
seams as thin delegates and drops the file path code.

Scheduler front: `application(environ, start_response)`. `GET` or `POST` on
`/internal/scheduler/mirror` only. Authentication is `Authorization: Bearer <CRON_SECRET>`
compared in constant time over SHA-256 digests; a missing or shorter than 32 character
secret disables the front (every request 404). Unauthorized requests are answered before
the application, a connection or any provider is created. An authorized call builds
`create_app()` once per process and runs `drive_mirror.run_mirror_pass` with `limit`
(`SCHEDULER_MIRROR_BATCH`, default 5, maximum 25) and a lease sized to the function
duration. Response: a value-free JSON body, `200` pass OK (including nothing due), `503`
store or Drive not runnable (result code), `500` unexpected, `401` bad credentials, `404`
anything else. Overlapping and duplicate invocations are safe through the MP-1 leases and
fences.

Object backup (`python -m app.storage.cli backup-objects | verify-backup | restore-objects`):
- backup reads every `storage_objects` row (active and retired) of the configured bucket
  through `read_verified` against the recorded size and SHA-256, and writes a staging
  directory of content-addressed files (`objects/<sha[:2]>/<sha256>`) plus a sealed
  manifest (format version, label, counts, per-object id / bucket / key / size / SHA-256 /
  MIME / lifecycle, the `reference_digest`). The set is promoted by rename only when
  complete, never replaces an existing set, and is refused inside the repository;
- verify (offline) checks the seal, every file's size and SHA-256 and the counts;
  `--database` also compares the manifest with the current references (missing,
  extra, changed);
- restore verifies the set, then uploads each object to the target bucket with no upsert,
  adopting an existing object only after a size and SHA-256 match (`TARGET_CONFLICT`
  otherwise), and finally reads every restored object back. It never deletes anything.

PostgreSQL-coherent admin: every SQLite-maintenance route (settings, retention, backup,
download, delete, restore, restore-upload, provider uploads) refuses before any effect
through the one capability owner. The page replaces the local-backup, destination-folder,
operations and retention cards by a posture card from `backup_posture()` (provider
backups and the operator tool for the database; the object backup for documents; the Drive
mirror) and keeps the Google Drive connection card, which the mirror needs. Hosted
credential forms are read-only with an environment-managed notice.

Lock order and transactions: throttle and preview writes are single-statement groups in
`write_transaction` and take no business-row lock. Nothing else changes.

Error model: fixed `[A-Z0-9_]` codes; readiness and CLI output name variables, never values.

## 4. Decisions

- D1 — Hosted mode is explicit (`SGAA_RUNTIME`). Rejected: inferring it from the platform
  (magic that fails silently when a marker changes) and tying it to `APP_ENV=production`
  (a Windows production runtime exists). The undeclared-serverless refusal keeps a
  forgotten flag from running local semantics on an ephemeral disk. `TRUST_PROXY_XFF` must
  be decided because the safe default depends on the platform: trusted on Vercel,
  which overwrites the header; unsafe elsewhere.
- D2 — The filesystem is scratch only. Legacy `local_legacy` documents are unreadable when
  hosted until converged (MP-3); the existing missing-file handling answers. Rejected:
  persistent-volume emulation.
- D3 — Secrets come from the environment when hosted; the machine store is neither read
  nor written. Local mode, `tools/configure_cloud_oauth.py` and the preflight are unchanged.
- D4 — Schema v16 adds two tables, empty and ephemeral on both engines (Path-B
  `OMIT_EPHEMERAL`; Layer-2 schema-only, like `storage_upload_intents`). Local mode keeps its
  in-memory throttle so the 46 test references and the single-process behaviour stand; the
  preview is database-backed in every mode (one code path, no dead file code). Rejected:
  signed stateless previews (replay), the settings key-value tables (misuse), an external
  Redis (new dependency and resource), platform rate limiting alone (a user gate; kept as
  defence in depth).
- D5 — The throttle writes on failed attempts only. This deliberately revises the comment
  "no writes on pre-authentication endpoints": the cost is bounded because a blocked key
  stops writing, but a flood of distinct keys still writes one row per request (residual,
  platform-level mitigation).
- D6 — The scheduler is a separate WSGI front, not a route of the web application. This
  keeps MP-1 I3 literal, adds nothing to the web route/CSRF/RBAC inventories, and lets a
  platform deploy it as its own function. `CRON_SECRET` is the Vercel convention; the
  contract is provider-neutral. Only the mirror pass is scheduled: converge and requeue
  stay operator decisions. The I3 guard's background set gains `scheduler` and
  `object_backup` (a strengthening: no web module may import them).
- D7 — Object backup is operator-run and file-based, outside the repository, on storage the
  operator encrypts (the Layer-2 policy). The bytes are personal data; the manifest and every
  report hold ids, sizes and digests only. Restore targets a bucket the operator created.
  Rejected: a second bucket in the same Supabase account (not independent), automatic
  scheduling (needs an off-platform destination), restore from Drive (no DEV Google; deferred).
- D8 — `backup_posture()` lives in `app/backup/capability` (its question: what maintenance
  and protection the configured backend has), not in the mixed `banco_dados` view.
- D9 — PostgreSQL connections get `connect_timeout` (`SGAA_PG_CONNECT_TIMEOUT`, default 10 s)
  unless the URL sets one, so a paused database cannot hold a function until its limit.
- D10 — Packaging is MP-3. No `vercel.json`, entrypoint file, project, deployment or
  environment variable is created. `docs/HOSTED_RUNTIME.md` records the contract (variables,
  entrypoints `main:app` and `app.storage.scheduler:application`, cron request shape).

Open decisions (product or architecture): none.

## 5. Phase invariants

- H1 A hosted process writes nothing outside the scratch root and never touches the
  machine secret store (tripwire guard with a negative control).
- H2 The web application's route, endpoint, RBAC and CSRF inventories are unchanged.
- H3 The scheduler is fail-closed: no or short `CRON_SECRET` means disabled, a session is
  never accepted, nothing secret appears in a body or log, and no provider is touched
  before authentication.
- H4 Backup and verify only read canonical objects; restore never overwrites or deletes.
- H5 Reports, manifests and logs hold no name, file name, URL or secret.
- H6 MP-1 I1–I5 hold; I3 is strengthened, not weakened.

## 6. Scope

- Allowed: the owners in §3; `app/__init__.py`, `app/db.py`, `app/auth.py` call-site wiring
  in `app/views/core.py` and `app/views/passwords.py`; `app/views/admin/atividades.py`
  (preview delegates), `app/views/admin/banco_dados.py` and `templates/admin_banco_dados.html`
  (refusals, posture); `app/prod1_schema.py`, `app/pg_schema.py`,
  `app/pg_migrate_from_sqlite.py`, `app/db_maintenance.py`, `app/services/backup_service.py`
  and `tools/pg_backup.py` for v16; `docs/` governance and runbooks; `tests/`.
- Protected: web routes and endpoints, RBAC and CSRF inventories, session semantics, the
  signed-TUS contract, MP-1 outbox / mirror / convergence semantics, `main.py`,
  `tools/bootstrap_sgaa_runtime.ps1` and the launch scripts, the Windows backup scheduler.
- Planned local refactors (`ENGINEERING_STANDARDS.md` §8): the limiter call sites move to
  `auth_throttle`; the preview file helpers leave `atividades.py`; the refusal helper in
  `banco_dados.py` is applied uniformly.
- Out of scope: MP-3 (PROD, Vercel project and descriptor files, real census, cutover,
  `SUPABASE_DATA_API_DISABLED`, Supabase PostgreSQL qualification, Layer-1 PITR); MP-4
  (legacy retirement, SQLite file backup removal, Windows scheduler removal).

## 7. Data & schema

- prod-1 v15 → v16 on SQLite and PostgreSQL, same slice, parity tests, migration registry
  updated. Two new empty tables, no backfill, no existing column touched:
  `auth_throttle_events(id, scope, key_digest, occurred_at)` and
  `admin_import_previews(token_digest, kind, usuario_id → usuarios, payload, created_at,
  expires_at)` with the indexes the queries need.
- Path-B: both tables `OMIT_EPHEMERAL`. Layer-2: both schema-only (`EPHEMERAL_OMITTED`); the
  manifest contract and TOC census follow. Real-PG nodes prove both.
- Rollout note: the first launch of v16 code on the workstation applies the additive
  migration to `database.db`; the operator takes the usual file backup first.
- Real data: none touched. The canonical `database.db` is not opened by any test or tool.

## 8. Security & RBAC

- No new or changed web route. The scheduler front is outside the Flask application.
- Secrets: `APP_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `DATABASE_URL`, `SUPABASE_SECRET_KEY`,
  `CRON_SECRET`, Google client values come from the environment and are never printed.
  Throttle keys are keyed digests, previews store token digests.
- Fail-closed: every readiness blocker raises at startup; an unreadable throttle store
  does not silently allow logins (the view returns the existing generic error path).
- Personal data: object bytes are personal data and live only in the operator's backup set;
  nothing else carries it.

## 9. Compatibility / rollout

- Local Windows behaviour is unchanged: the mode defaults to local, the in-memory limiters,
  DPAPI store, directory creation and file logging stay.
- Hosted behaviour is new and inert until `SGAA_RUNTIME=hosted` is set.
- Rollback: v16 tables are inert in local mode; the code can be reverted by a new commit.

## 10. External boundaries / environment permissions

- Supabase DEV `sgaa-dev` (`pkwtgqsiulzeqkqlsdou`) only: create one private bucket per run
  (`sgaa-mp2-<run hex>`), upload, list, read, delete objects in it, delete the bucket, leak
  audit. Credential: the existing DEV rehearsal secret kept outside the repository.
- Local: disposable PostgreSQL databases (`sgaa_mp2_test_<run>_*`) on the persistent PG15
  cluster; pytest temporary directories.
- PROD, Vercel, Google live, any deployment: none.

## 11. Evidence plan

- Every slice: T0; T1/T2 on the new owners; T3 = `grep` importers and tests of every changed
  module; T4 = route inventory, CSRF inventory, RBAC coverage, C4 hook isolation, connection
  ownership, `test_pg_readiness_unit4_transactions.py`, residual-main guards, catalogue
  ledger, `test_storage_mp1_web_isolation.py`.
- E-PG1 for every new SQL path; E-PG2 for throttle (concurrent failures counted exactly,
  cross-connection visibility), preview one-shot under contention, scheduler overlap.
- Hosted proof: `create_app` and representative requests under a write tripwire (patched
  `open`, `os.makedirs`, `os.mkdir`, `tempfile`, `shutil`, `sqlite3.connect`) allowing only
  the scratch root; a negative control proves it detects a known write; two independent app
  instances over one real-PG database prove shared throttle and preview state; a memory
  limiter run fails the same test (discriminating control).
- E-LIVE (DEV): backup → verify → restore into a second run-owned bucket with read-back;
  corrupted byte, deleted object, truncated and tampered manifest, bucket conflict as
  negative controls; leak audit and cleanup.
- Mutation probes before each review: seal check removed; read-back removed; adoption check
  removed; bearer comparison weakened; hosted tripwire disabled; throttle clear removed.
- Full suite: expected T5 at close (TEP §5.1 A and B: bootstrap and schema), run detached
  once on the candidate tree; per-slice runs stay targeted.
- Review: S1, S3, S4, S5 get an R2 independent fresh-context review before landing; S2 is
  R1 (no new route, no provider).

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | Hosted runtime: mode, readiness, scratch, env-only secrets, connect timeout, health, `check` CLI | `hosting`, `__init__`, `machine_secrets`, `cloud_*`, `db`, tests | T1–T4; E-PG1 hosted smoke; tripwire; R2 | pending |
| 2 | PostgreSQL-coherent backup/admin | `capability`, `banco_dados`, template, tests | T1–T4; route tests on both engines; E-PG1 page; R1 | pending |
| 3 | Schema v16, durable throttle, DB-backed preview | ddl/migration modules, `pg_schema`, Path-B, `pg_backup`, `auth_throttle`, `import_previews`, views, tests | T1–T4; parity; E-PG1/E-PG2; Path-B and Layer-2 real PG; R2 | pending |
| 4 | Scheduler front, I3 guard extension | `scheduler`, guard test, tests | T1–T4; E-PG2 overlap; DEV canonical reads with a fake Drive; R2 | pending |
| 5 | Object backup/verify/restore, CLI, runbooks, closure | `object_backup`, `cli`, `docs/HOSTED_RUNTIME.md`, runbook, ES §2, PROJECT_STATE, this SPEC | T1–T4; E-LIVE DEV; T5; R2; closure | pending |

## 13. Acceptance criteria

- AC1 — A hosted process refuses each readiness blocker with a fixed code, starts without
  creating a file, and serves login, the admin dashboard and the Banco de dados page on real
  PostgreSQL with zero writes outside scratch. Evidence: slice 1 tests, tripwire and its
  negative control.
- AC2 — Hosted secrets resolve from the environment (Google OAuth, token key, public URL)
  with the store untouched; credential forms are read-only; local behaviour is unchanged.
- AC3 — Under PostgreSQL no route or page element performs or offers SQLite-file maintenance,
  creates a directory, lists a local snapshot or queries the Windows task. Evidence: slice 2.
- AC4 — Login and recovery limits hold across independent instances with unchanged
  thresholds; blocked attempts write nothing; success clears; growth is bounded.
- AC5 — The activity-import preview works across instances with no file, is one-shot,
  user-bound and expiring.
- AC6 — Schema v16 passes SQLite/PostgreSQL parity, v15 → v16 migration, Path-B and Layer-2
  real-PG nodes.
- AC7 — The scheduler runs a mirror pass only for a valid bearer, is disabled without one,
  and overlapping calls never double-sync. Evidence: slice 4 tests and E-PG2.
- AC8 — Object backup, offline and database verification, and restore pass on DEV with every
  negative control detected, canonical objects untouched, and the leak audit clean.
- AC9 — MP-1 I1–I5 and `ENGINEERING_STANDARDS.md` §13 self-audit pass.

## 14. Phase-specific hard stops

- Evidence that a hosted code path wrote durable state to local disk and relied on it (H4).
- Any DEV action on a bucket or object the run did not create (H3).
- A web route, endpoint or CSRF/RBAC inventory change becoming necessary (H7/H9).

## 15. Deferred / known non-blockers

- Vercel project, descriptor files, environment wiring, region and `maxDuration`, WAF /
  platform rate limiting (MP-3).
- `SUPABASE_DATA_API_DISABLED`, Supabase PostgreSQL version qualification, Layer-1 PITR,
  cross-environment backup proof (MP-3).
- Scheduled object backup; object restore from the Drive mirror; independent off-platform
  object copy beyond the operator set.
- A flood of distinct login keys writes one throttle row per request.
- `main.py` still attaches a file handler when its directory is writable; harmless when
  hosted and frozen by the facade rule.
- Legacy local documents are unavailable when hosted until MP-3 converges them.

## 16. Amendments

None yet.

## 17. Closure

Filled in the last slice.
