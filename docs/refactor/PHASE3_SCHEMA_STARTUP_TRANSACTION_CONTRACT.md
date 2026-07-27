# Phase 3 schema, startup, and transaction contract

**Status:** PHASE 3-B7 intentional revision of the accepted PHASE 3-B5/B6 contract
**Phase status:** B5/B5-R1/B6 CLOSED / ACCEPTED; B7 IMPLEMENTED / LOCALLY VERIFIED / AWAITING EXTERNAL SUPERVISOR REVIEW
**B7 baseline:** `b328789f16cc4db0173e58d2d2454902565d0610` (`Separate access schema from normalization`)
**Executable contract:** `tests/test_phase3_schema_startup_transaction_contract.py`

## 1. Scope and purpose

This document freezes the accepted behavior that exists before the final Phase 3
cutover. B7 intentionally revises only backup-settings structural/runtime ownership,
its semantic split, the matching lazy edge, and the affected transaction/runtime-side-effect matrix. It remains a review and
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

- `app.db._init_db_impl` obtains four dependencies through the lazy bridge,
  directly invokes `ensure_usuario_access_schema` and `ensure_reportes_table`, invokes
  `ensure_atividades_schema_current`, includes `cursos.total_horas_aac` and
  `cursos.total_horas_aeu`, reconciles `turmas.matriz_id`, and then commits.
- `main.init_db` owns its own monolithic table/ALTER sequence, invokes
  `ensure_app_settings_schema`, `ensure_cloud_backup_schema`, and
  `ensure_turmas_matriz_schema`, adds legacy `atividades.documentos_json`, does
  not call `ensure_reportes_table` or `ensure_atividades_schema_current`, and
  then commits.
- Both call migration metadata at the end and both finalize the shared Flask
  connection. A caller that already has pending work on that connection would
  have that work committed too; this is frozen current behavior, not a target.

## 4. Exact caller inventory

The executable manifest identifies call expressions by tracked path and lexical
scope rather than by brittle line number. At this baseline there are **73** calls
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
3. Retrieve, in exact order: `ensure_atividades_schema_current`,
   `ensure_atividade_versioning_schema`, `get_preferred_matriz_for_curso`, `logger`.
4. Obtain `conn` from `get_db_connection`.
5. Create `usuarios`; best-effort email index.
6. Call direct `ensure_usuario_access_schema`.
7. Call direct `ensure_usuario_profile_schema`.
8. Call direct `ensure_backup_settings_schema` from `app.backup_settings`.
9. Create `alunos`; best-effort indexes.
10. Create `turmas`; best-effort status index.
11. Create `atividades`.
12. Create `requisicoes`.
13. Create `requisicao_arquivos`; best-effort requisition/file indexes.
14. Call direct `ensure_reportes_table`.
15. Read bootstrap-admin settings and conditionally insert the admin.
16. Attempt the six legacy `atividades` column additions, in order:
    `tipo_atividade`, `tem_limitacao`, `tipo_limitacao`, `limite_horas_total`,
    `limite_horas_semestral`, `descricao`.
17. Normalize empty/null `atividades.tipo_atividade`.
18. Call lazy `ensure_atividades_schema_current`.
19. Conditionally add `alunos.turma_id` plus index.
20. Conditionally add `alunos.foto_perfil`.
21. Conditionally add `requisicoes.nome_evento`.
22. Conditionally add `requisicoes.aluno_update_notified_at`.
23. Conditionally add `requisicoes.aluno_update_seen_at`.
24. Best-effort create `idx_reqs_aluno_update_pending`.
25. Call direct `ensure_requisicao_alert_receipts_table`.
26. Conditionally add `turmas.numero`.
27. Create `cursos` with AAC/AEU totals.
28. Conditionally add `cursos.periodo`, `total_horas_aac`, and
    `total_horas_aeu`; normalize invalid/null totals.
29. Seed `GERAL` only when no course exists.
30. Call direct `ensure_matrizes_atividades_table`.
31. Call direct `ensure_matriz_atividade_links_table`.
32. Call lazy `ensure_atividade_versioning_schema`.
33. Attempt the five `turmas` additions, in order: `curso_id`, `ano_inicio`,
    `semestre_inicio`, `codigo`, `matriz_id`.
34. Conditionally add `ano_fim`, then `semestre_fim`.
35. Create course/matrix indexes and best-effort unique turma indexes.
36. Reconcile old turmas: assign `GERAL`, sequential numbers, and generated
    codes with collision fallback.
37. Reconcile missing `turmas.matriz_id` through lazy
    `get_preferred_matriz_for_curso`.
38. Call direct `apply_schema_migrations(conn, logger=logger)`.
39. Execute the one expected final `conn.commit()`.

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
| `ensure_schema_migrations_table`, `_migration_v1_baseline`, `apply_schema_migrations`, `SCHEMA_VERSION`, `SCHEMA_MIGRATIONS` | `app/db_maintenance.py` | Migration metadata and application owner. |
| `ensure_usuario_access_structural_schema` | `app/db_maintenance.py` | Pure access DDL owner; no default-data, normalization, savepoint, commit, or rollback. |
| `seed_usuario_access_default_data` | `app/db_maintenance.py` | Historical five-row `INSERT OR IGNORE` owner; reuses `app.auth.DEFAULT_ACCESS_PASSWORDS`; no DDL. |
| `normalize_usuario_access_startup_data` | `app/db_maintenance.py` | Startup-wide accepted access normalization owner; reuses `app.auth.default_access_level_for_user_type`; no DDL. |
| `ensure_usuario_access_schema` | `app/db_maintenance.py` | Public compatibility orchestrator and sole owner of the access savepoint. `main` and `app.db` are direct compatibility exports. |
| `ensure_backup_settings_structural_schema` | `app/db_maintenance.py` | Pure owner of `configuracoes_backup` CREATE TABLE; no Flask config, DML, read/merge, transaction control, directory or external effect. |
| `bind_backup_settings_runtime_app`, `_backup_settings_defaults`, `seed_backup_settings_default_data`, `normalize_legacy_backup_sync_interval`, `read_backup_settings`, `_apply_backup_settings_to_app`, `get_backup_settings`, `ensure_backup_settings_schema` | `app/backup_settings.py` | Sole owners of the explicit legacy runtime-app binding, runtime-derived defaults, historical six-row seeding, exact stripped `"300"` normalization, persisted read/merge, six Flask config effects and ordered startup orchestration. `main` binds its exact module-level `app` after configuring the six values and compatibility-exports the four historical names; `app.db` directly imports the orchestrator. |
| `ensure_app_settings_schema` | `main.py` | Application-settings schema owner, reachable from `main.init_db` only. |
| `ensure_cloud_backup_schema` | `main.py` | Adjacent cloud schema owner for `cloud_accounts`, `backup_logs`, and `cloud_drive_settings`; unchanged and isolated from B7. |
| `ensure_atividades_schema_current` | `main.py` | Legacy activity-table rebuild owner and PRAGMA-sensitive path. |
| `_recreate_atividade_versao`, `_migrate_atividade_versao_to_numero_versao`, `_fix_atividade_versao_default`, `ensure_atividade_versioning_schema` | `main.py` | Activity-versioning schema owners; may cross a self-managed transaction. |
| `ensure_turmas_matriz_schema` | `main.py` | Remaining turma/matrix schema owner; delegates accepted matrix owner. |
| `_needs_atividade_versao_migration`, `_needs_atividade_versao_default_fix`, `_needs_index_hardening` | `main.py` | Schema-state predicates, not defining owners. |
| `get_preferred_matriz_for_curso` | `main.py` | Query/runtime behavior rather than defining ownership, but it invokes the matrix ensure and can therefore cause caller-owned schema work. |
| `_get_main_db_helpers` | `app/db.py` | Compatibility/lazy wiring only, not schema ownership. |
| `DATABASE`, `get_db_connection`, `close_db_connection` exports in `main.py` | `app.db` objects | Compatibility exports only, not defining ownership. |

`ensure_admin_arquivos_table` and `ensure_admin_alertas_table` remain defined by
`main.py`, but they are not reachable from either current `init_db` path and are
therefore outside this init reachability matrix.

## 7. Remaining lazy-bridge matrix

The exact four entries and matching `_init_db_impl` retrievals are frozen in this
order:

| Order | Lazy key | Current source object | Matching local retrieval | Role |
|---:|---|---|---|---|
| 1 | `ensure_atividades_schema_current` | `main.ensure_atividades_schema_current` | same-name local | Schema rebuild |
| 2 | `ensure_atividade_versioning_schema` | `main.ensure_atividade_versioning_schema` | same-name local | Versioning schema |
| 3 | `get_preferred_matriz_for_curso` | `main.get_preferred_matriz_for_curso` | same-name local | Query/runtime with lazy schema side effect |
| 4 | `logger` | `main.logger` | same-name local | Warning/migration logging |

B7 removed only the backup-settings key and matching retrieval; it added no lazy key and
retained the exact relative order above. `app.db` directly imports only
`ensure_backup_settings_schema` from `app.backup_settings`. The exact direct
`app.db_maintenance` import set remains:
`apply_schema_migrations`, `ensure_matriz_atividade_links_table`,
`ensure_matrizes_atividades_table`, `ensure_reportes_table`,
`ensure_requisicao_alert_receipts_table`, `ensure_usuario_access_schema`, and
`ensure_usuario_profile_schema`.

## 8. Migration baseline

- `SCHEMA_VERSION == 1`.
- `SCHEMA_MIGRATIONS` contains exactly one ordered item:
  `(1, "baseline_schema_management", _migration_v1_baseline)`.
- Migration v1 is a **historical baseline marker**. Its function body is only a
  docstring; the current physical schema is still produced by the two bootstrap
  bodies and their reachable helpers. The baseline migration is not a complete
  physical-schema definition.
- `schema_migrations` columns are `version INTEGER PRIMARY KEY`,
  `name TEXT NOT NULL`, `applied_at TEXT NOT NULL DEFAULT (datetime('now'))`,
  and nullable `details_json`.
- `apply_schema_migrations` ensures the metadata table, reads recorded versions
  into a set, iterates the ordered tuple, calls each missing migration, inserts
  its metadata, logs when a logger exists, sets `PRAGMA user_version` to
  `SCHEMA_VERSION`, and returns status.
- It performs no commit, rollback, savepoint, or `executescript`; both current
  init implementations own the final commit.

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
| `ensure_atividades_schema_current` | none | none | none | none | `OFF`, then `ON` in `finally` | Effective PRAGMA toggling assumes a connection state in which SQLite accepts it; code does not enforce this precondition | Rebuild DDL/DML may be caller-rollbackable, but PRAGMA is connection state and not proof of transaction ownership | PRAGMA-sensitive rebuild exception |
| `_recreate_atividade_versao` | SQL `COMMIT` | no explicit SQL rollback | none | one `executescript` containing `PRAGMA OFF; BEGIN; ... COMMIT; PRAGMA ON` | `OFF`/`ON` | Must not be treated as a neutral nested helper | Caller rollback cannot undo the completed internal commit | Self-transactional exception |
| `_migrate_atividade_versao_to_numero_versao`, `_fix_atividade_versao_default` | indirect | indirect | none | each delegates once to `_recreate_atividade_versao` | indirect | Same conditional constraint as delegate | Same as delegate when branch executes | Delegated self-transactional exception |
| `ensure_atividade_versioning_schema` | none directly | none directly | none | conditionally invokes either self-transactional delegate | indirect | Caller-owned only when no rebuild branch runs | Caller rollback covers direct additive DDL, not a completed rebuild delegate | Conditional self-transactional exception |

The accepted caller-owned direct schema helpers are:
`ensure_reportes_table`, `ensure_usuario_profile_schema`,
`ensure_requisicao_alert_receipts_table`,
`ensure_matrizes_atividades_table`, and
`ensure_matriz_atividade_links_table`. The savepoint-owned direct import is
`ensure_usuario_access_schema`; `apply_schema_migrations` is listed separately
as migration metadata.

## 10. Known exceptions and technical debt

1. Two active init bodies duplicate and diverge.
2. Both init owners commit the shared Flask connection and may finalize unrelated
   pending caller work.
3. The access helper has savepoint-dependent clean-vs-nested durability.
4. `ensure_atividades_schema_current` changes `PRAGMA foreign_keys` around a
   rebuild without enforcing a transaction-state precondition.
5. Activity-version migration/default-fix branches call a self-transactional
   `executescript` and cannot be classified as caller-owned.
6. `get_preferred_matriz_for_curso` is named as a query but lazily ensures matrix
   schema.
7. The restore flow reinitializes the restored database through `main.init_db`,
   not `app.db.init_db`.
8. Development startup uses `main.init_db`; demo seeding uses `app.db.init_db`.
9. Logger warnings can hide best-effort ALTER/index/reconciliation failures; a
   warning is not schema postcondition evidence.
10. The v1 migration marker records a baseline rather than constructing the
    complete physical schema.

## 11. Current versus target architecture

**Current:** the exact dual-init, four-entry lazy bridge, compatibility exports,
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
| `atividades` rebuild and FK PRAGMA semantics | **Phase 3 activity-rebuild unit** |
| Activity-versioning additive schema and self-transactional rebuild | **Phase 3 activity-versioning ownership unit** |
| Migration baseline expansion/version policy | **Phase 3 migration-metadata unit** |
| Matrix query that ensures schema | **Phase 3 matrix/repository boundary unit** |
| Logger/wiring lazy edge | **Final Phase 3 init wiring unit** |
| Dual direct core schemas, startup/seed/restore selection, and final commit ownership | **Final Phase 3 `init_db` cutover unit** |
| Main-defined admin-only lazy schemas not reachable from init | Their route/module extraction phases; not part of the init cutover until explicitly added |

B7 was separately authorized after B6 acceptance and changed only the backup-settings
unit described above. No B8 implementation is inferred or authorized.

## 13. Canonical-database safety rules

- Canonical path: repository-root `database.db`.
- Frozen identity for B5: SHA-256
  `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`,
  size `544768` bytes, `database.db-wal` absent, `database.db-shm` absent.
- Canonical SQLite opens in B5, B6 and B7: **exactly 0**.
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
- this contract is not authorization for B8, unrelated production code, migration,
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
acceptance remains pending. PHASE 3-B8 remains unauthorized.
