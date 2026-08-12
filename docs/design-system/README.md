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
                          Owns no global rule. Do not add one.
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

## 3. The button contract

```
.btn.primary                 canonical primary — #003366, no elevation
.btn.primary.btn--raised     explicit raised variant — #002244 border,
                             1px shadow, 0 6px 16px hover glow
```

Both are owned by `modern-style.css`. The variant wins on **specificity**
(`0,3,0` vs `0,2,0`), not on load order, so it works regardless of which
stylesheets a page happens to include.

Use `btn--raised` when you deliberately want an elevated primary button. If you
just want the standard primary, use `.btn.primary` and nothing else.

> Before DS-3 the raised appearance was imposed by `components/list-cards.css`
> on *every* primary button of *any* page that loaded it — an accident of
> cascade order, not a decision. DS-3 preserved the rendering exactly and made
> the intent explicit. Do not reintroduce a `.btn.primary` rule in a component
> stylesheet.

### No remaining load-order divergence

DS-3b finished the job. `components/list-cards.css` no longer defines `*`,
`body`, `.btn`, `.btn:hover`, `.badge`, `.toolbar` or `.toolbar .filters`.
Those duplicated `modern-style.css` and existed only so the stylesheet could
stand alone for an unrouted demo template, which was removed.

The only selectors still shared between the two files are inside
`@media print` (`body`, `.btn`, `.toolbar` → `display:none`), which is a
separate concern, not a screen-contract duplication.

`components/list-cards.css` is now what its header always claimed: list and
card grids, toolbar composition, popovers and status badges.

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

### 5.1 The browser gate

For anything the static analyser cannot prove — selector changes, specificity
changes, markup changes — there is a Playwright harness that renders a fixed
catalogue and compares against versioned baselines.

```bash
python -m pip install playwright && python -m playwright install chromium
```

```bash
python -m pytest tests/test_visual_regression.py --visual
```

Re-approve the current appearance (a deliberate act — it accepts whatever is on
screen as correct):

```bash
python -m tools.visual.harness
```

* **47 shots**: every admin page, every aluno page, login, 404, the filter
  popover on 8 list pages, the sort popover, focus-visible and a toast.
* **Opt-in.** Skipped unless `--visual` is passed, so the canonical suite count
  and runtime stay stable. Takes ~3 minutes.
* **Tolerance: ±1 per channel, 0 pixels beyond that.** Repeated captures are
  byte-identical; across processes the compositor occasionally rounds an edge
  pixel by 1. Measured: 5 and 7 pixels out of 1,296,000, all delta 1, all on
  rounded borders. A single pixel changing by 2 fails the gate. This is much
  stricter than a percentage-of-pixels threshold, which would let a small
  element change completely as long as it was small enough.
* On failure, a red-highlighted diff and the actual render are written to
  `tests/visual/_diff/` (gitignored).

**Determinism is engineered, not assumed:**

| Source of drift | How it is pinned |
|---|---|
| Google Fonts | blocked; falls back to the stack's next entry |
| `lucide@latest` from a CDN | served from a vendored, pinned copy in `tests/visual/vendor/` |
| Clock | `Date` frozen to 2026-06-15T12:00:00Z |
| Data | database seeded from scratch each run |
| Runtime paths | fixed directory — `/admin/banco-dados` renders them |
| pytest's runtime root | capture runs in a subprocess with `APP_*` stripped |
| Animation, caret, scrollbars | disabled via injected CSS |
| Viewport | 1440×900, `deviceScaleFactor` 1 |

**Baselines are machine-specific.** With webfonts blocked, text falls back to a
system font, so a baseline captured on Windows will not match one captured on
Linux. On a new machine, regenerate rather than treating the mismatch as a
regression.

**Coverage is not uniform.** Most `.btn.primary` instances live inside popovers
and modals that are invisible on page load — of 40 templates using
`class="btn primary"`, a naive page-only catalogue detected a change to that
selector on just 4 shots. The filter-popover shots exist specifically to close
that gap and bring it to 12. When you change a component, check that some shot
actually renders it before trusting a green run.

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
| **DS-2A ✅** | Playwright visual harness, 47 versioned baselines. | validated both directions |
| **DS-3 ✅** | `.btn.primary` decoupled from list context into the explicit `.btn--raised` variant. | Playwright, 47/47, zero baseline delta |
| **DS-3b ✅** | Removed the last global rules from the component file; unrouted demo template deleted. | Playwright, 47/47 |
| DS-4 | Repatriate `<style>` blocks into owners, starting with the modal component: 118 of 136 shared declarations are byte-identical across 6 templates, 18 diverge (widths, paddings, footer alignment) and stay as page overrides. | browser gate + ratchets |
| DS-5 | Static `style=""` → component classes / custom properties. | ratchets |
| DS-6 | Responsive contract: breakpoint tokens, consolidate 16 ad-hoc breakpoints. | browser gate |
| DS-7 | Focus/accessibility contract; wire up `--focus-ring-color`. | browser gate + manual a11y pass |
| DS-8 | Dead CSS removal, with consumer evidence. | coverage evidence |

---

## 8. Pre-existing defects recorded, not yet fixed

* `--focus-ring-color` and `--btn-primary-light` are defined but never used.
* `templates/demo_impressoes.html` was unreachable (no route) and was removed
  in DS-3b. It was the only consumer of the `--imp-cols` print-shop default.
* `templates/aluno_minhas_requisicoes.html` defines `--col-id`, never used.
* 185 distinct hardcoded colour literals across 585 occurrences.
* 16 distinct breakpoints with no scale.
* `class="btn btn-primary"` (hyphen) appears in 5 places but `.btn-primary` is
  styled nowhere, so those buttons silently render as plain `.btn`.
