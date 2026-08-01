# Phase 4 Admin Blueprint Compatibility Contract

## 1. Authority and status

This document is the canonical compatibility contract for the incremental Phase 4 admin-blueprint extraction.

Current authorized unit: **PHASE 4-B1 — IMPLEMENTED / AWAITING SUPERVISOR REVIEW**.

Phase 4 is not closed. Phase 4-B2 is not authorized. Phase 5 and Phase 6 are not authorized. Migration v4 is prohibited.

## 2. Accepted endpoint-preservation strategy

Phase 4 uses transitional Flask blueprints as ownership containers while preserving every existing global endpoint name. A moved view is not registered with `@bp.route`, because normal blueprint registration would introduce a namespaced endpoint and break `url_for`, `request.endpoint`, RBAC classification, templates, and compatibility imports.

The accepted pattern is:

1. represent each legacy route with one immutable specification containing its exact rule, endpoint, view function, and business methods;
2. attach the specification tuple to one uniquely named blueprint through `Blueprint.record_once`;
3. during factory registration, preflight the complete tuple set before mutation;
4. register each rule through `state.app.add_url_rule(..., endpoint=<legacy name>)`;
5. create no namespaced endpoint, alias, duplicate decorator, or second rule;
6. register the blueprint only through `create_app`, never through `main.py`.

Legacy endpoints remain transitional compatibility contracts until the final Phase 4 cohort completes and a separately authorized cleanup proves that all callers, templates, RBAC mappings, tests, and external integrations can cut over atomically. No cleanup is authorized by B1.

## 3. Registrar ownership and collision contract

`app/views/admin/__init__.py` owns the reusable registrar and contains no business logic.

The registrar must:

- use immutable route specifications;
- use `Blueprint.record_once` and `state.app.add_url_rule`;
- reject a blueprint that was already registered on the same Flask application;
- reject any preexisting requested endpoint;
- reject a preexisting exact rule/business-method collision, including one owned by a different endpoint;
- validate the complete specification set and the complete target application before adding any B1 rule;
- raise `LegacyRouteRegistrationError` explicitly rather than silently skipping a conflict;
- permit the same blueprint object to be registered once in each of two independently created Flask applications.

`state.add_url_rule`, `@bp.route`, namespaced aliases, silent collision skips, and duplicate rules are prohibited.

## 4. Exact Phase 4-B1 route scope

B1 moves exactly eight rules and no ninth admin route:

| Rule | Endpoint | Methods | RBAC requirement |
|---|---|---|---|
| `/admin/configuracoes` | `admin_configuracoes` | `GET` | `configuracoes:view` |
| `/admin/configuracoes/horas-padrao` | `admin_configuracoes_horas_padrao_salvar` | `POST` | `configuracoes:edit` |
| `/admin/configuracoes/prazo-adequacao` | `admin_configuracoes_prazo_adequacao_salvar` | `POST` | `configuracoes:edit` |
| `/admin/configuracoes/tempo-resposta` | `admin_configuracoes_tempo_resposta_salvar` | `POST` | `configuracoes:edit` |
| `/admin/configuracoes/tempo-resposta/reset` | `admin_configuracoes_tempo_resposta_resetar` | `POST` | `configuracoes:full` |
| `/admin/mensagens` | `admin_mensagens` | `GET` | `mensagens:view` |
| `/admin/mensagens/salvar` | `admin_mensagens_salvar` | `POST` | `mensagens:edit` |
| `/admin/mensagens/<message_key>/reset` | `admin_mensagens_resetar` | `POST` | `mensagens:full` |

Dashboard, Requisições, `dashboard.py`, `admin_meus_dados`, and every other admin cohort remain in their existing owners. Their future ownership is unresolved and requires explicit authorization.

## 5. Settings-helper ownership

`app/views/admin/configuracoes.py` is the sole defining owner of:

- `_normalize_optional_iso_date`;
- `get_app_settings`;
- `get_response_time_settings`;
- `save_app_settings`;
- `reset_response_time_metrics`;
- `save_return_response_settings`;
- `get_horas_settings`;
- `save_horas_settings`.

The module also owns the eight B1 view functions, the unique blueprint object, and the exact route-specification tuple. It must not import `main`, create an application, connect to a database, write to the filesystem, call the network, or register against a concrete app at import time.

## 6. Main compatibility-export policy

`main.py` imports and re-exports the exact canonical route and helper objects from `app.views.admin.configuracoes`. Compatibility is identity-based:

- no wrapper;
- no forwarding function;
- no duplicated helper body;
- no duplicated route decorator;
- no runtime proxy;
- no import of `main` from `app/`.

Remaining Dashboard and Requisições code in `main.py` continues to resolve the imported settings helpers without functional alteration. The compatibility exports remain until a separately authorized final Phase 4 cleanup.

## 7. Factory wiring

`app.create_app` owns B1 registration through the bounded flag:

`register_admin_configuracoes_blueprint: bool = True`

The default factory and `main.app` receive all eight global legacy endpoints exactly once. An isolated test caller may set the flag to `False`. Independent factory calls each receive the same eight routes once. Existing preset, aluno, core, CSRF, teardown, security-header, and `route_url` behavior remains unchanged.

## 8. Route, endpoint, RBAC, and behavior invariants

B1 must preserve:

- 131 Flask route tuples;
- 130 unique endpoints;
- 134 governed route/method pairs;
- zero RBAC-unmapped admin routes;
- actor matrix 402 = 263 allowed + 139 denied;
- byte-identical canonical route snapshot;
- exact URL, business methods, global endpoint, `url_for`, and `request.endpoint` for every moved rule;
- exact `admin_required`, central RBAC, browser/AJAX denial, and CSRF behavior;
- exact templates, redirects, flash messages, validation, settings persistence, and message save/reset behavior;
- no endpoint beginning with the B1 blueprint namespace;
- no duplicate rule and no `app -> main` import.

All tests must use disposable databases and runtime roots. The canonical SQLite database must never be opened by this unit.

## 9. Authorized B1 manifest and boundaries

Production paths are exactly:

1. `app/__init__.py`;
2. `main.py`;
3. `app/views/admin/__init__.py`;
4. `app/views/admin/configuracoes.py`;
5. `utils/messages.py`, limited to deterministic recursive AST/read-only discovery under `app/views/**/*.py` and static `LegacyRouteSpec` route metadata.

Test paths are `tests/test_phase4_configuracoes_blueprint.py` and `tests/test_csrf_inventory_audit.py`; the latter is limited to deterministic recursive canonical-owner discovery and transitional `main` compatibility identity for the eight moved handlers. Governance paths are this contract, `docs/DOCUMENTATION_INDEX.md`, `docs/mapeamento/05_avaliacao_refactor.md`, `docs/refactor/ARCHITECTURE_REFACTOR_LEDGER.md`, `PROJECT_STATE.md`, and `AGENT_HANDOFF.md`. The complete authorized manifest is exactly 13 paths; no fourteenth path is authorized.

No template, JavaScript/static asset, route/RBAC snapshot, auth module, database module, migration, versioning module, Phase 5 file, or Phase 6 file is in scope.

## 10. Final Phase 4 cleanup condition

After the last explicitly authorized Phase 4 cohort — not during B1 — a separate cleanup unit must inventory all legacy endpoint consumers and compatibility exports, prove route/RBAC/actor/CSRF invariants, and remove only transitional machinery that has no remaining consumer. The registrar and `main` compatibility imports cannot be removed merely because one cohort is complete.

B1 does not schedule Phase 5, authorize migration v4, resolve `dashboard.py` ownership, resolve `admin_meus_dados` ownership, or authorize B2.
