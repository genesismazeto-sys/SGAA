# 06 — Deploy e infraestrutura (Pergunta 2)

> **Pergunta do dono:** a arquitetura (app + banco) está boa? Onde hospedar da
> forma mais simples e barata (~100 alunos), idealmente infra gratuita tipo
> Vercel, podendo pagar uma pequena quantia? Vale adaptar para Supabase/Vercel?

## Resposta curta

Para **~100 alunos**, a carga é baixíssima e a arquitetura **funciona bem como
está**. O ponto decisivo **não** é escala — é que o app é **stateful**: depende de
**filesystem persistente** e de **uma única instância**. Isso torna
**Vercel/serverless inadequado sem reescrever partes** do app.

**Recomendação:** hospedar em uma **plataforma com disco persistente e instância
sempre ligada** — **Render**, **Fly.io** ou uma **VPS** (~US$5/mês). Mantém o
SQLite, exige zero reescrita de banco, e custa pouco ou nada. Só migre para
**Postgres gerenciado (Supabase/Neon)** se/quando quiser múltiplas instâncias,
serverless de verdade, ou eliminar o risco de "arquivo único".

## Por que NÃO Vercel (do jeito atual)

Vercel é serverless (funções efêmeras, sem disco persistente entre invocações).
O app depende de coisas que serverless não oferece:

| Dependência do app | Onde no código | Problema no serverless |
|--------------------|----------------|------------------------|
| **SQLite em arquivo** (`database.db`) | `app/db.py` | Sem disco persistente; escritas se perdem; vários containers = vários bancos divergentes |
| **Uploads/documentos em disco** (`uploads/`, `documentos_alunos/`) | `app/student_documents.py`, `save_upload` | Arquivos somem entre invocações |
| **Backups locais** (`database.pre-*`, snapshots) | `db_maintenance` | Sem disco |
| **Sync de backup no `after_request`** | `main.py:5208` | I/O pesado por request; timeouts |
| **Rate limit em memória** | `app/auth.py` | Cada invocação é um processo novo → some |
| **Instância única / WAL** | SQLite WAL | SQLite não suporta múltiplos writers em rede |

Conclusão: rodar isso em Vercel exigiria trocar SQLite por Postgres, mover
uploads para storage de objetos (S3/R2), tirar o sync do request e mover
rate-limit para Redis. É um projeto à parte — **não compensa para 100 alunos**.

> Para o **front-end** o app também não combina com Vercel: não há SPA/Next.js;
> é HTML renderizado no servidor por Flask. Vercel brilha com front-ends
> estáticos/Next, não com apps Flask stateful.

## Dimensionamento (por que "simples" basta)

100 alunos, uso esporádico (abrir requisição, anexar PDF, consultar progresso).
Picos prováveis em prazos de entrega. Estimativa: dezenas de requests/min no
pico, escrita baixa. **Um container pequeno (256–512 MB RAM, 1 vCPU
compartilhada) com waitress/gunicorn segura com folga.** O gargalo nunca será CPU
ou banco — será garantir **persistência e backup**.

## Opções recomendadas (da mais simples à mais robusta)

### Opção A — VPS barata (melhor custo-controle) ⭐ recomendada p/ custo mínimo
Ex.: Hetzner (~€4/mês), Contabo, DigitalOcean (US$4–6/mês), Oracle Cloud Free
Tier (grátis, com ressalvas de disponibilidade).
- **Banco:** SQLite fica no disco da VPS (persistente). ✅ zero mudança.
- **Servir:** `gunicorn`/`waitress` + **Caddy** ou **Nginx** como proxy reverso
  com **HTTPS automático** (Caddy faz Let's Encrypt sozinho). Lembre de
  `TRUST_PROXY_XFF=1` atrás do proxy.
- **Sempre ligado** (sem cold start), **disco persistente**, uploads OK.
- **Backup:** o app já faz backup para Google Drive/OneDrive; some uma cópia
  externa automática. Adicione um `cron` de cópia do `.db` por garantia.
- **Contras:** você administra o servidor (updates, segurança do SO). Com Caddy +
  systemd, é pouco trabalho.

### Opção B — Render (mais simples, "PaaS") ⭐ recomendada p/ simplicidade
- **Web Service** (Python) + **Persistent Disk** (a partir de ~US$1/GB·mês) onde
  ficam `database.db`, `uploads/`, `documentos_alunos/`.
- Deploy por `git push`; HTTPS e domínio automáticos; sempre ligado no plano pago
  (~US$7/mês). O plano **free dorme** após inatividade (cold start) e **não tem
  disco persistente** → use o plano pago para este app.
- **Quase zero reescrita:** só apontar `APP_DATABASE` e as pastas de upload para o
  disco montado, e usar `gunicorn` como start command.
- Cron Jobs do Render podem rodar o backup/sync **fora do request** (recomendado).

### Opção C — Fly.io (bom meio-termo)
- Roda um container (seu `Dockerfile`) com **Volume persistente** para o SQLite e
  uploads. Instância pequena cabe na faixa de poucos dólares/mês.
- HTTPS automático, regiões perto do Brasil (GRU/São Paulo).
- **Importante:** mantenha **1 instância** (SQLite não tolera múltiplos writers).
  Fly escala fácil — aqui você quer o oposto.

### Opção D — PythonAnywhere (mais "didático")
- Hospedagem Python com disco persistente; plano pago barato (~US$5/mês).
- Simples para Flask, bom para faculdade; menos flexível que as anteriores.

### Comparativo

| Critério | VPS (A) | Render (B) | Fly.io (C) | Vercel | Supabase/Neon (+host) |
|----------|:------:|:----------:|:----------:|:------:|:---------------------:|
| Mantém SQLite sem reescrever | ✅ | ✅ | ✅ | ❌ | ❌ (vira Postgres) |
| Disco persistente | ✅ | ✅ (pago) | ✅ (volume) | ❌ | n/a |
| Sempre ligado (sem cold start) | ✅ | ✅ (pago) | ✅ | ❌ | depende do host |
| Simplicidade de operar | 🟡 | ✅ | 🟡 | ✅ | 🟡 |
| Custo p/ 100 alunos | ~US$4–6 | ~US$7 | ~US$3–7 | (incompatível) | grátis-ish + host |
| Escala horizontal | ❌ | 🟡 | ✅ | ✅ | ✅ |

> Preços são aproximados (verifique os valores atuais de cada provedor). Para 100
> alunos qualquer um deles fica em "poucos dólares/mês" ou grátis.

## E o Supabase? Quando faz sentido

Supabase = **Postgres gerenciado** + Auth + Storage + APIs, com tier grátis
generoso. **Não** é onde você "roda o Flask" — é onde ficaria o **banco** (e,
opcionalmente, o storage de arquivos e o auth).

Faz sentido migrar o **banco** para Supabase/Neon **se** você quiser:
- rodar o app em **serverless/Vercel** ou em **múltiplas instâncias**;
- eliminar o risco de "arquivo SQLite único" (Postgres gerenciado tem backups,
  réplicas, point-in-time);
- usar o **Storage do Supabase** para uploads (resolve a dependência de disco).

**Custo da migração SQLite → Postgres** (estimativa média):
- Trocar a camada de conexão (`sqlite3` → `psycopg`/SQLAlchemy).
- Ajustar SQL específico de SQLite: `datetime('now')` → `now()`, `AUTOINCREMENT`
  → `SERIAL/IDENTITY`, `PRAGMA`/WAL (não existem), a collation custom
  `PTBR_NOACCENT` (no Postgres usa-se `unaccent` + `ILIKE`/`collate`), `BOOLEAN`
  como inteiro, e revisar os `ensure_*`/migrações.
- Mover uploads para Supabase Storage/S3 e tirar o sync do `after_request`.
- É um esforço real (não trivial), porém **não urgente** para 100 alunos.

**Recomendação sobre Supabase:** não migre agora só por migrar. Mantenha SQLite +
VPS/Render. **Deixe a migração para Postgres como "Fase 2 de infraestrutura"**,
para quando (a) o uso crescer, (b) você quiser alta disponibilidade, ou (c)
quiser ir serverless. Quando for, o refactor de [05](05_avaliacao_refactor.md)
(camada `repositories/` + `db/connection.py`) torna essa troca **muito** mais
fácil — outro motivo para fazer o refactor primeiro.

## Ajustes recomendados antes de subir em produção (qualquer host)

Independente do provedor escolhido:

1. **Servidor WSGI de produção.** Trocar `app.run()` por **gunicorn** (Linux) ou
   **waitress** (cross-platform). Adicionar ao `requirements.txt`. Use **1
   worker** enquanto o banco for SQLite (ou aceite as ressalvas de WAL).
2. **`APP_ENV=production`** + setar `APP_SECRET_KEY` forte, `TOKEN_ENCRYPTION_KEY`,
   `APP_PUBLIC_BASE_URL`. O `create_app` já valida e recusa subir sem isso. ✅
3. **HTTPS + proxy reverso** (Caddy/Nginx) e `TRUST_PROXY_XFF=1` para o rate-limit
   enxergar o IP real.
4. **Disco persistente** para `database.db`, `uploads/`, `documentos_alunos/`
   (apontar via `APP_DATABASE` e `APP_DOCUMENTOS_ALUNOS_FOLDER`).
5. **Tirar o backup/sync do `after_request`** e rodar como **cron/job agendado**
   (ex.: 1×/dia). Hoje roda em toda resposta — desnecessário e custoso.
6. **Backups redundantes:** manter o backup automático para Google Drive/OneDrive
   (já implementado) + cópia do `.db` no host. Testar o **restore** (existe rota).
7. **Logs:** já há `RotatingFileHandler`; garantir que a pasta `logs/` é gravável
   no host.
8. **Configurar os redirect URIs OAuth** (Google/Microsoft) para o domínio de
   produção (derivados de `APP_PUBLIC_BASE_URL`).

## Caminho recomendado (resumo de decisão)

```
Você quer o MAIS SIMPLES e barato, mantendo o que já funciona?
        │
        ├─ Topa administrar um Linux mínimo?  ── SIM ─► VPS + Caddy + gunicorn  (Opção A) ~US$4-6/mês
        │                                       └ NÃO ─► Render Web Service + Disk (Opção B) ~US$7/mês
        │
        └─ Vai precisar escalar / serverless / alta disponibilidade no futuro?
                 └─► Faça o refactor (doc 05) e depois migre o BANCO p/ Postgres
                     gerenciado (Supabase/Neon) + Storage p/ uploads.
```

**TL;DR:** a arquitetura está **boa para o seu tamanho**. Não vá para Vercel/
serverless agora — exigiria reescrever banco e storage sem benefício real para
100 alunos. Suba em **Render (mais simples)** ou **VPS barata (mais controle)**,
mantendo SQLite, com disco persistente e backup agendado. Guarde Supabase/Postgres
para depois do refactor, se e quando crescer.
