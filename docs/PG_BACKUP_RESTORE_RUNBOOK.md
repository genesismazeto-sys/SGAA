# SGAA — PostgreSQL logical backup / restore runbook (Layer 2)

Owner: `tools/pg_backup.py` (operator tool; the web application never imports
it and has no backup route for PostgreSQL —
`POSTGRESQL_BACKUP_IS_OPERATIONAL_NOT_WEB_UI`).
Tests: `tests/test_pg_backup_tool.py` (no database),
`tests/test_pg_backup_restore_real_pg.py` (real PostgreSQL + native tools).

## 0. Architecture and scope

| Layer | What | Owner | Status |
|---|---|---|---|
| 1 | Provider-managed backups / PITR (Supabase) | provider configuration | not available on the Free plan the deployment uses (paid feature); not an acceptance requirement |
| 2 | Operator-controlled logical backup of SGAA-owned objects, retained independently of the provider | this runbook | implemented, restore proven locally |

Layer 2 is **mandatory** and, on the Supabase Free plan, the only database backup (Layer 1 does not exist there). A Layer-2 artifact is an
**SGAA application backup**: the SGAA objects in schema `public` only
(39 tables incl. `pg_schema_meta`, 23 identity sequences, 15 functions,
constraints, 59 explicit indexes, 17 triggers; all rows except the four
schema-only tables, see §D2). It is **not** a
cluster dump and **not** a Supabase platform dump: roles, ownership,
privileges, `auth`, `storage`, `vault`, `extensions`, `realtime` and every
other provider schema are excluded by construction and refused if present in
the archive.

It protects **database rows only**. Files on local disk (`uploads/`),
Google Drive / OneDrive content and OAuth tokens are outside it (sections I/J).

Two procedures are kept apart throughout:

* **LOCAL / PLAIN PG qualification** — what was executed and proven
  (PostgreSQL 15.19, WSL2 cluster `127.0.0.1:54315`, Windows client 15.19).
* **FUTURE SUPABASE production procedure** — same tool and same contract, but
  every Supabase-specific point below is **unqualified** until the
  cross-environment proof of §Q has run on the actual project.

## A. Backup prerequisites

1. A checkout of the repository at a known commit (the manifest records the
   tool's git SHA and file SHA-256) and a Python environment with `psycopg`.
2. Native `pg_dump` and `pg_restore` whose **major is ≥ the server major**
   (the tool reads `server_version_num` and refuses otherwise:
   `CLIENT_OLDER_THAN_SERVER`). Point `SGAA_PG_BIN_DIR` at the binaries or put
   them on `PATH`. Do not assume a major: PG15 is only the local qualification
   environment.
3. `DATABASE_URL` naming the source database **without a password**.
4. The source is the SGAA contract: `validate_pg_schema` CURRENT (epoch
   `prod-1`, v16, contract digest), `schema_migrations` = provisioner baseline,
   17 triggers enabled, no extension-owned objects in `public`, the 64 Path-B
   domain checks green. Anything else is refused; the tool never repairs.
5. An output directory **outside the repository** (refused inside it:
   `OUTPUT_INSIDE_REPOSITORY`) on encrypted storage, with no leftover
   `*.sgaa-pgbackup-staging` file (§N).

## B. Credential handling

* Preferred: libpq password file — Windows `%APPDATA%\postgresql\pgpass.conf`,
  POSIX `~/.pgpass` (mode 0600): `host:port:database:user:password`.
* Fallback: `PGPASSWORD` set in the operator's shell for that session only;
  the native tools inherit it from the environment.
* Never: a password or other secret in `DATABASE_URL` /
  `SGAA_RESTORE_TARGET_URL` (userinfo, `password=`, `sslpassword=`,
  `oauth_client_secret=`, `scram_client_key=`, `scram_server_key=`, any
  case) — refused unread (`*_URL_CONTAINS_PASSWORD`); a password on any
  command line (the tool has no such option and puts none in subprocess argv).
  A mistyped option is a usage error (exit 2) that never echoes the argument.
* Output never contains the URL, password or subprocess environment. Native
  stderr is never forwarded; failures print `exit=<n> class=<CODE>` only.
* The **dump is sensitive** (it contains personal data and password hashes).
  The **manifest is non-sensitive**: identities, versions, counts, digests.

## C. Backup command

```
set DATABASE_URL=postgresql://<user>@<host>:<port>/<database>
set SGAA_PG_BIN_DIR=<dir with pg_dump/pg_restore>        (optional)
python tools/pg_backup.py backup --output-dir <DIR> --label <label>
```

`<label>`: 1–40 of `a-z 0-9 -`. Result: exactly three files

```
sgaa-pg-<YYYYMMDDTHHMMSSZ>-<label>.dump            pg_dump custom format
sgaa-pg-<YYYYMMDDTHHMMSSZ>-<label>.dump.sha256     "<sha256>  <file>.dump"
sgaa-pg-<YYYYMMDDTHHMMSSZ>-<label>.manifest.json   sealed, non-sensitive
```

What the command does: connects, prints the sanitized source identity, checks
versions, opens `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`, exports
the snapshot (`pg_export_snapshot()`), validates and reads the manifest state
**in that snapshot**, runs

```
pg_dump --format=custom --schema=public --no-owner --no-privileges
        --no-password --snapshot=<exported> --file <staging> --dbname <url>
```

while the exporting transaction stays open, ends the transaction, then
verifies the archive's own TOC (`pg_restore --list`) against the SGAA
contract, reads the archived identity states, builds the manifest and
promotes the files. Exit 0 and `result: BACKUP_OK` only after promotion.

Consistency semantics: rows, counts and digests in the manifest and in the
archive are the **same exported snapshot** (proven by the E-PG2 node: a writer
that commits after the export is in neither). Identity sequences are not
MVCC: pg_dump records each sequence when it reads it, which can be later than
the snapshot (never earlier). The manifest records the **archived** state
(what a restore yields) plus the in-snapshot observation; the tool refuses an
archive whose next id would not be above every archived row id
(`IDENTITY_BELOW_ROWS`) or whose sequence moved backwards. A sequence ahead of
the rows is safe: the next id skips values, it never collides. For the
cutover/offline backup traffic is stopped, so both coincide.

## D. Artifact verification (no database)

```
python tools/pg_backup.py verify --manifest <DIR>/<base>.manifest.json
```

Checks: manifest format and **seal** (`manifest_sha256` over the canonical
JSON — any edit → `MANIFEST_DIGEST_MISMATCH`); sidecar equals the manifest
(`SIDECAR_MISMATCH`); dump size/SHA-256 (`ARTIFACT_SHA_MISMATCH`); archive TOC
is exactly the SGAA contract and equals the manifest census (`TOC_*`);
archived identity states equal the manifest. Independently:
`sha256sum -c <base>.dump.sha256` (POSIX) or `Get-FileHash` (Windows).
The seal detects corruption and accidental edits; **authenticity** comes from
the encrypted, access-controlled storage of §E, not from the seal.

Manifest fields: format/version, `created_at` (UTC), label, scope and
pg_dump options, sanitized source identity (backend, host, port, database,
user, server version, cluster system identifier), server version/major/
encoding/collation, pg_dump and pg_restore versions, artifact file/size/
SHA-256, consistency mode, schema epoch/version/contract digest/latest
migration, per-table row count + normalized digest (39 tables; image `bytea`
content enters the digest as length + SHA-256, never as bytes; the four
schema-only tables are recorded as the empty state a restore yields), 23
identity records (`last_value`, `is_called`, `predicted_next_id`, `max_id`,
in-snapshot observation), TOC census + digest, 64 domain-check results,
triggers enabled, account/credential cardinality, `table_data_policy`,
the canonical-storage census (`storage`), tool git SHA + file SHA-256,
`result: ok`. No password, URL, token, configuration value, row value or
personal data. Manifest `format_version` 2 (prod-1/v16).

### D2. Table-data policy (canonical storage, ephemeral state)

| Table | Archive | Restored state |
|---|---|---|
| `storage_objects` | schema + data | exactly the source rows |
| `requisicao_arquivos.storage_object_id`, `admin_arquivos.storage_object_id` | schema + data | exactly the source references |
| `storage_upload_intents` | **schema only** (`EPHEMERAL_OMITTED`) | empty -- signed-upload workflow state is never restored; a client whose intent vanished uploads again |
| `storage_worker_status` | **schema only** (`TARGET_SIDE_RECREATED`) | empty = the authoritative "mirror worker never ran" state |
| `auth_throttle_events` (v16) | **schema only** (`EPHEMERAL_OMITTED`) | empty -- throttle windows are minutes of state; a restored database starts with every limit clear |
| `admin_import_previews` (v16) | **schema only** (`EPHEMERAL_OMITTED`) | empty -- a pending import preview is simply generated again |

The omission is enforced by `pg_dump --exclude-table-data` and by the TOC
contract (no `TABLE DATA` entry may exist for either table), not assumed from
empty tables. The manifest's `storage` census holds counts by lifecycle and
mirror state, the total size, a digest over id / bucket / key / SHA-256 / size
and the business-reference counts + digest -- no filename and no person.
**Object bytes are not in a Layer-2 archive**: they live in the canonical
Supabase bucket. Their backup is the operator object set
(`python -m app.storage.cli backup-objects`, `docs/HOSTED_RUNTIME.md` §10), taken
with the database backup and kept with it under the policy of §E. A database
restore does not check that the referenced objects exist in Storage; inside the
database every reference is FK-checked and domain-checked, and
`verify-backup --set <set> --database` run against the restored database reports
the references that differ from the set (missing, extra, changed).

## E. Off-platform storage requirement (retention policy)

Minimum policy (no vendor chosen here; final legal retention is not decided
by this runbook):

* stored **outside the repository**, **not** on the Vercel filesystem and
  **not solely** in the source Supabase account;
* **encrypted at rest**, with the encryption key held separately from the
  storage credentials;
* the three files are kept together; a set without its manifest is not a
  backup;
* the object-byte set (`backup-objects`) is personal data and follows the same
  policy: outside the repository, encrypted, off-platform, and verified
  (`verify-backup`) before it is trusted. Its seal is an integrity check, not
  authenticity: keep the set where nobody else can alter it;
* **at least two generations** retained;
* the **cutover baseline** (§P) is kept until a later generation has itself
  passed a restore validation (§F/§G);
* a periodic **restore drill** into a new scratch database is recommended
  (restore + verify + smoke), recorded with the manifest SHA it used.

## F. Restore into a new target

Only into a **new, empty** PostgreSQL database. Plain PostgreSQL:

```
CREATE DATABASE <new_name> ENCODING 'UTF8' TEMPLATE template1;   -- as a role with CREATEDB
set SGAA_RESTORE_TARGET_URL=postgresql://<user>@<host>:<port>/<new_name>
python tools/pg_backup.py restore --manifest <DIR>/<base>.manifest.json
```

Refused before anything is written: artifact checks of §D; a target URL
that does not route to exactly one host, port and database as libpq parses
it — multi-host lists, `host=` / `hostaddr=` / `port=` / `dbname=` /
`service=` / `servicefile=` query parameters (`TARGET_URL_AMBIGUOUS`; the URL
is not echoed); target `postgres`/`template0`/`template1`/`sgaa_qual` or any template
(`TARGET_PROTECTED`); the backup's source database (same cluster system
identifier + name) or the database named by `DATABASE_URL`
(`TARGET_IS_SOURCE`); non-UTF8; target major older than the source major;
`pg_restore` older than the archive's `pg_dump`; no CREATE on `public`;
**not empty** (`TARGET_NOT_EMPTY`).

**EMPTY (plain PG)** — all zero: schemas other than `public`, `pg_catalog`,
`information_schema`, `pg_toast` and temp schemas; relations, routines,
types, collations, operators in `public`; extensions other than `plpgsql`;
event triggers. An already provisioned SGAA schema is therefore refused;
there is no `--clean` and no `--force`.

Then:

```
pg_restore --exit-on-error --single-transaction --no-owner --no-privileges
           --no-password --use-list <filtered list> --dbname <target> <dump>
```

The filtered list comments out exactly two entries — `SCHEMA - public` and
`COMMENT - SCHEMA public` — because the target already has `public` (without
this, PG15 fails with `schema "public" already exists`; proven). Any failure
rolls back the single transaction; the tool then re-checks that the target is
still empty (`RESTORE_FAILED ... target verified still empty`, exit 1). If it
cannot prove that, or the run was interrupted: `RESTORE_OUTCOME_UNCERTAIN`,
exit 3 — drop that database and restore into a new one. Once `pg_restore`
has returned successfully the target **holds the restored data**; the tool
then verifies it (§G). A mismatch, a database error or an interruption during
that verification is `RESTORE_VERIFY_FAILED`, exit 3 (never "rolled back"):
do not use that database and do not restore into it again; after
investigation drop it and restore into a freshly created one. The tool never
cleans it up itself.

Target pinning (automatic): the restore preflight connection resolves the
target and runs every check above; `pg_restore` is then pinned to the
numeric server address that checked connection actually used (`PGHOSTADDR`
in the child environment, overwriting any inherited value; no second DNS
lookup). The URL keeps the original host name, so TLS `verify-full` hostname
validation and pgpass matching still use it. If the checked connection
reports no numeric address the restore is refused
(`TARGET_HOSTADDR_UNAVAILABLE`); an inherited `PGSERVICE` is refused
(`TARGET_ENV_ROUTING`) and `PGSERVICE`/`PGSERVICEFILE` are removed from
`pg_restore`'s environment. No operator step is involved.

## G. Verification command

```
set SGAA_RESTORE_TARGET_URL=postgresql://<user>@<host>:<port>/<restored>
python tools/pg_backup.py verify --manifest <...>.manifest.json --restored
```

Read-only (`REPEATABLE READ READ ONLY`, rolled back; no `nextval`): §D
artifact checks, then `validate_pg_schema` CURRENT (tables, columns, types,
nullability, identity, PK/unique/check/FK incl. the 41 FKs and their actions,
explicit/partial indexes, the 17 triggers, required functions,
`pg_schema_meta`), `schema_migrations` baseline, every table's row count and
normalized digest, all 23 identity states, 64 domain checks, 17 triggers
enabled, account/credential cardinality, the canonical-storage census, and
both schema-only tables EMPTY (`SCHEMA_ONLY_TABLE_NOT_EMPTY` otherwise) — each
compared with the manifest. Differences print `category=<C> object=<table>`
only. Against the quiescent source the same command reports exactly the
schema-only tables that hold rows there (the manifest describes what a
restore yields, not the source) and nothing else.

## H. Sequence verification

`verify --restored` compares `last_value`, `is_called` and the predicted next
id of all 23 identities with the manifest and checks next id > max(id). To
exercise real allocation **without touching the evidence database**, clone it:

```
CREATE DATABASE <b_prime> TEMPLATE <restored>;   -- no session may be connected to <restored>
-- on <b_prime> only:
SELECT nextval(pg_get_serial_sequence('<table>', 'id'));      -- = predicted_next_id
INSERT INTO admin_alertas (mensagem) VALUES ('probe') RETURNING id;  -- = predicted, no collision
DROP DATABASE <b_prime>;
```

The same clone is where trigger behaviour may be probed (a request snapshot
update and a cross-axis lineage update must be rejected with SQLSTATE
`SG001`).

## I. External file reconciliation

The database holds **references**: `admin_arquivos` `local_legacy` files
under the upload root, Drive ids in `requisicao_arquivos` / `admin_arquivos`.
A Layer-2 backup does not contain the files. After a restore, reconcile every
`local_legacy` row against the restored upload root (same relative path,
same size/SHA-256 as recorded at copy time) before opening traffic.
Profile photos and report screenshots (prod-1/v13 `usuarios_foto`,
`alunos_foto`, `reportes_captura`) are database rows, so they are inside the
archive and covered by the row digests; they need no file reconciliation.

An archive is bound to the contract version that wrote it: the manifest's
table set, schema version and contract digest must equal the tool's current
contract, so a v13 archive is refused by the v14 tool (`MANIFEST_INVALID`).
Restore an older archive with the repository revision recorded in its
manifest (`tool.git_sha`).
**`LOCAL_UPLOAD_STORAGE_PRODUCTION_BLOCKER_REMAINS`**: production has no
persistent upload storage yet; Vercel's filesystem is not one.

## J. Google Drive / OneDrive / mail reconnect

`EXTERNAL_RECONNECT_REQUIRED` for Google Drive, OneDrive and mail. OAuth
tokens are never the recovery mechanism (they are encrypted under a
machine-local key and are excluded by Path-B). Reconnect through the
application's OAuth flow with the **same Google account** that holds the
existing Drive-backed evidence, then open one Drive-backed file.

## K. R5 only where needed

A restore reproduces the credentials that existed at backup time. Run
`python -m app.admin_bootstrap --email <admin>` only when the restored
database has no usable full administrator (e.g. a baseline taken before the
first activation). It is not a routine restore step.

## L. Application smoke

Against the restored database (`DATABASE_URL` pointed at it in a
non-production process): `/health` 200; `POST /login` as a full admin → 302;
`/admin/acesso` → 200; one request detail; one local file (if any) served;
one Drive-backed file after §J.

## M. Promotion / repoint decision

A restore always produces a **new** database. Making it the application's
database is a separate, explicit operator decision taken only after §G, §I,
§J and §L are green: stop traffic, repoint `DATABASE_URL`, smoke, reopen.
The tool never repoints, renames or drops anything.

## N. Commit-uncertain and partial-artifact recovery

* Backup interrupted or failed before promotion: the tool removes this run's
  staging files. A **hard kill** can leave `*.sgaa-pgbackup-staging` files
  only — never bytes under a final name. The next backup into that directory
  is refused (`STAGING_LEFTOVER`, names the file); they are never a backup:
  delete them and rerun.
* A kill between promotions can leave `.dump` (+ `.sha256`) **without** the
  manifest; verify/restore refuse it (`MANIFEST_MISSING`). Delete that
  incomplete set; the manifest is promoted last and marks a complete set.
* An existing set is never replaced (`ARTIFACT_EXISTS`).
* Restore exit 3 (`RESTORE_OUTCOME_UNCERTAIN` / `RESTORE_VERIFY_FAILED`):
  the target may hold (for `RESTORE_VERIFY_FAILED`: does hold) a committed
  restore; do not use, repair or retry into it — drop it and restore into a
  new database.
* The source is never written by backup; nothing to reconcile there.

## O. Never restore destructively over production

No `--clean`, no restore into a non-empty database, no restore into the
source or into the database named by `DATABASE_URL`. Qualification and
drills always restore into a **new** database and never mutate the evidence
database (behaviour probes run on clones).

## P. Real cutover: immediate-backup sequence

1. Stop application traffic; confirm the SQLite `-wal` is 0 B.
2. Frozen byte copy; Path-B migrate it into the freshly provisioned target
   (`python -m app.pg_migrate_from_sqlite ... --apply`); validate.
3. R5 activation; application smoke on the new target.
4. **Immediately** take the Layer-2 cutover baseline (`<DIR>` as in §A.5:
   outside the repository, on encrypted storage):
   `python tools/pg_backup.py backup --output-dir <DIR> --label cutover-baseline`.
5. `verify --manifest`; restore drill into a scratch database
   (`restore`), §H clone probe, §L smoke against the scratch database; drop
   the scratch database.
6. Store the set in two off-platform locations (§E); record manifest SHA,
   artifact SHA and tool git SHA in the cutover record.
7. Reopen traffic. Keep this baseline until a later generation has passed a
   restore validation.

## Q. FUTURE SUPABASE production procedure (unqualified until proven)

* **Data API**: SGAA uses direct PostgreSQL connections. Before production
  data is loaded: **`SUPABASE_DATA_API_DISABLED`**, unless a future
  architecture explicitly introduces Data API access with its own
  authorization/RLS review. RLS is not implemented across SGAA for an unused
  API surface.
* **Major version**: do not assume PG15 or PG17. Read `server_version_num`;
  use native clients with major ≥ server major; re-run the materially
  relevant PG qualification (schema authority, E-PG1/E-PG2, route smoke,
  Path-B, this module) on that major.
* **Connection**: use a direct (or session-mode) connection for backup and
  restore; `pg_export_snapshot` / `--snapshot` need one session held for the
  whole dump, which transaction-mode pooling does not give.
* **Same contract**: `--schema=public`, `--no-owner`, `--no-privileges`;
  provider schemas are never dumped; the TOC check refuses anything else
  (including extension objects created in `public`).
* **Identity**: if `pg_control_system()` is not readable there, target/source
  identity falls back to normalized host/port/database.
* **Restore targets**: a new Supabase project is not EMPTY under the plain-PG
  definition (provider schemas and extensions exist), so the tool refuses it.
  The Supabase EMPTY definition must be adjudicated and qualified before any
  restore into Supabase; until then restore drills target plain PostgreSQL of
  a major ≥ the source.
* **Cross-environment proof (required before production)**: take a Layer-2
  artifact **from the actual Supabase project**, verify it, restore it into a
  new database, `verify --restored`, clone probes, smoke.
* Layer 1 (provider backups / PITR) is a paid provider feature and is not used
  on the Free plan; Layer 2, the object set (`docs/HOSTED_RUNTIME.md` §10),
  at least two generations, an encrypted off-platform copy and restore drills
  are the recovery posture, and the achievable RPO is the backup cadence.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | `BACKUP_OK` / `VERIFY_OK` / `RESTORE_OK` |
| 1 | refused or failed with nothing promoted / nothing restored (`RESTORE_FAILED` = rolled back, target proven empty); verify mismatch |
| 2 | usage (unknown option — there is no URL, password, `--force` or `--clean` option; the offending argument is never echoed) |
| 3 | restore needs reconciliation (interrupted `pg_restore`, or committed restore whose verification failed / could not complete): drop the target, restore into a new database |
