# PROJECT_STATE — live state

Active branch: `refactor/design-system-foundation`.
Current HEAD: authoritative value is `git rev-parse HEAD`.
Protected `main`: `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1` — unchanged; no main action.

PROD-1 technical acceptance is final. Phase A technical landing completed at
`2026-08-21T11:13:22Z` with commit
`c9452b5bffa2c2620305ee1b296ff81deb22b65f`; the live remote branch was
independently verified at that SHA before the Phase B reset.

Phase B pre-go-live database reset and active validation completed at
`2026-08-21T11:17:57Z`. Active database contract: epoch `prod-1`, version `1`,
marker `first_production_baseline`; 409600 bytes; SHA-256
`cbd4197615d8929b7a19b5e52f016e06ecbc7fd1ad9297521b8a4fee25b37244`;
28 tables, 40 explicit indexes, 7 triggers, clean foreign-key and integrity
checks, no legacy objects, and no SQLite sidecars.

Initial content is defaults only: one `Geral` course, five access defaults, six
application settings, and six backup settings. Users/admins, requests/history,
Normas, activity catalogue, Matrices, Turmas, and students are empty. No admin
was created. Focused disposable regression: 18 passed, 0 failed, 0 errors.

Old database custody: 544768 bytes, SHA-256
`338c833bc565c97cb55d5e08a3df9dbbe307a99820bb5a56f0cbed62d699633d`,
archived at `D:\SGAA_CUSTODY\pre-go-live-prod1\20260821T111131Z\database.db`.
Old code rollback artifact: `old-code-779dbb24.zip`, SHA-256
`ee1e0542923964fa3584bcfffd52e9cd2d2cc617a1b30cc80ab67a8b9d81f169`.
Full evidence is in the same external custody directory and in
`docs/PRE_GO_LIVE_PROD1_RESET_CUTOVER_RECORD.md`.

`PRODUCTION_WEB_RUNTIME_ACTIVATION = DEFERRED`. Phase C still requires the final
HTTPS `APP_PUBLIC_BASE_URL`, externally provisioned `APP_SECRET_KEY` and
`TOKEN_ENCRYPTION_KEY`, binding/proxy decisions, production `create_app`
preflight, web startup/smoke, and manual admin creation. No production web
runtime was started in Phase A/B.

## Historical UT live-summary record

The block below preserves the prior UT-17 live summary as phase-time history;
it is not the current project summary.

Structural-refactor branch (history, no longer the active line):
`refactor/architecture-safety-net`
Plateau landing parent: `230de41b3439a60951049e9021d6b0063f3bc2db`
UT-9 entry parent: `7909b2d59b2de987d84dc859a15bede215a3261b`
UT-10 entry parent: `e8f64a8244196b1c7acd634c9f78fbde29d70ef9`
UT-11 entry parent: `a0092149c2c596f90932b8f83991a33e1f98c32c`
UT-12 entry parent: `4820e4d3a46a1a3564c730d384b86aa989d752c9`
UT-13 entry parent: `2e0afa34ed1b927014ac35875668bbdc132743ad`
UT-14 entry parent: `ef7bc0302cc86b4fa37f301be8157363922e51e7`
UT-15 entry parent: `37316d6dc2f3f55c050152e6b4ae835074ccdac6`
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
Next UT: NONE — FINAL ROADMAP COMPLETE. Work continuing after this point runs on
the Design System track below, which is NOT a UT and does not extend the UT
roadmap.

## FC-08 — TURMA EXPLICIT MATRIX AUTHORITY — CLOSED / ACCEPTED

FC08_F1_F2_FINAL_REREVIEW_ACCEPT. `turmas.matriz_id` is the sole persisted
academic Matrix authority for a cohort. Resolution requires the exact persisted
Matrix to belong to the Turma's Curso; no preferred/newest/active fallback
remains in academic authority. An explicit M1 remains M1 after M2 changes
recency or status. NULL, invalid and foreign Matrix pointers fail closed for
new academic scope.

Turma creation and normal full edit require an explicit valid `matriz_id`;
blank, missing and foreign choices reject atomically. GET and startup do not
write or backfill. Student catalogue and new student/admin request scope use
the exact Turma Matrix; canonical `matrix_scope` returns no authority and an
empty allowed scope when it cannot resolve one.

Historical persisted requests remain processable only when the aluno exists,
the Turma exists and that existing Turma has `matriz_id IS NULL`. This does
not reconstruct a Matrix. Missing/dangling aluno-Turma relationships receive
no exception, and explicit-Matrix historical requests still enforce exact
Matrix membership. No request, Turma, snapshot or version rebinding occurs.

Student and admin dashboards do not fabricate 160/80 targets without exact
Matrix authority. Factual approved hours/counts may remain visible, while
target, denominator and progress semantics are unavailable/non-applicable;
configured Matrix targets remain authoritative. The versioning resolver
delegates to canonical `matrix_scope`. FC-08 is not full versioning cutover:
request snapshot authority, historical-rule authority and legacy academic-rule
removal remain future functional work.

Follow-up Matrix-freeze debt remains open: selected activity-version links;
Matrix totals/status/validity/Curso identity fields; Activity-Version rule
fields; and Matrix deletion/dangling Turma protection. These are not closed by
FC-08.

Final canonical: 1600 passed / 133 skipped / 17 deselected / 0 failed / 0
errors. Invariants: routes 131; endpoints 130; RBAC unmapped 0; actor matrix
402; message catalogue 539; Design System 198; route inventory unchanged;
main `@app.route` 0; main-owned hooks 0; prohibited import main 0. No route,
endpoint, schema, migration, RBAC, message catalogue or CSRF snapshot change.

## FC-09 — ASSIGNED MATRIX ACADEMIC GRAPH FREEZE — CLOSED / ACCEPTED

FC09_W3_FINAL_REREVIEW_ACCEPT. FC-08 established exact persisted Turma Matrix
authority; FC-09 now guarantees that once a Matrix is referenced by at least
one Turma, its academic graph cannot be changed in place through ordinary
application writes.

- **Core authority:** freeze is usage-based — `EXISTS` Turma referencing
  Matrix; no separate frozen flag/column. When zero Turmas reference the
  Matrix again, existing ordinary unassigned management semantics resume,
  subject to existing rules.
- **Matrix row freeze:** for an assigned Matrix, protected
  academic/identity-bearing fields are `curso_id`, `status`,
  `data_inicio_vigencia`, `data_fim_vigencia`, `horas_aac_obrigatorias` and
  `horas_extensao_obrigatorias`; descriptive fields `nome`, `versao` and
  `descricao` remain editable under the accepted contract. Illegal protected
  edits reject atomically.
- **Norma:** NMB remains authoritative — assigned Matrix Norma binding set
  remains frozen. FC-09 does not replace or reopen NMB.
- **Activity membership:** assigned Matrix activity membership is frozen for
  both AAC and AEU; no add/remove/replace/explicit-empty semantic mutation.
- **Exact Activity-Version links:** assigned Matrix exact selections are
  frozen; a cohort pointing at V1 remains on V1. No V1→V2 relink, link
  removal or indirect/default newer-version replacement through ordinary
  Matrix management. Unassigned Matrix retains existing legal management.
- **Activity-Version rule freeze:** an existing Activity Version selected by
  any assigned Matrix cannot have its historical academic rule mutated in
  place. Shared case: assigned Matrix A + unassigned Matrix B both reference
  V1 ⇒ V1 is frozen. A Version referenced only through an unassigned Matrix
  is not frozen merely due to that unassigned reference. New Activity
  Version creation remains permitted; FC-07 copy-on-create remains
  authoritative.
- **Deletion / indirect mutation:** assigned Matrix deletion is refused.
  Bulk Matrix deletion preflights atomically so an earlier unassigned Matrix
  is not deleted before an assigned Matrix causes rejection. Indirect
  deletion of catalogue/activity state that would break an assigned
  historical graph is protected. Create-activity-from-Matrix cannot
  partially create Activity/Base/Version/map state when attempting to add
  into an assigned Matrix.
- **Startup historical stability:** `ensure_matrizes_atividades_table` must
  not normalize/rewrite protected academic hour targets of assigned
  Matrices; historical assigned invalid values are preserved rather than
  silently changed. Unassigned Matrix normalization retains prior behavior;
  bootstrap safely handles `turmas` table/column absence. This is startup
  custody protection, not a second application freeze authority.
- **Review history:** initial independent final review
  `FC09_FINAL_REVIEW_REJECT` (material findings: startup normalization could
  mutate assigned Matrix targets; FC09 tests insufficiently discriminating);
  repair rereview `FC09_FINDINGS_REREVIEW_REJECT` (sole residual: W3
  bulk-delete test false-green due to sorted persisted IDs); test-only W3
  repair `U1 < A < U2`; final ultra-targeted independent rereview
  `FC09_W3_FINAL_REREVIEW_ACCEPT`. Custody hash conflict was separately
  reconciled as `REPORTING_TRANSCRIPTION_ERROR` with no unauthorized
  repository mutation.
- **Final test evidence:** latest canonical after production repair: 1631
  passed / 133 skipped / 17 deselected / 0 failed / 0 errors. Final W3
  test-only repair did not change production bytes; post-W3 targeted FC09
  suite: 31 passed. No full canonical rerun after test-only W3 repair by
  design.
- **Invariants:** unchanged — routes 131; endpoints 130; RBAC unmapped 0;
  actor matrix 402; message catalogue 539; Design System 198; route
  inventory unchanged; main `@app.route` 0; main-owned hooks 0; prohibited
  import main 0. No route, endpoint, schema, migration, RBAC, message
  catalogue or CSRF snapshot delta.
- **Non-cutover warning:** FC-09 is NOT full versioning cutover and does NOT
  make request snapshots normative. Still future: request snapshot
  authority for new requests; pending request rule frozen at creation; admin
  processing under historical frozen request rule; progress/hours under
  historical rule; canonical E2E cutover; removal of obsolete legacy
  authority/shadow/mapping paths. Legacy academic-rule paths have not been
  removed.
- **Boundary:** full-database restore remains a global database replacement
  boundary and was not redesigned by FC-09; FC-09 does not protect against
  intentional full-database restore.

## FC-10 — REQUEST SNAPSHOT CREATION AUTHORITY — CLOSED / ACCEPTED

FC10_CLOSED_PUBLISHED. Technical acceptance is final.

### Authority

For every new normal operational requisition for a real aluno/turma, successful
creation requires a creation-time snapshot of the exact Turma Matrix, exact
Matrix-selected Activity Version, exact Norma and academic rule. Student normal
create and admin normal create are Category A mandatory writers. Historical
`admin_importar_requisicoes` rows with `aluno_id=NULL` remain the intentional
Category B legacy/no-snapshot boundary; test and fixture writers are Category C.

`turma.matriz_id` is the sole Matrix authority. The exact persisted
`matriz_atividade_versao_item` selection determines the Activity Version; no
preferred/newest/latest fallback exists. An M1/V1 cohort remains M1/V1 even
when M2/V2 is later available.

### Snapshot contract

Frozen identity includes `atividade_base_id`, `atividade_id_legacy`,
`atividade_versao_id`, `atividade_versao_numero`, `norma_id`,
`codigo_normativo`, `eixo`, `grupo`, `matriz_id_efetiva`, `flow_origin`,
`snapshot_written_at` and `schema_version`. Request columns and JSON identity
are mutually consistent.

Frozen rule/history values include `grupo`, `ch_por_evento`,
`limite_semestre`, `limite_total`, `observacao_aluno`, `observacao_admin`,
`documentos_json`, `vigencia_inicio`, `vigencia_fim`, `numero_versao` and
`status`, plus normative/base identity. `documentos_json` comes from the exact
selected Activity Version, including `NULL`.

Snapshot preparation requires the actual persisted `norma_atividade` row.
Dangling Norma and contradictory Activity Version/Norma/resolver/Matrix
identity fail closed; no mixed-version fallback or field merging is allowed.

### Creation and immutability

Student/admin normal creation is fail-closed. Attachment writes are tracked and
compensated after post-file commit or registration failure, leaving no
`requisicoes` row, `requisicao_arquivos` row or new physical orphan. Partial
file-save cleanup is owned by `student_documents`; request authority remains
in the views. `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` cannot suppress
Category A snapshots; unrelated display/shadow controls are not claimed
retired.

Snapshotted requests retain `atividade_versao_id`,
`codigo_normativo_snapshot` and `regra_snapshot_json` across ordinary edits;
activity identity cannot change in place. Historical no-snapshot rows are not
backfilled, including through GET, edit or startup.

### Review and evidence

Initial independent review: `FC10_FINAL_REVIEW_REJECT`, identifying attachment
orphans, missing physical Norma acceptance, insufficient mixed-identity checks,
omitted `documentos_json` and weak W5/W8 discriminators. Bounded repair was
completed. Targeted independent rereview: `FC10_FINDINGS_REREVIEW_ACCEPT`.

Final executor canonical: 1657 passed / 133 skipped / 17 deselected / 0
failed / 0 errors. Independent final targeted rereview: 260 passed. FC-10
standalone: 26 passed. No canonical rerun occurred after that rereview by
design.

Invariants remain: routes 131, endpoints 130, RBAC unmapped 0, actor matrix
402, message catalogue 539, Design System 198, route inventory unchanged,
`main @app.route` 0, main-owned hooks 0 and prohibited import main 0. No
schema change, migration, v4, route/endpoint/RBAC/message delta or read-side
processing cutover.

FC-10 is the write-side snapshot authority cutover for new normal requests,
not the read-side academic-rule cutover. Admin processing/deferment, pending
requests, progress/historical approved-hour calculations, canonical E2E
cutover and removal of obsolete legacy/shadow/mapping authorities remain
future work. Versioning is not globally complete.

## FC-11 — REQUEST SNAPSHOT PROCESSING AUTHORITY — CLOSED / ACCEPTED

`FC11_CLOSED_PUBLISHED`. Technical acceptance is final. FC-10 made creation
snapshots mandatory; FC-11 makes the frozen request snapshot authoritative for
admin processing and deferment. Processing does not reinterpret a request via
current legacy activity, current Activity Version, current Norma, current
Turma Matrix, preferred/latest Matrix, or a newer Activity Version.

### Authority and processing model

The canonical owner is `app/versioning/snapshots.py`. Its authority states are
`NO_SNAPSHOT`, `VALID_AUTHORITATIVE_SNAPSHOT` and
`INVALID_AUTHORITATIVE_SNAPSHOT`; corrupt or partial snapshot-shaped data is
not treated as historical no-snapshot data. The supported schema is exactly
`d6.4.0-v1`, with one canonical definition shared by writer and reader.
Missing, null, empty, non-string, typo and future schema values are invalid.

A valid snapshot supplies the frozen `limite_total` and `limite_semestre`.
`ch_por_evento` is validated but is not newly enforced because the existing
flow has no per-event cap; FC-11 does not claim to introduce that rule. A
self-contained M1/V1 request remains processable after V2 exists and after
legacy limits, live version, Norma or current Matrix changes. No resolver is
rerun, and current Matrix membership does not invalidate a valid snapshot.
Aggregation remains by persisted `atividade_id`; no progress or base-wide
migration is claimed. Partial deferment uses the frozen rule.

Recognizably snapshotted invalid/corrupt requests are rejected before any
processing mutation for `Pendente`, `Deferida`, `Deferida Parcialmente`,
`Indeferida`, `Devolvida` and `Encerrada`. Status, hours, observations, dates,
admin state, notification state and snapshot columns remain unchanged; there
is no legacy fallback. True no-snapshot compatibility remains, including the
FC-08 NULL-Matrix behavior. No backfill, manufactured version or processing
snapshot creation occurs. Snapshot columns are immutable. The snapshot display
flag is presentation-only.

### Review and evidence

Initial independent review: `FC11_FINAL_REVIEW_REJECT`, finding (1) invalid
snapshots could mutate non-defer statuses and (2) unsupported schema values
were accepted. Bounded repair was completed. Targeted independent rereview:
`FC11_FINDINGS_REREVIEW_ACCEPT`. Technical acceptance is final.

Final executor canonical after repair: 1689 passed / 133 skipped / 17
deselected / 0 failed / 0 errors. Repair-focused executor: 46 passed.
Affected regression executor: 219 passed. Final independent targeted
rereview: 98 passed / 0 failures / 0 errors. No canonical rerun occurred
after the final rereview by design.

Invariants remain: routes 131, endpoints 130, RBAC unmapped 0, actor matrix
402, catalogue 539, Design System 198, route inventory unchanged, main
`@app.route` 0, main-owned hooks 0 and prohibited import main 0. No schema,
migration, v4, route, endpoint, RBAC, message or CSRF delta.

FC-11 closes processing/deferment authority only, not global cutover. Future
work remains student progress under historical semantics, dashboard and
historical approved-hour calculations, canonical E2E cutover, and removal of
obsolete legacy/shadow/mapping paths. Legacy paths remain and global
versioning is not complete. `AGENT_HANDOFF.md`, the execution protocol,
ledger, documentation index and historical contracts are unchanged.

## FC-07 — ACTIVITY VERSION COPY-ON-CREATE — CLOSED / ACCEPTED

FC-07 (activity version copy-on-create) — CLOSED / ACCEPTED. Production
contract, review findings F1–F4, baseline reconciliation and test-only custody
hardening accepted; published by this landing commit.

- **Contract:** Activity owns version history; the existing new-version route
  remains canonical owner; `?from=<atividade_versao_id>` selects one exact
  same-base predecessor; GET is read-only and prefills the editable rule
  fields; normal "Criar versão" uses the existing version with greatest
  `numero_versao`; `versao_anterior_id` records lineage; admin-submitted POST
  values remain authoritative; `codigo_normativo` and `eixo` derive from the
  selected Norma server-side; the new version receives base-wide
  `MAX(numero_versao)+1`; the new version remains `rascunho`; the predecessor
  remains immutable; existing Matrix links remain unchanged. No
  route/endpoint/schema/migration/RBAC change; no Request/snapshot authority
  change.
- **Review findings resolved (F1–F4):** F1 — the three prefill validation
  messages are legitimate scanner-visible `return-message` entries
  (`msg_03205429255601e0`, `msg_46c6438260c43d3e`, `msg_91bb2d4061ab3f00`);
  current canonical message catalogue is **539** (536 was the historical prior
  baseline; 539 is the current post-FC07 baseline). CSRF consequence: exact +3
  `/admin/mensagens/<message_key>/reset` actions; both CSRF snapshots updated
  only for those three legitimate catalogue entries; strict historical custody
  comparators permit exactly that semantic +3 and reject any fourth/unrelated
  delta. F2 — default-predecessor test separates `numero_versao` from
  id/creation order; F3 — base-wide next-number test separates lineage from
  version-number allocation; F4 — Norma derivation test proves the selected
  POST Norma controls `norma_id`/`codigo_normativo`/`eixo`; predecessor and
  Matrix immutability proven.
- **Technical gates:** canonical suite 1574 passed / 133 skipped / 17
  deselected / 0 failed / 0 errors. Invariants: routes 131; endpoints 130;
  RBAC unmapped 0; actor matrix 402; message catalogue 539; Design System 198;
  route inventory unchanged; main `@app.route` 0; main-owned hooks 0;
  prohibited import main 0. Independent final status:
  `FC07_P1_REREVIEW_ACCEPT` / `HISTORICAL_PROOFS_PRESERVED`. Database custody
  preserved.

## NMB — NORMA ↔ MATRIX BINDING — CLOSED / ACCEPTED

NMB (Norma ↔ Matrix Binding) — CLOSED / ACCEPTED. Implementation and
independent review accepted; canonical gate green after the authorized repair.

- **Matrix is the canonical write owner** of the binding management surface
  (`app/views/admin/matrizes.py`, `POST /admin/editar_matriz/<int:matriz_id>`);
  `matriz_norma` remains **many-to-many** — the same Norma may be bound to
  multiple Matrices (no exclusivity filter).
- **Unused Matrix** (no Turma assignment) permits Norma-set management;
  a Matrix assigned to any Turma **freezes academic Norma bindings**
  (add/remove refused) while descriptive edits remain allowed.
- Explicit management intent is carried by `manage_normas_present`; absent
  intent preserves bindings; explicit empty set unbinds; only **active** Normas
  are new-bindable; inactive historical linked Normas are preserved and
  round-trip safely through the rendered form.
- Protected unbind (Norma used by a selected activity version) is **refused
  atomically**; exact `norma_id` authority; single coherent transaction;
  **GET does not write**; Matrix-scoped mutation only.
- **No route, endpoint, RBAC, schema/migration or message-catalogue change**;
  message-catalogue metadata for the reused user-facing messages was preserved
  byte-for-byte (536) by moving presentation strings to the route boundary
  (`_MATRIZ_NORMA_ERROR_TEXT`) and returning internal sentinel codes from the
  routeless validation helper.
- Design System ceiling **198 preserved** (the three NMB static inline styles
  were replaced by `static/css/components/form.css` compositions
  `.field-card.norma-list` / `.norma-checkbox-row`).
- CSRF snapshots unchanged (byte- and mtime-identical); `route_inventory_baseline.json`
  unchanged; full canonical suite green.

Full canonical suite (this window): 1558 passed / 133 skipped / 17 deselected /
0 failed / 0 errors / 446.94s. Invariants: routes 131 / endpoints 130 /
RBAC unmapped 0 / actor matrix 402 / message catalogue 536 / hooks_main 0 /
main `@app.route` 0 / zero `import main` in `app/` `services/` `utils/`.

## POST-REFACTOR APPLICATION DEFECT — ADMIN ARQUIVOS EDIT 500 — CLOSED / ACCEPTED / PUBLISHED

Technical state: **CLOSED / ACCEPTED**.

**This is a post-refactor application defect fix, not structural-refactor or
Design System work.** The structural refactor remains **CLOSED / ACCEPTED /
PUBLISHED**. There is no UT-18. C-2 and later census findings remain separate
and unstarted. This entry does not reopen the structural refactor, Phase 4,
Arquivos extraction work or any Design System phase.

**DEFECT.** The valid admin edit flow was:

`GET /admin/arquivos/<id>/editar` → redirect →
`/admin/arquivos?edit_arquivo=<id>` → formerly HTTP `500`.

**ROOT CAUSE.** `app/admin_files.py::get_admin_arquivo` returns a
`sqlite3.Row`; `app/views/admin/arquivos.py` passed that row as
`edit_arquivo`; `templates/admin_arquivos.html` serializes `edit_arquivo` with
Jinja `|tojson`; and `sqlite3.Row` is not JSON serializable. The helper was not
defective; the defect was at the presentation serialization boundary.

**TECHNICAL COMMIT.** `15b5e92937733e117a8de60502940c8a732e4c06` — **Fix admin
arquivo edit render**. Parent: `2e7215526ee543432c51a47bac6bb59f49dbf4a0`.

The production change is presentation-boundary-only:

```python
edit_row = get_admin_arquivo(...)
edit_arquivo = dict(edit_row) if edit_row is not None else None
```

The helper return contract remains `sqlite3.Row`, and conversion occurs only
before template serialization. `None` behavior remains preserved. There was no
route change, endpoint change, query change, RBAC change, POST edit behavior
change, template change, schema change or migration change.

**RED / FUNCTIONAL COVERAGE.** `tests/test_admin_arquivos.py` added exactly two
selected C-1 regression tests:

- valid edit flow follows the redirect to the final render and proves the
  serialized edit payload;
- nonexistent edit query id renders `200` with a null edit payload.

| State | Result |
|---|---|
| Broken-tree RED | 1 failed / 6 passed |
| Final focused gate | 7 passed |

The positive RED reproduced the exact `TypeError: Object of type Row is not
JSON serializable`. The negative control already passed.

**CSRF SNAPSHOT RECONCILIATION.** Both canonical CSRF snapshots were regenerated
only through the sanctioned `--update-csrf-snapshots` mechanism and became
byte-identical to each other. Each has SHA-256
`31668315a5564217865f46f93c94373a4e7d36e978505fc85e47c13eeb2d5ab9`.

The direct C-1 delta is `/admin/arquivos?edit_arquivo=1` `500 → 200`. The
semantic consequences are narrow and mechanical:

- the edit row gains rendered-form CSRF evidence;
- `csrf_in_html` becomes `true`;
- the edit form has `token_count = 1`;
- edit classification changes from `ok_dynamic_form_token` to
  `ok_rendered_form_token`;
- the delete row gains the two dynamic evidences exposed by the rendered page;
- `ok_dynamic_form_token` changes `14 → 13`;
- `ok_rendered_form_token` changes `54 → 55`.

There is no risk delta, notes delta, route/method delta, high-risk delta or
total-mutating-route delta. The `shadow_on` and `shadow_off` C-1 deltas are
identical.

**HISTORICAL CONTRACT RECONCILIATION.** Narrow reconciliation was required in:

- `tests/test_ut10_arquivos_blueprint.py`;
- `tests/test_phase4_alunos_turmas_cursos_blueprint.py`;
- `tests/test_phase4_matrizes_blueprint.py`;
- `tests/test_phase4_requisicoes_blueprint.py`.

UT-10 frozen historical Arquivos shapes were **not rewritten**. C-1 is handled
as a separate post-refactor normalization/authorization. Historical baseline
SHAs remain unchanged:

- B6: `cab4c61bdf7a1eef361a80f426dda558b11e9201`;
- Matrizes: `ef874b9d14b02656a0f26ea885024a280d49682e`;
- Requisicoes: `c587098152e97d125f41a2d26f2f414c10ae5676`.

Historical cumulative totals remain `36 / 44 / 49`. The already-authorized
course-detail `/admin/cursos/2` `500 → 200` exception remains separate and
unchanged.

Independent governance-contract review: **ACCEPT**, zero MATERIAL, zero
NON_MATERIAL, zero OUT_OF_SCOPE and zero FUTURE_HARDENING findings. The
reconciliation rejected the adversarial false-green mutations used by the
independent review.

**REVIEW CHAIN.**

- implementation independent R1: **ACCEPT**, no MATERIAL findings;
- snapshot reconciliation: exact C-1-only semantic delta, no unexpected delta;
- historical governance reconciliation: **RECONCILED**;
- independent governance reconciliation R1: **ACCEPT**, zero findings;
- local technical commit qualification: **QUALIFIED**.

### Canonical qualification

Command: `python -m pytest -q`

| Metric | Result |
|---|---:|
| collected | 1686 |
| deselected | 17 |
| selected | 1669 |
| passed | 1536 |
| skipped | 133 |
| failed | 0 |
| errors | 0 |
| duration | 341.01s |

Arithmetic: `1686 - 17 = 1669`; `1536 + 133 = 1669`.

The canonical run was green for `tests/test_admin_arquivos.py` 7/7, the
UT-10 C-1 reconciliation, the Phase-4 B6, Matrizes and Requisicoes
reconciliations, UT-15 snapshot custody, UT-16 artifact custody, UT-17
artifact custody and both CSRF inventory audit parameterizations. No visual
baseline or Design System changes occurred. The message catalogue remains
536, and the route, endpoint and RBAC surface remains unchanged.

### Database and sidecar custody

The local custody sentinel for this window is:

| Metric | Value |
|---|---|
| `database.db` size | 544768 bytes |
| `database.db` SHA-256 | `df3bb46a00d2c846f64295e5ef4363aa731fe380b52b5c9d5a7a33a9338bbcdf` |
| `database.db-wal` | absent |
| `database.db-shm` | absent |
| `database.db-journal` | absent |

This is a local custody sentinel for this window only and does not replace the
canonical historical database baseline.

The eight repository-root pre-D6 WAL/SHM files encountered during TC-1 were
independently classified as **PRE-EXISTING / IGNORED / NONCANONICAL** historical
snapshot artifacts. Their exact identity is governed by
`docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`; they remained
byte-identical, no cleanup was performed or authorized, and no new runtime
sidecar appeared.

### Deferred census findings — not actioned

C-1 alone is closed. The remaining census findings remain separate and
**UNSTARTED**:

- **C-2:** Admin Arquivos row-action JavaScript `ReferenceError` caused by the
  `canArquivosEdit` / `canArquivosFull` scope mismatch;
- **C-3:** XLSX import / SheetJS CDN versus CSP allowlist mismatch;
- **C-4:** provider brand image paths missing in uploads;
- **C-5:** matrix `NULL` date renders `None`.

None of these is classified as authorized implementation, and C-2 was not
started.

### Publication status

Technical state: **CLOSED / ACCEPTED / PUBLISHED**. Technical commit
`15b5e92937733e117a8de60502940c8a732e4c06` was published, and governance
record `66c51cfd355eb53861ffe2b4e1dd9eb22bf5c766` was published by normal
fast-forward. Post-publication verification confirmed the live remote at
`66c51cfd355eb53861ffe2b4e1dd9eb22bf5c766` before this closeout record. C-2,
C-3, C-4 and C-5 remain separate and **UNSTARTED**.

## POST-REFACTOR APPLICATION DEFECT — COURSE DETAIL 500 — CLOSED / ACCEPTED / PUBLISHED

Published by this governance landing commit (landing SHA not invented).

**This is an application defect fix, not Design System work.** It is **NOT
DS-9**, **NOT UT-18**, and does not open, extend or reopen any Design System
phase or the UT roadmap. It was discovered as carried-forward debt during
DS-8 (`docs/design-system/README.md` §8) but the fix itself is a missing
view template plus its test/governance coverage — no CSS, no route, no RBAC,
no query.

**DEFECT.** The admin course detail page returned HTTP 500 for every valid
course because `templates/admin_detalhes_curso.html` did not exist, even
though the handler that rendered it (`admin_detalhes_curso`, in
`app/views/admin/alunos_turmas_cursos.py`) was otherwise correct and
unchanged since before the UT structural refactor.

**LIVE USER PATH.** `GET /admin/cursos/<id>/visualizar` → redirect →
`GET /admin/cursos/<id>` → formerly `500` → now `200`. Reachable directly
from the "Ver curso" hover action on `admin_cursos.html`.

**ROOT CAUSE.** Missing template only. No route, query or RBAC defect —
confirmed by the unmodified Phase-4 AST/route/RBAC structural tests.

**Technical commit:** `7911e57945cde4fb589d0b8c2ece16d5003918da` — Add admin
course detail page.
**Governance test reconciliation:** `63bd7e6028dd15390f1ab9b7f89da1959709ca87`
— Reconcile course-detail CSRF governance ledgers.

**Implemented contract:**
- dedicated course-detail page (`templates/admin_detalhes_curso.html`);
- consumes only the already-supplied `curso` + `turmas` handler context, no
  new query;
- no Python application logic changed — route path, endpoint name, queries,
  RBAC decorator, invalid-id guard and the `visualizar` redirect are all
  byte-identical to before;
- current Design System components reused throughout (see
  `docs/design-system/README.md` §8 for the DS-relevant detail);
- one scoped list-layout rule added, `.imp-curso-turmas` in
  `static/css/components/list-cards.css`.

**Test coverage:** six new functional tests in
`tests/test_admin_curso_detalhes.py` — populated render, `visualizar`
redirect-then-render, invalid id (already-correct behaviour pinned), aluno
access blocked, unauthenticated access blocked, zero-turmas empty state; one
new visual baseline (`page_admin_curso_detalhes`).

**CSRF golden change.** Both sanctioned CSRF snapshots
(`tests/_artifacts/csrf_inventory_shadow_off.json` and `shadow_on.json`)
changed in exactly one field each: `/admin/cursos/2` `status_code`
`500 → 200` — the single, correct, intended consequence of the fix. The
three historical governance ledgers that independently assert on those
snapshots (`test_phase4_alunos_turmas_cursos_blueprint.py`,
`test_phase4_matrizes_blueprint.py`, `test_phase4_requisicoes_blueprint.py`)
were reconciled to authorize exactly that one delta, with every historical
row partition, named category and baseline commit SHA (36 / 44 / 49)
preserved unchanged. Independent review of the reconciliation: **ACCEPT**,
zero MATERIAL, zero NON_MATERIAL findings, adversarially tested against 8
false-green scenarios with zero passes.

**Independent review chain:** implementation R1 —
`ACCEPT_IMPLEMENTATION_PENDING_GOVERNANCE_RECONCILIATION`, zero MATERIAL;
governance-ledger reconciliation spot review — **ACCEPT**, zero MATERIAL,
zero NON_MATERIAL.

### Measured state at governance time

| Metric | Value |
|---|---|
| course-detail focused tests | 6/6 |
| visual baselines | 88/88 (87 unchanged + 1 new), zero regeneration |
| F-7 popover contract | 38/38 |
| dashboard container contract | 7/7 |
| DS static gates | 11/11 |
| message catalogue | 536 unchanged |
| cross-engine (new page) | Chromium / Firefox / WebKit — PASS, 0 divergence |
| supported width (new page) | 1440 / 1024 / 900 / 768 — PASS, 0 horizontal overflow |

Canonical reconciliation:

| Metric | Value |
|---|---|
| collected | 1684 |
| selected | 1667 |
| passed | 1534 |
| skipped | 133 |
| deselected | 17 |
| failed | 0 |
| errors | 0 |

### Database custody

The repository-local `database.db` sentinel (SHA-256 `df3bb46a…8bbcdf`, 544768
bytes, `change_counter` 98, `user_version` 3, `schema_cookie` 157) was
verified identical across the defect diagnosis, the implementation, the
governance-ledger reconciliation, and this final governance/publication
pass. **This is a local custody sentinel for this window only — it does not
replace the canonical documented `database.db` baseline** recorded under
"Database baseline" below.

### Carried forward — NOT closed by this fix

Unrelated debt remains open and is not touched or reopened by this entry:
F-7 findings F1–F5, modal focus containment, the WebKit visual-catalogue
login race, runtime requisição CSS, the mobile/640 product decision,
`.btn-primary` unstyled, `admin_turma_form.html`
(`UNROUTED_BUT_REFERENCED`), the deferred Atividades v1/template cleanup,
and the broader brittle historical-ledger test-design pattern this fix's
reconciliation narrowly worked around (`PRE_EXISTING_TEST_DESIGN_DEBT` — the
three ledgers' all-or-nothing whole-summary equality is fixed for this one
delta only, not redesigned). See `docs/design-system/README.md` §8 for the
full register.

## POST-REFACTOR DESIGN SYSTEM — DS-8 — CLOSED / ACCEPTED / PUBLISHED

Published by this governance landing commit (landing SHA not invented).

**Relationship to the UT roadmap.** DS-8 is a post-refactor Design System phase
on the same frontend track as F-7 and the responsive milestone below. It is
**NOT UT-18**; there is no UT-18. The structural refactor remains **CLOSED /
ACCEPTED / PUBLISHED** and nothing here modifies, reopens or supersedes any UT
verdict, the structural plateau, or the C1–C7 criteria.

**DS-8 technical commit:** `2c69d06c6e2191b0e442f60b15d7859474da05d6`
(parent `95d7c90d62e1581a430664ee71ef025ee299166f`, the F-7 governance landing).
This commit's tree is byte-identical to the technical work first landed as
`ebd8bab46a51149313d54cc196a40f2349b76687` — R1 (below) reviewed that tree;
after R1, only the commit **message** was amended to correct cascade
aggregates that had been captured mid-experiment (tree SHA before/after amend:
identical; `git diff ebd8bab 2c69d06`: empty). Do not refer to `ebd8bab` as
the current DS-8 commit.

**Scope.** Dead CSS removal with consumer evidence, plus one dead template.
Four files changed, deletion only:

- `static/css/modern-style.css`
- `static/css/components/form.css`
- `static/css/foundation/tokens.css`
- `templates/components/content_block.html` (deleted)

No selector was reordered, renamed, moved, reformatted or consolidated; no
baseline was regenerated. Backend behaviour, business logic, services, schema
and migrations: unchanged.

**Result.** 108 selectors deleted across 113 (context, selector) keys, plus
one property (`--btn-primary-light`) removed from a surviving `:root`.
`modern-style.css` 1623 → 1281 lines (−342, −21.1%). Total Design System CSS
2683 → 2333 lines (−350, −13.0%).

**`admin_turma_form.html` was authorized for deletion and was NOT deleted.**
It has no routed consumer, but `utils/messages.py::_iter_frontend_files()`
scans `templates/**/*.html` by directory and this template contributes 3
message-catalog entries; deleting it drops the catalog 536 → 533, restoring it
returns 536. Reclassified `UNROUTED_BUT_REFERENCED`, not dead, and withheld.

### Independent review

**R1 independent adversarial review of the DS-8 tree: ACCEPT — zero MATERIAL
findings.** The review re-derived deadness by two independent methods (static
class-token scan across 347 files and live-DOM query against the pre-deletion
tree across 40 surface/viewport/overlay states — 0 of the 108 deleted
selectors matched any element), re-ran `tools/ds_css.py`'s cascade-equivalence
gate directly rather than trusting the executor's summary, and re-derived the
message-catalog counts for both the deleted template and the withheld one.
Non-material observations and future-hardening items were recorded and
deliberately NOT actioned, so the reviewed technical tree is exactly the tree
that was accepted. Findings carried forward are recorded in
`docs/design-system/README.md` §8.

### Cross-engine pre-publication verification

Verified on **Chromium 151.0.7922.34, Firefox 153.0 and WebKit 26.5**, 23
production surfaces per engine (list, report, dashboard, form/modal,
requisições) — **0 geometry/computed-style deltas parent-vs-DS-8 on any
engine**, 0 horizontal overflow. A WebKit login-race artifact in the shared
visual harness (pre-existing, present on both trees, recorded in
`docs/design-system/README.md` §8) was worked around out-of-tree without
modifying `tools/visual/catalogue.py`.

### Measured state at governance time

- visual baselines: **87**, zero regenerated
- cascade equivalence (`tools/ds_css.py`, DS-8 vs its parent):
  0 ORDER VIOLATED, 0 RESOLUTION CHANGED, 0 RESOLUTION ADDED, 26,076
  RESOLUTION LOST (all traced to the deleted manifest), 59 TOKEN CHANGED (all
  `--btn-primary-light`)

Canonical reconciliation:

| Metric | Value |
|---|---|
| collected | 1677 |
| selected | 1660 |
| passed | 1528 |
| skipped | 132 |
| deselected | 17 |
| failed | 0 |
| errors | 0 |

### Database custody

The repository-local `database.db` sentinel (SHA-256 `df3bb46a…8bbcdf`, 544768
bytes, `change_counter` 98, `user_version` 3, `schema_cookie` 157) was verified
identical at entry and exit of both the R1 review and this governance pass.
**This is a local custody sentinel for this review window only — it does not
replace the canonical documented `database.db` baseline** recorded under
"Database baseline" below. During R1, a read-only SQLite connection against
this WAL-mode database materialised two untracked, gitignored sidecars
(`database.db-wal`, `database.db-shm`); the database content was never
touched (byte-identical hash, unmoved `change_counter`) and the sidecars were
removed before this governance commit.

### R1 findings carried forward — NOT closed by DS-8

See `docs/design-system/README.md` §8 for the full register, including the
`admin_turma_form.html` reclassification, the Atividades v1 family, the
catalogue-aware proof required before deleting the remaining deferred
templates, and the pre-existing `admin_detalhes_curso.html` missing-template
defect (outside DS-8 scope — DS-8 is CSS/template-ownership, not view work).

## POST-REFACTOR DESIGN SYSTEM — F-7 — CLOSED / ACCEPTED / PUBLISHED

Published by this governance landing commit (landing SHA not invented).

**Relationship to the UT roadmap.** F-7 is a post-refactor Design System phase on
the same frontend track as the responsive milestone below. It is **NOT UT-18**;
there is no UT-18. The structural refactor remains **CLOSED / ACCEPTED /
PUBLISHED** and nothing here modifies, reopens or supersedes any UT verdict, the
structural plateau, or the C1–C7 criteria.

**F-7 implementation commit:**
`5e25bce44594e9a9cb6dfae60c865fa9e9284645`
(parent `0835ac180a9f71ef0e283acff0f83254806c208f`, the responsive-milestone
governance landing). The implementation tree was frozen at that commit and was
NOT modified by this governance commit.

**Scope.** Frontend only, four items:

1. **Popover vertical reachability.** Sort, filter and the actions menus are now
   clamped on the vertical axis as well as the horizontal one, 12px inside the
   viewport edge where the clamp binds.
2. **Popover close-on-scroll behaviour.** All three dismiss on a `.app-main`
   scroll or a window resize instead of remaining pinned to the screen while
   their anchor scrolls away. Scrolls originating inside a popover are exempt.
3. **Actions-menu rendered-width measurement.** Every opener now reveals the menu
   before measuring it, retiring the hidden-width fallback that measured a
   `display:none` element.
4. **Sort focus visibility.** `#sort-field` and its direction toggle expose a
   visible `:focus-visible` indicator on all four live id-families.

Backend behaviour, business logic, services, schema and migrations: unchanged.
Frontend runtime behaviour was intentionally changed, which is the point of the
work.

**Why the previously deferred vertical clamp was reopened.** The responsive
milestone deferred it on the stated premise that an overrun bottom edge stays
reachable because it scrolls with `.app-main`. That premise was measured and is
false: the document never scrolls, so the popover is pinned to the screen while
its anchor moves. The deferral was reopened on that new evidence, not on taste.

### Independent review

**R1 independent adversarial review of `5e25bce4`: ACCEPT — zero MATERIAL
findings.** The review re-derived the scroll model, the coordinate conversion,
the clamp arithmetic, the focus specificity and the baseline causation from the
diff and from measured rendered behaviour rather than from executor reports, and
challenged all four page-template migrations individually. Findings F1–F5 below
were recorded and deliberately NOT actioned, so the reviewed technical tree is
exactly the tree that was accepted.

### Cross-engine pre-publication verification

Verified on **Chromium 151.0.7922.34, Firefox 153.0 and WebKit 26.5**, driven
through the production click paths — **all PASS on all three engines, no
divergence**:

- binding vertical clamp: 12px bottom margin, zero actionable controls off screen;
- non-binding geometry: the 6px anchor relationship preserved (measured 5.9px);
- dismissal on `.app-main` scroll, with `aria-expanded` returning to `false`;
- internal-menu scroll exemption, tested against a forced-scrollable pane;
- sort focus indicator visible and unclipped;
- actions-menu real-width horizontal containment.

### Measured state at governance time

- visual baselines: **87** (83 carried forward, 4 added by F-7)
- opt-in browser tests: **132** = 87 visual + 7 dashboard container-contract +
  38 F-7 popover-reachability
- static Design System gates: **11**

Canonical reconciliation:

| Metric | Value |
|---|---|
| collected | 1677 |
| selected | 1660 |
| passed | 1528 |
| skipped | 132 |
| deselected | 17 |
| failed | 0 |
| errors | 0 |

One pre-existing baseline was re-approved: `page_admin_mensagens`, 44 of
1,296,000 pixels inside a single 7×8px box, with zero differing pixels outside
it. That page renders the runtime-computed source line number of each message
literal; F-7 added five lines above one literal in `admin_acesso.html`, moving
its reported origin from `:1090` to `:1095`. R1 proved causation from the file
history and classified it JUSTIFIED_INCIDENTAL_CONTENT_DELTA. No other baseline
changed, which is itself the evidence that resting geometry did not move.

### R1 findings carried forward — NOT closed by F-7

| ID | Class | Finding |
|---|---|---|
| F1 | NON_MATERIAL | `admin_reportes` and `admin_requisicoes` call `syncItems()` after `openFixedMenu()`, so their clamp can briefly measure the previous content state. No production reachability failure was reproduced. Small future hardening candidate. |
| F2 | PRE_EXISTING_TEST_DEBT | Five zero-row actions-menu consumers are exercised through the shared opener rather than a seeded real click path. At least one seeded-row end-to-end case would improve consumer-wiring coverage. |
| F3 | NON_MATERIAL | Sort/actions dismissal is capture-phase and therefore also fires on unrelated page scrollers. Over-eager but not functionally wrong. |
| F4 | NON_MATERIAL | The `clamp_binds` test heuristic conditionally gates one 12px assertion. |
| F5 | FUTURE_HARDENING | The approved `--focus-ring-color` produces approximately 1.68:1 contrast against the white button surface, below the 3:1 non-text contrast target. This is inherited Design System convention, not an F-7 implementation defect. |

**F-7 does not close the broader focus-contrast problem, does not implement modal
focus containment, and claims no phone/mobile or 640px support.** Outstanding
Design System debt remains recorded in `docs/design-system/README.md` and is
explicitly NOT closed by this phase.

## POST-REFACTOR DESIGN SYSTEM — RESPONSIVE MILESTONE — CLOSED / ACCEPTED / PUBLISHED

Published by an earlier governance landing commit (landing SHA not invented).

**Relationship to the UT roadmap.** The Design System track is a separate line of
work that began after the structural refactor closed. It is NOT UT-18; there is
no UT-18. The structural refactor remains **CLOSED / ACCEPTED / PUBLISHED**, and
nothing in this section modifies, reopens or supersedes any UT verdict, the
structural plateau, or the C1–C7 criteria recorded below.

**Scope of the Design System track.** Frontend only: `static/css/**`,
`static/js/**`, presentation-level template markup, the Playwright visual
catalogue and its baselines. This milestone changed **no** backend route, **no**
business logic, **no** service, **no** database schema and **no** migration.

**Frontend runtime behaviour WAS intentionally changed by this milestone.** That
is the point of the work, and governance must not be read as claiming otherwise.
The deliberate changes are CSS responsive/reflow behaviour (form label gutter and
narrow-viewport containment, toolbar wrapping, dashboard grid column counts, the
content-block row wrap) and popover positioning in
`static/js/toolbar-filters.js`. What did not change is backend behaviour, per the
scope statement above.

### Reviewed technical chain

Phases, in order, ending the reviewed chain at F-6B2:

| Phase | Commit | Subject |
|---|---|---|
| F-5D | `aac630f` | reserve the label gutter instead of centring into it |
| F-5E | `9db9078` | contain the form in the track it actually lives in |
| F-6A1 | `0354f55` | let the toolbar wrap in the column it actually has |
| F-6A2 | `1219a2e` | give the sort/filter popovers the clamp the actions menu already had |
| F-6B | `85bda75` | let the dashboards measure the column they have, not the window |
| F-6B2 | `cc82f36` | let the Resumo row break instead of running off the card |

Earlier phases on this track, already published: DS-1, DS-2A, DS-3, DS-3b,
DS-4, DS-5, DS-6, DS-7, F-5B, F-5C.

### Independent review

**R1 independent adversarial review of `cc82f36`: ACCEPT — zero MATERIAL
findings.** The review re-derived the container-query boundary, the popover
clamp arithmetic, the toolbar contract and the content-block blast radius from
the diff and from measured rendered behaviour rather than from executor reports.
Non-material observations, pre-existing test debt and out-of-scope debt were
recorded and deliberately NOT actioned in the governance commit, so the reviewed
technical tree is exactly the tree that was accepted.

### Cross-engine pre-publication verification

Verified before publication on Chromium 151.0.7922.34, Firefox 153.0 and
WebKit 26.5 against one shared application state — all PASS on all four checks:

- container-query boundary: 792px actual track → 4 columns, 791px → 2 columns,
  for `.kpi-grid` (admin and aluno) and `.dashboard-turma-row-kpis`;
- F-5D absolute label geometry: 0 clipped, 0 pushed off-left, geometry identical
  with and without `container-type`;
- F-6A2 popover clamp: exactly 12px inside the viewport where the clamp binds,
  anchor relationship preserved where it does not;
- fixed-overlay geometry: real `.modal-overlay` elements inside `.app-track`
  measure the full viewport at (0,0) and still cover sidebar and header, so
  `container-type:inline-size` does not become the fixed-position containing
  block in any of the three engines.

### Measured state at governance time

- visual baselines: **83** (before this governance commit)
- opt-in browser tests: **90** = 83 visual + 7 dashboard container-contract
- static Design System gates: **11**

Latest accepted canonical reconciliation:

| Metric | Value |
|---|---|
| collected | 1635 |
| selected | 1618 |
| passed | 1528 |
| skipped | 90 |
| deselected | 17 |
| failed | 0 |
| errors | 0 |

Operational Design System documentation: `docs/design-system/README.md` and
`docs/design-system/form-contract.md`. Outstanding Design System debt is
recorded there and is explicitly NOT closed by this milestone.

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

## Full-suite status — structural refactor (UT-17 canonical, historical)

These are the UT-17 figures and they stand as the structural-refactor canonical
record. They are **not** the current suite shape: the Design System track has
since added opt-in browser tests. For the current reconciliation see
**POST-REFACTOR DESIGN SYSTEM** above (1635 collected / 1618 selected / 1528
passed / 90 skipped / 17 deselected / 0 failed / 0 errors).

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

## FC-12 — HISTORICAL APPROVED-HOURS READ AUTHORITY / FUNCTIONAL CUTOVER — CLOSED / ACCEPTED

FC-12 is technically closed and accepted. FC-10 freezes creation-time request
authority; FC-11 consumes that authority during processing; FC-12 now consumes
the same frozen authority across material academic reads and request filters.

### Functional authority

For a valid snapshotted request, current legacy activity state no longer controls
AAC/AEU classification, historical group/name/limits, approved-hour aggregation,
student progress, student dashboard numerators, admin cohort numerators,
cohort student-detail totals, or student/admin request-list inclusion,
exclusion, search, sorting, count, and pagination.

Canonical owner: `app/versioning/request_history.py`, reusing the strict parser
and classifier in `app/versioning/snapshots.py`. Views orchestrate only
aggregation, filtering, and presentation; they do not parse snapshot JSON or own
AAC/AEU mapping.

Authority states remain `NO_SNAPSHOT`, `VALID_AUTHORITATIVE_SNAPSHOT`, and
`INVALID_AUTHORITATIVE_SNAPSHOT`:

- `VALID_AUTHORITATIVE_SNAPSHOT` uses frozen historical request authority.
- `NO_SNAPSHOT` uses accepted legacy compatibility only.
- `INVALID_AUTHORITATIVE_SNAPSHOT` fails closed and never falls back to current
  academic activity state.

Frozen `eixo` is normative and is cross-checked against frozen legacy type;
contradictory authority fails closed. Approved hours remain persisted request
facts: partial approvals use `horas_deferidas`, while full approvals retain the
accepted deferred/requested semantics. Activity-Version rules do not recompute
approved hours.

The exact persisted Turma Matrix remains the cohort denominator/requirement
authority. Historical snapshots remain numerator/classification authority.
Current progress catalogue resolution is Turma -> exact Matrix -> exact
Matrix-selected Activity Versions, with no preferred/latest replacement,
fabricated 160/80 fallback, or historical out-of-catalogue loss.

V1 and V2 requests sharing one legacy activity retain independent frozen
metadata and are not collapsed or double-counted. Read paths do not backfill,
manufacture Activity Versions, rewrite snapshot columns, or mutate history.

### Request-filter repair and review history

The initial independent review found a material residual: student/admin request
lists filtered by current live activity fields before frozen presentation. The
bounded repair moved canonical historical filtering/search/sort before count,
pagination, and rendering. Frozen AAC + live AEU remains AAC-only; frozen AEU +
live AAC remains AEU-only; mixed valid/no-snapshot rows preserve both authority
categories.

The original T30 three-string residual scan was replaced by an AST-based
production-owner census plus adversarial behavior tests for every material
consumer. Final independent rereview accepted:

`FC12_ZERO_MATERIAL_AUTHORITY_RESIDUAL`

No material production read path can reinterpret the academic meaning,
inclusion/exclusion, classification, grouping, approved totals, historical
limits, or historical identity of a valid snapshotted request using current
legacy activity state. This does not mean legacy compatibility, shadow, or
mapping code has been physically removed.

Review history: initial candidate `FC12_READY_FOR_INDEPENDENT_REVIEW`; initial
independent review rejected the candidate for the filter residual and false-
green T30; bounded repair completed; final targeted rereview
`FC12_FINDINGS_REREVIEW_ACCEPT`. The supplied final rereview evidence records
107 direct repair/regression checks and 15 invariant guards, with canonical
evidence independently accepted without rerun.

### Final evidence and invariants

- Repair cases: 8 passed.
- FC-12 test file: 24 passed.
- Filter/regression lane: 88 passed.
- Focused gate: 325 passed.
- Full canonical: 1713 passed, 133 skipped, 17 deselected, 0 failed, 0 errors.
- Invariants unchanged: routes 131; endpoints 130; RBAC unmapped 0; actor
  matrix 402; message catalogue 539; Design System 198; route inventory
  unchanged; main routes 0; main hooks 0; prohibited main imports 0.
- No schema, migration, v4, route, endpoint, RBAC, message, or CSRF delta.

Functional academic authority cutover for the ordinary FC-10 -> FC-11 -> FC-12
versioned lifecycle is accepted. The project is not globally finished: obsolete
legacy/shadow/mapping authority paths, transitional flags, and true
no-snapshot compatibility boundaries remain the next cleanup front. AAC -> AEU
exceptional workflow remains a separate product concern.

This FC-12 state is published by the authorized landing commit; the landing
SHA is Git-authoritative and is not duplicated here.

## FC-13 — OBSOLETE AUTHORITY / SHADOW / MAPPING CLEANUP — CLOSED / TECHNICALLY ACCEPTED

Identifier: `FC13-OBSOLETE-AUTHORITY-SHADOW-MAPPING-CLEANUP-1`.

Final technical verdict: `FC13_W19_FINAL_REREVIEW_ACCEPT`.

**FC-13 OBSOLETE EXECUTABLE AUTHORITY CLEANUP TECHNICAL ACCEPTANCE IS FINAL.**

FC-13 removed obsolete executable shadow authority and physically removed its
retired launchers. It also removed the dead preferred-Matrix startup census and
helper and the zero-caller generic resolver facade. Active current-write,
exact-persisted-resolution, and diagnostic purposes remain supported. The
semantic absence contract now rejects equivalent resurrection through renamed
flags, inline latest-selection SQL, executable tooling, re-exported facades,
test-only callers, and unqualified same-name call collisions.

No schema or table was removed. Schema version remains 3, with no migration v4.
The AAC -> AEU exceptional workflow remains separate and outside FC-13.

### Final accepted evidence

- Full canonical: 1718 passed, 133 skipped, 17 deselected, 0 failed, 0 errors.
- Final semantic scanner: 48 passed.
- Routes/endpoints: 131/130.
- RBAC unmapped: 0.
- Actor matrix: 402.
- Message catalogue: 539.
- Design System inline ceiling: 198.
- Main routes/hooks/prohibited imports: 0/0/0.
- Schema version: 3; no v4.

### Final residual and false-green census

- `PROVEN_DEAD_EXECUTABLE_RESIDUAL_COUNT = 0`
- `PROVEN_DEAD_INERT_FILE_RESIDUAL_COUNT = 0`
- `TEST_ONLY_RETENTION_COUNT = 0`
- `SEMANTIC_FALSE_GREEN_CASES = 0`
- `PACKAGE_REEXPORT_FALSE_GREEN_CASES = 0`
- `DIRECT_TOOL_EXECUTION_FALSE_GREEN_CASES = 0`
- `CALLER_OWNERSHIP_FALSE_GREEN_CASES = 0`
- `TEST_CALLER_FALSE_GREEN_CASES = 0`
- `SAME_NAME_COLLISION_FALSE_GREEN_CASES = 0`

FC-13 is technically closed and accepted. Publication is performed by the
single authorized landing commit; the landing SHA remains Git-authoritative.

## AAC -> AEU EXCEPTIONAL WORKFLOW — CLOSED / ACCEPTED

Final verdict: `AAC_AEU_FINDINGS_REREVIEW_ACCEPT`.

**AAC→AEU EXCEPTIONAL WORKFLOW TECHNICAL ACCEPTANCE IS FINAL.**

AAC means Acadêmica Complementar; AEU means Extensão Universitária. A legal
AAC -> AEU transition is explicit `aac_para_aeu` provenance, with a required
justification, between versions of the same conceptual activity. The exact
Matrix-selected Activity Version controls current classification: the old
Matrix preserves AAC and the successor Matrix preserves AEU.

A valid historical request snapshot freezes exact Matrix, Activity Version,
Norma, and axis authority. Historical admin request processing uses the frozen
`matriz_id_efetiva`, never the student's current Matrix. Current/new-request
scope continues to use the student's current exact Matrix. Invalid historical
authority fails closed; legitimate `NO_SNAPSHOT` compatibility remains
preserved.

If the historical admin modal cannot load request authority, activity mutation
fails closed. The mutable legacy client catalogue is not an executable
fallback. The server owns authority selection; the client renders that result
and does not independently decide AAC/AEU.

The stale post-FC13 startup-contract test seam was repaired without reopening
FC-13. It no longer depends on a transient uncommitted Git deletion state. The
final synthetic isolated-Git contract preserves:

- tracked plus Git-deleted file -> intentional deletion;
- tracked/modeled plus unexpectedly missing without Git deletion -> fail closed.

Final accepted evidence: AAC lane 13 passed; direct admin regressions 4 passed;
invariant/governance nodes 11 passed; full canonical 1731 passed, 133 skipped,
17 deselected, 0 failed, 0 errors.

Final invariants: routes 131; endpoints 130; RBAC unmapped 0; actor matrix 402;
message catalogue 539; Design System inline styles 198, accepted ceiling 198;
main routes 0; main hooks 0; prohibited main imports 0; schema version 3;
migrations v1/v2/v3 only; no v4.

No schema change, migration, or repository database mutation occurred. This
workflow is published by the authorized landing commit; its SHA remains
Git-authoritative.

## SCHEMA OWNER CLEANUP — CLOSED / TECHNICALLY ACCEPTED

Final verdict: `SCHEMA_OWNER_CLEANUP_INDEPENDENT_REVIEW_ACCEPT`.

**SCHEMA OWNER CLEANUP TECHNICAL ACCEPTANCE IS FINAL.**

`get_schema_status` is read-only: inspection with an absent
`schema_migrations` registry and restore-candidate inspection are non-mutating.
`app/db_maintenance.py::ensure_requisicao_arquivos_table` is the single
canonical DDL owner for `requisicao_arquivos`; bootstrap, admin, and student
paths are callers only. `grupos_def` has one defining owner, reused by group
rename and delete.

Physical schema and compatibility storage are unchanged. Schema version remains
3 with migrations v1/v2/v3 only; no v4, data migration, or backfill occurred.
Accepted census deltas are: query/schema side effects 40 -> 39; duplicate schema
authority 2 -> 0; route-local schema objects 3 -> 2; proven-dead logical paths
5 -> 0; proven-dead physical objects 0; physical compatibility objects 11
unchanged; stale current Phase-3 statements 11 -> 0.

Accepted evidence: new contract nodes 6 passed; authorized focused lane 120
passed; invariant lane 18 passed; full canonical 1736 passed, 133 skipped, 17
deselected, 0 failed, 0 errors; independent targeted review 77 passed, 0 failed.
Final invariants: routes 131; endpoints 130; RBAC unmapped 0; actor matrix 402;
message catalogue 539; Design System 198 / ceiling 198; main
routes/hooks/prohibited imports 0/0/0.

No physical schema object is currently proven dead. No table, column, index, or
trigger deletion is justified; legacy compatibility storage remains live and
required. Destructive schema cleanup is not authorized or justified on current
evidence, and no migration v4 is required.

## SGAA-EJ REFACTOR — FINAL COMPLETION RECONCILIATION

The structural refactor is complete and all mandatory current fronts are
closed. `TOTAL_REAL_REFACTOR_RESIDUAL_COUNT = 0` and
`RELEASE_LANDING_RESIDUAL_COUNT = 0`. Current publication of
`refactor/design-system-foundation` is sufficient for refactor completion; no
merge, pull request, fast-forward, tag, release branch, deployment, or other
`main` action is required by current governance. Deployment is separate and is
not required for technical completion.

No migration v4 is required. No physical schema cleanup is justified. There is
no UT-18, and no DS-9 is automatically authorized.

**SGAA-EJ REFACTOR HAS NO REMAINING REAL TECHNICAL RESIDUALS.**

Final accepted evidence: 1736 passed / 133 skipped / 17 deselected / 0 failed /
0 errors. Final invariants: routes 131; endpoints 130; RBAC unmapped 0; actor
matrix 402; message catalogue 539; Design System 198 / ceiling 198; main
routes/hooks/prohibited imports 0/0/0; schema version 3; migrations v1/v2/v3
only; no v4.

### Final reconciliation census

- `PROJECT_STATE_REAL_RESIDUAL_COUNT = 0`
- `MASTER_PLAN_REAL_RESIDUAL_COUNT = 0`
- `CURRENT_CANONICAL_DOC_CONTRADICTION_COUNT = 0` (reconciled from 3)
- `MAIN_REAL_OWNERSHIP_RESIDUAL_COUNT = 0`
- `ROUTE_EXTRACTION_REAL_RESIDUAL_COUNT = 0`
- `SHARED_OWNER_REAL_RESIDUAL_COUNT = 0`
- `VERSIONING_REAL_RESIDUAL_COUNT = 0`
- `SCHEMA_REAL_RESIDUAL_COUNT = 0`
- `DESIGN_SYSTEM_REAL_RESIDUAL_COUNT = 0`
- `TEST_GUARDRAIL_REAL_RESIDUAL_COUNT = 0`
- `CODE_MARKER_REAL_REFACTOR_RESIDUAL_COUNT = 0`
- `PROVEN_DEAD_FILE_RESIDUAL_COUNT = 0`
- `ACCEPTED_COMPATIBILITY_DEBT_COUNT = 8`
- `FUTURE_PRODUCT_WORK_COUNT = 9`
- `TOTAL_REAL_REFACTOR_RESIDUAL_COUNT = 0`
- `RELEASE_LANDING_RESIDUAL_COUNT = 0`

### Accepted compatibility debt

Retained compatibility is not unfinished refactor work:

1. legacy atividades storage;
2. Matrix legacy-link storage;
3. `atividade_legacy_map`;
4. true `NO_SNAPSHOT` requests;
5. legacy request columns/fields;
6. runtime `ensure_*` compatibility callers;
7. `main` compatibility exports/facades;
8. two active route-local feature schemas.

`ACCEPTED_COMPATIBILITY_DEBT_IS_NOT_REFACTOR_RESIDUAL`

### Future product work separation

The completion audit identified future product/application work that is
separate from refactor completion: C-2 Admin Arquivos JavaScript scope; C-3
SheetJS/CDN vs CSP; C-4 provider brand images; C-5 Matrix NULL-date
presentation; OneDrive large-file sessions; cloud token encryption;
phone/mobile shell decision; optional hard-RBAC rollout; and optional
multi-worker login rate limiting. None is required or automatically authorized
by this closeout.

### Branch and governance disposition

At the accepted audit topology, protected `main` is
`340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`; the current refactor branch HEAD
is Git-authoritative; ahead/behind versus `main` is 147/0 and fast-forward is
mechanically possible. The accepted disposition is
`BRANCH_PUBLICATION_COMPLETE_NO_MAIN_ACTION_REQUIRED`.

`TECHNICAL_COMPLETION_REQUIRES_DEPLOYMENT = NO`

`FINAL_PROJECT_CLOSEOUT_RECORD_REQUIRED` is satisfied by this documentation
unit only after independent acceptance and publication. This candidate does
not claim its own publication.

## REMOVE-NORMA-DOMAIN-1 — ACCEPTED / LANDED

Final independent review verdict: `REMOVE_NORMA_DOMAIN_ACCEPTED`.

Logical implementation commit: `3cd804d8734d0d7f94def1b7ed5eda336ae54f4b`
(parent `2cb1db7e68fddb1f68b0b0a3b24b06bb919d6e7c`, subject `Remove Norma domain while preserving activity versioning`).

Schema transition: prod-1 `user_version` 1 -> 2; migration marker `remove_norma_domain`
recorded in `schema_migrations` (version 2, applied during controlled cutover startup).

The active database was migrated through the accepted real application path
(`bootstrap_prod1_schema` -> `migrate_prod1_v1_to_v2`) during a controlled application
start; no ad-hoc migration SQL was used. Post-migration active DB validation:
`integrity_check` ok, `foreign_key_check` zero rows, 27 `atividade_base` preserved,
27 `atividade_versao` preserved (IDs, `numero_versao`, `eixo` and matrix row preserved
byte-for-byte against the clean v1 backup), matrix row preserved. Live counts:
`requisicoes` 0, `turmas` 0, `matriz_atividade_versao_item` 0.

Removed physical structures confirmed absent from the active v2 DB: `norma_atividade`,
`matriz_norma`, `atividade_versao.norma_id`, `atividade_versao.codigo_normativo`,
`requisicoes.codigo_normativo_snapshot`. No fake/sentinel Norma replacement exists.
Removed Norma routes are absent (404). `atividade_versao` remains the canonical version
authority; `matriz_atividade_versao_item` remains the exact matrix->version authority;
immutable `regra_snapshot_json` remains the historical authority.

Final accepted suite: 1271 passed, 136 skipped, 0 failed (independent review evidence;
no canonical rerun during landing by design).

Backup custody (external): `C:\Users\klebe\AppData\Local\Temp\SGAA-PROD1-V1-BACKUP-20260829-141215\`
- raw bundle: `database.db` SHA-256 `84E4891FD9A3BBE320880439C216E983DD8433B74433EDDD394AF123E31935E2` (421888 bytes); WAL was 0 bytes and SHM was removed by SQLite clean-close before copy, so the main DB file is the complete v1 state.
- clean v1 backup: `database-v1-clean.db` SHA-256 `84E4891FD9A3BBE320880439C216E983DD8433B74433EDDD394AF123E31935E2`; independently validated `user_version=1`, `integrity_check` ok, `foreign_key_check` zero, counts 27/27/1/0/0.

Runtime smoke (real application, live HTTP, admin login): login/admin shell, Matrizes list,
existing matrix open, matrix form without "Normas aplicaveis", AAC list, AEU list, activity
catalogue ("Versoes das atividades"), version detail, exact-version management page all
PASS; removed Norma routes 404; no SQL error referencing removed tables/columns.
Second-start idempotence: `user_version` stayed 2, no migration rerun, counts unchanged.

Active v2 DB post-cutover: SHA-256 `E65BC2C924FD2DC70D5A7BF3FD1BD9F72B92753208B0298509C0B598119FD28B`, `user_version` 2.

`run.bat` / `run2.bat` residue remains pre-existing and unrelated (unstaged, unmodified
by this landing). `AGENT_HANDOFF.md` remains frozen and unchanged.

## REMOVE-MATRIX-VERSION-METADATA-1 — ACCEPTED / LANDED

Independent final verdict: `REMOVE_MATRIX_VERSION_ACCEPTED`.

Logical implementation commit: `5be2829fea1fd9041685ac22cea9ad7c48f8824a`
(parent `e74baa5955b6616567410ce332458e54773482d6`).

Schema transition: prod-1 `user_version` 2 -> 3; migration marker
`remove_matrix_version_metadata` recorded in `schema_migrations` (version 3).
The active database was migrated through the accepted normal application startup
path; no ad-hoc migration SQL was used.

Post-migration validation: `integrity_check` ok, `foreign_key_check` zero rows,
live counts unchanged at 1 matrix / 0 turmas / 0 requisicoes /
0 matriz_atividade_versao_item. Matrix ID 1, `curso_id`, name, description,
status, validity, AAC/AEU hour requirements and `created_at` were preserved.
`matrizes_atividades.versao` and `matrizes_atividades.matriz_origem_id` were
removed. Matrix ID remains canonical identity; `turma.matriz_id`,
`atividade_versao` (including `numero_versao` and `versao_anterior_id`),
`matriz_atividade_versao_item` and `regra_snapshot_json` remain protected
authorities.

Raw v2 backup custody: `C:\Users\klebe\AppData\Local\Temp\SGAA-PROD1-V2-BACKUP-20260829-173806679\`
(`database.db` SHA-256
`E65BC2C924FD2DC70D5A7BF3FD1BD9F72B92753208B0298509C0B598119FD28B`).
Clean v2 rollback backup: `database-v2-clean.db`, same SHA-256, independently
validated at `user_version=2`, `integrity_check` ok, `foreign_key_check` zero,
and unchanged counts.

Real application/admin-login smoke passed for the admin shell, Matrizes list,
existing matrix, matrix form/list removal of Versao metadata, AAC, AEU,
activity-version catalog/detail, exact matrix activity-version management,
legacy `versao` query parameters, and absent Norma UI. Second-start
idempotence passed: v3, three markers and business counts remained unchanged.

Accepted suite: 1287 passed, 136 skipped, 0 failed. Active v3 database final
SHA-256 `19548FB631017436CB8E1E6226875EFA2D6D18415DAE83731A278EC322F99997`,
`user_version=3`.

`run.bat` / `run2.bat` remain pre-existing unrelated residue. `AGENT_HANDOFF.md`
remains frozen and unchanged.

## LAUNCHER-RESIDUE-CLOSEOUT-1 — LANDED

`run.bat` / `run2.bat` long-lived dirty residue resolved.

- `run.bat` remains the canonical configurable Windows/dev launcher
  (APP_HOST/APP_PORT overridable, venv preferred with PATH fallback,
  browser auto-opens `/login`).
- `run2.bat` retained as the strict manual deterministic launcher
  (fixed 127.0.0.1:5000, venv required, no browser auto-open).
- Occupied-port error visibility hardened with `pause` before `exit /b 1`
  in both launchers.
- Foreground PowerShell invocation now uses
  `-NoProfile -NonInteractive -NoExit` in both launchers.
- Bounded launcher validation passed: PowerShell flag combo (command runs,
  `-NoExit` keeps shell alive), `pause` interactive wait and non-interactive
  EOF return, occupied-port branch on both launchers (offender PID/CMD
  shown, exit 1, no second instance), run.bat bounded startup + `/login`
  HTTP 200 on alternate port with clean tree termination; real prod-1
  instance untouched and healthy throughout.
- Logical launcher commit: `801d619345f71575900701961c1a9bc07262d2f7`.
- Known `run.bat` / `run2.bat` residue is now resolved; tracked worktree
  expected clean except ignored authorized artifacts.

`AGENT_HANDOFF.md` remains frozen and unchanged.
