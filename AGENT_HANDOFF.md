# Agent Handoff

Last updated: 2026-06-11
Closeout: D7.2B6 docs-only pending commit
Executor: Codex GPT-5 (docs closeout)

## Current State

- D7.2B6 functional implementation completed and approved, but **not committed yet**.
- Current branch: `recovery/d7-activity-versioning`.
- Current `HEAD`: `5f7dbc8` (`Record D7.2B5-PATCH2 substitution closeout`).
- `origin/recovery/d7-activity-versioning` is aligned with local at `5f7dbc8`.
- `main` / `origin/main` remain intact at `7e5eb56`.
- Working tree currently contains pending D7.2B6 functional changes in:
  - `main.py`
  - `templates/admin_catalogo_versao_detalhe.html`
  - `tests/test_admin_activity_version_catalog_readonly.py`
- Existing approved committed milestones remain:
  - D7.2B5-PATCH2 committed at `9d2e9fb`;
  - D7.2B5-PATCH1 committed at `f235f62`;
  - D7.2B4-PATCH1 committed at `255ff80`;
  - D7.2B3-PATCH3 committed/pushed at `28d922d`;
  - `main` / `origin/main` preserved at `7e5eb56`.

## D7.2B6 Summary

- Scope delivered:
  - read-only helper `get_atividade_transicoes_por_base`;
  - `JOIN` between `atividade_transicao` and source/destination versions;
  - filter by `atividade_base` through source or destination;
  - payload with `versao_origem`, `versao_destino`, `tipo_transicao`, `eixo`, `created_at`, and `motivo`;
  - `motivo = justificativa or observacao_admin or '-'`;
  - existing `GET /admin/catalogo-versoes/<base_id>` now passes `transicoes_historico`;
  - `templates/admin_catalogo_versao_detalhe.html` renders a read-only `Histórico de transições` section with table and empty state.
- Scope explicitly unchanged:
  - no new `POST`;
  - no CSRF change;
  - no schema or trigger change;
  - no student flow change;
  - no calculation or deferment change;
  - no writer/versioned snapshot change;
  - no matrix behavior change;
  - no change to activation/inactivation/discontinuation/substitution logic.

## Validation Already Executed

- `python -m pytest tests/test_admin_activity_version_catalog_readonly.py -q --tb=short`
  - Result: `21 passed in 10.03s`.
- `python -m pytest tests/test_admin_activity_version_catalog_version_lifecycle.py -q --tb=short`
  - Result: `34 passed in 102.08s`.
- Visual gate already executed:
  - temporary headless render of the template;
  - empty-history scenario displayed `Nenhuma transição registrada para esta atividade-base.`;
  - populated-history scenario displayed origin, destination, `tipo_transicao`, fallback `'-'`, and `created_at`;
  - existing `Ativar`, `Inativar`, `Descontinuar`, and `Substituir` actions remained visible without obvious layout breakage.

## Recent Commits

- `73d45ac` - Add read-only activity version catalog
- `a3537cf` - Fix activity version catalog card grids
- `b91d03f` - Add create forms for activity base and norms
- `44d367a` - Clarify activity version creation placeholder
- `16b1480` - Add draft activity version creation
- `ccf1a7e` - Record D7.2B3 draft version creation
- `c90ffe3` - Add draft activity version editing
- `28d922d` - Add draft activity version activation
- `255ff80` - Add admin UI for explicit matrix→atividade_versao links (D7.2B4)
- `f235f62` - Add admin lifecycle transitions for atividade_versao (D7.2B5)
- `9d2e9fb` - Add explicit activity version substitution
- `5f7dbc8` - Record D7.2B5-PATCH2 substitution closeout

## Risks To Keep In View

- D7.2B6 is still only in the working tree; there is no commit yet for this phase.
- `created_at` is displayed raw; no formatting pass was added in this phase.
- There is still no actor/admin audit field in `atividade_transicao`.
- The read-only history UI is generic and may later show transition types beyond `mesmo_eixo`.
- The catalog screens still are not linked from the menu/sidebar.
- Reativação de versão still does not exist.
- No new phase should begin before the D7.2B6 selective commit decision is made.

## Recommended Next Step

- If authorized, perform a selective commit for D7.2B6 only.
- Do **not** use `git add .`; stage only:
  - `main.py`
  - `templates/admin_catalogo_versao_detalhe.html`
  - `tests/test_admin_activity_version_catalog_readonly.py`
  - optionally `PROJECT_STATE.md` and `AGENT_HANDOFF.md` if the docs closeout should be committed together.
- Do not push without explicit authorization.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Treat `atividade_id` as the operational source of truth.
- D7.2B6 is functionally approved but not committed.
- The branch `recovery/d7-activity-versioning` is aligned locally/remotely at `5f7dbc8`, with D7.2B6 changes pending in the working tree.
- Next action should be a selective commit of D7.2B6 only after authorization.
- Continuous prohibited scope remains:
  - `main` branch;
  - matriz operacional;
  - aluno;
  - cálculo;
  - deferimento;
  - snapshot writer;
  - schema/migration;
  - backfill/cutover;
  - fallback silencioso;
  - resolver_versao_por_matriz / resolver_versao_por_aluno / resolver_versao / maybe_write_versioned_requisicao_snapshot.
