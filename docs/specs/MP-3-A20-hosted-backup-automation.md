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
| 2 | Configured cadences incl. sub-daily on free plans | The endpoint is cadence-agnostic and deadline-driven (M4/A4): every wake records itself, learns the interval to the next expected wake from the just-elapsed time between wakes (daily floor when unknown, clamped, sub-minute = duplicate), and runs when the deadline would otherwise fall before that next wake — so a generation whose phase sits later than the wake (a manual at 07:00 vs a 04:47 cron) runs at that same wake, the 47 h gap stays impossible, and sub-daily cadences run on cadence (never per wake, never past it); wakes come from the descriptor cron (daily floor, zero cost) plus Supabase Cron + pg_net (free; bearer in Vault; user-enabled) for sub-daily | due/no-op/allow sequences with a simulated clock, the reviewer's manual→wake sequence as a discriminating real-PG lane, the interval-learning and duplicate lanes; the trigger firing proven on the platform lane before it is relied upon | The wake interval itself is not contract; the observed interval is a record, not a setting |
| 3 | Hosting limits, concurrency, idempotency, failure recovery | Runs inside the existing scheduler function (`maxDuration` 300, scratch `/tmp`); object set pre-checks (object count, manifest size, free space) refuse loudly; a lock ROW with a lease in `sgaa_ops.backup_lock` (M2/A3) — taken and released in transactions committed on their own (visible through the transaction pooler and past any ambient request transaction), expired leases stolen, holder-checked release, never a false-busy state — shared by the pass, the manual button and the restore; control DDL retries once against concurrent-first-use catalog races; receipts insert `ON CONFLICT DO NOTHING`; uploads never replace; unique identity+token names; every receipt records its completeness and only complete wakes advance the clock (M1/A3); a killed run retries next wake; partial receipts own their files so retention bounds every drive | overflow refusal; duplicate-wake no-duplicate lane; busy-lock lane; lease-steal, holder-safe release and cross-backend visibility lanes; partial-delivery/retry and mixed-history lanes; killed-run recovery lane | Object sets beyond the function envelope fail visibly; batching deferred (§15) |
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
  one posture read (identity-filtered, intact receipts only) against a strictly read policy (M3) and a
  **deadline rule** (M4/A4): the wake records itself and learns the interval to the next expected wake
  from the just-elapsed time between wakes (the platform's daily floor when unknown, clamped to
  [1 min, 7 days], a sub-minute elapsed being a duplicate delivery), and runs when the deadline would
  otherwise fall before that next wake (`age ≥ cadence − interval + 1 min`). Actions: objects due →
  fresh DB snapshot + sealed object set in one receipt; DB due only → snapshot; neither → 200 no-op.
  Unreadable/invalid policy → 503 (`POLICY_UNREADABLE` / `POLICY_INVALID`), nothing runs or is deleted.
- S3 — object set: built by `object_backup.backup()` in scratch (owner of the builder:
  `app.backup.object_sets`, a background module the scheduler service injects — amendment A1),
  archived as its own zip kind in the snapshot folder naming pattern (installation identity + random
  token), uploaded with the snapshot, recorded in the receipt's additive `object_files` map,
  downloadable from the same row, pruned per kind to the policy keeping only receipt-named files.
- Failure model: fixed codes only (`OK`, `NOT_DUE`, `POLICY_INVALID`, `POLICY_UNREADABLE`, `NO_DRIVE`,
  `SKIPPED_BUSY`, `SET_*`, `DELIVERY_INCOMPLETE`, `SNAPSHOT_*`, `JOB_FAILED`); a refusal never reverts a
  completed generation; the page already renders LATE/next-due from the receipts.  A due object set
  that cannot be built stops the pass before any upload or receipt.  Every receipt records its own
  completeness (A3): the scheduled pass answers `DELIVERY_INCOMPLETE` when any connected drive is
  missing any required artifact of the wake, the receipt is still recorded with `complete=false` (so
  retention owns the files that did land) — and the protection clock, the due dates and the page's
  status read only complete receipts, so a partial delivery never looks like protection and the same
  work stays due for the next wake.  A workspace beyond the function envelope therefore needs the
  deferred batching (§15), never partial claims.

## 4. Decisions

- D1 — execute on the existing scheduler front (rejected: operator-PC task — excluded by directive and
  P6-incompatible; a new hosted service — unnecessary; paid schedulers).
- D2 — when objects are due, one combined receipt (fresh snapshot + set): one coherent recovery point,
  no new receipt kind, no read-side status change (rejected: object-only receipts).
- D3 — a lock ROW with a lease in `sgaa_ops.backup_lock` shared by the scheduled pass, the manual
  button and the restore (M2): the production runtime uses the transaction pooler, where a
  session-level advisory lock is not valid (a later statement may run on another backend); the row is
  taken and released atomically in transactions committed on their own (the request paths may hold an
  ambient transaction from the auth hooks — a savepoint lease would be invisible while the run
  proceeds) and an expired lease is stolen, so a killed run can never leave a persistent false-busy
  state (rejected: `pg_try_advisory_lock` — pooler-unsafe; no lock — duplicate runs and prune races).
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
- A receipt is only recorded for a run whose snapshot (and set, when due) verified; every receipt
  carries its completeness, and only complete receipts advance the protection clock, the due dates
  or the page's status (M1/A3); a refusal never undoes a completed generation.
- The schedule runs on the deadline rule (M4/A4): a wake runs when the deadline would otherwise fall
  before the next expected wake; the observed wake interval is a record, never a setting.
- Manual snapshot, download and restore routes, and every operator tool, keep their behaviour; the only
  addition on the manual paths is the shared busy lock (a clear message, nothing lost).
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
| 4 | Wake wiring, docs, full suite, review | `vercel.json`, runbook, HOSTED_RUNTIME, review packet | full suite (baseline-clean) + review verdict | DONE |
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

- A run killed mid-upload (platform timeout) can leave at most one wake's files per drive with no
  receipt: they are inert, never claimed and never pruned — deleting them would need an ownership
  proof the accepted M4 contract does not allow.  Bounded by interruption frequency, not by drive
  health (a failing drive's files ARE receipt-owned and rotate).
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
- A2 2026-10-14 — The independent R3 review of `e4d3cd4` returned FAIL with four material findings;
  this amendment is their remediation, accepted as contract: **M1** the scheduled contract is
  all-or-nothing per wake — no receipt (and therefore no advanced protection clock, no "current"
  status) until every connected drive received the snapshot, the registers and, when due, the sealed
  set; a partial delivery answers `DELIVERY_INCOMPLETE`, leaves the work due and retries next wake,
  while the manual route keeps its A19 partial semantics.  **M2** mutual exclusion is a lock row with
  a lease in `sgaa_ops.backup_lock` (taken/released atomically in short transactions, expired leases
  stolen, holder-checked release), valid through the transaction pooler; the pass, the manual button
  and the restore share it, and a killed run can never leave a persistent false-busy state.  **M3**
  the scheduled decision reads the administrator's policy strictly: an unreadable policy answers
  `POLICY_UNREADABLE` and a partial or invalid one `POLICY_INVALID`; the defaults are used only when
  the policy is provably unset (empty table).  **M4** the due test runs on the deadline rule (A4):
  each wake is recorded and learns the interval to the next expected wake (the platform's daily floor
  when unknown, clamped to 1 minute–7 days; a sub-minute elapsed is a duplicate delivery), and the
  pass runs when the deadline would otherwise fall before that next wake
  (`age ≥ cadence − interval + 1 min`) — so a generation whose phase sits later than the wake (a
  manual at 07:00 against a 04:47 cron) runs at that same wake, the reported ~47 h gap stays
  impossible, and sub-daily cadences still never run on every wake.  Focused evidence replaces a new
  full suite (TEP; the previous T5 baseline is qualified): the A20 suite (58 nodes incl. the M1
  partial-delivery/retry lane, the M2 lock/lease lanes, the M3 partial-policy lane and the M4
  deadline/47 h-gap lanes on real PostgreSQL) plus the
  368-node focused regression set are green on the remediated candidate.
- A3 2026-10-14 — The second independent R3 review returned FAIL with four material counterexamples
  against the integrated contracts; this amendment is their consolidated remediation (A2's
  all-or-nothing publication is superseded by the completeness marker below — the receipt is
  recorded, not hidden).  (1) Mixed manual/scheduled histories: every receipt now records its
  completeness (``complete``, computed on both the manual and the scheduled path); the protection
  clock, the due dates, the statuses and the schedule count only complete receipts, while partial
  receipts are recorded, shown with a "parcial" marker and own their files.  A partial manual run
  therefore never satisfies the scheduled cadence, and a partial scheduled wake stays due.  (2)
  Genuine transaction boundaries: the lock acquire and release are committed on their own around the
  protected operation — the request paths may hold an ambient transaction from the auth hooks, and a
  savepoint lease is invisible to every other backend while the run proceeds (reproduced live on
  PostgreSQL).  (3) Concurrent first use: the control DDL (schema, lock table, restore-marker table)
  runs through ``pg_posture.run_ddl``, which retries once when two processes race the catalog on
  first use.  (4) Scheduling jitter: the due window is min(10% of the cadence, 90 min) — at 24 h the
  threshold stays 22.5 h (the reported 47 h gap remains impossible) while a 1 h policy runs at
  ~54–60 min, never at 45.  *(Superseded by A4: the static window still skipped a day for a
  generation whose phase sits later than the wake; the deadline rule replaces it.)*  Related failure paths closed in the same pass: a folder-setting read
  failure is a partial delivery, not a 500; retention rotates complete generations and partial runs
  separately (a failing drive can neither push the newest complete generation out of its window nor
  grow the healthy drive without bound); the lease is pinned above the platform's function limit.
  Evidence: the A20 suite (64 nodes, including the cross-backend lock-visibility, the manual-partial
  mixed-history, the partial-retention split and the DDL-race lanes on real PostgreSQL) and the
  432-node focused regression set, green on the remediated candidate.
- A4 2026-10-14 — Pre-R3 material clarification: the static due window was a scheduling-contract
  flaw, reproduced on `692cedd` (Day1 06:00 scheduled, Day1 07:00 complete manual, Day2 04:47 wake:
  NOT_DUE at 21 h 47 min, next wake Day3 04:47 → a 45 h 47 min protection gap).  The window is
  replaced by deadline scheduling: each wake records itself in `sgaa_ops.backup_schedule` and learns
  the interval to the next expected wake from the just-elapsed time between wakes (the platform's
  documented daily floor when unknown; clamped to [1 min, 7 days]; a sub-minute elapsed is a
  duplicate delivery and keeps the stored interval), and the pass runs when the deadline would
  otherwise fall before that next wake (`age ≥ cadence − interval + 1 min`; the same minute guards a
  duplicated wake).  Consequences: a generation whose phase sits later than the wake runs at that
  same wake (the reviewer's sequence runs Day2 04:47, gap 21 h 47 min); consecutive daily wakes keep
  running; a 1 h cadence with a 15- or 30-minute waker runs at ~60 min (never past the cadence,
  never per wake); a duplicated delivery never re-runs a fresh generation.  Evidence: the reviewer's
  sequence as a discriminating real-PostgreSQL lane (NOT_DUE on `692cedd`, OK now), the
  interval-learning and duplicate real-PG lanes, the `note_wake` unit lane, and the 435-node focused
  regression set — all green on this candidate.

## 17. Closure

T5 completed on `0d0efc0` (local PostgreSQL 17 lanes on): **6224 passed / 3 failed / 159 skipped /
12 errors** in 67 minutes.  Classification: the three failures are two pre-existing local-cluster
failures (reproduced identically on the entry baseline `8aa45a0`: the `pg_restore` message
classification and the non-pt-BR cluster collation) and the recorded MX3 549-vs-548 debt; the 12
errors were the missing `sgaa_qual` admin database of the disposable cluster — the E-PG2 lane passes
12/12 once the prerequisite exists; no candidate-caused failure.  The recorded debt that did not
manifest this run (xlwt collection errors, `TestSentinelSurvival`, the backup-package test, the
non-hermetic CSRF node) is not claimed green beyond this run's result.  Remaining: the gated
production slice (S5) and the `PROJECT_STATE.md` reconciliation at close.
