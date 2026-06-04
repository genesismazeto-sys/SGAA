# Project State

Last updated: 2026-06-04
Closeout: D6.6-DISPLAY-RUNTIME-CLOSEOUT-1
Executor: MiniMax

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

## Relevant Commits

- `483f069` - Add controlled versioned snapshot write for requests
- `ba5a3df` - Document snapshot write activation runbook
- `8845dce` - Record controlled snapshot activation validation
- `18c169a` - Record target snapshot activation validation
- `bb1ca51` - Add admin snapshot diagnostics
- `b9ffda2` - Add admin snapshot comparison display
- `09749ef` - Fix snapshot comparison labels

## Current Risks And Limits

- D6.6 remains admin-only display work, not an operational read path based on snapshot data.
- Snapshot data must not be used to approve or reject requests.
- Snapshot data must not be used to calculate hours or limits.
- Snapshot data must not be used for matrix scope, dashboards, import flow, or student screens.
- Import flow remains out of scope.
- Student dashboards and progress remain on the legacy path.
- Backfill for old requests has not been performed yet.
- Any next D6.7 work should start only after controlled runtime validation of D6.6 display behavior.

## Permanent Working Directives

- ChatGPT acts as technical supervisor, auditor, and orchestrator.
- Codex or GitCP is the main executor for real code changes.
- MiniMax may be used for low-cost volume work, logs, tests, repetitive tasks, and simple low-risk patches.
- Kimi may be used for strong second opinions, architecture work, or difficult multi-file problems.
- GLM, Qwen, MiMo, and DeepSeek may be used selectively for safe tasks, preferably read-only, test-only, or review work.
- Sensitive data, real databases, production actions, security work, backfill or cutover, and critical decisions must not be delegated to a low-cost agent without final audit.
- Every phase must leave a report, evidence, tests or justification, risks, and a clear next step.
- `PROJECT_STATE.md` and `AGENT_HANDOFF.md` must be updated after an important phase closeout, agent or chat handoff, structural change, or relevant risk change.
