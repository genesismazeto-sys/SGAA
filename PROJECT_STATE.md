# PROJECT_STATE — live state

Rewritten (not appended) once per unit of work. Historical narrative predating
UT-2 is not preserved here — see `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`.

Branch: `refactor/architecture-safety-net`
HEAD: current Git HEAD — authoritative value: `git rev-parse HEAD`
UT-2 entry parent: `ab1614dd525047e862da00baef975e81eca01c6b`
Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`

Last completed UT: UT-2 (unify composition root + Adoption part 2) — qualified;
both independent reviews PASS (DeepSeek V4 Pro; Claude Opus 5)
Next UT: UT-3 (migrate remaining app hooks to composition root)

## Invariants (last measured)

- routes: 131
- endpoints: 130
- RBAC unmapped: 0
- actor matrix: 402
- message catalog: 536
- hooks_main: 7

## Latest full-suite status

UT-2 qualification full suite: 1110 passed / 17 deselected / 0 failed /
0 errors / exit 0.
Detail: `docs/refactor/EXECUTION_PROTOCOL.md` §11 (UT-2 row) and
`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` (UT-2 block).

## Authority

Operational authority: `docs/refactor/EXECUTION_PROTOCOL.md` v1.1 FINAL.
`AGENT_HANDOFF.md` is historical/frozen as of the v1.1 governance adoption —
no new writes, not read by the active governance cycle.
