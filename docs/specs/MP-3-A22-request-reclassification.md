# SPEC MP-3 A22 — Correcting the activity of an editable request (schema v17)

Status: FROZEN 2026-10-19 (slice 1 implemented; PROD gate G1 pending).
Charter (owner, 2026-10-19, production defect on a real request): "A student can actually correct an
incorrectly selected activity while the request is editable, without corrupting versioned academic
records or requiring a duplicate request." Owner's decision on the schema (same day): narrow the
database trigger (option 1) -- Pendente may change its activity, Devolvida may inside its
rectification deadline, Deferida / Indeferida / Encerrada stay protected, activity and snapshot change
together in one transaction; implement v17 and its tests, do not run the migration in production; the
production migration follows the governed procedure before the compatible code is published.
Risk tier: R3 (production schema change; an integrity invariant of the request record). Continues the
MP-3 post-PONR line (C13 recorded; changes reach production only through GF1 forward fixes).

## 1. Outcome

- A student corrects Tipo / Grupo / Atividade of a Pendente request, or of a Devolvida one inside its
  deadline, on the existing edit form; the request keeps its id, documents and history.
- An administrator corrects a Pendente request from the Requisições modal under the same rules.
- The corrected request carries a fresh authoritative snapshot of the new activity; the previous
  classification is preserved inside that snapshot. `atividade_versao` is never written.
- A decided or expired request, an activity outside the student's effective Matrix or inactive, and a
  form filled before someone else's correction are refused; nothing is written.
- A correctable refusal keeps the student on the edit form with what was typed and the reason.

## 2. Current facts

- The database froze the pair for every status: SQLite `trg_requisicoes_snapshot_immutable`
  (v16 head, `app/prod1_schema.py`), PostgreSQL `fn_requisicoes_snapshot_immutable`
  (`app/pg_schema.py`), live on PROD. The D8.2B guards in `app/views/aluno.py` and
  `app/views/admin/requisicoes.py` were the friendly front of that rule; no application change
  could reclassify in place.
- The student edit offered the activity selects, but listed only the stored activity's type; every
  POST outcome redirected to the bare detail page (`aluno_requisicao_detalhe.html`), including
  correctable errors and success.
- The snapshot service `app.versioning.snapshots.prepare_versioned_requisicao_snapshot` already
  resolves the version against the student's effective Matrix (`resolver_versao_por_aluno`, the FC13
  allowlisted caller) and requires `status = 'ativa'`.
- PostgreSQL had no in-place upgrade path: v16 was provisioned fresh at the cutover;
  `validate_pg_schema` pins version and contract digest and checks function names, not bodies.
- The hosted entrypoint (`main:app`) never runs `init_db`: a running deployment does not validate the
  schema version at start. `tools/pg_backup.py` (governed generations) and the Path-B reader do,
  exactly. The daily governed backup runs from a pinned worktree of an earlier commit.
- `app/backup/pg_snapshot.py` hard-coded `user_version == 16` for the hosted snapshot (fixed here).
- The processing page (`admin_processar_requisicao`) rendered an empty "Atividade:" for every
  request (pre-existing; fixed here because the administrator decides there).
- The Requisições modal's group filter keyed only "N - Descrição" groups, so an unnumbered group
  (Extensão's "NA") could not be chosen; it now uses the student form's group key.

## 3. Target design

- `app/prod1_request_reclassification_ddl.py` (SQLite authority) + `app/prod1_request_reclassification_v17.py`
  (v16 -> v17 migration, one `BEGIN IMMEDIATE`, rows digested before/after). The trigger refuses:
  any pair change unless OLD and NEW status are Pendente/Devolvida (v16 message kept); a change of
  only one column; a new snapshot that is not a JSON object whose integer `atividade_versao_id` is
  the new activity. NULL-safe (`IS` / `IS NOT`), JSON inspected only after `json_valid`.
- `app/pg_schema.py`: same rule in `fn_requisicoes_snapshot_immutable` (nested IFs, SG001),
  version 17, seed row 17, `upgrade_pg_schema` / CLI `python -m app.pg_schema upgrade` (exact frozen
  v16 only: meta version + digest, migration rows 1..16, the v16 function body; locks the meta row;
  idempotent on v17), and `validate_pg_schema` now compares the body of every upgraded function
  (`PG_UPGRADED_FUNCTIONS`).
- `app/request_reclassification.py` (domain owner): `prepare_reclassification` (stale-form check
  against the classification the form was filled with, reclassifiable status, the snapshot service,
  declared type vs. activity, history entry) and `apply_reclassification` (compare-and-set on id,
  status, old activity and old snapshot). `log_reclassified` after commit (`event=request_reclassified`,
  ids only).
- Views stay thin: the student POST (`_save_student_request_edit`) and the admin edit call the owner
  inside the same `write_transaction` as the field edit / resubmission and the document attachment.
  The admin field UPDATE gained `AND status = 'Pendente'`. The admin API adds `reclassification`
  (offer for a Pendente request only); its historical `activities` contract is unchanged.
- Forms carry `atividade_versao_id_registrada` (the stored classification they were filled with).

## 4. Decisions

- D1 — Narrow the trigger (owner). Rejected: a duplicate request (loses id and documents); hiding
  the selects (does not fix the defect).
- D2 — Traceability in the authority row: `reclassification_history` inside the new snapshot,
  carried forward. Rejected: a new audit table (a second schema change for one fact).
- D3 — The deadline of a Devolvida request stays an application rule (`app.requisition_policy`);
  the database enforces status, pairing and identity only.
- D4 — Ordinary edits keep the snapshot byte for byte; only a change of activity writes a new one.
- D5 — A POST without the registered classification cannot change the activity (fail closed).

Open decisions: none.

## 5. Phase invariants

- The activity and its snapshot never diverge (database, both engines).
- Deferida, Deferida Parcialmente, Indeferida and Encerrada never change classification.
- No write to `atividade_versao`, `atividade_base` or Matrix tables.
- Route URLs, endpoint names, RBAC and CSRF unchanged (route and CSRF inventories untouched).

## 6. Scope

- Allowed: the files of §3, the two request templates, the schema test helpers and pins that the
  version change makes false, `app/backup/pg_snapshot.py` (version constant), the processing view's
  activity name, governance docs.
- Protected: Path-B table policies, Layer-2 table-data policy, the cutover ledger and its tools.
- Out of scope: the bare detail page's layout (no longer reached by the edit flow); restoring
  pre-v17 snapshots through "Recuperar banco de dados" (§9).

## 7. Data & schema

Schema v17 on SQLite and PostgreSQL: one trigger (function body) replaced, migration row 17, no
table, column, index, constraint or data change, no backfill. Path-B: unchanged policies; its reader
requires the source `user_version` equal to the PostgreSQL version, so a v16 SQLite source is
migrated by the bootstrap first. Layer-2: same table-data policy; a v16 generation restores only
with the v16 tooling (forward-only, as every schema step). Real data: untouched by this slice.

## 8. Security & RBAC

No new route. Student: the existing ownership and edit-window checks run first; the owner refuses
outside the student's effective Matrix. Admin: the existing `admin_editar_requisicao` RBAC and
`edit_target_id` binding. Fail closed on a missing or stale registered classification.

## 9. Compatibility / rollout

- Running v16 code tolerates a v17 database (it never changes the pair). v17 code against a v16
  database refuses a correction (generic failure, nothing written) until the upgrade.
- Tools validate exactly: `ops_backup` / `pg_backup` of the v16 worktree refuse a v17 database and
  vice versa. Pre-v17 hosted snapshots are refused by the v17 restore reader
  (`SOURCE_SCHEMA_UNSUPPORTED`); the post-upgrade generations are the new restore points.
- Rollback: forward-only. A code rollback needs no schema rollback; a schema rollback is the
  v16 function body + row 17 removal + meta (v16 digest), performed only under a new gate.

## 10. External boundaries / environment permissions

Slice 1: no provider, no DEV or PROD action; local PostgreSQL 15/17 run-owned databases only.
PROD gate G1 (user, after review; GF1 forward fix):
1. the owner's message naming this commit and the upgrade (GF1 grant);
2. pre-upgrade governed generation with objects from the current pinned worktree;
3. a worktree of this commit; **(user terminal)** `python -m app.pg_schema upgrade` against the
   verified PROD source, then `validate` and `python -m app.hosting_cli check --database`;
4. in the same session, a governed generation with objects from the new worktree (cadence and new
   restore point), and the daily governed-backup script repinned to that worktree;
5. GF1 deploy, `authorize-code`, promote, smoke; the owner corrects request #42 through the UI.

## 11. Evidence plan

T1 `tests/test_request_reclassification.py` (routes, owner, SQLite trigger),
`tests/test_schema_v17_request_reclassification.py` (migration, parity), E-PG1/E-PG2
`tests/test_request_reclassification_real_pg.py` (owner write, trigger, two-writer races, upgrade and
its serialization) on PostgreSQL 17. T3: every module pinned to the schema head, the request edit,
rectification, comprovante and admin-request suites, the catalogue governance suites. T4: route /
CSRF / RBAC inventories, FC13, transaction and connection ownership guards. E-UI: headless browser
on the real edit form. Full suite: not triggered (TEP §5.1: no shared primitive, bootstrap or test
machinery change; the schema step's blast radius is the pinned set). Review: R2 fresh-context review
before landing; the R3 cross-family review is the owner's, before G1.

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | v17 schema, owner, student and admin flows, tests, docs | §3, §6 | §11 green | implemented |
| G1 | PROD upgrade and deploy | §10 | ledger entries, smoke, owner's correction of #42 | gated |

## 13. Acceptance criteria

- AC1 — Pendente request moves A -> B (same Matrix) and AAC -> AEU: same id, documents preserved,
  valid new snapshot, history entry → `test_a_pending_request_moves_…`, `test_a_correction_may_cross_axes_…`.
- AC2 — Devolvida inside the deadline is corrected and resubmitted with the reason kept → `test_a_returned_request_…`.
- AC3 — Outside the Matrix, inactive, contradicting type, decided, expired, stale form, concurrent
  decision: refused, nothing written → the refusal tests (SQLite and E-PG2).
- AC4 — Edit without activity change keeps the snapshot byte for byte → `test_an_edit_that_keeps_…`.
- AC5 — Administrator edit follows the same rules → `test_the_admin_…`.
- AC6 — Database refuses decided, partial and mismatched pairs on both engines; v16 -> v17 is exact.
- AC7 — `docs/ENGINEERING_STANDARDS.md` self-audit (§13) passes.

## 14. Phase-specific hard stops

- Any PROD action before G1. Any change to request #42 or other real records by the executor.

## 15. Deferred / known non-blockers

- The bare detail page (`aluno_requisicao_detalhe.html`) keeps its legacy layout; the edit flow no
  longer lands there.

## 16. Amendments

- A1 2026-10-19 — R2 review (fresh context, PASS, no MATERIAL) asked to state consequences the
  slice already carried and to close one race · additions: (a) the student edit's other outcomes
  also move: success returns to Minhas requisições, a closed request goes to `?view=1`, file parts
  re-render the form (415); (b) files touched as consequences of v17: `app/prod1_ephemeral_state_v16.py`
  (the v15 -> v16 step validates the frozen v16 shape), `app/db_maintenance.py` (row 17),
  `app/db.py` (operator hint names `upgrade`), docstrings of `app/backup/pg_restore.py` and
  `app/student_request_edit.py`; the modal's group key also serves the admin create flow;
  (c) a decision is recorded only on the classification the administrator was shown: the
  processing page and the modal send `atividade_versao_id_registrada`, and the decision UPDATE is a
  compare-and-set on the activity and snapshot the route read; (d) PostgreSQL also requires the
  snapshot's version id to print as digits. Remaining engine difference, fail-safe: SQLite reads
  the first of duplicate JSON keys and PostgreSQL the last, and PostgreSQL accepts `2e0`; the
  application never writes either, and the processing reader refuses such a snapshot · not material.

## 17. Closure

Pending G1.
