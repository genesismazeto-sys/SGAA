# 04 — Arquitetura e módulos

## Visão de dependências

```
                       ┌─────────────────────────────┐
                       │          main.py            │  15.494 linhas
                       │  • app = create_app()       │  • ~113 rotas
                       │  • regras de negócio        │  • helpers de schema
                       │  • versionamento/resolver   │  • backup/sync
                       └──────┬───────────────┬──────┘
              importa (topo)  │               │  importam main em RUNTIME (lazy)
                              ▼               ▲   (ciclo!)
                    ┌──────────────────┐      │
                    │  app/__init__.py │      │
                    │  create_app()    │      │
                    └───┬─────────┬────┘      │
                        │         │           │
        ┌───────────────┘         └────────┐  │
        ▼                                  ▼  │
  app/views/core.py   app/views/aluno.py  presets_api.py
  (login/logout)      (bp_aluno)          (bp_presets)
        │  import main (lazy)  │ import main (lazy) ──────┘
        ▼                      ▼
  app/auth.py   app/db.py ──(import main lazy: ensure_*, hash_password)──┐
  app/db_maintenance.py   app/cloud_drives.py   app/student_documents.py │
  app/services/*          services/*            utils/*  ◄───────────────┘
```

**O nó do problema:** existe um **ciclo de dependência** entre `main.py` e o
pacote `app/`. `main.py` importa `create_app` de `app` no topo; e
`app/db.py`, `app/views/core.py`, `app/views/aluno.py` importam de volta o módulo
`main` em **runtime** (lazy, dentro de funções) para pegar dezenas de helpers
(`ensure_*`, `hash_password`, `check_password`, `get_db_connection`, `aluno_url`,
etc.). O lazy-import é o "band-aid" que faz o ciclo não estourar no import.

Isso é o sintoma mais claro de que a extração para módulos **começou mas não
terminou**: a lógica foi "fatiada" para `app/`, mas o miolo continua em `main.py`
e os módulos novos puxam de volta o miolo.

## Inventário de módulos

| Módulo | Linhas | Responsabilidade | Saúde |
|--------|-------:|------------------|-------|
| `main.py` | 15.494 | Tudo: app, rotas admin, negócio, schema, versionamento, backup | 🔴 monólito |
| `app/__init__.py` | 434 | `create_app`, segurança, CSRF, headers, registro de rotas core | 🟢 bom |
| `app/auth.py` | 477 | RBAC (níveis/recursos/escopos), decorators, rate limit | 🟢 bom |
| `app/db.py` | 453 | Conexão + `init_db` (puxa helpers de main) | 🟡 ciclo |
| `app/db_maintenance.py` | 444 | Migrações versionadas, snapshot, retenção, sync nuvem | 🟢 bom |
| `app/cloud_drives.py` | 445 | Abstração de contas de nuvem | 🟢 bom |
| `app/views/aluno.py` | 2.119 | Blueprint do aluno (ativo) | 🟡 grande mas coeso |
| `app/views/core.py` | 138 | login/logout/index (puxa helpers de main) | 🟡 ciclo |
| `app/services/google_drive_service.py` | 290 | OAuth+upload Google | 🟢 bom |
| `app/services/backup_service.py` | 266 | Zip de backup SQLite | 🟢 bom |
| `app/services/token_encryption.py` | 124 | Fernet p/ tokens | 🟢 bom |
| `app/student_documents.py` | 119 | Salvamento/sanitização de docs de aluno | 🟢 bom |
| `services/onedrive_service.py` | 563 | OAuth+upload OneDrive (MSAL) | 🟢 bom |
| `services/oauth_config.py` | 137 | Redirect URIs / base URL | 🟢 bom |
| `presets_api.py` | ~230 | API de presets (blueprint) | 🟢 bom |
| `utils/messages.py` | 998 | Mensagens editáveis + flash | 🟡 grande |

Observação: a maior parte do pacote `app/` e dos `services/` está **bem feita** —
módulos pequenos, coesos, com responsabilidade clara. O peso morto está
concentrado em `main.py`.

## O que existe dentro de `main.py` (mapa interno)

Pela varredura de `def`/decorators, `main.py` mistura ~10 responsabilidades que
deveriam ser módulos separados:

1. **Bootstrap/app object** (`app = create_app`, config legada, logging).
2. **Helpers de senha** (`hash_password`, `check_password`, legado).
3. **Helpers de parsing/paginação/filtros** (`get_pagination`, `get_*_query`,
   `append_*_condition`, `normalize_header`, sort PT-BR).
4. **Schema/migração** (`init_db` duplicado, dezenas de `ensure_*`,
   `_recreate_*`, `_migrate_*`).
5. **Configurações** (`get/save_app_settings`, backup settings, retention, drive).
6. **RBAC runtime** (`_admin_can`, `_load_admin_access_context`, overrides).
7. **Versionamento de atividades** (resolver, shadow read, snapshot,
   diagnóstico) — ~1.500+ linhas.
8. **Backup/nuvem** (`_maybe_upload_to_drives`, `_maybe_sync_database_snapshot`,
   contas cloud).
9. **Rotas admin** (~113) — requisições, atividades, matrizes, alunos, turmas,
   cursos, arquivos, alertas, reportes, banco-dados, acesso, configurações.
10. **Código morto do aluno** (`@aluno_runtime_route` no-op).

## Dívidas técnicas (priorizadas)

### 🔴 1. Monólito `main.py` (15k linhas)
O maior obstáculo para humanos e IAs. Qualquer mudança exige carregar 15k linhas
de contexto; o risco de efeito colateral é alto; ferramentas de IA têm que ler o
arquivo inteiro para entender uma rota. **É o item nº 1 a atacar.**

### 🔴 2. Ciclo `main ↔ app` via lazy import
`app/db.py`, `core.py`, `aluno.py` fazem `import main` dentro de funções. Isso:
- impede mover lógica sem mexer em dois lados;
- esconde dependências reais (não aparecem no topo);
- torna testes e refactors arriscados.
A direção correta: helpers compartilhados descem para módulos de `app/`
(`app/security.py`, `app/repositories/`, `app/services/`), e `main.py` deixa de
ser fonte de helpers.

### 🟡 3. Código morto do aluno
~6 views `aluno_*` em `main.py` decoradas com `@aluno_runtime_route` (no-op
porque `USE_ALUNO_BLUEPRINT=True`). Devem ser **removidas** (o blueprint já é a
verdade). Antes de remover, confirmar que nada importa essas funções por nome.

### 🟡 4. Migrações ad-hoc + `init_db` duplicado
`init_db` existe em `main.py` e `app/db.py`; ALTERs em try/except. Convergir para
`schema_migrations` (já existe a infra em `db_maintenance`).

### 🟡 5. Sync de backup no `after_request`
`_maybe_sync_database_snapshot` + retenção + upload nuvem rodam em **toda
resposta** (`main.py:5208`). Custo de latência e acoplamento; deveria ser job
agendado / fora do request. Crítico para serverless (ver [06](06_deploy_e_infraestrutura.md)).

### 🟡 6. Dupla modelagem de atividades (legado + versionado)
Concluir a migração `atividade_legacy_map` e aposentar `atividades` quando
possível reduz muito a complexidade do resolver.

### 🟢 7. Itens menores
- Headers duplicados/divergentes entre os dois `after_request`.
- Estado de rate-limit em memória (multi-worker).
- `templates/admin_turmas-KRThinkpad.html` — PHASE-1-U2 CLOSED / ACCEPTED. Template excluído e aceito externamente em 5932dff.
- `templates/src.code-workspace-1.code-workspace` — removido por PHASE-1-U1 (CLOSED / ACCEPTED).
- Snapshots `database.pre-*.db` na raiz — sujeitos a decisão de custódia de dados. Nenhum outro candidato de limpeza está autorizado.

## Pontos fortes da arquitetura (preservar no refactor)

- **`create_app` factory** já existe e é boa (segurança por ambiente, guard-rails
  de produção). É a fundação certa.
- **RBAC** desenhado de forma declarativa e central (`app/auth.py`).
- **CSRF** robusto e automático.
- **Camada de serviços** (`services/`, `app/services/`) já isola integrações
  externas — modelo a replicar para o resto.
- **Cobertura de testes alta** (70 arquivos) — a rede de segurança que torna o
  refactor viável.
- **Blueprint do aluno** já provou o caminho de extração (de main → blueprint).
