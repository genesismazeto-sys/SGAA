# Agent Handoff

Last updated: 2026-06-09
Closeout: D7.2B4-PATCH1
Executor: Claude Sonnet 4.6 (functional + docs)

## Current State

- D7.2B4-PATCH1 completed.
- D7.2B4-PATCH1 functional code committed at `255ff80` (local only; not yet pushed to origin).
- D7.2B3-PATCH3-DOCS-CLOSEOUT remains approved.
- D7.2B3-PATCH3 functional code committed at `28d922d` and pushed to
  `origin/recovery/d7-activity-versioning`.
- D7.2B3-PATCH2-DOCS-CLOSEOUT remains approved.
- D7.2B3-PATCH2 functional code pushed at `c90ffe3`.
- D7.2B3-PATCH1-CLOSEOUT-DOCS-1 remains approved.
- D7.2B3-PATCH1 functional code pushed at `ccf1a7e`.
- D7.2B2-CLOSEOUT-DOCS-1 remains approved.
- D7.2B1-CLOSEOUT-DOCS-1 remains approved.
- D7.1-CLOSEOUT-DOCS-1 remains approved.
- D6.6-DISPLAY-1R remains approved.
- D6.6-DISPLAY-TEXT-ACCENTS-1R remains approved.
- D6.7-PLAN remains approved.
- Commits on `recovery/d7-activity-versioning` (local ahead of remote by 1):
  - `73d45ac` — `Add read-only activity version catalog`.
  - `a3537cf` — `Fix activity version catalog card grids`.
  - `b91d03f` — `Add create forms for activity base and norms`.
  - `44d367a` — `Clarify activity version creation placeholder`.
  - `16b1480` — `Add draft activity version creation`.
  - `ccf1a7e` — `Record D7.2B3 draft version creation`.
  - `c90ffe3` — `Add draft activity version editing`.
  - `28d922d` (origin/recovery/d7-activity-versioning) — `Add draft activity version activation`.
  - `255ff80` (HEAD -> recovery/d7-activity-versioning) — `Add admin UI for explicit matrix→atividade_versao links (D7.2B4)`.
- D7.2B4-PATCH1 delivered admin UI for explicit matriz→atividade_versao links:
  - 5 new helpers: `get_bases_escopo_matriz`, `get_versoes_ativas_por_base_na_matriz`, `get_vinculo_versao_da_matriz`, `_set_versao_da_matriz_para_base`, `_remover_versao_da_matriz_para_base`;
  - 3 new admin routes: GET `admin_matriz_versoes`, POST `admin_matriz_versoes_definir`, POST `admin_matriz_versoes_remover`;
  - 1 new template: `templates/admin_matriz_versoes.html`;
  - 1 updated template: `templates/admin_matriz_form.html` ("Versões" tab added);
  - 1 new test file: `tests/test_admin_matriz_versao_link.py` (14 tests);
  - updated `tests/test_csrf_inventory_audit.py` (seed/evidência real para as 2 novas rotas POST);
  - **381 passed** na suíte completa (up from 367).
- D7.2B3-PATCH3 delivered controlled activation of `atividade_versao` in rascunho:
  - 1 new admin POST route: `/admin/catalogo-versoes/<base_id>/versoes/<versao_id>/ativar`;
  - no new helpers (reuses `get_atividade_base`, `get_atividade_versao_by_id`, `get_norma_by_id`);
  - template `admin_catalogo_versao_detalhe.html` ganhou form "Ativar" com csrf_token ao lado do link "Editar";
  - alteração em `test_csrf_inventory_audit.py` (seed/evidência real, sem whitelist);
  - novo teste: `test_admin_activity_version_catalog_version_activate.py` com 17 testes;
  - 367 passed na suíte completa.
- D7.2B3-PATCH2 delivered controlled editing of `atividade_versao` in rascunho.
- D7.2B2 previously delivered controlled creation of `atividade_base` and `norma_atividade`.
- D7.2B1 produced the first admin read-only layer of the versioned catalog.
- D6.4.0 remains activated and validated in the target environment.
- `main` / `origin/main` intact at `7e5eb56`.

## Last Closed Phase

- D7.2B4-PATCH1 completed (functional code committed locally).
- Admin UI for explicit matrix→atividade_versao links.
- Commit `255ff80` on `recovery/d7-activity-versioning` (local only; not yet pushed to origin).
- 5 new helpers + 3 new admin routes + 1 new template + 1 updated template + 1 new test file (14 tests) + 1 updated CSRF test.
- "set" operation enforces max-1 per matriz+base via DELETE+INSERT in `matriz_atividade_versao_item`.
- 14 new tests pass; 381 total tests pass in the full suite.
- Resolver untouched. No silent fallback. No first-active. Ambiguity remains a hard error.
- No student flow, no calculation/deferment, no schema/migration, no snapshot writer, no backfill, no cutover.
- `main` / `origin/main` intact at `7e5eb56`.
- Branch `recovery/d7-activity-versioning` local at `255ff80`, remote at `28d922d`.

## Recommended Next Phase

- No new implementation phase is approved right now.
- D7.2B4-PATCH1 is closed (admin UI for explicit matrix→versao links).
- Próxima fase provável ainda não aprovada:
  - inativação/descontinuação/substituição de versão; ou
  - importação/cadastro real de regulamentos; ou
  - auditoria de ações de vínculo (quem definiu/removeu, quando).
  - Nenhuma deve iniciar sem planejamento read-only separado e escopo aprovado.
- Keep the current D6.6 state: admin-only, diagnostic, read-only.
- The new catalog screens exist but are not linked from the menu/sidebar yet.
- Immediate next step: if approved, push the docs commit.
- Any matrix selection of `atividade_versao_id` or version lifecycle expansion
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
- D7.2B1 created read-only screens without menu/sidebar links; users must access them by direct URL only.
- D7.2B2 only created `atividade_base` and `norma_atividade`.
- D7.2B3-PATCH1 created `atividade_versao` in rascunho.
- D7.2B3-PATCH2 added editing of `atividade_versao` in rascunho.
- D7.2B3-PATCH3 added activation of `atividade_versao` rascunho→ativa.
- D7.2B4-PATCH1 added the admin UI to set/remove explicit matriz→versão links.
  - Max 1 link per matriz+base enforced by "set" operation (DELETE old + INSERT new).
  - Resolver still requires an explicit link; no first-active fallback.
- Inativação/descontinuação/substituição de versão ainda não existem.
- Não há auditoria de quem definiu/removeu vínculo.
- Fase seguinte não deve começar sem escopo explícito.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Summarize understanding before implementing anything.
- Treat `atividade_id` as the operational source of truth.
- Do not expand snapshot display beyond the current admin-only read-only surfaces unless a new approved phase explicitly authorizes it.
- D7.2B4-PATCH1 is closed. Inativação/descontinuação/substituição de versão
  e qualquer outra extensão não devem começar sem escopo explícito aprovado.
- The branch `recovery/d7-activity-versioning` is local at `255ff80`, remote at `28d922d`.
  Push of the D7.2B4-PATCH1 commit (`255ff80`) requires authorization.
- Escopo proibido contínuo: main, matriz operacional, aluno, cálculo,
  deferimento, snapshot writer, schema/migration, backfill/cutover,
  primeira ativa, inferência de versão por nome/eixo/data, fallback silencioso,
  resolver_versao_por_matriz / resolver_versao_por_aluno / resolver_versao /
  maybe_write_versioned_requisicao_snapshot.
