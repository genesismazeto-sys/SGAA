# Agent Handoff

Last updated: 2026-06-12
Closeout: D7.3D normative dry-run importer closeout
Executor: Claude Sonnet 4.6 (docs closeout); Kimi K2.6 (audit D7.3D-PATCH1-REVIEW)

## Current State

- D7.3D dry-run importer implemented, audited (Kimi K2.6), and committed.
- Current branch: `recovery/d7-activity-versioning`.
- Current `HEAD`: TBD (D7.3D commit, being set by this closeout).
- `origin/recovery/d7-activity-versioning` will be aligned after push.
- `main` / `origin/main` remain intact at `7e5eb56`.
- Working tree clean after commit (expected).
- New files delivered in D7.3D:
  - `tools/d73d_normative_importer_dryrun.py` — CLI dry-run importer.
  - `tests/test_d73d_normative_importer_dryrun.py` — 5 tests, all passing.
  - `requirements.txt` — added `PyYAML==6.0.2`.
- D7.3D-PATCH1 accepted: 5 tests pass, no bloqueante/alto findings, database.db intacto.
- Importação real para `database.db` ainda não foi executada.
- Existing approved committed milestones:
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
- TBD        - Add D7.3D normative dry-run importer

## Risks To Keep In View

- `created_at` is displayed raw; no formatting pass was added.
- There is still no actor/admin audit field in `atividade_transicao`.
- The catalog screens still are not linked from the menu/sidebar.
- Reativação de versão still does not exist.
- D7.3D delivered the dry-run importer; real importation into `database.db` has NOT been performed.
- Real importation must not be started without explicit approved scope and a separate plan.
- Ambiguous cases between "apoio institucional" (AAC) and "extensão" (AEU) require human review.
- B-01: `documentacao_exigida` validated only when key is present; future fixture versions that omit the key will pass silently.
- `atividade_transicao` has no DB-level UNIQUE on `(from, to, tipo)`; idempotency relies on SELECT-before-INSERT in the tool.

## Recommended Next Step

- D7.3D is closed (dry-run importer implemented, audited, committed).
- Real importation into `database.db` requires separate explicit scope approval before starting.
- Do not start any new implementation phase without explicit approved scope and read-only planning pass.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Treat `atividade_id` as the operational source of truth.
- D7.3A canonized three norms: AAC-rev5 (histórico), AAC-rev6 (vigente), AEU-rev1 (vigente).
- D7.3C created the canonical fixture: `normative_fixtures/d73c_normative_fixture.yaml`.
- D7.3D delivered the dry-run importer: `tools/d73d_normative_importer_dryrun.py`.
  - Run with: `python tools/d73d_normative_importer_dryrun.py --fixture normative_fixtures/d73c_normative_fixture.yaml`
  - Tests: `python -m pytest tests/test_d73d_normative_importer_dryrun.py -q --tb=short`
  - Do NOT run with a real `--db` pointing to `database.db`; the tool will refuse, but do not attempt it.
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
