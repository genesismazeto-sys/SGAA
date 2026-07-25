# Architecture Refactor Ledger

## Phase table

| Phase | Objective | Status | Technical commit | Closeout commit | Test baseline | Contract | Residual risk |
|-------|-----------|--------|-----------------|-----------------|---------------|----------|---------------|
| REF-0A | Create refactor branch without application changes | ACCEPTED | N/A | NO SEPARATE COMMIT | N/A | No standalone contract; `340fc7c` is branch-starting architecture-map baseline only | None |
| REF-0ENV | Rebuild local `.venv` with Python 3.11.15 | ACCEPTED | N/A (env only) | NO SEPARATE COMMIT | 42 passed (focused) | No standalone contract | None |
| REF-0B | Route contract and RBAC debt characterization | ACCEPTED | `f2b1cfc` | NO SEPARATE COMMIT | 8 passed existing focused baseline; 3 passed new contract tests; 42 passed required regression baseline | No standalone contract | RBAC debt uncorrected by design |
| REF-0T | Isolated full-suite baseline and test isolation audit | ACCEPTED | `c440297` | NO SEPARATE COMMIT | 537 collected, 519 passed, 18 failed (baseline) | No standalone contract | NO-GO for REF-0C-A until failures classified |
| REF-0TF | Full-suite failure classification | ACCEPTED | `722b7a7` | NO SEPARATE COMMIT | 537 collected, 519 passed, 18 failed | `docs/refactor/REF_0TF_FAILURE_CLASSIFICATION.md` | Cluster A time-decaying; Cluster B non-hermetic |
| REF-0TF-A | Progress calendar contract hardening | ACCEPTED | `e111cd5` | `d8dab45` (state-reconciliation) | 538 collected, 521 passed, 17 failed | `docs/refactor/REF_0TF_A_PROGRESS_CALENDAR_CONTRACT.md` | None |
| REF-0TF-B | D73H historical verification isolation | ACCEPTED | `9b47c37` | NO SEPARATE COMMIT | 521 passed, 17 deselected | `docs/refactor/REF_0TF_B_D73H_HISTORICAL_VERIFICATION_ISOLATION.md` | Historical lane still requires sanitized artifacts |
| REF-0C-A | RBAC policy matrix diagnosis (24-row) | CLOSED / ACCEPTED | `f977fd6` | `c8acd07` | 521 passed, 17 deselected | `docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md` | R22-R24 unresolved diagnostic policy |
| REF-0C-A-R1 | REF-0C-A refinement (within same phase) | CLOSED / ACCEPTED | `f977fd6` | `c8acd07` | Same as REF-0C-A | No standalone contract; same as REF-0C-A | R22-R24 unresolved |
| REF-0C-B1-P0 | Admin access-context transaction hygiene | CLOSED / ACCEPTED | `92b25d2` | `5fb4276` (acceptance closeout) | 5 passed focused; inherited full 562 passed, 17 deselected | `docs/refactor/REF_0C_B1_P0_ACCESS_CONTEXT_TRANSACTION_HYGIENE.md` | None |
| REF-0C-B1 | 21 HIGH-confidence RBAC mappings + denial tests | CLOSED / ACCEPTED | `932c6d7` | `5fb4276` | 562 passed, 17 deselected | Contract documented in REF-0C-A diagnosis; B1-P0 supports the mapping | R22-R24 remain unmapped; R20 readonly unchanged |
| REF-0C-B2-A | R22-R24 diagnostic access policy decision | CLOSED / ACCEPTED | `a9d375d` | `ed1803f` | 577 passed, 17 deselected | `docs/refactor/REF_0C_B2_A_DIAGNOSTIC_ACCESS_POLICY_DECISION.md` | None |
| REF-0C-B2 | Implement R22-R24 diagnostic RBAC mappings | CLOSED / ACCEPTED | `c9e1843` | `042288a` | 577 passed, 17 deselected | `docs/refactor/REF_0C_B2_DIAGNOSTIC_RBAC_IMPLEMENTATION.md` | R20 local readonly unchanged |
| REF-0C-C-A | Fail-closed authorization gate diagnosis | CLOSED / ACCEPTED | `020cd7f` | `9453aa2` | 577 passed, 17 deselected | `docs/refactor/REF_0C_C_A_FAIL_CLOSED_AUTHORIZATION_GATE_DIAGNOSIS.md` | Production hard enforcement not authorized |
| REF-0C-C-B1 | Hybrid boundary, shadow audit, test/dev hard failure | CLOSED / ACCEPTED | `fb90cc1` | `128b2ce` | 600 passed, 17 deselected (23 C-B1 tests) | `docs/refactor/REF_0C_C_B1_FAIL_CLOSED_SHADOW_GATE_IMPLEMENTATION.md` | Logger failure can lose one shadow audit event |
| REF-0C-C-B1-R1 | Shadow audit logger failure safety correction | CLOSED / ACCEPTED | `39f7732` | `128b2ce` | 601 passed, 17 deselected (+1 R1 regression over C-B1) | `docs/refactor/REF_0C_C_B1_FAIL_CLOSED_SHADOW_GATE_IMPLEMENTATION.md` | Residual: one lost shadow event acceptable |
| REF-0C-D | Formalize actor matrix and immutability-after-denial tests for all admin routes | **SATISFIED** | `fe0ce87a3838fd14691b3d7c006bfe6864b9371f` (REF-0C-D-R1 technical commit) | This acceptance closeout commit | 634 passed, 17 deselected, 0 failed, 0 errors; focused 33 passed | Original scope: `docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md` section 20. Satisfied by REF-0C-D-R1. | None |
| REF-0C-D-R1 | Route-complete actor decision and pre-handler denied-action immutability coverage | **CLOSED / ACCEPTED** | `fe0ce87a3838fd14691b3d7c006bfe6864b9371f`; subject `Make CSRF snapshot validation hermetic` | This acceptance closeout commit | 634 passed, 17 deselected, 0 failed, 0 errors in 380.15s; focused 33 passed in 19.93s | `docs/refactor/REF_0C_D_R1_ROUTE_COMPLETE_ACTOR_IMMUTABILITY.md` | None; test-only, no production change |
| PHASE-0-R9A | Isolate every pytest runtime output from preexisting workspace directories before smoke execution | **CLOSED / ACCEPTED** | Isolate pytest runtime from workspace directories | Same commit | Focused 15 passed; collection 649/666 with 17 D73H deselected; regressions 23 passed; full suite 649 passed, 17 deselected in 441.22s; canonical manifests unchanged | No standalone contract; `tests/test_pytest_runtime_isolation.py`, `PROJECT_STATE.md`, and this ledger are canonical evidence | Pytest private `_inicache` compatibility; three older temp roots left untouched due unproven provenance |
| PHASE-0-R9 | Implement five fixture-controlled hermetic smoke flows (admin login, aluno login, create requisicao, process requisicao, local backup) | **CLOSED / ACCEPTED** | `df24639faa4b18d5aad429940a82982b4beeab98` | Accepted via R10 docs-only external acceptance closeout; closeout records evidence and transition | Smoke 5 passed in 5.99s; full suite 654 passed, 17 deselected in 298.82s, exit 0, 0 failures, 0 errors; R9-R2 aggregate invariant hash e3d10dc; database.db 544768 bytes SHA-256 a3a55e... unchanged | `docs/refactor/PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.md` | None residual; all Phase-0 requirements satisfied |
| Macro Fase 0 | Safety net: route inventory, RBAC coverage, hermetic suite, actor matrix, fail-closed, smoke flows | **CLOSED / ACCEPTED** | `df24639faa4b18d5aad429940a82982b4beeab98` | R10 docs-only acceptance closeout | 654 passed, 17 deselected, 0 failures, 0 errors; all Phase-0 requirements satisfied and externally accepted | `docs/mapeamento/05_avaliacao_refactor.md` | None. Macro Phase 0 is canonically CLOSED / ACCEPTED. |
| PHASE-1-U1 | Remove accidental tracked VS Code workspace artifact | **CLOSED / ACCEPTED** | `68f52fb902c726cc79ff92955e58f95ac0b21cd7`; subject `Remove accidental VS Code workspace artifact` | R14 docs-only external acceptance closeout | 654 passed, 17 deselected, 0 failed, 0 errors, D73H executed 0; focused gate 7 passed; runtime-isolation nodes 2 passed; aggregate invariant e4bee85... pre/post identical | `docs/mapeamento/05_avaliacao_refactor.md` | None |
| PHASE-1-U2 | Delete KRThinkpad parallel template | CLOSED / ACCEPTED | `5932dff2d6dbd63e4a1f52ffd649ea33577535d0`; subject `Remove obsolete machine-specific turma template` | R16 authorized subject `Record acceptance of Phase 1 U2`; documentary commit identity resolved through Git history | Deleted path admin_turmas-KRThinkpad.html; blob SHA-1 96ae0698; 2114 bytes; raw SHA-256 01f32a5d; catalog SHA-256 ae408075; 0 key/usage delta; 73 inputs; 536 keys; runtime-isolation 2 passed; focused 45 passed; full 654 passed 17 deselected; invariant a485690d pre/post identical | `docs/mapeamento/05_avaliacao_refactor.md` | None |
| PHASE-1-U3 | Remove legacy aluno route bodies | CLOSED / ACCEPTED | `c4fd2dd1852011a0ec860493ed4cf53834584c42`; subject `Remove legacy aluno route bodies` | R19 docs-only external acceptance closeout; documentary commit identity resolved through Git history | Removed symbols: _noop_route, aluno_runtime_route, aluno_arquivos, aluno_minhas_requisicoes, aluno_requisicao_detalhe, aluno_dashboard, aluno_nova_requisicao, aluno_meus_dados; main.py delta 0 insertions 756 deletions; 8 compatibility exports preserved; Flask rules 131 unchanged; catalog keys 536 unchanged; CSRF snapshots regenerated as coherent pair; focused lane 47 passed; full suite 657 passed 17 deselected 0 failed 0 errors; invariant aggregate unchanged | `docs/mapeamento/05_avaliacao_refactor.md` | None |
| PHASE-1-U4 | Remove unused main imports + correct hashlib comment | CLOSED / ACCEPTED | `742b67c0623bdf41e292280a11a40d2fddad717c`; subject `Remove unused main imports` | R22 authorized subject `Record acceptance of Phase 1 U4`; documentary commit identity resolved through Git history | PHASE-1-U4: CLOSED/ACCEPTED; U4 read-only proof: CLOSED/ACCEPTED; U4-B bounded implementation: CLOSED/ACCEPTED. Removed imports: wraps (functools), Flask (flask), bp_presets (presets_api); hashlib preserved with corrected comment; msal probe preserved; main.py delta 2 insertions 4 deletions; AST confirmed only those 3 bindings removed; indirect consumers zero; import-time PASS; SQLite connections during import zero; test_aluno_compat_exports 3 passed; route inventory + RBAC coverage 3 passed; full suite 657 passed 17 deselected 0 failed 0 errors; D73H executed 0; snapshots regenerated: 0. R21 routing: flash_free→flash_normal; cause FALLBACK_FREE_EXECUTION_FAILURE; effective opencode-go/deepseek-v4-flash; session ses_0699201ebffep2uXFswB6iotIf; cost 0.000425292; fallback explicit | `docs/mapeamento/05_avaliacao_refactor.md` | None |
| PHASE-1-U5 | Remove stale diagnostic output | CLOSED / ACCEPTED | `8b55230314605dcf9295072c109f04bea59323c3`; subject `Remove stale diagnostic output` | R25 authorized subject `Record acceptance of Phase 1 U5`; documentary commit identity resolved through Git history | PHASE-1-U5: CLOSED/ACCEPTED; U5 read-only reconciliation: CLOSED/ACCEPTED; U5-B bounded implementation: CLOSED/ACCEPTED. Sole path tools/diag_out.txt; blob SHA-1 45f5fc833364e9d2bc49132b4a0f6a0b045be74e; 11746 bytes; raw SHA-256 f5e027ea7748b4246f224545e399b9014f74a5536e867bbe47e0b65eafcc534b; no functional consumer; focused gate 15 passed; full suite 657 passed 17 deselected 0 failed 0 errors; D73H executed 0; snapshots regenerated 0; protected databases and sidecars unchanged; no canonical database opened; publication incident BLOCKED_PUSH_TIMEOUT→PUBLICATION_COMPLETE | `docs/mapeamento/05_avaliacao_refactor.md` | None |
| PHASE-1-U6 | Read-only Phase-1 completion assessment and residual-custody disposition boundary | CLOSED / ACCEPTED | N/A (read-only, no technical commit) | R27 docs-only closeout; authorizing subject identity resolved through Git history | Read-only assessment; zero implementation, no tests, no technical commit; confirmed no other safe cleanup bounded candidate with material evidence | `docs/mapeamento/05_avaliacao_refactor.md` | None; U6 was read-only without physical mutation |
| Fase 1 | Safe cleanup: dead code, lixo, headers | CLOSED / ACCEPTED | U1 `68f52fb`, U2 `5932dff`, U3 `c4fd2dd`, U4 `742b67c`, U5 `8b55230` | R27 docs-only closeout | U1-U6 CLOSED / ACCEPTED; PHASE1_CLOSABLE_WITH_SEPARATE_CUSTODY_TRACK; U6 confirmed no other safe cleanup bounded candidate with material evidence; Phase 1 leaves no partial technical implementation; snapshots not a mandatory technical closeout criterion; custody transferred without physical action to autonomous administrative track | `docs/mapeamento/05_avaliacao_refactor.md` | Residual: historical database snapshot custody transferred to separate governance track — OPEN / POLICY APPROVED / CANONICAL_DESTINATION_UNRESOLVED / PHYSICAL ACTION NOT AUTHORIZED |
| HISTORICAL-DATABASE-SNAPSHOT-CUSTODY | Administrative/governance track for 17 historical snapshot artifacts | OPEN / POLICY APPROVED / CANONICAL_DESTINATION_SELECTED / PROVISIONING_AND_COPY_CONTRACT_APPROVED / DESTINATION NOT YET PROVISIONED / PHYSICAL EXECUTION NOT AUTHORIZED AT THIS TIME | N/A (no physical mutation authorized) | docs-only approved provisioning and copy contract closeout | R1, R2 and R3 CLOSED / ACCEPTED. Custody policy: APPROVED. Custody model: SHARED. Retention: INDEFINITE. Destination class: EXTERNAL CANONICAL CUSTODY LOCATION — DEDICATED DIRECTORY OUTSIDE REPOSITORY AND ONEDRIVE. Human-selected canonical destination: `D:\programas\SGAA_Historical_Custody`. Destination status: SELECTED. Provisioning status: SELECTED / PARENT PATH NOT YET PROVISIONED. Physical volume: SAME VOLUME AS SOURCE WORKSPACE — D:; logical separation, not independent-disk redundancy. Gates 0–6 ratified documentally, none executed. R3 read-only assessment completed and its contract APPROVED by human decision on 25/07/2026: layout `artifacts\`/`manifests\`/`evidence\`; executor `KR-IDEAPAD\klebe`; ACL with inheritance disabled and `Authenticated Users` plus `BUILTIN\Users` removed; copy-only with explicit 17-path list and overwrite disabled; custody manifest JSON without credentials, SQLite content or PII; partial residue preserved until explicit cleanup decision; provisional Level 2 environment `D:\tmp\sgaa_restore_<UTC>` while `CONTAINER_RUNTIME_NOT_AVAILABLE` holds. Physical execution: NOT AUTHORIZED AT THIS TIME. Does not integrate Phase 1, Phase 2 or any architectural implementation phase. See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` | `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` | OPEN / POLICY APPROVED / CANONICAL_DESTINATION_SELECTED / PROVISIONING_AND_COPY_CONTRACT_APPROVED / DESTINATION NOT YET PROVISIONED / PHYSICAL EXECUTION NOT AUTHORIZED AT THIS TIME. Policy approved via R1; destination selected via R2; contract approved via R3. No mutation authorized. R4 next (controlled provisioning, ACL, copy, manifest and verification), blocked on a separate explicit human order releasing physical execution |
| Fase 2 | Shared helpers extraction | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized; requires explicit supervisor order |
| Fase 3 | Data access consolidation | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized |
| Fase 4 | Admin blueprint extraction | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized |
| Fase 5 | Backup/sync offloading | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized |
| Fase 6 | `main.py` as entrypoint only | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized |

## Historical / superseded governance event — CANONICAL-GOV-R1

Its phase-time states about Phase 0, REF-0C-D-R1 and Fase 1 are historical record superseded by current canon/R27.

**Objective:** Establish documentation index, architecture phase ledger,
Phase-0 completion matrix and REF-0C-D decision.

**Implementation/documentation commit:**
`ce90db579137d5cb0075c5f7a525c02062e982b0`.

**Status: CLOSED / ACCEPTED** after external supervisor direct GitHub inspection.

**Tests not run:** documentation-only.

**Evidence:** Exact five-document GitHub manifest:
- `docs/DOCUMENTATION_INDEX.md` — added, ACCEPTED
- `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` — added, ACCEPTED
- `docs/mapeamento/05_avaliacao_refactor.md` — modified, ACCEPTED
- `PROJECT_STATE.md` — modified, ACCEPTED
- `AGENT_HANDOFF.md` — modified, ACCEPTED

**Residual state:** Phase 0 remains open with REF-0C-D-R1 and smoke-flow
contract/evidence. REF-0C-D-R1, Fase 1, and production hard enforcement remain
not authorized.

## Historical / superseded governance event — R25

Its Phase-1-OPEN and U6-NOT-STARTED residual states are phase-time history superseded by R27.

**Objective:** Record acceptance of PHASE-1-U5 — remove stale diagnostic output (`tools/diag_out.txt`).

**Objective type:** docs-only external acceptance closeout.

**Closeout identity:** authorized subject `Record acceptance of Phase 1 U5`; documentary commit identity resolved through Git history.

**Status: CLOSED / ACCEPTED.**

**Tests:** NOT RUN (PROHIBITED); relied on pre-existing staging-lane evidence.

**Accepted technical commit:** `8b55230314605dcf9295072c109f04bea59323c3` — `Remove stale diagnostic output`.

**Evidence:** Removed `tools/diag_out.txt` (11,746 bytes, SHA-1 `45f5fc833364e9d2bc49132b4a0f6a0b045be74e`, SHA-256 `f5e027ea7748b4246f224545e399b9014f74a5536e867bbe47e0b65eafcc534b`). Focused isolation gate: 15 passed. Full suite: 657 passed, 17 deselected, zero failures/errors. D73H executed zero. Snapshots regenerated zero. No code, tests, database, or behavior changed.

**Files changed (this closeout only):** `AGENT_HANDOFF.md`, `PROJECT_STATE.md`, `docs/DOCUMENTATION_INDEX.md`, `docs/mapeamento/04_arquitetura_e_modulos.md`, `docs/mapeamento/05_avaliacao_refactor.md`, `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`.

**Residual state:** Phase 1 remains OPEN / IN PROGRESS. Snapshot custody: CUSTODY_DECISION_REQUIRED. All identified safe technical candidates executed. Next authorized action: PHASE-1-U6 (NOT STARTED). Phases 2–6 remain unauthorized.

## REF-0C-D formal decision

**Decision: SATISFIED**

REF-0C-D-R1 closed the route-complete gap: test-only, fixture-controlled, parametrized actor matrix and immutability-after-denial coverage was implemented from canonical route inventory/classifier. After external acceptance, **REF-0C-D is SATISFIED**.

Repository evidence (for audit trail):
- Complete route mapping (`test_route_inventory_snapshot.py`)
- Complete governed-boundary classification (`test_ref_0c_c_b1_fail_closed_shadow_gate.py` + `classify_governed_admin_request`)
- Actor HTTP and denied-mutation tests were **representative** for R1-R24 before REF-0C-D-R1, not **route-complete** for every governed admin business route-method pair

The original gap (closed by REF-0C-D-R1): REF-0C-D required formalized actor matrix and immutability-after-denial tests for **all** admin routes. B1/B2 tests covered representative routes per (resource, scope) group but did not parametrically prove allow/deny for every route-method-actor combination.

**Closed invariant:** Route-complete actor decision and pre-handler denied-action immutability coverage over every current governed admin business route-method pair and every denied admin access level derived from the canonical resource/scope model.

**Affected set** (now covered): Every governed admin business route-method pair from `tests/_artifacts/route_inventory_baseline.json` where `classify_governed_admin_request(..., method)["governed"]` is True and `get_admin_permission_requirement(endpoint, method)` returns a non-None `(resource, scope)`, crossed with admin access levels `admin_total`, `administrativo`, `consultivo` whose effective scope does not satisfy the requirement, **excluding** only combinations already directly covered by accepted HTTP denial tests. Anonymous and aluno outer-auth behavior is already accepted but is not the missing invariant — the gap was admin-level actor matrix completeness, not outer-auth boundary.

**Closed by:** REF-0C-D-R1. Tests were test-only, fixture-controlled, parametrized from the canonical route inventory and classifier, proving expected allow/deny at the permission layer for every access level, proving each denied combination returns the central browser/AJAX contract before handler execution, and proving no fixture domain mutation. Prohibited: production code, UI, schema, dependencies, production hard enforcement, R20 cleanup, route changes, and Fases 1–6.

## Macro Fase 0 formal decision

**Decision: CLOSED / ACCEPTED**

All Phase-0 safety-net requirements are satisfied. The smoke-flow contract/evidence
was accepted by the external supervisor at technical commit
`df24639faa4b18d5aad429940a82982b4beeab98`. Accepted evidence: route inventory;
RBAC coverage; actor x route x method matrix; denied-action immutability;
fail-closed development/shadow production contract; hermetic pytest runtime;
hermetic CSRF snapshots; five fixture-controlled smoke flows; full suite 654
passed, 17 D73H deselected, 0 failures, 0 errors. R10 documents this acceptance
closeout. R10 is a docs-only acceptance closeout; its eventual commit identity is
resolved through Git history. **R10 contract status:** The pre-acceptance status text in Section 10 of the immutable R9 contract is a historical snapshot, superseded by this R10 current canon; the contract is not modified in R10.

## Authorized state

**Architecture refactor Phase 1: CLOSED / ACCEPTED.**
- **PHASE-1-U1:** CLOSED / ACCEPTED at `68f52fb902c726cc79ff92955e58f95ac0b21cd7`.
- **PHASE-1-U2:** CLOSED / ACCEPTED at `5932dff2d6dbd63e4a1f52ffd649ea33577535d0`.
- **PHASE-1-U3:** CLOSED / ACCEPTED at `c4fd2dd1852011a0ec860493ed4cf53834584c42`.
- **PHASE-1-U4:** CLOSED / ACCEPTED at `742b67c0623bdf41e292280a11a40d2fddad717c`. U4 read-only proof: CLOSED / ACCEPTED. U4-B bounded implementation: CLOSED / ACCEPTED.
- **PHASE-1-U5:** CLOSED / ACCEPTED at `8b55230314605dcf9295072c109f04bea59323c3`. U5 read-only reconciliation: CLOSED / ACCEPTED. U5-B bounded implementation: CLOSED / ACCEPTED. Removed tools/diag_out.txt — stale diagnostic artifact, 11,746 bytes, no functional consumer.
- **PHASE-1-U6:** CLOSED / ACCEPTED. Read-only, no implementation, no tests, no technical commit.
- **Classification: PHASE1_CLOSABLE_WITH_SEPARATE_CUSTODY_TRACK.**
  U6 confirmed no other safe cleanup bounded candidate has material evidence.
  Phase 1 leaves no partial technical implementation.
  Snapshots are not a mandatory technical closeout criterion.
  Custody transferred without physical action to autonomous administrative track.

**Historical snapshot custody: OPEN / CANONICAL_DESTINATION_UNRESOLVED.**
R1: CLOSED / ACCEPTED. Custody policy: APPROVED. Specific destination: UNRESOLVED.
Physical action: NOT AUTHORIZED.
Separate governance/administrative track. Does not integrate Phase 1, Phase 2,
or any architectural implementation phase.
See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.

Exact next action:

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R2 — read-only canonical destination
requirements and controlled-copy contract boundary.

R2 is NOT STARTED, requires a separate explicit order and is not authorized
for physical mutation.

Future R2 objectives: define objective destination requirements; evaluate real
available options; select specific destination by human decision; draft copy
contract; define disposable restoration environment; define Level 2 and Level 3
gates. R2 will not execute a copy. Phase 2 remains without authorized next action.

Explicitly prohibited without separate authorization: route extraction;
blueprint restructuring; database consolidation; behavior changes; schema/migrations;
RBAC; UI; dependencies; production hard enforcement.

Production shadow-only remains in force; production hard enforcement
unauthorized. D73H historical lane unchanged; R20 unchanged. Do not claim a final
commit SHA or successful push before they exist; no self-referential follow-up commit.

## Governance event — R27

**Objective:** Close PHASE-1-U6 and Phase 1; establish snapshot custody track.

**Objective type:** docs-only phase closeout and governance-track establishment.

**Closeout identity:** authorized subject `Close Phase 1 and establish snapshot custody track`; identity resolved through Git history.

**Status: CLOSED / ACCEPTED.**

**Tests:** NOT RUN / PROHIBITED.

**Baseline/pre-closeout HEAD:** `8a895ce93bfc9e38a8ee29d28d24a715caf49ccc`.

**Classification:** PHASE1_CLOSABLE_WITH_SEPARATE_CUSTODY_TRACK.
**Exact eight-document manifest:**
- `AGENT_HANDOFF.md`
- `PROJECT_STATE.md`
- `docs/DOCUMENTATION_INDEX.md`
- `docs/mapeamento/03_banco_de_dados.md`
- `docs/mapeamento/04_arquitetura_e_modulos.md`
- `docs/mapeamento/05_avaliacao_refactor.md`
- `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
- `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`

**Zero code/test/SQLite mutation:** physical action NOT AUTHORIZED. Phase 2–6 NOT AUTHORIZED. Production shadow-only unchanged. R20/D73H unchanged.

Exact next action:

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R1 — read-only custody policy decision
packet and human-authorization boundary.

R1 is NOT STARTED, requires a separate explicit order and is not authorized
for physical mutation.

Future R1 objectives (not decided now): retention alternatives; custodian;
destination options; restoration requirements; integrity proof; request explicit human
decision. Phase 2 remains without authorized next action.

## Governance event — R29

**Objective:** Record approved snapshot custody policy; documentary ratification of R1 human decision.

**Objective type:** docs-only human policy ratification.

**Closeout identity:** authorized subject `Record approved snapshot custody policy`; identity resolved through Git history.

**Status: CLOSED / ACCEPTED.**

**Tests:** NOT RUN / PROHIBITED.

**R28 (preceding read-only custody policy decision packet):** Read-only completed. Human decision: CLOSED / ACCEPTED. Policy approved. Specific destination: UNRESOLVED. Physical action: NOT AUTHORIZED.

**R29 actions:**
- R1 recorded as CLOSED / ACCEPTED.
- Historical / superseded classification: CUSTODY_POLICY_UNRESOLVED. Active classification: CANONICAL_DESTINATION_UNRESOLVED.
- Custody policy: APPROVED. Model: SHARED. Retention: INDEFINITE.
- Destination class: EXTERNAL CANONICAL CUSTODY LOCATION. Specific destination: NOT YET SELECTED.
- Acceptance gate: RESTORE LEVEL 2 — SCHEMA AND METADATA.
- Gate before source removal: RESTORE LEVEL 3 — OPERATIONAL RESTORATION.
- First future physical action: COPY ONLY. Move: NOT AUTHORIZED. Delete: NOT AUTHORIZED. Compress: NOT AUTHORIZED YET.
- Source after copy: MUST REMAIN INTACT.
- Technical operator: EXECUTES ONLY EXPLICITLY AUTHORIZED ACTIONS.
- Zero physical mutation, zero code/test/SQLite change.
- Phase 2–6 remain NOT AUTHORIZED. Production shadow-only unchanged. R20/D73H unchanged.

Exact next action (phase-time, superseded by R31):

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R2 — read-only canonical destination
requirements and controlled-copy contract boundary.

R2 is NOT STARTED, requires a separate explicit order and is not authorized
for physical mutation.

Future R2 objectives: define objective destination requirements; evaluate real
available options; select specific destination by human decision; draft copy
contract; define disposable restoration environment; define Level 2 and Level 3
gates. R2 will not execute a copy. Phase 2 remains without authorized next action.

## Governance event — R31

**Objective:** Record the human-selected historical custody destination; read-only
destination verification and documentary closeout of HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R2.

**Objective type:** read-only destination verification + docs-only closeout.

**Closeout identity:** authorized subject `Record selected historical custody destination`;
identity resolved through Git history.

**Status: CLOSED / ACCEPTED.**

**Tests:** NOT RUN / PROHIBITED.

**R30 (preceding read-only destination-options packet):** Read-only completed.
Phase-time state `DESTINATION_OPTIONS_READY_AWAITING_HUMAN_SELECTION`, now
SUPERSEDED BY HUMAN SELECTION. Its statement that R2 was NOT STARTED is phase-time
history superseded by this event.

**Binding human decision:**

Human-selected canonical destination:

D:\programas\SGAA_Historical_Custody

Destination: SELECTED. Destination class: DEDICATED DIRECTORY OUTSIDE REPOSITORY AND
ONEDRIVE. Physical volume: SAME VOLUME AS SOURCE WORKSPACE — D:. Physical action:
NOT AUTHORIZED.

**Gate A — read-only destination verification (no creation, no write test, no ACL change):**
- `D:\programas` — DOES NOT EXIST.
- `D:\programas\SGAA_Historical_Custody` — DOES NOT EXIST.
- Provisioning status: SELECTED / PARENT PATH NOT YET PROVISIONED. Not a blocker for
  the R2 documentary closeout and not an authorization to create anything.
- Volume `D:` — NTFS, Fixed, Disk 1 (SAMSUNG MZALQ512HBLU-00BL2, NVMe).
- Free space 497,651,699,712 bytes against 4,808,704 bytes required for the 17 artifacts.
- Outside every SGAA Git worktree; outside the OneDrive tree; outside
  `D:\OneDrive\Programação\SGAA_database_backups`; outside the pytest roots
  (`pytest.ini` declares `testpaths = tests`).
- Zero conflicting files bearing any of the 17 canonical names.
- Apparent read ACL on `D:\` readable; longest projected path 98 characters.
- Source inventory revalidated read-only: 17/17 artifacts present, sizes and SHA-256
  identical to the canonical inventory.

**Storage-domain risk:** the selected destination is outside the repository and outside
the observed OneDrive tree, but it remains on the same physical D: storage domain as the
source workspace. This provides logical separation, not independent-disk redundancy. The
destination must not be represented as redundant, immutable, off-site, independent of the
source disk, versioned, or protected against deletion. A second independent copy may be
discussed in the future and is not part of R2.

**R31 actions:**
- R2 recorded as CLOSED / ACCEPTED; canonical destination recorded as SELECTED.
- Controlled-copy contract Gates 0–6 preserved and ratified documentally; no gate executed.
- Preferred disposable restoration environment recorded as ISOLATED CONTAINER binding only
  a derived disposable copy; the source workspace must not be mounted as the restoration
  database; the custodial artifact must not be opened directly. Preference only — no
  container created, no Docker runtime verified, no volume mounted, no image built.
- Historical / superseded classification extended with CANONICAL_DESTINATION_UNRESOLVED.
- Zero physical mutation: no directory created, no copy, no move, no delete, no compress,
  no SQLite database opened, zero code or test change.
- Physical action, copy, move, delete, compress and SQLite open remain NOT AUTHORIZED.
- Phase 2–6 remain NOT AUTHORIZED. Production shadow-only unchanged. R20/D73H unchanged.

Exact next action (phase-time, superseded by the approved-contract closeout below):

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R3 — read-only provisioning and
copy-execution readiness contract.

R3 is NOT STARTED, requires a separate explicit order and is not authorized
to create the destination or copy, move, delete, compress or open any artifact.

Future R3 objectives: controlled creation of the directory; desired ACL; technical
executor; manifest; exact copy commands; rollback and hard stops; disposable container;
evidence required before requesting physical authorization. R3 is also read-only.
Phase 2 remains without authorized next action.

## Governance event — R31 publication recovery and R3 read-only assessment

**Objective:** publish the existing R31 commit, then produce the read-only provisioning
and copy-execution readiness contract.

**Objective type:** publication recovery + read-only contract assessment. No document
was changed in that round.

**Status: COMPLETE.**

**Tests:** NOT RUN / PROHIBITED. `main.py` not imported. Application not executed.

**Publication:** local commit `59fa66bb5d73a04713524657bdc761def3d0b9c8`
(`Record selected historical custody destination`, parent
`c8c093a14bc6afe932461c00ab6e00774a5d3ac2`, exactly seven documents) published to
`origin/refactor/architecture-safety-net` by
`git push --porcelain origin HEAD:refs/heads/refactor/architecture-safety-net`.
Result `c8c093a..59fa66b`, fast-forward, exit 0, non-forced, not rejected. Post-push:
local HEAD = upstream = live remote; divergence 0/0; `main` unchanged at
`340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`; worktree clean; index empty.
Classification: PUBLICATION_COMPLETE. The earlier BLOCKED_PUSH_TIMEOUT incident recorded
under U5 did not recur.

**R3 read-only evidence:** inventory 17/17 — 9 `.db` + 4 `.db-wal` + 4 `.db-shm`,
4,808,704 bytes, every SHA-256 identical to canon, 17/17 ignored, zero tracked, zero
untracked-not-ignored, 4 complete basename families plus 5 lone `.db`; zero drift.
Destination absent (`D:\programas` and `D:\programas\SGAA_Historical_Custody`), no
resolution to `D:\Programação`, outside every Git worktree, outside OneDrive, outside the
pytest roots (`testpaths = tests`), zero name conflicts. Volume `D:` NTFS Fixed, Disk 1
SAMSUNG MZALQ512HBLU-00BL2 NVMe, free 497,651,490,816 bytes. Longest projected path 108
characters with `LongPathsEnabled = 0`. `D:\` ACL read-only inspected: `ContainerInherit,
ObjectInherit` ACEs grant `Authenticated Users` effective modify, which is why the Gate P2
ACL is mandatory. `CONTAINER_RUNTIME_NOT_AVAILABLE`: `docker` absent from PATH, no install
path present, `com.docker.service` not installed.

**Zero mutation in that round:** no document changed, no commit created, no directory
created, no file created, no write test, no ACL applied, no copy, no move, no compress,
no delete, no SQLite opened, no manifest created, no pytest run.

**Phase-time classification:** `COPY_EXECUTION_CONTRACT_READY_AWAITING_HUMAN_AUTHORIZATION`
— superseded by the human approval recorded in the event below.

## Governance event — approved provisioning and copy contract

**Objective:** record the human approval of the R3 provisioning and copy contract and
close R3.

**Objective type:** docs-only human ratification. No R-number was issued for this event
by the authorizing order; it is identified by objective and by Git history.

**Closeout identity:** authorized subject `Record approved provisioning and copy contract`;
identity resolved through Git history.

**Status: CLOSED / ACCEPTED.**

**Tests:** NOT RUN / PROHIBITED.

**Baseline/pre-closeout HEAD:** `59fa66bb5d73a04713524657bdc761def3d0b9c8`.

**Exact seven-document manifest:**
- `AGENT_HANDOFF.md`
- `PROJECT_STATE.md`
- `docs/DOCUMENTATION_INDEX.md`
- `docs/mapeamento/03_banco_de_dados.md`
- `docs/mapeamento/05_avaliacao_refactor.md`
- `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
- `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`

**Binding human decisions (25/07/2026):**
1. A future separate round is authorized to create `D:\programas` and
   `D:\programas\SGAA_Historical_Custody`.
2. Layout approved: `artifacts\`, `manifests\`, `evidence\`.
3. ACL approved: inheritance disabled on the custodial directory; `Authenticated Users`
   and `BUILTIN\Users` removed; `SYSTEM` and `Administrators` FullControl; executor Modify
   during provisioning and copy; after verification, ReadAndExecute on `artifacts\` and
   Modify on `manifests\` and `evidence\`.
4. Authorized technical executor: `KR-IDEAPAD\klebe`.
5. Custody manifest JSON authorized, without credentials, personal data, SQLite content or
   business data.
6. Partial-copy residue preserved until an explicit human decision. Cleanup and silent
   retry NOT AUTHORIZED.
7. Provisional Level 2 restoration alternative approved: controlled external directory
   `D:\tmp\sgaa_restore_<UTC>` while no container runtime is available.
8. A future separate round is authorized only to provision the directories, apply the ACL,
   copy the 17 artifacts, create the manifest and verify count, sizes and SHA-256.

**Explicitly withheld in the same decision: PHYSICAL EXECUTION.** Move, delete, compress,
SQLite open, restoration execution, source removal and Phase 2–6 remain PROHIBITED.

**Zero physical mutation, zero code/test/SQLite change.** Production shadow-only unchanged.
R20/D73H unchanged.

Exact next action:

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R4 — controlled provisioning, ACL application, copy
of the 17 artifacts, manifest creation and integrity verification.

R4 is NOT STARTED. Its contract is APPROVED, but physical execution was explicitly
withheld. R4 requires a separate explicit human order releasing physical execution; the
approval recorded here is not that order and must never be read as one. Phase 2 remains
without authorized next action.
