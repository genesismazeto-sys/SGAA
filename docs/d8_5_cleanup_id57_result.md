# D8.5 — Resultado da limpeza controlada da requisição smoke D8.4A (id=57)

> Documento de registro de resultado (docs-only). **Nenhum cutover real foi
> executado.** A flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` permanece com
> default `OFF` em código e não foi ligada em nenhum ambiente persistente.
> Este documento fecha a fase D8.5B (limpeza controlada de dado live local) e
> abre a decisão de D8.5D.

## 1. Fase

D8.5B — CONTROLLED-CLEANUP-D8.4A-SMOKE-REQUISITION.

## 2. Objetivo

Remover de forma controlada a requisição smoke D8.4A `id=57`, sem restaurar
backup inteiro e sem alterar código.

## 3. Baseline Git

- branch `main`;
- HEAD `7a67c7e`;
- `origin/main...main = 0 0`;
- working tree limpo;
- `database.db` não rastreado.

## 4. `database.db` antes

- SHA256:
  `0A00BCC9779A5DBD57447BA72EC51C90D9FF981DEC046F581F4C67D61A2574CD`;
- tamanho: `544768` bytes.

## 5. Backup D8.5B

`D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.5B-cleanup-id57-20260620-231236.db`

- SHA256:
  `0A00BCC9779A5DBD57447BA72EC51C90D9FF981DEC046F581F4C67D61A2574CD`;
- tamanho: `544768` bytes;
- hash idêntico ao live antes do delete;
- fora do repositório;
- não rastreado pelo Git.

## 6. Auditoria pré-delete

- `PRAGMA foreign_keys=ON` confirmado;
- total `requisicoes=42`;
- snapshots `=14/14/14`;
- `id=57` existia;
- `nome_evento='D8.4A_SMOKE_LOCAL_WRITE_FLAG_ON'`;
- `aluno_id=1`;
- `atividade_id=1`;
- `status=Pendente`;
- `atividade_versao_id=2`;
- `codigo_normativo_snapshot=AAC-rev6`;
- exatamente `1` linha com `nome_evento LIKE '%D8.4A%'`;
- `0` anexos para `requisicao_id=57`;
- `0` alerta receipts para `requisicao_id=57`.

## 7. SQL executado

```sql
DELETE FROM requisicao_arquivos WHERE requisicao_id = 57;
DELETE FROM requisicao_alerta_receipts WHERE requisicao_id = 57;
DELETE FROM requisicoes WHERE id = 57 AND nome_evento = 'D8.4A_SMOKE_LOCAL_WRITE_FLAG_ON';
```

- executado dentro de transação explícita `BEGIN`/`COMMIT`.

## 8. Rowcounts

- `requisicao_arquivos`: `0`;
- `requisicao_alerta_receipts`: `0`;
- `requisicoes`: `1`;
- rollback guard não acionado.

## 9. Validação pós-delete

- total `requisicoes=41`;
- snapshots `=13/13/13`;
- `id=57` ausente;
- `0` linhas com `nome_evento LIKE '%D8.4A%'`;
- `requisicao_arquivos` total `=4` preservado;
- `requisicao_alerta_receipts` total `=38` preservado;
- `0` dependentes para `requisicao_id=57`.

## 10. Integridade

- `PRAGMA foreign_key_check` vazio;
- sem violações referenciais.

## 11. `database.db` depois

- SHA256:
  `1CA32F61553433E740E2B60B5428C56BC287ABB271ABB96680DD1320D17C5C80`;
- tamanho: `544768` bytes;
- sem `VACUUM`.

## 12. Nota sobre hash

O hash pós-delete não precisa voltar ao hash pré-D8.4A porque o SQLite não
compacta páginas liberadas sem `VACUUM`. O critério aceito foi integridade
lógica: `41` requisições, snapshots `13/13/13`, FK limpo e ausência da
`id=57`.

## 13. Backups

- backup D8.5B íntegro;
- backup D8.4A pré-smoke íntegro:
  `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`.

## 14. Estado Git final da D8.5B

- working tree limpo;
- `origin/main...main = 0 0`;
- `database.db` não rastreado;
- nenhum commit;
- nenhum push.

## 15. Riscos residuais

- `database.db` contém página livre por delete sem `VACUUM`, sem impacto
  funcional;
- `.venv` do projeto continua quebrado;
- cutover permanente da flag WRITE continua não autorizado;
- `.env` continua inexistente/intocado.

## 16. Conclusão

D8.5B aprovada.

## 17. Próxima etapa

D8.5D — final verify and push do closeout documental. Antes de D8.6/cutover,
decidir separadamente sobre:

- correção do `.venv`;
- plano de ativação controlada da flag;
- eventual `VACUUM`, somente se houver fase própria.
