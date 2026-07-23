# REF-0C-D-R1 — Route-Complete Actor Decision and Pre-Handler Denied-Action Immutability

## Contract

**Status:** IMPLEMENTED / VALIDATION PENDING / NOT COMMITTED / NOT PUBLISHED

**Starting HEAD:** `ccb1b926a0a612dae9f7b253231c285dd97a2a32`
(`Record supervisor acceptance of canonical governance foundation`)

**Branch:** `refactor/architecture-safety-net`
**Divergence:** `origin/refactor/architecture-safety-net...HEAD = 0 0`

## Derivation

All counts are mechanically re-derived from:
- `tests/_artifacts/route_inventory_baseline.json` (131 rules, 160 business method combinations)
- Live `main.app.url_map` Flask rules
- `app/auth.py` classifiers, profiles, and `get_admin_permission_requirement`

| Metric | Count | Source |
|--------|-------|--------|
| Baseline rules | 131 | `route_inventory_baseline.json` |
| Baseline business route-method combinations | 160 | Sum of methods across baseline |
| Governed requirement combinations | 134 | `classify_governed_admin_request` → governed=True, kind=requirement |
| Actor cross-product (134 × 3) | 402 | |
| Allowed (admin_total always) | 263 | 134 (admin_total) + 98 (administrativo) + 31 (consultivo) |
| Denied | 139 | 0 (admin_total) + 36 (administrativo) + 103 (consultivo) |
| Governed dynamic route+endpoint+method combos | 53 | Route has converter(s), governed requirement |
| Distinct governed dynamic rules | 43 | Distinct (endpoint, rule) among the 53 |
| External governed callbacks | 3 | `auth_callback`, `google_callback`, `onedrive_callback` (all `banco_dados`/`edit`) |

### Profile resource-scope digests

Algorithm: `json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` then `sha256(raw.encode("utf-8")).hexdigest()`.

Three canonical scope digests — one per admin access level, keyed by `ACCESS_RESOURCE_ORDER`.

### Requirement matrix digest

Algorithm: sort all 134 `(endpoint, method, resource, scope)` tuples, JSON-dump, SHA-256 hex digest. Compact JSON separators.

## Converter strategy

Live governed rules exercise only `IntegerConverter` and `UnicodeConverter`. Generic branches for `FloatConverter`, `PathConverter`, `UUIDConverter`, and `AnyConverter` exist for future use.

`AnyConverter` uses a real Werkzeug instance (`AnyConverter(Map(), *items)`) — not a fake class. Empty items raise `NotImplementedError` naming endpoint, rule, arg and class name.

Unsupported converter type raises `NotImplementedError` identifying endpoint, rule, arg and class name.

| Converter | Python value | Notes |
|-----------|-------------|-------|
| `IntegerConverter` | `1` (or `910000 + case_idx` for AJAX) | Deterministic valid int; AJAX values remain case-unique without banning generic digits |
| `FloatConverter` | `1.0` | Generic support |
| `UnicodeConverter` / default string | Name-mapped | `active_tab`→`"aac"`, `provider`→`"google"`, `message_key`→`"msg_test_0c_d_r1"`, else `"test_{arg}"` |
| `PathConverter` | `"test/path"` | Generic support |
| `UUIDConverter` | `00000000-...-000000000001` | Generic support |
| `AnyConverter` | First permitted item | Real Werkzeug `Map`-bound instance |

## URL roundtrip

Every concrete URL, including all 160 baseline combinations and each browser/AJAX denial-case URL, is built from the exact live `Rule` via `Rule.build(append_unknown=False)` and immediately resolved inside `_build_url_for_governed` via `MapAdapter.match(return_rule=True)`. Building from the exact Rule preserves literal aliases that share one endpoint. Assertions:

- Same `Rule` object identity (`matched_rule is rule`)
- Exact rule literal (`matched_rule.rule == rule_text`)
- Exact endpoint (`matched_rule.endpoint == endpoint`)
- Normalized method in `matched_rule.methods`
- Extracted kwargs equal to converter-normalized supplied kwargs (each value round-tripped through `converter.to_url` then `converter.to_python`)

No broad exception, no literal-rule fallback.

## Browser denial contract

For every one of 139 denied actor-route-method combinations:
- Flask `test_client` sends a normal (non-AJAX) request
- `before_request` gate (`enforce_admin_access_control`) runs
- Per-request closure sentinel replaces `app.view_functions[endpoint]` — raises immediately if invoked
- `finally` restores original handler identity exactly; asserted `app.view_functions[endpoint] is original`
- Assertion error identifies endpoint, rule, method, access level and requirement via `_case_context` string
- No broad `except Exception` — try/finally used only for handler/session restoration
- Assert 302 redirect
- `urllib.parse.urlsplit(Location).path` normalized to `/admin/dashboard`
- Sentinel not invoked
- Fingerprint identical before/after (captured via `_capture_fingerprint(env)`)
- `conn.in_transaction` False after request
- Original handler non-None asserted before installation
- Executed counter exactly 139

Before baseline fingerprinting, the fixture directly initializes the editable-message schema used lazily by the central denial response and commits it, then directly loads the real admin access context. This avoids an allowed HTTP warmup while ensuring that creation of `mensagens_editaveis` is not misclassified as denied-handler mutation.

## AJAX denial contract

For every one of 139 denied actor-route-method combinations:
- `X-Requested-With: XMLHttpRequest` header
- `Authorization: Bearer <unique_case_marker>` header
- 403 JSON response
- `ok: false`, `error: "forbidden"`, `resource` and `required_scope` match the canonical requirement
- Localized `message` present but not asserted for literal equality
- Distinct unique case markers in every dynamic URL argument (via `case_idx`), query parameter, request-body marker (for all methods, including GET), `_csrf_token` on mutating methods, and `Authorization` bearer marker
- Leak absence verified independently for four named surfaces: deterministic serialized JSON, JSON message field, response headers, raw response body — each via its own `_check_surface` call with separate `pytest.fail` naming surface + full case context + leaked value
- Sensitive set includes: all isolated filesystem paths (native string, `Path.as_posix()`, JSON-escaped), all built kwarg strings, distinct query/body/CSRF/auth markers, and `traceback`/`exception` literals. The route URL itself is not treated as secret.
- Specific digits such as `'1'` are not banned
- Status 403, ok false, error forbidden, exact resource/scope, sentinel absent, fingerprint identical
- `conn.in_transaction` False after request
- Original handler non-None asserted before installation
- Executed counter exactly 139

## Sentinel

- Per-request closure state (dict), not module global
- Before each denial HTTP request: store original `app.view_functions[endpoint]`
- Assert original is non-None (all governed endpoints have registered handlers)
- Replace with a function that raises `RuntimeError("sentinel invoked for {endpoint}")`
- `finally` block restores exact original handler identity
- After restoration: assert `app.view_functions[endpoint] is original`
- If sentinel was reached → before-request gate failed to intercept → test fails
- Assertion error identifies endpoint, rule, method, access level and requirement

## Fingerprint

Algorithm:

1. Assert `Path(main.DATABASE).resolve() == Path(env['db_path']).resolve()`
2. Assert `app.config['DATABASE_PATH'] == main.DATABASE`
3. Open app context, get DB connection
4. Assert `PRAGMA database_list` main file on active connection equals resolved `main.DATABASE`
5. Assert `conn.in_transaction` False
6. Enumerate all application tables (`sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'`)
7. Per table:
   a. Ordered column metadata from `PRAGMA table_info` — each field type-tagged via `_fingerprint_value` (cid, name, type, notnull, dflt_value, pk)
   b. Every complete data row: each value type-tagged via `_fingerprint_value` (N=null, I=integer, R=real, T=text/UTF-8, B=blob/hex)
   c. Serialized row strings sorted in Python via `json.dumps(row, separators=(",", ":"))`
   d. Deterministic JSON payload: `{"table": tname, "columns": [...], "rows": [...]}` with `sort_keys=True`
8. Hash each per-table JSON payload into cumulative SHA-256
9. Assert `conn.in_transaction` False after capture
10. Return hex digest

No `ORDER BY 1` or `default=str`. No write-capable PRAGMA (`wal_checkpoint`, `VACUUM`, `ANALYZE`). Identifiers are SQL-double-quoted with embedded quotes doubled.

Captured before and after each denied HTTP request; asserts strict equality.

## Filesystem isolation

- `db_path`, `uploads_path`, `documents_path`, `local_backups_path`, `cloud_backups_path` all under `tmp_path`
- Temporary log path under `tmp_path` for denied-request logging
- App logging FileHandlers (root logger, `main.logger`, `app.logger`) deduplicated by identity, temporarily redirected to `tmp_path` in `env` fixture
- Original handler list (order-preserved) restored after closing temp handlers

## External governed callbacks

Derived from EVERY governed pair whose literal rule is neither `/admin` nor starts with `/admin/`. The non-admin governed set builds a mapping of endpoint→methods, then asserts exact equality to `auth.NON_ADMIN_RBAC_GOVERNED_ENDPOINTS` and exactly 3 endpoints.

The `test_no_anonymous_selected` exclusion uses `set(auth.NON_ADMIN_RBAC_GOVERNED_ENDPOINTS)` — no hardcoded callback set.

## Contract evidence

- `tests/test_route_inventory_snapshot.py` + `tests/_artifacts/route_inventory_baseline.json`
- `tests/test_rbac_requirement_coverage.py` + `tests/_artifacts/rbac_unmapped_routes_baseline.json`
- `tests/test_ref_0c_b1_rbac_high_confidence_mappings.py`
- `tests/test_ref_0c_b2_diagnostic_rbac.py`
- `tests/test_ref_0c_c_b1_fail_closed_shadow_gate.py`
- `tests/test_ref_0c_b1_p0_access_context_transactions.py`

Focused evidence command (R2 suites not yet run):
```
pytest tests/test_ref_0c_d_r1_route_complete_actor_matrix.py -q --tb=short
```

## Residual risks

- Test module depends on exact baseline JSON and exact Flask URL map; any route change requires deliberate baseline regeneration and re-validation
- HTTP denial tests exercise real `before_request` but do not test production-only code paths (production shadow audit vs test/development hard failure)
- Handler execution is proven absent via sentinel, but handler side-effects are not tested for allowed cases
- Fingerprint excludes `sqlite_%` internal tables only — no application table silently excluded
- Converter values are deterministic but not domain-valid; URL resolution roundtrip proves structural correctness but not that the generated URL is semantically valid for the domain

## Exact status

**IMPLEMENTED / VALIDATION PENDING / NOT COMMITTED / NOT PUBLISHED**

Pending selective supervisor commit. No push performed. No production code, UI, schema, database, dependency, or R20 change.

## Macro Fase 0 remainder

Exactly two Phase-0 remainders:
1. **REF-0C-D-R1** pending external acceptance (this contract)
2. Smoke-flow contract/evidence

**REF-0C-D: PARTIALLY_SATISFIED_REMAINDER_REQUIRED** (not satisfied). Fase 1 and production hard enforcement remain unauthorized.
