# 05 — Avaliação do refactor (Pergunta 1)

> **Pergunta do dono:** vale um refactor de arquitetura para ficar o mais
> profissional e modular possível, facilitar a vida das IAs e evitar quebras de
> rota / falhas de autenticação? Qual o plano para manter tudo operacional?

## Veredito

**Sim, vale — mas com escopo cirúrgico, não um rewrite.** O app é maduro e
seguro; o problema é **organização**, concentrada em um arquivo (`main.py`,
15.494 linhas) e num **ciclo de dependências** que ficou pela metade. O objetivo
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

### Macro Fase 0 — Rede de segurança — fechamento aberto com resíduos delimitados

**Status: PHASE_0_REMAINS_OPEN_WITH_BOUNDED_REMAINDER** (2026-07-22)

#### Phase-0 completion matrix

| Requirement | Canonical source | Implemented by phase | Commit | Test/evidence | Status |
|---|---|---|---|---|---|
| Stable route inventory | `tests/test_route_inventory_snapshot.py` + `tests/_artifacts/route_inventory_baseline.json` | REF-0B | `f2b1cfc` | 131 rules, 130 endpoints, 160 business methods; read-only comparison | SATISFIED |
| RBAC coverage | `tests/test_rbac_requirement_coverage.py` + `tests/_artifacts/rbac_unmapped_routes_baseline.json` | REF-0B | `f2b1cfc` | 0 unmapped admin routes; dynamic enumeration from `main.app.url_map` | SATISFIED |
| Unmapped-route detection | Same RBAC coverage test; dynamic from `main.app.url_map` | REF-0B | `f2b1cfc` | Filters `/admin` paths, calls `get_admin_permission_requirement` | SATISFIED |
| Actor/access-level matrix | `tests/test_ref_0c_b1_rbac_high_confidence_mappings.py`, `tests/test_ref_0c_b2_diagnostic_rbac.py` | REF-0C-B1, REF-0C-B2 | `932c6d7`, `c9e1843` | B1: 36 tests covering R1-R21 actor matrix; B2: 18 tests covering R22-R24. Routes per (resource,scope) group are representative, not route-complete. | PARTIALLY_SATISFIED |
| Denied-action immutability | Same B1 + B2 test files | REF-0C-B1, REF-0C-B2 | `932c6d7`, `c9e1843` | B1: `test_denied_post_atividades_edit_is_immutable`, `test_denied_post_matrizes_edit_is_immutable`; B2: domain-state equality checks. Representative per domain group, not route-complete. | PARTIALLY_SATISFIED |
| Access-context isolation | `tests/test_ref_0c_b1_p0_access_context_transactions.py` | REF-0C-B1-P0 | `92b25d2` | 5 tests: transaction-neutral, idempotent, no lock/FK failure on rebuild | SATISFIED |
| Deterministic hermetic suite | Full `pytest` suite with D73H deselected | REF-0TF-B, REF-0C-B1-P0 through REF-0C-C-B1-R1 | `9b47c37`, cumulative | 601 passed, 17 deselected; no failures/errors/skips/xfails/xpasses | SATISFIED |
| D73H historical isolation | `--run-d73h-historical` marker, `pytest.ini` | REF-0TF-B | `9b47c37` | 17 tests deselected by default; CLI options for historical lane; optional lane still needs sanitized artifacts | SATISFIED_WITH_ACCEPTED_RESIDUAL_RISK |
| Testing/development fail-closed | `AdminAuthorizationConfigurationError` in `app/auth.py`, `enforce_admin_access_control` | REF-0C-C-B1 | `fb90cc1` | `test_ref_0c_c_b1_fail_closed_shadow_gate.py` raises hard error in non-production | SATISFIED |
| Production shadow audit | `_audit_missing_admin_authorization_configuration` in `main.py` | REF-0C-C-B1, REF-0C-C-B1-R1 | `fb90cc1`, `39f7732` | Safe shadow event; logger failure caught locally, does not block request; one event can be lost on logger failure | SATISFIED_WITH_ACCEPTED_RESIDUAL_RISK |
| Smoke-flow requirements | `tools/smoke_test.py`, `tools/smoke_test_admin.py`, `tools/smoke_test_rbac_permissions.py` | REF-0B onward (tools exist) | Cumulative | Tools exist but no frozen manual smoke-flow list defined in repository | PARTIALLY_SATISFIED |
| Production hard enforcement | N/A (not a Phase-0 completion criterion) | N/A | N/A | Production remains shadow-only; no permanent allow-open switch | NOT_APPLICABLE |
| R20 status | Central `matrizes`/`edit` mapping in `get_admin_permission_requirement` | REF-0C-B1 (central mapping); local `readonly` unchanged | `932c6d7` | Central gate enforces; local `readonly` is inert; cleanup unauthorized | SATISFIED_WITH_ACCEPTED_RESIDUAL_RISK |

#### Formal REF-0C-D decision

**Decision: B. PARTIALLY_SATISFIED_REMAINDER_REQUIRED.**

Repository evidence confirms complete route mapping and complete governed-boundary classification, but actor HTTP and denied-mutation tests are representative (R1-R24 sample), not route-complete for every governed admin business route-method pair × every denied access level.

**Missing invariant:** Route-complete actor decision and pre-handler denied-action immutability coverage over every current governed admin business route-method pair and every denied admin access level derived from the canonical resource/scope model.

**Affected set (exact by rule):** Every governed admin business route-method pair from `tests/_artifacts/route_inventory_baseline.json` where `classify_governed_admin_request(..., method)["governed"]` is True and `get_admin_permission_requirement(endpoint, method)` returns a non-None `(resource, scope)`, crossed with admin access levels `admin_total`, `administrativo`, `consultivo` whose effective scope does not satisfy the requirement, **excluding** only combinations already directly covered by accepted HTTP denial tests. Anonymous and aluno outer-auth behavior is already accepted but is not the missing invariant — the gap is admin-level actor matrix completeness.

**Required tests:** Test-only, fixture-controlled, parametrized from canonical route inventory/classifier, proving expected allow/deny at the permission layer for every access level, proving each denied combination returns the central browser/AJAX contract before handler execution, and proving no fixture domain mutation.

**Proposed phase:** REF-0C-D-R1. Prohibited: production code, UI, schema, dependencies, production hard enforcement, R20 cleanup, route changes, and Fases 1–6.

#### Macro Fase 0 decision

**Decision: PHASE_0_REMAINS_OPEN_WITH_BOUNDED_REMAINDER.**

Two bounded remainders:
1. **REF-0C-D-R1** — route-complete actor and immutability coverage (see above). Authorizable, not authorized.
2. **Smoke-flow contract/evidence** — frozen manual smoke-flow list for admin login, aluno login, create requisicao, process requisicao, backup. Not yet defined or proven in the repository.

The remainder smoke-flow requirement does not block REF-0C-D-R1. They are independent.

#### Next authorizable action

**REF-0C-D-R1 only.** It is authorizable, not authorized. Fase 1 and production hard enforcement remain unauthorized. Fases 1–6 (target architecture) are preserved as originally defined below but remain unauthorized.

### Fase 1 — Limpeza sem risco (0,5 dia)
- [ ] Remover **código morto do aluno** (`@aluno_runtime_route` no-op em main.py).
- [ ] Remover lixo: `templates/admin_turmas-KRThinkpad.html`,
      `templates/src.code-workspace*`, snapshots `database.pre-*.db` (arquivar).
- [ ] Unificar headers divergentes (`Referrer-Policy`).
- [ ] Limpar comentário "hashlib" enganoso.

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
