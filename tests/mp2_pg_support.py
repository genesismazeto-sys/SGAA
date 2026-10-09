"""Real-PostgreSQL harness for the MP-2 suites -- TEST ONLY.

Same discipline as ``tests.storage_mp1_pg_support`` (run-owned databases under
a random prefix, plain DROP first, a leftover census) with the MP-2 prefix
``sgaa_mp2_test_<run>_`` and a schema-only template: MP-2 suites seed their own
rows.
"""

from __future__ import annotations

import secrets

from tests.storage_mp1_pg_support import PG_URL, adapter, database_url, raw_connection
from tests.storage_mp1_pg_support import Registry as _Mp1Registry

ADMIN_EMAIL = "mp2.admin@example.test"
ADMIN_PASSWORD = "mp2-senha-admin-sintetica"


class Registry(_Mp1Registry):
    def __init__(self, label: str) -> None:
        super().__init__(label)
        self.prefix = f"sgaa_mp2_test_{secrets.token_hex(3)}_{label}_"

    def provision_template(self, seed=None) -> None:
        from app import pg_schema

        name, url = self.create()
        raw = raw_connection(url)
        try:
            pg_schema.provision_pg_schema(raw)
            raw.commit()
        finally:
            raw.close()
        if seed is not None:
            conn = adapter(url)
            try:
                seed(conn)
                conn.commit()
            finally:
                conn.close()
        self.template = name


def seed_admin(conn, *, email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD) -> int:
    """One administrator through the production account owner (real hash and credential)."""
    from app.security.passwords import hash_password
    from app.user_accounts import create_usuario_with_access_level

    cursor = create_usuario_with_access_level(
        conn, "MP2 Admin", email, hash_password(password), "admin", "admin_total", credential_state="personal"
    )
    return int(cursor.usuario_id)


__all__ = ["ADMIN_EMAIL", "ADMIN_PASSWORD", "PG_URL", "Registry", "adapter", "database_url", "raw_connection", "seed_admin"]
