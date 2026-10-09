# coding: utf-8
"""STORAGE S3-B M1 RED extension: the live-intent delete gate on LEGACY targets (SQLite lane).

Material review finding M1 (supervisor-adjudicated): S3-B lets a replacement
intent target a legacy ARQUIVOS row (``google`` + ``active``,
``local_legacy`` + ``legacy_active``), so the live-target-intent delete gate
applies to EVERY row that can receive such an intent -- not only canonical
rows.  A legacy delete is refused while a target ``admin_arquivo`` intent is
LIVE (issued / verified AND unexpired): the row, the intent and the uploaded
bytes stay tracked, and no Drive trash / local removal happens.  Issued /
verified intents past ``expires_at`` never block; an allowed legacy delete
keeps its legacy provider behavior (Drive trash / local removal, row gone).

The frozen S3-B RED (``tests/test_storage_s3b_arquivos.py``) is reused, not
modified: its fixtures and helpers are imported from it.
"""

from __future__ import annotations

import secrets

import pytest

import main
from tests.storage_s3a_support import BUCKET, INTENT_TTL_SECONDS, PNG
from tests.storage_s3b_support import seed_admin_intent
from tests.test_storage_s3b_arquivos import (  # noqa: F401 - ``legacy_env`` is a fixture
    SLOTS,
    _answered,
    _arquivo,
    _as_admin,
    _db,
    _delete,
    _intent,
    _local_path,
    _refused,
    _seed,
    legacy_env,
)

LEGACY_TARGETS = ("google", "local")
LIVE_STATES = ("issued", "verified")
PAST_EXPIRY_STATES = ("issued", "verified")
DRIVE_ID = "drv-m1-target"
LOCAL_RELATIVE = "arquivos/m1-legado.pdf"


def _seed_legacy(env, kind) -> int:
    if kind == "google":
        return _seed("google", env, remote_file_id=DRIVE_ID, operation_key="m1-google-op")
    return _seed("local", env, filename=LOCAL_RELATIVE)


def _seed_target_intent(env, row_id, state):
    with main.app.app_context():
        return seed_admin_intent(
            _db(), env["store"], actor=env["admin_id"], submission_id=secrets.token_hex(16), slot=SLOTS[0],
            content=PNG, mime="image/png", now=env["clock"].now, admin_arquivo_id=row_id,
            verify=(state == "verified"),
        )


def _assert_legacy_bytes_untouched(env, kind):
    if kind == "google":
        assert env["drive"].trashed == [], "Drive was trashed under a live replacement intent"
    else:
        assert _local_path(env, LOCAL_RELATIVE).exists(), "the local legacy file was removed"


def _assert_legacy_delete_allowed(env, kind, row_id, response):
    assert _answered(response) and response.status_code == 302, response
    assert _arquivo(row_id) is None, "the legacy delete did not complete"
    if kind == "google":
        assert env["drive"].trashed == [DRIVE_ID], env["drive"].trashed
    else:
        assert not _local_path(env, LOCAL_RELATIVE).exists(), "legacy local removal behavior changed"


@pytest.mark.parametrize("state", LIVE_STATES)
@pytest.mark.parametrize("kind", LEGACY_TARGETS)
def test_M1_L1_to_L4_legacy_delete_is_refused_while_a_live_replacement_intent_exists(legacy_env, kind, state):
    """L1 google+issued, L2 google+verified, L3 local+issued, L4 local+verified."""
    env = legacy_env
    row_id = _seed_legacy(env, kind)
    intent = _seed_target_intent(env, row_id, state)
    row_before = _arquivo(row_id)
    assert _intent(intent.id)["state"] == state and _intent(intent.id)["expires_at"] > env["clock"].now
    _as_admin(env)

    refused = _delete(env, row_id)

    assert _refused(refused), refused
    assert _arquivo(row_id) == row_before, "the legacy row changed under a live replacement intent"
    expected_status = "active" if kind == "google" else "legacy_active"
    assert _arquivo(row_id)["storage_status"] == expected_status
    assert _intent(intent.id) is not None and _intent(intent.id)["state"] == state, "live intent tracking was lost"
    assert (BUCKET, intent.storage_key) in env["store"].objects
    assert "delete" not in env["store"].calls
    _assert_legacy_bytes_untouched(env, kind)

    # Once the window closes the intent is no longer live: the legacy delete proceeds
    # with its legacy provider behavior, without any scheduler / sweeper having run.
    env["clock"].advance(INTENT_TTL_SECONDS + 1)
    _assert_legacy_delete_allowed(env, kind, row_id, _delete(env, row_id))


@pytest.mark.parametrize("state", PAST_EXPIRY_STATES)
@pytest.mark.parametrize("kind", LEGACY_TARGETS)
def test_M1_L5_L6_a_target_intent_past_expires_at_never_blocks_a_legacy_delete(legacy_env, kind, state):
    """L5 issued past expires_at, L6 verified past expires_at (nothing ran the lifecycle)."""
    env = legacy_env
    row_id = _seed_legacy(env, kind)
    intent = _seed_target_intent(env, row_id, state)
    env["clock"].advance(INTENT_TTL_SECONDS + 1)
    row = _intent(intent.id)
    assert row["state"] == state and row["expires_at"] <= env["clock"].now
    _as_admin(env)
    _assert_legacy_delete_allowed(env, kind, row_id, _delete(env, row_id))
