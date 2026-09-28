# UI-B11 — Raw-colour / tokenization audit

**Status:** AUDIT_COMPLETE — CATEGORY_A_REDUCED / TOKENIZATION_QUEUE_REMAINS (2026-09-28, second extended batch).
The original audit changed no colour; the category-A pass below converted **39** exact duplicates (498 → **459**).

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

**Remaining A — 13 (not zero-risk, left for a later decision):**
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
