"""Real-PostgreSQL harness for the MP-1 suites -- TEST ONLY.

One template database per module (prefix ``sgaa_mp1_test_<run>_``) is
provisioned through ``app.pg_schema`` and seeded with
``tests.storage_mp1_support.SEED_SQL``; every node gets its own
``CREATE DATABASE ... TEMPLATE`` clone, dropped at teardown together with the
template, followed by a leftover census.  Connections are the runtime adapter
(``app.db._PostgresConnectionAdapter``, READ COMMITTED), so the owners run
exactly the SQL production runs.
"""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlsplit, urlunsplit

PG_URL = os.environ.get("SGAA_PG_TEST_URL", "").strip()
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "sgaa_qual"})
CONNECT_TIMEOUT_SECONDS = 10


def _psycopg():
    import psycopg

    return psycopg


def database_url(database: str) -> str:
    parts = urlsplit(PG_URL)
    return urlunsplit((parts.scheme, parts.netloc, "/" + database,
                       f"connect_timeout={CONNECT_TIMEOUT_SECONDS}", ""))


def raw_connection(url: str, *, autocommit: bool = False):
    return _psycopg().connect(url, prepare_threshold=None, autocommit=autocommit,
                              connect_timeout=CONNECT_TIMEOUT_SECONDS)


def adapter(url: str):
    from app.db import _PostgresConnectionAdapter

    raw = raw_connection(url)
    raw.isolation_level = _psycopg().IsolationLevel.READ_COMMITTED
    return _PostgresConnectionAdapter(raw)


class Registry:
    """Sole creator and destroyer of one module's disposable databases."""

    def __init__(self, label: str) -> None:
        self.prefix = f"sgaa_mp1_test_{secrets.token_hex(3)}_{label}_"
        self.admin = raw_connection(PG_URL, autocommit=True)
        self.created: list[str] = []
        self.template: str | None = None

    def create(self, template: str | None = None) -> tuple[str, str]:
        name = f"{self.prefix}{secrets.token_hex(3)}"
        assert name.startswith(self.prefix) and name not in PROTECTED_DATABASES
        suffix = f' TEMPLATE "{template}"' if template else ""
        self.admin.execute(f'CREATE DATABASE "{name}"{suffix}')
        self.created.append(name)
        return name, database_url(name)

    def drop(self, name: str) -> None:
        assert name.startswith(self.prefix) and name not in PROTECTED_DATABASES
        psycopg = _psycopg()
        try:
            self.admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        except psycopg.errors.ObjectInUse:
            self.admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        self.created.remove(name)

    def provision_template(self) -> None:
        from app import pg_schema
        from tests.storage_mp1_support import SEEDED_TABLES, seed_business

        name, url = self.create()
        raw = raw_connection(url)
        try:
            pg_schema.provision_pg_schema(raw)
            raw.commit()
        finally:
            raw.close()
        conn = adapter(url)
        try:
            seed_business(conn)
            for table in SEEDED_TABLES:
                conn.execute(f"ALTER TABLE {table} ALTER COLUMN id RESTART WITH 100")
            conn.commit()
        finally:
            conn.close()
        self.template = name

    def close(self) -> int:
        for name in reversed(list(self.created)):
            try:
                self.drop(name)
            except Exception:  # pragma: no cover - teardown best effort; the census below reports leftovers
                pass
        self.admin.close()
        census = raw_connection(PG_URL, autocommit=True)
        try:
            return int(census.execute(
                "SELECT count(*) FROM pg_database WHERE datname LIKE %s", (self.prefix + "%",)
            ).fetchone()[0])
        finally:
            census.close()


__all__ = ["PG_URL", "Registry", "adapter", "database_url", "raw_connection"]
