# PROJECT_STATE — live state

Branch: `refactor/architecture-safety-net`
HEAD: current Git HEAD — authoritative value: `git rev-parse HEAD`
UT-3 entry parent: `7468a0f3502a7f51537fc9e537d401b4e1dc6f1c`
Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`
Rewritten once per UT; history in `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`.

Last completed UT: UT-3 (migrate remaining app hooks to `app/web/*`) — qualified;
both independent reviews PASS (DeepSeek V4 Pro; Claude Opus 5). R1 fixed UT3-01
(direct-entrypoint logger identity), pinned by a dedicated regression test.
Next UT: UT-4 (path containment)

## Invariants (last measured)

- routes: 131
- endpoints: 130
- RBAC unmapped: 0
- actor matrix: 402
- message catalog: 536
- hooks_main: 1 (`_legacy_post_response_backup_sync`, transitional until UT-5)

## Latest full-suite status

UT-3 qualification: 1126 passed / 17 deselected / 0 failed / 0 errors / exit 0.
Detail: `docs/refactor/EXECUTION_PROTOCOL.md` §11 (UT-3 row) and
`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` (UT-3 block).

## Database baseline

Canonical `database.db`: 544768 bytes / SHA-256
`bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818`
(`user_version` 3; `schema_migrations` v1/v2/v3; no `-wal`/`-shm`/`-journal`).
Former baseline `a3a55e63…70fe9` RETIRED (pre-v2/v3); the human-authorized
migration reconciliation found no business-data mutation.

## Authority

Operational authority: `docs/refactor/EXECUTION_PROTOCOL.md` v1.1 FINAL.
`AGENT_HANDOFF.md` is historical/frozen — no new writes, not read by the cycle.
