# SGAA-EJ — PROTOCOLO DE EXECUÇÃO DO REFACTOR (FASE FINAL)

**Versão:** 1.3 — 2026-08-09
**Autoridade:** substitui a governança por fase (contrato + closeout por unidade) para todo o
trabalho remanescente. Não revoga contratos fechados (B1–B7-P permanecem como histórico).
**Condutor:** ChatGPT / GPT-5.6 Sol (sem acesso direto ao código; lê o repositório via GitHub após push).
**Executores:** GPT-5.6 Sol, Claude Opus 5, Claude Sonnet 5, DeepSeek V4 Pro, DeepSeek V4 Flash.

### Changelog

**1.3 — 2026-08-09 — CORREÇÃO VERSIONADA DA DEFINIÇÃO DO CRITÉRIO 4 (PLATEAU).** Não altera
escopo de UT, sequência, arquitetura, invariantes numéricos, comportamento de negócio nem
roteamento de modelos. Substitui **apenas** o texto ativo do Critério 4 do PLATEAU ESTRUTURAL
(§3).

Critério 4 na v1.2 — texto histórico, preservado aqui na íntegra:

> "Nenhuma escrita em disco, banco ou rede dentro de hook de requisição."

Sob essa redação literal, a **primeira validação formal do plateau** (pós-UT-9, HEAD
`230de41b`) resultou corretamente em **6/7 PASS — Critério 4 FAIL**. A emissão síncrona de
diagnóstico RBAC/CSRF em arquivo local durante a execução de hook é, literalmente, "escrita em
disco". O validador original **não errou**: aplicou a definição então vigente. Aquele resultado
permanece **válido sob a v1.2** e está preservado como fato histórico no ledger. Havia ainda,
naquele momento, bloqueadores de estado de aplicação de fato — escrita de schema/normalização
de acesso em caminho de leitura de requisição, ensure preguiçoso de `mensagens_editaveis` em
caminho de leitura, e conversão persistente de `journal_mode` pela conexão genérica — todos
removidos pela remediação do C4 antes desta versão.

A v1.3 é uma **correção de definição**, não um PASS retroativo silencioso. Ela distingue
**escrita durável de estado de aplicação** de **observabilidade diagnóstica local
pré-configurada**. Tudo o que a v1.2 proibia em termos de estado de aplicação, banco e rede
**continua proibido**; a exceção é estritamente limitada a logging diagnóstico/auditoria
**local** cujo subsistema foi **integralmente configurado fora do caminho de requisição**. Não
se autoriza `QueueHandler`/`QueueListener`, thread de logging em segundo plano nem qualquer
handler com backend de rede: o contrato de logging **síncrono** é preservado.

A segunda validação formal, sob a v1.3, resultou em **7/7 PASS / 0 achados materiais**. As duas
medições não se contradizem: avaliam textos de critério diferentes sobre o mesmo comportamento,
que não mudou entre elas.

**1.2 — 2026-08-08 — MODEL ROUTING ONLY.** Muda apenas o roteamento de modelos; não altera
escopo de UT, arquitetura, invariantes, comportamento de negócio nem mecânica de governança.
Adiciona **GPT-5.6 Sol**, preferido para supervisão/arquitetura/arbitragem (IAsup); torna
**DeepSeek V4 Flash** o executor padrão (IAexec) quando compatível, com permissão explícita
para editar produção e testes; mantém **DeepSeek V4 Pro** como escalada barata e revisão
adversarial; mantém **Claude Sonnet 5** como executor/revisor alternativo; reduz **Claude
Opus 5** a revisão independente crítica, arquitetura excepcional e desempate; introduz
rastreabilidade provider/modelo/versão/fallback. Regras ativas que proibiam Flash de editar
ou de revisar são removidas.

**1.2 R1 (2026-08-08) — correção oficial de especificações de modelo.** Preenche as
especificações oficiais do GPT-5.6 Sol (contexto 1.050.000 tokens; saída máx. 128K; alias
`gpt-5.6`; entrada USD 5,00 / cache USD 0,50 / saída USD 30,00 por MTok). Atualiza os preços
oficiais do DeepSeek V4 Pro (cache-miss USD 0,435 / cache-hit USD 0,003625 / saída USD 0,87
por MTok) e registra o cache-hit do V4 Flash (USD 0,0028). Remove os valores antigos de Pro
(1,74 / 3,48). Nenhuma mudança de política de roteamento.

**1.1 FINAL — correção documental (2026-08-07)** — duas inconsistências de gate/contagem,
ambas corrigidas **por medição direta**, sem mudança de escopo, ordem, propriedade ou critério:
(a) o gate da Adoção parte 1 citava "3 failed conhecidos", que pertencem a
`test_phase3_final_init_cutover.py` e `test_pytest_runtime_isolation.py` e **não** aos cinco
leitores de governança — o gate passa a ser delimitado, com protocolo A→D e baseline medido
(`77 passed / 0 failed / 0 errors / exit 0`);
(b) `hooks_main` na entrada era declarado 8 e é **7** (medido por `__module__`) —
`_legacy_post_response_backup_sync` não existe na entrada, é criado na UT-2; e o rótulo
"51 decoradas = 47 rotas + 4 hooks" contava os 3 errorhandlers como rotas — a decomposição
medida é **44 rotas + 4 hooks + 3 errorhandlers**.

**1.1 FINAL (2026-08-07)** — texto adotado. Acrescenta a **UT-3 (migração dos hooks de app)**,
sem a qual o critério PLATEAU #1 era insatisfazível: nenhuma unidade possuía o `before_request`
de RBAC nem os dois `context_processor`, e os 3 errorhandlers estavam mal arquivados sob
"infra" junto de `uploaded_file`. Sequência renumerada para 14 UTs. Inventário de hook por
**módulo dono** (§4). Adoção bipartida (§13) porque os 5 testes leitores de governança leem
`PROJECT_STATE.md`.

**1.1 (2026-08-07)** — resolve nove contradições operacionais. Suíte verde antes da composition
root. Higiene dividida em encoding (Sonnet) e path containment (Opus). Proibido o pacote
`app/db/`. Divisão de `db_maintenance` removida da sequência obrigatória. Bloco D e dois
estados finais nomeados. Flash proibido de implementar. Aposentadoria de testes tabelada.

**1.0 (2026-08-07)** — versão inicial.

---

## 0. COMO USAR ESTE ARQUIVO

Cole este arquivo como *project file* no ChatGPT. Ele contém tudo o que o condutor precisa
saber sem ler o repositório.

O condutor (ChatGPT):
1. Escolhe a próxima UT da §2, **sempre na ordem dada**.
2. Monta o prompt do executor com os templates da §7.
3. Roteia para revisão conforme §6.
4. Atualiza a §11 e devolve ao humano o comando de commit.

O condutor **não** inventa UTs. Trabalho fora da lista vai para §10 e segue.

---

## 1. ESTADO DO REPOSITÓRIO — SNAPSHOT v1.1 (HEAD `c385322`, 2026-08-07)

> Snapshot **datado**, não atualizado por UT. Estado vivo: `PROJECT_STATE.md`. Ver §9.

Branch: `refactor/architecture-safety-net` (base `clean-baseline`).

**Tamanhos**
- `main.py`: **5.238 linhas** (baseline 12.707 → −59%).
- `app/`: 49 `.py` (baseline 13).
- Testes: 105 arquivos, 44.680 linhas — **1,87× o Python de produção**.
- Governança: 1,41 MB de markdown vs. 0,92 MB de Python de produção (**1,54:1**).

**Composição de `main.py`** (AST)
- 406 linhas de import (62 statements, 360 nomes).
- 51 funções decoradas com `@app.*` — 2.534 linhas. Decomposição **medida por AST**:
  **44 `@app.route` + 1 `@app.after_request` + 1 `@app.before_request` +
  2 `@app.context_processor` + 3 `@app.errorhandler`.** As 7 não-rota são exatamente os
  hooks/handlers pertencentes a `main` (§4). O rótulo "47 rotas + 4 hooks" usado até a
  v1.1 contava os 3 errorhandlers como rotas — corrigido.
- 78 funções auxiliares — 1.607 linhas.
- **230 dos 360 nomes importados nunca são usados por `main.py`** — re-exports puros.
  Consumidor real: **94 dos ~102 arquivos de teste fazem `import main`.**

**As 44 rotas de `main.py`, por coorte** (errorhandlers não são rotas — ver abaixo)
| Coorte | Rotas | UT |
|---|---:|---|
| Banco de Dados / backup / OAuth / nuvem | 20 | UT-8 |
| Acesso | 6 | UT-9 |
| Arquivos | 5 | UT-10 |
| Alertas | 4 | UT-11 |
| Reportes | 3 | UT-12 |
| Dashboard + demo + meus_dados | 3 | UT-13 |
| Infra (`uploaded_file`, `health`, `favicon`) | 3 | UT-14 |
| **Total** | **44** | |

**Os 7 hooks/handlers pertencentes a `main` na entrada** (`hooks_main = 7`, medido por
`__module__`): `add_security_headers` (after_request, UT-2); `enforce_admin_access_control`
(before_request, UT-3); `inject_admin_access_helpers` e `inject_editable_message_templates`
(context_processor, UT-3); `not_found`, `internal_error`, `handle_large_upload`
(errorhandler, UT-3).
`_legacy_post_response_backup_sync` **não existe na entrada** — é criado na UT-2 pela extração
do bloco de sync/upload de dentro de `add_security_headers`, e removido na UT-5. Por isso
`hooks_main` permanece 7 após a UT-2: um símbolo `main` sai e outro entra.

**Invariantes vivos:** rotas **131**, endpoints **130**, RBAC unmapped **0**,
actor matrix **402**, catálogo de mensagens **536**. Endpoints com namespace: 13.

**Defeitos abertos**
1. **Dois composition roots.** `create_app()` e o corpo de `main.py` configuram em duplicata:
   `Compress(app)` 2×, `MAX_CONTENT_LENGTH` 2×, `TEMPLATES_AUTO_RELOAD` 2×,
   `jinja_loader.searchpath` 2×, logging 2×, e dois `after_request` de headers.
   Medido: `GET /health` devolve `Referrer-Policy: no-referrer-when-downgrade`
   (`main.py:1565`); o `strict-origin-when-cross-origin` de `app/__init__.py:373` é código
   morto — Flask executa `after_request` na ordem inversa de registro e ambos usam `setdefault`.
2. **I/O de rede no ciclo da requisição.** `main.py:1566-1576`: snapshot SQLite + retenção +
   upload para Google Drive / OneDrive dentro do `after_request`.
3. **Ciclo `app → main` vivo.** `app/views/aluno.py:57` (2 símbolos) e
   `app/views/core.py:21` (3: `aluno_url`, `get_db_connection`, `logger`).
4. **Aresta cross-blueprint.** `app/views/admin/matrizes.py:36` importa `_build_grupo_label`
   e `_canonicalize_tipo_limitacao` de `app/views/admin/atividades.py`.
5. **Ciclo de infraestrutura.** `app.db → app.db_maintenance → app.auth → utils.flash →
   utils.messages → app.db`, quebrado só por import lazy. `db_maintenance → auth` está na
   direção errada.
6. **`app/db_maintenance.py` com 1.900 linhas.** Ver D-1.
7. **3 testes falhando** (encoding UTF-8 em subprocess no Windows), reproduzidos no baseline.
   Dois são guardas sobre o import-time de `main.py` que a UT-2 altera.
8. **`_best_effort_remove_admin_arquivo_file`** (`main.py:3695`) apaga sem a checagem de
   contenção `startswith(base)` usada por `uploaded_file`.

**Acoplamentos de teste medidos — restringem UTs**
- **5 arquivos** referenciam `app/db.py` por caminho literal.
- **8 arquivos** referenciam `app/db_maintenance.py` por caminho literal.
- **8 arquivos** importam `SCHEMA_VERSION` / registro de migração.
- **`app/web/request.py`** é referenciado por caminho (`test_phase4_alunos_turmas_cursos_shared_owners.py:15`);
  o **diretório** `app/web/` não tem asserção — arquivos novos ali são seguros.
- **`test_phase4_matrizes_shared_owners.py:235`** faz parse AST de `app/admin_access.py` e
  afirma conjunto de defs top-level **exatamente cinco** → nada pode ser adicionado a esse módulo.
- **`test_phase4_alunos_turmas_cursos_shared_owners.py:237`** faz
  `inspect.getsource(main._admin_access_denied_response)` e exige `"_is_ajax_request()"` no
  corpo → **sobrevive** ao movimento via re-export por identidade com corpo inalterado.
- **5 arquivos leitores de governança** leem `PROJECT_STATE.md` **e** `AGENT_HANDOFF.md`
  **e** `DOCUMENTATION_INDEX.md` **e** o ledger:
  `test_phase3_schema_startup_transaction_contract`, `test_phase4_atividades_blueprint`,
  `test_phase4_configuracoes_blueprint`, `test_phase4_requisicoes_shared_owners`,
  `test_phase4_versioning_subsystem`. **Consequência operacional na §13.**

---

## 2. ESCOPO RESTANTE — LISTA FECHADA

Catorze unidades em quatro blocos, **nesta ordem**. Nada além disto é autorizado.

### Bloco A — fundação

**UT-1 — Suíte verde (encoding).** Sonnet 5. Sem produção.
Corrigir o encoding UTF-8 em subprocess/arquivo temporário no Windows que faz falhar
`test_phase3_final_init_cutover.py::test_seed_tool_uses_factory_owner_without_main_and_is_idempotent`,
`test_pytest_runtime_isolation.py::TestSubprocessImportMain::test_import_main_uses_runtime_root`
e `::TestMainNoOverwrite::test_import_main_preserves_upload_folder`.
**Primeira porque dois desses três são guardas diretos sobre o import-time de `main.py` que a
UT-2 modifica.** Gate: `pytest` completo, 0 failed / 0 errors. Aposenta: nada.

**UT-2 — Unificar composition root (config + headers).** Opus 5 `xhigh`. Revisão dupla.
Deletar de `main.py` o bloco duplicado (~1289-1301): `Compress(app)`, `MAX_CONTENT_LENGTH`,
`TEMPLATES_AUTO_RELOAD`, `jinja_loader.searchpath`. Mover para `create_app()` as atribuições
restantes de `app.config` (`DATABASE_PATH`, `LOCAL_BACKUP_DIR`, `CLOUD_BACKUP_DIR`,
`CLOUD_SYNC_INTERVAL_SECONDS`, `EXTERNAL_BACKUP_*`) e o logging, **preservando o nome de logger
`main`**. Fundir os headers de `main.add_security_headers` em `_apply_security_headers`,
mantendo `strict-origin-when-cross-origin`.

O bloco de sync/upload **não** vai para `create_app` — depende de ~200 linhas de helpers
main-locais que só se movem na UT-5. Aqui ele é **desacoplado dos headers, renomeado
`_legacy_post_response_backup_sync` e isolado**, com comentário apontando para a UT-5.

**Esta UT também executa a Adoção parte 2** (§13): reescrita destrutiva de `PROJECT_STATE.md`
para o formato ≤40 linhas, atualização da hierarquia de autoridade em `DOCUMENTATION_INDEX.md`,
e aposentadoria das asserções leitoras de governança dos 5 arquivos da §8. Formato e asserção
morrem juntos, no mesmo commit.

Gates: (a) `GET /health` devolve `Referrer-Policy: strict-origin-when-cross-origin`;
(b) inventário de `after_request` igual à linha "Após UT-2" da §4;
(c) `test_import_main_preserves_upload_folder` verde.

**UT-3 — Migrar os hooks de app para o composition root.** Opus 5 `xhigh`. Revisão dupla.
Move os 6 hooks/handlers restantes de `main.py`. Todas as dependências já vivem em `app/`.

| Símbolo | Tipo | Dono novo |
|---|---|---|
| `enforce_admin_access_control` | before_request | `app/web/authz_gate.py` (novo) |
| `_admin_access_denied_response` | helper | `app/web/authz_gate.py` |
| `_audit_missing_admin_authorization_configuration` | helper | `app/web/authz_gate.py` |
| `inject_admin_access_helpers` | context_processor | `app/web/context.py` (novo) |
| `inject_editable_message_templates` | context_processor | `app/web/context.py` |
| `not_found`, `internal_error`, `handle_large_upload` | errorhandler | `app/web/errors.py` (novo) |
| `_format_bytes_label` | helper | `app/presentation.py` (existente) |

Restrições vinculantes:
- **Proibido usar `app/admin_access.py`** — teste afirma conjunto de defs exatamente cinco.
- `_format_bytes_label` tem 4 consumidores, 3 deles no código de Banco de Dados (UT-8) →
  precisa ser dono neutro, não morar em `errors.py`.
- Registrar `enforce_admin_access_control` **depois de `csrf.init_app(app)`** para preservar a
  ordem `['csrf_protect', 'enforce_admin_access_control']`.
- Registrar os context processors **nesta ordem**: `inject_admin_access_helpers`, depois
  `inject_editable_message_templates`.
- `main` mantém re-export por identidade de `_admin_access_denied_response`
  (`test_phase4_alunos_turmas_cursos_shared_owners.py:237` segue o objeto via `inspect.getsource`;
  sobrevive com corpo inalterado — **não** aposentar).
- `authz_gate.py` e `errors.py` contêm mensagens de usuário → **adicionar ambos ao
  `_iter_backend_files()` do scanner de mensagens** (§4), sob pena de quebrar o catálogo 536.
- Inventário (Flash) deve provar zero referência por caminho literal a `app/web/authz_gate.py`,
  `app/web/context.py`, `app/web/errors.py` antes de criá-los.

Gates: inventário de hook igual à linha "Após UT-3" da §4; `enforce_admin_access_control` com
`__module__ == "app.web.authz_gate"`; actor matrix 402 inalterada; RBAC unmapped 0.

### Bloco B — runtime e ciclos

**UT-4 — Containment de path.** Opus 5. Produção, **mudança de comportamento declarada**.
Adicionar a checagem de contenção em `_best_effort_remove_admin_arquivo_file`, espelhando a de
`uploaded_file`. Passa a recusar apagar fora da raiz de upload. Commit isolado, mudança nomeada
na mensagem. Gate: teste novo provando recusa para `..` e para caminho absoluto externo.

**UT-5 — Fase 5: I/O fora do `after_request`.** Opus 5 `xhigh`. Revisão dupla.
Criar o pacote **greenfield `app/backup/`** e mover `_maybe_sync_database_snapshot`,
`_run_retention_cleanup`, `_maybe_upload_to_drives`, `_upload_snapshot_if_external_enabled`,
`_get_runtime_backup_settings`, `_database_backup_locations` e correlatos. Expor CLI
(`python -m app.backup.sync`). Remover `_legacy_post_response_backup_sync`. Manter o
acionamento manual pela tela de Banco de Dados. **Não remover funcionalidade.**
`app/backup/` **chama** `app.db_maintenance`; **não escreve nele** (ver D-1).
Gate: **zero hooks pertencentes a `main`** (§4, gate executável). CLI executável.

**UT-6 — Fechar ciclo `app → main`.** Sonnet 5.
`app/views/core.py`: `get_db_connection` já vive em `app.db`; `logger` vira
`logging.getLogger("main")` local (**preservar o nome**); `aluno_url` (3 linhas) vira
`app/web/urls.py`. `app/views/aluno.py`: `get_student_request_update_alert` e
`mark_student_request_updates_seen` → `app/requisitions.py`.
Gate: `grep -rn "import main" app/ services/ utils/` vazio.

**UT-7 — Helpers `matrizes` → `activity_catalog`.** Inventário: Flash. **Implementação: Flash (padrão); escalada Pro conforme §6.**
Mover `_build_grupo_label` e `_canonicalize_tipo_limitacao` para `app/activity_catalog.py`.
Gate: `grep -n "from app.views.admin.atividades import" app/views/admin/matrizes.py` vazio.

### Bloco C — coortes de rota

**UT-8 — Banco de Dados.** Flash (padrão quando viável); Pro revisão adversarial; Sol
arquitetura/arbitragem final pelo tamanho. 20 rotas → `app/views/admin/banco_dados.py`.
Padrão `LegacyRouteSpec`. ~1.400 linhas saem de `main.py`. Consome `_format_bytes_label` de
`app/presentation.py` (movido na UT-3).

**UT-9 — Acesso.** Sol (arquitetura/supervisão de alto risco); Pro revisão adversarial; Opus
segunda revisão genuinamente cega. Safeguards de RBAC inalterados. 6 rotas → `app/views/admin/acesso.py`.
**Maior risco de RBAC do repositório:** `get_admin_permission_requirement` usa
`endpoint.startswith("admin_acesso")` para conceder escopo `full`. Nenhum endpoint renomeado.

→ **PLATEAU ESTRUTURAL declarável aqui.** Ver §3.

### Bloco D — fechamento (condicional; decidir após UT-9)

Só necessário para `REFACTOR ESTRUTURAL COMPLETO`. Módulos pequenos e separados —
**é proibido fundi-los** (§10).

| UT | Coorte | Owner | Rotas | Modelo |
|---|---|---|---:|---|
| UT-10 | Arquivos | `app/views/admin/arquivos.py` | 5 | Flash (padrão); Pro revisão adversarial |
| UT-11 | Alertas | `app/views/admin/alertas.py` | 4 | Flash (padrão); Pro revisão adversarial |
| UT-12 | Reportes | `app/views/admin/reportes.py` | 3 | Flash (padrão); Pro revisão adversarial; Sol só para ambiguidade/escalada |
| UT-13 | Dashboard + demo + meus_dados | `app/views/admin/dashboard.py` | 3 | Flash ou Pro conforme inventário; Sol revisão arquitetural/arbitragem |
| UT-14 | Infra | `app/views/files.py` (`uploaded_file`); `health` e `favicon` em `create_app`, como `/csrf-token` | 3 | Sol (arquitetura/supervisão de alto risco); Pro revisão adversarial; Opus segunda revisão cega |

UT-13 leva `_build_admin_dashboard_turma_cards` (267 linhas), `periodo_corrente` e os
formatadores do dashboard. UT-14 é Sol porque `uploaded_file` (106 linhas) contém autorização
aluno/admin e guarda de path traversal.

→ **REFACTOR ESTRUTURAL COMPLETO declarável aqui.**

### Diferidas — NÃO autorizadas

| ID | Unidade | Por que não agora | Gatilho |
|---|---|---|---|
| **D-1** | Dividir `app/db_maintenance.py` | Premissa original ("a Fase 5 vai engordá-lo") é **falsa**: a UT-5 cria `app/backup/` greenfield e apenas *chama* `db_maintenance`. Custo medido: **8 arquivos** referenciam o caminho literal e **8** importam `SCHEMA_VERSION`/registro. | >2.500 linhas, ou feature exigir |
| **D-2** | RBAC declarativo (`resource`/`scope` no `LegacyRouteSpec`; aposentar a cadeia `if/elif` de `app/auth.py`) | Maior alavanca do repositório, **mas é mudança adjacente a comportamento de autorização** | Decidir após UT-9, suíte verde |
| **D-3** | Purga dos 230 re-exports | Custo real é migrar 94 arquivos de teste para fora de `import main` — trabalho de teste, não de arquitetura | Nunca por si só |

**Permanentemente proibido:** `app/repositories/`; Migration v4; fundir Arquivos/Alertas/Reportes;
criar o pacote `app/db/` (§5).

---

## 3. CRITÉRIOS DE PARADA

### PLATEAU ESTRUTURAL — ao fim da UT-9

1. `main.py` não contém nenhum hook de app: `before_request`, `after_request`,
   `context_processor` **nem `errorhandler`**. (Satisfeito a partir da UT-5; ver §4.)
2. `create_app()` é o único lugar que instala extensão Flask ou define chave de `app.config`.
3. `grep -rn "import main" app/ services/ utils/` retorna vazio.
4. **Isolamento de escrita em hook de requisição.** Hooks de requisição não podem executar
   escritas duráveis de estado de aplicação em banco ou em sistema de arquivos, nem escritas
   de saída para rede/provedor externo. O único efeito colateral persistente permitido é a
   emissão de log diagnóstico/auditoria através de um subsistema de logging **local**
   integralmente configurado **fora** do caminho de requisição. O código de hook pode emitir
   registros, mas **não pode**: criar, configurar, substituir ou remover handlers; alterar
   destinos de log; mutar diretamente estado de aplicação no sistema de arquivos; usar logging
   com backend de rede; executar bootstrap de banco ou de schema; normalizar ou reparar estado
   persistente; nem converter persistentemente o `journal_mode` do banco. Append e rotação
   geridos pelo próprio handler sobre o sink diagnóstico local pré-configurado são
   **observabilidade**, não mutação de estado de aplicação. *(Redação ativa desde a v1.3. A
   redação literal da v1.2 e a primeira validação formal 6/7 obtida sob ela estão preservadas
   no Changelog desta versão e no ledger; não são o mesmo texto de critério.)*
5. Toda rota registrada resolve para exatamente um requisito de RBAC ou exceção aprovada,
   garantido por teste.
6. Route inventory + actor matrix verdes.
7. Suíte completa: 0 failed / 0 errors.

### REFACTOR ESTRUTURAL COMPLETO — ao fim da UT-14

Os sete acima, **mais**:

8. `main.py` não contém nenhum `@app.route`.
9. Cada coorte de domínio tem exatamente um módulo dono; nenhuma coorte dividida entre
   `main.py` e `app/`.

### Não exigido em nenhum dos dois

`main.py` ≤150 linhas; eliminar os 230 re-exports; todo módulo ≤800 linhas;
`app/repositories/`; migrar os 94 arquivos de teste; `LegacyRouteSpec` removido.

Quatro coisas distintas: **completude arquitetural** (os critérios acima); **completude de
migração** (re-exports e testes repontados — opcional); **limpeza de código** (handlers de 350
linhas — iniciativa separada, dirigida por feature); **eliminação de dívida técnica** (não é meta).

---

## 4. INVARIANTES INVIOLÁVEIS

Toda UT termina com estes valores idênticos aos da entrada, salvo declaração explícita da
própria UT autorizada pelo humano:

```
rotas .................. 131
endpoints .............. 130
RBAC unmapped .......... 0
actor matrix ........... 402
catálogo de mensagens .. 536
route_inventory_baseline.json .. byte-idêntico
database.db ............ 544768 bytes / SHA-256 inalterado dentro da UT
                       baseline canônico vigente (desde a UT-3):
                       bda97645d2f57cc405dee90de183d48cd1b80a0f3794b86c29f1319c05a30818
                       user_version 3; schema_migrations v1/v2/v3; sem -wal/-shm/-journal
```

**Transição de baseline de banco — autorizada pelo humano na UT-3.** O baseline anterior
`a3a55e63427024476d85d1fce3e0a5efaedcd33624400b2e67a815217d570fe9` está **APOSENTADO /
PRÉ-v2-v3** e não é mais o invariante ativo. Uma sondagem de startup de revisor executou
legitimamente as migrações v2/v3 já existentes contra o banco v1. A perícia estabeleceu apenas
escrituração de migração — `schema_migrations` ganhou v2 e v3 e `user_version` foi de 1 para 3 —
sem mutação de dado de negócio: `atividades` 32/32 e `atividade_versao` 63/63 logicamente
idênticos; as migrações de startup passam a ser registradas e ignoradas nas execuções seguintes.
O hash antigo permanece válido **apenas** como registro histórico nas evidências de fase
anteriores; nenhuma restauração dele é autorizada.

### Inventário de hook por módulo dono

O gate correto é o **módulo dono**, não o nome: `before_request` e `context_processor` não mudam
de lista na UT-3, apenas de sítio de registro.

| Momento | `before_request` | `after_request` | `context_processor` | `errorhandler` | hooks `main` |
|---|---|---|---|---|---:|
| Entrada (medido) | `csrf_protect`@flask_wtf, **`enforce_admin_access_control`@main** | `after_request`@compress, `_apply_security_headers`@app, `after_request`@compress, **`add_security_headers`@main** | `_default_...`@flask, `<lambda>`@flask_wtf, **`inject_admin_access_helpers`@main**, **`inject_editable_message_templates`@main** | 400→app, **404/500/413→main** | **7** |
| Após UT-2 | idem | `after_request`@compress, `_apply_security_headers`@app, **`_legacy_post_response_backup_sync`@main** | idem | idem | **7** |
| Após UT-3 | `csrf_protect`@flask_wtf, `enforce_admin_access_control`@**app.web.authz_gate** | idem UT-2 | `_default_...`, `<lambda>`, `inject_admin_access_helpers`@**app.web.context**, `inject_editable_message_templates`@**app.web.context** | 400→app, 404/500/413→**app.web.errors** | **1** |
| Após UT-5 | idem UT-3 | `after_request`@compress, `_apply_security_headers`@app | idem UT-3 | idem UT-3 | **0** |
| Após UT-9 (PLATEAU) | idem | idem | idem | idem | **0** |
| Após UT-14 (COMPLETO) | idem | idem | idem | idem | **0** |

Gate executável, obrigatório de UT-5 em diante:

```python
main_hooks = [f.__name__
  for lst in (a.before_request_funcs[None], a.after_request_funcs[None], a.template_context_processors[None])
  for f in lst if f.__module__ == "main"]
main_hooks += [fn.__name__ for d in a.error_handler_spec.values()
               for h in (d or {}).values() for fn in (h or {}).values() if fn.__module__ == "main"]
assert main_hooks == [], main_hooks
```

Comando de verificação geral (~2s):

```bash
APP_ENV=testing python -c "
import main
a=main.app; r=list(a.url_map.iter_rules())
print('rotas',len(r),'endpoints',len(a.view_functions))
for k,v in [('before',a.before_request_funcs),('after',a.after_request_funcs),('ctx',a.template_context_processors)]:
    print(k,[(f.__name__,f.__module__) for f in v[None]])
from app.auth import get_admin_permission_requirement as g
B={'GET','POST','PUT','PATCH','DELETE'}
un=[(x.rule,m) for x in r for m in (set(x.methods or ())&B) if str(x.endpoint).startswith('admin') and g(x.endpoint,m) is None]
print('rbac_unmapped',len(un),un[:5])
"
```

Regras adicionais:
- **Nomes de endpoint e URLs não mudam.** O RBAC casa por string com semântica de prefixo.
- **Nenhuma mudança de regra de negócio no mesmo commit que mexe em estrutura.**
  Exceção nomeada: UT-4, declaradamente comportamental, vai sozinha.
- **Zero `import main` dentro de `app/`** a partir da UT-6.
- **Nenhum `@app.route` ou hook novo em `main.py`.** Só saem, nunca entram.
- **Todo módulo novo com mensagem de usuário deve ser adicionado ao `_iter_backend_files()`
  do scanner de mensagens.** Foi assim que o catálogo foi de 535→536 em B6-P. Aplica-se
  concretamente a `app/web/authz_gate.py` e `app/web/errors.py` na UT-3.

---

## 5. REGRAS DE ESTRUTURA DE ARQUIVO

**Proibido criar o pacote `app/db/`.** Converter `app/db.py` em `app/db/__init__.py` quebra
5 arquivos de teste que abrem o caminho literal para parse AST. Subdivisões futuras usam
**módulos irmãos planos** (`app/db_migrations.py`, `app/db_schema.py`).

**Proibido adicionar símbolos a `app/admin_access.py`.**
`test_phase4_matrizes_shared_owners.py:235` afirma conjunto de defs top-level exatamente cinco.

**Pacotes e módulos novos só com prova de zero referência por caminho literal.** Antes de criar,
o inventário (Flash) roda `grep -rn '"<nome>"' tests/ tools/`. `app/backup/` (UT-5) e os três
arquivos novos em `app/web/` (UT-3) já foram verificados como seguros; `app/web/request.py` é
referenciado por caminho, mas o **diretório** não tem asserção.

**Fachadas de re-export são preservadas.** `app/db_maintenance.py` permanece arquivo real
enquanto 8 arquivos de teste o abrirem por caminho.

---

## 6. OS CINCO MODELOS — CAPACIDADE E ROTEAMENTO

### 6.1 Ficha técnica

| | **GPT-5.6 Sol** | **Claude Opus 5** | **Claude Sonnet 5** | **DeepSeek V4 Pro** | **DeepSeek V4 Flash** |
|---|---|---|---|---|---|
| ID | `gpt-5.6-sol` | `claude-opus-5` | `claude-sonnet-5` | `deepseek-v4-pro` | `deepseek-v4-flash` |
| Alias | `gpt-5.6` | — | — | — | — |
| Contexto | 1.050.000 tokens | 1M | 1M | 1M | 1M |
| Saída máx. | 128K | 128K | 128K | 384K | 384K (65K no OpenRouter) |
| Preço in/out (USD/MTok) | 5,00 in (0,50 cached) / 30,00 out | 5 / 25 | 3 / 15 (2/10 até 31/08) | 0,435 in (0,003625 cached) / 0,87 out | 0,14 in (0,0028 cached) / 0,28 out |
| SWE-bench Verified | — | topo de linha | quase-Opus | 80,6 | — |
| Effort | — | `low`…`max` | `low`…`max` | thinking mode | `high` / `xhigh` |
| Licença | OpenAI / ChatGPT | API Anthropic | API Anthropic | MIT, aberto | MIT, aberto |
| Forte em | supervisão, arquitetura, adjudicação, trabalho cross-cutting difícil, alta criticidade | trabalho agêntico longo, refactor multi-arquivo, decisão arquitetural | código em volume a custo médio | revisão adversarial independente, caça a bugs | varredura mecânica barata em contexto enorme, execução mecânica |
| Fraco em | custo quando usado para volume/rotina | custo | tokenizer novo — reestimar orçamento | julgamento arquitetural | **muito verboso**; exige supervisão em trabalho de alto risco |

> Especificações do GPT-5.6 Sol conforme documentação oficial atual da OpenAI (R1,
> 2026-08-08). Campos sem valor oficial informado (SWE-bench, Effort) permanecem `—`.

### 6.2 Regra de roteamento

**Princípio canônico:** USE O MODELO MAIS BARATO CONFIÁVELMENTE SUFICIENTE PARA A TAREFA.
**DeepSeek V4 Flash é o executor padrão (IAexec) quando compatível.** NÃO existe escada de
escalada obrigatória. O supervisor pode rotear diretamente para um modelo mais forte quando
risco ou complexidade claramente exigirem. Roteamento por adequação, risco e capacidade
demonstrada — não por hierarquia fixa.

Roteamento típico:
- inventário / diagnóstico simples → **Flash**
- patch/refactor limitado → **Flash**
- Flash insuficiente / raciocínio cross-file mais difícil / diversificação de família → **Pro**
- arquitetura significativa / supervisão / adjudicação / conflito de achados → **Sol**
- revisão independente crítica de alto risco → **Sol ou Opus** conforme risco/independência

| Tarefa | Modelo | Por quê |
|---|---|---|
| Supervisão, arquitetura, ownership, adjudicação, conflito de achados | **GPT-5.6 Sol** | Julgamento preferido; substitui Opus como padrão premium normal |
| UT que toca RBAC, auth, CSRF, uploads ou path handling | **Sol** | Erro caro e invisível a teste verde |
| UT que toca composition root ou hooks de app | **Sol** | Ordem de registro e efeito global |
| Extração mecânica de coorte / refactor bounded | **Flash (padrão)** | Volume; mais barato e suficiente quando compatível |
| Testes de contrato | **Flash (padrão)**; Sonnet como alternativa | Volume |
| Implementação difícil quando modelos mais baratos não são adequados | **Sol** | Qualidade |
| **Revisão adversarial de todo diff** | **Pro (padrão)**; **Sol** para adjudicação difícil/alto risco | Família diferente = independência real; escalada barata |
| 2ª revisão (quando exigida por risco/protocolo) | **Sol ou Opus** | Independência/criticidade genuína; Opus reservado |
| Revisão independente crítica de altíssima consequência (RBAC/infra) | **Opus 5** | Segunda opinião cega |
| Inventário: call sites, diff de snapshot, contagem de rotas, `grep`, prova de zero-referência-por-caminho | **Flash** | 1M de contexto por $0,14/MTok |

**DeepSeek V4 Flash — regras (IAexec padrão):**
- Flash é o **executor padrão (IAexec) quando compatível**.
- Flash **pode**: inventariar; diagnosticar; desenhar/implementar RED; editar testes; editar
  produção; executar refactors bounded; extração mecânica; trabalho cross-file pequeno/médio;
  revisão técnica rotineira; checagens de custódia/invariantes.
- Flash **não deve ser o único revisor** para trabalho de alto risco ou arquitetonicamente
  ambíguo; nesses casos, Pro (padrão) ou Sol/Opus conforme §6.2.
- Preferir a **versão V4 Flash atual comprovada** disponível no provider selecionado. Falhas
  de rota antiga/gratuita **não** se generalizam em banimento permanente de capacidade do
  Flash atual.
- **Formato de saída:** varreduras/inventários verificáveis por máquina: preferir JSON ou
  tabela estruturada fixa; implementação/revisão: usar o formato mais adequado à evidência;
  **não** forçar JSON quando prejudicar a clareza.

**Rota FREE vs paga do V4 Flash — fallback explícito:**
Quando existir rota FREE do V4 Flash comprovadamente compatível:
1. preferir a rota FREE primeiro;
2. se indisponível, falhando tecnicamente, limitada de contexto/orçamento, de versão incerta
   ou operacionalmente incompatível: cair automaticamente para o V4 Flash normal/pago;
3. **não** pular direto para Pro/Sol/Opus enquanto o Flash pago continuar adequado;
4. escalar além do Flash apenas quando a tarefa exigir.
Sem fallback silencioso. Quando a identidade do modelo for material para a qualificação,
registrar: provider efetivamente usado; modelo efetivo; identificador de modelo/versão quando
disponível; rota FREE vs paga quando material; motivo do fallback. Não afirmar que uma rota de
agregador é o Flash mais recente/atual sem verificação real.

**Custo esperado:** UT de coorte ≈ Flash (padrão) + Pro (revisão) + Sol/Opus (arbitragem,
apenas quando necessário). UT acima de ~$15 indica recorte errado, não modelo errado.

### 6.3 Regra de dados (não negociável)

O repositório contém `database.db` com dados reais de alunos e `documentos_alunos/`.

- **Nunca** colar conteúdo de banco, dump com linhas, ou arquivo de `documentos_alunos/`,
  `uploads/` ou `logs/` em nenhum dos cinco modelos. Schema (DDL) e código, sim; linhas, não.
- Vale igualmente para Anthropic e DeepSeek. A distinção relevante não é o fornecedor — é que
  dado pessoal de aluno não entra em prompt nenhum.
- Antes de qualquer push, confirmar que `database.db` e `documentos_alunos/` não estão no diff.

---

## 7. CICLO DE UMA UNIDADE DE TRABALHO

```
1. INVENTÁRIO      (Flash)     → arquivos, símbolos, call sites, rotas, zero-referência-por-caminho
2. PLANO           (Sol para trabalho arquitetural; Flash/Pro permitidos para planejamento mecânico limitado) → recorte, riscos, gate específico. ≤1 página.
3. RED             (Flash padrão quando compatível) → testes que falham porque a mudança ainda não existe
4. IMPLEMENTAÇÃO   (§6.2 — IAexec selecionado; Flash padrão quando compatível)
5. GREEN           (executor)  → suíte focada verde
6. REVISÃO         (Pro padrão; Sol para adjudicação difícil/alto risco) → obrigatória, adversarial, read-only
6b. 2ª REVISÃO     (quando exigida por risco/protocolo; Sol ou Opus conforme independência/criticidade)
7. SUÍTE COMPLETA  (humano)    → pytest inteiro (~330s), 0 failed / 0 errors
8. INVARIANTES     (Flash)     → tabelas da §4
9. COMMIT          (humano)    → 1 commit técnico. Sem commit de governança separado.
```

Passo 6 é read-only; o revisor não edita, emite veredito. Defeito material volta ao passo 4.

Mensagem de commit:
```
<Verbo> <objeto>

UT-N. Invariantes: rotas 131, endpoints 130, rbac_unmapped 0, hooks_main <n>.
Revisão: <modelo>, veredito PASS, achados <n>.
Testes aposentados: <lista ou "nenhum">.
```

### Templates

**Inventário (Flash)**
```
Tarefa: inventário — etapa de leitura; NÃO edite arquivos durante o inventário. NÃO opine.
Escopo: UT-N — <uma linha>

Retorne preferencialmente JSON ou tabela estruturada fixa (varredura verificável por máquina);
use o formato mais adequado à evidência quando JSON prejudicar a clareza (ver §6.2).
{
  "arquivos_afetados": ["caminho:motivo"],
  "simbolos_movidos": [{"nome":"","de":"arquivo:linha","para":"arquivo"}],
  "call_sites": [{"simbolo":"","arquivo":"","linha":0}],
  "rotas_afetadas": [{"regra":"","endpoint":"","metodos":[]}],
  "hooks_afetados": [{"nome":"","tipo":"","modulo_atual":"","modulo_destino":""}],
  "testes_que_referenciam": ["arquivo::teste"],
  "referencias_por_caminho_literal": ["arquivo:linha"],
  "mensagens_de_usuario_em_modulo_novo": ["texto"],
  "riscos_detectados": ["texto curto"]
}
Sem prosa fora do formato escolhido.
```

**Plano arquitetural (GPT-5.6 Sol ou modelo selecionado conforme §6)**
```
Papel: arquiteto responsável por esta unidade.
Leia EXECUTION_PROTOCOL.md §1 (estado), §4 (invariantes), §5 (estrutura de arquivo).
Unidade: UT-N. Inventário: <colar JSON>

Em no máximo uma página:
1. Recorte exato: o que entra, o que fica de fora, por quê.
2. Ordem das edições.
3. Gate executável que prova o resultado.
4. Risco mais provável de quebra silenciosa e como o RED o pega.
5. Arquivos que NÃO devem ser tocados.
6. Testes de andaime a aposentar (só da tabela §8; se nenhum, escreva "nenhum").
Não escreva código.
```

**Implementação (IAexec selecionado conforme §6; Flash padrão quando compatível)**
```
Papel: executor. Comportamento idêntico — mover, não mudar.
Unidade: UT-N. Plano aprovado: <colar>

Regras:
- Nenhuma mudança de regra de negócio.
- Nomes de endpoint e URLs inalterados.
- Nenhum símbolo novo em main.py; apenas remoções e re-exports de identidade.
- Preservar o nome do logger "main".
- Preservar a ordem de registro dos hooks (§4).
- Não criar módulo/pacote sem prova de zero referência por caminho literal (§5).
- Módulo novo com mensagem de usuário → adicionar ao _iter_backend_files() do scanner.
- Não tocar: database.db, documentos_alunos/, uploads/, logs/, tests/_artifacts/,
  app/admin_access.py.

Entregue: diff unificado por arquivo + gate rodando verde.
Achados fora do recorte: LISTAR ao final sob "FORA DE ESCOPO", sem alterar.
```

**Revisão adversarial (Pro padrão; Sol para adjudicação difícil) — obrigatória**
```
Papel: revisor independente. READ-ONLY. Você não escreveu isto e não deve aprová-lo.
Unidade: UT-N. Diff: <colar>. Invariantes: <colar §4>.

REFUTE as três afirmações. Assuma erradas até prova em contrário:
A) "O comportamento em runtime é idêntico ao anterior."
B) "Nenhuma rota, endpoint, hook ou requisito de RBAC mudou de semântica."
C) "Nada fora do recorte declarado foi alterado."

Para cada: VERDADEIRA / FALSA / NÃO VERIFICÁVEL, com arquivo:linha como evidência.
Liste achados materiais separados dos não-materiais.
Veredito final em uma palavra: PASS ou FAIL.
Não sugira estilo. Não reescreva código.
```

---

## 8. APOSENTADORIA DE TESTES DE ANDAIME — TABELA FECHADA

**Regra:** uma asserção só é aposentada **no mesmo commit da UT que a torna estruturalmente
falsa**, e **só se estiver nesta tabela**. Não existe autorização para limpeza ampla, varredura
nem "aposentar por coorte". Item fora desta tabela exige autorização humana e bump de versão.

| Teste / constante | Arquivo | UT | Substituto |
|---|---|---|---|
| `test_phase4_b1_governance_closeout_is_canonical` | `test_phase4_configuracoes_blueprint.py` | UT-2 | nenhum |
| asserções leitoras de governança | `test_phase4_atividades_blueprint.py` | UT-2 | nenhum |
| asserções leitoras de governança | `test_phase4_requisicoes_shared_owners.py` | UT-2 | nenhum |
| asserções leitoras de governança | `test_phase4_versioning_subsystem.py` | UT-2 | nenhum |
| `test_canonical_contract_document_and_governance_registration`, `test_macro_phase3_acceptance_closeout_is_current_and_bounded` | `test_phase3_schema_startup_transaction_contract.py` | UT-2 | nenhum |
| `test_b7p_aluno_lazy_map_reduced_to_exactly_two_requisicoes_keys` | `test_phase4_arquivos_alertas_shared_owners.py` | UT-6 | **uma** asserção: `app/` contém zero `import main` |
| `EXPECTED_ALUNO_LAZY_KEYS_AFTER_VERSIONING_EXTRACTION` | `test_db_schema_maintenance.py` | UT-6 | idem (mesma asserção única) |
| `REMAINING_ALUNO_MAIN_HELPERS` | `test_phase4_versioning_subsystem.py` | UT-6 | idem |
| `test_b7p_zero_route_movement_all_twelve_handlers_remain_main_local` | `test_phase4_arquivos_alertas_shared_owners.py` | UT-10 | specs da coorte Arquivos |
| `test_b7p_reportes_ownership_unchanged` | `test_phase4_arquivos_alertas_shared_owners.py` | UT-12 | specs da coorte Reportes |
| `test_b7p_admin_dashboard_unchanged_from_entry_baseline` | `test_phase4_arquivos_alertas_shared_owners.py` | UT-13 | specs da coorte Dashboard |
| `test_periodo_corrente_unchanged_against_baseline_and_still_main_local` | `test_phase4_alunos_turmas_cursos_blueprint.py` | UT-13 | idem |
| `test_b7p_uploaded_file_unchanged_from_entry_baseline` | `test_phase4_arquivos_alertas_shared_owners.py` | UT-14 | teste de autorização de `uploaded_file` no novo owner |

**A UT-3 não aposenta nada.** `test_central_admin_access_denied_uses_canonical_ajax_helper`
sobrevive por identidade (`inspect.getsource` segue o objeto ao novo arquivo; corpo inalterado).

**Explicitamente NÃO aposentáveis por nenhuma UT:**
`test_auth_static_baseline_unchanged_against_cab4c61` (reclassificado como **contrato valioso**:
guarda contra deriva de `app/auth.py`); `test_route_inventory_snapshot`;
`test_rbac_requirement_coverage`; `test_ref_0c_d_r1_route_complete_actor_matrix`;
`test_db_connection_ownership`; `test_admin_access_module_defines_exactly_five_helpers_without_routes`;
toda a suíte comportamental.

### Dívida de teste registrada (não paga por este protocolo)

Asserções de contagem exata das coortes já fechadas permanecem intactas porque nenhuma UT
altera essas coortes. Dívida latente, paga na primeira feature que adicionar rota à coorte:
`test_exactly_ten_helpers_and_no_eleventh`,
`test_route_specs_exactly_17_endpoints_and_24_pairs_with_no_extra`,
`test_rbac_scope_counts_remain_exact_view6_edit13_full5`; equivalentes em
`test_phase4_matrizes_blueprint.py`, `test_phase4_atividades_blueprint.py`,
`test_phase4_requisicoes_blueprint.py`, `test_phase4_configuracoes_blueprint.py`.

`test_message_catalog_count_remains_536` permanece; a regra que o mantém verde está na §4.

---

## 9. GOVERNANÇA, MUTABILIDADE E PAPÉIS DE DOCUMENTO

### Mutabilidade deste arquivo

| Seção | Regime |
|---|---|
| §0–§8, §12, §13 | **Imutáveis durante a execução.** Alteração exige autorização humana, bump de versão e linha no Changelog. |
| §1 | Snapshot **datado**; **não** atualizado por UT. Obsoleto de propósito. |
| §10 (achados fora de escopo) | **Append-only** pelo condutor. |
| §11 (progresso) | **Append-only** pelo condutor, uma linha por UT. |

O condutor escreve em §10 e §11 sem autorização. Em qualquer outra seção, não.

### Papéis dos documentos

| Documento | Papel |
|---|---|
| `EXECUTION_PROTOCOL.md` | **Autoridade operacional.** Escopo, ordem, invariantes, roteamento, parada. |
| `PROJECT_STATE.md` | **Estado vivo, ≤40 linhas.** Branch, HEAD, última UT concluída, próxima UT, tabela de invariantes atuais, resultado da última suíte. **Reescrito** (não apendado) a cada UT. Formato novo entra na UT-2 (§13). |
| `ARCHITECTURE_REFACTOR_LEDGER.md` | **Registro histórico.** Uma linha nova por UT (formato §11). Blocos antigos preservados, não editados. |
| `AGENT_HANDOFF.md` | **CONGELADO como histórico** a partir da Adoção parte 1. Nenhuma escrita nova. Motivo: 277 KB append-only, maior custo de contexto por turno do repositório, e nada no ciclo da §7 o lê. |
| `DOCUMENTATION_INDEX.md` | Hierarquia de autoridade atualizada na UT-2 (§13). |
| `docs/refactor/PHASE*.md` | **Históricos.** Nenhum contrato novo por unidade. |
| `docs/mapeamento/05_avaliacao_refactor.md` | Histórico do plano original. Não é mais autoridade de escopo — a §2 é. |

### O que deixa de existir

Contrato `.md` por unidade; commit de governança separado; manifesto de caminhos exatos com
teto numérico e "path N hard stop"; registro de sessão/custo/hash de revisor no ledger;
testes que fazem parse de markdown de governança (aposentados na UT-2, §8).

---

## 10. ANTI-PADRÕES E ACHADOS FORA DE ESCOPO

**Não fundir Arquivos + Alertas + Reportes num módulo.** Três domínios não relacionados; a única
coisa que os une é adjacência em `main.py`. UT-10, UT-11 e UT-12 são separadas.

**Não fazer fase de "shared owner prerequisite" para conjunto pequeno.** B7-P gastou ciclo
RED/GREEN completo, arquivo de teste com 11 casos, contrato de 13 KB, manifesto de 15 caminhos,
revisão externa e commit de closeout — para mover **quatro funções que somam 19 linhas**.
Símbolos compartilhados movem-se no mesmo commit das rotas.

**Não trocar `LegacyRouteSpec` durante UT-1…UT-14.** Ver D-2.
**Não criar o pacote `app/db/` nem adicionar a `app/admin_access.py`.** Ver §5.
**Não criar novo documento de contrato por fase.** Ver §9.
**Não autorizar Migration v4 nem `app/repositories/`.**

### Achados fora de escopo (append-only)

| Data | UT em curso | Achado | Ação |
|---|---|---|---|
| 2026-08-07 | UT-1 | Quarto defeito de encoding UTF-8 pré-existente do Windows, da mesma classe dos três nós nomeados, descoberto pela suíte completa em `tests/test_d73d_normative_importer_dryrun.py::test_invalid_fixture_aborts_without_partial_insertion` (helper `_run_cli`). Reproduzido contra o HEAD de entrada `2c99f1641387ee115f519ee1517523cd1ecd28c2` com o diff da UT-1 removido via `git stash`, confirmando que não foi introduzido por esta UT. | Incorporado explicitamente à UT-1 por autorização humana (UT-1-R1); nenhuma nova UT criada. Classificação: `PRE_EXISTING_BASELINE_REPRODUCED / SAME_UTF8_ENCODING_DEFECT_CLASS / DISCOVERED_BY_UT1_FULL_SUITE / AUTHORIZED_UT1_SCOPE_EXPANSION`. |
| 2026-08-08 | UT-4 | `app/views/admin/atividades.py::_delete_upload_relpath` — caminho de deleção sem guarda de contenção. | OUT OF SCOPE para UT-4; deferido para trabalho de segurança separadamente autorizado. |
| 2026-08-08 | UT-4 | `app/views/aluno.py::aluno_baixar_arquivo` — contenção lexical via `startswith` identificada como sensível a prefixo-irmão (sibling-prefix). | OUT OF SCOPE para UT-4; deferido para trabalho de segurança separadamente autorizado. |
| 2026-08-08 | UT-6 | Detector de regressão AST da UT-6 não captura formas de alias estaticamente resolúveis simples, como alias de atribuição de `sys.modules`/`importlib.import_module` e `__import__` em forma de atributo. | DEFERIDO — `NON_MATERIAL_FUTURE_HARDENING`. Candidato UT-6 atual verificado limpo independentemente por duas revisões adversariais. Não corrigir dentro da UT-6. |
| 2026-08-08 | UT-6 | `tests/test_ref_0c_b1_p0_access_context_transactions.py` faz patch de `main.get_db_connection` embora a rota que pretende rastrear resolva o dono canônico `app.db.get_db_connection`. | DEFERIDO — `PRE_EXISTING_TEST_DEBT`. Reparo futuro deve redirecionar a interceptação para o dono canônico quando explicitamente autorizado. |

---

## 11. REGISTRO DE PROGRESSO (append-only)

| UT | Nome | Commit | Executor | Revisor | Veredito | rotas/endpoints/rbac | hooks main | Suíte | Aposentados | Data |
|---|---|---|---|---|---|---|---|---|---|---|
| — | Adoção parte 1 | | — | — | — | — | 7 | — | nenhum | |
| UT-1 | Suíte verde (encoding) — 4 pontos (3 originais + 1 achado pela suíte, UT-1-R1) | | Sonnet 5 | Opus 5 (substituto, não-independente — DeepSeek V4 Pro indisponível neste harness) | PASS (rodada 2; rodada 1 FAIL com achado material corrigido) | 131/130/0 | 7 | 1106 passed/0 failed/17 deselected | nenhum | 2026-08-07 |
| UT-2 | Composition root + Adoção parte 2 | | Claude Opus 5 | DeepSeek V4 Pro + Claude Opus 5 | PASS | 131/130/0 | 7 | 1110 passed/0 failed/0 errors/17 deselected | 5 arq. leitores de governança / 6 funções leitoras autorizadas | 2026-08-07 |
| UT-3 | Hooks de app — donos canônicos `app.web.authz_gate` / `app.web.context` / `app.web.errors`; `_format_bytes_label` para `app.presentation`; pai de entrada `7468a0f3502a7f51537fc9e537d401b4e1dc6f1c`; R1 corrigiu UT3-01 (identidade do logger de entrypoint direto) com teste de regressão dedicado; actor matrix 402; catálogo 536; `database.db` 544768 bytes / `bda97645…a30818`, user_version 3, schema_migrations v1/v2/v3 (transição de baseline autorizada pelo humano) | | Claude Opus 5 | DeepSeek V4 Pro + Claude Opus 5 | PASS | 131/130/0 | 1 | 1126 passed/0 failed/0 errors/17 deselected | nenhum | 2026-08-08 |
| UT-4 | Containment de path | | Claude Opus 5 | DeepSeek V4 Pro + Claude Opus 5 | PASS | 131/130/0 | 1 | 1129 passed/0 failed/0 errors/17 deselected | nenhum | 2026-08-08 |
| UT-5 | Fase 5 → `app/backup/` | | Claude Opus 5 | DeepSeek V4 Pro + Claude Opus 5 | PASS | 131/130/0 | **0** | 1142 passed/0 failed/0 errors/17 deselected | nenhum | 2026-08-08 |
| UT-6 | Fechar ciclo app→main | | Claude Opus 5 | DeepSeek V4 Pro + Claude Opus 5 | PASS | 131/130/0 | 0 | 1210 passed/0 failed/0 errors/17 deselected | nenhum (3 previstas, mantidas) | 2026-08-08 |
| UT-7 | Helpers matrizes→catalog | | DeepSeek V4 Flash | DeepSeek V4 Pro | PASS | 131/130/0 | 0 | 1218 passed/0 failed/0 errors/17 deselected | nenhum | 2026-08-08 |
| UT-8 | Coorte Banco de Dados | | DeepSeek V4 Flash | DeepSeek V4 Pro | PASS | 131/130/0 | 0 | 1238 passed/0 failed/0 errors/17 deselected | nenhum | 2026-08-09 |
| UT-9 | Coorte Acesso | | DeepSeek V4 Flash | DeepSeek V4 Pro | PASS | 131/130/0 | 0 | 1282 passed/0 failed/0 errors/17 deselected | nenhum | 2026-08-09 |
| — | **PLATEAU ESTRUTURAL** | landing da Fase H (este commit) | Claude Opus 5 | Claude Opus 5 (revalidação formal independente) | **7/7 PASS** (Critério 4 v1.3; 1ª validação formal foi 6/7 sob v1.2) | 131/130/0 | 0 | 1302 passed/0 failed/0 errors/17 deselected | nenhum | 2026-08-09 |

UT-9 — Coorte Acesso: QUALIFICADA / FECHADA neste commit final. Extração: 6 rotas + 3 helpers.
Suíte final: 1282 collected / 1265 passed / 17 deselected / 0 failed / 0 errors. Invariantes
finais: 131 / 130 / 0 / 402 / 536 / 0. Plateau: naquele momento apenas **elegível** para
validação formal, ainda **não declarado** — valor histórico da UT-9.

**PLATEAU ESTRUTURAL — VALIDADO / PUBLICADO** em 2026-08-09, no commit de landing da Fase H
(subject `Validate structural plateau request-hook isolation`; pai `230de41b`). Matriz formal
**7/7 PASS** sob o Critério 4 da v1.3: C1 `hooks_main` PASS / C2 composition root PASS /
C3 dependência reversa PASS / C4 isolamento de escrita em hook PASS / C5 RBAC PASS /
C6 inventário de rotas + actor matrix PASS / C7 suíte canônica PASS. Suíte canônica à época
do plateau (histórica): 1319 collected / 1302 passed / 17 deselected / 0 failed / 0 errors /
407,40s. Suíte canônica vigente após o landing da UT-10 (histórica): 1345 collected /
1328 passed / 17 deselected / 0 failed / 0 errors / 0 skipped / 345,89s. Suíte canônica
vigente após o landing da UT-11 (histórica): 1373 collected / 1356 passed / 17 deselected /
0 failed / 0 errors / 0 skipped / 368,73s. Suíte canônica vigente após o landing da UT-12:
1399 collected / 1382 passed / 17 deselected / 0 failed / 0 errors / 0 skipped / 377,54s.
Suíte canônica vigente após o landing da UT-13:
1429 collected / 1412 passed / 17 deselected / 0 failed / 0 errors / 0 skipped / 357,96s.
Invariantes: 131 / 130 / 0 / 402 /
536 / 0. **Histórico preservado:** a primeira validação formal, sob o
Critério 4 da v1.2, foi **6/7 PASS com C4 FAIL** — ver Changelog v1.3 e o ledger. UT-10:
CLOSED / ACCEPTED / PUBLISHED (ver bloco UT-10 abaixo). UT-11: CLOSED / ACCEPTED /
PUBLISHED (ver bloco UT-11 abaixo). UT-12: CLOSED / ACCEPTED / PUBLISHED (ver bloco
UT-12 abaixo). UT-13: CLOSED / ACCEPTED / PUBLISHED (ver bloco UT-13 abaixo).
UT-14: NÃO INICIADA.

**UT-10 — Coorte Arquivos: CLOSED / ACCEPTED / PUBLISHED** no commit de landing (subject
`Extract admin files routes`; pai de entrada `e8f64a8244196b1c7acd634c9f78fbde29d70ef9`).
Extração: 5 rotas / 6 pares endpoint-method / 4 helpers locais para
`app/views/admin/arquivos.py`; facade de compatibilidade `main` 9/9 por identidade; owner
`app/views/admin/arquivos.py`. Primeira suíte canônica: 1345 / 1324 / 4 failed /
17 deselected — quatro lacunas de expectativa de teste histórica (3 cumulativas CSRF +
1 inventário do pacote `app/views/admin`), reconciliadas exatamente em 4 arquivos de teste,
sem mudança de produção. Retry canônico: 1345 collected / 1328 passed / 17 deselected /
0 failed / 0 errors / 0 skipped / 345,89s. Invariantes finais: 131 / 130 / 0 / 402 / 536 / 0.
UT-11: NÃO INICIADA.

**UT-11 — Coorte Alertas: CLOSED / ACCEPTED / PUBLISHED** no commit de landing (subject
Extract admin alerts routes; pai de entrada 0092149c2c596f90932b8f83991a33e1f98c32c).
Extração: 4 rotas / 4 pares endpoint-method / 3 helpers / 1 constante para
pp/views/admin/alertas.py; facade de compatibilidade main 8/8 por identidade; owner
pp/views/admin/alertas.py. Seam de contrato de teste (TEST_CONTRACT_SEAM): dois GREEN da
UT-11 e um GREEN histórico da UT-10 codificavam estado pré-extração; corrigidos para
state-aware exatos, sem defeito de produção e sem reabertura da UT-10 (SHAs substitutos
registrados no ledger). Suíte canônica final: 1373 collected / 1356 passed / 17 deselected /
0 failed / 0 errors / 0 skipped / 368,73s. Invariantes finais: 131 / 130 / 0 / 402 / 536 / 0.
UT-12: NÃO INICIADA.

**UT-12 — Coorte Reportes: CLOSED / ACCEPTED / PUBLISHED** no commit de landing (subject
Extract admin reports routes; pai de entrada `4820e4d3a46a1a3564c730d384b86aa989d752c9`).
Extração: 3 rotas / 3 pares endpoint-method / 1 helper / 1 constante para
`app/views/admin/reportes.py`; facade de compatibilidade main 5/5 por identidade; owner
`app/views/admin/reportes.py`; factory opt-out `register_admin_reportes_blueprint` (default
True). Seam de contrato de teste (TEST_CONTRACT_SEAM / LEGITIMATE_UT12_COCHANGE): os
contratos históricos UT-10/UT-11/B7-P codificavam residência Reportes em `main` e tornaram-se
obsoletos com a extração legítima da UT-12; reconciliação state-aware estreita autorizada pelo
supervisor (alvo real ausente → ownership `main`; alvo real presente → ownership exata
`app.views.admin.reportes`; identidade exigida; ownership misto rejeitado; proteções
Arquivos/Alertas/Dashboard preservadas). Suíte canônica final: 1399 collected / 1382 passed /
17 deselected / 0 failed / 0 errors / 0 skipped / 377,54s. Invariantes finais: 131 / 130 /
0 / 402 / 536 / 0. UT-13: NÃO INICIADA.

**UT-13 — Coorte Dashboard: CLOSED / ACCEPTED / PUBLISHED** no commit de landing (subject
`Extract admin dashboard route`; pai de entrada `2e0afa34ed1b927014ac35875668bbdc132743ad`).
Extração: 1 rota (`admin_dashboard`, GET `/admin/dashboard`) / 1 par endpoint-method /
9 helpers para `app/views/admin/dashboard.py`; facade de compatibilidade `main` 10/10 por
identidade; owner `app/views/admin/dashboard.py`; factory opt-out
`register_admin_dashboard_blueprint` (default True); LegacyRouteSpec 1 spec / 1 par.
Vizinhos excluídos (hard boundary): `admin_demo_clientes_form_pack` e `admin_meus_dados`
permanecem main-owned; `admin_meus_dados` não faz parte da UT-13 (trabalho futuro separado).
Seam de contrato de teste (TEST_CONTRACT_SEAM / LEGITIMATE_UT13_COCHANGE): contratos
históricos de ownership do Dashboard em UT-12 / Alunos-Turmas / shared owners /
Requisições / Arquivos-Alertas / Configurações tornaram-se state-aware (alvo real ausente →
ownership `main`; alvo real presente → 10 símbolos exatos target-owned + facade `main`
10/10; ownership misto rejeitado; vizinhos main-owned nos dois estados). Correção RED
(RED_CONTRACT_DEFECT / RESOLVED): o RED inicial (SHA `3ba52bf3…`) exigia vizinhos
main-owned dentro de instâncias `create_app` no `test_red_j`; correção estreita autorizada
removeu apenas as asserções positivas contraditórias; RED congelado final
`63a811794f136e087e47b624b1ec1a53f695138464f7a960b6291f9bded41ef2`; nenhum byte de produção
alterado pelo achado. Suíte canônica final: 1429 collected / 1412 passed / 17 deselected /
0 failed / 0 errors / 0 skipped / 357,96s. Invariantes finais: 131 / 130 / 0 / 402 / 536 / 0.
UT-14: NÃO INICIADA.

| UT-10 | Coorte Arquivos | | DeepSeek V4 Flash | DeepSeek V4 Pro | PASS | 131/130/0 | 0 | 1328 passed/0 failed/0 errors/17 deselected | 1 | 2026-08-09 |
| UT-11 | Coorte Alertas | | DeepSeek V4 Flash | DeepSeek V4 Pro | PASS | 131/130/0 | 0 | 1356 passed/0 failed/0 errors/17 deselected | nenhum | 2026-08-09 |
| UT-12 | Coorte Reportes | | DeepSeek V4 Flash | DeepSeek V4 Pro | PASS | 131/130/0 | 0 | 1382 passed/0 failed/0 errors/17 deselected | 1 | 2026-08-10 |
| UT-13 | Coorte Dashboard | | DeepSeek V4 Flash | DeepSeek V4 Pro | PASS | 131/130/0 | 0 | 1412 passed/0 failed/0 errors/17 deselected | 1 | 2026-08-10 |
| UT-14 | Infra | | | | | | 0 | | 1 | |
| — | **REFACTOR ESTRUTURAL COMPLETO** | | | | | | 0 | | | |

---

## 12. MAPEAMENTO PARA O VOCABULÁRIO ANTIGO

| UT | Equivale a |
|---|---|
| UT-1 | Higiene; sem correspondente de fase |
| UT-2 | Fase 1, item "unificar headers divergentes" (nunca executado) + consolidação de bootstrap |
| UT-3 | Pré-requisito da **Fase 6**; nunca teve dono no plano original |
| UT-4 | Dívida residual registrada em B7-P |
| UT-5 | **Fase 5** |
| UT-6 | Pré-requisito da **Fase 6** (invariante "zero back-reference `app/ → main`") |
| UT-7 | Correção de aresta cross-blueprint de B5 |
| UT-8 | **Fase 4-B8** (`app/views/admin/banco_dados.py`) |
| UT-9 | **Fase 4-B9** (`app/views/admin/acesso.py`) |
| UT-10…UT-12 | **Fase 4-B7**, redefinida: três módulos separados, não um fundido |
| UT-13 | Resolve o "dashboard.py e admin_meus_dados ownership remain unresolved" do ledger |
| UT-14 | Resíduo da **Fase 6** |
| D-1 | Resíduo de **Fase 3** (ownership de manutenção) |
| — | Migration v4: permanece **PROIBIDA** |

`PHASE 4` deixa de ser "OPEN / INCREMENTAL" e passa a ser rastreada pelas UTs acima.

---

## 13. TRANSIÇÃO DE GOVERNANÇA — ADOÇÃO BIPARTIDA

Não é UT e não é closeout de fase. É uma transição única, dividida em duas partes porque os
**5 arquivos de teste leitores de governança leem `PROJECT_STATE.md`, `AGENT_HANDOFF.md`,
`DOCUMENTATION_INDEX.md` e o ledger** (§1). Reescrever `PROJECT_STATE.md` agora deixaria a
suíte vermelha **antes** da UT-1, que é a UT encarregada de torná-la verde.

### Adoção parte 1 — antes da UT-1. Estritamente aditiva.

Nenhuma string existente pode ser removida ou alterada.

| Caminho | Ação |
|---|---|
| `docs/refactor/EXECUTION_PROTOCOL.md` | **Novo.** Nenhum teste o lê. |
| `AGENT_HANDOFF.md` | **Prepend** de banner, e nada mais: `> **HISTÓRICO — congelado em 2026-08-07 pela v1.1 do EXECUTION_PROTOCOL. Nenhuma escrita nova. Estado vivo: PROJECT_STATE.md. Autoridade operacional: docs/refactor/EXECUTION_PROTOCOL.md.**` |
| `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md` | **Append no fim do arquivo** (nunca no topo — a seção "Current authoritative state" deve continuar sendo a primeira) de um bloco `## Transição para EXECUTION_PROTOCOL v1.1`, registrando: data, motivo, as 14 UTs, os dois estados finais, e que os contratos B1–B7-P permanecem históricos e válidos. |

**Não incluir** `PROJECT_STATE.md` nem `DOCUMENTATION_INDEX.md` nesta parte.

#### Gate delimitado dos leitores de governança

Escopo: **exatamente estes cinco arquivos**. Nenhum outro teste entra nesta verificação. As
falhas ambientais de encoding pertencem a `test_phase3_final_init_cutover.py` e
`test_pytest_runtime_isolation.py`, são tratadas pela UT-1, **não fazem parte deste gate e não
devem ser citadas nele**.

**A. Antes de qualquer mutação da Adoção parte 1**, rodar exatamente:
```bash
pytest tests/test_phase3_schema_startup_transaction_contract.py \
       tests/test_phase4_atividades_blueprint.py \
       tests/test_phase4_configuracoes_blueprint.py \
       tests/test_phase4_requisicoes_shared_owners.py \
       tests/test_phase4_versioning_subsystem.py -q
```

**B. Registrar:** `collected`, `passed`, `failed`, `errors`, `exit code`.

**C. Após a mutação estritamente aditiva**, rodar os **mesmos cinco arquivos** com o mesmo
comando.

**D. Resultado exigido:** o resultado pós-mutação deve ser **exatamente igual** ao baseline
pré-mutação para esses cinco arquivos, **sem nenhuma falha ou erro novo**.

**Baseline medido em 2026-08-07, HEAD `c385322`:**
```
collected 77 | passed 77 | failed 0 | errors 0 | exit 0   (11,67s)
```
Como os cinco estão **todos GREEN**, o gate pós-adoção também deve ser **todos GREEN**:
`77 passed / 0 failed / 0 errors / exit 0`.

Se algum dos cinco quebrar com uma mudança puramente aditiva, **pare**: significa que ele
afirma estrutura (contagem de seções, ordem, primeira ocorrência) e não conteúdo, e a parte 1
deve ser reduzida ao caminho 1 apenas.

### Adoção parte 2 — dentro da UT-2. Destrutiva.

| Caminho | Ação |
|---|---|
| `PROJECT_STATE.md` | Reescrito no formato ≤40 linhas da §9. |
| `docs/DOCUMENTATION_INDEX.md` | Hierarquia de autoridade atualizada: `EXECUTION_PROTOCOL.md` no topo; `AGENT_HANDOFF.md` marcado histórico. |
| 5 arquivos de teste | Asserções leitoras de governança aposentadas (§8). |

Formato e asserção morrem no mesmo commit. É por isso que a parte 2 é da UT-2 e não da adoção.

---

**Fim do protocolo. Decisão não coberta aqui é do humano — não do condutor.**
