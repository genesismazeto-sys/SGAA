# Project State

Last updated: 2026-06-04
Closeout: D7.1-CLOSEOUT-DOCS-1
Executor: Codex

## Permanent State

### D6.4.0 - controlled snapshot write
- Implemented and approved.
- Flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` exists and remains default `OFF` in code.
- Controlled activation in the target environment was validated.
- The target environment used port `5001` after a conflict on `5000`.
- Rollback was validated: with the flag `OFF`, new requests are created with versioned fields set to `NULL`.
- `atividade_id` remains preserved and operational.
- No backfill was performed.
- No read cutover was performed.

### D6.5 - admin-only diagnostics
- Implemented and approved.
- `/admin/requisicoes` shows the discrete badge `"Snapshot versionado"`.
- `/admin/processar_requisicao/<id>` shows the read-only block `"Diagnostico do snapshot"`.
- The diagnostic is admin-only.
- No student screen was changed.
- JOIN, calculation, decision, limits, and processing remain on the legacy `atividade_id`.
- Missing or invalid snapshot data does not break the screen.
- Raw JSON is not exposed.
- Forbidden fields do not leak: observations, free text, documents, paths, or additional personal data.

### D6.6 - admin read-only comparison display
- D6.6-DISPLAY-1 approved.
- Commit `b9ffda2` - `Add admin snapshot comparison display`.
- Commit `09749ef` - `Fix snapshot comparison labels`.
- D6.6-DISPLAY-TEXT-ACCENTS-1R approved.
- Flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY` exists and remains default `OFF` in code.
- The display flag is independent from `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE`.
- The display flag is independent from `SGAA_VERSIONED_RESOLVER_SHADOW_READ`.
- With the flag `ON`, `/admin/processar_requisicao/<id>` `GET` shows the read-only comparison `Legado atual` vs `Snapshot versionado`.
- `/admin/requisicoes` did not gain a new comparison and still shows only the D6.5 badge.
- POST, processing, calculation, limits, and matrix scope remain on the legacy `atividade_id`.
- No backfill was performed.
- No cutover was performed.
- No student screen was changed.

### D6.7 - planning decision after D6.6 display
- D6.7-PLAN completed in read-only mode on `HEAD` `04b40cc`.
- No code, template, test, database, env, flag, or schema change was made during the analysis.
- Recommendation: pause at D6.6.
- `/admin/processar_requisicao/<id>` `GET` is already the safe and sufficient diagnostic surface.
- `/admin/processar_requisicao/<id>` `POST` remains legacy and out of scope.
- `/admin/requisicoes` should remain badge-only.
- Student request screens should not receive snapshot display now.
- Dashboards, progress, turma, and import flow remain out of scope.
- Snapshot remains admin-only, diagnostic, and read-only.
- `atividade_id` remains the operational source of truth.
- No backfill was performed.
- No read cutover was performed.
- No operational use of snapshot data was approved.

### D7.1 - activity version matrix contract tests
- Implemented and approved.
- Commit `e0427ee` — `Add activity version matrix contract tests`.
- Added helper `_get_turma_explicit_matriz_id_for_snapshot`.
- Added pre-check in `maybe_write_versioned_requisicao_snapshot`.
- Proved contract: if `turma.matriz_id` is `NULL`, the writer does **not** stamp `atividade_versao_id`.
- Ambiguity of version remains a hard error.
- Resolver remains read-only.
- No UI was changed.
- No schema was changed.
- No calculation or deferment was changed.
- No cutover or backfill was performed.
- `app/db.py` contains auto-fill in a seed/dev tool, but that does not run in the normal runtime of this branch.

## Relevant Commits

- `483f069` - Add controlled versioned snapshot write for requests
- `ba5a3df` - Document snapshot write activation runbook
- `8845dce` - Record controlled snapshot activation validation
- `18c169a` - Record target snapshot activation validation
- `bb1ca51` - Add admin snapshot diagnostics
- `b9ffda2` - Add admin snapshot comparison display
- `09749ef` - Fix snapshot comparison labels
- `e0427ee` - Add activity version matrix contract tests

## Current Risks And Limits

- D6.6 remains admin-only display work, not an operational read path based on snapshot data.
- Snapshot data must not be used to approve or reject requests.
- Snapshot data must not be used to calculate hours or limits.
- Snapshot data must not be used for matrix scope, dashboards, import flow, or student screens.
- Import flow remains out of scope.
- Student dashboards and progress remain on the legacy path.
- Backfill for old requests has not been performed yet.
- D6.7 concluded with the recommendation to pause at D6.6 rather than expand snapshot surfaces now.
- D7.1 proved the contract for `turma.matriz_id == NULL` but did not introduce any new runtime surface.
- D7.2 must address UI/admin catalog + controlled legacy mapping, but requires a new scope before starting.

## Permanent Working Directives

- ChatGPT acts as technical supervisor, auditor, and orchestrator.
- Codex or GitCP is the main executor for real code changes.
- MiniMax may be used for low-cost volume work, logs, tests, repetitive tasks, and simple low-risk patches.
- Kimi may be used for strong second opinions, architecture work, or difficult multi-file problems.
- GLM, Qwen, MiMo, and DeepSeek may be used selectively for safe tasks, preferably read-only, test-only, or review work.
- Sensitive data, real databases, production actions, security work, backfill or cutover, and critical decisions must not be delegated to a low-cost agent without final audit.
- Every phase must leave a report, evidence, tests or justification, risks, and a clear next step.
- `PROJECT_STATE.md` and `AGENT_HANDOFF.md` must be updated after an important phase closeout, agent or chat handoff, structural change, or relevant risk change.
