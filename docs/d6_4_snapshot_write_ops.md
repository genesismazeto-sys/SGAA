# D6.4.0 snapshot write ops

## Estado atual

- D6.4.0-WRITE-1 aprovada no commit `483f06978c484a1ad5523425a8279f06ba86f6f4`.
- `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` permanece com default `OFF`.
- `atividade_id` continua sendo o caminho operacional principal para listagem, processamento e joins legados.
- Nao houve cutover de leitura.
- Nao houve backfill de requisicoes antigas.
- `SGAA_VERSIONED_RESOLVER_SHADOW_READ` continua independente e pode permanecer ligado para auditoria.

## Como ativar

- Definir `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=1` no ambiente de execucao desejado.
- Manter `SGAA_VERSIONED_RESOLVER_SHADOW_READ=1` como configuracao recomendada para auditoria paralela.
- Reiniciar a aplicacao somente pelo fluxo operacional previsto para o ambiente local.
- Nao alterar `atividade_id`.
- Nao ligar a flag junto com qualquer tentativa de cutover, backfill ou mudanca de leitura.

Exemplo PowerShell para sessao local:

```powershell
$env:SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE = "1"
$env:SGAA_VERSIONED_RESOLVER_SHADOW_READ = "1"
```

## Como validar apos ativacao

- Criar uma requisicao controlada via fluxo `aluno_create`.
- Criar uma requisicao controlada via fluxo `admin_create`.
- Verificar na tabela `requisicoes`:
- `atividade_id` preenchido e preservado.
- `atividade_versao_id` preenchido.
- `codigo_normativo_snapshot` preenchido.
- `regra_snapshot_json` preenchido com JSON valido.
- Verificar o log dedicado em `logs/versioned_shadow_reads.log`.
- Confirmar que o evento de shadow read continua sendo emitido para a requisicao criada.

Campos esperados no `regra_snapshot_json`:

- `schema_version`
- `snapshot_written_at`
- `flow_origin`
- `resolver_status`
- `resolver_warnings`
- `legacy_scope_ok`
- `matriz_id_efetiva`
- `atividade_id_legacy`
- `atividade_base_id`
- `atividade_versao_id`
- `codigo_normativo`
- `eixo`
- `grupo`
- `ch_por_evento`
- `limite_semestre`
- `limite_total`
- `nome_exibivel`
- `nome_legacy`
- `tipo_atividade_legacy`
- `versao_status`

Validacoes negativas obrigatorias no snapshot:

- Nao conter `observacao_aluno`.
- Nao conter `observacao_admin`.
- Nao conter texto livre do usuario.
- Nao conter `documentos`.
- Nao conter `paths`.
- Nao conter dados pessoais adicionais.

## Como validar compatibilidade

- Verificar que `/aluno/dashboard` retorna `200`.
- Verificar que `/admin/requisicoes` retorna `200`.
- Verificar que `admin_processar_requisicao` continua funcional pelo legado.
- Confirmar que o processamento administrativo continua usando `atividade_id`.
- Confirmar que requisicoes antigas com snapshot `NULL` continuam listando normalmente.
- Confirmar que base mista continua funcional:
- requisicoes antigas com `atividade_versao_id = NULL`
- requisicoes novas com snapshot preenchido

Ponto critico de compatibilidade:

- A D6.4.0 nao autoriza leitura operacional por snapshot.
- O join legado `requisicoes.atividade_id -> atividades.id` deve continuar funcional.

## Rollback

- Voltar `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=0`.
- Manter `SGAA_VERSIONED_RESOLVER_SHADOW_READ=1` se a auditoria ainda for desejada.
- Nao apagar snapshots ja gravados.
- Nao fazer backfill reverso.
- Nao alterar requisicoes historicas.
- Manter `atividade_id` como caminho operacional principal.

Exemplo PowerShell para rollback local:

```powershell
$env:SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE = "0"
$env:SGAA_VERSIONED_RESOLVER_SHADOW_READ = "1"
```

## Fora de escopo

- Leitura operacional por snapshot.
- Backfill de requisicoes antigas.
- Migracao de requisicoes antigas para snapshot.
- `admin_processar_requisicao` lendo snapshot.
- `admin_importar_requisicoes` escrevendo snapshot.
- Cutover de leitura.
- Remocao ou substituicao de `atividade_id`.

## Checklist final de ativacao

- Confirmar que o ambiente esta no commit aprovado da D6.4.0-WRITE-1.
- Confirmar que `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` sera ligado de forma explicita.
- Confirmar que `SGAA_VERSIONED_RESOLVER_SHADOW_READ=1` esta mantido para auditoria.
- Criar uma requisicao `aluno_create` controlada.
- Criar uma requisicao `admin_create` controlada.
- Verificar `atividade_id`, `atividade_versao_id`, `codigo_normativo_snapshot` e `regra_snapshot_json`.
- Conferir `logs/versioned_shadow_reads.log`.
- Validar `/aluno/dashboard` com retorno `200`.
- Validar `/admin/requisicoes` com retorno `200`.
- Confirmar que requisicoes antigas com snapshot `NULL` continuam listando.

## Checklist final de rollback

- Voltar `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=0`.
- Reiniciar a aplicacao pelo fluxo operacional normal do ambiente.
- Confirmar que novas requisicoes voltam a gravar `atividade_versao_id = NULL`.
- Confirmar que snapshots antigos permanecem intactos para auditoria.
- Confirmar que `atividade_id` continua sendo o caminho operacional.
- Confirmar que nao houve tentativa de backfill reverso.

## Validacao controlada realizada - D6.4.0-ACTIVATE-1

- Hash validado: `ba5a3dfbdf43d7c904b1f7d88d234e3c8a7db307`

Flags usadas:

- `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=1`
- `SGAA_VERSIONED_RESOLVER_SHADOW_READ=1`

Requisicoes com snapshot:

- `33` - `aluno_create` AAC
- `34` - `admin_create` AEU

Rollback testado:

- `35` - criada com `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=0` e campos versionados `NULL`

Resultado:

- `atividade_id` preservado
- snapshot preenchido somente com flag `ON`
- base mista funcionando
- shadow read dedicado funcionando
- `/aluno/dashboard` -> `200`
- `/admin/requisicoes` -> `200`
- `/admin/processar_requisicao/34` -> `200`
- `pytest -q` -> `237 passed`

- Sem backfill.
- Sem cutover de leitura.
- Sem commit de codigo.
- Sem alteracao no projeto antigo.

## Validacao controlada no ambiente alvo - D6.4.0-ACTIVATE-TARGET-1

- Hash validado: `ba5a3dfbdf43d7c904b1f7d88d234e3c8a7db307`

Porta efetiva:

- `127.0.0.1:5001`

Motivo:

- porta `5000` estava ocupada por `gerador_provas_app`; foi usado fallback permitido para `5001`.

Flags usadas na ativacao:

- `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=1`
- `SGAA_VERSIONED_RESOLVER_SHADOW_READ=1`

Observacao operacional:

- evitar espaco a direita no valor da flag. Usar `"1"`, nao `"1 "`.

Requisicoes criadas com snapshot:

- `39` - `aluno_create` AAC
- `40` - `admin_create` AEU

Rollback testado:

- `41` - criada com `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=0` e campos versionados `NULL`

Validacoes:

- `atividade_id` preservado
- `atividade_versao_id` preenchido nas reqs `39` e `40`
- `codigo_normativo_snapshot` preenchido nas reqs `39` e `40`
- `regra_snapshot_json` valido
- snapshot sem observacoes, texto livre, documentos, paths ou dados pessoais adicionais
- `/aluno/dashboard` -> `200`
- `/admin/requisicoes` -> `200`
- `/admin/processar_requisicao/40` -> `200`
- JOIN legado `r.atividade_id = atividades.id` funcionando
- `logs/versioned_shadow_reads.log` ativo
- reqs `39` e `40` registradas como `resolved`
- `resolver_exception=0`
- `error=0`
- `pytest -q` -> `237 passed`

Estado final:

- app religado com flags ON em `127.0.0.1:5001`

- Sem backfill.
- Sem cutover de leitura.
- Sem alteracao de codigo.
- Sem commit de runtime.
- Sem alteracao no projeto antigo.
