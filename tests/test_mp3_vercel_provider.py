# coding: utf-8
"""MP-3 SPEC A17 finding 5: the platform's own record of the production project (``tools/vercel_provider.py``).

The governed deploy and the ledger ask the platform, through the user's pinned CLI, which deployments the
project holds, what files each one received and which one the public address resolves to.  The CLI is
scripted here (its answers are the shapes recorded on the rehearsal project, MP-3 A17); the live lane is
``test_mp3_vercel_live``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from tools import vercel_provider as vp

TEAM = "team_" + "T" * 24
PROJECT = "prj_" + "P" * 28
DEPLOYMENT = {"id": "dpl_" + "A" * 24, "url": "sgaa-x-team.vercel.app", "readyState": "READY", "target": "production",
              "projectId": PROJECT, "aliasAssigned": False}


class _Cli:
    """A scripted ``npx vercel``: answers by command, records every call and its environment."""

    def __init__(self, answers=None, deploy_stdout=None, returncode=0):
        self.answers = answers or {}
        self.deploy_stdout = deploy_stdout
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs.get("env") or {}))
        verb = command[3]
        if verb == "api":
            body = self.answers.get(command[4])
            stdout = json.dumps(body) if body is not None else "{}"
        elif verb == "deploy":
            stdout = self.deploy_stdout
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, self.returncode, stdout=stdout, stderr="")


def _cli(**kwargs):
    runner = _Cli(**kwargs)
    return vp.VercelCli(team_id=TEAM, project_id=PROJECT, runner=runner, npx="npx"), runner


def _code(call, *args, **kwargs):
    with pytest.raises(vp.Refused) as caught:
        call(*args, **kwargs)
    return caught.value.code


@pytest.mark.parametrize("team,project", [
    ("ej-883a", PROJECT), (TEAM, "sgaa-mp3-rehearsal"), ("", PROJECT), (TEAM, None), (TEAM, PROJECT + " --prod"),
])
def test_the_project_is_named_by_its_identifiers_and_nothing_else(team, project):
    assert _code(vp.VercelCli, team_id=team, project_id=project) == "PROVIDER_PROJECT_INVALID"


def test_every_call_is_the_pinned_cli_in_the_named_team():
    cli, runner = _cli(answers={f"/v13/deployments/{DEPLOYMENT['id']}": DEPLOYMENT})
    cli.deployment(DEPLOYMENT["id"])
    command, _env = runner.calls[0]
    assert command[:3] == ["npx", "--yes", vp.CLI_PACKAGE] and command[-2:] == ["--scope", TEAM]
    assert vp.CLI_PACKAGE == "vercel@63.1.2"


def test_a_deployment_is_an_upload_to_production_that_takes_no_alias_with_its_admission_on_the_deployment():
    cli, runner = _cli(answers={f"/v13/deployments/{DEPLOYMENT['id']}": DEPLOYMENT},
                       deploy_stdout=json.dumps({"status": "ok", "deployment": {"id": DEPLOYMENT["id"]}}))
    found = cli.deploy("C:/tmp/upload", {"SGAA_ADMISSION": "operator"})
    assert found["id"] == DEPLOYMENT["id"] and found["state"] == "READY" and found["target"] == "production"
    command, env = runner.calls[0]
    assert command[3:9] == ["deploy", "C:/tmp/upload", "--prod", "--skip-domain", "--yes", "--env"]
    assert command[9] == "SGAA_ADMISSION=operator"
    # The project is named by the environment: the CLI writes nothing into the uploaded directory.
    assert env["VERCEL_ORG_ID"] == TEAM and env["VERCEL_PROJECT_ID"] == PROJECT


def test_the_deployment_is_found_from_the_plain_output_of_a_terminal_too():
    host = DEPLOYMENT["url"]
    cli, runner = _cli(answers={f"/v13/deployments/{host}": DEPLOYMENT},
                       deploy_stdout=f"Vercel CLI 63.1.2\nhttps://{host}\n")
    assert cli.deploy("d", {})["id"] == DEPLOYMENT["id"]
    cli, runner = _cli(deploy_stdout="no address at all")
    assert _code(cli.deploy, "d", {}) == "PROVIDER_ANSWER_INVALID"


def test_a_deployment_of_another_project_or_a_cli_failure_is_refused():
    other = dict(DEPLOYMENT, projectId="prj_" + "O" * 28)
    cli, _runner = _cli(answers={f"/v13/deployments/{other['id']}": other})
    assert _code(cli.deployment, other["id"]) == "DEPLOYMENT_NOT_IN_THE_PROJECT"
    cli, _runner = _cli(answers={f"/v13/deployments/x": {"id": "not-an-id", **{k: v for k, v in DEPLOYMENT.items()
                                                                             if k != "id"}}})
    assert _code(cli.deployment, "x") == "PROVIDER_ANSWER_INVALID"
    cli, _runner = _cli(returncode=1)
    assert _code(cli.deployment, "x") == "PROVIDER_REFUSED"


def test_every_deployment_of_the_project_is_listed_across_pages():
    first = f"/v6/deployments?projectId={PROJECT}&limit=100"
    second = first + "&until=1700"
    cli, runner = _cli(answers={
        first: {"deployments": [{"uid": "dpl_" + "A" * 24, "url": "a.vercel.app", "readyState": "READY"}],
                "pagination": {"next": 1700}},
        second: {"deployments": [{"uid": "dpl_" + "B" * 24, "url": "b.vercel.app", "state": "ERROR"}],
                 "pagination": {"next": None}},
    })
    assert cli.deployments() == [
        {"id": "dpl_" + "A" * 24, "url": "https://a.vercel.app", "state": "READY"},
        {"id": "dpl_" + "B" * 24, "url": "https://b.vercel.app", "state": "ERROR"},
    ]


# The shape recorded on the rehearsal project: the uploaded source under ``src``, build outputs under ``out``.
TREE = [
    {"name": "src", "type": "directory", "children": [
        {"name": "main.py", "type": "file", "uid": "1" * 40},
        {"name": "app", "type": "directory", "children": [{"name": "__init__.py", "type": "file", "uid": "2" * 40}]},
    ]},
    {"name": "out", "type": "directory", "children": [{"name": "services", "type": "directory", "children": []}]},
]


def test_the_uploaded_files_are_read_from_the_platforms_source_tree_by_their_content_digest():
    files = vp.files_from_tree(TREE)
    assert files == {"main.py": "1" * 40, "app/__init__.py": "2" * 40}
    assert vp.content_sha1(b"abc") == "a9993e364706816aba3e25717850c26c9cd0d89d"
    assert vp.files_sha256(files) == vp.files_sha256(dict(reversed(list(files.items()))))
    assert vp.files_sha256(files) != vp.files_sha256({**files, "main.py": "3" * 40})
    for broken in ([], [{"name": "out", "type": "directory"}], [TREE[0], TREE[0]],
                   [{"name": "src", "type": "directory", "children": [{"name": "../x", "type": "file", "uid": "1"}]}],
                   [{"name": "src", "type": "directory", "children": [{"name": "a/b", "type": "file", "uid": "1"}]}],
                   "not a tree"):
        assert _code(vp.files_from_tree, broken) == "PROVIDER_ANSWER_INVALID", broken


def test_the_alias_resolves_to_the_deployment_the_platform_serves_and_promote_and_remove_name_it():
    cli, runner = _cli(answers={"/v13/deployments/sgaa.vercel.app": DEPLOYMENT})
    assert cli.alias_target("sgaa.vercel.app") == DEPLOYMENT["id"]
    cli.promote(DEPLOYMENT["id"])
    cli.remove(DEPLOYMENT["id"])
    assert runner.calls[1][0][3:6] == ["promote", DEPLOYMENT["id"], "--yes"]
    assert runner.calls[2][0][3:6] == ["remove", DEPLOYMENT["id"], "--yes"]


def test_on_windows_the_cli_runs_through_node_so_no_shell_parses_an_api_path(tmp_path, monkeypatch):
    """A .cmd shim is parsed by cmd.exe, which splits ``/v6/deployments?projectId=..&limit=..`` at '&'."""
    shim = tmp_path / "npx.cmd"
    shim.write_text("@echo off")
    script = tmp_path / "node_modules" / "npm" / "bin" / "npx-cli.js"
    script.parent.mkdir(parents=True)
    script.write_text("// npx")
    monkeypatch.setattr(vp.os, "name", "nt")
    monkeypatch.setattr(vp.shutil, "which", lambda name: str(shim) if name == "npx" else "C:/node/node.exe")
    cli = vp.VercelCli(team_id=TEAM, project_id=PROJECT)
    command = cli._command("api", "/v6/deployments?projectId=x&limit=100")
    assert command[:2] == ["C:/node/node.exe", str(script)] and "/v6/deployments?projectId=x&limit=100" in command
    script.unlink()
    with pytest.raises(vp.Refused) as caught:
        cli._command("api", "/x")
    assert caught.value.code == "PROVIDER_UNAVAILABLE"
