# PROJECT_STATE — live state

Branch: `refactor/architecture-safety-net`
HEAD: current Git HEAD — authoritative value: `git rev-parse HEAD`
Plateau landing parent: `230de41b3439a60951049e9021d6b0063f3bc2db`
UT-9 entry parent: `7909b2d59b2de987d84dc859a15bede215a3261b`
UT-10 entry parent: `e8f64a8244196b1c7acd634c9f78fbde29d70ef9`
UT-11 entry parent: `a0092149c2c596f90932b8f83991a33e1f98c32c`
UT-12 entry parent: `4820e4d3a46a1a3564c730d384b86aa989d752c9`
UT-13 entry parent: `2e0afa34ed1b927014ac35875668bbdc132743ad`
UT-14 entry parent: `ef7bc0302cc86b4fa37f301be8157363922e51e7`
UT-15 entry parent: `37316d6dc2f3f55c050152e6b4ae835074ccdac6`
Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`
Rewritten once per UT; history in `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`.

Last completed UT: UT-17 — Infra — CLOSED / ACCEPTED / PUBLISHED (published by
this UT-17 landing commit; landing SHA not invented). UT-17 entry parent:
`511f1c368cae9b7da54fdc42585c9917dc8ac59d`.
Last completed work: UT-17
3 routes moved (`uploaded_file` → `app/views/files.py`; `health`/`favicon` →
create_app composition-local, como `/csrf-token`); main local `@app.route` = 0.
REFACTOR ESTRUTURAL COMPLETO — CLOSED / ACCEPTED / PUBLISHED (published by the
final UT-17 landing commit; landing SHA not invented). Chronology: technical
qualification occurred before governance; governance records the technically
proven final state; canonical publication occurs only when this governance +
the UT-17 technical patch land in the single commit and remote verification
succeeds. There is NO UT-18; the roadmap technical sequence is exhausted.
0 routes moved. Criterion-9 residual ownership resolved: Group A removed
main-local `_coerce_aluno_snapshot_scalar` / `_build_aluno_requisicao_snapshot_display`
(canonical owner `app/views/aluno.py`, no facade); Group B removed main-local
`UPPER_CODE_RE` (canonical owner
`app/views/admin/alunos_turmas_cursos.py`, no facade); Group C moved
`validar_integridade_versionamento_atividades` MOVE-DO-NOT-CHANGE to
`app/versioning/integrity.py` (fingerprint
`c6ad435ba8a5ccd970c67e5e8f8e6fb17b1cc83fa63be366b4518410bb2a235d`) with
main exact identity facade only. Message scanner explicitly registers
`app/versioning/integrity.py`; catalog 536. Prior landings: UT-15 Demo
extraction (parent `37316d6d`); UT-14 Meus Dados (parent `ef7bc030`);
UT-13 Dashboard (parent `2e0afa34`); UT-12 Reportes (parent `4820e4d3`);
UT-11 Alertas (parent `a0092149`); UT-10 Arquivos (parent `e8f64a82`);
C4 request-hook write isolation + STRUCTURAL PLATEAU publication
(Phase-H landing commit, parent `230de41b`).
Next UT: NONE — FINAL ROADMAP COMPLETE.

## STRUCTURAL PLATEAU — VALIDATED / PUBLISHED

Published by this Phase-H landing commit (subject `Validate structural plateau request-hook
isolation`, parent `230de41b`). Governing criteria text: `docs/refactor/EXECUTION_PROTOCOL.md`
§3, **Protocol v1.4 — 2026-08-10**.

| # | Criterion | Verdict |
|---|---|---|
| C1 | `hooks_main` | PASS |
| C2 | `create_app` composition root | PASS |
| C3 | reverse dependency `app`/`services`/`utils` → `main` | PASS |
| C4 | request-hook write isolation (Protocol v1.3) | PASS |
| C5 | RBAC completeness | PASS |
| C6 | route inventory / actor matrix | PASS |
| C7 | canonical full suite | PASS |

criteria: **7/7** — 0 material findings.

**Formal validation history — both results stand, they are not the same criterion text.**
The FIRST formal validation, under the Protocol **v1.2** literal wording
("Nenhuma escrita em disco, banco ou rede dentro de hook de requisição"), returned
**6/7 PASS — C4 FAIL**, and that result remains valid under v1.2. A supervisor-authorized
versioned definition correction (v1.3) then distinguished durable application-state writes
from preconfigured local diagnostic observability. The SECOND formal validation, under v1.3,
returned **7/7 PASS**. The first FAIL is not erased, not rewritten, and not retroactively a
PASS; it was added to governance for the first time by this landing commit, as historical
reconciliation. Detail: `EXECUTION_PROTOCOL.md` Changelog v1.3 and the ledger block
"Plateau estrutural — validação formal, correção de definição e publicação".

### C4 outcome (measured)

- request-hook application-state SQL writes: **0**
- request-time access schema repair/normalization: **0**
- request-time `mensagens_editaveis` schema repair: **0**
- generic `get_db_connection` persistent journal-mode mutation: **0**
- `init_db` owns WAL establishment and schema bootstrap: **yes**
- synchronous, preconfigured, LOCAL RBAC/CSRF diagnostic logging: permitted observability
  under Protocol v1.3 (no handler construction/mutation in hooks; no `QueueHandler`; no
  background logging thread; no network-backed handler)
- hook network/provider writes: **0**

## UT-10 — Arquivos — CLOSED / ACCEPTED / PUBLISHED

Published by this UT-10 landing commit (subject `Extract admin files routes`,
entry parent `e8f64a8244196b1c7acd634c9f78fbde29d70ef9`).

Owner: `app/views/admin/arquivos.py`.

Extracted cohort: 5 routes / 6 endpoint-method pairs / 4 cohort-local helpers
(9 symbols, 0 constants). Compatibility facade: `main` identity re-exports =
9/9 (no wrappers, no duplicated implementation).

Boundaries preserved: Alertas/Reportes remain main-owned = 7/7; `uploaded_file`
remains main-owned; UT-11 NOT STARTED.

Canonical current invariants (measured): routes 131 / distinct endpoints 130 /
RBAC unmapped 0 / actor matrix 402 / message catalog 536 / hooks_main 0 /
reverse dependencies app/services/utils → main 0 / SCHEMA_VERSION 3 /
migrations v1/v2/v3 only / after_request[None] exactly
`flask_compress.flask_compress.after_request` and `app._apply_security_headers`
/ teardown_appcontext canonical owner `app.db.close_db_connection`.

The first canonical UT-10 suite exposed exactly four historical
test-expectation integration gaps: 3 cumulative CSRF ownership-count contracts
(B6 environment 27→30, Matrizes 35→38, Requisições 40→43) and 1 exact
`app/views/admin` package-inventory contract. These were reconciled exactly,
with no production change: UT-10 Arquivos adds exactly 3 CSRF owner-only
transitions (`main.admin_adicionar_arquivo` / `main.admin_editar_arquivo` /
`main.admin_deletar_arquivo` → `app.views.admin.arquivos.*`); `arquivos.py`
added to the exact admin-package inventory and the no-main-import audit.
Canonical retry passed completely.

Canonical full-suite status: 1345 collected / 1328 passed / 17 deselected /
0 failed / 0 errors / 0 skipped / 345.89s.

Structural plateau remains: VALIDATED / PUBLISHED. C4 remains: CLOSED /
ACCEPTED / PUBLISHED. Protocol remains: v1.4.

## UT-11 — Alertas — CLOSED / ACCEPTED / PUBLISHED

Published by this UT-11 landing commit (subject `Extract admin alerts routes`,
entry parent `a0092149c2c596f90932b8f83991a33e1f98c32c`).

Owner: `app/views/admin/alertas.py`.

Extracted cohort: 4 routes / 4 endpoint-method pairs / 3 helper functions /
1 cohort-local constant (8 moved symbols). Compatibility facade: `main`
identity re-exports = 8/8 (no wrappers, no copied constant). Factory:
`register_admin_alertas_blueprint` default = true.

Boundaries preserved: Reportes remain main-owned = 3/3; Arquivos remains
`app/views/admin.arquivos`-owned; shared owners remain
`ensure_admin_alertas_table` → `app.db_maintenance` and
`list_active_admin_alertas` → `app.admin_alerts`; `uploaded_file` remains
main-owned; UT-12 NOT STARTED.

Canonical current invariants (measured): routes 131 / distinct endpoints 130 /
RBAC unmapped 0 / actor matrix 402 / message catalog 536 / hooks_main 0 /
reverse dependencies app/services/utils → main 0 / SCHEMA_VERSION 3 /
migrations v1/v2/v3 only / after_request[None] exactly
`flask_compress.flask_compress.after_request` and `app._apply_security_headers`
/ teardown_appcontext canonical owner `app.db.close_db_connection`.

UT-11 test-contract seam (supervisor-classified TEST_CONTRACT_SEAM, no
production defect, no architecture change, no UT-10 production reopening):
the initial UT-11 implementation exposed two GREEN controls that encoded
pre-extraction state rather than state-invariant contracts, and one UT-10
historical GREEN permanently required Alertas to remain in main. The seams
were corrected to be state-aware and exact: the guarded loader distinguishes
absent/present real target; the CSRF control distinguishes coherent pre/post
ownership without deriving expectations from snapshots; the historical UT-10
contract keeps Reportes permanently main-owned while allowing Alertas to move
only when its real canonical target exists; main compatibility requires
identity, not wrappers. Reportes remained strictly main-owned. Final UT-11
RED = 28/28; historical UT-10 contract = 26/26; canonical full suite passed
completely.

Canonical superseding test SHAs: UT-11
`C0BE5F1593106A3F9A948EE0124A8EBF9E395422478708C762C286374BFB1905` (superseding
`32207A77…`); UT-10
`E24648784C21ABC495E3B45954AE7011DBDB5ECD95487015597F4DD864BBCC07`
(superseding `578ADB5F…`).

Canonical full-suite status: 1373 collected / 1356 passed / 17 deselected /
0 failed / 0 errors / 0 skipped / 368.73s.

Structural plateau remains: VALIDATED / PUBLISHED. C4 remains: CLOSED /
ACCEPTED / PUBLISHED. Protocol remains: v1.4.

## UT-12 — Reportes — CLOSED / ACCEPTED / PUBLISHED

Published by this UT-12 landing commit (subject `Extract admin reports routes`,
entry parent `4820e4d3a46a1a3564c730d384b86aa989d752c9`).

Owner: `app/views/admin/reportes.py`.

Extracted cohort: 3 routes / 3 endpoint-method pairs / 1 helper function /
1 cohort-local constant (`REPORTE_STATUS_OPTIONS`) — 5 moved symbols total.
Compatibility facade: `main` identity re-exports = 5/5 (no wrappers, no copied
constant). Factory: `register_admin_reportes_blueprint` default = true.

Canonical shared owners preserved: `REPORTE_CATEGORY_OPTIONS` remains in
`app.reporting`; `ensure_reportes_table` remains in `app.db_maintenance`.

Boundaries preserved: Dashboard remains main-owned; Alertas remains
`app.views.admin.alertas`; Arquivos remains `app.views.admin.arquivos`;
UT-13 NOT STARTED.

Canonical current invariants (measured): routes 131 / distinct endpoints 130 /
RBAC unmapped 0 / actor matrix 402 / message catalog 536 / hooks_main 0 /
reverse dependencies app/services/utils → main 0 / SCHEMA_VERSION 3 /
migrations v1/v2/v3 only / after_request[None] exactly
`flask_compress.flask_compress.after_request` and `app._apply_security_headers`
/ teardown_appcontext canonical owner `app.db.close_db_connection`.

UT-12 test-contract seam (supervisor-authorized TEST_CONTRACT_SEAM /
LEGITIMATE_UT12_COCHANGE — no production defect, no architecture change, no
UT-10/UT-11 reopening): historical UT-10/UT-11/B7-P contracts correctly
encoded Reportes main residency in their original states but became stale when
UT-12 legitimately extracted Reportes. The supervisor explicitly authorized
narrow state-aware reconciliation. Replacement semantics: real reportes target
absent → historical main ownership expected; real target present → exact
`app.views.admin.reportes` ownership; main compatibility requires identity;
mixed ownership rejected; Arquivos, Alertas and Dashboard protections
preserved. Not: UT10_REOPEN / UT11_REOPEN / PRODUCTION_FIX / ARCHITECTURE_CHANGE.

Canonical full-suite status: 1399 collected / 1382 passed / 17 deselected /
0 failed / 0 errors / 0 skipped / 377.54s.

Structural plateau remains: VALIDATED / PUBLISHED. C4 remains: CLOSED /
ACCEPTED / PUBLISHED. Protocol remains: v1.4.

## UT-13 — Dashboard — CLOSED / ACCEPTED / PUBLISHED

Published by this UT-13 landing commit (subject `Extract admin dashboard route`,
entry parent `2e0afa34ed1b927014ac35875668bbdc132743ad`).

Owner: `app/views/admin/dashboard.py`.

Extracted cohort: 1 route (`admin_dashboard`, GET `/admin/dashboard`) /
1 endpoint-method pair / 9 helper functions (`_build_admin_dashboard_turma_cards`,
`periodo_corrente`, `_format_dashboard_hours`, `_format_dashboard_average`,
`_format_dashboard_days`, `_calculate_pending_response_metrics`,
`get_admin_new_request_alert`, `mark_admin_new_request_alert_seen`,
`_admin_request_alert_kind`) — 10 moved symbols total. Compatibility facade:
`main` identity re-exports = 10/10 (no wrappers, no duplicated implementation).
Factory: `register_admin_dashboard_blueprint` default = true, registered through
exactly one `register_legacy_blueprint`; opt-out removes exactly
`admin_dashboard`. LegacyRouteSpecs: 1; endpoint/method pairs: 1 (no HEAD pair).

Behavior: MOVE, DO NOT CHANGE — SQL / query ordering / filters / counts /
metric calculations / template and context / session reads / `g._adm_dash_metrics`
and `g._adm_dash_ts` 30-second cache / `conn.commit` timing /
`auto_indefer_devolvidas` behavior / request-alert behavior /
`list_active_admin_alertas` behavior / turma-card closure (periodo_corrente,
`get_effective_matriz_for_turma`, `ensure_turmas_matriz_schema`, attainment,
Total Geral, formatters, `DEFAULT_CURSO_TOTAL_HORAS_AAC/AEU`) / pending-response
metrics preserved. Pre-existing request-path write/bootstrap behavior remains
debt and was not remediated.

Neighbors explicitly remain main-owned (hard boundary, both states):
`admin_demo_clientes_form_pack` and `admin_meus_dados`.
`admin_meus_dados` is NOT part of UT-13 and remains candidate for separate
future work. Canonical dependency owners preserved (`list_active_admin_alertas`
→ app.admin_alerts; `ensure_requisicao_alert_receipts_table` →
app.db_maintenance; `ensure_turmas_matriz_schema` → app.db;
`get_effective_matriz_for_turma` → app.matrix_scope;
`DEFAULT_CURSO_TOTAL_HORAS_AAC/AEU` → app.academics; `auto_indefer_devolvidas`
→ app.requisitions; `get_response_time_settings` → app.settings;
`_parse_optional_processing_datetime` → app.requisition_policy;
`canonicalize_access_level`/`default_access_level_for_user_type`/`admin_required`
→ app.auth; `resolve_user_message` → utils.messages).

Sequential owners: Arquivos `app.views.admin.arquivos`; Alertas
`app.views.admin.alertas`; Reportes `app.views.admin.reportes`; Dashboard
`app.views.admin.dashboard`.

Canonical current invariants (measured): routes 131 / distinct endpoints 130 /
RBAC unmapped 0 / actor matrix 402 / message catalog 536 / hooks_main 0 /
reverse dependencies app/services/utils → main 0 / SCHEMA_VERSION 3 /
migrations v1/v2/v3 only / after_request[None] exactly
`flask_compress.flask_compress.after_request` and `app._apply_security_headers`
/ teardown_appcontext canonical owner `app.db.close_db_connection`.

UT-13 historical seam reconciliation (supervisor-classified TEST_CONTRACT_SEAM /
LEGITIMATE_UT13_COCHANGE — no production defect, no architecture change, no
UT-12/UT-11/UT-10 reopening, not UT12_REOPEN / PRODUCTION_FIX / BUSINESS_CHANGE):
the UT-12 Dashboard ownership contracts
(`test_red_m_target_owns_reportes_routes_dashboard_stays_main` →
`test_red_m_target_owns_reportes_routes_and_dashboard_split_state_aware`,
`test_green_8_dashboard_remains_main_owned` →
`test_green_8_dashboard_ownership_state_aware`), the Alunos/Turmas Dashboard
helper ownership contracts
(`test_periodo_corrente_unchanged_against_baseline_and_still_main_local` →
`test_periodo_corrente_unchanged_against_baseline_and_state_aware_owner`),
the Alunos/Turmas shared-owner `periodo_corrente` contract
(`test_periodo_corrente_stays_in_main` →
`test_periodo_corrente_ownership_state_aware`), the Requisicoes Dashboard
ownership clause
(`test_no_matriz_aluno_or_dashboard_route_was_moved` →
`test_no_matriz_aluno_route_was_moved_and_dashboard_ownership_state_aware`),
the Arquivos/Alertas Dashboard baseline ownership
(`test_b7p_admin_dashboard_unchanged_from_entry_baseline`, name kept) and the
Configuracoes exact admin package inventory (+ `dashboard.py` only) were
reconciled narrowly. Replacement semantics: real dashboard target absent →
historical main ownership valid; real target present → all 10 Dashboard symbols
exact target-owned + main identity facade 10/10; mixed ownership rejected;
neighbors remain main-owned in both states. Reportes/Alertas/Arquivos
protections were not weakened.

UT-13 RED correction (RED_CONTRACT_DEFECT / RESOLVED): the initial UT-13 RED
(SHA `3ba52bf3743588348242a144f462c3c7e656ef242bf18da17c9a2c4b5fe8ad6f`)
contained a contradictory factory-neighbor requirement — `test_red_j` demanded
the main-owned neighbors `admin_demo_clientes_form_pack` and
`admin_meus_dados` inside `create_app` instances, contradicting the accepted
architecture (neighbors are registered only on `main.app` via `@app.route` and
are never factory-registered, as `test_green_16` correctly protects).
Supervisor-authorized narrow correction removed exactly the contradictory
positive-neighbor factory assertions; no production byte was changed by or
because of this finding. Final frozen RED SHA:
`63a811794f136e087e47b624b1ec1a53f695138464f7a960b6291f9bded41ef2`.

Canonical full-suite status: 1429 collected / 1412 passed / 17 deselected /
0 failed / 0 errors / 0 skipped / 357.96s.

CSRF: Dashboard owner deltas = 0; historical cumulative totals remain
35 / 43 / 48; both canonical snapshots byte-identical to HEAD.

Structural plateau remains: VALIDATED / PUBLISHED. C4 remains: CLOSED /
ACCEPTED / PUBLISHED. Protocol remains: v1.4.

## UT-14 — Meus Dados — CLOSED / ACCEPTED / PUBLISHED

Entry parent: `ef7bc0302cc86b4fa37f301be8157363922e51e7`. Published by this
UT-14 landing commit; landing SHA not invented. Protocol v1.4 — 2026-08-10.

Owner: `app/views/admin/meus_dados.py`.

Extracted cohort: 1 route (`admin_meus_dados`, `GET` + `POST`,
`/admin/meus_dados`) / 2 business endpoint-method pairs / 0 cohort-local
helpers / 0 cohort-local constants (only the standard wiring assignments
`bp_admin_meus_dados` and `LEGACY_ROUTE_SPECS`). Compatibility facade: `main`
exact identity re-export only — `main.admin_meus_dados is
target.admin_meus_dados` (no wrapper, no copied implementation); main local
ownership = 0. Factory: `register_admin_meus_dados_blueprint` default = true,
registered through exactly one `register_legacy_blueprint`; default
registration = 1 route / 2 pairs; opt-out = 0 cohort routes.
LegacyRouteSpecs: 1 (`/admin/meus_dados` / `admin_meus_dados` / GET, POST).
Blueprint name: `admin_meus_dados_blueprint`.

Behavior: MOVE, DO NOT CHANGE — function body AST-identical to the removed
`main.py` route with decorators normalized (allowed differences: module
location, canonical imports, Blueprint/LegacyRouteSpec wiring, decorator
resolving directly from `app.auth`). SQL / query ordering / exactly one
success-path `conn.commit` / `ensure_usuario_profile_schema` on every GET /
`session["user_name"]` set before avatar handling / avatar-ValueError
continue-toward-commit / no explicit rollback / flash strings / template
context (`aluno_meus_dados.html`, `base_template="base.html"`,
`show_student_fields=False`, `cancel_url=url_for("admin_dashboard")`,
`turmas=[]`) preserved exactly. Pre-existing request-path write/bootstrap
behavior remains debt, was not remediated, and no C4/schema cleanup and no
migration v4 were introduced.

RBAC unchanged: GET → `meus_dados:view`; POST → `meus_dados:edit`.

CSRF: exactly one ownership transition in each canonical snapshot
(`main.admin_meus_dados` → `app.views.admin.meus_dados.admin_meus_dados`);
single row changed, only the `view_function` field; both snapshots stay at
78 rows and shadow_on/off remain coherent; no behavioral CSRF change.
Cumulative owner-transition totals: 36 / 44 / 49 (35 / 43 / 48 + 1 UT-14
owner-only transition). Route inventory baseline
`route_inventory_baseline.json`: byte-identical.

Boundaries preserved: `admin_demo_clientes_form_pack` remains main-owned
(UT-15 cohort); Dashboard `app.views.admin.dashboard`; Reportes
`app.views.admin.reportes`; Alertas `app.views.admin.alertas`; Arquivos
`app.views.admin.arquivos`; aluno profile routes and every UT-16 residual
symbol stay in their current owners. UT-15 NOT STARTED / NEXT.

Sequential owners: Arquivos `app.views.admin.arquivos`; Alertas
`app.views.admin.alertas`; Reportes `app.views.admin.reportes`; Dashboard
`app.views.admin.dashboard`; Meus Dados `app.views.admin.meus_dados`.

Authorized historical seams (supervisor pre-authorized, in exactly
`tests/test_ut13_dashboard_blueprint.py`,
`tests/test_ut12_reportes_blueprint.py` and
`tests/test_phase4_requisicoes_blueprint.py` — classified
TEST_CONTRACT_SEAM / LEGITIMATE_UT14_COCHANGE): narrow state-aware
meus_dados ownership transitions only (absent → main-owned; present →
`app.views.admin.meus_dados`); no weakening of any Dashboard/Reportes/
Requisicoes contract; Demo remains main-owned; mixed ownership rejected;
UT-10/UT-11/UT-12/UT-13 files not reopened.

Ratified UT-14 cochanges (supervisor-classified LEGITIMATE_UT14_COCHANGE, no
production defect, no architecture change):
- `tests/test_phase4_matrizes_blueprint.py` — cumulative CSRF transition
  43 → 44 (one Meus Dados ownership partition only)
- `tests/test_phase4_alunos_turmas_cursos_blueprint.py` — cumulative CSRF
  transition 35 → 36 (one Meus Dados ownership partition only)
- `tests/test_phase4_configuracoes_blueprint.py` — exact admin package
  inventory gains `meus_dados.py` only; no unrelated relaxation
- `tests/test_phase3_schema_startup_transaction_contract.py` — `main.init_db`
  caller manifest 75 → 76; added caller
  `tests/test_ut14_meus_dados_blueprint.py::_prepare_behavior_env`; no caller
  removed or relocated (delta independently reviewed and accepted)

No other scope expansion.

Frozen RED: `tests/test_ut14_meus_dados_blueprint.py` — 27/27 PASS;
SHA-256 `B3E3DFEE8BDC60C8CF55B89EA2CCDAC6F52C9B03B5A55FAC0FBDD23653DEBB5E`.

Qualification evidence: UT-14 gate 27/27; historical seam lane 77/77;
permanent contract lane 72/72; historical cochange/baseline lane 298/298;
independent review lane 190/190; C4 gate 36/36. Canonical full suite
(qualifying, pre-landing): 1456 collected / 1439 passed / 17 deselected /
0 failed / 0 errors / 0 skipped / 368.24s. Independent review: PASS /
0 material findings.

Canonical invariants unchanged: routes 131 / distinct endpoints 130 /
RBAC unmapped 0 / actor matrix 402 / message catalog 536 / hooks_main 0 /
app/services/utils → main 0 / SCHEMA_VERSION 3 / migrations v1/v2/v3 only.

Database unchanged: 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818`; no
sidecars.

Structural plateau remains: VALIDATED / PUBLISHED. C4 remains: CLOSED /
ACCEPTED / PUBLISHED. Protocol remains: v1.4.

## UT-15 — Demo — CLOSED / ACCEPTED / PUBLISHED

Entry parent: `37316d6dc2f3f55c050152e6b4ae835074ccdac6`. Published by this
UT-15 landing commit; landing SHA not invented. Protocol v1.4 — 2026-08-10.

Owner: `app/views/admin/demo.py`.

Extracted cohort: 1 route (`admin_demo_clientes_form_pack`, GET only
`/admin/demo/clientes-form-pack`) / 1 business endpoint-method pair /
0 cohort-local helpers / 0 cohort-local constants (only the standard wiring
assignments `bp_admin_demo` and `LEGACY_ROUTE_SPECS`). Compatibility facade:
`main` exact identity re-export only — `main.admin_demo_clientes_form_pack is
target.admin_demo_clientes_form_pack` (no wrapper, no copied implementation);
main local ownership = 0. Factory: `register_admin_demo_blueprint` default =
true, registered through exactly one `register_legacy_blueprint`; default
registration = 1 route / 1 pair; opt-out = 0 cohort routes.
LegacyRouteSpecs: 1 (`/admin/demo/clientes-form-pack` /
`admin_demo_clientes_form_pack` / GET). Blueprint name:
`admin_demo_blueprint`.

Behavior: MOVE, DO NOT CHANGE — function body preserved exactly
(`return render_template("demo_clientes_form_pack.html")`, no context kwargs,
no redirect, no DB, no session logic). The shared `dashboard:view`
authorization scope is authorization only and does NOT move Demo into
`dashboard.py`.

RBAC unchanged: GET → `dashboard:view`.

CSRF: zero owner transitions / zero mutating-row delta; historical cumulative
totals remain 36 / 44 / 49; rows remain 78; both canonical snapshots
repository-unchanged (no tracked delta, Git-canonical content unchanged;
CRLF/LF checkout materialization alone is not artifact mutation). Route
inventory baseline `route_inventory_baseline.json` unchanged.

Main remaining local `@app.route` handlers: `uploaded_file`, `health`,
`favicon` (count 3). Boundaries preserved: Dashboard `app.views.admin.dashboard`;
Meus Dados `app.views.admin.meus_dados`; Reportes `app.views.admin.reportes`;
Alertas `app.views.admin.alertas`; Arquivos `app.views.admin.arquivos`; every
UT-16 residual symbol stays in its current owner. UT-16 NOT STARTED / NEXT.

Sequential owners: Arquivos `app.views.admin.arquivos`; Alertas
`app.views.admin.alertas`; Reportes `app.views.admin.reportes`; Dashboard
`app.views.admin.dashboard`; Meus Dados `app.views.admin.meus_dados`; Demo
`app.views.admin.demo`.

Authorized historical seams (supervisor, classified TEST_CONTRACT_SEAM /
LEGITIMATE_UT15_COCHANGE): narrow state-aware demo ownership transitions in
`tests/test_ut14_meus_dados_blueprint.py` (red_j factory presence, red_m
ownership, green_6 sequential map), `tests/test_ut13_dashboard_blueprint.py`
(green_16 factory opt-out), `tests/test_ut12_reportes_blueprint.py` (two
Dashboard-neighbor ownership sites) and
`tests/test_phase4_configuracoes_blueprint.py` (exact admin package inventory
gains `demo.py` only). Late authorized additional seam:
`tests/test_ut13_dashboard_blueprint.py::test_green_8_neighbor_routes_hard_boundary_main_owned`
— found by the implementation-time seam lane (previously unknown historical
pin); reconciled state-aware: Demo absent → `main`; Demo present →
`app.views.admin.demo`; never Dashboard-owned. No UT-10/11/12 reopening.

RED defect / review history: initial UT-15 RED SHA
`F7E8BA0B3BBB69B7FB17ED4FC42198A5C1EBA125D24E7E38B6B75D5FC8531274`; first
independent adversarial review FAIL due to MATERIAL_TEST_CONTRACT_DEFECT in
the artifact-custody wording/semantics (CRLF/LF normalization described as
literal byte identity); no production defect, no artifact mutation. Corrected
custody semantics: Git-canonical repository-content identity + no tracked
artifact delta. Corrected RED SHA:
`7311F1A49E13096B643F66BBA7F9C901376832C9A4651B623161D51BDDC4D520`. Second
independent review: PASS / 0 material findings.

Frozen RED: `tests/test_ut15_demo_blueprint.py` — 26/26 PASS; SHA-256
`7311F1A49E13096B643F66BBA7F9C901376832C9A4651B623161D51BDDC4D520`.

Qualification evidence: UT-15 gate 26/26; historical seam lane 106/106;
sequential extraction / baseline lane 311/311; permanent + C4 lane 81/81.
Canonical full suite (qualifying, pre-landing): 1482 collected / 1465 passed
/ 17 deselected / 0 failed / 0 errors / 0 skipped / 413.52s.

Canonical invariants unchanged: routes 131 / distinct endpoints 130 /
RBAC unmapped 0 / actor matrix 402 / message catalog 536 / hooks_main 0 /
app/services/utils → main 0 / `main.init_db` callers 76 / SCHEMA_VERSION 3 /
migrations v1/v2/v3 only / main local `@app.route` handlers 3.

Database unchanged: 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818`; no
sidecars. Artifacts `csrf_inventory_shadow_on.json`,
`csrf_inventory_shadow_off.json`, `route_inventory_baseline.json`: no tracked
delta, Git-canonical content unchanged (CRLF/LF materialization from checkout
normalization is not artifact mutation).

Structural plateau remains: VALIDATED / PUBLISHED. C4 remains: CLOSED /
ACCEPTED / PUBLISHED. Protocol remains: v1.4.

## UT-16 — Residual Main Ownership — CLOSED / ACCEPTED / PUBLISHED

Entry parent: `d217c40ffa676cd023fb327cb36eece52eb6b253`. Published by this
UT-16 landing commit; landing SHA not invented. Protocol v1.4 — 2026-08-10.
Routes moved: 0.

Criterion-9 blocker groups resolved (supervisor-adjudicated scope):
- **Group A — Aluno snapshot ownership:** removed main-local
  `_coerce_aluno_snapshot_scalar` / `_build_aluno_requisicao_snapshot_display`
  (dead divergent duplicates); canonical owner `app/views/aluno.py`; no main
  facade retained.
- **Group B — Cursos/Turmas constant ownership:** removed main-local
  `UPPER_CODE_RE` (identical duplicate); canonical owner
  `app/views/admin/alunos_turmas_cursos.py`; no main facade retained.
- **Group C — Versioning integrity ownership:** moved
  `validar_integridade_versionamento_atividades` MOVE-DO-NOT-CHANGE from
  `main.py` to `app/versioning/integrity.py`; canonical normalized AST
  fingerprint `c6ad435ba8a5ccd970c67e5e8f8e6fb17b1cc83fa63be366b4518410bb2a235d`;
  main retains exact identity compatibility facade only
  (`main.validar_integridade_versionamento_atividades is
  app.versioning.integrity.validar_integridade_versionamento_atividades`).

Criterion-9 blockers after UT-16: **0**.

Explicit non-scope (deliberately NOT removed): `proximo_numero_turma`,
`_login_attempts`, `_APP_DIR`, `_TEMPLATES_DIR`, compatibility
wrappers/stubs/rebinds, identity facades generally. D-3 remains deferred. No
generic main.py cleanup; no route behavior changed.

Message scanner: `utils/messages.py::_iter_backend_files()` now explicitly
includes `app/versioning/integrity.py` (message-bearing validator moved out of
main.py; `app/versioning/**` is not recursively scanned). Catalog: **536**,
zero semantic delta.

Authorized test-contract cochanges (TEST_CONTRACT_SEAM /
LEGITIMATE_UT16_COCHANGE):
- `tests/test_phase4_versioning_subsystem.py` — exact `app/versioning`
  package inventory gains `integrity.py` only; audit preserved (no import
  main, no CREATE/ALTER TABLE, no SCHEMA_VERSION, forbidden-domain audit).
- `tests/test_phase4_configuracoes_blueprint.py` — backend message-scanner
  explicit allow-set gains exactly `app/versioning/integrity.py`; no
  prefix/wildcard/subset relaxation; sorted/unique and catalog constraints
  preserved.

Frozen RED: `tests/test_ut16_residual_main_ownership.py` — 15 tests; SHA-256
`D55063AC2C6063DD76034CBF7AA574A3F58B9C9D4164A3114D6B7454FD07B297`; final
gate 15/15; no retired tests.

Review / defect history (not sanitized): Independent Review R1 **REJECT** —
MATERIAL_PROCESS_DEFECT_WITH_RESIDUAL_PRODUCTION_DAMAGE: scripted main.py
editing used a stale/original line index after earlier deletions and
accidentally removed `elif user_type == "aluno":` inside UT-17-owned
`uploaded_file` (real authorization behavior damage before correction).
Correction: single-line restoration from HEAD; proofs:
`uploaded_file` AST match to HEAD = True; normalized source match to HEAD =
True; exhaustive main.py scope audit found no second collateral victim, no
residual damage. Disposition: MATERIAL_DEFECT_CORRECTED / NO_RESIDUAL_DAMAGE.
Independent Review R2 **ACCEPT**. R2 report metadata anomaly (recorded
truthfully): the "EFFECTIVE MODEL / PROVIDER" field was malformed as
"FALLBACK" and the report contained a contradictory "FULL SUITE
AUTHORIZATION: NO"; supervisor adjudicated NON_MATERIAL_REPORT_METADATA_DEFECT;
technical ACCEPT remained valid; the full suite was explicitly authorized
afterward. No invented R2 provider/model metadata.

Full-suite history (both runs preserved):
- First canonical suite: 1497 collected / 1479 passed / 17 deselected /
  0 skipped / 1 failed / 0 errors — failure
  `test_phase4_configuracoes_blueprint.py::test_backend_message_inventory_recurses_deterministically_without_duplicates`
  (previously unknown exact message-scanner file-set pin; classification
  TEST_CONTRACT_SEAM / LEGITIMATE_UT16_COCHANGE; no production defect).
- After the authorized exact-set cochange — FINAL CANONICAL SUITE: 1497
  collected / 1480 passed / 17 deselected / 0 skipped / 0 failed / 0 errors /
  322.69s / exit 0. Count reconciliation: 1482 UT-15 baseline + 15 UT-16 RED
  tests = 1497; no tests retired.

Qualification evidence: UT-16 gate 15/15; versioning subsystem 14/14;
Phase-B versioning behavior 13/13; domain ownership lane 63/63; permanent/C4
lane 77/77; uploaded_file behavioral set (after material-defect correction)
47/47; configuracoes gate (after final seam) 23/23. Independent review final
disposition: ACCEPT / 0 remaining material findings.

UT-17 firewall: main local `@app.route` handlers remain exactly
`uploaded_file`, `health`, `favicon` (3), all HEAD-identical after the defect
correction. Carry-forward planning inputs (measured coverage gaps, NOT UT-16
defects): (1) no explicit authorized-admin direct GET 200 test for
`uploaded_file`; (2) no explicit aluno accessing another aluno's file → 403
test.

Invariants (final): routes 131 / distinct endpoints 130 / RBAC unmapped 0 /
actor matrix 402 / message catalog 536 / hooks_main 0 / app-services-utils →
main 0 / `main.init_db` callers 76 / SCHEMA_VERSION 3 / migrations v1/v2/v3
only / main local routes 3.

Criterion 9: SATISFIED for all UT-16 residual ownership blockers. Criterion
8: NOT YET SATISFIED (3 `@app.route` handlers remain for UT-17). Therefore
REFACTOR ESTRUTURAL COMPLETO: NOT YET DECLARABLE.

Database unchanged: 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818`; no
sidecars. Artifacts `csrf_inventory_shadow_on.json`,
`csrf_inventory_shadow_off.json`, `route_inventory_baseline.json`: no tracked
delta, Git-canonical content unchanged.

Structural plateau remains: VALIDATED / PUBLISHED. C4 remains: CLOSED /
ACCEPTED / PUBLISHED. Protocol remains: v1.4.

HEAD: `b632edf90e2397abb145edc5d47e5a89bd48f078`. Census type: read-only.
Files altered during census: 0. Protocol v1.4 — 2026-08-10.

The post-UT-13 census measured exactly 5 remaining `@app.route` handlers in
`main.py`: `admin_demo_clientes_form_pack`, `admin_meus_dados`, `uploaded_file`,
`health`, `favicon`. This falsified the old live roadmap assumption that UT-13
resolved dashboard + demo + meus_dados (3 routes). UT-13 extracted Dashboard
only; demo and meus_dados remain main-owned. Criterion 8 (zero `@app.route` after
final completion) therefore requires additional UTs to resolve the residual 5
routes. The residual census also identified main-local non-route symbols that
may affect Criterion 9; these are catalogued as evidence/input for UT-16.

Revised remaining roadmap (governance-only; no production change):
- UT-14 — Meus Dados: `admin_meus_dados` → `app/views/admin/meus_dados.py` (1 route, GET+POST)
- UT-15 — Demo: `admin_demo_clientes_form_pack` → `app/views/admin/demo.py` (1 route, GET only)
- UT-16 — Residual Main Ownership: eliminate main-local non-facade duplication preventing Criterion 9
- UT-17 — Infra: `uploaded_file` → `app/views/files.py`; `health`/`favicon` → `create_app` (3 routes)
REFACTOR ESTRUTURAL COMPLETO: declarable only after UT-17 and only if Criteria 1-9 all pass.

Criterion 4 v1.3 unchanged. Database/schema policy unchanged. Invariants unchanged.
Historical planning records preserved; the old grouping (Dashboard + demo + meus_dados)
is not rewritten. UT-14 Meus Dados: NOT STARTED / NEXT.

## UT-17 — Infra — CLOSED / ACCEPTED / PUBLISHED

Entry parent: `511f1c368cae9b7da54fdc42585c9917dc8ac59d`. Published by this
UT-17 landing commit; landing SHA not invented. Protocol v1.4 — 2026-08-10.
Routes moved: 3.

Final ownership:
- `uploaded_file` (`/uploads/<path:filename>`, endpoint `uploaded_file`, GET) →
  `app/views/files.py`, registered via `create_app` → `app.add_url_rule` with
  duplicate guard; no Blueprint, no LegacyRouteSpec, no factory flag, no
  endpoint namespace, no app→main backedge. MOVE-DO-NOT-CHANGE fingerprints:
  args `58079bef5f8ba39f54d2838c1eb3f292fa1a93a3b23b85930c76aa4196bb91ed`,
  body `e29270ac0d7c92a5d1015990d33e4ebd3f0125b3078d70b453156c00076bc768`.
  Security/behavior preserved: anonymous redirect; traversal/containment 403;
  admin `arquivos:view` authorization; aluno own/foreign ownership; docs vs
  uploads roots; fail-closed DB; nosniff + `private, no-store` headers. UT-16
  carried-forward gaps CLOSED by the UT-17 RED: authorized-admin direct GET
  200 (covered) and aluno accessing another aluno's file → 403 (covered).
- `health` (`/health`, endpoint `health`, GET) → create_app composition-local
  (module `app`, qualname `create_app.<locals>.health`); SELECT 1 →
  `200 {"status":"ok"}`; exception → logger channel "main",
  `500 {"status":"error"}`, no leak. Canonicalized baseline fingerprint
  (health_logger→logger): `ac74eb097f396d1e2328098507a2d536e43f392d742ad38724e836d5af1ea140`.
- `favicon` (`/favicon.ico`, endpoint `favicon`, GET) → create_app
  composition-local (module `app`, qualname `create_app.<locals>.favicon`);
  `app.root_path/static/favicon.ico` present → 200, absent → 204. Body
  fingerprint: `57cb890b3f6f30007af7dc4bb16efd9ee11b7bd7bc42e092b49af0ac59b61e90`.

main final state: local `@app.route` = 0; local FunctionDefs
`uploaded_file`/`health`/`favicon` removed; compatibility surfaces identity-only
(`main.<name> is` live canonical callable, no wrappers). No generic main
cleanup; D-3 remains deferred/non-required under Protocol v1.4 (not a blocker).

Authorized historical seams (TEST_CONTRACT_SEAM / LEGITIMATE_UT17_COCHANGE):
A. UT-10 `test_green_9_uploaded_file_boundary_main_owned_outside_cohort`
state-aware canonical-owner transition; B. B7-P
`test_b7p_uploaded_file_unchanged_from_entry_baseline` retired under Protocol
§8 — exactly ONE test retired, replacement evidence is the frozen UT-17
fingerprint + authorization/security contract; C. Matrizes admin_access
consumer moved from the current-main consumer set to the canonical
`app.views.files` identity proof; D. UT-16
`test_green_4_ut17_firewall_three_routes_unchanged` state-aware 3→0 routes.
No other seam or retirement.

UT-16 SHA handling: published frozen
`D55063AC2C6063DD76034CBF7AA574A3F58B9C9D4164A3114D6B7454FD07B297` recorded as
historical evidence; post-UT17 authorized-seam SHA
`0C6C4429C9E41DC23A00ABB9BF1C0C12DA9752C7D6E0E2AFB37D4F1E6D2A1522`. The
published UT-16 SHA is never rewritten as though the file stayed byte-identical.

Frozen UT-17 RED: `tests/test_ut17_infra_routes.py` — 38 tests, final
38/38 PASS / 0 failed / 0 errors / 0 skipped; SHA-256
`04DB4E96256EB24C06085AF961500677554D5F5A8256524B7057724EFEDBCD41`; no later
mutation.

Review history (not sanitized): Independent Review R1 ACCEPT / 0 material
findings; R1 also classified implementation-provenance wording as
NON_MATERIAL_PROCESS_REPORTING_AMBIGUITY (durable evidence did not prove either
unauthorized implementation or a scope violation). Second Blind Review R2
original verdict REJECT — claim: health early-bound `get_db_connection`
prevented an app.db-only monkeypatch from intercepting. Supervisor
adjudication: REJECT OVERRULED — published HEAD main.py already early-bound
`get_db_connection` via `from app.db import get_db_connection`, and the UT-17
implementation authorization explicitly allowed the equivalent canonical
import in `app/__init__.py`; no baseline behavior/resolution-site regression
demonstrated. Classification: NON_MATERIAL_TESTABILITY_OBSERVATION /
REVIEWER_CONTRACT_OVERREACH. Final R2 disposition after adjudication:
ACCEPT / 0 MATERIAL FINDINGS. Reviewer routing fact: requested Claude Opus 5
was unavailable; platform-assigned Codex / GPT-5 family performed R2; no
GPT-5.6 Luna usage invented.

Full canonical suite (both final deterministic runs): Run 1 — 1534 collected /
1517 passed / 17 deselected / 0 skipped / 0 failed / 0 errors / 379.06s.
Run 2 (canonical recorded) — 1534 collected / 1517 passed / 17 deselected /
0 skipped / 0 failed / 0 errors / 348.84s / exit 0. Count reconciliation:
UT-16 baseline 1497/1480 +38 frozen RED tests −1 retired B7-P test = 1534/1517;
no unexplained collection delta.

Criteria 1-9 final gate: all PASS (C1 hooks_main 0; C2 create_app single
composition root; C3 zero app/services/utils→main and files.py without
backedge; C4 v1.3/v1.4 definition, historical v1.2 failure preserved as
historical truth; C5 RBAC unmapped 0; C6 routes 131/endpoints 130/actor
matrix 402, inventory unchanged; C7 canonical suite 0/0/exit 0; C8 main local
`@app.route` = 0; C9 one canonical owner per cohort, 0 residual blockers).

Final invariants: routes 131 / endpoints 130 / RBAC unmapped 0 / actor matrix
402 / message catalog 536 / hooks_main 0 / app/services/utils→main 0 /
`main.init_db` callers 76 / SCHEMA_VERSION 3 / migrations v1/v2/v3 only / main
local routes 0. Permanent prohibitions preserved: no migration v4, no
`app/db` package, no `app/repositories` layer.

Database unchanged: 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818`; no sidecars.
Artifacts `csrf_inventory_shadow_on.json`, `csrf_inventory_shadow_off.json`,
`route_inventory_baseline.json`: zero tracked delta, Git-canonical content
unchanged.

Final structural disposition: REFACTOR ESTRUTURAL COMPLETO CLOSED / ACCEPTED /
PUBLISHED (see section below). UT-17 TECHNICALLY ACCEPTED. Formal canonical
declaration occurs at the single landing commit with remote verification.

## REFACTOR ESTRUTURAL COMPLETO — CLOSED / ACCEPTED / PUBLISHED

Declared by this final UT-17 landing commit; landing SHA not invented. All
active Criteria 1-9 were technically qualified PASS before this governance
closeout (independent review R1 ACCEPT, R2 final ACCEPT after supervisor
override; canonical full suite 1534/1517/17, 0 failed, 0 errors, exit 0).
Chronology: technical qualification occurred before governance; governance
records the technically proven final state; canonical publication occurs only
when this governance + the UT-17 technical patch land in the single commit and
remote verification succeeds. There is NO UT-18; the roadmap technical
sequence is exhausted after UT-17. D-3 and the other deferrals remain
deferred/non-required under Protocol v1.4 and are NOT outstanding blockers.

## Process anomalies — Phase-5 review tooling hygiene

Two stray untracked review-tooling scripts from the prior independent-review
phase (`measure_invariants.py`, `verify_rbac_matrix.py`) were found and removed
before the canonical full suite. Classification: NON_MATERIAL PROCESS
DEVIATION / REVIEW_TOOLING_HYGIENE. They were not candidate files, did not
affect any qualified byte, were not present during the canonical suite, and do
not require suite repetition. No candidate or DB byte changed.

## Invariants (last measured)

- routes: 131
- distinct endpoints: 130
- RBAC unmapped: 0
- actor matrix: 402
- message catalog: 536
- hooks_main: 0
- after_request[None] exactly 2, both non-`main`: `flask_compress.after_request`;
  `app._apply_security_headers`
- architectural reverse dependencies (app/services/utils → main): 0
- literal main import edges: 0
- `main.init_db` compatibility callers: 76 (75→76 solely the frozen UT-14 RED
  test's `_prepare_behavior_env`; UT-15 introduces no caller; production
  caller delta 0)
- `app_db`-qualified `init_db` callers: 6 (5→6 solely `tests/conftest.py::
  _bootstrap_session_database`; production caller delta 0)
- `SCHEMA_VERSION`: 3 — migrations v1/v2/v3 only (migration v4 remains PROHIBITED)
- main local `@app.route` handlers: 0 (UT-17 final; Criterion 8 satisfied)

## Latest full-suite status

Final canonical suite (UT-17, two deterministic runs): Run 1 — 1534 collected /
1517 passed / 17 deselected / 0 failed / 0 errors / 0 skipped / 379.06s.
Run 2 (canonical recorded) — 1534 collected / 1517 passed / 17 deselected /
0 failed / 0 errors / 0 skipped / 348.84s / exit 0. Reconciliation: 1497
UT-16 baseline + 38 UT-17 RED − 1 retired B7-P = 1534/1517.
Frozen UT-17 RED `tests/test_ut17_infra_routes.py`: 38/38 passed; frozen
SHA-256 `04DB4E96256EB24C06085AF961500677554D5F5A8256524B7057724EFEDBCD41`.
Retired in UT-17: exactly 1 (`test_b7p_uploaded_file_unchanged_from_entry_baseline`).
Frozen UT-16 RED `tests/test_ut16_residual_main_ownership.py`: published SHA
`D55063AC2C6063DD76034CBF7AA574A3F58B9C9D4164A3114D6B7454FD07B297`; post-UT17
authorized-seam SHA `0C6C4429C9E41DC23A00ABB9BF1C0C12DA9752C7D6E0E2AFB37D4F1E6D2A1522`
(15/15 passed).
REFACTOR ESTRUTURAL COMPLETO: CLOSED / ACCEPTED / PUBLISHED (canonical at the
future single landing commit; landing SHA not invented).
Frozen UT-15 RED `tests/test_ut15_demo_blueprint.py`: 26/26 passed;
frozen SHA-256 `7311F1A49E13096B643F66BBA7F9C901376832C9A4651B623161D51BDDC4D520`
(retired: `F7E8BA0B3BBB69B7FB17ED4FC42198A5C1EBA125D24E7E38B6B75D5FC8531274` —
MATERIAL_TEST_CONTRACT_DEFECT in artifact-custody wording/semantics found by
independent review; corrected custody semantics: Git-canonical
repository-content identity + no tracked artifact delta; CRLF/LF checkout
materialization alone is not artifact mutation).
Frozen UT-14 RED `tests/test_ut14_meus_dados_blueprint.py`: 27/27 passed;
frozen SHA-256 `B3E3DFEE8BDC60C8CF55B89EA2CCDAC6F52C9B03B5A55FAC0FBDD23653DEBB5E`.
Frozen UT-13 RED `tests/test_ut13_dashboard_blueprint.py`: 30/30 passed;
frozen SHA-256 `63a811794f136e087e47b624b1ec1a53f695138464f7a960b6291f9bded41ef2`.
Frozen C4 gate `tests/test_plateau_c4_request_hook_write_isolation.py`: 36/36 passed;
frozen SHA-256 `277b0c3a872c540e5e58372d6697777842bd15c825ff20e4e77402b781519dde`.
Detail: `docs/refactor/EXECUTION_PROTOCOL.md` §11 and
`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` (UT-9, UT-10, UT-11, UT-12, UT-13, UT-14, UT-15, UT-16 and plateau blocks).

## Database baseline

Canonical `database.db`: 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818` (`user_version` 3; no
persistent `-wal` / `-shm` / `-journal` sidecars).

## Open / deferred — NOT closed by the plateau

The plateau is architectural completeness against the seven criteria, not zero architectural
debt. Explicitly still open and NOT to be reopened by the landing commit:

- FUTURE_HARDENING: duplicate 500-path logging; unsupported/hypothetical WSGI/`FLASK_APP`
  startup without `init_db`.
- OUT_OF_SCOPE: request-time schema/application writes that remain inside route bodies
  (outside the hook criterion); `presets_api.py` root-module DB + reverse-`main` debt
  (outside current C3 scope).
- D-1 / D-2 / D-3 deferrals of `EXECUTION_PROTOCOL.md` §2 remain unauthorized.

## Authority

Operational authority: `docs/refactor/EXECUTION_PROTOCOL.md` (v1.4 — 2026-08-10).
`AGENT_HANDOFF.md` is historical/frozen — no new writes, not read by the cycle.
