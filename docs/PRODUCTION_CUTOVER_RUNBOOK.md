# SGAA — Production cutover runbook (MP-3)

Owner: the operator. Authority of record: `docs/specs/MP-3-production-integration.md`
(states §3.3, rollback and point of no return §3.4, gates §10). This document is the
procedure; it holds no project state, no value and no student data. Commands are
templates: `<…>` is supplied at run time and is never written into this file, the
ledger or any report.

Zero recurring cost is a requirement of the phase (Vercel Hobby, Supabase Free). A step
that would cost money is not performed; stop and say so.

## 0. Ground rules

- **Gates.** A gate is one explicit user message naming its id. Record it with
  `cutover_ledger grant` only after that message exists. A gate covers its state and its
  resumptions, nothing else.
- **Ledger.** Every transition goes through `python tools/cutover_ledger.py` in a directory
  outside the repository. It validates order, gates, value-free evidence and carried
  identities, and executes nothing. A refusal is information, not an obstacle to route around.
  Evidence goes in as `advance --state <Cn> --evidence <json file>` (the file stays in the
  ledger directory, never in the repository). Every command prints the chain head; pass it
  to the next `grant`, `advance` or `rollback` as `--expect-head <head>`: the command line
  refuses without it (`HEAD_REQUIRED`) and a truncated or replaced ledger is refused
  (`HEAD_MISMATCH`). One command runs at a time (`LEDGER_BUSY`).
- **Value-free evidence.** Counts, classes, digests and fixed codes. A path, a name, an
  address, a row or a log line never goes into evidence, a report or a chat.
- **Custody directory.** One encrypted directory outside the repository holds the frozen
  copy, the converged copy, backup sets and reports. It is personal data; treat it so.
- **Secrets.** A production secret is placed in the platform by the user (GP2) or typed into
  one process environment for one gated command; never in a file, a history line or an
  argument. Database passwords come from the libpq password file.
- **Never** run a tool against the live workstation database. The only touch of the live
  file is the read-only snapshot of GR0 and the byte copy of the stopped runtime of GR1.

## 1. Before C0 (rehearsal and review)

1. The dress rehearsal (SPEC slice 6) ran C1–C14 on DEV with fault injection and a rollback
   from every state before C13. Its index and the measured end-to-end time exist.
2. This runbook is amended with the measured numbers and its SHA-256 is frozen.
3. The final-candidate R3 review passed; the commit to deploy is the reviewed one.
4. `python tools/cutover_ledger.py init --ledger-dir <ledger>`; then `advance --state C0
   --evidence <json>` with `commit`, `runbook_sha256`, `rehearsal_index_sha256`,
   `review_verdict` (`PASS`).

## 1b. Measured numbers (DEV dress rehearsal, synthetic production-shaped data)

- Convergence into Supabase Storage from the workstation: 1.5 s per object (11 documents in
  16.6 s: read, upload, byte verification, link). The window of C2 is twice
  `objects x 1.5 s` plus the fixed steps; the census at C2 gives `objects`.
- The whole C0..C14 rehearsal, including a real restore drill into scratch PostgreSQL, runs in
  under one minute at this size; the data-dependent steps are convergence, Path-B and the
  restore drill, which scale with rows and bytes.
- Supabase DEV, synthetic one-administrator database, from the operator workstation (MP-3 SPEC A14):
  v16 provisioning 26 s; session-mode snapshot backup of the managed project 57 s; DR1 (that set into
  local PostgreSQL 17, verified, application booted and smoked) 5 s; DR3 (a foreign set into the managed
  target, verified, recipe applied, probe clean, application served through the transaction pooler and
  smoked) 140 s, of which the restore is 88 s. Real data adds dump and restore time in proportion to
  rows and bytes; the 140 s is dominated by the pooler round trips of the restore.
- These are lower bounds from a small synthetic set: record the real figures from C5 and C8.

## 2. States

### C1 PROD_QUALIFIED — gates GP0, GP1, GP2

1. GP0: read the PROD project's metadata (major, region, usage against the Free limits,
   Data API and Storage settings). Record the major; qualify it if it is not 17.
2. GP1, as the schema-owning role, in this order: the revocation statements of
   `docs/HOSTED_RUNTIME.md` §11; `python -m app.pg_schema provision`; `… validate`; the
   revocation again; create the private bucket; one synthetic canary object written, read
   back and removed; `python -m app.hosting_cli check --database` (direct or session
   address) must report `api_exposure.clean: true`. The Data API toggle is off (user).
3. Capacity: the projected database size, storage bytes and monthly egress are below the
   Free limits with headroom; project pause is avoided by the daily scheduler pass and use.
4. GP2: the user places `APP_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `DATABASE_URL`
   (transaction pooler), `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SGAA_STORAGE_BUCKET`,
   `SUPABASE_PUBLISHABLE_KEY`, `APP_PUBLIC_BASE_URL`, `APP_ENV=production`,
   `SGAA_RUNTIME=hosted`, `TRUST_PROXY_XFF=1` and the Google client values in the platform.
   `CRON_SECRET` is NOT set yet (the scheduler front stays disabled).
5. Ledger C1 evidence: `pg_major`, `schema_current`, `rows` 0, `objects` 0,
   `data_api_toggle_off`, `data_api_probe` NOT_SERVED, `api_exposure_clean`, `capacity_ok`.

### C2 SNAPSHOT_CENSUSED — gate GR0

1. Take a read-only online snapshot of the workstation database into the custody directory.
2. On the snapshot only: upgrade the copy to schema v16 if its `PRAGMA user_version` is
   older, with the migration entry point the application runs at start, in an isolated
   process and never on the live file:
   `python -c "import sqlite3,sys; from app.db_maintenance import apply_schema_migrations as m;
   c=sqlite3.connect(sys.argv[1]); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON');
   print(m(c)['schema_version']); c.commit()" <copy>` (prints 16; the rehearsal proves it on a
   v15 copy and that the frozen source's bytes never change). Then, with `APP_DATABASE` set to
   the copy and no `DATABASE_URL`: `python -m app.storage.cli census`. The census command alone
   does NOT upgrade a copy.
3. From the counts: the maintenance window (twice the rehearsal throughput estimate) and the
   proposed disposition of terminal and unsupported legacy rows (SPEC D15, UD6). The user
   decides the accepted classes; the executor never improvises one.
4. Ledger C2: `database_bytes`, `document_bytes`, `census` (class and count pairs, non-empty).

### C3 SOURCE_FROZEN — gate GR1

1. Announce; stop the workstation runtime and its scheduled tasks; confirm no `-wal`.
2. Byte-copy the database, the document roots and the file backup into the custody directory.
   Record size and SHA-256 (use `git hash-object` for repository files; plain SHA-256 for these).
3. Ledger C3 evidence: `source_size`, `source_sha256`, `wal_bytes` 0.

### C4 SOURCE_PREPARED — gate GR1 (same gate)

1. On the copy: upgrade to v16 if needed (the procedure of C2), `PRAGMA integrity_check`, foreign-key check.
2. Authoritative census on the copy; the classes and counts the user accepted become
   `accepted_exceptions`; `accepted_by_user` is true only after the user's message.
3. Ledger C4 evidence: `source_sha256` (unchanged), `prepared_sha256`, `integrity_ok`,
   `fk_violations` 0, `schema_version` 16, `accepted_exceptions`, `accepted_by_user`.

### C5 CONVERGED and C6 SOURCE_CROSS_CHECKED — gate GR2

1. Process environment of one shell: the PROD canonical-store variables and the runtime's
   database path set to the PREPARED COPY; the document roots set to the copied roots.
2. `python -m app.storage.cli converge` (dry run), review, then `converge --apply`; it is
   resumable: rerun after any interruption. Exit 0 or the accepted exceptions only.
3. `python -m app.storage.cli verify --deep`: converged and clean. Record `reference_digest`.
4. Ledger C5: `prepared_sha256`, `converged_rows`, `unconverged`, `legacy_bytes_touched` 0.
   `unconverged` is derived from the post-apply census, per table: every `blocked` class,
   plus any `eligible` count still above zero (an eligible row that did not converge -- a
   target conflict, a failed upload -- is a failure to fix, never an accepted class). The
   ledger refuses the state unless the list equals exactly what the user accepted at C4.
   Class names are `<TABLE>_<PROVIDER>_<STATUS>` in capitals, every `:` or `-` an underscore
   (for example `REQUISICAO_ARQUIVOS_GOOGLE_TRASHED`; an eligible leftover is
   `<TABLE>_<PROVIDER>_ELIGIBLE_UNCONVERGED`), at most 64 characters; the counts come with them. Ledger C6: `prepared_sha256`, `reference_digest`, `verdict`.

### C7 TARGET_LOADED — gate GR3

1. `python -m app.pg_migrate_from_sqlite --source <prepared copy> --expected-source-sha256 <h>`
   (dry run, `DATABASE_URL` = the direct or session address), then the same with `--apply`.
2. Exit 3 (commit uncertain): inspect the target; application rows present means it
   committed (do not rerun); empty means rerun. Exit 4: investigate before anything else.
3. Ledger C7: `prepared_sha256`, `pathb_exit` (0, or 3 with `commit_resolved_by_inspection`
   true after the inspection above), `commit_outcome` COMMITTED.

### C8 TARGET_VERIFIED — gates GB1 (and GP3 only if a bootstrap is needed)

1. `python -m app.storage.cli verify --deep` on PROD: `reference_digest` equals C6.
2. If no login-capable full administrator exists: GP3, `python -m app.admin_bootstrap
   --email <administrator>`; the output stays on the terminal.
3. **Cutover baseline**: `python tools/pg_backup.py backup --output-dir <set dir> --label
   cutover-baseline` (direct or session address, password file); `verify --manifest`; the
   object set `python -m app.storage.cli backup-objects --destination <new dir>`, then
   `verify-backup --set <dir> --database`; restore drill into scratch PostgreSQL of the PROD
   major (`restore`, `verify --restored`, the clone probe of `PG_BACKUP_RESTORE_RUNBOOK.md`
   §H); drop the scratch database; keep two encrypted copies, one off-platform.
4. Ledger C8: `reference_digest`, `census_equal`, `baseline_manifest_sha256`,
   `object_set_digest`, `restore_drill`, `verify_backup`, `admin_bootstrap`.

### C9 DEPLOYED_DARK — gate GD1

1. `python tools/deploy_audit.py export --commit <reviewed commit> --out <new empty dir>`
   (committed content only, runtime allowlist) and `audit --dir <that dir>`: CLEAN.
2. Deploy that directory to the production project with the user-authenticated CLI, DARK:
   `npx vercel@<pinned> deploy --prod --skip-domain --yes` from the exported directory (linked
   with `vercel link`; delete the `.env.local` and `.gitignore` the link writes before the
   upload and re-run the audit). The platform does not validate a descriptor: a rewrite to a
   service that does not exist deploys READY and, without `--skip-domain`, takes the public
   alias (rehearsed: every page answered 404). The daily cron entry is in `vercel.json` but
   the scheduler front is disabled while `CRON_SECRET` is unset. Publish the one Hobby
   rate-limit rule (below). Environment values are written without a trailing line ending
   (`type <file> | vercel env add NAME production --sensitive`; a value from a PowerShell pipe
   carries CRLF and a `CRON_SECRET` with whitespace fails the build).
   The one rate-limit rule, per address, counted over 600 s across the four credential POSTs:
   method `POST`, path matching `^/(login|esqueci-minha-senha|primeiro-acesso|redefinir-senha)$`,
   fixed window 600 s, limit 100, key `ip`, mitigation `rate_limit` with `rateLimit.action`
   `rate_limit` (the response is 429; `deny` answers 403). Rehearsed: the 101st request in a
   window is refused, a GET of the login page is not counted, and a window that keeps
   receiving requests stays refused.
   The public alias is then taken only after the dark deployment's own address passes the
   smoke (section C10) and the operator promotes it (`vercel promote <deployment id> --yes`,
   about 4 s; the same command with the previous deployment id is the rollback).
3. `python -m app.hosting_cli check --database` with the production environment: ready.
   The export verifies every file against the commit's blob id and normalizes line endings
   itself (`core.autocrlf` of the workstation does not matter); `EXPORT_NOT_THE_COMMIT` means
   the bytes do not match the reviewed commit and nothing is deployed. Plant the sentinel
   file of the rehearsal in the audit (`audit --dir <dir> --sentinels <file>`) when you have one.
4. Ledger C9: `commit`, `readiness` READY, `bundle_audit` CLEAN, `scheduler_front` DISABLED.

### C10 SMOKED

`python tools/hosted_smoke.py --base-url <public address> --data-api-url <project address>`
with `SUPABASE_PUBLISHABLE_KEY` in the process environment (the data-API check needs the key:
without it the check refuses rather than passing on a 401) and, for the sign-in check,
`--email <operator>` (password at the hidden prompt; refused over plain http). PASS required.
The data-API check asks one application table in the `public` schema (`Accept-Profile: public`)
with the valid key, and with a bogus key as the control (the gateway must answer 401, else
`DATA_API_CONTROL`). It passes only on 406 `PGRST106` whose hint lists no schema but the empty
placeholder (`pgrst_no_exposed_schemas` / `pg_pgrst_no_exposed_schemas`). Rows, 404 `PGRST205`,
401 `42501`, a PGRST106 that lists another schema, a valid key refused like the bogus one and a
protection page all fail (`DATA_API_SERVES`): none of them proves the API off. The data-API
address must be the provider's (`*.supabase.co`, `DATA_API_URL_NOT_PROVIDER`). The schema root
is not asked: it answers 401 to every publishable key whatever the state. Its positive control is run once
before C10 against a project whose API is on and must FAIL; a check that cannot fail proves
nothing.

The smoke reads `/csrf-token`, never the dashboard (its view writes alert receipts and may
derive a rejection). Its only application write is the sign-in. Prove that, do not assume it:
`python tools/pg_fingerprint.py snapshot --out <before>` and `--out <after>` around the smoke
(`DATABASE_URL` = the direct or session address; a snapshot needs a read-only snapshot
transaction, which the transaction pooler does not give), then `compare`. Identical is
`write_set_ok` true. The first sign-in may rewrite student rows that kept the legacy access
level `administrativo` (the application normalizes them): `changed_tables` USUARIOS with
`changed_columns` nivel_acesso only is that known, once-only derived write; adjudicate it and
take the reference after it (section C12). Anything else is investigated before C10.
Ledger C10: `smoke` PASS, `write_set_ok`.

### C11 MIRROR_PROVEN — gates GG1, GG2, GD2

1. GG1: the callback is registered on the legacy OAuth client (user, in the Google console);
   the administrator connects Google through the hosted page. The consent screen is in
   production status. Compare the logical account key with the source's (census).
2. GG2: from the operator machine, `python -m app.storage.cli mirror-run --limit 1 --passes
   1`, then raise the batch; `verify --drive`. Anything `reconciliation_required` is
   understood before going on (`mirror-requeue` only after the cause is fixed).
3. GD2: the user sets `CRON_SECRET` (at least 32 characters) and the deployment is redone;
   the daily pass is observed. If the backlog needs a higher cadence, the external trigger
   (a Supabase `pg_cron` job with `pg_net`, bearer only) is created under the same gate.
4. Ledger C11: `account_key_match`, `mirror_passes`, `reconciliation_required` 0,
   `scheduler_front` ENABLED.

### C12 OPEN_PONR_PENDING — gate GO

1. Take the reference fingerprint AFTER the smoke (C10) and the mirror proof (C11), with the
   direct or session address: `python tools/pg_fingerprint.py snapshot --out <ref>`. Keep the
   file in the custody directory; it holds digests and counts only.
2. Admit users (announcement). The local runtime stays stopped and protected.
3. Ledger C12: `reference_fingerprint_sha256` (the value the snapshot printed), `opened_at`.
4. While pending, rollback is available (section 3).

### C13 PONR_RECORDED

Periodically, and after any report of a user action: `python tools/pg_fingerprint.py
snapshot --out <now>` then `compare --reference <ref> --current <now>`. The report names the
changed tables and columns and counts rows added, removed and changed; it never prints a
value. A difference is a CANDIDATE: the operator adjudicates it (the detector over-reports on
purpose). Known derived writes that remain included are the automatic rejection of an overdue
returned request that an administrator's dashboard view triggers and the student "seen" mark;
the credential-version bump of a legacy-hash re-hash (USUARIO_CREDENCIAIS, columns
`auth_version` and `atualizado_em` only; a real password change has the same signature);
a changed table or column that is not one of them, or one the operator cannot explain, is a
business write. Record it: `advance --state C13` with `write_class` (the changed table name as
printed), `detected_at`, `current_fingerprint_sha256` (the snapshot that showed it; it must
differ from the reference) and `adjudicated_by_operator` true. From here the cutover is
forward-fix only (SPEC §3.4), gates that only serve rollback are refused, and window W starts.

### C14 WINDOW_CLOSED

After W days: no unresolved reconciliation, a later Layer-2 generation restore-validated,
the object set verified. Ledger C14: `window_days`, `second_generation_restore` OK,
`unresolved_reconciliation` 0, `object_set_verified`. The window report lists them; MP-4
may then be chartered.

## 3. Rollback (before C13)

| At | Do | Then |
|---|---|---|
| C1–C4 | stop; restart the workstation runtime if frozen | `cutover_ledger rollback --reason <CODE>` |
| C5–C6 | as above | bucket objects stay as additive orphans; removal only under GX1 |
| C7–C11 | as above; take the deployment down or pause it; remove the scheduler secret | the PROD database is a copy; emptying it needs GX1 |
| C12 | stop admitting users; take a fresh snapshot AFTER the last ledger entry (the file records its own time; a copy of an older one is refused) and pass it as `rollback --current-snapshot <file>` (its digest must equal the opening's; a changed one is a business write, go to C13 -- unless the only differences are the known derived writes of C13, which the operator may adjudicate with `--derived-class <TABLE>` per changed table, recorded in the ledger); pause the deployment; restart the workstation runtime | mirror files already in the Drive stay (additive) |

After C13 there is no rollback: use the latest Layer-2 generation and the frozen source for
manual reconciliation. Never improvise a reverse migration. A forward-fix deployment is the
one deployment action that remains: each one needs its own user message, recorded with
`grant --gate GF1 --ref <code>` (valid only after C13; the gates that act on the source or on
the first deployment are refused).

## 4. Routine after cutover

- Backups: `python tools/ops_backup.py --root <primary dir> --off-platform <second dir>
  [--objects]` on the cadence of UD10 (database from `DATABASE_URL`, direct or session
  address): two generations kept, the copy to the off-platform directory verified, restore
  verification; a periodic restore drill into scratch PostgreSQL. Rotation deletes only
  generations the tool itself registered; the cutover baseline is never rotated.
- Watch the Free limits (database 500 MB, storage 1 GB, egress 5 GB a month, Hobby
  invocations and active CPU, seven days of inactivity) before they bind.
- Secret rotation: `CRON_SECRET` by redeploy; `APP_SECRET_KEY` ends sessions and clears
  throttle windows; `TOKEN_ENCRYPTION_KEY` needs a Google reconnect.
