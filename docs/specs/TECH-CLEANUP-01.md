# SPEC TECH-CLEANUP-01 — Bounded technical defects after GF1-CONSOLIDATED

Status: FROZEN 2026-11-21
Charter: "Eliminate bounded, reproducible technical defects remaining after GF1-CONSOLIDATED,
without changing accepted product behavior." Starting HEAD `bd631f9`; Local/DEV and disposable
test data only; commit and push to the development branch; no production deployment.
Risk tier: R2 (charter floor; slice 2 is a concurrency change, the others R1).

## 1. Outcome

- A Turma code holding a NUL byte answers the DIAG-500 404 on PostgreSQL too, never HTTP 500.
- Concurrent uses of the `sgaa_ops` control-schema DDL never fail with
  `tuple concurrently updated`: overlapping scheduler invocations all answer 200.
- Every test recorded as known debt in `PROJECT_STATE.md` passes for a reason that matches
  accepted behaviour, or stays recorded with its cause.
- The stale technical statements found during reconciliation say what the code does.

## 2. Current facts

Reproduced on `bd631f9` (evidence outside the repository, `D:\SGAA_tmp\tc01`, synthetic data):

- F1 — `app/views/admin/versioning.py::_consulta_diagnostica` binds the selected
  `turma_codigo` as text. psycopg refuses a NUL byte in a text parameter, so on PostgreSQL the
  lookup raises before the query and both routes answer 500. SQLite answers 404
  (`PG-NUL-TURMA-CODIGO-404`, recorded by `docs/specs/DIAG-500.md`).
- F2 — `app/backup/pg_posture.py::run_ddl` runs the control-schema DDL (`CREATE … IF NOT
  EXISTS` plus `REVOKE ALL … FROM PUBLIC`) in a transaction and retries once. Every caller runs
  it on each use: `copy_registry.prepare` (first use), `hosted_backup.backup_lock` and
  `note_wake` (every call), `pg_restore`, `pg_posture.publish`. `REVOKE` rewrites the catalog row
  even when nothing changes, so concurrent attempts collide on it. On PostgreSQL 17 with three
  concurrent callers, one fails with `InternalError_` / XX000 `tuple concurrently updated` in
  20 of 20 rounds, both on a fresh database and once the objects exist; with two callers the
  retry absorbs it. This is the recorded intermittent HTTP 500 of
  `tests/test_mp2_scheduler_real_pg.py::test_overlapping_invocations_mirror_each_object_exactly_once`
  (the front logs the class `InternalError`; in isolation the test passes 8 of 8, its timing
  rarely aligns three first uses).
- F3 — the recorded failing tests, each with its cause:

| Test | Cause | Class |
|---|---|---|
| `test_ut5_backup_package.py::test_cli_backup_sync_runs_isolated_with_app_context_only` | fingerprints the gitignored `database.db`; absent in a clean checkout | fixture defect |
| `test_phase4_atividades_blueprint.py::test_activity_blueprint_owns_exact_canonical_surface` | pins 20 routes; `118796c` (v19, in PROD) added the four template routes | stale expectation |
| `test_b11_category_a_tokenization.py` (3 tests) | read `#req-presets-modal …` / `.presets-ph:hover` in `templates/admin_requisicoes.html`; `5b989cd` moved those rules unchanged to `static/css/components/request-presets.css` | stale path |
| `test_ds_pill_radius.py::test_no_stylesheet_restores_a_fully_rounded_pill` | its `ROUND_ALLOWED` entry for `.presets-ph` names the old owner file (same move) | stale path |
| `test_pg_readiness_unit5d_ptbr_portability.py` (2 controls) | the declared later deltas stop at v17; v18 (one CHECK on `requisicao_email_eventos`) and v19 (two tables, one index, two triggers) were never declared | stale declaration |
| `test_pg_readiness_unit5f_untyped_null_query.py::test_production_sql_has_no_placeholder_is_null_predicate` | flags `SELECT to_regclass(?) IS NOT NULL` (`app/storage/copy_registry.py:108`); PostgreSQL 15 and 17 type that placeholder from the function signature even bound to NULL, while `%s IS NULL` and `(%s) IS NULL` raise 42P18 | scanner false positive |
| `test_status_badge_semantics_ui_b02_b03.py::test_b4_shared_tones_are_only_within_one_semantic_category` | defines the caution category as non-notifying; v18 made a return (`Devolvida`) a notifying decision, and `Devolvida` is caution in the accepted UI | stale predicate |
| `test_storage_s2_real_pg.py::test_fresh_v14_authority_validates_and_is_empty`, `test_storage_s3a_real_pg.py::test_pg_authority_is_v15` | pin the head at v16 | stale pin |
| `test_mp2_scheduler_real_pg.py::test_overlapping_invocations_mirror_each_object_exactly_once` | F2 | production defect |

- F4 — stale or contradictory documentation: `docs/ENGINEERING_STANDARDS.md` §2 says
  `app/pg_schema.py` owns "the in-place v16 → v17 upgrade" (it upgrades a frozen v16, v17 or v18
  to v19); `docs/specs/MP-3-A22-request-reclassification.md` and its index row say "PROD gate G1
  pending", while `PROJECT_STATE.md` records G1 executed on 2026-10-19 (ledger seq 173-181).
- F5 — the MP-2 residuals in `PROJECT_STATE.md` (§15) are outside R2 or need a product decision.

## 3. Target design

- **Slice 1, `app/views/admin/versioning.py`.** In the selected Turma-code lookup, a code that
  contains NUL names no Turma: it raises the existing `LookupError(_TURMA_NAO_ENCONTRADA)`
  without querying. PostgreSQL text cannot hold NUL, and no write path stores one (the DIAG-500
  valid-code invariant), so the answer is the 404 SQLite already gives. The reading
  (`_ler_consulta`), the precedence, an unused `turma_codigo` and the page echo (NUL shown as
  U+FFFD, which reads back as the same 404) are unchanged.
- **Slice 2, `app/backup/pg_posture.py::run_ddl`.** Each attempt's transaction first takes one
  transaction-scoped advisory lock (`pg_advisory_xact_lock`, a fixed key owned by `pg_posture`),
  so concurrent callers run the DDL one after another. The waiter's statements see the winner's
  committed objects. The lock ends with the attempt's transaction. The one retry stays for a
  racer that does not take the lock. Callers, DDL texts and their transaction boundaries are
  unchanged. No business lock is taken, so the lock order of the callers is untouched.
- **Slice 3, tests only.** Each F3 test is repaired at its cause (§4 D3).
- **Slice 4, documents.** F4 corrected; `PROJECT_STATE.md` known-debt and residual sections
  rewritten to the present state; this SPEC closed.

## 4. Decisions

- D1 — NUL is refused at the one lookup that binds it, not in `app.db`. A driver-level rule
  would change a wide primitive (TEP §5.1 A) for every route. Other free-text parameters on
  PostgreSQL are recorded (§15), not swept.
- D2 — Serialize, don't retry harder. A retry loop only lowers the odds; the advisory lock
  removes the collision. The lock lives in the DDL helper, the single owner of control-schema
  DDL, so all five callers gain it. `app.db` lock helpers lock business rows on the
  application adapter; this is a PostgreSQL-only control-schema primitive on a raw connection.
- D3 — Test repairs keep or strengthen what each test proves:
  - the activity surface pins its 24 endpoints by name (stronger than a count);
  - the b11 and pill-radius assertions read the stylesheet that owns the rules, with the same
    values and the same allowance reason;
  - the U5-A control declares the v18 and v19 deltas exactly, as v13–v17 did;
  - the untyped-NULL scanner treats a placeholder that is a function call's whole argument as
    typed. Negative controls keep `%s IS NULL`, `(%s) IS NULL` and `AND (%s IS NULL …)`
    flagged, and an opt-in real-PostgreSQL node proves each verdict against PostgreSQL;
  - the caution category is "open: the classification may still be corrected"
    (`RECLASSIFIABLE_REQUEST_STATUSES`), never a grant or a denial, with a negative control;
  - the S2 / S3-A real-PG nodes assert that the authority validates at the owner's head
    (`PG_SCHEMA_VERSION`) and still holds their v14 / v15 rows;
  - the backup CLI isolation test records the canonical file's state (absent or its hash) and
    requires that state unchanged, so a clean checkout also proves the CLI never creates it.
  Each item is a declared contract change of this SPEC. None removes a guard or widens an allowance
  beyond the file move.

Open decisions (product or architecture): none.

## 5. Phase invariants

- No route, endpoint, RBAC mapping, CSRF policy, message, template or stylesheet changes.
- No schema change, no migration, no data change.
- The scheduler and backup routes keep their status codes and bodies for every outcome other
  than the removed collision.

## 6. Scope

- Allowed paths: `app/views/admin/versioning.py`, `app/backup/pg_posture.py`, the tests named in
  §2 and §11, `PROJECT_STATE.md`, `docs/ENGINEERING_STANDARDS.md` §2 (fact), `docs/specs/README.md`,
  the A22 SPEC status line (fact), this SPEC.
- Protected: everything else, notably `app/db.py`, `main.py`, `app/hosting.py`, templates, CSS,
  `tests/conftest.py`, `pytest.ini`, `tests/_artifacts/`.
- Planned local refactors: none.
- Out of scope: F5, every item of §15, visual and DS changes.

## 7. Data & schema

No schema version change; no data touched. The advisory lock is session-side only.

## 8. Security & RBAC

No route or RBAC change. Slice 1 answers a refused input earlier and logs nothing new.
Slice 2 adds no privilege: an advisory lock needs none, and the DDL still revokes `PUBLIC`.

## 9. Compatibility / rollout

Code-only. Nothing is deployed by this phase; production receives it only through a later GF1.
Rollback is reverting the slice commit.

## 10. External boundaries / environment permissions

Local PostgreSQL 15 (`127.0.0.1:54315`) and 17 (`127.0.0.1:54317`) through `SGAA_PG_TEST_URL`,
run-owned databases only. No DEV provider, no PROD access. PROD user gates: none.

## 11. Evidence plan

- Slice 1: T1 SQLite route tests (both routes; selected NUL code 404 with the alert; NUL in an
  unused field still resolves the selected Turma; page echo); E-PG1 new route-smoke node on
  PostgreSQL 15 and 17 (RED on `bd631f9`: 500); T2 the DIAG-500 impact set (diagnostic, resolver,
  DS alert, button contract, diagnostic RBAC, FC13, route inventory, RBAC coverage, CSRF inventory).
- Slice 2 (R2): T1 unit contract of `run_ddl` (the lock opens every attempt; the retry kept);
  E-PG2 new real-PG test with concurrent callers, both on first use and with the objects present
  (RED on `bd631f9`), plus the scheduler overlap test repeated; T2 the A20 module, the copy-registry,
  staging-release, drive-mirror and restore real-PG lanes; T3 the importers of `pg_posture`.
  One independent review in a fresh context before landing; targeted recheck after fixes.
- Slice 3: each repaired test, its negative controls, and the owner module of each guard.
- Slice 4: T0 only.
- Full suite: none expected. No §5.1 trigger applies: slice 2 is a PostgreSQL-only path SQLite
  never executes, slices 1 and 3 are bounded (one view, test-only), and no harness changes.

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | NUL Turma code is a 404 on PostgreSQL | `app/views/admin/versioning.py`, two test files | §11 slice 1 | planned |
| 2 | Control-schema DDL serialized | `app/backup/pg_posture.py`, `tests/test_mp3_a20_hosted_backup_automation.py` | §11 slice 2, R2 review | planned |
| 3 | Known test debt repaired | the F3 test files | §11 slice 3 | planned |
| 4 | Documents and closure | §6 documents | T0 | planned |

## 13. Acceptance criteria

- AC1 — `turma_codigo` with NUL answers 404 on both routes on PostgreSQL 15 and 17 and on SQLite;
  every other DIAG-500 case unchanged → slice 1 evidence.
- AC2 — concurrent `run_ddl` callers all succeed on PostgreSQL; the scheduler overlap test passes
  → slice 2 evidence.
- AC3 — every F3 test passes; each changed guard has a negative control that fails on the defect
  it targets → slice 3 evidence.
- AC4 — F4 statements match the code and the recorded state → T0.
- AC5 — `docs/ENGINEERING_STANDARDS.md` self-audit (§13) passes.

## 14. Phase-specific hard stops

- A repair would need a product, schema or UI change, or the removal of a guard → stop.

## 15. Deferred / known non-blockers

- MP-2 residuals, unchanged:
  - the hosted scratch path is predictable on a shared POSIX temp directory. Changing it is
    hosted security posture (R3); the hosted platform's temp directory is per instance.
  - `main.py` attaches a file handler when its directory is writable. That is application
    bootstrap (TEP §5.1 A) in a frozen facade.
  - a report `descricao` has no length bound. Choosing one is a product decision.
- Free-text query parameters on other PostgreSQL routes are not audited for NUL (D1).
- `DIAG-500-A1-CODE-CONTROL-CHARACTERS` stays as DIAG-500 recorded it.
- `MAX_RAW_COLOURS` and other DS debt (charter exclusion).

## 16. Amendments

None.

## 17. Closure

Filled in slice 4.
