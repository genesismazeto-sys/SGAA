"""Characterize current admin RBAC policy debt without normalizing it away.

Deliberate baseline update command (PowerShell):
    $env:SGAA_UPDATE_RBAC_DEBT_BASELINE = "1"
    .venv\\Scripts\\python.exe -m pytest tests/test_rbac_requirement_coverage.py -q
    Remove-Item Env:SGAA_UPDATE_RBAC_DEBT_BASELINE
"""

import difflib
import json
import os
from pathlib import Path

import main


ARTIFACT_PATH = Path(__file__).parent / "_artifacts" / "rbac_unmapped_routes_baseline.json"
ADMIN_PATH_PREFIX = "/admin"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
UPDATE_ENVIRONMENT_VARIABLE = "SGAA_UPDATE_RBAC_DEBT_BASELINE"
TECHNICAL_REASON = (
    "Admin URL discovered from main.app.url_map has no granular requirement: "
    "get_admin_permission_requirement(endpoint, method) returned None."
)


def _is_admin_path(rule: str) -> bool:
    return rule == ADMIN_PATH_PREFIX or rule.startswith(f"{ADMIN_PATH_PREFIX}/")


def build_unmapped_admin_route_inventory() -> dict:
    """Enumerate unmapped admin route/method pairs from URL paths, not endpoint names."""
    gaps = []
    for rule in main.app.url_map.iter_rules():
        if not _is_admin_path(rule.rule):
            continue
        for method in sorted(set(rule.methods or ()) & BUSINESS_METHODS):
            requirement = main.get_admin_permission_requirement(rule.endpoint, method)
            if requirement is None:
                gaps.append(
                    {
                        "url": rule.rule,
                        "endpoint": rule.endpoint,
                        "method": method,
                        "technical_reason": TECHNICAL_REASON,
                        "current_requirement": None,
                    }
                )
    gaps.sort(key=lambda item: (item["url"], item["endpoint"], item["method"]))
    return {
        "schema_version": 1,
        "generated_from": "main.app.url_map filtered by /admin path",
        "target_state": "lista vazia",
        "statement": (
            "Este baseline caracteriza dívida preexistente. O estado-alvo obrigatório "
            "é lista vazia. A existência do baseline não autoriza novas rotas sem política."
        ),
        "unmapped_routes": gaps,
    }


def _serialize(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _baseline_diff(expected: dict, actual: dict) -> str:
    return "".join(
        difflib.unified_diff(
            _serialize(expected).splitlines(keepends=True),
            _serialize(actual).splitlines(keepends=True),
            fromfile=f"expected/{ARTIFACT_PATH.name}",
            tofile="actual/admin-url-map-rbac-requirements",
        )
    )


def test_unmapped_admin_routes_match_versioned_debt_baseline():
    """The baseline changes only through the explicit update command above."""
    actual = build_unmapped_admin_route_inventory()
    if os.environ.get(UPDATE_ENVIRONMENT_VARIABLE) == "1":
        ARTIFACT_PATH.write_text(_serialize(actual), encoding="utf-8")

    expected = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    assert actual == expected, _baseline_diff(expected, actual)


def test_rbac_debt_source_is_the_admin_url_path():
    """Prevent endpoint-name heuristics from becoming the source of this inventory."""
    actual = build_unmapped_admin_route_inventory()
    assert all(_is_admin_path(item["url"]) for item in actual["unmapped_routes"])
