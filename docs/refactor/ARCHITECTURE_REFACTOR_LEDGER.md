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
| PHASE-0-R9 | Implement five fixture-controlled hermetic smoke flows (admin login, aluno login, create requisicao, process requisicao, local backup) | **IMPLEMENTED / LOCALLY VALIDATED** | `c978ed7` (parent); new file `tests/test_phase_0_smoke_flows.py` | Evidence is owned by `docs/refactor/PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.md` and `tests/test_phase_0_smoke_flows.py`. Commit identity is resolved through Git history; no self-referential follow-up commit is required. | Smoke 5 passed in 5.99s; full suite 654 passed, 17 deselected in 298.82s, exit 0; R9-R2 aggregate invariant hash e3d10dc (includes five frozen dirty files, canonical database/root manifests, three preexisting temp-root manifests/set, Git status, empty staging); database.db 544768 bytes SHA-256 a3a55e... unchanged | `docs/refactor/PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.md` | Smoke flows depend on stable routes; fixture patches app.config/module globals |
| Macro Fase 0 | Safety net: route inventory, RBAC coverage, hermetic suite, actor matrix, fail-closed, smoke flows | **LOCALLY SATISFIED / AWAITING EXTERNAL SUPERVISOR ACCEPTANCE** | See individual rows | See individual rows | 654 passed, 17 deselected in 298.82s; all Phase-0 requirements met locally | `docs/mapeamento/05_avaliacao_refactor.md` | No further Phase-0 work remains locally. Final bounded remainder (smoke flows) defined and proven. Awaiting external supervisor acceptance. |
| Fase 1 | Safe cleanup: dead code, lixo, headers | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized; requires explicit supervisor order |
| Fase 2 | Shared helpers extraction | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized; requires explicit supervisor order |
| Fase 3 | Data access consolidation | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized |
| Fase 4 | Admin blueprint extraction | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized |
| Fase 5 | Backup/sync offloading | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized |
| Fase 6 | `main.py` as entrypoint only | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized |

## Governance event — CANONICAL-GOV-R1

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

**Decision: LOCALLY SATISFIED / AWAITING EXTERNAL SUPERVISOR ACCEPTANCE**

The final bounded remainder — smoke-flow contract/evidence — is now defined in
`tests/test_phase_0_smoke_flows.py` and proven by `654 passed, 17 deselected in
298.82s`, exit 0, D73H executed 0 (smoke 5 passed in 5.99s). No further Phase-0 work remains locally.

All prior Phase-0 requirements (route inventory, RBAC coverage, hermetic suite,
actor matrix, fail-closed design, runtime isolation, smoke flows) are locally
satisfied. Phase 0 must not be claimed as CLOSED or ACCEPTED before external
supervisor acceptance.

## Next authorizable action

**EXTERNAL SUPERVISOR REVIEW OF THE R9 COMMIT ONLY.** R9A is CLOSED / ACCEPTED.
R9 (smoke-flow contract/evidence) is IMPLEMENTED / LOCALLY VALIDATED / PENDING
EXTERNAL ACCEPTANCE. Fase 1
and production hard enforcement remain unauthorized. Production shadow-only
remains in force. D73H historical lane (17 deselected, 0 executed) and R20 are
unchanged. Do not claim a final commit SHA or successful push before they exist;
no self-referential follow-up commit.
