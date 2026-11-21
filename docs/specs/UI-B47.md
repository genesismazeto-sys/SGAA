# SPEC UI-B47 — Manual dismissal of the pending-email flag

Status: CLOSED 2026-11-21 (frozen the same day)
Charter: "Allow an administrator to manually clear the pending-email indicator on a request through
the existing Ações menu in Admin → Requisições." Starting HEAD `701e308`; synthetic data only; commit
and push to the development branch; PRODUCTION HOLD (no deployment). Source: backlog row UI-B47.
Risk tier: R2 (one new route and its RBAC mapping; a compare-and-set write with a concurrency claim).

## 1. Outcome

- With every selected request flagged (its current decision awaits e-mail), the Ações menu offers
  **Desmarcar sinalização de e-mail**; after a confirmation the flag disappears and stays gone.
- Nothing is sent, the decision and status do not change, no delivery is recorded, and every
  dispatch attempt and generation row is kept.
- A later decision on the same request raises its own flag, and Enviar e-mail works as before.
- A view-only administrator never sees the action and the server refuses it.

## 2. Current facts

- The flag is the request's current *pending generation*: one `requisicao_email_eventos` row with
  `estado='pending'`; the partial unique index `ux_req_email_eventos_pendente` allows at most one per
  request (`app/prod1_notifications_ddl.py`, `app/pg_schema.py`). The list renders the icon from
  `pending_request_ids` and its red variant from `failed_request_ids`
  (`app/views/admin/requisicoes.py::admin_requisicoes`, `templates/admin_requisicoes.html`).
- `estado` admits `pending`, `sent`, `superseded` (CHECK on both engines). `superseded` already means
  "closed without delivery" for three causes: a new decision, a reopen/close
  (`supersede_pending_event`) and the automatic Devolvida → Indeferida expiry. No product screen reads
  the generation history; only the dispatch reads pending rows and `email_envios`.
- Only `record_final_decision_event` creates a generation; it supersedes the pending one and inserts
  a new `pending` row, so a later decision always raises a new flag.
- Enviar e-mail (`admin_requisicoes_email_preview` / `_enviar`, requirement `requisicoes`/`edit`) is
  offered only when every selected row is flagged (`selectionAllEmailPending`), and the server refuses
  a selection with an unflagged request (409). The dispatch reads its plan without locks, links the
  still-pending generations to the attempt, and marks only still-pending generations sent.
- RBAC is resolved by endpoint in `app/auth.py::get_admin_permission_requirement`; no prefix rule
  covers `admin_requisicoes*`. CSRF is the global `CSRFProtect`; the page's fetches send `X-CSRFToken`.

## 3. Target design

- **Owner `app/request_email_notifications.py`.**
  - `pending_event_ids(conn, requisicao_ids=None) -> dict[int, int]`: request id → its current
    pending generation id. `pending_request_ids` becomes the key set of it (one query owner).
  - `dismiss_pending_events(conn, generations)`: `generations` maps request id → the generation id
    the administrator saw. In one `write_transaction`, one statement moves exactly those generations
    from `pending` to `superseded` (`superseded_em` now) and returns them; unless every pair came back,
    `EmailFlagDismissalStale` names the requests that moved and the transaction rolls back. Nothing
    else is written: no `email_envios` row, no `email_envio_id` change, no request column.
- **Route** `POST /admin/requisicoes/email/desmarcar`, endpoint `admin_requisicoes_email_desmarcar`
  (`LegacyRouteSpec`, same module). Body `{"sinalizacoes": [{"requisicao_id", "evento_id"}, …]}`,
  1–500 entries of positive integers with distinct requests; anything else is 400
  (`motivo: "selecao_invalida"`). Stale is 409 (`motivo: "desatualizada"`, `desatualizadas`).
  Success flashes the outcome, logs `event=request_email_flag_dismissed` with ids only, and answers
  `{"ok": true, "desmarcadas": n}`. The JSON carries no user text; the page owns its messages.
- **Page.** Each flagged row carries `data-email-event-id`. The Ações menu gains the item after
  Enviar e-mail, shown only when the user may edit and every selected row is flagged (with a count
  for a multi-selection, as Enviar e-mail). It opens a DS modal (`components/modal.css`; Cancelar, then
  the primary Desmarcar on the right) that states what changes and what does not; a refusal shows in
  the e-mail flow's red alert box; success reloads the page, where the shared flash confirms it.

## 4. Decisions

- D1 — Dismissal closes the generation as `superseded`; schema v19 is unchanged. Rejected: a
  `dismissed` state or provenance columns (a v20 production migration, the charter's stop boundary,
  for a distinction no reader uses). Provenance is the log line (administrator, requests,
  generations).
- D2 — Compare-and-set on the generation the page showed, not on the request: a page loaded before a
  new decision can never clear that decision's flag, and a generation already sent stays sent.
- D3 — A multi-selection follows Enviar e-mail's contract (every row flagged, otherwise not offered)
  and is all-or-nothing. One `UPDATE … WHERE id IN (…)` has the statement shape of the dispatch's own
  link update, so both take row locks in the same order on PostgreSQL.
- D4 — Offered from the Ações menu only, and hidden (not disabled) when not applicable, like Editar.
  The floating row bar keeps its approved icon set.
- D5 — Requirement `requisicoes`/`edit`, the same as Enviar e-mail; the item follows
  `canRequisicoesEdit`.
- D6 — An e-mail already being dispatched is not interlocked (pre-existing dispatch design, which the
  charter keeps): §15.

Open decisions (product or architecture): none.

## 5. Phase invariants

- No schema, migration or data-repair change; `email_envios` is never written by a dismissal.
- The request row (status, decision, hours, observation, dates, notification stamps) is unchanged.
- Enviar e-mail, its preview, the floating bar, the processing flow and every other Ações item keep
  their behaviour.

## 6. Scope

- Allowed paths: `app/request_email_notifications.py`, `app/views/admin/requisicoes.py`,
  `app/auth.py` (one mapping), `templates/admin_requisicoes.html`, new tests
  `tests/test_request_email_flag_dismissal*.py`, the guard data the new route and messages make false
  (`tests/_artifacts/route_inventory_baseline.json`, `tests/canonical_baseline_support.py`,
  `tests/canonical_rbac_test_support.py`, `tests/test_ut_br2abc_canonical_baseline_governance.py`,
  `tests/test_phase4_requisicoes_blueprint.py`, others only where the same change falsifies them),
  `docs/backlog/UI_ACCEPTANCE_BACKLOG.md` (UI-B47 row), `docs/specs/README.md`, `PROJECT_STATE.md`,
  this SPEC.
- Protected: everything else, notably `app/request_email_dispatch.py`, the schema owners, `app/db.py`,
  `main.py`, `tests/conftest.py`, `pytest.ini`, shared CSS components.
- Planned local refactors: `pending_request_ids` over `pending_event_ids` (§3).
- Out of scope: the floating bar, e-mail history screens, dispatch interlocking, TECH-CLEANUP-01.

## 7. Data & schema

No schema version change; SQLite/PostgreSQL parity is the existing table; Path-B and Layer-2 copy the
table unchanged. Tests use synthetic, disposable databases only.

## 8. Security & RBAC

One new mutating admin route: requirement (`requisicoes`, `edit`), CSRF by the global protection,
fail-closed parsing (400), stale refusal (409), no user text or personal data in the JSON or the log.

## 9. Compatibility / rollout

Code only; reaches production only through a later GF1. Rollback: revert the slice commit (dismissed
generations stay `superseded`, a valid state for the previous code).

## 10. External boundaries / environment permissions

Local SQLite test databases; local PostgreSQL 15 (`127.0.0.1:54315`) and 17 (`127.0.0.1:54317`) with
run-owned databases; local Chromium against a live local server. No provider, no DEV or PROD access.
PROD user gates: none.

## 11. Evidence plan

- T1 owner and route contracts (`tests/test_request_email_flag_dismissal.py`): clears only the named
  generation; request and `email_envios` untouched; a failed attempt's link kept; stale (new decision,
  sent, mismatched pair) and a partly stale batch change nothing; a new decision raises a new flag and
  is sendable; 400 shapes; 403 for a view-only administrator; CSRF refusal; nothing sent.
- E-PG1 / E-PG2 (`tests/test_request_email_flag_dismissal_real_pg.py`, PostgreSQL 15 and 17):
  dismissal ↔ concurrent decision in both orders (the waiter sees the committed state; no flag lost,
  no unique violation, no newer flag cleared).
- E-UI (`tests/test_request_email_flag_dismissal_browser.py`, real Chromium, live server): the six
  acceptance scenarios at 1440 × 900 and 390 × 844; screenshots outside the repository with Inter
  loaded.
- T2: the request e-mail suites and the processing-correction suite. T4: route inventory, RBAC
  coverage, actor matrix, RBAC boundary, canonical baseline and message catalogue, CSRF inventory,
  requisições blueprint, DS button contract, popover reachability, mail service boundary.
- Full suite: none expected (no TEP §5.1 trigger: one domain, no wide primitive, no schema, no test
  infrastructure change).
- Review: R2 independent fresh-context review before landing; targeted recheck after fixes.

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | Dismissal owner, route, Ações item and modal, guards, closure | §6 | §11 | DONE |

## 13. Acceptance criteria

- AC1 — A flagged selection offers the action; an unflagged one does not → E-UI, T1.
- AC2 — Dismissal removes the flag, and it stays removed after a reload → E-UI, T1.
- AC3 — No e-mail, no request change, no delivery record, history kept → T1.
- AC4 — `requisicoes`/`edit` on both sides; CSRF; fail-closed input → T1, T4.
- AC5 — Stale or concurrent changes never clear a newer flag and leave a refused batch untouched →
  T1, E-PG2, E-UI.
- AC6 — A new decision raises a new flag; Enviar e-mail unchanged → T1, T2, E-UI.
- AC7 — Desktop and mobile evidence → E-UI.
- AC8 — `docs/ENGINEERING_STANDARDS.md` self-audit (§13) passes.

## 14. Phase-specific hard stops

- A design that needs a new `estado`, column or any schema change (production migration): stop.

## 15. Deferred / known non-blockers

- PRE_EXISTING — the floating row bar (`#pedido-actions-float`, z-index 1200,
  `components/actions-float.css`) stacks above every `.popover` (1000) and `.modal-overlay` (40):
  it covers the lower items of an open menu and stays bright over a dialog's scrim (on Requisições
  over Enviar e-mail, the presets and the request dialog too). A1 handles only what this item needs.
  One shared stacking rule in the component, for every list page that uses the bar, with their
  recapture, is a separate change.
- PRE_EXISTING — in `.toolbar-actions-menu` the item rule (`display:flex`) outranks `[hidden]`, so
  items a script hides are drawn disabled (Editar on a decided request; for a profile that may not
  edit, the menu's other items). A1 scopes the fix to the new item; whether the others should
  disappear is a product decision.
- PRE_EXISTING (D6) — the dispatch reads its plan without locks and ignores the link update's
  count: a dismissal (or reopen) committed after the plan does not stop that e-mail, and one that
  lands between the link and the confirmation leaves a delivered generation `superseded`;
  `email_envios` stays the delivery record and the generation keeps its attempt link.
- Provenance of a dismissal is the application log only; a durable record (a state or columns)
  would be a schema v20 change.

## 16. Amendments

- A1 2026-11-21 — Page-local corrections in `templates/admin_requisicoes.html`, after the evidence
  renders and the R2 review: the open Ações menu sits above the selected row's floating bar, which
  covered its lower items, the new one included; `#req-action-email-dismiss[hidden]` is not drawn
  (the menu's item rule outranks `[hidden]`, so D4's "hidden" needed it, also for a view-only
  profile); while the new confirmation is open the bar is hidden and out of the tab order; the menu
  syncs its items before it is measured and clamped, since an item revealed after the measure
  wrapped its label on a phone. The other dialogs and items keep their behaviour (§5, §15).
  Material: no.
- A2 2026-11-21 — D3's lock-order statement corrected (R2 review): the lock order of an `IN` list
  follows the plan, so a dismissal and a dispatch locking several of the same student's generations
  in opposite orders can deadlock; PostgreSQL aborts one side and neither is half-applied. The
  processing handler (request row, then one generation) cannot deadlock with a dismissal. Ids above
  the signed 64-bit range are refused as invalid input (400) instead of failing to bind.
  Material: no.

## 17. Closure

Closed 2026-11-21; this closure lands with slice 1. Evidence outside the repository:
`D:\SGAA_tmp\ui_b47` (EVIDENCE.md, contact sheets, screenshots, logs, mutation probes).

- AC1 met — E-UI: an unflagged selection does not draw the item, a flagged one offers it
  uncovered, a view-only profile never sees it; T1.
- AC2 met — E-UI: the flag is gone after the confirmation and after a reload, desktop and phone; T1.
- AC3 met — T1: request row, `email_envios` and the attempt link unchanged; nothing sent.
- AC4 met — T1 (403 to the page's fetch for a view-only profile, redirect otherwise; CSRF refusal
  with a positive control; 400 for every ambiguous or out-of-range selection), T4 guards.
- AC5 met — T1 (moved, sent, reopened, mismatched and partly stale selections change nothing),
  E-PG2 on PostgreSQL 15 and 17 in both orders, E-UI (a stale page is refused, the newer flag kept).
- AC6 met — T1 (the new flag is sendable), the e-mail suites, E-UI (the re-raised flag is offered;
  Enviar e-mail sends through the fake transport and clears its flag).
- AC7 met — E-UI at 1440 × 900 and 390 × 844 with Inter loaded.
- AC8 met — self-audit in the phase report, no exception.

Runs: T1 29; impact set 1056 passed, 38 opt-in skips, one class-B ledger pin updated (its file
rerun); template and DS guards 403, then 261 and 207 on the final bytes; popover contract 5;
E-PG 3 + 3; E-UI 1; ten mutants killed. Full suite not triggered (no TEP §5.1 trigger). R2: a
fresh-context review (same model family) found two MATERIAL template defects (the item drawn when
it must be hidden; the bar rule reaching every dialog), fixed by A1; its non-material findings are
A2 and §15. The targeted recheck passed all five items with no new MATERIAL finding; its remaining
notes (a non-vacuous view-only check, the menu measuring order) are applied. Owner visual
acceptance pending (backlog UI-B47).
