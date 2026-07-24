# Phase-0 Smoke Flow — Contract and Evidence

## Objective

Define and prove the five fixture-controlled hermetic smoke flows required by
the Phase-0 master plan. Each flow exercises one real application route, uses an
ephemeral SQLite database under a unique session-owned runtime root, and
asserts both functional behavior and output isolation.

## Baseline

- Repository: `genesismazeto-sys/SGAA`; workspace `D:\OneDrive\Programação\SGAA_clean_baseline`
- Starting HEAD: `c978ed7471e60f78151608cccafe95f21527553b`
- Parent unchanged; index/staging empty; R9 initial worktree contained only untracked `tests/test_phase_0_smoke_flows.py`
- No production code, schema, DB, dependency, or route was modified
- R9 introduced two evidence files: the smoke test module and this contract

## Scope — Exactly Five Flows

Each subsection below lists the actor, fixture prerequisites, request sequence,
expected response, database invariants, filesystem invariants, isolation
mechanism, the test that produces the evidence, and explicit exclusions.

---

### Flow 1 — `test_admin_login_flow`

| Attribute | Detail |
|-----------|--------|
| **Actor** | Admin user `admin_total@ej.edu.br` / `admin123` created by `smoke_env` fixture |
| **Fixture prerequisites** | `smoke_env`: `sub_root` under `PYTEST_RUNTIME_ROOT.resolve()`; ephemeral `test.db`; `init_db` ran; admin row inserted; `admin_id` captured and yielded |
| **Request sequence** | 1. `GET /login` → 200. 2. `POST /login` with email+senha, `follow_redirects=False`. 3. `GET /admin/dashboard` → 200 |
| **Expected response** | `POST` returns 302/303; `Location` == `/admin/dashboard`. Dashboard GET returns 200 |
| **Database invariants** | No mutation tested by this flow |
| **Filesystem invariants** | No filesystem mutation tested |
| **Isolation mechanism** | Unique `sub_root`; `DATABASE`/`app.config` redirected; teardown closes DB without `except` swallow |
| **Evidence test** | `test_admin_login_flow` in `tests/test_phase_0_smoke_flows.py` |
| **Explicit exclusions** | No direct session injection, no production credentials/data, no external service |

### Flow 2 — `test_aluno_login_flow`

| Attribute | Detail |
|-----------|--------|
| **Actor** | Aluno user with per-test email `aluno.{suffix}@teste.local` / `aluno123` |
| **Fixture prerequisites** | `smoke_env` plus: curso, turma, usuario (aluno, `nivel_acesso=usuario`), and alunos row inserted via `main.get_db_connection()` |
| **Request sequence** | 1. `POST /login` with aluno email+senha, `follow_redirects=False`. 2. `GET /aluno/dashboard` |
| **Expected response** | `POST` returns 302/303; `Location` == `/aluno/dashboard`. Dashboard GET returns 200 |
| **Database invariants** | No post-login database mutation invariant is asserted; the test seeds `cursos`, `turmas`, `usuarios`, `alunos` in fixture setup, then asserts login redirect and dashboard only |
| **Filesystem invariants** | Not tested |
| **Isolation mechanism** | Same `smoke_env`; seed data created inside `with main.app.app_context():` using the ephemeral connection |
| **Evidence test** | `test_aluno_login_flow` in `tests/test_phase_0_smoke_flows.py` |
| **Explicit exclusions** | No registration flow, no aluno profile display, no redirect chain beyond dashboard |

### Flow 3 — `test_criacao_requisicao_sem_anexo`

| Attribute | Detail |
|-----------|--------|
| **Actor** | Aluno user with per-test email `aluno.req.{suffix}@teste.local` / `aluno123`; at least one `atividades` row exists |
| **Fixture prerequisites** | `smoke_env` plus: curso, turma, atividade, usuario/aluno (via DB). `pre_count` and `pre_upload_inv`/`pre_docs_inv` captured before POST |
| **Request sequence** | 1. `POST /login` as aluno. 2. `POST /aluno/nova-requisicao` with `atividade_id`, `nome_evento`, `data_evento`, `horas_solicitadas`, `observacao` |
| **Expected response** | Both POST return 302/303 |
| **Database invariants** | `COUNT(*)` from `requisicoes` increases by exactly 1. The latest `requisicoes` row: `aluno_id` and `atividade_id` match seeded values; `status == 'Pendente'`; `horas_solicitadas == 8.0`; `horas_deferidas is None`; `admin_id is None`; `data_processamento is None`; `arquivo_comprovante is None`; `aluno_update_notified_at is None`; `aluno_update_seen_at is None`. `requisicao_arquivos` count for that req == 0 |
| **Filesystem invariants** | `_dir_inventory(upload_dir)` and `_dir_inventory(documents_dir)` captured before and after POST; both inventories are identical and both are empty `{}`. Inventory per file records `relpath`, `size`, `sha256` |
| **Isolation mechanism** | Same `smoke_env`; upload and documents dirs are under `sub_root` |
| **Evidence test** | `test_criacao_requisicao_sem_anexo` in `tests/test_phase_0_smoke_flows.py` |
| **Explicit exclusions** | No file upload/attachment; no admin processing; no email notification; no multi-step form |

### Flow 4 — `test_processamento_requisicao_pendente`

| Attribute | Detail |
|-----------|--------|
| **Actor** | Admin user `admin_total@ej.edu.br` (logged in via `POST /login`); the admin processes a pre-seeded pending requisicao |
| **Fixture prerequisites** | `smoke_env` yields `admin_id`. Test seeds curso, turma, atividade, usuario/aluno, and one `requisicoes` row with `status='Pendente'`, `horas_solicitadas=10`, `nome_evento='Evento Processar'` |
| **Request sequence** | 1. `POST /login` as admin. 2. `POST /admin/processar_requisicao/{req_id}` with `status='Deferida Parcialmente'`, `horas_deferidas='6'`, `observacao='Processado no teste'` |
| **Expected response** | Both POST return 302/303 |
| **Database invariants** | The processed `requisicoes` row: `status == 'Deferida Parcialmente'`; `horas_deferidas == 6.0`; `observacao == 'Processado no teste'`; `admin_id == admin_id` (exact value from fixture); `data_processamento is not None`; `aluno_update_notified_at is not None and == data_processamento`; `aluno_update_seen_at is None` |
| **Filesystem invariants** | Not tested |
| **Isolation mechanism** | Same `smoke_env`; admin_id is explicit in fixture tuple |
| **Evidence test** | `test_processamento_requisicao_pendente` in `tests/test_phase_0_smoke_flows.py` |
| **Explicit exclusions** | No deferimento total/indeferimento; no partial approval edge cases; no email trigger verification; no rollback testing |

### Flow 5 — `test_backup_local`

| Attribute | Detail |
|-----------|--------|
| **Actor** | Admin user `admin_total@ej.edu.br`; test configures `save_backup_settings` with `cloud_backup_dir=""`, `gdrive_enabled=0`, `onedrive_enabled=0` |
| **Fixture prerequisites** | `smoke_env` plus: marker `atividades` row (`marker_name`/`marker_id`); `call_log = []`; 7 spy functions registered |
| **Request sequence** | 1. `POST /login` as admin. 2. `POST /admin/banco-dados/backup` with `follow_redirects=False` |
| **Expected response** | POST returns 302/303; `Location` == `/admin/banco-dados` |
| **Database invariants** | Snapshot DB opened with `sqlite3.connect`; `SELECT id, nome FROM atividades WHERE id = ?` returns `id == marker_id` AND `nome == marker_name` |
| **Filesystem invariants** | `local_backup_dir / "snapshots"` exists and is a directory. Exactly 1 `.db` and 1 `.json` file. Manifest path (the `.json`) and `database_path` (from manifest content) both proven descendants of `local_backup_dir.resolve()` and `sub_root.resolve()` via `relative_to`. `os.path.exists(snapshot_db_path)` is True |
| **No-network spy** | `call_log` instruments 7 sinks: `main.maybe_sync_database_to_cloud`, `main.upload_snapshot_to_external_server`, `main._cd.refresh_google_if_needed`, `main._cd.refresh_onedrive_if_needed`, `main._cd.google_upload`, `main._cd.onedrive_upload`, `main._cd.apply_retention_to_drive`. All return safe results. Wrappers `_maybe_upload_to_drives` and `_maybe_sync_database_snapshot` are NOT replaced. After POST, `assert call_log == []` |
| **Isolation mechanism** | Same `smoke_env`; `CLOUD_BACKUP_DIR` set to `""` in both `save_backup_settings` payload and `app.config`; backup dir under `sub_root` |
| **Evidence test** | `test_backup_local` in `tests/test_phase_0_smoke_flows.py` |
| **Explicit exclusions** | No real cloud/network call; no remote retention; no external server upload; no restore flow; no backup rotation beyond the single snapshot |

## Commands and Results

| Command | Result |
|---------|--------|
| `./.venv/Scripts/python.exe -m pytest tests/test_phase_0_smoke_flows.py -q --tb=short` | `5 passed in 5.99s` |
| `./.venv/Scripts/python.exe -m pytest -q --tb=short` (full suite, accepted R9-R2) | `654 passed, 17 deselected in 298.82s (0:04:58)` |

### Directed gate results (all zero failures/errors)

| Sub-suite | Result |
|-----------|--------|
| Smoke | 5 passed in 5.99s |
| Auth | 9 passed in 8.41s |
| Requisicao | 25 passed in 22.37s |
| Local backup | 11 passed in 8.61s |
| Runtime isolation | 15 passed in 12.95s |
| REF-0C-D-R1 | 33 passed in 22.17s |
| RBAC | 53 passed in 22.11s |

## Accepted R9-R2 invariant set

| Path | Status |
|------|--------|
| `database.db` (project root) | 544768 bytes; SHA-256 `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`; unchanged |
| `uploads/` | Unchanged |
| `documentos_alunos/` | Unchanged |
| `backups/` | Unchanged |
| `logs/` | Unchanged |
| `.pytest_cache/` | Unchanged |
| Temp roots | Current-session owned root removed after execution; three older preexisting roots (`400m71o1`, `humxysw6`, `ty_dj_wz`) untouched |
| R9-R2 aggregate invariant hash | `e3d10dc0e8d782ab73acedd6737f285e37b4e21691218049ad8dc654f1ff3331` (before AND after accepted R9-R2 suite; includes the five frozen dirty files, canonical `database.db`/root manifests, all three preexisting temp-root manifests/set, Git status, and empty staging; not the final seven-path Git manifest) |

## Agents, Sessions, Fallback

- **Supervisor:** `openai-codex/gpt-5.6-sol` (high)
- **Diagnosis (read-only):** `ses_06e6be957ffefFhWJO2OaOcGNR` — read-only diagnosis, not a failed implementation; blocked on missing test-env preconditions, no file produced
- **First implementation (flash-free):** `ses_06e693a6affel7mGVS7rlSqWU2` — produced no file, rejected
- **Effective implementation (flash-normal):** `ses_06e678ee0ffexS48io7Qa8wZ9n` — selected after `FALLBACK_FREE_BUDGET_EXHAUSTED`; test implemented, accepted after correction
- **Independent review (flash-normal):** `ses_06e6170a5ffeBtfhHUtnUFCKaN` — found blocking gaps, rejected
- **Correction and partial documentation (flash-normal):** applied all eight fixes to the test. The partial documentation state originated from the immediately preceding failed R9 documentation attempt, which terminated before completing the canonical document set.
- **Final independent review (read-only, DeepSeek Pro):** `ses_06e4325e5ffeJVoaEKkeyIDV38` — provider `opencode-go`; model `opencode-go/deepseek-v4-pro`; cost 0.000880904; fallback_used false; fallback_trigger null; exit 0; passed true; no mutations; no findings; confirmed every required static contract
- **No Pro, Luna, or Sol implementation fallback**
- **Model (this session):** `opencode-go/deepseek-v4-flash`

## Production Changes

**None.** No production code, schema, migration, database, dependency, UI, route,
configuration, or environment file was created or modified. There are two new
files: `tests/test_phase_0_smoke_flows.py` (test) and
`docs/refactor/PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.md` (contract). Five
existing documents were updated: `AGENT_HANDOFF.md`, `PROJECT_STATE.md`,
`docs/DOCUMENTATION_INDEX.md`, `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`,
and `docs/mapeamento/05_avaliacao_refactor.md`.

## Final exact seven-path Git manifest

| Path | Status |
|------|--------|
| `tests/test_phase_0_smoke_flows.py` | New |
| `docs/refactor/PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.md` | New |
| `AGENT_HANDOFF.md` | Updated |
| `PROJECT_STATE.md` | Updated |
| `docs/DOCUMENTATION_INDEX.md` | Updated |
| `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` | Updated |
| `docs/mapeamento/05_avaliacao_refactor.md` | Updated |

These seven paths constitute the complete R9-R2 Git manifest. No other path is
included in the implementation/documentary commit.

## Five-path freeze facts (byte-identical across accepted R9-R2 suite)

| Path | Size | SHA-256 |
|------|------|---------|
| `tests/test_phase_0_smoke_flows.py` | 19433 | `517c449751ff24ba24a7757d8d3c0e815fc2e37eda524e8c8c17d6009ac4172d` |
| `AGENT_HANDOFF.md` | 110073 | `75f6c6443ca057b21039a3dab8827e8295642237efc4f8d49f3c949955e9498e` |
| `PROJECT_STATE.md` | 146161 | `68573ca7cd7fa70acb87df26fa4771019231b2aa163f0acec13856a9dafc599e` |
| `docs/DOCUMENTATION_INDEX.md` | 10308 | `bd87bbbd7c2693d1204e9e3fac8c13e403815d3d05190df0ada3964341c1996b` |
| `docs/refactor/PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.md` | 7093 | `4605705a177f1e4cb2bfb38a942512fe2e6b1f2dbacb6f093e2811a018986948` |

The freeze SHA values above are the initial states before doc reconciliation;
the current SHA values after this edit are the reconciled final states.

## Residual Risks

1. Smoke flows depend on route behavior remaining stable; any route change or
   middleware change may break them silently.
2. The `smoke_env` fixture patches a fixed set of `app.config` and module-level
   globals; a future refactor that changes the initialization path would require
   fixture maintenance.
3. Backup flow assumes `save_backup_settings` and `create_database_snapshot`
   continue returning the expected snapshot structure.
4. D73H was not executed (17 deselected, 0 executed in accepted command).
5. Fase 1 remains unauthorized. Production hard enforcement remains unauthorized.

## Next Step

**External supervisor review only.** R9 is IMPLEMENTED / LOCALLY VALIDATED.
Macro Phase 0 is LOCALLY SATISFIED / AWAITING EXTERNAL SUPERVISOR ACCEPTANCE.
Fase 1 and production hard enforcement remain unauthorized. Phase 0 must never
be claimed as CLOSED or ACCEPTED before external supervisor acceptance.
