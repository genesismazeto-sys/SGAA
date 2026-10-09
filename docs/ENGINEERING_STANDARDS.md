# SGAA — Engineering Standards

**Version:** 1.0 — 2026-10-09 (adopted by MP-0).
**Authority:** binding owner of permanent structural and code-health rules.
Every SPEC's acceptance includes compliance with this document. Rules marked
*guarded* are enforced by the tests in §11; reviewers and the executor's
self-audit (§13) enforce the rest. A change that creates or moves an owner
updates §2 in the same slice. Process lives in `docs/OPERATING_MODEL.md`;
testing policy in `docs/TEST_EXECUTION_POLICY.md`.

## 1. The core rule

**"KEEP SCOPE BOUNDED" NEVER MEANS "PILE MORE CODE INTO A BAD OWNER."** When
appending a change would make an owner worse, a proportional local refactor
(§8) is required, not optional. Debt the phase does not touch stays untouched.

## 2. Canonical owners

| Responsibility | Owner |
|---|---|
| App factory, configuration, extensions, hook registration | `app/__init__.py::create_app` |
| Request authorization gate, template context, error handlers | `app/web/authz_gate.py`, `app/web/context.py`, `app/web/errors.py` |
| Admin routes | one module per cohort in `app/views/admin/`, declared as `LegacyRouteSpec` and registered by `register_legacy_blueprint` (`app/views/admin/__init__.py`) |
| Connections, transactions, lock helpers, database-error classification | `app/db.py` (`get_db_connection`, `write_transaction`, `lock_*`, `classify_database_error`) |
| SQL that differs between SQLite and PostgreSQL | `app/sql_dialect.py` |
| SQLite schema and migrations | `app/prod1_schema.py` + `app/prod1_<topic>_ddl.py` / `app/prod1_<topic>_vNN.py` |
| PostgreSQL schema | `app/pg_schema.py` |
| SQLite → PostgreSQL cutover; PostgreSQL logical backup | `app/pg_migrate_from_sqlite.py`; `tools/pg_backup.py` (operator tool, never imported by `app/`) |
| SQLite file backup | `app/backup/` (`capability.py` decides whether it applies) |
| RBAC requirements | `app/auth.py` (`get_admin_permission_requirement`, `classify_governed_admin_request`) |
| User-facing messages | `utils/messages.py` (`flash`, `resolve_user_message`, `_iter_backend_files`) |
| Storage | `app/storage/`, one module per concern: `contracts` (error hierarchy), `custody_common` (shared custody primitives), `upload_intents`, `mirror_outbox`, `object_store`, `supabase_store`, `google_drive`, `google_connection`, `request_documents`, `arquivo_documents`, `drive_mirror` (Drive mirror worker), `legacy_convergence` (legacy eligibility and convergence), `storage_audit` (census and convergence cross-check), `cli` (operator command line, `python -m app.storage.cli`; never imported by the web runtime) |

Domain modules elsewhere in `app/` state their single responsibility in their
module docstring.

## 3. Dependency direction

- Views → domain owners → `app.db` / `app.sql_dialect` / provider adapters.
  A lower layer never imports a view.
- Nothing in `app/`, `services/` or `utils/` imports `main` (*guarded*).
  `main.py` is a frozen compatibility facade: no new symbols, routes or hooks;
  code only leaves it.
- A view module never imports another view module's helpers; shared logic
  moves to a domain owner (*guarded* for the UT-7 case).
- Import from the canonical owner, not through a facade or re-export.

## 4. HTTP layer

- Views parse input, authorize, call the owner, then flash, redirect or
  render. Business rules, rule-bearing SQL and state machines live in owners.
- Routes are registered by `create_app` or through `LegacyRouteSpec`; never in
  `main.py`.
- Endpoint names and URLs are stable contracts. `app/auth.py` resolves RBAC by
  endpoint string, including prefix rules (for example `admin_acesso*`), so a
  new endpoint name must not fall under a prefix rule by accident.
- Every governed admin route and method resolves to exactly one RBAC
  requirement or approved exemption; an unknown scope denies (*guarded*).
- Mutating routes are CSRF-protected (*guarded* inventory).
- Request hooks perform no durable write to the database, filesystem or a
  provider (*guarded*, Plateau C4).

## 5. Data, transactions and schema

- An atomic business mutation runs inside `app.db.write_transaction` and takes
  locks through the `app.db` lock helpers in the order the owner declares. New
  business code does not call `.commit()` directly.
- `BEGIN IMMEDIATE` appears only where the transaction guard allows
  (*guarded*).
- Engine-specific SQL lives only in `app.sql_dialect` or the schema owners;
  no new `database_engine(...) == "postgres"` branches elsewhere. Values are
  always bound parameters.
- A schema change is declared by a SPEC. A new version is a DDL module plus a
  migration module; SQLite and PostgreSQL change in the same slice with parity
  tests; the migration registry is updated (*guarded*); the Path-B migration
  policy and the Layer-2 backup policy state how the new data is migrated and
  backed up.
- Real data is never copied into fixtures, test artifacts or commits.

## 6. Errors, security and messages

- Fail closed: an unknown scope, a missing mapping or an invalid state denies
  or raises; it never grants silently. New code adds no fail-open path.
- Storage and provider errors carry fixed codes and fixed messages
  (`app/storage/contracts.py`, `custody_common.sanitize_error_code`), never
  raw provider text.
- No swallowed exceptions. A deliberate best-effort path says why in a comment
  and logs.
- Secrets never appear in reprs, logs, error messages, stored URLs or commits;
  server-only keys never reach the browser.
- Provider adapters load configuration lazily, bound reads, set timeouts and
  do not follow redirects (reference: `app/storage/supabase_store.py`).
- User-facing text goes through `utils.messages`. A module with user text is
  listed by `_iter_backend_files()`, and catalogue changes are named in
  `tests/canonical_baseline_support.py::CATALOG_LEDGER` (*guarded*).

## 7. Module shape

- One responsibility per module, stated in its docstring.
- No generic dumping grounds: no new `utils`, `helpers`, `common` or
  `services` modules. The existing `services/` and `app/services/` are legacy
  and do not grow.
- No wrapper or abstraction without a second real consumer or a named boundary
  (provider adapter, transaction primitive, compatibility facade an existing
  caller requires). No speculative abstraction for future phases.
- A duplicated business rule or constant is a defect: reuse the owner.
- A new responsibility never goes into a module that already mixes
  responsibilities (for example `app/views/admin/banco_dados.py`,
  `app/views/admin/atividades.py`, `app/views/aluno.py`); it goes into a
  cohesive owner the view calls. Size is a review trigger — a function over
  ~80 lines, a module over ~800 lines with mixed sections — not a gate.
- Carried structural rules: no `app/db/` package (tests open `app/db.py` by
  path); nothing added to `app/admin_access.py` (*guarded*: exactly five
  definitions); before creating a module, search `tests/` and `tools/` for
  literal path references to it; compatibility facades stay while tests
  reference them.

## 8. Local refactor rule

A refactor needs no escalation when all four hold:

1. **Where** — code the slice modifies, or its direct owner or callers (one
   hop), inside the SPEC's subsystem.
2. **Why** — it lets the change land in a coherent owner: extract a rule from a
   mixed view, consolidate a duplicate the change would otherwise copy, move a
   touched function onto `write_transaction`, delete dead code the change
   orphans.
3. **Behaviour-preserving** — proven by existing or new tests.
4. **Proportional** — a minority of the slice (guide: ≤~30 % of its diff or
   ≤~300 changed lines). Anything larger becomes a declared slice by amendment
   or is deferred.

When these conditions hold and appending would worsen the owner, the refactor
is required. Not allowed: repository-wide sweeps, cross-subsystem moves,
endpoint or URL renames, speculative frameworks, retiring guards. Debt in
untouched code is recorded, not fixed.

## 9. Tests

- Tests exercise public behaviour (routes, owner functions, CLIs) and the
  failure modes that matter: refusals, rollback, concurrency, provider errors.
- Tests discriminate: each would fail on the defect it targets. A guard that
  could pass falsely has a negative control or mutation probe.
- Structural guards assert invariants, not incidental counts or exact
  allowlists; exact-count pins caused most of the UT-10…UT-17 test churn.
- Locking and isolation claims need real-PostgreSQL evidence (TEP §4).
- Default tests fake provider boundaries; real providers appear only in the
  E-LIVE lane (TEP §4).

## 10. Comments and landing hygiene

- Comments and docstrings explain non-obvious *why*, contracts and invariants
  — not what the next line does. No phase or ticket narration in production
  code; history belongs in Git.
- A landing commit contains no temporary harness, debug output, commented-out
  code, dead code orphaned by the change, or TODO without an owner.

## 11. Permanent guards

| Guard | Enforces |
|---|---|
| `tests/test_ut16_residual_main_ownership.py`; the `green_7` guards in `tests/test_ut1[0-5]_*.py` | no `import main` from `app/`, `services/`, `utils/`; `main` owns no hooks or routes beyond its allowlist |
| `tests/test_db_connection_ownership.py` | `app.db` is the only connection owner |
| `tests/test_route_inventory_snapshot.py` | route inventory vs `tests/_artifacts/route_inventory_baseline.json` |
| `tests/test_rbac_requirement_coverage.py` | every governed admin route is mapped |
| `tests/test_ref_0c_d_r1_route_complete_actor_matrix.py`, `tests/test_ut_br2d_rbac_boundary_governance.py` | actor × route authorization decisions |
| `tests/test_ut_br2abc_canonical_baseline_governance.py` | canonical baselines still discriminate |
| `tests/test_csrf_inventory_audit.py` | CSRF inventory of mutating routes |
| `tests/test_plateau_c4_request_hook_write_isolation.py` | request hooks write nothing durable |
| `tests/test_fc13_obsolete_authority_cleanup.py` | only allowlisted callers resolve activity versions |
| `tests/test_phase3_schema_startup_transaction_contract.py` | single `init_db` owner; migration registry |
| `tests/test_pg_readiness_unit4_transactions.py` | `BEGIN IMMEDIATE` placement; `write_transaction` adoption |
| `tests/test_pg_readiness_unit5a_schema.py`, `tests/test_pg_readiness_unit5b_runtime_dialect.py` | SQLite / PostgreSQL schema parity; dialect surface |
| `tests/test_ut_schema_presets_ddl_authority.py` | single DDL authority |
| `tests/test_phase4_*_shared_owners.py`, `tests/test_ut7_helpers_activity_catalog_owner.py`, `tests/test_backup_settings_ownership.py` | one owner per shared helper |
| `tests/canonical_baseline_support.py::CATALOG_LEDGER` | message-catalogue deltas are named |

A guard's expected data changes only when a SPEC's declared contract change
makes it false, with negative controls proving it still discriminates.
Weakening or retiring a guard otherwise is hard stop H9.

## 12. Known debt — do not add to it; fix only when §8 requires

- Partial `write_transaction` adoption: direct `.commit()` remains in
  `app/arquivos.py`, `app/comprovantes.py`, `app/views/admin/banco_dados.py`,
  `app/views/admin/alunos_turmas_cursos.py` and others.
- Engine branches outside `app.sql_dialect` (`app/db_maintenance.py`, several
  `app/storage/` modules, `app/views/admin/atividades.py`).
- Local `_utc_now` / `_utc_now_iso` copies beside
  `custody_common.utc_now_text`.
- Storage-domain user messages are outside the `_iter_backend_files()` scanner.
- `main.py` residue: real wrappers (`admin_required`, `aluno_required`), the
  unused `proximo_numero_turma`, a duplicate log handler.
- `app/web/authz_gate.py` admits a governed admin request whose RBAC
  configuration is missing when `IS_PRODUCTION` is set (shadow audit only).
  This is a deliberate historical decision, mitigated by the RBAC-coverage
  guard; it is re-decided in the pre-go-live security review, not changed
  opportunistically.

## 13. Self-audit checklist (answered in every phase report)

1. Each new or changed responsibility has exactly one owner; no duplicated rule
   or constant.
2. Views stay thin.
3. Imports come from canonical owners; no `main` import; nothing new in
   `main.py`; no reverse or cross-view dependency.
4. Engine-specific SQL only in the dialect or schema owners.
5. Atomic mutations use `write_transaction` with declared lock order.
6. Routes: one RBAC requirement, CSRF, fail-closed; user text through
   `utils.messages`.
7. Errors are coded and useful; nothing swallowed; secrets clean.
8. No dumping ground, needless wrapper or speculative abstraction.
9. Nothing piled into a mixed module; §8 applied where it was required.
10. Tests discriminate and cover failure modes; guards changed only per a
    declared contract, with negative controls.
11. Comments explain why; no temporary, debug or dead code.
12. Schema changes: SQLite/PostgreSQL parity and Path-B / Layer-2 policies
    handled, or not applicable.

Any "no" carries a reason in the report.
