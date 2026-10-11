# coding: utf-8
"""MP-3 SPEC A16: every backup the cutover ledger counts comes from the PROD database and store.

Unit part: the canonical source identity of ``app.hosting`` (which Supabase project a pooler login, a
direct address or a storage address belongs to; the digest every cutover comparison uses), the
object set's sealed ``source`` and its validation.

Real-PostgreSQL part (opt-in, ``SGAA_PG_TEST_URL``): two disposable databases stand for PROD and for
a foreign database.  Real ``ops_backup`` generations (``pg_backup`` and the object-backup command run
as children, recording what they actually connected to) are offered to the real ledger, which reads
the live database itself:

* a generation of PROD is recorded with PROD's identity;
* a Layer-2 set of the other database is refused, and so is a PROD Layer-2 set paired with an object
  set read from the other database, or from another project's store.

The local server is not a Supabase project, so this module maps its address to the fixtures' PROD
project (in-process, in the ledger only; the children record the raw facts).  The project binding
itself -- a consistent wrong project -- is proven against Supabase DEV in ``test_mp3_live_db.py``.
"""

from __future__ import annotations

import json

import pytest

from app import hosting
from app.storage import object_backup
from tests.mp3_ledger_support import ALL_GATES, GOOD, OTHER_REF, PROD_REF, PROJECT, SOURCE, local_server_is_project
from tools import hosted_smoke

# ---- which project ------------------------------------------------------------------------------------


@pytest.mark.parametrize("host,login,expected", [
    ("aws-0-us-east-1.pooler.supabase.com", "postgres." + PROD_REF, PROD_REF),       # the session pooler's tenant
    ("AWS-0-us-east-1.pooler.supabase.com.", "postgres." + PROD_REF, PROD_REF),
    ("aws-0-us-east-1.pooler.supabase.com", "postgres", None),                      # no tenant: no project
    ("aws-0-us-east-1.pooler.supabase.com", "postgres." + PROD_REF[:-1], None),     # not a reference
    ("aws-0-us-east-1.pooler.supabase.com", "postgres." + PROD_REF.upper(), None),
    ("aws-0-us-east-1.pooler.supabase.com", "other." + PROD_REF, None),
    ("db." + PROD_REF + ".supabase.co", "postgres", PROD_REF),                       # the direct address
    (PROD_REF + ".supabase.co", None, PROD_REF),                                     # the storage API
    ("db." + PROD_REF + ".supabase.co.evil.test", "postgres", None),
    ("127.0.0.1", "postgres." + PROD_REF, None),                                      # a workstation or scratch
    ("", None, None),
])
def test_the_project_is_read_from_the_authenticated_tenant_or_the_projects_own_address(host, login, expected):
    assert hosting.supabase_project_ref(host, login) == expected


class _Cursor:
    def __init__(self, answers):
        self.answers = list(answers)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        return self

    def fetchone(self):
        return self.answers.pop(0)


class _Connection:
    """psycopg-shaped: the server says role ``postgres``; the pooler authenticated the tenant."""

    def __init__(self, readable=True):
        self.readable = readable
        self.info = type("Info", (), {"user": "postgres." + PROD_REF, "host": "aws-0-us-east-1.pooler.supabase.com",
                                      "port": 5432})()

    def cursor(self, row_factory=None):
        answers = [("postgres", "postgres", self.readable)]
        if self.readable:
            answers.append(("7400000000000000001",))
        return _Cursor(answers)


def test_the_live_source_takes_the_project_from_the_authenticated_login_not_the_server_role():
    source = hosting.database_source(_Connection())
    assert source == SOURCE
    assert hosting.source_project_sha256(source) == PROJECT
    unproven = hosting.database_source(_Connection(readable=False))
    assert unproven["system_identifier"] is None and hosting.source_identity_sha256(unproven) is None


def test_the_project_digest_is_the_one_the_ledger_and_the_smoke_compute():
    assert hosting.project_sha256(PROD_REF) == PROJECT == hosted_smoke.project_digest(PROD_REF)


def test_the_canonical_identity_names_database_role_cluster_and_project():
    base = hosting.source_identity_sha256(SOURCE)
    assert base is not None and hosting.source_identity_sha256(dict(SOURCE)) == base
    for change in ({"database": "other"}, {"user": "other"}, {"system_identifier": "7400000000000000002"},
                   {"login_user": "postgres." + OTHER_REF}, {"host": "127.0.0.1"}):
        assert hosting.source_identity_sha256(dict(SOURCE, **change)) != base, change
    # The port and the address kind's host name do not split one database in two.
    assert hosting.source_identity_sha256(dict(SOURCE, port="6543")) == base
    assert hosting.source_identity_sha256(dict(SOURCE, system_identifier=None)) is None  # unproven
    assert hosting.source_identity_sha256(None) is None and hosting.source_identity_sha256("x") is None
    assert hosting.source_project_sha256(SOURCE) == PROJECT
    assert hosting.source_project_sha256(dict(SOURCE, host="127.0.0.1")) is None


def test_a_layer2_manifest_source_and_a_live_source_share_the_basis():
    """``pg_backup`` records TargetIdentity.as_dict(): the same keys the live reading has, plus its own."""
    from tools import pg_backup

    recorded = pg_backup.TargetIdentity("postgresql", SOURCE["host"], SOURCE["port"], SOURCE["database"],
                                        SOURCE["user"], "17.6", SOURCE["system_identifier"],
                                        SOURCE["login_user"]).as_dict()
    assert hosting.source_identity_sha256(recorded) == hosting.source_identity_sha256(SOURCE)
    older = {k: v for k, v in recorded.items() if k != "login_user"}  # a set written before A16
    assert hosting.source_identity_sha256(older) != hosting.source_identity_sha256(SOURCE)


# ---- the object set's sealed source ------------------------------------------------------------------------------


def _manifest(source):
    manifest = {"format": object_backup.FORMAT, "kind": object_backup.KIND, "label": "x",
                "created_at": "2026-10-11 00:00:00", "counts": {"objects": 0, "contents": 0, "bytes": 0,
                                                                "active": 0, "retired": 0},
                "objects": [], "objects_digest": object_backup.objects_digest([])}
    if source is not ...:
        manifest["source"] = source
    manifest["seal"] = object_backup._seal(manifest)
    return manifest


@pytest.mark.parametrize("source,ok", [
    (..., True),                                                   # a set written before A16
    ({"database": SOURCE, "store_host": PROD_REF + ".supabase.co"}, True),
    ({"database": None, "store_host": None}, True),                # SQLite and a store with no address
    ({"database": dict(SOURCE, system_identifier=None), "store_host": "h"}, True),
    ({"database": SOURCE}, False),
    ({"database": SOURCE, "store_host": "h", "extra": 1}, False),
    ({"database": {k: v for k, v in SOURCE.items() if k != "login_user"}, "store_host": "h"}, False),
    ({"database": dict(SOURCE, port=5432), "store_host": "h"}, False),
    ({"database": SOURCE, "store_host": "h" * 300}, False),
    ("a source", False),
])
def test_the_object_set_source_is_validated_with_the_manifest(source, ok):
    if ok:
        object_backup._validate_manifest(_manifest(source))
    else:
        with pytest.raises(object_backup.SetInvalid):
            object_backup._validate_manifest(_manifest(source))


def test_the_store_names_its_projects_address_and_never_its_key():
    from app.storage.supabase_store import SupabaseObjectStore, SupabaseStorageConfig

    store = SupabaseObjectStore(SupabaseStorageConfig(url=f"https://{PROD_REF}.supabase.co", bucket="b",
                                                      secret_key="sb_secret_" + "k" * 30))
    assert store.origin_host == PROD_REF + ".supabase.co"
    assert hosting.supabase_project_ref(store.origin_host) == PROD_REF


def test_a_sqlite_source_names_no_database():
    import sqlite3

    class _Adapter:
        raw_connection = sqlite3.connect(":memory:")

    assert object_backup.backup_source(_Adapter(), object()) == {"database": None, "store_host": None}


# ---- real PostgreSQL ------------------------------------------------------------------------------------------

from tests.mp2_pg_support import PG_URL  # noqa: E402

NEEDS_PG = pytest.mark.skipif(not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT")


@pytest.fixture(scope="module")
def registry():
    if not PG_URL:
        pytest.skip("SGAA_PG_TEST_URL is not configured")
    from tests.mp2_pg_support import Registry

    registry = Registry("bksrc")
    try:
        registry.provision_template()
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def two_databases(registry):
    prod_name, prod_url = registry.create(template=registry.template)
    other_name, other_url = registry.create(template=registry.template)
    try:
        yield prod_url, other_url
    finally:
        registry.drop(prod_name)
        registry.drop(other_name)


def _live_source(url):
    from tools import pg_backup

    conn = pg_backup.connect(url)
    try:
        return hosting.database_source(conn)
    finally:
        conn.close()


@NEEDS_PG
def test_a_live_database_proves_its_cluster_and_two_databases_never_share_an_identity(two_databases):
    prod_url, other_url = two_databases
    prod, other = _live_source(prod_url), _live_source(other_url)
    assert prod["system_identifier"] and prod["login_user"] and prod["database"] != other["database"]
    assert hosting.source_identity_sha256(prod) == hosting.source_identity_sha256(_live_source(prod_url))
    assert hosting.source_identity_sha256(prod) != hosting.source_identity_sha256(other)


@NEEDS_PG
def test_the_layer2_tool_records_the_same_identity_the_live_database_has(two_databases, tmp_path, monkeypatch):
    from tools import pg_backup

    prod_url, _other = two_databases
    monkeypatch.setenv(pg_backup.SOURCE_URL_ENV, prod_url)
    (tmp_path / "set").mkdir()
    pg_backup.backup(str(tmp_path / "set"), "source-check")
    recorded = json.loads(next((tmp_path / "set").glob("*.manifest.json")).read_text())["source"]
    assert recorded["login_user"] and recorded["system_identifier"]
    assert hosting.source_identity_sha256(recorded) == hosting.source_identity_sha256(_live_source(prod_url))


@NEEDS_PG
def test_an_object_set_seals_the_database_it_read_and_the_store_it_read_from(two_databases, tmp_path):
    from tests.canonical_store_fake import InMemoryObjectStore
    from tests.storage_mp1_pg_support import adapter

    prod_url, _other = two_databases
    store = InMemoryObjectStore()
    store.origin_host = PROD_REF + ".supabase.co"
    conn = adapter(prod_url)
    try:
        report = object_backup.backup(conn, store, str(tmp_path / "set"), label="source")
        assert report.ok
        assert object_backup.verify_set(str(tmp_path / "set")).ok
    finally:
        conn.close()
    path = tmp_path / "set" / object_backup.MANIFEST_NAME
    manifest = json.loads(path.read_text())
    assert manifest["source"]["store_host"] == PROD_REF + ".supabase.co"
    assert hosting.source_identity_sha256(manifest["source"]["database"]) == \
        hosting.source_identity_sha256(_live_source(prod_url))
    # The source is under the seal: an edited source is a damaged set.
    manifest["source"]["store_host"] = OTHER_REF + ".supabase.co"
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    assert not object_backup.verify_set(str(tmp_path / "set")).ok


@pytest.fixture
def at_c11(tmp_path, monkeypatch):
    """A ledger at C11 bound to the fixtures' PROD project; the local server mapped to that project."""
    from tools import cutover_ledger as ledger

    local_server_is_project(monkeypatch, PROD_REF)
    directory = tmp_path / "ledger"
    ledger.init(directory)
    for index, gate in enumerate(ALL_GATES):
        ledger.grant(directory, gate, f"user-msg-{index}")
    for state in ledger.STATES[: ledger.STATES.index("C11") + 1]:
        ledger.advance(directory, state, GOOD[state])
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "not-a-real-key-" + "x" * 20)  # no object is read: no rows
    monkeypatch.setenv("SGAA_STORAGE_BUCKET", "sgaa-documentos")
    return directory


def _generation(monkeypatch, root, database_url, *, objects, store_ref=PROD_REF):
    from tools import ops_backup

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SUPABASE_URL", f"https://{store_ref}.supabase.co")
    result = ops_backup.run_generation(root, label="source", generations=2, objects=objects,
                                       off_platform=root.parent / (root.name + "-off"))
    assert result["result"] == "GENERATION_COMPLETE"


def _record(directory, root, prod_url):
    from tools import cutover_ledger as ledger

    return ledger.record_backup(directory, root, root.parent / (root.name + "-off"),
                                observer=ledger.Observer(database_url=prod_url))


@NEEDS_PG
def test_real_generations_from_another_database_or_store_are_refused_and_prods_are_recorded(
        two_databases, at_c11, tmp_path, monkeypatch):
    from tools import cutover_ledger as ledger

    prod_url, other_url = two_databases
    prod_identity = hosting.source_identity_sha256(_live_source(prod_url))

    def refused(root):
        with pytest.raises(ledger.Refused) as caught:
            _record(at_c11, root, prod_url)
        return caught.value.code

    # The other database's Layer-2 set, offered while DATABASE_URL is PROD.
    _generation(monkeypatch, tmp_path / "other", other_url, objects=True)
    assert refused(tmp_path / "other") == "BACKUP_NOT_FROM_THE_PROD_DATABASE"
    # PROD's Layer-2 set paired with the other database's object set (the newest of each in one root).
    _generation(monkeypatch, tmp_path / "mixed", other_url, objects=True)
    _generation(monkeypatch, tmp_path / "mixed", prod_url, objects=False)
    assert refused(tmp_path / "mixed") == "OBJECT_SET_NOT_FROM_THE_PROD_PROJECT"
    # PROD's database with an object set read from another project's store.
    _generation(monkeypatch, tmp_path / "store", prod_url, objects=True, store_ref=OTHER_REF)
    assert refused(tmp_path / "store") == "OBJECT_SET_NOT_FROM_THE_PROD_PROJECT"
    # PROD's own generation is recorded, with PROD's identity; nothing foreign was.
    _generation(monkeypatch, tmp_path / "prod", prod_url, objects=True)
    entry = _record(at_c11, tmp_path / "prod", prod_url)
    assert entry["source_identity_sha256"] == prod_identity and entry["object_set_name"] != "NONE"
    assert [e["type"] for e in ledger.read_ledger(at_c11)].count("backup") == 1
    # DATABASE_URL left on another database (a drill's scratch, say) while PROD's next generation is
    # offered: the live database is not the one the generation came from.
    _generation(monkeypatch, tmp_path / "prod", prod_url, objects=False)
    with pytest.raises(ledger.Refused) as caught:
        _record(at_c11, tmp_path / "prod", other_url)
    assert caught.value.code == "BACKUP_NOT_FROM_THE_PROD_DATABASE"
