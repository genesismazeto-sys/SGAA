# coding: utf-8
"""MP-3 slice 1 on real PostgreSQL (opt-in, ``SGAA_PG_TEST_URL``): the API-exposure probe.

Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).

A managed platform's default privileges hand its HTTP-API roles every new
table, sequence and function.  The probe must see that, and the documented
revocation must clear it -- including the PostgreSQL built-in default that a
new function is executable by PUBLIC -- without disturbing the schema contract
or the owner's runtime.  A plain cluster has no such roles; the pseudo-role
``public`` stands in for them because every role inherits it, so a grant to
PUBLIC is exactly what reaches ``anon``.
"""

from __future__ import annotations

import io
import json
import tempfile

import pytest

from tests.mp2_pg_support import PG_URL, Registry, adapter

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

pytest.importorskip("psycopg")

PUBLIC = ("public",)


@pytest.fixture(scope="module")
def registry():
    registry = Registry("exposure")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def database(registry):
    name, url = registry.create(template=registry.template)
    yield url
    registry.drop(name)


def _apply_recipe(conn):
    """The statements of ``docs/HOSTED_RUNTIME.md`` section 11, for the stand-in role."""
    conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC")
    conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC")
    conn.execute("ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")
    for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
        conn.execute(f"REVOKE ALL ON ALL {kind} IN SCHEMA public FROM PUBLIC")
    conn.commit()


def _exposure(conn):
    from app import pg_schema

    return pg_schema.api_role_exposure(conn, roles=PUBLIC)


def test_a_plain_cluster_without_api_roles_is_clean_and_probes_nothing(database):
    from app import pg_schema

    conn = adapter(database)
    try:
        report = pg_schema.api_role_exposure(conn)
        assert report["roles_probed"] == [] and report["clean"] is True
    finally:
        conn.close()


def test_a_fresh_schema_shows_postgresql_s_own_function_default_and_the_recipe_clears_it(database):
    conn = adapter(database)
    try:
        fresh = _exposure(conn)
        counts = fresh["exposed"]["public"]
        assert counts["tables"] == 0 and counts["sequences"] == 0
        assert counts["functions"] > 0  # a function is executable by PUBLIC unless revoked
        assert fresh["function_default_public_execute"] is True and fresh["clean"] is False
        _apply_recipe(conn)
        cleared = _exposure(conn)
        assert cleared["exposed"]["public"] == {"tables": 0, "sequences": 0, "functions": 0, "default_privileges": 0}
        assert cleared["function_default_public_execute"] is False and cleared["clean"] is True
    finally:
        conn.close()


@pytest.mark.parametrize(
    "grant,klass",
    [
        ("GRANT SELECT ON TABLE usuarios TO PUBLIC", "tables"),
        ("GRANT USAGE ON SEQUENCE usuarios_id_seq TO PUBLIC", "sequences"),
        ("GRANT EXECUTE ON FUNCTION sgaa_human_text_key(text) TO PUBLIC", "functions"),
    ],
)
def test_each_class_alone_makes_a_cleared_schema_unclean(database, grant, klass):
    conn = adapter(database)
    try:
        _apply_recipe(conn)
        assert _exposure(conn)["clean"] is True
        conn.execute(grant)
        conn.commit()
        report = _exposure(conn)
        assert report["exposed"]["public"][klass] == 1 and report["clean"] is False
        _apply_recipe(conn)
        assert _exposure(conn)["clean"] is True
    finally:
        conn.close()


@pytest.mark.parametrize(
    "grant",
    [
        "GRANT INSERT ON TABLE usuarios TO PUBLIC",
        "GRANT UPDATE ON TABLE usuarios TO PUBLIC",
        "GRANT DELETE ON TABLE usuarios TO PUBLIC",
        "GRANT TRUNCATE ON TABLE usuarios TO PUBLIC",
        "GRANT REFERENCES ON TABLE usuarios TO PUBLIC",
        "GRANT TRIGGER ON TABLE usuarios TO PUBLIC",
    ],
)
def test_every_table_privilege_the_api_could_use_is_seen(database, grant):
    conn = adapter(database)
    try:
        _apply_recipe(conn)
        conn.execute(grant)
        conn.commit()
        assert _exposure(conn)["exposed"]["public"]["tables"] == 1
    finally:
        conn.close()


def test_the_maintain_privilege_is_seen_on_postgresql_17(database):
    conn = adapter(database)
    try:
        if int(conn.execute("SHOW server_version_num").fetchone()[0]) < 170000:
            pytest.skip("MAINTAIN exists from PostgreSQL 17")
        _apply_recipe(conn)
        conn.execute("GRANT MAINTAIN ON TABLE usuarios TO PUBLIC")
        conn.commit()
        assert _exposure(conn)["exposed"]["public"]["tables"] == 1
    finally:
        conn.close()


@pytest.mark.parametrize(
    "default_grant",
    [
        "ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO PUBLIC",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO PUBLIC",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO PUBLIC",
    ],
)
def test_a_global_or_per_class_default_privilege_is_seen(database, default_grant):
    conn = adapter(database)
    try:
        _apply_recipe(conn)
        conn.execute(default_grant)
        conn.commit()
        report = _exposure(conn)
        assert report["exposed"]["public"]["default_privileges"] >= 1 and report["clean"] is False
    finally:
        conn.close()


def test_a_function_created_after_the_recipe_is_not_reachable(database):
    conn = adapter(database)
    try:
        _apply_recipe(conn)
        conn.execute("CREATE FUNCTION mp3_after_recipe() RETURNS integer LANGUAGE sql AS 'SELECT 1'")
        conn.commit()
        report = _exposure(conn)
        assert report["exposed"]["public"]["functions"] == 0 and report["clean"] is True
    finally:
        conn.close()


def test_the_recipe_in_the_document_is_the_recipe_the_tests_apply(database):
    """Doc drift is a defect: the statements of section 11, with the API roles replaced, run clean."""
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "docs" / "HOSTED_RUNTIME.md").read_text(encoding="utf-8")
    block = re.search(r"```\n(ALTER DEFAULT PRIVILEGES.*?)```", text, re.S).group(1)
    statements = [line.rstrip(";") for line in block.strip().splitlines() if line.strip()]
    assert len(statements) == 7
    conn = adapter(database)
    try:
        for statement in statements:
            # The platform's API roles do not exist on a plain cluster: PUBLIC stands in.
            statement = re.sub(r"(PUBLIC, )?anon, authenticated, service_role", "PUBLIC", statement)
            conn.execute(statement)
        conn.commit()
        report = _exposure(conn)
        assert report["clean"] is True and report["exposed"]["public"]["functions"] == 0
    finally:
        conn.close()


def test_a_column_level_grant_is_seen(database):
    conn = adapter(database)
    try:
        _apply_recipe(conn)
        conn.execute("GRANT SELECT (id) ON TABLE usuarios TO PUBLIC")
        conn.commit()
        report = _exposure(conn)
        assert report["exposed"]["public"]["tables"] == 1 and report["clean"] is False
    finally:
        conn.close()


def test_a_default_privilege_that_would_expose_future_objects_is_seen_and_a_new_object_proves_it(database):
    conn = adapter(database)
    try:
        _apply_recipe(conn)
        conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO PUBLIC")
        conn.commit()
        report = _exposure(conn)
        assert report["exposed"]["public"]["default_privileges"] == 1 and report["clean"] is False
        # The entry is not theoretical: the next table is reachable at once.
        conn.execute("CREATE TABLE mp3_future_probe (id integer)")
        conn.commit()
        assert _exposure(conn)["exposed"]["public"]["tables"] == 1
    finally:
        conn.close()


def test_the_recipe_leaves_the_contract_and_the_owner_runtime_intact(database):
    from app import pg_schema

    conn = adapter(database)
    try:
        _apply_recipe(conn)
        assert pg_schema.validate_pg_schema(conn.raw_connection)["table_count"] > 0
        # The owner (the runtime role) still reads and runs the schema's own functions.
        conn.execute("SELECT count(*) FROM usuarios").fetchone()
        conn.execute("SELECT sgaa_human_text_key('Ação')").fetchone()
        conn.rollback()
    finally:
        conn.close()


def _hosted_environment(monkeypatch, url, tmp_path):
    import app.db as app_db

    for name in ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SGAA_RUNTIME", "hosted")
    monkeypatch.setenv("TRUST_PROXY_XFF", "1")
    monkeypatch.setenv("APP_SECRET_KEY", "x" + "7" * 47)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(app_db, "DATABASE_URL", url)


def test_readiness_is_not_ready_for_one_table_grant_and_ready_once_revoked(database, monkeypatch, tmp_path):
    from app import hosting_cli, pg_schema

    _hosted_environment(monkeypatch, database, tmp_path)
    monkeypatch.setattr(pg_schema, "API_ROLES", PUBLIC)

    def run():
        out = io.StringIO()
        code = hosting_cli.main(["check", "--database"], out=out)
        return code, json.loads(out.getvalue())

    conn = adapter(database)
    try:
        _apply_recipe(conn)
        code, report = run()
        assert code == 0 and report["database"]["api_exposure"]["clean"] is True
        assert report["database"]["connection_kind"] == "direct"

        conn.execute("GRANT SELECT ON TABLE usuarios TO PUBLIC")  # one table, nothing else
        conn.commit()
        code, report = run()
        assert code == 1
        assert report["database"]["current"] is True  # the schema is fine; only the exposure fails
        assert report["database"]["api_exposure"]["exposed"]["public"]["tables"] == 1

        _apply_recipe(conn)
        code, report = run()
        assert code == 0 and report["database"]["api_exposure"]["clean"] is True
    finally:
        conn.close()
