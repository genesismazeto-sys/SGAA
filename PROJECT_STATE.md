# PROJECT_STATE — live state

Branch: `refactor/architecture-safety-net`
HEAD: current Git HEAD — authoritative value: `git rev-parse HEAD`
UT-8 entry parent: `7c5b319a39639468943ef6c5521a36cc44545615`
Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`
Rewritten once per UT; history in `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`.

Last completed UT: UT-8 (Banco de Dados) — qualified.
UT-8 outcome:
- canonical owner = `app/views/admin/banco_dados.py`
- relocated: 20 routes / 24 helpers / 2 constants / 46 total symbols
- `main.py` retains identity compatibility re-exports: 46/46
- LegacyRouteSpec: 20 specs / 21 endpoint-method pairs
- `banco_dados` → `main`: 0
- factory registration through existing legacy blueprint mechanism
- lower-layer DB/backup/service architecture unchanged
- no schema/migration/repository change

Reviews: DeepSeek V4 Pro — PASS / 0 material findings (primary; narrow repair review).
Next UT: UT-9 — NOT STARTED

## Invariants (last measured)

- routes: 131
- endpoints: 130
- RBAC unmapped: 0
- actor matrix: 402
- message catalog: 536
- hooks_main: 0
- after_request: 2 non-main handlers (flask_compress; app._apply_security_headers)
- architectural reverse dependencies (app/services/utils → main): 0
- literal main import edges: 0
- main.init_db compatibility callers: 73 (72→73 solely the frozen RED test's
  isolated_env caller; production caller change was pure ownership relocation)

## Latest full-suite status

UT-8 qualification: 1255 collected / 1238 passed / 17 deselected / 0 failed / 0 errors.
Detail: `docs/refactor/EXECUTION_PROTOCOL.md` §11 (UT-8 row) and
`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` (UT-8 block).

## Database baseline

Canonical `database.db`: 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818` (`user_version` 3; no sidecars).

## Authority

Operational authority: `docs/refactor/EXECUTION_PROTOCOL.md`.
`AGENT_HANDOFF.md` is historical/frozen — no new writes, not read by the cycle.
