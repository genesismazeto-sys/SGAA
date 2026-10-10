# coding: utf-8
"""MP-2 S2: the database administration page and routes are PostgreSQL-coherent.

U5-E made the backup/restore ENTRYPOINTS refuse under PostgreSQL.  MP-2 closes
the rest of the surface a hosted operator meets:

* four routes still ran their SQLite-file logic -- ``configuracoes`` (it creates
  the configured directories), ``retencao``, ``download`` and ``excluir``;
* the page still listed local snapshots, queried the Windows task and rendered
  directory, restore, retention and "send backup" controls that cannot work.

Harness: the U5-E stand-in (``app.db.DATABASE_URL`` switched, the PostgreSQL
connect replaced by a private SQLite copy, every ``sqlite3.connect`` spied).
Every refusal arm has a SQLite control proving the gate, not a general failure,
is what the assertion discriminates.
"""
from __future__ import annotations

import pytest

from app.backup import task_scheduler
from app.views.admin import banco_dados as banco_dados_view
from tests.test_backup_destination_outcomes_ui_c11_c12 import (  # noqa: F401  (fixtures)
    admin_client,
    backup_env,
    events,
)
from tests.test_pg_readiness_unit5e_maintenance_boundary import (
    _clear_flashes,
    _flashes,
    _PostgresBackend,
    _request,
    _source_snapshot,
)

PAGE = "/admin/banco-dados"


@pytest.fixture
def pg_backend(backup_env, admin_client, monkeypatch, tmp_path):
    return _PostgresBackend(backup_env, monkeypatch, tmp_path)


@pytest.fixture
def forbid_file_backup_reads(monkeypatch):
    """Under PostgreSQL nothing may list snapshots or query the Windows task."""
    calls: list[str] = []

    def listed(*_a, **_k):
        calls.append("list_database_backups")
        return []

    def queried(*_a, **_k):
        calls.append("query_task")
        return None

    monkeypatch.setattr(banco_dados_view, "list_database_backups", listed)
    monkeypatch.setattr(task_scheduler, "query_task", queried)
    return calls


@pytest.fixture
def google_connected(monkeypatch):
    """A connected Google account (test double): the cards that remain must show it."""
    monkeypatch.setattr(
        banco_dados_view,
        "get_application_credential_status",
        lambda provider: {"configured": True, "source": "ENVIRONMENT"},
    )
    monkeypatch.setattr(
        banco_dados_view,
        "_get_active_cloud_account",
        lambda conn, provider: (
            {"account_email": "conta@example.invalid", "token_json_available": True}
            if provider == "google"
            else None
        ),
    )


def _page(client) -> str:
    response = client.get(PAGE)
    assert response.status_code == 200
    return response.get_data(as_text=True)


# Markers of the file-backup family: each is present on the SQLite page (control)
# and must be absent under PostgreSQL.
FILE_BACKUP_MARKERS = (
    'name="local_backup_dir"',
    'name="cloud_backup_dir"',
    "admin/banco-dados/configuracoes",
    "restore-snapshot-form",
    "restore-upload-form",
    "admin/banco-dados/backup",
    'id="retention-form"',
    "Snapshots disponíveis",
    "Política de retenção",
    "gdrive-backup-now",
    "data-google-picker-button",
    "data-automatic-backup-status",
    "gdrive_enabled_submitted",
    "https://apis.google.com/js/api.js",
)


# ===========================================================================
# 1. the four routes that used to run SQLite-file logic
# ===========================================================================

ROUTES = (
    ("post", "/admin/banco-dados/configuracoes", lambda tmp: {
        "local_backup_dir": str(tmp / "must-not-be-created" / "local"),
        "cloud_backup_dir": str(tmp / "must-not-be-created" / "cloud"),
        "cloud_sync_interval_seconds": "600",
    }),
    ("post", "/admin/banco-dados/retencao", lambda tmp: {"retention_w0_slots": "3"}),
    ("get", "/admin/banco-dados/download?manifest_path=nao-existe.json", lambda tmp: None),
    ("post", "/admin/banco-dados/excluir", lambda tmp: {"manifest_path": "nao-existe.json"}),
)


@pytest.mark.parametrize("method, url, payload", ROUTES, ids=["configuracoes", "retencao", "download", "excluir"])
def test_pg_file_backup_routes_refuse_and_write_nothing(
    backup_env, admin_client, pg_backend, tmp_path, monkeypatch, method, url, payload
):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    pg_backend.activate()

    def reached(name):
        def boom(*_a, **_k):
            raise AssertionError(f"{name} reached under PostgreSQL")

        return boom

    # The refusal comes first: none of the writers or readers behind it is touched.
    for name in (
        "save_backup_settings",
        "save_retention_policy",
        "delete_database_snapshot",
        "_resolve_allowed_backup_manifest_path",
        "send_file",
    ):
        monkeypatch.setattr(banco_dados_view, name, reached(name))
    _clear_flashes(admin_client)

    if method == "get":
        response, exc = _request(lambda: admin_client.get(url))
    else:
        response, exc = _request(lambda: admin_client.post(url, data=payload(tmp_path)))

    assert exc is None, exc
    assert response.status_code in (302, 303)
    assert response.headers["Location"].endswith(PAGE)
    flashes = _flashes(admin_client)
    assert flashes and all(category != "success" for category, _m in flashes), flashes
    assert any("postgresql" in str(message).lower() for _c, message in flashes), flashes
    pg_backend.assert_no_sqlite_io()
    pg_backend.assert_stale_untouched()
    pg_backend.assert_no_new_artifacts()
    assert not (tmp_path / "must-not-be-created").exists(), "the refused route created directories"


def test_sqlite_control_configuracoes_saves_and_creates_directories(backup_env, admin_client, tmp_path):
    """Discrimination: the same POST under SQLite succeeds, so the refusal above is the gate."""
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    target = tmp_path / "control-local"
    _clear_flashes(admin_client)
    response = admin_client.post(
        "/admin/banco-dados/configuracoes",
        data={
            "local_backup_dir": str(target),
            "cloud_backup_dir": "",
            "cloud_sync_interval_seconds": "600",
        },
    )
    assert response.status_code in (302, 303)
    assert any("atualizados com sucesso" in str(m) for _c, m in _flashes(admin_client)), _flashes(admin_client)
    assert target.is_dir()


def test_sqlite_control_retencao_saves(backup_env, admin_client):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    _clear_flashes(admin_client)
    response = admin_client.post(
        "/admin/banco-dados/retencao", data=banco_dados_view._retention_policy_defaults()
    )
    assert response.status_code in (302, 303)
    flashes = _flashes(admin_client)
    assert any("Política de retenção atualizada com sucesso" in str(m) for _c, m in flashes), flashes
    assert not any("postgresql" in str(m).lower() for _c, m in flashes), flashes


# ===========================================================================
# 2. the page
# ===========================================================================


def test_pg_page_drops_file_backup_surfaces_and_keeps_account_state(
    backup_env, admin_client, pg_backend, forbid_file_backup_reads, google_connected
):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    pg_backend.activate()

    html = _page(admin_client)

    assert forbid_file_backup_reads == [], forbid_file_backup_reads
    pg_backend.assert_no_sqlite_io()
    assert "PostgreSQL" in html
    assert 'data-database-protection="postgresql"' in html
    for marker in FILE_BACKUP_MARKERS:
        assert marker not in html, f"file-backup surface still rendered under PostgreSQL: {marker!r}"
    # What remains is meaningful on this backend: the schema state and the account.
    assert "Compatibilidade futura" in html
    assert "Google Drive" in html
    assert "conta@example.invalid" in html
    assert "admin/backup/google/connect" in html  # (re)connect stays available
    assert "Testar conexão" in html


def test_pg_page_credential_form_posts_no_destination_fields(
    backup_env, admin_client, pg_backend, forbid_file_backup_reads
):
    """The handler writes exactly what arrives: no destination marker, no stale overwrite."""
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    pg_backend.activate()
    html = _page(admin_client)
    assert "gdrive_dest_folder" not in html
    assert "onedrive_dest_folder" not in html
    assert "onedrive_enabled_submitted" not in html
    assert 'name="gdrive_enabled"' not in html
    assert 'name="onedrive_enabled"' not in html


def test_sqlite_control_page_renders_every_file_backup_marker(
    backup_env, admin_client, google_connected, monkeypatch
):
    """Discrimination: each marker the PostgreSQL arm forbids exists on the SQLite page."""
    backup_env.configure(cloud_folder=False, google=True, onedrive=False)
    _source_snapshot(backup_env)  # the snapshot restore form renders only when one exists
    # The scheduled-task chip renders from the effective status; a deterministic one.
    monkeypatch.setattr(task_scheduler, "query_task", lambda: None)

    html = _page(admin_client)

    missing = [marker for marker in FILE_BACKUP_MARKERS if marker not in html]
    assert missing == [], f"markers absent from the SQLite page (the PostgreSQL arm proves nothing): {missing}"
    assert "postgresql" not in html.lower()
    assert 'data-database-protection="postgresql"' not in html


def test_pg_page_context_flag_is_the_single_decision(backup_env, admin_client, pg_backend, forbid_file_backup_reads):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    pg_backend.activate()
    with backup_env.main.app.test_request_context(PAGE):
        conn = backup_env.main.get_db_connection()
        context = banco_dados_view._build_database_admin_context(conn)
    assert context["sqlite_maintenance_supported"] is False
    assert context["backups"] == []
    assert context["automatic_backup_status"] is None
    assert forbid_file_backup_reads == []
