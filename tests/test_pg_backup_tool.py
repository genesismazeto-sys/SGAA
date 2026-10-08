# coding: utf-8
"""Layer-2 PostgreSQL backup tool (``tools/pg_backup.py``) -- no database.

Secret handling (password / secret-valued URLs refused unread, no
URL/password/force options, usage errors never echoed, native stderr
classified never forwarded, child argv/env), ambiguous restore-target
routing refused before connecting, the archive TOC
allowlist, client/server version gate, manifest seal and artifact-file
atomicity (staging, non-replacing promotion, hard-kill leftovers).  The
real-PostgreSQL round trip lives in ``test_pg_backup_restore_real_pg.py``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import pg_schema
from tools import pg_backup as tool

UNUSED_URL = "postgresql://nobody@127.0.0.1:1/never_connected"
SENTINEL = "s3ntinel-Pa55"
SEQUENCES = [f"{table}_id_seq" for table in tool.IDENTITY_TABLES]


def _codes(func, *args, **kwargs):
    with pytest.raises(tool.BackupToolError) as caught:
        func(*args, **kwargs)
    return caught.value


# ---------------------------------------------------------------------------
# connection strings / CLI surface
# ---------------------------------------------------------------------------


def test_password_urls_are_refused_without_echo(monkeypatch):
    cases = {
        f"postgresql://sgaa:{SENTINEL}@db.example.test:5432/sgaa": "SOURCE_URL_CONTAINS_PASSWORD",
        f"postgresql://sgaa@db.example.test/sgaa?sslmode=require&password={SENTINEL}": "SOURCE_URL_CONTAINS_PASSWORD",
        f"postgresql://sgaa@db.example.test/sgaa?PASSWORD={SENTINEL}": "SOURCE_URL_CONTAINS_PASSWORD",
        "postgresql://sgaa@db.example.test": "SOURCE_URL_INVALID",
        "sqlite:///database.db": "SOURCE_NOT_POSTGRESQL",
        "": "SOURCE_REQUIRED",
    }
    for url, code in cases.items():
        error = _codes(tool.require_url, url, tool.SOURCE_URL_ENV)
        assert error.code == code
        assert SENTINEL not in str(error) and "db.example.test" not in str(error)
    error = _codes(tool.require_url, f"postgres://u:{SENTINEL}@h/d", tool.TARGET_URL_ENV)
    assert error.code == "TARGET_URL_CONTAINS_PASSWORD"
    monkeypatch.delenv(tool.SOURCE_URL_ENV, raising=False)
    assert _codes(tool.require_url, None, tool.SOURCE_URL_ENV).code == "SOURCE_REQUIRED"
    assert tool.require_url("postgresql://sgaa@h:5432/sgaa?sslmode=require", tool.SOURCE_URL_ENV)


def test_cli_password_url_is_refused_before_anything(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(tool.SOURCE_URL_ENV, f"postgresql://sgaa:{SENTINEL}@127.0.0.1:1/sgaa")
    assert tool.main(["backup", "--output-dir", str(tmp_path), "--label", "x"]) == tool.EXIT_FAILED
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "SOURCE_URL_CONTAINS_PASSWORD" in output
    assert SENTINEL not in output and "127.0.0.1" not in output
    assert list(tmp_path.iterdir()) == []


def test_cli_has_no_url_password_force_or_clean_options(tmp_path, capsys):
    out = str(tmp_path)
    for argv in (
        ["backup", "--output-dir", out, "--label", "a", "--password", "x"],
        ["backup", "--output-dir", out, "--label", "a", "--database-url", UNUSED_URL],
        ["backup", "--output-dir", out, "--label", "a", "--dbname", UNUSED_URL],
        ["backup", "--output-dir", out, "--label", "a", "--force"],
        ["restore", "--manifest", "m.manifest.json", "--force"],
        ["restore", "--manifest", "m.manifest.json", "--clean"],
        ["restore", "--manifest", "m.manifest.json", "--target-url", UNUSED_URL],
        ["backup", "--out", out, "--label", "a"],  # no abbreviations
        ["backup", "--label", "a"],
        [],
        ["dump"],
    ):
        assert tool.main(argv) == tool.EXIT_USAGE, argv
    capsys.readouterr()
    assert list(tmp_path.iterdir()) == []


def test_usage_errors_never_echo_the_offending_argument(tmp_path, capsys):
    secret_url = f"postgresql://sgaa:{SENTINEL}@db.example.test/sgaa"
    out = str(tmp_path)
    for argv in (
        ["backup", "--output-dir", out, "--label", "a", "--db-url", secret_url],
        ["backup", "--output-dir", out, "--label", "a", f"--db-url={secret_url}"],
        ["backup", "--output-dir", out, "--label", "a", secret_url],
        ["backup", "--out", secret_url, "--label", "a"],  # abbreviations stay rejected
        ["restore", "--manifest", "m.manifest.json", "--target", secret_url],
        [secret_url],
    ):
        assert tool.main(argv) == tool.EXIT_USAGE
        captured = capsys.readouterr()
        output = captured.out + captured.err
        generic = "usage error" in output and "never echoed" in output
        echoed = SENTINEL in output or "db.example.test" in output
        assert generic and not echoed
    assert list(tmp_path.iterdir()) == []
    # --help stays useful; a valid command line parses exactly as before.
    assert tool.main(["--help"]) == tool.EXIT_OK
    top_help = capsys.readouterr().out
    assert all(word in top_help for word in ("backup", "restore", "verify", "DATABASE_URL"))
    assert tool.main(["backup", "--help"]) == tool.EXIT_OK
    assert "--output-dir" in capsys.readouterr().out
    options = tool._parser().parse_args(["backup", "--output-dir", out, "--label", "a"])
    assert (options.command, options.output_dir, options.label) == ("backup", out, "a")


def _stub_restore_surface(monkeypatch, tmp_path):
    """restore() up to its first connection: artifact checks stubbed, every
    connection and native-tool start recorded, nothing reaches a server."""
    seen = {"connect": [], "argv": []}

    def fake_connect(url):
        seen["connect"].append(url)
        raise tool.Refused("STUB_CONNECTED", "test stop at the first connection")

    def fake_run(argv, **kwargs):
        seen["argv"].append([str(part) for part in argv])
        return subprocess.CompletedProcess(argv, 0, b"pg_dump (PostgreSQL) 15.19", b"")

    loaded = tool.LoadedArtifact(tmp_path / "x.manifest.json", tmp_path / "x.dump", {}, "", [], {})
    monkeypatch.setattr(tool, "verify_artifact", lambda *args, **kwargs: loaded)
    monkeypatch.setattr(tool, "connect", fake_connect)
    monkeypatch.setattr(tool.subprocess, "run", fake_run)
    monkeypatch.delenv(tool.SOURCE_URL_ENV, raising=False)
    return seen


@pytest.mark.parametrize(
    "key", ["sslpassword", "SSLPassword", "oauth_client_secret", "scram_client_key", "scram_server_key",
            "pass%77ord"],
)
def test_secret_valued_query_keys_are_refused_without_echo_or_argv(key, tmp_path, monkeypatch, capsys):
    url = f"postgresql://sgaa@db.example.test:5432/sgaa?sslmode=require&{key}={SENTINEL}"
    for env_name, role in ((tool.SOURCE_URL_ENV, "SOURCE"), (tool.TARGET_URL_ENV, "TARGET")):
        error = _codes(tool.require_url, url, env_name)
        assert error.code == f"{role}_URL_CONTAINS_PASSWORD"
        assert SENTINEL not in str(error)
    seen = _stub_restore_surface(monkeypatch, tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv(tool.SOURCE_URL_ENV, url)
    assert tool.main(["backup", "--output-dir", str(out), "--label", "x"]) == tool.EXIT_FAILED
    monkeypatch.delenv(tool.SOURCE_URL_ENV)
    monkeypatch.setenv(tool.TARGET_URL_ENV, url)
    assert tool.main(["restore", "--manifest", "x.manifest.json"]) == tool.EXIT_FAILED
    captured = capsys.readouterr()
    output = captured.out + captured.err
    refused_twice = output.count("_URL_CONTAINS_PASSWORD") == 2
    echoed = SENTINEL in output or "db.example.test" in output
    assert refused_twice and not echoed
    # Refused before any connection or native tool: the secret reached no argv.
    assert seen["connect"] == [] and seen["argv"] == []
    assert list(out.iterdir()) == []


AMBIGUOUS_TARGETS = {
    "multi-host": f"postgresql://sgaa@{SENTINEL}-a,{SENTINEL}-b/sgaa_restore",
    "multi-host-ports": f"postgresql://sgaa@{SENTINEL}-a:5432,{SENTINEL}-b:5433/sgaa_restore",
    "encoded-comma-host": f"postgresql://sgaa@{SENTINEL}-a%2C{SENTINEL}-b/sgaa_restore",
    "trailing-empty-host": f"postgresql://sgaa@{SENTINEL}:5432,/sgaa_restore",
    "host-query": f"postgresql://sgaa@db.example.test/sgaa_restore?host={SENTINEL}",
    "hostaddr-query": f"postgresql://sgaa@db.example.test/{SENTINEL}?hostaddr=10.9.8.7",
    "dbname-query": f"postgresql://sgaa@db.example.test/sgaa_restore?dbname={SENTINEL}",
    "port-query": f"postgresql://sgaa@db.example.test:5432/{SENTINEL}?port=6543",
    "service-query": f"postgresql://sgaa@db.example.test/sgaa_restore?service={SENTINEL}",
    # libpq does not accept servicefile in a URI at all: refused as unparsable.
    "servicefile-query": f"postgresql://sgaa@db.example.test/sgaa_restore?servicefile=/{SENTINEL}",
}


@pytest.mark.parametrize("case", sorted(AMBIGUOUS_TARGETS))
def test_ambiguous_restore_target_routing_is_refused_before_connecting(case, tmp_path, monkeypatch, capsys):
    url = AMBIGUOUS_TARGETS[case]
    expected = {"TARGET_URL_INVALID"} if case == "servicefile-query" else {"TARGET_URL_AMBIGUOUS"}
    seen = _stub_restore_surface(monkeypatch, tmp_path)
    error = _codes(tool.restore, "x.manifest.json", target_url=url)
    assert error.code in expected and SENTINEL not in str(error)
    monkeypatch.setenv(tool.TARGET_URL_ENV, url)
    assert tool.main(["restore", "--manifest", "x.manifest.json"]) == tool.EXIT_FAILED
    captured = capsys.readouterr()
    output = captured.out + captured.err
    refused = any(code in output for code in expected)
    echoed = SENTINEL in output or "db.example.test" in output
    assert refused and not echoed
    assert seen["connect"] == [] and seen["argv"] == []


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://sgaa@db.example.test:6543/sgaa_restore?sslmode=require&connect_timeout=10",
        "postgres://sgaa@127.0.0.1/sgaa_restore",
        "postgresql://sgaa@[::1]:5432/sgaa_restore?application_name=drill",
    ],
)
def test_ordinary_single_host_restore_target_passes_routing(url, tmp_path, monkeypatch):
    assert tool.require_url(url, tool.TARGET_URL_ENV) == url
    tool.require_single_target_route(url)
    seen = _stub_restore_surface(monkeypatch, tmp_path)
    assert _codes(tool.restore, "x.manifest.json", target_url=url).code == "STUB_CONNECTED"
    assert seen["connect"] == [url]


PINNED_URL = "postgresql://sgaa@db.example.test:6543/sgaa_restore?sslmode=verify-full"
STALE_HOSTADDR = "198.51.100.99"


class _CheckedConnection:
    """A preflight connection that passed every target check."""

    def __init__(self, hostaddr):
        self._hostaddr = hostaddr
        self.closed = False

    @property
    def info(self):
        if isinstance(self._hostaddr, Exception):
            raise self._hostaddr
        return type("Info", (), {"hostaddr": self._hostaddr})()

    def close(self):
        self.closed = True


def _stub_pinned_restore(monkeypatch, tmp_path, hostaddr):
    """restore() with real control flow; the checked connection, pg_restore
    and the post-restore verification are stubs, every child run is recorded."""
    seen = {"runs": [], "connections": []}
    restore_tool = tool.NativeTool("pg_restore", str(tmp_path / "pg_restore"), "15.19", 15)
    loaded = tool.LoadedArtifact(tmp_path / "x.manifest.json", tmp_path / "x.dump", {}, "", [],
                                 {"pg_restore": restore_tool})

    def fake_connect(url):
        connection = _CheckedConnection(hostaddr)
        seen["connections"].append(connection)
        return connection

    def fake_run(argv, **kwargs):
        seen["runs"].append({"argv": [str(part) for part in argv], "env": dict(kwargs["env"])})
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(tool, "verify_artifact", lambda *args, **kwargs: loaded)
    monkeypatch.setattr(tool, "connect", fake_connect)
    monkeypatch.setattr(tool, "_check_target", lambda conn, manifest, tools: tool.TargetIdentity(
        "postgresql", "db.example.test", "6543", "sgaa_restore", "sgaa", "15.19", "7001"))
    monkeypatch.setattr(tool.subprocess, "run", fake_run)
    monkeypatch.setattr(tool, "verify_database", lambda manifest, url, announce=None: "verified")
    monkeypatch.delenv(tool.SOURCE_URL_ENV, raising=False)
    monkeypatch.delenv("PGSERVICE", raising=False)
    return seen


@pytest.mark.parametrize(
    "checked, pinned",
    [("203.0.113.10", "203.0.113.10"), ("2001:db8::10", "2001:db8::10"), ("::1", "::1"),
     ("2001:DB8:0:0::10", "2001:db8::10")],
)
def test_pg_restore_is_pinned_to_the_checked_preflight_address(checked, pinned, tmp_path, monkeypatch):
    monkeypatch.setenv("PGHOSTADDR", STALE_HOSTADDR)  # stale / hostile: must not survive
    monkeypatch.setenv("PGSERVICEFILE", str(tmp_path / "pg_service.conf"))
    monkeypatch.setenv("PGSSLROOTCERT", str(tmp_path / "ca.pem"))  # TLS configuration is kept
    monkeypatch.setenv("PGPASSWORD", SENTINEL)  # credential path unchanged
    seen = _stub_pinned_restore(monkeypatch, tmp_path, checked)
    assert tool.restore("x.manifest.json", target_url=PINNED_URL) == "verified"

    [run] = seen["runs"]
    environment, argv = run["env"], run["argv"]
    assert environment["PGHOSTADDR"] == pinned
    assert STALE_HOSTADDR not in environment.values()
    assert "PGSERVICE" not in environment and "PGSERVICEFILE" not in environment
    assert environment["PGSSLROOTCERT"] == str(tmp_path / "ca.pem")
    assert environment["PGPASSWORD"] == SENTINEL
    # The URI keeps the logical host name (TLS verify-full, pgpass); the
    # address travels only in the environment, never in argv.
    assert argv[argv.index("--dbname") + 1] == PINNED_URL
    assert all(pinned not in part and SENTINEL not in part for part in argv)
    assert "--single-transaction" in argv
    assert all(connection.closed for connection in seen["connections"])
    # Only the restore is pinned: other native runs (pg_dump) inherit as before.
    unpinned = tool._child_environment()
    assert unpinned["PGHOSTADDR"] == STALE_HOSTADDR and "PGSERVICEFILE" in unpinned


@pytest.mark.parametrize(
    "checked",
    ["", None, "db.example.test", "203.0.113.10,198.51.100.99", "999.1.1.1", f"{SENTINEL}.example.test",
     tool.BackupToolError("NOT_SUPPORTED")],
)
def test_missing_or_non_numeric_checked_address_fails_closed_before_pg_restore(checked, tmp_path, monkeypatch,
                                                                                capsys):
    seen = _stub_pinned_restore(monkeypatch, tmp_path, checked)
    error = _codes(tool.restore, "x.manifest.json", target_url=PINNED_URL)
    assert error.code == "TARGET_HOSTADDR_UNAVAILABLE" and error.exit_code == tool.EXIT_FAILED
    monkeypatch.setenv(tool.TARGET_URL_ENV, PINNED_URL)
    assert tool.main(["restore", "--manifest", "x.manifest.json"]) == tool.EXIT_FAILED
    captured = capsys.readouterr()
    output = captured.out + captured.err
    refused = "TARGET_HOSTADDR_UNAVAILABLE" in output
    echoed = SENTINEL in output or "203.0.113.10" in output or "?sslmode" in output
    assert refused and not echoed
    assert seen["runs"] == []  # pg_restore never started, no second DNS lookup
    assert all(connection.closed for connection in seen["connections"])


def test_inherited_pgservice_cannot_route_the_restore(tmp_path, monkeypatch, capsys):
    seen = _stub_pinned_restore(monkeypatch, tmp_path, "203.0.113.10")
    monkeypatch.setenv("PGSERVICE", f"{SENTINEL}-service")
    error = _codes(tool.restore, "x.manifest.json", target_url=PINNED_URL)
    assert error.code == "TARGET_ENV_ROUTING" and SENTINEL not in str(error)
    monkeypatch.setenv(tool.TARGET_URL_ENV, PINNED_URL)
    assert tool.main(["restore", "--manifest", "x.manifest.json"]) == tool.EXIT_FAILED
    captured = capsys.readouterr()
    output = captured.out + captured.err
    refused = "TARGET_ENV_ROUTING" in output
    echoed = SENTINEL in output or "db.example.test" in output
    assert refused and not echoed
    # Refused before the preflight connection could pick up service defaults.
    assert seen["connections"] == [] and seen["runs"] == []


def test_label_and_output_directory_guards(tmp_path, monkeypatch):
    monkeypatch.setenv(tool.SOURCE_URL_ENV, UNUSED_URL)
    assert _codes(tool.backup, tmp_path, "Bad Label").code == "LABEL_INVALID"
    assert _codes(tool.backup, tmp_path / "absent", "ok").code == "OUTPUT_DIR_MISSING"
    assert _codes(tool.backup, tool.REPOSITORY_ROOT / "tests", "ok").code == "OUTPUT_INSIDE_REPOSITORY"
    leftover = tmp_path / ("sgaa-pg-20260101T000000Z-x.dump" + tool.STAGING_SUFFIX)
    leftover.write_bytes(b"partial")
    error = _codes(tool.backup, tmp_path, "ok")
    assert error.code == "STAGING_LEFTOVER" and leftover.name in str(error)
    assert leftover.read_bytes() == b"partial"  # recognised, never deleted by the tool


def test_identity_comparison_uses_cluster_then_endpoint():
    a = tool.TargetIdentity("postgresql", "127.0.0.1", "5432", "sgaa", "u", "15.19", "7001")
    assert tool.same_database(a, tool.TargetIdentity("postgresql", "other", "1", "sgaa", "x", "15.19", "7001"))
    assert not tool.same_database(a, tool.TargetIdentity("postgresql", "127.0.0.1", "5432", "sgaa", "u", "15.19", "7002"))
    assert not tool.same_database(a, tool.TargetIdentity("postgresql", "127.0.0.1", "5432", "b", "u", "15.19", "7001"))
    no_id = tool.TargetIdentity("postgresql", "localhost", "5432", "sgaa", "u", "15.19")
    assert tool.same_database(no_id, tool.TargetIdentity("postgresql", "127.0.0.1", "5432", "sgaa", "v", "15.19"))
    assert "password" not in a.label() and set(a.as_dict()) == set(tool.TargetIdentity.__dataclass_fields__)


# ---------------------------------------------------------------------------
# native tools
# ---------------------------------------------------------------------------


def test_versions_and_client_older_than_server_gate():
    assert tool.parse_tool_version("pg_dump (PostgreSQL) 15.19") == ("15.19", 15)
    assert tool.parse_tool_version("pg_restore (PostgreSQL) 17.2 (Ubuntu 17.2-1.pgdg24.04+1)") == ("17.2", 17)
    assert _codes(tool.parse_tool_version, "garbage").code == "NATIVE_TOOL_VERSION_UNKNOWN"

    def tools(dump, restore):
        return {"pg_dump": tool.NativeTool("pg_dump", "x", f"{dump}.0", dump),
                "pg_restore": tool.NativeTool("pg_restore", "x", f"{restore}.0", restore)}

    tool.require_client_not_older(tools(15, 15), 15)
    tool.require_client_not_older(tools(17, 17), 15)
    assert _codes(tool.require_client_not_older, tools(14, 15), 15).code == "CLIENT_OLDER_THAN_SERVER"
    assert _codes(tool.require_client_not_older, tools(17, 16), 17).code == "CLIENT_OLDER_THAN_SERVER"


def test_missing_binaries_are_refused_before_connecting(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(tool.BIN_DIR_ENV, str(tmp_path))
    assert _codes(tool.discover_native_tools).code == "NATIVE_TOOL_MISSING"
    assert _codes(tool.run_native, [str(tmp_path / "no-such-binary")]).code == "NATIVE_TOOL_MISSING"
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv(tool.SOURCE_URL_ENV, UNUSED_URL)
    assert tool.main(["backup", "--output-dir", str(out), "--label", "x"]) == tool.EXIT_FAILED
    assert "NATIVE_TOOL_MISSING" in capsys.readouterr().err
    assert list(out.iterdir()) == []


def test_native_failure_is_classified_and_never_echoed(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"], seen["env"] = argv, kwargs["env"]
        stderr = (f"pg_dump: error: connection to server at \"db.example.test\" failed: "
                  f"postgresql://u:{SENTINEL}@db.example.test/x password={SENTINEL}").encode()
        return subprocess.CompletedProcess(argv, 1, b"", stderr)

    monkeypatch.setenv("PGPASSWORD", SENTINEL)
    monkeypatch.setenv(tool.SOURCE_URL_ENV, UNUSED_URL)
    monkeypatch.setenv(tool.TARGET_URL_ENV, UNUSED_URL)
    monkeypatch.setattr(tool.subprocess, "run", fake_run)
    error = _codes(tool.run_native, ["pg_dump", "--dbname", "postgresql://u@h/d"])
    assert isinstance(error, tool.NativeToolError)
    assert error.code == "NATIVE_TOOL_FAILED"
    assert error.detail == "pg_dump exit=1 class=CONNECTION_FAILED"
    assert SENTINEL not in str(error) and "db.example.test" not in str(error)
    # The password only ever reaches the child through its inherited environment.
    assert all(SENTINEL not in part for part in seen["argv"])
    assert seen["env"]["PGPASSWORD"] == SENTINEL
    assert tool.SOURCE_URL_ENV not in seen["env"] and tool.TARGET_URL_ENV not in seen["env"]
    assert tool.classify_stderr(b'ERROR:  schema "public" already exists') == "OBJECT_EXISTS"
    assert tool.classify_stderr(b"pg_dump: error: aborting because of server version mismatch") == \
        "SERVER_VERSION_MISMATCH"
    assert tool.classify_stderr(b"something new") == "UNCLASSIFIED"


# ---------------------------------------------------------------------------
# archive TOC
# ---------------------------------------------------------------------------


def _listing(*, extra=(), drop=(), public_entries=True):
    lines = [";", "; Archive created at 2026-01-01 00:00:00", ";     Format: CUSTOM", ";"]
    if public_entries:
        lines += ["4; 2615 2200 SCHEMA - public pg_database_owner",
                  "3944; 0 0 COMMENT - SCHEMA public pg_database_owner"]
    number = 100
    for desc, tags in tool.expected_toc(SEQUENCES).items():
        for tag in sorted(tags):
            if (desc, tag) in drop:
                continue
            number += 1
            shown = f"{tag}(text)" if desc == "FUNCTION" else tag
            lines.append(f"{number}; 1259 {number} {desc} public {shown} sgaa_qual")
    return "\n".join(lines + list(extra)) + "\n"


def test_contract_toc_is_accepted_with_census():
    census = tool.validate_toc(tool.parse_toc(_listing()), SEQUENCES)
    specs = pg_schema.PG_TABLE_SPECS
    assert census["classes"] == {
        "CONSTRAINT": sum(1 + len(specs[t]["uniques"]) for t in pg_schema.PG_SCHEMA_TABLES),
        "FK CONSTRAINT": 40,
        "FUNCTION": 15,
        "INDEX": len(pg_schema.PG_EXPLICIT_INDEXES),
        "SEQUENCE": 22,
        "SEQUENCE SET": 22,
        "TABLE": 37,
        # v14: storage_upload_intents / storage_worker_status are schema-only.
        "TABLE DATA": 35,
        "TRIGGER": 17,
    }
    assert census["public_schema_entries"] == 2
    assert len(census["sha256"]) == 64
    # Owner names and oids do not change the census digest.
    other = _listing().replace(" sgaa_qual", " supabase_admin").replace("1259", "9999")
    assert tool.validate_toc(tool.parse_toc(other), SEQUENCES) == census
    assert tool.validate_toc(tool.parse_toc(_listing(public_entries=False)), SEQUENCES)["public_schema_entries"] == 0


def test_schema_only_tables_carry_no_table_data_in_the_contract():
    """v14: intents / worker health are archived schema-only, proven from the TOC."""
    assert "--exclude-table-data=public.storage_upload_intents" in tool.PG_DUMP_OPTIONS
    assert "--exclude-table-data=public.storage_worker_status" in tool.PG_DUMP_OPTIONS
    assert tool.SCHEMA_ONLY_TABLE_POLICIES == {
        "storage_upload_intents": "EPHEMERAL_OMITTED", "storage_worker_status": "TARGET_SIDE_RECREATED",
    }
    for table in tool.SCHEMA_ONLY_TABLE_POLICIES:
        leaked = _listing(extra=[f"999; 0 0 TABLE DATA public {table} sgaa_qual"])
        assert _codes(tool.validate_toc, tool.parse_toc(leaked), SEQUENCES).code == "TOC_UNEXPECTED_OBJECT"
        assert table in tool.expected_toc(SEQUENCES)["TABLE"]
    # Negative control: canonical object metadata MUST be archived with data.
    missing = _listing(drop={("TABLE DATA", "storage_objects")})
    assert _codes(tool.validate_toc, tool.parse_toc(missing), SEQUENCES).code == "TOC_INCOMPLETE"


@pytest.mark.parametrize(
    "extra, code",
    [
        ("9001; 1259 1 TABLE auth users supabase_auth_admin", "TOC_UNEXPECTED_SCHEMA"),
        ("9001; 2615 1 SCHEMA - storage supabase_admin", "TOC_UNEXPECTED_SCHEMA"),
        ("9001; 1255 1 FUNCTION extensions uuid_generate_v4() postgres", "TOC_UNEXPECTED_SCHEMA"),
        ("9001; 3079 1 EXTENSION - pgcrypto ", "TOC_UNEXPECTED_OBJECT_CLASS"),
        ("9001; 0 0 ACL public TABLE usuarios sgaa_qual", "TOC_UNEXPECTED_OBJECT_CLASS"),
        ("9001; 826 1 DEFAULT ACL public DEFAULT PRIVILEGES FOR TABLES postgres", "TOC_UNEXPECTED_OBJECT_CLASS"),
        ("9001; 1259 1 VIEW public stray_view sgaa_qual", "TOC_UNEXPECTED_OBJECT_CLASS"),
        ("9001; 3256 1 POLICY public usuarios p_all sgaa_qual", "TOC_UNEXPECTED_OBJECT_CLASS"),
        ("9001; 1255 1 FUNCTION public stray_fn() sgaa_qual", "TOC_UNEXPECTED_OBJECT"),
        ("9001; 1259 1 TABLE public stray_table sgaa_qual", "TOC_UNEXPECTED_OBJECT"),
        ("9001; 0 0 COMMENT public TABLE usuarios sgaa_qual", "TOC_UNEXPECTED_OBJECT"),
        ("101; 1259 101 TABLE public usuarios sgaa_qual\n101; 1259 101 TABLE public usuarios sgaa_qual",
         "TOC_DUPLICATE_ENTRY"),
        ("this is not a toc line", "TOC_UNREADABLE"),
    ],
)
def test_toc_outside_the_contract_is_refused(extra, code):
    def check():
        tool.validate_toc(tool.parse_toc(_listing(extra=extra.split("\n"))), SEQUENCES)

    assert _codes(check).code == code


def test_incomplete_toc_is_refused():
    trigger = next(iter(tool.expected_toc(SEQUENCES)["TRIGGER"]))
    listing = _listing(drop={("TRIGGER", trigger)})
    error = _codes(tool.validate_toc, tool.parse_toc(listing), SEQUENCES)
    assert error.code == "TOC_INCOMPLETE" and "TRIGGER" in str(error)
    listing = _listing(drop={("TABLE DATA", "usuarios")})
    assert _codes(tool.validate_toc, tool.parse_toc(listing), SEQUENCES).code == "TOC_INCOMPLETE"


def test_restore_list_comments_out_only_the_public_schema_entries():
    listing = _listing()
    filtered = tool.restore_list(listing).splitlines()
    original = listing.splitlines()
    assert len(filtered) == len(original)
    changed = [(a, b) for a, b in zip(original, filtered) if a != b]
    assert [b for _, b in changed] == [
        ";4; 2615 2200 SCHEMA - public pg_database_owner",
        ";3944; 0 0 COMMENT - SCHEMA public pg_database_owner",
    ]


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------


def _manifest_files(directory: Path, base="sgaa-pg-20260101T000000Z-unit"):
    dump = directory / (base + tool.DUMP_SUFFIX)
    dump.write_bytes(b"PGDMP synthetic")
    size, sha = tool.file_sha256(dump)
    manifest = tool.seal_manifest({
        "format": tool.MANIFEST_FORMAT,
        "format_version": tool.MANIFEST_FORMAT_VERSION,
        "result": "ok",
        "artifact": {"file": dump.name, "sidecar": base + tool.SIDECAR_SUFFIX, "size": size, "sha256": sha},
        "tables": {
            t: tool._EMPTY_TABLE.get(t, {"rows": 0, "sha256": "0" * 64}) for t in pg_schema.PG_SCHEMA_TABLES
        },
        "table_data_policy": {
            t: {"policy": p, "restored_rows": 0, "source": {}} for t, p in tool.SCHEMA_ONLY_TABLE_POLICIES.items()
        },
        "storage": {},
        "identities": {t: {"sequence": f"{t}_id_seq"} for t in tool.IDENTITY_TABLES},
    })
    (directory / (base + tool.SIDECAR_SUFFIX)).write_bytes(tool.sidecar_bytes(sha, dump.name))
    path = directory / (base + tool.MANIFEST_SUFFIX)
    path.write_bytes(tool.manifest_bytes(manifest))
    return path, manifest, dump


def test_manifest_seal_detects_any_edit(tmp_path):
    path, manifest, _dump = _manifest_files(tmp_path)
    assert tool.load_manifest(path) == manifest
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["tables"]["usuarios"]["rows"] = 1
    path.write_text(json.dumps(edited), encoding="utf-8")
    assert _codes(tool.load_manifest, path).code == "MANIFEST_DIGEST_MISMATCH"
    path.write_text("{not json", encoding="utf-8")
    assert _codes(tool.load_manifest, path).code == "MANIFEST_INVALID"
    path.write_text(json.dumps({"format": "other"}), encoding="utf-8")
    assert _codes(tool.load_manifest, path).code == "MANIFEST_INVALID"
    path.unlink()
    assert _codes(tool.load_manifest, path).code == "MANIFEST_MISSING"
    assert _codes(tool.load_manifest, tmp_path / "x.dump").code == "MANIFEST_MISSING"


def test_manifest_must_record_the_v14_table_data_policy(tmp_path):
    path, manifest, _dump = _manifest_files(tmp_path)
    for mutate in (
        lambda m: m["table_data_policy"]["storage_upload_intents"].update(policy="MIGRATE_EXACT"),
        lambda m: m["table_data_policy"].pop("storage_worker_status"),
        lambda m: m["tables"]["storage_upload_intents"].update(rows=3),
        lambda m: m.pop("storage"),
    ):
        edited = json.loads(json.dumps(manifest))
        edited.pop("manifest_sha256", None)
        mutate(edited)
        path.write_bytes(tool.manifest_bytes(tool.seal_manifest(edited)))
        assert _codes(tool.load_manifest, path).code == "MANIFEST_INVALID"
    path.write_bytes(tool.manifest_bytes(manifest))
    assert tool.load_manifest(path) == manifest


def test_artifact_and_sidecar_tamper_is_refused_before_any_tool_runs(tmp_path, monkeypatch):
    monkeypatch.setenv(tool.BIN_DIR_ENV, str(tmp_path / "no-binaries-here"))
    path, manifest, dump = _manifest_files(tmp_path)
    sidecar = tmp_path / manifest["artifact"]["sidecar"]
    sidecar.write_bytes(tool.sidecar_bytes("f" * 64, dump.name))
    assert _codes(tool.verify_artifact, path).code == "SIDECAR_MISMATCH"
    sidecar.write_bytes(tool.sidecar_bytes(manifest["artifact"]["sha256"], dump.name))
    dump.write_bytes(b"PGDMP synthetiC")
    assert _codes(tool.verify_artifact, path).code == "ARTIFACT_SHA_MISMATCH"
    dump.unlink()
    assert _codes(tool.verify_artifact, path).code == "ARTIFACT_MISSING"
    sidecar.unlink()
    assert _codes(tool.verify_artifact, path).code == "ARTIFACT_MISSING"


# ---------------------------------------------------------------------------
# artifact atomicity
# ---------------------------------------------------------------------------


def test_promotion_never_replaces_and_undo_removes_only_this_run(tmp_path):
    paths = tool.ArtifactPaths(tmp_path, "sgaa-pg-20260101T000000Z-a")
    staged = tool._StagedSet(paths)
    for final in paths.finals():
        staged.write(final, b"new " + final.name.encode())
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        tool.ArtifactPaths.staging(f).name for f in paths.finals()
    )
    staged.promote()
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(f.name for f in paths.finals())

    # A different file already holds the manifest name: dump and sidecar are
    # promoted first, then the conflict is refused and only this run's files go.
    other = tool.ArtifactPaths(tmp_path, "sgaa-pg-20260101T000000Z-b")
    other.manifest.write_bytes(b"someone else's manifest")
    staged = tool._StagedSet(other)
    for final in other.finals():
        staged.write(final, b"run b")
    with pytest.raises(tool.Failed) as caught:
        staged.promote()
    assert caught.value.code == "ARTIFACT_EXISTS"
    staged.undo()
    assert other.manifest.read_bytes() == b"someone else's manifest"
    assert not other.dump.exists() and not other.sidecar.exists()
    assert not any(p.name.endswith(tool.STAGING_SUFFIX) for p in tmp_path.iterdir())
    for final in paths.finals():  # the first complete set is untouched
        assert final.read_bytes() == b"new " + final.name.encode()


_HARD_KILL_SCRIPT = """
import os, sys
from pathlib import Path
from tools import pg_backup as tool

paths = tool.ArtifactPaths(Path(sys.argv[1]), "sgaa-pg-20260101T000000Z-kill")
staged = tool._StagedSet(paths)
staged.write(paths.dump, b"PGDMP partial bytes")
staged.claim(paths.sidecar)
os._exit(9)  # no except/finally/atexit runs: a hard kill before promotion
"""


def test_hard_kill_leaves_only_recognised_staging_files(tmp_path):
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    killed = subprocess.run(
        [sys.executable, "-c", _HARD_KILL_SCRIPT, str(tmp_path)],
        cwd=str(tool.REPOSITORY_ROOT), env=environment, capture_output=True, timeout=120,
    )
    assert killed.returncode == 9, killed.stderr.decode("utf-8", "replace")[-2000:]
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names and all(name.endswith(tool.STAGING_SUFFIX) for name in names)
    error = _codes(tool.check_output_directory, tmp_path)
    assert error.code == "STAGING_LEFTOVER"
    assert sorted(p.name for p in tmp_path.iterdir()) == names  # never deleted by the tool

    # A kill between promotions leaves a set without its manifest: refused.
    paths = tool.ArtifactPaths(tmp_path, "sgaa-pg-20260101T000000Z-half")
    paths.dump.write_bytes(b"PGDMP")
    assert _codes(tool.verify_artifact, paths.manifest).code == "MANIFEST_MISSING"


def test_the_web_application_never_imports_the_backup_tool():
    root = tool.REPOSITORY_ROOT
    sources = [root / "main.py", *(root / "app").rglob("*.py")]
    importers = [
        path.relative_to(root).as_posix()
        for path in sources
        if "pg_backup" in path.read_text(encoding="utf-8")
    ]
    assert importers == []
