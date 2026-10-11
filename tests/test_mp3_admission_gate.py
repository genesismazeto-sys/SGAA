# coding: utf-8
"""MP-3 R3 remediation, finding 1: the hosted pre-opening admission gate (``app.web.admission_gate``).

Unit part: the contract of ``app.hosting`` (production must decide; ``operator`` needs a credential;
nothing is echoed).  Real-application part (opt-in, ``SGAA_PG_TEST_URL``): ``main:app`` served by a
fresh interpreter in hosted production mode over a disposable PostgreSQL database.

* Before the opening a stranger -- even one who knows a valid administrator password -- is refused
  every page and every credential POST with 503 ``X-SGAA-Admission: closed``, no cookie, and the
  database does not change by a single row (business, throttle or any other table).
* The operator passes with the credential: the public smoke (header) and a browser (the admission
  form, then an HMAC cookie) both work; a forged cookie or a wrong token does not.
* Opening is the only switch: the same database served with ``SGAA_ADMISSION=open`` admits everyone
  and has no admission route.
"""

from __future__ import annotations

import http.client
import re
import time
from urllib.parse import urlencode, urlsplit

import pytest

from app import hosting
from app.hosting import Blocker
from tests.mp2_pg_support import ADMIN_EMAIL, ADMIN_PASSWORD, PG_URL, Registry, adapter
from tests.mp3_served_app import REPO_ROOT, seed_admin_and_requests, served_app
from tools import hosted_smoke

NEEDS_PG = pytest.mark.skipif(not PG_URL, reason="SGAA_PG_TEST_URL is not configured -- REAL-PG EVIDENCE: ABSENT")
TOKEN = "operator-" + "Q7" * 20
SENTINEL = "SENTINEL-ADMISSION-VALUE-0123456789"
REFERENCE = "ab" * 32  # a cutover reference digest the opening is lifted with


# ---- the contract -----------------------------------------------------------------------------


@pytest.mark.parametrize("raw,production,expected", [
    ("operator", True, "operator"), ("OPEN", True, "open"), (" open ", False, "open"),
    ("", True, None), ("", False, "open"), ("closed", True, None), ("closed", False, None),
    ("yes", False, None),
])
def test_production_must_decide_and_nothing_is_guessed(raw, production, expected):
    assert hosting.admission_mode({"SGAA_ADMISSION": raw}, production=production) == expected


def test_a_process_on_a_serverless_platform_must_decide_even_outside_production():
    """A deployment missing APP_ENV runs non-production; on the platform it still has to decide."""
    assert hosting.admission_mode({"SGAA_ADMISSION": "", "VERCEL": "1"}, production=False) is None
    assert hosting.admission_mode({"SGAA_ADMISSION": "operator", "VERCEL": "1"}, production=False) == "operator"
    assert hosting.admission_mode({"SGAA_ADMISSION": ""}, production=False) == "open"  # a workstation, a test


def test_the_code_identity_is_the_deployed_code_and_never_what_the_platform_writes_at_build(tmp_path):
    """Observed on the rehearsal project (MP-3 A17): the function holds the uploaded code paths byte for byte,
    ``vercel.json`` rewritten, and a ``pyproject.toml`` / ``uv.lock`` the Python builder adds.  The identity
    the application announces must equal the one the governed deploy computes from the export."""
    files = {"app/__init__.py": b"x = 1\n", "app/web/gate.py": b"y = 2\n", "static/app.css": b"body{}",
             "templates/a.html": b"<p>", "main.py": b"import app\n", "requirements.txt": b"flask\n",
             ".python-version": b"3.12\n"}
    for relative, data in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_bytes(data)
    export = hosting.code_sha256({path: hosting.git_blob_id(data) for path, data in files.items()})
    assert hosting.runtime_code_sha256(tmp_path) == export
    for relative, data in (("vercel.json", b'{"rewritten": true}'), ("pyproject.toml", b"[project]\n"),
                           ("uv.lock", b"lock"), (".vercelignore", b"*"), ("app/__pycache__/gate.cpython-312.pyc", b"c"),
                           ("app/web/gate.cpython-312.pyc", b"c"), ("_vendor/flask/__init__.py", b"v"),
                           ("___vc/__env.encrypted", b"e")):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_bytes(data)
    assert hosting.runtime_code_sha256(tmp_path) == export  # build outputs and the platform's files are not code
    (tmp_path / "app" / "web" / "gate.py").write_bytes(b"y = 3\n")
    assert hosting.runtime_code_sha256(tmp_path) != export  # one changed byte of code is another identity
    assert not any(hosting.is_code_path(p) for p in ("pyproject.toml", "uv.lock", "vercel.json", "public/x.css"))


def test_the_opening_reference_is_a_digest_and_its_tag_is_what_the_ledger_expects():
    assert hosting.opening_reference({"SGAA_OPENING_REFERENCE": REFERENCE.upper()}) == REFERENCE
    for bad in ("", "ab" * 31, "zz" * 32, "ab" * 32 + "0"):
        assert hosting.opening_reference({"SGAA_OPENING_REFERENCE": bad}) is None
    assert hosting.opening_tag(REFERENCE) != hosting.opening_tag("cd" * 32) and len(hosting.opening_tag(REFERENCE)) == 64


def test_install_itself_refuses_an_undecided_an_uncredentialled_or_an_unbound_production_app():
    """Defence in depth behind the startup blockers: the gate never installs a guessed state."""
    from flask import Flask

    from app.hosting import HostingConfigurationError
    from app.web import admission_gate

    for env, code in (({}, "HOSTED_ADMISSION_UNDECIDED"),
                      ({"SGAA_ADMISSION": "operator"}, "HOSTED_OPERATOR_TOKEN_REQUIRED"),
                      ({"SGAA_ADMISSION": "open"}, "HOSTED_OPENING_REFERENCE_REQUIRED")):
        app = Flask(__name__)
        app.config["IS_PRODUCTION"] = True
        with pytest.raises(HostingConfigurationError) as caught:
            admission_gate.install(app, env)
        assert [b.code for b in caught.value.blockers] == [code]
    app = Flask(__name__)
    app.config["IS_PRODUCTION"] = True
    assert admission_gate.install(app, {"SGAA_ADMISSION": "open", "SGAA_OPENING_REFERENCE": REFERENCE}) == "open"
    assert app.config["SGAA_OPENING_TAG"] == hosting.opening_tag(REFERENCE)


@pytest.mark.parametrize("token,ok", [
    ("a" * 32, True), ("a" * 31, False), ("", False), ("é" * 40, False), ("a" * 31 + "\n", False),
    ("a\x00" + "b" * 40, False),
])
def test_the_operator_credential_has_a_minimum_shape(token, ok):
    assert (hosting.operator_token({"SGAA_OPERATOR_TOKEN": token}) is not None) is ok


def _blockers(env, monkeypatch, *, production):
    import app.db as app_db

    monkeypatch.setattr(app_db, "DATABASE_URL", "postgresql://sgaa@127.0.0.1:1/none")
    base = {"TRUST_PROXY_XFF": "1", "SUPABASE_URL": "https://abcdefghijklmnop.supabase.co",
            "SUPABASE_SECRET_KEY": "sb_secret_" + "x" * 30, "SGAA_STORAGE_BUCKET": "sgaa-documentos"}
    return hosting.startup_blockers({**base, **env}, production=production)


def test_a_production_start_refuses_without_an_admission_decision_or_without_the_credential(monkeypatch):
    assert _blockers({}, monkeypatch, production=True) == (Blocker("HOSTED_ADMISSION_UNDECIDED", ("SGAA_ADMISSION",)),)
    assert _blockers({"SGAA_ADMISSION": SENTINEL}, monkeypatch, production=True) == (
        Blocker("HOSTED_ADMISSION_UNDECIDED", ("SGAA_ADMISSION",)),)
    assert _blockers({"SGAA_ADMISSION": "operator"}, monkeypatch, production=True) == (
        Blocker("HOSTED_OPERATOR_TOKEN_REQUIRED", ("SGAA_OPERATOR_TOKEN",)),)
    short = _blockers({"SGAA_ADMISSION": "operator", "SGAA_OPERATOR_TOKEN": "x" * 31}, monkeypatch, production=True)
    assert [b.code for b in short] == ["HOSTED_OPERATOR_TOKEN_REQUIRED"]
    assert _blockers({"SGAA_ADMISSION": "operator", "SGAA_OPERATOR_TOKEN": TOKEN}, monkeypatch, production=True) == ()
    opening = Blocker("HOSTED_OPENING_REFERENCE_REQUIRED", ("SGAA_OPENING_REFERENCE",))
    assert _blockers({"SGAA_ADMISSION": "open"}, monkeypatch, production=True) == (opening,)
    assert _blockers({"SGAA_ADMISSION": "open", "SGAA_OPENING_REFERENCE": "ab" * 31}, monkeypatch,
                     production=True) == (opening,)
    assert _blockers({"SGAA_ADMISSION": "open", "SGAA_OPENING_REFERENCE": REFERENCE}, monkeypatch,
                     production=True) == ()
    assert _blockers({}, monkeypatch, production=False) == ()  # a workstation or a test serves no real user
    assert _blockers({"SGAA_ADMISSION": "open"}, monkeypatch, production=False) == ()
    # On the platform even a deployment that forgot APP_ENV must decide, and an opening names its reference.
    assert _blockers({"VERCEL": "1"}, monkeypatch, production=False) == (
        Blocker("HOSTED_ADMISSION_UNDECIDED", ("SGAA_ADMISSION",)),)
    assert _blockers({"VERCEL": "1", "SGAA_ADMISSION": "open"}, monkeypatch, production=False) == (opening,)
    assert SENTINEL not in repr(_blockers({"SGAA_ADMISSION": SENTINEL}, monkeypatch, production=True))


# ---- the real application -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registry():
    registry = Registry("admission")
    try:
        registry.provision_template(seed=seed_admin_and_requests)
        yield registry
    finally:
        assert registry.close() == 0


@pytest.fixture
def database(registry):
    name, url = registry.create(template=registry.template)
    yield url
    registry.drop(name)


def _whole_database(url) -> dict:
    """Every row of every table in ``public``, digested: any write at all changes it."""
    conn = adapter(url)
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename").fetchall()]
        state = {}
        for table in tables:
            state[table] = tuple(conn.execute(
                f'SELECT count(*), md5(coalesce(string_agg(t::text, \'|\' ORDER BY t::text), \'\')) FROM public."{table}" t'
            ).fetchone())
        conn.rollback()
        return state
    finally:
        conn.close()


def _request(base, method, path, *, body=None, headers=None):
    parts = urlsplit(base)
    conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=30)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, data, \
            response.msg.get_all("Set-Cookie") or []
    finally:
        conn.close()


_FORM = {"Content-Type": "application/x-www-form-urlencoded"}
STRANGER_REQUESTS = (
    ("GET", "/", None, {}),
    ("GET", "/login", None, {}),
    ("GET", "/admin/dashboard", None, {}),
    ("GET", "/csrf-token", None, {}),
    ("GET", "/primeiro-acesso", None, {}),
    ("POST", "/login", urlencode({"email": ADMIN_EMAIL, "senha": ADMIN_PASSWORD}).encode(), _FORM),
    ("POST", "/login", urlencode({"email": "aluno@example.invalid", "senha": "x" * 12}).encode(), _FORM),
    ("POST", "/esqueci-minha-senha", urlencode({"email": ADMIN_EMAIL}).encode(), _FORM),
    ("POST", "/redefinir-senha/abc", urlencode({"senha": "y" * 12}).encode(), _FORM),
    ("GET", "/login", None, {"X-SGAA-Operator-Token": "wrong-" + "x" * 40}),
    ("GET", "/login", None, {"Cookie": "sgaa_operator=" + "0" * 64}),
)


@NEEDS_PG
def test_before_the_opening_a_stranger_is_refused_everything_and_writes_nothing(database, tmp_path):
    before = _whole_database(database)
    with served_app(database, tmp_path, SGAA_ADMISSION="operator", SGAA_OPERATOR_TOKEN=TOKEN) as app:
        for method, path, body, headers in STRANGER_REQUESTS:
            status, seen, data, cookies = _request(app.url, method, path, body=body, headers=headers)
            assert (status, seen.get("x-sgaa-admission"), cookies) == (503, "closed", []), (method, path)
            assert b"csrf" not in data.lower() and ADMIN_EMAIL.encode() not in data
        assert hosted_smoke.probe_admission(app.url, allow_insecure=True) == "closed"
        # Reachable without the credential: the health check (read-only) and static files.
        assert _request(app.url, "GET", "/health")[0] == 200
        assert _request(app.url, "GET", "/static/css/modern-style.css")[0] == 200
        # A wrong token at the admission form is refused and sets no admission cookie.
        status, _seen, form, cookies = _request(app.url, "GET", "/operator-admission")
        csrf = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', form).group(1).decode()
        session_cookie = "; ".join(c.split(";", 1)[0] for c in cookies)
        status, _seen, _data, cookies = _request(
            app.url, "POST", "/operator-admission", headers={**_FORM, "Cookie": session_cookie},
            body=urlencode({"csrf_token": csrf, "token": "wrong-" + "z" * 40}).encode())
        assert status == 403 and not any(c.startswith("sgaa_operator=") for c in cookies)
    assert _whole_database(database) == before  # not one row, in any table


@NEEDS_PG
def test_before_the_opening_the_operator_smoke_passes_with_the_credential(database, tmp_path):
    with served_app(database, tmp_path, SGAA_ADMISSION="operator", SGAA_OPERATOR_TOKEN=TOKEN) as app:
        report = hosted_smoke.run(app.url, allow_insecure=True, operator_token=TOKEN, admission="closed",
                                  email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
        failed = [(c["check"], c["code"]) for c in report["checks"] if not c["ok"]]
        assert report["result"] == "PASS", failed
        assert {c["check"] for c in report["checks"]} >= {"ADMISSION", "SIGN_IN", "LOGIN_PAGE", "HEADERS"}


@NEEDS_PG
def test_before_the_opening_a_browser_enters_once_with_the_token_and_then_carries_only_an_hmac(database, tmp_path):
    with served_app(database, tmp_path, SGAA_ADMISSION="operator", SGAA_OPERATOR_TOKEN=TOKEN) as app:
        _status, _seen, form, cookies = _request(app.url, "GET", "/operator-admission")
        csrf = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', form).group(1).decode()
        session_cookie = "; ".join(c.split(";", 1)[0] for c in cookies)
        status, seen, _data, cookies = _request(
            app.url, "POST", "/operator-admission", headers={**_FORM, "Cookie": session_cookie},
            body=urlencode({"csrf_token": csrf, "token": TOKEN}).encode())
        assert status == 303 and seen["location"].endswith("/login")
        admission = [c for c in cookies if c.startswith("sgaa_operator=")]
        assert len(admission) == 1 and TOKEN not in admission[0]
        assert re.search(r";\s*httponly", admission[0], re.I) and re.search(r";\s*secure", admission[0], re.I)
        carried = admission[0].split(";", 1)[0]
        assert _request(app.url, "GET", "/login", headers={"Cookie": carried})[0] == 200
        # The CSRF protection still guards the form: without its token the right credential is refused.
        assert _request(app.url, "POST", "/operator-admission", headers=_FORM,
                        body=urlencode({"token": TOKEN}).encode())[0] in {400, 403}


@NEEDS_PG
def test_the_admission_cookie_expires_and_cannot_be_dated_or_forged(database, tmp_path):
    from app.web import admission_gate
    from tests.mp3_served_app import SERVED_SECRET_KEY

    now = int(time.time())

    def carried(cookie):
        return _request(app.url, "GET", "/login", headers={"Cookie": f"sgaa_operator={cookie}"})[0]

    with served_app(database, tmp_path, SGAA_ADMISSION="operator", SGAA_OPERATOR_TOKEN=TOKEN) as app:
        assert carried(admission_gate.cookie_for(SERVED_SECRET_KEY, TOKEN, now)) == 200  # control
        assert carried(admission_gate.cookie_for(SERVED_SECRET_KEY, TOKEN,
                                                 now - admission_gate.ADMISSION_COOKIE_SECONDS - 5)) == 503
        assert carried(admission_gate.cookie_for(SERVED_SECRET_KEY, TOKEN, now + 3600)) == 503
        assert carried(admission_gate.cookie_for(SERVED_SECRET_KEY, "x" * 40, now)) == 503
        assert carried(admission_gate.cookie_for("another-key-" + "z" * 40, TOKEN, now)) == 503
        old_mac = admission_gate.cookie_for(SERVED_SECRET_KEY, TOKEN, now - 10 ** 6).split(".", 1)[1]
        assert carried(f"{now}.{old_mac}") == 503  # an old cookie re-dated
        assert "x-sgaa-opening" not in _request(app.url, "GET", "/health")[1]


@NEEDS_PG
def test_opening_is_the_switch_the_same_database_served_open_admits_everyone(database, tmp_path):
    before = _whole_database(database)
    with served_app(database, tmp_path, SGAA_ADMISSION="open") as app:  # lifted under a standing authorization
        reference = app.opening_reference
        status, seen, page, cookies = _request(app.url, "GET", "/login")
        assert status == 200 and "x-sgaa-admission" not in seen
        assert _request(app.url, "GET", "/operator-admission")[0] == 404
        assert hosted_smoke.probe_admission(app.url, allow_insecure=True) == "open"
        # The opening announces the reference it was lifted with, and its code, on every response.
        assert seen["x-sgaa-opening"] == hosting.opening_tag(reference)
        assert hosted_smoke.probe_opening_tag(app.url, allow_insecure=True) == hosting.opening_tag(reference)
        assert hosted_smoke.probe_code(app.url, allow_insecure=True) == hosting.runtime_code_sha256(REPO_ROOT)
        # Control for the "writes nothing" witness: once open, a stranger's failed sign-in IS a write.
        csrf = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', page).group(1).decode()
        session_cookie = "; ".join(c.split(";", 1)[0] for c in cookies)
        _request(app.url, "POST", "/login", headers={**_FORM, "Cookie": session_cookie},
                 body=urlencode({"csrf_token": csrf, "email": ADMIN_EMAIL, "senha": "wrong-" + "p" * 12}).encode())
    after = _whole_database(database)
    assert after != before and after["auth_throttle_events"] != before["auth_throttle_events"]


@NEEDS_PG
def test_a_production_deployment_without_an_admission_decision_does_not_start(database, tmp_path):
    from tests.mp3_served_app import hosted_environment

    env = hosted_environment(database, tmp_path)
    env.pop("SGAA_ADMISSION")
    import subprocess
    import sys

    from tests.mp3_served_app import REPO_ROOT

    done = subprocess.run([sys.executable, "-m", "app.hosting_cli", "check"], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 1 and "HOSTED_ADMISSION_UNDECIDED" in done.stdout
    env["SGAA_ADMISSION"] = "operator"
    done = subprocess.run([sys.executable, "-m", "app.hosting_cli", "check"], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 1 and "HOSTED_OPERATOR_TOKEN_REQUIRED" in done.stdout
    env["SGAA_OPERATOR_TOKEN"] = TOKEN
    done = subprocess.run([sys.executable, "-m", "app.hosting_cli", "check"], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 0 and '"admission": "operator"' in done.stdout and TOKEN not in done.stdout
    # An opening without the reference it is lifted with does not start either.
    env["SGAA_ADMISSION"] = "open"
    env.pop("SGAA_OPENING_REFERENCE")
    done = subprocess.run([sys.executable, "-m", "app.hosting_cli", "check"], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 1 and "HOSTED_OPENING_REFERENCE_REQUIRED" in done.stdout


# ---- the opening authorization, on the real application (MP-3 A17 finding 1) -------------------------------


def _identity(url):
    conn = adapter(url)
    try:
        return hosting.source_identity_sha256(hosting.database_source(conn.raw_connection))
    finally:
        conn.close()


def _authorization(url, *, kind="reference", identity=None, code=None, project=None, reference=None,
                   tamper=False, revoked=False, key=None):
    """Write one authorization row the way the ledger shapes it; returns the reference to lift with."""
    import hashlib

    from tests.mp3_served_app import PROJECT_ID

    own_code = hosting.runtime_code_sha256(REPO_ROOT)
    body = {"seq": 7, "prev": "0" * 64, "at": "2026-11-01T00:00:00Z", "type": kind,
            "database_identity_sha256": identity or _identity(url), "code_sha256": code or own_code,
            "vercel_project_sha256": project or hashlib.sha256(PROJECT_ID.encode()).hexdigest()}
    if kind == "authorization":
        body["opening_reference"] = reference
    entry = dict(body, hash=hosting.ledger_entry_hash(body))
    lifted = key or (entry["hash"] if kind == "reference" else reference)
    if tamper:
        entry["seq"] = 8  # no longer the entry its hash names
    import json

    conn = adapter(url)
    raw = conn.raw_connection  # the ledger's own SQL, with psycopg placeholders
    try:
        for statement in hosting.OPENING_DDL:
            raw.execute(statement)
        raw.execute(hosting.OPENING_INSERT_SQL, (lifted, own_code, json.dumps(entry)))
        if revoked:
            raw.execute(hosting.OPENING_REVOKE_SQL)
        raw.commit()
    finally:
        conn.close()
    return lifted


@NEEDS_PG
@pytest.mark.parametrize("case", [
    "no_row", "revoked", "other_code", "other_database", "other_project", "not_a_ledger_entry", "other_kind",
])
def test_an_open_application_admits_no_one_without_a_standing_authorization_for_itself(database, tmp_path, case):
    """A well-formed value, a revoked or edited authorization, or one for another code, database or platform
    project opens nothing: the application answers like a closed deployment and writes nothing."""
    if case == "no_row":
        reference = "6" * 64
    elif case == "revoked":
        reference = _authorization(database, revoked=True)
    elif case == "other_code":
        reference = _authorization(database, code="9" * 64)
    elif case == "other_database":
        reference = _authorization(database, identity="8" * 64)
    elif case == "other_project":
        reference = _authorization(database, project="7" * 64)
    elif case == "not_a_ledger_entry":
        reference = _authorization(database, tamper=True)
    else:  # stored under the lifted reference, but a forward-fix authorization naming another one
        reference = _authorization(database, kind="authorization", reference="4" * 64, key="3" * 64)
    before = _whole_database(database)
    with served_app(database, tmp_path, SGAA_ADMISSION="open", SGAA_OPENING_REFERENCE=reference) as app:
        for method, path, body, headers in STRANGER_REQUESTS[:6]:
            status, seen, _data, cookies = _request(app.url, method, path, body=body, headers=headers)
            assert (status, seen.get("x-sgaa-admission"), cookies) == (503, "closed", []), (case, method, path)
        assert hosted_smoke.probe_admission(app.url, allow_insecure=True) == "closed"
        status, seen, _data, _cookies = _request(app.url, "GET", "/health")
        assert seen.get("x-sgaa-code") == hosting.runtime_code_sha256(REPO_ROOT)  # it still names its code
    assert _whole_database(database) == before


@NEEDS_PG
def test_a_forward_fix_authorization_naming_the_lifted_reference_admits_users(database, tmp_path):
    """The positive control of the authorization kind a forward fix uses (``authorize-code``)."""
    reference = "2" * 64
    _authorization(database, kind="authorization", reference=reference)
    with served_app(database, tmp_path, SGAA_ADMISSION="open", SGAA_OPENING_REFERENCE=reference) as app:
        assert hosted_smoke.probe_admission(app.url, allow_insecure=True) == "open"
