# Agent Handoff

Last updated: 2026-06-09
Closeout: D7.2B5-PATCH1
Executor: Claude Sonnet 4.6 (functional + docs)

## Current State

- D7.2B5-PATCH1 completed.
- D7.2B5-PATCH1 functional code committed at `f235f62` (local only; not yet pushed to origin).
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
- Commits on `recovery/d7-activity-versioning` (local ahead of remote by 2):
  - `73d45ac` — `Add read-only activity version catalog`.
  - `a3537cf` — `Fix activity version catalog card grids`.
  - `b91d03f` — `Add create forms for activity base and norms`.
  - `44d367a` — `Clarify activity version creation placeholder`.
  - `16b1480` — `Add draft activity version creation`.
  - `ccf1a7e` — `Record D7.2B3 draft version creation`.
  - `c90ffe3` — `Add draft activity version editing`.
  - `28d922d` (origin/recovery/d7-activity-versioning) — `Add draft activity version activation`.
  - `255ff80` — `Add admin UI for explicit matrix→atividade_versao links (D7.2B4)`.
  - `f235f62` (HEAD -> recovery/d7-activity-versioning) — `Add admin lifecycle transitions for atividade_versao (D7.2B5)`.
- D7.2B5-PATCH1 delivered inativação and descontinuação of ativa versões:
  - 2 new admin POST routes: `admin_catalogo_inativar_versao`, `admin_catalogo_descontinuar_versao`;
  - hard B1 block if any `matriz_atividade_versao_item` link exists (no silent DELETE);
  - updated template `templates/admin_catalogo_versao_detalhe.html` (Inativar / Descontinuar buttons for ativa versões);
  - 1 new test file: `tests/test_admin_activity_version_catalog_version_lifecycle.py` (19 tests);
  - CSRF inventory unchanged (existing `versao_lnk_id` ativa provides form evidence);
  - **400 passed** na suíte completa (up from 381).
- D7.2B4-PATCH1 delivered admin UI for explicit matriz→atividade_versao links:
  - 5 new helpers, 3 new admin routes, 1 new template, 1 updated template, 14 tests; 381 passed.
- D7.2B3-PATCH3 delivered controlled activation of `atividade_versao` in rascunho; 367 passed.
- D7.2B3-PATCH2 delivered controlled editing of `atividade_versao` in rascunho.
- D7.2B2 previously delivered controlled creation of `atividade_base` and `norma_atividade`.
- D7.2B1 produced the first admin read-only layer of the versioned catalog.
- D6.4.0 remains activated and validated in the target environment.
- `main` / `origin/main` intact at `7e5eb56`.

## Last Closed Phase

- D7.2B5-PATCH1 completed (functional code committed locally).
- Admin lifecycle transitions: ativa → inativa; ativa → descontinuada.
- Commit `f235f62` on `recovery/d7-activity-versioning` (local only; not yet pushed to origin).
- 2 new POST routes + template update + 19 new tests.
- Hard B1 block: inativar/descontinuar rejeitadas se há vínculo em `matriz_atividade_versao_item`.
  Error message orientates admin to remove the link first; no automatic deletion.
- 19 new tests pass; 400 total tests pass in the full suite.
- Resolver untouched. No `atividade_transicao`. No substituta. No silent fallback.
- No student flow, no calculation/deferment, no schema/migration, no snapshot writer, no backfill, no cutover.
- `main` / `origin/main` intact at `7e5eb56`.
- Branch `recovery/d7-activity-versioning` local at `f235f62`, remote at `28d922d`.

## Recommended Next Phase

- No new implementation phase is approved right now.
- D7.2B5-PATCH1 is closed (inativação + descontinuação de versão ativa).
- Próximas fases prováveis ainda não aprovadas:
  - substituição de versão (`substituida`), com ou sem `atividade_transicao`; ou
  - auditoria de ações de ciclo de vida (quem inativou/descontinuou, quando); ou
  - importação/cadastro real de regulamentos.
  - Nenhuma deve iniciar sem planejamento read-only separado e escopo aprovado.
- Keep the current D6.6 state: admin-only, diagnostic, read-only.
- The new catalog screens exist but are not linked from the menu/sidebar yet.
- Immediate next step: if approved, push the pending commits (D7.2B4 + D7.2B5).
- Any version lifecycle expansion beyond inativa/descontinuada must not start without a new approved scope.
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
- D7.2B5-PATCH1 added inativação (ativa→inativa) and descontinuação (ativa→descontinuada).
  - Bloqueio B1: a operação rejeita se houver qualquer vínculo em `matriz_atividade_versao_item`.
  - Sem DELETE automático de vínculo. Sem `atividade_transicao`. Sem substituta. Sem fallback.
- Substituição de versão (`substituida`) ainda não existe.
- Reativação de versão (inativa/descontinuada → ativa) ainda não existe.
- Não há auditoria de quem ativou/inativou/descontinuou/definiu/removeu vínculo.
- Fase seguinte não deve começar sem escopo explícito.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Summarize understanding before implementing anything.
- Treat `atividade_id` as the operational source of truth.
- Do not expand snapshot display beyond the current admin-only read-only surfaces unless a new approved phase explicitly authorizes it.
- D7.2B5-PATCH1 is closed. Substituição, reativação, `atividade_transicao`, e qualquer
  outra extensão de ciclo de vida não devem começar sem escopo explícito aprovado.
- The branch `recovery/d7-activity-versioning` is local at `f235f62`, remote at `28d922d`.
  Push of commits `255ff80` and `f235f62` requires authorization.
- Escopo proibido contínuo: main, matriz operacional, aluno, cálculo,
  deferimento, snapshot writer, schema/migration, backfill/cutover,
  primeira ativa, inferência de versão por nome/eixo/data, fallback silencioso,
  resolver_versao_por_matriz / resolver_versao_por_aluno / resolver_versao /
  maybe_write_versioned_requisicao_snapshot.
