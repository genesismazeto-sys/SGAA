# Project State

Last updated: 2026-06-08
Closeout: D7.2B3-PATCH1-CLOSEOUT-DOCS-1
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

### D7.2B1 - read-only activity version catalog (admin)
- Implemented and approved.
- Commit `73d45ac` — `Add read-only activity version catalog`.
- Commit `a3537cf` — `Fix activity version catalog card grids`.
- Read-only helpers added in `main.py`.
- 4 admin `GET` routes:
  - `/admin/catalogo-versoes`
  - `/admin/catalogo-versoes/<base_id>`
  - `/admin/normas-atividade`
  - `/admin/mapeamento-legado`
- 4 new templates:
  - `admin_catalogo_versoes.html`
  - `admin_catalogo_versao_detalhe.html`
  - `admin_normas_atividade.html`
  - `admin_mapeamento_legado.html`
- New test file: `tests/test_admin_activity_version_catalog_readonly.py`.
- CSS adjustments in `static/css/components/list-cards.css` with overrides for `.imp-catalogo`, `.imp-normas`, and `.imp-mapeamento`.
- Tests: D7.2B1 specific `17 passed`; D7.1/resolver/aluno scope regressions `17 passed`.
- Runtime check: `/admin/catalogo-versoes` `200`; `/admin/catalogo-versoes/1` `200`; `/admin/catalogo-versoes/999999` clean redirect, no `500`; `/admin/normas-atividade` `200`; `/admin/mapeamento-legado` `200`.
- CSS fix validated visually: no overflow on listings, final columns visible.
- Guarantees preserved: no new `POST`, no DB writes through the new routes, no auto-mapping, no student change, no operational matrix change, no calculation/deferment change, no schema/migration, no snapshot writer, no flags, no menu/sidebar entry, no backfill, no cutover.
- `main` / `origin/main` intact at `7e5eb56`.

### D7.2B2 - controlled creation of activity base and norms (admin)
- Implemented and approved.
- Commit `b91d03f` — `Add create forms for activity base and norms`.
- Commit `44d367a` — `Clarify activity version creation placeholder`.
- 2 new admin `GET/POST` routes:
  - `/admin/catalogo-versoes/nova-base`
  - `/admin/normas-atividade/nova`
- 2 new templates:
  - `templates/admin_catalogo_base_form.html`
  - `templates/admin_norma_form.html`
- Buttons `Nova base` and `Nova norma` enabled in the existing list screens
  (`templates/admin_catalogo_versoes.html` and `templates/admin_normas_atividade.html`).
- New test file: `tests/test_admin_activity_version_catalog_create.py`.
- Validations for `atividade_base`:
  - `nome_conceito` required;
  - whitespace trim;
  - empty name rejected;
  - `status` restricted to `ativo`/`inativo`;
  - duplicate rejected by case-insensitive pre-check;
  - success redirects to the detail of the created base.
- Validations for `norma_atividade`:
  - `codigo` required;
  - `codigo` trimmed;
  - `eixo` restricted to `AAC`/`AEU`;
  - `revisao` required;
  - `status` restricted to `ativa`/`inativa`;
  - duplicate rejected by case-insensitive pre-check;
  - success redirects to `/admin/normas-atividade`.
- Runtime check:
  - backup created before real `POST`s;
  - `GET`s of the new screens returned `200`;
  - invalid `POST`s did not insert rows;
  - valid `POST`s created temporary `D7TEMP` rows;
  - `D7TEMP` rows removed surgically by `id`/`codigo`/`nome`;
  - zero `D7TEMP` rows remaining;
  - `PRAGMA foreign_key_check` reported no violations;
  - hashes and counts of relevant tables returned to baseline;
  - local database restored to the pre-phase state;
  - `64 passed` tests.
- Textual fix in `44d367a`:
  - in `templates/admin_catalogo_versao_detalhe.html`, removed the obsolete
    reference to D7.2B2 in the version-creation placeholder;
  - placeholder now uses `fase posterior`;
  - `Criar versão` button remains disabled;
  - no new route, `POST`, or version-creation functionality was introduced;
  - `47 passed` tests.
- Guarantees preserved:
  - no `atividade_versao` creation;
  - no edit;
  - no legacy mapping save;
  - no change in `matriz_atividade_versao_item`;
  - no change in `matrizes_atividades_itens`;
  - no change in `aluno`;
  - no change in calculation/deferment;
  - no schema/migration change;
  - no snapshot writer;
  - no flags;
  - no menu/sidebar entry;
  - no backfill;
  - no cutover.
- `main` / `origin/main` intact at `7e5eb56`.

### D7.2B3-PATCH1 - draft activity version creation
- Implemented and approved.
- Commit `16b1480` — `Add draft activity version creation`.
- Commit `ccf1a7e` — `Record D7.2B3 draft version creation` (current `HEAD`).
- 1 new admin `GET/POST` route:
  - `/admin/catalogo-versoes/<int:base_id>/nova-versao`
- 1 new template: `templates/admin_catalogo_versao_form.html`.
- 1 updated template: `templates/admin_catalogo_versao_detalhe.html` (button enabled).
- 1 new test file: `tests/test_admin_activity_version_catalog_version_form.py` (17 tests).
- Helpers added in `main.py`:
  - `get_norma_by_id(conn, norma_id)` — read-only lookup.
  - `get_versoes_da_base_por_eixo(conn, base_id, eixo)` — read-only lookup now
    actively used to populate the optional `versao_anterior_id` select.
- Functional guarantees:
  - rota GET/POST `/admin/catalogo-versoes/<base_id>/nova-versao`;
  - helper `get_norma_by_id`;
  - helper `get_versoes_da_base_por_eixo` agora usado no formulário;
  - criação de `atividade_versao` com status forçado em rascunho;
  - `codigo_normativo` derivado de `norma_atividade.codigo`;
  - `eixo` derivado de `norma_atividade.eixo`;
  - `norma_id` obrigatório, sem primeira norma automática;
  - select de norma com placeholder obrigatório;
  - `versao_anterior_id` como select opcional com placeholder "Sem versão anterior";
  - validação server-side de base, norma ativa, duplicidade base+norma,
    números inválidos/negativos, versão anterior inexistente, de outra base
    ou de eixo incompatível;
  - botão "Criar versão" habilitado no detalhe da atividade-base;
  - novo template `templates/admin_catalogo_versao_form.html`;
  - novo teste `tests/test_admin_activity_version_catalog_version_form.py`
    com 17 testes;
  - suíte parcial validada com 91 passed.
- Garantias explícitas de fora do escopo do PATCH1:
  - edição de versão;
  - ativação/publicação;
  - vínculo com matriz;
  - UI de matriz;
  - fluxo do aluno;
  - cálculo/deferimento;
  - snapshot writer;
  - schema/migration;
  - backfill/cutover;
  - importação de regulamentos reais;
  - menu/sidebar;
  - mapeamento legado salvo.
- `main` / `origin/main` intact at `7e5eb56`.
- Branch `recovery/d7-activity-versioning` pushed to origin at `ccf1a7e`.

## Relevant Commits

- `483f069` - Add controlled versioned snapshot write for requests
- `ba5a3df` - Document snapshot write activation runbook
- `8845dce` - Record controlled snapshot activation validation
- `18c169a` - Record target snapshot activation validation
- `bb1ca51` - Add admin snapshot diagnostics
- `b9ffda2` - Add admin snapshot comparison display
- `09749ef` - Fix snapshot comparison labels
- `e0427ee` - Add activity version matrix contract tests
- `73d45ac` - Add read-only activity version catalog
- `a3537cf` - Fix activity version catalog card grids
- `b91d03f` - Add create forms for activity base and norms
- `44d367a` - Clarify activity version creation placeholder
- `16b1480` - Add draft activity version creation
- `ccf1a7e` - Record D7.2B3 draft version creation

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
- D7.2B1 created the read-only admin catalog, but the new screens are not linked from the menu/sidebar yet.
- D7.2B2 only delivered controlled creation of `atividade_base` and `norma_atividade`.
- D7.2B3-PATCH1 delivered controlled creation of `atividade_versao` in rascunho
  (commit `16b1480`). Edition of `atividade_versao` still does not exist.
- The `Criar versão` button is now enabled in the detail of each `atividade_base`
  and points to the new draft creation form.
- All `atividade_versao` created by PATCH1 are inserted with `status = 'rascunho'`
  and are not yet usable by any matrix.
- The legacy mapping (`mapeamento-legado`) remains read-only.
- The matrix still does not choose `atividade_versao_id` through the UI.
- D7.2B3-PATCH2 (edition of rascunho versions) is not approved; it requires a
  new explicit scope and must not start without authorization.

## Permanent Working Directives

- ChatGPT acts as technical supervisor, auditor, and orchestrator.
- Codex or GitCP is the main executor for real code changes.
- MiniMax may be used for low-cost volume work, logs, tests, repetitive tasks, and simple low-risk patches.
- Kimi may be used for strong second opinions, architecture work, or difficult multi-file problems.
- GLM, Qwen, MiMo, and DeepSeek may be used selectively for safe tasks, preferably read-only, test-only, or review work.
- Sensitive data, real databases, production actions, security work, backfill or cutover, and critical decisions must not be delegated to a low-cost agent without final audit.
- Every phase must leave a report, evidence, tests or justification, risks, and a clear next step.
- `PROJECT_STATE.md` and `AGENT_HANDOFF.md` must be updated after an important phase closeout, agent or chat handoff, structural change, or relevant risk change.
