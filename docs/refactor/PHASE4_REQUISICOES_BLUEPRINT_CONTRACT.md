# PHASE 4-B4.2 — Admin Requisições Blueprint Compatibility Contract

Date: 2026-08-02
Status: **CLOSED / ACCEPTED**

## Authority and boundary

PHASE 4-B4.2 is CLOSED / ACCEPTED over the accepted B4.1 baseline
`c587098152e97d125f41a2d26f2f414c10ae5676`. Its published technical commit is
`3231dbd2ff9759d8f855f2a4118102783aedea83`, subject `Extract admin requisitions blueprint`,
with that B4.1 baseline as its direct parent. Publication: COMPLETE. Post-publication
verification: COMPLETE. B1, B2, B3, B4-A and B4.1 remain CLOSED / ACCEPTED. Phase 4
remains OPEN / INCREMENTAL IMPLEMENTATION and is not closed. Matrizes is NOT STARTED /
NOT AUTHORIZED BY THIS CLOSEOUT. Phase 5 and Phase 6 are NOT AUTHORIZED. Migration v4
is PROHIBITED.

This unit moves the exact Admin Requisições route cohort from `main.py` to
`app/views/admin/requisicoes.py`. It does not authorize schema, migration, product,
RBAC, template, static, transaction, upload/document, versioning, matrix-policy or
requisition-policy redesign.

## Exact legacy route contract

| Methods | Rule | Global endpoint | Requirement |
|---|---|---|---|
| GET, POST | `/admin/importar_requisicoes` | `admin_importar_requisicoes` | `requisicoes:full` |
| GET | `/admin/requisicoes` | `admin_requisicoes` | `requisicoes:view` |
| GET, POST | `/admin/requisicoes/nova` | `admin_nova_requisicao` | `requisicoes:edit` |
| POST | `/admin/requisicoes/<int:req_id>/editar` | `admin_editar_requisicao` | `requisicoes:edit` |
| POST | `/admin/requisicoes/<int:req_id>/excluir` | `admin_excluir_requisicao` | `requisicoes:full` |
| GET | `/admin/requisicao/<int:req_id>` | `admin_detalhes_requisicao` | `requisicoes:view` |
| GET | `/admin/api/requisicao/<int:req_id>` | `admin_api_requisicao` | `requisicoes:view` |
| GET | `/admin/api/aluno/<int:aluno_id>/requisicao-scope` | `admin_api_aluno_requisicao_scope` | `requisicoes:view` |
| GET, POST | `/admin/processar_requisicao/<int:req_id>` | `admin_processar_requisicao` | `requisicoes:edit` |

The contract is exactly 9 global endpoints and 12 route/method pairs. The RBAC
pair distribution is exactly `view=4`, `edit=5`, `full=3`. A tenth endpoint,
compatibility route, duplicate rule/method or namespaced endpoint is prohibited.
Every canonical handler remains decorated by `admin_required`.

## Ownership and registration

`app.views.admin.requisicoes` is the canonical owner of the nine handlers. It defines
`bp_admin_requisicoes` and immutable `LEGACY_ROUTE_SPECS`, and uses only the accepted
`LegacyRouteSpec`, `configure_legacy_routes` and `register_legacy_blueprint` mechanism.
It contains no `@bp.route`, direct or dynamic `main` import, wrapper or route alias.

`app.create_app` exposes `register_admin_requisicoes_blueprint: bool = True`, registers
this cohort after the accepted Phase-4 admin cohorts, and preserves independent-app and
opt-out behavior. `main` imports and re-exports the canonical callables by identity;
`main.app.view_functions[endpoint]` resolves to those same objects.

## Moved private closure

The exact B4.2-private closure moved with the cohort is:

- `ALLOWED_EXCEL`
- `_normalize_requisicao_data_evento`
- `_get_admin_requisicao_scope_for_aluno`
- `_list_admin_requisicao_alunos`
- `_append_requisicao_arquivos`

`main` preserves compatibility identities for these names. No duplicate implementation
or reverse `app -> main` edge is retained. Runtime dependencies are consumed directly
from the accepted neutral owners in `app.db`, `app.db_maintenance`, `app.requisitions`,
`app.matrix_scope`, `app.activity_catalog`, `app.versioning`, `app.student_documents`,
`app.uploads`, `app.web`, `app.auth` and `utils.messages`.

The only owner adaptation inside moved bodies is `app.config` to Flask
`current_app.config`. An AST adjudication against `HEAD:main.py` proves all 13 moved
functions byte-semantically identical after removing only legacy `@app.route`
decorators and applying that owner substitution. SQL, transaction boundaries, commits,
rollbacks, flashes, templates, redirects, JSON shape/status, document cleanup, snapshots,
shadow reads and matrix scope are unchanged.

## Consumer and compatibility adjudication

Direct/transitive consumers were classified before movement. The four private helpers
and `ALLOWED_EXCEL` have no runtime consumer outside the nine-handler cohort; tests that
consume compatibility identities continue through `main` re-exports. The accepted
B4.1 neutral owners are imported directly. The formerly legacy monkeypatch in
`tests/test_admin_snapshot_diagnostics.py` now targets the canonical owner; this is a
mechanical test-owner correction explicitly authorized by the supervisor and does not
change production behavior.

B3/B1 architectural tests were mechanically advanced to recognize the authorized
`requisicoes.py` owner and the removal of `admin_requisicoes` as a local `main.py`
definition. Their assertions remain strict and now verify the canonical import.

## TDD and focused evidence

The B4.2 RED test was created before production mutation. On the accepted baseline it
returned `20 failed, 3 passed` because `app.views.admin.requisicoes` and its factory flag
were absent. After implementation and correction of two superseded prior-cohort
expectations, the primary focused lane returned `138 passed`; the route/RBAC/actor,
versioning, Phase-3 and request-alert lane returned `107 passed`. Total independently
rerun focused evidence: 245 passed, zero failed.

Focused evidence proves:

- exact 9 endpoints, 12 route/method pairs and `4/5/3` RBAC distribution;
- global endpoint identity and collision-safe fail-closed registration;
- default registration, exact opt-out and independent-app behavior;
- no local moved definitions in `main.py` and identity-preserving exports;
- no `app -> main` import edge and isolated blueprint import;
- route inventory unchanged at 131 routes and 130 endpoint names;
- governed pairs 134, RBAC unmapped zero and actor matrix 402 = 263 allowed + 139 denied;
- message catalog 536 with zero key/default/kind/placeholder/semantic-usage delta;
- both CSRF snapshots changed in exactly five `view_function` values and no other field;
- create/edit/delete/list/filter/pagination/detail/API/scope/matrix/process/release/CSRF,
  versioning snapshot/shadow-read and request-alert regressions remain green;
- Phase-3 startup/schema/transaction and accepted B1/B2/B3/B4.1 contracts remain green.

The first full lane exposed four stale governance assertions without candidate or physical
drift (`1001 passed / 4 failed / 17 deselected`). This remains historical failure evidence.
The bounded documentary compatibility correction was focused-GREEN. Accepted final evidence:
final hermetic `1005 passed / 17 deselected / 0 failed / 0 errors / 362.33s`; index-visible
`57 passed / 0 failed / 0 errors`; post-publication `56 passed / 1 deselected / 0 failed /
0 errors`. The post-commit CSRF comparison `HEAD^ -> HEAD` returned `[5, 5]` owner-only
deltas. Canonical SQLite opens: 0.

The independent technical review used logical route `flash_free`, effective provider/model
`opencode` / `opencode/deepseek-v4-flash-free`, session
`ses_03ff5695bffeEBNIZRiSVZonYz`, cost 0, exit 0, fallback none and mutation 0. Verdict:
PASS; blocking findings NONE; scope EXACT; behavior PRESERVED. Its hash-method
reproducibility finding was VALID / NONBLOCKING / DOCUMENTARILY CORRECTED /
NO TECHNICAL IMPACT.

The accepted documentary addendum requested `flash_free` and selected `flash_normal` through
`FALLBACK_FREE_BUDGET_EXHAUSTED`; effective provider/model `opencode-go` /
`opencode-go/deepseek-v4-flash`; session `ses_03fce2ebbffejkf6IUdfPrsxF3`; exit 0; router
cost `0.0011911032 USD`; observed step-finish aggregate `0.0180531456 USD`; mutation 0;
outside-scope reads 0; PASS; blocking findings NONE. Flash FREE itself did not complete the
accepted documentary addendum.

### Candidate content-hash algorithms

The accepted technical worktree hash is
`1b8435a9db10f8a2ae680f60c17a9ad0a723eed88066a834ca59255bf7b8cc0e`, identified as
`WORKTREE_RAW_CONTENT_MANIFEST_SHA256_V1`. It is SHA-256 over the concatenation, for each
of the 16 manifest paths sorted by UTF-8 path bytes, of: `path_utf8`, one NUL byte, the raw
file length as an unsigned 8-byte big-endian integer, and the 32 raw bytes of
`SHA256(raw_file_bytes)`.

Publication uses `GIT_CANONICAL_CONTENT_MANIFEST_SHA256_V1`. For each of the same ordered
paths, canonical bytes are obtained by replacing every CRLF pair in the worktree bytes with
LF; the concatenated record is then `path_utf8`, NUL, canonical length as unsigned 8-byte
big-endian, and the 32 raw bytes of `SHA256(canonical_bytes)`. Applying the same aggregate
SHA-256 produces `c362566627667ba684765ad3ea8fdeb9abf7678dd52e185cedd3ed8b08a891b4`,
the accepted Git-canonical identity recomputed from the staged Git blobs. This
candidate-specific canonicalization records the repository clean
filter's observed line-ending effect without changing worktree bytes. Both identifiers are
content-manifest hashes, not Git patch hashes.

The accepted governance raw/canonical six-path identities are
`19519783e02bf983f820d357e6c2b250db541581fae57f6988e64cf1900f544d` and
`b44ae4231aaaeb022c2cfc2ca94f20be76a94dd7e82c51e97966866d294d0ceb`. The accepted
production/test raw identity is
`f60ebdab5cd1e7aa2d98d9ade66534925c5a077326dff2e70b24c72e6390c037`. Raw worktree
and Git-canonical identities are intentionally distinct and must not be conflated.

## Physical invariants

The canonical `database.db` remains 544768 bytes with SHA-256
`a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`.
`database.db-wal`, `database.db-shm` and `database.db-journal` remain absent. The protected
residual remains 17420 bytes with SHA-256
`7388cfbc8f446410ef3c98ec0fa274c2c36ff4f3ef8ed2cd649bb1f3e1d3bb0e`.
No canonical SQLite opening, schema change, migration or residual mutation is authorized.

## Accepted technical artifact manifest

The published technical artifact contains exactly 16 paths: 3 production, 7 test/snapshot and
6 governance paths.

Production:

- `app/__init__.py`
- `app/views/admin/requisicoes.py`
- `main.py`

Tests and snapshots:

- `tests/_artifacts/csrf_inventory_shadow_off.json`
- `tests/_artifacts/csrf_inventory_shadow_on.json`
- `tests/test_admin_snapshot_diagnostics.py`
- `tests/test_phase4_atividades_blueprint.py`
- `tests/test_phase4_configuracoes_blueprint.py`
- `tests/test_phase4_requisicoes_blueprint.py`
- `tests/test_phase4_requisicoes_shared_owners.py`

Governance:

- `AGENT_HANDOFF.md`
- `PROJECT_STATE.md`
- `docs/DOCUMENTATION_INDEX.md`
- `docs/mapeamento/05_avaliacao_refactor.md`
- `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
- `docs/refactor/PHASE4_REQUISICOES_BLUEPRINT_CONTRACT.md`

No path outside this manifest is part of B4.2.

## Current decision and closeout boundary

`PHASE4_B4_2_CLOSED / ACCEPTED / REQUISICOES_BLUEPRINT_ESTABLISHED /
EXACT_9_LEGACY_ENDPOINTS_PRESERVED / EXACT_12_ROUTE_METHOD_PAIRS_PRESERVED /
RBAC_4_VIEW_5_EDIT_3_FULL_PRESERVED / B4_1_NEUTRAL_OWNERS_PRESERVED /
ZERO_APP_TO_MAIN_EDGE / ROUTES_131 / ENDPOINTS_130 / GOVERNED_PAIRS_134 /
RBAC_UNMAPPED_ZERO / ACTOR_402_263_139 / MESSAGE_CATALOG_536 /
CSRF_EXACT_FIVE_OWNER_ONLY_DELTAS / FULL_HERMETIC_1005_17 /
INDEPENDENTLY_REVIEWED / TECHNICAL_COMMIT_3231DBD2 / PUBLICATION_VERIFIED /
GOVERNANCE_CLOSEOUT_PUBLISHED`.

The governance closeout changes exactly the six governance paths listed above and no
production, test/snapshot, route, database, schema or migration path. Its authorized subject
is `Record acceptance of Phase 4-B4.2`; identity resolves through Git history. Historical
candidate-unstaged/unpublished, addendum-pending, commit/push-pending and external-review-
pending statements are superseded, while RED/GREEN, first-failed-full-suite, review/fallback,
hash-normalization and authorized scope-expansion history remain preserved. Phase 4 stays
OPEN / INCREMENTAL IMPLEMENTATION. Matrizes, Phase 5, Phase 6 and migration v4 remain outside
authority. Do not begin the next cohort.
