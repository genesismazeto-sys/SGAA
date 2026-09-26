from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from app.password_tokens import (
    PURPOSE_FIRST_ACCESS,
    PURPOSE_PASSWORD_RESET,
    consume_password_token_and_set_password,
    issue_password_token,
    password_token_digest,
    resolve_password_token,
)
from app.prod1_schema import bootstrap_prod1_schema
from app.security.passwords import check_password, hash_password
from app.user_accounts import (
    CREDENTIAL_STATE_PENDING,
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_with_access_level,
    set_usuario_password_hash,
)


NOW = dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.timezone.utc)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(conn)
    return conn


def _user(conn, email: str, state: str) -> int:
    cursor = create_usuario_with_access_level(
        conn,
        email.split("@", 1)[0],
        email,
        hash_password("admin123"),
        "admin",
        "admin_total",
        credential_state=state,
    )
    conn.commit()
    return int(cursor.lastrowid)


def test_issue_stores_only_digest_supersedes_same_purpose_and_get_is_read_only():
    conn = _connection()
    user_id = _user(conn, "token@example.test", CREDENTIAL_STATE_PENDING)
    first = "A" * 43
    second = "B" * 43

    first_raw, first_id = issue_password_token(
        conn, user_id, PURPOSE_FIRST_ACCESS, now=NOW, token_factory=lambda _size: first
    )
    conn.commit()
    before = tuple(conn.execute("SELECT * FROM senha_tokens WHERE id=?", (first_id,)).fetchone())
    assert first_raw == first
    assert first not in repr(before)
    assert before[3] == password_token_digest(first)
    assert resolve_password_token(conn, first, purpose=PURPOSE_FIRST_ACCESS, now=NOW)
    after = tuple(conn.execute("SELECT * FROM senha_tokens WHERE id=?", (first_id,)).fetchone())
    assert after == before

    second_raw, second_id = issue_password_token(
        conn, user_id, PURPOSE_FIRST_ACCESS, now=NOW, token_factory=lambda _size: second
    )
    conn.commit()
    assert second_raw == second
    assert resolve_password_token(conn, first, purpose=PURPOSE_FIRST_ACCESS, now=NOW) is None
    assert resolve_password_token(conn, second, purpose=PURPOSE_PASSWORD_RESET, now=NOW) is None
    assert resolve_password_token(conn, second, purpose=PURPOSE_FIRST_ACCESS, now=NOW).id == second_id


def test_expiry_first_access_state_and_atomic_consumption_contract():
    conn = _connection()
    pending_id = _user(conn, "pending@example.test", CREDENTIAL_STATE_PENDING)
    personal_id = _user(conn, "personal@example.test", CREDENTIAL_STATE_PERSONAL)

    expired = "C" * 43
    issue_password_token(
        conn,
        pending_id,
        PURPOSE_PASSWORD_RESET,
        now=NOW,
        ttl=dt.timedelta(seconds=1),
        token_factory=lambda _size: expired,
    )
    conn.commit()
    assert resolve_password_token(
        conn, expired, purpose=PURPOSE_PASSWORD_RESET, now=NOW + dt.timedelta(seconds=2)
    ) is None

    personal_first = "D" * 43
    issue_password_token(
        conn,
        personal_id,
        PURPOSE_FIRST_ACCESS,
        now=NOW,
        token_factory=lambda _size: personal_first,
    )
    conn.commit()
    assert consume_password_token_and_set_password(
        conn,
        personal_first,
        PURPOSE_FIRST_ACCESS,
        hash_password("new-personal"),
        now=NOW,
    ) is None

    sibling = "E" * 43
    current = "F" * 43
    issue_password_token(
        conn,
        pending_id,
        PURPOSE_PASSWORD_RESET,
        now=NOW,
        token_factory=lambda _size: sibling,
    )
    issue_password_token(
        conn,
        pending_id,
        PURPOSE_FIRST_ACCESS,
        now=NOW,
        token_factory=lambda _size: current,
    )
    conn.commit()

    assert consume_password_token_and_set_password(
        conn,
        current,
        PURPOSE_FIRST_ACCESS,
        hash_password("chosen-secret"),
        now=NOW,
    ) == 2
    user = conn.execute("SELECT senha FROM usuarios WHERE id=?", (pending_id,)).fetchone()
    credential = conn.execute(
        "SELECT estado,auth_version FROM usuario_credenciais WHERE usuario_id=?",
        (pending_id,),
    ).fetchone()
    assert check_password(user["senha"], "chosen-secret")
    assert tuple(credential) == (CREDENTIAL_STATE_PERSONAL, 2)
    assert resolve_password_token(conn, sibling, purpose=PURPOSE_PASSWORD_RESET, now=NOW) is None
    assert resolve_password_token(conn, current, purpose=PURPOSE_FIRST_ACCESS, now=NOW) is None
    assert consume_password_token_and_set_password(
        conn,
        current,
        PURPOSE_FIRST_ACCESS,
        hash_password("second-submit"),
        now=NOW,
    ) is None


def _file_connection(path, *, timeout: float = 5.0) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def test_two_connections_race_for_one_token_and_exactly_one_wins(tmp_path):
    """Two live connections observe the same valid token; only one may consume it.

    Deterministic by construction -- the interleaving is driven by SQLite's
    write lock and by ordering the calls, never by sleeping.
    """
    db_path = tmp_path / "password_token_race.db"
    setup = _file_connection(db_path)
    bootstrap_prod1_schema(setup)
    user_id = _user(setup, "race@example.test", CREDENTIAL_STATE_PENDING)
    raw = "H" * 43
    issue_password_token(
        setup, user_id, PURPOSE_FIRST_ACCESS, now=NOW, token_factory=lambda _size: raw
    )
    setup.commit()
    original_hash = setup.execute(
        "SELECT senha FROM usuarios WHERE id=?", (user_id,)
    ).fetchone()["senha"]
    setup.close()

    conn_a = _file_connection(db_path, timeout=0)
    conn_b = _file_connection(db_path, timeout=0)

    # Both connections independently resolve the very same live token.
    seen_a = resolve_password_token(conn_a, raw, purpose=PURPOSE_FIRST_ACCESS, now=NOW)
    seen_b = resolve_password_token(conn_b, raw, purpose=PURPOSE_FIRST_ACCESS, now=NOW)
    assert seen_a is not None and seen_b is not None
    assert seen_a.id == seen_b.id

    # Leg 1 -- genuine write-lock contention. B holds the write lock, so A's
    # BEGIN IMMEDIATE is refused outright and leaves nothing half-written.
    conn_b.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError):
            consume_password_token_and_set_password(
                conn_a, raw, PURPOSE_FIRST_ACCESS, hash_password("loser-a"), now=NOW
            )
        assert not conn_a.in_transaction
    finally:
        conn_b.execute("ROLLBACK")

    # Leg 2 -- B wins the token it already resolved as valid.
    assert consume_password_token_and_set_password(
        conn_b, raw, PURPOSE_FIRST_ACCESS, hash_password("winner-b"), now=NOW
    ) == 2

    # Leg 3 -- A still holds its own earlier "valid" observation and loses
    # safely: no exception, no second write, no second consumption.
    assert consume_password_token_and_set_password(
        conn_a, raw, PURPOSE_FIRST_ACCESS, hash_password("loser-a"), now=NOW
    ) is None

    audit = _file_connection(db_path)
    stored = audit.execute("SELECT senha FROM usuarios WHERE id=?", (user_id,)).fetchone()["senha"]
    credential = audit.execute(
        "SELECT estado,auth_version FROM usuario_credenciais WHERE usuario_id=?", (user_id,)
    ).fetchone()
    tokens = audit.execute(
        "SELECT consumed_at,invalidated_at FROM senha_tokens WHERE usuario_id=?", (user_id,)
    ).fetchall()

    assert check_password(stored, "winner-b")
    assert not check_password(stored, "loser-a")
    assert stored != original_hash
    # A single password write happened, so a single auth_version bump happened.
    assert tuple(credential) == (CREDENTIAL_STATE_PERSONAL, 2)
    assert len([row for row in tokens if row["consumed_at"] is not None]) == 1
    assert resolve_password_token(audit, raw, purpose=PURPOSE_FIRST_ACCESS, now=NOW) is None

    conn_a.close()
    conn_b.close()
    audit.close()


def test_any_direct_password_change_invalidates_outstanding_tokens():
    conn = _connection()
    user_id = _user(conn, "invalidate@example.test", CREDENTIAL_STATE_PERSONAL)
    raw = "G" * 43
    issue_password_token(
        conn,
        user_id,
        PURPOSE_PASSWORD_RESET,
        now=NOW,
        token_factory=lambda _size: raw,
    )
    conn.commit()
    set_usuario_password_hash(
        conn,
        user_id,
        hash_password("direct-change"),
        credential_state=CREDENTIAL_STATE_PERSONAL,
    )
    conn.commit()
    assert resolve_password_token(conn, raw, purpose=PURPOSE_PASSWORD_RESET, now=NOW) is None
    assert conn.execute(
        "SELECT auth_version FROM usuario_credenciais WHERE usuario_id=?", (user_id,)
    ).fetchone()[0] == 2
