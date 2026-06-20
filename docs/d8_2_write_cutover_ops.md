# D8.2 — Contrato de edição após snapshot e plano de cutover de write

> Documento de planejamento operacional. **Nenhum cutover foi executado.**
> A flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` permanece com default `OFF`
> e não foi ligada em produção.

## D8.2B — Contrato de edição do aluno após snapshot versionado (implementado)

### Regra

Quando uma requisição **já possui** snapshot versionado registrado no momento
da criação, o aluno **não pode trocar a atividade** durante a edição.

Detecção de snapshot presente (qualquer um dos campos preenchido):

- `requisicoes.atividade_versao_id IS NOT NULL`, ou
- `requisicoes.codigo_normativo_snapshot` não vazio, ou
- `requisicoes.regra_snapshot_json` não vazio.

### Comportamento

- **Troca de atividade com snapshot presente:** rejeitada de forma atômica.
  A rota faz `flash(...)` + `redirect` para o detalhe da requisição, **antes**
  de qualquer escrita no banco ou gravação de anexo. Nada é atualizado.
  - Mensagem: *"Esta solicitação já possui versão normativa registrada. Para
    trocar a atividade, crie uma nova solicitação."*
- **Demais edições (nome do evento, horas, data, observação, anexos):**
  continuam permitidas normalmente quando a atividade **não** é trocada.
- **Requisições sem snapshot:** preservam o comportamento legado de troca de
  atividade, mantida a validação de atividade permitida pela matriz da turma.

### Por que não recalcular nem limpar o snapshot em edição

- O snapshot é um **registro imutável do momento da criação** (carimbo
  normativo). Recalcular na edição reabriria a porta para divergência entre o
  que o aluno viu ao criar e o que passaria a valer depois.
- Limpar o snapshot apagaria evidência histórica já exibida ao aluno (bloco
  "Versão normativa registrada") e ao admin (diagnóstico read-only).
- A decisão operacional de deferimento continua no caminho legado
  `requisicoes.atividade_id -> atividades.id`. Bloquear a troca de atividade
  preserva a coerência entre o snapshot exibido e a atividade da requisição,
  sem mexer no resolver, no writer ou no deferimento.

### Escopo do código

- Alterado: `app/views/aluno.py` (rota ativa de edição da requisição do aluno).
- `main.py`, schema, migrations, `database.db`, resolver, writer
  (`maybe_write_versioned_requisicao_snapshot`), shadow read e telas de admin
  **não** foram alterados.
- A flag de write permanece `OFF` por padrão; os testes a ligam apenas via
  `monkeypatch`, nunca no ambiente.

### Cobertura de teste (`tests/test_aluno_requisicao_versioned_readonly.py`)

- T01 — snapshot presente: trocar atividade é bloqueado (rejeição atômica,
  flash observável, atividade e snapshot inalterados).
- T02 — snapshot presente: edições não estruturais seguem permitidas.
- T03 — sem snapshot: troca de atividade continua permitida (legado).
- T04 — `aluno_create` com WRITE ON e resolvedor não-resolvido: cria sem
  snapshot, não bloqueia, GET detalhe não quebra.
- T05 — exceção no resolvedor não bloqueia a criação.
- T06 — regressão D8.1B: bloco no detalhe e chip `vN` na lista.

## Sequência futura recomendada (não executada)

O cutover real do write **não faz parte** desta fase. Quando autorizado, seguir
a ordem abaixo, sem pular etapas:

1. **Smoke em cópia do banco.** Copiar `database.db` para um arquivo de
   trabalho; ligar `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE=1` apenas no
   ambiente da cópia; criar requisições controladas (`aluno_create` e
   `admin_create`); validar `atividade_id`, `atividade_versao_id`,
   `codigo_normativo_snapshot`, `regra_snapshot_json`, `/aluno/dashboard` 200 e
   `/admin/requisicoes` 200; descartar a cópia. **Sem write no banco live.**
2. **Flag ON em ambiente local.** Ativação controlada no ambiente local, com
   `SGAA_VERSIONED_RESOLVER_SHADOW_READ=1` para auditoria paralela; validar e
   fazer rollback (`...WRITE=0`).
3. **Backup fresco do live.** Antes de qualquer ativação no ambiente alvo,
   criar backup nomeado pela fase, fora do worktree e não versionado.
4. **Cutover real só em fase posterior e explícita**, com rollback documentado
   (voltar a flag para `0`; manter snapshots já gravados; sem backfill reverso).

Referência operacional detalhada do writer: `docs/d6_4_snapshot_write_ops.md`.
