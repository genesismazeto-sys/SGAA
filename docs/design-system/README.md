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
    modal.css           ← the shared modal contract (overlay/card/header/
                          body/footer). Size and placement stay per page.
    form.css            ← shared form compositions. See form-contract.md.
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

Enforced by `test_templates_with_style_blocks_does_not_grow` and
`test_cross_template_duplication_does_not_grow`. The second one is the metric
that actually tracks progress: line counts barely move when duplicated rules
are written as one-liners, but the count of byte-identical declarations shared
between templates falls every time a family gets an owner.

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

**The sort control focus contract (F-7).** `#sort-field` and its direction
toggle set `outline:0` and `box-shadow:none` unconditionally, so those applied
in the focus state too: measured on all four live id families, the focused
presentation was identical to the resting one while `:focus-visible` matched. A
keyboard user had two invisible stops on every list page. The
`.input-group:has(> input, > select):focus-within` rule that rescues the search
box cannot help — an ordenar group contains only buttons.

The indicator is drawn **inside** the control, `outline-offset:-2px`. Measured
group geometry, identical on all four families: the group is 32px tall with
`overflow:hidden` and a 1px border while both controls are 30px tall, so each has
exactly 1.0px of slack top and bottom and the toggle 1.0px on the right.
Anything drawn outside the button is clipped away in full.

Everything else matches the treatment already shipped in six places (the toggle
switches, the dashboard alerta cards): `outline:2px solid` in the focus colour.
Those six hardcode `rgba(37,99,235,.35)`; **F-7 is the first consumer of
`--focus-ring-color`, the token that holds exactly that value.** Only the offset
differs, and only because of the clip above.

Specificity is load-bearing: the suppressors are `(1,0,0)` on the field and
`(2,0,0)` on the toggle, and three of the four families declare their own copies
from a page `<style>` block that loads *after* the component. The owned rule is
`:is(group) :is(control):focus-visible` at `(2,1,0)`, which wins on specificity
rather than order.

This is a focus contract for the sort controls, not a global one. The rest of
the system's focus states are unchanged.

### 2.6 Responsive contract

Delivered by DS-7 and the F-5/F-6 phases. The governing idea is that a rule
should measure **the box it actually lives in**, not the window: the shell eats
240px of sidebar plus 64px of padding plus the scrollbar gutter, so a viewport
number is wrong by an amount that changes with the platform.

**Supported width.** `768px` is the current supported floor for the list and
dashboard contracts below. Behaviour under 768 is not part of this contract.
A 360–480px phone shell is a **separate product decision** and is not claimed,
implied or supported here.

**Forms**

* `--form-gutter` reserves the space the absolutely positioned `.row-label`
  needs to the LEFT of the form. The form's left margin is floored at that
  gutter and only centres itself when there is room to spare, so the form
  narrows rather than pushing its labels out of view. Two tuned variants exist
  as named classes: `.form-cards-narrow--gutter-wide` and
  `--gutter-compact`.
* At `max-width:720px` the gutter is released and the form is contained by its
  own track (`max-width:100%`), not by a `100vw` expression. The historical
  `100vw-32` / `100vw-64` split does not survive below 720 and is gone there.
* Label **stacking** below 720 is the DS-7 contract and is unchanged by F-5.
* Where the shipped contract requires it, form width derives from the available
  track rather than the raw viewport.

See [form-contract.md](form-contract.md) for the measured detail.

**Toolbars**

* `.app-main .toolbar`, `.filters` and `.actions` all wrap. Wrapping is
  **intrinsic / container-driven**: it fires exactly when the toolbar exceeds
  its own content box, which is `.app-track`.
* **No viewport breakpoint is responsible for toolbar wrapping.** Do not add
  one — it would have to be re-derived per platform.
* Filters and actions stay visible and in DOM order; wrap reflows in DOM order,
  so tab order is unchanged. Nothing is hidden, reordered or scrolled away.
* The `.app-main` scoping and the separate `row-gap` longhand are load-bearing:
  a bare `.toolbar{row-gap:8px}` loses to the `gap` shorthand on
  `.app-main .toolbar`, and using the `gap` shorthand here would overwrite the
  2px column gap that sets the horizontal rhythm.

**Popovers**

* Sort, filter and the actions menus share one clamp on **both axes**. Where it
  binds, the popover sits exactly **12px** inside the viewport edge; where it
  does not bind, the popover stays on its button with the usual 6px gap.
* **Both axes are clamped (F-7).** The vertical axis was previously deferred on
  the premise that "an overrun bottom edge still scrolls with `.app-main`, so it
  stays reachable". **That premise was measured and is false.** `.app-layout` is
  `height:100vh` and `.app-main` owns the scroll, so `window.scrollY` is 0 and
  the document never scrolls: `openPopover` writes viewport coordinates into an
  absolutely positioned element whose containing block is the initial containing
  block, and `openFixedMenu` writes them into a fixed one. Either way the popover
  is pinned to the *screen* while its anchor scrolls away underneath. Measured on
  /admin/acesso: scrolling `.app-main` by 120px moved the button −120px and the
  popover 0px, growing the 6px gap to 126px and leaving the overflow unchanged.
  And on the only path that reaches the control at those heights — scroll the
  toolbar into view — `.app-main` is already at maximum scroll. What was off
  screen was `#filter-apply`, `#filter-clear-all` and the destructive
  `access-action-*` items.
* **Popovers are positioned once and dismissed on viewport change.** They are not
  re-positioned while open; continuous tracking would write geometry every frame
  for a menu about to be dismissed. So a `.app-main` scroll or a window resize
  closes them. The filter popover always did this; F-7 gives sort and the actions
  menus the same contract, which is what stops them floating over unrelated
  content while still reporting `aria-expanded="true"`. Scrolls originating
  *inside* a popover are exempt — `.menu-list` and `.filter-values` are their own
  `max-height:260px` scroll panes.
* **Both axes are clamped against the REAL rendered box.** Every opener reveals
  the menu before measuring it, parked at the containing block's origin so a
  shrink-to-fit box is not constrained by the edge the clamp is about to move it
  away from. `openMenu()`'s hidden-width fallback is gone: it read `offsetWidth`
  while the menu was still `display:none`, measured 0 and resolved to 190 against
  a real width of 212–395px, which is why the actions menu came to rest flush
  against the viewport edge with 0px of margin instead of 12.
* **One owner, four former copies.** `static/js/toolbar-filters.js` owns the
  clamp. `admin_acesso`, `admin_matrizes`, `admin_reportes` and
  `admin_requisicoes` each carried a byte-identical copy of it — with a 190 or
  200 fallback and their own literal 12s — and now call
  `openFixedMenu` / `bindDismissOnViewportChange` from the shared helpers object.
  `admin_atividades`'s per-row "more" menu is deliberately **not** in this family:
  it is a row context menu with its own 8px margin that already measures after
  reveal and already flips above its anchor.

**Dashboards**

* `.app-track` is `container-type:inline-size` with `container-name:track`. It
  is the named query container everything inside the content column measures
  against.
* Four KPI columns have a hard intrinsic minimum:

  ```
  4 × 180px + 3 × 24px = 792px
  ```

* At an actual track of **≤791px** the grid drops to 2 columns — `.kpi-grid` on
  both dashboards and `.dashboard-turma-row-kpis` on the admin dashboard.
  The threshold is the track, never the viewport.
* An `@supports not (container-type: inline-size)` fallback with an identical
  rule body exists for engines without inline-size container queries. Its
  viewport threshold is deliberately conservative, so it switches early rather
  than late on every platform.
* Verified on Chromium, Firefox and WebKit that `container-type:inline-size`
  does **not** make `.app-track` the containing block for absolutely or fixed
  positioned descendants — the reserved label gutter and the popover/modal
  geometry are unaffected by it.

**Content block**

* `.content-block-body` may **wrap** when its children no longer fit, instead of
  running past the card edge. `gap:16px` already supplies the row gap.

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

**Style a toolbar control**
`components/list-cards.css` owns the toolbar: the input group, the chips, and
the per-control overrides for `#grp-busca-impressoes`, `#grp-ordenar`,
`#sort-field`, `#sort-toggle` and `#filter-btn`. Do not paste those into a
page. If a page genuinely needs something different, override it from that
page's own `<style>`, which loads after the component.

> Those ids are inherited from the print-shop origin of the file and mean
> nothing in SGAA. They are kept verbatim because they are the ids in the
> markup; turning them into semantic classes changes specificity from
> `(1,0,0)` and needs its own phase.

**Use a modal**
Link `components/modal.css` and use `.modal-overlay > .modal-card >
.modal-header/.modal-body/.modal-footer`. The component sets appearance and
structure but deliberately not size: give the dialog its own
`.modal-card{width;max-height}` and its own header/body/footer padding in the
page, because those legitimately differ per dialog. Never copy the core rules
into a page again.

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

* **87 shots**: every admin page, every aluno page, login, 404, the filter
  popover on 8 list pages, the sort popover, focus-visible, a toast, plus the
  responsive bands added by the F-5/F-6 phases (form containment at 640/720,
  toolbar wrap at 768–1366, the popover clamp at 768/900, and the dashboard
  grids at 768–1094), plus the four F-7 states: the filter popover and the
  actions menu vertically clamped on /admin/acesso at 1366×768, the actions menu
  at 1440 (it had no baseline at any width), and the sort control's focus ring.
  The two F-7 acesso shots are the first in this catalogue where viewport
  **height** is the load-bearing dimension, which is why they carry it in their
  names.

  One caveat worth knowing: `page_admin_mensagens` renders the *source line
  number* of every message literal, computed at runtime by AST-walking the
  templates. Editing any template that carries one shifts those numbers and
  changes that baseline — F-7 moved one origin from `admin_acesso.html:1090` to
  `:1095`. It is a content delta, not a layout one, but it means that shot is
  coupled to line numbers across the whole template tree.
* **Opt-in.** Skipped unless `--visual` is passed, so the canonical suite count
  and runtime stay stable. Takes ~6 minutes.
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

**`full_page=True` does not reach below the internal fold.** `.app-layout` is
`height:100vh` and `.app-main` is what scrolls, so the *document* is always
exactly viewport-height. A "full page" capture therefore captures the viewport
and nothing more, on every shot in this catalogue. A shot whose target sits
below that fold must scroll `.app-main` first — `toolbar_acesso_768` does, via
`scroll_toolbar_into_view`. Anything below the fold on every other shot is
**not pinned**.

### 5.2 The dashboard container contract

A screenshot cannot pin the container-query threshold, because the visual
harness injects `scrollbar-width:none` and so renders one scrollbar geometry
while the contract spans two. These tests sidestep it by setting the query
container's inline size directly and asserting the resulting column count:

```bash
python -m pytest tests/test_dashboard_container_contract.py --visual
```

* **7 tests**: 792 → 4 columns and 791 → 2 columns for `.kpi-grid` on both
  dashboards and for `.dashboard-turma-row-kpis`, plus a probe asserting that
  `container-type` has not become a containing block for absolute positioning.
* Same opt-in flag as the visual gate.

### 5.3 The popover reachability contract

```bash
python -m pytest tests/test_popover_reachability_contract.py --visual
```

38 tests. Neither the screenshot catalogue nor the static analyser can pin these:
one behaviour only appears after the user scrolls `.app-main` and opens a menu
whose bottom edge would fall past the viewport, the other only exists while a
control holds keyboard focus. They assert that every actionable control in an
opened popover is on screen, that resting geometry is untouched where no clamp
binds, that no popover is ever left detached from its anchor, that both sort
controls present differently when focused from the keyboard on all four id
families, and that all **eleven** actions menus clamp against their real width.

Five of those eleven sit behind `initToolbarRowSelection`, which returns
undefined when a list renders zero rows — and the demo seed produces no rows for
them. That gate predates F-7. Rather than skip five of eleven consumers, those
cases invoke the shared opener directly: since F-7 every one of these menus
reaches the viewport through that one function, so the geometry contract is still
exercised on the page's real markup.

**Opt-in browser total: 132 = 87 visual + 7 dashboard container-contract + 38
popover-contract.** Static Design System gates: 11
(`tests/test_ds_design_system_contract.py`, not opt-in).

**Cross-engine status: verified.** The responsive contracts in §2.6 were
verified before publication of the responsive milestone on **Chromium
151.0.7922.34, Firefox 153.0 and WebKit 26.5** — the 792/791 container
boundary, the F-5D absolute label geometry, the F-6A2 popover clamp, and the
fixed-overlay geometry of real modals inside `.app-track`. All four passed on
all three engines.

F-7 was re-verified on the same three engines, with **full agreement and no
divergence**: the vertical clamp lands on a 12px bottom margin with zero controls
off screen; non-binding popovers keep their 5.9px measured anchor gap; sort,
filter and actions all dismiss on `.app-main` scroll with `aria-expanded`
returning to `false`; the sort controls' `outline:solid/2px/-2px` renders
unclipped and `:focus-visible` matches after a real Tab on every engine
(including WebKit); and the actions menu measures 305px — not the old 190
fallback — landing 12px inside the right edge.

The committed gates themselves still run Chromium only; re-run the cross-engine
check by hand when a responsive contract changes. Note that any such run must
work around `login()`'s navigation race, which WebKit loses 11 times in 12 (§8).

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

### Completed

Ownership phases (DS) moved CSS and proved equivalence. Responsive phases
(F-5 / F-6) are the first ones that deliberately change rendered behaviour.

| Phase | Scope | Gate |
|---|---|---|
| **DS-1 ✅** | Token contract. Single owner, load-order macro, analyser + gates. | static cascade equivalence |
| **DS-2A ✅** | Playwright visual harness, 47 versioned baselines. | validated both directions |
| **DS-3 ✅** | `.btn.primary` decoupled from list context into the explicit `.btn--raised` variant. | Playwright, 47/47, zero baseline delta |
| **DS-3b ✅** | Removed the last global rules from the component file; unrouted demo template deleted. | Playwright, 47/47 |
| **DS-4 ✅** | Modal core extracted to `components/modal.css`: 27 declarations that were identical across 7 copies. The 60 that legitimately differ (width, max-height, padding, footer alignment, borders) stay as page overrides. | Playwright 58/58 |
| **DS-5 ✅** | Toolbar per-control overrides relocated: 34 declarations that were copy-pasted into 6–13 templates each (302 instances, zero divergence). | Playwright 59/59 |
| **DS-6 ✅** | Form ownership foundation. `components/form.css` created; 92 provably-shared declarations relocated; 72 look-alike declarations proven page-specific and kept. See [form-contract.md](form-contract.md). | Playwright 66/66 |
| **DS-7 ✅** | Approved form state contract: validation, disabled, read-only, required marker, 2px focus ring, and `.row-label` stacking at ≤720px. **First approved visual change.** | Playwright, 17 baselines replaced |
| **F-5B ✅** | Form widths named as tokens; redundant restatements deleted. | Playwright, zero delta |
| **F-5C ✅** | The arquivo modal takes the canonical modal form width. | Playwright |
| **F-5D ✅** | Reserved label gutter (`--form-gutter`). Fixed label clipping across the 860–1366 band on 16 of 23 label-bearing surfaces. | Playwright 70/70 |
| **F-5E ✅** | Narrow-viewport form containment: below 720 the form is bound by its track, not by `100vw`. | Playwright 72/72 |
| **F-6A1 ✅** | Toolbar wraps, container-driven, no breakpoint. Restores controls clipped from 1344px down. | Playwright 76/76 |
| **F-6A2 ✅** | Sort/filter popovers get the actions menu's horizontal viewport clamp. | Playwright 79/79 |
| **F-6B ✅** | `.app-track` becomes the named inline-size query container `track`; dashboard grids switch on the actual track at 792/791, with an `@supports` fallback. | Playwright 82/82 + 7 container-contract |
| **F-6B2 ✅** | `.content-block-body` wraps instead of running past the card edge. | Playwright 83/83 |
| **F-7 ✅** | Popover reachability on both axes, dismissal on viewport change, real-width measurement, and a visible `:focus-visible` ring on the sort controls. Reopened the F-6A2 vertical deferral on new evidence: the popover does **not** scroll with `.app-main`. | Playwright 87/87 + 7 container-contract + 38 popover-contract, cross-engine on all three |

The F-5/F-6 chain closed as the **responsive milestone**: R1 independent
adversarial review ACCEPT with zero material findings, and cross-engine
verification on Chromium, Firefox and WebKit (§5.2).

### Not started

| Phase | Scope | Gate |
|---|---|---|
| DS-2 | Extract `foundation/reset.css` + `base.css`; give the standalone demo page an explicit foundation; remove the last duplicated base rules. | static cascade equivalence |
| DS-8 | Dead CSS removal, with consumer evidence. | coverage evidence |
| — | Static `style=""` → component classes / custom properties. | ratchets |
| — | Breakpoint scale / tokens for the remaining ad-hoc viewport breakpoints. F-6 removed the viewport constant only where the binding box is the track; the rest still have no scale. | browser gate |
| — | Centralised focus contract. F-7 wired `--focus-ring-color` into the sort controls (§2.5) and proved the rest of the tab order already presents a focus state, so what remains is consolidation rather than a defect. Modals declare `aria-modal="true"` with no focus containment — that one is a real gap. | browser gate + manual a11y pass |

---

## 8. Pre-existing defects recorded, not yet fixed

This is a **register, not a work list.** Nothing here is closed by the
responsive milestone, and none of it should be picked up incidentally while
doing something else.

**Ownership / dead code**

* `--btn-primary-light` is defined but never used. (`--focus-ring-color` is now
  referenced — F-7 wired it into the sort control focus contract, §2.5.)
* `templates/demo_impressoes.html` was unreachable (no route) and was removed
  in DS-3b. It was the only consumer of the `--imp-cols` print-shop default.
* `templates/aluno_minhas_requisicoes.html` defines `--col-id`, never used.
* `templates/components/content_block.html` has no consumers — dead template.
* `.form-cards-narrow--modal` is declared in `components/form.css` but nothing
  uses it; both modals set their width through their own page rules.
* 185 distinct hardcoded colour literals across 585 occurrences.
* `class="btn btn-primary"` (hyphen) appears in 5 places but `.btn-primary` is
  styled nowhere, so those buttons silently render as plain `.btn`.
* `admin_requisicoes.html` builds a `<style>` element in JavaScript and appends
  it at runtime (~50 lines of form/file-card/button CSS). It is the only place
  in the codebase that delivers CSS this way. The modal core it duplicated was
  removed in DS-4; the rest still has no owner.
* `@media print` rules live in `components/list-cards.css` and have no owner.

**Responsive / layout**

* 16 distinct breakpoints with no scale. F-6 removed the viewport constant only
  where the binding box is the track.
* ~~**Vertical popover overflow.**~~ Fixed by F-7. The deferral's premise — that
  an overrun bottom edge stays reachable because it scrolls with `.app-main` —
  was measured and found false; see §2.6.
* ~~**`openMenu()` hidden-width measurement.**~~ Fixed by F-7, which had to
  measure the same opener for the vertical axis anyway.
* **Mobile shell / C5.** The 240px sidebar never collapses, so below roughly
  480px the content track falls under a field card's intrinsic minimum. 768px
  is the supported floor (§2.6); a 360–480px phone shell is a separate product
  decision and is **not** supported.
* **Residual narrow-form geometry below the supported floor.** Between the 720
  stacking breakpoint and 768, the `--gutter-wide` surfaces are squeezed far
  enough that field cards can exceed the form box. Measured strictly better
  than before F-5D at every width in that band, and no baseline covers it.

**Harness**

* `full_page=True` cannot reach below `.app-main`'s internal fold (§5.1), so
  content below the first viewport is unpinned on every shot except
  `toolbar_acesso_768`.
* The container-contract probe checks `position:absolute` only. The
  higher-consequence `position:fixed` case is covered by the manual
  cross-engine check (§5.2), not by a committed test.
* `tools/visual/catalogue.py`'s `login()` waits for `domcontentloaded` after
  submitting, which can resolve against the pre-POST document. Chromium and
  Firefox win that race; WebKit loses it from the second browser context on.
  Harmless today because the committed gates are Chromium-only and use one
  context, but any future multi-engine or multi-context run must account for it.
