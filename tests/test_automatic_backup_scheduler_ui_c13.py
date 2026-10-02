"""UI-C13: automatic backup that follows the SGAA periodicity, runs one cycle at a
time, leaves durable evidence and is shown as active only when it really is.

* Periodicity owner: the existing ``cloud_sync_interval_seconds`` ("Intervalo
  de verificação (s)", ``0 = ao alterar``) -- the gate the automatic cycle had
  before UT-5. The Windows task only wakes the SGAA every ``POLL_MINUTES``;
  ``app.backup.automatic.evaluate_due`` decides.
* Concurrency: ``app.backup.lock.backup_cycle_lock`` (OS file lock in the local
  backup folder) is held by the CLI, "Gerar backup agora" and both restores.
* Effective state: ``app.backup.task_scheduler.automatic_backup_status``.
* Indicator: the Drive/OneDrive activity chip owner (``.db-chip.is-active``)
  beside the Banco de dados title, only when effectively active.

Nothing here registers, changes or queries a real scheduled task: every
Windows call goes through ``task_scheduler._run``/``query_task`` doubles.
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.backup import automatic, orchestrator, task_scheduler
from app.backup.lock import BackupCycleBusy, backup_cycle_lock
from tests.test_backup_destination_outcomes_ui_c11_c12 import (  # noqa: F401  (fixtures)
    admin_client,
    backup_env,
    events,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUSY = "Outro backup está em andamento. Aguarde a conclusão e tente novamente."
T0 = datetime.datetime(2026, 9, 28, 9, 0, tzinfo=datetime.timezone.utc)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the supported scheduler is Windows Task Scheduler")


# ------------------------------------------------------------------ helpers

def _set_interval(env, seconds: int) -> None:
    with env.main.app.app_context():
        conn = env.main.get_db_connection()
        conn.execute(
            "UPDATE configuracoes_backup SET valor=? WHERE chave='cloud_sync_interval_seconds'",
            (str(seconds),),
        )
        conn.commit()


def _touch_data(env, marker: str) -> None:
    """A real content change outside the backup bookkeeping tables."""
    with env.main.app.app_context():
        conn = env.main.get_db_connection()
        conn.execute(
            "INSERT INTO configuracoes_app(chave, valor) VALUES('ui_c13_marker', ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
            (marker,),
        )
        conn.commit()


def _tick(env, moment):
    with env.main.app.app_context():
        return automatic.run_automatic_cycle(trigger="scheduled", now=moment)


def _snapshots(env) -> list[Path]:
    return sorted((env.local_dir / "snapshots").glob("*.db"))


def _current_task(**overrides) -> dict:
    expected = task_scheduler.expected_action()
    task = {
        "enabled": True,
        "triggers_enabled": True,
        "repetition": f"PT{task_scheduler.POLL_MINUTES}M",
        "command": expected["command"],
        "arguments": expected["arguments"],
        "working_directory": expected["working_directory"],
        "user_id": "S-1-5-21-ui-c13",
        "logon_type": "InteractiveToken",
    }
    task.update(overrides)
    return task


@pytest.fixture
def scheduler(monkeypatch, tmp_path):
    """Task Scheduler double: the registered task is whatever the test sets."""
    interpreter = tmp_path / "venv" / "Scripts" / "pythonw.exe"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"")
    monkeypatch.setattr(task_scheduler, "canonical_interpreter", lambda: str(interpreter))
    monkeypatch.setattr(task_scheduler, "current_user", lambda: {"name": "PC\\usuario", "sid": "S-1-5-21-ui-c13"})

    class Scheduler:
        task: dict | None = None
        commands: list[list[str]] = []

    state = Scheduler()
    state.commands = []
    monkeypatch.setattr(task_scheduler, "query_task", lambda: state.task)

    def fake_run(args):
        state.commands.append(list(args))
        if args[:2] == ["schtasks", "/Create"]:
            state.task = _current_task()
        elif args[:2] == ["schtasks", "/Delete"]:
            state.task = None
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(task_scheduler, "_run", fake_run)
    return state


VALID = {"local_backup_dir": "C:\\SGAA_BACKUPS", "cloud_sync_interval_seconds": "600"}


def _status(settings=VALID, database=None):
    return task_scheduler.automatic_backup_status(
        settings, database or task_scheduler.canonical_database_path()
    )


# ------------------------------------------------ 1-5: effective state

def test_1_task_disabled_or_invalid_sgaa_config_is_not_active(scheduler):
    """SGAA has no global on/off: 'disabled' is a disabled task or unusable config."""
    scheduler.task = _current_task(enabled=False)
    assert _status()["active"] is False and _status()["state"] == task_scheduler.STATE_DISABLED
    scheduler.task = _current_task()
    for broken in ({**VALID, "cloud_sync_interval_seconds": "abc"}, {**VALID, "cloud_sync_interval_seconds": "-1"}, {**VALID, "local_backup_dir": ""}):
        status = _status(broken)
        assert status["active"] is False and status["state"] == task_scheduler.STATE_CONFIG_INVALID


def test_2_configured_but_no_scheduled_task_is_not_active(scheduler):
    scheduler.task = None
    status = _status()
    assert status["active"] is False
    assert status["state"] == task_scheduler.STATE_NOT_INSTALLED
    assert status["interval_seconds"] == 600


def test_3_installed_enabled_current_task_is_active(scheduler):
    scheduler.task = _current_task()
    status = _status()
    assert status["active"] is True and status["state"] == task_scheduler.STATE_ACTIVE
    assert status["problems"] == []


def test_4_disabled_trigger_is_not_active(scheduler):
    scheduler.task = _current_task(triggers_enabled=False)
    assert _status()["state"] == task_scheduler.STATE_DISABLED


@pytest.mark.parametrize(
    "override, state",
    [
        ({"command": "C:\\Python311\\pythonw.exe"}, task_scheduler.STATE_STALE),
        ({"arguments": "-m app.backup.sync"}, task_scheduler.STATE_STALE),
        ({"working_directory": "C:\\copia-antiga\\SGAA"}, task_scheduler.STATE_STALE),
        ({"user_id": "S-1-5-18"}, task_scheduler.STATE_WRONG_ACCOUNT),
    ],
)
def test_5_task_pointing_at_another_install_or_account_is_not_active(scheduler, override, state):
    scheduler.task = _current_task(**override)
    status = _status()
    assert status["active"] is False and status["state"] == state and status["problems"]


def test_5b_missing_venv_interpreter_is_stale(scheduler, monkeypatch, tmp_path):
    missing = str(tmp_path / "gone" / "pythonw.exe")
    monkeypatch.setattr(task_scheduler, "canonical_interpreter", lambda: missing)
    scheduler.task = _current_task(command=missing)
    assert _status()["state"] == task_scheduler.STATE_STALE


def test_5c_task_covers_the_canonical_database_only(scheduler, tmp_path):
    scheduler.task = _current_task()
    status = _status(database=str(tmp_path / "acceptance" / "database.db"))
    assert status["active"] is False and status["state"] == task_scheduler.STATE_OTHER_DATABASE


# ------------------------------------------------ 6-7: periodicity

@pytest.mark.parametrize("interval", [0, 60, 300, 600, 3600, 7200, 86400])
def test_6_every_sgaa_interval_is_respected_by_the_polling_task(interval):
    """Simulated three days of 5-minute wakes with data changing every wake."""
    poll = datetime.timedelta(minutes=task_scheduler.POLL_MINUTES)
    state: dict = {}
    backups = []
    for step in range(int(datetime.timedelta(days=3) / poll)):
        # The snapshot is dated a few seconds after its wake, like the real one.
        moment = T0 + step * poll + datetime.timedelta(seconds=7)
        due, _reason = automatic.evaluate_due(state, f"digest-{step}", interval, moment)
        if due:
            backups.append(moment)
            state = {"last_backup_at": automatic._iso(moment), "last_digest": f"digest-{step}"}
    gaps = [(later - earlier).total_seconds() for earlier, later in zip(backups, backups[1:])]
    assert gaps, "three days of changes must produce backups"
    lower = max(interval - automatic.DUE_GRACE_SECONDS, 0)
    upper = max(interval, poll.total_seconds()) + poll.total_seconds()
    assert all(lower <= gap <= upper for gap in gaps), (interval, sorted(set(gaps)))


def test_6b_unchanged_database_is_never_backed_up_again():
    state = {"last_backup_at": automatic._iso(T0), "last_digest": "same"}
    for hours in (1, 24, 24 * 30):
        assert automatic.evaluate_due(state, "same", 0, T0 + datetime.timedelta(hours=hours)) == (False, "unchanged")


def test_7_changing_the_interval_in_sgaa_changes_the_next_wake_without_touching_the_task(backup_env, events, scheduler):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    _set_interval(backup_env, 7200)
    first = _tick(backup_env, T0)
    assert first["ran"] and first["reason"] == "first_run"
    _touch_data(backup_env, "a")
    assert _tick(backup_env, T0 + datetime.timedelta(minutes=10)) ["reason"] == "interval"
    _set_interval(backup_env, 0)  # "0 = ao alterar"
    third = _tick(backup_env, T0 + datetime.timedelta(minutes=15))
    assert third["ran"] and third["reason"] == "changed"
    assert scheduler.commands == [], "the SGAA setting is read on each wake; the task is never rewritten"
    xml = task_scheduler.build_task_xml(
        user_sid="S-1", command="C:\\py\\pythonw.exe", arguments=task_scheduler.TASK_ARGUMENTS,
        working_directory="C:\\SGAA", start_boundary="2026-09-28T09:00:00",
    )
    assert "7200" not in xml and "cloud_sync_interval" not in xml
    assert f"<Interval>PT{task_scheduler.POLL_MINUTES}M</Interval>" in xml


# ------------------------------------------------ 8-12: execution

def test_8_wake_when_not_due_is_a_clean_logged_skip(backup_env, events, caplog):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    _set_interval(backup_env, 3600)
    assert _tick(backup_env, T0)["ran"]
    before = _snapshots(backup_env)
    caplog.set_level("INFO", logger="main")
    skipped = _tick(backup_env, T0 + datetime.timedelta(minutes=5))
    assert skipped == {"ran": False, "reason": "unchanged", "result": None}
    assert _snapshots(backup_env) == before
    assert "não devido (unchanged)" in caplog.text
    state = automatic.read_state(str(backup_env.local_dir), backup_env.main.DATABASE)
    assert state["last_result"] == "unchanged" and state["last_backup_at"] == automatic._iso(T0)


def test_9_wake_when_due_runs_the_cycle_and_records_it(backup_env, events):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    _set_interval(backup_env, 600)
    first = _tick(backup_env, T0)["result"]["snapshot"]["database_path"]
    _touch_data(backup_env, "b")
    result = _tick(backup_env, T0 + datetime.timedelta(minutes=10))
    assert result["ran"] and result["reason"] == "changed"
    state = automatic.read_state(str(backup_env.local_dir), backup_env.main.DATABASE)
    # A new snapshot (the local GFS retention may thin the same-bucket older one).
    assert state["last_snapshot"] != first and Path(state["last_snapshot"]).exists()
    assert state["last_result"] == "backup" and state["last_trigger"] == "scheduled"
    assert state["last_backup_at"] == automatic._iso(T0 + datetime.timedelta(minutes=10))


def test_10_manual_and_scheduled_cannot_overlap(backup_env, events, admin_client):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    before = _snapshots(backup_env)
    with backup_cycle_lock(str(backup_env.local_dir)):
        # A scheduled wake while a cycle runs refuses without touching anything...
        with pytest.raises(BackupCycleBusy):
            _tick(backup_env, T0)
        # ...and so does "Gerar backup agora", with a truthful message.
        response = admin_client.post("/admin/banco-dados/backup", follow_redirects=False)
        assert response.status_code in (302, 303)
        with admin_client.session_transaction() as session:
            assert list(session.get("_flashes", [])) == [("warning", BUSY)]
    assert _snapshots(backup_env) == before
    assert automatic.read_state(str(backup_env.local_dir), backup_env.main.DATABASE) == {}
    # Once the holder is gone, the next cycle proceeds.
    assert _tick(backup_env, T0)["ran"]


def test_10b_restore_refuses_while_another_cycle_runs(backup_env, events, admin_client):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    admin_client.post("/admin/banco-dados/backup")
    with admin_client.session_transaction() as session:
        session.pop("_flashes", None)
    manifest = next((backup_env.local_dir / "snapshots").glob("*.json"))
    database = Path(backup_env.main.DATABASE)
    fingerprint = database.read_bytes()
    with backup_cycle_lock(str(backup_env.local_dir)):
        response = admin_client.post("/admin/banco-dados/restaurar", data={"manifest_path": str(manifest)})
        assert response.status_code in (302, 303)
        with admin_client.session_transaction() as session:
            assert list(session.get("_flashes", [])) == [("warning", BUSY)]
    assert database.read_bytes() == fingerprint


def test_10c_a_crashed_holder_never_leaves_a_stale_lock(tmp_path):
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys,time; sys.path.insert(0, sys.argv[1]);"
         "from app.backup.lock import backup_cycle_lock;"
         "ctx = backup_cycle_lock(sys.argv[2]); ctx.__enter__(); print('locked', flush=True); time.sleep(60)",
         str(PROJECT_ROOT), str(tmp_path)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(BackupCycleBusy):
            with backup_cycle_lock(str(tmp_path)):
                pass
    finally:
        holder.kill()  # abrupt end: no unlock, no cleanup
        holder.wait(timeout=30)
    # Windows releases a dead process's byte-range lock asynchronously, shortly
    # after termination; the next scheduled wake is minutes away anyway.
    deadline = time.monotonic() + 15
    while True:
        try:
            with backup_cycle_lock(str(tmp_path)):
                break  # the OS released it with the process
        except BackupCycleBusy:
            assert time.monotonic() < deadline, "lock of a killed process was never released"
            time.sleep(0.2)


def test_11_cloud_providers_follow_their_own_switches_on_a_scheduled_wake(backup_env, events):
    backup_env.configure(cloud_folder=False, google=False, onedrive=True)
    outcomes = _tick(backup_env, T0)["result"]["outcomes"]
    assert outcomes["google"]["status"] == orchestrator.OUTCOME_NOT_ENABLED
    assert outcomes["onedrive"]["status"] == orchestrator.OUTCOME_SUCCESS
    assert [provider for provider, _path in events.uploads] == ["onedrive"]


@pytest.mark.parametrize("cloud_folder", [True, False])
def test_12_legacy_cloud_folder_stays_independent_on_a_scheduled_wake(backup_env, events, cloud_folder):
    backup_env.configure(cloud_folder=cloud_folder, google=True, onedrive=False)
    outcomes = _tick(backup_env, T0)["result"]["outcomes"]
    expected = orchestrator.OUTCOME_SUCCESS if cloud_folder else orchestrator.OUTCOME_NOT_CONFIGURED
    assert outcomes["cloud_folder"]["status"] == expected
    assert outcomes["google"]["status"] == orchestrator.OUTCOME_SUCCESS
    assert bool(list((backup_env.cloud_dir / "snapshots").glob("*.db"))) is cloud_folder


# ------------------------------------------------ 13-16: header indicator

def _page(client) -> str:
    return client.get("/admin/banco-dados").get_data(as_text=True)


def _destination_chips(page: str) -> str:
    """The chip group on the right of the "Destinos e sincronização" card header."""
    head = page.split("Destinos e sincronização</span>", 1)[1]
    return head.split('<div class="db-chips">', 1)[1].split("</div>", 1)[0]


# Same label in both states, like the destination chips beside it; only the style tells the state.
ACTIVE_CHIP = '<span class="db-chip is-active" role="status" data-automatic-backup-status="active">Backup automático</span>'
INACTIVE_CHIP = '<span class="db-chip" role="status" data-automatic-backup-status="inactive">Backup automático</span>'


def _no_state_words(page: str) -> None:
    assert "Backup automático ativo" not in page and "Backup automático inativo" not in page


def test_13_effectively_active_shows_the_blue_chip_among_the_destination_chips(backup_env, events, admin_client, scheduler, monkeypatch):
    backup_env.configure(cloud_folder=False, google=False, onedrive=False)
    _set_interval(backup_env, 7200)
    _tick(backup_env, T0)
    monkeypatch.setattr(task_scheduler, "canonical_database_path", lambda: backup_env.main.DATABASE)
    scheduler.task = _current_task()
    page = _page(admin_client)
    chips = _destination_chips(page)
    assert ACTIVE_CHIP in chips  # A: blue shared `.db-chip.is-active`, in the destinations header
    assert INACTIVE_CHIP not in page
    _no_state_words(page)
    assert page.count("data-automatic-backup-status") == 1
    # D: the destination chips stay, in order, and the automatic-backup state closes the group.
    positions = [chips.index(label) for label in (">Pasta sincronizada<", ">Google Drive<", ">OneDrive<", ">Backup automático<")]
    assert positions == sorted(positions)
    # No scheduler detail anywhere on the chip, and the page title carries no chip.
    assert "title=" not in ACTIVE_CHIP
    for detail in ("Agendador de Tarefas", "Último backup automático", "no máximo a cada", "Verificação a cada"):
        assert detail not in page, detail
    assert '<h1 class="main-title">Banco de dados</h1>' in page.split("<header>", 1)[1].split("</header>", 1)[0]


@pytest.mark.parametrize("task", [None, "disabled", "stale", "wrong_account"])
def test_14_15_configured_but_missing_or_broken_scheduler_shows_the_neutral_inactive_chip(backup_env, admin_client, scheduler, monkeypatch, task):
    backup_env.configure(cloud_folder=False, google=True, onedrive=True)
    monkeypatch.setattr(task_scheduler, "canonical_database_path", lambda: backup_env.main.DATABASE)
    scheduler.task = {
        None: None,
        "disabled": _current_task(enabled=False),
        "stale": _current_task(working_directory="C:\\outro"),
        "wrong_account": _current_task(user_id="S-1-5-21-outra-conta"),
    }[task]
    page = _page(admin_client)
    chips = _destination_chips(page)
    assert INACTIVE_CHIP in chips  # B: neutral shared `.db-chip`, never blue
    assert ACTIVE_CHIP not in page and "db-chip is-active\" role=\"status\"" not in page
    _no_state_words(page)
    assert 'data-automatic-backup-status="active"' not in page


def test_15b_acceptance_database_is_never_reported_as_covered(backup_env, admin_client, scheduler):
    scheduler.task = _current_task()  # a perfect task -- but for the canonical database
    page = _page(admin_client)
    assert INACTIVE_CHIP in _destination_chips(page)
    assert ACTIVE_CHIP not in page and "db-chip is-active\" role=\"status\"" not in page
    _no_state_words(page)


def test_15c_provider_upload_timestamps_are_not_on_the_page(backup_env, admin_client, scheduler, monkeypatch):
    """C: the "Destinos em nuvem e externos" card no longer lists per-provider upload timestamps."""
    backup_env.configure(cloud_folder=False, google=True, onedrive=True)
    with backup_env.main.app.app_context():
        conn = backup_env.main.get_db_connection()
        for key in ("gdrive_last_upload_at", "onedrive_last_upload_at"):
            conn.execute(
                "INSERT INTO configuracoes_backup(chave, valor) VALUES(?, '2026-09-28T14:15:34Z') "
                "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                (key,),
            )
        conn.commit()
    page = _page(admin_client)
    assert "Último upload Google Drive" not in page
    assert "Último upload OneDrive" not in page


def test_16_indicator_reuses_the_destination_chip_owner_and_adds_no_colour():
    template = (PROJECT_ROOT / "templates" / "admin_banco_dados.html").read_text(encoding="utf-8")
    group = template.split("Destinos e sincronização</span>", 1)[1].split('<div class="db-chips">', 1)[1]
    group = group.split("\n      </div>", 1)[0]
    # D: provider chips unchanged, same owner as the new state chip.
    for provider in (
        '<span class="db-chip {% if cloud_backup_dir %}is-active{% endif %}">Pasta sincronizada</span>',
        '<span class="db-chip {% if gdrive_connected %}is-active{% endif %}">Google Drive</span>',
        '<span class="db-chip {% if onedrive_connected %}is-active{% endif %}">OneDrive</span>',
    ):
        assert provider in group
    assert ACTIVE_CHIP in group and INACTIVE_CHIP in group
    # F: rendered from the effective resolver's verdict, never from a setting.
    assert "{% if (automatic_backup_status or {}).active %}" in group
    # E: no local style, no new colour, no second chip owner; the shared rules are the pre-UI-C13 ones.
    assert "style=" not in group
    assert template.count(".db-chip {") == 1 and template.count(".db-chip.is-active {") == 1
    # UI-B11: the shared chip owner now paints its one colour through the global
    # --info-bg token (same value); no new colour and no second chip owner.
    assert ".db-chip.is-active { background:var(--info-bg); border-color:transparent; color:var(--accent-blue); font-weight:500; }" in template
    assert "db-title-row" not in template
    assert "header-status" not in (PROJECT_ROOT / "static" / "css" / "modern-style.css").read_text(encoding="utf-8")


# ------------------------------------------------ logging + CLI (isolated subprocess)

def _cli_env(tmp_path):
    from tests.test_ut5_backup_package import _create_disposable_prod1_database, _quarantine_backup_settings

    database = tmp_path / "isolated.db"
    _create_disposable_prod1_database(database)
    local_dir, cloud_dir, logs = tmp_path / "local", tmp_path / "cloud", tmp_path / "logs"
    for directory in (local_dir, cloud_dir, logs, tmp_path / "uploads", tmp_path / "docs"):
        directory.mkdir(parents=True, exist_ok=True)
    _quarantine_backup_settings(database, local_dir=local_dir, cloud_dir=cloud_dir)
    conn = sqlite3.connect(database)
    conn.execute("UPDATE configuracoes_backup SET valor='600' WHERE chave='cloud_sync_interval_seconds'")
    # A secret the log must never repeat.
    conn.execute("UPDATE configuracoes_backup SET valor='segredo-ui-c13-nao-logar' WHERE chave='external_backup_token'")
    conn.commit()
    conn.close()
    env = os.environ.copy()
    env.update(
        APP_DATABASE=str(database), APP_LOG_DIR=str(logs), APP_LOCAL_BACKUP_DIR=str(local_dir),
        APP_CLOUD_BACKUP_DIR=str(cloud_dir), APP_UPLOAD_FOLDER=str(tmp_path / "uploads"),
        APP_DOCUMENTOS_ALUNOS_FOLDER=str(tmp_path / "docs"), APP_BOOTSTRAP_DEFAULT_ADMIN="0",
        DISABLE_CSRF="1", APP_SECRET_KEY="ui-c13-cli-isolated-secret-not-for-use", EXTERNAL_BACKUP_ENABLED="0",
    )
    return env, local_dir, logs / automatic.RUN_LOG_FILENAME


def _cli(env, *args):
    return subprocess.run(
        [sys.executable, "-B", "-m", "app.backup.sync", *args],
        cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True, timeout=120,
    )


def test_scheduled_cli_leaves_durable_evidence_and_skips_when_not_due(tmp_path):
    env, local_dir, log_path = _cli_env(tmp_path)
    first = _cli(env, "--scheduled")
    assert first.returncode == 0, first.stderr
    second = _cli(env, "--scheduled")
    assert second.returncode == 0, second.stderr
    log = log_path.read_text(encoding="utf-8")
    assert log.count("início (gatilho=scheduled, intervalo configurado=600s") == 2
    assert "devido (first_run); executando o ciclo." in log
    assert "Backup automático: concluído (snapshot=" in log and "destinos: cloud_folder=" in log
    assert "não devido (unchanged); nada foi feito." in log
    assert log.count("fim (gatilho=scheduled, código de saída=0)") == 2
    assert "segredo-ui-c13-nao-logar" not in log
    assert len(list((local_dir / "snapshots").glob("*.db"))) == 1


def test_cli_busy_exit_codes_scheduled_is_clean_manual_cli_is_3(tmp_path):
    env, local_dir, log_path = _cli_env(tmp_path)
    with backup_cycle_lock(str(local_dir)):
        scheduled = _cli(env, "--scheduled")
        unconditional = _cli(env)
    assert scheduled.returncode == 0 and unconditional.returncode == 3
    assert "outro ciclo de backup está em andamento" in log_path.read_text(encoding="utf-8")
    assert not list((local_dir / "snapshots").glob("*.db"))


# ------------------------------------------------ installer (no real scheduler)

def test_install_dry_run_registers_nothing_and_the_definition_holds_no_secret(scheduler):
    outcome = task_scheduler.install(dry_run=True)
    assert outcome["ok"] and outcome["changed"] is False and scheduler.commands == []
    xml = outcome["plan"]["xml"]
    parsed = task_scheduler.parse_task_xml(xml)
    expected = task_scheduler.expected_action()
    assert parsed["command"] == expected["command"] and parsed["arguments"] == "-m app.backup.sync --scheduled"
    assert parsed["working_directory"] == str(PROJECT_ROOT)
    assert parsed["logon_type"] == "InteractiveToken" and parsed["user_id"] == "S-1-5-21-ui-c13"
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "<ExecutionTimeLimit>PT30M</ExecutionTimeLimit>" in xml
    scrubbed = xml.replace("<LogonType>InteractiveToken</LogonType>", "").lower()
    for forbidden in ("token", "senha", "password", "secret", "app_", "master", "<password"):
        assert forbidden not in scrubbed, forbidden


def test_install_status_reconcile_uninstall_are_idempotent(scheduler):
    assert task_scheduler.reconcile(dry_run=True)["previous_state"] == task_scheduler.STATE_NOT_INSTALLED
    assert scheduler.commands == []
    installed = task_scheduler.install()
    assert installed["ok"] and installed["changed"] and installed["state"] == task_scheduler.STATE_ACTIVE
    create = scheduler.commands[-1]
    assert create[:4] == ["schtasks", "/Create", "/TN", task_scheduler.TASK_NAME] and create[-1] == "/F"
    assert not Path(create[5]).exists(), "the temporary definition file is removed"
    assert task_scheduler.reconcile() == {"ok": True, "changed": False, "state": task_scheduler.STATE_ACTIVE, "problems": []}
    scheduler.task = _current_task(working_directory="C:\\copia-antiga")
    repaired = task_scheduler.reconcile()
    assert repaired["previous_state"] == task_scheduler.STATE_STALE and repaired["ok"] and repaired["changed"]
    assert task_scheduler.uninstall()["changed"] is True and scheduler.task is None
    assert task_scheduler.uninstall() == {"ok": True, "changed": False, "problems": [], "command": ["schtasks", "/Delete", "/TN", task_scheduler.TASK_NAME, "/F"]}


def test_registered_task_xml_as_schtasks_prints_it_parses():
    printed = task_scheduler.build_task_xml(
        user_sid="S-1-5-21-1", command="C:\\Users\\u\\AppData\\Local\\SGAA\\venv\\Scripts\\pythonw.exe",
        arguments=task_scheduler.TASK_ARGUMENTS, working_directory="D:\\SGAA", start_boundary="2026-09-28T09:00:00",
    ).replace("\n", "\r\r\n")
    parsed = task_scheduler.parse_task_xml(printed)
    assert parsed["enabled"] and parsed["triggers_enabled"] and parsed["repetition"] == "PT5M"
    disabled = printed.replace("<Enabled>true</Enabled>\r\r\n    <Hidden>", "<Enabled>false</Enabled>\r\r\n    <Hidden>")
    assert task_scheduler.parse_task_xml(disabled)["enabled"] is False
