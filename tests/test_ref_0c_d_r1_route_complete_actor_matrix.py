"""REF-0C-D-R1 — Route-complete actor decision and pre-handler denied-action immutability."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from werkzeug.routing import (
    IntegerConverter,
    FloatConverter,
    UnicodeConverter,
    PathConverter,
    UUIDConverter,
    AnyConverter,
    Map,
)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app import auth
from tests import canonical_rbac_test_support as rbac
from tests.canonical_baseline_support import (
    assert_route_inventory_artifact_is_canonical,
)
from tests.versioned_test_support import isolated_versioned_app_env
from utils.messages import ensure_message_overrides_schema


ARTIFACT_PATH = Path(__file__).parent / "_artifacts" / "route_inventory_baseline.json"
# UT-BR2-D: the RBAC derivation, the admin boundary and the actor/denial matrices
# are owned by ``tests/canonical_rbac_test_support.py``.  This suite keeps its own
# semantic proofs -- classification invariants, URL roundtrip, HTTP denial replay,
# filesystem isolation, database immutability -- and delegates the global identity
# sets there instead of re-freezing a private copy of each total.
BUSINESS_METHODS = rbac.BUSINESS_METHODS
ADMIN_ACCESS_LEVELS = rbac.ADMIN_ACCESS_LEVELS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_baseline() -> dict:
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def _build_live_inventory() -> dict:
    routes = []
    for rule in main.app.url_map.iter_rules():
        routes.append({
            "endpoint": rule.endpoint,
            "methods": sorted(set(rule.methods or ()) & BUSINESS_METHODS),
            "rule": rule.rule,
        })
    routes.sort(key=lambda r: (r["rule"], r["endpoint"], r["methods"]))
    return {"schema_version": 1, "generated_from": "main.app.url_map", "routes": routes}


def _find_live_rule(rule_text: str, endpoint: str):
    matches = [
        rule for rule in main.app.url_map.iter_rules()
        if rule.rule == rule_text and rule.endpoint == endpoint
    ]
    if len(matches) == 0:
        raise LookupError(f"No live rule for ({rule_text}, {endpoint})")
    if len(matches) > 1:
        raise LookupError(f"Multiple live rules ({len(matches)}) for ({rule_text}, {endpoint})")
    return matches[0]


def _classify(rule_text: str, endpoint: str, method: str) -> dict:
    return auth.classify_governed_admin_request(endpoint, _find_live_rule(rule_text, endpoint), method)


def _live_inventory_routes() -> list[dict]:
    """Artifact-shaped entries built from the live URL map, not from the artifact."""
    return [
        {
            "endpoint": rule.endpoint,
            "methods": sorted(set(rule.methods or ()) & BUSINESS_METHODS),
            "rule": rule.rule,
        }
        for rule in main.app.url_map.iter_rules()
    ]


# The canonical classification is derived once, from the route artifact *after*
# it has been checked against its pinned digest, against the live URL map.  The
# two module-level projections below keep the historical tuple shapes --
# ``(rule, endpoint, method, resource, scope)`` and that plus a level -- so the
# HTTP replay further down is unchanged; they are now exact, deterministically
# ordered identity sets rather than lists whose lengths were frozen separately.
_CLASSIFICATION = rbac.canonical_classification()
_GOVERNED_PAIRS = rbac.canonical_requirements_in_order(_CLASSIFICATION)


# ---------------------------------------------------------------------------
# SQLite type-safe fingerprint
# ---------------------------------------------------------------------------

def _fingerprint_value(v):
    if v is None:
        return "N"
    if isinstance(v, int):
        return f"I:{v}"
    if isinstance(v, float):
        return f"R:{v}"
    if isinstance(v, str):
        return f"T:{v}"
    if isinstance(v, bytes):
        return f"B:{v.hex()}"
    raise ValueError(f"Unsupported SQL type {type(v).__name__} value={v!r}")


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _capture_fingerprint(env, ctx: str = "") -> str:
    detail = f" for {ctx}" if ctx else ""
    resolved_main = Path(main.DATABASE).resolve()
    resolved_fixture = Path(env["db_path"]).resolve()
    assert resolved_main == resolved_fixture, (
        f"fingerprint: main.DATABASE resolved {resolved_main} != fixture db_path {resolved_fixture}{detail}"
    )
    resolved_config = Path(main.app.config["DATABASE_PATH"]).resolve()
    assert resolved_config == resolved_main, (
        f"fingerprint: app DATABASE_PATH resolved {resolved_config} != main.DATABASE {resolved_main}{detail}"
    )
    hasher = hashlib.sha256()
    with main.app.app_context():
        conn = main.get_db_connection()
        database_rows = conn.execute("PRAGMA database_list").fetchall()
        main_rows = [row for row in database_rows if row["name"] == "main"]
        assert len(main_rows) == 1, (
            f"fingerprint: expected one main database, got {len(main_rows)}{detail}"
        )
        db_file = main_rows[0]
        assert Path(db_file["file"]).resolve() == resolved_main, (
            f"fingerprint: PRAGMA database_list file {Path(db_file['file']).resolve()} != {resolved_main}{detail}"
        )
        assert not conn.in_transaction, f"fingerprint: unexpected open transaction{detail}"
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        for tname in tables:
            quoted_name = _quote_identifier(tname)
            meta_rows = sorted(
                conn.execute(f"PRAGMA table_info({quoted_name})").fetchall(),
                key=lambda row: int(row["cid"]),
            )
            columns = []
            for row in meta_rows:
                columns.append({
                    "cid": _fingerprint_value(row["cid"]),
                    "name": _fingerprint_value(row["name"]),
                    "type": _fingerprint_value(row["type"]),
                    "notnull": _fingerprint_value(row["notnull"]),
                    "dflt_value": _fingerprint_value(row["dflt_value"]),
                    "pk": _fingerprint_value(row["pk"]),
                })
            cursor = conn.execute(f"SELECT * FROM {quoted_name}")
            rows = []
            for r in cursor.fetchall():
                rows.append([_fingerprint_value(v) for v in r])
            row_strings = sorted(json.dumps(r, separators=(",", ":")) for r in rows)
            table_payload = json.dumps(
                {"table": tname, "columns": columns, "rows": row_strings},
                sort_keys=True, separators=(",", ":")
            )
            hasher.update(table_payload.encode("utf-8"))
        assert not conn.in_transaction, (
            f"fingerprint: unexpected open transaction after capture{detail}"
        )
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Converter and URL building
# ---------------------------------------------------------------------------

def _case_context(endpoint: str, rule_text: str, method: str, level: str, resource: str, scope: str) -> str:
    return (
        f"endpoint={endpoint} rule={rule_text} method={method} "
        f"level={level} resource={resource} scope={scope}"
    )


def _string_value_for_arg(arg_name: str, case_idx: int = -1) -> str:
    base = {"active_tab": "aac", "provider": "google", "message_key": "msg_test_0c_d_r1"}
    val = base.get(arg_name, f"test_{arg_name}")
    if case_idx >= 0:
        val = f"{val}_r1_deny_{case_idx}"
    return val


def _converter_value(converter, arg_name: str, *, endpoint: str = "", rule_text: str = "", case_idx: int = -1):
    cls = type(converter)
    if cls is IntegerConverter:
        return 910000 + case_idx if case_idx >= 0 else 1
    if cls is FloatConverter:
        return 910000.25 + case_idx if case_idx >= 0 else 1.0
    if cls is UnicodeConverter:
        return _string_value_for_arg(arg_name, case_idx)
    if cls is PathConverter:
        base = "test/path"
        return f"{base}/r1_deny_{case_idx}" if case_idx >= 0 else base
    if cls is UUIDConverter:
        if case_idx >= 0:
            return uuid.UUID(f"00000000-0000-0000-0000-{case_idx:012d}")
        return uuid.UUID("00000000-0000-0000-0000-000000000001")
    if cls is AnyConverter:
        items = converter.items
        if not items:
            raise NotImplementedError(
                f"AnyConverter with empty items: endpoint={endpoint} "
                f"rule={rule_text} arg={arg_name} class=AnyConverter"
            )
        return next(iter(items))
    raise NotImplementedError(
        f"Unsupported converter {cls.__name__}: endpoint={endpoint} "
        f"rule={rule_text} arg={arg_name} class={cls.__name__}"
    )


def _normalize_kwargs(rule, kwargs):
    normalized = {}
    for arg in rule.arguments:
        conv = rule._converters.get(arg)
        if conv:
            url_val = conv.to_url(kwargs[arg])
            normalized[arg] = conv.to_python(url_val)
        else:
            normalized[arg] = kwargs[arg]
    return normalized


def _assert_url_roundtrip(rule, rule_text, endpoint, method, url, kwargs, ctx: str) -> None:
    matched_rule, matched_kwargs = main.app.url_map.bind("").match(
        url.rsplit("?", 1)[0], method=method, return_rule=True
    )
    assert matched_rule is rule, f"URL matched a different Rule object for {ctx}"
    assert matched_rule.rule == rule_text, (
        f"URL matched rule={matched_rule.rule}, expected {rule_text} for {ctx}"
    )
    assert matched_rule.endpoint == endpoint, (
        f"URL matched endpoint={matched_rule.endpoint}, expected {endpoint} for {ctx}"
    )
    assert method.upper() in matched_rule.methods, (
        f"method={method} not in matched methods={matched_rule.methods} for {ctx}"
    )
    normalized_kwargs = _normalize_kwargs(rule, kwargs)
    assert matched_kwargs == normalized_kwargs, (
        f"URL matched kwargs={matched_kwargs}, expected {normalized_kwargs} for {ctx}"
    )


def _build_url_for_governed(
    rule_text: str,
    endpoint: str,
    method: str,
    *,
    case_idx: int = -1,
    ctx: str = "",
) -> tuple[str, dict]:
    rule = _find_live_rule(rule_text, endpoint)
    kwargs = {}
    for arg in rule.arguments:
        conv = rule._converters.get(arg)
        if conv:
            kwargs[arg] = _converter_value(
                conv, arg, endpoint=endpoint, rule_text=rule_text, case_idx=case_idx
            )
        else:
            kwargs[arg] = _string_value_for_arg(arg, case_idx)
    roundtrip_ctx = ctx or f"endpoint={endpoint} rule={rule_text} method={method}"
    built = rule.build(kwargs, append_unknown=False)
    assert built is not None, f"Rule.build failed for {roundtrip_ctx}"
    domain_part, url = built
    assert domain_part == "", (
        f"unexpected domain part {domain_part!r} while building URL for {roundtrip_ctx}"
    )
    _assert_url_roundtrip(
        rule, rule_text, endpoint, method, url, kwargs, roundtrip_ctx
    )
    return url, kwargs


# ---------------------------------------------------------------------------
# DB context warming
# ---------------------------------------------------------------------------

def _warm_access_context(user_id: int, level: str, env, ctx: str = "") -> None:
    detail = f" for {ctx}" if ctx else ""
    with main.app.app_context():
        conn = main.get_db_connection()
        database_rows = conn.execute("PRAGMA database_list").fetchall()
        main_rows = [row for row in database_rows if row["name"] == "main"]
        assert len(main_rows) == 1, f"warming: expected one main database{detail}"
        resolved_db = Path(main_rows[0]["file"]).resolve()
        assert resolved_db == Path(env["db_path"]).resolve(), (
            f"warming: connection DB {resolved_db} != fixture DB {env['db_path']}{detail}"
        )
        assert not conn.in_transaction, (
            f"warming: unexpected open transaction before load{detail}"
        )
        ensure_message_overrides_schema(conn)
        conn.commit()
        assert not conn.in_transaction, (
            f"warming: unexpected open transaction after message-schema warmup{detail}"
        )
        access_ctx = main._load_admin_access_context(conn, user_id)
        assert access_ctx["is_admin"], (
            f"warm: is_admin False for user_id={user_id} level={level}{detail}"
        )
        assert access_ctx["access_level"] == level, (
            f"warm: access_level={access_ctx['access_level']} expected {level}{detail}"
        )
        assert access_ctx["overrides"] == {}, (
            f"warm: non-empty overrides: {access_ctx['overrides']}{detail}"
        )
        expected_scopes = auth.merge_resource_scopes(level, {})
        assert access_ctx["effective_scopes"] == expected_scopes, (
            f"warm: effective_scopes mismatch for {level}{detail}"
        )
        assert not conn.in_transaction, (
            f"warm: unexpected open transaction after context load{detail}"
        )


# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------

def _make_sentinel(ctx: str):
    sentinel_state = {"raised": False, "exc": None}
    def _sentinel(*a, **kw):
        sentinel_state["raised"] = True
        exc = RuntimeError(f"sentinel invoked for {ctx}")
        sentinel_state["exc"] = exc
        raise exc
    return _sentinel, sentinel_state


def _install_sentinel(app, endpoint: str, sentinel_func) -> object:
    orig = app.view_functions.get(endpoint)
    app.view_functions[endpoint] = sentinel_func
    return orig


# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------

def _make_admin(access_level: str) -> int:
    with main.app.app_context():
        conn = main.get_db_connection()
        uid = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso)"
            " VALUES (?, ?, ?, ?, ?) RETURNING id",
            (
                f"Admin {access_level}",
                f"r1.{access_level}.{uuid.uuid4().hex[:8]}@example.com",
                main.hash_password("r1-test-pass"),
                "admin",
                access_level,
            ),
        ).fetchone()["id"]
        conn.commit()
    return uid


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_type"] = "admin"
        sess["user_name"] = "R1 Test"


def _logout(client) -> None:
    with client.session_transaction() as sess:
        sess.clear()


# ---------------------------------------------------------------------------
# Denied-case helpers
# ---------------------------------------------------------------------------

# The exact set of actor/policy combinations whose canonical decision is deny,
# in deterministic order.  Replayed case by case over HTTP below; the HTTP tests
# assert identity-set equality against this tuple, never a case count.
_DENIED_CASES = rbac.canonical_denial_cases(_CLASSIFICATION)


def _assert_browser_denial(resp, ctx: str) -> None:
    assert resp.status_code == 302, (
        f"browser: expected 302 for {ctx}, got {resp.status_code}"
    )
    loc = resp.headers.get("Location", "")
    path = urlsplit(loc).path.rstrip("/")
    assert path == "/admin/dashboard", (
        f"browser: expected /admin/dashboard for {ctx}, got Location={loc}"
    )


def _assert_ajax_denial(resp, resource: str, required_scope: str, ctx: str) -> None:
    assert resp.status_code == 403, (
        f"AJAX: expected 403 for {ctx}, got {resp.status_code}"
    )
    data = resp.get_json()
    assert data is not None, f"AJAX: no JSON body for {ctx}"
    assert data.get("ok") is False, f"AJAX: ok not False for {ctx}"
    assert data.get("error") == "forbidden", f"AJAX: error not forbidden for {ctx}"
    assert data.get("resource") == resource, (
        f"AJAX: resource mismatch for {ctx}: expected {resource} got {data.get('resource')}"
    )
    assert data.get("required_scope") == required_scope, (
        f"AJAX: scope mismatch for {ctx}: expected {required_scope} got {data.get('required_scope')}"
    )
    assert "message" in data, f"AJAX: message missing for {ctx}"


def _sensitive_set(env) -> list[str]:
    paths = [
        str(env["db_path"]),
        str(env["uploads_path"]),
        str(env["documents_path"]),
        str(env["local_backups_path"]),
        str(env["cloud_backups_path"]),
    ]
    lp = env.get("temp_log_path")
    if lp:
        paths.append(str(lp))
    result: list[str] = []
    for p in paths:
        result.append(p)
        result.append(Path(p).as_posix())
        result.append(json.dumps(p)[1:-1])
    result.append("traceback")
    result.append("exception")
    return result


def _check_surface(text: str, label: str, sensitive: list[str], ctx: str):
    lower = text.lower()
    for s in sensitive:
        if len(s) < 3:
            continue
        if s.lower() in lower:
            pytest.fail(
                f"AJAX: sensitive value leaked in {label} for {ctx}: value={s[:80]}"
            )


# ---------------------------------------------------------------------------
# Part 1 — Baseline equals live inventory
# ---------------------------------------------------------------------------

def test_baseline_matches_live_inventory():
    assert _build_live_inventory() == _load_baseline()


def test_route_artifact_is_pinned_to_the_canonical_url_contract():
    """Replaces ``len(routes) == 128``.

    The rule count was a lossy shadow of the URL contract: it could not tell a
    deleted route plus an added route from no change at all.  The canonical
    owner pins the full (rule, endpoint, methods) identity digest instead, so
    this suite's entire RBAC derivation is anchored to a reviewed artifact.
    """
    assert_route_inventory_artifact_is_canonical(context="REF-0C-D-R1")


def test_combinations_partition_into_governed_and_non_governed():
    """Replaces ``combinations == 156``.

    Every business combination of the artifact is classified exactly once, into
    exactly one side of the boundary, with nothing unresolvable or ambiguous.
    """
    expected = frozenset(
        rbac.Combination(entry["rule"], entry["endpoint"], method)
        for entry in _load_baseline()["routes"]
        for method in entry["methods"]
    )
    combinations = rbac.combination_identities(_CLASSIFICATION)
    governed = rbac.governed_identities(_CLASSIFICATION)
    non_governed = rbac.non_governed_identities(_CLASSIFICATION)

    assert _CLASSIFICATION.unresolved == (), (
        f"inventory identities absent from the live URL map: {_CLASSIFICATION.unresolved}"
    )
    assert _CLASSIFICATION.ambiguous == (), (
        f"inventory identities resolving to several live rules: {_CLASSIFICATION.ambiguous}"
    )
    assert combinations == expected
    assert len(_CLASSIFICATION.combinations) == len(combinations), "duplicate combination identity"
    assert governed | non_governed == combinations
    assert governed & non_governed == frozenset()


# ---------------------------------------------------------------------------
# Part 2 — Governed classification invariants
# ---------------------------------------------------------------------------

def test_governed_set_is_exactly_the_requirement_carrying_set():
    """Replaces ``governed requirements == 130``.

    The count could not distinguish "an admin route lost its policy while an
    unrelated route gained one".  The contract is that the governed partition
    and the requirement-carrying set are the *same* identities, and that their
    (endpoint, method, resource, scope) projection still hashes to the pinned
    requirement matrix.
    """
    requirements = rbac.requirement_identities(_CLASSIFICATION)
    assert {requirement.combination for requirement in requirements} == rbac.governed_identities(
        _CLASSIFICATION
    )
    assert len(requirements) == len(rbac.governed_identities(_CLASSIFICATION))
    assert rbac.requirement_matrix_digest(requirements) == rbac.CANONICAL_REQUIREMENT_MATRIX_DIGEST


def test_governed_set_is_the_admin_boundary_plus_the_declared_external_callbacks():
    """The exact composition the old ``== 130`` comment described in prose.

    ``130  # 127 /admin pairs + 3 approved external callbacks`` asserted the
    sum only.  Here each side of that sum is reconstructed as an identity set,
    so the two can no longer drift in opposite directions and cancel out.
    """
    governed = rbac.governed_identities(_CLASSIFICATION)
    admin = {identity for identity in governed if rbac.is_admin_rule(identity.rule)}
    external = governed - admin

    expected_admin = set()
    expected_external = set()
    for rule in main.app.url_map.iter_rules():
        for method in sorted(set(rule.methods or ()) & BUSINESS_METHODS):
            identity = rbac.Combination(rule.rule, rule.endpoint, method)
            if rbac.is_admin_rule(rule.rule):
                expected_admin.add(identity)
            if method in auth.NON_ADMIN_RBAC_GOVERNED_ENDPOINTS.get(rule.endpoint, frozenset()):
                expected_external.add(identity)

    assert admin == expected_admin, (
        "every /admin business pair, and only those, must be inside the boundary"
    )
    assert external == expected_external, (
        "the only governed non-admin pairs are the declared external callbacks"
    )
    assert admin & external == set()
    assert admin | external == governed


def test_all_governed_requirement_kind():
    for entry in _load_baseline()["routes"]:
        for m in entry["methods"]:
            cls = _classify(entry["rule"], entry["endpoint"], m)
            if cls["governed"]:
                assert cls["kind"] == "requirement", (
                    f"endpoint={entry['endpoint']} rule={entry['rule']} method={m} kind={cls['kind']}"
                )


def test_xor_policy_holds():
    for entry in _load_baseline()["routes"]:
        for m in entry["methods"]:
            cls = _classify(entry["rule"], entry["endpoint"], m)
            if not cls["governed"]:
                continue
            req = cls.get("requirement")
            ex = cls.get("exemption")
            assert bool(req) != bool(ex), (
                f"XOR violated: endpoint={entry['endpoint']} rule={entry['rule']} "
                f"method={m}: req={req} ex={ex}"
            )


def test_exemption_registry_empty():
    assert len(auth.APPROVED_ADMIN_RBAC_EXEMPTIONS) == 0


def test_requirement_equals_get_admin_permission_requirement():
    for entry in _load_baseline()["routes"]:
        for m in entry["methods"]:
            cls = _classify(entry["rule"], entry["endpoint"], m)
            if cls["governed"] and cls["kind"] == "requirement":
                expected = main.get_admin_permission_requirement(entry["endpoint"], m)
                assert cls["requirement"] == expected, (
                    f"Mismatch: endpoint={entry['endpoint']} rule={entry['rule']} "
                    f"method={m}: classifier={cls['requirement']} direct={expected}"
                )


def test_requirement_matrix_digest_lock():
    assert (
        rbac.requirement_matrix_digest(_GOVERNED_PAIRS)
        == rbac.CANONICAL_REQUIREMENT_MATRIX_DIGEST
    )


def test_policy_ownership_is_exactly_one_policy_per_governed_pair():
    """No missing policy, no duplicate policy, and no fail-open required scope."""
    assert rbac.policy_ownership_violations(_CLASSIFICATION) == []


def test_no_admin_combination_is_outside_the_governed_boundary():
    """The admin fail-closed invariant that ``non_governed == 26`` never carried.

    Bumping that scalar to 27 would have silently accepted "one aluno route
    left the non-governed set and one /admin route joined it".  This asserts
    the security property directly: no ``/admin`` business combination may sit
    outside the boundary, whatever the size of either partition.
    """
    assert rbac.admin_boundary_violations(_CLASSIFICATION) == []
    assert rbac.exemption_registry_violations() == []
    stranded = sorted(
        identity
        for identity in rbac.non_governed_identities(_CLASSIFICATION)
        if rbac.is_admin_rule(identity.rule)
    )
    assert stranded == [], f"admin combinations outside the governed boundary: {stranded}"


def test_non_governed_surface_is_explicitly_categorized():
    """Replaces ``non_governed == 26``.

    Every combination outside the boundary must be claimed by exactly one
    named, non-admin boundary category with a written rationale.  There is no
    catch-all bucket, so a route that silently stops being governed fails here
    until it is classified on purpose.
    """
    identities = rbac.non_governed_identities(_CLASSIFICATION)
    assert rbac.non_governed_category_violations(identities) == []
    assert (
        rbac.identities_digest(identities)
        == rbac.CANONICAL_NON_GOVERNED_IDENTITIES_SHA256
    )


# ---------------------------------------------------------------------------
# Part 3 — Profile scope digests
# ---------------------------------------------------------------------------

def test_profile_digests_match_canonical():
    for level in ADMIN_ACCESS_LEVELS:
        assert rbac.profile_digest(level) == rbac.CANONICAL_PROFILE_DIGESTS[level], (
            f"{level} digest mismatch"
        )


def test_admin_total_has_full_for_all():
    for resource in auth.ACCESS_RESOURCE_ORDER:
        assert auth.PROFILE_RESOURCE_SCOPES["admin_total"].get(resource) == "full", resource


def test_administrativo_security_resources_are_none():
    for resource in auth.SECURITY_RESTRICTED_RESOURCES:
        assert auth.PROFILE_RESOURCE_SCOPES["administrativo"].get(resource) == "none", resource


def test_administrativo_non_security_are_full():
    for resource in auth.ACCESS_RESOURCE_ORDER:
        if resource not in auth.SECURITY_RESTRICTED_RESOURCES:
            assert auth.PROFILE_RESOURCE_SCOPES["administrativo"].get(resource) == "full", resource


def test_consultivo_security_resources_are_none():
    for resource in auth.SECURITY_RESTRICTED_RESOURCES:
        assert auth.PROFILE_RESOURCE_SCOPES["consultivo"].get(resource) == "none", resource


# ---------------------------------------------------------------------------
# Part 4 — Permission-layer matrix
# ---------------------------------------------------------------------------

def test_canonical_denial_matrix_is_the_exact_derived_set():
    """The denial matrix, reconstructed from the two pinned anchors.

    Replaces ``total_denied == 136``.  The denial set is fully determined by the
    requirement matrix and the profile scopes, both digest-pinned above, so it
    is derived here rather than typed -- and then pinned as an *identity*
    digest, so a change to either anchor has to be acknowledged where its
    security meaning lives.
    """
    actors = rbac.actor_identities(_GOVERNED_PAIRS)
    denials = rbac.denial_identities(actors)
    allowances = rbac.allowance_identities(actors)

    assert rbac.actor_matrix_violations(_GOVERNED_PAIRS, actors) == []
    assert denials | allowances == actors
    assert denials & allowances == frozenset()
    assert frozenset(_DENIED_CASES) == denials
    assert len(_DENIED_CASES) == len(denials), "duplicate denial identity"
    assert (
        rbac.identities_digest(denials) == rbac.CANONICAL_DENIAL_MATRIX_IDENTITIES_SHA256
    )


def test_permission_layer_matrix(env):
    """Every actor/policy combination evaluated against the real access context.

    The scalar totals this test used to end on (390 / 254 / 136 and the
    per-level 130/95/29) are replaced by exact set reconstruction: the set the
    loop actually evaluated must *be* the governed set times the access levels,
    and the allow/deny split it observed must *be* the canonical split.
    """
    ids = {l: _make_admin(l) for l in ADMIN_ACCESS_LEVELS}
    evaluated: set[rbac.ActorCase] = set()
    observed_allowed: set[rbac.ActorCase] = set()
    observed_denied: set[rbac.ActorCase] = set()
    with main.app.app_context():
        conn = main.get_db_connection()
        for rule_text, endpoint, method, resource, scope in _GOVERNED_PAIRS:
            for level in ADMIN_ACCESS_LEVELS:
                actor = rbac.ActorCase(rule_text, endpoint, method, resource, scope, level)
                assert actor not in evaluated, f"actor combination evaluated twice: {actor}"
                evaluated.add(actor)
                ctx = main._load_admin_access_context(conn, ids[level])
                ctx_str = _case_context(endpoint, rule_text, method, level, resource, scope)
                assert ctx["access_level"] == level, f"ctx access_level mismatch for {ctx_str}"
                assert ctx["overrides"] == {}, f"unexpected overrides for {ctx_str}: {ctx['overrides']}"
                expected_scopes = auth.merge_resource_scopes(level, {})
                assert ctx["effective_scopes"] == expected_scopes, (
                    f"effective_scopes mismatch for {ctx_str}"
                )
                assert not conn.in_transaction, f"open transaction after context load for {ctx_str}"
                can = main._admin_can(resource, scope, ctx)
                eff = auth.PROFILE_RESOURCE_SCOPES[level].get(resource, "none")
                expected = auth.permission_scope_satisfies(eff, scope)
                assert can == expected, (
                    f"{level} _admin_can({resource},{scope}) = {can} "
                    f"but permission_scope_satisfies({eff},{scope}) = {expected} "
                    f"for {ctx_str}"
                )
                assert can == rbac.canonical_decision(level, resource, scope), (
                    f"live decision diverged from the canonical decision for {ctx_str}"
                )
                (observed_allowed if can else observed_denied).add(actor)

    assert rbac.actor_matrix_violations(_GOVERNED_PAIRS, evaluated) == []
    assert observed_denied == rbac.denial_identities(evaluated)
    assert observed_allowed == rbac.allowance_identities(evaluated)
    assert observed_allowed | observed_denied == evaluated
    assert observed_allowed & observed_denied == set()
    assert observed_denied == frozenset(_DENIED_CASES)

    # Per-level structure, restated from the profile semantics rather than from
    # the decision function, so the two have to agree independently.
    security = auth.SECURITY_RESTRICTED_RESOURCES
    denied_requirements = {
        level: {actor.requirement for actor in observed_denied if actor.level == level}
        for level in ADMIN_ACCESS_LEVELS
    }
    governed = set(_GOVERNED_PAIRS)

    # admin_total holds "full" everywhere: it is denied nothing.
    assert denied_requirements["admin_total"] == set()

    # administrativo holds "none" on the security resources and "full" elsewhere.
    assert denied_requirements["administrativo"] == {
        requirement for requirement in governed if requirement.resource in security
    }

    # consultivo holds "none" on security, "edit" on meus_dados and "view" elsewhere.
    assert denied_requirements["consultivo"] == {
        requirement
        for requirement in governed
        if requirement.resource in security
        or (requirement.resource == "meus_dados" and requirement.scope == "full")
        or (
            requirement.resource not in security
            and requirement.resource != "meus_dados"
            and requirement.scope != "view"
        )
    }


# ---------------------------------------------------------------------------
# Part 5 — URL builder for dynamic governed routes
# ---------------------------------------------------------------------------

def test_dynamic_and_static_governed_requirements_partition_exactly():
    """Replaces ``dynamic combos == 53`` / ``dynamic rules == 43``.

    The two counts could both stay correct while a parameterised admin route was
    swapped for a static one.  The contract here is the exact identity subset:
    dynamic and static must partition the governed requirement set, every member
    must genuinely carry (or not carry) a converter, and the dynamic identities
    must still hash to the pinned set -- so a dynamic governed route cannot
    silently disappear.
    """
    requirements = rbac.requirement_identities(_CLASSIFICATION)
    dynamic = rbac.dynamic_requirement_identities(requirements)
    static = rbac.static_requirement_identities(requirements)

    assert rbac.dynamic_partition_violations(requirements, dynamic, static) == []
    assert dynamic, "the governed surface must still contain parameterised routes"
    assert (
        rbac.identities_digest(dynamic)
        == rbac.CANONICAL_DYNAMIC_REQUIREMENT_IDENTITIES_SHA256
    )


def test_every_dynamic_governed_route_still_generates_and_resolves():
    """Generation/resolution ownership for the parameterised governed surface.

    ``_build_url_for_governed`` builds the URL from the live Rule and asserts the
    URL matches back to that same Rule object, endpoint, method and arguments,
    so this also proves no dynamic governed route is shadowed by another rule.
    """
    requirements = rbac.requirement_identities(_CLASSIFICATION)
    dynamic = rbac.dynamic_requirement_identities(requirements)
    resolved = set()
    for requirement in sorted(dynamic):
        url, _ = _build_url_for_governed(
            requirement.rule, requirement.endpoint, requirement.method
        )
        assert not rbac.DYNAMIC_SEGMENT_RE.search(url), (
            f"built URL still holds a converter placeholder: {url} for {requirement}"
        )
        resolved.add(requirement)
    assert resolved == dynamic


def test_converter_unsupported_types_hard_fail():
    fake_instance = type("FakeConverter", (), {})()
    with pytest.raises(NotImplementedError) as exc:
        _converter_value(fake_instance, "x", endpoint="test_ep", rule_text="/test/<x>")
    msg = str(exc.value)
    assert "endpoint=test_ep" in msg, f"error missing endpoint: {msg}"
    assert "rule=/test/<x>" in msg, f"error missing rule: {msg}"
    assert "arg=x" in msg or "arg_name=x" in msg, f"error missing arg: {msg}"
    assert "FakeConverter" in msg, f"error missing class name: {msg}"


def test_converter_any_empty_items_hard_fail():
    real_any = AnyConverter(Map())
    assert len(real_any.items) == 0
    with pytest.raises(NotImplementedError) as exc:
        _converter_value(real_any, "x", endpoint="test_ep", rule_text="/test/<x>")
    msg = str(exc.value)
    assert "AnyConverter with empty items" in msg
    assert "endpoint=test_ep" in msg
    assert "rule=/test/<x>" in msg
    assert "arg=x" in msg


def test_converter_any_with_items():
    real_any = AnyConverter(Map(), "a", "b")
    assert len(real_any.items) > 0
    first = next(iter(real_any.items))
    assert _converter_value(real_any, "x") == first


def test_url_roundtrip(env):
    """Every baseline combination builds a URL that resolves back to itself.

    Replaces ``len(built) == 156``: the roundtrip set is compared to the exact
    combination identity set, so a route that stops building -- or one that
    builds but resolves to a *different* rule -- is caught by identity rather
    than by a total that a second, compensating change could restore.
    """
    baseline = _load_baseline()
    built = {}
    for entry in baseline["routes"]:
        rule_text = entry["rule"]
        endpoint = entry["endpoint"]
        for method in entry["methods"]:
            identity = rbac.Combination(rule_text, endpoint, method)
            url, _ = _build_url_for_governed(rule_text, endpoint, method)
            assert identity not in built, f"combination built twice: {identity}"
            built[identity] = url
    assert frozenset(built) == rbac.combination_identities(_CLASSIFICATION)


def test_live_governed_converters_are_int_and_string_only(env):
    seen_types = set()
    for rule_text, endpoint, method, res, scope in _GOVERNED_PAIRS:
        rule = _find_live_rule(rule_text, endpoint)
        if not rule.arguments:
            continue
        for arg in rule.arguments:
            conv = rule._converters.get(arg)
            if conv is not None:
                seen_types.add(type(conv).__name__)
    assert "IntegerConverter" in seen_types
    assert seen_types <= {"IntegerConverter", "UnicodeConverter"}, (
        f"Unexpected converters: {seen_types - {'IntegerConverter', 'UnicodeConverter'}}"
    )
    assert "FloatConverter" not in seen_types
    assert "PathConverter" not in seen_types
    assert "UUIDConverter" not in seen_types
    assert "AnyConverter" not in seen_types


# ---------------------------------------------------------------------------
# Part 6 — External governed callbacks
# ---------------------------------------------------------------------------

def test_external_governed_callbacks_derive_from_canonical():
    canonical = dict(auth.NON_ADMIN_RBAC_GOVERNED_ENDPOINTS)
    found: dict[str, set[str]] = {}
    for rule_text, endpoint, method, res, scope in _GOVERNED_PAIRS:
        is_admin_rule = rule_text == "/admin" or rule_text.startswith("/admin/")
        if not is_admin_rule:
            assert endpoint in canonical, (
                f"non-admin governed endpoint={endpoint} rule={rule_text} method={method} "
                f"not in NON_ADMIN_RBAC_GOVERNED_ENDPOINTS={set(canonical)}"
            )
            assert method in canonical[endpoint], (
                f"endpoint={endpoint} rule={rule_text} method={method} "
                f"not in canonical entry {canonical[endpoint]}"
            )
            assert res == "banco_dados", f"endpoint={endpoint}: expected banco_dados, got {res}"
            assert scope == "edit", f"endpoint={endpoint}: expected edit, got {scope}"
            found.setdefault(endpoint, set()).add(method)
    for ep, expected_methods in canonical.items():
        actual = found.get(ep, set())
        assert actual == set(expected_methods), (
            f"endpoint={ep}: expected governed methods {set(expected_methods)}, got {actual}"
        )
    assert len(found) == 3, f"external governed endpoints: {len(found)} expected 3, got {list(found.keys())}"


# ---------------------------------------------------------------------------
# Part 7 — Exclusion invariants
# ---------------------------------------------------------------------------

def test_no_automatic_options_selected():
    for cls in (
        _classify(e["rule"], e["endpoint"], m)
        for e in _load_baseline()["routes"]
        for m in e["methods"]
    ):
        assert cls.get("kind") != "automatic_options"


def test_no_unmatched_head_selected():
    for cls in (
        _classify(e["rule"], e["endpoint"], m)
        for e in _load_baseline()["routes"]
        for m in e["methods"]
    ):
        assert cls.get("method") != "HEAD"


def test_no_anonymous_selected():
    known_external = set(auth.NON_ADMIN_RBAC_GOVERNED_ENDPOINTS)
    for cls in (
        _classify(e["rule"], e["endpoint"], m)
        for e in _load_baseline()["routes"]
        for m in e["methods"]
    ):
        ep = cls.get("endpoint", "")
        rule = cls.get("rule", "")
        is_admin_url = rule == "/admin" or rule.startswith("/admin/")
        if not is_admin_url and ep not in known_external:
            assert not cls["governed"], f"non-admin URL endpoint={ep} rule={rule} classified as governed"


def test_no_aluno_routes_selected():
    for cls in (
        _classify(e["rule"], e["endpoint"], m)
        for e in _load_baseline()["routes"]
        for m in e["methods"]
    ):
        ep = cls.get("endpoint", "")
        if ep.startswith("aluno"):
            assert not cls["governed"], f"aluno endpoint={ep} classified as governed"


def test_no_exemptions_selected():
    for cls in (
        _classify(e["rule"], e["endpoint"], m)
        for e in _load_baseline()["routes"]
        for m in e["methods"]
    ):
        assert cls.get("kind") != "exemption"


# ---------------------------------------------------------------------------
# Part 8 — Filesystem path isolation
# ---------------------------------------------------------------------------

def test_filesystem_paths_are_under_tmp_path(env):
    tmp_parent = env["db_path"].resolve().parent
    for key in ("db_path", "uploads_path", "documents_path", "local_backups_path", "cloud_backups_path"):
        p = Path(env[key]).resolve()
        assert tmp_parent in p.parents or p.parent == tmp_parent, (
            f"{key}={p} not under tmp_path={tmp_parent}"
        )


def test_fingerprint_db_path_resolution(env):
    resolved_main = Path(main.DATABASE).resolve()
    resolved_fixture = Path(env["db_path"]).resolve()
    assert resolved_main == resolved_fixture, (
        f"main.DATABASE resolved {resolved_main} != fixture db_path {resolved_fixture}"
    )
    assert main.app.config["DATABASE_PATH"] == main.DATABASE, (
        f"app DATABASE_PATH={main.app.config['DATABASE_PATH']} != main.DATABASE={main.DATABASE}"
    )
    with main.app.app_context():
        conn = main.get_db_connection()
        db_file = conn.execute("PRAGMA database_list").fetchone()
        assert db_file is not None
        assert Path(db_file["file"]).resolve() == resolved_main, (
            f"PRAGMA database_list file {Path(db_file['file']).resolve()} != {resolved_main}"
        )
        assert not conn.in_transaction


def test_fingerprint_in_transaction_invariant(env):
    fp = _capture_fingerprint(env)
    assert isinstance(fp, str) and len(fp) == 64, f"unexpected fingerprint format: {fp}"


# ---------------------------------------------------------------------------
# Part 9/10 — HTTP denial: browser and AJAX with sentinel and fingerprint
# ---------------------------------------------------------------------------

def _run_browser_denials(env):
    client = env["client"]
    ids = {l: _make_admin(l) for l in ADMIN_ACCESS_LEVELS}
    executed: set[rbac.ActorCase] = set()
    for idx, (rule_text, endpoint, method, resource, scope, level) in enumerate(_DENIED_CASES):
        user_id = ids[level]
        ctx = _case_context(endpoint, rule_text, method, level, resource, scope)
        url, _ = _build_url_for_governed(
            rule_text, endpoint, method, ctx=ctx
        )
        _login(client, user_id)
        _warm_access_context(user_id, level, env, ctx)
        fp_before = _capture_fingerprint(env, ctx)
        sentinel_func, sentinel_state = _make_sentinel(ctx)
        orig = _install_sentinel(main.app, endpoint, sentinel_func)
        assert orig is not None, f"browser: endpoint view function missing for {ctx}"
        try:
            resp = client.open(url, method=method)
            _assert_browser_denial(resp, ctx)
            assert not sentinel_state["raised"], f"browser: sentinel raised for {ctx}"
            executed.add(rbac.ActorCase(rule_text, endpoint, method, resource, scope, level))
        finally:
            _restore_view(main.app, endpoint, orig)
            _logout(client)
        assert main.app.view_functions[endpoint] is orig, f"browser: handler not restored for {ctx}"
        with main.app.app_context():
            conn = main.get_db_connection()
            assert not conn.in_transaction, f"browser: open transaction after request for {ctx}"
        fp_after = _capture_fingerprint(env, ctx)
        assert fp_before == fp_after, f"browser: fingerprint mismatch for {ctx}"
    _assert_denial_replay_is_complete(executed, "browser")


def _assert_denial_replay_is_complete(executed, label: str) -> None:
    """The replayed cases must be the canonical denial set, identity by identity.

    Replaces ``executed == 136``.  A count cannot tell "two actors stopped being
    denied and two new ones started" from "nothing changed"; set equality names
    the exact combination that gained access.
    """
    canonical = frozenset(_DENIED_CASES)
    executed = frozenset(executed)
    missing = sorted(canonical - executed)
    unexpected = sorted(executed - canonical)
    assert missing == [], f"{label}: canonical denial cases never replayed: {missing}"
    assert unexpected == [], f"{label}: replayed cases outside the denial set: {unexpected}"
    assert executed == canonical
    assert executed == rbac.denial_identities(rbac.actor_identities(_GOVERNED_PAIRS))


def test_browser_denial_covers_every_canonical_denial_case(env):
    _run_browser_denials(env)


def _restore_view(app, endpoint: str, original) -> None:
    if original is None:
        app.view_functions.pop(endpoint, None)
    else:
        app.view_functions[endpoint] = original


def _run_ajax_denials(env):
    client = env["client"]
    ids = {l: _make_admin(l) for l in ADMIN_ACCESS_LEVELS}
    executed: set[rbac.ActorCase] = set()
    for idx, (rule_text, endpoint, method, resource, scope, level) in enumerate(_DENIED_CASES):
        user_id = ids[level]
        ctx = _case_context(endpoint, rule_text, method, level, resource, scope)
        url, kwargs = _build_url_for_governed(
            rule_text, endpoint, method, case_idx=idx, ctx=ctx
        )
        _login(client, user_id)
        _warm_access_context(user_id, level, env, ctx)
        fp_before = _capture_fingerprint(env, ctx)
        sentinel_func, sentinel_state = _make_sentinel(ctx)
        orig = _install_sentinel(main.app, endpoint, sentinel_func)
        assert orig is not None, f"AJAX: endpoint view function missing for {ctx}"
        try:
            query_marker = f"query_r1_deny_{idx}"
            body_marker = f"body_r1_deny_{idx}"
            csrf_marker = f"csrf_r1_deny_{idx}"
            auth_marker = f"auth_r1_deny_{idx}"
            authorization_value = f"Bearer {auth_marker}"
            headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Authorization": authorization_value,
            }
            url_with_query = f"{url}?_marker={query_marker}"
            body = {"_body_marker": body_marker}
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                body["_csrf_token"] = csrf_marker
            resp = client.open(url_with_query, method=method, data=body, headers=headers)
            _assert_ajax_denial(resp, resource, scope, ctx)
            assert not sentinel_state["raised"], f"AJAX: sentinel raised for {ctx}"
            data = resp.get_json()
            raw = resp.get_data(as_text=True)
            sensitive = _sensitive_set(env)
            sensitive.extend(str(v) for v in kwargs.values())
            sensitive.extend(
                [query_marker, body_marker, auth_marker, authorization_value]
            )
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                sensitive.append(csrf_marker)
            _check_surface(
                json.dumps(data, ensure_ascii=False, sort_keys=True) if data else "",
                "serialized JSON", sensitive, ctx,
            )
            message = data.get("message", "") if data else ""
            _check_surface(str(message), "JSON message", sensitive, ctx)
            _check_surface(
                json.dumps(dict(resp.headers), ensure_ascii=False, sort_keys=True),
                "response headers", sensitive, ctx,
            )
            _check_surface(raw, "raw response body", sensitive, ctx)
            executed.add(rbac.ActorCase(rule_text, endpoint, method, resource, scope, level))
        finally:
            _restore_view(main.app, endpoint, orig)
            _logout(client)
        assert main.app.view_functions[endpoint] is orig, f"AJAX: handler not restored for {ctx}"
        with main.app.app_context():
            conn = main.get_db_connection()
            assert not conn.in_transaction, f"AJAX: open transaction after request for {ctx}"
        fp_after = _capture_fingerprint(env, ctx)
        assert fp_before == fp_after, f"AJAX: fingerprint mismatch for {ctx}"
    _assert_denial_replay_is_complete(executed, "AJAX")


def test_ajax_denial_covers_every_canonical_denial_case(env):
    _run_ajax_denials(env)


# ---------------------------------------------------------------------------
# Module-level fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def env(tmp_path):
    temp_log_dir = tmp_path / "logs"
    temp_log_dir.mkdir(parents=True, exist_ok=True)
    temp_log_file = temp_log_dir / "app.log"
    isolated_handlers: list[tuple[logging.Logger, list[logging.Handler]]] = []
    seen_ids = set()
    for logger_candidate in (logging.getLogger(), main.logger, main.app.logger):
        if logger_candidate is None or id(logger_candidate) in seen_ids:
            continue
        seen_ids.add(id(logger_candidate))
        orig_handlers = list(logger_candidate.handlers)
        file_handlers = [h for h in orig_handlers if isinstance(h, logging.FileHandler)]
        if file_handlers:
            for fh in file_handlers:
                logger_candidate.removeHandler(fh)
            new_handler = logging.FileHandler(str(temp_log_file), encoding="utf-8")
            new_handler.setFormatter(
                file_handlers[0].formatter or logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )
            logger_candidate.addHandler(new_handler)
            isolated_handlers.append((logger_candidate, orig_handlers, new_handler))
    try:
        with isolated_versioned_app_env(tmp_path, "ref0c_d_r1.db") as e:
            e["temp_log_path"] = temp_log_file
            yield e
    finally:
        for logger_candidate, orig_handlers, new_handler in reversed(isolated_handlers):
            logger_candidate.removeHandler(new_handler)
            new_handler.close()
            logger_candidate.handlers = list(orig_handlers)
