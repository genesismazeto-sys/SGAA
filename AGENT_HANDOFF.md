# Agent Handoff

## Current state — PHASE-0-R9A PYTEST RUNTIME ISOLATION LOCALLY VALIDATED / PENDING EXTERNAL SUPERVISOR REVIEW

- **Task:** R9A — remove the destructive pytest workspace-cleanup gate before Phase-0 smoke execution.
- **Project:** SGAA-EJ; workspace `D:\OneDrive\Programação\SGAA_clean_baseline`; branch `refactor/architecture-safety-net`.
- **Starting HEAD/upstream:** `06786f2a2353894554c982f41e29d35d5d5cadee`; divergence `0/0`; clean worktree/index and zero untracked paths.
- **Commit identity:** subject `Isolate pytest runtime from workspace directories`; this commit contains the technical and documentary closeout. Resolve its final SHA with `git rev-parse HEAD` after commit; do not create a follow-up commit merely to embed its own SHA.
- **Mode/agents:** OpenAI Codex `openai-codex/gpt-5.6-sol` supervised. IAexec implementation used `opencode-go/deepseek-v4-flash` session `ses_06eed9eebffecp7qkYbjPpaSeL` through `FALLBACK_FREE_BUDGET_EXHAUSTED`; two bounded corrections used `opencode-go/deepseek-v4-pro` session `ses_06edc602effeWZ997yHcw9TVwY`. The final two-line correction was applied by IAsup after two executor quality failures. Independent read-only review used a fresh `opencode-go/deepseek-v4-pro` session `ses_06eac821fffejIIeNNMy11xiQY`; verdict `passed=true`, no security concerns or logic errors. Luna review route failed at the provider and was not used as evidence.
- **Root cause:** `tests/conftest.py::_cleanup_root_output_artifacts()` ran at session start/finish, deleted preexisting root `backups/`, `uploads/`, and `documentos_alunos/`, and hid `shutil.rmtree` failures with `ignore_errors=True`. Database, uploads, documents, backups, application logs, the shadow-read log, and pytest cache were not all owned by one session runtime root.
- **Implemented contract:**
  - one unique system-temp `PYTEST_RUNTIME_ROOT` is created before application import;
  - `APP_DATABASE`, `APP_UPLOAD_FOLDER`, `APP_DOCUMENTOS_ALUNOS_FOLDER`, local/cloud backup paths, `APP_LOG_DIR`, and pytest cache are routed under that root;
  - `create_app()` honors non-empty `APP_UPLOAD_FOLDER`/`APP_LOG_DIR`; unset values preserve repository-root production defaults;
  - `main.py` no longer overwrites factory `UPLOAD_FOLDER`, and both application/shadow log paths honor `APP_LOG_DIR`;
  - cleanup rejects symlink roots/markers, requires direct system-temp parent, exact prefix, exact marker filename/content token, removes only the owned root, and surfaces every mandatory teardown failure;
  - canonical root manifests for `database.db`, `uploads`, `documentos_alunos`, `backups`, `logs`, and `.pytest_cache` are checked at session finish.
- **Files read:** `app/__init__.py`, `main.py`, `tests/conftest.py`, `.gitignore`, `pytest.ini`, the four canonical documents, relevant existing backup/application tests, and current Git diff/state.
- **Eight-path authorized manifest:** `app/__init__.py`, `main.py`, `tests/conftest.py`, `tests/test_pytest_runtime_isolation.py`, `AGENT_HANDOFF.md`, `PROJECT_STATE.md`, `docs/DOCUMENTATION_INDEX.md`, `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`.
- **Commands/gates:** AST parse of all four technical files passed; `git diff --check` passed; static scan found no shell injection, `eval`/`exec`, pickle, SQL formatting, or credential leak. Deterministic marker-token strings were reviewed as test data, not secrets.
- **Test evidence:**
  - focused runtime-isolation module: `15 passed in 20.40s`, zero skipped;
  - collection: `649/666 tests collected`, `17 deselected` D73H, `6.76s`;
  - backup/app/backend/requisition regressions: `23 passed in 23.20s`;
  - full hermetic suite: `649 passed, 17 deselected in 441.22s`; no D73H historical execution;
  - independent pre-commit review: PASS, no blocking findings;
  - pre/post byte/hash/mtime manifests and temp-root sets were identical after every accepted gate; `database.db` remained 544,768 bytes at SHA-256 `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`.
- **Forensic temp cleanup:** 22 task-owned leaked roots from failed implementation/correction runs were removed only after exact path, timestamp window, and direct-parent provenance checks. Three older `sgaa_pytest_runtime_*` roots predated this task window and remain untouched due missing provenance.
- **Scope not executed:** none of the five Phase-0 smoke flows was implemented or run; no schema, migration, dependency, UI, route, R20, production hard-enforcement, D73H historical, or database change.
- **Status:** R9A IMPLEMENTED / LOCALLY VALIDATED / PENDING EXTERNAL SUPERVISOR REVIEW. Runtime-directory cleanup debt is locally satisfied but not externally accepted yet.
- **Macro Fase 0 remains PHASE_0_REMAINS_OPEN_WITH_BOUNDED_REMAINDER:** exactly one bounded remainder remains — smoke-flow contract/evidence for admin login, aluno login, create requisicao, process requisicao, and backup.
- **Fase 1 remains unauthorized; production remains shadow-only.**
- **Exact next action after push:** external supervisor review of this R9A commit. Only after acceptance may the five Phase-0 smoke-flow contracts/evidence resume.

## Historical operational handoff — REF-0C-B2-A diagnostic access-policy decision (2026-07-18)

### REF-0C-B2-A — Diagnostic Access Policy and R20 Defense-in-Depth Decision Package (READ-ONLY / DOCUMENTATION-ONLY / LOCALLY COMPLETE / PENDING CHATGPT SUPERVISOR REVIEW)
- Project `SGAA-EJ`; workspace `D:\OneDrive\Programação\SGAA_clean_baseline`; branch `refactor/architecture-safety-net`.
- Starting HEAD `5fb4276` (`Refresh PROJECT_STATE after REF-0C-B1 acceptance`); before this closeout `origin/main...HEAD = 0 11`; `932c6d7` is an ancestor with exactly one commit after it; clean working tree, empty staging, zero untracked files, no push.
- Accepted phase chain: REF-0B `f2b1cfc` → REF-0T `c440297` → REF-0TF `722b7a7` → REF-0TF-A `e111cd5` → REF-0TF-B `9b47c37` → REF-0C-A diagnosis `f977fd6` → REF-0C-A closeout `c8acd07` (CLOSED/ACCEPTED) → REF-0C-B1-P0 `92b25d2` (CLOSED/ACCEPTED) → REF-0C-B1 `932c6d7` (CLOSED/ACCEPTED) → REF-0C-B1 state refresh `5fb4276`.
- Status: **read-only architectural policy analysis and documentation-only closeout — no RBAC implementation.** Deliverable created: `docs/refactor/REF_0C_B2_A_DIAGNOSTIC_ACCESS_POLICY_DECISION.md`.
- Files read completely: `PROJECT_STATE.md` (REF-0 section), `AGENT_HANDOFF.md` (REF-0C section), `docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md`, `docs/refactor/REF_0C_B1_P0_ACCESS_CONTEXT_TRANSACTION_HYGIENE.md`, `app/auth.py`, `tests/_artifacts/rbac_unmapped_routes_baseline.json`, `tests/test_ref_0c_b1_rbac_high_confidence_mappings.py`.
- Files inspected partially: `main.py` — `_load_admin_access_context`/`_get_current_admin_access_context`/`_admin_can`, `_admin_access_denied_response`/`enforce_admin_access_control`/`_is_ajax_request`, the R22/R23/R24 handlers and their data-source + log-source helpers, and R20 `admin_matriz_nova_atividade` with `readonly` computation. Real `database.db` and real production log contents were not accessed.
- Files changed (this closeout only): `docs/refactor/REF_0C_B2_A_DIAGNOSTIC_ACCESS_POLICY_DECISION.md` (new), `PROJECT_STATE.md`, `AGENT_HANDOFF.md`.
- Policy recommendations (NOT implemented):
  - R22 → `atividades`/`view` → {admin_total, administrativo, consultivo} (set A; unchanged vs current). Confidence MEDIUM-HIGH.
  - R23 → `atividades`/`view` → {admin_total, administrativo, consultivo}; must equal R22 (identical data/call-graph). Confidence MEDIUM-HIGH.
  - R24 → `banco_dados`/`view` → {admin_total} only (set C; deliberately revokes administrativo+consultivo; exposes FS paths/env value/exception tracebacks/identifiers → security-sensitive; no UI link). Confidence MEDIUM-HIGH.
  - R20 local `readonly` → keep unchanged this phase (central `matrizes`/`edit` gate already enforces before handler body; `readonly` is inert on this route); later prefer Option C (remove) or D (rename). Not modified.
- Alternatives rejected: `banco_dados`/`view` for R22/R23 (needlessly revokes consultivo/administrativo read of curricular data); `atividades`/`view` for R24 (exposes resolver internals/paths/env broadly); endpoint-specific/role-name logic for any (brittle, invisible to the actor-matrix tests, drift); Option B for R20 (duplicate-authz drift risk).
- Effective actor sets representable by the model: A = all admins (non-restricted resource / `view`); B = admin_total+administrativo (non-restricted / `edit`, or a new `diagnosticos` resource at `view` — clean form needs new vocabulary); C = admin_total only (security-restricted resource). Set D (admin_total+consultivo, administrativo denied) is NOT role-level representable without a per-user override or new vocabulary. New vocabulary (`diagnosticos` resource) is required only if set B is demanded for a diagnostic.
- Repository-vs-documentation note (not a BLOCKED condition): R22/R23 do not read `alunos`/`requisicoes` (the accepted REF-0C-A R22 row over-listed them); no student PII is exposed. Refines an analysis field only; conflicts with no accepted state/decision.
- Unresolved decisions (owned by ChatGPT supervisor + user): D2′ resource for R22/R23; D3′ resource for R24 and whether administrativo needs it (set B → new vocabulary); accept/reject the R24 tightening; D-consistency (R22 must equal R23 — recommended yes); D1′ R20 remove vs rename; and whether/when REF-0C-B2 implementation is authorized.
- Risks: R22-R24 remain granularly unprotected (fail-open to any admin) until a policy is implemented; choosing `banco_dados` for R24 is a conscious behavioral tightening; a new `diagnosticos` resource, if chosen, touches the access-management UI and the RBAC test matrix.
- Prohibitions still in force: no `app/auth.py`/`main.py`/test/baseline/template/JS change; no R22-R24 mapping; no R20 behavior change; no profile-scope change; no new resource; no global fail-closed gate; no schema/DB/dependency change; no modularization; no push.
- Exact next action: ChatGPT supervisor review of the decision package and the user's normative decision; then, only if authorized, REF-0C-B2 implementation. Do not begin REF-0C-B2 implementation, REF-0C-C, UI, schema, database, or modularization work.
- Recommended model/effort for the later implementation phase: Claude Sonnet, medium (mechanical mapping + tests once the policy is chosen); escalate to Opus/High only if the user requires the new `diagnosticos` vocabulary or an endpoint-specific rule.
- No ChatGPT acceptance is claimed for REF-0C-B2-A.

## Current operational handoff — REF-0C-B1 implementation (2026-07-17)

### REF-0C-B1-P0 — Admin access-context transaction hygiene (IMPLEMENTED / LOCALLY VALIDATED / PENDING CHATGPT SUPERVISOR REVIEW)
- Commit: `92b25d2` (`Fix admin access-context transaction hygiene`), directly after accepted `c8acd07`. The REF-0C-B1 mapping work follows in a separate commit and contains no `main.py` transaction patch.
- Exact root cause: authorization-context loading calls `ensure_usuario_access_schema()` on the Flask request's shared SQLite connection. Its `INSERT OR IGNORE` defaults and normalization `UPDATE`s open an implicit write transaction, including on no-op calls. That dangling transaction blocked `PRAGMA foreign_keys` during the affected lazy `atividades` rebuild and could hold a write lock.
- Final ownership mechanism: the helper owns a named savepoint. `RELEASE` persists helper schema/bootstrap work on a clean connection; within an existing outer transaction it releases only the nested savepoint. The caller remains responsible for the outer commit or rollback. The global authorization gate now performs neither operation.
- Focused temporary-database evidence: `5 passed` — clean access context is transaction-neutral, bootstrap state persists, caller-owned work remains uncommitted and rollbackable by its owner, repeated loads are idempotent, a mapped rebuild route completes without lock/FK DDL failure, and mapped allow/deny behavior is unchanged. Contract: `docs/refactor/REF_0C_B1_P0_ACCESS_CONTEXT_TRANSACTION_HYGIENE.md`.
- Status: locally validated, pending ChatGPT supervisor review; no real database, schema design, migration, UI, dependency, or policy change.

### REF-0C-B1 — Strongly Supported RBAC Mappings and Denial Tests (IMPLEMENTED / LOCALLY VALIDATED / PENDING CHATGPT SUPERVISOR REVIEW)
- Project `SGAA-EJ`; workspace `D:\OneDrive\Programação\SGAA_clean_baseline`; branch `refactor/architecture-safety-net`.
- Initial HEAD `c8acd07` (REF-0C-A closeout). Final lineage has exactly two unpushed commits after it: P0 `92b25d2` and the following REF-0C-B1 mapping commit. Expected `origin/main...HEAD = 0 10` after final verification.
- Accepted phase chain: REF-0B `f2b1cfc` → REF-0T `c440297` → REF-0TF `722b7a7` → REF-0TF-A `e111cd5` → REF-0TF-B `9b47c37` → REF-0C-A diagnosis `f977fd6` → REF-0C-A closeout `c8acd07` (CLOSED/ACCEPTED) → REF-0C-B1-P0 → REF-0C-B1 (both pending review).
- Scope executed exactly per the REF-0C-B1 order: the 21 HIGH-confidence route-method policies R1-R21 mapped in `get_admin_permission_requirement`. R20 received the central `matrizes`/`edit` mapping only; its local `readonly` behavior was NOT changed. R22-R24 were NOT mapped.
- Mapping groups: `atividades`/`view` = R1-R4; `atividades`/`edit` = R5-R16; `matrizes`/`view` = R17; `matrizes`/`edit` = R18, R19, R20, R21.
- Prerequisite relationship: REF-0C-B1-P0 corrects transaction ownership at the access-schema helper source. This mapping commit has no `main.py` transaction patch; the global gate neither commits nor rolls back request work.
- Debt baseline `tests/_artifacts/rbac_unmapped_routes_baseline.json` regenerated with the documented `SGAA_UPDATE_RBAC_DEBT_BASELINE=1` command → now exactly R22, R23, R24. Zero change to R22-R24.
- Existing tests fixed under supervisor Option A: `tests/test_admin_matriz_versao_link.py` and `tests/test_admin_activity_version_catalog_version_lifecycle.py` login helpers changed from the non-existent `user_id=999999` to the real bootstrap `admin_total` (`user_id=1`). All existing assertions preserved.
- New tests: `tests/test_ref_0c_b1_rbac_high_confidence_mappings.py` (36 tests): requirement mapping for all 21 routes, R22-R24 remain unmapped, actor matrix (admin_total/administrativo/consultivo), HTTP allow/deny, denial redirect to `admin_dashboard`, anonymous→login, and no-mutation invariants for a denied POST per domain group.
- Full hermetic suite: `562 passed`, `17` D73H deselected, `0` failures/errors/skips/xfails/xpasses (`pytest -q`, 528.92s). This is `+5` selected tests relative to the earlier `557`, exactly the P0-focused tests.
- Files in the RBAC commit: `app/auth.py`, `tests/_artifacts/rbac_unmapped_routes_baseline.json`, `tests/test_admin_matriz_versao_link.py`, `tests/test_admin_activity_version_catalog_version_lifecycle.py`, `tests/test_ref_0c_b1_rbac_high_confidence_mappings.py` (new), and these canonical records. `main.py` is P0-only.
- `user_id=999999` inventory: exactly two affected successful-admin login assignments were changed to bootstrap `admin_total` (`user_id=1`) in `_login_admin` of `tests/test_admin_matriz_versao_link.py` and `tests/test_admin_activity_version_catalog_version_lifecycle.py`. Their two retained mentions are explanatory comments. All other `999999`/`9999999` occurrences in tests are retained negative-authentication or missing-resource inputs.
- Working tree otherwise clean; `tests/_artifacts/csrf_inventory_shadow_{on,off}.json` (previously described as randomized churn; corrected by R6/R7 — churn was deterministic stale snapshots after three deterministic message entries; normal mode is now read-only) reverted and excluded.
- Unresolved decisions still owned by the supervisor: R22-R24 diagnostic access policy (D2/D3/D4); whether to enforce or remove R20's local `readonly` (D1); whether to adopt a fail-closed global gate (REF-0C-C).
- Known risks/debts: R22-R24 remain granularly unprotected admin routes; P0 and B1 remain pending supervisor review.
- Prohibited actions still in force: R22-R24 policy implementation, fail-closed global enforcement, R20 `readonly` change/removal, UI/schema/database/dependency changes, route modularization, and push.
- Exact next action: ChatGPT supervisor review and acceptance of REF-0C-B1-P0 and REF-0C-B1. Do not begin REF-0C-B2 or REF-0C-C without an explicit order.
- Recommended model/effort for the review-driven follow-up: Claude Sonnet, medium; escalate to Opus/High only if the supervisor requires architectural changes to the gate correction.

### REF-0C-A / REF-0C-A-R1 (CLOSED / ACCEPTED)
- REF-0C-A / REF-0C-A-R1 is **CLOSED / ACCEPTED** after ChatGPT supervisor review.
- Accepted diagnosis HEAD: `f977fd6` (`Document normative RBAC policy matrix diagnosis`).
- Branch `refactor/architecture-safety-net`; HEAD `f977fd6`; `origin/main...HEAD = 0 7`; working tree clean.
- Accepted matrix confidence counts: HIGH 21, MEDIUM 3, LOW 0.
- R22-R24 remain unresolved normative diagnostic-policy decisions. No policy has been selected for these routes.
- No RBAC implementation has started.
- Modularization remains prohibited.
- The next authorized technical phase is **REF-0C-B1 — Strongly Supported RBAC Mappings and Denial Tests**.
- REF-0C-B1 is explicitly limited to the 21 HIGH-confidence route-method combinations (R1–R19, R21).
- R22, R23, and R24 are explicitly excluded from implementation until their diagnostic access policy is approved.
- For R20, only the central `matrizes`/`edit` RBAC mapping and its tests are authorized. Changing or removing the local `readonly` behavior is not authorized in this closeout.
- Do not claim that R22–R24 have a selected policy.
- Do not authorize fail-closed global enforcement, UI changes, schema changes, database changes, or modularization.

- Current branch: `refactor/architecture-safety-net`; `HEAD` `f977fd6`; `origin/main...HEAD = 0 7`; working tree clean, staging empty, no untracked files; no push performed.
- Last accepted commit: `9b47c37` (`Record D73H historical verification isolation and pytest interface` — REF-0TF-B).
- Standard suite hermetic: `538` discovered, `17` D73H deselected, `521` selected and passed. REF-0C-A did not modify, add, or run any test.
- Phase classification: `STOP` — normative diagnosis only. No RBAC implementation, no production code change, no test change, no schema/DB/UI/config/dependency change.
- Files read: `PROJECT_STATE.md`, `AGENT_HANDOFF.md`, `main.py` (lines 9619–14305, all 24 handler functions), `app/auth.py`, `app/__init__.py`, `tests/_artifacts/rbac_unmapped_routes_baseline.json`, `tests/test_route_inventory_snapshot.py`, `tests/test_rbac_requirement_coverage.py`, `docs/refactor/REF_0B_ROUTE_CONTRACT_AND_RBAC_DEBT_CHARACTERIZATION.md`, `docs/refactor/REF_0TF_FAILURE_CLASSIFICATION.md`, `docs/refactor/REF_0TF_A_PROGRESS_CALENDAR_CONTRACT.md`, `docs/refactor/REF_0TF_B_D73H_HISTORICAL_VERIFICATION_ISOLATION.md`, `.gitignore`, `pytest.ini`.
- Files changed: `docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md` (created — main deliverable, 24-row matrix), `PROJECT_STATE.md` (REF-0C-A section added), `AGENT_HANDOFF.md` (this section).
- Baseline reconciliation: confirmed exactly 24 unmapped routes match `rbac_unmapped_routes_baseline.json`. No artifact was modified or regenerated.
- Superseded by REF-0C-A-R1: 21 HIGH-confidence recommendations, 3 MEDIUM, 0 LOW; R22-R24 require the unresolved diagnostic access-policy decision.
- Unresolved decisions for RBAC implementation (not gaps in the diagnosis):
  - R10 diagnostics resource: `requisicoes` vs `arquivos`
  - R11 diagnostics resource: `mensagens` vs `sistema_config`
  - R12 diagnostics resource: `matriculas` vs `turmas`
  - R20 readonly enforcement gap: `readonly` vs `read` for dispatch semantics
  - Resource authority limitation: `get_admin_permission_requirement` returns single tuple; implementation may need multi-requirement support
  - Template-driven access control: pre-identified remediation sites
  - Missing test plan for RBAC verification
  - Informational GET risk for R2, R8, R13, R18
- Prohibitions:
  - No RBAC implementation in this phase (REF-0C-A is STOP)
  - No changes to `main.py`, `app/auth.py`, tests, schemas, UI, DB, deps, or configs
  - No baseline artifact regeneration or modification
- Exact next action: **ChatGPT supervisor must inspect the repository and return APPROVED, CHANGES REQUIRED, or BLOCKED.** If APPROVED, the next authorized phase is REF-0C-B (RBAC implementation planning) or equivalent.
- RBAC correction and route modularization remain prohibited.

## REF-0B — route contract and RBAC debt characterization (2026-07-16)

- Starting state: `refactor/architecture-safety-net` at `340fc7c`; REF-0B was accepted at `f2b1cfc`; no production code, UI, database, schema, environment, or dependency file changed.
- Files read: `main.py`, `app/auth.py`, `tests/conftest.py`, existing CSRF/release tests, `PROJECT_STATE.md`, and this handoff.
- Files changed: `tests/test_route_inventory_snapshot.py`, `tests/test_rbac_requirement_coverage.py`, `tests/_artifacts/route_inventory_baseline.json`, `tests/_artifacts/rbac_unmapped_routes_baseline.json`, `PROJECT_STATE.md`, and this handoff.
- Contract: `tests/test_route_inventory_snapshot.py` derives a deterministic snapshot from `main.app.url_map` (excluding automatic `HEAD` and `OPTIONS`) and compares it read-only in normal runs. Deliberate refresh requires `SGAA_UPDATE_ROUTE_INVENTORY_BASELINE=1`.
- RBAC debt: `tests/test_rbac_requirement_coverage.py` begins independently from URL paths `/admin` and `/admin/...`, then calls `get_admin_permission_requirement(endpoint, method)`. The current baseline has `24` unmapped route/method combinations; the full exact list, technical reason, and `null` current requirement are in `tests/_artifacts/rbac_unmapped_routes_baseline.json`. “Este baseline caracteriza dívida preexistente. O estado-alvo obrigatório é lista vazia. A existência do baseline não autoriza novas rotas sem política.” Deliberate refresh requires `SGAA_UPDATE_RBAC_DEBT_BASELINE=1`.
- Validation: pre-flight focused baseline `8 passed`; new contract tests `3 passed`; required regression baseline `42 passed`. The two new tests were rerun normally after baseline generation and did not rewrite either artifact.
- Risks: RBAC debt remains uncorrected by design; route URL and endpoint changes now require deliberate baseline review. No route modularization is authorized.
- Historical next step at REF-0B closeout: `REF-0T`, subsequently accepted at `c440297`. RBAC remediation was not authorized by that transition.

## REF-0T — test isolation audit and full-suite baseline (2026-07-16)

- Starting state verified: `refactor/architecture-safety-net`, `f2b1cfc`, `origin/main...HEAD = 0 1`, clean worktree, Python `3.11.15`. The REF-0B commit manifest contained exactly its six authorized files.
- Files read: `tests/conftest.py`, `pytest.ini`, `app/__init__.py`, `app/db.py`, relevant database/upload/document/backup/sync hooks in `main.py`, and test filesystem-operation sites.
- Isolation findings: test DB is `tests/.pytest_app_database.db`; temporary runtime documents and backups use `tempfile`; per-test uploads/logs/backups use `tmp_path`. Destructive operations include `shutil.rmtree` for test runtime and guarded root artifacts, plus test-local removes, writes, and copies. No absolute path points to the main workspace; fixture-only `C:/...` strings are non-operational. D73H reads `ROOT/database.db`, which resolves to the current checkout, never the principal workspace.
- Disposable detached worktree: `C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0t-f2b1cfc`, HEAD `f2b1cfc`; it contained no `database.db`, `.env`, uploads, documents, backups, junction, or symlink to the main workspace. It was removed after evidence capture. Git reported a permission error only while deleting the now-unlisted administrative worktree metadata; no project data was affected.
- Collection: `537` tests, exit `0`, `5.23s`, no collection errors or relevant warnings.
- Full suite: `519 passed`, `18 failed`, `0 skipped`, `0 xfailed`, `0 xpassed`, exit `1`, `255.57s`, no relevant warnings. Distinct failures: (1) `tests/test_aluno_progresso.py::test_aluno_progresso_renderiza_catalogo_e_agrega_semestres` expected two semesters but observed a third (`2026/2`); (2) seventeen D73H reconciliation tests failed with `FileNotFoundError` because the deliberately data-free worktree lacks root `database.db`.
- Worktree effects before removal: modified `tests/_artifacts/csrf_inventory_shadow_off.json` and `csrf_inventory_shadow_on.json`; ignored `.pytest_cache`, Python `__pycache__`, `logs/app.log`, and empty `uploads/`. No backup, document, or real database was generated.
- Main workspace after execution: `database.db` SHA-256 unchanged at `A3A55E63427024476D85D1FCE3E0A5EFAEDCD33624400B2E67A815217D570FE9`; sensitive-directory manifest unchanged (`backups`/`uploads`/`documentos_alunos` absent; `logs` manifest `05daa74ef6f65a68fd13eb78f9abc1d95f8d945d6377f0971d2084e08615b619`); clean status and unchanged HEAD.
- Permanent changes in this phase: only `PROJECT_STATE.md` and this handoff. No production, UI, database, schema, environment, dependency, RBAC, or modularization change.
- Decision: **NO-GO** for `REF-0C-A`. Do not correct RBAC or modularize. Architect authorization is required for a dedicated failure-classification phase.

## REF-0TF — full-suite failure classification (2026-07-16)

- Investigation started at `refactor/architecture-safety-net` / `c440297`, clean status, `origin/main...HEAD = 0 2`; all focused execution used a detached temporary worktree and the validated primary `.venv` interpreter. No primary database was opened or copied.
- Files read: progress test/fixture and `app/views/aluno.py`; D73H test, tool, YAML fixture, database/runtime setup, canonical state, and relevant Git history (`dea3de5`, `ecdc9f5`, `b8ad2ae`).
- Cluster A: classification C+B. The fixture's 2026-09-10 event is now in the current 2026/2 semester. `date.today()` is the explicit production gate; three fresh runs identically observed `['2025/2', '2026/1', '2026/2']`. The test expectation is stale; no product regression is evidenced.
- Cluster B: classification G+D+E. All 17 nodes fail at the same absent root source. A worktree-only database initialized by `main.init_db()` retained SHA-256 `6D82B8ED4B0EAB9678FAFB9B84CC4B0CD82B7140A2B20D1B4E60EE053389CA12` across plan mode, then failed on missing historical `AAC-rev5`. D73H is historical live-operation verification, not clean-clone regression coverage.
- Historical authorized sequence at REF-0TF closeout: `REF-0TF-A — Progress Calendar Contract Hardening`, then `REF-0TF-B — D73H Historical Verification Isolation`. REF-0TF-A is now accepted at `e111cd5`; REF-0TF-B has not started. Neither phase authorizes RBAC, production refactoring, UI changes, live database access, or use of untracked historical backups.
- Risks: do not freeze production time while fixing the calendar test; do not turn private historical data into a fixture. RBAC correction and modularization remain prohibited.

## REF-0TF-A — progress calendar contract hardening (2026-07-16)

- Starting state: `refactor/architecture-safety-net` / `722b7a7`, clean worktree, `origin/main...HEAD = 0 3`.
- Files changed: `tests/test_aluno_progresso.py`, `docs/refactor/REF_0TF_A_PROGRESS_CALENDAR_CONTRACT.md`, `PROJECT_STATE.md`, and this handoff. No production, UI, database, schema, environment, dependency, RBAC, or modularization file changed.
- Contract: only the `datetime` binding imported by `app.views.aluno` is monkeypatched. On `2026-06-30`, `2026/2` is excluded as a future semester; on `2026-07-01`, it is included and aggregates its hours. The expected values are explicit and do not call the application helper.
- Validation: focused boundary nodes passed three consecutive times (`2 passed` each); `tests/test_aluno_progresso.py` passed (`4 passed`). In detached worktree `C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0tf-a-validation`, collection was `538` and the full suite was `521 passed, 17 failed` in `234.13s`. The exact 17 remaining failures are D73H and all stop on missing worktree-local `database.db`; no other failure was introduced.
- The primary database and untracked historical backups were not opened, copied, or changed. The temporary worktree is disposable; its runtime artifacts do not belong to the primary worktree.
- Decision: **GO for REF-0TF-B only.** Do not correct RBAC, modularize routes, alter production code, or use a live database/backup. REF-0TF-B must define a sanitized, versioned D73H fixture or an explicit separate invocation contract.

Last updated: 2026-07-16
Closeout: D8.5C cleanup of id=57 closeout (docs-only)
Executor: Claude Sonnet 4.6 (D8.5A read-only post-smoke audit + D8.5B controlled cleanup of id=57 + D8.5C docs-only closeout); Claude Sonnet 4.6 (D8.4A local write-flag-on supervised smoke + D8.4B docs-only closeout); Claude Sonnet 4.6 (D8.3A copy-db write-flag smoke + D8.3B docs-only closeout); Claude Sonnet 4.6 (D8.2A read-only write-cutover risk plan + D8.2B student-edit-snapshot contract hardening + D8.2B-CLOSEOUT docs sync); Claude Sonnet 4.6 (D8.1B student-facing versioned snapshot read-only display + validation + D8.1C docs closeout); Claude Sonnet 4.6 (D8.0A read-only audit + D8.0B baseline suite + backup); Claude Sonnet 4.6 (D7.7C3 final verify and push + D7.7C4 post-push doc sync; D7.7B1 matrix version validity hardening + docs closeout; D7.6G2 full suite remediation + docs closeout; D7.6E latest active version default + docs closeout; D7.6D matrix version selection + docs closeout; D7.6C activity version menu + docs closeout; D7.6B2 schema migration + R1 + R2 hardening + D7.6B3 docs closeout; D7.5D patch implementation + visual R1 fix + commit closeout); Codex GPT-5 (D7.5C patch implementation + validation report + commit closeout); Claude Sonnet 4.6 (D7.4F read-only archive audit; D7.4G archive execution); Codex GPT-5 (D7.3K read-only diagnosis + docs closeout; D7.3J live apply + suite stabilization + docs closeout; D7.3I validation + docs closeout; D7.3H docs closeout); Claude Sonnet 4.6 (D7.3E closeout); Kimi K2.6 (audit D7.3D-PATCH1-REVIEW)

## Current State

- D8.5B aprovada; D8.5C em fechamento documental.
  - HEAD esperado antes do closeout: `7a67c7e`.
  - `origin/main...main` antes: `0 0`.
  - Resultado: requisição smoke `id=57` removida do `database.db` live;
    contagens de `requisicoes` de volta a `41` (snapshots `13`/`13`/`13`);
    `PRAGMA foreign_key_check` vazio; backups D8.5B e D8.4A preservados e
    íntegros; `database.db` continua não rastreado; sem `VACUUM` executado.
  - Backup D8.5B: `D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.5B-cleanup-id57-20260620-231236.db`.
  - `database.db` live: SHA256 antes
    `0A00BCC9779A5DBD57447BA72EC51C90D9FF981DEC046F581F4C67D61A2574CD`,
    SHA256 depois
    `1CA32F61553433E740E2B60B5428C56BC287ABB271ABB96680DD1320D17C5C80`
    (hash não retorna ao pré-D8.4A — esperado, pois SQLite não compacta
    páginas liberadas sem `VACUUM`; critério aceito foi integridade lógica).
  - Relatório completo: `docs/d8_5_cleanup_id57_result.md`.
  - Cutover real continua **NÃO** autorizado.
  - Próxima etapa: D8.5D — final verify and push do closeout documental.
  - O que NÃO fazer:
    - não restaurar backup sem fase própria;
    - não executar `VACUUM` sem fase própria;
    - não ligar a flag de forma permanente;
    - não alterar `.env`;
    - não iniciar cutover real;
    - não criar novo fix de handoff apenas para perseguir o hash deste
      closeout docs-only.
- D8.4A funcionalmente fechada; docs em fechamento (D8.4B, docs-only).
  - Smoke executado diretamente contra o `database.db` local live (não
    uma cópia), com backup fresco verificado criado antes de qualquer
    escrita; `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=1` ligada somente
    no processo Python isolado do smoke; `.env` não foi criado/alterado.
  - Caso válido: PASS (`id=57`, `nome_evento=D8.4A_SMOKE_LOCAL_WRITE_FLAG_ON`,
    `atividade_versao_id=2`, `codigo_normativo_snapshot=AAC-rev6`,
    `regra_snapshot_json` coerente, `schema_version=d6.4.0-v1`).
  - Guard de edição: PASS (troca de `atividade_id` bloqueada de forma
    atômica; mensagem de bloqueio visível na resposta).
  - Caso skip: **não exercitado no live** por decisão deliberada (sem
    candidato natural seguro; preferência por não criar curso/turma
    artificial no live); já validado em cópia isolada na D8.3A.
  - Contagens de `requisicoes`: `41`→`42` (delta exato `+1` em
    `atividade_versao_id`/`codigo_normativo_snapshot`/`regra_snapshot_json`);
    mutação confirmada restrita à tabela `requisicoes`.
  - `database.db` live: SHA256 antes
    `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`,
    SHA256 depois
    `0A00BCC9779A5DBD57447BA72EC51C90D9FF981DEC046F581F4C67D61A2574CD`
    (mudança esperada pela linha smoke), 544.768 bytes antes/depois; não
    versionado.
  - Backup: `D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.4A-local-write-flag-on-20260620-212052.db`
    — hash idêntico ao live antes da escrita; permanece intacto após o
    smoke.
  - Script do smoke fora do repo:
    `D:\OneDrive\Programação\SGAA_database_backups\d8_4a_smoke.py`.
  - Ambiente auxiliar: `.venv` do projeto estava quebrado (Python 3.13
    removido da máquina); criado venv Python 3.11 descartável fora do
    repo (`SGAA_database_backups\d84a_runtime_venv`) só para executar o
    smoke; nenhum arquivo do repositório foi alterado por isso.
  - Requisição smoke `id=57` permanece no `database.db` live como
    evidência; mantida até decisão explícita de fase própria de
    cleanup/restauração.
  - Sem alteração de código, schema, template ou teste; sem commit; sem
    push na D8.4A.
  - Relatório completo: `docs/d8_4_local_write_flag_on_smoke_result.md`.
  - Cutover real continua **NÃO** autorizado.
  - Próxima etapa: D8.4C — final verify and push do closeout documental;
    depois, decisão explícita entre manter `id=57` como evidência, abrir
    fase própria de cleanup/restauração, ou planejar ativação controlada
    mais ampla.
  - O que NÃO fazer:
    - não remover a requisição `id=57` sem fase própria;
    - não restaurar o backup sem fase própria;
    - não ligar a flag de forma permanente;
    - não alterar `.env`;
    - não iniciar cutover real;
    - não criar novo fix de handoff apenas para perseguir o hash deste
      closeout docs-only.
- D8.3A funcionalmente fechada (closeout anterior, ver histórico).
  - Smoke executado inteiramente em cópia física isolada de `database.db`;
    `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=1` ligada somente no processo
    isolado do smoke; live nunca foi escrito.
  - Caso válido: PASS (`id=58`, `atividade_versao_id=2`,
    `codigo_normativo_snapshot=AAC-rev6`, `regra_snapshot_json` coerente).
  - Guard de edição: PASS (troca de atividade bloqueada de forma atômica).
  - Caso skip: PASS (`id=59`, snapshot `NULL`, sem 500).
  - `database.db` live: SHA256 antes/depois idêntico,
    `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`,
    544.768 bytes; não versionado.
  - Backup: `D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.3A-live-baseline-20260620-205155.db`.
  - Cópia de trabalho: `D:\OneDrive\Programação\SGAA_database_backups\database.D8.3A-smoke-working-20260620-205155.db`.
  - Sem alteração de código, sem commit, sem push na D8.3A.
  - Relatório completo: `docs/d8_3_copy_db_write_flag_smoke_result.md`.
  - Cutover real continua **NÃO** autorizado.
  - Próxima etapa: D8.3C — final verify and push do closeout documental;
    depois, D8.4A — plano/ativação local controlada da flag, somente com
    autorização explícita.
  - O que NÃO fazer:
    - não ligar a flag em ambiente live;
    - não alterar `.env`;
    - não substituir `database.db` pela cópia do smoke;
    - não iniciar cutover real;
    - não criar novo fix de handoff apenas para perseguir o hash deste
      closeout docs-only.
- D8.2B funcionalmente fechada (closeout anterior, ver histórico).
  - Commit funcional aceito: `d06a02d` — `Block activity changes after student snapshot write`.
  - `origin/main...main` antes do closeout: `0 1`.
  - Push: não realizado.
  - Contrato D8.2B:
    - aluno não pode trocar atividade se já houver snapshot;
    - demais campos continuam editáveis;
    - requisições sem snapshot mantêm troca legada;
    - sem recalcular/limpar snapshot;
    - sem alteração em admin/deferimento/resolver/schema/`database.db`.
  - Testes aceitos: 12 passed (D8.2B/D8.1B); 32 passed (regressão dirigida);
    534 passed (suíte completa), 0 failed, 0 errors.
  - Próxima etapa: D8.2C — final verify and push.
  - Nota anti-loop: este closeout docs-only cria novo HEAD documental; não
    criar outro commit apenas para "corrigir HEAD" no handoff. O commit
    funcional `d06a02d` permanece a baseline da D8.2B; o hash documental deste
    closeout é reportado no relatório final, não perseguido por um novo fix.
  - O que NÃO fazer:
    - não ligar flag de write sem nova fase explícita;
    - não recalcular snapshot em edição do aluno;
    - não alterar deferimento admin sem plano próprio;
    - não alterar `database.db` sem autorização explícita.
- D8.1B funcionalmente fechada (closeout anterior, ver histórico):
  - Commit `1b34b55` — `Show versioned snapshot metadata to students`.
  - Testes aceitos: 6 passed (D8.1B); 32 passed (regressão dirigida);
    528 passed (suíte completa).
- D7.3D dry-run importer implemented, audited, and committed.
- D7.3E-RO1 read-only fixture vs real database convergence diagnostic accepted.
- D7.3F-PLAN read-only reconciliation matrix accepted and its architectural decisions are now closed.
- D7.3G-PLAN-APPLY accepted as a read-only future apply plan.
- D7.3H-PATCH1 controlled reconciliation apply script implemented and accepted after independent audit.
- D7.3I-VALIDATE-APPLY-COPY accepted after controlled execution against a temporary DB copy.
- D7.3J-LIVE-APPLY-CREATE-DRAFT accepted after controlled execution first on a DB copy and then by replacing live with the validated copy.
- D7.3J-PATCH1-TEST-STABILIZE accepted after decoupling the focused suite from mutable live DB state.
- D7.3K-DECIDE-MATRIX-LINK accepted after read-only diagnosis.
- D7.3 final decision: keep `61/62` as draft and close the trail with no activation and no matrix link.
- D7.4F read-only archive audit completed: all expected states confirmed before archival.
- D7.4G branch archive executed:
  - tag `archive/d7-activity-versioning` created at
    `b5aafa7605bab4f8ef4b61885ec5200627ea2f0b` and published to remote;
  - `recovery/d7-activity-versioning` remote branch deleted;
  - local branch `recovery/d7-activity-versioning` preserved at `b5aafa7` (`[gone]`);
  - no apply, SQL, activation, matrix link, merge, rebase, or code change executed.
- D7.5C accepted after implementation, focused tests, and user visual validation.
- D7.5C functional commit created:
  - `bc8a4f6` - `Add matrix-scoped activity creation`;
  - files: `main.py`, `templates/admin_matriz_form.html`,
    `tests/test_admin_matrix_new_activity.py`.
- D7.5C delivered:
  - generic `+ Nova atividade` button in the left header of the matrix screen;
  - same flow for `Lista de AAC` and `Lista de AEU`;
  - modal/form opened from the matrix screen;
  - initial `atividade_versao` created transactionally;
  - `matriz_atividade_versao_item` created when `Adicionar à matriz atual` is checked;
  - matrix name used only as contextual UI label, never in `codigo_normativo`.
- D7.5C preserved:
  - no schema/migration;
  - no `database.db` change in the feature closeout.
- D7.5D accepted after implementation, focused tests, visual validation, and R1 visual alert fix.
- D7.5D functional commit created:
  - `0dbd2b1` - `Add matrix card version creation`;
  - files: `main.py`, `templates/admin_matriz_form.html`,
    `tests/test_admin_matriz_nova_versao_card.py`.
- D7.5D delivered:
  - `⋮` button on right-column (selected/linked) activity cards in the matrix edit screen;
  - modal with norma select and context label `Versão nesta matriz: [codigo_normativo]`;
  - POST route creates or reuses `atividade_versao` respecting UNIQUE constraint;
  - relinks only the current matrix; older matrices preserve their original version link;
  - matrix name not written into `codigo_normativo`.
- D7.5D preserved:
  - no schema/migration;
  - no `database.db` change in the feature closeout;
  - no in-place UPDATE of a version already used by older matrices;
  - D7.5C not reopened.
- Current branch: `main`.
- D7.5D functional state is recorded by commit `0dbd2b1` on `main`.
- `main` is 3 commits ahead of `origin/main`.
- Working tree clean.
- D7 fully integrated into `main`. D7.4 trail is closed.
- D7.5D is complete (commit `0dbd2b1`).
- D7.6B2 is complete: `numero_versao` operacional entregue, schema endurecido, testes validados.
  - `UNIQUE(atividade_base_id, norma_id)` removida.
  - `UNIQUE INDEX idx_atividade_versao_base_num ON atividade_versao(atividade_base_id, numero_versao)` — full, non-partial.
  - `numero_versao >= 1` enforced by triggers (existing DB) and `CHECK` (new DB DDL).
  - `codigo_normativo` remains normative metadata, not the operational version identifier.
  - `norma_id` and `codigo_normativo` remain `NOT NULL`.
  - Commits: `1ca00a3`, `5184143`, `6b1579a`.
- D7.6C is complete: menu ⋮ de versões na tela `/admin/atividades` entregue.
  - Commit aceito: `62aed4b` — `Add activity version menu to admin activities`.
  - Menu contém: Editar atividade, Criar nova versão, Ver versões.
  - "Criar nova versão" navega para `/admin/catalogo-versoes/<base_id>/nova-versao`.
  - "Ver versões" navega para `/admin/catalogo-versoes/<base_id>`.
  - `base_id` obtido via subquery em `atividade_legacy_map` na query de `admin_atividades`.
  - Atividades sem `base_id` não geram link inválido (ações ficam `disabled`).
  - Nenhum template da matriz alterado; schema e `database.db` intocados.
  - Testes: `tests/test_admin_atividades_version_menu.py` 9/9; regressões 57/57.
- D7.6D is complete: matriz escolhe/relinka versão operacional existente.
  - Commit aceito: `2f81179` — `Make matrix choose operational activity versions`.
  - Card da matriz exibe badge `vN` via `atividade_versao.numero_versao`.
  - `codigo_normativo` é metadado secundário; não é badge principal.
  - Modal lista versões existentes da mesma `atividade_base` em ordem decrescente.
  - Versão atual da matriz aparece pré-selecionada (`is_current: true`).
  - POST relinka via `_set_versao_da_matriz_para_base`; não cria `atividade_versao`.
  - POST valida `versao_id` pertencente à mesma `atividade_base`; rejeita cross-base e inexistentes.
  - `templates/admin_atividades.html` não alterado. Schema e `database.db` intocados.
  - Testes: `tests/test_admin_matriz_escolher_versao.py` 10/10; `tests/test_admin_matriz_nova_versao_card.py` 13/13; regressões 64/64.
- D7.6E is complete: novo vínculo matriz→atividade_base usa automaticamente a última versão ativa.
  - Commit aceito: `e359047` — `Default matrix links to latest active activity versions`.
  - `_ensure_default_versao_link` inserida em `_save_matriz_activity_links`: resolve `base_id` via `atividade_legacy_map`; verifica link existente; obtém última ativa via `get_ultima_versao_ativa_por_base`; cria link via `_set_versao_da_matriz_para_base`.
  - Vínculo manual existente preservado: se `matriz_atividade_versao_item` já contém link para a base, nenhuma alteração.
  - Caso sem versão ativa: nenhum link criado (documentado no T09).
  - Matriz não cria `atividade_versao`: confirmado no T07.
  - Admin → Atividades não alterado. Templates da matriz não alterados. Schema e `database.db` intocados.
  - Testes: `tests/test_admin_matriz_latest_active_default.py` 9/9; regressões relacionadas 74/74.
- D7.6G2 is complete: suíte completa remediada após introdução de `UNIQUE(atividade_base_id, numero_versao)` pelo D7.6B2.
  - Commit aceito: `bdd5ddc` — `Fix legacy seeds and scripts for D7.6B2 UNIQUE(base,numero_versao) constraint`.
  - Testes aceitos: 503 passed, 4 warnings, 0 failed.
  - Seeds legados em 7 arquivos de teste corrigidos com `COALESCE(MAX(numero_versao), 0) + 1`.
  - `tools/d73h_reconciliation_apply.py` corrigido com `enumerate(TARGET_NORMA_CODES, start=1)`.
  - Asserts de catálogo atualizados para refletir remoção intencional de `UNIQUE(base,norma)`.
  - Inventário CSRF: rotas D7.6C/D adicionadas a `SPECIFIC_REGRESSION_TESTS`.
  - Exceção de escopo aceita: `tests/_artifacts/csrf_inventory_shadow_off.json` e `csrf_inventory_shadow_on.json` — artifacts deterministicamente gerados; nenhum `blocked_real_risk`; `high_risk_routes=0`.
  - `main.py` e templates: não alterados em D7.6G2.
  - `database.db` não alterado: SHA256 `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`, 544768 bytes.
- D7.7A aceita como auditoria read-only pós-push. Nenhum arquivo alterado. Quatro riscos confirmados e transferidos para D7.7B1.
- D7.7B1 is complete: validação de versões no modal, POST e default agora respeitam `status='ativa'` e `matriz_norma`; vínculos explícitos órfãos removidos ao salvar lista.
  - Commit aceito: `d53d9cd` — `Harden matrix version selection validity`.
  - Testes aceitos: focados 28/28; regressão D7.6 (7 arquivos) 84/84; suíte completa 512/0.
  - Artifacts CSRF restaurados no cleanup R1; não entraram no commit.
  - `database.db` não alterado.
- D7.7C1 is complete: `vN` agora exibido no catálogo de versões, nos formulários de criação/edição e na tela de versões da matriz.
  - Commit aceito: `99f4659` — `Show operational version numbers in admin version UI`.
  - Escopo: `admin_catalogo_versao_detalhe.html`, `admin_catalogo_versao_form.html`, `admin_matriz_versoes.html`, `main.py`, `tests/test_admin_version_visibility_ui.py`.
  - `codigo_normativo` permanece metadado normativo; backend D7.7B intocado.
  - Testes aceitos: focados A 52/52; focados B 38/38; suíte lotes (batchSize=20) 522/0.
  - Artifacts CSRF restaurados antes do commit.
  - `database.db` não alterado.
- Current branch: `main`. HEAD: `5c6859b` — `Fix D7.7C handoff current state`.
- `origin/main` also at `5c6859b` after D7.7C3 push. `origin/main...main = 0 0`. Working tree clean. Push D7.7C3 executed successfully (fast-forward, no force, no amend).
- No broad real importation into `database.db` has been performed; only the
  narrow D7.3J controlled `CREATE_DRAFT` live apply.
- `database.db` current state (post-D7.6B2):
  - `544768` bytes;
  - SHA256 `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`.
- Live now contains:
  - `atividade_base.id=37`;
  - `atividade_versao.id=61`, `AAC-rev5`, `status=rascunho`;
  - `atividade_versao.id=62`, `AAC-rev6`, `status=rascunho`;
  - no matrix links, no transition changes, and no request changes for those rows.
- D7.3K confirmed in read-only mode:
  - no file changed during diagnosis;
  - no DB changed during diagnosis;
  - only SQLite `SELECT` / `PRAGMA` were executed in `mode=ro`;
  - there is still no legitimate matrix candidate for base `37`.

## D7.3D - Historical Tooling Write Phase

- Scope: dry-run importer consuming `normative_fixtures/d73c_normative_fixture.yaml` into an isolated SQLite DB.
- Delivered files:
  - `tools/d73d_normative_importer_dryrun.py`
  - `tests/test_d73d_normative_importer_dryrun.py`
  - `requirements.txt` with `PyYAML==6.0.2`
- Guarantees:
  - no `--apply`;
  - refuses `--db database.db`;
  - no import from `main` / runtime app context;
  - temporary isolated DB only;
  - transaction-safe and idempotent;
  - real `database.db` preserved.
- Audit result: **ACEITAR D7.3D-PATCH1**.

## D7.3E-RO1 - Fixture vs Real Database Convergence Diagnostic

- Scope: read-only comparison between `normative_fixtures/d73c_normative_fixture.yaml` and the current `database.db`.
- Git state observed during diagnosis:
  - branch `recovery/d7-activity-versioning`;
  - `HEAD` `45dd39d`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - working tree clean.
- DB access method:
  - SQLite URI read-only mode (`mode=ro`);
  - only `SELECT`, `PRAGMA`, and `sqlite_master` reads.
- Current DB counts at D7.3E:
  - `norma_atividade`: `6`;
  - `atividade_base`: `35`;
  - `atividade_versao`: `60`;
  - `atividade_transicao`: `31`;
  - `matriz_atividade_versao_item`: `59`;
  - `requisicoes`: `41`;
  - fully versioned `requisicoes`: `13`;
  - only one version outside matrix links: `id=60`, `Runtime Base 2cb9b503`, `NRM-RT-2cb9b503`, `rascunho`.
- Technical conclusion:
  - the dry-run importer would abort on the first divergent norm if pointed at the current real DB;
  - it must not be repurposed as `apply`;
  - direct fixture application to the live DB is unsafe.

## D7.3F-PLAN - Reconciliation Matrix Decisions

- Scope: read-only reconciliation matrix between the canonical fixture and the current real database.
- Execution state observed:
  - initial `HEAD` `f10db80`;
  - branch `recovery/d7-activity-versioning`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - working tree clean;
  - SQLite opened only by URI read-only mode (`mode=ro`);
  - no file or database altered during the diagnosis.
- Matrix summary:
  - `30` fixture activities have preservable mappings to existing bases;
  - `59` of `61` fixture versions have an existing preservable candidate;
  - the remaining `2` versions were `VISITAS_TECNICAS_PROFESSORES` in `AAC-rev5` and `AAC-rev6`;
  - all versions `1..59` are already linked in `matriz_atividade_versao_item`;
  - versions `2`, `8`, `10`, `56`, and `58` also appear in versioned requests/snapshots;
  - `atividade_versao.id=60` is runtime `NRM-RT-2cb9b503` and remains outside official reconciliation;
  - fixture transition `TRAB_VOLUNTARIO_TERCEIRO_SETOR AAC-rev5 -> AEU-rev1` already exists as `atividade_transicao.id=27`, but with divergent `justificativa`.
- Architectural decision closed for `PROJETOS_EXTENSAO`:
  - preserve the live split;
  - preserve `base27` / `v52` / `v53` for extension projects;
  - preserve `base8` / `v51` for institutional support projects;
  - preserve the extra persisted `aac_para_aeu` transition already present in runtime;
  - do not collapse these into a single canonical live base.
- Architectural decision closed for `VISITAS_TECNICAS_PROFESSORES`:
  - do not map it automatically to `base6`;
  - `base6` is too generic for a safe canonical mapping;
  - if a future apply phase is explicitly approved, create a new specific `atividade_base` and draft versions for `AAC-rev5` and `AAC-rev6`;
  - this phase did not authorize any real creation.
- Frozen reconciliation rules:
  - never overwrite `atividade_versao.id=1..59`;
  - never overwrite versions with versioned requests/snapshots: `2`, `8`, `10`, `56`, `58`;
  - never overwrite `atividade_transicao.id=1..31`;
  - never alter runtime `NRM-RT*` items;
  - any future structural reconciliation must happen through a new draft version or explicit mapping, never overwrite.
- Runtime items that remain `PRESERVE_EXISTING / OUT_OF_FIXTURE`:
  - `NRM-RT`;
  - `NRM-RT-5c96604e`;
  - `NRM-RT-2cb9b503`;
  - `Runtime Base`;
  - `Runtime Base 5c96604e`;
  - `Runtime Base 2cb9b503`.
- Human decisions are now closed:
  - `PROJETOS_EXTENSAO`: keep runtime split;
  - `VISITAS_TECNICAS_PROFESSORES`: no mapping to `base6`; future specific draft creation only if later approved.

## D7.3G-PLAN-APPLY - Future Apply Plan

- Scope: read-only technical plan for a possible future apply, derived from D7.3F.
- Execution state observed:
  - initial `HEAD` `da869e9`;
  - branch `recovery/d7-activity-versioning`;
  - remotes aligned;
  - working tree clean;
  - `database.db` intact at `528384` bytes and SHA256 `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.
- Apply scope frozen:
  - not a general reconciliation;
  - not a real import of the entire fixture;
  - only a possible future `CREATE_DRAFT` path for `VISITAS_TECNICAS_PROFESSORES`.
- `PRESERVE / NO-OP` set:
  - norms `AAC-rev5`, `AAC-rev6`, `AEU-rev1`;
  - all already reconciled bases and versions;
  - `atividade_versao.id=1..59`;
  - `atividade_transicao.id=1..31`;
  - `matriz_norma`;
  - `matriz_atividade_versao_item`;
  - `requisicoes`;
  - runtime `NRM-RT*`.
- `PROJETOS_EXTENSAO` remains preserve-only:
  - preserve `base8` / `v51`;
  - preserve `base27` / `v52` / `v53`;
  - preserve the extra persisted `aac_para_aeu` transition;
  - do not collapse.
- `CREATE_DRAFT` is the only future write path allowed in principle:
  - create `1` new specific `atividade_base` for `VISITAS_TECNICAS_PROFESSORES`;
  - create `1` draft `atividade_versao` for `AAC-rev5`;
  - create `1` draft `atividade_versao` for `AAC-rev6`;
  - do not create matrix links;
  - do not create transitions;
  - do not modify requests.
- `FORBIDDEN` set:
  - overwrite any existing `atividade_versao`;
  - change `ativa -> rascunho`;
  - alter matrix;
  - alter requests or snapshots;
  - alter existing transitions;
  - alter runtime `NRM-RT*`;
  - collapse `PROJETOS_EXTENSAO`;
  - create new AAC/AEU norms;
  - create new versions for already mapped activities;
  - create new transitions in the initial apply.
- Mandatory preconditions for any real future apply:
  - intact verifiable backup of `database.db`;
  - recorded size and SHA256 before execution;
  - execute first against a DB copy;
  - produce logical before/after diff report;
  - explicit rollback path;
  - explicit human approval;
  - focused post-apply tests;
  - guaranteed `+0` changes to matrix, requests, transitions, and norms.

## D7.3H-PATCH1 - Controlled Reconciliation Apply Script

- Scope: new independent controlled `plan/apply` script for the only future write
  case admitted in planning: `CREATE_DRAFT` of `VISITAS_TECNICAS_PROFESSORES`.
- Delivered files:
  - `tools/d73h_reconciliation_apply.py`
  - `tests/test_d73h_reconciliation_apply.py`
- Script behavior:
  - `--plan` opens the target DB only by read-only URI mode;
  - `--apply` only accepts an explicit safe DB copy via `--db-copy`;
  - `--apply` refuses live `database.db`;
  - `--apply` refuses any `--db-copy` whose basename is `database.db`;
  - `--apply` requires `--backup-path`;
  - `--apply` requires `--backup-confirmed`;
  - `--apply` requires `--allow-create-visitas-professores`.
- Write scope allowed by the script:
  - `+1` `atividade_base`;
  - `+2` `atividade_versao` in `rascunho`;
  - `+0` `norma_atividade`;
  - `+0` `atividade_transicao`;
  - `+0` `matriz_atividade_versao_item`;
  - `+0` `requisicoes`.
- Guarantees preserved:
  - no general apply path;
  - no overwrite;
  - no touch to `PROJETOS_EXTENSAO`;
  - no touch to `NRM-RT*`;
  - no use of `base6`/`base7` as destination;
  - no alteration of existing versions;
  - no matrix change;
  - no request change;
  - no transition change.
- Validation evidence accepted:
  - real `database.db` preserved at `528384` bytes and
    `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
  - focused pytest:
    - `python -m pytest tests/test_d73h_reconciliation_apply.py -q --tb=short`
    - result: `17 passed`;
  - CLI `plan` text OK;
  - CLI `plan` JSON OK;
  - `apply` in temporary copy OK;
  - `apply` on live DB refused;
  - `git diff --check` clean.
- Audit:
  - `D7.3H-PATCH1-REVIEW` verdict: **ACEITAR D7.3H-PATCH1**;
  - no blocking/high/medium/low findings;
  - non-blocking observation: the suite does not explicitly assert default mode
    without `--plan/--apply` nor mutual exclusion by direct CLI execution, but
    the behavior is implemented and was independently audited as correct.
- Residual risks:
  - script assumes `AAC-rev5=id=1` and `AAC-rev6=id=2`;
  - `documentos_json` remains `NULL` in D7.3H-v1;
  - partial/conflicting state fails intentionally rather than repairing it.

## D7.3I-VALIDATE-APPLY-COPY - Validation Of Apply On Controlled DB Copy

- Scope executed:
  - validation of `tools/d73h_reconciliation_apply.py`;
  - `--apply` executed only on a temporary copy of `database.db`;
  - `--backup-path`, `--backup-confirmed`, and
    `--allow-create-visitas-professores` were required and supplied;
  - no write was performed against live `database.db`.
- Result of the apply on the copy:
  - process returned `0`;
  - `mode=apply`;
  - `disposition=create`;
  - created records:
    - `atividade_base.id=37`;
    - `atividade_versao.id=61`, `AAC-rev5`, `status=rascunho`;
    - `atividade_versao.id=62`, `AAC-rev6`, `status=rascunho`.
- Deltas confirmed on the copy:
  - `atividade_base`: `35 -> 36` (`+1`);
  - `atividade_versao`: `60 -> 62` (`+2`);
  - `norma_atividade`: `6 -> 6` (`+0`);
  - `atividade_transicao`: `31 -> 31` (`+0`);
  - `matriz_atividade_versao_item`: `59 -> 59` (`+0`);
  - `requisicoes`: `41 -> 41` (`+0`).
- Before/after comparison:
  - remained unchanged:
    - `norma_atividade`;
    - `atividade_transicao`;
    - `matriz_atividade_versao_item`;
    - `requisicoes`;
    - all pre-existing rows of `atividade_base`;
    - all pre-existing rows of `atividade_versao`;
  - the only observed effect was insertion of the 3 expected records in the copy.
- Guardrails confirmed:
  - `base6`/`base7` exist, but were treated as prohibited candidates;
  - `base6`/`base7` were not used as destination;
  - `PROJETOS_EXTENSAO` was not touched;
  - `NRM-RT*` was not touched.
- Live `database.db`:
  - was not a write target;
  - stayed at `528384` bytes;
  - stayed at SHA256
    `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.
- Conclusion:
  - validation on a DB copy passed;
  - the script behaved correctly in the controlled scenario;
  - this does **not** authorize any real apply on live.

## D7.3J-LIVE-APPLY-CREATE-DRAFT - Controlled Live Apply And Suite Stabilization

- Initial state before the live apply:
  - `HEAD=aedf936`;
  - branch `recovery/d7-activity-versioning`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - live `database.db` before apply:
    - `528384` bytes;
    - SHA256
      `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.
- Backup created:
  - `backups/database.pre-d73j-live-apply-20260612-165031.db`;
  - `528384` bytes;
  - SHA256
    `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
  - backup matched the initial live DB.
- Apply execution model:
  - executed first only on a controlled DB copy;
  - after validation, live `database.db` was replaced by that validated copy;
  - no manual SQL was executed;
  - there was no direct apply against the live file;
  - script used: `tools/d73h_reconciliation_apply.py`.
- Records created in live:
  - `atividade_base.id=37`;
  - `atividade_versao.id=61`, `norma_codigo=AAC-rev5`, `status=rascunho`,
    `eixo=AAC`;
  - `atividade_versao.id=62`, `norma_codigo=AAC-rev6`, `status=rascunho`,
    `eixo=AAC`.
- Final deltas in live:
  - `atividade_base`: `35 -> 36` (`+1`);
  - `atividade_versao`: `60 -> 62` (`+2`);
  - `norma_atividade`: `6 -> 6` (`+0`);
  - `atividade_transicao`: `31 -> 31` (`+0`);
  - `matriz_atividade_versao_item`: `59 -> 59` (`+0`);
  - `requisicoes`: `41 -> 41` (`+0`).
- Guarantees confirmed:
  - no new norm;
  - no new transition;
  - no new matrix link;
  - no request changed;
  - no old version changed;
  - `PROJETOS_EXTENSAO` was not touched;
  - `NRM-RT*` was not touched;
  - `base6`/`base7` were treated as prohibited candidates and not used as destination;
  - versions `61/62` remained `rascunho` and without matrix link.
- Live final signature:
  - `528384` bytes;
  - SHA256
    `09C0791A00B9A6EAB3BABC7E8349E8582092ADE6EB911798CE55062819A48E1A`.
- Post-apply test anomaly:
  - after the live apply, `4` focused D7.3H tests failed;
  - cause: those tests assumed `REAL_DB_PATH` still reflected the pre-apply state;
  - that premise stopped being valid because live moved to post-apply;
  - this was not a defect in the script and not a defect in the data.
- D7.3J-PATCH1-TEST-STABILIZE:
  - changed only `tests/test_d73h_reconciliation_apply.py`;
  - create-path tests now use a temporary controlled pre-apply scenario;
  - already-exists / idempotency tests now use a temporary controlled
    post-apply scenario;
  - fallback without backup removes only the 3 D7.3J rows in a temporary copy;
  - if `VISITAS_TECNICAS_PROFESSORES` gains more complex links or state later,
    the helper fails on purpose instead of masking the new scenario.
- Validation after stabilization:
  - focused pytest:
    - `python -m pytest tests/test_d73h_reconciliation_apply.py -q --tb=short`
    - result: `18 passed`;
  - live `plan` JSON updated:
    - `status=ok`;
    - `mode=plan`;
    - `disposition=already_exists`;
    - `planned_counts={"atividade_base": 0, "atividade_versao": 0}`;
    - `planned_actions=[]`;
    - `created_ids={"atividade_base": null, "atividade_versao": []}`;
  - live counts:
    - `atividade_base=36`;
    - `atividade_versao=62`;
    - `norma_atividade=6`;
    - `atividade_transicao=31`;
    - `matriz_atividade_versao_item=59`;
    - `requisicoes=41`.
- Git operational note:
  - `database.db` is ignored by the repository;
  - `git status --short` can appear clean after an operational DB change;
  - `git status --short --ignored` shows `database.db`, `database.db-wal`,
    `database.db-shm`, backups, and `tmp/` as ignored;
  - none of those artifacts must be committed.
- Final D7.3J state:
  - `VISITAS_TECNICAS_PROFESSORES` exists in live as draft;
  - it was not activated;
  - it was not linked to any matrix;
  - it did not alter requests;
  - it did not alter transitions;
  - it did not alter norms;
  - no refactor was performed.

## D7.3K-DECIDE-MATRIX-LINK - Read-Only Diagnosis And Final D7.3 Decision

- Execution mode:
  - read-only architectural / operational diagnosis only;
  - no file edits in the diagnosis phase;
  - no DB writes in the diagnosis phase;
  - only Git inspection, file reads, SQLite `SELECT` and `PRAGMA` in `mode=ro`.
- Initial state confirmed:
  - branch `recovery/d7-activity-versioning`;
  - `HEAD=b8ad2ae`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - `git status --short` was empty;
  - live `database.db` stayed at `528384` bytes and
    `09C0791A00B9A6EAB3BABC7E8349E8582092ADE6EB911798CE55062819A48E1A`.
- Live state confirmed by read-only queries:
  - `atividade_base.id=37` exists and is `status='ativo'`;
  - `atividade_versao.id=61` exists with `AAC-rev5`, `status='rascunho'`, `eixo='AAC'`;
  - `atividade_versao.id=62` exists with `AAC-rev6`, `status='rascunho'`, `eixo='AAC'`;
  - both have no row in `matriz_atividade_versao_item`;
  - both have no row in `requisicoes`;
  - both have no row in `atividade_transicao` as origin or destination.
- Counts confirmed:
  - `atividade_base=36`;
  - `atividade_versao=62`;
  - `norma_atividade=6`;
  - `atividade_transicao=31`;
  - `matriz_atividade_versao_item=59`;
  - `requisicoes=41`.
- Matrix diagnosis:
  - matrix `1` has `AAC-rev6` in `matriz_norma`;
  - matrix `2` has `AAC-rev5` in `matriz_norma`;
  - there is no real candidate matrix now because base `37` has no
    `atividade_legacy_map` row and therefore is outside the legacy scope of
    every matrix.
- Technical rule confirmed:
  - matrixâ†’`atividade_versao` link requires version `status='ativa'`;
  - the admin UI lists only active versions;
  - the route also requires the base to be in the matrix legacy scope;
  - the route also requires the version norm to be present in `matriz_norma`.
- Architectural decision:
  - do not activate `61/62` now;
  - do not link `61/62` now;
  - keep both versions as `rascunho`;
  - close D7.3 with no additional DB action.
- Reason:
  - a draft version cannot be linked;
  - isolated activation would still be insufficient;
  - there is no legitimate legacy mapping for base `37`;
  - forcing a mapping now would create collision risk without proven
    operational need.
- Future prohibition recorded:
  - do not reuse `base6` / `base7` as destination to resolve base `37`;
  - do not activate or link `61/62` without a new separate phase.
- Future phase permitted only if a real operational need appears:
  - decide the correct legacy activity to map to base `37`;
  - create or validate the legacy mapping;
  - activate the correct version;
  - link explicitly to the correct matrix;
  - test the resolver and the admin link route.
- Final D7.3 conclusion:
  - D7.3J created the controlled draft versions;
  - D7.3K decided not to expose, activate, or link them;
  - the D7.3 trail is closable with no further action now.

## D7.4G-BRANCH-ARCHIVE-EXECUTE - Branch Archive And D7.4 Trail Closeout

- Execution mode:
  - archival of `recovery/d7-activity-versioning` as annotated reference;
  - documentation update only — no code, no DB, no apply, no SQL, no activation,
    no matrix link, no merge, no rebase.
- Initial state confirmed before execution:
  - branch `main`;
  - `HEAD=6a9bf2d9146c8a0011ddc3376c7fb842eebf7da6`;
  - `origin/main...main = 0 0`;
  - `origin/recovery...main = 0 1`;
  - `origin/main...origin/recovery = 1 0`;
  - `merge-base = b5aafa7605bab4f8ef4b61885ec5200627ea2f0b`;
  - tag `archive/d7-activity-versioning` did not exist;
  - `git status --short` was empty;
  - `database.db`: `528384` bytes;
    SHA256 `09C0791A00B9A6EAB3BABC7E8349E8582092ADE6EB911798CE55062819A48E1A`.
- Operations executed:
  1. `git tag archive/d7-activity-versioning b5aafa7605bab4f8ef4b61885ec5200627ea2f0b`
  2. `git push origin archive/d7-activity-versioning`
  3. `git push origin --delete recovery/d7-activity-versioning`
- Confirmations:
  - tag `archive/d7-activity-versioning` exists at remote:
    `b5aafa7605bab4f8ef4b61885ec5200627ea2f0b`;
  - `refs/heads/recovery/d7-activity-versioning` no longer exists on remote
    (ls-remote returned empty);
  - local branch `recovery/d7-activity-versioning` preserved at `b5aafa7` (`[gone]`);
    not deleted in this phase.
- `database.db` preserved throughout:
  - `528384` bytes;
  - SHA256 `09C0791A00B9A6EAB3BABC7E8349E8582092ADE6EB911798CE55062819A48E1A`.
- D7 trail status: all functional work is integrated into `main`. The
  `archive/d7-activity-versioning` tag is the permanent named reference to the
  D7 activity versioning trail endpoint.
- No further work is required on the D7.4 trail.

## D7.5C-COMMIT-CLOSEOUT - Matrix-Scoped Activity Creation

- Execution mode:
  - focused feature closeout only;
  - no new functionality beyond D7.5C;
  - no D7.5D implementation;
  - no push.
- Functional commit:
  - `bc8a4f6` - `Add matrix-scoped activity creation`.
- Delivered behavior:
  - generic `+ Nova atividade` button in the left-column header of the matrix
    edit screen;
  - identical flow in `Lista de AAC` and `Lista de AEU`;
  - modal/form opened from the matrix screen;
  - creation of legacy activity + `atividade_base` + `atividade_legacy_map`;
  - initial `atividade_versao` created in the same transaction;
  - `matriz_atividade_versao_item` created when `Adicionar à matriz atual` is checked.
- Contract preserved:
  - server infers the axis from the matrix tab/route;
  - matrix name is only a contextual UI label;
  - matrix name is not written into `codigo_normativo`;
  - `codigo_normativo` remains the norm/regulation code;
  - multiple compatible active norms require explicit choice;
  - there is no fallback to the first active norm;
  - rollback is total on intermediate failure;
  - POST is CSRF-protected;
  - no schema/migration;
  - no D7.5D card menu/version cloning yet.
- Validation:
  - user visually validated the live screen after implementation;
  - focused pytest rerun passed:
    - `python -m pytest tests/test_admin_matrizes.py tests/test_admin_matrizes_csrf_ui.py tests/test_admin_matriz_versao_link.py tests/test_admin_matrix_new_activity.py -q --tb=short`
    - result: `28 passed`.
- Files touched in the functional commit:
  - `main.py`
  - `templates/admin_matriz_form.html`
  - `tests/test_admin_matrix_new_activity.py`
- Next phase authorized after this closeout:
  - `D7.5D-PATCH-CARD-VERSION-MENU`.

## D7.5D-COMMIT-CLOSEOUT - Matrix Card Version Menu

- Execution mode:
  - focused feature closeout only;
  - no new functionality beyond D7.5D;
  - no D7.5E implementation;
  - no push.
- Functional commit:
  - `0dbd2b1` - `Add matrix card version creation`.
- Delivered behavior:
  - `⋮` button on right-column (selected/linked) activity cards in the matrix edit screen;
  - `Criar nova versão` action opens a modal with norma select;
  - context label `Versão nesta matriz: [codigo_normativo]` for orientation;
  - server creates or reuses `atividade_versao` respecting UNIQUE(atividade_base_id, norma_id);
  - only the current matrix is relinked; older matrices keep their original version link.
- R1 visual alert correction included:
  - `<p class="matriz-modal-warning">` replaced with
    `<div class="flash flash-warning" role="alert">`;
  - reuses system-wide style; no new CSS added.
- Contract preserved:
  - matrix name is only a contextual UI label;
  - matrix name is not written into `codigo_normativo`;
  - no in-place UPDATE of a version already used by older matrices or requests;
  - full rollback on intermediate failure;
  - POST is CSRF-protected;
  - no schema/migration;
  - no `database.db` edit in the closeout;
  - D7.5C not reopened.
- Validation:
  - user visually validated the live screen after implementation;
  - focused pytest rerun passed:
    - `python -m pytest tests/test_admin_matriz_nova_versao_card.py -q --tb=short`
    - result: `15 passed`.
- Files touched in the functional commit:
  - `main.py`
  - `templates/admin_matriz_form.html`
  - `tests/test_admin_matriz_nova_versao_card.py`
- Next phase authorized after this closeout:
  - `D7.5E-CARD-VERSION-BADGE-UI`.

## D7.6B2-SCHEMA-CLOSEOUT - Operational Version Numbers For atividade_versao

- D7.6B2 aprovada funcionalmente após R1 (DEFAULT fix) e R2 (index hardening + triggers).
- Commits aceitos:
  - `1ca00a3` — `Add operational activity version numbers`
  - `5184143` — `D7.6B2-R1: fix numero_versao DEFAULT 0 -> DEFAULT 1 in atividade_versao`
  - `6b1579a` — `D7.6B2-R2: harden numero_versao schema — full unique index + pos triggers`
- Backup R2:
  - `database.pre-D7.6B2-R2-hardening-20260613-184709.db`
  - 544.768 bytes
  - SHA256 `92627DED44C9094E74F01DA5718C995CD3FDD5AC467EF79298541A75B777CD8C`
- Testes aceitos:
  - `tests/test_atividade_versao_numero.py`: 12/12 passed (T01–T12).
  - Regressão D7 (4 arquivos): 45/45 passed.
- Schema final:
  - `numero_versao INTEGER NOT NULL DEFAULT 1` com `CHECK(numero_versao >= 1)` no DDL de bancos novos.
  - `UNIQUE INDEX idx_atividade_versao_base_num ON atividade_versao(atividade_base_id, numero_versao)` — não-parcial.
  - Triggers: `trg_atividade_versao_num_pos_insert` e `trg_atividade_versao_num_pos_update` protegem `database.db` existente.
- Helpers entregues em `main.py`:
  - `get_next_numero_versao(conn, base_id)`
  - `get_ultima_versao_ativa_por_base(conn, base_id)`
- Próxima fase técnica: `D7.6C` — Admin → Atividades cria nova versão operacional.
- O que NÃO fazer na próxima fase:
  - não criar versão pela matriz como fluxo principal;
  - não usar `codigo_normativo` como badge ou identificador principal;
  - não alterar schema sem nova auditoria;
  - não fazer push;
  - não misturar UI da matriz com UI de atividades;
  - não implementar D7.6D junto com D7.6C.

## D7.6C-COMMIT-CLOSEOUT - Activity Version Menu On Admin Activities List

- Execution mode:
  - focused feature closeout only;
  - no new functionality beyond D7.6C;
  - no D7.6D implementation;
  - no push.
- Functional commit:
  - `62aed4b` — `Add activity version menu to admin activities`.
- Delivered behavior:
  - botão ⋮ (`data-action="more"`) adicionado ao float bar de `/admin/atividades`;
  - dropdown `ativ-more-menu` com três ações:
    - `data-menu-action="edit"` → Editar atividade (rota existente);
    - `data-menu-action="nova-versao"` → Criar nova versão (`/admin/catalogo-versoes/<base_id>/nova-versao`);
    - `data-menu-action="ver-versoes"` → Ver versões (`/admin/catalogo-versoes/<base_id>`).
  - "Criar nova versão" e "Ver versões" ficam `disabled` quando `base_id` é vazio.
  - Posicionamento do dropdown via `requestAnimationFrame`; fecha ao clicar fora.
- Backend:
  - query de `admin_atividades` agora inclui:
    ```sql
    (SELECT atividade_base_id FROM atividade_legacy_map WHERE atividade_id_legacy = id) AS base_id
    ```
  - `base_id` exposto como `data-base-id` em cada card `.impresso-card`.
- Contract preserved:
  - ações "Ver" e "Editar" preexistentes mantidas no float bar;
  - `codigo_normativo` não exposto como identificador operacional na lista;
  - `UNIQUE(atividade_base_id, norma_id)` não reintroduzida;
  - `numero_versao` via `get_next_numero_versao` preservado para inserções futuras;
  - nenhum template da matriz alterado;
  - schema e `database.db` intocados;
  - push não realizado.
- Validation:
  - focused pytest:
    - `python -m pytest tests/test_admin_atividades_version_menu.py -q --tb=short`
    - result: `9 passed`.
  - regression suite (5 files):
    - `python -m pytest tests/test_atividade_versao_numero.py tests/test_matriz_versao_contract.py tests/test_admin_matriz_versao_link.py tests/test_admin_matrix_new_activity.py tests/test_admin_matriz_nova_versao_card.py -q --tb=short`
    - result: `57 passed`.
- Files touched in the functional commit:
  - `main.py`
  - `templates/admin_atividades.html`
  - `tests/test_admin_atividades_version_menu.py`
- Next phase authorized after this closeout:
  - `D7.6D` — Matriz escolhe versão e card mostra vN.

## D7.6D-COMMIT-CLOSEOUT - Matrix Chooses Operational Activity Version

- Execution mode:
  - focused feature closeout only;
  - no new functionality beyond D7.6D;
  - no D7.6E implementation;
  - no push.
- Functional commit:
  - `2f81179` — `Make matrix choose operational activity versions`.
- Delivered behavior:
  - card da matriz exibe badge `vN` (ex.: `v1`, `v2`, `v3`) baseado em `atividade_versao.numero_versao`;
  - botão ⋮ abre modal reformulado que lista versões existentes da mesma `atividade_base` em ordem decrescente;
  - versão atual da matriz aparece pré-selecionada (`is_current: true`) via radio buttons;
  - `codigo_normativo` aparece no modal como metadado secundário, nunca como badge principal;
  - POST de escolha aceita `versao_id` (não mais `norma_id`); valida que a versão pertence à mesma `atividade_base`; relinka apenas a matriz atual via `_set_versao_da_matriz_para_base`;
  - POST não executa `INSERT INTO atividade_versao`; nenhuma versão nova é criada pela matriz;
  - POST rejeita `versao_id` de base diferente, `versao_id` inexistente e `versao_id` ausente.
- Contract preserved:
  - Admin → Atividades cria versão; Matriz apenas escolhe versão existente;
  - `templates/admin_atividades.html` não alterado;
  - schema e `database.db` não alterados;
  - `codigo_normativo` não é badge ou identificador principal;
  - CSRF obrigatório no POST;
  - rollback total em erro intermediário;
  - push não realizado.
- Validation:
  - focused pytest (novo):
    - `python -m pytest tests/test_admin_matriz_escolher_versao.py -q --tb=short`
    - result: `10 passed`.
  - focused pytest (atualizado):
    - `python -m pytest tests/test_admin_matriz_nova_versao_card.py -q --tb=short`
    - result: `13 passed`.
  - regression suite (6 files):
    - `python -m pytest tests/test_atividade_versao_numero.py tests/test_admin_atividades_version_menu.py tests/test_matriz_versao_contract.py tests/test_admin_matriz_versao_link.py tests/test_admin_matrix_new_activity.py tests/test_admin_matriz_nova_versao_card.py -q --tb=short`
    - result: `64 passed`.
- Files touched in the functional commit:
  - `main.py` (M)
  - `templates/admin_matriz_form.html` (M)
  - `tests/test_admin_matriz_escolher_versao.py` (A — novo)
  - `tests/test_admin_matriz_nova_versao_card.py` (M — semântica D7.6D)
- Next phase authorized after this closeout:
  - `D7.6E` — garantir que nova matriz / atividade adicionada usa a última versão ativa por padrão.

## D7.6E-COMMIT-CLOSEOUT - Matrix Defaults to Latest Active Activity Version

- Execution mode:
  - focused feature closeout only;
  - no new functionality beyond D7.6E;
  - no push.
- Functional commit:
  - `e359047` — `Default matrix links to latest active activity versions`.
- Delivered behavior:
  - ao salvar lista de atividades da matriz (`_save_matriz_activity_links`), novo vínculo recebe automaticamente a última `atividade_versao` ativa da base;
  - "última versão ativa" = `status='ativa'` com maior `numero_versao`;
  - vínculo manual já existente em `matriz_atividade_versao_item` é preservado sem alteração;
  - atividade sem entrada em `atividade_legacy_map`: nenhum link criado (no-op);
  - base sem versão ativa: nenhum link criado (documentado e testado no T09).
- Contract preserved:
  - Admin → Atividades cria versão; Matriz escolhe versão existente;
  - nenhum `INSERT INTO atividade_versao` no fluxo modificado;
  - `templates/admin_atividades.html` não alterado;
  - `templates/admin_matriz_form.html` não alterado nesta fase;
  - schema e `database.db` não alterados;
  - `codigo_normativo` não é badge ou identificador principal;
  - push não realizado.
- Validation:
  - focused pytest (novo):
    - `python -m pytest tests/test_admin_matriz_latest_active_default.py -q --tb=short`
    - result: `9 passed`.
  - regression suite (7 files):
    - `python -m pytest tests/test_admin_matriz_escolher_versao.py tests/test_admin_matriz_nova_versao_card.py tests/test_atividade_versao_numero.py tests/test_admin_atividades_version_menu.py tests/test_matriz_versao_contract.py tests/test_admin_matriz_versao_link.py tests/test_admin_matrix_new_activity.py -q --tb=short`
    - result: `74 passed`.
- Files touched in the functional commit:
  - `main.py` (M — +26 linhas: `_ensure_default_versao_link` + loop em `_save_matriz_activity_links`)
  - `tests/test_admin_matriz_latest_active_default.py` (A — novo, 341 linhas, T01–T09)
- Next recommended step:
  - gate de revisão / fechamento consolidado D7.6 antes de push;
  - não iniciar nova implementação sem autorização explícita.

## D7.6G2-COMMIT-CLOSEOUT - Full Suite Remediation

- Execution mode:
  - full suite remediation only;
  - no new functionality;
  - no push.
- Functional commit:
  - `bdd5ddc` — `Fix legacy seeds and scripts for D7.6B2 UNIQUE(base,numero_versao) constraint`.
- Root cause: `UNIQUE(atividade_base_id, numero_versao)` introduzido pelo D7.6B2 causou 52 falhas em seeds de teste que inseriam múltiplas `atividade_versao` para a mesma base sem `numero_versao` distinto.
- Corrections applied:
  - Seeds legados (7 arquivos): `COALESCE(MAX(numero_versao), 0) + 1` para calcular próximo `numero_versao` sem invocar `main.py`.
  - `tools/d73h_reconciliation_apply.py`: `enumerate(TARGET_NORMA_CODES, start=1)` → AAC-rev5 `numero_versao=1`, AAC-rev6 `numero_versao=2` por base.
  - `test_post_nova_versao_duplicate_rejected` e `test_post_editar_versao_duplicate_rejected_but_self_allowed` (7b): asserts atualizados para refletir que `UNIQUE(base,norma)` foi intencionalmente removida em D7.6B2; ambos os asserts preservados (valores ajustados).
  - `SPECIFIC_REGRESSION_TESTS` em `test_csrf_inventory_audit.py`: rotas D7.6C (`/admin/matrizes/<int:matriz_id>/atividades/<int:atividade_id>/nova-versao`) e D7.6D (`/admin/matrizes/<int:matriz_id>/atividades/nova/<string:active_tab>`) adicionadas apontando para testes de regressão CSRF já existentes e aprovados.
- Scope exception:
  - `tests/_artifacts/csrf_inventory_shadow_off.json` e `tests/_artifacts/csrf_inventory_shadow_on.json` incluídos no commit `bdd5ddc`.
  - Justificativa: artifacts gerados deterministicamente; 2 novas rotas recebem `ok_specific_regression_test`; `total_mutating_routes` 76→78; `ok_specific_regression_test` 1→3; `high_risk_routes=0`; nenhum status existente rebaixado; churn cosmético em `/admin/mensagens/<message_key>/reset` (entradas `msg_*`).
- Contract preserved:
  - `UNIQUE(atividade_base_id, numero_versao)` mantida.
  - `UNIQUE(atividade_base_id, norma_id)` não restaurada.
  - `main.py` não alterado.
  - Templates não alterados.
  - Schema e `database.db` não alterados.
  - Push não realizado.
- Validation:
  - full suite: `python -m pytest -q --tb=short`
  - result: `503 passed, 4 warnings, 0 failed`.
- Files touched in commit `bdd5ddc`:
  - `tests/test_activity_versioning_phase_b_schema.py` (M)
  - `tests/test_activity_versioning_resolver.py` (M)
  - `tests/test_admin_activity_version_catalog_readonly.py` (M)
  - `tests/test_admin_activity_version_catalog_version_activate.py` (M)
  - `tests/test_admin_activity_version_catalog_version_edit.py` (M)
  - `tests/test_admin_activity_version_catalog_version_form.py` (M)
  - `tests/test_admin_activity_version_catalog_version_lifecycle.py` (M)
  - `tests/test_csrf_inventory_audit.py` (M)
  - `tests/_artifacts/csrf_inventory_shadow_off.json` (M — scope exception)
  - `tests/_artifacts/csrf_inventory_shadow_on.json` (M — scope exception)
  - `tools/d73h_reconciliation_apply.py` (M)
- Next authorized step: D7.6H — verificação final pré-push e push, se autorizado.

## D7.7B1-COMMIT-CLOSEOUT - Matrix Version Validity Hardening

- Execution mode:
  - focused backend patch only;
  - no templates altered;
  - no schema altered;
  - no push.
- Functional commit:
  - `d53d9cd` — `Harden matrix version selection validity`.
- Delivered behavior:
  - `get_card_version_menu_data`: `versoes` list now filtered to `status='ativa'` + `norma_id IN matriz_norma`; inativas, rascunho, descontinuadas, substituídas e versões de norma fora da matriz excluídas do modal.
  - `admin_matriz_nova_versao_card`: dois guards adicionados após validação de `atividade_base_id`: (1) `status != 'ativa'` → flash + redirect; (2) `norma_id` ausente de `matriz_norma` → flash + redirect; nenhum efeito colateral em caso de rejeição.
  - `_ensure_default_versao_link`: substituiu `get_ultima_versao_ativa_por_base` por query inline com JOIN em `matriz_norma`, `ORDER BY numero_versao DESC LIMIT 1`; se não houver versão ativa com norma na matriz, retorna sem criar link.
  - `_save_matriz_activity_links`: após `_ensure_default_versao_link`, coleta `selected_base_ids` das atividades válidas do tab corrente; emite DELETE scoped por `activity_type` para remover vínculos de bases não mais selecionadas; preserva vínculos do outro tab; preserva vínculo manual quando a base continua selecionada.
- Tests updated:
  - `tests/test_admin_matriz_escolher_versao.py`: seed atualizado com `versao_inactive_id` (status=`inativa`) e `versao_norma_out_id` (norma_id=2, fora de `matriz_norma`); 5 novos testes T11–T15.
  - `tests/test_admin_matriz_latest_active_default.py`: seed atualizado com `INSERT INTO matriz_norma` + `norma_out_id` + `base_e/ativ_e/versao_e1` + `base_f/ativ_f/versao_f1/versao_f2`; 4 novos testes T10–T13.
- Contract preserved:
  - Admin → Atividades continua criando versão; Matriz continua apenas escolhendo/relinkando versão existente.
  - Matriz não cria `atividade_versao`.
  - Card da matriz continua mostrando `vN`.
  - Escolha manual válida continua preservada (no-op em `_ensure_default_versao_link` quando link já existe).
  - `codigo_normativo` continua metadado normativo, não badge principal.
  - `database.db` não alterado; push não realizado.
- Validation:
  - focused: `python -m pytest tests/test_admin_matriz_escolher_versao.py tests/test_admin_matriz_latest_active_default.py -q --tb=short` → 28 passed.
  - regression D7.6 (7 files): 84 passed.
  - full suite: 512 passed, 0 failed.
  - `git diff --check`: clean (apenas warnings CRLF, sem erros).
- Files touched in commit `d53d9cd`:
  - `main.py` (M)
  - `tests/test_admin_matriz_escolher_versao.py` (M — +5 testes T11–T15, seed atualizado)
  - `tests/test_admin_matriz_latest_active_default.py` (M — +4 testes T10–T13, seed atualizado com `matriz_norma`)
- Next authorized step: D7.7C3 — verificação final pré-push e push.

## D7.7C1-COMMIT-CLOSEOUT - Operational Version Numbers In Admin Version UI

- Execution mode:
  - visual/template patch only;
  - no schema altered;
  - no backend validity logic altered;
  - no push.
- Functional commit:
  - `99f4659` — `Show operational version numbers in admin version UI`.
- Delivered behavior:
  - `admin_catalogo_versao_detalhe.html`: exibe `vN` como rótulo visual da versão; `codigo_normativo` permanece visível como metadado normativo abaixo do rótulo.
  - `admin_catalogo_versao_form.html` (edição): mostra a versão operacional que está sendo editada (`vN`).
  - `admin_catalogo_versao_form.html` (nova versão): mostra a próxima `vN` prevista.
  - `admin_matriz_versoes.html`: exibe `vN` na coluna de versão atual e nas opções do select de definição.
  - `main.py`: ajustes de contexto para expor `numero_versao` nas rotas acima.
- Contract preserved:
  - `codigo_normativo` permanece metadado normativo em todas as telas; não substituído por `vN`.
  - Backend de validade D7.7B (`get_card_version_menu_data`, `admin_matriz_nova_versao_card`, `_ensure_default_versao_link`, `_save_matriz_activity_links`) intocado.
  - `UNIQUE(atividade_base_id, numero_versao)` intacta.
  - Schema e `database.db` não alterados.
  - Push não realizado.
- Validation:
  - focados A (`readonly`, `version_form`, `matriz_link`): 52 passed.
  - focados B (`escolher_versao`, `latest_active_default`, `version_visibility_ui`): 38 passed.
  - suíte completa em lotes: batchSize=20, 66 arquivos, 4 lotes — 522 passed, 0 failed, 0 errors.
  - Artifacts CSRF restaurados via `git restore` antes do commit.
  - `git diff --check`: silencioso.
- Files touched in the functional commit:
  - `main.py` (M)
  - `templates/admin_catalogo_versao_detalhe.html` (M)
  - `templates/admin_catalogo_versao_form.html` (M)
  - `templates/admin_matriz_versoes.html` (M)
  - `tests/test_admin_version_visibility_ui.py` (A — novo)
- Residual risks:
  - warning LF→CRLF no Windows (comportamento git padrão, sem impacto funcional).
  - menu hover-only de Admin → Atividades permanece como possível polish futuro.
- Next authorized step: D7.7C3 — verificação final pré-push e push, se explicitamente autorizado.

## Recent Commits

- `95cb897` - Add admin transition history for activity versions
- `cbde400` - Record D7.3A normative canonization
- `5f66239` - Add D7.3C canonical normative fixture and docs closeout
- `45dd39d` - Add D7.3D normative dry-run importer
- `f10db80` - Record D7.3E fixture database convergence diagnostic
- `da869e9` - Record D7.3F reconciliation matrix decisions
- `ecdc9f5` - Add D7.3H controlled reconciliation apply script
- `aedf936` - Record D7.3I apply copy validation
- `b8ad2ae` - Record D7.3J live draft creation and stabilize tests
- `b5aafa7` - Record D7.3K matrix link decision
- `6a9bf2d` - Update CSRF inventory artifacts after D7 merge (pre-D7.5C main baseline)
- `bc8a4f6` - Add matrix-scoped activity creation
- `cdbc7ab` - Record D7.5C matrix activity creation closeout
- `0dbd2b1` - Add matrix card version creation
- `3d3c4ff` - Record D7.5D matrix card version closeout
- `1ca00a3` - Add operational activity version numbers
- `5184143` - D7.6B2-R1: fix numero_versao DEFAULT 0 -> DEFAULT 1 in atividade_versao
- `6b1579a` - D7.6B2-R2: harden numero_versao schema — full unique index + pos triggers
- `62aed4b` - Add activity version menu to admin activities
- `ed706c1` - Record D7.6C activity version menu closeout
- `2f81179` - Make matrix choose operational activity versions
- `79e11a2` - Record D7.6D matrix version selection closeout
- `e359047` - Default matrix links to latest active activity versions
- `088da75` - Record D7.6E latest active version default closeout
- `bdd5ddc` - Fix legacy seeds and scripts for D7.6B2 UNIQUE(base,numero_versao) constraint
- `d72f985` - Record D7.6G full suite remediation closeout
- `01aaa0f` - Fix D7.6G handoff current HEAD
- `d53d9cd` - Harden matrix version selection validity
- `99f4659` - Show operational version numbers in admin version UI

## Risks To Keep In View

- Critical:
  - overwriting versions already used in matrix or versioned requests;
  - reconciling `PROJETOS_EXTENSAO` without preserving the live split.
- High:
  - mapping `VISITAS_TECNICAS_PROFESSORES` to `base6`;
  - changing `NRM-RT` runtime items;
  - promoting the dry-run importer into a real apply path.
- High:
  - broadening beyond the single completed `CREATE_DRAFT` path for `VISITAS_TECNICAS_PROFESSORES`;
  - activating or matrix-linking versions `61/62` without a separate authorization phase.
- Medium:
  - structural divergences in group / workload / limits;
  - fixture does not cover all persisted transition history.
- Low:
  - textual divergences when IDs and persisted history are preserved.
- Residual backlog:
  - `documentacao_exigida` is only validated when the key exists in the fixture tool;
  - `atividade_transicao` still has no DB-level UNIQUE on `(from, to, tipo)`.

## Recommended Next Step

- D7.7C3 — final verify and push — executed successfully. Baseline published at `5c6859b`.
- D7.7C4 — post-push documentation sync — docs-only; baseline functional published remains `5c6859b`.
- D8.0A — read-only audit pós-D7 — aprovada; baseline D8 autorizado.
- D8.0B — baseline suite + backup — concluída (docs-only commit, ver abaixo).
  - Suíte: 522 passed, 0 failed, 4 warnings em 470.91s — execução única, sem OOM.
  - Artifacts CSRF restaurados ao estado HEAD; não commitados.
  - `database.db`: 544.768 bytes, SHA256 `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`.
  - Backup verificado: `D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.0B-baseline-20260614-140824.db`
    SHA256 idêntico; não versionado; não entrou no Git.
  - HEAD base: `3cb28c8`. origin/main...main: 0 0.
- Próxima etapa recomendada: **D8.1A — READONLY-ALUNO-REQUISICOES-VERSIONED-CUTOVER-PLAN**.
  - Planejar (somente leitura) como conectar `aluno_nova_requisicao` ao snapshot writer.
  - Avaliar cutover da flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` para o fluxo do aluno.
  - Mapear telas do aluno que precisarão exibir versão operacional (`vN`, `observacao_aluno`).
  - Definir testes mínimos: `tests/test_aluno_requisicao_versionada.py`.
- D8.1B — display read-only do snapshot versionado para o aluno — aprovada
  funcionalmente. Commit `1b34b55` aceito.
  - 6 passed (D8.1B) + 32 passed (regressão dirigida) + 528 passed (suíte completa), 0 failed, 0 errors.
  - `database.db`: 544.768 bytes, SHA256 `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6` — inalterado.
  - Ressalva aceita: commit já existia localmente antes da validação; backup
    específico não foi criado pois o backup D8.0B já cobre o estado do banco,
    que permaneceu com hash idêntico.
- Próxima etapa recomendada: **D8.1D — final verify and push**.
- Não reabrir D7.7B1 sem novo bug concreto.
- Não reabrir D7.7C1 sem novo bug concreto.
- Não reabrir D7.6 sem novo bug concreto.
- Não ignorar a exceção de escopo de artifacts CSRF documentada em D7.6G2.
- Não reabrir D7.7C3 — push já executado e validado.
- Não iniciar D8.1 sem plano read-only aprovado.
- Não ligar flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` sem novo backup do live.
- Não alterar deferimento admin sem teste específico.
- Não alterar `database.db` sem autorização explícita.
- Não reabrir D8.1B sem novo bug concreto.
- Não ligar flag de write (`SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE`) sem nova fase explícita.
- Não recalcular snapshot em edição do aluno.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Start from `main`; D7.5C functional state is commit `bc8a4f6`.
- Treat `atividade_id` as the operational source of truth.
- `database.db` is already in the post-D7.3J state; do not assume pre-apply live.
- There is no active feature branch for D7 on the remote. Any new work must start
  from `main` at `6a9bf2d`. Do not reference or attempt to push to
  `recovery/d7-activity-versioning`.
- The archive tag `archive/d7-activity-versioning` at `b5aafa7` is the permanent
  reference to the D7 trail endpoint — treat it as read-only history.
- Local branch `recovery/d7-activity-versioning` may still exist as `[gone]` and
  should be treated as a stale local ref only; do not work from it.
- Do not attempt any additional real import, reconciliation write, or importer `apply` against `database.db`.
- `PROJETOS_EXTENSAO` is no longer open for semantic collapse: preserve the live split.
- `VISITAS_TECNICAS_PROFESSORES` must not be mapped to `base6`.
- `VISITAS_TECNICAS_PROFESSORES` must not be forced into `base7` either.
- The only admitted live write path in D7.3 was the now-completed `CREATE_DRAFT` for `VISITAS_TECNICAS_PROFESSORES`.
- Versions `61/62` already exist in `rascunho` and remain unlinked to matrix.
- D7.5C is complete and visually validated; do not reopen it unless a concrete
  regression is found.
- D7.5D is complete (commit `0dbd2b1`); do not reopen it unless a concrete
  regression is found.
- D7.6B2 is complete (commits `1ca00a3`, `5184143`, `6b1579a`); schema is hardened; do not reopen.
- `atividade_versao.numero_versao` is the operational version number (v1/v2/v3… per base).
- `codigo_normativo` is normative metadata; do not use it as a badge or operational identifier.
- `UNIQUE(atividade_base_id, norma_id)` no longer exists; do not reference or recreate it.
- `UNIQUE(atividade_base_id, numero_versao)` is the active uniqueness constraint (full index, no WHERE).
- All INSERTs into `atividade_versao` must supply `numero_versao` via `get_next_numero_versao`.
- Do not insert `numero_versao <= 0`; it is blocked by triggers and by CHECK in new DB DDL.
- `norma_id` and `codigo_normativo` remain `NOT NULL` in this phase.
- D7.6C is complete (commit `62aed4b`):
  - `/admin/atividades` now exposes a ⋮ menu on hover with Editar / Criar nova versão / Ver versões.
  - `base_id` is resolved via `atividade_legacy_map` subquery in the activities query.
  - Activities without `base_id` do not generate invalid links.
  - No matrix templates were changed; no schema was changed.
- D7.6D is complete (commit `2f81179`):
  - Card da matriz exibe badge `vN` via `atividade_versao.numero_versao`.
  - Modal lista versões existentes da mesma `atividade_base`; versão atual pré-selecionada.
  - POST relinka via `_set_versao_da_matriz_para_base`; não cria `atividade_versao`.
  - POST valida `versao_id` pertencente à mesma `atividade_base`; rejeita cross-base e inexistentes.
  - `templates/admin_atividades.html` não alterado. Schema e `database.db` intocados.
  - `tests/test_admin_matriz_escolher_versao.py` (novo, 10 testes) e `tests/test_admin_matriz_nova_versao_card.py` (atualizado, 13 testes) aceitos.
- D7.6E is complete (commit `e359047`):
  - Novo vínculo matriz→atividade_base usa automaticamente a última versão ativa.
  - `_ensure_default_versao_link`: resolve `base_id`, verifica link existente, obtém última ativa, cria link via `_set_versao_da_matriz_para_base`.
  - Vínculo manual existente preservado (no-op se link já existe para a base).
  - Caso sem versão ativa: nenhum link criado.
  - `main.py` (M) e `tests/test_admin_matriz_latest_active_default.py` (A, 9 testes) aceitos.
  - Regressões 74/74 passed.
- D7.6G2 is complete (commit `bdd5ddc`): suíte completa 503/0 verde; exceção de escopo aceita para artifacts CSRF deterministicamente gerados.
  - Não reabrir D7.6G2 — todas as 52 falhas corrigidas e auditadas em D7.6G2-R1 e R2.
  - Artifacts CSRF (`tests/_artifacts/csrf_inventory_shadow_off.json`, `csrf_inventory_shadow_on.json`) entram como exceção de escopo documentada; `blocked_real_risk=0`; `high_risk_routes=0`.
- D7.7B1 is complete (commit `d53d9cd`): modal, POST e default de versão agora respeitam `status='ativa'` e `matriz_norma`; `_save_matriz_activity_links` limpa vínculos explícitos órfãos; 512 passed, 0 failed.
  - `get_card_version_menu_data` filtra `versoes` por `ativa + norma_id IN matriz_norma`.
  - `admin_matriz_nova_versao_card` rejeita versão não ativa ou com norma fora de `matriz_norma`.
  - `_ensure_default_versao_link` usa query inline com JOIN em `matriz_norma`; sem fallback para norma fora da matriz.
  - `_save_matriz_activity_links` remove vínculos explícitos órfãos scoped por `activity_type` do tab corrente.
  - Não reabrir D7.7B1 sem novo bug concreto.
- D7.7C1 is complete (commit `99f4659`): `vN` agora exibido no catálogo de versões (`admin_catalogo_versao_detalhe.html`), nos formulários de criação/edição (`admin_catalogo_versao_form.html`) e na tela de versões da matriz (`admin_matriz_versoes.html`).
  - `codigo_normativo` permanece metadado normativo em todas as telas; não foi substituído por `vN`.
  - Backend D7.7B intocado: `get_card_version_menu_data`, `_ensure_default_versao_link`, `_save_matriz_activity_links` e `admin_matriz_nova_versao_card` inalterados.
  - Novo teste `tests/test_admin_version_visibility_ui.py` aceito.
  - Suíte completa em lotes: 522 passed, 0 failed.
  - Não reabrir D7.7C1 sem novo bug concreto.
- Contrato permanente pós-D7.7B1:
  - Admin → Atividades cria versão; Matriz escolhe versão existente (apenas ativas, norma na matriz).
  - Novo vínculo usa última versão ativa dentro de `matriz_norma` por padrão; escolha manual é respeitada.
  - Card da matriz mostra `vN`; `codigo_normativo` é metadado normativo, não badge principal.
  - `UNIQUE(atividade_base_id, numero_versao)` ativa; `UNIQUE(atividade_base_id, norma_id)` removida — não restaurar.
  - Todos os INSERTs em `atividade_versao` devem fornecer `numero_versao` via `get_next_numero_versao` ou equivalente.
  - Não reintroduzir criação de versão pela matriz como fluxo principal.
  - Não alterar schema sem nova auditoria.
  - Não fazer push sem ordem explícita.
- Runtime `NRM-RT*` items remain outside fixture reconciliation.
- Never overwrite versions already used in matrix or versioned requests.
- No next agent should activate, matrix-link, remap legacy scope, or perform any additional live apply without a new explicit authorization phase and real operational need.
- Continuous prohibited scope (D7 — não desfazer sem nova fase explícita):
  - alterar contratos publicados da Matriz → Versões;
  - alterar `resolver_versao_por_matriz` / `resolver_versao_por_aluno` / `resolver_versao`;
  - alterar schema ou rodar migrations sem nova fase;
  - executar backfill/cutover sem autorização;
  - introduzir fallback silencioso;
  - fazer push sem ordem explícita.
- D8.1A quando autorizada: escopo permitido será leitura e planejamento do fluxo
  `aluno_nova_requisicao` → snapshot writer → telas do aluno.
  Não executar nenhum write sem nova fase D8.1B explícita.
- `database.db` baseline D8: 544.768 bytes,
  SHA256 `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`.
- D8.3A — COPY-DB-WRITE-FLAG-SMOKE — executada e aprovada (docs em
  `docs/d8_3_copy_db_write_flag_smoke_result.md`).
  - HEAD esperado antes do closeout: `27e6f23`.
  - `origin/main...main` antes: `0 0`.
  - Resultado do smoke:
    - WRITE ON em cópia isolada passou (caso válido, guard de edição e caso
      skip todos aprovados);
    - live `database.db` inalterado (SHA256 idêntico antes/depois,
      `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`);
    - sem alteração de código, sem commit, sem push na D8.3A.
  - O que NÃO fazer:
    - não ligar a flag em ambiente live;
    - não alterar `.env`;
    - não substituir `database.db` pela cópia do smoke;
    - não iniciar cutover real;
    - não criar novo fix de handoff só para perseguir o hash deste closeout
      docs-only.
  - Próxima etapa: D8.3C — final verify and push do closeout documental;
    depois, D8.4A apenas se houver autorização explícita.
  Backup em `D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.0B-baseline-20260614-140824.db`.

## REF-0C-A — RBAC policy matrix diagnosis (CLOSED / ACCEPTED)

- REF-0C-A / REF-0C-A-R1 is **CLOSED / ACCEPTED** at accepted diagnosis HEAD `f977fd6`.
- Accepted matrix counts: HIGH 21, MEDIUM 3, LOW 0.
- R22-R24 remain unresolved normative diagnostic-policy decisions. No policy has been selected for these routes.
- No RBAC implementation has started. Modularization remains prohibited.

### Next Authorized Phase: REF-0C-B1 — Strongly Supported RBAC Mappings and Denial Tests

- Explicitly limited to the 21 HIGH-confidence route-method combinations (R1–R19, R21).
- R22, R23, and R24 are explicitly excluded from implementation until their diagnostic access policy is approved.
- For R20, only the central `matrizes`/`edit` RBAC mapping and its tests are authorized. Changing or removing the local `readonly` behavior is not authorized.
- Do not claim that R22–R24 have a selected policy.
- Do not authorize fail-closed global enforcement, UI changes, schema changes, database changes, or modularization.

### Instructions For The Next Agent (REF-0C-B1)
- Read `docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md` as the primary input.
- The 21 HIGH-confidence routes in the diagnosis document define the normative target: each route–method pair must return a specific `resource:scope` tuple from `get_admin_permission_requirement`.
- The 3 MEDIUM-confidence routes (R22, R23, R24) require explicit diagnostic access-policy decision before implementation. Do not proceed with those routes in REF-0C-B1.
- Do not modify `rbac_unmapped_routes_baseline.json` — it characterizes preexisting debt and its target state is empty list. Do not regenerate or delete it without explicit authorization.
- Do not modify `route_inventory_baseline.json` — it is the frozen URL->endpoint contract.
- The D8.x trail (student-facing versioned snapshot display, write flag smoke, cleanup) remains independent and can proceed in parallel if separately authorized.
- RBAC correction and route modularization remain prohibited in all phases without explicit authorization.
- This closeout does not authorize fail-closed global enforcement, UI changes, schema changes, database changes, or modularization.
## REF-0C-B2-A — supervisor decision closeout (CLOSED / ACCEPTED)

- Accepted decision commit: `a9d375d` (`Document diagnostic RBAC and R20 policy options`).
- Authorized next scope is only REF-0C-B2 R22–R24: R22/R23 GET → `atividades`/`view` → `admin_total`, `administrativo`, `consultivo`; R24 GET → `banco_dados`/`view` → `admin_total` only. Aluno and anonymous remain denied by `@admin_required`.
- R22 and R23 must resolve identically. R24's restriction intentionally protects paths, environment values, tracebacks, and operational identifiers from administrativo and consultivo.
- R20 `readonly` remains unchanged; central `matrizes`/`edit` enforcement is authoritative. No R20 cleanup, global fail-closed gate, UI, schema, database, dependency, or modularization change is authorized.
- REF-0C-C remains unauthorized. Implement and validate the bounded R22–R24 mappings, then request ChatGPT supervisor review; do not claim REF-0C-B2 accepted.
- REF-0C-B2 implementation is locally validated and pending ChatGPT supervisor review: R22/R23 GET → `atividades`/`view` ({admin_total, administrativo, consultivo}); R24 GET → `banco_dados`/`view` ({admin_total}); the dynamic debt baseline is empty. R20 remains unchanged, and REF-0C-C/global fail-closed work remains prohibited. Final detached-worktree suite evidence is pending closeout.
- Full detached-worktree validation for REF-0C-B2: `577 passed`, `17` D73H deselected, zero failures/errors/skips/xfails/xpasses, exit `0`; selected-test delta `+15`. The temporary worktree is to be removed after evidence closeout. Next action: ChatGPT supervisor review; do not claim acceptance or begin R20/REF-0C-C.
- REF-0C-B2 implementation commit: current `HEAD` (`Implement REF-0C-B2 diagnostic RBAC mappings`); decision closeout commit: `ed1803f` (`Close REF-0C-B2-A after supervisor decision`).
- Worktree cleanup exception: its Git registration was removed, but environment policy blocked deletion of the empty temporary directory `C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0c-b2-full-validation`; no production data was copied there. A local user may delete it.
## REF-0C-B2-C — supervisor acceptance (CLOSED / ACCEPTED)

- Accepted phase chain: `a9d375d` → `ed1803f` → `c9e1843`; current technical HEAD `c9e1843`; divergence before this closeout `0 14`.
- Policies: R22/R23 GET → `atividades`/`view` → `admin_total`, `administrativo`, `consultivo`; R24 GET → `banco_dados`/`view` → `admin_total` only; aluno/anonymous retain outer authentication denial.
- Debt baseline: zero remaining route-method combinations. Suite: `577 passed`, `17` D73H deselected. R20 readonly unchanged; no global fail-closed gate.
- Prohibitions: no main.py, app/auth.py, tests, baseline, R20, UI, schema, database, dependency, or modularization changes; no push.
- Next candidate: `REF-0C-C-A — FAIL-CLOSED AUTHORIZATION GATE DIAGNOSIS`, **NOT STARTED / NOT YET AUTHORIZED FOR IMPLEMENTATION**. Next action: ChatGPT supervisor issuance of a read-only REF-0C-C-A diagnosis order.
## REF-0C-C-A — Fail-Closed Authorization Gate Diagnosis (2026-07-18)

- Branch / starting HEAD: `refactor/architecture-safety-net` / `042288a`; accepted predecessor chain is `a9d375d → ed1803f → c9e1843 → 042288a`.
- Status: completed locally, documentation-only, **pending ChatGPT supervisor review**. Changed files: `docs/refactor/REF_0C_C_A_FAIL_CLOSED_AUTHORIZATION_GATE_DIAGNOSIS.md`, `PROJECT_STATE.md`, and this file only.
- Complete reads: canonical state/handoff, auth, coverage/B1/B2/conftest/baseline/pytest config, and REF-0C-A/B1-P0/B2-A/B2 documents. Relevant routing, blueprints, hooks, core/aluno views, presets API, errors, static/upload/health behavior inspected.
- Dynamic route inventory: 131 rules, 130 endpoints, 160 business combinations; 109 `/admin` endpoints / 131 `/admin` combinations, all explicitly mapped; unmapped baseline empty. Three non-prefix administrative callbacks (`auth_callback`, `google_callback`, `onedrive_callback`) map to `banco_dados/edit`.
- Recommendation: Option E hybrid. Govern resolved `/admin` rules plus the exact external callback registry. Normalize HEAD to GET; exempt automatic OPTIONS only; require mapping XOR approved endpoint+method exemption. No explicit admin exemptions exist now. Preserve endpoint-None, 404, and 405 framework behavior.
- Missing governed mapping recommendation: production generic browser 403 / AJAX JSON 403 configuration error with safe structured event; development/test dedicated configuration failure. Existing mapped scope transport and anonymous/aluno decorator behavior stay unchanged.
- Risks: endpoint rename, newly permitted method, shared handler, dynamic/late blueprint registration, HEAD/OPTIONS, AJAX expectation, stale inventory, and B1-P0 transaction hygiene. Rollout is characterization → registry → bounded shadow → dev/test hard failure → production; preferred rollback is release rollback, not permanent allow-open switch.
- Read-only validation: coverage+B1+B1-P0 `40 passed`; B2 `18 passed`; combined `58 passed`, all exit 0. No real database or production log access.
- Prohibitions remain: no REF-0C-C implementation, R20 cleanup, UI/schema/database/dependency/modularization work, baseline changes, push, or runtime bypass.
- Next action: ChatGPT supervisor review and user architectural decision on boundary, production transport, observability owner, rollback policy, and late-registration contract. Recommended later implementation model/effort: Claude Sonnet, High (or GPT-5.6 Sol, High) after explicit authorization.

## REF-0C-C-A supervisor acceptance closeout (2026-07-18)

- REF-0C-C-A is **CLOSED / ACCEPTED**. Accepted diagnosis commit: `020cd7f` (`Document fail-closed authorization gate diagnosis`).
- Approved design: resolved `/admin` rule boundary plus exact non-prefix governed callbacks `auth_callback`, `google_callback`, and `onedrive_callback`; requirement XOR approved endpoint+method exemption; HEAD inherits GET; automatic OPTIONS is framework-exempt; endpoint-None, 404, and 405 remain Flask behavior.
- Staged rollout is approved: REF-0C-C-B1 implements the hybrid registry, production shadow audit, and hard testing/development configuration failure only. Production hard enforcement remains prohibited and no permanent allow-open switch is authorized.
- R20 remains unchanged. UI, schema, database, dependency, and modularization work remain prohibited. Next action after B1: ChatGPT supervisor review.

## REF-0C-C-B1 — Hybrid boundary and shadow gate (2026-07-18)

- REF-0C-C-A is CLOSED / ACCEPTED; diagnosis `020cd7f`, closeout commit `9453aa2`. REF-0C-C-B1 is implemented locally, pending ChatGPT supervisor review.
- Changed implementation scope: `app/auth.py`, `main.py`, `tests/test_ref_0c_c_b1_fail_closed_shadow_gate.py`, B1 implementation document, PROJECT_STATE, and this handoff only. Existing tests/baselines were not weakened or regenerated.
- Classifier: resolved `/admin` rule or exact GET callback registry (`auth_callback`, `google_callback`, `onedrive_callback`); requirement XOR exemption. No exemptions exist. HEAD→GET; automatic OPTIONS exempt; explicit OPTIONS mapped/exempt; endpoint-None/404/405 remain Flask behavior.
- Runtime: testing/development missing configuration raises a distinct error before access-context/database load. Production emits one safe event (`endpoint`, normalized method, rule template, existing access level, rollout mode) and continues current behavior; no production hard denial and no permanent allow-open flag.
- Focused new test result: `23 passed in 11.47s`, exit 0; combined required focused set: `81 passed`, exit 0. Fresh detached worktree `C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0c-c-b1-full-validation` full hermetic suite: `600 passed, 17 deselected in 427.00s`, exit 0 (`+23` selected tests); temporary worktree/output removed.
- R20, UI, schema/database, dependency, and modularization remain prohibited. Next action: ChatGPT supervisor review. Recommended review/correction model: Claude Opus High (GPT-5.6 Sol High alternative).
