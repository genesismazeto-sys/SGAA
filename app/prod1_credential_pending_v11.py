"""prod-1 v10 -> v11: a true ``pending`` credential state; the global switch retires.

WHAT CHANGES
    ``usuario_credenciais`` is rebuilt so ``estado`` accepts ``pending``, and
    the legacy ``configuracoes_app.default_passwords_enabled`` row is deleted.
    This migration is the last reader of that setting: it decides how each
    legacy ``default`` row is classified, and then nothing may read it again.

THE CLASSIFICATION RULE: PRESERVE WHO CAN AUTHENTICATE
    For every account, whether it can authenticate with a password -- and with
    which secret -- is the same after the migration as before it. Only durable
    evidence decides, in this order:

    1. ``personal``                           -> ``personal``   (untouched)
    2. ``default`` and ``acesso_ativo = 0``   -> ``pending``
       Revocation installs an unusable random hash and forces ``default``;
       the row never held a usable credential in the new sense.
    3. ``default`` while the legacy switch is OFF -> ``pending``
       Under v10 login refused every ``default`` row while the switch was
       off, so none of these could authenticate with a password. Making them
       ``default`` in a model without the switch would silently hand a shared,
       administrator-readable password back to every one of them.
    4. ``default`` while the switch is ON, and the stored hash verifies against
       the profile default currently configured for the account's level
       -> ``default``. The account holds, and can use today, a genuine shared
       default credential.
    5. ``default`` while the switch is ON, and the hash does NOT verify
       -> REFUSED. Such a hash is either an unusable placeholder (the account
       was created or reactivated while the switch was off) or a default
       applied under a since-edited profile value. The two cannot be told
       apart from the database, and each wants a different state, so the
       migration stops instead of guessing.

    A missing setting row is read as ON, exactly as the v10 reader did.

    Nothing is re-hashed and ``auth_version`` is not bumped: the rule is
    chosen so that no account's authentication outcome changes, so there is
    no session to end. A ``pending`` row keeps whatever ``usuarios.senha`` it
    had; login refuses ``pending`` by state before any hash comparison.

WHY A REBUILD
    SQLite cannot alter a CHECK constraint. Rows are staged in a TEMP table,
    the canonical v11 DDL is created under the real name -- so its stored SQL
    is textually the bootstrap's -- and every row is copied back with its
    ``usuario_id``, ``auth_version``, ``atualizado_em`` and ``acesso_ativo``
    unchanged. Nothing references ``usuario_credenciais``, so no other table
    is touched; foreign keys are still switched off for the swap and checked
    in full before commit.
"""

from __future__ import annotations

import sqlite3

from app.auth import (
    DEFAULT_ACCESS_PASSWORDS,
    canonicalize_access_level,
    default_access_level_for_user_type,
)
from app.prod1_credential_pending_ddl import USUARIO_CREDENCIAIS_V11_TABLE_SQL
from app.prod1_password_foundation_v8 import _configured_access_defaults
from app.security.passwords import check_password


LEGACY_DEFAULT_PASSWORDS_SETTING = "default_passwords_enabled"

_V11_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","credential_state":"pending|default|personal",'
    '"legacy_backfill":"authentication_preserving",'
    '"retired_setting":"default_passwords_enabled"}'
)

#: Classification outcomes, named so the migration report is self-describing.
KEPT_PERSONAL = "personal->personal"
REVOKED_TO_PENDING = "default(revoked)->pending"
SWITCH_OFF_TO_PENDING = "default(switch_off)->pending"
APPLIED_DEFAULT_KEPT = "default(current_default_hash)->default"
AMBIGUOUS = "default(switch_on,hash_not_current_default)->?"


class LegacyCredentialClassificationError(RuntimeError):
    """Durable evidence cannot classify some legacy ``default`` rows."""

    def __init__(self, usuario_ids: list[int]) -> None:
        self.usuario_ids = sorted(int(value) for value in usuario_ids)
        super().__init__(
            "prod-1/v11 cannot classify legacy default credential(s) for "
            f"usuarios.id={self.usuario_ids!r}: the default-password switch is on "
            "and the stored hash does not verify against the current profile "
            "default, so it is either an unusable placeholder or a stale default"
        )


def legacy_default_passwords_enabled(conn: sqlite3.Connection) -> bool:
    """The retired switch, read the way the v10 application read it."""
    row = conn.execute(
        "SELECT valor FROM configuracoes_app WHERE chave=?",
        (LEGACY_DEFAULT_PASSWORDS_SETTING,),
    ).fetchone()
    if row is None:
        return True
    return str(row[0]).strip() == "1"


def classify_legacy_credentials(conn: sqlite3.Connection) -> dict[int, str]:
    """Outcome per ``usuarios.id``. Read-only; hashes only where rule 4/5 needs it."""
    switch_on = legacy_default_passwords_enabled(conn)
    configured_defaults = _configured_access_defaults(conn) if switch_on else {}
    outcomes: dict[int, str] = {}
    for usuario_id, estado, acesso_ativo, stored_hash, user_type, access_level in conn.execute(
        """
        SELECT c.usuario_id,c.estado,c.acesso_ativo,u.senha,u.tipo,u.nivel_acesso
          FROM usuario_credenciais c
          JOIN usuarios u ON u.id=c.usuario_id
         ORDER BY c.usuario_id
        """
    ).fetchall():
        usuario_id = int(usuario_id)
        if estado == "personal":
            outcomes[usuario_id] = KEPT_PERSONAL
        elif int(acesso_ativo) != 1:
            outcomes[usuario_id] = REVOKED_TO_PENDING
        elif not switch_on:
            outcomes[usuario_id] = SWITCH_OFF_TO_PENDING
        else:
            level = canonicalize_access_level(
                access_level, default_access_level_for_user_type(user_type)
            )
            configured = configured_defaults.get(
                level,
                DEFAULT_ACCESS_PASSWORDS[default_access_level_for_user_type(user_type)],
            )
            outcomes[usuario_id] = (
                APPLIED_DEFAULT_KEPT
                if check_password(str(stored_hash), configured)
                else AMBIGUOUS
            )
    return outcomes


def _target_state(outcome: str) -> str:
    if outcome == KEPT_PERSONAL:
        return "personal"
    if outcome == APPLIED_DEFAULT_KEPT:
        return "default"
    if outcome in (REVOKED_TO_PENDING, SWITCH_OFF_TO_PENDING):
        return "pending"
    raise ValueError(f"no target state for {outcome!r}")


def _credential_rows(conn: sqlite3.Connection) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT usuario_id,estado,auth_version,atualizado_em,acesso_ativo"
            " FROM usuario_credenciais ORDER BY usuario_id"
        ).fetchall()
    ]


def _password_rows(conn: sqlite3.Connection) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute("SELECT id,senha FROM usuarios ORDER BY id").fetchall()
    ]


def _token_rows(conn: sqlite3.Connection) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute("SELECT * FROM senha_tokens ORDER BY id").fetchall()
    ]


def _other_settings(conn: sqlite3.Connection) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT chave,valor,atualizado_em FROM configuracoes_app"
            " WHERE chave<>? ORDER BY chave",
            (LEGACY_DEFAULT_PASSWORDS_SETTING,),
        ).fetchall()
    ]


def migrate_prod1_v10_to_v11(conn: sqlite3.Connection) -> dict[str, object]:
    from app.prod1_schema import (
        BASELINE_MARKER,
        CREDENTIAL_PENDING_MARKER,
        SCHEMA_EPOCH,
        Prod1SchemaError,
        _validate_prod1_v10_schema,
        validate_prod1_schema,
    )

    if conn.in_transaction:
        raise Prod1SchemaError("prod-1/v11 migration requires a clean connection")
    _validate_prod1_v10_schema(conn)

    # PBKDF2 runs here, before the write lock is taken. The snapshot below is
    # re-checked inside the transaction, so a concurrent credential write
    # between the two cannot slip past the classification.
    legacy_switch_on = legacy_default_passwords_enabled(conn)
    legacy_setting_present = conn.execute(
        "SELECT 1 FROM configuracoes_app WHERE chave=?",
        (LEGACY_DEFAULT_PASSWORDS_SETTING,),
    ).fetchone() is not None
    outcomes = classify_legacy_credentials(conn)
    ambiguous = [usuario_id for usuario_id, outcome in outcomes.items() if outcome == AMBIGUOUS]
    if ambiguous:
        raise LegacyCredentialClassificationError(ambiguous)

    credentials_before = _credential_rows(conn)
    passwords_before = _password_rows(conn)
    tokens_before = _token_rows(conn)
    settings_before = _other_settings(conn)

    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        if _credential_rows(conn) != credentials_before:
            raise Prod1SchemaError("prod-1/v11 credentials changed during classification")

        conn.execute(
            "CREATE TEMP TABLE _usuario_credenciais_v10 AS"
            " SELECT usuario_id,estado,auth_version,atualizado_em,acesso_ativo"
            " FROM main.usuario_credenciais"
        )
        conn.execute("DROP TABLE main.usuario_credenciais")
        conn.execute(USUARIO_CREDENCIAIS_V11_TABLE_SQL)
        conn.executemany(
            """
            INSERT INTO main.usuario_credenciais(
                usuario_id,estado,auth_version,atualizado_em,acesso_ativo)
            SELECT usuario_id,?,auth_version,atualizado_em,acesso_ativo
              FROM temp._usuario_credenciais_v10
             WHERE usuario_id=?
            """,
            [(_target_state(outcome), usuario_id) for usuario_id, outcome in outcomes.items()],
        )
        conn.execute("DROP TABLE temp._usuario_credenciais_v10")
        conn.execute(
            "DELETE FROM configuracoes_app WHERE chave=?",
            (LEGACY_DEFAULT_PASSWORDS_SETTING,),
        )
        conn.execute(
            "INSERT INTO schema_migrations(version,name,schema_epoch,details_json)"
            " VALUES(?,?,?,?)",
            (11, CREDENTIAL_PENDING_MARKER, SCHEMA_EPOCH, _V11_DETAILS_JSON),
        )
        conn.execute("PRAGMA user_version=11")

        expected = [
            (usuario_id, _target_state(outcomes[usuario_id]), *rest)
            for usuario_id, _estado, *rest in credentials_before
        ]
        if _credential_rows(conn) != expected:
            raise Prod1SchemaError("prod-1/v11 credential rows diverged from the classification")
        if _password_rows(conn) != passwords_before:
            raise Prod1SchemaError("prod-1/v11 migration changed usuarios.senha")
        if _token_rows(conn) != tokens_before:
            raise Prod1SchemaError("prod-1/v11 migration changed password tokens")
        if _other_settings(conn) != settings_before:
            raise Prod1SchemaError("prod-1/v11 migration changed unrelated settings")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise Prod1SchemaError("prod-1/v11 integrity check failed")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise Prod1SchemaError(f"prod-1/v11 foreign key violations: {violations!r}")
        validate_prod1_schema(conn)
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys_enabled else 'OFF'}")

    status = validate_prod1_schema(conn)
    counts: dict[str, int] = {}
    for outcome in outcomes.values():
        counts[outcome] = counts.get(outcome, 0) + 1
    return {
        **status,
        "baseline_marker": BASELINE_MARKER,
        "credential_backfill": "authentication_preserving",
        "legacy_default_passwords_enabled": legacy_switch_on,
        "legacy_setting_present": legacy_setting_present,
        "classification": dict(sorted(counts.items())),
    }


__all__ = [
    "AMBIGUOUS",
    "APPLIED_DEFAULT_KEPT",
    "KEPT_PERSONAL",
    "LEGACY_DEFAULT_PASSWORDS_SETTING",
    "LegacyCredentialClassificationError",
    "REVOKED_TO_PENDING",
    "SWITCH_OFF_TO_PENDING",
    "classify_legacy_credentials",
    "legacy_default_passwords_enabled",
    "migrate_prod1_v10_to_v11",
]
