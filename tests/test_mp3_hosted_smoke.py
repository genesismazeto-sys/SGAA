# coding: utf-8
"""MP-3 slice 5: the public smoke (``tools/hosted_smoke.py``) against a scripted local server.

The tool must pass a deployment that honours the contract and fail each
defect it names: a failing health check, a cookie without a flag, a missing
header, an admin page that answers anonymously, an unserved static asset, a
scheduler that is open, a trace in an error page, a data API that serves, an
admission state other than the one declared.  Every output is value-free (no
host, no body).
"""

from __future__ import annotations

import base64
import io
import json
import threading
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

from tools import hosted_smoke as smoke

GOOD_HEADERS = [
    ("Content-Security-Policy", "default-src 'self'"),
    ("Strict-Transport-Security", "max-age=31536000"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
]
LOGIN_HTML = (b'<html><link rel="stylesheet" href="/static/css/app.css">'
              b'<form><input name="csrf_token" type="hidden" value="tok123"></form></html>')
OPERATOR_TOKEN = "op-" + "t" * 40
PROJECT = "127.0.0.1"  # the scripted data-API server is this project's address (PROJECT_HOST_TEMPLATE below)
SEEN_OPERATOR_HEADER_ON_DATA_API = []


class _Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(autouse=True)
def _local_project_host(monkeypatch):
    monkeypatch.setattr(smoke, "PROJECT_HOST_TEMPLATE", "{ref}")
    SEEN_OPERATOR_HEADER_ON_DATA_API.clear()


def _app(**defect):
    def application(environ, start_response):
        path, method = environ["PATH_INFO"], environ["REQUEST_METHOD"]
        # Read the body first: a stub that closes with an unread request body resets the connection on
        # Windows, which the smoke rightly reports as UNREACHABLE (seen once under load).
        length = int(environ.get("CONTENT_LENGTH") or 0)
        if length:
            environ["wsgi.input"].read(length)
        headers = [h for h in GOOD_HEADERS if h[0] not in defect.get("drop_headers", ())]

        def reply(status, body=b"", extra=()):
            start_response(status, [("Content-Type", "text/html"), *headers, *extra])
            return [body]

        if defect.get("admission_closed") and path != "/health" and not path.startswith("/static/") \
                and environ.get("HTTP_X_SGAA_OPERATOR_TOKEN", "") != OPERATOR_TOKEN:
            extra = [("X-SGAA-Admission", "closed")]
            if defect.get("closed_sets_cookie"):
                extra.append(("Set-Cookie", "session=leak; Secure; HttpOnly; SameSite=Lax"))
            if defect.get("closed_admits_post") and method == "POST":
                return reply("302 Found", b"", [("Location", "/admin/dashboard")])
            return reply("503 Service Unavailable", b"<p>fechado</p>", extra)
        if path == "/health":
            body = b'{"status": "degraded"}' if defect.get("health_body") else b'{"status": "ok"}'
            announced = [("X-SGAA-Opening", defect["opening_tag"])] if defect.get("opening_tag") else []
            return reply("500 ERR" if defect.get("health") else "200 OK", body, announced)
        if defect.get("login_missing") and path == "/login" and method == "GET":  # not an application page
            return reply("404 Not Found", b"<h1>404</h1>")
        if path == "/login" and method == "GET":
            cookie = "session=abc; Path=/; HttpOnly; SameSite=Lax"
            if not defect.get("cookie_no_secure"):
                cookie += "; Secure"
            return reply("200 OK", LOGIN_HTML, [("Set-Cookie", cookie)])
        if path == "/login" and method == "POST":
            return reply("302 Found", b"", [("Location", "/admin/dashboard"), ("Set-Cookie", "session=on; HttpOnly")])
        if path == "/admin/dashboard":
            if environ.get("HTTP_COOKIE", "").find("session=on") >= 0:
                return reply("200 OK", b"dash")
            if defect.get("admin_open"):
                return reply("200 OK")
            location = "/somewhere-else" if defect.get("admin_redirects_elsewhere") else "/login"
            return reply("302 Found", b"", [("Location", location)])
        if path == "/csrf-token":
            if environ.get("HTTP_COOKIE", "").find("session=on") >= 0:
                return reply("200 OK", b'{"csrf_token": "t"}')
            return reply("401 Unauthorized", b"{}")
        if path == "/static/css/app.css":
            return reply("404 Not Found" if defect.get("static") else "200 OK", b"x")
        if path == "/internal/scheduler/mirror":
            if defect.get("scheduler_disabled"):
                return reply("404 Not Found", b"{}")
            return reply("200 OK" if defect.get("scheduler_open") else "401 Unauthorized", b"{}")
        if path == "/rest/v1/usuarios":
            if environ.get("HTTP_X_SGAA_OPERATOR_TOKEN"):
                SEEN_OPERATOR_HEADER_ON_DATA_API.append(True)
            # The platform gateway refuses a bogus key whatever the Data API state is.
            if environ.get("HTTP_APIKEY", "") not in ("pub-key-123", defect.get("valid_key", "")) \
                    and not defect.get("gateway_open"):
                return reply("401 Unauthorized", b'{"message":"Invalid API key"}')
            profile = environ.get("HTTP_ACCEPT_PROFILE", "")
            if defect.get("data_api_serves"):  # enabled and serving rows
                return reply("200 OK", b"[]")
            if defect.get("data_api_locked"):  # enabled, privileges revoked
                return reply("401 Unauthorized", b'{"code":"42501","message":"permission denied for table usuarios"}')
            if defect.get("data_api_merely_authenticated"):  # the key passed, a JWT error came back
                return reply("401 Unauthorized", b'{"code":"PGRST301","message":"JWSError"}')
            if defect.get("data_api"):  # enabled, public exposed, table not in the schema cache
                return reply("404 Not Found", b'{"code":"PGRST205","message":"Could not find the table"}')
            if defect.get("data_api_absent"):  # no PostgREST answer at all
                return reply("404 Not Found", b'{"message":"no route"}')
            if defect.get("data_api_other_schema"):  # public hidden, another schema serves rows
                return reply("406 Not Acceptable", b'{"code":"PGRST106","hint":"Only the following schemas are '
                             b'exposed: api, pgrst_no_exposed_schemas","message":"Invalid schema: public"}')
            if defect.get("data_api_old_message"):  # an older PostgREST wording: not proven on DEV
                return reply("406 Not Acceptable", b'{"code":"PGRST106","details":null,"hint":null,'
                             b'"message":"The schema must be one of the following: pgrst_no_exposed_schemas"}')
            if defect.get("data_api_toggle_only"):  # the toggle's own placeholder, without the override
                return reply("406 Not Acceptable", b'{"code":"PGRST106","details":null,"hint":"Only the following '
                             b'schemas are exposed: pg_pgrst_no_exposed_schemas","message":"Invalid schema: public"}')
            if defect.get("data_api_schema_cache"):  # the toggle alone, a PostgREST that cannot build its cache
                return reply("503 Service Unavailable", b'{"code":"PGRST002","details":null,"hint":null,'
                             b'"message":"Could not query the database for the schema cache. Retrying."}')
            placeholder = (b'"details":null,"hint":"Only the following schemas are exposed: pgrst_no_exposed_schemas",'
                           b'"message":"Invalid schema: public"')
            if defect.get("data_api_extra_detail"):  # the proven answer plus something not proven
                return reply("406 Not Acceptable", b'{"code":"PGRST106",' + placeholder + b',"extra":1}')
            if defect.get("data_api_wrong_status"):  # the placeholder body, but not a 406
                return reply("200 OK", b'{"code":"PGRST106",' + placeholder + b"}")
            if defect.get("data_api_no_code"):  # a 406 that is not PGRST106
                return reply("406 Not Acceptable", b"{" + placeholder + b"}")
            if defect.get("data_api_no_hint"):  # PGRST106 without the schema list: nothing to verify
                return reply("406 Not Acceptable", b'{"code":"PGRST106","message":"Invalid schema: public"}')
            if defect.get("data_api_refuses_valid_key"):  # a wrong or foreign key: refused like the bogus one
                return reply("401 Unauthorized", b'{"message":"Invalid API key"}')
            if defect.get("data_api_protection_page"):  # a protection page in front of the host
                return reply("403 Forbidden", b"<html>blocked</html>")
            if profile == "public":  # off: only an empty schema is exposed
                return reply("406 Not Acceptable", b"{\"code\":\"PGRST106\"," + placeholder + b"}")
            return reply("404 Not Found", b'{"code":"PGRST205","message":"not in pgrst_no_exposed_schemas"}')
        body = b"Traceback (most recent call last):\n File \"x.py\"" if defect.get("trace") else b"<h1>404</h1>"
        return reply("404 Not Found", body)

    return application


@pytest.fixture
def server():
    started = []

    def start(**defect):
        httpd = make_server("127.0.0.1", 0, _app(**defect), handler_class=_Quiet)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        started.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield start
    for httpd in started:
        httpd.shutdown()
        httpd.server_close()


def _failed(report):
    return {item["check"] for item in report["checks"] if not item["ok"]}


def _code(report, check):
    return {item["check"]: item["code"] for item in report["checks"]}[check]


def _data_api(server, key="pub-key-123", project=PROJECT, **state):
    return smoke.run(server(), allow_insecure=True, data_api_url=server(**state), publishable_key=key,
                     data_api_project_ref=project)


def _jwt(claims: dict) -> str:
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return part({"alg": "HS256", "typ": "JWT"}) + "." + part(claims) + ".c2lnbmF0dXJl"


def test_a_deployment_that_honours_the_contract_passes(server):
    report = _data_api(server)
    assert report["result"] == "PASS", report
    assert {item["check"] for item in report["checks"]} >= {
        "HEALTH", "LOGIN_PAGE", "COOKIE_FLAGS", "HEADERS", "ADMIN_REFUSED", "STATIC", "SCHEDULER",
        "NO_TRACEBACK", "DATA_API",
    }
    assert report["data_api_project_sha256"] == smoke.project_digest(PROJECT)


@pytest.mark.parametrize(
    "defect,check",
    [
        ({"health": True}, "HEALTH"),
        ({"health_body": True}, "HEALTH"),
        ({"cookie_no_secure": True}, "COOKIE_FLAGS"),
        ({"drop_headers": ("X-Frame-Options",)}, "HEADERS"),
        ({"drop_headers": ("Strict-Transport-Security",)}, "HEADERS"),
        ({"drop_headers": ("Content-Security-Policy",)}, "HEADERS"),
        ({"admin_open": True}, "ADMIN_REFUSED"),
        ({"admin_redirects_elsewhere": True}, "ADMIN_REFUSED"),
        ({"static": True}, "STATIC"),
        ({"scheduler_open": True}, "SCHEDULER"),
        ({"trace": True}, "NO_TRACEBACK"),
    ],
)
def test_each_named_defect_fails_its_own_check_and_only_that_check(server, defect, check):
    report = smoke.run(server(**defect), allow_insecure=True)
    assert report["result"] == "FAIL"
    assert _failed(report) == {check}


# ---- the data API proof -------------------------------------------------------------------------


@pytest.mark.parametrize("state,code", [
    ("data_api", "DATA_API_SERVES"),
    ("data_api_serves", "DATA_API_SERVES"),
    ("data_api_absent", "DATA_API_SERVES"),
    ("data_api_other_schema", "DATA_API_SERVES"),
    ("data_api_protection_page", "DATA_API_SERVES"),
    ("data_api_wrong_status", "DATA_API_SERVES"),
    ("data_api_no_code", "DATA_API_SERVES"),
    ("data_api_no_hint", "DATA_API_SERVES"),
    ("data_api_old_message", "DATA_API_SERVES"),
    ("data_api_toggle_only", "DATA_API_SERVES"),
    ("data_api_schema_cache", "DATA_API_SERVES"),
    ("data_api_extra_detail", "DATA_API_SERVES"),
    ("data_api_locked", "DATA_API_KEY_REFUSED"),
    ("data_api_merely_authenticated", "DATA_API_KEY_REFUSED"),
    ("data_api_refuses_valid_key", "DATA_API_KEY_REFUSED"),
])
def test_anything_but_the_placeholder_schema_answer_fails_the_check(server, state, code):
    """Rows, a missing table, revoked privileges, another exposed schema, a refused or merely
    authenticated key, an ambiguous answer, a protection page and any answer not proven on DEV (an
    older wording, the toggle's own placeholder, a schema-cache error, an extra field) are not proof."""
    report = _data_api(server, **{state: True})
    assert _code(report, "DATA_API") == code
    assert _failed(report) == {"DATA_API"}


# Verbatim from Supabase DEV (SPEC A15): the override in place, then reset (API on), then a key of the
# publishable shape that is not the project's.
DEV_OFF = (406, b'{"code":"PGRST106","details":null,"hint":"Only the following schemas are exposed: '
                b'pgrst_no_exposed_schemas","message":"Invalid schema: public"}')
DEV_ON = (404, b'{"code":"PGRST205","details":null,"hint":null,'
               b'"message":"Could not find the table \'public.usuarios\' in the schema cache"}')
DEV_FOREIGN_KEY = (401, b'{"hint":"Double check the provided API key for typos. This API key might also be owned by '
                        b'another Supabase project.","message":"Invalid API key"}')


def test_only_the_answer_proven_on_dev_is_accepted_whatever_its_key_order(server):
    assert smoke._data_api_off(*DEV_OFF) is True
    reordered = json.dumps(dict(reversed(list(json.loads(DEV_OFF[1]).items())))).encode()
    assert smoke._data_api_off(406, reordered) is True
    assert smoke._data_api_off(*DEV_ON) is False
    assert smoke._data_api_off(*DEV_FOREIGN_KEY) is False
    assert smoke._data_api_off(200, DEV_OFF[1]) is False
    assert smoke._data_api_off(406, b"<html>406</html>") is False
    assert _failed(_data_api(server)) == set()


def test_the_proof_is_bound_to_the_intended_project(server):
    assert _code(_data_api(server, project=None), "DATA_API") == "DATA_API_PROJECT_REQUIRED"
    assert _code(_data_api(server, project="otherproject1"), "DATA_API") == "DATA_API_WRONG_PROJECT"
    foreign = _jwt({"ref": "otherproject1", "role": "anon"})
    assert _code(_data_api(server, key=foreign, valid_key=foreign), "DATA_API") == "DATA_API_KEY_WRONG_PROJECT"
    service = _jwt({"ref": PROJECT, "role": "service_role"})
    assert _code(_data_api(server, key=service, valid_key=service), "DATA_API") == "DATA_API_KEY_WRONG_PROJECT"
    own = _jwt({"ref": PROJECT, "role": "anon"})
    assert _failed(_data_api(server, key=own, valid_key=own)) == set()


def test_open_means_an_application_serving_its_login_page_not_any_answer_without_the_header(server):
    assert smoke.probe_admission(server(), allow_insecure=True) == "open"
    assert smoke.probe_admission(server(login_missing=True), allow_insecure=True) == "unknown"


def test_the_opening_tag_and_the_public_host_are_read_for_the_ledger(server):
    tag = "AB" * 32
    assert smoke.probe_opening_tag(server(opening_tag=tag), allow_insecure=True) == tag.lower()
    assert smoke.probe_opening_tag(server(), allow_insecure=True) == ""
    assert smoke.host_digest("https://SGAA.Example.test:443/x") == smoke.host_digest("https://sgaa.example.test")
    assert smoke.host_digest("https://sgaa.example.test") != smoke.host_digest("https://other.example.test")
    base = server()
    assert smoke.run(base, allow_insecure=True)["public_host_sha256"] == smoke.host_digest(base)


def test_the_production_address_must_be_the_projects_own(monkeypatch):
    monkeypatch.setattr(smoke, "PROJECT_HOST_TEMPLATE", "{ref}.supabase.co")
    result = smoke.run("https://example.invalid", data_api_url="https://otherproject1.supabase.co",
                       publishable_key="pub-key-123", data_api_project_ref="intendedref1")
    assert _code(result, "DATA_API") == "DATA_API_WRONG_PROJECT"


def test_a_gateway_that_accepts_a_bogus_key_makes_the_answer_meaningless(server):
    """The control: the bogus key must be refused (401), or the valid-key answer proves nothing."""
    assert _code(_data_api(server, gateway_open=True), "DATA_API") == "DATA_API_CONTROL"


def test_the_data_api_check_proves_nothing_without_the_key_and_says_so(server):
    report = _data_api(server, key=None, data_api=True)
    assert _code(report, "DATA_API") == "DATA_API_KEY_REQUIRED"
    assert _failed(report) == {"DATA_API"}


# ---- admission ----------------------------------------------------------------------------------


def test_before_the_opening_the_operator_smoke_passes_and_strangers_are_refused(server):
    base = server(admission_closed=True)
    report = smoke.run(base, allow_insecure=True, operator_token=OPERATOR_TOKEN, admission="closed",
                       email="operator@example.test", password="x", data_api_url=server(),
                       publishable_key="pub-key-123", data_api_project_ref=PROJECT)
    assert report["result"] == "PASS", [(c["check"], c["code"]) for c in report["checks"] if not c["ok"]]
    assert SEEN_OPERATOR_HEADER_ON_DATA_API == []  # the operator credential never leaves the application
    stranger = smoke.run(base, allow_insecure=True)
    assert _failed(stranger) >= {"LOGIN_PAGE", "ADMIN_REFUSED"}


@pytest.mark.parametrize("defect,admission,code", [
    ({}, "closed", "ADMISSION_NOT_CLOSED"),                                       # an open deployment
    ({"admission_closed": True, "closed_sets_cookie": True}, "closed", "ADMISSION_NOT_CLOSED"),
    ({"admission_closed": True, "closed_admits_post": True}, "closed", "ADMISSION_NOT_CLOSED"),
    ({"admission_closed": True}, "open", "ADMISSION_NOT_OPEN"),                    # still closed at GO
])
def test_the_admission_check_fails_on_any_other_state(server, defect, admission, code):
    report = smoke.run(server(**defect), allow_insecure=True, operator_token=OPERATOR_TOKEN, admission=admission)
    assert _code(report, "ADMISSION") == code
    assert "ADMISSION" in _failed(report)


def test_the_probes_tell_closed_open_and_the_scheduler_front_apart(server):
    assert smoke.probe_admission(server(admission_closed=True), allow_insecure=True) == "closed"
    assert smoke.probe_admission(server(), allow_insecure=True) == "open"
    assert smoke.probe_admission(server(admission_closed=True, closed_admits_post=True), allow_insecure=True) == "unknown"
    assert smoke.probe_scheduler_front(server(scheduler_disabled=True), allow_insecure=True) == "disabled"
    assert smoke.probe_scheduler_front(server(), allow_insecure=True) == "enabled"
    assert smoke.probe_scheduler_front(server(scheduler_open=True), allow_insecure=True) == "unknown"


# ---- the rest ----------------------------------------------------------------------------------


def test_the_operator_sign_in_check_reads_an_endpoint_that_writes_nothing(server):
    report = smoke.run(server(), allow_insecure=True, email="operator@example.test", password="x")
    assert report["result"] == "PASS"
    assert any(item["check"] == "SIGN_IN" and item["ok"] for item in report["checks"])


def test_an_unreachable_deployment_fails_every_check_it_could_not_run():
    report = smoke.run("http://127.0.0.1:9", allow_insecure=True)
    assert report["result"] == "FAIL" and _failed(report) >= {"HEALTH", "LOGIN_PAGE"}
    by_name = {item["check"]: item["code"] for item in report["checks"]}
    assert by_name["HEALTH"] == by_name["LOGIN_PAGE"] == by_name["SCHEDULER"] == "UNREACHABLE"


def test_plain_http_is_refused_unless_explicitly_allowed_and_bad_addresses_are_refused():
    for url, code in (("http://example.test", "TLS_REQUIRED"), ("ftp://example.test", "BASE_URL_INVALID"),
                      ("https://user@example.test", "BASE_URL_INVALID"), ("https://example.test/path", "BASE_URL_INVALID")):
        err = io.StringIO()
        assert smoke.main(["--base-url", url, "--admission", "open"], out=io.StringIO(), err=err) == 1
        assert code in err.getvalue()


def test_c1_proves_the_data_api_off_alone_before_any_deployment_exists(server, monkeypatch):
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "pub-key-123")
    args = ["--data-api-only", "--allow-insecure", "--data-api-project-ref", PROJECT]
    out = io.StringIO()
    assert smoke.main(args + ["--data-api-url", server()], out=out, err=io.StringIO()) == 0
    report = json.loads(out.getvalue())
    assert [c["check"] for c in report["checks"]] == ["DATA_API"]
    assert report["data_api_project_sha256"] == smoke.project_digest(PROJECT)
    out = io.StringIO()
    assert smoke.main(args + ["--data-api-url", server(data_api=True)], out=out, err=io.StringIO()) == 1
    assert json.loads(out.getvalue())["checks"][0]["code"] == "DATA_API_SERVES"
    err = io.StringIO()
    assert smoke.main(["--data-api-only", "--data-api-url", server()], out=io.StringIO(), err=err) == 1
    assert "DATA_API_PROJECT_REQUIRED" in err.getvalue()
    assert smoke.main(args + ["--data-api-url", server(), "--base-url", server()],
                      out=io.StringIO(), err=io.StringIO()) == 2
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY")
    out = io.StringIO()
    assert smoke.main(args + ["--data-api-url", server()], out=out, err=io.StringIO()) == 1
    assert json.loads(out.getvalue())["checks"][0]["code"] == "DATA_API_KEY_REQUIRED"


def test_the_command_line_states_the_admission_and_never_takes_the_operator_credential_as_an_argument(
        server, monkeypatch):
    assert smoke.main(["--base-url", server()], out=io.StringIO(), err=io.StringIO()) == 2  # no --admission
    monkeypatch.delenv("SGAA_OPERATOR_TOKEN", raising=False)
    err = io.StringIO()
    assert smoke.main(["--base-url", server(), "--allow-insecure", "--admission", "closed"],
                      out=io.StringIO(), err=err) == 1
    assert "OPERATOR_TOKEN_REQUIRED" in err.getvalue()
    err = io.StringIO()
    assert smoke.main(["--base-url", server(), "--allow-insecure", "--admission", "open",
                       "--data-api-url", server()], out=io.StringIO(), err=err) == 1
    assert "DATA_API_PROJECT_REQUIRED" in err.getvalue()
    assert smoke.main(["--base-url", server(), "--admission", "open", "--operator-token", "x"],
                      out=io.StringIO(), err=io.StringIO()) == 2
    monkeypatch.setenv("SGAA_OPERATOR_TOKEN", OPERATOR_TOKEN)
    out = io.StringIO()
    assert smoke.main(["--base-url", server(admission_closed=True), "--allow-insecure", "--admission", "closed"],
                      out=out, err=io.StringIO()) == 0
    assert OPERATOR_TOKEN not in out.getvalue()


def test_output_names_neither_the_host_nor_any_body(server):
    base = server(trace=True)
    out = io.StringIO()
    code = smoke.main(["--base-url", base, "--allow-insecure", "--admission", "open"], out=out, err=io.StringIO())
    assert code == 1
    text = out.getvalue()
    assert "127.0.0.1" not in text and "Traceback" not in text and "tok123" not in text
    assert json.loads(text)["host_digest"]


def test_credentials_are_never_sent_over_plain_http(server):
    asked = []
    err = io.StringIO()
    code = smoke.main(["--base-url", server(), "--allow-insecure", "--admission", "open",
                       "--email", "operator@example.test"],
                      out=io.StringIO(), err=err, prompt=lambda text: asked.append(text) or "s3cret")
    assert code == 1 and asked == [] and "INSECURE_WITH_CREDENTIALS" in err.getvalue()


def test_the_password_is_asked_at_a_prompt_never_taken_as_an_argument(server, monkeypatch):
    asked = []
    out = io.StringIO()
    # The sign-in check refuses plain http; the scripted server is http, so exercise the prompt through run().
    monkeypatch.setattr(smoke, "run", lambda *a, **k: {"result": "PASS", "host_digest": "x", "checks": [],
                                                       "seen_password": k.get("password")})
    code = smoke.main(["--base-url", "https://example.test", "--admission", "open", "--email", "operator@example.test"],
                      out=out, err=io.StringIO(), prompt=lambda text: asked.append(text) or "s3cret")
    assert code == 0 and asked == ["Operator password: "]
    assert smoke.main(["--base-url", "https://x.test", "--admission", "open", "--password", "x"],
                      out=io.StringIO(), err=io.StringIO()) == 2
