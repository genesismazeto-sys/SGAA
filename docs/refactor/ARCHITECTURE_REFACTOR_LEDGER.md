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
| REF-0C-D | Formalize actor matrix and immutability-after-denial tests for all admin routes | **PARTIALLY_SATISFIED_REMAINDER_REQUIRED** | N/A (documentation + decision only) | N/A | N/A (decision only; tests not implemented) | Original scope: `docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md` section 20. No standalone contract. | Actor HTTP and denied-mutation coverage is representative (R1-R24 sample), not route-complete for every governed admin business route-method pair × every denied access level |
| REF-0C-D-R1 | Route-complete actor decision and pre-handler denied-action immutability coverage | **IMPLEMENTED / LOCALLY VALIDATED / AWAITING EXTERNAL SUPERVISOR REVIEW** | `ccb1b926a0a612dae9f7b253231c285dd97a2a32` (starting); subject `Make CSRF snapshot validation hermetic` (this commit) | N/A (external acceptance pending) | 634 passed, 17 deselected, 0 failed, 0 errors in 380.15s; focused 33 passed in 19.93s | `docs/refactor/REF_0C_D_R1_ROUTE_COMPLETE_ACTOR_IMMUTABILITY.md` | Test-only; external acceptance pending; scope expansion or production change requires hard-stop |
| Macro Fase 0 | Safety net: route inventory, RBAC coverage, hermetic suite, actor matrix, fail-closed | **PHASE_0_REMAINS_OPEN_WITH_BOUNDED_REMAINDER** | See individual REF-0* rows | See individual REF-0* rows | See individual REF-0* rows; full suite 634 passed, 17 deselected, 0 failed, 0 errors in 380.15s | `docs/mapeamento/05_avaliacao_refactor.md` | Exactly two bounded remainders: REF-0C-D-R1 pending external acceptance, and smoke-flow contract/evidence |
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

**Decision: B. PARTIALLY_SATISFIED_REMAINDER_REQUIRED**

Repository evidence confirms:
- Complete route mapping (`test_route_inventory_snapshot.py`)
- Complete governed-boundary classification (`test_ref_0c_c_b1_fail_closed_shadow_gate.py` + `classify_governed_admin_request`)
- Actor HTTP and denied-mutation tests are **representative** for R1-R24, not **route-complete** for every governed admin business route-method pair

The verified gap: REF-0C-D requires formalized actor matrix and immutability-after-denial tests for **all** admin routes. Current B1/B2 tests cover representative routes per (resource, scope) group but do not parametrically prove allow/deny for every route-method-actor combination.

**Missing invariant:** Route-complete actor decision and pre-handler denied-action immutability coverage over every current governed admin business route-method pair and every denied admin access level derived from the canonical resource/scope model.

**Affected set (exact by rule):** Every governed admin business route-method pair from `tests/_artifacts/route_inventory_baseline.json` where `classify_governed_admin_request(..., method)["governed"]` is True and `get_admin_permission_requirement(endpoint, method)` returns a non-None `(resource, scope)`, crossed with admin access levels `admin_total`, `administrativo`, `consultivo` whose effective scope does not satisfy the requirement, **excluding** only combinations already directly covered by accepted HTTP denial tests. Anonymous and aluno outer-auth behavior is already accepted but is not the missing invariant — the gap is admin-level actor matrix completeness, not outer-auth boundary.

**Bounded proposed phase:** REF-0C-D-R1. Tests must be test-only, fixture-controlled, parametrized from the canonical route inventory and classifier, prove expected allow/deny at the permission layer for every access level, prove each denied combination returns the central browser/AJAX contract before handler execution, and prove no fixture domain mutation. Prohibited: production code, UI, schema, dependencies, production hard enforcement, R20 cleanup, route changes, and Fases 1–6.

**REF-0C-D remains PARTIALLY_SATISFIED_REMAINDER_REQUIRED** pending external acceptance of REF-0C-D-R1.

## Macro Fase 0 formal decision

**Decision: PHASE_0_REMAINS_OPEN_WITH_BOUNDED_REMAINDER**

Exactly two bounded remainders recorded:
1. **REF-0C-D-R1** — route-complete actor and immutability coverage, pending external acceptance (not satisfied until accepted)
2. **Smoke-flow contract/evidence** — a frozen manual smoke-flow list for admin login, aluno login, create requisicao, process requisicao, and backup is required by the Phase-0 master plan but not yet defined or proven in the repository

The remainder smoke-flow requirement does not block REF-0C-D-R1. They are independent.

## Next authorizable action

**REF-0C-D-R1 now implemented and pending external supervisor acceptance.** Fase 1 and production hard enforcement remain unauthorized. Smoke-flow contract/evidence remains a bounded remainder of Macro Fase 0. **REF-0C-D remains PARTIALLY_SATISFIED_REMAINDER_REQUIRED** (not satisfied by REF-0C-D-R1 until external acceptance).
