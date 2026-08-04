# PHASE 4-B6 — Alunos/Turmas/Cursos admin blueprint contract

Date: 2026-08-04
Status: **CLOSED / ACCEPTED — GOVERNANCE CLOSEOUT PUBLISHED**

## 1. Status and authority

- PHASE 4-B6-P: **CLOSED / ACCEPTED**.
- PHASE 4-B6-R1: **CLOSED / ACCEPTED** as incorporated supervisor correction.
- PHASE 4-B6: **CLOSED / ACCEPTED**.
- PHASE 4: **OPEN / INCREMENTAL IMPLEMENTATION**; it is not closed.
- Phase 5: **NOT AUTHORIZED**.
- Phase 6: **NOT AUTHORIZED**.
- Migration v4: **PROHIBITED**.
- Arquivos / Alertas / Reportes are not included and must not begin under this contract.

This contract records the accepted, published Phase 4-B6 blueprint. Technical commit `3d9660a99e6944ff94a3991a353ecf3aaf300987`, subject `Extract admin alunos turmas cursos blueprint`. Technical publication: **COMPLETE**. Post-publication verification: **COMPLETE**. External supervisor acceptance: **GRANTED**. Governance closeout: published by R3.

## 2. Baseline, branch and publication boundary

- Repository: `genesismazeto-sys/SGAA`.
- Workspace: `D:\OneDrive\Programação\SGAA_clean_baseline`.
- Branch: `refactor/architecture-safety-net`.
- Accepted technical commit: `3d9660a99e6944ff94a3991a353ecf3aaf300987`,
  subject `Extract admin alunos turmas cursos blueprint`.
- Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`.
- Technical publication: **COMPLETE**.
- Post-publication verification: **COMPLETE**.
- External supervisor acceptance: **GRANTED**.
- Governance closeout: being published by this R3 commit.

## 3. Supervisor R1 correction — `periodo_corrente`

The original B6 ownership contract was contradictory: three B6 handlers passed
`periodo_corrente` as dead template context while the function had to remain exclusively
main-local for the legitimate non-B6 consumer `_build_admin_dashboard_turma_cards`, and
`app -> main` was prohibited.

The supervisor corrected only that contradiction under:

`SUPERVISOR_CONTRACT_CORRECTION / NO_PATH_POOL_EXPANSION /
NO_DOMAIN_SCOPE_EXPANSION / DEAD_TEMPLATE_CONTEXT_REMOVAL_ONLY`.

Repository-wide inspection proved zero `periodo_corrente` references in `templates/**`.
Exactly these three dead `render_template` keyword arguments were removed:

1. `admin_detalhes_curso`: `periodo_corrente=periodo_corrente`;
2. `admin_turmas`: `periodo_corrente=periodo_corrente`;
3. `admin_detalhes_turma`: `periodo_corrente=periodo_corrente`.

No fourth removal or body change is accepted. `periodo_corrente` remains defined only in
`main.py`, byte/AST-identical to baseline, and `_build_admin_dashboard_turma_cards` still
resolves and calls it. The new B6 module contains no binding, alias, import, copy, wrapper
or injection for `periodo_corrente`.

## 4. Canonical owner and exact route cohort

`app.views.admin.alunos_turmas_cursos` is the canonical owner. It defines:

- blueprint object `bp_admin_alunos_turmas_cursos`;
- blueprint name `admin_alunos_turmas_cursos_blueprint`;
- immutable `LEGACY_ROUTE_SPECS` configured through the accepted
  `LegacyRouteSpec` / `configure_legacy_routes` registrar;
- exactly **17 global legacy endpoints / 24 route-method pairs**;
- exactly **10 route-private helpers**.

### Exact 17 endpoints / 24 pairs

| Endpoint | Rule | Methods |
|---|---|---|
| `admin_cursos` | `/admin/cursos` | GET |
| `admin_adicionar_curso` | `/admin/cursos/adicionar` | GET, POST |
| `admin_editar_curso` | `/admin/cursos/<int:curso_id>/editar` | GET, POST |
| `admin_detalhes_curso` | `/admin/cursos/<int:curso_id>` | GET |
| `admin_visualizar_curso` | `/admin/cursos/<int:curso_id>/visualizar` | GET |
| `admin_deletar_curso` | `/admin/deletar_curso/<int:curso_id>` | POST |
| `admin_alunos` | `/admin/alunos` | GET |
| `admin_adicionar_aluno` | `/admin/adicionar_aluno` | GET, POST |
| `admin_editar_aluno` | `/admin/editar_aluno/<int:usuario_id>` | GET, POST |
| `admin_deletar_aluno` | `/admin/deletar_aluno/<int:usuario_id>` | POST |
| `admin_alterar_status_alunos` | `/admin/alterar_status_alunos` | POST |
| `admin_turmas` | `/admin/turmas` | GET |
| `admin_adicionar_turma` | `/admin/adicionar_turma` | GET, POST |
| `admin_editar_turma` | `/admin/editar_turma/<int:turma_id>` | GET, POST |
| `admin_deletar_turma` | `/admin/deletar_turma/<int:turma_id>` | POST |
| `admin_detalhes_turma` | `/admin/turma/<int:turma_id>` | GET |
| `admin_turmas_importar` | `/admin/turmas/importar` | GET, POST |

There is no eighteenth endpoint and no twenty-fifth route-method pair.

### Exact ten helpers

1. `resolve_existing_aluno_by_identifiers`;
2. `_matrizes_by_curso`;
3. `_resolve_turma_matriz_id`;
4. `_periodo_label_for_turma_row`;
5. `_turma_effective_matriz_label`;
6. `validar_codigo_curso`;
7. `semestre_atual_hoje`;
8. `proximo_numero_turma_por_curso`;
9. `curso_mais_populoso_id`;
10. `_safe_return_to_target`.

No eleventh helper is accepted.

## 5. Body equivalence, compatibility and imports

- All ten helper bodies are literally AST-identical to
  `cab4c61bdf7a1eef361a80f426dda558b11e9201:main.py`.
- All 17 handler bodies are equivalent to that baseline modulo removal of `@app.route`
  decorators and only the exact three R1 dead-context keyword deletions.
- `@admin_required` is preserved.
- `main.py` has zero local B6 handler/helper bodies and re-exports all 27 moved symbols by
  identity.
- No `@bp.route`, namespaced alias, duplicate route, compatibility wrapper, `import main`,
  dynamic import or `sys.modules` bridge exists.
- There is zero `app -> main` edge.

The accepted B6-P neutral owners remain canonical and are consumed directly:

- `app.academics`: `build_turma_aluno_matricula`,
  `resequence_turma_aluno_matriculas`,
  `resequence_turma_aluno_matriculas_for_ids`;
- `app.user_accounts`: `_access_defaults_map`, `_default_password_for_user_type`,
  `create_usuario_with_default_access`, `create_usuario_with_default_password`,
  `normalize_usuario_access_for_user_type`;
- `app.web.request`: `_is_ajax_request`.

## 6. Factory, legacy registrar and RBAC

`app.create_app` exposes keyword-only
`register_admin_alunos_turmas_cursos_blueprint: bool = True`. Default registration adds
exactly the B6 cohort through the accepted legacy registrar; explicit `False` removes
exactly that cohort. Independent app instances remain isolated. Endpoint and rule/method
collisions fail atomically.

RBAC is frozen for all 24 route-method pairs at exactly:

- VIEW: 6;
- EDIT: 13;
- FULL: 5.

`app/auth.py` is unchanged. No route, rule, method, endpoint or RBAC semantic delta is
accepted.

## 7. CSRF contract and historical cumulative reconciliation

The generated shadow-off and shadow-on artifacts are preserved without regeneration after
their qualified byte-identical second generation. Against B6 parent `cab4c61...`, each has
exactly **11 B6 owner-only deltas** and zero non-owner or unexpected route delta.

Historical cumulative partitions are exact and exhaustive in both shadows:

- Requisições local contribution: 5;
- Matrizes local contribution: 8;
- B6 local contribution: 11;
- Matrizes contract comparison: `8 + 11 = 19` owner-only deltas;
- Requisições contract comparison: `5 + 8 + 11 = 24` owner-only deltas.

The corrected Matrizes and Requisições assertions preserve exact equality, all non-owner
checks and endpoint restrictions. They do not use `>=`, subset-only acceptance, generic
owner broadening or arbitrary extra deltas.

## 8. Test chronology — preserved truthfully

- Original RED: collected 25; passed 6; failed 19; errors 0; collection errors 0.
- Primary GREEN: 28 passed.
- Hermetic CSRF regeneration: 2 passed; `CANONICAL_SQLITE_OPENS=0`; second regeneration
  byte-identical; exactly 11 B6 owner-only deltas.
- Expanded focused lane: 254 passed; `CANONICAL_SQLITE_OPENS=0`.
- Initial full hermetic: 1093 passed; 2 failed; 17 deselected;
  `CANONICAL_SQLITE_OPENS=0`. The exact failures were stale cumulative CSRF expectations in
  `tests/test_phase4_matrizes_blueprint.py` and
  `tests/test_phase4_requisicoes_blueprint.py`.
- R2 direct requalification of those two corrected tests: collected 2; passed 2; failed 0;
  errors 0; duration 1.08s; exit 0; `CANONICAL_SQLITE_OPENS=0`.
- R2 structural/global lane: collected 34; passed 34; failed 0; errors 0; duration 1.29s;
  exit 0; `CANONICAL_SQLITE_OPENS=0`.
- Pre-freeze full hermetic: collected 1112; selected/passed 1095; deselected exactly 17;
  failed 0; errors 0; duration 433.87s; exit 0; `CANONICAL_SQLITE_OPENS=0`.
- The selective-staging whitespace gate exposed five copied trailing-space lines. The first
  bounded cleanup removed two syntactic spaces but also changed three SQL string constants;
  the post-review/full gate simultaneously exposed the B1 ledger-row compatibility regression.
  That recovery full is preserved truthfully: 1093 passed; 2 failed; 17 deselected; the failures
  were B6 AST literal equivalence and B1 governance compatibility, not CSRF.
- Final bounded correction: the three SQL-string spaces are represented as source `\x20`, the
  two syntactic trailing spaces remain removed, and canonical `| Fase 4 |` ledger wording is
  restored. Both focused recovery nodes passed. Repeated final full: collected 1112; passed
  1095; deselected exactly 17; failed 0; errors 0; duration 318.06s; exit 0;
  `CANONICAL_SQLITE_OPENS=0`.

The historical 1093/2/17 result is not rewritten as if it never occurred.

## 9. Global invariants and physical custody

- Routes: 131.
- Endpoints: 130.
- Business route-method pairs: 160.
- Governed pairs: 134.
- RBAC unmapped: 0.
- Actor matrix: 402 = 263 allowed + 139 denied.
- Message catalog: 536.
- Route inventory: 20814 bytes; SHA-256
  `6e32148cd1988d5e405c9d11bdbda285359f72d5fc7eca8bd5ef8da9b83049fa`.
- Canonical `database.db`: 544768 bytes; SHA-256
  `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`;
  WAL/SHM/journal absent; canonical SQLite opens 0.
- Protected residual: 17420 bytes; SHA-256
  `7388cfbc8f446410ef3c98ec0fa274c2c36ff4f3ef8ed2cd649bb1f3e1d3bb0e`.

The final full run left the ten-path technical/test candidate manifest, index, route
inventory, database, residual and runtime-root custody unchanged.

## 10. Exact authorized candidate manifest

### Production — 3

1. `app/views/admin/alunos_turmas_cursos.py`;
2. `app/__init__.py`;
3. `main.py`.

### Tests/artifacts — 7

4. `tests/test_phase4_alunos_turmas_cursos_blueprint.py`;
5. `tests/test_phase4_alunos_turmas_cursos_shared_owners.py`;
6. `tests/test_phase4_configuracoes_blueprint.py`;
7. `tests/_artifacts/csrf_inventory_shadow_off.json`;
8. `tests/_artifacts/csrf_inventory_shadow_on.json`;
9. `tests/test_phase4_matrizes_blueprint.py`;
10. `tests/test_phase4_requisicoes_blueprint.py`.

The last two paths are the explicit post-initial-full scope expansion for exact cumulative
CSRF reconciliation.

### Governance — 6

11. `PROJECT_STATE.md`;
12. `AGENT_HANDOFF.md`;
13. `docs/DOCUMENTATION_INDEX.md`;
14. `docs/mapeamento/05_avaliacao_refactor.md`;
15. `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`;
16. `docs/refactor/PHASE4_ALUNOS_TURMAS_CURSOS_BLUEPRINT_CONTRACT.md`.

Technical/test ceiling 10; governance ceiling 6; absolute candidate ceiling 16. Path 17 is
a hard stop.

## 11. Execution and recovery evidence

- IAsup/orchestrator and R2 direct reconciliation, adjudication, deterministic gates and Git:
  Hermes `openai-codex/gpt-5.6-sol`.
- Initial RED delegation requested `flash_free`; provider/model
  `opencode` / `opencode/deepseek-v4-flash-free`; session
  `ses_032652d85ffeDWcqx0kaCy6OFg`; cost 0; exit 1; technical execution failure.
- Explicit permitted fallback: `FALLBACK_FREE_EXECUTION_FAILURE`; provider/model
  `opencode-go` / `opencode-go/deepseek-v4-flash`; session
  `ses_0325fd6beffeObTU6RTDl3L8i7`; cost `0.001052156`; exit 0; no Pro/Luna/Sol
  delegation.
- R2 was executed directly because the candidate already existed, state reconciliation and
  test-diff adjudication depended on accumulated evidence, and delegating would fragment
  context and increase mutation/revalidation risk.
- Recovered verifier defect: the first custom read-only CSRF partition verifier failed due
  to its own assertion implementation; no candidate mutation occurred. A diagnostic and
  corrected read-only verifier proved exact 11, 19 and 24 partitions with zero non-owner or
  unexpected delta.
- No hard stop was triggered in R2. No fallback beyond the documented initial route was
  used by R2.

## 12. Current decision

`PHASE4_B6_CLOSED / ACCEPTED / ALUNOS_TURMAS_CURSOS_BLUEPRINT_ESTABLISHED /
EXACT_17_ENDPOINTS / EXACT_24_ROUTE_METHOD_PAIRS / EXACT_10_PRIVATE_HELPERS /
RBAC_6_VIEW_13_EDIT_5_FULL / B6_P_NEUTRAL_OWNERS_PRESERVED /
PERIODO_CORRENTE_MAIN_LOCAL / R1_EXACT_THREE_DEAD_CONTEXT_REMOVALS /
MAIN_IDENTITY_REEXPORTS / ZERO_LOCAL_MAIN_B6_BODIES / ZERO_APP_TO_MAIN /
MESSAGE_CATALOG_536 / CSRF_B6_11_OWNER_ONLY /
HISTORICAL_CSRF_CONTRACTS_RECONCILED / ROUTE_INVENTORY_BYTE_IDENTICAL /
FULL_HERMETIC_GREEN / TECHNICAL_PUBLICATION_COMPLETE /
POST_PUBLICATION_VERIFICATION_COMPLETE /
EXTERNAL_SUPERVISOR_ACCEPTANCE_GRANTED /
GOVERNANCE_CLOSEOUT_PUBLISHED`.

PHASE 4-B6 is CLOSED / ACCEPTED. Phase 4 remains open. Phase 5, Phase 6 and the
Arquivos / Alertas / Reportes cohort remain unauthorized; Migration v4 remains prohibited.
