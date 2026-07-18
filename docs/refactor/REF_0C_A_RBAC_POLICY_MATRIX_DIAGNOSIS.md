# REF-0C-A — RBAC Policy Matrix Diagnosis

## 1. Scope

Read-only diagnosis of the 24 unmapped `/admin` route-method combinations currently recorded in `tests/_artifacts/rbac_unmapped_routes_baseline.json`.

This phase determines the correct authorization policy for every gap. It does not implement or alter any policy.

## 2. Initial Git State

| Check | Value |
|-------|-------|
| Branch | `refactor/architecture-safety-net` |
| HEAD | `64d3d1214b87095edb65127839089f25b5237fc8` |
| Working tree | clean |
| Staging | empty |
| Untracked files | none |
| Divergence | `origin/main...HEAD = 0 7` |
| Python | 3.11.15 |

## 3. Files Read Completely

- `PROJECT_STATE.md`
- `AGENT_HANDOFF.md`
- `tests/_artifacts/rbac_unmapped_routes_baseline.json`
- `tests/test_rbac_requirement_coverage.py`
- `tests/test_release_admin_actions.py`
- `tests/test_admin_requisicao_list_scope.py`
- `app/auth.py`
- `app/__init__.py`
- `docs/refactor/REF_0TF_FAILURE_CLASSIFICATION.md`
- `docs/refactor/REF_0TF_B_D73H_HISTORICAL_VERIFICATION_ISOLATION.md`
- `tests/test_admin_activity_version_catalog_readonly.py`
- `tests/test_admin_activity_version_catalog_create.py`
- `tests/test_admin_activity_version_catalog_version_form.py`
- `tests/test_admin_activity_version_catalog_version_edit.py`
- `tests/test_admin_activity_version_catalog_version_activate.py`
- `tests/test_admin_activity_version_catalog_version_lifecycle.py`
- `tests/test_admin_matriz_versao_link.py`
- `tests/test_admin_matrix_new_activity.py`
- `tests/test_activity_versioning_phase_d1_diagnostic.py`
- `tests/test_activity_versioning_shadow_read_diagnostic.py`

### Files Inspected (relevant sections)

- `main.py`: all handler functions for the 24 unmapped routes (lines 9606–14305)
- `main.py`: `_get_current_admin_access_context` (line 1545), `_admin_can` (line 1562), `enforce_admin_access_control` (line 5248), `_admin_access_denied_response` (line 5232)
- `templates/admin_catalogo_versoes.html`
- `templates/admin_catalogo_versao_detalhe.html`
- `templates/admin_catalogo_versao_form.html`
- `templates/admin_catalogo_base_form.html`
- `templates/admin_normas_atividade.html`
- `templates/admin_norma_form.html`
- `templates/admin_mapeamento_legado.html`
- `templates/admin_matriz_versoes.html`
- `templates/admin_matriz_form.html`
- `templates/admin_diagnostico_atividades_versionadas_view.html`
- `templates/admin_atividades.html`

## 4. Commands Executed

```
git branch --show-current
git rev-parse HEAD
git status --short
git status --porcelain=v2 --untracked-files=all
git diff --cached --name-status
git rev-list --left-right --count origin/main...HEAD
git log --oneline -8
git show --check 9b47c37
git show --stat --name-status --oneline 9b47c37
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -c "import main; ..." (24-route reconciliation)
```

## 5. Current Role / Resource / Scope Inventory

### Roles (from `app/auth.py`)

| Key | Label | Type |
|-----|-------|------|
| `admin_total` | Admin | admin |
| `consultivo` | Consultor | admin |
| `administrativo` | Coordenador | admin |
| `usuario` | Usuário | aluno |
| `usuario_teste` | Usuário teste | aluno |

### Resources (from `app/auth.py`)

| Resource | Label | Group |
|----------|-------|-------|
| `dashboard` | Início | Visão geral |
| `requisicoes` | Requisições | Operação |
| `atividades` | Atividades | Cadastros |
| `matrizes` | Matrizes de atividades | Cadastros |
| `alunos` | Alunos | Cadastros |
| `turmas` | Turmas | Cadastros |
| `cursos` | Cursos | Cadastros |
| `arquivos` | Arquivos | Cadastros |
| `alertas` | Alertas | Operação |
| `reportes` | Reportes | Operação |
| `banco_dados` | Banco de dados | Segurança |
| `acesso` | Acesso | Segurança |
| `configuracoes` | Configurações | Sistema |
| `mensagens` | Mensagens de sistema | Sistema |
| `meus_dados` | Meus dados | Conta |

**SECURITY_RESTRICTED_RESOURCES**: `banco_dados`, `acesso`, `configuracoes`, `mensagens`

### Default Scopes by Role

| Role | Security resources | Other resources | `meus_dados` |
|------|-------------------|-----------------|--------------|
| `admin_total` | full | full | full |
| `administrativo` | none | full | full |
| `consultivo` | none | view | edit |

### Current profile-resource scopes (PROFILE_RESOURCE_SCOPES)

The 24 unmapped endpoints fall outside all existing resource definitions. No existing `ACCESS_RESOURCES_META` entry covers catalog-versioning, norms, legacy-mapping, diagnostics, or matrix-version links.

### Current Authorization Flow

1. `@admin_required` decorator checks `session["user_type"] == "admin"` — all 24 routes have this.
2. `enforce_admin_access_control` `@app.before_request` calls `get_admin_permission_requirement(endpoint, method)`.
3. If the requirement is `None` (as it is for all 24), the before-request passes through without checking scope.
4. No granular RBAC check is performed.

## 6. Baseline Reconciliation

**Result: EXACT MATCH.** The dynamic route-map enumeration returns exactly 24 unmapped route-method combinations, matching `tests/_artifacts/rbac_unmapped_routes_baseline.json` in URL, endpoint, method, and `current_requirement: null`.

No divergence detected. Reconciliation passes.

## 7. Complete 24-Row Matrix

### Domain Group: Catalog Versioning (read-only)

---

#### R1: `GET /admin/catalogo-versoes` — `admin_catalogo_versoes`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_versoes` |
| Source | `main.py:13405-13415` |
| Operation | List all `atividade_base` with version counts |
| Type | Read-only |
| Tables read | `atividade_base` |
| Tables mutated | None |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None |
| CSRF | N/A (GET) |
| UI exposure | `templates/admin_catalogo_versoes.html`; no sidebar entry per D7.2B1 design. Reachable via breadcrumb from detail pages. |
| Route callers | `admin_catalogo_versao_detalhe.html` (back link), `admin_catalogo_base_form.html` (cancel link) |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `view` |
| **Allowed roles** | `admin_total`, `administrativo`, `consultivo` |
| **Denied roles** | `anonymous`, `aluno` (already blocked by `@admin_required`) |
| **Denial response** | Redirect to `admin_dashboard` with flash error (via `_admin_access_denied_response`) |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) |
| Tests | `test_admin_activity_version_catalog_readonly.py` lines 183-201 |
| Missing tests | No consultivo/administrativo role coverage, no scope-denial test |
| Evidence | Existing catalog list endpoints use resource `atividades` with `view` scope (e.g., `admin_atividades`). READ-only catalog listing is semantically equivalent to viewing activities. |
| **Confidence** | **HIGH** |
| Approval required | No |
| Risk | None — policy follows existing pattern for read-only activity listing |

---

#### R2: `GET /admin/catalogo-versoes/<int:base_id>` — `admin_catalogo_versao_detalhe`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_versao_detalhe` |
| Source | `main.py:13420-13472` |
| Operation | Detail of a single `atividade_base` with all linked versions, transition history, and substitution candidates |
| Type | Read-only |
| Tables read | `atividade_base`, `atividade_versao`, `atividade_transicao` |
| Tables mutated | None |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None |
| CSRF | N/A (GET) |
| UI exposure | Same template family as R1; no sidebar entry |
| Route callers | `admin_catalogo_versoes.html` (detail links), `admin_catalogo_versao_form.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `view` |
| **Allowed roles** | `admin_total`, `administrativo`, `consultivo` |
| **Denied roles** | `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) |
| Tests | `test_admin_activity_version_catalog_readonly.py` lines 240-411 |
| Missing tests | No role-coverage tests for detail page |
| Evidence | Same resource as R1; read-only detail of catalog data |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R3: `GET /admin/normas-atividade` — `admin_normas_atividade`

| Field | Value |
|-------|-------|
| Handler | `admin_normas_atividade` |
| Source | `main.py:13477-13487` |
| Operation | List all `norma_atividade` with version counts |
| Type | Read-only |
| Tables read | `norma_atividade` |
| Tables mutated | None |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None |
| CSRF | N/A (GET) |
| UI exposure | `templates/admin_normas_atividade.html`; no sidebar entry |
| Route callers | `admin_norma_form.html` (cancel link) |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `view` |
| **Allowed roles** | `admin_total`, `administrativo`, `consultivo` |
| **Denied roles** | `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) |
| Tests | `test_admin_activity_version_catalog_readonly.py` lines 417-443 |
| Missing tests | No role-coverage tests |
| Evidence | Norm listing is normative metadata read; same business domain as activity catalog |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R4: `GET /admin/mapeamento-legado` — `admin_mapeamento_legado`

| Field | Value |
|-------|-------|
| Handler | `admin_mapeamento_legado` |
| Source | `main.py:13492-13510` |
| Operation | List legacy activities with mapping status to `atividade_base` |
| Type | Read-only |
| Tables read | `atividades`, `atividade_legacy_map`, `atividade_base` |
| Tables mutated | None (proven by test `test_mapeamento_legado_does_not_auto_map`) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None |
| CSRF | N/A (GET) |
| UI exposure | `templates/admin_mapeamento_legado.html`; no sidebar entry |
| Route callers | Self-referential filter links |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `view` |
| **Allowed roles** | `admin_total`, `administrativo`, `consultivo` |
| **Denied roles** | `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) |
| Tests | `test_admin_activity_version_catalog_readonly.py` lines 450-543 |
| Missing tests | No role-coverage tests |
| Evidence | Same domain as activity catalog; read-only mapping visualization |
| **Confidence** | **HIGH** |
| Approval required | No |

---

### Domain Group: Catalog Versioning (create/update)

---

#### R5: `GET /admin/catalogo-versoes/nova-base` — `admin_catalogo_nova_base`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_nova_base` |
| Source | `main.py:13515-13574` |
| Operation | Show form to create a new `atividade_base` |
| Type | Read-only (form display) |
| Tables read | None (GET renders empty form) |
| Tables mutated | None (GET) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None |
| CSRF | N/A (GET), but form has CSRF field for POST |
| UI exposure | Button "Nova base" in `admin_catalogo_versoes.html` |
| Route callers | `admin_catalogo_versoes.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` (GET form = edit permission required to see create form) |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) |
| Tests | `test_admin_activity_version_catalog_create.py` (tests GET 200 and POST behavior) |
| Missing tests | No consultivo denial test, no scope test |
| Evidence | Existing create-form GET routes use `edit` scope (e.g., `admin_adicionar_atividade`, `admin_adicionar_curso` both use `atividades`/`edit`). Pattern is well established. |
| **Confidence** | **HIGH** |
| Approval required | No |
| Risk | Consultivo would see a 403 instead of being able to view the form but not submit. This is consistent with existing pattern. |

---

#### R6: `POST /admin/catalogo-versoes/nova-base` — `admin_catalogo_nova_base`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_nova_base` |
| Source | `main.py:13515-13574` (POST branch) |
| Operation | Create new `atividade_base` row |
| Type | Create |
| Tables read | `atividade_base` (duplicate check) |
| Tables mutated | `atividade_base` (INSERT) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None (server-side validation for duplicates/status only, not auth) |
| CSRF | Yes (Flask-WTF, auto-injected) |
| UI exposure | Form rendered on GET; button "Nova base" in catalog listing |
| Route callers | Form POST from `admin_catalogo_base_form.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | `atividade_base` row count unchanged; no new rows inserted |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_activity_version_catalog_create.py` lines 2-13 for POST behaviors |
| Missing tests | No consultivo/administrativo denial test, no immutability-after-denial test |
| Evidence | Existing create POST routes use `atividades`/`edit` |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R7: `GET /admin/normas-atividade/nova` — `admin_norma_nova`

| Field | Value |
|-------|-------|
| Handler | `admin_norma_nova` |
| Source | `main.py:13579-13634` |
| Operation | Show form to create a new `norma_atividade` |
| Type | Read-only (form display) |
| Tables read | None (GET renders empty form) |
| Tables mutated | None |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None |
| CSRF | N/A (GET) |
| UI exposure | Button "Nova norma" in `admin_normas_atividade.html` |
| Route callers | `admin_normas_atividade.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) |
| Tests | `test_admin_activity_version_catalog_create.py` tests GET 200 |
| Missing tests | No consultivo denial test |
| Evidence | Same pattern as `admin_catalogo_nova_base` GET |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R8: `POST /admin/normas-atividade/nova` — `admin_norma_nova`

| Field | Value |
|-------|-------|
| Handler | `admin_norma_nova` |
| Source | `main.py:13579-13634` (POST branch) |
| Operation | Create new `norma_atividade` row |
| Type | Create |
| Tables read | `norma_atividade` (duplicate check) |
| Tables mutated | `norma_atividade` (INSERT) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None (server-side validation for required fields, eixo, status only) |
| CSRF | Yes (Flask-WTF, auto-injected) |
| UI exposure | Form rendered on GET |
| Route callers | Form POST from `admin_norma_form.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | `norma_atividade` row count unchanged; no new rows inserted |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_activity_version_catalog_create.py` tests POST behaviors |
| Missing tests | No consultivo denial test, no immutability-after-denial test |
| Evidence | Same pattern as other create POST routes |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R9: `GET /admin/catalogo-versoes/<int:base_id>/nova-versao` — `admin_catalogo_nova_versao`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_nova_versao` |
| Source | `main.py:13639-13791` (GET branch) |
| Operation | Show form to create a new `atividade_versao` in draft status |
| Type | Read-only (form display) |
| Tables read | `atividade_base`, `norma_atividade`, `atividade_versao` (for previous versions, next numero) |
| Tables mutated | None (GET) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None |
| CSRF | N/A (GET) |
| UI exposure | Button "Criar versão" in `admin_catalogo_versao_detalhe.html`; also reachable from admin activities menu |
| Route callers | `admin_catalogo_versao_detalhe.html`, `admin_atividades.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) |
| Tests | `test_admin_activity_version_catalog_version_form.py` tests GET 200 and missing-base redirect |
| Missing tests | No consultivo denial test |
| Evidence | Version creation is part of activity catalog management, requiring `edit` scope |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R10: `POST /admin/catalogo-versoes/<int:base_id>/nova-versao` — `admin_catalogo_nova_versao`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_nova_versao` |
| Source | `main.py:13639-13791` (POST branch) |
| Operation | Create new `atividade_versao` row with `status='rascunho'` |
| Type | Create |
| Tables read | `atividade_base`, `norma_atividade`, `atividade_versao` |
| Tables mutated | `atividade_versao` (INSERT) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | Server-side validation: base exists, norma exists and active, numeric fields valid, versao_anterior_id valid. No auth-level check beyond `@admin_required`. |
| CSRF | Yes (Flask-WTF, auto-injected) |
| UI exposure | Form rendered on GET |
| Route callers | Form POST from `admin_catalogo_versao_form.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | `atividade_versao` row count unchanged; no INSERT executed |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_activity_version_catalog_version_form.py` |
| Missing tests | No consultivo denial test, no immutability-after-denial test |
| Evidence | Same pattern as other create POST routes |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R11: `GET /admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/editar` — `admin_catalogo_editar_versao`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_editar_versao` |
| Source | `main.py:13799-13989` (GET branch) |
| Operation | Show form to edit an existing `atividade_versao` (draft only, no usage) |
| Type | Read-only (form display) |
| Tables read | `atividade_base`, `atividade_versao`, `norma_atividade` |
| Tables mutated | None (GET) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | Server-side status check (`status == 'rascunho'`) and usage check; no auth-level check |
| CSRF | N/A (GET) |
| UI exposure | "Editar" link in `admin_catalogo_versao_detalhe.html` for draft versions |
| Route callers | `admin_catalogo_versao_detalhe.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) |
| Tests | `test_admin_activity_version_catalog_version_edit.py` items 1-4 |
| Missing tests | No consultivo denial test |
| Evidence | Edit form GET follows same pattern as other edit routes (e.g., `admin_editar_atividade` uses `atividades`/`edit`) |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R12: `POST /admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/editar` — `admin_catalogo_editar_versao`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_editar_versao` |
| Source | `main.py:13799-13989` (POST branch) |
| Operation | Update existing `atividade_versao` fields (draft only, no usage) |
| Type | Update |
| Tables read | `atividade_base`, `atividade_versao`, `norma_atividade` |
| Tables mutated | `atividade_versao` (UPDATE) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | Status `rascunho`, usage check, norma validation; no auth-level check |
| CSRF | Yes |
| UI exposure | Form rendered on GET |
| Route callers | Form POST from `admin_catalogo_versao_form.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | `atividade_versao` row for versao_id has unchanged values |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_activity_version_catalog_version_edit.py` items 5-28 |
| Missing tests | No consultivo denial test, no immutability-after-denial test |
| Evidence | Same pattern as other edit POST routes |
| **Confidence** | **HIGH** |
| Approval required | No |

---

### Domain Group: Version Lifecycle Transitions

---

#### R13: `POST /admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/ativar` — `admin_catalogo_ativar_versao`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_ativar_versao` |
| Source | `main.py:13997-14063` |
| Operation | Activate a draft version: `status = 'rascunho'` → `'ativa'` |
| Type | Activate (normative change) |
| Tables read | `atividade_base`, `atividade_versao`, `norma_atividade` |
| Tables mutated | `atividade_versao` (UPDATE status) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | Base exists, version exists and belongs to base, status is `rascunho`, norma exists and is `ativa`; rowcount guard. No auth-level check. |
| CSRF | Yes (real token in template form) |
| UI exposure | Button "Ativar" in `admin_catalogo_versao_detalhe.html` for draft versions only |
| Route callers | Form POST from `admin_catalogo_versao_detalhe.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | `atividade_versao` status unchanged from previous value |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_activity_version_catalog_version_activate.py` (17 tests) |
| Missing tests | No consultivo denial test, no immutability-after-denial test |
| Evidence | Activation is a write operation on activity version data. Requires `edit` scope by existing pattern. |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R14: `POST /admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/inativar` — `admin_catalogo_inativar_versao`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_inativar_versao` |
| Source | `main.py:14181-14238` |
| Operation | Inactivate an active version: `status = 'ativa'` → `'inativa'` |
| Type | Deactivate |
| Tables read | `atividade_base`, `atividade_versao` |
| Tables mutated | `atividade_versao` (UPDATE status) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | Base exists, version exists and belongs to base, status is `ativa`, no matrix link (B1 guard) |
| CSRF | Yes (real token in template form) |
| UI exposure | Button "Inativar" in `admin_catalogo_versao_detalhe.html` for active versions |
| Route callers | Form POST from `admin_catalogo_versao_detalhe.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | `atividade_versao` status unchanged from previous value |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_activity_version_catalog_version_lifecycle.py` items 1-9, 15-19 |
| Missing tests | No consultivo denial test, no immutability-after-denial test |
| Evidence | Same pattern as activation — version lifecycle management |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R15: `POST /admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/descontinuar` — `admin_catalogo_descontinuar_versao`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_descontinuar_versao` |
| Source | `main.py:14246-14305` |
| Operation | Discontinue an active version: `status = 'ativa'` → `'descontinuada'` |
| Type | Discontinue |
| Tables read | `atividade_base`, `atividade_versao` |
| Tables mutated | `atividade_versao` (UPDATE status) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | Base exists, version exists and belongs to base, status is `ativa`, no matrix link (B1 guard) |
| CSRF | Yes (real token in template form) |
| UI exposure | Button "Descontinuar" in `admin_catalogo_versao_detalhe.html` for active versions |
| Route callers | Form POST from `admin_catalogo_versao_detalhe.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | `atividade_versao` status unchanged from previous value |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_activity_version_catalog_version_lifecycle.py` items 10-14, 15-19 |
| Missing tests | No consultivo denial test, no immutability-after-denial test |
| Evidence | Same lifecycle domain as activation/inactivation |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R16: `POST /admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/substituir` — `admin_catalogo_substituir_versao`

| Field | Value |
|-------|-------|
| Handler | `admin_catalogo_substituir_versao` |
| Source | `main.py:14071-14173` |
| Operation | Substitute an active version: marks origin as `'substituida'` and creates `atividade_transicao` |
| Type | Replace |
| Tables read | `atividade_base`, `atividade_versao`, `atividade_transicao` (usage check), `matriz_atividade_versao_item` (usage check) |
| Tables mutated | `atividade_versao` (UPDATE status on origin), `atividade_transicao` (INSERT) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | Base, origin, destination existence and validity; status checks; usage checks (matrix link, existing transitions); same-base and same-eixo validations; rowcount guard |
| CSRF | Yes (real token in template form) |
| UI exposure | "Substituir" form in `admin_catalogo_versao_detalhe.html` for active versions with candidates |
| Route callers | Form POST from `admin_catalogo_versao_detalhe.html` |
| **Proposed resource** | `atividades` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | Both origin and destination `atividade_versao` rows unchanged; `atividade_transicao` has no new rows |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_activity_version_catalog_version_lifecycle.py` items (substituir tests, lines 925-1165) |
| Missing tests | No consultivo denial test, no immutability-after-denial test |
| Evidence | Substitution is the most impactful lifecycle operation; still in the activity management domain |
| **Confidence** | **HIGH** |
| Approval required | No |

---

### Domain Group: Matrix Versioning and Activities

---

#### R17: `GET /admin/matrizes/<int:matriz_id>/versoes` — `admin_matriz_versoes`

| Field | Value |
|-------|-------|
| Handler | `admin_matriz_versoes` |
| Source | `main.py:13229-13262` |
| Operation | List scope bases with current version links and available active versions |
| Type | Read-only |
| Tables read | `matrizes_atividades`, `atividade_base`, `atividade_versao`, `matrizes_atividades_itens`, `atividade_legacy_map`, `matriz_atividade_versao_item`, `matriz_norma` |
| Tables mutated | None |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None (matrix existence validated, no auth check) |
| CSRF | N/A (GET) |
| UI exposure | Link in `admin_matriz_form.html` "Versões" tab |
| Route callers | `admin_matriz_form.html` |
| **Proposed resource** | `matrizes` |
| **Proposed scope** | `view` |
| **Allowed roles** | `admin_total`, `administrativo`, `consultivo` |
| **Denied roles** | `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) |
| Tests | `test_admin_matriz_versao_link.py` items 1-4 |
| Missing tests | No consultivo denial test |
| Evidence | This page shows matrix version link data; the `matrizes` resource already exists in `ACCESS_RESOURCES_META` |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R18: `POST /admin/matrizes/<int:matriz_id>/versoes/definir` — `admin_matriz_versoes_definir`

| Field | Value |
|-------|-------|
| Handler | `admin_matriz_versoes_definir` |
| Source | `main.py:13267-13351` |
| Operation | Set/replace the explicit version link for a matrix+base |
| Type | Update |
| Tables read | `matrizes_atividades`, `atividade_base`, `atividade_versao`, `matrizes_atividades_itens`, `atividade_legacy_map`, `matriz_norma` |
| Tables mutated | `matriz_atividade_versao_item` (DELETE old + INSERT new) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | 7 server-side validations (matrix, base, version, base ownership, status `ativa`, legado scope, matriz_norma). No auth-level check. |
| CSRF | Yes (real token in template form) |
| UI exposure | "Definir" form in `admin_matriz_versoes.html` |
| Route callers | Form POST from `admin_matriz_versoes.html` |
| **Proposed resource** | `matrizes` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | `matriz_atividade_versao_item` row count for matriz_id unchanged from before request |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_matriz_versao_link.py` items 5-14 |
| Missing tests | No consultivo denial test, no immutability-after-denial test |
| Evidence | Mutating matrix-version links is a matrix edit operation |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R19: `POST /admin/matrizes/<int:matriz_id>/versoes/remover` — `admin_matriz_versoes_remover`

| Field | Value |
|-------|-------|
| Handler | `admin_matriz_versoes_remover` |
| Source | `main.py:13354-13398` |
| Operation | Remove the explicit version link for a matrix+base |
| Type | Update |
| Tables read | `matrizes_atividades`, `atividade_base` |
| Tables mutated | `matriz_atividade_versao_item` (DELETE) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | Matrix exists, base exists, base_id is digit. No auth-level check. |
| CSRF | Yes (real token in template form) |
| UI exposure | "Remover" form in `admin_matriz_versoes.html` |
| Route callers | Form POST from `admin_matriz_versoes.html` |
| **Proposed resource** | `matrizes` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | `matriz_atividade_versao_item` row count for matriz_id unchanged |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_matriz_versao_link.py` items 8, 10 |
| Missing tests | No consultivo denial test, no immutability-after-denial test |
| Evidence | Same matrix edit domain as definir |
| **Confidence** | **HIGH** |
| Approval required | No |

---

#### R20: `POST /admin/matrizes/<int:matriz_id>/atividades/nova/<string:active_tab>` — `admin_matriz_nova_atividade`

| Field | Value |
|-------|-------|
| Handler | `admin_matriz_nova_atividade` |
| Source | `main.py:12894-13082` |
| Operation | Create a new legacy activity + `atividade_base` + `atividade_legacy_map` + `atividade_versao` (status `ativa`) + optionally `matriz_atividade_versao_item` |
| Type | Create |
| Tables read | `matrizes_atividades`, `norma_atividade`, `matriz_norma` |
| Tables mutated | `atividades` (INSERT), `atividade_base` (INSERT), `atividade_legacy_map` (INSERT), `atividade_versao` (INSERT), `matrizes_atividades_itens` (INSERT if add_to_matrix), `matriz_atividade_versao_item` (INSERT if add_to_matrix) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | Matrix exists, `_admin_can("matrizes", "edit", auth_context)` check (line 12906, `readonly` flag), but **check is not enforced** — `readonly` is computed but the route never redirects if readonly is True (it only drives UI), making this a **redundant check** that does not prevent the mutation. |
| CSRF | Yes (Flask-WTF) |
| UI exposure | Button "+ Nova atividade" in `admin_matriz_form.html` |
| Route callers | Modal form POST from `admin_matriz_form.html` |
| **Proposed resource** | `matrizes` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | All 6 affected tables have unchanged row counts |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_matrix_new_activity.py` |
| Missing tests | No consultivo denial test, no immutability-after-denial test. **Critical:** `readonly` variable is set but never enforced on POST — this needs explicit architect attention. |
| Evidence | Matrix activity creation is a write operation on matrix data |
| **Policy confidence** | **HIGH** — `matrizes`/`edit` allows `admin_total` and `administrativo`, and denies `consultivo` under the current profile model. |
| Approval required | No decision is needed to identify the RBAC mapping. The local `readonly` value is a separate enforcement/cleanup issue. |

---

#### R21: `POST /admin/matrizes/<int:matriz_id>/atividades/<int:atividade_id>/nova-versao` — `admin_matriz_nova_versao_card`

| Field | Value |
|-------|-------|
| Handler | `admin_matriz_nova_versao_card` |
| Source | `main.py:13092-13183` |
| Operation | Re-link a matrix to an existing operational version of an activity |
| Type | Update |
| Tables read | `matrizes_atividades`, `atividade_legacy_map`, `matrizes_atividades_itens`, `atividade_versao`, `matriz_norma`, `matriz_atividade_versao_item` |
| Tables mutated | `matriz_atividade_versao_item` (DELETE old + INSERT new via `_set_versao_da_matriz_para_base`) |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | Matrix exists, legacy_map exists, in_scope check, version exists, belongs to base, status `ativa`, norma in `matriz_norma`. No auth-level check. |
| CSRF | Yes (Flask-WTF) |
| UI exposure | Modal form from `admin_matriz_form.html` (⋮ menu on card) |
| Route callers | Modal form POST from `admin_matriz_form.html` |
| **Proposed resource** | `matrizes` |
| **Proposed scope** | `edit` |
| **Allowed roles** | `admin_total`, `administrativo` |
| **Denied roles** | `consultivo`, `anonymous`, `aluno` |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | `matriz_atividade_versao_item` row count for matriz_id unchanged |
| **No-filesystem invariant** | N/A |
| Tests | `test_admin_matriz_nova_versao_card.py` (referenced in D7.5D documentation) |
| Missing tests | No consultivo denial test, no immutability-after-denial test |
| Evidence | Same matrix edit domain |
| **Confidence** | **HIGH** |
| Approval required | No |

---

### Domain Group: Diagnostics

---

#### R22: `GET /admin/diagnostico/atividades-versionadas` — `admin_diagnostico_atividades_versionadas`

| Field | Value |
|-------|-------|
| Handler | `admin_diagnostico_atividades_versionadas` |
| Source | `main.py:9619-9663` |
| Operation | JSON diagnostic endpoint returning versioned activity model for a turma/matriz |
| Type | Diagnostic (read-only) |
| Tables read | `atividades`, `atividade_base`, `atividade_versao`, `atividade_legacy_map`, `matrizes_atividades`, `matrizes_atividades_itens`, `matriz_atividade_versao_item`, `matriz_norma`, `turmas` |
| Tables mutated | None |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None |
| CSRF | N/A (GET) |
| UI exposure | Link from `admin_diagnostico_atividades_versionadas_view.html` |
| Route callers | View template link, direct API calls |
| **Policy status** | **Unresolved** — pending the explicit diagnostic access-policy decision in D4. |
| **Candidate mappings** | A. `atividades`/`view` → `admin_total`, `administrativo`, `consultivo`; B. `banco_dados`/`view` → `admin_total` only; C. `admin_total` + `administrativo`, consultivo denied → not representable by the documented default scopes without an override, new resource, new scope, or endpoint-specific rule. |
| **Allowed roles** | Pending D4; no definitive role list is recorded. |
| **Denied roles** | Pending D4; anonymous and aluno remain blocked by `@admin_required`. |
| **Denial response** | JSON `{"ok": false, "error": "forbidden"}` with 403 for AJAX (via `_admin_access_denied_response`), or redirect |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) |
| Tests | `test_activity_versioning_phase_d1_diagnostic.py` |
| Missing tests | No role-coverage tests; only tests with default admin user |
| Evidence | Diagnostic endpoint is read-only activity version analysis; `atividades` view scope is the closest match. However, this is a JSON diagnostic that exposes internal model structure — might warrant a dedicated resource or `banco_dados` view scope. |
| **Confidence** | **MEDIUM** — resource choice is ambiguous between `atividades` and `banco_dados` |
| Approval required | **Yes** — architect should confirm whether diagnostic JSON exposure should use `atividades` view scope (read operations on activity data) or `banco_dados` view scope (system diagnostic) |

---

#### R23: `GET /admin/diagnostico/atividades-versionadas/view` — `admin_diagnostico_atividades_versionadas_view`

| Field | Value |
|-------|-------|
| Handler | `admin_diagnostico_atividades_versionadas_view` |
| Source | `main.py:9736-9787` |
| Operation | HTML view/template for the versioned activity diagnostic |
| Type | Diagnostic (read-only) |
| Tables read | Same as R22 |
| Tables mutated | None |
| Filesystem | None |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None |
| CSRF | N/A (GET) |
| UI exposure | Direct URL access; also linked from diagnostic view page |
| Route callers | View template navigation |
| **Policy status** | **Unresolved** — pending the explicit diagnostic access-policy decision in D4. |
| **Candidate mappings** | A. `atividades`/`view` → `admin_total`, `administrativo`, `consultivo`; B. `banco_dados`/`view` → `admin_total` only; C. `admin_total` + `administrativo`, consultivo denied → not representable by the documented default scopes without an override, new resource, new scope, or endpoint-specific rule. |
| **Allowed roles** | Pending D4; no definitive role list is recorded. |
| **Denied roles** | Pending D4; anonymous and aluno remain blocked by `@admin_required`. |
| **Denial response** | Redirect to `admin_dashboard` with flash error |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) |
| Tests | `test_activity_versioning_phase_d1_diagnostic.py` |
| Missing tests | No role-coverage tests |
| Evidence | Same diagnostic domain as R22; HTML view should have same RBAC as JSON counterpart |
| **Confidence** | **MEDIUM** — same ambiguity as R22 |
| Approval required | **Yes** — tied to R22 decision |

---

#### R24: `GET /admin/diagnostico/versioned-shadow-reads` — `admin_diagnostico_versioned_shadow_reads`

| Field | Value |
|-------|-------|
| Handler | `admin_diagnostico_versioned_shadow_reads` |
| Source | `main.py:9668-9731` |
| Operation | JSON diagnostic endpoint for versioned resolver shadow-read log events |
| Type | Diagnostic (read-only) |
| Tables read | None (reads from log files, not DB) |
| Tables mutated | None |
| Filesystem | Reads `logs/app.log` and/or a dedicated shadow-read log file |
| Auth | `@admin_required` |
| Granular RBAC | None |
| Local checks | None |
| CSRF | N/A (GET) |
| UI exposure | No UI entry; direct API access |
| Route callers | Direct API calls |
| **Proposed resource** | `banco_dados` |
| **Proposed scope** | `view` |
| **Allowed roles under current defaults** | `admin_total` only |
| **Denied roles under current defaults** | `administrativo`, `consultivo`, `anonymous`, `aluno` |
| **Denial response** | JSON 403 for AJAX, or redirect |
| **No-mutation invariant** | N/A (GET) |
| **No-filesystem invariant** | N/A (GET) — reads log files but does not modify them |
| Tests | `test_activity_versioning_shadow_read_diagnostic.py` |
| Missing tests | No consultivo denial test, no role-coverage test |
| Evidence | This is an internal system diagnostic that exposes resolver behavior, log paths, and environment configuration. Existing pattern: `banco_dados` resource with `view` scope is used for system diagnostics (e.g., `admin_banco_dados` GET uses `banco_dados`/`view`). This is a closer match than `atividades`. |
| **Confidence** | **MEDIUM** — resource choice is between `banco_dados` and a new dedicated `diagnostico` resource |
| Approval required | **Yes** — architect should decide if a new `diagnostico` resource should be created, or if `banco_dados`/`view` is appropriate |

---

## 8. Domain Group Analysis

### 8.1 Catalog Versioning (R1-R4: read-only)

All 4 read-only catalog routes can reuse the existing `atividades` resource with `view` scope. This resource already exists in `ACCESS_RESOURCES_META` and is used by neighboring read-only activity endpoints (`admin_atividades`, `admin_atividades_academicas`, `admin_atividades_extensao`). The vocabulary is semantically consistent: catalog browsing is activity metadata reading.

**No new vocabulary required.**

### 8.2 Catalog Versioning (R5-R12: create/update)

All 8 create/update catalog routes can reuse the existing `atividades` resource with `edit` scope. This matches the existing pattern for activity mutations (`admin_adicionar_atividade` uses `atividades`/`edit`).

**No new vocabulary required.**

### 8.3 Version Lifecycle Transitions (R13-R16)

All 4 lifecycle transition routes can reuse the existing `atividades` resource with `edit` scope. Although these are semantically "activate"/"deactivate"/"discontinue"/"replace", they are mutations on `atividade_versao` rows, which belong to the activity catalog domain. The existing `edit` scope is sufficient.

**No new vocabulary required.**

### 8.4 Matrix Versioning and Activities (R17-R21)

R17 (GET) should use `matrizes`/`view`. Routes R18-R21 should use `matrizes`/`edit`. The `matrizes` resource already exists in `ACCESS_RESOURCES_META` and is used by neighboring matrix endpoints.

**No new vocabulary required.**

However, R20 (`admin_matriz_nova_atividade`) requires special attention: the route computes a `readonly` variable from `_admin_can("matrizes", "edit", auth_context)` at line 12906, but never enforces it — `readonly` is only used for UI rendering. The POST mutation executes regardless. This means that even with the correct RBAC mapping, the local `readonly` check is misleading: a consultivo user currently can reach this POST route and create data if they bypass the UI, because:
1. `get_admin_permission_requirement` returns `None` → no before-request gate
2. `@admin_required` passes (consultivo is admin type)
3. `readonly` is `True` for consultivo but not enforced

This is classified as **REDUNDANT LOCAL AUTHORIZATION** (the check exists but does not prevent the operation). Fixing the RBAC mapping will resolve this, as `consultivo` with `matrizes`/`edit` denied would be stopped at the before-request gate.

### 8.5 Diagnostics (R22-R24)

Two possible vocabularies:

**Option A: `atividades`/`view`** — The diagnostic endpoints read activity version data. However, they expose internal resolver state, which is more than just activity metadata.

**Option B: `banco_dados`/`view`** — The existing `banco_dados` resource already covers system-level diagnostics. The shadow-read diagnostic (R24) reads log files and resolver state, fitting this category. R22-R23 read from multiple tables including resolver state.

**Consider creating a new `diagnostico` resource** — If diagnostics should be treated as a distinct category with its own scope, a new resource would be cleaner. However, this requires explicit architectural decision.

**Recommendation**: Use `banco_dados`/`view` for R24 (shadow reads = system diagnostic), and `atividades`/`view` for R22-R23 (activity version model diagnostic). This avoids creating new vocabulary while maintaining semantic separation.

### 8.6 Legacy Mapping (R4)

The legacy mapping view reads both `atividades` and `atividade_base`/`atividade_legacy_map` tables. It belongs to the activity catalog domain. Using `atividades`/`view` is consistent.

## 9. Strongly Supported Policies

The following recommendations follow directly from existing role definitions, neighboring protected routes, tests, UI restrictions, and operation semantics:

- **R1** — `atividades`/`view`, all admin roles
- **R2** — `atividades`/`view`, all admin roles
- **R3** — `atividades`/`view`, all admin roles
- **R4** — `atividades`/`view`, all admin roles
- **R5** — `atividades`/`edit`, admin_total + administrativo
- **R6** — `atividades`/`edit`, admin_total + administrativo
- **R7** — `atividades`/`edit`, admin_total + administrativo
- **R8** — `atividades`/`edit`, admin_total + administrativo
- **R9** — `atividades`/`edit`, admin_total + administrativo
- **R10** — `atividades`/`edit`, admin_total + administrativo
- **R11** — `atividades`/`edit`, admin_total + administrativo
- **R12** — `atividades`/`edit`, admin_total + administrativo
- **R13** — `atividades`/`edit`, admin_total + administrativo
- **R14** — `atividades`/`edit`, admin_total + administrativo
- **R15** — `atividades`/`edit`, admin_total + administrativo
- **R16** — `atividades`/`edit`, admin_total + administrativo
- **R17** — `matrizes`/`view`, all admin roles
- **R18** — `matrizes`/`edit`, admin_total + administrativo
- **R19** — `matrizes`/`edit`, admin_total + administrativo
- **R21** — `matrizes`/`edit`, admin_total + administrativo

**Total: 21 out of 24 routes have HIGH-confidence policy recommendations.**

## 10. Moderately Inferred Policies

The following recommendations are supported by multiple signals but no explicit normative rule:

- **R22** — `atividades`/`view` (all admin roles) — diagnostic JSON reads activity model data
- **R23** — `atividades`/`view` (all admin roles) — HTML view of same diagnostic
- **R24** — unresolved diagnostic policy; `banco_dados`/`view` permits only `admin_total` under current defaults

These are classified as MEDIUM confidence because the resource choice is ambiguous.

## 11. Explicit Decisions Required

| # | Routes | Issue | Options | Security Impact | Usability Impact | Recommended Default |
|---|--------|-------|---------|----------------|-----------------|-------------------|
| D1 | R20 | `readonly` variable computed but not enforced | (a) Keep RBAC mapping as `matrizes`/`edit` and let before-request gate enforce; (b) Also enforce `readonly` in POST handler | Medium — consultivo could currently create data via direct POST | None | (a) — fix RBAC gap; `readonly` UI hint is secondary |
| D2 | R22, R23 | Resource choice for activity version diagnostics | (a) `atividades`/`view`; (b) `banco_dados`/`view`; (c) new `diagnostico` resource | Low — both are read-only | Low | (a) — consistent with reading activity data |
| D3 | R24 | Resource choice for shadow-read diagnostics | (a) `banco_dados`/`view`; (b) new `diagnostico` resource; (c) `atividades`/`view` | Medium — shadow reads expose resolver internals and log paths | None (no UI entry) | (a) — system diagnostic fits `banco_dados` |
| D4 | R22-R24 | Diagnostic access policy | A. `atividades`/`view`: admin_total, administrativo, consultivo; no override. B. `banco_dados`/`view`: admin_total only; no override. C. admin_total + administrativo, consultivo denied: explicit override, new resource, new scope, or endpoint-specific rule. | A broadest; B most restrictive; C intermediate | A all admins; B admin_total only; C keeps administrativo | Unresolved; architect decision required |

## 12. Redundant Local Checks

**R20 (`admin_matriz_nova_atividade`):** The handler computes `readonly = not _admin_can("matrizes", "edit", auth_context)` at line 12906 and passes it to the template, but the POST mutation at line 12980+ does not check `readonly` before executing INSERTs. The check exists for UI purposes only and does not prevent unauthorized writes.

**Classification: D — REDUNDANT LOCAL AUTHORIZATION.** A granular RBAC mapping would make the local check genuinely redundant. The local check should either be made effective or removed after RBAC is in place.

---

## 13. Closeout — Supervisor Acceptance of REF-0C-A

### 13.1 Status

| Item | Value |
|------|-------|
| Phase | REF-0C-A / REF-0C-A-R1 |
| **Status** | **CLOSED / ACCEPTED** |
| Accepted diagnosis HEAD | `f977fd6` |
| Accepted matrix HIGH count | 21 |
| Accepted matrix MEDIUM count | 3 |
| Accepted matrix LOW count | 0 |
| RBAC implementation started | No |
| Modularization | Remains prohibited |

### 13.2 Unresolved Normative Diagnostic-Policy Decisions

The following routes retain unresolved diagnostic-policy status (no policy selected):

- **R22** — `GET /admin/diagnostico/atividades-versionadas` — diagnostic access policy unresolved
- **R23** — `GET /admin/diagnostico/atividades-versionadas/view` — diagnostic access policy unresolved
- **R24** — `GET /admin/diagnostico/versioned-shadow-reads` — diagnostic access policy unresolved

These three routes remain excluded from implementation until their diagnostic access policy is approved.

### 13.3 Next Authorized Technical Phase

**REF-0C-B1 — Strongly Supported RBAC Mappings and Denial Tests**

Scope is explicitly limited to the 21 HIGH-confidence route-method combinations from Section 9 (R1–R19, R21). The following constraints apply:

1. **Only HIGH-confidence routes**: Implementation is limited to the 21 routes with HIGH confidence in Section 9. R20 is authorized only for the central `matrizes`/`edit` RBAC mapping and its tests.
2. **R20 scope limitation**: For R20, authorize only the central `matrizes`/`edit` RBAC mapping and its tests. Do not change or remove the local `readonly` behavior in this closeout.
3. **R22–R24 excluded**: R22, R23, and R24 are explicitly excluded from implementation. No policy has been selected for these routes.
4. **No fail-closed global enforcement**: This phase does not authorize fail-closed global enforcement of `get_admin_permission_requirement`.
5. **No UI changes**: Template-level access control modifications are not authorized.
6. **No schema or database changes**: Schema migrations and database modifications are not authorized.
7. **No modularization**: Route modularization remains prohibited.

### 13.4 Accepted Diagnosis Commit

The normative RBAC policy matrix diagnosis recorded in this document at commit `f977fd6` (`Document normative RBAC policy matrix diagnosis`) is accepted as the authoritative policy reference. The diagnosis HEAD is `f977fd6`.

### 13.5 Matrix Confidence Counts

| Confidence | Count | Routes |
|------------|-------|--------|
| **HIGH** | 21 | R1–R19, R21 |
| **MEDIUM** | 3 | R22, R23, R24 |
| **LOW** | 0 | — |

## 14. Routes with No Granular Compensation

All 24 routes currently depend solely on `@admin_required`. None perform a granular permission check that would compensate for a missing `get_admin_permission_requirement` entry:

- **No handler** calls `_admin_can()` to check resource-level permission
- **No handler** inspects `session["nivel_acesso"]` directly
- **No handler** validates against `PROFILE_RESOURCE_SCOPES`

Exception: R20 computes `_admin_can()` but does not enforce it on POST (see section 12).

**Classification for all 24: E — CURRENTLY UNPROTECTED GRANULARLY.**

## 15. Required Denial Behavior

For all 24 routes when a denied role (e.g., consultivo on a POST mutation) accesses the route:

- **Non-AJAX request**: redirect to `admin_dashboard` with flash error message (standard response via `_admin_access_denied_response`)
- **AJAX request**: JSON 403 with `{"ok": false, "error": "forbidden", "resource": "...", "required_scope": "..."}`
- The `@admin_required` decorator remains the outer gate (anonymous → login redirect)
- The `enforce_admin_access_control` before-request handler checks the granular requirement

This matches the existing project-standard denial behavior from `main.py:5232-5245`.

## 16. Required No-Mutation Invariants

For every mutating route (POST), when access is denied:

| Route | Table | Invariant |
|-------|-------|-----------|
| R6 | `atividade_base` | Row count unchanged |
| R8 | `norma_atividade` | Row count unchanged |
| R10 | `atividade_versao` | Row count unchanged |
| R12 | `atividade_versao` | Row values unchanged for targeted versao_id |
| R13 | `atividade_versao` | `status` column unchanged for targeted versao_id |
| R14 | `atividade_versao` | `status` column unchanged |
| R15 | `atividade_versao` | `status` column unchanged |
| R16 | `atividade_versao`, `atividade_transicao` | Both tables unchanged |
| R18 | `matriz_atividade_versao_item` | Row count for matriz_id unchanged |
| R19 | `matriz_atividade_versao_item` | Row count for matriz_id unchanged |
| R20 | `atividades`, `atividade_base`, `atividade_legacy_map`, `atividade_versao`, `matrizes_atividades_itens`, `matriz_atividade_versao_item` | All 6 tables unchanged |
| R21 | `matriz_atividade_versao_item` | Row count for matriz_id unchanged |

No filesystem artifacts are created by any of these routes. The invariants apply to an isolated test database with fixture-controlled database state; no real institutional `database.db` access is permitted.

## 17. Existing Test Coverage

| Route | Tests | Coverage |
|-------|-------|----------|
| R1 | `test_admin_activity_version_catalog_readonly.py` | 200, title, admin-required |
| R2 | Same file | Detail listing, 404 handling, transition history |
| R3 | Same file | 200, seeded content, no forbidden terms |
| R4 | Same file | 200, filters, no-auto-map, total_changes |
| R5-R6 | `test_admin_activity_version_catalog_create.py` | GET 200, POST validation, duplicate rejection, no-forbidden-terms |
| R7-R8 | Same file | Norma create GET/POST |
| R9-R10 | `test_admin_activity_version_catalog_version_form.py` | Base validation, POST create, duplicate rejection |
| R11-R12 | `test_admin_activity_version_catalog_version_edit.py` | GET/POST edit, status guards, usage guards |
| R13 | `test_admin_activity_version_catalog_version_activate.py` | 17 tests: activation from each status, norma guard, resolver impact |
| R14-R15 | `test_admin_activity_version_catalog_version_lifecycle.py` | Inativar/descontinuar with B1 blocker, resolver impact |
| R16 | Same file | Substituir with full validation matrix |
| R17-R19 | `test_admin_matriz_versao_link.py` | GET 200, POST definir/remover, 7 validations, resolver impact, CSRF |
| R20 | `test_admin_matrix_new_activity.py` | Create activity from matrix, counts, rollback |
| R21 | `test_admin_matriz_nova_versao_card.py` | Relink matrix to existing version |
| R22-R23 | `test_activity_versioning_phase_d1_diagnostic.py` | JSON diagnostic endpoints, correctness of model |
| R24 | `test_activity_versioning_shadow_read_diagnostic.py` | Shadow read diagnostic, filters, limits |

All existing tests use a hardcoded admin user (`user_id=1` or `999999`) with implicit `admin_total` access level. **No test exercises consultivo, administrativo, or scope-denial paths.**

## 18. Missing Test Plan

The following test gaps must be filled in REF-0C-B1:

1. **Role access matrix tests** for all 24 routes:
   - `consultivo` → allowed on resolved GET `view` routes (R1-R4, R17), denied on GET `edit` routes (R5, R7, R9, R11), denied on all POST routes; R22-R24 remain pending D4
   - `administrativo` → allowed on all routes
   - `anonymous` → denied on all routes (redirect to login)
   - `aluno` → denied on all routes (redirect to login)

2. **Denial response tests** for at least one POST route per domain group:
   - POST returns status 302 with `/admin/dashboard` in Location header
   - Target table row count unchanged after denial

3. **CSRF tests** beyond current coverage (R16, R18, R19, R20, R21)

4. **UI visibility tests**: templates do not render action buttons for denied roles

## 19. Implementation Risks

1. **Resource vocabulary mismatch**: If `banco_dados`/`view` is chosen for R22-R23, consultivo would lose access to diagnostics they currently have. This is a behavioral change and must be approved.

2. **R20 readonly gap**: The `readonly` variable at line 12906 of `main.py` is computed but not enforced on POST. Two fixes are needed: (a) add the RBAC mapping; (b) decide whether to also enforce `readonly` or remove the variable. Both changes are in `main.py`, which is in the prohibited area for this phase but must be explicitly authorized for REF-0C-B.

3. **Side effect of RBAC mapping**: Adding mappings for these 24 routes means `enforce_admin_access_control` will start enforcing granular scope checks. Routes that previously passed through for consultivo (e.g., R22-R24) will now be denied if the chosen scope excludes consultivo. This is correct behavior but must be consciously accepted.

4. **No new resource vocabulary**: The analysis demonstrates that all 24 routes can be mapped using existing `atividades` and `matrizes` resources. This avoids the need for new resource/scopes but requires accepting the semantic stretch on R22-R24.

## 20. Recommended Phase Decomposition

### REF-0C-B1 — Strongly Supported RBAC Mappings (HIGH confidence)

Implement RBAC mappings for the 21 HIGH-confidence routes:
- `atividades`/`view`: R1, R2, R3, R4
- `atividades`/`edit`: R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15, R16
- `matrizes`/`view`: R17
- `matrizes`/`edit`: R18, R19, R21

Plus RBAC tests for role coverage, denial behavior, and immutability.

**This requires modifying `app/auth.py` and test files.**

### REF-0C-B2 — User-Approved Policy Decisions (MEDIUM confidence)

Implement decisions for R20 (readonly enforcement), R22-R24 (diagnostic resource choice), and D1-D4.

**Requires architectural decisions before implementation.**

### REF-0C-C — Fail-Closed Authorization Gate

Audit that no route exists without an explicit `get_admin_permission_requirement` entry. Consider converting the baseline to a fail-closed gate (reverse current logic: routes without mapping are denied by default, not allowed).

### REF-0C-D — Actor Matrix and Denied-Action Immutability

Formalize the actor matrix (who can do what) and immutability-after-denial tests for all admin routes.

## 21. REF-0C-A-R1 Superseding Corrections

This section supersedes any earlier conflicting statement in this document.

- R20 is HIGH confidence: `matrizes`/`edit`; `admin_total` and `administrativo` allowed; `consultivo` denied. The unused local `readonly` value is a separate enforcement or cleanup decision, not a policy ambiguity.
- R22-R24 are unresolved pending D4. `atividades`/`view` allows `admin_total`, `administrativo`, and `consultivo`. `banco_dados`/`view` allows only `admin_total`; both `administrativo` and `consultivo` are denied by the documented default scopes. No profile override changes that result.
- The required `admin_total` + `administrativo`, consultivo-denied diagnostic policy cannot be represented by the documented defaults using only `atividades`/`view` or `banco_dados`/`view`; it requires an explicit profile override, new resource, new scope, or endpoint-specific rule.
- Diagnostic vocabulary remains an explicit choice among `atividades`, `banco_dados`, or a new diagnostic-specific vocabulary if approved. No R22-R24 test may prescribe consultivo access before D4.
- The denial source is `main.py:5232-5245`. Denied-mutation checks use an isolated test database and fixture-controlled state, never the real institutional `database.db`.

## 22. Confirmation of Non-Implementation

No policy was implemented during this phase. No production file, test file, schema, database, UI, or configuration was changed. Only the three authorized documentation files were created or modified.

All 24 RBAC mappings are recommendations only. No mapping or authorization logic is active.
> **REF-0C-B2-A factual erratum (2026-07-18):** linked to decision commit
> `a9d375d` (`Document diagnostic RBAC and R20 policy options`). Static inspection
> of R22/R23 and their called helpers proves they do not query `alunos` or
> `requisicoes`; the R22 inventory below has been corrected and R23 remains “Same
> as R22.” This is factual only and does not alter accepted REF-0C-A policy
> conclusions or confidence classification.
