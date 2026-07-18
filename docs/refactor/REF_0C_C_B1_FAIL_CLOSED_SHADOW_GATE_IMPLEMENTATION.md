# REF-0C-C-B1 — Hybrid Boundary, Production Shadow Audit, and Test/Development Hard Failure

## Scope and accepted decision

REF-0C-C-A was accepted at diagnosis commit `020cd7f` and closed at `9453aa2`.
This implementation performs only the authorized first rollout stage: canonical
hybrid classification, an empty explicit-exemption registry, production audit-only
handling for missing governed configuration, and hard configuration failure in
testing/development. Production hard denial is not active or authorized.

Starting branch/implementation parent: `refactor/architecture-safety-net` at
`9453aa2`. R20, UI, schema, database, dependency, and modularization scope remain
unchanged and prohibited.

## Callback classification

The accepted diagnosis classifies all three callbacks as **additional governed
administrative endpoints outside `/admin`**, not authentication exemptions:

| Endpoint | Rule | Normalized method | Requirement |
|---|---|---|---|
| `auth_callback` | `/auth/callback` | GET | `banco_dados/edit` |
| `google_callback` | `/google/callback` | GET | `banco_dados/edit` |
| `onedrive_callback` | `/onedrive/callback` | GET | `banco_dados/edit` |

The registry is endpoint-and-method specific. Callback-like names and other
non-prefix routes are not governed by name similarity.

## Exact classifier and exemption contract

`app.auth.classify_governed_admin_request(endpoint, url_rule, method)` is a
database-free, near-pure classifier. It requires a Flask-resolved endpoint and
rule. A request is governed only if the resolved rule is `/admin` or below, or the
endpoint/method is one of the three literal external callback entries.

For a governed normalized pair, the classifier returns exactly one of
`requirement`, `exemption`, `missing_configuration`, or
`invalid_configuration`. A requirement and exemption together are invalid; their
absence is missing configuration. Every current governed business pair resolves
to one explicit requirement.

`APPROVED_ADMIN_RBAC_EXEMPTIONS` is deliberately `{}`. It accepts only literal
`(endpoint, normalized_method)` keys with review metadata in a later authorized
phase; no prefix, wildcard, blueprint, catch-all, or authentication exemption was
introduced.

## Method, framework, and error behavior

- `GET`, `POST`, `PUT`, `PATCH`, and `DELETE` are uppercased centrally.
- HEAD inherits GET when the resolved rule permits GET; B2's GET-only diagnostics
  therefore do not acquire a HEAD bypass.
- Flask-generated automatic OPTIONS is returned as `automatic_options` before
  governed lookup. Explicit OPTIONS remains governed and requires a mapping or
  an approved precise exemption.
- Missing endpoint/rule is outside the boundary. Flask 404 and 405 responses,
  static files, public routes, aluno routes, login, logout, and error handlers are
  unchanged. A Flask-generated 405 has no authorization configuration failure.

## Runtime behavior

Mapped requirements keep the accepted access-context reload and existing browser
redirect/AJAX JSON-403 scope-denial behavior. Exemptions would continue without
granular lookup, but none exist.

A missing or ambiguous governed configuration is handled before access-context
loading:

- **testing/development:** raises `AdminAuthorizationConfigurationError`, a
  distinct hard configuration failure rather than user scope denial;
- **production:** emits one `logger.error` shadow event and allows the current
  request behavior to continue. It does not return 403 and has no runtime
  allow-open switch.

The event uses stable text `event=admin_rbac_missing_configuration` and only
endpoint, normalized method, rule template, already-present session access level,
and `rollout_mode=production_shadow`. It does not include raw query strings,
form/body data, cookies, session contents, credentials, OAuth tokens, student
data, or raw URLs. The gate executes once per request, producing one event.

## Transaction safety

Classification runs before `_get_current_admin_access_context`. Focused tests
replace that loader with a failure sentinel and prove missing configuration never
loads it. The no-database assertion proves no `g.db` is opened on the hard-failure
path; no context load means no access-schema DML, commit, rollback, or filesystem
side effect. Existing B1-P0 transaction-hygiene tests remain part of focused
validation.

## Changed files

- `app/auth.py`: classifier, normalized method helper, callback registry, empty
  exemption registry, and configuration exception.
- `main.py`: classifier-first gate and safe production shadow audit.
- `tests/test_ref_0c_c_b1_fail_closed_shadow_gate.py`: boundary, methods,
  framework, shadow/hard-failure, actor, immutability, and no-context tests.
- this document, `PROJECT_STATE.md`, and `AGENT_HANDOFF.md`.

No existing RBAC test was weakened or changed. No baseline was regenerated.

## Focused validation

```text
.venv\Scripts\python.exe -m pytest tests\test_ref_0c_c_b1_fail_closed_shadow_gate.py -q --tb=short
23 passed in 11.47s; exit 0
```

Combined focused validation (`new C-B1 + coverage + B1 + B2 + B1-P0`) completed
with `81 passed`, exit 0 (independent collection also reported 81 tests). The detached full hermetic suite ran at
`C:\Users\klebe\AppData\Local\Temp\sgaa-ref-0c-c-b1-full-validation` from the
implementation commit using the primary workspace virtualenv but no primary
workspace database/data: `600 passed, 17 deselected in 427.00s`, exit 0. This is
a `+23` selected-test delta from the accepted 577-pass baseline, exactly the new
C-B1 tests. The disposable worktree and its temporary captured output were removed
after evidence collection.

## Preserved prohibitions and status

There is no production hard denial for missing mapping, no permanent allow-open
flag, no broad exemption, no RBAC policy change, no R20 change, and no UI,
database, schema, dependency, or modularization change. REF-0C-C-B1 is
implemented locally and pending ChatGPT supervisor review.

## R1 shadow-audit failure safety correction

Review found that the original production shadow helper allowed a normal
`logger.error` backend exception to escape and fail the request. R1 contains that
normal `Exception` locally in `_audit_missing_admin_authorization_configuration`.
It does not catch `BaseException`, does not re-raise, and deliberately performs no
recursive logger call, print, traceback output, or alternate fallback. The original
safe event payload is unchanged.

`test_production_shadow_logger_failure_does_not_block_request_or_load_context`
registers and removes a temporary unmapped `/admin` rule at the URL-map layer,
then makes a real Flask request in canonical production-shadow configuration while
the exact `logger.error` call raises. It proves the handler still returns 200, the
logger is attempted exactly once, no fallback/recursive logger call occurs, and
the access-context loader, database connection helper, and access-schema helper
are not invoked. The test also suppresses unrelated snapshot work so no database
or filesystem operation is available on this characterization path.

Focused R1 validation selected 99 tests across C-B1, RBAC coverage/B1/B2, P0, and
login/logout/404/405/security coverage: `99 passed`, exit 0. The full hermetic
suite in a fresh detached worktree selected 601 tests: `601 passed`, with 17 D73H
tests deselected, exit 0. This is a +1 selected-test delta from the pre-R1
600-pass baseline, exactly the new logger-failure regression. Production remains
shadow-only, and the status remains pending ChatGPT supervisor review.
