# PHASE 4-B4.1 — Requisições neutral shared-owner contract

## Status and authority

PHASE 4-B4-A: **CLOSED / ACCEPTED**.

PHASE 4-B4.1 is an authorized, bounded shared-owner extraction. Its recorded state is
**IMPLEMENTED / AWAITING SUPERVISOR REVIEW**. PHASE 4 remains open.

PHASE 4-B4.2: NOT AUTHORIZED. Phase 5: NOT AUTHORIZED. Phase 6: NOT AUTHORIZED.
Migration v4: PROHIBITED.

## Baseline and publication identity

- Repository: `genesismazeto-sys/SGAA`.
- Branch: `refactor/architecture-safety-net`.
- Parent: `185426daccc9f0eb0dba4497248100c1a88d15fa` (`Record acceptance of Phase 4-B3`).
- Required baseline divergence: `0/0`.
- Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`.
- B4.1 commit subject: `Extract requisition shared owners`.
- The exact commit identity is resolved from that subject as the single child of the
  recorded parent on the authorized feature branch; the commit tree does not carry a
  self-referential SHA.

## Exact scope

B4.1 performs only three compatibility-preserving owner cuts:

1. `app/settings.py` becomes the sole defining owner of the eight app-settings helpers
   formerly defined by `app/views/admin/configuracoes.py`. Configurações and `main.py`
   re-export the same callable identities.
2. `app/requisitions.py` becomes the sole defining owner of
   `auto_indefer_devolvidas`. Its helper-owned conditional commit remains unchanged.
3. `app/matrix_scope.py` becomes the sole defining owner of the shared matrix-scope
   query/label functions. `main.py` preserves compatibility identities and
   `app/views/aluno.py` consumes `get_effective_matriz_for_turma` directly.

`utils/messages.py` explicitly scans `app/settings.py` so the six moved backend message
usages retain their existing keys/defaults while their canonical `source_path` changes.
The catalog remains 536 keys.

## Expanded-candidate reconciliation

Classification: **B4_1_SCOPE_EXPANSION / COHERENT_NEUTRALIZATION /
SUPERVISOR_RECONCILED**.

- `app/settings.py` is accepted as the neutral owner of all eight B1 settings helpers.
  At B1-time, Configurações defined all eight. At B4.1-time, defining ownership moves to
  `app.settings`; Configurações and `main` retain identity-compatible exports. All eight B1
  routes and their accepted behavior remain unchanged.
- `app/matrix_scope.py` is accepted as the dedicated neutral matrix-scope owner instead of
  expanding `app/academics.py`. Its exact closure is `MATRIZ_STATUS_META`,
  `_matriz_status_label`, `_matriz_option_label`, `get_effective_matriz_for_turma`,
  `is_activity_allowed_for_turma_matrix`, and
  `get_allowed_activity_ids_for_turma_matrix`. Baseline defining owner: `main.py`; B4.1
  defining owner: `app.matrix_scope`; `main` retains identity exports.
- Runtime consumers are bounded to `main` and Aluno. Dashboard consumes
  `get_effective_matriz_for_turma`; Turmas consumes `get_effective_matriz_for_turma` and
  `_matriz_option_label`; Matrizes consumes `MATRIZ_STATUS_META` and
  `_matriz_status_label`; Requisições consumes `_matriz_option_label`,
  `get_allowed_activity_ids_for_turma_matrix`, and
  `is_activity_allowed_for_turma_matrix`; Aluno directly consumes only
  `get_effective_matriz_for_turma`. The module contains no route body or Blueprint and is
  not a generic owner for the future Matrizes cohort.
- B2 established six Aluno lazy-main residual edges at B2-time. B4.1 later removes only
  `get_effective_matriz_for_turma` by establishing its neutral owner. The exact B4.1-time
  five are `ensure_admin_arquivos_table`, `get_admin_arquivo`,
  `get_student_request_update_alert`, `list_active_admin_alertas`, and
  `mark_student_request_updates_seen`.
- `tests/test_phase3_schema_startup_transaction_contract.py` changes only
  `test_macro_phase3_acceptance_closeout_is_current_and_bounded`, replacing the former
  blanket “no checked Phase 4 item” assertion with the exact accepted/current Phase 4
  governance checklist. It does not relax transaction assertions or change migration,
  startup, schema, or any other Phase-3 technical expectation.

## No route movement

**NO ROUTE MOVEMENT. EXACT 9 REQUISICOES ROUTES REMAIN IN MAIN.PY.**

`app/views/admin/requisicoes.py` is not created. All nine endpoint callables remain
top-level definitions in `main.py`, stay bound to their existing global endpoint names,
and preserve their function ASTs. No URL, method, endpoint, RBAC, CSRF, template,
redirect, JSON, transaction, SQL, upload, document, snapshot or shadow-read behavior is
changed.

## Transaction and behavior invariants

- The eight app-settings helpers are AST-identical to their accepted B1 bodies.
- The five moved matrix functions and `MATRIZ_STATUS_META` are AST-identical to their
  baseline bodies/assignment.
- `auto_indefer_devolvidas` is AST-identical to its baseline body and retains exactly one
  conditional `commit()` and no rollback.
- All nine Requisições route functions are AST-identical to the baseline.
- No functional hardening is included. Existing upload/rollback/cleanup risks remain
  out of scope.
- No schema, migration, canonical database opening or protected-artifact mutation is
  authorized.

## Exact 20-path manifest

Production (7):

- `app/matrix_scope.py`
- `app/requisitions.py`
- `app/settings.py`
- `app/views/admin/configuracoes.py`
- `app/views/aluno.py`
- `main.py`
- `utils/messages.py`

Tests (7):

- `tests/test_db_schema_maintenance.py`
- `tests/test_phase4_atividades_blueprint.py`
- `tests/test_phase4_configuracoes_blueprint.py`
- `tests/test_phase3_schema_startup_transaction_contract.py`
- `tests/test_phase4_requisicoes_shared_owners.py`
- `tests/test_phase4_versioning_subsystem.py`
- `tests/test_residual_shared_helpers.py`

Governance (6):

- `AGENT_HANDOFF.md`
- `PROJECT_STATE.md`
- `docs/DOCUMENTATION_INDEX.md`
- `docs/mapeamento/05_avaliacao_refactor.md`
- `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
- `docs/refactor/PHASE4_REQUISICOES_SHARED_OWNER_CONTRACT.md`

Any path outside this manifest is unauthorized for B4.1.

## Test-driven and deterministic gates

- Baseline focused gate: 125 passed; canonical SQLite opens 0.
- Technical RED: 7 expected failures and 1 no-route-movement pass before owners existed.
- Governance RED: 1 expected missing-contract failure.
- AST equivalence: settings, Requisições neutral helper, matrix scope, matrix metadata and
  all nine route functions PASS.
- Focused affected gate before governance closeout: 247 passed; canonical SQLite opens 0.
- First full gate: 981 passed / 3 failed / 17 deselected. Two failures were stale
  governance readers mechanically exposed by the new current B4.1 state and were corrected;
  one randomized pre-existing turma-code collision is retained as recovered test evidence.
- Recovered failures: the three nodes passed together after the bounded corrections/isolation.
- Final full hermetic: 984 passed / 17 deselected / 419.95s; canonical SQLite opens 0.
- Technical review: logical/selected route `flash_free`; requested/effective model
  `opencode/deepseek-v4-flash-free`; session `ses_040d538bfffegBsAJQbLJrnqSV`; exit 0;
  cost 0; fallback none; mutation count 0; PASS; material findings NONE. Reviewed tracked
  diff SHA-256: `f4b6cb00b4365cc7c20af5fcba1ac736ece1bab0ab9c6e0f89b19084799727f9`.
  Complete pre-addendum candidate SHA-256:
  `ddc73cb94786899595f3cce9d577bdbcca961a082c83866498a36ebd4687a23f`.
  Non-governance SHA-256:
  `74649089be0699dff4440260bdb11793b4e5793550f17456893f4a281bd6096b`.
  Reviewer narrative “8 tests” is rejected as
  `REJECTED_NON_MATERIAL / STALE NARRATIVE COUNT / NO TECHNICAL CONSEQUENCE`; the exact
  manifest contains seven test paths.
- Index-visible and post-publication counts are recorded in the current state/handoff and
  execution closeout after their respective boundaries.

## Irreversible boundaries

- Repository mutation: crossed only for the exact source/test/governance manifest.
- Commit: one bounded selective commit after all gates and read-only review pass.
- Push: one fast-forward push of only the authorized feature branch.
- No canonical database, migration, cleanup, removal, production or B4.2 boundary is
  crossed.

## Next authority

External supervisor review of B4.1 is the next action after this selective publication.
B4.2 remains separately gated and must not begin without a new explicit order.
