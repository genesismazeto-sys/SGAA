# SPEC DS-CONSISTENCY-01 — One section card and one button contract

Status: FROZEN 2026-11-21
Charter: the owner approved the DS consolidation proposal on 2026-11-21 ("Aprovar e aplicar tudo"),
including the defaults it put to him (four buttons in two rows of two; one order for the request decision
buttons; header and in-row buttons unchanged). Publication: push to `backlog/ds-consistency-01`;
integration into the development branch only after owner acceptance. No deployment.
Risk tier: R1 (presentation only: no schema, route, RBAC, CSRF, provider or concurrency change)

## 1. Outcome

- Every section panel uses one shared section card (header with title and chips, body, footer with the note
  on the left and the buttons on the right), at every width.
- Every action group follows one written button contract on the desktop and on the phone (below 768 px),
  with no empty space beside buttons on the phone.
- The primary action is always the rightmost button and always blue.
- Status pills carry only statuses; labels, levels and counts are chips.
- A guard fails when a screen breaks any of the above again.

## 2. Current facts

- The section card is page-local CSS copied into three templates: `templates/admin_configuracoes.html`
  (the owner's reference, "Prazo de adequação"), `templates/aluno_reportar.html`,
  `templates/aluno_progresso.html`. Below 640 px its footer stacks and left-aligns the buttons.
- `static/css/components/modal.css` gives `.modal-footer` no alignment; ten templates, `request-presets.css`
  and `modern-style.css` (`.rejection-decision`) override it (center, right or space-between).
- `templates/admin_atividades.html` (Grupos), `templates/admin_requisicoes.html` (e-mail confirm) and
  `templates/admin_catalogo_base_form.html` use `btn btn-primary`, a class the DS does not define: white.
- Inverted order (primary left of Cancelar/Voltar): `admin_importar_atividades` (page and modal),
  `admin_turmas` (import modal), `admin_importar_requisicoes`, `admin_processar_requisicao`.
- The decision buttons are ordered Indeferir, Deferir Parcialmente, Deferir in the Requisições modal and
  the reverse on `admin_processar_requisicao`.
- The versioned-activity diagnostic view (`admin_diagnostico_atividades_versionadas_view.html`) uses
  `.diag-card` boxes, left-aligned buttons and status pills for "Admin-only" / "Leitura paralela".
- `admin_acesso.html` draws permission levels (Total, Edição, Leitura, Nenhum) and e-mail send counts
  (Enviados, Falhas, Indeterminados) as status pills.
- `admin_importar_requisicoes.html` renders the browser's native file input and checkbox.
- The Alunos list header "Solicitações pendentes" (130 px of text) sits in a 120 px column and is clipped.
- Measured inventory (candidate `83c378b`, synthetic data, scrollbars visible, 1440 and 390 px): 1370 action
  groups, 99 outside the contract, grouped B1–B9 in the owner proposal (artifact `EjgjVS7k3jJp3ScUM5U8R9`;
  scratch `D:\SGAA_tmp\ds_audit`).

## 3. Target design

- **Section card owner** — `static/css/components/section-card.css`: `.cfg-card`, `.cfg-card-head`,
  `.cfg-section-label`, `.cfg-chips`, `.cfg-chip` (`.is-active`), `.cfg-card-body`, `.cfg-card-footer`,
  `.cfg-footer-note`, `.cfg-footer-actions`. Loaded for every shell by `design_system_css`. Page templates keep
  only their field layouts. Multi-line notes are justified with the last line at the start.
- **Button contract owner** — `static/css/components/actions.css`: `.btn-row` (right-aligned group),
  `.btn-row--center` (data-entry forms), `.btn-row--pairs` (four buttons, two rows of two). Below 768 px a
  `.btn-row` fills its line: every visible button grows from a zero basis and keeps its label width as
  minimum; rows wrap in reverse, so when the buttons do not fit the last (primary) one goes on top with the
  full width and the others share the line below. `.btn-row--pairs` is a two-column grid on the phone.
- `.modal-footer` is right-aligned by `modal.css`; page-local footer alignment overrides are removed.
- The list toolbar on the phone: search on its own line; sort and filter share the next line; the action
  buttons follow the `.btn-row` rule.
- The primary action is `btn primary`; order is secondary(ies) then primary.
- Decision buttons everywhere: Indeferir, Deferir Parcialmente, Deferir.
- The diagnostic view becomes section cards (Consulta / Resumo / one card per axis) with chips in the header
  and its buttons in the Consulta footer.

## 4. Decisions

- D1 — Keep the `cfg-*` class names and move them to a component, instead of renaming to new classes ·
  rename rejected: churn across templates and tests with no user-visible gain.
- D2 — Count-free phone layout (flex, zero basis, reverse wrap) · per-count CSS (`:nth-child`) rejected:
  hidden buttons (`[hidden]`, mode toggles) would be counted.
- D3 — Four buttons use the explicit `.btn-row--pairs` grid (owner default: two rows of two, primary bottom right).
- D4 — Header back buttons and in-row buttons (Baixar, Retificar, Adicionar comprovante, Nova versão,
  Criar versão, Nova requisição on the student dashboard, Conectar Microsoft) are outside the contract
  (owner default B8).
- D5 — Data-entry form actions stay centered on the desktop; on the phone they follow the `.btn-row` rule.
- D6 — Chips for non-status labels reuse `.cfg-chip`; status pills stay `.badge.status-pill`.

Open decisions: none.

## 5. Phase invariants

- No change to routes, view functions, RBAC, CSRF, form field names, element ids used by scripts, or data.
- Every behaviour the pages had (opening modals, submitting, the decision flow) is unchanged; only placement,
  order, colour class and chip/pill presentation change.
- Personal data never enters fixtures or evidence (synthetic `@example.com` data only).

## 6. Scope

- Allowed: `static/css/**`, `templates/**`, the inline scripts that build the Acesso pills, `tests/**`,
  `docs/design-system/README.md`, `docs/specs/**`, `PROJECT_STATE.md`.
- Protected: `app/**` Python behaviour, schema owners, `tools/**`, deployment configuration.
- Out of scope: visual baselines (stale since 2026-08-14, owner decision), the toolbar on the desktop,
  native date inputs, the remaining page-local `<style>` blocks not touched by these rules.

## 7. Data & schema

No schema change; no data touched.

## 8. Security & RBAC

No route, permission or CSRF change. Templates keep their existing forms and tokens.

## 9. Compatibility / rollout

Presentation only. Rollback is reverting the branch before integration; after integration a forward fix.

## 10. External boundaries / environment permissions

Local only: the synthetic-data harness and the test suite. PROD: none. DEV providers: none.

## 11. Evidence plan

- T1/T2: new guard tests — static (no `btn-primary`; no page-local `.modal-footer` alignment; the section
  card defined only in its component; decision-button order) and a browser contract over every page and
  modal at 1440 and 390 px (alignment by context, primary rightmost and blue, phone rows without holes,
  with the approved exceptions of D4).
- T3: the existing UI guard tests that pin the changed structures (`test_ui_corrections_batch2/3`,
  `test_operacoes_backup_action_footer_ui_b07`, `test_cloud_provider_card_symmetry_ui_b07`,
  `test_ui_panel_footers_and_controls_ui_b16_b19`, `test_admin_access_repair_contract`,
  `test_access_email_batch`, `test_console_form_semantics_ui_b15`, `test_request_rectification_flow`,
  the `form-actions` tests, DS ratchets) — updated where this SPEC's contract change falsifies them, with
  negative controls.
- E-UI: the audit re-run with 0 violations outside D4, and prints at 1440 / 390 of every changed screen.
- Full suite: TEP §5.1 C (served delta across many templates) — one T5 at close.

## 12. Slices

| # | Goal | Paths | Exit evidence | Status |
|---|---|---|---|---|
| 1 | Components (section card, button row, modal footer) + white primaries + README contract | css components, 3 card templates, modal templates | static guards, T3 | landed with 2–3 (A7) |
| 2 | Action groups on every screen (forms, cards, modals, order, decisions, toolbar) | templates, list toolbar CSS | browser contract, T3 | landed (A7) |
| 3 | Diagnostic view, Banco de dados cards and provider buttons, Acesso chips, Alunos header, Importar requisições file field | those templates | browser contract, T3 | landed (A7) |
| 4 | Close: audit 0, prints, T5, SPEC closure | docs, PROJECT_STATE | T5 | |

## 13. Acceptance criteria

- AC1 — Audit over every page and modal at 1440 / 390: 0 action groups outside the contract except D4.
- AC2 — No `btn-primary`; every primary action blue and rightmost.
- AC3 — The section card is defined once; every card footer keeps its buttons on the right at every width.
- AC4 — No status pill with a non-status text on the changed screens.
- AC5 — Guards fail on a reintroduced defect (negative controls recorded).
- AC6 — `docs/ENGINEERING_STANDARDS.md` self-audit (§13) passes.

## 14. Phase-specific hard stops

None beyond `docs/OPERATING_MODEL.md` §7.

## 15. Deferred / known non-blockers

## 16. Amendments

- A1 2026-11-21 — On the request processing page the decision buttons are centered with the page's form
  actions (Voltar / Salvar), not right-aligned: that page is a data-entry form (D5). The modal keeps them on the
  right. One order in both places, as decided. Not material (placement inside an approved rule).
- A2 2026-11-21 — The report detail modal keeps Excluir apart on the left; its Fechar / Salvar group is the
  `.btn-row`. A destructive action beside the primary was not part of the approved proposal. Not material.
- A3 2026-11-21 — Configurações, "Tempo de processamento padrão": with Resetar contagem moved beside Salvar, the
  footer note names it ("Resetar contagem reinicia a apuração…"). Copy only. Not material.
- A4 2026-11-21 — Importar requisições rebuilt on the form-row pattern: labels "Arquivo padrão" / "Arquivo
  Excel" and a note on the required tab replace the long inline sentence. Field names unchanged. Not material.
- A5 2026-11-21 — The Acesso e-mail counts become neutral chips: the colour tone they took from their value
  (green sent, red failures) goes with the pill; "Em andamento" / "Concluído" stays the status pill.
  Follows D6. Not material.
- A6 2026-11-21 — The list toolbar implements the phone rules in `modern-style.css`, its owner, with the
  specificity of its existing toolbar rules (a `.btn-row` class there would lose to them). Four actions use
  `.actions--pairs`. Not material.
- A7 2026-11-21 — Slices 1–3 land as one commit: the components, the screens and the guards change the same
  templates and tests, and no intermediate state passes the browser contract on its own. Not material.

## 17. Closure
