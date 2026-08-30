# 01 — Mapa completo de rotas

Todas as rotas do app, organizadas por área. Colunas:

- **URL** — padrão de rota Flask.
- **Métodos** — verbos HTTP aceitos.
- **Endpoint / View** — nome do endpoint Flask e onde está definido.
- **Acesso** — quem pode entrar e qual permissão RBAC é exigida (ver
  [02](02_autenticacao_e_seguranca.md) para o modelo de permissões).

> Como ler "Acesso": rotas `admin_*` exigem `user_type == "admin"` **mais** o
> par `(recurso, escopo)` definido em `app/auth.py::get_admin_permission_requirement`.
> O `before_request` (`enforce_admin_access_control`) aplica isso automaticamente.
> Rotas `aluno.*` usam o decorator `@aluno_required`.

## Visão geral (contagem)

| Origem | Rotas | Status |
|--------|-------|--------|
| `main.py` (`@app.route`) | ~113 | ativas |
| `app/views/aluno.py` (`bp_aluno`) | 11 | **ativas** (`USE_ALUNO_BLUEPRINT=True`) |
| `app/views/core.py` (via `create_app`) | 3 + `/csrf-token` | ativas |
| `presets_api.py` (`bp_presets`) | 2 | ativas |
| `main.py` `@aluno_runtime_route` | 6 | **CÓDIGO MORTO** (no-op, ver abaixo) |

> ⚠️ **Duplicação aluno (código morto):** `main.py` ainda contém as views
> `aluno_dashboard`, `aluno_minhas_requisicoes`, `aluno_requisicao_detalhe`,
> `aluno_arquivos`, `aluno_nova_requisicao`, `aluno_meus_dados` decoradas com
> `@aluno_runtime_route`. Como `USE_ALUNO_BLUEPRINT=True` (`main.py:4579`), esse
> decorator vira **no-op** e essas funções **não são registradas** — as versões
> ativas vivem no blueprint `app/views/aluno.py`. São ~centenas de linhas de
> código morto. Detalhe em [04](04_arquitetura_e_modulos.md).

---

## Público / infraestrutura

| URL | Métodos | Endpoint / View | Acesso |
|-----|---------|-----------------|--------|
| `/` | GET | `index` — `app/views/core.py` | Público (redirect p/ `/login`) |
| `/login` | GET, POST | `login` — `app/views/core.py` | Público (rate-limited, isento de CSRF) |
| `/logout` | GET, POST | `logout` — `app/views/core.py` | Autenticado |
| `/csrf-token` | GET | `csrf_token_refresh` — `app/__init__.py` | Autenticado (refresca token CSRF p/ AJAX) |
| `/health` | GET | `health` — `main.py:15365` | Público (healthcheck) |
| `/favicon.ico` | GET | `favicon` — `main.py:15444` | Público |
| `/uploads/<path:filename>` | GET | `uploads` — `main.py:15257` | Autenticado (serve arquivos enviados) |

## Área do Aluno (blueprint `aluno`, `@aluno_required`)

Todas em `app/views/aluno.py`. Endpoints no formato `aluno.<func>`.

| URL | Métodos | Endpoint | Função |
|-----|---------|----------|--------|
| `/aluno/dashboard` | GET | `aluno.aluno_dashboard` | Painel do aluno (progresso de horas) |
| `/aluno/progresso` | GET | `aluno.aluno_progresso` | Detalhe de progresso por grupo/limite |
| `/aluno/meus_dados` | GET, POST | `aluno.aluno_meus_dados` | Dados pessoais + foto |
| `/aluno/arquivos` | GET | `aluno.aluno_arquivos` | Arquivos publicados pelo admin |
| `/aluno/arquivos/ver/<int:arquivo_id>` | GET | `aluno.aluno_visualizar_arquivo` | Visualiza arquivo |
| `/aluno/arquivos/download/<int:arquivo_id>` | GET | `aluno.aluno_baixar_arquivo` | Baixa arquivo |
| `/aluno/reportar` | GET, POST | `aluno.aluno_reportar` | Reporta bug/problema (vira `reportes`) |
| `/aluno/requisicoes` | GET | `aluno.aluno_minhas_requisicoes` | Lista requisições do aluno |
| `/aluno/nova-requisicao` _e_ `/aluno/nova_requisicao` | GET, POST | `aluno.aluno_nova_requisicao` | Cria requisição (2 URLs → mesma view) |
| `/aluno/requisicoes/<int:req_id>` | GET, POST | `aluno.aluno_requisicao_detalhe` | Detalhe/edição da requisição |

## Área Admin — Dashboard e conta

| URL | Métodos | Endpoint | Permissão |
|-----|---------|----------|-----------|
| `/admin/dashboard` | GET | `admin_dashboard` | `dashboard:view` |
| `/admin/demo/clientes-form-pack` | GET | `admin_demo_clientes_form_pack` | `dashboard:view` |
| `/admin/meus_dados` | GET, POST | `admin_meus_dados` | `meus_dados:view` (GET) / `edit` (POST) |

## Admin — Requisições

| URL | Métodos | Endpoint | Permissão |
|-----|---------|----------|-----------|
| `/admin/requisicoes` | GET | `admin_requisicoes` | `requisicoes:view` |
| `/admin/requisicoes/nova` | GET, POST | `admin_nova_requisicao` | `requisicoes:edit` |
| `/admin/requisicoes/<int:req_id>/editar` | POST | `admin_editar_requisicao` | `requisicoes:edit` |
| `/admin/requisicoes/<int:req_id>/excluir` | POST | `admin_excluir_requisicao` | `requisicoes:full` |
| `/admin/requisicao/<int:req_id>` | GET | `admin_detalhes_requisicao` | `requisicoes:view` |
| `/admin/api/requisicao/<int:req_id>` | GET | `admin_api_requisicao` | `requisicoes:view` |
| `/admin/api/aluno/<int:aluno_id>/requisicao-scope` | GET | `admin_api_aluno_requisicao_scope` | `requisicoes:view` |
| `/admin/processar_requisicao/<int:req_id>` | GET, POST | `admin_processar_requisicao` | `requisicoes:edit` |
| `/admin/importar_requisicoes` | GET, POST | `admin_importar_requisicoes` | `requisicoes:full` |

## Admin — Atividades (modelo legado)

| URL | Métodos | Endpoint | Permissão |
|-----|---------|----------|-----------|
| `/admin/atividades` | GET | `admin_atividades` | `atividades:view` |
| `/admin/atividades/academicas` | GET | `admin_atividades_academicas` | `atividades:view` |
| `/admin/atividades/extensao` | GET | `admin_atividades_extensao` | `atividades:view` |
| `/admin/adicionar_atividade` | GET, POST | `admin_adicionar_atividade` | `atividades:edit` |
| `/admin/editar_atividade/<int:atividade_id>` | GET, POST | `admin_editar_atividade` | `atividades:edit` |
| `/admin/deletar_atividade/<int:atividade_id>` | POST | `admin_deletar_atividade` | `atividades:full` |
| `/admin/atividades/importar/preview` | GET, POST | `admin_atividades_importar_preview` | `atividades:full` |
| `/admin/atividades/importar/confirmar` | POST | `admin_atividades_importar_confirmar` | `atividades:full` |
| `/admin/grupos/renomear` | POST | `admin_grupos_renomear` | `atividades:full` |
| `/admin/grupos/excluir` | POST | `admin_grupos_excluir` | `atividades:full` |

## Admin — Catálogo versionado de atividades

Modelo novo: bases, versões, normas, mapeamento legado.

| URL | Métodos | Endpoint | Permissão* |
|-----|---------|----------|-----------|
| `/admin/catalogo-versoes` | GET | `admin_catalogo_versoes` | `atividades:view` |
| `/admin/catalogo-versoes/<int:base_id>` | GET | `admin_catalogo_versao_detalhe` | `atividades:view` |
| `/admin/catalogo-versoes/nova-base` | GET, POST | `admin_catalogo_nova_base` | `atividades` |
| `/admin/catalogo-versoes/<int:base_id>/nova-versao` | GET, POST | `admin_catalogo_nova_versao` | `atividades` |
| `/admin/catalogo-versoes/<base_id>/versoes/<versao_id>/editar` | GET, POST | `admin_catalogo_versao_editar` | `atividades` |
| `/admin/catalogo-versoes/<base_id>/versoes/<versao_id>/ativar` | POST | `admin_catalogo_versao_ativar` | `atividades` |
| `/admin/catalogo-versoes/<base_id>/versoes/<versao_id>/substituir` | POST | `admin_catalogo_versao_substituir` | `atividades` |
| `/admin/catalogo-versoes/<base_id>/versoes/<versao_id>/inativar` | POST | `admin_catalogo_versao_inativar` | `atividades` |
| `/admin/catalogo-versoes/<base_id>/versoes/<versao_id>/descontinuar` | POST | `admin_catalogo_versao_descontinuar` | `atividades` |
| `/admin/normas-atividade` | GET | `admin_normas_atividade` | `atividades:view` |
| `/admin/normas-atividade/nova` | GET, POST | `admin_nova_norma` | `atividades` |
| `/admin/mapeamento-legado` | GET | `admin_mapeamento_legado` | `atividades:view` |

\* As rotas de catálogo cujo endpoint **não** está explicitamente listado em
`get_admin_permission_requirement` caem na regra genérica de prefixo (verifique
o endpoint exato no auth.py; várias herdam `atividades:view`/`edit`/`full`).

## Admin — Matrizes de atividades

| URL | Métodos | Endpoint | Permissão |
|-----|---------|----------|-----------|
| `/admin/matrizes` | GET | `admin_matrizes` | `matrizes:view` |
| `/admin/adicionar_matriz` | GET, POST | `admin_adicionar_matriz` | `matrizes:edit` |
| `/admin/editar_matriz/<int:matriz_id>` | GET, POST | `admin_editar_matriz` | `matrizes:view` (GET) / `edit` (POST) |
| `/admin/matrizes/<int:matriz_id>/atividades/nova/<string:active_tab>` | POST | (nova atividade na matriz) | `matrizes:*` |
| `/admin/matrizes/<matriz_id>/atividades/<atividade_id>/nova-versao` | POST | (nova versão na matriz) | `matrizes:*` |
| `/admin/matrizes/excluir` | POST | `admin_excluir_matrizes` | `matrizes:full` |
| `/admin/matrizes/<int:matriz_id>/excluir` | POST | `admin_excluir_matriz` | `matrizes:full` |
| `/admin/matrizes/<int:matriz_id>/versoes` | GET | (lista versões da matriz) | `matrizes` |
| `/admin/matrizes/<int:matriz_id>/versoes/definir` | POST | (define versão por base) | `matrizes` |
| `/admin/matrizes/<int:matriz_id>/versoes/remover` | POST | (remove versão da matriz) | `matrizes` |

## Admin — Alunos, Turmas, Cursos

| URL | Métodos | Endpoint | Permissão |
|-----|---------|----------|-----------|
| `/admin/alunos` | GET | `admin_alunos` | `alunos:view` |
| `/admin/adicionar_aluno` | GET, POST | `admin_adicionar_aluno` | `alunos:edit` |
| `/admin/editar_aluno/<int:usuario_id>` | GET, POST | `admin_editar_aluno` | `alunos:edit` |
| `/admin/deletar_aluno/<int:usuario_id>` | POST | `admin_deletar_aluno` | `alunos:full` |
| `/admin/alterar_status_alunos` | POST | `admin_alterar_status_alunos` | `alunos:edit` |
| `/admin/turmas` | GET | `admin_turmas` | `turmas:view` |
| `/admin/adicionar_turma` | GET, POST | `admin_adicionar_turma` | `turmas:edit` |
| `/admin/editar_turma/<int:turma_id>` | GET, POST | `admin_editar_turma` | `turmas:edit` |
| `/admin/deletar_turma/<int:turma_id>` | POST | `admin_deletar_turma` | `turmas:full` |
| `/admin/turma/<int:turma_id>` | GET | `admin_detalhes_turma` | `turmas:view` |
| `/admin/turmas/importar` | GET, POST | `admin_turmas_importar` | `turmas:full` |
| `/admin/cursos` | GET | `admin_cursos` | `cursos:view` |
| `/admin/cursos/adicionar` | GET, POST | `admin_adicionar_curso` | `cursos:edit` |
| `/admin/cursos/<int:curso_id>/editar` | GET, POST | `admin_editar_curso` | `cursos:edit` |
| `/admin/cursos/<int:curso_id>` | GET | `admin_detalhes_curso` | `cursos:view` |
| `/admin/cursos/<int:curso_id>/visualizar` | GET | `admin_visualizar_curso` | `cursos:view` |
| `/admin/deletar_curso/<int:curso_id>` | POST | `admin_deletar_curso` | `cursos:full` |

## Admin — Arquivos, Alertas, Reportes

| URL | Métodos | Endpoint | Permissão |
|-----|---------|----------|-----------|
| `/admin/arquivos` | GET | `admin_arquivos` | `arquivos:view` |
| `/admin/arquivos/adicionar` | POST | `admin_adicionar_arquivo` | `arquivos:edit` |
| `/admin/arquivos/<int:arquivo_id>/editar` | GET, POST | `admin_editar_arquivo` | `arquivos:edit` |
| `/admin/arquivos/<int:arquivo_id>/visualizar` | GET | `admin_visualizar_arquivo` | `arquivos:view` |
| `/admin/arquivos/<int:arquivo_id>/deletar` | POST | `admin_deletar_arquivo` | `arquivos:full` |
| `/admin/alertas` | GET | `admin_alertas` | `alertas:view` |
| `/admin/alertas/salvar` | POST | `admin_salvar_alerta` | `alertas:edit` |
| `/admin/alertas/<int:alerta_id>/alternar` | POST | `admin_alternar_alerta` | `alertas:edit` |
| `/admin/alertas/<int:alerta_id>/deletar` | POST | `admin_deletar_alerta` | `alertas:full` |
| `/admin/reportes` | GET | `admin_reportes` | `reportes:view` |
| `/admin/reportes/novo` | POST | `admin_reportes_novo` | `reportes:edit` |
| `/admin/reportes/<int:reporte_id>/status` | POST | `admin_reportes_status` | `reportes:edit` |
| `/admin/reportes/<int:reporte_id>/deletar` | POST | `admin_reportes_deletar` | `reportes:full` |

## Admin — Configurações e Mensagens

| URL | Métodos | Endpoint | Permissão |
|-----|---------|----------|-----------|
| `/admin/configuracoes` | GET | `admin_configuracoes` | `configuracoes:view` |
| `/admin/configuracoes/tempo-resposta` | POST | `admin_configuracoes_tempo_resposta_salvar` | `configuracoes:edit` |
| `/admin/configuracoes/tempo-resposta/reset` | POST | `admin_configuracoes_tempo_resposta_resetar` | `configuracoes:full` |
| `/admin/configuracoes/prazo-adequacao` | POST | `admin_configuracoes_prazo_adequacao_salvar` | `configuracoes:edit` |
| `/admin/configuracoes/horas-padrao` | POST | `admin_configuracoes_horas_padrao_salvar` | `configuracoes:edit` |
| `/admin/mensagens` | GET | `admin_mensagens` | `mensagens:view` |
| `/admin/mensagens/salvar` | POST | `admin_mensagens_salvar` | `mensagens:edit` |
| `/admin/mensagens/<message_key>/reset` | POST | `admin_mensagens_resetar` | `mensagens:full` |

## Admin — Banco de dados e Backup

| URL | Métodos | Endpoint | Permissão |
|-----|---------|----------|-----------|
| `/admin/banco-dados` | GET | `admin_banco_dados` | `banco_dados:view` |
| `/admin/banco-dados/configuracoes` | POST | `admin_banco_dados_configuracoes` | `banco_dados:edit` |
| `/admin/banco-dados/retencao` | POST | `admin_banco_dados_retencao` | `banco_dados:edit` |
| `/admin/banco-dados/drive-settings` | POST | `admin_banco_dados_drive_settings` | `banco_dados:edit` |
| `/admin/banco-dados/backup` | POST | `admin_banco_dados_backup` | `banco_dados:edit` |
| `/admin/banco-dados/download` | GET | `admin_banco_dados_download` | `banco_dados:view` |
| `/admin/banco-dados/excluir` | POST | `admin_banco_dados_excluir` | `banco_dados:full` |
| `/admin/banco-dados/restaurar` | POST | `admin_banco_dados_restaurar` | `banco_dados:full` |
| `/admin/banco-dados/restaurar/upload` | POST | `admin_banco_dados_restaurar_upload` | `banco_dados:full` |
| `/admin/banco-dados/oauth/start` | GET | `admin_banco_dados_oauth_start` | `banco_dados:edit` |
| `/admin/banco-dados/oauth/disconnect` | POST | `admin_banco_dados_oauth_disconnect` | `banco_dados:edit` |
| `/admin/backup/google/connect` | GET | `admin_backup_google_connect` | `banco_dados:edit` |
| `/admin/backup/google/upload` | POST | `admin_backup_google_upload` | `banco_dados:edit` |
| `/admin/backup/onedrive/connect` | GET | `admin_backup_onedrive_connect` | `banco_dados:edit` |
| `/admin/backup/onedrive/upload` | POST | `admin_backup_onedrive_upload` | `banco_dados:edit` |
| `/admin/backup/cloud-folders/<provider>` | GET | `admin_backup_cloud_folders` | `banco_dados:edit` |
| `/admin/backup/cloud-folder/<provider>` | GET, POST | `admin_backup_cloud_folder` | `banco_dados:edit` |

### Callbacks OAuth (backup em nuvem)

| URL | Métodos | Endpoint | Permissão |
|-----|---------|----------|-----------|
| `/google/callback` | GET | `google_callback` | `banco_dados:edit` |
| `/onedrive/callback` | GET | `onedrive_callback` | `banco_dados:edit` |
| `/auth/callback` | GET | `auth_callback` | `banco_dados:edit` (legado) |

## Admin — Acesso (RBAC / usuários)

| URL | Métodos | Endpoint | Permissão |
|-----|---------|----------|-----------|
| `/admin/acesso` | GET | `admin_acesso` | `acesso:view` |
| `/admin/acesso/salvar` | POST | `admin_acesso_salvar` | `acesso:full` |
| `/admin/acesso/senhas-default` | POST | `admin_acesso_senhas_default` | `acesso:full` |
| `/admin/acesso/<int:usuario_id>/resetar-senha` | POST | `admin_acesso_resetar_senha` | `acesso:full` |
| `/admin/acesso/definir-senha` | POST | `admin_acesso_definir_senha` | `acesso:full` |
| `/admin/acesso/<int:usuario_id>/deletar` | POST | `admin_acesso_deletar` | `acesso:full` |

## Admin — Diagnóstico (versionamento)

| URL | Métodos | Endpoint | Observação |
|-----|---------|----------|-----------|
| `/admin/diagnostico/atividades-versionadas` | GET | `admin_diagnostico_atividades_versionadas` | Diagnóstico do resolver versionado |
| `/admin/diagnostico/atividades-versionadas/view` | GET | (view HTML do diagnóstico) | |
| `/admin/diagnostico/versioned-shadow-reads` | GET | (logs de "shadow read") | Telemetria de migração de versionamento |

## API de Presets (blueprint `presets`)

| URL | Métodos | Endpoint | Permissão |
|-----|---------|----------|-----------|
| `/admin/api/presets` | GET | `presets.get_presets` | `requisicoes:view` |
| `/admin/api/presets` | POST | `presets.post_presets` | `requisicoes:edit` |

---

## Notas importantes sobre rotas

1. **Endpoint = nome da função.** As rotas em `main.py` usam o nome da função
   como endpoint (sem prefixo de blueprint). Por isso o RBAC em `auth.py` casa
   por nome de endpoint (ex.: `admin_requisicoes`). Ao refatorar para blueprints,
   os endpoints virarão `<blueprint>.<func>` e **o mapa de permissões em
   `get_admin_permission_requirement` precisa ser atualizado junto** (risco nº 1
   de quebra — ver [05](05_avaliacao_refactor.md)).

2. **Helper `route_url` / `aluno_url`.** Templates usam o global `route_url(...)`
   (`app/__init__.py:196`) que tenta múltiplos nomes de endpoint até um existir —
   uma rede de segurança contra `BuildError` durante a migração para blueprints.
   `aluno_url()` em `main.py:4594` prefixa `aluno.` quando o blueprint está ativo.

3. **Catálogo versionado:** algumas rotas de catálogo/matriz têm decoradores
   multi-linha em `main.py` (ex.: linhas 13087, 13794, 13992, 14066, 14176, 14241).
   Confirme sempre o nome exato da função logo abaixo do decorator.
