# coding: utf-8
"""MP-3 slice 1: the provider API-role exposure probe and the connection kind (no database).

The probe is read-only SQL over the catalog; here a scripted connection answers
it, so the report shape, the role validation, the verdict (each class on its
own) and the value-free connection classification are pinned without a server.
The real-PostgreSQL behaviour is in ``test_mp3_api_exposure_real_pg``.
"""

from __future__ import annotations

import re

import pytest

from app import hosting, pg_schema


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _ScriptedConnection:
    """Answers the probe's statements from a table of (role, class) -> count."""

    def __init__(self, roles_in_cluster, counts=None, *, version=170011, public_execute_default=False):
        self.roles_in_cluster = roles_in_cluster
        self.counts = counts or {}
        self.version = version
        self.public_execute_default = public_execute_default
        self.statements = []

    def _role_count(self, sql, klass):
        found = re.search(r"'(anon|authenticated|service_role|public)'|rolname = '(\w+)'", sql)
        role = (found.group(1) or found.group(2)) if found else "public"  # `grantee = 0` is PUBLIC
        return self.counts.get((role, klass), 0)

    def execute(self, sql, params=None):
        self.statements.append(sql)
        assert params is None, "the probe must not need bound parameters"
        text = sql.strip()
        if text == "SELECT current_schema()":
            return _Cursor([("public",)])
        if text.startswith("SELECT rolname FROM pg_catalog.pg_roles"):
            return _Cursor([(name,) for name in self.roles_in_cluster])
        if "server_version_num" in text:
            return _Cursor([(self.version,)])
        if "has_table_privilege" in text:
            return _Cursor([(self._role_count(text, "tables"),)])
        if "has_sequence_privilege" in text:
            return _Cursor([(self._role_count(text, "sequences"),)])
        if "has_function_privilege" in text:
            return _Cursor([(self._role_count(text, "functions"),)])
        if "d.defaclobjtype IN ('r','S','f')" in text:
            return _Cursor([(self._role_count(text, "default_privileges"),)])
        if "d.defaclobjtype = 'f'" in text:
            return _Cursor([(0 if self.public_execute_default else 1,)])
        raise AssertionError(f"unexpected statement: {text[:90]}")


def test_a_plain_postgresql_cluster_has_no_api_roles_and_is_clean():
    conn = _ScriptedConnection(roles_in_cluster=["postgres"])
    report = pg_schema.api_role_exposure(conn)
    assert report == {"roles_probed": [], "exposed": {}, "function_default_public_execute": False, "clean": True}


def test_platform_defaults_that_grant_the_api_roles_everything_are_reported_unclean():
    conn = _ScriptedConnection(
        roles_in_cluster=["postgres", "anon", "authenticated", "service_role"],
        counts={("anon", "tables"): 40, ("anon", "sequences"): 23, ("authenticated", "tables"): 40,
                ("service_role", "functions"): 2, ("anon", "default_privileges"): 3},
    )
    report = pg_schema.api_role_exposure(conn)
    assert report["roles_probed"] == ["anon", "authenticated", "service_role"]
    assert report["exposed"]["anon"] == {"tables": 40, "sequences": 23, "functions": 0, "default_privileges": 3}
    assert report["exposed"]["service_role"]["functions"] == 2
    assert report["clean"] is False


def test_revoked_roles_are_clean_even_though_they_exist():
    conn = _ScriptedConnection(["anon", "authenticated"])
    report = pg_schema.api_role_exposure(conn)
    assert report["roles_probed"] == ["anon", "authenticated"] and report["clean"] is True


@pytest.mark.parametrize("klass", ["tables", "sequences", "functions", "default_privileges"])
def test_each_exposure_class_alone_makes_the_schema_unclean(klass):
    conn = _ScriptedConnection(["anon", "authenticated"], counts={("authenticated", klass): 1})
    report = pg_schema.api_role_exposure(conn)
    assert report["exposed"]["authenticated"][klass] == 1 and report["clean"] is False


def test_the_builtin_public_execute_default_alone_makes_a_platform_schema_unclean():
    conn = _ScriptedConnection(["anon"], public_execute_default=True)
    report = pg_schema.api_role_exposure(conn)
    assert report["function_default_public_execute"] is True and report["clean"] is False
    # Without API roles the default is irrelevant and is not reported.
    plain = pg_schema.api_role_exposure(_ScriptedConnection(["postgres"], public_execute_default=True))
    assert plain["clean"] is True


def test_the_maintain_privilege_is_probed_only_where_the_server_has_it():
    new = _ScriptedConnection(["anon"], version=170011)
    pg_schema.api_role_exposure(new)
    assert any("MAINTAIN" in sql for sql in new.statements)
    old = _ScriptedConnection(["anon"], version=150019)
    pg_schema.api_role_exposure(old)
    assert not any("MAINTAIN" in sql for sql in old.statements)


def test_column_level_privileges_are_part_of_the_table_check():
    conn = _ScriptedConnection(["anon"])
    pg_schema.api_role_exposure(conn)
    assert any("has_any_column_privilege" in sql for sql in conn.statements)


@pytest.mark.parametrize("bad", ["Anon", "anon'; DROP TABLE x;--", "a b", "", "x" * 64])
def test_role_names_are_validated_before_any_statement_is_built(bad):
    conn = _ScriptedConnection(["anon"])
    with pytest.raises(pg_schema.PostgresSchemaError):
        pg_schema.api_role_exposure(conn, roles=(bad,))
    assert conn.statements == []


def test_the_default_role_set_is_the_platform_api_roles():
    assert pg_schema.API_ROLES == ("anon", "authenticated", "service_role")


@pytest.mark.parametrize(
    "url,kind",
    [
        ("postgresql://postgres@db.example.supabase.co:5432/postgres", "direct"),
        ("postgresql://postgres.abc@aws-0-us-east-1.pooler.supabase.com:6543/postgres", "pooler_transaction"),
        ("postgresql://postgres.abc@aws-0-us-east-1.pooler.supabase.com:5432/postgres", "pooler_session"),
        ("postgresql://postgres.abc@aws-0-us-east-1.pooler.supabase.com/postgres", "pooler_session"),
        ("postgresql://u@localhost:6543/db", "direct"),
        ("postgresql://u@127.0.0.1:54317/db?connect_timeout=5", "direct"),
        # What libpq honours that a plain URL split does not.
        ("postgresql://u@aws-0-x.pooler.supabase.com.:6543/db", "pooler_transaction"),
        ("postgresql://u@aws-0-x.pooler.supabase.com:5432/db?port=6543", "pooler_transaction"),
        ("postgresql://u@/db?host=aws-0-x.pooler.supabase.com&port=6543", "pooler_transaction"),
        ("postgresql://u@aws-0-x%2Epooler.supabase.com:6543/db", "pooler_transaction"),
        ("postgresql://u@AWS-0-X.POOLER.SUPABASE.COM:6543/db", "pooler_transaction"),
        # libpq reads a leading zero or a plus sign as the same port number.
        ("postgresql://u@aws-0-x.pooler.supabase.com:06543/db", "pooler_transaction"),
        ("postgresql://u@aws-0-x.pooler.supabase.com:+6543/db", "pooler_transaction"),
        ("postgresql://u@aws-0-x.pooler.supabase.com/db?port=06543", "pooler_transaction"),
        ("postgresql://u@aws-0-x.pooler.supabase.com:05432/db", "pooler_session"),
        ("postgresql://u:p%40ss@aws-0-x.pooler.supabase.com:6543/db", "pooler_transaction"),
        ("postgresql://u@[::1]:6543/db", "direct"),
        # Several hosts, no host at all (taken from the environment), a service file, a pinned
        # address, a port that is not a number: not the address the URL shows.
        ("postgresql://u@a.example:5432,aws-0-x.pooler.supabase.com:6543/db", "unknown"),
        ("postgresql://u@/db", "unknown"),
        ("postgresql://u@aws-0-x.pooler.supabase.com/db?service=prod", "unknown"),
        ("postgresql://u@aws-0-x.pooler.supabase.com:6543/db?hostaddr=10.0.0.1", "unknown"),
        ("postgresql://u@aws-0-x.pooler.supabase.com:6543x/db", "unknown"),
        ("postgresql://u@aws-0-x.pooler.supabase.com:0/db", "unknown"),
    ],
)
def test_connection_kind_follows_libpq_and_names_the_pooler_mode_never_the_host(url, kind):
    assert hosting.connection_kind(url) == kind


def test_a_port_that_would_come_from_the_environment_is_not_guessed(monkeypatch):
    url = "postgresql://u@aws-0-x.pooler.supabase.com/db"
    monkeypatch.delenv("PGPORT", raising=False)
    assert hosting.connection_kind(url) == "pooler_session"
    monkeypatch.setenv("PGPORT", "6543")
    assert hosting.connection_kind(url) == "unknown"
    assert hosting.connection_kind(url + "?port=5432") == "pooler_session"  # an explicit port wins


def test_the_public_execute_statement_is_also_limited_to_the_connected_role():
    conn = _ScriptedConnection(["anon"])
    pg_schema.api_role_exposure(conn)
    statements = [sql for sql in conn.statements if "d.defaclobjtype = 'f'" in sql]
    assert statements and all(
        "d.defaclrole = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user)" in sql
        for sql in statements
    )


def test_connection_kind_of_an_unparseable_value_is_unknown_not_an_error():
    assert hosting.connection_kind("postgresql://[::1") == "unknown"


def test_only_the_connected_roles_default_privileges_count():
    """A platform keeps default-privilege entries for its own roles; they cannot reach
    objects the schema owner creates, so counting them would make a platform schema
    permanently "not ready".  Pinned on the statement because a plain cluster has no
    second role to create the entry with."""
    conn = _ScriptedConnection(["anon"])
    pg_schema.api_role_exposure(conn)
    statements = [sql for sql in conn.statements if "pg_default_acl" in sql and "defaclobjtype IN" in sql]
    assert statements and all(
        "d.defaclrole = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user)" in sql
        for sql in statements
    )
