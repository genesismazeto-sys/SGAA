# Agent Handoff

Last updated: 2026-06-12
Closeout: D7.3C canonical fixture creation closeout
Executor: Kimi (fixture creation + docs closeout)

## Current State

- D7.3C canonical fixture created and validated.
- Current branch: `recovery/d7-activity-versioning`.
- Current `HEAD`: `cbde400` (`Record D7.3A closeout`).
- `origin/recovery/d7-activity-versioning` aligned with local at `cbde400`.
- `main` / `origin/main` remain intact at `7e5eb56`.
- Working tree has one new untracked directory: `normative_fixtures/` (to be committed).
- D7.3A analyzed three DOCX regulations stored in `_normativos_inbox/`:
  - `ACC-rev5.docx` → internal codigo AAC-rev5 (histórico/legado).
  - `ACC-rev6.docx` → internal codigo AAC-rev6 (AAC vigente).
  - `AE-rev1.docx` → internal codigo AEU-rev1 (AEU vigente).
- D7.3B-PLAN specified the fixture format (YAML, controlled vocabulary, mapping to schema).
- D7.3C created the canonical fixture: `normative_fixtures/d73c_normative_fixture.yaml`.
  - 3 normas: AAC-rev5, AAC-rev6, AEU-rev1.
  - 32 unique conceptual activities.
  - 61 total versions across all norms.
  - 2 activities removed in AAC-rev6: SIMULADOR_VOO, TRAB_VOLUNTARIO_TERCEIRO_SETOR.
  - 3 native AEU activities: ORG_EVENTOS_EXTENSIONISTAS, PART_EVENTOS_EXTENSIONISTAS, CURSOS_OFICINAS_PALESTRAS_COMUNIDADE.
  - 1 explicit transition: TRAB_VOLUNTARIO_TERCEIRO_SETOR (AAC-rev5 → AEU-rev1).
  - PROJETOS_EXTENSAO is ambiguous (AAC apoio institucional vs AEU extensão) and requires human decision.
  - `status_inicial` = "rascunho" for all versions.
  - `ch_regra_condicional` uses controlled vocabulary.
  - YAML validated with `python -c "yaml.safe_load(...)"` → `YAML_OK`.
  - No code, template, test, DB, or seed was changed.
  - The DOCX files remain excluded from Git and must not be committed.
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

## D7.3B-PLAN — Fixture Specification

- Scope: specify the canonical fixture format before implementation.
- Format: YAML chosen over JSON/CSV for human readability, multiline support, and Git diff clarity.
- Directory: `normative_fixtures/` (no `data/` directory exists in project).
- Structure: `meta`, `normas`, `atividades` with `versoes`, `atividade_removida_em`, `atividade_nova_em`, `transicao_proposta`.
- `status_inicial` = "rascunho" for all versions.
- `ch_regra_condicional` uses controlled vocabulary: null, equivalente_curso, equivalente_horas, tempo_declarado_ou_limite, carga_declarada_ou_limite_evento, tier_documental, horas_por_evento, horas_por_banca, regra_especial_ivao, exige_decisao_humana.
- `[REGRA: ...]` and `[ANEXOS: ...]` prefixes used in `observacao_admin` to preserve normative metadata.
- No code, template, test, DB, or seed was changed during D7.3B-PLAN.

## D7.3C — Canonical Fixture Creation

- Scope: create the real canonical normative fixture YAML from the three DOCX regulations.
- Output: `normative_fixtures/d73c_normative_fixture.yaml`.
- Contents:
  - 3 normas: AAC-rev5 (29 activities), AAC-rev6 (27 activities), AEU-rev1 (5 activities).
  - 32 unique conceptual activities mapped to `atividade_base`.
  - 61 total versions across all norms.
  - 2 activities removed in AAC-rev6: SIMULADOR_VOO, TRAB_VOLUNTARIO_TERCEIRO_SETOR.
  - 3 native AEU activities: ORG_EVENTOS_EXTENSIONISTAS, PART_EVENTOS_EXTENSIONISTAS, CURSOS_OFICINAS_PALESTRAS_COMUNIDADE.
  - 1 explicit transition: TRAB_VOLUNTARIO_TERCEIRO_SETOR (AAC-rev5 → AEU-rev1, tipo: aac_para_aeu).
  - PROJETOS_EXTENSAO is ambiguous (AAC apoio institucional vs AEU extensão) and requires human decision (`exige_decisao_humana` noted in observacao_admin).
  - `status_inicial` = "rascunho" for all 61 versions.
  - `ch_regra_condicional` uses controlled vocabulary throughout.
  - YAML validated with Python `yaml.safe_load` → `YAML_OK`.
  - Deep validation: no invalid `ch_regra_condicional` values, no missing required fields.
- No code, template, test, DB, or seed was changed during D7.3C.
- The DOCX files remain in `_normativos_inbox/` and are excluded from Git.

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
- Three normative regulations were canonized (D7.3A) and fixture was created (D7.3C), but no data has been imported yet.
- D7.3D (dry-run importer) must consume the fixture YAML, not the DOCX directly.
- Importação must not touch matrix, requests, student, calculation, or deferment.
- Ambiguous cases between "apoio institucional" (AAC) and "extensão" (AEU) require human review.
- Fixture is uncommitted; working tree has `normative_fixtures/` ready to stage.

## Recommended Next Step

- D7.3C is closed (fixture created, validated, no code).
- D7.3D: create a dry-run importer consuming the fixture YAML into an isolated DB.
- Dry-run importer must not touch matrix, requests, student, calculation, or deferment.
- Do not start any new implementation phase without explicit approved scope.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Treat `atividade_id` as the operational source of truth.
- D7.3A canonized three norms: AAC-rev5 (histórico), AAC-rev6 (vigente), AEU-rev1 (vigente).
- D7.3C created the canonical fixture: `normative_fixtures/d73c_normative_fixture.yaml`.
- The canonical DOCX are stored in `_normativos_inbox/` and excluded from Git; do not commit them.
- The branch `recovery/d7-activity-versioning` is aligned locally/remotely at `cbde400` before this docs closeout.
- D7.3D must consume the fixture YAML, not the DOCX directly.
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
