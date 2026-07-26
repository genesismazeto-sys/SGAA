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
7. **Historical snapshot custody** (`docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`)
    — autonomous administrative/governance track for the 17 historical database
    snapshot artifacts; R1, R2 and R3 CLOSED / ACCEPTED; **R4 EXECUTED**; **R5 CLOSED / ACCEPTED**
    — destination `D:\programas\SGAA_Historical_Custody` PROVISIONED, 17 artifacts copied
    and verified (4,808,704 bytes), custody manifest and evidence report written, source
    preserved, SQLite never opened; parent-ACL hardening policy approved but not applied;
    security-complete custody NOT YET CLAIMED; does not integrate any architectural
    implementation phase.
8. **Agent handoff** (`AGENT_HANDOFF.md`) — current operational handoff for the
   next executor; the top block is operationally canonical but is **not** a
   substitute for the repository canon.
9. **Supporting evidence** — tests and artifacts under `tests/` (especially
   `tests/_artifacts/`) and tools under `tools/`.
10. **Legacy / historical** — older blocks, superseded contracts, and historical
    architecture snapshots preserved for audit trail; they do not govern current
    work.

## Mandatory reading order (first time on this branch)

1. `docs/DOCUMENTATION_INDEX.md` — this file.
2. `docs/mapeamento/README.md` — top-level map index.
3. `docs/mapeamento/05_avaliacao_refactor.md` — master plan, Phase 0–6.
4. `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` — phase ledger.
5. `PROJECT_STATE.md` — canonical current state (top block).
6. `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` — historical snapshot custody governance track.
7. `AGENT_HANDOFF.md` — current operational handoff.
8. All `docs/refactor/REF_*.md` / `docs/refactor/PHASE_0_*.md` files in dependency order: REF-0TF →
   REF-0TF-A → REF-0TF-B → REF-0C-A → REF-0C-B1-P0 → REF-0C-B1 →
   REF-0C-B2-A → REF-0C-B2 → REF-0C-C-A → REF-0C-C-B1 → REF-0C-D-R1 →
   PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.
## Canonical current state (2026-07-25)

- Branch: `refactor/architecture-safety-net`
- Accepted technical commits: `68f52fb902c726cc79ff92955e58f95ac0b21cd7` (U1), `5932dff2d6dbd63e4a1f52ffd649ea33577535d0` (U2), `c4fd2dd1852011a0ec860493ed4cf53834584c42` (U3), `742b67c0623bdf41e292280a11a40d2fddad717c` (U4), `8b55230314605dcf9295072c109f04bea59323c3` (U5)
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
- **PHASE-1-U3: CLOSED / ACCEPTED** — removed legacy aluno route bodies from main.py at commit `c4fd2dd1852011a0ec860493ed4cf53834584c42`; 0 insertions, 756 deletions; all eight compatibility exports preserved.
- **PHASE-1-U4: CLOSED / ACCEPTED** — U4 read-only proof: CLOSED / ACCEPTED; U4-B bounded implementation: CLOSED / ACCEPTED. Removed unused imports from main.py (wraps, Flask, bp_presets) and corrected hashlib comment at commit `742b67c0623bdf41e292280a11a40d2fddad717c`; 2 insertions, 4 deletions; no behavioral change.
- **PHASE-1-U5: CLOSED / ACCEPTED** — U5 read-only reconciliation: CLOSED / ACCEPTED; U5-B bounded implementation: CLOSED / ACCEPTED. Removed stale diagnostic artifact `tools/diag_out.txt` (11,746 bytes, SHA-1 45f5fc833364e9d2bc49132b4a0f6a0b045be74e, SHA-256 f5e027ea7748b4246f224545e399b9014f74a5536e867bbe47e0b65eafcc534b) at commit `8b55230314605dcf9295072c109f04bea59323c3`. No functional consumer. Focused gate 15 passed; full suite 657 passed, 17 deselected, zero failures/errors; D73H executed zero; snapshots regenerated zero.
- **PHASE-1-U6: CLOSED / ACCEPTED** — read-only Phase-1 completion assessment; zero implementation, no tests, no technical commit, no physical mutation.
- **Phase 1: CLOSED / ACCEPTED.**
  Classification: PHASE1_CLOSABLE_WITH_SEPARATE_CUSTODY_TRACK.
  U6 confirmed no other safe cleanup bounded candidate has material evidence.
  Snapshots are not a mandatory technical closeout criterion.
  Custody transferred without physical action to autonomous administrative track.
- **HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R1: CLOSED / ACCEPTED.**
  Custody policy: APPROVED.
  Physical action: NOT AUTHORIZED.
  Separate governance/administrative track. Does not integrate Phase 1, Phase 2,
  or any architectural implementation phase.
  See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.
- **HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R2: CLOSED / ACCEPTED.**
  R30: DESTINATION_OPTIONS_READY_AWAITING_HUMAN_SELECTION / SUPERSEDED BY HUMAN SELECTION.
  Human-selected canonical destination: `D:\programas\SGAA_Historical_Custody`.
  Destination status: SELECTED.
  Destination class: DEDICATED DIRECTORY OUTSIDE REPOSITORY AND ONEDRIVE.
  Physical volume: SAME VOLUME AS SOURCE WORKSPACE — D:.
  Provisioning status: SELECTED / PARENT PATH NOT YET PROVISIONED.
  Storage-domain risk: outside the repository and outside the observed OneDrive tree,
  but on the same physical D: storage domain as the source workspace — logical
  separation, not independent-disk redundancy; not immutable, not off-site, not
  versioned, not protected against deletion.
  Controlled-copy contract Gates 0–6 ratified documentally; none executed.
  Preferred disposable restoration environment: ISOLATED CONTAINER binding only a
  derived disposable copy; preference only, nothing created or opened.
  Physical action: NOT AUTHORIZED. Copy / Move / Delete / Compress / SQLite open:
  NOT AUTHORIZED.
  See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.
- **HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R3: CLOSED / ACCEPTED.**
  R3 was read-only. Phase-time state `COPY_EXECUTION_CONTRACT_READY_AWAITING_HUMAN_AUTHORIZATION`,
  SUPERSEDED BY HUMAN APPROVAL of 25/07/2026.
  Phase-time classification, superseded by R4: PROVISIONING_AND_COPY_CONTRACT_APPROVED /
  DESTINATION NOT YET PROVISIONED / PHYSICAL EXECUTION NOT AUTHORIZED AT THIS TIME.
  Approved: layout `artifacts\` / `manifests\` / `evidence\`; executor `KR-IDEAPAD\klebe`;
  ACL with inheritance disabled, `Authenticated Users` and `BUILTIN\Users` removed,
  `SYSTEM` and `Administrators` FullControl, executor Modify during provisioning and copy
  then ReadAndExecute on `artifacts\`; copy-only contract with explicit 17-path list and
  overwrite disabled; custody manifest JSON without credentials, SQLite content or PII;
  partial residue preserved until explicit cleanup decision; provisional Level 2
  environment `D:\tmp\sgaa_restore_<UTC>` while `CONTAINER_RUNTIME_NOT_AVAILABLE` holds.
  R31 publication recovery in the same round: `59fa66bb5d73a04713524657bdc761def3d0b9c8`
  published fast-forward; divergence 0/0; `main` unchanged.
  Physical execution, move, delete, compress, SQLite open, restoration execution and
  source removal: NOT AUTHORIZED.
  See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.
- **HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R4: EXECUTED / PHYSICAL PROVISIONING COMPLETE /
  COPY COMPLETE / INTEGRITY VERIFIED / SOURCE PRESERVED.**
  Pre-execution physical authorization: EVIDENCED. Authority: PROJECT OWNER. Scope: R4 ONLY.
  Destination PROVISIONED: `artifacts\` 17 files / 4,808,704 bytes;
  `manifests\custody-manifest-20260725T233026Z.json` (16,872 bytes, SHA-256
  `8552c289…f0c3`); `evidence\r4-copy-and-verification-20260725T233315Z.md` (4,505 bytes,
  SHA-256 `82494024…6d71`). Source aggregate SHA-256 `44ae5da3…3be3` unchanged.
  Per-file destination SHA-256 = source = canon for all 17. SQLite NOT OPENED.
  Restoration Level 2 and Level 3 NOT EXECUTED. Source removal NOT AUTHORIZED.
  Operational nonconformities: DECLARED / CONTAINED / NO ARTIFACT INTEGRITY IMPACT /
  NOT AN AUTHORIZED PRECEDENT — three occurrences recorded in the custody document.
  Residual security risk: PARENT DIRECTORY ACL EXPOSURE OPEN. Security-complete custody:
  NOT YET CLAIMED. The R4 report's `DELETE_CHILD` claim is corrected: the inherited
  `Authenticated Users` mask `0x1301BF` on `D:\programas` does not include
  `FILE_DELETE_CHILD`.
  See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.
- **HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R5: CLOSED / ACCEPTED.**
  R5 was a strict read-only Windows ACL assessment and hardening decision closeout.
  No ACL or physical mutation occurred. Findings: `D:\programas` dedicated to custody;
  inherited Authenticated Users mask `0x001301BF` lacks `FILE_DELETE_CHILD`, `WRITE_DAC`,
  `WRITE_OWNER`. Human approved strict hardening (Option B): disable inheritance, remove
  Authenticated Users and BUILTIN\Users, SYSTEM + Administrators FullControl,
  executor ReadAndExecute. Target SDDL recorded as policy only, NOT applied.
  Current `D:\programas` SDDL remains inherited R4-era. Custody-root ACL unchanged.
  Next: R6 — controlled physical application of approved DACL (NOT AUTHORIZED).
  See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.

Exact next action:

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R6 — controlled physical application and
verification of the approved strict D:\programas DACL.

R6 is NOT STARTED. Its policy is approved, but physical application is NOT AUTHORIZED.
R6 requires a later separate explicit human order restricted to that round. Phase 2
remains without authorized next action; Phases 2-6 remain unauthorized.

Custody remains OPEN and SECURITY-COMPLETE CUSTODY remains NOT YET CLAIMED until the
approved parent DACL is physically applied and verified in a separately authorized
round.

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
- **Fase 1 — Safe cleanup**: dead code, lixo, headers. **CLOSED / ACCEPTED.**
  - **PHASE-1-U1 (accidental VS Code workspace artifact): CLOSED / ACCEPTED.**
  - **PHASE-1-U2 (KRThinkpad parallel template): CLOSED / ACCEPTED.**
  - **PHASE-1-U3 (legacy aluno routes and `aluno_runtime_route`): CLOSED / ACCEPTED.**
  - **PHASE-1-U4 (unused main imports cleanup): CLOSED / ACCEPTED.**
  - **PHASE-1-U5 (stale diagnostic output): CLOSED / ACCEPTED.**
  - **PHASE-1-U6 (Phase-1 completion assessment): CLOSED / ACCEPTED.**
- **Fase 2 — Shared helpers**: extract from `main.py`, break cycle.
- **Fase 3 — Data access consolidation**: unify `init_db`, migrate `ensure_*`.
- **Fase 4 — Blueprint extraction**: one admin blueprint per domain.
- **Fase 5 — Backup/sync offloading**: background jobs.
- **Fase 6 — `main.py` as entrypoint only**: ~50–150 lines.

Phase 1 is CLOSED / ACCEPTED. U1, U2, U3, U4, U5 and U6 are CLOSED / ACCEPTED. Phases 2–6 remain **unauthorized**. R1, R2 and R3 are CLOSED / ACCEPTED, R4 is EXECUTED and R5 is CLOSED / ACCEPTED — Historical snapshot custody: OPEN / DESTINATION PROVISIONED / COPY EXECUTED AND VERIFIED / SOURCE PRESERVED / PARENT ACL HARDENING POLICY APPROVED NOT APPLIED / SECURITY-COMPLETE CUSTODY NOT YET CLAIMED (separate governance track, canonical destination `D:\programas\SGAA_Historical_Custody`, 17 artifacts copied and verified, parent ACL hardening policy approved but not applied, see `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`).

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
| `HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` | Autonomous governance | Administrative custody track for 17 historical snapshot artifacts; R1, R2 and R3 CLOSED / ACCEPTED; R4 EXECUTED; R5 CLOSED / ACCEPTED — destination `D:\programas\SGAA_Historical_Custody` provisioned, 17 artifacts copied and integrity-verified, manifest and evidence written, source preserved, SQLite never opened; parent-ACL hardening policy approved but not applied; security-complete custody not yet claimed |

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
