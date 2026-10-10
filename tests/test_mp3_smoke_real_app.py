# coding: utf-8
"""MP-3 slice 5 on real PostgreSQL (opt-in): the public smoke against the REAL application.

``test_mp3_hosted_smoke`` pins the tool against a scripted server.  Here the tool
runs over HTTP against ``main:app`` -- the entrypoint a WSGI host loads -- in
production + hosted mode, in a FRESH interpreter with a platform-shaped
environment and a disposable PostgreSQL database, so a header, a cookie flag or
a route the smoke expects is proven to be what the application actually does.
Without ``SGAA_PG_TEST_URL`` the module skips (REAL-PG EVIDENCE: ABSENT).
"""

from __future__ import annotations

import pytest

from tests.mp2_pg_support import ADMIN_EMAIL, ADMIN_PASSWORD, PG_URL, Registry
from tests.mp3_served_app import seed_admin_and_requests, served_app
from tools import hosted_smoke, pg_fingerprint

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

pytest.importorskip("psycopg")



@pytest.fixture(scope="module")
def registry():
    registry = Registry("smoke")
    try:
        registry.provision_template(seed=seed_admin_and_requests)
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def served(registry, tmp_path):
    """``main:app`` in production + hosted mode (admission open) served by a child interpreter."""
    name, url = registry.create(template=registry.template)
    try:
        with served_app(url, tmp_path) as app:
            yield app
    finally:
        registry.drop(name)


def _fingerprint(url):
    from tools import pg_backup

    conn = pg_backup.connect(url)
    try:
        return pg_fingerprint.snapshot(conn)
    finally:
        conn.close()


def test_the_real_application_passes_every_public_check_and_the_smoke_writes_no_business_row(served):
    before = _fingerprint(served.database)
    report = hosted_smoke.run(served.url, allow_insecure=True, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
    failed = [(item["check"], item["code"]) for item in report["checks"] if not item["ok"]]
    assert report["result"] == "PASS", failed
    assert {item["check"] for item in report["checks"]} >= {
        "HEALTH", "LOGIN_PAGE", "COOKIE_FLAGS", "HEADERS", "ADMIN_REFUSED", "STATIC", "SCHEDULER",
        "NO_TRACEBACK", "SIGN_IN",
    }
    # The smoke's only application write is the sign-in; the PONR detector must not see it (SPEC D8).
    assert pg_fingerprint.compare(before, _fingerprint(served.database)) == {
        "identical": True, "changed_tables": [], "detail": {}}


def _smoke(served):
    report = hosted_smoke.run(served.url, allow_insecure=True, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
    assert report["result"] == "PASS", [(i["check"], i["code"]) for i in report["checks"] if not i["ok"]]


def test_a_legacy_access_level_is_normalized_once_by_the_first_sign_in_so_the_reference_follows_the_smoke(served):
    """A student row that kept the legacy default is rewritten by the application's own start-up
    normalization on the first sign-in -- a derived write the PONR detector WOULD count.  The cutover
    order (smoke C10 before the reference C12) makes it happen before the reference; this pins both facts."""
    from tools import pg_backup

    conn = pg_backup.connect(served.database)
    try:
        conn.execute("UPDATE usuarios SET nivel_acesso = 'administrativo' WHERE id = 2")
        conn.commit()
    finally:
        conn.close()
    reference_before_smoke = _fingerprint(served.database)
    _smoke(served)
    after_first = pg_fingerprint.compare(reference_before_smoke, _fingerprint(served.database))
    assert after_first["changed_tables"] == ["USUARIOS"]
    assert after_first["detail"]["USUARIOS"]["changed_columns"] == ["nivel_acesso"]
    reference_after_smoke = _fingerprint(served.database)
    _smoke(served)
    assert pg_fingerprint.compare(reference_after_smoke, _fingerprint(served.database))["identical"] is True


def test_the_seeded_requests_are_what_the_trap_needs(served):
    from tools import pg_backup

    conn = pg_backup.connect(served.database)
    try:
        rows = conn.execute("SELECT id, status FROM requisicoes ORDER BY id").fetchall()
    finally:
        conn.close()
    assert [tuple(row) for row in rows] == [(1, "Pendente"), (2, "Devolvida")]
