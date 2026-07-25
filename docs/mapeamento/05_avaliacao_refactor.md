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

**Historical snapshot custody: OPEN / POLICY APPROVED / CANONICAL_DESTINATION_UNRESOLVED / PHYSICAL ACTION NOT AUTHORIZED.**
Separate governance/administrative track. Does not integrate Phase 1, Phase 2,
or any architectural implementation phase.
See `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md`.

Transferred residual governance matter:
HISTORICAL-DATABASE-SNAPSHOT-CUSTODY
Status: R1 CLOSED / ACCEPTED (policy approved; specific destination UNRESOLVED).
No archival performed or authorized.

Exact next action:

HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R2 — read-only canonical destination
requirements and controlled-copy contract boundary.

R2 is NOT STARTED, requires a separate explicit order and is not authorized
for physical mutation.

Future R2 objectives: define objective destination requirements; evaluate real
available options; select specific destination by human decision; draft copy
contract; define disposable restoration environment; define Level 2 and Level 3
gates. R2 will not execute a copy. Phase 2 remains
without authorized next action.

Production shadow-only remains in force; production hard enforcement unauthorized.
D73H historical lane unchanged; R20 unchanged. Fases 2–6 (target architecture) remain
preserved as originally defined below but unauthorized.

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
- [ ] `app/security/passwords.py` — `hash_password`, `check_password`, legado.
- [ ] `app/web/pagination.py` + `app/web/filters.py` — paginação e query helpers.
- [ ] `app/text.py` — `normalize_header`, sort PT-BR, collation.
- [ ] Apontar `app/db.py`, `core.py`, `aluno.py` para os novos módulos e
      **remover os `import main` lazy** correspondentes.
Meta da fase: **nenhum `import main` dentro de funções de `app/`**.

### Fase 3 — Consolidar acesso a dados (2–4 dias)
- [ ] Unificar `init_db` (uma única implementação em `app/db.py`).
- [ ] Migrar os `ensure_*` ad-hoc para migrações versionadas em
      `app/db_maintenance.py` + `schema_migrations`.
- [ ] (Opcional) introduzir `app/repositories/` (ex.: `requisicoes_repo.py`,
      `alunos_repo.py`) extraindo as queries das views.

### Fase 4 — Quebrar `main.py` em blueprints admin (4–8 dias, o grosso)
Um blueprint por área de negócio, **um PR por blueprint**, sempre com:
inventário de rotas verde + RBAC atualizado + `pytest` verde.
- [ ] `app/views/admin/requisicoes.py`
- [ ] `app/views/admin/atividades.py` (+ catálogo versionado)
- [ ] `app/views/admin/matrizes.py`
- [ ] `app/views/admin/alunos_turmas_cursos.py` (ou um por entidade)
- [ ] `app/views/admin/arquivos_alertas_reportes.py`
- [ ] `app/views/admin/banco_dados.py` (backup/restore/nuvem/oauth callbacks)
- [ ] `app/views/admin/acesso.py` + `app/views/admin/configuracoes.py`
- [ ] Mover o subsistema de **versionamento** para `app/versioning/`
      (resolver, snapshot, shadow read, diagnóstico).

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
