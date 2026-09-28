# coding: utf-8
"""Tarefa do Agendador de Tarefas do Windows para o backup automático (UI-C13).

Arquitetura: a tarefa **não** carrega periodicidade. Ela acorda o SGAA num
ritmo fixo de verificação (:data:`POLL_MINUTES`) e executa
``pythonw -m app.backup.sync --scheduled``; quem decide se o backup é devido é
o SGAA, pelo "Intervalo de verificação" configurado na tela Banco de dados
(:mod:`app.backup.automatic`). Mudar o intervalo no SGAA não exige tocar na
tarefa, e não há uma segunda configuração de agenda no Windows.

Conta: as credenciais de nuvem estão no DPAPI **do usuário**
(``%LOCALAPPDATA%\\SGAA\\secrets``), então a tarefa roda como o usuário que
instalou, com ``LogonType=InteractiveToken`` (enquanto ele está conectado).
Nenhuma senha é pedida, lida, gravada ou registrada pelo SGAA, e a definição
da tarefa não contém token, chave nem segredo -- só o interpretador, o módulo
e a pasta do projeto.

Uso (nada é instalado sem pedido explícito)::

    python -m app.backup.task_scheduler status
    python -m app.backup.task_scheduler install   [--dry-run]
    python -m app.backup.task_scheduler reconcile [--dry-run]
    python -m app.backup.task_scheduler uninstall [--dry-run]

``install`` é idempotente (``schtasks /Create /F``); ``reconcile`` só
reinstala quando a tarefa existente está desativada, desatualizada ou aponta
para outra instalação -- é o comando de atualização depois de mover o projeto
ou recriar o venv.
"""
from __future__ import annotations

import argparse
import ctypes
import functools
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

TASK_NAME = "SGAA - Backup automatico"
#: Ritmo fixo do despertar -- técnico, não é a periodicidade do backup.
POLL_MINUTES = 5
TASK_ARGUMENTS = "-m app.backup.sync --scheduled"
EXECUTION_TIME_LIMIT = "PT30M"

_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

STATE_ACTIVE = "active"
STATE_UNSUPPORTED = "unsupported_platform"
STATE_CONFIG_INVALID = "config_invalid"
STATE_NOT_INSTALLED = "not_installed"
STATE_DISABLED = "disabled"
STATE_STALE = "stale"
STATE_WRONG_ACCOUNT = "wrong_account"
STATE_OTHER_DATABASE = "other_database"


# ===================== Instalação atual (resolvida em tempo de execução) =====================


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def canonical_database_path() -> str:
    """O banco que a tarefa agendada cobre: a tarefa não define APP_DATABASE."""
    return os.path.join(project_root(), "database.db")


def canonical_interpreter() -> str:
    """O ``pythonw.exe`` do venv canônico que o run.bat cria (sem console)."""
    local_app_data = (os.getenv("LOCALAPPDATA") or "").strip()
    return os.path.join(local_app_data, "SGAA", "venv", "Scripts", "pythonw.exe")


def expected_action() -> dict[str, str]:
    return {
        "command": canonical_interpreter(),
        "arguments": TASK_ARGUMENTS,
        "working_directory": project_root(),
    }


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(os.path.abspath(str(left or ""))) == os.path.normcase(os.path.abspath(str(right or "")))


# ===================== Windows (isolado para testes) =====================


def _run(args: list[str]) -> subprocess.CompletedProcess:
    """Único ponto que executa programas do Windows; os testes o substituem."""
    return subprocess.run(args, capture_output=True, timeout=30)


def _decode(data: bytes) -> str:
    """schtasks/whoami escrevem na página de código OEM do console."""
    try:
        codepage = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    except (AttributeError, OSError):
        codepage = "utf-8"
    try:
        return (data or b"").decode(codepage, errors="replace")
    except LookupError:
        return (data or b"").decode("utf-8", errors="replace")


@functools.lru_cache(maxsize=1)
def current_user() -> dict[str, str]:
    """Nome e SID do usuário do processo (``whoami /user``)."""
    result = _run(["whoami", "/user", "/fo", "csv", "/nh"])
    fields = [field.strip().strip('"') for field in _decode(result.stdout).strip().split('","')]
    if result.returncode != 0 or len(fields) != 2:
        return {"name": "", "sid": ""}
    return {"name": fields[0], "sid": fields[1]}


# ===================== Definição da tarefa =====================


def build_task_xml(*, user_sid: str, command: str, arguments: str, working_directory: str, start_boundary: str) -> str:
    """Definição completa da tarefa. Sem segredos: só caminho, módulo e pasta."""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="{_NS['t']}">
  <RegistrationInfo>
    <Author>SGAA</Author>
    <Description>SGAA - backup automatico. Acorda o SGAA a cada {POLL_MINUTES} min; o SGAA decide se o backup e devido pelo Intervalo de verificacao configurado em Banco de dados.</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT{POLL_MINUTES}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{escape(start_boundary)}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user_sid)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>{EXECUTION_TIME_LIMIT}</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(working_directory)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def parse_task_xml(text: str) -> dict:
    """Campos da tarefa registrada que decidem se ela é a instalação atual."""
    body = re.sub(r"^\s*<\?xml[^>]*\?>", "", str(text or "").lstrip("﻿"), count=1)
    root = ET.fromstring(body)

    def _text(path: str, default: str = "") -> str:
        node = root.find(path, _NS)
        return (node.text or "").strip() if node is not None and node.text is not None else default

    def _enabled(node) -> bool:
        flag = node.find("t:Enabled", _NS) if node is not None else None
        return flag is None or (flag.text or "").strip().lower() != "false"

    triggers = root.find("t:Triggers", _NS)
    trigger_nodes = list(triggers) if triggers is not None else []
    return {
        "enabled": _enabled(root.find("t:Settings", _NS)),
        "triggers_enabled": any(_enabled(node) for node in trigger_nodes),
        "repetition": _text("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval"),
        "command": _text("t:Actions/t:Exec/t:Command"),
        "arguments": _text("t:Actions/t:Exec/t:Arguments"),
        "working_directory": _text("t:Actions/t:Exec/t:WorkingDirectory"),
        "user_id": _text("t:Principals/t:Principal/t:UserId"),
        "logon_type": _text("t:Principals/t:Principal/t:LogonType"),
    }


def query_task() -> dict | None:
    """A tarefa registrada, ou ``None`` se não existe (ou não pôde ser lida)."""
    result = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/XML"])
    if result.returncode != 0:
        return None
    try:
        return parse_task_xml(_decode(result.stdout))
    except ET.ParseError:
        return None


# ===================== Estado efetivo =====================


def task_problems(task: dict | None) -> tuple[str, list[str]]:
    """``(estado, problemas)`` da tarefa frente à instalação atual."""
    if task is None:
        return STATE_NOT_INSTALLED, ["tarefa não registrada no Agendador de Tarefas"]
    if not task.get("enabled") or not task.get("triggers_enabled"):
        return STATE_DISABLED, ["tarefa desativada no Agendador de Tarefas"]
    expected = expected_action()
    problems = []
    if not _same_path(task.get("command"), expected["command"]):
        problems.append("a tarefa usa outro interpretador Python")
    elif not os.path.exists(expected["command"]):
        problems.append("o interpretador do venv canônico não existe mais")
    if " ".join(str(task.get("arguments") or "").split()) != expected["arguments"]:
        problems.append("a tarefa executa outro comando")
    if not _same_path(task.get("working_directory"), expected["working_directory"]):
        problems.append("a tarefa aponta para outra pasta do SGAA")
    if problems:
        return STATE_STALE, problems
    user = current_user()
    owner = str(task.get("user_id") or "").lower()
    if not owner or owner not in {user.get("sid", "").lower(), user.get("name", "").lower()}:
        return STATE_WRONG_ACCOUNT, ["a tarefa roda em outra conta do Windows (sem acesso ao DPAPI deste usuário)"]
    return STATE_ACTIVE, []


def automatic_backup_status(settings: dict, database_path: str) -> dict:
    """Backup automático **efetivamente** ativo para ``database_path``?

    Ativo só quando, ao mesmo tempo: a configuração do SGAA é válida (pasta
    local e intervalo inteiro >= 0), a tarefa existe, está ativada, aponta para
    esta instalação (interpretador, comando e pasta atuais), roda na conta
    deste usuário e cobre este banco. Não há interruptor global no SGAA; os
    destinos em nuvem continuam com seus próprios "Incluir no backup automático".
    """
    status = {
        "active": False,
        "state": STATE_UNSUPPORTED,
        "problems": [],
        "interval_seconds": None,
        "poll_minutes": POLL_MINUTES,
        "last_backup_at": "",
        "last_check_at": "",
        "last_result": "",
    }
    local_dir = str(settings.get("local_backup_dir") or "").strip()
    try:
        interval = int(str(settings.get("cloud_sync_interval_seconds") or "").strip())
        if interval < 0:
            raise ValueError
    except ValueError:
        interval = None
    status["interval_seconds"] = interval
    if local_dir:
        from app.backup.automatic import read_state

        state = read_state(local_dir, database_path)
        status.update(
            last_backup_at=str(state.get("last_backup_at") or ""),
            last_check_at=str(state.get("last_check_at") or ""),
            last_result=str(state.get("last_result") or ""),
        )
    if os.name != "nt":
        status["problems"] = ["o agendamento suportado é o Agendador de Tarefas do Windows"]
        return status
    if not local_dir or interval is None:
        status.update(state=STATE_CONFIG_INVALID, problems=["configuração de backup inválida no SGAA"])
        return status
    state_code, problems = task_problems(query_task())
    if state_code == STATE_ACTIVE and not _same_path(database_path, canonical_database_path()):
        state_code, problems = STATE_OTHER_DATABASE, ["a tarefa agendada cobre outro banco de dados"]
    status.update(state=state_code, problems=problems, active=state_code == STATE_ACTIVE)
    return status


# ===================== Instalar / atualizar / remover =====================


def _start_boundary() -> str:
    import datetime

    return datetime.datetime.now().replace(second=0, microsecond=0).isoformat()


def install_plan() -> dict:
    """O que ``install`` registraria, sem registrar nada."""
    action = expected_action()
    user = current_user()
    return {
        "task_name": TASK_NAME,
        "user": user.get("name", ""),
        "user_sid": user.get("sid", ""),
        **action,
        "xml": build_task_xml(
            user_sid=user.get("sid", ""),
            command=action["command"],
            arguments=action["arguments"],
            working_directory=action["working_directory"],
            start_boundary=_start_boundary(),
        ),
    }


def _preflight_problems(plan: dict) -> list[str]:
    problems = []
    if os.name != "nt":
        problems.append("o Agendador de Tarefas só existe no Windows")
    if not plan.get("user_sid"):
        problems.append("não foi possível identificar o usuário do Windows")
    if not os.path.exists(plan["command"]):
        problems.append(f"interpretador não encontrado: {plan['command']} (execute o run.bat uma vez)")
    if not os.path.exists(os.path.join(plan["working_directory"], "app", "backup", "sync.py")):
        problems.append("a pasta do projeto não contém app/backup/sync.py")
    return problems


def install(*, dry_run: bool = False) -> dict:
    plan = install_plan()
    problems = _preflight_problems(plan)
    command = ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", "<definição>", "/F"]
    if problems or dry_run:
        return {"ok": not problems, "changed": False, "dry_run": dry_run, "problems": problems, "plan": plan, "command": command}
    handle, xml_path = tempfile.mkstemp(prefix="sgaa-backup-task-", suffix=".xml")
    os.close(handle)
    try:
        with open(xml_path, "w", encoding="utf-16") as stream:
            stream.write(plan["xml"])
        command[5] = xml_path
        result = _run(command)
    finally:
        os.remove(xml_path)
    if result.returncode != 0:
        return {"ok": False, "changed": False, "problems": [_decode(result.stderr).strip() or "schtasks falhou"], "plan": plan, "command": command}
    state_code, problems = task_problems(query_task())
    return {"ok": state_code == STATE_ACTIVE, "changed": True, "state": state_code, "problems": problems, "plan": plan, "command": command}


def reconcile(*, dry_run: bool = False) -> dict:
    state_code, problems = task_problems(query_task())
    if state_code == STATE_ACTIVE:
        return {"ok": True, "changed": False, "state": state_code, "problems": []}
    outcome = install(dry_run=dry_run)
    outcome["previous_state"] = state_code
    outcome["previous_problems"] = problems
    return outcome


def uninstall(*, dry_run: bool = False) -> dict:
    command = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    if query_task() is None:
        return {"ok": True, "changed": False, "problems": [], "command": command}
    if dry_run:
        return {"ok": True, "changed": False, "dry_run": True, "problems": [], "command": command}
    result = _run(command)
    return {"ok": result.returncode == 0, "changed": result.returncode == 0, "problems": [] if result.returncode == 0 else [_decode(result.stderr).strip()], "command": command}


# ===================== CLI =====================


def _print_status() -> int:
    task = query_task()
    state_code, problems = task_problems(task)
    print(f"Tarefa: {TASK_NAME}")
    print(f"Estado: {state_code}")
    for problem in problems:
        print(f"  - {problem}")
    if task:
        print(f"Comando: {task.get('command')} {task.get('arguments')}")
        print(f"Pasta: {task.get('working_directory')}")
        print(f"Despertar: {task.get('repetition') or 'n/d'}  Conta: {task.get('user_id')} ({task.get('logon_type')})")
    expected = expected_action()
    print(f"Esperado: {expected['command']} {expected['arguments']} em {expected['working_directory']}")
    print(f"Banco coberto: {canonical_database_path()}")
    print("Periodicidade: a do SGAA (Banco de dados -> Intervalo de verificação); a tarefa só acorda o SGAA.")
    return 0 if state_code == STATE_ACTIVE else 1


def _print_outcome(outcome: dict) -> int:
    plan = outcome.get("plan") or {}
    if outcome.get("dry_run"):
        print("Simulação (--dry-run): nada foi alterado no Agendador de Tarefas.")
    if outcome.get("previous_state"):
        print(f"Estado anterior: {outcome['previous_state']}")
    if plan:
        print(f"Tarefa: {plan['task_name']}  Conta: {plan['user']} ({plan['user_sid']}), apenas com o usuário conectado")
        print(f"Comando: {plan['command']} {plan['arguments']}")
        print(f"Pasta: {plan['working_directory']}")
        print(f"Despertar: a cada {POLL_MINUTES} min; sem nova instância se a anterior ainda roda; limite {EXECUTION_TIME_LIMIT}")
    if outcome.get("command"):
        print("schtasks: " + " ".join(outcome["command"]))
    if outcome.get("dry_run") and plan.get("xml"):
        print(plan["xml"])
    for problem in outcome.get("problems") or []:
        print(f"Problema: {problem}")
    print("Resultado: " + ("ok" if outcome.get("ok") else "falhou") + (" (alterado)" if outcome.get("changed") else " (sem alteração)"))
    return 0 if outcome.get("ok") else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.backup.task_scheduler")
    parser.add_argument("action", choices=("status", "install", "reconcile", "uninstall"))
    parser.add_argument("--dry-run", action="store_true", help="mostra o que seria feito sem alterar nada")
    args = parser.parse_args(argv)
    if args.action == "status":
        return _print_status()
    handler = {"install": install, "reconcile": reconcile, "uninstall": uninstall}[args.action]
    return _print_outcome(handler(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
