# SGAA-EJ — Form Contract (as of F-5E)

The state of the form system after ownership consolidation, measured rather
than asserted. This is the document to read before proposing a forms redesign.

> DS-6 moved CSS and changed no rendered pixel. **DS-7 is the first approved
> visual change**: required markers, validation, disabled, read-only, a 2px
> focus ring and responsive labels. 17 baselines were replaced with approved
> renders; the other 49 are byte-unchanged. Everything not listed as changing
> keeps its current rendered value.
>
> **F-5B → F-5E then changed form width and responsive behaviour** (see §5).
> F-5B named the widths as tokens, F-5C gave the arquivo modal the canonical
> modal width, F-5D reserved the label gutter, and F-5E contained the form in
> its own track below 720px. The **locked anatomy is unchanged** by all of it:
> field cards, chips, the toggle switch, colours, typography and the DS-7
> form-state contracts all keep their approved rendered values. What moved is
> where the form sits and how wide it is.

---

## 1. Canonical owners

| Owner | Declarations | Responsibility |
|---|---:|---|
| `static/css/modern-style.css` | 405 | **Form primitives.** `.form-row`, `.row-label`, `.field-label`, `.field-card` base, `.field-chip`, `.control`, `input/select/textarea`, and the hover / focus contract on all of them. |
| `static/css/components/form.css` | 46 | **Form compositions** that every page able to render them already agreed on: `.field-card` composite variants (`split-2`, `compact-left`, `is-compact`), the import-modal form grid, `.input-with-icon`. |
| `static/css/components/list-cards.css` | 91 | Filter/search inputs inside list toolbars. Form-shaped, but toolbar-owned. |
| page `<style>` | 864 | Everything else — see §4. |
| JS-injected (1 site) | 55 | See §5. |

**37% owned, 62% still in templates.** That is the honest headline. DS-6
established ownership and removed what was provably duplicated; it did not
repatriate the long tail, because most of it is genuinely page-specific.

*The declaration counts in this table are the DS-6 measurement and have not been
re-measured since. F-5B–F-5E added rules to `components/form.css` without moving
the ownership boundary, so the split is directionally unchanged but the absolute
numbers are stale. Re-run `tools/ds_css.py` before quoting them.*

Load order (from `templates/components/design_system_css.html`):

```
tokens.css → modern-style.css → components/form.css → page component links → page <style>
```

`form.css` sits immediately after the primitives so it overrides them exactly
as the page-level copies it replaced used to.

---

## 2. Shared components

* `.field-card.split-2` / `.split-2.compact-left` — two- and four-column field
  rows.
* `.field-card.is-compact` — 32px dense variant.
* `.field-card.file-card` — the file control (chip, hidden input, filename,
  right-hand action chip). **Partly shared, partly per-page — see §3.**
* `.import-modal-form` / `.import-modal-grid` — the CSV-import form layout.
* `.input-with-icon` — relative wrapper for an icon-in-field.

---

## 3. Page-specific variants that must NOT be unified silently

These 72 declarations *look* duplicated but failed the safety test: at least
one page that renders the same markup does **not** carry them. Hoisting any of
them changes that page.

| Family | Why it is not shared |
|---|---|
| `.form-actions` | 11 templates align it `flex-end`. `404.html` renders `.form-actions` **without** that override and is left-aligned today. The visual gate caught exactly this when it was hoisted. |
| `.form-cards-narrow` | 12 pages, **three** widths (`0.55`, `0.70`, `0.75 × --form-card-w`). *Superseded in part:* F-5B named those three widths as tokens, and F-5E ended the old `100vw-32px` / `100vw-64px` max-width split below 720px — both families are now bound by their own track there. See §5. |
| `.field-card.file-card` | Styled in only some of the templates that render it. `admin_requisicoes` paints its chip `#000`; `aluno_nova_requisicao` uses `var(--text-tertiary)`. |
| `.toggle-switch` | Three templates, **two** sizes: 46×24 (`admin_alertas`) and 42×22 (`admin_banco_dados`, `admin_configuracoes`), with matching slider offsets. |
| `.modal-card textarea.control.auto-grow` | `admin_alertas` uses `line-height:1.35 / padding:6px`; `admin_arquivos` uses `1.2 / 8px`. |

14 further declarations are outright **divergent** across templates and are
listed by `tools/ds_css.py`.

---

## 4. Remaining inline / runtime form CSS

* **864 declarations in page `<style>` blocks.** 118 unique are still
  byte-identical across more than one template (333 instances) but did not pass
  the "every renderer declares it" test, so hoisting them is a visual decision,
  not a refactor.
* **55 declarations injected at runtime by JavaScript**, in
  `templates/admin_requisicoes.html`. It builds a `<style>` element and appends
  it to `<head>`, so it lands last in the cascade.
  DS-6 moved 8 declarations out of it — the ones that were provably shared —
  and left the rest. Migrating the remainder means unpicking the requisição
  form pack, the file-card styling and three action-button colour variants
  (`.btn-indeferir`, `.btn-parcial`, `.btn-deferir`) that exist nowhere else.
  That is its own slice.
* **198 static `style=""` attributes** across all templates (ratcheted).

---

## 5. Responsive behaviour

> **Reconciled after DS-7 and F-5D/F-5E.** This section previously recorded that
> `.row-label` had no responsive rule and that the dominant form layout had no
> responsive fallback. **That is no longer true** — it was the measured state
> before DS-7, and it is kept here only as the reason the work happened.

Two label patterns:

| Pattern | Uses | Responsive |
|---|---:|---|
| `.row-label` | 107 | **Yes, in two tiers.** Above 720px it stays absolutely positioned via `.form-cards-narrow .row-label{right:calc(100% + var(--form-gap))}`, but the form now reserves `--form-gutter` on its left so the label can no longer be pushed out of view (F-5D). At `max-width:720px` it stacks above its control (DS-7). |
| `.field-label` | 2 templates | Reflows from absolute to block under `@media (max-width:1000px)`. |

**The width contract that goes with it:**

* `--form-gutter` = the room a form must keep on its left before it may centre
  itself. Default `--form-label-w + --form-gap`; overridden by the named classes
  `.form-cards-narrow--gutter-wide` and `--gutter-compact`.
* The form's left margin is `max(gutter, centred position)`, so it centres
  whenever there is room and parks at the gutter when there is not. The form
  narrows rather than pushing labels off the left edge, where nothing scrolls to
  reveal them.
* Below 720px the gutter is released (stacked labels need no left column) and
  both families are contained by `max-width:100%` — their own track — instead of
  a `100vw` expression that does not know the 240px sidebar exists (F-5E).

Pinned by `form_responsive_960`, `form_responsive_720`,
`form_responsive_wide_720`, `form_responsive_640` and
`form_field_label_reflow`.

**Supported floor: 768px.** Below the 720px stacking breakpoint the contract
holds; in the narrow band just above it the `--gutter-wide` surfaces are
squeezed hard enough that field cards can exceed the form box. That is recorded
as debt in the [README](README.md) §8 and is not claimed as supported.

---

## 5b. Native state population (measured, DS-7)

The new disabled and read-only treatments apply wherever those attributes
genuinely exist in markup. That population was never measured before DS-7, and
not measuring it is why the expected-delta forecast under-predicted:

| Template | disabled | read-only |
|---|---:|---:|
| `admin_editar_aluno.html` | 6 | 6 |
| `admin_matriz_form.html` | 2 | 9 |
| `admin_curso_form.html` | 1 | 4 |
| `aluno_nova_requisicao.html` | 0 | 9 |
| `aluno_meus_dados.html` | 0 | 2 |
| `admin_atividades.html` | 0 | 1 |
| `admin_requisicoes.html` | 0 | 1 |
| **total** | **9** | **32** |

Before DS-7 all 41 rendered identically to editable fields.

---

## 5c. Deriving expected deltas — do not hand-map

`page_admin_nova_requisicao` was classified in the DS-7 proposal as having *no
form surface*, because `admin_requisicao_nova.html` contains no `.field-card`.
The live route in fact renders **14 field cards, 12 row labels and 7 required
controls**. The forecast was wrong and the visual gate caught it.

Hand-mapping a URL to a template cannot be trusted: routes pick templates at
runtime (`base_template|default(...)`, a differently-named `render_template`,
includes, partials). Use the resolved DOM instead:

```bash
python -m tools.visual.form_surface
```

It loads every catalogue shot in its own role and counts **visible** matches
for `.field-card`, `.control`, `.row-label`, `.form-actions`, `required`,
`:disabled`, `[readonly]` and `.toggle-switch`. Visibility matters: pages such
as `admin_requisicoes` carry an entire hidden modal form and look like large
form surfaces while rendering none of it.

Validated against DS-7: predicting "required marker appears where a required
control and a row-label are both visible" reproduced the 17 changed shots
exactly — no false positives, no false negatives.

---

## 6. Accessibility / focus contract

**Exists and is preserved:**

* `.field-card:hover` and `.field-card:focus-within` restyle the whole field.
* `input.control:hover/:focus`, `select`, `textarea` — border, background and
  focus ring via `--field-focus-border` / `--field-focus-ring`.
* Pinned by `form_focus_within` and `form_hover`.

**Added in DS-7:**

* **Validation, two independent paths.** `:user-invalid` for native browser
  validation and `[aria-invalid="true"]` for server-rendered errors. They are
  different selectors and are pinned by two separate shots —
  `form_invalid_user` and `form_invalid_aria` — so they cannot regress
  together unnoticed. `:invalid` is deliberately not used: it would flag every
  empty required field the moment a blank form opened.
* **Disabled** — muted surface, `--text-tertiary`, `not-allowed`.
* **Read-only** — `--field-readonly-bg` (`#f1f5f9`) with `--text-secondary`.
  Deliberately *not* disabled semantics: fully readable, still focusable,
  normal cursor, no textual badge. The first attempt used `#f8fafc`, which was
  invisible against the white card on the real render.
* **Focus ring 1px → 2px** via `--field-focus-ring-w`. The ring **colour is
  unchanged**.
* **Required marker** generated from the control's own `required` attribute.

`--focus-ring-color` was deliberately **not** wired into fields: its value is
`rgba(37,99,235,.35)` while the field ring is `rgba(3,105,161,.22)`, so
adopting it would have changed an approved colour. It is the literal the
toggle's focus outline already uses, which is where it belongs.

---

## 7. Duplication remaining

| Metric | DS-0 | after DS-6 |
|---|---:|---:|
| Form declarations owned by a stylesheet | 405 (27%) | **542 (37%)** |
| Form declarations in templates | 1001 (66%) | **919 (62%)** |
| Duplicated identical (form) | 160 unique / 421 inst. | **118 unique / 333 inst.** |
| Cross-template duplication (all CSS) | 623 | **541** |

---

## 8. What is now safe to redesign centrally

Because these have a single owner, a change here lands everywhere at once:

* **Field primitives** — `.field-card`, `.field-chip`, `.control` geometry,
  colour, border and radius (`modern-style.css`).
* **Focus / hover contract** — one place, one set of tokens.
* **Field composite variants** — `split-2`, `compact-left`, `is-compact`
  (`components/form.css`).
* **Import-modal form layout** (`components/form.css`).
* **Modal shell** around any form (`components/modal.css`, from DS-4).
* **Tokens** — `--form-card-w`, `--form-gap`, `--form-label-w`,
  `--form-top-pad`, `--field-*` (`foundation/tokens.css`).

**Form width (`.form-cards-narrow`) is now safe to change centrally.** F-5B
named the three widths as tokens, F-5C removed the arquivo modal's divergent
width, and F-5D/F-5E gave the family one owned width-and-gutter contract (§5).
Change it in `modern-style.css` / `components/form.css`, not per page — but note
the two tuned gutter variants and the modals' own `(0,2,0)` rules, which are
deliberate and must keep winning.

**Not yet safe to change centrally** — each still needs per-page work:
the action row (`.form-actions`), the file control, the toggle switch, and
anything inside the `admin_requisicoes` runtime-injected block.

---

## 9. Recommended redesign surface

If a forms redesign is approved, the highest-value and lowest-risk order is:

Steps 1–3 and 5 are **done**; they are kept here so the order and its reasoning
stay legible.

1. ~~**Add a validation contract.**~~ Delivered by DS-7.
2. ~~**Add a `:disabled` contract for `.control`.**~~ Delivered by DS-7.
3. ~~**Give `.row-label` a responsive rule.**~~ Delivered by DS-7 (stacking at
   ≤720px) and F-5D (the reserved gutter above it). This was the real defect
   behind "forms look broken on a small screen"; see §5 for the shipped
   contract.
4. **Unify `.form-actions` alignment.** One decision (`flex-end` vs the
   404 default) collapses 11 page overrides into one owned rule. **Still open.**
5. ~~**Unify `.form-cards-narrow` width** into a small set of named variants~~
   (`--form-card-w × 0.55 / 0.70 / 0.75`). Delivered by F-5B/F-5C, with the
   gutter and containment contract added by F-5D/F-5E.
6. **Unify the toggle switch** to one size. **Still open.**

Remaining steps 4 and 6 are genuine visual changes and need product sign-off;
each one has a measured before/after and a pinned baseline ready to prove the
delta.
