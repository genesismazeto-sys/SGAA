# PHASE 4-B5 — Matrizes admin blueprint contract

Date: 2026-08-02
Status: **IMPLEMENTED / AWAITING SUPERVISOR REVIEW** (NOT CLOSED / ACCEPTED; candidate unstaged / uncommitted / unpushed; independent technical review COMPLETE / PASS; external supervisor review/acceptance PENDING)

## Status and authority

PHASE 4-B4.2: **CLOSED / ACCEPTED**.
PHASE 4-B5-A: **DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED**.
PHASE 4-B5-P: **CLOSED / ACCEPTED** (neutral admin-access shared-owner prerequisite;
published technical commit `92486f87ea15697282a265cb7a9941678cb9138f`, parent
`a0b56896252a276e562da3842d3d61b078bd9f27`; publication and post-publication
verification COMPLETE; independent review accepted; governance closeout published).
PHASE 4-B5: **IMPLEMENTED / AWAITING SUPERVISOR REVIEW** — this contract records the
Matrizes admin blueprint implementation candidate. It is **NOT CLOSED / ACCEPTED**; no
technical commit, push or staging has occurred yet, and no review hash, commit, push or
acceptance is invented here. Independent technical read-only review is **COMPLETE /
PASS**; external supervisor review/acceptance remains **PENDING**. PHASE 4 remains
**OPEN / INCREMENTAL IMPLEMENTATION** and is not closed. Phase 5 and
Phase 6 are **NOT AUTHORIZED**. Migration v4 is **PROHIBITED**. No later cohort is
named or authorized by this contract.

## Baseline and candidate identity

- Repository: `genesismazeto-sys/SGAA`.
- Branch: `refactor/architecture-safety-net`.
- **Baseline / parent (required):** HEAD/upstream/live `ef874b9d14b02656a0f26ea885024a280d49682e`,
  subject `Record acceptance of Phase 4-B5-P`. Required baseline divergence `0/0`.
- Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`.
- **Candidate publication state:** unstaged / uncommitted / unpushed. The future
  authorized technical subject is `Extract admin matrices blueprint`. Independent
  technical read-only review is **COMPLETE / PASS**; external supervisor
  review/acceptance is **PENDING** at the time of this writing and must remain so in
  these documents until the next operational phase. No commit, push, review hash or
  acceptance exists yet.

## Authority and boundary

PHASE 4-B5 is the Matrizes admin blueprint extraction. It is the successor of the
PHASE 4-B5-A diagnosis and the PHASE 4-B5-P neutral shared-owner prerequisite. The
blueprint stage moves the exact Matrizes route cohort and corrected helpers out of
`main.py` into a canonical owner module. `app/views/admin/matrizes.py` is the new
canonical owner. `main.py` retains only identity re-exports.

Void names `_get_grupos_atividade` and `_get_matriz_active_norma_ids` remain absent
and are never created/exported in `main` or the new module. Classification:
`SUPERVISOR CONTRACT CORRECTION / NOT A PATH-POOL EXPANSION / NOT A DOMAIN-SCOPE EXPANSION`.

## Ownership: exact 10 endpoints / 12 route-method pairs / 21 corrected helpers

`app.views.admin.matrizes` is the canonical owner of exactly **10 global legacy
endpoints / 12 route-method pairs** and the **21 route-private corrected helpers**.

### 10 endpoints (global legacy endpoints; 12 route-method pairs)

| Endpoint | Rule | Methods |
|----------|------|---------|
| `admin_matrizes` | `/admin/matrizes` | GET |
| `admin_adicionar_matriz` | `/admin/adicionar_matriz` | GET, POST |
| `admin_editar_matriz` | `/admin/editar_matriz/<int:matriz_id>` | GET, POST |
| `admin_excluir_matrizes` | `/admin/matrizes/excluir` | POST |
| `admin_excluir_matriz` | `/admin/matrizes/<int:matriz_id>/excluir` | POST |
| `admin_matriz_nova_atividade` | `/admin/matrizes/<int:matriz_id>/atividades/nova/<string:active_tab>` | POST |
| `admin_matriz_nova_versao_card` | `/admin/matrizes/<int:matriz_id>/atividades/<int:atividade_id>/nova-versao` | POST |
| `admin_matriz_versoes` | `/admin/matrizes/<int:matriz_id>/versoes` | GET |
| `admin_matriz_versoes_definir` | `/admin/matrizes/<int:matriz_id>/versoes/definir` | POST |
| `admin_matriz_versoes_remover` | `/admin/matrizes/<int:matriz_id>/versoes/remover` | POST |

Total route-method pairs: 12. No 11th endpoint exists.

### 21 corrected helpers

`get_bases_escopo_matriz`; `get_versoes_ativas_por_base_na_matriz`;
`get_vinculo_versao_da_matriz`; `_set_versao_da_matriz_para_base`;
`_remover_versao_da_matriz_para_base`; `get_card_version_menu_data`;
`_matriz_status_badge_type`; `_matriz_vigencia_label`; `_matriz_activity_type_for_tab`;
`_matriz_axis_for_tab`; `_get_grupos_por_tipo`; `_get_matriz_active_normas_for_axis`;
`_build_matriz_new_activity_modal_context`; `_matriz_transfer_meta`;
`_matriz_activity_rule_summary`; `_matriz_transfer_lists`; `_matriz_counts`;
`_render_matriz_form`; `_matriz_payload_from_request`; `_ensure_default_versao_link`;
`_save_matriz_activity_links`.

### Main identities and body removal

`main.py` has **zero local bodies/decorators** for the 10 handlers and **zero local
bodies** for the 21 helpers, re-exporting all by identity. All **31 moved bodies are
AST-identical to the baseline modulo removal of `@app.route` decorators**;
`@admin_required` is preserved. No wrapper, alias, rename or redesign was introduced.

## Registrar, blueprint and factory

- `bp_admin_matrizes = Blueprint("admin_matrizes_blueprint", __name__)`.
- `LEGACY_ROUTE_SPECS` is an immutable tuple of `LegacyRouteSpec` entries configured via
  `configure_legacy_routes`. Exactly 10 specs and 12 route-method pairs; endpoints are
  global legacy names (no `.` namespace); no `@bp.route`, no namespaced alias, no
  duplicate rule, no compatibility wrapper, no `import main`, no dynamic import and no
  `sys.modules` edge.
- `app.create_app` exposes keyword-only `register_admin_matrizes_blueprint: bool = True`.
  Default registers the exact cohort deterministically after the accepted admin cohorts
  (requisicoes order preserved). Explicit `False` removes exactly the cohort. Independent
  apps remain isolated. Endpoint collisions and rule/method collisions fail atomically
  through the accepted registrar (`LegacyRouteRegistrationError`) before any B5 route is
  added.
- `app/views/admin/__init__.py` (the accepted registrar) is unchanged and is not part of
  this mutation pool.

## RBAC (frozen)

Exact **3 view / 7 edit / 2 full**, as proven by the B5 test:

- VIEW: `admin_matrizes` GET; `admin_editar_matriz` GET; `admin_matriz_versoes` GET.
- EDIT: `admin_adicionar_matriz` GET/POST; `admin_editar_matriz` POST;
  `admin_matriz_nova_atividade` POST; `admin_matriz_nova_versao_card` POST;
  `admin_matriz_versoes_definir` POST; `admin_matriz_versoes_remover` POST.
- FULL: `admin_excluir_matrizes` POST; `admin_excluir_matriz` POST.

`app/auth.py` is unchanged.

## B5-P owner preservation

`app.admin_access` remains protected and byte-identical (4546 bytes, SHA-256
`b2dc2592637b1268c001ef6153c0e9ad619b1336654c976e328224c6da1d9814`). The two B5-P
consumers `admin_editar_matriz` and `admin_matriz_nova_atividade` now live in
`app.views.admin.matrizes` and resolve through their `__globals__` the same canonical
`_get_current_admin_access_context` and `_admin_can` objects from `app.admin_access`.
`_persist_user_access_overrides` and `_parse_access_overrides_from_form` remain main-local.

## Direct owners consumed

`app.views.admin.matrizes` imports directly from accepted owners:
`app.admin_access`, `app.matrix_scope`, `app.activity_catalog`, `app.db`,
`app.db_maintenance`, `app.web.filters`, `app.web.pagination`, `app.auth`,
`utils.messages`, and from `app.views.admin.atividades` only `_build_grupo_label` and
`_canonicalize_tipo_limitacao`. Zero `app -> main` edge exists.

## Schema / transaction / UI / messages / CSRF freezes

- Ensures `ensure_matrizes_atividades_table`, `ensure_matriz_atividade_links_table` and
  `ensure_atividade_versioning_schema` are preserved literally, including GET timing.
- SQL, transaction boundaries, commits/rollbacks/exceptions, version/matrix links,
  templates, `url_for`, redirects, flashes/messages, CSRF and HTTP behavior are frozen.
- Zero redesign/hardening.

## Test-driven, recovery and deterministic gates

- Preimplementation ownership/governance nodes: `3 passed`.
- Corrected TDD RED: `20 failed / 4 passed / 0 collection errors`, exit 1; failures
  exclusively because `app.views.admin.matrizes` was absent, the factory
  `register_admin_matrizes_blueprint` flag/opt-out was absent, `main` still owned the
  handlers/helpers, and the CSRF snapshots still showed owner `main`.
- Primary B5 GREEN: `24 passed` in `3.74s`.
- Focused expanded (44 files including all identified matriz/versioning coverage):
  `578 passed` in `249.33s`.
- First full hermetic run: `1049 passed / 1 failed / 17 deselected` in `370.60s`. The
  sole failure was `tests/test_phase4_configuracoes_blueprint.py` admin-package
  membership (it did not yet include `matrizes.py`). **HARD STOP** before any change
  outside the authorized pool.
- B5-R3 one-for-one mutable-pool substitution: removed `tests/test_ref_0c_b1_p0_access_context_transactions.py`
  from mutation authorization (it remains a read-only focused gate, unchanged) and added
  `tests/test_phase4_configuracoes_blueprint.py` only to add `matrizes.py` to the package
  membership. Exact node: `1 passed` in `0.64s`. Affected focused lane: `143 passed` in
  `24.30s`.
- Final full hermetic (fresh): `1050 passed / 17 deselected / 0 failed / 0 errors` in
  `317.65s`; collected 1067; canonical SQLite opens 0.
- CSRF snapshots prove exactly `[8, 8]` owner-only deltas (shadow-off and shadow-on),
  78 rows each, summaries equal, no non-owner delta: `main.<handler>` →
  `app.views.admin.matrizes.<handler>` for the 8 Matrizes POST handlers only.

## Invariants

- Routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC unmapped 0.
- Actor matrix 402 = 263 allowed + 139 denied.
- Message catalog 536.
- Route inventory byte-identical: 20814 bytes, SHA-256
  `6e32148cd1988d5e405c9d11bdbda285359f72d5fc7eca8bd5ef8da9b83049fa`.
- CSRF exactly `[8, 8]` owner-only deltas (78 rows each; summaries equal; no non-owner
  delta).
- Canonical database: 544768 bytes, SHA-256
  `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`; WAL/SHM/journal
  absent; canonical SQLite opens 0.
- Protected residual: 17420 bytes, SHA-256
  `7388cfbc8f446410ef3c98ec0fa274c2c36ff4f3ef8ed2cd649bb1f3e1d3bb0e`.
- `app/admin_access.py` byte-identical: 4546 bytes, SHA-256
  `b2dc2592637b1268c001ef6153c0e9ad619b1336654c976e328224c6da1d9814`.

## Execution and routing evidence

- Supervisor/IAsup: Hermes `openai-codex/gpt-5.6-sol`, direct adjudication and
  deterministic gates.
- RED IAexec: logical/effective `flash_free`; provider/model `opencode` /
  `opencode/deepseek-v4-flash-free`; session `ses_03b57ca6bffenOnPYH3mt5WdX0`; exit 0;
  cost 0; fallback none.
- Implementation IAexec: logical `flash_free` → selected `flash_normal` by
  `FALLBACK_FREE_CONTEXT_TOO_LARGE`; actual `opencode-go` /
  `opencode-go/deepseek-v4-flash`; same session `ses_03b57ca6bffenOnPYH3mt5WdX0`; exit 0;
  cost `0.0010985912`; no silent escalation.
- Corrections IAsup direct: two deterministic typos in the new RED and the B5-R3
  membership expressly authorized; rationale: lower risk/cost and preservation of the
  second FREE for independent review.

## Independent technical review — COMPLETE / PASS

- Original request: logical `flash_free`, `opencode` / `opencode/deepseek-v4-flash-free`.
  The wrapper created session `ses_03adb7f27ffeJ1feNSLhrFij5R`, cost 0, exit 1 — a FREE
  technical failure with no usable verdict and no mutation.
- Single explicit fallback R4 `FALLBACK_FREE_EXECUTION_FAILURE`: selected `flash_normal`,
  actual `opencode-go` / `opencode-go/deepseek-v4-flash`, session
  `ses_03ad0a15dffeR53I9BqGU6a4tl`, exit 0, cost `0.001000188`, status COMPLETED; no
  further escalation.
- READ-ONLY mode; mutation 0; index empty before/after; manifest and identities
  initial/final identical.
- Isolated reviewer gates: `51 passed` in `6.19s`; supplemental requisicoes
  csrf/route/owners `3 passed`.
- Findings: BLOCKING 0. NONBLOCKING 4: (1) some routing/cost documentary facts are IAsup
  evidence and not re-executed; (2) `test_phase4_atividades_blueprint` owner assertion was
  a more precise mechanical correction, not weakening; (3) malformed/preexisting protected
  residual outside the manifest, do not clean; (4) preexisting ignored `__pycache__`, not
  created. Additional risks recorded: full/focused not re-executed by the reviewer per
  order; CSRF off/on byte-identical is a pre-existing state and not introduced by B5.
- Verdict: **PASS / SCOPE EXACT / BEHAVIOR PRESERVED / MUTATION 0**.
- Reviewer confirmed: 31 AST-exact bodies, 10/12 route-method pairs, 21 helpers,
  RBAC 3/7/2, zero `app -> main`, 8 owner-only CSRF deltas, exact package-membership
  change, coherent governance, shared-owner contract unchanged.

## Frozen and reconfirmed identities (initial = final)

- Exact manifest: **17** (11 technical + 6 governance); ceiling 18.
- Full WORKTREE raw content manifest SHA-256 v1:
  `73706a7bf10b10d96e273489bee2824aab57cd91197f23a37f59f1e6f2e33e60`.
- Full GIT-canonical content manifest SHA-256 v1:
  `aed7ef95144deb711ec45ca018ec33a8dd0da97b4ec4ab48753ad652215dcf33`.
- Production/test raw: `9e8c0bbc8e7421a160a0386ee357c4f2062fbfa7a3d4bf06717d5ab8043e1cd4`.
- Production/test git-canonical: `0b4caa7bf50a706cc68f7ef6d6557aea09dd40eb3c342282fc4a04edbe860b88`.
- Governance raw pre-review-doc-update:
  `769e75d33df559133befcc6b244e920a9ec230cff7486bbffdaae40abf2a95a8`.
- Governance git-canonical pre-review-doc-update:
  `2d9429ea76eed4fb0b2f68d5055bfb7134b759440cdbf70753a54c44b0b32cde`.

The two full hashes and the two governance hashes identify the candidate actually
reviewed before this documentary addendum; they are naturally superseded by this
documentation update. The production/test hashes remain valid and are the stable
technical link. Do not present the pre-update hashes as post-addendum identity.

## Candidate mutable pools (exact)

Technical manifest — production (3):

- `app/views/admin/matrizes.py` (new)
- `app/__init__.py`
- `main.py`

Technical manifest — tests/snapshots (8):

- `tests/test_phase4_matrizes_blueprint.py` (new)
- `tests/test_admin_matriz_nova_versao_card.py`
- `tests/test_phase4_configuracoes_blueprint.py` (B5-R3 membership; added only to include
  `matrizes.py` in the admin-package membership)
- `tests/test_phase4_atividades_blueprint.py`
- `tests/test_phase4_requisicoes_blueprint.py`
- `tests/test_phase4_matrizes_shared_owners.py`
- `tests/_artifacts/csrf_inventory_shadow_off.json`
- `tests/_artifacts/csrf_inventory_shadow_on.json`

Authorized but unchanged: `tests/test_phase4_requisicoes_shared_owners.py`; read-only
focused gate (unchanged): `tests/test_ref_0c_b1_p0_access_context_transactions.py`.

After these six governance writes the real manifest is **17 paths** (11 technical + 6
governance) within the authorized ceiling **18** (3 production + pool of 9
tests/snapshots + 6 governance).

## Irreversible boundaries

- Repository mutation crossed only for the exact source/test/governance manifest above.
- No technical commit or push has occurred yet; independent technical read-only review is
  COMPLETE / PASS; external supervisor review/acceptance is still pending; do not stage,
  commit, push or claim acceptance.
- This documentary delta changes only the six governance paths; it changes no production,
  test, snapshot, database, migration, schema, route, RBAC, template, static or
  transaction path.
- `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md` is NOT modified and remains
  the accepted B5-P record.

## Final current status

`PHASE4_B5_IMPLEMENTED / AWAITING_SUPERVISOR_REVIEW /
MATRIZES_BLUEPRINT_ESTABLISHED / EXACT_10_LEGACY_ENDPOINTS /
EXACT_12_ROUTE_METHOD_PAIRS / EXACT_21_CORRECTED_HELPERS /
MAIN_IDENTITY_REEXPORTS_PRESERVED / ZERO_LOCAL_MAIN_BODIES_FOR_31 /
RBAC_3_VIEW_7_EDIT_2_FULL / B5_P_ADMIN_ACCESS_PRESERVED / ZERO_APP_TO_MAIN_EDGE /
ROUTES_131 / ENDPOINTS_130 / BUSINESS_PAIRS_160 / GOVERNED_PAIRS_134 /
RBAC_UNMAPPED_ZERO / ACTOR_402_263_139 / MESSAGE_CATALOG_536 /
ROUTE_INVENTORY_BYTE_IDENTICAL / CSRF_EXACT_8_OWNER_ONLY_DELTAS /
FULL_HERMETIC_1050_17 / INDEPENDENT_REVIEW_PASS / UNSTAGED_UNCOMMITTED_UNPUSHED /
AWAITING_SUPERVISOR_REVIEW`.

PHASE 4 remains OPEN / INCREMENTAL IMPLEMENTATION. PHASE 4-B5 is NOT CLOSED / ACCEPTED;
independent technical review is COMPLETE / PASS and external supervisor review/acceptance
remains pending; do not stage, commit, push or claim acceptance. No later
cohort is authorized.
