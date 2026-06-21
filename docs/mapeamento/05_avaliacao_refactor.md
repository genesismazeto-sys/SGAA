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

### Fase 0 — Rede de segurança (1–2 dias) ✅ pré-requisito
- [ ] Teste de **inventário de rotas** (snapshot do `url_map`).
- [ ] Teste de **cobertura RBAC** (toda rota admin tem permissão exigida).
- [ ] Garantir que `pytest` roda limpo e rápido; documentar como rodar.
- [ ] Congelar uma lista de **smoke flows** manuais (login admin, login aluno,
      criar requisição, processar, backup) — `tools/smoke_test*.py` já ajudam.

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
