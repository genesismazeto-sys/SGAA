# 03 — Banco de dados

- **SGBD:** SQLite (arquivo único `database.db`), modo **WAL**,
  `synchronous = NORMAL`, `foreign_keys = ON`.
- **Conexão:** uma por request, em `g.db` (`app/db.py::get_db_connection`).
  `row_factory = sqlite3.Row`. Há uma collation custom `PTBR_NOACCENT` para
  ordenação alfabética PT-BR sem acento.
- **Caminho:** `APP_DATABASE` (env) ou `./database.db`.
- **Tabelas:** 32. **Dados reais hoje:** 71 usuários, 70 alunos, 41 requisições,
  32 atividades (legado), 37 bases / 63 versões de atividade, 9 matrizes, 2
  turmas, 1 curso.

## Mapa de relacionamentos (alto nível)

```
usuarios (admin|aluno)
   │ 1:1 (usuario_id)
   ▼
 alunos ──────────────┐
   │ turma_id          │ aluno_id
   ▼                   ▼
 turmas            requisicoes ──── atividade_id ──► atividades (legado)
   │ curso_id        │  │
   │ matriz_id       │  ├─ atividade_versao_id ──► atividade_versao (snapshot)
   ▼                 │  └─ requisicao_arquivos (1:N comprovantes)
 cursos              │
   │ 1:N             │ admin_id ──► usuarios
   ▼                 │
 matrizes_atividades ◄┘ (turma.matriz_id / curso preferida)
   ├─ matrizes_atividades_itens ──► atividades (legado)
   ├─ matriz_atividade_versao_item ──► atividade_versao (modelo novo)
   └─ matriz_norma ──► norma_atividade

CATÁLOGO VERSIONADO:
 atividade_base ──1:N──► atividade_versao ◄── norma_atividade
                               │
                               └─ atividade_transicao (from/to versão)
 atividade_legacy_map: atividades(legado) ──► atividade_base
```

## Entidades principais

### `usuarios`
Identidade e credenciais. `tipo` ∈ {admin, aluno}; `nivel_acesso` (RBAC, default
`administrativo`); `senha` (hash PBKDF2); `foto_perfil`. Índice em `email`.

### `alunos`
Perfil acadêmico do aluno. `usuario_id` (FK 1:1 → usuarios), `matricula` (única),
`turma` (texto legado) **e** `turma_id` (FK nova), `status` (Ativo/Inativo).
Convivência de `turma` texto + `turma_id` é dívida de migração.

### `turmas`
`curso_id`, `matriz_id`, `numero`, `codigo` (único), `ano_inicio/semestre_inicio`,
`ano_fim/semestre_fim`, `turno`, `status`. Colunas foram adicionadas via ALTER ao
longo do tempo (visível no DDL "achatado"). Índices únicos
`uq_turma_por_curso(curso_id, numero)` e `uq_turma_codigo(codigo)`.

### `cursos`
`codigo` (único, maiúsculas), `duracao_periodos`, `periodo`, `status`. Curso
default "GERAL" é semeado se a tabela estiver vazia. (Nota: as colunas
`total_horas_aac/aeu` existem no código de init mas a versão atual do schema
moveu essa obrigatoriedade para as **matrizes** — ver `matrizes_atividades`.)

### `atividades` (modelo LEGADO)
Catálogo simples original: `grupo`, `nome` (único), `tipo_atividade` (Acadêmica
Complementar | Extensão Universitária), limites (`tem_limitacao`,
`tipo_limitacao` total|semestral, `limite_horas_total/semestral`),
`documentos_json`. Ainda é a FK de `requisicoes.atividade_id`.

### `requisicoes` (entidade central de operação)
`aluno_id`, `atividade_id`, `data_solicitacao`, `data_evento`,
`horas_solicitadas`, `horas_deferidas`, `nome_evento`, `status` ∈ {Pendente,
Deferida, Deferida Parcialmente, Indeferida, Devolvida}, `observacao`,
`arquivo_comprovante`, `data_processamento`, `admin_id`.
Colunas de **notificação** ao aluno: `aluno_update_notified_at`,
`aluno_update_seen_at`.
Colunas de **snapshot normativo**: `atividade_versao_id`, `regra_snapshot_json`,
`codigo_normativo_snapshot` — congelam a regra vigente no momento da requisição
(coração do versionamento; ver abaixo). FKs: aluno (SET NULL), atividade
(RESTRICT), admin (SET NULL).

### `requisicao_arquivos`
Anexos/comprovantes 1:N de uma requisição (`label`, `filename`).

## Catálogo versionado de atividades (modelo NOVO)

Este é o subsistema mais sofisticado e o foco do trabalho recente (fases "D6/D7/D8"
nos docs). Objetivo: quando a **norma** de uma atividade muda, alunos que já
estavam sob a norma antiga mantêm a regra antiga; novos seguem a nova.

- **`atividade_base`** — o "conceito" estável da atividade (`nome_conceito` único).
- **`norma_atividade`** — a norma/resolução (`codigo` único, `eixo` AAC|AEU,
  `revisao`, `status`).
- **`atividade_versao`** — uma versão concreta de uma base sob uma norma:
  `eixo`, `grupo`, `ch_por_evento`, `limite_semestre`, `limite_total`,
  `numero_versao`, `status` ∈ {rascunho, ativa, inativa, descontinuada,
  substituida}, `versao_anterior_id` (cadeia), vigência.
- **`atividade_transicao`** — liga versões (from/to) com `tipo_transicao`
  (mesmo_eixo, aac_para_aeu, nova_aeu, descontinuada, sem_transicao).
- **`atividade_legacy_map`** — mapeia `atividades` (legado) → `atividade_base`,
  com `status` (pendente/mapeada/revisar). Ponte da migração.
- **`matriz_atividade_versao_item`** — quais versões compõem uma matriz.
- **`matriz_norma`** — quais normas se aplicam a uma matriz.

**Resolução de versão** (qual regra vale para um aluno/requisição): funções
`resolver_versao`, `resolver_versao_por_matriz`, `resolver_versao_por_aluno` em
`main.py`. Há um mecanismo de **"shadow read"** (flags
`is_versioned_resolver_shadow_read_enabled`, etc.) que roda o resolver novo em
paralelo ao legado e loga divergências, mais um **snapshot** gravado na
requisição (`maybe_write_versioned_requisicao_snapshot`). Estratégia de migração
cuidadosa, com diagnósticos em `/admin/diagnostico/*`.

## Matrizes

### `matrizes_atividades`
Conjunto de atividades válidas para um curso/período. `curso_id`, `nome`,
`versao`, `status`, vigência, `horas_aac_obrigatorias` (160),
`horas_extensao_obrigatorias` (80), `matriz_origem_id` (clonagem). É aqui que as
**horas obrigatórias** do aluno são definidas hoje.

- `matrizes_atividades_itens` — itens via modelo legado (`atividade_id`).
- `matriz_atividade_versao_item` — itens via modelo versionado.

Resolução da matriz efetiva de uma turma: `get_effective_matriz_for_turma`
(turma.matriz_id → preferida do curso → fallback).

## Tabelas de sistema / configuração

| Tabela | Função |
|--------|--------|
| `usuarios_permissoes_acesso` | Overrides de escopo por usuário (RBAC) |
| `configuracoes_acesso` | Senhas padrão por nível de acesso |
| `configuracoes_app` | Chave/valor: tempo de resposta, prazos, horas padrão |
| `configuracoes_backup` | Chave/valor: agendamento/destino de backup |
| `configuracoes_presets` | Presets de respostas/e-mails (tipo, preset_id) |
| `mensagens_editaveis` | Overrides de mensagens da UI (chave→texto) |
| `grupos_def` | Definição de grupos por tipo de atividade |
| `admin_alertas` | Banners/alertas exibidos a alunos |
| `admin_arquivos` | Arquivos publicados pelo admin (download p/ alunos) |
| `reportes` | Bugs/problemas reportados por alunos |
| `requisicao_alerta_receipts` | "Lido" de alertas de atualização por usuário |
| `cloud_accounts` | Contas OAuth de nuvem (token Fernet-criptografado) |
| `cloud_drive_settings` | Pasta de destino por provedor |
| `backup_logs` | Histórico de backups (provider, tamanho, status) |
| `schema_migrations` | Controle de migrações aplicadas (version, name, applied_at) |

## Migrações de schema

Estratégia **mista** (ponto de dívida técnica):

1. **`init_db()`** (existe em `app/db.py` **e** duplicado em `main.py:5869`):
   `CREATE TABLE IF NOT EXISTS ...` + uma **lista de `ALTER TABLE` em try/except**
   que ignora `OperationalError` (coluna já existe). É idempotente mas frágil e
   difícil de auditar.
2. **`ensure_*` functions** (em `main.py`): cada subsistema garante seu schema
   sob demanda (`ensure_atividade_versioning_schema`, `ensure_usuario_access_schema`,
   etc.). Algumas recriam tabelas (`_recreate_atividade_versao`) para mudar
   constraints — operação delicada em SQLite.
3. **`apply_schema_migrations(conn)`** (`app/db_maintenance.py`) + tabela
   `schema_migrations` — abordagem **versionada e correta**, adotada mais
   recentemente. É para onde o resto deveria convergir.

> Os 17 artefatos `database.pre-*.db`, `database.pre-*.db-shm` e `database.pre-*.db-wal`
> na raiz são snapshots manuais históricos (9 .db, 4 .db-shm, 4 .db-wal). Não são
> usados em runtime; sua custódia é governada por trilha administrativa autônoma.
> Estes 17 artefatos históricos NÃO são backups gerenciados por `app/db_maintenance.py`
> nem `app/services/backup_service.py`. Nenhuma validação, restauração ou arquivamento
> foi realizada ou autorizada.
> A custódia destes artefatos é regida pela política aprovada em R1 (HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R1: CLOSED / ACCEPTED). Modelo de custódia: SHARED.
> HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R2: CLOSED / ACCEPTED. Destino canônico
> selecionado por decisão humana: `D:\programas\SGAA_Historical_Custody`.
> Destination status: SELECTED. Provisioning status: SELECTED / PARENT PATH NOT YET
> PROVISIONED — o diretório ainda não existe e sua criação não está autorizada.
> Risco de domínio de armazenamento: o destino está fora do repositório e fora da
> árvore OneDrive observada, mas permanece no mesmo domínio físico de armazenamento
> D: do workspace de origem; isso oferece separação lógica, não redundância em disco
> independente. Não é redundante, imutável, off-site, independente do disco de origem,
> versionado nem protegido contra exclusão.
> Contrato de cópia Gates 0–6 ratificado documentalmente; nenhum gate executado.
> HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R3: CLOSED / ACCEPTED. R3 foi read-only e seu
> contrato de provisionamento e cópia foi APROVADO por decisão humana em 25/07/2026.
> Classificação de fase, superada pela R4: PROVISIONING_AND_COPY_CONTRACT_APPROVED /
> DESTINATION NOT YET PROVISIONED / PHYSICAL EXECUTION NOT AUTHORIZED AT THIS TIME.
> Layout aprovado: `artifacts\` (os 17 artefatos), `manifests\` (manifesto de custódia
> JSON), `evidence\` (relatórios de cópia e verificação).
> Executor técnico aprovado: `KR-IDEAPAD\klebe`.
> ACL aprovada: herança desabilitada; `Usuários autenticados` e `BUILTIN\Usuários`
> removidos; `SYSTEM` e `Administradores` com FullControl; executor com Modify durante
> provisionamento e cópia e, após a verificação, ReadAndExecute em `artifacts\` e Modify
> em `manifests\` e `evidence\`. A ACL é obrigatória porque `D:\` possui ACEs
> `ContainerInherit, ObjectInherit` que concedem modify efetivo a `Usuários autenticados`;
> com herança padrão a custódia ficaria gravável e excluível por qualquer usuário
> autenticado da máquina. ACL não é imutabilidade.
> Contrato de cópia aprovado: copy-only; lista explícita dos 17 paths; glob proibido;
> overwrite proibido; `.db`, `.db-wal` e `.db-shm` preservados conjuntamente; parada no
> primeiro erro; nenhuma abertura SQLite; origem nunca modificada; semântica
> `File.Copy(source, destination, overwrite: false)`.
> Resíduo de cópia parcial: preservado até decisão humana explícita; limpeza automática e
> retry silencioso NÃO AUTORIZADOS.
> Ambiente de restauração Nível 2: `CONTAINER_RUNTIME_NOT_AVAILABLE` observado em leitura;
> alternativa provisória aprovada `D:\tmp\sgaa_restore_<UTC>`, descartável, montando apenas
> cópia derivada de `artifacts\`; o workspace de origem nunca é montado como banco de
> restauração e `artifacts\` nunca é aberto diretamente. ISOLATED CONTAINER volta a ser
> preferido se houver runtime instalado.
> HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R4: **EXECUTADA** — provisionamento físico completo,
> cópia completa, integridade verificada, origem preservada. Autorização física
> pré-execução: EVIDENCIADA; autoridade: dono do projeto; escopo: somente R4.
> Destino provisionado em `D:\programas\SGAA_Historical_Custody`, com `artifacts\`
> (17 arquivos, 4.808.704 bytes), `manifests\custody-manifest-20260725T233026Z.json`
> (16.872 bytes) e `evidence\r4-copy-and-verification-20260725T233315Z.md` (4.505 bytes).
> SHA-256 por arquivo no destino = origem = cânone para os 17. Hash agregado da origem
> `44ae5da3f368605ac2550cc65d70d2081d432977c48fad1f467884a65f2e3be3` inalterado antes e
> depois da cópia. Os 17 artefatos originais permanecem na raiz do repositório, ignored,
> untracked e fisicamente inalterados.
> Nenhum banco foi aberto como SQLite em nenhum momento — apenas hash e cópia binária.
> Restauração Nível 2 e Nível 3: NÃO EXECUTADAS. Remoção da origem: NÃO AUTORIZADA.
> Não conformidades operacionais da R4: DECLARED / CONTAINED / NO ARTIFACT INTEGRITY
> IMPACT / NOT AN AUTHORIZED PRECEDENT — três ocorrências registradas no documento de
> custódia. A R4 não deve ser descrita como execução sem falhas.
> Risco residual: exposição de ACL no diretório pai `D:\programas` ainda ABERTA; custódia
> completa do ponto de vista de segurança AINDA NÃO declarada.
> Próxima ação canônica: HISTORICAL-DATABASE-SNAPSHOT-CUSTODY-R5 — verificação read-only da
> exposição do pai e pacote de decisão sobre endurecimento da ACL do pai. R5 is NOT STARTED
> e não está autorizada a modificar `D:\programas`, o diretório custodial, qualquer ACL,
> artefato, manifesto ou arquivo de evidência. Fases 2–6 permanecem não autorizadas.
> Wording histórico/superado: "Destino específico: NOT YET SELECTED".
> Consulte `docs/refactor/HISTORICAL_DATABASE_SNAPSHOT_CUSTODY.md` para o inventário
> completo e política vigente. Nenhuma ação de arquivamento foi executada ou autorizada.

## Backup e sincronização

- **Snapshot local:** `create_database_snapshot` (cópia do `.db`) com política de
  retenção (`apply_retention_policy`).
- **Upload nuvem:** Google Drive (`app/services/google_drive_service.py`) e
  OneDrive (`services/onedrive_service.py`) via OAuth; zip do SQLite
  (`app/services/backup_service.py`).
- **Disparo:** `_maybe_sync_database_snapshot` é chamado no **`after_request` de
  toda resposta** (`main.py:5208`) — não em um job agendado. ⚠️ Acopla
  persistência ao ciclo de request; ver [04](04_arquitetura_e_modulos.md) e
  [06](06_deploy_e_infraestrutura.md).
- **Restore:** upload de zip → `extract_restore_database_artifact` →
  `restore_database_snapshot` (rotas `/admin/banco-dados/restaurar*`).

## Avaliação do banco (resumo — detalhes em [06](06_deploy_e_infraestrutura.md))

**Pontos fortes**
- Schema bem normalizado, com FKs, CHECKs de domínio e índices em abundância.
- Modelo de versionamento bem pensado (snapshots imutáveis na requisição).
- Migrações versionadas já existem (`schema_migrations`).

**Pontos de atenção**
- **SQLite** é ótimo para ~100 alunos e baixa concorrência de escrita, **mas**:
  escrita é serializada (1 writer por vez), exige **filesystem persistente** e
  **uma única instância** (não escala horizontalmente / não combina com
  serverless). É o fator nº 1 nas decisões de deploy.
- **Dupla modelagem de atividades** (legado `atividades` + versionado
  `atividade_*`) aumenta a carga cognitiva; há um plano de convergência em
  andamento (legacy_map). Concluir a migração reduziria muito a complexidade.
- **`init_db` duplicado** (main.py vs app/db.py) e ALTERs em try/except: migrar
  tudo para `schema_migrations` versionado.
- Convivência `alunos.turma` (texto) + `alunos.turma_id` (FK): consolidar.
