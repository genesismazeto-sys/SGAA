# SPEC UI-B49 — Quick actions on the pending-email icon

Status: CLOSED 2026-11-21; in PROD since GF1-2 (`227ec51`); owner visual acceptance pending
Charter: "In Admin → Requisições, make the pending-email icon directly actionable" — a compact DS
dialog with exactly Cancelar, Desmarcar and Enviar. Starting HEAD `8e5a29c`; synthetic data only;
commit and push to the development branch; PRODUCTION HOLD (superseded by GF1-2, §17).
Owner note: a dialog box centres its buttons; deliver two screenshots (desktop, phone).
Risk tier: R1 (presentation and client script over existing routes; no route, RBAC, schema or
concurrency change).

## 1. Outcome

- An administrator who may edit Requisições clicks the blue (pending) or red (last attempt failed)
  icon of a row and gets a compact dialog for that request: Cancelar, Desmarcar, Enviar.
- Desmarcar withdraws that request's current flag through the UI-B47 operation, with no second
  confirmation; a stale page is refused and nothing changes.
- Enviar opens the existing preview; only its own explicit Enviar sends.
- A read-only profile sees the same icon as a status indicator only. The Ações menu, its UI-B47
  confirmation, the selection and the floating bar behave as before.

## 2. Current facts

- The icon is `<i class="lucide req-email-pending" role="img">` in the reserved `.req-email-cell`
  (`templates/admin_requisicoes.html`, `email_cell`); the row carries `data-req-id`,
  `data-req-aluno`, `data-email-pending` and, since UI-B47, `data-email-event-id`. Measured on
  `8e5a29c`: the 14 × 14 icon sits 7 px from each side of its cell and 9 px from the row's top and
  bottom at 1440 and 390 (`D:\SGAA_tmp\ui_b49\logs\geometry_before.txt`).
- Dismissal: `POST admin_requisicoes_email_desmarcar` with `{requisicao_id, evento_id}` pairs
  (requisicoes/edit, compare-and-set on the generation, 409 when stale). Its client call lives inside
  the UI-B47 confirmation block.
- Sending: `window.openRequisicoesEmailConfirm(ids)` opens the preview dialog; its Enviar posts to
  `admin_requisicoes_email_enviar`.
- Row selection ignores clicks on `a, button, input, label, select, textarea`
  (`static/js/toolbar-filters.js::isInteractiveTarget`); rows have no key handler of their own.
- Button placement: `.btn-row--center` exists (`components/actions.css`), but `components/modal.css`
  loads later and its `.modal-footer{justify-content:flex-end}` wins, so no modal footer can centre
  today. The DS button guard already checks a `--center` row is centred.
- Modal focus pattern (`static/js/rejection-decision.js`): remember the opener, focus a button on
  open, Escape and the scrim close, focus returns to the opener.

## 3. Target design

- **Icon.** With `can_requisicoes_edit`, the icon is wrapped in `<button type="button"
  class="req-email-flag" data-email-quick aria-haspopup="dialog">` carrying the existing status
  label as its name and tooltip; the inner icon is `aria-hidden`. The button adds no box (no padding,
  border or background), so the icon keeps its measured position; a transparent `::before` widens the
  touch target; `:focus-visible` uses the DS ring. Without the permission the markup is unchanged.
- **Dialog** `#req-email-quick-modal` (`components/modal.css`): title with the status label of the
  clicked icon (pending or failed), one line naming the request and the student, the e-mail flow's red
  box for refusals, and `.modal-footer.btn-row.btn-row--center`: Cancelar, Desmarcar, Enviar
  (primary, rightmost).
- **Behaviour.** The button handles its own click and stops it there, so the selection and the
  floating bar are untouched; it reads only its own row. Desmarcar posts that one pair through the
  shared client call and reloads on success (the flash confirms); stale shows the UI-B47 stale message
  and disables Desmarcar; a failure shows the generic message. Enviar closes the dialog and calls
  `openRequisicoesEmailConfirm([id])`. Focus: Enviar on open; Cancelar, ×, Escape and the scrim close
  and return focus to the icon. While the dialog is open the floating bar is hidden, extending UI-B47's
  page-local rule to this dialog only.
- **One client owner for dismissal.** The UI-B47 confirmation and the new dialog call one page
  function that posts the pairs and returns `ok | stale | error`; the row-to-pair reading is one
  helper used by the Ações item and the icon. Behaviour of the UI-B47 path is unchanged.
- **Centred modal footer.** `components/actions.css` (placement owner) gains
  `.modal-footer.btn-row--center{justify-content:center}`, opt-in; DS README §3.1 records the owner's
  rule for a compact choice dialog. `static_asset_version` is bumped.

## 4. Decisions

- D1 — Reuse the UI-B47 route and the existing preview; no endpoint, no server change.
- D2 — The quick dialog is itself the confirmation for Desmarcar (charter).
- D3 — Centred buttons only where a row opts in; every other modal stays right-aligned (DS §3.1).
  Whether the UI-B47 confirmation should also centre is left to the owner (not reopened).
- D4 — Read-only profiles keep the `role="img"` indicator: no button, no handler.

Open decisions (product or architecture): none.

## 5. Phase invariants

- No route, RBAC, CSRF, schema, data or dispatch change; the Ações menu, the UI-B47 confirmation,
  the preview, the selection and the floating bar keep their behaviour.
- The icon's position and size are unchanged at 1440 and 390.

## 6. Scope

- Allowed: `templates/admin_requisicoes.html`, `static/css/components/actions.css` (one opt-in rule),
  `templates/base.html` and `templates/base_aluno.html` (`static_asset_version`),
  `docs/design-system/README.md` §3.1, new `tests/test_request_email_quick_actions*.py`, catalogue
  guard data the new message makes false, `docs/backlog/UI_ACCEPTANCE_BACKLOG.md` (UI-B49 row),
  `docs/specs/README.md`, `PROJECT_STATE.md`, this SPEC.
- Protected: everything under `app/`, `main.py`, the other templates, `tests/conftest.py`.
- Out of scope: UI-B48 (shared overlay stacking), any change to UI-B47's contract.

## 7. Data & schema

None.

## 8. Security & RBAC

No new route. The button is rendered only for requisicoes/edit; the server keeps refusing others
(UI-B47 and REN1 contracts). CSRF, stale protection and delivery history are those of the reused
routes.

## 9. Compatibility / rollout

Code only; reaches production only through a later GF1. Rollback: revert the slice commit.

## 10. External boundaries / environment permissions

Local SQLite and Chromium only. PROD user gates: none.

## 11. Evidence plan

- T1: template contract (button only with edit permission, `role="img"` otherwise, data attributes,
  dialog markup and centred row); catalogue +1.
- E-UI (`tests/test_request_email_quick_actions_browser.py`, real Chromium, live server, 1440 × 900
  and 390 × 844): the eight acceptance items, the icon geometry against §2, focus return, keyboard
  activation, a multi-selection left intact. Two screenshots for the owner (desktop and phone dialog).
- T2/T3: the UI-B47 and request e-mail suites (the shared dismissal call), the UI-B47 browser test,
  the status-in-view browser test (icon geometry), DS button contract (browser), popover contract,
  floating-bar guards, catalogue guards.
- Mutation probes on the new behaviour. Full suite: none expected (no TEP §5.1 trigger).
- Review: R1 structured self-review.

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | Icon button, quick dialog, shared dismissal call, centred footer, guards, closure | §6 | §11 | DONE |

## 13. Acceptance criteria

- AC1 — Blue and red icons open the same three-action dialog → E-UI.
- AC2 — Cancelar changes nothing → E-UI.
- AC3 — Desmarcar clears only the clicked request's current flag, whatever is selected → E-UI, T2.
- AC4 — Enviar opens the existing preview and sends nothing by itself → E-UI.
- AC5 — A stale decision keeps its new flag → E-UI.
- AC6 — A read-only profile cannot activate anything → T1, E-UI.
- AC7 — The Ações menu and its UI-B47 path are unchanged → UI-B47 browser and contract tests.
- AC8 — `docs/ENGINEERING_STANDARDS.md` self-audit passes.

## 14. Phase-specific hard stops

- Any need for a new endpoint or server change: stop and record.

## 15. Deferred / known non-blockers

- The preview that Enviar opens does not move the focus into itself (pre-existing behaviour of the
  e-mail confirmation dialog); its buttons are reachable by Tab as before.
- Whether the UI-B47 confirmation dialog should also centre its buttons is the owner's call (D3).

## 16. Amendments

- A1 2026-11-21 — A click inside the new dialog stops at the dialog: the page clears the row
  selection on any click outside the list (`static/js/toolbar-filters.js`), so Cancelar was clearing a
  selection the icon had left intact. Only this dialog's clicks are kept; every other dialog of the
  page behaves as before. Material: no.
- A2 2026-11-21 — Owner question ("after Desmarcar the icon has to disappear, not turn red"): the
  browser test now dismisses a red icon too and asserts that no icon of any colour, nor its button or
  data, remains in that row, immediately and after a reload. Behaviour was already correct; the red
  icon in the first renders was another seeded request (the red-variant case). Material: no.

## 17. Closure

Closed 2026-11-21; this closure lands with slice 1. Evidence outside the repository: `D:\SGAA_tmp\ui_b49`
(screenshots, before/after of a red dismissal, logs, scratch probes).

- AC1 met — E-UI: blue and red icons open the same three-action dialog at 1440 and 390; centred row
  on desktop, one filled row on the phone; the icon keeps its measured position (7 / 7 / 9 / 9 px).
- AC2 met — E-UI: Cancelar, ×, Escape and the scrim change nothing; focus returns to the icon; a
  multi-selection elsewhere stays selected.
- AC3 met — E-UI: Desmarcar (also by keyboard) clears only the clicked request's flag; the row then
  shows no icon, blue or red, before and after a reload; T2 for the shared route.
- AC4 met — E-UI: Enviar opens the existing preview; nothing is sent until its own Enviar.
- AC5 met — E-UI: a stale row is refused, its newer flag kept, Desmarcar disabled.
- AC6 met — T1 (no button, `role="img"` kept), E-UI (clicking a read-only icon opens nothing).
- AC7 met — the UI-B47 browser and contract tests pass unchanged.
- AC8 met — self-audit: one client owner for the dismissal call, user text through `user_message`,
  no server change, no dead code; no exception.

Runs: T1 4; E-UI 1 (both widths, read-only profile included); regression set 502 (UI-B47 browser,
DS button contract, status-in-view geometry, e-mail suites, catalogue and route guards); popover
contract 5. Mutation probes: a client call that reports success without dismissing, and a server
that keeps the flag pending, both fail the browser test. Full suite not triggered (no TEP §5.1
trigger). Review: R1 self-review. Published by GF1-2 as part of `227ec51`; owner visual acceptance
remains pending (backlog UI-B49). SMOKE-AUTH-01 consolidated the read-only and acceptance steps.
