# SGAA Documentation Index

## Authority hierarchy

1. **Canonical repository state** — `git` commit/tree facts are the single source
   of truth. Chat memory and unsaved documentation carry zero authority.
2. **This index** — defines the mandatory reading order, documents the authority
   hierarchy, and records closeout rules.
3. **Project state** (`PROJECT_STATE.md`) — authoritative current-state block at
   the top; historical blocks beneath are preserved but superseded by newer
   blocks or phase closeouts.
4. **Master plan** (`docs/mapeamento/05_avaliacao_refactor.md`) — the incremental
   refactor plan; frozen Phase 0–6 decomposition with completion matrix and
   formal decisions.
5. **Architecture refactor ledger** (`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`)
   — normalized table of every refactor phase, commits, status, and residual risk.
6. **Phase contracts** (`docs/refactor/REF_*.md`) — per-phase scope, decisions,
   and closeout evidence. Standalone contracts exist for: REF-0TF, REF-0TF-A,
   REF-0TF-B, REF-0C-A, REF-0C-B1-P0, REF-0C-B2-A, REF-0C-B2, REF-0C-C-A,
   REF-0C-C-B1. No standalone contract exists for REF-0A, REF-0ENV, REF-0B,
   REF-0T, REF-0C-A-R1, or REF-0C-D; their scope is documented in the ledger
   and PROJECT_STATE historical blocks.
7. **Agent handoff** (`AGENT_HANDOFF.md`) — current operational handoff for the
   next executor; the top block is operationally canonical but is **not** a
   substitute for the repository canon.
8. **Supporting evidence** — tests and artifacts under `tests/` (especially
   `tests/_artifacts/`) and tools under `tools/`.
9. **Legacy / historical** — older blocks, superseded contracts, and historical
   architecture snapshots preserved for audit trail; they do not govern current
   work.

## Mandatory reading order (first time on this branch)

1. `docs/DOCUMENTATION_INDEX.md` — this file.
2. `docs/mapeamento/README.md` — top-level map index.
3. `docs/mapeamento/05_avaliacao_refactor.md` — master plan, Phase 0–6.
4. `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` — phase ledger.
5. `PROJECT_STATE.md` — canonical current state (top block).
6. `AGENT_HANDOFF.md` — current operational handoff.
7. All `docs/refactor/REF_*.md` / `docs/refactor/PHASE_0_*.md` files in dependency order: REF-0TF →
   REF-0TF-A → REF-0TF-B → REF-0C-A → REF-0C-B1-P0 → REF-0C-B1 →
   REF-0C-B2-A → REF-0C-B2 → REF-0C-C-A → REF-0C-C-B1 → REF-0C-D-R1 →
   PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.

## Canonical current state (2026-07-24)

- Branch: `refactor/architecture-safety-net`
- Accepted technical commit: `5932dff2d6dbd63e4a1f52ffd649ea33577535d0` — `Remove obsolete machine-specific turma template`
- **PHASE-0-R9A pytest runtime isolation:** CLOSED / ACCEPTED
- **PHASE-0-R9 smoke-flow contract and evidence:** CLOSED / ACCEPTED via R10 docs-only external acceptance closeout
- R9 evidence: `tests/test_phase_0_smoke_flows.py` (new, 5 tests); contract: `docs/refactor/PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.md`
- Accepted full hermetic test suite: **654 passed, 17 deselected, 0 failures, 0 errors**
- Production: shadow-only (no hard enforcement)
- **REF-0C-D-R1: CLOSED / ACCEPTED**
- **REF-0C-D: SATISFIED**
- **Macro Fase 0: CLOSED / ACCEPTED** — all Phase-0 safety-net requirements satisfied
- **Accepted evidence:** route inventory; RBAC coverage; actor x route x method matrix; denied-action immutability; fail-closed development/shadow production contract; hermetic pytest runtime; hermetic CSRF snapshots; five fixture-controlled smoke flows; full suite 654 passed, 17 D73H deselected, 0 failures, 0 errors.
- **PHASE-1-U1: CLOSED / ACCEPTED** — removed `templates/src.code-workspace-1.code-workspace` at commit `68f52fb`.
- **PHASE-1-U2: CLOSED / ACCEPTED** — deleted `templates/admin_turmas-KRThinkpad.html` at commit `5932dff2d6dbd63e4a1f52ffd649ea33577535d0`.
- **Phase 1:** OPEN / IN PROGRESS.
- **Exact next technical action:** PHASE-1-U3 — focused read-only proof of legacy/no-op aluno route bodies and `aluno_runtime_route`. REQUIRES SEPARATE ORDER. No mutation. Future-proof scope: determine all legacy aluno functions involved; rebind behavior at end of main.py; route and endpoint neutrality; message-catalog effects caused by `aluno_runtime_route` decorators; import and compatibility-export consumers; exact safe deletion boundary if any.
- Explicitly prohibited without separate authorization: route extraction; blueprint restructuring; database consolidation; behavior changes; schema/migrations; RBAC; UI; dependencies; production hard enforcement.
- Production shadow-only: **in force**; production hard enforcement: **unauthorized**
- D73H historical lane: **unchanged**
- R20: **unchanged**
- **R10 is docs-only acceptance closeout; its eventual commit identity is resolved through Git history.**
- **R10 contract status:** The pre-acceptance status text in Section 10 of the immutable R9 contract is a historical snapshot, superseded by this R10 current canon; the contract is not modified in R10.

## Master plan (Phase 0–6)

Defined in `docs/mapeamento/05_avaliacao_refactor.md`:

- **Macro Fase 0 — Safety net (rede de segurança)**: route inventory, RBAC
  coverage, hermetic suite, smoke flows, actor matrix, fail-closed design.
  **CLOSED / ACCEPTED — all requirements satisfied.**
- **Fase 1 — Safe cleanup**: dead code, lixo, headers. **OPEN / IN PROGRESS.**
  - **PHASE-1-U1 (accidental VS Code workspace artifact): CLOSED / ACCEPTED.**
  - **PHASE-1-U2 (KRThinkpad parallel template): CLOSED / ACCEPTED.**
  - **PHASE-1-U3 (legacy aluno routes and `aluno_runtime_route`): NOT STARTED / REQUIRES SEPARATE ORDER.**
- **Fase 2 — Shared helpers**: extract from `main.py`, break cycle.
- **Fase 3 — Data access consolidation**: unify `init_db`, migrate `ensure_*`.
- **Fase 4 — Blueprint extraction**: one admin blueprint per domain.
- **Fase 5 — Backup/sync offloading**: background jobs.
- **Fase 6 — `main.py` as entrypoint only**: ~50–150 lines.

Phase 1 is OPEN / IN PROGRESS. Only U1 and U2 are CLOSED / ACCEPTED. No other Phase-1 cleanup unit is implemented or accepted. U3 is NOT STARTED / REQUIRES SEPARATE ORDER. Phases 2–6 remain **unauthorized**.

## Ledger

See `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` for the complete normalized
table of every phase.

## Architecture contracts (phase documents in `docs/refactor/`)

| File | Phase | Scope |
|------|-------|-------|
| `REF_0TF_FAILURE_CLASSIFICATION.md` | REF-0TF | Full-suite failure classification |
| `REF_0TF_A_PROGRESS_CALENDAR_CONTRACT.md` | REF-0TF-A | Calendar test hardening |
| `REF_0TF_B_D73H_HISTORICAL_VERIFICATION_ISOLATION.md` | REF-0TF-B | D73H isolation |
| `REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md` | REF-0C-A | 24-row RBAC matrix (contains REF-0C-D original scope at section 20) |
| `REF_0C_B1_P0_ACCESS_CONTEXT_TRANSACTION_HYGIENE.md` | REF-0C-B1-P0 | Transaction ownership fix |
| `REF_0C_B2_A_DIAGNOSTIC_ACCESS_POLICY_DECISION.md` | REF-0C-B2-A | R22-R24 diagnostic policy |
| `REF_0C_B2_DIAGNOSTIC_RBAC_IMPLEMENTATION.md` | REF-0C-B2 | R22-R24 implementation |
| `REF_0C_C_A_FAIL_CLOSED_AUTHORIZATION_GATE_DIAGNOSIS.md` | REF-0C-C-A | Fail-closed gate design |
| `REF_0C_C_B1_FAIL_CLOSED_SHADOW_GATE_IMPLEMENTATION.md` | REF-0C-C-B1 | Shadow gate + hard test/dev failure |
| `REF_0C_D_R1_ROUTE_COMPLETE_ACTOR_IMMUTABILITY.md` | REF-0C-D-R1 | Route-complete actor matrix + browser/AJAX denial contracts |
| `PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.md` | PHASE-0-R9 | Five smoke flows (admin/aluno login, create/process requisicao, local backup) |

Phases without standalone contracts: REF-0A, REF-0ENV, REF-0B, REF-0T,
REF-0C-A-R1. See the ledger and `PROJECT_STATE.md` historical blocks.

## Phase contracts

Each existing `REF_*` document in `docs/refactor/` is a phase contract for that
phase. A standalone contract now exists for REF-0C-D-R1:
`docs/refactor/REF_0C_D_R1_ROUTE_COMPLETE_ACTOR_IMMUTABILITY.md`.
The original REF-0C-D scope was documented in
`docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md` section 20.

## Supporting evidence

| Evidence | Location | Status |
|----------|----------|--------|
| Route inventory snapshot | `tests/test_route_inventory_snapshot.py` + `tests/_artifacts/route_inventory_baseline.json` | SATISFIED |
| RBAC requirement coverage | `tests/test_rbac_requirement_coverage.py` + `tests/_artifacts/rbac_unmapped_routes_baseline.json` | SATISFIED |
| B1 high-confidence RBAC mappings | `tests/test_ref_0c_b1_rbac_high_confidence_mappings.py` (36 tests) | SATISFIED |
| P0 transaction hygiene | `tests/test_ref_0c_b1_p0_access_context_transactions.py` (5 tests) | SATISFIED |
| B2 diagnostic RBAC | `tests/test_ref_0c_b2_diagnostic_rbac.py` (18 tests) | SATISFIED |
| C-B1 shadow gate | `tests/test_ref_0c_c_b1_fail_closed_shadow_gate.py` (23 tests pre-R1, plus R1 regression test) | SATISFIED |
| D-R1 route-complete actor matrix | `tests/test_ref_0c_d_r1_route_complete_actor_matrix.py` | CLOSED / ACCEPTED |
| R9A pytest runtime isolation | `tests/test_pytest_runtime_isolation.py` + session-owned `tests/conftest.py` runtime root | CLOSED / ACCEPTED |
| R9 smoke flows | `tests/test_phase_0_smoke_flows.py` (5 tests) + `docs/refactor/PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.md` | CLOSED / ACCEPTED via R10 |
| Hermetic full suite (R9) | 654 passed, 17 deselected, 0 failures, 0 errors | CLOSED / ACCEPTED |
| Smoke tools | `tools/smoke_test.py`, `tools/smoke_test_admin.py`, `tools/smoke_test_rbac_permissions.py` | SUPERSEDED_BY_R9 |

## Architecture mapping snapshots (`docs/mapeamento/`)

`docs/mapeamento/README.md` indexes all seven files. The following files are
historical snapshots generated from the state of `main` (2026-06-21) and
predate all REF-0 refactoring phases. They have **not** been revalidated after
the accepted REF-0 changes and may not reflect the current branch state:

- `docs/mapeamento/01_rotas.md` — historical route map (pre-REF-0)
- `docs/mapeamento/02_autenticacao_e_seguranca.md` — historical auth/security
  snapshot (pre-REF-0C-B1, pre-REF-0C-C-B1)

## Legacy / historical

- Older blocks in `PROJECT_STATE.md` and `AGENT_HANDOFF.md` below the current
  authoritative block are historical phase records. They are preserved for audit
  trail but do not govern current work.
- Superseded phase decisions are recorded in their respective closeout documents
  and the ledger. No content is deleted or compacted.

## Superseded docs

No documentation is explicitly superseded; phase contracts are additive.
The ledger records each phase's closeout. When a later phase amends a prior
finding, the later phase document and the ledger supersede the earlier claim.

## Closeout rules

1. Every phase contract must document its starting HEAD, ending decision, and
   changed files.
2. No phase may claim a SATISFIED status for a requirement that lacks
   repository evidence.
3. Closeout decisions are recorded in `PROJECT_STATE.md` and the ledger.
4. Only the supervisor or a documented decision may close or accept a phase.
5. Production hard enforcement, Fase 1–6 work, and route changes are not
   authorized unless a phase contract explicitly permits them.

## GitHub branch/HEAD verification

Before any phase execution:
- Verify branch is `refactor/architecture-safety-net`.
- Verify HEAD matches the expected starting commit.
- Verify worktree and index are clean.
- Verify divergence from `origin/refactor/architecture-safety-net` is `0 0`.
- Re-prove these invariants before any edit.

## Explicit rule

**Chat memory, agent handoff notes, and unsaved documentation are not
substitutes for repository canon.** Every authoritative fact must exist in a
committed file. This index, the ledger, `PROJECT_STATE.md`, and `AGENT_HANDOFF.md`
are the canonical entry points.
