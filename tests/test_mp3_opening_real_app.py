# coding: utf-8
"""MP-3 R3 remediations (A15, A17), end to end on the REAL application (opt-in, ``SGAA_PG_TEST_URL``).

The cutover's opening and its rollback run through the real ledger commands, observing a real
``main:app`` (hosted production mode, served by a fresh interpreter) and a real scheduler front,
over a disposable PostgreSQL database holding an administrator with a known password and an
overdue returned request (the dashboard's derived-write trap).  The loopback server stands for the
PROD project's database (``tests.mp3_ledger_support.LocalObserver``: its storage API and the
platform's deployment list are scripted; the database, the barrier, the authorization and every
address are real):

* C1 is qualified by the ledger itself; C8's baseline is taken by the governed backup and restore-drilled
  into a fresh scratch database by the drill; C9 and C10 name served applications recorded as deployments.
* C11 -> C12: a governed generation; the reference while every deployment is observed CLOSED, which
  writes the opening authorization into the database; an application lifted with THAT reference admits
  users only because the authorization is there -- one lifted with another value, or before the
  reference, admits no one.
* A real non-operator administrator signs in on the open deployment and views the dashboard: the
  application auto-rejects the overdue request.  ``close`` revokes the authorization (the open
  application turns itself closed) and applies the write barrier: no new session of the application's
  role can write; the ledger proves it, takes the fingerprint live twice and records the rollback only
  when the derived class is acknowledged exactly.
* A real business write instead refuses the rollback; ``resume`` lifts the barrier and the point of no
  return is recorded.

``QUIESCENCE_SECONDS`` is shortened here; the interval itself is pinned by the unit tests.
"""

from __future__ import annotations

import re
import time
from contextlib import ExitStack
from urllib.parse import urlencode

import pytest

from app import hosting
from app.web import admission_gate
from tests import mp3_ledger_support as ls
from tests.mp2_pg_support import ADMIN_EMAIL, ADMIN_PASSWORD, PG_URL, Registry, adapter
from tests.mp3_ledger_support import GOOD, LIFT, PROD_REF, PROJECT_ID
from tests.mp3_served_app import REPO_ROOT, seed_admin_and_requests, served_app
from tools import cutover_ledger as ledger
from tools import hosted_smoke

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

pytest.importorskip("psycopg")
TOKEN = "operator-" + "R5" * 20
# The served applications all answer on this host; the promotion and C10 record it as the public address.
LOCAL_HOST = hosted_smoke.host_digest("http://127.0.0.1")
_FORM = {"Content-Type": "application/x-www-form-urlencoded"}
_CODE = hosting.runtime_code_sha256(REPO_ROOT)  # what every served application announces


def _seed(conn):
    seed_admin_and_requests(conn)
    from app.db import ensure_app_settings_schema

    ensure_app_settings_schema(conn)
    conn.execute("INSERT INTO configuracoes_app(chave, valor) VALUES('auto_indefer_devolvida', '1')"
                 " ON CONFLICT (chave) DO UPDATE SET valor = '1'")
    # A production account always carries a credential row (a Layer-2 domain check).
    conn.execute("INSERT INTO usuario_credenciais(usuario_id, estado) SELECT id, 'personal' FROM usuarios"
                 " ON CONFLICT DO NOTHING")
    from tests.storage_mp1_support import SEEDED_TABLES

    for table in SEEDED_TABLES:  # explicit ids were seeded: identities move past them (a Layer-2 check)
        conn.execute(f"ALTER TABLE {table} ALTER COLUMN id RESTART WITH 100")


@pytest.fixture(scope="module")
def registry():
    registry = Registry("opening")
    try:
        registry.provision_template(seed=_seed)
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def lane(registry, tmp_path, monkeypatch):
    name, url = registry.create(template=registry.template)
    scratch_name, scratch_url = registry.create()
    monkeypatch.setenv("DATABASE_URL", url)
    # The object-set child builds the canonical store from the environment; there are no objects to read.
    monkeypatch.setenv("SUPABASE_URL", f"https://{PROD_REF}.supabase.co")  # the PROD project's store
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "not-a-real-key-" + "x" * 20)
    monkeypatch.setenv("SGAA_STORAGE_BUCKET", "sgaa-documentos")
    monkeypatch.setattr(ledger, "QUIESCENCE_SECONDS", 3)
    platform = ls.Platform()
    stack = ExitStack()
    state = {"url": url, "stack": stack, "tmp": tmp_path, "ledger": tmp_path / "ledger", "served": 0,
             "platform": platform, "scratch": scratch_url}

    def serve(admission, **extra):
        env = {"SGAA_ADMISSION": admission, "VERCEL_PROJECT_ID": PROJECT_ID, **extra}
        if admission == "operator":
            env["SGAA_OPERATOR_TOKEN"] = TOKEN
        state["served"] += 1
        return stack.enter_context(served_app(url, tmp_path / f"app-{state['served']}", **env))

    def observer(base=None, scheduler=None):
        return ls.LocalObserver(base, database_url=url, scheduler_url=scheduler, platform=platform)

    state["serve"], state["observer"] = serve, observer
    try:
        yield state
    finally:
        stack.close()
        registry.drop(scratch_name)
        registry.drop(name)


def _governed(lane, root):
    return ls.governed_local(lane["ledger"], lane["observer"](), lane["tmp"] / root)


def _to_c11(lane):
    """C0..C11 through the real ledger: the ledger's qualification, the governed baseline and its real drill,
    the dark deployment (a served operator application) recorded and promoted."""
    closed = lane["serve"]("operator")
    ls.drive_local_to_c11(lane["ledger"], lane["observer"](), tmp=lane["tmp"], scratch_url=lane["scratch"],
                          code=_CODE, host=LOCAL_HOST, deployment_url=closed.url)
    return closed


def _reference(lane, closed):
    """C11: a governed generation, then the reference while every deployment is observed closed."""
    directory = lane["ledger"]
    # Since GD2 the production deployment's scheduler front is enabled (CRON_SECRET set).
    front = lane["serve"]("operator", CRON_SECRET="c" * 40, wsgi="app.storage.scheduler:application")
    _governed(lane, "backups")
    reference = lane["tmp"] / "reference.json"
    taken = ledger.take_reference(directory, reference, lane["tmp"] / "backups", lane["tmp"] / "backups-off",
                                  cadence_hours=24, observer=lane["observer"](closed.url, front.url))
    assert taken["admission"] == "CLOSED" and taken["code_sha256"] == _CODE
    return taken, reference


def _lift(lane, taken):
    opened = lane["serve"]("open", SGAA_OPENING_REFERENCE=taken["hash"], VERCEL_DEPLOYMENT_ID=LIFT)
    ls.record_served(lane["ledger"], lane["platform"], LIFT, opened.url, code=_CODE, admission="OPEN",
                     opening_reference=taken["hash"])
    ledger.admit_deployment(lane["ledger"], LIFT, observer=lane["observer"]())  # its own platform identity
    ls.promote_served(lane["ledger"], lane["platform"], LIFT, code=_CODE, host=LOCAL_HOST)
    return opened


def _open_cutover(lane):
    closed = _to_c11(lane)
    taken, reference = _reference(lane, closed)
    opened_app = _lift(lane, taken)
    opened = ledger.open_admission(lane["ledger"], observer=lane["observer"](opened_app.url))
    assert opened["state"] == "C12" and opened["evidence"]["opening_authorized"] is True
    return opened_app, reference


def _sign_in_and_view_the_dashboard(base, path="/admin/dashboard"):
    """A non-operator administrator uses the OPEN deployment the ordinary way (a browser's requests)."""
    import http.client
    from urllib.parse import urlsplit

    parts = urlsplit(base)
    cookies: dict[str, str] = {}

    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=60)
        sent = dict(headers or {})
        if cookies:
            sent["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
        conn.request(method, path, body=body, headers=sent)
        response = conn.getresponse()
        data = response.read()
        for cookie in response.msg.get_all("Set-Cookie") or []:
            name, _, rest = cookie.partition("=")
            cookies[name.strip()] = rest.split(";", 1)[0]
        conn.close()
        return response.status, data

    _status, page = request("GET", "/login")
    csrf = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', page).group(1).decode()
    status, _ = request("POST", "/login", urlencode({"csrf_token": csrf, "email": ADMIN_EMAIL,
                                                     "senha": ADMIN_PASSWORD}).encode(), _FORM)
    assert status in {302, 303}
    status, page = request("GET", path)
    assert status == 200
    return page.decode("utf-8")


def test_the_opened_product_shows_the_governed_backup_posture_and_its_restore_validation(lane):
    """SPEC A19: a governed run at C12 publishes the ledger's own records into the database it backed up,
    and the Banco de dados page of the open deployment shows the posture: cadence recorded at the opening,
    the generation current, the baseline's restore drill as the validation."""
    from app.backup import pg_posture

    opened_app, _reference_path = _open_cutover(lane)
    result = _governed(lane, "backups")
    assert result["posture"]["result"] == "PUBLISHED", result["posture"]
    records = [e for e in ledger.read_ledger(lane["ledger"]) if e["type"] in ("backup", "restore")]
    conn = adapter(lane["url"])
    try:
        posture = pg_posture.read(conn.raw_connection)
    finally:
        conn.close()
    assert posture["generations_recorded"] == len([e for e in records if e["type"] == "backup"]) == 3
    assert posture["ignored"] == 0 and posture["ceiling_hours"] == 24
    assert posture["database_status"] == "CURRENT" and posture["validation"]["tables_verified"] > 0
    page = _sign_in_and_view_the_dashboard(opened_app.url, "/admin/banco-dados")
    assert 'data-protection-state="RECORDED"' in page
    assert 'data-protection-database-status="CURRENT"' in page and 'data-protection-objects-status="CURRENT"' in page
    assert 'data-protection-validation="CURRENT"' in page and "teto registrado na abertura: 24 h" in page
    assert "Linha de base" in page and "proteção do próprio provedor" not in page
    assert "data-protection-operations" in page and 'id="pg-retention-form"' in page


def _close_and_quiesce(lane, opened_app):
    """What the operator does first on a rollback: the scheduler front disabled, then `close`."""
    scheduler = lane["serve"]("operator", wsgi="app.storage.scheduler:application")  # no CRON_SECRET: disabled
    observer = lane["observer"](opened_app.url, scheduler.url)
    closed = ledger.close(lane["ledger"], observer=observer)
    assert closed["action"] == "APPLIED"
    # The open deployment reads the revoked authorization at its next check and admits no one.
    time.sleep(admission_gate.OPENING_CHECK_SECONDS + 1)
    assert observer.admission() == "closed"
    return observer


def _write_is_refused(url):
    import psycopg

    conn = adapter(url)
    try:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("UPDATE requisicoes SET horas_solicitadas = horas_solicitadas + 1 WHERE id = 1")
    finally:
        conn.close()


def test_a_dashboard_view_on_the_opened_deployment_is_a_derived_write_and_the_rollback_proves_it(lane):
    opened_app, reference = _open_cutover(lane)
    _sign_in_and_view_the_dashboard(opened_app.url)
    conn = adapter(lane["url"])
    try:
        assert conn.execute("SELECT status FROM requisicoes WHERE id = 2").fetchone()[0] == "Indeferida"
    finally:
        conn.close()
    observer = _close_and_quiesce(lane, opened_app)
    _write_is_refused(lane["url"])  # whatever address or tool would write, the database refuses it now
    directory = lane["ledger"]
    with pytest.raises(ledger.Refused) as caught:  # not acknowledged: refused, nothing written
        ledger.rollback(directory, "OPERATOR_STOP", observer=observer, reference_path=str(reference))
    assert caught.value.code == "DERIVED_CLASSES_NOT_ACKNOWLEDGED"
    entry = ledger.rollback(directory, "OPERATOR_STOP", observer=observer, reference_path=str(reference),
                            derived_classes=["REQUISICOES_AUTO_REJECTION"])
    assert entry["quiescence"] == "PROVEN" and entry["barrier"] == "VERIFIED"
    assert entry["derived_classes"] == ["REQUISICOES_AUTO_REJECTION"]
    assert ledger.status(directory)["rolled_back"] is True
    _write_is_refused(lane["url"])  # the barrier stays after the rollback is recorded


def test_a_business_write_after_the_opening_refuses_the_rollback_resume_reopens_and_the_ponr_is_recorded(lane):
    opened_app, reference = _open_cutover(lane)
    conn = adapter(lane["url"])
    try:
        conn.execute("UPDATE requisicoes SET horas_solicitadas = horas_solicitadas + 1 WHERE id = 1")
        conn.commit()
    finally:
        conn.close()
    directory = lane["ledger"]
    # Still open and no barrier: no proof is even attempted.
    with pytest.raises(ledger.Refused) as caught:
        ledger.rollback(directory, "OPERATOR_STOP", observer=lane["observer"](opened_app.url),
                        reference_path=str(reference))
    assert caught.value.code == "BARRIER_REQUIRED"
    observer = _close_and_quiesce(lane, opened_app)
    with pytest.raises(ledger.Refused) as caught:
        ledger.rollback(directory, "OPERATOR_STOP", observer=observer, reference_path=str(reference),
                        derived_classes=["REQUISICOES_AUTO_REJECTION"])
    assert caught.value.code == "FINGERPRINT_CHANGED"
    current = observer.fingerprint()["fingerprint_sha256"]
    lifted = ledger.resume(directory, observer=observer, backup_root=lane["tmp"] / "backups",
                           off_platform=lane["tmp"] / "backups-off")
    assert lifted["action"] == "LIFTED" and observer.writable()
    time.sleep(admission_gate.OPENING_CHECK_SECONDS + 1)
    assert observer.admission() == "open"  # the authorization stands again: production goes forward
    entry = ledger.advance(directory, "C13", {**GOOD["C13"], "current_fingerprint_sha256": current})
    assert entry["state"] == "C13"


def test_an_application_lifted_before_the_reference_admits_no_one_and_cannot_be_recorded(lane):
    """A premature lift -- a well-formed value, another ledger's reference -- opens nothing (fail closed)."""
    closed = _to_c11(lane)
    premature = lane["serve"]("open", SGAA_OPENING_REFERENCE="5" * 64)
    observer = lane["observer"](premature.url)
    assert observer.admission() == "closed" and observer.code() == _CODE
    # On the platform, that deployment was never recorded: the reference refuses to proceed.
    lane["platform"].deployments["dpl_" + "P" * 24] = {"url": premature.url, "state": "READY", "files": ls.FILES}
    front = lane["serve"]("operator", CRON_SECRET="c" * 40, wsgi="app.storage.scheduler:application")
    _governed(lane, "backups")
    with pytest.raises(ledger.Refused) as caught:
        ledger.take_reference(lane["ledger"], lane["tmp"] / "reference.json", lane["tmp"] / "backups",
                              lane["tmp"] / "backups-off", cadence_hours=24,
                              observer=lane["observer"](closed.url, front.url))
    assert caught.value.code == "UNRECORDED_DEPLOYMENT"
