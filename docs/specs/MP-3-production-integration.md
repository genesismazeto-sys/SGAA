# SPEC MP-3 — Production integration and cutover

Status: FROZEN 2026-10-10; amended by the user's acknowledgement of the same day (§16)
Charter: "Take the hosting-ready SGAA from qualified DEV architecture to a fully rehearsed,
recoverable and production-ready Vercel + Supabase deployment, including the real-data
cutover plan and the first live Drive mirror operation. MP-1 and MP-2 contracts and
invariants are binding and must not be reopened."
Risk tier: R3 (authorization semantics, migration of real data, production actions, security
posture; `docs/OPERATING_MODEL.md` §8). R3 adds exactly three things to R2: this SPEC's
acknowledgement, a blind cross-family review of the final candidate, and the user gates of §10.

Cost constraint (binding, acknowledgement of 2026-10-10). Zero recurring platform cost: Vercel
Hobby and Supabase Free. No paid plan, add-on, PITR, compute, domain or provider feature is
selected, enabled or required, and an action that would cost money is hard stop H3 (§14).

Reading rule. *Preparation* (repository, local disposable, SGAA DEV, user-provisioned rehearsal
resources) and *production* (anything that touches Supabase PROD, a production deployment, the
institution's Google Drive or real student data) are separated everywhere below. Production
happens only through the gates of §10.2 and only after the final-candidate review passes.

## 1. Outcome

- An operator deploys the exact published commit as a Vercel Hobby web function and a separate
  scheduler function wired to Supabase Free PROD, at zero recurring cost, with the Data API off,
  the platform rate-limit rule in front of login, secrets only in the platform, and one readiness
  command and one public smoke command.
- The whole cutover — frozen source backup, census, convergence, Path-B, cross-check, deployment
  switch, smoke, first live mirror, rollback window, DR proof — is a state machine enforced by an
  evidence ledger and rehearsed end to end on DEV with production-shaped synthetic data, with a
  fault injected at every state and a rollback exercised from every state before the point of no
  return.
- Recoverability without any paid provider backup: a logical (Layer-2) and an object-byte backup
  taken from the managed platform restore into a different environment and the application boots on
  the result; backups run on a schedule, keep at least two generations and an encrypted off-platform
  copy, and are restore-verified.
- The first live Drive mirror is a supervised, bounded, verified operation, preceded by live proof
  on a DEV Google account when the user provides one.
- The security review is done and its decisions are recorded: authorization gate fail-closed in
  production, platform controls, secret and OAuth provisioning, administrator bootstrap, leak
  controls.

## 2. Current facts

Repository (verified 2026-10-10):

- Nothing deployable is declared: no `vercel.json`, `pyproject.toml`, `.python-version` or
  `.vercelignore`. Web entrypoint `main:app` (`main.py:674`); scheduler
  `app.storage.scheduler:application` (`app/storage/scheduler.py:143`).
- `.gitignore` excludes databases, uploads, documents and logs, yet the working tree beside it holds
  the real database and its pre-migration copies. A deployment taken from the working tree is a
  data-leak path (§8).
- `app/db.py:836` disables prepared statements and bounds connect time. Layer-2 needs
  `pg_export_snapshot`, one session for the whole dump (`docs/PG_BACKUP_RESTORE_RUNBOOK.md` §C, §Q).
- Path-B accepts only a source whose `user_version` equals the schema version, 16
  (`app/pg_migrate_from_sqlite.py:574`), refuses an unconverged `local_legacy` request row, requires
  an empty provisioned target, and does not move credentials or cloud accounts (Google is reconnected).
- The Drive scope is `drive.file` (`app/cloud_config.py:46`): the application sees only files its
  own OAuth client created or the user opened. The hosted deployment must therefore use the
  workstation's existing OAuth client identity; a new client cannot see the legacy hierarchy.
- `app/web/authz_gate.py:80`: under `IS_PRODUCTION` a governed admin request whose RBAC
  configuration was missing or invalid passed with a shadow log (changed by S3, A8). `docs/ENGINEERING_STANDARDS.md` §12
  defers that decision to this phase's security review.
- The application already sets the response security headers and a default CSP
  (`app/__init__.py::_apply_security_headers`; found by the S3 review, A8). Session cookies are
  `Secure` under `IS_PRODUCTION`. `TRUST_PROXY_XFF` is an explicit startup decision.
- `app/admin_bootstrap.py` prints the administrator's e-mail on success.
- Roadmap residuals assigned here (`PROJECT_STATE.md`): Vercel project and descriptors, rate
  limiting / WAF, Supabase qualification, DR proof (PITR is out: paid), `SUPABASE_DATA_API_DISABLED`, real census
  and convergence including terminal legacy rows and unsupported content, first live mirror,
  scheduled object backup and an off-platform object copy, public URL, secrets, preflight, smoke,
  administrator bootstrap, security review.

Providers (documentation read 2026-10-10; DEV metadata read through the Supabase API):

- Supabase DEV `sgaa-dev`: **PostgreSQL 17.11**, region us-east-1, `public` empty, extensions only
  in provider schemas. Every real-PG lane so far and every Layer-2 client binary is **15.19**, and
  Layer-2 refuses a client older than the server (runbook §A.2). The PROD major is unread.
- Supabase connections: serverless should use the transaction pooler (6543; no prepared statements,
  no session state); the direct connection is IPv6-only without an add-on; the session pooler
  (5432) is IPv4. Free plan: no provider backups and no PITR (both paid); 500 MB database, 1 GB
  storage, 5 GB egress, two projects (DEV and PROD use both); a project with low database activity
  over seven days is paused; database backups never include Storage objects; the Data API has a
  project toggle.
- Vercel (Hobby): a Flask preset is one function and takes precedence over `/api` files; a second
  function needs Services (Beta), legacy `builds` or a second project. Python bundle 500 MB; request
  and response body 4.5 MB; `maxDuration` 300 s. Cron is a `GET` with `Authorization: Bearer
  $CRON_SECRET`, not retried, possibly duplicated, redirects not followed, **at most once a day
  (±59 min)**. WAF rate limiting is fixed-window, counted per region, **one rule per project**
  (three custom rules in all). One hour of runtime logs; 1 M invocations and 4 active-CPU hours a
  month, after which usage stops (no overage billing); 100 deployments a day. The Hobby terms
  restrict use to personal or non-commercial purposes (read 2026-10-10); that eligibility is the
  user's decision of record (§16, U1). Flask static files should be served from `public/**`.

Unknowns and how each resolves: PROD PostgreSQL major, region, plan, compute (GP0); real volume,
classes and terminal rows (GR0); Services, headers, static and cron behaviour on the user's Vercel
account (S2 on the rehearsal project); PostgreSQL 17 and pooler behaviour (S1); live Google
behaviour (DEV Google if provided, else GG2).

## 3. Target design

### 3.1 Environments

| Tier | Contents | Rule |
|---|---|---|
| E0 | repository, local disposable PostgreSQL 15 and 17, pytest | unchanged autonomy |
| E1 (DEV) | Supabase DEV database and run-owned buckets, a user-provisioned Vercel Hobby rehearsal project, an optional DEV Google account (the Free plan's two projects are DEV and PROD, so no third project) | standing authorization on acknowledgement (§10); synthetic data only |
| E2 (PROD) | Supabase PROD, the production Vercel project and its free hostname, the institution's Google account, the workstation database and document roots | only through gates |

Rehearsal data is synthetic and production-shaped: a deterministic generator driven by a value-free
shape profile (counts by class) builds a v16 SQLite source; every rehearsal value that must never
leak carries a sentinel so a leak audit can search outputs, logs and bundles for it.

### 3.2 Deployable shape and owners

| Artifact | Single responsibility |
|---|---|
| `vercel.json`, `pyproject.toml`, `.python-version`, `.vercelignore` (root) | declarative deployment: two functions, `maxDuration`, the daily cron entry, bundle exclusions, Python 3.12. No logic and no response headers (the application owns them) |
| `tools/deploy_audit.py` (new operator tool) | refuses a deployment source or built output that holds a forbidden path, database or dump signature or sentinel; value-free |
| `tools/hosted_smoke.py` (new operator tool) | public HTTPS smoke, read-only, value-free (checks listed at state C10) |
| `tools/cutover_ledger.py` (new operator tool) | the state machine as an append-only hash-chained ledger outside the repository; validates order and evidence, executes nothing |
| `tools/pg_fingerprint.py` (new operator tool) | read-only business-table fingerprint of PROD: the PONR detector (A10) |
| `tools/ops_backup.py` (new operator tool) | sequences Layer-2 backup, verify, object backup, verify, rotation and the off-platform copy; value-free log |
| `app/hosting_cli` (extended) | `check --database` also reports whether provider API roles hold privileges on SGAA tables and the connection kind |
| `app/web/authz_gate` (changed) | production fail-closed (UD7) |
| `tools/pg_backup.py` (extended) | PostgreSQL 17 corrections found by S1 and an explicit Supabase restore profile (allow-list of provider schemas and extensions; the strict plain-PG definition stays the default) |
| `docs/PRODUCTION_CUTOVER_RUNBOOK.md` (new) | operator procedure: states, gates, rollback, smoke, DR drill, command templates, no values |
| `docs/HOSTED_RUNTIME.md`, `docs/PG_BACKUP_RESTORE_RUNBOOK.md` (extended) | the contracts the above change |

Two functions. The web function is `main:app`; the scheduler function is
`app.storage.scheduler:application` and is never loaded by the web function (MP-2 D6, I3). The
packaging mechanism is chosen by qualification in S2, in this order, taking the first that meets
P1–P5: Vercel Services; legacy `builds` in `vercel.json`; a second project. P1 the scheduler
function loads only the scheduler front; P2 the web function imports nothing from the I3 background
set; P3 the cron reaches the scheduler path and the bearer check passes; P4 per-function
`maxDuration` and region; P5 the bundle audit is clean. Static assets are copied at build to
`public/static/` when URL mapping works, otherwise served by Flask from the function.

Cadence on Hobby. Vercel cron runs at most once a day, so the scheduled mirror pass is a daily
floor. A higher cadence uses a free external trigger that calls the same authenticated front: a
Supabase `pg_cron` job with `pg_net` (database activity that also keeps the Free project from
pausing) or a scheduled CI job. The trigger carries only the bearer secret and is enabled when the
census backlog needs it (S2 qualifies it; GD2 enables it).

Deployment source. Always a clean export of a published commit (never the working tree), deployed
with the user-authenticated Vercel CLI after `deploy_audit` passes. `.vercelignore` is defence in
depth, not the control. No Git integration is attached to a protected branch.

Database access. The web and scheduler functions use the transaction-pooler URL. Operator tools
that need session state (Layer-2, Path-B, the readiness check) use the direct or session-pooler URL
and a libpq password file, never a URL password. S1 qualifies the application on the pooler.

PostgreSQL major. The binding major is the one read at GP0; 17 is qualified regardless because DEV
runs it. A PostgreSQL 17 cluster is added beside the persistent PG15 cluster, which is never touched.

Data API. "Off" is proven three ways, all recorded: the project toggle (user), a REST probe with the
publishable key returns not-served, and a catalog probe shows no privilege held by the provider's
API roles on any SGAA table (revoked by the runbook step if present).

### 3.3 Cutover state machine

Executed through the ledger; every transition names its gate, source identity (size and SHA-256 of
the frozen source) and value-free evidence. Transitions are forward-only; the ledger refuses a
skipped state, a different source identity, a digest that differs from C6, or an exception class
the user has not accepted.

| State | Gate | What happens | Exit evidence |
|---|---|---|---|
| C0 REHEARSED | — | S1–S6 done, runbook hash frozen, final-candidate review PASS, UD answered | rehearsal index |
| C1 PROD_QUALIFIED | GP0 GP1 GP2 | PROD major read; Data API off (three proofs); v16 provisioned and validated; private bucket; canary object round trip then removed; API-role privileges revoked; Free-plan capacity and pause preconditions recorded (database, storage, egress against the census); secrets in the platform | schema CURRENT, 0 rows, 0 objects |
| C2 SNAPSHOT_CENSUSED | GR0 | online snapshot copy of the workstation database, upgraded offline on the copy when needed; census; volume and classes; downtime budget from rehearsal throughput; disposition proposal | counts by class |
| C3 SOURCE_FROZEN | GR1 | workstation runtime and scheduled tasks stopped; no `-wal`; byte copy of database and document roots plus the file backup into an encrypted custody directory outside the repository | size, SHA-256 |
| C4 SOURCE_PREPARED | GR1 | on the copy only: offline upgrade to v16 if needed, integrity and FK checks, authoritative census; terminal and unsupported rows dispositioned per UD6 | accepted classes with exact counts |
| C5 CONVERGED | GR2 | `converge --apply` on the copy (resumable): deterministic keys into the PROD bucket; legacy bytes untouched | zero unaccepted rows |
| C6 SOURCE_CROSS_CHECKED | GR2 | `verify --deep` of the converged copy against the PROD bucket and its listing | clean verdict, reference digest D |
| C7 TARGET_LOADED | GR3 | Path-B dry run, then apply into the PROD database; validation | report; commit outcome known |
| C8 TARGET_VERIFIED | GB1 GP3 | `verify --deep` on PROD: digest equals D, census equal; administrator bootstrap only if no login-capable full administrator exists; **cutover baseline** (Layer-2 and object set), both verified, restore drill into scratch PostgreSQL of the PROD major, clone probe | digest equality, manifest identities |
| C9 DEPLOYED_DARK | GD1 | production deployment of the exact commit from a clean export, readiness `--database` ready, the one rate-limit rule published, the scheduler front disabled (no `CRON_SECRET`; the daily cron entry in the committed descriptor reaches a disabled front) | deployment identity |
| C10 SMOKED | — | `hosted_smoke`: TLS and hostname, `/health`, login page and cookie flags, response headers, unauthenticated admin refusal, static asset, scheduler probes (404/401), Data API probe, read-only authenticated checks by an operator account; its write set is pinned by a rehearsal tripwire | report |
| C11 MIRROR_PROVEN | GG1 GG2 GD2 | OAuth connect through the hosted UI (legacy client, registered callback); account key equals the source's; supervised bounded passes; `verify --drive`; `CRON_SECRET` set and the deployment redone (the same commit) so the daily cron reaches the enabled front and, if the backlog needs it, the external trigger enabled; first scheduled passes observed | results; none `reconciliation_required` |
| C12 OPEN_PONR_PENDING | GO | users admitted (announcement); the local runtime stays stopped and protected; the business-table fingerprint taken at the opening is the reference; rollback is still available | timestamp, reference fingerprint |
| C13 PONR_RECORDED | — | the first successful non-operator business write on PROD is detected (fingerprint delta) and recorded explicitly in the ledger; window W starts | the write's class and time, never its content |
| C14 WINDOW_CLOSED | — | W elapsed; no unresolved reconciliation; a later Layer-2 generation restore-validated; object set verified; hand-over to MP-4 | window report |

Order note. The charter lists the elements; MP-1 D12 and Path-B force convergence before Path-B for
local rows, and convergence on the frozen copy keeps the live source unmutated. The opening is after
the first live mirror and the cutover baseline on purpose: a failure there is rollback-free, and
rollback stays available after the opening until the first business write (§3.4).

### 3.4 Rollback and point of no return

| From | Rollback | Cost |
|---|---|---|
| C1–C4 | stop; restart the workstation runtime if frozen | none; PROD holds nothing real |
| C5–C6 | as above; PROD bucket keeps additive unreferenced objects, adopted by a rerun | none; removal only under GX1 |
| C7–C11 | as above; abandon the deployment (no cron, trigger disabled); PROD database holds a copy, so a retry needs it emptied (GX1) | none to source; PROD copy discarded; mirror files written to the Drive at C11 stay (additive, removed by hand) |
| C12 | as above: stop admitting users, pause the deployment, restart the workstation runtime; operator and system writes on PROD are discarded with the copy | none to source; users told once |
| C13 onward | forward-fix only | see below |

PONR is the first successful non-operator business write on PROD, not the opening. Opening only
starts PONR_PENDING (C12). The operator detects the write as a delta of the business-table
fingerprint against the one taken at the opening (`tools/pg_fingerprint.py`: row count and content
digest per business table; ephemeral, machine and mirror state excluded) and records it explicitly
in the ledger (C13); until it is
recorded, rollback stays the C12 row. Before it the workstation source is frozen, untouched and
authoritative, and no step changed it or any legacy byte. After it a return to the workstation
loses the hosted writes: MP-3 builds no reverse migration. Recovery after PONR is a Layer-2
generation (bounded by the backup cadence, since no provider backup or PITR exists on the Free
plan), and the frozen source plus legacy bytes stay intact for window W so a manual reconciliation
remains possible. W ends only on the C14 criteria; purge and legacy contraction are MP-4.

### 3.5 Backup, DR and schedule

- No provider backup or PITR is used or required. The Free plan has none, and database backups
  would exclude Storage objects in any case. Layer-2 (database) and the object set are the only
  recovery assets; the achievable RPO equals the backup cadence and is recorded, not promised.
- Layer-2 and object set: the cutover baseline at C8 (runbook §P), then `ops_backup` on the
  operator's machine at the cadence of UD10, at least two generations, one encrypted off-platform
  copy, every generation verified (`verify`, `verify-backup --database`), the baseline kept until a
  later generation passed a restore validation (runbook §E). A scheduled restore drill into scratch
  PostgreSQL is part of the procedure.
- DR proof, cross-environment, recorded with measured RTO and the cadence-bound RPO: DR1 (E1) a
  Layer-2 set taken from Supabase DEV, restored into local PostgreSQL of the same major with
  `verify --restored`, clone probes, application boot and smoke; object set DEV bucket → second
  run-owned bucket. DR2 (E2, GB1) PROD → scratch PostgreSQL on the operator machine plus
  object-set verification. DR3 (E1, S4) a synthetic Layer-2 set from local PostgreSQL (a different
  source) restored into the empty Supabase DEV database through the Supabase restore profile: the
  managed-target proof, with no third project.
- Recovery after total loss of the PROD project is a new Free project (after PROD is deleted, since
  two projects is the limit) restored from the latest verified generation through the same profile;
  the runbook states the steps and the DNS-free hostname consequences.

### 3.6 Security design

- Authorization gate: a governed admin request with missing or invalid RBAC configuration is
  refused in every mode (403 and an error log in production; the existing raise elsewhere). The
  RBAC-coverage guard and the actor-matrix guards are unchanged; a negative control proves the
  refusal.
- Platform: response security headers and the CSP are the application's (one owner; the smoke
  checks they arrive at the public address). Hobby allows one rate-limit rule, so it
  covers the login and password-recovery submissions together, set above the application's
  per-address attempt limit within the same window so the platform never refuses a legitimate user
  first; counters are per region, recorded as a residual. Everything else rests on the durable
  application throttle (MP-2). Attack Challenge Mode is documented as the incident lever.
- Scheduler: bearer `CRON_SECRET` (random, at least 32 characters, rotated by redeploy), fail-closed
  front, path rule limiting the route to the cron user agent as noise reduction only.
- Secrets: a matrix of every variable, its owner, generation, platform scope (write-only where the
  plan offers it), rotation effect (`APP_SECRET_KEY` ends sessions and clears throttle windows;
  `TOKEN_ENCRYPTION_KEY` forces a Google reconnect) and revocation. The executor never receives a
  PROD value. `SUPABASE_SECRET_KEY`, which the hosted runtime requires, lives only as a protected
  platform environment secret provisioned by the user (GP2); never in the repository, a log, the
  ledger or model context. A one-off operator credential is process-scoped and never written to disk.
- OAuth: `APP_PUBLIC_BASE_URL` https; legacy redirect variables unset; the exact callback registered
  on the legacy OAuth client; consent screen verified as in production, since a testing-status
  client expires refresh tokens within days.
- Administrator bootstrap: only when no login-capable full administrator exists, password at a
  hidden prompt, output on the operator terminal only and never captured by the ledger.
- Leak controls: bundle audit, sentinel search of logs and reports, value-free ledger, platform log
  retention noted (hours to a day), error pages checked for traces, advisory review of the pinned
  dependencies (a same-major bump for a published advisory that affects a used feature is allowed,
  with T5).

## 4. Decisions

- D1 — Convergence runs on the frozen copy, before Path-B. Rejected: converging the live database
  (mutates the authoritative source) and converging on the target (couples cutover to the hosted
  OAuth reconnect before data is complete).
- D2 — Two functions, mechanism by qualification (§3.2). Rejected: a scheduler route inside the web
  application (reopens MP-2 D6, I3).
- D3 — Deploy from a clean export of a published commit with the user's CLI. Rejected: deploying the
  working tree; wiring a Git integration to `main` or `clean-baseline` (protected).
- D4 — Runtime on the transaction pooler; operator session-state tools on direct or session pooler.
- D5 — PROD major is binding; 17 qualified because DEV runs it; PG15 evidence is kept, not reused.
- D6 — Data API off proven three ways, privileges revoked as defence in depth.
- D7 — The ledger validates and records; it never executes a step. Rejected: an orchestrator that
  performs PROD actions (a second authorization surface).
- D8 — The smoke is read-only and its write set is pinned; an operator business write after C8 would
  move the fingerprint the PONR detector compares against.
- D9 — PONR is the first successful non-operator business write, recorded explicitly (C13); the
  opening (C12) is only PONR_PENDING. No reverse migration (MP-3 does not build one; the window and
  the Layer-2 generations are the mitigation).
- D10 — The mirror cron is added by redeploy at C11, not before; on Hobby it is daily, and a free
  external trigger raises the cadence only when the backlog needs it.
- D11 — Backup automation is an operator-side wrapper with an off-platform copy; scheduling the
  operator's machine task remains an operator action (the Windows scheduler is MP-4's). No paid
  provider backup is an acceptance requirement.
- D12 — Authorization gate fail-closed in production (UD7).
- D13 — No schema change and no new runtime dependency; advisory bumps within the same major allowed.
- D14 — Rehearsals use synthetic production-shaped data only; real data is never loaded to DEV.
- D15 — Terminal legacy rows and unsupported content: fail closed. Rows that cannot converge stay
  legacy, unavailable when hosted, bytes untouched, listed by class and count in the cutover record;
  the ledger accepts only the exact classes and counts the user signed at C4 (UD6).
- D16 — Zero recurring cost is a product requirement: any step that would cost money is hard stop
  H3 and no gate can grant it; capacity limits of the Free plans are checked before load (C1, C2).
- D17 — Hosting is Vercel Hobby with Supabase Free and is closed. It reopens only if Vercel itself
  produces a concrete technical blocker during implementation (§14).

Open decisions (product or architecture): none. The user decisions UD1–UD10 carry
recommended defaults and are batched with the gates in §10.

## 5. Phase invariants

- P1 No real student or personal datum in a prompt, review packet, commit, fixture, ledger, log,
  bundle or report; every rehearsal output is searched for sentinels.
- P2 No MP-3 tool runs against the live workstation database. The only operation on it is taking a
  read-only snapshot (GR0, SQLite's online backup interface) or the byte copy of the stopped
  runtime (GR1); every tool then works on that copy, identified by size and SHA-256.
- P3 No MP-3 step mutates the source database, a legacy Drive file or a legacy local file
  (MP-1 I2; the mirror only adds, MP-1 D5).
- P4 No PROD or real-data action without its gate; a gate covers its state including resumption,
  nothing else.
- P5 Fail closed: an unknown transition, a digest mismatch, an unaccepted exception or a missing
  gate refuses.
- P6 A PROD secret is never written to disk, the repository, the ledger or a log.
- P7 MP-1 I1–I5 and MP-2 H1–H6 hold; `ENGINEERING_STANDARDS.md` guards stay (a guard changes only
  for a contract this SPEC declares, with negative controls).
- P8 No MP-4 action: no purge, no contraction, no retirement of Windows / SQLite / DPAPI paths.
- P9 No step selects, enables or requires a paid plan, add-on or provider feature.

## 6. Scope

- Allowed: root deployment descriptors; `tools/` (the five new tools of §3.2 and `pg_backup`);
  `app/web/authz_gate.py`; `app/hosting_cli.py`; `app/hosting.py` and `app/pg_schema.py`
  (read-only probe and classifier, A6); deployment-facing parts of `app/__init__.py` if a
  qualification proves them necessary; `docs/` governance, runbooks and `HOSTED_RUNTIME`;
  `ENGINEERING_STANDARDS.md` §2 owner facts; `PROJECT_STATE.md`; `tests/` (new `mp3` modules and
  support; existing guards only where §3.6 declares a change).
- Protected: web routes, endpoints, RBAC and CSRF inventories; schema v16; the signed-TUS contract;
  MP-1 outbox, mirror and convergence semantics; MP-2 throttle, preview and scheduler contracts;
  `main.py`; the Windows runtime scripts; the workstation database and document roots.
- Planned local refactors (§8): none expected; the gate change is a few lines in its owner.
- Out of scope: MP-4; any schema change; reverse migration; CSP; OneDrive; scheduled mirror of
  retired objects; the deferred-hours spreadsheet import.

## 7. Data & schema

- No schema change; v16 on both engines. A need discovered by the PostgreSQL 17 qualification is a
  hard stop H6 and a SPEC amendment, never an opportunistic migration.
- Path-B and Layer-2 policies are unchanged; the Supabase restore profile changes only the target
  emptiness definition, behind an explicit option.
- Real-data custody: source frozen, copied, hashed, operated on as a copy, never the live file;
  convergence idempotent, resumable and dry-run first (MP-1 §7); Path-B has no force path and rolls
  back wholly before commit; commit-uncertain is resolved by inspecting the target, never by blind
  rerun (Path-B module contract).

## 8. Security & RBAC

- No new or changed web route, endpoint, RBAC mapping or CSRF surface. The one behavioural change is
  §3.6's gate refusal, which affects only an unmapped governed route; the coverage guard says none.
- The deployment-from-working-tree leak path is closed by D3, the audit and the sentinels.
- Personal data lives only in E2, the operator's encrypted custody and backup sets, and the
  production Drive; reports, ledger and logs hold counts, classes, digests and fixed codes.

## 9. Compatibility / rollout

- The local Windows runtime, SQLite, DPAPI and their scheduler are unchanged and stay the rollback
  asset until MP-4. Hosted behaviour is inert until a deployment is made.
- Order: S1…S6, final-candidate review, then S7 under gates. The user may hold S7 indefinitely; the
  phase then closes as prepared (§13).

## 10. External boundaries, user decisions and gates

Standing authorization on acknowledgement (E1 only, run-owned, unique per run, cleaned up, leak
audited):

- Supabase DEV `sgaa-dev`: the database `public` schema is declared run-owned and reset between
  rehearsals; private buckets `sgaa-mp3-<run>`; objects; the DEV secret key kept outside the
  repository. The Data API toggle and project-level settings are the user's (GA4).
- The rehearsal Vercel project the user provisions (GA1): deployments, environment variables of that
  project, its cron entry and its one rate-limit rule; never a production hostname.
- DEV Google (GA2), if provided.
- Local: disposable databases on PG15 and PG17 clusters, pytest directories, a scratch custody
  directory outside the repository. Read-only documentation and provider metadata.

### 10.1 Batched user decisions

One acknowledgement of this SPEC adopts every default below unless the message names a different
answer. Gates (§10.2) are separate acts.

| # | Decision | Default (recommended) | Alternative and consequence |
|---|---|---|---|
| UD1 | Vercel plan | **Hobby (user decision of record)**; no upgrade. Consequences accepted: daily cron floor, one rate-limit rule, 300 s, 1 h of logs, hard usage ceiling | none: Pro is not selectable under the cost constraint |
| UD2 | Supabase protection | **Free plan; no provider backup or PITR**; Layer-2 and the object set compensate | none |
| UD3 | Public host | the free platform hostname; a custom domain only if the user already owns one and it adds no recurring cost | changing the host later reconnects Google |
| UD4 | Rollback window W | 30 days after C13 (PONR_RECORDED) | shorter/longer; MP-4 cannot start before it closes |
| UD5 | Maintenance window | one window of at least twice the S6-measured end-to-end time, announced; date is an input at GR1 | a shorter window needs the optional pre-seed pass (apply on a snapshot copy before the freeze) |
| UD6 | Terminal and unsupported legacy rows | D15 fail-closed policy, each class accepted by count at C4 | remediate before cutover (re-upload through the application) or block the cutover until zero |
| UD7 | Authorization gate in production | fail closed (403, error log) | keep shadow allow: a future unmapped route would be open to every admin |
| UD8 | DEV Google account | provide one: live proof of `describe_file` and a mirror pass before touching the real Drive | none: the first PROD pass is one object, supervised, and the proof is the production Drive |
| UD9 | DR project | **void**: the Free plan allows two projects (DEV, PROD). DR3 restores a synthetic set from a different source into DEV | none |
| UD10 | Backup posture | zero-cost, operator-controlled: regular Layer-2, object sets, at least two generations, one encrypted off-platform copy (location and key custody named at GB1), restore verification; cadence default nightly Layer-2, weekly object set and after any convergence or bulk import; no provider backup is an acceptance requirement | slower cadence raises RPO; no off-platform copy is not accepted |

Inputs the user supplies at gates (not decisions): hostname and DNS, the window date, secret values
(typed into the platform), Google console changes, backup destination and key custody.

### 10.2 Gates

Gates. One explicit user message naming the gate id grants it; silence grants nothing. "P" touches
PROD, "R" real data, "D" deployment, "G" Google, "B" backup of real data, "X" destructive.

| Gate | Action | Reversal |
|---|---|---|
| GA1 | user provisions the Vercel Hobby account, an empty rehearsal project (Git integration off), CLI sign-in; no plan purchase | user |
| GA2 | optional: DEV Google account, test OAuth client, callback on the rehearsal URL | user |
| GA3 | void (the Free plan allows two projects) | — |
| GA4 | DEV Data API off; consent that DEV `public` is run-owned | user |
| GP0 | read PROD provider metadata (version, region, plan, usage against the Free limits, Data API, Storage settings); no SQL | none needed |
| GP1 | qualify PROD: provision v16 on the empty database, validate, private bucket, canary round trip removed, revoke API-role privileges, record the Free-plan capacity check and the Data API proof | empty again by GX1 |
| GP2 | the user places the production secrets in the platform; the executor sees no value | rotate |
| GP3 | administrator bootstrap on PROD, only when none is login-capable | GX1 before PONR |
| GR0 | read-only census of an online snapshot copy of the workstation database (value-free output) | delete copy |
| GR1 | freeze: stop the workstation runtime and tasks; custody copy and hash | restart |
| GR2 | converge apply from the copy: reads legacy Drive / local bytes, writes the PROD bucket | GX1 (objects) |
| GR3 | Path-B apply into the PROD database | GX1 |
| GB1 | cutover baseline: Layer-2 and object set from PROD to the operator's encrypted storage; restore drill into scratch PostgreSQL | delete scratch |
| GD1 | production deployment (dark) on the free hostname, the one rate-limit rule published | roll back / delete |
| GD2 | redeploy with the daily cron entry; enable the external trigger (a `pg_cron` job in PROD is a PROD database write) when the backlog needs it | redeploy without; job removed |
| GG1 | register the callback on the legacy OAuth client; connect Google through the hosted UI | disconnect |
| GG2 | first live mirror passes against the institution's Drive (additive; the mirror never deletes) | files removed by hand |
| GO | open to users: starts PONR_PENDING (C12); PONR itself is recorded at C13 | stop admitting users while pending (§3.4) |
| GX1 | empty the PROD database or remove unreferenced PROD bucket objects this phase created, before PONR | irreversible by design |

User-only acts, never gates the executor holds: creating and revoking credentials (including
revoking the DEV rehearsal secret when S6 ends), billing, DNS, Google console, protected branches,
tags, releases, pull requests. Any PROD access not in this table, and any action that would cost
money, is hard stop H3.

## 11. Evidence plan

- Every slice: T0; T1/T2 for new owners; T3 by grep of importers and literal path references; T4 =
  route inventory, CSRF inventory, RBAC coverage, actor matrix, C4 hook isolation, connection
  ownership, `test_pg_readiness_unit4_transactions.py`, residual-main guards, catalogue ledger,
  `test_storage_mp1_web_isolation.py`.
- Lanes: E-PG1/E-PG2 on **PostgreSQL 17** for every real-PG module of the readiness, MP-1 and MP-2
  families, Path-B and Layer-2, and again on the PROD major if it differs; E-LIVE-DB (Supabase DEV
  through the transaction pooler: throttle, preview claim, lock helpers, `SKIP LOCKED` claim; and
  through session mode: snapshot backup); E-LIVE (rehearsal deployment: functions, daily cron entry
  and the external trigger, headers, the rate-limit rule observed as 429, scheduler contract, TUS
  uploads with the Data API off); E-LIVE Google only on GA2.
- S6 dress rehearsal: C1–C14 on DEV with production-shaped synthetic data, throughput measured,
  one injected fault per state (killed converge, bucket conflict, unavailable Drive, wrong secret,
  failed deployment, duplicate cron, commit-uncertain simulated at the harness, corrupted backup),
  one rollback from every state before C13 (including from C12), ledger refusals proven, the PONR
  detector proven on a synthetic write, leak audit by sentinels.
- Mutation probes before each review: authz refusal removed; bundle-audit pattern removed; digest
  equality check removed; ledger order check removed; PONR marker removed; bearer comparison weakened;
  smoke write-set pin removed.
- Full suite: T5 at S3 (§5.1 A: a shared authorization gate) and at the final candidate (§5.1 G:
  deployment milestone), delta-qualified per TEP §6 where no invalidator is touched; the PG17 lane
  routing is itself an environment invalidator for the real-PG families.
- Reviews: R2 fresh-context review before S1–S5 land, targeted recheck after fixes; R3 below.
  - **R3 blind cross-family review** of the final candidate (frozen SPEC plus amendments, runbook,
    diff since the freeze, value-free evidence index, the questions: PONR and gate completeness,
    leak paths, the authorization change, rollback claims, DR claims, ledger bypass). Recommended
    reviewer: GPT-5.6 Sol, High, SESSION NOVA, run by the user from the executor's packet; MATERIAL
    findings fixed and rechecked by the same session before GP0. The user may also have the same
    reviewer read this frozen SPEC before acknowledging.

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | PostgreSQL 17 and Supabase DEV qualification: PG17 cluster, v16 provisioning on DEV, pooler and session lanes, exposure probe, Data API off with Storage working, Layer-2 client 17 | `hosting_cli`, `pg_backup`, tests, support | T1–T4; E-PG1/E-PG2 on 17; E-LIVE-DB; R2 | planned |
| 2 | Packaging and rehearsal deployment on Hobby: descriptors, mechanism qualification P1–P5, static, headers, daily cron and the external trigger, `deploy_audit`, rehearsal project | root descriptors, `tools/deploy_audit.py`, docs, tests | T1–T4; E-LIVE (GA1); R2 | planned |
| 3 | Security posture: authz gate fail-closed, the one rate-limit rule, secrets matrix, OAuth, bootstrap leak control, advisories, live negative probes | `authz_gate`, descriptors, docs, tests | T1–T4; T5; E-LIVE probes; R2 | planned |
| 4 | Backup and DR without provider backups: Supabase restore profile, `ops_backup`, DR1 and DR3, RTO measured, cadence-bound RPO, schedule | `pg_backup`, `tools/ops_backup.py`, runbooks, tests | T1–T4; E-PG1; E-LIVE; R2 | planned |
| 5 | Cutover tooling and runbook: ledger, smoke, generator and harness, PROD qualification checklist, first-mirror procedure | `tools/cutover_ledger.py`, `tools/hosted_smoke.py`, runbook, tests | T1–T4; ledger mutation probes; R2 | planned |
| 6 | Full DEV dress rehearsal and final candidate: S6 evidence plan, runbook amended with measured numbers, packet for R3, T5 | tests, runbook, docs | rehearsal index; T5; R3 PASS | planned |
| 7 | Gated production execution C1–C14 | none in code; ledger and runbook | gate-by-gate evidence | gated |

S1, S4 and S5 do not depend on GA1; a missing GA1 is a BLOCKER for S2/S6 only. Landing order S1, S4,
S2, S3, S5, S6.

## 13. Acceptance criteria

- AC1 — The deployable artifact built from a clean export contains no forbidden file and runs the
  web and scheduler functions as declared on the Hobby rehearsal project (P1–P5). Evidence: S2, audit
  negative control.
- AC2 — The application, Path-B and Layer-2 pass on PostgreSQL 17 (and the PROD major), through the
  transaction pooler and session mode; the Data API is proven off with Storage uploads working.
  Evidence: S1.
- AC3 — Authorization is fail-closed in production with guards intact; the rate-limit rule is observed;
  the scheduler contract holds live; the secrets matrix, OAuth and bootstrap controls are
  rehearsed; the leak audit is clean; R3 verdict PASS. Evidence: S3, S6, review.
- AC4 — With no provider backup or PITR assumed, a Layer-2 set taken from the managed platform
  restores into a different environment and the application boots on it; a set from another source
  restores into the managed DEV target; objects restore with read-back; backups run on schedule
  with two generations, an encrypted off-platform copy and restore verification; RTO is measured
  and the cadence-bound RPO recorded. Evidence: S4.
- AC5 — The state machine is enforced by the ledger and rehearsed with a fault and a rollback per
  state; the measured end-to-end time sets the maintenance window. Evidence: S5, S6.
- AC6 — Production (only when executed): every gate granted by the user with its evidence, C12 and
  C13 at recorded times, first live mirror verified, DR2 restore-validated, no cost incurred.
  Evidence: S7.
- AC7 — `ENGINEERING_STANDARDS.md` §13 self-audit passes.

Closure levels. *Prepared*: AC1–AC5 and AC7 met, R3 PASS, S7 pending the user's gates (closed with
that exception stated). *Cutover done*: AC6 as well.

## 14. Phase-specific hard stops

- Any secret, student datum or database file in a bundle, log, ledger, packet or commit (H5).
- Evidence that a PostgreSQL 17 or pooler behaviour requires a schema or data change (H6).
- No packaging mechanism meets P1–P5 on the Hobby account, or Vercel itself produces another
  concrete technical blocker (H11): the only reopening trigger for the hosting decision (D17).
- Any step that would cost money, or a Free-plan limit (database, storage, egress, invocations,
  active CPU, project pause) that the census or rehearsal shows cannot hold the institution's data
  (H3 / BLOCKER with options; never an upgrade).
- The PROD major cannot satisfy the qualified lanes (BLOCKER with options).
- The source fails integrity, FK or version checks, or the unaccepted-row share cannot be accepted
  by the user (H4).
- Any step that would alter the source database or a legacy byte (H4).

## 15. Deferred / known non-blockers

- A flood of distinct login keys writes one throttle row per request; the throttle check and the
  failure record are separated by the password hash (MP-2); the single Hobby rate-limit rule is the
  complement and is regional.
- Hobby: daily cron floor, 1 h of logs, a hard monthly usage ceiling that stops service rather than
  bills, and the personal / non-commercial terms the user accepted; Supabase Free: no provider backup,
  7-day inactivity pause, 500 MB / 1 GB / 5 GB limits.
- `main.py` still attaches a file handler when its directory is writable; the scratch path is
  predictable on a shared POSIX temp directory; a report description is bounded only by request size.
- No CSP (inline script); no reverse migration; OneDrive; mirror copy of retired objects; cross-account
  re-mirroring; widening the legacy content domain; the deferred-hours spreadsheet import.
- Purge of legacy bytes, retired objects and bucket orphans, contraction, and retiring SQLite,
  Windows scheduling and DPAPI paths: MP-4.

## 16. Amendments

Acknowledgement of 2026-10-10 (user; binding; no gate granted, no paid action authorized):

- U0 Cost: zero recurring hosting and platform cost is a product requirement of MP-3.
- U1 Hosting: Vercel Hobby. The Hobby terms (personal / non-commercial; "commercial" includes the
  financial gain of anyone involved in producing the project) and technical limits were presented;
  the user decided that Vercel remains the target and that other providers are not to be evaluated.
  Eligibility under the terms is the user's decision of record. The hosting decision reopens only on
  a concrete Vercel technical blocker (D17).
- U2 Database: Supabase Free; no paid PITR, compute or backup feature; Layer-2, the object set,
  generations, an encrypted off-platform copy and restore drills compensate.
- U3 Host name: the free platform hostname; a custom domain only if already owned and free of
  recurring platform cost.
- U10 Backups: regular Layer-2, object sets, at least two generations, one encrypted off-platform
  copy, restore verification; no provider backup is an acceptance requirement.
- UA1 Secret custody: `SUPABASE_SECRET_KEY` lives only as a protected platform environment secret
  provisioned by the user; never in the repository, logs, ledger or model context; one-off operator
  credentials are process-scoped.
- UA2 PONR: opening admits users and starts PONR_PENDING; PONR is the first successful
  non-operator business write on PROD, recorded explicitly; rollback stays available until then.
- UD4–UD8 defaults are adopted unchanged.

Executor amendments (consequences of the above; not material beyond what the user decided):

- A1 2026-10-10 — Provider-plan assumptions removed from §1, §2, §3.3–§3.6, §4, §10, §11–§15: Pro,
  PITR, daily provider backups, 40 WAF rules, 800 s and per-minute cron no longer appear as design
  inputs. The cutover states C12–C14 now separate opening, PONR and window closure.
- A2 2026-10-10 — UD9 is void and GA3 / GB2 are removed: the Free plan allows two projects, both
  taken. The managed-target restore proof (DR3) uses a synthetic set from a different source
  restored into the empty DEV database.
- A3 2026-10-10 — The mirror cadence on Hobby is a daily cron floor plus an optional free external
  trigger (§3.2); the external trigger is a GD2 action, not a new paid feature.
- A4 2026-10-10 — A capacity and pause precondition is added at C1 and C2 (§3.3, D16).
- A5 2026-10-10 — `docs/PG_BACKUP_RESTORE_RUNBOOK.md` (Layer 1 and §Q) is reconciled with the Free
  plan in the same change: provider backups and PITR are not available and not required.
- A6 2026-10-10 — Slice 1. (a) The engine SQL of the exposure probe lives in `app/pg_schema.py`
  (the schema owner, ES §5) and the connection classifier in `app/hosting.py`; §6 and slice 1 are
  widened to both files, read-only, no contract change (R2 review M2). (b) The Supabase DEV default
  ACLs (read through the provider API) grant `anon`, `authenticated` and `service_role` every
  privilege on new tables, sequences and functions in `public`, so the revocation recipe is part of
  provisioning and `hosting_cli check --database` is not ready while those roles reach the schema,
  including column grants, future-object default entries and PostgreSQL's built-in PUBLIC EXECUTE on
  new functions (review M1, N3). (c) PostgreSQL 17.11 passes the real-PG families (the two failures
  were pins of the major, now major-aware); the PG15 lane stays. (d) Layer-2 refuses a
  transaction-pooler address and a list of hosts. (e) The real-PG lanes against the Supabase DEV
  database (pooler and session modes) need the DEV database credential, a user-only input recorded as
  a BLOCKER for that sub-lane; every other S1 lane ran. Not material.
- A8 2026-10-10 — Slice 3. The authorization gate refuses (403 and an error log) a governed admin request
  with no or an invalid RBAC requirement in production (UD7); the three guards that encoded the shadow
  behaviour were updated with negative controls (non-production still raises, a mapped route is decided
  as before). Advisory review of the pinned runtime dependencies (read-only, 2026-10-10): same-major
  bumps applied (Flask 3.1.3 for the missing `Vary: Cookie`, Werkzeug 3.1.9, python-dotenv 1.2.2,
  requests 2.33.0, Pillow 12.3.0 and pypdf 6.19.0, which parse uploads). `cryptography` 45.0.7 carries 13
  advisories fixed only from 46.0.5 (and 48/49/50 for the others); 46 requires `msal` >= 1.32, which
  crosses D13's same-major bound, so it is deferred with this analysis: the advisories concern X.509 path
  validation, PKCS7 decryption, EC public-key loading from numbers, non-contiguous buffers and the
  OpenSSL statically linked into wheels, none of which the application calls (Fernet over bytes, token
  claims decoded without a signature check). Recommendation recorded for the user: bump `cryptography` and `msal`
  together in a hardening change. Not material to the design; the bump itself is the user's decision.
- A8b 2026-10-10 — Slice 3 review. The application already owns the response security headers and a
  default CSP, so `vercel.json` declares none (the first descriptor draft duplicated them, with a
  conflicting `X-Frame-Options`); the smoke now also requires the CSP header; the rate-limit rule is
  sized against the login and recovery limits together, and `/primeiro-acesso` and `/redefinir-senha`
  are named as not throttled by the application (covered only by the platform rule). Not material.

## 17. Closure

Filled in the last slice.
