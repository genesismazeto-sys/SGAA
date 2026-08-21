"""Route/action-level CSRF inventory for every surviving mutating surface."""
from __future__ import annotations

import inspect
import re

import main
from tests.versioned_test_support import isolated_versioned_app_env


MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
INTENTIONAL_EXEMPTIONS = {
    ("/login", "login"): "public first-login flow without an established session",
}


def _mutating_rules(app):
    rows = [
        (rule, sorted(set(rule.methods or ()) & MUTATING_METHODS))
        for rule in app.url_map.iter_rules()
        if set(rule.methods or ()) & MUTATING_METHODS
    ]
    return sorted(rows, key=lambda item: (item[0].rule, item[0].endpoint))


def _view_identity(view) -> str:
    target = inspect.unwrap(view)
    return f"{target.__module__}.{target.__name__}"


def _materialize(rule: str) -> str:
    def replacement(match):
        converter, _, _name = match.group(1).partition(":")
        return "1" if converter in {"int", "float"} else "google"

    return re.sub(r"<([^>]+)>", replacement, rule)


def test_every_surviving_mutating_route_has_an_explicit_csrf_classification():
    csrf = main.app.extensions["csrf"]
    exempt_views = set(csrf._exempt_views)
    classification = {}
    for rule, methods in _mutating_rules(main.app):
        assert rule.endpoint in main.app.view_functions
        identity = _view_identity(main.app.view_functions[rule.endpoint])
        declared_exemption = INTENTIONAL_EXEMPTIONS.get((rule.rule, rule.endpoint))
        if declared_exemption:
            assert identity in exempt_views
            classification[(rule.rule, tuple(methods))] = "intentional_public_exemption"
        else:
            assert identity not in exempt_views
            classification[(rule.rule, tuple(methods))] = "csrf_protected"

    assert classification
    assert set(classification.values()) == {
        "csrf_protected",
        "intentional_public_exemption",
    }
    assert exempt_views == {"app.views.core.login"}
    assert not any("shadow" in route or "legacy" in route for route, _ in classification)


def test_every_protected_mutating_action_rejects_a_missing_token(tmp_path):
    with isolated_versioned_app_env(tmp_path, "csrf-complete-inventory.db") as env:
        previous = {
            "WTF_CSRF_ENABLED": main.app.config.get("WTF_CSRF_ENABLED"),
            "WTF_CSRF_CHECK_DEFAULT": main.app.config.get("WTF_CSRF_CHECK_DEFAULT"),
        }
        main.app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_CHECK_DEFAULT=True)
        try:
            results = {}
            for rule, methods in _mutating_rules(main.app):
                path = _materialize(rule.rule)
                for method in methods:
                    response = env["client"].open(path, method=method)
                    results[(rule.rule, rule.endpoint, method)] = response.status_code
                    if (rule.rule, rule.endpoint) in INTENTIONAL_EXEMPTIONS:
                        assert response.status_code != 400
                    else:
                        assert response.status_code == 400, (
                            rule.rule,
                            rule.endpoint,
                            method,
                            response.status_code,
                        )
            assert len(results) == sum(
                len(methods) for _, methods in _mutating_rules(main.app)
            )
        finally:
            main.app.config.update(previous)
