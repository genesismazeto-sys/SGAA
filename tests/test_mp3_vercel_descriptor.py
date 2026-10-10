# coding: utf-8
"""MP-3 slice 2: the Vercel descriptor files describe what the code actually is -- no network.

``vercel.json`` is configuration the platform interprets; a typo in an
entrypoint or a cron path is a production fault no unit test would otherwise
see.  These tests tie the descriptor to the code it names: the entrypoints
exist, the scheduler rewrite and cron point at the scheduler's own route, the
cadence is one the Hobby plan accepts, and the ignore list covers the data a
working tree holds.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from app.storage import scheduler
from tools import deploy_audit

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))


def _defines(path: Path, name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return True
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return True
    return False


def test_the_web_service_names_the_full_application_entrypoint():
    web = DESCRIPTOR["services"]["web"]
    assert web["entrypoint"] == "main:app"
    assert _defines(ROOT / "main.py", "app")


def test_the_scheduler_is_its_own_service_with_the_scheduler_front_as_entrypoint():
    front = DESCRIPTOR["services"]["scheduler"]
    assert front["entrypoint"] == "app.storage.scheduler:application"
    assert _defines(ROOT / "app" / "storage" / "scheduler.py", "application")
    # The web entrypoint never reaches the scheduler module (MP-1 I3 / MP-2 D6).
    assert DESCRIPTOR["services"]["web"]["entrypoint"].split(":")[0] != "app.storage.scheduler"


def test_the_scheduler_route_is_rewritten_before_the_catch_all_and_to_the_scheduler_service():
    rewrites = DESCRIPTOR["rewrites"]
    sources = [rule["source"] for rule in rewrites]
    prefix = scheduler.ROUTE_MIRROR.rsplit("/", 1)[0]
    scheduler_rules = [i for i, rule in enumerate(rewrites) if rule["destination"] == {"service": "scheduler"}]
    catch_all = [i for i, source in enumerate(sources) if source == "/(.*)"]
    assert len(scheduler_rules) == 1 and len(catch_all) == 1 and scheduler_rules[0] < catch_all[0]
    assert re.fullmatch(rewrites[scheduler_rules[0]]["source"], scheduler.ROUTE_MIRROR)
    assert rewrites[scheduler_rules[0]]["source"].startswith(prefix)
    assert rewrites[catch_all[0]]["destination"] == {"service": "web"}


def test_the_cron_targets_the_scheduler_route_at_most_once_a_day():
    crons = DESCRIPTOR["crons"]
    assert [cron["path"] for cron in crons] == [scheduler.ROUTE_MIRROR]
    for cron in crons:
        minute, hour, day, month, weekday = cron["schedule"].split()
        # Hobby: an expression that would run more than once a day fails the deployment.
        assert minute.isdigit() and hour.isdigit() and day == month == weekday == "*"


def test_function_durations_fit_the_hobby_ceiling():
    for service in DESCRIPTOR["services"].values():
        for config in service.get("functions", {}).values():
            assert config["maxDuration"] <= 300


def test_response_headers_have_one_owner_the_application():
    """The application already emits the security headers and a default CSP
    (``app/__init__.py::_apply_security_headers``); a second declaration at the edge
    would be a conflicting copy of the same fact."""
    assert "headers" not in DESCRIPTOR
    source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8-sig")
    for header in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Strict-Transport-Security",
                   "Content-Security-Policy"):
        assert header in source


def test_the_python_version_is_the_qualified_minor():
    assert (ROOT / ".python-version").read_text().strip() == "3.12"


def test_the_ignore_file_covers_the_data_a_working_tree_holds():
    patterns = {line.strip() for line in (ROOT / ".vercelignore").read_text().splitlines()
                if line.strip() and not line.startswith("#")}
    assert {".env", "*.db", "*.db-wal", "uploads/", "documentos_alunos/", "logs/", ".git/"} <= patterns


def test_the_descriptor_files_are_on_the_export_allowlist_and_carry_no_secret_shape(tmp_path):
    names = {"vercel.json", ".python-version", ".vercelignore"}
    assert names <= set(deploy_audit.RUNTIME_ALLOWLIST)
    for name in names:
        shutil_target = tmp_path / name
        shutil_target.write_bytes((ROOT / name).read_bytes())
    assert deploy_audit.audit(tmp_path)["findings"] == []


@pytest.mark.parametrize("key", ["functions", "buildCommand", "installCommand", "outputDirectory"])
def test_build_and_runtime_keys_are_not_at_the_top_level_in_services_mode(key):
    # Vercel: with `services` present these belong to a service, where their owner is unambiguous.
    assert key not in DESCRIPTOR
