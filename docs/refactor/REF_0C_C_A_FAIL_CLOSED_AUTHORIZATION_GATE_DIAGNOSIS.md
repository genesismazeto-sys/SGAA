# REF-0C-C-A — Fail-Closed Authorization Gate Diagnosis

## 1. Scope and result

This is a read-only architectural diagnosis of the existing central administrative
authorization gate. It recommends how a later, separately authorized phase can
make a *governed* request fail closed when it has neither a granular requirement
nor an approved exemption. It does not authorize or implement that change.

**Recommendation: Option E, a hybrid rule-classification + requirement-registry
gate.** A request is governed when its resolved Flask rule is under `/admin` or
its endpoint is in a small, explicit registry of non-`/admin` administrative
callbacks. For a governed request and normalized method, exactly one of these
must exist: a granular requirement or an approved explicit exemption. Otherwise
the gate denies before any handler, access-context load, or domain mutation.

This is deliberately not a global “unknown endpoint means forbidden” rule. That
would break routing errors and framework behavior. It is fail closed inside a
defined, tested administrative boundary.

## 2. Initial Git reconciliation

| Check | Actual value |
|---|---|
| Branch | `refactor/architecture-safety-net` |
| Starting HEAD | `042288ae536bb0bf8b61cca0cdf6edf9fdddf3b0` |
| Parent | `c9e1843cc4fe7df18f24cad057aca1194476b394` |
| `origin/main...HEAD` | `0 15` |
| `c9e1843` ancestor / commits after | yes / `1` |
| Initial worktree, index, untracked files | clean / empty / none |
| Python | `3.11.15` |

The accepted chain is `a9d375d` (policy decision) → `ed1803f` (decision
closeout) → `c9e1843` (B2 mappings) → `042288a` (B2 acceptance closeout).
`git show --check 042288a` was clean. Repository state agrees with the accepted
documentation: R22/R23 use `atividades/view`, R24 uses `banco_dados/view`, the
unmapped-admin baseline is empty, and the current gate still allows a `None`
requirement to continue.

## 3. Evidence inspected

### Read completely

- `PROJECT_STATE.md`, `AGENT_HANDOFF.md`
- `app/auth.py`, `tests/conftest.py`, `pytest.ini`
- `tests/test_rbac_requirement_coverage.py`
- `tests/_artifacts/rbac_unmapped_routes_baseline.json`
- `tests/test_ref_0c_b1_rbac_high_confidence_mappings.py`
- `tests/test_ref_0c_b2_diagnostic_rbac.py`
- `docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md`
- `docs/refactor/REF_0C_B1_P0_ACCESS_CONTEXT_TRANSACTION_HYGIENE.md`
- `docs/refactor/REF_0C_B2_A_DIAGNOSTIC_ACCESS_POLICY_DECISION.md`
- `docs/refactor/REF_0C_B2_DIAGNOSTIC_RBAC_IMPLEMENTATION.md`

### Relevant source and registration inspection

- `main.py`: application construction, all route decorators, access-context
  loading, `_admin_can`, gate, denial transport, upload/static-like route,
  health route, error handlers, and legacy rebindings.
- `app/__init__.py`: `create_app`, core routes, static handling supplied by
  Flask, CSRF handler, application hooks, and blueprint registration.
- `app/views/core.py`: login, logout, index.
- `app/views/aluno.py`: registered aluno blueprint and `@aluno_required` routes.
- `presets_api.py`: registered administrative API blueprint and its separate
  `_require_admin` guard.

No real `database.db` or production logs were opened. Dynamic inventory imports
used temporary `APP_DATABASE`, document, backup, and testing settings only.

## 4. Commands and validation evidence

Pre-flight commands were exactly the twelve commands required by the handoff:
branch/HEAD/parent/divergence/status/index/log/show/ancestry/count/Python checks.
Additional read-only commands dynamically enumerated `main.app.url_map`, matched
Flask routing for 404/405/HEAD/OPTIONS/static/login/logout, and inspected route,
hook, decorator, and error-handler source.

Focused validation:

```text
.venv\Scripts\python.exe -m pytest \
  tests\test_rbac_requirement_coverage.py \
  tests\test_ref_0c_b1_rbac_high_confidence_mappings.py \
  tests\test_ref_0c_b1_p0_access_context_transactions.py -q --tb=no --disable-warnings -rN
40 passed in 22.36s; exit 0

.venv\Scripts\python.exe -m pytest \
  tests\test_ref_0c_b2_diagnostic_rbac.py -q --tb=no --disable-warnings -rN
18 passed in 24.83s; exit 0
```

Combined result: **58 passed, exit 0**. These tests use fixture-controlled
databases and isolated runtime/log paths. A full suite was not required and was
not run.

## 5. Dynamic route inventory

The runtime map contains **131 rules**, **130 endpoints**, and **160 business
route-method combinations** (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`). Flask
adds automatic `OPTIONS` to all 131 rules and automatic `HEAD` to the 111 rules
that allow GET.

| Inventory class | Rules / endpoints | Business combinations | Requirement state | Proposed boundary |
|---|---:|---:|---|---|
| `/admin` routes in `main.py` | 107 endpoints | 129 | explicit for every pair; each inspected handler has `@admin_required` | governed |
| `/admin/api/presets` blueprint | 2 endpoints | 2 | explicit; handler has its own `_require_admin` guard | governed |
| Non-`/admin` OAuth callbacks | 3 endpoints | 3 GET | explicit `banco_dados/edit`; `@admin_required` | governed by explicit external registry |
| Aluno blueprint and legacy aluno routes | aluno endpoints | 19 | no admin requirement; `@aluno_required` | non-admin |
| Public core, health, uploads, favicon, static | remaining endpoints | 7 | no admin requirement, except protected upload handler has local policy | non-admin/framework |
| Total | 130 endpoints | 160 | 134 explicit requirements; 26 non-admin combinations have none | as above |

The 109 `/admin` endpoints yield **131** business combinations: **all 131 have
an explicit requirement**, **zero lack one**. `107` have a `functools.wraps`
wrapper from the administrative decorator and the remaining two are
`presets.get_presets` and `presets.post_presets`, which deliberately enforce
their own `_require_admin` contract. The non-prefix governed callbacks are
`google_callback`, `onedrive_callback`, and `auth_callback`; each is GET and
currently maps to `banco_dados/edit`.

The versioned artifact contains `"unmapped_routes": []`, and the existing
coverage test dynamically reaches the same empty result. This proves today's
business-method inventory is mapped; it does **not** prove that a future route,
automatic method, or routing error would be safe under an indiscriminate global
deny rule.

For every business combination, the dynamic inventory recorded rule, endpoint,
method, prefix classification, requirement, and automatic HEAD/OPTIONS flags.
All `/admin` combinations are admin/governed; all three callback combinations
are admin/governed external exceptions; aluno routes are aluno-only; core,
health, favicon and Flask static are public/framework; uploads are a non-admin
route with its own authoritative per-file policy. No current business
combination is an approved granular-RBAC admin exemption.

## 6. Current control flow

`enforce_admin_access_control` is an application `before_request` hook. It:

1. substitutes `""` for a missing endpoint;
2. returns immediately unless `session["user_type"] == "admin"`;
3. calls `get_admin_permission_requirement(endpoint, request.method)`;
4. returns immediately when it receives `None` (**current fail-open point**);
5. otherwise reloads the admin access context, stores the requirement in `g`,
   permits a sufficient scope, or uses `_admin_access_denied_response`.

The latter returns JSON `403` for `X-Requested-With: XMLHttpRequest`; otherwise
it flashes and redirects to `admin_dashboard`. The outer `@admin_required`
decorator separately redirects anonymous and aluno sessions to login. The
presets blueprint additionally requires the gate to have written the matching
requirement into `g`.

| Request case | Current hook / outcome | Fail-closed compatibility result |
|---|---|---|
| Anonymous public route | hook returns before lookup; handler runs | unchanged |
| Anonymous admin route | hook returns; `@admin_required` redirects login | unchanged |
| Aluno admin route | hook returns; `@admin_required` redirects login | unchanged |
| `admin_total`, mapped admin route | lookup → context reload → allow | unchanged |
| `administrativo`, mapped view route | lookup → sufficient scope → allow | unchanged |
| `consultivo`, mapped edit route | lookup → existing browser redirect or AJAX 403 | unchanged |
| Authenticated admin, governed missing requirement | lookup returns `None`; handler presently runs | future configuration denial before handler |
| `request.endpoint is None` | hook calls lookup with empty string; passes | preserve framework result |
| 404 | no matched endpoint; 404 handler renders 404 | preserve 404, never turn into auth denial |
| 405 | Flask match raises `MethodNotAllowed` before an endpoint is usable | preserve 405 and `Allow` |
| HEAD to GET rule | endpoint resolves, current lookup receives `HEAD` | normalize to GET requirement |
| Automatic OPTIONS | endpoint/rule resolves, current lookup can be inconsistent | framework exemption; preserve negotiation |
| Static file | Flask endpoint `static`, no admin classification | unchanged |
| Login / logout | core endpoints, no admin classification | unchanged |
| AJAX scope denial | existing JSON 403 | unchanged for mapped scope denial; distinct config code for missing mapping |
| Browser form scope denial | existing flash + dashboard redirect | unchanged for mapped scope denial; generic configuration 403 for missing mapping |

The access-context transaction hygiene fix matters here: a mapped request reloads
context through the transaction-neutral helper. A missing-requirement rejection
should happen **before** that reload, avoiding needless schema/context activity,
and must retain the B1-P0 no-leak invariant.

## 7. Designs evaluated

| Option | Assessment | Decision |
|---|---|---|
| A. Decorator-only | Runtime decorator identity is not a stable Flask route property. `wraps` preserves `__wrapped__`, but not a reliable identity of which decorator was applied; the presets endpoints intentionally use another guard. This couples policy to wrapper mechanics. | reject |
| B. `/admin` URL prefix | Covers all current 131 prefix combinations, is easy to test, and makes a newly added `/admin` route fail closed. It misses the three mapped OAuth callbacks outside `/admin`; a broad non-prefix exception would become open-ended. | insufficient alone |
| C. Explicit endpoint registry | Clear and testable, but duplicates the requirement mapping and silently ages on endpoint renames unless route coverage tests are strict. | useful component, not sole classifier |
| D. Requirement registry only | A newly added admin route has no requirement, so it is outside the classifier and passes. It is therefore not fail closed. | reject |
| E. Hybrid | Use resolved `/admin` rule classification plus a tiny explicit external governed-endpoint registry; require requirement-or-exemption inside it. Coverage tests bind all three sources. | **recommend** |

## 8. Recommended applicability predicate

The later implementation should use the resolved rule, not endpoint-name prefixes
or decorator introspection. In precise order:

```text
if request.endpoint is None or request.url_rule is None:
    outside boundary; let Flask return its normal routing/error response
elif request.method == OPTIONS and request.url_rule.provide_automatic_options:
    framework exemption; continue
else:
    effective_method = GET if request.method == HEAD and GET is allowed else request.method
    governed = (
        rule.rule == "/admin" or rule.rule.startswith("/admin/")
        or endpoint in NON_ADMIN_RBAC_GOVERNED_ENDPOINTS
    )
    if not governed:
        continue
    requirement = requirement_for(endpoint, effective_method)
    exemption = explicit_exemption_for(endpoint, effective_method)
    if requirement and not exemption: enforce requirement
    elif exemption and not requirement: continue
    else: fail closed as authorization configuration error
```

`NON_ADMIN_RBAC_GOVERNED_ENDPOINTS` initially contains exactly
`auth_callback`, `google_callback`, and `onedrive_callback`; each has GET only.
It must be expressed as an endpoint/method registry, not a URL-prefix exception.
The implementation should reject the invalid dual state (both mapping and
exemption) as well as the absent state. A newly added `/admin` rule consequently
fails both coverage and runtime until deliberately mapped or explicitly approved
as an exemption.

This boundary intentionally treats a future public route under `/admin` as an
explicit design decision: it must be moved outside the prefix or receive a
non-admin/framework exemption reviewed by tests. It must not acquire a broad
“public under `/admin`” bypass.

## 9. Exemption contract

There are **no current explicit administrative business-method exemptions**.
Every current governed method has a granular requirement. The registry must be
empty initially and remain an allow-list with this shape:

```text
{ endpoint: { methods: {...}, reason, current_protection, owner, required_test } }
```

An exemption entry is valid only when it names the endpoint and methods, explains
why no granular scope is authoritative, identifies its alternate protection,
records risk, and has a coverage/runtime test. It may never be a prefix, wildcard,
`None` fallback, or “all OPTIONS” catch-all.

| Category | Treatment | Current examples |
|---|---|---|
| Framework exemption | outside boundary or automatic OPTIONS only | static, endpoint-less routing failures, automatic OPTIONS |
| Authentication infrastructure | non-admin route, outside boundary | login, logout, index, CSRF token refresh |
| Non-admin route | outside boundary; preserve its own access mechanism | aluno blueprint, health, uploads |
| External governed endpoint | inside explicit external registry; must map | three OAuth callbacks |
| Explicit admin exemption | only named endpoint+method registry after approval | none today |
| Prohibited exemption | no broad prefix/wildcard/unknown-method/endpoint fallback | all such forms |

Password recovery and test/development-only routes are not present in the live
map. If later added outside `/admin`, they remain non-admin; if placed under
`/admin`, the fail-closed test forces an explicit reviewed decision. CLI functions
do not traverse HTTP hooks and are not candidates for this registry. CSRF errors
are handled by Flask-WTF's error handler and must not become exemptions for a
governed handler; `before_request` authorization still precedes handler execution.

## 10. Method normalization contract

1. GET, POST, PUT, PATCH, and DELETE use uppercase canonical matching in one
   lookup helper. The current map contains GET/POST business methods, but the
   contract must cover the others.
2. HEAD for a rule that permits GET inherits the GET requirement. Flask strips
   the body; authorization must not become weaker merely because the response is
   bodyless. This corrects the present B2 GET-only branches, which otherwise
   return `None` for `HEAD`.
3. Automatic OPTIONS is a framework exemption when `provide_automatic_options`
   is true. It must not load context or require a granular mapping; this preserves
   normal `Allow`/method negotiation and avoids accidental CORS breakage.
4. A deliberately registered OPTIONS handler is not automatic. It must have its
   own requirement or a precise approved exemption.
5. A matched governed endpoint with an unregistered, permitted business method
   is a configuration failure and fails closed. A method disallowed by the Flask
   rule is a normal 405, not an authorization failure.
6. Normalize centrally before both requirement and exemption lookup; do not
   scatter HEAD special cases in route mappings.

## 11. Missing endpoint and error behavior

`request.endpoint is None`, `request.url_rule is None`, malformed/unknown URLs,
and exceptions raised before routing are outside the predicate. They retain Flask
404/400/500 behavior. Dynamic matching confirmed `/does-not-exist` → 404 and
`POST /admin/dashboard` → 405; both must remain so even for an authenticated
administrator. The gate must never make a 404/405 look like an authorization
failure.

The application 404/500 handlers render public error templates; they must not
attempt a second authorization pass merely because an admin session exists. If a
future error handler renders privileged data, that handler needs its own reviewed
design rather than an implicit gate exemption.

For a resolved governed endpoint with an absent/ambiguous mapping, this is not an
unknown URL: it is a deployment configuration defect. Deny it before context
loading and handler execution. The same applies to an endpoint listed in the
external registry but renamed or removed: coverage should catch it before
deployment; runtime remains closed as defense in depth.

## 12. Denial and observability contracts

Mapped scope denials retain the accepted behavior:

- authenticated admin browser: flash + redirect to `/admin/dashboard`;
- authenticated admin AJAX: JSON 403 with `error: forbidden`, resource and
  required scope;
- anonymous or aluno admin request: existing outer redirect to `/login`.

For a **missing requirement on a governed endpoint**, recommend a distinct,
non-sensitive authorization-configuration failure:

| Environment / caller | Recommended response |
|---|---|
| Production browser | generic HTTP 403 page/message, no dashboard redirect and no mapping detail |
| Production AJAX | JSON HTTP 403: `ok: false`, `error: authorization_configuration_error`, generic message only |
| Development / test | raise a dedicated configuration exception (or surface HTTP 500) so the defect cannot resemble normal insufficient scope |
| Mapped scope denial everywhere | unchanged accepted transport |

The production status is deliberately 403 to fail safely without exposing the
endpoint's policy internals. Structured error logging differentiates it from a
true scope denial. Development/test must make this unmistakable, and future tests
must prove no database/file mutation and no open transaction on either path.

Initial enforcement should include structured error-level observability; it is a
rollout requirement, not an optional afterthought. Record event name, endpoint,
normalized method, rule template (not raw query), authenticated access level,
request/correlation ID when available, and deployment mode. Never record session
cookies, authorization headers, form bodies, credentials, raw query strings, or
unredacted personal data. No logging is implemented in this diagnosis.

## 13. Compatibility risks

- A new `/admin` route, a newly permitted method, or a renamed endpoint can be
  unavailable until mapping/exemption and tests land; that is the intended safe
  failure.
- The three OAuth callbacks prove that `/admin` is not the whole boundary; an
  endpoint rename can break them without the external-registry reconciliation.
- Shared handlers and method-specific mappings require normalized HEAD and
  method coverage.
- Extensions or dynamically registered blueprints added after the coverage
  inventory runs need an application-factory/registration contract and a test;
  otherwise they risk stale inventory.
- Existing dynamically created test routes must either be registered before
  inventory and explicitly mapped/exempt, or intentionally live outside the
  boundary. Test-only prefix bypasses are prohibited.
- Automatic OPTIONS and HEAD are the chief protocol compatibility risks.
- Browser callers expect redirect on ordinary insufficient scope; preserve it.
  AJAX callers expect JSON for ordinary scope denial; preserve it.
- Access context has prior transaction-hygiene constraints; missing-config denial
  must not load context, and mapped paths must retain B1-P0 behavior.
- The uploads route and presets routes have local authoritative mechanisms;
  neither should be accidentally reclassified by endpoint-name heuristics.

## 14. Rollout and rollback

Recommended later phases, each separately authorized:

1. **Characterization:** add exhaustive route/rule/method classification tests,
   including the external callback registry and 404/405/HEAD/OPTIONS.
2. **Registry contract:** introduce constants/data structures only, with an empty
   explicit-exemption registry and validation that requirement XOR exemption is
   true for every governed combination.
3. **Shadow/audit mode:** calculate and log missing/ambiguous configuration in a
   controlled non-production or canary environment without changing user
   responses. Bound its duration and exit criteria.
4. **Fail-closed test mode:** enable hard missing-config failure in test and
   development; prove all characterization and immutability contracts.
5. **Production enforcement:** deploy the production configuration-denial path
   with structured event monitoring and an explicit deployment checklist.
6. **Post-deploy review:** confirm zero missing-config events; remove any
   temporary shadow-only path rather than retaining a bypass.

A permanent runtime compatibility switch is **not recommended**: it makes the
security boundary optional and can become a silent bypass. If an emergency
rollback is required, use a short-lived, operator-controlled deployment rollback
to the prior verified artifact, or a time-bounded release-level kill switch with
auditable ownership, alerting, default-off semantics, and removal deadline. The
preferred rollback is deploy rollback, not a request-controlled or long-lived
allow-open flag. Preserve the route inventory and logs needed to diagnose the
failed deployment, but do not collect sensitive request data.

## 15. Future test contract

The later implementation must add, at minimum:

1. every governed route-method has exactly one requirement or approved exemption;
2. a newly added unmapped `/admin` route fails coverage;
3. that route fails closed at runtime before its handler;
4. a non-admin route remains unaffected;
5. login and logout remain functional;
6. anonymous admin access retains login redirect;
7. aluno admin access retains authentication denial;
8. browser missing-requirement response follows the production contract;
9. AJAX missing-requirement response follows the production contract;
10. explicit mapped-scope denial is unchanged;
11. 404 remains 404 and 405 remains 405 with method negotiation intact;
12. HEAD inherits GET and has no bypass;
13. automatic OPTIONS remains functional; explicit OPTIONS is mapped/exempt;
14. static-file behavior and endpoint-`None` behavior remain unaffected;
15. a denied request makes no database mutation or filesystem mutation;
16. missing-config rejection opens/leaks no transaction; mapped paths retain
    B1-P0 transaction neutrality;
17. tests use no real database or production logs;
18. exemption-registry schema, reason, alternate protection, and test coverage
    are validated, with no wildcard entries;
19. endpoint rename/removal breaks coverage rather than silently bypassing;
20. dynamic blueprint registration before app finalization is inventoried;
21. registration after finalization is either prohibited or fails a startup/test
    assertion;
22. every non-`/admin` external governed endpoint is present in both route and
    requirement reconciliation;
23. observability emits safe fields for configuration denial and no secrets.

## 16. Recommended phase decomposition and unresolved decisions

| Later phase | Scope |
|---|---|
| REF-0C-C-B | characterization tests and authoritative route-classification contract only |
| REF-0C-C-C | registry/normalization implementation plus tests, development/test hard failure |
| REF-0C-C-D | controlled shadow/canary and production enforcement decision |

No phase above is authorized by this document.

Supervisor/user decisions still required:

1. approve Option E and the exact three-callback external registry;
2. approve the production missing-configuration response (recommended generic
   403) versus a production 500 policy;
3. approve mandatory structured observability and its retention/monitoring owner;
4. decide whether a tightly governed emergency release kill switch is needed or
   deployment rollback alone is acceptable;
5. define the policy for extensions that register routes after application setup.

Confidence is **high** for the current-route boundary, mapping reconciliation,
and HEAD/OPTIONS/404/405 constraints; **medium-high** for production transport
and rollout mechanics because they require operational ownership decisions.

## 17. Confirmation of non-implementation

No production code, test, route, artifact baseline, database, schema, dependency,
UI, JavaScript, observability, exemption registry, runtime switch, or fail-closed
gate was changed. This phase changes documentation only. Fail-closed behavior is
**not active**, and no subsequent implementation phase is authorized. The exact
next action is ChatGPT supervisor review followed by the user's architectural
decision.
