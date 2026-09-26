"""Admin > Acesso "Senhas padrão" panel under the prod-1/v11 credential model.

Supersedes ``test_admin_access_default_passwords_enabled.py``: the global
"Ativar senhas padrão" switch is retired. What remains is:

* the panel is CONFIGURATION ONLY -- saving the five profile defaults writes
  ``configuracoes_acesso`` and never an account's hash or credential state;
* no switch is rendered, submitted, persisted or consulted;
* account credential transitions go through explicit actions only.
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import main

from app.security.passwords import check_password, hash_password
from app.user_accounts import (
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_with_access_level,
)
from tests.versioned_test_support import isolated_versioned_app_env


ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = "/admin/acesso/senhas-default"


class _FormTopologyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.nested = False
        self.forms: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag == "form":
            if self.depth:
                self.nested = True
            self.depth += 1
            self.forms.append({"action": values.get("action"), "inputs": []})
        elif tag == "input" and self.depth:
            self.forms[-1]["inputs"].append(values)

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.depth -= 1


def _login(client, user_id: int, level: str = "admin_total") -> None:
    with main.app.app_context():
        auth_version = int(
            main.get_db_connection().execute(
                "SELECT auth_version FROM usuario_credenciais WHERE usuario_id=?",
                (user_id,),
            ).fetchone()[0]
        )
    with client.session_transaction() as session:
        session.clear()
        session.update(
            user_id=user_id,
            user_type="admin",
            user_name="Default password panel test",
            access_level=level,
            auth_version=auth_version,
        )


def _admin_id() -> int:
    conn = main.get_db_connection()
    return int(
        conn.execute(
            "SELECT id FROM usuarios WHERE tipo='admin' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )


def _rows(conn, sql: str) -> list[tuple]:
    return [tuple(row) for row in conn.execute(sql).fetchall()]


def _access_defaults_digest(conn) -> str:
    rows = _rows(
        conn,
        "SELECT nivel_acesso,senha_padrao FROM configuracoes_acesso ORDER BY nivel_acesso",
    )
    return hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _target_form(html: str) -> dict[str, object]:
    parser = _FormTopologyParser()
    parser.feed(html)
    assert not parser.nested
    matches = [form for form in parser.forms if form["action"] == PANEL_PATH]
    assert len(matches) == 1
    return matches[0]


def _csrf_token_for_target_form(html: str) -> str:
    form = _target_form(html)
    tokens = [
        attrs.get("value")
        for attrs in form["inputs"]
        if attrs.get("name") == "csrf_token"
    ]
    assert len(tokens) == 1 and tokens[0]
    return str(tokens[0])


_DEFAULT_FIELDS = (
    "default_admin_total",
    "default_administrativo",
    "default_consultivo",
    "default_usuario",
    "default_usuario_teste",
)


def _panel_payload(html: str) -> dict[str, str]:
    """Submit the panel exactly as the browser would: every rendered value."""
    form = _target_form(html)
    values = {
        attrs["name"]: attrs.get("value", "")
        for attrs in form["inputs"]
        if attrs.get("name") in _DEFAULT_FIELDS
    }
    assert set(values) == set(_DEFAULT_FIELDS), values
    payload = dict(values)
    payload["csrf_token"] = _csrf_token_for_target_form(html)
    return payload


def _credential_snapshot(conn) -> tuple[list[tuple], list[tuple]]:
    return (
        _rows(conn, "SELECT id,senha FROM usuarios ORDER BY id"),
        _rows(
            conn,
            "SELECT usuario_id,estado,auth_version,atualizado_em,acesso_ativo"
            " FROM usuario_credenciais ORDER BY usuario_id",
        ),
    )


def _state(conn, user_id: int) -> str:
    return conn.execute(
        "SELECT estado FROM usuario_credenciais WHERE usuario_id=?", (user_id,)
    ).fetchone()[0]


# ------------------------------------------------------------ PANEL: NO SWITCH


def test_panel_renders_no_switch_and_one_save(tmp_path):
    with isolated_versioned_app_env(tmp_path, "panel-no-switch.db") as env:
        with main.app.app_context():
            admin_id = _admin_id()
        _login(env["client"], admin_id)
        html = env["client"].get("/admin/acesso").get_data(as_text=True)

        assert "Ativar senhas padrão" not in html
        assert "default_passwords_enabled" not in html
        assert "default-passwords-enabled" not in html
        assert "defaultPasswordsEnabled" not in html
        assert 'class="toggle-switch"' not in html

        # The header keeps the recovery status and nothing else interactive.
        head_start = html.find('class="access-defaults-head"')
        head_end = html.find('class="access-defaults-body"', head_start)
        header = html[head_start:head_end]
        assert "Recuperação por e-mail:" in header
        assert "<input" not in header
        assert "<label" not in header
        assert "<button" not in header

        # The five configured values and exactly one Save.
        start = html.find('<section class="access-defaults-panel">')
        panel = html[start: html.find("</section>", start)]
        buttons = re.findall(r"<button\b[^>]*type=\"submit\"[^>]*>(.*?)</button>", panel, re.S)
        labels = [" ".join(re.sub(r"<[^>]+>", "", raw).split()) for raw in buttons]
        assert labels == ["Salvar"], labels

        form = _target_form(html)
        names = {attrs.get("name") for attrs in form["inputs"]}
        assert names == {"csrf_token", *_DEFAULT_FIELDS}


def test_panel_leaves_no_dead_switch_css_or_js():
    source = (ROOT / "templates/admin_acesso.html").read_text(encoding="utf-8")
    for dead in (
        "access-defaults-toggle-form",
        "access-defaults-toggle-label",
        "default-passwords-enabled",
        "defaultPasswordsEnabled",
        "passwordHelpEditNoDefault",
        "passwordHelpCreateNoDefault",
        "levelLabels",
    ):
        assert dead not in source, dead


# ------------------------------------------------ SAVE IS CONFIGURATION ONLY


def test_saving_profile_defaults_rewrites_no_account(tmp_path):
    """The contract: the panel persists configuration and touches no credential."""
    with isolated_versioned_app_env(tmp_path, "panel-config-only.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            admin_id = _admin_id()
            applied = create_usuario_with_access_level(
                conn, "Applied", "applied@example.test", hash_password("consultivo123"),
                "admin", "consultivo", credential_state="default",
            ).lastrowid
            conn.commit()
            before = _credential_snapshot(conn)
            unrelated_settings = _rows(
                conn, "SELECT chave,valor,atualizado_em FROM configuracoes_app ORDER BY chave"
            )
        _login(env["client"], admin_id)

        custom = {
            "default_admin_total": "AdminCustom1",
            "default_administrativo": "CoordCustom2",
            "default_consultivo": "ConsultCustom3",
            "default_usuario": "AlunoCustom4",
            "default_usuario_teste": "TesteCustom5",
        }
        html = env["client"].get("/admin/acesso").get_data(as_text=True)
        payload = _panel_payload(html)
        payload.update(custom)
        # A stale client still posting the retired field is simply ignored.
        payload["default_passwords_enabled"] = "0"
        saved = env["client"].post(PANEL_PATH, data=payload, follow_redirects=False)
        assert saved.status_code in (302, 303)

        with main.app.app_context():
            conn = main.get_db_connection()
            stored = dict(
                _rows(conn, "SELECT nivel_acesso,senha_padrao FROM configuracoes_acesso")
            )
            assert {f"default_{level}": value for level, value in stored.items()} == custom
            # No hash, no state, no auth_version moved.
            assert _credential_snapshot(conn) == before
            # The applied account still holds the value applied at the time.
            senha = conn.execute("SELECT senha FROM usuarios WHERE id=?", (applied,)).fetchone()[0]
            assert check_password(senha, "consultivo123")
            assert not check_password(senha, "ConsultCustom3")
            # And the retired setting was not resurrected.
            assert _rows(
                conn, "SELECT chave,valor,atualizado_em FROM configuracoes_app ORDER BY chave"
            ) == unrelated_settings
            assert conn.execute(
                "SELECT COUNT(*) FROM configuracoes_app WHERE chave='default_passwords_enabled'"
            ).fetchone()[0] == 0


def test_saving_the_panel_code_path_reads_and_writes_no_switch():
    source = (ROOT / "app/views/admin/acesso.py").read_text(encoding="utf-8")
    body = source[source.index("def admin_acesso_salvar_senhas_default"):]
    body = body[: body.index("\n@admin_required")]
    assert "default_passwords_enabled" not in body
    assert "configuracoes_app" not in body
    assert "UPDATE usuarios" not in body
    assert "set_usuario" not in body


def test_default_passwords_mutation_requires_csrf(tmp_path):
    app = main.app
    original = app.config.get("WTF_CSRF_ENABLED")
    try:
        with isolated_versioned_app_env(tmp_path, "default-passwords-csrf.db") as env:
            app.config["WTF_CSRF_ENABLED"] = True
            with app.app_context():
                admin_id = _admin_id()
            _login(env["client"], admin_id)
            html = env["client"].get("/admin/acesso").get_data(as_text=True)

            missing = env["client"].post(PANEL_PATH, data={})
            assert missing.status_code == 400
            valid = env["client"].post(
                PANEL_PATH, data=_panel_payload(html), follow_redirects=False
            )
            assert valid.status_code in (302, 303)
    finally:
        app.config["WTF_CSRF_ENABLED"] = original


def test_insufficient_rbac_actor_cannot_mutate_default_passwords(tmp_path):
    with isolated_versioned_app_env(tmp_path, "default-passwords-rbac.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            cursor = create_usuario_with_access_level(
                conn,
                "Consultant",
                "consultant@example.test",
                hash_password("consultant-password"),
                "admin",
                "consultivo",
                credential_state=CREDENTIAL_STATE_PERSONAL,
            )
            actor_id = int(cursor.lastrowid)
            conn.commit()
            digest = _access_defaults_digest(conn)
        _login(env["client"], actor_id, "consultivo")

        response = env["client"].post(
            PANEL_PATH,
            data={field: "hijack" for field in _DEFAULT_FIELDS},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)
        assert "/admin/dashboard" in (response.headers.get("Location") or "")
        with main.app.app_context():
            assert _access_defaults_digest(main.get_db_connection()) == digest


# ------------------------------------------- EXPLICIT CREDENTIAL TRANSITIONS


def test_admin_access_password_actions_maintain_credential_state(tmp_path):
    """blank create -> pending; Nova -> personal; Aplicar -> default; edit -> personal."""
    with isolated_versioned_app_env(tmp_path, "access-password-states.db") as env:
        with main.app.app_context():
            admin_id = _admin_id()
        _login(env["client"], admin_id)

        create = env["client"].post(
            "/admin/acesso/salvar",
            data={
                "nome": "Credential state user",
                "email": "credential-state@example.test",
                "nivel_acesso": "consultivo",
                "senha": "",
            },
            follow_redirects=False,
        )
        assert create.status_code in (302, 303)
        with main.app.app_context():
            conn = main.get_db_connection()
            user_id = int(
                conn.execute(
                    "SELECT id FROM usuarios WHERE email='credential-state@example.test'"
                ).fetchone()[0]
            )
            assert _state(conn, user_id) == "pending"
            senha = conn.execute("SELECT senha FROM usuarios WHERE id=?", (user_id,)).fetchone()[0]
            # Never the shared default, not even as an unused hash.
            assert not check_password(senha, "consultivo123")

        bulk = env["client"].post(
            "/admin/acesso/definir-senha",
            data={"usuario_ids": [str(user_id)], "nova_senha": "personal-password"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert bulk.status_code == 200
        with main.app.app_context():
            assert _state(main.get_db_connection(), user_id) == "personal"

        reset = env["client"].post(
            f"/admin/acesso/{user_id}/resetar-senha", follow_redirects=False
        )
        assert reset.status_code in (302, 303)
        with main.app.app_context():
            assert _state(main.get_db_connection(), user_id) == "default"

        edit = env["client"].post(
            "/admin/acesso/salvar",
            data={
                "usuario_id": str(user_id),
                "nome": "Credential state user",
                "email": "credential-state@example.test",
                "nivel_acesso": "consultivo",
                "senha": "another-personal-password",
            },
            follow_redirects=False,
        )
        assert edit.status_code in (302, 303)
        with main.app.app_context():
            assert _state(main.get_db_connection(), user_id) == "personal"


def test_explicit_password_equal_to_current_default_is_personal_and_apply_is_explicit(
    tmp_path,
):
    """Typing the default's text is an individual password; Aplicar is the opt-in."""
    with isolated_versioned_app_env(tmp_path, "explicit-default-value.db") as env:
        with main.app.app_context():
            admin_id = _admin_id()
        _login(env["client"], admin_id)
        created = env["client"].post(
            "/admin/acesso/salvar",
            data={
                "nome": "Explicit default value",
                "email": "explicit-default@example.test",
                "nivel_acesso": "consultivo",
                "senha": "consultivo123",
            },
            follow_redirects=False,
        )
        assert created.status_code in (302, 303)
        with main.app.app_context():
            conn = main.get_db_connection()
            row = conn.execute(
                """
                SELECT u.id,u.senha,c.estado,c.auth_version
                  FROM usuarios u
                  JOIN usuario_credenciais c ON c.usuario_id=u.id
                 WHERE u.email='explicit-default@example.test'
                """
            ).fetchone()
            user_id = int(row["id"])
            assert row["estado"] == "personal"
            before = (row["senha"], int(row["auth_version"]))

        applied = env["client"].post(
            f"/admin/acesso/{user_id}/resetar-senha", follow_redirects=False
        )
        assert applied.status_code in (302, 303)
        with main.app.app_context():
            after = main.get_db_connection().execute(
                """
                SELECT u.senha,c.estado,c.auth_version
                  FROM usuarios u
                  JOIN usuario_credenciais c ON c.usuario_id=u.id
                 WHERE u.id=?
                """,
                (user_id,),
            ).fetchone()
        assert after["estado"] == "default"
        assert int(after["auth_version"]) == before[1] + 1
        assert after["senha"] != before[0]


def test_retired_activation_endpoint_is_gone():
    """No mutation endpoint for the retired switch survives anywhere."""
    rules = {str(rule.rule) for rule in main.app.url_map.iter_rules()}
    assert "/admin/acesso/ativar-senhas-padrao" not in rules
    assert "admin_acesso_salvar_ativacao_senhas_padrao" not in main.app.view_functions
    source = (ROOT / "app/views/admin/acesso.py").read_text(encoding="utf-8")
    assert "admin_acesso_salvar_ativacao_senhas_padrao" not in source
    assert "default_passwords_enabled" not in source


def test_toggle_design_system_contract_is_shared_without_page_local_clones():
    """The DS toggle survives the Acesso switch's removal for its other consumers."""
    css = (ROOT / "static/css/components/form.css").read_text(encoding="utf-8")
    assert "--toggle-switch-width:42px" in css
    assert "--toggle-switch-height:22px" in css
    assert ".toggle-switch--large" in css
    assert "--toggle-switch-width:46px" in css
    assert "--toggle-switch-height:24px" in css
    assert ".toggle-switch input:checked + .toggle-switch-slider" in css
    assert ".toggle-switch input:focus-visible + .toggle-switch-slider" in css
    assert ".toggle-switch input:disabled" in css
    assert "var(--focus-ring-color)" in css

    consumers = {
        "templates/admin_alertas.html": "toggle-switch toggle-switch--large",
        "templates/admin_arquivos.html": "toggle-switch toggle-switch--large",
        "templates/admin_banco_dados.html": "toggle-switch",
        "templates/admin_configuracoes.html": "toggle-switch",
    }
    for relative, class_value in consumers.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert f'class="{class_value}"' in source
        assert re.search(r"(?m)^\s*\.toggle-switch\s*\{", source) is None
        assert re.search(r"(?m)^\s*\.toggle-switch-slider\s*\{", source) is None
    acesso = (ROOT / "templates/admin_acesso.html").read_text(encoding="utf-8")
    assert "toggle-switch" not in acesso


# ------------------------------------------------ PANEL SURFACE (DS)


def _page_rule(source: str, selector: str) -> dict[str, str]:
    """Declarations of the base (first, non-media) page-local rule for ``selector``."""
    matches = re.findall(rf"(?m)^\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", source)
    assert matches, selector
    declarations: dict[str, str] = {}
    for chunk in matches[0].split(";"):
        if ":" in chunk:
            prop, value = chunk.split(":", 1)
            declarations[prop.strip()] = value.strip()
    return declarations


def test_defaults_panel_is_one_standard_white_surface():
    """Border and header/footer dividers follow the DS panel pattern
    (``1px solid var(--border-strong)``, as ``.content-block`` and the summary
    cards). Header, body and footer no longer paint the rejected translucent
    ``--bg-underpanel`` over the gray page; the outer panel owns the shared
    ``--surface`` token and the three regions inherit it."""
    source = (ROOT / "templates/admin_acesso.html").read_text(encoding="utf-8")
    tokens = (ROOT / "static/css/foundation/tokens.css").read_text(encoding="utf-8")
    assert re.search(r"--surface:\s*#ffffff\s*;", tokens)

    panel = _page_rule(source, ".access-defaults-panel")
    assert panel["background"] == "var(--surface)"
    # Geometry of the outer block is untouched.
    assert panel["border"] == "1px solid var(--border-strong)"
    assert panel["border-radius"] == "var(--radius)"
    assert panel["overflow"] == "hidden"
    assert panel["margin-bottom"] == "18px"

    expected_regions = {
        ".access-defaults-head": {
            "display": "flex", "align-items": "center",
            "justify-content": "space-between", "gap": "14px", "padding": "7px 16px",
        },
        ".access-defaults-body": {
            "padding": "16px", "border-top": "1px solid var(--border-strong)",
        },
        ".access-defaults-footer": {
            "display": "flex", "justify-content": "flex-end",
            "padding": "11px 16px", "border-top": "1px solid var(--border-strong)",
        },
    }
    for selector, expected in expected_regions.items():
        declarations = _page_rule(source, selector)
        assert declarations == expected, (selector, declarations)
        assert not any(prop.startswith("background") for prop in declarations), selector
        assert re.search(
            rf"{re.escape(selector)}[^{{]*\{{[^}}]*background", source
        ) is None, selector

    # Outer border and both dividers use the DS panel border, not a raw
    # translucent black hairline.
    region_rules = [
        line for line in source.splitlines()
        if re.match(r"\s*\.access-defaults-(panel|head|body|footer)\s*\{", line)
    ]
    assert region_rules
    assert not any("rgba(0,0,0,0.08)" in line for line in region_rules)

    # No raw white introduced for the panel surface, and the rejected token is
    # gone from this block.
    panel_css = "\n".join(
        line for line in source.splitlines() if ".access-defaults-" in line
    )
    assert "--bg-underpanel" not in panel_css
    assert re.search(r"(?i)background\s*:\s*(white|#fff\b|#ffffff\b|rgb|hsl)", panel_css) is None


def test_defaults_panel_markup_is_unchanged_by_the_surface_cleanup():
    source = (ROOT / "templates/admin_acesso.html").read_text(encoding="utf-8")
    start = source.index('<section class="access-defaults-panel">')
    panel = source[start: source.index("</section>", start)]
    order = [
        panel.index('<form method="post" action="{{ url_for(\'admin_acesso_salvar_senhas_default\') }}">'),
        panel.index('<div class="access-defaults-head">'),
        panel.index('<div class="access-defaults-body">'),
        panel.index('<div class="access-defaults-grid">'),
        panel.index('<div class="access-defaults-footer">'),
    ]
    assert order == sorted(order)
    assert panel.count('<div class="access-default-card">') == 5
    assert panel.count('class="pw-wrapper"') == 5
    assert "Recuperação por e-mail:" in panel
    assert panel.count('<button class="btn primary btn--raised" type="submit">') == 1
    assert "style=" not in panel
