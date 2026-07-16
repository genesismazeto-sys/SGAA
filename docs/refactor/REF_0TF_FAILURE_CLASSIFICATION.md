# REF-0TF — Full-suite failure classification

## Scope and starting state

- Read-only investigation on `refactor/architecture-safety-net`, initial HEAD `c440297` and `origin/main...HEAD = 0 2`.
- The primary workspace was clean. `database.db` is ignored by `.gitignore` (`*.db`) and was never opened, copied, or changed.
- Detached disposable worktree: `C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0tf-c440297`, at `c440297`. It had no `database.db`, `.env`, uploads, documents, backups, junction, or symlink to the primary workspace. It was removed after evidence capture.

## Files read

- `tests/conftest.py`, `pytest.ini`, `tests/test_aluno_progresso.py`, `app/views/aluno.py`, `tests/test_d73h_reconciliation_apply.py`, `tools/d73h_reconciliation_apply.py`, and `normative_fixtures/d73c_normative_fixture.yaml`.
- Relevant database/runtime setup in `main.py`, `app/__init__.py`, and `app/db.py`; D73H history in `PROJECT_STATE.md`, `AGENT_HANDOFF.md`, and Git commits `ecdc9f5` and `b8ad2ae`.

## Commands and reproduction

- `pytest tests/test_aluno_progresso.py::test_aluno_progresso_renderiza_catalogo_e_agrega_semestres -vv --tb=long` ran three times with fresh `tmp_path/aluno_progresso_test.db`: each exited `1` and returned `['2025/2', '2026/1', '2026/2']` (12.48 s, 2.51 s, and 3.45 s).
- `pytest tests/test_aluno_progresso.py -q --tb=short`: `1 failed, 2 passed`.
- `pytest tests/test_d73h_reconciliation_apply.py -q --tb=short` with no root database: `17 failed, 1 passed`; all 17 failures stop at the same missing-file boundary.
- A synthetic worktree-only `database.db` was created by setting `APP_DATABASE` to the temporary root and running the repository's `main.init_db()` mechanism. SHA-256 before and after the representative plan test was identical: `6D82B8ED4B0EAB9678FAFB9B84CC4B0CD82B7140A2B20D1B4E60EE053389CA12`.

## Cluster A — student progress semester expectation

Classification: **C — time-dependent test; B — stale/incorrect assertion.**

- Fixture line 268 inserts `data_evento='2026-09-10'` and labels it future; line 346 fixes the expected list at `['2025/2', '2026/1']`.
- `app/views/aluno.py::_build_aluno_progresso_payload` derives `semestre_atual` from `datetime.date.today()` and excludes only requests later than that semester. On 2026-07-16, 2026/2 is current, so 2026-09-10 belongs to the accepted semester and is correctly included.
- The test database is isolated per test through its `tmp_path` fixture; repeated runs are identical, so execution order/shared state is not involved.
- Git history/blame shows both fixture and assertion were introduced in `dea3de5` on 2026-05-29. No product rule was found that freezes visible semesters at 2026/1.

Conclusion: no application regression is evidenced. The assertion decays as calendar time advances. Minimum remediation is a test-only calendar-contract hardening phase: make the future fixture dynamically future relative to the test contract, or inject a deterministic clock through an existing seam. Risk is incorrectly changing the intended rule that excludes only future semesters; regression coverage must prove current semesters remain visible and later semesters remain excluded.

## Cluster B — D73H reconciliation apply tests

Classification: **G — intentional historical-data verification; D/E — non-hermetic dependency on ignored local database and missing repository fixture/setup contract.**

- `tests/test_d73h_reconciliation_apply.py` defines `ROOT` from `__file__`, then `REAL_DB_PATH = ROOT / 'database.db'` and optional `PRE_APPLY_BACKUP_PATH = ROOT / 'backups' / 'database.pre-d73j-live-apply-20260612-165031.db'`.
- `_resolve_pre_apply_source()` prefers that historical backup, otherwise falls back to root `database.db`; `_prepare_copy_and_backup()` copies it to `tmp_path`, and may remove the historical target from those copies. The test asserts historical norm IDs/codes `AAC-rev5` and `AAC-rev6`.
- The synthetic standard database proved this is not merely a missing schema: the plan command reached validation and failed `Required norm missing in database: AAC-rev5`. It remained byte-identical because plan is read-only.
- History shows `ecdc9f5` introduced the controlled D7.3H reconciliation script/test and `b8ad2ae` added the pre-apply backup/rewind assumption after the live operation. The test is post-operation acceptance evidence, not a clean-clone regression test.

Conclusion: all 17 failed nodes share the same unavailable historical-source boundary; no later independent behavior is observable until that boundary is supplied. They are not portable to a clean clone and do not belong in the standard full suite without a sanitized, versioned fixture. Do not use the primary database or its backup as a fixture.

## Complete failing nodes

1. `tests/test_aluno_progresso.py::test_aluno_progresso_renderiza_catalogo_e_agrega_semestres`
2. `tests/test_d73h_reconciliation_apply.py::test_plan_mode_does_not_alter_live_database_signature`
3. `tests/test_d73h_reconciliation_apply.py::test_plan_mode_json_reports_one_base_and_two_versions_planned`
4. `tests/test_d73h_reconciliation_apply.py::test_plan_mode_json_reports_already_exists_on_controlled_post_apply_copy`
5. `tests/test_d73h_reconciliation_apply.py::test_apply_refuses_without_backup_confirmed`
6. `tests/test_d73h_reconciliation_apply.py::test_apply_refuses_without_backup_path`
7. `tests/test_d73h_reconciliation_apply.py::test_apply_refuses_without_allow_create_flag`
8. `tests/test_d73h_reconciliation_apply.py::test_apply_refuses_live_db_and_forbidden_database_db_basename`
9. `tests/test_d73h_reconciliation_apply.py::test_apply_on_copy_creates_exactly_one_base_and_two_versions_and_reports_created_ids`
10. `tests/test_d73h_reconciliation_apply.py::test_apply_does_not_alter_norma_atividade`
11. `tests/test_d73h_reconciliation_apply.py::test_apply_does_not_alter_atividade_transicao`
12. `tests/test_d73h_reconciliation_apply.py::test_apply_does_not_alter_matriz_atividade_versao_item`
13. `tests/test_d73h_reconciliation_apply.py::test_apply_does_not_alter_requisicoes`
14. `tests/test_d73h_reconciliation_apply.py::test_apply_does_not_touch_runtime_nrm_rt_items`
15. `tests/test_d73h_reconciliation_apply.py::test_apply_json_report_contains_created_ids_and_final_counts`
16. `tests/test_d73h_reconciliation_apply.py::test_apply_is_idempotent_on_same_copy`
17. `tests/test_d73h_reconciliation_apply.py::test_apply_fails_if_existing_target_base_is_conflicting`
18. `tests/test_d73h_reconciliation_apply.py::test_apply_fails_if_fixture_is_missing_target_activity`

## Recommended authorized remediation phases

1. `REF-0TF-A — Progress Calendar Contract Hardening`: test-only remediation of the time-decaying fixture/assertion, with explicit current-versus-future semester contract tests.
2. `REF-0TF-B — D73H Historical Verification Isolation`: separate D73H from the default suite unless and until a sanitized, versioned, deterministic fixture and explicit invocation contract exist. It must not use the live database or untracked backups.
3. Only after both phases are accepted may the architect reconsider the RBAC diagnosis phase. RBAC remediation and modularization remain prohibited now.

## Risks and non-actions

- Calendar remediation can accidentally change product semantics if it freezes production time instead of only test data.
- D73H remediation can accidentally normalize live historical state into a fixture or expose sensitive data; fixture design needs separate approval.
- No application, test, UI, schema, dependency, database, or environment correction was implemented in this phase.
