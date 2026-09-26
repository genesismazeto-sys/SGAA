# coding: utf-8
"""UI-B15: console / CSP / form semantics on Admin > Acesso.

The user reported five browser console messages on ``/admin/acesso``. The
inventory that preceded this file found that they are **not five defects**:

======================  ==================================================
Console message         What it actually is
======================  ==================================================
use.typekit.net fonts   NOT SGAA's. The repository references Adobe /
refused by ``font-src``  Typekit nowhere, and the rendered page asks for
                        exactly two font origins, both already allowed. The
                        directive is working. Pinned by
                        ``test_no_external_font_provider_is_referenced`` and
                        ``test_font_src_does_not_gain_typekit``.
----------------------  --------------------------------------------------
unpkg source map        A DevTools-only fetch of the ``sourceMappingURL``
refused by              comment at the end of the CDN Lucide bundle. A
``connect-src``         source map is never a runtime dependency, so the
                        cure is the asset, never the policy: SGAA now
                        serves a pinned Lucide from ``'self'`` with that
                        comment removed, and ``script-src`` LOST
                        ``https://unpkg.com`` as a result.
----------------------  --------------------------------------------------
"Multiple forms ..."    A password-manager heuristic, not malformed HTML.
on senhas-default       Proven here: the page's forms are siblings, closed,
                        and each control belongs to its own endpoint. See
                        the FORM OWNERSHIP lane.
----------------------  --------------------------------------------------
access-email has no     A real gap. The field is the login identity, so it
autocomplete            now declares ``username``.
----------------------  --------------------------------------------------
password form has no    A real gap. The dialog now carries a hidden,
username                readonly, name-less identity field.
======================  ==================================================

The CSP lane is written as a ratchet in BOTH directions: it pins what the
policy must keep allowing *and* asserts that the specific origins this task
was tempted to add were not added.

Every database-backed test uses a disposable database; the canonical database
is never written.
"""

from __future__ import annotations

import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

import main
from app.root_admin import resolve_root_admin_id
from tests.versioned_test_support import isolated_versioned_app_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACESSO_TEMPLATE = PROJECT_ROOT / "templates" / "admin_acesso.html"
BASE_TEMPLATE = PROJECT_ROOT / "templates" / "base.html"
BASE_ALUNO_TEMPLATE = PROJECT_ROOT / "templates" / "base_aluno.html"
ERROR_400_TEMPLATE = PROJECT_ROOT / "templates" / "400.html"
VENDORED_LUCIDE = PROJECT_ROOT / "static" / "vendor" / "lucide.min.js"
PINNED_LUCIDE = PROJECT_ROOT / "tests" / "visual" / "vendor" / "lucide.min.js"

#: Every template that loads the icon library.
ICON_HOST_TEMPLATES = (BASE_TEMPLATE, BASE_ALUNO_TEMPLATE, ERROR_400_TEMPLATE)

#: The only two external font origins SGAA is allowed to depend on: the Google
#: Fonts stylesheet and the files it points at. Anything else on this page is
#: not ours.
ALLOWED_EXTERNAL_HOSTS = frozenset(
    {
        "fonts.googleapis.com",  # the Inter stylesheet
        "fonts.gstatic.com",  # the font files that stylesheet references
        "www.w3.org",  # SVG xmlns, never fetched
    }
)

#: Origins that would have made the console quiet by weakening the policy.
#: None of them may appear anywhere in the CSP.
FORBIDDEN_CSP_ORIGINS = (
    "typekit",
    "unpkg",
    "use.typekit.net",
    "p.typekit.net",
)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def acesso_render():
    """``/admin/acesso`` as the root administrator actually receives it."""
    with tempfile.TemporaryDirectory() as tmp:
        with isolated_versioned_app_env(Path(tmp), "ui-b15.db") as env:
            client = env["client"]
            with main.app.app_context():
                conn = main.get_db_connection()
                admin_id = resolve_root_admin_id(conn)
                assert admin_id is not None, "isolated database has no root admin"
                auth_version = int(
                    conn.execute(
                        "SELECT auth_version FROM usuario_credenciais"
                        " WHERE usuario_id=?",
                        (admin_id,),
                    ).fetchone()[0]
                )
            with client.session_transaction() as session:
                session.clear()
                session.update(
                    user_id=admin_id,
                    user_type="admin",
                    user_name="UI-B15",
                    access_level="admin_total",
                    auth_version=auth_version,
                )
            response = client.get("/admin/acesso")
            assert response.status_code == 200
            yield {
                "html": response.get_data(as_text=True),
                "csp": response.headers.get("Content-Security-Policy", ""),
            }


def _csp_directive(csp: str, name: str) -> list[str]:
    for chunk in csp.split(";"):
        parts = chunk.strip().split()
        if parts and parts[0] == name:
            return parts[1:]
    raise AssertionError(f"CSP has no {name!r} directive: {csp!r}")


# --------------------------------------------------------------------------- #
# CSP — the policy must stay restrictive
# --------------------------------------------------------------------------- #


def test_font_src_does_not_gain_typekit(acesso_render):
    """The refused Typekit request is not ours, so the cure is never the CSP."""
    font_src = _csp_directive(acesso_render["csp"], "font-src")
    assert font_src == ["'self'", "data:", "https://fonts.gstatic.com"], font_src


def test_connect_src_does_not_gain_unpkg_for_a_source_map(acesso_render):
    """A blocked source map is a DevTools inconvenience, not a dependency."""
    connect_src = _csp_directive(acesso_render["csp"], "connect-src")
    assert connect_src == [
        "'self'",
        "https://www.googleapis.com",
        "https://oauth2.googleapis.com",
        "https://accounts.google.com",
    ], connect_src


def test_script_src_no_longer_allows_the_cdn(acesso_render):
    """Self-hosting Lucide let the policy get *narrower*, which is the point."""
    script_src = _csp_directive(acesso_render["csp"], "script-src")
    assert "https://unpkg.com" not in script_src, script_src
    # The Google origins are load-bearing (Picker / OAuth) and must survive.
    assert "https://apis.google.com" in script_src
    assert "https://accounts.google.com" in script_src


@pytest.mark.parametrize("origin", FORBIDDEN_CSP_ORIGINS)
def test_no_convenience_origin_anywhere_in_the_policy(acesso_render, origin):
    assert origin not in acesso_render["csp"].lower()


def test_no_wildcard_source_in_the_policy(acesso_render):
    """``font-src *`` / ``connect-src *`` / bare ``https:`` are forbidden."""
    for chunk in acesso_render["csp"].split(";"):
        sources = chunk.strip().split()[1:]
        assert "*" not in sources, chunk
        assert "https:" not in sources, chunk
        assert not any(s.startswith("*.") for s in sources), chunk


# --------------------------------------------------------------------------- #
# Typekit — the request chain, traced to its absence
# --------------------------------------------------------------------------- #


def test_no_external_font_provider_is_referenced_anywhere(acesso_render):
    """Every external host the rendered page names, enumerated.

    If a Typekit (or any other) font provider ever enters SGAA -- through a
    template, a stylesheet, an ``@import``, an ``@font-face`` or a vendored
    library -- it lands in this set and this test is the first thing to fail.
    """
    hosts = set(re.findall(r"https?://([A-Za-z0-9.\-]+)", acesso_render["html"]))
    assert hosts <= ALLOWED_EXTERNAL_HOSTS, sorted(hosts - ALLOWED_EXTERNAL_HOSTS)


def test_no_render_surface_references_a_typekit_origin():
    """Source-level companion: the chain a font request could come from.

    ``templates/`` and ``static/`` are the only places that can make a browser
    fetch a font -- a ``<link>``, an ``@import``, an ``@font-face`` or a
    library that injects one. Python cannot. The CSP's own freedom from
    ``typekit`` is asserted separately, against the served header, because
    ``app/__init__.py`` legitimately *names* the origin in the comment that
    explains why it is refused.
    """
    suffixes = {".html", ".css", ".js"}
    offenders = []
    for root in ("templates", "static"):
        for path in (PROJECT_ROOT / root).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if "typekit" in path.read_text(encoding="utf-8", errors="ignore").lower():
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == []


def test_no_served_css_or_js_asset_declares_a_typekit_dependency(acesso_render):
    """The source-side proof, taken from the *served* bytes.

    The console keeps reporting blocked Typekit font requests after the
    repair. Scanning files answers "is it written down"; this answers the
    stronger question "does anything SGAA actually serves ask for it". Every
    stylesheet and script the page links is fetched through the app and
    searched -- including the vendored Lucide and XLSX bundles, which are the
    only third-party code in the response.

    Nothing here can see a browser extension, which is why final attribution
    needs an incognito / extensions-disabled recheck. See §UI-B15.
    """
    html = acesso_render["html"]
    assets = set(re.findall(r'(?:href|src)="(/static/[^"]+\.(?:css|js))', html))
    assert len(assets) >= 6, sorted(assets)

    with tempfile.TemporaryDirectory() as tmp:
        with isolated_versioned_app_env(Path(tmp), "ui-b15-assets.db") as env:
            for asset in sorted(assets):
                response = env["client"].get(asset.split("?")[0])
                assert response.status_code == 200, asset
                body = response.get_data(as_text=True).lower()
                assert "typekit" not in body, asset
                # No asset may declare any other remote font provider either.
                for host in re.findall(r"https?://([a-z0-9.\-]+)", body):
                    assert host in ALLOWED_EXTERNAL_HOSTS or host.endswith(
                        ("unpkg.com", "lucide.dev", "github.com")
                    ), (asset, host)


def test_font_authority_is_the_design_system_token():
    """No second font family was introduced to make the console quiet."""
    tokens = (PROJECT_ROOT / "static" / "css" / "foundation" / "tokens.css").read_text(
        encoding="utf-8"
    )
    assert "--font-sans:'Inter'" in tokens.replace(" ", "")
    # Controls do not inherit font-family from ancestors, so the shared .btn
    # contract restores it (UI-B06). That is the single authority; this repair
    # must not have added another.
    modern = (PROJECT_ROOT / "static" / "css" / "modern-style.css").read_text(
        encoding="utf-8"
    )
    assert "font-family:inherit" in modern


# --------------------------------------------------------------------------- #
# Lucide — self-hosted, pinned, no remote source map
# --------------------------------------------------------------------------- #


def test_vendored_lucide_carries_no_source_mapping_url():
    """The exact line that made DevTools fetch the map from the CDN origin."""
    assert VENDORED_LUCIDE.is_file(), VENDORED_LUCIDE
    assert "sourceMappingURL" not in VENDORED_LUCIDE.read_text(encoding="utf-8")


def test_vendored_lucide_is_the_pinned_build_the_baseline_renders():
    """Self-hosting must not change which icons exist.

    The served file is the visual baseline's pinned bundle plus an SGAA
    provenance header, minus the source-map comment. Comparing the library
    body proves no icon drifted.
    """
    served = VENDORED_LUCIDE.read_text(encoding="utf-8")
    pinned = PINNED_LUCIDE.read_text(encoding="utf-8")
    pinned_body = pinned.replace("//# sourceMappingURL=lucide.min.js.map", "").strip()
    assert pinned_body and pinned_body in served
    assert "@license lucide" in served, "the library's own licence banner is required"


#: Any ``<script src=...>`` pointing at a host, i.e. a real remote dependency
#: rather than a comment that merely names one.
_REMOTE_SCRIPT_RE = re.compile(r"<script[^>]*\bsrc\s*=\s*[\"']https?://([^/\"']+)")


def _icon_registry() -> set[str]:
    """The PascalCase keys of the pinned bundle's ``icons`` object.

    This is the exact set ``lucide.createIcons()`` resolves a ``data-lucide``
    name against: it PascalCases the attribute and looks it up here. Parsed
    straight out of the shipped file -- ``a.icons=<var>`` then
    ``<var>=Object.freeze({...})`` -- so the test cannot drift from what the
    browser actually loads, and needs no Node runtime.
    """
    js = VENDORED_LUCIDE.read_text(encoding="utf-8")
    var = re.search(r"a\.icons=([A-Za-z0-9_$]+)", js).group(1)
    opening = f"{var}=Object.freeze({{"
    start = js.index(opening) + len(opening)
    body = js[start : js.index("})", start)]
    return set(re.findall(r"(?:^|,)([A-Za-z][A-Za-z0-9]*):", body))


def _pascal(icon_name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in icon_name.split("-"))


def test_the_pinned_registry_parses_and_is_plausibly_complete():
    """Guards the parser above: a broken regex must not silently pass."""
    registry = _icon_registry()
    assert len(registry) > 1500, len(registry)
    for known in ("Crown", "ShieldCheck", "KeyRound", "Database", "Trash2"):
        assert known in registry, known


def test_every_icon_rendered_on_acesso_exists_in_the_pinned_bundle(acesso_render):
    """The browser proved this lane was needed: "cloud-backup" was not found.

    Covers both the icons in the markup and the ones the page's own script
    injects (the floating action bar, the modal title swap), because a missing
    name in either place is the same silent blank in the UI.
    """
    html = acesso_render["html"]
    static_names = set(re.findall(r'data-lucide="([^"{}]+)"', html))
    scripted_names = set(re.findall(r"data-lucide=\\?[\"']([a-z0-9-]+)", html))
    names = {n for n in static_names | scripted_names if n}
    assert len(names) > 30, "the audit must actually see the page's icons"

    registry = _icon_registry()
    missing = sorted(n for n in names if _pascal(n) not in registry)
    assert missing == [], missing


def test_cloud_backup_is_gone_and_its_replacement_is_real():
    """The specific name the console reported, and the one that replaced it."""
    registry = _icon_registry()
    assert "CloudBackup" not in registry, "still not a Lucide icon"
    assert "DatabaseBackup" in registry

    for template in (BASE_TEMPLATE, BASE_ALUNO_TEMPLATE, ERROR_400_TEMPLATE):
        text = template.read_text(encoding="utf-8")
        assert 'data-lucide="cloud-backup"' not in text, template.name


def test_no_template_anywhere_renders_an_unknown_icon_name():
    """One silently blank icon was enough; sweep the whole template tree."""
    registry = _icon_registry()
    offenders: list[tuple[str, str]] = []
    for path in (PROJECT_ROOT / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for name in re.findall(r'data-lucide="([^"{}]+)"', text):
            if _pascal(name) not in registry:
                offenders.append((str(path.relative_to(PROJECT_ROOT)), name))
    assert offenders == [], offenders


def test_lucide_runtime_is_still_wired(acesso_render):
    """Icons still load and still get created; behaviour is untouched."""
    html = acesso_render["html"]
    assert "/static/vendor/lucide.min.js" in html
    assert _REMOTE_SCRIPT_RE.findall(html) == [], "no script is loaded remotely"
    assert "data-lucide=" in html


@pytest.mark.parametrize(
    "template", ICON_HOST_TEMPLATES, ids=lambda p: p.name
)
def test_no_template_loads_lucide_from_the_cdn(template):
    """script-src dropped unpkg, so a straggler would be a blocked script."""
    text = template.read_text(encoding="utf-8")
    assert _REMOTE_SCRIPT_RE.findall(text) == []
    assert "vendor/lucide.min.js" in text


# --------------------------------------------------------------------------- #
# FORM OWNERSHIP — the rendered DOM, not the template
# --------------------------------------------------------------------------- #


class _FormAudit(HTMLParser):
    """Records form nesting, form ownership and every control's owner."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.max_depth = 0
        #: Indices into ``self.forms``. A form's ``id`` is NOT usable as the
        #: key: the senhas-default form legitimately has none, and an empty
        #: string is indistinguishable from "no owner".
        self.stack: list[int] = []
        self.forms: list[dict] = []
        self.unmatched_close = 0
        #: (tag, attrs, owning form index or None, explicit form= attribute)
        self.controls: list[tuple[str, dict, int | None, str | None]] = []

    def handle_starttag(self, tag, attrs):
        attributes = {k: (v if v is not None else "") for k, v in attrs}
        if tag == "form":
            self.forms.append(
                {
                    "id": attributes.get("id", ""),
                    "action": attributes.get("action", ""),
                    "method": (attributes.get("method", "") or "").lower(),
                    "nested_in": self.stack[-1] if self.stack else None,
                    "controls": [],
                }
            )
            self.stack.append(len(self.forms) - 1)
            self.max_depth = max(self.max_depth, len(self.stack))
            return
        if tag in {"input", "select", "textarea", "button"}:
            owner = self.stack[-1] if self.stack else None
            self.controls.append((tag, attributes, owner, attributes.get("form")))
            if owner is not None:
                self.forms[owner]["controls"].append((tag, attributes))

    def handle_endtag(self, tag):
        if tag != "form":
            return
        if not self.stack:
            self.unmatched_close += 1
            return
        self.stack.pop()


@pytest.fixture(scope="module")
def audit(acesso_render) -> _FormAudit:
    parser = _FormAudit()
    parser.feed(acesso_render["html"])
    return parser


def test_no_nested_forms_and_no_malformed_closing_tags(audit):
    """The first thing the brief asks about the "multiple forms" warning.

    Chrome's parser drops a nested ``<form>`` and reparents its controls, which
    is a genuine ownership defect. This page has none: forms are siblings, the
    nesting depth never exceeds one, and every open tag is matched.
    """
    assert audit.max_depth == 1, audit.max_depth
    assert audit.stack == [], "a <form> was never closed"
    assert audit.unmatched_close == 0, "stray </form>"
    assert [f["nested_in"] for f in audit.forms] == [None] * len(audit.forms)


def test_each_independent_action_keeps_one_form_one_endpoint_one_method(audit):
    """Endpoint, method and CSRF survive the repair, per form."""
    by_action = {f["action"]: f for f in audit.forms}
    assert set(by_action) == {
        "/admin/acesso/senhas-default",
        "/admin/acesso/salvar",
        "/admin/acesso/definir-senha",
    }, sorted(by_action)
    for action, form in by_action.items():
        assert form["method"] == "post", (action, form["method"])
        names = [a.get("name") for _tag, a in form["controls"]]
        assert "csrf_token" in names, f"{action} lost its CSRF token"


def test_no_control_is_orphaned_or_pointed_at_a_missing_form(audit):
    """Buttons outside their form must declare ownership explicitly.

    The two modal Save buttons sit in ``.modal-footer``, outside the ``<form>``
    they submit, and bind to it with the HTML ``form=`` attribute. That is
    valid, explicit ownership -- the opposite of the accidental kind the
    warning is about -- but only while the id it names exists.
    """
    form_ids = {f["id"] for f in audit.forms if f["id"]}
    for tag, attributes, owner, explicit in audit.controls:
        if explicit is not None:
            assert explicit in form_ids, (tag, explicit)
            # `form=` is only meaningful from outside; inside it must agree.
            assert owner is None or audit.forms[owner]["id"] == explicit, (
                tag,
                owner,
                explicit,
            )

    submits = [
        (a.get("form"), owner)
        for tag, a, owner, _e in audit.controls
        if tag == "button" and a.get("type") == "submit"
    ]
    assert submits, "the page has submit buttons"
    for explicit, owner in submits:
        assert explicit is not None or owner is not None, "submit owns no form"


def test_the_defaults_panel_is_one_action_and_stays_one_action(audit):
    """The warning must not be "fixed" by splitting the single Save.

    Five password values are persisted by one POST (the activation switch was
    retired in prod-1/v11).
    Breaking them into five forms would satisfy Chrome's heuristic and break
    the panel, so the contract is pinned in the opposite direction.
    """
    defaults = next(
        f for f in audit.forms if f["action"] == "/admin/acesso/senhas-default"
    )
    passwords = [
        a for tag, a in defaults["controls"]
        if tag == "input" and a.get("type") == "password"
    ]
    assert len(passwords) == 5, [a.get("name") for a in passwords]
    names = [a.get("name") for _t, a in defaults["controls"]]
    # prod-1/v11 retired the global switch: the panel carries values only.
    assert "default_passwords_enabled" not in names
    submits = [
        a for tag, a in defaults["controls"]
        if tag == "button" and a.get("type") == "submit"
    ]
    assert len(submits) == 1, "the panel has exactly one Save"


# --------------------------------------------------------------------------- #
# AUTOCOMPLETE SEMANTICS
# --------------------------------------------------------------------------- #


def _control(audit: _FormAudit, element_id: str) -> dict:
    for _tag, attributes, _owner, _explicit in audit.controls:
        if attributes.get("id") == element_id:
            return attributes
    raise AssertionError(f"no control with id={element_id!r}")


def test_access_email_declares_the_account_identity(audit):
    """It is the login identity (``usuarios.email``, used by ``/login``)."""
    email = _control(audit, "access-email")
    assert email["type"] == "email"
    assert email["name"] == "email"
    assert email.get("autocomplete") == "username"
    assert "required" in email


def test_access_email_was_not_silenced_with_off(audit):
    """``off`` would quiet the warning by misdescribing the field."""
    assert _control(audit, "access-email").get("autocomplete") != "off"


def test_create_edit_password_is_a_credential_being_set(audit):
    """Admin assigns a password; it never autofills an existing one."""
    assert _control(audit, "access-password").get("autocomplete") == "new-password"


def test_password_dialog_password_is_a_credential_being_replaced(audit):
    assert (
        _control(audit, "access-password-new-value").get("autocomplete")
        == "new-password"
    )


def test_default_password_fields_are_configuration_secrets_not_credentials(audit):
    """``off``, and the browser is why.

    These five are the default password of a PROFILE -- Admin, Coordenador,
    Consultor, Usuário, Usuário teste. A profile is not a login identity and
    has no account, so the form has no username and cannot be given one.

    A first pass set them to ``new-password`` to try to stop Chrome's
    heuristic from splitting the form. Real console output disproved it twice
    over: the "Multiple forms" line survived, and ``new-password`` asserted
    these were *account password-change* fields, which made Chrome start
    demanding a username field for the one form on the page that can never
    have one. ``off`` is the accurate token for a configuration secret: do not
    autofill it, do not offer to manage it.
    """
    defaults = next(
        f for f in audit.forms if f["action"] == "/admin/acesso/senhas-default"
    )
    fields = [
        a for tag, a in defaults["controls"]
        if tag == "input" and a.get("type") == "password"
    ]
    assert len(fields) == 5
    for attributes in fields:
        assert attributes.get("autocomplete") == "off", attributes.get("name")


def test_the_defaults_panel_has_no_username_and_must_not_gain_one(audit):
    """No fake identity for Admin / Coordenador / Consultor / Usuário."""
    defaults = next(
        f for f in audit.forms if f["action"] == "/admin/acesso/senhas-default"
    )
    identities = [
        a for _tag, a in defaults["controls"]
        if a.get("autocomplete") == "username"
    ]
    assert identities == [], "a profile is not a login identity"


def test_default_password_fields_stay_masked(audit):
    """Not turned into text inputs to hide them from Chrome's parser."""
    defaults = next(
        f for f in audit.forms if f["action"] == "/admin/acesso/senhas-default"
    )
    masked = [
        a.get("name") for tag, a in defaults["controls"]
        if tag == "input" and (a.get("name") or "").startswith("default_")
    ]
    assert len(masked) == 5
    for tag, attributes in defaults["controls"]:
        if (attributes.get("name") or "").startswith("default_"):
            assert attributes.get("type") == "password", attributes["name"]


def test_password_dialog_carries_a_username_identity(audit):
    """Chrome asks a password form for an "(optionally hidden) username".

    REGRESSION GUARD, and it is the point of this test. The first attempt used
    the HTML ``hidden`` attribute and the browser kept warning: ``hidden``
    means ``display:none``, the element is never rendered, and a field the
    layout does not produce cannot be associated by the password manager.
    "Optionally hidden" means visually hidden, not removed. Anything that
    takes the element out of rendering -- ``hidden``, ``type="hidden"``,
    ``display:none``, ``visibility:hidden`` -- must fail here.
    """
    identity = _control(audit, "access-password-username")
    assert identity.get("autocomplete") == "username"
    assert identity.get("type") == "email"
    assert "hidden" not in identity, "the `hidden` attribute is what failed"
    assert identity.get("type") != "hidden"
    assert "sr-only" in (identity.get("class") or "").split()
    style = identity.get("style") or ""
    assert "display:none" not in style.replace(" ", "")
    assert "visibility:hidden" not in style.replace(" ", "")
    assert "readonly" in identity, "the admin does not edit the account identity"
    assert identity.get("tabindex") == "-1", "must not enter the dialog tab order"


def test_the_sr_only_primitive_keeps_the_field_rendered():
    """``.sr-only`` must hide visually without removing it from the layout."""
    css = (PROJECT_ROOT / "static" / "css" / "modern-style.css").read_text(
        encoding="utf-8"
    )
    block = css.split(".sr-only{", 1)[1].split("}", 1)[0].replace(" ", "")
    assert "display:none" not in block
    assert "visibility:hidden" not in block
    assert "position:absolute" in block
    assert "clip:rect(0,0,0,0)" in block


def test_the_identity_is_not_visibly_duplicated_in_the_modal(audit):
    """Exactly one identity field in the dialog, and it is the hidden one."""
    password_form = next(
        f for f in audit.forms if f["id"] == "access-password-form"
    )
    identities = [
        a for _tag, a in password_form["controls"]
        if a.get("autocomplete") == "username"
    ]
    assert len(identities) == 1
    assert identities[0].get("id") == "access-password-username"


def test_the_username_identity_lives_inside_the_password_form(audit):
    password_form = next(
        f for f in audit.forms if f["id"] == "access-password-form"
    )
    ids = [a.get("id") for _t, a in password_form["controls"]]
    assert "access-password-username" in ids


def test_the_username_identity_can_never_reach_the_endpoint(audit):
    """It is a browser hint. A ``name`` would make it a request field."""
    identity = _control(audit, "access-password-username")
    assert "name" not in identity, identity


def test_the_username_identity_is_never_invented(audit):
    """Its value comes from the selected row, and only when there is one."""
    template = ACESSO_TEMPLATE.read_text(encoding="utf-8")
    assert "passwordUsername" in template
    # A bulk selection has no single identity and must not borrow one.
    assert re.search(
        r"passwordUsername\.value\s*=\s*selectedRows\.length === 1\s*"
        r"\?\s*\(selectedRows\[0\]\.getAttribute\('data-user-email'\)[^)]*\)\s*"
        r":\s*''",
        template,
    ), "the identity must be the single selected row's e-mail, or nothing"
    # It is rendered empty; only JS fills it.
    assert _control(audit, "access-password-username").get("value") == ""


def test_bulk_selection_declares_no_identity():
    """Several accounts, no unique username: the field stays empty.

    The alternative -- naming one of N accounts being changed -- would be a
    false statement to the password manager and to the administrator. The
    visible ``#access-password-selection-count`` already says how many are
    affected, so nothing is lost by declining to name one.
    """
    template = ACESSO_TEMPLATE.read_text(encoding="utf-8")
    branch = template.split("passwordUsername.value =", 1)[1].split(";", 1)[0]
    assert "selectedRows.length === 1" in branch
    assert branch.rstrip().endswith("''"), branch


def test_no_stale_identity_survives_close_or_a_selection_change():
    """Cleared on close AND when the selection moves underneath the dialog."""
    template = ACESSO_TEMPLATE.read_text(encoding="utf-8")
    close_body = template.split("function closePasswordModal()", 1)[1].split(
        "\n    }", 1
    )[0]
    assert "passwordUsername.value = ''" in close_body

    selection_body = template.split("onSelectionChange:", 1)[1].split("}", 1)[0]
    assert "passwordUsername.value = ''" in selection_body


def test_password_dialog_still_posts_the_selection_not_the_identity():
    """The real request body is unchanged: ``usuario_ids`` + ``nova_senha``."""
    template = ACESSO_TEMPLATE.read_text(encoding="utf-8")
    assert "body.append('usuario_ids'" in template
    assert "body.set('nova_senha', novaSenha)" in template
    assert "body.set('csrf_token', csrfToken)" in template


def test_the_endpoint_reads_only_the_two_fields_it_owns():
    """Why a name-less identity is safe even if it ever grew a name.

    ``admin_acesso_definir_senha`` consumes exactly ``usuario_ids`` and
    ``nova_senha``; every other posted field is ignored and cannot reach the
    credential mutation.
    """
    source = (PROJECT_ROOT / "app" / "views" / "admin" / "acesso.py").read_text(
        encoding="utf-8"
    )
    body = source.split("def admin_acesso_definir_senha():", 1)[1].split(
        "\n@", 1
    )[0]
    read = set(re.findall(r"request\.form\.(?:get|getlist)\(\"([^\"]+)\"", body))
    assert read == {"usuario_ids", "nova_senha"}, read
