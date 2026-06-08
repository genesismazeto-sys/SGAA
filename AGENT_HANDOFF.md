# Agent Handoff

Last updated: 2026-06-08
Closeout: D7.2B3-PATCH2-DOCS-CLOSEOUT
Executor: MiniMax-M3

## Current State

- D7.2B3-PATCH2-DOCS-CLOSEOUT is in progress.
- D7.2B3-PATCH2 functional code committed at `c90ffe3`
  on `recovery/d7-activity-versioning` (not yet pushed to origin).
- D7.2B3-PATCH1-CLOSEOUT-DOCS-1 remains approved.
- D7.2B3-PATCH1 functional code pushed at `ccf1a7e`.
- D7.2B2-CLOSEOUT-DOCS-1 remains approved.
- D7.2B1-CLOSEOUT-DOCS-1 remains approved.
- D7.1-CLOSEOUT-DOCS-1 remains approved.
- D6.6-DISPLAY-1R remains approved.
- D6.6-DISPLAY-TEXT-ACCENTS-1R remains approved.
- D6.7-PLAN remains approved.
- Commits on `recovery/d7-activity-versioning`:
  - `73d45ac` — `Add read-only activity version catalog`.
  - `a3537cf` — `Fix activity version catalog card grids`.
  - `b91d03f` — `Add create forms for activity base and norms`.
  - `44d367a` — `Clarify activity version creation placeholder`.
  - `16b1480` — `Add draft activity version creation`.
  - `ccf1a7e` — `Record D7.2B3 draft version creation`.
  - `c90ffe3` — `Add draft activity version editing` (current `HEAD`).
- D7.2B3-PATCH2 delivered controlled editing of `atividade_versao` in rascunho:
  - 1 new admin `GET/POST` route: `/admin/catalogo-versoes/<base_id>/versoes/<versao_id>/editar`;
  - 2 new helpers in `main.py`: `get_atividade_versao_by_id`, `get_atividade_versao_usage_counts`;
  - template `admin_catalogo_versao_form.html` parametrized (form_action, form_title, submit_label);
  - template `admin_catalogo_versao_detalhe.html` ganhou coluna "Ações" com link "Editar" só para rascunho;
  - novo teste: `test_admin_activity_version_catalog_version_edit.py` com 28 testes;
  - 119 passed na suíte parcial.
- D7.2B2 previously delivered controlled creation of `atividade_base` and `norma_atividade`.
- D7.2B1 produced the first admin read-only layer of the versioned catalog.
- D6.4.0 remains activated and validated in the target environment.
- `main` / `origin/main` intact at `7e5eb56`.

## Last Closed Phase

- D7.2B3-PATCH2-DOCS-CLOSEOUT in progress (functional code committed, docs pending).
- Controlled editing of `atividade_versao` in rascunho in the admin catalog.
- Commit `c90ffe3` on `recovery/d7-activity-versioning` (not yet pushed).
- 1 new admin `GET/POST` route (`/admin/catalogo-versoes/<base_id>/versoes/<versao_id>/editar`),
  2 new helpers in `main.py` (`get_atividade_versao_by_id`, `get_atividade_versao_usage_counts`),
  1 parametrized template (`admin_catalogo_versao_form.html`),
  1 updated template (`admin_catalogo_versao_detalhe.html`, coluna "Ações"),
  1 new test file (`test_admin_activity_version_catalog_version_edit.py`, 28 tests).
- Edição permitida apenas para `status = 'rascunho'`.
- Bloqueio total se houver uso em `matriz_atividade_versao_item`,
  `requisicoes`, ou `atividade_transicao`.
- 28 new tests pass; 119 total tests pass in the targeted suite.
- No activation/publication, no matrix link, no student flow change,
  no calculation/deferment change, no snapshot writer change,
  no schema/migration, no flags, no menu/sidebar entry,
  no backfill, no cutover.
- `atividade_id` preserved as the operational source.
- `main` / `origin/main` intact at `7e5eb56`.
- Branch `recovery/d7-activity-versioning` local at `c90ffe3`; not yet pushed.

## Recommended Next Phase

- No new implementation phase is approved right now.
- D7.2B3-PATCH2 is closed (draft version editing in rascunho).
- D7.2B3-PATCH1 remains approved (draft version creation).
- Próxima fase provável ainda não aprovada:
  - ativação/publicação de versão; ou
  - vínculo matriz→atividade_versao.
  - Nenhuma deve iniciar sem planejamento read-only separado.
- Keep the current D6.6 state: admin-only, diagnostic, read-only.
- The new catalog screens exist but are not linked from the menu/sidebar yet.
- Immediate next step: commit documental (this closeout) and, if approved,
  push the branch.
- Any matrix selection of `atividade_versao_id` or activation/publication
  must not start without a new approved scope.
- If work resumes later, prefer docs/runbook clarification or a fresh
  architectural review before any new code phase.

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
- D7.2B2 only created `atividade_base` and `norma_atividade`.
- D7.2B3-PATCH1 created `atividade_versao` in rascunho.
- D7.2B3-PATCH2 added editing of `atividade_versao` in rascunho.
  Versões com `status != 'rascunho'` ou com uso registrado em
  matriz/requisição/transição estão protegidas contra edição.
- The `Criar versão` button is enabled and points to the draft creation form.
- All `atividade_versao` are inserted with `status = 'rascunho'`
  and are not yet usable by any matrix.
- The legacy mapping (`/admin/mapeamento-legado`) remains read-only.
- The matrix still does not choose `atividade_versao_id` through the UI.
- Ativação/publicação de versão ainda não existe.
- Vínculo matriz→versão ainda não existe.
- PATCH3 ou fase seguinte não deve começar sem escopo explícito.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Summarize understanding before implementing anything.
- Treat `atividade_id` as the operational source of truth.
- Do not expand snapshot display beyond the current admin-only read-only surfaces unless a new approved phase explicitly authorizes it.
- Ativação/publicação de versão e vínculo matriz→atividade_versao
  não devem começar sem um planejamento read-only separado e escopo aprovado.
- The branch `recovery/d7-activity-versioning` is local at `c90ffe3`
  (not yet pushed). Do not push without authorization.
- Escopo proibido contínuo: main, matriz operacional, aluno, cálculo,
  deferimento, snapshot writer, schema/migration, backfill/cutover.
