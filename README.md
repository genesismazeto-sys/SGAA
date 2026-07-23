# Sistema de Atividades Complementares (Flask)

Pequena aplicação Flask com SQLite para gestão de cursos, turmas, alunos, atividades e requisições.

## Requisitos

- Python 3.10+
- Windows PowerShell (ou bash)

## Setup

```powershell
# (opcional) criar venv
python -m venv .venv; .\.venv\Scripts\Activate.ps1

# instalar dependências
pip install -r requirements.txt

# (opcional) configurar variáveis de ambiente
$env:APP_SECRET_KEY = "troque-isto"
# $env:APP_DATABASE = "d:\\caminho\\para\\database.db"
# $env:APP_LOCAL_BACKUP_DIR = "d:\\caminho\\para\\backups-locais"
# $env:APP_CLOUD_BACKUP_DIR = "D:\\DriveFaculdade\\AtividadesComplementares\\database-backups"
# $env:APP_CLOUD_SYNC_INTERVAL_SECONDS = "300"
# $env:SESSION_COOKIE_SECURE = "1"   # se rodar em HTTPS

# executar
python .\main.py
```

A aplicação inicializa o banco automaticamente (init_db) ao subir.


Rotas úteis:
- /health → status do app (200 ok)
- /login → tela de autenticação
- /uploads/<arquivo> → serve anexos enviados (com cabeçalhos de segurança)

## Novidades desta revisão

- Configuração via variáveis de ambiente (chave secreta, banco, cookies de sessão)
- Uploads mais seguros: validação de extensão, nomes únicos e sanitizados
- Correção no join de pendências em `admin_alunos`
- Melhorias de performance no SQLite: WAL + índices
- Versionamento formal de schema com baseline para migrações futuras
- Área admin para backup/restauração do banco com snapshots locais e sincronização para pasta em nuvem
- Handlers de erro 404/500 e rota `/health`

## Estrutura rápida

- `main.py` – app Flask e rotas
- `app/db_maintenance.py` – versionamento do schema, snapshots e restauração segura
- `templates/` – páginas HTML (Jinja)
- `static/` – CSS/JS/Imagens
- `uploads/` – arquivos enviados (criado automaticamente)

## Dicas

- Log em `app.log`
- Painel admin de banco: `/admin/banco-dados`
- A sincronização em nuvem usa snapshots consistentes do SQLite; a pasta configurada em `APP_CLOUD_BACKUP_DIR` deve ser uma pasta já sincronizada pelo drive institucional.
- A restauração cobre os dados do banco. Arquivos enviados em `uploads/` permanecem fora desse backup básico.
- Em produção, execute com um servidor WSGI (gunicorn/uwsgi) atrás de um proxy e defina `SESSION_COOKIE_SECURE=1`.
- Uploads permitidos: anexos (pdf, png, jpg, jpeg), CSV (.csv) e Excel (.xlsx). Outros tipos serão rejeitados.
- Tamanho máximo de upload: 16MB (erro amigável será exibido).

## Teste rápido (smoke tests)

```powershell
# do diretório src
python .\tools\smoke_test.py          # health e login (GET)
python .\tools\smoke_test_admin.py    # login admin e dashboard
```

## Ferramentas de desenvolvimento (opcional)

```powershell
# instalar ferramentas de dev
pip install -r requirements-dev.txt

# rodar tarefas do VS Code (Ctrl+Shift+B)
# - Run: App
# - Test: Smoke / Smoke Admin
# - Lint: flake8
# - Format: black
```

## Problemas comuns

- "Arquivo muito grande": reduza para <16MB (ou ajuste MAX_CONTENT_LENGTH se necessário).
- "Extensão não permitida": consulte a lista de extensões aceitas acima.
- Banco em caminho diferente: defina APP_DATABASE para apontar para outro .db.
