# Phase 3 schema, startup, and transaction contract

**Status:** PHASE 3-B9 intentional revision of the accepted PHASE 3-B5/B6/B7/B8 contract
**Phase status:** B5/B5-R1/B6/B7/B8 CLOSED / ACCEPTED; B9 IMPLEMENTED / FOCUSED VERIFIED / FULL VERIFICATION AND PUBLICATION PENDING
**B9 baseline:** `42ad0b500fe26fb2a4f49a2f8655d0217233af75` (`Extract activity versioning leaf schema ownership`)
**Executable contract:** `tests/test_phase3_schema_startup_transaction_contract.py`

## 1. Scope and purpose

This document freezes the accepted behavior that exists before the final Phase 3
cutover. B9 replaces the recurring `atividades` rebuild with migration v2,
adds an isolated pre-bootstrap migration checkpoint to both active init bodies,
converges both fresh schemas to the canonical eleven-column contract, and removes
only the matching lazy edge and request-route repair call. B8 leaf ownership and
the B10 activity-versioning core remain unchanged. It remains a review and
regression baseline for later settings,
backup, migration, activity-rebuild, activity-versioning, repository, and
`init_db`-cutover units. It records current ownership, call paths, ordering, and
transaction boundaries; it does not redesign unrelated behavior.

The two active initialization implementations are deliberately documented as
**divergent**. B5 changes no production Python, schema, migration, runtime,
route, RBAC, template, UI, backup, restore, or canonical database state.

## 2. Current connection authority

| Concern | Current contract |
|---|---|
| `DATABASE` | Sole defining owner: `app/db.py`; resolved as `os.environ.get("APP_DATABASE", os.path.join(PROJECT_ROOT, "database.db"))`. |
| `get_db_connection` | Sole defining owner: `app/db.py`; stores one connection in Flask `g.db` and reuses it for the application context. |
| `close_db_connection` | Sole defining owner: `app/db.py`; pops `g.db` and closes it. `create_app` registers this exact object once with `teardown_appcontext`. |
| Main compatibility | `main.py` imports `DATABASE`, `get_db_connection`, and `close_db_connection`; the exported objects are identical to the `app.db` owners. Compatibility is not defining ownership. |
| Row and collation | New connections use `sqlite3.Row` and register `PTBR_NOACCENT`. |
| PRAGMAs | Every newly created connection executes `foreign_keys = ON`, `journal_mode = WAL`, and `synchronous = NORMAL`, in that order. |
| Local sync shim | `app.db._sync_database_from_main()` is the accepted no-op and returns local `DATABASE`; it does not read or import `main`. |

The application factory creates/configures the Flask app and registers the close
lifecycle. It does **not** call either `init_db`. Module-level `main.app` is
created with `create_app(...)`; development bootstrap happens separately in the
`__main__` block.

## 3. Current dual-init entry-point inventory

| Entry point | Defining owner | Direct caller | Context and transaction contract |
|---|---|---|---|
| `app.db.init_db` | `app/db.py` | `tools/seed_demo_data.py::seed` | Caller explicitly owns `app.app_context()`. Wrapper calls the local no-op sync and delegates to `_init_db_impl`; the implementation commits. |
| `app.db._init_db_impl` | `app/db.py` | `app.db.init_db` only | Requires an active Flask application context because `get_db_connection` uses `g`. It obtains the connection and performs exactly one final `conn.commit()`. |
| `main.init_db` | `main.py` | Startup, restore, tools, and tests listed below | Requires an active or inherited Flask application/request context. It obtains the connection and performs exactly one final `conn.commit()`. |

Both implementations are active. They share many core tables and helpers, but
are not equivalent:

- `app.db._init_db_impl` obtains three dependencies through the lazy bridge,
  invokes `apply_early_schema_migrations` immediately after connection acquisition,
  directly invokes `ensure_usuario_access_schema` and `ensure_reportes_table`, includes
  `cursos.total_horas_aac` and `cursos.total_horas_aeu`, reconciles
  `turmas.matriz_id`, and then commits.
- `main.init_db` owns its own monolithic table/ALTER sequence, invokes
  `ensure_app_settings_schema`, `ensure_cloud_backup_schema`, and
  `ensure_turmas_matriz_schema`, invokes the same early checkpoint immediately
  after connection acquisition, does not call `ensure_reportes_table`, and then commits.
- Both create the same eleven-column `atividades` table on a fresh database, call
  unrestricted migration application at the end, and finalize the shared Flask
  connection. The early checkpoint rejects preexisting caller work before any
  bootstrap SQL, so neither init may silently commit or roll back unrelated work.

## 4. Exact caller inventory

The executable manifest identifies call expressions by tracked path and lexical
scope rather than by brittle line number. At this baseline there are **74** calls
to `main.init_db`, **1** call to `app.db.init_db`, and **1** call to
`app.db._init_db_impl`.

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

## 5. app.db bootstrap sequence

The following is the exact current semantic order of
`app.db._init_db_impl`; nested SQL details are grouped without changing order:

1. Obtain `_get_main_db_helpers`.
2. Bind AAC/AEU defaults.
3. Retrieve, in exact order: `ensure_atividade_versioning_schema`,
   `get_preferred_matriz_for_curso`, `logger`.
4. Obtain `conn` from `get_db_connection`.
5. Call direct `apply_early_schema_migrations(conn, logger=logger)`.
6. Create `usuarios`; best-effort email index.
7. Call direct `ensure_usuario_access_schema`.
8. Call direct `ensure_usuario_profile_schema`.
9. Call direct `ensure_backup_settings_schema` from `app.backup_settings`.
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
28. Call direct `ensure_matrizes_atividades_table`.
29. Call direct `ensure_matriz_atividade_links_table`.
30. Call lazy `ensure_atividade_versioning_schema`.
31. Attempt the five `turmas` additions, in order: `curso_id`, `ano_inicio`,
    `semestre_inicio`, `codigo`, `matriz_id`.
32. Conditionally add `ano_fim`, then `semestre_fim`.
33. Create course/matrix indexes and best-effort unique turma indexes.
34. Reconcile old turmas: assign `GERAL`, sequential numbers, and generated
    codes with collision fallback.
35. Reconcile missing `turmas.matriz_id` through lazy
    `get_preferred_matriz_for_curso`.
36. Call unrestricted `apply_schema_migrations(conn, logger=logger)`.
37. Execute the one expected final `conn.commit()`.

The matrix order is mandatory: matrices before links, links before activity
versioning. Migration metadata is mandatory before the final commit.

Logger-dependent paths in this implementation are the caught failures for:
`alunos.turma_id`, `alunos.foto_perfil`, `requisicoes.nome_evento`, both
requisition alert timestamps, the pending-alert index, `turmas.numero`,
`turmas.ano_fim`, `turmas.semestre_fim`, old turma course/code reconciliation,
and old turma matrix reconciliation. These warnings do not replace transaction
or schema verification.

## 6. Schema-owner matrix

| Function or metadata | Defining owner | Frozen classification |
|---|---|---|
| `_init_db_impl` | `app/db.py` | Direct owner of one current core bootstrap and its final commit. |
| `init_db` in `app.db` | `app/db.py` | Compatibility/bootstrap wrapper only; no independent schema body. |
| `init_db` in `main` | `main.py` | Direct owner of the second active, divergent core bootstrap and its final commit. |
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
| `bind_backup_settings_runtime_app`, `_backup_settings_defaults`, `seed_backup_settings_default_data`, `normalize_legacy_backup_sync_interval`, `read_backup_settings`, `_apply_backup_settings_to_app`, `get_backup_settings`, `ensure_backup_settings_schema` | `app/backup_settings.py` | Sole owners of the explicit legacy runtime-app binding, runtime-derived defaults, historical six-row seeding, exact stripped `"300"` normalization, persisted read/merge, six Flask config effects and ordered startup orchestration. `main` binds its exact module-level `app` after configuring the six values and compatibility-exports the four historical names; `app.db` directly imports the orchestrator. |
| `ensure_app_settings_schema` | `main.py` | Application-settings schema owner, reachable from `main.init_db` only. |
| `ensure_cloud_backup_schema` | `main.py` | Adjacent cloud schema owner for `cloud_accounts`, `backup_logs`, and `cloud_drive_settings`; unchanged and isolated from B7. |
| `ATIVIDADES_SCHEMA_COLUMNS`, migration-v2 predicate/copy/rebuild/validation | `app/db_maintenance.py` | Sole canonical eleven-column migration contract. `main.ensure_atividades_schema_current` and its request-time call are retired. |
| `ensure_atividade_versioning_leaf_tables`, `ensure_atividade_versioning_leaf_triggers`, `ensure_atividade_versioning_leaf_indexes` | `app/db_maintenance.py` | Pure owners, respectively, of exactly four additive leaf tables, two `atividade_transicao` triggers and eight ordinary leaf indexes. They own no transaction, migration, PRAGMA, DML, core or requisicoes statement. |
| `_recreate_atividade_versao`, `_migrate_atividade_versao_to_numero_versao`, `_fix_atividade_versao_default`, `ensure_atividade_versioning_schema` | `main.py` | Self-transactional rebuild/migration owners and active public orchestrator. The orchestrator retains core tables/triggers/indexes and requisicoes compatibility statements and composes the three leaf helpers at their accepted semantic positions. |
| `ensure_turmas_matriz_schema` | `main.py` | Remaining turma/matrix schema owner; delegates accepted matrix owner. |
| `_needs_atividade_versao_migration`, `_needs_atividade_versao_default_fix`, `_needs_index_hardening` | `main.py` | Schema-state predicates, not defining owners. |
| `get_preferred_matriz_for_curso` | `main.py` | Query/runtime behavior rather than defining ownership, but it invokes the matrix ensure and can therefore cause caller-owned schema work. |
| `_get_main_db_helpers` | `app/db.py` | Compatibility/lazy wiring only, not schema ownership. |
| `DATABASE`, `get_db_connection`, `close_db_connection` exports in `main.py` | `app.db` objects | Compatibility exports only, not defining ownership. |

`ensure_admin_arquivos_table` and `ensure_admin_alertas_table` remain defined by
`main.py`, but they are not reachable from either current `init_db` path and are
therefore outside this init reachability matrix.

## 7. Remaining lazy-bridge matrix

The exact three entries and matching `_init_db_impl` retrievals are frozen in this
order:

| Order | Lazy key | Current source object | Matching local retrieval | Role |
|---:|---|---|---|---|
| 1 | `ensure_atividade_versioning_schema` | `main.ensure_atividade_versioning_schema` | same-name local | Versioning schema |
| 2 | `get_preferred_matriz_for_curso` | `main.get_preferred_matriz_for_curso` | same-name local | Query/runtime with lazy schema side effect |
| 3 | `logger` | `main.logger` | same-name local | Warning/migration logging |

B7 removed only the backup-settings key and matching retrieval; B8 preserved the
then-four-entry bridge. B9 removes only the recurring-activities key and retrieval and
adds the direct early runner before bootstrap SQL. `app.db` directly imports only
`ensure_backup_settings_schema` from `app.backup_settings`. The exact direct
`app.db_maintenance` import set remains:
`apply_early_schema_migrations`, `apply_schema_migrations`, `ensure_matriz_atividade_links_table`,
`ensure_matrizes_atividades_table`, `ensure_reportes_table`,
`ensure_requisicao_alert_receipts_table`, `ensure_usuario_access_schema`, and
`ensure_usuario_profile_schema`.

## 8. Migration baseline

- `SCHEMA_VERSION == 2`.
- `SCHEMA_MIGRATIONS` contains exactly two contiguous ordered items:
  `(1, "baseline_schema_management", _migration_v1_baseline)` and
  `(2, "normalize_atividades_schema", _migration_v2_normalize_atividades_schema)`.
- Migration v1 is a **historical baseline marker**. Its function body is only a
  docstring; the current physical schema is still produced by the two bootstrap
  bodies and their reachable helpers. The baseline migration is not a complete
  physical-schema definition.
- `schema_migrations` columns are `version INTEGER PRIMARY KEY`,
  `name TEXT NOT NULL`, `applied_at TEXT NOT NULL DEFAULT (datetime('now'))`,
  and nullable `details_json`.
- Migration v2 accepts only known legacy subsets, preserves accepted data including
  `documentos_json`, rebuilds to the exact eleven-column table when needed, preserves
  `sqlite_sequence`, validates the physical postcondition and rejects later drift once
  v2 is recorded.
- `apply_schema_migrations` validates contiguous version/name history, optionally bounds
  application with `through_version`, calls each missing migration, records only a
  successful migration, and sets `PRAGMA user_version` to the highest actually recorded
  version rather than the global target.
- It performs no commit, rollback, savepoint, or `executescript`; both current
  init implementations own the final unrestricted-pass commit.
- `apply_early_schema_migrations` skips a physically fresh database without recording v2.
  For an existing `atividades`, it requires `conn.in_transaction is False`, records and
  disables FK enforcement before `BEGIN IMMEDIATE`, runs through v2, commits only that
  bounded transaction, rolls the whole unit back on failure, and restores the original
  FK state. Failure propagates before bootstrap continues.

## 9. Transaction-boundary matrix

`Active transaction` below means an outer transaction already owned by the
caller before the helper is entered.

| Function/path | Commit | Rollback | Savepoint | `executescript` / SQL transaction | FK PRAGMA | Active transaction expectation | Caller rollback contract | Classification |
|---|---:|---:|---:|---|---|---|---|---|
| `app.db._init_db_impl` | 1 final | none | none | none | indirect only | Does not require one; will finalize all pending work on the shared connection | Not available after its final commit | Self-finalizing init owner |
| `main.init_db` | 1 final | none | none | none | indirect only | Does not require one; will finalize all pending work on the shared connection | Not available after its final commit | Self-finalizing init owner |
| `app.db.init_db` | none directly | none | none | delegates | indirect | Delegates to `_init_db_impl` | Same as implementation | Wrapper |
| Five caller-owned direct schema helpers in `app.db_maintenance` | none | none | none | none | none | Work on clean or active connection | Outer rollback removes their uncommitted DDL/DML | Caller-owned |
| `ensure_schema_migrations_table`, `apply_schema_migrations` | none | none | none | none | none | Work on clean or active connection | Outer rollback removes uncommitted metadata/PRAGMA transaction effects as SQLite permits | Caller-owned |
| `apply_early_schema_migrations` | 1 bounded | 1 bounded on error | none | `BEGIN IMMEDIATE` | records original; `OFF` before begin; exact restore after completion | Requires no active transaction and verifies FK is actually disabled | No caller work may exist; migration/rebuild/v2 metadata/user-version effects roll back together | Isolated early migration owner |
| `ensure_usuario_access_structural_schema` | none | none | none | none | none | Invoked directly in tests or through public wrapper | Outer rollback removes uncommitted DDL | Caller-owned structural component |
| `seed_usuario_access_default_data` | none | none | none | none | none | Invoked directly in tests or through public wrapper | Outer rollback removes uncommitted inserts | Caller-owned default-data component |
| `normalize_usuario_access_startup_data` | none | none | none | none | none | Invoked directly in tests or through public wrapper | Outer rollback removes uncommitted updates | Caller-owned normalization component |
| `ensure_usuario_access_schema` | none via connection method | `ROLLBACK TO SAVEPOINT` only on error | owns `ensure_usuario_access_schema` savepoint and releases it | none | none | Works clean or nested | On a clean connection, top-level `RELEASE` finalizes helper work; inside an outer transaction, caller rollback still removes it | Savepoint-owned exception |
| `ensure_app_settings_schema` | none | none | none | none | none | Work on clean or active connection | Outer rollback removes uncommitted work | Caller-owned |
| `ensure_backup_settings_structural_schema` | none | none | none | none | none | Clean call creates only the table; under caller `BEGIN`, DDL remains caller-owned | Clean post-DDL table remains; outer rollback removes uncommitted DDL | Caller-owned structural component |
| `seed_backup_settings_default_data` | none | none | none | none | none | First DML starts/joins the caller transaction; partial insert failure is not repaired | Caller rollback removes inserted defaults | Caller-owned default-data component |
| `normalize_legacy_backup_sync_interval` | none | none | none | none | none | Exact stripped `"300"` update joins caller work | Caller rollback removes the update | Caller-owned legacy-normalization component |
| `read_backup_settings` / `get_backup_settings` | none | none | none | none | none | Read occurs after startup DML in the orchestrator | Read failure leaves prior caller-owned work pending | Caller-owned read/merge component |
| `_apply_backup_settings_to_app` | none | none | none | none | none | Flask config mutates before the caller's eventual database commit | A later DB rollback does not undo already-applied runtime config; partial runtime mutation remains on failure | Runtime side effect, caller-owned DB boundary |
| `ensure_backup_settings_schema` | none | none | none | none | none | Exact order: structural → defaults → seed → legacy normalize → read/merge → runtime apply | Caller rollback removes uncommitted DB work but not prior runtime config effects | Caller-owned orchestrator; no atomicity improvement |
| `ensure_cloud_backup_schema` | none | none | none | none | none | Work on clean or active connection | Outer rollback removes uncommitted work | Caller-owned |
| `ensure_turmas_matriz_schema` | none | none | none | none | none | Work on clean or active connection | Outer rollback removes its and delegated matrix work | Caller-owned/delegating |
| `get_preferred_matriz_for_curso` | none | none | none | none | none | Query may be called clean or active | Delegated matrix ensure remains caller-owned | Query/runtime with schema side effect |

| `_recreate_atividade_versao` | SQL `COMMIT` | no explicit SQL rollback | none | one `executescript` containing `PRAGMA OFF; BEGIN; ... COMMIT; PRAGMA ON` | `OFF`/`ON` | Must not be treated as a neutral nested helper | Caller rollback cannot undo the completed internal commit | Self-transactional exception |
| `_migrate_atividade_versao_to_numero_versao`, `_fix_atividade_versao_default` | indirect | indirect | none | each delegates once to `_recreate_atividade_versao` | indirect | Same conditional constraint as delegate | Same as delegate when branch executes | Delegated self-transactional exception |
| `ensure_atividade_versioning_schema` | none directly | none directly | none | conditionally invokes either self-transactional delegate | indirect | Caller-owned only when no rebuild branch runs | Caller rollback covers direct additive DDL, not a completed rebuild delegate | Conditional self-transactional exception |
| Three `ensure_atividade_versioning_leaf_*` helpers | none | none | none | none | none | Execute only caller-owned `CREATE TABLE`, `CREATE TRIGGER`, or `CREATE INDEX` statements | Outer rollback removes their uncommitted DDL; injected failures propagate without commit, rollback or savepoint | Caller-owned pure DDL components |

The accepted caller-owned direct schema helpers are:
`ensure_reportes_table`, `ensure_usuario_profile_schema`,
`ensure_requisicao_alert_receipts_table`,
`ensure_matrizes_atividades_table`, and
`ensure_matriz_atividade_links_table`. The savepoint-owned direct import is
`ensure_usuario_access_schema`; `apply_schema_migrations` is listed separately
as migration metadata.

## 10. Known exceptions and technical debt

1. Two active init bodies duplicate and diverge.
2. Both init owners retain one final bootstrap commit, but the early checkpoint now
   rejects unrelated pending caller work at entry.
3. The access helper has savepoint-dependent clean-vs-nested durability.
4. The `atividades` rebuild is now one-time migration v2; later drift is detected and
   fails instead of being repaired silently.
5. Activity-version migration/default-fix branches call a self-transactional
   `executescript` and cannot be classified as caller-owned.
6. `get_preferred_matriz_for_curso` is named as a query but lazily ensures matrix
   schema.
7. The restore flow reinitializes the restored database through `main.init_db`,
   not `app.db.init_db`.
8. Development startup uses `main.init_db`; demo seeding uses `app.db.init_db`.
9. Logger warnings can hide best-effort ALTER/index/reconciliation failures; a
   warning is not schema postcondition evidence.
10. The v1 migration marker still records a historical baseline; v2 owns only the
    canonical `atividades` transition, not the complete physical schema.

## 11. Current versus target architecture

**Current:** the exact dual-init, three-entry lazy bridge, compatibility exports,
helper ownership, transaction exceptions, and call graph above are accepted and
frozen for regression protection. Access DDL, historical defaults, startup-wide
normalization, and savepoint orchestration are explicit semantic layers in
`app.db_maintenance`; runtime login normalization remains in `main.py` and is
consumed unchanged by `app/views/core.py`.
Backup-settings table DDL is separately owned by `app.db_maintenance`; runtime
defaults, seeding, exact legacy normalization, read/merge, Flask config application
and the one-argument compatibility orchestrator are explicit layers in
`app.backup_settings`. The runtime module deliberately does not use `current_app`:
`main` explicitly binds its exact module-level `app`, preserving the historical target
even while another Flask app context is active. This is
`EXPLICIT_LEGACY_RUNTIME_APP_BINDING / BASELINE_COMPATIBILITY_SHIM /
NOT_TARGET_ARCHITECTURE`, not the final application-factory design. Cloud/OAuth/
retention/restore workflows remain in `main.py`.
The activity-versioning public orchestrator, core `atividade_versao` schema, rebuild,
migration predicates/delegates, core triggers/indexes and requisicoes compatibility
block remain in `main.py`. Only the four-table leaf cluster, two transition triggers
and eight matching indexes are defined by three pure helpers in `app.db_maintenance`.
The separate `atividades` table is governed by recorded migration v2 and an isolated
early checkpoint; request processing no longer repairs its schema.

**Target:** later separately authorized units may establish one canonical init,
move remaining owners out of `main.py`, separate query behavior from schema
ensures, and make transaction ownership explicit. This document does not choose
or implement that redesign.

No target statement changes current behavior. No current statement endorses the
behavior as ideal.

## 12. Later owning phases

Each unresolved responsibility has one named future owner. These are planning
boundaries, not authorization:

| Unresolved responsibility | Explicit later owning unit |
|---|---|
| Access schema/default-data/startup normalization and savepoint semantics | **Resolved by PHASE 3-B6** |
| Application-settings schema | **Phase 3 application-settings ownership unit** |
| Backup-settings schema/default-data/legacy normalization/runtime application | **Resolved by PHASE 3-B7** |
| Cloud-account/log/drive schema and backup offloading | **Phase 5 backup-schema/offloading unit**, separately gated |
| `atividades` rebuild and FK PRAGMA semantics | **Resolved by PHASE 3-B9** |
| Activity-versioning leaf tables/transition triggers/leaf indexes | **Resolved by PHASE 3-B8** |
| Activity-versioning core schema, requisicoes compatibility and self-transactional rebuild | **Later Phase 3 activity-versioning core ownership unit** |
| Migration baseline expansion/version policy | **Partially resolved by PHASE 3-B9 through version 2; later migrations remain separately gated** |
| Matrix query that ensures schema | **Phase 3 matrix/repository boundary unit** |
| Logger/wiring lazy edge | **Final Phase 3 init wiring unit** |
| Dual direct core schemas, startup/seed/restore selection, and final commit ownership | **Final Phase 3 `init_db` cutover unit** |
| Main-defined admin-only lazy schemas not reachable from init | Their route/module extraction phases; not part of the init cutover until explicitly added |

B9 was separately authorized after B8 acceptance and changed only the versioned
`atividades` migration/checkpoint/bridge unit described above. No B10 implementation
is inferred or authorized.

## 13. Canonical-database safety rules

- Canonical path: repository-root `database.db`.
- Frozen identity for B5: SHA-256
  `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`,
  size `544768` bytes, `database.db-wal` absent, `database.db-shm` absent.
- Canonical SQLite opens in B5, B6, B7, B8 and B9: **exactly 0**.
- Contract tests are static or use pytest-owned paths. No contract test calls
  `sqlite3.connect`; existing schema helper tests use `:memory:` and release
  tests use `tmp_path`/session-owned external roots.
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
3. Explicit adjudication of whether the two init implementations still diverge.
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
- divergent does not mean equivalent;
- caller-owned does not include the savepoint, PRAGMA-sensitive, conditional
  self-transactional, or self-finalizing exceptions listed above;
- this contract is not authorization for B10, unrelated production code, another migration,
  restore, canonical SQLite access, or final cutover.

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
9. `tests/test_atividades_schema_migration_v2.py`
10. `tests/test_activity_versioning_leaf_schema_ownership.py`
11. `tests/test_backup_settings_ownership.py`
12. `tests/test_db_schema_maintenance.py`
13. `tests/test_phase3_schema_startup_transaction_contract.py`
14. `tests/test_ref_0c_b1_p0_access_context_transactions.py`

No fourth waiver path exists. Canonical `database.db` remains outside the manifest and
unopened as SQLite; the protected ignored residual remains outside the index. Publication
is intentionally recorded as pending at commit-tree time, and no future/self-referential
commit SHA is inserted into this commit. PHASE 3-B10 remains unauthorized.
