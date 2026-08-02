# PHASE 4-B5-P — Matrizes neutral admin-access shared-owner contract

Date: 2026-08-02
Status: **CLOSED / ACCEPTED** (PHASE 4-B5-P-R3 governance closeout)

## Status and authority

PHASE 4-B4.2: **CLOSED / ACCEPTED**.
PHASE 4-B5-A: **DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED**.
PHASE 4-B5-P: **CLOSED / ACCEPTED** by external supervisor acceptance. Its
published technical commit, independent review, publication and post-publication
verification are recorded below; no identity, reviewer, verdict, hash or cost is
invented.
PHASE 4-B5: **NOT AUTHORIZED FOR IMPLEMENTATION**. PHASE 4 remains
**OPEN / INCREMENTAL IMPLEMENTATION** and is not closed. Phase 5 and Phase 6 are
**NOT AUTHORIZED**. Migration v4 is **PROHIBITED**.

This unit is only the neutral shared-owner prerequisite for the future Matrizes
cohort. **B5 Matrizes blueprint extraction is NOT AUTHORIZED and no route moved.**
`app/views/admin/matrizes.py` remains absent.

## Baseline and published technical identity

- Repository: `genesismazeto-sys/SGAA`.
- Branch: `refactor/architecture-safety-net`.
- Baseline HEAD (pre-commit): `a0b56896252a276e562da3842d3d61b078bd9f27`
  (`Record acceptance of Phase 4-B4.2`).
- Required baseline divergence: `0/0`.
- Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`.
- **Published technical commit:** `92486f87ea15697282a265cb7a9941678cb9138f`
  (`Extract admin access context shared owner`), parent
  `a0b56896252a276e562da3842d3d61b078bd9f27`. Publication: COMPLETE.
  Post-publication verification: COMPLETE.
- **Accepted independent review:** provider `opencode`, model
  `opencode/deepseek-v4-flash-free`, session `ses_03c92c10affegAmZLZ63tmTjjA`,
  exit 0, cost 0, fallback none, mutation 0, blocking findings 0, nonblocking
  findings 3 (R2 no literal `NO ROUTE MOVEMENT` token; `B4_2_BASELINE_COMMIT`
  naming; runtime duration changed). External acceptance GRANTED by the
  PHASE 4-B5-P-R3 order.
- **Accepted content identities:** raw candidate `bf67fcaa7a44d27ae70adc4b2ab38842a9e808d31eb66a7907f56dad50aefaaf`;
  technical raw `932793aaac94862cac81310dcfca17aa53a5ce52a69283f82e7c2f2d5fde574c`;
  Git-normalized `068bf70d5434685980c8268c12de5c550c7f6f2f4ed07666c8d802ff8334e9bf`.
- This closeout is authorized under subject `Record acceptance of Phase 4-B5-P`;
  the future closeout commit identity is resolved through Git history and is not
  invented here.

## Ownership: exact five-symbol closure

`app/admin_access.py` is the canonical owner of exactly five symbols:

- `_fetch_user_access_overrides`
- `_build_access_scope_groups_for_level`
- `_load_admin_access_context`
- `_get_current_admin_access_context`
- `_admin_can`

`main.py` has **zero local bodies** for those five symbols. It directly imports and
re-exports all five by identity. All five moved bodies are **AST-identical** to parent
`a0b56896252a276e562da3842d3d61b078bd9f27:main.py` with **no redesign**; no behavioral, signature, default or error-path
change was introduced.

`_persist_user_access_overrides` and `_parse_access_overrides_from_form` remain local
in `main.py`. They are not moved, not re-exported from the owner, and not altered.

## Exact consumers

The exact current `main` consumers are six:

- `enforce_admin_access_control`
- `inject_admin_access_helpers`
- `admin_editar_matriz`
- `admin_matriz_nova_atividade`
- `admin_acesso`
- `uploaded_file`

The existing Flask `admin_required` wrappers are unwrapped **only by test
introspection**; no compatibility wrapper was added and no consumer signature changed.

## Dependency, import and cycle safety

- `app.admin_access` imports only `app.auth`, `app.db`, `app.db_maintenance` and the
  Flask `g`/`session` objects.
- `app.admin_access -> main` edges: **0**.
- `app.auth -> app.admin_access` edges: **0**.
- No cycle exists among these modules.
- Existing unrelated lazy `app.views.core` / `app.views.aluno -> main` edges remain
  baseline and are **not** caused by B5-P.
- An isolated `app.admin_access` import creates **no** Flask app, file, network,
  SQLite or migration side effect.
- Transaction neutrality is preserved: no commit, rollback, close or connection
  replacement was added.

## Behavior freeze

The five moved bodies preserve, byte-semantically, the baseline access-context
behavior: admin access overrides loading, access-scope group construction, admin
access-context load and current retrieval, and the `_admin_can` permission check.
No RBAC policy, route, template, CSRF, message, schema, migration, transaction,
snapshot or shadow-read behavior changed.

## Transaction / RBAC / route / CSRF / message invariants

- Routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC unmapped 0.
- Actor matrix 402 = 263 allowed + 139 denied.
- Message catalog 536.
- Route inventory byte-identical: 20814 bytes, SHA-256
  `6e32148cd1988d5e405c9d11bdbda285359f72d5fc7eca8bd5ef8da9b83049fa`.
- CSRF `shadow_off` and `shadow_on` snapshots are byte-identical to HEAD and to each
  other: each 288349 bytes, SHA-256
  `3a94e2e1ca587ffe966262717e2cdcde1251ef90b61202d81d4b681ae79a0056`. The historical
  B4.2 five-owner-only deltas remain proven against the fixed
  `c587098152e97d125f41a2d26f2f414c10ae5676` baseline.
- Canonical database: 544768 bytes, SHA-256
  `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`;
  WAL/SHM/journal absent; canonical SQLite opens 0.
- Protected residual: 17420 bytes, SHA-256
  `7388cfbc8f446410ef3c98ec0fa274c2c36ff4f3ef8ed2cd649bb1f3e1d3bb0e`.

## Test-driven, recovery and deterministic gates

- Corrected pre-production RED: `20 failed` in `2.01s`, exit 1, because
  `app.admin_access` was absent and `main` still owned the five bodies.
- First core GREEN attempt after the exact production move exposed two latent
  contradictions owned by the new test: `2 failed / 23 passed` in `3.88s`. They were
  mechanically corrected **without production mutation**: canonical grouped ordering
  follows `ACCESS_RESOURCE_GROUPS`, not `ACCESS_RESOURCE_ORDER`; decorated consumers
  require `__wrapped__` test introspection. Recovered core lane: `25 passed` in
  `3.78s`.
- Focused mandatory/access/admin-context/route/RBAC/CSRF/message lane:
  `168 passed` in `59.40s`.
- First full hermetic run: `1 failed / 1024 passed / 17 deselected` in `399.46s`.
  The sole deterministic stale assumption at
  `tests/test_phase4_requisicoes_blueprint.py:432` compared historical B4.2 CSRF
  snapshots against moving HEAD, which now already contained published B4.2 snapshots
  and yielded zero deltas.
- Mutation froze; state was reconciled; the user explicitly authorized exactly that
  one extra test path in B5-P-R1. The direct minimal correction introduced
  `B4_2_BASELINE_COMMIT=c587098152e97d125f41a2d26f2f414c10ae5676` and replaced only
  HEAD with that fixed reference.
- Required classification verbatim:
  `PRE_REVIEW_SCOPE_EXPANSION / NOW_EXPLICITLY_RATIFIED /
  NO_RETROACTIVE_GENERIC_AUTHORITY`.
- R1 exact node: `1 passed` in `0.68s`. The read-only comparison proves exactly five
  owner-only deltas for each shadow-off/on snapshot, the exact five Requisições POST
  routes, `main.<handler>` → `app.views.admin.requisicoes.<handler>`, and all other
  fields equal.
- A later full run was externally interrupted before result, with no mutation or
  postcondition impact; it is not treated as a physical failure or final result.
- B5-P-R2 SUPPLEMENTAL SCOPE AUTHORIZATION added and modified only
  `tests/test_phase4_requisicoes_shared_owners.py`: it reads accepted B4.1 governance
  from fixed commit `c587098152e97d125f41a2d26f2f414c10ae5676`, preserves B4.1
  closure/publication/assertions, and separately proves current B4.2 CLOSED / ACCEPTED,
  B5-P IMPLEMENTED / AWAITING SUPERVISOR REVIEW, Phase 4 OPEN, Phase 5 and Phase 6 NOT
  AUTHORIZED, Migration v4 PROHIBITED. No unrelated assertion was weakened. Required
  classification verbatim: `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED_B5_P_R2 /
  FIXED_ACCEPTED_B4_1_BASELINE / NO_RETROACTIVE_GENERIC_AUTHORITY`.
- R2 exact node: `1 passed` in `1.02s`. Affected governance aggregate: `118 passed` in
  `16.70s`.
- Final full hermetic after R2: total collected 1042 = 1025 passed + exactly 17 D73H
  deselected; 0 failed; 0 errors; `326.74s`; exit 0. The earlier
  `1025 passed / 17 deselected / 306.41s` run is only pre-R2 historical evidence, not
  final.
- Independent-review rerun of the final candidate: 1025 passed / 17 deselected /
  0 failed / 0 errors / `367.27s` / exit 0.
- Post-publication focused lane: 132 passed / 0 failed / 0 errors / `39.23s`.
- Historical first full hermetic (stale B4.2 CSRF baseline): `1 failed / 1024 passed /
  17 deselected / 399.46s`; superseded after the B5-P-R1 fixed-baseline correction.
  All pre-publication pending statements are historical and superseded, not current.

## Execution and routing evidence

- Supervisor/IAsup: Hermes `openai-codex/gpt-5.6-sol`, direct adjudication and
  deterministic gates.
- TDD/implementation IAexec continuity session `ses_03ce1c465ffeb31XEcAo57hbC4`.
  Initial route `flash_free`; later explicit fallback to
  `opencode-go/deepseek-v4-flash` because FREE context exceeded the policy threshold,
  trigger `FALLBACK_FREE_CONTEXT_TOO_LARGE`. Recorded router costs available: RED
  correction `0.0008019144 USD`; GREEN `0.0009146312 USD`; test correction
  `0.0007943432 USD`. No silent escalation.
- B5-P-R1 direct IAsup correction rationale: the exact deterministic two-site
  fixed-reference test correction was already fully specified and independently
  proved; a fourth 234k-context delegated continuation would increase cost/context/risk
  without judgment value.
- Earlier B5-P governance authoring succeeded via `flash_normal`,
  `opencode-go/deepseek-v4-flash`, session `ses_03cb9cee8ffeyk6hJFuMcmRrgD`, exit 0,
  cost `0.0013047696 USD`, no fallback, exact six governance mutations. A later
  continuation attempt to that expired/nonexistent session failed with
  `FLASH_NORMAL_FAILED / Session not found / no session / no cost / no mutation`;
  recorded as a recoverable transport/session failure. The fresh explicit delegation
  then succeeded via `flash_normal`, `opencode-go/deepseek-v4-flash`, session
  `ses_03c9ae6a7ffe4XeucPqy9Iyrre`, exit 0, cost `0.0005911248 USD`, with no fallback
  and mutations limited to the same six governance paths.
- The R2 test correction was a direct IAsup Sol correction because it was
  deterministic, exact, tiny, and safer/cheaper than another context export.
- **Accepted independent review (post-publication):** provider `opencode`, model
  `opencode/deepseek-v4-flash-free`, session `ses_03c92c10affegAmZLZ63tmTjjA`,
  exit 0, cost 0, fallback none, mutation 0, blocking findings 0, nonblocking
  findings 3 (R2 no literal `NO ROUTE MOVEMENT` token; `B4_2_BASELINE_COMMIT`
  naming; runtime duration changed). External acceptance GRANTED by the
  PHASE 4-B5-P-R3 order.

## Candidate manifest (exact 11 changed paths) and ceiling

After these six governance writes, the actual candidate manifest is exactly **11
changed paths**: 2 production + 3 tests + 6 governance.

Production (2):

- `app/admin_access.py`
- `main.py`

Tests (3):

- `tests/test_phase4_matrizes_shared_owners.py` (new)
- `tests/test_phase4_requisicoes_blueprint.py` (mechanical fixed-baseline correction)
- `tests/test_phase4_requisicoes_shared_owners.py` (B5-P-R2 supplemental scope
  authorization; reads accepted B4.1 governance from fixed commit
  `c587098152e97d125f41a2d26f2f414c10ae5676`)

Governance (6):

- `AGENT_HANDOFF.md`
- `PROJECT_STATE.md`
- `docs/DOCUMENTATION_INDEX.md`
- `docs/mapeamento/05_avaliacao_refactor.md`
- `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
- `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md`

The updated authorized ceiling is 12: 2 production + pool of 4 tests + 6 governance.
The authorized but unchanged `tests/test_ref_0c_b1_p0_access_context_transactions.py`
remains a **gate**, not a changed path. Do not claim 12 changed paths.

## Irreversible boundaries

- Repository mutation: crossed only for the exact source/test/governance manifest.
- Technical commit, technical push and independent technical read-only review: **COMPLETE**. Technical commit
  `92486f87ea15697282a265cb7a9941678cb9138f` is published; publication and
  post-publication verification are COMPLETE; external acceptance is GRANTED.
- This B5-P-R3 closeout changes only the six governance paths; it changes no
  production, test, snapshot, database, migration, schema, route, RBAC, template,
  static or transaction path.
- No Matrizes route moved; `app/views/admin/matrizes.py` remains absent; B5 blueprint
  extraction remains NOT AUTHORIZED.

## Final current status

`PHASE4_B5_P_CLOSED / ACCEPTED / ADMIN_ACCESS_NEUTRAL_OWNER_ESTABLISHED /
EXACT_FIVE_SHARED_SYMBOLS / MAIN_IDENTITY_REEXPORTS_PRESERVED /
ZERO_LOCAL_MAIN_BODIES_FOR_FIVE / TRANSACTION_NEUTRALITY_PRESERVED /
ZERO_ROUTE_MOVEMENT /
ROUTES_131 / ENDPOINTS_130 / BUSINESS_PAIRS_160 / GOVERNED_PAIRS_134 /
RBAC_UNMAPPED_ZERO / ACTOR_402_263_139 / MESSAGE_CATALOG_536 /
ROUTE_INVENTORY_BYTE_IDENTICAL / CSRF_SHADOWS_BYTE_IDENTICAL /
FULL_HERMETIC_1025_17 / INDEPENDENT_REVIEW_PASS / TECHNICAL_COMMIT_92486F87 /
PUBLICATION_VERIFIED / GOVERNANCE_CLOSEOUT_PUBLISHED`.

No B5-P technical action remains. PHASE 4 remains OPEN / INCREMENTAL IMPLEMENTATION.
PHASE 4-B5 is NOT AUTHORIZED BY THIS CLOSEOUT. Do not begin
`app/views/admin/matrizes.py`; later cohorts remain NOT AUTHORIZED.
