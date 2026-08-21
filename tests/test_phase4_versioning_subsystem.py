"""Canonical versioning subsystem contains no shadow-read lane."""
from pathlib import Path

import main
from app.auth import get_admin_permission_requirement
from app.views.admin import versioning


def test_versioning_blueprint_exposes_only_two_read_diagnostics():
    specs = versioning.LEGACY_ROUTE_SPECS
    assert len(specs) == 2
    assert all(spec.methods == ("GET",) for spec in specs)
    assert all(spec.endpoint in main.app.view_functions for spec in specs)


def test_versioning_diagnostics_keep_read_permission():
    for spec in versioning.LEGACY_ROUTE_SPECS:
        assert get_admin_permission_requirement(spec.endpoint, "GET") == ("atividades", "view")


def test_shadow_read_module_is_physically_absent():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "app" / "versioning" / "shadow_reads.py").exists()
    assert not any("shadow" in rule.rule or "shadow" in rule.endpoint for rule in main.app.url_map.iter_rules())


def test_versioning_modules_do_not_import_main():
    root = Path(__file__).resolve().parents[1] / "app" / "versioning"
    for path in root.glob("*.py"):
        assert "import main" not in path.read_text(encoding="utf-8")
