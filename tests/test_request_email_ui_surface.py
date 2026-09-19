"""UI surface contract for the request e-mail notification feature.

Static assertions over the rendered template source: the pending indicator, the
selection-aware Ações item and the floating-bar integration all read from the
same selected-row authority.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (PROJECT_ROOT / "templates" / "admin_requisicoes.html").read_text(
    encoding="utf-8"
)
TOOLBAR_JS = (PROJECT_ROOT / "static" / "js" / "toolbar-filters.js").read_text(
    encoding="utf-8"
)


# --- pending indicator -----------------------------------------------------

def test_row_exposes_email_pending_state():
    assert "data-email-pending" in TEMPLATE
    assert "'data-email-pending': '1' if is_email_pendente else '0'" in TEMPLATE


def test_pending_icon_is_conditional_on_pending_state():
    assert "{% if is_email_pendente %}" in TEMPLATE
    assert "req-email-pending" in TEMPLATE


def test_pending_icon_has_accessible_label():
    assert "E-mail pendente de envio" in TEMPLATE


def test_failed_attempt_has_danger_treatment_and_tooltip():
    assert "E-mail pendente — última tentativa falhou." in TEMPLATE
    assert "is-error" in TEMPLATE
    assert "mail-warning" in TEMPLATE


# --- Ações menu ------------------------------------------------------------

def test_actions_menu_has_send_email_item_gated_on_edit_permission():
    assert 'id="req-action-email"' in TEMPLATE
    marker = TEMPLATE.split('id="req-action-email"')[1][:200]
    assert "disabled" in marker
    assert "not can_requisicoes_edit" in marker


def test_send_email_requires_every_selected_row_pending():
    assert "function selectionAllEmailPending(rows)" in TEMPLATE
    assert "rows.every(r => r.getAttribute('data-email-pending') === '1')" in TEMPLATE
    assert "rows.length > 0" in TEMPLATE


def test_send_email_uses_shared_row_selection_authority():
    """No second selection model: ids come from rowSelectionApi."""
    block = TEMPLATE.split("itmEmail?.addEventListener")[1][:400]
    assert "rowSelectionApi.getSelectedRows()" in block


def test_single_row_actions_stay_single_row():
    """A multi-selection must not let Ver/Editar/Processar act on row zero."""
    assert "const row  = rows.length === 1 ? rows[0] : null;" in TEMPLATE


def test_mixed_selection_hint_is_shown():
    assert "Todas as requisições selecionadas precisam ter e-mail pendente." in TEMPLATE


# --- floating bar ----------------------------------------------------------

def test_floating_bar_has_email_action():
    assert 'data-action="email"' in TEMPLATE


def test_floating_bar_uses_same_selection_authority():
    assert "window.requisicoesRowSelectionApi?.getSelectedRows?.()" in TEMPLATE


def test_floating_bar_batch_mode_hides_single_request_actions():
    assert "const singleOnlyActions = ['process','edit','view','delete'];" in TEMPLATE
    assert "if (btn) btn.hidden = batch;" in TEMPLATE


def test_floating_bar_shows_selection_count_in_batch_mode():
    assert 'data-role="selection-count"' in TEMPLATE
    assert "countEl.textContent = batch ? String(rows.length) : '';" in TEMPLATE


def test_floating_bar_email_requires_all_selected_pending():
    block = TEMPLATE.split("function applyBatchMode(rows)")[1][:600]
    assert "allSelectedPending(rows)" in block


def test_hover_does_not_retarget_an_active_batch():
    """Repaired: ANY selection owns the bar, not only a multi-selection."""
    assert "function selectionOwnsBar(){ return selectedRows().length > 0; }" in TEMPLATE
    block = TEMPLATE.split("scrollWrap?.addEventListener('mouseover'")[1][:600]
    assert "if (selectionOwnsBar()) return;" in block


# --- confirmation step -----------------------------------------------------

def test_send_opens_confirmation_before_any_send():
    assert 'id="req-email-modal"' in TEMPLATE
    assert "window.openRequisicoesEmailConfirm" in TEMPLATE
    # The menu item opens the dialog; it never posts to the send endpoint.
    block = TEMPLATE.split("itmEmail?.addEventListener")[1][:400]
    assert "email/enviar" not in block


def test_confirmation_shows_counts_template_and_recipients():
    assert "emailSummary" in TEMPLATE
    # Repaired: the nouns are agreed server-side, so the template only joins
    # three already-formed parts instead of hardcoding plural words.
    assert "'emailSummary': user_message('{value_1} · {value_2} · {value_3}')" in TEMPLATE
    assert "value_1: data.resumo_requisicoes" in TEMPLATE
    assert 'id="req-email-recipients"' in TEMPLATE
    assert 'id="req-email-template"' in TEMPLATE


def test_confirmation_offers_preview():
    assert 'id="req-email-preview"' in TEMPLATE
    assert "Pré-visualizar mensagem" in TEMPLATE


def test_confirm_button_is_guarded_against_double_submit():
    assert "let inFlight = false;" in TEMPLATE
    assert "if (inFlight || btnConfirm.disabled) return;" in TEMPLATE


def test_no_provider_internals_are_rendered():
    for forbidden in ("access_token", "refresh_token", "client_secret", "Bearer "):
        assert forbidden not in TEMPLATE


# --- shared selection authority is unchanged -------------------------------

def test_shared_selection_component_still_multi_select():
    assert "const selectedRows = new Set();" in TOOLBAR_JS
    assert "const addRange = (index) =>" in TOOLBAR_JS


# --- Pré-definições surface ------------------------------------------------

def test_presets_editor_exposes_subject_and_default():
    assert 'id="preset-subject-input"' in TEMPLATE
    assert 'id="preset-default-input"' in TEMPLATE
    assert "Assunto do e-mail" in TEMPLATE


def test_presets_editor_documents_titulo_is_not_the_subject():
    assert "Nome interno do modelo. Não é o assunto do e-mail." in TEMPLATE


def test_presets_editor_lists_placeholders_with_block_explanation():
    """The help text is supplied by PLACEHOLDER_HELP and rendered per chip."""
    from app.request_email_render import PLACEHOLDER_HELP

    assert 'id="preset-placeholders"' in TEMPLATE
    # Each chip renders its token and carries the help text as its tooltip.
    assert "{% for token, help_text in email_placeholder_help %}" in TEMPLATE
    assert 'title="{{ help_text }}"' in TEMPLATE
    help_by_token = dict(PLACEHOLDER_HELP)
    assert help_by_token["{requisicoes}"] == (
        "Insere o detalhamento das requisições selecionadas para o aluno."
    )


@pytest.mark.parametrize(
    "token",
    [
        "{saudacao}",
        "{aluno.nome}",
        "{aluno.primeironome}",
        "{aluno.matricula}",
        "{data.inicio}",
        "{data.fim}",
        "{quantidade_requisicoes}",
        "{requisicoes}",
    ],
)
def test_every_placeholder_is_offered_in_the_editor(token):
    from app.request_email_render import PLACEHOLDER_HELP

    assert token in {name for name, _help in PLACEHOLDER_HELP}


def test_justificativas_section_is_preserved():
    assert "Justificativas pré-definidas" in TEMPLATE
    assert 'value="respostas"' in TEMPLATE


# --- unconfirmed-resend acknowledgement -----------------------------------

def test_unresolved_recipients_are_marked_in_the_confirmation_list():
    assert "d.reenvio_incerto ? ' is-unresolved' : ''" in TEMPLATE
    assert ".req-email-recipient.is-unresolved" in TEMPLATE


def test_acknowledgement_block_exists_and_starts_hidden():
    assert 'id="req-email-resend-block"' in TEMPLATE
    block = TEMPLATE.split('id="req-email-resend-block"')[1][:120]
    assert "hidden" in block
    assert 'id="req-email-resend-ack"' in TEMPLATE


def test_send_stays_blocked_until_the_duplicate_risk_is_accepted():
    """An unconfirmed previous attempt must not be resendable by default."""
    assert "function syncConfirmState()" in TEMPLATE
    body = TEMPLATE.split("function syncConfirmState()")[1][:420]
    assert "unresolvedIds.length > 0" in body
    assert "ackResend" in body and "checked" in body
    assert "btnConfirm.disabled = !ready || ackPending;" in body


def test_acknowledgement_is_sent_only_for_the_acknowledged_students():
    block = TEMPLATE.split("const body = { requisicao_ids: currentIds };")[1][:400]
    assert "if (unresolvedIds.length && ackResend && ackResend.checked)" in block
    assert "body.confirmar_reenvio = unresolvedIds;" in block


def test_acknowledgement_resets_every_time_the_dialog_opens():
    """A stale tick must never carry over into the next selection."""
    block = TEMPLATE.split("window.openRequisicoesEmailConfirm = async function(ids)")[1][:900]
    assert "unresolvedIds = [];" in block
    assert "lastPreview = null;" in block
    assert "ackResend.checked = false;" in block
