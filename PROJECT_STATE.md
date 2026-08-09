# PROJECT_STATE — live state

Branch: `refactor/architecture-safety-net`
HEAD: current Git HEAD — authoritative value: `git rev-parse HEAD`
UT-9 entry parent: `7909b2d59b2de987d84dc859a15bede215a3261b`
Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`
Rewritten once per UT; history in `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`.

Last completed UT: UT-9 (Acesso) — technically qualified / accepted for publication.
UT-9 outcome:
- canonical owner = `app/views/admin/acesso.py`
- relocated: 6 routes / 3 helpers / 0 constants
- LegacyRouteSpec: 6 specs / 6 endpoint-method pairs
- RBAC: 1 view / 5 full
- `main.py` retains identity compatibility re-exports: 9/9
- `main.py` local ownership of moved symbols: 0
- `acesso` → `main`: 0
- `main.py` `@app.route` count: 18 (unchanged)
- factory registration through existing legacy blueprint mechanism
- `app/auth.py` and `app/admin_access.py` unchanged
- password / transaction / delete / resequence semantics unchanged

Transparency (UT-9 qualification path):
- initial RED SHA superseded by a supervisor-approved green_11 seam correction;
- first canonical full suite exposed one stale exact init_db caller-manifest contract;
- narrow repair added only the legitimate test-side isolated_env caller;
- narrow review PASS / 0 material;
- final canonical retry PASS.

Corrected frozen UT-9 RED SHA: `e88d9939afd570c6cbcfa7b097946012ee1cf988c379a807c5f76a97fc6fb5f5`

Reviews: DeepSeek V4 Pro — PASS / 0 material findings (primary adversarial review; narrow repair review).
Next UT: UT-10 — NOT STARTED

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
- main.init_db compatibility callers: 74 (73→74 solely the frozen UT-9 RED test's
  isolated_env caller; production caller delta 0)

## Latest full-suite status

UT-9 qualification: 1282 collected / 1265 passed / 17 deselected / 0 failed / 0 errors.
Detail: `docs/refactor/EXECUTION_PROTOCOL.md` §11 (UT-9 row) and
`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` (UT-9 block).

## Plateau

All seven current plateau criteria measured PASS. Formal plateau validation becomes eligible
AFTER UT-9 publication; not formally declared in this task.

## Database baseline

Canonical `database.db`: 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818` (`user_version` 3; no sidecars).

## Authority

Operational authority: `docs/refactor/EXECUTION_PROTOCOL.md`.
`AGENT_HANDOFF.md` is historical/frozen — no new writes, not read by the cycle.
