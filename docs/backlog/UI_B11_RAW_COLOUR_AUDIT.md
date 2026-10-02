# UI-B11 — Raw-colour / tokenization audit

**Status:** TECHNICALLY COMPLETE — CLOSED FOR THE AUTHORIZED NO-VISUAL-CHANGE TOKENIZATION SCOPE (2026-10-02).
The third cohort created the missing semantic token families at their exact rendered values and converted every
unambiguous C1 / safe-C4 occurrence (430 → **291**). No safe no-visual-change replacement remains: what is left is
component-local (B), content/chart (D), legitimate local semantics (C3), or a visual-convergence decision (C2). Every
group is listed below, with the third-cohort record first. **This is not unfinished technical cleanup:** the remainder
is intentional, non-blocking, and must not be pursued without a future explicit visual-design decision.
History: the 2026-09-28 audit changed no colour. The first category-A pass converted 39 sites (498 → 459). The
2026-09-29 cohort converted 28 more (458 → **430**) with no visual change. The 2026-10-02 cohort converted 139 more
with no visual change and split the former category C into C1/C2/C3/C4.

## Re-audit and second category-A cohort (2026-09-29)

**Scope** is the same as the guard `tests/test_b11_category_a_tokenization.py`: `static/css/**` minus `tokens.css`
(comments stripped), `static/js/**`, template `<style>` blocks and `style=""`. The 2026-09-28 pass left 459. HEAD
`009a79a` measured 458, because one literal left with intervening work. Scanner and classifier:
`SGAA_backups/ui_b11_tokenization_20260929/tools/{scan,classify}.py`. The per-occurrence inventories
(`inventory_{before,after}.json`) record owner, line, selector, property and declaration.

**Scheme (2026-09-29 brief).** It differs from the 2026-09-28 letters:
- **A** SAFE_TOKEN_REPLACEMENT: an existing token is the exact intended equivalent, by value *and* role.
- **B** COMPONENT_LOCAL_BUT_VALID.
- **C** NEEDS_SEMANTIC_TOKEN_DECISION: no existing token expresses the role, or converging would change the colour.
  This merges the old C and old E.
- **D** EXTERNAL/CONTENT colour.
- **E** DEAD/UNUSED, proven only.

| | A | B | C | D | E | total |
|---|---|---|---|---|---|---|
| before (HEAD `009a79a`) | 28 | 30 | 389 | 7 | 4 | 458 |
| after | **0** | 30 | 389 | 7 | 4 | **430** |

### Cohort A: what changed (28 occurrences, 6 files)

| Group | Token / owner | Sites | Why it is an exact equivalent |
|---|---|---|---|
| surface-layer white fills (11) | `--surface` | `modern-style.css`: `.sr-only-focusable:focus`, `.sidebar-link:hover`, `.sidebar-link.active…`, `.sidebar-link.active:hover`, `#avatar-box`, `.icon-btn.danger`. `admin_banco_dados.html`: `.db-folder-btn-close`. `admin_atividades.html`: `#grp-add`, `#grp-del:hover`. `admin_requisicoes.html`: `#preset-add`, `#preset-del:hover` | Each element is drawn as a button/card surface: white plus `--border-strong`, often `--shadow-sm`. `.btn`, `.icon-btn` and `.btn.danger` already own that fill as `var(--surface)`, and `.icon-btn.danger` only restated its base |
| computed field card (1) | `--field-readonly-bg` | `modern-style.css` `.field-card.is-off` (Turma "Fim (calculado)") | The card is shown but not editable, which is the read-only role. The value is identical (`#f1f5f9`) |
| Cursos status pills (6) | the shared status-pill properties `--status-pill-text/-bg/-border` | `list-cards.css` `.imp-cursos .badge.status-pill.status-{positive,negative}` | The rules restated the shared palette byte-for-byte on the element that defines those properties. `!important` is kept |
| inert fallbacks (10) | the token already named | `list-cards.css` `var(--field-chip-hover-bg/-focus-bg, #f1f5f9)` ×4, `var(--field-focus-border, #0369a1)`, `var(--field-focus-ring, rgba(…,.2))`, `var(--field-focus-ring, rgba(…,.22))`, `var(--accent-blue, #0369a1)`, `var(--surface, #fff)`. `aluno_requisicao_detalhe.html` `var(--btn-primary, #0369a1)` | Every consumer extends `base.html`/`base_aluno.html`, whose `design_system_css()` loads `tokens.css` first, so these fallbacks never render. Two had already drifted: `.2` against the token's `.22`, and `#0369a1` against `--btn-primary` `#003366` |

**Visual check** (disposable runtime: fresh seeded temp DB, test client served to headless Chromium, no port, canonical
untouched). Eight pages were probed before and after: Dashboard (sidebar, skip link), Nova Turma (`is-off`), Adicionar
Aluno (avatar, `.icon-btn.danger`), Cursos (real pills), Alunos (chips, filter inputs, selected card), Atividades and
Requisições (mini-toolbars), and Banco de dados (folder close button). The probe compared **45 element states**
(default plus forced `:hover` / `:focus` / `:focus-within` / `:focus-visible`) and found **0 differences** in computed
colours, borders, shadows, outlines or opacity. 7 of 8 full-page screenshots are pixel-identical. The Banco de dados
difference is only the disposable runtime's temp path (`pytest-3408` vs `pytest-3409`). **No intended or perceptible
visual change.**

**Guard.** `tests/test_b11_category_a_tokenization.py`:
- The ratchet ceiling moves 459 → **430**.
- The new sites are pinned.
- One DS invariant is added: *no colour fallback on a token that `tokens.css` always defines*. Such a fallback never
  renders and drifts silently, as two already had.
- Fallbacks on tokens that `tokens.css` does *not* define are what actually render, so they stay allowed.

### What remains, and why (430)

| Cat. | Group | Count | Values (top) | Owners (top) | Why no safe replacement / next step |
|---|---|---|---|---|---|
| B | status-pill shared owner palette | 24 | `#d9dde2`, `#f4f5f6`, `#48505a`, `#7b8794` … | modern-style.css 24 | The authoritative owner of the status palette: component properties plus the default. Promoting it to `tokens.css` is optional |
| B | `@media print` table palette | 4 | `#ccc`, `#f5f5f5`, `#333`, `#ddd` | list-cards.css | Paper output only |
| B | toggle-switch component token | 1 | `#0f5b99` | form.css | Component-local token definition |
| B | Alertas colour-dot hairline | 1 | `rgba(0,0,0,.12)` | admin_alertas.html | Must stay visible over any user-chosen colour |
| D | aluno dashboard `.days-bar` ramp | 6 | `#2ecc71`, `#27ae60`, `#f1c40f` … | aluno_dashboard.html | Data-visualisation threshold ramp |
| D | Alertas "border-only" swatch | 1 | `#fff` | admin_alertas.html | The user's alert colour "white", not UI `--surface` |
| E | Banco de dados provider `.db-badge` fallbacks | 4 | `#d9dde2`, `#f4f5f6`, `#48505a`, `#7b8794` | admin_banco_dados.html | Proven dead: `.local`, `.warning` and `:not(.local):not(.warning)` always define `--status-pill-*`. They are parked with the status-palette decision below, which rewrites this block anyway |
| C | info / identifier / selected-row family | 54 | `#eff6ff`, `#1d4ed8`, `#bfdbfe`, `#1e3a8a` … | modern-style 10, admin_atividades 10, diagnóstico 8 … | No `--info-*` family. The status-pill *info* palette has different values |
| C | danger family | 43 | `#b91c1c`, `#dc2626`, `#fef2f2`, `#ef4444` … | modern-style 14, admin_requisicoes 9, admin_banco_dados 4 … | `--field-invalid-*` has the same values but is field-scoped. A `--danger-text/-bg/-border` family is needed |
| C | shadows / overlays / tinted states | 42 | `rgba(15,23,42,.04/.06)`, `rgba(0,0,0,.25)`, `rgba(2,6,23,.45)` … | admin_acesso 9, modern-style 7, admin_dashboard 5 … | `--shadow-sm/-md` differ. `--shadow-card`, `--backdrop` and tint tokens are needed |
| C | zinc neutral scale | 42 | `#71717a`, `#e4e4e7`, `#f4f4f5`, `#a1a1aa` … | admin_requisicoes 26, admin_atividades 14 … | A parallel neutral scale (the presets / grupos modals and mini-toolbars). Converging onto the slate/gray tokens is a visual change and needs the user's decision |
| C | subtle surfaces / hover fills | 39 | `#f8fafc`, `#f1f5f9`, `#fbfdff`, `#f3f4f6` … | modern-style 8, list-cards 5, admin_atividades 3 … | `--field-hover-bg`, `--bg` and `--field-readonly-bg` have the same values but other roles. A `--surface-subtle` / `--hover-bg` token is needed (`.btn:hover`, menu/filter hovers, table headers) |
| C | warning family | 30 | `#92400e`, `#b45309`, `#f59e0b`, `#fef3c7` … | modern-style 6, admin_dashboard 6, aluno_dashboard 6 … | No `--warning-*` family |
| C | strong ink / dark fills | 30 | `#0f172a`, `#1e293b`, `#111827` | admin_banco_dados 12, admin_acesso 7 … | `--text-primary` is `#1f2937`, so converging changes the colour (user decision) |
| C | slate muted text | 28 | `#475569`, `#64748b`, `#94a3b8`, `#334155` | admin_banco_dados 11, admin_acesso 7, diagnóstico 6 … | `--text-secondary` is `#6b7280`, so converging changes the colour (user decision) |
| C | dividers / hairlines | 16 | `#e2e8f0`, `rgba(15,23,42,.08)` … | admin_banco_dados 6 … | `--field-disabled-border` has the same value but is field-scoped. A `--divider` token is needed |
| C | success family | 15 | `#047857`, `#27500a`, `#eaf3de`, `#ecfdf3` … | modern-style 6, admin_banco_dados 4 … | No `--success-*` family |
| C | Banco de dados status palette re-declared | 12 | `#e9f5e7`, `#b9d7b5`, `#1f5a3c` … | admin_banco_dados.html | It restates the shared status-pill palette, but that palette is class-scoped and the badge geometry differs (24px / 12.5px / 6px dot vs 18px / 11px / 5px). Either promote global `--status-*` tokens, now shared by three owners (status-pill, `.db-badge`, formerly `.imp-cursos`), or adopt the shared classes, which is a visual change |
| C | aluno_dashboard legacy inline styles | 12 | `#666`, `#222`, `#111`, `#eee` | aluno_dashboard.html | Restyling them with DS classes is a visual change |
| C | text on brand/dark fills | 10 | `#fff` | modern-style 6 … | No `--text-on-brand` token |
| C | phantom tokens | 6 | `#f2f2f2`, `#b91c1c`, `#f8fafc` | turma-alunos 2, actions-float 1, form 1 … | `var(--danger, …)`, `var(--surface-alt, …)` and `var(--surface-2, …)` name tokens that were never defined, so the literal is what renders. They resolve when the danger / subtle-surface tokens exist |
| C | file-card chip ink | 6 | `#000` | form.css 2, modern-style 2, aluno_nova_requisicao 2 | Deliberately pure black ("manter cor preta"). `--text-primary` differs |
| C | white in a gradient ramp / selected-row badge | 3 | `#fff` | modern-style, admin_mensagens, admin_atividades | Tokenizing one stop splits the ramp from its `#f8fafc` end (subtle-surface). The selected-row badge belongs to the info family |
| C | Alertas selected-swatch outline | 1 | `#0f5b99` | admin_alertas.html | Same value as form.css-local `--toggle-switch-active`. It needs one shared `--control-selected` token |

**Outside the ratchet scope (12, not counted above).** Template `<script>` blocks:
- `admin_requisicoes.html`'s JS-injected stylesheet (10) → C. It holds the Deferir / Parcial / Indeferir decision-button
  palette `#5C9A7F` / `#9C7132` / `#B8534C` with their 5 % tints, plus the `--surface-2` phantom fallback and chip ink.
  The block itself has no owner yet.
- The Alertas default user colour `#e3eefd` ×2 → D (content default).

**Observation, not colour (not touched).** `.field-card.is-off` still carries `opacity:.55`. That conflicts with the
accepted "no opacity hacks / shared read-only treatment" contract. Converging it onto the shared read-only treatment is
a visual change and a separate decision.

**Suggested order for the remainder.** *Item 1 was executed by the third cohort below; only item 2 is still open.*
1. ~~Value-preserving new semantic tokens: `--danger-*`, `--warning-*`, `--success-*`, `--info-*`,
   `--surface-subtle`/`--hover-bg`, `--divider`, `--shadow-card`/`--backdrop`, `--text-on-brand`, `--control-selected`,
   and the global `--status-*` palette.~~ Implemented 2026-10-02 exactly as listed, at current values. `--warning-*` and
   `--success-*` were **not** created: their occurrences use competing values for the same role, so they are C2.
2. User visual decisions remain: the zinc scale, strong ink vs `--text-primary`, slate text vs `--text-secondary`,
   the warning/success/danger/info variants, and the aluno_dashboard inline styles.

## Third cohort — missing semantic tokens (2026-10-02)

**Scope** is unchanged (`tests/test_b11_category_a_tokenization.py`). HEAD `77618c0` measured **430**. The 389 former
C occurrences were re-split into **C1** token-missing visual-exact · **C2** visual decision required · **C3** local
semantic value · **C4** undefined token reference. Only C1 and the safe C4 references were implemented. Every token
carries the literal that already rendered, so no computed colour changes.

| | C1 | C2 | C3 | C4 | total C |
|---|---|---|---|---|---|
| before | 108 | 243 | 32 | 6 | 389 |
| after | **0** | 243 | 32 | **0** | 275 |

Cohort result: **430 → 291** raw occurrences (139 converted or removed: C1 108, safe C4 6, B status/toggle 21, E 4).

### Tokens created (`foundation/tokens.css`, exact values)

| Token | Value | Ownership / role |
|---|---|---|
| `--surface-subtle` | `#f8fafc` | subtle fills (table headers, chips, panels) |
| `--hover-bg` | `#f8fafc` | hover fills (menu/filter/row/chip hovers) |
| `--field-chip-bg` | `#f2f2f2` | resting file-card trailing chip; also resolves `var(--surface-2, …)` |
| `--divider` | `#e2e8f0` | solid hairline dividers |
| `--divider-soft` | `rgba(15,23,42,.08)` | soft divider (import-help borders) |
| `--text-on-brand` | `#ffffff` | white ink on brand/dark fills |
| `--control-selected` | `#0f5b99` | selected swatch outline + toggle switch (form.css's component token now aliases it) |
| `--info-bg` / `--info-text` / `--info-border` | `#eff6ff` / `#1d4ed8` / `#bfdbfe` | informational surface / text / border |
| `--danger-text` / `--danger-bg` / `--danger-border` | `#b91c1c` / `#fef2f2` / `#fecaca` | generic destructive/error; field validation keeps its own `--field-invalid-*` |
| `--shadow-card` | `0 1px 2px rgba(15,23,42,.04), 0 1px 3px rgba(15,23,42,.06)` | repeated card elevation (4 consumers) |
| `--shadow-modal` | `0 10px 30px rgba(2,6,23,.25)` | modal card elevation (2 consumers) |
| `--backdrop` | `rgba(2,6,23,.45)` | modal scrim (2 consumers) |
| `--status-{positive,neutral,caution,negative,info}-{bg,border,text,dot}` | 20 values | shared status palette, promoted from the byte-identical `.badge.status-pill` and `.db-badge` copies |

Safe C4 resolutions: `var(--danger, #b91c1c)` ×2 → `var(--danger-text)`;
`var(--surface-alt, #f8fafc)` ×1 → `var(--hover-bg)`; `var(--surface-2, #f2f2f2)` ×4 → `var(--field-chip-bg)`.

### Replacements

All of `#b91c1c` (20), `#eff6ff` (12), `#fef2f2` (4), `#1d4ed8` (4), `#bfdbfe` (4), `#fecaca` (2),
`#f2f2f2` (3 in scope + 1 in the Requisições script), `rgba(15,23,42,.08)` (4), `#0f5b99` (2) and the 20 status-palette
values are now token-only; 26 files changed. `modern-style.css` 90 → 53, `admin_banco_dados.html` 69 → 42,
`admin_requisicoes.html` 51 → 36, `admin_acesso.html` 34 → 24, `admin_atividades.html` 34 → 26.

**Dead E removed (4).** The `.db-provider-head .db-badge` fallbacks `#d9dde2`, `#f4f5f6`, `#48505a`, `#7b8794`
never render: every provider badge carries `.local`, `.warning`, or matches `:not(.local):not(.warning)`. The
declarations stay; only the dead fallbacks go. The `.badge.status-pill` base fallbacks stay — they are live for
`status-pill status-warning` and promoting the default is a separate semantic decision.

**Template-script colours (12).** The JS-injected `.chip-right` background now consumes `--field-chip-bg`. The
Deferir/Parcial/Indeferir decision palette (`#5C9A7F` / `#9C7132` / `#B8534C` with their 5 % tints) and the `#000`
chip ink stay literal: single-consumer component palette, and tokenizing them would be a JS styling decision. The
Alertas default user colour `#e3eefd` ×2 stays content.

### Visual proof

Disposable runtime (fresh seeded temp DB, test client, no port, canonical untouched). A baseline worktree at
`77618c0` and the working tree were probed with the same script: 78 page/state fingerprints (26 pages × default /
forced `:hover` / forced `:focus`), each recording computed colour, borders, outline, shadow, background-image and
opacity for every element, plus 26 full screenshots, with transitions and animations disabled. **BEFORE vs AFTER:
0 differences across all 78 fingerprints and 0 differing pixels in all 26 screenshots (channel tolerance 1).**
No intended or perceptible visual change.

### What remains (291)

| Cat. | Group | Count | Why it is not a safe C1 |
|---|---|---|---|
| B | `@media print` palette | 4 | paper output only |
| B | status-pill default fallback | 4 | live for `status-pill status-warning`; promoting the default is a semantic decision |
| B | Alertas colour-dot hairline | 1 | must stay visible over any user colour |
| D | aluno_dashboard `.days-bar` ramp | 6 | data-visualisation threshold ramp |
| D | Alertas border-only swatch | 1 | user colour "white", not UI `--surface` |
| C2 | zinc neutral scale | 39 | choose between the parallel zinc values and the slate/gray tokens |
| C2 | warning family | 30 | competing values (`#92400e` vs `#b45309`, three bg/border pairs) |
| C2 | strong ink / dark fills | 28 | `#0f172a` vs `--text-primary` `#1f2937` would change colour |
| C2 | slate muted text | 28 | `#475569` etc. vs `--text-secondary` `#6b7280` would change colour |
| C2 | one-off chrome rgba | 27 | unique shadow/overlay/tint values; one token per site is not shared ownership |
| C2 | danger competing variants | 19 | `#dc2626`, `#ef4444`, `#fee2e2`, `#991b1b` … — pick one destructive scale |
| C2 | subtle-surface competing variants | 18 | `#f1f5f9`, `#fbfdff`, `#fafafa`, `#f3f4f6`, `#eef4f8` |
| C2 | info competing variants | 17 | `#2563eb`, `#1e3a8a`, `#0c447c`, `#155e75` … |
| C2 | success family | 13 | competing values |
| C2 | aluno_dashboard legacy inline styles | 12 | restyling is a visual change |
| C2 | gradient ramp stops / selected-row badge | 8 | tokenizing one stop splits the ramp from its owner |
| C3 | file-card chip ink | 6 | deliberate pure black ("manter cor preta") |
| C3 | identifier chip palette | 6 | `.badge-grupo` / `.version-identifier` component values |
| C3 | tooltip chrome | 4 | `.ui-tooltip` component values |
| C3 | Atividades filter active state | 4 | `#filter-btn.is-active` component state |
| C3 | db-origin-pill palette | 4 | component data palette |
| C3 | access custom-scope teal | 3 | component state accent |
| C3 | db-badge neutral base | 2 | component base fill |
| C3 | access student panel tint | 2 | component local tint |
| C3 | Requisições outline-primary hover | 1 | component-local |
| C2 | folder chrome one-offs | 4 | `#d9e2ee`, `#bdd4ee`, `#f8fbff`, `#d6dce6` |
| **total** | | **291** | |

No C1 and no safe C4 occurrence remains. What is left is B component-local, D content/chart, C3 legitimate
component-local semantics, and C2 visual-convergence decisions. **UI-B11 is technically complete for
NO-VISUAL-CHANGE consolidation**; the remaining C2 is a design decision, not tokenization debt.

**Guard.** `tests/test_b11_category_a_tokenization.py`:
- ratchet 430 → **291**;
- every fully tokenized value is pinned to its owner and forbidden elsewhere;
- the status palette's single owner, the info/danger/subtle/divider/hover/on-brand/control consumers, the
  whole-value elevation tokens and the removed dead fallbacks are pinned;
- phantom `var(--danger,`, `var(--surface-alt,`, `var(--surface-2,` are forbidden.

## Scope and method

Read-only scan of product UI code: every `static/css/**/*.css` (except the token owner `static/css/foundation/tokens.css`),
every template `<style>` block and inline `style="…"`, and `static/js/**/*.js`. Hex, `rgb()/rgba()` and `hsl()/hsla()`
literals were normalised (`#fff` → `#ffffff`, spaces removed) and compared with the colour values defined in `tokens.css`.
Vendor code, images, tests and docs are excluded. Each finding was assigned to exactly one owner/role group below.

**Totals (audit baseline):** 498 raw-colour occurrences, 156 distinct values, 35 owners.
**By category (audit baseline):** A 63 · B 29 · C 237 · D 0 · E 169.

**Totals after the category-A pass:** **459** occurrences, 153 distinct values, 29 owners.
**By category after the pass:** **A 13 · B 37 · C 238 · D 0 · E 171** (39 A resolved; 11 A reclassified, see below).

Categories: **A** should use an existing token (exact semantic duplicate) · **B** component-internal, legitimate ·
**C** missing semantic token (repeated role, no DS token) · **D** dead/unused CSS · **E** unknown / needs a visual decision.

## Category-A pass (2026-09-28, second extended batch)

Every A finding was re-located in the current working tree (the audit kept no per-line list, so the group was rebuilt
from the owner/role rows; the rebuilt set matches the documented per-row and per-owner counts) and re-checked: the raw value
must equal the token's literal after normalisation, the role must be the token's documented role, and the token must be
loaded where the declaration lives (every A site extends `base.html`/`base_aluno.html`, which load `tokens.css` first).
Only ownership changed — every replaced value resolves to the identical colour. Counts were re-measured with the same
scanner scope (CSS minus `tokens.css`, JS, template `<style>` and `style=""`), which reproduces the 498 baseline exactly.

**Resolved — 39 occurrences, 19 owners (zero visual change):**

| Group | Token | Sites |
|---|---|---|
| card/panel surfaces (13 of 15) | `--surface` | `admin_banco_dados.html` `.db-card`, `.db-provider-card`, `.db-folder-modal-panel`, `.db-folder-item`; `admin_acesso.html` `.access-default-card` (default-password profile cards), `.access-policy-summary`, `.access-scope-card`; `admin_turmas.html` `.import-help-code`, `.import-help-note`; `admin_atividades.html` / `admin_importar_atividades.html` `.import-help-code`; `admin_dashboard.html` `.dashboard-empty-state`; `admin_diagnostico_atividades_versionadas_view.html` `.diag-card` |
| empty-state / muted text (14 of 14) | `--text-secondary` | inline empty states in `admin_alertas`, `admin_alunos`, `admin_arquivos`, `admin_atividades` (×2, one in JS), `admin_cursos`, `admin_matrizes`, `admin_requisicoes` (×2, one in JS), `admin_turmas`, `aluno_arquivos`, `aluno_minhas_requisicoes`; `list-cards.css` `.cell .muted`; `toolbar-filters.js` empty state. Colour only — the inline padding stays (`.table-empty` pads differently, so adopting it would be a visual change) |
| field fills (5 of 7) | `--field-bg` | `modern-style.css` `.progresso-type-select`, `.field input,.field select,.field textarea` (overridden later by the unified field states — no effect either way); `admin_atividades.html` presets input; `admin_acesso.html` `.access-scope-card select`; `admin_requisicoes.html` presets textarea |
| selection / hover accent (3 of 6) | `--accent-blue` | `list-cards.css` `#filter-menu/#sort-menu .menu-item.selected`, `.impresso-card:hover:not(.selected)`; `aluno_minhas_requisicoes.html` `.input-chip.active` text |
| `.btn.primary:hover` (2 of 2) | `--btn-primary-strong` | `modern-style.css` background + border |
| focus outlines (2 of 2) | `--focus-ring-color` | `admin_dashboard.html`, `aluno_dashboard.html` alert-card `:focus-visible` |

**Remaining A — 13 (not zero-risk, left for a later decision):** *Superseded 2026-09-29.* The `.db-badge` palette
is now C (status-palette decision) plus 4 proven-dead fallbacks (E). The unpinned `modern-style.css` surface was
resolved per site: the skip link and `#avatar-box` became `--surface`, and the gradient stop stays C. See the re-audit above.
- Banco de Dados `.db-badge` status palette (12): the values equal the shared `.status-pill` palette, but those are
  class-scoped custom properties, not global tokens, and the badge geometry differs (24px / 12.5px / 6px dot vs 18px / 11px / 5px).
  Adopting the shared classes is a markup and visual change.
- `modern-style.css` surface (1): the audit counted one surface `#ffffff` there but did not record which; three value-exact
  candidates exist (`.sr-only-focusable:focus`, `#avatar-box`, the `.progresso-summary-card` gradient stop). Not guessed.

**Reclassified on re-validation — 11:**
- → **B** (8): the raw value is only a `var(--token, #…)` fallback of an already-tokenized declaration — `list-cards.css`
  `.impresso-card.selected` (`var(--surface, #fff)`), `.filter-text-input:focus` (`var(--field-focus-border, #0369a1)`),
  `.impresso-card.selected` border (`var(--accent-blue, #0369a1)`), the four `.input-group … .input-chip` hover/focus fills
  (`var(--field-chip-*-bg, #f1f5f9)`), and `aluno_requisicao_detalhe.html` card border (`var(--btn-primary, #0369a1)` — the
  rendered colour is `--btn-primary` `#003366`; swapping in `--accent-blue` would have *changed* it).
- → **C** (1): `list-cards.css` `.input-chip` resting fill `#f1f5f9` — the chip tokens are hover/focus roles; there is no
  resting-chip token.
- → **E** (2): `admin_mensagens.html` `.messages-stat` gradient first stop (tokenizing one stop splits the ramp's
  ownership; the `#f8fafc` end stop is C); `admin_atividades.html` `#grupos-modal .menu-item.is-selected .badge` white
  (a badge fill on a selected row — not a field, so `--field-bg` is the wrong role).

**Untouched by design:** every B, C and E finding, including the Alertas residuals (swatch outline `#0f5b99` → C, colour-dot
hairline → B, border-only white swatch → B). Guard: `tests/test_b11_category_a_tokenization.py` (ceiling 459, the converted
sites, and the Alertas literals).

## Owner / role table (audit baseline, 498)

| Owner / component | Raw values (top) | Semantic role | Count | Cat. | Existing token | Recommended action | Where (top owners) |
|---|---|---|---|---|---|---|---|
| card/panel surfaces | `#ffffff` | surface | 15 | A | --surface | var(--surface) | admin_banco_dados.html 4, admin_acesso.html 3, admin_turmas.html 2 … |
| empty-state / muted text | `#6b7280` | muted text | 14 | A | --text-secondary | use .table-empty / var(--text-secondary) | admin_atividades.html 2, admin_requisicoes.html 2, list-cards.css 1 … |
| Banco de Dados .db-badge | `#e9f5e7`, `#b9d7b5`, `#1f5a3c`, `#3e835a` … | status palette re-declared | 12 | A | .badge.status-pill.status-positive/caution/neutral (same values) | adopt shared pill classes (markup change -> not zero-risk) | admin_banco_dados.html 12 |
| field backgrounds | `#ffffff` | field fill | 7 | A | --field-bg | var(--field-bg) | modern-style.css 2, admin_atividades.html 2, list-cards.css 1 … |
| selection / accent borders | `#0369a1` | accent | 6 | A | --accent-blue | var(--accent-blue) | list-cards.css 4, aluno_minhas_requisicoes.html 1, aluno_requisicao_detalhe.html 1 |
| list-cards input chip | `#f1f5f9` | chip bg | 5 | A | --field-chip-hover-bg/--field-chip-focus-bg | use chip tokens | list-cards.css 5 |
| btn.primary hover | `#002244` | primary strong | 2 | A | --btn-primary-strong | var(--btn-primary-strong) | modern-style.css 2 |
| focus outlines | `rgba(37,99,235,.35)` | focus ring | 2 | A | --focus-ring-color | var(--focus-ring-color) | admin_dashboard.html 1, aluno_dashboard.html 1 |
| badge.status-pill (shared owner) | `#e9f5e7`, `#b9d7b5`, `#1f5a3c`, `#3e835a` … | status palette definitions | 20 | B | defined here | authoritative owner; optionally promote to tokens.css later | modern-style.css 20 |
| aluno_dashboard progress ramp | `#2ecc71`, `#27ae60`, `#f1c40f`, `#e67e22` … | data-viz threshold ramp | 6 | B | - | keep (chart semantics) | aluno_dashboard.html 6 |
| component-local token | `#0f5b99` | .toggle-switch | 1 | B | - | keep | form.css 1 |
| Alertas palette | `#ffffff` | 'border-only' swatch = user colour white | 1 | B | (--surface is a UI role, not this data colour) | keep literal | admin_alertas.html 1 |
| Alertas palette | `rgba(0,0,0,.12)` | colour-dot hairline on arbitrary user colour | 1 | B | - | keep literal (must stay visible on any user colour) | admin_alertas.html 1 |
| info / identifier family | `#eff6ff`, `#1d4ed8`, `#bfdbfe`, `#1e3a8a` … | info + identifier chips | 45 | C | (status-pill info palette differs) | add --info-* | admin_atividades.html 10, modern-style.css 8, admin_requisicoes.html 8 … |
| shadows / overlays | `rgba(15,23,42,.04)`, `rgba(15,23,42,.06)`, `rgba(0,0,0,.25)`, `rgba(2,6,23,.45)` … | elevation + backdrop | 44 | C | (--shadow-sm/--shadow-md differ) | add --shadow-card / --backdrop | modern-style.css 9, admin_acesso.html 9, admin_dashboard.html 5 … |
| danger / error family | `#b91c1c`, `#dc2626`, `#fef2f2`, `#ef4444` … | destructive + error text/bg/border | 43 | C | (--field-invalid-* same value, field-scoped) | add --danger-text/-bg/-border | modern-style.css 13, admin_requisicoes.html 9, admin_banco_dados.html 4 … |
| subtle surfaces / hover fills | `#f8fafc`, `#fbfdff`, `#f3f4f6` | surface-subtle + hover | 34 | C | (--field-hover-bg / --bg same value, other roles) | add --surface-subtle / --hover-bg | modern-style.css 6, list-cards.css 4, admin_atividades.html 3 … |
| warning family | `#92400e`, `#b45309`, `#f59e0b`, `#fef3c7` … | warning text/bg/border | 30 | C | - | add --warning-* | modern-style.css 6, admin_dashboard.html 6, aluno_dashboard.html 6 … |
| dividers / hairlines | `#e2e8f0`, `rgba(15,23,42,.08)`, `#d9dde2`, `rgba(148,163,184,.45)` … | divider | 15 | C | (--field-disabled-border same value) | add --divider | admin_banco_dados.html 7, admin_turmas.html 2, list-cards.css 1 … |
| success family | `#047857`, `#27500a`, `#eaf3de`, `#ecfdf3` … | success text/bg/border | 15 | C | - | add --success-* | modern-style.css 6, admin_banco_dados.html 4, admin_importar_atividades.html 2 … |
| text on brand/dark fills | `#ffffff` | on-brand text | 10 | C | - | add --text-on-brand | modern-style.css 6, admin_atividades.html 1, admin_requisicoes.html 1 … |
| Alertas palette | `#0f5b99` | selected-swatch outline | 1 | C | (form.css local --toggle-switch-active = same value) | promote one shared --control-selected token; then use it here + toggle | admin_alertas.html 1 |
| zinc neutral scale (Requisições/Atividades modals, list-cards) | `#71717a`, `#e4e4e7`, `#f4f4f5`, `#a1a1aa` … | parallel neutral scale | 46 | E | - | visual decision: converge on slate/gray tokens | admin_requisicoes.html 26, admin_atividades.html 14, list-cards.css 4 … |
| misc one-offs | `#000000`, `#f1f5f9`, `#f2f2f2`, `#fcebeb` … | various | 40 | E | - | per-site decision | modern-style.css 12, list-cards.css 7, admin_diagnostico_atividades_versionadas_view.html 5 … |
| slate muted text | `#475569`, `#64748b`, `#94a3b8`, `#334155` … | secondary text variants | 31 | E | (--text-secondary is #6b7280) | visual decision: converge on --text-secondary? | admin_banco_dados.html 12, admin_acesso.html 8, admin_diagnostico_atividades_versionadas_view.html 6 … |
| strong ink | `#0f172a`, `#111827` | heading/strong text | 29 | E | (--text-primary is #1f2937) | visual decision: converge on --text-primary? | admin_banco_dados.html 12, admin_acesso.html 7, admin_dashboard.html 3 … |
| aluno_dashboard inline styles | `#666666`, `#222222`, `#111111`, `#eeeeee` | legacy inline text/bg | 12 | E | - | visual decision: restyle with DS classes | aluno_dashboard.html 12 |
| white fills (hover/active/buttons) | `#ffffff` | misc white fill | 11 | E | --surface? | per-site decision | modern-style.css 6, admin_atividades.html 2, admin_requisicoes.html 2 … |

## Notes

- **Value match ≠ role match.** 140 occurrences equal some token's value, but only the 63 in category A share its *role*. For example, `#b91c1c` is the value of
  `--field-invalid-text` but is used as the generic destructive/danger colour at 20 sites (buttons, menus, KPIs). That makes it category C
  (a `--danger-*` family is missing), not A. `#f8fafc` (`--field-hover-bg`), `#e2e8f0` (`--field-disabled-border`) and
  `#f3f4f6` (`--bg`) are treated the same way.
- **D = 0.** The six colour rules whose selectors appear unused are all live through dynamic class composition:
  `flash flash-{{ category }}` (`components/flash_messages.html`), `login-feedback-{{ … }}` (`login.html`), and the Lucide
  `data-lucide="trash-2|x-circle|minus"` icons (the classes are added at runtime). `.badge.success/.danger` is still emitted by
  `admin_detalhes_curso.html` next to `status-pill` classes. Its colours are overridden there, which makes it a later cleanup candidate but not dead.
- **Known residuals (§9.4), classified rather than assumed:**
  - Alertas `.palette-swatch.is-selected{outline:3px solid #0f5b99}` → **C**. The same value is `form.css`'s component-local
    `--toggle-switch-active`. The DS lacks one shared "selected/active control" token; promote it, then use it in both places.
  - Alertas `.alerta-color-dot{border:1px solid rgba(0,0,0,.12)}` → **B**. It is a neutral hairline that must stay visible on any user-chosen colour.
  - Alertas `.alerta-color-swatch.border-only{background:#fff}` → **B**. It depicts the user colour "white/border-only", which is a data
    colour and not the UI `--surface` role (it must not follow a future surface retheme).
  - Alertas empty text `color:#6b7280` (inline) → **A** (`.table-empty` / `--text-secondary`).
  - Default-password profile cards `.access-default-card{background:#fff}` (`admin_acesso.html`) → **still present**, **A**
    (`--surface`). The same holds for `.access-policy-summary` and `.access-scope-card`.
- **Banco de Dados `.db-badge`** re-declares the shared `.badge.status-pill` palette byte-for-byte (positive/caution/neutral).
  It is category A, but fixing it means changing markup to use the shared pill classes, so it is not a zero-risk overnight edit.

## Zero-risk repair decision (§9.3)

*Superseded 2026-09-28 by the category-A pass above.* Original decision: none applied. The A items are spread across 20+ files, several of which carry accepted but uncommitted visual work. Converting them
one site at a time in an unattended batch adds review churn for a zero-visual-change result. This queue is the deliverable.

## Tokenization queue (suggested order)

1. **A (mechanical, zero visual change):** surfaces → `--surface`; field fills → `--field-bg`; muted empty-states → `.table-empty`;
   accent borders → `--accent-blue`; chip fills → chip tokens; `.btn.primary:hover` → `--btn-primary-strong`; focus outlines →
   `--focus-ring-color`. `.db-badge` → shared `status-pill` classes (markup change; needs a visual check).
2. **C (needs new tokens in `tokens.css`, no visual change if the values are adopted as-is):** `--danger-*`, `--warning-*`, `--success-*`,
   `--info-*`, `--surface-subtle`/`--hover-bg`, `--divider`, `--shadow-card`/`--backdrop`, `--text-on-brand`,
   `--control-selected` (the Alertas outline plus the toggle switch).
3. **E (user visual decision first):** converge the zinc neutral scale (Requisições/Atividades modals) onto the slate/gray tokens;
   `#0f172a` strong ink vs `--text-primary` `#1f2937`; slate muted text vs `--text-secondary`; `aluno_dashboard` legacy inline styles;
   misc one-offs.

The per-occurrence inventory (owner, selector, property, value, matching token) is reproducible with the read-only scanner
kept with the batch evidence (`b11_scan.py` → `b11_inventory.json`; `b11_classify.py` assigns the groups above).
