# Technical Panorama and File Map

Objective, verified summary for continuity: architecture, data model/constraints, UI patterns, flows, recent fixes, validation, and next steps—with exact file/selector pointers.

## Architecture / Stack
- Backend: Flask + SQLite + Jinja2
  - Entrypoint: `main.py` (runs `init_db()` then Flask dev server)
  - DB path: `database.db`
  - Uploads dir: `uploads/` (auto-created alongside `main.py`)
- Frontend: HTML + CSS + JS (vanilla)
  - Templates: `templates/`
  - Static assets: `static/` (notably `static/css/components/actions-float.css`, `static/css/components/list-cards.css`)

## Data Model (key tables/columns)
Defined and migrated in `main.py:init_db()`.

- `atividades`
  - Columns: `id`, `grupo` (string "N - descrição"), `nome` UNIQUE, `limite_horas` (legado),
    `tipo_atividade` CHECK ('Acadêmica Complementar'|'Extensão Universitária'),
    `tem_limitacao` (0/1), `tipo_limitacao` CHECK ('total'|'semestral'),
  `limite_horas_total`, `limite_horas_semestral`, `documentos_json` (TEXT JSON array)
- `grupos_def`
  - Created lazily in route `/admin/grupos/renomear` with PK `(tipo_atividade, numero)`; canonical map of number→description per tipo
- `requisicoes`
  - Columns include: `arquivo_comprovante` (legado)
  - Multi-attachments: `requisicao_arquivos` (created in `/aluno/nova_requisicao` POST)

Important rule: when no limitation, code coerces `tem_limitacao=0` and sets neutral `tipo_limitacao='total'` to satisfy CHECK (see POST in `/admin/adicionar_atividade` and `/admin/editar_atividade`).

## Routes and Pages (selected)
- Admin
  - List Atividades: `/admin/atividades` → `templates/admin_atividades.html`
  - Add Atividade: `/admin/adicionar_atividade` → `templates/admin_adicionar_atividade.html`
  - Edit Atividade: `/admin/editar_atividade/<id>` → `templates/admin_editar_atividade.html`
  - Grupos modal persist: POST `/admin/grupos/renomear` → updates `grupos_def` and labels in `atividades`
  - List Alunos: `/admin/alunos` → `templates/admin_alunos.html`
- Aluno
  - Nova Requisição: `/aluno/nova_requisicao` (multi-file upload; saves first file to legacy column and all in `requisicao_arquivos`)

Controller refs in `main.py` (quick grep anchors):
- `def admin_atividades()` renders list and computes `docs_por_atividade` from `documentos_json`.
- `def admin_adicionar_atividade()` and `def admin_editar_atividade()` map UI hidden fields to DB columns and coerce `tipo_limitacao` when no limitation.
- `@app.route('/admin/grupos/renomear', methods=['POST'])` persists `grupos_def` and updates labels in `atividades` by número.
- `def aluno_nova_requisicao()` builds `docs_por_atividade` and accepts múltiplos arquivos into `requisicao_arquivos`.

## UI Patterns and CSS Utilities
- Forms: `.form-cards-narrow`, `.form-row`, `.field-card`, `.field-chip`, `.control`, `.field-card.split-2`, `.compact-left`
- Document chips (required docs): `.svc-pair` container, `.svc-pills .btn.pill` chips, remove button `#chip-rem-documento`, add with `.svc-mini-btn`
  - Add: `templates/admin_adicionar_atividade.html` (JS builds chips and syncs hidden `documentos_json`)
  - Edit: `templates/admin_editar_atividade.html` (same UX, robust parsing)
- Lists (Impressões grid): `.impressoes-cards` with sticky header, `.cell` columns
  - Activities list: `templates/admin_atividades.html`
  - Alunos list: `templates/admin_alunos.html`
- Floating actions bar (view/edit/delete): CSS in `static/css/components/actions-float.css`; JS instantiation in each list template
- Grupos Modal: overlay `.modal-overlay`, card `.modal-card` → `templates/admin_atividades.html`

Where these classes live
- Core app styles: `static/css/modern-style.css` (global UI). Loaded via `base.html` and `base_aluno.html`.
- Print/list styles: `static/css/components/list-cards.css` (impresso card/grid). Loaded locally in templates that use impresso lists (admin/aluno list pages).
- Form atoms: `static/css/clientes-form-pack.css`, `static/css/modern-style-CS.css` define `.form-row`, `.field-card`, `.field-chip`, split variants.
- Floating actions bar: `static/css/components/actions-float.css` styles `#pedido-actions-float` and `.act-btn`.
- Modal and svc-classes: inline `<style>` blocks inside specific templates (`admin_atividades.html`, `admin_adicionar_atividade.html`, `admin_editar_atividade.html`).

CSS usage rules
- Keep `modern-style.css` as the only global include in base templates.
- Include `list-cards.css` only in pages rendering impresso lists (avoid global import).
- Avoid adding new global CSS files; prefer local `<style>` or per-page component CSS to minimize side effects.

## Behaviors and JS (where to find)
- Group split (number + description) with hidden `grupo`:
  - Add: `templates/admin_adicionar_atividade.html` (populate `#grupo_num` from `grupos_por_tipo`, readonly `#grupo_desc`, updates hidden `#grupo_hidden`)
  - Edit: `templates/admin_editar_atividade.html` (restores saved number; injects option if missing; tolerant to different hyphen chars)
- Documents required (chips):
  - Parsers handle JSON string, JSON-encoded string, Python-list-like string, and comma-separated legacy
  - Sync to hidden `#documentos_json` on submit with `syncHidden()`
- Limitation fields mapping to hidden inputs to satisfy DB CHECKs
- Modal Grupos: `admin_atividades.html` contains logic to list, edit description by number, and POST to `/admin/grupos/renomear`

Exact selectors/IDs used
- Grupo (Add/Edit): `#grupo_card`, `#grupo_num`, `#grupo_desc[readonly]`, hidden `#grupo_hidden`; tipo select `#tipo_atividade_sel`; JSON payload `#grupos-por-tipo-json`.
- Docs chips (Add/Edit): container `#documentos-chips`, hidden `<input id="documentos_json" name="documentos_json" data-initial-docs="…">`, add input `#novo-documento`, add button `#add-documento`, remove `#chip-rem-documento`.
- Admin list actions: `#pedido-actions-float` (toolbar), per-row `.impresso-card[role=listitem]` with `.cell` columns.
- Grupos modal: `#grupos-modal`, `#grupos-list`, `#grupo-desc-box`, `#grupos-save` (persists via fetch to `/admin/grupos/renomear`).
- Aluno Nova Requisição: tipo `#tipo_atividade_select`, grupo `#grupo_num`/`#grupo_desc` + hidden `#grupo_hidden`, atividade `#atividade_id_select`, docs JSON payload `#docs-por-atividade-json`, dynamic uploads container `#comprovantes_container` (inputs `name="comprovantes_files"` with paired `name="comprovantes_labels"`).

## Recent Changes and Fixes (implemented)
- Add/Edit Atividade: parity in layout and UX (narrow form; same order of fields)
- Group number restoration in Edit: robust extraction from hidden value; injects option if absent; fallback 1..50 list
- Description resolution tolerant to Unicode hyphens (`-, , , , ??`) and formats like "N-descrição" / "N - descrição"
- Documents chips: robust parsing from multiple formats; save on submit; list view renders based on `documentos_json`
- Floating actions bar for Activities and Alunos lists

Code refs:
- Add: `templates/admin_adicionar_atividade.html`
- Edit: `templates/admin_editar_atividade.html`
- List: `templates/admin_atividades.html`
- Actions bar CSS: `static/css/components/actions-float.css`
- Backend routes: `main.py` (search for `admin_atividades`, `admin_adicionar_atividade`, `admin_editar_atividade`, `admin_grupos_renomear`)

Aluno flow (uploads)
- Dynamic required files render in `templates/aluno_nova_requisicao.html` based on `docs_por_atividade`.
- Backend saves the first file into legacy `requisicoes.arquivo_comprovante` and all files into `requisicao_arquivos`.

## Current Status vs Remaining
- Add/Edit Atividade are in parity; group selection and `documentos_json` working end-to-end
- DB CHECK on `tipo_limitacao` handled via hidden mapping
- Remaining nice-to-have:
  - View-only mode via `?view=1` to disable inputs on Edit pages
  - Light tests for (no/semestral/total) limitations
  - Revisit `UNIQUE(atividades.nome)` if scoping by tipo/grupo becomes desired

Discrepancies / Issues spotted
- Atividade “Descrição” field in templates (`name="descricao"`) isn’t persisted: no `descricao` column in `atividades` and controllers don’t read it.
- Aluno “Nome do evento” (`name="nome_evento"`) isn’t persisted in `/aluno/nova_requisicao` POST; only `observacao` and files are stored.
- View-only (`?view=1`) hinted in toolbar redirect is not implemented: pages set `const is_view = false` and don’t disable inputs.
- Admin Alunos pendentes count join likely wrong: subquery groups by `r.aluno_id` but outer join uses `p.aluno_id = a.usuario_id` (should be `a.id`).
- Uploads accept any file type; consider validating extensions/MIME to reduce risk.

## Quick Validation
- Add Activity: select Tipo; choose Grupo number and confirm description; add 2–3 docs; Save; list shows group number and docs like "doc1, doc2, +1"
- Edit Activity: number restored; chips load; add/remove and Save; list reflects changes; toggle Tipo repopulates numbers and updates hidden `grupo`
- Grupos modal: edit description and Save; list labels update; persistence via `/admin/grupos/renomear`
- Aluno Nova Requisição: select activity; expected number of file inputs appears per `documentos_json`; submit saves files to `uploads/` and links in `requisicao_arquivos`

## Notes
- If legacy `grupo` strings don’t start with a number, parsers ignore number; manual correction may be needed for extreme cases
- `documentos_json` should be a JSON list, but parsers already cover common legacy formats

Next steps (suggested)
- Implement view-only mode on Edit pages when `?view=1`: set `is_view=true`, disable inputs, hide destructive actions.
- Either remove the non-persisted “Descrição” and “Nome do evento” fields or wire them to DB columns (add columns + controllers).
- Fix Admin Alunos pendentes join (`p.aluno_id = a.id`). Add a tiny test/visual indicator.
- Optional: scope `UNIQUE` for `atividades.nome` by `(tipo_atividade, grupo, nome)` if needed.

CSS next steps (suggested)
- If area-specific overrides grow, add thin `static/css/admin.css` and `static/css/aluno.css` that import `modern-style.css` and hold minimal overrides.
- Consider a partial `components/impresso_card.html` to unify header+row markup of card lists without changing visuals.
