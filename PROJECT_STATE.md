# PROJECT_STATE — live state

Branch: `refactor/architecture-safety-net`
HEAD: current Git HEAD — authoritative value: `git rev-parse HEAD`
UT-5 entry parent: `9b6cce5019319394264ee76bc3c67b20dc7e83b9`
Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`
Rewritten once per UT; history in `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`.

Last completed UT: UT-5 (backup I/O removed from request cycle) — qualified; both independent
reviews PASS (DeepSeek V4 Pro; Claude Opus 5). 0 material findings.
Next UT: UT-6 (close app → main cycle)

## Invariants (last measured)

- routes: 131
- endpoints: 130
- RBAC unmapped: 0
- actor matrix: 402
- message catalog: 536
- hooks_main: 0
- after_request: 2 non-main handlers (flask_compress; app._apply_security_headers)

## Latest full-suite status

UT-5 qualification: 1142 passed / 17 deselected / 0 failed / 0 errors.
Detail: `docs/refactor/EXECUTION_PROTOCOL.md` §11 (UT-5 row) and
`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` (UT-5 block).

## Database baseline

Canonical `database.db`: 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818`
(`user_version` 3; no sidecars).

## Authority

Operational authority: `docs/refactor/EXECUTION_PROTOCOL.md`.
`AGENT_HANDOFF.md` is historical/frozen — no new writes, not read by the cycle.
