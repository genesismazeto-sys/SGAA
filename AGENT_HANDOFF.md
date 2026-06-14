# Agent Handoff

Last updated: 2026-06-13
Closeout: D7.6D matrix version selection
Executor: Claude Sonnet 4.6 (D7.6D matrix version selection + docs closeout; D7.6C activity version menu + docs closeout; D7.6B2 schema migration + R1 + R2 hardening + D7.6B3 docs closeout; D7.5D patch implementation + visual R1 fix + commit closeout); Codex GPT-5 (D7.5C patch implementation + validation report + commit closeout); Claude Sonnet 4.6 (D7.4F read-only archive audit; D7.4G archive execution); Codex GPT-5 (D7.3K read-only diagnosis + docs closeout; D7.3J live apply + suite stabilization + docs closeout; D7.3I validation + docs closeout; D7.3H docs closeout); Claude Sonnet 4.6 (D7.3E closeout); Kimi K2.6 (audit D7.3D-PATCH1-REVIEW)

## Current State

- D7.3D dry-run importer implemented, audited, and committed.
- D7.3E-RO1 read-only fixture vs real database convergence diagnostic accepted.
- D7.3F-PLAN read-only reconciliation matrix accepted and its architectural decisions are now closed.
- D7.3G-PLAN-APPLY accepted as a read-only future apply plan.
- D7.3H-PATCH1 controlled reconciliation apply script implemented and accepted after independent audit.
- D7.3I-VALIDATE-APPLY-COPY accepted after controlled execution against a temporary DB copy.
- D7.3J-LIVE-APPLY-CREATE-DRAFT accepted after controlled execution first on a DB copy and then by replacing live with the validated copy.
- D7.3J-PATCH1-TEST-STABILIZE accepted after decoupling the focused suite from mutable live DB state.
- D7.3K-DECIDE-MATRIX-LINK accepted after read-only diagnosis.
- D7.3 final decision: keep `61/62` as draft and close the trail with no activation and no matrix link.
- D7.4F read-only archive audit completed: all expected states confirmed before archival.
- D7.4G branch archive executed:
  - tag `archive/d7-activity-versioning` created at
    `b5aafa7605bab4f8ef4b61885ec5200627ea2f0b` and published to remote;
  - `recovery/d7-activity-versioning` remote branch deleted;
  - local branch `recovery/d7-activity-versioning` preserved at `b5aafa7` (`[gone]`);
  - no apply, SQL, activation, matrix link, merge, rebase, or code change executed.
- D7.5C accepted after implementation, focused tests, and user visual validation.
- D7.5C functional commit created:
  - `bc8a4f6` - `Add matrix-scoped activity creation`;
  - files: `main.py`, `templates/admin_matriz_form.html`,
    `tests/test_admin_matrix_new_activity.py`.
- D7.5C delivered:
  - generic `+ Nova atividade` button in the left header of the matrix screen;
  - same flow for `Lista de AAC` and `Lista de AEU`;
  - modal/form opened from the matrix screen;
  - initial `atividade_versao` created transactionally;
  - `matriz_atividade_versao_item` created when `Adicionar à matriz atual` is checked;
  - matrix name used only as contextual UI label, never in `codigo_normativo`.
- D7.5C preserved:
  - no schema/migration;
  - no `database.db` change in the feature closeout.
- D7.5D accepted after implementation, focused tests, visual validation, and R1 visual alert fix.
- D7.5D functional commit created:
  - `0dbd2b1` - `Add matrix card version creation`;
  - files: `main.py`, `templates/admin_matriz_form.html`,
    `tests/test_admin_matriz_nova_versao_card.py`.
- D7.5D delivered:
  - `⋮` button on right-column (selected/linked) activity cards in the matrix edit screen;
  - modal with norma select and context label `Versão nesta matriz: [codigo_normativo]`;
  - POST route creates or reuses `atividade_versao` respecting UNIQUE constraint;
  - relinks only the current matrix; older matrices preserve their original version link;
  - matrix name not written into `codigo_normativo`.
- D7.5D preserved:
  - no schema/migration;
  - no `database.db` change in the feature closeout;
  - no in-place UPDATE of a version already used by older matrices;
  - D7.5C not reopened.
- Current branch: `main`.
- D7.5D functional state is recorded by commit `0dbd2b1` on `main`.
- `main` is 3 commits ahead of `origin/main`.
- Working tree clean.
- D7 fully integrated into `main`. D7.4 trail is closed.
- D7.5D is complete (commit `0dbd2b1`).
- D7.6B2 is complete: `numero_versao` operacional entregue, schema endurecido, testes validados.
  - `UNIQUE(atividade_base_id, norma_id)` removida.
  - `UNIQUE INDEX idx_atividade_versao_base_num ON atividade_versao(atividade_base_id, numero_versao)` — full, non-partial.
  - `numero_versao >= 1` enforced by triggers (existing DB) and `CHECK` (new DB DDL).
  - `codigo_normativo` remains normative metadata, not the operational version identifier.
  - `norma_id` and `codigo_normativo` remain `NOT NULL`.
  - Commits: `1ca00a3`, `5184143`, `6b1579a`.
- D7.6C is complete: menu ⋮ de versões na tela `/admin/atividades` entregue.
  - Commit aceito: `62aed4b` — `Add activity version menu to admin activities`.
  - Menu contém: Editar atividade, Criar nova versão, Ver versões.
  - "Criar nova versão" navega para `/admin/catalogo-versoes/<base_id>/nova-versao`.
  - "Ver versões" navega para `/admin/catalogo-versoes/<base_id>`.
  - `base_id` obtido via subquery em `atividade_legacy_map` na query de `admin_atividades`.
  - Atividades sem `base_id` não geram link inválido (ações ficam `disabled`).
  - Nenhum template da matriz alterado; schema e `database.db` intocados.
  - Testes: `tests/test_admin_atividades_version_menu.py` 9/9; regressões 57/57.
- D7.6D is complete: matriz escolhe/relinka versão operacional existente.
  - Commit aceito: `2f81179` — `Make matrix choose operational activity versions`.
  - Card da matriz exibe badge `vN` via `atividade_versao.numero_versao`.
  - `codigo_normativo` é metadado secundário; não é badge principal.
  - Modal lista versões existentes da mesma `atividade_base` em ordem decrescente.
  - Versão atual da matriz aparece pré-selecionada (`is_current: true`).
  - POST relinka via `_set_versao_da_matriz_para_base`; não cria `atividade_versao`.
  - POST valida `versao_id` pertencente à mesma `atividade_base`; rejeita cross-base e inexistentes.
  - `templates/admin_atividades.html` não alterado. Schema e `database.db` intocados.
  - Testes: `tests/test_admin_matriz_escolher_versao.py` 10/10; `tests/test_admin_matriz_nova_versao_card.py` 13/13; regressões 64/64.
- Current branch: `main`. HEAD: `2f81179`.
- `main` is 11 commits ahead of `origin/main`. Working tree clean. Push não realizado.
- No broad real importation into `database.db` has been performed; only the
  narrow D7.3J controlled `CREATE_DRAFT` live apply.
- `database.db` current state (post-D7.6B2):
  - `544768` bytes;
  - SHA256 `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`.
- Live now contains:
  - `atividade_base.id=37`;
  - `atividade_versao.id=61`, `AAC-rev5`, `status=rascunho`;
  - `atividade_versao.id=62`, `AAC-rev6`, `status=rascunho`;
  - no matrix links, no transition changes, and no request changes for those rows.
- D7.3K confirmed in read-only mode:
  - no file changed during diagnosis;
  - no DB changed during diagnosis;
  - only SQLite `SELECT` / `PRAGMA` were executed in `mode=ro`;
  - there is still no legitimate matrix candidate for base `37`.

## D7.3D - Historical Tooling Write Phase

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

## D7.3I-VALIDATE-APPLY-COPY - Validation Of Apply On Controlled DB Copy

- Scope executed:
  - validation of `tools/d73h_reconciliation_apply.py`;
  - `--apply` executed only on a temporary copy of `database.db`;
  - `--backup-path`, `--backup-confirmed`, and
    `--allow-create-visitas-professores` were required and supplied;
  - no write was performed against live `database.db`.
- Result of the apply on the copy:
  - process returned `0`;
  - `mode=apply`;
  - `disposition=create`;
  - created records:
    - `atividade_base.id=37`;
    - `atividade_versao.id=61`, `AAC-rev5`, `status=rascunho`;
    - `atividade_versao.id=62`, `AAC-rev6`, `status=rascunho`.
- Deltas confirmed on the copy:
  - `atividade_base`: `35 -> 36` (`+1`);
  - `atividade_versao`: `60 -> 62` (`+2`);
  - `norma_atividade`: `6 -> 6` (`+0`);
  - `atividade_transicao`: `31 -> 31` (`+0`);
  - `matriz_atividade_versao_item`: `59 -> 59` (`+0`);
  - `requisicoes`: `41 -> 41` (`+0`).
- Before/after comparison:
  - remained unchanged:
    - `norma_atividade`;
    - `atividade_transicao`;
    - `matriz_atividade_versao_item`;
    - `requisicoes`;
    - all pre-existing rows of `atividade_base`;
    - all pre-existing rows of `atividade_versao`;
  - the only observed effect was insertion of the 3 expected records in the copy.
- Guardrails confirmed:
  - `base6`/`base7` exist, but were treated as prohibited candidates;
  - `base6`/`base7` were not used as destination;
  - `PROJETOS_EXTENSAO` was not touched;
  - `NRM-RT*` was not touched.
- Live `database.db`:
  - was not a write target;
  - stayed at `528384` bytes;
  - stayed at SHA256
    `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.
- Conclusion:
  - validation on a DB copy passed;
  - the script behaved correctly in the controlled scenario;
  - this does **not** authorize any real apply on live.

## D7.3J-LIVE-APPLY-CREATE-DRAFT - Controlled Live Apply And Suite Stabilization

- Initial state before the live apply:
  - `HEAD=aedf936`;
  - branch `recovery/d7-activity-versioning`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - live `database.db` before apply:
    - `528384` bytes;
    - SHA256
      `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.
- Backup created:
  - `backups/database.pre-d73j-live-apply-20260612-165031.db`;
  - `528384` bytes;
  - SHA256
    `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
  - backup matched the initial live DB.
- Apply execution model:
  - executed first only on a controlled DB copy;
  - after validation, live `database.db` was replaced by that validated copy;
  - no manual SQL was executed;
  - there was no direct apply against the live file;
  - script used: `tools/d73h_reconciliation_apply.py`.
- Records created in live:
  - `atividade_base.id=37`;
  - `atividade_versao.id=61`, `norma_codigo=AAC-rev5`, `status=rascunho`,
    `eixo=AAC`;
  - `atividade_versao.id=62`, `norma_codigo=AAC-rev6`, `status=rascunho`,
    `eixo=AAC`.
- Final deltas in live:
  - `atividade_base`: `35 -> 36` (`+1`);
  - `atividade_versao`: `60 -> 62` (`+2`);
  - `norma_atividade`: `6 -> 6` (`+0`);
  - `atividade_transicao`: `31 -> 31` (`+0`);
  - `matriz_atividade_versao_item`: `59 -> 59` (`+0`);
  - `requisicoes`: `41 -> 41` (`+0`).
- Guarantees confirmed:
  - no new norm;
  - no new transition;
  - no new matrix link;
  - no request changed;
  - no old version changed;
  - `PROJETOS_EXTENSAO` was not touched;
  - `NRM-RT*` was not touched;
  - `base6`/`base7` were treated as prohibited candidates and not used as destination;
  - versions `61/62` remained `rascunho` and without matrix link.
- Live final signature:
  - `528384` bytes;
  - SHA256
    `09C0791A00B9A6EAB3BABC7E8349E8582092ADE6EB911798CE55062819A48E1A`.
- Post-apply test anomaly:
  - after the live apply, `4` focused D7.3H tests failed;
  - cause: those tests assumed `REAL_DB_PATH` still reflected the pre-apply state;
  - that premise stopped being valid because live moved to post-apply;
  - this was not a defect in the script and not a defect in the data.
- D7.3J-PATCH1-TEST-STABILIZE:
  - changed only `tests/test_d73h_reconciliation_apply.py`;
  - create-path tests now use a temporary controlled pre-apply scenario;
  - already-exists / idempotency tests now use a temporary controlled
    post-apply scenario;
  - fallback without backup removes only the 3 D7.3J rows in a temporary copy;
  - if `VISITAS_TECNICAS_PROFESSORES` gains more complex links or state later,
    the helper fails on purpose instead of masking the new scenario.
- Validation after stabilization:
  - focused pytest:
    - `python -m pytest tests/test_d73h_reconciliation_apply.py -q --tb=short`
    - result: `18 passed`;
  - live `plan` JSON updated:
    - `status=ok`;
    - `mode=plan`;
    - `disposition=already_exists`;
    - `planned_counts={"atividade_base": 0, "atividade_versao": 0}`;
    - `planned_actions=[]`;
    - `created_ids={"atividade_base": null, "atividade_versao": []}`;
  - live counts:
    - `atividade_base=36`;
    - `atividade_versao=62`;
    - `norma_atividade=6`;
    - `atividade_transicao=31`;
    - `matriz_atividade_versao_item=59`;
    - `requisicoes=41`.
- Git operational note:
  - `database.db` is ignored by the repository;
  - `git status --short` can appear clean after an operational DB change;
  - `git status --short --ignored` shows `database.db`, `database.db-wal`,
    `database.db-shm`, backups, and `tmp/` as ignored;
  - none of those artifacts must be committed.
- Final D7.3J state:
  - `VISITAS_TECNICAS_PROFESSORES` exists in live as draft;
  - it was not activated;
  - it was not linked to any matrix;
  - it did not alter requests;
  - it did not alter transitions;
  - it did not alter norms;
  - no refactor was performed.

## D7.3K-DECIDE-MATRIX-LINK - Read-Only Diagnosis And Final D7.3 Decision

- Execution mode:
  - read-only architectural / operational diagnosis only;
  - no file edits in the diagnosis phase;
  - no DB writes in the diagnosis phase;
  - only Git inspection, file reads, SQLite `SELECT` and `PRAGMA` in `mode=ro`.
- Initial state confirmed:
  - branch `recovery/d7-activity-versioning`;
  - `HEAD=b8ad2ae`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - `git status --short` was empty;
  - live `database.db` stayed at `528384` bytes and
    `09C0791A00B9A6EAB3BABC7E8349E8582092ADE6EB911798CE55062819A48E1A`.
- Live state confirmed by read-only queries:
  - `atividade_base.id=37` exists and is `status='ativo'`;
  - `atividade_versao.id=61` exists with `AAC-rev5`, `status='rascunho'`, `eixo='AAC'`;
  - `atividade_versao.id=62` exists with `AAC-rev6`, `status='rascunho'`, `eixo='AAC'`;
  - both have no row in `matriz_atividade_versao_item`;
  - both have no row in `requisicoes`;
  - both have no row in `atividade_transicao` as origin or destination.
- Counts confirmed:
  - `atividade_base=36`;
  - `atividade_versao=62`;
  - `norma_atividade=6`;
  - `atividade_transicao=31`;
  - `matriz_atividade_versao_item=59`;
  - `requisicoes=41`.
- Matrix diagnosis:
  - matrix `1` has `AAC-rev6` in `matriz_norma`;
  - matrix `2` has `AAC-rev5` in `matriz_norma`;
  - there is no real candidate matrix now because base `37` has no
    `atividade_legacy_map` row and therefore is outside the legacy scope of
    every matrix.
- Technical rule confirmed:
  - matrixâ†’`atividade_versao` link requires version `status='ativa'`;
  - the admin UI lists only active versions;
  - the route also requires the base to be in the matrix legacy scope;
  - the route also requires the version norm to be present in `matriz_norma`.
- Architectural decision:
  - do not activate `61/62` now;
  - do not link `61/62` now;
  - keep both versions as `rascunho`;
  - close D7.3 with no additional DB action.
- Reason:
  - a draft version cannot be linked;
  - isolated activation would still be insufficient;
  - there is no legitimate legacy mapping for base `37`;
  - forcing a mapping now would create collision risk without proven
    operational need.
- Future prohibition recorded:
  - do not reuse `base6` / `base7` as destination to resolve base `37`;
  - do not activate or link `61/62` without a new separate phase.
- Future phase permitted only if a real operational need appears:
  - decide the correct legacy activity to map to base `37`;
  - create or validate the legacy mapping;
  - activate the correct version;
  - link explicitly to the correct matrix;
  - test the resolver and the admin link route.
- Final D7.3 conclusion:
  - D7.3J created the controlled draft versions;
  - D7.3K decided not to expose, activate, or link them;
  - the D7.3 trail is closable with no further action now.

## D7.4G-BRANCH-ARCHIVE-EXECUTE - Branch Archive And D7.4 Trail Closeout

- Execution mode:
  - archival of `recovery/d7-activity-versioning` as annotated reference;
  - documentation update only — no code, no DB, no apply, no SQL, no activation,
    no matrix link, no merge, no rebase.
- Initial state confirmed before execution:
  - branch `main`;
  - `HEAD=6a9bf2d9146c8a0011ddc3376c7fb842eebf7da6`;
  - `origin/main...main = 0 0`;
  - `origin/recovery...main = 0 1`;
  - `origin/main...origin/recovery = 1 0`;
  - `merge-base = b5aafa7605bab4f8ef4b61885ec5200627ea2f0b`;
  - tag `archive/d7-activity-versioning` did not exist;
  - `git status --short` was empty;
  - `database.db`: `528384` bytes;
    SHA256 `09C0791A00B9A6EAB3BABC7E8349E8582092ADE6EB911798CE55062819A48E1A`.
- Operations executed:
  1. `git tag archive/d7-activity-versioning b5aafa7605bab4f8ef4b61885ec5200627ea2f0b`
  2. `git push origin archive/d7-activity-versioning`
  3. `git push origin --delete recovery/d7-activity-versioning`
- Confirmations:
  - tag `archive/d7-activity-versioning` exists at remote:
    `b5aafa7605bab4f8ef4b61885ec5200627ea2f0b`;
  - `refs/heads/recovery/d7-activity-versioning` no longer exists on remote
    (ls-remote returned empty);
  - local branch `recovery/d7-activity-versioning` preserved at `b5aafa7` (`[gone]`);
    not deleted in this phase.
- `database.db` preserved throughout:
  - `528384` bytes;
  - SHA256 `09C0791A00B9A6EAB3BABC7E8349E8582092ADE6EB911798CE55062819A48E1A`.
- D7 trail status: all functional work is integrated into `main`. The
  `archive/d7-activity-versioning` tag is the permanent named reference to the
  D7 activity versioning trail endpoint.
- No further work is required on the D7.4 trail.

## D7.5C-COMMIT-CLOSEOUT - Matrix-Scoped Activity Creation

- Execution mode:
  - focused feature closeout only;
  - no new functionality beyond D7.5C;
  - no D7.5D implementation;
  - no push.
- Functional commit:
  - `bc8a4f6` - `Add matrix-scoped activity creation`.
- Delivered behavior:
  - generic `+ Nova atividade` button in the left-column header of the matrix
    edit screen;
  - identical flow in `Lista de AAC` and `Lista de AEU`;
  - modal/form opened from the matrix screen;
  - creation of legacy activity + `atividade_base` + `atividade_legacy_map`;
  - initial `atividade_versao` created in the same transaction;
  - `matriz_atividade_versao_item` created when `Adicionar à matriz atual` is checked.
- Contract preserved:
  - server infers the axis from the matrix tab/route;
  - matrix name is only a contextual UI label;
  - matrix name is not written into `codigo_normativo`;
  - `codigo_normativo` remains the norm/regulation code;
  - multiple compatible active norms require explicit choice;
  - there is no fallback to the first active norm;
  - rollback is total on intermediate failure;
  - POST is CSRF-protected;
  - no schema/migration;
  - no D7.5D card menu/version cloning yet.
- Validation:
  - user visually validated the live screen after implementation;
  - focused pytest rerun passed:
    - `python -m pytest tests/test_admin_matrizes.py tests/test_admin_matrizes_csrf_ui.py tests/test_admin_matriz_versao_link.py tests/test_admin_matrix_new_activity.py -q --tb=short`
    - result: `28 passed`.
- Files touched in the functional commit:
  - `main.py`
  - `templates/admin_matriz_form.html`
  - `tests/test_admin_matrix_new_activity.py`
- Next phase authorized after this closeout:
  - `D7.5D-PATCH-CARD-VERSION-MENU`.

## D7.5D-COMMIT-CLOSEOUT - Matrix Card Version Menu

- Execution mode:
  - focused feature closeout only;
  - no new functionality beyond D7.5D;
  - no D7.5E implementation;
  - no push.
- Functional commit:
  - `0dbd2b1` - `Add matrix card version creation`.
- Delivered behavior:
  - `⋮` button on right-column (selected/linked) activity cards in the matrix edit screen;
  - `Criar nova versão` action opens a modal with norma select;
  - context label `Versão nesta matriz: [codigo_normativo]` for orientation;
  - server creates or reuses `atividade_versao` respecting UNIQUE(atividade_base_id, norma_id);
  - only the current matrix is relinked; older matrices keep their original version link.
- R1 visual alert correction included:
  - `<p class="matriz-modal-warning">` replaced with
    `<div class="flash flash-warning" role="alert">`;
  - reuses system-wide style; no new CSS added.
- Contract preserved:
  - matrix name is only a contextual UI label;
  - matrix name is not written into `codigo_normativo`;
  - no in-place UPDATE of a version already used by older matrices or requests;
  - full rollback on intermediate failure;
  - POST is CSRF-protected;
  - no schema/migration;
  - no `database.db` edit in the closeout;
  - D7.5C not reopened.
- Validation:
  - user visually validated the live screen after implementation;
  - focused pytest rerun passed:
    - `python -m pytest tests/test_admin_matriz_nova_versao_card.py -q --tb=short`
    - result: `15 passed`.
- Files touched in the functional commit:
  - `main.py`
  - `templates/admin_matriz_form.html`
  - `tests/test_admin_matriz_nova_versao_card.py`
- Next phase authorized after this closeout:
  - `D7.5E-CARD-VERSION-BADGE-UI`.

## D7.6B2-SCHEMA-CLOSEOUT - Operational Version Numbers For atividade_versao

- D7.6B2 aprovada funcionalmente após R1 (DEFAULT fix) e R2 (index hardening + triggers).
- Commits aceitos:
  - `1ca00a3` — `Add operational activity version numbers`
  - `5184143` — `D7.6B2-R1: fix numero_versao DEFAULT 0 -> DEFAULT 1 in atividade_versao`
  - `6b1579a` — `D7.6B2-R2: harden numero_versao schema — full unique index + pos triggers`
- Backup R2:
  - `database.pre-D7.6B2-R2-hardening-20260613-184709.db`
  - 544.768 bytes
  - SHA256 `92627DED44C9094E74F01DA5718C995CD3FDD5AC467EF79298541A75B777CD8C`
- Testes aceitos:
  - `tests/test_atividade_versao_numero.py`: 12/12 passed (T01–T12).
  - Regressão D7 (4 arquivos): 45/45 passed.
- Schema final:
  - `numero_versao INTEGER NOT NULL DEFAULT 1` com `CHECK(numero_versao >= 1)` no DDL de bancos novos.
  - `UNIQUE INDEX idx_atividade_versao_base_num ON atividade_versao(atividade_base_id, numero_versao)` — não-parcial.
  - Triggers: `trg_atividade_versao_num_pos_insert` e `trg_atividade_versao_num_pos_update` protegem `database.db` existente.
- Helpers entregues em `main.py`:
  - `get_next_numero_versao(conn, base_id)`
  - `get_ultima_versao_ativa_por_base(conn, base_id)`
- Próxima fase técnica: `D7.6C` — Admin → Atividades cria nova versão operacional.
- O que NÃO fazer na próxima fase:
  - não criar versão pela matriz como fluxo principal;
  - não usar `codigo_normativo` como badge ou identificador principal;
  - não alterar schema sem nova auditoria;
  - não fazer push;
  - não misturar UI da matriz com UI de atividades;
  - não implementar D7.6D junto com D7.6C.

## D7.6C-COMMIT-CLOSEOUT - Activity Version Menu On Admin Activities List

- Execution mode:
  - focused feature closeout only;
  - no new functionality beyond D7.6C;
  - no D7.6D implementation;
  - no push.
- Functional commit:
  - `62aed4b` — `Add activity version menu to admin activities`.
- Delivered behavior:
  - botão ⋮ (`data-action="more"`) adicionado ao float bar de `/admin/atividades`;
  - dropdown `ativ-more-menu` com três ações:
    - `data-menu-action="edit"` → Editar atividade (rota existente);
    - `data-menu-action="nova-versao"` → Criar nova versão (`/admin/catalogo-versoes/<base_id>/nova-versao`);
    - `data-menu-action="ver-versoes"` → Ver versões (`/admin/catalogo-versoes/<base_id>`).
  - "Criar nova versão" e "Ver versões" ficam `disabled` quando `base_id` é vazio.
  - Posicionamento do dropdown via `requestAnimationFrame`; fecha ao clicar fora.
- Backend:
  - query de `admin_atividades` agora inclui:
    ```sql
    (SELECT atividade_base_id FROM atividade_legacy_map WHERE atividade_id_legacy = id) AS base_id
    ```
  - `base_id` exposto como `data-base-id` em cada card `.impresso-card`.
- Contract preserved:
  - ações "Ver" e "Editar" preexistentes mantidas no float bar;
  - `codigo_normativo` não exposto como identificador operacional na lista;
  - `UNIQUE(atividade_base_id, norma_id)` não reintroduzida;
  - `numero_versao` via `get_next_numero_versao` preservado para inserções futuras;
  - nenhum template da matriz alterado;
  - schema e `database.db` intocados;
  - push não realizado.
- Validation:
  - focused pytest:
    - `python -m pytest tests/test_admin_atividades_version_menu.py -q --tb=short`
    - result: `9 passed`.
  - regression suite (5 files):
    - `python -m pytest tests/test_atividade_versao_numero.py tests/test_matriz_versao_contract.py tests/test_admin_matriz_versao_link.py tests/test_admin_matrix_new_activity.py tests/test_admin_matriz_nova_versao_card.py -q --tb=short`
    - result: `57 passed`.
- Files touched in the functional commit:
  - `main.py`
  - `templates/admin_atividades.html`
  - `tests/test_admin_atividades_version_menu.py`
- Next phase authorized after this closeout:
  - `D7.6D` — Matriz escolhe versão e card mostra vN.

## D7.6D-COMMIT-CLOSEOUT - Matrix Chooses Operational Activity Version

- Execution mode:
  - focused feature closeout only;
  - no new functionality beyond D7.6D;
  - no D7.6E implementation;
  - no push.
- Functional commit:
  - `2f81179` — `Make matrix choose operational activity versions`.
- Delivered behavior:
  - card da matriz exibe badge `vN` (ex.: `v1`, `v2`, `v3`) baseado em `atividade_versao.numero_versao`;
  - botão ⋮ abre modal reformulado que lista versões existentes da mesma `atividade_base` em ordem decrescente;
  - versão atual da matriz aparece pré-selecionada (`is_current: true`) via radio buttons;
  - `codigo_normativo` aparece no modal como metadado secundário, nunca como badge principal;
  - POST de escolha aceita `versao_id` (não mais `norma_id`); valida que a versão pertence à mesma `atividade_base`; relinka apenas a matriz atual via `_set_versao_da_matriz_para_base`;
  - POST não executa `INSERT INTO atividade_versao`; nenhuma versão nova é criada pela matriz;
  - POST rejeita `versao_id` de base diferente, `versao_id` inexistente e `versao_id` ausente.
- Contract preserved:
  - Admin → Atividades cria versão; Matriz apenas escolhe versão existente;
  - `templates/admin_atividades.html` não alterado;
  - schema e `database.db` não alterados;
  - `codigo_normativo` não é badge ou identificador principal;
  - CSRF obrigatório no POST;
  - rollback total em erro intermediário;
  - push não realizado.
- Validation:
  - focused pytest (novo):
    - `python -m pytest tests/test_admin_matriz_escolher_versao.py -q --tb=short`
    - result: `10 passed`.
  - focused pytest (atualizado):
    - `python -m pytest tests/test_admin_matriz_nova_versao_card.py -q --tb=short`
    - result: `13 passed`.
  - regression suite (6 files):
    - `python -m pytest tests/test_atividade_versao_numero.py tests/test_admin_atividades_version_menu.py tests/test_matriz_versao_contract.py tests/test_admin_matriz_versao_link.py tests/test_admin_matrix_new_activity.py tests/test_admin_matriz_nova_versao_card.py -q --tb=short`
    - result: `64 passed`.
- Files touched in the functional commit:
  - `main.py` (M)
  - `templates/admin_matriz_form.html` (M)
  - `tests/test_admin_matriz_escolher_versao.py` (A — novo)
  - `tests/test_admin_matriz_nova_versao_card.py` (M — semântica D7.6D)
- Next phase authorized after this closeout:
  - `D7.6E` — garantir que nova matriz / atividade adicionada usa a última versão ativa por padrão.

## Recent Commits

- `95cb897` - Add admin transition history for activity versions
- `cbde400` - Record D7.3A normative canonization
- `5f66239` - Add D7.3C canonical normative fixture and docs closeout
- `45dd39d` - Add D7.3D normative dry-run importer
- `f10db80` - Record D7.3E fixture database convergence diagnostic
- `da869e9` - Record D7.3F reconciliation matrix decisions
- `ecdc9f5` - Add D7.3H controlled reconciliation apply script
- `aedf936` - Record D7.3I apply copy validation
- `b8ad2ae` - Record D7.3J live draft creation and stabilize tests
- `b5aafa7` - Record D7.3K matrix link decision
- `6a9bf2d` - Update CSRF inventory artifacts after D7 merge (pre-D7.5C main baseline)
- `bc8a4f6` - Add matrix-scoped activity creation
- `cdbc7ab` - Record D7.5C matrix activity creation closeout
- `0dbd2b1` - Add matrix card version creation
- `3d3c4ff` - Record D7.5D matrix card version closeout
- `1ca00a3` - Add operational activity version numbers
- `5184143` - D7.6B2-R1: fix numero_versao DEFAULT 0 -> DEFAULT 1 in atividade_versao
- `6b1579a` - D7.6B2-R2: harden numero_versao schema — full unique index + pos triggers
- `62aed4b` - Add activity version menu to admin activities
- `ed706c1` - Record D7.6C activity version menu closeout
- `2f81179` - Make matrix choose operational activity versions

## Risks To Keep In View

- Critical:
  - overwriting versions already used in matrix or versioned requests;
  - reconciling `PROJETOS_EXTENSAO` without preserving the live split.
- High:
  - mapping `VISITAS_TECNICAS_PROFESSORES` to `base6`;
  - changing `NRM-RT` runtime items;
  - promoting the dry-run importer into a real apply path.
- High:
  - broadening beyond the single completed `CREATE_DRAFT` path for `VISITAS_TECNICAS_PROFESSORES`;
  - activating or matrix-linking versions `61/62` without a separate authorization phase.
- Medium:
  - structural divergences in group / workload / limits;
  - fixture does not cover all persisted transition history.
- Low:
  - textual divergences when IDs and persisted history are preserved.
- Residual backlog:
  - `documentacao_exigida` is only validated when the key exists in the fixture tool;
  - `atividade_transicao` still has no DB-level UNIQUE on `(from, to, tipo)`.

## Recommended Next Step

- `D7.6E` — Garantir que nova matriz / atividade adicionada usa a última versão ativa por padrão.
- D7.6D está completa: card mostra `vN`, modal lista versões, POST relinka sem criar versão.
- Contrato permanente estabelecido: Admin → Atividades cria versão; Matriz escolhe versão.
- `codigo_normativo` é metadado secundário; não usar como badge ou identificador operacional.
- Não alterar schema sem nova auditoria explícita.
- Não fazer push.

## Instructions For The Next Agent

- Read `PROJECT_STATE.md` and `AGENT_HANDOFF.md` before any action.
- Start from `main`; D7.5C functional state is commit `bc8a4f6`.
- Treat `atividade_id` as the operational source of truth.
- `database.db` is already in the post-D7.3J state; do not assume pre-apply live.
- There is no active feature branch for D7 on the remote. Any new work must start
  from `main` at `6a9bf2d`. Do not reference or attempt to push to
  `recovery/d7-activity-versioning`.
- The archive tag `archive/d7-activity-versioning` at `b5aafa7` is the permanent
  reference to the D7 trail endpoint — treat it as read-only history.
- Local branch `recovery/d7-activity-versioning` may still exist as `[gone]` and
  should be treated as a stale local ref only; do not work from it.
- Do not attempt any additional real import, reconciliation write, or importer `apply` against `database.db`.
- `PROJETOS_EXTENSAO` is no longer open for semantic collapse: preserve the live split.
- `VISITAS_TECNICAS_PROFESSORES` must not be mapped to `base6`.
- `VISITAS_TECNICAS_PROFESSORES` must not be forced into `base7` either.
- The only admitted live write path in D7.3 was the now-completed `CREATE_DRAFT` for `VISITAS_TECNICAS_PROFESSORES`.
- Versions `61/62` already exist in `rascunho` and remain unlinked to matrix.
- D7.5C is complete and visually validated; do not reopen it unless a concrete
  regression is found.
- D7.5D is complete (commit `0dbd2b1`); do not reopen it unless a concrete
  regression is found.
- D7.6B2 is complete (commits `1ca00a3`, `5184143`, `6b1579a`); schema is hardened; do not reopen.
- `atividade_versao.numero_versao` is the operational version number (v1/v2/v3… per base).
- `codigo_normativo` is normative metadata; do not use it as a badge or operational identifier.
- `UNIQUE(atividade_base_id, norma_id)` no longer exists; do not reference or recreate it.
- `UNIQUE(atividade_base_id, numero_versao)` is the active uniqueness constraint (full index, no WHERE).
- All INSERTs into `atividade_versao` must supply `numero_versao` via `get_next_numero_versao`.
- Do not insert `numero_versao <= 0`; it is blocked by triggers and by CHECK in new DB DDL.
- `norma_id` and `codigo_normativo` remain `NOT NULL` in this phase.
- D7.6C is complete (commit `62aed4b`):
  - `/admin/atividades` now exposes a ⋮ menu on hover with Editar / Criar nova versão / Ver versões.
  - `base_id` is resolved via `atividade_legacy_map` subquery in the activities query.
  - Activities without `base_id` do not generate invalid links.
  - No matrix templates were changed; no schema was changed.
- D7.6D is complete (commit `2f81179`):
  - Card da matriz exibe badge `vN` via `atividade_versao.numero_versao`.
  - Modal lista versões existentes da mesma `atividade_base`; versão atual pré-selecionada.
  - POST relinka via `_set_versao_da_matriz_para_base`; não cria `atividade_versao`.
  - POST valida `versao_id` pertencente à mesma `atividade_base`; rejeita cross-base e inexistentes.
  - `templates/admin_atividades.html` não alterado. Schema e `database.db` intocados.
  - `tests/test_admin_matriz_escolher_versao.py` (novo, 10 testes) e `tests/test_admin_matriz_nova_versao_card.py` (atualizado, 13 testes) aceitos.
- Contrato permanente pós-D7.6D:
  - Admin → Atividades cria versão; Matriz escolhe versão existente.
  - Card da matriz mostra `vN`; `codigo_normativo` é metadado secundário.
  - Não reintroduzir criação de versão pela matriz como fluxo principal.
  - Não usar `AAC-rev5`/`AAC-rev6` como badge principal.
- D7.6E is the next authorized feature scope:
  - garantir que nova matriz / atividade adicionada usa a última versão ativa por padrão;
  - do not alter schema without a new explicit audit;
  - do not implement D7.6E alongside any other major feature.
- Runtime `NRM-RT*` items remain outside fixture reconciliation.
- Never overwrite versions already used in matrix or versioned requests.
- No next agent should activate, matrix-link, remap legacy scope, or perform any additional live apply without a new explicit authorization phase and real operational need.
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
