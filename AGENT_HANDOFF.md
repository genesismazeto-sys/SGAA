# Agent Handoff

Last updated: 2026-06-08
Closeout: D7.2B2-CLOSEOUT-DOCS-1
Executor: Codex

## Current State

- D7.2B2-CLOSEOUT-DOCS-1 is approved.
- D7.2B1-CLOSEOUT-DOCS-1 remains approved.
- D7.1-CLOSEOUT-DOCS-1 remains approved.
- D6.6-DISPLAY-1R remains approved.
- D6.6-DISPLAY-TEXT-ACCENTS-1R remains approved.
- D6.7-PLAN remains approved.
- Commits on `recovery/d7-activity-versioning`:
  - `73d45ac` — `Add read-only activity version catalog`.
  - `a3537cf` — `Fix activity version catalog card grids`.
  - `b91d03f` — `Add create forms for activity base and norms`.
  - `44d367a` — `Clarify activity version creation placeholder` (current `HEAD`).
- D7.2B2 delivered the controlled creation of `atividade_base` and `norma_atividade`
  in the admin catalog:
  - 2 new `GET/POST` admin routes: `/admin/catalogo-versoes/nova-base` and
    `/admin/normas-atividade/nova`;
  - 2 new templates: `templates/admin_catalogo_base_form.html` and
    `templates/admin_norma_form.html`;
  - buttons `Nova base` and `Nova norma` enabled in the existing list screens;
  - new test file: `tests/test_admin_activity_version_catalog_create.py`;
  - `64 passed` tests after the create-forms commit;
  - `47 passed` tests after the textual-placeholder fix.
- D7.2B2 runtime check:
  - backup created before real `POST`s;
  - `GET`s of the new screens returned `200`;
  - invalid `POST`s did not insert rows;
  - valid `POST`s created temporary `D7TEMP` rows that were removed surgically
    (by `id`/`codigo`/`nome`);
  - zero `D7TEMP` rows remaining;
  - `PRAGMA foreign_key_check` reported no violations;
  - hashes and counts of the relevant tables returned to baseline;
  - local database restored to the pre-phase state.
- D7.2B2 textual fix (`44d367a`):
  - in `templates/admin_catalogo_versao_detalhe.html`, the obsolete reference to
    D7.2B2 in the version-creation placeholder was removed;
  - the placeholder now uses `fase posterior`;
  - the `Criar versão` button remains disabled;
  - no route, `POST`, or version-creation functionality was added.
- Guarantees preserved by D7.2B2: no `atividade_versao` creation, no edit,
  no legacy mapping save, no change in `matriz_atividade_versao_item`,
  no change in `matrizes_atividades_itens`, no change in `aluno`,
  no change in calculation/deferment, no schema/migration change,
  no snapshot writer, no flags, no menu/sidebar entry, no backfill, no cutover.
- D7.2B1 produced the first admin read-only layer of the versioned catalog:
  read-only helpers in `main.py`; 4 admin `GET` routes; 4 new templates; new test file
  `tests/test_admin_activity_version_catalog_readonly.py`; CSS adjustments in
  `static/css/components/list-cards.css` (overrides for `.imp-catalogo`, `.imp-normas`,
  and `.imp-mapeamento`).
- D7.2B1 tests: `17 passed`; D7.1/resolver/aluno scope regressions: `17 passed`.
- D7.2B1 runtime check: `/admin/catalogo-versoes` `200`; `/admin/catalogo-versoes/1` `200`;
  `/admin/catalogo-versoes/999999` clean redirect, no `500`; `/admin/normas-atividade` `200`;
  `/admin/mapeamento-legado` `200`.
- CSS fix validated visually: no overflow on listings, final columns visible.
- D6.4.0 remains activated and validated in the target environment with snapshot write `ON` and shadow read `ON`.
- The target app ran on `127.0.0.1:5001` after port fallback.
- `app/db.py` has auto-fill in a seed/dev tool, but that does not run in normal runtime.
- `main` / `origin/main` intact at `7e5eb56`.

## Last Closed Phase

- D7.2B2-CLOSEOUT-DOCS-1 approved.
- Controlled creation of `atividade_base` and `norma_atividade` in the admin catalog.
- Commits `b91d03f` and `44d367a` on `recovery/d7-activity-versioning`.
- 2 admin `GET/POST` routes, 2 new templates, 1 new test file, textual fix in
  `admin_catalogo_versao_detalhe.html`.
- No `atividade_versao` creation, no edit, no legacy mapping save,
  no schema/migration, no flags, no menu/sidebar entry, no backfill, no cutover.
- `atividade_id` preserved as the operational source.
- Snapshot remains admin-only and read-only.
- `main` / `origin/main` intact at `7e5eb56`.

## Recommended Next Phase

- No new implementation phase is approved right now.
- D7.2B2 is closed, but D7.2B3 (creation/edition of `atividade_versao`,
  matrix selection of `atividade_versao_id`, anything that unblocks the
  `Criar versão` button) is **not** approved and **must not** start
  without a new explicit scope.
- Keep the current D6.6 state: admin-only, diagnostic, read-only.
- The new catalog screens exist but are not linked from the menu/sidebar yet.
- The `Criar versão` button remains disabled and points to a `fase posterior`.
- If work resumes later, prefer docs/runbook clarification or a fresh architectural review
  before any new code phase.

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
- D7.2B1 created read-only screens without menu/sidebar links; users must access them by direct URL only.
- D7.2B2 only created `atividade_base` and `norma_atividade`; creation/edition of
  `atividade_versao` still does not exist.
- The `Criar versão` button is still disabled and points to a `fase posterior`.
- The legacy mapping (`/admin/mapeamento-legado`) remains read-only.
- The matrix still does not choose `atividade_versao_id` through the UI.
- D7.2B3 must not start without a new explicit scope covering creation/edition of
  `atividade_versao` and any matrix UI change.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Summarize understanding before implementing anything.
- Treat `atividade_id` as the operational source of truth.
- Do not expand snapshot display beyond the current admin-only read-only surfaces unless a new approved phase explicitly authorizes it.
- D7.2B3 (creation/edition of `atividade_versao`, matrix selection of
  `atividade_versao_id`, unblocking the `Criar versão` button) must not start
  without a new approved scope.
- Do not start D7.2B3 based on this closeout alone.
