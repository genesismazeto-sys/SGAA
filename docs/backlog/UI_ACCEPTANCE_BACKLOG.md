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
> title line in each Turma form — *since landed as `66be92f`, see 2026-09-29*) and the one-off UI-B01 repair script
> `tools/repair_email_preset_cardinality.py`. Machine-local configuration
> (`.env`) is never versioned.

> **Landing record (2026-09-28).** Everything accepted since `e834d58` was landed on
> `refactor/design-system-foundation` in five commits: request data integrity and the Alertas
> read-only view (`bacca6b` — UI-C03, C07, C09, C19, C20); one governed commit for the Ver/RBAC
> repairs, shared error pages and the automatic-backup pipeline (`ad4ba43` — UI-C01, C04, C05,
> C06, C08, C10–C14, C16, C18, bound together by the message-catalog ledger); Design System
> consistency (`8aa1f1a` — DS-PILL-RADIUS, DS-FLOAT-BAR-ORDER, UI-B11 category A, UI-B14 guard);
> login / e-mail preset / auth (`ada4282` — UI-C17, UI-B12, UI-B13); and this record. Still
> deliberately **not** landed: the optional-header student-import candidate (its nine paths —
> *since landed as `66be92f`, see 2026-09-29*) and
> the one-off UI-B01 repair script `tools/repair_email_preset_cardinality.py`. The Windows
> scheduled task that drives UI-C13 is machine state, not repository content.

> **Landing record (2026-09-29).** The optional-header student-import candidate is **published**
> as `66be92f` (`feat(turmas): make the student import header row optional`), repaired by its
> audit before landing: the old-column-order guard (a first row carrying ≥ 2 column names in any
> other layout is rejected, never read as data with shifted columns) and UTF-8 preview
> consistency (the preview decodes CSV as strict UTF-8 and keeps every cell as text, like the
> server). The Turma data-integrity phase followed on top of it: `38f6caf` (UI-B30, matrícula
> preservation) and `659b69f` (UI-B31, malformed import rows), then this record. Only the
> one-off UI-B01 repair script `tools/repair_email_preset_cardinality.py` remains local and
> unversioned, by decision.

> **Landing record (2026-09-29, identity & defaults).** Four bounded cohorts on top of
> `616374e`, each pushed on its own: `3d58804` (UI-B35, typed e-mails validated server-side),
> `1010280` (UI-B34, spreadsheet formulas rejected), `18d9fda` (UI-B32, e-mail change retires
> mailed links) and `bb2bb32` (UI-B33, prod-1 → v12, Extensão default 160 h), then this record.
> Canonical stays v11 until its next launch migrates it. Only the one-off UI-B01 repair script
> `tools/repair_email_preset_cardinality.py` remains local and unversioned, by decision.

> **Landing record (2026-09-29, root identity & canonical v12).** `9af6ba2` (UI-B36, the root
> e-mail is read-only and refused on Meus dados) was pushed on its own, then this record.
> Canonical `database.db` was migrated **v11 → v12** under custody at 10:44 through the normal
> startup path (`run_startup_preflight` + `init_db`, without `app.run`), rehearsed first on a byte
> copy. Result: `user_version` 12, head digest `4aa56698…`, `schema_migrations` row 12
> (`extension_hours_default`); every other table row-identical (30 of 31); only the `cursos` /
> `matrizes_atividades` DDL changed (`DEFAULT 80` → `DEFAULT 160` on the Extensão column); indexes,
> foreign keys, AUTOINCREMENT counters, `integrity_check` and `foreign_key_check` intact.
> `PPA-NOT` keeps `total_horas_aeu = 80` (UI-B37); a disposable row in a copy took 160/160.
> Content digest `a92d234c…` → `3347788e…` (schema and row 12 only). The automatic-backup task
> was not paused: the migration is one `BEGIN IMMEDIATE` transaction, and a wake writes only when
> a backup is due, which needs the post-commit digest — 2 638 wake-style reads during the
> rehearsal saw only the pre- or post-migration state. The next wake (10:49) backed up the v12
> database (local, Google, OneDrive). Pre-v12 rollback copy kept:
> `SGAA_backups/identity_defaults_20260929/database.pre-v12-extension-hours.db`. Only the
> one-off UI-B01 repair script `tools/repair_email_preset_cardinality.py` remains local and
> unversioned, by decision.

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
| UI-C01 | Matrizes de Atividades → Ver × Editar | "Ver" looked and behaved like "Editar": editable white fields, manipulable composition, edit/mutation controls visible, nothing said read-only | Ver = the same form in explicit view mode: shared `fieldset.form-fieldset` + `disabled aria-readonly="true"` (`--field-readonly-bg` from `components/form.css`); mutation-only controls omitted, not disabled; no mutation JS; `detail_header` Back; no Save/Cancel/footer. Editar keeps every mutation control and its accepted Save/Cancel | DONE | **Confirmed functional defect, not just CSS:** the list's `view_url` and `edit_url` were the *same* URL, so for any account with `matrizes:edit` Ver was the editor and could persist (class C). Fix: `view_url` gains `?view=1` on the existing GET route (no new route, no new catalogued message); `_render_matriz_form(view_mode=)` forces the lock and keeps tabs inside Ver. Reference case for the Ver/Editar consistency checklist — see §UI-C01. Tests: `tests/test_matriz_ver_readonly_ui_c01.py` (21). Acceptance: `/admin/matrizes` → a matrix → Ver / Editar. **Visually accepted 2026-09-26; reference implementation for SGAA read-only detail surfaces (UI-C02).** |
| UI-C02 | Application-wide Ver × Editar consistency audit | Ver/Editar pairs across the admin were never checked against one contract | Inventory every admin Ver/Editar pair against the UI-C01 contract, classify S0–S3, group by shared owner, propose repair items; no product change | DONE | Audit item, not visual acceptance. 9 pairs: **S3 1** (Requisições), **S2 1** (Atividades → catálogo hub), **S1 5** (Cursos, Alunos, Ver versão, Turmas, Alertas), **S0 2** (Matrizes, Arquivos). Separate Editar-locked finding (matrix linked to a Turma). Proposed UI-C03…UI-C08 in §2. Evidence and master table: §UI-C02. No product code changed. |
| UI-C03 | Requisições → modal Ver must be non-submittable (**S3**, from UI-C02) | Ver could persist: the modal kept a live `type=submit` (only `hidden`) and the `form.action` last written by Editar/Criar, so Enter in any read-only field of Ver implicitly submitted. Editar R1 → close → Ver R2 → Enter overwrote R1 with R2's `nome_evento`/`horas`/`data` and set R1's `observacao` to NULL | Ver carries no mutation target and no submit path, whatever the open/close order; Editar rebuilds its target from the selected request only; legitimate read actions stay live | DONE | **Root cause:** `setSaveButton` was the only writer of `form.action` and nothing ever cleared it; view/process only set `hidden` on the submit, and a hidden default button still fires on implicit submission. The form was also *rendered* with a live create action. **Repair (`templates/admin_requisicoes.html`):** the form is rendered with no action; only Criar/Editar assign one, and Editar also writes `edit_target_id`. `clearWritableTarget()` (removes the action, empties the target, submit `hidden` **and** `disabled`) runs in Ver, in Processar, after the process-confirm step and on every close. Close also clears `data-mode`, `reqId`/`reqStatus` and any selected upload files. Editar re-arms only when the target matches the request shown; a capture-phase submit guard refuses any submit outside Criar/Editar (defence in depth). **Server (`admin_editar_requisicao`):** a POST whose `edit_target_id` is not the URL's request is refused before any read or write, reusing the catalogued "Falha ao atualizar requisição." (catalog digest unchanged). **Abrir:** it only `window.open`s an existing receipt, so it is live in Ver (the `pointer-events:none; opacity:.6` toggle is gone). Processar had the same hole (its enabled horas-deferidas field) and is covered by the same call. Tests: `tests/test_requisicao_view_non_submittable_ui_c03.py` (15). Browser tests drive real headless Chromium with trusted Enter/clicks; every page request is served by the Flask test client on an isolated DB (`tests/cdp_browser_support.py`, no app port). On the pre-fix code the same harness reproduced the corruption end to end. Acceptance: `/admin/requisicoes` — needs one pending, disposable request (canonical has none) |
| UI-C10 | Banco de Dados → manual backup independent of automatic-backup participation | "Incluir no backup automático" was permanently disabled (template constant `auto_backup_toggle_editable = false`) under the tooltip "Disponível quando o backup automático for ativado.", right beside "Enviar backup agora", so it read as a precondition of the manual action and could never be switched | The switch only decides automatic-cycle participation and is editable; "Enviar backup agora" depends solely on the provider being connected/usable, on both cards, whatever the switch | DONE | Audit: button, manual endpoints, JS and automatic selection were already independent; the locked switch + tooltip was the defect. Template-only repair (`templates/admin_banco_dados.html`); no route/symbol/message change. Tests: `tests/test_manual_backup_independent_of_auto_ui_c10.py` (21). **Visually accepted 2026-09-27.** See §UI-C10 |
| UI-C11 | Banco de Dados → "Gerar backup agora" result must reflect actual destination outcomes | After a backup that reached Google Drive **and** OneDrive the screen said "Backup local criado. A sincronização em nuvem foi adiada ou não detectou mudanças." The message was chosen from the legacy "Pasta em nuvem" step alone (skipped: folder not configured) **before** the providers ran, and their results were discarded | Local snapshot first; then pasta em nuvem, Google Drive, OneDrive and servidor externo each attempted independently; retention; only then one message naming what was sent and what failed. Never claims "adiada"/"sem mudanças" unless that comparison happened | DONE | Structured per-destination outcome (`success` / `skipped_not_configured` / `skipped_not_enabled` / `unchanged` / `deferred` / `failed`) in `app/backup/orchestrator.py`; the view picks one of four catalogued messages (catalog term UI-C11, +4/−4, count 582). Provider-card "Enviar backup agora" untouched. Tests: `tests/test_backup_destination_outcomes_ui_c11_c12.py`. See §UI-C11–C13 |
| UI-C12 | Automatic cycle → cloud providers must not depend on the legacy cloud-folder sync | `run_backup_cycle` uploaded to Google/OneDrive only if the "Pasta em nuvem" sync succeeded **and was not skipped**; with no folder configured (the canonical state) the automatic cycle never reached any provider, whatever the switches said | Local snapshot is the only prerequisite; folder (if configured), Google (if switched on) and OneDrive (if switched on) run independently; one failing never stops or rewrites another | DONE | Repair in `app/backup/orchestrator.py` (+ `app/backup/sync.py` logging). Local retention now keeps one series per location (local / pasta em nuvem), newest-first on same-second ties, so a cycle never deletes its own fresh snapshot. Not observable in the UI until UI-C13 gives the cycle a trigger. See §UI-C11–C13 |
| UI-C14 | Error pages (400 / 403 / 404 / 500) must use the shared Design System | The 400 page (stale session / CSRF) carried a page-local orange badge, a hand-built grey note, a raw-hex gradient and its own card and button overrides; 500 cloned `.card` and `a.btn` with raw colours; 404 sat in the admin chrome and sent every user, students included, to the admin dashboard; 403 had no SGAA page at all (`abort(403)` showed Werkzeug's bare English "Forbidden") | One shared owner; every surface an existing DS component; no raw colour; same texts, same CSRF/session behaviour; back/home navigation kept | DONE | `templates/error_page.html` owns the page; 400/403/404/500 only fill its blocks. Reused: `.login-page`/`.login-card` (public-page shell), `.badge.status-pill.status-negative`, `.login-title`/`.login-subtitle`, `.flash.flash-info` (note), `.btn.primary`/`.btn` + `.btn-label`. 403 gains a handler (`app.web.errors.forbidden`, catalog term UI-C14 +1 for its fallback). Tests: `tests/test_error_pages_design_system_ui_c14.py` (23). See §UI-C14 |


---

## 2. Backlog

| ID | Area | User-reported issue | Expected behavior / constraint | Status | Notes / acceptance evidence |
|---|---|---|---|---|---|
| UI-B13 | Meus dados → campo de senha | "Deixe em branco para manter" may no longer be literally true after the new credential flow | Audit the password field in Meus dados against the credential contract. **Blank must be a true no-op:** hash unchanged, `usuario_credenciais.estado` unchanged, `auth_version` unchanged, `senha_tokens` untouched, and no accidental transition into first-access or shared-default state. **A new password must:** store a personal credential, set `estado=personal`, bump `auth_version`, and invalidate other sessions/tokens per the current contract — with the acting user's own session restamped so a self-change does not log them out. `default_passwords_enabled` ON/OFF must not alter any of this. Cover the root administrator and the aluno/usuário paths, not just admin. Finally, verify the copy "Deixe em branco para manter" is still literally accurate; if behaviour is correct but the wording is not, fix the wording | DONE | **Audited 2026-09-28 (extended batch) — already correct; no product change.** Both `/admin/meus_dados` and `/aluno/meus_dados` write credentials only when `senha` is non-empty: a **blank** (or omitted) password updates the profile only — hash, `estado`, `auth_version`, `acesso_ativo`, first-access/reset tokens and the session all unchanged, so "Deixe em branco para manter" is truthful. A **new** password goes through the shared `set_usuario_password_hash` (new hash, `estado='personal'`, `auth_version`+1 so other sessions end, active tokens invalidated, acting session restamped, `acesso_ativo` untouched). Root: blank keeps its state; a personal password leaves the master key working. A revoked account cannot reach the page (revocation bumps `auth_version`). Tests: `tests/test_meus_dados_password_contract_ui_b13.py` (9, DB before/after). **Policy note (no change):** a password of only spaces is non-empty and would be set — trimming/rejecting it is a password-policy decision |
| UI-B04 | Alertas | The alert title is being rendered to the target user | The title is **internal**: it exists so the administrator can identify the alert later when editing/managing it. It must not appear in the alert delivered to or displayed for the target user unless a separate, explicit product field is intended as user content. Internal title stays available in admin management; the user sees only the actual alert content/message | DONE_PENDING_VISUAL_CONFIRMATION | Recipient rendering was already correct (`aluno_dashboard.html` binds `alerta.mensagem` only). The leak was preview-only: `updatePreview()` in `templates/admin_alertas.html` concatenated `titulo + ' - ' + mensagem`, and `tituloInput` was wired to it. Preview now reads the message alone; admin list column and the edit modal's Titulo field are untouched. Tests: `tests/test_alerta_preview_matches_recipient_ui_b04.py` (10 passed; 3 fail against the pre-fix template). Visual check: `/admin/alertas` -> Novo alerta |
| UI-B12 | Configurações → Pré-definições (editor de e-mail) | Preset editor permits manually composing grammatically inconsistent singular/plural fragments | The fragment placeholders (`{requisicao.possessivo}`, `{requisicao.substantivo}`, `{requisicao.processamento}`) remain in the published vocabulary, so an administrator can still hand-glue a plural possessive to a singular noun — the exact shape of the delivered UI-B01 defect. Wanted: a save-time coherence guard, or retirement of the fragment tokens in favour of the whole-sentence `{requisicao.frase}` | DONE_PENDING_VISUAL_CONFIRMATION | **Decision B (user, 2026-09-28): the fragment tokens are removed from the authoring contract.** Classified from `app/request_email_render.py`. **Retired (3):** `{requisicao.possessivo}`, `{requisicao.substantivo}`, `{requisicao.processamento}`, which only work if literal words are glued around them. **Kept:** the safe whole-sentence `{requisicao.frase}`; the UI-B01 subject noun phrase `{atividade.substantivo}` (the canonical default subject uses it); and `{saudacao}`, `{aluno.*}`, `{data.*}`, `{quantidade_requisicoes}`, `{requisicoes}`. **Removed from:** `PLACEHOLDER_HELP`, the editor's insert-chips and help (both render from it) and the save allowlist (`SCALAR_PLACEHOLDERS`). **Server-side:** `presets_api` rejects a retired fragment in any new or edited subject/body ("{…} foi descontinuado: use {requisicao.frase}…", shown through the existing `presetSaveError` toast). **Legacy compatibility:** the save replaces every model at once, so a stored model whose subject and body are byte-identical to what is already stored under the same id round-trips untouched. The retired tokens stay *render-only* (`RETIRED_PLACEHOLDERS`), so such a model or a restored backup keeps sending exactly as before; preview and send share `build_plan`. **Stored data (read-only audit):** no preset in canonical, acceptance or any of the 8 backup databases uses a retired token, so no migration was needed and none was run. A token-to-`{requisicao.frase}` migration would not be deterministic anyway: the fragments say "solicitação", the sentence says "requisição". The canonical default (`Processamento de {atividade.substantivo}` / `{requisicao.frase}`) is unchanged. The acceptance preset's literal pre-B01 prose (no tokens) is admin text and was not rewritten. **Visible change:** the Pré-definições e-mail editor shows 3 fewer chips (visual confirmation pending). Tests: `tests/test_email_preset_fragment_retirement_ui_b12.py` (15); 3 stale assertions of the old contract in `test_request_email_ux_repair.py` inverted **Non-visual regression re-check 2026-09-28 (second extended batch):** headless Chromium on a disposable DB — the editor offers none of the three retired chips and does offer `{requisicao.frase}` / `{atividade.substantivo}`; a new save with a retired fragment → 400 ("… foi descontinuado …"), a safe model → 200; an untouched legacy model stays byte-identical; no page error. Canonical preset data unchanged (content digest) |
| UI-B11 | Design System — colour tokenization audit | Raw reusable component colours bypass the DS token layer | Search shared and page-local SGAA UI CSS for raw hex/rgb/hsl controlling reusable semantics and classify each finding: **A** already tokenized correctly; **B** reusable semantic colour using a raw literal → migrate to the existing token; **C** duplicate semantic token → consolidate deliberately; **D** genuinely page/content-specific → may remain, with an explicit stated reason. Do not mass-rewrite blindly, and never replace one raw value with another raw value. Goal: same semantic state → same token → same visual treatment | SAFE_COHORT_COMPLETE — REMAINDER_NEEDS_SEMANTIC_TOKEN_DECISIONS | **Second category-A cohort 2026-09-29 (re-audit on `009a79a`, brief scheme A safe · B component-local · C needs semantic-token decision · D content · E proven dead):** 28 value- and role-identical sites across 6 files. White button/card surface fills become `--surface`: the skip link, sidebar hover/active, avatar frame, `.icon-btn.danger`, the Banco de dados folder close button and the Atividades/Requisições mini-toolbar buttons. The computed Turma “Fim” card `.field-card.is-off` becomes `--field-readonly-bg`. The Cursos pills that restated the shared palette now use the status-pill component properties. 10 inert `var()` fallbacks on always-defined tokens were dropped; two had drifted, including `var(--btn-primary, #0369a1)`. 458 → **430**; before A 28 · B 30 · C 389 · D 7 · E 4, after **A 0** · B 30 · C 389 · D 7 · E 4. **No visual change:** 45 element states (default plus forced hover/focus) are computed-identical, and 7/8 full-page screenshots are pixel-identical (the 8th differs only in the disposable runtime's temp path). Remaining, with exact reasons, in `docs/backlog/UI_B11_RAW_COLOUR_AUDIT.md`: B is the status-pill owner palette, the print palette, the toggle token and the Alertas hairline. D is the days-bar data-viz ramp and the Alertas user white. E is the 4 dead `.db-badge` fallbacks, parked with the status-palette decision. C needs new value-preserving semantic tokens (`--danger-*`, `--warning-*`, `--success-*`, `--info-*`, `--surface-subtle`/`--hover-bg`, `--divider`, shadows/backdrop, `--text-on-brand`, `--control-selected`, global `--status-*`, plus 3 phantom tokens) or a user visual decision (zinc scale, `#0f172a` ink, slate text, aluno_dashboard inline styles). Guard `tests/test_b11_category_a_tokenization.py`: ceiling 430, and no colour fallback on a `tokens.css` token. **Category-A pass 2026-09-28 (second extended batch, working tree only):** 39 exact duplicates tokenized across 19 owners with zero visual change — surfaces → `--surface` (incl. the default-password profile cards), empty-state/muted text → `--text-secondary`, field fills → `--field-bg`, selection/hover accent → `--accent-blue`, `.btn.primary:hover` → `--btn-primary-strong`, focus outlines → `--focus-ring-color`. 498 → **459** raw colours (153 values, 29 owners); categories now **A 13 · B 37 · C 238 · D 0 · E 171**: 13 A remain (the `.db-badge` palette needs a markup change; one `modern-style.css` surface the audit never pinned to a line), 11 A were reclassified on re-validation (8 `var()` fallbacks → B, resting chip fill → C, a gradient stop and a selected-row badge white → E). B/C/E untouched, incl. the Alertas residuals. Details: `docs/backlog/UI_B11_RAW_COLOUR_AUDIT.md`; guard `tests/test_b11_category_a_tokenization.py` (ceiling 459). *Original audit:* **Audited 2026-09-28 (extended batch) — no colour changed.** Full audit and owner/role table: `docs/backlog/UI_B11_RAW_COLOUR_AUDIT.md`. 498 raw literals, 156 distinct values, 35 owners, classified with the batch brief's scheme (the row's scheme maps as: row-B → A, row-C → C, row-D → B): **A** use an existing token 63 · **B** legitimate component-internal 29 · **C** missing semantic token 237 · **D** dead 0 · **E** needs a visual decision 169. Value match ≠ role match: e.g. `#b91c1c` equals `--field-invalid-text` but is the generic danger colour at 20 sites → C (`--danger-*` missing). Known residuals: Alertas selected-swatch outline `#0f5b99` → C (same value as form.css-local `--toggle-switch-active`; promote one `--control-selected`); colour-dot `rgba(0,0,0,.12)` → B; border-only swatch `#fff` → B (user data colour, not `--surface`); default-password profile cards `#fff` still present → A (`--surface`). Banco de Dados `.db-badge` duplicates the shared status-pill palette byte-for-byte → A via markup change. No zero-risk repair applied (queue is the deliverable); queue order A → C (new tokens) → E (user visual decisions) |
| UI-B14 | Design System — `select` / form-control consistency | `select` border-radius diverges from the rest of the shared form-control contract | Reconcile `select` with the DS form-control primitive rather than patching individual pages: one radius token, one border, one hover/focus treatment shared with `input` and the other controls. Audit page-local `select` rules that restate geometry (`admin_acesso.html` alone carries two) and fold them into the shared owner. Do not introduce a new token or a second radius | DONE | **Status aligned 2026-09-28 with the backlog vocabulary (was CLOSED_ALREADY_CONSISTENT): non-visual, no product change, evidence below.** **Audited 2026-09-28 (extended batch) — no product change.** The shared field radius owner is `var(--radius)` (4px): `.field-card` (frames every carded input/select/textarea/date/number), bare `select.control` (dedicated rule), `.field input/select/textarea`, the toolbar select and input group, and every page-local field rule. A headless-Chromium probe of the frame actually drawn around each visible control on Matriz, Versão, Banco de Dados, Requisições, Acesso, Meus dados, Alunos and Login measured **4px for every control**. The earlier squarer `select` is already resolved by the `select.control{ border-radius:var(--radius) }` rule. Guard: `tests/test_form_control_radius_ui_b14.py` (2). Pills/badges are not in scope (DS-PILL-RADIUS, deferred) |
| DS-PILL-RADIUS | Design System — rounded pills / badges | Pills and badges are fully rounded (`border-radius:999px` on `.badge` and `.badge.status-pill` in `static/css/modern-style.css`) while the rest of the DS uses the 4px `--radius` token | Standardize every pill/badge on one shared DS border-radius token of **4px**, changed once at the shared owner/token — never page by page | DONE_PENDING_VISUAL_CONFIRMATION | **Implemented 2026-09-28 (second extended batch, working tree only).** One global token `--pill-radius: 4px` in `static/css/foundation/tokens.css` — its own token, deliberately separate from the field/card `--radius` (the pill corner is its own DS decision). Consumers: the shared `.badge` and `.badge.status-pill` owners (`modern-style.css`) — every status pill, plain count badges and the UI-C14 error-page status label inherit it; `.imp-cursos .badge.status-badge` (`list-cards.css`); and the page-local status-label families that restated the pill: Banco de dados `.db-badge` / `.db-origin-pill` / provider-head `.db-badge`, Atividades filter-count badge and local `.badge`, Requisições local `.badge`, Importar atividades `.status-chip`, Diagnóstico `.diag-badge` / `.diag-chip` / `.diag-pill`, and Mensagens `.message-badge` (already 4px, now token-owned). Only the corner changed — padding, heights, font sizes, colours, borders and text untouched. **Excluded (keep their shape):** status dots (`::before`), avatars, the Requisições floating-bar selection counter `.act-count` (a circle), the presets placeholder-insert chips `.presets-ph` (buttons), switches, buttons, icon buttons and floating-bar buttons; `.db-chip`, `.cfg-chip`, `.access-count-chip`, `.matriz-modal-chip` already use `--radius` (4px); `.badge-grupo` (6px/2px), `.unit-chip` (6px) and the `.filter-pill` / `.msg-search-pill` controls (4px) unchanged. Headless Chromium (Banco de dados, Requisições, Atividades, Turmas, 404): every pill/badge 4px, dots 50%, `.btn` 4px, switch 3px. Guard: `tests/test_ds_pill_radius.py` (7); the UI-B17 single-radius-token pin now allows exactly `--radius` + `--pill-radius`. Visual acceptance pending |
| DS-FLOAT-BAR-ORDER | Design System — floating row-action bars (`#pedido-actions-float`) | Equivalent actions sit in different positions from one list/table floating bar to another | FLOATING ACTION BAR ORDER: equivalent actions occupy the same position across list/table floating bars; reading **left to right**, the primary read/detail action (Eye) comes **first**, then Editar, and Excluir comes **last**; future repairs standardize the order once at the shared owner/pattern, never page by page | DONE_PENDING_VISUAL_CONFIRMATION | **Implemented 2026-09-28 (second extended batch, working tree only) for every surface whose placement is unambiguous.** There is no shared macro — 14 hand-written bars; only `components/actions-float.css` is shared and nothing reverses DOM order — so one guard walks all of them: `tests/test_ds_float_bar_order.py` (44: slots, canonical registered icons `eye`/`edit`/`trash-2`, per-role visibility, click handlers). Rule applied: Eye first, Editar second, Excluir last; domain actions keep their relative order between Editar and Excluir (the placement Atividades, the versions hub and Acesso already used). **Changed (markup reorder only — `data-action`, icons, labels, permission guards and handlers untouched):** Reportes Excluir, Ver → Ver, Excluir; Matrizes Ver, AAC, AEA, Editar, Excluir → Ver, Editar, AAC, AEA, Excluir; Alertas Ativar/Desativar, Ver, Editar, Excluir → Ver, Editar, Ativar/Desativar, Excluir (as the versions hub places its state actions). **Already conforming:** Turmas (reference, untouched), Cursos, Alunos, Arquivos, Detalhes da turma, Atividades, versions hub, Acesso (no Ver), Aluno arquivos, Aluno requisições. **AMBIGUOUS — left unchanged, user decision:** Requisições (Processar/Reabrir, Editar, Ver, Enviar e-mail, Excluir) — Processar/Reabrir is that list's primary workflow action and no other bar offers a placement for it; the bar is selection-owned with a batch mode. Its current order is pinned by the guard so it only changes deliberately. Browser x-order confirmed on Turmas, Cursos, Alunos, Matrizes, Alertas, Reportes. Visual acceptance pending |
| UI-C04 | Ver routed through editor endpoints — Cursos, Alunos, Ver versão (**S1 navigation, functional dead-end**) | *Found by UI-C02.* The three Ver actions advertised under `:view` targeted endpoints governed by `:edit`, so Consultor was bounced to `/admin/dashboard` | Ver has a dedicated GET-only `:view` endpoint that renders the accepted shared form read-only; Editar keeps its GET+POST `:edit` endpoint; delete/lifecycle routes keep full/edit | DONE | Cursos reuses `admin_visualizar_curso`; Alunos adds `admin_visualizar_aluno`; exact versions add `admin_catalogo_visualizar_versao`. Main Alunos and Turma roster point to the same view endpoint. UI-C05 affordance/switcher inconsistencies are unchanged. Focused RBAC, route-governance and read-only suites green. See §UI-C04 |
| UI-C05 | Atividades → catálogo hub and Ver versão (**S2** for view-only; S1 navigation) | *Proposed by UI-C02.* The hub (the list's Ver) renders Editar/Ativar/Suspender/Excluir and **Criar versão**, and Ver versão renders **Nova versão**, with no `auth_can` gate; for a Consultor every one is refused server-side. Ver versão's version switcher always targets the editor URL, so switching to a draft drops out of Ver | Gate hub/lifecycle/create affordances on `auth_can('atividades', 'edit'/'full')`; the switcher preserves the mode it was opened in | DONE | **Implemented 2026-09-27 (working tree only).** One `auth_can('atividades','edit')` flag gates every WRITE on the hub (Criar versão, Editar, Ativar, Inativar, Descontinuar, Substituir, Excluir: toolbar buttons, hidden lifecycle forms, substitution options, modal, edit URLs) and "Nova versão" on Ver/Editar versão; view-only users see Ver on every version, drafts included. The switcher keeps its mode (Ver → `/visualizar`, Editar → `/editar`) and Ver's form carries no action/method/CSRF. Editors' state rules unchanged; backend unchanged (every write still `atividades:edit`). Tests: `tests/test_atividades_ver_no_mutation_ui_c05.py` (10). See §UI-C05 |
| UI-C06 | Alunos Ver + Turma detail → shared header (**S1**) | *Proposed by UI-C02.* Ver Aluno uses a plain `h1` and a generic bottom `← Voltar` footer; Turma detail uses a page-local `.turma-topbar` with a generic "Voltar" and an inline raw `color:#6b7280` | Both adopt `detail_header` with a contextual Back label; Ver Aluno drops its view footer (Editar keeps Cancelar/Salvar). Field paint is already correct (per-control `readonly aria-readonly`) | DONE | **Implemented 2026-09-27 (working tree only).** Ver/Editar Aluno and Turma detail use the shared `detail_header` (unchanged component); Back names its destination (Aluno: `return_to` → "Turma" from a roster, else "Alunos"; Turma: "Turmas"). Ver Aluno has no footer; Editar keeps Cancelar + Salvar; the turma picker sits in the header's trailing slot; the page-local `.turma-topbar` and the roster empty-state's inline `#6b7280` are gone (`.table-empty`). Catalog term UI-C06 (−1, "Voltar"). Tests: `tests/test_aluno_turma_header_ui_c06.py` (7). See §UI-C06 |
| UI-C07 | Alertas → modal Ver (**S1**) | *Proposed by UI-C02.* View mode paints through a page-local read-only clone — `.modal-card.is-readonly .control{background:#f8fafc}` (raw gray, not `--field-readonly-bg`) — and dims the colour-pick buttons with `opacity:.5` | Controls take the shared read-only contract (`readonly`/`disabled` + `aria-readonly="true"` → `components/form.css`); no page-local clone, no opacity dimming | DONE_PENDING_VISUAL_CONFIRMATION | **Implemented 2026-09-27 (working tree only).** Ver drops the page-local `#f8fafc` control paint and the `opacity:.5` pipettes: Título/Mensagem take form.css's shared read-only contract (`readonly` + `aria-readonly` → `--field-readonly-bg`, `--text-secondary`), the colour hex fields restate those same tokens, the pipettes (mutation-only) are omitted, swatches stay visible but inert, and the form carries no `action` in Ver. Editar, the shared modal and the MESSAGE-only preview unchanged. Tests: `tests/test_alertas_ver_readonly_ui_c07.py` (5; 3 in headless Chromium). See §UI-C07 |
| UI-C08 | Editar locked state — Matriz linked to a Turma; Atividades "Editar" on a non-draft (**Editar issue, not Ver/Edit**) | *Proposed by UI-C02.* (a) Matriz Editar, frozen: Curso/Status selects carry `aria-readonly` + `tabindex=-1` but stay **enabled** (the mouse still changes them; the select's value precedes the hidden duplicate in the POST), and Início/Fim/Horas AAC/Horas AEU are fully enabled; all six are refused server-side with the generic "Parâmetros inválidos." — only Nome/Descrição can change. Composition tabs show a lone bottom Voltar beside the header Back. (b) The Atividades list's Editar targets the current version, which is normally active, so it opens a read-only page titled "Ver versão" | A locked Editar presents its locked fields as read-only through the shared contract and keeps navigation single; the list does not label a read-only destination "Editar" | DONE_PENDING_VISUAL_CONFIRMATION | **Implemented 2026-09-27 (working tree only).** *Versão:* Editar is offered only for a version the canonical freeze policy lets be edited in place (an unreferenced draft); a locked version's `/editar` renders Ver (no save target); the Editar-mode switcher opens locked targets in Ver. *Matriz (rule decided: a linked Matriz stays editable):* it keeps "Editar"; Nome and Descrição stay editable; Curso/Status are `disabled aria-readonly` (existing hidden mirrors submit the unchanged value) and both dates / both hour fields `readonly aria-readonly` — the shared read-only contract; AAC/AEA composition read-only with no redundant bottom Voltar. Backend unchanged. Tests: `tests/test_state_locked_versions_ui_c08.py` (8), `tests/test_matriz_linked_partial_edit_ui_c08.py` (11). See §UI-C08 |
| UI-C09 | Requisições → admin edit endpoint treats an absent `observacao` as "clear" | *Found during UI-C03.* `admin_editar_requisicao` writes `observacao = NULL` whenever the field is missing from the POST, not only when it is submitted empty. The UI always submits it in Editar (the textarea is enabled), so this is not reachable from the current screen after UI-C03 — but any client that omits the field (a script, a future UI that disables the textarea, a partial payload) silently erases the observação. Same shape for the other optional fields should be checked | Distinguish "field absent" (keep the stored value) from "field submitted empty" (clear it); decide whether the student edit endpoint needs the same | DONE | **Fixed 2026-09-27 (overnight batch, working tree only).** `admin_editar_requisicao` now writes `observacao` only when the field is submitted: **missing** → stored observação preserved; **empty** (or whitespace) → explicit clear (NULL, as before); **text** → replaced (trimmed). The normal Editar form always submits the prefilled textarea, so preserve/change/clear work as before; no UI change. UI-C03 guards untouched (`edit_target_id`, stale/missing target refused before any write). Tests: `tests/test_requisicao_observacao_semantics_ui_c09.py` (18; the omitted-field test fails on the old endpoint). **Same bug class left for a decision (not changed):** `admin_processar_requisicao` (processing note) and the student's `aluno_requisicao_detalhe` edit also write `observacao` from `request.form.get` unconditionally, so an omitted field clears it **Siblings resolved 2026-09-28:** the student edit is repaired (UI-C19, DONE); the processing route is repaired too (UI-C20, DONE) |
| UI-C13 | Automatic backup scheduler ownership / installation | *Found during UI-C11/C12.* Nothing runs the automatic backup cycle. UT-5 (2026-08-08) removed the `after_request` hook and made `python -m app.backup.sync` the trigger, explicitly with no thread/timer/worker; no scheduled task, installer or registration script exists in the repository, and none is registered on this machine | The SGAA-configured periodicity (Banco de dados → Intervalo de verificação) drives automatic backups through a supported, idempotently installed Windows task; manual and scheduled cycles never overlap; every scheduled run leaves durable evidence; the header says "Backup automático ativo" only when it is effectively active | DONE_PENDING_VISUAL_CONFIRMATION | **Visual correction 2026-09-28 (user):** the indicator now lives where it was asked for — the right side of the "Destinos e sincronização" card header, closing the destination chip group (Pasta sincronizada, Google Drive, OneDrive, then the automatic-backup state) on the same `.db-chip` owner: blue `.is-active` "Backup automático ativo" when the effective resolver says active, neutral "Backup automático inativo" otherwise (it never disappears). Removed: the chip and its `.db-title-row` wrapper from the page title, the scheduler tooltip (poll/interval/last-run text) and the `automatic_backup_last_label` context that fed it, and — at the user's request — the "Último upload Google Drive" / "Último upload OneDrive" lines of the "Destinos em nuvem e externos" card (they dated from the clean baseline `dea3de5`, not from UI-C13; the provider cards keep their own UI-B07 "Último upload" notes). Resolver semantics unchanged. Tests: `tests/test_automatic_backup_scheduler_ui_c13.py` (tests 13–16 rewritten: active, four inactive causes, acceptance DB, no upload lines, shared owner/no colour). *Earlier record, superseded where it describes the title chip and tooltip:* **Installed 2026-09-28 11:14 (authorized; second extended batch)** after the focused gate (1231 passed) and the full suite (3288 passed, 136 skipped, 0 failed, 0 xfailed). `python -m app.backup.task_scheduler install` → `status` active → `reconcile` no-op → `status` active; exactly one task `SGAA - Backup automatico` at the root folder: canonical venv `pythonw.exe -m app.backup.sync --scheduled`, working directory the repository, the current user's SID with `InteractiveToken` / `LeastPrivilege`, `PT5M`, `IgnoreNew`, `PT30M`; the exported definition holds no secret. One on-demand Task Scheduler run (11:15): result 0; `logs/backup-automatico.log` recorded `gatilho=scheduled`, the SGAA interval (600 s), `first_run` → local snapshot + Google success + OneDrive success (pasta em nuvem not configured), retention removed 0, exit 0, no secret. The next automatic wake (11:19) logged `não devido (unchanged)`. Canonical application data unchanged — only the bookkeeping `configuracoes_backup` upload timestamps and the `cloud_accounts` token refresh changed; DPAPI store unchanged; lock released. `/admin/banco-dados` on canonical renders "Backup automático ativo" on `.db-chip.is-active` (computed `#eff6ff` / `--accent-blue`, 4px, beside the title, identical to the Google activity chip) with a truthful tooltip ("… a cada 5 min … no máximo a cada 10 min. Último backup automático: 28/09/2026 às 11:15"); the resolver reports `other_database` for the acceptance DB. The retention risk this activated (the first due cycle after a restore pruning the local pre-restore safety snapshot) was closed the same day — see UI-C18. Visual acceptance pending. *Implementation record:* **Implemented 2026-09-28; the real task is not installed (installation not authorized).** Design: `docs/backlog/UI_C13_SCHEDULER_DECISION_MEMO.md`. **Periodicity is the SGAA's own:** the existing `cloud_sync_interval_seconds` ("Intervalo de verificação (s)", 0 = ao alterar), which was the pre-UT-5 automatic gate (changed **and** interval elapsed). There is no time-of-day field and no global on/off; the provider switches stay per destination. The earlier "cadence/time decision required" was wrong and has been withdrawn. **Architecture:** a Windows task (`SGAA - Backup automatico`, runs as the user with an interactive token, `pythonw -m app.backup.sync --scheduled`, every 5 min, `IgnoreNew`, 30-min limit) only wakes the SGAA; `app.backup.automatic.evaluate_due` decides from the SGAA interval plus a logical content digest, with state in `<local>/.sgaa-automatic-backup-state`. Changing the interval needs no task change. **Gaps closed:** an OS file lock (`app.backup.lock`) is held by the CLI, "Gerar backup agora" and both restores. The loser is refused: the scheduled wake exits 0 and logs it; the plain CLI exits 3; the web shows "Outro backup está em andamento…" (catalog +1). A crashed holder releases the lock with its process. The durable `logs/backup-automatico.log` records start, trigger, interval, decision, snapshot, per-destination outcomes and end, with no secrets. **Installer:** `python -m app.backup.task_scheduler status|install|reconcile|uninstall [--dry-run]`, idempotent; the definition holds no secret. **Effective status and header indicator (acceptance item folded in here):** "Backup automático ativo" appears beside the Banco de dados title only when the task exists, is enabled, is current (interpreter, command and folder), runs as this user and covers the database being viewed. It reuses the Drive/OneDrive activity chip (`.db-chip.is-active`); otherwise nothing is shown. **Machine dry run:** `status` = `not_installed`; `install --dry-run` printed the definition; nothing was registered. Tests: `tests/test_automatic_backup_scheduler_ui_c13.py` (38). **Pending:** the user runs `install`, then `status`, and confirms the chip on the canonical runtime |
| UI-C15 | Atividades → list Ver for an activity without a catalog base | *Found during UI-C05.* The Atividades list's Ver opens the versions hub when the row has a catalog base; for a row without one it still navigates to the legacy `admin_editar_atividade?view=1`, which is `atividades:edit`-gated, so a view-only user would dead-end there (the C04 shape). Not yet established whether any such activity exists | Confirm whether base-less activities can exist; if so, give their Ver a view-authorised target (or retire the branch) | CLOSED_NON_ACTIONABLE | **Audited 2026-09-27 (overnight batch) — classification C, impossible state; no product change.** Evidence: the Atividades list (and the Acadêmicas/Extensão lists) build every row `FROM atividade_base b JOIN atividade_versao v` (`_canonical_activity_rows_sql`), so `data-base-id` is always `b.id`; `atividade_versao.atividade_base_id` is `NOT NULL`; the legacy `atividades` table no longer exists; `admin_adicionar_atividade` always creates a base + v1; `admin_editar_atividade` never renders its page (it redirects into the catalog by the version's base); canonical and the acceptance DB have 0 orphan versions. The list's "no base" Ver branch (`admin_editar_atividade?view=1`) is therefore unreachable dead code — left as is |
| UI-C16 | Turma page — `sortFieldBtn` console error | `Uncaught ReferenceError: sortFieldBtn is not defined` on `/admin/turma/<id>` (already in HEAD, not from C04/C06): two page-local document listeners (outside-click, Escape) left from an older page-local sort menu referenced `sortFieldBtn`/`sortMenu`/`closePopover`, which only exist inside the shared `initToolbarSortMenu()` (`static/js/toolbar-filters.js`). Load-time initialisation was not aborted; the error fired on every click and every keypress | No uncaught error on the Turma page; sort menu still opens/closes on outside click and Escape via the shared owner | DONE | Dead listeners removed (the shared initializer already registers both behaviours for `#sort-field`/`#sort-menu`); no guard, no fake element, no try/catch. `templates/admin_detalhes_turma.html` only. Tests: `tests/test_turma_page_console_ui_c16.py` (2; the browser one records uncaught errors and reproduced the exact error on the pre-fix template). CSP untouched: the separate `font-src` refusal is `use.typekit.net`-style third-party content (no reference in `templates/`/`static/`, see UI-B15) — no product defect |
| UI-C17 | Login → identity + self-service recovery | Login heading read "Sistema de Atividades Complementares"; the footer told users with access problems to e-mail `atividadescomplementares@ej.com.br` (mailto) although SGAA has a self-service recovery flow | Heading "SGAA"; access problems point to the existing recovery (`/esqueci-minha-senha`, `forgot_password`) | DONE_PENDING_VISUAL_CONFIRMATION | **Implemented 2026-09-27 (overnight batch, working tree only).** `templates/login.html` only: `<h1 class="login-title">SGAA</h1>`; footer "Problemas de acesso? Recuperar senha" (plain footer link, as the former mailto; the page keeps its single `.login-forgot-link`, pinned by `test_password_login_session_phase2`). Subtitle, auth shell, "Esqueceu sua senha?" link, recovery flow (anonymous, rate-limited, neutral answer, reset-purpose e-mail) and v11 credential semantics unchanged; a revoked account stays refused. Tests: `tests/test_login_identity_recovery_ui_c17.py` (9). Acceptance: `/login` |
| UI-C18 | Banco de Dados → restore must reach cloud providers independently | *Residual of UI-C11/C12.* After a restore, `_restore_database_from_source` uploaded to Google/OneDrive only the legacy "Pasta em nuvem" snapshot, so with no folder configured a restore never reached any provider | The restored database goes to pasta em nuvem, Google and OneDrive independently; a destination failure never undoes the restore; the pre-restore safety snapshot survives retention | DONE | **Fixed 2026-09-28 (extended batch, working tree only).** After `init_db()` the restored DB is snapshotted into a private work dir (not the local series) and handed to the shared `orchestrator._distribute_snapshot` (folder → Google → OneDrive → local retention), then the work dir is removed; outcomes are logged; distribution errors are caught after the restore. Pre-restore safety snapshot, validation, restore itself and both success messages unchanged (they only ever described the local safety snapshot). `app/views/admin/banco_dados.py` (one function body). Tests: `tests/test_restore_distribution_ui_c18.py` (13). **Retention residual resolved 2026-09-28 (user decision: the undo point must survive normal retention).** `app/db_maintenance.py` `apply_retention_policy` never returns a `pre-restore-safety` snapshot for deletion; it still occupies its bucket exactly as before, so every other snapshot is kept or thinned as the previous policy decided (proven against a verbatim copy of it), and the `manual-backup` exemption is unchanged. Remote provider retention is untouched — providers never receive this snapshot type. Tests: `tests/test_retention_pre_restore_safety_ui_c18.py` (15, incl. a real restore followed by a real scheduled cycle: the undo point survives, the older automatic snapshot is still thinned, the manual one kept); 8 of them fail on the previous policy |
| UI-C19 | Aluno → requisição → editar (data integrity; UI-C09 sibling) | `aluno_requisicao_detalhe` wrote `observacao` from `request.form.get` unconditionally, so an edit POST that omitted the field erased the stored observação | Missing → preserve; submitted empty → explicit clear; text → replace; ownership, the edit window and the snapshot activity lock still refuse before any write | DONE | **Fixed 2026-09-28 (second extended batch, working tree only).** `app/views/aluno.py`: the UPDATE writes `observacao = ?` only when the field is submitted, otherwise it self-assigns (keeping the SQL valid for the other fields and for the upload `finalize_db` path). Both student forms always submit the prefilled textarea (edit page; Pendente detail form), so the normal UI is unchanged, and an empty submission still stores empty, as before. Tests: `tests/test_aluno_requisicao_observacao_semantics_c09_sibling.py` (8: missing preserves while other fields update, an uploads-only POST preserves, empty clears, text replaces, the edit form always submits the textarea, another student / outside the edit window / a refused activity change write nothing); the two omission tests fail on the old handler. Backend-only, automated acceptance |
| UI-C20 | Admin → Requisições → processar (data integrity; UI-C09 sibling) | `admin_processar_requisicao` wrote `observacao` from `request.form.get` unconditionally, and the normal modal sends it only when the justificativa is non-empty — so every Deferir, Encerrar and Reabrir cleared the stored observação (the student's note, a student reply after Devolvida, or an earlier admin justification) | **Decided by the user 2026-09-28:** a processing action that omits `observacao` preserves the stored value; missing → preserve, submitted empty → explicit clear (the full-page processing form can submit it empty), text → replace (the modal's justificativa, as before). Never infer "clear" from a missing field | DONE | **Fixed 2026-09-28 (working tree only).** Audit: one column serves the student's note, the modal justificativa (sent as `observacao` only when non-empty; required for Parcial, Indeferida and Devolvida) and the full-page form (always submits the prefilled textarea); a final decision snapshots it into the e-mail event, whose "Justificativa" line is printed only for Parcial/Indeferida. There is no separate admin note field. `app/views/admin/requisicoes.py`: the UPDATE writes `observacao` only when the field is submitted; status, hours, processing date, admin, validations, permissions, event recording and its commit order unchanged. The modal and the Requisições floating bar are unchanged. Tests: `tests/test_requisicao_processing_observacao_ui_c20.py` (24: the exact Deferir/Encerrar/Reabrir payloads keep "Texto original"; the student still sees it; a status-only Deferida e-mail block carries no justification; empty clears; text replaces for Indeferida/Devolvida/Deferida; Parcial keeps its hours; a view-only admin and every refused transition write nothing); the three status-only cases and the student check fail on the old handler. Backend-only, automated acceptance. Residual (unchanged, not reachable from the UI): a direct POST of Indeferida/Parcial *without* a justificativa now keeps the stored note, which the decision event then records as its justificativa — the modal always sends one for those statuses |
| UI-B22 | Login → institutional name | The login subtitle reads "Faculdade de Tecnologia em Aviação Civil" (`templates/login.html`, `.login-subtitle`) | It must read "EJ - Faculdade de Tecnologia em Aviação Civil" | DONE_PENDING_VISUAL_CONFIRMATION | **Implemented 2026-09-28.** Owner: the literal `.login-subtitle` in `templates/login.html` (no config or shared branding variable exists; the string appears nowhere else). Heading "SGAA", recovery links, shell, spacing and typography unchanged. Guard: `test_login_institutional_name_is_exact_ui_b22` in `tests/test_login_identity_recovery_ui_c17.py` (exactly one subtitle, exact text). |
| DS-EMPTY-TABLE-STATE | Design System — empty state of every ordinary data table/list | With zero rows some surfaces still render the column-header row and then the empty-state phrase beneath it — e.g. Reportes: "# · Data · Categoria · Título · Status" followed by "Nenhum reporte enviado ainda." | One shared DS contract for all ordinary tables/lists: **row_count == 0** → no column-header row, only the surface's own empty-state message in its existing vocabulary ("Nenhum reporte enviado ainda.", "Nenhuma requisição encontrada.", …); **row_count > 0** → the normal table structure with headers. Fixed once at the shared list/table owner, never page by page | DONE_PENDING_VISUAL_CONFIRMATION | **Implemented 2026-09-28.** Owner: `components/card_list.html` `collection(rows, message)` (README §2.6c) — with rows it renders the caller (header + rows), with zero rows only `<div class="table-empty">message</div>`; no header, no fake colspan row. Migrated (each keeps its own wording): Alunos, Turmas, Cursos, Matrizes, Atividades, Requisições (admin/aluno), Reportes (admin/aluno), Alertas, Arquivos (admin/aluno), Acesso, Turma → alunos, Curso → turmas, Versões da atividade (versões/transições — already compliant, now through the owner), Atividades Acadêmicas/Extensão partial, Progresso and `components/list_table.html` (the last three had fake colspan rows). Inline empty styles and the page-local `.access-empty` / `.imp-curso-turmas-empty` gave way to `.table-empty`. Not changed, with reason: Banco de dados (retention = config grid; logs/snapshot history already conditional), diagnóstico (already conditional), CSV import preview (form step, no message), `admin_turma_form.html` (unrendered). Guard: `tests/test_ds_empty_table_state.py` (static ownership + zero/populated renders, Reportes explicit). The aluno Painel "Requisições Recentes" blocks (never functional) were removed by UI-B29. |
| UI-B23 | Aluno → requisição (criar/editar) — next-phase UX | (1) A student must be able to attach more than one comprovante to one request, and the form appears limited to one; (2) "Nome do evento" and (3) "Data do evento" are filled inconsistently with the proof because guidance is not visible while filling | **1. Múltiplos comprovantes:** audit backend/storage and create/edit semantics before any change (the file input already declares `multiple` and the handler reads `getlist("comprovantes_files")`, so the perceived one-file limit must be traced first); selected and existing attachments listed elegantly below the attachment control, one item per attachment, filename clearly visible, individual remove action (x/trash); adding another file never silently replaces the previous one. **2. Nome do evento — orientação contextual automática** (visible as soon as the request card/form opens, never only behind a help icon the student must discover): enter the event name exactly as it appears on the attached proof, not the regulation's generic activity name/category — e.g. palestra → the title/name of that specific lecture; horas de voo → the name of the course/training those flight hours refer to; an inconsistency with the proof may lead to summary denial (final wording per product). **3. Data do evento — orientação contextual automática** (also visible while filling): the date the event/activity actually occurred, consistent with the proof; for continuing/multi-event activities, the date of the final event/activity; never the request/submission date. Visual design to be defined in the next phase | DONE | **Implemented 2026-09-28; accepted by the user 2026-09-28.** *Trace:* storage was never single-file — the input already had `multiple`, both student handlers read `getlist("comprovantes_files")`, and `requisicao_arquivos` holds one row per file (no cardinality limit; stored names carry an operation-key suffix, so equal original names never collide). The limit was the page: a second picker interaction replaced the native FileList, 2+ files collapsed into "N arquivos selecionados" (names only in a `title` that `ui-tooltips.js` strips), and no stored comprovante could be removed individually. Edit already preserved stored files (append-only). No schema change. *Now:* `static/js/comprovantes-picker.js` — picking appends, the same file twice is kept once, every file is listed under the card (`.file-list`, `components/form.css`) with a real remove button named for it ("Remover comprovante <nome>"), and the submitted FileList is exactly the list. Stored comprovantes appear in the same list (links) in Editar; × only marks `remover_comprovantes=<id>`, applied on Atualizar. `app/comprovantes.py` `remove_comprovantes`: only submitted ids, each a current attachment of that request (else the whole edit is refused before any write), removed after the edit itself succeeded; Google → trashed remotely, row kept `trashed` (request-deletion custody); legacy local → row + file removed; a remote failure restores everything and says so. Batch validation unchanged (types, 16 MiB per file, one invalid file refuses the whole batch) but the message now names the file. Aggregate: the existing request-body limit (`MAX_CONTENT_LENGTH` 16 MB → "Arquivo muito grande…") — no new rule. Admin surfaces already looped every attachment (detail, processar, modal API) — unchanged. The Pendente detail page's plain input uses the same card + list. *Guidance:* `.form-note.form-note--guide` (a `.form-note` variant, tokens only, accent not invalid) under Nome do evento and under Solicitadas/Data, rendered whenever the form is editable (Nova/Editar; absent in Ver), linked by `aria-describedby`; no hover/tooltip/icon click. Texts: "Informe o nome exatamente como consta no comprovante — não o nome genérico da atividade no regulamento. Ex.: em uma palestra, informe o título da palestra; em horas de voo, o curso ao qual as horas se referem. Divergências podem resultar em indeferimento sumário." / "Informe a data em que a atividade ocorreu, conforme o comprovante — não a data da solicitação. Em atividades continuadas, informe a data da última atividade realizada." Tests: `tests/test_request_comprovantes_ui_b23.py`. |
| UI-B24 | Login → e-mail copy | The login e-mail field read "Seu e-mail institucional" (placeholder, `templates/login.html`) — false: students log in with their registered e-mail, not an institutional one | Visible copy "Entre com seu e-mail"; no "e-mail institucional/acadêmico/corporativo" rule anywhere on the login surface | DONE | **Fixed 2026-09-28.** Audit: the placeholder was the only occurrence on any login/auth surface (forgot/set password, first access and flashes carry no such rule; the two "institucional" mentions in Banco de dados describe a backup folder and were left alone). Placeholder → "Entre com seu e-mail"; label "E-mail", SGAA heading, "EJ - Faculdade…" subtitle, recovery links and auth behaviour unchanged. Guard: `test_login_email_copy_states_no_institutional_rule_ui_b24`. Note: the sibling password placeholder still reads "Sua senha". |
| UI-B25 | Aluno → Painel → "Para Corrigir" cards | The two dashboard cards over the retifiable requests were headed "Para Corrigir - Acadêmicas Complementares" / "Para Corrigir - Extensão Universitária" | Terminology: "Para Retificar" (copy only, no workflow change) | DONE | **Fixed 2026-09-28.** Owner: the two card-heading literals in `templates/aluno_dashboard.html` (not a shared token, badge, filter or status; no other surface says "Para Corrigir"). Now "Para Retificar - …", keeping the existing heading capitalisation of the sibling cards ("Limitações - …"). Which requests appear (Indeferida, processed < 30 days ago), the count, the days bars and the link to Minhas requisições are unchanged; no status, route or DB change. Guard: `tests/test_aluno_dashboard_retificar_ui_b25.py`. **Left as is (same concept, outside the literal brief):** the Resumo KPI label "Corrigíveis" and the empty states "Nenhuma requisição corrigível acadêmica./de extensão." inside those cards — change them to "retificável" wording only if the user asks. |
| UI-B26 | Upload cards ("Anexar") → keyboard access | The "Anexar" file cards could be used by mouse only: Tab never reached them and Enter/Space did nothing | Keyboard only: Tab reaches ONE upload control, it is announced as a button with a name, Enter/Space open the picker, Tab then walks the × remove buttons; mouse flow unchanged; existing DS focus treatment | DONE_PENDING_VISUAL_CONFIRMATION | **Fixed 2026-09-28.** Root cause: the shared primitive `.field-card.file-card .file-input{display:none}` (`modern-style.css`, copied in `form.css` for import modals and in three page `<style>` blocks) took the real `<input type="file">` out of the tab order, and the visible "Anexar" chip is a `<div>`; pages opened the picker from mouse click handlers only (a `required` file input could not even show its validation bubble). Fix at the owner, native first: the input stays in the card, visually hidden but focusable (clip technique), so it is the card's single keyboard target; Enter/Space open the picker natively; the card shows the standard `.field-card:focus-within` ring. The four copies were removed; page click handlers already ignore clicks whose target is the input, so keyboard activation opens the picker once. Every file card is covered: Nova/Editar requisição and the Pendente detail (comprovantes), Reportar (captura), admin Reportes/Arquivos/Requisições modals, Banco de dados restore, the Atividades import and — via the shared CSS only, files untouched — the protected Turmas import forms. Two inputs had no accessible name and got their visible field label: Reportar "Captura de tela", Arquivos "Arquivo" (others are named by `<label for>` or `aria-label`, e.g. "Comprovantes"). Tests: `tests/test_file_upload_keyboard_ui_b26.py` (static guards + headless keyboard: Tab, role/name, Space/Enter → file chooser, one stop, × via keyboard, mouse still opens once). **Residuals closed 2026-10-02:** `admin_turma_alunos.html` now reuses the published Turma import trigger (real `button` over the hidden input, exactly one focusable control) instead of the mouse-only `<label class="btn">` over a `display:none` input; the Banco de dados restore card no longer disables its chip/picker after a choice, so mouse and keyboard can both reopen/replace the selection while the chosen filename stays visible. Guards: `tests/test_file_upload_accessibility_residuals_ui_b26.py` (2 static + 1 headless mouse/keyboard). |
| UI-B27 | Aluno → Nova requisição → values after a rejected submit | A submission refused by the server (no/invalid activity, activity outside the matrix, invalid comprovante, snapshot or storage error) came back as an EMPTY form: the student lost everything typed | Every safe, redisplayable submitted field comes back; the native file input is legitimately empty and nothing claims a file is still attached; a failed submit stays all-or-nothing | DONE | **Fixed 2026-09-28.** Root cause: every rejection branch of `aluno_nova_requisicao` re-rendered the template without `init`, the only source the template and its JS prefill (Tipo → Grupo → Atividade) read. `_submitted_request_init` (in `app/views/aluno.py`) now rebuilds `init` from the submitted fields only — Tipo (known values only), Grupo, Atividade (an id, dropped when the matrix check refused it), Nome do evento, Solicitadas (h), Data do evento (ISO only), Observação — echoed through the template's escaping and `tojson`; nothing server-derived. The native file input and the comprovantes list start empty (browsers never let a page restore local files); the error still names the rejected file. Batch validation before any write, the new operation id per render and the delete-on-failure path are unchanged: a failed submit creates no request and stores no file; a corrected retry saves exactly once. Error/flash pattern unchanged. The Editar flow (redirect to the stored request) is unchanged. Tests: `tests/test_nova_requisicao_state_retention_ui_b27.py` (7 incl. a headless check that the re-rendered form reselects Tipo/Grupo/Atividade). |
| UI-B28 | Aluno → Nova requisição → Extensão activities unreachable | Found 2026-09-28 while tracing UI-B27. `aluno_nova_requisicao` lists activities filtered by the `?tipo=` query string, defaulting to "Acadêmica Complementar", and nothing links to the page with `?tipo=` (dashboard and Minhas requisições open the plain URL). The page's own Tipo select switches client-side only, so choosing "Extensão Universitária" shows no group and no activity: a student cannot create an Extensão request from the UI. Measured on the reference dataset: plain page 26 AAC / 0 AEU options; `?tipo=Todas` 26 AAC + 5 AEU. Canonical (read-only): 3 student-created requests, all AAC | `tests/test_ut_nr1_nova_requisicao_group_population.py` already states the contract — "Nova Requisicao must expose every Matrix activity… the server offered five AEU activities and the page let the student reach none" — but only the client-side group index was fixed then | DONE | **Fixed 2026-09-28.** Proven first: the matrix catalogue (`list_exact_matrix_activity_catalogue`) already returns every activity of the student's matrix with its authoritative type (from `eixo`); the only Acadêmica restriction was the helper's `tipo_atividade == tipo_filtro` step, fed by `?tipo=` (default Acadêmica), and it enforced nothing else — eligibility stays matrix membership (POST check) plus an active version (snapshot layer). `aluno_nova_requisicao` now lists the whole matrix (`"Todas"`) and the existing Tipo select filters it client-side (Acadêmica → AAC groups/activities only; Extensão → AEU only); `?tipo=` only preselects the Tipo (invalid values fall back to Acadêmica). Backend authority added: a submitted Tipo that contradicts the activity's own type (a crafted cross-type POST, either direction) is refused with the existing "Selecione uma atividade válida." and nothing is written; an activity outside the matrix is still refused; a POST without Tipo behaves as before. The UI-B27 re-render now restores an Extensão request as Extensão (Tipo, Grupo "NA", Atividade). Edit flow unchanged (it lists the request's own type; a versioned request's activity is immutable). Tests: `tests/test_nova_requisicao_extensao_ui_b28.py` (11; 7 of them fail on the previous code), incl. a real Extensão create with two comprovantes. |
| UI-B29 | Aluno → Painel → "Requisições Recentes" (Acadêmicas / Extensão) | Two blocks that never showed a column since the repository's first commit (the page set `cols_acad`/`cols_ext`, `components/list_table.html` reads `cols`); wired, they exposed an unfinished layout (Atividade 0 px at 1280 px), "Deferidas (h)" showing requested hours for Pendente requests and raw status text | **Product decision (user, 2026-09-28): remove the broken duplicate blocks; do not rebuild them. Minhas requisições remains the authoritative request list.** | DONE | **Removed 2026-09-28.** `templates/aluno_dashboard.html`: the two `<section>`s "Requisições Recentes - Acadêmicas Complementares / Extensão Universitária" and their page-local `.recentes-table` CSS. `app/views/aluno.py` (`aluno_dashboard`): the loop building `requisicoes_recentes_acad`/`_ext`, the unused `requisicoes_recentes`, and the three context values — nothing else read them. Kept: Resumo, the KPI cards and their "Ver requisições" links to Minhas requisições, Para Retificar, Limitações (all their data untouched), and `components/list_table.html` (a DS table; its empty-state contract is now tested on the component directly). No replacement card or text. The grid is simply two rows shorter (2 columns ≥ 921 px, 1 column below — no orphan). Tests: `tests/test_aluno_dashboard_recentes_removed_ui_b29.py` (blocks and their context gone, every surviving count/card/link unchanged with one Acadêmica + one Extensão request, no script error, grid at 1280/820 px). |
| UI-B30 | Turmas → Editar Turma (and every roster flow) → matrícula renumbered | Found by the `66be92f` import audit: saving Editar Turma without a file rewrote every roster matrícula to `<código>.NNN` in name order, overwriting institutional values such as `001234`; a later import restored them only through the e-mail fallback | A matrícula is identity, not a row number: a no-op, metadata, reorder, add or remove save never changes an existing student's matrícula; a new student keeps the matrícula it was created with; an explicit different value changes only that student, through the existing identity rules, atomically | DONE | **Fixed 2026-09-29 (`38f6caf`).** Cause: `resequence_turma_aluno_matriculas_for_ids` ended every roster mutation since the clean baseline (`dea3de5`); `efa5450` only narrowed it to saves without an imported file (that narrowing was what the student-import AST guard pinned as the "imported-row resequence boundary"), and `015ff99` had already removed it from Editar Aluno because renumbering contradicted the typed field. No document stated `<código>.NNN` as a product rule. The same call ran on Nova Turma, Novo Aluno into a Turma, Deletar Aluno and Acesso save/transfer, so all six call sites were retired; the helpers stay in `app.academics` (B6-P shared-owner re-exports) with no production caller. Governance: the AST guard now proves the exact baseline resequence statement is retired from both Turma handlers and rejects its reintroduction; `admin_deletar_aluno` is a declared bounded body change. Tests: `tests/test_turma_matricula_preservation.py` (GET → unchanged POST byte-for-byte, metadata incl. a código change, remove, add, reorder, import → save, e-mail re-import, intentional edit, in-roster and cross-Turma conflicts rolled back with the Turma UPDATE, credentials/tokens unchanged, Nova Turma, Novo Aluno, Deletar Aluno, Acesso rename/transfer, static no-call-site contract). Stored matrículas are never rewritten back — canonical values stay exactly as stored. Full suite at `659b69f` in a clean worktree: 3597 collected, 3461 passed, 136 skipped (88 = opt-in visual regression), 0 failed, 0 xfailed. Runtime smoke on the disposable :5000 harness (`SGAA_backups/turma_integrity_20260929/acceptance`, real login + CSRF): Editar Turma saved with a turno change kept `001234`, `ACE-0002`, `EJ/ADM/2024/0099`, `2019.1.0457-X` byte-for-byte |
| UI-B31 | Turmas → importar alunos (CSV/XLSX/XLS) → malformed rows | Found by the `66be92f` import audit: (a) e-mail format was not validated; (b) a header row repeated mid-file became a student "Aluno" / "E-mail" / "Matricula" | Reject the file at the true source row; nothing written (no student, Turma or credential change); no silent skip; no normalization beyond the existing strip; the preview agrees with the server; the optional first-row header is unchanged | DONE | **Fixed 2026-09-29 (`659b69f`).** File rows use SGAA's single e-mail rule, `is_valid_email` (`app/services/mail_service.py`, applied by every outbound mail path including the first-access e-mail) — no import-only regex. Any non-empty row after the first that the published `_looks_like_header` recognises is rejected as "cabeçalho repetido no meio do arquivo". Parsing fails before any write, so the modal import and Editar/Nova Turma (Turma UPDATE included) roll back entirely. Manual form rows keep the browser `type=email` contract. `static/js/student-import-preview.js` mirrors both rules with identical messages and order. Tests: `tests/test_student_import_row_validation.py` (3 formats × header/no-header through server and node preview; an e-mail corpus against `is_valid_email` on both sides; HTTP rollback over alunos, usuarios, usuario_credenciais, senha_tokens and turmas). Junk-row audit: whitespace-only rows are skipped; partially blank, duplicate, arbitrary-text and footer ("Total: 25") rows were already rejected deterministically; XLSX formula/error cells outside the matrícula column → UI-B34. Full suite: see UI-B30; the same runtime smoke refused both bad files in CSV, XLSX and XLS with nothing written, then imported the valid file (`IMP-0042`, `000777`) and an ordinary save kept every matrícula |
| UI-B32 | Acesso / credentials → first-access link after an e-mail change | Changing a student's e-mail (import update or manual edit) does not invalidate a first-access link already issued to the old address | Credential-policy decision: whether an e-mail change must invalidate outstanding first-access tokens. Separate phase | DONE | Recorded 2026-09-29 from the import audit; deliberately untouched by UI-B30/B31. Import e-mail updates never touch `usuario_credenciais`, senha or tokens by design (`66be92f` contract), and manual edit behaves the same. **Fixed 2026-09-29 (`18d9fda`).** Decision (user brief): a link mailed to the old address must stop working once the account address changes. Token audit: `senha_tokens` is the only e-mail-delivered credential (`first_access` 72 h, `password_reset` 60 min), bound to `usuario_id` alone; the recipient is `usuarios.email` at send time and is never stored; validity is expiry/consumption/`invalidated_at` (+ `pending` for first access), independent of `auth_version`. `app.user_accounts.set_usuario_email` is now the single writer of `usuarios.email` (static guard): a real change (case/space-insensitive, like every SGAA identity lookup) invalidates every outstanding link of the account through the existing `invalidated_at` revocation. Routed through it: import and Turma roster, Editar Aluno, Acesso, Aluno › Meus dados, Admin › Meus dados and the offline `migrate_root_admin_email`. Unchanged by design: hash, `estado`, `acesso_ativo`, `auth_version` (live sessions continue — the rule `migrate_root_admin_email` already documented), no automatic new link; revoked stays revoked; a refused or conflicting change rolls back with its transaction. Acesso needs no new text: a pending account whose delivered link was retired derives to "Expirado". Tests: `tests/test_email_change_token_invalidation.py` (24; 14 fail on the previous code). The root finding of this audit is UI-B36 |
| UI-B33 | Cursos → legacy 80 h extension default | `DEFAULT_CURSO_TOTAL_HORAS_AEU = 80` (`app/academics.py`) and the schema defaults `total_horas_aeu … DEFAULT 80` / `horas_extensao_obrigatorias … DEFAULT 80` (`app/prod1_schema.py`) still carry the legacy value | Decide the correct default and whether stored rows and schema defaults migrate; schema/migration implications need their own phase | DONE | Recorded 2026-09-29; deliberately not modified in the Turma data-integrity phase. **Fixed 2026-09-29 (`bb2bb32`), prod-1 → v12 (`extension_hours_default`).** Contract (user brief): 160 h for both kinds when no explicit value is given; explicit values stay authoritative; no backfill. Inventory: `DEFAULT_CURSO_TOTAL_HORAS_AEU = 80` (sole consumer: the bootstrap "Geral" course), `cursos.total_horas_aeu DEFAULT 80` (reached by Nova Curso, which inserts without hours), `matrizes_atividades.horas_extensao_obrigatorias DEFAULT 80` (no INSERT omits it today) and the historical `_MATRIZES_ATIVIDADES_V3_SQL` (v2→v3 step only; kept to reproduce the frozen v3 schema). The "Horas padrão" settings, the Matriz form and every student/dashboard calculation already used 160 or the matrix value. Constant → 160; both DEFAULTs → 160 through a v3/v11-style table rebuild (TEMP staging, foreign keys off, the canonical DDL shared with the bootstrap, rows, child references and AUTOINCREMENT counters re-verified, integrity and FK check, head digest `4aa56698…`). Proven on a byte copy of canonical: only `schema_migrations` gains row 12; idempotent through the dispatcher; a failure leaves v11 intact; the test-only inverse restores the frozen v11 digest. Canonical audit (read-only): 1 course (`PPA-NOT`) holds `total_horas_aeu = 80`, none 160; its matrices hold AEU 0 and 160. No form has ever written `cursos.total_horas_aeu` (provenance from the clean baseline on), so that 80 is a legacy default and no calculation reads it; it is left as stored — any correction is a separate, explicit data decision (UI-B37). **Canonical migrated to v12 on 2026-09-29** under custody (see the root identity & canonical v12 landing record): only `schema_migrations` gained row 12 and `PPA-NOT` still holds 80; the pre-v12 rollback copy stays in `SGAA_backups/identity_defaults_20260929/`. Tests: `tests/test_prod1_v12_extension_hours_default.py` (11) plus the declared version pins |
| UI-B34 | Turmas → importar alunos (XLSX) → formula/error cells outside the matrícula column | Found by the UI-B31 junk-row audit: the server reads XLSX with `data_only=False`, so a formula in Aluno or E-mail imports as its formula text (`=UPPER("bia")`; `="bia"&"@example.com"` even passes the e-mail rule) and an error cell (`#N/A`) in Aluno becomes the student's name. The preview reads the cached value instead (and refuses a formula saved without one), so the two disagree | Product decision: reject formula/error cells in every column, as the matrícula column already does, or import the cached value | DONE | Recorded 2026-09-29, not implemented (no established rule for these columns). CSV has no formulas; XLS (xlrd) yields cached values; an error cell in E-mail is already rejected by UI-B31. **Fixed 2026-09-29 (`1010280`).** Decision (user brief): reject — never evaluate, never use the cached value. A formula or error cell in Aluno, E-mail or Matricula rejects the file at the true row ("Linha N: fórmula ou valor de erro na coluna X; a importação aceita apenas valores digitados."), server and preview alike, by the reader's cell type: openpyxl `f`/`e` (XLSX); for XLS the sheet's BIFF `FORMULA` records (xlrd keeps only a formula's cached result) plus xlrd's error type; SheetJS `.f` / `t:'e'` in the preview, read a second time with `sheetStubs` so a formula saved without a cached value is still seen. A formula counts as content and is never a column name. CSV literal text is unchanged. Also closed: an XLS `#N/A` in Aluno used to become a student named "42". Modal import, Editar and Nova Turma write nothing and leave no upload. Tests: `tests/test_student_import_spreadsheet_expressions.py` (29; 27 fail on the previous code) |
| UI-B35 | Turmas → typed student rows (and every typed e-mail) | Found by the UI-B31 audit: file rows use `is_valid_email`, but typed Turma rows relied on the browser's `type=email` alone; a direct POST — or `a@b`, which browsers accept — stored a malformed address | The server is the authority: the same `is_valid_email` for every typed e-mail; refuse the request, name the row/student, write nothing | DONE | **Fixed 2026-09-29 (`3d58804`).** Proven first with direct POSTs on seven paths (Nova/Editar Turma rows, Novo Aluno, Editar Aluno, Acesso save, Aluno and Admin "Meus dados"): every one answered success and stored the malformed address. Turma rows go through the import normalizer ("Linha N (Nome): e-mail inválido." — the name identifies the student because the error page reloads the saved roster); the single-student forms refuse with "E-mail inválido." through `app.user_accounts.require_valid_email`. No new regex; a valid e-mail is stored exactly as submitted. Atomic: no Turma metadata, student, e-mail, roster removal, credential or token change. Canonical (read-only) holds no malformed address. Supersedes the UI-B31 note "Manual form rows keep the browser `type=email` contract". Tests: `tests/test_manual_student_email_validation.py` (23; 21 fail on the previous code) |
| UI-B36 | Admin → Meus dados → root administrator e-mail | Found by the UI-B32 root audit: Acesso refuses to move the root address, but Admin › Meus dados has no such guard. Proven on a disposable database: root saves a new e-mail, "Seus dados foram atualizados com sucesso.", and afterwards no account resolves as root (`resolve_root_admin_id` → None) — root protections and the master-key path are gone until the address is restored | Decision (user brief, 2026-09-29): the root e-mail is not editable through Meus dados; root identity moves only through the dedicated root migration (`migrate_root_admin_email`) | DONE_PENDING_VISUAL_CONFIRMATION | **Status corrected 2026-09-29 (documentation only):** the fix changes a visible surface (root's read-only e-mail on Meus dados) and the user has not yet confirmed it visually, so it cannot be `DONE` under this file's rules. Recorded 2026-09-29; deliberately not changed in UI-B32. **Fixed 2026-09-29 (`9af6ba2`).** For the root only (`is_root_admin`), Admin › Meus dados shows the e-mail read-only with the form's existing treatment — the same markup as the student's Matrícula (`control is-readonly`, `readonly aria-readonly="true"`), still visible, no added copy — and never calls `set_usuario_email`. A crafted POST that changes the address (case/space-insensitive identity) is refused with Acesso's existing catalogued message "O e-mail do administrador raiz não pode ser alterado por esta tela." and writes nothing (name, password and photo included); validation still runs first, so a malformed address is reported as "E-mail inválido.". Resubmitting the same mailbox in another case never rewrites the stored address. Unchanged: root's name, photo and password (a new password → `personal`, `auth_version` + 1, master key independent); ordinary admins and students still change their own address with UI-B32's link retirement; `migrate_root_admin_email` still moves root (links in the old mailbox retired, credential untouched) and the lock follows the identity to its new address. No catalog key added. On canonical (GET-only probe) root's Meus dados renders the e-mail read-only and a student's stays editable. Tests: `tests/test_root_email_profile_lock_ui_b36.py` (13, including a headless-Chromium paint check; 8 fail on the previous code) |
| UI-B37 | Cursos → existing course data → `PPA-NOT` stored Extensão total (80 h) | Canonical course `PPA-NOT` stores `cursos.total_horas_aeu = 80`, the legacy schema default when it was created; UI-B33 / prod-1 v12 changed only the default for future rows | Not a defect until product decides whether this existing course should hold 80 or 160. Any change is a separate, explicit data decision — no migration or backfill in UI-B33 or v12 | DONE | **LEGACY VALUE REPAIRED 2026-09-29 (authorised canonical data repair, with UI-B38).** `PPA-NOT` (id 2) `total_horas_aeu` 80 → 160 in the same guarded transaction (guard: id + code + name + current 80; exactly 1 row). No other `cursos` column or row changed; matrices and their assignments are untouched, and the operative Extensão requirement still comes from the assigned matrix — a separate follow-up audit, UI-B39. Non-visual: nothing renders or reads the column. Previously: **READY_FOR_DATA_REPAIR_DECISION — provenance `PROVEN_LEGACY_DEFAULT` (read-only forensic audit, 2026-09-29; the stored 80 is unchanged).** *Origin of the row:* the prod-1 canonical was created fresh on 2026-08-21, holding only `init_db`'s seed course ("Geral", id 1); `PPA-NOT` is id 2, created afterwards through Cursos → Adicionar, and it already existed on 2026-09-08 with 160/80. *Why the 80 was never chosen:* from `c9452b5` to HEAD the add handler inserts only `nome, codigo, duracao_periodos, status`, and the edit handler updates only those four columns, so the 80 is prod-1's `DEFAULT 80`, never a submitted value; the row equals the 160/80 defaults exactly. The earlier lineages carried 80 the same way: the predecessor course under `DEFAULT 80`, the June database via `ADD COLUMN … DEFAULT 80`. *Usage re-confirmed:* nothing reads the column; all 83 students resolve to matrix `01.2025` (Extensão 0) through their Turma, and `01.2026` (160) is assigned to no Turma or student. **DECISION REQUIRED — existing legacy value intentionally preserved.** Recorded 2026-09-29 while migrating canonical to v12; the stored 80 survived the migration unchanged. Context for the decision: no view, template or calculation reads `cursos.total_horas_aeu` (its only writer is `init_db`'s first-course seed; a course created in the UI takes the column default, now 160); the operative Extensão requirement is the matrix value — `PPA-NOT`'s matrices hold 0 (`01.2025`) and 160 (`01.2026`) — and the "Horas padrão" settings are 160/160. No code or data changed |
| UI-B38 | Alunos / Turmas → historical matrículas overwritten by the retired resequencer | Before `38f6caf` (UI-B30), roster flows renumbered a whole Turma to `<código>.NNN`, and canonical still holds those generated values. The open questions are which values replaced a real institutional matrícula, and whether the original can be recovered with high confidence | Read-only forensic audit first. Any restoration is a separate, explicitly authorised data repair: exact source values, one guarded transaction, rehearsed on a copy. No backfill and no inferred values | DONE_PENDING_VISUAL_CONFIRMATION | **DATA REPAIR COMPLETED 2026-09-29 (authorised).** *Decisions (user brief):* restore exactly the 77 CONFIRMED_RECOVERABLE rows in their exact source format. T10/T11 keep the hyphen (`…PPA-3.NNN`, 61) and T12 keeps the space (`…PPA 3.NNN`, 16). The one 2-digit tail is restored verbatim, with no padding. The conflicting, unknown and 4 legitimate/unproven rows stay untouched. *Execution:* one `BEGIN IMMEDIATE` transaction, held under the application's backup-cycle lock with the web runtime stopped; the scheduled task stayed enabled. All 77 guards were re-validated live first (identity, and no change since the audit: canonical was byte-identical to the audited file). Each UPDATE was guarded by id + usuario_id + current generated value and affected exactly 1 row. The run was rehearsed on a fresh byte copy, and a forced post-UPDATE failure rolled back byte-identically. *Proof:* a full before/after diff of all 31 tables shows only `alunos.matricula` × 77 and `cursos.total_horas_aeu` × 1 (UI-B37). The 6 excluded rows, e-mails, credentials, tokens, roster membership and matrices are byte-identical; integrity and FK checks are clean; the v12 schema digest is unchanged; content digest `3347788e…` → `2893cf4e…`. The pre-repair backup is in `SGAA_backups/canonical_data_repair_20260929/` (SHA-256 `ffde0b6e…`), and the next scheduled backup captured the repair (local + Google + OneDrive). On a copy of the repaired database, nine roster flows renumbered nothing: no-op save, metadata save, reorder, add, removal, rename, Turma move, delete and Nova Turma. A GET-only probe of canonical renders the restored values on every Turma page. *Pending:* the user's visual check. Previously: **READY_FOR_DATA_REPAIR_DECISION — audit complete 2026-09-29; canonical unchanged (content digest `3347788e…` before and after).** *Inventory:* all 83 canonical matrículas are generated, and in all three Turmas they equal the resequencer's output exactly (name, e-mail, id order). *Evidence:* 26 repo-local snapshots; 637 SQLite files, 220 of them holding canonical e-mails, including the predecessor system's databases from 2026-04-26 to 05-31; and the predecessor's 2026-05-19 export CSVs. Identity uses stable PKs inside the canonical lineage and a unique e-mail across lineages, never a name. *Two damage events:* the predecessor's 2026-05-19/20 clean-database import (T10/T11), and a typed roster save between 2026-09-13 17:31 and 2026-09-14 18:05 (T12). *Classification:* **77 CONFIRMED_RECOVERABLE** — T10 24 and T11 37, where the predecessor databases and the export agree exactly, plus T12 16 from the 2026-09-13 canonical snapshot. **1 CONFLICTING_EVIDENCE** — same digits, but the separator is `-` in one source and a space in the other. **1 LIKELY_DAMAGED_BUT_ORIGINAL_UNKNOWN**. **4 LEGITIMATE_OR_UNPROVEN** — 2 in-app test accounts and 2 students with no source. *Copy-only rehearsal:* 77 guarded updates changed only `alunos.matricula` (77 rows); integrity and FK checks pass, there are no duplicates, and credentials, rosters and requests are untouched; the Turma and student pages render the restored values. *Decisions required:* whether to restore at all; whether to keep the source formats (T10/T11 `…PPA-3.NNN`, T12 `…PPA 3.NNN`) or normalise them; how to resolve the separator conflict; and one original with a 2-digit tail to confirm with the institution. The candidate table and evidence contain personal data and stay outside Git in `SGAA_backups/forensic_matricula_20260929/` |
| UI-B39 | Cursos / Matrizes → `PPA-NOT` operative Extensão requirement | Observed while repairing UI-B37: `cursos.total_horas_aeu` now says 160, but nothing reads it, and a student's Extensão requirement comes from the assigned matrix. All 83 students resolve to matrix `01.2025` (Extensão 0) through their Turma, and `01.2026` (Extensão 160) is assigned to no Turma or student | Separate follow-up audit: which requirement `PPA-NOT` students should carry, and whether matrix assignments or matrix hours should change. Nothing changes without an explicit decision | BACKLOG | **READ-ONLY AUDIT 2026-09-29 → `LEGACY_CONFIGURATION_LIKELY` — ACADEMIC DECISION REQUIRED (status stays BACKLOG).** No canonical data, matrix, hour or assignment changed (content digest `2893cf4e…` before and after). *Resolution:* `app/student_matrix.py::get_effective_matrix_for_student` — a Turma-bound student is governed only by `turmas.matriz_id` (same Curso required); `alunos.matriz_id` answers only when `turma_id IS NULL`. No rule picks a matrix by status, vigência, name or cohort (FC-08: an explicit M1 remains M1 — `PROJECT_STATE.md`); status and vigência only order the Turma dropdown. Consumers: student dashboard (KPIs, total, Limitações), `/aluno/progresso`, new-request scope, admin Requisições, admin dashboard Turma cards; no report, export or completion calculation; `cursos.total_horas_*` unread. *Canonical:* T10 27 / T11 39 / T12 17 students all resolve to `01.2025` (AAC 160 / Extensão 0; 27 AAC items and **no Extensão activity**) through their Turma, no exceptions; the only explicit `alunos.matriz_id` belongs to the `example.invalid` test account and is ignored by the resolver. `01.2026` (160/160, `vigente`, from 2026-01-01; the same 27 AAC concepts, 13 of them in revised v2 rules, plus 5 Extensão activities) has never been referenced by any Turma or student. The names `01.2025`/`01.2026` have no documented meaning. On `01.2025` the student dashboard shows Extensão "0/0 h — 100% cumprido" while the admin Turma card shows AEU N/A. *History:* the predecessor app (April–August 2026) held `01.2025` 160/0 (AAC regulation rev5, where extension activities count inside AAC) → T10 (2025/1) and `05.2026` 160/160 (AAC rev6 + Extensão regulation rev1) → T11 (2026/1); T12 never existed there. Prod-1 re-created `01.2025` on 2026-08-29 with Extensão 0 entered explicitly (the form pre-filled 80). At 2026-09-13 17:31 no Turma had a matrix; `01.2026` — prod-1's re-entry of `05.2026` (same hours, same 5 Extensão activities, a few AAC limits differ) — was created at 17:38; by 2026-09-14 18:05 all three Turmas pointed at `01.2025`. No log records who made that assignment or why (successful Turma/Matriz saves are not logged). *Academic sources (local, readable):* AAC regulation rev5 and rev6 state 160 h for PPA with no cohort scoping; the Extensão regulation rev1 sets per-activity caps only, states no total and defers to the PPC; no CONSU approval act was found. The PPC/PDI files are cloud-only and were not opened. *Requests:* 3 in total, all AAC, from one T10 student (24 h approved); 0 Extensão requests and 0 approved Extensão hours. *Impact (copy-only simulation through the product resolver and real page renders):* T11 → `01.2026` (the only predecessor-backed change): 39 students gain a 160 h Extensão requirement (6 240 h outstanding) and 5 Extensão activities become requestable; adding T12 (cohort inference only, no precedent): 56 students (8 960 h). T10 sits on an Extensão-0 matrix in every lineage, so moving it is not supported by any evidence. The pending AAC request keeps its rule snapshot either way, and `01.2026` becomes frozen once assigned. **Decision needed (academic):** (1) are the 2026 cohorts — T11 `26.01.PPA` and T12 `26.02.PPA` — governed by the AAC rev6 + Extensão rev1 regime with a 160 h Extensão requirement, while T10 `25.01.PPA` stays on the rev5 regime (Extensão 0)? The PPC is the likely authority; (2) is `01.2026` as stored (its 13 revised AAC rules, vigência from 2026-01-01 where the predecessor used 2026-05-01) the matrix intended for them? A reassignment is one field per Turma (`turmas.matriz_id`); no student row changes. Private evidence: `SGAA_backups/ui_b39_matrix_audit_20260929/`. Previously: Recorded 2026-09-29 by user instruction (canonical data repair brief) as a follow-up audit item only. The repair deliberately left every matrix, matrix hour and assignment untouched; nothing else was inspected |


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
| List action | At UI-B05 implementation: `admin_editar_curso` + `{ view: 1 }`. Superseded by UI-C04: `admin_visualizar_curso`, a dedicated `cursos:view` route, renders the same accepted form |

Three further defects found in the turmas list on the same page and repaired:
`--imp-cols` had a fixed px maximum on all four tracks (396px of grid inside a
`width:100%` card, so the columns bunched left); `Status` sat in column 2 while
every other SGAA list ends with it; and `Ano/Semestre` read `t.semestre` /
`t.ano`, which the `turmas` table does not have (`semestre_inicio` /
`ano_inicio`), so every row rendered an em dash.

**UI-C04 follow-up.** `admin_visualizar_curso`
(`/admin/cursos/<id>/visualizar`) is now the list's GET-only `cursos:view`
destination and renders this same read-only form. Its declared governance
exception records that bounded body change. `admin_detalhes_curso`
(`/admin/cursos/<id>`) still works but remains unlinked; retiring it is a
separate governed decision.

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

### §UI-C01 — Matrizes de Atividades: Ver × Editar (consistency-audit reference case)

First case of the Ver/Editar consistency audit; the table below is the checklist
to replay against the other Ver/Editar pairs after visual acceptance.

**Architecture before.** One template (`admin_matriz_form.html`), one route
(`admin_editar_matriz`, GET=`matrizes:view`, POST=`matrizes:edit`), three tabs
(`dados` / `aac` / `aea`). The template already had a `readonly` flag, but it was
set **only** by RBAC (account lacks `matrizes:edit`). The list built
`view_url` and `edit_url` identically, so Ver never set it for editors.

**Could Ver persist? Yes (class C) for any editor**: Dados submitted the
`UPDATE`; the transfer form re-wrote the composition; the version modal posted
to `admin_matriz_nova_versao_card`. For view-only accounts it was already class D
server-side (POST refused by RBAC), but painted per-control, with a bottom Voltar.

| Element | Ver before | Editar before | Expected Ver | Repair |
|---|---|---|---|---|
| Header / Back | plain `h1` "Editar matriz…" | plain `h1` | `detail_header`, "Ver matriz de atividades", Back → Matrizes | `detail_header` in both modes (Curso precedent); Ver title from `readonly` |
| Main fields (nome, datas, horas, descrição) | editable (C) | editable | disabled via region | `fieldset.form-fieldset disabled aria-readonly="true"`; per-control `readonly` markers removed |
| Selects (curso, status) | editable (C) | editable | disabled via region | same fieldset |
| Read-only background | white | white | `--field-readonly-bg`, secondary text | shared READ-ONLY REGION rule in `components/form.css` — nothing page-local |
| Composition rows | checkbox + version select per row (C) | same | rows + version badge only | Ver renders the existing `composition_locked` branch |
| Add / remove (`>` `>>` `<` `<<`) | rendered, working (C) | rendered | omitted | not rendered; empty column loses its "Mover…" `aria-label` |
| Reorder | n/a — composition is an unordered set | n/a | n/a | — |
| Edit item (version `⋮` + modal) | rendered, posting (C) | rendered | omitted | not rendered (menu data not even computed) |
| Selection hidden inputs | rendered (C) | rendered | omitted | not rendered |
| Search / group filters | usable | usable | usable (read tools, not data) | unchanged |
| Help text "Selecione…" | shown | shown | omitted (instructs selection) | hidden when locked |
| Status | select | select | disabled select, same vocabulary | no semantics change (`status_presentation.py` untouched) |
| Save | present (C) | present | absent | footer is `{% if not readonly %}` |
| Footer | Voltar/Cancelar + Salvar | same | none | header owns Back |
| JS mutation hooks | `moveItems`, `syncHiddenInputs`, change handler, `openVersionModal` | same | not defined | existing `{% if not composition_locked %}` guards now cover view mode |
| Tabs | → Editar URLs | Editar URLs | stay in Ver | tab URLs carry `view=1` in view mode |
| "Seu acesso… somente para consulta" | RBAC viewers | RBAC viewers | only when access is actually limited | keyed on `access_readonly`, not on view mode |

**Backend.** Ver is a GET that only reads (proved: row + composition identical
after rendering all three Ver tabs). No route added; the write endpoints stay
authoritative — a consultive account is refused on POST with or without
`?view=1`, and on the version endpoint. An editor POSTing to `?view=1` by hand
gains nothing they do not already have in Editar, so no view-specific refusal
(and no new catalogued message) was added.

**Residual, deliberately out of scope:** (a) a frozen matrix (assigned to a
Turma) opened in **Editar** keeps its accepted lone bottom Voltar on the
composition tabs and its `aria-readonly` + `tabindex=-1` selects on Dados;
(b) Editar now also shows the header Back beside its bottom Voltar/Cancelar, as
Editar Curso does; (c) the other Ver/Editar pairs are not audited yet.

### §UI-C02 — Ver × Editar consistency audit (reference: UI-C01)

Method: static inspection of every admin list's Ver/Editar actions and their
routes, templates, JS and `app/auth.py` requirements, plus bounded probes. The
probes were a disposable copy of the canonical DB driven by the Flask test
client (no port, canonical untouched) and a standalone headless-Chromium repro
for implicit submission. No product code changed.

**Excluded (not a Ver/Editar pair):** Acesso (Editar only); Reportes (Ver-only
triage modal; its status form is `canReportesEdit`-gated); Configurações,
Mensagens, Meus dados (no Ver); dashboard "Ver …" shortcuts (links to lists);
student pages. `aluno_nova_requisicao?view=1` mirrors the student's own
Editar, so it is out of scope. It omits its submit button, so implicit
submission cannot fire there.

| Surface | Ver route/mode | Editar route/mode | Read-only fields | Mutation controls in Ver | Save in Ver | Header/Back | Footer | JS mutation | Persistence risk | Severity | Repair |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Matrizes de Atividades | `editar_matriz?view=1` | `editar_matriz` | fieldset region, `--field-readonly-bg` | none | none | `detail_header` → Matrizes | none | not emitted | none | **S0** (reference) | — |
| Cursos | `cursos/<id>/editar?view=1` | same, no flag | fieldset region | none | none | `detail_header` → Cursos | none | none | none, but GET needs `cursos:edit` → Consultor dead-ends | **S1** | UI-C04 |
| Alunos (list + Turma roster) | `editar_aluno/<id>?view=1` | same, no flag | per-control `readonly aria-readonly` → correct paint; selects shown as read-only text; password row omitted | none | none (no submit button, ≥2 text fields → no implicit submit) | plain `h1`, no header Back | generic bottom `← Voltar` | none | none, but GET needs `alunos:edit` → Consultor dead-ends | **S1** | UI-C04, UI-C06 |
| Atividades → Ver (catálogo hub) | `catalogo-versoes/<base>` | n/a (hub) | n/a — document/list renderer | Editar/Ativar/Suspender/Excluir/Criar versão ungated for view-only | n/a | `detail_header` → Atividades | none | lifecycle forms bound; server refuses view-only | none (endpoints need edit) | **S2** (view-only accounts) | UI-C05 |
| Atividades → Ver versão / Editar versão | `…/versoes/<v>/editar`, read-only by **state** (non-draft) | same URL, drafts only | fieldset region | "Nova versão" link in Ver | none | `detail_header` → activity | none in Ver | form-shaping only; controls disabled | none, but GET needs edit → Consultor dead-ends; switcher leaves Ver | **S1** | UI-C04, UI-C05 |
| Turmas | `turma/<id>` (detail + roster) | `editar_turma/<id>` | n/a — document renderer | roster actions belong to the Alunos resource and are RBAC-gated | n/a | page-local topbar, generic "Voltar" | none | n/a | none | **S1** (legitimate exception, header only) | UI-C06 |
| Requisições (modal) | modal `data-mode=view` | modal `data-mode=edit` | per-control `readonly`/`disabled` + `aria-readonly` (UI-H03) | comprovante **Abrir** (a read action) disabled via opacity | hidden but **live** submit + stale `form.action` | modal header | hidden by CSS | implicit Enter submission reaches the stale edit action | **yes** — overwrites a pending request, NULLs `observacao` | **S3** | UI-C03 |
| Alertas (modal) | modal `is-readonly` | modal edit | `readonly`/`disabled`, painted by a page-local `#f8fafc` clone | none (pickers disabled, dimmed `.5`) | save `hidden` + `disabled` | modal header | "Voltar" (renamed Cancelar) | pickers guarded | none | **S1** | UI-C07 |
| Arquivos | `arquivos/<id>/visualizar` → the file itself | modal on list | n/a — document | n/a | n/a | n/a | n/a | n/a | none | **S0** (legitimate exception) | — |

**Counts:** S0 2 · S1 5 · S2 1 · S3 1 (9 pairs). The Editar-locked Matriz case
(UI-C08) is separate and not counted.

**Shared root causes.**
1. *An editor endpoint serves as Ver without a GET/POST split.* One policy site
   (`app/auth.py`) breaks Ver for every view-only account on three surfaces
   (UI-C04). Matrizes already shows the split.
2. *Mutation affordances are not permission-gated in Ver*: the catálogo hub
   and Ver versão (UI-C05).
3. *Modal view modes are built by toggling controls, not by omitting them.*
   Requisições keeps a live submit and a stale action (UI-C03); Alertas keeps a
   page-local paint clone (UI-C07). A `disabled` default button blocks implicit
   submission; `hidden` or `display:none` does not.

**Legitimate exceptions:** the catálogo hub, Turma detail and Arquivos are
document or roster renderers rather than forms, so `.form-fieldset` does not
apply to them. They stay non-mutating through their own permission gating
(Turma, Arquivos; the hub once UI-C05 lands). Ver versão is read-only by version
state rather than by `?view=1`, which is correct because only unreferenced
drafts are mutable.

**Matrix linked to a Turma:** this is an **Editar locked-state** issue, not a
Ver/Edit one; Ver of a frozen matrix is fully correct. Tracked as UI-C08(a).

**Repair queue (current).** UI-C03 and UI-C04 are implemented pending visual
confirmation. Next: S2 UI-C05; then S1 UI-C06/UI-C07; Editar-locked UI-C08.

**Residuals, no item:** `admin_editar_atividade.html` is never rendered (the
route redirects to the catálogo editor and drops `view=1`), yet tests still
treat it as a read-only reference. `admin_detalhes_curso` has had no in-app link
since UI-B05. The latent server behaviour behind UI-C03 is that
`admin_editar_requisicao` writes an absent `observacao` as NULL.

### §UI-C04 — Ver routes require view, not edit

**Repair.** The presentation remains the accepted shared form; authority is no
longer inferred from a `?view=1` flag on an editor endpoint.

| Surface | Ver | Editar | Mutation authority |
|---|---|---|---|
| Cursos | `GET /admin/cursos/<id>/visualizar` → `cursos:view`; shared course form forced read-only | `GET/POST /admin/cursos/<id>/editar` → `cursos:edit` | delete stays `cursos:full` |
| Alunos | `GET /admin/visualizar_aluno/<usuario_id>` → `alunos:view`; used by the main list and Turma roster; shared aluno form forced read-only | `GET/POST /admin/editar_aluno/<usuario_id>` → `alunos:edit` | delete stays `alunos:full`; bulk status stays `alunos:edit` |
| Ver versão | `GET /admin/catalogo-versoes/<base_id>/versoes/<versao_id>/visualizar` → `atividades:view`; shared exact-version form forced read-only independently of version state | `GET/POST .../editar` → `atividades:edit`; eligible drafts remain editable | create/activate/inactivate/discontinue/delete/substitute stay `atividades:edit` |

The two new GET-only routes are in the canonical route inventory. The RBAC
requirement matrix and dynamic-route digests were deliberately re-anchored;
the denial-matrix digest is unchanged. A crafted POST to either view URL is
405, while POSTs to editor/mutation endpoints are refused by RBAC for a
Consultor before any write.

**Focused proof.** `tests/test_ver_routes_require_view_ui_c04.py` covers, for
all three surfaces: view-only Ver 200/read-only; Editar and direct mutation
refused with byte-for-byte database state unchanged; editor Ver read-only,
Editar writable and valid POST effective; no-permission Ver/Editar refused;
and every advertised Ver destination. Existing Curso, Aluno, version,
Matriz-Ver and Requisições read-only regressions remain green. No browser or
application-port validation was run; visual acceptance remains with the
architect. Final bounded lane: **479 passed / 8 browser tests deliberately
deselected / 0 failed**.

**Acceptance.** No Consultor exists in the canonical database. Create or use a
disposable `consultivo` account in Acesso, then verify Cursos → Ver, Alunos →
Ver, Turma → roster → Ver aluno, and Atividades → activity hub → Ver versão.
Each must open read-only with no Save; direct Editar URLs must return to the
dashboard. Repeat with an editor: Ver stays read-only and Editar remains
writable. UI-C05 is intentionally unchanged: mutation affordances on the
activity hub and the version switcher still need their own repair.

### §UI-C10 — manual backup independent of automatic-backup participation

**Reported:** "Enviar backup agora" disabled while "Incluir no backup automático"
is OFF, under the tooltip "Disponível quando o backup automático for ativado."

**Audit (every layer):**

| Layer | Owner | Finding |
|---|---|---|
| Manual button | `templates/admin_banco_dados.html` macro `provider_backup_now_button` | Gated only on `gdrive_connected` / `onedrive_connected` (configured app credentials + active account + readable token). Never read `*_enabled`. Disabled title: "Conecte o … para enviar backups" |
| Automatic switch | same template, both cards | **The defect.** `auto_backup_toggle_editable = false` was a template constant, so the switch always rendered `disabled` and `is-disabled`, and the label, switch and checkbox all carried the tooltip. No setting anywhere could make it editable: no in-app "backup automático" toggle exists. `*_enabled` was never stored in canonical (default `0`) |
| Front-end JS | inline scripts on the page | No logic touches the button or the switch |
| Manual endpoints | `admin_backup_google_upload`, `admin_backup_onedrive_upload` | Check only the active account, token readability and encryption readiness. Never read `*_enabled`. Correct, unchanged |
| Automatic selection | `orchestrator._maybe_upload_to_drives` (from `run_backup_cycle` / `app/backup/sync.py` and "Gerar backup agora") | Skips providers whose `<prefix>_enabled` is not `1`. Correct, unchanged |
| Card save | `admin_banco_dados_drive_settings` `save_credentials` | Writes `<prefix>_enabled` only when `<prefix>_enabled_submitted` is posted. Correct, unchanged |

The reported coupling was therefore perceptual. The permanently locked switch sat
beside the button with a tooltip that reads as a precondition. On 2026-09-26 the
Google button *was* disabled, but because Google's grant had expired
(`invalid_grant`), not because of the switch.

**Repair (template only):** the lock constant, its tooltip and the
`.db-provider-config-toggle.is-disabled` rules are removed. Both cards always
carry the `<prefix>_enabled_submitted` marker, so Salvar writes the switch
state. A POST without the marker still preserves the stored flag. No route,
view symbol or catalogued message changed. Layout, Salvar, fields, footer and
button styles are untouched.

**Tests:** `tests/test_manual_backup_independent_of_auto_ui_c10.py` (21).
For each provider:
- connected with AUTO off and on: button enabled, endpoint uploads, flag untouched;
- disconnected, or token unreadable: button disabled for an availability reason, endpoint refuses;
- the automatic cycle excludes a provider switched off and includes exactly the providers switched on;
- no stale tooltip; the switch is editable and carries the marker;
- toggling ON/OFF/ON through the card save never changes the button;
- a markerless save preserves the flag.

Against the HEAD template only the switch/tooltip test fails, which confirms
the button and both backends were already independent.

**Correction (2026-09-27, UI-C12):** the audit row "Automatic selection" above was true of `_maybe_upload_to_drives` only. `run_backup_cycle` reached it solely when the pasta em nuvem sync succeeded, so with no folder configured the automatic cycle uploaded nowhere. Repaired under UI-C12; the switch is authoritative for the automatic cycle only from that repair on.

**Acceptance:** `http://localhost:5000/admin/banco-dados`, with both providers
connected.
- AUTO off: "Enviar backup agora" enabled.
- Toggle the switch and Salvar: the button stays enabled.
- A real "Enviar backup agora" click is left to the user.

### §UI-C11–C13 — backup destinations and their trigger

**Execution graph before the repair**

- "Gerar backup agora" (`admin_banco_dados_backup`): local snapshot → pasta em nuvem sync (`force=True`) → external server → **message chosen here** (from the external result, else from the folder result) → local retention → Google/OneDrive (`_maybe_upload_to_drives`, result discarded).
- Automatic cycle (`run_backup_cycle`, via `python -m app.backup.sync`): pasta em nuvem sync → only **if it succeeded and was not skipped**: local retention → Google/OneDrive with the *folder* snapshot. No local snapshot at all.
- Why the chain existed: the pre-UT-5 `after_request` hook used the folder sync as its change-detection/cool-down gate and as the producer of the artefact. The CLI calls it with `force=True`, so the gate no longer did anything there; only the artefact dependency remained — no folder, no upload.

**After the repair**

- Both paths create a local snapshot first; `_distribute_snapshot` then runs pasta em nuvem → Google Drive → OneDrive → local retention. Each destination returns its own outcome; remote retention runs only for a provider whose upload succeeded. A provider counts as `success` from the moment it accepted the file, even if the local bookkeeping write afterwards fails.
- The manual route adds the external server (unchanged contract: never part of the automatic cycle), then chooses **one** message from all outcomes:
  - sent only → "Backup local criado e enviado para {destinos}." (success)
  - sent and failed → "Backup local criado e enviado para {destinos}, mas o envio falhou para {destinos}." (warning)
  - failed only → "Backup local criado, mas o envio falhou para {destinos}." (warning)
  - nothing attempted → "Backup local criado. Nenhum destino em nuvem está configurado para receber backups." (info)
- `unchanged` / `deferred` exist only for the pasta em nuvem (signature / minimum interval, and only without `force`); they never gate the providers and never reach a message.
- A provider switched on without application credentials is `skipped_not_configured`; one that is configured but not usable (e.g. needs reconnecting) is `failed`.

**Retention.** Local retention now applies the same policy to each location separately (local, pasta em nuvem), as remote retention already runs per provider. The automatic cycle creates a local `auto-backup` snapshot next to the folder copy, and one combined series let the two compete for a single 2-hour slot, deleting the fresh local file. Snapshots are also handed to the policy newest-first by file name, so a same-second tie keeps the newest. `manual-backup` snapshots stay exempt; `apply_retention_policy` itself is unchanged.

**Scheduler (UI-C13).** Intended trigger since UT-5: the external command `python -m app.backup.sync`. No installer, registration or scheduled task exists in the repository and none is registered here, so the missing task is a product gap, not a lost local configuration. Nothing was installed. *Update 2026-09-28:* implemented without a second schedule. A polling task wakes `python -m app.backup.sync --scheduled`, and the SGAA's own `cloud_sync_interval_seconds` decides whether a backup is due. The task is not installed yet. See the UI-C13 row and `docs/backlog/UI_C13_SCHEDULER_DECISION_MEMO.md`.

**Residual, not repaired:** a restore (`_restore_database_from_source`) still sends the providers only the folder snapshot, so with no folder configured a restore uploads nothing to the cloud.

### §UI-C14 — error pages on the shared Design System

**Architecture before.** Three unrelated surfaces and a gap:
- 400: standalone `templates/400.html`, rendered only by the CSRF handler (`app/__init__.py`), with a 90-line page-local `<style>`: raw-hex gradient body, an orange `#fcd34d/#fffbeb/#92400e` badge, a `#f8fafc` note box, its own card, its own button min-width and icon margin.
- 500: standalone `templates/500.html` whose `<style>` redefined `.card` and `a.btn` (`#1e7bf6`, `#5a6270`, `#f5f6f8`) and labelled a link to `/` "Voltar".
- 404: extended `base.html` with an inline style and linked to `admin_dashboard` for everyone.
- 403: no handler and no template.

**After.** `templates/error_page.html` is the single owner; each code template only fills `page_title`, `error_code`, `error_title`, `error_message` and, for 400, `error_note` and `error_actions`.

| Element | Before (400) | DS owner now |
|---|---|---|
| Page / card | local shell, gradient, local card | `.login-page` / `.login-card` — the shared public-page shell of login, forgot and set-password |
| "Erro 400" | local orange badge + icon | `.badge.status-pill.status-negative` |
| Title / copy | local 28–34px title, local copy | `.login-title` / `.login-subtitle` |
| Help block | local bordered `#f8fafc` box | `.flash.flash-info` (as `matriz-tab-notice` already uses it), `role="note"` |
| Actions | `.btn` + local min-width / icon margin | `.btn.primary` / `.btn` with `.btn-label`; icon size and gap from `.btn .lucide` |

The only local CSS left is three layout rules (pill spacing, note spacing, centred action row) with no colour, border or font. The pill uses the status pill's own dot, so the badge icon is gone.

**Navigation.** 400 keeps "Abrir tela anterior" (referrer) as primary and "Ir para o início" as secondary. Home is now role-aware on every page: `/admin/dashboard` for an admin session, `/aluno/dashboard` for a student, `/` otherwise. Before, `/` put a signed-in user on the login form, and 404 sent students to the admin dashboard. Single-action pages (403/404/500) show "Ir para o início" as the primary action. 500 already rendered its only action as a filled blue button; the label "Voltar" became "Ir para o início" because the link always went home.

**Unchanged.** CSRF handling (`_handle_csrf_error`, its log line, status 400 and message), the 404/500/413 handlers, the literal-path / no-`url_for` contract of error pages.

**403.** `abort(403)` (file and comprovante access checks) now renders the shared page through `app.web.errors.forbidden`, registered beside 404/500 in `main.py`; its minimal fallback string is catalog term UI-C14 (+1, 583). The request-hook audit set lists the new handler.

### §UI-C05 — Atividades hub and Ver versão: no mutation for view-only

**Architecture.** `/admin/atividades` (list, already gated: edit/nova-versão/ver-versões need `edit`, import/delete need `full`) → hub `/admin/catalogo-versoes/<base>` (`admin_catalogo_versao_detalhe.html`, `atividades:view`) → Ver versão `/versoes/<v>/visualizar` and Editar versão `/versoes/<v>/editar`, both rendered by `admin_catalogo_versao_form.html` through `admin_catalogo_editar_versao` (Ver = `force_readonly`). Hub row actions are one JS floating toolbar driven by `data-*` attributes and hidden per-row POST forms.

| Action | Class | Before (view-only) | After (view-only) | Editor |
|---|---|---|---|---|
| Ver (hub toolbar) | READ | only for non-drafts | every version, drafts included | unchanged (non-drafts; drafts open in Editar) |
| Criar versão (hub) / Nova versão (Ver/Editar) | WRITE | rendered | not rendered | unchanged |
| Editar, Ativar, Inativar, Substituir, Descontinuar, Excluir | WRITE | toolbar buttons + hidden forms + modal + `data-version-edit-url` in the DOM | none of them in the DOM | unchanged, still by version state |
| Version switcher | READ | always → `/editar` (refused, or silently left Ver) | Ver → `/visualizar` | Ver → `/visualizar`, Editar → `/editar` |
| Ver's `<form>` | — | `action=".../editar" method="post"` + CSRF | no action, no method, no CSRF | Editar unchanged |

**JS.** One script, not a fork: the toolbar markup renders write buttons only for editors, `syncActions` tolerates their absence, and the substitute-modal handlers are wired only when the modal exists.

**Backend.** Unchanged and proven: create version, edit, activate, inactivate, discontinue, substitute and delete still require `atividades:edit` (crafted view-only requests → 302 to the dashboard, data unchanged); hub and Ver stay `atividades:view`; a user without `atividades` is refused as before. The view passes its existing `view_mode` to the template (one keyword).

**Residuals.** UI-C08 unchanged: an active version's Editar is read-only by state yet keeps its save target, and the list's Editar on an active version lands on that state-locked page. The legacy list Ver for an activity without a catalog base still targets `admin_editar_atividade?view=1` (edit-gated). Test pin retargeted: `test_ver_versao_readonly_presentation.py` located the Ver form by `<form action=`, which Ver no longer has.

### §UI-C06 — Aluno and Turma on the shared detail header

**Before / after.**

| Page | Header before | Header after | Bottom actions before | After |
|---|---|---|---|---|
| Ver Aluno (`/admin/visualizar_aluno/<id>`) | plain `h1.main-title` "Ver Aluno" | `detail_header("Ver Aluno", back, label)` | generic "Voltar" (to `return_to` or Alunos) | none — the header Back replaces it |
| Editar Aluno (`/admin/editar_aluno/<id>`) | plain `h1.main-title` "Editar Aluno" | `detail_header("Editar Aluno", back, label)` | Cancelar + Salvar | Cancelar + Salvar, unchanged (form contract; Cancelar keeps the same target) |
| Turma (`/admin/turma/<id>`) | page-local `.turma-topbar`: `h1` "Turma" + turma picker + spacer + generic "Voltar" (to Turmas) | `detail_header("Turma", Turmas, "Turmas")` with the picker in its trailing slot | none (the "Voltar" was in the top bar) | none |

**Back target.** Unchanged targets, contextual labels. Both the Alunos list and the Turma roster open Ver/Editar Aluno with `return_to` (`navigateWithReturnTo`), so no new navigation state was needed: the label is "Turma" when `return_to` is a `/admin/turma/<id>` roster and "Alunos" otherwise; the href is the same `return_to or admin_alunos` the old footer used. No JS history emulation.

**Shared owner.** `components/detail_header.html` unchanged — the trailing slot it already offers (used by Ver versão for its status pill) carries the turma picker. Removed: `.turma-topbar` / `.turma-topbar-spacer` CSS, the inline `padding:1rem; text-align:center; color:#6b7280` empty state (now the shared `.table-empty`, whose colour is `var(--text-secondary)`, the same value).

**Catalog.** The bottom `user_message("Voltar")` was that literal's only consumer: term UI-C06 retires it (−1, 582). "Alunos" and "Turma" were already catalogued.

**Overlap.** Neither touched template belongs to the protected student-import candidate; both already carried accepted UI-C04 hunks (Aluno's `force_readonly` line, the roster's Ver → `admin_visualizar_aluno`), preserved unchanged. Test pin updated: `test_ver_aluno_view_presentation.py` looked for the literal "Voltar"; it now looks for the header Back.

**Residuals (not touched).** `return_to` is used as an href without validation — pre-existing, shared with Curso Ver/Editar and the old footer; worth a separate review. Roster, its actions, import controls and permissions unchanged. DS-PILL-RADIUS stays deferred.

### §UI-C07 — Alertas Ver on the shared read-only contract

**Architecture.** `/admin/alertas` → one shared modal (`components/modal.css`) for Novo / Ver / Editar, switched client-side by `setModalMode`; Ver is `.modal-card.is-readonly` plus `readOnly` inputs, disabled pipettes/swatches/switch, Salvar hidden+disabled, Cancelar relabelled "Voltar"; a view-mode submit guard and a view-mode picker guard already existed. Backend unchanged (`admin_salvar_alerta` still `alertas:edit`).

| Element (Ver) | Before | After |
|---|---|---|
| Título, Mensagem | `.modal-card.is-readonly .control{background:#f8fafc; color:var(--text-secondary)}` — a raw clone that also overrode form.css (same specificity, later) | form.css `.field-card:has(.control[readonly])` → `--field-readonly-bg`, control `--text-secondary`; `aria-readonly="true"` declared |
| Fundo / Borda hex fields | readonly text, normal group paint | the same tokens restated on the custom group (`--field-readonly-bg`, `--text-secondary`) — the group is not a `.field-card`, so it cannot inherit by structure |
| Pipette buttons | `pointer-events:none; opacity:.5` | omitted (`hidden` + `disabled`): mutation-only affordance |
| Palette swatches | disabled, but hover still lifted them | disabled and inert (no hover lift), fully legible — they show the chosen colour |
| Form target | `action=".../alertas/salvar"` kept | no `action` in Ver; restored on Editar/Novo |
| Dead rule | `.modal-card.is-readonly .swatch-option` (no such element) | removed |

Kept on purpose: `.modal-card.is-readonly #admin-alerta-save{display:none !important}` is load-bearing (`.btn` sets `display` and there is no global `[hidden]` rule), not a DS duplicate.

**Preview.** Unchanged: the recipient preview renders the MESSAGE only; the internal title never appears in it (UI-B04 tests unchanged and green).

**Residuals for UI-B11 (not touched).** Page-local raw colours outside the read-only paint: the selected-swatch outline `#0f5b99`, `.alerta-color-dot` border `rgba(0,0,0,.12)`, the list swatch `.alerta-color-swatch.border-only{background:#fff}`. The visibility switch in Ver uses the shared disabled toggle (`form.css`), which only changes the cursor — a DS-level question, not an Alertas clone.

### §UI-C08 — state-locked records: Editar must match real mutability

**Versão — authoritative rule** (`app/activity_catalog.py::can_activity_version_be_mutated_in_place`, used by `admin_catalogo_editar_versao`): editable in place **only** when `status == 'rascunho'` **and** nothing references it — no requisição, no transition in or out, no successor (`versao_anterior_id` pointing at it), not linked from an assigned Matriz. Everything else (every active/inactive/discontinued/substituted version, and referenced drafts) is **fully** locked: a POST to its `/editar` returns before any write ("Apenas versões em rascunho…" / "Esta versão já está em uso…"). The only legitimate change is a successor via "Nova versão" (separate action, unchanged).

**Versão — misleading actions found and repaired.**

| Entry point | Before | After |
|---|---|---|
| Versions hub toolbar | Editar for every draft (`status === 'rascunho'`), even referenced ones; Ver hidden for drafts | Editar iff `data-version-editable="1"` (server-computed by the canonical rule); Ver for every non-editable version (or any version for view-only users); `data-version-edit-url` only for editable versions. Ativar/Inativar/… state rules unchanged |
| Atividades list row bar | Editar opened the row's version editor even when it was locked (typically the active current version) | rows carry `data-editable`; Editar hidden for a locked versioned row (Ver → hub remains). Rows without a catalog base unchanged (UI-C15) |
| Direct `/editar` of a locked version | rendered read-only but titled by state, kept `action`/`method`/CSRF, switcher stayed on `/editar` | renders the Ver page in place — the pattern `/visualizar` and `?view=1` already use (UI-C01/C04/C05): "Ver versão", no save target, switcher → `/visualizar`. Chosen over a redirect because it is the form's existing read-only mode and leaves the POST path untouched |
| Version switcher in Editar | every target → `/editar` | options carry `data-editable`; a locked target opens `/visualizar`, an editable draft stays `/editar` |

Backend unchanged: locked POSTs still refused with data unchanged; the editable draft still saves in place.

**Matriz — authoritative rule** (`app/matrix_scope.py::is_matrix_assigned`: a Turma **or a student** points at the Matriz). When assigned:
* **Dados:** six protected fields are frozen — `curso_id`, `status`, `data_inicio_vigencia`, `data_fim_vigencia`, `horas_aac_obrigatorias`, `horas_extensao_obrigatorias` — enforced in `admin_editar_matriz` (a change → "Parâmetros inválidos.", the same text as a generic invalid payload). **`nome` and `descricao` remain legitimately editable** and save.
* **Composição (AAC/AEA):** fully frozen — `_save_matriz_activity_links` refuses, `_set_versao_da_matriz_para_base` raises `AcademicGraphFrozenError` (card relink refused).
* **Exclusão:** refused.

**Matriz — why no change was made.** The brief's rule: if fields remain legitimately editable after linkage, stop and document before changing the UI. They do (Nome, Descrição), so the Matriz is *not* fully immutable and must not be turned into Ver. Current presentation (confirmed): Curso/Status selects carry `aria-readonly` + `tabindex=-1` but stay **enabled** (the mouse still changes them; the select's value precedes a hidden duplicate in the POST, so the save is refused); both dates and both hour fields are fully enabled; composition tabs are read-only with a notice and a lone bottom "Voltar" (a template comment records that Voltar as previously accepted).

**Decision needed (recommendation first).**
1. **Keep "Editar" for an assigned Matriz** (it is a real edit of Nome/Descrição) and present the six protected fields through the shared read-only contract (`disabled aria-readonly="true"` / `readonly`, values still submitted unchanged so the backend comparison passes), with a short notice; composition tabs stay read-only. No state or permission change.
2. Offer Ver for an assigned Matriz in the list and move Nome/Descrição editing elsewhere — a product change, not recommended.

**Matriz — decided and implemented (same day).** Decision: a linked Matriz stays **editable** (Nome, Descrição), so the page keeps "Editar"; recommendation 1 above was taken.

| Field / area (linked Matriz) | Before | After |
|---|---|---|
| Nome, Descrição | editable | editable (unchanged) |
| Curso, Status (`<select>`) | `aria-readonly` + `tabindex=-1` but **enabled** — the mouse still changed them; a hidden duplicate followed | `disabled aria-readonly="true"` (form.css DISABLED-BUT-READ-ONLY paint); the existing hidden mirror is now the only submitted value — the established frozen-value pattern of this form |
| Início/Fim de vigência, Horas AAC/AEU (`<input>`) | fully editable | `readonly aria-readonly="true"` (shared read-only paint; read-only inputs still submit, so no mirror needed) |
| Save | Salvar | Salvar (unchanged) — a Nome/Descrição change saves; protected values reach the backend unchanged |
| Composição AAC/AEA | read-only (no form, no move/version controls, no hidden `selected_activity_ids`, mutation JS already gated) + a lone bottom "Voltar" | same read-only composition, **no footer**: the header Back ("Matrizes") owns navigation (UI-C01/C06 contract) |

Backend unchanged and proven: Nome/Descrição saves on a linked Matriz; crafted changes to Curso, Status, a date or an hour field are refused with the row unchanged; a composition POST is refused; an unlinked Matriz stays fully editable (fields, composition controls, Cancelar + Salvar).

**Residuals.** "Parâmetros inválidos." for the frozen case is left as is (reached today only because the UI offers impossible edits; option 1 removes that path). UI-C15 (base-less activities) untouched.

## Changelog

- 2026-10-02 — **UI-B26 upload residuals closed (working tree only).** The two recorded residuals were reproduced on HEAD and repaired with already-published patterns: the orphaned `admin_turma_alunos.html` import now uses the Turma import candidate's real-button-over-hidden-input trigger (one focusable control, Enter/Space native) instead of the mouse-only label; the Banco de dados restore card no longer marks its chip disabled or blocks `openPicker` after a file is chosen, so mouse and keyboard both reopen/replace the selection (keyboard already did). No import semantics, no restore action, no data or schema touched. Guards: `tests/test_file_upload_accessibility_residuals_ui_b26.py` (3; the disabled-chip and mouse re-open checks fail on the previous code). UI-B26 stays DONE_PENDING_VISUAL_CONFIRMATION.
- 2026-09-29 — **UI-B11 → SAFE_COHORT_COMPLETE — REMAINDER_NEEDS_SEMANTIC_TOKEN_DECISIONS.** A second category-A cohort replaced 28 raw colours with existing tokens / the shared status-pill properties (458 → 430). No safe replacement remains. The remaining 430 are component-local (30), content (7), proven dead and parked (4), or waiting for a semantic-token or visual decision (389), each group with its reason in `UI_B11_RAW_COLOUR_AUDIT.md`. Zero visual change: computed styles and screenshots were compared on a disposable runtime. Frontend only: no canonical data, schema or migration touched.
- 2026-09-29 — **UI-B39 forensic audit (read-only; no code or canonical data changed).**
  - All 83 students resolve to `01.2025` (Extensão 0) through their Turma; `01.2026` (Extensão 160) has never been assigned.
  - The predecessor app assigned T11 to its Extensão-160 matrix and T10 to `01.2025`; prod-1 put all three Turmas on `01.2025` on 2026-09-13/14, with no recorded reason.
  - No readable academic document states the Extensão total or its cohort scope; 0 Extensão hours have been approved.
  - **UI-B39 → `LEGACY_CONFIGURATION_LIKELY`, ACADEMIC DECISION REQUIRED** (status stays BACKLOG). UI-B36 and UI-B38 remain DONE_PENDING_VISUAL_CONFIRMATION.
- 2026-09-29 — **Canonical data repair (authorised; no code changed).** A pre-repair backup sits in `SGAA_backups/canonical_data_repair_20260929/`.
  - 77 proven matrículas restored to their exact historical values; source separators kept, nothing normalised.
  - The 6 other students (1 conflicting, 1 unknown, 4 legitimate/unproven) were intentionally left untouched.
  - `PPA-NOT` `total_horas_aeu` 80 → 160.
  - No other canonical business data changed: the full-table diff shows exactly 77 + 1 cells.
  - **UI-B38 → DONE_PENDING_VISUAL_CONFIRMATION** (data repair completed). **UI-B37 → DONE.** **UI-B39 opened (BACKLOG):** a follow-up audit of `PPA-NOT`'s matrix Extensão requirement.
- 2026-09-29 — **Forensic audit (read-only).** Canonical data, every matrícula and `PPA-NOT`'s 80 are unchanged; no code changed.
  - **UI-B38 opened (BACKLOG — READY_FOR_DATA_REPAIR_DECISION):** 77 of the 83 generated matrículas have a recoverable original, rehearsed on a copy only.
  - **UI-B37 → READY_FOR_DATA_REPAIR_DECISION** (`PROVEN_LEGACY_DEFAULT`; status stays BACKLOG).
  - **UI-B36 DONE → DONE_PENDING_VISUAL_CONFIRMATION:** a visible surface that the user has not yet confirmed visually.
- 2026-09-29 — **Canonical migrated to prod-1/v12** under custody through the normal startup path, without pausing the automatic backup; every stored row kept, `PPA-NOT` still 80. **UI-B37 opened (BACKLOG — DECISION REQUIRED):** whether that existing course keeps 80 h or moves to 160 h.
- 2026-09-29 — **UI-B36 → DONE** (`9af6ba2`). Root's e-mail is read-only on Admin › Meus dados and a crafted change is refused; `migrate_root_admin_email` remains the only way to move root.
- 2026-09-29 — **UI-B36 opened (BACKLOG).** Root can move its own address through Admin › Meus dados, which leaves the installation without a root; decision required.
- 2026-09-29 — **UI-B33 → DONE** (`bb2bb32`). prod-1/v12: new courses and matrices default Extensão to 160 h; every stored value kept; canonical migrates on its next launch.
- 2026-09-29 — **UI-B32 → DONE** (`18d9fda`). An e-mail change retires every link mailed to the previous address; credential and sessions untouched.
- 2026-09-29 — **UI-B34 → DONE** (`1010280`). Formula and error cells rejected in every student column, server and preview.
- 2026-09-29 — **UI-B35 → DONE** (`3d58804`). Typed e-mails validated server-side on every manual path.
- 2026-09-29 — **UI-B30 → DONE, UI-B31 → DONE** (`38f6caf`, `659b69f`, recorded by `616374e`). Closed; not reopened by this phase.
- 2026-09-28 — **UI-B29 → DONE (user decision).** The broken "Requisições Recentes" dashboard blocks and the view data that fed only them were removed; Minhas requisições remains authoritative.
- 2026-09-28 — **UI-B28 → DONE.** Nova requisição lists the student's whole matrix and the Tipo select filters it, so Extensão requests can be created; crafted cross-type POSTs are refused.
- 2026-09-28 — **UI-B29 opened: DASHBOARD_RECENT_REQUESTS_DECISION_REQUIRED.** The aluno Painel "Requisições Recentes" blocks have never rendered since the first commit; the intended output is not unambiguous (layout, deferred-hours meaning, status pill, duplication of Minhas requisições). No product change.
- 2026-09-28 — **UI-B27 → DONE.** A rejected Nova requisição keeps the student's values (files must be picked again). **UI-B28 opened (BACKLOG):** the plain Nova requisição page offers no Extensão activities.
- 2026-09-28 — **UI-B26 → DONE_PENDING_VISUAL_CONFIRMATION.** Upload cards keyboard accessible: the real file input is the card's single focus target (visually hidden, not display:none).
- 2026-09-28 — **UI-B25 → DONE.** Student dashboard card headings "Para Corrigir" → "Para Retificar" (copy only).
- 2026-09-28 — **UI-B23 → DONE (accepted by the user). UI-B24 → DONE.** Login e-mail placeholder "Seu e-mail institucional" → "Entre com seu e-mail".
- 2026-09-28 — **UI-B23 → DONE_PENDING_VISUAL_CONFIRMATION.** Several comprovantes per request with an appendable, removable file list; explicit removal of stored comprovantes on Editar; automatic Nome/Data do evento guidance. No schema change.
- 2026-09-28 — **DS-EMPTY-TABLE-STATE → DONE_PENDING_VISUAL_CONFIRMATION.** One owner (`cl.collection`) for the empty state of every ordinary list/table: zero rows → only the surface's own message, no header. Residual recorded: the dormant aluno Painel "Requisições Recentes" tables.
- 2026-09-28 — **UI-B22 → DONE_PENDING_VISUAL_CONFIRMATION.** Login subtitle now reads "EJ - Faculdade de Tecnologia em Aviação Civil" (template literal, its only owner).
- 2026-09-28 — **Landing checkpoint: next-phase items recorded (BACKLOG only, nothing implemented).** UI-B22 (login institutional name "EJ - Faculdade de Tecnologia em Aviação Civil"), DS-EMPTY-TABLE-STATE (no column headers on an empty table/list, only its empty-state message) and UI-B23 (multiple comprovantes; automatic Nome/Data do evento guidance).
- 2026-09-28 — **UI-C13 visual correction (user; stays DONE_PENDING_VISUAL_CONFIRMATION).** The automatic-backup state moved into the "Destinos e sincronização" header chip group (blue "Backup automático ativo" / neutral "Backup automático inativo", effective state only); the title chip, its tooltip and the "Último upload Google Drive/OneDrive" lines were removed. No other status changed.
- 2026-09-28 — **UI-C18 retention residual resolved; UI-C20 → DONE (user decisions, working tree only).** `apply_retention_policy` never deletes a `pre-restore-safety` snapshot (it keeps its bucket as before; ordinary thinning and the `manual-backup` exemption unchanged). Processing a requisição without `observacao` now preserves the stored observação (empty clears, text replaces). The Requisições floating bar is unchanged. No other status changed.
- 2026-09-28 — **Second extended batch (working tree only).** DS-PILL-RADIUS → DONE_PENDING_VISUAL_CONFIRMATION (one `--pill-radius` 4px token at the shared and page-local pill owners). DS-FLOAT-BAR-ORDER → DONE_PENDING_VISUAL_CONFIRMATION for Reportes, Matrizes and Alertas; Requisições left for a decision. UI-B11 → AUDIT_COMPLETE — CATEGORY_A_REDUCED / TOKENIZATION_QUEUE_REMAINS (39 exact duplicates tokenized; 498 → 459). UI-C19 opened and fixed → DONE (the student edit keeps an omitted observação). UI-C20 opened → BACKLOG (processing: keep vs clear). UI-B12 non-visual re-check passed (stays DONE_PENDING_VISUAL_CONFIRMATION). UI-B14 CLOSED_ALREADY_CONSISTENT → DONE (vocabulary only). UI-C13 → DONE_PENDING_VISUAL_CONFIRMATION: the real task was installed and run once (first_run backup — local, Google and OneDrive succeeded; the next wake skipped as unchanged); the header chip is active on canonical. The UI-C18 latent retention note is now live (decision required). Unchanged on purpose: UI-C07, UI-C08, UI-C17 (awaiting visual acceptance), UI-C18 and UI-B13 (already DONE), the UI-B11 C/E queue and the error-page badge preference.
- 2026-09-28 — **Console / view sweep (second extended batch) — no new issue.** Headless Chromium on a disposable DB, 17 page loads (login, Banco de dados, Requisições, Alertas, Turmas, Turma detail, Alunos, Aluno Ver, Cursos, Curso Ver, Matrizes, Matriz Ver, Atividades, versions hub, Versão Ver, Reportes, 404): 0 uncaught errors, 0 `console.error`, 0 CSP violations, 0 unrendered `data-lucide` icons, 0 hidden-but-enabled submits, 0 nested forms, no Ver page with a live POST target.
- 2026-09-28 — **UI-B12 → DONE_PENDING_VISUAL_CONFIRMATION (decision B).** The three request fragments left the authoring contract: help, chips and allowlist, with server-side rejection on new or edited saves. They stay render-only for untouched stored models. No stored preset used them.
- 2026-09-28 — **UI-C13 → IMPLEMENTED — PENDING SCHEDULER INSTALLATION ACCEPTANCE.** The polling task defers to the SGAA's existing interval (`cloud_sync_interval_seconds`), with a cycle lock, a durable run log, an idempotent installer CLI and the effective-status header chip. The real task is not installed. The overnight memo's "cadence decision required" was withdrawn: the SGAA already owns the cadence.
- 2026-09-28 — **Static consistency / console audit (extended batch, Phase G) — no new issue.** Headless-Chromium sweep of 57 page loads (41 admin, 9 read-only consultivo, 8 aluno incl. detail/Ver pages, 4 anonymous) in an isolated DB: 0 uncaught errors, 0 `console.error`, 0 CSP violations, 0 unrendered `data-lucide` icons, 0 hidden-but-enabled submits, 0 live POST forms on Ver/consultivo surfaces; every emitted `view=1` link (Matriz, Versão, aluno request) honoured. External requests are pre-existing and CSP-allowed (Google Fonts on base; Google GSI/Picker on Banco de Dados). Static scan: no readonly/disabled rule carries a local raw colour (the shared `--field-readonly-bg` owner holds). `/admin/editar_turma/<id>?view=1` is not a mode (Turma Ver is `/admin/turma/<id>`) and nothing links to it — not a defect. No code changed.
- 2026-09-28 — **UI-C13 architecture audit (extended batch) — stays BLOCKED — DECISION REQUIRED.** Decision memo `docs/backlog/UI_C13_SCHEDULER_DECISION_MEMO.md`; cadence and preferred local time are user decisions. Nothing installed. *Superseded the same day:* the SGAA already owns the cadence (`cloud_sync_interval_seconds`), so no cadence or time-of-day decision is needed. See the UI-C13 IMPLEMENTED entry above.
- 2026-09-28 — **UI-B11 → AUDIT_COMPLETE — TOKENIZATION QUEUE READY (extended batch).** Owner/role audit written to `docs/backlog/UI_B11_RAW_COLOUR_AUDIT.md` (A 63 · B 29 · C 237 · D 0 · E 169); no CSS or template changed.
- 2026-09-28 — **UI-B12 → AUDIT_COMPLETE_REPAIR_DECISION_REQUIRED (extended batch).** Footguns and options recorded in the row; no code or preset changed (the old one-off repair script was not run).
- 2026-09-28 — **UI-B14 → CLOSED_ALREADY_CONSISTENT (extended batch).** Every ordinary form field already resolves its frame radius from `var(--radius)`; measured 4px everywhere; ownership guard test added. No CSS changed.
- 2026-09-28 — **UI-B13 → DONE (extended batch, audit + tests, no product change).** Meus dados blank password proven a credential no-op; new password proven to follow the shared v11 credential service.
- 2026-09-28 — **UI-C18 opened and fixed (extended batch, working tree only) → DONE.** Restore now distributes the restored database through the shared `_distribute_snapshot`; providers no longer depend on the legacy cloud folder. No UI change.
- 2026-09-28 — **Status reconciliation (extended batch).** UI-C03, UI-C06 and UI-C14 → DONE (explicitly accepted by the user). Unchanged on purpose: UI-C07, UI-C08, UI-C17 (awaiting visual acceptance), UI-C13 (BLOCKED — DECISION REQUIRED), UI-C15 (CLOSED_NON_ACTIONABLE), DS-PILL-RADIUS / DS-FLOAT-BAR-ORDER (deferred); UI-C04, UI-C05, UI-C09, UI-C10–C12 and UI-C16 were already DONE.
- 2026-09-27 — **UI-C15 → CLOSED_NON_ACTIONABLE (overnight batch).** Audit proved a list row without a catalog base cannot exist (JOIN from `atividade_base`, `NOT NULL` base FK column, no legacy table, 0 orphans); no product change.
- 2026-09-27 — **UI-C17 opened and implemented (overnight batch, working tree only) → DONE_PENDING_VISUAL_CONFIRMATION.** Login heading "SGAA"; the mailto access-help footer now links to the existing self-service recovery. Template-only.
- 2026-09-27 — **UI-C09 → DONE (overnight batch, working tree only).** Omitted `observacao` no longer erases the stored observação on the admin edit endpoint; empty still clears; text still replaces. Backend-only, automated acceptance. Residual same-class sites (processing note, student edit) recorded in the UI-C09 row, not changed.
- 2026-09-27 — **UI-C08 → DONE_PENDING_VISUAL_CONFIRMATION (Matriz half implemented).** A linked Matriz keeps Editar; Nome/Descrição editable; its six frozen fields use the shared read-only contract (selects disabled + existing hidden mirrors, inputs readonly); frozen composition tabs lose the redundant bottom Voltar. `templates/admin_matriz_form.html` only (UI-C01 hunks preserved). UI-C09, UI-C13 and the deferred DS items untouched.
- 2026-09-27 — **UI-C08 partial (working tree only). UI-C16 → DONE (visually accepted).** Versão: Editar follows real mutability (canonical freeze policy) on the hub, the Atividades list and the switcher; a locked version's `/editar` renders Ver. Matriz: stopped — an assigned Matriz is field-locked (Nome/Descrição editable), decision recorded in §UI-C08; no Matriz change. UI-C09, UI-C13 and the deferred DS items untouched.
- 2026-09-27 — **UI-C16 opened and implemented (working tree only) → DONE_PENDING_VISUAL_CONFIRMATION.** Turma page: two dead document listeners referencing the shared sort menu's private variables removed; no more `sortFieldBtn` ReferenceError. CSP unchanged. UI-C07 untouched; UI-C08, UI-C09, UI-C13 unchanged.
- 2026-09-27 — **UI-C07 implemented (working tree only) → DONE_PENDING_VISUAL_CONFIRMATION.** Alertas Ver takes the shared read-only paint; local `#f8fafc` and opacity pipettes removed; no writable target in Ver; Editar and the MESSAGE-only preview unchanged. `templates/admin_alertas.html` only. UI-C08, UI-C09, UI-C13, DS-PILL-RADIUS and DS-FLOAT-BAR-ORDER untouched.
- 2026-09-27 — **Turmas floating action bar (bounded adjustment, working tree only).** The Alunos/detail action keeps its behaviour, route, permissions and label but uses the shared Eye icon instead of the graduation cap. Order, left to right: Eye → Editar → Excluir (an interim version briefly had Eye rightmost; corrected). `templates/admin_turmas.html` only; test `tests/test_turmas_floating_bar_eye.py` (3). Rule recorded as DS-FLOAT-BAR-ORDER (deferred); no other bar changed.
- 2026-09-27 — **UI-C06 implemented (working tree only) → DONE_PENDING_VISUAL_CONFIRMATION; UI-C05 → DONE (visually accepted); UI-C15 recorded (BACKLOG).** Ver/Editar Aluno and Turma detail adopt the shared detail header with a destination-named Back; redundant generic Voltar and the Turma page-local top bar / raw empty-state colour removed. Catalog term UI-C06 (−1, 582). UI-C03, UI-C07…UI-C09, UI-C13 untouched.
- 2026-09-27 — **UI-C05 implemented (working tree only) → DONE_PENDING_VISUAL_CONFIRMATION; UI-C04 → DONE (visually accepted); DS-PILL-RADIUS recorded (deferred, not implemented).** View-only users see no write affordance on the Atividades hub or Ver/Editar versão; the version switcher keeps Ver/Editar mode; editor state rules and every backend permission unchanged. UI-C03, UI-C06…UI-C14 untouched.
- 2026-09-27 — **UI-C04 implemented (working tree only) → DONE_PENDING_VISUAL_CONFIRMATION.** Cursos, Alunos (main list and Turma roster), and exact Ver versão now use dedicated GET-only `:view` routes; editor GET/POST and every mutation endpoint retain edit/full authority. Shared read-only presentation is unchanged. UI-C05 untouched; no commit/push.
- 2026-09-27 — **UI-C14 implemented (working tree only) → DONE_PENDING_VISUAL_CONFIRMATION.** 400/403/404/500 share `templates/error_page.html` built from existing DS owners; 403 gains a page and handler; home is role-aware. Catalog term UI-C14 (+1, 583). UI-C10…UI-C12 accepted as DONE by the user; UI-C03, UI-C13 and UI-C04…UI-C09 untouched.
- 2026-09-27 — **UI-C11 and UI-C12 implemented (working tree only) → DONE_PENDING_VISUAL_CONFIRMATION; UI-C13 recorded (BLOCKED — DECISION REQUIRED).** "Gerar backup agora" reports each destination's real outcome after all of them ran; the automatic cycle creates a local snapshot and reaches Google/OneDrive independently of the legacy cloud folder; local retention keeps one series per location. Catalog term UI-C11 (+4/−4, 582). UI-C10 stays in acceptance; its audit statement about the automatic selection is corrected in §UI-C10. UI-C03 and UI-C04…UI-C09 untouched.
- 2026-09-27 — **UI-C10 opened and implemented (working tree only) →
  DONE_PENDING_VISUAL_CONFIRMATION.** "Incluir no backup automático" is editable
  on both provider cards and the stale "Disponível quando o backup automático
  for ativado." tooltip is gone. The manual button stays gated only on provider
  availability. Template-only change plus 21 tests (§UI-C10). UI-C03 and
  UI-C04…UI-C09 untouched.

- 2026-09-26 — **UI-C03 implemented (working tree only) → DONE_PENDING_VISUAL_CONFIRMATION.**
  The Requisições modal in Ver/Processar has no action, no target and a disabled submit; close
  clears every trace of the last target; the edit endpoint refuses a POST whose target is not its
  request. "Abrir" is live in Ver. UI-C09 (absent `observacao` = clear) recorded separately.
  UI-C02 stays DONE; UI-C04…UI-C08 untouched.

- 2026-09-26 — **UI-C01 → DONE (visually accepted). UI-C02 audit recorded (DONE).** Nine
  Ver/Editar pairs classified: S3 1, S2 1, S1 5, S0 2; UI-C03…UI-C08 proposed as BACKLOG.
  No product code changed.

- 2026-09-26 — **UI-C01 opened and implemented (working tree only).** Matrizes de Atividades:
  Ver was the editor (same URL) and could persist. Ver is now the same form with `?view=1`,
  the shared read-only region, no mutation controls or JS, `detail_header` Back and no
  footer; Editar unchanged in behaviour. `DONE_PENDING_VISUAL_CONFIRMATION`. First
  consistency-audit reference case (§UI-C01). No other item touched.

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
