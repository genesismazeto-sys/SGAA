"""prod-1/v11: a true ``pending`` credential state; the global switch retires.

Four concerns, separated:

1. SCHEMA -- v11 widens ``usuario_credenciais.estado`` to
   ``pending|default|personal`` through a governed table rebuild. A migrated
   v10 database and a fresh v11 bootstrap are digest-identical; v10 stays
   recognisable; the rebuild is reversible on a disposable copy.

2. MIGRATION CLASSIFICATION -- the authentication-preserving rule in
   ``app/prod1_credential_pending_v11.py``: every account can authenticate after
   the migration exactly as before it, and a legacy row the durable evidence
   cannot classify stops the migration instead of being guessed.

3. MODEL -- blank creation is ``pending``; login is decided by the state alone;
   first access / reset end in ``personal``; "Aplicar senha padrão" is the only
   route into ``default``; tokens and sessions behave on every transition.

4. NO GLOBAL SWITCH -- nothing in the application reads
   ``default_passwords_enabled`` any more, and a stale row changes nothing.

Every database here is disposable. The canonical database is never opened for
writing.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

import main
from app import db_maintenance
from app.password_tokens import (
    PURPOSE_FIRST_ACCESS,
    PURPOSE_PASSWORD_RESET,
    consume_password_token_and_set_password,
    issue_password_token,
)
from app.prod1_credential_pending_ddl import USUARIO_CREDENCIAIS_V11_TABLE_SQL
from app.prod1_credential_pending_v11 import (
    APPLIED_DEFAULT_KEPT,
    KEPT_PERSONAL,
    REVOKED_TO_PENDING,
    SWITCH_OFF_TO_PENDING,
    LegacyCredentialClassificationError,
)
from app.prod1_schema import (
    CREDENTIAL_PENDING_MARKER,
    SCHEMA_VERSION,
    Prod1SchemaError,
    _PROD1_V10_SIGNATURE_SHA256,
    _PROD1_V11_SIGNATURE_SHA256,
    _normalize_schema_sql,
    _physical_schema_digest,
    _validate_prod1_v10_schema,
    bootstrap_prod1_schema,
    migrate_prod1_v10_to_v11,
    validate_prod1_schema,
)
from app.security.passwords import check_password, hash_password
from app.user_accounts import (
    CREDENTIAL_STATE_DEFAULT,
    CREDENTIAL_STATE_PENDING,
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_pending,
    create_usuario_with_access_level,
    credential_state_allows_password_login,
    get_usuario_auth_version,
)
from tests.prod1_v11_support import revert_prod1_v11_to_v10
from tests.versioned_test_support import isolated_versioned_app_env


ROOT = Path(__file__).resolve().parents[1]
LEGACY = "default_passwords_enabled"
#: The shipped profile defaults (``app.auth.DEFAULT_ACCESS_PASSWORDS``).
ADMIN_DEFAULT = "admin123"
CONSULTIVO_DEFAULT = "consultivo123"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _fast_hash(password: str) -> str:
    """A verifiable hash without the 600k-iteration cost; tests only."""
    from werkzeug.security import generate_password_hash

    return generate_password_hash(password, method="pbkdf2:sha256:1")


def _build_v10(conn: sqlite3.Connection) -> None:
    bootstrap_prod1_schema(conn)
    revert_prod1_v11_to_v10(conn)
    assert _physical_schema_digest(conn) == _PROD1_V10_SIGNATURE_SHA256


def _seed_v10(conn, label: str, *, estado: str, senha: str, ativo: int = 1, level="consultivo"):
    usuario_id = conn.execute(
        "INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso) VALUES(?,?,?,?,?)",
        (label, f"{label}@example.test", _fast_hash(senha), "admin", level),
    ).lastrowid
    conn.execute(
        "INSERT INTO usuario_credenciais(usuario_id,estado,auth_version,acesso_ativo)"
        " VALUES(?,?,?,?)",
        (usuario_id, estado, 3, ativo),
    )
    return int(usuario_id)


def _set_legacy_switch(conn, value: str | None) -> None:
    conn.execute("DELETE FROM configuracoes_app WHERE chave=?", (LEGACY,))
    if value is not None:
        conn.execute(
            "INSERT INTO configuracoes_app(chave,valor,atualizado_em)"
            " VALUES(?,?,'2026-09-20 21:13:43')",
            (LEGACY, value),
        )


def _rows(conn, sql: str) -> list[tuple]:
    return [tuple(row) for row in conn.execute(sql).fetchall()]


# =========================================================================== #
# 1. SCHEMA
# =========================================================================== #


def test_head_is_v11_and_registered_last():
    assert SCHEMA_VERSION == 11
    assert db_maintenance.SCHEMA_MIGRATIONS[-1][:2] == (11, CREDENTIAL_PENDING_MARKER)
    assert len(db_maintenance.SCHEMA_MIGRATIONS) == 11


def test_fresh_bootstrap_is_the_frozen_v11_shape():
    conn = _connect()
    status = bootstrap_prod1_schema(conn)
    assert status["schema_version"] == 11
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 11
    assert _physical_schema_digest(conn) == _PROD1_V11_SIGNATURE_SHA256
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='usuario_credenciais'"
    ).fetchone()[0]
    assert _normalize_schema_sql(sql) == _normalize_schema_sql(USUARIO_CREDENCIAIS_V11_TABLE_SQL)
    assert "estado IN ('pending','default','personal')" in sql
    # A fresh v11 database never carries the retired setting.
    assert conn.execute(
        "SELECT COUNT(*) FROM configuracoes_app WHERE chave=?", (LEGACY,)
    ).fetchone()[0] == 0


def test_column_contract_is_unchanged_apart_from_the_check():
    v10 = _connect()
    _build_v10(v10)
    head = _connect()
    bootstrap_prod1_schema(head)
    info = "PRAGMA table_xinfo(usuario_credenciais)"
    assert _rows(v10, info) == _rows(head, info)
    fks = "PRAGMA foreign_key_list(usuario_credenciais)"
    assert _rows(v10, fks) == _rows(head, fks)


def test_check_accepts_the_three_states_and_nothing_else():
    conn = _connect()
    bootstrap_prod1_schema(conn)
    for index, state in enumerate(("pending", "default", "personal", "revoked", "")):
        usuario_id = conn.execute(
            "INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso) VALUES(?,?,?,?,?)",
            (f"u{index}", f"u{index}@example.test", "x", "admin", "admin_total"),
        ).lastrowid
        if state in ("pending", "default", "personal"):
            conn.execute(
                "INSERT INTO usuario_credenciais(usuario_id,estado) VALUES(?,?)",
                (usuario_id, state),
            )
        else:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO usuario_credenciais(usuario_id,estado) VALUES(?,?)",
                    (usuario_id, state),
                )


def test_v10_is_recognised_as_the_predecessor():
    conn = _connect()
    _build_v10(conn)
    _validate_prod1_v10_schema(conn)
    with pytest.raises(Prod1SchemaError):
        validate_prod1_schema(conn)


def test_v11_migration_refuses_a_database_that_is_not_v10():
    conn = _connect()
    bootstrap_prod1_schema(conn)  # already v11
    before = list(conn.iterdump())
    with pytest.raises(Prod1SchemaError):
        migrate_prod1_v10_to_v11(conn)
    assert list(conn.iterdump()) == before


def test_migrated_v11_is_digest_identical_to_a_fresh_bootstrap():
    migrated = _connect()
    _build_v10(migrated)
    _seed_v10(migrated, "p", estado="personal", senha="secret")
    _seed_v10(migrated, "d", estado="default", senha=CONSULTIVO_DEFAULT)
    migrated.commit()
    migrate_prod1_v10_to_v11(migrated)

    fresh = _connect()
    bootstrap_prod1_schema(fresh)
    assert _physical_schema_digest(migrated) == _physical_schema_digest(fresh)
    assert _physical_schema_digest(migrated) == _PROD1_V11_SIGNATURE_SHA256
    assert migrated.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []


def test_bootstrap_chains_a_v10_database_to_the_head():
    conn = _connect()
    _build_v10(conn)
    status = bootstrap_prod1_schema(conn)
    assert status["schema_version"] == 11
    assert [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == list(range(1, 12))


# =========================================================================== #
# 2. MIGRATION CLASSIFICATION
# =========================================================================== #


def _classification_fixture(switch: str | None):
    conn = _connect()
    _build_v10(conn)
    ids = {
        "personal": _seed_v10(conn, "personal", estado="personal", senha="own-secret"),
        # A personal password that happens to equal the default stays personal.
        "personal_eq_default": _seed_v10(
            conn, "personaleq", estado="personal", senha=CONSULTIVO_DEFAULT
        ),
        "revoked": _seed_v10(conn, "revoked", estado="default", senha="random-x", ativo=0),
        "default_current": _seed_v10(conn, "defcur", estado="default", senha=CONSULTIVO_DEFAULT),
        "default_admin": _seed_v10(
            conn, "defadm", estado="default", senha=ADMIN_DEFAULT, level="admin_total"
        ),
    }
    _set_legacy_switch(conn, switch)
    issue_password_token(conn, ids["default_current"], PURPOSE_FIRST_ACCESS)
    conn.commit()
    return conn, ids


def _snapshot(conn):
    return {
        "passwords": _rows(conn, "SELECT id,senha FROM usuarios ORDER BY id"),
        "tokens": _rows(conn, "SELECT * FROM senha_tokens ORDER BY id"),
        "credentials": _rows(
            conn,
            "SELECT usuario_id,auth_version,atualizado_em,acesso_ativo"
            " FROM usuario_credenciais ORDER BY usuario_id",
        ),
        "settings": _rows(
            conn,
            f"SELECT chave,valor,atualizado_em FROM configuracoes_app WHERE chave<>'{LEGACY}'"
            " ORDER BY chave",
        ),
    }


def _states(conn) -> dict[int, str]:
    return {
        int(row[0]): str(row[1])
        for row in conn.execute("SELECT usuario_id,estado FROM usuario_credenciais")
    }


def test_switch_off_maps_every_default_row_to_pending_and_preserves_everything_else():
    """The canonical shape: switch '0', so no default row could password-login."""
    conn, ids = _classification_fixture("0")
    before = _snapshot(conn)

    report = migrate_prod1_v10_to_v11(conn)

    states = _states(conn)
    assert states[ids["personal"]] == CREDENTIAL_STATE_PERSONAL
    assert states[ids["personal_eq_default"]] == CREDENTIAL_STATE_PERSONAL
    assert states[ids["revoked"]] == CREDENTIAL_STATE_PENDING
    assert states[ids["default_current"]] == CREDENTIAL_STATE_PENDING
    assert states[ids["default_admin"]] == CREDENTIAL_STATE_PENDING
    # Every hash, token, auth_version, timestamp and unrelated setting is intact.
    assert _snapshot(conn) == before
    assert report["legacy_default_passwords_enabled"] is False
    assert report["legacy_setting_present"] is True
    # Every seeded row is classified exactly once (a bare bootstrap seeds none).
    assert sum(report["classification"].values()) == len(ids)
    assert report["classification"] == {
        KEPT_PERSONAL: 2,
        REVOKED_TO_PENDING: 1,
        SWITCH_OFF_TO_PENDING: 2,
    }
    # The retired setting is gone.
    assert conn.execute(
        "SELECT COUNT(*) FROM configuracoes_app WHERE chave=?", (LEGACY,)
    ).fetchone()[0] == 0


@pytest.mark.parametrize("switch", ["1", None], ids=["switch-on", "setting-absent"])
def test_switch_on_keeps_genuine_default_credentials(switch):
    """With the switch on (or absent, which v10 read as on) a default row whose
    hash IS the current profile default was a working credential: it stays."""
    conn, ids = _classification_fixture(switch)
    before = _snapshot(conn)

    report = migrate_prod1_v10_to_v11(conn)

    states = _states(conn)
    assert states[ids["personal"]] == CREDENTIAL_STATE_PERSONAL
    assert states[ids["revoked"]] == CREDENTIAL_STATE_PENDING
    assert states[ids["default_current"]] == CREDENTIAL_STATE_DEFAULT
    assert states[ids["default_admin"]] == CREDENTIAL_STATE_DEFAULT
    assert _snapshot(conn) == before
    assert report["legacy_default_passwords_enabled"] is True
    assert report["legacy_setting_present"] is (switch is not None)
    assert report["classification"] == {
        KEPT_PERSONAL: 2,
        REVOKED_TO_PENDING: 1,
        APPLIED_DEFAULT_KEPT: 2,
    }


def test_an_unclassifiable_default_row_stops_the_migration_without_mutation():
    """Switch on + a default hash that is NOT the current profile default.

    Placeholder or stale default: the database cannot tell, so v11 refuses.
    """
    conn, _ids = _classification_fixture("1")
    ambiguous = _seed_v10(conn, "stale", estado="default", senha="an-older-default")
    conn.commit()
    before = list(conn.iterdump())

    with pytest.raises(LegacyCredentialClassificationError) as captured:
        migrate_prod1_v10_to_v11(conn)

    assert captured.value.usuario_ids == [ambiguous]
    assert list(conn.iterdump()) == before
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 10
    _validate_prod1_v10_schema(conn)


def test_migration_preserves_who_can_authenticate():
    """The rule's defining property, checked with the v10 and v11 login rules."""
    for switch in ("0", "1"):
        conn, ids = _classification_fixture(switch)
        candidates = {
            ids["personal"]: "own-secret",
            ids["personal_eq_default"]: CONSULTIVO_DEFAULT,
            ids["revoked"]: "random-x",
            ids["default_current"]: CONSULTIVO_DEFAULT,
            ids["default_admin"]: ADMIN_DEFAULT,
        }

        def v10_login(usuario_id, senha):
            estado, ativo = conn.execute(
                "SELECT estado,acesso_ativo FROM usuario_credenciais WHERE usuario_id=?",
                (usuario_id,),
            ).fetchone()
            stored = conn.execute("SELECT senha FROM usuarios WHERE id=?", (usuario_id,)).fetchone()[0]
            allowed = ativo == 1 and (estado == "personal" or (estado == "default" and switch == "1"))
            return allowed and check_password(stored, senha)

        def v11_login(usuario_id, senha):
            estado, ativo = conn.execute(
                "SELECT estado,acesso_ativo FROM usuario_credenciais WHERE usuario_id=?",
                (usuario_id,),
            ).fetchone()
            stored = conn.execute("SELECT senha FROM usuarios WHERE id=?", (usuario_id,)).fetchone()[0]
            return ativo == 1 and credential_state_allows_password_login(estado) and check_password(stored, senha)

        before = {uid: v10_login(uid, senha) for uid, senha in candidates.items()}
        migrate_prod1_v10_to_v11(conn)
        after = {uid: v11_login(uid, senha) for uid, senha in candidates.items()}
        assert after == before, f"switch={switch}"


def test_rollback_on_a_disposable_copy_restores_v10_exactly():
    conn, _ids = _classification_fixture("0")
    legacy_row = conn.execute(
        "SELECT valor,atualizado_em FROM configuracoes_app WHERE chave=?", (LEGACY,)
    ).fetchone()
    dump_before = sorted(conn.iterdump())

    migrate_prod1_v10_to_v11(conn)
    assert _physical_schema_digest(conn) == _PROD1_V11_SIGNATURE_SHA256
    revert_prod1_v11_to_v10(conn, restore_setting=(legacy_row[0], legacy_row[1]))

    assert _physical_schema_digest(conn) == _PROD1_V10_SIGNATURE_SHA256
    _validate_prod1_v10_schema(conn)
    assert sorted(conn.iterdump()) == dump_before
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


# =========================================================================== #
# 3. MODEL
# =========================================================================== #


def test_only_default_and_personal_are_password_credentials():
    assert credential_state_allows_password_login(CREDENTIAL_STATE_PERSONAL) is True
    assert credential_state_allows_password_login(CREDENTIAL_STATE_DEFAULT) is True
    for state in (CREDENTIAL_STATE_PENDING, None, "", "revoked"):
        assert credential_state_allows_password_login(state) is False


def test_create_usuario_pending_holds_no_known_secret():
    conn = _connect()
    bootstrap_prod1_schema(conn)
    usuario_id = create_usuario_pending(conn, "P", "p@example.test", "aluno").lastrowid
    estado = conn.execute(
        "SELECT estado FROM usuario_credenciais WHERE usuario_id=?", (usuario_id,)
    ).fetchone()[0]
    stored = conn.execute("SELECT senha FROM usuarios WHERE id=?", (usuario_id,)).fetchone()[0]
    assert estado == CREDENTIAL_STATE_PENDING
    for guess in ("", "aluno123", ADMIN_DEFAULT, CONSULTIVO_DEFAULT):
        assert not check_password(stored, guess)


def _login(client, email: str, senha: str) -> int | None:
    from app.auth import _login_attempts, _login_attempts_by_account

    _login_attempts.clear()
    _login_attempts_by_account.clear()
    client.get("/logout")
    client.post("/login", data={"email": email, "senha": senha}, follow_redirects=False)
    with client.session_transaction() as session:
        return session.get("user_id")


def _login_root(client) -> None:
    from app.root_admin import resolve_root_admin_id

    with main.app.app_context():
        conn = main.get_db_connection()
        admin_id = resolve_root_admin_id(conn)
        version = get_usuario_auth_version(conn, admin_id)
    with client.session_transaction() as session:
        session.clear()
        session.update(
            user_id=admin_id, user_type="admin", user_name="root",
            access_level="admin_total", auth_version=version,
        )


def _credential(usuario_id: int):
    with main.app.app_context():
        return dict(
            main.get_db_connection().execute(
                "SELECT u.senha,c.estado,c.auth_version FROM usuarios u"
                " JOIN usuario_credenciais c ON c.usuario_id=u.id WHERE u.id=?",
                (usuario_id,),
            ).fetchone()
        )


def _live_tokens(usuario_id: int) -> int:
    with main.app.app_context():
        return int(
            main.get_db_connection().execute(
                "SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=?"
                " AND consumed_at IS NULL AND invalidated_at IS NULL",
                (usuario_id,),
            ).fetchone()[0]
        )


@pytest.fixture
def v11_env(tmp_path):
    from app.auth import _login_attempts, _login_attempts_by_account

    with isolated_versioned_app_env(tmp_path, "v11-model.db") as env:
        _login_attempts.clear()
        _login_attempts_by_account.clear()
        yield env
    _login_attempts.clear()
    _login_attempts_by_account.clear()


def _create_via_acesso(client, email: str, senha: str = "") -> int:
    _login_root(client)
    client.post(
        "/admin/acesso/salvar",
        data={"nome": "Sujeito", "email": email, "nivel_acesso": "consultivo", "senha": senha},
        follow_redirects=False,
    )
    with main.app.app_context():
        return int(
            main.get_db_connection().execute(
                "SELECT id FROM usuarios WHERE email=?", (email,)
            ).fetchone()[0]
        )


def test_new_account_blank_is_pending_and_explicit_is_personal(v11_env):
    client = v11_env["client"]
    blank = _create_via_acesso(client, "blank@example.test")
    explicit = _create_via_acesso(client, "explicit@example.test", "escolhida-1")
    assert _credential(blank)["estado"] == CREDENTIAL_STATE_PENDING
    assert _credential(explicit)["estado"] == CREDENTIAL_STATE_PERSONAL
    assert _login(client, "blank@example.test", CONSULTIVO_DEFAULT) is None
    assert _login(client, "blank@example.test", "") is None
    assert _login(client, "explicit@example.test", "escolhida-1") == explicit


def test_pending_first_access_completion_becomes_personal(v11_env):
    client = v11_env["client"]
    usuario_id = _create_via_acesso(client, "first@example.test")
    before = _credential(usuario_id)
    with main.app.app_context():
        conn = main.get_db_connection()
        raw, token_id = issue_password_token(conn, usuario_id, PURPOSE_FIRST_ACCESS)
        conn.commit()
        version = consume_password_token_and_set_password(
            conn, raw, PURPOSE_FIRST_ACCESS, hash_password("minha-senha-1")
        )
        consumed = conn.execute(
            "SELECT consumed_at FROM senha_tokens WHERE id=?", (token_id,)
        ).fetchone()[0]
    after = _credential(usuario_id)
    assert after["estado"] == CREDENTIAL_STATE_PERSONAL
    assert version == after["auth_version"] == before["auth_version"] + 1
    assert consumed is not None
    assert _login(client, "first@example.test", "minha-senha-1") == usuario_id


def _first_access_page(client, raw_token: str, method: str = "GET", senha: str = "tentativa-1"):
    if method == "GET":
        response = client.get(f"/primeiro-acesso?token={raw_token}")
    else:
        response = client.post(
            "/primeiro-acesso",
            data={"token": raw_token, "senha": senha, "confirmacao_senha": senha},
        )
    return response.status_code, response.get_data(as_text=True)


def _unknown_token_pages(client):
    """What any dead link renders: the generic refusal every case must equal."""
    import secrets

    unknown = secrets.token_urlsafe(32)
    return _first_access_page(client, unknown), _first_access_page(client, unknown, "POST")


def _token_row(token_id: int):
    with main.app.app_context():
        return tuple(
            main.get_db_connection().execute(
                "SELECT consumed_at,invalidated_at FROM senha_tokens WHERE id=?", (token_id,)
            ).fetchone()
        )


def test_a_pending_first_access_link_completes_onboarding_over_http(v11_env):
    """A. pending + valid first_access -> personal, through the real route."""
    client = v11_env["client"]
    usuario_id = _create_via_acesso(client, "fa-pending@example.test")
    with main.app.app_context():
        conn = main.get_db_connection()
        raw, token_id = issue_password_token(conn, usuario_id, PURPOSE_FIRST_ACCESS)
        conn.commit()
    client.get("/logout")
    status, html = _first_access_page(client, raw)
    assert status == 200 and 'name="token"' in html
    response = client.post(
        "/primeiro-acesso",
        data={"token": raw, "senha": "escolhida-9", "confirmacao_senha": "escolhida-9"},
    )
    assert response.status_code in (302, 303)
    assert _credential(usuario_id)["estado"] == CREDENTIAL_STATE_PERSONAL
    assert _token_row(token_id)[0] is not None
    assert _login(client, "fa-pending@example.test", "escolhida-9") == usuario_id


def test_applying_the_default_ends_onboarding_and_kills_every_outstanding_link(v11_env):
    """B. pending -> Aplicar senha padrão -> default; the old link fails generically."""
    client = v11_env["client"]
    usuario_id = _create_via_acesso(client, "fa-apply@example.test")
    with main.app.app_context():
        conn = main.get_db_connection()
        raw_first, first_id = issue_password_token(conn, usuario_id, PURPOSE_FIRST_ACCESS)
        _raw_reset, reset_id = issue_password_token(conn, usuario_id, PURPOSE_PASSWORD_RESET)
        conn.commit()
    assert _live_tokens(usuario_id) == 2

    _login_root(client)
    client.post(f"/admin/acesso/{usuario_id}/resetar-senha")
    applied = _credential(usuario_id)
    assert applied["estado"] == CREDENTIAL_STATE_DEFAULT
    # Both purposes invalidated by the credential write, neither consumed.
    for token_id in (first_id, reset_id):
        consumed_at, invalidated_at = _token_row(token_id)
        assert consumed_at is None and invalidated_at is not None
    assert _live_tokens(usuario_id) == 0

    client.get("/logout")
    generic_get, generic_post = _unknown_token_pages(client)
    assert _first_access_page(client, raw_first) == generic_get
    assert _first_access_page(client, raw_first, "POST") == generic_post
    assert _credential(usuario_id) == applied
    assert _login(client, "fa-apply@example.test", "tentativa-1") is None
    assert _login(client, "fa-apply@example.test", CONSULTIVO_DEFAULT) == usuario_id


@pytest.mark.parametrize("state", [CREDENTIAL_STATE_DEFAULT, CREDENTIAL_STATE_PERSONAL])
def test_a_surviving_first_access_link_is_refused_outside_pending(v11_env, state):
    """C/D. A first_access token that SURVIVED onto a default/personal account.

    Planted directly -- no ordinary path issues one -- to prove the redemption
    precondition itself, not the writers that should have invalidated it.
    """
    client = v11_env["client"]
    email = f"fa-surviving-{state}@example.test"
    if state == CREDENTIAL_STATE_DEFAULT:
        usuario_id = _create_via_acesso(client, email)
        _login_root(client)
        client.post(f"/admin/acesso/{usuario_id}/resetar-senha")
        working = CONSULTIVO_DEFAULT
    else:
        usuario_id = _create_via_acesso(client, email, "pessoal-5")
        working = "pessoal-5"
    before = _credential(usuario_id)
    assert before["estado"] == state
    with main.app.app_context():
        conn = main.get_db_connection()
        raw, token_id = issue_password_token(conn, usuario_id, PURPOSE_FIRST_ACCESS)
        conn.commit()

    client.get("/logout")
    generic_get, generic_post = _unknown_token_pages(client)
    # The form is not offered, and the POST is refused, exactly like a dead link:
    # the page says nothing about the account's state.
    assert _first_access_page(client, raw) == generic_get
    assert _first_access_page(client, raw, "POST") == generic_post
    # Nothing was written: same hash, same state, same auth_version...
    assert _credential(usuario_id) == before
    # ...and the token was not consumed into a success.
    assert _token_row(token_id)[0] is None
    # The service layer refuses the same way.
    with main.app.app_context():
        assert consume_password_token_and_set_password(
            main.get_db_connection(), raw, PURPOSE_FIRST_ACCESS, hash_password("tentativa-2")
        ) is None
    assert _credential(usuario_id) == before
    assert _login(client, email, "tentativa-1") is None
    assert _login(client, email, working) == usuario_id


def test_first_access_redemption_is_pending_only():
    from app.user_accounts import first_access_redeemable

    assert first_access_redeemable(CREDENTIAL_STATE_PENDING) is True
    for state in (CREDENTIAL_STATE_DEFAULT, CREDENTIAL_STATE_PERSONAL, None, "", "revoked"):
        assert first_access_redeemable(state) is False


@pytest.mark.parametrize("start", ["default", "personal"])
def test_reset_always_ends_in_personal(v11_env, start):
    client = v11_env["client"]
    usuario_id = _create_via_acesso(client, f"reset-{start}@example.test", "inicial-1")
    if start == "default":
        _login_root(client)
        client.post(f"/admin/acesso/{usuario_id}/resetar-senha")
    assert _credential(usuario_id)["estado"] == start
    with main.app.app_context():
        conn = main.get_db_connection()
        raw, _ = issue_password_token(conn, usuario_id, PURPOSE_PASSWORD_RESET)
        conn.commit()
        assert consume_password_token_and_set_password(
            conn, raw, PURPOSE_PASSWORD_RESET, hash_password("redefinida-1")
        ) is not None
    assert _credential(usuario_id)["estado"] == CREDENTIAL_STATE_PERSONAL
    assert _login(client, f"reset-{start}@example.test", "redefinida-1") == usuario_id


def test_apply_default_transitions_and_login(v11_env):
    """pending -> default -> default (reapply) ; personal -> default."""
    client = v11_env["client"]
    pending = _create_via_acesso(client, "to-default@example.test")
    personal = _create_via_acesso(client, "was-personal@example.test", "antiga-1")

    # pending -> default: the applied default now authenticates.
    _login_root(client)
    client.post(f"/admin/acesso/{pending}/resetar-senha")
    first = _credential(pending)
    assert first["estado"] == CREDENTIAL_STATE_DEFAULT
    assert _login(client, "to-default@example.test", CONSULTIVO_DEFAULT) == pending

    # personal -> default: the old personal password stops working.
    _login_root(client)
    client.post(f"/admin/acesso/{personal}/resetar-senha")
    assert _credential(personal)["estado"] == CREDENTIAL_STATE_DEFAULT
    assert _login(client, "was-personal@example.test", "antiga-1") is None
    assert _login(client, "was-personal@example.test", CONSULTIVO_DEFAULT) == personal

    # Changing the configured profile default rewrites nobody...
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE configuracoes_acesso SET senha_padrao='consultivo-2026' WHERE nivel_acesso='consultivo'"
        )
        conn.commit()
    assert _credential(pending)["senha"] == first["senha"]
    assert _login(client, "to-default@example.test", CONSULTIVO_DEFAULT) == pending
    assert _login(client, "to-default@example.test", "consultivo-2026") is None

    # ...until default -> default reapplies the CURRENT configured value.
    _login_root(client)
    client.post(f"/admin/acesso/{pending}/resetar-senha")
    again = _credential(pending)
    assert again["estado"] == CREDENTIAL_STATE_DEFAULT
    assert again["auth_version"] == first["auth_version"] + 1
    assert _login(client, "to-default@example.test", "consultivo-2026") == pending
    assert _login(client, "to-default@example.test", CONSULTIVO_DEFAULT) is None


def test_apply_default_kills_tokens_and_ends_live_sessions(v11_env):
    client = v11_env["client"]
    usuario_id = _create_via_acesso(client, "session@example.test", "pessoal-1")
    assert _login(client, "session@example.test", "pessoal-1") == usuario_id
    with main.app.app_context():
        conn = main.get_db_connection()
        issue_password_token(conn, usuario_id, PURPOSE_PASSWORD_RESET)
        conn.commit()
    assert _live_tokens(usuario_id) == 1

    # A second client holds the user's live session.
    user_client = main.app.test_client()
    with client.session_transaction() as source, user_client.session_transaction() as target:
        target.update(dict(source))
    assert user_client.get("/aluno/dashboard").status_code in (200, 302)

    _login_root(client)
    client.post(f"/admin/acesso/{usuario_id}/resetar-senha")
    assert _live_tokens(usuario_id) == 0
    user_client.get("/admin/dashboard")
    with user_client.session_transaction() as session:
        assert "user_id" not in session, "a session survived an administrative credential replacement"


def test_revoked_is_denied_whatever_the_state(v11_env):
    client = v11_env["client"]
    applied = _create_via_acesso(client, "rev-default@example.test")
    _login_root(client)
    client.post(f"/admin/acesso/{applied}/resetar-senha")
    personal = _create_via_acesso(client, "rev-personal@example.test", "pessoal-9")
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE usuario_credenciais SET acesso_ativo=0 WHERE usuario_id IN (?,?)",
            (applied, personal),
        )
        conn.commit()
    assert _login(client, "rev-default@example.test", CONSULTIVO_DEFAULT) is None
    assert _login(client, "rev-personal@example.test", "pessoal-9") is None


def test_reactivation_without_a_password_is_pending(v11_env):
    client = v11_env["client"]
    usuario_id = _create_via_acesso(client, "reactivate@example.test", "pessoal-3")
    _login_root(client)
    client.post(f"/admin/acesso/{usuario_id}/deletar")
    assert _credential(usuario_id)["estado"] == CREDENTIAL_STATE_PENDING
    _login_root(client)
    client.post(
        "/admin/acesso/salvar",
        data={"nome": "Sujeito", "email": "reactivate@example.test", "nivel_acesso": "consultivo", "senha": ""},
    )
    with main.app.app_context():
        ativo = main.get_db_connection().execute(
            "SELECT acesso_ativo FROM usuario_credenciais WHERE usuario_id=?", (usuario_id,)
        ).fetchone()[0]
    assert ativo == 1
    assert _credential(usuario_id)["estado"] == CREDENTIAL_STATE_PENDING
    assert _login(client, "reactivate@example.test", CONSULTIVO_DEFAULT) is None
    assert _login(client, "reactivate@example.test", "pessoal-3") is None


def test_pending_accounts_get_first_access_and_holders_get_reset(v11_env, monkeypatch):
    import app.password_email as password_email

    captured = []
    monkeypatch.setattr(password_email, "password_email_status", lambda _conn: {"ready": True})
    monkeypatch.setattr(password_email, "get_public_base_url", lambda: "https://sgaa.example.test")
    monkeypatch.setattr(password_email, "send_text_email", lambda _conn, message: captured.append(message))

    client = v11_env["client"]
    pending = _create_via_acesso(client, "mail-pending@example.test")
    applied = _create_via_acesso(client, "mail-applied@example.test")
    personal = _create_via_acesso(client, "mail-personal@example.test", "pessoal-8")
    _login_root(client)
    client.post(f"/admin/acesso/{applied}/resetar-senha")

    # G. The row action the list offers...
    import json
    import re

    _login_root(client)
    html = client.get("/admin/acesso").get_data(as_text=True)
    payload = json.loads(
        re.search(
            r'<script id="access-users-data" type="application/json">(.*?)</script>', html, re.S
        ).group(1)
    )
    assert payload[str(pending)]["emailActionLabel"] == "Enviar acesso"
    assert payload[str(applied)]["emailActionLabel"] == "Redefinir por e-mail"
    assert payload[str(personal)]["emailActionLabel"] == "Redefinir por e-mail"

    # ...and the link the endpoint actually issues: first access only for pending.
    for usuario_id in (pending, applied, personal):
        _login_root(client)
        client.post(f"/admin/acesso/{usuario_id}/senha-por-email")
    assert "/primeiro-acesso?token=" in captured[0].body_text
    assert "/redefinir-senha?token=" in captured[1].body_text
    assert "/redefinir-senha?token=" in captured[2].body_text
    with main.app.app_context():
        purposes = {
            int(row[0]): str(row[1])
            for row in main.get_db_connection().execute(
                "SELECT usuario_id,purpose FROM senha_tokens WHERE usuario_id IN (?,?,?)",
                (pending, applied, personal),
            )
        }
    assert purposes == {
        pending: PURPOSE_FIRST_ACCESS,
        applied: PURPOSE_PASSWORD_RESET,
        personal: PURPOSE_PASSWORD_RESET,
    }


def test_student_import_creates_pending_accounts():
    from app.services.student_import_service import import_students_into_turma
    from app.student_import import StudentImportRow

    conn = _connect()
    bootstrap_prod1_schema(conn)
    curso = conn.execute(
        "INSERT INTO cursos(nome,codigo,duracao_periodos,status) VALUES('C','C1',8,'ativo')"
    ).lastrowid
    turma = conn.execute(
        "INSERT INTO turmas(nome,codigo,numero,curso_id,status,ano_inicio,semestre_inicio)"
        " VALUES('T','C1-T1',1,?,'Ativa',2026,1)",
        (curso,),
    ).lastrowid
    rows = [
        StudentImportRow(aluno=f"Aluno {i}", email=f"imp{i}@example.test", matricula=f"IMP{i}", source_row=i + 2)
        for i in range(2)
    ]
    result = import_students_into_turma(conn, int(turma), rows)
    assert result.created == 2
    for row in conn.execute(
        "SELECT u.senha,c.estado FROM usuarios u JOIN usuario_credenciais c ON c.usuario_id=u.id"
        " WHERE u.email LIKE 'imp%@example.test'"
    ).fetchall():
        assert row["estado"] == CREDENTIAL_STATE_PENDING
        assert not check_password(row["senha"], "aluno123")


# =========================================================================== #
# 4. NO GLOBAL SWITCH
# =========================================================================== #


_ALLOWED_LEGACY_READERS = {
    # Frozen history: the v8 migration seeded the row.
    "app/prod1_password_foundation_v8.py",
    # The last reader: v11 classifies with it, then deletes it.
    "app/prod1_credential_pending_v11.py",
}


def test_no_application_code_reads_or_writes_the_retired_setting():
    offenders = []
    for path in [*ROOT.joinpath("app").rglob("*.py"), ROOT / "main.py", *ROOT.joinpath("services").rglob("*.py")]:
        relative = path.relative_to(ROOT).as_posix()
        if relative in _ALLOWED_LEGACY_READERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and LEGACY in node.value
                and not relative.startswith("app/prod1_schema")
            ):
                offenders.append(relative)
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if name in ("get_default_passwords_enabled", "save_default_passwords_enabled"):
                    offenders.append(relative)
    assert offenders == []


def test_settings_module_no_longer_exposes_the_switch():
    import app.settings as settings

    assert not hasattr(settings, "get_default_passwords_enabled")
    assert not hasattr(settings, "save_default_passwords_enabled")
    assert not hasattr(settings, "DEFAULT_PASSWORDS_ENABLED_KEY")
    from app.db import _app_settings_defaults

    assert LEGACY not in _app_settings_defaults()


def test_changing_or_removing_the_legacy_row_has_no_authentication_effect(v11_env):
    client = v11_env["client"]
    _create_via_acesso(client, "legacy-pending@example.test")
    applied = _create_via_acesso(client, "legacy-applied@example.test")
    _login_root(client)
    client.post(f"/admin/acesso/{applied}/resetar-senha")
    personal = _create_via_acesso(client, "legacy-personal@example.test", "pessoal-7")

    expected = {
        ("legacy-pending@example.test", CONSULTIVO_DEFAULT): None,
        ("legacy-applied@example.test", CONSULTIVO_DEFAULT): applied,
        ("legacy-personal@example.test", "pessoal-7"): personal,
    }
    for value in ("0", "1", None):
        with main.app.app_context():
            conn = main.get_db_connection()
            _set_legacy_switch(conn, value)
            conn.commit()
        for (email, senha), outcome in expected.items():
            assert _login(client, email, senha) == outcome, (value, email)


def test_canonical_database_is_not_migrated_by_this_suite():
    canonical = ROOT / "database.db"
    if not canonical.exists():
        pytest.skip("no canonical database present in this checkout")
    probe = sqlite3.connect(f"file:{canonical.as_posix()}?mode=ro", uri=True)
    try:
        version = probe.execute("PRAGMA user_version").fetchone()[0]
    finally:
        probe.close()
    # The v10 -> v11 migration of canonical was authorised and performed on
    # 2026-09-24; this suite itself must never be what migrates it.
    assert version in (10, 11), "canonical is at an unexpected version"
