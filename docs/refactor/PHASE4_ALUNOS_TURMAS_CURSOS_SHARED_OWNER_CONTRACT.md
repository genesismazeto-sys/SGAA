# PHASE 4-B6-P — Alunos/Turmas/Cursos neutral shared-owner contract

Date: 2026-08-04
Status: **IMPLEMENTED / AWAITING SUPERVISOR REVIEW** (must never become CLOSED /
ACCEPTED; publication permitted only after an independent read-only review PASS,
bounded gates, selective per-path staging and a live-remote race check; technical
publication, when completed, does not constitute external supervisor acceptance;
post-publication next action is external supervisor review)

## Status and authority

PHASE 4-B5: **CLOSED / ACCEPTED** (published; immutable prerequisite history).
PHASE 4-B6-A: **DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED**.
PHASE 4-B6-P: **IMPLEMENTED / AWAITING SUPERVISOR REVIEW** and must never
become CLOSED / ACCEPTED.
PHASE 4-B6: **NOT AUTHORIZED**. PHASE 4 remains **OPEN / INCREMENTAL
IMPLEMENTATION** and is not closed. Phase 5 and Phase 6 are **NOT AUTHORIZED**.
Migration v4 is **PROHIBITED**. No commit SHA is invented here; the
authorized subject is `Extract B6 shared neutral owners` and its commit and
publication identity resolves through Git history.

This unit is only the neutral shared-owner prerequisite for the future
Alunos/Turmas/Cursos cohort. **B6 Alunos/Turmas/Cursos blueprint extraction is
NOT AUTHORIZED and no route moved.** `app/views/admin/alunos_turmas_cursos.py`
remains absent.

## B6-A diagnosis (read-only prerequisite diagnosis)

The B6-A diagnosis and supervisor correction identified exactly the nine shared
symbols below and **excluded `periodo_corrente`**, which remains local in `main`
and is AST-identical to parent. No route, factory, endpoint, RBAC, CSRF or schema
movement was diagnosed for B6-P. DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE
REQUIRED.

## Baseline and candidate parent (required)

- Repository: `genesismazeto-sys/SGAA`.
- Branch: `refactor/architecture-safety-net`.
- Parent (required): `1bf5173949b0bf0bdce15d1b87d6ed15d535158c`
  (`Record acceptance of Phase 4-B5`). This is also the live remote HEAD.
- Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`.
- Pre-publication freeze fact (preserved): at freeze, the candidate was NOT
  committed and NOT pushed; the authorized subject is `Extract B6 shared neutral
  owners`, and commit and publication identity resolves through Git history. No
  SHA is invented here.

## Ownership: exact nine-symbol closure, neutral owners 3/5/1

Exactly 9 shared symbols moved to neutral owners:

- `app.academics` (3): `build_turma_aluno_matricula`,
  `resequence_turma_aluno_matriculas`, `resequence_turma_aluno_matriculas_for_ids`.
- `app.user_accounts` (5): `_access_defaults_map`,
  `_default_password_for_user_type`, `create_usuario_with_default_access`,
  `create_usuario_with_default_password`, `normalize_usuario_access_for_user_type`.
- `app.web.request` (1): `_is_ajax_request`.

`main.py` has **zero local bodies** for the nine symbols; it directly imports and
re-exports all nine by identity, with no wrappers or aliases. All nine moved
bodies are **AST-equivalent to parent `1bf5173949b0bf0bdce15d1b87d6ed15d535158c:main.py`**
with no redesign; no behavioral, signature, default or error-path change was
introduced.

`periodo_corrente` remains local in `main`, unchanged and AST-identical to parent.

## Consumer resolution

- `app.views.core` imports `normalize_usuario_access_for_user_type` directly from
  `app.user_accounts`.
- The residual lazy map in `core._get_main_helpers` remains exactly
  `aluno_url` / `get_db_connection` / `logger`.
- The `login` flow `normalize_usuario_access_for_user_type(...) ->
  conn.commit() -> refreshed SELECT` is preserved.
- Acesso consumers and `_admin_access_denied_response` (uses the canonical
  `_is_ajax_request`) are preserved.

## Import isolation and transaction neutrality

- Isolated imports of the three owners do not import `main`; no new owner →
  `main` edge or cycle exists.
- `app.auth` / `app.db_maintenance` do not import `app.user_accounts`.
- No route, factory, endpoint, RBAC, CSRF, message or schema ownership moved.
- Transaction neutrality is preserved: no commit, rollback, close or connection
  replacement was added.

## B6-P-R1 literal record

`PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED /
MESSAGE_SCANNER_OWNER_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY`.

- R1 added `utils/messages.py` to production scope and exactly
  `PROJECT_ROOT / "app" / "academics.py"` to `_iter_backend_files()`;
  no recursive `app/**/*.py`, no `app/user_accounts.py`, no `app/web/request.py`,
  no hashing/normalization/sink/frontend/template/static/DB/editable/display/
  context change.
- Regression RED before fix: catalog 535, key `msg_4642b1608cf6a126` absent;
  GREEN after fix: catalog 536, key present, exact default
  `"Turma sem código para gerar matrícula."`, source `app/academics.py`,
  no duplicate.
- Scanner provenance preserved literally: the moved `ValueError` message
  usage/source owner changed from `main.py` to `app/academics.py` (because the
  raising `build_turma_aluno_matricula` body moved there), while key
  `msg_4642b1608cf6a126` and the exact default text remained unchanged — the
  message itself did not change.
- Discrimination was an in-memory monkeypatch filtering `app/academics.py`,
  proving 535/key absent, then restoring the real callable/cache; final bytes
  retain the entry.

## B6-P-R3 literal record

`PRE_REVIEW_SCOPE_EXPANSION / ONE_FOR_ONE_TEST_POOL_SUBSTITUTION_PLUS_FOUR_ADDITIONS /
STALE_GOVERNANCE_TEST_RECONCILIATION / MESSAGE_SCANNER_ALLOWLIST_RECONCILIATION /
NO_RETROACTIVE_GENERIC_AUTHORITY`.

- `tests/test_residual_shared_helpers.py` lost mutation authority and remained
  unchanged gate-only; five paths were explicitly added; the final exact mutable
  test pool is the six test paths in the actual dirty manifest.
- First full result exposed four preexisting stale governance assertions plus one
  R1-caused scanner allowlist assertion: 1061 passed, 5 failed, 17 deselected,
  410.35s, canonical opens 0, physical state identical.
- Exact five-node recovery passed 5/5 in 1.06s.
- Coupled five-file lane passed 77/77 in 11.26s.
- Fresh final full: collected 1083 = 1066 passed + exactly 17 deselected,
  0 failed, 0 errors, 328.77s, exit 0, `CANONICAL_SQLITE_OPENS=0`, physical
  before/after candidate snapshot identical.
- The five R3 test corrections are mechanical only: current-state stale assertions
  and explicit `app/academics.py` allowlist; historical technical assertions,
  route/RBAC/schema/transaction behavior remain intact.

## Historical TDD / scanner-owner chronology (preserved, not rewritten)

- Initial structural RED: `13 failed / 31 passed` (owner modules absent; `main`
  still owned the nine bodies).
- Initial structural GREEN: `44 passed` (exact nine shared symbols moved, neutral
  owners 3/5/1).
- Historical focused lane: `203 passed / 2 failed`, both failures scanner-owner
  expectations (message catalog RED at 535, key `msg_4642b1608cf6a126` absent);
  the R1 scanner-owner reconciliation added exactly
  `PROJECT_ROOT / "app" / "academics.py"` to `_iter_backend_files()` and brought
  the catalog to 536 with the exact default
  `"Turma sem código para gerar matrícula."`.
- These historical failures are retained as phase-time evidence and are not
  claimed to have never happened.

## Earlier focused qualification

- Accepted focused qualification: collected/passed 206, failed 0, errors 0,
  117.65s, exit 0.
- The first failed harness attempt (206 passed but exit 1) was a recoverable
  basetemp path translation defect (MSYS `/c` interpreted by native Windows
  Python as `D:/c`); rerun with native `C:/` path passed with identical physical
  state.
- Exact R1 CSRF nodes passed 2/2, snapshot bytes unchanged, B6-P CSRF delta
  `[0,0]`.

## Invariants

- Routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC
  unmapped 0.
- Actor matrix 402 = 263 allowed + 139 denied.
- Message catalog 536.
- Route inventory byte-identical: 20814 bytes, SHA-256
  `6e32148cd1988d5e405c9d11bdbda285359f72d5fc7eca8bd5ef8da9b83049fa`.
- CSRF shadow-off and shadow-on byte-identical and equal to each other: each
  288509 bytes, SHA-256
  `4b16f1b4a1e672807398f33fb626f073e29ada5e9453675eabe5c824a7eec769`.
- Canonical database: 544768 bytes, SHA-256
  `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`;
  WAL/SHM/journal absent; canonical SQLite opens 0.
- Protected residual: 17420 bytes, SHA-256
  `7388cfbc8f446410ef3c98ec0fa274c2c36ff4f3ef8ed2cd649bb1f3e1d3bb0e`.

## Authorized ceiling and exact manifest (18 paths; path 19 hard stop)

Authorized ceiling after R3: production 6, tests 6, governance 6, total 18;
path 19 hard stop.

Actual non-governance dirty manifest is exactly 12 paths:
- Production (6): `app/academics.py`, `app/user_accounts.py`, `app/web/request.py`,
  `app/views/core.py`, `main.py`, `utils/messages.py`.
- Tests (6): `tests/test_phase4_alunos_turmas_cursos_shared_owners.py`,
  `tests/test_phase3_schema_startup_transaction_contract.py`,
  `tests/test_phase4_atividades_blueprint.py`,
  `tests/test_phase4_configuracoes_blueprint.py`,
  `tests/test_phase4_requisicoes_shared_owners.py`,
  `tests/test_phase4_versioning_subsystem.py`.

Governance (6):
- `AGENT_HANDOFF.md`
- `PROJECT_STATE.md`
- `docs/DOCUMENTATION_INDEX.md`
- `docs/mapeamento/05_avaliacao_refactor.md`
- `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
- `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_SHARED_OWNER_CONTRACT.md` (new, this
  closeout)

Adding the exact six governance documents yields exactly 18 changed paths.
`tests/test_residual_shared_helpers.py` remains unchanged and is a read-only gate,
not a changed path. This documentary delta changes no production, test, snapshot
or database path.

## Irreversible boundaries

- Repository mutation: crossed only for the exact production/test/governance
  manifest above.
- Pre-publication freeze fact (preserved): at freeze, the candidate was NOT
  staged, NOT committed and NOT pushed.
- No Alunos/Turmas/Cursos route moved; `app/views/admin/alunos_turmas_cursos.py`
  remains absent; B6 blueprint extraction remains NOT AUTHORIZED.
- No canonical SQLite opening, test execution or Git mutation occurred in this
  closeout.

## Final current status

`PHASE4_B6_P_IMPLEMENTED / AWAITING_SUPERVISOR_REVIEW / EXACT_NINE_SHARED_SYMBOLS /
NEUTRAL_OWNERS_3_5_1 / MAIN_IDENTITY_REEXPORTS_PRESERVED /
ZERO_LOCAL_MAIN_BODIES_FOR_NINE / CORE_DIRECT_IMPORT_REDUCTION /
RESIDUAL_LAZY_MAP_ALUNO_URL_DB_LOGGER / PERIODO_CORRENTE_LOCAL_AST_IDENTICAL /
TRANSACTION_NEUTRALITY_PRESERVED / ZERO_ROUTE_MOVEMENT /
B6_ROUTE_EXTRACTION_NOT_AUTHORIZED / ROUTES_131 / ENDPOINTS_130 /
BUSINESS_PAIRS_160 / GOVERNED_PAIRS_134 / RBAC_UNMAPPED_ZERO /
ACTOR_402_263_139 / MESSAGE_CATALOG_536 / ROUTE_INVENTORY_BYTE_IDENTICAL /
CSRF_SHADOWS_BYTE_IDENTICAL / FULL_HERMETIC_1066_17 /
CANONICAL_SQLITE_OPENS_ZERO /
TECHNICAL_REVIEW_AND_PUBLICATION_GOVERNED_BY_GIT_EVIDENCE /
EXTERNAL_SUPERVISOR_ACCEPTANCE_PENDING`.

PHASE 4 remains OPEN / INCREMENTAL IMPLEMENTATION. PHASE 4-B6 is NOT AUTHORIZED;
Phase 5 and Phase 6 are NOT AUTHORIZED; Migration v4 is PROHIBITED.

## Publication gate (stable process wording)

IAsup freezes/adjudicates the 18-path candidate and obtains an independent Flash
FREE-first read-only review. Publication is permitted only after that review
PASS, bounded gates, selective per-path staging and a live-remote race check
against parent `1bf5173949b0bf0bdce15d1b87d6ed15d535158c`. The authorized subject
is `Extract B6 shared neutral owners`; commit and publication identity resolves
through Git history. Technical publication, when completed, does not constitute
external supervisor acceptance; the post-publication next action is external
supervisor review. B6 remains NOT AUTHORIZED; protected `main` remains
`340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`.
