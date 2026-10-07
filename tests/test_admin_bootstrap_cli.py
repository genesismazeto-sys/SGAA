# coding: utf-8
"""R5 -- ``python -m app.admin_bootstrap`` command-line contract.

Covers only what the real-PostgreSQL lane does not: the hidden, confirmed
password prompt, the refusal of a password argument, exit codes, and that no
secret reaches the output.  Every state assertion about created/activated
accounts lives in ``tests/test_pg_readiness_r5_admin_bootstrap_real_pg.py``.

The database is a private SQLite copy of the pytest session database (taken
with the sqlite3 backup API), so the canonical ``database.db`` is never opened
and the session database is never written.
"""
from __future__ import annotations

import getpass
import inspect
import os
import sqlite3

import pytest

from app import admin_bootstrap
from app import db as app_db
from tests.root_admin_test_config import TEST_ROOT_ADMIN_EMAIL

SECRET = "r5-cli-Synthetic-secret-9f3"


class _Prompt:
    """Hidden-prompt stand-in: returns scripted answers, records the prompts."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, text):
        self.prompts.append(text)
        return self.answers.pop(0)


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def database(tmp_path, monkeypatch):
    """A private copy of the session database whose admins are all pending."""
    source = sqlite3.connect(os.environ["APP_DATABASE"])
    path = str(tmp_path / "r5_cli.db")
    target = sqlite3.connect(path)
    try:
        source.backup(target)
    finally:
        source.close()
    target.execute(
        "UPDATE usuario_credenciais SET estado='pending' "
        "WHERE usuario_id IN (SELECT id FROM usuarios WHERE tipo='admin')"
    )
    target.commit()
    target.close()
    monkeypatch.setattr(app_db, "DATABASE", path)
    monkeypatch.setattr(app_db, "DATABASE_URL", "")
    return path


def _root_state(path):
    conn = _connect(path)
    try:
        return tuple(
            conn.execute(
                "SELECT u.id,u.senha,c.estado,c.auth_version FROM usuarios u "
                "JOIN usuario_credenciais c ON c.usuario_id=u.id WHERE u.email=?",
                (TEST_ROOT_ADMIN_EMAIL,),
            ).fetchone()
        )
    finally:
        conn.close()


def _assert_no_secret(captured, *secrets):
    for secret in secrets:
        assert secret not in captured.out
        assert secret not in captured.err


def test_default_prompt_is_the_hidden_getpass_prompt():
    assert inspect.signature(admin_bootstrap.main).parameters["prompt"].default is getpass.getpass


@pytest.mark.parametrize(
    "argv",
    [
        ["--email", TEST_ROOT_ADMIN_EMAIL, "--password", SECRET],
        [f"--password={SECRET}", "--email", TEST_ROOT_ADMIN_EMAIL],
        ["--email"],
        [],
    ],
    ids=["password-flag", "password-equals", "email-without-value", "no-arguments"],
)
def test_password_argument_and_bad_usage_are_refused_before_anything_runs(
    argv, monkeypatch, capsys
):
    def _no_connection():
        raise AssertionError("usage errors must not open the database")

    monkeypatch.setattr(admin_bootstrap, "_open_connection", _no_connection)
    prompt = _Prompt()
    assert admin_bootstrap.main(argv, prompt=prompt) == 2
    assert prompt.prompts == []
    captured = capsys.readouterr()
    assert "usage: python -m app.admin_bootstrap" in captured.err
    assert captured.out == ""


def test_confirmation_mismatch_exits_nonzero_and_writes_nothing(database, capsys):
    before = _root_state(database)
    prompt = _Prompt(SECRET, SECRET + "x")
    assert admin_bootstrap.main(["--email", TEST_ROOT_ADMIN_EMAIL], prompt=prompt) == 1
    assert len(prompt.prompts) == 2
    captured = capsys.readouterr()
    assert "do not match" in captured.err
    _assert_no_secret(captured, SECRET)
    assert _root_state(database) == before


def test_empty_password_exits_nonzero_and_writes_nothing(database, capsys):
    before = _root_state(database)
    prompt = _Prompt("")
    assert admin_bootstrap.main(["--email", TEST_ROOT_ADMIN_EMAIL], prompt=prompt) == 1
    assert len(prompt.prompts) == 1
    assert "empty password" in capsys.readouterr().err
    assert _root_state(database) == before


def test_refusal_is_decided_before_the_password_prompt(database, capsys):
    conn = _connect(database)
    conn.execute(
        "UPDATE usuario_credenciais SET estado='personal' WHERE usuario_id="
        "(SELECT id FROM usuarios WHERE email=?)",
        (TEST_ROOT_ADMIN_EMAIL,),
    )
    conn.commit()
    conn.close()
    before = _root_state(database)
    prompt = _Prompt()
    assert admin_bootstrap.main(["--email", "r5-other@sgaa-tests.invalid"], prompt=prompt) == 1
    assert prompt.prompts == []
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "bootstrap-admin: refused: a login-capable full administrator already exists" in captured.err
    assert _root_state(database) == before


def test_success_output_is_operational_only(database, capsys):
    usuario_id, old_hash, _estado, _version = _root_state(database)
    prompt = _Prompt(SECRET, SECRET)
    assert admin_bootstrap.main(["--email", TEST_ROOT_ADMIN_EMAIL], prompt=prompt) == 0
    assert prompt.prompts == ["New administrator password: ", "Confirm password: "]
    captured = capsys.readouterr()
    assert captured.out.strip() == (
        "bootstrap-admin: pending full administrator activated "
        f"(usuario_id={usuario_id} email={TEST_ROOT_ADMIN_EMAIL})"
    )
    assert captured.err == ""
    new_hash = _root_state(database)[1]
    assert new_hash != old_hash
    _assert_no_secret(captured, SECRET, new_hash, old_hash, "pbkdf2")
