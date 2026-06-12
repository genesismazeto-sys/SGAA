# Agent Handoff

Last updated: 2026-06-12
Closeout: D7.3A normative canonization closeout
Executor: MiniMax-M3 (docs closeout)

## Current State

- D7.3A documental canonization completed (read-only, no code change).
- Current branch: `recovery/d7-activity-versioning`.
- Current `HEAD`: `5ffab77` (`Record D7.2B6 push closeout`).
- `origin/recovery/d7-activity-versioning` aligned with local at `5ffab77`.
- `main` / `origin/main` remain intact at `7e5eb56`.
- Working tree is clean.
- D7.3A analyzed three DOCX regulations stored in `_normativos_inbox/`:
  - `ACC-rev5.docx` → internal codigo AAC-rev5 (histórico/legado).
  - `ACC-rev6.docx` → internal codigo AAC-rev6 (AAC vigente).
  - `AE-rev1.docx` → internal codigo AEU-rev1 (AEU vigente).
- Canonization is accepted. No code, template, test, DB, or seed was changed.
- The DOCX files are excluded from Git via `.git/info/exclude` and must not be committed.
- D7.3B (fixture/importer) has not started.
- Existing approved committed milestones remain:
  - D7.2B6 committed/pushed at `95cb897`;
  - D7.2B5-PATCH2 committed at `9d2e9fb`;
  - D7.2B5-PATCH1 committed at `f235f62`;
  - D7.2B4-PATCH1 committed at `255ff80`;
  - D7.2B3-PATCH3 committed/pushed at `28d922d`;
  - `main` / `origin/main` preserved at `7e5eb56`.

## D7.3A — Last Closed Phase

- Scope: read-only documental diagnosis of three real normative DOCX files.
- Documents analyzed (stored in `_normativos_inbox/`, excluded from Git):
  - `ACC-rev5.docx` → AAC-rev5 (histórico/legado).
  - `ACC-rev6.docx` → AAC-rev6 (AAC vigente).
  - `AE-rev1.docx` → AEU-rev1 (AEU vigente).
- Key findings:
  - ACC-rev6 simplifies documentation vs ACC-rev5, removes simulador, relocates
    "trabalho voluntário 3º setor" to AEU.
  - AEU-rev1 requires interaction with external community, has own activities
    (organização/participação em eventos extensionistas, cursos/oficinas para comunidade).
  - Canonical fixture (YAML/JSON/CSV) recommended before any importer.
- No code, template, test, DB, or seed was changed during D7.3A.
- The DOCX files are excluded from Git and must not be committed.
- D7.3B has not started; recommended next step: plan fixture first, then dry-run importer.

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
- `95cb897` - Add admin transition history for activity versions

## Risks To Keep In View

- `created_at` is displayed raw; no formatting pass was added.
- There is still no actor/admin audit field in `atividade_transicao`.
- The catalog screens still are not linked from the menu/sidebar.
- Reativação de versão still does not exist.
- Three normative regulations were canonized (D7.3A) but no data has been imported yet.
- D7.3B (fixture/importer) must not import directly from DOCX; fixture first, dry-run second.
- Importação must not touch matrix, requests, student, calculation, or deferment.
- Ambiguous cases between "apoio institucional" (AAC) and "extensão" (AEU) require human review.

## Recommended Next Step

- D7.3A is closed (normative canonization, read-only, no code).
- D7.3B: create a reviewable canonical fixture (YAML/JSON/CSV) derived from the three DOCX.
- Only after fixture audit, create a dry-run importer consuming the fixture into an isolated DB.
- Dry-run importer must not touch matrix, requests, student, calculation, or deferment.
- Do not start any new implementation phase without explicit approved scope.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Treat `atividade_id` as the operational source of truth.
- D7.3A canonized three norms: AAC-rev5 (histórico), AAC-rev6 (vigente), AEU-rev1 (vigente).
- The canonical DOCX are stored in `_normativos_inbox/` and excluded from Git; do not commit them.
- The branch `recovery/d7-activity-versioning` is aligned locally/remotely at `5ffab77` before this docs closeout.
- D7.3B must not start importing directly from DOCX; fixture first, then dry-run.
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
