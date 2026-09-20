from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import main

from app.security.passwords import hash_password
from app.user_accounts import (
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_with_access_level,
)
from tests.versioned_test_support import isolated_versioned_app_env


ROOT = Path(__file__).resolve().parents[1]
# One settings surface, one Save: the activation switch is persisted by the
# same panel form that owns the five configured default passwords.
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
            user_name="Password foundation test",
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


def _panel_payload(html: str, *, enabled: bool) -> dict[str, str]:
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
    # Mirror the real form: the hidden "0" always rides along, and the checkbox
    # adds "1" only when it is checked.
    payload["default_passwords_enabled"] = ["0", "1"] if enabled else ["0"]
    return payload


def _post_panel(client, *, enabled: bool):
    html = client.get("/admin/acesso").get_data(as_text=True)
    return client.post(
        PANEL_PATH, data=_panel_payload(html, enabled=enabled), follow_redirects=False
    )


def test_default_passwords_toggle_is_independent_and_preserves_all_protected_data(tmp_path):
    with isolated_versioned_app_env(tmp_path, "default-passwords-isolation.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            admin_id = _admin_id()
            access_rows = _rows(
                conn,
                "SELECT nivel_acesso,senha_padrao FROM configuracoes_acesso ORDER BY nivel_acesso",
            )
            assert len(access_rows) == 5
            access_digest = _access_defaults_digest(conn)
            passwords = _rows(conn, "SELECT id,senha FROM usuarios ORDER BY id")
            credentials = _rows(
                conn,
                "SELECT usuario_id,estado,auth_version,atualizado_em FROM usuario_credenciais ORDER BY usuario_id",
            )
            unrelated_settings = _rows(
                conn,
                "SELECT chave,valor,atualizado_em FROM configuracoes_app "
                "WHERE chave<>'default_passwords_enabled' ORDER BY chave",
            )
            assert conn.execute(
                "SELECT valor FROM configuracoes_app WHERE chave='default_passwords_enabled'"
            ).fetchone()[0] == "1"

        _login(env["client"], admin_id)
        off = _post_panel(env["client"], enabled=False)
        assert off.status_code in (302, 303)
        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute(
                "SELECT valor FROM configuracoes_app WHERE chave='default_passwords_enabled'"
            ).fetchone()[0] == "0"
            assert _access_defaults_digest(conn) == access_digest
            assert _rows(conn, "SELECT id,senha FROM usuarios ORDER BY id") == passwords
            assert _rows(
                conn,
                "SELECT usuario_id,estado,auth_version,atualizado_em FROM usuario_credenciais ORDER BY usuario_id",
            ) == credentials
            assert _rows(
                conn,
                "SELECT chave,valor,atualizado_em FROM configuracoes_app "
                "WHERE chave<>'default_passwords_enabled' ORDER BY chave",
            ) == unrelated_settings

        on = _post_panel(env["client"], enabled=True)
        assert on.status_code in (302, 303)
        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute(
                "SELECT valor FROM configuracoes_app WHERE chave='default_passwords_enabled'"
            ).fetchone()[0] == "1"
            assert _access_defaults_digest(conn) == access_digest
            assert _rows(conn, "SELECT id,senha FROM usuarios ORDER BY id") == passwords
            assert _rows(
                conn,
                "SELECT usuario_id,estado,auth_version,atualizado_em FROM usuario_credenciais ORDER BY usuario_id",
            ) == credentials
            assert _rows(
                conn,
                "SELECT chave,valor,atualizado_em FROM configuracoes_app "
                "WHERE chave<>'default_passwords_enabled' ORDER BY chave",
            ) == unrelated_settings


def test_default_passwords_render_state_accessibility_and_form_topology(tmp_path):
    with isolated_versioned_app_env(tmp_path, "default-passwords-render.db") as env:
        with main.app.app_context():
            admin_id = _admin_id()
        _login(env["client"], admin_id)

        html_on = env["client"].get("/admin/acesso").get_data(as_text=True)
        form = _target_form(html_on)
        checkbox = next(
            attrs
            for attrs in form["inputs"]
            if attrs.get("name") == "default_passwords_enabled"
            and attrs.get("type") == "checkbox"
        )
        assert checkbox.get("type") == "checkbox"
        assert "checked" in checkbox
        assert "Ativar senhas padrão" in html_on
        assert 'class="toggle-switch"' in html_on
        assert 'aria-labelledby="default-passwords-enabled-label"' in html_on
        assert 'class="toggle-switch-slider"' in html_on

        _post_panel(env["client"], enabled=False)
        html_off = env["client"].get("/admin/acesso").get_data(as_text=True)
        off_checkbox = next(
            attrs
            for attrs in _target_form(html_off)["inputs"]
            if attrs.get("name") == "default_passwords_enabled"
            and attrs.get("type") == "checkbox"
        )
        assert "checked" not in off_checkbox


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
            token = _csrf_token_for_target_form(html)

            missing = env["client"].post(PANEL_PATH, data={})
            assert missing.status_code == 400
            payload = _panel_payload(html, enabled=True)
            payload["csrf_token"] = token
            valid = env["client"].post(
                PANEL_PATH, data=payload, follow_redirects=False
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
        _login(env["client"], actor_id, "consultivo")

        response = env["client"].post(PANEL_PATH, data={}, follow_redirects=False)
        assert response.status_code in (302, 303)
        assert "/admin/dashboard" in (response.headers.get("Location") or "")
        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT valor FROM configuracoes_app WHERE chave='default_passwords_enabled'"
            ).fetchone()[0] == "1"


def test_admin_access_password_actions_maintain_credential_state(tmp_path):
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
            assert conn.execute(
                "SELECT estado FROM usuario_credenciais WHERE usuario_id=?", (user_id,)
            ).fetchone()[0] == "default"

        bulk = env["client"].post(
            "/admin/acesso/definir-senha",
            data={"usuario_ids": [str(user_id)], "nova_senha": "personal-password"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert bulk.status_code == 200
        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT estado FROM usuario_credenciais WHERE usuario_id=?", (user_id,)
            ).fetchone()[0] == "personal"

        reset = env["client"].post(
            f"/admin/acesso/{user_id}/resetar-senha", follow_redirects=False
        )
        assert reset.status_code in (302, 303)
        with main.app.app_context():
            assert main.get_db_connection().execute(
                "SELECT estado FROM usuario_credenciais WHERE usuario_id=?", (user_id,)
            ).fetchone()[0] == "default"

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
            assert main.get_db_connection().execute(
                "SELECT estado FROM usuario_credenciais WHERE usuario_id=?", (user_id,)
            ).fetchone()[0] == "personal"


def test_explicit_password_equal_to_current_default_is_personal_and_apply_is_blocked_when_off(
    tmp_path,
):
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

        _post_panel(env["client"], enabled=False)
        denied = env["client"].post(
            f"/admin/acesso/{user_id}/resetar-senha", follow_redirects=False
        )
        assert denied.status_code in (302, 303)
        with main.app.app_context():
            conn = main.get_db_connection()
            after = conn.execute(
                """
                SELECT u.senha,c.estado,c.auth_version
                  FROM usuarios u
                  JOIN usuario_credenciais c ON c.usuario_id=u.id
                 WHERE u.id=?
                """,
                (user_id,),
            ).fetchone()
            assert (after["senha"], int(after["auth_version"])) == before
            assert after["estado"] == "personal"

def test_toggle_design_system_contract_is_shared_without_page_local_clones():
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
        "templates/admin_acesso.html": "toggle-switch",
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


def _visible_save_buttons(html: str) -> list[str]:
    """Labels of submit buttons rendered inside the Senhas padrão panel."""
    start = html.find('<section class="access-defaults-panel">')
    assert start != -1, "Senhas padrão panel not rendered"
    end = html.find("</section>", start)
    panel = html[start:end]
    buttons = re.findall(r"<button\b[^>]*type=\"submit\"[^>]*>(.*?)</button>", panel, re.S)
    labels = []
    for raw in buttons:
        text = re.sub(r"<[^>]+>", "", raw)
        labels.append(" ".join(text.split()))
    return labels


def test_password_panel_has_exactly_one_save_labelled_salvar(tmp_path):
    with isolated_versioned_app_env(tmp_path, "panel-single-save.db") as env:
        with main.app.app_context():
            admin_id = _admin_id()
        _login(env["client"], admin_id)
        html = env["client"].get("/admin/acesso").get_data(as_text=True)

        labels = _visible_save_buttons(html)
        assert labels == ["Salvar"], labels

        # The header carries the state pill and the switch, and no Save.
        head_start = html.find('class="access-defaults-head"')
        head_end = html.find('class="access-defaults-body"', head_start)
        header = html[head_start:head_end]
        assert "Recuperação por e-mail:" in header
        assert "Ativar senhas padrão" in header
        assert 'class="toggle-switch"' in header
        assert "<button" not in header.replace('type="button"', "")

        # One form owns the whole panel and nothing is nested.
        parser = _FormTopologyParser()
        parser.feed(html)
        assert not parser.nested
        panel_forms = [form for form in parser.forms if form["action"] == PANEL_PATH]
        assert len(panel_forms) == 1
        names = {attrs.get("name") for attrs in panel_forms[0]["inputs"]}
        assert {"default_passwords_enabled", "csrf_token", *_DEFAULT_FIELDS} <= names


def test_panel_save_persists_switch_and_values_and_off_on_preserves_defaults(tmp_path):
    with isolated_versioned_app_env(tmp_path, "panel-unified-save.db") as env:
        with main.app.app_context():
            admin_id = _admin_id()
        _login(env["client"], admin_id)

        custom = {
            "default_admin_total": "AdminCustom1",
            "default_administrativo": "CoordCustom2",
            "default_consultivo": "ConsultCustom3",
            "default_usuario": "AlunoCustom4",
            "default_usuario_teste": "TesteCustom5",
        }
        html = env["client"].get("/admin/acesso").get_data(as_text=True)
        payload = _panel_payload(html, enabled=True)
        payload.update(custom)
        saved = env["client"].post(PANEL_PATH, data=payload, follow_redirects=False)
        assert saved.status_code in (302, 303)

        with main.app.app_context():
            conn = main.get_db_connection()
            stored = dict(
                _rows(conn, "SELECT nivel_acesso,senha_padrao FROM configuracoes_acesso")
            )
            passwords = _rows(conn, "SELECT id,senha FROM usuarios ORDER BY id")
            digest = _access_defaults_digest(conn)
            assert stored["admin_total"] == "AdminCustom1"
            assert stored["usuario_teste"] == "TesteCustom5"
            assert conn.execute(
                "SELECT valor FROM configuracoes_app WHERE chave='default_passwords_enabled'"
            ).fetchone()[0] == "1"

        # OFF must not clear, blank, regenerate or rehash anything.
        assert _post_panel(env["client"], enabled=False).status_code in (302, 303)
        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute(
                "SELECT valor FROM configuracoes_app WHERE chave='default_passwords_enabled'"
            ).fetchone()[0] == "0"
            assert _access_defaults_digest(conn) == digest
            assert _rows(conn, "SELECT id,senha FROM usuarios ORDER BY id") == passwords

        # While OFF the values still render, so turning ON reuses them exactly.
        off_html = env["client"].get("/admin/acesso").get_data(as_text=True)
        off_values = {
            attrs["name"]: attrs.get("value")
            for attrs in _target_form(off_html)["inputs"]
            if attrs.get("name") in _DEFAULT_FIELDS
        }
        assert off_values == custom

        assert _post_panel(env["client"], enabled=True).status_code in (302, 303)
        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute(
                "SELECT valor FROM configuracoes_app WHERE chave='default_passwords_enabled'"
            ).fetchone()[0] == "1"
            assert _access_defaults_digest(conn) == digest
            assert _rows(conn, "SELECT id,senha FROM usuarios ORDER BY id") == passwords


def test_retired_activation_endpoint_is_gone():
    """The redundant second mutation endpoint must not survive anywhere."""
    rules = {str(rule.rule) for rule in main.app.url_map.iter_rules()}
    assert "/admin/acesso/ativar-senhas-padrao" not in rules
    assert "admin_acesso_salvar_ativacao_senhas_padrao" not in main.app.view_functions
    source = (ROOT / "app/views/admin/acesso.py").read_text(encoding="utf-8")
    assert "admin_acesso_salvar_ativacao_senhas_padrao" not in source


def test_password_only_save_never_silently_disables_the_mechanism(tmp_path):
    """A POST that does not mention the switch must leave it untouched.

    The panel always submits the field (hidden "0" + checkbox "1"), so an
    unchecked box is an explicit off.  Any other caller saving only the five
    configured values must not flip a security-relevant setting by omission.
    """
    with isolated_versioned_app_env(tmp_path, "panel-partial-post.db") as env:
        with main.app.app_context():
            admin_id = _admin_id()
        _login(env["client"], admin_id)

        def switch():
            with main.app.app_context():
                return main.get_db_connection().execute(
                    "SELECT valor FROM configuracoes_app WHERE chave='default_passwords_enabled'"
                ).fetchone()[0]

        assert switch() == "1"

        # Field absent entirely -> unchanged.
        html = env["client"].get("/admin/acesso").get_data(as_text=True)
        payload = _panel_payload(html, enabled=False)
        payload.pop("default_passwords_enabled", None)
        assert env["client"].post(
            PANEL_PATH, data=payload, follow_redirects=False
        ).status_code in (302, 303)
        assert switch() == "1", "omitting the field must not disable default passwords"

        # Explicit "0" (what the unchecked panel actually sends) -> off.
        payload["default_passwords_enabled"] = "0"
        env["client"].post(PANEL_PATH, data=payload, follow_redirects=False)
        assert switch() == "0"

        # Absent again while off -> still off, not silently re-enabled.
        payload.pop("default_passwords_enabled")
        env["client"].post(PANEL_PATH, data=payload, follow_redirects=False)
        assert switch() == "0"


def test_panel_pairs_the_switch_with_a_hidden_zero():
    source = (ROOT / "templates/admin_acesso.html").read_text(encoding="utf-8")
    hidden = '<input type="hidden" name="default_passwords_enabled" value="0">'
    checkbox = 'id="default-passwords-enabled" name="default_passwords_enabled" type="checkbox" value="1"'
    assert hidden in source
    assert checkbox in source
    assert source.index(hidden) < source.index(checkbox), "hidden default must precede the checkbox"
