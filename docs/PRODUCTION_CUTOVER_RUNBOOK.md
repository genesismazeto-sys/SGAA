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
- **Secrets (SPEC P6, A15).** The user enters every production value; the executor never
  receives, reads back or prints one, and none ever lands in a file:
  - platform values (GP2, GD2, GO): the Vercel dashboard (Settings, Environment Variables,
    Sensitive, Production), or the CLI's own interactive prompt
    `vercel env add <NAME> production --sensitive` with nothing piped or redirected into it.
    There is no `< file` or `type <file> |` path;
  - a value one command on the operator machine needs (`PGPASSWORD` for the PROD database,
    `SUPABASE_SECRET_KEY` for an object set or a convergence, `SGAA_OPERATOR_TOKEN` for the
    smoke): typed by the user at a hidden prompt into one terminal's environment and removed
    after the command. Such a command is marked **(user terminal)**: the user runs it and the
    executor receives only its value-free output. In PowerShell:

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
- **One database address, the PROD project's.** Every operator command whose output the ledger
  compares (backups, fingerprints, the ledger's `record-backup`, `reference` and `rollback`, in
  `DATABASE_URL`) uses the same session-pooler address of the PROD project. The ledger reads the
  database's identity from the connection itself -- database, role, cluster (`system_identifier`)
  and the Supabase project the pooler authenticated (the login `postgres.<ref>`) -- and refuses a
  database of any other project, a scratch or local server (`DATABASE_NOT_THE_PROD_PROJECT`), one
  that does not prove its cluster (`DATABASE_IDENTITY_UNPROVEN`) and, once the reference exists,
  any other database (`DATABASE_NOT_THE_REFERENCE`). An address of another kind may identify
  itself differently and is refused the same way.
- **The store's address is the project's.** `SUPABASE_URL` is `https://<ref>.supabase.co` (the address
  the object set records; a custom domain or another form names no project and its object sets are
  refused, `OBJECT_SET_NOT_FROM_THE_PROD_PROJECT`).
- **No provider-side change to the PROD database from C11 to C14.** An upgrade, a pause and restore or
  a migration of the project changes its cluster identifier; every later generation is then refused
  (`DATABASE_NOT_THE_REFERENCE`) and C14 cannot be reached in this ledger (fail closed, no data lost).
  If the provider forces one, stop and escalate before recording anything else.
- **Two terminals: production backups and restore drills never share one.** The PROD backup
  terminal has `DATABASE_URL` = the PROD session address and nothing else; a restore drill runs in
  a separate terminal where `DATABASE_URL` is unset and the scratch database is named only as
  `SGAA_RESTORE_TARGET_URL` (`restore`, `verify --restored`), closed when the drill ends. A drill
  never changes `DATABASE_URL`, so the next production backup cannot read scratch; if it ever did,
  the ledger would refuse that generation (it names another database as its source).
- **https only.** The ledger observes the public address over https; `--allow-insecure` is for
  the tests' loopback servers and is refused for any other host (`INSECURE_ONLY_ON_LOOPBACK`).
- **Never** run a tool against the live workstation database. The only touch of the live
  file is the read-only snapshot of GR0 and the byte copy of the stopped runtime of GR1.

## 1. Before C0 (rehearsal and review)

1. The dress rehearsal (SPEC slice 6) ran C1–C13 on DEV (C14 refused before its window) with fault injection and a rollback
   from every state before C13. Its index and the measured end-to-end time exist.
2. This runbook is amended with the measured numbers and its SHA-256 is frozen.
3. The final-candidate R3 review passed; the commit to deploy is the reviewed one.
4. `python tools/cutover_ledger.py init --ledger-dir <ledger>`; then `advance --state C0
   --evidence <json>` with `commit`, `runbook_sha256`, `rehearsal_index_sha256`,
   `review_verdict` (`PASS`) and `prod_project_sha256`: the SHA-256 of the PROD project
   reference GP0 names (`python -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" <ref>`).
   Every data-API proof is bound to it (C1 `DATA_API_NOT_THE_PROD_PROJECT`, C10
   `DATA_API_PROJECT_CHANGED`).

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
   address) must report `api_exposure.clean: true`, `database_identity_proven: true` and the
   `database_project_sha256` of the PROD project named at C0: the qualification proves that this
   connection belongs to the PROD project (the pooler's authenticated tenant), not to whatever the
   URL points at.
3. GP1, the Data API, in this order. These are the only PROD writes of this step and they
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
      (`DATA_API_WRONG_PROJECT`). A failure blocks C1; the check is never weakened. Its
      positive control (the same check on DEV with the override reset) FAILED as it must
      (SPEC A15); rerun it if the tool changes.
4. Capacity: the projected database size, storage bytes and monthly egress are below the
   Free limits with headroom; project pause is avoided by the daily scheduler pass and use.
5. GP2: the user places `APP_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `DATABASE_URL`
   (transaction pooler), `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SGAA_STORAGE_BUCKET`,
   `SUPABASE_PUBLISHABLE_KEY`, `APP_PUBLIC_BASE_URL`, `APP_ENV=production`,
   `SGAA_RUNTIME=hosted`, `TRUST_PROXY_XFF=1`, `SGAA_ADMISSION=operator`,
   `SGAA_OPERATOR_TOKEN` (at least 32 random characters, generated by the user) and the
   Google client values in the platform, by the dashboard or the interactive prompt (ground
   rules). `CRON_SECRET` is NOT set yet (the scheduler front stays disabled), nor is
   `SGAA_OPENING_REFERENCE` (it exists only after the reference, at GO). A deployment without
   `SGAA_ADMISSION` does not start (`HOSTED_ADMISSION_UNDECIDED`), even one that forgot
   `APP_ENV`.
6. Ledger C1 evidence: `pg_major`, `schema_current`, `rows` 0, `objects` 0,
   `data_api_toggle_off` (the user's statement: no probe can tell the toggle's state while the
   override stands), `data_api_override` APPLIED, `data_api_probe` NOT_SERVED (the
   smoke's PASS), `data_api_project_sha256` (printed by the smoke; it must equal C0's
   `prod_project_sha256`), `api_exposure_clean`, `capacity_ok`, `database_project_sha256` (from
   the readiness report; it must equal C0's `prod_project_sha256`, `DATABASE_NOT_THE_PROD_PROJECT`),
   `database_identity_proven` (true: the cluster identifier is readable; otherwise C1 waits, since every
   later generation would be refused as unproven).

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
   cutover-baseline` (**user terminal**: the session address, `PGPASSWORD` at the hidden
   prompt, never the password file); `verify --manifest`; the
   object set `python -m app.storage.cli backup-objects --destination <new dir>`, then
   `verify-backup --set <dir> --database`; restore drill into scratch PostgreSQL of the PROD
   major in the drill terminal (ground rules: `SGAA_RESTORE_TARGET_URL` only; `restore`, `verify
   --restored`, the clone probe of `PG_BACKUP_RESTORE_RUNBOOK.md` §H); drop the scratch database;
   keep two encrypted copies, one off-platform.
4. Ledger C8: `reference_digest`, `census_equal`, `baseline_manifest_sha256`,
   `object_set_digest`, `restore_drill`, `verify_backup`, `admin_bootstrap`.

### C9 DEPLOYED_DARK — gate GD1

From here until the opening the deployment admits only the operator
(`SGAA_ADMISSION=operator`, `docs/HOSTED_RUNTIME.md` §2a): every request without the operator
credential is refused with 503 before any session, view or database access. "Not announced" is
not the control; this is. Vercel Authentication is not relied on (SPEC A15); switch it off for
the production project as rehearsed, so the gate is what the probes observe.

1. `python tools/deploy_audit.py export --commit <reviewed commit> --out <new empty dir>`
   (committed content only, runtime allowlist) and `audit --dir <that dir>`: CLEAN. The
   export verifies every file against the commit's blob id and normalizes line endings
   itself (`core.autocrlf` of the workstation does not matter); `EXPORT_NOT_THE_COMMIT` means
   the bytes do not match the reviewed commit and nothing is deployed. Plant the sentinel
   file of the rehearsal in the audit (`audit --dir <dir> --sentinels <file>`) when you have one.
2. `vercel link` in that directory, then delete the `.env.local` (an OIDC token) and
   `.gitignore` the link writes.
3. Immediately before the upload, with nothing in between:
   `python tools/deploy_audit.py verify --dir <that dir> --commit <reviewed commit>` must print
   `IDENTICAL`: the directory holds exactly the commit's allowlisted files with the commit's
   blob ids, and the only extra files are `.vercel/project.json` and `.vercel/README.txt`.
   An added, removed or changed deployable file, a link, or any other extra file refuses
   (`DEPLOY_TREE_DIFFERS`, counts only; `LINK_IN_UPLOAD`) and nothing is deployed. Keep its
   `deploy_tree_sha256` for C9; if anything touched the directory after it, run it again.
4. Deploy that directory to the production project with the user-authenticated CLI, DARK:
   `npx vercel@<pinned> deploy --prod --skip-domain --yes` from the exported directory. The
   platform does not validate a descriptor: a rewrite to a service that does not exist deploys
   READY and, without `--skip-domain`, takes the public alias (rehearsed: every page answered
   404). The daily cron entry is in `vercel.json` but the scheduler front is disabled while
   `CRON_SECRET` is unset. Publish the one Hobby rate-limit rule:
   method `POST`, path matching `^/(login|esqueci-minha-senha|primeiro-acesso|redefinir-senha)$`,
   fixed window 600 s, limit 100, key `ip`, mitigation `rate_limit` with `rateLimit.action`
   `rate_limit` (the response is 429; `deny` answers 403). Rehearsed: the 101st request in a
   window is refused, a GET of the login page is not counted, and a window that keeps
   receiving requests stays refused.
5. **(user terminal)** `python -m app.hosting_cli check --database` with the production
   environment: ready, and the report names `admission` `operator`.
6. **(user terminal**, `SGAA_OPERATOR_TOKEN` at the hidden prompt**)**
   `python tools/hosted_smoke.py --base-url <deployment address> --admission closed`: its
   ADMISSION check (a client WITHOUT the credential: two pages and a credential POST each
   503 `X-SGAA-Admission: closed`, no cookie) is the C9 observation.
7. Ledger C9: `commit`, `readiness` READY, `bundle_audit` CLEAN, `deploy_verify` IDENTICAL,
   `deploy_tree_sha256`, `scheduler_front` DISABLED, `admission` CLOSED.

Every later redeploy of the same commit (GD2, the lift at GO, a rollback) repeats steps 1–4
from a fresh export, `verify` included, and is then promoted (`vercel promote <deployment id>
--yes`) so that the public address serves it; a dark deployment changes nothing the ledger
observes.

### C10 SMOKED

**(user terminal**, `SGAA_OPERATOR_TOKEN` and, for the sign-in, the operator password at
hidden prompts**)** `python tools/hosted_smoke.py --base-url <deployment address> --admission
closed --data-api-url https://<ref>.supabase.co --data-api-project-ref <ref> [--email
<operator>]` with `SUPABASE_PUBLISHABLE_KEY` in the environment. The smoke sends the operator
credential on every application request and proves, with a separate anonymous client, that
everyone else is still refused (ADMISSION). The DATA_API check is C1's. PASS required.

The public alias is then taken only after the dark deployment's own address passes the
smoke and the operator promotes it (`vercel promote <deployment id> --yes`, about 4 s; before
C11 the same command with the previous deployment id is the rollback; from C11 on, section 3).
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
(must equal C1's), `public_host_sha256` (from the run on the public address).

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
   and the same commit is redeployed (C9 steps 1–4, admission still `operator`); the daily
   pass is observed. If the backlog needs a higher cadence, the external trigger is created
   under the same gate, with no secret in it:
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
4. The ADMISSION check again (C9 step 6, public address): still closed.
5. Ledger C11: `account_key_match`, `mirror_passes`, `reconciliation_required` 0,
   `scheduler_front` ENABLED, `admission` CLOSED.

### C11 → C12 THE OPENING — gate GO

The order is binding and the ledger enforces it: no ordinary user can write before the
reference exists, because the deployment refuses them until the lift and the lift comes
after the reference.

1. Pre-opening generation, **(user terminal**, `PGPASSWORD` and `SUPABASE_SECRET_KEY` at
   hidden prompts; `DATABASE_URL` the session address**)**:
   `python tools/ops_backup.py --root <primary dir> --off-platform <second dir> --objects
   --label pre-open --ledger-dir <ledger>`. The Layer-2 set and the object set are taken and
   verified, the off-platform copy is compared file by file, and the ledger records the
   generation only after re-verifying it and proving its source: the live database is the PROD
   project's, the Layer-2 manifest's recorded source is that same database (identity derived from
   the manifest, never typed; `BACKUP_NOT_FROM_THE_PROD_DATABASE`), and the object set's sealed
   source names that database and the PROD project's store (`OBJECT_SET_NOT_FROM_THE_PROD_PROJECT`).
   The `backup` entry carries the source identity (value-free).
2. The reference, **(user terminal**, `PGPASSWORD`, `DATABASE_URL` the session address**)**:
   `python tools/cutover_ledger.py
   reference --ledger-dir <ledger> --expect-head <head> --base-url <public address>
   --backup-root <primary dir> --off-platform <second dir> --out <custody>/reference.json
   --backup-cadence-hours <h>` (UD10: `24`, at most 24). The ledger refuses unless the state
   is C11 with GO granted, no reference was taken before (`REFERENCE_ALREADY_TAKEN`: there is
   one reference per opening, so nothing written after it can be re-baselined), the address is
   C10's and is the production deployment (its scheduler front answers as enabled: CRON_SECRET has
   been set since GD2, so an older deployment is refused, `SCHEDULER_FRONT_NOT_ENABLED`), the
   deployment is observed CLOSED without any credential, the last recorded backup was
   made after C11 and includes an object set, that generation re-verifies from both directories
   and is current (its Layer-2 table digests equal the live fingerprint and its object set equals
   the live references). It then takes the fingerprint itself, writes the reference file (digests
   and counts only), records the reference, the database identity, the cadence and the RPO (= the
   cadence), and prints the new entry's `hash` (also printed as `head`).
3. The lift (GO). First, if the newest generation is older than the cadence allows (1.5 × `h`,
   or 1.5 weeks for the object set), record a new one (step 1 again): `open` would refuse it
   (`BACKUP_TOO_OLD_TO_OPEN`) only after users are admitted. Then the user sets
   `SGAA_ADMISSION=open` and `SGAA_OPENING_REFERENCE=<that hash>` (not a secret; `status` also
   prints it as `opening_reference`) and the same commit is redeployed and promoted (C9 steps
   1–4). A production deployment set `open` without a well-formed value does not start
   (`HOSTED_OPENING_REFERENCE_REQUIRED`). The value is the reference entry's chain hash: it is not
   known before this ledger records the reference (it covers the chain position and time), so a
   value left from an earlier attempt or computed from a fingerprint snapshot does not match, and
   `open` accepts no other. The open deployment announces a tag
   of it on every response (`X-SGAA-Opening`). `SGAA_OPENING_REFERENCE` stays set for as long as
   production is open (an open production deployment without it does not start); a rollback
   removes it. Keep `SGAA_OPERATOR_TOKEN` in the platform until C14: a rollback closes admission
   again with it.
4. `python tools/cutover_ledger.py open --ledger-dir <ledger> --expect-head <head> --base-url
   <public address>`: the ledger observes, at C10's address, admission OPEN and the tag of ITS
   reference (`OPENING_NOT_BOUND_TO_THE_REFERENCE` otherwise), and writes C12 from the reference
   (`reference_fingerprint_sha256`, `database_identity_sha256`, `opened_at`, `admission` OPEN,
   `pre_open_backup_manifest_sha256`, `backup_cadence_hours`, `rpo_hours`, `opening_bound`,
   `reference_age_seconds`); `advance --state C12` is refused (`OPENING_NEEDS_THE_OPEN_COMMAND`).
   A late lift is not refused: the reference still precedes it, and anything the operator wrote
   in between counts as a business write for the rollback (fail closed). The newest recorded
   generation must be within 1.5 × the cadence (`BACKUP_TOO_OLD_TO_OPEN`: record a new one first,
   which C11 allows), because the cadence is counted from the opening.
5. Announce. The local runtime stays stopped and protected.

### C12 OPEN_PONR_PENDING

- The cadence recorded at the opening is in force until C14: **(user terminal)**
  `python tools/ops_backup.py --root <primary dir> --off-platform <second dir> [--objects]
  --ledger-dir <ledger>` every `h` hours, with `--objects` at least weekly. A Layer-2 gap longer
  than 1.5 × `h`, or an object-set gap longer than 1.5 weeks, anywhere from the opening to C14
  refuses C14 (`BACKUP_CADENCE_BROKEN`, `OBJECT_CADENCE_BROKEN`). The cadence is measured by each
  generation's own creation time; a generation is recorded once (`BACKUP_ALREADY_RECORDED`), never
  older than one already recorded and never dated in the future, and only when its Layer-2 set and
  object set name the reference's database and the PROD store as their source (as at the opening):
  a generation of DEV, of scratch or of another project is refused and so counts for neither
  cadence nor the C14 drill. A scheduled task is not used for PROD: it would need a stored PROD
  secret (P6).
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

After UD4's 30 days from C13, with the cadence held: a generation made after C13 (and so
recorded with the PROD database as its source) restored into scratch PostgreSQL of the PROD major in
the drill terminal (`SGAA_RESTORE_TARGET_URL` only; `restore`, `verify --restored`), no unresolved
reconciliation, the object set verified. Ledger C14: `restore_validated_manifest_sha256` (that
generation's manifest digest, as recorded), `restore_drill` OK, `unresolved_reconciliation` 0,
`object_set_verified`. The ledger refuses before 30 days from C13 (`WINDOW_NOT_ELAPSED`), on a
cadence gap since the opening, and on a drill of a generation not made after C13
(`RESTORE_VALIDATION_NOT_A_WINDOW_GENERATION`). The window report lists them; MP-4 may then
be chartered.

## 3. Rollback (before C13)

| At | Do | Then |
|---|---|---|
| C1–C4 | stop; restart the workstation runtime if frozen | `cutover_ledger rollback --reason <CODE>` |
| C5–C6 | as above | bucket objects stay as additive orphans; removal only under GX1 |
| C7–C11 (no reference taken) | as above; admission is still closed; take the deployment down or pause it; remove `CRON_SECRET`; `select cron.unschedule('sgaa-mirror')` and delete the Vault entry if they exist | the PROD database is a copy; emptying it needs GX1 |
| C12, or C11 once a reference exists | in this order: (1) close admission: `SGAA_ADMISSION=operator`, remove `SGAA_OPENING_REFERENCE`, redeploy the same commit and promote it (C9 steps 1–4), then delete every deployment that ran `open` (`vercel remove <deployment url> --yes`) so that no address still admits users; (2) stop system writes: remove `CRON_SECRET` and redeploy (the scheduler front answers 404), `select cron.unschedule('sgaa-mirror')`; (3) **(user terminal**, `PGPASSWORD`**)** `python tools/cutover_ledger.py rollback --ledger-dir <ledger> --expect-head <head> --reason <CODE> --base-url <public address> --reference <custody>/reference.json [--derived-class <CLASS> ...]`; (4) pause the deployment; restart the workstation runtime | see below |

The C12 rollback is decided by the ledger, not by the operator. It observes, without any
credential, that admission is closed, that the scheduler front is disabled and that no
`pg_cron` job is active, and that the database is the reference's; it then takes the
fingerprint live in one read-only snapshot, waits 330 s, observes quiescence again and takes it
again: the two must agree (`QUIESCENCE_NOT_PROVEN`). Equal to the reference: recorded. Unequal:
refused `FINGERPRINT_CHANGED` -- go to C13 -- unless every changed table and column belongs to
the fixed derived classes, no row was added or removed, each changed row reproduces the derived
value from the reference row (`REQUISICOES_AUTO_REJECTION`: a returned request now rejected
with its note extended by the fixed automatic-rejection marker; `REQUISICOES_STUDENT_SEEN`: an
empty "seen" mark now set), and the operator's `--derived-class` list equals the observed
classes exactly (`DERIVED_CLASSES_NOT_ACKNOWLEDGED`). A file, a timestamp or a fingerprint typed
by the operator is never the evidence. Mirror files already in the Drive stay (additive).

From C11 with a reference, a `FINGERPRINT_CHANGED` (an operator write after the reference, or a
legacy-hash sign-in) cannot be followed by C13 at once, and no second reference is taken: the
cutover either goes forward -- the lift, `open`, then C13 recorded immediately with the changed
fingerprint -- or, only if no lift has happened (no user can have written), is abandoned with a new
ledger (PROD is a copy; emptying it needs GX1).

When a rollback from C12 is refused (`FINGERPRINT_CHANGED`), production goes forward: restore
`SGAA_ADMISSION=open`, `SGAA_OPENING_REFERENCE=<status opening_reference>` and `CRON_SECRET`,
redeploy and promote, re-enable the external trigger if it was used, and record C13 with the
changed fingerprint.

After C13 there is no rollback: use the latest Layer-2 generation and the frozen source for
manual reconciliation. Never improvise a reverse migration. A forward-fix deployment is the
one deployment action that remains: each one needs its own user message, recorded with
`grant --gate GF1 --ref <code>` (valid only after C13; the gates that act on the source or on
the first deployment are refused).

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
- `SGAA_ADMISSION=open` and `SGAA_OPENING_REFERENCE` stay set for the life of production: an
  open production deployment without the reference does not start.
