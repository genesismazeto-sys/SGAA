# SGAA — UI acceptance backlog

Persisted record of user-reported UI defects and pending work, so that none of
it depends on chat history or agent memory. This exists because
`docs/DOCUMENTATION_INDEX.md` ("Explicit rule") already states that chat memory
and agent handoff notes are not substitutes for repository canon.

**Opened:** 2026-09-21 · **Branch:** `refactor/design-system-foundation` ·
**HEAD at time of writing:** `ba0caae`

## Scope and rules

- This is the single backlog file for user-reported UI/acceptance items. Do not
  open a second one; add rows here.
- Only items explicitly raised by the user are recorded. No suggestions, no
  opportunistic refactors, no speculative cleanup.
- Statuses are limited to: `IN_ACCEPTANCE`, `BACKLOG`,
  `DONE_PENDING_VISUAL_CONFIRMATION`, `DONE`.
- **A passing test suite is not acceptance.** An item that changes a visible
  surface may not be marked `DONE` until the user has confirmed it visually.
  `DONE` on a non-visual item means the behavioural/contract evidence named in
  its Notes column is in the repository.

> **Landing record (2026-09-26).** The repairs referenced below were landed on
> `refactor/design-system-foundation` on top of `ba0caae` in three commits:
> the credential/access lifecycle (`feat: finalize per-account credential
> lifecycle`), the Design-System/UI repairs (`fix: consolidate design system and
> admin ui repairs`) and this record (`docs: update design system and ui
> acceptance records`). Deliberately **not** landed and left in the working tree:
> the optional-header student-import candidate (its nine paths, including one
> title line in each Turma form) and the one-off UI-B01 repair script
> `tools/repair_email_preset_cardinality.py`. Machine-local configuration
> (`.env`) is never versioned.

Acceptance runtime convention: `http://localhost:5000`. SGAA has one
application port. An isolated acceptance run swaps the **database**, never the port, and
the canonical runtime must be stopped first — `run_acceptance.bat` refuses to
start while 5000 is occupied.

---

## 1. In acceptance

| ID | Area | User-reported issue | Expected behavior / constraint | Status | Notes / acceptance evidence |
|---|---|---|---|---|---|
| UI-A01 | Atividades → Ver versão | Generic `← Voltar` rendered centred/isolated below the form | Contextual page-level back action in the header, right-aligned, reusing the activity-detail pattern; label is the real parent activity name, resolved from page data (never hardcoded); destination is the parent version-list page | DONE_PENDING_VISUAL_CONFIRMATION | `templates/admin_catalogo_versao_form.html` now uses the shared `detail_header` macro; local `.version-form-heading` copy retired; footer block is `{% if not readonly %}`. Label `base.nome_conceito`, href `admin_catalogo_versao_detalhe`. Tests: `tests/test_ui_repairs_back_action_toolbar_cards.py` (A lane). Acceptance: `/admin/atividades` → activity → Ver versão |
| UI-A02 | Reportes → toolbar | `Ações` floating in the middle of the toolbar | `Ações` grouped with `Novo reporte` inside `.actions`; toolbar back to the two children `justify-content:space-between` expects; normal shared flex only — no absolute positioning, spacers, offsets or magic pixels | DONE_PENDING_VISUAL_CONFIRMATION | Cause: commit `a8382dd` appended `Novo reporte` *after* `</div>` of `.actions`, creating a third flex child. Fix is markup-only in `templates/admin_reportes.html`; no CSS changed. Tests: same file (B lane), incl. narrow-width wrap contract. Acceptance: `/admin/reportes` |
| UI-B10 | Design System / shared form controls / Ver versão | Non-editable fields on "Ver versão" rendered substantially darker than the read-only fields normalized in Requisições / Ver Aluno | One authoritative DS colour contract for equivalent read-only fields; reconcile the Design System rather than override the page; no raw colour, no page-local gray, no duplicated token, no local opacity hack | DONE_PENDING_VISUAL_CONFIRMATION | **Confirmed cause** (the recorded lead was right and was the whole cause): `disabled` on a `<fieldset>` is *inherited*, so every control matched `:disabled` while carrying no `aria-readonly` of its own — the UI-H03 rule keys on the control, so it matched nothing and all eight fields fell to the "not applicable" paint. **Fix:** shared `components/form.css` gains a READ-ONLY REGION contract keyed on the pairing `fieldset[disabled][aria-readonly="true"]`, plus a zero-specificity `:not(:where(…))` guard so the disabled paint yields inside a region and border/shadow/chip fall back to the untouched primitives. Only 2 consumers exist, both `{% if readonly %}`. Also cancelled the page-local `.is-off-chunk` opacity inside the region (compound halves). Tests: `tests/test_ver_versao_readonly_presentation.py` (18). Acceptance: `/admin/atividades` → activity → Ver versão |
| UI-A03 | Banco de dados → Google Drive × OneDrive | OneDrive card distributed its surplus height inside the content, so its sections drifted down relative to Google Drive | Cards top-aligned; comparable sections share the same vertical rhythm; `APP_PUBLIC_BASE_URL` aligned; all surplus height sits **after** the last configuration field and **before** the footer/divider; footers aligned | DONE | Cause: `.db-provider-card` was an auto-row grid stretched by `.db-drive-grid`, so default `align-content:stretch` split the surplus equally between every row. Fix: card → flex column; `.db-provider-config{flex:1 1 auto}`; `.db-provider-config-footer{margin-top:auto}`. No spacer element, no fixed height, no provider-specific geometry. Tests: same file (C lane). **Pixel alignment is not automated** — Playwright is not installed in this environment, so the visual check is the acceptance step. **REOPENED 2026-09-21** — the user visually found remaining semantic-row asymmetry before the common actions: the Google card carried a `Seleção de pasta: configuração segura desta máquina` metadata row OneDrive had no equivalent for, so Google reached the common action area one text row later. The height contract from the first repair was correct and is untouched; the defect was a redundant row, not geometry. Carried into UI-B07 and resolved there (Case B). Acceptance: `/admin/banco-dados` |
| UI-B09 | Admin > Acesso → floating action bar | "Aplicar senha padrão" is almost always seen disabled | **Matrix superseded by UI-CP1 (2026-09-24): there is no switch branch any more** — root → disabled/refused ("Ação indisponível para o administrador raiz."); revoked → disabled/refused ("Acesso revogado."); every ordinary active account (pending, personal or default) → enabled/applies. *Original brief, kept for history:* Verify the actual implementation before changing anything. Expected matrix: default passwords OFF → disabled; ON + ordinary active eligible user → enabled; root → disabled where protected; revoked access → disabled; other ineligible state → disabled. If the DS already provides disabled-action explanations/tooltips, show the real reason instead of leaving a mysteriously dead action | DONE_PENDING_VISUAL_CONFIRMATION | **UI-CP1 update (2026-09-24):** the ladder is now two rungs (root → revoked); `REASON_DEFAULTS_DISABLED` ("Ative as senhas padrão para usar esta ação."), the page-global `defaultPasswordsEnabled` JS constant and both server-rendered `disabled` attributes are removed; the endpoint no longer refuses on the switch. Everything below about root/revoked guards, per-row authority, the zero-PBKDF2 render and the shared disabled treatment still holds. Re-acceptance needed with the simplified panel. **Original record:** **The observation is correct behaviour, not a defect — and it hid three real ones.** The live database carries `default_passwords_enabled = '0'` (set 2026-09-20 21:13), and the contract says that is exactly when the action must be dead. What was defective is everything around it: (a) **no root protection at all** — the endpoint had no `is_root_admin` guard and the bar never checked `isRootAdmin` (unlike `delete`), so with the switch on an administrator could replace the root credential with a password printed on the settings panel that stops working the instant the switch is turned off — the precise lock-out `app/root_admin.py` exists to prevent; (b) **no revoked guard**, contradicting `admin_acesso_senha_por_email`, which refuses revoked explicitly; (c) **no per-row authority** — `showBar` set `delete` and `email` per row but never touched `reset`, whose enabled state came once from a page-global Jinja flag, so the frontend could not express any account-level rule; plus the DS disabled treatment (`opacity:.45; cursor:not-allowed`) was scoped to `.atividades-actions-float`, so a refused action on this bar was the "mysteriously dead" button the brief describes. **Fix:** one owner, `app/access_default_password.py`, holding a three-rule ladder (switch → root → revoked) and the reason vocabulary; the view ships `canApplyDefaultPassword`/`applyDefaultPasswordReason` in `users_payload` and the endpoint consults the same module before writing. Reason shown through the `disabled` + `aria-disabled="true"` + `title` triple this app already uses throughout `admin_banco_dados.html` — no new component. The bulk menu item adopted the same authority and the all-or-nothing rule `Excluir` already used. **`estado` is deliberately not an input.** A first pass added an "already uses the current default" no-op refusal; the user rejected it and the rejection was right on both counts. Product: applying the shared default is an explicit administrative credential reset — fresh salt, `auth_version` bump that ends every live session, first-access/reset links killed — so it is never a no-op even when the resulting plaintext is unchanged, and there is nothing to refuse. Engineering: deciding it required comparing a stored hash, i.e. one PBKDF2-600k verification (**measured 226ms**) per row, and `/admin/acesso` applies no LIMIT unless the client asks, so it renders the whole active population (**83 accounts live, 81 of them `default`**) — ~19s of key derivation per page load. Removing the rule made the matrix total: **no row is enabled in the frontend and categorically refused by the backend**, and eligibility is O(rows) column reads in one batched query. Guarded behaviourally by counting `werkzeug.security.check_password_hash` calls during a render and requiring **zero**, plus an AST guard that the owner module cannot even import `app.security.passwords`. Reason strings live in the new module rather than `app/views/**`, so the message catalog digest is untouched (the same placement `app/status_presentation.py` already uses). **Blast radius:** the promoted `#pedido-actions-float .act-btn:disabled` rule reaches every floating action bar — that is the repair, not a side effect; declarations are unchanged. Tests: `tests/test_access_default_password_ui_b09.py` (23) + the node harness fixture now carries the new descriptor field. Acceptance: `/admin/acesso` |
| UI-B02 | Requisições → status badges | Semantically different states shared the same visual treatment | Pendente / Deferida / Deferida Parcialmente / Indeferida must not be indistinguishable; tones must come from the shared DS semantic vocabulary, not from a page-local palette | DONE_PENDING_VISUAL_CONFIRMATION | **Confirmed cause:** each surface owned its own status ladder. Admin gave `Pendente` and `Deferida Parcialmente` the same `status-caution`; the aluno copy had **no `Deferida Parcialmente` branch at all**, so a partial approval reached the student as the unknown-value neutral pill. **Fix:** one owner, `app/status_presentation.py`, exposed to templates as the `status_tone` / `status_label` Jinja globals. Parcialmente → `info`, freed by moving `Devolvida` to `caution` alongside `Pendente` (same category: open, non-final, student-editable, non-notifying). No CSS changed. Tests: `tests/test_status_badge_semantics_ui_b02_b03.py` (36). See detail §UI-B02/B03. Acceptance: `/admin/requisicoes` and `/aluno/requisicoes` |
| UI-B03 | Matriz → status badges | "Vigente" appeared visually neutral, identical to "Rascunho" | "Vigente" is the effective/active state and must take the authoritative active tone; "Rascunho" stays neutral/draft. Shared DS tones only | DONE_PENDING_VISUAL_CONFIRMATION | **Confirmed cause:** `admin_matrizes.html` carried a **pasted copy of the Requisições ladder** (`deferida` / `devolvida` / `indeferida` …). `vigente` appears nowhere in it, so it fell through to the `neutral` fallback — byte-identical to `Rascunho`, which the ladder *did* map to neutral. Every row in the live `matrizes_atividades` is `vigente`, so the whole list was neutral. **Fix:** same shared mapper; `Vigente` → `positive`, `Rascunho` → `neutral`. Only the matriz list renders a matriz status pill. No CSS changed. Tests: same file. See detail §UI-B02/B03. Acceptance: `/admin/matrizes` |
| UI-B05 | Cursos → visualização do curso | Unusual top band/card/layout that visually diverges from other SGAA detail pages | Reuse an accepted detail pattern; do not "fix margins" blindly. Reference chosen by the user: **Turma detail** | DONE | **Confirmed cause:** the page used `.content-block` — the *dashboard summary card* — with the `.content-block-header` that names every other card built from it omitted, leaving untitled full-track chrome whose `justify-content:space-between` body pinned the items to the page edges; it had also never adopted the detail-header contract (raw `.main-title`, stranded footer `← Voltar`). **Fix:** shared `detail_header` macro + a new shared `.detail-meta-strip` in `modern-style.css` reproducing the Turma strip (no chrome, small label above value, blocks from the left). `Turmas`/`Alunos` added on the user's instruction, derived from the rows the view already passes and labelled from the Cursos **list** header vocabulary. No view change, no raw colour, no page `<style>`. **Final shape (user direction):** `Ver` now opens the **edit form with the edit taken away** (`/admin/cursos/<id>/editar?view=1`), the established SGAA pattern — read-only region via `fieldset[disabled][aria-readonly]`, no footer buttons, Back in the header; edit mode gained the shared `.form-actions center`. Tests: `tests/test_curso_detail_shared_header_ui_b05.py` (22). See detail §UI-B05. **Visually accepted by the user 2026-09-21.** |
| UI-B06 | Admin > Acesso | "Novo acesso" primary button appears to use different typography from the normal SGAA primary button | Compare computed `font-family`, `font-size`, `font-weight`, `line-height` and the DS classes against the shared primary-button contract. If different, adopt the shared contract — do not visually approximate with local CSS | DONE_PENDING_VISUAL_CONFIRMATION | **The report was right, and the cause was not on the Acesso page.** `.btn` owned `font-size`, `font-weight` and `line-height` but **not `font-family`** — and a `<button>` does not inherit font-family from its ancestors, the UA stylesheet supplies its own for form controls. So one class rendered in two typefaces by element: **63 `<a class="btn">` in `--font-sans` (Inter, loaded in `base.html`) and 206 `<button class="btn">` in the UA font**. `Novo acesso` is a `<button>`; the list CTAs it was compared against (Alunos, Cursos, Turmas, Matrizes, Requisições, Atividades, detalhe da turma) are anchors. Everything else already agreed — `font-size:13px` and `height:30px` from `.toolbar .actions .btn` reach both, `font-weight:400`/`line-height:1` from `.btn`, and no `letter-spacing`/`text-transform` exists on any button. **Fix:** one declaration, `font-family:inherit` on `.btn` in `modern-style.css`. No page-local rule, no Acesso-specific typography. **Blast radius is the whole app:** all 206 `<button class="btn">` change typeface — that is the repair, not a side effect. Tests: `tests/test_novo_acesso_button_typography_ui_b06.py` (6). See detail §UI-B06. Acceptance: `/admin/acesso` |
| UI-B01 | E-mail de processamento de atividades/requisições | For **one** processed request the delivered e-mail read "Suas requisição … foi processada." | Cardinality coherent across the whole message. 1: "Sua requisição … foi processada." 2+: "Suas requisições … foram processadas." Subject audited too — 1: "Processamento de atividade acadêmica"; 2+: "Processamento de atividades acadêmicas". Subject and body must derive from one authoritative cardinality; independently pluralized fragments must not be concatenated. Sender name "Atividades Complementares EJ" unchanged | DONE_PENDING_VISUAL_CONFIRMATION | **Confirmed cause:** the renderer was already correct; the frozen copy was administrator-authored **preset data** (`configuracoes_presets`, the `is_default=1` e-mail model), which glued literal `Suas` + literal `requisição` + literal `foi processada` and a permanently plural subject. **Fix:** one authoritative cardinality decision in `build_context` now emits the whole agreeing sentence as `{requisicao.frase}` plus a subject-safe `{atividade.substantivo}`; the stored model was rewritten to placeholder-only copy by `tools/repair_email_preset_cardinality.py`. Tests: `tests/test_request_email_cardinality_ui_b01.py` (18), captured through the existing fake-mail boundary. See detail §UI-B01. Acceptance: process 1 request → send; process 2 → send |
| UI-B07 | Banco de dados → Operações + provider cards | "Enviar backup agora" sat inside the upper provider body, and the Google card carried one metadata row more than OneDrive before reaching it | Backup-now belongs to the card **footer**, beside Salvar, with endpoint / method / CSRF / provider / icon / disabled behaviour unchanged and exactly one per provider. Common body rows must align across both cards; spare height only between the last configuration field and the footer. No spacer, no `&nbsp;`, no fixed height, no provider-specific padding | DONE | **Case B.** The Google-only row printed `google_picker_config_source`, which `cloud_config.get_google_picker_config()` derives from the **same** `providers.google` machine-store record `gdrive_config_source` already reports one row above — the identical custody sentence about the identical blob. OneDrive has no equivalent because its folder browser (`/admin/backup/cloud-folders/onedrive`) runs on the OAuth token it already holds, so it has no second credential to report. Row removed from Google rather than invented for OneDrive; both cards are now 3 rows. The genuinely Google-specific part is the **failure** (Picker API key + App ID missing), which moved to the state-driven note region both cards already share with `Último upload` / `Falha` — never a common metadata row. Backup-now moved to `.db-provider-config-footer` via a `provider_backup_now_*` macro pair; forms cannot nest, so it POSTs through a control-only `<form>` bound with the HTML `form` attribute. **Operações lane (the originally reported defect, now delivered):** the generic `Gerar backup agora` left the explanatory row and moved to the bottom of the Operações card, reusing the footer contract this page already owns and that was accepted on `Destinos de backup` and `Política de retenção` — a `.db-actions` row as the last child of a card form, right-aligned over a divider by `.db-card form > .db-actions`. No new class. The `.db-card-lead` flex wrapper existed only to pin that button right of the sentence and had exactly one consumer, so wrapper and its three rules were deleted. Placement only: endpoint, POST, CSRF, `banco_dados:edit` gate, `database` icon and label unchanged. Tests: `tests/test_cloud_provider_card_symmetry_ui_b07.py` (20) + `tests/test_operacoes_backup_action_footer_ui_b07.py` (11). See detail §UI-B07. Acceptance: `/admin/banco-dados` |
| UI-B08 | Admin > Acesso | No column showing the person's access/account state | Add a final column with **one** concise pill. Semantics to cover: pending/not yet delivered, access e-mail delivered, active, revoked, and others only if genuinely necessary. See detail §UI-B08 for the full constraint list | DONE_PENDING_VISUAL_CONFIRMATION | **UI-CP1 update (2026-09-24):** status mapping reconciled with the v11 credential model — `pending` follows first-access evidence (Pendente / Disponibilizado / Expirado), `personal` **and an explicitly applied `default`** are Ativo; see §UI-CP1 "Situação mapping". **Original record:** **Schema change required, and it was the whole point.** The durable-evidence inventory found that `app/password_email.py` already distinguished `sent` / `failed` / `indeterminate` / `unavailable`, but only two of those left a trace: `unavailable` issues no token, `failed` sets `invalidated_at` — while **`sent` and `indeterminate` were byte-identical in the database**, both leaving a live unconsumed token and differing only in a log line. A live `first_access` token therefore proved "issued, and the provider either confirmed or said nothing", which is not delivery. `email_envios` (status `prepared/sending/sent/failed/indeterminate`) is the **requisição/preset** outbox, keyed `aluno_id` → `alunos`; password mail never passes through it. So v9 could **not** prove a successful send. **prod-1/v10 `access_delivery`** adds one nullable column, `senha_tokens.sent_at`, written by a single writer (`mark_password_token_sent`) on the confirmed-send branch only. Additive one-line `ALTER`, digest-identical to a fresh v10 bootstrap (the declare-last-before-FOREIGN-KEY technique v9 used). **Backfill is deliberately nothing** — no pre-v10 row carries the evidence, so accounts e-mailed before v10 read `Pendente` until resent; inventing a timestamp from `created_at` would manufacture the very proof the column exists to require. State model (5, compact): `Pendente` / `Disponibilizado` / `Ativo` / `Revogado` / `Expirado`. `Expirado` adopted because it is durably provable and materially operational — it separates "link still actionable by the student" from "link dead, resend needed", which `Disponibilizado` would otherwise misreport. `Falhou` / `Indeterminado` / `Não enviado` deliberately NOT added. **Default-password edge case:** a `default`-state account may log in via the shared password while the switch is on and is still `Pendente` — the derivation reads neither `configuracoes_app` nor the switch, so toggling it moves no pill (tested, plus a structural guard). **Header `Situação`:** `Status` is already SGAA's near-universal header for the academic Ativo/Inativo lifecycle (`admin_alunos`, `admin_cursos`, `admin_turmas`), i.e. exactly the concept this column must not be confused with; this table carries no academic status column, so `Situação` can only read as the situation of the *acesso* each row is. **Known scope limit:** the active list excludes `acesso_ativo = 0` by pre-existing design (revoked access is history kept for attribution), so `Revogado` is derived and tested but never rendered here. Not changed in this task. Tones from the single owner `app/status_presentation.py`, all pre-existing: Pendente `caution` (the same word already caution in the Requisições ladder), Disponibilizado `info`, Ativo `positive`, Revogado `negative`, Expirado `caution` (nothing is terminal — it waits on an admin, the Pendente/Devolvida precedent). Shared `.badge.status-pill`, one pill per row, no local CSS, no raw colour. Geometry: a 6th track `minmax(150px,0.9fr)`; the five existing minima are untouched and `--imp-list-min-width` grows 966→1116px. Tests: `tests/test_access_onboarding_status_ui_b08.py` (33) + `tests/test_prod1_v10_access_delivery.py` (12). See detail §UI-B08. Acceptance: `/admin/acesso` |
| UI-CP1 | Admin > Acesso → credential model (accepted product direction) | The global "Ativar senhas padrão" switch is conceptually rejected | Default passwords become an explicit per-account administrative action. A true `pending` credential state exists; no global setting takes part in login, in "Aplicar senha padrão", in account creation or in password e-mail flows. Do not mark complete until the model is implemented, the migration proven, focused tests pass and the user visually accepts the simplified panel. UI-B13/B14/B15 are out of scope | DONE | **Visually accepted by the user on 2026-09-24.** Implemented in the working tree as prod-1/**v11** (`credential_pending`). **Canonical `database.db` migrated to v11 on 2026-09-24 23:36 (authorised)** through the governed `bootstrap_prod1_schema` dispatcher, exactly once: `personal→personal` 2, `default(switch off)→pending` 83, `default→default` 0, refused 0. Pre-v11 backup `D:\Projetos\SGAA_backups\v11_credential_pending\database.pre-v11-credential-pending-20260924-233553.db` (SHA-256 `141c825b…15559f`, v10). Post-acceptance cosmetic cleanup (same item, no new row): the "Senhas padrão" header/body/footer no longer paint the translucent `--bg-underpanel` over the gray page — the outer `.access-defaults-panel` owns `background:var(--surface)` and the three regions inherit it; the outer border and the header/footer dividers moved from the raw `0.5px solid rgba(0,0,0,0.08)` hairline to the DS panel border `1px solid var(--border-strong)` (as `.content-block` and the summary cards). Evidence: `tests/test_prod1_v11_credential_pending.py`, `tests/test_admin_access_default_password_panel.py` (supersedes `test_admin_access_default_passwords_enabled.py`), and the reworked UI-B08/UI-B09 suites. Acceptance: `/admin/acesso` on a disposable v11 copy via `run_acceptance.bat` |
| UI-B15 | Admin > Acesso — console / CSP / semântica de formulário | Five browser-console messages: Typekit fonts refused by `font-src`; Chrome's "Multiple forms ... break up complex forms" against `/admin/acesso/senhas-default`; `#access-email` with no `autocomplete`; `#access-password-form` with no username identity; `unpkg.com/lucide.min.js.map` refused by `connect-src` | Inventory each message to its exact owner before touching anything. Remove unnecessary external dependencies at the source rather than widening CSP. No `font-src *`, `connect-src *`, bare `https:` or `*.` wildcard. Valid HTML, one form owner per independent server action, endpoint/POST/CSRF/toggles/RBAC preserved. Correct standard autocomplete tokens — never `off` to silence a warning. Not a visual redesign | IN_ACCEPTANCE | **First pass: three of the five were not SGAA defects. Real browser output then corrected two of those answers — see BROWSER EVIDENCE below.** **(1) Typekit:** the repository references Adobe/Typekit **nowhere** — no `@font-face`, `@import`, `<link>`, inline style or library — and the rendered page names exactly three external hosts (`fonts.googleapis.com`, `fonts.gstatic.com`, and `www.w3.org` as an SVG `xmlns`, never fetched). The request originates outside the application; `font-src` is working. **Nothing added to CSP.** Font authority unchanged: `--font-sans` (Inter) in `foundation/tokens.css`, reaching controls through the UI-B06 `font-family:inherit` on `.btn`. **(2) Lucide source map:** the CDN bundle ends in a `sourceMappingURL` comment, which DevTools resolves against the script origin → `https://unpkg.com/lucide.min.js.map`, a map that is not published there. A source map is never a runtime dependency, so `connect-src` was not widened; the **asset** was fixed. SGAA now serves `static/vendor/lucide.min.js` — the same pinned v0.544.0 build the visual baseline already renders with (`tests/visual/vendor/lucide.min.js`), minus that one line. **CSP got narrower as a result: `https://unpkg.com` was removed from `script-src`.** All three icon-loading templates (`base.html`, `base_aluno.html`, `400.html`) moved together, since leaving one behind would be a blocked script. **(3) "Multiple forms":** the rendered DOM was audited before any edit and **none** of the structural causes exists — the three forms are siblings (nesting depth 1), every tag closes, no control belongs to another endpoint, and the two modal Save buttons outside their form use the HTML `form=` attribute, which is explicit ownership. The panel is also genuinely **one** server action: one POST persists five passwords plus the switch. The message comes from Chrome's password-manager parser, which cannot map five differently-named password fields with no account identity onto one credential form and splits them. Splitting the form would satisfy the heuristic and break the Save, so it was not done; instead the fields now declare their real intent, `autocomplete="new-password"` (the token this repo already uses for masked configuration secrets in `admin_banco_dados.html`), which is strictly more specific than the previous `off`. **No username was invented for that panel — it configures profiles, not an account.** **The two real gaps were fixed.** `#access-email` is the login identity (`usuarios.email`, what `/login` authenticates on) → `autocomplete="username"`, pairing with the sibling `new-password`. `#access-password-form` gained a hidden, readonly, **name-less** `type="email" autocomplete="username"` identity, filled by `openPasswordModal()` from the selected row **only when exactly one row is selected** — a bulk selection has no single identity and borrows none — and cleared on close. Name-less on purpose: the real body is hand-built (`usuario_ids` + `nova_senha` + `csrf_token`), so the hint can never reach the endpoint. Password autocomplete audited and already correct (`new-password` on both credential-setting fields). Geometry, pills, table, cards, colours, spacing, typography and button placement untouched. Tests: `tests/test_console_form_semantics_ui_b15.py` (31; 13 fail against the pre-fix tree). **BROWSER EVIDENCE 2026-09-21 — two of the first-pass answers were wrong and are corrected.** **(a) `cloud-backup` is a real product defect**, not a self-hosting side effect: the name is absent from the Lucide registry, so the `Backup de dados` sidebar entry has been rendering **no glyph at all**, on the CDN too — self-hosting only made it audible. Owner `templates/base.html`; replaced with `database-backup`, which exists in the pinned v0.544.0 set and matches the `database` vocabulary `/admin/banco-dados` already uses. All 39 icon names rendered on `/admin/acesso` were then audited against the shipped registry: `cloud-backup` was the only miss, and the sweep now covers the whole template tree. **(b) The hidden username field did not work** — Chrome kept warning. The HTML `hidden` attribute resolves to `display:none`, the element is never rendered, and a field the layout does not produce cannot be associated by the password manager. "Optionally hidden" means *visually* hidden. It is now the shared `.sr-only` primitive: present in the layout, zero visual footprint, `readonly`, `tabindex="-1"`, still name-less. **(c) `new-password` on the five profile defaults was the wrong token and was reverted to `off`.** They are application **configuration secrets**, not browser-manageable credentials — Admin / Coordenador / Consultor / Usuário / Usuário teste are PROFILES, not login identities. `new-password` asserted they were account password-change fields, which made Chrome demand a username field for the one form on the page that can never have one: one wrong answer, two warnings. **(d) "Multiple forms" survived both `off` and `new-password`**, which is the evidence that closes it: it is a Chrome heuristic false positive on a valid single-action settings form. Proven from the rendered structure (sibling forms, nesting depth 1, every tag closed, every control owned, one POST, one Save) and **not** chased by splitting the panel. **(e) Typekit** re-proved from the *served* bytes, not just the source tree: every CSS/JS asset the page links is fetched through the app and searched. Nothing SGAA serves declares it. Source inspection cannot see extension-injected resources — **final attribution requires an incognito / extensions-disabled recheck**. No CSP change. **(f) Forced reflow 35ms** — not investigated and not optimized, per instruction; see §UI-B15 for the likely handler. CSP posture held: Lucide from `'self'`, no unpkg script or connect exception, no Typekit font exception. Tests: `tests/test_console_form_semantics_ui_b15.py` (43). See detail §UI-B15. Acceptance: `/admin/acesso` |
| UI-B16 | Banco de dados → Operações / Política de retenção / Destinos e sincronização | Card footers do not follow the Design-System footer pattern | Footers adopt the accepted panel footer (Configurações cards, Acesso "Senhas padrão"): full-bleed `1px solid var(--border-strong)` divider over `11px 16px` padding. No new class, no raw colour | DONE_PENDING_VISUAL_CONFIRMATION | **Cause:** the shared `.db-card form > .db-actions` footer drew a raw `#edf2f7` divider inset by the card's 16px padding (`padding-top:10px`, no bottom rhythm), and the Google Drive / OneDrive provider footers (`.db-provider-config-footer`) a raw inset `#e2e8f0` one. **Fix:** both rules now carry `border-top:1px solid var(--border-strong); padding:11px 16px` and pull out to the card edges with negative margins equal to the card padding (`16px -16px -16px` / `0 -16px -16px`; provider keeps `margin-top:auto`, declared after the shorthand, so the UI-A03 surplus still lands above the footer). Destinos' settings footer sits mid-card, directly above the provider separator: `form:has(+ .db-drive-sep) > .db-actions{margin-bottom:0}` + `form + .db-drive-sep{margin-top:0}` make the separator line close the footer instead of stacking a second divider. Markup untouched. Tests: `tests/test_ui_panel_footers_and_controls_ui_b16_b19.py` + existing UI-B07/UI-A03 suites green. Acceptance: `/admin/banco-dados` |
| UI-B17 | Atividades → Ver versão → `.versao-switcher .control` | Version `select` does not follow the standard border-radius | Use the shared DS radius; no page-local patch, no new token | DONE_PENDING_VISUAL_CONFIRMATION | **Cause:** the shared "Unified Field States" rule gives `select.control` colours and hover/focus only; geometry comes from `.field-card` (which draws the frame around a borderless control) or `.field select`. A `select.control` with no `.field-card` around it — the version switcher and the "Substituir versão" dialog select, the only two — fell back to the browser's own corner. **Fix (DS, not page):** `modern-style.css` gains `select.control{ border-radius:var(--radius); }` next to the shared field states; inert inside `.field-card` (borderless, transparent). The wider `select` audit stays **UI-B14** (`BACKLOG`). Tests: `tests/test_ui_panel_footers_and_controls_ui_b16_b19.py`. Acceptance: any activity's Ver versão page |
| UI-B18 | Configurações → Mensagens | Message cards have no footer splitter line | Resetar/Salvar row becomes the DS panel footer: full-bleed `1px solid var(--border-strong)` divider, `11px 16px` padding | DONE_PENDING_VISUAL_CONFIRMATION | **Cause:** `.message-actions` was a plain flex row inside the body's `12px 16px` padding, while head/body already follow the Configurações card contract. **Fix:** `.message-actions` adds `margin:4px -16px -12px; padding:11px 16px; border-top:1px solid var(--border-strong)` — flush with the card edges through the body padding (card keeps `overflow:hidden`). Markup untouched. Tests: `tests/test_ui_panel_footers_and_controls_ui_b16_b19.py`. Acceptance: `/admin/mensagens` |
| UI-B19 | Alunos → Adicionar aluno | Remove the "Foto" label | The avatar row carries no row label, as Meus dados already does; avatar, accessible name and controls unchanged | DONE_PENDING_VISUAL_CONFIRMATION | `<label class="row-label">{{ user_message("Foto") }}</label>` removed; `.row-label` is absolutely positioned in the gutter, so nothing reflows. It was the literal's only consumer, so `msg_0f5e4f087245b242` retires: catalog ledger term 14, **−1** (583 → 582), `UIB19_PHOTO_LABEL_RETIRED_KEYS` + `catalog_keys_before_photo_label()` walked at all three reconstruction sites, canonical digest re-declared. All 20 catalog-pinning test files green. Tests: `tests/test_ui_panel_footers_and_controls_ui_b16_b19.py`. Acceptance: `/admin/adicionar_aluno` |
| UI-B20 | Requisições → formulário da requisição → Observação | "Observação" sits farther from the previous card than the standard row spacing | One standard `.form-cards-narrow` row-gap (12px) between Comprovantes and Observação | DONE_PENDING_VISUAL_CONFIRMATION | **Cause:** the empty `<div id="m_comprovantes_container"></div>` between the two rows is still a 0px grid item of `.form-cards-narrow` (`row-gap:12px`), so the gap was paid twice (24px). **Fix:** `#m_comprovantes_container:empty{ display:none; }` in the page's runtime stylesheet — out of the grid while empty; it keeps `display:grid; row-gap:12px` when it lists existing comprovantes (every JS reset uses `innerHTML = ''`, so `:empty` holds). Tests: `tests/test_ui_requisicao_gap_turma_surface_ui_b20_b21.py`. Acceptance: `/admin/requisicoes` → Nova requisição |
| UI-B21 | Turmas → Adicionar turma / Editar turma → Alunos da turma | Card background and the band around the student rows are gray; the fix must reach Editar turma too and be tokenized in the Design System | Header and the area around the rows use the standard white surface on **both** pages, through one DS component whose tokens resolve to global tokens; rows unchanged | DONE_PENDING_VISUAL_CONFIRMATION | **Cause:** both pages carried a byte-for-byte copy of the student-list CSS in their own `<style>` (the only difference was the first-pass fix, which is why it did not reach Editar turma), and the copies set `--turma-alunos-header-bg` / `--turma-alunos-content-bg` to `var(--bg)` and the row shell to a raw `#f3f4f6`. **Fix:** the whole list (card, header, action buttons, rows, cells, status select, remove button) moved to the new DS component `static/css/components/turma-alunos.css`, linked from both pages' `extra_head` before their `<style>`; nothing of it remains in either template. Component tokens on `.alunos-wide`: header and content `var(--surface)`, row shell `var(--bg)` (was raw `#f3f4f6`, the same value); the rows' `#` chip and inner band read the row token so the lines are unchanged. Only literal left is the pre-existing `var(--danger, #b91c1c)` fallback (no global `--danger` token exists). DS README file map updated; cross-template duplication ratchet reset to the measured 308 (was a loose 536). Tests: `tests/test_ui_requisicao_gap_turma_surface_ui_b20_b21.py` + `tests/test_ds_design_system_contract.py`. Acceptance: `/admin/adicionar_turma` and `/admin/editar_turma/<id>` |


---

## 2. Backlog

| ID | Area | User-reported issue | Expected behavior / constraint | Status | Notes / acceptance evidence |
|---|---|---|---|---|---|
| UI-B13 | Meus dados → campo de senha | "Deixe em branco para manter" may no longer be literally true after the new credential flow | Audit the password field in Meus dados against the credential contract. **Blank must be a true no-op:** hash unchanged, `usuario_credenciais.estado` unchanged, `auth_version` unchanged, `senha_tokens` untouched, and no accidental transition into first-access or shared-default state. **A new password must:** store a personal credential, set `estado=personal`, bump `auth_version`, and invalidate other sessions/tokens per the current contract — with the acting user's own session restamped so a self-change does not log them out. `default_passwords_enabled` ON/OFF must not alter any of this. Cover the root administrator and the aluno/usuário paths, not just admin. Finally, verify the copy "Deixe em branco para manter" is still literally accurate; if behaviour is correct but the wording is not, fix the wording | BACKLOG | Raised by the user during UI-B09 and recorded so it is not lost. **Not investigated.** Related durable owners to read first: `app/user_accounts.py` (`set_usuario_password_hash` always bumps `auth_version` and invalidates every outstanding token), `app/access_onboarding.py` (the pill derives from `estado` + confirmed deliveries, so a stray `estado` write moves it), and `app/access_default_password.py` (UI-B09's ladder). Acceptance: `/meus-dados` |
| UI-B04 | Alertas | The alert title is being rendered to the target user | The title is **internal**: it exists so the administrator can identify the alert later when editing/managing it. It must not appear in the alert delivered to or displayed for the target user unless a separate, explicit product field is intended as user content. Internal title stays available in admin management; the user sees only the actual alert content/message | DONE_PENDING_VISUAL_CONFIRMATION | Recipient rendering was already correct (`aluno_dashboard.html` binds `alerta.mensagem` only). The leak was preview-only: `updatePreview()` in `templates/admin_alertas.html` concatenated `titulo + ' - ' + mensagem`, and `tituloInput` was wired to it. Preview now reads the message alone; admin list column and the edit modal's Titulo field are untouched. Tests: `tests/test_alerta_preview_matches_recipient_ui_b04.py` (10 passed; 3 fail against the pre-fix template). Visual check: `/admin/alertas` -> Novo alerta |
| UI-B12 | Configurações → Pré-definições (editor de e-mail) | Preset editor permits manually composing grammatically inconsistent singular/plural fragments | The fragment placeholders (`{requisicao.possessivo}`, `{requisicao.substantivo}`, `{requisicao.processamento}`) remain in the published vocabulary, so an administrator can still hand-glue a plural possessive to a singular noun — the exact shape of the delivered UI-B01 defect. Wanted: a save-time coherence guard, or retirement of the fragment tokens in favour of the whole-sentence `{requisicao.frase}` | BACKLOG | Residual of UI-B01, promoted from prose in §UI-B01 to a tracked item. **Not implemented.** The shipped default copy no longer uses the fragments; this is about what an administrator can still author |
| UI-B11 | Design System — colour tokenization audit | Raw reusable component colours bypass the DS token layer | Search shared and page-local SGAA UI CSS for raw hex/rgb/hsl controlling reusable semantics and classify each finding: **A** already tokenized correctly; **B** reusable semantic colour using a raw literal → migrate to the existing token; **C** duplicate semantic token → consolidate deliberately; **D** genuinely page/content-specific → may remain, with an explicit stated reason. Do not mass-rewrite blindly, and never replace one raw value with another raw value. Goal: same semantic state → same token → same visual treatment | BACKLOG | Recorded as a separate audit item alongside UI-B10, per the user's instruction. Priority order: 1 form controls · 2 read-only/disabled · 3 badges/status pills · 4 buttons/actions · 5 cards/modals/toolbars |
| UI-B14 | Design System — `select` / form-control consistency | `select` border-radius diverges from the rest of the shared form-control contract | Reconcile `select` with the DS form-control primitive rather than patching individual pages: one radius token, one border, one hover/focus treatment shared with `input` and the other controls. Audit page-local `select` rules that restate geometry (`admin_acesso.html` alone carries two) and fold them into the shared owner. Do not introduce a new token or a second radius | BACKLOG | Requested by the user before UI-B15 and recorded so it is not lost. **Not investigated, not implemented** — UI-B15 deliberately changed no geometry. Likely owners to read first: `static/css/components/form.css` and the `--radius` token in `static/css/foundation/tokens.css`. **2026-09-26:** the standalone `select.control` corner (version switcher) was fixed at the shared rule under UI-B17; the rest of this audit is still open |


---

## 3. History — repaired, do not reopen

| ID | Area | User-reported issue | Expected behavior / constraint | Status | Notes / acceptance evidence |
|---|---|---|---|---|---|
| UI-H01 | Admin > Acesso | Root-recovery informational row shown on the page | Row removed | DONE | User stated: "The root-recovery note removal is accepted." |
| UI-H02 | Admin > Acesso → Novo acesso | Permission "Total" pills used page-local custom CSS (yellow badge family) | Shared DS pill; access level is a neutral value, not a status | DONE | Adopted `badge status-pill status-neutral` from `modern-style.css`; local `.access-scope-pill` family removed. User stated: "The permission-pill repair is accepted." |
| UI-H03 | Requisições → request/detail modal | Equivalent non-editable controls rendered with different backgrounds/text treatments | One shared DS read-only presentation for input / select / textarea / compound / icon-leading fields; semantics unchanged | DONE | `aria-readonly="true"` adopted as the declared-intent marker; `components/form.css` "DISABLED-BUT-READ-ONLY" block added. Tests: `tests/test_requisicao_readonly_presentation.py`. The user cites this surface as the **accepted reference** in UI-B10 |
| UI-H04 | Admin > Acesso → Novo acesso | "Enviar acesso" threw on a null `emailUrl` when the action bar hid mid-confirmation | Action descriptor snapshotted at click time; no read of mutable hover state after an `await` | DONE | Non-visual behavioural repair. Evidence: `tests/test_admin_access_repair_contract.py` + the node harness `tests/js/acesso_action_bar_harness.js` replaying the reported interleaving |
| UI-H05 | Admin > Acesso | Blank password still promised a default login with the default-password switch OFF | With the switch off, the account is born with no usable password and the help text must not promise one | DONE | Non-visual behavioural repair. Evidence: the four-cell creation matrix in `tests/test_admin_access_repair_contract.py` |
| UI-H06 | Access lifecycle | No durable access revocation | Revocation persisted in schema v9 | DONE | Non-visual. Evidence: `app/prod1_access_status_v9.py`, `app/prod1_access_status_ddl.py`, `tests/test_prod1_v9_access_status.py` |
| UI-H07 | Root identity | Root e-mail / master-key contract undefined | E-mail-keyed root identity with a `tipo=admin` guard and legacy fallback | DONE | Non-visual. Evidence: `app/root_admin.py`, `tests/test_root_admin_contract.py`. **2026-09-26 configuration boundary:** the real root address and the break-glass hash are per-installation configuration (`APP_BOOTSTRAP_ADMIN_EMAIL`, `APP_ROOT_MASTER_KEY_HASH`, kept in the git-ignored `.env`), never source. The source default is the non-deliverable `root-admin@example.invalid`; with no hash configured the master-key path is unavailable and everything else is unchanged. The suite self-configures synthetic values (`tests/root_admin_test_config.py`, exported by `tests/conftest.py`) |

> UI-H04 through UI-H07 are non-visual (behaviour, schema, identity), so "visual
> confirmation" does not apply; `DONE` here means the named repository evidence
> exists and passes. They remain uncommitted — see the worktree caveat above.

---

## 4. Item detail

Detail is recorded only where the user stated constraints that do not compress
into a table cell. The table above remains the canonical status record.

### §UI-B01 — e-mail cardinality

Observed for a single processed request:

> "Suas requisição … foi processada."

Required:

- 1 request → "Sua requisição … foi processada."
- 2+ requests → "Suas requisições … foram processadas."

Subject audit:

- 1 activity → "Processamento de atividade acadêmica"
- 2+ activities → "Processamento de atividades acadêmicas"

Constraints:

- Subject and body must both derive from the **authoritative cardinality**.
- Do not concatenate independently pluralized fragments.
- Sender name "Atividades Complementares EJ" remains unchanged.

**Resolution (`DONE_PENDING_VISUAL_CONFIRMATION`).**

Production composer: `app/request_email_render.render_student_email`, called once
per student from `app/request_email_dispatch.build_plan`, whose output
`dispatch()` hands to `app.services.mail_service.send_text_email`. Subject and
body are **not** in the codebase: they come from `template["assunto"]` /
`template["texto"]`, i.e. the `is_default=1` row of `configuracoes_presets`
(`presets_api.get_default_email_preset`).

Cause. The renderer already derived `possessivo` / `substantivo` /
`processamento` from one per-student count. The delivered defect was in the
stored preset, which had frozen two of the three words as literals:

```
assunto: 'Processamento de atividades acadêmicas'
texto:   '{saudacao}, {aluno.primeironome}.\n\n'
         'Suas requisição do dia {data.inicio} foi processada. '
         'Acesse o SGAA para conferir.'
```

`Suas` (plural literal) + `requisição` (singular literal) + `foi processada`
(singular literal) + a permanently plural subject. Only `{data.inicio}` was
dynamic, so the same text shipped to a student with one decision and to a
student with five.

Authoritative cardinality: `len(events)` for **this student's** bucket from
`group_events_by_student`. Each `requisicao_email_eventos` row snapshots exactly
one request and exactly one academic activity (`atividade_versao_id` →
`atividade_nome`), so the request count *is* the processed-activity count — the
subject and the body cannot disagree. Distinct activity *names* are deliberately
not collapsed: two requests for the same activity are two processed items, and a
deduplicated subject would contradict the body's count.

| Phrase | Governing count |
|---|---|
| `{requisicao.frase}` (body sentence) | `len(events)` for this student |
| `{atividade.substantivo}` (subject) | `len(events)` for this student |

Fix. `build_context` computes the decision once and assembles the **whole
sentence** as a single context value, so a preset can no longer desynchronize its
parts. Two placeholders added to the closed vocabulary:

- `{requisicao.frase}` → `Sua requisição do dia 15/09/2026 foi processada.` /
  `Suas requisições do dia 15/09/2026 foram processadas.` (and
  `… de 15/09/2026 a 18/09/2026 …` for a real range; no double space when no
  date is known).
- `{atividade.substantivo}` → `atividade acadêmica` / `atividades acadêmicas`,
  scalar and therefore subject-safe.

The existing fragment tokens (`{requisicao.possessivo}`,
`{requisicao.substantivo}`, `{requisicao.processamento}`) stay — they are each
correct and are part of the published admin vocabulary — but the shipped copy no
longer uses them.

Before / after (rendered through the live stored model):

| | Before | After (1) | After (2+) |
|---|---|---|---|
| Subject | `Processamento de atividades acadêmicas` (always) | `Processamento de atividade acadêmica` | `Processamento de atividades acadêmicas` |
| Body | `Suas requisição do dia 15/09/2026 foi processada.` (always) | `Sua requisição do dia 15/09/2026 foi processada.` | `Suas requisições do dia 15/09/2026 foram processadas.` |

Stored-data repair: `tools/repair_email_preset_cardinality.py` (dry run by
default, `--apply` to write, idempotent) rewrote the model to
`DEFAULT_SUBJECT_TEMPLATE` / `DEFAULT_BODY_TEMPLATE`. Backup taken as
`database.pre-ui-b01-email-cardinality-20260921-003113.db`. Adding placeholders
alone would not have repaired copy that was already saved.

Same-flow audit (§6 scope only, nothing outside this flow): `render_request_block`
emits per-event singular labels — correct by construction. `dispatch.summarize`
already agrees (`1 e-mail enviado` / `2 e-mails enviados`, `não pôde` /
`não puderam`, `já havia` / `já haviam`, `aguarda` / `aguardam`) via the shared
`pluralize`. The Requisições summary chip consumes server-agreed parts. No other
disagreement found in this flow.

Residual risk (recorded, not expanded into this task): the fragment tokens remain
available, so an administrator can still hand-glue `Suas` to a hardcoded singular
noun in Pré-definições. The chip help text names the coherent phrase first; no
save-time guard was added.

Not automated: the actual provider delivery. Acceptance is sending one processed
request and then two, from the real Requisições send action.

### §UI-B02 / §UI-B03 — status badge semantics

One cause behind both reports: **every surface decided locally what a status
looks like.** Three independent ladders existed for two domains, and they had
drifted.

**Requisições — authoritative statuses.** `app.prod1_schema.REQUEST_STATUSES`,
the same six the `requisicoes.status` CHECK enforces: `Pendente`, `Deferida`,
`Deferida Parcialmente`, `Indeferida`, `Devolvida`, `Encerrada`.

**Matrizes — authoritative statuses.** The `matrizes_atividades.status` CHECK:
`rascunho`, `vigente`, `encerrada`, `ativa`, `inativa`. The form and the list
filter only offer the first three; `ativa`/`inativa` are reachable through
stored data only.

**Before.**

| Status | admin_requisicoes | aluno_minhas_requisicoes | admin_matrizes | Collided with |
|---|---|---|---|---|
| Pendente | caution | caution | — | **Deferida Parcialmente** |
| Deferida | positive | positive | — | — |
| Deferida Parcialmente | caution | **no branch → neutral** | — | **Pendente** (admin); unknown-status pill (aluno) |
| Indeferida | negative | negative | — | Encerrada |
| Devolvida | info | info | — | — |
| Encerrada | negative | negative | — | Indeferida |
| Rascunho | — | — | neutral | — |
| Vigente | — | — | **neutral (fallback)** | **Rascunho** |
| Encerrada (matriz) | — | — | negative | — |

`admin_matrizes.html` held a **copy of the Requisições ladder** — its branches
tested for `deferida`, `devolvida`, `indeferida`, `parcialmente deferido`.
`vigente` matched none of them and fell to the final `neutral`. Every row in
the live `matrizes_atividades` is `vigente`, so the entire column was neutral.

**Semantic reasoning.** Categories taken from domain code, not from taste:

| Category | Members | Evidence in code | Tone |
|---|---|---|---|
| open, no final decision | Pendente, Devolvida | both student-editable (`requisition_policy.can_student_edit_requisition`), both in `NON_NOTIFYING_STATUSES` | caution |
| final decision, granted in full | Deferida | `APPROVED_STATUSES` ∩ `FINAL_DECISION_STATUSES` | positive |
| final decision, granted in part | Deferida Parcialmente | same, but the only status carrying `horas_deferidas` | info |
| terminal, nothing granted | Indeferida, Encerrada | the admin "Encerrar" action already carries `btn-indeferir` and the same `circle-x` icon | negative |
| unrecognised value | — | — | neutral |

| Matriz status | Reading | Tone |
|---|---|---|
| Rascunho | not yet the effective matrix — draft | neutral |
| Vigente | the currently effective matrix | positive |
| Encerrada | retired, no longer usable | negative |
| Ativa / Inativa | matches the active/inactive pair Alunos, Cursos and Turmas already use | positive / neutral |

**Two shared tones, both deliberate** (the constraint was *not* to give every
status a unique colour for the sake of uniqueness):

* `caution` = Pendente + Devolvida. Same category — open, non-final, awaiting
  action, no decision e-mail. The pill text carries the distinction.
* `negative` = Indeferida + Encerrada. Same category — the request is over and
  no hours were awarded.

`Devolvida` moved `info → caution` to free `info` for the partial grant. That
is the one knock-on change: `info` was the only remaining non-neutral tone, and
a partial *outcome* has a stronger claim to a distinct tone than a second
waiting state does.

**After — the four the user named resolve to four distinct tones.**

| Status | Tone | Change |
|---|---|---|
| Pendente | caution | unchanged |
| Deferida | positive | unchanged |
| Deferida Parcialmente | **info** | was caution (admin) / neutral (aluno) |
| Indeferida | negative | unchanged |
| Devolvida | **caution** | was info |
| Encerrada | negative | unchanged |
| Rascunho | neutral | unchanged |
| **Vigente** | **positive** | was neutral — the UI-B03 fix |

**Central helper.** `app/status_presentation.py` — `status_tone(domain,
status)` and `status_label(domain, status)`, registered as Jinja globals in
`create_app`. Deliberately **not** under `app/views/**`: that tree is scanned
by `utils/messages.py`, and these are presentation vocabulary, not editable
messages. The module contains no colour value and cannot: it selects among the
five tones `modern-style.css` already publishes as
`.badge.status-pill.status-*`.

**Consumers audited — the full population.**

| Surface | Renders a status pill? | Action |
|---|---|---|
| `admin_requisicoes.html` (list) | yes | ladder replaced by the shared mapper |
| `aluno_minhas_requisicoes.html` (list) | yes | ladder replaced; missing Parcialmente branch added |
| `admin_matrizes.html` (list) | yes | pasted Requisições ladder replaced |
| `admin_detalhes_requisicao.html` | no — plain text | untouched |
| `admin_processar_requisicao.html` | no — plain text | untouched |
| `aluno_requisicao_detalhe.html` | no — plain text | untouched |
| `aluno_dashboard.html` (Requisições Recentes) | no — `list_table.html` plain cells | untouched |
| `admin_matriz_form.html` | no — `<select>` options | untouched |
| `admin_editar_aluno.html` matrix selector | no — `"Nome \| Vigente"` option text | untouched |
| `admin_catalogo_versao_detalhe/_form.html` | yes, but **atividade_versao** lifecycle | out of scope, untouched |
| `admin_reportes.html` | yes, but **reportes** domain | out of scope, untouched |

**No colour was added.** `static/css/**` is byte-unchanged by this task. The
mapper holds no literal; the pill markup holds none; the tones resolve to the
`.badge.status-pill.status-*` variants that already existed.

One shared-macro change: `templates/components/card_list.html` no longer
defaults a *status pill* to the legacy `badge success` class. That legacy
family (`.badge.success/.warning/.danger`) is an older colour vocabulary that
`.badge.status-pill` fully overrides, so defaulting to it only pretended to say
something — and on the matriz list the markup literally claimed `success` while
painting neutral. Every other caller passes `badge_type` explicitly and is
byte-unchanged; the four inert `success`/`warning`/`danger` classes were also
dropped from the aluno pills, where they had begun to contradict the tone.

**Residual, recorded not actioned.** The aluno list renders five of its six
status labels through `user_message(...)`, which makes them administrator-
editable catalog entries. `Deferida Parcialmente` is rendered from the shared
mapper instead, because adding a sixth `user_message()` literal is a governed
catalog addition (8 coordinated edits across the baseline support and three
reconstruction sites) and is out of scope for a presentation-mapping task. The
message catalog is 587 keys before and after, digest unchanged.

### §UI-B05 — Cursos detail page

| | |
|---|---|
| Route | `GET /admin/cursos/<int:curso_id>` (`/visualizar` 302s into it) |
| View | `admin_detalhes_curso`, `app/views/admin/alunos_turmas_cursos.py` — **unchanged** |
| Template | `templates/admin_detalhes_curso.html` |
| Reference | `templates/admin_detalhes_turma.html` — chosen by the user |

**The band, mapped.** `h1.main-title` (raw global `margin-bottom:48px`) →
`section.content-block` (`--surface` · `1px --border-strong` · `--radius` ·
`padding:16px` · `--shadow-md`, no height set) → `div.content-block-body`
(`flex; wrap; justify-content:space-between`) → the list → a stranded
`a.btn ← Voltar`. `.content-block` is the dashboard summary card; every other
card built from it carries a `.content-block-header` naming it. Used without
one, on a full `.app-track`, it is untitled chrome with its contents pinned to
the left/centre/right page edges. No gradient, no nested card, no duplicated
detail-header styling, no toolbar misuse — checked, none present.

**First attempt rejected by the user.** Retiring the card but keeping
`.content-block-body`'s `.item` vocabulary left the values as unframed text
between the header and the list, and was worse than the original. Recorded so it
is not retried. The failure mode behind it: no browser automation exists in this
environment (Playwright/Selenium absent), so a layout decision was reasoned from
CSS instead of looked at. **Do not ship a layout change here without a human
look.**

**What shipped.** The Turma detail treatment, promoted to shared CSS:

| | |
|---|---|
| Header | shared `detail_header(curso.nome, url_for('admin_cursos'), 'Voltar')` — title left, Back right on one line, as Turma's topbar renders it |
| Strip | new `.detail-meta-strip` / `.detail-meta-block` / `.detail-meta-label` / `.detail-meta-value` in `modern-style.css`: no fill, border, radius, shadow or padding; 11px secondary label above a 600-weight value; 5px label/value gap (Turma's); flex, wrapping, reading from the left |
| Fields | `Código · Duração · Turmas · Alunos · Status`, status still a pill |

Turma keeps its own copy in a page `<style>` block as a 9-column grid tuned to
its nine fields; that grid is not reusable, so the same treatment is expressed
here as a flex strip. Turma's template was **not** touched — it is an accepted
surface.

`Turmas` and `Alunos` were added on the user's instruction ("pode colocar
informações como o número de turmas se ficar faltando"). Both are computed in
the template from the `turmas` rows the view already passes — no query, no view
change — and both labels already exist in the Cursos **list** column header, so
no new wording was invented.

**Not measured in a browser** — same limitation as UI-A03. The width behaviour
is the shared `@container track (max-width:480px)` header contract plus
`flex-wrap` and `text-overflow:ellipsis` on the strip; the visual pass is the
acceptance step.

**Final shape, after user direction (2026-09-21).** The strip above repaired
`/admin/cursos/<id>`, but the user then set the actual requirement: **`Ver` must
open the edit form with the edit taken away** — the pattern `admin_editar_atividade`
(`?view=1`) and `admin_catalogo_versao_form` already use.

| | |
|---|---|
| Ver | `/admin/cursos/<id>/editar?view=1` — one template, both modes |
| Read-only paint | `<fieldset class="form-fieldset" disabled aria-readonly="true">`, which is what `components/form.css` keys its READ-ONLY REGION contract on (UI-B10) → `--field-readonly-bg` on the field cards. No page-local colour. |
| View footer | none — `{% if not readonly %}`; the page-level Back lives in `detail_header` |
| Edit footer | `<div class="form-actions center">` — it was a bare `.form-actions`; every accepted form uses the `center` modifier |
| List action | `admin_cursos.html` Ver → `admin_editar_curso` + `{ view: 1 }`, the idiom Alunos/Atividades/turma-detail already use |

Three further defects found in the turmas list on the same page and repaired:
`--imp-cols` had a fixed px maximum on all four tracks (396px of grid inside a
`width:100%` card, so the columns bunched left); `Status` sat in column 2 while
every other SGAA list ends with it; and `Ano/Semestre` read `t.semestre` /
`t.ano`, which the `turmas` table does not have (`semestre_inicio` /
`ano_inicio`), so every row rendered an em dash.

**Loose end, deliberately not actioned.** With `Ver` retargeted, nothing in the
UI links to `admin_detalhes_curso` (`/admin/cursos/<id>`) or
`admin_visualizar_curso` (`/admin/cursos/<id>/visualizar`) any more. Both routes
still work. They were **not** removed or redirected because
`admin_visualizar_curso`'s body is AST-frozen against the extraction baseline by
`test_moved_handler_and_helper_bodies_ast_equivalent_to_baseline` (it is in
`MOVED_SYMBOLS` and in none of the change-allowlists). Retiring that surface is a
governed decision, not a presentation repair.

### §UI-B06 — Novo acesso button typography

Surface: Admin > Acesso, `templates/admin_acesso.html:332`.

```html
<button class="btn btn-nova-alinhado" type="button" id="btn-acesso-adicionar">
  <svg … class="btn-icon btn-icon-plus icon icon-tabler icons-tabler-outline icon-tabler-plus">…</svg>
  <span class="btn-label">{{ user_message("Novo acesso") }}</span>
</button>
```

**Resolved comparison** against `Novo reporte` (`btn primary btn--raised`) and
against the eight anchor CTAs. Both live under `.toolbar > .actions`, so the
descendant rule reaches both.

| Property | Novo acesso | Reference CTAs | Winning selector | Agreed? |
|---|---|---|---|---|
| font-family | **UA form-control font** | **`--font-sans`** on the 8 anchors | *nothing* — `.btn` did not declare it | **NO** |
| font-size | 13px | 13px | `.toolbar .actions .btn` (list-cards.css) over `.btn` | yes |
| font-weight | 400 | 400 | `.btn` | yes |
| line-height | 1 | 1 | `.btn` | yes |
| letter-spacing | normal | normal | none exists on any button | yes |
| text-transform | none | none | none exists on any button | yes |
| height | 30px | 30px | `.toolbar .actions .btn` | yes |
| padding | 0 10px | 0 10px | `.btn` | yes |
| gap | 2px | 2px | `.btn` | yes |
| icon box | 15×15, 4px right | 15×15, 4px right | `.btn .btn-icon` / `.btn .lucide` | yes |
| background | `--add-blue` | `--add-blue` | `.btn:has(.btn-icon-plus)` / `.btn:has(.lucide[data-lucide="plus"])` | yes |

**Population, which decides what "authoritative" means here.** The list-CTA
treatment is `btn btn-nova-alinhado` + the inline Tabler plus on **11**
templates. `btn primary btn--raised` + a Lucide plus exists on exactly **one**,
`admin_reportes.html`. So `Novo acesso` already carries the majority contract;
Reportes is the outlier. Recorded, not actioned — that page is UI-A02's and §7
put it out of scope.

**Two differences that are real but not typography**, deliberately left alone:
`btn--raised` gives Reportes a `box-shadow:0 1px 0` no other list CTA has, and
`.btn-nova-alinhado` zeroes the optical nudges (`--btn-text-nudge-y:0.5px`,
`--btn-icon-nudge-y:-0.75px`) that every other button keeps. Both are shared
decisions with their own owners.

**No page-local override existed.** `admin_acesso.html`'s `<style>` block
touches `.access-toolbar-actions` (flex/gap) and `.access-actions-shell
.btn[disabled]` (opacity) — the CTA is a sibling of that shell, not inside it —
and nothing in it names a typography property for a button.

**Not measured in a browser.** No Playwright/Selenium here, so the comparison
above is a cascade resolution from the shipped stylesheets and the rendered
markup, with the winning selector named for every row. The visual pass is the
acceptance step.

### §UI-B07 — provider-card symmetry and the backup action

Reopens UI-A03. The height contract shipped for UI-A03 was correct and is
untouched; what the user saw was a **semantic** asymmetry above it.

#### The Google-only line — what it actually was

| Rendered line | Template source | Context key | Underlying state | Kind |
|---|---|---|---|---|
| account e-mail | `.db-provider-line` | `google_drive_account_email` / `onedrive_account_email` | `cloud_accounts.account_email` of the active connection | E. connected identity |
| folder path | `.db-provider-line` + `data-lucide="folder"` | `google_folder_label` / `onedrive_folder_label` | `_get_cloud_drive_folder_setting(conn, provider)`, falling back to `drive_settings.<prefix>_dest_folder` | B. folder selection — the live destination |
| `Credenciais do aplicativo: …` | `.db-provider-line.is-muted` | `gdrive_config_source` / `onedrive_config_source` | `cloud_config.get_application_credential_status(provider)["source"]` → `MACHINE_LOCAL_DPAPI` / `ENVIRONMENT` / `ABSENT` | A. credential storage custody |
| ~~`Seleção de pasta: …`~~ **(removed)** | `.db-provider-line.is-muted` | `google_picker_config_source` | `cloud_config.get_google_picker_config()["source"]` | A again — custody of the **same** record |

`get_google_picker_config()` calls `_stored_provider("google")`, which is the
same single dict that holds `client_id` and `client_secret`. `stored_configured`
is `all(...)` over `client_id`, `picker_api_key`, `app_id` — the same DPAPI blob,
the same custody, the same sentence. The row was implementation detail about
where two extra Google values are kept, restated verbatim one line below the row
that already says it.

#### Why OneDrive never had it

Not an omission. The two providers implement folder selection differently:

- **Google** uses the client-side **Google Picker**, which needs two credentials
  of its own — `picker_api_key` and `app_id` — beyond the OAuth pair.
- **OneDrive** uses a server-side browser, `GET /admin/backup/cloud-folders/onedrive`
  → `app.cloud_connections` → `list_onedrive_folders_with_access_token`, driven by
  the OAuth access token the card already reports. There is no second credential,
  so there is no second custody state to print.

#### Resolution — Case B (with a Case C treatment for the failure)

Case B for the row: removed from Google rather than invented for OneDrive. Both
`.db-provider-meta` blocks are now exactly three rows with identical classes, so
neither card reaches the common action area a row before the other.

Case C for what is genuinely provider-specific: when the Picker credentials are
missing, `Seleção de pasta indisponível: …` must still be shown, because
"Selecionar pasta" really is unusable. That is an actionable problem state, not
metadata, so it now renders in the state-driven note region the two cards already
share with `Último upload` / `Falha`:

```html
<p class="db-provider-note is-warning" data-google-picker-missing>…</p>
```

`.db-provider-note.is-warning` was folded into the card's existing
`.db-provider-line.is-warning` declaration — one colour, no new token.

#### The backup action

`Enviar backup agora` left `.db-provider-actions > .db-provider-primary` (now
deleted, CSS included) and joined `.db-provider-config-footer` inside a new
`.db-provider-footer-actions` group, before `Salvar`. It still POSTs to
`/admin/backup/{google,onedrive}/upload`; because HTML forms cannot nest, the
POST target is emitted once per card as a control-only
`<form class="db-provider-post-target">` (`display:none`, not a layout
participant) and the button binds to it with the HTML `form` attribute. Method,
action, CSRF, icon, label and the connected/disconnected disabled variants are
unchanged. Both call sites go through one macro pair, so the action cannot drift
between providers, and exactly one renders per provider.

`margin-left:auto` moved from `.db-provider-config-footer .btn` to the new group
— with two buttons the old per-button rule would have split them apart.

#### Alignment

Unchanged from UI-A03 and re-asserted by the new tests: `.db-provider-card` is a
flex column with no `justify-content`; `.db-provider-config{flex:1 1 auto}` is
the only block that absorbs surplus; `.db-provider-config-footer{margin-top:auto}`
pins the divider/toggle/buttons. `APP_PUBLIC_BASE_URL` is still the first
configuration field on both cards. OneDrive has one field fewer, so its spare
height sits between its last field and the footer — nowhere else.

**Not measured in a browser.** Same limitation as UI-A03: no Playwright here, so
row counts, region order and the CSS contract are asserted structurally and the
pixel comparison is the acceptance step.

#### The Operações strip — delivered

The generic `Gerar backup agora` is a different action family from the provider
cards' `Enviar backup agora`, and it was the originally reported UI-B07 defect:
it sat on the card's explanatory row, pinned right by `.db-card-lead`.

It now sits at the bottom of the whole Operações surface. **No footer style was
invented** — this page already owns one, accepted on two other cards here:

```css
.db-card form > .db-actions{ justify-content:flex-end;
                             padding-top:10px;
                             border-top:1px solid #edf2f7; }
```

so the markup is the same shape `Destinos de backup` and `Política de retenção`
already use: a `.db-actions` row as the last child of a card form. Rendered
order is now head → lead paragraph → `Recuperar banco de dados` → footer action.

`.db-card-lead` had exactly one consumer — that row — so the wrapper and its
three rules were removed rather than left holding a single paragraph. The
paragraph is now ordinary body copy and flows the full card width; nothing empty
was left on the right.

Placement only: `POST /admin/banco-dados/backup`, the CSRF input, the
`{% if auth_can('banco_dados', 'edit') %}` gate, the `database` icon and the
label are the same bytes that used to sit on the lead row. The server-side
permission (`admin_banco_dados_backup` → `banco_dados:edit`, `app/auth.py:357`)
is asserted unchanged by the tests.

### §UI-B08 — access/onboarding status column

One concise pill in a final column, covering concepts such as: pending / not yet
delivered, access e-mail delivered, active, revoked — and any other state only
if genuinely necessary.

Constraints:

- Preferably one word per pill.
- Do not pile multiple badges into the row.
- Do **not** infer "Disponibilizado" merely because a token exists — state must
  rest on durable authoritative evidence.
- Avoid confusing access state "Ativo" with the academic aluno status "Ativo".
- **First map what durable data currently exists**, then define final labels.

Labels discussed but explicitly **not** final: `Pendente`, `Disponibilizado`,
`Ativo`, `Revogado`.

**Resolved 2026-09-21 (v10).**

#### Durable evidence inventory

| Source | Durable? | What it can prove |
|---|---|---|
| `usuario_credenciais.acesso_ativo` (v9) | yes | may this account authenticate at all |
| `usuario_credenciais.estado` | yes | `personal` = an individual password exists; `default` = none |
| `usuario_credenciais.auth_version` | yes | session invalidation counter — no onboarding meaning |
| `senha_tokens.purpose` | yes | `first_access` vs `password_reset` |
| `senha_tokens.created_at` | yes | a token was **issued**. NOT that anything was sent |
| `senha_tokens.expires_at` | yes | whether the link is still inside its TTL (first access: 72 h) |
| `senha_tokens.consumed_at` | yes | the link was used to install a password |
| `senha_tokens.invalidated_at` | yes | superseded / cancelled / a **definite** send failure |
| `senha_tokens.sent_at` (**new, v10**) | yes | the provider **confirmed** the send |
| `email_envios.status` (`sent`/`failed`/`indeterminate`) | yes, but | the **requisição/preset** outbox, keyed `aluno_id` → `alunos`. Password mail never passes through it |
| `PasswordMailOutcome` (`sent`/`indeterminate`/`failed`/`unavailable`) | **no** | a return value; gone at the end of the request |
| `logger` lines `password_mail_sent` / `_indeterminate` / `_failed` | **no** | log text, not queryable state |
| flash messages | **no** | transient, session-scoped |

#### Could v9 prove a successful send? No.

Only two of the four outcomes left a trace. `unavailable` returns before issuing
a token, and `failed` invalidates the token it just issued — but **`sent` and
`indeterminate` were indistinguishable**: both left a live, unconsumed,
un-invalidated token and differed only in a log line. Presenting that as
delivery would claim something SGAA does not know, which is precisely what the
requirement forbids.

#### Transition table

| # | Event | Durable delta | State |
|---|---|---|---|
| A | account created, blank password | `estado=default`, no token | `Pendente` |
| B | `Enviar acesso`, provider confirms | token + `sent_at` | `Disponibilizado` |
| C | `Enviar acesso`, definite failure | token + `invalidated_at`, no `sent_at` | `Pendente` |
| D | `Enviar acesso`, indeterminate | live token, **no `sent_at`** | `Pendente` |
| E | user completes first access | `consumed_at`, `estado=personal` | `Ativo` |
| F | admin sets an explicit password | `estado=personal`, no token needed | `Ativo` |
| G | `Excluir acesso` (revoke) | `acesso_ativo=0` | `Revogado` |
| H | reactivate **with** a password | `estado=personal`, `acesso_ativo=1` | `Ativo` |
| H'| reactivate **without** one | `estado=default`, prior tokens still invalid | `Pendente`, or `Expirado` if a confirmed delivery had been killed |
| I | resend | a second `sent_at` row; newest by `(sent_at, id)` decides | `Disponibilizado` |
| J | confirmed delivery, TTL elapsed | `sent_at` + `expires_at <= now` | `Expirado` |
| K | `Aplicar senha padrão` on an onboarded account | `estado=default`, old token stays `consumed_at` | `Pendente` (a delivery was *used*; no link died) |
| L | password-reset mail to an `Ativo` account | `sent_at` on a `password_reset` token | `Ativo` (only `first_access` is onboarding) |

#### Status / action coherence

`emailActionLabel` and the derivation both key on `usuario_credenciais.estado`,
so they are structurally unable to disagree: the three pre-onboarding states
(`Pendente`, `Disponibilizado`, `Expirado`) all offer `Enviar acesso`, and
`Ativo` offers `Redefinir por e-mail`. `admin_acesso_senha_por_email` already
refuses a revoked access outright, and the active list excludes it, so nothing
offers to e-mail a `Revogado` account as though it were live. Root shows its
truthful state with one pill, no revoke/delete affordance, and no master-key
vocabulary reaches the page. The action bar was not redesigned.

#### What this does not claim

A confirmed send means SGAA handed the message to the provider successfully. It
is **not** a read receipt, and no state asserts the recipient opened anything.

#### Geometry round (2026-09-21) — and the global DS rule it produced

The state model was accepted; the column's geometry was not. Two defects, one
root cause each:

* **too wide / drifting left** — the track shipped as `minmax(150px, 0.9fr)`.
  The `0.9fr` made it *flexible*, so it absorbed leftover row width instead of
  letting the descriptive columns have it, and the `150px` floor was a guess
  about a font rather than a measurement of the content.
* **left-aligned pills** — the cell was passed `'class':'left'` and the page
  carried `.imp-acesso .impresso-card .cell:nth-child(6){ justify-content:
  flex-start }`.

The user promoted the fix to an **objective Design-System rule**, now recorded
in `docs/design-system/README.md` §2.6b:

> **STATUS COLUMN IN TABLES** — last data column; rightmost; centred header and
> values; intrinsic width sized to the largest supported pill; descriptive
> columns absorb the remaining space; actions are separate.

Implemented once, in the shared geometry owner `components/list-cards.css`:

| Piece | What it is |
|---|---|
| `--imp-status-col` | the track. First shipped as `max-content`; **corrected by the width round below** to a stable domain-derived length |
| `.cell.status-col` | alignment. `(0,4,0)` and declared after every `.imp-*` block, so it beats both the broad `justify-content:flex-start` rules and an equally specific `:nth-child()` — **no `!important`, no per-list nth-child rule** |
| ~~`--imp-status-col-reserve: 120px`~~ | **retired by the width round below** — a second, unexplained notion of the same column's width |

`.imp-acesso` now reads `… minmax(160px, 1fr) var(--imp-status-col)` with
`--imp-list-min-width: calc(966px + var(--imp-col-gap) + var(--imp-status-col))`.
The five descriptive minima (180/220/180/160/160) are untouched and keep every
`fr` on the row. The page declares no status-column width or alignment at all.

One pre-existing governance test,
`test_matrix_list_geometry.py::test_every_scrollable_card_grid_owns_its_complete_responsive_width`,
pinned `--imp-list-min-width` as a literal `\d+px`. It was pinning a *syntax*
where it meant a *requirement* — a grid with an intrinsic track cannot express
its threshold any other way — so the regex now also accepts `calc(…)`. The
"every scope must declare its threshold" force is unchanged.

**Audit, deliberately not migrated.** Nine further lists carry a status pill
and predate this contract, each still centring via per-list `nth-child` rules:
`admin_alunos` (its pill is `left`-aligned — the one outright violation of the
new rule), `admin_cursos`, `admin_turmas`, `admin_matrizes`,
`admin_detalhes_curso`, `admin_detalhes_turma`, `admin_requisicoes`, plus
`admin_reportes` and `admin_catalogo_versao_detalhe` where Status is **not** the
last column. Each is a visible change needing its own acceptance.

Tests: `tests/test_status_column_geometry_ui_b08.py` (15). Semantics stay in
`tests/test_access_onboarding_status_ui_b08.py`, which handed its three
geometry assertions over to the new file.

#### Width correction round (2026-09-21) — largest SUPPORTED, not largest rendered

The alignment repair was accepted; the sizing was **not**, and the failure was
mine. The rule said *largest **supported** pill*; `max-content` sizes to the
largest **rendered** one. I then wrote the gap up as an accepted trade-off rather
than an unmet requirement.

Corrected, still one shared mechanism in `components/list-cards.css`:

```
--imp-status-col = chars x 1ch x (pill font-size / grid font-size) + chrome
```

| Term | Value | Source |
|---|---|---|
| `--imp-status-col-chars` | `15` on `.imp-acesso`; file default `21` | character count of the **domain's longest supported label**. The only value a list supplies, and it is semantic — not a width |
| `--imp-status-col-font-scale` | `calc(11 / 14)` | `ch` resolves at the grid box's `--font-size-base` (14px); the text is the pill's (11px). **Omitting this made the first fixed attempt ~148px — wider than the 150px it replaced.** CSS cannot divide lengths, so it is unitless |
| `--imp-status-col-chrome` | `28px` | pill padding 12 + border 2 + dot 5 + gap 5, plus `.cell` padding 4. Read off the two owners |

Acesso reserves ~122px where the longest pill needs 103–109px against the
installed UI font: 13–20px of no-clip allowance, and **28px narrower than the
rejected 150px**. Stable by construction — nothing in the calc consults the rows.

`max-content`, `min-content`, `fit-content`, `auto` and `fr` are now explicitly
forbidden on the track and asserted against.

**The 120px reserve is retired.** `--imp-list-min-width` reuses
`var(--imp-status-col)` directly, so one column has exactly one width; a test
fails if the second token ever returns.

Every number is pinned to its real source by test, so none can drift: the
character count against `ACCESS_STATUS_TONES`, the chrome against the pill and
cell rules, the font scale against the two declared font sizes, and the file
default against the longest label in any SGAA status domain.

Tests: `tests/test_status_column_geometry_ui_b08.py` (22, up from 15) — including
a page forced to contain only `Ativo` that still reserves `Disponibilizado`, and
a same-page before/after proving the geometry is byte-identical once longer
statuses appear.

### §UI-B10 — read-only colour tokenization on Ver versão

Surface: Admin > Atividades > atividade > **Ver versão**.

Forbidden approaches, as stated by the user:

- page-local gray values;
- new hex/rgb colours;
- a "version readonly" colour;
- visually approximating the existing token;
- changing field semantics only to obtain the desired colour.

**Lead already on record (not a solution, and not investigated further).** During
the Requisições read-only normalization (UI-H03) this surface was inspected and
deliberately left alone. `templates/admin_catalogo_versao_form.html:79` declares
non-editability on the **fieldset**:

```html
<fieldset class="form-fieldset" {% if readonly %}disabled aria-readonly="true"{% endif %}>
```

The DS read-only rule added by UI-H03 keys on the **control**
(`.field-card .control:disabled[aria-readonly="true"]`, `components/form.css`).
Controls inside a disabled fieldset are disabled by inheritance but carry no
`aria-readonly` of their own, so they do not match that rule and fall through to
the "not applicable" disabled paint — `--field-disabled-bg`, a dead border and
`--text-tertiary` — which is darker than the read-only paint
(`--field-readonly-bg` / `--text-secondary`). That is consistent with the
reported symptom, but it has **not** been confirmed as the whole cause, and the
fix direction (reconcile the DS vs. move the marker) is an open decision for
whoever picks this up. The page also carries a local
`.form-fieldset[disabled]{ opacity:1 }`.

The same fieldset pattern exists in `templates/admin_editar_atividade.html`, so
any reconciliation should check that consumer too.

**Resolved 2026-09-21.** The lead above was confirmed as the *whole* cause by
cascade analysis — there was no second contributor. Consumer audit, the full
population of both patterns:

| Consumer | Pattern | Classification | Effect of the fix |
|---|---|---|---|
| `admin_catalogo_versao_form.html` | `fieldset[disabled][aria-readonly]` | READ_ONLY_VIEW | repainted (the reported surface) |
| `admin_editar_atividade.html` (`?view=1`) | `fieldset[disabled][aria-readonly]` | READ_ONLY_VIEW | repainted (same defect, same repair) |
| `admin_matriz_form.html` | control-level `disabled aria-readonly` / bare `aria-readonly` | READ_ONLY_VIEW | untouched — already UI-H03 |
| `admin_requisicoes.html` | control-level, set by JS | READ_ONLY_VIEW | untouched — already UI-H03 |
| `admin_editar_aluno.html` (Ver Aluno) | `readonly aria-readonly` inputs | READ_ONLY_VIEW | untouched — the reference paint |
| `aluno_nova_requisicao.html`, `aluno_meus_dados.html` | control-level `readonly` | READ_ONLY_VIEW | untouched |
| `tipo_locked` select in *editable* versão/atividade mode | own `disabled`, no region | TRULY_DISABLED | untouched — still `--field-disabled-bg` / `--text-tertiary` |

Only two templates in the repository carry a `<fieldset>` at all, and both gate
the markers on `{% if readonly %}`, so the region rule cannot reach an editable
form. `fieldset[disabled]` **alone** is deliberately not a trigger: a disabled
fieldset with no `aria-readonly` still means "not applicable" and still looks
it, exactly like a disabled control without the marker.

One consequence worth stating: inside a declared read-only region a control's
own `disabled` attribute no longer buys a darker paint. That is the intended
reading — in a view there is no second kind of non-editability, and whether a
field applies is carried by its value (`Nenhuma`, `Sem sugestão`, `NA`, empty),
not by a shade. The same page in edit mode keeps the distinction intact.

The page-local `.is-off-chunk{opacity:.55}` is cancelled inside the region on
both templates: it is an *editing* affordance ("waiting on the other half"),
and in a view it only left one half of a compound card lighter than the other —
the same one-state-two-treatments defect expressed with opacity instead of a
token. `pointer-events:none` is kept.


### §UI-B15 — console, CSP and form semantics on Admin > Acesso

**Rule applied throughout: a console message is a symptom, not a specification.**
Each of the five was traced to an owner before anything was edited, and three of
them turned out not to be SGAA defects at all.

#### The five messages, and what each one actually was

| # | Console message | Owner | Verdict |
|---|---|---|---|
| 1 | `use.typekit.net` font refused by `font-src` | none — not in this repository | **Not ours.** CSP working. No change |
| 2 | "Multiple forms should be contained in their own form elements" on `/admin/acesso/senhas-default` | `templates/admin_acesso.html` | **Not a form-ownership defect.** Password-manager heuristic. Semantics declared, structure kept |
| 3 | `#access-email` has no `autocomplete` | `templates/admin_acesso.html` | **Real gap.** Fixed |
| 4 | `#access-password-form` has no username field | `templates/admin_acesso.html` | **Real gap.** Fixed |
| 5 | `https://unpkg.com/lucide.min.js.map` refused by `connect-src` | the CDN bundle | **DevTools-only, and removable.** Fixed at the asset; CSP got *narrower* |

#### 1 — Typekit: the request chain, traced to its absence

The brief's first question was the right one: *why* is SGAA asking for
`use.typekit.net`? It is not. Searched: templates, page-local `<style>` blocks,
every file under `static/css/` for `@import` and `@font-face` (**there are none
of either**), linked stylesheets, vendored libraries, inline styles. Zero
matches for `typekit` anywhere in `templates/` or `static/`.

The rendered `/admin/acesso` names exactly three external hosts:

| Host | Why | Allowed by |
|---|---|---|
| `fonts.googleapis.com` | the Inter stylesheet (`base.html`) | `style-src` |
| `fonts.gstatic.com` | the font files that stylesheet points at | `font-src` |
| `www.w3.org` | SVG `xmlns`, a namespace identifier — never fetched | n/a |

So the font request has no origin inside the application and `font-src` is
refusing it correctly. **`use.typekit.net` was not added to the policy.** Two
tests hold this shut from both ends: one enumerates every external host the page
names, the other pins `font-src` to its exact three sources.

Font authority is unchanged and was re-checked: `--font-sans` (Inter) in
`static/css/foundation/tokens.css`, reaching buttons, inputs, selects and modal
content through `font:inherit` / the UI-B06 `font-family:inherit` on `.btn`. No
second family was introduced, and no font file was bundled to silence CSP.

#### 2 — "Multiple forms": the DOM was audited before anything was edited

Every structural cause the brief lists was checked against the **rendered** DOM,
not the template:

| Suspected cause | Finding |
|---|---|
| nested `<form>` | none — three forms, all siblings, parser nesting depth 1 |
| malformed closing tags | none — every open tag matched, no stray `</form>` |
| controls belonging to another action | none — each form carries only its own fields *and* its own `csrf_token` |
| buttons submitting an unintended ancestor | none — the two modal Saves sit in `.modal-footer` outside their form and bind with the HTML `form=` attribute, i.e. **explicit** ownership |
| hidden/provider form inside another | none — the JS `submitPost()` helper appends its throwaway form to `document.body` |

The panel is also genuinely **one** server action: a single POST to
`admin_acesso_salvar_senhas_default` persists the five configured defaults and
the activation switch together. Splitting it into five forms would satisfy
Chrome and destroy the one Save the brief ordered preserved — so it was not
done, and a test pins the panel at *five password fields, one switch, one
submit* to stop a later "fix" from doing it.

What the message really reports is Chrome's password-manager parser: five
`<input type="password">` with five different names and no account identity
cannot be mapped onto a single credential form, so the heuristic pass splits
them. The repair is therefore semantic, not structural — see below.

#### 3, 4 and the autocomplete audit

| Field | Before | After | Why |
|---|---|---|---|
| `#access-email` | *(none)* | `username` | It is the login identity: `admin_acesso_salvar` writes `usuarios.email` and `/login` authenticates on it. `off` was rejected — it would silence the warning by lying about the field |
| `#access-password` (create/edit) | `new-password` | unchanged | Already correct: an administrator **sets** a credential, never autofills one |
| `#access-password-new-value` | `new-password` | unchanged | Already correct: replacing a credential |
| the five `default_*` | `off` | `new-password` | Values the form **sets**. Same token `admin_banco_dados.html` already uses for masked configuration secrets (`client_secret`, `picker_api_key`), and strictly more specific than `off`, which left classification to the heuristics that split the form |
| `#access-password-username` | *(did not exist)* | `username`, hidden, readonly, **no `name`** | The identity Chrome asks a password form to carry |

The new identity field is the delicate one:

- **Hidden and readonly** because the dialog must not grow a visible field —
  modal geometry is explicitly out of scope, and the selection is already named
  in `#access-password-selection-count`.
- **No `name` attribute, deliberately.** The value is a browser hint. The real
  request body is hand-built in the submit handler (`usuario_ids`, `nova_senha`,
  `csrf_token`), so the field must be incapable of reaching
  `admin_acesso_definir_senha` even if the form were ever submitted natively.
  Chrome identifies fields by `name` **or** `id`; the `id` suffices.
- **Never invented.** `openPasswordModal()` fills it from the selected row only
  when **exactly one** row is selected. A bulk selection has no single identity,
  so it stays empty rather than naming one of several accounts being changed. It
  is cleared again on close, so a dismissed dialog does not sit in the DOM
  holding somebody's e-mail.

#### 5 — the Lucide source map, fixed at the asset

`https://unpkg.com/lucide@latest` served a bundle ending in a `sourceMappingURL`
comment. DevTools resolves that relative to the script's URL, which is how the
request became `https://unpkg.com/lucide.min.js.map` — a file that is not
published at that path anyway. `connect-src` refused it.

A source map is never a runtime dependency, so the policy was not touched. The
**asset** was: SGAA now serves `static/vendor/lucide.min.js`, the same pinned
**v0.544.0** build the visual baseline already renders with
(`tests/visual/vendor/lucide.min.js`), with that single comment removed and a
provenance header added. A test compares the served body against the pinned one,
so "self-hosted" cannot quietly become "a different icon set". Icon behaviour is
untouched and Lucide was not replaced.

Two consequences worth stating plainly:

- **CSP got narrower, not wider.** `https://unpkg.com` was removed from
  `script-src` entirely. This is the only CSP edit in UI-B15 and it is a
  tightening.
- **Blast radius is the whole app, and that is the repair.** All three
  icon-loading templates moved together — `base.html`, `base_aluno.html`,
  `400.html` — because leaving one on the CDN would turn it into a blocked
  script. `@latest` also meant the icon library could change with no commit in
  this repo; it no longer can. The visual harness's unpkg interception is now
  dead and is kept, relabelled, as a regression net.

#### What was deliberately NOT done

- `use.typekit.net` **not** added to `font-src`.
- `unpkg.com` **not** added to `connect-src` for a source map.
- No wildcard, no bare `https:`, no `*.` source anywhere — asserted by test.
- No nonce/hash change.
- `autocomplete="off"` **not** used to silence any warning.
- No username invented for the senhas-default panel, and none persisted.
- No geometry, pill, table, card, colour, spacing, typography or
  button-placement change. UI-B14 (`select` radius) was recorded as `BACKLOG`
  and left alone.

#### Browser evidence, 2026-09-21 — what the console actually said

The first pass could not capture the console (no Playwright/Chromium here) and
said so. The user then ran the real browser. Five messages came back, and they
**corrected two of the first pass's answers**. Recorded honestly, because the
value of this row is the diagnosis, not the defence of it.

| Console message | First-pass answer | Verdict after the browser |
|---|---|---|
| `icon name "cloud-backup" was not found` | not seen at all | **Real product defect.** Fixed |
| "Password forms should have ... username fields" | fixed with a `hidden` field | **Fix failed.** `hidden` is not "optionally hidden". Re-fixed |
| "Multiple forms should be contained in their own form elements" | semantic declaration might clear it | **It did not.** Closed as a heuristic false positive, now with evidence |
| Typekit fonts refused | not ours | **Unchanged.** Re-proved from served bytes |
| `[Violation] Forced reflow ... 35ms` | not seen | **Out of scope by instruction** |

##### `cloud-backup` — the one genuine defect, and it predates UI-B15

`templates/base.html` rendered a `cloud`+`backup` compound name for the
`Backup de dados` sidebar link. It is **not in the Lucide registry** — not in
v0.544.0, and not on `@latest` either. So that sidebar entry has been rendering
**no glyph at all** for as long as the name has been there; self-hosting did
not break it, it only made the failure audible, because a bundle that is
present and complete reports the miss instead of failing silently behind a
blocked request.

Replacement is `database-backup`, chosen from the icons the repository already
uses successfully for this concept (`database` for the backup action on
`/admin/banco-dados`, `upload-cloud` for provider uploads). No SVG invented, no
version bump, no CDN, no CSP change.

All **39** `data-lucide` names rendered on `/admin/acesso` — markup *and* the
names the page's own script injects into the floating action bar and the modal
title — were then resolved against the shipped registry. `cloud-backup` was the
only miss. The registry is parsed directly out of the served file
(`a.icons=<var>` → `Object.freeze({...})`, 1861 entries, matching Node), so the
audit cannot drift from what the browser loads, and a second test sweeps the
entire template tree.

##### Why the hidden username field did not work

The first fix used the HTML `hidden` attribute. That resolves to
`display:none` in the UA stylesheet, so the element is **never rendered** — and
a field the layout does not produce is not a field the password manager can
associate. Chrome's "(optionally hidden)" means *visually* hidden, not removed
from rendering. The same disqualification applies to `type="hidden"`,
`display:none` and `visibility:hidden`.

It is now the shared `.sr-only` primitive promoted into `modern-style.css` (the
standard clip-rect pattern, already present verbatim but page-scoped as
`.progresso-type-menu-label`, which was **not** folded in — out of scope here).
The field is in the layout with a 1×1 clipped box, so the dialog's geometry and
the "do not visibly repeat the e-mail" constraint both hold. It keeps
`readonly`, gains `tabindex="-1"` so it cannot enter the dialog's tab order,
and `aria-hidden="true"` is safe only because of that. It is still **name-less**:
`admin_acesso_definir_senha` reads exactly `usuario_ids` and `nova_senha` and
ignores everything else (asserted by test), so a name would be harmless — having
none makes participation in a credential mutation impossible.

Selection semantics, unchanged in intent and now guarded three ways: one row
selected → that account's real e-mail; **bulk selection → empty**, because
several accounts have no unique username and naming one of N would be a false
statement to both the password manager and the administrator (the visible
`#access-password-selection-count` already says how many are affected); cleared
on close **and** whenever the selection moves underneath the dialog.

##### The five profile defaults: configuration secrets, not credentials

The follow-up brief asked the decisive question — *are these browser-manageable
user credentials, or application configuration secrets?* They are configuration
secrets. `Admin`, `Coordenador`, `Consultor`, `Usuário`, `Usuário teste` are
**profiles**, not login identities; there is no account behind any of them and
no username exists to declare.

`autocomplete="new-password"` was therefore wrong, and it cost twice: the
"Multiple forms" line survived it unchanged, **and** it told Chrome these were
account password-change fields, which is how this form — the one form on the
page that can never have an identity — began drawing the username warning too.
Reverted to `autocomplete="off"`, the accurate token for "do not autofill this
and do not offer to manage it". The inputs stay `type="password"`: the values
are genuinely secret and must be masked, and changing the type to hide them
from Chrome's parser would be tricking the browser at the user's expense.

##### "Multiple forms": closed as a heuristic false positive, with evidence

The warning survived `off` **and** `new-password`, which is what settles it.
The rendered structure is valid and the suite pins every part of that claim:
three sibling forms, parser nesting depth 1, every tag closed, no stray
`</form>`, every control owned by its own endpoint, explicit `form=` binding on
the two outside Saves, and one POST persisting all six values behind one Save.

There is no product model under which this becomes several forms: splitting it
would create five POSTs and destroy the accepted single-Save workflow. It is
recorded as a browser heuristic that mis-reads a settings surface carrying
several independent secrets. **Do not split this form to chase it.**

##### Typekit — re-proved from the served bytes

Four proofs, the last two new in this pass:

1. rendered HTML names no Typekit host (it names three external hosts total);
2. no file under `templates/` or `static/` contains the string;
3. **every CSS and JS asset the page links is fetched through the app and
   searched** — including the vendored Lucide and XLSX bundles, the only
   third-party code in the response — and none declares it;
4. no remote `<script src>` and no remote font origin beyond Google Fonts.

Nothing SGAA serves asks for Typekit. Source inspection **cannot** see resources
injected by a browser extension, so **final attribution requires re-testing in
incognito with extensions disabled**. Until that is done the message is
attributed to the browser profile, not to SGAA. No CSP change was made and none
is warranted.

##### Forced reflow (35ms) — reported, not touched

Per instruction, not investigated and not optimized. The trivially identifiable
candidates on this page are the two places that deliberately measure after
mutating: `positionFor()` in `admin_acesso.html`, which reads
`getBoundingClientRect()`, `offsetHeight`/`offsetWidth` and `getComputedStyle()`
on hover after writing `bar.style.top`, and the shared `openFixedMenu()` in
`toolbar-filters.js`, which measures the menu *after* revealing it in order to
clamp it (that measure-after-reveal is its documented contract). A single 35ms
report is not evidence of a user-facing defect. **If it becomes reproducible or
visibly janky, open a separate backlog item — it is not UI-B15.**

#### What still needs a browser to confirm

- `Backup de dados` shows a glyph, and no `icon name ... was not found` line.
- The password-form username warning is gone for `#access-password-form`.
- The username warning has **not** appeared on the senhas-default panel
  (the `off` revert is what should prevent it).
- Whether "Multiple forms" persists. **It is expected to.** If it does, it is
  the documented false positive — do not act on it.
- Typekit, re-run in incognito with extensions disabled, to attribute it.

---

### §UI-CP1 — credential model: explicit per-account default, true `pending`

**Accepted product direction, 2026-09-24.** The global "Ativar senhas padrão"
switch is rejected. Default passwords are an explicit per-account administrative
action; an account without a usable credential is `pending`.

#### Final model

| `estado` | Meaning | Password login |
|---|---|---|
| `pending` | account exists, no usable password credential | always refused, generically |
| `personal` | an individual password (user-chosen, or typed by an administrator for this account) | against the stored hash |
| `default` | an administrator explicitly applied the shared profile default to **this** account | against the stored hash — the value hashed at apply time |

`acesso_ativo = 0` refuses login before any of the above. Root keeps its
break-glass master key in every state; ordinary "Aplicar senha padrão" is refused
for root.

#### Retired switch — every reader and writer, classified

| Site | Kind | Before | After |
|---|---|---|---|
| `app/settings.py` `get_/save_default_passwords_enabled`, `DEFAULT_PASSWORDS_ENABLED_KEY` | accessor | live | **removed** |
| `app/views/core.py` `login` | authentication reader | `default` only while switch on | **removed** — state alone decides |
| `app/access_default_password.py` ladder rung 1 | eligibility reader | refused everything while off | **removed** — two rungs: root, revoked |
| `app/views/admin/acesso.py` `admin_acesso` | render reader | template flag | **removed** |
| `admin_acesso_salvar_senhas_default` | writer | saved the switch with the values | **removed** — Save is configuration only |
| `admin_acesso_salvar` (blank password) | creation reader | usable default hash when on | **removed** — `pending`, unusable hash |
| `_reactivate_usuario_access` (no password) | creation reader | usable default hash when on | **removed** — `pending` |
| `admin_acesso_resetar_senha` | action reader | flash-refused when off | **removed** |
| `app/db.py` `_app_settings_defaults` | seed writer | seeded `'1'` on every start | **removed** |
| `templates/admin_acesso.html` | UI | toggle + hidden `0`, JS const, two `disabled` attrs, help-text branch, CSS | **removed**, plus now-dead `levelLabels` |
| `app/prod1_password_foundation_v8.py` | frozen v8 migration writer | inserted `'1'` | kept (history) |
| `app/prod1_credential_pending_v11.py` | last reader | — | reads it once to classify, then **deletes the row** |
| password e-mail flows (`password_email.py`, `views/passwords.py`) | — | never read it | unchanged |

Two creation paths never read the switch but installed a **usable** shared
default unconditionally: `admin_adicionar_aluno` (blank password) and the batch
student import. Both now create `pending` accounts. Typing a password equal to
the default's text is an individual password (`personal`).

#### Canonical v10 census (read-only backup copy, 2026-09-24)

85 `usuarios` / 85 `usuario_credenciais`. Legacy switch `'0'` since
2026-09-20 21:13:43. Configured profile defaults equal the shipped ones.

| estado | acesso_ativo | tipo / nível | stored hash | auth_version | tokens | count |
|---|---|---|---|---|---|---|
| default | 1 | admin / admin_total (root, id 1) | = current profile default | 1 | none | 1 |
| default | 1 | aluno / usuario | = current profile default | 1 | none | 82 |
| personal | 1 | aluno / usuario (id 2) | happens to equal the `usuario` default | 2 | 1 consumed reset | 1 |
| personal | 1 | admin / administrativo (id 86) | equals another profile's default | 2 | 1 consumed first access | 1 |

No placeholder hash, no revoked row. `auth_version = 1` on all 83 `default`
rows proves none has been through "Aplicar senha padrão" since v8 (the action
bumps it). Because the switch is off, **none of the 83 can password-login
today**; root gets in only through the master key.

#### v10 → v11 mapping rule — authentication-preserving, durable evidence only

1. `personal` → `personal`.
2. `default` + `acesso_ativo = 0` → `pending` (revocation always installs an unusable hash).
3. `default` while the legacy switch is **off** → `pending` (v10 refused every one of them).
4. `default` while the switch is **on** (or the row is absent, read as on by v10) and the hash
   verifies against the account level's *current* profile default → `default`.
5. `default` while the switch is on and the hash does **not** verify → **migration refuses**
   (`LegacyCredentialClassificationError`, no mutation): an unusable placeholder and a
   since-edited default cannot be told apart.

No hash is rewritten and `auth_version` is not bumped: by construction no
account's authentication outcome changes, so there is no session to end.

**Projected canonical outcome:** `personal→personal` 2 · `default(switch_off)→pending` 83
(root + 82 alunos) · `default→default` 0 · refused 0. Root stays master-key-only,
exactly as today.

*Alternative considered and not adopted:* hash evidence alone (ignore the switch)
would map all 83 to `default` and silently hand an administrator-readable shared
password back to 82 aluno accounts that cannot use it today. Choosing it later
needs no schema change — only rule 3.

#### Schema v11 (`credential_pending`)

- `usuario_credenciais.estado CHECK(estado IN ('pending','default','personal'))`; column
  order, defaults and FK byte-identical to v9/v10. SQLite cannot alter a CHECK, so the
  migration stages rows in a TEMP table, recreates the canonical DDL under the real name
  and copies back `usuario_id`, `auth_version`, `atualizado_em`, `acesso_ativo` verbatim.
- Frozen digest `15cb8e68b915f99b6fb687596cd3b7f4158fb7901403fd55ece7abddd5d0bff5`;
  a migrated v10 equals a fresh v11 bootstrap. v10 keeps a frozen recognizer.
- In-transaction guards: credential snapshot re-checked after the write lock is taken,
  `usuarios.senha`, `senha_tokens` and every other `configuracoes_app` row unchanged,
  `integrity_check` ok, zero FK violations, head validation before COMMIT.
- Rollback (test-only, `tests/prod1_v11_support.py`): rebuild with the v9 DDL,
  `pending→default`, drop marker 11, restore the setting row → frozen v10 digest and a
  row-identical dump. Proven on a snapshot of canonical: 476 data statements identical;
  the only byte difference is whitespace inside the stored `CREATE TABLE` text, because
  canonical's `acesso_ativo` was spliced in by the v9 `ALTER` — the digest normalises it.

#### Transitions

| From → to | Trigger | auth_version | Tokens | Sessions |
|---|---|---|---|---|
| — → `pending` | create / reactivate without password; revoke | +1 on reactivate/revoke | all invalidated | ended |
| — → `personal` | create with an explicit password | 1 | — | — |
| `pending` → `personal` | first access completed | +1 | link consumed, others invalidated | user signs in fresh |
| `default` → `personal` | reset completed (first access is **refused** outside `pending`) | +1 | same | same |
| `personal` → `personal` | reset / Nova / admin edit with password | +1 | invalidated | ended (own session restamped) |
| `pending`/`personal` → `default` | "Aplicar senha padrão" | +1 | all invalidated | ended |
| `default` → `default` | "Aplicar senha padrão" again | +1 | all invalidated | ended; picks up the current profile value |

Saving the profile-default cards writes `configuracoes_acesso` only: no hash,
state or `auth_version` moves. An account reaches an edited value only when the
default is (re)applied to it.

#### Situação mapping (UI-B08 under v11)

| Credential | Pill |
|---|---|
| revoked | Revogado |
| `personal` | Ativo |
| `default` | **Ativo** — a deliberately applied, usable credential; no switch can take it away |
| `pending`, no confirmed first-access send | Pendente |
| `pending`, confirmed send, link usable | Disponibilizado |
| `pending`, confirmed send, link expired/invalidated | Expirado |
| `pending`, confirmed link consumed (credential later removed) | Pendente |

Coherent with the row action: `pending` → "Enviar acesso" (first-access link);
`personal`/`default` → "Redefinir por e-mail" (reset link).

**First access belongs to `pending` only (final review, 2026-09-24).** Redemption
checks `estado == 'pending'` inside the consuming write transaction
(`app.user_accounts.first_access_redeemable`), and the form refuses to render
otherwise. A first-access token that survives onto a `default` or `personal`
account -- stale history, migrated data, a writer that forgot to invalidate -- is
refused with the same page an unknown token gets: no write, no consumption, no
state leak. `password_reset` has no state precondition. "Aplicar senha padrão"
invalidates every outstanding first-access and reset token of the account.

#### Catalog

CP1 is ledger term 13, **−4**, no addition: the "Ative as senhas padrão antes de
aplicá-las a um acesso." flash and the three blank-password help texts that
promised the shared default retire. Surviving help texts were already catalogued.

## Changelog

- 2026-09-26 — **Root secrets moved out of source before publication.** The root address and
  the break-glass hash now come only from `APP_BOOTSTRAP_ADMIN_EMAIL` / `APP_ROOT_MASTER_KEY_HASH`
  (machine-local `.env`, git-ignored); tests use synthetic values. Local behaviour verified
  unchanged (root resolves to id 1, master key authenticates). Canonical custody pins updated
  to accept the authorised v11.

- 2026-09-26 — **UI-B20 / UI-B21 opened and implemented (working tree only).** Requisições: an
  empty comprovantes container no longer doubles the row-gap above Observação. Adicionar turma:
  the Alunos da turma header and content use `var(--surface)`; rows unchanged. Both
  `DONE_PENDING_VISUAL_CONFIRMATION`. **Correction (user):** the first pass reached only
  Adicionar turma. The student list is now the DS component `components/turma-alunos.css`,
  shared by Adicionar and Editar turma, with component tokens on `--surface` / `--bg`.

- 2026-09-26 — **UI-B16 / UI-B17 / UI-B18 / UI-B19 opened and implemented (working tree only).**
  Banco de dados card and provider footers, and Mensagens card footers, adopt the DS panel footer
  (full-bleed `1px solid var(--border-strong)`, `11px 16px`); standalone `select.control` takes
  `var(--radius)`; the Adicionar aluno "Foto" label is removed and its catalog key retired (ledger
  term 14, −1, 582 keys). All four `DONE_PENDING_VISUAL_CONFIRMATION`. UI-B14 stays `BACKLOG`.

- 2026-09-24 — **UI-CP1 → DONE (visually accepted).** Follow-up cleanup inside the same item:
  the "Senhas padrão" header/body/footer dropped `background:var(--bg-underpanel)`; the outer
  `.access-defaults-panel` now owns `background:var(--surface)`, so the block reads as one
  standard white surface. Second pass (user correction): the outer border and the header/footer
  dividers now use the DS panel border `1px solid var(--border-strong)` instead of the raw
  `0.5px solid rgba(0,0,0,0.08)` hairline. Padding, cards and behaviour unchanged. Guarded in `tests/test_admin_access_default_password_panel.py`. UI-B14 stays `BACKLOG`.

- 2026-09-24 — **UI-CP1 canonical v10→v11 migration (authorised).** Backup taken, canonical
  migrated once (83 → `pending`, 2 `personal` kept, 0 `default`, 0 refused), invariants and a
  bounded auth smoke verified, normal runtime restarted on 5000. UI-CP1 stays `IN_ACCEPTANCE`
  pending visual acceptance of Admin > Acesso.

- 2026-09-24 — **UI-CP1 final review correction.** The v10→v11 mapping and the
  UI-B08 mapping were approved as proposed. One defect rejected: a first-access link
  still redeemed on a `default` account. First access is now `pending`-only at the
  point of redemption (defence in depth, generic refusal), proven end-to-end over
  `/primeiro-acesso`; Apply Default's invalidation of both token purposes proven the
  same way. Canonical still v10 and byte-identical.

- 2026-09-24 — **UI-CP1 opened and implemented (working tree only).** Global
  "Ativar senhas padrão" switch retired; prod-1/v11 `credential_pending` adds a true
  `pending` state (table rebuild, authentication-preserving classification, refuses
  ambiguous legacy rows). Blank creation, reactivation, revocation, the aluno add form
  and the student import now yield `pending`; "Aplicar senha padrão" is the only route
  into `default`. UI-B09 ladder reduced to root → revoked; UI-B08 maps `default` to
  Ativo. Panel toggle, its CSS/JS and four catalogued messages removed. **Canonical
  `database.db` untouched (v10)**; migration proven on disposable copies only.
  UI-B13/B14/B15 not touched.

- 2026-09-21 — **UI-B08 width correction.** The alignment repair was accepted; the
  sizing was not, and the miss was mine: the rule said *largest **supported** pill* and
  `max-content` sizes to the largest **rendered** one, which I then documented as a
  trade-off instead of an unmet requirement. The track is now a stable computed length —
  `chars x 1ch x (pill font-size / grid font-size) + chrome` — so nothing in it consults
  the row population. `.imp-acesso` supplies one semantic value, `15`, the character
  count of `Disponibilizado`; a test pins it to `ACCESS_STATUS_TONES` so a longer state
  fails rather than truncating. The font-scale term is load-bearing: without it the
  reservation was ~148px, **wider than the 150px originally objected to**; with it Acesso
  reserves ~122px against 103–109px of real pill — 13–20px of no-clip allowance and 28px
  narrower than before. `max-content`/`min-content`/`fit-content`/`auto`/`fr` are now
  forbidden and asserted against. **`--imp-status-col-reserve:120px` is retired**:
  `--imp-list-min-width` reuses `var(--imp-status-col)`, so one column has one width, and
  a test fails if the second token returns. DS §2.6b rewritten to state the stability
  requirement explicitly. No DB migration, no runtime started, canonical left alone.
  Status semantics, labels, tones, transitions and row actions untouched. UI-B08 stays
  `DONE_PENDING_VISUAL_CONFIRMATION`. No other backlog item touched.

- 2026-09-21 — **UI-B08 geometry round.** The state model was accepted; the column
  was too wide, absorbed surplus width and left-aligned its pills. Cause:
  `minmax(150px, 0.9fr)` (flexible **and** a guessed floor) plus `'class':'left'`
  and a page-local `nth-child(6)` rule. The user promoted the fix to a **global
  Design-System rule** for any table with a semantic status column — last, rightmost,
  centred, intrinsically sized, descriptive columns absorb the rest, actions separate
  — now recorded in `docs/design-system/README.md` §2.6b and implemented once in
  `components/list-cards.css`: a shared `--imp-status-col` for the track and a
  shared `.cell.status-col` for alignment, `(0,4,0)` and last in the file so it needs
  no `!important` and no per-list `nth-child`. The scroll threshold is a self-documenting
  `calc()` that reuses the same shared token.
  No page-local status CSS remains on Acesso; the five descriptive minima and
  fractions are untouched. Nine other lists were **audited and left alone**
  (`admin_alunos` is the one outright violation — a `left`-aligned status pill), each
  needing its own visual acceptance. One governance regex in
  `test_matrix_list_geometry.py` was widened to accept `calc()` for
  `--imp-list-min-width`, because it pinned a syntax where it meant a requirement.
  Status semantics, v10 `sent_at`, labels, tones, transitions and row actions were not
  touched. UI-B08 stays `DONE_PENDING_VISUAL_CONFIRMATION`. No other backlog item
  touched.
  **Custody note, not caused by this task:** canonical `database.db` is now at **v10**.
  A `run.bat` launch at 17:01 migrated it, because startup bootstrap chains to the head.
  It validates as v10, digest matches the frozen signature, `integrity_check ok`, 85
  usuarios / 2 tokens / 0 confirmed sends. The additive column is reversible —
  `DROP COLUMN sent_at` + removing marker 10 restores the frozen v9 digest exactly,
  proved on a copy. There is no pre-v10 snapshot, because the migration happened via
  that launch rather than a governed step.

- 2026-09-21 — **UI-A03 → `DONE`** and **UI-B07 → `DONE`**: both visually accepted by
  the user. **UI-B08 implemented** and moved from §2 Backlog to §1 In acceptance
  (`DONE_PENDING_VISUAL_CONFIRMATION`). The durable-evidence inventory came first and
  it changed the task: v9 could not prove a successful send, because `sent` and
  `indeterminate` were byte-identical in the database — both left a live unconsumed
  `first_access` token and differed only in a log line — while `email_envios`, which
  does carry `sent`/`failed`/`indeterminate`, is the requisição/preset outbox keyed to
  `alunos` and password mail never touches it. So **prod-1/v10 `access_delivery`**
  landed: one nullable `senha_tokens.sent_at`, one writer
  (`mark_password_token_sent`), called only on the confirmed-send branch. Additive
  one-line `ALTER`, digest-identical to a fresh v10 bootstrap, **zero backfill** —
  accounts e-mailed before v10 read `Pendente` until resent, because SGAA genuinely
  cannot prove those older sends. Proven on disposable copies including a copy of the
  real canonical database (token, credential and password-hash rows byte-unchanged;
  `integrity_check ok`; 0 tokens gained evidence); **canonical `database.db` was not
  migrated** and is byte-identical. Five states, `Situação` as the header (because
  `Status` is already SGAA's word for the *academic* Ativo/Inativo lifecycle, the exact
  confusion the brief forbids), tones all pre-existing and from the single owner,
  one shared `.badge.status-pill` per row as the final column. `Revogado` is derived and
  tested but not rendered, because the active list excludes `acesso_ativo = 0` by
  pre-existing design — flagged, not changed. Bumping the schema head also required
  updating 14 pin files and rebuilding three predecessor fixtures
  (`_build_v6`/`_build_v8`/`_build_v9`). No other backlog item touched; UI-B09, UI-B11,
  UI-B12, Alertas, Curso, Backup and the badge mappings were not opened.

- 2026-09-21 — file created. Recorded UI-A01..A03 (in acceptance), UI-B01..B11
  (backlog), UI-H01..H07 (history). No backlog item implemented in this task.
- 2026-09-21 — UI-B10 implemented and moved from §2 Backlog to §1 In acceptance
  (`DONE_PENDING_VISUAL_CONFIRMATION`). Cause confirmed, consumer audit table
  added to §UI-B10. UI-B11 deliberately not started.
- 2026-09-21 — UI-B02 and UI-B03 implemented together and moved from §2 Backlog
  to §1 In acceptance (`DONE_PENDING_VISUAL_CONFIRMATION`). One cause, three
  page-local status ladders; consolidated into `app/status_presentation.py`.
  §UI-B02/B03 records both inventories, the before matrix, the semantic
  reasoning for every tone (including the two deliberately shared ones), the
  consumer audit and the residual. Zero CSS changed. UI-B11's broad colour
  audit deliberately not started. Also opened UI-B12 to persist the residual
  UI-B01 preset-composition footgun as a tracked item rather than prose.
- 2026-09-21 — UI-B01 implemented and moved from §2 Backlog to §1 In acceptance
  (`DONE_PENDING_VISUAL_CONFIRMATION`). Cause was stored preset data, not the
  renderer; §UI-B01 now records the composer, the authoritative count per phrase,
  the before/after copy, the same-flow audit and the residual footgun. No other
  backlog item touched.
- 2026-09-21 — UI-B05 implemented and moved from §2 Backlog to §1 In acceptance
  (`DONE_PENDING_VISUAL_CONFIRMATION`). Cause was `.content-block` used without
  its header. A first attempt was rejected by the user and fully reverted before
  the second; §UI-B05 records it so it is not retried. Shipped treatment is the
  Turma detail strip promoted to shared CSS, plus the shared `detail_header`.
  `Turmas`/`Alunos` added on the user's instruction. Turma's own template was not
  touched. No other backlog item touched.
- 2026-09-21 — UI-B05 visually accepted by the user → `DONE`. UI-B06 implemented and
  moved from §2 Backlog to §1 In acceptance (`DONE_PENDING_VISUAL_CONFIRMATION`). The
  report was correct: `.btn` never owned `font-family`, so the class rendered in two
  typefaces depending on whether an `<a>` or a `<button>` carried it. One declaration
  added to the component owner; nothing page-local. §UI-B06 records the full resolved
  comparison, the population count and the app-wide blast radius. No other backlog
  item touched.
- 2026-09-21 — **UI-A03 reopened** (`DONE_PENDING_VISUAL_CONFIRMATION` → `IN_ACCEPTANCE`):
  the user visually found remaining semantic-row asymmetry before the common actions.
  The UI-A03 height contract was correct and untouched; the defect was a redundant
  metadata row. UI-B07 implemented and moved from §2 Backlog to §1 In acceptance
  (`DONE_PENDING_VISUAL_CONFIRMATION`), rescoped from the Operações strip to the
  provider cards per the brief. Traced first: the Google-only
  `Seleção de pasta: configuração segura desta máquina` printed the custody of the
  **same** machine-store record the row above it already reported, and OneDrive has no
  equivalent because it browses folders over Graph with the OAuth token it already
  holds. **Case B** — removed from Google, not invented for OneDrive. The Picker
  *failure* message moved to the shared state-driven note region. `Enviar backup agora`
  moved from the card body to the footer beside `Salvar`, bound to a control-only POST
  target with the HTML `form` attribute; endpoint, method, CSRF, icon and disabled
  behaviour unchanged. No spacer, no `&nbsp;`, no fixed height, no provider-specific
  geometry. One pre-existing assertion in
  `tests/test_cloud_credentials_product_recovery.py` was sharpened: a bare
  `"connect" not in config_form` also matched the `gdrive_connected` boolean the footer
  reads, so it now guards the connect **endpoints** it was written for. The Operações
  card's own `Gerar backup agora` was **not** moved — see §UI-B07. No other backlog
  item touched.
- 2026-09-21 — UI-B07, Operações lane. The user reported for the 4th/5th time that the
  generic `Gerar backup agora` was still on the explanatory row and explicitly
  authorized adding a footer. It was a mistake to have deferred this on "adding a
  footer is a redesign" grounds: the page already owned an accepted card-footer
  contract — `.db-card form > .db-actions` (right-aligned over a divider), used by
  `Destinos de backup` and `Política de retenção` — so nothing had to be invented.
  The action moved to the bottom of the Operações card using that exact structure;
  `.db-card-lead`, whose only purpose was pinning the button right of the sentence and
  whose only consumer was that row, was deleted along with its three rules. Endpoint,
  POST, CSRF, `banco_dados:edit` gate, icon and label unchanged. Provider
  `Enviar backup agora` buttons not touched. UI-B07 stays `IN_ACCEPTANCE` until the
  user visually confirms this exact move. No other backlog item touched.
- 2026-09-21 — **UI-B15 implemented**, opened and closed in the same pass, and
  `DONE_PENDING_VISUAL_CONFIRMATION`. Five console messages inventoried to their
  owners first; **three were not SGAA defects**. Typekit appears nowhere in the
  repository and the rendered page names only the two Google Fonts origins, so
  `font-src` is working and **nothing was added to it**. The "Multiple forms"
  warning was checked against the rendered DOM — no nesting, no malformed tags,
  no misowned control, explicit `form=` binding on the two outside Saves — and
  the panel is one server action, so the single Save was kept and the five
  configured defaults instead declare `autocomplete="new-password"`, the token
  this repo already uses for masked configuration secrets. The Lucide source map
  was fixed at the asset rather than the policy: the pinned v0.544.0 bundle is
  now served from `'self'` without its source-map directive, which let
  **`https://unpkg.com` be removed from `script-src`** — the only CSP edit, and a
  tightening. Two real gaps closed: `#access-email` declares `username`, and the
  password dialog gained a hidden, readonly, name-less username identity bound to
  a single-row selection only. Zero geometry/colour/typography change. Tests:
  `tests/test_console_form_semantics_ui_b15.py` (31; 13 fail against the pre-fix
  tree). Console not captured — Playwright is not installed here; the heuristic
  message is the one open question for visual acceptance. Also recorded
  **UI-B14** (`select` border-radius / form-control DS consistency) as `BACKLOG`,
  **not implemented**, per the user's instruction. No other backlog item touched.
- 2026-09-21 — **UI-B15 follow-up on real browser evidence; status moved
  `DONE_PENDING_VISUAL_CONFIRMATION` → `IN_ACCEPTANCE`.** The console corrected
  two of the first pass's answers and surfaced a defect it had not seen.
  **(a)** `cloud-backup` is not a Lucide icon in any version, so the
  `Backup de dados` sidebar entry has been rendering no glyph at all — a
  pre-existing defect that self-hosting made audible rather than caused. Now
  `database-backup`, from the vocabulary `/admin/banco-dados` already uses. All
  39 icon names rendered on `/admin/acesso` audited against the registry parsed
  out of the shipped bundle; the sweep extends to the whole template tree.
  **(b)** The hidden username field **failed**: the HTML `hidden` attribute is
  `display:none`, so the element is never rendered and the password manager
  cannot associate it. Replaced with a promoted shared `.sr-only` primitive —
  in the layout, visually hidden, `readonly`, `tabindex="-1"`, still name-less.
  **(c)** `new-password` on the five profile defaults **reverted to `off`**:
  they are application configuration secrets, not browser-manageable
  credentials, and the wrong token had additionally provoked the username
  warning on the one form that can never have an identity. No fake usernames
  for profiles. **(d)** "Multiple forms" survived both tokens and is closed as a
  Chrome heuristic false positive on a valid single-action form, proven from the
  rendered structure; the single Save was not split. **(e)** Typekit re-proved
  from the served CSS/JS bytes; attribution still needs an incognito recheck.
  **(f)** Forced reflow reported, not optimized. CSP unchanged and still
  tightened. Tests: `tests/test_console_form_semantics_ui_b15.py` (31 → 43).
  UI-B14 untouched and still `BACKLOG`. No other backlog item touched.
