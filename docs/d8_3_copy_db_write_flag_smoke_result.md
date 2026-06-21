# D8.3 — Resultado do smoke de write flag em cópia isolada do banco

> Documento de registro de resultado (docs-only). **Nenhum cutover real foi
> executado.** A flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` permanece com
> default `OFF` em código e não foi ligada em produção. Este documento fecha
> a fase D8.3A (smoke) e abre a decisão de D8.3B/D8.4A.

## 1. Fase

D8.3A — COPY-DB-WRITE-FLAG-SMOKE.

## 2. Data/hora reportada

2026-06-20 (execução do smoke), fechamento documental D8.3B em 2026-06-20.

## 3. Objetivo

Validar o comportamento de `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=ON` para
criação de requisição do aluno em uma cópia física isolada de `database.db`,
sem alterar o banco live, sem alterar `.env`, sem alterar código e sem ligar a
flag fora do processo isolado do smoke.

## 4. Baseline Git

- branch `main`;
- HEAD `27e6f23` (`Record D8.2B student edit snapshot contract closeout`);
- `origin/main...main = 0 0`;
- working tree limpo;
- `database.db` não versionado (`git ls-files database.db` vazio).

## 5. Baseline do `database.db` live

- tamanho: `544768` bytes;
- SHA256: `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`.

## 6. Backup externo criado

`D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.3A-live-baseline-20260620-205155.db`
— hash/tamanho idênticos ao live no momento da criação; fora do worktree; não
versionado.

## 7. Cópia de trabalho do smoke

`D:\OneDrive\Programação\SGAA_database_backups\database.D8.3A-smoke-working-20260620-205155.db`
— hash/tamanho idênticos ao live no momento da criação; única cópia que
recebeu qualquer escrita do smoke; fora do worktree; não versionada.

## 8. Mecanismo seguro de DB path

Redirecionamento feito inteiramente por variável de ambiente, sem alterar
código nem `.env`:

- `APP_DATABASE` (env var lida em `main.py` e sincronizada por
  `app/db.py::_sync_database_from_main`);
- `main.DATABASE` confirmado apontando para a cópia;
- `app_db_module.DATABASE` confirmado apontando para a cópia;
- `app.config["DATABASE_PATH"]` confirmado apontando para a cópia;
- `PRAGMA database_list` de uma conexão sqlite real aberta pelo processo
  confirmando o arquivo físico da cópia, nunca o live.

## 9. Flag

`SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=1` definida somente no processo
isolado do smoke (variável de ambiente do processo, nunca em `.env`, nunca em
ambiente live).

## 10. Contagens iniciais na cópia (antes de qualquer escrita do smoke)

- `41` requisições;
- `13` com `atividade_versao_id`;
- `13` com `codigo_normativo_snapshot`;
- `13` com `regra_snapshot_json`;
- `70` alunos com `turma.matriz_id` explícito;
- `55` pares atividade/matriz elegíveis para norma ativa.

## 11. Caso válido selecionado

- aluno `id=1`;
- turma `PPA-T11`;
- `matriz_id=1`;
- `curso_id=2`;
- atividade legacy `id=1`;
- `atividade_base_id=1`;
- `atividade_versao_id` resolvida `=2`;
- `codigo_normativo=AAC-rev6`;
- `eixo=AAC`;
- `legacy_scope_ok=True`;
- sem warnings do resolvedor.

## 12. Resultado da criação válida

- `POST /aluno/nova-requisicao`;
- evento `D8.3A_SMOKE_WRITE_FLAG_ON`;
- HTTP `302`;
- requisição `id=58` criada na cópia;
- `atividade_versao_id=2`;
- `codigo_normativo_snapshot=AAC-rev6`;
- `regra_snapshot_json` preenchido;
- `schema_version=d6.4.0-v1`.

## 13. Coerência do snapshot

`numero_versao`, `codigo_normativo`, `eixo` e `grupo` do snapshot gravado
confirmados coerentes com a linha real de `atividade_versao id=2` no banco.

## 14. Guard de edição

- tentativa de troca de `atividade_id` na requisição com snapshot presente
  bloqueada de forma atômica;
- `atividade_id` inalterado;
- `atividade_versao_id` inalterado;
- `codigo_normativo_snapshot` inalterado;
- `regra_snapshot_json` inalterado;
- mensagem de bloqueio confirmada na resposta.

## 15. Caso skip

- cenário sem matriz explícita / sem resolução válida (turma com
  `matriz_id=NULL` em curso dedicado sem `matrizes_atividades`, garantindo
  que a heurística de fallback não interfira na validação legada);
- `POST /aluno/nova-requisicao` final: HTTP `302`;
- requisição `id=59` criada na cópia;
- `atividade_versao_id` `NULL`;
- `codigo_normativo_snapshot` `NULL`;
- `regra_snapshot_json` `NULL`;
- sem erro 500.

## 16. Integridade do live

- hash do live antes/durante/depois do smoke: idêntico;
- nenhuma conexão sqlite foi aberta contra o caminho live durante o smoke;
- o backup `pre-D8.3A-live-baseline` permaneceu inalterado;
- a cópia de trabalho do smoke terminou com hash diferente do inicial, como
  esperado (contém as linhas e entidades de apoio criadas pelo smoke).

## 17. Estado Git pós-smoke

- working tree limpo;
- `origin/main...main = 0 0`;
- nenhum commit criado pelo smoke;
- nenhum push;
- `.env` inexistente/intocado.

## 18. Conclusão

D8.3A aprovada. O smoke validou, em cópia isolada e com prova de
redirecionamento, que `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=ON` produz
snapshot coerente no caso válido, é bloqueado corretamente na edição quando o
snapshot já existe, e não escreve snapshot quando não há matriz explícita
resolvível — sem nenhum efeito sobre o banco live.

## 19. Limite

D8.3A não autoriza cutover real. A flag permanece `OFF` por padrão em código
e não foi ligada em nenhum ambiente live ou compartilhado.

## 20. Próxima fase recomendada

D8.4A — plano/ativação local controlada da flag, somente com autorização
explícita prévia. Nenhuma ativação decorre automaticamente deste closeout.
