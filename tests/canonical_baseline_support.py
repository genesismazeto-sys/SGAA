"""UT-BR2-ABC: the single canonical owner for three cross-cutting baselines.

Three global truths are consumed by almost every blueprint-extraction suite:

* the ``utils.messages`` message catalog key set,
* the Flask URL contract (``tests/_artifacts/route_inventory_baseline.json``),
* the CSRF inventory snapshots (``tests/_artifacts/csrf_inventory_shadow_*.json``).

Historically each extraction suite froze its own *copy* of the corresponding
scalar (``assert len(catalog) == 556``, ``assert len(rules) == 128``,
``assert len(rows) == 77``, ``ROUTE_INVENTORY_BYTES = 20171``, ...).  Every
later extraction then had to edit dozens of unrelated magic numbers, so the
copies rotted into three mutually inconsistent eras while the real contracts
moved on to 554 catalog keys, 125 route entries and 74 CSRF rows.

This module is the ONLY place those global truths are declared.  Extraction
suites keep their own *local* semantic assertions -- blueprint ownership, owner
partitions, scanner coverage, retirement proofs, extraction deltas -- and
delegate the global totals here.

Every delegation is exact equality against a content digest, never a bare
count, so the consolidated control is strictly stronger than the scalars it
replaces: a single unauthorized added, removed, renamed or re-owned catalog
key / route / CSRF row still fails.  ``tests/test_ut_br2abc_canonical_baseline_
governance.py`` carries the mutation probes that prove it.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = Path(__file__).resolve().parent / "_artifacts"

BUSINESS_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _digest(lines) -> str:
    """Stable digest of an unordered identity collection."""
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# A. Message catalog -- named delta ledger
# ---------------------------------------------------------------------------
# The canonical count is never typed as a total: it is the arithmetic result of
# a ledger whose every term is a reviewed, documented product delta.  Adding a
# catalogued message means appending a named term here, in one place.
CATALOG_LEDGER: tuple[tuple[str, int], ...] = (
    ("FC-07 head: catalog state at the Arquivos service extraction", 526),
    ("FC-07..UT-17 legitimate net product delta", 19),
    (
        "UT-AM1 retired 'Selecione uma matriz para a turma.' "
        "(msg_4d8251747aafd60d) when the Turma Matrix became an optional default",
        -1,
    ),
    (
        "UT-AM2 explicit student Matrix assignment: 'Matriz academica' "
        "(msg_34c6fdd255ae0c6e) and 'Sem matriz' (msg_c52418de2740e169)",
        2,
    ),
    ("UT-TM1/UT-TM2 neutral Turma Matrix validation messages", 2),
    ("UT-MX3 StudentMatrixError default-text ownership", 6),
)

# Everything before the UT-MX3 term is MX3's exact parent state.
PARENT_CATALOG_COUNT = sum(delta for _term, delta in CATALOG_LEDGER[:-1])
CANONICAL_CATALOG_COUNT = sum(delta for _term, delta in CATALOG_LEDGER)

# FC-07 head reconciliation.  The FC-07 era *expected* 537 keys while the actual
# head was 526: an 11-key baseline debt this project keeps deliberately visible
# rather than papering over.  After every named product delta the residual is 2.
CATALOG_FC07_HEAD_ACTUAL = CATALOG_LEDGER[0][1]
CATALOG_FC07_NET_PRODUCT_DELTA = CATALOG_LEDGER[1][1]
CATALOG_FC07_HEAD_EXPECTED = 537
CATALOG_VISIBLE_BASELINE_DEBT = (
    CATALOG_FC07_HEAD_EXPECTED + CATALOG_FC07_NET_PRODUCT_DELTA
) - CANONICAL_CATALOG_COUNT

# Key-set digests.  The parent digest is UT-MX3's frozen pre-candidate state;
# the canonical digest governs the live catalog and is what makes
# ``CANONICAL_CATALOG_COUNT`` unable to drift independently of the real keys.
PARENT_CATALOG_KEYS_SHA256 = (
    "f5dc176c0e574f969f566007ad05a867dc4362b4d51787a70844775136d44265"
)
CANONICAL_CATALOG_KEYS_SHA256 = (
    "373c712ec17f00d4bef29dfdf018f40a22a4e3f1befe0bfe1b8737ce680f67a6"
)


def catalog_keys_digest(keys) -> str:
    """Digest of a catalog key set, comparable with the frozen SHA constants."""
    return _digest(keys)


def canonical_message_catalog(*, fresh: bool = True) -> dict:
    """Return the live message catalog, by default past the lru_cache."""
    from utils import messages

    if fresh:
        messages._message_catalog.cache_clear()
    return messages._message_catalog()


def assert_catalog_matches_canonical_baseline(catalog=None, *, context: str = "") -> dict:
    """Assert the message catalog is exactly the canonical key set.

    Replaces the per-suite ``assert len(catalog) == <frozen scalar>`` copies.
    Exact-equality on the key-set digest means an unauthorized addition,
    removal or key rename fails -- which the frozen count could not detect for
    a same-size swap.
    """
    if catalog is None:
        catalog = canonical_message_catalog(fresh=False)
    keys = set(catalog)
    where = f" [{context}]" if context else ""
    assert len(keys) == CANONICAL_CATALOG_COUNT, (
        f"message catalog must stay exactly {CANONICAL_CATALOG_COUNT} keys"
        f"{where}; got {len(keys)}. The canonical count is the "
        "tests/canonical_baseline_support.py CATALOG_LEDGER sum -- append a "
        "named term there instead of editing a per-suite scalar."
    )
    observed = catalog_keys_digest(keys)
    assert observed == CANONICAL_CATALOG_KEYS_SHA256, (
        f"message catalog key set diverged from the canonical baseline{where}: "
        f"digest {observed} != {CANONICAL_CATALOG_KEYS_SHA256}. The count is "
        "unchanged, so a key was renamed or swapped."
    )
    return catalog


# ---------------------------------------------------------------------------
# B. Route inventory -- delegated to the versioned artifact owner guard
# ---------------------------------------------------------------------------
ROUTE_INVENTORY_ARTIFACT = ARTIFACTS_DIR / "route_inventory_baseline.json"


def load_route_inventory_baseline() -> dict:
    return json.loads(ROUTE_INVENTORY_ARTIFACT.read_text(encoding="utf-8"))


def route_identities(routes) -> frozenset[tuple[str, str, tuple[str, ...]]]:
    """(rule, endpoint, methods) identities for artifact-shaped route entries."""
    return frozenset(
        (entry["rule"], entry["endpoint"], tuple(entry["methods"])) for entry in routes
    )


def _route_identity_lines(identities) -> list[str]:
    return [f"{rule}\t{endpoint}\t{','.join(methods)}" for rule, endpoint, methods in identities]


def route_identities_digest(identities) -> str:
    return _digest(_route_identity_lines(identities))


CANONICAL_ROUTE_IDENTITIES = route_identities(load_route_inventory_baseline()["routes"])
CANONICAL_ROUTE_ENTRY_COUNT = len(CANONICAL_ROUTE_IDENTITIES)
CANONICAL_ROUTE_ENDPOINT_COUNT = len(
    {endpoint for _rule, endpoint, _methods in CANONICAL_ROUTE_IDENTITIES}
)
CANONICAL_ROUTE_RULE_COUNT = len(
    {rule for rule, _endpoint, _methods in CANONICAL_ROUTE_IDENTITIES}
)
# Independent pin on the artifact itself.  Without it the derived counts above
# would follow any edit of the JSON; with it, a deliberate URL-contract change
# has to be declared here, exactly once, on top of regenerating the artifact.
CANONICAL_ROUTE_IDENTITIES_SHA256 = (
    "7ba3d5001c50e264db60f5ef2c368d8dce28234e6218d24a81a4ccb492ec1255"
)


def _route_diff(expected, actual) -> str:
    return "".join(
        difflib.unified_diff(
            sorted(_route_identity_lines(expected)),
            sorted(_route_identity_lines(actual)),
            fromfile="expected/route_inventory_baseline.json",
            tofile="actual/live-url-map",
            lineterm="",
            n=1,
        )
    )


def assert_route_inventory_artifact_is_canonical(data=None, *, context: str = "") -> dict:
    """Assert the versioned route artifact is the declared canonical contract."""
    if data is None:
        data = load_route_inventory_baseline()
    where = f" [{context}]" if context else ""
    assert data["schema_version"] == 1, f"route artifact schema_version{where}"
    assert data["generated_from"] == "main.app.url_map", (
        f"route artifact generated_from{where}"
    )
    identities = route_identities(data["routes"])
    assert len(data["routes"]) == CANONICAL_ROUTE_ENTRY_COUNT == len(identities), (
        f"route artifact must hold exactly {CANONICAL_ROUTE_ENTRY_COUNT} unique "
        f"entries{where}; got {len(data['routes'])}"
    )
    observed = route_identities_digest(identities)
    assert observed == CANONICAL_ROUTE_IDENTITIES_SHA256, (
        f"route artifact diverged from the canonical URL contract{where}: "
        f"digest {observed} != {CANONICAL_ROUTE_IDENTITIES_SHA256}\n"
        + _route_diff(CANONICAL_ROUTE_IDENTITIES, identities)
    )
    return data


def assert_live_route_inventory_matches_canonical_baseline(*, context: str = ""):
    """Delegate global URL-contract truth to the canonical owner guard.

    Reuses ``test_route_inventory_snapshot.build_route_inventory`` so there is
    exactly one definition of "the live inventory", then pins the artifact
    itself.  Together this detects a deleted route, an added route and a changed
    rule/endpoint/method pairing -- the three things the per-suite scalar counts
    were standing in for.

    The artifact declares ``generated_from = "main.app.url_map"``, so the
    canonical inventory is defined for ``main.app`` only; there is deliberately
    no ``app`` parameter to silently accept some other application.
    """
    from tests.test_route_inventory_snapshot import build_route_inventory

    where = f" [{context}]" if context else ""
    expected = assert_route_inventory_artifact_is_canonical(context=context)
    actual = build_route_inventory()
    assert actual == expected, (
        f"live URL map diverged from the versioned route baseline{where}:\n"
        + _route_diff(route_identities(expected["routes"]), route_identities(actual["routes"]))
    )
    return actual


def assert_live_route_surface_matches_canonical_baseline(app=None, *, context: str = ""):
    """Route inventory equality plus the live endpoint-registry projection.

    Replaces the ``len(rules) == 128`` / ``len(view_functions) == 127`` pairs.
    Both projections are derived from the canonical artifact, so they cannot
    disagree with it.  ``app`` may be passed for readability at the call site but
    must be ``main.app``, the only application the canonical artifact describes.
    """
    import main

    if app is None:
        app = main.app
    assert app is main.app, (
        "the canonical route inventory is defined for main.app only"
    )
    where = f" [{context}]" if context else ""
    assert_live_route_inventory_matches_canonical_baseline(context=context)
    rules = list(app.url_map.iter_rules())
    assert len(rules) == CANONICAL_ROUTE_ENTRY_COUNT, (
        f"live url_map must hold exactly {CANONICAL_ROUTE_ENTRY_COUNT} rules"
        f"{where}; got {len(rules)}"
    )
    assert len(app.view_functions) == CANONICAL_ROUTE_ENDPOINT_COUNT, (
        f"live view_functions must hold exactly {CANONICAL_ROUTE_ENDPOINT_COUNT} "
        f"endpoints{where}; got {len(app.view_functions)}"
    )
    return rules


# ---------------------------------------------------------------------------
# C. CSRF inventory snapshots -- owner partitions over one canonical row set
# ---------------------------------------------------------------------------
CSRF_OFF_ARTIFACT = ARTIFACTS_DIR / "csrf_inventory_shadow_off.json"
CSRF_ON_ARTIFACT = ARTIFACTS_DIR / "csrf_inventory_shadow_on.json"
CANONICAL_CSRF_ARTIFACTS = (CSRF_OFF_ARTIFACT, CSRF_ON_ARTIFACT)

CSRF_SUMMARY_KEYS = frozenset(
    {"total_mutating_routes", "status_counts", "high_risk_routes", "page_statuses"}
)


def load_csrf_snapshot(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def csrf_row_identities(rows) -> frozenset[tuple[str, str, str]]:
    """(route, method, view_function) -- protection surface plus its owner."""
    return frozenset(
        (row["route"], row["method"], row["view_function"]) for row in rows
    )


def _csrf_identity_lines(identities) -> list[str]:
    return [f"{route}\t{method}\t{owner}" for route, method, owner in identities]


def csrf_row_identities_digest(identities) -> str:
    return _digest(_csrf_identity_lines(identities))


def csrf_owner_partitions(rows) -> dict[str, frozenset[tuple[str, str, str]]]:
    """Partition canonical rows by the owning module of their view function."""
    partitions: dict[str, set] = {}
    for row in rows:
        owner_module = row["view_function"].rsplit(".", 1)[0]
        partitions.setdefault(owner_module, set()).add(
            (row["route"], row["method"], row["view_function"])
        )
    return {module: frozenset(members) for module, members in partitions.items()}


CANONICAL_CSRF_ROWS = tuple(load_csrf_snapshot(CSRF_OFF_ARTIFACT)["rows"])
CANONICAL_CSRF_ROW_IDENTITIES = csrf_row_identities(CANONICAL_CSRF_ROWS)
CANONICAL_CSRF_ROW_COUNT = len(CANONICAL_CSRF_ROW_IDENTITIES)
CANONICAL_CSRF_PAGE_STATUS_COUNT = len(
    load_csrf_snapshot(CSRF_OFF_ARTIFACT)["summary"]["page_statuses"]
)
# Independent pin, same rationale as CANONICAL_ROUTE_IDENTITIES_SHA256: the
# derived counts follow the artifact, this digest anchors the artifact.
CANONICAL_CSRF_ROW_IDENTITIES_SHA256 = (
    "cafdbcb780647f22f0766cf3a32d75833a51dc0f9383baa7a8c904ddae4b557f"
)
# Named owner partitions of the canonical row set.  Every extraction that moved
# handlers out of ``main`` is visible here as its own term; the terms are
# disjoint and sum to CANONICAL_CSRF_ROW_COUNT.
CANONICAL_CSRF_OWNER_PARTITIONS: dict[str, int] = {
    "app.views.admin.acesso": 5,
    "app.views.admin.alertas": 3,
    "app.views.admin.alunos_turmas_cursos": 11,
    "app.views.admin.arquivos": 3,
    "app.views.admin.atividades": 14,
    "app.views.admin.banco_dados": 11,
    "app.views.admin.matrizes": 5,
    "app.views.admin.meus_dados": 1,
    "app.views.admin.reportes": 2,
    "app.views.admin.requisicoes": 5,
    "app.views.aluno": 5,
    "app.views.core": 2,
    "main": 6,
    "presets_api": 1,
}


# Named retirement ledger.  Suites that reconcile a historical PHASE-4-era
# snapshot (``git show <baseline>:tests/_artifacts/csrf_inventory_*.json``)
# against the canonical snapshot must subtract exactly these retirements -- and
# nothing else -- before comparing row-for-row.  Declared once here so the three
# suites that perform that reconciliation cannot drift apart again.
NORMAS_DOMAIN_RETIRED_ROUTES = frozenset({"/admin/normas-atividade/nova"})
NORMAS_DOMAIN_RETIRED_CSRF_PAGES = frozenset(
    {"/admin/normas-atividade", "/admin/normas-atividade/nova"}
)
# The Matrix version surface retirement removed three mutating routes; the
# historical snapshot counted them in ``total_mutating_routes`` and in two
# status buckets, so those projections are corrected by the same ledger.
MATRIX_VERSION_SURFACE_RETIRED_ROUTES = frozenset(
    {
        "/admin/matrizes/<int:matriz_id>/atividades/nova/<string:active_tab>",
        "/admin/matrizes/<int:matriz_id>/versoes/definir",
        "/admin/matrizes/<int:matriz_id>/versoes/remover",
    }
)
MATRIX_VERSION_SURFACE_RETIRED_CSRF_PAGES = frozenset(
    {"/admin/matrizes/1/versoes", "/admin/catalogo-versoes"}
)
MATRIX_VERSION_SURFACE_RETIRED_STATUS_COUNTS = {
    "ok_rendered_form_token": 2,
    "ok_specific_regression_test": 1,
}

RETIRED_CSRF_ROUTES = (
    NORMAS_DOMAIN_RETIRED_ROUTES | MATRIX_VERSION_SURFACE_RETIRED_ROUTES
)
RETIRED_CSRF_PAGES = (
    NORMAS_DOMAIN_RETIRED_CSRF_PAGES | MATRIX_VERSION_SURFACE_RETIRED_CSRF_PAGES
)


def reconcile_historical_csrf_snapshot(snapshot: dict) -> dict:
    """Subtract the named retirement ledger from a pre-retirement era snapshot.

    Mutates and returns ``snapshot`` so the caller can then compare it row-for-row
    against the canonical one.  ``/admin/mapeamento-legado`` is deliberately left
    in place: each suite's own summary reconciliation asserts that exactly one
    such retired page is present, which is its local retirement proof.
    """
    snapshot["rows"] = [
        row for row in snapshot["rows"] if row["route"] not in RETIRED_CSRF_ROUTES
    ]
    summary = snapshot["summary"]
    summary["page_statuses"] = [
        page for page in summary["page_statuses"] if page["path"] not in RETIRED_CSRF_PAGES
    ]
    summary["total_mutating_routes"] -= len(MATRIX_VERSION_SURFACE_RETIRED_ROUTES)
    for status, retired in MATRIX_VERSION_SURFACE_RETIRED_STATUS_COUNTS.items():
        summary["status_counts"][status] -= retired
    return snapshot


def _csrf_diff(expected, actual) -> str:
    return "".join(
        difflib.unified_diff(
            sorted(_csrf_identity_lines(expected)),
            sorted(_csrf_identity_lines(actual)),
            fromfile="expected/canonical-csrf-rows",
            tofile="actual/csrf-rows",
            lineterm="",
            n=1,
        )
    )


def assert_csrf_snapshot_matches_canonical_baseline(snapshot, *, context: str = ""):
    """Assert a CSRF snapshot is exactly the canonical protection inventory.

    Replaces the per-suite ``assert len(rows) == 77``.  Row identities carry the
    owner, so this detects a disappearing protected row, an undeclared new one
    and a silent re-owning -- none of which a row count could discriminate.
    """
    rows = snapshot["rows"] if isinstance(snapshot, dict) else list(snapshot)
    where = f" [{context}]" if context else ""
    identities = csrf_row_identities(rows)
    assert len(rows) == CANONICAL_CSRF_ROW_COUNT == len(identities), (
        f"CSRF snapshot must hold exactly {CANONICAL_CSRF_ROW_COUNT} unique "
        f"protected rows{where}; got {len(rows)} ({len(identities)} unique)"
    )
    observed = csrf_row_identities_digest(identities)
    assert observed == CANONICAL_CSRF_ROW_IDENTITIES_SHA256, (
        f"CSRF protection inventory diverged from the canonical snapshot{where}: "
        f"digest {observed} != {CANONICAL_CSRF_ROW_IDENTITIES_SHA256}\n"
        + _csrf_diff(CANONICAL_CSRF_ROW_IDENTITIES, identities)
    )
    if isinstance(snapshot, dict) and "summary" in snapshot:
        summary = snapshot["summary"]
        assert set(summary) == set(CSRF_SUMMARY_KEYS), (
            f"CSRF snapshot summary shape{where}: {sorted(summary)}"
        )
        assert len(summary["page_statuses"]) == CANONICAL_CSRF_PAGE_STATUS_COUNT, (
            f"CSRF snapshot must keep exactly {CANONICAL_CSRF_PAGE_STATUS_COUNT} "
            f"page statuses{where}; got {len(summary['page_statuses'])}"
        )
    return rows


def assert_csrf_owner_partitions_reconstruct_canonical(rows, *, context: str = ""):
    """Named owner partitions: disjoint, exactly sized, union == canonical set."""
    where = f" [{context}]" if context else ""
    partitions = csrf_owner_partitions(rows)
    assert {
        module: len(members) for module, members in partitions.items()
    } == CANONICAL_CSRF_OWNER_PARTITIONS, (
        f"CSRF owner partition sizes diverged{where}: "
        f"{ {m: len(v) for m, v in sorted(partitions.items())} }"
    )
    union: set = set()
    for module, members in partitions.items():
        overlap = union & members
        assert not overlap, f"owner partitions must stay disjoint{where}: {module} {overlap}"
        union |= members
    assert union == CANONICAL_CSRF_ROW_IDENTITIES, (
        f"owner partitions must reconstruct the canonical row set{where}\n"
        + _csrf_diff(CANONICAL_CSRF_ROW_IDENTITIES, union)
    )
    assert sum(CANONICAL_CSRF_OWNER_PARTITIONS.values()) == CANONICAL_CSRF_ROW_COUNT, (
        "the named owner ledger must sum to the canonical row count"
    )
    return partitions
