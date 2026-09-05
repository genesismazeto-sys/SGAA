"""REF-0C-C-B1 hybrid boundary, shadow audit, and non-production hard-failure contract.

All database-backed assertions use the fixture-controlled versioned environment.
The configuration-failure tests intentionally avoid access-context/database loading.

UT-3 NOTE (monkeypatch retarget completed):
``enforce_admin_access_control`` and its collaborators now live in
``app.web.authz_gate``; ``main`` only re-exports them by identity for Flask
registration. Because the moved implementation resolves ``session``-adjacent
dependencies through ``authz_gate.__globals__``, the direct calls and the
``_get_current_admin_access_context`` / ``logger`` patches below target
``app.web.authz_gate`` -- patching the re-exported ``main`` alias would rebind a
name the executed function never reads and silently void these proofs.

``main.get_db_connection`` / ``main.ensure_usuario_access_schema`` deliberately
stay patched on ``main``: they were never resolved through the gate's globals
(the gate reaches the database only via ``_get_current_admin_access_context``,
which is itself replaced by a failing stub here). They guard the *other*
code still on the executed request path.

UT-5 NOTE (RED, retargeted): the old patch of ``main._maybe_sync_database_snapshot``
guarded against the (now-removed) ``_legacy_post_response_backup_sync``
after_request hook doing real backup I/O during this test. UT-5 deletes that
hook entirely, so patching ``main._maybe_sync_database_snapshot`` would become
dead: nothing on the request path calls it anymore, and post-UT-5 the name
may not even exist on ``main``. The sentinel below targets the lookup the
*new* orchestrator would actually execute if anything on this ordinary
request path still triggered backup orchestration --
``app.backup.orchestrator._maybe_sync_database_snapshot`` -- turning "silently
becomes a no-op" into "fails loudly if backup orchestration reappears on the
request path". At RED (current HEAD), ``app.backup`` does not exist yet, so
this import itself is the expected failure (EXPECTED RED — app.backup
ABSENT), not a weakened/dead assertion.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from werkzeug.routing import Rule


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app import auth
from app.web import authz_gate
from tests.versioned_test_support import isolated_versioned_app_env


BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _resolved_rule(path: str, method: str = "GET"):
    return main.app.url_map.bind("").match(path, method=method, return_rule=True)[0]


def _classification(path: str, method: str = "GET"):
    rule = _resolved_rule(path, method)
    return auth.classify_governed_admin_request(rule.endpoint, rule, method)


def _set_admin_session(access_level: str = "admin_total") -> None:
    from flask import session

    session["user_id"] = 999999
    session["user_type"] = "admin"
    session["access_level"] = access_level


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ref0cc_b1_shadow_gate.db") as value:
        yield value


def _make_admin(access_level: str) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        user_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) "
            "VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                f"C-B1 {access_level}",
                f"cb1.{access_level}.{uuid.uuid4().hex[:10]}@example.com",
                main.hash_password("rbac-test-pass"),
                "admin",
                access_level,
            ),
        ).fetchone()["id"]
        conn.commit()
    return int(user_id)


def _login(client, access_level: str) -> None:
    with client.session_transaction() as value:
        value.clear()
        value["user_id"] = _make_admin(access_level)
        value["user_type"] = "admin"
        value["user_name"] = f"C-B1 {access_level}"
        value["access_level"] = access_level


def test_resolved_admin_rule_is_governed_and_mapped():
    result = _classification("/admin/dashboard")
    assert result["governed"] is True
    assert result["kind"] == "requirement"
    assert result["requirement"] == ("dashboard", "view")


@pytest.mark.parametrize("path", ["/login", "/aluno/dashboard", "/static/no-such-file.css", "/health"])
def test_non_admin_public_aluno_and_static_rules_are_outside_boundary(path):
    result = _classification(path)
    assert result["governed"] is False
    assert result["kind"] == "outside_boundary"


@pytest.mark.parametrize("path,endpoint", [
    ("/auth/callback", "auth_callback"),
    ("/google/callback", "google_callback"),
    ("/onedrive/callback", "onedrive_callback"),
])
def test_accepted_callbacks_are_exact_external_governed_endpoints(path, endpoint):
    result = _classification(path)
    assert result["endpoint"] == endpoint
    assert result["governed"] is True
    assert result["kind"] == "requirement"
    assert result["requirement"] == ("banco_dados", "edit")


def test_callback_like_name_or_outside_admin_rule_is_not_governed():
    rule = Rule("/integration/callback", endpoint="totally_callback_like", methods={"GET"})
    result = auth.classify_governed_admin_request("totally_callback_like", rule, "GET")
    assert result["governed"] is False
    assert result["kind"] == "outside_boundary"


def test_every_current_governed_business_pair_has_exactly_one_policy():
    governed = []
    for rule in main.app.url_map.iter_rules():
        for method in set(rule.methods or ()) & BUSINESS_METHODS:
            result = auth.classify_governed_admin_request(rule.endpoint, rule, method)
            if result["governed"]:
                governed.append(result)
                assert bool(result["requirement"]) != bool(result["exemption"])
                assert result["kind"] in {"requirement", "exemption"}
    assert len(governed) == 130  # 127 /admin pairs + 3 approved external callbacks.


def test_new_governed_unmapped_pair_is_detected_without_route_registration():
    rule = Rule("/admin/unmapped-characterization", endpoint="admin_unmapped_characterization", methods={"GET"})
    result = auth.classify_governed_admin_request(rule.endpoint, rule, "GET")
    assert result["governed"] is True
    assert result["kind"] == "missing_configuration"
    assert result["requirement"] is None
    assert result["exemption"] is None


def test_empty_debt_baseline_and_empty_explicit_exemption_registry_are_preserved():
    from tests.test_rbac_requirement_coverage import build_unmapped_admin_route_inventory

    assert build_unmapped_admin_route_inventory()["unmapped_routes"] == []
    assert auth.APPROVED_ADMIN_RBAC_EXEMPTIONS == {}
    assert not any("*" in endpoint or "*" in method for endpoint, method in auth.APPROVED_ADMIN_RBAC_EXEMPTIONS)


def test_head_inherits_get_without_duplicate_head_mapping():
    rule = _resolved_rule("/admin/diagnostico/atividades-versionadas", "HEAD")
    result = auth.classify_governed_admin_request(rule.endpoint, rule, "HEAD")
    assert result["method"] == "GET"
    assert result["requirement"] == ("atividades", "view")
    assert auth.get_admin_permission_requirement(rule.endpoint, "HEAD") == auth.get_admin_permission_requirement(rule.endpoint, "GET")


def test_automatic_options_is_framework_exempt_and_explicit_options_is_not():
    automatic = _classification("/admin/dashboard", "OPTIONS")
    assert automatic["governed"] is False
    assert automatic["kind"] == "automatic_options"

    explicit = Rule("/admin/explicit-options", endpoint="admin_explicit_options", methods={"OPTIONS"})
    result = auth.classify_governed_admin_request(explicit.endpoint, explicit, "OPTIONS")
    assert result["governed"] is True
    assert result["kind"] == "missing_configuration"


def test_method_normalization_is_uppercase_and_deterministic():
    assert auth.normalize_admin_permission_method(" get ") == "GET"
    assert auth.normalize_admin_permission_method("head", {"GET", "HEAD"}) == "GET"
    assert auth.normalize_admin_permission_method("patch", {"PATCH"}) == "PATCH"


def test_endpoint_none_is_outside_boundary_and_404_405_preserve_flask_behavior():
    result = auth.classify_governed_admin_request(None, None, "GET")
    assert result["governed"] is False
    client = main.app.test_client()
    assert client.get("/does-not-exist").status_code == 404
    response = client.post("/admin/dashboard")
    assert response.status_code == 405
    assert "GET" in response.headers["Allow"]


def test_login_logout_and_automatic_options_retain_current_behavior():
    client = main.app.test_client()
    assert client.get("/login").status_code == 200
    assert client.get("/logout").status_code == 302
    options = client.open("/admin/dashboard", method="OPTIONS")
    assert options.status_code == 200
    assert "GET" in options.headers["Allow"]


def test_testing_missing_configuration_raises_before_access_context(monkeypatch):
    monkeypatch.setattr(auth, "get_admin_permission_requirement", lambda *_: None)
    monkeypatch.setattr(authz_gate, "_get_current_admin_access_context", lambda **_: pytest.fail("context loaded"))
    monkeypatch.setitem(main.app.config, "IS_PRODUCTION", False)
    monkeypatch.setitem(main.app.config, "APP_ENV", "testing")
    with main.app.test_request_context("/admin/dashboard"):
        _set_admin_session()
        with pytest.raises(auth.AdminAuthorizationConfigurationError):
            authz_gate.enforce_admin_access_control()


def test_development_missing_configuration_uses_same_hard_failure(monkeypatch):
    monkeypatch.setattr(auth, "get_admin_permission_requirement", lambda *_: None)
    monkeypatch.setitem(main.app.config, "IS_PRODUCTION", False)
    monkeypatch.setitem(main.app.config, "APP_ENV", "development")
    with main.app.test_request_context("/admin/dashboard"):
        _set_admin_session()
        with pytest.raises(auth.AdminAuthorizationConfigurationError):
            authz_gate.enforce_admin_access_control()


def test_production_shadow_audits_once_without_denying_or_loading_context(monkeypatch):
    events = []
    monkeypatch.setattr(auth, "get_admin_permission_requirement", lambda *_: None)
    monkeypatch.setattr(authz_gate, "_get_current_admin_access_context", lambda **_: pytest.fail("context loaded"))
    monkeypatch.setattr(authz_gate.logger, "error", lambda message, *args: events.append((message, args)))
    monkeypatch.setitem(main.app.config, "IS_PRODUCTION", True)
    with main.app.test_request_context("/admin/dashboard?token=must-not-log"):
        _set_admin_session("consultivo")
        assert authz_gate.enforce_admin_access_control() is None
    assert len(events) == 1
    message, fields = events[0]
    assert message.startswith("event=admin_rbac_missing_configuration")
    assert fields == ("admin_dashboard", "GET", "/admin/dashboard", "consultivo")
    serialized = repr((message, fields))
    for forbidden in ("token=", "must-not-log", "cookie", "session", "password", "body"):
        assert forbidden not in serialized.lower()


def test_production_shadow_logger_failure_does_not_block_request_or_load_context(monkeypatch):
    endpoint = "admin_shadow_audit_logger_failure_regression"
    path = "/admin/shadow-audit-logger-failure-regression"
    rule = Rule(path, endpoint=endpoint, methods={"GET"})
    logger_attempts = []

    def failing_logger(*_args, **_kwargs):
        logger_attempts.append(True)
        raise RuntimeError("test logger backend unavailable")

    def unexpected_access(*_args, **_kwargs):
        pytest.fail("production shadow classification loaded access context or database state")

    monkeypatch.setattr(authz_gate.logger, "error", failing_logger)
    monkeypatch.setattr(authz_gate, "_get_current_admin_access_context", unexpected_access)
    # Still patched on ``main``: these guard the main-owned code that remains on
    # the executed request path, not the gate (see module docstring).
    monkeypatch.setattr(main, "get_db_connection", unexpected_access)
    monkeypatch.setattr(main, "ensure_usuario_access_schema", unexpected_access)
    # UT-5 RED retarget: sentinel on the future canonical owner (see module
    # docstring). Fails here with ModuleNotFoundError against current HEAD,
    # which is the expected RED reason (app.backup absent) -- not a stale,
    # silently-dead patch on a hook that no longer runs.
    from app.backup import orchestrator as backup_orchestrator

    monkeypatch.setattr(
        backup_orchestrator,
        "_maybe_sync_database_snapshot",
        lambda **_kwargs: pytest.fail(
            "ordinary request path invoked "
            "app.backup.orchestrator._maybe_sync_database_snapshot"
        ),
    )
    monkeypatch.setitem(main.app.config, "IS_PRODUCTION", True)
    monkeypatch.setitem(main.app.config, "APP_ENV", "production")
    monkeypatch.setitem(main.app.config, "TESTING", False)
    monkeypatch.setitem(main.app.config, "DEBUG", False)

    # Flask disallows add_url_rule after the first request, so this deliberately
    # registers a test-only rule at the URL-map layer and removes it afterwards.
    # It still traverses Flask's actual request routing and before_request hook.
    main.app.url_map.add(rule)
    main.app.view_functions[endpoint] = lambda: ("shadow request continued", 200)
    try:
        client = main.app.test_client()
        with client.session_transaction() as value:
            value.clear()
            value["user_id"] = 999999
            value["user_type"] = "admin"
            value["access_level"] = "admin_total"

        response = client.get(path)

        assert response.status_code == 200
        assert response.get_data(as_text=True) == "shadow request continued"
        assert logger_attempts == [True]
    finally:
        main.app.view_functions.pop(endpoint, None)
        main.app.url_map._rules.remove(rule)
        main.app.url_map._rules_by_endpoint.pop(endpoint, None)
        main.app.url_map.update()


def test_existing_mapped_browser_ajax_and_actor_contracts_are_preserved(env):
    client = env["client"]
    _login(client, "consultivo")
    browser = client.get("/admin/catalogo-versoes/nova-base")
    assert browser.status_code == 302
    assert browser.headers["Location"].endswith("/admin/dashboard")
    ajax = client.get("/admin/catalogo-versoes/nova-base", headers={"X-Requested-With": "XMLHttpRequest"})
    assert ajax.status_code == 403
    assert ajax.get_json()["error"] == "forbidden"

    _login(client, "admin_total")
    assert client.get("/admin/atividades").status_code == 200
    _login(client, "administrativo")
    assert client.get("/admin/atividades").status_code == 200


def test_anonymous_and_aluno_admin_authentication_contracts_are_preserved(env):
    client = env["client"]
    assert client.get("/admin/atividades").status_code == 302
    with client.session_transaction() as value:
        value.clear()
        value["user_id"] = 1
        value["user_type"] = "aluno"
    response = client.get("/admin/atividades")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_missing_configuration_classifier_does_not_open_or_mutate_database_state(monkeypatch):
    # The hook must stop before access-context loading; therefore it neither opens
    # a connection nor can commit/rollback a caller-owned transaction.
    monkeypatch.setattr(auth, "get_admin_permission_requirement", lambda *_: None)
    monkeypatch.setattr(authz_gate, "_get_current_admin_access_context", lambda **_: pytest.fail("context loaded"))
    monkeypatch.setitem(main.app.config, "IS_PRODUCTION", False)
    with main.app.test_request_context("/admin/dashboard"):
        _set_admin_session()
        with pytest.raises(auth.AdminAuthorizationConfigurationError):
            authz_gate.enforce_admin_access_control()
        from flask import g

        assert "db" not in g
