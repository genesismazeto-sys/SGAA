"""UT-SEC1: an invalid *required* permission scope must fail closed.

Before this UT, ``permission_scope_satisfies`` normalized **both** sides of the
comparison through ``normalize_permission_scope``, whose contract is to answer
"unrecognized" with a caller-chosen fallback (``"none"`` by default).  An
unrecognized *requirement* -- ``"typo_scope"``, a renamed scope, a blank config
value -- therefore became the zero-rank ``none`` scope, and
``ACCESS_SCOPE_RANK[current] >= ACCESS_SCOPE_RANK["none"]`` holds for every
actor.  A misconfigured policy granted universal access instead of denying.

The canonical route policies in ``get_admin_permission_requirement`` are all
hard-coded ``view``/``edit``/``full`` literals, so the defect was latent rather
than exploited.  The primitive itself was fail-open, which is what this suite
pins shut.

Probe letters match the UT-SEC1 brief:

A. an unknown required scope denies ``admin_total``
B. an unknown required scope denies ``administrativo``
C. an unknown required scope denies ``consultivo``
D. an unknown *current* (actor) scope gains nothing
E. valid required scopes retain the ``none < view < edit < full`` hierarchy
F. malformed / blank / absent required scopes are explicitly pinned
G. the real authorization path denies an invalid requirement end to end

Probe G is the reason this file is not a pure unit suite: asserting that a
helper returns ``False`` does not prove the request path honors it.  G drives
``enforce_admin_access_control`` over a real request with a real admin session
and proves the protected handler never runs.

Every database-backed proof uses the fixture-controlled isolated environment;
the operational ``database.db`` is never opened.
"""
from __future__ import annotations

import logging
import os
import sys
import uuid

import pytest


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app import admin_access, auth
from app.web import authz_gate
from tests.versioned_test_support import isolated_versioned_app_env
from tests.session_support import stamp_auth_version


ADMIN_LEVELS = ("admin_total", "administrativo", "consultivo")

# Values that must never resolve to an authorization requirement.
INVALID_REQUIRED_SCOPES = (
    "typo_scope",
    "delete",
    "readonly",
    "admin",
    "vieww",
    "ful",
    "escrita",
    "*",
    "none ou view",
)

# Absent / malformed requirements.  ``normalize_permission_scope`` maps all of
# these to its fallback, which is exactly the confusion UT-SEC1 removes from the
# required-scope side.
BLANK_REQUIRED_SCOPES = (None, "", " ", "   ", "\t", "\n", "\t \n ", 0, False, [], {})

# Aliases production intentionally accepts, and the canonical scope each one
# resolves to.  These keep their pre-UT-SEC1 meaning.
CANONICAL_SCOPE_ALIASES = (
    ("none", "none"),
    ("nenhum", "none"),
    ("sem acesso", "none"),
    ("view", "view"),
    ("visualizar", "view"),
    ("leitura", "view"),
    ("consulta", "view"),
    ("consultivo", "view"),
    ("edit", "edit"),
    ("edicao", "edit"),
    ("Edição", "edit"),
    ("editar", "edit"),
    ("full", "full"),
    ("total", "full"),
    ("acesso total", "full"),
    ("completo", "full"),
)


def _context(level: str) -> dict[str, object]:
    """A synthetic, database-free admin access context for ``level``."""
    return {
        "is_admin": True,
        "access_level": level,
        "effective_scopes": auth.merge_resource_scopes(level, {}),
    }


def _make_admin(access_level: str) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        user_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) "
            "VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                f"SEC1 {access_level}",
                f"sec1.{access_level}.{uuid.uuid4().hex[:10]}@example.com",
                main.hash_password("sec1-test-pass"),
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
        value["user_name"] = f"SEC1 {access_level}"
        value["access_level"] = access_level
        stamp_auth_version(value)


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ut_sec1_required_scope.db") as value:
        yield value


# ---------------------------------------------------------------------------
# Probes A / B / C -- an unknown requirement denies every admin level
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level", ADMIN_LEVELS)
@pytest.mark.parametrize("invalid", INVALID_REQUIRED_SCOPES)
def test_unknown_required_scope_denies_every_admin_level(level, invalid):
    for resource in auth.ACCESS_RESOURCE_ORDER:
        current = auth.PROFILE_RESOURCE_SCOPES[level].get(resource, "none")
        assert auth.permission_scope_satisfies(current, invalid) is False, (
            f"{level} holding {current!r} on {resource!r} satisfied invalid "
            f"requirement {invalid!r}"
        )


@pytest.mark.parametrize("level", ADMIN_LEVELS)
@pytest.mark.parametrize("invalid", INVALID_REQUIRED_SCOPES)
def test_unknown_required_scope_denies_admin_can_for_every_level(level, invalid):
    """The same denial one layer up, through the real ``_admin_can`` gate."""
    context = _context(level)
    for resource in auth.ACCESS_RESOURCE_ORDER:
        assert admin_access._admin_can(resource, invalid, context) is False, (
            f"_admin_can({resource!r}, {invalid!r}) granted access to {level}"
        )


def test_admin_total_holds_full_everywhere_so_the_denial_is_the_scope_not_the_actor():
    """Discriminating control: admin_total is allowed under a valid requirement."""
    context = _context("admin_total")
    for resource in auth.ACCESS_RESOURCE_ORDER:
        assert auth.PROFILE_RESOURCE_SCOPES["admin_total"][resource] == "full"
        assert admin_access._admin_can(resource, "full", context) is True
        assert admin_access._admin_can(resource, "typo_scope", context) is False


# ---------------------------------------------------------------------------
# Probe D -- an unknown *current* scope gains nothing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "unknown_current", ["typo_scope", "superuser", "root", "delete", None, "", "   "]
)
@pytest.mark.parametrize("required", ["view", "edit", "full"])
def test_unknown_current_scope_never_gains_access(unknown_current, required):
    assert auth.permission_scope_satisfies(unknown_current, required) is False


def test_unknown_current_scope_still_normalizes_to_none():
    """Actor-side normalization is deliberately unchanged: unknown means nothing."""
    assert auth.normalize_permission_scope("typo_scope") == "none"
    assert auth.normalize_permission_scope(None) == "none"
    # ...and "none" is exactly what the zero-privilege actor holds.
    assert auth.permission_scope_satisfies("typo_scope", "none") is True
    assert auth.permission_scope_satisfies("none", "none") is True


@pytest.mark.parametrize("unknown_current", ["typo_scope", None, ""])
@pytest.mark.parametrize("invalid_required", ["typo_scope", None, ""])
def test_unknown_on_both_sides_is_still_denied(unknown_current, invalid_required):
    """An unknown actor scope must not "cancel out" an unknown requirement."""
    assert auth.permission_scope_satisfies(unknown_current, invalid_required) is False


# ---------------------------------------------------------------------------
# Probe E -- the valid hierarchy is unchanged
# ---------------------------------------------------------------------------

REGRESSION_MATRIX = (
    ("none", "view", False),
    ("none", "edit", False),
    ("none", "full", False),
    ("view", "view", True),
    ("view", "edit", False),
    ("view", "full", False),
    ("edit", "view", True),
    ("edit", "edit", True),
    ("edit", "full", False),
    ("full", "view", True),
    ("full", "edit", True),
    ("full", "full", True),
)


@pytest.mark.parametrize("current,required,expected", REGRESSION_MATRIX)
def test_valid_scope_hierarchy_is_unchanged(current, required, expected):
    assert auth.permission_scope_satisfies(current, required) is expected


def test_canonical_hierarchy_ranks_are_unchanged():
    assert auth.ACCESS_SCOPES == ("none", "view", "edit", "full")
    assert auth.ACCESS_SCOPE_RANK == {"none": 0, "view": 1, "edit": 2, "full": 3}


@pytest.mark.parametrize("alias,canonical", CANONICAL_SCOPE_ALIASES)
def test_supported_aliases_keep_their_meaning_on_both_sides(alias, canonical):
    assert auth.normalize_permission_scope(alias) == canonical
    assert auth.normalize_required_permission_scope(alias) == canonical
    assert auth.is_valid_permission_scope(alias) is True
    for current, required, expected in REGRESSION_MATRIX:
        if required != canonical:
            continue
        assert auth.permission_scope_satisfies(current, alias) is expected


def test_surrounding_whitespace_and_case_on_a_valid_requirement_still_resolve():
    for variant in ("  edit  ", "EDIT", "Edit", "edicao", "EDIÇÃO", "Edição"):
        assert auth.permission_scope_satisfies("edit", variant) is True
        assert auth.permission_scope_satisfies("view", variant) is False


# ---------------------------------------------------------------------------
# Probe F -- blank / absent / malformed requirements are pinned
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("blank", BLANK_REQUIRED_SCOPES)
@pytest.mark.parametrize("current", ["none", "view", "edit", "full"])
def test_blank_required_scope_fails_closed(blank, current):
    """Pinned decision: an *absent* requirement is a defect, not a free pass.

    No production caller passes an empty requirement -- every required scope
    reaching ``permission_scope_satisfies`` is a hard-coded ``view``/``edit``/
    ``full`` literal -- so nothing depends on the old permissive behavior.
    """
    assert auth.permission_scope_satisfies(current, blank) is False
    assert auth.is_valid_permission_scope(blank) is False
    assert auth.normalize_required_permission_scope(blank) is None


@pytest.mark.parametrize("invalid", INVALID_REQUIRED_SCOPES)
def test_strict_parser_reports_none_for_invalid_requirements(invalid):
    assert auth.normalize_required_permission_scope(invalid) is None
    assert auth.is_valid_permission_scope(invalid) is False


def test_permissive_normalizer_contract_is_untouched():
    """``normalize_permission_scope`` keeps its fallback contract for its own callers.

    UT-SEC1 separated the trust boundary instead of making the shared helper
    raise: it also serves display labels, persisted overrides and form input,
    where a fallback is the correct answer.
    """
    assert auth.normalize_permission_scope("typo_scope") == "none"
    assert auth.normalize_permission_scope("typo_scope", "view") == "view"
    assert auth.normalize_permission_scope("", "edit") == "edit"
    assert auth.normalize_permission_scope(None, "full") == "full"
    assert auth.permission_scope_label("typo_scope") == "Sem acesso"
    # Persisted-override normalization keeps falling back to the default scope.
    merged = auth.merge_resource_scopes("consultivo", {"alunos": "typo_scope"})
    assert merged["alunos"] == "view"


def test_invalid_required_scope_is_logged_for_operational_visibility(caplog):
    with caplog.at_level(logging.WARNING, logger="app.auth"):
        assert auth.permission_scope_satisfies("full", "typo_scope") is False
    assert any(
        "authz_invalid_required_scope" in record.getMessage()
        for record in caplog.records
    ), "an invalid required scope must leave operational evidence"


def test_valid_required_scope_logs_nothing(caplog):
    with caplog.at_level(logging.WARNING, logger="app.auth"):
        assert auth.permission_scope_satisfies("full", "edit") is True
    assert not [
        record
        for record in caplog.records
        if "authz_invalid_required_scope" in record.getMessage()
    ]


def test_denial_is_returned_not_raised():
    """Pinned error behavior: deny cleanly, do not raise.

    ``_admin_can`` is also called from template context processors
    (``app.web.context.inject_admin_access_helpers``), where an exception would
    turn a safe 403 into an uncontrolled 500 during rendering.  The canonical
    controlled error ``AdminAuthorizationConfigurationError`` stays reserved for
    the *classifier* contract it already owns in ``app.web.authz_gate``.
    """
    assert auth.permission_scope_satisfies("full", "typo_scope") is False
    assert admin_access._admin_can("alunos", "typo_scope", _context("admin_total")) is False


# ---------------------------------------------------------------------------
# The canonical production policy set contains no invalid requirement
# ---------------------------------------------------------------------------

def test_every_canonical_route_requirement_uses_a_valid_scope():
    checked = 0
    for rule in main.app.url_map.iter_rules():
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            if method not in (rule.methods or set()):
                continue
            requirement = auth.get_admin_permission_requirement(rule.endpoint, method)
            if requirement is None:
                continue
            resource, scope = requirement
            checked += 1
            assert auth.is_valid_permission_scope(scope), (
                f"{rule.endpoint} {method} declares invalid required scope {scope!r}"
            )
            assert scope in {"view", "edit", "full"}, (
                f"{rule.endpoint} {method} declares required scope {scope!r}; "
                "an explicit 'none' requirement would deny nobody"
            )
            assert resource in auth.ACCESS_RESOURCES_META
    assert checked > 0, "the canonical policy set must not be empty"


# ---------------------------------------------------------------------------
# Probe G -- the real authorization path fails closed
# ---------------------------------------------------------------------------

def _invalid_requirement_classifier(endpoint_to_break: str, invalid_scope: str):
    real_classify = auth.classify_governed_admin_request

    def classify(endpoint, url_rule, method):
        result = real_classify(endpoint, url_rule, method)
        if endpoint == endpoint_to_break and result.get("kind") == "requirement":
            resource = result["requirement"][0]
            return {**result, "requirement": (resource, invalid_scope)}
        return result

    return classify


def test_invalid_requirement_fails_closed_on_the_real_authorization_path(env, monkeypatch):
    """Drive ``enforce_admin_access_control`` with an invalid governed requirement.

    The requirement is injected test-side into the classifier the gate actually
    calls; ``get_admin_permission_requirement`` and every production mapping are
    left untouched.  ``admin_total`` holds ``full`` on ``alunos``, so an allow
    here could only come from the requirement side.
    """
    client = env["client"]
    _login(client, "admin_total")

    executed: list[str] = []
    real_view = main.app.view_functions["admin_alunos"]

    def recording_view(*args, **kwargs):
        executed.append("admin_alunos")
        return real_view(*args, **kwargs)

    monkeypatch.setitem(main.app.view_functions, "admin_alunos", recording_view)

    # Control: with the canonical ("alunos", "view") requirement the same actor,
    # the same route and the same recorder produce an allow and run the handler.
    allowed = client.get("/admin/alunos")
    assert allowed.status_code == 200
    assert executed == ["admin_alunos"], "the recorder must observe a genuine allow"

    executed.clear()
    monkeypatch.setattr(
        authz_gate,
        "classify_governed_admin_request",
        _invalid_requirement_classifier("admin_alunos", "typo_scope"),
    )

    browser = client.get("/admin/alunos")
    assert browser.status_code == 302, "an invalid requirement must not authorize a browser request"
    assert browser.headers["Location"].endswith("/admin/dashboard")
    assert executed == [], "the protected handler executed under an invalid requirement"

    ajax = client.get("/admin/alunos", headers={"X-Requested-With": "XMLHttpRequest"})
    assert ajax.status_code == 403
    assert ajax.get_json()["error"] == "forbidden"
    assert executed == [], "the protected handler executed under an invalid requirement"


@pytest.mark.parametrize("level", ADMIN_LEVELS)
def test_invalid_requirement_denies_every_level_over_http(env, monkeypatch, level):
    client = env["client"]
    monkeypatch.setattr(
        authz_gate,
        "classify_governed_admin_request",
        _invalid_requirement_classifier("admin_alunos", "typo_scope"),
    )
    _login(client, level)
    response = client.get("/admin/alunos", headers={"X-Requested-With": "XMLHttpRequest"})
    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_requirement_fails_closed_over_http(env, monkeypatch, blank):
    client = env["client"]
    monkeypatch.setattr(
        authz_gate,
        "classify_governed_admin_request",
        _invalid_requirement_classifier("admin_alunos", blank),
    )
    _login(client, "admin_total")
    response = client.get("/admin/alunos", headers={"X-Requested-With": "XMLHttpRequest"})
    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"


def test_the_gate_is_unpatched_afterwards(env):
    """The monkeypatched classifier must not leak into neighbouring tests."""
    assert (
        authz_gate.classify_governed_admin_request
        is auth.classify_governed_admin_request
    )
    client = env["client"]
    _login(client, "admin_total")
    assert client.get("/admin/alunos").status_code == 200
