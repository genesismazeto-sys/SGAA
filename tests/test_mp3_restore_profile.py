# coding: utf-8
"""MP-3 slice 4: the Supabase restore profile of ``tools/pg_backup.py``.

A NEW managed project is not empty under the plain-PostgreSQL definition: it
holds provider schemas, default extensions and API event triggers.  The
profile (explicit, never inferred) allows exactly those and still refuses a
used project (provider rows), a stray schema, an unlisted extension and
anything in ``public``.  The unit part pins the allow-lists and the CLI; the
real-PostgreSQL part builds a target shaped like a fresh project (provider
schemas, a default extension, empty provider tables) and runs a real restore.
"""

from __future__ import annotations

import io
import contextlib

import pytest

from tests.mp2_pg_support import PG_URL, Registry
from tools import pg_backup as tool

NEEDS_PG = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)


def test_the_plain_profile_is_the_unchanged_definition():
    assert tool.empty_target_checks("plain") == tool.EMPTY_TARGET_CHECKS


def test_the_supabase_profile_allows_exactly_the_listed_provider_objects():
    checks = tool.empty_target_checks("supabase")
    assert set(checks) == set(tool.EMPTY_TARGET_CHECKS)
    for schema in tool.SUPABASE_PROFILE_SCHEMAS:
        assert f"'{schema}'" in checks["schemas"]
    for extension in tool.SUPABASE_PROFILE_EXTENSIONS:
        assert f"'{extension}'" in checks["extensions"]
    for trigger in tool.SUPABASE_PROFILE_EVENT_TRIGGERS:
        assert f"'{trigger}'" in checks["event_triggers"]
    # Nothing in public is ever tolerated.
    for name in ("relations", "routines", "types", "collations", "operators"):
        assert checks[name] == tool.EMPTY_TARGET_CHECKS[name]
    assert "NOT IN" in checks["extensions"] and "NOT IN" in checks["event_triggers"]


def test_an_unknown_profile_is_refused_and_the_default_is_plain():
    with pytest.raises(tool.Refused) as caught:
        tool.empty_target_checks("neon")
    assert caught.value.code == "TARGET_PROFILE_UNKNOWN"
    parser = tool._parser()
    assert parser.parse_args(["restore", "--manifest", "m"]).target_profile == "plain"
    assert parser.parse_args(["restore", "--manifest", "m", "--target-profile", "supabase"]).target_profile == "supabase"
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert tool.main(["restore", "--manifest", "m", "--target-profile", "neon"]) == tool.EXIT_USAGE


def test_a_managed_projects_own_database_is_a_target_only_under_the_supabase_profile():
    """Supabase names its application database ``postgres``; a plain cluster's ``postgres`` stays
    protected, and the templates and the qualification database are refused under both profiles."""
    url = "postgresql://postgres.ref@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
    with pytest.raises(tool.Refused) as caught:
        tool._refuse_before_connecting(url)
    assert caught.value.code == "TARGET_PROTECTED"
    tool._refuse_before_connecting(url, "supabase")  # no refusal
    for database in ("template0", "template1", "sgaa_qual"):
        for profile in tool.TARGET_PROFILES:
            with pytest.raises(tool.Refused):
                tool._refuse_before_connecting(f"postgresql://u@h:5432/{database}", profile)
    assert tool.protected_databases("supabase") == tool.PROTECTED_DATABASES - {"postgres"}


# ---- real PostgreSQL ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registry():
    registry = Registry("rprofile")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


def _fresh_project_shape(url):
    """Provider schemas, a default extension and empty provider tables: what a new project holds."""
    conn = tool.connect(url)
    try:
        for schema in ("auth", "storage", "extensions", "vault", "graphql", "realtime"):
            conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute("CREATE EXTENSION pgcrypto WITH SCHEMA extensions")
        conn.execute("CREATE TABLE auth.users (id integer)")
        conn.execute("CREATE TABLE storage.buckets (id text)")
        conn.execute("CREATE TABLE storage.objects (id integer)")
    finally:
        conn.close()


def _occupancy(url, profile):
    conn = tool.connect(url)
    try:
        return tool.target_occupancy(conn, profile)
    finally:
        conn.close()


@NEEDS_PG
def test_a_fresh_project_shape_is_empty_only_under_the_supabase_profile(registry):
    name, url = registry.create()
    _fresh_project_shape(url)
    plain = _occupancy(url, "plain")
    assert plain["schemas"] > 0 and plain["extensions"] == 1
    assert not any(_occupancy(url, "supabase").values())


@NEEDS_PG
@pytest.mark.parametrize(
    "setup,counted",
    [
        ("INSERT INTO storage.objects VALUES (1)", "provider_rows"),
        ("INSERT INTO auth.users VALUES (1)", "provider_rows"),
        ("CREATE SCHEMA appdata", "schemas"),
        ("CREATE EXTENSION hstore WITH SCHEMA extensions", "extensions"),
        ("CREATE TABLE public.leftover (id integer)", "relations"),
    ],
)
def test_a_used_project_or_a_stray_object_is_still_not_empty(registry, setup, counted):
    name, url = registry.create()
    _fresh_project_shape(url)
    conn = tool.connect(url)
    try:
        conn.execute(setup)
    finally:
        conn.close()
    occupancy = _occupancy(url, "supabase")
    assert occupancy[counted] >= 1 and sum(1 for v in occupancy.values() if v) >= 1


@NEEDS_PG
def test_a_real_restore_into_a_fresh_project_shape_needs_the_profile_and_verifies(registry, tmp_path, monkeypatch):
    source, source_url = registry.create(template=registry.template)
    monkeypatch.setenv(tool.SOURCE_URL_ENV, source_url)
    monkeypatch.delenv(tool.TARGET_URL_ENV, raising=False)
    result = tool.backup(str(tmp_path), "profile-proof")
    manifest = next(tmp_path.glob("*.manifest.json"))

    target, target_url = registry.create()
    _fresh_project_shape(target_url)
    with pytest.raises(tool.BackupToolError) as caught:
        tool.restore(str(manifest), target_url=target_url)  # plain: the provider objects make it "not empty"
    assert caught.value.code == "TARGET_NOT_EMPTY"

    tool.restore(str(manifest), target_url=target_url, profile="supabase")
    loaded = tool.verify_artifact(str(manifest))
    tool.verify_database(loaded.manifest, target_url)  # raises on any difference
    assert result.manifest["schema"]["version"] == loaded.manifest["schema"]["version"]


class _Rows:
    def __init__(self, names):
        self._names = names

    def execute(self, _sql):
        return self

    def fetchall(self):
        return [(name,) for name in self._names]


@pytest.mark.parametrize("schemas,ok", [
    (["auth", "storage", "extensions"], True),
    (["auth", "storage", "extensions", "vault", "realtime"], True),
    (["auth", "storage"], False),
    (["extensions"], False),
    ([], False),
])
def test_the_postgres_database_is_a_target_only_with_the_providers_own_schemas(schemas, ok):
    if ok:
        tool.require_managed_project(_Rows(schemas))
        return
    with pytest.raises(tool.Refused) as caught:
        tool.require_managed_project(_Rows(schemas))
    assert caught.value.code == "TARGET_PROTECTED"
