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
6. **Phase contracts** (`docs/refactor/REF_*.md` and named Phase 3/4 contracts) — per-phase scope, decisions,
   and closeout evidence. The canonical Phase 3 authority, intentionally revised
   through the B11 single-init cutover, is
   `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md`. Standalone REF contracts exist for: REF-0TF, REF-0TF-A,
   REF-0TF-B, REF-0C-A, REF-0C-B1-P0, REF-0C-B2-A, REF-0C-B2, REF-0C-C-A,
   REF-0C-C-B1. No standalone contract exists for REF-0A, REF-0ENV, REF-0B,
   REF-0T, REF-0C-A-R1, or REF-0C-D; their scope is documented in the ledger
   and PROJECT_STATE historical blocks. Phase 4 endpoint-preserving blueprint extraction is
   governed by `docs/refactor/PHASE4_ADMIN_BLUEPRINT_COMPATIBILITY_CONTRACT.md`.
7. **Historical snapshot custody** (`docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`)
    — autonomous administrative/governance track for the 17 historical database
    snapshot artifacts; R1, R2 and R3 CLOSED / ACCEPTED; **R4 EXECUTED**; **R5 CLOSED / ACCEPTED**;
    **R6 CLOSED / ACCEPTED WITH DECLARED POST-MUTATION NONCONFORMITY**
    — destination `D:\programas\SGAA_Historical_Custody` PROVISIONED, 17 artifacts copied
    and verified (4,808,704 bytes), custody manifest and evidence report written, source
    preserved, SQLite never opened; parent DACL target applied and independently verified;
    R6 remains classified POST-MUTATION HARD STOP;
    **R7 CLOSED / ACCEPTED / DOCUMENTARY CLOSEOUT PUBLISHED**;
    **LEVEL 2 PHYSICAL RESTORATION COMPLETE / LOCALLY VERIFIED / SUPERVISOR ACCEPTED**
    in restore root `D:\tmp\sgaa_restore_20260726T165550Z`, validator
    SQLITE_LEVEL2_CHECKS_PASS, evidence 7/7, restore root preserved, no new SQLite
    opening authorized; Level 3 NOT EXECUTED;
    security-complete custody NOT CLAIMED;
    does not integrate any architectural
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
5. `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` — final and accepted
   Macro Phase 3 executable single-init schema/startup/transaction contract.
6. `docs/refactor/PHASE4_ADMIN_BLUEPRINT_COMPATIBILITY_CONTRACT.md` — current B1
   endpoint-preservation, registrar, factory, compatibility-export and scope contract.
7. `PROJECT_STATE.md` — canonical current state (top block).
8. `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` — historical snapshot custody governance track.
9. `AGENT_HANDOFF.md` — current operational handoff.
10. All `docs/refactor/REF_*.md` / `docs/refactor/PHASE_0_*.md` files in dependency order: REF-0TF →
   REF-0TF-A → REF-0TF-B → REF-0C-A → REF-0C-B1-P0 → REF-0C-B1 →
   REF-0C-B2-A → REF-0C-B2 → REF-0C-C-A → REF-0C-C-B1 → REF-0C-D-R1 →
   PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.
## Canonical current state (2026-07-31)

- Branch: `refactor/architecture-safety-net`
- **Final Phase 3 technical commit:** `c9009bf3d68950ad4e0499b65928603e84bee341`
  (`Unify database initialization ownership`), parent
  `e63e1a66b9d2ebad7253a0efd2e0a367b89b8b8a`; the 14-path B11 technical
  artifact is committed, pushed, and post-commit verified.
- **PHASE 3-B11-R1:** CLOSED / ACCEPTED at governance commit
  `630d4eb448b992bdc3beb28752c30717989312bb` (`Record B11 publication and review
  closeout`), parent `c9009bf3d68950ad4e0499b65928603e84bee341`.
- **Macro Phase 3:** CLOSED / ACCEPTED. The canonical Phase 3 contract is final and
  accepted; B11 and B11-R1 are the accepted technical/governance baseline. B11-R1
  updated the existing contract and created no competing Phase 3 contract.
- **PHASE 4-B1:** CLOSED / ACCEPTED at technical commit
  `cd8a76b2484abc376174332578ecd8be4b8206ea` (`Extract admin configuration blueprint`).
  Exactly eight Configurações/Mensagens routes and eight settings helpers moved under the
  accepted endpoint-preserving registrar/factory/identity-export pattern. B1-R1 uses
  deterministic filesystem-recursive repository-tree discovery under `app/views/**/*.py`;
  it does not query or filter through the Git index. Phase 4 is not closed; B2, Phase 5 and
  Phase 6 are not authorized, and migration v4 remains prohibited.
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
  executor ReadAndExecute. Preserved R5 phase-time state: target SDDL recorded as policy
  only and then NOT applied; `D:\programas` remained inherited R4-era; custody-root ACL
  unchanged. The R6 closeout immediately below supersedes this historical state.
  See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.
- **HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R6: CLOSED / ACCEPTED WITH DECLARED
  POST-MUTATION NONCONFORMITY.**
  R6 execution classification: POST-MUTATION HARD STOP. Physical DACL outcome:
  TARGET APPLIED / INDEPENDENTLY VERIFIED. `SetAccessControl` calls: 1; Apply EXIT 1;
  post-application `PropertyNotFoundStrict` in the verification/serialization path;
  retry and rollback NOT PERFORMED / PROHIBITED. Parent DACL protected with the exact
  three approved ACEs; owner/group preserved; descendants zero drift; integrity 17/17.
  Nonconformity: DECLARED / CONTAINED / NO DACL TARGET DEVIATION /
  NO ARTIFACT INTEGRITY IMPACT / NO RETRY / NOT AN AUTHORIZED PRECEDENT.
  See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R7: CLOSED / ACCEPTED.
R7 READ-ONLY ASSESSMENT: COMPLETE.
LEVEL2 EXECUTION CONTRACT: READY.
PHYSICAL LEVEL2 RESTORATION: NOT AUTHORIZED AT R7 TIME — superseded by the accepted
Level 2 execution recorded below.
R7 DOCUMENTARY CLOSEOUT: COMMITTED AND PUBLISHED under the authorized subject
`Record accepted R7 Level 2 restoration contract`; identity is resolved through Git history.
The assessment remained read-only; the published closeout changes exactly seven documents.

LEVEL 2 PHYSICAL RESTORATION (execution round R3):
COMPLETE / LOCALLY VERIFIED / SUPERVISOR ACCEPTED.
Restore root `D:\tmp\sgaa_restore_20260726T165550Z`; candidate
`database.pre-D7.6B2-R2-hardening-20260613-184709.db` (544768 bytes, SHA-256
`92627ded44c9094e74f01da5718c995cd3fdd5ac467ef79298541a75b777cd8c`); validator outcome
`SQLITE_LEVEL2_CHECKS_PASS` with integrity PASS, schema PASS, 0 foreign-key violations
and 0 business-data exposure; SQLite connections source 0 / custody 0 / sealed 0 /
working 1 / total 1 / fallback 0; evidence 7/7 complete. Custody unchanged at 17/17 and
4,808,704 bytes; source preserved; no source removal.
Restore root and its `sealed\`, `working\` and `evidence\` contents remain PRESERVED
until a separate explicit cleanup order. NO new SQLite opening is authorized.
Level 3: NOT STARTED / NOT AUTHORIZED. Phase 2 was later authorized independently of
the custody track and is IN PROGRESS; PHASE2-D awaits external review.

Exact next action:

Supervisor review of the Level 2 acceptance record. No further custody action is
authorized; restore-root cleanup, any new SQLite opening, the fallback candidate,
and Level 3 each require a new separate explicit human order. The former Phase 2
authorization requirement was satisfied by later human orders.

No physical order is issued by this record.

Historical snapshot custody remains OPEN / DESTINATION PROVISIONED / COPY VERIFIED /
PARENT ACL HARDENING APPLIED AND VERIFIED / SOURCE PRESERVED /
LEVEL 2 PHYSICAL RESTORATION COMPLETE AND ACCEPTED / LEVEL 3 NOT EXECUTED /
SECURITY-COMPLETE CUSTODY NOT CLAIMED.

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
- **Fase 2 — Shared helpers**: **CLOSED / ACCEPTED.** PHASE2-A through PHASE2-D are
  CLOSED / ACCEPTED. The explicit ownership rule moves database/schema/repository
  dependencies to Phase 3, versioning/view dependencies to Phase 4, and wiring/logging/
  routing dependencies to their owning later phases. Zero runtime `app`→`main`
  back-references remains mandatory before Phase 6 closes.
- **Fase 3 — Data access consolidation**: **CLOSED / ACCEPTED.** PHASE 3-A,
  the PHASE 3-B assessment, and PHASE 3-B1 through PHASE 3-B10-R1 are CLOSED /
  ACCEPTED. PHASE 3-B10
  is COMMITTED AND PUSHED at `8fe0345eab08e312f7e015730f70d02327e7eb5f`
  (`Version activity versioning core schema`). B10-R1 is a governance-only
  correction recording the actual 15-path manifest, classifying the undocumented
  fifteenth test path as a process nonconformity, and correcting the lazy-bridge
  description in the canonical contract. PHASE 3-B11 is published at
  `c9009bf3d68950ad4e0499b65928603e84bee341`; its caller verifier records qualified
  lexical inventory 72 `main.init_db(...)` / 5 `app_db.init_db(...)` plus three bare
  imported-owner calls, and its corrected registry extractor proves exact callable
  v1/v2/v3 with no gap, duplicate or v4. Final hermetic evidence is 913 passed / 17
  deselected / 416.66s / exit 0; index-visible evidence is 67 passed; post-publication
  evidence is 212 passed / 42.37s; routes remain 131 and RBAC unmapped remains 0.
  Independent paid-Flash review verdict `APPROVE` is accepted with both declared
  reviewer process nonconformities recorded in the canonical state, ledger, and
  contract. B11 and B11-R1 are CLOSED / ACCEPTED; all mandatory Macro Phase 3
  objectives are satisfied. Optional repository-layer extraction is not implemented
  and is not a closure blocker or hidden Phase 4 assignment.
- **Fase 4 — Blueprint extraction**: OPEN / INCREMENTAL IMPLEMENTATION / B1 CLOSED /
  ACCEPTED. B1 commit `cd8a76b2484abc376174332578ecd8be4b8206ea` establishes the
  accepted compatibility registrar and exact eight-route Configurações/Mensagens cohort.
  Phase 4 is not closed and B2 is not authorized.
- **Fase 5 — Backup/sync offloading**: background jobs.
- **Fase 6 — `main.py` as entrypoint only**: ~50–150 lines.

Phase 1 is CLOSED / ACCEPTED. U1, U2, U3, U4, U5 and U6 are CLOSED / ACCEPTED.
Phase 2 is CLOSED / ACCEPTED. Macro Phase 3, PHASE 3-B11 and PHASE 3-B11-R1 are
CLOSED / ACCEPTED at technical commit `c9009bf3d68950ad4e0499b65928603e84bee341`
and governance commit `630d4eb448b992bdc3beb28752c30717989312bb`. PHASE 4-B1 is
CLOSED / ACCEPTED at `cd8a76b2484abc376174332578ecd8be4b8206ea`; Phase 4 is not
closed. B2, Phase 5 and Phase 6 remain **NOT AUTHORIZED**, and migration v4 remains
**PROHIBITED**. R1, R2 and R3 are CLOSED / ACCEPTED,
R4 is EXECUTED, R5 is CLOSED / ACCEPTED, R6 is CLOSED / ACCEPTED WITH DECLARED
POST-MUTATION NONCONFORMITY, and R7 is CLOSED / ACCEPTED / DOCUMENTARY CLOSEOUT
PUBLISHED — Historical snapshot custody: OPEN / DESTINATION PROVISIONED / COPY VERIFIED /
PARENT ACL HARDENING APPLIED AND VERIFIED / SOURCE PRESERVED / LEVEL 2 PHYSICAL
RESTORATION COMPLETE AND ACCEPTED / LEVEL 3 NOT EXECUTED / SECURITY-COMPLETE CUSTODY
NOT CLAIMED (separate governance track, canonical destination
`D:\programas\SGAA_Historical_Custody`, 17 artifacts copied and verified, parent DACL
target applied and independently verified, Level 2 executed and accepted in restore root
`D:\tmp\sgaa_restore_20260726T165550Z` with validator SQLITE_LEVEL2_CHECKS_PASS and evidence
7/7, restore root preserved, no new SQLite opening authorized, see
`docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`).

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
| `PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | PHASE 3-B5/B6/B7/B8/B9/B10/B11/B11-R1 | Final accepted Macro Phase 3 single-init, caller, schema-owner, startup-order, migration and transaction contract; B11 establishes `app.db` as sole init owner, preserves `main.init_db` identity compatibility, removes all lazy bridge and `app.db → main` dependencies, directly owns preferred-matrix selection and startup settings, and records exact per-boundary failure postconditions; B11-R1 records accepted publication/review governance |
| `PHASE4_ADMIN_BLUEPRINT_COMPATIBILITY_CONTRACT.md` | PHASE 4-B1 | CLOSED / ACCEPTED at `cd8a76b2484abc376174332578ecd8be4b8206ea`; endpoint-preserving admin blueprint pattern: immutable legacy route specs, collision-safe `record_once` registrar, exact eight Configurações/Mensagens routes, settings-helper ownership, factory opt-out, `main` identity exports, and no app-to-main import. Phase 4 not closed; B2 not authorized. |
| `HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` | Autonomous governance | Administrative custody track for 17 historical snapshot artifacts; R1-R3 CLOSED / ACCEPTED; R4 EXECUTED; R5 CLOSED / ACCEPTED; R6 CLOSED / ACCEPTED WITH DECLARED POST-MUTATION NONCONFORMITY; R7 CLOSED / ACCEPTED / DOCUMENTARY CLOSEOUT PUBLISHED; LEVEL 2 PHYSICAL RESTORATION COMPLETE / LOCALLY VERIFIED / SUPERVISOR ACCEPTED — destination provisioned, 17 artifacts copied and integrity-verified, source preserved, parent DACL target applied and independently verified; Level 2 executed and accepted in restore root `D:\tmp\sgaa_restore_20260726T165550Z`, evidence 7/7, restore root preserved, no new SQLite opening authorized; Level 3 not executed; security-complete custody not claimed |

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
| Phase 3-B5/B6/B7/B8/B9/B10/B11 schema/startup/transaction contract | `tests/test_phase3_schema_startup_transaction_contract.py` + `tests/test_phase3_final_init_cutover.py` + `tests/test_atividades_schema_migration_v2.py` + `tests/test_activity_versioning_core_migration_v3.py` + `tests/test_backup_settings_ownership.py` + `tests/test_activity_versioning_leaf_schema_ownership.py` + `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | B5 through B11-R1 CLOSED / ACCEPTED; B11 technical commit `c9009bf3d68950ad4e0499b65928603e84bee341`; B11-R1 governance commit `630d4eb448b992bdc3beb28752c30717989312bb`; review APPROVE; Macro Phase 3 CLOSED / ACCEPTED; Phase 4 NOT AUTHORIZED |
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
