"""UT-BR2-D: the canonical owner for RBAC governed-boundary and actor-matrix truth.

``tests/canonical_baseline_support.py`` (UT-BR2-ABC) owns three *global*
baselines: the message catalog, the Flask URL contract and the CSRF inventory.
This module deliberately does **not** extend it.  Authorization ownership is
security-sensitive and stays visible in a file whose name says so; the only
thing borrowed from the UT-BR2-ABC owner is the URL contract itself
(``assert_route_inventory_artifact_is_canonical``), so there is exactly one
definition of "which routes exist" and this module never becomes a second
route inventory.

Everything here is a *projection* of two anchors that are already pinned:

1. the canonical route artifact (rule / endpoint / methods identities), and
2. the production classifier ``app.auth.classify_governed_admin_request``
   together with ``app.auth.PROFILE_RESOURCE_SCOPES``.

The historical suites froze a scalar per projection -- ``rules == 128``,
``combinations == 156``, ``governed == 130``, ``non_governed == 26``,
``actor_combinations == 390``, ``denials == 136``, ``dynamic == 53``.  Those
copies rotted into three mutually inconsistent eras while the real contract
moved to 125 entries / 153 combinations / 126 governed / 27 non-governed.
Worse, a bare count is a *weaker* control than the thing it stands in for: it
cannot tell "one admin route lost its policy and one non-admin route gained
one" from "nothing changed".

So no security guard below is a count.  Every guard is either

* exact set reconstruction (``*_violations`` helpers return the offending
  identities, and the caller asserts the list is empty), or
* exact identity-set equality against a declared, reviewable membership.

Derived counts are exposed through :func:`diagnostics` for failure messages
and human review only; nothing asserts against them.

``tests/test_ut_br2d_rbac_boundary_governance.py`` carries the mutation probes
that prove each guard actually fails when its invariant is broken.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import NamedTuple

from tests.canonical_baseline_support import (
    BUSINESS_METHODS,
    assert_route_inventory_artifact_is_canonical,
    load_route_inventory_baseline,
)


__all__ = [
    "ADMIN_ACCESS_LEVELS",
    "BUSINESS_METHODS",
    "ActorCase",
    "Combination",
    "NON_GOVERNED_BOUNDARY_CATEGORIES",
    "NonGovernedCategory",
    "RbacClassification",
    "Requirement",
    "actor_identities",
    "actor_matrix_violations",
    "admin_boundary_violations",
    "canonical_classification",
    "canonical_decision",
    "canonical_denial_cases",
    "denial_identities",
    "diagnostics",
    "dynamic_partition_violations",
    "dynamic_requirement_identities",
    "is_admin_rule",
    "load_route_inventory_baseline",
    "non_governed_category_violations",
    "policy_ownership_violations",
    "requirement_identities",
    "requirement_matrix_digest",
]


ADMIN_ACCESS_LEVELS: tuple[str, ...] = ("admin_total", "administrativo", "consultivo")

# A werkzeug rule is dynamic exactly when it carries a ``<converter:arg>``
# placeholder.  Kept here so the actor matrix and the URL-roundtrip proof share
# one definition of "dynamic".
DYNAMIC_SEGMENT_RE = re.compile(r"<[^>]+>")

# The scope an actor holds when it has been granted nothing at all.  Used to
# prove a declared requirement can actually deny (see
# :func:`policy_ownership_violations`).
ZERO_PRIVILEGE_SCOPE = "none"


def _digest(lines) -> str:
    """Stable digest of an unordered identity collection."""
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def is_admin_rule(rule_text) -> bool:
    """Mirror of the admin-boundary predicate inside ``classify_governed_admin_request``.

    Deliberately a *copy* rather than an import: if production ever widens or
    narrows its own predicate, ``test_admin_rule_predicate_mirrors_production``
    fails instead of this module silently following the change it is supposed
    to police.
    """
    text = "" if rule_text is None else str(rule_text)
    return text == "/admin" or text.startswith("/admin/")


# ---------------------------------------------------------------------------
# Identity shapes
# ---------------------------------------------------------------------------
# All three are plain tuple subclasses, so they hash, sort and compare equal to
# the bare tuples the historical suites already used.


class Combination(NamedTuple):
    rule: str
    endpoint: str
    method: str


class Requirement(NamedTuple):
    rule: str
    endpoint: str
    method: str
    resource: str
    scope: str

    @property
    def combination(self) -> Combination:
        return Combination(self.rule, self.endpoint, self.method)


class ActorCase(NamedTuple):
    rule: str
    endpoint: str
    method: str
    resource: str
    scope: str
    level: str

    @property
    def requirement(self) -> Requirement:
        return Requirement(self.rule, self.endpoint, self.method, self.resource, self.scope)


class RbacClassification(NamedTuple):
    """Every business combination of the inventory, partitioned by the classifier."""

    combinations: tuple[Combination, ...]
    governed: tuple[tuple[Combination, dict], ...]
    non_governed: tuple[tuple[Combination, dict], ...]
    #: identity present in the inventory but absent from the live URL map
    unresolved: tuple[Combination, ...]
    #: identity resolving to more than one live Rule object
    ambiguous: tuple[tuple[Combination, int], ...]


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

def classify_inventory(routes=None, *, rules=None, app=None, classify=None) -> RbacClassification:
    """Classify every ``(rule, endpoint, method)`` business combination.

    ``routes`` defaults to the canonical route artifact *after* it has been
    verified against its pinned digest, so the RBAC projections below can never
    silently follow an unreviewed edit of the JSON.

    ``rules`` / ``app`` / ``classify`` exist so the mutation probes can hand in
    test-side doubles.  No probe needs to touch a production file.
    """
    if routes is None:
        routes = assert_route_inventory_artifact_is_canonical(
            context="canonical_rbac_test_support.classify_inventory"
        )["routes"]
    if rules is None:
        if app is None:
            import main

            app = main.app
        rules = app.url_map.iter_rules()
    if classify is None:
        from app import auth

        classify = auth.classify_governed_admin_request

    index: dict[tuple[str, str], list] = {}
    for rule in rules:
        index.setdefault((rule.rule, rule.endpoint), []).append(rule)

    combinations: list[Combination] = []
    governed: list[tuple[Combination, dict]] = []
    non_governed: list[tuple[Combination, dict]] = []
    unresolved: list[Combination] = []
    ambiguous: list[tuple[Combination, int]] = []

    for entry in routes:
        matches = index.get((entry["rule"], entry["endpoint"]), [])
        for method in entry["methods"]:
            combination = Combination(entry["rule"], entry["endpoint"], method)
            combinations.append(combination)
            if len(matches) == 0:
                unresolved.append(combination)
                continue
            if len(matches) > 1:
                ambiguous.append((combination, len(matches)))
                continue
            result = classify(entry["endpoint"], matches[0], method)
            if result["governed"]:
                governed.append((combination, result))
            else:
                non_governed.append((combination, result))

    return RbacClassification(
        combinations=tuple(combinations),
        governed=tuple(governed),
        non_governed=tuple(non_governed),
        unresolved=tuple(unresolved),
        ambiguous=tuple(ambiguous),
    )


def combination_identities(classification: RbacClassification) -> frozenset[Combination]:
    return frozenset(classification.combinations)


def governed_identities(classification: RbacClassification) -> frozenset[Combination]:
    return frozenset(combination for combination, _ in classification.governed)


def non_governed_identities(classification: RbacClassification) -> frozenset[Combination]:
    return frozenset(combination for combination, _ in classification.non_governed)


def requirement_identities(classification: RbacClassification) -> frozenset[Requirement]:
    """The governed pairs that carry an applicable permission requirement."""
    found = set()
    for combination, result in classification.governed:
        if result.get("kind") != "requirement" or not result.get("requirement"):
            continue
        resource, scope = result["requirement"]
        found.add(Requirement(*combination, resource, scope))
    return frozenset(found)


def canonical_requirements_in_order(classification: RbacClassification) -> tuple[Requirement, ...]:
    """Deterministic ordering for test iteration that must be reproducible."""
    return tuple(sorted(requirement_identities(classification)))


# ---------------------------------------------------------------------------
# Guard 1 -- admin fail-closed boundary
# ---------------------------------------------------------------------------

def admin_boundary_violations(classification: RbacClassification, *, exemptions=None) -> list[str]:
    """Every ``/admin`` business combination must sit inside the governed boundary.

    This is the invariant the stale ``non_governed == 26`` scalar was standing
    in for, and it is strictly stronger: bumping the number to 27 would have
    accepted "one aluno route left the non-governed set, one admin route
    joined it".  Here an admin identity in the non-governed partition is a
    violation regardless of how many identities are in it.
    """
    if exemptions is None:
        from app import auth

        exemptions = auth.APPROVED_ADMIN_RBAC_EXEMPTIONS

    violations: list[str] = []
    for combination in classification.unresolved:
        if is_admin_rule(combination.rule):
            violations.append(
                f"admin combination not resolvable in the live URL map: {_fmt(combination)}"
            )
    for combination, count in classification.ambiguous:
        if is_admin_rule(combination.rule):
            violations.append(
                f"admin combination resolves to {count} live rules: {_fmt(combination)}"
            )
    for combination, _result in classification.non_governed:
        if is_admin_rule(combination.rule):
            violations.append(
                f"admin combination classified outside the governed boundary: {_fmt(combination)}"
            )
    for combination, result in classification.governed:
        if not is_admin_rule(combination.rule):
            continue
        kind = result.get("kind")
        if kind == "requirement":
            continue
        if kind == "exemption":
            key = (combination.endpoint, result.get("method", combination.method))
            if key not in exemptions:
                violations.append(
                    f"admin combination exempted without a registry entry: {_fmt(combination)}"
                )
            continue
        violations.append(
            f"admin combination governed but kind={kind!r}: {_fmt(combination)}"
        )
    return violations


def exemption_registry_violations(exemptions=None) -> list[str]:
    """Approved exemptions must be literal, exact ``(endpoint, method)`` keys.

    The current expectation is an empty registry.  This guard does not assert
    emptiness -- ``test_exemption_registry_empty`` does -- it makes sure that if
    an entry is ever added it cannot be a wildcard or a prefix that quietly
    removes a family of admin routes from the boundary.
    """
    if exemptions is None:
        from app import auth

        exemptions = auth.APPROVED_ADMIN_RBAC_EXEMPTIONS

    violations: list[str] = []
    for key in exemptions:
        if not isinstance(key, tuple) or len(key) != 2:
            violations.append(f"exemption key is not an (endpoint, method) tuple: {key!r}")
            continue
        endpoint, method = key
        for label, value in (("endpoint", endpoint), ("method", method)):
            if not isinstance(value, str) or not value:
                violations.append(f"exemption {label} is not a non-empty string: {key!r}")
            elif "*" in value or "?" in value:
                violations.append(f"exemption {label} contains a wildcard: {key!r}")
        if isinstance(method, str) and method and method != method.upper().strip():
            violations.append(f"exemption method is not a normalized method: {key!r}")
    return violations


# ---------------------------------------------------------------------------
# Guard 2 -- exactly one applicable policy per governed pair
# ---------------------------------------------------------------------------

def policy_ownership_violations(
    classification: RbacClassification,
    *,
    resources=None,
    satisfies=None,
    direct_lookup=None,
) -> list[str]:
    """Exactly one applicable authorization policy per governed business pair.

    Covers, in order: unresolvable identity, ambiguous route resolution, a
    governed pair with no policy, a governed pair with two policies
    (requirement *and* exemption -- the classifier reports that as
    ``invalid_configuration``), a requirement naming an unknown resource, a
    requirement whose scope silently falls back to allow, and a requirement
    that disagrees with the direct ``get_admin_permission_requirement`` lookup.
    """
    from app import auth

    if resources is None:
        resources = auth.ACCESS_RESOURCE_ORDER
    if satisfies is None:
        satisfies = auth.permission_scope_satisfies
    if direct_lookup is None:
        direct_lookup = auth.get_admin_permission_requirement
    resources = frozenset(resources)

    violations: list[str] = []
    for combination in classification.unresolved:
        violations.append(f"no live rule for inventory identity: {_fmt(combination)}")
    for combination, count in classification.ambiguous:
        violations.append(f"{count} live rules share identity: {_fmt(combination)}")

    seen: dict[Combination, tuple] = {}
    for combination, result in classification.governed:
        kind = result.get("kind")
        requirement = result.get("requirement")
        exemption = result.get("exemption")
        if kind == "missing_configuration":
            violations.append(f"governed pair has no applicable policy: {_fmt(combination)}")
            continue
        if kind == "invalid_configuration":
            violations.append(
                f"governed pair has both a requirement and an exemption: {_fmt(combination)}"
            )
            continue
        if bool(requirement) == bool(exemption):
            violations.append(
                f"governed pair violates the requirement/exemption XOR: {_fmt(combination)}"
            )
            continue
        if kind not in {"requirement", "exemption"}:
            violations.append(f"governed pair has kind={kind!r}: {_fmt(combination)}")
            continue
        if kind == "exemption":
            continue

        previous = seen.get(combination)
        if previous is not None and previous != tuple(requirement):
            violations.append(
                f"governed pair resolves to two requirements {previous} / "
                f"{tuple(requirement)}: {_fmt(combination)}"
            )
        seen[combination] = tuple(requirement)

        resource, scope = requirement
        if resource not in resources:
            violations.append(
                f"requirement names unknown resource {resource!r}: {_fmt(combination)}"
            )
        # A required scope that does not normalize to a known scope silently
        # degrades to "none", which every actor satisfies -- a fail-OPEN policy
        # that no count-based check could ever see.
        if satisfies(ZERO_PRIVILEGE_SCOPE, scope):
            violations.append(
                f"requirement scope {scope!r} is satisfied by the zero-privilege actor "
                f"(fail-open policy): {_fmt(combination)}"
            )
        direct = direct_lookup(combination.endpoint, result.get("method", combination.method))
        if tuple(requirement) != tuple(direct or ()):
            violations.append(
                f"classifier requirement {tuple(requirement)} disagrees with direct lookup "
                f"{direct!r}: {_fmt(combination)}"
            )
    return violations


# ---------------------------------------------------------------------------
# Guard 3 -- the non-governed surface is explicitly categorized
# ---------------------------------------------------------------------------

class NonGovernedCategory(NamedTuple):
    name: str
    rationale: str
    identities: frozenset


# Every combination outside the governed boundary is enumerated here under a
# named, reviewable non-admin category.  There is deliberately no catch-all
# bucket: a newly non-governed route fails ``test_non_governed_surface_is_
# explicitly_categorized`` until somebody classifies it on purpose.
NON_GOVERNED_BOUNDARY_CATEGORIES: tuple[NonGovernedCategory, ...] = (
    NonGovernedCategory(
        name="public_landing",
        rationale=(
            "Unauthenticated entry point; redirects by session state and exposes "
            "no administrative data."
        ),
        identities=frozenset({Combination("/", "index", "GET")}),
    ),
    NonGovernedCategory(
        name="authentication_entry_exit",
        rationale=(
            "Login and logout establish/destroy the session the admin boundary "
            "is evaluated against; they cannot themselves require an admin scope."
        ),
        identities=frozenset({
            Combination("/login", "login", "GET"),
            Combination("/login", "login", "POST"),
            Combination("/logout", "logout", "GET"),
            Combination("/logout", "logout", "POST"),
        }),
    ),
    NonGovernedCategory(
        name="health_probe",
        rationale="Liveness probe for the deployment platform; returns no business data.",
        identities=frozenset({Combination("/health", "health", "GET")}),
    ),
    NonGovernedCategory(
        name="csrf_token_infrastructure",
        rationale=(
            "CSRF token refresh is request-infrastructure consumed by both admin "
            "and aluno surfaces; it is owned by the CSRF inventory baseline."
        ),
        identities=frozenset({Combination("/csrf-token", "csrf_token_refresh", "GET")}),
    ),
    NonGovernedCategory(
        name="static_and_upload_delivery",
        rationale=(
            "Byte delivery of static assets and uploaded files; no RBAC resource "
            "projection exists for an asset path."
        ),
        identities=frozenset({
            Combination("/favicon.ico", "favicon", "GET"),
            Combination("/static/<path:filename>", "static", "GET"),
            Combination("/uploads/<path:filename>", "uploaded_file", "GET"),
        }),
    ),
    NonGovernedCategory(
        name="aluno_self_service",
        rationale=(
            "Student-facing self-service surface. Authorization is the aluno "
            "session/ownership boundary, not the admin access-level matrix; "
            "test_no_aluno_routes_selected pins that these never become governed."
        ),
        identities=frozenset({
            Combination("/aluno/arquivos", "aluno.aluno_arquivos", "GET"),
            Combination("/aluno/arquivos/download/<int:arquivo_id>", "aluno.aluno_baixar_arquivo", "GET"),
            Combination("/aluno/arquivos/ver/<int:arquivo_id>", "aluno.aluno_visualizar_arquivo", "GET"),
            Combination("/aluno/dashboard", "aluno.aluno_dashboard", "GET"),
            Combination("/aluno/meus_dados", "aluno.aluno_meus_dados", "GET"),
            Combination("/aluno/meus_dados", "aluno.aluno_meus_dados", "POST"),
            Combination("/aluno/nova-requisicao", "aluno.aluno_nova_requisicao", "GET"),
            Combination("/aluno/nova-requisicao", "aluno.aluno_nova_requisicao", "POST"),
            Combination("/aluno/nova_requisicao", "aluno.aluno_nova_requisicao", "GET"),
            Combination("/aluno/nova_requisicao", "aluno.aluno_nova_requisicao", "POST"),
            Combination("/aluno/progresso", "aluno.aluno_progresso", "GET"),
            Combination("/aluno/reportar", "aluno.aluno_reportar", "GET"),
            Combination("/aluno/reportar", "aluno.aluno_reportar", "POST"),
            Combination("/aluno/requisicoes", "aluno.aluno_minhas_requisicoes", "GET"),
            Combination("/aluno/requisicoes/<int:req_id>", "aluno.aluno_requisicao_detalhe", "GET"),
            Combination("/aluno/requisicoes/<int:req_id>", "aluno.aluno_requisicao_detalhe", "POST"),
        }),
    ),
    NonGovernedCategory(
        name="comprovante_actor_scoped_delivery",
        rationale=(
            "Shared attachment delivery for aluno and admin actors. It enforces "
            "its own per-request actor check (authorize_request_comprovante_actor, "
            "admin_scope='view') instead of a route-level admin requirement, so a "
            "student may open only their own comprovante."
        ),
        identities=frozenset({
            Combination("/comprovantes/<int:attachment_id>/open", "comprovantes.open_comprovante", "GET"),
        }),
    ),
)


def non_governed_category_violations(identities) -> list[str]:
    """The observed non-governed surface must equal the declared categories exactly."""
    observed = frozenset(Combination(*identity) for identity in identities)

    violations: list[str] = []
    declared: set[Combination] = set()
    owner: dict[Combination, str] = {}
    for category in NON_GOVERNED_BOUNDARY_CATEGORIES:
        if not category.rationale.strip():
            violations.append(f"category {category.name!r} has no rationale")
        if not category.identities:
            violations.append(f"category {category.name!r} is empty")
        for identity in category.identities:
            identity = Combination(*identity)
            if is_admin_rule(identity.rule):
                violations.append(
                    f"category {category.name!r} declares an admin identity as "
                    f"non-governed: {_fmt(identity)}"
                )
            previous = owner.get(identity)
            if previous is not None:
                violations.append(
                    f"identity declared by both {previous!r} and {category.name!r}: "
                    f"{_fmt(identity)}"
                )
            owner[identity] = category.name
            declared.add(identity)

    for identity in sorted(observed - declared):
        violations.append(
            f"non-governed identity has no boundary category: {_fmt(identity)}"
        )
    for identity in sorted(declared - observed):
        violations.append(
            f"boundary category declares an identity that is no longer "
            f"non-governed: {_fmt(identity)}"
        )
    return violations


# ---------------------------------------------------------------------------
# Guard 4 -- actor matrix and denial matrix
# ---------------------------------------------------------------------------

def actor_identities(requirements, levels=ADMIN_ACCESS_LEVELS) -> frozenset[ActorCase]:
    """The exact actor evaluation set: every governed requirement x every level."""
    return frozenset(
        ActorCase(*Requirement(*requirement), level)
        for requirement in requirements
        for level in levels
    )


def actor_matrix_violations(requirements, actors, levels=ADMIN_ACCESS_LEVELS) -> list[str]:
    """``actors`` must be the exact product of the governed set and the levels."""
    expected = actor_identities(requirements, levels)
    observed = frozenset(ActorCase(*actor) for actor in actors)
    violations: list[str] = []
    for actor in sorted(expected - observed):
        violations.append(f"governed actor combination missing from the matrix: {_fmt(actor)}")
    for actor in sorted(observed - expected):
        violations.append(f"matrix evaluated an actor combination outside the governed set: {_fmt(actor)}")
    return violations


def canonical_decision(level: str, resource: str, scope: str, *, profiles=None, satisfies=None) -> bool:
    """The canonical allow/deny decision for one actor/policy combination."""
    from app import auth

    if profiles is None:
        profiles = auth.PROFILE_RESOURCE_SCOPES
    if satisfies is None:
        satisfies = auth.permission_scope_satisfies
    return bool(satisfies(profiles.get(level, {}).get(resource, ZERO_PRIVILEGE_SCOPE), scope))


def denial_identities(actors, *, profiles=None, satisfies=None) -> frozenset[ActorCase]:
    """The exact subset of actor combinations whose canonical decision is deny."""
    return frozenset(
        ActorCase(*actor)
        for actor in (ActorCase(*value) for value in actors)
        if not canonical_decision(
            actor.level, actor.resource, actor.scope, profiles=profiles, satisfies=satisfies
        )
    )


def allowance_identities(actors, *, profiles=None, satisfies=None) -> frozenset[ActorCase]:
    return frozenset(ActorCase(*actor) for actor in actors) - denial_identities(
        actors, profiles=profiles, satisfies=satisfies
    )


def canonical_denial_cases(classification=None, levels=ADMIN_ACCESS_LEVELS) -> tuple[ActorCase, ...]:
    """Deterministically ordered denial cases for HTTP-level replay."""
    if classification is None:
        classification = canonical_classification()
    actors = actor_identities(requirement_identities(classification), levels)
    return tuple(sorted(denial_identities(actors)))


# ---------------------------------------------------------------------------
# Guard 5 -- dynamic / static partition
# ---------------------------------------------------------------------------

def dynamic_requirement_identities(requirements) -> frozenset[Requirement]:
    return frozenset(
        Requirement(*requirement)
        for requirement in requirements
        if DYNAMIC_SEGMENT_RE.search(Requirement(*requirement).rule)
    )


def static_requirement_identities(requirements) -> frozenset[Requirement]:
    return frozenset(Requirement(*value) for value in requirements) - dynamic_requirement_identities(
        requirements
    )


def dynamic_partition_violations(requirements, dynamic, static) -> list[str]:
    """``dynamic`` and ``static`` must partition the governed requirement set exactly."""
    everything = frozenset(Requirement(*value) for value in requirements)
    dynamic = frozenset(Requirement(*value) for value in dynamic)
    static = frozenset(Requirement(*value) for value in static)

    violations: list[str] = []
    for requirement in sorted(dynamic & static):
        violations.append(f"requirement classified both dynamic and static: {_fmt(requirement)}")
    for requirement in sorted(everything - (dynamic | static)):
        violations.append(f"governed requirement in neither partition: {_fmt(requirement)}")
    for requirement in sorted((dynamic | static) - everything):
        violations.append(f"partition holds a non-governed requirement: {_fmt(requirement)}")
    for requirement in sorted(dynamic):
        if not DYNAMIC_SEGMENT_RE.search(requirement.rule):
            violations.append(f"dynamic partition holds a static rule: {_fmt(requirement)}")
    for requirement in sorted(static):
        if DYNAMIC_SEGMENT_RE.search(requirement.rule):
            violations.append(f"static partition holds a dynamic rule: {_fmt(requirement)}")
    return violations


# ---------------------------------------------------------------------------
# Identity digests -- the pinned anchors
# ---------------------------------------------------------------------------

def requirement_matrix_digest(requirements) -> str:
    """Byte-compatible with the historical REF-0C-D-R1 requirement-matrix digest."""
    rows = sorted(
        (requirement.endpoint, requirement.method, requirement.resource, requirement.scope)
        for requirement in (Requirement(*value) for value in requirements)
    )
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _identity_lines(identities) -> list[str]:
    return ["\t".join(str(field) for field in identity) for identity in identities]


def identities_digest(identities) -> str:
    return _digest(_identity_lines(identities))


def profile_digest(level: str, profiles=None) -> str:
    from app import auth

    if profiles is None:
        profiles = auth.PROFILE_RESOURCE_SCOPES
    raw = json.dumps(
        profiles.get(level, {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# The requirement matrix is the primary RBAC anchor: which (endpoint, method)
# pair requires which (resource, scope).  Inherited unchanged from REF-0C-D-R1.
CANONICAL_REQUIREMENT_MATRIX_DIGEST = (
    "98de88ba6c58a3b6da4f6d17749c06bb42c9b435ce34ccbce34049cd5a33d796"
)

# The profile anchor: which access level holds which scope per resource.
CANONICAL_PROFILE_DIGESTS = {
    "admin_total": "8100f29522b3bea3cd55d37f2e35bd04a7e663e014669237b5ef7646777a77ae",
    "administrativo": "bce039124b87b716dfc6c0c78a75a0a08b563fa8d452dbd148931cd733da759c",
    "consultivo": "b592479780c57f1d9820bef4fb5f476a7a6caf178f262ca594c29f009da9bbb0",
}

# The three projections below are fully determined by the two anchors above.
# They are pinned anyway, as identity digests rather than counts, so that a
# change in either anchor has to be acknowledged where its security meaning
# lives: which routes are reachable by parameter, and which actor is denied.
CANONICAL_NON_GOVERNED_IDENTITIES_SHA256 = (
    "a8ceef4cfe307ce75731d9a22f9fba6200964036984df3746c7121896c5f3899"
)
CANONICAL_DYNAMIC_REQUIREMENT_IDENTITIES_SHA256 = (
    "b7544cb0ca095be49aa141e50d36b958af35645009ef3c22ee84482f97e10b90"
)
CANONICAL_DENIAL_MATRIX_IDENTITIES_SHA256 = (
    "cbb2c5d8970dfb60ebc7347a93ac25a855df6d5c2082673ad65aafed22fc8610"
)


# ---------------------------------------------------------------------------
# Canonical singletons and diagnostics
# ---------------------------------------------------------------------------

_CACHE: dict[str, object] = {}


def canonical_classification() -> RbacClassification:
    """The canonical classification of the pinned artifact against the live URL map."""
    if "classification" not in _CACHE:
        _CACHE["classification"] = classify_inventory()
    return _CACHE["classification"]  # type: ignore[return-value]


def diagnostics(classification=None) -> dict:
    """Derived counts for failure messages and review. Nothing asserts on these."""
    if classification is None:
        classification = canonical_classification()
    requirements = requirement_identities(classification)
    actors = actor_identities(requirements)
    denials = denial_identities(actors)
    dynamic = dynamic_requirement_identities(requirements)
    return {
        "route_entries": len({(c.rule, c.endpoint) for c in classification.combinations}),
        "combinations": len(combination_identities(classification)),
        "governed": len(governed_identities(classification)),
        "governed_requirements": len(requirements),
        "non_governed": len(non_governed_identities(classification)),
        "admin_governed": len([c for c in governed_identities(classification) if is_admin_rule(c.rule)]),
        "external_governed": len(
            [c for c in governed_identities(classification) if not is_admin_rule(c.rule)]
        ),
        "distinct_policies": len({(r.resource, r.scope) for r in requirements}),
        "actor_combinations": len(actors),
        "denials": len(denials),
        "allowances": len(actors) - len(denials),
        "dynamic_requirements": len(dynamic),
        "dynamic_rules": len({(r.endpoint, r.rule) for r in dynamic}),
        "static_requirements": len(requirements) - len(dynamic),
        "denials_by_level": {
            level: len([d for d in denials if d.level == level]) for level in ADMIN_ACCESS_LEVELS
        },
    }


def _fmt(identity) -> str:
    return " ".join(f"{name}={value}" for name, value in zip(identity._fields, identity))
