# REF-0C-B2-A — Diagnostic Access Policy and R20 Defense-in-Depth Decision Package

> **Phase type:** read-only architectural policy analysis and documentation-only closeout.
> **No RBAC implementation is authorized or performed in this phase.**
> This document produces an executable decision package for R22, R23, R24, and the
> R20 local `readonly` behavior. It does not select a policy for the system; it
> records repository facts, the exact effective actor outcomes of each candidate
> policy, a recommendation, and the decisions that still require explicit user
> approval. Nothing here changes `app/auth.py`, `main.py`, tests, or behavior.

---

## 1. Scope

Produce an explicit, executable architectural decision package for the four
open items left after REF-0C-B1 acceptance:

1. **R22** — `GET /admin/diagnostico/atividades-versionadas` (`admin_diagnostico_atividades_versionadas`) — JSON activity-version diagnostic.
2. **R23** — `GET /admin/diagnostico/atividades-versionadas/view` (`admin_diagnostico_atividades_versionadas_view`) — HTML view of the same diagnostic.
3. **R24** — `GET /admin/diagnostico/versioned-shadow-reads` (`admin_diagnostico_versioned_shadow_reads`) — JSON shadow-read log diagnostic.
4. **R20** local `readonly` behavior in `admin_matriz_nova_atividade` (the central `matrizes`/`edit` gate is already implemented and accepted).

The package distinguishes: repository facts; effective current RBAC behavior;
possible policies; policies representable with the current model; policies
requiring new vocabulary or profile overrides; the recommended policy; and the
decisions that still require explicit user approval. **No recommendation is
implemented.**

---

## 2. Initial Git State

| Check | Value |
|-------|-------|
| Branch | `refactor/architecture-safety-net` |
| HEAD | `5fb4276d6b48f9b6eaba509198e405aa83002521` (`Refresh PROJECT_STATE after REF-0C-B1 acceptance`) |
| HEAD^ | `932c6d7a5ce29c88c07c8e3b180f1fc0be1eda79` (`Implement REF-0C-B1 strongly supported RBAC mappings`) |
| Divergence `origin/main...HEAD` | `0  11` |
| `932c6d7` is ancestor of HEAD | yes |
| Commits after `932c6d7` | exactly `1` |
| Working tree | clean |
| Staging | empty |
| Untracked files | none |
| Push | none performed |

Verified lineage:

```
c8acd07  Close REF-0C-A after supervisor acceptance
  → 92b25d2  Fix admin access-context transaction hygiene            (REF-0C-B1-P0)
  → 932c6d7  Implement REF-0C-B1 strongly supported RBAC mappings    (REF-0C-B1)
  → 5fb4276  Refresh PROJECT_STATE after REF-0C-B1 acceptance        (HEAD)
```

`git show --check 5fb4276` clean; `5fb4276` touches only `PROJECT_STATE.md`.

### Idempotency check

`docs/refactor/REF_0C_B2_A_DIAGNOSTIC_ACCESS_POLICY_DECISION.md` did not exist before
this phase, and no commit with subject `Document diagnostic RBAC and R20 policy options`
exists in history. This phase is therefore **not** ALREADY SATISFIED; it proceeds.

---

## 3. Files Read Completely

- `PROJECT_STATE.md` (REF-0 refactor section fully; permanent D-series history is background)
- `AGENT_HANDOFF.md` (current REF-0C operational handoff fully; historical D-series is background)
- `docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md` (all 1219 lines)
- `docs/refactor/REF_0C_B1_P0_ACCESS_CONTEXT_TRANSACTION_HYGIENE.md`
- `app/auth.py`
- `tests/_artifacts/rbac_unmapped_routes_baseline.json`
- `tests/test_ref_0c_b1_rbac_high_confidence_mappings.py`

## 4. Files Inspected Partially

`main.py` — the relevant functions and their complete call graphs:

- `_load_admin_access_context` (1522), `_get_current_admin_access_context` (1564), `_admin_can` (1581)
- `_admin_access_denied_response` (5251), `enforce_admin_access_control` (5268), `inject_admin_access_helpers` (5283), `_is_ajax_request` (8408)
- `admin_diagnostico_atividades_versionadas` (9638, R22)
- `admin_diagnostico_versioned_shadow_reads` (9687, R24)
- `admin_diagnostico_atividades_versionadas_view` (9755, R23)
- `admin_matriz_nova_atividade` (12913, R20)
- R22/R23 data sources: `listar_atividades_versionadas_por_matriz` (3141), `listar_atividades_versionadas_por_turma` (3294), `_serialize_versioned_activity_row` (3117), `_diagnostico_versionado_turmas_disponiveis` (9601), `_require_versioning_read_model` (3052), `_get_effective_matriz_for_turma_readonly` (3106), `_get_preferred_matriz_for_curso_readonly` (3084), `_periodo_label_for_turma_row` (2993), `_matriz_option_label` (2944)
- R24 log sources: `_versioned_shadow_read_dedicated_log_path` (3708), `_collect_versioned_shadow_read_log_paths` (4336), `_resolve_versioned_shadow_read_log_sources` (4365), `_read_versioned_shadow_read_events` (4453), `_parse_versioned_shadow_read_event_line` (4272), `_build_versioned_shadow_read_event_line` (3720), `_shadow_read_event_matches_filters` (4421), `_parse_shadow_read_bool_filter` (4410)

The real institutional `database.db` was **not** accessed. Real production log
contents were **not** read. Only static code inspection of log paths and parsing
behavior was performed.

## 5. Commands Executed

Pre-flight (all recorded, all matched expectations):

```
git branch --show-current
git rev-parse HEAD
git rev-parse HEAD^
git rev-list --left-right --count origin/main...HEAD
git status --porcelain=v2 --untracked-files=all
git diff --cached --name-status
git log --oneline --decorate -12
git show --check 5fb4276
git show --stat --name-status --oneline 5fb4276
git merge-base --is-ancestor 932c6d7 HEAD
git rev-list --count 932c6d7..HEAD
```

Idempotency probe: directory listing of `docs/refactor/`; `git log --all` grep for the B2 subject.

---

## 6. Current RBAC Model and Representational Limits

### 6.1 Roles (`ACCESS_LEVEL_META`, `app/auth.py:59-65`)

| Key | Label | `user_type` |
|-----|-------|-------------|
| `admin_total` | Admin | admin |
| `consultivo` | Consultor | admin |
| `administrativo` | Coordenador | admin |
| `usuario` | Usuário | aluno |
| `usuario_teste` | Usuário teste | aluno |

"Anonymous" is the unauthenticated caller — no session `user_type`.

### 6.2 Resources and scopes

Scopes are an ordered ladder (`app/auth.py:20-21`): `none` < `view` < `edit` < `full`.
A requirement `(resource, scope)` is satisfied when the actor's effective scope
for `resource` ranks **≥** the required scope (`permission_scope_satisfies`).

Resources (`ACCESS_RESOURCES_META`, `app/auth.py:24-40`): `dashboard`,
`requisicoes`, `atividades`, `matrizes`, `alunos`, `turmas`, `cursos`,
`arquivos`, `alertas`, `reportes`, `banco_dados`, `acesso`, `configuracoes`,
`mensagens`, `meus_dados`.

### 6.3 `SECURITY_RESTRICTED_RESOURCES` (`app/auth.py:99`)

`banco_dados`, `acesso`, `configuracoes`, `mensagens`.

### 6.4 Default scope behavior per administrative role (`PROFILE_RESOURCE_SCOPES`, `app/auth.py:102-120`)

| Role | Security-restricted resources | All other resources | Explicit exception |
|------|------------------------------|---------------------|--------------------|
| `admin_total` | `full` | `full` | — |
| `administrativo` | `none` | `full` | — |
| `consultivo` | `none` | `view` | `meus_dados` = `edit` |
| `usuario` | (empty map → all `none`) | (all `none`) | — |
| `usuario_teste` | (empty map → all `none`) | (all `none`) | — |

### 6.5 Every explicit `PROFILE_RESOURCE_SCOPES` override

The profile maps are generated by comprehension, so the only *within-profile*
explicit exception is **`consultivo` → `meus_dados` = `edit`** (`app/auth.py:112-114`).
There is no other per-resource special case baked into `PROFILE_RESOURCE_SCOPES`.

Separately, **per-user overrides** exist: `_load_admin_access_context` calls
`_fetch_user_access_overrides(conn, user_id)` and `merge_resource_scopes` layers
them over the role defaults (`app/auth.py:174-180`, `main.py:1552-1553`). These
are stored per individual user, not per role. This distinction matters for the
representational analysis below (see actor set D and E).

### 6.6 Effective scope of each admin role, by resource class

| Resource class | admin_total | administrativo | consultivo |
|----------------|-------------|----------------|------------|
| Non-restricted (e.g., `atividades`, `matrizes`) | `full` | `full` | `view` |
| Security-restricted (e.g., `banco_dados`) | `full` | `none` | `none` |

Consequence — the **exhaustive** set of role-level actor sets a single
`(resource, scope)` requirement can produce over `{admin_total, administrativo, consultivo}`:

| Requirement | admin_total | administrativo | consultivo | Resulting role set |
|-------------|:-----------:|:--------------:|:----------:|--------------------|
| non-restricted / `view` | ✓ | ✓ | ✓ | **A** = all three |
| non-restricted / `edit` | ✓ | ✓ | ✗ | **B** = admin_total + administrativo |
| non-restricted / `full` | ✓ | ✓ | ✗ | **B** = admin_total + administrativo |
| restricted / `view`,`edit`,`full` | ✓ | ✗ | ✗ | **C** = admin_total only |

(`anonymous` and `aluno` are always denied by `@admin_required` before any of this.)

### 6.7 Representability of each requested actor set (Part A.6)

| Set | Actors | Directly representable? | Mechanism | Verdict |
|-----|--------|--------------------------|-----------|---------|
| **A** | admin_total + administrativo + consultivo | **Yes, directly** | any non-restricted resource at `view` (e.g., `atividades`/`view`, `matrizes`/`view`) | Advisable when consultivo should read |
| **B** | admin_total + administrativo | **Yes, directly** | any non-restricted resource at `edit`/`full` (e.g., `atividades`/`edit`) | Representable, but for a *read* endpoint it means "require write scope to read" — a **semantic mismatch**. Clean form needs a new `diagnosticos` resource with custom defaults (admin_total=`full`, administrativo=`view`, consultivo=`none`). |
| **C** | admin_total only | **Yes, directly** | any `SECURITY_RESTRICTED` resource at any scope (e.g., `banco_dados`/`view`) | Advisable for security-sensitive internals |
| **D** | admin_total + consultivo (administrativo denied) | **No** at role level | Not expressible with default scopes (administrativo ≥ consultivo on every non-restricted resource; both `none` on restricted). Achievable only per **individual user** via a stored override, or via **new vocabulary / endpoint-specific logic**. | **Not advisable** — inverts the privilege ordering |
| **E** | administrative roles with *different* diagnostic scopes | **Partially** | Default ranking forces administrativo ≥ consultivo on non-restricted resources. Differentiating at the **role** level requires a **new resource with custom `PROFILE_RESOURCE_SCOPES` defaults** (code/vocabulary), or **per-user overrides** (individual level only) | Possible only with new vocabulary or per-user overrides |

**Key limit:** the current model cleanly represents only three role-level shapes
for a GET/read diagnostic — *all three admins* (`view`), *admin_total only*
(restricted resource), and *admin_total + administrativo* (at the price of an
`edit` scope on a read). Any policy that grants consultivo while denying
administrativo (set D), or that differentiates administrativo from consultivo at
role level without using `edit`-on-read (set B cleanly, or set E), requires new
vocabulary, a profile override, or endpoint-specific logic.

### 6.8 Enforcement mechanism (repository fact)

`enforce_admin_access_control` (`main.py:5268-5280`) is an `@app.before_request`:

1. If `session["user_type"] != "admin"` → returns `None` (the `@admin_required`
   decorator on each route separately redirects anonymous/aluno to `login`).
2. `requirement = get_admin_permission_requirement(endpoint, method)`.
3. **If `requirement is None` → returns `None` (the route is allowed for any
   authenticated admin).** This is fail-*open* for unmapped routes.
4. Otherwise it evaluates `_admin_can(resource, scope)`; on failure it returns
   `_admin_access_denied_response`.

`_admin_access_denied_response` (`main.py:5251-5264`): if `_is_ajax_request()`
(true only when header `X-Requested-With: XMLHttpRequest`) → **JSON 403**
`{"ok": false, "error": "forbidden", "resource", "required_scope", "message"}`;
otherwise → flash + **302 redirect to `admin_dashboard`**.

Because R22–R24 return `None` from `get_admin_permission_requirement`, their
**current effective policy is: any authenticated admin — `admin_total`,
`administrativo`, and `consultivo` — is allowed; anonymous and aluno are blocked
by `@admin_required`.**

---

## 7. R22 Analysis — `GET /admin/diagnostico/atividades-versionadas` (JSON)

### 7.1 What it returns / tables read (repository fact)

Handler `admin_diagnostico_atividades_versionadas` (`main.py:9638-9682`) dispatches
on `turma_id` / `turma_codigo` / `matriz_id` query args and calls, respectively,
`listar_atividades_versionadas_por_turma` → `listar_atividades_versionadas_por_matriz`,
or `_diagnostico_versionado_turmas_disponiveis` for the index. It returns
`jsonify({"ok": True, ...payload})`; `LookupError`→404, `RuntimeError`→503,
`ValueError`→400.

**Tables actually read** (verified across the full call graph):
`matrizes_atividades`, `cursos` (LEFT JOIN), `turmas`, `norma_atividade`,
`matriz_norma`, `matriz_atividade_versao_item`, `atividade_versao`,
`atividade_base`, `atividade_legacy_map`, and `atividades` (only via a scalar
subquery to resolve the legacy display name/type). **No mutations. No filesystem.**

**Fields exposed** (via `_serialize_versioned_activity_row`, `main.py:3117-3138`,
plus the matriz/turma/norma envelope): matrix id/name/version/status/label and
its course id/name/code; linked classes (`turmas`) by id/code/name/period label;
norms by id/code/eixo/revisão/name; per activity — `atividade_versao_id`,
`atividade_base` id+name, `nome_exibivel`, `grupo`, `ch_por_evento`,
`limite_semestre`, `limite_total`, `observacao_aluno`, `observacao_admin`,
`status`, `eixo`, `norma_codigo`, legacy correspondence flags/ids and legacy
name/type.

### 7.2 Sensitivity classification

- Personal/academic student data (names, enrollment, requests): **none.**
  `alunos` and `requisicoes` are **not** queried anywhere in the call graph.
- Operational academic configuration (matrix, course, class metadata, norms,
  versioned activity rules): **yes** — this is curricular catalog data.
- Internal/admin note: `observacao_admin` — an admin-facing note on a version.
- Internal resolver state, configuration, filesystem paths, security values: **none.**
- Identifiers exposed: activity/base/version/legacy/matrix/norm/class ids
  (structural), not student identifiers.

> **Repository-vs-documentation note.** The accepted REF-0C-A diagnosis (R22 row,
> line 839) lists `alunos` and `requisicoes` among "Tables read." Static inspection
> of the actual call graph shows those two tables are **not** read by R22/R23. R22/R23
> therefore expose **no student PII** — i.e., they are *less* sensitive than that
> descriptive field implied. This corrects an over-inclusive analysis field only; it
> does **not** conflict with any accepted state, phase acceptance, confidence count,
> or decision (R22–R24 remain unmapped). It is surfaced here rather than silently
> reconciled, and it strengthens the case for the least-restrictive option.

### 7.3 UI discoverability and operational need

The JSON endpoint (R22) has no sidebar entry; it is reached by direct API call
and as the data source behind the R23 HTML view. Operational need: verifying that
the versioned activity model resolves correctly for a class/matrix in parallel to
the legacy model — a read-only sanity/diagnostic view of curricular configuration
that `consultivo` (Consultor) already sees the constituent parts of via
`atividades`/`view` and `matrizes`/`view` (R1–R4, R17, all accepted for all admins).

### 7.4 R22 policy options — exact effective role sets

| Option | Resource / scope | admin_total | administrativo | consultivo | vs. current |
|--------|------------------|:-----------:|:--------------:|:----------:|-------------|
| **1** | `atividades` / `view` | ✓ | ✓ | ✓ (set **A**) | **unchanged** |
| **2** | `banco_dados` / `view` | ✓ | ✗ | ✗ (set **C**) | revokes administrativo + consultivo |
| **3** | new `diagnosticos` / `view` | depends on chosen defaults (see §10) | | | new vocabulary |
| **4** | endpoint-specific / role-name special case | arbitrary (e.g., set **B**) | | | brittle |

`aluno` and `anonymous` are denied under every option (via `@admin_required`).

**Option 3 specifics** (if pursued): a new `diagnosticos` resource would need an
entry in `ACCESS_RESOURCES_META`, a group in `ACCESS_RESOURCE_GROUPS`, and a
per-level default in each `PROFILE_RESOURCE_SCOPES` profile. Whether it is
security-restricted decides the administrativo/consultivo defaults. To obtain set
**B** (admin_total + administrativo, consultivo denied) cleanly at `view` scope,
defaults would be admin_total=`full`, administrativo=`view`, consultivo=`none`,
and it must **not** be in `SECURITY_RESTRICTED_RESOURCES`. Migration/compat: existing
per-user override rows have no value for the new resource, so `merge_resource_scopes`
falls back to the level default (safe). UI: the access-management screen would show a
new "Diagnósticos" row for every admin. Tests: the RBAC coverage/actor-matrix suite
would need the new resource added.

**Option 4** (endpoint-specific / role-name): hardcoding e.g.
`if access_level in {"admin_total","administrativo"}` inside
`get_admin_permission_requirement` or the handler bypasses the resource/scope
abstraction. It is inferior to resource-based RBAC: it is invisible to the
uniform `(resource, scope)` actor-matrix tests, it fragments the single
authorization vocabulary, and it creates a second place where policy can drift
from the profile model. Preferable only if a one-off actor set were needed that
the model genuinely cannot express and that must not become reusable vocabulary —
not the case here.

### 7.5 R22 recommended policy — **not implemented**

| Field | Value |
|-------|-------|
| Resource | `atividades` |
| Scope | `view` |
| Allowed roles | `admin_total`, `administrativo`, `consultivo` |
| Denied roles | `aluno`, `anonymous` |
| Effective actor set | **A** (all three admin roles) |
| Confidence | **MEDIUM-HIGH** |
| Security rationale | Read-only curricular catalog data with no student PII, no resolver internals, no paths, no config. Same data class consultivo already reads via `atividades`/`view` and `matrizes`/`view`. |
| Usability rationale | Zero behavioral change vs. current effective access; consultivo keeps a coherent read surface across catalog + diagnostic. |
| Implementation complexity | One mapping line in `get_admin_permission_requirement`; no vocabulary. |
| Compatibility impact | None — preserves current effective access; no revocation. |
| Required tests | See §17. |

---

## 8. R23 Analysis — `GET /admin/diagnostico/atividades-versionadas/view` (HTML)

### 8.1 What it returns / tables read (repository fact)

Handler `admin_diagnostico_atividades_versionadas_view` (`main.py:9755-9806`) calls
the **same** `listar_atividades_versionadas_por_turma` / `_por_matriz` /
`_diagnostico_versionado_turmas_disponiveis` helpers as R22, then renders
`admin_diagnostico_atividades_versionadas_view.html` with `make_response(..., status_code)`.
Same tables, same payload, same error status codes (404/503/400) — just HTML
instead of JSON.

### 8.2 HTML vs JSON exposure

The HTML view exposes the **same** underlying data as the JSON route (identical
call graph and payload). It does not expose more or less; it renders the same
model into a template. There is **no** additional table, field, path, or internal
value in R23 beyond R22.

### 8.3 Must R22 and R23 share the same policy?

**Yes — strongly.** They serve identical data from identical queries; the only
difference is representation (JSON vs HTML). Splitting their policy would let a
role read the data in one format but not the other, which is incoherent and a
maintenance trap. R22 and R23 must be mapped to the **same** `(resource, scope)`.

### 8.4 R23 policy options

Identical option table to §7.4 (same effective role sets), because the data and
call graph are identical.

### 8.5 R23 recommended policy — **not implemented**

Same as R22: **`atividades` / `view`**, allowed `admin_total` + `administrativo`
+ `consultivo`, denied `aluno` + `anonymous`, effective set **A**, confidence
**MEDIUM-HIGH**. Denial contract differs only by transport: a denied XHR gets JSON
403; a denied browser navigation gets a 302 redirect to `admin_dashboard`
(R23 is normally a browser navigation → redirect).

---

## 9. R24 Analysis — `GET /admin/diagnostico/versioned-shadow-reads` (JSON)

### 9.1 What it reads / exposes (repository fact)

Handler `admin_diagnostico_versioned_shadow_reads` (`main.py:9687-9750`) reads
**log files**, not the database. Log paths come from
`_resolve_versioned_shadow_read_log_sources` → `_versioned_shadow_read_dedicated_log_path`
(app-relative `logs/versioned_shadow_reads.log`) and `_collect_versioned_shadow_read_log_paths`
(the dedicated path, each logging handler's `baseFilename`, and app-relative
`logs/app.log`, plus their `.1` rotations). Events are parsed by
`_parse_versioned_shadow_read_event_line` and filtered in memory.

**Files read:** the dedicated shadow-read log and/or the application log(s) and
their rotations — all derived from app-relative paths and logger handler
filenames.

**Data exposed in the JSON response:**

- `dedicated_log_path`, `log_paths` — **absolute server filesystem paths.**
- `shadow_read_env_raw` — the **raw value of the environment variable**
  `SGAA_VERSIONED_RESOLVER_SHADOW_READ` (`os.getenv`, line 9717).
- `shadow_read_enabled`, `source_mode`, `dedicated_log_exists`,
  `dedicated_log_in_paths` — feature-flag / source state.
- `logger_level`, `handler_count` — internal logging configuration.
- `events[]` — per shadow-read event: `origin`, `req_id`, `aluno_id`,
  `atividade_id_legacy`, `status`, `atividade_versao_id`, `codigo_normativo`,
  `eixo`, `warnings`, `reason`, `timestamp`, and **`exception_type`,
  `exception_message`, `exception_traceback`** (base64-decoded from the log line).

### 9.2 Sensitivity classification

R24 is materially more sensitive than R22/R23. It discloses:

- **Filesystem paths** of the server (information disclosure that aids an attacker).
- **Environment/feature-flag configuration** (`shadow_read_env_raw`).
- **Internal resolver behavior and reasons**, including **exception messages and
  stack traces** — internal error internals.
- **Student/request identifiers** (`aluno_id`, `req_id`, `atividade_id_legacy`)
  correlated with resolver decisions.

This is a **system/security-adjacent operational diagnostic**, not curricular data.

### 9.3 User-supplied filtering / traversal / over-exposure

- **User-supplied filtering exists**: `origin`, `status`, `codigo_normativo`,
  `eixo`, `aluno_id` (int), `atividade_id_legacy` (int), `has_warnings` (bool),
  `limit` (int, coerced to 1..500). These filters select parsed events in memory.
- **Filesystem traversal is not possible from user input**: no query parameter is
  ever used to build a file path. Paths come solely from app-relative constants
  and logger handler `baseFilename`. Confirmed in
  `_resolve_versioned_shadow_read_log_sources` / `_collect_versioned_shadow_read_log_paths` /
  `_read_versioned_shadow_read_events`.
- **Excessive log exposure is bounded** by `limit` (≤ 500) after dedup, but the
  endpoint still returns raw paths, env value, and tracebacks regardless of filters.
- File read is best-effort and never raises (broad `except` per source file).

### 9.4 Availability by role — assessment

- **`administrativo` (Coordenador):** no operational need for resolver internals,
  filesystem paths, environment values, or stack traces. Denying is defensible.
- **`consultivo` (Consultor, read-only):** clearly should **not** see internal
  paths/config/tracebacks. Denying is the safe default.
- **No UI link:** R24 has no UI entry (direct API only). Restricting it therefore
  breaks **no** navigation and changes no visible screen — the security policy can
  be tightened at essentially zero usability cost.

### 9.5 R24 policy options — exact effective role sets

| Option | Resource / scope | admin_total | administrativo | consultivo | vs. current |
|--------|------------------|:-----------:|:--------------:|:----------:|-------------|
| **1** | `atividades` / `view` | ✓ | ✓ | ✓ (set **A**) | unchanged — but exposes paths/env/tracebacks to all admins |
| **2** | `banco_dados` / `view` | ✓ | ✗ | ✗ (set **C**) | **revokes administrativo + consultivo** |
| **3** | new `diagnosticos` / scope | depends on defaults (§10) | | | new vocabulary; can yield set **B** or **C** cleanly |
| **4** | endpoint-specific / role-name | arbitrary | | | brittle |

### 9.6 R24 recommended policy — **not implemented**

| Field | Value |
|-------|-------|
| Resource | `banco_dados` |
| Scope | `view` |
| Allowed roles | `admin_total` |
| Denied roles | `administrativo`, `consultivo`, `aluno`, `anonymous` |
| Effective actor set | **C** (admin_total only) |
| Confidence | **MEDIUM-HIGH** |
| Security rationale | Restricts disclosure of filesystem paths, environment values, exception tracebacks, resolver internals, and student/request identifiers to the top administrative role, matching the existing `banco_dados`/`view` pattern used for system diagnostics (`admin_banco_dados`). |
| Usability rationale | No UI link exists → no navigation breaks. The only effect is deliberately removing an endpoint from administrativo/consultivo, who have no operational need for it. |
| Implementation complexity | One mapping line; no new vocabulary. |
| Compatibility impact | **Behavioral tightening** — administrativo and consultivo lose access they currently have (fail-open). This must be consciously accepted (see §16, §19). |
| Required tests | See §17. |

If the institution decides `administrativo` (Coordenador) **does** need shadow-read
diagnostics while `consultivo` does not, that is actor set **B** — **not**
representable at `view` scope with existing resources — and would require a new
`diagnosticos` resource with custom per-level defaults (Option 3) or endpoint-specific
logic (Option 4). That is an explicit unresolved decision (§19, D3′).

---

## 10. Optional new `diagnosticos` vocabulary (only if set B is required)

If, and only if, the user requires the intermediate actor set **B**
(admin_total + administrativo, consultivo denied) for any diagnostic at a
semantically clean *read* scope, the minimal new vocabulary is:

- `ACCESS_RESOURCES_META["diagnosticos"] = {"label": "Diagnósticos", "group": "Segurança"|"Sistema"}`.
- Add `diagnosticos` to the relevant `ACCESS_RESOURCE_GROUPS` tuple.
- `PROFILE_RESOURCE_SCOPES` per-level defaults: admin_total=`full`,
  administrativo=`view`, consultivo=`none`; `usuario`/`usuario_teste` unaffected.
- Do **not** add it to `SECURITY_RESTRICTED_RESOURCES` (that would force
  administrativo to `none` and collapse it back to set C).
- Map R22/R23 (and/or R24) to `diagnosticos`/`view`.

Impact: this is schema-free (code-only vocabulary), but it is genuinely *new*
vocabulary, touches the access-management UI (new row for all admins), and
requires the RBAC test matrix to learn the new resource. It is **not**
recommended unless set B is explicitly required, because the recommended policy
(§7, §9) needs no new vocabulary.

---

## 11. R20 Local `readonly` Analysis — `admin_matriz_nova_atividade`

### 11.1 How `readonly` is computed and used (repository fact)

In `admin_matriz_nova_atividade` (`main.py:12913-...`):

- Line 12924-12925:
  `auth_context = _get_current_admin_access_context()` then
  `readonly = not _admin_can("matrizes", "edit", auth_context)`.
- `readonly` is passed **only** to `_render_matriz_form(..., readonly=readonly, ...)`
  inside the `_render_modal_error` re-render path and the final render — i.e., it
  drives **template presentation** only.
- The actual write path (INSERTs into `atividades`, `atividade_base`,
  `atividade_legacy_map`, `atividade_versao`, and optionally
  `matrizes_atividades_itens` / `matriz_atividade_versao_item`, from line ~12998)
  **does not consult `readonly`.** There is no `if readonly: deny/redirect` guard.

### 11.2 Can POST execution occur after the central denial?

**No.** REF-0C-B1 mapped R20 to `matrizes`/`edit` in
`get_admin_permission_requirement` (`app/auth.py:390-396`). The
`enforce_admin_access_control` before-request gate therefore denies any role
lacking `matrizes`/`edit` (i.e., `consultivo`) **before** the handler body runs,
returning `_admin_access_denied_response` (302 to dashboard, or JSON 403 for XHR).
Consequently the handler body is reached **only** by roles that already hold
`matrizes`/`edit` (`admin_total`, `administrativo`), for whom
`_admin_can("matrizes","edit")` is `True` and thus `readonly` is **always `False`**.

The gate reloads context with `force_reload=True` and stores it in
`g.admin_access_context`; the handler's `_get_current_admin_access_context()`
returns that same cached context, so the two evaluations are consistent — there is
no window where the handler runs with `readonly == True`.

This is exactly the REF-0C-A finding (§12, §18.2, D1) — the local `readonly` is a
**redundant/vestigial local authorization value**: it does not, and never did,
gate the write; the write is now protected centrally.

### 11.3 Does retaining the variable provide useful presentation behavior?

Minimal. Because the handler is only ever reached with `readonly == False`, the
value passed to the template is a constant `False` on this route. It provides no
differentiated rendering in practice. (`_render_matriz_form` presumably also
serves genuine read-only contexts elsewhere via `admin_editar_matriz`, where the
parameter is meaningful; on *this* POST route it is inert.)

### 11.4 Would a second handler-level denial improve defense in depth?

Marginally, and at a cost. A `if readonly: return _admin_access_denied_response(...)`
guard would be a belt-and-suspenders check if the central mapping were ever
removed or regressed. But:

- It **duplicates authorization logic** already owned by the central gate → two
  sources of truth → **drift risk** (the REF-0C-A "REDUNDANT LOCAL AUTHORIZATION"
  classification).
- The accepted REF-0C-A decision **D1** recommends option (a): rely on the central
  gate; treat `readonly` as a secondary UI concern.
- REF-0C-B1 already added denial + immutability regression tests around
  `matrizes`/`edit` (actor matrix, denied-POST-is-immutable), so the central
  enforcement of R20 is already covered by tests.

### 11.5 Is the variable name misleading?

Somewhat. A variable named `readonly` that never actually prevents writes on a
write route is misleading to a future reader — it reads like an enforcement flag
but is a presentation hint. This is a clarity/maintainability issue, not a
security hole.

### 11.6 R20 options

| Option | Security effect | Maintenance risk | UI effect | Test requirements | Code impact | Compatibility |
|--------|-----------------|------------------|-----------|-------------------|-------------|---------------|
| **A. Keep as UI/presentation hint only** | Neutral — central gate enforces | Leaves an inert, mildly misleading variable | None | None new (B1 covers enforcement) | None | None |
| **B. Add handler-level denial** | Marginal defense-in-depth | **Higher — duplicate authz logic, drift risk** | None | New handler-level denial test | Small addition in `main.py` | None |
| **C. Remove local calc after central enforcement proven** | Neutral | **Lowest — removes dead code + drift risk** | Must confirm `_render_matriz_form` re-render path tolerates omission/`False` | Regression test that write path stays centrally gated (already exists) | Small deletion in `main.py` | None (behavior identical) |
| **D. Rename/refactor to presentation-only** | Neutral | Improves clarity | None | None new | Rename in `main.py` | None |

### 11.7 R20 recommendation — **not implemented, not modified**

- **This phase: Option A** — keep `readonly` unchanged (R20 modification is
  explicitly prohibited here, and there is no security gap: the central gate
  enforces `matrizes`/`edit` before the handler body).
- **Future authorized cleanup (REF-0C-B2 implementation or a dedicated cleanup):
  prefer Option C (remove)**, or at minimum **Option D (rename to a
  presentation-only name)**, to eliminate the misleading inert variable. Removal
  is safe because the central gate + existing B1 regression tests already prove
  the write is protected.
- **Reject Option B** as the primary direction: it re-introduces duplicate
  authorization logic and drift risk for negligible gain over the proven central
  gate — contrary to accepted decision D1.

The choice between C and D at implementation time is an explicit user/supervisor
decision (see §19, D1′). No change is made now.

---

## 12. Policy Options Summary

| Route | Opt 1 `atividades`/`view` | Opt 2 `banco_dados`/`view` | Opt 3 new `diagnosticos` | Opt 4 endpoint-specific |
|-------|---------------------------|----------------------------|--------------------------|--------------------------|
| R22 | all admins (set A) — **recommended** | admin_total only (set C) | configurable | brittle |
| R23 | all admins (set A) — **recommended** (must match R22) | admin_total only (set C) | configurable | brittle |
| R24 | all admins (set A) | admin_total only (set C) — **recommended** | configurable (set B/C) | brittle |

---

## 13. Exact Effective Actor Sets (recommended policy)

| Route | Policy (recommended) | admin_total | administrativo | consultivo | aluno | anonymous |
|-------|----------------------|:-----------:|:--------------:|:----------:|:-----:|:---------:|
| **Current R22/R23/R24 (unmapped)** | — | ✓ | ✓ | ✓ | ✗ (login) | ✗ (login) |
| **R22** | `atividades`/`view` | ✓ | ✓ | ✓ | ✗ | ✗ |
| **R23** | `atividades`/`view` | ✓ | ✓ | ✓ | ✗ | ✗ |
| **R24** | `banco_dados`/`view` | ✓ | ✗ | ✗ | ✗ | ✗ |
| **R20 (already mapped, accepted)** | `matrizes`/`edit` | ✓ | ✓ | ✗ | ✗ | ✗ |

Denial transport: XHR (`X-Requested-With: XMLHttpRequest`) → JSON 403; otherwise →
302 redirect to `admin_dashboard`. Anonymous/aluno → redirect to `login` via `@admin_required`.

Every recommended actor set is representable by the described mechanism:
R22/R23 = non-restricted resource at `view` (set A); R24 = security-restricted
resource at `view` (set C). Neither needs new vocabulary or overrides.

---

## 14. Recommended Policy (consolidated) — **not implemented**

1. **R22** → `atividades` / `view` → {admin_total, administrativo, consultivo}. Confidence **MEDIUM-HIGH**.
2. **R23** → `atividades` / `view` → {admin_total, administrativo, consultivo} (must equal R22). Confidence **MEDIUM-HIGH**.
3. **R24** → `banco_dados` / `view` → {admin_total}. Confidence **MEDIUM-HIGH**.
4. **R20** → keep local `readonly` unchanged this phase; future disposition Option C (remove) preferred, else D (rename). Reject Option B.

---

## 15. Confidence

| Item | Confidence | Basis |
|------|-----------|-------|
| R22 = `atividades`/`view` | MEDIUM-HIGH | Read-only curricular data, no PII/paths/config; preserves current access; matches neighboring catalog routes. Residual: `observacao_admin` is an admin note (low concern). |
| R23 = `atividades`/`view` | MEDIUM-HIGH | Identical data/call-graph to R22; must share policy. |
| R24 = `banco_dados`/`view` | MEDIUM-HIGH | Exposes paths/env/tracebacks/identifiers → security-sensitive; matches `banco_dados` diagnostic pattern; no UI cost. Residual: whether administrativo needs it (set B) is a user decision. |
| R20 = keep now / remove later | HIGH | Central gate proven + B1 regression tests; local value is inert on this route. |

---

## 16. Security Impact

- **R22/R23 (recommended `atividades`/`view`):** neutral vs current — no new
  exposure, no PII, no internals. Choosing `banco_dados`/`view` instead would
  *increase* restriction (admin_total only) at the cost of removing a legitimate
  read surface from consultivo/administrativo.
- **R24 (recommended `banco_dados`/`view`):** **improves** security — removes
  filesystem-path, environment-value, exception-traceback, and identifier
  disclosure from administrativo and consultivo, confining it to admin_total.
- **R20:** no change now; no security gap exists because the central
  `matrizes`/`edit` gate blocks denied roles before the write. Future removal of
  the inert `readonly` reduces drift risk.
- **Cross-cutting:** none of R22–R24 mutate the database or filesystem; R24 reads
  logs read-only with no user-controlled paths (no traversal).

## 17. Usability Impact

- **R22/R23:** none — same roles as today keep access; consultivo retains a
  coherent catalog+diagnostic read surface.
- **R24:** none visible — no UI link exists; only administrativo/consultivo lose a
  direct-API endpoint they have no operational need for.
- **R20:** none — presentation unchanged; the inert value renders as it does today.

## 18. Implementation Impact (for the later, separately-authorized phase — not now)

- **R22/R23/R24:** three added mappings in `get_admin_permission_requirement`
  (`app/auth.py`). No schema, DB, dependency, template, or JS change. If Option 3
  is chosen for any route, add `diagnosticos` to `ACCESS_RESOURCES_META`,
  `ACCESS_RESOURCE_GROUPS`, and every `PROFILE_RESOURCE_SCOPES` profile (+ access
  UI + tests).
- **R20:** if Option C/D is chosen, a small localized edit in
  `admin_matriz_nova_atividade` in `main.py`.
- **Debt baseline:** implementing R22–R24 mappings would empty
  `tests/_artifacts/rbac_unmapped_routes_baseline.json` (target state "lista
  vazia"), regenerated only with the documented `SGAA_UPDATE_RBAC_DEBT_BASELINE=1`.
- **Test suite:** new denial/actor-matrix tests per §17 below.

## 19. Required New Vocabulary or Overrides

- **Recommended policy needs none.** R22/R23 = `atividades`/`view` and R24 =
  `banco_dados`/`view` are fully representable with existing resources and scopes,
  no `PROFILE_RESOURCE_SCOPES` change, no per-user override.
- **New vocabulary is required only** if the user picks an actor set the defaults
  cannot express at a clean read scope — specifically set **B** (admin_total +
  administrativo, consultivo denied) for a diagnostic — which needs the new
  `diagnosticos` resource of §10 (or endpoint-specific logic).

---

## 20. Future Test Contract (to be authored in a later phase — no tests added now)

### 20.1 R22/R23/R24 (recommended policy)

For each of R22, R23, R24, and for actors `admin_total`, `administrativo`,
`consultivo`, `aluno`, `anonymous`:

- **admin_total** → allowed (200) on all three.
- **administrativo** → allowed on R22/R23; **denied** on R24.
- **consultivo** → allowed on R22/R23; **denied** on R24.
- **aluno** → denied on all three (redirect to `login` via `@admin_required`).
- **anonymous** → denied on all three (redirect to `login`).
- **AJAX denial contract:** a denied actor with `X-Requested-With: XMLHttpRequest`
  on R22/R24 → JSON `403` `{"ok": false, "error": "forbidden", "resource",
  "required_scope"}`.
- **Browser denial contract:** a denied actor without the XHR header on R23 (and
  on R22/R24 via browser) → `302` redirect to `/admin/dashboard`.
- **JSON response contract:** allowed R22/R24 return well-formed JSON with the
  documented keys; R24 payload contract asserted (see 20.2).
- **Redirect contract:** denial `Location` ends with `/admin/dashboard`; anonymous
  `Location` contains `/login`.
- **No database mutation:** GET diagnostics mutate zero rows (row counts of read
  tables unchanged before/after).
- **No filesystem mutation:** R24 does not create/modify/delete any log or file
  (mtime/size of log paths unchanged; endpoint is read-only best-effort).
- **No log modification:** R24 only reads; assert no write to any candidate log path.
- **No policy fallback:** once mapped, an unauthorized role is never silently
  allowed (no `requirement is None` pass-through for these endpoints).
- **R22/R23 policy consistency:** a parametrized test asserts R22 and R23 resolve
  to the **same** `(resource, scope)` requirement and the **same** allow/deny
  outcome for every actor.
- **R24 sensitive-output restrictions:** assert that only `admin_total` can obtain
  the response containing `dedicated_log_path`/`log_paths`, `shadow_read_env_raw`,
  `logger_level`/`handler_count`, and event `exception_*`/`aluno_id`/`req_id`
  fields; denied roles never receive them.

### 20.2 R24 payload contract (allowed path)

Assert the JSON contains the documented keys (`diagnostico`, `source`,
`source_mode`, `count`, `raw_count`, `deduplicated_count`, `limit`, `filters`,
`log_not_found`, `shadow_read_enabled`, `shadow_read_env_raw`, `dedicated_log_path`,
`dedicated_log_exists`, `dedicated_log_in_paths`, `log_paths`, `logger_level`,
`handler_count`, `events`), that `limit` is clamped to `1..500`, and that filters
select events without ever using a user value as a filesystem path.

### 20.3 R20 (recommended local-readonly disposition)

If **Option C (remove)** is chosen later:
- Regression: `admin_total`/`administrativo` POST still succeeds (write path intact).
- Regression: `consultivo` POST still denied by the central gate with no mutation
  across all six affected tables (already covered in spirit by B1's
  `test_denied_post_matrizes_edit_is_immutable`; extend to R20's exact route/tables).
- Presentation: `_render_matriz_form` error re-render path still renders without
  the removed variable.

If **Option D (rename)** is chosen later:
- Assert the renamed presentation-only flag no longer implies enforcement; central
  gate remains the sole authorization point.

If **Option B (handler denial)** were chosen (not recommended):
- A handler-level denial test for a role reaching the body with `readonly == True`
  — but note this state is unreachable while the central mapping stands, so the
  test would require artificially bypassing the gate.

---

## 21. Unresolved User / Supervisor Decisions

| # | Decision | Options | Recommended | If not recommended |
|---|----------|---------|-------------|--------------------|
| **D2′** (R22/R23) | Resource for the activity-version diagnostic | (a) `atividades`/`view` → all admins; (b) `banco_dados`/`view` → admin_total only; (c) new `diagnosticos` | **(a)** — read-only curricular data, no PII; preserves current access | (b) if consultivo/administrativo must be excluded from curricular diagnostics; (c) only if set B is required |
| **D3′** (R24) | Resource for the shadow-read diagnostic | (a) `banco_dados`/`view` → admin_total only; (b) new `diagnosticos` (set B: +administrativo); (c) `atividades`/`view` → all admins | **(a)** — confines path/env/traceback disclosure to admin_total | (b) if Coordenador (administrativo) needs it while Consultor does not → **new vocabulary**; (c) rejected (broad internals exposure) |
| **D-consistency** | Must R22 and R23 share policy? | yes / no | **yes** — identical data/call-graph | n/a |
| **D-tightening** | Accept revoking administrativo+consultivo from R24? | accept / reject | **accept** — no UI cost, security gain | reject → choose D3′(b) or D3′(c) |
| **D1′** (R20) | Local-readonly disposition in the later phase | A keep / B add denial / C remove / D rename | **C (remove)**, else **D (rename)** | B rejected (drift risk) |
| **D-B2-auth** | Whether/when to authorize REF-0C-B2 implementation | authorize / defer | supervisor + user | — |

No R22–R24 policy is active. No test prescribes consultivo (or any) access for
R22–R24. These remain unresolved pending the ChatGPT supervisor review and the
user's normative decision.

---

## 22. Confirmation of Non-Implementation

No policy was implemented in this phase. `app/auth.py`, `main.py`, tests, the RBAC
debt baseline, templates, and JavaScript were **not** changed. No R22–R24 mapping
was added; `get_admin_permission_requirement` still returns `None` for
`admin_diagnostico_atividades_versionadas`, `admin_diagnostico_atividades_versionadas_view`,
and `admin_diagnostico_versioned_shadow_reads`. R20 behavior is unchanged; the
local `readonly` value is untouched. No global fail-closed gate was introduced. No
schema, database, dependency, UI, or modularization change occurred. Only the three
authorized documentation files (this file, `PROJECT_STATE.md`, `AGENT_HANDOFF.md`)
are modified in the accompanying commit. All statements above are recommendations
only; no authorization logic is active for R22–R24, and no later implementation
phase is authorized by this document. The next action is ChatGPT supervisor review
and the user's normative decision.
