## Current authoritative state — Architecture refactor Phase 1: CLOSED / ACCEPTED — R1 CLOSED / ACCEPTED — R2 CLOSED / ACCEPTED — R3 CLOSED / ACCEPTED — Historical snapshot custody: OPEN / POLICY APPROVED / CANONICAL_DESTINATION_SELECTED / PROVISIONING_AND_COPY_CONTRACT_APPROVED / DESTINATION NOT YET PROVISIONED / PHYSICAL EXECUTION NOT AUTHORIZED AT THIS TIME (2026-07-25)

- **PHASE-1-U1:** CLOSED / ACCEPTED.
- **Accepted commit:** 68f52fb902c726cc79ff92955e58f95ac0b21cd7 — `Remove accidental VS Code workspace artifact`.
- **Deleted artifact:** `templates/src.code-workspace-1.code-workspace` — 61 bytes, SHA-1 `bab1b7f616b360395e747dbbcd59ebadc307ad61`. It had no runtime, scanner, test, tool, or workflow consumer.
- **Validation evidence:** Full hermetic suite 654 passed, 17 deselected, 0 failed, 0 errors, D73H executed 0. Focused gate 7 passed. Previously failing runtime-isolation nodes 2 passed. Staged-deletion validation was required because `tests/test_pytest_runtime_isolation.py` copies `git ls-files`.
- **Database, historical snapshots, and runtime manifests:** Unchanged.
- **PHASE-1-U2:** CLOSED / ACCEPTED.
- **Accepted commit:** 5932dff2d6dbd63e4a1f52ffd649ea33577535d0 — `Remove obsolete machine-specific turma template`.
- **Parent:** c90223190eb662747978c9ff5a4a50b8e7f62ed6 — `Record acceptance of Phase 1 U1`.
- **Deleted path:** `templates/admin_turmas-KRThinkpad.html`.
- **Git blob SHA-1:** 96ae069833834da2941ea127968157bc9420e2e0.
- **Raw Git blob size:** 2114 bytes.
- **Correct raw Git blob SHA-256:** 01f32a5d9ed96754158206e47338ddbf18f35d4841432a2ddda59c7fa90be77d.
- **Correct normalized catalog SHA-256:** ae408075905e131490627b6a8e3bf262d74330d0ed9f7671fbc4b765fb52c7a4; 188681 normalized JSON bytes; 73 effective inputs; 536 catalog keys.
- **Exact zero catalog delta:** removed keys 0, added keys 0, removed usages 0, added usages 0, changed kinds 0, changed default texts 0.
- **Scanner exclusion:** remains via krthinkpad; candidate absent from effective inputs.
- **Zero runtime consumers;** zero Python, JavaScript, Jinja, test, tool, release, configuration, or workflow consumers; zero dynamic template-resolution paths; active route continues to render `admin_turmas.html`; zero Jinja edges to the removed file; scanner excluded the candidate through `krthinkpad`.
- **All 70 remaining tracked templates compiled:** active admin_turmas.html compiled.
- **Runtime-isolation copy gate:** 2 passed in 11.56s, 0 failed/errors.
- **Focused U2 lane:** 45 passed in 24.03s, no failures/errors/skips/deselections.
- **Full hermetic suite:** 654 passed, 17 deselected in 351.62s, 0 failures/errors, D73H executed 0.
- **Fresh physical invariant aggregate SHA-256:** a485690ddda0fcaf5a398e14a485dfe34611ee7f24c64444078acd1cd6879775 was identical before and after every lane; database.db, all nine database.pre-*.db snapshots, uploads/, documentos_alunos/, backups/, logs/, .pytest_cache, the three preexisting sgaa_pytest_runtime_* roots, Git staged deletion, empty unstaged diff, and zero untracked paths were preserved; no canonical database was opened or queried.
- **The two previous literal mismatches** (raw blob identity order value and normalized catalog hash order value) were corrected order-data errors, not repository drift; only corrected values are preserved as active canon.
- **PHASE-1-U3:** CLOSED / ACCEPTED.
- **Accepted technical commit:** c4fd2dd1852011a0ec860493ed4cf53834584c42 — `Remove legacy aluno route bodies`.
- **Removed symbols from main.py:** `_noop_route`; assignment to `aluno_runtime_route`; `aluno_arquivos`; `aluno_minhas_requisicoes`; `aluno_requisicao_detalhe`; `aluno_dashboard`; `aluno_nova_requisicao`; `aluno_meus_dados`.
- **main.py delta:** 0 insertions, 756 deletions.
- **Preserved compatibility boundary:** `USE_ALUNO_BLUEPRINT = True`; `app = create_app(register_aluno_blueprint=USE_ALUNO_BLUEPRINT)`; `aluno_url`; `_rebind_legacy_aluno_exports`; its invocation; all eight compatibility exports; all active implementations in `app/views/aluno.py`. Required eight exports: `aluno_dashboard`, `aluno_meus_dados`, `aluno_nova_requisicao`, `aluno_minhas_requisicoes`, `aluno_requisicao_detalhe`, `aluno_arquivos`, `aluno_visualizar_arquivo`, `aluno_baixar_arquivo`. All eight remain identical to their active `app.views.aluno` callables in object identity, name, module and signature.
- **Route/URL acceptance:** total Flask rules 131; aluno bindings 11; routes removed 0; routes added 0; endpoint delta 0; method delta 0; host delta 0; subdomain delta 0; redirect delta 0; strict-slashes delta 0. Accepted URL neutrality for `/aluno/dashboard`, `/aluno/meus_dados`, `/aluno/nova_requisicao`, `/aluno/requisicoes`, `/aluno/requisicoes/17`, `/aluno/arquivos`, `/aluno/arquivos/ver/23`, `/aluno/arquivos/download/23`. For each relevant endpoint, `url_for("aluno.<name>") == main.aluno_url(name)`.
- **Message-catalog acceptance:** catalog keys 536; removed keys 0; added keys 0; changed defaults 0; changed kinds 0; semantic usages removed exactly 23; semantic usages added 0; affected keys exactly 18; orphaned overrides 0. Removed-usage distribution: aluno_requisicao_detalhe 10; aluno_meus_dados 6; aluno_nova_requisicao 4; aluno_dashboard 2; aluno_minhas_requisicoes 1; aluno_arquivos 0. Every affected message key remains present through active code or another active source. Forensic relocation: 4 retained usages: -6 lines; 198 retained usages: -430 lines; 142 retained usages: -756 lines; 421 retained usages unchanged. Source-line relocation is not a behavioral change.
- **CSRF snapshots:** both snapshots (`tests/_artifacts/csrf_inventory_shadow_off.json` and `tests/_artifacts/csrf_inventory_shadow_on.json`) regenerated through canonical `--update-csrf-snapshots` and adopted as one coherent pair. Raw SHA-256 for each: ab40107b840eabcc566f678662c813e33cccc0201adfdea7e37b3e37d8a23f8c. Mutable routes 78; endpoint identities 77; high-risk 0; blocked-risk 0; rendered templates 19; route records 78; form records 592; evidence records 628; route/status mappings unchanged; methods unchanged; decorators unchanged; token modes unchanged; test references unchanged; prohibited semantic deltas 0. Byte changes were ordering-only under normalized semantic comparison.
- **Tests/invariants:** new `tests/test_aluno_compat_exports.py` with three tests: (1) legacy bodies and no-op registration absent; (2) main compatibility exports match active blueprint; (3) rebind idempotent and URLs stable. Compatibility-only recheck 3 passed. Focused lane 47 passed, 0 failed, 0 errors, 0 skips, 0 deselected. Full hermetic suite 657 passed, 17 deselected, 0 failed, 0 errors, D73H executed 0. Invariants: aggregate physical/Git hash unchanged around focused and full lanes; `database.db` unchanged; all nine `database.pre-*.db` snapshots unchanged; uploads unchanged; `documentos_alunos` unchanged; backups unchanged; logs unchanged; `.pytest_cache` unchanged; preexisting pytest runtime roots unchanged; no execution-owned runtime root survived; no canonical database opened or queried.
- **U1 remains CLOSED / ACCEPTED.**
- **U2 remains CLOSED / ACCEPTED.**
- **U3 is CLOSED / ACCEPTED.**
- **PHASE-1-U6: CLOSED / ACCEPTED.** Read-only, no implementation, no tests, no commit, no physical mutation.
- **Phase 1: CLOSED / ACCEPTED.**
  Classification: PHASE1_CLOSABLE_WITH_SEPARATE_CUSTODY_TRACK.
  U6 confirmed no other safe cleanup bounded candidate has material evidence.
  Phase 1 leaves no partial technical implementation.
  Snapshots are not a mandatory technical closeout criterion.
  Custody transferred without physical action to autonomous administrative track.
- **Historical snapshot custody: OPEN / POLICY APPROVED / CANONICAL_DESTINATION_SELECTED / DESTINATION NOT YET PROVISIONED / PHYSICAL ACTION NOT AUTHORIZED.**
  Separate governance/administrative track. Does not integrate Phase 1, Phase 2,
  or any architectural implementation phase.
  See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.
- **HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R1: CLOSED / ACCEPTED.** Custody policy: APPROVED.
- **HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R2: CLOSED / ACCEPTED.**
  R30: DESTINATION_OPTIONS_READY_AWAITING_HUMAN_SELECTION / SUPERSEDED BY HUMAN SELECTION.
  Human-selected canonical destination: `D:\programas\SGAA_Historical_Custody`.
  Destination status: SELECTED.
  Destination class: DEDICATED DIRECTORY OUTSIDE REPOSITORY AND ONEDRIVE.
  Physical volume: SAME VOLUME AS SOURCE WORKSPACE — D:.
  Provisioning status: SELECTED / PARENT PATH NOT YET PROVISIONED. Read-only Gate A
  confirmed that neither `D:\programas` nor `D:\programas\SGAA_Historical_Custody`
  exists; the path lies outside every SGAA Git worktree, outside the OneDrive tree,
  outside `SGAA_database_backups`, and outside the pytest roots; zero name conflicts
  with the 17 artifacts; free space 497,651,699,712 bytes against 4,808,704 bytes
  required; longest projected path 98 characters. Nothing was created and no write
  test was performed.
  Storage-domain risk: the destination is outside the repository and outside the
  observed OneDrive tree, but remains on the same physical D: storage domain as the
  source workspace. This provides logical separation, not independent-disk redundancy.
  It must not be represented as redundant, immutable, off-site, independent of the
  source disk, versioned, or protected against deletion.
  Controlled-copy contract Gates 0–6 ratified documentally; none executed.
  Preferred disposable restoration environment: ISOLATED CONTAINER binding only a
  derived disposable copy; the source workspace must not be mounted as the restoration
  database; the custodial artifact must not be opened directly. Preference only.
  Physical action: NOT AUTHORIZED. Copy: NOT AUTHORIZED. Move: NOT AUTHORIZED.
  Delete: NOT AUTHORIZED. Compress: NOT AUTHORIZED. SQLite open: NOT AUTHORIZED.
  Phase 2–6: UNAUTHORIZED.
- **HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R3: CLOSED / ACCEPTED.**
  R3 was read-only: nothing created, nothing copied, no ACL applied, no SQLite opened.
  Phase-time classification `COPY_EXECUTION_CONTRACT_READY_AWAITING_HUMAN_AUTHORIZATION`,
  now SUPERSEDED BY HUMAN APPROVAL.
  Active classification: PROVISIONING_AND_COPY_CONTRACT_APPROVED / DESTINATION NOT YET
  PROVISIONED / PHYSICAL EXECUTION NOT AUTHORIZED AT THIS TIME.
  Human approval date: 25/07/2026.
  Approved layout: `artifacts\` (17 artifacts), `manifests\` (custody manifest JSON),
  `evidence\` (copy and verification reports). Longest projected path 108 characters
  against the 260 limit; `LongPathsEnabled = 0`.
  Approved technical executor: `KR-IDEAPAD\klebe`
  (SID `S-1-5-21-1500819853-3011909004-3032907821-1001`).
  Approved ACL: inheritance disabled on the custodial directory; `Authenticated Users`
  and `BUILTIN\Users` removed; `SYSTEM` and `Administrators` FullControl; executor
  Modify during provisioning and copy; after verification, executor ReadAndExecute on
  `artifacts\` and Modify on `manifests\` and `evidence\`. The ACL is mandatory because
  `D:\` carries `ContainerInherit, ObjectInherit` ACEs granting `Authenticated Users`
  effective modify rights; default inheritance would leave the custody writable and
  deletable by any authenticated user. An ACL is not immutability.
  Approved copy contract: copy-only; explicit list of the 17 paths; open glob prohibited;
  overwrite prohibited; exact names preserved; `.db`/`.db-wal`/`.db-shm` preserved
  jointly; stop at first error; no SQLite open; source never modified; mechanism
  equivalent to `File.Copy(source, destination, overwrite: false)`.
  Approved manifest: JSON with `manifest_version`, `created_at_utc`, `project`,
  `source_workspace`, `destination_root`, `authorized_by`, `executed_by`,
  `policy_commit`, `copy_contract_version`, `artifact_count`, `total_bytes`,
  `artifacts[]`; no credentials, tokens, SQLite content, business data or PII.
  Approved partial-failure policy: origin never modified; partial residue preserved
  until an explicit cleanup decision; automatic cleanup and silent retry NOT AUTHORIZED.
  Level 2 restoration environment: `CONTAINER_RUNTIME_NOT_AVAILABLE` observed read-only
  (`docker` absent from PATH, no install path, service not installed). Approved
  provisional alternative: controlled external directory `D:\tmp\sgaa_restore_<UTC>`,
  disposable, binding only a copy derived from `artifacts\`; the source workspace must
  never be mounted as restoration database; `artifacts\` must never be opened directly.
  ISOLATED CONTAINER returns as preferred if a runtime is installed.
  Source inventory revalidated read-only in R3: 17/17 present, 4,808,704 bytes,
  9 `.db` + 4 `.db-wal` + 4 `.db-shm`, all SHA-256 identical to canon, all ignored and
  untracked, 4 complete basename families plus 5 lone `.db`. Zero drift.
  Destination revalidated read-only: neither `D:\programas` nor
  `D:\programas\SGAA_Historical_Custody` exists; no resolution to `D:\Programação`;
  outside every Git worktree, outside OneDrive, outside the pytest roots; zero conflicts.
  **PHYSICAL EXECUTION NOT AUTHORIZED AT THIS TIME — withheld in the same human decision
  that approved the contract.** Move, delete, compress, SQLite open, restoration
  execution, source removal and Phase 2–6 remain PROHIBITED.
- **Preserved historical/superseded — pre-R3 wording:** statements that R3 was "NOT STARTED",
  "requires a separate explicit order", that the provisioning and copy contract was undrafted
  or pending, and the R3 phase-time state `COPY_EXECUTION_CONTRACT_READY_AWAITING_HUMAN_AUTHORIZATION`
  are superseded by this closeout and preserved in historical blocks only as historical record.
- **Preserved historical/superseded — pre-R2 wording:** statements that R2 was "NOT STARTED", that the specific canonical destination was "UNRESOLVED" or "NOT YET SELECTED", and the R30 state `DESTINATION_OPTIONS_READY_AWAITING_HUMAN_SELECTION` are superseded by this closeout and preserved in historical blocks only as historical record.
- **PHASE-1-U4:** CLOSED / ACCEPTED.
- **U4 read-only proof:** CLOSED / ACCEPTED.
- **U4-B bounded implementation:** CLOSED / ACCEPTED.
- **Accepted technical commit:** 742b67c0623bdf41e292280a11a40d2fddad717c — `Remove unused main imports`.
- **File changed:** `main.py` only; delta 2 insertions, 4 deletions.
- **Removed imports:** `wraps` (from `functools`), `Flask` (from `flask`), `bp_presets` (from `presets_api`).
- **Preserved:** `hashlib` — import retained; comment corrected to reflect compatibility with legacy salted SHA-256 hashes. Local `msal` probe import preserved.
- **No behavioral change:** zero routes, decorators, exports, blueprints, or authentication behavior changed.
- **Validation evidence:** AST confirmed only those three bindings removed; indirect consumers zero; hermetic import-time PASS; SQLite connections during import zero; `tests/test_aluno_compat_exports.py` 3 passed; route inventory plus RBAC coverage 3 passed; full suite 657 passed, 17 deselected, zero failed/errors; D73H executed zero; snapshots regenerated: zero; protected databases and roots unchanged.
- **U3 made no import unused.** All three removed imports were preexisting dead bindings predating U3. The hashlib comment correction and local msal probe preservation were included in the same bounded unit.
- **R21 routing:** original logical route flash_free; native fallback flash_normal; cause FALLBACK_FREE_EXECUTION_FAILURE; effective model opencode-go/deepseek-v4-flash; session ses_0699201ebffep2uXFswB6iotIf; cost 0.000425292; fallback explicit, not silent.
- **PHASE-1-U5:** CLOSED / ACCEPTED.
- **U5 read-only reconciliation:** CLOSED / ACCEPTED.
- **U5-B bounded implementation:** CLOSED / ACCEPTED.
- **Accepted technical commit:** 8b55230314605dcf9295072c109f04bea59323c3 — `Remove stale diagnostic output`.
- **Sole technical path:** `tools/diag_out.txt`.
- **Path nature:** tracked, passive, obsolete diagnostic artifact.
- **Original Git blob SHA-1:** 45f5fc833364e9d2bc49132b4a0f6a0b045be74e.
- **Original raw size:** 11,746 bytes.
- **Raw SHA-256:** f5e027ea7748b4246f224545e399b9014f74a5536e867bbe47e0b65eafcc534b.
- **No functional consumer found; Git history preserves recovery.**
- **No code, tests, database, or behavior changed.**
- **Accepted technical evidence:**
  - Staged deletion occurred before tests.
  - `git ls-files` no longer included `tools/diag_out.txt` during the lanes.
  - Focused isolation gate: 15 passed.
  - Full suite: 657 passed, 17 deselected.
  - Failures/errors: zero.
  - D73H executed: zero.
  - Snapshots regenerated: zero.
  - Protected databases and sidecars unchanged.
  - No canonical database opened.
  - No R24 root survived.
  - Publication incident: Initial publication: BLOCKED_PUSH_TIMEOUT; Recovery: PUBLICATION_COMPLETE.
  - The timeout is not a technical patch failure.
- **Nonconformities (recorded succinctly):**
  - First lane used an interpreter without dependencies and was rejected.
  - Unauthorized pip install attempts installed no packages.
  - Unauthorized git hash-object -w attempt produced no object.
  - First full-suite run timed out and was replaced by an approved complete execution.
  - Initial push timed out.
  - Recovery used foreground PTY without bypassing Git Credential Manager.
  - None caused any additional repository change.
  - None is an authorized precedent.
- **Phases 2-6 remain unauthorized.**
- **Production remains shadow-only; production hard enforcement remains unauthorized.**
- **R20 and D73H remain unchanged.**
- **Not authorized:** database snapshot deletion; Referrer-Policy changes; Phase 2 work.
- **Preserved historical/superseded — pre-U3 wording:** statements that U3 was "NOT STARTED / REQUIRES SEPARATE ORDER", "awaiting separate implementation order", "awaiting original read-only proof", "awaiting external acceptance", or "only locally validated" are superseded by this closeout. Such claims in historical blocks below are preserved only as historical record.
- **Preserved historical/superseded — pre-U4 wording:** statements that U4 was "NOT STARTED", "future read-only only", "awaiting diagnosis/implementation", "U4-B awaiting audit", "hashlib comment deferred", or "import cleanup not done" are superseded by this closeout. Such claims in historical blocks below are preserved only as historical record.
- **Preserved historical/superseded — pre-U5 wording:** statements that U5 was "NOT STARTED", "requires separate order", "read-only only", "NOT STARTED / REQUIRES SEPARATE ORDER", or "not authorized for mutation" are superseded by this closeout. Such claims in historical blocks below are preserved only as historical record.
- **Preserved historical/superseded — pre-U6 wording:** statements that U6 was "NOT STARTED", "requires separate explicit order", or "not authorized for mutation" are superseded by this closeout. Such claims in historical blocks below are preserved only as historical record.
- Preserved in historical blocks below: all Phase-0 and Macro Phase 0 closeout facts.
- Canonical reading order remains `docs/DOCUMENTATION_INDEX.md` → `docs/mapeamento/README.md` → `docs/mapeamento/05_avaliacao_refactor.md` → `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` → this top block → `AGENT_HANDOFF.md` → phase contracts.

Exact next action:

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R4 — controlled provisioning, ACL application,
copy of the 17 artifacts, manifest creation and integrity verification.

R4 is NOT STARTED. Its contract is APPROVED, but physical execution was explicitly
withheld in the same human decision. R4 requires a separate explicit human order
releasing physical execution; the recorded approval is not that order.

R4 scope when released: create `D:\programas` and
`D:\programas\SGAA_Historical_Custody\{artifacts,manifests,evidence}`; apply the
approved ACL; copy exactly 17 artifacts with overwrite disabled; create the custody
manifest; verify count, sizes and SHA-256. Move, delete, compress, SQLite open,
restoration execution and source removal remain prohibited. Phase 2 remains without
authorized next action.

### Historical — PHASE-0-R9 smoke-flow contract and evidence (CLOSED / ACCEPTED)

- Repository: `genesismazeto-sys/SGAA`; workspace `D:\OneDrive\Programação\SGAA_clean_baseline`; branch `refactor/architecture-safety-net`.
- Starting HEAD: `c978ed7471e60f78151608cccafe95f21527553b`; parent unchanged; index/staging empty. R9 initial worktree: only untracked `tests/test_phase_0_smoke_flows.py`. R9-R2 initial accepted partial worktree: three tracked doc modifications plus untracked contract/test. Before selective staging, the documentary-completion worktree manifest comprised exactly seven paths.
- Previous phase **R9A (pytest runtime isolation):** CLOSED / ACCEPTED externally.
- This phase **R9 (smoke-flow contract and evidence):** CLOSED / ACCEPTED via R10 docs-only closeout.
- Evidence file: `tests/test_phase_0_smoke_flows.py` (new, 485 lines, 5 tests).
- Contract: `docs/refactor/PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.md` (new).
- Five flows proven: admin login, aluno login, create requisicao sem anexo, process requisicao, local backup. All fixture-controlled, hermetic, under unique `PYTEST_RUNTIME_ROOT` subroot, with `relative_to` containment, explicit `admin_id`, filesystem inventory SHA-256 assertions, empty `call_log` for 7 backup sinks, `follow_redirects=False` + 302/303 + Location assertion, and snapshot `id`/`nome` marker verification.
- Test evidence:
  - smoke module: `5 passed in 5.99s`;
  - accepted full hermetic suite (`pytest -q --tb=short`): `654 passed, 17 deselected in 298.82s (0:04:58)`, exit 0, 0 failed, 0 errors, D73H executed 0 (no separate smoke duration);
  - R9-R2 aggregate invariant hash before AND after: `e3d10dc0e8d782ab73acedd6737f285e37b4e21691218049ad8dc654f1ff3331` (includes the five frozen dirty files, canonical `database.db`/root manifests, all three preexisting temp-root manifests/set, Git status, and empty staging; it is not the final seven-path Git manifest);
  - `database.db` unchanged: 544768 bytes, SHA-256 `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`.

### Historical — R9A pytest runtime isolation (CLOSED / ACCEPTED)

- R9A was externally accepted. Status: CLOSED / ACCEPTED.
- Root cause, invariant, production compatibility, agents, validation, and forensic cleanup remain as documented in the original R9A block below.
- The five Phase-0 smoke flows were **not** implemented or run in R9A.
- R9A full suite: `649 passed, 17 deselected in 441.22s`. `database.db` remained 544768 bytes at SHA-256 `a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9`.

### Historical REF-0C-C-B1 hybrid boundary and shadow gate (2026-07-18)

- REF-0C-C-A is CLOSED / ACCEPTED at `020cd7f` (documentation closeout commit follows it). REF-0C-C-B1 is implemented locally and pending ChatGPT supervisor review.
- Boundary: Flask-resolved `/admin` rule, plus exact external governed GET callbacks `auth_callback`, `google_callback`, and `onedrive_callback`; a governed normalized pair must have exactly one requirement or approved exemption. Exemption registry is empty.
- HEAD inherits GET; automatic OPTIONS remains framework-exempt; explicit OPTIONS must map/exempt; endpoint-None/404/405 preserve Flask behavior.
- Missing governed configuration raises `AdminAuthorizationConfigurationError` in testing/development. Production only emits one safe shadow audit event and continues current request behavior; production hard enforcement and permanent allow-open switches are not active.
- R20 is unchanged. No UI, schema, database, dependency, or modularization work occurred. Focused C-B1 test: `23 passed`; full detached hermetic suite: `600 passed`, `17 deselected` (`+23` selected tests over the accepted baseline).
- Exact next action after validation: ChatGPT supervisor review; no later phase is authorized.

### REF-0C-C-A fail-closed authorization gate diagnosis (2026-07-18)

- **CLOSED / ACCEPTED** at diagnosis commit `020cd7f` (`Document fail-closed authorization gate diagnosis`); closeout is recorded in the successor documentation commit. Diagnosis: `docs/refactor/REF_0C_C_A_FAIL_CLOSED_AUTHORIZATION_GATE_DIAGNOSIS.md`.
- Dynamic live inventory: 131 rules, 130 endpoints, 160 business route-method combinations. All 131 `/admin` combinations have explicit requirements; the unmapped `/admin` baseline remains empty. Three non-`/admin` OAuth callbacks are also centrally governed (`banco_dados/edit`).
- Recommended design only: hybrid fail-closed boundary—resolved `/admin` rule classification plus a precise registry for `auth_callback`, `google_callback`, and `onedrive_callback`; governed normalized method must have exactly one requirement or approved exemption. No explicit admin exemptions exist today.
- Proposed method policy: HEAD inherits GET; framework-generated OPTIONS is exempt; explicit OPTIONS must map or be precisely exempt; 404/405 and endpoint-None remain framework behavior.
- Missing governed mapping: production generic 403 (browser) / JSON 403 configuration error (AJAX), distinct internal observability; development/test should expose a configuration failure. Existing mapped scope denial and anonymous/aluno login behavior remain unchanged.
- Recommended rollout: characterization → registry contract → bounded shadow/canary → hard test/dev enforcement → production enforcement; rollback by verified deployment rollback, not a permanent allow-open switch.
- The supervisor approved the hybrid boundary, callback registry, staged rollout, and production shadow-before-enforcement direction. Production hard enforcement remains unauthorized. R20 remains unchanged; no UI, schema, database, dependency, or modularization work is authorized.
- Only REF-0C-C-B1 is authorized next: boundary registry, production shadow audit, and testing/development hard configuration failure. After B1, exact next action is ChatGPT supervisor review.

### REF-0C-B2-C supervisor acceptance closeout (2026-07-18)

- **REF-0C-B2-A: CLOSED / ACCEPTED** at `ed1803f`; **REF-0C-B2: CLOSED / ACCEPTED** at accepted implementation HEAD `c9e1843`.
- Current branch: `refactor/architecture-safety-net`; current divergence before this closeout: `origin/main...HEAD = 0 14`; no push.
- R22 GET and R23 GET → `atividades`/`view` → {`admin_total`, `administrativo`, `consultivo`}; R24 GET → `banco_dados`/`view` → {`admin_total`} only. Aluno and anonymous remain covered by `@admin_required`.
- RBAC debt baseline contains zero remaining route-method combinations. Full hermetic suite: `577 passed`, `17` D73H deselected.
- R20 local `readonly` remains unchanged; no global fail-closed gate, UI, schema, database, dependency, or modularization change occurred.
- Next candidate only: `REF-0C-C-A — FAIL-CLOSED AUTHORIZATION GATE DIAGNOSIS`, **NOT STARTED / NOT YET AUTHORIZED FOR IMPLEMENTATION**. Next action: ChatGPT supervisor issuance of a read-only REF-0C-C-A diagnosis order.

The historical REF-0C-A/B1 entries below retain their original phase-time facts.
The REF-0C-B2-C block above was the authoritative state as of its phase closeout;
it is historical and superseded by the current top block.

# Project State

## REF-0 refactor safety net

- Current branch: `refactor/architecture-safety-net`; current technical HEAD `932c6d7` (`Implement REF-0C-B1 strongly supported RBAC mappings`); transaction prerequisite `92b25d2` (`Fix admin access-context transaction hygiene`). Before this documentation-only closeout commit, `origin/main...HEAD = 0 10`; no push has been performed.
- REF-0A accepted: the refactor branch was created without application changes.
- REF-0ENV accepted: local `.venv` was rebuilt with Python `3.11.15`; the focused baseline passed `42` tests.
- Accepted phase chain: REF-0B at `f2b1cfc`; REF-0T at `c440297`; REF-0TF at `722b7a7`; REF-0TF-A at `e111cd5`; REF-0TF-B at `9b47c37`.
- REF-0TF-B accepted at `9b47c37`. D73H historical verification is isolated behind `--run-d73h-historical` marker; standard suite is hermetic.
- Independent architecture review completed on branch `refactor/architecture-safety-net` at `340fc7c` (`Add app mapping for refactor planning`).
- URL rules and endpoint names are frozen by `tests/_artifacts/route_inventory_baseline.json`, generated from `main.app.url_map`: `131` routes, `130` endpoints, and `160` business methods. Normal test execution only compares the contract and never rewrites it.
- RBAC policy debt is characterized by `tests/_artifacts/rbac_unmapped_routes_baseline.json`. After REF-0C-B1 this baseline lists `3` remaining `/admin` combinations (R22-R24 diagnostics) with no granular requirement; the `21` HIGH-confidence route-method mappings (R1-R21) are implemented.
- "Este baseline caracteriza dívida preexistente. O estado-alvo obrigatório é lista vazia. A existência do baseline não autoriza novas rotas sem política."
- Historical REF-0T/REF-0TF baseline (not the current suite result): `538` discovered, `17` D73H deselected, `521` selected and passed. Standard suite is hermetic.
- REF-0TF-B accepted at `9b47c37`.
- REF-0C-A / REF-0C-A-R1 CLOSED and ACCEPTED at accepted diagnosis HEAD `f977fd6`.
- REF-0C-B1-P0 CLOSED / ACCEPTED at `92b25d2`; REF-0C-B1 CLOSED / ACCEPTED at `932c6d7`.
- Current full hermetic suite: `562 passed`, `17` D73H deselected, with zero failures, errors, skips, xfails, or xpasses.
- R22-R24 remain unmapped and unresolved; R20 local `readonly` behavior remains unchanged; no global fail-closed authorization gate exists.
- No UI, schema, database, dependency, or modularization work is authorized. No subsequent implementation phase is automatically authorized.
- REF-0C-B2-A completed **locally and pending ChatGPT supervisor review**: a read-only, documentation-only decision package for the R22-R24 diagnostic access policy and the R20 local-readonly disposition. Starting HEAD `5fb4276` on branch `refactor/architecture-safety-net`; before this closeout `origin/main...HEAD = 0 11`. Decision document: `docs/refactor/REF_0C_B2_A_DIAGNOSTIC_ACCESS_POLICY_DECISION.md`. **No RBAC implementation was performed; R22-R24 still return `None`; R20 unchanged.**
  - Recommended R22 policy: `atividades`/`view` → {admin_total, administrativo, consultivo} (effective set A; zero behavioral change vs current). Confidence MEDIUM-HIGH. Not implemented.
  - Recommended R23 policy: `atividades`/`view` → {admin_total, administrativo, consultivo}; must equal R22 (identical data/call-graph). Confidence MEDIUM-HIGH. Not implemented.
  - Recommended R24 policy: `banco_dados`/`view` → {admin_total} only (effective set C; deliberately revokes administrativo+consultivo, who see filesystem paths/env value/exception tracebacks/identifiers; no UI link → no navigation cost). Confidence MEDIUM-HIGH. Not implemented.
  - Recommended R20 local-readonly disposition: keep unchanged this phase (central `matrizes`/`edit` gate already enforces before the handler body, so `readonly` is inert on this route); future authorized cleanup should prefer Option C (remove) or Option D (rename); reject Option B (handler-level denial → duplicate-authz drift risk). Not modified.
  - Repository-vs-documentation note recorded: R22/R23 do **not** read `alunos`/`requisicoes` (accepted REF-0C-A R22 row over-listed those); they expose no student PII. This refines an analysis field only and conflicts with no accepted state or decision.
  - Exact unresolved decisions (owned by ChatGPT supervisor + user): D2′ resource for R22/R23; D3′ resource for R24 (and whether administrativo needs it → set B requires a new `diagnosticos` resource / new vocabulary); accept/reject the R24 tightening; D1′ R20 removal vs rename; and whether/when REF-0C-B2 implementation is authorized. New vocabulary is required only if actor set B (admin_total + administrativo, consultivo denied) is demanded for a diagnostic.
- Next action: ChatGPT supervisor review of `REF_0C_B2_A_DIAGNOSTIC_ACCESS_POLICY_DECISION.md` and the user's normative decision on R22-R24 diagnostic access policy, R20 local-readonly cleanup, and whether/when REF-0C-B2 implementation may be authorized. Do not begin REF-0C-B2 implementation or REF-0C-C.
- Non-blocking cosmetic debt: the duplicate section number in `docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md` is deferred to the next authorized edit of that document.

### REF-0T — isolated full-suite baseline (2026-07-16)

- REF-0B (`f2b1cfc`) was accepted as the starting commit. Main workspace pre-flight matched `refactor/architecture-safety-net`, `f2b1cfc`, clean status, and `origin/main...HEAD = 0 1`.
- Test isolation audit: `tests/conftest.py` directs the test database to `tests/.pytest_app_database.db`, runtime documents/backups to `tempfile`, and per-test uploads/logs to `tmp_path`. Test-local destructive operations were audited; no inherited `APP_*` path pointed to the main workspace. The main-workspace root-artifact cleanup guard is not active in the temporary worktree because its root name differs.
- A detached worktree at `C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0t-f2b1cfc` was created from `f2b1cfc` without `database.db`, `.env`, uploads, documents, or backups. Collection passed: `537` tests, exit code `0`, no collection errors or relevant warnings.
- Full suite result: `519 passed`, `18 failed`, exit code `1`, `255.57s`. One failure is the pre-existing semester expectation in `test_aluno_progresso_renderiza_catalogo_e_agrega_semestres`; seventeen failures in `test_d73h_reconciliation_apply.py` require `database.db` at the checkout root, deliberately absent from the disposable worktree.
- Worktree side effects were limited to two tracked CSRF inventory JSON artifacts, ignored Python caches, `logs/app.log`, and an empty `uploads/` directory. No real data was copied. The worktree was removed after evidence collection.
- Main workspace preservation was confirmed before/after: `database.db` SHA-256 `A3A55E63427024476D85D1FCE3E0A5EFAEDCD33624400B2E67A815217D570FE9`; `backups`, `uploads`, and `documentos_alunos` absent; `logs` manifest SHA-256 `05daa74ef6f65a68fd13eb78f9abc1d95f8d945d6377f0971d2084e08615b619`; clean Git status and unchanged HEAD.
- Decision: **NO-GO** for `REF-0C-A`. Correcting RBAC and route modularization remain prohibited. The architect must authorize a dedicated classification phase for the full-suite failures.

### REF-0TF — full-suite failure classification (2026-07-16)

- REF-0T is accepted as an isolated baseline: 537 collected, 519 passed, 18 failed.
- Cluster A is a time-dependent stale test expectation, not an evidenced product defect: `test_aluno_progresso_renderiza_catalogo_e_agrega_semestres` hard-codes 2026/1 while the application intentionally includes the current semester determined by `date.today()`.
- Cluster B is not hermetic: the 17 D73H failures are historical-data verification tests coupled to ignored root `database.db` and an optional untracked pre-apply backup. A schema-only synthetic database fails next on historical `AAC-rev5` data, proving a missing historical fixture/setup contract.
- Required remediation phases: `REF-0TF-A — Progress Calendar Contract Hardening` and `REF-0TF-B — D73H Historical Verification Isolation`.
- RBAC correction and modularization remain prohibited. `REF-0C-A` remains **NO-GO** until the architect authorizes and accepts both remediation phases.

### REF-0TF-A — progress calendar contract hardening (2026-07-16)

- Starting state: `refactor/architecture-safety-net` at `722b7a7`, clean worktree, `origin/main...HEAD = 0 3`.
- Test-only change: `tests/test_aluno_progresso.py` now replaces only the module-local `app.views.aluno.datetime` binding. It proves that `2026/2` is excluded on reference date `2026-06-30` and included with its hours on `2026-07-01`; no application clock or source behavior changed.
- Focused boundary nodes passed in three consecutive runs (`2 passed` each); the whole file passed (`4 passed`).
- Detached temporary worktree `C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0tf-a-validation` collected `538` tests and ran the full suite: `521 passed`, `17 failed`, `234.13s`. The 17 failures are exactly the known D73H nodes, all blocked by absent worktree-local `database.db`; no additional regression occurred.
- The principal workspace database, environment, templates, static assets, schema, and production code were not opened or changed. The worktree was disposable; no real database or backup was copied into it.
- Decision: **GO for REF-0TF-B only.** D73H historical verification isolation is the next authorized remediation. RBAC correction and route modularization remain prohibited.

Last updated: 2026-07-25 (R31 docs-only selected-destination closeout; PHASE-1-U1 CLOSED / ACCEPTED; PHASE-1-U2 CLOSED / ACCEPTED; PHASE-1-U3 CLOSED / ACCEPTED; PHASE-1-U4 CLOSED / ACCEPTED; PHASE-1-U5 CLOSED / ACCEPTED; PHASE-1-U6 CLOSED / ACCEPTED; Phase 1 CLOSED / ACCEPTED; R1 CLOSED / ACCEPTED; R2 CLOSED / ACCEPTED; Historical snapshot custody: OPEN / POLICY APPROVED / CANONICAL_DESTINATION_SELECTED / DESTINATION NOT YET PROVISIONED / PHYSICAL ACTION NOT AUTHORIZED)
Closeout: R29 docs-only human policy ratification
Executor: R27 documentary execution (detailed routing telemetry retained outside the worktree); deepseek-v4-flash-free (R10 docs-only acceptance closeout); Claude Sonnet 4.6 (D8.5A read-only post-smoke audit + D8.5B controlled cleanup of id=57 + D8.5C docs-only closeout); Claude Sonnet 4.6 (D8.4A local write-flag-on supervised smoke + D8.4B docs-only closeout); Claude Sonnet 4.6 (D8.3A copy-db write-flag smoke + D8.3B docs-only closeout); Claude Sonnet 4.6 (D8.2A read-only write-cutover risk plan + D8.2B student-edit-snapshot contract hardening + docs closeout); Claude Sonnet 4.6 (D8.0A read-only audit + D8.0B baseline suite + backup); Claude Sonnet 4.6 (D7.7C3 final verify and push + D7.7C4 post-push doc sync; D7.7B1 matrix version validity hardening + docs closeout; D7.6G2 full suite remediation + docs closeout; D7.6E latest active version default + docs closeout; D7.6D matrix version selection + docs closeout; D7.6C activity version menu); Claude Sonnet 4.6 (D7.6B2 schema migration + R1 + R2 hardening + D7.6B3 docs closeout); Codex GPT-5 (D7.5C patch implementation + validation report + commit closeout); Claude Sonnet 4.6 (D7.4F read-only archive audit; D7.4G archive execution); Codex GPT-5 (D7.3K read-only diagnosis + docs closeout; D7.3J live apply + suite stabilization + docs closeout; D7.3I validation + docs closeout; D7.3H docs closeout); Claude Sonnet 4.6 (D7.3E closeout); Kimi K2.6 (audit); executor-PATCH1 (implementation); auditor-PATCH1-REVIEW

## Permanent State

### D6.4.0 - controlled snapshot write
- Implemented and approved.
- Flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` exists and remains default `OFF` in code.
- Controlled activation in the target environment was validated.
- The target environment used port `5001` after a conflict on `5000`.
- Rollback was validated: with the flag `OFF`, new requests are created with versioned fields set to `NULL`.
- `atividade_id` remains preserved and operational.
- No backfill was performed.
- No read cutover was performed.

### D6.5 - admin-only diagnostics
- Implemented and approved.
- `/admin/requisicoes` shows the discrete badge `"Snapshot versionado"`.
- `/admin/processar_requisicao/<id>` shows the read-only block `"Diagnostico do snapshot"`.
- The diagnostic is admin-only.
- No student screen was changed.
- JOIN, calculation, decision, limits, and processing remain on the legacy `atividade_id`.
- Missing or invalid snapshot data does not break the screen.
- Raw JSON is not exposed.
- Forbidden fields do not leak: observations, free text, documents, paths, or additional personal data.

### D6.6 - admin read-only comparison display
- D6.6-DISPLAY-1 approved.
- Commit `b9ffda2` - `Add admin snapshot comparison display`.
- Commit `09749ef` - `Fix snapshot comparison labels`.
- D6.6-DISPLAY-TEXT-ACCENTS-1R approved.
- Flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY` exists and remains default `OFF` in code.
- The display flag is independent from `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE`.
- The display flag is independent from `SGAA_VERSIONED_RESOLVER_SHADOW_READ`.
- With the flag `ON`, `/admin/processar_requisicao/<id>` `GET` shows the read-only comparison `Legado atual` vs `Snapshot versionado`.
- `/admin/requisicoes` did not gain a new comparison and still shows only the D6.5 badge.
- POST, processing, calculation, limits, and matrix scope remain on the legacy `atividade_id`.
- No backfill was performed.
- No cutover was performed.
- No student screen was changed.

### D6.7 - planning decision after D6.6 display
- D6.7-PLAN completed in read-only mode on `HEAD` `04b40cc`.
- No code, template, test, database, env, flag, or schema change was made during the analysis.
- Recommendation: pause at D6.6.
- `/admin/processar_requisicao/<id>` `GET` is already the safe and sufficient diagnostic surface.
- `/admin/processar_requisicao/<id>` `POST` remains legacy and out of scope.
- `/admin/requisicoes` should remain badge-only.
- Student request screens should not receive snapshot display now.
- Dashboards, progress, turma, and import flow remain out of scope.
- Snapshot remains admin-only, diagnostic, and read-only.
- `atividade_id` remains the operational source of truth.
- No backfill was performed.
- No read cutover was performed.
- No operational use of snapshot data was approved.

### D7.1 - activity version matrix contract tests
- Implemented and approved.
- Commit `e0427ee` — `Add activity version matrix contract tests`.
- Added helper `_get_turma_explicit_matriz_id_for_snapshot`.
- Added pre-check in `maybe_write_versioned_requisicao_snapshot`.
- Proved contract: if `turma.matriz_id` is `NULL`, the writer does **not** stamp `atividade_versao_id`.
- Ambiguity of version remains a hard error.
- Resolver remains read-only.
- No UI was changed.
- No schema was changed.
- No calculation or deferment was changed.
- No cutover or backfill was performed.
- `app/db.py` contains auto-fill in a seed/dev tool, but that does not run in the normal runtime of this branch.

### D7.2B1 - read-only activity version catalog (admin)
- Implemented and approved.
- Commit `73d45ac` — `Add read-only activity version catalog`.
- Commit `a3537cf` — `Fix activity version catalog card grids`.
- Read-only helpers added in `main.py`.
- 4 admin `GET` routes:
  - `/admin/catalogo-versoes`
  - `/admin/catalogo-versoes/<base_id>`
  - `/admin/normas-atividade`
  - `/admin/mapeamento-legado`
- 4 new templates:
  - `admin_catalogo_versoes.html`
  - `admin_catalogo_versao_detalhe.html`
  - `admin_normas_atividade.html`
  - `admin_mapeamento_legado.html`
- New test file: `tests/test_admin_activity_version_catalog_readonly.py`.
- CSS adjustments in `static/css/components/list-cards.css` with overrides for `.imp-catalogo`, `.imp-normas`, and `.imp-mapeamento`.
- Tests: D7.2B1 specific `17 passed`; D7.1/resolver/aluno scope regressions `17 passed`.
- Runtime check: `/admin/catalogo-versoes` `200`; `/admin/catalogo-versoes/1` `200`; `/admin/catalogo-versoes/999999` clean redirect, no `500`; `/admin/normas-atividade` `200`; `/admin/mapeamento-legado` `200`.
- CSS fix validated visually: no overflow on listings, final columns visible.
- Guarantees preserved: no new `POST`, no DB writes through the new routes, no auto-mapping, no student change, no operational matrix change, no calculation/deferment change, no schema/migration, no snapshot writer, no flags, no menu/sidebar entry, no backfill, no cutover.
- `main` / `origin/main` intact at `7e5eb56`.

### D7.2B2 - controlled creation of activity base and norms (admin)
- Implemented and approved.
- Commit `b91d03f` — `Add create forms for activity base and norms`.
- Commit `44d367a` — `Clarify activity version creation placeholder`.
- 2 new admin `GET/POST` routes:
  - `/admin/catalogo-versoes/nova-base`
  - `/admin/normas-atividade/nova`
- 2 new templates:
  - `templates/admin_catalogo_base_form.html`
  - `templates/admin_norma_form.html`
- Buttons `Nova base` and `Nova norma` enabled in the existing list screens
  (`templates/admin_catalogo_versoes.html` and `templates/admin_normas_atividade.html`).
- New test file: `tests/test_admin_activity_version_catalog_create.py`.
- Validations for `atividade_base`:
  - `nome_conceito` required;
  - whitespace trim;
  - empty name rejected;
  - `status` restricted to `ativo`/`inativo`;
  - duplicate rejected by case-insensitive pre-check;
  - success redirects to the detail of the created base.
- Validations for `norma_atividade`:
  - `codigo` required;
  - `codigo` trimmed;
  - `eixo` restricted to `AAC`/`AEU`;
  - `revisao` required;
  - `status` restricted to `ativa`/`inativa`;
  - duplicate rejected by case-insensitive pre-check;
  - success redirects to `/admin/normas-atividade`.
- Runtime check:
  - backup created before real `POST`s;
  - `GET`s of the new screens returned `200`;
  - invalid `POST`s did not insert rows;
  - valid `POST`s created temporary `D7TEMP` rows;
  - `D7TEMP` rows removed surgically by `id`/`codigo`/`nome`;
  - zero `D7TEMP` rows remaining;
  - `PRAGMA foreign_key_check` reported no violations;
  - hashes and counts of relevant tables returned to baseline;
  - local database restored to the pre-phase state;
  - `64 passed` tests.
- Textual fix in `44d367a`:
  - in `templates/admin_catalogo_versao_detalhe.html`, removed the obsolete
    reference to D7.2B2 in the version-creation placeholder;
  - placeholder now uses `fase posterior`;
  - `Criar versão` button remains disabled;
  - no new route, `POST`, or version-creation functionality was introduced;
  - `47 passed` tests.
- Guarantees preserved:
  - no `atividade_versao` creation;
  - no edit;
  - no legacy mapping save;
  - no change in `matriz_atividade_versao_item`;
  - no change in `matrizes_atividades_itens`;
  - no change in `aluno`;
  - no change in calculation/deferment;
  - no schema/migration change;
  - no snapshot writer;
  - no flags;
  - no menu/sidebar entry;
  - no backfill;
  - no cutover.
- `main` / `origin/main` intact at `7e5eb56`.

### D7.2B3-PATCH1 - draft activity version creation
- Implemented and approved.
- Commit `16b1480` — `Add draft activity version creation`.
- Commit `ccf1a7e` — `Record D7.2B3 draft version creation`.
- 1 new admin `GET/POST` route:
  - `/admin/catalogo-versoes/<int:base_id>/nova-versao`
- 1 new template: `templates/admin_catalogo_versao_form.html`.
- 1 updated template: `templates/admin_catalogo_versao_detalhe.html` (button enabled).
- 1 new test file: `tests/test_admin_activity_version_catalog_version_form.py` (17 tests).
- Helpers added in `main.py`:
  - `get_norma_by_id(conn, norma_id)` — read-only lookup.
  - `get_versoes_da_base_por_eixo(conn, base_id, eixo)` — read-only lookup now
    actively used to populate the optional `versao_anterior_id` select.
- Functional guarantees:
  - rota GET/POST `/admin/catalogo-versoes/<base_id>/nova-versao`;
  - helper `get_norma_by_id`;
  - helper `get_versoes_da_base_por_eixo` agora usado no formulário;
  - criação de `atividade_versao` com status forçado em rascunho;
  - `codigo_normativo` derivado de `norma_atividade.codigo`;
  - `eixo` derivado de `norma_atividade.eixo`;
  - `norma_id` obrigatório, sem primeira norma automática;
  - select de norma com placeholder obrigatório;
  - `versao_anterior_id` como select opcional com placeholder "Sem versão anterior";
  - validação server-side de base, norma ativa, duplicidade base+norma,
    números inválidos/negativos, versão anterior inexistente, de outra base
    ou de eixo incompatível;
  - botão "Criar versão" habilitado no detalhe da atividade-base;
  - novo template `templates/admin_catalogo_versao_form.html`;
  - novo teste `tests/test_admin_activity_version_catalog_version_form.py`
    com 17 testes;
  - suíte parcial validada com 91 passed.
- Garantias explícitas de fora do escopo do PATCH1:
  - edição de versão;
  - ativação/publicação;
  - vínculo com matriz;
  - UI de matriz;
  - fluxo do aluno;
  - cálculo/deferimento;
  - snapshot writer;
  - schema/migration;
  - backfill/cutover;
  - importação de regulamentos reais;
  - menu/sidebar;
  - mapeamento legado salvo.
- `main` / `origin/main` intact at `7e5eb56`.
- Branch `recovery/d7-activity-versioning` pushed to origin at `ccf1a7e`.

### D7.2B3-PATCH2 - draft activity version editing
- Implemented and approved locally.
- Commit `c90ffe3` — `Add draft activity version editing` (current `HEAD`).
- 1 new admin `GET/POST` route:
  - `/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/editar`
- 2 new helpers in `main.py`:
  - `get_atividade_versao_by_id(conn, versao_id)` — read-only lookup with JOIN to base.
  - `get_atividade_versao_usage_counts(conn, versao_id)` — read-only usage check
    across `matriz_atividade_versao_item`, `requisicoes`, `atividade_transicao`.
- Template `admin_catalogo_versao_form.html` parametrized for creation and editing
  (`form_action`, `form_title`, `submit_label`).
- Template `admin_catalogo_versao_detalhe.html` gains an "Ações" column:
  - "Editar" link visible only when versão status is `rascunho`.
- New test file:
  `tests/test_admin_activity_version_catalog_version_edit.py` (28 tests).
- Functional guarantees:
  - edição permitida **somente** para `status = 'rascunho'`;
  - GET e POST bloqueiam versões `ativa`, `inativa`, `descontinuada`, `substituida`;
  - bloqueio total se a versão tiver **qualquer uso** em:
    - `matriz_atividade_versao_item`;
    - `requisicoes.atividade_versao_id`;
    - `atividade_transicao.from_atividade_versao_id`;
    - `atividade_transicao.to_atividade_versao_id`;
  - `codigo_normativo` recalculado de `norma_atividade.codigo`;
  - `eixo` recalculado de `norma_atividade.eixo`;
  - `status` **não editável** (ignorado via payload);
  - `atividade_base_id` **não editável** (ignorado via payload);
  - `created_at` preservado;
  - `documentos_json` preservado e fora do escopo do PATCH2;
  - validação de norma obrigatória, existente e ativa;
  - validação de duplicidade base+norma ignorando a própria versão;
  - validação de números: vazios → NULL, não numéricos rejeitados, negativos rejeitados;
  - validação de `versao_anterior_id` opcional:
    - deve existir;
    - deve pertencer à mesma base;
    - deve ter mesmo eixo;
    - não pode ser a própria versão.
- Explicitly out of scope:
  - ativação/publicação;
  - edição de status;
  - vínculo com matriz ou UI de matriz escolhendo versão;
  - fluxo do aluno;
  - cálculo/deferimento/indeferimento;
  - snapshot writer;
  - schema/migration;
  - backfill/cutover;
  - importação de regulamentos reais;
  - menu/sidebar;
  - `documentos_json`;
  - mapeamento legado salvo.
- Test suite validated: **119 passed**.
- `main` / `origin/main` intact at `7e5eb56`.
- Branch `recovery/d7-activity-versioning` local at `c90ffe3`; not yet pushed.

### D7.2B3-PATCH3 - draft activity version activation
- Implemented, approved, and pushed.
- Commit `28d922d` — `Add draft activity version activation`.
- Commit pushed to `origin/recovery/d7-activity-versioning` at `28d922d`.
- `main` / `origin/main` intact at `7e5eb56`.
- 1 new admin POST route:
  - `/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/ativar`
- Functional guarantees:
  - ativação explícita `status = 'rascunho'` → `status = 'ativa'`;
  - `@admin_required` na rota;
  - validação server-side: base existe, versão existe e pertence à base, status == `'rascunho'`, norma vinculada existe e está `'ativa'`;
  - `UPDATE atividade_versao SET status='ativa' WHERE id=? AND status='rascunho'` com rowcount check;
  - rollback + flash + redirect em falha, sem 500;
  - commit + flash + redirect no sucesso;
  - botão/form "Ativar" apenas para versões em rascunho no template de detalhe;
  - `csrf_token` real renderizado no form;
  - confirmação JS (`window.confirm`) é apenas UX; segurança é server-side.
- Change in `tests/test_csrf_inventory_audit.py` (56 lines):
  - **apenas seed/evidência real**: inserção de `atividade_base`, `norma_atividade` (ativa) e `atividade_versao` (rascunho) no setup isolado;
  - adição de `base_id` e `versao_id` ao `sample_values` do crawler;
  - **sem whitelist, sem bypass, sem relaxamento de política CSRF, sem remoção de rota do inventário.**
- Decisões de produto aplicadas:
  - **D1** — múltiplas versões ativas permitidas no catálogo; bloqueio de ambiguidade fica para fase de vínculo matriz→atividade_versao.
  - **D2** — norma vinculada inativa bloqueia ativação.
  - **D3** — CH, limites e vigência não são exigidos para ativação.
  - **D4** — confirmação simples no form (JS opcional), segurança server-side.
- Testes validados:
  - `test_csrf_inventory_audit.py` — **2 passed**;
  - `test_admin_activity_version_catalog_version_activate.py` — **17 passed** (novo);
  - `test_admin_activity_version_catalog_version_edit.py` — **28 passed**;
  - `test_admin_activity_version_catalog_version_form.py` — **17 passed**;
  - `test_matriz_versao_contract.py` + `test_activity_versioning_resolver.py` — **14 passed**;
  - `pytest -q --tb=line` (full suite) — **367 passed**, 4 warnings (openpyxl deprecation).
- Explicitly out of scope:
  - inativação/descontinuação/substituição de versão;
  - auditoria de "quem ativou quando";
  - vínculo matriz → atividade_versao;
  - UI de matriz escolhendo versão;
  - fluxo do aluno;
  - cálculo/deferimento/indeferimento;
  - snapshot writer;
  - schema/migration;
  - backfill/cutover;
  - importação de regulamentos reais;
  - menu/sidebar;
  - primeira ativa ou fallback silencioso.
- Artifacts CSRF gerados por teste (`tests/_artifacts/csrf_inventory_shadow_*.json`) foram restaurados e não fazem parte do closeout.

### D7.2B4-PATCH1 - admin UI for explicit matrix→atividade_versao links
- Implemented and committed.
- Commit `255ff80` — `Add admin UI for explicit matrix→atividade_versao links (D7.2B4)`.
- Branch `recovery/d7-activity-versioning` at `255ff80` (not yet pushed to origin).
- `main` / `origin/main` intact at `7e5eb56`.
- **New helpers in `main.py`** (read-only + write, all scoped to admin routes):
  - `get_bases_escopo_matriz(conn, matriz_id)` — bases in matrix legacy scope via `matrizes_atividades_itens + atividade_legacy_map`.
  - `get_versoes_ativas_por_base_na_matriz(conn, matriz_id, base_id)` — active versions for a base whose norma is in `matriz_norma` for this matrix.
  - `get_vinculo_versao_da_matriz(conn, matriz_id, base_id)` — single explicit link from `matriz_atividade_versao_item` for a matriz+base.
  - `_set_versao_da_matriz_para_base(conn, matriz_id, base_id, versao_id)` — DELETE old + INSERT new, enforcing max-1 per matriz+base.
  - `_remover_versao_da_matriz_para_base(conn, matriz_id, base_id)` — removes any link for this matriz+base, returns rowcount.
- **3 new admin routes**:
  - `GET  /admin/matrizes/<id>/versoes` → `admin_matriz_versoes` (page listing all scope bases with their current link and available versions).
  - `POST /admin/matrizes/<id>/versoes/definir` → `admin_matriz_versoes_definir` (set/replace explicit link, 7 server-side validations).
  - `POST /admin/matrizes/<id>/versoes/remover` → `admin_matriz_versoes_remover` (remove link, idempotent).
- **Server-side validations in `admin_matriz_versoes_definir`**:
  1. Matriz exists.
  2. `base_id` and `versao_id` are digits.
  3. `atividade_base` exists.
  4. `atividade_versao` exists.
  5. Versão belongs to the given base.
  6. Versão `status == 'ativa'`.
  7. Base is in the matrix's legacy scope (`matrizes_atividades_itens + atividade_legacy_map`).
  8. Versão's `norma_id` is in `matriz_norma` for this matrix.
  - Rollback + flash + redirect on error; commit + flash + redirect on success.
- **1 new template**: `templates/admin_matriz_versoes.html`.
  - Table: Atividade-base | Versão atual | Definir versão ativa | Remover vínculo.
  - "Definir" form only shown when `versoes_disponiveis` non-empty.
  - "Remover" form only shown when `vinculo` is set.
  - Both forms include `name="csrf_token"` with `{{ csrf_token() }}`.
- **Updated template**: `templates/admin_matriz_form.html`.
  - "Versões" tab added in both `{% if activity_tabs_enabled %}` branch (active link to `admin_matriz_versoes`) and `{% else %}` branch (disabled span).
- **New test file**: `tests/test_admin_matriz_versao_link.py` — **14 tests** covering:
  1. GET 200.
  2. UI shows scope bases.
  3. Helper returns only ativas.
  4. Helper excludes rascunho/inativa/descontinuada/substituida.
  5. POST rejects version whose norma is not in `matriz_norma`.
  6. POST creates valid link in DB.
  7. POST replaces previous link (no duplicates per matriz+base).
  8. POST removes link.
  9. Resolver resolves after link set.
  10. Resolver returns `base_without_version_for_matrix` after link removed.
  11. POST rejects base not in matrix's legacy scope.
  12. POST rejects version with norma absent from `matriz_norma`.
  13. No first-active fallback without explicit link.
  14. CSRF token present in rendered POST forms.
- **Updated test**: `tests/test_csrf_inventory_audit.py` — seed data added (norma ativa, versão ativa, atividade_legacy_map, matrizes_atividades_itens, matriz_norma, matriz_atividade_versao_item) so the CSRF crawler renders the POST forms for the 2 new mutating routes.
- **Test suite**: **381 passed**, 4 warnings (openpyxl). Up from 367 (+14 from new file, net).
- **Permanent constraints preserved**:
  - `resolver_versao_por_matriz` / `resolver_versao_por_aluno` / `resolver_versao` / `maybe_write_versioned_requisicao_snapshot` — untouched.
  - No silent fallback / no first-active / version ambiguity remains a hard error.
  - No version inference by name / eixo / date.
  - No calculation / deferment / student screens changed.
  - No schema / migration.
  - No backfill / cutover.
  - No merge to main.
- Explicitly out of scope:
  - Inativação/descontinuação/substituição de versão.
  - Bulk import / real regulations.
  - Matrix operational join switch.
  - Student screens / calculation / deferment.
  - Snapshot writer.

### D7.2B5-PATCH1 - admin lifecycle transitions for atividade_versao
- Implemented and committed.
- Commit `f235f62` — `Add admin lifecycle transitions for atividade_versao (D7.2B5)`.
- Branch `recovery/d7-activity-versioning` at `f235f62` (not yet pushed to origin).
- `main` / `origin/main` intact at `7e5eb56`.
- **2 new admin POST routes**:
  - `POST /admin/catalogo-versoes/<base_id>/versoes/<versao_id>/inativar` → `admin_catalogo_inativar_versao`.
  - `POST /admin/catalogo-versoes/<base_id>/versoes/<versao_id>/descontinuar` → `admin_catalogo_descontinuar_versao`.
- **Functional guarantees**:
  - Ambas exigem `@admin_required` e CSRF real no form.
  - Validação server-side: base existe, versão existe e pertence à base da URL, status atual == `'ativa'`.
  - **Bloqueio B1**: rejeita se houver qualquer vínculo em `matriz_atividade_versao_item`; mensagem orienta o admin a remover o vínculo na tela de versões da matriz primeiro, sem realizar nenhum efeito colateral.
  - `UPDATE atividade_versao SET status = 'inativa'/'descontinuada' WHERE id = ? AND status = 'ativa'` com rowcount check.
  - Rollback + flash + redirect em falha; commit + flash + redirect em sucesso.
  - A versão inativada/descontinuada sai automaticamente do escopo do resolvedor (pois `_atividade_versao_status_ativo` retorna `False` para esses status) sem nenhuma alteração no resolvedor.
- **Template `templates/admin_catalogo_versao_detalhe.html`**:
  - Nova branch `{% elif status_key == 'ativa' %}` na coluna Ações com botões "Inativar" (âmbar) e "Descontinuar" (vermelho).
  - Ambos os botões têm `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
  - Confirmação JS (`window.confirm`) é apenas UX; segurança é server-side.
  - CSS: `.vc-inativar-btn` e `.vc-descontinuar-btn` adicionados ao bloco `<style>`.
- **New test file**: `tests/test_admin_activity_version_catalog_version_lifecycle.py` — **19 tests**:
  1–8: inativar — ativa sem vínculo, inexistente, outra base, já inativa, rascunho, descontinuada, substituida, com vínculo (bloqueio B1 completo).
  9: resolver retorna ausência de versão após inativar.
  10–14: descontinuar — ativa sem vínculo, com vínculo, rascunho, já descontinuada, inativa.
  15–17: template — buttons rendered for ativa only, not rascunho, not outros.
  18: CSRF token presente em ambos os forms.
  19: regressão D7.2B4 — inativar versão A não quebra resolver para versão B da mesma matriz.
- **CSRF inventory test** (`tests/test_csrf_inventory_audit.py`): **sem alterações** — `versao_lnk_id` (ativa, da seed D7.2B4) já fornece evidência renderizada para ambas as novas rotas POST.
- **Test suite**: **400 passed**, 4 warnings (openpyxl). Up from 381 (+19 from new file, net).
- **Permanent constraints preserved**:
  - `resolver_versao_por_matriz` / `resolver_versao_por_aluno` / `resolver_versao` / `maybe_write_versioned_requisicao_snapshot` — untouched.
  - No silent fallback / no first-active / version ambiguity remains a hard error.
  - No DELETE automático de `matriz_atividade_versao_item`.
  - No `atividade_transicao` created.
  - No version substituta chosen.
  - No calculation / deferment / student screens changed.
  - No schema / migration.
  - No backfill / cutover.
  - No merge to main.
- **Explicitly out of scope**:
  - Substituição de versão (`substituida`).
  - Reativação de versão inativa ou descontinuada.
  - `atividade_transicao`.
  - Auditoria de quem inativou/descontinuou.
  - Bulk import / real regulations.
  - Student screens / calculation / deferment.
  - Snapshot writer.

### D7.2B5-PATCH2 - explicit activity version substitution
- Implemented and committed.
- Commit `9d2e9fb` - `Add explicit activity version substitution`.
- Branch `recovery/d7-activity-versioning` later advanced to docs closeout `5f7dbc8`, aligned with `origin/recovery/d7-activity-versioning`.
- `main` / `origin/main` intact at `7e5eb56`.
- 1 new admin POST route:
  - `/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/substituir`
- Functional guarantees:
  - explicit substitution only; no fallback and no implicit target selection;
  - origin must exist, belong to the URL base, and be `status = 'ativa'`;
  - origin is blocked if any `matriz_atividade_versao_item` link exists;
  - `to_versao_id` is mandatory and must be a valid integer;
  - destination must exist, be `status = 'ativa'`, belong to the same `atividade_base`, have the same `eixo`, and differ from origin;
  - origin cannot already be `from_atividade_versao_id` in `atividade_transicao`;
  - destination cannot already be `from_atividade_versao_id` in `atividade_transicao`;
  - operation is transactional: `UPDATE atividade_versao SET status='substituida'` on origin + `INSERT INTO atividade_transicao (..., tipo_transicao='mesmo_eixo')`;
  - rollback on failure; commit on success.
- Template `templates/admin_catalogo_versao_detalhe.html` updated:
  - active versions now render a `Substituir` form;
  - form includes explicit `to_versao_id` select with active same-base same-axis candidates only, excluding the origin itself;
  - form is disabled when no valid candidate exists;
  - CSRF token present in the rendered form.
- Scope explicitly unchanged:
  - no resolver changes;
  - no snapshot writer changes;
  - no schema/migration changes;
  - no aluno/calculation/deferment changes;
  - no `aac_para_aeu`;
  - no reactivation.
- Focused tests already executed:
  - lifecycle + activate/edit/form: `96 passed`;
  - matriz/resolver/csrf: `30 passed`;
  - lifecycle isolated: `34 passed`.

### D7.2B6 - admin transition history (read-only)
- Implemented, validated, committed, and published.
- Functional commit published on `recovery/d7-activity-versioning`:
  - `95cb897` - `Add admin transition history for activity versions`
  - remote hash: `95cb89797f1a0a16ff812933d9788f2019b14ad4`
- Branch state after functional push:
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`
  - `origin/main...main = 0 0`
  - working tree was clean after the functional push
  - `main` / `origin/main` remained at `7e5eb56`
- Functional scope delivered:
  - new read-only helper `get_atividade_transicoes_por_base`;
  - `JOIN` entre `atividade_transicao` e versões origem/destino;
  - filtro por `atividade_base` da origem ou do destino;
  - payload com `versao_origem`, `versao_destino`, `tipo_transicao`, `eixo`, `created_at` e `motivo`;
  - `motivo` usa `justificativa` ou `observacao_admin` ou fallback `"-"`;
  - rota `GET /admin/catalogo-versoes/<base_id>` passa `transicoes_historico` ao template existente;
  - `templates/admin_catalogo_versao_detalhe.html` ganhou a seção read-only `Histórico de transições` com tabela e estado vazio.
- Garantias preservadas:
  - sem `POST` novo;
  - sem CSRF novo;
  - sem schema/triggers;
  - sem fluxo do aluno;
  - sem cálculo/deferimento;
  - sem writer/versioned snapshot;
  - sem matriz;
  - sem alteração da lógica de ativar/inativar/descontinuar/substituir.
- Testes executados:
  - `python -m pytest tests/test_admin_activity_version_catalog_readonly.py -q --tb=short` → `21 passed in 10.03s`;
  - `python -m pytest tests/test_admin_activity_version_catalog_version_lifecycle.py -q --tb=short` → `34 passed in 102.08s`.
- Revisão visual executada:
  - renderização headless temporária do template;
  - cenário sem transições exibiu `Nenhuma transição registrada para esta atividade-base.`;
  - cenário com transição exibiu origem, destino, `tipo_transicao`, fallback `"-"` em motivo e `created_at`;
  - botões `Ativar`, `Inativar`, `Descontinuar` e `Substituir` permaneceram visíveis sem quebra visual óbvia.
- Riscos residuais:
  - `created_at` segue exibido em formato cru do SQLite;
  - não há auditoria de ator/admin na tabela `atividade_transicao`;
  - a UI lista tipos de transição de forma genérica, sem fluxo novo para além de `mesmo_eixo`.
- Status de projeto após a publicação:
  - branch ativa continua `recovery/d7-activity-versioning`;
  - `HEAD` da branch avança além de `95cb897` apenas com closeouts documentais subsequentes;
  - D7.2B6 funcional está fechada e publicada em `95cb897`;
  - próxima fase ainda não foi iniciada.

### D7.3A - normative canonization of AAC/AEU regulations
- Accepted as read-only documental diagnosis. No code, template, test, DB, or seed change.
- Documents analyzed (stored in `_normativos_inbox/`, excluded from Git):
  - `ACC-rev5.docx` — Regulamento de Atividades Complementares antigo (160 h, 5 grupos).
  - `ACC-rev6.docx` — Regulamento de Atividades Complementares atualizado, simplificado.
  - `AE-rev1.docx` — Regulamento de Atividades de Extensão Universitária (Res. CNE/CES 7/2018).
- Canonization accepted:
  - `ACC-rev5.docx` → internal codigo_normativo **AAC-rev5** (eixo AAC, revisão rev5).
  - `ACC-rev6.docx` → internal codigo_normativo **AAC-rev6** (eixo AAC, revisão rev6).
  - `AE-rev1.docx` → internal codigo_normativo **AEU-rev1** (eixo AEU, revisão rev1).
- Normative status:
  - AAC-rev5: histórico/legado, preservado para matrizes legadas quando aplicável.
  - AAC-rev6: AAC vigente.
  - AEU-rev1: AEU vigente.
- Key differences ACC-rev5 vs ACC-rev6:
  - ACC-rev6 simplifies documentation requirements for several categories.
  - ACC-rev6 removes "Horas de voo em simulador".
  - ACC-rev6 removes/relocates "Trabalho voluntário em organizações do terceiro setor" to AEU.
  - ACC-rev6 separates "Projetos de apoio institucional" from "Projetos de extensão".
  - ACC-rev6 simplifies book reading to 10h/book (was 5h non-technical / 10h technical).
  - ACC-rev6 reduces minimum report length (2 pages instead of 3).
- Key differences AAC vs AEU:
  - AEU requires interaction with external community.
  - Trabalho voluntário em terceiro setor migrates to AEU.
  - Projetos de extensão belong to AEU axis.
  - AEU has own activities: organização de eventos extensionistas, participação em
    eventos extensionistas, cursos/oficinas/palestras para comunidade externa.
  - Ambiguous cases between "apoio institucional" and "extensão" require human decision.
- Schema/model gaps:
  - Conditional workload rules depend on observation fields.
  - Documentation requirements and annexes have no dedicated structured fields.
  - AEU-rev1 does not define mandatory total workload; depends on PPC.
  - AAC→AEU transitions must be explicit and justified.
  - Direct DOCX import must not be the primary operational source.
- Architectural decision:
  - D7.3B must not import directly from DOCX to the production database.
  - Preferred next step: create a reviewable canonical fixture (YAML/JSON/CSV),
    derived from the DOCX and audited, before any importer.
  - Only then create a dry-run importer consuming the fixture.
  - Dry-run importer must not touch matrix, requests, student, calculation, or deferment.
- DOCX disposal: the DOCX files are local diagnostic inputs in `_normativos_inbox/`,
  excluded from Git via `.git/info/exclude`, and must not be committed at this stage.
- Next step: plan D7.3B as reviewable canonical specification/fixture; do not implement yet.

### D7.3B-PLAN - Fixture format specification
- Accepted as read-only specification. No code, template, test, DB, or seed change.
- Format: YAML chosen over JSON/CSV for human readability, multiline support, and Git diff clarity.
- Directory: `normative_fixtures/` (no `data/` directory exists in project).
- Structure: `meta`, `normas`, `atividades` with `versoes`, `atividade_removida_em`, `atividade_nova_em`, `transicao_proposta`.
- `status_inicial` = "rascunho" for all versions.
- `ch_regra_condicional` uses controlled vocabulary: null, equivalente_curso, equivalente_horas, tempo_declarado_ou_limite, carga_declarada_ou_limite_evento, tier_documental, horas_por_evento, horas_por_banca, regra_especial_ivao, exige_decisao_humana.
- `[REGRA: ...]` and `[ANEXOS: ...]` prefixes used in `observacao_admin` to preserve normative metadata.
- `transicao_proposta` must include `de` (from norma), `para` (to norma), `tipo`, `justificativa`.
- `atividade_nova_em` only for activities that are genuinely new and do not exist in previous norms.
- `atividade_removida_em` only for activities that exist in previous norms but not in the current one.
- Next step: create the canonical fixture YAML (D7.3C).

### D7.3C - Canonical fixture creation
- Scope: create the real canonical normative fixture YAML from the three DOCX regulations.
- Output: `normative_fixtures/d73c_normative_fixture.yaml`.
- Contents validated:
  - 3 normas: AAC-rev5 (29 activities), AAC-rev6 (27 activities), AEU-rev1 (5 activities).
  - 32 unique conceptual activities mapped to `atividade_base`.
  - 61 total versions across all norms.
  - 2 activities removed in AAC-rev6: SIMULADOR_VOO, TRAB_VOLUNTARIO_TERCEIRO_SETOR.
  - 3 native AEU activities: ORG_EVENTOS_EXTENSIONISTAS, PART_EVENTOS_EXTENSIONISTAS, CURSOS_OFICINAS_PALESTRAS_COMUNIDADE.
  - 1 explicit transition: TRAB_VOLUNTARIO_TERCEIRO_SETOR (AAC-rev5 → AEU-rev1, tipo: aac_para_aeu).
  - PROJETOS_EXTENSAO is ambiguous (AAC apoio institucional vs AEU extensão) and requires human decision (noted in `observacao_admin` of AEU-rev1 version).
  - `status_inicial` = "rascunho" for all 61 versions.
  - `ch_regra_condicional` uses controlled vocabulary throughout; no invalid values.
  - YAML validated with Python `yaml.safe_load` → `YAML_OK`.
  - Deep validation: no invalid `ch_regra_condicional` values, no missing required fields.
- No code, template, test, DB, or seed was changed during D7.3C.
- The DOCX files remain in `_normativos_inbox/` and are excluded from Git.
- Next step: D7.3D dry-run importer consuming the fixture YAML into an isolated DB.

### D7.3D-PATCH1 - normative dry-run importer
- Implemented, audited, and committed.
- D7.3D-PATCH1-REVIEW executed by Kimi K2.6 in read-only mode: ACEITAR D7.3D-PATCH1.
- New files:
  - `tools/d73d_normative_importer_dryrun.py` — CLI dry-run importer.
  - `tests/test_d73d_normative_importer_dryrun.py` — test suite (5 tests).
- Modified file:
  - `requirements.txt` — added `PyYAML==6.0.2`.
- Functional guarantees:
  - `--fixture` obrigatório; `--report text/json`; `--strict` trata warnings como erro.
  - Sem `--apply`, sem modo real, sem importação operacional.
  - Recusa `--db` com basename `database.db` (case-insensitive) antes de qualquer conexão.
  - Não importa `main`, `create_app`, `init_db`, ou `APP_DATABASE`.
  - Banco temporário criado via `tempfile.NamedTemporaryFile` e removido em `finally`.
  - `database.db` real preservado: tamanho e SHA256 inalterados após qualquer execução.
  - Schema SCHEMA_SQL idêntico ao de `main.py` (4 tabelas + 6 triggers).
  - Validações de fixture: YAML parseável; top-level meta/normas/atividades; normas únicas; códigos únicos; nomes canônicos únicos (NFKD); norma_ref existente; transicao_proposta de/para existentes; ch_regra_condicional em vocabulário aprovado; documentacao_exigida não vazia se presente; atividade_removida_em sem versão indevida; atividade_nova_em sem versão legada indevida salvo exige_decisao_humana.
  - Idempotência: segunda execução no mesmo `--db` produz inserted=0, skipped=3/32/61/1.
  - Transação atômica: rollback automático se qualquer insert falhar.
- Contagens validadas com `normative_fixtures/d73c_normative_fixture.yaml`:
  - 3 normas, 32 bases, 61 versões, 1 transição.
  - Todas as versões inseridas com status `rascunho`.
  - 2 removidas em AAC-rev6 não geram versão na norma removida.
  - 3 nativas AEU presentes somente em AEU-rev1.
  - Transição AAC-rev5 → AEU-rev1 (aac_para_aeu) com eixos corretos.
- Testes:
  - `python -m pytest tests/test_d73d_normative_importer_dryrun.py -q --tb=short`
  - Executor: 5 passed in 7.40s.
  - Auditor: 5 passed in 4.07s.
- Risco backlog [B-01]: `documentacao_exigida` validada somente quando a chave existe; futura iteração pode tornar a chave obrigatória em toda versão.
- Importação real para `database.db` não foi executada. D7.3D fica fechada neste ponto.
- Próximo passo: não iniciar importador real sem escopo explícito aprovado.

### D7.3E-RO1 - fixture vs real database convergence diagnostic
- Accepted as read-only convergence diagnosis between canonical fixture and the current real database.
- No code, fixture, importer, test, requirements, database, script, migration, or seed change was made during D7.3E-RO1.
- Observed Git state:
  - branch `recovery/d7-activity-versioning`;
  - `HEAD` `45dd39d`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - working tree clean.
- `main` / `origin/main` preserved at `7e5eb56`.
- Real database preserved:
  - before: `528384` bytes;
  - SHA256 before: `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
  - after: `528384` bytes;
  - SHA256 after: `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
  - SQLite connection opened in read-only URI mode (`mode=ro`);
  - only `SELECT`, `PRAGMA`, and `sqlite_master` reads were executed.
- Current database counts:
  - `norma_atividade`: `6`;
  - `atividade_base`: `35`;
  - `atividade_versao`: `60`;
  - `atividade_transicao`: `31`;
  - `matriz_atividade_versao_item`: `59` links;
  - `requisicoes`: `41` total;
  - `requisicoes` fully versioned: `13` rows with `atividade_versao_id`, `regra_snapshot_json`, and `codigo_normativo_snapshot` populated;
  - only `1` version outside matrix links: `id=60`, `Runtime Base 2cb9b503`, `NRM-RT-2cb9b503`, `status='rascunho'`.
- Fixture counts:
  - `3` normas;
  - `32` atividades;
  - `61` versÃµes;
  - `1` proposed transition;
  - `2` removed activities;
  - `3` new activities;
  - by norm: `AAC-rev5=29`, `AAC-rev6=27`, `AEU-rev1=5`.
- Norm comparison:
  - `AAC-rev5` exists by `codigo`, but `nome` diverges;
  - `AAC-rev6` exists by `codigo`, but `nome` diverges;
  - `AEU-rev1` exists by `codigo`, but `nome` diverges;
  - extra norms outside fixture: `NRM-RT`, `NRM-RT-5c96604e`, `NRM-RT-2cb9b503`.
- Technical result:
  - under the current dry-run importer semantics, execution against the real DB would abort on the first divergent `norma_atividade`;
  - this confirms the dry-run importer is not a real importer and must not be reused as `apply`.
- Activity/version comparison summary:
  - `20` bases with exactly matching `nome_conceito` still have divergent `descricao`;
  - `11` clear nominal duplicates;
  - `1` near match: `Prova de InglÃªs ICAO` vs `Prova de inglÃªs ICAO`;
  - `38` fixture versions have some comparable DB version, but all are divergent;
  - `23` fixture versions remain `missing` in semantic crosswalk because of `nome_conceito` differences;
  - `18` divergences are status-only;
  - `20` divergences also include structural field differences;
  - all comparable existing versions are already linked in matrix.
- Transition comparison:
  - fixture transition `TRAB_VOLUNTARIO_TERCEIRO_SETOR` `AAC-rev5 -> AEU-rev1` already exists in DB as `aac_para_aeu`, but with divergent `justificativa`;
  - no direct fixture transition is missing;
  - DB contains extra transition history outside fixture:
    - `25` `mesmo_eixo`;
    - `1` additional `aac_para_aeu` for `ParticipaÃ§Ã£o em projetos de extensÃ£o`;
    - `3` `nova_aeu`;
    - `1` `descontinuada` for `SIMULADOR_VOO`.
- High risks:
  - applying the fixture directly would fail or require reconciliation before the first norm;
  - high risk of duplicating bases where names are not exact matches;
  - `59` matrix links and `13` versioned requests depend on the current catalog;
  - any overwrite or recreation may break runtime/history;
  - `PROJETOS_EXTENSAO` requires explicit human decision because fixture canonizes one base while DB materialized distinct bases and its own transition.
- Medium risks:
  - `NRM-RT` namespace exists outside fixture;
  - fixture does not cover all transition history already persisted in `atividade_transicao`.
- Decision:
  - do not apply the fixture to `database.db`;
  - do not build a real importer yet;
  - next technical phase should be `D7.3F-PLAN`, read-only reconciliation planning only.
- Recommended next step:
  - `D7.3F-PLAN` - build a read-only reconciliation matrix for each norm/base/version/transition with explicit outcomes:
    - map to existing;
    - create new;
    - preserve existing;
    - do not apply;
    - require human decision;
    - never overwrite a version already used in matrix or request without an explicit plan.

### D7.3F-PLAN - reconciliation matrix between fixture and real database
- Accepted as a read-only reconciliation plan between the canonical fixture and the current real database.
- No code, fixture, importer, test, requirements, database, script, migration, or seed change was made during D7.3F-PLAN.
- Execution state observed during the plan:
  - initial `HEAD` `f10db80`;
  - branch `recovery/d7-activity-versioning`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - working tree clean;
  - SQLite connection opened only by URI read-only mode (`mode=ro`);
  - no file or database was altered during the diagnosis.
- Real database preserved:
  - before: `528384` bytes;
  - SHA256 before: `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
  - after: `528384` bytes;
  - SHA256 after: `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.
- Reconciliation matrix summary:
  - `30` fixture activities have preservable mappings to existing bases;
  - `59` of `61` fixture versions have an existing preservable candidate;
  - the `2` pending versions were `VISITAS_TECNICAS_PROFESSORES` in `AAC-rev5` and `AAC-rev6`;
  - all versions `1..59` are already linked in `matriz_atividade_versao_item`;
  - versions `2`, `8`, `10`, `56`, and `58` also appear in versioned request snapshots;
  - `atividade_versao.id=60` is runtime `NRM-RT-2cb9b503` and must remain outside official fixture reconciliation;
  - fixture transition `TRAB_VOLUNTARIO_TERCEIRO_SETOR` `AAC-rev5 -> AEU-rev1` already exists as `atividade_transicao.id=27`, but with divergent `justificativa`.
- Architectural decision closed for `PROJETOS_EXTENSAO`:
  - preserve the current split in the live database;
  - do not collapse it into a single base;
  - preserve `base27` / `v52` / `v53` for extension projects;
  - preserve `base8` / `v51` for institutional support projects;
  - preserve the extra persisted `aac_para_aeu` transition already present in runtime history;
  - human decision closed: keep the runtime split.
- Architectural decision closed for `VISITAS_TECNICAS_PROFESSORES`:
  - do not auto-map it to `base6`;
  - `base6` is too generic for a safe canonical mapping;
  - if a future apply phase is approved, create a new specific `atividade_base` plus draft versions for `AAC-rev5` and `AAC-rev6`;
  - this closeout does not authorize any real creation now;
  - human decision closed: future draft creation, not remapping to `base6`.
- Frozen reconciliation rules:
  - never overwrite `atividade_versao.id=1..59`;
  - never overwrite versions with versioned request snapshots: `2`, `8`, `10`, `56`, `58`;
  - never overwrite `atividade_transicao.id=1..31`;
  - never alter `NRM-RT*` runtime items;
  - any future structural reconciliation must happen through a new draft version or explicit mapping, never by overwrite.
- Runtime items outside fixture remain `PRESERVE_EXISTING / OUT_OF_FIXTURE`:
  - `NRM-RT`;
  - `NRM-RT-5c96604e`;
  - `NRM-RT-2cb9b503`;
  - `Runtime Base`;
  - `Runtime Base 5c96604e`;
  - `Runtime Base 2cb9b503`.
- Risk classification after closeout:
  - critical: overwriting versions already used in matrix or versioned requests;
  - critical: reconciling `PROJETOS_EXTENSAO` without preserving the live split;
  - high: mapping `VISITAS_TECNICAS_PROFESSORES` to `base6` without explicit approval;
  - high: changing `NRM-RT` runtime items;
  - medium: future reconciliation of structural differences in group / workload / limits;
  - low: textual divergences when IDs and persisted history are preserved.
- Recommended next step:
  - `D7.3G-PLAN-APPLY` may now be planned after this closeout;
  - `D7.3G` must still be planning only, not real apply;
  - any real apply requires intact backup, item-by-item plan, dry-run against a copy, and explicit approval.

### D7.3G-PLAN-APPLY - future technical apply plan
- Accepted as a read-only future apply plan derived from the frozen D7.3F reconciliation decisions.
- No code, fixture, importer, test, requirements, database, script, migration, or seed change was made during D7.3G-PLAN-APPLY.
- Execution state observed during the plan:
  - initial `HEAD` `da869e9`;
  - branch `recovery/d7-activity-versioning`;
  - remotes aligned;
  - working tree clean;
  - `database.db` intact at `528384` bytes;
  - SHA256 `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.
- Scope of any future apply was narrowed explicitly:
  - it is not a general reconciliation;
  - it is not a real import of the whole fixture;
  - it is only a plan for a possible future `CREATE_DRAFT` path for `VISITAS_TECNICAS_PROFESSORES`.
- `PRESERVE / NO-OP` set frozen for any future apply:
  - norms `AAC-rev5`, `AAC-rev6`, `AEU-rev1`;
  - all already reconciled bases and versions;
  - `atividade_versao.id=1..59`;
  - `atividade_transicao.id=1..31`;
  - `matriz_norma`;
  - `matriz_atividade_versao_item`;
  - `requisicoes`;
  - runtime `NRM-RT*`.
- `PROJETOS_EXTENSAO` remains preserve-only:
  - preserve live split;
  - preserve `base8` / `v51`;
  - preserve `base27` / `v52` / `v53`;
  - preserve the extra persisted `aac_para_aeu` transition;
  - do not collapse.
- `CREATE_DRAFT` remains the only future write path allowed in principle:
  - create `1` new specific `atividade_base` for `VISITAS_TECNICAS_PROFESSORES`;
  - create `1` draft `atividade_versao` for `AAC-rev5`;
  - create `1` draft `atividade_versao` for `AAC-rev6`;
  - do not create matrix links;
  - do not create transitions;
  - do not touch requests.
- `FORBIDDEN` set frozen for the future apply:
  - overwrite of any existing `atividade_versao`;
  - status change `ativa -> rascunho`;
  - any matrix alteration;
  - any request or snapshot alteration;
  - any change to existing transitions;
  - any change to runtime `NRM-RT*`;
  - collapsing `PROJETOS_EXTENSAO`;
  - creating new AAC/AEU norms;
  - creating new versions for already mapped activities;
  - creating new transitions in the initial apply.
- Mandatory preconditions for any future real apply:
  - intact and verifiable backup of `database.db`;
  - recorded size and SHA256 before execution;
  - execution first against a DB copy;
  - logical before/after diff report;
  - explicit rollback path;
  - explicit human approval;
  - focused post-apply tests;
  - guaranteed `+0` changes to matrix, requests, transitions, and norms.
- Recommended next step:
  - `D7.3H-IMPL-PLAN-SCRIPT` may be planned after this closeout;
  - D7.3H must still begin as script implementation planning;
  - no real apply is authorized at this point.

### D7.3H-PATCH1 - controlled reconciliation apply script
- Implemented, audited, and accepted.
- New files:
  - `tools/d73h_reconciliation_apply.py`
  - `tests/test_d73h_reconciliation_apply.py`
- Scope delivered:
  - controlled `plan/apply` script for the only future write case admitted by D7.3G:
    `CREATE_DRAFT` of `VISITAS_TECNICAS_PROFESSORES`;
  - `--plan` always opens the target DB by read-only URI mode;
  - `--apply` only operates on an explicit safe copy passed by `--db-copy`;
  - live `database.db` is refused for `--apply`;
  - `--apply` requires `--backup-path`, `--backup-confirmed`, and
    `--allow-create-visitas-professores`.
- Write scope allowed by the script:
  - `+1` `atividade_base`;
  - `+2` `atividade_versao` with `status='rascunho'`;
  - `+0` `norma_atividade`;
  - `+0` `atividade_transicao`;
  - `+0` `matriz_atividade_versao_item`;
  - `+0` `requisicoes`.
- Guarantees preserved:
  - no general apply/import path;
  - no overwrite of existing versions;
  - does not touch `PROJETOS_EXTENSAO`;
  - does not touch runtime `NRM-RT*`;
  - does not use `base6`/`base7` as destination;
  - does not alter existing versions;
  - does not alter matrix links;
  - does not alter requests;
  - does not alter transitions.
- Validations accepted:
  - real `database.db` preserved during implementation/review/closeout:
    - before: `528384` bytes;
    - SHA256 before: `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
    - after: `528384` bytes;
    - SHA256 after: `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
  - focused test suite:
    - `python -m pytest tests/test_d73h_reconciliation_apply.py -q --tb=short`
    - result: `17 passed`;
  - CLI `plan` text validated;
  - CLI `plan` JSON validated;
  - `apply` against a temporary DB copy validated;
  - `apply` against live `database.db` refused with clear error;
  - `git diff --check` clean.
- Audit result:
  - `D7.3H-PATCH1-REVIEW` accepted the patch;
  - no blocking/high/medium/low findings;
  - non-blocking observation: the suite does not assert the default behavior
    without `--plan/--apply` and the mutual exclusion by direct CLI execution,
    but the behavior is implemented and was audited as correct.
- Residual risks:
  - the script assumes `AAC-rev5=id=1` and `AAC-rev6=id=2`;
  - `documentos_json` remains `NULL` in D7.3H-v1 by design;
  - partial/conflicting state fails intentionally instead of attempting repair.
- Next step after this closeout:
  - D7.3H is closed at the script/documentation level;
  - no real apply on the live database is authorized;
  - any future phase must be an explicit decision either to execute only on a
    controlled DB copy or to stop the trail without applying to live.

### D7.3I-VALIDATE-APPLY-COPY - validation of apply on a controlled DB copy
- Accepted.
- Scope executed:
  - validated `tools/d73h_reconciliation_apply.py`;
  - ran `--apply` only against a temporary copy of `database.db`;
  - used `--backup-path`, `--backup-confirmed`, and
    `--allow-create-visitas-professores`;
  - performed no write against live `database.db`.
- Result of the apply on the DB copy:
  - process returned `0`;
  - `mode=apply`;
  - `disposition=create`;
  - records created in the copy:
    - `atividade_base.id=37`;
    - `atividade_versao.id=61`, `AAC-rev5`, `status=rascunho`;
    - `atividade_versao.id=62`, `AAC-rev6`, `status=rascunho`.
- Confirmed deltas in the copy:
  - `atividade_base`: `35 -> 36` (`+1`);
  - `atividade_versao`: `60 -> 62` (`+2`);
  - `norma_atividade`: `6 -> 6` (`+0`);
  - `atividade_transicao`: `31 -> 31` (`+0`);
  - `matriz_atividade_versao_item`: `59 -> 59` (`+0`);
  - `requisicoes`: `41 -> 41` (`+0`).
- Before/after comparison:
  - remained unchanged:
    - `norma_atividade`;
    - `atividade_transicao`;
    - `matriz_atividade_versao_item`;
    - `requisicoes`;
    - all pre-existing rows of `atividade_base`;
    - all pre-existing rows of `atividade_versao`;
  - only observed effect: insertion of the 3 expected records in the copy.
- Guardrails confirmed:
  - `base6`/`base7` exist, but were treated as prohibited candidates;
  - `base6`/`base7` were not used as destination;
  - `PROJETOS_EXTENSAO` was not touched;
  - `NRM-RT*` was not touched.
- Live `database.db`:
  - was not a write target;
  - size before/after: `528384` bytes;
  - SHA256 before/after:
    `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.
- Conclusion:
  - validation on a DB copy passed;
  - the script behaved correctly in the controlled scenario;
  - this still does **not** authorize real apply on live.
- Next step after this closeout:
  - D7.3I is closed at the validation/documentation level;
  - the next decision must be explicit:
    - either end the trail without any real apply;
    - or open a separate decision/risk phase for a possible future live apply;
  - no real apply is authorized by this closeout.

### D7.3J-LIVE-APPLY-CREATE-DRAFT - live create-draft execution and suite stabilization
- Accepted.
- Initial state before the live apply:
  - `HEAD=aedf936`;
  - branch `recovery/d7-activity-versioning`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - live `database.db` before apply:
    - `528384` bytes;
    - SHA256
      `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`.
- Backup created:
  - `backups/database.pre-d73j-live-apply-20260612-165031.db`;
  - `528384` bytes;
  - SHA256
    `AD8CD589D190489580BD6E3FC82E90DD146B376FAA6D259722376732D3C44A88`;
  - backup matches the initial live DB.
- Live apply execution model:
  - executed first only against a controlled DB copy;
  - then live `database.db` was replaced by the validated copy;
  - no manual SQL was executed;
  - there was no direct apply against the live file;
  - script used: `tools/d73h_reconciliation_apply.py`.
- Records created in live:
  - `atividade_base.id=37`;
  - `atividade_versao.id=61`, `norma_codigo=AAC-rev5`, `status=rascunho`,
    `eixo=AAC`;
  - `atividade_versao.id=62`, `norma_codigo=AAC-rev6`, `status=rascunho`,
    `eixo=AAC`.
- Final deltas in live:
  - `atividade_base`: `35 -> 36` (`+1`);
  - `atividade_versao`: `60 -> 62` (`+2`);
  - `norma_atividade`: `6 -> 6` (`+0`);
  - `atividade_transicao`: `31 -> 31` (`+0`);
  - `matriz_atividade_versao_item`: `59 -> 59` (`+0`);
  - `requisicoes`: `41 -> 41` (`+0`).
- Guarantees confirmed:
  - no new norm;
  - no new transition;
  - no new matrix link;
  - no request changed;
  - no old version changed;
  - `PROJETOS_EXTENSAO` was not touched;
  - `NRM-RT*` was not touched;
  - `base6`/`base7` were treated as prohibited candidates and not used as
    destination;
  - versions `61/62` remained `rascunho` and without matrix link.
- Live final signature:
  - `528384` bytes;
  - SHA256
    `09C0791A00B9A6EAB3BABC7E8349E8582092ADE6EB911798CE55062819A48E1A`.
- Post-apply test anomaly:
  - after the live apply, `4` focused D7.3H tests failed;
  - cause: the tests assumed `REAL_DB_PATH` still reflected the pre-apply state;
  - that assumption became invalid because live had moved to post-apply;
  - this was not a script defect and not a data defect.
- D7.3J-PATCH1-TEST-STABILIZE:
  - changed only `tests/test_d73h_reconciliation_apply.py`;
  - create-path tests now use a temporary controlled pre-apply scenario;
  - already-exists / idempotency tests now use a temporary controlled
    post-apply scenario;
  - the fallback without backup removes only the 3 D7.3J rows in a temporary
    copy;
  - if `VISITAS_TECNICAS_PROFESSORES` gains more complex links or state in the
    future, the helper fails on purpose instead of masking the new scenario.
- Validations after stabilization:
  - focused pytest:
    - `python -m pytest tests/test_d73h_reconciliation_apply.py -q --tb=short`
    - result: `18 passed`;
  - live `plan` JSON updated:
    - `status=ok`;
    - `mode=plan`;
    - `disposition=already_exists`;
    - `planned_counts={"atividade_base": 0, "atividade_versao": 0}`;
    - `planned_actions=[]`;
    - `created_ids={"atividade_base": null, "atividade_versao": []}`;
  - live counts:
    - `atividade_base=36`;
    - `atividade_versao=62`;
    - `norma_atividade=6`;
    - `atividade_transicao=31`;
    - `matriz_atividade_versao_item=59`;
    - `requisicoes=41`.
- Git operational note:
  - `database.db` is ignored by the repository;
  - `git status --short` can appear clean after an operational DB change;
  - `git status --short --ignored` shows `database.db`, `database.db-wal`,
    `database.db-shm`, backups, and `tmp/` as ignored;
  - none of those artifacts must be committed.
- Final D7.3J state:
  - `VISITAS_TECNICAS_PROFESSORES` was created in live as draft;
  - it was not activated;
  - it was not linked to any matrix;
  - it did not alter requests;
  - it did not alter transitions;
  - it did not alter norms;
  - no refactor was performed.
- Next step after this closeout:
  - D7.3J is closed after this documental commit/push;
  - the next phase, if any, must be a separate decision:
    - `D7.3K-DECIDE-MATRIX-LINK`, if matrix linking of the draft versions is
      needed;
    - or close the D7.3 trail with no immediate follow-up;
  - no activation or matrix link is authorized by this closeout.

### D7.3K-DECIDE-MATRIX-LINK - read-only matrix link diagnosis and final D7.3 decision
- Accepted.
- Execution mode:
  - read-only architectural / operational diagnosis only;
  - no file edits in the diagnosis phase;
  - no DB writes in the diagnosis phase;
  - only Git inspection, file reads, SQLite `SELECT` and `PRAGMA` in
    `mode=ro`.
- Initial state confirmed before diagnosis:
  - branch `recovery/d7-activity-versioning`;
  - `HEAD=b8ad2ae`;
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`;
  - `origin/main...main = 0 0`;
  - `git status --short` was empty;
  - live `database.db`:
    - `528384` bytes;
    - SHA256
      `09C0791A00B9A6EAB3BABC7E8349E8582092ADE6EB911798CE55062819A48E1A`.
- Operational guarantees confirmed:
  - no file was changed during the diagnosis phase;
  - no bank was changed during the diagnosis phase;
  - no apply was executed;
  - no manual SQL was executed;
  - no activation was executed;
  - no matrix link was executed.
- Live state confirmed by read-only queries:
  - `atividade_base.id=37` exists and is `status='ativo'`;
  - `atividade_versao.id=61` exists, `AAC-rev5`, `status='rascunho'`,
    `eixo='AAC'`;
  - `atividade_versao.id=62` exists, `AAC-rev6`, `status='rascunho'`,
    `eixo='AAC'`;
  - both have no row in `matriz_atividade_versao_item`;
  - both have no row in `requisicoes`;
  - both have no row in `atividade_transicao` as origin or destination.
- Live counts confirmed:
  - `atividade_base=36`;
  - `atividade_versao=62`;
  - `norma_atividade=6`;
  - `atividade_transicao=31`;
  - `matriz_atividade_versao_item=59`;
  - `requisicoes=41`.
- Matrix diagnosis:
  - matrix `1` has `AAC-rev6` in `matriz_norma`;
  - matrix `2` has `AAC-rev5` in `matriz_norma`;
  - however, there is no real candidate matrix now because `atividade_base.id=37`
    has no row in `atividade_legacy_map` and therefore is outside the legacy
    scope of every matrix.
- Technical rule confirmed:
  - matrixâ†’`atividade_versao` link requires version `status='ativa'`;
  - the admin UI lists only active versions as available options;
  - the route also requires the base to be in the matrix legacy scope;
  - the route also requires the version norm to be present in `matriz_norma`.
- Architectural decision:
  - do not activate `61/62` now;
  - do not link `61/62` now;
  - keep both versions as `rascunho`;
  - close D7.3 with no additional DB action.
- Reason for the decision:
  - a draft version cannot be linked;
  - isolated activation would still be insufficient;
  - there is no legitimate legacy mapping for base `37`;
  - forcing a mapping now would create collision risk without proven
    operational need.
- Future prohibition recorded:
  - do not reuse `base6` / `base7` as destination to resolve base `37`;
  - do not activate or link `61/62` without a new separate phase.
- Future phase permitted only if a real operational need appears:
  - decide the correct legacy activity to map to base `37`;
  - create or validate the legacy mapping;
  - activate the correct version;
  - link explicitly to the correct matrix;
  - test the resolver and the admin link route.
- Final D7.3 conclusion:
  - D7.3J created the controlled draft versions;
  - D7.3K decided not to expose, activate, or link them;
  - the D7.3 trail is closable with no further action now.

### D7.5C - matrix-scoped activity creation from the matrix screen
- Implemented, visually validated by the user, and committed.
- Functional commit `bc8a4f6` - `Add matrix-scoped activity creation`.
- Scope delivered:
  - generic button `+ Nova atividade` in the left-column header of the matrix
    edit screen;
  - same behavior in tabs `Lista de AAC` and `Lista de AEU`;
  - modal/form opened from the matrix screen;
  - server-scoped POST route for matrix activity creation;
  - initial `atividade_versao` created together with the new activity.
- Backend guarantees:
  - server infers context by tab/route: `aac -> AAC`, `aea -> AEU`;
  - matrix must exist;
  - compatible active norm is required for the current axis;
  - if multiple compatible active norms exist, explicit `norma_id` is required;
  - no fallback to the first active norm;
  - full rollback on intermediate failure;
  - CSRF-protected POST.
- Persistence guarantees:
  - creates legacy `atividades` row;
  - creates `atividade_base`;
  - creates `atividade_legacy_map`;
  - creates initial `atividade_versao` with `status='ativa'`;
  - when `Adicionar à matriz atual` is checked, also creates:
    - `matrizes_atividades_itens`;
    - `matriz_atividade_versao_item`.
- Contract preserved:
  - matrix remains the practical flow for scoped creation;
  - matrix name is used only as contextual UI label;
  - matrix name is not written into `codigo_normativo`;
  - `codigo_normativo` remains the norm/regulation code;
  - no schema or migration change;
  - no `database.db` edit in this closeout;
  - no D7.5D menu/card behavior was implemented.
- Focused validation:
  - `python -m pytest tests/test_admin_matrizes.py tests/test_admin_matrizes_csrf_ui.py tests/test_admin_matriz_versao_link.py tests/test_admin_matrix_new_activity.py -q --tb=short`
  - result: `28 passed`.
- New focused test file:
  - `tests/test_admin_matrix_new_activity.py`.
- Next authorized phase:
  - `D7.5D-PATCH-CARD-VERSION-MENU`.
- D7.5D was pending at D7.5C closeout and is now complete (see below).

### D7.5D - card version menu on linked activity cards
- Implemented, visually validated by the user (including R1 visual alert fix), and committed.
- Functional commit `0dbd2b1` - `Add matrix card version creation`.
- Scope delivered:
  - `⋮` button on right-column (selected/linked) activity cards in the matrix edit screen;
  - `Criar nova versão` action opens a modal with norma select and context label;
  - context label: `Versão nesta matriz: [codigo_normativo]` for orientation;
  - POST route `admin_matriz_nova_versao_card` at
    `/admin/matrizes/<int:matriz_id>/atividades/<int:atividade_id>/nova-versao`.
- Backend guarantees:
  - creates new `atividade_versao` if `(atividade_base_id, norma_id)` does not exist;
  - reuses existing `atividade_versao` if the same pair already exists;
  - UNIQUE constraint `(atividade_base_id, norma_id)` always respected;
  - only the current matrix is relinked via `_set_versao_da_matriz_para_base`;
  - older matrices keep their original version link — no cross-matrix mutation;
  - no in-place `UPDATE` of a version already used by older matrices or requests;
  - matrix name is not written into `codigo_normativo`;
  - full rollback on any intermediate failure;
  - CSRF-protected POST.
- Read-only helper `get_card_version_menu_data` added to `main.py`:
  - returns alternative normas for each linked activity in the current matrix;
  - serialized to JS variable via `card_version_menu_data | tojson`.
- R1 visual alert correction:
  - warning `<p class="matriz-modal-warning">` replaced with
    `<div class="flash flash-warning" role="alert">`;
  - no new CSS; reuses system-wide `flash flash-warning` style
    (`#fef4c0` background, 13px font).
- Contract preserved:
  - no schema or migration change;
  - no `database.db` edit in this closeout;
  - no student flow change;
  - D7.5C preserved and not reopened.
- Focused validation:
  - `python -m pytest tests/test_admin_matriz_nova_versao_card.py -q --tb=short`
  - result: `15 passed`.
- New focused test file:
  - `tests/test_admin_matriz_nova_versao_card.py` (15 tests: T01–T15).
- Next authorized phase:
  - `D7.5E-CARD-VERSION-BADGE-UI`.
- D7.5E must preserve:
  - show version label on the card without changing card height;
  - first line: truncated activity name + version label at right edge;
  - no overlap between name and label;
  - no table transformation;
  - preserve D7.5C and D7.5D behavior.

### D7.6B2 - operational version numbers for atividade_versao

- Implemented, hardened (R1 + R2), and accepted.
- Commits:
  - `1ca00a3` — `Add operational activity version numbers`
  - `5184143` — `D7.6B2-R1: fix numero_versao DEFAULT 0 -> DEFAULT 1 in atividade_versao`
  - `6b1579a` — `D7.6B2-R2: harden numero_versao schema — full unique index + pos triggers`
- Schema changes delivered:
  - `atividade_versao.numero_versao INTEGER NOT NULL DEFAULT 1` added.
  - Old constraint `UNIQUE(atividade_base_id, norma_id)` removed.
  - New index: `UNIQUE INDEX idx_atividade_versao_base_num ON atividade_versao(atividade_base_id, numero_versao)` — full, non-partial (no WHERE clause).
  - `numero_versao >= 1` enforced by triggers `trg_atividade_versao_num_pos_insert` and `trg_atividade_versao_num_pos_update` for `database.db`; and by `CHECK(numero_versao >= 1)` in the DDL for fresh databases.
  - Existing rows migrated via `ROW_NUMBER() OVER (PARTITION BY atividade_base_id ORDER BY id ASC)`.
  - `AUTOINCREMENT` sequence preserved after migration.
- Operational model:
  - `numero_versao` is the operational version number: v1, v2, v3… per `atividade_base`, assigned sequentially.
  - `codigo_normativo` remains normative metadata (the regulation/norm code); it is not the operational version identifier or badge.
  - `norma_id` and `codigo_normativo` remain `NOT NULL` in this phase.
- Helpers added in `main.py`:
  - `get_next_numero_versao(conn, base_id)` — returns `MAX(numero_versao) + 1` for a base.
  - `get_ultima_versao_ativa_por_base(conn, base_id)` — returns the row with highest `numero_versao` where `status='ativa'`.
- All INSERTs into `atividade_versao` in routes and tests supply `numero_versao` explicitly via `get_next_numero_versao`.
- New test file: `tests/test_atividade_versao_numero.py` — 12 tests (T01–T12).
- Test results:
  - `tests/test_atividade_versao_numero.py`: 12/12 passed.
  - D7 regression suite (4 files): 45/45 passed.
- Backup before R2: `database.pre-D7.6B2-R2-hardening-20260613-184709.db`, 544.768 bytes,
  SHA256 `92627DED44C9094E74F01DA5718C995CD3FDD5AC467EF79298541A75B777CD8C`.
- Matrix visual adjustment not yet done; D7.6C complete; D7.6D remains pending.

### D7.6C - activity version menu on admin activities list

- Implementada e aceita.
- Commit: `62aed4b` — `Add activity version menu to admin activities`
- Closeout docs: `ed706c1` — `Record D7.6C activity version menu closeout`
- Escopo entregue:
  - Menu ⋮ exposto no hover/floating bar da tela `/admin/atividades`.
  - Menu contém três ações:
    - **Editar atividade** — navega para a rota existente de edição.
    - **Criar nova versão** — navega para `/admin/catalogo-versoes/<base_id>/nova-versao`.
    - **Ver versões** — navega para `/admin/catalogo-versoes/<base_id>`.
  - Ações "Criar nova versão" e "Ver versões" ficam `disabled` quando a atividade não possui `base_id` mapeado.
- Como `base_id` é obtido:
  - Subquery correlated na query principal de `/admin/atividades`:
    ```sql
    (SELECT atividade_base_id FROM atividade_legacy_map WHERE atividade_id_legacy = id) AS base_id
    ```
  - Atividades sem mapeamento retornam `NULL`; template usa `a.base_id or ''` → `data-base-id=""`.
- Arquivos alterados:
  - `main.py` (+6/-1): subquery `base_id` na query de `admin_atividades`.
  - `templates/admin_atividades.html` (+80/-7): `data-base-id` nos cards; botão ⋮ e dropdown `ativ-more-menu`.
  - `tests/test_admin_atividades_version_menu.py` (+233/0): 9 testes novos.
- Testes aceitos:
  - `tests/test_admin_atividades_version_menu.py`: 9/9 passed.
  - Regressões relacionadas (5 arquivos): 57/57 passed.
- Garantias preservadas:
  - Nenhum template da matriz alterado (`admin_matriz_form.html`, `admin_matriz_versoes.html`).
  - Schema e `database.db` não alterados.
  - `codigo_normativo` não exposto como badge operacional na lista de atividades.
  - `UNIQUE(atividade_base_id, norma_id)` não reintroduzida.
  - `numero_versao` via `get_next_numero_versao` preservado para criações futuras.
  - Push não realizado.
- Próxima fase: `D7.6D` — Matriz escolhe versão e card mostra vN.

### D7.6D - matrix chooses operational activity version

- Implementada e aceita.
- Commit: `2f81179` — `Make matrix choose operational activity versions`
- Escopo entregue:
  - Fluxo da matriz alterado de "criar versão por norma" para "escolher versão existente".
  - Card da matriz agora exibe badge `vN` baseado em `atividade_versao.numero_versao`.
  - `codigo_normativo` permanece metadado secundário (visível no modal como info), nunca como badge principal.
  - Modal de versão reformulado: lista versões existentes da mesma `atividade_base` em ordem decrescente de `numero_versao`; versão atual aparece pré-selecionada (`is_current: true`); usuário escolhe via radio buttons.
  - POST de escolha relinka apenas a matriz atual via `_set_versao_da_matriz_para_base`; não insere em `atividade_versao`.
  - POST valida que `versao_id` pertence à mesma `atividade_base` antes de relinkar.
  - POST rejeita `versao_id` de base diferente, `versao_id` inexistente e `versao_id` ausente.
- Helpers alterados em `main.py`:
  - `get_card_version_menu_data`: agora retorna `numero_versao` e lista `versoes` (não mais `normas`).
  - `get_vinculo_versao_da_matriz`: agora inclui `av.numero_versao` no SELECT.
  - Rota `admin_matriz_nova_versao_card`: não cria mais `atividade_versao`; apenas valida e relinka.
- Garantias preservadas:
  - `templates/admin_atividades.html` não foi alterado.
  - Schema e `database.db` não foram alterados.
  - `norma_id` e `codigo_normativo` permanecem `NOT NULL`.
  - `UNIQUE(atividade_base_id, numero_versao)` intacta.
  - Outras matrizes não são afetadas pelo relink.
  - CSRF obrigatório no POST.
  - Rollback total em erro intermediário.
  - Push não realizado.
- Testes aceitos:
  - `tests/test_admin_matriz_escolher_versao.py`: 10/10 passed (novo, T01–T10).
  - `tests/test_admin_matriz_nova_versao_card.py`: 13/13 passed (atualizado para semântica D7.6D).
  - Regressões relacionadas (6 arquivos): 64/64 passed.
- Arquivos alterados no commit:
  - `main.py` (M)
  - `templates/admin_matriz_form.html` (M)
  - `tests/test_admin_matriz_escolher_versao.py` (A — novo)
  - `tests/test_admin_matriz_nova_versao_card.py` (M — atualizado)
- Próxima fase recomendada:
  - `D7.6E` — garantir que nova matriz / atividade adicionada usa a última versão ativa por padrão.

### D7.6E - matrix defaults to latest active activity version

- Implementada e aceita.
- Commit: `e359047` — `Default matrix links to latest active activity versions`
- Escopo entregue:
  - Ao salvar lista de atividades da matriz (POST `editar_matriz` com `active_tab=aac/aea`), novo vínculo matriz → atividade_base recebe automaticamente a última `atividade_versao` ativa.
  - "Última versão ativa" definida por: `status='ativa'`, maior `numero_versao`.
  - Vínculo manual existente é preservado: `_ensure_default_versao_link` verifica `get_vinculo_versao_da_matriz` antes de criar novo link; se já existe, retorna sem alterar.
  - `_save_matriz_activity_links` não sobrescreve `matriz_atividade_versao_item` quando vínculo para aquela base já existe.
  - Caso sem versão ativa: nenhum link criado (comportamento documentado e testado no T09).
  - Atividade sem entrada em `atividade_legacy_map`: nenhum link criado (no-op silencioso).
- Helper adicionado em `main.py`:
  - `_ensure_default_versao_link(conn, matriz_id, activity_id)`: resolve `base_id` via `atividade_legacy_map`; verifica link existente; obtém última ativa via `get_ultima_versao_ativa_por_base`; cria link via `_set_versao_da_matriz_para_base`. Não commita.
- Garantias preservadas:
  - Matriz não cria `atividade_versao`: nenhum `INSERT INTO atividade_versao` no fluxo modificado.
  - Admin → Atividades não foi alterado.
  - `templates/admin_atividades.html` não foi alterado.
  - `templates/admin_matriz_form.html` não foi alterado nesta fase.
  - Schema e `database.db` não foram alterados.
  - `codigo_normativo` permanece metadado normativo, não badge operacional.
  - Push não realizado.
- Testes aceitos:
  - `tests/test_admin_matriz_latest_active_default.py`: 9/9 passed (novo, T01–T09).
  - Regressões relacionadas (7 arquivos): 74/74 passed.
- Arquivos alterados no commit:
  - `main.py` (M — +26 linhas)
  - `tests/test_admin_matriz_latest_active_default.py` (A — novo, 341 linhas)
- Estado conceitual final do D7.6:
  - Admin → Atividades cria versão.
  - Matriz escolhe versão existente via modal (D7.6D).
  - Card da matriz mostra `vN` (D7.6D).
  - Nova matriz / novo vínculo usa última versão ativa por padrão (D7.6E).
  - `codigo_normativo` permanece metadado normativo, não identificador operacional.

### D7.7A - runtime/UX post-push audit

- Aceita como auditoria read-only de runtime e UX pós-push.
- Nenhum código, template, teste, schema ou `database.db` alterado durante D7.7A.
- Problemas confirmados e transferidos como escopo da D7.7B1:
  - `get_card_version_menu_data` listava versões inativas/rascunho/descontinuadas/substituídas e versões cuja norma não pertence à matriz.
  - `admin_matriz_nova_versao_card` aceitava versão inválida (validava apenas mesma `atividade_base`, não `status` nem `norma_id` em `matriz_norma`).
  - `_ensure_default_versao_link` usava última versão ativa da base sem filtrar pela norma da matriz.
  - `_save_matriz_activity_links` removia `matrizes_atividades_itens` mas não limpava vínculos explícitos órfãos em `matriz_atividade_versao_item`.

### D7.7B1 - matrix version validity hardening

- Implementada e aceita.
- Commit aceito: `d53d9cd` — `Harden matrix version selection validity`.
- Escopo entregue:
  - `get_card_version_menu_data` agora lista apenas versões com `status='ativa'` cujo `norma_id` está em `matriz_norma` para a matriz; versões inativas, rascunho, descontinuadas, substituídas e de norma fora da matriz são excluídas do modal.
  - `admin_matriz_nova_versao_card` rejeita versões com `status != 'ativa'` ou cujo `norma_id` não está em `matriz_norma`; retorna flash + redirect sem alterar `matriz_atividade_versao_item`.
  - `_ensure_default_versao_link` usa query filtrada por `matriz_norma` para selecionar a última versão ativa cuja norma pertence à matriz (ORDER BY `numero_versao DESC LIMIT 1`); se não existir versão válida nas normas da matriz, nenhum link é criado.
  - `_save_matriz_activity_links` remove de `matriz_atividade_versao_item` os vínculos da matriz cujo `atividade_base_id` não está mais entre as bases selecionadas para o tab corrente; preserva vínculo manual quando a base continua selecionada; preserva vínculos do outro tab (AEA quando salvando AAC e vice-versa).
- Arquivos alterados:
  - `main.py`
  - `tests/test_admin_matriz_escolher_versao.py`
  - `tests/test_admin_matriz_latest_active_default.py`
- Testes aceitos:
  - focados: 28 passed (15 em `test_admin_matriz_escolher_versao.py` T01–T15, 13 em `test_admin_matriz_latest_active_default.py` T01–T13).
  - regressão D7.6 relacionada (7 arquivos): 84 passed.
  - suíte completa: 512 passed, 0 failed.
- Artifacts CSRF (`tests/_artifacts/csrf_inventory_shadow_*.json`) gerados pela suíte foram restaurados no cleanup R1 e não entraram no commit.
- `database.db` não alterado.
- Riscos residuais:
  - UX/template ainda não mostra alerta quando vínculo legado inválido deixa o modal sem opções elegíveis (template fora do escopo D7.7B1).
  - Catálogo/telas ainda podem expor `vN` com mais clareza (D7.7C).
  - Risco AEA cross-tab por bases compartilhadas entre tipos: baixo pelo invariante do schema, aceito como conhecido.
- Próxima etapa recomendada: D7.7B3 — verificação final pré-push e push; ou D7.7C — UX/template polish após publicação.

### D7.7C1 - operational version numbers in admin version UI

- Aprovada funcionalmente.
- Commit aceito: `99f4659` — `Show operational version numbers in admin version UI`.
- Escopo entregue:
  - catálogo de versões (`admin_catalogo_versao_detalhe.html`) exibe `vN` como identificador visual da versão.
  - `codigo_normativo` permanece visível como metadado normativo; semântica não alterada.
  - formulário de edição (`admin_catalogo_versao_form.html`) mostra a versão operacional que está sendo editada.
  - formulário de nova versão (`admin_catalogo_versao_form.html`) mostra a próxima `vN` prevista.
  - tela "Versões" da matriz (`admin_matriz_versoes.html`) mostra `vN` na versão atual e nas opções disponíveis.
- Arquivos alterados:
  - `main.py`
  - `templates/admin_catalogo_versao_detalhe.html`
  - `templates/admin_catalogo_versao_form.html`
  - `templates/admin_matriz_versoes.html`
  - `tests/test_admin_version_visibility_ui.py` (novo)
- Backend de validade D7.7B não foi alterado.
- Testes aceitos:
  - focados A (`readonly`, `version_form`, `matriz_link`): 52 passed.
  - focados B (`escolher_versao`, `latest_active_default`, `version_visibility_ui`): 38 passed.
  - suíte completa em lotes (batchSize=20, 66 arquivos, 4 lotes): 522 passed, 0 failed, 0 errors.
- Artifacts CSRF (`tests/_artifacts/csrf_inventory_shadow_*.json`) gerados pela suíte foram restaurados e não entraram no commit.
- `database.db` permaneceu não versionado; sem alteração.
- Riscos residuais:
  - warning LF→CRLF no Windows (comportamento git padrão, sem impacto funcional).
  - riscos de ambiguidade vN/código normativo reduzidos nesta tela.
  - menu hover-only de Admin → Atividades permanece como possível polish futuro.
- Próxima etapa recomendada: D7.7C3 — verificação final e push.

### D7.7C3 - final verify and push

- Approved.
- Push D7.7C executed with sucesso.
- Baseline publicado em origin/main:
  - `5c6859b` — `Fix D7.7C handoff current state`.
- Estado pós-push:
  - `origin/main...main = 0 0`;
  - HEAD local e remoto alinhados em `5c6859b`;
  - working tree limpo;
  - `git diff --check` limpo;
  - `git ls-remote origin main` confirmou `5c6859b459dfc5b39192985b9ba6e7957dc67b72` em `refs/heads/main`.
- Testes focados finais:
  - Lote A (`test_admin_version_visibility_ui.py`, `test_admin_activity_version_catalog_readonly.py`, `test_admin_activity_version_catalog_version_form.py`, `test_admin_matriz_versao_link.py`): 62 passed.
  - Lote B (`test_admin_matriz_escolher_versao.py`, `test_admin_matriz_latest_active_default.py`): 28 passed.
  - Total: 90 passed, 0 failed.
- Push `a157502..5c6859b main -> main`:
  - fast-forward limpo;
  - sem force, sem amend, sem rebase.
- Commits publicados no escopo D7.7C:
  - `99f4659` — `Show operational version numbers in admin version UI` (D7.7C1 funcional);
  - `c30c8b7` — `Record D7.7C version visibility closeout` (D7.7C2 docs);
  - `5c6859b` — `Fix D7.7C handoff current state` (D7.7C2-R2 docs fix).
- Nenhuma alteração de código, schema, template, tool ou `database.db` no push D7.7C3.
- `database.db` permanece não versionado (`git ls-files database.db` vazio).
- Riscos residuais:
  - AGENT_HANDOFF.md permaneceu referenciando HEAD `c30c8b7` e `0 2` até este closeout docs-only;
  - o HEAD real pós-push é `5c6859b`;
  - este descompasso é resolvido por D7.7C4, não por outro commit de "fix handoff current HEAD".
- Próxima etapa recomendada:
  - D7.7C4 — pós-push documentation sync (docs-only, apenas `PROJECT_STATE.md` e `AGENT_HANDOFF.md`);
  - ou encerrar D7.7 e abrir nova macrofase.

### D7.7C4 - post-push documentation sync

- Accepted.
- Escopo: docs-only harmonização pós-push. Apenas `PROJECT_STATE.md` e `AGENT_HANDOFF.md` alterados.
- Não houve alteração funcional, de schema, de `database.db`, de main.py, de templates, de tests ou de tools.
- Baseline funcional publicado permanece `5c6859b`.
- Commit docs-only:
  - mensagem: `Record D7.7C post-push documentation sync`;
  - novo HEAD documental criado após o push, sem reabrir nenhum escopo funcional.
- Push docs-only:
  - `5c6859b..<novo HEAD> main -> main`;
  - fast-forward limpo, sem force.
- Estado pós-push D7.7C4:
  - `origin/main...main = 0 0`;
  - `git ls-remote origin main` aponta para o novo HEAD criado por este docs-only;
  - working tree limpo.
- Nota explícita: o AGENT_HANDOFF.md registra `5c6859b` como baseline publicado e `0 0` como estado pós-push. Não criar novo commit de "fix handoff current HEAD" para perseguir o hash do próprio commit docs-only — o baseline funcional publicado permanece `5c6859b`.
- Próxima decisão fica a cargo do arquiteto:
  - encerrar D7.7;
  - abrir D7.7D read-only audit de polish restante (UX template, menu hover-only, alerta de vínculo legado inválido);
  - ou abrir nova macrofase.

### D7.6G2 - full suite remediation

- D7.6G2 aprovada.
- Commit aceito: `bdd5ddc` — `Fix legacy seeds and scripts for D7.6B2 UNIQUE(base,numero_versao) constraint`
- Suíte completa: 503 passed, 0 failed.
- Correções aplicadas:
  - Seeds legados em 7 arquivos de teste: adicionado cálculo de `numero_versao` via `COALESCE(MAX(numero_versao), 0) + 1` para garantir unicidade no `UNIQUE(atividade_base_id, numero_versao)`.
  - `tools/d73h_reconciliation_apply.py`: loop alterado para `enumerate(TARGET_NORMA_CODES, start=1)` atribuindo `numero_versao=idx` (AAC-rev5 → 1, AAC-rev6 → 2) por base.
  - Asserts de catálogo (`test_post_nova_versao_duplicate_rejected`, `test_post_editar_versao_duplicate_rejected_but_self_allowed`): valores esperados atualizados para refletir a remoção intencional de `UNIQUE(atividade_base_id, norma_id)` pelo D7.6B2. Ambos os asserts preservados (apenas valores ajustados).
  - Inventário CSRF (`test_csrf_inventory_audit.py`): rotas D7.6C e D7.6D adicionadas a `SPECIFIC_REGRESSION_TESTS` apontando para testes de regressão CSRF já existentes.
- Exceção de escopo aceita: `tests/_artifacts/csrf_inventory_shadow_off.json` e `tests/_artifacts/csrf_inventory_shadow_on.json` incluídos no commit `bdd5ddc`.
  - Justificativa: artifacts gerados deterministicamente pelo teste CSRF a cada execução; alterações refletem adição das rotas D7.6C/D com status `ok_specific_regression_test`; nenhuma rota classificada como `blocked_real_risk`; nenhum status existente rebaixado; `high_risk_routes=0` preservado; churn adicional em `/admin/mensagens/<message_key>/reset` é cosmético (entradas `msg_*`, sem impacto em segurança).
- `database.db`: não alterado. SHA256 `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`, 544768 bytes — inalterado antes e depois de todos os ciclos de teste.
- `main.py` e templates: não alterados em D7.6G2.
- Estado D7.6 consolidado (pós-G2):
  - Admin → Atividades cria versão com `numero_versao` único por base.
  - Matriz escolhe versão existente via modal (D7.6D); não cria `atividade_versao`.
  - Card da matriz exibe `vN` via `numero_versao`; `codigo_normativo` é metadado normativo, não badge principal.
  - Novo vínculo matriz→atividade_base usa automaticamente a última versão ativa por padrão (D7.6E); vínculo manual existente preservado.
  - `UNIQUE(atividade_base_id, numero_versao)` ativa; `UNIQUE(atividade_base_id, norma_id)` removida (D7.6B2).
  - Suíte completa 503 passed, 0 failed — verde.

## Relevant Commits

- `483f069` - Add controlled versioned snapshot write for requests
- `ba5a3df` - Document snapshot write activation runbook
- `8845dce` - Record controlled snapshot activation validation
- `18c169a` - Record target snapshot activation validation
- `bb1ca51` - Add admin snapshot diagnostics
- `b9ffda2` - Add admin snapshot comparison display
- `09749ef` - Fix snapshot comparison labels
- `e0427ee` - Add activity version matrix contract tests
- `73d45ac` - Add read-only activity version catalog
- `a3537cf` - Fix activity version catalog card grids
- `b91d03f` - Add create forms for activity base and norms
- `44d367a` - Clarify activity version creation placeholder
- `16b1480` - Add draft activity version creation
- `ccf1a7e` - Record D7.2B3 draft version creation
- `c90ffe3` - Add draft activity version editing
- `28d922d` - Add draft activity version activation
- `255ff80` - Add admin UI for explicit matrix→atividade_versao links (D7.2B4)
- `f235f62` - Add admin lifecycle transitions for atividade_versao (D7.2B5)
- `9d2e9fb` - Add explicit activity version substitution
- `5f7dbc8` - Record D7.2B5-PATCH2 substitution closeout
- `95cb897` - Add admin transition history for activity versions
- `cbde400` - Record D7.3A normative canonization
- `5f66239` - Add D7.3C canonical normative fixture and docs closeout
- `45dd39d` - Add D7.3D normative dry-run importer
- `da869e9` - Record D7.3F reconciliation matrix decisions
- `ecdc9f5` - Add D7.3H controlled reconciliation apply script
- `aedf936` - Record D7.3I apply copy validation
- `b8ad2ae` - Record D7.3J live draft creation and stabilize tests
- `b5aafa7` - Record D7.3K matrix link decision
- `6a9bf2d` - Update CSRF inventory artifacts after D7 merge (pre-D7.5C main baseline)
- `bc8a4f6` - Add matrix-scoped activity creation
- `cdbc7ab` - Record D7.5C matrix activity creation closeout
- `0dbd2b1` - Add matrix card version creation
- `3d3c4ff` - Record D7.5D matrix card version closeout
- `1ca00a3` - Add operational activity version numbers
- `5184143` - D7.6B2-R1: fix numero_versao DEFAULT 0 -> DEFAULT 1 in atividade_versao
- `6b1579a` - D7.6B2-R2: harden numero_versao schema — full unique index + pos triggers
- `62aed4b` - Add activity version menu to admin activities
- `ed706c1` - Record D7.6C activity version menu closeout
- `2f81179` - Make matrix choose operational activity versions
- `79e11a2` - Record D7.6D matrix version selection closeout
- `e359047` - Default matrix links to latest active activity versions
- `088da75` - Record D7.6E latest active version default closeout
- `bdd5ddc` - Fix legacy seeds and scripts for D7.6B2 UNIQUE(base,numero_versao) constraint
- `d72f985` - Record D7.6G full suite remediation closeout
- `01aaa0f` - Fix D7.6G handoff current HEAD
- `d53d9cd` - Harden matrix version selection validity
- `99f4659` - Show operational version numbers in admin version UI
- `c30c8b7` - Record D7.7C version visibility closeout
- `5c6859b` - Fix D7.7C handoff current state

## Current Risks And Limits

- D6.6 remains admin-only display work, not an operational read path based on snapshot data.
- Snapshot data must not be used to approve or reject requests.
- Snapshot data must not be used to calculate hours or limits.
- Snapshot data must not be used for matrix scope, dashboards, import flow, or student screens.
- Import flow remains out of scope.
- Student dashboards and progress remain on the legacy path.
- Backfill for old requests has not been performed yet.
- D6.7 concluded with the recommendation to pause at D6.6 rather than expand snapshot surfaces now.
- D7.1 proved the contract for `turma.matriz_id == NULL` but did not introduce any new runtime surface.
- D7.2B1 created the read-only admin catalog, but the new screens are not linked from the menu/sidebar yet.
- D7.2B2 only delivered controlled creation of `atividade_base` and `norma_atividade`.
- D7.2B3-PATCH1 delivered controlled creation of `atividade_versao` in rascunho
  (commit `16b1480` / `ccf1a7e`).
- D7.2B3-PATCH2 delivered controlled editing of `atividade_versao` em rascunho
  (commit `c90ffe3`). Versões com `status != 'rascunho'` e versões com qualquer
  uso em matriz, requisição ou transição estão protegidas contra edição.
- The `Criar versão` button is now enabled in the detail of each `atividade_base`
  and points to the new draft creation form.
- All `atividade_versao` created by PATCH1/2 are inserted with `status = 'rascunho'`
  and are not yet usable by any matrix.
- The legacy mapping (`mapeamento-legado`) remains read-only.
- The matrix still does not choose `atividade_versao_id` through the UI.
- Versões que já estão em uso (matriz, requisição, transição) ficam imutáveis
  pela rota de edição — qualquer alteração futura exigiria nova versão.
- Ativação de versão (rascunho→ativa) foi implementada no PATCH3.
- Vínculo explícito matriz→versão foi implementado em D7.2B4-PATCH1.
- Inativação e descontinuação de versão foram implementadas em D7.2B5-PATCH1.
- Substituição explícita de versão foi implementada em D7.2B5-PATCH2:
  - exige `to_versao_id` explícito;
  - marca origem como `substituida`;
  - cria `atividade_transicao` com `tipo_transicao='mesmo_eixo'`;
  - bloqueia origem com vínculo em matriz;
  - bloqueia origem/destino com transição prévia como `from`.
- D7.2B6 adicionou histórico administrativo read-only no detalhe da atividade-base
  e foi publicada no commit `95cb897`.
- Catálogo pode ter múltiplas versões ativas; ambiguidade é controlada
  pelo vínculo explícito em `matriz_atividade_versao_item` (max 1 por matriz+base).
- Não há auditoria de quem ativou/inativou/descontinuou/substituiu versão.
- D7.3A realizou canonização documental dos regulamentos AAC/AEU (read-only, sem código).
- D7.3B-PLAN especificou o formato do fixture YAML (controlled vocabulary, mapping ao schema).
- D7.3C criou o fixture canônico: `normative_fixtures/d73c_normative_fixture.yaml`.
  - 32 atividades únicas, 61 versões totais, 3 normas.
  - 2 removidas (AAC-rev6), 3 nativas AEU, 1 transição explícita (AAC→AEU).
  - YAML validado, sem erros de estrutura ou valores inválidos.
- Importação de dados reais ainda não foi executada; fixture está pronto para D7.3D.
- D7.3D entregou o importador dry-run (tools/d73d_normative_importer_dryrun.py).
  A importação real para database.db ainda não foi executada.
- D7.3E-RO1 confirmou, em modo read-only, que fixture e banco real não convergem de forma aplicável sem reconciliação.
- O dry-run atual abortaria na primeira norma divergente se apontado para o banco real; ele não deve ser promovido para `apply`.
- O banco real contém dependências operacionais relevantes no catálogo versionado atual:
  - `59` vínculos em `matriz_atividade_versao_item`;
  - `13` requisições com snapshot/versionamento preenchido;
  - namespace `NRM-RT` fora da fixture;
  - histórico adicional em `atividade_transicao`.
- D7.3F-PLAN fechou as decisões humanas pendentes:
  - `PROJETOS_EXTENSAO` permanece dividido entre apoio institucional e extensão;
  - `VISITAS_TECNICAS_PROFESSORES` não deve mapear para `base6` e exigirá criação futura específica se houver apply aprovado.
- Versões `1..59` e transições `1..31` ficam congeladas contra overwrite em qualquer plano futuro.
- D7.3G-PLAN-APPLY estreitou formalmente o apply futuro ao caso `CREATE_DRAFT` de `VISITAS_TECNICAS_PROFESSORES`.
- D7.3H-PATCH1 entregou o script controlado `tools/d73h_reconciliation_apply.py`
  e sua suíte focada `tests/test_d73h_reconciliation_apply.py`.
- O script de D7.3H não autoriza apply real no `database.db`; ele apenas cria um
  caminho controlado para `plan` e para `apply` em cópia segura.
- D7.3I validou esse `apply` em cópia temporária e confirmou os deltas esperados:
  `+1` `atividade_base`, `+2` `atividade_versao`, `+0` nas demais tabelas
  monitoradas.
- D7.3J executou o `CREATE_DRAFT` controlado no live e criou
  `atividade_base.id=37` e `atividade_versao.id=61/62`, ambas em `rascunho`.
- O live agora contém esses 3 novos registros com `+0` mudanças em normas,
  transições, vínculos de matriz e requisições.
- D7.3K confirmou, em modo read-only, que `61/62` não podem ser vinculadas no
  estado atual: seguem `rascunho`, a UI aceita apenas versões ativas e
  `atividade_base.id=37` não está no escopo legado de nenhuma matriz.
- `VISITAS_TECNICAS_PROFESSORES` não está mais pendente de criação e também não
  seguirá para ativação ou vínculo nesta trilha.
- `documentos_json` permanece `NULL` em D7.3H-v1.
- A decisão final da trilha é encerrar D7.3 sem ativar nem vincular `61/62`.
- Nenhum apply adicional no live, nenhuma ativação e nenhum vínculo de matriz
  estão autorizados sem nova fase explícita e necessidade operacional real.
- D7.4F (read-only archive audit) confirmou estado esperado; nenhuma divergência.
- D7.4G arquivou a branch `recovery/d7-activity-versioning`:
  - tag `archive/d7-activity-versioning` criada e publicada em
    `b5aafa7605bab4f8ef4b61885ec5200627ea2f0b`;
  - branch remota `recovery/d7-activity-versioning` deletada;
  - `main` / `origin/main` em `6a9bf2d`;
  - `database.db` preservado: `528384` bytes;
    SHA256 `09C0791A00B9A6EAB3BABC7E8349E8582092ADE6EB911798CE55062819A48E1A`.
- D7 está integrada em `main`. Qualquer nova fase parte de `main`, não da
  branch archivada. Não existe branch ativa `recovery/d7-activity-versioning`
  no remoto.
- D7.6B2 concluída: schema operacional de `numero_versao` em `atividade_versao` entregue e endurecido.
  - `UNIQUE(atividade_base_id, norma_id)` removida; `UNIQUE(atividade_base_id, numero_versao)` ativa (índice não-parcial).
  - `numero_versao <= 0` bloqueado por triggers em `database.db` existente; `CHECK(numero_versao >= 1)` no DDL de bancos novos.
  - `codigo_normativo` permanece metadado normativo, não badge operacional.
  - `norma_id` e `codigo_normativo` permanecem `NOT NULL`.
  - `database.db` pós-D7.6B2: 544.768 bytes, SHA256 `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`.
- D7.6C concluída (commit `62aed4b`): menu ⋮ de versões na tela `/admin/atividades` entregue.
- D7.6D concluída (commit `2f81179`): matriz escolhe/relinka versão operacional existente; card mostra vN; matrix não cria atividade_versao.
- D7.6E concluída (commit `e359047`): novo vínculo matriz→atividade_base usa automaticamente a última versão ativa; vínculo manual existente preservado; nenhum INSERT em atividade_versao.
- D7.6G2 concluída (commit `bdd5ddc`): suíte completa corrigida após introdução de `UNIQUE(atividade_base_id, numero_versao)` pelo D7.6B2; 503 passed, 0 failed; exceção de escopo aceita para artifacts CSRF deterministicamente gerados.
- D7.7A auditoria pós-push confirmou quatro riscos reais de persistência/resolução; transferidos como escopo da D7.7B1.
- D7.7B1 concluída (commit `d53d9cd`): modal filtra apenas versões ativas com norma na matriz; POST rejeita versão inativa ou fora de `matriz_norma`; default respeita `matriz_norma`; `_save_matriz_activity_links` limpa vínculos órfãos; 512 passed, 0 failed.
- D7.7C1 concluída (commit `99f4659`): `vN` exibido no catálogo de versões, nos formulários de criação/edição e na tela de versões da matriz; `codigo_normativo` permanece metadado normativo; backend D7.7B intocado; 522 passed, 0 failed.
- UX/template ainda não mostra alerta quando vínculo legado inválido deixa o modal sem opções elegíveis (templates fora do escopo D7.7B1).
- Menu hover-only de Admin → Atividades permanece como possível polish futuro.
- Risco AEA cross-tab por bases compartilhadas entre tipos: baixo, aceito como conhecido.

## Permanent Working Directives

- ChatGPT acts as technical supervisor, auditor, and orchestrator.
- Codex or GitCP is the main executor for real code changes.
- MiniMax may be used for low-cost volume work, logs, tests, repetitive tasks, and simple low-risk patches.
- Kimi may be used for strong second opinions, architecture work, or difficult multi-file problems.
- GLM, Qwen, MiMo, and DeepSeek may be used selectively for safe tasks, preferably read-only, test-only, or review work.
- Sensitive data, real databases, production actions, security work, backfill or cutover, and critical decisions must not be delegated to a low-cost agent without final audit.
- Every phase must leave a report, evidence, tests or justification, risks, and a clear next step.
- `PROJECT_STATE.md` and `AGENT_HANDOFF.md` must be updated after an important phase closeout, agent or chat handoff, structural change, or relevant risk change.
- D7.5D-PATCH-CARD-VERSION-MENU is complete (functional commit `0dbd2b1`).
- D7.6B2 is complete: `numero_versao` operacional entregue, schema endurecido, testes validados.
- D7.6C is complete: menu ⋮ de versões na tela `/admin/atividades` entregue (commit `62aed4b`).
- D7.6D is complete: matriz escolhe/relinka versão operacional existente; card mostra vN (commit `2f81179`).
  - Matriz não cria `atividade_versao`; apenas escolhe entre as existentes.
  - Card exibe `vN` via `numero_versao`; `codigo_normativo` é metadado secundário.
  - `templates/admin_atividades.html` não foi alterado em D7.6D.
  - Schema e `database.db` não foram alterados em D7.6D.
- D7.6E is complete: novo vínculo matriz→atividade_base usa automaticamente a última versão ativa (commit `e359047`).
  - `_ensure_default_versao_link` cria link apenas quando não existe; preserva escolha manual.
  - Caso sem versão ativa: nenhum link criado (documentado e testado).
  - Matriz não cria `atividade_versao`.
  - `templates/admin_atividades.html`, `admin_matriz_form.html` não alterados em D7.6E.
  - Schema e `database.db` não alterados em D7.6E.
- D7.6G2 is complete: suíte completa 503/0 verde após remediação de seeds, script D7.3H e asserts de catálogo para `UNIQUE(atividade_base_id, numero_versao)`. Commit `bdd5ddc` aceito.
- D7.7B1 is complete: modal, POST e default de versão agora respeitam `status='ativa'` e `matriz_norma`; `_save_matriz_activity_links` limpa vínculos explícitos órfãos. Commit `d53d9cd` aceito. 512 passed, 0 failed.
  - Não reintroduzir criação de versão pela matriz como fluxo principal.
  - Não alterar schema sem nova auditoria.
  - Não usar `codigo_normativo` como badge principal.
  - Não fazer push sem ordem explícita.
  - Não ignorar que artifacts CSRF entraram como exceção de escopo documentada em D7.6G2.
  - Não reabrir D7.7B1 sem novo bug concreto; a limpeza de órfãos é scoped por tab.
- D7.7B1 está funcionalmente completo e documentalmente registrado.
- D7.7C1 is complete: `vN` agora exibido no catálogo de versões, nos formulários e na tela de versões da matriz. Commit `99f4659` aceito. 522 passed, 0 failed.
  - `codigo_normativo` permanece metadado normativo em todas as telas.
  - Backend D7.7B intocado.
- D7.7C3 published D7.7C to origin/main at `5c6859b`. 90/90 focused tests passed before push. No code/schema/DB changes in the push.
- D7.7C4 recorded the post-push doc sync (docs-only). Baseline functional published remains `5c6859b`.
- D8.0A is complete: read-only audit pós-D7 aprovada; baseline D8 autorizado.
- D8.0B is complete: 522 passed, 0 failed; backup verificado em
  `D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.0B-baseline-20260614-140824.db`;
  SHA256 `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`.
  - Não iniciar D8.1 sem plano read-only aprovado.
  - Não ligar flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` sem backup novo.
  - Não alterar deferimento admin sem teste específico.
  - Não alterar `database.db` sem autorização explícita.
- D8.1B is complete: display read-only do snapshot versionado entregue para
  o aluno (lista e detalhe). Commit `1b34b55` aceito. 6 passed (D8.1B) + 32
  passed (regressão dirigida) + 528 passed (suíte completa), 0 failed, 0 errors.
  - Não ligar flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` sem nova fase explícita.
  - Não recalcular snapshot em edição do aluno.
  - Não alterar deferimento admin sem plano próprio.
  - Não alterar `database.db` sem autorização explícita.
- D8.2A is complete: plano read-only de cutover de escrita aprovado
  (READONLY-WRITE-CUTOVER-RISK-PLAN); nenhuma flag ligada, nenhum código
  alterado nesta fase.
- D8.2B is complete: contrato de edição do aluno após snapshot versionado
  implementado e aceito. Commit `d06a02d` — `Block activity changes after
  student snapshot write`. 12 passed (D8.2B/D8.1B focados) + 32 passed
  (regressão dirigida) + 534 passed (suíte completa), 0 failed, 0 errors.
  - Aluno não pode trocar `atividade_id` quando a requisição já tem snapshot
    versionado (`atividade_versao_id` ou `codigo_normativo_snapshot` ou
    `regra_snapshot_json` presentes).
  - Demais campos (nome do evento, horas, data, observação, anexos) seguem
    editáveis.
  - Requisições sem snapshot preservam troca de atividade legada.
  - Snapshot não é recalculado nem limpo na edição.
  - `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` e
    `SGAA_VERSIONED_RESOLVER_SHADOW_READ` permanecem OFF por padrão; `.env`
    não foi alterado.
  - Writer/resolver/admin/deferimento/schema/`database.db` não foram
    alterados.
  - Não fazer push sem ordem explícita.
  - Não reabrir D8.2B sem novo bug concreto.

### D8.0 - Baseline pós-D7 / Macrofase aluno-requisições versionadas

- D8.0A (read-only audit) confirmou:
  - D7 fechado e publicado; origin/main...main = 0 0; HEAD = `3cb28c8`.
  - 10 pontos corretos, 5 problemas documentados, 5 lacunas de teste, 5 riscos de UX,
    5 riscos de backend, 2 riscos de dados live.
  - Fluxo do aluno 100% legacy; `aluno_nova_requisicao` não chama snapshot writer;
    `observacao_aluno` existe mas nenhuma tela do aluno a exibe.
  - Recomendação aprovada: D8.0B como gate antes de D8.1.
- D8.0B (baseline suite + backup) executada em `3cb28c8`:
  - Suíte: `python -m pytest tests/ -q --tb=short` — execução única (sem OOM).
  - Resultado: **522 passed, 0 failed, 0 errors, 4 warnings** em 470.91s (7m50s).
  - Warnings: DeprecationWarning openpyxl `datetime.utcnow()` — não são falhas.
  - Artifacts CSRF (`csrf_inventory_shadow_off.json`, `csrf_inventory_shadow_on.json`)
    gerados deterministicamente pela suíte e restaurados ao estado HEAD após o run;
    não commitados.
  - `database.db` pós-D8.0B:
    - Caminho: `D:\OneDrive\Programação\SGAA_clean_baseline\database.db`
    - Tamanho: 544.768 bytes
    - SHA256: `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`
    - Não versionado (git ls-files vazio).
  - Backup criado (fora do worktree, não versionado):
    - Caminho: `D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.0B-baseline-20260614-140824.db`
    - Tamanho: 544.768 bytes
    - SHA256: `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`
    - Hash idêntico ao original confirmado; backup não entrou no Git.
  - Estado D8 baseline: D7 fechado; suíte verde (522/0); backup verificado.
  - Próxima etapa: D8.1A — READONLY-ALUNO-REQUISICOES-VERSIONED-CUTOVER-PLAN.

### D8.1 - Display read-only de snapshot versionado para o aluno

- D8.1A aprovada como plano read-only do cutover aluno/requisições versionadas
  (somente leitura e planejamento; nenhum write autorizado nesta etapa).
- D8.1B aprovada funcionalmente.
  - Commit aceito: `1b34b55` — `Show versioned snapshot metadata to students`.
  - Escopo entregue:
    - `app/views/aluno.py` expõe metadados read-only do snapshot versionado
      (`atividade_versao_id`, `codigo_normativo_snapshot`, `regra_snapshot_json`,
      join com `atividade_versao`) nas rotas reais do aluno
      (`aluno_minhas_requisicoes`, `aluno_requisicao_detalhe`).
    - `main.py` mantém paridade nas rotas legacy (ativas apenas quando
      `USE_ALUNO_BLUEPRINT=False`; hoje `True`, blueprint é a rota real).
    - `templates/aluno_requisicao_detalhe.html` mostra bloco
      "Versão normativa registrada" quando há snapshot.
    - `templates/aluno_minhas_requisicoes.html` mostra chip `vN` quando há snapshot.
    - `tests/test_aluno_requisicao_versioned_readonly.py` cobre 6 cenários
      (T01–T06: flag ON com bloco completo, flag OFF sem bloco, chip na lista,
      JSON inválido sem 500, turma sem matriz/writer no-op, edição não regenera snapshot).
  - Contrato preservado:
    - `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` permanece OFF por padrão;
    - `SGAA_VERSIONED_RESOLVER_SHADOW_READ` permanece OFF;
    - edição pelo aluno não recalcula snapshot;
    - admin/deferimento/resolver/schema/`database.db` não foram alterados.
  - Validação aceita:
    - testes focados D8.1B: `tests/test_aluno_requisicao_versioned_readonly.py` — 6 passed;
    - regressão dirigida (`test_release_requisicoes_flow`, `test_matriz_versao_contract`,
      `test_activity_versioning_shadow_read`, `test_admin_requisicao_process_ui`,
      `test_admin_requisicao_create`): 32 passed;
    - suíte completa: `python -m pytest tests/ -q --tb=short` — 528 passed, 0 failed,
      0 errors, 4 warnings em 447.70s — execução única, sem OOM.
  - `database.db`:
    - não versionado (`git ls-files database.db` vazio);
    - SHA256 antes/depois inalterado:
      `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`;
    - tamanho: 544.768 bytes.
  - Ressalva processual: o commit `1b34b55` já existia localmente antes da
    validação desta sessão (implementado em sessão anterior); backup
    pré-implementação específico da D8.1B não foi criado. A ressalva é aceita
    porque o backup D8.0B já existe, o banco não foi alterado por nenhuma
    etapa desta trilha, e a validação confirmou hash idêntico antes/depois.
  - Próxima etapa recomendada: D8.1D — final verify and push.

### D8.2 - Contrato de edição do aluno após snapshot versionado / risco de cutover de escrita

- D8.2A aprovada como plano read-only de cutover de escrita
  (READONLY-WRITE-CUTOVER-RISK-PLAN).
  - Somente leitura e planejamento; nenhuma flag ligada; nenhum código
    alterado.
  - Risco primário identificado: edição do aluno após snapshot já gravado
    poderia trocar `atividade_id` sem recalcular nem invalidar o snapshot,
    gerando divergência entre o que foi exibido ao aluno e o que valeria
    depois. Esse risco foi tratado como bloqueador para qualquer cutover real
    de `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE`.
  - Relatório de 15 seções entregue, sem nenhuma escrita real.
- D8.2B aprovada funcionalmente.
  - Commit aceito: `d06a02d` — `Block activity changes after student snapshot write`.
  - Escopo entregue:
    - `app/views/aluno.py` bloqueia troca de atividade pelo aluno quando a
      requisição já possui snapshot versionado;
    - edição de demais campos (nome do evento, horas, data, observação,
      anexos) permanece permitida;
    - requisições sem snapshot preservam comportamento legado de troca de
      atividade (mantida a validação de matriz já existente);
    - snapshot não é recalculado em edição;
    - snapshot não é limpo em edição;
    - `docs/d8_2_write_cutover_ops.md` registra o contrato e o plano de smoke
      futuro (não executado).
  - Contrato preservado:
    - `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` permanece OFF por padrão;
    - `SGAA_VERSIONED_RESOLVER_SHADOW_READ` permanece OFF;
    - `.env` não foi alterado;
    - writer/resolver/admin/deferimento/schema/`database.db` não foram
      alterados.
  - Validação aceita:
    - `tests/test_aluno_requisicao_versioned_readonly.py`: 12 passed
      (6 D8.1B + 6 D8.2B, T01–T06);
    - regressão dirigida (`test_release_requisicoes_flow`,
      `test_matriz_versao_contract`, `test_activity_versioning_shadow_read`,
      `test_admin_requisicao_process_ui`, `test_admin_requisicao_create`):
      32 passed;
    - suíte completa: `python -m pytest tests/ -q --tb=short` — 534 passed,
      0 failed, 0 errors, 4 warnings, execução única, sem OOM;
    - artifacts CSRF (`tests/_artifacts/csrf_inventory_shadow_off.json`,
      `csrf_inventory_shadow_on.json`) restaurados ao estado HEAD após a
      suíte; não entraram no commit;
    - `git diff --check`: limpo (apenas aviso benigno de normalização
      LF→CRLF).
  - `database.db`:
    - não versionado (`git ls-files database.db` vazio);
    - SHA256 antes/depois inalterado:
      `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`;
    - tamanho: 544.768 bytes.
  - Riscos residuais:
    - admin ainda pode editar a atividade de uma requisição com snapshot por
      design, fora do escopo D8.2B — divergência potencial fica registrada
      para uma fase futura se o write cutover avançar;
    - `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` segue OFF, então o guard hoje
      só protege as requisições já carimbadas (smoke D6.4) ou requisições
      futuras após um cutover real;
    - duplicação blueprint/legacy em `aluno.py`/`main.py` deve ser observada
      em um refactor futuro, fora do escopo desta fase.
  - Próxima etapa recomendada:
    - D8.2C — final verify and push dos commits locais D8.2B + closeout;
    - depois, nova fase explícita de smoke em cópia do banco antes de
      qualquer cutover real de `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE`.

### D8.3 - Smoke de write flag em cópia isolada do banco

- D8.3A (COPY-DB-WRITE-FLAG-SMOKE) executada e aprovada.
  - Smoke executado inteiramente contra cópia física isolada de
    `database.db`; banco live não foi escrito em nenhum momento.
  - `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=1` ligada somente no processo
    isolado do smoke (variável de ambiente do processo); `.env` não foi
    alterado; nenhuma flag foi ligada em ambiente live.
  - Redirecionamento feito via `APP_DATABASE`, sem alteração de código;
    prova de redirecionamento confirmada em `main.DATABASE`,
    `app_db_module.DATABASE`, `app.config["DATABASE_PATH"]` e
    `PRAGMA database_list`.
  - Caso válido: PASS — requisição `id=58` na cópia, `atividade_versao_id=2`,
    `codigo_normativo_snapshot=AAC-rev6`, `regra_snapshot_json` coerente com
    `atividade_versao id=2`, `schema_version=d6.4.0-v1`.
  - Guard de edição: PASS — tentativa de troca de atividade bloqueada de
    forma atômica; `atividade_id` e snapshot inalterados.
  - Caso skip (turma sem matriz explícita resolvível): PASS — requisição
    `id=59` criada na cópia com `atividade_versao_id`,
    `codigo_normativo_snapshot` e `regra_snapshot_json` `NULL`, sem 500.
  - Sem alteração de código, sem commit, sem push na D8.3A.
  - Backup externo: `D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.3A-live-baseline-20260620-205155.db`.
  - Cópia de trabalho do smoke: `D:\OneDrive\Programação\SGAA_database_backups\database.D8.3A-smoke-working-20260620-205155.db`.
  - `database.db` live:
    - SHA256 antes/depois inalterado:
      `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`;
    - tamanho: 544.768 bytes;
    - não versionado (`git ls-files database.db` vazio).
  - Cutover real continua **NÃO** autorizado por este resultado.
  - Relatório completo: `docs/d8_3_copy_db_write_flag_smoke_result.md`.
- D8.3B (closeout documental, docs-only) registra o resultado acima sem
  nenhuma alteração de código, schema, template, teste ou `database.db`.
- Próxima etapa:
  - D8.3C — final verify and push do closeout documental;
  - depois, D8.4A — plano/ativação local controlada da flag, somente com
    autorização explícita.

### D8.4 - Smoke de write flag no database.db local live (supervisionado)

- D8.4A (LOCAL-WRITE-FLAG-ON-SUPERVISED-SMOKE) executada e aprovada.
  - Smoke executado diretamente contra o `database.db` local live (não
    uma cópia), com backup fresco verificado criado antes de qualquer
    escrita.
  - `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=1` ligada somente no
    processo Python isolado do smoke (variável de ambiente do processo);
    `.env` não foi criado/alterado (continua inexistente); nenhuma flag
    permanente foi ligada.
  - Script do smoke armazenado fora do repositório:
    `D:\OneDrive\Programação\SGAA_database_backups\d8_4a_smoke.py`.
  - Ambiente auxiliar: `.venv` do projeto estava quebrado (apontava para
    Python 3.13 removido da máquina); criado venv Python 3.11 descartável
    fora do repo (`SGAA_database_backups\d84a_runtime_venv`) só para
    executar o smoke; nenhum arquivo do repositório foi alterado por isso.
  - Caso válido: PASS — requisição `id=57` no live,
    `nome_evento=D8.4A_SMOKE_LOCAL_WRITE_FLAG_ON`, `atividade_versao_id=2`,
    `codigo_normativo_snapshot=AAC-rev6`, `regra_snapshot_json` coerente
    com `atividade_versao id=2`, `schema_version=d6.4.0-v1`.
  - Guard de edição: PASS — tentativa de troca de `atividade_id`
    bloqueada de forma atômica; `atividade_id` e snapshot inalterados.
  - Caso skip: **não exercitado no live** por decisão deliberada (sem
    candidato natural seguro; preferência por não criar curso/turma
    artificial no live); já validado em cópia isolada na D8.3A.
  - Contagens de `requisicoes`: `41`→`42` total, `13`→`14` com
    `atividade_versao_id`/`codigo_normativo_snapshot`/`regra_snapshot_json`
    (delta exato `+1` em cada, consistente com a única linha criada).
  - Escopo da mutação confirmado: somente a tabela `requisicoes` mudou;
    `requisicao_arquivos` sem nova linha; tabelas auxiliares intocadas.
  - `database.db` live:
    - SHA256 antes: `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`;
    - SHA256 depois: `0A00BCC9779A5DBD57447BA72EC51C90D9FF981DEC046F581F4C67D61A2574CD`
      (mudança esperada, decorrente apenas da linha smoke);
    - tamanho antes/depois: 544.768 bytes;
    - não versionado (`git ls-files database.db` vazio).
  - Backup externo: `D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.4A-local-write-flag-on-20260620-212052.db`
    — hash `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`
    confirmado idêntico ao live antes da escrita e permanece intacto após o
    smoke.
  - Requisição smoke `id=57` permanece no `database.db` live como
    evidência; não removida sem fase própria de cleanup/restauração.
  - Sem alteração de código, schema, template ou teste; sem commit; sem
    push na D8.4A.
  - Cutover real continua **NÃO** autorizado por este resultado.
  - Relatório completo: `docs/d8_4_local_write_flag_on_smoke_result.md`.
- D8.4B (closeout documental, docs-only) registra o resultado acima sem
  nenhuma alteração de código, schema, template, teste ou `database.db`.
- Próxima etapa:
  - D8.4C — final verify and push do closeout documental;
  - depois, decisão explícita entre manter `id=57` como evidência, abrir
    fase própria de cleanup/restauração, ou planejar ativação controlada
    mais ampla.

### D8.5 - Limpeza controlada da requisição smoke D8.4A (id=57)

- D8.5A (READONLY-POST-SMOKE-LIVE-ARTIFACT-AND-RUNTIME-DECISION) executada
  e aprovada; auditoria read-only do `database.db` live, do backup D8.4A e
  dos artefatos externos confirmou zero dependentes de `id=57` em
  `requisicao_arquivos`/`requisicao_alerta_receipts` e recomendou limpeza
  controlada (Option B) como única próxima fase.
- D8.5B (CONTROLLED-CLEANUP-D8.4A-SMOKE-REQUISITION) executada e aprovada.
  - Backup fresco criado antes do delete:
    `D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.5B-cleanup-id57-20260620-231236.db`
    — hash idêntico ao live antes da escrita.
  - Auditoria pré-delete: total `requisicoes=42`, snapshots `14/14/14`,
    `id=57` confirmado com `nome_evento=D8.4A_SMOKE_LOCAL_WRITE_FLAG_ON`,
    `0` anexos e `0` alerta receipts dependentes.
  - Delete controlado em transação explícita `BEGIN`/`COMMIT`, com rowcount
    guards: `0` linhas em `requisicao_arquivos`, `0` em
    `requisicao_alerta_receipts`, exatamente `1` em `requisicoes`.
  - Validação pós-delete: total `requisicoes=41`, snapshots `13/13/13`,
    `id=57` ausente, `requisicao_arquivos` total `4` preservado,
    `requisicao_alerta_receipts` total `38` preservado, `0` dependentes.
  - `PRAGMA foreign_key_check` vazio — integridade referencial confirmada.
  - `database.db` live:
    - SHA256 antes: `0A00BCC9779A5DBD57447BA72EC51C90D9FF981DEC046F581F4C67D61A2574CD`;
    - SHA256 depois: `1CA32F61553433E740E2B60B5428C56BC287ABB271ABB96680DD1320D17C5C80`;
    - tamanho antes/depois: 544.768 bytes; sem `VACUUM`.
  - Nota sobre hash: o hash pós-delete não retorna ao valor pré-D8.4A
    porque o SQLite não compacta páginas liberadas sem `VACUUM`; o critério
    aceito foi integridade lógica (contagens e FK check), não o hash do
    arquivo.
  - Backup D8.5B e backup D8.4A
    (`CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`)
    permanecem íntegros.
  - Sem alteração de código, schema, template ou teste; sem commit; sem
    push na D8.5B; sem `VACUUM`; sem restauração de backup.
  - `.venv` do projeto continua quebrado — risco de tooling separado, fora
    do escopo desta fase.
  - Cutover real continua **NÃO** autorizado por este resultado.
  - Relatório completo: `docs/d8_5_cleanup_id57_result.md`.
- Próxima etapa:
  - D8.5D — final verify and push do closeout documental.

### REF-0 refactor safety net (continued)

#### REF-0C-A - RBAC policy matrix diagnosis for 24 unmapped /admin routes
- REF-0C-A / REF-0C-A-R1 is **CLOSED / ACCEPTED**.
- Accepted diagnosis HEAD: `f977fd6` (`Document normative RBAC policy matrix diagnosis`).
- Current branch: `refactor/architecture-safety-net`; `HEAD` `f977fd6`; `origin/main...HEAD = 0 7`; working tree clean.
- Accepted matrix confidence counts: HIGH 21, MEDIUM 3, LOW 0.
- R22, R23, R24 remain unresolved normative diagnostic-policy decisions. No policy has been selected for these routes.
- No RBAC implementation has started.
- Modularization remains prohibited.
- The next authorized technical phase is **REF-0C-B1 — Strongly Supported RBAC Mappings and Denial Tests**.
- REF-0C-B1 is explicitly limited to the 21 HIGH-confidence route-method combinations (R1–R19, R21).
- R22, R23, and R24 are explicitly excluded from implementation until their diagnostic access policy is approved.
- For R20, only the central `matrizes`/`edit` RBAC mapping and its tests are authorized. Changing or removing the local `readonly` behavior is not authorized in this closeout.
- Do not claim that R22–R24 have a selected policy.
- Do not authorize fail-closed global enforcement, UI changes, schema changes, database changes, or modularization.

#### REF-0C-B1-P0 - Admin access-context transaction hygiene (CLOSED / ACCEPTED)
- Accepted prerequisite commit: `92b25d2` (`Fix admin access-context transaction hygiene`). The separately accepted REF-0C-B1 mapping commit is `932c6d7`; it contains no `main.py` transaction patch.
- Root cause: `_get_current_admin_access_context()` calls `_load_admin_access_context()` on the shared request connection, which calls `ensure_usuario_access_schema()`. Its idempotent `INSERT OR IGNORE` and normalization `UPDATE` statements open SQLite's implicit write transaction even when no data changes. The dangling transaction prevented the later lazy `atividades` rebuild from changing `PRAGMA foreign_keys` and could hold a write lock.
- Correction: `ensure_usuario_access_schema()` owns a named savepoint. On a clean connection, `RELEASE SAVEPOINT` persists required bootstrap/schema state and leaves no transaction open. In a pre-existing caller transaction, it releases only its nested savepoint and does not commit or roll back the caller's work. The global gate no longer commits or rolls back transactions.
- Focused isolated tests (temporary databases only): `5 passed`; they prove clean-connection neutrality and persistence, caller-transaction preservation, repeated idempotence, a mapped lazy-rebuild route with no lock/FK DDL failure, and unchanged allow/deny results. Technical contract: `docs/refactor/REF_0C_B1_P0_ACCESS_CONTEXT_TRANSACTION_HYGIENE.md`.
- No schema design, migration, authorization-policy, UI, dependency, or real-database change. P0 is CLOSED / ACCEPTED.

#### REF-0C-B1 - Strongly Supported RBAC Mappings and Denial Tests (CLOSED / ACCEPTED)
- Scope executed: the 21 HIGH-confidence route-method policies (R1-R21) from the accepted diagnosis Section 9 (HEAD `f977fd6`). R22-R24 were **not** mapped and remain unmapped debt.
- Central mapping added to `get_admin_permission_requirement` (`app/auth.py`):
  - `atividades`/`view`: R1 `admin_catalogo_versoes`, R2 `admin_catalogo_versao_detalhe`, R3 `admin_normas_atividade`, R4 `admin_mapeamento_legado`.
  - `atividades`/`edit`: R5/R6 `admin_catalogo_nova_base`, R7/R8 `admin_norma_nova`, R9/R10 `admin_catalogo_nova_versao`, R11/R12 `admin_catalogo_editar_versao`, R13 `admin_catalogo_ativar_versao`, R14 `admin_catalogo_inativar_versao`, R15 `admin_catalogo_descontinuar_versao`, R16 `admin_catalogo_substituir_versao`.
  - `matrizes`/`view`: R17 `admin_matriz_versoes`.
  - `matrizes`/`edit`: R18 `admin_matriz_versoes_definir`, R19 `admin_matriz_versoes_remover`, R20 `admin_matriz_nova_atividade` (central mapping only), R21 `admin_matriz_nova_versao_card`.
- Resulting actor matrix (documented defaults): `admin_total` and `administrativo` allowed on all 21; `consultivo` allowed on `view` routes (R1-R4, R17) and denied on `edit` routes (R5-R16, R18-R21); anonymous/aluno denied. Denial contract: non-AJAX redirect to `admin_dashboard`; no target-table mutation on a denied POST.
- Prerequisite relationship: REF-0C-B1-P0 fixes access-context transaction ownership at the helper source. This RBAC commit contains no `main.py` transaction patch; the authorization gate only evaluates permissions and does not commit or roll back request work.
- Debt baseline regenerated via the documented `SGAA_UPDATE_RBAC_DEBT_BASELINE=1` command: `tests/_artifacts/rbac_unmapped_routes_baseline.json` now lists exactly the 3 R22-R24 diagnostic routes. Zero change to R22-R24 policy.
- Existing-test adjustment (authorized under supervisor Option A): two versioning suites logged in as the non-existent admin `user_id=999999`, which passed only while these routes were unmapped; once mapped, a non-resolvable admin is correctly denied. Their login helpers now authenticate as the real bootstrap `admin_total` (`user_id=1`); all existing assertions preserved. Files: `tests/test_admin_matriz_versao_link.py`, `tests/test_admin_activity_version_catalog_version_lifecycle.py`.
- New tests: `tests/test_ref_0c_b1_rbac_high_confidence_mappings.py` (36 tests) covering the 21-route requirement mapping, R22-R24-remain-unmapped, the actor matrix at the permission layer, HTTP allow/deny paths, the denial redirect contract, and no-mutation invariants for a denied POST per domain group.
- Full hermetic suite: `562 passed`, `17` D73H deselected, `0` failures/errors/skips/xfails/xpasses (`pytest -q`, 528.92s). The selected-test delta versus the earlier `557` is `+5`, exactly the dedicated P0 transaction tests.
- No-mutation invariants validated: a denied `consultivo` POST to `admin_catalogo_nova_base` leaves `atividade_base` unchanged; a denied POST to `admin_matriz_versoes_definir` leaves `matriz_atividade_versao_item` (matriz_id=1) unchanged.
- Out of scope / still prohibited: R22-R24 policy selection, fail-closed global enforcement, R20 local `readonly` enforcement or removal, UI changes, schema/database changes, dependency changes, route modularization, and any push.
- Files in the RBAC commit: `app/auth.py`, `tests/_artifacts/rbac_unmapped_routes_baseline.json`, `tests/test_admin_matriz_versao_link.py`, `tests/test_admin_activity_version_catalog_version_lifecycle.py`, `tests/test_ref_0c_b1_rbac_high_confidence_mappings.py` (new), and these canonical records. `main.py` belongs only to P0.
- Authentication-helper inventory: all `999999` occurrences in the affected two versioning suites were inspected. Exactly two were successful-admin login assignments and were changed to the real bootstrap `admin_total` (`user_id=1`): `tests/test_admin_matriz_versao_link.py::_login_admin` and `tests/test_admin_activity_version_catalog_version_lifecycle.py::_login_admin`. The two retained textual references are explanatory comments. Other `999999`/`9999999` values elsewhere in the test suite are missing-resource or negative-authentication inputs and were retained.
- Historical non-REF-0C-B1 churn: `tests/_artifacts/csrf_inventory_shadow_{on,off}.json` were previously rewritten by `test_csrf_inventory_audit.py`; R6/R7 established that the root cause was deterministic stale snapshots after three deterministic message entries, not randomized keys. Normal mode is now read-only; the artifacts had been reverted and excluded from the historical REF-0C-B1 commit.
- No subsequent implementation phase is automatically authorized. Exact next action: ChatGPT/user normative decision on R22-R24 diagnostic access policy, R20 local readonly enforcement or cleanup, and whether/when REF-0C-B2 may be authorized. Do not begin REF-0C-B2 or REF-0C-C.
- REF-0C-B2 implemented and locally validated, pending ChatGPT supervisor review: R22/R23 GET → `atividades`/`view` ({admin_total, administrativo, consultivo}); R24 GET → `banco_dados`/`view` ({admin_total}). The debt baseline dynamically rebuilds to zero entries. R20 `readonly` is unchanged; no global fail-closed gate or later phase is authorized. Full-suite detached-worktree evidence is pending final closeout.
- REF-0C-B2 full detached-worktree suite: `577 passed`, `17` D73H deselected, zero failures/errors/skips/xfails/xpasses, exit `0`; selected-test delta `+15` (18 B2 tests less 3 obsolete B1 unmapped assertions). REF-0C-B2 remains pending ChatGPT supervisor review.
- REF-0C-B2 implementation commit: current `HEAD` (`Implement REF-0C-B2 diagnostic RBAC mappings`).
- Detached-worktree cleanup note: Git removed the worktree registration; environment policy blocked deletion of the empty temporary directory `C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0c-b2-full-validation`. It contains no production data and may be deleted locally.
