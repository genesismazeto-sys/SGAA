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
| `DATABASE_URL` | Supabase pooler or direct URL; no password in logs | yes |
| `SGAA_PG_CONNECT_TIMEOUT` | seconds, default 10; ignored when the URL carries `connect_timeout` or `PGCONNECT_TIMEOUT` is set | no |
| `APP_SECRET_KEY` | session and CSRF signing; at least 24 characters, not a published value | yes |
| `TRUST_PROXY_XFF` | `0` or `1` | no |
| `APP_ENV` | `production` for the real deployment | no |
| `APP_PUBLIC_BASE_URL` | https origin, OAuth callbacks derive from it | no |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for `cloud_accounts.token_json` | yes |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth application (also the Picker values `GOOGLE_PICKER_API_KEY`, `GOOGLE_APP_ID`) | secret / no |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SGAA_STORAGE_BUCKET`, `SUPABASE_PUBLISHABLE_KEY` | canonical document storage | secret key only |
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
a SQLite file). Exit 0 ready, 1 not ready, 2 usage. It builds the application as
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
