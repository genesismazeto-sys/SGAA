# PROJECT_STATE — live state

Branch: `refactor/architecture-safety-net`
HEAD: current Git HEAD — authoritative value: `git rev-parse HEAD`
Plateau landing parent: `230de41b3439a60951049e9021d6b0063f3bc2db`
UT-9 entry parent: `7909b2d59b2de987d84dc859a15bede215a3261b`
UT-10 entry parent: `e8f64a8244196b1c7acd634c9f78fbde29d70ef9`
UT-11 entry parent: `a0092149c2c596f90932b8f83991a33e1f98c32c`
Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`
Rewritten once per UT; history in `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`.

Last completed UT: UT-11 (Alertas) — CLOSED / ACCEPTED / PUBLISHED (published by
this UT-11 landing commit, subject `Extract admin alerts routes`, entry parent
`a0092149`). Last completed work: UT-11 Alertas extraction — 4 routes / 4
endpoint-method pairs / 3 helper functions / 1 cohort-local constant (8 moved
symbols) moved to `app/views/admin/alertas.py`. Prior landing: UT-10 Arquivos
extraction (parent `e8f64a82`); C4 request-hook write isolation + STRUCTURAL
PLATEAU publication (Phase-H landing commit, parent `230de41b`).
Next UT: UT-12 — NOT STARTED.

## STRUCTURAL PLATEAU — VALIDATED / PUBLISHED

Published by this Phase-H landing commit (subject `Validate structural plateau request-hook
isolation`, parent `230de41b`). Governing criteria text: `docs/refactor/EXECUTION_PROTOCOL.md`
§3, **Protocol v1.3 — 2026-08-09**.

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
ACCEPTED / PUBLISHED. Protocol remains: v1.3.

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
ACCEPTED / PUBLISHED. Protocol remains: v1.3.

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
- `main.init_db` compatibility callers: 75 (74→75 solely the frozen C4 RED test's
  `_bootstrapped_env`; production caller delta 0)
- `app_db`-qualified `init_db` callers: 6 (5→6 solely `tests/conftest.py::
  _bootstrap_session_database`; production caller delta 0)
- `SCHEMA_VERSION`: 3 — migrations v1/v2/v3 only (migration v4 remains PROHIBITED)

## Latest full-suite status

Canonical suite: 1373 collected / 1356 passed / 17 deselected / 0 failed / 0 errors / 368.73s.
Frozen C4 gate `tests/test_plateau_c4_request_hook_write_isolation.py`: 36/36 passed;
frozen SHA-256 `277b0c3a872c540e5e58372d6697777842bd15c825ff20e4e77402b781519dde`.
Detail: `docs/refactor/EXECUTION_PROTOCOL.md` §11 and
`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` (UT-9, UT-10, UT-11 and plateau blocks).

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

Operational authority: `docs/refactor/EXECUTION_PROTOCOL.md` (v1.3 — 2026-08-09).
`AGENT_HANDOFF.md` is historical/frozen — no new writes, not read by the cycle.
