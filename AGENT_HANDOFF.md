# Agent Handoff

Last updated: 2026-06-12
Closeout: D7.3H controlled reconciliation apply closeout
Executor: Codex GPT-5 (docs closeout); Claude Sonnet 4.6 (D7.3E closeout); Kimi K2.6 (audit D7.3D-PATCH1-REVIEW); auditor-PATCH1-REVIEW

## Current State

- D7.3D dry-run importer implemented, audited, and committed.
- D7.3E-RO1 read-only fixture vs real database convergence diagnostic accepted.
- D7.3F-PLAN read-only reconciliation matrix accepted and its architectural decisions are now closed.
- D7.3G-PLAN-APPLY accepted as a read-only future apply plan.
- D7.3H-PATCH1 controlled reconciliation apply script implemented and accepted after independent audit.
- Current branch: `recovery/d7-activity-versioning`.
- `origin/recovery/d7-activity-versioning...HEAD = 0 0` before this closeout.
- `origin/main...main = 0 0`.
- `main` / `origin/main` preserved at `7e5eb56`.
- Working tree had only the 2 expected untracked D7.3H files before selective staging.
- Real importation into `database.db` has still not been performed.
- `database.db` remained preserved during D7.3H:
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

## D7.3G-PLAN-APPLY - Future Apply Plan

- Scope: read-only technical plan for a possible future apply, derived from D7.3F.
- Execution state observed:
  - initial `HEAD` `da869e9`;
  - branch `recovery/d7-activity-versioning`;
  - remotes aligned;
  - working tree clean;
  - `database.db` intact at `528384` bytes and SHA256 `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.
- Apply scope frozen:
  - not a general reconciliation;
  - not a real import of the entire fixture;
  - only a possible future `CREATE_DRAFT` path for `VISITAS_TECNICAS_PROFESSORES`.
- `PRESERVE / NO-OP` set:
  - norms `AAC-rev5`, `AAC-rev6`, `AEU-rev1`;
  - all already reconciled bases and versions;
  - `atividade_versao.id=1..59`;
  - `atividade_transicao.id=1..31`;
  - `matriz_norma`;
  - `matriz_atividade_versao_item`;
  - `requisicoes`;
  - runtime `NRM-RT*`.
- `PROJETOS_EXTENSAO` remains preserve-only:
  - preserve `base8` / `v51`;
  - preserve `base27` / `v52` / `v53`;
  - preserve the extra persisted `aac_para_aeu` transition;
  - do not collapse.
- `CREATE_DRAFT` is the only future write path allowed in principle:
  - create `1` new specific `atividade_base` for `VISITAS_TECNICAS_PROFESSORES`;
  - create `1` draft `atividade_versao` for `AAC-rev5`;
  - create `1` draft `atividade_versao` for `AAC-rev6`;
  - do not create matrix links;
  - do not create transitions;
  - do not modify requests.
- `FORBIDDEN` set:
  - overwrite any existing `atividade_versao`;
  - change `ativa -> rascunho`;
  - alter matrix;
  - alter requests or snapshots;
  - alter existing transitions;
  - alter runtime `NRM-RT*`;
  - collapse `PROJETOS_EXTENSAO`;
  - create new AAC/AEU norms;
  - create new versions for already mapped activities;
  - create new transitions in the initial apply.
- Mandatory preconditions for any real future apply:
  - intact verifiable backup of `database.db`;
  - recorded size and SHA256 before execution;
  - execute first against a DB copy;
  - produce logical before/after diff report;
  - explicit rollback path;
  - explicit human approval;
  - focused post-apply tests;
  - guaranteed `+0` changes to matrix, requests, transitions, and norms.

## D7.3H-PATCH1 - Controlled Reconciliation Apply Script

- Scope: new independent controlled `plan/apply` script for the only future write
  case admitted in planning: `CREATE_DRAFT` of `VISITAS_TECNICAS_PROFESSORES`.
- Delivered files:
  - `tools/d73h_reconciliation_apply.py`
  - `tests/test_d73h_reconciliation_apply.py`
- Script behavior:
  - `--plan` opens the target DB only by read-only URI mode;
  - `--apply` only accepts an explicit safe DB copy via `--db-copy`;
  - `--apply` refuses live `database.db`;
  - `--apply` refuses any `--db-copy` whose basename is `database.db`;
  - `--apply` requires `--backup-path`;
  - `--apply` requires `--backup-confirmed`;
  - `--apply` requires `--allow-create-visitas-professores`.
- Write scope allowed by the script:
  - `+1` `atividade_base`;
  - `+2` `atividade_versao` in `rascunho`;
  - `+0` `norma_atividade`;
  - `+0` `atividade_transicao`;
  - `+0` `matriz_atividade_versao_item`;
  - `+0` `requisicoes`.
- Guarantees preserved:
  - no general apply path;
  - no overwrite;
  - no touch to `PROJETOS_EXTENSAO`;
  - no touch to `NRM-RT*`;
  - no use of `base6`/`base7` as destination;
  - no alteration of existing versions;
  - no matrix change;
  - no request change;
  - no transition change.
- Validation evidence accepted:
  - real `database.db` preserved at `528384` bytes and
    `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
  - focused pytest:
    - `python -m pytest tests/test_d73h_reconciliation_apply.py -q --tb=short`
    - result: `17 passed`;
  - CLI `plan` text OK;
  - CLI `plan` JSON OK;
  - `apply` in temporary copy OK;
  - `apply` on live DB refused;
  - `git diff --check` clean.
- Audit:
  - `D7.3H-PATCH1-REVIEW` verdict: **ACEITAR D7.3H-PATCH1**;
  - no blocking/high/medium/low findings;
  - non-blocking observation: the suite does not explicitly assert default mode
    without `--plan/--apply` nor mutual exclusion by direct CLI execution, but
    the behavior is implemented and was independently audited as correct.
- Residual risks:
  - script assumes `AAC-rev5=id=1` and `AAC-rev6=id=2`;
  - `documentos_json` remains `NULL` in D7.3H-v1;
  - partial/conflicting state fails intentionally rather than repairing it.

## Recent Commits

- `95cb897` - Add admin transition history for activity versions
- `cbde400` - Record D7.3A normative canonization
- `5f66239` - Add D7.3C canonical normative fixture and docs closeout
- `45dd39d` - Add D7.3D normative dry-run importer
- `f10db80` - Record D7.3E fixture database convergence diagnostic
- `da869e9` - Record D7.3F reconciliation matrix decisions

## Risks To Keep In View

- Critical:
  - overwriting versions already used in matrix or versioned requests;
  - reconciling `PROJETOS_EXTENSAO` without preserving the live split.
- High:
  - mapping `VISITAS_TECNICAS_PROFESSORES` to `base6`;
  - changing `NRM-RT` runtime items;
  - promoting the dry-run importer into a real apply path.
- High:
  - broadening D7.3G beyond the `CREATE_DRAFT` path for `VISITAS_TECNICAS_PROFESSORES`.
- Medium:
  - structural divergences in group / workload / limits;
  - fixture does not cover all persisted transition history.
- Low:
  - textual divergences when IDs and persisted history are preserved.
- Residual backlog:
  - `documentacao_exigida` is only validated when the key exists in the fixture tool;
  - `atividade_transicao` still has no DB-level UNIQUE on `(from, to, tipo)`.

## Recommended Next Step

- D7.3H is closed at the implementation/documentation level.
- No real apply on live `database.db` is authorized.
- Any next phase must be an explicit product/operations decision between:
  - executing only on a controlled database copy;
  - or ending the trail without any live apply.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Treat `atividade_id` as the operational source of truth.
- Do not attempt any real import, reconciliation write, or importer `apply` against `database.db`.
- `PROJETOS_EXTENSAO` is no longer open for semantic collapse: preserve the live split.
- `VISITAS_TECNICAS_PROFESSORES` must not be mapped to `base6`.
- The only future apply path currently admitted in planning is `CREATE_DRAFT` for `VISITAS_TECNICAS_PROFESSORES`.
- Runtime `NRM-RT*` items remain outside fixture reconciliation.
- Never overwrite versions already used in matrix or versioned requests.
- D7.3H is already implemented and accepted.
- No next agent should perform real apply on `database.db` without a new explicit authorization phase.
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
