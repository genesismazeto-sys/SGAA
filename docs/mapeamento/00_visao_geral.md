# 00 — Visão geral

## O que é o app

**SGAA** — sistema web para gestão de **Atividades Acadêmicas Complementares
(AAC)** e **Atividades de Extensão Universitária (AEU)**. Alunos abrem
requisições de horas (com comprovante anexado), e a coordenação/admin defere,
indefere, defere parcialmente ou devolve. O sistema controla limites de horas
por atividade, por curso e por matriz, com **versionamento normativo** das
atividades (quando a norma muda, versões antigas continuam valendo para quem já
estava sob elas).

Público: ~100 alunos de uma faculdade. Custo de operação alvo: ~zero (ou poucos
dólares/mês).

## Stack técnico

| Camada | Tecnologia |
|--------|-----------|
| Linguagem | Python 3 (10+) |
| Web framework | Flask 3.1 |
| Templating | Jinja2 (HTML renderizado no servidor) |
| Front-end | HTML + CSS próprio + JavaScript vanilla (sem React/Vue/build step) |
| Banco | **SQLite** (arquivo `database.db`, modo WAL) |
| Auth | Sessão Flask (cookie assinado) + RBAC próprio. `Flask-Login` está no requirements mas o controle real é manual via `session` |
| CSRF | Flask-WTF (`CSRFProtect`) + auto-injeção de token nos forms |
| Senhas | Werkzeug `pbkdf2:sha256:600000` (com suporte a hashes legados) |
| Compressão | Flask-Compress |
| Integrações | Google Drive (google-api-python-client) e OneDrive (MSAL) p/ backup |
| Criptografia | `cryptography` (Fernet) p/ criptografar tokens OAuth no banco |
| Testes | pytest (70 arquivos de teste) |

### Dependências (`requirements.txt`)

```
flask==3.1.1            unidecode==1.4.0        openpyxl==3.1.2
werkzeug==3.1.3         Flask-Compress==1.14    Flask-Login==0.6.3
Flask-WTF==1.2.2        python-dotenv==1.0.1    requests==2.32.3
PyYAML==6.0.2           cryptography==45.0.7    msal==1.31.1
google-api-python-client==2.169.0  google-auth==2.40.2
google-auth-oauthlib==1.2.2        google-auth-httplib2==0.2.0
```

> Não há servidor WSGI de produção (gunicorn/waitress) listado — hoje roda no
> servidor de desenvolvimento do Flask. Ver [06](06_deploy_e_infraestrutura.md).

## Como roda

- **Entrypoint:** `main.py`. No fim do arquivo (`if __name__ == "__main__":`)
  chama `app.run(...)`. O objeto `app` é criado em
  `main.py:4589` via `app = create_app(...)`, definido em
  [`app/__init__.py`](../../app/__init__.py).
- **Windows/dev:** `run.bat` ativa o `.venv`, checa a porta 5000, abre o
  navegador no `/login` e roda `python main.py`.
- **Variáveis de ambiente:** ver `.env.example`. Principais:
  - `APP_ENV` = `development` | `production` | `testing`
  - `APP_SECRET_KEY` (obrigatória e forte em produção)
  - `APP_PUBLIC_BASE_URL` (deriva os callbacks OAuth)
  - `TOKEN_ENCRYPTION_KEY` (Fernet, obrigatória em produção p/ tokens de nuvem)
  - `GOOGLE_*`, `MS_*` (credenciais OAuth de backup)
  - `APP_DATABASE` (caminho do SQLite; default `./database.db`)
  - flags de sessão/CSRF/rate-limit (ver `create_app`)

### Comportamento por ambiente (`APP_ENV`)

`create_app` muda postura de segurança conforme o ambiente:

- **production:** exige `APP_SECRET_KEY` forte; cookies `Secure`; HSTS ligado;
  exige `TOKEN_ENCRYPTION_KEY` e `APP_PUBLIC_BASE_URL`; proíbe `DEBUG`; sessão de
  8h; **não** semeia admin padrão a menos que `APP_BOOTSTRAP_ADMIN_PASSWORD`.
- **development:** secret efêmera, sessão 24h, semeia admin `admin@ej.edu.br` /
  `admin123`.
- **testing:** CSRF desabilitado (para a suíte de testes).

## Estatísticas do código

| Métrica | Valor |
|---------|-------|
| LOC Python (sem `.venv`) | ~54.000 |
| **`main.py`** | **15.494 linhas** (≈ 631 KB) |
| `app/views/aluno.py` | 2.119 linhas |
| `utils/messages.py` | 998 linhas |
| `services/onedrive_service.py` | 563 linhas |
| Templates Jinja | 71 arquivos, ~21.000 linhas |
| Maiores templates | `admin_banco_dados.html` (2.114), `admin_requisicoes.html` (1.849), `admin_matriz_form.html` (1.238) |
| Arquivos de teste | 70 |
| Rotas (`@app.route` em main.py) | 113 (+ blueprints) |
| Tabelas no banco | 32 |
| Arquivos versionados no git | 210 |

## Estrutura de pastas

```
SGAA_clean_baseline/
├── main.py                  # ★ Monólito: app object, ~113 rotas, regras, schema helpers
├── presets_api.py           # Blueprint: API de presets de respostas/e-mails
├── app/                     # Pacote parcialmente modularizado
│   ├── __init__.py          # create_app() — bootstrap, segurança, CSRF, blueprints
│   ├── auth.py              # RBAC: níveis, recursos, escopos, decorators, rate limit
│   ├── db.py                # Conexão SQLite + init_db (chama helpers de main.py!)
│   ├── db_maintenance.py    # Migrações de schema, snapshots, retenção, sync nuvem
│   ├── cloud_drives.py      # Abstração de contas de nuvem (Google/OneDrive)
│   ├── student_documents.py # Salvamento/validação de documentos de aluno
│   ├── views/
│   │   ├── core.py          # login / logout / index
│   │   └── aluno.py         # Blueprint do aluno (dashboard, requisições, etc.)
│   └── services/
│       ├── backup_service.py        # Zip de backup do SQLite
│       ├── google_drive_service.py  # OAuth + upload Google Drive
│       └── token_encryption.py      # Fernet p/ tokens OAuth
├── services/                # (fora do pacote app) integrações externas
│   ├── onedrive_service.py  # OAuth + upload OneDrive (MSAL)
│   └── oauth_config.py      # Resolução de redirect URIs / base URL
├── utils/
│   ├── messages.py          # Mensagens editáveis (overrides em banco) + flash
│   └── flash.py             # helpers de flash
├── templates/               # 71 templates Jinja (admin_*, aluno_*, base*, components/)
├── static/                  # css/ js/ images/ (sem build step)
├── tools/                   # Scripts utilitários (seed, smoke tests, migrações pontuais)
├── tests/                   # 70 arquivos pytest
├── docs/                    # Documentação operacional (D6/D8 ops, auditorias) + esta pasta
├── uploads/                 # Comprovantes/uploads (gitignored, precisa persistir)
├── documentos_alunos/       # Documentos de alunos (gitignored, precisa persistir)
├── logs/                    # Logs rotativos (gitignored)
├── database.db              # Banco SQLite (gitignored)
└── database.pre-*.db        # Snapshots manuais de migrações antigas (poluindo a raiz)
```

## Fluxo de uma requisição HTTP (request lifecycle)

1. **`before_request` → `enforce_admin_access_control`** (`main.py:5248`): se o
   usuário é admin, verifica a permissão (recurso/escopo) exigida pelo endpoint.
   Se não tiver, 403 (ou redirect ao dashboard).
2. **View** roda (em `main.py`, ou no blueprint `aluno`/`presets`/`core`). Pega
   conexão via `g.db` (uma por request).
3. **`after_request`** (dois hooks):
   - `add_security_headers` (`main.py:5208`): injeta headers **e dispara um
     possível sync de snapshot do banco para a nuvem em TODA resposta**
     (`_maybe_sync_database_snapshot`). ⚠️ ver nota abaixo.
   - `_apply_security_headers` (`app/__init__.py:340`): CSP, HSTS, e
     **auto-injeção de `<input csrf_token>`** em todo `<form method=post>` do HTML.
4. **`teardown_appcontext`** fecha a conexão SQLite.

> ⚠️ **Nota de arquitetura:** o backup/sync para nuvem ser disparado dentro do
> `after_request` de cada resposta é uma decisão que tem custo de latência e
> acopla persistência a I/O externo. É um dos pontos discutidos em
> [04](04_arquitetura_e_modulos.md) e [06](06_deploy_e_infraestrutura.md).

## Domínios de negócio (mapa mental)

- **Identidade:** `usuarios` (admin/aluno) ↔ `alunos` (perfil do aluno).
- **Acadêmico:** `cursos` → `turmas` → `alunos`; cada turma aponta para uma
  `matriz` de atividades.
- **Catálogo de atividades:** modelo **legado** (`atividades`) convivendo com o
  modelo **versionado** (`atividade_base` → `atividade_versao` ← `norma_atividade`,
  ligados a matrizes via `matriz_atividade_versao_item`). Há tabelas de
  transição/mapeamento (`atividade_transicao`, `atividade_legacy_map`).
- **Operação:** `requisicoes` (+ `requisicao_arquivos`, snapshots normativos),
  `reportes` (alunos reportam bugs), `admin_alertas`, `admin_arquivos`.
- **Sistema:** `configuracoes_app`, `configuracoes_backup`, `configuracoes_acesso`,
  `mensagens_editaveis`, `cloud_accounts`, `backup_logs`, `schema_migrations`.

Ver detalhes em [03_banco_de_dados.md](03_banco_de_dados.md).
