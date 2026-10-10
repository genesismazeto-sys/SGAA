# SGAA Documentation Index

Map of the documentation and its authority, since MP-0 (2026-10-09). The
pre-MP-0 index is preserved verbatim in
`docs/history/DOCUMENTATION_INDEX_PRE_MP0_2026-10-09.md`, including its
per-contract descriptions of the historical phase contracts.

## Authority

Git is the source of truth. Chat memory, handoff notes and unsaved
documentation carry no authority; every authoritative fact lives in a
committed file.

| Owner | Governs |
|---|---|
| `docs/OPERATING_MODEL.md` | process: roles, macro-phase lifecycle, charter, SPEC lifecycle, autonomy rule, hard stops, review tiers, landing, reporting, documentation discipline |
| active frozen SPEC in `docs/specs/` | the execution contract of the current macro-phase |
| `docs/ENGINEERING_STANDARDS.md` | permanent structural and code-health rules; permanent guards |
| `docs/TEST_EXECUTION_POLICY.md` (TEP) | test selection, full-suite triggers, delta qualification, reruns, evidence lanes |
| `PROJECT_STATE.md` | present state, readiness, environment facts, roadmap |
| this index | the map of documents |

A SPEC operates inside `OPERATING_MODEL.md`, `ENGINEERING_STANDARDS.md` and the
TEP: it may demand more, never less. Those three owners change only through an
explicitly authorized governance change.

## Reading order

1. `PROJECT_STATE.md`
2. `docs/OPERATING_MODEL.md`
3. `docs/ENGINEERING_STANDARDS.md`
4. `docs/TEST_EXECUTION_POLICY.md`
5. the active SPEC, if any (`docs/specs/README.md`)
6. the subsystem reference documents below that the work touches

`CLAUDE.md` holds session pointers for the executor and no rules of its own.

## Current reference documents (accurate for their subsystem)

- `docs/HOSTED_RUNTIME.md` — hosted-runtime contract: mode, startup blockers,
  variables, filesystem rules, readiness check, platform exposure, security
  posture and deployment on Vercel Hobby (owner: `app/hosting.py`).
- `docs/PG_BACKUP_RESTORE_RUNBOOK.md` — PostgreSQL Layer-2 backup/restore
  operator runbook, the Supabase restore profile and scheduled generations.
- `docs/PRODUCTION_CUTOVER_RUNBOOK.md` — the MP-3 cutover procedure: states,
  gates, rollback and the point of no return (authority: its SPEC).
- `docs/PRE_GO_LIVE_PROD1_RESET_CUTOVER_RECORD.md` — PROD-1 database reset
  record; Phase C (production web runtime) deferral.
- `docs/refactor/PYTEST_CUSTODY_EXTERNAL_WRITER_CONTRACT.md` — full-suite
  custody contract behind `tests/conftest.py` (TEP §14).
- `docs/design-system/README.md` — Design System contracts and E-UI gates;
  `form-contract.md` (current form system); `form-redesign-proposal.md`
  (proposal awaiting product approval).
- `docs/backlog/UI_ACCEPTANCE_BACKLOG.md` — the single canonical record of
  user-reported UI items; add rows there, never in a second backlog.
  `UI_C13_SCHEDULER_DECISION_MEMO.md` and `UI_B11_RAW_COLOUR_AUDIT.md` are its
  supporting records.
- `docs/mail/AUTH_EMAIL_EXTENSION_POINT.md` — outbound-mail reuse contract.

## Historical records (not authority)

- `docs/history/` — verbatim archives of `PROJECT_STATE.md` and of this index
  before MP-0.
- `docs/refactor/EXECUTION_PROTOCOL.md` — process of the UT-1…UT-17 structural
  refactor (superseded as process authority by `OPERATING_MODEL.md`).
- `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` — frozen ledger of the
  refactor phases.
- `docs/refactor/PHASE*.md`, `docs/refactor/REF_*.md`,
  `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` — closed phase
  contracts and custody records.
- `docs/mapeamento/` — architecture map as of 2026-06, partly superseded (for
  example the deployment notes in `06_deploy_e_infraestrutura.md`).
- `AGENT_HANDOFF.md` — frozen since 2026-08-07.
- `README.md`, `TECH_NOTES.md`, `docs/release_1_0_checks.md`,
  `docs/auditoria_static_2026-05-20.*`, `docs/d6_4_snapshot_write_ops.md`,
  `docs/d8_*.md` — earlier overviews and operation records.

## Rules

- One fact, one home (`OPERATING_MODEL.md` §11). A new document needs an owner
  role in this index; otherwise the fact belongs in an existing owner.
- Historical records are not edited to match the present; at most they carry a
  short pointer to the current authority.
