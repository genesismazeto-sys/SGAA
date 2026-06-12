# Agent Handoff

Last updated: 2026-06-12
Closeout: D7.3F reconciliation matrix decisions closeout
Executor: Codex GPT-5 (docs closeout); Claude Sonnet 4.6 (D7.3E closeout); Kimi K2.6 (audit D7.3D-PATCH1-REVIEW)

## Current State

- D7.3D dry-run importer implemented, audited, and committed.
- D7.3E-RO1 read-only fixture vs real database convergence diagnostic accepted.
- D7.3F-PLAN read-only reconciliation matrix accepted and its architectural decisions are now closed.
- Current branch: `recovery/d7-activity-versioning`.
- Initial `HEAD` of D7.3F-PLAN: `f10db80` (`Record D7.3E fixture database convergence diagnostic`).
- `origin/recovery/d7-activity-versioning...HEAD = 0 0` before this closeout.
- `origin/main...main = 0 0`.
- `main` / `origin/main` preserved at `7e5eb56`.
- Working tree was clean at the start of this closeout.
- Real importation into `database.db` has still not been performed.
- `database.db` remained preserved during D7.3F:
  - before: `528384` bytes;
  - SHA256 before: `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
  - after: `528384` bytes;
  - SHA256 after: `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.

## D7.3D - Last Write Phase

- Scope: dry-run importer consuming `normative_fixtures/d73c_normative_fixture.yaml` into an isolated SQLite DB.
- Delivered files:
  - `tools/d73d_normative_importer_dryrun.py`
  - `tests/test_d73d_normative_importer_dryrun.py`
  - `requirements.txt` with `PyYAML==6.0.2`
- Guarantees:
  - no `--apply`;
  - refuses `--db database.db`;
  - no import from `main` / runtime app context;
  - temporary isolated DB only;
  - transaction-safe and idempotent;
  - real `database.db` preserved.
- Audit result: **ACEITAR D7.3D-PATCH1**.

## D7.3E-RO1 - Fixture vs Real Database Convergence Diagnostic

- Scope: read-only comparison between `normative_fixtures/d73c_normative_fixture.yaml` and the current `database.db`.
- Git state observed during diagnosis:
  - branch `recovery/d7-activity-versioning`;
  - `HEAD` `45dd39d`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - working tree clean.
- DB access method:
  - SQLite URI read-only mode (`mode=ro`);
  - only `SELECT`, `PRAGMA`, and `sqlite_master` reads.
- Current DB counts at D7.3E:
  - `norma_atividade`: `6`;
  - `atividade_base`: `35`;
  - `atividade_versao`: `60`;
  - `atividade_transicao`: `31`;
  - `matriz_atividade_versao_item`: `59`;
  - `requisicoes`: `41`;
  - fully versioned `requisicoes`: `13`;
  - only one version outside matrix links: `id=60`, `Runtime Base 2cb9b503`, `NRM-RT-2cb9b503`, `rascunho`.
- Technical conclusion:
  - the dry-run importer would abort on the first divergent norm if pointed at the current real DB;
  - it must not be repurposed as `apply`;
  - direct fixture application to the live DB is unsafe.

## D7.3F-PLAN - Reconciliation Matrix Decisions

- Scope: read-only reconciliation matrix between the canonical fixture and the current real database.
- Execution state observed:
  - initial `HEAD` `f10db80`;
  - branch `recovery/d7-activity-versioning`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - working tree clean;
  - SQLite opened only by URI read-only mode (`mode=ro`);
  - no file or database altered during the diagnosis.
- Matrix summary:
  - `30` fixture activities have preservable mappings to existing bases;
  - `59` of `61` fixture versions have an existing preservable candidate;
  - the remaining `2` versions were `VISITAS_TECNICAS_PROFESSORES` in `AAC-rev5` and `AAC-rev6`;
  - all versions `1..59` are already linked in `matriz_atividade_versao_item`;
  - versions `2`, `8`, `10`, `56`, and `58` also appear in versioned requests/snapshots;
  - `atividade_versao.id=60` is runtime `NRM-RT-2cb9b503` and remains outside official reconciliation;
  - fixture transition `TRAB_VOLUNTARIO_TERCEIRO_SETOR AAC-rev5 -> AEU-rev1` already exists as `atividade_transicao.id=27`, but with divergent `justificativa`.
- Architectural decision closed for `PROJETOS_EXTENSAO`:
  - preserve the live split;
  - preserve `base27` / `v52` / `v53` for extension projects;
  - preserve `base8` / `v51` for institutional support projects;
  - preserve the extra persisted `aac_para_aeu` transition already present in runtime;
  - do not collapse these into a single canonical live base.
- Architectural decision closed for `VISITAS_TECNICAS_PROFESSORES`:
  - do not map it automatically to `base6`;
  - `base6` is too generic for a safe canonical mapping;
  - if a future apply phase is explicitly approved, create a new specific `atividade_base` and draft versions for `AAC-rev5` and `AAC-rev6`;
  - this phase did not authorize any real creation.
- Frozen reconciliation rules:
  - never overwrite `atividade_versao.id=1..59`;
  - never overwrite versions with versioned requests/snapshots: `2`, `8`, `10`, `56`, `58`;
  - never overwrite `atividade_transicao.id=1..31`;
  - never alter runtime `NRM-RT*` items;
  - any future structural reconciliation must happen through a new draft version or explicit mapping, never overwrite.
- Runtime items that remain `PRESERVE_EXISTING / OUT_OF_FIXTURE`:
  - `NRM-RT`;
  - `NRM-RT-5c96604e`;
  - `NRM-RT-2cb9b503`;
  - `Runtime Base`;
  - `Runtime Base 5c96604e`;
  - `Runtime Base 2cb9b503`.
- Human decisions are now closed:
  - `PROJETOS_EXTENSAO`: keep runtime split;
  - `VISITAS_TECNICAS_PROFESSORES`: no mapping to `base6`; future specific draft creation only if later approved.

## Recent Commits

- `95cb897` - Add admin transition history for activity versions
- `cbde400` - Record D7.3A normative canonization
- `5f66239` - Add D7.3C canonical normative fixture and docs closeout
- `45dd39d` - Add D7.3D normative dry-run importer
- `f10db80` - Record D7.3E fixture database convergence diagnostic

## Risks To Keep In View

- Critical:
  - overwriting versions already used in matrix or versioned requests;
  - reconciling `PROJETOS_EXTENSAO` without preserving the live split.
- High:
  - mapping `VISITAS_TECNICAS_PROFESSORES` to `base6`;
  - changing `NRM-RT` runtime items;
  - promoting the dry-run importer into a real apply path.
- Medium:
  - structural divergences in group / workload / limits;
  - fixture does not cover all persisted transition history.
- Low:
  - textual divergences when IDs and persisted history are preserved.
- Residual backlog:
  - `documentacao_exigida` is only validated when the key exists in the fixture tool;
  - `atividade_transicao` still has no DB-level UNIQUE on `(from, to, tipo)`.

## Recommended Next Step

- `D7.3G-PLAN-APPLY` should be the next phase.
- Scope of `D7.3G-PLAN-APPLY`:
  - produce an item-by-item apply plan that respects the D7.3F frozen rules and decisions;
  - keep the work planning-only;
  - do not write to `database.db`.
- Any future real apply requires:
  - intact backup;
  - item-by-item approved plan;
  - dry-run against a database copy;
  - explicit authorization.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Treat `atividade_id` as the operational source of truth.
- Do not attempt any real import, reconciliation write, or importer `apply` against `database.db`.
- `PROJETOS_EXTENSAO` is no longer open for semantic collapse: preserve the live split.
- `VISITAS_TECNICAS_PROFESSORES` must not be mapped to `base6`.
- Runtime `NRM-RT*` items remain outside fixture reconciliation.
- Never overwrite versions already used in matrix or versioned requests.
- Next intended phase is `D7.3G-PLAN-APPLY`, still planning-only.
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
  - `resolver_versao_por_matriz`;
  - `resolver_versao_por_aluno`;
  - `resolver_versao`;
  - `maybe_write_versioned_requisicao_snapshot`.
