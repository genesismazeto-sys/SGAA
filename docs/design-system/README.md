# SGAA-EJ — Design System

The visual layer of SGAA-EJ, made explicit.

This document is **operational**: it tells you where things live, what you are
allowed to do, and how to avoid breaking the approved look of the system.

> **The current appearance is approved and is a hard invariant.**
> This design system exists to make the design SGAA-EJ *already has*
> explicit and maintainable. It is not a redesign. Changing a colour, a
> spacing value or a radius because it "looks better" is out of scope.

---

## 1. Where things live

```
static/css/
  foundation/
    tokens.css          ← every global design token. Single source of truth.
  modern-style.css      ← global app UI: reset, base, layout, forms, tables,
                          buttons, cards, list grids, print helpers.
  components/
    list-cards.css      ← list/card grids, toolbars, popovers, status badges.
    actions-float.css   ← the floating actions bar (#pedido-actions-float).

templates/components/
  design_system_css.html  ← THE load-order contract. One owner, one list.

tools/ds_css.py           ← static cascade analyser + equivalence gate.
tests/test_ds_design_system_contract.py  ← the structural gates.
```

This layout is deliberately small. It grows as CSS is repatriated out of
templates — see [Roadmap](#7-roadmap). Files are not split before there is
enough content to justify a split.

---

## 2. The contracts

### 2.1 Token contract

* Every **global** token is defined in `static/css/foundation/tokens.css`,
  inside `:root`, and **nowhere else**.
* `tokens.css` contains tokens only. No selectors other than `:root`, no
  visual rules.
* A component may own **component tokens** — for example `--imp-cols` in
  `components/list-cards.css`. These live with the component. They must never
  shadow a global token.
* **Variant tokens** are the established pattern for stateful components and
  should be preferred:

  ```css
  .badge.status-pill.status-positive{
    --status-pill-bg:#e9f5e7;
    --status-pill-text:#1f5a3c;
  }
  ```

  This is scoped overriding, not duplication. It is correct — keep doing it.

Enforced by `test_global_tokens_have_exactly_one_owner`,
`test_no_token_resolves_to_two_values_on_one_page`,
`test_tokens_file_declares_tokens_only`.

### 2.2 Cascade / load-order contract

Load order is decided in exactly one place:
`templates/components/design_system_css.html`.

```
foundation/tokens.css   →   modern-style.css   →   component CSS   →   page <style>
```

* Base templates call `{{ design_system_css(static_asset_version) }}`. Do not
  add `<link>` tags for foundation or global CSS anywhere else.
* Page-specific component stylesheets are linked from the page's own
  `{% block extra_head %}`, which always renders after the macro.
* Component stylesheets must have **disjoint selectors**. If two component
  files style the same selector, their relative order becomes load-bearing and
  the architecture has failed. `list-cards.css` and `actions-float.css` are
  currently disjoint — keep it that way.

Enforced by `test_every_page_loads_the_token_foundation_first`,
`test_every_referenced_stylesheet_exists`.

**Cascade layers (`@layer`) are deliberately not used yet.** Partial adoption
inverts the cascade: unlayered rules beat layered ones regardless of
specificity, and 4.5k lines of CSS still live unlayered inside templates.
Revisit once template CSS has been repatriated.

### 2.3 Template CSS contract

CSS in a template is allowed only when it is genuinely unique to that one
page and used nowhere else.

If a rule is shared by two or more pages, it belongs in a stylesheet with a
named owner. The number of templates carrying `<style>` blocks is capped by a
ratchet test and may only go **down**.

Enforced by `test_templates_with_style_blocks_does_not_grow`.

### 2.4 Inline style contract

* `style="…"` with a **static** value is not allowed in new markup. It has no
  owner, cannot be themed, and cannot be overridden without `!important`.
  Use a component class.
* `style="…"` containing Jinja (`{{ … }}`) is legitimate when the value is
  genuinely dynamic — a computed width, a progress percentage. Prefer passing
  the value through a CSS custom property:

  ```html
  <div class="progress" style="--progress:{{ pct }}%"></div>
  ```

  so the *styling* stays in CSS and only the *data* is inline.

Enforced by `test_static_inline_style_attributes_do_not_grow`.

### 2.5 Accessibility contract

These must not regress:

* `:focus-visible` styling stays visible and distinguishable.
* Disabled and error states keep their contrast.
* `.sr-only-focusable` (the skip link) keeps working.
* `@media (prefers-reduced-motion:reduce)` keeps disabling transitions.

Known gap: `--focus-ring-color` is defined but **never referenced**. There is
no centralised focus contract yet. Do not delete the token — it is the anchor
for the focus work in a later phase.

---

## 3. Known divergence you must not "fix"

`.btn`, `.btn.primary`, `.btn.primary:hover` and `.toolbar` resolve
**differently** on pages that load `components/list-cards.css` than on pages
that do not:

| Selector | without list-cards.css | with list-cards.css |
|---|---|---|
| `.btn.primary` border | `var(--brand)` `#003366` | `var(--btn-primary-strong)` `#002244`, plus a `box-shadow` |
| `.btn.primary:hover` | no shadow | `0 6px 16px rgba(0,51,102,.18)` |
| `.btn` | `height`, `justify-content:center` | adds `min-height`, `min-width:0`, richer transition |
| `.toolbar .filters` gap | `8px` | `2px` |

This is the **current approved rendering**. It is treated as a compatibility
contract until someone consciously decides which of the two is correct.
Do not unify them silently — that is a redesign decision, not a refactor.

---

## 4. How to do common things

**Add a new page**
1. `{% extends "base.html" %}` (admin) or `base_aluno.html` (aluno). The
   foundation loads automatically.
2. If it is a list/card page, link `components/list-cards.css` from
   `{% block extra_head %}`.
3. Use existing component classes. Add page-unique CSS only if it truly is
   page-unique.

**Add a colour / spacing value**
Check `foundation/tokens.css` first. If an equivalent token exists, use it.
If not, and the value is used in more than one place, add a token. A one-off
value inside a single component may stay literal.

**Add a component**
Create `static/css/components/<name>.css`, add it to the page's
`extra_head`, and keep its selectors disjoint from other component files.
Document its variants at the top of the file.

**Change how something looks**
Stop. That is a visual change and needs product sign-off. This document
covers refactoring, not redesign.

---

## 5. Visual regression: how equivalence is proved

`tools/ds_css.py` statically resolves, for every page template, the ordered
stream of CSS declarations that page loads, and the winning declaration for
each `(at-rule context, selector, property)` triple.

Two invariants prove that a move/merge/delete refactor cannot change rendering:

* **ORDER** — the new declaration stream is a *subsequence* of the old one.
  Nothing was reordered or inserted.
* **RESOLUTION** — every `(context, selector, property)` still resolves to the
  same value, and `var()` chains resolve to the same literal.

Usage:

```bash
python tools/ds_css.py --out before.json
```

```bash
python tools/ds_css.py --compare before.json
```

**Limits — read these before trusting the result.**

* Winners are resolved **per exact selector text**, not per DOM element.
  Identical selector text implies identical specificity, so document order
  decides — which is exactly what proves *file reorganisation* safe.
* It does **not** model cross-selector competition (`.btn` vs `.toolbar .btn`).
  Any phase that changes selector text, specificity, or markup is **outside
  what this gate can prove** and needs a browser-based check.
* It does not see styles applied by JavaScript.
* A green backend test suite is **not** evidence of visual equivalence.

There is currently **no browser-based pixel-diff harness** in this repository.
Adding one (Playwright) is proposed for the phase that reworks the `.btn`
contract, because that phase changes specificity and the static gate cannot
cover it.

---

## 6. JavaScript-managed styles

There are ~147 places where JavaScript writes to `.style.*` or `.style.cssText`
(popover positioning, column sizing, show/hide). CSS refactors do not see them.

Rule going forward: JavaScript may set **geometry and visibility** computed at
runtime (`top`, `left`, `display`, custom properties). It should not set
colours, borders, radii, shadows or fonts — those belong to a class or a token.
Existing violations are tracked, not yet migrated.

---

## 7. Roadmap

| Phase | Scope | Gate |
|---|---|---|
| **DS-1 ✅** | Token contract. Single owner, load-order macro, analyser + gates. | static cascade equivalence |
| DS-2 | Extract `foundation/reset.css` + `base.css`; give the standalone demo page an explicit foundation; remove the last duplicated base rules. | static cascade equivalence |
| DS-3 | Model the `.btn` / `.toolbar` divergence as explicit named variants. **Changes specificity** → needs a browser gate first. | Playwright pixel-diff |
| DS-4 | Repatriate `<style>` blocks from templates into owners, one component family at a time. | browser gate + ratchets |
| DS-5 | Static `style=""` → component classes / custom properties. | ratchets |
| DS-6 | Responsive contract: breakpoint tokens, consolidate 16 ad-hoc breakpoints. | browser gate |
| DS-7 | Focus/accessibility contract; wire up `--focus-ring-color`. | browser gate + manual a11y pass |
| DS-8 | Dead CSS removal, with consumer evidence. | coverage evidence |

---

## 8. Pre-existing defects recorded, not yet fixed

* `--focus-ring-color` and `--btn-primary-light` are defined but never used.
* `templates/demo_impressoes.html` has **no route** — it is unreachable from
  the running app. It referenced 8 tokens that never resolved.
* `templates/aluno_minhas_requisicoes.html` defines `--col-id`, never used.
* 185 distinct hardcoded colour literals across 585 occurrences.
* 16 distinct breakpoints with no scale.
* `.btn` / `.toolbar` dual contract (section 3).
