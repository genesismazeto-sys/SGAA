# SGAA Documentation Index

## Authority hierarchy

1. **Canonical repository state** — `git` commit/tree facts are the single source
   of truth. Chat memory and unsaved documentation carry zero authority.
2. **`docs/refactor/EXECUTION_PROTOCOL.md`** — operational authority for all
   remaining refactor work (UT-1 onward): scope, order, invariants, model
   routing, stop criteria, and the closed test-retirement table. Adopted
   2026-08-07 (v1.1 FINAL); supersedes per-phase contract governance for
   remaining work. Does not revoke closed contracts — B1–B7-P remain valid
   history (item 7 below).
3. **This index** — defines the mandatory reading order, documents the authority
   hierarchy, and records closeout rules.
4. **Project state** (`PROJECT_STATE.md`) — live current-state block. From
   UT-2 onward it is **rewritten (not appended), at most ≤40 lines, once per
   unit of work**: branch, HEAD, last/current/next UT, live invariants, and
   the latest full-suite result. Historical narrative predating UT-2 is not
   preserved here — it lives only in the ledger (item 6 below).
5. **Master plan** (`docs/mapeamento/05_avaliacao_refactor.md`) — the incremental
   refactor plan; frozen Phase 0–6 decomposition with completion matrix and
   formal decisions. Superseded as scope authority for remaining work by
   `EXECUTION_PROTOCOL.md` §2 (item 2 above); retained as historical plan.
6. **Architecture refactor ledger** (`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`)
   — normalized table of every refactor phase, commits, status, and residual risk.
   Historical record; append-only.
7. **Phase contracts** (`docs/refactor/REF_*.md` and named Phase 3/4 contracts) — per-phase scope, decisions,
   and closeout evidence. The canonical Phase 3 authority, intentionally revised
   through the B11 single-init cutover, is
   `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md`. Standalone REF contracts exist for: REF-0TF, REF-0TF-A,
   REF-0TF-B, REF-0C-A, REF-0C-B1-P0, REF-0C-B2-A, REF-0C-B2, REF-0C-C-A,
   REF-0C-C-B1. No standalone contract exists for REF-0A, REF-0ENV, REF-0B,
   REF-0T, REF-0C-A-R1, or REF-0C-D; their scope is documented in the ledger
   and PROJECT_STATE historical blocks. Phase 4 endpoint-preserving extraction is
   governed by `docs/refactor/PHASE4_ADMIN_BLUEPRINT_COMPATIBILITY_CONTRACT.md` for B1,
   `docs/refactor/PHASE4_VERSIONING_SUBSYSTEM_CONTRACT.md` for B2,
   `docs/refactor/PHASE4_ATIVIDADES_BLUEPRINT_CONTRACT.md` for B3,
   `docs/refactor/PHASE4_REQUISICOES_SHARED_OWNER_CONTRACT.md` for B4.1,
   `docs/refactor/PHASE4_REQUISICOES_BLUEPRINT_CONTRACT.md` for B4.2,
   `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md` for B5-P (neutral
    admin-access shared-owner prerequisite; CLOSED / ACCEPTED), and
`docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md` for PHASE 4-B5
      (Matrizes admin blueprint extraction; CLOSED / ACCEPTED; technical commit
      `2a122357a79080fa66aa19c00ed5ff8533308f41`; publication and post-publication
      verification COMPLETE; external supervisor acceptance GRANTED), and
      `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_SHARED_OWNER_CONTRACT.md` for
      PHASE 4-B6-P (Alunos/Turmas/Cursos neutral shared-owner prerequisite;
      CLOSED / ACCEPTED; technical publication, post-publication recovery and
      verification COMPLETE; external supervisor acceptance GRANTED), and
      `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_BLUEPRINT_CONTRACT.md` for
      PHASE 4-B6 (Alunos/Turmas/Cursos admin blueprint; CLOSED / ACCEPTED;
      technical commit `3d9660a99e6944ff94a3991a353ecf3aaf300987`, subject
      `Extract admin alunos turmas cursos blueprint`; exact 17 endpoints /
      24 route-method pairs / 10 helpers; exact R1 three-dead-context
      exception; technical publication COMPLETE; post-publication verification
      COMPLETE; external supervisor acceptance GRANTED; governance closeout
      published by R3), and
      `docs/refactor/PHASE4_ARQUIVOS_ALERTAS_SHARED_OWNER_CONTRACT.md` for
      PHASE 4-B7-P (Arquivos/Alertas neutral shared-owner prerequisite;
      CLOSED / ACCEPTED; accepted technical commit
      `1c82a1954250aa5e6654349ce77a50d60f03fe8f`; exact 4 shared symbols,
      neutral owners 2/1/1 across `app.db_maintenance`, `app.admin_files`
      (new) and `app.admin_alerts` (new); zero route movement; PHASE 4-B7
      route extraction NOT AUTHORIZED).
8. **Historical snapshot custody** (`docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`)
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
9. **Agent handoff** (`AGENT_HANDOFF.md`) — **HISTORICAL / FROZEN** as of the
   `EXECUTION_PROTOCOL.md` v1.1 governance adoption (2026-08-07). No new
   writes; the live operational state is `PROJECT_STATE.md` (item 4). The
   preserved top block remains a historical operational record but is
   **not** a substitute for the repository canon and is not read by the
   active governance cycle.
10. **Supporting evidence** — tests and artifacts under `tests/` (especially
    `tests/_artifacts/`) and tools under `tools/`.
11. **Legacy / historical** — older blocks, superseded contracts, and historical
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
7. `docs/refactor/PHASE4_VERSIONING_SUBSYSTEM_CONTRACT.md` — current B2
   ownership, three-route, aluno reverse-edge and logging-compatibility contract.
8. `docs/refactor/PHASE4_ATIVIDADES_BLUEPRINT_CONTRACT.md` — accepted B3 exact
   22-endpoint/29-combination, shared-catalog, upload and scope-reconciliation contract.
 9. `docs/refactor/PHASE4_REQUISICOES_SHARED_OWNER_CONTRACT.md` — accepted B4.1 neutral-owner contract.
 10. `docs/refactor/PHASE4_REQUISICOES_BLUEPRINT_CONTRACT.md` — accepted B4.2 exact
     nine-endpoint/12-pair blueprint and publication contract.
 11. `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md` — accepted B5-P neutral
      admin-access shared-owner prerequisite contract; CLOSED / ACCEPTED.
 12. `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md` — current PHASE 4-B5
      Matrizes admin blueprint extraction contract; CLOSED / ACCEPTED; technical
      commit `2a122357a79080fa66aa19c00ed5ff8533308f41`; publication and
      post-publication verification COMPLETE; external supervisor acceptance
      GRANTED.
 13. `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_SHARED_OWNER_CONTRACT.md` — PHASE 4-B6-P
      Alunos/Turmas/Cursos neutral shared-owner prerequisite contract; CLOSED /
      ACCEPTED; technical publication, post-publication recovery and verification
      COMPLETE; external supervisor acceptance GRANTED.
 14. `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_BLUEPRINT_CONTRACT.md` — PHASE 4-B6
      Alunos/Turmas/Cursos admin blueprint contract; CLOSED / ACCEPTED;
      technical commit `3d9660a99e6944ff94a3991a353ecf3aaf300987`; exact 17
      endpoints / 24 route-method pairs / 10 helpers; full hermetic GREEN;
      external supervisor acceptance GRANTED; governance closeout published by R3.
 15. `docs/refactor/PHASE4_ARQUIVOS_ALERTAS_SHARED_OWNER_CONTRACT.md` — PHASE 4-B7-P
      Arquivos/Alertas neutral shared-owner prerequisite contract; CLOSED /
      ACCEPTED; accepted technical commit
      `1c82a1954250aa5e6654349ce77a50d60f03fe8f`; exact 4 shared symbols moved
      to neutral owners 2/1/1 (`app.db_maintenance`, `app.admin_files` new,
      `app.admin_alerts` new); aluno lazy map reduced 5 → 2; zero route
      movement; PHASE 4-B7 blueprint route extraction remains NOT AUTHORIZED.
 16. `PROJECT_STATE.md` — canonical current state (top block).
 17. `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` — historical snapshot custody governance track.
 18. `AGENT_HANDOFF.md` — current operational handoff.
 19. All `docs/refactor/REF_*.md` / `docs/refactor/PHASE_0_*.md` files in dependency order: REF-0TF →
   REF-0TF-A → REF-0TF-B → REF-0C-A → REF-0C-B1-P0 → REF-0C-B1 →
   REF-0C-B2-A → REF-0C-B2 → REF-0C-C-A → REF-0C-C-B1 → REF-0C-D-R1 →
   PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.
## Canonical current state (2026-08-04)

- **PHASE 4-B7-P current candidate:** CLOSED / ACCEPTED. Accepted technical commit `1c82a1954250aa5e6654349ce77a50d60f03fe8f`, subject `Extract B7 shared neutral owners`, parent `b6d6e2295e2beeba046cfe1f4c1614f667261ad2`. Technical publication COMPLETE; post-publication bounded verification COMPLETE; external supervisor technical acceptance GRANTED. Exact 4 shared symbols moved to neutral owners 2/1/1: `app.db_maintenance` owns `ensure_admin_arquivos_table` + `ensure_admin_alertas_table` (joining the pre-existing `ensure_reportes_table`); new `app.admin_files` owns `get_admin_arquivo`; new `app.admin_alerts` owns `list_active_admin_alertas`. `main` re-exports all four by identity, zero local bodies; all four bodies AST-equivalent to entry baseline `b6d6e2295e2beeba046cfe1f4c1614f667261ad2:main.py`. `aluno._get_main_helpers()` reduced from 5 keys to exactly `{get_student_request_update_alert, mark_student_request_updates_seen}`. Zero route movement: all 12 Arquivos/Alertas/Reportes handlers (13 route-method pairs) remain main-local. `uploaded_file` and `admin_dashboard` AST-unchanged; Reportes ownership unchanged. RED (new `tests/test_phase4_arquivos_alertas_shared_owners.py`, 11 collected): 7 failed / 4 passed, exit 1, all failures attributable to the absent prerequisite. GREEN: 11 passed, exit 0. PHASE 4-B7-P-R2 supplemental-scope correction (supervisor-authorized): two additional frozen 5-key aluno-lazy-map assertions outside the named pool — `tests/test_db_schema_maintenance.py::EXPECTED_ALUNO_LAZY_KEYS_AFTER_VERSIONING_EXTRACTION` and `tests/test_phase4_versioning_subsystem.py::REMAINING_ALUNO_MAIN_HELPERS` — received the identical one-for-one 5→2 correction; classification `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED / ALUNO_LAZY_MAP_INVARIANT_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY`. PHASE 4-B7-P-R2 environmental waiver (supervisor-authorized): full default suite `1103 passed / 3 failed / 17 deselected`, exit 1, NOT claimed GREEN; the exact three failures (`test_phase3_final_init_cutover.py::test_seed_tool_uses_factory_owner_without_main_and_is_idempotent`, `test_pytest_runtime_isolation.py::TestSubprocessImportMain::test_import_main_uses_runtime_root`, `test_pytest_runtime_isolation.py::TestMainNoOverwrite::test_import_main_preserves_upload_folder`) were independently reproduced with identical fingerprints on a disposable worktree of unmodified entry baseline `b6d6e2295e2beeba046cfe1f4c1614f667261ad2`; classification `PRE_EXISTING_BASELINE_REPRODUCED / ENVIRONMENTAL_ENCODING_FAILURE / UNRELATED_TO_B7_P / ACCEPTED_NONBLOCKING_RESIDUAL / NO_RETROACTIVE_GREEN_CLAIM`; neither file modified or added to the mutable pool. B7-P-specific/affected focused gates: 0 failed / 0 errors / exit 0 throughout. Invariants unchanged: routes 131; endpoints 130; business pairs 160; RBAC unmapped 0; message catalog 536; `database.db` 544768 bytes / SHA-256 `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9` unchanged, WAL/SHM/journal absent. Exact manifest: production 5 (`app/db_maintenance.py`, `app/admin_files.py` new, `app/admin_alerts.py` new, `app/views/aluno.py`, `main.py`) + tests 4 (`tests/test_phase4_arquivos_alertas_shared_owners.py` new, `tests/test_phase4_requisicoes_shared_owners.py`, `tests/test_db_schema_maintenance.py`, `tests/test_phase4_versioning_subsystem.py`) + governance 6 = 15 paths; path 16 hard stop absent further authorization. Contract: `docs/refactor/PHASE4_ARQUIVOS_ALERTAS_SHARED_OWNER_CONTRACT.md`. PHASE 4-B7 (blueprint route extraction) remains **NOT AUTHORIZED**. PHASE 4 remains OPEN / INCREMENTAL IMPLEMENTATION; Phase 5/6 NOT AUTHORIZED; Migration v4 PROHIBITED.
- **PHASE 4-B6 current candidate (superseded as "current" by the B7-P block above; B6 remains CLOSED / ACCEPTED):** PHASE 4-B6-P remains CLOSED / ACCEPTED. PHASE 4-B6-R1 and PHASE 4-B6 are **CLOSED / ACCEPTED**. Accepted technical commit `3d9660a99e6944ff94a3991a353ecf3aaf300987`, subject `Extract admin alunos turmas cursos blueprint`. Technical publication: COMPLETE. Post-publication verification: COMPLETE. External supervisor acceptance: GRANTED. Governance closeout published by this R3 commit. Canonical owner `app.views.admin.alunos_turmas_cursos` has exactly 17 endpoints / 24 route-method pairs / 10 helpers; `main` has zero local B6 bodies and 27 identity re-exports; RBAC 6/13/5; accepted B6-P neutral owners preserved; factory default/exact opt-out; zero `app -> main`. R1 resolves the original `periodo_corrente` ownership contradiction with only three dead template-context removals (`admin_detalhes_curso`, `admin_turmas`, `admin_detalhes_turma`); `periodo_corrente` remains main-local and unchanged for `_build_admin_dashboard_turma_cards`. History is preserved: RED 25 = 6/19/0; GREEN 28; focused 254; initial full 1093 passed / 2 stale cumulative-CSRF failures / 17 deselected; pre-freeze full collected 1112 = 1095 passed / 17 deselected / 0 failed / 0 errors / 433.87s / exit 0 / canonical opens 0. The selective-staging whitespace gate and B1 ledger compatibility gate caused a bounded correction (SQL-string spaces represented as source `\x20`, only syntactic trailing spaces removed, canonical `| Fase 4 |` restored); the first recovery full was 1093 passed / 2 failed / 17 deselected, the two focused recovery nodes passed, and the repeated final full was 1095 passed / 17 deselected / 0 failed / 0 errors / 318.06s / exit 0 / canonical opens 0. CSRF exact partitions: B6 11, Matrizes 8+11=19, Requisições 5+8+11=24, owner-only and exhaustive. Routes 131; endpoints 130; business pairs 160; governed pairs 134; unmapped 0; actor 402 = 263+139; catalog 536; route inventory byte-identical. Exact candidate ceiling: 10 technical/test + 6 governance = 16. Contract: `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_BLUEPRINT_CONTRACT.md`. Parent/live feature was `cab4c61bdf7a1eef361a80f426dda558b11e9201`; protected `main` remains `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`; technical commit, publication, post-publication verification and external supervisor acceptance are COMPLETE. B6 is CLOSED / ACCEPTED. PHASE 4 remains OPEN / INCREMENTAL IMPLEMENTATION; Phase 5/6 NOT AUTHORIZED; Migration v4 PROHIBITED; no later cohort authorized.
- **Historical predecessor:** the B6-P-only statements below that PHASE 4-B6 was not authorized are preserved phase-time history and are superseded only by the separate B6/R1/R2 orders above.
- Branch: `refactor/architecture-safety-net`; accepted technical commit `0b003c5f00e5e6181c9b9a5f96d8572b8488323f`; accepted recovery commit `5af7fc70547fccbfed42ebaf5ca353365371c892`; technical publication, post-publication recovery and verification COMPLETE; external supervisor acceptance GRANTED; R6 closeout identity resolves through Git history; protected `main` `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`.
- **PHASE 4-B6-A:** DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED (historical read-only prerequisite diagnosis; supervisor correction excluded `periodo_corrente`, which remains local in `main`). **PHASE 4-B6-P:** CLOSED / ACCEPTED. Accepted technical commit `0b003c5f00e5e6181c9b9a5f96d8572b8488323f` (`Extract B6 shared neutral owners`), parent `1bf5173949b0bf0bdce15d1b87d6ed15d535158c`; accepted recovery commit `5af7fc70547fccbfed42ebaf5ca353365371c892` (`Repair B6-P post-publication governance state`). Technical publication COMPLETE; post-publication recovery COMPLETE; post-publication verification COMPLETE; external supervisor acceptance GRANTED. Permanent process record: `PREPUBLICATION_BOUNDED_GATE_INVOCATION_ERROR / DISCOVERED_POST_PUBLICATION / NO_RETROACTIVE_GREEN_CLAIM`; `python -m sgaa_canonical_db_guard -m pytest ...` did not execute pytest, and the valid recovery gates used `python -m pytest -p sgaa_canonical_db_guard ...`. Neutral Alunos/Turmas/Cursos shared-owner prerequisite: Exactly 9 shared symbols moved to neutral owners 3/5/1: `app.academics` (3: `build_turma_aluno_matricula`, `resequence_turma_aluno_matriculas`, `resequence_turma_aluno_matriculas_for_ids`), `app.user_accounts` (5: `_access_defaults_map`, `_default_password_for_user_type`, `create_usuario_with_default_access`, `create_usuario_with_default_password`, `normalize_usuario_access_for_user_type`), `app.web.request` (1: `_is_ajax_request`). `main` re-exports all nine by identity with zero local bodies/wrappers/duplicates; all moved bodies AST-equivalent to parent. `app.views.core` imports `normalize_usuario_access_for_user_type` directly from `app.user_accounts`; residual lazy map exactly `aluno_url` / `get_db_connection` / `logger`; login `normalize -> conn.commit() -> refreshed SELECT` preserved; `periodo_corrente` stays local AST-identical. Isolated owner imports do not import `main`; no new owner→`main` edge/cycle. Zero B6 route movement; no blueprint/factory/endpoint/RBAC/CSRF ownership migration; **PHASE 4-B6 route extraction remains NOT AUTHORIZED**. B6-P-R1 literal: `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED / MESSAGE_SCANNER_OWNER_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY` (R1 added `utils/messages.py` to production scope and exactly `PROJECT_ROOT / "app" / "academics.py"` to `_iter_backend_files()`; RED catalog 535 / key `msg_4642b1608cf6a126` absent → GREEN catalog 536 / key present, default `"Turma sem código para gerar matrícula."`, source `app/academics.py`, no duplicate; scanner provenance literal: the moved `ValueError` message usage/source owner changed from `main.py` to `app/academics.py` while key and exact default text remained unchanged — the message itself did not change). B6-P-R3 literal: `PRE_REVIEW_SCOPE_EXPANSION / ONE_FOR_ONE_TEST_POOL_SUBSTITUTION_PLUS_FOUR_ADDITIONS / STALE_GOVERNANCE_TEST_RECONCILIATION / MESSAGE_SCANNER_ALLOWLIST_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY` (`test_residual_shared_helpers.py` unchanged read-only gate; final mutable test pool = six test paths in the dirty manifest; first full 1061/5/17; five-node recovery 5/5; coupled lane 77/77; fresh final full collected 1083 = 1066 passed + 17 deselected / 0 failed / 0 errors / 328.77s / exit 0 / `CANONICAL_SQLITE_OPENS=0`). Earlier focused 206 passed/117.65s/exit 0 (first harness attempt exit 1 was a recoverable MSYS `/c`→`D:/c` basetemp defect; native `C:/` rerun passed). Historical TDD/scanner-owner chronology preserved (not rewritten): structural RED 13 failed / 31 passed; structural GREEN 44 passed; focused 203 passed / 2 failed (scanner-owner findings, catalog RED 535 / key absent → R1 GREEN 536). R1 CSRF nodes 2/2, B6-P CSRF delta `[0,0]`. Fresh invariants: routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC unmapped 0; actor 402 = 263 + 139; message catalog 536; route inventory byte-identical 20814 bytes / `6e32148c…49fa`; CSRF shadows each 288509 bytes / `4b16f1b4…769`; canonical database 544768 / `a3a55e63…70fe9`, WAL/SHM/journal absent, opens 0; protected residual 17420 / `7388cfbc…bb0e`. Scope ceiling production 6 / tests 6 / governance 6 / total 18; path 19 hard stop; exact 12-path non-governance dirty manifest + six governance documents = 18. Contract: `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_SHARED_OWNER_CONTRACT.md`. PHASE 4 remains OPEN / INCREMENTAL IMPLEMENTATION; PHASE 4-B6, Phase 5 and Phase 6 are NOT AUTHORIZED; Migration v4 is PROHIBITED.
- **PHASE 4-B5 (historical / superseded for the B6-P prerequisite stage):** CLOSED / ACCEPTED. Matrizes admin blueprint extraction is technically
  published at `2a122357a79080fa66aa19c00ed5ff8533308f41` (subject
  `Extract admin matrices blueprint`), parent
  `ef874b9d14b02656a0f26ea885024a280d49682e` (`Record acceptance of Phase 4-B5-P`);
  protected `main` `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`. Publication: COMPLETE.
  Post-publication verification: COMPLETE. Published manifest: exactly 17 paths.
  External supervisor acceptance: GRANTED. Accepted technical review (READ-ONLY,
  mutation 0; sessions `ses_03adb7f27ffeJ1feNSLhrFij5R`
  FREE failure exit 1 / `ses_03ad0a15dffeR53I9BqGU6a4tl` accepted fallback
  `FALLBACK_FREE_EXECUTION_FAILURE`, exit 0, cost `0.001000188`; verdict PASS / SCOPE
  EXACT / BEHAVIOR PRESERVED; blocking 0; nonblocking 4; gates 51 + 3). `app.views.admin.matrizes` is the canonical owner of exactly
  10 global legacy endpoints / 12 route-method pairs and 21 route-private corrected
  helpers; `main` re-exports all by identity with zero local bodies/decorators;
  `bp_admin_matrizes` + immutable `LEGACY_ROUTE_SPECS` via the accepted
  `LegacyRouteSpec`/`configure_legacy_routes` registrar; keyword-only factory flag
  `register_admin_matrizes_blueprint=True`; RBAC exactly 3 view / 7 edit / 2 full;
  `app.auth` and `app.admin_access` unchanged; zero `app -> main` edge; ensures/SQL/
  transaction/UI/messages/CSRF frozen. Void names `_get_grupos_atividade` and
  `_get_matriz_active_norma_ids` absent (classification `SUPERVISOR CONTRACT
  CORRECTION / NOT A PATH-POOL EXPANSION / NOT A DOMAIN-SCOPE EXPANSION`). Evidence:
  corrected TDD RED `20 failed / 4 passed / 0 collection errors`; primary B5 GREEN
  `24 passed / 3.74s`; focused expanded (44 files) `578 passed / 249.33s`; first full
  `1049 passed / 1 failed / 17 deselected / 370.60s` (sole failure: configuracoes
  package membership; HARD STOP); B5-R3 one-for-one mutable-pool substitution (node
  1 passed / 0.64s; affected focused 143 passed / 24.30s); final full hermetic fresh
  `1050 passed / 17 deselected / 0 failed / 0 errors / 317.65s` (collected 1067);
  canonical SQLite opens 0. Routes 131; endpoints 130; business pairs 160; governed
  pairs 134; RBAC unmapped 0; actor 402 = 263 + 139; message catalog 536; route
  inventory byte-identical (20814 bytes, SHA-256 `6e32148c…49fa`); CSRF exactly
  `[8, 8]` owner-only deltas (78 rows each, summaries equal, no non-owner delta);
  canonical database 544768 bytes / `a3a55e63…70fe9`, WAL/SHM/journal absent, opens 0;
  protected residual 17420 bytes / `7388cfbc…bb0e`; `app/admin_access.py` byte-identical
  (4546 bytes, SHA-256 `b2dc2592…d9814`). Routing: IAsup Hermes
  `openai-codex/gpt-5.6-sol`; RED IAexec `opencode` / `opencode/deepseek-v4-flash-free`,
  session `ses_03b57ca6bffenOnPYH3mt5WdX0`, cost 0; implementation IAexec
  `flash_free` → selected `flash_normal` by `FALLBACK_FREE_CONTEXT_TOO_LARGE`, actual
  `opencode-go` / `opencode-go/deepseek-v4-flash`, same session, cost `0.0010985912`,
  no silent escalation; IAsup direct corrections (two RED typos; B5-R3 membership).
  Contract: `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md`. PHASE 4 remains
  OPEN / INCREMENTAL IMPLEMENTATION. PHASE 4-B5 is CLOSED / ACCEPTED; Phase 5 and
  Phase 6 are NOT AUTHORIZED; Migration v4 is PROHIBITED. The Section-22
  pre-implementation reconciliation gate was NOT executed before the first B5
  production mutation (process deviation recorded truthfully, not retroactively
  satisfied). The authorized governance closeout subject is `Record acceptance of
  Phase 4-B5`; its identity resolves through Git history.
- **PHASE 4-B5-P:** CLOSED / ACCEPTED. Neutral admin-access shared-owner prerequisite
  at technical commit `92486f87ea15697282a265cb7a9941678cb9138f` (`Extract admin access
  context shared owner`), parent baseline HEAD `a0b56896252a276e562da3842d3d61b078bd9f27`
  (`Record acceptance of Phase 4-B4.2`); protected `main`
  `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`. Publication: COMPLETE. Post-publication
  verification: COMPLETE. `app.admin_access` canonically owns exactly
  `_fetch_user_access_overrides`, `_build_access_scope_groups_for_level`,
  `_load_admin_access_context`, `_get_current_admin_access_context` and `_admin_can`;
  `main` has zero local bodies and re-exports all five by identity. Six exact main
  consumers: `enforce_admin_access_control`, `inject_admin_access_helpers`,
  `admin_editar_matriz`, `admin_matriz_nova_atividade`, `admin_acesso`, `uploaded_file`.
  Zero `app.admin_access -> main` and zero `app.auth -> app.admin_access` edges; no
  cycle. Actual 11-path artifact (2 production + 3 tests + 6 governance) within the
  updated authorized ceiling 12 (2 production + pool of 4 tests + 6 governance); the
  authorized but unchanged `tests/test_ref_0c_b1_p0_access_context_transactions.py`
  remains a gate, not a changed path. B5-P-R2 SUPPLEMENTAL SCOPE AUTHORIZATION added and
  modified only `tests/test_phase4_requisicoes_shared_owners.py`: it reads accepted B4.1
  governance from fixed commit `c587098152e97d125f41a2d26f2f414c10ae5676`, preserves
  B4.1 closure/publication/assertions, and separately proves current B4.2 CLOSED /
  ACCEPTED, Phase 4 OPEN, Phase 5 and Phase 6 NOT AUTHORIZED, Migration v4 PROHIBITED.
  Classification `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED_B5_P_R2 /
  FIXED_ACCEPTED_B4_1_BASELINE / NO_RETROACTIVE_GENERIC_AUTHORITY`; R2 node 1 passed in
  1.02s; affected governance aggregate 118 passed in 16.70s. Final pre-publication
  hermetic after R2: 1025 passed / 17 deselected / 0 failed / 0 errors / 326.74s / exit
  0; the earlier 1025/17/306.41s run is only pre-R2 historical evidence. Independent
  review rerun 1025/17/0/0/367.27s; post-publication focused 132 passed / 39.23s.
  Accepted independent review: provider `opencode`, model `opencode/deepseek-v4-flash-free`,
  session `ses_03c92c10affegAmZLZ63tmTjjA`, exit 0, cost 0, fallback none, mutation 0,
  blocking 0, nonblocking 3; external acceptance GRANTED by the PHASE 4-B5-P-R3 order.
  Accepted content identities: raw candidate `bf67fcaa…`, technical raw `932793aa…`,
  Git-normalized `068bf70d…`. Routes 131; endpoints 130; business pairs 160; governed
  pairs 134; RBAC unmapped 0; actor 402 = 263 + 139; message catalog 536; route
  inventory byte-identical (20814 bytes, SHA-256 `6e32148c…49fa`); CSRF shadow-off/on
  byte-identical to HEAD and each other (each 288349 bytes, SHA-256 `3a94e2e1…a0056`);
  canonical database 544768 bytes / `a3a55e63…70fe9`, WAL/SHM/journal absent, opens 0;
  protected residual 17420 bytes / `7388cfbc…bb0e`. The former pre-publication pending
  state (IMPLEMENTED / AWAITING SUPERVISOR REVIEW; independent review, staging, commit
  and publication PENDING) is historical and superseded. This B5-P bullet is now
  **historical / superseded** by the PHASE 4-B5 CLOSED / ACCEPTED
  bullet above; its phase-time statements that `app/views/admin/matrizes.py`
  remains absent and that PHASE 4-B5 blueprint extraction is NOT AUTHORIZED are
  B5-P closeout-time history only; the blueprint is now technically published at
  `2a122357a79080fa66aa19c00ed5ff8533308f41` and CLOSED / ACCEPTED. Contract: `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md`.
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
  it does not query or filter through the Git index.
- **PHASE 4-B2:** CLOSED / ACCEPTED. Published technical commit
  `17e468ad938e873e1f9e9c303808ad31b9f3806b` (`Extract versioning subsystem ownership`),
  parent `2fbe4954106dc8d410f6495ca8bd4b1956b326d2`; exact 24-path artifact:
  8 production, 10 tests and 6 governance. Post-publication verification: COMPLETE.
  Resolver, snapshot and shadow-read ownership moved to `app.versioning`; exactly three
  legacy diagnostic endpoints moved to `app.views.admin.versioning`; aluno retains six
  lazy-main dependencies. R1 preserves repository-root logging paths and logger `main`.
  Recovered first full 949 passed / 2 failed / 17 deselected; final contract 14, affected
  lane 241, full hermetic 954 passed / 17 deselected / 343.75s / exit 0, index-visible
  271 passed and post-publication 282 passed. Routes 131,
  endpoints 130, governed pairs 134, RBAC unmapped 0 and actor matrix 402. Canonical
  database, protected residual and route snapshot remain unchanged. The FREE review attempt
  (`opencode/deepseek-v4-flash-free`, session `ses_0433de371ffefBa8J03FBmkoV4`, cost 0,
  exit 0) was an UNUSABLE DELIVERY / NO VERDICT; fallback classification
  `FALLBACK_FREE_UNUSABLE_DELIVERY`. The accepted review used
  `opencode-go/deepseek-v4-flash`, session `ses_043375c9affeYmMxqtbpNjNohl`, cost
  `0.01838004 USD`, exit 0, mutation count 0, PASS, material findings 0, on diff SHA-256
  `a97275ac9f29cefcfd8ed4d3038ce37f552a886036481be0f7fd1c7f85a373b7`. The LOW matrix
  status-label finding was REJECTED AS NON-MATERIAL / SEMANTIC EQUIVALENCE PROVED.
  External `baseline_main.py` scratch (SHA-256
  `2652d1213d7f0b5ac577ebddb528341448e9eb0afb8b41d051e5826a56d4af48`) was outside the
  repository, never staged/committed, selectively removed and had no candidate/index impact.
  Final documentary review addendum: route `flash_free`, provider/model
  `opencode/deepseek-v4-flash-free`, session `ses_0431aa4d7ffev4hTZImBDA86Ca`, cost 0,
  PASS, no fallback. Final published diff SHA-256
  `2a98b4a4ff9747745335259d0e5aad2c18eb9a8c0bc4762c1ea2681bc7571eec`.
  Phase 4 remains OPEN / INCREMENTAL IMPLEMENTATION and is not closed. The B2 closeout's
  phase-time B3 prohibition is superseded only by the separate B3 authorization below.
  Phase 5: NOT AUTHORIZED. Phase 6: NOT AUTHORIZED. Migration v4: PROHIBITED.
- **PHASE 4-B3:** CURRENT / CLOSED / ACCEPTED. Published technical commit
  `50801b6bdddc4d2772853c13f4905c49e8c996cf` (`Extract admin activities blueprint`), parent
  `81cc6b10b893f1d34bd211a527e9fd12c3b6bbbe`; exact 16-path artifact = 6 production + 4
  tests/snapshots + 6 governance. Publication and post-publication verification are COMPLETE.
  Exactly 22 legacy endpoints / 29 route-method combinations belong to
  `app.views.admin.atividades`; `app.activity_catalog` and `app.uploads` are neutral owners;
  Matrizes/Requisições routes remain unmoved. Message inventory 536→536 has zero semantic
  delta; both CSRF snapshots have exactly 15 owner-only deltas. Final hermetic 974/17;
  index-visible 300; post-publication 300; routes 131; endpoints 130; governed pairs 134; RBAC
  unmapped 0; actor matrix 402 = 263 allowed + 139 denied. Technical review PASS / findings
  NONE; documentary addendum PASS / findings NONE. Accepted hashes: reviewed technical
  `ec96796d3541710a36ac8121e40ffd888737c7c926f191a28034482cedbfd556`, final publication
  `c41ffe5b7328b6d5a986dbdc28f054fe89641496589003b4e5649ff88463cc19`, governance
  `af2906ef0fa9fef7fdd469dd4e967cd1c914b4bfb21fc2a132b8d74c2d8dfd27`, non-governance
  `13b0af13e653641d75d2466d7d8d69090e655a18e28bb678a7090dbe0e2ecab0`. Provisional FREE
  session `ses_0425bf1cbffeIxMwsDQn0etSEC` was UNUSABLE / NO VERDICT; final FREE session
  `ses_0422f0e1cffepCXyNpg47dWpoq` timed out; accepted fallback session
  `ses_04224ca47ffe5qAwwHGtxlR7i7` was PASS. Documentary addendum first rejected stale
  historical index wording, received a governance-only correction, then passed under
  `opencode-go/deepseek-v4-flash`, session `ses_04203dca3ffe8OM83rhbHyjqYI`. The former
  review/staging/commit/push/publication-pending state is historical and superseded. B4, Phase
  5/6 and migration v4 remain unauthorized/prohibited.
- **PHASE 4-B4.1:** CLOSED / ACCEPTED. Published technical commit
  `73ebf0dc34681e74e778759af476e1cd2f981444` (`Extract requisition shared owners`), parent
  `185426daccc9f0eb0dba4497248100c1a88d15fa`; exact 20-path artifact = 7 production + 7
  tests + 6 governance. Publication and post-publication verification are COMPLETE.
  Accepted owners are `app.settings` for eight settings helpers, `app.requisitions` for
  `auto_indefer_devolvidas`, and `app.matrix_scope` for exactly six matrix-scope symbols.
  Configurações/`main` identity exports are preserved; Aluno directly imports the matrix
  resolver and retains exactly five lazy-main edges. NO ROUTE MOVEMENT; nine Requisições
  handlers / 12 route-method pairs remain in `main.py`; `app/views/admin/requisicoes.py` is
  absent. Final hermetic 984/17; index-visible 170; post-publication 170; routes 131;
  endpoints 130; governed pairs 134; RBAC unmapped 0; actor 402 = 263 + 139; message catalog
  536. Technical review PASS / findings NONE; documentary addendum PASS / findings NONE.
  Accepted hashes: reviewed `f4b6cb00b4365cc7c20af5fcba1ac736ece1bab0ab9c6e0f89b19084799727f9`,
  pre-addendum `ddc73cb94786899595f3cce9d577bdbcca961a082c83866498a36ebd4687a23f`,
  non-governance `74649089be0699dff4440260bdb11793b4e5793550f17456893f4a281bd6096b`,
  final publication `bdd947a18df900aac691ce12683f393a82d8c8efc3e28a8c54c55226d7bf2d4a`,
  governance `301a6a891936338bd1a752ff0be65dd7855302d1e3a8e81f9bcbd94964b66a71`.
  External supervisor acceptance is recorded by B4.1-R2. Its statement that B4.2 was not
  authorized is the B4.1-R2 phase-time boundary, superseded by the accepted B4.2 order and
  publication below. Phase 4 remains open.
- **PHASE 4-B4.2:** CLOSED / ACCEPTED. Published technical commit
  `3231dbd2ff9759d8f855f2a4118102783aedea83` (`Extract admin requisitions blueprint`), parent
  `c587098152e97d125f41a2d26f2f414c10ae5676`; exact 16-path artifact = 3 production + 7
  tests/snapshots + 6 governance. Publication: COMPLETE. Post-publication verification:
  COMPLETE. `app.views.admin.requisicoes` owns exactly 9 legacy endpoints / 12 route-method
  pairs; RBAC is 4 view / 5 edit / 3 full; B4.1 neutral owners and zero `app -> main` are
  preserved. Final hermetic 1005 passed / 17 deselected / 362.33s; index-visible 57 passed;
  post-publication 56 passed / 1 deselected. Routes 131; endpoints 130; governed pairs 134;
  RBAC unmapped 0; actor 402 = 263 + 139; message catalog 536; CSRF `[5, 5]` owner-only
  deltas; canonical SQLite opens 0. Technical Flash FREE review PASS / blocking NONE / scope
  EXACT / behavior PRESERVED. The accepted documentary addendum requested `flash_free`,
  selected `flash_normal` with `FALLBACK_FREE_BUDGET_EXHAUSTED`, and passed under
  `opencode-go/deepseek-v4-flash`, session `ses_03fce2ebbffejkf6IUdfPrsxF3`, router cost
  `0.0011911032 USD`, observed aggregate `0.0180531456 USD`, mutation 0 and outside-scope
  reads 0. Accepted raw/Git-canonical complete identities:
  `1b8435a9db10f8a2ae680f60c17a9ad0a723eed88066a834ca59255bf7b8cc0e` /
  `c362566627667ba684765ad3ea8fdeb9abf7678dd52e185cedd3ed8b08a891b4`; governance
  raw/canonical `19519783e02bf983f820d357e6c2b250db541581fae57f6988e64cf1900f544d` /
  `b44ae4231aaaeb022c2cfc2ca94f20be76a94dd7e82c51e97966866d294d0ceb`; production/test raw
  `f60ebdab5cd1e7aa2d98d9ade66534925c5a077326dff2e70b24c72e6390c037`. Governance closeout
  subject `Record acceptance of Phase 4-B4.2`; identity resolves through Git history. Phase 4
  remains OPEN / INCREMENTAL IMPLEMENTATION. Matrizes is NOT STARTED / NOT AUTHORIZED BY THIS
  CLOSEOUT. Phase 5/6 are NOT AUTHORIZED. Migration v4 is PROHIBITED.
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
  ACCEPTED / B2 CLOSED / ACCEPTED / B3 CLOSED / ACCEPTED / PHASE 4-B4-A CLOSED /
  ACCEPTED / PHASE 4-B4.1 CLOSED / ACCEPTED / PHASE 4-B4.2 CLOSED / ACCEPTED /
  PHASE 4-B5-A DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED /
  PHASE 4-B5-P CLOSED / ACCEPTED / PHASE 4-B5 CLOSED / ACCEPTED
  (technical commit `2a122357a79080fa66aa19c00ed5ff8533308f41`; publication and
  post-publication verification COMPLETE; external supervisor acceptance GRANTED) /
  PHASE 4-B6-A DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED (read-only
  diagnosis; supervisor correction excluded `periodo_corrente`, which remains local in
  `main`) /
  PHASE 4-B6-P CLOSED / ACCEPTED (neutral Alunos/Turmas/Cursos shared-owner
  prerequisite; technical commit `0b003c5f00e5e6181c9b9a5f96d8572b8488323f`;
  recovery commit `5af7fc70547fccbfed42ebaf5ca353365371c892`; technical publication,
  post-publication recovery and verification COMPLETE; external supervisor acceptance
  GRANTED; PHASE 4-B6 NOT AUTHORIZED) /
  B6 route extraction NOT AUTHORIZED;
  Phase 4 is not closed. B1 commit
  `cd8a76b2484abc376174332578ecd8be4b8206ea` establishes the accepted compatibility
  registrar and exact eight-route Configurações/Mensagens cohort. B2 establishes the
  locally qualified versioning owners, exactly three diagnostics and six-key aluno lazy
  boundary. B2 technical commit `17e468ad938e873e1f9e9c303808ad31b9f3806b`, technical
  review PASS, documentary addendum PASS, publication and post-publication verification are
  recorded. B3 technical commit `50801b6bdddc4d2772853c13f4905c49e8c996cf`, exact 16-path
  artifact, technical review PASS, documentary addendum PASS, publication and post-publication
  verification are recorded above. PHASE 4-B4.1 reconciles the bounded expansion to
  `app/settings.py` (neutral owner of all eight B1 helpers), `app/matrix_scope.py` (dedicated
  six-symbol neutral owner), the one direct-import reduction in `app/views/aluno.py`, and the
  governance-reader-only Phase-3 test delta. Technical review `flash_free`, effective
  `opencode/deepseek-v4-flash-free`, session `ses_040d538bfffegBsAJQbLJrnqSV`, cost 0,
  reviewed hash `f4b6cb00b4365cc7c20af5fcba1ac736ece1bab0ab9c6e0f89b19084799727f9`,
  mutation 0, PASS / findings NONE. Final hermetic: 984 passed / 17 deselected. Exact artifact:
  20 paths = 7 production + 7 tests + 6 governance; message catalog 536. Technical commit
  `73ebf0dc34681e74e778759af476e1cd2f981444`; publication and post-publication verification
  COMPLETE; index-visible/post-publication 170/170. NO ROUTE MOVEMENT, EXACT 9 REQUISICOES
  ROUTES REMAIN IN MAIN.PY. Contract:
  `docs/refactor/PHASE4_REQUISICOES_SHARED_OWNER_CONTRACT.md`. PHASE 4-B4.2 now moves that
  exact accepted cohort to `app.views.admin.requisicoes`: 9 global endpoints, 12 route-method
  pairs, RBAC 4/5/3, zero `app -> main`, exact 16-path candidate, focused lanes 138 + 107,
  routes 131, endpoints 130, governed pairs 134, RBAC unmapped 0, actor 402 and message
  catalog 536. Final hermetic qualification, independent review, technical publication and
  post-publication verification are complete at technical commit
  `3231dbd2ff9759d8f855f2a4118102783aedea83`. Contract:
  `docs/refactor/PHASE4_REQUISICOES_BLUEPRINT_CONTRACT.md`. PHASE 4-B5-P is the neutral
  admin-access shared-owner prerequisite, CLOSED / ACCEPTED: `app.admin_access`
  canonically owns exactly `_fetch_user_access_overrides`,
  `_build_access_scope_groups_for_level`, `_load_admin_access_context`,
  `_get_current_admin_access_context` and `_admin_can`; `main` has zero local bodies and
  re-exports all five by identity; six exact main consumers; zero
  `app.admin_access -> main` and zero `app.auth -> app.admin_access` edges; actual
  11-path artifact (2 production + 3 tests + 6 governance) within updated ceiling 12;
  B5-P-R2 supplemental scope authorization added and modified only
  `tests/test_phase4_requisicoes_shared_owners.py`, reading accepted B4.1 governance
  from fixed commit `c587098152e97d125f41a2d26f2f414c10ae5676` (classification
  `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED_B5_P_R2 /
  FIXED_ACCEPTED_B4_1_BASELINE / NO_RETROACTIVE_GENERIC_AUTHORITY`); final
  pre-publication hermetic after R2 1025/17/0/0/326.74s/exit 0 (the 306.41s run is
  pre-R2 historical); independent-review rerun 367.27s; post-publication focused 132
  passed/39.23s; accepted independent review session `ses_03c92c10affegAmZLZ63tmTjjA`
  (blocking 0 / nonblocking 3); routes 131; endpoints 130; business pairs 160; governed
   pairs 134; RBAC unmapped 0; actor 402; message catalog 536; route inventory and CSRF
   shadows byte-identical. **No Matrizes route moved; `app/views/admin/matrizes.py`
   remains absent; B5 blueprint extraction is NOT AUTHORIZED.** Technical commit
   `92486f87ea15697282a265cb7a9941678cb9138f` published; governance closeout published.
   Contract: `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md`. (Historical B5-P
   prerequisite bullet; superseded for the blueprint stage by PHASE 4-B5 below.)
   PHASE 4-B5 is **CLOSED / ACCEPTED**. Technical commit
   `2a122357a79080fa66aa19c00ed5ff8533308f41`, subject
   `Extract admin matrices blueprint`, parent
   `ef874b9d14b02656a0f26ea885024a280d49682e`, was published by one normal
   fast-forward; publication and post-publication verification are COMPLETE and external
   technical acceptance is GRANTED. The published manifest is exactly 17 paths.
   `app.views.admin.matrizes`
   owns exactly 10 global legacy endpoints / 12 route-method pairs and 21 corrected
   helpers; `main` re-exports by identity with zero local bodies; factory flag
   `register_admin_matrizes_blueprint=True`; RBAC 3 view / 7 edit / 2 full;
   `app.auth`/`app.admin_access` unchanged; zero `app -> main`; ensures/SQL/transaction/
   UI/messages/CSRF frozen; void names `_get_grupos_atividade`/`_get_matriz_active_norma_ids`
   absent (`SUPERVISOR CONTRACT CORRECTION / NOT A PATH-POOL EXPANSION / NOT A DOMAIN-SCOPE
   EXPANSION`). Corrected RED `20 failed / 4 passed`; primary GREEN `24 passed / 3.74s`;
   focused expanded `578 passed / 249.33s`; first full `1049 passed / 1 failed / 17 deselected`;
   B5-R3 one-for-one mutable-pool substitution; final full hermetic `1050 passed / 17 deselected /
   0 failed / 0 errors / 317.65s`; accepted post-publication bounded lane
   `59 passed / 0 failed / 0 errors / 22.59s`; reviewer gates 51 passed / 6.19s + supplemental 3 passed;
   routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0;
   actor 402; message catalog 536; route inventory byte-identical; CSRF `[8, 8]` owner-only;
   canonical SQLite opens 0. Contract: `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md`.
   PHASE 4 remains OPEN / INCREMENTAL IMPLEMENTATION and is not closed. Phase 5 and
   Phase 6 remain NOT AUTHORIZED; Migration v4 remains PROHIBITED.

   **Section-22 permanent historical record:** the Section-22 pre-implementation
   reconciliation gate was NOT executed before the first B5 production mutation as
   required by the original order. `SECTION_22_PROCESS_DEVIATION: VALID`;
   `ORIGINAL ORDERING REQUIREMENT: NOT SATISFIED`; `DISCOVERED: BEFORE PUBLICATION`;
   `LATE RECONCILIATION: EXECUTED / GREEN`; `TECHNICAL IMPACT: NONE DEMONSTRATED`;
   `SUPERVISOR ADJUDICATION: ACCEPTED_NONBLOCKING_GOVERNANCE_DEBT /
   PREPUBLICATION_PROCESS_DEVIATION / LATE_GATES_GREEN /
   NO_RETROACTIVE_COMPLIANCE_CLAIM`. The B5-R4 hard stop detected the missing record
   before publication; the B5-R5 waiver superseded only that pre-push documentary blocker
   and authorized the frozen technical commit unchanged. This closeout records the
   deviation truthfully; it does not rewrite history or claim retroactive compliance.
   Phase 4 remains open.
- **Fase 5 — Backup/sync offloading**: background jobs.
- **Fase 6 — `main.py` as entrypoint only**: ~50–150 lines.

Phase 1 is CLOSED / ACCEPTED. U1, U2, U3, U4, U5 and U6 are CLOSED / ACCEPTED.
Phase 2 is CLOSED / ACCEPTED. Macro Phase 3, PHASE 3-B11 and PHASE 3-B11-R1 are
CLOSED / ACCEPTED at technical commit `c9009bf3d68950ad4e0499b65928603e84bee341`
and governance commit `630d4eb448b992bdc3beb28752c30717989312bb`. PHASE 4-B1 is
CLOSED / ACCEPTED at `cd8a76b2484abc376174332578ecd8be4b8206ea`; PHASE 4-B2 is
CLOSED / ACCEPTED at `17e468ad938e873e1f9e9c303808ad31b9f3806b`; PHASE 4-B3 is
CLOSED / ACCEPTED at `50801b6bdddc4d2772853c13f4905c49e8c996cf`; PHASE 4-B4.1 is
CLOSED / ACCEPTED at `73ebf0dc34681e74e778759af476e1cd2f981444`; PHASE 4-B4.2 is
CLOSED / ACCEPTED at technical commit `3231dbd2ff9759d8f855f2a4118102783aedea83`.
PHASE 4-B5-P is CLOSED / ACCEPTED at technical commit
`92486f87ea15697282a265cb7a9941678cb9138f` (parent
`a0b56896252a276e562da3842d3d61b078bd9f27`); PHASE 4-B5-A DIAGNOSIS COMPLETE /
SHARED_OWNER_PREREQUISITE REQUIRED; PHASE 4-B5 is CLOSED / ACCEPTED at technical commit
`2a122357a79080fa66aa19c00ed5ff8533308f41`, subject
`Extract admin matrices blueprint`, parent
`ef874b9d14b02656a0f26ea885024a280d49682e`; publication and post-publication
verification COMPLETE; external technical acceptance GRANTED. Phase 4 is OPEN /
INCREMENTAL IMPLEMENTATION and is not closed. The neutral admin-access shared-owner
prerequisite (B5-P) remains CLOSED / ACCEPTED. PHASE 5:
NOT AUTHORIZED. PHASE 6: NOT AUTHORIZED.
MIGRATION V4: PROHIBITED. R1, R2 and R3 are CLOSED / ACCEPTED,
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
| `PHASE4_ADMIN_BLUEPRINT_COMPATIBILITY_CONTRACT.md` | PHASE 4-B1 | CLOSED / ACCEPTED at `cd8a76b2484abc376174332578ecd8be4b8206ea`; endpoint-preserving admin blueprint pattern: immutable legacy route specs, collision-safe `record_once` registrar, exact eight Configurações/Mensagens routes, settings-helper ownership, factory opt-out, `main` identity exports, and no app-to-main import. Its B2 prohibition is the preserved B1 phase-time boundary, superseded only by the separate B2 order/contract below. |
| `PHASE4_VERSIONING_SUBSYSTEM_CONTRACT.md` | PHASE 4-B2 | CLOSED / ACCEPTED at `17e468ad938e873e1f9e9c303808ad31b9f3806b`; canonical resolver/snapshot/shadow-read owners, exact three legacy diagnostics, six-key aluno lazy boundary, repository-root logging and logger-identity compatibility; full 954/17; index-visible 271; post-publication 282; exact 24-path artifact; technical review PASS; documentary addendum PASS; publication complete. |
| `PHASE4_ATIVIDADES_BLUEPRINT_CONTRACT.md` | PHASE 4-B3 | CURRENT / CLOSED / ACCEPTED at technical commit `50801b6bdddc4d2772853c13f4905c49e8c996cf`; exact 22 legacy endpoints / 29 route-method pairs; neutral shared activity-catalog and upload owners; exact message/CSRF scope-expansion reconciliation; full 974/17; index-visible and post-publication 300/300; exact 16-path artifact; technical review and documentary addendum PASS; publication complete. |
| `PHASE4_REQUISICOES_SHARED_OWNER_CONTRACT.md` | PHASE 4-B4.1 | CLOSED / ACCEPTED at technical commit `73ebf0dc34681e74e778759af476e1cd2f981444`; exact 20-path shared-owner artifact; full 984/17; index-visible and post-publication 170/170; technical review and documentary addendum PASS; zero Requisições route movement; publication complete; external supervisor acceptance recorded by B4.1-R2. |
| `PHASE4_REQUISICOES_BLUEPRINT_CONTRACT.md` | PHASE 4-B4.2 | CLOSED / ACCEPTED at technical commit `3231dbd2ff9759d8f855f2a4118102783aedea83`; exact 9 global endpoints / 12 route-method pairs; RBAC 4 view / 5 edit / 3 full; canonical `app.views.admin.requisicoes` owner; exact 16-path artifact; final hermetic 1005/17; index-visible 57; post-publication 56/1; Flash FREE technical review PASS; documentary addendum paid-Flash fallback PASS; publication complete; external supervisor acceptance recorded by B4.2-R2. |
| `PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md` | PHASE 4-B5-P | CLOSED / ACCEPTED at technical commit `92486f87ea15697282a265cb7a9941678cb9138f`, parent `a0b56896252a276e562da3842d3d61b078bd9f27`; PHASE 4-B5-A DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED; PHASE 4-B5-P is the accepted neutral admin-access shared-owner prerequisite. `app.admin_access` canonically owns exactly five symbols; `main` zero local bodies with identity re-exports; six exact main consumers; zero `app.admin_access -> main` and zero `app.auth -> app.admin_access` edges; actual 11-path artifact (2 production + 3 tests + 6 governance) within ceiling 12; B5-P-R2 supplemental scope authorization added and modified only `tests/test_phase4_requisicoes_shared_owners.py`, reading accepted B4.1 governance from fixed commit `c587098152e97d125f41a2d26f2f414c10ae5676`; final pre-publication hermetic after R2 1025/17/0/0/326.74s/exit 0 (the 306.41s run is pre-R2 historical); independent-review rerun 1025/17/0/0/367.27s; post-publication focused 132 passed/39.23s; accepted independent review session `ses_03c92c10affegAmZLZ63tmTjjA` (blocking 0 / nonblocking 3); routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC unmapped 0; actor 402; message catalog 536; route inventory and CSRF shadows byte-identical. No Matrizes route moved at B5-P-time; `app/views/admin/matrizes.py` absent at B5-P-time; B5 blueprint extraction NOT AUTHORIZED at B5-P-time. Publication and governance closeout published. This B5-P row is historical / superseded for the blueprint stage by the PHASE 4-B5 row below. |
| `PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md` | PHASE 4-B5 | CLOSED / ACCEPTED at published technical commit `2a122357a79080fa66aa19c00ed5ff8533308f41`, subject `Extract admin matrices blueprint`, parent `ef874b9d14b02656a0f26ea885024a280d49682e`; publication and post-publication verification COMPLETE; external technical acceptance GRANTED; published manifest exactly 17 paths; independent technical review COMPLETE / PASS (READ-ONLY, mutation 0, verdict PASS / SCOPE EXACT / BEHAVIOR PRESERVED). `app.views.admin.matrizes` canonically owns exactly 10 global legacy endpoints / 12 route-method pairs and 21 corrected helpers; `main` zero local bodies with identity re-exports; `bp_admin_matrizes` + immutable `LEGACY_ROUTE_SPECS` via accepted registrar; factory keyword-only `register_admin_matrizes_blueprint=True`; RBAC exactly 3 view / 7 edit / 2 full; `app.auth` and `app.admin_access` unchanged; zero `app -> main`; ensures/SQL/transaction/UI/messages/CSRF frozen; void names `_get_grupos_atividade`/`_get_matriz_active_norma_ids` absent (classification `SUPERVISOR CONTRACT CORRECTION / NOT A PATH-POOL EXPANSION / NOT A DOMAIN-SCOPE EXPANSION`). Evidence: corrected RED `20 failed / 4 passed / 0 collection errors`; primary GREEN `24 passed / 3.74s`; focused expanded (44 files) `578 passed / 249.33s`; first full `1049 passed / 1 failed / 17 deselected / 370.60s`; B5-R3 one-for-one mutable-pool substitution (node 1 passed / 0.64s; affected focused 143 passed / 24.30s); final full hermetic fresh `1050 passed / 17 deselected / 0 failed / 0 errors / 317.65s` (collected 1067); reviewer gates 51 passed / 6.19s + supplemental 3 passed; routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC unmapped 0; actor 402; message catalog 536; route inventory byte-identical; CSRF `[8, 8]` owner-only; canonical SQLite opens 0. Exact 11-path technical manifest (3 production + 8 tests/snapshots) within ceiling 18 after governance; frozen identities recorded in the contract; publication and post-publication verification COMPLETE; accepted post-publication bounded lane 59 passed / 0 failed / 0 errors / 22.59s. |
| `PHASE4_ALUNOS_TURMAS_CURSOS_SHARED_OWNER_CONTRACT.md` | PHASE 4-B6-P | PHASE 4-B6-A DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED (historical read-only prerequisite diagnosis; supervisor correction excluded `periodo_corrente`, which remains local in `main`); PHASE 4-B6-P CLOSED / ACCEPTED at accepted technical commit `0b003c5f00e5e6181c9b9a5f96d8572b8488323f` (`Extract B6 shared neutral owners`), parent `1bf5173949b0bf0bdce15d1b87d6ed15d535158c`, plus accepted recovery commit `5af7fc70547fccbfed42ebaf5ca353365371c892` (`Repair B6-P post-publication governance state`). Technical publication COMPLETE; post-publication recovery COMPLETE; post-publication verification COMPLETE; external supervisor acceptance GRANTED. Permanent process record `PREPUBLICATION_BOUNDED_GATE_INVOCATION_ERROR / DISCOVERED_POST_PUBLICATION / NO_RETROACTIVE_GREEN_CLAIM`; invalid command did not execute pytest; correct post-publication gates recovered the documentary defect. Neutral Alunos/Turmas/Cursos shared-owner prerequisite: exactly 9 shared symbols moved to neutral owners 3/5/1 — `app.academics` (3), `app.user_accounts` (5), `app.web.request` (1); `main` identity re-exports with zero local bodies; `app.views.core` direct import of `normalize_usuario_access_for_user_type`, residual lazy map exactly `aluno_url`/`get_db_connection`/`logger`; `periodo_corrente` local AST-identical; owner imports isolated from `main`, no new owner→`main` edge/cycle. R1 literal `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED / MESSAGE_SCANNER_OWNER_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY` (scanner provenance literal: moved `ValueError` message usage/source owner changed from `main.py` to `app/academics.py` while key `msg_4642b1608cf6a126` and exact default text remained unchanged — the message itself did not change); R3 literal `PRE_REVIEW_SCOPE_EXPANSION / ONE_FOR_ONE_TEST_POOL_SUBSTITUTION_PLUS_FOUR_ADDITIONS / STALE_GOVERNANCE_TEST_RECONCILIATION / MESSAGE_SCANNER_ALLOWLIST_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY`; full 1066/17; independent review PASS; publication complete. |
| `PHASE4_ALUNOS_TURMAS_CURSOS_BLUEPRINT_CONTRACT.md` | PHASE 4-B6 | CLOSED / ACCEPTED at technical commit `3d9660a99e6944ff94a3991a353ecf3aaf300987`, subject `Extract admin alunos turmas cursos blueprint`; exact 17 endpoints / 24 route-method pairs / 10 helpers; main 27 identity re-exports and zero local B6 bodies; RBAC 6/13/5; B6-P owners preserved; R1 exactly three dead `periodo_corrente` context removals while the function remains main-local; zero `app -> main`; CSRF B6 11 owner-only and exact historical partitions 19/24; final full 1095 passed / 17 deselected / 0 failed/errors / 433.87s / canonical opens 0; exact 16-path candidate ceiling; technical publication COMPLETE; post-publication verification COMPLETE; external supervisor acceptance GRANTED; governance closeout published by R3. |
| `PHASE4_ARQUIVOS_ALERTAS_SHARED_OWNER_CONTRACT.md` | PHASE 4-B7-P | CLOSED / ACCEPTED at accepted technical commit `1c82a1954250aa5e6654349ce77a50d60f03fe8f`, subject `Extract B7 shared neutral owners`, parent `b6d6e2295e2beeba046cfe1f4c1614f667261ad2`; technical publication COMPLETE; post-publication bounded verification COMPLETE; external supervisor technical acceptance GRANTED. PHASE 4-B7-A DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE_REQUIRED (accepted). Exact 4 shared symbols moved to neutral owners 2/1/1: `app.db_maintenance` (`ensure_admin_arquivos_table`, `ensure_admin_alertas_table`, joining pre-existing `ensure_reportes_table`), new `app.admin_files` (`get_admin_arquivo`), new `app.admin_alerts` (`list_active_admin_alertas`). `main` identity re-exports, zero local bodies; all four bodies AST-equivalent to entry baseline `b6d6e2295e2beeba046cfe1f4c1614f667261ad2:main.py`. `aluno._get_main_helpers()` reduced 5→2 keys (`get_student_request_update_alert`, `mark_student_request_updates_seen` remain, both out-of-scope Requisições dependencies). Zero route movement: 12 handlers / 13 route-method pairs remain main-local; `uploaded_file` and `admin_dashboard` AST-unchanged; Reportes ownership unchanged. RED 11 collected / 7 failed / 4 passed, exit 1; GREEN 11 passed, exit 0. R2 supplemental-scope correction (supervisor-authorized): identical 5→2 fix applied to `tests/test_db_schema_maintenance.py` and `tests/test_phase4_versioning_subsystem.py`, classification `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED / ALUNO_LAZY_MAP_INVARIANT_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY`. R2 environmental waiver (supervisor-authorized): full suite `1103 passed / 3 failed / 17 deselected`, NOT claimed GREEN; the three failures independently reproduced identical on unmodified entry baseline via disposable worktree, classification `PRE_EXISTING_BASELINE_REPRODUCED / ENVIRONMENTAL_ENCODING_FAILURE / UNRELATED_TO_B7_P / ACCEPTED_NONBLOCKING_RESIDUAL / NO_RETROACTIVE_GREEN_CLAIM`. B7-P-specific/affected focused gates 0 failed/0 errors/exit 0. Routes 131; endpoints 130; business pairs 160; RBAC unmapped 0; message catalog 536; `database.db` 544768 bytes / `a3a55e63…f0e9` unchanged. Exact manifest 15 paths (5 production + 4 tests + 6 governance); path 16 hard stop. PHASE 4-B7 route/blueprint extraction remains NOT AUTHORIZED. |
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
| Phase 4-B2 versioning ownership and compatibility | `tests/test_phase4_versioning_subsystem.py` + versioning resolver/shadow/diagnostic/aluno/ownership/runtime/route/RBAC gates + `docs/refactor/PHASE4_VERSIONING_SUBSYSTEM_CONTRACT.md` | CLOSED / ACCEPTED at `17e468ad938e873e1f9e9c303808ad31b9f3806b`; contract 14; affected 241; full 954 passed / 17 deselected; index-visible 271; post-publication 282; routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0; actor matrix 402; technical review PASS; documentary addendum PASS; publication complete |
| Phase 4-B3 Atividades blueprint and scope reconciliation | `tests/test_phase4_atividades_blueprint.py` + Atividades/import/catalog/CSRF/B1/B2/route/RBAC/actor/runtime gates + `docs/refactor/PHASE4_ATIVIDADES_BLUEPRINT_CONTRACT.md` | CLOSED / ACCEPTED at `50801b6bdddc4d2772853c13f4905c49e8c996cf`; B3 contract 19; affected lane 353; full 974 passed / 17 deselected; index-visible 300; post-publication 300; exact 22 endpoints / 29 combinations; routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0; actor matrix 402; route snapshot unchanged; exact 16-path artifact; technical review and documentary addendum PASS; publication complete. |
| Phase 4-B4.1 Requisições shared-owner prerequisite | `tests/test_phase4_requisicoes_shared_owners.py` + B1/B2/B3/Phase-3/route/RBAC/actor gates + `docs/refactor/PHASE4_REQUISICOES_SHARED_OWNER_CONTRACT.md` | CLOSED / ACCEPTED at `73ebf0dc34681e74e778759af476e1cd2f981444`; exact 20-path artifact; full 984/17; index-visible 170; post-publication 170; routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0; actor matrix 402; message catalog 536; technical review and documentary addendum PASS; publication complete. |
| Phase 4-B4.2 Admin Requisições blueprint | `tests/test_phase4_requisicoes_blueprint.py` + shared-owner/functional/CSRF/B1/B2/B3/Phase-3/route/RBAC/actor/runtime gates + `docs/refactor/PHASE4_REQUISICOES_BLUEPRINT_CONTRACT.md` | CLOSED / ACCEPTED at `3231dbd2ff9759d8f855f2a4118102783aedea83`; RED 20 failed / 3 passed and first full 1001/4/17 preserved historically; final hermetic 1005/17; index-visible 57; post-publication 56/1; exact 9 endpoints / 12 pairs; routes 131; endpoints 130; governed 134; unmapped 0; actor 402; message catalog 536; CSRF 5/5 owner-only; technical review PASS; documentary addendum PASS; publication complete. |
| Phase 4-B5-P Matrizes neutral admin-access shared-owner prerequisite | `tests/test_phase4_matrizes_shared_owners.py` (new) + access/admin-context/route/RBAC/CSRF/message gates + `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md` | CLOSED / ACCEPTED at technical commit `92486f87ea15697282a265cb7a9941678cb9138f`, parent `a0b56896252a276e562da3842d3d61b078bd9f27`; actual 11-path artifact (2 production + 3 tests + 6 governance) within ceiling 12; B5-P-R2 added and modified only `tests/test_phase4_requisicoes_shared_owners.py`, reading accepted B4.1 governance from fixed commit `c587098...`, classification `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED_B5_P_R2 / FIXED_ACCEPTED_B4_1_BASELINE / NO_RETROACTIVE_GENERIC_AUTHORITY`, R2 node 1 passed in 1.02s, affected governance aggregate 118 passed in 16.70s; corrected pre-production RED 20 failed; recovered core lane 25 passed; focused lane 168 passed; final pre-publication hermetic after R2 1025/17/0/0/326.74s/exit 0 (the 306.41s run is pre-R2 historical); independent-review rerun 367.27s; post-publication focused 132 passed/39.23s; accepted review `ses_03c92c10affegAmZLZ63tmTjjA`; routes 131; endpoints 130; business pairs 160; governed pairs 134; unmapped 0; actor 402; message catalog 536; route inventory and CSRF shadows byte-identical; B4.2 five-owner-only deltas proven against fixed `c587098...` baseline. No Matrizes route moved at B5-P-time; `app/views/admin/matrizes.py` absent at B5-P-time; B5 blueprint extraction NOT AUTHORIZED at B5-P-time. Publication and governance closeout published. Historical B5-P row, superseded for the blueprint stage by the B5 row below. |
| Phase 4-B5 Matrizes admin blueprint extraction | `tests/test_phase4_matrizes_blueprint.py` (new) + `tests/test_phase4_matrizes_shared_owners.py` + matrizes functional/versioning/CSRF lanes + `tests/test_phase4_configuracoes_blueprint.py` (membership) + `tests/test_phase4_atividades_blueprint.py` + `tests/test_phase4_requisicoes_blueprint.py` + `tests/test_admin_matriz_nova_versao_card.py` + CSRF snapshots + `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md` | CLOSED / ACCEPTED at technical commit `2a122357a79080fa66aa19c00ed5ff8533308f41`, parent `ef874b9d14b02656a0f26ea885024a280d49682e`; publication and post-publication verification COMPLETE; external technical acceptance GRANTED; published manifest exactly 17 paths; independent technical review COMPLETE / PASS (READ-ONLY, mutation 0, verdict PASS / SCOPE EXACT / BEHAVIOR PRESERVED). Exact 10 global legacy endpoints / 12 route-method pairs / 21 corrected helpers owned by `app.views.admin.matrizes`; `main` identity re-exports with zero local bodies; factory `register_admin_matrizes_blueprint=True`; RBAC 3 view / 7 edit / 2 full; `app.auth`/`app.admin_access` unchanged; zero `app -> main`; ensures/SQL/transaction/UI/messages/CSRF frozen; void names absent. Corrected RED `20 failed / 4 passed / 0 collection errors`; primary GREEN `24 passed / 3.74s`; focused expanded `578 passed / 249.33s`; first full `1049 passed / 1 failed / 17 deselected / 370.60s`; B5-R3 one-for-one mutable-pool substitution (node 1 passed / 0.64s; affected focused 143 passed / 24.30s); final full hermetic `1050 passed / 17 deselected / 0 failed / 0 errors / 317.65s` (collected 1067); reviewer gates 51 passed / 6.19s + supplemental 3 passed; routes 131; endpoints 130; governed pairs 134; unmapped 0; actor 402; message catalog 536; route inventory byte-identical; CSRF `[8, 8]` owner-only; canonical SQLite opens 0. Exact 11-path technical manifest (3 production + 8 tests/snapshots) within ceiling 18 after governance. Frozen identities recorded in the contract. |
| Phase 4-B6-P Alunos/Turmas/Cursos neutral shared-owner prerequisite | `tests/test_phase4_alunos_turmas_cursos_shared_owners.py` (new) + academics/user-accounts/web-request/core consumers + message/RBAC/route/CSRF gates + `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_SHARED_OWNER_CONTRACT.md` | PHASE 4-B6-A DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED (historical read-only prerequisite diagnosis; supervisor correction excluded `periodo_corrente`, which remains local in `main`); PHASE 4-B6-P CLOSED / ACCEPTED at accepted technical commit `0b003c5f00e5e6181c9b9a5f96d8572b8488323f`, parent `1bf5173949b0bf0bdce15d1b87d6ed15d535158c`, and accepted recovery commit `5af7fc70547fccbfed42ebaf5ca353365371c892`. Technical publication, post-publication recovery and verification COMPLETE; external supervisor acceptance GRANTED; governance closeout publication governed by `Record acceptance of Phase 4-B6-P`. Permanent process record `PREPUBLICATION_BOUNDED_GATE_INVOCATION_ERROR / DISCOVERED_POST_PUBLICATION / NO_RETROACTIVE_GREEN_CLAIM`. Exactly 9 shared symbols to neutral owners 3/5/1; `main` identity re-exports zero local bodies; `app.views.core` direct import of `normalize_usuario_access_for_user_type`, residual lazy map exactly `aluno_url`/`get_db_connection`/`logger`; `periodo_corrente` local AST-identical; owner isolation from `main`, no new edge/cycle. R1 literal `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED / MESSAGE_SCANNER_OWNER_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY` (RED catalog 535 key `msg_4642b1608cf6a126` absent → GREEN catalog 536, default `"Turma sem código para gerar matrícula."`, source `app/academics.py`, no duplicate; scanner provenance literal: moved `ValueError` message usage/source owner changed from `main.py` to `app/academics.py` while key and exact default text remained unchanged — the message itself did not change); R3 literal `PRE_REVIEW_SCOPE_EXPANSION / ONE_FOR_ONE_TEST_POOL_SUBSTITUTION_PLUS_FOUR_ADDITIONS / STALE_GOVERNANCE_TEST_RECONCILIATION / MESSAGE_SCANNER_ALLOWLIST_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY` (`test_residual_shared_helpers.py` unchanged read-only gate; first full 1061/5/17; five-node recovery 5/5; coupled lane 77/77; fresh final 1066/17/0/0/328.77s/exit 0/`CANONICAL_SQLITE_OPENS=0`). Historical TDD/scanner-owner chronology preserved: structural RED 13/31; structural GREEN 44; focused 203/2 (scanner-owner findings). Earlier focused 206 passed/117.65s/exit 0 (first harness exit 1 = recoverable MSYS `/c`→`D:/c` basetemp defect; native `C:/` rerun passed). Fresh invariants: routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0; actor 402 = 263 + 139; message catalog 536; route inventory byte-identical 20814 bytes / `6e32148c…49fa`; CSRF shadows each 288509 bytes / `4b16f1b4…769`; canonical database 544768 / `a3a55e63…70fe9`, opens 0; protected residual 17420 / `7388cfbc…bb0e`. Zero B6 route movement; **PHASE 4-B6 NOT AUTHORIZED**. |
| Phase 4-B7-P Arquivos/Alertas neutral shared-owner prerequisite | `tests/test_phase4_arquivos_alertas_shared_owners.py` (new) + `tests/test_phase4_requisicoes_shared_owners.py` + `tests/test_db_schema_maintenance.py` + `tests/test_phase4_versioning_subsystem.py` + `docs/refactor/PHASE4_ARQUIVOS_ALERTAS_SHARED_OWNER_CONTRACT.md` | PHASE 4-B7-A DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE_REQUIRED (accepted); PHASE 4-B7-P CLOSED / ACCEPTED at accepted technical commit `1c82a1954250aa5e6654349ce77a50d60f03fe8f`, subject `Extract B7 shared neutral owners`, parent `b6d6e2295e2beeba046cfe1f4c1614f667261ad2`; technical publication COMPLETE; post-publication bounded verification COMPLETE; external supervisor technical acceptance GRANTED. Exact 4 shared symbols to neutral owners 2/1/1 (`app.db_maintenance`, `app.admin_files` new, `app.admin_alerts` new); `main` identity re-exports zero local bodies; aluno lazy map reduced 5→2; zero route movement. RED 11/7/4/exit1; GREEN 11/0/0/exit0. R2 supplemental-scope correction (supervisor-authorized) reconciled two additional frozen 5-key assertions in `test_db_schema_maintenance.py` and `test_phase4_versioning_subsystem.py`. R2 environmental waiver (supervisor-authorized): full suite 1103 passed / 3 failed / 17 deselected, NOT GREEN, the three failures baseline-reproduced and unrelated. Routes 131; endpoints 130; business pairs 160; RBAC unmapped 0; message catalog 536; `database.db` unchanged. Exact 15-path manifest; PHASE 4-B7 route extraction NOT AUTHORIZED. |
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
