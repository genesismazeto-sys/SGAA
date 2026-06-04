# Agent Handoff

Last updated: 2026-06-04
Closeout: D7.1-CLOSEOUT-DOCS-1
Executor: Codex

## Current State

- D7.1-CLOSEOUT-DOCS-1 is approved.
- D6.6-DISPLAY-1R remains approved.
- D6.6-DISPLAY-TEXT-ACCENTS-1R remains approved.
- D6.7-PLAN remains approved.
- Commit `e0427ee` — `Add activity version matrix contract tests`.
- Proved contract: if `turma.matriz_id` is `NULL`, the writer does **not** stamp `atividade_versao_id`.
- Test status for D7.1: `tests/test_matriz_versao_contract.py` + `tests/test_activity_versioning_resolver.py` + `tests/test_aluno_matrix_scope.py`: `17 passed`; `tests/test_activity_versioning_shadow_read.py` + `tests/test_admin_snapshot_diagnostics.py`: `30 passed, 4 known openpyxl warnings`; total `47 passed, 0 failed`.
- No code change was made during this docs-only closeout.
- D6.4.0 remains activated and validated in the target environment with snapshot write `ON` and shadow read `ON`.
- The target app ran on `127.0.0.1:5001` after port fallback.
- `app/db.py` has auto-fill in a seed/dev tool, but that does not run in normal runtime.

## Last Closed Phase

- D7.1-CLOSEOUT-DOCS-1 approved.
- Added activity version matrix contract tests in commit `e0427ee`.
- Proved contract: if `turma.matriz_id` is `NULL`, the writer does **not** stamp `atividade_versao_id`.
- Ambiguity of version remains a hard error.
- Resolver remains read-only.
- No UI, schema, calculation, deferment, cutover, or backfill change.
- `atividade_id` preserved as the operational source.
- Snapshot remains admin-only and read-only.

## Recommended Next Phase

- No new implementation phase is approved right now.
- D7.2 must address UI/admin catalog + controlled legacy mapping, but requires a new explicit scope before starting.
- Do not start D7.2 without a new approved scope.
- Keep the current D6.6 state: admin-only, diagnostic, read-only.
- If work resumes later, prefer docs/runbook clarification or a fresh architectural review before any new code phase.

## Risks To Keep In View

- Do not switch the main JOIN yet.
- Do not use snapshot data for approval or rejection decisions.
- Do not use snapshot data for limit or hours calculation.
- Do not use snapshot data for matrix scope, dashboards, import flow, or student screens.
- Keep `/admin/requisicoes` badge-only for now.
- Keep `/admin/processar_requisicao/<id>` `POST` fully legacy.
- Do not change import flow.
- Do not change student, dashboard, or progress flows in the next phase.
- Always validate mixed data: older rows with `NULL` snapshot fields and newer rows with snapshot data.
- Do not claim the system distinguishes an admin's explicit choice from a dev-tool auto-fill; that distinction does not exist in the current schema.
- D7.2 requires new scope before any code work begins.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Summarize understanding before implementing anything.
- Treat `atividade_id` as the operational source of truth.
- Do not expand snapshot display beyond the current admin-only read-only surfaces unless a new approved phase explicitly authorizes it.
- D7.2 must not start without a new approved scope covering UI/admin catalog and controlled legacy mapping.
