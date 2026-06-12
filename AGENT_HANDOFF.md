# Agent Handoff

Last updated: 2026-06-12
Closeout: D7.3E fixture database convergence diagnostic closeout
Executor: Claude Sonnet 4.6 (docs closeout); Kimi K2.6 (audit D7.3D-PATCH1-REVIEW)

## Current State

- D7.3D dry-run importer implemented, audited (Kimi K2.6), and committed.
- D7.3E-RO1 read-only fixture vs real database convergence diagnostic accepted.
- Current branch: `recovery/d7-activity-versioning`.
- Current `HEAD`: `45dd39d` (`Add D7.3D normative dry-run importer`).
- `origin/recovery/d7-activity-versioning` aligned with `HEAD` (`0 0`).
- `main` / `origin/main` remain intact at `7e5eb56`.
- Working tree clean.
- New files delivered in D7.3D:
  - `tools/d73d_normative_importer_dryrun.py` — CLI dry-run importer.
  - `tests/test_d73d_normative_importer_dryrun.py` — 5 tests, all passing.
  - `requirements.txt` — added `PyYAML==6.0.2`.
- D7.3D-PATCH1 accepted: 5 tests pass, no bloqueante/alto findings, database.db intacto.
- Importação real para `database.db` ainda não foi executada.
- D7.3E-RO1 confirmed in read-only mode that the canonical fixture does not safely converge with the current real DB without reconciliation first.
- Existing approved committed milestones:
  - D7.3D committed/pushed at `45dd39d`;
  - D7.3C committed at `5f66239`;
  - D7.2B6 committed/pushed at `95cb897`;
  - D7.2B5-PATCH2 committed at `9d2e9fb`;
  - D7.2B5-PATCH1 committed at `f235f62`;
  - D7.2B4-PATCH1 committed at `255ff80`;
  - D7.2B3-PATCH3 committed/pushed at `28d922d`;
  - `main` / `origin/main` preserved at `7e5eb56`.

## D7.3D — Last Closed Phase

- Scope: dry-run importer consuming `normative_fixtures/d73c_normative_fixture.yaml` into an isolated SQLite DB.
- Files delivered:
  - `tools/d73d_normative_importer_dryrun.py` (979 lines) — CLI, validation, upsert logic, schema + triggers.
  - `tests/test_d73d_normative_importer_dryrun.py` (236 lines) — 5 tests, all passing.
  - `requirements.txt` — added `PyYAML==6.0.2`.
- Audit: D7.3D-PATCH1-REVIEW by Kimi K2.6, result: **ACEITAR D7.3D-PATCH1**. No bloqueante/alto findings.
  - Risco baixo B-01: `documentacao_exigida` validada somente quando a chave existe.
- Functional guarantees:
  - `--fixture` obrigatório; `--report text/json`; `--strict` eleva warnings a erros.
  - Sem `--apply`, sem modo real; recusa `--db database.db` antes de qualquer conexão.
  - Sem import de `main`, `create_app`, `init_db`, ou `APP_DATABASE`.
  - Banco temporário via `tempfile`, removido em `finally`; ou `--db` explícito seguro.
  - `database.db` real preservado: tamanho e SHA256 inalterados (verificado por teste).
  - Schema idêntico ao de `main.py`: 4 tabelas, 6 triggers.
  - Idempotência: segunda execução no mesmo `--db` → inserted=0, skipped=3/32/61/1.
  - Transação atômica: rollback completo em qualquer falha de insert.
- Contagens com fixture D7.3C: 3 normas, 32 bases, 61 versões, 1 transição.
- Testes: `python -m pytest tests/test_d73d_normative_importer_dryrun.py -q --tb=short` → 5 passed.
- Importação real para `database.db` não foi executada. D7.3D está fechada.

## D7.3E-RO1 — Fixture vs Real Database Convergence Diagnostic

- Scope: read-only comparison between `normative_fixtures/d73c_normative_fixture.yaml` and the current `database.db`.
- Git state observed during diagnosis:
  - branch `recovery/d7-activity-versioning`;
  - `HEAD` `45dd39d`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - working tree clean;
  - `main` / `origin/main` preserved at `7e5eb56`.
- Real DB integrity preserved:
  - before: `528384` bytes;
  - SHA256 before: `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
  - after: `528384` bytes;
  - SHA256 after: `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.
- DB access method:
  - SQLite URI read-only mode (`mode=ro`);
  - only `SELECT`, `PRAGMA`, and `sqlite_master` reads.
- Current DB counts:
  - `norma_atividade`: `6`;
  - `atividade_base`: `35`;
  - `atividade_versao`: `60`;
  - `atividade_transicao`: `31`;
  - `matriz_atividade_versao_item`: `59`;
  - `requisicoes`: `41`;
  - fully versioned `requisicoes`: `13`;
  - only one version outside matrix links: `id=60`, `Runtime Base 2cb9b503`, `NRM-RT-2cb9b503`, `rascunho`.
- Fixture counts:
  - `3` normas, `32` atividades, `61` versões, `1` proposed transition;
  - `2` removed activities;
  - `3` new activities;
  - per norm: `AAC-rev5=29`, `AAC-rev6=27`, `AEU-rev1=5`.
- Norm comparison:
  - `AAC-rev5`, `AAC-rev6`, and `AEU-rev1` exist by code, but all diverge in `nome`;
  - extra norms outside fixture: `NRM-RT`, `NRM-RT-5c96604e`, `NRM-RT-2cb9b503`.
- Activity/version comparison:
  - `20` exact-name bases have divergent descriptions;
  - `11` clear nominal duplicates;
  - `1` near match: `Prova de Inglês ICAO` vs `Prova de inglês ICAO`;
  - `38` fixture versions have some comparable DB version, but all are divergent;
  - `23` versions remain `missing` in semantic crosswalk because DB uses different `nome_conceito`;
  - `18` divergences are status-only;
  - `20` divergences also include structural differences;
  - all comparable existing versions are already used in matrix.
- Transition comparison:
  - fixture transition `TRAB_VOLUNTARIO_TERCEIRO_SETOR AAC-rev5 -> AEU-rev1` already exists as `aac_para_aeu`, but with divergent `justificativa`;
  - no direct fixture transition is missing;
  - DB has extra transition history outside fixture:
    - `25` `mesmo_eixo`;
    - `1` extra `aac_para_aeu` for `Participação em projetos de extensão`;
    - `3` `nova_aeu`;
    - `1` `descontinuada` for `SIMULADOR_VOO`.
- Technical conclusion:
  - with the current semantics, the dry-run importer would abort on the first divergent norm if pointed at the real DB;
  - the dry-run importer is not a real importer and must not be repurposed as `apply`.
- High risks:
  - direct fixture apply would fail or require reconciliation before the first norm;
  - risk of duplicating bases on non-exact names;
  - `59` matrix links and `13` versioned requests depend on the current catalog;
  - overwrite/recreation could break runtime/history;
  - `PROJETOS_EXTENSAO` requires explicit human decision because the fixture canonizes one base while DB materialized distinct bases plus its own transition.
- Medium risks:
  - `NRM-RT` namespace outside fixture;
  - fixture does not cover all already-persisted transition history.
- Decision:
  - do not apply the fixture to `database.db`;
  - do not build a real importer yet;
  - next phase should be `D7.3F-PLAN`, read-only reconciliation planning only.

## D7.3A — Prior Closed Phase

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

- `9d2e9fb` - Add explicit activity version substitution
- `5f7dbc8` - Record D7.2B5-PATCH2 substitution closeout
- `95cb897` - Add admin transition history for activity versions
- `cbde400` - Record D7.3A normative canonization
- `5f66239` - Add D7.3C canonical normative fixture and docs closeout
- `45dd39d` - Add D7.3D normative dry-run importer

## Risks To Keep In View

- `created_at` is displayed raw; no formatting pass was added.
- There is still no actor/admin audit field in `atividade_transicao`.
- The catalog screens still are not linked from the menu/sidebar.
- Reativação de versão still does not exist.
- D7.3D delivered the dry-run importer; real importation into `database.db` has NOT been performed.
- D7.3E-RO1 proved that fixture and real DB do not safely converge without prior reconciliation planning.
- The dry-run importer would abort on the first divergent norm if pointed at the current real DB.
- The live catalog already carries operational dependency:
  - `59` matrix links;
  - `13` fully versioned requests;
  - extra `NRM-RT` namespace;
  - extra transition history outside fixture.
- Real importation must not be started without explicit approved scope and a separate plan.
- Ambiguous cases between "apoio institucional" (AAC) and "extensão" (AEU) require human review.
- `PROJETOS_EXTENSAO` remains the most sensitive reconciliation case and requires explicit human decision.
- B-01: `documentacao_exigida` validated only when key is present; future fixture versions that omit the key will pass silently.
- `atividade_transicao` has no DB-level UNIQUE on `(from, to, tipo)`; idempotency relies on SELECT-before-INSERT in the tool.

## Recommended Next Step

- D7.3F-PLAN should be the next phase.
- Scope of D7.3F-PLAN: read-only reconciliation matrix between fixture and real DB for each norm/base/version/transition.
- The plan must classify each item as: map to existing, create new, preserve existing, do not apply, or require human decision.
- Never overwrite any version already used in matrix or request without an explicit approved apply plan.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Treat `atividade_id` as the operational source of truth.
- D7.3A canonized three norms: AAC-rev5 (histórico), AAC-rev6 (vigente), AEU-rev1 (vigente).
- D7.3C created the canonical fixture: `normative_fixtures/d73c_normative_fixture.yaml`.
- D7.3D delivered the dry-run importer: `tools/d73d_normative_importer_dryrun.py`.
  - Run with: `python tools/d73d_normative_importer_dryrun.py --fixture normative_fixtures/d73c_normative_fixture.yaml`
  - Tests: `python -m pytest tests/test_d73d_normative_importer_dryrun.py -q --tb=short`
  - Do NOT run with a real `--db` pointing to `database.db`; the tool will refuse, but do not attempt it.
- D7.3E-RO1 already diagnosed fixture vs real DB convergence in read-only mode.
- Do not attempt any real import, reconciliation write, or importer `apply` against `database.db`.
- Next intended phase is `D7.3F-PLAN`, still read-only.
- The canonical DOCX are stored in `_normativos_inbox/` and excluded from Git; do not commit them.
- Real importation into `database.db` has NOT been performed. Do not perform it without explicit scope approval.
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
