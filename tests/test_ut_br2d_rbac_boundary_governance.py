"""UT-BR2-D: adversarial probes for the RBAC boundary / actor-matrix guards.

``tests/canonical_rbac_test_support.py`` replaced seven frozen scalars
(``rules == 128``, ``combinations == 156``, ``governed == 130``,
``non_governed == 26``, ``actor_combinations == 390``, ``denials == 136``,
``dynamic == 53``) with exact identity reconstruction.  A consolidation is only
worth trusting if the replacement provably still fails, so every probe below
breaks one invariant and asserts the corresponding guard reports it.

The probe letters match the UT-BR2-D brief:

A. a governed ``/admin`` route with no policy
B. a duplicate / ambiguous policy for the same governed pair
C. an ``/admin`` route classified as non-governed
D. a denial silently turned into an allow
E. a governed pair dropped from actor-matrix generation
F. a route <-> endpoint identity mutation
G. a dynamic governed route omitted

Every probe mutates only test-side copies, monkeypatched dictionaries or
synthetic ``werkzeug`` rules.  No production file, route, policy or database is
touched, and each probe asserts the canonical (unmutated) derivation is still
clean so a probe can never leave global state behind.
"""
from __future__ import annotations

import copy
import os
import sys

import pytest
from werkzeug.routing import Rule


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app import auth
from tests import canonical_rbac_test_support as rbac
from tests.canonical_baseline_support import (
    assert_route_inventory_artifact_is_canonical,
    load_route_inventory_baseline,
)


PROBE_ADMIN_RULE = "/admin/ut-br2d-probe"
PROBE_ADMIN_ENDPOINT = "admin_ut_br2d_probe"


def _canonical_routes() -> list[dict]:
    return copy.deepcopy(load_route_inventory_baseline()["routes"])


def _live_rules() -> list:
    return list(main.app.url_map.iter_rules())


def _canonical() -> rbac.RbacClassification:
    return rbac.canonical_classification()


def _first_admin_requirement() -> rbac.Requirement:
    requirements = sorted(rbac.requirement_identities(_canonical()))
    for requirement in requirements:
        if rbac.is_admin_rule(requirement.rule):
            return requirement
    raise AssertionError("no governed admin requirement to probe")


# ---------------------------------------------------------------------------
# Baseline: the canonical derivation is clean before and after every probe
# ---------------------------------------------------------------------------

def test_canonical_derivation_reports_no_violations():
    classification = _canonical()
    assert classification.unresolved == ()
    assert classification.ambiguous == ()
    assert rbac.admin_boundary_violations(classification) == []
    assert rbac.policy_ownership_violations(classification) == []
    assert rbac.exemption_registry_violations() == []
    assert rbac.non_governed_category_violations(
        rbac.non_governed_identities(classification)
    ) == []


def test_admin_rule_predicate_mirrors_production():
    """The support module's copy of the boundary predicate must track production.

    ``is_admin_rule`` is deliberately a copy rather than an import; this is what
    stops the copy from silently following a widened production predicate.
    """
    for rule in main.app.url_map.iter_rules():
        for method in sorted(set(rule.methods or ()) & rbac.BUSINESS_METHODS):
            result = auth.classify_governed_admin_request(rule.endpoint, rule, method)
            external = method in auth.NON_ADMIN_RBAC_GOVERNED_ENDPOINTS.get(
                rule.endpoint, frozenset()
            )
            assert result["governed"] == (rbac.is_admin_rule(rule.rule) or external), (
                f"boundary predicate disagrees with production for "
                f"{rule.rule} {rule.endpoint} {method}"
            )


@pytest.mark.parametrize("rule_text,expected", [
    ("/admin", True),
    ("/admin/dashboard", True),
    ("/admin/a/b/c", True),
    # Prefix traps: a sibling path that merely starts with the same letters is
    # outside the boundary and must not be treated as an admin rule.
    ("/administrativo", False),
    ("/adminx", False),
    ("/aluno/admin", False),
    ("/", False),
    (None, False),
])
def test_admin_rule_predicate_rejects_prefix_traps(rule_text, expected):
    assert rbac.is_admin_rule(rule_text) is expected


# ---------------------------------------------------------------------------
# Probe A — governed /admin route with no policy
# ---------------------------------------------------------------------------

def test_probe_a_admin_route_without_policy_is_caught():
    rule = Rule(PROBE_ADMIN_RULE, endpoint=PROBE_ADMIN_ENDPOINT, methods={"GET"})
    assert auth.get_admin_permission_requirement(PROBE_ADMIN_ENDPOINT, "GET") is None

    routes = _canonical_routes() + [
        {"endpoint": PROBE_ADMIN_ENDPOINT, "methods": ["GET"], "rule": PROBE_ADMIN_RULE}
    ]
    classification = rbac.classify_inventory(routes=routes, rules=_live_rules() + [rule])

    assert any(
        "no applicable policy" in violation and PROBE_ADMIN_ENDPOINT in violation
        for violation in rbac.policy_ownership_violations(classification)
    )
    assert any(
        PROBE_ADMIN_ENDPOINT in violation
        for violation in rbac.admin_boundary_violations(classification)
    )
    # The classifier itself must call this governed-but-unconfigured, never
    # "outside the boundary".
    result = auth.classify_governed_admin_request(PROBE_ADMIN_ENDPOINT, rule, "GET")
    assert result["governed"] is True
    assert result["kind"] == "missing_configuration"


# ---------------------------------------------------------------------------
# Probe B — duplicate / ambiguous policy for the same governed pair
# ---------------------------------------------------------------------------

def test_probe_b_ambiguous_route_resolution_is_caught():
    """Two live rules sharing one (rule, endpoint) identity: which policy applies?"""
    target = _first_admin_requirement()
    rules = _live_rules()
    duplicate = next(
        rule for rule in rules
        if rule.rule == target.rule and rule.endpoint == target.endpoint
    )
    classification = rbac.classify_inventory(rules=rules + [duplicate])

    assert any("2 live rules share identity" in v for v in rbac.policy_ownership_violations(classification))
    assert any(
        "resolves to 2 live rules" in v for v in rbac.admin_boundary_violations(classification)
    )
    # The pair is no longer classified at all, so it silently leaves the
    # governed set -- the guard must not let that pass as "one less route".
    assert target.combination not in rbac.governed_identities(classification)


def test_probe_b_duplicate_requirement_and_exemption_is_caught(monkeypatch):
    """A governed pair holding both a requirement and an approved exemption."""
    target = _first_admin_requirement()
    monkeypatch.setitem(
        auth.APPROVED_ADMIN_RBAC_EXEMPTIONS,
        (target.endpoint, target.method),
        {"reason": "UT-BR2-D probe", "current_protection": "n/a", "test": __name__},
    )
    classification = rbac.classify_inventory()

    assert any(
        "both a requirement and an exemption" in v and target.endpoint in v
        for v in rbac.policy_ownership_violations(classification)
    )
    assert any(target.endpoint in v for v in rbac.admin_boundary_violations(classification))
    result = auth.classify_governed_admin_request(
        target.endpoint, _live_rule_for(target), target.method
    )
    assert result["kind"] == "invalid_configuration"


def test_probe_b_wildcard_exemption_is_rejected(monkeypatch):
    """An exemption may never be a wildcard that removes a family of admin routes."""
    monkeypatch.setitem(
        auth.APPROVED_ADMIN_RBAC_EXEMPTIONS, ("admin_*", "GET"), {"reason": "probe"}
    )
    assert any("wildcard" in v for v in rbac.exemption_registry_violations())


def _live_rule_for(requirement: rbac.Requirement):
    matches = [
        rule for rule in main.app.url_map.iter_rules()
        if rule.rule == requirement.rule and rule.endpoint == requirement.endpoint
    ]
    assert len(matches) == 1
    return matches[0]


# ---------------------------------------------------------------------------
# Probe C — /admin route classified as non-governed
# ---------------------------------------------------------------------------

def test_probe_c_admin_route_classified_non_governed_is_caught():
    target = _first_admin_requirement()

    def classify(endpoint, url_rule, method):
        result = auth.classify_governed_admin_request(endpoint, url_rule, method)
        if (url_rule.rule, endpoint, method) == target.combination:
            return {
                **result,
                "governed": False,
                "kind": "outside_boundary",
                "requirement": None,
                "exemption": None,
            }
        return result

    classification = rbac.classify_inventory(classify=classify)

    assert any(
        "outside the governed boundary" in v and target.endpoint in v
        for v in rbac.admin_boundary_violations(classification)
    )
    # The non-governed surface guard catches it independently: an admin identity
    # can never be claimed by a non-admin boundary category.
    assert any(
        "no boundary category" in v and target.endpoint in v
        for v in rbac.non_governed_category_violations(
            rbac.non_governed_identities(classification)
        )
    )
    assert (
        rbac.identities_digest(rbac.non_governed_identities(classification))
        != rbac.CANONICAL_NON_GOVERNED_IDENTITIES_SHA256
    )


def test_probe_c_admin_identity_declared_as_a_boundary_category_is_caught(monkeypatch):
    """A *declared* admin identity inside a non-governed category is a violation.

    This is the smuggling attack the category table exists to stop: somebody
    reclassifies a real ``/admin`` route as non-governed and then silences the
    catch-all guard by declaring that route inside an explicit category.  The
    undeclared path is already covered by
    ``test_probe_c_non_governed_surface_has_no_catch_all``; here the identity is
    fully declared *and* observed, so the only control that can still catch it
    is the structural rule that no boundary category may ever claim an
    ``/admin`` identity.

    The injection targets a test-side copy of the registry installed with
    ``monkeypatch``, which restores the canonical tuple on teardown.  No
    repository file, artifact or persistent global is mutated.
    """
    smuggled = _first_admin_requirement().combination
    assert rbac.is_admin_rule(smuggled.rule), smuggled
    assert smuggled in rbac.governed_identities(_canonical()), (
        "the probe must smuggle a genuinely governed /admin identity"
    )

    target_category = "aluno_self_service"
    canonical_registry = rbac.NON_GOVERNED_BOUNDARY_CATEGORIES
    assert any(category.name == target_category for category in canonical_registry)

    smuggled_registry = tuple(
        category._replace(identities=category.identities | {smuggled})
        if category.name == target_category
        else category
        for category in canonical_registry
    )
    assert smuggled_registry != canonical_registry
    monkeypatch.setattr(rbac, "NON_GOVERNED_BOUNDARY_CATEGORIES", smuggled_registry)

    # The identity is declared *and* observed, so neither the undeclared branch
    # nor the stale-declaration branch can fire.  Anything reported is therefore
    # attributable to the admin-in-category rule alone.
    identities = rbac.non_governed_identities(_canonical()) | {smuggled}
    violations = rbac.non_governed_category_violations(identities)

    expected = (
        f"category {target_category!r} declares an admin identity as non-governed"
    )
    assert any(expected in v and f"endpoint={smuggled.endpoint}" in v for v in violations), (
        f"admin identity smuggled into {target_category!r} was not reported: {violations}"
    )
    assert not any("no boundary category" in v for v in violations), (
        "the probe must fail because a category declares an admin identity, "
        f"not because an observed identity is undeclared: {violations}"
    )
    assert not any("no longer non-governed" in v for v in violations), violations
    assert len(violations) == 1, (
        f"expected exactly the admin-category violation, got: {violations}"
    )


def test_probe_c_non_governed_surface_has_no_catch_all():
    """A brand-new non-admin non-governed route must still fail until classified."""
    stranger = rbac.Combination("/ut-br2d-probe-public", "ut_br2d_probe_public", "GET")
    identities = rbac.non_governed_identities(_canonical()) | {stranger}
    assert any(
        "no boundary category" in v and "ut_br2d_probe_public" in v
        for v in rbac.non_governed_category_violations(identities)
    )


# ---------------------------------------------------------------------------
# Probe D — a denial silently turned into an allow
# ---------------------------------------------------------------------------

def test_probe_d_denial_flipped_to_allow_is_caught():
    requirements = rbac.requirement_identities(_canonical())
    actors = rbac.actor_identities(requirements)
    canonical_denials = rbac.denial_identities(actors)
    assert canonical_denials, "the denial matrix must not be empty"

    weakened = dict(auth.PROFILE_RESOURCE_SCOPES)
    weakened["consultivo"] = {resource: "full" for resource in auth.ACCESS_RESOURCE_ORDER}
    mutated = rbac.denial_identities(actors, profiles=weakened)

    assert mutated < canonical_denials, "granting consultivo full access must remove denials"
    assert any(actor.level == "consultivo" for actor in canonical_denials - mutated)
    assert (
        rbac.identities_digest(mutated) != rbac.CANONICAL_DENIAL_MATRIX_IDENTITIES_SHA256
    )
    assert (
        rbac.identities_digest(canonical_denials)
        == rbac.CANONICAL_DENIAL_MATRIX_IDENTITIES_SHA256
    )


def test_probe_d_fail_open_requirement_scope_is_caught():
    """A required scope that does not normalize degrades to "none" -- allowing everyone.

    ``permission_scope_satisfies`` normalizes an unknown required scope to
    ``none``, whose rank is 0, so *every* actor satisfies it.  No count-based
    check could ever see this; the zero-privilege probe in
    ``policy_ownership_violations`` does.
    """
    assert auth.permission_scope_satisfies("none", "delete") is True, (
        "precondition: an unrecognized required scope is satisfied by everyone"
    )
    rule = Rule(PROBE_ADMIN_RULE, endpoint=PROBE_ADMIN_ENDPOINT, methods={"GET"})

    def classify(endpoint, url_rule, method):
        if endpoint == PROBE_ADMIN_ENDPOINT:
            return {
                "endpoint": endpoint,
                "rule": url_rule.rule,
                "method": method,
                "governed": True,
                "kind": "requirement",
                "requirement": ("alunos", "delete"),
                "exemption": None,
            }
        return auth.classify_governed_admin_request(endpoint, url_rule, method)

    routes = _canonical_routes() + [
        {"endpoint": PROBE_ADMIN_ENDPOINT, "methods": ["GET"], "rule": PROBE_ADMIN_RULE}
    ]
    classification = rbac.classify_inventory(
        routes=routes, rules=_live_rules() + [rule], classify=classify
    )
    assert any(
        "fail-open policy" in v for v in rbac.policy_ownership_violations(classification)
    )


def test_probe_d_requirement_naming_an_unknown_resource_is_caught():
    rule = Rule(PROBE_ADMIN_RULE, endpoint=PROBE_ADMIN_ENDPOINT, methods={"GET"})

    def classify(endpoint, url_rule, method):
        if endpoint == PROBE_ADMIN_ENDPOINT:
            return {
                "endpoint": endpoint,
                "rule": url_rule.rule,
                "method": method,
                "governed": True,
                "kind": "requirement",
                "requirement": ("nao_existe", "full"),
                "exemption": None,
            }
        return auth.classify_governed_admin_request(endpoint, url_rule, method)

    routes = _canonical_routes() + [
        {"endpoint": PROBE_ADMIN_ENDPOINT, "methods": ["GET"], "rule": PROBE_ADMIN_RULE}
    ]
    classification = rbac.classify_inventory(
        routes=routes, rules=_live_rules() + [rule], classify=classify
    )
    assert any(
        "unknown resource" in v for v in rbac.policy_ownership_violations(classification)
    )


# ---------------------------------------------------------------------------
# Probe E — a governed pair dropped from actor-matrix generation
# ---------------------------------------------------------------------------

def test_probe_e_governed_pair_omitted_from_the_actor_matrix_is_caught():
    requirements = sorted(rbac.requirement_identities(_canonical()))
    dropped = requirements[0]
    truncated_actors = rbac.actor_identities(requirements[1:])

    violations = rbac.actor_matrix_violations(requirements, truncated_actors)
    assert violations
    assert all("missing from the matrix" in v for v in violations)
    assert any(dropped.endpoint in v for v in violations)
    assert len(violations) == len(rbac.ADMIN_ACCESS_LEVELS)


def test_probe_e_actor_outside_the_governed_set_is_caught():
    requirements = sorted(rbac.requirement_identities(_canonical()))
    smuggled = rbac.ActorCase(
        PROBE_ADMIN_RULE, PROBE_ADMIN_ENDPOINT, "GET", "alunos", "full", "consultivo"
    )
    actors = rbac.actor_identities(requirements) | {smuggled}
    assert any(
        "outside the governed set" in v
        for v in rbac.actor_matrix_violations(requirements, actors)
    )


def test_probe_e_dropping_an_access_level_is_caught():
    requirements = sorted(rbac.requirement_identities(_canonical()))
    partial = rbac.actor_identities(requirements, ("admin_total", "administrativo"))
    violations = rbac.actor_matrix_violations(requirements, partial)
    assert violations
    assert all("consultivo" in v for v in violations)


# ---------------------------------------------------------------------------
# Probe F — route <-> endpoint identity mutation
# ---------------------------------------------------------------------------

def test_probe_f_route_endpoint_identity_mutation_is_caught():
    routes = _canonical_routes()
    target = next(entry for entry in routes if rbac.is_admin_rule(entry["rule"]) and entry["methods"])
    original_endpoint = target["endpoint"]
    target["endpoint"] = f"{original_endpoint}_ut_br2d_probe"

    classification = rbac.classify_inventory(routes=routes)
    assert classification.unresolved
    assert any(
        "no live rule for inventory identity" in v
        for v in rbac.policy_ownership_violations(classification)
    )
    assert any(
        "not resolvable in the live URL map" in v
        for v in rbac.admin_boundary_violations(classification)
    )


def test_probe_f_artifact_mutation_is_caught_by_the_canonical_anchor():
    """The RBAC derivation is anchored to the pinned artifact, not to raw JSON."""
    baseline = load_route_inventory_baseline()
    mutated = {**baseline, "routes": _canonical_routes()}
    mutated["routes"][0] = {**mutated["routes"][0], "endpoint": "ut_br2d_probe_renamed"}
    with pytest.raises(AssertionError) as exc:
        assert_route_inventory_artifact_is_canonical(mutated, context="UT-BR2-D probe F")
    assert "diverged from the canonical URL contract" in str(exc.value)


def test_probe_f_method_mutation_is_caught():
    routes = _canonical_routes()
    target = next(
        entry for entry in routes
        if rbac.is_admin_rule(entry["rule"]) and entry["methods"] == ["GET"]
    )
    target["methods"] = ["DELETE"]

    classification = rbac.classify_inventory(routes=routes)
    requirements = rbac.requirement_identities(classification)
    assert (
        rbac.requirement_matrix_digest(requirements)
        != rbac.CANONICAL_REQUIREMENT_MATRIX_DIGEST
    )


# ---------------------------------------------------------------------------
# Probe G — a dynamic governed route omitted
# ---------------------------------------------------------------------------

def test_probe_g_omitted_dynamic_governed_route_is_caught():
    requirements = rbac.requirement_identities(_canonical())
    dynamic = rbac.dynamic_requirement_identities(requirements)
    static = rbac.static_requirement_identities(requirements)
    assert dynamic

    dropped = sorted(dynamic)[0]
    omitted = dynamic - {dropped}

    violations = rbac.dynamic_partition_violations(requirements, omitted, static)
    assert any("in neither partition" in v and dropped.endpoint in v for v in violations)
    assert (
        rbac.identities_digest(omitted)
        != rbac.CANONICAL_DYNAMIC_REQUIREMENT_IDENTITIES_SHA256
    )
    assert (
        rbac.identities_digest(dynamic)
        == rbac.CANONICAL_DYNAMIC_REQUIREMENT_IDENTITIES_SHA256
    )


def test_probe_g_dynamic_route_reclassified_as_static_is_caught():
    requirements = rbac.requirement_identities(_canonical())
    dynamic = rbac.dynamic_requirement_identities(requirements)
    static = rbac.static_requirement_identities(requirements)
    moved = sorted(dynamic)[0]

    violations = rbac.dynamic_partition_violations(
        requirements, dynamic - {moved}, static | {moved}
    )
    assert any("static partition holds a dynamic rule" in v for v in violations)


def test_probe_g_partition_overlap_is_caught():
    requirements = rbac.requirement_identities(_canonical())
    dynamic = rbac.dynamic_requirement_identities(requirements)
    static = rbac.static_requirement_identities(requirements)
    overlap = sorted(dynamic)[0]

    violations = rbac.dynamic_partition_violations(requirements, dynamic, static | {overlap})
    assert any("both dynamic and static" in v for v in violations)


# ---------------------------------------------------------------------------
# Closeout: no probe leaked into the canonical derivation
# ---------------------------------------------------------------------------

def test_canonical_derivation_is_unchanged_after_the_probes():
    classification = rbac.classify_inventory()
    requirements = rbac.requirement_identities(classification)
    assert rbac.admin_boundary_violations(classification) == []
    assert rbac.policy_ownership_violations(classification) == []
    assert rbac.exemption_registry_violations() == []
    assert auth.APPROVED_ADMIN_RBAC_EXEMPTIONS == {}
    assert (
        rbac.requirement_matrix_digest(requirements)
        == rbac.CANONICAL_REQUIREMENT_MATRIX_DIGEST
    )
    assert (
        rbac.identities_digest(rbac.non_governed_identities(classification))
        == rbac.CANONICAL_NON_GOVERNED_IDENTITIES_SHA256
    )
    assert (
        rbac.identities_digest(
            rbac.denial_identities(rbac.actor_identities(requirements))
        )
        == rbac.CANONICAL_DENIAL_MATRIX_IDENTITIES_SHA256
    )
