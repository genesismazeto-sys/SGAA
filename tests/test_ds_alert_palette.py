"""The Design System's one alert palette: tokens.css --alert-* (the owner's Alertas colours).

Every message box takes its background and border from the palette and its
text from --alert-text, whatever the tone: the Alertas cards, the .flash
toasts, the auth alert (tests/test_auth_feedback_alerts.py covers its tones),
the diagnostic page's error box and the e-mail warnings in Requisições. The
Alertas presets and the automatic yellow alert are data that must equal the
tokens. Destructive actions, invalid fields and status badges are not alerts
and keep their own families. DS README §2.1 (the alert palette).
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _source(relative):
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def _rule(source, selector):
    match = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert match, selector
    return match.group(1).replace(" ", "").replace("\n", "")


def _alert_tokens():
    tokens = _source("static/css/foundation/tokens.css")
    return {name: value.lower() for name, value in re.findall(r"--(alert-[\w-]+)\s*:\s*([^;]+);", tokens)}


def test_the_alert_palette_has_one_owner_and_every_copy_matches_it():
    """tokens.css --alert-* is the system's one alert palette (the owner's Alertas colours)."""
    from app.requisitions import AUTO_ALERT_YELLOW_BG, AUTO_ALERT_YELLOW_BORDER
    from app.views.admin.alertas import ALERTA_COLOR_OPTIONS

    tokens = _alert_tokens()
    names = {"Azul": "blue", "Amarelo": "yellow", "Verde": "green", "Laranja": "orange",
             "Vermelho": "red", "Roxo": "purple", "Ciano": "cyan"}
    # Every preset an administrator can pick is a token, value for value, and nothing more.
    assert {option["label"] for option in ALERTA_COLOR_OPTIONS} == set(names)
    for option in ALERTA_COLOR_OPTIONS:
        colour = names[option["label"]]
        assert option["bg"].lower() == tokens[f"alert-{colour}-bg"], option["label"]
        assert option["border"].lower() == tokens[f"alert-{colour}-border"], option["label"]
    assert len(tokens) == 2 * len(names) + 1  # seven pairs and --alert-text
    assert (AUTO_ALERT_YELLOW_BG.lower(), AUTO_ALERT_YELLOW_BORDER.lower()) == (
        tokens["alert-yellow-bg"], tokens["alert-yellow-border"])
    # The Alertas cards, the auth alert and the flash toasts share --alert-text.
    assert tokens["alert-text"] == "#0f172a"
    for page, selector in (("templates/aluno_dashboard.html", ".aluno-alerta-card"),
                           ("templates/admin_dashboard.html", ".admin-alerta-card")):
        body = re.search(r"(?m)^\s*" + re.escape(selector) + r"\{([^}]*)\}", _source(page)).group(1)
        assert "color:var(--alert-text)" in body.replace(" ", ""), page


def test_the_flash_toasts_use_the_alert_palette():
    modern = _source("static/css/modern-style.css")
    flash = re.search(r"(?m)^\.flash\{([^}]*)\}", modern).group(1).replace(" ", "")
    assert "color:var(--alert-text)" in flash
    # .flash-error shares the .flash-danger rule (grouped selector).
    assert re.search(r"(?m)^\.flash\.flash-error,\s*\n\.flash\.flash-danger\s*\{", modern)
    for category, colour in (("danger", "red"), ("success", "green"), ("warning", "yellow"), ("info", "blue")):
        body = re.search(r"(?m)^\.flash\.flash-" + category + r"\s*\{([^}]*)\}", modern).group(1).replace(" ", "")
        assert f"background:var(--alert-{colour}-bg)" in body and f"border-color:var(--alert-{colour}-border)" in body
        assert "color:" not in body.replace("border-color:", ""), "toast text is --alert-text, not a tone colour"


def test_every_message_box_takes_the_alert_palette():
    """Message boxes outside the auth pages (UI-B46, owner decisions): palette tone, dark text, DS corners."""
    boxes = (
        ("templates/admin_diagnostico_atividades_versionadas_view.html", ".diag-alert", "red"),
        ("templates/admin_requisicoes.html", ".req-email-warnings", "red"),
        ("templates/admin_requisicoes.html", ".req-email-resend", "yellow"),
    )
    for page, selector, colour in boxes:
        body = _rule(_source(page), selector)
        assert f"border:1pxsolidvar(--alert-{colour}-border)" in body, (page, selector)
        assert f"background:var(--alert-{colour}-bg)" in body, (page, selector)
        assert "color:var(--alert-text)" in body, (page, selector)
        assert "border-radius:var(--radius)" in body, (page, selector)
        assert "--danger" not in body and not re.search(r"#[0-9a-fA-F]{3,8}\b", body), selector
    # The link inside the e-mail warnings reads as the box's text.
    requisicoes = _source("templates/admin_requisicoes.html")
    assert "color:inherit" in _rule(requisicoes, ".req-email-cta")
    # A highlighted recipient row takes the tone of the warning that lists it.
    for selector, colour in ((".req-email-recipient.is-blocked", "red"), (".req-email-recipient.is-unresolved", "yellow")):
        body = _rule(requisicoes, selector)
        assert f"background:var(--alert-{colour}-bg)" in body, selector


def test_destructive_actions_invalid_fields_and_status_badges_are_not_alerts():
    """They keep their own families; none takes the alert palette."""
    modern = _source("static/css/modern-style.css")
    form = _source("static/css/components/form.css")
    keep = (
        (modern, "\n.btn.danger", "--danger-text"),
        (modern, ".badge.status-pill.status-negative", "--status-negative-"),
        (modern, ".badge.status-pill.status-positive", "--status-positive-"),
        (form, ".field-error", "--field-invalid-"),
    )
    for source, selector, family in keep:
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
        assert match, selector
        assert family in match.group(1) and "--alert-" not in match.group(1), selector


def _style_block(page):
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", _source(page), re.S))


def test_the_email_modal_and_the_diagnostic_page_take_every_colour_from_tokens():
    """Owner decision (UI-B46): both screens fully on the DS -- tokens and DS components, no literal colour."""
    raw = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(")
    diag_page = "templates/admin_diagnostico_atividades_versionadas_view.html"
    assert not raw.search(_style_block(diag_page)), "the diagnostic page keeps a literal colour"
    modal_rules = [
        (sel, body) for sel, body in re.findall(r"(?m)^(\.req-email-[^{]*)\{([^}]*)\}", _style_block("templates/admin_requisicoes.html"))
        if not sel.startswith(".req-email-cell")  # the list column's icon, not the confirmation modal
    ]
    assert len(modal_rules) >= 15, "lost sight of the e-mail modal rules"
    offenders = [sel.strip() for sel, body in modal_rules if raw.search(body)]
    assert not offenders, f"e-mail modal rules with a literal colour: {offenders}"
    # Corners are the DS radius, not a page-local 8px.
    assert not [sel for sel, body in modal_rules if "border-radius:8px" in body.replace(" ", "")]
    # Roles take DS components: the section card's chips for the page labels (DS-CONSISTENCY-01: a status
    # pill carries a status only, and "Admin-only" is a label), the DS disclosure toggle colour.
    page = _source(diag_page)
    assert '<span class="cfg-chip">Admin-only</span>' in page
    assert '<span class="cfg-chip">Leitura paralela (não operacional)</span>' in page
    assert "status-pill" not in page, "the diagnostic page has no status to show"
    assert not re.search(r"diag-(?:badge|pill|chip)\b(?!s)", page), "page-local badges are gone"
    toggle = _rule(_style_block("templates/admin_requisicoes.html"), ".req-email-preview-wrap > summary")
    assert "color:var(--text-secondary)" in toggle and "font-size:var(--font-size-small)" in toggle
