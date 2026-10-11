# SGAA — Production cutover runbook (MP-3)

Owner: the operator. Authority of record: `docs/specs/MP-3-production-integration.md`
(states §3.3, rollback and point of no return §3.4, gates §10, amendments A15–A17). This
document is the procedure; it holds no project state, no value and no student data.
Commands are templates: `<…>` is supplied at run time and is never written into this file,
the ledger or any report.

Zero recurring cost is a requirement of the phase (Vercel Hobby, Supabase Free). A step
that would cost money is not performed; stop and say so.

## 0. Ground rules

- **Gates.** A gate is one explicit user message naming its id. Record it with
  `cutover_ledger grant` only after that message exists. A gate covers its state and its
  resumptions, nothing else.
- **Ledger.** Every transition goes through `python tools/cutover_ledger.py` in a directory
  outside the repository. It validates order, gates, value-free evidence and carried
  identities. A refusal is information, not an obstacle to route around. Typed evidence goes
  in as `advance --state <Cn> --evidence <json file>` (the file stays in the ledger directory,
  never in the repository). Every command prints the chain head; pass it to the next ledger
  command as `--expect-head <head>`: the command line refuses without it (`HEAD_REQUIRED`) and a
  truncated or replaced ledger is refused (`HEAD_MISMATCH`). One command runs at a time
  (`LEDGER_BUSY`). After a refused command, `status` prints the head.
- **Nothing the ledger relies on is typed (SPEC A17).** The ledger observes for itself or takes
  the receipt of the governed tool that performed the step, while it performed it:
  the PROD database is qualified by `cutover_ledger qualify`; backups are recorded only by
  `ops_backup --ledger-dir` as it takes them; restore drills only by `ops_backup drill` as it
  runs them; deployments only by `deploy_audit deploy` and `promote`. There is no command that
  records a backup, a drill or a deployment found on disk or typed by the operator.
- **Value-free evidence.** Counts, classes, digests, opaque identifiers and fixed codes. A
  path, a name, an address, a row or a log line never goes into evidence, a report or a chat.
- **Custody directory.** One encrypted directory outside the repository holds the frozen
  copy, the converged copy, backup sets and reports. It is personal data; treat it so.
- **Secrets (SPEC P6, A15).** The user enters every production value; the executor never
  receives, reads back or prints one, and none ever lands in a file:
  - platform values (GP2, GD2): the Vercel dashboard (Settings, Environment Variables,
    Sensitive, Production), or the CLI's own interactive prompt
    `vercel env add <NAME> production --sensitive` with nothing piped or redirected into it.
    There is no `< file` or `type <file> |` path;
  - a value one command on the operator machine needs (`PGPASSWORD` for the PROD database,
    `SUPABASE_SECRET_KEY` for an object set, the qualification or a convergence,
    `SGAA_OPERATOR_TOKEN` for the smoke): typed by the user at a hidden prompt into one
    terminal's environment and removed after the command. Such a command is marked
    **(user terminal)**: the user runs it and the executor receives only its value-free output.
    In PowerShell:

    ```powershell
    $s = Read-Host -AsSecureString 'PGPASSWORD'
    $env:PGPASSWORD = [System.Net.NetworkCredential]::new('', $s).Password
    # ... the command ...
    Remove-Item Env:PGPASSWORD
    ```

  - the bearer of the external trigger: Supabase Vault (C11).

  The libpq password file serves DEV only. A value never goes into a file, a pipe, an
  argument, a history line, the ledger, a report or a chat. Every command that reads PROD
  (database or bucket) or carries the operator token is a user-terminal command.
- **The PROD database only through the verified source (SPEC A17).** Every command whose answer
  the ledger relies on (`qualify`, the governed backups, `reference`, `open`, `close`, `resume`,
  `rollback`) opens `DATABASE_URL` through `tools/prod_source`:
  - `DATABASE_URL` is the PROD project's session-pooler address,
    `postgresql://postgres.<ref>@<region>.pooler.supabase.com:5432/postgres`, with no password
    and no parameter but `sslmode` (refused otherwise: `SOURCE_URL_PARAMETER_REFUSED`,
    `SOURCE_NOT_THE_SESSION_POOLER`, `SOURCE_NO_TENANT`);
  - the connection is `sslmode=verify-full` against the Supabase root CA committed in
    `tools/certs/` (pinned by the SHA-256 of its DER bytes, `807025ad…e6cafa`; a replaced file
    is refused, `SOURCE_CA_PIN_MISMATCH`), whatever the URL said: a hosts entry or any
    redirection to another server fails before a query (`SOURCE_TLS_NOT_VERIFIED`);
  - no libpq routing or TLS variable may be set in the terminal: `PGHOST`, `PGHOSTADDR`, `PGPORT`,
    `PGDATABASE`, `PGUSER`, `PGSERVICE`, `PGSERVICEFILE`, `PGSYSCONFDIR`, `PGOPTIONS`,
    `PGTARGETSESSIONATTRS`, `PGLOADBALANCEHOSTS`, `PGSSLMODE`, `PGREQUIRESSL`, `PGSSLNEGOTIATION`,
    `PGSSLROOTCERT`, `PGSSLCRL`, `PGSSLCRLDIR`, `PGSSLSNI`, `PGSSLCERT`, `PGSSLKEY`,
    `PGSSLMIN/MAXPROTOCOLVERSION`, `PGGSSENCMODE`, `PGREQUIREAUTH`, `PGCHANNELBINDING`,
    `PGREQUIREPEER` (`SOURCE_ENV_ROUTING` names it). `PGPASSWORD` is allowed;
  - the identity the ledger reads (database, role, cluster `system_identifier`, and the project of
    the tenant the pooler authenticated) is recorded once at GP1 by `qualify`, cross-checked
    against the project's own storage API, and every later observation must be that database
    (`DATABASE_NOT_THE_QUALIFIED_ONE`; another project `DATABASE_NOT_THE_PROD_PROJECT`).
- **The store's address is the project's.** `SUPABASE_URL` is `https://<ref>.supabase.co` (the
  address the object set records and the qualification compares; a custom domain or another form
  names no project and is refused, `STORE_NOT_A_PROJECT`, `OBJECT_SET_NOT_FROM_THE_PROD_PROJECT`).
- **No provider-side change to the PROD database from C1 to C14.** An upgrade, a pause and
  restore or a migration of the project changes its cluster identifier; every later observation
  is then refused (`DATABASE_NOT_THE_QUALIFIED_ONE`) and the cutover cannot continue in this
  ledger (fail closed, no data lost). If the provider forces one, stop and escalate.
- **Deployments only through the governed tool (SPEC A17).** Every production deployment is
  `python tools/deploy_audit.py deploy` and every promotion `deploy_audit promote`, with
  `--vercel-team <team id> --vercel-project <project id>` (identifiers, not names; the CLI is the
  user's, authenticated). `deploy` exports the commit into a directory it creates, audits and
  verifies it, uploads it with `--prod --skip-domain` (it takes no alias) and the admission set on
  the deployment itself, then asks the platform for the files it received -- they must equal the
  verified export byte for byte (`DEPLOYED_FILES_DIFFER` otherwise: whatever changed after the
  verification is never served) -- and observes at the deployment's own address that it runs the
  export's code (`X-SGAA-Code`) and, for an operator deployment, refuses users. Only then is it
  recorded; a deployment failing any check is removed. Never deploy or redeploy by hand (CLI,
  dashboard, Git integration): an unrecorded deployment blocks the reference
  (`UNRECORDED_DEPLOYMENT`). `SGAA_ADMISSION` and `SGAA_OPENING_REFERENCE` are never project
  variables; the tool sets them on each deployment.
- **Vercel Authentication is off for the production project** (Settings, Deployment Protection),
  as rehearsed: the tool and the ledger must reach every deployment address without a credential;
  the application's own gate is the control.
- **The ledger's two PROD writes (SPEC A17).** The opening authorization (`sgaa_cutover.opening`,
  a schema outside `public`) is written by `reference` together with the reference entry, revoked
  by `close`, restored by `resume`, and authorized for a forward fix by `authorize-code`. The write
  barrier (the writers' role defaults to read-only in the PROD database and every older session of
  it is ended) is applied by `close` and lifted by `resume`. Nothing else in PROD is written by the
  ledger.
- **Two terminals: production commands and restore drills never share one.** The PROD terminal
  has `DATABASE_URL` = the PROD session address; a restore drill runs in a separate terminal where
  `DATABASE_URL` is unset (`DRILL_SOURCE_URL_SET` otherwise) and the scratch database is named
  only as `SGAA_RESTORE_TARGET_URL`, closed when the drill ends.
- **https only.** The ledger observes the public address over https; `--allow-insecure` is for
  the tests' loopback servers and is refused for any other host (`INSECURE_ONLY_ON_LOOPBACK`).
- **Never** run a tool against the live workstation database. The only touch of the live
  file is the read-only snapshot of GR0 and the byte copy of the stopped runtime of GR1.

## 1. Before C0 (rehearsal and review)

1. The dress rehearsal (SPEC slice 6) ran C1–C13 on DEV (C14 refused before its window) with fault
   injection and a rollback from every state before C13. Its index and the measured end-to-end time exist.
2. This runbook is amended with the measured numbers and its SHA-256 is frozen.
3. The final-candidate R3 review passed; the commit to deploy is the reviewed one.
4. `python tools/cutover_ledger.py init --ledger-dir <ledger>`; then `advance --state C0
   --evidence <json>` with `commit`, `runbook_sha256`, `rehearsal_index_sha256`,
   `review_verdict` (`PASS`) and `prod_project_sha256`: the SHA-256 of the PROD project
   reference GP0 names (`python -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" <ref>`).
   Every data-API proof and the qualification are bound to it.

## 1b. Measured numbers (DEV dress rehearsal, synthetic production-shaped data)

- Convergence into Supabase Storage from the workstation: 1.5 s per object (11 documents in
  16.6 s: read, upload, byte verification, link). The window of C2 is twice
  `objects x 1.5 s` plus the fixed steps; the census at C2 gives `objects`.
- The whole C0..C14 rehearsal, including a real restore drill into scratch PostgreSQL, runs in
  a few minutes at this size; the data-dependent steps are convergence, Path-B, the backups and
  the restore drill, which scale with rows and bytes.
- Supabase DEV, synthetic one-administrator database, from the operator workstation (MP-3 SPEC
  A14, A17): v16 provisioning 26–28 s; session-mode snapshot backup 57–59 s; a governed generation
  (Layer-2, object set, off-platform copy, ledger record) 72 s; a restore drill of it into local
  PostgreSQL 17 under 2 s; DR1 6 s; DR3 140 s, of which the restore is 88 s; the write barrier
  applied in 2 s and lifted in 3 s. Real data adds dump and restore time in proportion to rows
  and bytes.
- These are lower bounds from a small synthetic set: record the real figures from C5 and C8.

## 2. States

### C1 PROD_QUALIFIED — gates GP0, GP1, GP2

1. GP0: read the PROD project's metadata (major, region, usage against the Free limits,
   Data API and Storage settings, and the PostgREST version in Settings, Infrastructure).
   Record the major; qualify it if it is not 17. The data-API answer accepted below was
   proven on DEV (SPEC A15) with the override in place while DEV's toggle was still on.
   Before GP1 relies on it, DEV is put in PROD's target configuration -- the user turns DEV's
   toggle off (GA4), the override stays -- and `hosted_smoke --data-api-only` against DEV must
   PASS again; if PROD's PostgREST version differs from DEV's, the proof is repeated on DEV at
   PROD's version. Until both hold, C1 waits.
2. GP1, as the schema-owning role, in this order: the revocation statements of
   `docs/HOSTED_RUNTIME.md` §11; `python -m app.pg_schema provision`; `… validate`; the
   revocation again; create the private bucket; one synthetic canary object written, read
   back and removed; `python -m app.hosting_cli check --database` (**user terminal**, the session
   address) must report `api_exposure.clean: true`.
3. GP1, the qualification of the database itself, **(user terminal**: `DATABASE_URL` the session
   address, `PGPASSWORD`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SGAA_STORAGE_BUCKET`**)**:
   `python tools/cutover_ledger.py qualify --ledger-dir <ledger> --expect-head <head>`. Through the
   verified source (ground rules) the ledger reads the database's identity; the tenant the pooler
   authenticated must be the PROD project of C0 (`DATABASE_NOT_THE_PROD_PROJECT`), the cluster must
   prove itself (`DATABASE_IDENTITY_UNPROVEN`), `SUPABASE_URL` must name the same project
   (`STORE_NOT_THE_PROD_PROJECT`), and the project's own storage API (public TLS, the secret key)
   must list exactly the buckets this database holds (`STORE_NOT_THE_DATABASES_PROJECT`; at least
   the private bucket of step 2, `NO_BUCKET_TO_COMPARE`). It records the identity; every later
   command compares with it.
4. GP1, the Data API, in this order. These are the only other PROD writes of this step and they
   are named here so that none is improvised:
   1. the user turns **Enable Data API** off (Dashboard, Integrations, Data API);
   2. the provider's documented override (Supabase troubleshooting, "schema
      pg_pgrst_no_exposed_schemas does not exist"), run exactly as written in the PROD SQL
      editor, by the user or by the executor under GP1:

      ```sql
      create schema if not exists pgrst_no_exposed_schemas;
      alter role authenticator set pgrst.db_schemas = 'pgrst_no_exposed_schemas';
      notify pgrst;
      ```

      It is reversed with `alter role authenticator reset pgrst.db_schemas; notify pgrst;`
      before the toggle is ever turned on again. Nothing else on `authenticator` changes;
   3. `python tools/hosted_smoke.py --data-api-only --data-api-url https://<ref>.supabase.co
      --data-api-project-ref <ref>` with `SUPABASE_PUBLISHABLE_KEY` in the process
      environment: PASS. It passes only on 406 with exactly the body proven on DEV,
      compared as JSON: `{"code":"PGRST106","details":null,"hint":"Only the following
      schemas are exposed: pgrst_no_exposed_schemas","message":"Invalid schema: public"}`,
      with a bogus-key control refused 401, the project's own address and a key the
      gateway accepts. Everything else fails: rows, 404 `PGRST205`, 401 `42501`, a valid
      key refused (`DATA_API_KEY_REFUSED`: a wrong, rotated or foreign key), another schema
      list or wording, the toggle's own placeholder without the override, a schema-cache
      error and a protection page (`DATA_API_SERVES`, "not proven off"); another address
      (`DATA_API_WRONG_PROJECT`). A secret or service key (`sb_secret_…`, a legacy JWT whose role
      is not `anon`) or any other shape is refused before anything is sent
      (`DATA_API_KEY_NOT_PUBLISHABLE`): the check uses only what a browser may hold. A failure
      blocks C1; the check is never weakened.
5. Capacity: the projected database size, storage bytes and monthly egress are below the
   Free limits with headroom; project pause is avoided by the daily scheduler pass and use.
6. GP2: the user places `APP_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `DATABASE_URL`
   (transaction pooler), `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SGAA_STORAGE_BUCKET`,
   `SUPABASE_PUBLISHABLE_KEY`, `APP_PUBLIC_BASE_URL`, `APP_ENV=production`,
   `SGAA_RUNTIME=hosted`, `TRUST_PROXY_XFF=1`, `SGAA_OPERATOR_TOKEN` (at least 32 random
   characters, generated by the user) and the Google client values in the platform, by the
   dashboard or the interactive prompt (ground rules). `CRON_SECRET` is NOT set yet (the scheduler
   front stays disabled). `SGAA_ADMISSION` and `SGAA_OPENING_REFERENCE` are never project variables
   (the governed deploy sets them per deployment). A deployment without `SGAA_ADMISSION` does not
   start (`HOSTED_ADMISSION_UNDECIDED`).
7. Ledger C1 evidence: `pg_major`, `schema_current`, `rows` 0, `objects` 0,
   `data_api_toggle_off` (the user's statement: no probe can tell the toggle's state while the
   override stands), `data_api_override` APPLIED, `data_api_probe` NOT_SERVED (the
   smoke's PASS), `data_api_project_sha256` (printed by the smoke; it must equal C0's
   `prod_project_sha256`), `api_exposure_clean`, `capacity_ok`. `advance --state C1` is refused
   until `qualify` recorded the database (`QUALIFICATION_REQUIRED`).

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
   `<TABLE>_<PROVIDER>_ELIGIBLE_UNCONVERGED`), at most 64 characters; the counts come with them.
   Ledger C6: `prepared_sha256`, `reference_digest`, `verdict`.

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
3. **Cutover baseline (governed)**, **(user terminal**: `DATABASE_URL` the session address,
   `PGPASSWORD`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SGAA_STORAGE_BUCKET`**)**:
   `python tools/ops_backup.py --baseline --root <baseline dir> --off-platform <baseline second dir>
   --ledger-dir <ledger>`. Before any step the run refuses a routing variable and observes, through
   the verified source, that `DATABASE_URL` is the qualified database
   (`SOURCE_NOT_THE_QUALIFIED_DATABASE`) and `SUPABASE_URL` the PROD store; the children connect
   through the same verified address; after the last step it observes the database again; the
   ledger records the baseline only from that run's receipt (its Layer-2 manifest and dump, its
   object set, the identity observed, the run's own time), re-verified from disk. It prints the
   baseline's `manifest_sha256` and `object_set_digest`. The baseline directories hold nothing else
   and are never rotated.
4. **Restore drill**, in the drill terminal (`DATABASE_URL` unset; `SGAA_RESTORE_TARGET_URL` = a new,
   empty scratch PostgreSQL of the PROD major): `python tools/ops_backup.py drill --ledger-dir
   <ledger> --root <baseline dir> --off-platform <baseline second dir> --generation <baseline
   manifest_sha256>`. It restores the recorded generation, verifies the restored database against
   the manifest, verifies the object set (seal, every file, its recorded digest) and that it holds
   the bytes of every restored `storage_objects` row, and records the receipt (the generation, its
   source, the scratch target's identity). The clone probe of `PG_BACKUP_RESTORE_RUNBOOK.md` §H in
   the same terminal; drop the scratch database; keep the two encrypted copies.
5. Ledger C8: `reference_digest`, `census_equal`, `baseline_manifest_sha256` and `object_set_digest`
   (as `ops_backup` printed them), `admin_bootstrap`. The ledger refuses without the recorded
   baseline (`BASELINE_REQUIRED`), with other digests (`BASELINE_NOT_THE_RECORDED_ONE`) or without its
   drill receipt (`BASELINE_RESTORE_REQUIRED`).

### C9 DEPLOYED_DARK — gate GD1

From here until the opening the deployment admits only the operator
(`SGAA_ADMISSION=operator`, `docs/HOSTED_RUNTIME.md` §2a): every request without the operator
credential is refused with 503 before any session, view or database access. "Not announced" is
not the control; this is.

1. `python tools/deploy_audit.py deploy --commit <reviewed commit> --ledger-dir <ledger>
   --vercel-team <team id> --vercel-project <project id> --admission operator [--sentinels <file>]`
   (ground rules: one operation from the export to the record). It prints the `deployment_id`, the
   code identity and the admission it observed. `LEDGER_COMMIT_NOT_THE_REHEARSED_ONE` means the
   commit is not C0's; `DEPLOYED_FILES_DIFFER`, `DEPLOYMENT_CODE_NOT_OBSERVED` or
   `LEDGER_DEPLOYMENT_NOT_CLOSED` mean the deployment was removed and nothing is recorded.
2. Publish the one Hobby rate-limit rule: method `POST`, path matching
   `^/(login|esqueci-minha-senha|primeiro-acesso|redefinir-senha)$`, fixed window 600 s, limit 100,
   key `ip`, mitigation `rate_limit` with `rateLimit.action` `rate_limit` (the response is 429; `deny`
   answers 403). Rehearsed: the 101st request in a window is refused, a GET of the login page is not
   counted, and a window that keeps receiving requests stays refused.
3. **(user terminal)** `python -m app.hosting_cli check --database` with the production
   environment: ready, and the report names `admission` `operator`.
4. **(user terminal**, `SGAA_OPERATOR_TOKEN` at the hidden prompt**)**
   `python tools/hosted_smoke.py --base-url <deployment address> --admission closed`: its
   ADMISSION check (a client WITHOUT the credential: two pages and a credential POST each
   503 `X-SGAA-Admission: closed`, no cookie) is the C9 observation.
5. Ledger C9: `commit`, `deployment_id` (the recorded one; `DEPLOYMENT_NOT_RECORDED` otherwise),
   `readiness` READY, `scheduler_front` DISABLED, `admission` CLOSED.

### C10 SMOKED

**(user terminal**, `SGAA_OPERATOR_TOKEN` and, for the sign-in, the operator password at
hidden prompts**)** `python tools/hosted_smoke.py --base-url <deployment address> --admission
closed --data-api-url https://<ref>.supabase.co --data-api-project-ref <ref> [--email
<operator>]` with `SUPABASE_PUBLISHABLE_KEY` in the environment. The smoke sends the operator
credential on every application request and proves, with a separate anonymous client, that
everyone else is still refused (ADMISSION). The DATA_API check is C1's. PASS required.

The public alias is then taken only after the dark deployment's own address passes the smoke:
`python tools/deploy_audit.py promote --ledger-dir <ledger> --vercel-team <team id>
--vercel-project <project id> --deployment <deployment id> --public-url https://<public host>`.
It promotes only a recorded deployment the platform still holds unchanged, and records the
promotion once the platform resolves the public address to it and the address serves its code.
Before C11 the same command with an earlier recorded deployment is the rollback of a promotion.
The smoke is then run again on the public address (`--base-url <public address> --admission
closed`, same flags): PASS, and its `public_host_sha256` is the address every later ledger
observation must probe (`ADDRESS_NOT_THE_DEPLOYMENT` otherwise).

The smoke reads `/csrf-token`, never the dashboard (its view writes alert receipts and may
derive a rejection). Its only application write is the sign-in. Prove that, do not assume it:
**(user terminal)** `python tools/pg_fingerprint.py snapshot --out <before>` and `--out
<after>` around the smoke (`DATABASE_URL` = the session address; a snapshot needs a
read-only snapshot transaction, which the transaction pooler does not give), then `compare`.
Identical is `write_set_ok` true. The first sign-in may rewrite student rows that kept the
legacy access level `administrativo` (the application normalizes them): `changed_tables`
USUARIOS with `changed_columns` nivel_acesso only is that known, once-only derived write;
adjudicate it before C10 (the reference of the opening is taken later and includes it).
Anything else is investigated before C10.
Ledger C10: `smoke` PASS, `write_set_ok`, `admission` CLOSED, `data_api_project_sha256`
(must equal C1's), `public_host_sha256` (from the run on the public address; it must be the
promoted one, `PUBLIC_ADDRESS_NOT_PROMOTED`).

### C11 MIRROR_PROVEN — gates GG1, GG2, GD2

1. GG1: the callback is registered on the legacy OAuth client (user, in the Google console).
   The administrator opens `<public address>/operator-admission`, presents the operator
   credential once (an HttpOnly cookie admits that browser for eight hours), signs in and
   connects Google through the hosted page. The consent screen is in production status.
   Compare the logical account key with the source's (census).
2. GG2: **(user terminal)** `python -m app.storage.cli mirror-run --limit 1 --passes 1`, then
   raise the batch; `verify --drive`. Anything `reconciliation_required` is understood before
   going on (`mirror-requeue` only after the cause is fixed).
3. GD2: the user sets `CRON_SECRET` (at least 32 characters; dashboard or interactive prompt)
   and the same commit is deployed and promoted again (`deploy_audit deploy … --admission
   operator`, then `promote`); the daily pass is observed. If the backlog needs a higher cadence,
   the external trigger is created under the same gate, with no secret in it:
   1. the user stores the same bearer value in Supabase Vault through the dashboard's Vault
      page, named `sgaa_scheduler_bearer` (not in the SQL editor, which keeps query history);
   2. the job, created as `postgres` in the SQL editor (it holds no value):

      ```sql
      select cron.schedule('sgaa-mirror', '*/30 * * * *', $job$
        select net.http_get(
          url := 'https://<public host>/internal/scheduler/mirror',
          headers := jsonb_build_object('Authorization', 'Bearer ' ||
            (select decrypted_secret from vault.decrypted_secrets where name = 'sgaa_scheduler_bearer')));
      $job$);
      ```

      Rotation updates the platform value and the Vault entry together.
4. The ADMISSION check again (C9 step 4, public address): still closed.
5. Ledger C11: `account_key_match`, `mirror_passes`, `reconciliation_required` 0,
   `scheduler_front` ENABLED, `admission` CLOSED.

### C11 → C12 THE OPENING — gate GO

The order is binding and the ledger enforces it: no ordinary user can write before the
reference exists, because every deployment refuses them until it is lifted under an
authorization that only the reference writes.

1. Pre-opening generation (governed), **(user terminal**, `PGPASSWORD` and `SUPABASE_SECRET_KEY`
   at hidden prompts; `DATABASE_URL` the session address**)**:
   `python tools/ops_backup.py --root <primary dir> --off-platform <second dir> --objects
   --label pre-open --ledger-dir <ledger>`. The run is the evidence (C8 step 3): only the
   generation it took, from the verified qualified database and the PROD store, is recorded.
2. The reference, **(user terminal**, `PGPASSWORD`, `DATABASE_URL` the session address**)**:
   `python tools/cutover_ledger.py reference --ledger-dir <ledger> --expect-head <head> --base-url
   <public address> --vercel-team <team id> --vercel-project <project id> --backup-root <primary dir>
   --off-platform <second dir> --out <custody>/reference.json --backup-cadence-hours <h>` (UD10:
   `24`, at most 24). The ledger refuses unless the state is C11 with GO granted, no reference was
   taken before (`REFERENCE_ALREADY_TAKEN`), the address is C10's and is the production deployment
   (its scheduler front answers as enabled, `SCHEDULER_FRONT_NOT_ENABLED`), it is observed CLOSED
   without any credential, and there is no observable sign that production could ever have opened:
   every deployment the platform holds for the project (failed and cancelled ones aside) is one the
   governed deploy recorded (`UNRECORDED_DEPLOYMENT`), recorded as operator-only
   (`DEPLOYMENT_OPENED_BEFORE_THE_REFERENCE`), observed CLOSED at its own address
   (`DEPLOYMENT_NOT_CLOSED`) and running its recorded code (`DEPLOYMENT_CODE_CHANGED`); the public
   address serves the candidate (`ALIAS_NOT_THE_CANDIDATE`); and the PROD database holds no opening
   authorization at all (`OPENING_AUTHORIZATION_EXISTS`). The last recorded generation must have
   been made after C11 with an object set, re-verify from both directories with the digests the
   ledger recorded, and be current (its Layer-2 table digests equal the live fingerprint and its
   object set the live references). The ledger then takes the fingerprint itself, writes the
   reference file (digests and counts only) and, in one database transaction with the ledger entry,
   the opening authorization: a row in `sgaa_cutover.opening` holding the reference entry itself
   (its hash, the database identity, the candidate's code, the platform project). It prints the
   entry's `hash` (also as `head`).
3. The lift (GO). First, if the newest generation is older than the cadence allows (1.5 × `h`,
   or 1.5 weeks for the object set), take a new one (step 1 again): `open` would refuse it
   (`BACKUP_TOO_OLD_TO_OPEN`) only after users are admitted. Then
   `python tools/deploy_audit.py deploy --commit <reviewed commit> --ledger-dir <ledger>
   --vercel-team <team id> --vercel-project <project id> --admission open --opening-reference <that
   hash>` and `promote` it (C10). The tool refuses any other value (`LEDGER_OPEN_WITHOUT_THE_REFERENCE`).
   An open production deployment admits users only while the PROD database holds the authorization
   for that reference and its own code: a deployment lifted with any other value, before the
   reference, with other code or after a revocation answers like a closed one (503), and it re-reads
   the authorization at most every 15 s. Every response announces `X-SGAA-Opening` (a tag of the
   reference) and `X-SGAA-Code`. `status` prints the reference as `opening_reference`. Keep
   `SGAA_OPERATOR_TOKEN` in the platform until C14: a rollback deployment closes admission with it.
4. `python tools/cutover_ledger.py open --ledger-dir <ledger> --expect-head <head> --base-url
   <public address> --vercel-team <team id> --vercel-project <project id>` (**user terminal**,
   `PGPASSWORD`): the ledger observes that the platform resolves the public address to the recorded
   open deployment of the candidate carrying ITS reference (`ALIAS_NOT_THE_AUTHORIZED_DEPLOYMENT`)
   and still holding the recorded files (`DEPLOYMENT_NOT_THE_RECORDED_ONE`), that no barrier is in
   force (`BARRIER_IN_FORCE`), that the database's authorization is valid for it
   (`OPENING_NOT_AUTHORIZED`), that the address admits users (`ADMISSION_NOT_OPEN`), announces the
   tag of THAT reference (`OPENING_NOT_BOUND_TO_THE_REFERENCE`) and runs the candidate's code
   (`DEPLOYMENT_CODE_CHANGED`), and that the newest generation is within the cadence. It writes C12
   from the reference; `advance --state C12` is refused (`OPENING_NEEDS_THE_OPEN_COMMAND`).
5. Announce. The local runtime stays stopped and protected.

### C12 OPEN_PONR_PENDING

- The cadence recorded at the opening is in force until C14: **(user terminal)**
  `python tools/ops_backup.py --root <primary dir> --off-platform <second dir> [--objects]
  --ledger-dir <ledger>` every `h` hours, with `--objects` at least weekly. A Layer-2 gap longer
  than 1.5 × `h`, or an object-set gap longer than 1.5 weeks, anywhere from the opening to C14
  refuses C14 (`BACKUP_CADENCE_BROKEN`, `OBJECT_CADENCE_BROKEN`). Only governed runs count: each
  generation is recorded once, dated inside its own run, never older than one already recorded,
  and only when the run read the qualified database throughout and its sets name that database and
  the PROD store; a generation of DEV, of scratch, of another project, a mixed one or a set found on
  disk is never recorded. A scheduled task is not used for PROD: it would need a stored PROD secret
  (P6).
- While pending, rollback is available (section 3).

### C13 PONR_RECORDED

Periodically, and after any report of a user action: **(user terminal)** `python
tools/pg_fingerprint.py snapshot --out <now>` then `compare --reference <ref> --current <now>`.
The report names the changed tables and columns and counts rows added, removed and changed; it
never prints a value. A difference is a CANDIDATE. Only two derived classes can ever be excused,
and only by the ledger's rollback proof (section 3), never by an operator's reading: the
automatic rejection of an overdue returned request that a dashboard view triggers
(`REQUISICOES_AUTO_REJECTION`) and the student "seen" mark (`REQUISICOES_STUDENT_SEEN`). Every
other change -- including the credential-version bump of a legacy-hash re-hash, which looks
exactly like a password change -- is a business write. Record it: `advance --state C13` with
`write_class` (the changed table name as printed), `detected_at`, `current_fingerprint_sha256`
(the snapshot that showed it; it must differ from the reference) and `adjudicated_by_operator`
true. From here the cutover is forward-fix only (SPEC §3.4), gates that only serve rollback are
refused, and the window starts.

### C14 WINDOW_CLOSED

After UD4's 30 days from C13, with the cadence held: a generation made after C13 with an object
set is restore-drilled in the drill terminal (`python tools/ops_backup.py drill --ledger-dir <ledger>
--root <primary dir> --off-platform <second dir> --generation <its manifest_sha256>`, as at C8), no
unresolved reconciliation. Ledger C14: `restore_validated_manifest_sha256` (that generation's
manifest digest), `unresolved_reconciliation` 0. The ledger refuses before 30 days from C13
(`WINDOW_NOT_ELAPSED`), on a cadence gap since the opening, on a generation not made after C13
(`RESTORE_VALIDATION_NOT_A_WINDOW_GENERATION`) and without the drill's receipt for it
(`RESTORE_RECEIPT_REQUIRED`); a receipt is only ever the drill's own, bound to a recorded
generation, its source and a scratch target of the PROD major. The window report lists them;
MP-4 may then be chartered.

## 3. Rollback (before C13)

| At | Do | Then |
|---|---|---|
| C1–C4 | stop; restart the workstation runtime if frozen | `cutover_ledger rollback --reason <CODE>` |
| C5–C6 | as above | bucket objects stay as additive orphans; removal only under GX1 |
| C7–C11 (no reference taken) | as above; admission is still closed; take the deployment down or pause it; remove `CRON_SECRET`; `select cron.unschedule('sgaa-mirror')` and delete the Vault entry if they exist | the PROD database is a copy; emptying it needs GX1 |
| C12, or C11 once a reference exists | in this order: (1) stop system writes at their source: `select cron.unschedule('sgaa-mirror')` (before the barrier; it is a write), remove `CRON_SECRET`, `deploy_audit deploy … --admission operator` and `promote` it (the public address answers closed and the scheduler front 404); (2) **(user terminal**, `PGPASSWORD`**)** `python tools/cutover_ledger.py close --ledger-dir <ledger> --expect-head <head>`; (3) **(user terminal**, `PGPASSWORD`**)** `python tools/cutover_ledger.py rollback --ledger-dir <ledger> --expect-head <head> --reason <CODE> --base-url <public address> --reference <custody>/reference.json [--derived-class <CLASS> ...]`; (4) remove every open deployment (`vercel remove <deployment id> --yes`; they admit no one already) and pause the project; restart the workstation runtime | see below |

`close` is the write control (SPEC A17). In one database transaction it revokes the opening
authorization (every open deployment, at whatever address -- the alias or an immutable deployment
URL -- answers closed within 15 s) and sets the role every writer uses (the application, the
scheduler, the external trigger) to read-only by default in the PROD database; it then ends every
session of that role older than the barrier, its own included (the provider's pooler reuses server
sessions; a pre-barrier session would otherwise be handed out again). It records the barrier only
after a fresh session proves it: the role default is set, the fresh session is read-only and a write
in it is refused, no older session remains, no authorization is in force (`BARRIER_NOT_IN_FORCE`
otherwise; `close` can be rerun). From then on no write can land in PROD, whichever deployment or
trigger reaches it.

The C12 rollback is then decided by the ledger, not by the operator. It requires the barrier
(`BARRIER_REQUIRED`) and verifies it again in a fresh session before each fingerprint and once more
immediately before the rollback is recorded (`BARRIER_NOT_IN_FORCE`), so no write can land between
the proof and the record. It also observes, without any credential, that admission is closed, that
the scheduler front is disabled and that no `pg_cron` job is active, and that the database is the
qualified one and the reference's; it then takes the fingerprint live in one read-only snapshot,
waits 330 s, observes again and takes it again: the two must agree (`QUIESCENCE_NOT_PROVEN`). Equal
to the reference: recorded. Unequal: refused `FINGERPRINT_CHANGED` -- go to C13 -- unless every
changed table and column belongs to the fixed derived classes, no row was added or removed, each
changed row reproduces the derived value from the reference row (`REQUISICOES_AUTO_REJECTION`: a
returned request now rejected with its note extended by the fixed automatic-rejection marker;
`REQUISICOES_STUDENT_SEEN`: an empty "seen" mark now set), and the operator's `--derived-class` list
equals the observed classes exactly (`DERIVED_CLASSES_NOT_ACKNOWLEDGED`). A file, a timestamp or a
fingerprint typed by the operator is never the evidence. Mirror files already in the Drive stay
(additive). The barrier stays after a recorded rollback: nothing lifts it, and production is not
written again (`resume` refuses, `ROLLED_BACK`).

When a rollback is refused (`FINGERPRINT_CHANGED`), production goes forward:
**(user terminal**, `PGPASSWORD`**)** `python tools/cutover_ledger.py resume --ledger-dir <ledger>
--expect-head <head>` lifts the barrier (resets the role default, ends every session that started
read-only, restores the authorization; `BARRIER_STILL_IN_FORCE` if a fresh session still cannot
write); restore `CRON_SECRET`, `deploy_audit deploy … --admission open --opening-reference <status
opening_reference>` and `promote`; re-enable the external trigger if it was used; record C13 with the
changed fingerprint. `resume` also lifts a barrier `close` applied but could not record.

From C11 with a reference, a `FINGERPRINT_CHANGED` (an operator write after the reference, or a
legacy-hash sign-in) cannot be followed by C13 at once, and no second reference is taken: the
cutover either goes forward -- `resume`, the lift, `open`, then C13 recorded immediately with the
changed fingerprint -- or, only if no lift has happened (no user can have written), is abandoned
with a new ledger (PROD is a copy; emptying it, the control schema included, needs GX1).

After C13 there is no rollback: use the latest Layer-2 generation and the frozen source for
manual reconciliation. Never improvise a reverse migration. A forward-fix deployment is the
one deployment action that remains: each one needs its own user message, recorded with
`grant --gate GF1 --ref <code>` (valid only after C13; the gates that act on the source or on
the first deployment are refused), then `deploy_audit deploy --commit <fix commit> … --admission open
--opening-reference <status opening_reference> --forward-fix-ref <code>` (it admits no one yet: its
code is not authorized), `cutover_ledger authorize-code --deployment <id>` (**user terminal**, adds
the authorization for that code under the same reference) and `promote`.

## 4. Routine after cutover

- Backups: until C14 as in C12 (with `--ledger-dir`); afterwards **(user terminal)** `python
  tools/ops_backup.py --root <primary dir> --off-platform <second dir> [--objects]` on the
  cadence of UD10 (database from `DATABASE_URL`, the session address, `PGPASSWORD` at the
  hidden prompt): two generations kept, the copy to the off-platform directory verified,
  restore verification; a periodic restore drill into scratch PostgreSQL in the drill terminal
  (ground rules), never with `DATABASE_URL` pointing at scratch. Rotation deletes only
  generations the tool itself registered; the cutover baseline is never rotated.
- Watch the Free limits (database 500 MB, storage 1 GB, egress 5 GB a month, Hobby
  invocations and active CPU, seven days of inactivity) before they bind.
- Secret rotation: `CRON_SECRET` by redeploy and the Vault entry; `APP_SECRET_KEY` ends
  sessions and clears throttle windows; `TOKEN_ENCRYPTION_KEY` needs a Google reconnect;
  `SGAA_OPERATOR_TOKEN` is removed after C14 (an open deployment does not read it).
- Production stays open only through the governed open deployment and the authorization in
  `sgaa_cutover.opening`; the control schema is kept for the life of production.
