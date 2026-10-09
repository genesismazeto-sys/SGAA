# SPEC MP-1 — Storage convergence

Status: CLOSED 2026-10-09
Charter: "Complete the hybrid-storage convergence layer: Supabase Storage remains
the canonical operational store, while Google Drive remains the required
asynchronous secondary mirror/archive and must never block canonical SGAA operations."
Risk tier: R2 (charter floor R2; provider integration on DEV, concurrency).

## 1. Outcome

- An operator runs the Drive mirror worker, which copies each active canonical object
  into the existing managed Drive hierarchy after the business commit. It uses
  bounded retries, fenced leases and recovery, and records health and audit data.
  Canonical operations never wait on it.
- An operator runs a census and a cross-check. Neither prints values. Together they
  prove or refute that database references, canonical Storage objects and Drive
  mirrors converge.
- An operator runs a convergence that starts as a dry run and can be resumed and
  repeated safely. It copies legacy `google` / `local_legacy` document bytes into
  canonical Supabase Storage, verified by size and SHA-256, and links the legacy rows.
  Legacy bytes are never touched.
- Every runtime path (read, remove, delete, replace) treats a converged legacy row as
  canonical, with no Google call. Path-B accepts converged rows.
- All of this is qualified on disposable data, real PostgreSQL 15 and a DEV
  rehearsal. No real legacy data is migrated (MP-3).

## 2. Current facts

- The outbox and lease primitives are in `app/storage/mirror_outbox.py`
  (`claim_due_mirror_work`, `complete_synced`, `mark_retry`,
  `mark_pending_disconnected`, `mark_reconciliation_required`,
  `release_expired_leases`, `record_worker_*`). No worker exists. A PostgreSQL claim
  uses `FOR UPDATE SKIP LOCKED` (E-PG2-proven in S2).
- v14 `storage_objects` already allows `origin` ∈ {`direct_upload`,
  `migrated_local_legacy`, `migrated_google`}. `uploader_user_id` is required only
  for `direct_upload`. A Drive account key, once bound, never changes
  (`trg_storage_objects_drive_account_bound`). See `app/prod1_storage_ddl.py`.
- v15 (`app/prod1_document_custody_ddl.py`): `provider='supabase'` requires full
  custody metadata. A legacy row that carries `storage_object_id` is legal, but the
  reverse implication is deliberately not enforced. Legacy `local_legacy` rows hold
  only `filename` and have no SHA, size, MIME, uploader or operation key
  (`app/prod1_comprovantes_v4.py:82`, `app/prod1_arquivos_v5.py:34`).
- Reads already dispatch canonical-first whenever `storage_object_id` is set:
  `app/views/comprovantes.py:58` and `arquivo_documents.is_canonical` (admin view,
  admin delete, student view and download).
- Request removal and request delete partition rows by `provider`
  (`app/comprovantes.py` `remove_comprovantes`, `delete_request_with_comprovantes`,
  `_retire_canonical_objects`). ARQUIVOS replacement refuses a legacy row that carries
  `storage_object_id` (`arquivo_documents.is_replaceable`).
- Drive conventions: request documents go to
  SGAA/COMPROVANTES/<turma>/<eixo>/<aluno> (`app/comprovante_hierarchy.ensure_request_hierarchy`,
  with context from `app/comprovantes._request_context`, which freezes the turma
  snapshot on first placement). ARQUIVOS go to SGAA/ARQUIVOS
  (`app/arquivos._ensure_arquivos_root`). Files are found idempotently through
  `appProperties` (`sgaaManaged`, `sgaaKind`, `sgaaOperation`, semantic properties),
  using find-operation-then-upload in `app/storage/google_drive.py`. Drive access uses
  the single active Google connection (`cloud_connections.get_active_cloud_account`,
  `app/storage/google_connection.resolve_google_managed_storage`).
- Path-B refuses `requisicao_arquivos` rows with `provider='local_legacy'` and
  copies the files of `local_legacy` ARQUIVOS (`app/pg_migrate_from_sqlite.py`
  `_UNSUPPORTED_LOCAL_REFERENCES`, `plan_local_assets`).
- The canonical adapter (`app/storage/supabase_store.py`) has no list operation.
  Server-side `upload` (POST `/object`, `x-upsert: false`) has never been
  live-proven. The Drive adapter has no metadata-by-id read.
- The existing operator CLI pattern is `python -m app.backup.sync` (`create_app()` plus
  an app context, deterministic exit codes).
- Unknowns: the real legacy volume and the share of unsupported content are measured
  by the census in MP-3, never in MP-1. No DEV Google environment exists, and the
  production Google account holds real data (see D15).

## 3. Target design

Owners (`app/storage/`, one concern each; `ENGINEERING_STANDARDS.md` §2 is updated in
the slice that creates each):

| Module | Responsibility |
|---|---|
| `mirror_outbox` (extended) | outbox state machine. Adds operator recovery: `requeue_for_mirror` (`reconciliation_required` → `pending`, attempts reset), `reset_missing_mirror` (`synced` → `pending`, Drive file cleared, account kept), and a `code` argument on `mark_pending_disconnected`. `MirrorWork` gains `attempts` |
| `drive_mirror` (new) | S4 worker: `run_mirror_pass`, Drive placement on the existing conventions, retry policy, active-Drive resolution shared by the storage background tools |
| `storage_audit` (new) | census and cross-check, value-free; reference digest; Drive verification of synced mirrors |
| `legacy_convergence` (new) | S5: eligibility rules (single owner, also used by the census), `plan` and `converge` (dry run / apply) |
| `cli` (new) | `python -m app.storage.cli` operator surface: argument parsing, app context, JSON report, exit codes. No logic of its own |
| `supabase_store` (extended) | `list_objects(bucket, prefix)` (paged, recursive, bounded) |
| `google_drive` (extended) | `describe_file(file_id)` → `RemoteObject` or `None` when the file is missing or trashed |
| `app/db.py` (extended) | `lock_admin_arquivo`, `lock_requisicao_arquivo` (PostgreSQL `FOR UPDATE`; no-op on SQLite under `BEGIN IMMEDIATE`) |

Mirror pass (`run_mirror_pass(conn, *, limit, lease_seconds)`):
1. `record_worker_started`.
2. Resolve the canonical store and the active Drive (account row before and after
   storage resolution must match). If the store is not configured, or no active
   Drive with a logical key exists, the pass ends having claimed nothing, with a
   result code (`STORAGE_CONFIG_MISSING`, `DRIVE_NOT_CONNECTED`,
   `DRIVE_ACCOUNT_UNKNOWN`).
3. `release_expired_leases`, then `claim_due_mirror_work` with a fresh token.
4. Each claimed item is processed with no transaction open:
   - Skip the item if its lease is too close to expiry.
   - If its bound key differs from the active key → `pending` / `DRIVE_ACCOUNT_UNAVAILABLE`.
   - Resolve the owner by `storage_object_id`: exactly one `requisicao_arquivos` or
     `admin_arquivos` row. A retired object → `pending` / `OBJECT_RETIRED`.
   - Compute the placement. Request placement runs inside a short `write_transaction`,
     because the turma snapshot may freeze there.
   - Read the canonical bytes with a bound and verify size and SHA-256 (`verify_object`).
   - Run the Drive find-operation-then-upload. Verify the result's size, SHA-256 and parent.
   - Commit with `complete_synced` under the fence.
5. `record_worker_finished`.

The fence makes a stale worker's commit fail with `MIRROR_LEASE_LOST`; the Drive side
stays idempotent through `sgaaOperation`. A Drive auth/connection failure during the
pass returns the item and every remaining claimed item to `pending` /
`DRIVE_AUTH_UNAVAILABLE`, and the pass stops.

Convergence (`converge(conn, *, apply, limit, tables)`), per eligible row:
1. Read the source bytes. Google rows download through the active Drive. Local rows
   are read under the configured roots with `resolve_student_document_path`, with a
   bound of 16 MiB + 1 byte.
2. Validate: non-empty, ≤ 16 MiB, `detect_supported_mime` ∈ PDF/PNG/JPEG, and equal to
   the recorded size, SHA-256 and MIME where recorded.
3. In dry run, stop here and report the outcome class.
4. Upload to the deterministic key with no upsert. `STORAGE_ALREADY_EXISTS` is adopted
   only after `verify_object` matches. Otherwise the outcome is `TARGET_CONFLICT`.
5. Read back and verify the object.
6. Link in one `write_transaction`: lock the business row (`app.db.lock_*`) and re-check
   eligibility with unchanged custody. INSERT a `storage_objects` row with the
   migrated origin, `content_verified_at = now`, uploader from the row (Google) or NULL
   (local). UPDATE the row's `storage_object_id`. A Google row whose download came
   from an account with a logical key is linked already `synced` to its verified
   legacy Drive file (D10).

Each row commits on its own. A rerun skips converged rows and adopts its own
interrupted uploads.

Lock order: the business row, then `storage_objects` (INSERT/UPDATE), then nothing
else. This is the same row-first order as S3-B. Concurrent runtime paths re-check
under their own row lock or conditional UPDATE (§5).

Error model: fixed `[A-Z0-9_]` codes only (`custody_common.sanitize_error_code`). The
CLI prints counts, codes and, only with `--show-ids`, integer ids. It never prints
names, filenames, locators, URLs or provider text.

## 4. Decisions

- D1 — One operator CLI, `python -m app.storage.cli`, with the subcommands `mirror-run`,
  `mirror-requeue`, `census`, `verify` and `converge`. It follows the
  `app.backup.sync` precedent. Rejected: Flask CLI hooks in `create_app`, and threads
  in the web process (both breach the hook isolation and hosting model). The
  scheduler trigger belongs to MP-2.
- D2 — Mirror placement reuses the existing conventions exactly (§2). The Drive file
  name is the basename of the business row's `filename`. The operation key is the
  row's `operation_key`; failing that, `sgaa-object-` plus the first 40 hex digits of
  SHA-256(`bucket/key`). Kind is `comprovante` (semantic `sgaaRequest`,
  `sgaaAttachment`) or `arquivo` (semantic `sgaaArquivo`). No new Drive convention.
- D3 — Retry policy:
  - Backoff is 60 s doubling per attempt, capped at 6 h.
  - At most 10 claims; after that a retryable failure becomes `reconciliation_required`
    / `MIRROR_RETRY_EXHAUSTED`.
  - Unsafe outcomes go straight to `reconciliation_required`: Drive conflict, integrity
    mismatch, invalid placement, missing owner, canonical object missing or divergent.
  - Drive unavailability never counts and never claims.
  - `mirror-requeue` resets attempts.
- D4 — Account binding:
  - An unbound object binds to the active connection's logical key.
  - A bound object waits as `pending` while its account is not the active one.
  - Re-mirroring an already bound object into another account is not offered (it
    needs a trigger change, so it is deferred).
- D5 — The mirror only adds; it never deletes or trashes anything, canonical or Drive.
  Retirement does not propagate to Drive. Only active objects are mirrored: an object
  retired before its first sync keeps its canonical bytes and gets no Drive copy.
- D6 — Linking model:
  - Convergence attaches `storage_object_id` and keeps `provider` and the legacy locator
    as provenance and residue.
  - Runtime rule: a row with `storage_object_id` is canonical custody, whatever its
    provider.
  - Rejected: converting rows to `provider='supabase'`. Local rows lack the uploader and
    operation metadata v15 requires, and fabricating it is refused.
- D7 — Deterministic keys are `legacy/comprovantes/<row id>` and
  `legacy/arquivos/<row id>`. If different bytes already sit at the key, the outcome is
  `TARGET_CONFLICT` (fail closed), never a new key.
- D8 — A source that is unsupported, too large, empty or divergent is skipped with a
  class code and reported. MP-1 does not widen the v14 content domain.
- D9 — Converged-row removal:
  - Request comprovante removal retires the object and deletes the row. A legacy status
    cannot be `trashed` without Drive-trash bookkeeping.
  - Request delete retires the objects of all rows it re-reads inside its transaction.
  - ARQUIVOS delete is the existing canonical delete.
  - ARQUIVOS replace of a converged row retires the old object and converts the row
    with `prior_provider` / `prior_locator`, the S3-B convention.
  - Legacy bytes of converged rows are never trashed or unlinked; purge is MP-4.
- D10 — A converged Google row adopts its verified legacy Drive file as the object's
  synced mirror. The binding is to the active account that served the bytes, with
  `drive_parent_id = remote_parent_id`. Without a logical key the mirror stays
  `pending`, and the worker later adopts the file through `sgaaOperation`.
- D11 — The cross-check reports, by class:
  - database reference invariants;
  - canonical existence and size (`--deep`: SHA-256 read);
  - a bucket listing for unreferenced objects (`intent_unconsumed` / `unknown`);
  - optionally (`--drive`), metadata of synced mirrors for objects bound to the active
    account, with `--requeue-missing-mirrors` as the recovery action;
  - a `reference_digest`: SHA-256 over sorted `table|row|object|sha` lines, for
    comparison across environments.
- D12 — Path-B treats converged rows as canonical metadata. A converged `local_legacy`
  request row is no longer an unsupported local reference, and a converged ARQUIVOS row
  plans no local asset.
- D13 — New row locks are `app.db` helpers. `arquivo_documents._lock_row` moves onto
  `lock_admin_arquivo` (§8 consolidation). No new engine branch outside `app.db`.
- D14 — Concurrent runtime vs convergence:
  - Legacy removal and request-delete statements become conditional on
    `storage_object_id IS NULL`.
  - Request delete re-reads attachments inside its transaction.
  - The legacy ARQUIVOS deletion transition performs the canonical delete when the row
    converged meanwhile.
  - ARQUIVOS replace is already protected by the custody fingerprint.
  - An upload left unlinked by a lost race is an unreferenced bucket object (D11), never
    a database inconsistency.
- D15 — No Google E-LIVE in MP-1. No DEV Google environment exists, and the production
  Google account holds real data. The mirror reuses production-exercised adapter
  methods; the new `describe_file` (`files.get`) is fake-tested only. This is a residual
  risk for MP-3's first supervised live mirror run.

Open decisions (product or architecture): none.

## 5. Phase invariants

- I1 DRIVE_AVAILABILITY_MUST_NOT_BLOCK_REQUEST_SUBMISSION and
  DRIVE_AVAILABILITY_MUST_NOT_BLOCK_ADMIN_ARQUIVOS_CANONICAL_OPERATION remain active.
  They now also cover converged rows (read, remove, delete, replace), proven with
  Google tripwires.
- I2 No MP-1 code path deletes, overwrites or upserts a canonical object, trashes or
  deletes a Drive file, or unlinks a legacy local file belonging to a converged row.
  Proven with recording tripwires on `delete`, `trash` and `os.remove`.
- I3 No web route, view or request hook imports `drive_mirror`, `legacy_convergence`,
  `storage_audit` or `cli` (structural guard with a negative control).
- I4 A converged row's object has exactly the verified size and SHA-256 of its source.
  A rerun changes nothing.
- I5 No CLI output, log line or error contains a secret, URL, locator, filename,
  person name or provider text.

## 6. Scope

- Allowed:
  - `app/storage/` (the modules in §3);
  - `app/comprovantes.py` (removal/delete partition, D9/D14);
  - `app/arquivos.py` (deletion transition, D14);
  - `app/db.py` (two lock helpers);
  - `app/pg_migrate_from_sqlite.py` (the two local-reference predicates, D12);
  - `docs/ENGINEERING_STANDARDS.md` §2 (owner facts);
  - `PROJECT_STATE.md`, `docs/specs/`;
  - `tests/` (new MP-1 modules and support; `tests/canonical_store_fake.py` gains
    `list_objects`; existing guards updated only where §3/§4 declare a change).
- Protected: routes, endpoints, RBAC and CSRF inventories; schema v15 (SQLite and
  PostgreSQL); `main.py`; the signed-TUS contract; Layer-2 (`tools/pg_backup.py`);
  every legacy Google read/write path for unconverged rows.
- Planned local refactors (§8): `_lock_row` → `app.db.lock_admin_arquivo`; extracting
  the in-transaction body of `delete_canonical_arquivo` for reuse by D14;
  `_retire_canonical_objects` keyed on `storage_object_id`.
- Out of scope:
  - MP-2: scheduler/hosting trigger, serverless runtime;
  - MP-3: PROD configuration, real census, real convergence, Path-B real cutover;
  - MP-4: purge of legacy bytes, retired objects or bucket orphans;
  - deferred: cross-account re-mirroring (D4), and widening the content domain for
    unsupported legacy files (D8).

## 7. Data & schema

- No schema version change; v15 is unchanged on both engines.
- Data writes are limited to `storage_objects` rows (existing origins and states) and
  `storage_object_id` on legacy rows, a legal v14/v15 shape.
- Path-B: the D12 predicate change gets real-PG nodes. Layer-2 is unaffected, since
  the metadata is already archived in full.
- Convergence is dry-run by default. It is idempotent, by deterministic key plus link
  re-check. It is resumable, with per-row commits and adoption of its own uploads. It
  verifies byte equality before upload, after upload and on adoption.
- Real data: none in MP-1. Fixtures are synthetic; the canonical `database.db` is
  never opened.

## 8. Security & RBAC

- No new or changed route, endpoint, RBAC mapping or CSRF surface.
- The CLI runs as the machine operator, with the server credentials from the
  environment.
- The secret key is used only through the existing adapter (`apikey`, never printed).
- Failures are fail-closed: unknown owner or state → `reconciliation_required`;
  ambiguous account → no claim; a differing target → `TARGET_CONFLICT`; changed custody
  → no link.
- Personal data stays where it already lives: Drive folder display names follow the
  existing convention. It never reaches outputs, logs, fixtures or reports.

## 9. Compatibility / rollout

- Unconverged legacy rows keep their legacy paths unchanged.
- Converged rows switch to canonical semantics atomically at link.
- Rollback before MP-3: unconverged data is unaffected. A converged link could be
  undone by clearing `storage_object_id` (legacy residue intact), but no tool is
  provided, because nothing real is converged in MP-1.
- The worker and convergence are opt-in operator commands. Nothing runs automatically.

## 10. External boundaries / environment permissions

- Supabase DEV `sgaa-dev` (`pkwtgqsiulzeqkqlsdou`) only:
  - create one private bucket per run, `sgaa-mp1-<run hex>`;
  - upload, list, read, sign and delete objects in it;
  - delete the bucket afterwards;
  - run a leak audit.
- Credential: the existing DEV rehearsal secret, kept outside the repository and never
  printed.
- PROD: none. Google: none live (D15). Local: disposable PostgreSQL databases
  (`sgaa_mp1_test_<run>_*`) on the persistent PG15 cluster, and pytest tmp
  directories.

## 11. Evidence plan

- Every slice:
  - T0;
  - T1/T2 for the new owners (SQLite, fakes);
  - T3 = importers and tests of every changed module (`grep` over `tests/`, `tools/`);
  - T4 = route inventory, CSRF inventory, RBAC coverage, C4 hook isolation, connection
    ownership, `test_pg_readiness_unit4_transactions.py`, residual-main guards,
    message-catalogue ledger, plus the I3 guard.
- E-PG1, all slices: every new SQL path runs on real PostgreSQL 15.
- E-PG2:
  - slice 1: concurrent workers (no double sync), stale-worker fence, requeue vs claim;
  - slice 3: converge × converge, converge × comprovante removal, converge × request
    delete, converge × ARQUIVOS delete.
- E-LIVE (DEV):
  - slice 2: adapter probe of `list_objects` paging and recursion, server `upload`
    no-upsert / duplicate (`STORAGE_ALREADY_EXISTS`), bounded read;
  - slice 3: an end-to-end rehearsal. Disposable PG v15 with synthetic legacy rows
    (local files plus a fake Drive), a real DEV bucket. Census → dry run → apply with
    an injected interruption → resume → idempotent rerun. Mirror worker with real
    canonical reads and fake Drive. `verify --deep` with listing, including a planted
    unreferenced object. Leak audit and full cleanup.
- Mutation controls:
  - the fence check removed;
  - the link re-check removed;
  - the adoption verification removed;
  - the canonical-first partition reverted;
  - the I3 guard's negative control.
- Full suite: none expected (no §5.1 trigger; T3 is bounded). Re-decided at close
  under the TEP.
- Review: an R2 independent fresh-context review before each slice lands, and a
  targeted recheck after fixes.

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | S4 mirror worker, recovery transitions, CLI `mirror-run` / `mirror-requeue` | `mirror_outbox`, `drive_mirror`, `cli`, ES §2, tests | T1–T4 green; E-PG1/E-PG2; I1–I3, I5 for the worker; R2 review | done |
| 2 | Census and cross-check, `list_objects`, `describe_file`, mirror recovery, CLI `census` / `verify` | `storage_audit`, `supabase_store`, `google_drive`, `cli`, fake, tests | T1–T4; E-PG1; E-LIVE adapter probe; R2 review | done |
| 3 | Convergence, canonical-first runtime for converged rows, Path-B predicate, lock helpers, CLI `converge`; closure | `legacy_convergence`, `comprovantes`, `arquivos`, `arquivo_documents`, `app/db.py`, Path-B, `cli`, tests, governance | T1–T4; E-PG1/E-PG2; Path-B real-PG; E-LIVE rehearsal; R2 review; SPEC closure, PROJECT_STATE | done |

## 13. Acceptance criteria

- AC1 — The worker mirrors active canonical request and ARQUIVOS objects into the
  existing hierarchy with verified size, SHA-256 and parent. It is idempotent on
  rerun and under crash/replay. Evidence: slice 1 tests.
- AC2 — The retry, backoff, exhaustion, disconnected-account, wrong-account, lease
  expiry, stale-worker and requeue semantics hold on SQLite and real PostgreSQL, and
  concurrent workers never double-sync. Evidence: slice 1 E-PG2.
- AC3 — No mirror outcome deletes or alters a canonical object (I2). Evidence:
  tripwire tests.
- AC4 — The census and cross-check classify every seeded discrepancy class correctly
  and print nothing personal (I5). Listing and upload are proven live on DEV.
  Evidence: slice 2 tests and E-LIVE.
- AC5 — Convergence passes the dry-run, apply, interruption/resume, idempotent-rerun,
  conflict, unsupported-source and custody-race vectors on both engines, and the
  rehearsal is green on DEV with cleanup. Evidence: slice 3 tests, E-PG2, E-LIVE.
- AC6 — Converged rows are canonical in read, remove, delete and replace, with zero
  Google calls (I1). Path-B accepts converged rows. Evidence: slice 3 tests and
  Path-B real-PG.
- AC7 — The `ENGINEERING_STANDARDS.md` self-audit (§13) passes.

## 14. Phase-specific hard stops

- Any evidence that MP-1 code mutated or deleted legacy bytes, or a canonical object
  it did not create in the same run (H4).
- Any DEV action on a bucket or object the run did not create (H3).

## 15. Deferred / known non-blockers

- Cross-account re-mirroring (D4).
- The legacy-content domain for unsupported legacy types (D8). MP-3 measures it with
  the census.
- Google live proof of `describe_file` and of a live mirror pass (D15).
- Purge of unreferenced bucket objects and of retired objects (MP-4).
- `converged` stays false while terminal legacy rows exist (trashed, failed, in
  reconciliation). This fails closed; MP-3 decides how to classify or remediate
  them before cutover.
- The eligibility rule is a state rule. A locator outside the legal alphabet is
  classified when convergence reads the row, so an eligible count is an upper bound.
- A retired object whose Drive copy is missing cannot be requeued, because the
  worker never starts a copy of a retired object (D5). `verify --drive` therefore
  exits 4 for it permanently. This fails closed; MP-3/MP-4 decide whether retired
  objects need an archive copy.
- A converged row removed or deleted at runtime leaves its legacy bytes
  (Drive file or local file) untracked once the row is gone. Purge policy is MP-4.
- Pre-existing request-flow hardening, outside this phase's scope:
  - manual commit control in `remove_comprovantes` (known debt, ES §12);
  - the canonical-removal message says the comprovantes were kept even when a
    canonical part already committed;
  - a canonical attach committed while a request delete waits on the `requisicoes`
    row is cascade-deleted, leaving its object active and unowned;
  - canonical removal writes rows in submission order while request delete locks
    them in id order, so a PostgreSQL deadlock is possible.
  The cross-check detects the unowned object (`ACTIVE_OBJECT_UNOWNED`).
- A local comprovante removal refused as `CUSTODY_CHANGED` (it converged
  meanwhile) is not flagged retryable, unlike the Google path. The user retries
  from the page.

## 16. Amendments

- A1 2026-10-09 — D3 clarified. "Drive unavailability" means the OAuth credential or
  the active account. A transport failure (timeout, reset) is transient and counts
  toward the retry budget. Two further cases also hand the object back to `pending`
  uncounted: a lease too close to expiry (`LEASE_SAFETY_MARGIN`, due at once) and an
  active account that changed during the pass (`DRIVE_ACCOUNT_CHANGED`, the pass
  stops, nothing is bound). Source: the R2 review. Not material.
- A2 2026-10-09 — D5 clarified. An object retired while its copy is being written
  keeps the copy and is recorded `synced`, because the record states what Drive
  holds. No new copy of a retired object is ever started. Not material.
- A3 2026-10-09 — Shared owners consolidated (§8):
  - `object_store.read_verified` returns verified bytes; `verify_object` now uses it.
  - `custody_common.is_drive_id` replaces the Drive-id pattern copied in
    `arquivo_documents`.
  Behaviour is preserved. Not material.
- A4 2026-10-09 — The D11 verdict is refined after the slice-2 R2 review:
  - `mirrors_verified` is True only when every synced mirror was verified intact,
    False on any failed check, and None when some mirror belongs to another account.
  - A database-only `mirror_complete` reports whether there is a mirror backlog.
  - `verify` exits 4 unless converged with a clean bucket; with `--drive` it also
    needs `mirrors_verified` True and `mirror_complete`.
  - A missing or divergent mirror is not trusted after the active account changed.
  - The provider -> origin rule now lives in `legacy_convergence` (one owner).
  - The listing reads each folder to an empty page and bounds its requests.
  Not material.
- A5 2026-10-09 — Slice-3 implementation details:
  - A third lock helper, `app.db.lock_request_attachments`, lets a request deletion
    lock and re-read its comprovantes, so a comprovante converged concurrently is
    retired instead of left as an unowned active object.
  - When a concurrent run of the tool linked the same row to the same key, the
    outcome is `ALREADY_CONVERGED`, which counts as success.
  - `arquivo_documents.is_replaceable` accepts a converged legacy row from the same
    steady state as an unconverged one.
  - `converge` exits 0 when every processed row converged, 3 when it is not
    runnable, and 4 otherwise.
  Not material.
- A6 2026-10-09 — Slice-3 R2 review fixes:
  - **M1 (material, fixed):** a Google row's Drive file is adopted as the synced
    mirror only while the account that served the bytes is still the active
    connection (`drive_mirror.still_active`); otherwise the mirror stays `pending`.
  - A row cursor (`after_id`, the report's `last_row_id`, one table at a time)
    stops rows that keep failing from stalling a run. These integer row ids are
    the one exception to "ids only with `--show-ids`"; they are not personal data.
  - Candidate rows are read in a short transaction.
  - An unreadable local file is a row outcome (`SOURCE_UNREADABLE`), not a fatal
    error.
  - `mirror_outbox.retire_if_active` is the one retire-if-active rule, and
    `comprovantes.request_document_roots` the one local-roots rule for the tools.
  Within the declared contract.

## 17. Closure

Closed 2026-10-09. Three slices, each fast-forward published to the development
branch (subjects; Git holds the SHAs):

1. `feat: add the Drive mirror worker for canonical storage (MP-1 S4)`
2. `feat: add the storage census and convergence cross-check (MP-1)`
3. `feat: converge legacy documents into canonical storage (MP-1 S5)`

Acceptance (evidence pointers; reports are outside the repository):

- AC1 met. See `tests/test_storage_mp1_drive_mirror.py` (conventions, adoption,
  idempotency, crash-after-write resume) and the real-PG IDLE-at-provider node.
- AC2 met. See `tests/test_storage_mp1_mirror_real_pg.py`: concurrent workers,
  the stale-worker fence, requeue × claim, crash resume, exhaustion and requeue on
  PostgreSQL.
- AC3 met. Recording tripwires (`BaseException`) on canonical upload/delete and on
  Drive trash/delete, with a negative control.
- AC4 met. See `tests/test_storage_mp1_audit*.py` and
  `tests/test_storage_mp1_adapters.py`, plus the E-LIVE DEV adapter probe (listing
  paging, recursion and bound; server upload; duplicate refusal; bounded read).
- AC5 met. See `tests/test_storage_mp1_convergence*.py` (SQLite, plus real-PG
  E-PG1/E-PG2 with proven lock waits) and the E-LIVE DEV rehearsal: dry run, an
  interrupted apply, resume by adoption, an idempotent rerun, real canonical reads
  by the mirror worker (re-run on the final, A6-fixed code), a 7 MiB object read back byte-exact, `verify --deep` with
  a planted unreferenced object detected, legacy bytes untouched, leak audit
  clean, and a run-owned bucket and database removed.
- AC6 met. See `tests/test_storage_mp1_converged_runtime.py` (Google tripwires
  armed) and the Path-B converged nodes in `tests/test_pg_migrate_from_sqlite.py`
  (real PostgreSQL).
- AC7 met. Self-audit in the phase report.

Reviews: an independent fresh-context R2 review of every slice, plus a targeted
recheck after fixes. Slice 1 had 3 MATERIAL findings, slice 2 had 2 and slice 3
had 1; all were fixed before landing.

Residuals carried to `PROJECT_STATE.md`:

- no live Google proof (D15);
- terminal legacy rows and unsupported legacy content need an MP-3 decision;
- no real census or convergence has been run yet (MP-3);
- purge of legacy bytes, retired objects and bucket orphans (MP-4).
