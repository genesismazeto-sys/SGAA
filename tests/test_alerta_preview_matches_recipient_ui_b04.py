"""UI-B04 -- the alert preview must show what the recipient sees.

Reported: the "Visualizacao" box in Admin > Alertas showed the alert's
administrative *Titulo* glued to the message, while the real alert delivered to
the student shows the message alone. The preview therefore advertised an output
the product never produces.

Cause (client-side only): ``updatePreview()`` in templates/admin_alertas.html
built the preview string from BOTH fields --

    const previewParts = [];
    if (titulo) previewParts.push(titulo);
    if (message) previewParts.push(message);
    previewText.textContent = previewParts.join(' - ') || ...

-- and ``tituloInput`` was wired to it with an ``input`` listener.

The recipient renderer (templates/aluno_dashboard.html, ``.aluno-alerta-card``)
was already correct and is NOT touched: it binds ``alerta.mensagem`` only, in
the visible span, the ``title`` attribute and the ``aria-label``.

Fix: the preview reads ``mensagemInput`` only. "Titulo" stays administrative
metadata -- still the list column, still an identification field in the
create/edit modal.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main  # noqa: E402
from tests.session_support import stamp_auth_version  # noqa: E402

ROOT = Path(BASE)
ADMIN_ALERTAS = ROOT / "templates" / "admin_alertas.html"
ALUNO_DASHBOARD = ROOT / "templates" / "aluno_dashboard.html"

# Deliberately disjoint strings: neither is a substring of the other, so a leak
# cannot hide behind a shared token.
TITULO = "IDENTIFICADOR INTERNO XYZ"
MENSAGEM = "Mensagem visivel ao usuario ABC"
MENSAGEM_ACENTUADA = "Mensagem visível ao usuário ABC"


@pytest.fixture(scope="module")
def client():
    with main.app.app_context():
        main.init_db()
    with main.app.test_client() as test_client:
        yield test_client


@pytest.fixture(scope="module")
def alerta_id():
    with main.app.app_context():
        conn = main.get_db_connection()
        main.ensure_admin_alertas_table(conn)
        conn.execute("DELETE FROM admin_alertas WHERE titulo = ?", (TITULO,))
        cursor = conn.execute(
            "INSERT INTO admin_alertas (titulo, mensagem, bg_color, border_color, visivel)"
            " VALUES (?, ?, ?, ?, 1)",
            (TITULO, MENSAGEM_ACENTUADA, "#e3eefd", "#7e95b2"),
        )
        conn.commit()
        new_id = cursor.lastrowid
    yield new_id
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM admin_alertas WHERE id = ?", (new_id,))
        conn.commit()


@pytest.fixture(scope="module")
def alertas_html(client, alerta_id):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"
        sess["access_level"] = "admin_total"
        stamp_auth_version(sess)
    response = client.get("/admin/alertas")
    assert response.status_code == 200, response.status_code
    return response.get_data(as_text=True)


def _update_preview_body(html: str) -> str:
    match = re.search(r"function updatePreview\(\)\{(.*?)\n    \}", html, re.S)
    assert match, "updatePreview() is gone or was restructured"
    return match.group(1)


def _preview_markup(html: str) -> str:
    match = re.search(
        r'<div class="alerta-preview".*?</div>', html, re.S
    )
    assert match, "the .alerta-preview box is gone or was restructured"
    return match.group(0)


# ---------------------------------------------------------------------------
# Administrative surfaces keep the internal title
# ---------------------------------------------------------------------------


def test_admin_list_still_identifies_the_alert_by_its_title(alertas_html):
    """Titulo is management metadata: the list column must keep showing it."""
    assert TITULO in alertas_html, "admin list lost the alert's identifying title"
    assert (
        f'<div class="cell left alerta-cell-message">{TITULO}</div>' in alertas_html
    ), "the admin list title cell was restructured"
    assert f'data-alerta-titulo="{TITULO}"' in alertas_html, (
        "the row must keep carrying the title so the edit modal can prefill it"
    )


def test_edit_modal_keeps_the_title_identification_field(alertas_html):
    """Create/edit still owns a real Titulo input -- storage is untouched."""
    assert '<label class="alerta-row-label" for="admin-alerta-titulo">Titulo</label>' in alertas_html
    assert 'id="admin-alerta-titulo" name="titulo"' in alertas_html, (
        "the titulo field must keep posting under its own name"
    )


# ---------------------------------------------------------------------------
# The preview shows the recipient's output only
# ---------------------------------------------------------------------------


def test_preview_never_renders_the_internal_title(alertas_html):
    """No seeded title reaches the preview box, server-side or as a default."""
    preview = _preview_markup(alertas_html)
    assert TITULO not in preview, f"internal title leaked into the preview: {preview}"


def test_preview_text_is_built_from_the_message_alone(alertas_html):
    """The only field feeding previewText is mensagemInput."""
    body = _update_preview_body(alertas_html)
    assert "mensagemInput" in body, "the preview stopped reading the message"
    assert "tituloInput" not in body, (
        f"updatePreview still reads the internal title: {body}"
    )
    assert "previewParts" not in body, (
        "the title/message concatenation must be gone, not merely reordered"
    )
    assert "' - '" not in body and '" - "' not in body, (
        "the ' - ' title/message separator must be gone"
    )


def test_title_input_is_no_longer_wired_to_the_preview(alertas_html):
    """Typing a title must not repaint the preview at all."""
    listeners = re.findall(
        r"(\w+)\?\.addEventListener\('input', updatePreview\)", alertas_html
    )
    assert listeners == ["mensagemInput"], (
        f"only the message may drive the preview, got {listeners}"
    )


def test_preview_empty_state_is_not_a_title_stand_in(alertas_html):
    """The removed title is not replaced by a heading, label or placeholder."""
    preview = _preview_markup(alertas_html)
    span = re.search(r'<span id="alerta-preview-text">(.*?)</span>', preview, re.S)
    assert span, "the preview text span is gone"
    empty_state = span.group(1).strip()
    assert empty_state == "Digite a mensagem do alerta", empty_state

    body = _update_preview_body(alertas_html)
    assert "Digite o titulo do alerta" not in body, (
        "the preview empty state must not point the admin at the title field"
    )

    # No heading/label element was introduced where the title used to sit.
    assert not re.search(r"<h[1-6]\b", preview), (
        f"the preview must not grow a heading: {preview}"
    )
    inner_spans = re.findall(r"<span\b[^>]*>", preview)
    assert len(inner_spans) == 1, (
        f"exactly one text node belongs in the preview, got {inner_spans}"
    )
    assert "><" in re.sub(r"\s+", "", preview), "sanity: preview markup is contiguous"


def test_preview_does_not_expose_the_title_through_aria(alertas_html):
    """No accessible-name relationship may resurface the internal title."""
    preview = _preview_markup(alertas_html)
    assert "aria-label" not in preview, preview
    assert "aria-labelledby" not in preview, preview
    # Nothing anywhere points at the preview text node, so removing the title
    # from it cannot have broken a reference.
    assert "alerta-preview-text" not in re.sub(
        r'<span id="alerta-preview-text">', "", alertas_html
    ).replace("getElementById('alerta-preview-text')", ""), (
        "an ARIA/label reference to the preview text node appeared"
    )


# ---------------------------------------------------------------------------
# The real recipient alert -- already correct, asserted so it stays that way
# ---------------------------------------------------------------------------


def _recipient_block() -> str:
    """The `alertas_ativos` stack as declared in aluno_dashboard.html.

    Anchored on `{% endfor %}</div>{% endif %}` so the inner
    `{% if alerta_href %}` does not truncate the block.
    """
    source = ALUNO_DASHBOARD.read_text(encoding="utf-8-sig")
    match = re.search(
        r"\{% if alertas_ativos %\}.*?\{% endfor %\}\s*</div>\s*\{% endif %\}",
        source,
        re.S,
    )
    assert match, "the aluno alert stack block is gone or was restructured"
    return match.group(0)


def _render_recipient_card(alerta: dict) -> str:
    """Render the student alert card exactly as aluno_dashboard.html declares it."""
    with main.app.app_context():
        template = main.app.jinja_env.from_string(_recipient_block())
        return template.render(alertas_ativos=[alerta])


def test_recipient_alert_shows_the_message_and_not_the_title():
    html = _render_recipient_card(
        {
            "titulo": TITULO,
            "mensagem": MENSAGEM_ACENTUADA,
            "bg_color": "#e3eefd",
            "border_color": "#7e95b2",
        }
    )
    assert MENSAGEM_ACENTUADA in html, html
    assert TITULO not in html, f"the internal title reached the student: {html}"


def test_recipient_accessible_name_is_the_message():
    html = _render_recipient_card(
        {
            "titulo": TITULO,
            "mensagem": MENSAGEM_ACENTUADA,
            "bg_color": "#e3eefd",
            "border_color": "#7e95b2",
            "href": "/aluno/requisicoes",
        }
    )
    assert f'aria-label="{MENSAGEM_ACENTUADA}"' in html, html
    assert f'title="{MENSAGEM_ACENTUADA}"' in html, html
    assert TITULO not in html, f"the internal title reached the student: {html}"


def test_recipient_template_binds_the_message_only():
    """Structural control: the card must never learn to read alerta.titulo."""
    block = _recipient_block()
    assert "alerta.mensagem" in block, "the recipient card stopped binding the message"
    assert "alerta.titulo" not in block, (
        "the recipient card must not bind the administrative title"
    )
