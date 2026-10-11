# coding: utf-8
"""The platform's own record of the production project -- through the user's Vercel CLI (MP-3 SPEC A17).

WHY THIS EXISTS
    A digest the operator types proves nothing about what the platform serves.  The governed deploy
    (``tools/deploy_audit deploy`` / ``promote``) and the cutover ledger ask the platform itself: which
    deployments the production project holds, what files each one received (the platform names every
    uploaded file by the SHA-1 of its bytes), which deployment the public address resolves to.  Every
    call goes through the pinned, user-authenticated CLI (``vercel api``, ``deploy``, ``promote``,
    ``remove``); this module holds no token and reads no credential file.  The deployment is created
    with the project named by the environment (``VERCEL_ORG_ID`` / ``VERCEL_PROJECT_ID``), so the CLI
    writes nothing into the uploaded directory.

OUTPUT
    Deployment identifiers, states and per-file SHA-1 digests: no secret, no file content.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from urllib.parse import quote

CLI_PACKAGE = "vercel@63.1.2"
DEPLOY_TIMEOUT_SECONDS = 15 * 60
API_TIMEOUT_SECONDS = 180
_DEPLOYMENT_ID = re.compile(r"dpl_[A-Za-z0-9]{8,64}")
_DEPLOYMENT_URL = re.compile(r"https://([a-z0-9-]+\.vercel\.app)\b")
_TEAM = re.compile(r"team_[A-Za-z0-9]{8,64}")
_PROJECT = re.compile(r"prj_[A-Za-z0-9]{8,64}")


class Refused(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def files_from_tree(tree) -> dict:
    """``{path: sha1}`` of the uploaded source as the platform lists it (its ``src`` directory)."""
    files: dict[str, str] = {}

    def walk(nodes, prefix):
        for node in nodes:
            name = str(node.get("name") or "")
            if not name or "/" in name or name in (".", ".."):
                raise Refused("PROVIDER_ANSWER_INVALID")
            if node.get("type") == "directory":
                walk(node.get("children") or [], prefix + name + "/")
            elif node.get("type") == "file":
                files[prefix + name] = str(node.get("uid") or "")

    try:
        source = [node for node in tree if node.get("name") == "src" and node.get("type") == "directory"]
        if len(source) != 1:
            raise Refused("PROVIDER_ANSWER_INVALID", "no single uploaded source tree")
        walk(source[0].get("children") or [], "")
    except (AttributeError, TypeError):
        raise Refused("PROVIDER_ANSWER_INVALID") from None
    return files


def files_sha256(files: dict) -> str:
    """SHA-256 of the sorted ``path NUL sha1`` list: one value for one uploaded file set."""
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode("utf-8", "surrogatepass") + b"\x00" + files[path].encode("ascii") + b"\n")
    return digest.hexdigest()


def content_sha1(data: bytes) -> str:
    """How the platform names an uploaded file (the SHA-1 of its bytes)."""
    return hashlib.sha1(data).hexdigest()


class VercelCli:
    """The production project's deployments, as the platform records them."""

    def __init__(self, *, team_id: str, project_id: str, runner=subprocess.run, npx: str | None = None) -> None:
        if not _TEAM.fullmatch(str(team_id or "")) or not _PROJECT.fullmatch(str(project_id or "")):
            raise Refused("PROVIDER_PROJECT_INVALID", "a team_... and a prj_... identifier")
        self.team_id = team_id
        self.project_id = project_id
        self._runner = runner
        self._npx = npx

    def _command(self, *arguments) -> list[str]:
        npx = self._npx or shutil.which("npx") or "npx"
        return [npx, "--yes", CLI_PACKAGE, *arguments, "--scope", self.team_id]

    def _run(self, arguments, *, timeout, extra_env=None):
        env = dict(os.environ)
        env.update(extra_env or {})
        try:
            done = self._runner(self._command(*arguments), capture_output=True, text=True, timeout=timeout,
                                env=env, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            raise Refused("PROVIDER_UNAVAILABLE") from None
        if done.returncode != 0:
            raise Refused("PROVIDER_REFUSED", f"exit {done.returncode}")
        return done.stdout or ""

    def api(self, path: str):
        try:
            return json.loads(self._run(["api", path], timeout=API_TIMEOUT_SECONDS))
        except ValueError:
            raise Refused("PROVIDER_ANSWER_INVALID") from None

    # -- what the platform holds ------------------------------------------------

    def deployment(self, id_or_host: str) -> dict:
        """``id``, ``url`` (host), ``state``, ``target``, ``project`` of one deployment."""
        answer = self.api(f"/v13/deployments/{quote(id_or_host, safe='')}")
        try:
            found = {"id": str(answer["id"]), "url": str(answer["url"]), "state": str(answer["readyState"]),
                     "target": str(answer.get("target") or ""), "project": str(answer["projectId"]),
                     "aliased": bool(answer.get("aliasAssigned"))}
        except (KeyError, TypeError):
            raise Refused("PROVIDER_ANSWER_INVALID") from None
        if not _DEPLOYMENT_ID.fullmatch(found["id"]):
            raise Refused("PROVIDER_ANSWER_INVALID")
        if found["project"] != self.project_id:
            raise Refused("DEPLOYMENT_NOT_IN_THE_PROJECT")
        return found

    def deployments(self) -> list[dict]:
        """Every deployment of the project the platform still holds (all states), following pages."""
        found: list[dict] = []
        until = None
        for _page in range(100):
            path = f"/v6/deployments?projectId={self.project_id}&limit=100" + (f"&until={until}" if until else "")
            answer = self.api(path)
            try:
                for item in answer["deployments"]:
                    found.append({"id": str(item["uid"]), "url": "https://" + str(item["url"]),
                                  "state": str(item.get("readyState") or item.get("state") or "")})
                until = (answer.get("pagination") or {}).get("next")
            except (KeyError, TypeError, AttributeError):
                raise Refused("PROVIDER_ANSWER_INVALID") from None
            if not until:
                return found
        raise Refused("PROVIDER_ANSWER_INVALID", "too many pages")

    def files(self, deployment_id: str) -> dict:
        return files_from_tree(self.api(f"/v6/deployments/{quote(deployment_id, safe='')}/files"))

    def alias_target(self, host: str) -> str:
        """The deployment the public address serves now, as the platform resolves the alias."""
        return self.deployment(host)["id"]

    # -- what the operator does through it --------------------------------------------

    def deploy(self, directory: str, env: dict) -> dict:
        """Upload ``directory`` as a production deployment that takes no alias (promoted separately)."""
        arguments = ["deploy", str(directory), "--prod", "--skip-domain", "--yes"]
        for name, value in sorted(env.items()):
            arguments += ["--env", f"{name}={value}"]
        output = self._run(arguments, timeout=DEPLOY_TIMEOUT_SECONDS,
                           extra_env={"VERCEL_ORG_ID": self.team_id, "VERCEL_PROJECT_ID": self.project_id})
        identifier = None
        try:
            identifier = str(json.loads(output)["deployment"]["id"])
        except (ValueError, KeyError, TypeError):
            match = _DEPLOYMENT_URL.search(output)
            identifier = match.group(1) if match else None
        if not identifier:
            raise Refused("PROVIDER_ANSWER_INVALID", "the deployment was not named")
        return self.deployment(identifier)

    def promote(self, deployment_id: str) -> None:
        self._run(["promote", deployment_id, "--yes"], timeout=API_TIMEOUT_SECONDS)

    def remove(self, deployment_id: str) -> None:
        self._run(["remove", deployment_id, "--yes"], timeout=API_TIMEOUT_SECONDS)


__all__ = ["CLI_PACKAGE", "Refused", "VercelCli", "content_sha1", "files_from_tree", "files_sha256"]
