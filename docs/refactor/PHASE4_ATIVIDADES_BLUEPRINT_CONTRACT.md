# Phase 4-B3 — Atividades Admin Blueprint Contract

## Status and scope

**Status: IMPLEMENTED / AWAITING SUPERVISOR REVIEW.** This contract does not declare B3 CLOSED / ACCEPTED.

Phase 4-B3 extracts the complete Atividades administrative cohort from `main.py` into `app.views.admin.atividades` while preserving the legacy public surface. The bounded owner contains exactly **22 endpoints** and **29 governed route/method combinations**.

This phase does not authorize extraction of Matrizes, Requisições, Alunos, Turmas, Cursos, Arquivos, Alertas, Reportes, Banco de Dados, Acesso, `dashboard.py`, `admin_meus_dados`, Phase 5, Phase 6, or migration v4.

## Legacy route matrix

| # | Rule | Endpoint | Methods | RBAC |
|---:|---|---|---|---|
| 1 | `/admin/atividades` | `admin_atividades` | GET | `atividades:view` |
| 2 | `/admin/atividades/academicas` | `admin_atividades_academicas` | GET | `atividades:view` |
| 3 | `/admin/atividades/extensao` | `admin_atividades_extensao` | GET | `atividades:view` |
| 4 | `/admin/adicionar_atividade` | `admin_adicionar_atividade` | GET, POST | `atividades:edit` |
| 5 | `/admin/editar_atividade/<int:atividade_id>` | `admin_editar_atividade` | GET, POST | `atividades:edit` |
| 6 | `/admin/deletar_atividade/<int:atividade_id>` | `admin_deletar_atividade` | POST | `atividades:full` |
| 7 | `/admin/atividades/importar/preview` | `admin_atividades_importar_preview` | GET, POST | `atividades:full` |
| 8 | `/admin/atividades/importar/confirmar` | `admin_atividades_importar_confirmar` | POST | `atividades:full` |
| 9 | `/admin/grupos/renomear` | `admin_grupos_renomear` | POST | `atividades:full` |
| 10 | `/admin/grupos/excluir` | `admin_grupos_excluir` | POST | `atividades:full` |
| 11 | `/admin/catalogo-versoes` | `admin_catalogo_versoes` | GET | `atividades:view` |
| 12 | `/admin/catalogo-versoes/<int:base_id>` | `admin_catalogo_versao_detalhe` | GET | `atividades:view` |
| 13 | `/admin/normas-atividade` | `admin_normas_atividade` | GET | `atividades:view` |
| 14 | `/admin/mapeamento-legado` | `admin_mapeamento_legado` | GET | `atividades:view` |
| 15 | `/admin/catalogo-versoes/nova-base` | `admin_catalogo_nova_base` | GET, POST | `atividades:edit` |
| 16 | `/admin/normas-atividade/nova` | `admin_norma_nova` | GET, POST | `atividades:edit` |
| 17 | `/admin/catalogo-versoes/<int:base_id>/nova-versao` | `admin_catalogo_nova_versao` | GET, POST | `atividades:edit` |
| 18 | `/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/editar` | `admin_catalogo_editar_versao` | GET, POST | `atividades:edit` |
| 19 | `/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/ativar` | `admin_catalogo_ativar_versao` | POST | `atividades:edit` |
| 20 | `/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/inativar` | `admin_catalogo_inativar_versao` | POST | `atividades:edit` |
| 21 | `/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/descontinuar` | `admin_catalogo_descontinuar_versao` | POST | `atividades:edit` |
| 22 | `/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/substituir` | `admin_catalogo_substituir_versao` | POST | `atividades:edit` |

No twenty-third endpoint is owned or registered by this blueprint.

## Registration and compatibility

- `bp_admin_atividades` is registered through the Phase-4 legacy-route adapter.
- Every route retains its global endpoint name; no blueprint-qualified endpoint is exposed.
- `create_app()` registers B3 by default and provides the explicit test/isolation switch `register_admin_atividades_blueprint=False`.
- `main.py` re-exports the moved routes and helpers by object identity for static and runtime consumers.
- Existing templates, redirects, CSRF handling, request methods, response headers, flashes, SQL, commits, rollbacks and exception paths are preserved.
- Route collision checks remain fail-closed before registration.

## Shared activity-catalog ownership

`app.activity_catalog` is the neutral shared owner for ordinary activity parsing/normalization and versioned catalog read helpers. It has no dependency on `main.py` or an administrative view module. This prevents future Matrizes and Requisições work from depending on `app.views.admin.atividades`.

The shared owner contains:

- `parse_documentos_json`;
- `_normalize_atividade_grupo`;
- activity-base, norma and version list/look-up helpers;
- version-number and latest-active-version helpers;
- version usage and transition-history helpers;
- legacy-map listing.

Matrizes and Requisições routes remain physically in `main.py` in B3. Their existing references resolve through compatibility imports from `app.activity_catalog`; no route from either cohort moves in this phase.

## CSV preview/import and upload ownership

The Atividades blueprint owns its CSV header normalization, row validation, preview persistence, preview cleanup, group-definition upsert and confirmation flow. The physical upload helper has the neutral owner `app.uploads`, uses the active Flask application's configured upload root, and remains re-exported from `main.py` for other current consumers.

Filesystem and transaction behavior remains unchanged:

- preview uploads stay below `UPLOAD_FOLDER/atividades_imports`;
- preview JSON stays below `UPLOAD_FOLDER/atividades_import_previews`;
- invalid previews delete the uploaded CSV;
- confirmation commits the activity/group changes as before;
- integrity failure rolls back and removes preview/upload artifacts;
- no canonical database or migration is opened or modified by the extraction itself.

`save_upload` had its defining body in baseline `main.py` and has current non-B3 consumers in
`admin_reportes` and `admin_meus_dados`, so `app.uploads` is the appropriate view-neutral owner.
`main.save_upload` is the same function object. `ALLOWED_ATTACHMENTS`, `ALLOWED_CSV` and
`ALLOWED_REPORTE_SCREENSHOTS` are set-equal to baseline. Valid callers keep the same relative
paths and filenames; `current_app.config["UPLOAD_FOLDER"]` replaces the baseline module-global
app coupling. B3-R1 also proves containment before mutation: an escaped internal subdirectory
raises before `os.makedirs` or `file_storage.save`, while every current production subdirectory
argument is a controlled relative path.

## B3-R1 scope-expansion reconciliation

The early changes to `app/uploads.py`, `utils/messages.py` and the two CSRF inventory snapshots
were withheld from staging/publication until direct reconciliation. Their classification is:

`PRE_REVIEW_SCOPE_EXPANSION / MECHANICALLY_CAUSED_BY_CANONICAL_OWNER_MOVE /
NOT_STAGED / NOT_COMMITTED / PUBLICATION_WITHHELD /
REQUIRES_SUPERVISOR_RECONCILIATION / RECONCILED_BY_B3_R1_EXACT_DELTA_PROVED`.

This is exact, path-specific reconciliation and not general retroactive authorization.

### Message inventory exact delta

- scanner roots gain exactly `app/uploads.py`, not broad `app/**/*.py` discovery;
- baseline/candidate keys: 536 / 536;
- added keys: 0; removed keys: 0;
- default-text deltas: 0; kind deltas: 0; semantic-usage deltas: 0;
- 292 usage records have only source path/line metadata relocation caused by moving handlers,
  `save_upload`, or shortening `main.py`;
- the existing `Extensão de arquivo não permitida.` default remains unchanged and is now
  attributed to `app/uploads.py::save_upload`.

### CSRF snapshot exact delta proof

Each 78-row snapshot (`shadow_off` and `shadow_on`) has exactly 15 changed fields. Every change
is a single `view_function` owner transition from `main.<handler>` to
`app.views.admin.atividades.<handler>` with the same handler suffix. Route, endpoint, methods,
form/action, CSRF classification, protection state, sink semantics and every other field are
unchanged. Unauthorized snapshot deltas: zero.

## Shared-helper consumer and transaction graph

All 14 helpers are canonically defined in `app.activity_catalog`, imported by `main` as identity
compatibility exports, and own no commit/rollback/savepoint. `parse_documentos_json` has a
Requisições consumer. `_normalize_atividade_grupo`, `get_atividade_base`,
`get_next_numero_versao` and `get_atividade_versao_by_id` have Matrizes consumers. Other direct
production consumers are in the Atividades blueprint, except the retained compatibility export
`get_ultima_versao_ativa_por_base`. The owner imports only `json` and future annotations: no
`main`, `app.views.*`, Flask or transaction dependency. B2 resolver/snapshot/shadow helpers are
not duplicated. Matrizes and Requisições route bodies remain physically in `main.py`.

## Qualification and physical evidence

- baseline HEAD/upstream/live remote: `81cc6b10b893f1d34bd211a527e9fd12c3b6bbbe`;
- B3 RED: 12 failed / 2 passed; current B3 owner/upload contract: 19 passed;
- mandatory final affected lane: 353 passed in 119.56s;
- historical pre-final-test-delta full run: 974 passed / 17 deselected / 292.86s, not final qualification;
- final exact-candidate hermetic: 974 passed / 17 deselected / zero failures/errors / 399.95s / exit 0;
- routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0;
- actor matrix 402 = 263 allowed + 139 denied;
- route inventory snapshot byte-identical;
- canonical database 544768 bytes / SHA-256
  `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`;
- WAL/SHM/journal absent; canonical SQLite opening count zero;
- protected residual 17420 bytes / SHA-256
  `7388cfbc8f446410ef3c98ec0fa274c2c36ff4f3ef8ed2cd649bb1f3e1d3bb0e`.

The exact candidate ceiling is 16 paths: six production, four tests/snapshots and six
governance paths. A seventeenth path is a hard stop. Implementation and deterministic gates were
performed directly by IAsup `openai-codex/gpt-5.6-sol`; independent review mutates zero files.

## B3-R2 review evidence and adjudication

- provisional review: logical `flash_free`, requested/effective
  `opencode/deepseek-v4-flash-free`, session `ses_0425bf1cbffeIxMwsDQn0etSEC`, router exit 0,
  cost 0, `free-uses-used=0`, no fallback; external-directory permission errors yielded no
  technical verdict. IAsup classification: `PROVISIONAL / UNUSABLE DELIVERY / NO VERDICT`;
- final FREE attempt: `opencode/deepseek-v4-flash-free`, session
  `ses_0422f0e1cffepCXyNpg47dWpoq`, cost 0; timed out after 600s without accepted delivery;
- accepted final review: logical `flash_free` selected `flash_normal` after the consumed FREE
  budget; router trigger `FALLBACK_FREE_BUDGET_EXHAUSTED`, with task-level technical cause the
  immediately preceding FREE timeout. Effective `opencode-go/deepseek-v4-flash`, session
  `ses_04224ca47ffe5qAwwHGtxlR7i7`, router exit 0, router-reported cost `0.0010424344 USD`
  (observed step-finish aggregate `0.0206550400 USD`), verdict PASS, findings NONE, mutation 0;
- exact reviewed/pre-documentation full diff SHA-256:
  `ec96796d3541710a36ac8121e40ffd888737c7c926f191a28034482cedbfd556`;
- frozen non-governance diff SHA-256:
  `13b0af13e653641d75d2466d7d8d69090e655a18e28bb678a7090dbe0e2ecab0`;
- IAsup accepted PASS. The reviewer's hash-canonicalization concern is `REJECTED_INCORRECT`
  because IAsup reproduced the specified path-framed binary-diff hash before and after review.
  The reviewer's no-test limitation is `ACCEPTED_NONBLOCKING` because the reviewer was
  intentionally read-only and the final hermetic gate belongs to IAsup.

The B3-R1 scope expansion remains reconciled by the exact message and CSRF proofs above. This
review record does not change the status from IMPLEMENTED / AWAITING SUPERVISOR REVIEW and does
not authorize B4, Phase 5, Phase 6 or migration v4.

## Acceptance gates

Acceptance requires:

1. the exact route matrix and RBAC mapping above;
2. compatibility exports by identity from `main.py`;
3. no moved route/helper body or B3 route decorator remaining in `main.py`;
4. no `main.py` import from either new owner;
5. B1 and B2 contracts green;
6. focused Atividades/catalog behavior green;
7. the complete test suite green;
8. protected database and residual hashes unchanged;
9. independent review of the frozen diff.

After these gates, only selective per-path staging is allowed. The reviewed and staged diff
hashes must match, with zero unstaged and zero non-ignored untracked paths. B4, Phase 5, Phase 6
and migration v4 remain unauthorized/prohibited.
