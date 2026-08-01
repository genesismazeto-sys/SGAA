# PHASE 4-B2 — Versioning subsystem ownership and compatibility contract

## 1. Status and authority

- **Unit:** PHASE 4-B2 / B2-R3 external supervisor acceptance closeout.
- **Status:** **PHASE 4-B2: CLOSED / ACCEPTED**.
- **Published commit:** `17e468ad938e873e1f9e9c303808ad31b9f3806b` (`Extract versioning subsystem ownership`), parent `2fbe4954106dc8d410f6495ca8bd4b1956b326d2`.
- **Workspace/branch:** `D:\OneDrive\Programação\SGAA_clean_baseline` / `refactor/architecture-safety-net`.
- **Published manifest:** exactly 24 paths: 8 production, 10 tests and 6 governance.
- **Post-publication verification:** COMPLETE.
- **External supervisor acceptance:** RECORDED BY B2-R3.
- **Preserved authority:** PHASE 4-B1 remains CLOSED / ACCEPTED. PHASE 4 remains OPEN / INCREMENTAL IMPLEMENTATION. PHASE 4-B3: NOT AUTHORIZED. Phase 5: NOT AUTHORIZED. Phase 6: NOT AUTHORIZED. Migration v4: PROHIBITED.

## 2. Purpose and bounded production scope

B2 transfers the existing activity-versioning runtime and exactly three diagnostic handlers out of `main.py` while preserving behavior:

| Canonical owner | Responsibility |
|---|---|
| `app/versioning/resolver.py` | resolver, read-only versioning model and diagnostic payload helpers |
| `app/versioning/snapshots.py` | versioned requisition snapshot feature flags, payload and caller-owned write |
| `app/versioning/shadow_reads.py` | shadow-read feature flag, event format, dedicated sink, parsing, filtering, deduplication and log-source discovery |
| `app/views/admin/versioning.py` | exactly three legacy-endpoint diagnostic handlers and their B1 registrar specification |
| `app/versioning/__init__.py` | canonical public compatibility surface for the versioning package |

B2 makes no schema change, no migration, no RBAC policy change and no Atividades, Catálogo, Matrizes or Requisições route-cohort expansion.

## 3. Owner and compatibility identities

`main.py` contains no local defining body for:

1. `resolver_versao_por_aluno`;
2. `maybe_write_versioned_requisicao_snapshot`;
3. `maybe_run_versioned_resolver_shadow_read`;
4. `admin_diagnostico_atividades_versionadas`;
5. `admin_diagnostico_atividades_versionadas_view`;
6. `admin_diagnostico_versioned_shadow_reads`.

`main.py` imports and re-exports the canonical owner objects by identity. The implementation has no wrapper and does not re-register the three routes. `app/versioning/` and `app/views/admin/versioning.py` do not import `main`.

Snapshot writes remain caller-owned: the canonical snapshot owner issues the same bounded `UPDATE` but introduces no `commit`, `rollback`, `BEGIN`, savepoint or migration boundary.

## 4. Aluno reverse-edge contract

`app/views/aluno.py` directly imports:

- `maybe_run_versioned_resolver_shadow_read`;
- `maybe_write_versioned_requisicao_snapshot`.

The lazy `main` map no longer contains either versioning key. It contains exactly these six residual dependencies:

1. `ensure_admin_arquivos_table`;
2. `get_admin_arquivo`;
3. `get_effective_matriz_for_turma`;
4. `get_student_request_update_alert`;
5. `list_active_admin_alertas`;
6. `mark_student_request_updates_seen`.

No seventh or eighth versioning dependency remains.

## 5. Exactly three diagnostic routes

The B1 `LegacyRouteSpec` / `configure_legacy_routes` mechanism is reused. The exact route contract is:

| Rule | Endpoint | Method | RBAC requirement |
|---|---|---|---|
| `/admin/diagnostico/atividades-versionadas` | `admin_diagnostico_atividades_versionadas` | GET | `atividades:view` |
| `/admin/diagnostico/atividades-versionadas/view` | `admin_diagnostico_atividades_versionadas_view` | GET | `atividades:view` |
| `/admin/diagnostico/versioned-shadow-reads` | `admin_diagnostico_versioned_shadow_reads` | GET | `banco_dados:view` |

Global legacy endpoints, `request.endpoint`, `url_for`, methods, query/filter defaults, JSON payload/status behavior and HTML template/context are preserved. Namespaced aliases and duplicate rules are prohibited. `app/auth.py`, templates and route/RBAC snapshots are unchanged.

## 6. Factory wiring

`create_app(register_admin_versioning_blueprint=True)` registers the versioning diagnostic blueprint after the accepted B1 configuration blueprint. The explicit `False` opt-out supports isolated factory tests. Registration uses the collision-safe B1 registrar and fails before partial route mutation on endpoint or rule/method collision.

## 7. Logging compatibility repair

### 7.1 Root defect

The first B2 extraction copied `os.path.dirname(os.path.abspath(__file__))` from `main.py` into `app/versioning/shadow_reads.py`. In `main.py` that expression represented the repository root; after relocation it represented `app/versioning`. That would have changed the default dedicated log and explicit `logs/app.log` fallback.

R1 establishes:

```text
PROJECT_ROOT = Path(__file__).resolve().parents[2]
```

This is independent of the process cwd and of the module's new physical location.

### 7.2 Logger identity

The legacy body evaluated `logging.getLogger(__name__)` while defined in `main.py`; the logical logger was therefore `main`. B2 preserves that identity without importing `main`:

```text
logger = logging.getLogger("main")
```

No new handler is configured, no `RotatingFileHandler` is created and import does not create a directory or file.

### 7.3 Paths and source precedence

When `APP_LOG_DIR` is unset:

- dedicated: `<REPOSITORY_ROOT>/logs/versioned_shadow_reads.log`;
- explicit fallback candidate: `<REPOSITORY_ROOT>/logs/app.log`.

When `APP_LOG_DIR` is set:

- dedicated: `<APP_LOG_DIR>/versioned_shadow_reads.log`.

Current file-backed handlers on logger `main` remain candidate app-log sources. Rotation expansion remains ordered, path-normalized and deduplicated. If the dedicated file exists, `source_mode == "dedicated"` and only it is read. If it is absent, `source_mode == "fallback_app_log"` and the handler-derived plus explicit root app-log candidates are read. Diagnostic `dedicated_path`, `candidate_paths` and `paths_to_read` use the same repaired resolution.

## 8. Explicit logging equivalence tests

The executable B2 contract proves:

- APP_LOG_DIR unset resolves the repository-root dedicated and explicit fallback paths;
- APP_LOG_DIR set resolves the dedicated path under the configured disposable directory and preserves handler-derived app-log behavior;
- `shadow_reads.logger is logging.getLogger("main")`;
- dedicated-present and dedicated-absent precedence/source mode;
- importing `app.versioning.shadow_reads` alone creates no logs directory, file, database, handler or network connection;
- event representation and deduplication identity remain compatible with the B1 baseline contract.

The contract file passed **14/14** after the R1 logging correction.

## 9. Physical-state resumption and recovered failure

R1 resumed the existing unstaged candidate without reset, broad restore or reimplementation. The pre-R1 semantic manifest contained 18 paths: eight production paths, three original-pool test paths and all seven newly authorized mechanically related test paths. `tests/test_activity_versioning_shadow_read.py` was physically modified despite the earlier failed-patch report; the Git diff, not that report, established its state.

The first full-suite attempt is preserved as recovered evidence:

- **949 passed / 2 failed / 17 deselected / 384.10s**;
- failures: stale lazy-main expectations in `tests/test_db_schema_maintenance.py` and `tests/test_residual_shared_helpers.py`;
- canonical database and protected residual unchanged.

Those two already-authorized test expectations were corrected to the canonical owner and six-key lazy-map contract. This was a recoverable test-contract defect, not a physical production failure.

## 10. Final local qualification

- B2 logging contract: **14 passed / 3.05s**.
- Complete affected lane: **241 passed / 106.86s**, zero failures/errors.
- Full hermetic command: `PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -B -m pytest -q --tb=short --durations=25`.
- Full hermetic result: **954 passed / 17 deselected / 343.75s / exit 0**, zero failures/errors.
- Active-node reconciliation: 951 prior active nodes + 3 newly added R1 logging regression nodes = 954.
- Route invariants: routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0; actor matrix 402 = 263 allowed + 139 denied.
- Route snapshot SHA-256: `6e32148cd1988d5e405c9d11bdbda285359f72d5fc7eca8bd5ef8da9b83049fa`, byte-identical before/after qualification.
- No pytest process remained after either final lane.

## 11. Database, residual and artifact safety

- Canonical `database.db`: 544768 bytes; SHA-256 `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`; unchanged.
- `database.db-wal`, `database.db-shm` and `database.db-journal`: absent.
- Protected ignored residual: 17420 bytes; SHA-256 `7388cfbc8f446410ef3c98ec0fa274c2c36ff4f3ef8ed2cd649bb1f3e1d3bb0e`; unchanged, ignored and index-absent.
- Candidate file aggregate and the preexisting runtime-surface aggregate were byte-identical before/after the full gate.
- Test runtimes were disposable and outside the repository; no repository artifact was produced.
- Migration v4 was not created or executed.

## 12. Line-ending reconciliation

Every modified tracked file was compared with the baseline after normalizing CRLF/LF only. Git's semantic diff and the normalized comparison contain the intended owner/test/governance hunks; no path has an EOL-only delta and no whole-file line-ending rewrite is retained. `.gitattributes` is unchanged and no repository-wide formatter or normalization was run. Git's Windows checkout warnings describe the configured future checkout conversion, not staged EOL-only content.

## 13. Exact final actual manifest

The final candidate contains **24 paths**, below the authorized ceiling of 25.

### Production — original pool (8)

1. `app/__init__.py` — factory registration/opt-out for the exact diagnostic blueprint.
2. `app/views/aluno.py` — direct canonical versioning imports and removal of two lazy keys.
3. `app/views/admin/versioning.py` — new canonical owner for exactly three diagnostic handlers/routes.
4. `app/versioning/__init__.py` — package compatibility exports.
5. `app/versioning/resolver.py` — canonical resolver/read-model owner.
6. `app/versioning/shadow_reads.py` — canonical shadow-read owner plus R1 root/logger repair.
7. `app/versioning/snapshots.py` — canonical snapshot owner preserving caller transaction.
8. `main.py` — removal of local bodies/routes and identity-only compatibility imports.

### Tests — original pool, retained only where semantic delta is necessary (3)

9. `tests/test_activity_versioning_shadow_read.py` — monkeypatches canonical shadow owner.
10. `tests/test_activity_versioning_shadow_read_diagnostic.py` — canonical diagnostic/log owner targets.
11. `tests/test_phase4_versioning_subsystem.py` — owner/factory/route/logging/event/import-isolation contract.

`tests/test_activity_versioning_resolver.py` is authorized but omitted because no semantic delta is necessary.

### Tests — R1 expanded pool (7)

12. `tests/conftest.py` — candidate sandbox copies cached and non-ignored untracked files before staging without weakening isolation.
13. `tests/test_pytest_runtime_isolation.py` — proves that expanded candidate-sandbox behavior and sentinel isolation.
14. `tests/test_db_schema_maintenance.py` — exact six-key aluno lazy-map expectation after removal of two versioning entries.
15. `tests/test_residual_shared_helpers.py` — canonical direct-import identity and absence of the two lazy keys.
16. `tests/test_aluno_requisicao_versioned_readonly.py` — canonical monkeypatch/import ownership for versioning helpers.
17. `tests/test_phase4_configuracoes_blueprint.py` — recognizes the authorized admin/versioning module while preserving B1 app-to-main and route invariants.
18. `tests/test_ref_0c_b2_diagnostic_rbac.py` — canonical diagnostic handler ownership with unchanged RBAC policy.

All seven expanded test paths are mechanically necessary and retained. No expanded-pool path is omitted; no test weakens unrelated behavior.

### Governance — original pool (6)

19. `docs/refactor/PHASE4_VERSIONING_SUBSYSTEM_CONTRACT.md` — this canonical contract.
20. `docs/DOCUMENTATION_INDEX.md` — authority/read-order/current-state index.
21. `docs/mapeamento/05_avaliacao_refactor.md` — Phase 4 plan/status.
22. `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` — normalized B2 ledger row.
23. `PROJECT_STATE.md` — current canonical project state.
24. `AGENT_HANDOFF.md` — exact continuation and publication boundary.

No 25th or 26th path is required.

## 14. Accepted technical review and process evidence

The accepted technical review applies to the complete 24-path pre-synchronization diff, SHA-256 `a97275ac9f29cefcfd8ed4d3038ce37f552a886036481be0f7fd1c7f85a373b7` (234297 bytes). Its production/test portion was frozen separately during R2 and remained byte-identical through documentary synchronization.

- FREE attempt: provider `opencode`; model `opencode/deepseek-v4-flash-free`; session `ses_0433de371ffefBa8J03FBmkoV4`; cost 0; exit 0; result **UNUSABLE DELIVERY / NO VERDICT**.
- Fallback classification: `FALLBACK_FREE_UNUSABLE_DELIVERY`.
- Accepted review: provider `opencode-go`; model `opencode-go/deepseek-v4-flash`; session `ses_043375c9affeYmMxqtbpNjNohl`; cost `0.01838004 USD`; exit 0; reviewed diff `a97275ac9f29cefcfd8ed4d3038ce37f552a886036481be0f7fd1c7f85a373b7`; mutation count 0; verdict **PASS**; material findings 0.
- LOW finding: matrix status label. IAsup adjudication: **REJECTED AS NON-MATERIAL / SEMANTIC EQUIVALENCE PROVED**; the baseline and extracted labels and fallback are equivalent.

An external reviewer continuation created `baseline_main.py` outside the repository. The artifact had SHA-256 `2652d1213d7f0b5ac577ebddb528341448e9eb0afb8b41d051e5826a56d4af48` and is classified **EXTERNAL_REVIEW_SCRATCH / OUTSIDE_REPOSITORY / NOT_STAGED / NOT_COMMITTED / SELECTIVELY_REMOVED / NO_CANDIDATE_OR_INDEX_IMPACT**. It must not be recreated.

The final documentary review addendum covered only the synchronized six-document delta and did not repeat the technical review. Route `flash_free`; provider/model `opencode` / `opencode/deepseek-v4-flash-free`; session `ses_0431aa4d7ffev4hTZImBDA86Ca`; cost 0; verdict **PASS**; no fallback.

## 15. Publication and acceptance completion

Publication completed as one normal fast-forward of `refactor/architecture-safety-net`. The accepted technical commit is `17e468ad938e873e1f9e9c303808ad31b9f3806b`, with the exact 24-path manifest and parent stated above. Index-visible qualification passed 271 tests; post-publication qualification passed 282 tests. Final published diff SHA-256: `2a98b4a4ff9747745335259d0e5aad2c18eb9a8c0bc4762c1ea2681bc7571eec`. Published technical diff SHA-256: `76f8089b577f04c7d9f4b2090627c1767ec2f2f4b9b3abcb6e973c1e41959e50`. Technical physical aggregate: `d54bec738de05934906e03c610f513dac18269206fdf3a6de9b0a79d64cd99a3`.

B2 is **CLOSED / ACCEPTED** and has no demonstrated technical residual or open correction. The stale R2 prepublication continuation instructions are historical and superseded by this B2-R3 closeout. PHASE 4 remains **OPEN / INCREMENTAL IMPLEMENTATION**. PHASE 4-B3: NOT AUTHORIZED. Phase 5: NOT AUTHORIZED. Phase 6: NOT AUTHORIZED. Migration v4: PROHIBITED.
