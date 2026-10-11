# coding: utf-8
"""MP-3 slice 4 on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``): the sequencer with the real tool.

No scripted children here: ``ops_backup`` runs ``tools/pg_backup.py backup`` and
``verify`` as subprocesses against a disposable database, copies the generation
to a second directory and rotates.  Without ``SGAA_PG_TEST_URL`` it skips
(REAL-PG EVIDENCE: ABSENT); the native ``pg_dump`` / ``pg_restore`` come from
``SGAA_PG_BIN_DIR`` as in the Layer-2 suite.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.mp2_pg_support import PG_URL, Registry
from tools import ops_backup as ob

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

pytest.importorskip("psycopg")
REPO_ROOT = Path(ob.__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def registry():
    registry = Registry("opsbk")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def database(registry):
    name, url = registry.create(template=registry.template)
    yield name, url
    registry.drop(name)


def test_three_generations_with_the_real_tool_keep_two_verified_sets_in_both_places(database, tmp_path, monkeypatch):
    name, url = database
    monkeypatch.setenv("DATABASE_URL", url)
    root, off = tmp_path / "primary", tmp_path / "off"
    tick = {"n": 0}

    def clock():
        tick["n"] += 1
        return datetime(2026, 10, 10, tzinfo=timezone.utc) + timedelta(seconds=tick["n"])

    last = None
    for _ in range(3):
        last = ob.run_generation(root, label="scheduled", generations=2, objects=False, off_platform=off, clock=clock)
        assert last["result"] == "GENERATION_COMPLETE"
        assert [s["exit"] for s in last["steps"]] == [0, 0]

    for directory in (root / "layer2", off / "layer2"):
        manifests = sorted(directory.glob("*.manifest.json"))
        assert len(manifests) == 2
        for manifest in manifests:
            # Each retained set verifies offline with the tool itself (seal, sizes, TOC).
            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "tools" / "pg_backup.py"), "verify", "--manifest", str(manifest)],
                cwd=REPO_ROOT, env=dict(os.environ), capture_output=True, text=True, timeout=300,
            )
            assert result.returncode == 0, result.stdout[-300:]
    assert last["rotation"]["primary"]["deleted"] == 1 and last["rotation"]["off_platform"]["deleted"] == 1


def test_the_command_line_reports_a_failed_backup_by_code_when_the_database_is_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/never_connected")
    out, err = io.StringIO(), io.StringIO()
    code = ob.main(["--root", str(tmp_path / "p"), "--off-platform", str(tmp_path / "o")], out=out, err=err)
    assert code == 1 and "STEP_FAILED_DATABASE_BACKUP" in err.getvalue()
    assert out.getvalue() == "" and not list((tmp_path / "o").rglob("*"))


def test_the_verified_generation_holds_exactly_the_live_business_state_until_a_write(database, tmp_path, monkeypatch):
    """The opening's proof that the pre-opening backup is current: Layer-2 digests == live fingerprint."""
    from tests.mp2_pg_support import adapter
    from tests.mp3_ledger_support import local_connector
    from tools import cutover_ledger

    name, url = database
    monkeypatch.setenv("DATABASE_URL", url)
    root, off = tmp_path / "primary", tmp_path / "off"
    ob.run_generation(root, label="pre-open", generations=2, objects=False, off_platform=off)
    generation = ob.verify_generation(root, off)
    observer = cutover_ledger.Observer(database_url=url, source_connector=local_connector(url))
    assert observer.backup_matches(generation["manifest_path"], observer.fingerprint()) is True
    conn = adapter(url)
    try:
        conn.execute("INSERT INTO cursos(nome, codigo, duracao_periodos) VALUES('Outro', 'OUT', 8)")
        conn.commit()
    finally:
        conn.close()
    assert observer.backup_matches(generation["manifest_path"], observer.fingerprint()) is False
    # and a damaged primary set is not a generation
    dump = next((root / "layer2").glob("*.dump"))
    dump.write_bytes(dump.read_bytes()[:-10])
    with pytest.raises(ob.Refused) as caught:
        ob.verify_generation(root, off)
    assert caught.value.code == "DATABASE_SET_INVALID"
