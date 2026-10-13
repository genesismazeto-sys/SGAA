# SPEC MP-3 A20 — Automated hosted backup execution

Status: FROZEN 2026-10-13 — **submitted for confirmation; substantive implementation waits for it.**
Charter (user decision, 2026-10-13, verbatim): "Database and storage backups must execute
automatically according to the frequencies configured in the SGAA administration interface, without
recurring manual intervention." Follow-up decisions of the same day: the cloud-native scheduler is the
preferred direction; actual restoration drills stay the authoritative test-restoration requirement and a
snapshot-integrity verification may exist only as a separate, clearly identified check that is never
reported as a drill; R3 process; no Windows scheduling; no paid infrastructure.
Risk tier: R3 (hosted recovery posture, production deploy gate). Continues the A19 line; standalone
contract for the A20 amendment.

Reconciliation of record: repository at `5663f58`; the cutover is post-PONR — C13 recorded
(2026-10-12), production reopened via GF1 (user reconciliation, 2026-10-13). `PROJECT_STATE.md` and the
README index still describe the pre-C13 pause; their reconciliation is scheduled at this phase's close
and is not part of the implemented behaviour.

## 1. Outcome

After confirmation and the gated deploy, without any operator workstation or manual action:

- The administrator's database cadence (1–24 h) executes: a verified snapshot reaches every connected
  drive and appears on the Banco de dados page as a generation.
- The object cadence (1–7 d) executes: a sealed, deduplicated, restorable object set rides with the
  snapshot taken at that frequency (one coherent recovery point).
- Retention (2–30) applies automatically per kind and per drive, deleting only files this installation's
  own intact receipts name.
- Failures are visible (endpoint codes, page LATE/next-due); protection never stops silently.
- Copies live in the user-controlled drive accounts — off-platform relative to Vercel/Supabase — and the
  operator's encrypted set pipeline is untouched.
- The governed C12–C14 obligations and the ledger are unchanged; drills remain the only evidence that
  counts as a test restoration.

## 2. Current facts (verified; file:line)

- Scheduler front deployed and bearer-gated: `app/storage/scheduler.py:143` (404 disabled / 401 / 405),
  `app/hosting.py:140` (`cron_secret`), descriptor `vercel.json:14-22` (service, `maxDuration` 300) and
  `:38-43` (daily mirror cron); proven live at C11 (MP-3 evidence section).
- Manual hosted snapshot flow exists and is production-proven (the PONR restore used one, MP-3 A19 (13)):
  `app/views/admin/banco_dados.py` `_send_postgres_snapshot` / `_prune_owned_snapshots`; the copy is
  proven table-by-table in `app/backup/pg_snapshot.py:97` (`create`); uploader
  `app/cloud_connections.upload_backup_zip`; receipts `app/backup/pg_posture.py` (`run_record`/`publish`);
  the page reads `pg_posture.read`/`summarize`.
- Policy owner: `app/backup/pg_posture.py:54` (`POLICY_FIELDS`), `read_policy`, `read`.
- Object-set owner: `app/storage/object_backup.py:326` (`backup`), `:550` (`verify_set`), sealed
  manifest, bounds (`MAX_OBJECTS`, `MAX_MANIFEST_BYTES`, disk-space pre-check); CLI in
  `app/storage/cli.py` (`backup-objects`, `verify-backup`, `restore-objects`).
- "Complete" is defined by the frozen table-data policy: `app/pg_migrate_from_sqlite.py:128`
  (`SOURCE_TABLE_POLICIES`; `configuracoes_backup` and OAuth tables are target-side recreated; ephemeral
  classes omitted per runbook D2). Images live in the database; object bytes live in the canonical store
  and travel in the object set.
- No backup automation exists today: runbook §R "the operator starts each run"; the SQLite Windows task
  is not installed and the workstation runtime is frozen. The Vercel cron runs the Drive mirror only.
- Evidence the platform already holds what a hosted run needs: its own database connection, the storage
  service key and the drive tokens (the mirror uses the same); **no new secret is required** (P6 and
  HOSTED_RUNTIME §12 untouched).
- Free-plan wake facts: Vercel Hobby cron is at most daily (MP-3 line 142); Supabase Cron (pg_cron) runs
  any interval from seconds to a year and can make HTTP requests (Supabase docs, Cron guide) — the MP-3
  A3 design already names it the free external trigger (bearer in Supabase Vault).

## 3. Target design

**Compatibility matrix — the six required demonstrations**

| # | Requirement | Mechanism | Evidence lane (later slices) | Residual / boundary |
|---|---|---|---|---|
| 1 | Complete, restorable DB and object backups, independent off-platform copies | Snapshot carries every `MIGRATE_EXACT` table (registers, images, `storage_objects` rows), proven table-by-table at creation; the sealed object set carries every object's bytes (dedup by SHA-256); both go to every connected drive (user-owned accounts, independent of Vercel/Supabase); restore = hosted "Recuperar" or Path-B for the DB, unzip → `verify-backup` → `restore-objects` for the bytes | real-PG lanes: snapshot → Path-B fingerprint equality; set zip round-trip → verify → restore into scratch; served lane shows the generation | Target-side classes (settings, OAuth, schema metadata, ephemeral) are kept/recreated by the installation by policy, not carried in the snapshot; provider accounts are user-managed |
| 2 | Configured cadences incl. sub-daily on free plans | The endpoint is cadence-agnostic: every wake reads the policy and no-ops unless due (DB vs `pg_database_cadence_hours`; objects vs `pg_object_cadence_days`); wakes come from the descriptor cron (daily floor, zero cost) plus Supabase Cron + pg_net (free; bearer in Vault; user-enabled) for sub-daily | due/no-op/allow sequences with a simulated clock; the trigger firing proven on the platform lane before it is relied upon | Exact wake interval is deliberately not contract (any wake ≤ cadence suffices) |
| 3 | Hosting limits, concurrency, idempotency, failure recovery | Runs inside the existing scheduler function (`maxDuration` 300, scratch `/tmp`); object set pre-checks (object count, manifest size, free space) refuse loudly; `pg_try_advisory_lock` held for the pass (shared with the manual route); receipts insert `ON CONFLICT DO NOTHING`; uploads never replace; unique identity+token names; no receipt until snapshot and set verify; a killed run retries next wake; orphaned drive files stay inert (never claimed or pruned) | overflow refusal; duplicate-wake no-duplicate lane; busy-lock lane; killed-run recovery lane | Object sets beyond the function envelope fail visibly; batching deferred (§15) |
| 4 | Security and credential boundaries | New path on the existing bearer-authenticated scheduler front: no session, no CSRF, fail-closed 404/401/405; no secret read or written; value-free bodies and logs; backups contain personal data and travel only to the user's drives over the existing TLS clients; P6/§12 custody untouched | extended auth-negative and leak-audit lanes; guard test: no new secret, no web route/RBAC/CSRF inventory change | none |
| 5 | C13–C14 governed obligations and ledger invariants | The hosted layer writes only `sgaa_ops` receipts (as the manual button does) and never `sgaa_cutover` or a business table; it claims no ledger provenance and no C14 cadence satisfaction — through C14 the operator governed cadence remains the obligation; after C14 (where the ledger records no generation) it is the product's primary protection | guard lane: no cutover/business writes; ledger lanes unaffected; C14 gate tests unchanged | After C14 the operator pipeline remains the recovery asset of record (D6) |
| 6 | Zero recurring cost, independence from operator workstations | Only already-deployed services and free-plan features (Vercel Hobby + Supabase Free + the user's drives); no Windows scheduling; no paid plan or third-party service; fully hosted | descriptor diff + hosting checks; no operator step in the automatic path | The user's one-time enablement of the Supabase Cron trigger (a PROD change, gated) |

**Owners and flow**

- S1 — owner extraction: new `app/backup/hosted_backup.py` owns `send_snapshot(...)` and
  `prune_owned(...)` (behaviour-preserving move of the view's `_send_postgres_snapshot` /
  `_prune_owned_snapshots`); the view delegates; `pg_snapshot` keeps the format, `object_backup` keeps
  the set contract.
- S2 — scheduler job: `hosted_backup.run_backup_pass()`; the scheduler front gains
  `GET|POST /internal/scheduler/backup` (thin dispatch, same auth posture as the mirror). Due-ness from
  one posture read (identity-filtered, intact receipts only). Actions: objects due → fresh DB snapshot +
  sealed object set in one receipt; DB due only → snapshot; neither → 200 no-op. Invalid/unreadable
  policy → 503 `POLICY_INVALID`, nothing runs or is deleted.
- S3 — object set: built by `object_backup.backup()` in scratch (owner of the builder:
  `app.backup.object_sets`, a background module the scheduler service injects — amendment A1),
  archived as its own zip kind in the snapshot folder naming pattern (installation identity + random
  token), uploaded with the snapshot, recorded in the receipt's additive `object_files` map,
  downloadable from the same row, pruned per kind to the policy keeping only receipt-named files.
- Failure model: fixed codes only (`OK`, `NOT_DUE`, `POLICY_INVALID`, `NO_DRIVE`, `SKIPPED_BUSY`,
  `SET_REFUSED_*`, `SNAPSHOT_*`, `JOB_FAILED`); a refusal never reverts a completed generation; the page
  already renders LATE/next-due from the receipts.

## 4. Decisions

- D1 — execute on the existing scheduler front (rejected: operator-PC task — excluded by directive and
  P6-incompatible; a new hosted service — unnecessary; paid schedulers).
- D2 — when objects are due, one combined receipt (fresh snapshot + set): one coherent recovery point,
  no new receipt kind, no read-side status change (rejected: object-only receipts).
- D3 — `pg_try_advisory_lock` shared by the scheduled and manual paths (rejected: a lease table —
  schema; no lock — duplicate runs and prune races).
- D4 — wake ladder: descriptor cron floor + Supabase Cron/pg_net sub-daily; the endpoint is
  cadence-agnostic (rejected: sub-daily Vercel cron — impossible on Hobby; third-party cron — new infra
  and bearer custody).
- D5 — restoration drills stay authoritative: only real drill receipts drive "Restauração de teste". A
  snapshot-integrity verification may be added later, clearly labelled, never feeding that status.
- D6 — additive posture: the hosted layer does not claim ledger provenance, C14 cadence or the
  operator's encrypted off-platform copy; the operator pipeline is unchanged and remains the recovery
  asset of record.

Open decisions: none.

## 5. Phase invariants

- The pass never deletes a file not named by an intact receipt of THIS database; never keeps fewer than
  `max(policy, 1)`; never touches operator roots, the ledger or the baseline.
- No receipt is published for a run whose snapshot or set did not verify; a refusal never undoes a
  completed generation.
- Manual snapshot, download and restore routes, and every operator tool, keep their behaviour; the only
  addition on the manual path is the shared busy lock (a clear message, nothing lost).
- No new secret anywhere; no schema change; no web route, RBAC or CSRF inventory change.

## 6. Scope

- Allowed: `app/backup/hosted_backup.py` (new), `app/backup/pg_posture.py` (additive `object_files`
  field), `app/backup/pg_snapshot.py` (prune/naming reuse), `app/storage/scheduler.py`,
  `app/views/admin/banco_dados.py` (delegation + shared lock + download kind), `vercel.json` (cron
  entry), tests, runbook §R/§B, `PROJECT_STATE.md`/README reconciliation at close.
- Protected: `tools/*` semantics (ops_backup, pg_backup, cutover_ledger), `app/storage/object_backup.py`
  semantics, the cutover records, RBAC inventories, schema and business tables.
- Planned local refactor: the S1 extraction (ENGINEERING_STANDARDS §8).
- Out of scope: drill automation; alerting mail; mirror policy; batching; Windows scheduling; paid
  infrastructure.

## 7. Data & schema

No schema change. Receipts are control-schema rows (`sgaa_ops`); `object_files` is additive and ignored
by existing readers. Policy keys unchanged. No business-fingerprint impact.

## 8. Security & RBAC

Not a web route: no session, no CSRF, no RBAC mapping. Bearer `CRON_SECRET` (constant-time, fail-closed:
404 when the front is disabled, 401 wrong bearer, 405 other methods). No secret is read or written by the
job; it uses only the platform's environment, as the mirror does. Backups hold personal data and go only
to the user's connected drives over the existing TLS clients; receipts and logs stay value-free (digests,
counts, fixed codes, times).

## 9. Compatibility / rollout

The descriptor change ships with the scheduler service; an older deployment has no endpoint (404 on the
front) and the manual path still works. Rollback = redeploy the previous commit; no data is lost and the
manual button remains. The manual path keeps working throughout.

## 10. External boundaries / environment permissions

- DEV/local (no gates): local PostgreSQL 17 and scripted drive/upload doubles; no provider writes.
- PROD, each explicitly user-authorized: (1) one deploy under its own GF1 (`deploy_audit`); (2) the
  user's enablement of the Supabase Cron trigger (bearer in Vault; a documented PROD database change);
  (3) observation of the first automatic occurrence on the page.
- Run-owned resources only; cleanup after each lane.

## 11. Evidence plan

Per slice: T1/T2 contract and owner lanes; T3 impact set; real-PG lane for the pass (due/no-op/rotation/
refusals/duplicate wake/killed run); served-application lane calling the real scheduler WSGI front with a
simulated waker (the page shows automatic generations with zero manual-route calls); restoration lanes
(snapshot → Path-B equality; set zip → unzip → `verify-backup` → `restore-objects`); negative/mutation
controls for every refusal. Full suite at S4 (TEP §5.1: hosted runtime and scheduler contract). Review:
before the production slice, a same-family independent review (R2-style) plus the user-run blind
cross-family R3 review from a packet the executor prepares; the deploy waits for both and its GF1.

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | Owner extraction, behaviour-preserving | `app/backup/hosted_backup.py`, view delegation, tests | owner + behaviour tests green | DONE |
| 2 | Endpoint, due-ness, lock, snapshot path | `app/storage/scheduler.py`, `hosted_backup.py`, `pg_posture.py`, tests | unit + real-PG + served lanes | DONE |
| 3 | Sealed object set, archive, download, prune | `hosted_backup.py`, `object_sets.py`, `pg_snapshot.py`, view download, tests | zip round-trip + restore lane | DONE |
| 4 | Wake wiring, docs, full suite, review | `vercel.json`, runbook, HOSTED_RUNTIME, review packet | full suite (baseline-clean) + review verdict | IN PROGRESS |
| 5 | GATED production deploy + observation | deployment + user enablement + page | first automatic generation observed; report | BLOCKED (gates) |

## 13. Acceptance criteria

- AC1 — a wake with nothing due returns 200 with a no-op code and writes nothing.
- AC2 — with the cadence due, one wake produces a verified snapshot on every connected drive, uploads
  the registers, publishes the receipt, and the served page shows it with no manual-route call.
- AC3 — the object cadence produces the sealed set; its zip round-trips to `verify-backup` and
  `restore-objects`; the page shows object coverage.
- AC4 — retention keeps the newest `pg_retention_generations` per kind per drive and never deletes a
  file not named by an intact receipt (foreign/same-named files untouched).
- AC5 — invalid policy, no drive, envelope overflow, duplicate wake and busy lock each answer a fixed
  code, deleting nothing and publishing nothing.
- AC6 — the manual route, download, restore and every operator tool keep their verified behaviour.
- AC7 — no new secret, no schema change, no web route/RBAC/CSRF change; C13–C14 guard lanes unchanged.
- AC8 — `docs/ENGINEERING_STANDARDS.md` self-audit passes.

## 14. Phase-specific hard stops

- Any need to store, move or read a new secret, or to touch the operator credential custody.
- Any deletion not provably receipt-named, or below the policy.
- Any hosted write to `sgaa_cutover`, the ledger or a business table; any attempt to record ledger
  entries or claim drill evidence.

## 15. Deferred / known non-blockers

- Snapshot-integrity verification as a separate labelled check (D5) — may be added after confirmation.
- Failure alerting by e-mail through the existing mail transport.
- Batching for object sets beyond the function envelope.
- Policy-driven mirror cadence; PROJECT_STATE/README reconciliation at close.

## 16. Amendments

- A1 2026-10-13 — The object-set builder is its own background module.  Implementation found the
  I3 guard (`tests/test_storage_mp1_web_isolation.py`) correctly forbids the web-runtime module
  ``hosted_backup`` from naming ``app.storage.object_backup`` even in a function body.  The builder
  therefore lives in ``app.backup.object_sets`` (a background capability, added to the guard's
  background set), and the scheduler service injects it into
  ``hosted_backup.run_backup_pass(build_objects=…)``; without the injection a due object set refuses
  loudly (``SET_BUILDER_UNAVAILABLE``).  No contract change: the web function still never loads a
  background tool, and the manual route never builds object sets.  A guard list was *extended* for a
  genuinely background module (its designed mechanism), not weakened; the scanner's negative controls
  are untouched.

## 17. Closure

Pending: filled in the last slice (acceptance results, slice commits, residuals to `PROJECT_STATE.md`).
