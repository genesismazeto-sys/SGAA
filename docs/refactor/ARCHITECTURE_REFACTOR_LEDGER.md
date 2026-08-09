# Architecture Refactor Ledger

## Current authoritative state — PHASE 4-B7-P-R3 CLOSED / ACCEPTED — GOVERNANCE CLOSEOUT PUBLISHED (2026-08-04)

PHASE 4-B6 is CLOSED / ACCEPTED (see `PHASE4-B6` row below). PHASE 4-B7-A (read-only
diagnosis of the Arquivos/Alertas/Reportes cohort) is **CLOSED / ACCEPTED** with
classification `SHARED_OWNER_PREREQUISITE_REQUIRED`. PHASE 4-B7-P is **CLOSED /
ACCEPTED**: accepted technical commit `1c82a1954250aa5e6654349ce77a50d60f03fe8f`
(`Extract B7 shared neutral owners`), parent
`b6d6e2295e2beeba046cfe1f4c1614f667261ad2`; technical publication COMPLETE;
post-publication bounded verification COMPLETE; external supervisor technical
acceptance GRANTED. It implements exactly the accepted prerequisite: 4 shared
symbols moved to neutral owners 2/1/1 — `app.db_maintenance`
(`ensure_admin_arquivos_table`, `ensure_admin_alertas_table`, joining the
pre-existing `ensure_reportes_table`), new `app.admin_files`
(`get_admin_arquivo`), new `app.admin_alerts` (`list_active_admin_alertas`). `main`
re-exports all four by identity with zero local bodies; `aluno._get_main_helpers()`
is reduced from 5 keys to exactly `get_student_request_update_alert` /
`mark_student_request_updates_seen`. Zero route movement. Routing/reviewer
deviation preserved truthfully: the ordered IAsup/IAexec router was not invocable
in the implementing harness; implementation was performed directly by Claude,
disclosed rather than substituted silently; the external supervisor subsequently
performed an independent repository review as part of this R3 acceptance
closeout; deviation accepted as nonblocking. See the `PHASE4-B7-A` and
`PHASE4-B7-P` rows below and `docs/refactor/PHASE4_ARQUIVOS_ALERTAS_SHARED_OWNER_CONTRACT.md`
for full evidence. PHASE 4-B7 (blueprint route extraction) remains **NOT AUTHORIZED**.
PHASE 4 remains OPEN / INCREMENTAL IMPLEMENTATION. Phase 5 and Phase 6 remain NOT
AUTHORIZED. Migration v4 remains PROHIBITED. This R3 governance closeout changes
exactly six governance paths; no production, test, snapshot, or database path is
changed.

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
| HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R5 | Read-only parent ACL assessment and hardening decision closeout | CLOSED / ACCEPTED | N/A (read-only, no technical commit) | Authorized subject `Record approved R5 parent ACL hardening decision`; identity resolved through Git history | Preserved R5 phase-time state: FILE_DELETE_CHILD_NOT_GRANTED_CONFIRMED; strict Option B approved; target DACL policy only and then NOT applied; no physical mutation in R5. Superseded by R6 outcome below. | `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` | Historical R5 phase-time state; not current physical state |
| HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R6 | Parent DACL physical application, independent reconciliation and documentary closeout | CLOSED / ACCEPTED WITH DECLARED POST-MUTATION NONCONFORMITY | Physical call external to Git; documentary commit subject `Record verified R6 parent ACL hardening outcome` | Explicit human authorization; IAsup deterministic closeout | R6 classification POST-MUTATION HARD STOP; target DACL APPLIED / INDEPENDENTLY VERIFIED; SetAccessControl calls 1; Apply EXIT 1; PropertyNotFoundStrict after mutation in verification/serialization path; retry/rollback prohibited and not performed; owner/group preserved; three approved ACEs; zero descendant drift; 17/17 integrity. Nonconformity DECLARED / CONTAINED / NO DACL TARGET DEVIATION / NO ARTIFACT INTEGRITY IMPACT / NO RETRY / NOT AN AUTHORIZED PRECEDENT. | `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` | R6 outcome remains authoritative historical antecedent; R7 supersedes only the prior R7-NOT-STARTED residual |
| HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R7 | Read-only Level 2 restoration readiness assessment and restoration-execution contract | CLOSED / ACCEPTED | N/A (read-only assessment, no technical commit) | Authorized subject `Record accepted R7 Level 2 restoration contract`; identity resolved through Git history | R7 READ-ONLY ASSESSMENT: COMPLETE. LEVEL2 EXECUTION CONTRACT: READY. PHYSICAL LEVEL2 RESTORATION: NOT AUTHORIZED AT R7 TIME — superseded by the accepted Level 2 execution in the row below. R7 DOCUMENTARY CLOSEOUT: COMMITTED AND PUBLISHED. The assessment round had no repository mutation or physical restoration; the documentary closeout changes exactly seven documents. Primary Level 2 candidate: database.pre-D7.6B2-R2-hardening-20260613-184709.db (SHA-256 92627ded44c9094e74f01da5718c995cd3fdd5ac467ef79298541a75b777cd8c). Fallback: database.pre-D7.6B-schema-migration-20260613-180525.db (SHA-256 7ffb0c1ccc1bc3d60a86492bcda15f800af00dc84b6d9693ff5f4762680d55bf; requires separate human decision). Primary environment: NATIVE WINDOWS. R3-era container preference superseded. No physical order is issued by this closeout. | `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` | R7 phase-time residual (physical Level 2 not authorized; requires a new separate explicit human order) — resolved by the accepted Level 2 execution in the row below |
| LEVEL 2 PHYSICAL RESTORATION (execution round R3) | Execute and accept the Level 2 schema-and-metadata restoration of the primary custody candidate in a disposable native-Windows restore root | COMPLETE / LOCALLY VERIFIED / SUPERVISOR ACCEPTED | Physical execution external to Git; documentary commit subject `Record accepted Level 2 restoration and sync canonical state` | Separate explicit human physical Level 2 order; supervisor acceptance | Restore root `D:\tmp\sgaa_restore_20260726T165550Z`; candidate `database.pre-D7.6B2-R2-hardening-20260613-184709.db` (544768 bytes, SHA-256 92627ded44c9094e74f01da5718c995cd3fdd5ac467ef79298541a75b777cd8c); validator SQLITE_LEVEL2_CHECKS_PASS with integrity PASS, schema PASS, 0 foreign-key violations, 0 business-data exposure; SQLite connections source 0 / custody 0 / sealed 0 / working 1 / total 1 / fallback 0; evidence 7/7 complete, including sqlite-result.json (43682 bytes, SHA-256 71bb40e4…5866), postflight.json (2318 bytes, SHA-256 e498af58…6176) and level2-report.md (SHA-256 efaa34bd…3622); restore-root ACLs root Modify, sealed/working ReadAndExecute, evidence Modify; custody unchanged 17/17 and 4,808,704 bytes; R8 register 11 entries, digest 75c00810…1023; package and qualification hashes unchanged; source preserved, no source removal. | `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` | Restore root preserved until a separate explicit cleanup order; no new SQLite opening authorized; fallback candidate unauthorized; Level 3 remains not started/unauthorized. Its phase-time Phase 2 status was superseded by later separate architectural orders. |
| HISTORICAL-DATABASE-SNAPSHOT-CUSTODY | Administrative/governance track for 17 historical snapshot artifacts | OPEN / DESTINATION PROVISIONED / COPY VERIFIED / PARENT ACL HARDENING APPLIED AND VERIFIED / SOURCE PRESERVED / LEVEL 2 PHYSICAL RESTORATION COMPLETE AND ACCEPTED / LEVEL 3 NOT EXECUTED / SECURITY-COMPLETE CUSTODY NOT CLAIMED | R4 copy + R6 parent DACL hardening + accepted Level 2 restoration; no repository code mutation | R4-R7 and Level 2 documentary closeouts resolved through Git history | R1-R3 CLOSED / ACCEPTED; R4 EXECUTED; R5 CLOSED / ACCEPTED; R6 CLOSED / ACCEPTED WITH DECLARED POST-MUTATION NONCONFORMITY; R7 CLOSED / ACCEPTED / DOCUMENTARY CLOSEOUT PUBLISHED; LEVEL 2 PHYSICAL RESTORATION COMPLETE / LOCALLY VERIFIED / SUPERVISOR ACCEPTED. Destination `D:\programas\SGAA_Historical_Custody`; 17/17 and 4,808,704 bytes; parent target DACL independently verified; source preserved; the only SQLite opening was the single qualified Level 2 validator open of `working\`; Level 3 not executed; no independent redundancy. | `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` | Restore root preserved until a separate explicit cleanup order; no new SQLite opening authorized; Level 3 requires a new separate explicit human order. The custody track grants no architecture-phase authorization; Phase 2 authorization derives from later separate human orders. |
| PHASE2-A | Shared password helpers | CLOSED / ACCEPTED | `2f7cc5cd98a8b2c763151fd6e3c0b3e1c0bc52b2` | Identity resolved through Git history | See current `PROJECT_STATE.md` historical evidence | `docs/mapeamento/05_avaliacao_refactor.md` | None recorded |
| PHASE2-B | Pagination and query-filter helpers | CLOSED / ACCEPTED | `1a0a690343462c23b8a30a1f0d6d8cb250027936` | Identity resolved through Git history | See current `PROJECT_STATE.md` historical evidence | `docs/mapeamento/05_avaliacao_refactor.md` | None recorded |
| PHASE2-C | PT-BR text helpers | CLOSED / ACCEPTED | `218d6949f63b0578ffd08507766fe5198b8f72b7` | Acceptance correction `7fc0629b4b4b40159a1eea6431402c9278fe3b40` | 700 passed, 17 D73H deselected; focused 24; expanded 37; isolation 15 | `docs/mapeamento/05_avaliacao_refactor.md` | None recorded |
| PHASE2-D | Residual shared-helper closure batch: Categories A and E | CLOSED / ACCEPTED / CATEGORY_A_ZERO / CATEGORY_E_ZERO | `8454ef149ebc701c169eec5d1d8eb7689c6a9dee` | Accepted by the explicit Phase-2 closure baseline preceding PHASE 3-A | Focused contract 28; affected functional lane 94; route/RBAC lane 87; Git-aware isolation 15; full hermetic 727 passed and 18 D73H deselected | `docs/mapeamento/05_avaliacao_refactor.md` | Categories B/C/D transferred to their owning later phases; final zero runtime app-to-main remains a Phase-6 invariant |
| PHASE2-C-ACCEPTANCE | External acceptance-state correction for PT-BR text helpers | CLOSED / ACCEPTED | `218d6949f63b0578ffd08507766fe5198b8f72b7`; subject `Extract PT-BR text helpers` | Authorized subject `Correct Phase 2-C acceptance state`; identity resolved through Git history | Documentation-only correction at baseline HEAD `8454ef149ebc701c169eec5d1d8eb7689c6a9dee`; tests not run / prohibited | `PROJECT_STATE.md`; `AGENT_HANDOFF.md`; `docs/DOCUMENTATION_INDEX.md` | Its phase-time PHASE2-D-pending residual is historical and superseded by the accepted Phase-2 closure and PHASE 3-A/B records below |
| Fase 2 | Shared helpers extraction | CLOSED / ACCEPTED | PHASE2-A through PHASE2-D above | Explicit closure baseline preceding PHASE 3-A | Category A 0; Category E 0; route delta 0; RBAC delta 0; canonical database mutation/open count 0 | `docs/mapeamento/05_avaliacao_refactor.md` | Final zero runtime app-to-main back-reference remains mandatory before Phase 6 closes; database/schema/repository moved to Phase 3, versioning/view to Phase 4, wiring/logging/routing to owning later phases |
| PHASE3-A | Canonical database connection ownership consolidation | CLOSED / ACCEPTED | `fac0d7a58af226de43e4ac81d35daf8e3bd0aa05`; subject `Consolidate canonical database connection ownership` | Explicit acceptance in PHASE 3-B1 order | Focused 38; Git-aware isolation 15; full hermetic 734 passed, 17 D73H deselected | `PROJECT_STATE.md`; `AGENT_HANDOFF.md` | `init_db` and schema-helper ownership intentionally remained for PHASE 3-B |
| PHASE3-B-ASSESSMENT | Read-only `init_db` and schema-helper ownership assessment | CLOSED / ACCEPTED | N/A (read-only, zero repository mutation) | Explicit acceptance in PHASE 3-B1 order | Static/AST/Git assessment only; no tests, application, migration or database execution | `PROJECT_STATE.md`; `AGENT_HANDOFF.md` | Established bounded sequence; B1 selected as first leaf extraction |
| PHASE3-B1 | Extract `ensure_reportes_table` ownership to `app/db_maintenance.py` | CLOSED / ACCEPTED | Authorized subject `Extract reportes schema helper ownership`; identity resolved through Git history | Explicit acceptance in PHASE 3-B2 order | Helper 6; reportes/aluno/ownership 45; route/RBAC 3; Git-aware isolation 15; full hermetic 739 passed, 17 D73H deselected | `PROJECT_STATE.md`; `AGENT_HANDOFF.md` | Waiting-review state superseded by B2 authorization |
| PHASE3-B2 | Extract `ensure_usuario_profile_schema` ownership to `app/db_maintenance.py` | CLOSED / ACCEPTED | Authorized subject `Extract user profile schema helper ownership`; identity resolved through Git history | Explicit acceptance in PHASE 3-B3 order | Focused schema/ownership/profile 45; route/RBAC 3; Git-aware isolation 15; full hermetic 748 passed, 17 D73H deselected | `PROJECT_STATE.md`; `AGENT_HANDOFF.md` | Waiting-review state superseded by B3 authorization |
| PHASE3-B3 | Extract `ensure_requisicao_alert_receipts_table` ownership to `app/db_maintenance.py` | CLOSED / ACCEPTED | Authorized subject `Extract requisition alert receipts schema ownership`; identity resolved through Git history | Explicit acceptance in PHASE 3-B4 order | Focused schema/ownership/alert/dashboard 59; route/RBAC 3; Git-aware isolation 15; full hermetic 756 passed, 17 D73H deselected | `PROJECT_STATE.md`; `AGENT_HANDOFF.md` | Waiting-review state superseded by B4 authorization |
| PHASE3-B4 | Extract matrix schema-helper cluster ownership to `app/db_maintenance.py` | CLOSED / ACCEPTED | `41a84fb4dd71278c61fd1707535dd60560a86a27`; subject `Extract matrix schema helper ownership` | Explicit acceptance in PHASE 3-B5 order | Focused ownership/schema 39; affected matrix/activity/requisition/versioning 334; route/RBAC 4; Git-aware isolation 15; full hermetic 773 passed, 17 D73H deselected | `PROJECT_STATE.md`; `AGENT_HANDOFF.md` | Waiting-review state superseded by B5 authorization; six `app.db` lazy entries remain |
| PHASE3-B5 | Freeze the accepted current schema, startup, migration, caller and transaction behavior without production changes | CLOSED / ACCEPTED | `39e5832d17820f4363829342c5f03bad3172844c`; subject `Freeze schema startup transaction contract` | Explicit acceptance in PHASE 3-B6 order | Contract 8; schema maintenance 39; ownership/residual 34; startup/factory 10; restore/clean 2; isolation 15; docs 1; route/RBAC 3; full hermetic 781 passed, 17 D73H deselected, 0 failures/errors; routes 131; RBAC unmapped 0 | Same canonical authority, intentionally revised by B6 | Historical handoff subcount corrected by B5-R1; dual init remains active/divergent |
| PHASE3-B5-R1 | Correct the handoff caller-inventory tests/fixtures subcount from 69 to 68 while preserving total 73 | CLOSED / ACCEPTED | `b29688839ea2105782fbf889550bbbd047e2a3f7`; subject `Correct B5 caller inventory handoff` | Explicit acceptance in PHASE 3-B6 order | Contract 8 and governance node 1 passed pre/post publication; caller arithmetic 2 + 3 + 68 = 73 | `AGENT_HANDOFF.md` | Documentation-only correction; no production or contract redesign |
| PHASE3-B6 | Separate access structural DDL, historical defaults, startup normalization and savepoint orchestration; extract sole ownership to `app.db_maintenance` | CLOSED / ACCEPTED | `b328789f16cc4db0173e58d2d2454902565d0610`; subject `Separate access schema from normalization` | Explicit acceptance in PHASE 3-B7 order | TDD RED confirmed missing owner/lazy/direct-import architecture; focused schema/ownership/contract 85; access/auth/admin/student/login/RBAC 130; isolation/clean/route/RBAC 19; full hermetic 791 passed, 17 D73H deselected; routes 131; RBAC unmapped 0 | `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | Runtime login normalization unchanged; dual init and other transaction debt remain |
| PHASE3-B7 | Separate backup-settings structural schema, runtime defaults, historical seeding, exact legacy normalization, read/merge and Flask runtime application; remove the matching lazy edge | CLOSED / ACCEPTED | `d1947b0c11506045b8d52bd235bc7381a2ca22c9`; subject `Separate backup schema from runtime configuration` | Explicit acceptance in PHASE 3-B8 order | Binding 39; integrated ownership/schema/contract 124; backup/cloud/restore 54; release admin/route/RBAC 6; runtime isolation 15; recovered test-binding leakage 41; full hermetic 830 passed, 17 D73H deselected; post-governance 142; routes 131; RBAC unmapped 0; independent FREE review `ses_05b37cc64ffeUakdqRN7BkJ9pq` APPROVE | `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | Explicit module-level `main.app` binding remains baseline compatibility debt / not target architecture; superseded waiting-review state |
| PHASE3-B8 | Extract four activity-versioning leaf tables, two transition triggers and eight leaf indexes into three pure caller-owned helpers while preserving the main core/rebuild orchestrator and four-entry lazy bridge | CLOSED / ACCEPTED | `42ad0b500fe26fb2a4f49a2f8655d0217233af75`; subject `Extract activity versioning leaf schema ownership` | Explicit acceptance in PHASE 3-B9 order | TDD final RED 16 failed + 3 baseline guards; focused 19; integrated 126; Git-aware isolation 15; expanded versioning/matrix/requisition 309; routes/RBAC 3 with 131/0; full hermetic 849 passed, 17 D73H deselected; independent FREE review `ses_05adebcf2ffe4xZqeQFq1LX6Fy` APPROVE | `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | Core activity-versioning schema and rebuild remain isolated for B10; B8 waiting-review state superseded by B9 authorization |
| PHASE3-B9 | Replace recurring `atividades` rebuild with versioned eleven-column migration v2, isolated early checkpoint in both init bodies, and three-entry lazy bridge | CLOSED / ACCEPTED | Authorized subject `Version atividades schema migration`; final identity resolves through Git history and publication proof | External supervisor review after publication | Stage-A FREE `ses_05ac5d405ffenqwkRrh7QeBAIo` rejected unusable; paid fallback `ses_05abb3bd1ffeut3C2R2SSaIuw7` accepted; initial full 869 passed / 2 CSRF inventory failures / 17 deselected; localized `SchemaMigrationStateError` repair; pre-staging full 872/17; staged caller-manifest failure 78 passed + 1 failed, corrected 73→74; post-staging 79; final full 873/17; independent paid-Flash review `ses_05a18eb14ffejH0B4Z7zROy427`, cost 0.0005707464, APPROVE / no findings after FREE became unusable/exhausted | `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | PATH B preserves three FK child datasets and caller work boundary; B8 leaf owners unchanged; exact 14-path manifest; publication pending in commit tree; PHASE 3-B10 unauthorized |
| PHASE3-B10 | Extract activity-versioning core migration v3, retire self-transactional rebuild, move core owner to `app.db_maintenance`, reduce lazy bridge to two entries | COMMITTED AND PUSHED / POST-COMMIT VERIFIED / AWAITING SUPERVISOR REVIEW / GOVERNANCE CORRECTION PENDING | `8fe0345eab08e312f7e015730f70d02327e7eb5f`; subject `Version activity versioning core schema`; parent `37c8757e4ef41647c971ad8a974c853dec6ce4e7` | Supervisor review after publication | 15-path actual manifest (1726 insertions, 464 deletions); SCHEMA_VERSION 3; v3 registry entry `normalize_activity_versioning_core`; legacy self-transactional rebuild retired from main.py; core owner in app.db_maintenance; lazy bridge exactly `get_preferred_matriz_for_curso` and `logger`; B8/B9/B7 preserved; full hermetic 898/17; routes 131; RBAC unmapped 0 | `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | Undocumented fifteenth path `tests/test_ref_0c_b1_p0_access_context_transactions.py` — mechanically required v3 expectation update, content correct, not preauthorized, process nonconformity, no production scope expansion. B10-R1 corrects governance record. |
| PHASE3-B10-R1 | Correct B10 governance manifest record, lazy-bridge description, and synchronize all governance documents to the actual 15-path commit artifact | CLOSED / ACCEPTED | `e63e1a66b9d2ebad7253a0efd2e0a367b89b8b8a`; subject `Correct B10 governance manifest record` | Accepted by explicit B11 continuation order | Governance-only correction: 6 authorized paths (no production delta). Corrected manifest from 14 to 15 paths, recorded fifteenth-path classification, fixed lazy-bridge count in canonical contract, added B10-R1 to ledger. | `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | Waiting-review state superseded by B11 authorization |
| PHASE3-B11 | Establish `app.db` as sole defining `init_db` owner; preserve `main.init_db` identity compatibility; remove reverse/lazy bridge; transfer preferred-matrix, logger, settings and startup ownership; reconcile exact failure postconditions | CLOSED / ACCEPTED | `c9009bf3d68950ad4e0499b65928603e84bee341`; subject `Unify database initialization ownership`; parent `e63e1a66b9d2ebad7253a0efd2e0a367b89b8b8a` | External supervisor acceptance; B11-R1 governance commit `630d4eb448b992bdc3beb28752c30717989312bb` | Exact 14-path manifest: `AGENT_HANDOFF.md`, `PROJECT_STATE.md`, `app/db.py`, `docs/DOCUMENTATION_INDEX.md`, `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`, `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md`, `main.py`, `tests/test_activity_versioning_leaf_schema_ownership.py`, `tests/test_backup_settings_ownership.py`, `tests/test_db_connection_ownership.py`, `tests/test_db_schema_maintenance.py`, `tests/test_phase3_final_init_cutover.py`, `tests/test_phase3_schema_startup_transaction_contract.py`, `tests/test_residual_shared_helpers.py`; 1428 insertions / 812 deletions; final hermetic 913/17/416.66s; index-visible 67; post-publication 212/42.37s; routes 131; RBAC unmapped 0; canonical diff SHA-256 `19f59666f1c55259493281950fa2651e6261fc7e6f8b8e01473f254326c87378`. Accepted review: `FALLBACK_FREE_TIMEOUT_UNUSABLE_DELIVERY`; `opencode-go` / `opencode-go/deepseek-v4-flash`; session `ses_032324d57fferZNeqNjUW681iq`; cost `0.01252156 USD`; APPROVE; Material/Critical/High 0; accepted LOW intentional tested `main` compatibility coupling; accepted INFO registry v1/v2/v3, caller inventory 72/5 plus three bare calls, sufficient fault-injection coverage. | `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | No functional residual demonstrated. Reviewer nonconformities declared: same-session textual verdict recovery through a second invocation with same provider/model/session, no new tools/diff/reviewer; external `/tmp/candidate.diff`, reported 144049 bytes / SHA-256 `fcd1b62e141434dccaa89dabe9b604afe61977c96490674503b9410185627771`, outside repo/index/commit and preserved uninspected. Phase 4 and migration v4 prohibited. |
| PHASE3-B11-R1 | Synchronize canonical governance with the published and post-publication-verified B11 technical artifact | CLOSED / ACCEPTED | N/A (governance-only; no production correction) | `630d4eb448b992bdc3beb28752c30717989312bb`; subject `Record B11 publication and review closeout`; external supervisor acceptance | Six-path governance manifest: `AGENT_HANDOFF.md`, `PROJECT_STATE.md`, `docs/DOCUMENTATION_INDEX.md`, `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`, `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md`, `tests/test_phase3_schema_startup_transaction_contract.py`. Publication, post-commit verification, accepted review and both declared reviewer process nonconformities recorded; latest governance/route/RBAC lane 12 passed; routes 131; RBAC unmapped 0. | `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | No production delta; no functional residual demonstrated; accepted LOW compatibility import remains declared. |
| Fase 3 | Data access consolidation | CLOSED / ACCEPTED | `c9009bf3d68950ad4e0499b65928603e84bee341`; B11 technical commit | `630d4eb448b992bdc3beb28752c30717989312bb`; B11-R1 governance commit; external supervisor acceptance | Final hermetic 913/17; B11 post-publication 212; latest governance/route/RBAC lane 12; routes 131; RBAC unmapped 0; independent review APPROVE; mandatory Phase 3 objectives satisfied | `docs/mapeamento/05_avaliacao_refactor.md`; `PROJECT_STATE.md`; `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md` | Accepted LOW compatibility import; no demonstrated functional residual; optional repository extraction deferred and not a closure blocker; Phase 4 and migration v4 unauthorized |
| PHASE4-B1 | Extract exactly eight Configurações/Mensagens admin routes and eight settings helpers into the first endpoint-preserving admin blueprint; establish reusable collision-safe registrar; add deterministic filesystem-recursive repository-tree message and CSRF canonical-owner discovery under `app/views/**/*.py` without Git-index filtering | CLOSED / ACCEPTED | `cd8a76b2484abc376174332578ecd8be4b8206ea`; subject `Extract admin configuration blueprint`; parent `7f393c72ad3e9d70eae4c06ee41e0d74881e40f2`; exact 13 paths: `AGENT_HANDOFF.md`, `PROJECT_STATE.md`, `app/__init__.py`, `app/views/admin/__init__.py`, `app/views/admin/configuracoes.py`, `docs/DOCUMENTATION_INDEX.md`, `docs/mapeamento/05_avaliacao_refactor.md`, `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`, `docs/refactor/PHASE4_ADMIN_BLUEPRINT_COMPATIBILITY_CONTRACT.md`, `main.py`, `tests/test_csrf_inventory_audit.py`, `tests/test_phase4_configuracoes_blueprint.py`, `utils/messages.py` | External supervisor acceptance | Original TDD RED 15 failed / 6 passed; focused GREEN 21 passed; B1-R1 recursive-inventory correction RED/GREEN 4 failed then 4 passed; targeted 47 passed; full hermetic 939 passed / 17 deselected / 297.48s; post-publication 91 passed; routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0; independent review route `flash_free`, provider/model `opencode` / `opencode/deepseek-v4-flash-free`, session `ses_0453cc57fffexsyJU43Oyi1wwz`, cost 0, no fallback/mutation, verdict PASS | `docs/refactor/PHASE4_ADMIN_BLUEPRINT_COMPATIBILITY_CONTRACT.md` | No functional residual demonstrated. Transitional global legacy endpoints and `main` identity exports intentionally retained; cleanup deferred until final Phase 4 cohort. The B1-time B2 prohibition is superseded only by the separate B2 order; Phase 5 and Phase 6 unauthorized; migration v4 prohibited; Phase 4 not closed. |
| PHASE4-B2 | Transfer activity-versioning resolver, snapshot and shadow-read ownership; move exactly three diagnostic handlers through the accepted B1 legacy registrar; remove two aluno lazy-main versioning edges; preserve root/log/logger compatibility | CLOSED / ACCEPTED | `17e468ad938e873e1f9e9c303808ad31b9f3806b`; subject `Extract versioning subsystem ownership`; parent `2fbe4954106dc8d410f6495ca8bd4b1956b326d2`; exact 24 paths (8 production, 10 tests, 6 governance) | External supervisor acceptance recorded by B2-R3; post-publication verification: COMPLETE | Full hermetic 954 passed / 17 deselected / 0 failures / 0 errors / 343.75s / exit 0; index-visible 271 passed; post-publication 282 passed; routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0; actor matrix 402 = 263 allowed + 139 denied. FREE review `opencode/deepseek-v4-flash-free` session `ses_0433de371ffefBa8J03FBmkoV4`: UNUSABLE DELIVERY / NO VERDICT; fallback `FALLBACK_FREE_UNUSABLE_DELIVERY`. Accepted review `opencode-go/deepseek-v4-flash`, session `ses_043375c9affeYmMxqtbpNjNohl`, cost 0.01838004 USD, diff `a97275ac9f29cefcfd8ed4d3038ce37f552a886036481be0f7fd1c7f85a373b7`, PASS, material findings 0; LOW rejected as non-material / semantic equivalence proved. Final addendum `flash_free`, `opencode/deepseek-v4-flash-free`, session `ses_0431aa4d7ffev4hTZImBDA86Ca`, cost 0, PASS, no fallback. | `docs/refactor/PHASE4_VERSIONING_SUBSYSTEM_CONTRACT.md` | No B2 technical residual demonstrated. External `baseline_main.py` scratch SHA-256 `2652d1213d7f0b5ac577ebddb528341448e9eb0afb8b41d051e5826a56d4af48`: outside repository, not staged/committed, selectively removed, no candidate/index impact. Stale prepublication continuation language is superseded by B2-R3. The B2 phase-time B3 prohibition is superseded only by the separate B3 authorization; Phase 5 and Phase 6 remain unauthorized; migration v4 prohibited. |
| PHASE4-B3 | Extract exactly 22 Atividades and versioned-catalog legacy endpoints / 29 route-method pairs; establish neutral `app.activity_catalog` and `app.uploads` ownership; reconcile message and CSRF owner metadata without moving Matrizes/Requisições routes | CLOSED / ACCEPTED | `50801b6bdddc4d2772853c13f4905c49e8c996cf`; subject `Extract admin activities blueprint`; parent `81cc6b10b893f1d34bd211a527e9fd12c3b6bbbe`; exact 16 paths | External supervisor acceptance recorded by B3-R3; closeout subject `Record acceptance of Phase 4-B3`, identity resolved through Git history; post-publication verification COMPLETE | B3 contract 19; affected lane 353; final hermetic 974/17/399.95s; index-visible 300; post-publication 300; routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0; actor matrix 402 = 263 allowed + 139 denied. Provisional FREE `ses_0425bf1cbffeIxMwsDQn0etSEC`: UNUSABLE / NO VERDICT. Final FREE `ses_0422f0e1cffepCXyNpg47dWpoq`: TIMEOUT. Accepted technical fallback `opencode-go/deepseek-v4-flash`, `ses_04224ca47ffe5qAwwHGtxlR7i7`, router cost 0.0010424344 USD, reviewed hash `ec96796d3541710a36ac8121e40ffd888737c7c926f191a28034482cedbfd556`, mutation 0, PASS / findings NONE. Documentary addendum first REJECTED stale historical index wording; governance-only correction; final `opencode-go/deepseek-v4-flash`, `ses_04203dca3ffe8OM83rhbHyjqYI`, PASS. Final publication/governance/non-governance hashes `c41ffe5b7328b6d5a986dbdc28f054fe89641496589003b4e5649ff88463cc19` / `af2906ef0fa9fef7fdd469dd4e967cd1c914b4bfb21fc2a132b8d74c2d8dfd27` / `13b0af13e653641d75d2466d7d8d69090e655a18e28bb678a7090dbe0e2ecab0`. | `docs/refactor/PHASE4_ATIVIDADES_BLUEPRINT_CONTRACT.md` | Historical prepublication scope state is superseded by `EXACT_DELTA_PROVED / SUPERVISOR_RECONCILED / INCLUDED_IN_ACCEPTED_B3_COMMIT / NO_GENERIC_RETROACTIVE_AUTHORITY`. No B3 residual. B4, Phase 5/6 unauthorized; migration v4 prohibited; Phase 4 not closed. |
| PHASE4-B4.1 | Extract neutral Requisições shared owners, reconcile all-eight B1 settings ownership and establish dedicated matrix-scope ownership without moving routes or hardening behavior | CLOSED / ACCEPTED | `73ebf0dc34681e74e778759af476e1cd2f981444`; subject `Extract requisition shared owners`; parent `185426daccc9f0eb0dba4497248100c1a88d15fa`; exact 20 paths (7 production, 7 tests, 6 governance) | External supervisor acceptance recorded by B4.1-R2; closeout subject `Record acceptance of Phase 4-B4.1`, identity resolved through Git history; post-publication verification COMPLETE | Final full 984/17/419.95s; index-visible 170; post-publication 170; routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0; actor 402 = 263 + 139; message catalog 536. Technical review `flash_free`, `opencode/deepseek-v4-flash-free`, session `ses_040d538bfffegBsAJQbLJrnqSV`, cost 0, reviewed hash `f4b6cb00b4365cc7c20af5fcba1ac736ece1bab0ab9c6e0f89b19084799727f9`, no fallback/mutation, PASS / findings NONE. Documentary addendum `flash_free`, same model, session `ses_040ae7625ffeHCGZxyXoMzoQmw`, cost 0, mutation 0, PASS / findings NONE. Final publication/governance/non-governance hashes `bdd947a18df900aac691ce12683f393a82d8c8efc3e28a8c54c55226d7bf2d4a` / `301a6a891936338bd1a752ff0be65dd7855302d1e3a8e81f9bcbd94964b66a71` / `74649089be0699dff4440260bdb11793b4e5793550f17456893f4a281bd6096b`. | `docs/refactor/PHASE4_REQUISICOES_SHARED_OWNER_CONTRACT.md` | Expanded scope accepted exactly; B1 history and B2 six-to-five Aluno edge history preserved. NO ROUTE MOVEMENT; nine Requisições handlers remain in `main.py`; no B4.1 residual. B4.2 unauthorized. |
| PHASE4-B4.2 | Move the exact Admin Requisições route cohort to its canonical blueprint while preserving global legacy endpoint identities and consuming accepted neutral owners | CLOSED / ACCEPTED | `3231dbd2ff9759d8f855f2a4118102783aedea83`; subject `Extract admin requisitions blueprint`; parent `c587098152e97d125f41a2d26f2f414c10ae5676`; exact 16 paths (3 production, 7 tests/snapshots, 6 governance) | External supervisor acceptance recorded by B4.2-R2; publication and post-publication verification COMPLETE | TDD RED 20 failed / 3 passed; focused GREEN 138 + 107; first full 1001/4/17 preserved historically; final hermetic 1005/17/362.33s; index-visible 57; post-publication 56/1; exact 9 endpoints / 12 route-method pairs; RBAC 4/5/3; routes 131; endpoints 130; governed pairs 134; unmapped 0; actor 402 = 263 + 139; message catalog 536; CSRF 5/5 owner-only; canonical SQLite opens 0. Technical Flash FREE review PASS / blocking NONE / scope EXACT / behavior PRESERVED. Documentary addendum selected paid Flash under `FALLBACK_FREE_BUDGET_EXHAUSTED`, PASS. | `docs/refactor/PHASE4_REQUISICOES_BLUEPRINT_CONTRACT.md` | Hash-method finding valid/nonblocking/documentarily corrected/no technical impact. B4.1 neutral owners preserved; no `app -> main`; no technical residual. Matrizes, Phase 5/6 unauthorized; migration v4 prohibited; Phase 4 not closed. |
| PHASE4-B4.2-R2 | Reconcile canonical governance with the accepted published B4.2 technical artifact | CLOSED / ACCEPTED / GOVERNANCE CLOSEOUT PUBLISHED | N/A (governance-only; no technical correction) | Authorized subject `Record acceptance of Phase 4-B4.2`; identity resolves through Git history | Exact six-path governance manifest; technical commit/parent/publication facts recorded; raw/Git-canonical identities preserved distinctly; accepted technical review and documentary fallback history retained; bounded governance/current-state and route/RBAC gates required; independent documentary review required read-only before staging | `AGENT_HANDOFF.md`; `PROJECT_STATE.md`; `docs/DOCUMENTATION_INDEX.md`; `docs/mapeamento/05_avaliacao_refactor.md`; `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`; `docs/refactor/PHASE4_REQUISICOES_BLUEPRINT_CONTRACT.md` | Zero production/test/snapshot/database mutation. Historical pending statements superseded, not erased. No next cohort authorized. |
| PHASE4-B5-A | Diagnose the neutral admin-access shared-owner cut required as the Matrizes prerequisite; prove the exact five-symbol closure, six main consumers, import graph and zero-route boundary | DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED | N/A (diagnosis only; prerequisite implemented by B5-P) | B5-P technical commit `92486f87ea15697282a265cb7a9941678cb9138f` satisfies the prerequisite; B5-P-R3 governance closeout published | Final full hermetic after R2 1025/17/0/0/326.74s/exit 0 (the 306.41s run is pre-R2 historical); independent-review rerun 1025/17/0/0/367.27s; post-publication focused 132 passed/39.23s; routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC unmapped 0; actor 402; message catalog 536 | `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md` | PHASE 4-B5 blueprint extraction implemented as an unstaged candidate by B5 (see PHASE4-B5 row); no Matrizes route moved at B5-P-time |
| PHASE4-B5-P | Establish the neutral admin-access shared-owner prerequisite: extract exactly five admin-access context symbols to `app/admin_access.py` with `main` identity re-exports, zero `app.admin_access -> main` and zero `app.auth -> app.admin_access` edges, and no route movement | CLOSED / ACCEPTED | `92486f87ea15697282a265cb7a9941678cb9138f`; subject `Extract admin access context shared owner`; parent `a0b56896252a276e562da3842d3d61b078bd9f27` | Authorized subject `Record acceptance of Phase 4-B5-P` (B5-P-R3); identity resolves through Git history; post-publication verification COMPLETE | Corrected pre-production RED 20 failed; first core GREEN attempt 2 failed/23 passed corrected without production mutation (grouped ordering follows `ACCESS_RESOURCE_GROUPS`; `__wrapped__` introspection); recovered core lane 25 passed; focused lane 168 passed; first full hermetic 1 failed/1024 passed/17 deselected (historical, superseded by B5-P-R1); B5-P-R1 classification `PRE_REVIEW_SCOPE_EXPANSION / NOW_EXPLICITLY_RATIFIED / NO_RETROACTIVE_GENERIC_AUTHORITY` with `B4_2_BASELINE_COMMIT=c587098152e97d125f41a2d26f2f414c10ae5676`; R1 exact node 1 passed; B5-P-R2 SUPPLEMENTAL SCOPE AUTHORIZATION added and modified only `tests/test_phase4_requisicoes_shared_owners.py`, reading accepted B4.1 governance from fixed commit `c587098152e97d125f41a2d26f2f414c10ae5676`, classification `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED_B5_P_R2 / FIXED_ACCEPTED_B4_1_BASELINE / NO_RETROACTIVE_GENERIC_AUTHORITY`, R2 node 1 passed in 1.02s, affected governance aggregate 118 passed in 16.70s; final pre-publication hermetic 1025 passed + 17 deselected / 0 failed / 0 errors / 326.74s / exit 0 (the 306.41s run is pre-R2 historical); independent-review rerun 1025/17/0/0/367.27s; post-publication focused 132 passed/39.23s; routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC unmapped 0; actor 402; message catalog 536; route inventory byte-identical; CSRF shadow-off/on byte-identical to HEAD and each other | `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md` | Actual 11-path artifact (2 production + 3 tests + 6 governance) within updated ceiling 12; accepted independent review `opencode` / `opencode/deepseek-v4-flash-free` / `ses_03c92c10affegAmZLZ63tmTjjA` exit 0 cost 0 mutation 0 blocking 0 nonblocking 3; accepted content identities raw candidate `bf67fcaa…`, technical raw `932793aa…`, Git-normalized `068bf70d…`. PHASE 4-B5 blueprint extraction NOT AUTHORIZED; no Matrizes route moved; `app/views/admin/matrizes.py` remains absent |
| PHASE4-B5-P-R3 | Reconcile canonical governance with the accepted published B5-P technical artifact | CLOSED / ACCEPTED / GOVERNANCE CLOSEOUT PUBLISHED | N/A (governance-only; no technical correction) | Authorized subject `Record acceptance of Phase 4-B5-P`; identity resolves through Git history | Exact six-path governance manifest; technical commit `92486f87ea15697282a265cb7a9941678cb9138f` / parent `a0b56896252a276e562da3842d3d61b078bd9f27`; publication and post-publication verification COMPLETE; accepted independent review recorded; raw/Git-canonical content identities preserved distinctly; historical pre-publication pending statements superseded, not erased | `AGENT_HANDOFF.md`; `PROJECT_STATE.md`; `docs/DOCUMENTATION_INDEX.md`; `docs/mapeamento/05_avaliacao_refactor.md`; `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`; `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md` | Zero production/test/snapshot/database mutation. This B5-P-R3 closeout is historical; PHASE 4-B5 implementation is governed by the B5/B5-R3 rows below |
| PHASE4-B5 | Extract the Matrizes admin blueprint: `app.views.admin.matrizes` owns exactly 10 global legacy endpoints / 12 route-method pairs and 21 corrected helpers; `main` identity re-exports with zero local bodies; factory keyword-only `register_admin_matrizes_blueprint=True`; RBAC exactly 3 view / 7 edit / 2 full; `app.auth` and `app.admin_access` unchanged; zero `app -> main`; ensures/SQL/transaction/UI/messages/CSRF frozen | CLOSED / ACCEPTED | `2a122357a79080fa66aa19c00ed5ff8533308f41`; subject `Extract admin matrices blueprint`; parent `ef874b9d14b02656a0f26ea885024a280d49682e`; published manifest exactly 17 paths | Authorized subject `Record acceptance of Phase 4-B5` (B5-R6 governance closeout); identity resolves through Git history; post-publication verification COMPLETE | Baseline/test integrity: HEAD `ef874b9d14b02656a0f26ea885024a280d49682e` (`Record acceptance of Phase 4-B5-P`); protected `main` `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`; preimplementation ownership/governance nodes 3 passed; corrected TDD RED `20 failed / 4 passed / 0 collection errors`; primary B5 GREEN `24 passed / 3.74s`; focused expanded (44 files) `578 passed / 249.33s`; first full `1049 passed / 1 failed / 17 deselected / 370.60s` (sole failure: configuracoes package membership; HARD STOP); final full hermetic fresh `1050 passed / 17 deselected / 0 failed / 0 errors / 317.65s` (collected 1067); accepted post-publication bounded lane `59 passed / 0 failed / 0 errors / 22.59s`; accepted technical review: FREE `ses_03adb7f27ffeJ1feNSLhrFij5R` exit 1 / fallback `ses_03ad0a15dffeR53I9BqGU6a4tl` `FALLBACK_FREE_EXECUTION_FAILURE` exit 0 cost `0.001000188` mutation 0 PASS / SCOPE EXACT / BEHAVIOR PRESERVED blocking 0 nonblocking 4; independent technical read-only review COMPLETE / PASS (READ-ONLY, mutation 0, verdict PASS / SCOPE EXACT / BEHAVIOR PRESERVED; gates 51 passed / 6.19s + supplemental 3 passed; initial/final manifest and identities identical); routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC unmapped 0; actor 402 = 263 + 139; message catalog 536; route inventory byte-identical; CSRF `[8, 8]` owner-only; canonical SQLite opens 0; `app/admin_access.py` byte-identical. Exact 11-path technical manifest (3 production + 8 tests/snapshots) within ceiling 18 after governance. Void names `_get_grupos_atividade`/`_get_matriz_active_norma_ids` absent (classification `SUPERVISOR CONTRACT CORRECTION / NOT A PATH-POOL EXPANSION / NOT A DOMAIN-SCOPE EXPANSION`) | `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md` | Section-22 pre-implementation reconciliation gate NOT executed before first B5 production mutation (SECTION_22_PROCESS_DEVIATION VALID / ORIGINAL ORDERING REQUIREMENT NOT SATISFIED / DISCOVERED BEFORE PUBLICATION / LATE RECONCILIATION EXECUTED GREEN / TECHNICAL IMPACT NONE DEMONSTRATED / SUPERVISOR ADJUDICATION ACCEPTED_NONBLOCKING_GOVERNANCE_DEBT / PREPUBLICATION_PROCESS_DEVIATION / LATE_GATES_GREEN / NO_RETROACTIVE_COMPLIANCE_CLAIM); B5-R4 hard stop and B5-R5 single waiver preserved as history; publication verified; later cohorts unauthorized; migration v4 prohibited; Phase 4 not closed |
| PHASE4-B5-R3 | Synchronize canonical governance with the PHASE 4-B5 implementation candidate | HISTORICAL / SUPERSEDED (pre-publication documentary synchronization; superseded by PHASE4-B5-R6 acceptance) | N/A (governance-only; no technical correction) | None yet; future technical subject `Extract admin matrices blueprint`; external supervisor review PENDING | Exact six-path governance manifest incl. new `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md`; candidate still unstaged/uncommitted/unpushed at HEAD `ef874b9d14b02656a0f26ea885024a280d49682e`; B5-R3 one-for-one mutable-pool substitution (removed `tests/test_ref_0c_b1_p0_access_context_transactions.py` mutation authorization, read-only focused gate; added `tests/test_phase4_configuracoes_blueprint.py` membership; node 1 passed / 0.64s; affected focused 143 passed / 24.30s); independent technical review COMPLETE / PASS recorded (FREE technical failure `ses_03adb7f27ffeJ1feNSLhrFij5R`; accepted fallback `ses_03ad0a15dffeR53I9BqGU6a4tl` `FALLBACK_FREE_EXECUTION_FAILURE`, cost `0.001000188`; mutation 0); frozen identities recorded; zero production/test/snapshot/database mutation by this documentary delta | `AGENT_HANDOFF.md`; `PROJECT_STATE.md`; `docs/DOCUMENTATION_INDEX.md`; `docs/mapeamento/05_avaliacao_refactor.md`; `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`; `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md` | External supervisor review/acceptance and publication PENDING (phase-time); do not claim acceptance; shared-owner contract untouched. Superseded by PHASE4-B5-R6. |
| PHASE4-B5-R6 | Governance-only closeout of PHASE 4-B5 external acceptance | CLOSED / ACCEPTED / GOVERNANCE CLOSEOUT PUBLISHED | N/A (governance-only; zero technical mutation) | Authorized subject `Record acceptance of Phase 4-B5`; identity resolves through Git history; no future closeout SHA claimed | Exact six-path governance manifest: `AGENT_HANDOFF.md`, `PROJECT_STATE.md`, `docs/DOCUMENTATION_INDEX.md`, `docs/mapeamento/05_avaliacao_refactor.md`, `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`, `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md`. Records technical commit `2a122357a79080fa66aa19c00ed5ff8533308f41` (subject `Extract admin matrices blueprint`) / parent `ef874b9d14b02656a0f26ea885024a280d49682e`; publication COMPLETE; post-publication verification COMPLETE; final hermetic 1050/17/317.65s; post-publication bounded lane 59 passed/22.59s; routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC unmapped 0; actor 402 = 263 + 139; message catalog 536; route inventory byte-identical; CSRF `[8, 8]` owner-only. Section-22 pre-implementation reconciliation gate NOT executed before first B5 production mutation — recorded truthfully (`SECTION_22_PROCESS_DEVIATION: VALID / ORIGINAL ORDERING REQUIREMENT: NOT SATISFIED / DISCOVERED: BEFORE PUBLICATION / LATE RECONCILIATION: EXECUTED / GREEN / TECHNICAL IMPACT: NONE DEMONSTRATED / SUPERVISOR ADJUDICATION: ACCEPTED_NONBLOCKING_GOVERNANCE_DEBT / PREPUBLICATION_PROCESS_DEVIATION / LATE_GATES_GREEN / NO_RETROACTIVE_COMPLIANCE_CLAIM`); the closeout resolves the governance debt by recording it, not by rewriting history; B5-R4 hard stop (correctly detected the missing required Section-22 record before publication and withheld publication) and B5-R5 external-supervisor waiver (superseded only the pre-push documentary blocker; no retroactive compliance claim; authorized publication of the frozen technical commit unchanged; single normal fast-forward; no force/main/tag/PR) preserved as history | `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md` | Zero production/test/snapshot/database mutation by this closeout; governance publication recorded as the intended/authorized closeout state; no next cohort named or authorized; shared-owner contract untouched |
| PHASE4-B6-A | Diagnose the neutral Alunos/Turmas/Cursos shared-owner cut required as the Alunos/Turmas/Cursos blueprint prerequisite; prove the exact nine-symbol closure (owners 3/5/1), main identity re-exports, direct-import consumer reduction, residual lazy map, import isolation and zero-route boundary | DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED | N/A (diagnosis only; prerequisite implemented by B6-P) | B6-P technical implementation satisfies the prerequisite; B6-P governance closeout complete | Read-only diagnosis; supervisor correction identified exactly the nine shared symbols below and **excluded `periodo_corrente`** (remains local in `main`, AST-identical to parent); no route/factory/endpoint/RBAC/CSRF/schema movement diagnosed | `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_SHARED_OWNER_CONTRACT.md` | PHASE 4-B6-P CLOSED / ACCEPTED; PHASE 4-B6 blueprint extraction NOT AUTHORIZED |
| PHASE4-B6-P | Establish the neutral Alunos/Turmas/Cursos shared-owner prerequisite: extract exactly nine shared symbols to neutral owners 3/5/1 — `app.academics` (3: `build_turma_aluno_matricula`, `resequence_turma_aluno_matriculas`, `resequence_turma_aluno_matriculas_for_ids`), `app.user_accounts` (5: `_access_defaults_map`, `_default_password_for_user_type`, `create_usuario_with_default_access`, `create_usuario_with_default_password`, `normalize_usuario_access_for_user_type`), `app.web.request` (1: `_is_ajax_request`) — with `main` identity re-exports and zero local bodies/wrappers/duplicates, direct `app.views.core` import of `normalize_usuario_access_for_user_type` leaving the residual lazy map exactly `aluno_url`/`get_db_connection`/`logger`, preserved login transaction flow (`normalize -> conn.commit() -> refreshed SELECT`), `periodo_corrente` local AST-identical to parent, no new owner → `main` edge/cycle, and no route movement | CLOSED / ACCEPTED | Accepted technical commit `0b003c5f00e5e6181c9b9a5f96d8572b8488323f`, subject `Extract B6 shared neutral owners`, parent `1bf5173949b0bf0bdce15d1b87d6ed15d535158c`; accepted recovery commit `5af7fc70547fccbfed42ebaf5ca353365371c892`, subject `Repair B6-P post-publication governance state`; protected `main` `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1` | External supervisor acceptance GRANTED; technical publication COMPLETE; post-publication recovery COMPLETE; post-publication verification COMPLETE; governance closeout subject `Record acceptance of Phase 4-B6-P` | Historical TDD/scanner-owner chronology preserved (not rewritten): structural RED `13 failed / 31 passed`; structural GREEN `44 passed`; focused `203 passed / 2 failed` (scanner-owner findings, catalog RED 535 / key `msg_4642b1608cf6a126` absent → R1 GREEN 536). B6-P-R1 literal `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED / MESSAGE_SCANNER_OWNER_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY` (RED catalog 535 key `msg_4642b1608cf6a126` absent → GREEN catalog 536, exact default `"Turma sem código para gerar matrícula."`, source `app/academics.py`, no duplicate; in-memory monkeypatch discrimination; scanner provenance literal: the moved `ValueError` message usage/source owner changed from `main.py` to `app/academics.py` while key and exact default text remained unchanged — the message itself did not change); B6-P-R3 literal `PRE_REVIEW_SCOPE_EXPANSION / ONE_FOR_ONE_TEST_POOL_SUBSTITUTION_PLUS_FOUR_ADDITIONS / STALE_GOVERNANCE_TEST_RECONCILIATION / MESSAGE_SCANNER_ALLOWLIST_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY` (`test_residual_shared_helpers.py` unchanged read-only gate; first full 1061/5/17/410.35s, canonical opens 0; five-node recovery 5/5/1.06s; coupled five-file lane 77/77/11.26s; fresh final full collected 1083 = 1066 passed + exactly 17 deselected / 0 failed / 0 errors / 328.77s / exit 0 / `CANONICAL_SQLITE_OPENS=0`); earlier focused 206 passed/117.65s/exit 0 (first harness exit 1 = recoverable MSYS `/c`→`D:/c` basetemp defect; native `C:/` rerun passed); R1 CSRF nodes 2/2, B6-P CSRF delta `[0,0]`; routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC unmapped 0; actor 402 = 263 + 139; message catalog 536; route inventory 20814 bytes / `6e32148c…49fa`; CSRF shadows each 288509 bytes / `4b16f1b4…769`; canonical database 544768 / `a3a55e63…70fe9`, WAL/SHM/journal absent, opens 0; protected residual 17420 / `7388cfbc…bb0e`; zero B6 route movement; **PHASE 4-B6 route extraction NOT AUTHORIZED** | `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_SHARED_OWNER_CONTRACT.md` | PHASE 4-B6 NOT AUTHORIZED; B6 route extraction NOT AUTHORIZED; technical publication, post-publication recovery and verification COMPLETE; external supervisor acceptance GRANTED; permanent pre-publication invocation-error record preserved without retroactive GREEN claim; later cohorts unauthorized; migration v4 prohibited; Phase 4 not closed |
| PHASE4-B6-P-R6 | Governance-only closeout of PHASE 4-B6-P external acceptance | CLOSED / ACCEPTED / GOVERNANCE CLOSEOUT AUTHORIZED | N/A (governance-only; zero technical mutation) | Authorized subject `Record acceptance of Phase 4-B6-P`; identity resolves through Git history | Exact six-path governance pool; accepted technical commit `0b003c5f00e5e6181c9b9a5f96d8572b8488323f` / parent `1bf5173949b0bf0bdce15d1b87d6ed15d535158c`; accepted recovery commit `5af7fc70547fccbfed42ebaf5ca353365371c892`; technical publication, post-publication recovery and verification COMPLETE; external supervisor acceptance GRANTED; full hermetic 1066/17/0/0/canonical opens 0; independent review PASS/blocking 0; recovery node 1/0; bounded post-publication 162/0/0; published-tree bounded 162/0/0; permanent `PREPUBLICATION_BOUNDED_GATE_INVOCATION_ERROR / DISCOVERED_POST_PUBLICATION / NO_RETROACTIVE_GREEN_CLAIM` record; invalid command did not execute pytest | `AGENT_HANDOFF.md`; `PROJECT_STATE.md`; `docs/DOCUMENTATION_INDEX.md`; `docs/mapeamento/05_avaliacao_refactor.md`; `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`; `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_SHARED_OWNER_CONTRACT.md` | PHASE 4 remains OPEN / INCREMENTAL IMPLEMENTATION; PHASE 4-B6, Phase 5 and Phase 6 NOT AUTHORIZED; Migration v4 PROHIBITED |
| PHASE4-B6 | Extract the exact Alunos/Turmas/Cursos admin blueprint into `app.views.admin.alunos_turmas_cursos`: 17 global legacy endpoints / 24 route-method pairs / 10 helpers; preserve 27 main identity re-exports, B6-P owners, accepted registrar/factory isolation, RBAC 6/13/5 and zero `app -> main`; apply only the R1 three-dead-context exception | CLOSED / ACCEPTED | `3d9660a99e6944ff94a3991a353ecf3aaf300987`; subject `Extract admin alunos turmas cursos blueprint` | External supervisor acceptance GRANTED; governance closeout published by R3 | RED 25 = 6 passed / 19 failed / 0 errors; primary GREEN 28; CSRF regeneration 2 and B6 11 owner-only; focused 254; initial full 1093 passed / 2 stale cumulative-CSRF failures / 17 deselected; R2 direct 2 passed; structural/global 34 passed; pre-freeze full collected 1112 = 1095 passed + 17 deselected / 0 failed/errors / 433.87s / exit 0 / `CANONICAL_SQLITE_OPENS=0`; selective-staging whitespace and B1 ledger compatibility correction; first recovery full 1093/2/17; focused recovery 2/2; repeated final full 1095/17/0/0/318.06s/exit 0/opens 0; exact historical CSRF partitions Matrizes 8+11=19 and Requisições 5+8+11=24; routes 131; endpoints 130; business pairs 160; governed 134; unmapped 0; actor 402=263+139; catalog 536; route inventory byte-identical | `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_BLUEPRINT_CONTRACT.md` | B6 closed/accepted. Phase 5/6 and Arquivos/Alertas/Reportes unauthorized; Migration v4 prohibited. |
| PHASE4-B6-R1 | Resolve the original `periodo_corrente` ownership contradiction without moving/copying/aliasing it: remove exactly three dead template-context kwargs from `admin_detalhes_curso`, `admin_turmas`, `admin_detalhes_turma`; preserve legitimate `_build_admin_dashboard_turma_cards` consumer and all other bodies | CLOSED / ACCEPTED as incorporated supervisor correction | Included in the accepted B6 technical commit `3d9660a99e6944ff94a3991a353ecf3aaf300987` | External supervisor acceptance GRANTED | Zero template consumers proved; exactly three deletions and no fourth; `periodo_corrente` main-local byte/AST unchanged; ten helpers AST-identical; 17 handlers equivalent modulo route decorators and these exact deletions; new module has no binding | `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_BLUEPRINT_CONTRACT.md` | `SUPERVISOR_CONTRACT_CORRECTION / NO_PATH_POOL_EXPANSION / NO_DOMAIN_SCOPE_EXPANSION / DEAD_TEMPLATE_CONTEXT_REMOVAL_ONLY` |
| PHASE4-B6-R2 | Recover the interrupted B6-R1 candidate; adjudicate exact cumulative CSRF test corrections; complete final technical qualification and synchronize six-path governance before frozen independent review | CLOSED / ACCEPTED as part of B6 acceptance | N/A as a separate commit; included in accepted B6 technical commit | External supervisor acceptance GRANTED | Preserved historical 1093/2/17 full; exact corrected tests 2/2; structural/global 34/34; pre-freeze full 1095/17/0/0; first recovery full 1093/2/17; focused recovery 2/2; repeated final full 1095/17/0/0/318.06s; custody unchanged; exact test expansion only `tests/test_phase4_matrizes_blueprint.py` and `tests/test_phase4_requisicoes_blueprint.py`; no weakened assertions | `AGENT_HANDOFF.md`; `PROJECT_STATE.md`; `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_BLUEPRINT_CONTRACT.md` | R2 gates satisfied; B6 now CLOSED / ACCEPTED. |
| PHASE4-B7-A | Read-only diagnosis of the Arquivos/Alertas/Reportes cohort: exact route/helper/RBAC/CSRF/filesystem/database inventory and classification of whether the cohort is a single safe blueprint, requires split, requires a shared-owner prerequisite, or is blocked by a cross-domain dependency | CLOSED / ACCEPTED (DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE_REQUIRED) | N/A (diagnosis only; prerequisite implemented by B7-P) | Accepted by the PHASE 4-B7-P-R3 governance closeout order | 12 endpoints / 13 route-method pairs (5 Arquivos, 4 Alertas, 3 Reportes); RBAC already fully mapped centrally in `app/auth.py` independent of module location; Reportes has zero shared-owner debt (`ensure_reportes_table` already `app.db_maintenance`-owned since Phase 3-B1, `REPORTE_CATEGORY_OPTIONS` already `app.reporting`-owned); Arquivos/Alertas share exactly four symbols (`ensure_admin_arquivos_table`, `get_admin_arquivo`, `ensure_admin_alertas_table`, `list_active_admin_alertas`) consumed by the already-extracted `app/views/aluno.py` blueprint via a test-frozen lazy `main` bridge and by `main.uploaded_file`/`main.admin_dashboard` directly; no canonical database opened or queried during diagnosis | `docs/refactor/PHASE4_ARQUIVOS_ALERTAS_SHARED_OWNER_CONTRACT.md` | PHASE 4-B7-P implements the accepted prerequisite; PHASE 4-B7 blueprint route extraction remains NOT AUTHORIZED |
| PHASE4-B7-P | Establish the neutral Arquivos/Alertas shared-owner prerequisite: extract exactly four shared symbols to neutral owners 2/1/1 — `app.db_maintenance` (2: `ensure_admin_arquivos_table`, `ensure_admin_alertas_table`, joining the pre-existing `ensure_reportes_table`), new `app.admin_files` (1: `get_admin_arquivo`), new `app.admin_alerts` (1: `list_active_admin_alertas`) — with `main` identity re-exports and zero local bodies, `app/views/aluno.py` direct imports of all three consumed symbols reducing its lazy `main` bridge from 5 keys to exactly `get_student_request_update_alert`/`mark_student_request_updates_seen`, AST-equivalent moved bodies, and no route movement | CLOSED / ACCEPTED | `1c82a1954250aa5e6654349ce77a50d60f03fe8f`; subject `Extract B7 shared neutral owners`, parent `b6d6e2295e2beeba046cfe1f4c1614f667261ad2` | Authorized subject `Record acceptance of Phase 4-B7-P` (PHASE4-B7-P-R3); external supervisor technical acceptance GRANTED; identity resolves through Git history | RED (new `tests/test_phase4_arquivos_alertas_shared_owners.py`, 11 collected): 7 failed / 4 passed, exit 1, all failures attributable solely to the absent prerequisite; GREEN: 11 passed, exit 0. B7-P-R2 supplemental-scope correction (supervisor-authorized): identical one-for-one 5→2 aluno-lazy-map fix applied to two additional frozen assertions outside the named pool, `tests/test_db_schema_maintenance.py::EXPECTED_ALUNO_LAZY_KEYS_AFTER_VERSIONING_EXTRACTION` and `tests/test_phase4_versioning_subsystem.py::REMAINING_ALUNO_MAIN_HELPERS`, classification `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED / ALUNO_LAZY_MAP_INVARIANT_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY`. B7-P-R2 environmental waiver (supervisor-authorized): full default suite `1103 passed / 3 failed / 17 deselected`, 329.53s, exit 1 — **NOT claimed GREEN**; exact three failures (`test_phase3_final_init_cutover.py::test_seed_tool_uses_factory_owner_without_main_and_is_idempotent`, `test_pytest_runtime_isolation.py::TestSubprocessImportMain::test_import_main_uses_runtime_root`, `test_pytest_runtime_isolation.py::TestMainNoOverwrite::test_import_main_preserves_upload_folder`) independently reproduced identical on a disposable `git worktree` of unmodified entry baseline `b6d6e2295e2beeba046cfe1f4c1614f667261ad2`; classification `PRE_EXISTING_BASELINE_REPRODUCED / ENVIRONMENTAL_ENCODING_FAILURE / UNRELATED_TO_B7_P / ACCEPTED_NONBLOCKING_RESIDUAL / NO_RETROACTIVE_GREEN_CLAIM`; neither file modified or added to the mutable pool. B7-P-specific/affected focused gates 0 failed/0 errors/exit 0: targeted lane 69 passed/19.97s; global-invariant lane 36 passed/29.72s. Routes 131; endpoints 130; business pairs 160; RBAC unmapped 0 (baseline artifact zero `git diff`); route inventory byte-identical (baseline artifact zero `git diff`); message catalog 536; canonical `database.db` 544768 bytes / SHA-256 `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9` unchanged before/after full suite; WAL/SHM/journal absent both times. Exact manifest: production 5 + tests 4 (2 original + 2 R2-supplemental) + governance 6 = 15 paths; path 16 hard stop absent further authorization. Pre-existing residual debt recorded, not repaired: `_best_effort_remove_admin_arquivo_file` path-containment observation (low-risk, server-generated filenames only); phantom `sgaa_canonical_db_guard` documentary-only debt (not invoked, not created) | `docs/refactor/PHASE4_ARQUIVOS_ALERTAS_SHARED_OWNER_CONTRACT.md` | PHASE 4-B7 route/blueprint extraction remains NOT AUTHORIZED; technical publication and external supervisor technical acceptance COMPLETE/GRANTED (see PHASE4-B7-P-R3 row); agent routing disclosure preserved: ordered IAsup/IAexec router not invocable in this harness, acting session performed diagnosis and implementation directly, no Pro/Luna/GPT escalation; external supervisor subsequently performed independent repository review as part of the R3 closeout |
| PHASE4-B7-P-R3 | Governance-only closeout of PHASE 4-B7-P external supervisor acceptance | CLOSED / ACCEPTED / GOVERNANCE CLOSEOUT PUBLISHED | N/A (governance-only; zero technical mutation) | Authorized subject `Record acceptance of Phase 4-B7-P`; identity resolves through Git history | Exact six-path governance manifest: `PROJECT_STATE.md`, `AGENT_HANDOFF.md`, `docs/DOCUMENTATION_INDEX.md`, `docs/mapeamento/05_avaliacao_refactor.md`, `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`, `docs/refactor/PHASE4_ARQUIVOS_ALERTAS_SHARED_OWNER_CONTRACT.md`. Records accepted technical commit `1c82a1954250aa5e6654349ce77a50d60f03fe8f` (subject `Extract B7 shared neutral owners`) / parent `b6d6e2295e2beeba046cfe1f4c1614f667261ad2`; technical publication COMPLETE; post-publication bounded verification COMPLETE; external supervisor technical acceptance GRANTED; bounded pre-push and post-push governance lane both 0 failed / 0 errors / exit 0; full default suite `1103 passed / 3 failed / 17 deselected` preserved truthfully as NOT GREEN, classification `PRE_EXISTING_BASELINE_REPRODUCED / ENVIRONMENTAL_ENCODING_FAILURE / UNRELATED_TO_B7_P / ACCEPTED_NONBLOCKING_RESIDUAL / NO_RETROACTIVE_GREEN_CLAIM` unchanged; phantom `sgaa_canonical_db_guard` debt and `_best_effort_remove_admin_arquivo_file` containment residual preserved unrepaired; routing/reviewer deviation preserved (ordered router not invocable, implementation performed by Claude, external supervisor independent review performed as part of this closeout, deviation accepted nonblocking) | `docs/refactor/PHASE4_ARQUIVOS_ALERTAS_SHARED_OWNER_CONTRACT.md` | Zero production/test/snapshot/database mutation by this closeout; governance publication recorded as the intended/authorized closeout state; no next cohort named or authorized; PHASE 4-B7 route/blueprint extraction remains NOT AUTHORIZED |
| Fase 4 | Admin blueprint extraction | OPEN / INCREMENTAL IMPLEMENTATION / B1-B3 CLOSED / ACCEPTED / B4-A CLOSED / ACCEPTED / B4.1 CLOSED / ACCEPTED / B4.2 CLOSED / ACCEPTED / B5-A DIAGNOSIS COMPLETE / B5-P CLOSED / ACCEPTED / PHASE 4-B5 CLOSED / ACCEPTED / PHASE 4-B6-P CLOSED / ACCEPTED / PHASE 4-B6-R1 AND PHASE 4-B6 CLOSED / ACCEPTED / PHASE 4-B7-A CLOSED / ACCEPTED / PHASE 4-B7-P CLOSED / ACCEPTED | B1-B7-P identities in their rows | B6 external supervisor acceptance GRANTED; governance closeout published by R3. B7-P external supervisor technical acceptance GRANTED; governance closeout published by PHASE4-B7-P-R3 | Current B6 final hermetic 1095 passed / 17 deselected / 0 failed/errors / 318.06s; B7-P GREEN focused gates 69+36 passed / 0 failed/errors; B7-P full default suite 1103 passed / 3 failed (pre-existing, baseline-reproduced, unrelated, waived) / 17 deselected; earlier accepted evidence preserved | `docs/mapeamento/05_avaliacao_refactor.md`; phase contracts | `dashboard.py` and `admin_meus_dados` ownership unresolved; Phase 4 not closed. PHASE 4-B7 route extraction, Phase 5/6 unauthorized; Migration v4 prohibited; no later cohort. |
| Fase 4 (historical through B6-P) | Admin blueprint extraction | OPEN / INCREMENTAL IMPLEMENTATION / B1-B3 CLOSED / ACCEPTED / B4-A CLOSED / ACCEPTED / B4.1 CLOSED / ACCEPTED / B4.2 CLOSED / ACCEPTED / B5-A DIAGNOSIS COMPLETE / B5-P CLOSED / ACCEPTED / PHASE 4-B5 CLOSED / ACCEPTED / PHASE 4-B6-A DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED / PHASE 4-B6-P CLOSED / ACCEPTED | B1 `cd8a76b2484abc376174332578ecd8be4b8206ea`; B2 `17e468ad938e873e1f9e9c303808ad31b9f3806b`; B3 `50801b6bdddc4d2772853c13f4905c49e8c996cf`; B4.1 `73ebf0dc34681e74e778759af476e1cd2f981444`; B4.2 `3231dbd2ff9759d8f855f2a4118102783aedea83`; B5-P `92486f87ea15697282a265cb7a9941678cb9138f`; B5 `2a122357a79080fa66aa19c00ed5ff8533308f41` (parent `ef874b9d14b02656a0f26ea885024a280d49682e`); B6-P accepted technical commit `0b003c5f00e5e6181c9b9a5f96d8572b8488323f`, parent `1bf5173949b0bf0bdce15d1b87d6ed15d535158c`, plus accepted recovery commit `5af7fc70547fccbfed42ebaf5ca353365371c892`; B6 accepted technical commit `3d9660a99e6944ff94a3991a353ecf3aaf300987` | B5-P-R3 closeout `Record acceptance of Phase 4-B5-P`; B5-R6 closeout `Record acceptance of Phase 4-B5`; B6-P technical publication, post-publication recovery and verification COMPLETE; external supervisor acceptance GRANTED; R6 governance closeout `Record acceptance of Phase 4-B6-P`; closeout identity resolves through Git history; B6 governance closeout `Record acceptance of Phase 4-B6` published by R3 | B1/B2/B3/B4-A/B4.1/B4.2 accepted evidence preserved; B5-P evidence preserved with final pre-publication hermetic 1025/17/326.74s, independent-review rerun 367.27s and post-publication focused 132/39.23s; B4.2 and B5-P technical publication and post-publication verification complete; B5 evidence: corrected RED 20/4, primary GREEN 24/3.74s, focused expanded 578/249.33s, first full 1049/1/17, final hermetic 1050/17/317.65s, reviewer gates 51+3, CSRF [8,8], routes 131, message catalog 536; B6-P accepted prerequisite (see PHASE4-B6-P row): R1 and R3 literals recorded; fresh final full 1066/17/0/0/328.77s/exit 0/`CANONICAL_SQLITE_OPENS=0`; focused 206/117.65s; routes 131; message catalog 536; CSRF shadows byte-identical 288509 bytes each / `4b16f1b4…769`; canonical SQLite opens 0; zero B6 route movement; PHASE 4-B6 CLOSED / ACCEPTED at technical commit `3d9660a99e6944ff94a3991a353ecf3aaf300987`; external supervisor acceptance GRANTED; governance closeout published by R3 | `docs/mapeamento/05_avaliacao_refactor.md`; Phase 4 B1/B2/B3/B4.1/B4.2 contracts; `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md` (B5-P); `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md` (B5); `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_SHARED_OWNER_CONTRACT.md` (B6-P) | PHASE 4-B5 CLOSED / ACCEPTED (technical publication and post-publication verification COMPLETE; Section-22 process deviation recorded; B5-R6 governance closeout published); later cohorts unauthorized; `dashboard.py` and `admin_meus_dados` ownership unresolved; migration v4 prohibited; Phase 4 not closed; PHASE 4-B6-P CLOSED / ACCEPTED — technical publication, post-publication recovery and verification COMPLETE; external supervisor acceptance GRANTED; PHASE 4-B6 route extraction NOT AUTHORIZED |
| Fase 5 | Backup/sync offloading | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized |
| Fase 6 | `main.py` as entrypoint only | NOT AUTHORIZED | N/A | N/A | N/A | `docs/mapeamento/05_avaliacao_refactor.md` | Unauthorized |

Executable Phase-3 compatibility note: the former table token `| Fase 4 | Admin blueprint extraction | NOT AUTHORIZED |` is retained here as a historical assertion only. It was superseded only for the explicitly authorized B1, B2 and B3 units and does not authorize B4 or close Phase 4.

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

**Historical snapshot custody: OPEN / DESTINATION PROVISIONED / COPY VERIFIED /
PARENT ACL HARDENING APPLIED AND VERIFIED / SOURCE PRESERVED /
LEVEL 2 PHYSICAL RESTORATION COMPLETE AND ACCEPTED / LEVEL 3 NOT EXECUTED /
SECURITY-COMPLETE CUSTODY NOT CLAIMED.**
R1: CLOSED / ACCEPTED. Custody policy: APPROVED.
R2: CLOSED / ACCEPTED. Destination: SELECTED — `D:\programas\SGAA_Historical_Custody`.
R3: CLOSED / ACCEPTED. Provisioning and copy contract approved.
R4: EXECUTED. Physical provisioning, copy, integrity verification complete.
R5: CLOSED / ACCEPTED. Option B strict approved; its not-applied state is historical.
R6: CLOSED / ACCEPTED WITH DECLARED POST-MUTATION NONCONFORMITY. Execution classification:
POST-MUTATION HARD STOP. Physical DACL outcome: TARGET APPLIED / INDEPENDENTLY VERIFIED.
R7: CLOSED / ACCEPTED. Level 2 execution contract READY; documentary closeout published.
Level 2 physical restoration: COMPLETE / LOCALLY VERIFIED / SUPERVISOR ACCEPTED, in restore
root `D:\tmp\sgaa_restore_20260726T165550Z`, validator SQLITE_LEVEL2_CHECKS_PASS,
evidence 7/7, custody unchanged 17/17 and 4,808,704 bytes, source preserved.
Restore root: PRESERVED until a separate explicit cleanup order.
New SQLite opening: NOT AUTHORIZED.
Physical action (additional copy/move/delete/compress/cleanup): NOT AUTHORIZED.
Further parent ACL application: NOT AUTHORIZED / PROHIBITED.
Level 3 operational restoration: NOT STARTED / NOT AUTHORIZED.
Separate governance/administrative track. Does not integrate Phase 1, Phase 2,
or any architectural implementation phase.
See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.

Exact next action:

Supervisor review of the Level 2 acceptance record. No further custody action is
authorized; restore-root cleanup, any new SQLite opening, the fallback candidate,
Level 3 and Phase 2 each require a new separate explicit human order.

No physical order is issued by this record.

Historical / superseded next action: "a new separate explicit human physical Level 2
order restricted to the primary candidate and containing a concrete literal timestamped
root matching `D:\tmp\sgaa_restore_<UTC>`" — satisfied by the executed and accepted
Level 2 restoration.

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

Exact next action (phase-time, superseded by R33 and R34 below):

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R4 — controlled provisioning, ACL application, copy
of the 17 artifacts, manifest creation and integrity verification.

R4 is NOT STARTED. Its contract is APPROVED, but physical execution was explicitly
withheld. R4 requires a separate explicit human order releasing physical execution; the
approval recorded here is not that order and must never be read as one. Phase 2 remains
without authorized next action.

## Governance event — R33 publication of the approved-contract closeout

**Objective:** publish the existing local documentary closeout commit.

**Objective type:** publication only. No document changed.

**Status: PUBLICATION_COMPLETE.**

**Tests:** NOT RUN / PROHIBITED.

**Published commit:** `c39c228054cfc34ed37f593402dcf382c7c29627`
(`Record approved provisioning and copy contract`, parent
`59fa66bb5d73a04713524657bdc761def3d0b9c8`, exactly seven documents, 436 insertions and
73 deletions). Push result `59fa66b..c39c228`, fast-forward, exit 0, non-forced, not
rejected. Post-push local HEAD = upstream = live remote; divergence 0/0; `main` unchanged
at `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`; worktree clean; index empty; zero untracked.

**Zero physical action:** no directory created, no ACL applied, no copy, no SQLite opened.

## Historical / superseded governance event — R34 R4 execution closeout

**Objective:** reconcile the executed R4 physical provisioning and copy against the
repository canon and close it documentally.

**Objective type:** read-only post-execution reconciliation + docs-only closeout.

**Closeout identity:** authorized subject
`Record executed historical custody provisioning and copy`; identity resolved through Git
history.

**Status: CLOSED / ACCEPTED.**

**Tests:** NOT RUN / PROHIBITED. Application not executed. `main.py` not imported.

**Baseline/pre-closeout HEAD:** `c39c228054cfc34ed37f593402dcf382c7c29627`.

**Exact seven-document manifest:**
- `AGENT_HANDOFF.md`
- `PROJECT_STATE.md`
- `docs/DOCUMENTATION_INDEX.md`
- `docs/mapeamento/03_banco_de_dados.md`
- `docs/mapeamento/05_avaliacao_refactor.md`
- `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
- `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`

**R4 outcome recorded:** EXECUTED / PHYSICAL PROVISIONING COMPLETE / COPY COMPLETE /
INTEGRITY VERIFIED / SOURCE PRESERVED. Destination `D:\programas\SGAA_Historical_Custody`
provisioned with `artifacts\` (17 files, 4,808,704 bytes, zero subdirectories),
`manifests\custody-manifest-20260725T233026Z.json` (16,872 bytes, SHA-256
`8552c289acfa0067a24848b960383446ffb1b5663a324515bac9309a65a9f0c3`) and
`evidence\r4-copy-and-verification-20260725T233315Z.md` (4,505 bytes, SHA-256
`82494024c71d374e54b5ed1d2470d86c00738d345ece8179d76967c80ac56d71`). Source aggregate
SHA-256 `44ae5da3f368605ac2550cc65d70d2081d432977c48fad1f467884a65f2e3be3` unchanged before
and after the copy. Per-file destination SHA-256 equals source equals canonical inventory
for all 17. SQLite NOT OPENED. Restoration Level 2 and Level 3 NOT EXECUTED. Source removal
NOT AUTHORIZED.

**Pre-execution physical authorization:** EVIDENCED. Authority: PROJECT OWNER. Scope: R4
ONLY. Issued as an explicit human instruction in the Claude Code session immediately before
execution and before the point of no return. Medium: session record, not a repository file;
this closeout is its durable repository record.

**Operational nonconformities:** DECLARED / CONTAINED / NO ARTIFACT INTEGRITY IMPACT / NOT
AN AUTHORIZED PRECEDENT. Three occurrences: `New-Item -LiteralPath` incompatible with
PowerShell 5.1, failing before any creation and replaced by
`[System.IO.Directory]::CreateDirectory`; `Set-Acl` failing with `PrivilegeNotHeldException`
(`SeSecurityPrivilege`) on the post-verification downgrade, corrected by
`DirectoryInfo.SetAccessControl` writing the DACL exclusively; and a first evidence-report
write failing on shell quoting with no partial file created. R4 is not described as a
flawless execution.

**Residual security risk:** PARENT DIRECTORY ACL EXPOSURE OPEN. Security-complete custody:
NOT YET CLAIMED. Correction of record: the R4 execution report asserted a `DELETE_CHILD`
exposure on the parent; direct measurement shows the inherited `Authenticated Users` mask
on `D:\programas` is `0x1301BF`, without `FILE_DELETE_CHILD`, `WRITE_DAC` or `WRITE_OWNER`.
What remains open is `ADD_FILE`/`ADD_SUBDIRECTORY` on the parent, `DELETE` on the parent
object itself, and owner-implicit `WRITE_DAC` over the custody root.

**Zero new physical action in R34:** no directory created, no artifact copied, no file
overwritten, no ACL altered, no residue cleaned, no move or compress, no SQLite opened, no
restoration executed, no external manifest or evidence file modified.

**R5 supersession note:** The R5-phase-time statements above ("R5 is NOT STARTED", "not
authorized to modify D:\programas", etc.) are historical phase-time record preserved in the
R34 section. R5 was subsequently executed as a strict read-only ACL assessment and closed
/ accepted via this closeout. See R5 row in the phase table and the custody document.

Historical phase-time next action, superseded by the current R7 closeout:

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R7 — read-only Level 2 restoration readiness
revalidation and bounded restoration-execution contract.

R7 is NOT STARTED and authorizes no physical Level 2 action: no direct artifact open,
restoration directory, copy, SQLite, application, ACL/source change or restoration.
Any physical Level 2 restoration requires a later separate explicit human order.
Phases 2-6 remain unauthorized.

R7 must revalidate container runtime, the `D:\tmp\sgaa_restore_<UTC>` alternative,
derived-copy-only handling, objective Level 2 criteria, separately authorized cleanup,
and evidence required before any future source removal.

## Historical governance event — R6 post-mutation documentary closeout

**Mode:** IAsup `openai-codex/gpt-5.6-sol`, MEDIUM, read-only reconciliation + docs-only
closeout + selective commit/publication. IAexec FREE session
`ses_06227b5d6ffe5s5DrFi4JTkxYE` returned no final text and was rejected; explicit
Flash-normal complement `ses_06226b324ffeHTsk45kMGIfguu` returned
`CONSULTATIVE_USABLE`. No silent fallback.

**Baseline:** `07fe0666eedbaa76395c278b4c0f798a0d3320ed`, subject
`Record approved R5 parent ACL hardening decision`; exact seven-document allowlist.

**Outcome:** R6 POST-MUTATION HARD STOP; target DACL APPLIED / INDEPENDENTLY VERIFIED;
one `SetAccessControl` call; Apply EXIT 1; post-mutation `PropertyNotFoundStrict` in the
verification/serialization path; no retry or rollback. External evidence hashes and full
physical/integrity evidence are canonical in the custody document.

**Zero new physical mutation:** no ACL call, external-file change, SQLite open,
restoration, source change, test, application, pytest or Phase 2-6 work in this closeout.

**Exact seven-document manifest:**
- `AGENT_HANDOFF.md`
- `PROJECT_STATE.md`
- `docs/DOCUMENTATION_INDEX.md`
- `docs/mapeamento/03_banco_de_dados.md`
- `docs/mapeamento/05_avaliacao_refactor.md`
- `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
- `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`

**Authorized commit subject:** `Record verified R6 parent ACL hardening outcome`.

## Transição para EXECUTION_PROTOCOL v1.1

**Data:** 2026-08-07. **Tipo:** transição de governança única. **Não é uma UT e não é um
closeout de fase.** Commit de adoção parte 1, assunto `Adopt execution protocol for remaining
refactor`, sobre o HEAD de entrada `c3853220189c0d6c279b2f169e0fdc68924c00d1`.

**Motivo.** O aparato de governança por fase (um contrato `.md` dedicado por unidade, um commit
de closeout separado, manifesto de caminhos com teto numérico e registro de sessão/custo/hash de
revisor) tornou-se o maior artefato do repositório: 1,41 MB de markdown de governança contra
0,92 MB de Python de produção, razão 1,54:1. O custo por unidade deixou de ser proporcional ao
trabalho técnico entregue. A partir desta transição, a autoridade operacional do trabalho
remanescente passa a ser um documento único, `docs/refactor/EXECUTION_PROTOCOL.md`, com registro
de aceitação reduzido a uma linha por unidade.

**Autoridade futura de execução.** `docs/refactor/EXECUTION_PROTOCOL.md` (v1.1 FINAL). Escopo,
ordem, invariantes, roteamento de modelos e critérios de parada do trabalho remanescente são
definidos por ele. `PROJECT_STATE.md` permanece o estado vivo; este ledger permanece o registro
histórico. `AGENT_HANDOFF.md` fica congelado como arquivo histórico a partir deste commit.

**Sequência fechada de 14 UTs.**

| UT | Nome | Bloco |
|---|---|---|
| UT-1 | Suíte verde (encoding UTF-8 em subprocess) | A — fundação |
| UT-2 | Unificar composition root (config + headers) + adoção parte 2 | A |
| UT-3 | Migrar os hooks de app para o composition root | A |
| UT-4 | Containment de path em `_best_effort_remove_admin_arquivo_file` | B — runtime e ciclos |
| UT-5 | Fase 5: I/O fora do `after_request`, pacote `app/backup/` | B |
| UT-6 | Fechar ciclo `app → main` | B |
| UT-7 | Helpers `matrizes` → `activity_catalog` | B |
| UT-8 | Coorte Banco de Dados (20 rotas) | C — coortes |
| UT-9 | Coorte Acesso (6 rotas) | C |
| UT-10 | Coorte Arquivos (5 rotas) | D — fechamento condicional |
| UT-11 | Coorte Alertas (4 rotas) | D |
| UT-12 | Coorte Reportes (3 rotas) | D |
| UT-13 | Dashboard + demo + meus_dados (3 rotas) | D |
| UT-14 | Infra: `uploaded_file`, `health`, `favicon` (3 rotas) | D |

Diferidas e não autorizadas: D-1 (dividir `app/db_maintenance.py`), D-2 (RBAC declarativo /
aposentar `LegacyRouteSpec`), D-3 (purga dos re-exports de `main`). Permanecem proibidos
`app/repositories/`, migration v4, o pacote `app/db/`, adicionar símbolos a
`app/admin_access.py` e fundir Arquivos/Alertas/Reportes num único módulo.

**PLATEAU ESTRUTURAL — declarável ao fim da UT-9.** `main.py` sem nenhum hook de app
(`before_request`, `after_request`, `context_processor`, `errorhandler`); `create_app()` como
único sítio de instalação de extensão Flask e de definição de chave de `app.config`; zero
`import main` em `app/`, `services/` e `utils/`; nenhuma escrita em disco, banco ou rede dentro
de hook de requisição; toda rota registrada resolvendo para exatamente um requisito de RBAC ou
exceção aprovada; route inventory e actor matrix verdes; suíte completa 0 failed / 0 errors.

**REFACTOR ESTRUTURAL COMPLETO — declarável ao fim da UT-14.** Os critérios do plateau, mais:
`main.py` sem nenhum `@app.route`; cada coorte de domínio com exatamente um módulo dono e
nenhuma coorte dividida entre `main.py` e `app/`.

**Contratos históricos.** PHASE 4-B1, B2, B3, B4-A, B4.1, B4.2, B5-P, B5, B6-A, B6-P, B6-R1,
B6, B7-A e B7-P **permanecem contratos históricos válidos**. Esta transição não os revoga, não
os reescreve e não reabre nenhuma de suas aceitações. Ela apenas cessa a produção de novos
contratos por unidade.

**Escopo desta transição.** Exatamente três caminhos: `docs/refactor/EXECUTION_PROTOCOL.md`
(novo), `AGENT_HANDOFF.md` (prepend de banner histórico, nenhuma outra alteração) e este ledger
(append no fim do arquivo). `PROJECT_STATE.md` e `docs/DOCUMENTATION_INDEX.md` **não** são
tocados aqui; sua reescrita pertence à adoção parte 2, dentro da UT-2, junto com a
aposentadoria das asserções leitoras de governança. Nenhum caminho de produção, teste,
snapshot ou banco foi alterado.

## UT-1 — Suíte verde (encoding UTF-8 em subprocess/arquivo temporário no Windows)

**Data:** 2026-08-07. **Autoridade:** `docs/refactor/EXECUTION_PROTOCOL.md` v1.1 FINAL, §2 UT-1,
com extensão de escopo autorizada explicitamente em UT-1-R1. **Não gerou contrato de fase nem
commit de governança separado.**

**Escopo original (3 nós nomeados):**
`test_phase3_final_init_cutover.py::test_seed_tool_uses_factory_owner_without_main_and_is_idempotent`,
`test_pytest_runtime_isolation.py::TestSubprocessImportMain::test_import_main_uses_runtime_root`,
`test_pytest_runtime_isolation.py::TestMainNoOverwrite::test_import_main_preserves_upload_folder`.
Causa raiz: `subprocess.run`/`Path.write_text` sem `encoding="utf-8"` explícito caem em
`locale.getpreferredencoding()` (cp1252 nesta máquina), divergente do UTF-8 exigido pelo caminho
do projeto (contém "ç") ou pelo `PYTHONUTF8="1"` do processo filho.

**Quarto ponto (achado pela suíte completa, incorporado por autorização humana UT-1-R1):**
`test_d73d_normative_importer_dryrun.py::test_invalid_fixture_aborts_without_partial_insertion`,
mesma classe de defeito no helper compartilhado `_run_cli`. Reproduzido contra o HEAD de entrada
`2c99f1641387ee115f519ee1517523cd1ecd28c2` com o diff da UT-1 removido via `git stash` — confirmado
pré-existente, não introduzido por esta UT. Classificação:
`PRE_EXISTING_BASELINE_REPRODUCED / SAME_UTF8_ENCODING_DEFECT_CLASS / DISCOVERED_BY_UT1_FULL_SUITE
/ AUTHORIZED_UT1_SCOPE_EXPANSION`.

**Correção do quarto ponto — duas rodadas.** A primeira correção (`encoding="utf-8"` apenas no
decode do lado pai) foi rejeitada pela revisão adversarial: em ambiente sem
`PYTHONIOENCODING`/`PYTHONUTF8` (locale ambiente `cp1252`, confirmado), o processo filho grava em
cp1252 enquanto o pai decodifica como UTF-8 — `subprocess._readerthread` engole o
`UnicodeDecodeError` resultante, deixando `result.stdout`/`result.stderr` como `None` em vez de
levantar exceção, o que transformou a falha do nó-alvo de um `AssertionError` legível em
`TypeError: argument of type 'NoneType' is not iterable`, e regrediu os quatro testes irmãos do
mesmo arquivo que usam o `_run_cli` compartilhado. Classificação:
`MATERIAL_FINDING / SAME_FAMILY_SUBSTITUTE_REVIEW / RETURNED_TO_IMPLEMENTATION`. A correção final
pina também o lado do filho (`environment["PYTHONUTF8"] = "1"` mais `env=environment`),
espelhando o padrão já aprovado em `test_phase3_final_init_cutover.py:329-341`. A segunda rodada
de revisão, rodada explicitamente sem `PYTHONIOENCODING`/`PYTHONUTF8` no shell do revisor para
validar o ambiente real, confirmou o mecanismo determinístico (`PYTHONUTF8=1` fixa a codificação
de stdio do interpretador filho independentemente de tty/pipe) e a ausência de acoplamento de
ordem de teste (`environment = os.environ.copy()` é cópia local por chamada).

**Desvio de governança declarado e não-genérico:** `DeepSeek V4 Pro` está indisponível neste
harness de execução. Toda revisão adversarial desta UT foi feita por um substituto Opus 5,
explicitamente rotulado como não-independente em cada rodada. Classificação:
`INDEPENDENT_CROSS_FAMILY_REVIEW_UNAVAILABLE / DISCLOSED / NONBLOCKING_FOR_TEST_ONLY_ENCODING_PATCH
/ NO_GENERIC_PRECEDENT`. Autorizado apenas para UT-1; não estabelece precedente para as UTs
seguintes, que permanecem sob o roteamento de modelos original da §6.

**Evidência final.** Total de quatro pontos de correção em três arquivos de teste, todos
adicionando `encoding="utf-8"` explícito (mais o pareamento `PYTHONUTF8` do lado do filho no
quarto ponto). Nenhuma asserção alterada, nenhuma exceção suprimida, nenhum teste marcado
skip/xfail, nenhum arquivo de produção tocado. Suíte completa final, ambiente padrão (sem
`PYTHONIOENCODING`/`PYTHONUTF8` no shell): `1106 passed / 0 failed / 0 errors / 17 deselected /
352,06s / exit 0`. Invariantes: rotas 131; endpoints 130; RBAC unmapped 0; actor matrix 402;
catálogo de mensagens 536; `hooks_main` 7; `route_inventory_baseline.json` byte-idêntico;
`database.db` 544768 bytes / SHA-256 `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`
inalterado; sem resíduo `-wal`/`-shm`/`-journal`. A antiga isenção ambiental de três falhas
conhecidas está **retirada** — não há exceção de encoding aceita após esta UT.

**Escopo do commit.** Exatamente quatro caminhos de teste (`tests/test_phase3_final_init_cutover.py`,
`tests/test_pytest_runtime_isolation.py`, `tests/test_d73d_normative_importer_dryrun.py`) mais os
dois documentos de governança (`docs/refactor/EXECUTION_PROTOCOL.md` §10/§11,
`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`, este bloco). `AGENT_HANDOFF.md`,
`PROJECT_STATE.md` e `docs/DOCUMENTATION_INDEX.md` não tocados — permanecem para a Adoção parte 2,
dentro da UT-2. Um único commit técnico; nenhum commit de governança separado.

## UT-2 — Unificação do composition root + Adoção parte 2

**Data:** 2026-08-07. **Autoridade:** `docs/refactor/EXECUTION_PROTOCOL.md` v1.1 FINAL, §2 UT-2 e
§13 "Adoção parte 2". **HEAD de entrada:** `ab1614dd525047e862da00baef975e81eca01c6b`.
**Não gerou contrato de fase nem commit de governança separado.**

**Escopo concluído.** `app/__init__.py::create_app` passa a ser o dono único da configuração de
runtime da aplicação. O bloco de configuração pós-`create_app` de `main.py` foi removido: o
`Compress(app)` duplicado (já registrado em `app/__init__.py:198`), o `MAX_CONTENT_LENGTH`, o
`TEMPLATES_AUTO_RELOAD`/`jinja_env.auto_reload`, a fixação do `jinja_loader.searchpath`, o
`DATABASE_PATH`, os diretórios `LOCAL_BACKUP_DIR`/`CLOUD_BACKUP_DIR`, o
`CLOUD_SYNC_INTERVAL_SECONDS`, as chaves `EXTERNAL_BACKUP_*` e a chamada
`bind_backup_settings_runtime_app(app)` migraram para `create_app`, resolvendo o `project_root`
canonicamente em vez de por `os.path.dirname(os.path.abspath(__file__))` de `main`. `main.py`
retém apenas um comentário normativo proibindo a redefinição desses valores.

**Cabeçalhos de segurança — dono único.** O `add_security_headers` de `main` foi dissolvido. Os
cabeçalhos passam a ser exclusivamente de `app.__init__._apply_security_headers`. Consequência
canônica: `Referrer-Policy` = `strict-origin-when-cross-origin` em todas as respostas, superando o
`no-referrer-when-downgrade` que `main` aplicava via `setdefault`. `X-Content-Type-Options:
nosniff` e `X-Frame-Options: SAMEORIGIN` permanecem.

**`_legacy_post_response_backup_sync` preservado.** O corpo de sincronização/upload de snapshot do
banco que convivia dentro do antigo `add_security_headers` foi isolado num `after_request` próprio
de `main`, renomeado para `_legacy_post_response_backup_sync`. Dono transitório declarado: `main`.
Removido na **UT-5**, quando o I/O de backup migra para `app/backup/`. Não é dívida silenciosa.

**Consequência de ordenação de CSRF.** Com a remoção do `Compress(app)` duplicado de `main`, a
ordem relativa dos `after_request` muda e a injeção `_inject_csrf_into_html`, executada dentro de
`_apply_security_headers`, passa a operar sobre corpos HTML não comprimidos — isto é, torna-se
efetivamente ativa. Classificação: `CSRF_ORDER_CHANGE = SAFE_AND_INTENDED`, explicitamente aceita
pelas duas revisões independentes. O custo de CPU da injeção agora ativa foi adjudicado **dentro**
da UT-2 e não constitui achado fora de escopo.

**Desvio de logging.** `app/__init__.py:306` e `main.py:1254` mantêm cada um seu
`logging.getLogger(__name__)`, preservando um logger `"main"` distinto do logger `"app"`. A
unificação do composition root não unificou a hierarquia de loggers. Classificação: `ACCEPT` —
desvio consciente, logger `"main"` distinto preservado.

**Adoção parte 2 concluída.** `PROJECT_STATE.md` reescrito para a forma de estado vivo (≤40
linhas), `docs/DOCUMENTATION_INDEX.md` atualizado, `AGENT_HANDOFF.md` não tocado e definitivamente
histórico/congelado.

**Aposentadoria de testes leitores de governança.** 6 funções aposentadas em 5 arquivos, conforme a
tabela fechada da §8:
`test_phase3_schema_startup_transaction_contract.py::test_canonical_contract_document_and_governance_registration`,
`::test_macro_phase3_acceptance_closeout_is_current_and_bounded`;
`test_phase4_atividades_blueprint.py::test_b3_r3_governance_closeout_is_canonical`;
`test_phase4_configuracoes_blueprint.py::test_phase4_b1_governance_closeout_is_canonical`;
`test_phase4_versioning_subsystem.py::test_b41_governance_records_exact_scope_and_preserves_later_prohibitions`;
`test_phase4_requisicoes_shared_owners.py::test_phase4_b2_current_governance_records_external_acceptance`.
Nenhuma asserção de comportamento de produção foi removida. Novo teste de contrato adicionado:
`tests/test_ut2_composition_root.py`.

**Revisão adversarial — duas revisões independentes, ambas PASS.** `DeepSeek V4 Pro`: PASS, 0
achados materiais, `CSRF_ORDER_CHANGE = SAFE_AND_INTENDED`, `LOGGING_DEVIATION = ACCEPT`. Segunda
revisão por `Claude Opus 5` em contexto limpo: PASS, 0 achados materiais, todos os eixos UT-2 PASS.
O desvio de governança da UT-1 (revisor substituto não-independente) **não** se repete aqui: a
revisão cross-family exigida pela §6 foi efetivamente executada.

**Evidência final.** Invariantes: rotas 131; endpoints 130; RBAC unmapped 0; actor matrix 402;
catálogo de mensagens 536; `hooks_main` 7; `route_inventory_baseline.json` byte-idêntico;
`database.db` 544768 bytes / SHA-256
`a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9` inalterado; sem resíduo
`-wal`/`-shm`/`-journal`. Inventário de `after_request`: Flask-Compress; `_apply_security_headers`
(dono `app`); `_legacy_post_response_backup_sync` (dono `main`, transitório até UT-5). Suíte
completa de qualificação: `1110 passed / 17 deselected / 0 failed / 0 errors / exit 0`.

**Escopo do commit.** 12 caminhos, commit técnico único: `app/__init__.py`, `main.py`,
`PROJECT_STATE.md`, `docs/DOCUMENTATION_INDEX.md`, `docs/refactor/EXECUTION_PROTOCOL.md` (§11),
`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` (este bloco), os cinco arquivos de teste leitores
de governança aposentados e `tests/test_ut2_composition_root.py`. `AGENT_HANDOFF.md` não aparece.
Nenhum commit de governança separado. §10 não recebeu entrada: nenhum achado fora de escopo
genuinamente novo surgiu nesta finalização.

**Próxima UT:** UT-3 — migrar os hooks restantes de `app` para o composition root.

## UT-3 — Migração dos hooks de app para os donos canônicos em `app/web/`

**Data:** 2026-08-08. **Autoridade:** `docs/refactor/EXECUTION_PROTOCOL.md` v1.1 FINAL, §2 UT-3
e §4 (inventário de hook por módulo dono). **HEAD de entrada:**
`7468a0f3502a7f51537fc9e537d401b4e1dc6f1c`. **Não gerou contrato de fase nem commit de
governança separado.**

**Escopo concluído — migração de dono canônico de hook.** Três módulos novos passam a deter os
corpos que viviam em `main.py`: `app/web/authz_gate.py` (`enforce_admin_access_control`,
`_admin_access_denied_response`, `_audit_missing_admin_authorization_configuration`),
`app/web/context.py` (`inject_admin_access_helpers`, `inject_editable_message_templates`) e
`app/web/errors.py` (`not_found`, `internal_error`, `handle_large_upload`). `main.py` deixa de
declarar esses corpos e passa a registrá-los funcionalmente contra o app composto, sem
decorator. `_format_bytes_label` migra para `app.presentation` e `main` o reexporta por
identidade. As duas únicas alterações de corpo em toda a migração são a substituição de
`app.config` por `current_app.config` em `enforce_admin_access_control` e `handle_large_upload`;
todos os demais corpos são byte-idênticos ao pré-UT-3.

**`hooks_main` 7 → 1.** O único hook Flask que permanece de `main` é
`_legacy_post_response_backup_sync` (dono transitório declarado na UT-2, removido na UT-5). A
medição varreu `before_request`, `after_request`, `context_processor`, `errorhandler`,
`teardown_request`, `teardown_appcontext`, `url_value_preprocessor` e `url_defaults`, em todos
os escopos (app e os oito blueprints): nenhuma registração duplicada ou oculta de `main`.

**Ordem preservada.** `before_request`: `csrf_protect`@`flask_wtf.csrf` e só depois
`enforce_admin_access_control`@`app.web.authz_gate` — CSRF-antes-de-RBAC permanece
determinístico porque `create_app()` executa antes do registro explícito. `context_processor`:
`inject_admin_access_helpers` antes de `inject_editable_message_templates`, ambos em
`app.web.context`. `errorhandler`: 404/500/413 em `app.web.errors`; `CSRFError` continua de
`app`. `after_request` inalterado: Flask-Compress, `_apply_security_headers`@`app`,
`_legacy_post_response_backup_sync`@`main`.

**Compatibilidade por identidade.** `main._admin_access_denied_response` **é** o mesmo objeto
que `app.web.authz_gate._admin_access_denied_response`, e `main._format_bytes_label` **é**
`app.presentation._format_bytes_label`. `inspect.getsource` resolve para o arquivo canônico e
contém `_is_ajax_request()`. Nenhum wrapper, nenhum corpo duplicado.

**Catálogo de mensagens.** `utils.messages::_iter_backend_files()` foi estendido com
`app/web/authz_gate.py` e `app/web/errors.py`; `app/web/context.py` permanece ausente por não
possuir sink próprio. O catálogo continua em **536**: o diferencial contra o HEAD de entrada
acusou zero chave nova ou perdida e zero mudança de texto padrão — apenas quatro mensagens
trocaram de arquivo de atribuição, de `main.py` para os novos donos.

**Fronteiras preservadas.** `app/admin_access.py` com zero diff e exatamente cinco definições
de topo. Nenhuma aresta `app/web/* -> main`, verificada estaticamente e em interpretador limpo.
`route_inventory_baseline.json` byte-idêntico.

**Revisão adversarial e R1.** Primeira revisão `DeepSeek V4 Pro`: PASS. Primeira revisão fresca
`Claude Opus 5`: encontrou **UT3-01** — `main.py` usava `logging.getLogger(__name__)`, que sob
`python main.py` vira o logger "__main__", enquanto os módulos migrados
vinculam-se a `logging.getLogger("main")`; no entrypoint publicado a evidência
de shadow-audit de RBAC e os tracebacks 500 de `internal_error` não alcançariam o
`RotatingFileHandler`. **Correção R1:** `logging.getLogger(__name__)` →
`logging.getLogger("main")`, uma única linha. Teste de regressão dedicado
adicionado: `tests/test_ut3_r1_direct_entrypoint_logger.py`, que executa `main.py` com semântica
real de `__name__ == "__main__"` via `runpy.run_path`, neutraliza `init_db` e
`Flask.run`, redireciona `APP_LOG_DIR` para `tmp_path` e fixa a identidade de objeto do logger
resultante — não asserções de texto-fonte. `DeepSeek V4 Pro` R1: PASS. Segunda revisão fresca
`Claude Opus 5` R1: **PASS / 0 achados materiais**, com teste de mutação confirmando que
reverter a linha R1 torna 4 dos 5 casos vermelhos.

**Reconciliação de rotas.** Uma sondagem manual anterior reportou 130/129. A reconciliação
reproduziu a discrepância exata: a varredura manual omitia `/favicon.ico`, a última rota
autônoma de `main.py`. A medição canônica é **131/130**, idêntica à do HEAD de entrada.

**Transição de baseline de banco — autorizada pelo humano.** O baseline
`a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9` está **APOSENTADO /
PRÉ-v2-v3**. Uma sondagem de startup de revisor executou legitimamente as migrações v2/v3 já
existentes contra o banco v1: `schema_migrations` ganhou v2 e v3, `user_version` foi de 1 para
3, e nenhuma mutação de dado de negócio foi encontrada — `atividades` 32/32 e `atividade_versao`
63/63 logicamente idênticos. Novo baseline canônico autorizado: 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818`, `integrity_check` ok,
`foreign_key_check` vazio, sem resíduo `-wal`/`-shm`/`-journal` antes e depois da suíte completa.

**Evidência final.** Invariantes: rotas 131; endpoints 130; RBAC unmapped 0; actor matrix 402;
catálogo de mensagens 536; `hooks_main` 1; `route_inventory_baseline.json` byte-idêntico. Suíte
completa de qualificação: `1126 passed / 17 deselected / 0 failed / 0 errors / exit 0`.

**Escopo do commit.** 16 caminhos, commit técnico único: 13 caminhos candidatos revisados e
congelados por hash (`main.py`, `app/presentation.py`, `utils/messages.py`,
`app/web/authz_gate.py`, `app/web/context.py`, `app/web/errors.py`,
`tests/test_ut3_app_hooks.py`, `tests/test_ut3_r1_direct_entrypoint_logger.py`,
`tests/test_phase4_alunos_turmas_cursos_shared_owners.py`,
`tests/test_phase4_configuracoes_blueprint.py`, `tests/test_phase4_matrizes_shared_owners.py`,
`tests/test_ref_0c_c_b1_fail_closed_shadow_gate.py`, `tests/test_ut2_composition_root.py`) mais
3 de governança (`PROJECT_STATE.md`, `docs/refactor/EXECUTION_PROTOCOL.md` §4 e §11,
`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` — este bloco). `AGENT_HANDOFF.md` e
`docs/DOCUMENTATION_INDEX.md` não aparecem. `database.db` não aparece: é untracked/ignorado.
§10 não recebeu entrada — UT3-01, a transição de baseline de banco e os seis achados
não-materiais das revisões são matéria adjudicada dentro do escopo da UT-3, não dívida de
arquitetura diferida nova.

**Próxima UT:** UT-4 — containment de path.

## UT-4 — Containment de path

**Data:** 2026-08-08. **HEAD de entrada:** `fa52a05a4ce07b4c56e1d4827b2c7d69c6c35f5c`.
`_best_effort_remove_admin_arquivo_file` foi endurecida com a contenção `_path_within_root` já
existente. **Mudança de comportamento declarada:** travessia de diretório pai (`..`) é
rejeitada; caminhos absolutos externos à raiz são rejeitados; limpeza legítima aninhada
permanece preservada. Nenhum teste aposentado. `DeepSeek V4 Pro`: PASS / 0 achados materiais.
`Claude Opus 5`: PASS / 0 achados materiais. Suíte completa: 1129 passed / 17 deselected / 0
failed / 0 errors. Invariantes: rotas 131 / endpoints 130 / RBAC unmapped 0 / actor matrix 402 /
catálogo de mensagens 536 / hooks_main 1. `database.db` inalterado em 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818`.

**Próxima UT:** UT-5 — Fase 5: I/O fora do after_request.

## UT-5 — Backup I/O fora do ciclo de request

**Data:** 2026-08-08. **HEAD de entrada:** `9b6cce5019319394264ee76bc3c67b20dc7e83b9`. A
orquestração de backup (sync de snapshot, retenção, upload para drives/servidor externo,
configurações de runtime e resolução segura de manifesto) foi movida para o pacote novo
`app/backup/` (`orchestrator.py`, `sync.py`, `__init__.py`); `main` reexporta os símbolos
canonicamente por identidade, nunca por wrapper. O hook `after_request` transitório
`_legacy_post_response_backup_sync` foi removido de `main.py` inteiramente — nenhuma
requisição HTTP comum (inclusive `GET /health`) mais dispara orquestração de backup, e o hook
não foi realocado para `before_request`/`teardown_request`/`teardown_appcontext`, thread,
timer, `atexit`, signal ou worker. O ciclo automático canonico agora é
`app.backup.orchestrator.run_backup_cycle`, acionado fora do request via CLI
`python -m app.backup.sync`. O comportamento manual da tela "Banco de Dados" permanece
preservado. `app/paths.py` passa a ser o dono canonico de `_path_within_root`
(`main._path_within_root is app.paths._path_within_root`, mesmo objeto). `hooks_main` 1 →
**0**.

**Ratchet de dívida do `init_db`.** Uma correção R1 no arnês de teste removeu um chamador
acidental novo de `main.init_db` introduzido durante a preparação da UT-5; o total de
chamadores de compatibilidade permanece **72**, e `tests/test_ut5_backup_package.py`
contribui zero chamadores novos.

`DeepSeek V4 Pro`: PASS / 0 achados materiais. `Claude Opus 5`: PASS / 0 achados materiais.
Suíte completa: 1142 passed / 17 deselected / 0 failed / 0 errors. Invariantes: rotas 131 /
endpoints 130 / RBAC unmapped 0 / actor matrix 402 / catálogo de mensagens 536 / hooks_main
**0**. `database.db` inalterado em 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818`.

## UT-6 — Fechar ciclo app → main

**Data:** 2026-08-08. **HEAD de entrada:** `1b0a0c3b3f05b7e6e2f52fb1e475ce9d21f192a8`. Resultado
estrutural: dependências reversas arquiteturais 3 → 0; arestas literais de import de `main` 2 → 0;
SCC reversa contendo `main` eliminada. Ownership: `app/web/urls.py` passa a possuir `aluno_url` e
`USE_ALUNO_BLUEPRINT`; `app/requisitions.py` passa a possuir os helpers de alerta de atualização de
solicitação do aluno e as constantes `AUTO_ALERT_YELLOW_*`; `utils/messages.py` resolve a conexão de
banco diretamente pelo dono canônico `app.db`, sem consultar `main` via `sys.modules`. `main`
preserva reexports de compatibilidade por identidade para todos os símbolos movidos. Catálogo de
mensagens: 536; dono do uso movido preservado sob `app/requisitions.py`.

Suíte de contrato nova da UT-6: 68/68. Zero testes aposentados; uma extensão autorizada de allowlist
do scanner de mensagens (inclusão de `app/requisitions.py`). `DeepSeek V4 Pro`: PASS / 0 achados
materiais. `Claude Opus 5`: PASS / 0 achados materiais (revisão genuinamente independente).

Achados diferidos: detector AST da UT-6 não captura formas simples de alias estaticamente
resolúveis (`NON_MATERIAL_FUTURE_HARDENING`); `tests/test_ref_0c_b1_p0_access_context_transactions.py`
faz patch de um alvo obsoleto `main.get_db_connection` (`PRE_EXISTING_TEST_DEBT`). Ambos registrados
em §10 de `EXECUTION_PROTOCOL.md`, sem UT nova criada.

Suíte completa: 1227 collected / 1210 passed / 17 deselected / 0 failed / 0 errors. Invariantes:
rotas 131 / endpoints 130 / RBAC unmapped 0 / actor matrix 402 / catálogo de mensagens 536 /
hooks_main 0. Chamadores de compatibilidade de `main.init_db`: 72 (inalterado; nenhum arquivo
candidato da UT-6 introduziu novo chamador). `database.db` inalterado em 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818`.

**Próxima UT:** UT-7 — helpers matrizes → activity_catalog. NÃO INICIADA.

## UT-7 — Helpers matrizes → activity_catalog

**Data:** 2026-08-08. **HEAD de entrada (pai de publicação):** `d59b80825ea180957de00ced47c5fd55d09660de`.
Ownership antes: `app/views/admin/atividades.py`; ownership depois: `app/activity_catalog.py`.
Helpers movidos: `_build_grupo_label` e `_canonicalize_tipo_limitacao` (cópia canônica única em
`app.activity_catalog`, com ambos em `__all__`). Compatibilidade: `app/views/admin/atividades.py`
permanece como facade de re-export por identidade (zero corpos locais; `__all__` preservado).
Direção do consumo: `matrizes → activity_catalog`. Aresta removida: `matrizes → atividades`
(cross-blueprint). `main.py`: inalterado (byte-idêntico ao HEAD, sem delta).

RED da UT-7: 8 coletados / 3 passed / 5 falhas arquiteturais esperadas / 0 errors. Contrato
pós-implementação: 8/8 passed. Controles focados: 65/65 phase4; 9/9 consumidores de comportamento.
Revisão: `DeepSeek V4 Pro`: PASS / 0 achados materiais.

Suíte completa: 1235 collected / 1218 passed / 17 deselected / 0 failed / 0 errors / 341.93s.
Invariantes finais: rotas 131 / endpoints 130 / RBAC unmapped 0 / actor matrix 402 / catálogo de
mensagens 536 / hooks_main 0. Banco: baseline canônico v3 inalterado — 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818` (sem sidecars).
Incidente transitório resolvido: sidecars WAL/SHM efêmeros produzidos por sonda de qualificação,
removidos com segurança, zero delta de bytes no banco.

**Próxima UT:** UT-8 — Banco de Dados. NÃO INICIADA.

## UT-8 — Banco de Dados

**Data:** 2026-08-09. **HEAD de entrada (pai de publicação):**
`7c5b319a39639468943ef6c5521a36cc44545615`. Before: 20 rotas Banco de Dados e helpers
coorte-local possuídos em `main.py`. After: `app/views/admin/banco_dados.py` passa a possuir
**20 rotas / 24 helpers / 2 constantes / 46 símbolos totais**. `main`: 46/46 reexports de
compatibilidade por identidade; zero ownership local dos símbolos movidos. LegacyRouteSpec:
20 specs / 21 pares endpoint-method. RBAC: 2 view / 16 edit / 3 full. Dependência:
`banco_dados → main` = **0**. Factory: `register_admin_banco_dados_blueprint` default True,
registrado via `register_legacy_blueprint`. Substituições arquiteturais aprovadas:
`app.config` → `current_app.config` em 12 sites movidos; acesso dinâmico canônico ao banco via
`app_db.DATABASE`. Camadas inferiores inalteradas. Não: pacote `app/db`, camada de repository,
migration v4, redesign de schema, redesign do subsistema de backup.

RED de qualificação: 20 coletados / 10 passed / 10 falhas arquiteturais esperadas / 0 errors.
RED pós-implementação: 20/20 passed. Lane focada de implementação: 158/158 passed. Revisão
adversarial primária: `DeepSeek V4 Pro`: PASS / 0 achados materiais. Adjudicação especial do
chamador `init_db`: 72 → 73 causada unicamente pelo caller `isolated_env` do teste RED
congelado; a mudança do chamador de produção foi pura realocação de ownership. Primeira suíte
completa: 1255 collected / 1234 passed / 4 failed / 17 deselected / 0 errors. Causa: quatro
contratos arquiteturais cumulativos obsoletos do Phase-4 — 3 contratos de delta de ownership
CSRF e 1 contrato de file-set exato do pacote admin. Reparo de qualificação: exatamente quatro
arquivos de teste; zero mudanças de byte em produção/snapshot/RED congelado. Repair-focused:
4/4, 96/96, 27/27. Revisão estreita do reparo: `DeepSeek V4 Pro`: PASS / 0 achados materiais.
Retry bem-sucedido da suíte completa: 1255 collected / 1238 passed / 17 deselected / 0 failed /
0 errors / 354.47s. Lane final limitada: 169/169 passed. Invariantes finais: rotas 131 /
endpoints 130 / RBAC unmapped 0 / actor matrix 402 / catálogo de mensagens 536 / hooks_main 0.
Banco: 544768 bytes / SHA canônico inalterado / `user_version` 3 / sem sidecars persistentes.
Falhas de primeira execução resolvidas NÃO são achados abertos.

**Próxima UT:** UT-9 — NÃO INICIADA.
