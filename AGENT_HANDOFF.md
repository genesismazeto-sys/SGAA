# Agent Handoff

Last updated: 2026-06-04
Closeout: D7.2B1-CLOSEOUT-DOCS-1
Executor: Codex

## Current State

- D7.2B1-CLOSEOUT-DOCS-1 is approved.
- D7.1-CLOSEOUT-DOCS-1 remains approved.
- D6.6-DISPLAY-1R remains approved.
- D6.6-DISPLAY-TEXT-ACCENTS-1R remains approved.
- D6.7-PLAN remains approved.
- Commits on `recovery/d7-activity-versioning`:
  - `73d45ac` — `Add read-only activity version catalog`.
  - `a3537cf` — `Fix activity version catalog card grids` (current `HEAD`).
- D7.2B1 produced the first admin read-only layer of the versioned catalog:
  read-only helpers in `main.py`; 4 admin `GET` routes; 4 new templates; new test file
  `tests/test_admin_activity_version_catalog_readonly.py`; CSS adjustments in
  `static/css/components/list-cards.css` (overrides for `.imp-catalogo`, `.imp-normas`,
  and `.imp-mapeamento`).
- D7.2B1 tests: `17 passed`; D7.1/resolver/aluno scope regressions: `17 passed`.
- Runtime check: `/admin/catalogo-versoes` `200`; `/admin/catalogo-versoes/1` `200`;
  `/admin/catalogo-versoes/999999` clean redirect, no `500`; `/admin/normas-atividade` `200`;
  `/admin/mapeamento-legado` `200`.
- CSS fix validated visually: no overflow on listings, final columns visible.
- Guarantees preserved: no new `POST`, no DB writes through the new routes,
  no auto-mapping, no student change, no operational matrix change,
  no calculation/deferment change, no schema/migration, no snapshot writer,
  no flags, no menu/sidebar entry, no backfill, no cutover.
- D6.4.0 remains activated and validated in the target environment with snapshot write `ON` and shadow read `ON`.
- The target app ran on `127.0.0.1:5001` after port fallback.
- `app/db.py` has auto-fill in a seed/dev tool, but that does not run in normal runtime.
- `main` / `origin/main` intact at `7e5eb56`.

## Last Closed Phase

- D7.2B1-CLOSEOUT-DOCS-1 approved.
- First read-only admin layer of the versioned activity catalog.
- Commits `73d45ac` and `a3537cf` on `recovery/d7-activity-versioning`.
- 4 admin `GET` routes, 4 templates, 1 new test file, CSS fixes in `list-cards.css`.
- No `POST`, no DB writes via the new routes, no schema/migration, no flags.
- `atividade_id` preserved as the operational source.
- Snapshot remains admin-only and read-only.
- `main` / `origin/main` intact at `7e5eb56`.

## Recommended Next Phase

- No new implementation phase is approved right now.
- D7.2B1 is closed, but D7.2B2 (controlled creation of `atividade_base` and `norma_atividade`)
  is **not** approved and **must not** start without a new explicit scope.
- Keep the current D6.6 state: admin-only, diagnostic, read-only.
- The new catalog screens exist but are not linked from the menu/sidebar yet.
- The `Nova base`, `Nova norma`, and `Criar versão` buttons are disabled until D7.2B2.
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
- D7.2B2 must not start without a new explicit scope covering controlled creation of
  `atividade_base` and `norma_atividade`.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Summarize understanding before implementing anything.
- Treat `atividade_id` as the operational source of truth.
- Do not expand snapshot display beyond the current admin-only read-only surfaces unless a new approved phase explicitly authorizes it.
- D7.2B2 (controlled creation of `atividade_base` and `norma_atividade`) must not start without a new approved scope.
- Do not start D7.2B2 based on this closeout alone.
