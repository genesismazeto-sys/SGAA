"""UI-C11 / UI-C12: backup destinations are independent and reported truthfully.

A backup has one prerequisite -- the local snapshot, because it is the artefact
every destination receives -- and then four independent destinations:

* the legacy "Pasta em nuvem" filesystem copy (only when configured);
* Google Drive and OneDrive (only when their "Incluir no backup automático"
  switch is on);
* the external server (manual route only, as before).

UI-C11: "Gerar backup agora" used to pick its message from the legacy folder
step alone, before the providers even ran, so a backup that reached Google
Drive and OneDrive was announced as "adiada ou não detectou mudanças".

UI-C12: ``run_backup_cycle`` only reached the providers when the legacy folder
sync succeeded and was not skipped, so with no folder configured the automatic
cycle never uploaded anywhere, whatever the switches said.

Every provider call below is a test double: no network, no real upload.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.backup import orchestrator
from app.cloud_connections import CloudConnectionError
from tests.root_admin_test_config import TEST_ROOT_ADMIN_EMAIL

STALE_WORDS = ("adiada", "mudanças")


# ---------------------------------------------------------------------------
# Environment: private database, backup directories under tmp_path
# ---------------------------------------------------------------------------


@pytest.fixture
def backup_env(tmp_path):
    """Isolated app whose effective backup settings live only under tmp_path.

    Same order-independence sequence as UT-5's ``isolated_admin_client``:
    bootstrap the private database first, then install and persist this
    test's paths, and restore every touched config key afterwards.
    """
    import main
    from tests.versioned_test_support import isolated_versioned_app_env

    local_dir = tmp_path / "local"
    cloud_dir = tmp_path / "cloud"
    local_dir.mkdir(parents=True, exist_ok=True)
    cloud_dir.mkdir(parents=True, exist_ok=True)
    guarded = (
        "TESTING",
        "LOCAL_BACKUP_DIR",
        "CLOUD_BACKUP_DIR",
        "CLOUD_SYNC_INTERVAL_SECONDS",
        "EXTERNAL_BACKUP_URL",
        "EXTERNAL_BACKUP_TOKEN",
        "EXTERNAL_BACKUP_ENABLED",
    )

    with isolated_versioned_app_env(tmp_path, "ui_c11_c12_backup.db"):
        original = {key: main.app.config.get(key) for key in guarded}
        main.app.config["TESTING"] = True
        main.app.config["LOCAL_BACKUP_DIR"] = str(local_dir)
        main.app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = 0

        def configure(*, cloud_folder: bool, google: bool, onedrive: bool) -> None:
            main.app.config["CLOUD_BACKUP_DIR"] = str(cloud_dir) if cloud_folder else ""
            with main.app.app_context():
                conn = main.get_db_connection()
                main.save_backup_settings(
                    conn,
                    {
                        "local_backup_dir": str(local_dir),
                        "cloud_backup_dir": str(cloud_dir) if cloud_folder else "",
                        "cloud_sync_interval_seconds": "0",
                        "external_backup_url": "",
                        "external_backup_token": "",
                        "external_backup_enabled": "0",
                    },
                )
                orchestrator._save_drive_config(
                    conn,
                    {
                        "gdrive_enabled": "1" if google else "0",
                        "onedrive_enabled": "1" if onedrive else "0",
                    },
                )
                conn.commit()

        class Env:
            pass

        env = Env()
        env.main = main
        env.local_dir = local_dir
        env.cloud_dir = cloud_dir
        env.configure = configure
        try:
            yield env
        finally:
            for key, value in original.items():
                main.app.config[key] = value


@pytest.fixture
def admin_client(backup_env):
    client = backup_env.main.app.test_client()
    response = client.post(
        "/login",
        data={"email": TEST_ROOT_ADMIN_EMAIL, "senha": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    return client


@pytest.fixture
def events(monkeypatch):
    """Provider doubles plus one ordered event log for every destination step."""

    class Recorder:
        def __init__(self):
            self.log: list[str] = []
            self.uploads: list[tuple[str, str]] = []
            self.remote_retention: list[str] = []
            self.fail: set[str] = set()

    recorder = Recorder()

    monkeypatch.setattr(
        orchestrator._cloud_connections,
        "get_authenticated_access_token",
        lambda conn, provider: (f"token-{provider}", f"dono+{provider}@example.invalid"),
    )

    def _upload(provider):
        def upload(token, path, folder):
            recorder.log.append(provider)
            recorder.uploads.append((provider, str(path)))
            if provider in recorder.fail:
                raise RuntimeError(f"{provider} indisponivel")
            return {"id": f"{provider}-file"}

        return upload

    monkeypatch.setattr(orchestrator._cd, "google_upload", _upload("google"))
    monkeypatch.setattr(orchestrator._cd, "onedrive_upload", _upload("onedrive"))

    def remote_retention(provider, **_kwargs):
        recorder.remote_retention.append(provider)
        return {"deleted": [], "errors": []}

    monkeypatch.setattr(orchestrator._cd, "apply_retention_to_drive", remote_retention)

    real_sync = orchestrator.maybe_sync_database_to_cloud

    def folder_sync(*args, **kwargs):
        recorder.log.append("folder")
        if "folder" in recorder.fail:
            raise OSError("pasta em nuvem indisponivel")
        return real_sync(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "maybe_sync_database_to_cloud", folder_sync)

    real_retention = orchestrator._run_retention_cleanup

    def local_retention(*args, **kwargs):
        recorder.log.append("retention")
        return real_retention(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "_run_retention_cleanup", local_retention)
    return recorder


def _flashes(client) -> list[tuple[str, str]]:
    with client.session_transaction() as session:
        return list(session.get("_flashes", []))


def _manual_backup(client) -> tuple[str, str]:
    response = client.post("/admin/banco-dados/backup", follow_redirects=False)
    assert response.status_code in (302, 303)
    flashes = _flashes(client)
    assert len(flashes) == 1, flashes
    category, message = flashes[0]
    for word in STALE_WORDS:
        assert word not in message, message
    return category, message


def _local_snapshots(env) -> list[Path]:
    return sorted((env.local_dir / "snapshots").glob("*.db"))


# ==========================================================================
# UI-C11 -- "Gerar backup agora": message chosen from every real outcome
# ==========================================================================


def test_local_only_says_so_without_claiming_deferral(backup_env, admin_client, events):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)

    category, message = _manual_backup(admin_client)

    assert (category, message) == (
        "info",
        "Backup local criado. Nenhum destino em nuvem está configurado para receber backups.",
    )
    assert events.uploads == []
    assert len(_local_snapshots(backup_env)) == 1


def test_local_plus_cloud_folder(backup_env, admin_client, events):
    backup_env.configure(cloud_folder=True, google=False, onedrive=False)

    assert _manual_backup(admin_client) == (
        "success",
        "Backup local criado e enviado para pasta em nuvem.",
    )
    assert sorted((backup_env.cloud_dir / "snapshots").glob("*.db"))


@pytest.mark.parametrize(
    "google, onedrive, expected",
    [
        (True, False, "Backup local criado e enviado para Google Drive."),
        (False, True, "Backup local criado e enviado para OneDrive."),
        (True, True, "Backup local criado e enviado para Google Drive e OneDrive."),
    ],
)
def test_providers_without_cloud_folder(backup_env, admin_client, events, google, onedrive, expected):
    """Folder not configured: providers still receive the local snapshot."""
    backup_env.configure(cloud_folder=False, google=google, onedrive=onedrive)

    assert _manual_backup(admin_client) == ("success", expected)
    (snapshot,) = _local_snapshots(backup_env)
    assert {path for _provider, path in events.uploads} == {str(snapshot)}
    assert [p for p, _ in events.uploads] == [
        p for p, on in (("google", google), ("onedrive", onedrive)) if on
    ]


def test_every_destination_listed_in_order(backup_env, admin_client, events):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)

    assert _manual_backup(admin_client) == (
        "success",
        "Backup local criado e enviado para pasta em nuvem, Google Drive e OneDrive.",
    )


def test_cloud_folder_failure_does_not_stop_google(backup_env, admin_client, events):
    backup_env.configure(cloud_folder=True, google=True, onedrive=False)
    events.fail.add("folder")

    assert _manual_backup(admin_client) == (
        "warning",
        "Backup local criado e enviado para Google Drive, mas o envio falhou para pasta em nuvem.",
    )
    assert [p for p, _ in events.uploads] == ["google"]


def test_google_failure_does_not_stop_onedrive(backup_env, admin_client, events):
    backup_env.configure(cloud_folder=False, google=True, onedrive=True)
    events.fail.add("google")

    assert _manual_backup(admin_client) == (
        "warning",
        "Backup local criado e enviado para OneDrive, mas o envio falhou para Google Drive.",
    )
    assert [p for p, _ in events.uploads] == ["google", "onedrive"]
    assert events.remote_retention == ["onedrive"]


def test_every_attempt_failing_still_reports_the_local_backup(backup_env, admin_client, events):
    backup_env.configure(cloud_folder=False, google=True, onedrive=True)
    events.fail.update({"google", "onedrive"})

    assert _manual_backup(admin_client) == (
        "warning",
        "Backup local criado, mas o envio falhou para Google Drive e OneDrive.",
    )
    assert len(_local_snapshots(backup_env)) == 1


def test_enabled_provider_without_app_credentials_is_not_reported_as_sent(
    backup_env, admin_client, events, monkeypatch
):
    backup_env.configure(cloud_folder=False, google=True, onedrive=False)

    def missing(conn, provider):
        raise CloudConnectionError("sem credenciais", debug_code="APPLICATION_CREDENTIALS_MISSING")

    monkeypatch.setattr(orchestrator._cloud_connections, "get_authenticated_access_token", missing)

    assert _manual_backup(admin_client) == (
        "info",
        "Backup local criado. Nenhum destino em nuvem está configurado para receber backups.",
    )
    assert events.uploads == []


def test_message_is_chosen_after_every_destination_and_retention(
    backup_env, admin_client, events, monkeypatch
):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    import app.views.admin.banco_dados as view

    real_flash = view.flash

    def flash_spy(message, category="message"):
        events.log.append("flash")
        return real_flash(message, category)

    monkeypatch.setattr(view, "flash", flash_spy)
    _manual_backup(admin_client)

    assert events.log == ["folder", "google", "onedrive", "retention", "flash"]


def test_fresh_local_snapshot_survives_retention_and_reaches_providers(
    backup_env, admin_client, events
):
    backup_env.configure(cloud_folder=False, google=True, onedrive=True)
    _manual_backup(admin_client)

    (snapshot,) = _local_snapshots(backup_env)
    assert snapshot.exists()
    assert sorted(events.remote_retention) == ["google", "onedrive"]


# ==========================================================================
# UI-C12 -- run_backup_cycle: providers independent of the legacy folder
# ==========================================================================


def _run_cycle(env, *, force=True):
    with env.main.app.app_context():
        conn = env.main.get_db_connection()
        return orchestrator.run_backup_cycle(force=force, conn=conn)


def _statuses(result) -> dict[str, str]:
    return {key: value["status"] for key, value in result["outcomes"].items()}


@pytest.mark.parametrize("folder", ["unset", "configured", "failing"])
@pytest.mark.parametrize(
    "google, onedrive",
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_automatic_cycle_honours_each_switch_whatever_the_folder(
    backup_env, events, folder, google, onedrive
):
    backup_env.configure(cloud_folder=folder != "unset", google=google, onedrive=onedrive)
    if folder == "failing":
        events.fail.add("folder")

    result = _run_cycle(backup_env)

    snapshot = Path(result["snapshot"]["database_path"])
    assert snapshot.parent == backup_env.local_dir / "snapshots"
    assert snapshot.exists(), "the cycle's own local snapshot must survive retention"
    assert [p for p, _ in events.uploads] == [
        p for p, on in (("google", google), ("onedrive", onedrive)) if on
    ]
    assert {path for _p, path in events.uploads} <= {str(snapshot)}

    statuses = _statuses(result)
    assert statuses["cloud_folder"] == {
        "unset": orchestrator.OUTCOME_NOT_CONFIGURED,
        "configured": orchestrator.OUTCOME_SUCCESS,
        "failing": orchestrator.OUTCOME_FAILED,
    }[folder]
    for provider, on in (("google", google), ("onedrive", onedrive)):
        assert statuses[provider] == (
            orchestrator.OUTCOME_SUCCESS if on else orchestrator.OUTCOME_NOT_ENABLED
        )


def test_google_failure_leaves_onedrive_running(backup_env, events):
    backup_env.configure(cloud_folder=False, google=True, onedrive=True)
    events.fail.add("google")

    statuses = _statuses(_run_cycle(backup_env))

    assert statuses["google"] == orchestrator.OUTCOME_FAILED
    assert statuses["onedrive"] == orchestrator.OUTCOME_SUCCESS
    assert events.remote_retention == ["onedrive"]


def test_onedrive_failure_leaves_google_result_intact(backup_env, events):
    backup_env.configure(cloud_folder=False, google=True, onedrive=True)
    events.fail.add("onedrive")

    statuses = _statuses(_run_cycle(backup_env))

    assert statuses["google"] == orchestrator.OUTCOME_SUCCESS
    assert statuses["onedrive"] == orchestrator.OUTCOME_FAILED
    assert events.remote_retention == ["google"]


@pytest.mark.parametrize(
    "folder_reason, expected",
    [("unchanged", "unchanged"), ("cooldown", "deferred")],
)
def test_folder_dedup_and_cooldown_stay_folder_only(
    backup_env, events, monkeypatch, folder_reason, expected
):
    """Only the folder has unchanged/deferred semantics; they never gate providers."""
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    monkeypatch.setattr(
        orchestrator,
        "maybe_sync_database_to_cloud",
        lambda *a, **k: {"ok": True, "skipped": True, "reason": folder_reason},
    )

    statuses = _statuses(_run_cycle(backup_env, force=False))

    assert statuses["cloud_folder"] == expected
    assert statuses["google"] == statuses["onedrive"] == orchestrator.OUTCOME_SUCCESS


def test_provider_bookkeeping_failure_after_upload_is_still_a_success(
    backup_env, events, monkeypatch
):
    """Once the provider holds the file, a local write error cannot unsend it."""
    backup_env.configure(cloud_folder=False, google=True, onedrive=False)
    real_save = orchestrator._save_drive_config

    def failing_save(conn, updates):
        if "gdrive_last_upload_at" in updates:
            raise RuntimeError("configuracoes_backup bloqueada")
        return real_save(conn, updates)

    monkeypatch.setattr(orchestrator, "_save_drive_config", failing_save)

    assert _statuses(_run_cycle(backup_env))["google"] == orchestrator.OUTCOME_SUCCESS


def test_retention_keeps_each_location_series_separately(backup_env, events):
    """The cycle's local snapshot and its folder copy never compete for one slot;
    a later cycle still thins each location to its newest within the window."""
    backup_env.configure(cloud_folder=True, google=False, onedrive=False)
    local_snapshots = backup_env.local_dir / "snapshots"
    folder_snapshots = backup_env.cloud_dir / "snapshots"

    first = Path(_run_cycle(backup_env)["snapshot"]["database_path"])
    assert first.exists()
    assert len(list(folder_snapshots.glob("*.db"))) == 1

    second = Path(_run_cycle(backup_env)["snapshot"]["database_path"])
    assert sorted(local_snapshots.glob("*.db")) == [second]
    assert len(list(folder_snapshots.glob("*.db"))) == 1


def test_cycle_order_is_local_then_destinations_then_retention(backup_env, events):
    backup_env.configure(cloud_folder=True, google=True, onedrive=True)
    _run_cycle(backup_env)
    assert events.log == ["folder", "google", "onedrive", "retention"]
