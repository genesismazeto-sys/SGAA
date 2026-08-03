# 05 — Avaliação do refactor (Pergunta 1)

> **Pergunta do dono:** vale um refactor de arquitetura para ficar o mais
> profissional e modular possível, facilitar a vida das IAs e evitar quebras de
> rota / falhas de autenticação? Qual o plano para manter tudo operacional?

## Veredito

**Sim, vale — mas com escopo cirúrgico, não um rewrite.** O app é maduro e
seguro; o problema é **organização**, concentrada em um arquivo (`main.py`,
14.792 linhas) e num **ciclo de dependências** que ficou pela metade. O objetivo
do refactor é puramente estrutural: **quebrar o monólito em módulos coesos sem
mudar comportamento**. Não há motivo para reescrever regras de negócio nem trocar
o framework.

A boa notícia: **você tem a rede de segurança certa** — 70 arquivos de teste
(incluindo CSRF, RBAC, fluxos críticos admin/aluno). Isso é o que torna um
refactor seguro e mensurável.

### Por que vale (benefício direto ao seu objetivo)
- **IAs trabalham muito melhor em módulos de 200–800 linhas** do que num arquivo
  de 15k. Hoje qualquer tarefa força carregar o monólito inteiro.
- **Menos quebra de rota / auth:** centralizar o RBAC e cobrir o mapeamento
  endpoint→permissão com teste remove a classe de bug mais perigosa.
- **Onboarding e manutenção** ficam triviais com fronteiras claras.

### Por que NÃO fazer big-bang
- Reescrever do zero joga fora anos de regra de negócio e os 70 testes.
- O risco de regressão silenciosa (RBAC, versionamento de atividades) é alto.

## Princípios do refactor

1. **Comportamento idêntico.** Cada passo é "mover, não mudar". Nenhuma mudança
   de regra de negócio no mesmo commit que mexe na estrutura.
2. **Testes verdes em todo passo.** `pytest` roda antes e depois de cada PR; nada
   entra com teste vermelho.
3. **Passos pequenos e reversíveis.** Cada PR move **um** assunto e é fácil de
   reverter.
4. **Endpoints estáveis.** Nomes de endpoint e URLs **não mudam** (ou mudam com
   compatibilidade), porque o RBAC e os templates dependem deles.

## Os 2 riscos que realmente quebram o app (e como blindar)

### Risco A — Quebra de rota ao migrar para blueprints
Mover `@app.route` (endpoint `admin_requisicoes`) para um blueprint muda o
endpoint para `admin.requisicoes`. Isso quebra:
- `url_for("admin_requisicoes")` nos templates → `BuildError`;
- o casamento do RBAC (que usa o nome do endpoint).

**Blindagem:**
- Já existe o helper `route_url(*endpoints)` (`app/__init__.py:196`) que tenta
  vários nomes — use-o nos templates durante a transição.
- Migre **um blueprint por vez** e rode a suíte (vários testes fazem
  `url_for`/GET das rotas).
- Adicione um **teste de inventário de rotas** (snapshot de
  `app.url_map`): congela URL+métodos+endpoint atuais e falha se algo sumir.

### Risco B — Falha de autenticação/RBAC
`get_admin_permission_requirement` casa por **nome de endpoint sem prefixo**. Se o
endpoint vira `admin.requisicoes` e o mapa continua esperando `admin_requisicoes`,
a função retorna `None` → **a rota fica sem proteção** (libera geral). É a falha
mais perigosa possível.

**Blindagem:**
- Atualizar `get_admin_permission_requirement` **no mesmo PR** que move as rotas.
- Adicionar um **teste que percorre `app.url_map` e garante que toda rota
  `admin*` tem uma permissão exigida** (nenhuma rota admin pode retornar `None`).
- Manter o `before_request` central (`enforce_admin_access_control`) — não
  espalhar checagem por view.

## Plano incremental (fases, cada uma é mergeável e operacional)

> Trabalhar sempre em branch a partir de `clean-baseline`, com `pytest` verde.

### Macro Fase 0 — Rede de segurança — CLOSED / ACCEPTED

**Status: CLOSED / ACCEPTED** (2026-07-24). All Phase-0 safety-net requirements satisfied via external supervisor acceptance of technical commit `df24639faa4b18d5aad429940a82982b4beeab98`.

#### Phase-0 completion matrix

| Requirement | Canonical source | Implemented by phase | Commit | Test/evidence | Status |
|---|---|---|---|---|---|
| Stable route inventory | `tests/test_route_inventory_snapshot.py` + `tests/_artifacts/route_inventory_baseline.json` | REF-0B | `f2b1cfc` | 131 rules, 130 endpoints, 160 business methods; read-only comparison | SATISFIED |
| RBAC coverage | `tests/test_rbac_requirement_coverage.py` + `tests/_artifacts/rbac_unmapped_routes_baseline.json` | REF-0B | `f2b1cfc` | 0 unmapped admin routes; dynamic enumeration from `main.app.url_map` | SATISFIED |
| Unmapped-route detection | Same RBAC coverage test; dynamic from `main.app.url_map` | REF-0B | `f2b1cfc` | Filters `/admin` paths, calls `get_admin_permission_requirement` | SATISFIED |
| Actor/access-level matrix | `tests/test_ref_0c_d_r1_route_complete_actor_matrix.py` (plus existing B1/B2 coverage) | REF-0C-D-R1 (closure via route-complete parametrization) | `fe0ce87a3838fd14691b3d7c006bfe6864b9371f` | 402 actor cross-product = 263 allowed + 139 denied; 134 governed requirement combinations; 0 exemptions | SATISFIED |
| Denied-action immutability | `tests/test_ref_0c_d_r1_route_complete_actor_matrix.py` (closure via route-complete pre-handler denial) | REF-0C-D-R1 (closure via route-complete parametrization) | `fe0ce87a3838fd14691b3d7c006bfe6864b9371f` | Browser/AJAX denial contract, URL roundtrip, type-safe fingerprint, per-request sentinel, profile digests, no mutation | SATISFIED |
| Access-context isolation | `tests/test_ref_0c_b1_p0_access_context_transactions.py` | REF-0C-B1-P0 | `92b25d2` | 5 tests: transaction-neutral, idempotent, no lock/FK failure on rebuild | SATISFIED |
| Deterministic hermetic suite | Full `pytest` suite with D73H deselected | REF-0TF-B, REF-0C-B1-P0 through REF-0C-C-B1-R1 | `9b47c37`, cumulative | 601 passed, 17 deselected; no failures/errors/skips/xfails/xpasses | SATISFIED |
| D73H historical isolation | `--run-d73h-historical` marker, `pytest.ini` | REF-0TF-B | `9b47c37` | 17 tests deselected by default; CLI options for historical lane; optional lane still needs sanitized artifacts | SATISFIED_WITH_ACCEPTED_RESIDUAL_RISK |
| Testing/development fail-closed | `AdminAuthorizationConfigurationError` in `app/auth.py`, `enforce_admin_access_control` | REF-0C-C-B1 | `fb90cc1` | `test_ref_0c_c_b1_fail_closed_shadow_gate.py` raises hard error in non-production | SATISFIED |
| Production shadow audit | `_audit_missing_admin_authorization_configuration` in `main.py` | REF-0C-C-B1, REF-0C-C-B1-R1 | `fb90cc1`, `39f7732` | Safe shadow event; logger failure caught locally, does not block request; one event can be lost on logger failure | SATISFIED_WITH_ACCEPTED_RESIDUAL_RISK |
| Smoke-flow requirements (hermetic, fixture-controlled) | `tests/test_phase_0_smoke_flows.py` (5 tests) + `docs/refactor/PHASE_0_SMOKE_FLOW_CONTRACT_AND_EVIDENCE.md` | PHASE-0-R9 | `c978ed7` (parent) | 5 passed; each flow exercises real routes, ephemeral SQLite, PYTEST_RUNTIME_ROOT subroot, relative_to containment, explicit admin_id, filesystem SHA-256 inventory, 7-sink call_log, 302/303 + Location, marker id+nome | SATISFIED |
| Smoke tools (legacy) | `tools/smoke_test.py`, `tools/smoke_test_admin.py`, `tools/smoke_test_rbac_permissions.py` | REF-0B onward | Cumulative | Tools exist but superseded by hermetic R9 flows | SUPERSEDED_BY_R9 |
| Production hard enforcement | N/A (not a Phase-0 completion criterion) | N/A | N/A | Production remains shadow-only; no permanent allow-open switch | NOT_APPLICABLE |
| R20 status | Central `matrizes`/`edit` mapping in `get_admin_permission_requirement` | REF-0C-B1 (central mapping); local `readonly` unchanged | `932c6d7` | Central gate enforces; local `readonly` is inert; cleanup unauthorized | SATISFIED_WITH_ACCEPTED_RESIDUAL_RISK |

#### Formal REF-0C-D decision

**Decision: SATISFIED.**

The original gap — route-complete actor decision and pre-handler denied-action immutability coverage over every current governed admin business route-method pair and every denied admin access level — was closed by REF-0C-D-R1. REF-0C-D-R1 implemented test-only, fixture-controlled, parametrized coverage from the canonical route inventory and classifier, proving expected allow/deny at the permission layer for every access level, proving each denied combination returns the central browser/AJAX contract before handler execution, and proving no fixture domain mutation.

**REF-0C-D is SATISFIED** after external acceptance of REF-0C-D-R1 (CLOSED / ACCEPTED).

#### Macro Fase 0 decision

**Decision: CLOSED / ACCEPTED.**

All Phase-0 safety-net requirements are satisfied. The smoke-flow contract/evidence
was accepted by the external supervisor at technical commit
`df24639faa4b18d5aad429940a82982b4beeab98`. Accepted evidence: route inventory;
RBAC coverage; actor x route x method matrix; denied-action immutability;
fail-closed development/shadow production contract; hermetic pytest runtime;
hermetic CSRF snapshots; five fixture-controlled smoke flows; full suite 654
passed, 17 D73H deselected, 0 failures, 0 errors. R10 documents this acceptance
closeout. **R10 contract status:** The pre-acceptance status text in Section 10 of the immutable R9 contract is a historical snapshot, superseded by this R10 current canon; the contract is not modified in R10.

#### Phase 1 — CLOSED / ACCEPTED

**Architecture refactor Phase 1: CLOSED / ACCEPTED.**
- **PHASE-1-U1:** CLOSED / ACCEPTED at commit `68f52fb902c726cc79ff92955e58f95ac0b21cd7` — removed `templates/src.code-workspace-1.code-workspace`. Full suite 654 passed, 17 deselected, 0 failed, 0 errors.
- **PHASE-1-U2:** CLOSED / ACCEPTED at commit `5932dff2d6dbd63e4a1f52ffd649ea33577535d0` — deleted `templates/admin_turmas-KRThinkpad.html`. Proven with zero consumers, zero catalog delta, zero scanner impact.
- **PHASE-1-U3:** CLOSED / ACCEPTED at commit `c4fd2dd1852011a0ec860493ed4cf53834584c42` — removed legacy aluno route bodies; 0 insertions, 756 deletions; eight compatibility exports preserved.
- **PHASE-1-U4:** CLOSED / ACCEPTED. U4 read-only proof: CLOSED / ACCEPTED. U4-B bounded implementation: CLOSED / ACCEPTED. Accepted technical commit `742b67c0623bdf41e292280a11a40d2fddad717c` — removed unused imports (wraps, Flask, bp_presets); corrected hashlib comment; main.py delta 2 insertions, 4 deletions; no behavioral change.
- **PHASE-1-U5:** CLOSED / ACCEPTED. U5 read-only reconciliation: CLOSED / ACCEPTED. U5-B bounded implementation: CLOSED / ACCEPTED. Accepted technical commit `8b55230314605dcf9295072c109f04bea59323c3` — `Remove stale diagnostic output`. Removed tools/diag_out.txt — stale diagnostic artifact, 11,746 bytes, SHA-1 `45f5fc833364e9d2bc49132b4a0f6a0b045be74e`, SHA-256 `f5e027ea7748b4246f224545e399b9014f74a5536e867bbe47e0b65eafcc534b`. No functional consumer.
- **PHASE-1-U6: CLOSED / ACCEPTED.** Read-only, no implementation, no tests, no technical commit.
- **Classification: PHASE1_CLOSABLE_WITH_SEPARATE_CUSTODY_TRACK.**
  U6 confirmed no other safe cleanup bounded candidate has material evidence.
  Phase 1 leaves no partial technical implementation.
  Snapshots are not a mandatory technical closeout criterion.
  Custody transferred without physical action to autonomous administrative track.
- Explicitly prohibited without separate authorization: route extraction; blueprint restructuring; database consolidation; behavior changes; schema/migrations; RBAC; UI; dependencies; production hard enforcement.
- **Not authorized:** database snapshot deletion; Referrer-Policy changes; Phase 2 work.

**Historical snapshot custody: OPEN / DESTINATION PROVISIONED / COPY VERIFIED /
PARENT ACL HARDENING APPLIED AND VERIFIED / SOURCE PRESERVED /
SECURITY-COMPLETE CUSTODY NOT CLAIMED.**
Separate governance/administrative track. Does not integrate Phase 1, Phase 2,
or any architectural implementation phase.
See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.

Transferred residual governance matter:
HISTORICAL-DATABASE-SNAPSHOT-CUSTODY
Status: R1 CLOSED / ACCEPTED (policy approved), R2 CLOSED / ACCEPTED (destination selected)
and R3 CLOSED / ACCEPTED (provisioning and copy contract approved).
R30: DESTINATION_OPTIONS_READY_AWAITING_HUMAN_SELECTION / SUPERSEDED BY HUMAN SELECTION.
Human-selected canonical destination: `D:\programas\SGAA_Historical_Custody`.
Destination status: SELECTED.
Destination class: DEDICATED DIRECTORY OUTSIDE REPOSITORY AND ONEDRIVE.
Physical volume: SAME VOLUME AS SOURCE WORKSPACE — D:.
Provisioning status: SELECTED / PARENT PATH NOT YET PROVISIONED.
Storage-domain risk: the destination is outside the repository and outside the
observed OneDrive tree, but remains on the same physical D: storage domain as the
source workspace. This provides logical separation, not independent-disk redundancy.
It is not redundant, immutable, off-site, independent of the source disk, versioned,
or protected against deletion.
Controlled-copy contract Gates 0–6 ratified documentally; none executed.
Preferred disposable restoration environment: ISOLATED CONTAINER binding only a
derived disposable copy; the source workspace must not be mounted as the restoration
database and the custodial artifact must not be opened directly. Preference only.
Physical action, copy, move, delete, compress and SQLite open: NOT AUTHORIZED.
No archival performed or authorized.
R3 read-only assessment completed; its contract was APPROVED by human decision on
25/07/2026 and remains UNEXECUTED. Approved: layout `artifacts\` / `manifests\` /
`evidence\`; technical executor `KR-IDEAPAD\klebe`; ACL with inheritance disabled,
`Authenticated Users` and `BUILTIN\Users` removed, `SYSTEM` and `Administrators`
FullControl, executor Modify during provisioning and copy then ReadAndExecute on
`artifacts\` and Modify on `manifests\` and `evidence\`; copy-only contract with an
explicit 17-path list, glob and overwrite prohibited, sidecars preserved jointly, stop at
first error, no SQLite open, source never modified; custody manifest JSON without
credentials, personal data, SQLite content or business data; partial residue preserved
until an explicit cleanup decision, with automatic cleanup and silent retry NOT AUTHORIZED;
provisional Level 2 restoration in a controlled external directory
`D:\tmp\sgaa_restore_<UTC>` while `CONTAINER_RUNTIME_NOT_AVAILABLE` holds.

Physical execution was withheld in that decision and released later by a separate explicit
human authorization scoped to R4 only.

R4 status: **EXECUTED / PHYSICAL PROVISIONING COMPLETE / COPY COMPLETE / INTEGRITY VERIFIED
/ SOURCE PRESERVED.** Pre-execution physical authorization: EVIDENCED; authority: project
owner; scope: R4 only. Destination `D:\programas\SGAA_Historical_Custody` provisioned with
`artifacts\` (17 files, 4,808,704 bytes), `manifests\custody-manifest-20260725T233026Z.json`
and `evidence\r4-copy-and-verification-20260725T233315Z.md`. Per-file destination SHA-256 =
source = canon for all 17; source aggregate SHA-256
`44ae5da3f368605ac2550cc65d70d2081d432977c48fad1f467884a65f2e3be3` unchanged. SQLite never
opened. Restoration Level 2 and Level 3 not executed. Source removal not authorized.

R4 operational nonconformities: DECLARED / CONTAINED / NO ARTIFACT INTEGRITY IMPACT / NOT AN
AUTHORIZED PRECEDENT. R4 is not described as a flawless execution.

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R5: **CLOSED / ACCEPTED.** R5 was a strict read-only
Windows ACL assessment and hardening decision closeout. No ACL or physical mutation occurred.
`D:\programas` dedicated to custody; inherited Authenticated Users mask `0x001301BF` lacks
`FILE_DELETE_CHILD`, `WRITE_DAC`, `WRITE_OWNER`. Human approved strict hardening (Option B):
disable inheritance, remove Authenticated Users and BUILTIN\Users, SYSTEM + Administrators
FullControl, executor ReadAndExecute. Preserved R5 phase-time state: target SDDL was
policy only and NOT applied; `D:\programas` remained inherited R4-era; custody-root ACL
was unchanged. The R6 closeout below supersedes this historical state.

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R6:
**CLOSED / ACCEPTED WITH DECLARED POST-MUTATION NONCONFORMITY.**
R6 execution classification: POST-MUTATION HARD STOP.
Physical DACL outcome: TARGET APPLIED / INDEPENDENTLY VERIFIED. One
`SetAccessControl` call; Apply EXIT 1; post-application `PropertyNotFoundStrict` in
the verification/serialization path. Retry and rollback NOT PERFORMED / PROHIBITED.
The parent DACL is protected with exactly three approved Allow ACEs; owner/group are
preserved; descendant ACLs have zero drift; artifact integrity remains 17/17.
Nonconformity: DECLARED / CONTAINED / NO DACL TARGET DEVIATION /
NO ARTIFACT INTEGRITY IMPACT / NO RETRY / NOT AN AUTHORIZED PRECEDENT.

Residual security risks remain accepted: owner-inherent DACL authority; elevated
Administrators FullControl; ACL is not immutability; source and destination share D:;
no independent redundancy; Level 3 not executed; source removal prohibited.
Security-complete custody: NOT CLAIMED.
Historical / superseded wording: "Level 2/3 not executed" — Level 2 is executed and
accepted; Level 3 remains not executed.

Preserved historical / superseded wording: "specific destination UNRESOLVED";
"NOT YET SELECTED"; "R2 is NOT STARTED"; "R3 is NOT STARTED"; "R4 is NOT STARTED";
"R5 is NOT STARTED"; "R5 não está autorizada"; "DESTINATION NOT YET PROVISIONED";
"PHYSICAL EXECUTION NOT AUTHORIZED AT THIS TIME"; the R3 phase-time state
`COPY_EXECUTION_CONTRACT_READY_AWAITING_HUMAN_AUTHORIZATION`; and the R5 pre-decision state
`PARENT_ACL_HARDENING_RECOMMENDED_AWAITING_HUMAN_DECISION`.

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R7: CLOSED / ACCEPTED.
R7 READ-ONLY ASSESSMENT: COMPLETE.
LEVEL2 EXECUTION CONTRACT: READY.
PHYSICAL LEVEL2 RESTORATION: NOT AUTHORIZED AT R7 TIME — superseded by the accepted
Level 2 execution recorded below.
R7 DOCUMENTARY CLOSEOUT: COMMITTED AND PUBLISHED under the authorized subject
`Record accepted R7 Level 2 restoration contract`; identity is resolved through Git history.
The assessment remained read-only; the published closeout changes exactly seven documents.
Level 2 candidate executed: `database.pre-D7.6B2-R2-hardening-20260613-184709.db`.
Fallback: `database.pre-D7.6B-schema-migration-20260613-180525.db` — NOT used
(fallback uses 0); requires separate human decision; never automatic.
Environment: NATIVE WINDOWS. R3-era container preference is historical/provisional;
R7 selected NATIVE WINDOWS and the executed Level 2 used it; no container fallback ready.

LEVEL 2 PHYSICAL RESTORATION (execution round R3):
**COMPLETE / LOCALLY VERIFIED / SUPERVISOR ACCEPTED.**
Executed under a separate explicit human physical order that resolved the timestamped
root into one concrete literal path: `D:\tmp\sgaa_restore_20260726T165550Z`.
Candidate `database.pre-D7.6B2-R2-hardening-20260613-184709.db`, 544768 bytes, SHA-256
`92627ded44c9094e74f01da5718c995cd3fdd5ac467ef79298541a75b777cd8c`; `sealed\` and
`working\` copies both match.
Validator outcome `SQLITE_LEVEL2_CHECKS_PASS`: integrity PASS, schema PASS, foreign-key
violations 0, business-data exposure 0.
SQLite connections: source 0, custody 0, sealed 0, working 1, total 1, fallback 0 — only
`working\` was opened, exactly once, by the qualified validator.
Evidence 7/7 complete, including `sqlite-result.json` (43682 bytes, SHA-256
`71bb40e4…5866`), `postflight.json` (2318 bytes, SHA-256 `e498af58…6176`) and
`level2-report.md` (SHA-256 `efaa34bd…3622`).
Restore-root ACLs: root Modify; `sealed\` and `working\` ReadAndExecute; `evidence\`
Modify. `D:\programas` retains the accepted protected three-ACE state.
Custody unchanged: 17/17 and 4,808,704 bytes, missing 0, mismatch 0, extras 0. R8
register: 11 entries, digest `75c00810…1023`. Package and qualification hashes unchanged.
Source preserved; Level 2 never authorizes source removal and none occurred.
Restore root and its `sealed\`, `working\` and `evidence\` contents remain PRESERVED
until a separate explicit cleanup order; automatic cleanup prohibited.
NO new SQLite opening is authorized.
Level 3 operational restoration: NOT STARTED / NOT AUTHORIZED.
Fase 2: AUTHORIZED / IN PROGRESS; PHASE2-D LOCALLY VERIFIED / AWAITING SUPERVISOR
REVIEW. A autorização arquitetural é separada da trilha de custódia e não autoriza
qualquer nova ação física sobre snapshots ou restore roots.

Exact next action:

Supervisor review of the Level 2 acceptance record. No further custody action is
authorized; restore-root cleanup, any new SQLite opening, the fallback candidate,
and Level 3 each require a new separate explicit human order. O antigo requisito de
uma nova ordem para iniciar a Fase 2 foi satisfeito por ordens humanas posteriores;
PHASE2-D agora aguarda revisão externa.

No physical order is issued by this record.

Historical / superseded next action: "a new separate explicit human physical Level 2
order restricted to the primary candidate and containing a concrete literal timestamped
root matching `D:\tmp\sgaa_restore_<UTC>`" — satisfied by the executed and accepted
Level 2 restoration.

Production shadow-only remains in force; production hard enforcement unauthorized.
D73H historical lane unchanged; R20 unchanged. The custody-track phase-time statement
that Phases 3–6 were unauthorized is superseded for Phase 3 only by the accepted Macro
Phase 3 closeout below. Phases 4–6 remain not authorized for execution.

### Fase 1 — Limpeza sem risco (0,5 dia)
- [x] Remover **código morto do aluno** (`@aluno_runtime_route` no-op em main.py) — CLOSED / ACCEPTED (PHASE-1-U3, commit c4fd2dd; 0 inserções, 756 deleções; oito exports de compatibilidade preservados).
- [x] Remover `templates/src.code-workspace-1.code-workspace` — concluído (PHASE-1-U1, CLOSED / ACCEPTED).
- [x] Remover `templates/admin_turmas-KRThinkpad.html` — concluído (PHASE-1-U2, CLOSED / ACCEPTED).
- [x] Remover imports mortos (wraps, Flask, bp_presets) + corrigir comentário hashlib — CLOSED / ACCEPTED (PHASE-1-U4, commit 742b67c; 2 inserções, 4 deleções; sem mudança comportamental).
- [x] Remover `tools/diag_out.txt` (artefato diagnóstico obsoleto) — CLOSED / ACCEPTED (PHASE-1-U5, commit 8b55230314605dcf9295072c109f04bea59323c3; 11.746 bytes; nenhum consumidor funcional).
- [ ] Unificar headers divergentes (`Referrer-Policy`) — fora do escopo da Fase 1.

### Historical / superseded

- [ ] Arquivar snapshots `database.pre-*.db` — historical / superseded Phase-1 checkbox; no archival performed or authorized; disposition moved to the autonomous custody track.

### Fase 2 — Extrair helpers compartilhados (quebrar o ciclo) (2–3 dias)
Mover de `main.py` para módulos próprios em `app/`, **um por PR**:
- [x] `app/security/passwords.py` — `hash_password`, `check_password`, legado.
- [x] `app/web/pagination.py` + `app/web/filters.py` — paginação e query helpers.
- [x] `app/text.py` — `normalize_header`, sort PT-BR, collation.
- [x] `app/presentation.py`, `app/requisition_policy.py`, `app/academics.py`,
      `app/uploads.py` e `app/reporting.py` — helpers/policies residuais da Category A.
- [x] Apontar consumidores diretos de `app/db.py` e `app/views/aluno.py` para os
      novos owners e remover os edges Category A correspondentes.
- [x] Remover as cinco entradas comprovadamente obsoletas da Category E nos lazy maps:
      `ensure_usuario_access_schema` e `ensure_usuario_profile_schema` de `core.py`;
      `REPORTE_STATUS_OPTIONS`, `save_upload` e `app` de `aluno.py`.

**Regra autoritativa de fechamento da Fase 2 — decisão humana explícita:** a Fase 2
remove dependências de helpers compartilhados e entradas obsoletas dos lazy maps.
Dependências de banco/schema/repository pertencem à Fase 3. Dependências de
versioning/views pertencem à Fase 4. Dependências de wiring/logging/routing pertencem
às fases posteriores que detêm esses domínios. A invariável final de arquitetura
continua obrigatória: zero back-references runtime de `app/` para `main`; ela deve ser
satisfeita antes do fechamento da Fase 6.

**Critério histórico/superado:** a antiga meta literal de que a Fase 2 só fecharia com
“nenhum `import main` dentro de funções de `app/`” foi superada por esta decisão humana
de ownership. As evidências históricas permanecem válidas como registro de seu tempo,
mas esse texto não transfere silenciosamente trabalho das Categories B, C ou D para a
Fase 2. A implementação PHASE2-D está localmente verificada e aguarda revisão externa;
este registro não declara a Fase 2 fechada.

### Macro Fase 3 — Consolidar acesso a dados — CLOSED / ACCEPTED

**Status:** CLOSED / ACCEPTED by external supervisor decision. Accepted technical
commit `c9009bf3d68950ad4e0499b65928603e84bee341`; accepted B11-R1 governance commit
`630d4eb448b992bdc3beb28752c30717989312bb`. All mandatory Phase 3 objectives are
satisfied; no open Phase 3 technical implementation remains.

- [x] Unificar `init_db` (uma única implementação em `app/db.py`) — satisfied by
      PHASE 3-B11; `main.init_db` is compatibility identity only.
- [x] Migrar os `ensure_*` ad-hoc para manutenção/migrações versionadas em
      `app/db_maintenance.py` + `schema_migrations` — satisfied through the accepted
      v1/v2/v3 registry, isolated destructive migration boundary and accepted schema owners.
- [ ] **OPTIONAL / NOT IMPLEMENTED / NOT A CLOSURE BLOCKER:** introduzir
      `app/repositories/` (ex.: `requisicoes_repo.py`, `alunos_repo.py`) extraindo
      queries das views. This optional item is deferred by design and is not silently
      assigned to Phase 4.

The Phase 3 closeout granted no Phase 4 authority. That historical prohibition was later
superseded only for the explicit PHASE 4-B1, PHASE 4-B2, PHASE 4-B3, PHASE 4-B4.1 and
PHASE 4-B4.2 units below. Migration v4 remains prohibited.

Current authorized checklist marker:
- [x] `app/views/admin/requisicoes.py` — PHASE 4-B4.2 CLOSED / ACCEPTED at technical commit
      `3231dbd2ff9759d8f855f2a4118102783aedea83`.
- [x] PHASE 4-B5-P — neutral admin-access shared-owner prerequisite CLOSED / ACCEPTED at
      technical commit `92486f87ea15697282a265cb7a9941678cb9138f` (parent
      `a0b56896252a276e562da3842d3d61b078bd9f27`). `app/admin_access.py` owns exactly the
      five admin-access context symbols; `main` re-exports by identity; no route moved at
      B5-P-time; B5 blueprint extraction was NOT AUTHORIZED at B5-P-time.
- [x] `app/views/admin/matrizes.py` — PHASE 4-B5 Matrizes admin blueprint extraction
      **CLOSED / ACCEPTED** at published technical commit
      `2a122357a79080fa66aa19c00ed5ff8533308f41`, subject
      `Extract admin matrices blueprint`, parent
      `ef874b9d14b02656a0f26ea885024a280d49682e`; publication and post-publication
      verification COMPLETE; external technical acceptance GRANTED; published manifest
      exactly 17 paths; protected `main` remains
      `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`.
      Exactly 10 global legacy endpoints / 12 route-method pairs and 21 corrected helpers
      owned by `app.views.admin.matrizes`; `main` identity re-exports with zero local
      bodies; factory keyword-only `register_admin_matrizes_blueprint=True`; RBAC 3 view /
      7 edit / 2 full; `app.auth`/`app.admin_access` unchanged; zero `app -> main`;
      ensures/SQL/transaction/UI/messages/CSRF frozen; void names
      `_get_grupos_atividade`/`_get_matriz_active_norma_ids` absent (classification
      `SUPERVISOR CONTRACT CORRECTION / NOT A PATH-POOL EXPANSION / NOT A DOMAIN-SCOPE
      EXPANSION`). Corrected RED `20 failed / 4 passed / 0 collection errors`; primary
      GREEN `24 passed / 3.74s`; focused expanded `578 passed / 249.33s`; first full
      `1049 passed / 1 failed / 17 deselected / 370.60s`; B5-R3 one-for-one mutable-pool
      substitution (node 1 passed / 0.64s; affected focused 143 passed / 24.30s); final
      full hermetic `1050 passed / 17 deselected / 0 failed / 0 errors / 317.65s`;
      routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0; actor 402; message
      catalog 536; route inventory byte-identical; CSRF `[8, 8]` owner-only; canonical
      SQLite opens 0. Contract:
      `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md`.
- [ ] `app/views/admin/alunos_turmas_cursos.py` (ou um por entidade)
- [ ] `app/views/admin/arquivos_alertas_reportes.py`
- [ ] `app/views/admin/banco_dados.py` (backup/restore/nuvem/oauth callbacks)
- [ ] `app/views/admin/acesso.py` — NOT IMPLEMENTED; the combined Acesso work is not complete
      and no later Configurações cohort is included in accepted B1.
- **Subsystem de versionamento:** movido para `app/versioning/` (resolver, snapshot,
      shadow read, diagnóstico) por B2 — CLOSED / ACCEPTED. This prerequisite versioning
      extraction for later Atividades, Matrizes and Requisições cohorts is satisfied.

### Fase 4 — Quebrar `main.py` em blueprints admin — OPEN / INCREMENTAL IMPLEMENTATION / B1-B3, B4-A, B4.1, B4.2, B5-P AND PHASE 4-B5 CLOSED / ACCEPTED / B5-A DIAGNOSIS COMPLETE

Um blueprint por área de negócio, **um PR por blueprint**, sempre com:
inventário de rotas verde + RBAC atualizado + `pytest` verde.
- **PHASE 4-B1 — CLOSED / ACCEPTED:** accepted technical commit
      `cd8a76b2484abc376174332578ecd8be4b8206ea`, subject
      `Extract admin configuration blueprint`, parent
      `7f393c72ad3e9d70eae4c06ee41e0d74881e40f2`.
      `app/views/admin/configuracoes.py` owns exactly eight
      Configurações/Mensagens routes and eight settings helpers. The reusable registrar in
      `app/views/admin/__init__.py` preserves global legacy endpoints without aliases or
      namespaced routes. Contract:
      `docs/refactor/PHASE4_ADMIN_BLUEPRINT_COMPATIBILITY_CONTRACT.md`.
      B1-R1 establishes deterministic filesystem-recursive repository-tree message and
      canonical CSRF-owner discovery under `app/views/**/*.py`; it does not query or filter
      through the Git index. Accepted gates: targeted 47 passed; full hermetic 939 passed /
      17 deselected; post-publication 91 passed; routes 131; endpoints 130; governed pairs
      134; RBAC unmapped 0; independent Flash FREE review PASS; exact 13-path manifest; no
      database, migration, template, JavaScript, RBAC or snapshot delta.
- **PHASE 4-B2 — CLOSED / ACCEPTED:** published technical commit
      `17e468ad938e873e1f9e9c303808ad31b9f3806b`, parent
      `2fbe4954106dc8d410f6495ca8bd4b1956b326d2`. Canonical owners are
      `app.versioning.resolver`, `app.versioning.snapshots`,
      `app.versioning.shadow_reads` and `app.views.admin.versioning`; `main` retains
      identity compatibility only. Exactly three legacy GET diagnostics and their
      existing RBAC requirements are preserved through the B1 registrar. The aluno
      lazy-main map drops the two versioning entries and retains exactly six accepted
      residual dependencies. R1 repairs the repository-root dedicated/fallback logs and
      preserves logger identity `main` without importing `main`. Accepted evidence:
      contract 14; affected lane 241; full hermetic 954 passed / 17 deselected /
      343.75s / exit 0; routes 131; endpoints 130; governed pairs 134; RBAC unmapped 0;
      actor matrix 402 = 263 allowed + 139 denied; index-visible 271 passed;
      post-publication 282 passed; exact 24-path artifact = 8 production
      + 10 tests + 6 governance; canonical
      database, protected residual and route snapshot unchanged. Contract:
      `docs/refactor/PHASE4_VERSIONING_SUBSYSTEM_CONTRACT.md`. The FREE attempt
      `opencode/deepseek-v4-flash-free` (`ses_0433de371ffefBa8J03FBmkoV4`, cost 0,
      exit 0) was UNUSABLE DELIVERY / NO VERDICT; fallback
      `FALLBACK_FREE_UNUSABLE_DELIVERY`. Accepted review:
      `opencode-go/deepseek-v4-flash`, session `ses_043375c9affeYmMxqtbpNjNohl`, cost
      `0.01838004 USD`, exit 0, diff SHA-256
      `a97275ac9f29cefcfd8ed4d3038ce37f552a886036481be0f7fd1c7f85a373b7`, mutation 0,
      PASS, material findings 0. LOW matrix status-label was REJECTED AS NON-MATERIAL /
      SEMANTIC EQUIVALENCE PROVED. External `baseline_main.py` scratch, SHA-256
      `2652d1213d7f0b5ac577ebddb528341448e9eb0afb8b41d051e5826a56d4af48`, was outside
      the repository, not staged/committed, selectively removed and had no candidate/index
      impact. The final documentary review addendum used `flash_free`,
      `opencode/deepseek-v4-flash-free`, session `ses_0431aa4d7ffev4hTZImBDA86Ca`, cost 0,
      and returned PASS with no fallback. Publication and post-publication verification are
      complete.
- **PHASE 4-B3 — CLOSED / ACCEPTED:** technical commit
      `50801b6bdddc4d2772853c13f4905c49e8c996cf`, parent
      `81cc6b10b893f1d34bd211a527e9fd12c3b6bbbe`; exact 16-path artifact. Exactly 22 legacy
      Atividades/CRUD/import/groups/versioned-catalog/normas/legacy-mapping endpoints and 29
      route/method combinations are owned by `app.views.admin.atividades` through the accepted
      legacy registrar. `app.activity_catalog` neutrally owns 14 shared helpers;
      `app.uploads` neutrally owns `save_upload`, which retains non-B3 consumers and uses the
      active app upload root. Matrizes/Requisições route bodies remain in `main`; no B2 helper,
      schema or migration moved. B3-R1 proves message inventory 536→536 with zero key/default/
      semantic delta and CSRF snapshots with exactly 15 owner-only deltas each. B3 contract 19
      passed; affected lane 353. The 974/17/292.86s run is historical pre-final-test-delta;
      final exact-candidate hermetic requalification passed 974 / 17 deselected / zero
      failures/errors in 399.95s. Routes 131;
      endpoints 130; governed pairs 134; RBAC unmapped 0; actor matrix 402; route snapshot and
      protected physical artifacts unchanged. Index-visible and post-publication gates passed
      300/300. Provisional
      FREE review (`opencode/deepseek-v4-flash-free`, session
      `ses_0425bf1cbffeIxMwsDQn0etSEC`, cost 0, no fallback) was UNUSABLE DELIVERY / NO VERDICT.
      The final FREE session `ses_0422f0e1cffepCXyNpg47dWpoq`, cost 0, timed out after 600s;
      accepted fallback used `opencode-go/deepseek-v4-flash`, session
      `ses_04224ca47ffe5qAwwHGtxlR7i7`, router cost `0.0010424344 USD`, hash
      `ec96796d3541710a36ac8121e40ffd888737c7c926f191a28034482cedbfd556`, mutation 0, PASS,
      findings NONE. IAsup accepted PASS; canonicalization concern was REJECTED_INCORRECT and
      no-test limitation ACCEPTED_NONBLOCKING. Frozen non-governance hash
      `13b0af13e653641d75d2466d7d8d69090e655a18e28bb678a7090dbe0e2ecab0`. Final publication
      hash `c41ffe5b7328b6d5a986dbdc28f054fe89641496589003b4e5649ff88463cc19`; governance hash
      `af2906ef0fa9fef7fdd469dd4e967cd1c914b4bfb21fc2a132b8d74c2d8dfd27`. Documentary
      addendum first REJECTED stale historical Documentation Index wording; the governance-only
      correction then passed under `opencode-go/deepseek-v4-flash`, session
      `ses_04203dca3ffe8OM83rhbHyjqYI`. Publication and post-publication verification are COMPLETE.
      The B3-R1 scope expansion is reconciled exactly, including message and CSRF owner-only
      proofs. Contract:
      `docs/refactor/PHASE4_ATIVIDADES_BLUEPRINT_CONTRACT.md`.
- [x] PHASE 4-B4.1 neutral shared-owner prerequisite — `app/settings.py`,
      `app/requisitions.py` and `app/matrix_scope.py`; identity-preserving re-exports;
      CLOSED / ACCEPTED at technical commit
      `73ebf0dc34681e74e778759af476e1cd2f981444`, parent
      `185426daccc9f0eb0dba4497248100c1a88d15fa`; exact 20-path artifact = 7 production +
      7 tests + 6 governance. Publication and post-publication verification are COMPLETE.
      Final hermetic 984/17; index-visible/post-publication 170/170; technical review PASS;
      documentary addendum PASS. NO ROUTE MOVEMENT; EXACT 9 REQUISICOES ROUTES REMAIN IN
      MAIN.PY / 12 route-method pairs. Contract:
      `docs/refactor/PHASE4_REQUISICOES_SHARED_OWNER_CONTRACT.md`.
  - **`app/views/admin/requisicoes.py` — [x] PHASE 4-B4.2 CLOSED / ACCEPTED.** Published
      technical commit `3231dbd2ff9759d8f855f2a4118102783aedea83`, subject
      `Extract admin requisitions blueprint`, parent
      `c587098152e97d125f41a2d26f2f414c10ae5676`; exact 16-path artifact = 3 production +
      7 tests/snapshots + 6 governance. Publication and post-publication verification are
      COMPLETE. The canonical owner contains exactly nine
      global legacy endpoints / 12 route-method pairs through the accepted registrar, with
      RBAC `view=4`, `edit=5`, `full=3`. `main` retains identity exports; the factory supports
      default registration and exact cohort opt-out; no `app -> main` edge exists. Focused
      lanes pass 138 + 107; routes remain 131, endpoints 130, governed pairs 134, RBAC
      unmapped 0, actor matrix 402, message catalog 536; each CSRF snapshot has exactly five
      owner-only deltas. Contract:
      `docs/refactor/PHASE4_REQUISICOES_BLUEPRINT_CONTRACT.md`.
      The first full lane exposed four stale governance assertions without physical drift
      (`1001 passed / 4 failed / 17 deselected`); after the bounded documentary correction,
      final hermetic qualification completed at `1005 passed / 17 deselected / 362.33s`;
      index-visible 57 passed; post-publication 56 passed / 1 deselected; zero failures/errors.
      Flash FREE technical review session `ses_03ff5695bffeEBNIZRiSVZonYz` returned PASS,
      blocking NONE, scope EXACT, behavior PRESERVED, governance COHERENT, mutation 0 and no
      fallback; its one nonblocking hash-method documentation finding was corrected.
      The accepted documentary addendum requested `flash_free`, selected `flash_normal` under
      `FALLBACK_FREE_BUDGET_EXHAUSTED`, and passed under
      `opencode-go/deepseek-v4-flash`, session `ses_03fce2ebbffejkf6IUdfPrsxF3`, mutation 0
      and outside-scope reads 0. Flash FREE itself did not complete that addendum.
- **PHASE 4-B5-A — DIAGNOSIS COMPLETE / SHARED_OWNER_PREREQUISITE REQUIRED** and
      **PHASE 4-B5-P — CLOSED / ACCEPTED.** Neutral admin-access shared-owner
      prerequisite at technical commit `92486f87ea15697282a265cb7a9941678cb9138f`
      (`Extract admin access context shared owner`), parent baseline HEAD
      `a0b56896252a276e562da3842d3d61b078bd9f27` (`Record acceptance of Phase 4-B4.2`);
      protected `main` `340fc7c91c6bc9b50e884adcb5915f9e29a0bfe1`. `app/admin_access.py`
      canonically owns exactly `_fetch_user_access_overrides`,
      `_build_access_scope_groups_for_level`, `_load_admin_access_context`,
      `_get_current_admin_access_context` and `_admin_can`; `main.py` has zero local bodies
      and re-exports all five by identity; all moved bodies are AST-identical to parent
      `a0b56896252a276e562da3842d3d61b078bd9f27:main.py`. Six exact main consumers: `enforce_admin_access_control`,
      `inject_admin_access_helpers`, `admin_editar_matriz`, `admin_matriz_nova_atividade`,
      `admin_acesso`, `uploaded_file`. Import graph: `app.admin_access -> app.auth, app.db,
      app.db_maintenance` and Flask `g`/`session`; `app.admin_access -> main = 0`;
      `app.auth -> app.admin_access = 0`; no cycle. Actual 11-path candidate manifest (2
      production + 3 tests + 6 governance) within the updated ceiling 12 (2 production +
      pool of 4 tests + 6 governance); the authorized but unchanged
      `tests/test_ref_0c_b1_p0_access_context_transactions.py` remains a gate, not a changed
      path. Evidence: corrected pre-production RED 20 failed; first core GREEN attempt
      2 failed / 23 passed corrected without production mutation (grouped ordering follows
      `ACCESS_RESOURCE_GROUPS`; `__wrapped__` introspection); recovered core lane 25 passed;
      focused lane 168 passed; first full hermetic 1 failed / 1024 passed / 17 deselected;
      B5-P-R1 classification
      `PRE_REVIEW_SCOPE_EXPANSION / NOW_EXPLICITLY_RATIFIED /
      NO_RETROACTIVE_GENERIC_AUTHORITY` with
      `B4_2_BASELINE_COMMIT=c587098152e97d125f41a2d26f2f414c10ae5676`; R1 exact node 1
      passed; B5-P-R2 SUPPLEMENTAL SCOPE AUTHORIZATION added and modified only
      `tests/test_phase4_requisicoes_shared_owners.py`, reading accepted B4.1 governance
      from the same fixed commit `c587098152e97d125f41a2d26f2f414c10ae5676`, preserving
      B4.1 closure/publication/assertions and separately proving current B4.2 CLOSED /
      ACCEPTED, B5-P IMPLEMENTED / AWAITING SUPERVISOR REVIEW, Phase 4 OPEN, Phase 5 and
      Phase 6 NOT AUTHORIZED, Migration v4 PROHIBITED; classification
      `PRE_REVIEW_SCOPE_EXPANSION / EXPLICITLY_AUTHORIZED_B5_P_R2 /
      FIXED_ACCEPTED_B4_1_BASELINE / NO_RETROACTIVE_GENERIC_AUTHORITY`; R2 exact node 1
      passed in 1.02s; affected governance aggregate 118 passed in 16.70s; final
      pre-publication hermetic after R2 total collected 1042 = 1025 passed + exactly 17
      D73H deselected; 0 failed; 0 errors; 326.74s; exit 0 (the earlier 1025/17/306.41s
      run is only pre-R2 historical evidence); independent-review rerun 1025/17/0/0 in
      367.27s; post-publication focused 132 passed / 0 failed / 0 errors / 39.23s.
      Routes 131; endpoints 130; business
      pairs 160; governed pairs 134; RBAC unmapped 0; actor 402 = 263 allowed + 139 denied;
      message catalog 536; route inventory byte-identical (20814 bytes, SHA-256
      `6e32148c…49fa`); CSRF shadow-off/on byte-identical to HEAD and each other (each
      288349 bytes, SHA-256 `3a94e2e1…a0056`); canonical database 544768 bytes /
      `a3a55e63…70fe9`, WAL/SHM/journal absent, opens 0; protected residual 17420 bytes /
      `7388cfbc…bb0e`. Routing: IAsup Hermes `openai-codex/gpt-5.6-sol`; IAexec continuity
      session `ses_03ce1c465ffeb31XEcAo57hbC4`; initial `flash_free`, explicit fallback
      `opencode-go/deepseek-v4-flash`, trigger `FALLBACK_FREE_CONTEXT_TOO_LARGE`; router
      costs RED correction 0.0008019144 USD / GREEN 0.0009146312 USD / test correction
      0.0007943432 USD. Earlier B5-P governance authoring succeeded via `flash_normal`,
      `opencode-go/deepseek-v4-flash`, session `ses_03cb9cee8ffeyk6hJFuMcmRrgD`, exit 0,
      cost 0.0013047696 USD, no fallback, exact six governance mutations; a later
      continuation attempt to that expired/nonexistent session failed with
      `FLASH_NORMAL_FAILED / Session not found / no session / no cost / no mutation`,
      recorded as a recoverable transport/session failure. The fresh explicit delegation
      then succeeded via `flash_normal`, `opencode-go/deepseek-v4-flash`, session
      `ses_03c9ae6a7ffe4XeucPqy9Iyrre`, exit 0, cost `0.0005911248 USD`, with no fallback
      and mutations limited to the same six governance paths; the R2 test correction was
      a direct IAsup Sol correction (deterministic,
      exact, tiny, safer/cheaper than another context export). Accepted independent
      read-only review: provider `opencode`, model `opencode/deepseek-v4-flash-free`,
      session `ses_03c92c10affegAmZLZ63tmTjjA`, exit 0, cost 0, fallback none, mutation 0,
      blocking 0, nonblocking 3 (R2 no literal `NO ROUTE MOVEMENT` token;
      `B4_2_BASELINE_COMMIT` naming; runtime duration changed); external acceptance
      GRANTED by the PHASE 4-B5-P-R3 order. Technical commit `92486f87…` is published;
      publication and post-publication verification are COMPLETE; governance closeout is
      published. The former pre-publication pending state is historical and superseded.
      This B5-P bullet is the accepted neutral admin-access shared-owner prerequisite and
      is **historical / superseded for the blueprint stage** by PHASE 4-B5 below. Its
      phase-time statements that `app/views/admin/matrizes.py` remains absent and that
      PHASE 4-B5 blueprint extraction is NOT AUTHORIZED are B5-P closeout-time history only.
      Contract:
      `docs/refactor/PHASE4_MATRIZES_SHARED_OWNER_CONTRACT.md`.
- **PHASE 4-B5 — Matrizes admin blueprint extraction — CLOSED / ACCEPTED.** Published
      technical commit `2a122357a79080fa66aa19c00ed5ff8533308f41`, subject
      `Extract admin matrices blueprint`, parent
      `ef874b9d14b02656a0f26ea885024a280d49682e`; exact 17-path published manifest;
      publication COMPLETE; post-publication verification COMPLETE; external technical
      acceptance GRANTED. The former unstaged/uncommitted/unpushed and awaiting-review
      statements are historical pre-publication facts superseded by this state.
      `app.views.admin.matrizes` canonically owns
      exactly 10 global legacy endpoints / 12 route-method pairs and 21 corrected helpers;
      `main` re-exports all by identity with zero local bodies/decorators; `bp_admin_matrizes`
      + immutable `LEGACY_ROUTE_SPECS` via the accepted `LegacyRouteSpec` /
      `configure_legacy_routes` registrar; no `@bp.route`, namespaced alias, duplicate,
      wrapper, `import main`, dynamic import or `sys.modules` edge; factory keyword-only
      `register_admin_matrizes_blueprint=True` (default exact 10/12, opt-out exact);
      independent apps isolated; collisions fail atomically; order deterministic after the
      accepted admin cohorts. RBAC exactly 3 view / 7 edit / 2 full; `app/auth.py` and
      `app.admin_access` unchanged; `admin_editar_matriz` / `admin_matriz_nova_atividade`
      consume the same canonical `_get_current_admin_access_context` / `_admin_can` objects;
      `_persist_user_access_overrides` and `_parse_access_overrides_from_form` remain
      main-local; zero `app -> main`. Direct owners consumed: `app.matrix_scope`,
      `app.activity_catalog`, `app.db`, `app.db_maintenance`, `app.web.filters`,
      `app.web.pagination`, `app.auth`, `utils.messages`, and only `_build_grupo_label` /
      `_canonicalize_tipo_limitacao` from `app.views.admin.atividades`. Ensures
      (`ensure_matrizes_atividades_table`, `ensure_matriz_atividade_links_table`,
      `ensure_atividade_versioning_schema`), GET timing, SQL, transactions, commits/
      rollbacks/exceptions, version/matrix links, templates, `url_for`, redirects, flashes/
      messages, CSRF and HTTP frozen; zero redesign/hardening. Void names
      `_get_grupos_atividade` and `_get_matriz_active_norma_ids` remain absent
      (classification `SUPERVISOR CONTRACT CORRECTION / NOT A PATH-POOL EXPANSION / NOT A
      DOMAIN-SCOPE EXPANSION`). Evidence: preimplementation ownership/governance nodes
      3 passed; corrected TDD RED `20 failed / 4 passed / 0 collection errors`; primary B5
      GREEN `24 passed / 3.74s`; focused expanded (44 files) `578 passed / 249.33s`; first
      full `1049 passed / 1 failed / 17 deselected / 370.60s` (sole failure: configuracoes
      package membership; HARD STOP); B5-R3 one-for-one mutable-pool substitution (node
      1 passed / 0.64s; affected focused 143 passed / 24.30s); final full hermetic fresh
      `1050 passed / 17 deselected / 0 failed / 0 errors / 317.65s` (collected 1067);
      accepted post-publication bounded lane `59 passed / 0 failed / 0 errors / 22.59s`;
      routes 131; endpoints 130; business pairs 160; governed pairs 134; RBAC unmapped 0;
      actor 402 = 263 allowed + 139 denied; message catalog 536; route inventory
      byte-identical (20814 bytes, SHA-256 `6e32148c…49fa`); CSRF exactly `[8, 8]`
      owner-only deltas (78 rows each, summaries equal, no non-owner delta); canonical
      database 544768 bytes / `a3a55e63…70fe9`, WAL/SHM/journal absent, opens 0; protected
      residual 17420 bytes / `7388cfbc…bb0e`; `app/admin_access.py` byte-identical
      (4546 bytes, SHA-256 `b2dc2592…d9814`). Routing: IAsup Hermes
      `openai-codex/gpt-5.6-sol`; RED IAexec logical/effective `flash_free`,
      `opencode` / `opencode/deepseek-v4-flash-free`, session `ses_03b57ca6bffenOnPYH3mt5WdX0`,
      exit 0, cost 0, fallback none; implementation IAexec logical `flash_free` → selected
      `flash_normal` by `FALLBACK_FREE_CONTEXT_TOO_LARGE`, actual
      `opencode-go` / `opencode-go/deepseek-v4-flash`, same session, exit 0, cost
      `0.0010985912`, no silent escalation; corrections IAsup direct (two deterministic RED
      typos; B5-R3 membership expressly authorized). Exact 11-path technical manifest
      (3 production + 8 tests/snapshots) within ceiling 18 after governance;
      `tests/test_phase4_requisicoes_shared_owners.py` authorized but unchanged;
      `tests/test_ref_0c_b1_p0_access_context_transactions.py` read-only focused gate,
      unchanged. Accepted technical review history: initial `flash_free`, effective
      `opencode/deepseek-v4-flash-free`, session `ses_03adb7f27ffeJ1feNSLhrFij5R`, exit 1,
      cost 0, TECHNICAL EXECUTION FAILURE / NO USABLE VERDICT / NO MUTATION; explicit
      `FALLBACK_FREE_EXECUTION_FAILURE` to `opencode-go/deepseek-v4-flash`, session
      `ses_03ad0a15dffeR53I9BqGU6a4tl`, exit 0, cost `0.001000188`, mutation 0, PASS /
      SCOPE EXACT / BEHAVIOR PRESERVED, blocking 0, nonblocking 4; no Pro/Luna/GPT
      escalation. Contract: `docs/refactor/PHASE4_MATRIZES_BLUEPRINT_CONTRACT.md`.
      PHASE 4 remains OPEN / INCREMENTAL IMPLEMENTATION; Phase 5/6 remain NOT AUTHORIZED;
      Migration v4 remains PROHIBITED.

      **Section-22 historical process deviation:** the Section-22 pre-implementation
      reconciliation gate was NOT executed before the first B5 production mutation as
      required by the original order. `SECTION_22_PROCESS_DEVIATION: VALID`;
      `ORIGINAL ORDERING REQUIREMENT: NOT SATISFIED`; `DISCOVERED: BEFORE PUBLICATION`;
      `LATE RECONCILIATION: EXECUTED / GREEN`; `TECHNICAL IMPACT: NONE DEMONSTRATED`;
      `SUPERVISOR ADJUDICATION: ACCEPTED_NONBLOCKING_GOVERNANCE_DEBT /
      PREPUBLICATION_PROCESS_DEVIATION / LATE_GATES_GREEN /
      NO_RETROACTIVE_COMPLIANCE_CLAIM`. The B5-R4 hard stop detected the missing record
      before publication. The B5-R5 waiver superseded only the pre-push documentary
      blocker and authorized one normal fast-forward publication of the frozen technical
      commit unchanged. This closeout records the deviation truthfully; it does not claim
      that Section 22 was satisfied retroactively or that the original ordering was met.
- **Historical/superseded checklist token (not current):** the following literal represented
      the pre-acceptance B3/B4.2 state and is preserved only for phase-time contract tests:
      ```text
      - [ ] `app/views/admin/atividades.py`
      - [ ] `app/views/admin/requisicoes.py`
      ```
- [x] `app/views/admin/atividades.py` (+ catálogo versionado) — CLOSED / ACCEPTED;
      `app.activity_catalog` established and the B3 prerequisite is complete.
- [x] `app/views/admin/matrizes.py` — PHASE 4-B5 CLOSED / ACCEPTED; see the published
      technical identity and Section-22 historical record above.
- [ ] `app/views/admin/alunos_turmas_cursos.py` (ou um por entidade)
- [ ] `app/views/admin/arquivos_alertas_reportes.py`
- [ ] `app/views/admin/banco_dados.py` (backup/restore/nuvem/oauth callbacks)
- [ ] `app/views/admin/acesso.py` — NOT IMPLEMENTED; the combined Acesso work is not complete
      and no later Configurações cohort is included in accepted B1.
- **Subsystem de versionamento:** movido para `app/versioning/` (resolver, snapshot,
      shadow read, diagnóstico) por B2 — CLOSED / ACCEPTED. This prerequisite versioning
      extraction for later Atividades, Matrizes and Requisições cohorts is satisfied.

Phase 4 is not closed. PHASE 4-B4-A, PHASE 4-B4.1 and PHASE 4-B4.2 are CLOSED / ACCEPTED.
B4.1 remains the accepted shared-owner prerequisite. The
bounded expansion is reconciled: all eight B1 settings-helper bodies move from their B1-time
Configurações owner to neutral `app.settings` with Configurações/`main` identity exports;
`app.matrix_scope` owns exactly the six shared matrix-scope symbols; Aluno removes only the
`get_effective_matriz_for_turma` lazy-main edge, reducing the B2-time six residual edges to
five at B4.1-time; the Phase-3 test delta is governance-reader-only. Technical review used
`flash_free` / `opencode/deepseek-v4-flash-free`, session
`ses_040d538bfffegBsAJQbLJrnqSV`, cost 0, reviewed hash
`f4b6cb00b4365cc7c20af5fcba1ac736ece1bab0ab9c6e0f89b19084799727f9`, mutation 0,
PASS / findings NONE. Exact artifact: 20 paths = 7 production + 7 tests + 6 governance;
final hermetic 984 passed / 17 deselected; index-visible 170; post-publication 170; message
catalog 536. Documentary addendum `flash_free`, `opencode/deepseek-v4-flash-free`, session
`ses_040ae7625ffeHCGZxyXoMzoQmw`, cost 0, mutation 0, PASS / findings NONE; its read-scope
deviation is `READ_SCOPE_DEVIATION / NON_MUTATING / PHYSICALLY_RECONCILED /
NO_CANDIDATE_IMPACT`. External supervisor acceptance is recorded by B4.1-R2. No B4.1
technical residual remains.
For B4.2, the exact 16-path technical artifact was published at
`3231dbd2ff9759d8f855f2a4118102783aedea83` from parent `c587098...`; final hermetic
qualification, independent review, publication and post-publication verification are
complete. Exactly nine
Requisições handlers / 12 route-method pairs moved; `main` preserves identities and no route,
RBAC, transaction, message, template, document, versioning or matrix-scope behavior changed.
`dashboard.py` and `admin_meus_dados` ownership remain unresolved and are not complete.
Accepted identities preserve the raw/Git-canonical distinction: complete
`1b8435a9db10f8a2ae680f60c17a9ad0a723eed88066a834ca59255bf7b8cc0e` /
`c362566627667ba684765ad3ea8fdeb9abf7678dd52e185cedd3ed8b08a891b4`; governance
`19519783e02bf983f820d357e6c2b250db541581fae57f6988e64cf1900f544d` /
`b44ae4231aaaeb022c2cfc2ca94f20be76a94dd7e82c51e97966866d294d0ceb`; production/test raw
`f60ebdab5cd1e7aa2d98d9ade66534925c5a077326dff2e70b24c72e6390c037`.
The B4.2 governance closeout changes exactly six governance paths under authorized subject
`Record acceptance of Phase 4-B4.2`; identity resolves through Git history. No technical path
is changed by the closeout. The former prepublication candidate state and its outstanding
documentary, Git-publication and external-acceptance gates are superseded; RED/GREEN,
first-failed-full-suite, review/fallback, hash-normalization and authorized scope-expansion
history remain preserved. For B5-P, only the neutral admin-access shared-owner
      prerequisite is implemented and CLOSED / ACCEPTED: `app.admin_access` owns exactly the
      five admin-access context symbols, `main` re-exports them by identity, and the actual
      artifact is 11 paths (2 production + 3 tests + 6 governance) within the updated ceiling
      12 (the B5-P-R2 test `tests/test_phase4_requisicoes_shared_owners.py` reads accepted
      B4.1 governance from fixed commit `c587098152e97d125f41a2d26f2f414c10ae5676`).
      Accepted technical commit `92486f87ea15697282a265cb7a9941678cb9138f` (parent
      `a0b56896252a276e562da3842d3d61b078bd9f27`); publication and post-publication
      verification COMPLETE; accepted independent review session
      `ses_03c92c10affegAmZLZ63tmTjjA`; governance closeout published. This B5-P
      prerequisite is CLOSED / ACCEPTED; its phase-time statement that Matrizes was
      NOT STARTED / NOT AUTHORIZED is B5-P closeout-time history only. For PHASE 4-B5,
      the Matrizes admin blueprint extraction is now **CLOSED / ACCEPTED** at technical
      commit `2a122357a79080fa66aa19c00ed5ff8533308f41`, subject
      `Extract admin matrices blueprint`, parent
      `ef874b9d14b02656a0f26ea885024a280d49682e`; publication and post-publication
      verification COMPLETE; external technical acceptance GRANTED. `app.views.admin.matrizes` owns exactly 10 global
      legacy endpoints / 12 route-method pairs and 21 corrected helpers; `main` re-exports
      by identity with zero local bodies; factory keyword-only
      `register_admin_matrizes_blueprint=True`; RBAC 3 view / 7 edit / 2 full;
      `app.auth`/`app.admin_access` unchanged; zero `app -> main`; ensures/SQL/transaction/
      UI/messages/CSRF frozen; void names absent (`SUPERVISOR CONTRACT CORRECTION / NOT A
      PATH-POOL EXPANSION / NOT A DOMAIN-SCOPE EXPANSION`). Corrected RED
      `20 failed / 4 passed / 0 collection errors`; primary
      GREEN `24 passed / 3.74s`; focused expanded `578 passed / 249.33s`; first full
      `1049 passed / 1 failed / 17 deselected / 370.60s`; B5-R3 one-for-one mutable-pool
      substitution (node 1 passed / 0.64s; affected focused 143 passed / 24.30s); final full
      hermetic `1050 passed / 17 deselected / 0 failed / 0 errors / 317.65s`; reviewer gates
      51 passed / 6.19s + supplemental requisicoes csrf/route/owners 3 passed; routes 131;
      endpoints 130; governed pairs 134; RBAC unmapped 0; actor 402; message catalog 536;
      route inventory byte-identical; CSRF `[8, 8]` owner-only; canonical SQLite opens 0.
      Accepted post-publication bounded lane 59/0/0/22.59s. Frozen identities and the
      Section-22 process deviation are recorded in the contract.
PHASE 5: NOT AUTHORIZED. PHASE 6: NOT AUTHORIZED. MIGRATION V4:
PROHIBITED. No later route cohort beyond PHASE 4-B5 is marked complete or authorized.

### Fase 5 — Mover backup/sync para fora do request (1–2 dias)
- [ ] Tirar `_maybe_sync_database_snapshot` do `after_request`; transformar em
      comando/job (`flask backup-sync`) acionado por cron/scheduler externo.
- [ ] (Se for multi-worker) mover rate-limit de login para backend externo
      (Redis) ou aceitar limite por-worker conscientemente.

### Fase 6 — `main.py` vira só entrypoint (0,5 dia)
- [ ] Ao final, `main.py` deve ter ~50–150 linhas: `from app import create_app;
      app = create_app()` + `if __name__ == "__main__": app.run(...)`. Toda
      lógica vive em `app/`.

> **Estimativa total:** ~3–4 semanas de trabalho focado (ou bem mais rápido com
> IA assistindo, justamente porque os módulos ficam pequenos). Cada fase deixa o
> app **100% operacional** — nada precisa de "freeze".

## Estrutura-alvo (depois do refactor)

```
app/
├── __init__.py            # create_app (já existe)
├── config.py              # configuração por ambiente (extraída)
├── extensions.py          # csrf, compress (instâncias)
├── security/
│   ├── passwords.py
│   └── rbac.py            # (hoje auth.py) níveis/recursos/escopos
├── db/
│   ├── connection.py
│   └── migrations.py      # schema_migrations versionado
├── repositories/          # queries por entidade (opcional mas recomendado)
├── services/              # integrações externas (já existe)
├── versioning/            # resolver + snapshot + diagnóstico de atividades
└── views/
    ├── core.py            # login/logout
    ├── aluno.py           # blueprint aluno (já existe)
    └── admin/             # um blueprint por área
main.py                    # ~50 linhas: cria e roda a app
```

## Como manter operacional durante o refactor (checklist por PR)

Para **cada** PR de refactor:
1. Branch a partir de `clean-baseline`.
2. `pytest` verde localmente (e em CI, se houver).
3. Teste de **inventário de rotas** verde (nada some/renomeia sem querer).
4. Teste de **cobertura RBAC** verde (nenhuma rota admin sem permissão).
5. Smoke manual rápido: login admin + login aluno + 1 requisição ponta-a-ponta.
6. PR pequeno, com descrição "move X, sem mudança de comportamento".
7. Merge → verificar app subindo (`run.bat`) antes do próximo PR.

> **Recomendação de processo para IAs:** depois da Fase 4, peça que cada tarefa
> de IA seja escopada a **um blueprint/módulo**. Com arquivos de 200–800 linhas,
> a IA consegue carregar o contexto inteiro do módulo, o que reduz drasticamente
> erros e alucinações. Mantenha um `CLAUDE.md`/`AGENTS.md` curto apontando para
> esta pasta de mapeamento e para os dois invariantes sagrados (inventário de
> rotas + cobertura RBAC).
