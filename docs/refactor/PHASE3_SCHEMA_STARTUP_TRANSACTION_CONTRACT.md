# Phase 3 schema, startup, and transaction contract

**Status:** PHASE 3-B11 final single-init revision of the accepted PHASE 3-B5/B6/B7/B8/B9/B10 contract; B11-R1 governance closeout implemented / awaiting supervisor review
**Phase status:** B5 through B10-R1 CLOSED / ACCEPTED; B11 technical artifact COMMITTED AND PUSHED / POST-COMMIT VERIFIED at `c9009bf3d68950ad4e0499b65928603e84bee341`; Phase 3 not formally closed until B11-R1 supervisor acceptance
**B11 identity:** `c9009bf3d68950ad4e0499b65928603e84bee341` (`Unify database initialization ownership`), parent `e63e1a66b9d2ebad7253a0efd2e0a367b89b8b8a` (`Correct B10 governance manifest record`)
**Executable contract:** `tests/test_phase3_schema_startup_transaction_contract.py`

## 1. Scope and purpose

This document defines the final Phase 3 single-initializer contract. B11 moves the
complete bootstrap body to `app.db.init_db`, removes `app.db._init_db_impl`, removes
`main.init_db` as a defining function, and preserves `main.init_db` only as the
object-identical compatibility import of the canonical owner. The former two-entry
lazy bridge is removed completely: `app.db` has no import, lookup, callback, or other
runtime dependency on `main`.

B11 directly owns application settings, cloud backup schema, turma/matrix schema,
preferred-matrix selection, and its module-local logger. It explicitly binds the
active Flask app into the historical backup-settings runtime owner before connection
acquisition. B8 leaf ownership, B9 migration v2, B10 migration v3, route/RBAC/API/UI
behavior, restore order, seed behavior, and migration registry remain unchanged.
This revision records exact transaction postconditions rather than imposing a false
whole-bootstrap rollback contract over independently durable historical units.

## 2. Current connection authority

| Concern | Current contract |
|---|---|
| `DATABASE` | Sole defining owner: `app/db.py`; resolved as `os.environ.get("APP_DATABASE", os.path.join(PROJECT_ROOT, "database.db"))`. |
| `get_db_connection` | Sole defining owner: `app/db.py`; stores one connection in Flask `g.db` and reuses it for the application context. |
| `close_db_connection` | Sole defining owner: `app/db.py`; pops `g.db` and closes it. `create_app` registers this exact object once with `teardown_appcontext`. |
| Main compatibility | `main.py` imports `DATABASE`, `get_db_connection`, and `close_db_connection`; the exported objects are identical to the `app.db` owners. Compatibility is not defining ownership. |
| Row and collation | New connections use `sqlite3.Row` and register `PTBR_NOACCENT`. |
| PRAGMAs | Every newly created connection executes `foreign_keys = ON`, `journal_mode = WAL`, and `synchronous = NORMAL`, in that order. |
| Reverse dependency | There is no sync shim and no `app.db` import or lazy lookup of `main`. |

The application factory creates/configures the Flask app and registers the close
lifecycle. It does not call `init_db`. Module-level `main.app` is created with
`create_app(...)`; development bootstrap happens separately in the `__main__` block.

## 3. Final single-init ownership

| Export | Defining owner | Direct caller | Context and transaction contract |
|---|---|---|---|
| `app.db.init_db` | `app/db.py` | `tools/seed_demo_data.py::seed` plus all compatibility callers below | Requires an active Flask application context, binds backup runtime settings, obtains the canonical connection, runs the complete bootstrap, and performs one final `conn.commit()`. |
| `main.init_db` | `app/db.py` | Development startup, restore, tools, and tests below | `main.py` imports the canonical function; `main.init_db is app.db.init_db`. It has no independent body or transaction ownership. |

`app.db.init_db` is the only defining initializer. `_init_db_impl`,
`_get_main_db_helpers`, `_sync_database_from_main`, the main-defined initializer,
and every lazy bridge entry are absent. Compatibility call sites keep their
historical spelling without retaining duplicate ownership.

## 4. Final caller inventory

The executable manifest identifies qualified call expressions by tracked/intended
path, lexical scope, exact expression, imported binding and canonical runtime owner,
rather than by brittle line number. The corrected qualified lexical inventory is
exactly **72** `main.init_db(...)` expressions and **5** `app_db.init_db(...)`
expressions. Every one resolves to canonical runtime owner `app.db.init_db`.
There are no calls to `_init_db_impl` because that symbol no longer exists.

Three additional bare `init_db(...)` expressions are tracked separately because
their exact imported binding is `from app.db import init_db`: development startup
and restore in `main.py`, plus `tools/seed_demo_data.py::seed`. They prove startup,
restore and factory/seed ownership but are not members of the qualified 72/5 count.

### Startup and restore callers

| Category | Exact caller | Flask context | Commit expectation |
|---|---|---|---|
| Development startup | `main.py::<module>` under `if __name__ == "__main__"` | Explicit `with app.app_context()` | `main.init_db` commits before `app.run`. |
| Restore bootstrap | `main.py::_restore_database_from_source` | Inherited request/app context from the two admin POST routes | Restore completes first; `main.init_db` commits schema reconciliation before snapshot sync/retention/upload continuation. |
| Restore route 1 | `main.py::admin_banco_dados_restaurar` | Flask request context | Calls `_restore_database_from_source`, not `init_db` directly. |
| Restore route 2 | `main.py::admin_banco_dados_restaurar_upload` | Flask request context | Calls `_restore_database_from_source`, not `init_db` directly. |
| Restore physical function | `app.db_maintenance.restore_database_snapshot` | Called by `_restore_database_from_source` | Replaces the configured target before the subsequent `main.init_db`; it is not an `init_db` implementation. |
| Seed | `tools/seed_demo_data.py::seed` | Explicit `with app.app_context()` | `app.db.init_db` commits bootstrap; the seed then obtains the connection and separately commits seed DML. |

### Tool callers of `main.init_db`

- `tools/smoke_test.py::<module>`
- `tools/smoke_test_admin.py::<module>`
- `tools/smoke_test_rbac_permissions.py::run`

Each tool wraps the call in an explicit application context and relies on the
callee's final commit.

### Test and fixture callers of `main.init_db`

The following is the exact frozen `(path -> lexical scopes)` manifest. Repeated
scope names represent distinct call expressions and are intentional.

- `tests/test_activity_versioning_phase_b_schema.py` ->
  `test_phase_b_schema_creates_additive_tables_and_columns`,
  `test_phase_b_allows_normas_and_versions_with_constraints`,
  `test_phase_b_requires_justification_for_aac_para_aeu_transition`,
  `test_phase_b_keeps_legacy_requisicoes_flow_and_nullable_snapshot_fields`,
  `test_phase_b1_validation_fails_when_same_base_has_active_aac_and_aeu_without_transition`,
  `test_phase_b1_validation_passes_with_valid_aac_para_aeu_transition`,
  `test_phase_b1_validation_passes_for_new_aeu_base_without_aac_history`,
  `test_phase_b1_validation_passes_for_two_aac_versions_in_same_base`,
  `test_phase_b1_validation_fails_for_cross_base_aac_para_aeu_transition`,
  `test_phase_b1_rejects_invalid_transition_type`,
  `test_phase_b1_rejects_duplicate_matriz_norma`,
  `test_phase_b1_rejects_duplicate_matriz_atividade_versao_item`,
  `test_phase_b_init_db_works_on_existing_legacy_database`
- `tests/test_activity_versioning_phase_d1_diagnostic.py` -> `isolated_legacy_client`
- `tests/test_activity_versioning_phase_d5_structured_hours.py` -> `isolated_legacy_client`
- `tests/test_activity_versioning_resolver.py` -> `isolated_legacy_client`
- `tests/test_admin_activity_version_catalog_create.py` -> `client`
- `tests/test_admin_activity_version_catalog_readonly.py` -> `client`
- `tests/test_admin_activity_version_catalog_version_activate.py` -> `client`
- `tests/test_admin_activity_version_catalog_version_edit.py` -> `client`
- `tests/test_admin_activity_version_catalog_version_form.py` -> `client`
- `tests/test_admin_add_aluno_csrf.py` -> `isolated_client_csrf`
- `tests/test_admin_arquivos.py` -> `client`
- `tests/test_admin_atividade_delete.py` -> `client`
- `tests/test_admin_atividade_description.py` -> `client`
- `tests/test_admin_atividades_filters.py` -> `client`
- `tests/test_admin_atividades_import.py` -> `client`
- `tests/test_admin_aux_sections.py` -> `client`
- `tests/test_admin_dashboard_request_alert.py` -> `client`
- `tests/test_admin_database_backups.py` -> `admin_client`,
  `test_database_module_requires_explicit_permission_for_consultivo_admin`
- `tests/test_admin_matrizes.py` -> `client`
- `tests/test_admin_matrizes_csrf_ui.py` -> `client`
- `tests/test_admin_messages.py` -> `client`
- `tests/test_admin_reportes.py` -> `client`
- `tests/test_admin_requisicao_api_scope.py` -> `client`
- `tests/test_admin_requisicao_create.py` -> `client`
- `tests/test_admin_requisicao_list_scope.py` -> `client`
- `tests/test_admin_requisicao_matrix_scope.py` -> `client`
- `tests/test_admin_requisicao_process_ui.py` -> `client`
- `tests/test_admin_snapshot_diagnostics.py` -> `client`
- `tests/test_admin_toolbar_filters.py` -> `client`
- `tests/test_admin_turmas_matriz.py` -> `client`
- `tests/test_admin_version_visibility_ui.py` -> `client`
- `tests/test_aluno_matrix_scope.py` -> `client`, `isolated_dashboard_client`
- `tests/test_aluno_progresso.py` -> `client`
- `tests/test_aluno_requisicao_update_alert.py` -> `client`
- `tests/test_aluno_toolbar_filters.py` -> `client`
- `tests/test_app_basic.py` -> `client`
- `tests/test_csrf_admin_flows.py` -> `isolated_client_csrf`
- `tests/test_csrf_e2e_critical_flows.py` -> `isolated_client_e2e`
- `tests/test_csrf_inventory_audit.py` -> `_setup_isolated_csrf_clients`
- `tests/test_db_schema_maintenance.py` -> `test_init_db_registers_schema_version`
- `tests/test_atividades_schema_migration_v2.py` -> `_run_init_on_temp_database`
- `tests/test_filter_schema_contract.py` -> `client`
- `tests/test_pagination.py` -> `setup_module`
- `tests/test_phase_0_smoke_flows.py` -> `smoke_env`
- `tests/test_release_admin_actions.py` -> `isolated_client`
- `tests/test_release_admin_actions_csrf.py` -> `isolated_client_csrf`
- `tests/test_release_admin_crud.py` -> `isolated_client`
- `tests/test_release_backend_core.py` -> `isolated_client`, `isolated_client_csrf`
- `tests/test_release_backup_restore_local.py` -> `test_release_backup_restore_local_isolated`
- `tests/test_release_clean_database.py` ->
  `test_release_clean_database_installation_and_idempotence` twice
- `tests/test_release_requisicoes_flow.py` -> `isolated_client`
- `tests/test_security.py` -> `client`
- `tests/versioned_test_support.py` -> `isolated_versioned_app_env`

Every test/fixture call above is lexically inside an explicit application
context. Pytest routes `APP_DATABASE` to a session-owned external runtime root
before collection. Release restore/clean tests additionally bind all effective
database paths to `tmp_path` and fingerprint repository databases.

### Qualified direct-owner call expressions

- `tests/test_atividades_schema_migration_v2.py::_run_init_on_temp_database` ->
  `app_db.init_db`, imported by `from app import db as app_db`
- `tests/test_phase3_final_init_cutover.py` -> `app_db.init_db`, imported by
  `from app import db as app_db`, in these four lexical scopes:
  `test_bootstrap_failure_postconditions_match_each_accepted_transaction_owner`,
  `test_early_migration_commit_survives_later_bootstrap_failure_without_partial_bootstrap`,
  `test_failure_inside_early_migration_rolls_back_only_the_isolated_unit`, and
  `test_failure_after_successful_early_migration_preserves_only_committed_versions`

All five have canonical runtime owner `app.db.init_db`. The 72 compatibility
expressions listed above have exact expression `main.init_db`, binding `main`, and
the same canonical runtime owner through the independently tested object identity.

## 5. app.db bootstrap sequence

The following is the exact semantic order of the sole `app.db.init_db`; nested
SQL details are grouped without changing order:

1. Bind the active Flask application with `bind_backup_settings_runtime_app(current_app._get_current_object())`.
2. Obtain `conn` from `get_db_connection`.
3. Call direct `apply_early_schema_migrations(conn, logger=logger)`.
4. Create `usuarios`; best-effort email index.
5. Call direct `ensure_usuario_access_schema`.
6. Call direct `ensure_usuario_profile_schema`.
7. Call direct `ensure_app_settings_schema`.
8. Call direct `ensure_backup_settings_schema`.
9. Call direct `ensure_cloud_backup_schema`.
10. Create `alunos`; best-effort indexes.
11. Create `turmas`; best-effort status index.
12. Create canonical eleven-column `atividades`.
13. Create `requisicoes`.
14. Create `requisicao_arquivos`; best-effort requisition/file indexes.
15. Call direct `ensure_reportes_table`.
16. Read bootstrap-admin settings and conditionally insert the admin.
17. Conditionally add `alunos.turma_id` plus index.
18. Conditionally add `alunos.foto_perfil`.
19. Conditionally add `requisicoes.nome_evento`.
20. Conditionally add `requisicoes.aluno_update_notified_at`.
21. Conditionally add `requisicoes.aluno_update_seen_at`.
22. Best-effort create `idx_reqs_aluno_update_pending`.
23. Call direct `ensure_requisicao_alert_receipts_table`.
24. Conditionally add `turmas.numero`.
25. Create `cursos` with AAC/AEU totals.
26. Conditionally add `cursos.periodo`, `total_horas_aac`, and
    `total_horas_aeu`; normalize invalid/null totals.
27. Seed `GERAL` only when no course exists.
28. Call direct `ensure_turmas_matriz_schema`.
29. Call direct `ensure_matriz_atividade_links_table`.
30. Call direct `ensure_atividade_versioning_schema`.
31. Attempt the five `turmas` additions, in order: `curso_id`, `ano_inicio`,
    `semestre_inicio`, `codigo`, `matriz_id`.
32. Conditionally add `ano_fim`, then `semestre_fim`.
33. Create course/matrix indexes and best-effort unique turma indexes.
34. Reconcile old turmas: assign `GERAL`, sequential numbers, and generated
    codes with collision fallback.
35. Reconcile missing `turmas.matriz_id` through direct
    `get_preferred_matriz_for_curso`.
36. Call unrestricted `apply_schema_migrations(conn, logger=logger)`.
37. Execute the one expected final `conn.commit()`.

The matrix order is mandatory: matrices before links, links before activity
versioning. Migration metadata is mandatory before the final commit.

The logger is `logging.getLogger(__name__)` in `app.db`; it has no local handler
and no dependency on `main.logger`. Logger-dependent paths are the caught failures for:
`alunos.turma_id`, `alunos.foto_perfil`, `requisicoes.nome_evento`, both
requisition alert timestamps, the pending-alert index, `turmas.numero`,
`turmas.ano_fim`, `turmas.semestre_fim`, old turma course/code reconciliation,
and old turma matrix reconciliation. These warnings do not replace transaction
or schema verification.

## 6. Schema-owner matrix

| Function or metadata | Defining owner | Frozen classification |
|---|---|---|
| `init_db` in `app.db` | `app/db.py` | Sole defining bootstrap owner and owner of the one final bootstrap commit. |
| `init_db` export in `main` | `app.db.init_db` object | Compatibility import only; object-identical and without a local function body. |
| `_init_db_impl` | Retired by B11 | Former delegated bootstrap body; symbol and callers removed. |
| `ensure_reportes_table` | `app/db_maintenance.py` | Accepted direct schema owner. `main` compatibility export only. |
| `ensure_usuario_profile_schema` | `app/db_maintenance.py` | Accepted direct schema owner. `main` compatibility export only. |
| `ensure_requisicao_alert_receipts_table` | `app/db_maintenance.py` | Accepted direct schema owner. `main` compatibility export only. |
| `ensure_matrizes_atividades_table` | `app/db_maintenance.py` | Accepted direct schema owner. `main` and `app.db` compatibility exports. |
| `ensure_matriz_atividade_links_table` | `app/db_maintenance.py` | Accepted direct schema owner; delegates matrix-table ensure. `main` and `app.db` compatibility exports. |
| `ensure_schema_migrations_table`, `_migration_v1_baseline`, `_migration_v2_normalize_atividades_schema`, `apply_schema_migrations`, `apply_early_schema_migrations`, `SCHEMA_VERSION`, `SCHEMA_MIGRATIONS` | `app/db_maintenance.py` | Sole versioned migration owner. The early runner alone owns the isolated pre-bootstrap transaction. |
| `ensure_usuario_access_structural_schema` | `app/db_maintenance.py` | Pure access DDL owner; no default-data, normalization, savepoint, commit, or rollback. |
| `seed_usuario_access_default_data` | `app/db_maintenance.py` | Historical five-row `INSERT OR IGNORE` owner; reuses `app.auth.DEFAULT_ACCESS_PASSWORDS`; no DDL. |
| `normalize_usuario_access_startup_data` | `app/db_maintenance.py` | Startup-wide accepted access normalization owner; reuses `app.auth.default_access_level_for_user_type`; no DDL. |
| `ensure_usuario_access_schema` | `app/db_maintenance.py` | Public compatibility orchestrator and sole owner of the access savepoint. `main` and `app.db` are direct compatibility exports. |
| `ensure_backup_settings_structural_schema` | `app/db_maintenance.py` | Pure owner of `configuracoes_backup` CREATE TABLE; no Flask config, DML, read/merge, transaction control, directory or external effect. |
| `bind_backup_settings_runtime_app`, `_backup_settings_defaults`, `seed_backup_settings_default_data`, `normalize_legacy_backup_sync_interval`, `read_backup_settings`, `_apply_backup_settings_to_app`, `get_backup_settings`, `ensure_backup_settings_schema` | `app/backup_settings.py` | Sole owners of the explicit runtime-app binding and backup-settings layers. Canonical init rebinds the active Flask app before obtaining the connection; the historical module-level main binding remains for non-init compatibility consumers. |
| `ensure_app_settings_schema` | `app/db.py` | Direct application-settings schema/default owner in the canonical bootstrap. |
| `ensure_cloud_backup_schema` | `app/db.py` | Direct owner of `cloud_accounts`, `backup_logs`, and `cloud_drive_settings` in the canonical bootstrap. |
| `ATIVIDADES_SCHEMA_COLUMNS`, migration-v2 predicate/copy/rebuild/validation | `app/db_maintenance.py` | Sole canonical eleven-column migration contract. `main.ensure_atividades_schema_current` and its request-time call are retired. |
| `ensure_atividade_versioning_leaf_tables`, `ensure_atividade_versioning_leaf_triggers`, `ensure_atividade_versioning_leaf_indexes` | `app/db_maintenance.py` | Pure owners, respectively, of exactly four additive leaf tables, two `atividade_transicao` triggers and eight ordinary leaf indexes. They own no transaction, migration, PRAGMA, DML, core or requisicoes statement. |
| `ensure_activity_versioning_core_tables`, `ensure_activity_versioning_core_triggers`, `ensure_activity_versioning_core_indexes`, `_create_activity_versioning_core_tables`, `_rebuild_activity_versioning_core_v3`, `_drop_activity_versioning_rebuild_sensitive_objects`, `_validate_activity_versioning_v3`, `_migration_v3_normalize_activity_versioning_core`, `ensure_requisicoes_versioning_compatibility_schema`, `ensure_requisicoes_versioning_compatibility_index`, `ensure_atividade_versioning_schema` | `app/db_maintenance.py` | Sole owner of the canonical activity-versioning core DDL, six core triggers, seven core indexes, requisicoes compatibility columns/index, and the v3 migration. B10 moved all core responsibility from `main.py` to `app.db_maintenance`. The public orchestrator `ensure_atividade_versioning_schema` is caller-owned (non-destructive) when v3 is recorded or absent; it rejects non-canonical non-v3 states. |
| `_migration_v3_normalize_activity_versioning_core`, `_activity_versioning_source_variant` | `app/db_maintenance.py` | v3 classification and eligibility; determines `absent`, `missing_numero`, `canonical`, etc. |
| `ensure_turmas_matriz_schema` | `app/db.py` | Direct turma/matrix schema owner; delegates the accepted matrix owner. |
| `_needs_atividade_versao_migration`, `_needs_atividade_versao_default_fix`, `_needs_index_hardening` | Retired by B10 | Former schema-state predicates in `main.py`; retired along with the self-transactional rebuild. |
| `get_preferred_matriz_for_curso` | `app/db.py` | Direct query/runtime owner; it invokes the matrix ensure and can therefore cause caller-owned schema work. `main` compatibility-exports the same object. |
| `_get_main_db_helpers` | Retired by B11 | Former lazy wiring; symbol, map, and all retrievals removed. |
| `DATABASE`, `get_db_connection`, `close_db_connection` exports in `main.py` | `app.db` objects | Compatibility exports only, not defining ownership. |

`ensure_admin_arquivos_table` and `ensure_admin_alertas_table` remain defined by
`main.py`, but they are not reachable from the canonical `init_db` path and are
therefore outside this init reachability matrix.

## 7. Zero lazy-bridge contract

The exact lazy bridge is empty. `_get_main_db_helpers` does not exist, there are
no `helpers[...]` retrievals, and `app.db` contains no `import main`, `sys.modules`
lookup, `importlib` lookup, callback, or logger reference that resolves through
`main`.

The exact direct `app.db_maintenance` import set is
`apply_early_schema_migrations`, `apply_schema_migrations`,
`ensure_atividade_versioning_schema`, `ensure_matriz_atividade_links_table`,
`ensure_matrizes_atividades_table`, `ensure_reportes_table`,
`ensure_requisicao_alert_receipts_table`, `ensure_usuario_access_schema`, and
`ensure_usuario_profile_schema`. Backup settings are imported directly from
`app.backup_settings`; app settings, cloud backup, preferred matrix, and turma
matrix ownership are local to `app.db`.

## 8. Migration baseline

- `SCHEMA_VERSION == 3`.
- `SCHEMA_MIGRATIONS` contains exactly three contiguous ordered items:
  `(1, "baseline_schema_management", _migration_v1_baseline)`,
  `(2, "normalize_atividades_schema", _migration_v2_normalize_atividades_schema)`, and
  `(3, "normalize_activity_versioning_core", _migration_v3_normalize_activity_versioning_core)`.
- Migration v1 is a **historical baseline marker**. Its function body is only a
  docstring; the current physical schema is still produced by the canonical
  bootstrap body and its reachable helpers. The baseline migration is not a complete
  physical-schema definition.
- Migration v2 owns the canonical eleven-column `atividades` table transition,
  preserves accepted data including `documentos_json`, validates physical postconditions,
  and rejects later drift once v2 is recorded.
- Migration v3 normalizes the `atividade_versao` core: supports `missing_numero`,
  `old_unique_base_norma`, `default_zero`, `partial_index`, and `canonical` source
  variants; rebuilds only when non-canonical; preserves parent/child/self-reference
  data; assigns deterministic `numero_versao` per `atividade_base`; handles
  `sqlite_sequence`; drops and recreates leaf triggers and the `base_num` index before
  rebuild; and validates core/leaf/requisicoes state afterward. Recorded-v3
  contradiction hard-stops before any mutation. The early runner generalizes its
  `through_version` logic to reach v3 only when the core already exists.

## 9. Transaction-boundary matrix

`Active transaction` below means an outer transaction already owned by the
caller before the helper is entered.

| Function/path | Commit | Rollback | Savepoint | `executescript` / SQL transaction | FK PRAGMA | Active transaction expectation | Caller rollback contract | Classification |
|---|---:|---:|---:|---|---|---|---|---|
| `app.db.init_db` | 1 final | none | none | none | indirect only | Starts on a clean connection after the isolated early runner; later DML owns the pending caller transaction | Not available after its successful final commit; failure propagates with pending work still rollback-capable or closed by the context | Sole self-finalizing init owner |
| `main.init_db` compatibility export | none independently | none | none | none | none | Object-identical call into `app.db.init_db` | Same as canonical owner | Compatibility import, not an owner |
| Caller-owned direct schema helpers in `app.db_maintenance` | none | none | none | none | none | Work on clean or active connection | Outer rollback removes their uncommitted DDL/DML | Caller-owned |
| `ensure_schema_migrations_table`, `apply_schema_migrations` | none | none | none | none | none | Work on clean or active connection | Outer rollback removes uncommitted metadata/PRAGMA transaction effects as SQLite permits | Caller-owned |
| `apply_early_schema_migrations` | 1 bounded | 1 bounded on error | none | `BEGIN IMMEDIATE` | records original; `OFF` before begin; exact restore after completion | Requires no active transaction and verifies FK is actually disabled | No caller work may exist; migration/rebuild/v2 metadata/user-version effects roll back together | Isolated early migration owner |
| `ensure_usuario_access_structural_schema` | none | none | none | none | none | Invoked directly in tests or through public wrapper | Outer rollback removes uncommitted DDL | Caller-owned structural component |
| `seed_usuario_access_default_data` | none | none | none | none | none | Invoked directly in tests or through public wrapper | Outer rollback removes uncommitted inserts | Caller-owned default-data component |
| `normalize_usuario_access_startup_data` | none | none | none | none | none | Invoked directly in tests or through public wrapper | Outer rollback removes uncommitted updates | Caller-owned normalization component |
| `ensure_usuario_access_schema` | none via connection method | `ROLLBACK TO SAVEPOINT` only on error | owns `ensure_usuario_access_schema` savepoint and releases it | none | none | Works clean or nested | On a clean connection, top-level `RELEASE` finalizes helper work; inside an outer transaction, caller rollback still removes it | Savepoint-owned exception |
| `ensure_app_settings_schema` | none | none | none | none | none | On a clean connection its table CREATE is SQLite statement-autocommitted; first INSERT opens/joins caller work | Outer rollback removes uncommitted rows, not an already completed clean-connection DDL statement | Caller-owned; no explicit finalization |
| `ensure_backup_settings_structural_schema` | none | none | none | none | none | Clean call creates only the table; under caller `BEGIN`, DDL remains caller-owned | Clean post-DDL table remains; outer rollback removes uncommitted DDL | Caller-owned structural component |
| `seed_backup_settings_default_data` | none | none | none | none | none | First DML starts/joins the caller transaction; partial insert failure is not repaired | Caller rollback removes inserted defaults | Caller-owned default-data component |
| `normalize_legacy_backup_sync_interval` | none | none | none | none | none | Exact stripped `"300"` update joins caller work | Caller rollback removes the update | Caller-owned legacy-normalization component |
| `read_backup_settings` / `get_backup_settings` | none | none | none | none | none | Read occurs after startup DML in the orchestrator | Read failure leaves prior caller-owned work pending | Caller-owned read/merge component |
| `_apply_backup_settings_to_app` | none | none | none | none | none | Flask config mutates before the caller's eventual database commit | A later DB rollback does not undo already-applied runtime config; partial runtime mutation remains on failure | Runtime side effect, caller-owned DB boundary |
| `ensure_backup_settings_schema` | none | none | none | none | none | Exact order: structural → defaults → seed → legacy normalize → read/merge → runtime apply | Caller rollback removes uncommitted DB work but not prior runtime config effects | Caller-owned orchestrator; no atomicity improvement |
| `ensure_cloud_backup_schema` | none | none | none | none | none | Work on clean or active connection | Outer rollback removes uncommitted work | Caller-owned |
| `ensure_turmas_matriz_schema` | none | none | none | none | none | Work on clean or active connection | Outer rollback removes its and delegated matrix work | Caller-owned/delegating |
| `get_preferred_matriz_for_curso` | none | none | none | none | none | Query may be called clean or active | Delegated matrix ensure remains caller-owned | Query/runtime with schema side effect |
| `ensure_atividade_versioning_schema` | none directly | none directly | none | none | none | Caller-owned additive DDL only | Outer rollback removes its uncommitted DDL | Caller-owned pure DDL orchestrator when v3 is absent or canonical |
| Three `ensure_atividade_versioning_leaf_*` helpers | none | none | none | none | none | Execute only caller-owned `CREATE TABLE`, `CREATE TRIGGER`, or `CREATE INDEX` statements | Outer rollback removes their uncommitted DDL; injected failures propagate without commit, rollback or savepoint | Caller-owned pure DDL components |

### Transaction-owner classification

| Helper/stage | Class | Exact owner fact |
|---|---|---|
| `apply_early_schema_migrations` | A | Isolated `BEGIN IMMEDIATE`; one commit on success, one rollback on error, exact FK restoration. |
| `ensure_usuario_access_schema` | B | Owns the only startup savepoint; outermost RELEASE persists on a clean connection, nested RELEASE leaves ownership with the caller. |
| `ensure_usuario_profile_schema` | D | Pure PRAGMA/ALTER helper; no finalization. |
| `ensure_backup_settings_schema` | C/D | Joins the transaction already opened by app-settings inserts; database work remains caller-owned, while runtime Flask config is non-transactional. |
| `ensure_app_settings_schema` | D | No explicit finalization; on clean SQLite connection its CREATE completes in autocommit, then INSERT opens caller work. |
| `ensure_cloud_backup_schema` | C | Executes after app-settings DML, inside caller-owned work. |
| `ensure_reportes_table` | C | Executes inside caller-owned work. |
| `ensure_turmas_matriz_schema` | C | Executes inside caller-owned work and delegates matrix-table ensure. |
| `ensure_matriz_atividade_links_table` | C | Executes inside caller-owned work. |
| `ensure_atividade_versioning_schema` | C | Executes inside caller-owned work and owns no finalization. |
| final `apply_schema_migrations` | C | Records v1/v2/v3 and `user_version` inside caller-owned work; no commit. |
| final `init_db` commit | C finalizer | The sole final bootstrap commit. |

No class-E boundary was found. AST comparison against B10 proves that both former
init bodies and B11 each contain one `conn.commit()` and no body-owned BEGIN,
SAVEPOINT, RELEASE, SQL COMMIT, or rollback. B11 added no transaction split.

### Failure postcondition matrix

The focused executable contract keeps the failing connection open, records
`in_transaction`, compares its visible state with a newly opened observer, and
then closes it without an explicit rollback to prove SQLite close rollback.

| Injection point | State immediately before/after exception | Observer-visible durable state | Forbidden false state |
|---|---|---|---|
| Before early migration | not in transaction / not in transaction | no tables, indexes, migration rows; `user_version=0`; FK unchanged | Any bootstrap continuation. |
| Inside early v2 migration | isolated transaction rolls back; FK restored | preexisting four-column `atividades` and its data only; no `schema_migrations`; `user_version=0` | False migration row, false user version, orphan migration table, or bootstrap continuation. |
| After successful early v1/v2 migration | not in transaction | canonical eleven-column `atividades`, migration rows v1/v2 and `user_version=2` remain durable | Undoing the accepted migration commit or starting bootstrap after injected failure. |
| During first core table CREATE | not in transaction | no new object | Any later helper or final commit. |
| During app-settings ensure, after access RELEASE | not in transaction | `usuarios`, `configuracoes_acesso`, `usuarios_permissoes_acesso`, `sqlite_sequence`; access defaults 5; indexes `idx_usuarios_email`, `idx_usuarios_permissoes_usuario` | Any settings, backup, course, matrix, or migration completion. |
| During matrix schema | caller transaction active | preceding access durable set plus empty `configuracoes_app`; all rows and later tables visible only on failing connection disappear on close | Hidden commit of app/backup settings, courses, core bootstrap, or matrix work. |
| Before final migration pass | caller transaction active | same preceding durable set; no durable `schema_migrations`; observer `user_version=0` on a fresh database | Representation of final migrations as completed. |
| Immediately before final commit | caller transaction active; one commit attempt fails | same preceding durable set; caller sees v1/v2/v3 and `user_version=3`, observer sees none and `user_version=0`; close removes caller work | Successful final commit, swallowed exception, or post-failure continuation. |
| Later failure after a successful early migration | depends on later point | successfully committed v1/v2/v3 remain; only later work beyond the exact historically durable access/autocommit set must remain uncommitted | Treating accepted early durability as partial-bootstrap defect. |

The accepted caller-owned direct schema helpers are:
`ensure_reportes_table`, `ensure_usuario_profile_schema`,
`ensure_requisicao_alert_receipts_table`,
`ensure_matrizes_atividades_table`, and
`ensure_matriz_atividade_links_table`. The savepoint-owned direct import is
`ensure_usuario_access_schema`; `apply_schema_migrations` is listed separately
as migration metadata.

## 10. Retained compatibility and technical debt

1. `main.init_db` remains a compatibility import because 72 qualified lexical
   callers retain the historical spelling; five qualified direct-owner expressions
   use `app_db.init_db`, and three bare imported-owner calls are recorded separately.
   Identity is canonical and defining duplication is zero.
2. The canonical initializer retains one final bootstrap commit; the early runner
   rejects unrelated pending caller work at entry.
3. The access helper retains savepoint-dependent clean-vs-nested durability.
4. Clean-connection DDL before the first DML follows SQLite statement autocommit;
   this is preexisting behavior and is represented exactly in failure postconditions.
5. Backup runtime config is applied before caller database commit and cannot be
   rolled back with SQLite; the explicit active-app binding removes target ambiguity,
   not this timing debt.
6. `get_preferred_matriz_for_curso` remains a query that ensures matrix schema,
   but its owner is now direct and no lazy bridge remains.
7. Restore and development callers retain `main.init_db` spelling but execute the
   object-identical `app.db.init_db`; seed calls the owner directly.
8. Logger warnings can hide best-effort ALTER/index/reconciliation failures; a
   warning is not schema postcondition evidence.
9. The v1 migration marker remains historical; v2 owns the `atividades` transition;
   v3 owns the activity-versioning core transition. No migration v4 exists.

## 11. Final Phase 3 architecture

**Final Phase 3:** `app.db` solely defines connection authority and initialization.
`main` compatibility-exports the canonical objects. The lazy bridge and reverse
`app.db → main` dependency are zero. Access DDL, historical defaults, startup-wide
normalization, and savepoint orchestration remain explicit semantic layers in
`app.db_maintenance`; runtime login normalization remains in `main.py` and is
consumed unchanged by `app/views/core.py`.
Backup-settings table DDL is separately owned by `app.db_maintenance`; runtime
defaults, seeding, exact legacy normalization, read/merge, Flask config application
and the one-argument compatibility orchestrator are explicit layers in
`app.backup_settings`. Canonical init binds its exact active Flask app explicitly
before connection acquisition; no reverse import is used. Cloud/OAuth/retention/
restore workflows remain in `main.py`.
Activity-versioning migration/core/leaf/requisicoes compatibility ownership remains
in `app.db_maintenance` as established by B8/B10.
The separate `atividades` table is governed by recorded migration v2 and an isolated
early checkpoint; request processing no longer repairs its schema.

Later separately authorized units may separate query behavior from schema ensures
or move cloud/route concerns, but they may not recreate duplicate initialization or
reverse dependencies. Phase 4 is not authorized by this closeout.

No target statement changes current behavior. No current statement endorses the
behavior as ideal.

## 12. Later owning phases

Each unresolved responsibility has one named future owner. These are planning
boundaries, not authorization:

| Unresolved responsibility | Explicit later owning unit |
|---|---|
| Access schema/default-data/startup normalization and savepoint semantics | **Resolved by PHASE 3-B6** |
| Application-settings schema | **Resolved by PHASE 3-B11** |
| Backup-settings schema/default-data/legacy normalization/runtime application | **Resolved by PHASE 3-B7** |
| Cloud-account/log/drive schema and backup offloading | **Phase 5 backup-schema/offloading unit**, separately gated |
| `atividades` rebuild and FK PRAGMA semantics | **Resolved by PHASE 3-B9** |
| Activity-versioning leaf tables/transition triggers/leaf indexes | **Resolved by PHASE 3-B8** |
| Activity-versioning core schema, requisicoes compatibility and self-transactional rebuild | **Resolved by PHASE 3-B10** |
| Migration baseline expansion/version policy | **Resolved through v3 by PHASE 3-B9/B10; any v4 remains separately gated and unauthorized** |
| Matrix query that ensures schema | **Direct owner established by PHASE 3-B11; query/schema coupling remains explicit debt** |
| Logger/wiring lazy edge | **Resolved by PHASE 3-B11** |
| Dual direct core schemas, startup/seed/restore selection, and final commit ownership | **Resolved by PHASE 3-B11** |
| Main-defined admin-only lazy schemas not reachable from init | Their route/module extraction phases; not part of the init cutover until explicitly added |

B11 closes the Phase 3 initialization cutover only. It does not authorize Phase 4,
migration v4, cloud offloading, route extraction, repository redesign, or unrelated
production changes.

## 13. Canonical-database safety rules

- Canonical path: repository-root `database.db`.
- Frozen identity for B5: SHA-256
  `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`,
  size `544768` bytes, `database.db-wal` absent, `database.db-shm` absent.
- Canonical SQLite opens in B5 through B11: **exactly 0**.
- Static contract tests do not connect to SQLite. B11 fault-injection, seed,
  factory, migration, release, and restore tests use only `:memory:`, `tmp_path`,
  or session-owned external roots.
- `APP_DATABASE` must be set before application imports during pytest and must
  resolve outside the repository.
- Hashing/stat/searching source bytes is permitted; opening the canonical file
  with SQLite, starting the app against it, restore, backup, cleanup, custody,
  checkpoint, migration, hardening, or schema execution is prohibited without a
  separate explicit order.
- Every validation lane must reprove hash, size, and sidecar absence afterward.

## 14. Contract change procedure

An intentional change requires all of the following:

1. A separate authorization naming production and documentary scope.
2. Fresh read-only caller, owner, order, migration, and transaction inventory.
3. Explicit adjudication of sole init ownership, compatibility identity, zero
   reverse dependency, and every transaction owner.
4. A test change that first fails for the intended semantic contract change; do
   not ratchet whole-module bytes or irrelevant formatting.
5. Matching update to this document, the executable manifest, documentation
   index, architecture ledger, project state, and handoff.
6. Disposable database tests only, followed by focused and full hermetic gates.
7. Independent manifest/diff inspection proving no unlisted production change.
8. Canonical hash/size/sidecar reproof and an explicit open-count statement.
9. Selective staging, bounded commit, single authorized branch push, and
   post-commit verification.

A report, warning, stdout message, or passing unrelated test is not authority to
change this contract silently.

## 15. Prohibited interpretations

- **current does not mean ideal**;
- **frozen does not mean permanent**;
- **compatibility export does not mean defining ownership**;
- **baseline migration does not define the complete physical schema**;
- compatibility spelling does not create a second initializer;
- caller-owned does not include the isolated migration, savepoint, SQLite
  clean-connection autocommit, runtime-config, or finalizing exceptions above;
- this contract is not authorization for Phase 4, unrelated production code,
  migration v4, canonical SQLite access, restore execution, or cleanup.

## 16. B5 validation and review record

The semantic contract is implemented and locally verified. All commands used
the repository `.venv/Scripts/python.exe -B`; no Python-global validation result
is accepted as evidence. The complete contract file passed 8 tests in 0.23s.
Focused lanes passed: database/schema maintenance 39 in 3.14s;
ownership/residual helpers 34 in 0.59s; startup/application factory 10 in
0.69s; restore/clean disposable paths 2 in 2.88s; Git-aware runtime isolation
15 in 10.65s; documentation governance/index 1 in 0.22s; route/RBAC 3 in
0.64s, proving exactly 131 routes and 0 unmapped requirements. The full
hermetic suite passed 781 tests with 17 canonical D73H deselected, zero
failures/errors, in 305.48s. No materially relevant pytest warning occurred.

Independent replacement review used R4 `flash_free`, effective provider/model
`opencode` / `opencode/deepseek-v4-flash-free`, session
`ses_05e8aa690ffeIdhCqffTTIquW5`, cost 0, exit 0 and no fallback. It used only
native read/grep, returned APPROVE with no findings, and IAsup accepted that
verdict after direct source, diff and test adjudication. An earlier FREE review
package, session `ses_05e8ec944ffeEtPduaRhCiZxvH`, was rejected because it
created and removed an external temporary script despite the no-artifact rule;
repository hashes and the six-path manifest remained unchanged.

The canonical database remained unopened by SQLite: size 544768 bytes,
SHA-256 `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`,
WAL/SHM absent. The only next action after publication is external B5 review.
This validation record does not close or accept B5 and does not authorize B6.

## 17. B6 intentional revision and validation record

B6 was separately authorized after B5/B5-R1 acceptance. It moved the accepted
access statements into the four semantic layers recorded above, removed exactly
one access lazy key plus its matching retrieval, and preserved runtime login
normalization unchanged. TDD recorded three expected RED failures before the
production extraction. Focused schema/ownership/contract tests passed 85 in
7.52s; access/authorization/admin/student/login/RBAC tests passed 130 in 62.79s;
runtime-isolation, clean-install, route and RBAC gates passed 19 in 11.60s. The
full hermetic suite passed 791 tests with 17 canonical D73H deselected and zero
failures/errors in 298.10s. Routes remained 131 and RBAC unmapped remained 0.
Canonical SQLite opens remained 0 and the frozen filesystem identity and absent
sidecars remained unchanged. B6 is CLOSED / ACCEPTED by the explicit B7 order.

## 18. B7 intentional revision and validation record

B7 was separately authorized after B6 acceptance. The physical
`configuracoes_backup` CREATE moved to `app.db_maintenance`; runtime-derived defaults,
six-row `INSERT OR IGNORE`, exact stripped `"300"` normalization, persisted read/merge,
six Flask config effects and startup orchestration moved to `app.backup_settings`.
The public one-argument signature and main compatibility identities remain unchanged.
Stage A initially classified `current_app` as equivalent, but downstream isolation
adjudication found the legitimate `tools/seed_demo_data.py` caller: it enters a distinct
`create_app()` context while the baseline helper still reads and mutates module-level
`main.app`. That hard stop froze review/staging/publication. The explicit continuation
waiver authorized `main → app.backup_settings.bind_backup_settings_runtime_app(main.app)`
inside the existing manifest. The runtime module now fails clearly when unbound, never
falls back to `current_app`, and never imports `main`. Deterministic two-app coverage
proves defaults, legacy `"300"` normalization and runtime effects target the bound app
while the active distinct app remains unchanged. This shim is compatibility debt, not
target architecture.
`app.db` removed exactly one lazy key/retrieval, imports the orchestrator directly and
retains its call after user-profile schema and before `alunos`. No commit, rollback or
savepoint was added. Runtime config still changes before caller commit and remains
changed if later DB work rolls back. Cloud/OAuth, retention, directories, snapshot,
restore and provider behavior remain outside the extracted modules. TDD first failed
because `app.backup_settings` did not exist. Binding-specific TDD then failed on the
missing binding owner and passed 39 tests after the waiver implementation. Final focused
lanes passed: integrated ownership/schema/contract 124 in 13.85s; backup/cloud/restore
isolation 54 in 21.17s; release admin/route/RBAC 6 in 6.35s; runtime isolation 15 in
13.91s. The first full run exposed test-owned binding leakage only: 828 passed, 17
deselected and 2 CSRF inventory failures in 308.97s. Restoring the previous binding in
the ownership test fixture made the exact contaminating order pass 41 in 14.42s. The
final hermetic suite passed 830 tests with 17 canonical D73H deselected, zero
failures/errors, in 375.82s, with no material warning.
Post-governance regression passed 142 tests in 21.43s; canonical builders proved
exactly 131 routes and 0 RBAC-unmapped requirements.

Independent review used R4 `flash_free`, effective provider/model `opencode` /
`opencode/deepseek-v4-flash-free`, session `ses_05b37cc64ffeUakdqRN7BkJ9pq`, cost 0,
exit 0, no fallback and no mutation. It returned APPROVE; IAsup accepted the material
verdict while retaining the explicit binding, dual-init and non-atomic runtime/DB timing
as debt. Canonical SQLite opens remain 0; size/hash and absent sidecars remain frozen.
Commit/publication identity and post-publication verification resolve through Git and
the final operational report rather than a self-referential SHA in this tree. External
acceptance was superseded by the explicit B8 authorization; B7 is CLOSED / ACCEPTED.

## 19. B8 intentional revision and validation record

B8 was separately authorized after B7 acceptance. Baseline
`d1947b0c11506045b8d52bd235bc7381a2ca22c9` retained the public one-argument
`main.ensure_atividade_versioning_schema` orchestrator, every migration/rebuild
predicate/delegate, core table/trigger/index and requisicoes compatibility statement.
Exactly four leaf table CREATEs, two transition-trigger CREATEs and eight ordinary
leaf-index CREATEs moved byte-semantically into three caller-owned pure-DDL helpers in
`app.db_maintenance`. The orchestrator calls them at the exact removed block positions.
`app/db.py` remains byte-identical to the B8 baseline, including its exact four-entry
lazy bridge and retrieval order. `SCHEMA_VERSION` and `SCHEMA_MIGRATIONS` are unchanged.

TDD first passed three baseline-only guards and failed 16 architecture/behavior tests
because the owners and calls were absent. After correcting only two overbroad test
classifiers, the final RED remained 16 failures and 3 baseline guards passing. The
implemented focused suite passed 19 in 2.05s; the initial integrated ownership,
Phase-B schema, requisition idempotence, matrix/versioning, maintenance, residual and
contract lane passed 126 in 15.24s. Git-aware runtime isolation passed 15 in 8.69s;
the expanded 25-file versioning/matrix/requisition lane passed 309 in 113.34s;
route/RBAC tests passed 3 in 0.53s and direct builders proved 131 routes and zero
unmapped requirements. The full hermetic suite passed 849 with 17 canonical D73H
deselected and zero failures/errors in 287.05s. Independent review used the second FREE
call, session `ses_05adebcf2ffe4xZqeQFq1LX6Fy`, cost 0, exit 0, no fallback and no
mutation; verdict APPROVE, accepted by IAsup. Publication and post-publication evidence
are recorded after those gates complete. Stage-A FREE used
`opencode/deepseek-v4-flash-free`, session `ses_05af8e352ffetO5DM4E9LJ4n3d`, cost 0,
exit 0 and no fallback. IAsup accepted its factual statement map but rejected its
incorrect recommendation to move the three `_needs_*` predicates; those remain in
`main.py` as required. B8 is CLOSED / ACCEPTED by the explicit B9 authorization.

## 20. B9 intentional revision and validation record

B9 was separately authorized after B8 acceptance, with an explicit three-test-path
manifest waiver. Baseline `42ad0b500fe26fb2a4f49a2f8655d0217233af75` contained a
request-time ten-column rebuild that could discard `documentos_json` and could cascade-delete
FK children when dropping `atividades`. PATH A was rejected because deferred FK checking
does not defer `ON DELETE CASCADE`; PATH B disables and verifies FK enforcement before an
isolated `BEGIN IMMEDIATE` checkpoint.

Migration v2 `normalize_atividades_schema` now owns the exact eleven-column target in
`app.db_maintenance`. It preserves accepted legacy values, unusual/empty/null JSON text,
IDs and `sqlite_sequence`; rejects unknown source columns and preexisting temp residue;
and validates unique/check constraints and physical state. The early runner rejects an
existing transaction, snapshots/restores FK state, commits only the bounded migration,
and rolls back CREATE/copy/DROP/rename/metadata/user-version failures atomically. Exact
rows in `requisicoes`, `matrizes_atividades_itens`, and `atividade_legacy_map` are preserved.

Both init bodies call the early runner immediately after obtaining the connection and
before dependent bootstrap SQL, create the same fresh eleven-column schema, and retain
one unrestricted final migration application followed by one final bootstrap commit.
The recurring helper, request-route call, old defensive ALTER/normalization sequence,
and one lazy key/retrieval are retired. B8 leaf helpers remain AST-equivalent to baseline;
the activity-versioning core remains in `main.py` and no B10 work is included.

TDD RED recorded 20 expected failures before production changes. Focused migration GREEN
ultimately passed 23 tests and the critical aggregate, including both CSRF snapshots,
passed 173. The initial complete hermetic run produced 869 passed, 2 failed and 17
canonical D73H deselected. Both failures were localized to CSRF inventory/message-catalog
collection: literal migration-infrastructure strings passed directly to `RuntimeError`
were incorrectly collected as editable UI messages; no route, CSRF-policy or snapshot
drift occurred. The bounded correction introduced `SchemaMigrationStateError`, kept it
as an internal `RuntimeError` subclass, and enforced the read-only contradiction hard stop
before any FK or transaction mutation. The final Windows `PYTHONUTF8=1`/`-B` hermetic
pre-staging suite passed 872 with 17 deselected and zero failures/errors in 354.14s.
Selective staging then made `tests/test_atividades_schema_migration_v2.py` visible to the
Git-aware exact caller scan. The post-staging lane produced 78 passed and one failure:
the frozen manifest omitted `_run_init_on_temp_database` and still asserted 73
`main.init_db` callers. This was a localized contract-evidence defect, not a migration,
runtime, database or route defect. Only the already authorized contract test and this
canonical contract were corrected to 74 callers. The targeted node passed 1, the complete
post-staging lane passed 79, and the required full hermetic rerun passed 873 with 17
deselected and zero failures/errors in 357.56s. Stage A FREE used `opencode` /
`opencode/deepseek-v4-flash-free`, session `ses_05ac5d405ffenqwkRrh7QeBAIo`, cost 0,
and was rejected as unusable. Explicit fallback reason
`FALLBACK_FREE_UNUSABLE_DELIVERY` used `opencode-go` /
`opencode-go/deepseek-v4-flash`, session `ses_05abb3bd1ffeut3C2R2SSaIuw7`, cost
`0.0021259168`; its PATH B conclusion was accepted after IAsup adjudication.

Independent review attempted the required FREE route first, but the FREE transport was
technically unusable/incomplete. After two recorded FREE uses, the final read-only delta
re-review explicitly used `FALLBACK_FREE_BUDGET_EXHAUSTED`: effective provider/model
`opencode-go` / `opencode-go/deepseek-v4-flash`, session
`ses_05a18eb14ffejH0B4Z7zROy427`, reported final-call cost `0.0005707464`, exit 0 and
zero mutation. Verdict: APPROVE, findings NONE. IAsup did not accept the verdict merely
as text: it independently checked the PATH B transaction boundary, original FK-state
restoration, contradiction detection before mutation, lossless `documentos_json`
preservation, exact preservation of `requisicoes`, `matrizes_atividades_itens` and
`atividade_legacy_map`, PATH A rejection evidence, and the exact three-key lazy bridge.
The verdict is accepted.

The authorized commit-tree manifest is exactly:

1. `AGENT_HANDOFF.md`
2. `PROJECT_STATE.md`
3. `app/db.py`
4. `app/db_maintenance.py`
5. `docs/DOCUMENTATION_INDEX.md`
6. `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
7. `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md`
8. `main.py`
9. `tests/test_activity_versioning_core_migration_v3.py`
10. `tests/test_atividades_schema_migration_v2.py`
11. `tests/test_activity_versioning_leaf_schema_ownership.py`
12. `tests/test_backup_settings_ownership.py`
13. `tests/test_db_schema_maintenance.py`
14. `tests/test_phase3_schema_startup_transaction_contract.py`
15. `tests/test_ref_0c_b1_p0_access_context_transactions.py`

Path 15 is a mechanically required v3 expectation update (migration
`normalize_activity_versioning_core` and `user_version 3`) with no production
scope expansion. It was not preauthorized in the explicit B10 boundary, its
content is accepted as correct, and it is classified as a process nonconformity
requiring this governance correction.

Publication is pending at commit-tree time. PHASE 3-B11 remains unauthorized.

## 21. B10 intentional revision and validation record

B10 was separately authorized after B9 acceptance. Baseline
`37c8757e4ef41647c971ad8a974c853dec6ce4e7` contained the legacy self-transactional
activity-versioning rebuild in `main.py` as the known exception #5. B10 extracts the
v3 migration `normalize_activity_versioning_core` to `app.db_maintenance`, retires all
seven legacy rebuild symbols from `main.py`, moves core DDL/triggers/indexes and
requisicoes-compatibility ownership to `app.db_maintenance`, and reduces the lazy bridge
from three to exactly two entries (`get_preferred_matriz_for_curso` and `logger`).

Migration v3 supports five legacy `atividade_versao` variants (`missing_numero`,
`old_unique_base_norma`, `default_zero`, `partial_index`, canonical) and rebuilds only
when non-canonical. It preserves parent rows (`atividade_base`, `norma_atividade`),
child FK sets (`atividade_transicao`, `matriz_norma`, `matriz_atividade_versao_item`,
`atividade_legacy_map`, `requisicoes`), self-references via `versao_anterior_id`, and
`sqlite_sequence`. Deterministic `numero_versao` is assigned via `ROW_NUMBER() OVER
(PARTITION BY atividade_base_id ORDER BY id)` for the `missing_numero` variant. Leaf
triggers and the `idx_atividade_versao_base_num` index are dropped before and recreated
after rebuild. Recorded-v3 physical contradiction, partial/unsupported core states, and
preexisting temp tables each hard-stop before any mutation.

The early runner `apply_early_schema_migrations` generalizes to reach v3 only when the
core already exists; absent core stops at `through_version=2`. Its isolated
`BEGIN IMMEDIATE` transaction remains the sole destructive migration boundary, with FK
state recording/disable/restore and atomic rollback on every injected failure stage.

`ensure_atividade_versioning_schema` in `app.db_maintenance` is now the
caller-owned non-destructive public orchestrator; it rejects non-canonical states
when v3 is not yet recorded and accepts canonical and absent states. `main.py` imports
it by identity. App.db directly imports it. The lazy bridge contains exactly
`get_preferred_matriz_for_curso` and `logger` in that order.

B8 leaf table/trigger/index ownership is preserved unchanged. B9 atividades v2
eleven-column contract is preserved unchanged. B7 backup-settings ownership is preserved
unchanged. No B11 work exists.

Test evidence: Focused v3+v2 tests passed 49 in 2.25s; six-test contract gate passed
163 in 10.36s; comprehensive regression passed 352 with 17 D73H deselected in 82.32s.
Routes remain 131; RBAC unmapped remains 0. Canonical database opens remain 0;
`database.db` size 544768 bytes, SHA-256
`a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`, WAL/SHM absent.
Protected residual remains 17420 bytes, SHA-256
`7388cfbc8f446410ef3c98ec0fa274c2c36ff4f3ef8ed2cd649bb1f3e1d3bb0e`.

The authorized commit-tree manifest is exactly:

1. `AGENT_HANDOFF.md`
2. `PROJECT_STATE.md`
3. `app/db.py`
4. `app/db_maintenance.py`
5. `docs/DOCUMENTATION_INDEX.md`
6. `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
7. `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md`
8. `main.py`
9. `tests/test_activity_versioning_core_migration_v3.py`
10. `tests/test_atividades_schema_migration_v2.py`
11. `tests/test_activity_versioning_leaf_schema_ownership.py`
12. `tests/test_backup_settings_ownership.py`
13. `tests/test_db_schema_maintenance.py`
14. `tests/test_phase3_schema_startup_transaction_contract.py`

Historical B10 commit-tree state: publication was pending and PHASE 3-B11 remained
unauthorized. That predecessor state is superseded by the published B11 record below.

## 22. B11 single-init validation, publication, and B11-R1 closeout record

PHASE 3-B11 starts from accepted B10-R1 commit
`e63e1a66b9d2ebad7253a0efd2e0a367b89b8b8a` and is published as technical commit
`c9009bf3d68950ad4e0499b65928603e84bee341`, subject `Unify database initialization
ownership`, with exactly one parent. Publication and post-publication verification
are complete. The exact B11 architecture and transaction semantics remain those in
sections 1–15; B11-R1 changes publication/review/closeout metadata only.

The accepted B11 artifact establishes `app.db.init_db` as the sole defining
initializer, with `main.init_db` as an object-identical compatibility import.
`_init_db_impl`, `_get_main_db_helpers`, the local database sync shim, every lazy
retrieval, and every `app.db → main` dependency are removed. No production correction
occurred after independent review.

The exact transaction-owner inventory and failure postcondition matrix remain in
section 9. Deterministic AST comparison found no B11-added transaction boundary.
Fault injection covers failing-connection state, observer state, close rollback,
migration rows, `user_version`, FK restoration, rows, tables, indexes, exception
propagation, and absence of continuation. Caller inventory remains 72 qualified
`main.init_db(...)`, 5 qualified direct-owner calls, and three separately tracked bare
imported-owner calls. Registry remains exact contiguous unique v1/v2/v3 with
`SCHEMA_VERSION == 3`; no migration v4 exists.

The B11 technical manifest is exactly 14 paths:

1. `AGENT_HANDOFF.md`
2. `PROJECT_STATE.md`
3. `app/db.py`
4. `docs/DOCUMENTATION_INDEX.md`
5. `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`
6. `docs/refactor/PHASE3_SCHEMA_STARTUP_TRANSACTION_CONTRACT.md`
7. `main.py`
8. `tests/test_activity_versioning_leaf_schema_ownership.py`
9. `tests/test_backup_settings_ownership.py`
10. `tests/test_db_connection_ownership.py`
11. `tests/test_db_schema_maintenance.py`
12. `tests/test_phase3_final_init_cutover.py`
13. `tests/test_phase3_schema_startup_transaction_contract.py`
14. `tests/test_residual_shared_helpers.py`

Git statistics are 1428 insertions and 812 deletions. Production paths are exactly
`app/db.py` and `main.py`. Canonical technical diff SHA-256 is
`19f59666f1c55259493281950fa2651e6261fc7e6f8b8e01473f254326c87378`.

Accepted test evidence is: final hermetic `913 passed / 17 deselected / 416.66s /
exit 0`; index-visible 67 passed; route/RBAC `3 passed / routes 131 / unmapped 0`;
post-publication `212 passed / 42.37s`.

The accepted independent review record is:

- fallback cause `FALLBACK_FREE_TIMEOUT_UNUSABLE_DELIVERY`;
- provider `opencode-go`;
- effective model `opencode-go/deepseek-v4-flash`;
- session `ses_032324d57fferZNeqNjUW681iq`;
- observed cost `0.01252156 USD`;
- verdict `APPROVE`;
- Material/Critical/High findings: 0;
- accepted LOW: the `main` compatibility import creates intentional and tested
  compatibility coupling;
- accepted INFO: registry remains v1/v2/v3; caller inventory 72/5 plus three bare
  imports is correctly distinguished; transaction fault-injection coverage is
  sufficient.

Reviewer nonconformity 1 is accepted with declaration:
`SAME_SESSION_OUTPUT_RECOVERY / SECOND_INVOCATION_PROCESS_NONCONFORMITY /
SAME_PROVIDER_MODEL_AND_SESSION / NO_NEW_TOOLS / NO_DIFF_CHANGE /
NO_REVIEWER_SUBSTITUTION / USABLE_VERDICT_RECOVERED / ACCEPTED_WITH_DECLARATION`.
The first post-opt-in inference produced no final text. A textual continuation in the
same provider/model/session recovered the verdict. No fallback, new tool, repository
mutation, reviewer substitution, or reviewed-candidate change occurred.

Reviewer nonconformity 2 is accepted with declaration:
`EXTERNAL_TEMPORARY_FILE_MUTATION / OUTSIDE_REPOSITORY / NOT_STAGED / NOT_COMMITTED /
NO_REPOSITORY_OR_INDEX_IMPACT / UNAUTHORIZED_BY_REVIEW_CONTRACT /
ACCEPTED_WITH_DECLARATION`. The declared artifact is `/tmp/candidate.diff`, reported
size 144049 bytes and reported SHA-256
`fcd1b62e141434dccaa89dabe9b604afe61977c96490674503b9410185627771`. It remains
preserved without inspection, alteration, or deletion under B11-R1.

B11-R1 is a six-path governance-only closeout awaiting supervisor review. It does not
repeat independent review, change the accepted architectural/transactional contract,
or authorize production work. Phase 3 is not formally closed until supervisor
acceptance. Phase 4 remains NOT AUTHORIZED and migration v4 remains PROHIBITED.
