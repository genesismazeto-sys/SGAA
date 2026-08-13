# SGAA-EJ — Form Contract (as of DS-6)

The state of the form system after ownership consolidation, measured rather
than asserted. This is the document to read before proposing a forms redesign.

> **Nothing here is a redesign.** DS-6 moved CSS and changed no rendered pixel:
> 66/66 visual baselines pass unchanged. Where forms differ between pages
> today, that difference has been *preserved and recorded*, not unified.

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
| `.form-cards-narrow` | 12 pages, **three** widths (`0.55`, `0.70`, `0.75 × --form-card-w`) and **two** max-widths (`100vw-32px`, `100vw-64px`). |
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

Two label patterns with two different stories:

| Pattern | Uses | Responsive |
|---|---:|---|
| `.row-label` | 107 | **None.** Absolutely positioned via `.form-cards-narrow .row-label{right:calc(100% + var(--form-gap))}` at every viewport. There is no breakpoint rule for it anywhere. |
| `.field-label` | 2 templates | Reflows from absolute to block under `@media (max-width:1000px)`. |

So the dominant form layout has **no responsive fallback**. Pinned by
`form_responsive_960`, `form_responsive_640` and `form_field_label_reflow`.
This is the clearest structural gap in the form system.

---

## 6. Accessibility / focus contract

**Exists and is preserved:**

* `.field-card:hover` and `.field-card:focus-within` restyle the whole field.
* `input.control:hover/:focus`, `select`, `textarea` — border, background and
  focus ring via `--field-focus-border` / `--field-focus-ring`.
* Pinned by `form_focus_within` and `form_hover`.

**Missing, and worth knowing before a redesign:**

* **No validation styling at all.** There is no `:invalid`, `:user-invalid`,
  `aria-invalid` or `.error` rule anywhere in the codebase. Invalid fields look
  identical to valid ones; the only feedback is the browser's native bubble.
* **No `:disabled` styling for form controls.** `:disabled` rules exist for
  some buttons and menu items, never for `.control`. `form_disabled` pins the
  browser default so a change is at least detected.
* `--focus-ring-color` is defined but referenced nowhere; fields use
  `--field-focus-ring` instead.

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

**Not yet safe to change centrally** — each still needs per-page work:
the action row (`.form-actions`), form width (`.form-cards-narrow`), the file
control, the toggle switch, and anything inside the `admin_requisicoes`
runtime-injected block.

---

## 9. Recommended redesign surface

If a forms redesign is approved, the highest-value and lowest-risk order is:

1. **Add a validation contract.** Nothing exists; this is additive, so it
   cannot regress an approved appearance.
2. **Add a `:disabled` contract for `.control`.** Same argument.
3. **Give `.row-label` a responsive rule.** The dominant label pattern has none;
   this is the real defect behind any "forms look broken on a small screen"
   report.
4. **Unify `.form-actions` alignment.** One decision (`flex-end` vs the
   404 default) collapses 11 page overrides into one owned rule.
5. **Unify `.form-cards-narrow` width** into a small set of named variants
   (`--form-card-w × 0.55 / 0.70 / 0.75` are already the only three values).
6. **Unify the toggle switch** to one size.

Steps 1–3 are additive and could proceed without changing any approved pixel.
Steps 4–6 are genuine visual changes and need product sign-off; each one has a
measured before/after and a pinned baseline ready to prove the delta.
