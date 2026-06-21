# 02 — Autenticação e segurança

> Veredito rápido: **a postura de segurança deste app é boa e madura** — RBAC
> granular, CSRF abrangente, PBKDF2 forte, rate limiting, headers e CSP, sessões
> endurecidas em produção. Os pontos de atenção são operacionais (estado em
> memória, sync em `after_request`), não falhas graves.

## 1. Autenticação (quem é você)

- **Mecanismo:** sessão Flask (cookie assinado com `SECRET_KEY`). Não há JWT nem
  OAuth para login de usuário — OAuth só é usado para backup em nuvem.
- **Login:** `app/views/core.py::login`. Fluxo:
  1. Rate limit por IP **e** por conta (`_login_rate_limited`).
  2. Busca `usuarios` por e-mail (somente leitura — evita DoS em pré-auth).
  3. `check_password()` valida; se o hash for legado, re-hashifica para PBKDF2.
  4. Normaliza `nivel_acesso` vs `tipo` (corrige contaminação histórica).
  5. `session.clear()` + grava `user_id`, `user_type`, `user_name`,
     `access_level`, `perfil`, eventualmente `foto_perfil`.
  6. `session.permanent = remember_me` (lembrar-me).
  7. Redireciona: admin → `admin_dashboard`; aluno → `aluno.aluno_dashboard`.
- **Logout:** `session.clear()` + redirect para login.
- **Chaves de sessão usadas:** `user_id`, `user_type` (`admin`|`aluno`),
  `user_name`, `access_level`, `perfil`, `foto_perfil`.

### Senhas (`main.py:250-294`)

- **Hash atual:** Werkzeug `generate_password_hash(method="pbkdf2:sha256:600000")`
  — PBKDF2-SHA256 com 600k iterações. **Forte e adequado.**
- **Legado:** formato antigo `base64(salt)$base64(sha256(salt+senha))` ainda é
  aceito em `check_password` via `_check_password_legacy` (comparação em tempo
  constante com `secrets.compare_digest`), e migrado no próximo login.
- O comentário no topo de `main.py` ("Substituindo bcrypt por hashlib") é
  **enganoso/desatualizado** — o caminho real usa Werkzeug PBKDF2, não hashlib cru.

### Rate limiting de login (`app/auth.py:440`)

- Janela e limites configuráveis: `LOGIN_MAX_ATTEMPTS` (IP, default 10),
  `LOGIN_ACCOUNT_MAX_ATTEMPTS` (conta, default 8), `LOGIN_WINDOW_SECONDS` (600s).
- ⚠️ **Estado em memória do processo** (`_login_attempts`, dicionários módulo).
  Em deploy **multi-worker** (gunicorn -w N) ou multi-instância, cada worker tem
  seu próprio contador → o limite efetivo multiplica por N. O próprio código
  comenta: "considerar backend externo (Redis)". Relevante para [06](06_deploy_e_infraestrutura.md).
- IP de cliente: `X-Forwarded-For` só é confiado se `TRUST_PROXY_XFF=1` (correto —
  evita spoofing do header atrás de proxy).

## 2. Autorização / RBAC (o que você pode fazer)

Modelo de permissões definido em [`app/auth.py`](../../app/auth.py). É um RBAC de
**dois eixos**: nível de acesso (papel) × recurso × escopo.

### Tipos de usuário (`usuarios.tipo`)

`admin` ou `aluno`. Determina o "mundo" (área admin vs área aluno) e os
decorators `admin_required` / `aluno_required`.

### Níveis de acesso (`usuarios.nivel_acesso`)

| Nível | Rótulo | user_type | Escopos padrão |
|-------|--------|-----------|----------------|
| `admin_total` | Admin | admin | `full` em **todos** os recursos |
| `administrativo` | Coordenador | admin | `full` em tudo, **exceto** recursos de segurança (`none`) |
| `consultivo` | Consultor | admin | `view` em tudo (e `edit` só em `meus_dados`), `none` em segurança |
| `usuario` | Usuário | aluno | (sem RBAC admin) |
| `usuario_teste` | Usuário teste | aluno | (sem RBAC admin) |

"Recursos de segurança" = `banco_dados`, `acesso`, `configuracoes`, `mensagens`
(`SECURITY_RESTRICTED_RESOURCES`). Só `admin_total` os acessa por padrão.

Há **aliases** robustos de normalização (`ACCESS_LEVEL_ALIASES`,
`canonicalize_access_level`) que aceitam variações como "administrador",
"coordenador", "consultora", etc. — defensivo contra dados inconsistentes.

### Recursos (módulos protegidos)

`dashboard`, `requisicoes`, `atividades`, `matrizes`, `alunos`, `turmas`,
`cursos`, `arquivos`, `alertas`, `reportes`, `banco_dados`, `acesso`,
`configuracoes`, `mensagens`, `meus_dados` (ver `ACCESS_RESOURCES_META`).

### Escopos (níveis de permissão por recurso)

Ordenados: `none` < `view` < `edit` < `full` (`ACCESS_SCOPE_RANK`).
`permission_scope_satisfies(atual, exigido)` compara o rank.

### Overrides por usuário

A tabela `usuarios_permissoes_acesso (usuario_id, recurso, escopo)` permite
**sobrescrever** o escopo padrão do nível para um usuário específico. Resolução:
`merge_resource_scopes(nivel, overrides)` → escopos efetivos.

### Como a permissão é aplicada (enforcement)

1. `get_admin_permission_requirement(endpoint, method)` (`app/auth.py:214`)
   mapeia cada endpoint admin → `(recurso, escopo_exigido)`. É um grande `if/elif`
   por nome de endpoint. **Esta é a fonte de verdade do RBAC de rotas.**
2. `before_request` → `enforce_admin_access_control` (`main.py:5248`):
   - Só age se `session.user_type == "admin"`.
   - Carrega contexto de acesso do usuário (`_get_current_admin_access_context`).
   - Se `_admin_can(recurso, escopo)` falhar → 403 (JSON p/ AJAX) ou redirect.
3. `context_processor` `inject_admin_access_helpers` (`main.py:5264`) expõe nos
   templates: `auth_can(recurso, escopo)`, `auth_scope(recurso)`,
   `auth_current_can_edit/full`, etc. → a UI esconde botões sem permissão.

> ⚠️ **Acoplamento crítico para o refactor:** o RBAC casa por **nome de endpoint
> sem prefixo de blueprint** (ex.: `admin_requisicoes`). Se você mover rotas para
> blueprints, os endpoints viram `admin.requisicoes` e o mapa de permissões
> **para de casar silenciosamente** (a função retorna `None` → libera geral).
> Tem que atualizar `get_admin_permission_requirement` em conjunto e cobrir com
> teste. Ver [05](05_avaliacao_refactor.md).

### Permissões da área aluno

A área aluno **não** usa o mapa de recurso/escopo — basta `@aluno_required`
(estar logado como aluno). A autorização fina (ex.: aluno só vê/edita as próprias
requisições, e só edita enquanto `Pendente`/`Devolvida`) é feita **dentro de cada
view** (`can_student_edit_requisition`, `can_student_delete_requisition` em
`main.py`, e checagens de `aluno_id` no blueprint).

## 3. CSRF

- **Flask-WTF `CSRFProtect`** inicializado em `create_app` (`csrf.init_app(app)`).
- **Auto-injeção:** o `after_request` `_apply_security_headers`
  (`app/__init__.py:340`) varre o HTML de resposta e injeta
  `<input type="hidden" name="csrf_token">` em **todo `<form method=post>`** que
  ainda não tenha, e também um `<meta name="csrf-token">` no `<head>` para AJAX.
  → forms não precisam lembrar de incluir o token manualmente.
- **`/csrf-token`** (GET, autenticado): endpoint para o JS refrescar o token sem
  recarregar a página (`static/js/csrf-shim.js`), evitando o erro 400 "página
  desatualizada".
- **Tempo de vida do token** acompanha a vida da sessão (corrige bug histórico em
  que o token expirava antes da sessão).
- **Isenções:** `/login` (sessão ainda não estabelecida no 1º POST) e os GETs de
  callback OAuth.
- **Erro de CSRF:** handler dedicado loga diagnóstico (método, path, motivo,
  referrer, user) **sem vazar o token** e renderiza `400.html` amigável.
- **Em `testing`:** CSRF desligado (`WTF_CSRF_ENABLED=False`).
- Há testes dedicados: `test_csrf_*` (inventário, fluxos críticos admin, e2e).

## 4. Sessão e cookies (`create_app`)

| Config | development | production |
|--------|-------------|-----------|
| `SECRET_KEY` | efêmera (token aleatório) | **obrigatória**, ≥24 chars, não pode ser valor público conhecido |
| `SESSION_COOKIE_HTTPONLY` | True | True |
| `SESSION_COOKIE_SAMESITE` | `Lax` (configurável) | `Lax` |
| `SESSION_COOKIE_SECURE` | configurável (default off) | **forçado True** |
| `PERMANENT_SESSION_LIFETIME` | 24h | 8h |
| HSTS | off | on (`max-age=31536000; includeSubDomains`) |

Em produção, `create_app` **se recusa a subir** se: `SECRET_KEY` fraca/ausente,
`DEBUG` ligado, `TOKEN_ENCRYPTION_KEY` ausente, ou `APP_PUBLIC_BASE_URL` não
resolvível (`_validate_production_runtime_settings`). Isso é um bom guard-rail.

## 5. Headers de segurança

Aplicados em dois `after_request` (há sobreposição entre `main.py` e
`app/__init__.py`):

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- `Referrer-Policy` (⚠️ **divergência:** `main.py` usa
  `no-referrer-when-downgrade`; `app/__init__.py` usa
  `strict-origin-when-cross-origin`. Vale unificar.)
- `Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=(), usb=()`
- `Strict-Transport-Security` (só produção)
- **CSP** (`Content-Security-Policy`) — configurável via env, default permite
  `'unsafe-inline'` em scripts/estilos e libera domínios Google (Picker/OAuth) e
  `unpkg.com`. (⚠️ `'unsafe-inline'` em `script-src` enfraquece a CSP — melhoria
  futura: nonces/hashes.)
- HTML autenticado recebe `Cache-Control: no-store` (evita cache em máquinas
  compartilhadas).

## 6. Criptografia de tokens OAuth

Tokens das contas de nuvem (`cloud_accounts.token_json`) são **criptografados em
repouso com Fernet** (`app/services/token_encryption.py`), usando
`TOKEN_ENCRYPTION_KEY`. Em produção a chave é obrigatória; o app valida na
inicialização.

## 7. Upload de arquivos

- `MAX_CONTENT_LENGTH = 16 MB` (geral); restore de backup até 128 MB
  (configurável).
- `secure_filename` + extensões permitidas + nomes únicos
  (`save_upload`/`_unique_filename` em `main.py`).
- Documentos de aluno: `app/student_documents.py` sanitiza o caminho relativo
  (`sanitize_student_document_relpath`) — defesa contra path traversal.
- Servidos por rota autenticada `/uploads/<path:filename>` (não diretamente pelo
  servidor estático).

## 8. SQL injection

Risco **baixo**. Das 548 chamadas `.execute(...)` em `main.py`, praticamente
todas usam parâmetros `?`. A única query com f-string
(`main.py:13203`, `DELETE ... WHERE id IN (...)`) monta apenas os **placeholders**
(`?,?,?`) dinamicamente e passa os valores parametrizados — padrão seguro.

## Resumo de pontos de atenção (não-bloqueantes)

| # | Item | Severidade | Onde tratar |
|---|------|-----------|-------------|
| 1 | Rate limit/contadores em memória → não funcionam multi-worker | Média | [06](06_deploy_e_infraestrutura.md) |
| 2 | RBAC casa por nome de endpoint sem prefixo → frágil ao migrar p/ blueprint | Alta (no refactor) | [05](05_avaliacao_refactor.md) |
| 3 | `Referrer-Policy` divergente entre os dois `after_request` | Baixa | unificar headers |
| 4 | CSP com `'unsafe-inline'` em scripts | Baixa/Média | endurecer CSP (nonces) |
| 5 | Comentário "hashlib" enganoso no topo de `main.py` | Cosmético | limpar |
