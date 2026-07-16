"""Route contract snapshot for the current Flask URL map.

Deliberate baseline update command (PowerShell):
    $env:SGAA_UPDATE_ROUTE_INVENTORY_BASELINE = "1"
    .venv\\Scripts\\python.exe -m pytest tests/test_route_inventory_snapshot.py -q
    Remove-Item Env:SGAA_UPDATE_ROUTE_INVENTORY_BASELINE
"""

import difflib
import json
import os
from pathlib import Path

import main


ARTIFACT_PATH = Path(__file__).parent / "_artifacts" / "route_inventory_baseline.json"
BUSINESS_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
UPDATE_ENVIRONMENT_VARIABLE = "SGAA_UPDATE_ROUTE_INVENTORY_BASELINE"


def build_route_inventory() -> dict:
    """Return the deterministic URL contract from the live Flask map."""
    routes = []
    for rule in main.app.url_map.iter_rules():
        routes.append(
            {
                "rule": rule.rule,
                "endpoint": rule.endpoint,
                "methods": sorted(set(rule.methods or ()) & BUSINESS_METHODS),
            }
        )
    routes.sort(key=lambda item: (item["rule"], item["endpoint"], item["methods"]))
    return {
        "schema_version": 1,
        "generated_from": "main.app.url_map",
        "routes": routes,
    }


def _serialize(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _baseline_diff(expected: dict, actual: dict) -> str:
    return "".join(
        difflib.unified_diff(
            _serialize(expected).splitlines(keepends=True),
            _serialize(actual).splitlines(keepends=True),
            fromfile=f"expected/{ARTIFACT_PATH.name}",
            tofile="actual/main.app.url_map",
        )
    )


def test_route_inventory_matches_versioned_baseline():
    """Normal execution is read-only; only the explicit environment flag writes."""
    actual = build_route_inventory()
    if os.environ.get(UPDATE_ENVIRONMENT_VARIABLE) == "1":
        ARTIFACT_PATH.write_text(_serialize(actual), encoding="utf-8")

    expected = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    assert actual == expected, _baseline_diff(expected, actual)
