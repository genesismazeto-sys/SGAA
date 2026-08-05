# PHASE 4-B7-P — Arquivos/Alertas neutral shared-owner contract

Date: 2026-08-04
Status: **IMPLEMENTED / AWAITING SUPERVISOR REVIEW**. Not yet committed or
published at the time this document was written; freeze, independent review,
commit and push follow this document within the same authorized phase.

## Status and authority

PHASE 4-B6: **CLOSED / ACCEPTED**.
PHASE 4-B7-A: **DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE_REQUIRED**
(accepted).
PHASE 4-B7-P: **IMPLEMENTED / AWAITING SUPERVISOR REVIEW**.
PHASE 4-B7 (Arquivos/Alertas/Reportes blueprint route extraction): **NOT
AUTHORIZED**. PHASE 4 remains **OPEN / INCREMENTAL IMPLEMENTATION** and is not
closed. Phase 5 and Phase 6 are **NOT AUTHORIZED**. Migration v4 is
**PROHIBITED**. The authorized technical/governance subject is `Extract B7
shared neutral owners`; required parent `b6d6e2295e2beeba046cfe1f4c1614f667261ad2`
(`Record acceptance of Phase 4-B6`).

This unit is only the neutral shared-owner prerequisite for a future Arquivos/
Alertas/Reportes cohort. **B7 route/blueprint extraction is NOT AUTHORIZED and
no route moved.** `app/views/admin/arquivos_alertas_reportes.py` remains
absent.

## B7-A diagnosis (accepted, read-only)

The B7-A diagnosis inventoried the Arquivos/Alertas/Reportes cohort:
12 endpoints / 13 route-method pairs (5 Arquivos, 4 Alertas, 3 Reportes). RBAC
is already fully mapped centrally in `app/auth.py::get_admin_permission_requirement`
(endpoint-name keyed, module-location-agnostic). Reportes has **zero**
shared-owner debt: `ensure_reportes_table` has been `app.db_maintenance`-owned
since Phase 3-B1, and `REPORTE_CATEGORY_OPTIONS` is already `app.reporting`-owned;
neither is touched by B7-P. Arquivos and Alertas share exactly four symbols
consumed outside the cohort: `ensure_admin_arquivos_table`, `get_admin_arquivo`,
`ensure_admin_alertas_table`, `list_active_admin_alertas` — consumed by the
already-extracted `app/views/aluno.py` blueprint through a test-frozen lazy
`main` bridge, and by `main.uploaded_file` (`/uploads/<path:filename>`) and
`main.admin_dashboard` directly (both out of scope, remain main-local).
Classification: **SHARED_OWNER_PREREQUISITE_REQUIRED**. No canonical database
was opened or queried during diagnosis.

## Canonical owners — exact 2/1/1 partition

- `app.db_maintenance` (pre-existing neutral schema-maintenance owner, already
  owning `ensure_reportes_table`) additionally owns:
  - `ensure_admin_arquivos_table`
  - `ensure_admin_alertas_table`
- `app.admin_files` (**new**) owns:
  - `get_admin_arquivo`
- `app.admin_alerts` (**new**) owns:
  - `list_active_admin_alertas`

Dependency direction: `app.admin_files -> app.db_maintenance.ensure_admin_arquivos_table`;
`app.admin_alerts -> app.db_maintenance.ensure_admin_alertas_table`. Neither
new neutral module imports `main`. `app.db_maintenance` continues to have zero
dependency on `main`.

## `main.py` contract

All four local function bodies were removed from `main.py`. `main.py` imports
and identity-re-exports all four canonical symbols via ordinary
`from app.db_maintenance import (ensure_admin_alertas_table,
ensure_admin_arquivos_table, ...)`, `from app.admin_files import
get_admin_arquivo`, and `from app.admin_alerts import list_active_admin_alertas`
statements — no wrapper, no duplicate body, no local forwarding function, no
dynamic import, no `sys.modules` bridge. `main.uploaded_file` and
`main.admin_dashboard` continue resolving the canonical imported identities
unchanged.

## `app/views/aluno.py` contract

The three B7-relevant consumers (`ensure_admin_arquivos_table` in
`aluno_arquivos`; `get_admin_arquivo` in `aluno_visualizar_arquivo` and
`aluno_baixar_arquivo`; `list_active_admin_alertas` in `aluno_dashboard`) now
resolve module-level direct imports from the three neutral owners instead of
the lazy `main` bridge. `_get_main_helpers()` is reduced from 5 keys to exactly
2: `get_student_request_update_alert`, `mark_student_request_updates_seen`
(both Requisições-domain, explicitly out of scope for B7, untouched).

## Body equivalence

All four moved bodies (and their argument signatures) are AST-equivalent to
entry baseline `b6d6e2295e2beeba046cfe1f4c1614f667261ad2:main.py`, verified by
`ast.dump` comparison in
`tests/test_phase4_arquivos_alertas_shared_owners.py::test_b7p_body_equivalence_against_entry_baseline`.
No SQL, index, transaction, schema, or return-shape change. For
`get_admin_arquivo`/`list_active_admin_alertas`, only name resolution of the
`ensure_*` dependency changed, through a normal import — the call expressions
themselves are byte-identical source.

## Zero route movement

All 12 Arquivos/Alertas/Reportes route handlers (`admin_arquivos`,
`admin_adicionar_arquivo`, `admin_editar_arquivo`, `admin_visualizar_arquivo`,
`admin_deletar_arquivo`, `admin_reportes`, `admin_reportes_atualizar_status`,
`admin_reportes_deletar`, `admin_alertas`, `admin_salvar_alerta`,
`admin_alternar_alerta`, `admin_deletar_alerta`) remain main-local,
byte/AST unchanged from entry baseline.

## Pre-existing residual debt (recorded, not repaired in B7-P)

- `_best_effort_remove_admin_arquivo_file` (main-local, untouched) deletes via
  `os.path.normpath(os.path.join(upload_root, rel_path))` + `os.path.isfile`,
  without the `startswith(base)` containment check `uploaded_file` uses.
  Low-risk because `rel_path` always originates from server-generated
  filenames via `save_upload`, never raw user input. Not touched in this
  phase; mixing security cleanup with the ownership prerequisite is explicitly
  out of scope.
- The `sgaa_canonical_db_guard` phantom governance debt (referenced only in
  documentary evidence labels across `PROJECT_STATE.md`/`AGENT_HANDOFF.md`/the
  refactor docs; no physical module exists) is neither invoked nor created in
  this phase. `CANONICAL_SQLITE_OPENS=0` is not claimed as measured evidence
  from it; physical database custody (size/SHA-256/sidecar presence) is used
  instead.

## TDD chronology

- **RED** — new `tests/test_phase4_arquivos_alertas_shared_owners.py`,
  11 collected: **7 failed / 4 passed**, exit 1, captured before any
  production mutation. All seven failures attributable solely to the
  not-yet-implemented prerequisite (owner modules absent; `main` still owned
  the four bodies; `aluno` still had the 5-key lazy map). The four passes were
  pre-true invariants (zero route movement, `uploaded_file`/`admin_dashboard`/
  Reportes unchanged).
- **GREEN** — same file, 11 passed, exit 0, after implementation.

## PHASE 4-B7-P-R2 — scope-expansion correction (supervisor-authorized in session)

The full default suite exposed two additional frozen assertions of the
identical pre-B7-P 5-key aluno lazy map, outside the originally named
13-path pool:

- `tests/test_db_schema_maintenance.py::EXPECTED_ALUNO_LAZY_KEYS_AFTER_VERSIONING_EXTRACTION`
  (historical residue from the B2 versioning-subsystem extraction), asserted
  by `test_usuario_profile_helper_owner_exports_and_direct_consumers`.
- `tests/test_phase4_versioning_subsystem.py::REMAINING_ALUNO_MAIN_HELPERS`,
  asserted by `test_aluno_direct_imports_and_exact_remaining_lazy_main_dependencies`.

Neither file references arquivos/alertas beyond this one shared constant, and
neither was flagged by the B7-A diagnosis. Classification:
`PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED /
ALUNO_LAZY_MAP_INVARIANT_RECONCILIATION / NO_RETROACTIVE_GENERIC_AUTHORITY`.
The supervisor explicitly authorized adding both to the mutable pool via
in-session confirmation; both received the identical one-for-one 5-key → 2-key
correction and no other change.

## PHASE 4-B7-P-R2 — pre-existing environmental failure waiver (supervisor-authorized in session)

Full default suite result: **1103 passed / 3 failed / 17 deselected**,
329.53s, exit 1. **This is NOT reported as GREEN and NOT reported as 0
failed.** The exact three failing node IDs:

1. `tests/test_phase3_final_init_cutover.py::test_seed_tool_uses_factory_owner_without_main_and_is_idempotent`
   — `AssertionError: assert 0 == 2` on a mis-decoded
   `"Seed demo concluído."` subprocess stdout string.
2. `tests/test_pytest_runtime_isolation.py::TestSubprocessImportMain::test_import_main_uses_runtime_root`
   — `SyntaxError: Non-UTF-8 code starting with '\xe7' ... but no encoding
   declared` on a generated temp `.py` file.
3. `tests/test_pytest_runtime_isolation.py::TestMainNoOverwrite::test_import_main_preserves_upload_folder`
   — identical `SyntaxError` root cause as #2.

These three were independently reproduced with **identical failure
fingerprints** on a disposable `git worktree` checkout of the unmodified entry
baseline `b6d6e2295e2beeba046cfe1f4c1614f667261ad2`, under the same
interpreter, before any B7-P code existed in that worktree. The worktree was
removed after verification; no residual. Grep of both failing files for
`arquivo`/`alerta` confirms zero reference to `admin_arquivos`/`admin_alertas`
or any of the four B7-P symbols. Root cause is a Windows console/subprocess
temp-file UTF-8 encoding defect, unrelated to arquivos/alertas.

Classification: `PRE_EXISTING_BASELINE_REPRODUCED /
ENVIRONMENTAL_ENCODING_FAILURE / UNRELATED_TO_B7_P /
ACCEPTED_NONBLOCKING_RESIDUAL / NO_RETROACTIVE_GREEN_CLAIM`. Neither failing
test file was modified by B7-P and neither is added to the mutable pool; that
environmental debt remains separate, unrepaired, out of scope.

## B7-P-specific/affected focused gates — all GREEN

- Targeted lane: `tests/test_phase4_arquivos_alertas_shared_owners.py` +
  `tests/test_phase4_requisicoes_shared_owners.py` +
  `tests/test_residual_shared_helpers.py` + `tests/test_admin_arquivos.py` +
  `tests/test_admin_reportes.py` + `tests/test_admin_aux_sections.py` +
  `tests/test_csrf_inventory_audit.py`: **69 passed, 0 failed, 0 errors,
  19.97s, exit 0**.
- Global-invariant lane: `tests/test_route_inventory_snapshot.py` +
  `tests/test_rbac_requirement_coverage.py` +
  `tests/test_ref_0c_d_r1_route_complete_actor_matrix.py`: **36 passed, 0
  failed, 0 errors, 29.72s, exit 0**.

## Global invariants (unchanged)

- Routes 131; endpoints 130; business route-method pairs 160 (measured via
  `main.app.url_map`).
- RBAC unmapped 0: `tests/_artifacts/rbac_unmapped_routes_baseline.json`
  byte-identical, zero `git diff`.
- Route inventory byte-identical: `tests/_artifacts/route_inventory_baseline.json`
  zero `git diff`.
- Message catalog 536 (measured directly via `utils.messages._message_catalog()`).
- No template/static/JS delta; no schema/semantic delta.

## Physical database custody

- Canonical `database.db` before the full suite: 544768 bytes, SHA-256
  `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`; WAL/SHM/
  journal absent.
- Canonical `database.db` after the full suite: 544768 bytes, SHA-256
  `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`; WAL/SHM/
  journal absent. **Unchanged.**

## Agent routing disclosure

The order specified IAsup `openai-codex/gpt-5.6-sol` and IAexec DeepSeek V4
Flash (FREE-first, explicit fallback to normal on failure). This session's
harness has no router tool capable of invoking that provider. All diagnosis
and implementation were performed directly by the acting Claude Code session.
This deviation is disclosed rather than silently substituted; no escalation to
a Pro/Luna/GPT tier occurred.

## Exact mutable manifest

Production (5): `app/db_maintenance.py`, `app/admin_files.py` (**new**),
`app/admin_alerts.py` (**new**), `app/views/aluno.py`, `main.py`.

Tests (4): `tests/test_phase4_arquivos_alertas_shared_owners.py` (**new**),
`tests/test_phase4_requisicoes_shared_owners.py` (one frozen-assertion
correction), `tests/test_db_schema_maintenance.py` (R2 supplemental,
one frozen-assertion correction), `tests/test_phase4_versioning_subsystem.py`
(R2 supplemental, one frozen-assertion correction).

Governance (6): `PROJECT_STATE.md`, `AGENT_HANDOFF.md`,
`docs/DOCUMENTATION_INDEX.md`, `docs/mapeamento/05_avaliacao_refactor.md`,
`docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`,
`docs/refactor/PHASE4_ARQUIVOS_ALERTAS_SHARED_OWNER_CONTRACT.md` (**new**,
this document).

**Exact total: 15 paths. Path 16 is a hard stop absent further authorization.**

Read-only gates (unchanged, not part of the mutable pool):
`tests/test_residual_shared_helpers.py`, `tests/test_admin_arquivos.py`,
`tests/test_admin_reportes.py`, `tests/test_admin_aux_sections.py`,
`tests/test_csrf_inventory_audit.py`.

## Next exact action

Freeze the candidate, run independent review (disclosed as not invocable via
the ordered router in this harness), commit as `Extract B7 shared neutral
owners` with required parent `b6d6e2295e2beeba046cfe1f4c1614f667261ad2`,
verify the race gate, and push by normal fast-forward only.
**PHASE 4-B7 (route/blueprint extraction) remains NOT AUTHORIZED by this
phase.**
