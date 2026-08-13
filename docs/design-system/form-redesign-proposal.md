# SGAA-EJ — FORM REDESIGN PROPOSAL / TARGET CONTRACT

**Status:** proposal, awaiting product approval. Nothing implemented.
**Scope:** forms only. Buttons, cards, tables, navigation, toolbars and the
modal *shell* are explicitly out of scope and must not shift to match.

---

## 0. Design intent

SGAA already has a distinctive field pattern: **a bordered card containing a
leading icon chip and a borderless control**, with the label in a fixed column
to its left. That pattern is good and is not being replaced.

This refresh does three things and no more:

1. **Completes** what is missing — validation, disabled/read-only, required
   indicators, responsive labels.
2. **Resolves** historical variants that have no functional reason to differ —
   four form widths, two toggle sizes, two file-chip colours.
3. **Tightens** spacing and typography onto a token scale, so the form system
   is describable rather than incidental.

It is not a stylistic reset. Field height stays `32px` (`--btn-h`), radius
stays `4px`, and the palette stays the existing one.

---

## 1. Measured inventory this proposal is based on

| | |
|---|---:|
| Templates rendering `.form-cards*` | 20 |
| `.field-card` instances | 141 |
| `.field-chip` instances | 161 |
| `.row-label` / `.field-label` | 111 / 19 |
| `.help` helper texts | 65 |
| `.form-actions` | 21 in 20 templates |
| Controls with `required` | 95 |
| Labels with a typed `*` | 7 |
| `<select>` / `<textarea>` / `input[type=file]` | 67 / 18 / 18 |
| Distinct form widths | **4** (`0.55`, `0.70`, `0.75`, `0.78` × `--form-card-w`) |
| Distinct toggle sizes | **2** (46×24, 42×22) |

The `required`/`*` mismatch is the sharpest finding: **95 controls are
functionally required, 7 say so visually.**

---

## 2. Field anatomy

```
.form-row
├─ .row-label            label, fixed column, right-aligned to the field
└─ .field-card           the bordered surface  ── states live here
   ├─ .field-chip        leading icon, 40px, divider on the right
   ├─ .control           input | select | textarea, borderless
   └─ .field-affix       (new, optional) trailing chip: unit, reveal, action
.field-help              (formalised .help) helper OR error message
```

Rules:

* The **card** owns border, background, radius and all state colour.
  The control never draws its own border. This is already true; it becomes
  explicit and enforced.
* `.field-chip` is optional. Fields without an icon keep the same height and
  inner padding.
* `.field-help` occupies the same slot whether it shows help or an error, so
  validation never shifts layout.

---

## 3. Labels, helper text, required

| | Today | Proposed |
|---|---|---|
| Label position | absolute, `right: calc(100% + var(--form-gap))`, width `--form-label-w` (150px) | same on wide screens, **stacked above** below the breakpoint |
| Label type | inherits | `13px`, `500`, `--text-primary` |
| Helper | `.help`, inconsistent | `.field-help`, `12px`, `--text-secondary`, `4px` below the card |
| Required | typed `*` in 7 labels | **generated from the control's `required` attribute** — no manual asterisks |

Required marker: `.form-row:has(.control[required]) .row-label::after` emits a
`*` in `--color-danger`. It cannot drift from the actual constraint, and the 7
hand-typed asterisks get removed so they do not double up.

---

## 4. States

All state colour is applied to `.field-card`; the control only inherits.

| State | Border | Background | Ring | Notes |
|---|---|---|---|---|
| rest | `--field-border` | `--field-bg` | — | unchanged |
| hover | `--field-hover-border` | `--field-hover-bg` | — | unchanged |
| focus | `--field-focus-border` | `--field-focus-bg` | `0 0 0 2px --field-focus-ring` | **ring 1px → 2px** |
| invalid | `--field-invalid-border` | `--field-invalid-bg` | on focus only | **new** |
| valid | `--field-valid-border` | `--field-bg` | — | **new, opt-in only** |
| disabled | `--field-disabled-border` | `--field-disabled-bg` | — | **new** |
| read-only | `--field-border` | `--field-readonly-bg` | focus ring kept | **new** |

Design decisions worth flagging:

* **Validation triggers on `:user-invalid`, not `:invalid`.** `:invalid` marks
  every empty required field red before the user has typed anything, which
  would make every "Adicionar" form open in an error state. `:user-invalid`
  fires only after interaction or a submit attempt. `[aria-invalid="true"]` is
  honoured too, for server-rendered errors.
* **Success styling is opt-in** (`.is-valid`), never automatic. Painting every
  correctly-filled field green is noise in a data-entry system.
* **Disabled is visually distinct from read-only.** Disabled means "not
  applicable"; read-only means "value shown, not editable" — the latter keeps
  normal text contrast and stays focusable.

---

## 5. Resolved historical variants

| Variant | Today | Proposed | Rationale |
|---|---|---|---|
| Form width | 4 values (0.55/0.70/0.75/0.78) | **3 named**: `.form-cards-narrow` (0.55), `--wide` (0.70), `--full` (0.78) | 0.75 collapses into 0.70; 1 template affected |
| Toggle **size** | 46×24 and 42×22 | **one**: 42×22 | majority (2 of 4 templates); knob offset 2px, travel 20px |
| File chip colour | `#000` vs `--text-tertiary` | `--text-secondary` | neither is a token today |
| Action row | 11 pages `flex-end`, 404 default | **`flex-end` canonical** | product decision |
| Auto-grow textarea | `1.35/6px` vs `1.2/8px` | `1.35/8px` | one rhythm |

### Toggle shape — preserved exactly, not restyled

The toggle is **rectangular** and must stay rectangular. Measured, identical in
all four templates:

```css
.toggle-switch-slider          { border-radius:3px;  background:#cbd5e1; }
.toggle-switch-slider::before  { border-radius:15%;  width:18px; height:18px;
                                 background:#fff;
                                 box-shadow:0 1px 3px rgba(15,23,42,.24); }
input:checked + .toggle-switch-slider { background:#0f5b99; }
input:focus-visible + .toggle-switch-slider {
                                 outline:2px solid rgba(37,99,235,.35);
                                 outline-offset:2px; }
transition: .18s ease
```

A `3px` track with a `15%`-radius knob is a deliberate rectangular switch, not
an approximation of a pill. **Only the size is being unified — the shape,
colours, knob shadow, travel timing and focus outline are preserved verbatim.**

Note `rgba(37,99,235,.35)` is exactly the value of the orphaned
`--focus-ring-color` token. The toggle is the only component using it, which
settles what that token should mean when it is finally wired up.

**Preserved as legitimate:** `.field-card.split-2` / `.compact-left` /
`.is-compact` — these encode real layout differences (two-value rows, dense
modal rows), not drift.

**`404.html`:** per the product decision it leaves the form contract. It stops
using `.form-actions` and gets a plain link row. Expected delta: **zero** —
with a single child the flex container renders identically. This will be
proven, not assumed.

---

## 6. Layout and responsive

```
--form-label-w      150px   label column (unchanged)
--form-gap          12px    label ↔ card gap (unchanged)
--form-row-gap      12px    row ↔ row (was --form-gap, split out)
--form-stack-at     720px   NEW: below this, labels stack above fields
```

At `≤720px`: `.row-label` becomes `position:static`, full width, `4px` below;
the field takes the full row. This is the **first responsive rule the dominant
label pattern has ever had** — currently it stays absolutely positioned at every
viewport, which is the real defect behind narrow-screen form breakage.

`.field-label` (2 templates) keeps its existing `1000px` reflow so those pages
do not move; it is folded into the same rule set in a later slice.

---

## 7. Spacing and typography

| Token | Value | Use |
|---|---|---|
| `--field-h` | `32px` (= `--btn-h`) | field height, unchanged |
| `--field-px` | `12px` | control horizontal padding |
| `--field-chip-w` | `40px` | leading chip |
| `--field-font` | `14px` | control text |
| `--field-label-font` | `13px / 500` | label |
| `--field-help-font` | `12px` | helper and error |
| `--field-help-gap` | `4px` | card → helper |

---

## 8. New tokens required

```css
/* state colour */
--field-invalid-border   #b91c1c   /* already the system danger colour */
--field-invalid-bg       #fef2f2
--field-invalid-ring     rgba(185,28,28,.18)
--field-invalid-text     #b91c1c
--field-valid-border     #3e835a   /* = --status-pill-dot, positive */
--toggle-track-off       #cbd5e1
--toggle-track-on        #0f5b99
--toggle-knob-radius     15%      /* rectangular switch, NOT a pill */
--toggle-track-radius    3px
--field-disabled-bg      #f3f4f6
--field-disabled-border  #e2e8f0
--field-disabled-text    #9ca3af
--field-readonly-bg      #f8fafc
/* rhythm */
--field-px --field-chip-w --field-help-gap
--field-label-font --field-help-font --form-row-gap
```

`--focus-ring-color` is currently defined and referenced nowhere. It becomes
the single focus token, with `--field-focus-ring` aliased to it.

---

## 9. Ownership after the redesign

| File | Gains |
|---|---|
| `foundation/tokens.css` | the ~14 new tokens above |
| `components/form.css` | full field anatomy, all states, required marker, helper, responsive rule, action row, toggle, file control |
| `modern-style.css` | **loses** its form section to `form.css` — one owner, not two |
| page `<style>` | keeps only genuine page layout; the width variants become classes |

This closes the split ownership recorded in the DS-6 contract.

---

## 10. Expected screenshot deltas

66 baselines. **33 expected to change, 33 must not.**

**Expected to change (33)** — every shot rendering a form surface:

```
form_disabled              form_focus_within          form_hover
form_file_control          form_responsive_640        form_responsive_960
form_field_label_reflow
modal_alerta               modal_aluno_reporte        modal_arquivo
modal_atividades_grupos    modal_atividades_import    modal_requisicao
modal_requisicao_presets   modal_turmas_import
page_admin_adicionar_aluno      page_admin_adicionar_atividade
page_admin_adicionar_curso      page_admin_adicionar_matriz
page_admin_adicionar_turma      page_admin_alertas
page_admin_arquivos             page_admin_atividades
page_admin_banco_dados          page_admin_configuracoes
page_admin_demo_form_pack       page_admin_meus_dados
page_admin_requisicoes          page_admin_turmas
page_admin_turmas_importar      page_aluno_meus_dados
page_aluno_nova_requisicao      page_aluno_reportar
```

**Must NOT change (33)** — no form surface. Any delta here is a bug:

```
page_404                        page_login
page_admin_acesso               modal_acesso_edit        modal_acesso_password
page_admin_alunos               page_admin_cursos        page_admin_matrizes
page_admin_dashboard            page_admin_mensagens     page_admin_reportes
page_admin_catalogo_versoes     page_admin_mapeamento_legado
page_admin_importar_requisicoes page_admin_normas_atividade
page_admin_nova_requisicao      modal_reporte
page_aluno_arquivos             page_aluno_dashboard
page_aluno_progresso            page_aluno_requisicoes
state_filter_* (8)              state_focus_visible
state_sort_popover              state_toast_success
state_toolbar_search_focus
```

Note `page_admin_acesso` uses its own `.access-modal-*` namespace and
`page_login` has no `.field-card`/`.control` at all — both are genuinely
outside the form contract.

New shots to add before implementing: `form_invalid`, `form_valid`,
`form_readonly`, `form_required_marker`, `form_stacked_720`.

---

## 11. Migration plan

Each step is separately gated and separately reviewable.

| Step | Content | Expected delta |
|---|---|---|
| **F-0** | Render a real before/after preview page exercising every field state, from the running app. **Approval runs on that, not on a mockup.** | n/a |
| **F-1** | Add the new state coverage shots against today's build | 0 (additive) |
| **F-2** | Tokens only — add the ~14 new custom properties, reference none | **0** |
| **F-3** | Additive states: validation, disabled, read-only, required marker | changes only where those states are captured |
| **F-4** | Responsive `.row-label` stacking | `form_responsive_640` + new `form_stacked_720` |
| **F-5** | Resolve variants: widths, toggle size, file chip, textarea rhythm | the affected subset |
| **F-6** | Action row `flex-end` canonical; 404 leaves the form contract | form pages; **404 must stay identical** |
| **F-7** | Move the form section out of `modern-style.css` into `form.css` | **0** — pure relocation, static gate provable |
| **F-8** | Refresh spacing/typography onto the token scale | all form surfaces |

Order rationale: everything with **zero** expected delta (F-2, F-7) is proven
mechanically; everything additive (F-3) cannot regress an approved appearance;
the genuine visual changes (F-5, F-6, F-8) come last, each with a reviewable
before/after.

Baselines are replaced **only** after the rendered result is shown and
approved, one step at a time, and never to make a test pass.

---

## 11b. Why approval must run on real renders

An earlier hand-drawn mockup of this proposal got three things wrong against
the real CSS: it drew the toggle as a pill with a circular knob (it is a
rectangle, `radius 3px` track / `15%` knob), coloured the field chip
`--text-secondary` (it is `--text-tertiary`), and omitted the field card's
`box-shadow: var(--shadow-sm)`.

None of those were in the plan — they were drawing errors. But a redesign whose
whole premise is "restrained, consistent with what exists" cannot be approved
against an approximation of what exists. So step **F-0** renders a real preview
page from the running application, through the same Playwright harness that
produces the baselines, and that render is what gets approved.

The 66 committed baselines are the authoritative "before". Nothing hand-drawn
is.

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| `:has()` for the required marker | Chromium/Firefox/Safari all support it; the marker is decorative — if unsupported, the field is simply unmarked, never broken |
| `:user-invalid` support | Same; degrades to no error styling, not to wrong styling |
| The 55 runtime-injected declarations in `admin_requisicoes` still override form CSS | F-3..F-8 must be checked against `modal_requisicao`; that block is scheduled for its own slice |
| 20 form templates still carry page CSS | Each step is measured against all 66 baselines, not just the page being edited |
| Print output is unverified | Out of scope; recorded in the roadmap |
