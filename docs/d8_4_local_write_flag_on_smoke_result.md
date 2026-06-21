# D8.4 — Resultado do smoke local com write flag ON no database.db live

> Documento de registro de resultado (docs-only). **Nenhum cutover real foi
> executado.** A flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` permanece com
> default `OFF` em código e não foi ligada em nenhum ambiente persistente.
> Este documento fecha a fase D8.4A (smoke supervisionado contra o
> `database.db` local live) e abre a decisão de D8.4C.

## 1. Fase

D8.4A — LOCAL-WRITE-FLAG-ON-SUPERVISED-SMOKE.

## 2. Objetivo

Validar `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=1` em processo local
supervisionado, usando o `database.db` local live (não uma cópia), com
backup fresco prévio verificado, sem tornar a flag permanente e sem alterar
`.env`.

## 3. Baseline Git

- branch `main`;
- HEAD `5a39161` (`Record D8.3A copy database write flag smoke`);
- `origin/main...main = 0 0`;
- working tree limpo;
- `database.db` não rastreado (`git ls-files database.db` vazio).

## 4. Baseline do `database.db` live (antes)

- tamanho: `544768` bytes;
- SHA256: `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`
  — confirmado idêntico ao hash esperado antes de qualquer escrita.

## 5. Backup fresco

`D:\OneDrive\Programação\SGAA_database_backups\database.pre-D8.4A-local-write-flag-on-20260620-212052.db`

- tamanho: `544768` bytes;
- SHA256: `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`;
- hash idêntico ao live antes da escrita (validado também por assert no
  próprio script do smoke, antes de tocar no live);
- fora do repositório (`SGAA_database_backups`, diretório irmão do
  worktree);
- não rastreado pelo Git.

## 6. Como a flag foi ligada

- `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=1` definida via `os.environ`
  **somente dentro do processo Python** que executou o smoke;
- script do smoke armazenado fora do repositório, em
  `SGAA_database_backups\d8_4a_smoke.py`;
- sem export persistente no shell, sem variável de ambiente de sistema,
  sem `.env`.

## 7. Ambiente auxiliar

- o `.venv` do projeto estava quebrado (`pyvenv.cfg` apontava para uma
  instalação Python 3.13 removida da máquina; só restava Python 3.11 sob
  `uv python`);
- para executar o smoke sem alterar código/schema/`.env`, foi criado um
  venv Python 3.11 descartável **fora do repositório**:
  `SGAA_database_backups\d84a_runtime_venv`;
- dependências instaladas nesse venv externo a partir do
  `requirements.txt` do projeto (mais `brotli`, exigido em runtime por
  `flask-compress`);
- nenhum arquivo do repositório foi criado ou alterado por essa correção
  de ambiente; o `.venv` original do projeto permanece intocado (e ainda
  quebrado, fora do escopo desta fase).

## 8. Contagens iniciais no live (antes de qualquer escrita do smoke)

- `41` requisições;
- `13` com `atividade_versao_id`;
- `13` com `codigo_normativo_snapshot`;
- `13` com `regra_snapshot_json`.

## 9. Caso válido selecionado

- aluno `id=1`;
- `turma_id=1`;
- turma `PPA-T11`;
- `matriz_id=1`;
- `curso_id=2`;
- atividade legacy `id=1`.

## 10. Resultado do resolver

- `status=resolved`;
- `atividade_versao_id=2`;
- `codigo_normativo=AAC-rev6`;
- `eixo=AAC`;
- `matriz_id_efetiva=1`;
- `legacy_scope_ok=True`;
- `warnings=[]`.

## 11. Criação local com WRITE ON

- `POST /aluno/nova-requisicao` via rota real de aluno (test client +
  sessão autenticada, fluxo idêntico ao usado em produção);
- HTTP `302`;
- `nome_evento=D8.4A_SMOKE_LOCAL_WRITE_FLAG_ON`;
- requisição criada `id=57` no `database.db` live.

## 12. Campos versionados gravados

- `atividade_versao_id=2`;
- `codigo_normativo_snapshot=AAC-rev6`;
- `regra_snapshot_json` preenchido;
- `schema_version=d6.4.0-v1`;
- `eixo=AAC`;
- `grupo="1 - Atividades fora da Faculdade"`;
- `numero_versao=2`;
- coerente com a linha real de `atividade_versao id=2` no banco.

## 13. Guard de edição

- tentativa de troca de `atividade_id` (`1`→`2`) na requisição `id=57`
  bloqueada;
- HTTP `200` (re-render do formulário) com mensagem visível:
  "Esta solicitação já possui versão normativa registrada";
- `atividade_id` inalterado;
- `atividade_versao_id` inalterado;
- `codigo_normativo_snapshot` inalterado;
- `regra_snapshot_json` inalterado;
- `nome_evento` inalterado;
- rejeição atômica confirmada (nenhum outro campo foi aplicado).

## 14. Caso skip

- não exercitado no `database.db` live, por decisão deliberada;
- não havia candidato natural seguro (turma sem `matriz_id` explícito)
  já existente no live;
- o contrato da fase prefere não criar curso/turma artificial no live;
- skip já validado em cópia isolada na D8.3A (`docs/d8_3_copy_db_write_flag_smoke_result.md`,
  seção 15).

## 15. Contagens finais no live (depois do smoke)

- `42` requisições;
- `14` com `atividade_versao_id`;
- `14` com `codigo_normativo_snapshot`;
- `14` com `regra_snapshot_json`;
- delta exato de `+1` em cada métrica, consistente com a única linha
  criada (`id=57`).

## 16. `database.db` live (depois)

- SHA256: `0A00BCC9779A5DBD57447BA72EC51C90D9FF981DEC046F581F4C67D61A2574CD`;
- tamanho: `544768` bytes (inalterado em bytes);
- hash mudou exatamente como esperado, em consequência da criação da
  requisição smoke.

## 17. Escopo da mutação no banco

- somente a tabela `requisicoes` foi alterada (`41`→`42`);
- a linha `id=57` é a única com `nome_evento LIKE '%D8.4A%'`;
- `requisicao_arquivos` não recebeu nenhuma linha nova (nenhum
  comprovante anexado no smoke);
- tabelas auxiliares (`alunos`, `turmas`, `cursos`, `usuarios`,
  `atividade_versao`, `matrizes_atividades_itens`) não foram tocadas pelo
  fluxo de criação.

## 18. Backup pós-smoke

- re-verificado após o smoke: SHA256
  `CF9FBF5C36900AA7E01DB150051BD81B2E4822764E946CBC188B0A91CBB635E6`,
  `544768` bytes — idêntico ao estado original, intacto.

## 19. Estado Git pós-smoke

- `git status --short` vazio;
- `origin/main...main = 0 0`;
- `database.db` continua não rastreado;
- nenhum commit criado pelo smoke;
- nenhum push;
- `.env` continua inexistente/intocado.

## 20. Decisão sobre artefatos

- manter a requisição smoke `id=57` no `database.db` live por enquanto,
  como evidência;
- manter o backup fresco
  `database.pre-D8.4A-local-write-flag-on-20260620-212052.db`;
- manter o script `d8_4a_smoke.py` (fora do repositório, em
  `SGAA_database_backups`);
- não remover nada antes de uma fase própria de limpeza/restauração, se
  e quando houver decisão explícita para isso.

## 21. Conclusão

D8.4A aprovada. O smoke validou, diretamente contra o `database.db` local
live (com backup fresco prévio e flag ligada apenas no processo), que
`SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=ON` produz snapshot coerente no
caso válido e é bloqueado corretamente na edição quando o snapshot já
existe — com mutação no banco limitada exatamente à linha esperada.

## 22. Limite

D8.4A não autoriza cutover permanente. `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE`
continua `OFF` por padrão em código. `.env` continua inexistente/intocado.

## 23. Próxima fase recomendada

D8.4C — final verify and push do closeout documental. Depois disso,
decisão explícita entre:

- manter `id=57` como evidência;
- ou abrir fase própria de cleanup/restauração;
- ou planejar ativação controlada mais ampla.
