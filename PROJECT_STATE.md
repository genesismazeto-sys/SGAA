# Project State

Last updated: 2026-06-12
Closeout: D7.3D normative dry-run importer closeout
Executor: Claude Sonnet 4.6 (docs closeout); Kimi K2.6 (audit); executor-PATCH1 (implementation)

## Permanent State

### D6.4.0 - controlled snapshot write
- Implemented and approved.
- Flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE` exists and remains default `OFF` in code.
- Controlled activation in the target environment was validated.
- The target environment used port `5001` after a conflict on `5000`.
- Rollback was validated: with the flag `OFF`, new requests are created with versioned fields set to `NULL`.
- `atividade_id` remains preserved and operational.
- No backfill was performed.
- No read cutover was performed.

### D6.5 - admin-only diagnostics
- Implemented and approved.
- `/admin/requisicoes` shows the discrete badge `"Snapshot versionado"`.
- `/admin/processar_requisicao/<id>` shows the read-only block `"Diagnostico do snapshot"`.
- The diagnostic is admin-only.
- No student screen was changed.
- JOIN, calculation, decision, limits, and processing remain on the legacy `atividade_id`.
- Missing or invalid snapshot data does not break the screen.
- Raw JSON is not exposed.
- Forbidden fields do not leak: observations, free text, documents, paths, or additional personal data.

### D6.6 - admin read-only comparison display
- D6.6-DISPLAY-1 approved.
- Commit `b9ffda2` - `Add admin snapshot comparison display`.
- Commit `09749ef` - `Fix snapshot comparison labels`.
- D6.6-DISPLAY-TEXT-ACCENTS-1R approved.
- Flag `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY` exists and remains default `OFF` in code.
- The display flag is independent from `SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE`.
- The display flag is independent from `SGAA_VERSIONED_RESOLVER_SHADOW_READ`.
- With the flag `ON`, `/admin/processar_requisicao/<id>` `GET` shows the read-only comparison `Legado atual` vs `Snapshot versionado`.
- `/admin/requisicoes` did not gain a new comparison and still shows only the D6.5 badge.
- POST, processing, calculation, limits, and matrix scope remain on the legacy `atividade_id`.
- No backfill was performed.
- No cutover was performed.
- No student screen was changed.

### D6.7 - planning decision after D6.6 display
- D6.7-PLAN completed in read-only mode on `HEAD` `04b40cc`.
- No code, template, test, database, env, flag, or schema change was made during the analysis.
- Recommendation: pause at D6.6.
- `/admin/processar_requisicao/<id>` `GET` is already the safe and sufficient diagnostic surface.
- `/admin/processar_requisicao/<id>` `POST` remains legacy and out of scope.
- `/admin/requisicoes` should remain badge-only.
- Student request screens should not receive snapshot display now.
- Dashboards, progress, turma, and import flow remain out of scope.
- Snapshot remains admin-only, diagnostic, and read-only.
- `atividade_id` remains the operational source of truth.
- No backfill was performed.
- No read cutover was performed.
- No operational use of snapshot data was approved.

### D7.1 - activity version matrix contract tests
- Implemented and approved.
- Commit `e0427ee` — `Add activity version matrix contract tests`.
- Added helper `_get_turma_explicit_matriz_id_for_snapshot`.
- Added pre-check in `maybe_write_versioned_requisicao_snapshot`.
- Proved contract: if `turma.matriz_id` is `NULL`, the writer does **not** stamp `atividade_versao_id`.
- Ambiguity of version remains a hard error.
- Resolver remains read-only.
- No UI was changed.
- No schema was changed.
- No calculation or deferment was changed.
- No cutover or backfill was performed.
- `app/db.py` contains auto-fill in a seed/dev tool, but that does not run in the normal runtime of this branch.

### D7.2B1 - read-only activity version catalog (admin)
- Implemented and approved.
- Commit `73d45ac` — `Add read-only activity version catalog`.
- Commit `a3537cf` — `Fix activity version catalog card grids`.
- Read-only helpers added in `main.py`.
- 4 admin `GET` routes:
  - `/admin/catalogo-versoes`
  - `/admin/catalogo-versoes/<base_id>`
  - `/admin/normas-atividade`
  - `/admin/mapeamento-legado`
- 4 new templates:
  - `admin_catalogo_versoes.html`
  - `admin_catalogo_versao_detalhe.html`
  - `admin_normas_atividade.html`
  - `admin_mapeamento_legado.html`
- New test file: `tests/test_admin_activity_version_catalog_readonly.py`.
- CSS adjustments in `static/css/components/list-cards.css` with overrides for `.imp-catalogo`, `.imp-normas`, and `.imp-mapeamento`.
- Tests: D7.2B1 specific `17 passed`; D7.1/resolver/aluno scope regressions `17 passed`.
- Runtime check: `/admin/catalogo-versoes` `200`; `/admin/catalogo-versoes/1` `200`; `/admin/catalogo-versoes/999999` clean redirect, no `500`; `/admin/normas-atividade` `200`; `/admin/mapeamento-legado` `200`.
- CSS fix validated visually: no overflow on listings, final columns visible.
- Guarantees preserved: no new `POST`, no DB writes through the new routes, no auto-mapping, no student change, no operational matrix change, no calculation/deferment change, no schema/migration, no snapshot writer, no flags, no menu/sidebar entry, no backfill, no cutover.
- `main` / `origin/main` intact at `7e5eb56`.

### D7.2B2 - controlled creation of activity base and norms (admin)
- Implemented and approved.
- Commit `b91d03f` — `Add create forms for activity base and norms`.
- Commit `44d367a` — `Clarify activity version creation placeholder`.
- 2 new admin `GET/POST` routes:
  - `/admin/catalogo-versoes/nova-base`
  - `/admin/normas-atividade/nova`
- 2 new templates:
  - `templates/admin_catalogo_base_form.html`
  - `templates/admin_norma_form.html`
- Buttons `Nova base` and `Nova norma` enabled in the existing list screens
  (`templates/admin_catalogo_versoes.html` and `templates/admin_normas_atividade.html`).
- New test file: `tests/test_admin_activity_version_catalog_create.py`.
- Validations for `atividade_base`:
  - `nome_conceito` required;
  - whitespace trim;
  - empty name rejected;
  - `status` restricted to `ativo`/`inativo`;
  - duplicate rejected by case-insensitive pre-check;
  - success redirects to the detail of the created base.
- Validations for `norma_atividade`:
  - `codigo` required;
  - `codigo` trimmed;
  - `eixo` restricted to `AAC`/`AEU`;
  - `revisao` required;
  - `status` restricted to `ativa`/`inativa`;
  - duplicate rejected by case-insensitive pre-check;
  - success redirects to `/admin/normas-atividade`.
- Runtime check:
  - backup created before real `POST`s;
  - `GET`s of the new screens returned `200`;
  - invalid `POST`s did not insert rows;
  - valid `POST`s created temporary `D7TEMP` rows;
  - `D7TEMP` rows removed surgically by `id`/`codigo`/`nome`;
  - zero `D7TEMP` rows remaining;
  - `PRAGMA foreign_key_check` reported no violations;
  - hashes and counts of relevant tables returned to baseline;
  - local database restored to the pre-phase state;
  - `64 passed` tests.
- Textual fix in `44d367a`:
  - in `templates/admin_catalogo_versao_detalhe.html`, removed the obsolete
    reference to D7.2B2 in the version-creation placeholder;
  - placeholder now uses `fase posterior`;
  - `Criar versão` button remains disabled;
  - no new route, `POST`, or version-creation functionality was introduced;
  - `47 passed` tests.
- Guarantees preserved:
  - no `atividade_versao` creation;
  - no edit;
  - no legacy mapping save;
  - no change in `matriz_atividade_versao_item`;
  - no change in `matrizes_atividades_itens`;
  - no change in `aluno`;
  - no change in calculation/deferment;
  - no schema/migration change;
  - no snapshot writer;
  - no flags;
  - no menu/sidebar entry;
  - no backfill;
  - no cutover.
- `main` / `origin/main` intact at `7e5eb56`.

### D7.2B3-PATCH1 - draft activity version creation
- Implemented and approved.
- Commit `16b1480` — `Add draft activity version creation`.
- Commit `ccf1a7e` — `Record D7.2B3 draft version creation`.
- 1 new admin `GET/POST` route:
  - `/admin/catalogo-versoes/<int:base_id>/nova-versao`
- 1 new template: `templates/admin_catalogo_versao_form.html`.
- 1 updated template: `templates/admin_catalogo_versao_detalhe.html` (button enabled).
- 1 new test file: `tests/test_admin_activity_version_catalog_version_form.py` (17 tests).
- Helpers added in `main.py`:
  - `get_norma_by_id(conn, norma_id)` — read-only lookup.
  - `get_versoes_da_base_por_eixo(conn, base_id, eixo)` — read-only lookup now
    actively used to populate the optional `versao_anterior_id` select.
- Functional guarantees:
  - rota GET/POST `/admin/catalogo-versoes/<base_id>/nova-versao`;
  - helper `get_norma_by_id`;
  - helper `get_versoes_da_base_por_eixo` agora usado no formulário;
  - criação de `atividade_versao` com status forçado em rascunho;
  - `codigo_normativo` derivado de `norma_atividade.codigo`;
  - `eixo` derivado de `norma_atividade.eixo`;
  - `norma_id` obrigatório, sem primeira norma automática;
  - select de norma com placeholder obrigatório;
  - `versao_anterior_id` como select opcional com placeholder "Sem versão anterior";
  - validação server-side de base, norma ativa, duplicidade base+norma,
    números inválidos/negativos, versão anterior inexistente, de outra base
    ou de eixo incompatível;
  - botão "Criar versão" habilitado no detalhe da atividade-base;
  - novo template `templates/admin_catalogo_versao_form.html`;
  - novo teste `tests/test_admin_activity_version_catalog_version_form.py`
    com 17 testes;
  - suíte parcial validada com 91 passed.
- Garantias explícitas de fora do escopo do PATCH1:
  - edição de versão;
  - ativação/publicação;
  - vínculo com matriz;
  - UI de matriz;
  - fluxo do aluno;
  - cálculo/deferimento;
  - snapshot writer;
  - schema/migration;
  - backfill/cutover;
  - importação de regulamentos reais;
  - menu/sidebar;
  - mapeamento legado salvo.
- `main` / `origin/main` intact at `7e5eb56`.
- Branch `recovery/d7-activity-versioning` pushed to origin at `ccf1a7e`.

### D7.2B3-PATCH2 - draft activity version editing
- Implemented and approved locally.
- Commit `c90ffe3` — `Add draft activity version editing` (current `HEAD`).
- 1 new admin `GET/POST` route:
  - `/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/editar`
- 2 new helpers in `main.py`:
  - `get_atividade_versao_by_id(conn, versao_id)` — read-only lookup with JOIN to base.
  - `get_atividade_versao_usage_counts(conn, versao_id)` — read-only usage check
    across `matriz_atividade_versao_item`, `requisicoes`, `atividade_transicao`.
- Template `admin_catalogo_versao_form.html` parametrized for creation and editing
  (`form_action`, `form_title`, `submit_label`).
- Template `admin_catalogo_versao_detalhe.html` gains an "Ações" column:
  - "Editar" link visible only when versão status is `rascunho`.
- New test file:
  `tests/test_admin_activity_version_catalog_version_edit.py` (28 tests).
- Functional guarantees:
  - edição permitida **somente** para `status = 'rascunho'`;
  - GET e POST bloqueiam versões `ativa`, `inativa`, `descontinuada`, `substituida`;
  - bloqueio total se a versão tiver **qualquer uso** em:
    - `matriz_atividade_versao_item`;
    - `requisicoes.atividade_versao_id`;
    - `atividade_transicao.from_atividade_versao_id`;
    - `atividade_transicao.to_atividade_versao_id`;
  - `codigo_normativo` recalculado de `norma_atividade.codigo`;
  - `eixo` recalculado de `norma_atividade.eixo`;
  - `status` **não editável** (ignorado via payload);
  - `atividade_base_id` **não editável** (ignorado via payload);
  - `created_at` preservado;
  - `documentos_json` preservado e fora do escopo do PATCH2;
  - validação de norma obrigatória, existente e ativa;
  - validação de duplicidade base+norma ignorando a própria versão;
  - validação de números: vazios → NULL, não numéricos rejeitados, negativos rejeitados;
  - validação de `versao_anterior_id` opcional:
    - deve existir;
    - deve pertencer à mesma base;
    - deve ter mesmo eixo;
    - não pode ser a própria versão.
- Explicitly out of scope:
  - ativação/publicação;
  - edição de status;
  - vínculo com matriz ou UI de matriz escolhendo versão;
  - fluxo do aluno;
  - cálculo/deferimento/indeferimento;
  - snapshot writer;
  - schema/migration;
  - backfill/cutover;
  - importação de regulamentos reais;
  - menu/sidebar;
  - `documentos_json`;
  - mapeamento legado salvo.
- Test suite validated: **119 passed**.
- `main` / `origin/main` intact at `7e5eb56`.
- Branch `recovery/d7-activity-versioning` local at `c90ffe3`; not yet pushed.

### D7.2B3-PATCH3 - draft activity version activation
- Implemented, approved, and pushed.
- Commit `28d922d` — `Add draft activity version activation`.
- Commit pushed to `origin/recovery/d7-activity-versioning` at `28d922d`.
- `main` / `origin/main` intact at `7e5eb56`.
- 1 new admin POST route:
  - `/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/ativar`
- Functional guarantees:
  - ativação explícita `status = 'rascunho'` → `status = 'ativa'`;
  - `@admin_required` na rota;
  - validação server-side: base existe, versão existe e pertence à base, status == `'rascunho'`, norma vinculada existe e está `'ativa'`;
  - `UPDATE atividade_versao SET status='ativa' WHERE id=? AND status='rascunho'` com rowcount check;
  - rollback + flash + redirect em falha, sem 500;
  - commit + flash + redirect no sucesso;
  - botão/form "Ativar" apenas para versões em rascunho no template de detalhe;
  - `csrf_token` real renderizado no form;
  - confirmação JS (`window.confirm`) é apenas UX; segurança é server-side.
- Change in `tests/test_csrf_inventory_audit.py` (56 lines):
  - **apenas seed/evidência real**: inserção de `atividade_base`, `norma_atividade` (ativa) e `atividade_versao` (rascunho) no setup isolado;
  - adição de `base_id` e `versao_id` ao `sample_values` do crawler;
  - **sem whitelist, sem bypass, sem relaxamento de política CSRF, sem remoção de rota do inventário.**
- Decisões de produto aplicadas:
  - **D1** — múltiplas versões ativas permitidas no catálogo; bloqueio de ambiguidade fica para fase de vínculo matriz→atividade_versao.
  - **D2** — norma vinculada inativa bloqueia ativação.
  - **D3** — CH, limites e vigência não são exigidos para ativação.
  - **D4** — confirmação simples no form (JS opcional), segurança server-side.
- Testes validados:
  - `test_csrf_inventory_audit.py` — **2 passed**;
  - `test_admin_activity_version_catalog_version_activate.py` — **17 passed** (novo);
  - `test_admin_activity_version_catalog_version_edit.py` — **28 passed**;
  - `test_admin_activity_version_catalog_version_form.py` — **17 passed**;
  - `test_matriz_versao_contract.py` + `test_activity_versioning_resolver.py` — **14 passed**;
  - `pytest -q --tb=line` (full suite) — **367 passed**, 4 warnings (openpyxl deprecation).
- Explicitly out of scope:
  - inativação/descontinuação/substituição de versão;
  - auditoria de "quem ativou quando";
  - vínculo matriz → atividade_versao;
  - UI de matriz escolhendo versão;
  - fluxo do aluno;
  - cálculo/deferimento/indeferimento;
  - snapshot writer;
  - schema/migration;
  - backfill/cutover;
  - importação de regulamentos reais;
  - menu/sidebar;
  - primeira ativa ou fallback silencioso.
- Artifacts CSRF gerados por teste (`tests/_artifacts/csrf_inventory_shadow_*.json`) foram restaurados e não fazem parte do closeout.

### D7.2B4-PATCH1 - admin UI for explicit matrix→atividade_versao links
- Implemented and committed.
- Commit `255ff80` — `Add admin UI for explicit matrix→atividade_versao links (D7.2B4)`.
- Branch `recovery/d7-activity-versioning` at `255ff80` (not yet pushed to origin).
- `main` / `origin/main` intact at `7e5eb56`.
- **New helpers in `main.py`** (read-only + write, all scoped to admin routes):
  - `get_bases_escopo_matriz(conn, matriz_id)` — bases in matrix legacy scope via `matrizes_atividades_itens + atividade_legacy_map`.
  - `get_versoes_ativas_por_base_na_matriz(conn, matriz_id, base_id)` — active versions for a base whose norma is in `matriz_norma` for this matrix.
  - `get_vinculo_versao_da_matriz(conn, matriz_id, base_id)` — single explicit link from `matriz_atividade_versao_item` for a matriz+base.
  - `_set_versao_da_matriz_para_base(conn, matriz_id, base_id, versao_id)` — DELETE old + INSERT new, enforcing max-1 per matriz+base.
  - `_remover_versao_da_matriz_para_base(conn, matriz_id, base_id)` — removes any link for this matriz+base, returns rowcount.
- **3 new admin routes**:
  - `GET  /admin/matrizes/<id>/versoes` → `admin_matriz_versoes` (page listing all scope bases with their current link and available versions).
  - `POST /admin/matrizes/<id>/versoes/definir` → `admin_matriz_versoes_definir` (set/replace explicit link, 7 server-side validations).
  - `POST /admin/matrizes/<id>/versoes/remover` → `admin_matriz_versoes_remover` (remove link, idempotent).
- **Server-side validations in `admin_matriz_versoes_definir`**:
  1. Matriz exists.
  2. `base_id` and `versao_id` are digits.
  3. `atividade_base` exists.
  4. `atividade_versao` exists.
  5. Versão belongs to the given base.
  6. Versão `status == 'ativa'`.
  7. Base is in the matrix's legacy scope (`matrizes_atividades_itens + atividade_legacy_map`).
  8. Versão's `norma_id` is in `matriz_norma` for this matrix.
  - Rollback + flash + redirect on error; commit + flash + redirect on success.
- **1 new template**: `templates/admin_matriz_versoes.html`.
  - Table: Atividade-base | Versão atual | Definir versão ativa | Remover vínculo.
  - "Definir" form only shown when `versoes_disponiveis` non-empty.
  - "Remover" form only shown when `vinculo` is set.
  - Both forms include `name="csrf_token"` with `{{ csrf_token() }}`.
- **Updated template**: `templates/admin_matriz_form.html`.
  - "Versões" tab added in both `{% if activity_tabs_enabled %}` branch (active link to `admin_matriz_versoes`) and `{% else %}` branch (disabled span).
- **New test file**: `tests/test_admin_matriz_versao_link.py` — **14 tests** covering:
  1. GET 200.
  2. UI shows scope bases.
  3. Helper returns only ativas.
  4. Helper excludes rascunho/inativa/descontinuada/substituida.
  5. POST rejects version whose norma is not in `matriz_norma`.
  6. POST creates valid link in DB.
  7. POST replaces previous link (no duplicates per matriz+base).
  8. POST removes link.
  9. Resolver resolves after link set.
  10. Resolver returns `base_without_version_for_matrix` after link removed.
  11. POST rejects base not in matrix's legacy scope.
  12. POST rejects version with norma absent from `matriz_norma`.
  13. No first-active fallback without explicit link.
  14. CSRF token present in rendered POST forms.
- **Updated test**: `tests/test_csrf_inventory_audit.py` — seed data added (norma ativa, versão ativa, atividade_legacy_map, matrizes_atividades_itens, matriz_norma, matriz_atividade_versao_item) so the CSRF crawler renders the POST forms for the 2 new mutating routes.
- **Test suite**: **381 passed**, 4 warnings (openpyxl). Up from 367 (+14 from new file, net).
- **Permanent constraints preserved**:
  - `resolver_versao_por_matriz` / `resolver_versao_por_aluno` / `resolver_versao` / `maybe_write_versioned_requisicao_snapshot` — untouched.
  - No silent fallback / no first-active / version ambiguity remains a hard error.
  - No version inference by name / eixo / date.
  - No calculation / deferment / student screens changed.
  - No schema / migration.
  - No backfill / cutover.
  - No merge to main.
- Explicitly out of scope:
  - Inativação/descontinuação/substituição de versão.
  - Bulk import / real regulations.
  - Matrix operational join switch.
  - Student screens / calculation / deferment.
  - Snapshot writer.

### D7.2B5-PATCH1 - admin lifecycle transitions for atividade_versao
- Implemented and committed.
- Commit `f235f62` — `Add admin lifecycle transitions for atividade_versao (D7.2B5)`.
- Branch `recovery/d7-activity-versioning` at `f235f62` (not yet pushed to origin).
- `main` / `origin/main` intact at `7e5eb56`.
- **2 new admin POST routes**:
  - `POST /admin/catalogo-versoes/<base_id>/versoes/<versao_id>/inativar` → `admin_catalogo_inativar_versao`.
  - `POST /admin/catalogo-versoes/<base_id>/versoes/<versao_id>/descontinuar` → `admin_catalogo_descontinuar_versao`.
- **Functional guarantees**:
  - Ambas exigem `@admin_required` e CSRF real no form.
  - Validação server-side: base existe, versão existe e pertence à base da URL, status atual == `'ativa'`.
  - **Bloqueio B1**: rejeita se houver qualquer vínculo em `matriz_atividade_versao_item`; mensagem orienta o admin a remover o vínculo na tela de versões da matriz primeiro, sem realizar nenhum efeito colateral.
  - `UPDATE atividade_versao SET status = 'inativa'/'descontinuada' WHERE id = ? AND status = 'ativa'` com rowcount check.
  - Rollback + flash + redirect em falha; commit + flash + redirect em sucesso.
  - A versão inativada/descontinuada sai automaticamente do escopo do resolvedor (pois `_atividade_versao_status_ativo` retorna `False` para esses status) sem nenhuma alteração no resolvedor.
- **Template `templates/admin_catalogo_versao_detalhe.html`**:
  - Nova branch `{% elif status_key == 'ativa' %}` na coluna Ações com botões "Inativar" (âmbar) e "Descontinuar" (vermelho).
  - Ambos os botões têm `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
  - Confirmação JS (`window.confirm`) é apenas UX; segurança é server-side.
  - CSS: `.vc-inativar-btn` e `.vc-descontinuar-btn` adicionados ao bloco `<style>`.
- **New test file**: `tests/test_admin_activity_version_catalog_version_lifecycle.py` — **19 tests**:
  1–8: inativar — ativa sem vínculo, inexistente, outra base, já inativa, rascunho, descontinuada, substituida, com vínculo (bloqueio B1 completo).
  9: resolver retorna ausência de versão após inativar.
  10–14: descontinuar — ativa sem vínculo, com vínculo, rascunho, já descontinuada, inativa.
  15–17: template — buttons rendered for ativa only, not rascunho, not outros.
  18: CSRF token presente em ambos os forms.
  19: regressão D7.2B4 — inativar versão A não quebra resolver para versão B da mesma matriz.
- **CSRF inventory test** (`tests/test_csrf_inventory_audit.py`): **sem alterações** — `versao_lnk_id` (ativa, da seed D7.2B4) já fornece evidência renderizada para ambas as novas rotas POST.
- **Test suite**: **400 passed**, 4 warnings (openpyxl). Up from 381 (+19 from new file, net).
- **Permanent constraints preserved**:
  - `resolver_versao_por_matriz` / `resolver_versao_por_aluno` / `resolver_versao` / `maybe_write_versioned_requisicao_snapshot` — untouched.
  - No silent fallback / no first-active / version ambiguity remains a hard error.
  - No DELETE automático de `matriz_atividade_versao_item`.
  - No `atividade_transicao` created.
  - No version substituta chosen.
  - No calculation / deferment / student screens changed.
  - No schema / migration.
  - No backfill / cutover.
  - No merge to main.
- **Explicitly out of scope**:
  - Substituição de versão (`substituida`).
  - Reativação de versão inativa ou descontinuada.
  - `atividade_transicao`.
  - Auditoria de quem inativou/descontinuou.
  - Bulk import / real regulations.
  - Student screens / calculation / deferment.
  - Snapshot writer.

### D7.2B5-PATCH2 - explicit activity version substitution
- Implemented and committed.
- Commit `9d2e9fb` - `Add explicit activity version substitution`.
- Branch `recovery/d7-activity-versioning` later advanced to docs closeout `5f7dbc8`, aligned with `origin/recovery/d7-activity-versioning`.
- `main` / `origin/main` intact at `7e5eb56`.
- 1 new admin POST route:
  - `/admin/catalogo-versoes/<int:base_id>/versoes/<int:versao_id>/substituir`
- Functional guarantees:
  - explicit substitution only; no fallback and no implicit target selection;
  - origin must exist, belong to the URL base, and be `status = 'ativa'`;
  - origin is blocked if any `matriz_atividade_versao_item` link exists;
  - `to_versao_id` is mandatory and must be a valid integer;
  - destination must exist, be `status = 'ativa'`, belong to the same `atividade_base`, have the same `eixo`, and differ from origin;
  - origin cannot already be `from_atividade_versao_id` in `atividade_transicao`;
  - destination cannot already be `from_atividade_versao_id` in `atividade_transicao`;
  - operation is transactional: `UPDATE atividade_versao SET status='substituida'` on origin + `INSERT INTO atividade_transicao (..., tipo_transicao='mesmo_eixo')`;
  - rollback on failure; commit on success.
- Template `templates/admin_catalogo_versao_detalhe.html` updated:
  - active versions now render a `Substituir` form;
  - form includes explicit `to_versao_id` select with active same-base same-axis candidates only, excluding the origin itself;
  - form is disabled when no valid candidate exists;
  - CSRF token present in the rendered form.
- Scope explicitly unchanged:
  - no resolver changes;
  - no snapshot writer changes;
  - no schema/migration changes;
  - no aluno/calculation/deferment changes;
  - no `aac_para_aeu`;
  - no reactivation.
- Focused tests already executed:
  - lifecycle + activate/edit/form: `96 passed`;
  - matriz/resolver/csrf: `30 passed`;
  - lifecycle isolated: `34 passed`.

### D7.2B6 - admin transition history (read-only)
- Implemented, validated, committed, and published.
- Functional commit published on `recovery/d7-activity-versioning`:
  - `95cb897` - `Add admin transition history for activity versions`
  - remote hash: `95cb89797f1a0a16ff812933d9788f2019b14ad4`
- Branch state after functional push:
  - `origin/recovery/d7-activity-versioning...HEAD = 0 0`
  - `origin/main...main = 0 0`
  - working tree was clean after the functional push
  - `main` / `origin/main` remained at `7e5eb56`
- Functional scope delivered:
  - new read-only helper `get_atividade_transicoes_por_base`;
  - `JOIN` entre `atividade_transicao` e versões origem/destino;
  - filtro por `atividade_base` da origem ou do destino;
  - payload com `versao_origem`, `versao_destino`, `tipo_transicao`, `eixo`, `created_at` e `motivo`;
  - `motivo` usa `justificativa` ou `observacao_admin` ou fallback `"-"`;
  - rota `GET /admin/catalogo-versoes/<base_id>` passa `transicoes_historico` ao template existente;
  - `templates/admin_catalogo_versao_detalhe.html` ganhou a seção read-only `Histórico de transições` com tabela e estado vazio.
- Garantias preservadas:
  - sem `POST` novo;
  - sem CSRF novo;
  - sem schema/triggers;
  - sem fluxo do aluno;
  - sem cálculo/deferimento;
  - sem writer/versioned snapshot;
  - sem matriz;
  - sem alteração da lógica de ativar/inativar/descontinuar/substituir.
- Testes executados:
  - `python -m pytest tests/test_admin_activity_version_catalog_readonly.py -q --tb=short` → `21 passed in 10.03s`;
  - `python -m pytest tests/test_admin_activity_version_catalog_version_lifecycle.py -q --tb=short` → `34 passed in 102.08s`.
- Revisão visual executada:
  - renderização headless temporária do template;
  - cenário sem transições exibiu `Nenhuma transição registrada para esta atividade-base.`;
  - cenário com transição exibiu origem, destino, `tipo_transicao`, fallback `"-"` em motivo e `created_at`;
  - botões `Ativar`, `Inativar`, `Descontinuar` e `Substituir` permaneceram visíveis sem quebra visual óbvia.
- Riscos residuais:
  - `created_at` segue exibido em formato cru do SQLite;
  - não há auditoria de ator/admin na tabela `atividade_transicao`;
  - a UI lista tipos de transição de forma genérica, sem fluxo novo para além de `mesmo_eixo`.
- Status de projeto após a publicação:
  - branch ativa continua `recovery/d7-activity-versioning`;
  - `HEAD` da branch avança além de `95cb897` apenas com closeouts documentais subsequentes;
  - D7.2B6 funcional está fechada e publicada em `95cb897`;
  - próxima fase ainda não foi iniciada.

### D7.3A - normative canonization of AAC/AEU regulations
- Accepted as read-only documental diagnosis. No code, template, test, DB, or seed change.
- Documents analyzed (stored in `_normativos_inbox/`, excluded from Git):
  - `ACC-rev5.docx` — Regulamento de Atividades Complementares antigo (160 h, 5 grupos).
  - `ACC-rev6.docx` — Regulamento de Atividades Complementares atualizado, simplificado.
  - `AE-rev1.docx` — Regulamento de Atividades de Extensão Universitária (Res. CNE/CES 7/2018).
- Canonization accepted:
  - `ACC-rev5.docx` → internal codigo_normativo **AAC-rev5** (eixo AAC, revisão rev5).
  - `ACC-rev6.docx` → internal codigo_normativo **AAC-rev6** (eixo AAC, revisão rev6).
  - `AE-rev1.docx` → internal codigo_normativo **AEU-rev1** (eixo AEU, revisão rev1).
- Normative status:
  - AAC-rev5: histórico/legado, preservado para matrizes legadas quando aplicável.
  - AAC-rev6: AAC vigente.
  - AEU-rev1: AEU vigente.
- Key differences ACC-rev5 vs ACC-rev6:
  - ACC-rev6 simplifies documentation requirements for several categories.
  - ACC-rev6 removes "Horas de voo em simulador".
  - ACC-rev6 removes/relocates "Trabalho voluntário em organizações do terceiro setor" to AEU.
  - ACC-rev6 separates "Projetos de apoio institucional" from "Projetos de extensão".
  - ACC-rev6 simplifies book reading to 10h/book (was 5h non-technical / 10h technical).
  - ACC-rev6 reduces minimum report length (2 pages instead of 3).
- Key differences AAC vs AEU:
  - AEU requires interaction with external community.
  - Trabalho voluntário em terceiro setor migrates to AEU.
  - Projetos de extensão belong to AEU axis.
  - AEU has own activities: organização de eventos extensionistas, participação em
    eventos extensionistas, cursos/oficinas/palestras para comunidade externa.
  - Ambiguous cases between "apoio institucional" and "extensão" require human decision.
- Schema/model gaps:
  - Conditional workload rules depend on observation fields.
  - Documentation requirements and annexes have no dedicated structured fields.
  - AEU-rev1 does not define mandatory total workload; depends on PPC.
  - AAC→AEU transitions must be explicit and justified.
  - Direct DOCX import must not be the primary operational source.
- Architectural decision:
  - D7.3B must not import directly from DOCX to the production database.
  - Preferred next step: create a reviewable canonical fixture (YAML/JSON/CSV),
    derived from the DOCX and audited, before any importer.
  - Only then create a dry-run importer consuming the fixture.
  - Dry-run importer must not touch matrix, requests, student, calculation, or deferment.
- DOCX disposal: the DOCX files are local diagnostic inputs in `_normativos_inbox/`,
  excluded from Git via `.git/info/exclude`, and must not be committed at this stage.
- Next step: plan D7.3B as reviewable canonical specification/fixture; do not implement yet.

### D7.3B-PLAN - Fixture format specification
- Accepted as read-only specification. No code, template, test, DB, or seed change.
- Format: YAML chosen over JSON/CSV for human readability, multiline support, and Git diff clarity.
- Directory: `normative_fixtures/` (no `data/` directory exists in project).
- Structure: `meta`, `normas`, `atividades` with `versoes`, `atividade_removida_em`, `atividade_nova_em`, `transicao_proposta`.
- `status_inicial` = "rascunho" for all versions.
- `ch_regra_condicional` uses controlled vocabulary: null, equivalente_curso, equivalente_horas, tempo_declarado_ou_limite, carga_declarada_ou_limite_evento, tier_documental, horas_por_evento, horas_por_banca, regra_especial_ivao, exige_decisao_humana.
- `[REGRA: ...]` and `[ANEXOS: ...]` prefixes used in `observacao_admin` to preserve normative metadata.
- `transicao_proposta` must include `de` (from norma), `para` (to norma), `tipo`, `justificativa`.
- `atividade_nova_em` only for activities that are genuinely new and do not exist in previous norms.
- `atividade_removida_em` only for activities that exist in previous norms but not in the current one.
- Next step: create the canonical fixture YAML (D7.3C).

### D7.3C - Canonical fixture creation
- Scope: create the real canonical normative fixture YAML from the three DOCX regulations.
- Output: `normative_fixtures/d73c_normative_fixture.yaml`.
- Contents validated:
  - 3 normas: AAC-rev5 (29 activities), AAC-rev6 (27 activities), AEU-rev1 (5 activities).
  - 32 unique conceptual activities mapped to `atividade_base`.
  - 61 total versions across all norms.
  - 2 activities removed in AAC-rev6: SIMULADOR_VOO, TRAB_VOLUNTARIO_TERCEIRO_SETOR.
  - 3 native AEU activities: ORG_EVENTOS_EXTENSIONISTAS, PART_EVENTOS_EXTENSIONISTAS, CURSOS_OFICINAS_PALESTRAS_COMUNIDADE.
  - 1 explicit transition: TRAB_VOLUNTARIO_TERCEIRO_SETOR (AAC-rev5 → AEU-rev1, tipo: aac_para_aeu).
  - PROJETOS_EXTENSAO is ambiguous (AAC apoio institucional vs AEU extensão) and requires human decision (noted in `observacao_admin` of AEU-rev1 version).
  - `status_inicial` = "rascunho" for all 61 versions.
  - `ch_regra_condicional` uses controlled vocabulary throughout; no invalid values.
  - YAML validated with Python `yaml.safe_load` → `YAML_OK`.
  - Deep validation: no invalid `ch_regra_condicional` values, no missing required fields.
- No code, template, test, DB, or seed was changed during D7.3C.
- The DOCX files remain in `_normativos_inbox/` and are excluded from Git.
- Next step: D7.3D dry-run importer consuming the fixture YAML into an isolated DB.

### D7.3D-PATCH1 - normative dry-run importer
- Implemented, audited, and committed.
- D7.3D-PATCH1-REVIEW executed by Kimi K2.6 in read-only mode: ACEITAR D7.3D-PATCH1.
- New files:
  - `tools/d73d_normative_importer_dryrun.py` — CLI dry-run importer.
  - `tests/test_d73d_normative_importer_dryrun.py` — test suite (5 tests).
- Modified file:
  - `requirements.txt` — added `PyYAML==6.0.2`.
- Functional guarantees:
  - `--fixture` obrigatório; `--report text/json`; `--strict` trata warnings como erro.
  - Sem `--apply`, sem modo real, sem importação operacional.
  - Recusa `--db` com basename `database.db` (case-insensitive) antes de qualquer conexão.
  - Não importa `main`, `create_app`, `init_db`, ou `APP_DATABASE`.
  - Banco temporário criado via `tempfile.NamedTemporaryFile` e removido em `finally`.
  - `database.db` real preservado: tamanho e SHA256 inalterados após qualquer execução.
  - Schema SCHEMA_SQL idêntico ao de `main.py` (4 tabelas + 6 triggers).
  - Validações de fixture: YAML parseável; top-level meta/normas/atividades; normas únicas; códigos únicos; nomes canônicos únicos (NFKD); norma_ref existente; transicao_proposta de/para existentes; ch_regra_condicional em vocabulário aprovado; documentacao_exigida não vazia se presente; atividade_removida_em sem versão indevida; atividade_nova_em sem versão legada indevida salvo exige_decisao_humana.
  - Idempotência: segunda execução no mesmo `--db` produz inserted=0, skipped=3/32/61/1.
  - Transação atômica: rollback automático se qualquer insert falhar.
- Contagens validadas com `normative_fixtures/d73c_normative_fixture.yaml`:
  - 3 normas, 32 bases, 61 versões, 1 transição.
  - Todas as versões inseridas com status `rascunho`.
  - 2 removidas em AAC-rev6 não geram versão na norma removida.
  - 3 nativas AEU presentes somente em AEU-rev1.
  - Transição AAC-rev5 → AEU-rev1 (aac_para_aeu) com eixos corretos.
- Testes:
  - `python -m pytest tests/test_d73d_normative_importer_dryrun.py -q --tb=short`
  - Executor: 5 passed in 7.40s.
  - Auditor: 5 passed in 4.07s.
- Risco backlog [B-01]: `documentacao_exigida` validada somente quando a chave existe; futura iteração pode tornar a chave obrigatória em toda versão.
- Importação real para `database.db` não foi executada. D7.3D fica fechada neste ponto.
- Próximo passo: não iniciar importador real sem escopo explícito aprovado.

## Relevant Commits

- `483f069` - Add controlled versioned snapshot write for requests
- `ba5a3df` - Document snapshot write activation runbook
- `8845dce` - Record controlled snapshot activation validation
- `18c169a` - Record target snapshot activation validation
- `bb1ca51` - Add admin snapshot diagnostics
- `b9ffda2` - Add admin snapshot comparison display
- `09749ef` - Fix snapshot comparison labels
- `e0427ee` - Add activity version matrix contract tests
- `73d45ac` - Add read-only activity version catalog
- `a3537cf` - Fix activity version catalog card grids
- `b91d03f` - Add create forms for activity base and norms
- `44d367a` - Clarify activity version creation placeholder
- `16b1480` - Add draft activity version creation
- `ccf1a7e` - Record D7.2B3 draft version creation
- `c90ffe3` - Add draft activity version editing
- `28d922d` - Add draft activity version activation
- `255ff80` - Add admin UI for explicit matrix→atividade_versao links (D7.2B4)
- `f235f62` - Add admin lifecycle transitions for atividade_versao (D7.2B5)
- `9d2e9fb` - Add explicit activity version substitution
- `5f7dbc8` - Record D7.2B5-PATCH2 substitution closeout
- `95cb897` - Add admin transition history for activity versions
- `cbde400` - Record D7.3A normative canonization
- `5f66239` - Add D7.3C canonical normative fixture and docs closeout
- TBD        - Add D7.3D normative dry-run importer

## Current Risks And Limits

- D6.6 remains admin-only display work, not an operational read path based on snapshot data.
- Snapshot data must not be used to approve or reject requests.
- Snapshot data must not be used to calculate hours or limits.
- Snapshot data must not be used for matrix scope, dashboards, import flow, or student screens.
- Import flow remains out of scope.
- Student dashboards and progress remain on the legacy path.
- Backfill for old requests has not been performed yet.
- D6.7 concluded with the recommendation to pause at D6.6 rather than expand snapshot surfaces now.
- D7.1 proved the contract for `turma.matriz_id == NULL` but did not introduce any new runtime surface.
- D7.2B1 created the read-only admin catalog, but the new screens are not linked from the menu/sidebar yet.
- D7.2B2 only delivered controlled creation of `atividade_base` and `norma_atividade`.
- D7.2B3-PATCH1 delivered controlled creation of `atividade_versao` in rascunho
  (commit `16b1480` / `ccf1a7e`).
- D7.2B3-PATCH2 delivered controlled editing of `atividade_versao` em rascunho
  (commit `c90ffe3`). Versões com `status != 'rascunho'` e versões com qualquer
  uso em matriz, requisição ou transição estão protegidas contra edição.
- The `Criar versão` button is now enabled in the detail of each `atividade_base`
  and points to the new draft creation form.
- All `atividade_versao` created by PATCH1/2 are inserted with `status = 'rascunho'`
  and are not yet usable by any matrix.
- The legacy mapping (`mapeamento-legado`) remains read-only.
- The matrix still does not choose `atividade_versao_id` through the UI.
- Versões que já estão em uso (matriz, requisição, transição) ficam imutáveis
  pela rota de edição — qualquer alteração futura exigiria nova versão.
- Ativação de versão (rascunho→ativa) foi implementada no PATCH3.
- Vínculo explícito matriz→versão foi implementado em D7.2B4-PATCH1.
- Inativação e descontinuação de versão foram implementadas em D7.2B5-PATCH1.
- Substituição explícita de versão foi implementada em D7.2B5-PATCH2:
  - exige `to_versao_id` explícito;
  - marca origem como `substituida`;
  - cria `atividade_transicao` com `tipo_transicao='mesmo_eixo'`;
  - bloqueia origem com vínculo em matriz;
  - bloqueia origem/destino com transição prévia como `from`.
- D7.2B6 adicionou histórico administrativo read-only no detalhe da atividade-base
  e foi publicada no commit `95cb897`.
- Catálogo pode ter múltiplas versões ativas; ambiguidade é controlada
  pelo vínculo explícito em `matriz_atividade_versao_item` (max 1 por matriz+base).
- Não há auditoria de quem ativou/inativou/descontinuou/substituiu versão.
- D7.3A realizou canonização documental dos regulamentos AAC/AEU (read-only, sem código).
- D7.3B-PLAN especificou o formato do fixture YAML (controlled vocabulary, mapping ao schema).
- D7.3C criou o fixture canônico: `normative_fixtures/d73c_normative_fixture.yaml`.
  - 32 atividades únicas, 61 versões totais, 3 normas.
  - 2 removidas (AAC-rev6), 3 nativas AEU, 1 transição explícita (AAC→AEU).
  - YAML validado, sem erros de estrutura ou valores inválidos.
- Importação de dados reais ainda não foi executada; fixture está pronto para D7.3D.
- D7.3D entregou o importador dry-run (tools/d73d_normative_importer_dryrun.py).
  A importação real para database.db ainda não foi executada.
- PATCH seguinte não deve começar sem escopo explícito e planejamento
  read-only separado.

## Permanent Working Directives

- ChatGPT acts as technical supervisor, auditor, and orchestrator.
- Codex or GitCP is the main executor for real code changes.
- MiniMax may be used for low-cost volume work, logs, tests, repetitive tasks, and simple low-risk patches.
- Kimi may be used for strong second opinions, architecture work, or difficult multi-file problems.
- GLM, Qwen, MiMo, and DeepSeek may be used selectively for safe tasks, preferably read-only, test-only, or review work.
- Sensitive data, real databases, production actions, security work, backfill or cutover, and critical decisions must not be delegated to a low-cost agent without final audit.
- Every phase must leave a report, evidence, tests or justification, risks, and a clear next step.
- `PROJECT_STATE.md` and `AGENT_HANDOFF.md` must be updated after an important phase closeout, agent or chat handoff, structural change, or relevant risk change.
