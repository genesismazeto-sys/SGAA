# PRE-GO-LIVE PROD-1 Reset and Cutover Record

## Scope and authorization

The human owner authorized a pre-go-live data reset because meaningful academic
production had not started and historical academic preservation was not
required. The accepted PROD-1 code baseline had final independent technical
acceptance before execution. This record covers only Phase A technical landing
and Phase B database reset. It does not claim application production activation
or go-live.

## Phase A — technical landing

- Previous/rollback code SHA: `779dbb24b185025b7a72b358c61a71d04304d60d`.
- Technical commit: `c9452b5bffa2c2620305ee1b296ff81deb22b65f`.
- Commit subject: `Establish PROD-1 canonical baseline`.
- Exact accepted candidate: 145 paths — 127 modified, 11 deleted, 7 added.
- Landing completion timestamp: `2026-08-21T11:13:22Z`.
- Remote `refactor/design-system-foundation` was verified at the technical SHA.
- Protected `main` remained
  `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`; no main action occurred.
- `database.db`, `.claude/settings.local.json`, secrets, custody, and staging
  artifacts were not committed.

## Old-state custody and rollback pair

- Old active database: 544768 bytes; SHA-256
  `338c833bc565c97cb55d5e08a3df9dbbe307a99820bb5a56f0cbed62d699633d`.
- Old database archive:
  `D:\SGAA_CUSTODY\pre-go-live-prod1\20260821T111131Z\database.db` with the
  same byte-for-byte SHA-256.
- Old code archive:
  `D:\SGAA_CUSTODY\pre-go-live-prod1\20260821T111131Z\old-code-779dbb24.zip`;
  SHA-256
  `ee1e0542923964fa3584bcfffd52e9cd2d2cc617a1b30cc80ab67a8b9d81f169`.
- Custody metadata:
  `D:\SGAA_CUSTODY\pre-go-live-prod1\20260821T111131Z\custody.json`.

The rollback unit is the compatible pair: old code SHA `779dbb24...` plus the
archived old database SHA `338c833b...`. If rollback is required, keep SGAA
stopped, preserve the current PROD-1 database externally, restore both members
of this pair, and do not mix schema epochs.

## Direct PROD-1 bootstrap

A missing-path database was created at
`D:\SGAA_CUTOVER_STAGING\20260821T111131Z\database.db`. Before importing
`app.db`, the isolated process set `APP_ENV=production` and `APP_DATABASE` to
that absolute staging path. It created only a minimal Flask application context
and called `app.db.init_db()` directly. Production `create_app()` was not
called, no server was started, and no public URL or runtime secret was used.

The bootstrap configuration was:

- local backup directory: `D:\SGAA_BACKUPS`;
- cloud backup directory: empty;
- cloud sync interval: 600 seconds;
- external backup URL and token: empty;
- external backup enabled: false;
- automatic default-admin bootstrap: false; admin email/password: empty.

The second `init_db()` call was idempotent. The staged database was closed and
checkpointed with no `-wal`, `-shm`, or `-journal`. It was 409600 bytes with
SHA-256
`cbd4197615d8929b7a19b5e52f016e06ecbc7fd1ad9297521b8a4fee25b37244`.

## Atomic reset and validation

The SGAA runtime freeze found zero confirmed SGAA processes, services, or
scheduled restart tasks. The old database hash and zero-sidecar state were
rechecked immediately before replacement. A verified same-volume copy of the
closed staging database was passed to `.NET File.Replace`; the old destination
was also retained as `database.atomic-pre-replace.db` in custody. The original
validated staging database remained available for independent hash comparison.

The active database then matched the staged SHA-256 exactly. A fresh process,
again using an absolute `APP_DATABASE` and minimal Flask context without
production `create_app()`, validated and idempotently initialized the active
database:

- epoch `prod-1`, version `1`, marker `first_production_baseline`;
- exact migration row `(1, first_production_baseline, prod-1)`;
- 28 tables, 40 explicit indexes, and 7 triggers;
- accepted physical constraints, request-status contract, Matrix composites,
  uniqueness, and snapshot immutability trigger;
- zero foreign-key violations and `integrity_check = ok`;
- legacy tables, columns, and indexes absent;
- no residual SQLite sidecars.

Initial contents are one `Geral` course, five access defaults, six application
settings, and six backup settings. Users/admins, requests/history, Normas,
activity catalogue, Matrices, Turmas, and students are empty. No admin was
created.

Focused disposable regression ran only the accepted baseline, final-init,
canonical request-flow, and bounded manual-backup contracts. Result: `18 passed
in 10.84s`, with 0 failed and 0 errors. Temporary databases, cache, and runtime
paths were external to the repository.

Phase B active validation completed at `2026-08-21T11:17:57Z`. Evidence files
are `prod1-build-evidence.json` in staging and
`active-validation-evidence.json` in the external custody directory.

## Deferred Phase C

`PRODUCTION_WEB_RUNTIME_ACTIVATION = DEFERRED` and
`SGAA_WEB_RUNTIME_STARTED = NO`.

A separately authorized Phase C must provide the final HTTPS
`APP_PUBLIC_BASE_URL`, externally provisioned `APP_SECRET_KEY` and valid
`TOKEN_ENCRYPTION_KEY`, final host/port and proxy decisions, production
`create_app()` validation, web startup and smoke checks, and manual admin
creation. No secrets are recorded here.
