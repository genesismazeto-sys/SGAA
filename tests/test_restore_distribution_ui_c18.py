"""UI-C18: a database restore reaches every backup destination independently.

``_restore_database_from_source`` used to upload to Google Drive / OneDrive only
the *legacy cloud-folder* snapshot, so with no "Pasta em nuvem" configured a
restore never reached any provider -- the same dependency UI-C11/C12 removed
from "Gerar backup agora" and ``run_backup_cycle``.

Now, after the restore, the restored database is snapshotted into a private
work dir (never the local backup series, so retention cannot trade the
pre-restore safety snapshot for it) and handed to the shared
``_distribute_snapshot``: pasta em nuvem, Google, OneDrive, then local
retention, each independent. A distribution failure never undoes the restore.
The user-facing messages are unchanged (they only ever described the local
safety snapshot). All provider calls are test doubles.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from app.backup import orchestrator
from app.db_maintenance import create_database_snapshot
from tests.test_backup_destination_outcomes_ui_c11_c12 import (  # noqa: F401  (fixtures)
    admin_client,
    backup_env,
    events,
)

SUCCESS = "Banco restaurado com sucesso. Um snapshot de segurança da base anterior foi salvo localmente."


@pytest.fixture
def artifacts(events, monkeypatch):
    """Wrap the provider doubles: record whether the artifact existed at upload."""
    seen: list[tuple[str, str, bool]] = []
    for provider in ("google", "onedrive"):
        inner = getattr(orchestrator._cd, f"{provider}_upload")

        def wrapper(token, path, folder, _inner=inner, _provider=provider):
            seen.append((_provider, str(path), os.path.isfile(path)))
            return _inner(token, path, folder)

        monkeypatch.setattr(orchestrator._cd, f"{provider}_upload", wrapper)
    return seen


def _source_snapshot(env) -> dict:
    import app.db as app_db

    with env.main.app.app_context():
        return create_database_snapshot(app_db.DATABASE, str(env.local_dir), reason="manual-backup", origin="local")


def _flash(client):
    with client.session_transaction() as session:
        return list(session.get("_flashes", []))


def _restore(env, client):
    snapshot = _source_snapshot(env)
    response = client.post(
        "/admin/banco-dados/restaurar", data={"manifest_path": snapshot["manifest_path"]}, follow_redirects=False
    )
    assert response.status_code in (302, 303)
    return snapshot


def _reasons(directory: Path) -> list[str]:
    import json

    return sorted(json.load(open(p, encoding="utf-8")).get("reason") for p in (directory / "snapshots").glob("*.json"))


def _database_ok(env) -> bool:
    import app.db as app_db

    return sqlite3.connect(app_db.DATABASE).execute("PRAGMA quick_check").fetchone()[0] == "ok"


# ==========================================================================
# Destination matrix
# ==========================================================================


@pytest.mark.parametrize(
    "folder, google, onedrive, uploaded",
    [
        (False, False, False, []),                        # 1 no destinations
        (True, False, False, []),                         # 2 folder only
        (False, True, False, ["google"]),                 # 3/6 folder unset + Google
        (False, False, True, ["onedrive"]),               # 4/7 folder unset + OneDrive
        (False, True, True, ["google", "onedrive"]),      # 5 both providers
        (True, True, True, ["google", "onedrive"]),       # folder + both
    ],
)
def test_restore_distributes_to_each_selected_destination(
    backup_env, admin_client, events, artifacts, folder, google, onedrive, uploaded
):
    backup_env.configure(cloud_folder=folder, google=google, onedrive=onedrive)
    events.uploads.clear()
    events.log.clear()

    _restore(backup_env, admin_client)

    assert _flash(admin_client)[-1] == ("success", SUCCESS)
    assert [provider for provider, _path, _existed in artifacts] == uploaded
    for _provider, path, existed in artifacts:
        assert existed, "the provider received a path that did not exist"
        assert Path(path).parent.parent != backup_env.local_dir, "artifact must not join the local series"
        assert not os.path.exists(path), "the private distribution artifact must be cleaned up"
    folder_copies = list((backup_env.cloud_dir / "snapshots").glob("*.db"))
    assert bool(folder_copies) is folder
    assert "retention" in events.log
    assert _database_ok(backup_env)


def test_failing_folder_still_reaches_both_providers(backup_env, admin_client, events, artifacts):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    events.fail.add("folder")
    _restore(backup_env, admin_client)
    assert [p for p, _path, _e in artifacts] == ["google", "onedrive"]
    assert _flash(admin_client)[-1] == ("success", SUCCESS)


@pytest.mark.parametrize("failing, succeeding", [("google", "onedrive"), ("onedrive", "google")])
def test_one_provider_failing_does_not_stop_the_other(backup_env, admin_client, events, artifacts, failing, succeeding):
    backup_env.configure(cloud_folder=False, google=True, onedrive=True)
    events.fail.add(failing)
    _restore(backup_env, admin_client)
    assert [p for p, _path, _e in artifacts] == ["google", "onedrive"]
    assert events.remote_retention == [succeeding]
    assert _flash(admin_client)[-1] == ("success", SUCCESS)
    assert _database_ok(backup_env)


def test_distribution_failure_never_undoes_the_restore(backup_env, admin_client, events, monkeypatch):
    backup_env.configure(cloud_folder=False, google=True, onedrive=False)

    def broken(*_a, **_k):
        raise RuntimeError("distribuição indisponível")

    monkeypatch.setattr(orchestrator, "_distribute_snapshot", broken)
    _restore(backup_env, admin_client)
    assert _flash(admin_client)[-1] == ("success", SUCCESS)
    assert _database_ok(backup_env)


# ==========================================================================
# No distribution when the restore does not happen
# ==========================================================================


def test_validation_failure_distributes_nothing(backup_env, admin_client, events, artifacts):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    before = _reasons(backup_env.local_dir) if (backup_env.local_dir / "snapshots").exists() else []
    response = admin_client.post(
        "/admin/banco-dados/restaurar", data={"manifest_path": str(backup_env.local_dir / "nope.json")}
    )
    assert response.status_code in (302, 303)
    assert _flash(admin_client)[-1][0] == "error"
    assert artifacts == [] and "folder" not in events.log
    after = _reasons(backup_env.local_dir) if (backup_env.local_dir / "snapshots").exists() else []
    assert after == before, "no safety snapshot is taken for a refused restore"


def test_restore_failure_uploads_nothing(backup_env, admin_client, events, artifacts, monkeypatch):
    import app.views.admin.banco_dados as view

    backup_env.configure(cloud_folder=False, google=True, onedrive=True)
    snapshot = _source_snapshot(backup_env)

    def failing_restore(*_a, **_k):
        raise sqlite3.DatabaseError("arquivo corrompido")

    monkeypatch.setattr(view, "restore_database_snapshot", failing_restore)
    with open(snapshot["database_path"], "rb") as handle:
        response = admin_client.post(
            "/admin/banco-dados/restaurar/upload",
            data={"backup_file": (handle, "backup.db")},
            content_type="multipart/form-data",
        )
    assert response.status_code in (302, 303)
    assert _flash(admin_client)[-1][0] == "error"
    assert artifacts == []
    assert _database_ok(backup_env)


# ==========================================================================
# Retention
# ==========================================================================


def test_retention_keeps_the_pre_restore_safety_snapshot(backup_env, admin_client, events, artifacts):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    _restore(backup_env, admin_client)
    reasons = _reasons(backup_env.local_dir)
    assert "pre-restore-safety" in reasons
    assert "post-restore" not in reasons
    for manifest in (backup_env.local_dir / "snapshots").glob("*.json"):
        assert manifest.with_suffix(".db").exists()
