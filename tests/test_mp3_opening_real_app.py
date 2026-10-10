# coding: utf-8
"""MP-3 R3 remediation, findings 1, 2 and 4, end to end on the REAL application (opt-in, ``SGAA_PG_TEST_URL``).

The cutover's opening and its rollback run through the real ledger commands, observing a real
``main:app`` (hosted production mode, served by a fresh interpreter) and a real scheduler front,
over a disposable PostgreSQL database holding an administrator with a known password and an
overdue returned request (the dashboard's derived-write trap):

* C11 -> C12: a real ``ops_backup`` generation (Layer-2 + object set + off-platform copy) is recorded
  by the ledger; the reference is taken while admission is observed CLOSED and the backup is proven
  current against the live database; the deployment is restarted OPEN and ``open`` observes it.
* A real non-operator administrator signs in on the open deployment and views the dashboard: the
  application auto-rejects the overdue request.  The deployment is closed again and the scheduler
  front is disabled; the ledger observes quiescence, takes the fingerprint live twice, classifies
  the change as the fixed derived class, and records the rollback only when it is acknowledged
  exactly.
* A real business write instead refuses the rollback: the point of no return must be recorded.

The prior states (C0..C11) carry the unit tests' value-free evidence; their own controls are proven
elsewhere.  ``QUIESCENCE_SECONDS`` is shortened here; the interval itself is pinned by the unit tests.
"""

from __future__ import annotations

import re
from contextlib import ExitStack
from urllib.parse import urlencode

import pytest

from tests.mp2_pg_support import ADMIN_EMAIL, ADMIN_PASSWORD, PG_URL, Registry, adapter
from tests.mp3_ledger_support import ALL_GATES, GOOD
from tests.mp3_served_app import seed_admin_and_requests, served_app
from tools import cutover_ledger as ledger
from tools import ops_backup

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT"
)

pytest.importorskip("psycopg")
TOKEN = "operator-" + "R5" * 20
_FORM = {"Content-Type": "application/x-www-form-urlencoded"}


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
    monkeypatch.setenv("DATABASE_URL", url)
    # The object-set child builds the canonical store from the environment; there are no objects to read.
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "not-a-real-key-" + "x" * 20)
    monkeypatch.setenv("SGAA_STORAGE_BUCKET", "sgaa-documentos")
    monkeypatch.setattr(ledger, "QUIESCENCE_SECONDS", 3)
    stack = ExitStack()
    state = {"url": url, "stack": stack, "tmp": tmp_path, "ledger": tmp_path / "ledger", "served": 0}

    def serve(admission, **extra):
        env = {"SGAA_ADMISSION": admission, **extra}
        if admission == "operator":
            env["SGAA_OPERATOR_TOKEN"] = TOKEN
        state["served"] += 1
        return stack.enter_context(served_app(url, tmp_path / f"app-{state['served']}", **env))

    state["serve"] = serve
    try:
        yield state
    finally:
        stack.close()
        registry.drop(name)


def _open_cutover(lane):
    """C0..C11 recorded, then the real opening: generation, record, reference while closed, reopen, open."""
    directory = lane["ledger"]
    ledger.init(directory)
    for index, gate in enumerate(ALL_GATES):
        ledger.grant(directory, gate, f"user-msg-{index}")
    for state in ledger.STATES[: ledger.STATES.index("C11") + 1]:
        ledger.advance(directory, state, GOOD[state])
    with ExitStack() as closed_stack:
        closed = closed_stack.enter_context(served_app(lane["url"], lane["tmp"] / "closed", SGAA_ADMISSION="operator",
                                                       SGAA_OPERATOR_TOKEN=TOKEN))
        observer = ledger.Observer(closed.url, allow_insecure=True, database_url=lane["url"])
        assert observer.admission() == "closed"
        root, off = lane["tmp"] / "backups", lane["tmp"] / "off-platform"
        generation = ops_backup.run_generation(root, label="pre-open", generations=2, objects=True,
                                               off_platform=off)
        assert generation["result"] == "GENERATION_COMPLETE"
        recorded = ledger.record_backup(directory, root, off, observer=observer)
        assert recorded["object_set_name"] != "NONE"
        reference = lane["tmp"] / "reference.json"
        taken = ledger.take_reference(directory, reference, root, off, cadence_hours=24, observer=observer)
        assert taken["admission"] == "CLOSED" and taken["pre_open_backup_manifest_sha256"] == recorded["manifest_sha256"]
    opened_app = lane["serve"]("open")
    opened = ledger.open_admission(directory, observer=ledger.Observer(opened_app.url, allow_insecure=True,
                                                                         database_url=lane["url"]))
    assert opened["state"] == "C12" and opened["evidence"]["admission"] == "OPEN"
    return opened_app, reference


def _sign_in_and_view_the_dashboard(base):
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
    status, _ = request("GET", "/admin/dashboard")
    assert status == 200


def _quiesce(lane):
    """Stop admitting users and disable the scheduler front: what the operator does first on a rollback."""
    closed = lane["serve"]("operator")
    scheduler = lane["serve"]("operator", wsgi="app.storage.scheduler:application")  # no CRON_SECRET: disabled
    return ledger.Observer(closed.url, allow_insecure=True, database_url=lane["url"], scheduler_url=scheduler.url)


def test_a_dashboard_view_on_the_opened_deployment_is_a_derived_write_and_the_rollback_proves_it(lane):
    opened_app, reference = _open_cutover(lane)
    _sign_in_and_view_the_dashboard(opened_app.url)
    conn = adapter(lane["url"])
    try:
        assert conn.execute("SELECT status FROM requisicoes WHERE id = 2").fetchone()[0] == "Indeferida"
    finally:
        conn.close()
    observer = _quiesce(lane)
    directory = lane["ledger"]
    with pytest.raises(ledger.Refused) as caught:  # not acknowledged: refused, nothing written
        ledger.rollback(directory, "OPERATOR_STOP", observer=observer, reference_path=str(reference))
    assert caught.value.code == "DERIVED_CLASSES_NOT_ACKNOWLEDGED"
    entry = ledger.rollback(directory, "OPERATOR_STOP", observer=observer, reference_path=str(reference),
                            derived_classes=["REQUISICOES_AUTO_REJECTION"])
    assert entry["quiescence"] == "PROVEN" and entry["derived_classes"] == ["REQUISICOES_AUTO_REJECTION"]
    assert ledger.status(directory)["rolled_back"] is True


def test_a_business_write_after_the_opening_refuses_the_rollback_and_the_ponr_is_recorded(lane):
    opened_app, reference = _open_cutover(lane)
    conn = adapter(lane["url"])
    try:
        conn.execute("UPDATE requisicoes SET horas_solicitadas = horas_solicitadas + 1 WHERE id = 1")
        conn.commit()
    finally:
        conn.close()
    directory = lane["ledger"]
    # Still open: no proof is even attempted.
    still_open = ledger.Observer(opened_app.url, allow_insecure=True, database_url=lane["url"])
    with pytest.raises(ledger.Refused) as caught:
        ledger.rollback(directory, "OPERATOR_STOP", observer=still_open, reference_path=str(reference))
    assert caught.value.code == "ADMISSION_STILL_OPEN"
    observer = _quiesce(lane)
    with pytest.raises(ledger.Refused) as caught:
        ledger.rollback(directory, "OPERATOR_STOP", observer=observer, reference_path=str(reference),
                        derived_classes=["REQUISICOES_AUTO_REJECTION"])
    assert caught.value.code == "FINGERPRINT_CHANGED"
    current = observer.fingerprint()["fingerprint_sha256"]
    entry = ledger.advance(directory, "C13", {**GOOD["C13"], "current_fingerprint_sha256": current})
    assert entry["state"] == "C13"


def test_the_reference_is_refused_while_the_deployment_already_admits_everyone(lane):
    directory = lane["ledger"]
    ledger.init(directory)
    for index, gate in enumerate(ALL_GATES):
        ledger.grant(directory, gate, f"user-msg-{index}")
    for state in ledger.STATES[: ledger.STATES.index("C11") + 1]:
        ledger.advance(directory, state, GOOD[state])
    opened = lane["serve"]("open")
    observer = ledger.Observer(opened.url, allow_insecure=True, database_url=lane["url"])
    root, off = lane["tmp"] / "backups", lane["tmp"] / "off-platform"
    ops_backup.run_generation(root, label="pre-open", generations=2, objects=True, off_platform=off)
    ledger.record_backup(directory, root, off, observer=observer)
    with pytest.raises(ledger.Refused) as caught:
        ledger.take_reference(directory, lane["tmp"] / "reference.json", root, off, cadence_hours=24,
                              observer=observer)
    assert caught.value.code == "ADMISSION_NOT_CLOSED"
