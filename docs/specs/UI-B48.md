# SPEC UI-B48 — Shared floating action bar below menus and modal layers

Status: CLOSED 2026-11-21 (development branch; PRODUCTION HOLD; owner visual acceptance PASS 2026-11-21)
Charter: "Correct the pre-existing stacking and visibility defects where floating row-action bars cover
open menus, popovers or modal backdrops on SGAA list pages." Starting HEAD
`a97b883b23f1782f18cc6b1107dc7d1b1596bf94`; synthetic data only; commit and push to the development
branch; no deployment.
Risk tier: R1 (one shared CSS declaration; no route, template, client script, RBAC, schema or data
change).

## 1. Outcome

- An open menu, popover or modal backdrop/dialog is never painted under the floating row-action bar;
  the bar is page chrome and sits below every overlay layer.
- The correction is one rule at the shared owner (`static/css/components/actions-float.css`), not a
  page-local patch; every list page that uses the bar inherits it.
- Closing the menu or dialog restores the bar's normal behaviour. Row selection, keyboard interaction,
  permissions and the actions themselves are unchanged (no JavaScript or markup change).
- UI-B47's accepted dismissal flow and UI-B49's accepted quick-action dialog keep their behaviour.

## 2. Current facts

- The bar is created by fourteen templates, all linking `css/components/actions-float.css`:
  `admin_acesso`, `admin_alertas`, `admin_alunos`, `admin_arquivos`, `admin_atividades`,
  `admin_catalogo_versao_detalhe`, `admin_cursos`, `admin_detalhes_turma`, `admin_matrizes`,
  `admin_reportes`, `admin_requisicoes`, `admin_turmas`, `aluno_arquivos`,
  `aluno_minhas_requisicoes`.
- `#pedido-actions-float.pedido-actions-float` declared `z-index: 1200`
  (`actions-float.css`, line 7). The shared owners it must sit below are `.popover`
  `z-index: 1000` (`components/list-cards.css`, line 174) and `.modal-overlay` `z-index: 40`
  (`components/modal.css`, line 31); the mobile navigation is 30 with a 29 backdrop
  (`modern-style.css`), and the sticky table header is 5.
- Reproduced in real Chromium on `a97b883`, 1440 x 900, `admin/Acesso`: hovering a row shows the bar
  (`1200`); the row's edit action opens `#access-modal` (`40`) while the pointer keeps the bar visible.
  The bar's rectangle (x 1263, y 767, 130 x 36) stayed bright above the scrim and
  `document.elementFromPoint` at its centre returned `pedido-actions-float`, not the dialog. Screenshot:
  `D:\SGAA_tmp\ui_b48\before\ui-b48-before-modal-desktop.png` (bar average RGB 242,241,243; after the
  fix the same area averages 135,136,144, i.e. under the 45% scrim).
- Reproduced for menus by the same declaration: on `admin/Alunos` the bar (130 x 36 at the row's right
  edge) and the open `#alunos-actions-menu` (328 x 140, `z-index: 1000`) overlap; with the bar at 1200
  the menu's lower items are under it. UI-B47 fixed only the Requisições menu locally (`#req-actions-menu
  { z-index: 1201; }`) and hid the bar for its two new dialogs; its §15 records the shared rule as this
  separate item.
- The bar's position is set by page JavaScript from the hovered/selected row; it is `position: fixed`
  and appended to `body`. The defect is purely its layer, not its geometry or its show/hide lifecycle.

## 3. Target design

- One declaration at the shared owner: the bar paints at `z-index: 20`, above the sticky table header
  (5) and below the navigation backdrop (29), the navigation (30), the modal overlay/dialog (40) and
  every popover (1000).
- A comment in `actions-float.css` states the contract and warns against raising it again.
- No template, script, modal, popover or token file changes. UI-B47's local menu pin stays as
  defence in depth (its comment is corrected); its dialog visibility rules are untouched.

## 4. Decisions

- D1 — Owner: `static/css/components/actions-float.css`. All fourteen consumers already link it; a
  page-local correction would be the scattered patch UI-B47 §15 warns against. Rejected: raising
  `.popover` and `.modal-overlay` above 1200 (changes shared overlay owners for every surface and puts
  menus above unrelated chrome); per-page overrides (fourteen copies, future pages uncovered).
- D2 — Layer 20: above the sticky header (5), below navigation (29/30), modal (40) and popovers (1000).
  Rejected: 0/auto (could fall under sticky headers and lose the bar over rows); any value above 40
  (reintroduces the defect for modal scrims).
- D3 — No token is added: the repository has no z-index scale token, and inventing one for a single
  consumer would not remove any other literal. The comment carries the contract.
- D4 — UI-B47's `#req-actions-menu { z-index: 1201; }` stays (accepted page-local pin, now redundant
  but harmless); its comment is corrected so it no longer claims the shared bar is at 1200. Its
  `visibility:hidden` rules for the two new dialogs stay unchanged.

## 5. Phase invariants

- I1 — The bar's computed `z-index` is below every `.popover` and `.modal-overlay` on every page that
  loads the component; it remains above the sticky header.
- I2 — Hovering/selecting a row, the bar's actions, the menus' items, selection, keyboard focus and the
  server-side authorization are unchanged; the delta is CSS only.
- I3 — Closing a menu or dialog leaves the page usable and the bar can be shown and used again.
- I4 — UI-B47's dismissal flow and UI-B49's quick-action dialog behave exactly as accepted.

## 6. Scope

- Allowed paths: `static/css/components/actions-float.css`, the UI-B47 comment in
  `templates/admin_requisicoes.html`, `tests/test_ui_b48_overlay_layering.py` (new), this SPEC,
  `docs/backlog/UI_ACCEPTANCE_BACKLOG.md` (UI-B48 row), `PROJECT_STATE.md`.
- Protected: every route, handler, template behaviour, JavaScript, modal/popover CSS, Design System
  tokens, permissions, data, deployment and the scheduled backup.
- Out of scope: unrelated redesigns, the `.toolbar-actions-menu` `[hidden]` residual (UI-B47 §15), the
  `admin_banco_dados` folder modal (its own z 1200, no shared bar), any production action.

## 7. Data & schema

None. No database, fixture, route or stored value changes.

## 8. Security & RBAC

None. No route, form, CSRF, session or permission changes; every action keeps its server-side guard.
The bar's buttons remain the same elements with the same handlers.

## 9. Compatibility / rollout

CSS-only, served by the existing static route. No cache-busting change is required: the file is not
version-pinned in the templates (the shared CSS query versions cover other files), and a reload picks
it up. Development branch commit and push only; PRODUCTION HOLD; no deployment.

## 10. External boundaries / environment permissions

None beyond the local isolated runtime and the real Chromium harness already used by the UI-B47/B49
evidence. No provider, credential, production data or scheduled task is touched.

## 11. Evidence plan

- T0: `git diff --check`; the delta is the component, one comment and the test; HEAD/status recorded.
- T1 (RED -> GREEN): the browser reproduction above. RED on `a97b883`: during `#access-modal` the bar
  is topmost at its centre (`hitIsBar` true, bar 1200 > overlay 40); GREEN after the change
  (`hitIsBar` false, `hitIsOverlay` true, bar 20 < overlay 40). Menu case: RED by the same declaration;
  GREEN on `admin/Alunos` at 1440 and 390 (menu 1000 > bar 20, overlap true, hit inside the menu).
- T2: the new test's static contract (bar below both shared overlay owners; every bar template links
  the owner; no page-local bar z-index).
- T3: the existing UI-B47 and UI-B49 browser tests (the two accepted neighbours of the bar), plus the
  Requisições floating-bar first-paint guard and the admin activities row-action-bar guard.
- T4: the Design System CSS/token guards that read the component (UI-B09, UI-B11, DS pill radius,
  requisicoes first paint) stay green; no token changed.
- E-UI: real Chromium at 1440 x 900 and 390 x 844, dialog and menu, screenshots outside the repository
  (`D:\SGAA_tmp\ui_b48`), including the before/after dialog pair.
- T5: not triggered. TEP §5.1 A-F do not apply: this is a presentation-only delta in one domain
  (CSS), bounded by the UI rendering guards above; §5.2 also names a small UI correction. No full suite.

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | Shared layer correction | `static/css/components/actions-float.css`, UI-B47 comment | T1 browser RED -> GREEN | DONE |
| 2 | Contract test and inventory guard | `tests/test_ui_b48_overlay_layering.py` | T1/T2 green; collection reconciled | DONE |
| 3 | Documentation and acceptance package | this SPEC, backlog row, `PROJECT_STATE.md` | evidence and screenshots | DONE |

## 13. Acceptance criteria

- AC1 — An open menu on a bar page is fully visible above the bar at 1440 and 390
  (`test_an_open_menu_paints_above_the_floating_bar`).
- AC2 — A modal backdrop and its dialog are not obstructed by the bar at 1440 and 390; the dialog is
  the topmost element at the bar's former position (`test_a_modal_backdrop_and_dialog_cover_the_bar`).
- AC3 — Closing the menu/dialog restores normal behaviour: the bar can be shown again and its buttons
  are the hit target (the closing steps of `test_a_modal_backdrop_and_dialog_cover_the_bar` and
  `test_an_open_menu_paints_above_the_floating_bar`).
- AC4 — The shared contract and the fourteen-page inventory are guarded
  (`test_the_bar_paints_below_the_shared_overlay_owners`,
  `test_every_floating_bar_page_links_the_shared_owner`).
- AC5 — UI-B47/B49 browser lanes and the existing bar/DS guards pass unchanged; the delta is CSS and
  one comment (`git diff --name-only`).
- AC6 — No route, template behaviour, schema, data, permission or deployment change.

## 14. Phase-specific hard stops

Any need to change a route, handler, template behaviour, JavaScript, modal/popover owner, Design System
token, data, permission, scheduled task or production resource; any browser evidence showing a
regression in selection, keyboard focus or the accepted UI-B47/B49 flows.

## 15. Deferred / known non-blockers

- UI-B47 §15's `.toolbar-actions-menu` `[hidden]` residual (items hidden by script still drawn disabled
  in some profiles) remains a separate product decision; this change does not touch it.
- `admin_banco_dados`' folder modal keeps its own `z-index: 1200`; that page does not use the shared
  bar, so it is outside this defect. If it ever adopts the bar, the modal is already above it.
- Log rotation/size and other UI-B48-unrelated items are out of scope.

## 16. Amendments

None.

## 17. Closure

Implemented 2026-11-21 on the development branch, not deployed; landed as `39e93dd`. Evidence is
recorded in §11 and in the final report; visual acceptance is the owner's.

- AC1/AC2/AC3 met — E-UI real Chromium at 1440 x 900 and 390 x 844: the Alunos menu overlaps the bar
  and is the hit target; the Acesso edit dialog covers the bar (bar 20, overlay 40; the bar's centre
  hits the dialog, not the bar); closing each restores the bar. Screenshots in
  `D:\SGAA_tmp\ui_b48\evidence` (`ui-b48-modal-1440/390`, `ui-b48-menu-1440/390`); the before/after
  pair is `D:\SGAA_tmp\ui_b48\before` and `after`.
- AC4 met — the static contract and the fourteen-page inventory guards pass; the computed-layer audit
  of all twelve admin pages and both student pages shows bar 20, popovers 1000 (Requisições' local
  menu pin 1201) and dialogs 40.
- AC5 met — `tests/test_ui_b48_overlay_layering.py` 6 passed; RED on the old layer 5 failed / 1
  passed (the inventory guard does not depend on the layer); the UI-B47 and UI-B49 browser lanes,
  Requisições first paint, the admin activities bar and the UI-B09/UI-B11/DS guards: 136 passed.
- AC6 met — the delta is `static/css/components/actions-float.css` (one declaration and its comment),
  one corrected comment in `templates/admin_requisicoes.html`, the new test, this SPEC and the
  documentation rows; no route, handler, schema, data, permission or deployment change.
- T5 not triggered (TEP §5.1 letters A-F absent; §5.2 names a small UI correction).
