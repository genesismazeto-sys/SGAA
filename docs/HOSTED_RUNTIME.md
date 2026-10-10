# SGAA — Hosted runtime contract

Owner: `app/hosting.py` (mode, scratch, startup blockers); operator command `python -m app.hosting_cli`.
Authority of record for the contract: SPEC `docs/specs/MP-2-hosting-readiness.md`.
This document is the operator-facing reference; it holds no project state.

Two modes exist and are **declared**, never inferred:

| Mode | When | Disk | Database | Secrets |
|---|---|---|---|---|
| `local` (default) | the Windows workstation, development, tests | persistent project directory | SQLite or PostgreSQL | DPAPI store, then environment |
| `hosted` | `SGAA_RUNTIME=hosted` (Vercel, any serverless or container host) | scratch only | PostgreSQL only | environment only |

A serverless platform (`VERCEL`, `AWS_LAMBDA_FUNCTION_NAME`) with no declaration
refuses to start (`RUNTIME_MODE_UNDECLARED`); `SGAA_RUNTIME=local` is the explicit
override. An unknown value is refused (`RUNTIME_MODE_INVALID`).

## 1. Entrypoints

| Process | Entrypoint | Notes |
|---|---|---|
| web application | `main:app` | `main` registers the authorization gate and error handlers, so it is the full application. A WSGI host never runs `init_db`; use the readiness check below |
| scheduled jobs | `app.storage.scheduler:application` | its own function (section 9); authenticated by `CRON_SECRET`; never loaded by the web function |
| operator tools | `python -m app.storage.cli`, `python -m app.hosting_cli`, `tools/pg_backup.py` | run from an operator machine or CI with the environment of the target |

## 2. Startup blockers (hosted)

`create_app` refuses to build a hosted application unless these hold. Each
refusal is a `HostingConfigurationError` carrying fixed codes and variable names
(never a value):

| Code | Condition | Names |
|---|---|---|
| `RUNTIME_MODE_INVALID` / `RUNTIME_MODE_UNDECLARED` | unknown `SGAA_RUNTIME` / serverless platform without a declaration | `SGAA_RUNTIME` |
| `HOSTED_POSTGRES_REQUIRED` | `DATABASE_URL` is not a PostgreSQL URL | `DATABASE_URL` |
| `HOSTED_PROXY_TRUST_UNDECIDED` | `TRUST_PROXY_XFF` is not an explicit boolean | `TRUST_PROXY_XFF` |
| `HOSTED_SECRET_KEY_REQUIRED` | `APP_SECRET_KEY` missing, weak or a published value (whatever `APP_ENV` is: every cold start is a new instance, so an ephemeral key would end all sessions) | `APP_SECRET_KEY` |
| `HOSTED_STORAGE_CONFIG_REQUIRED` | production only: a canonical-storage variable is missing or malformed | `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SGAA_STORAGE_BUCKET` |
| `HOSTED_TOKEN_KEY_REQUIRED` | production only: no valid Fernet `TOKEN_ENCRYPTION_KEY` | `TOKEN_ENCRYPTION_KEY` |
| `HOSTED_PUBLIC_URL_INVALID` | production only: `APP_PUBLIC_BASE_URL` missing or not https | `APP_PUBLIC_BASE_URL` |

`TRUST_PROXY_XFF` is a decision, not a default. On Vercel set `1`: the platform
overwrites `X-Forwarded-For` with the real client address and never forwards a
client-supplied value (Vercel request-headers documentation, read 2026-10-09).
On a host that does not overwrite it, set `0`, and accept that the per-IP login
limit then sees the proxy address. Without a decision the per-IP limiter is
either bypassable or locks every user out together.

## 3. Variables

| Variable | Hosted use | Secret |
|---|---|---|
| `SGAA_RUNTIME` | `hosted` | no |
| `DATABASE_URL` | the web and scheduler functions use the Supabase **transaction pooler** (port 6543; the application disables prepared statements and keeps no session state). Operator tools that need one session (Layer-2 backup and restore, Path-B, convergence runs) use the direct or the session-pooler address and a libpq password file; Layer-2 refuses a transaction-pooler address. No password in logs | yes |
| `SGAA_PG_CONNECT_TIMEOUT` | seconds, default 10; ignored when the URL carries `connect_timeout` or `PGCONNECT_TIMEOUT` is set | no |
| `APP_SECRET_KEY` | session and CSRF signing; at least 24 characters, not a published value | yes |
| `TRUST_PROXY_XFF` | `0` or `1` | no |
| `APP_ENV` | `production` for the real deployment | no |
| `APP_PUBLIC_BASE_URL` | https origin, OAuth callbacks derive from it | no |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for `cloud_accounts.token_json` | yes |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth application (also the Picker values `GOOGLE_PICKER_API_KEY`, `GOOGLE_APP_ID`) | secret / no |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SGAA_STORAGE_BUCKET`, `SUPABASE_PUBLISHABLE_KEY` | canonical document storage | secret key only |
| `CRON_SECRET` | enables the scheduler front (at least 32 characters; unset or shorter: disabled) | yes |
| `SCHEDULER_MIRROR_BATCH`, `SCHEDULER_MIRROR_LEASE_SECONDS` | objects per mirror invocation (default 5, at most 25) and lease length (default 300) | no |
| `APP_LOG_DIR` | optional; defaults to `<scratch>/logs` when hosted, because `main` creates its log directory at import, before the factory runs. Logs also go to the platform stream (both the `app` and `main` channels) | no |

Hosted mode never reads or writes the DPAPI machine store; the Banco de dados page
shows the credential forms read-only with an environment-managed notice.

## 4. Filesystem

The only writable place is `<system temp>/sgaa-scratch` (`hosting.scratch_root()`),
created by whoever writes first. Scratch holds one request's upload while it is
parsed; nothing durable lives there and nothing may rely on a later request
finding it. Documents are canonical in Supabase Storage, images are database rows,
cross-request state (throttling, import previews) is in the database.
Legacy `local_legacy` documents are unreadable on a hosted runtime until they have
been converged (`python -m app.storage.cli converge`, MP-3).

## 5. Readiness check

```
python -m app.hosting_cli check [--database]
```

Prints one value-free JSON report: the mode, whether the process would start (the
blockers by code and variable name, or the class of an unexpected startup error),
the scheduler state, and with `--database` the connected schema version against
the code's target (`--database` needs a PostgreSQL `DATABASE_URL` and never opens
a SQLite file). With `--database` the report also names the connection kind
(`direct`, `pooler_session`, `pooler_transaction`; never the host) and the API
exposure of the schema (section 11); exposure that is not clean is "not ready".
Exit 0 ready, 1 not ready, 2 usage. It builds the application as
a start does, so a local-mode check creates the local directories a local start
creates. Run it with the target environment before promoting a deployment. `/health` additionally fails when the
hosted database is not at the code's schema version.

## 6. Login and password-recovery throttling

A single process throttles in memory; a hosted runtime is many instances, so the
same limits would never trip. When hosted, the counters live in the database
(`auth_throttle_events`, schema v16), with the same thresholds and windows:
`LOGIN_MAX_ATTEMPTS` per address, `LOGIN_ACCOUNT_MAX_ATTEMPTS` per account,
`LOGIN_WINDOW_SECONDS`, and the `PASSWORD_RESET_*` equivalents.

- Only a keyed digest is stored: `HMAC-SHA-256(APP_SECRET_KEY, scope | value)`.
  No address or e-mail can be read back. Rotating `APP_SECRET_KEY` therefore also
  clears every window, which is harmless.
- A failed login (and every recovery request) writes one row per key. A request
  that is already blocked writes nothing; a successful login clears its keys.
- Each write prunes the key's expired events and a bounded batch of the expired
  events of the scopes it wrote, with that scope family's window (rows another
  writer holds are skipped, never waited for).
- The limits are the configuration `create_app` always sets; a missing value
  fails the request (closed) instead of falling back to a second set of
  defaults. A store that cannot be read refuses the attempt (no fallback to
  memory, no pass-through).
- The check and the failure record are separated by the password hash, so a
  parallel burst is allowed about as many guesses as it has requests before
  any event lands; platform rate limiting is the complement.
- Residual: a flood of *distinct* keys still writes one row per request. Put the
  platform's rate limiting (Vercel Firewall) in front as defence in depth; it is
  a project setting, not code.
- Locally the in-memory limiters are unchanged.

## 7. Import previews

The activity-import preview (upload, review, confirm) keeps its state in
`admin_import_previews` instead of a file: the browser holds an unguessable key,
the table holds its SHA-256, the parsed payload and the owning administrator. A
preview expires after one hour, is visible only to the administrator who made it,
and is consumed by the transaction that applies it: two simultaneous
confirmations apply once, and an import that rolls back keeps its preview. The
uploaded CSV itself lives for the one request that parses it. A preview too
large to hold (8 MiB of payload) is refused like an invalid CSV. This applies in
every mode.

## 8. The Banco de dados page under PostgreSQL

The page and its routes follow the configured backend. Under PostgreSQL there is no
SQLite file to protect, so every file-maintenance route refuses before any effect
(manual backup, restore from snapshot or upload, provider uploads, destination
settings, retention, snapshot download and delete) and the page drops the surfaces
that only work on a file: the local-backup and destination-folder cards, the
operations, retention and snapshot cards, the automatic-backup chip, the folder
picker with its Google scripts, and each provider's destination and "send backup"
controls. What remains is the schema state, a card stating that the database is
protected by its provider and the documented operational procedure
(`docs/PG_BACKUP_RESTORE_RUNBOOK.md`), and the Google Drive and OneDrive account
cards (connect, test, disconnect), because the Drive mirror uses the connected
account. Nothing is listed from the local disk and the Windows task is not queried.

## 9. Scheduled jobs

The Drive mirror needs something to call it. The scheduler is a separate WSGI
callable, `app.storage.scheduler:application`, deployed as its own function: the
web application never loads it, so the web function does not carry the Drive
worker and the web route, RBAC and CSRF inventories do not grow.

| Request | Effect |
|---|---|
| `GET` or `POST /internal/scheduler/mirror` with `Authorization: Bearer <CRON_SECRET>` | one bounded mirror pass |

Answers are value-free JSON: `200` the pass ran (including "nothing due"), `503` the
canonical store or Drive is not runnable (`result_code`), `500` an unexpected failure
(a fixed code, never exception text), `401` missing or wrong credential, `405` other
method, `404` any other path or a disabled front.

- `CRON_SECRET` (at least 32 ASCII characters, surrounding whitespace ignored) enables
  the front; without it every request is a `404` (so a caller can tell "not configured"
  from "wrong credential"). It is compared in constant time over SHA-256 digests; nothing is read
  from the query string, no session or cookie is consulted, and no application,
  database or provider is touched before the credential is accepted.
- `SCHEDULER_MIRROR_BATCH` (default 5, at most 25) bounds the objects per
  invocation; `SCHEDULER_MIRROR_LEASE_SECONDS` (default 300, from 120 to 3600) sizes the
  lease. Keep the lease at or above the function's maximum duration plus a margin: a
  function killed mid-pass leaves its claims `syncing` until the lease expires, then MP-1
  releases them into `retry` (each such kill uses one of an object's attempts).
- Platform cron is at-least-once and may overlap (Vercel Cron documentation, read
  2026-10-09: `GET` with `Authorization: Bearer $CRON_SECRET`, no retry on failure,
  Hobby plans run at most daily). The MP-1 leases, fences and find-by-operation make
  duplicate and overlapping invocations safe: a claimed object is owned by one pass, and
  a pass that loses its lease ends as `lost` and is adopted by the next one rather than
  uploading a second copy.
- Only the mirror pass is scheduled. Convergence, requeue and object backup remain
  operator decisions (`python -m app.storage.cli`).
- Any caller works: Vercel Cron, `pg_cron` with `pg_net`, a CI job, `curl`.

## 10. Object backup

The database backup (Layer-2) holds rows and no object bytes. The object backup is
the other half: a self-checking set of every canonical object, written by an operator
to storage they control and encrypt (the set is personal data), outside the
repository.

```
python -m app.storage.cli backup-objects  --destination <new directory> [--label <text>]
python -m app.storage.cli verify-backup   --set <directory> [--database]
python -m app.storage.cli restore-objects --set <directory> [--bucket <name>]
```

| Command | Needs | Does |
|---|---|---|
| `backup-objects` | database, storage variables | reads every `storage_objects` row (active and retired) through the verified read and writes the set; never writes to storage |
| `verify-backup` | nothing (`--database`: database) | offline proof of the set; with `--database` also compares it with the current rows (missing / extra / changed) |
| `restore-objects` | storage variables only | puts the set's objects into the bucket without overwriting or deleting; adopts an existing object only when its size, SHA-256 and MIME type match |

Set layout: `MANIFEST.json` (per-object id, bucket, key, size, SHA-256, MIME,
lifecycle; the counts; the `objects_digest` and the `seal`) and
`objects/<sha256[:2]>/<sha256>`. The seal detects corruption and truncation; it is
an integrity check, not authenticity, so keep the set where it cannot be altered.

- A backup is complete or it does not exist: it is written to a staging directory and
  promoted by rename only when every object read back correctly; one unreadable
  object aborts it (exit 4) and names the ids and fixed codes.
- The destination must not exist and must lie outside the repository, by its path
  or through any link or junction. A promotion that fails after the set is
  complete (a lock, a permission) keeps the staging directory and names it
  (`PROMOTE_FAILED`, `staged_as`); `verify-backup` accepts it as it is. A killed
  run can leave `<destination>.partial-*`: it holds personal data, delete it.
  Files take the operator's default permissions: write the set to a protected
  location.
- Restore verifies the set first and refuses an invalid one before any storage call.
  An existing object is adopted only when its size, SHA-256 and MIME type match; a
  conflicting one is reported (`TARGET_CONFLICT`, exit 4) and never replaced;
  everything uploaded is read back. `--bucket` restores into another bucket under the
  same keys; without it each object goes to its recorded bucket. Re-pointing database
  references to a different bucket is a deliberate, separate step. Restore does not
  compare the set with the database: run `verify-backup --set <set> --database`
  first.
- Reports carry counts, ids and fixed codes only: no key, URL, file name or byte.
- Residual: scheduled object backup and restore from the Drive mirror are not
  provided; the operator set is the only copy beyond the provider's own protection.

## 11. Platform exposure (managed PostgreSQL with an HTTP data API)

SGAA reaches its database only through PostgreSQL connections as the schema
owner. A managed platform also maps an HTTP data API onto its own roles (on Supabase
`anon`, `authenticated`, `service_role`) and, by default, grants those roles every
new table, sequence and function. The API being switched off is not the only
defence: the grants are removed as well, so re-enabling the API by mistake exposes
nothing.

Three proofs, all recorded before real data is loaded:

1. the project's Data API toggle is off (a user action in the provider dashboard);
2. the API endpoint answers "not served" to a request with the publishable key;
3. `python -m app.hosting_cli check --database` reports `api_exposure.clean: true`:
   no table (including a column-level grant), sequence or non-trigger function is
   reachable by a probed role, no default-privilege entry would hand it a future
   object, and a new function is not executable by PUBLIC by default.

The probe names the roles in `pg_schema.API_ROLES` (the Supabase API roles); a
platform whose API roles are named otherwise needs them added, and a cluster
without those roles reports nothing probed.

Procedure, as the schema-owning role, before `python -m app.pg_schema provision`
and again after it (a clean probe is the acceptance, not the statements):

```
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES    FROM anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated, service_role;
```

The fourth statement is the global form on purpose: PostgreSQL grants EXECUTE on a
new function to PUBLIC by built-in default, and a per-schema entry can only add to
the global defaults, never remove that grant. It applies to functions the current
role creates later. Run the statements as the schema-owning role (the one that
provisions). The platform also keeps default-privilege entries for its own roles
(`supabase_admin`); they apply to objects those roles create, cannot reach objects the
owner creates, and the probe counts only the connected role's entries.

The owner keeps its own privileges, so the runtime, the triggers and the schema
contract are unaffected (`tests/test_mp3_api_exposure_real_pg.py`). The recipe
protects the objects that exist and those the owner creates afterwards; the probe,
not the statements, is the acceptance. Layer-2 dumps with `--no-privileges`, so a
restore into a managed project needs this procedure again before the application
opens.

## 12. Security posture on the platform

**Authorization.** A governed admin request whose RBAC requirement is missing or
invalid is refused (403, an error line with endpoint, method and access level; no
payload) in production, and raises everywhere else. The coverage guards make the case
unreachable for registered routes; the refusal is what a future unmapped route meets.

**Headers.** The application owns them (`_apply_security_headers`): `nosniff`,
`X-Frame-Options: SAMEORIGIN`, `Referrer-Policy`, `Permissions-Policy`, HSTS in
production (`includeSubDomains`) and a default Content-Security-Policy (`default-src
'self'`, scripts and styles allowing inline, the Google origins the Drive picker needs,
the Storage origin in `connect-src` only when `SUPABASE_URL` is configured). `vercel.json`
declares none, so there is one owner; the public smoke checks that they arrive at the
public address. `CONTENT_SECURITY_POLICY` overrides the default.

**Rate limiting.** The application throttle is durable (section 6) and covers `/login` and
`/esqueci-minha-senha`; `/primeiro-acesso` and `/redefinir-senha` are not throttled by the
application. The Hobby plan allows one WAF rate-limit rule per project; it covers the four
public credential POSTs together (`/login`, `/esqueci-minha-senha`, `/primeiro-acesso`,
`/redefinir-senha`), counted per address over the longest window (600 s). Its ceiling is
set above the application's own per-address limits combined (`LOGIN_MAX_ATTEMPTS` and
`PASSWORD_RESET_MAX_ATTEMPTS`, 10 failures each in 600 s, plus the successful submissions
of a shared campus address) so that the platform never refuses a legitimate user first;
the action is the default 429. Counters are per region and approximate. Attack Challenge Mode is the incident lever.

**Scheduler.** `CRON_SECRET` (at least 32 random characters) enables the front; it is
unset until the mirror is wanted (the cron entry then reaches a disabled front that answers
404). A route-level rule is not added: the user agent of a platform cron or of a database
trigger is spoofable and the bearer is the control.

**Secrets.** Only the platform holds production values; the repository, logs, the ledger
and every report hold none.

| Variable | Set by | Rotation effect |
|---|---|---|
| `APP_SECRET_KEY` | user, platform | sessions end, throttle windows clear |
| `TOKEN_ENCRYPTION_KEY` | user, platform | stored Google tokens become unreadable: reconnect Google |
| `DATABASE_URL` (transaction pooler) | user, platform | rotate the database password at the provider, update, redeploy |
| `SUPABASE_SECRET_KEY` | user, platform only | rotate at the provider, update, redeploy; never on a workstation file |
| `CRON_SECRET` | user, platform | redeploy; the old value stops working at once |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | user, platform | the legacy OAuth client; a new client cannot see the legacy Drive files (`drive.file`) |
| `SUPABASE_URL`, `SGAA_STORAGE_BUCKET`, `SUPABASE_PUBLISHABLE_KEY`, `APP_PUBLIC_BASE_URL` | user, platform | configuration, not secrets (the publishable key is public by design) |

A one-off operator credential (the production secret key for a gated run, a database
password through the libpq file) is scoped to one process and never written to a file.

**OAuth.** `APP_PUBLIC_BASE_URL` is https; the legacy `GOOGLE_REDIRECT_URI` /
`MS_REDIRECT_URI` variables are unset; the exact callback is registered on the legacy
OAuth client; the consent screen is published to production (a client left in testing
status expires refresh tokens within days).

**Administrator bootstrap.** Only when no login-capable full administrator exists; the
password is read at a hidden prompt and the tool prints the account e-mail on success, so
its output stays on the operator terminal and is never captured by the ledger or a report.

**Leaks.** The deployment is built from `tools/deploy_audit.py export` and checked with
`audit` (forbidden paths, database and dump signatures, secret shapes, planted sentinels,
links); runtime logs on Hobby are kept for one hour, so a leak is looked for at the moment
and the platform's log drains are not enabled for personal data.

**Dependencies.** The pinned runtime dependencies were checked against published
advisories (read-only). Same-major fixes are applied. `cryptography` 45.0.7 is outside
that bound: its fixed releases (46.0.5 and later, with `msal` 1.32 or later) were not
applied in MP-3; the advisories concern X.509 chain validation, PKCS7 decryption, EC public
key loading from numbers, non-contiguous buffers and the OpenSSL linked into wheels, none of
which the application calls. Bump `cryptography` and `msal` together in a hardening change.

## 13. Deployment on Vercel Hobby

The working tree beside the code holds the real database, its copies, uploaded documents
and logs, none of them in Git. A platform CLI that uploads "the directory" would publish
them, so a deployment is never made from the working tree:

```
python tools/deploy_audit.py export --commit <reviewed commit> --out <new empty directory>
python tools/deploy_audit.py audit  --dir <that directory> [--sentinels <file>]
```

`export` writes the committed content of one commit, keeping only the runtime allowlist
(the application, templates, static files, requirements and the descriptors below); tests,
docs and tools are not uploaded. `audit` refuses a forbidden path (databases, dumps,
documents, logs, `.env`), a SQLite or dump signature in any file, a secret-shaped value, a
planted sentinel and any link. Its output is counts, fixed codes and path digests (paths
only with `--show-paths`). The user-authenticated Vercel CLI then deploys that directory.

Descriptors at the repository root: `vercel.json` (two services -- web `main:app` and the
scheduler `app.storage.scheduler:application` -- the scheduler rewrite before the
catch-all and one daily cron entry; no response headers, the application owns them),
`.python-version` (3.12) and
`.vercelignore` (defence in depth, not the control). Hobby runs a cron at most once a day
(any minute within the hour): the entry reaches a disabled front until `CRON_SECRET` is
set, so one commit is rehearsed, deployed and promoted. A higher mirror cadence uses a
free external trigger that sends the same bearer (a Supabase `pg_cron` job with `pg_net`,
which is also database activity that keeps a Free project from pausing).

Limits the deployment lives with (Hobby, read 2026-10-10): `maxDuration` 300 s, a 4.5 MB
request or response body, one hour of runtime logs, one rate-limit rule per project, and a
monthly ceiling on invocations and active CPU after which usage stops rather than bills.
Student documents do not pass through the function (signed direct uploads); a CSV import
larger than the body limit fails at the platform.
