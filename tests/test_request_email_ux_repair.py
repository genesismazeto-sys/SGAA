"""Post-landing UX/regression repairs for the request e-mail feature.

Covers: Microsoft capability wording, floating-bar ownership, the design-system
chevron, the dedicated pending-e-mail column, and pt-BR count agreement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.request_email_render import (
    PLACEHOLDER_HELP,
    PlaceholderError,
    build_context,
    pluralize,
    render_template,
    validate_template,
)
from tests.request_email_support import (
    decide,
    new_v7_connection,
    seed_activity,
    seed_request,
    seed_student,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (PROJECT_ROOT / "templates" / "admin_requisicoes.html").read_text(encoding="utf-8")
BANCO_TPL = (PROJECT_ROOT / "templates" / "admin_banco_dados.html").read_text(encoding="utf-8")
LIST_CSS = (PROJECT_ROOT / "static" / "css" / "components" / "list-cards.css").read_text(encoding="utf-8")


def _events(conn, ids):
    from app.request_email_notifications import load_pending_events
    return load_pending_events(conn, ids)


def _student_with(dates):
    conn = new_v7_connection()
    versao = seed_activity(conn)
    aluno = seed_student(conn, nome="Aluno Teste", matricula="1", email="a@x.com")
    ids = []
    for d in dates:
        r = seed_request(conn, aluno_id=aluno, versao_id=versao, data_solicitacao=d)
        decide(conn, r, status="Deferida")
        ids.append(r)
    return conn, ids


# ===================== 1. MICROSOFT CAPABILITY =====================

class _FakeAccount(dict):
    pass


def _status_with(monkeypatch, *, account, scopes=None):
    import app.services.mail_service as ms
    payload = None
    if account is not None:
        payload = dict(account)
        if scopes is not None:
            payload["token_json"] = json.dumps({"msal_cache": "{}", "scopes": scopes})
    monkeypatch.setattr(
        "app.cloud_connections.get_active_cloud_account", lambda conn, provider: payload
    )
    return ms.mail_transport_status(object())


def test_connected_storage_without_mail_send_is_not_called_disconnected(monkeypatch):
    st = _status_with(
        monkeypatch,
        account={"account_email": "a@b.com", "token_json_available": True},
        scopes=["User.Read", "Files.ReadWrite"],
    )
    assert st["reason"] == "scope_missing"
    assert st["provider_connected"] is True
    assert st["provider_status"] == "connected"
    assert "Reconecte" not in st["message"]
    assert st["message"] == "Autorize o envio de e-mails para a conta Microsoft conectada."


def test_missing_mail_send_cta_describes_authorization_not_reconnection(monkeypatch):
    st = _status_with(
        monkeypatch,
        account={"account_email": "a@b.com", "token_json_available": True},
        scopes=["User.Read", "Files.ReadWrite"],
    )
    assert st["cta_label"] == "Autorizar envio de e-mails"
    assert "Reconectar" not in st["cta_label"]


def test_missing_mail_send_still_blocks_send(monkeypatch):
    st = _status_with(
        monkeypatch,
        account={"account_email": "a@b.com", "token_json_available": True},
        scopes=["User.Read", "Files.ReadWrite"],
    )
    assert st["ready"] is False


def test_mail_send_present_reports_authorized_and_ready(monkeypatch):
    st = _status_with(
        monkeypatch,
        account={"account_email": "a@b.com", "token_json_available": True},
        scopes=["User.Read", "Files.ReadWrite", "Mail.Send"],
    )
    assert st["ready"] is True
    assert st["provider_connected"] is True
    assert st["provider_status"] == "connected"


def test_genuinely_disconnected_keeps_connect_semantics(monkeypatch):
    st = _status_with(monkeypatch, account=None)
    assert st["reason"] == "not_connected"
    assert st["provider_connected"] is False
    assert st["provider_status"] == "disconnected"
    assert st["cta_label"] == "Conectar Microsoft"


def test_capability_probe_never_clears_a_token(monkeypatch):
    """Rendering capability state must not disconnect or rewrite anything."""
    import app.cloud_connections as cc
    calls = []
    monkeypatch.setattr(cc, "disconnect_cloud_account", lambda *a, **k: calls.append("disconnect"))
    monkeypatch.setattr(cc, "update_cloud_account_token", lambda *a, **k: calls.append("update"))
    _status_with(
        monkeypatch,
        account={"account_email": "a@b.com", "token_json_available": True},
        scopes=["User.Read", "Files.ReadWrite"],
    )
    assert calls == []


def test_authorization_route_is_non_destructive_incremental_consent():
    """The reused connect route must not disconnect before re-consenting."""
    src = (PROJECT_ROOT / "app" / "views" / "admin" / "banco_dados.py").read_text(encoding="utf-8")
    body = src.split("def admin_backup_onedrive_connect(")[1].split("\ndef ")[0]
    assert "disconnect_cloud_account" not in body
    assert "_save_drive_config" not in body


def test_banco_dados_shows_mail_capability_separately():
    assert "onedrive_mail_status" in BANCO_TPL
    # The provider badge itself is untouched.
    assert "status-positive\">Conectado</span>" in BANCO_TPL


# --- mail status card: label + pill, matching the neighbouring rows ---------

def test_mail_row_label_is_ordinary_card_text_with_the_colon():
    assert "<strong>Envio de e-mails:</strong>" in BANCO_TPL


def test_pill_contains_only_the_state():
    assert '<span class="badge status-pill status-positive">Autorizado</span>' in BANCO_TPL
    assert '<span class="badge status-pill status-warning">Não autorizado</span>' in BANCO_TPL


def test_whole_phrase_is_never_inside_the_pill():
    """The regression was `[Envio de e-mails: autorizado]` as one pill."""
    for bad in (
        'status-pill status-positive">Envio de e-mails',
        'status-pill status-warning">Envio de e-mails',
        "Envio de e-mails: autorizado",
        "Envio de e-mails: autorização necessária",
    ):
        assert bad not in BANCO_TPL
    src = (PROJECT_ROOT / "app" / "views" / "admin" / "banco_dados.py").read_text(encoding="utf-8")
    assert "Envio de e-mails: autorizado" not in src
    assert "Envio de e-mails: autorização necessária" not in src


def test_mail_row_reuses_the_same_ds_structure_as_providers():
    """Same shape as the Google Drive / OneDrive rows: <strong>label</strong> + pill."""
    import re
    rows = re.findall(
        r"<strong>([^<]+:)</strong>\s*\n\s*(?:\{%.*?%\}\s*\n\s*)?"
        r'<span class="badge status-pill status-(\w+)">([^<]+)</span>',
        BANCO_TPL,
    )
    labels = {label for label, _tone, _state in rows}
    assert "Google Drive:" in labels
    assert "Envio de e-mails:" in labels
    # The mail state reuses an existing DS tone, not a bespoke colour.
    tones = {tone for _l, tone, _s in rows}
    assert tones <= {"positive", "neutral", "warning", "caution", "negative"}


def test_mail_row_is_hidden_when_provider_is_not_connected():
    """Disconnected Microsoft keeps normal connect semantics; no mail row."""
    src = (PROJECT_ROOT / "app" / "views" / "admin" / "banco_dados.py").read_text(encoding="utf-8")
    block = src.split("def _onedrive_mail_capability(")[1].split("\ndef ")[0]
    assert '"visible": False' in block
    assert 'status["reason"] != "scope_missing"' in block
    assert "onedrive_mail_status.visible" in BANCO_TPL


# ===================== 2. FLOATING BAR COUNTER =====================

def test_hidden_counter_has_zero_rendered_footprint():
    assert ".pedido-actions-float .act-count[hidden]{ display:none; }" in TEMPLATE


def test_counter_rule_order_lets_hidden_win():
    base = TEMPLATE.index(".pedido-actions-float .act-count{")
    hidden = TEMPLATE.index(".pedido-actions-float .act-count[hidden]")
    assert hidden > base, "the [hidden] rule must come after the base rule"


def test_counter_only_populated_for_batch():
    assert "countEl.hidden = !batch;" in TEMPLATE
    assert "countEl.textContent = batch ? String(rows.length) : '';" in TEMPLATE


# ============ 2b. FLOATING BAR CONTAINMENT (right-edge overflow) ============

def _position_block():
    return TEMPLATE.split("function positionFor(card)")[1].split("\n    }")[0]


def _position_code():
    """positionFor body with // comments stripped, so assertions test code."""
    import re
    return "\n".join(
        re.sub(r"//.*$", "", line) for line in _position_block().splitlines()
    )


def test_geometry_is_taken_from_the_anchor_card_not_the_track():
    code = _position_code()
    assert "card.getBoundingClientRect()" in code
    assert ".app-track" not in code, "must not anchor to the global content track"
    assert "contentRight" not in code


def test_bar_is_flush_with_the_row_right_edge_with_zero_inset():
    """DS convention: "encostar na BORDA DIREITA" -- no gap, ever.

    Alunos/Cursos/Turmas/Atividades all compute `right_edge - barWidth` with no
    inset; Requisições must agree, differing only in WHICH right edge is the
    anchor (the row, because this list scrolls horizontally).

    Requisições additionally drops the shared `Math.round()`: a row in this grid
    rarely ends on a whole pixel, and rounding UP put the bar's right edge past
    the row's border (see tests/test_requisicoes_floating_bar_first_paint.py ::
    test_fractional_row_boundary_is_never_crossed). The formula is otherwise
    identical -- still a bare `right_edge - barWidth` with zero inset.
    """
    block = _position_block()
    assert "bar.style.left = (boundRight - barW) + 'px';" in block
    assert "Math.round(boundRight" not in block


def test_no_invented_inset_constant():
    block = _position_code()
    assert "BAR_INSET" not in block
    assert "INSET" not in block
    assert "+ 8" not in block and "- 8" not in block


def test_matches_the_shared_geometry_convention_of_the_other_lists():
    """Same formula shape as the canonical lists: edge minus bar width."""
    import re
    others = []
    for name in ("admin_alunos", "admin_cursos", "admin_turmas", "admin_atividades"):
        src = (PROJECT_ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8")
        body = src.split("function positionFor(card)")[1].split("\n      }")[0]
        others.append(body)
    # Every canonical list subtracts only the bar width from a right edge.
    for body in others:
        assert re.search(r"-\s*bar\.offsetWidth", body)
        assert "INSET" not in body
    # Requisições does the same, against the row's right edge.
    assert re.search(r"boundRight\s*-\s*barW", _position_block())


def test_bounds_clamped_to_visible_list_area_for_horizontal_scroll():
    block = _position_code()
    assert "boundRight = Math.min(boundRight, wrapRect.right);" in block


def test_stale_right_positioning_is_cleared():
    assert "bar.style.right = 'auto';" in _position_block()


def test_no_magic_negative_margin_used():
    block = _position_code()
    assert "margin" not in block


def test_geometry_recalculated_on_scroll_resize_and_horizontal_scroll():
    assert "window.addEventListener('scroll', reposition);" in TEMPLATE
    assert "window.addEventListener('resize', reposition);" in TEMPLATE
    assert "scrollWrap?.addEventListener('scroll', reposition);" in TEMPLATE


def test_containment_simulated_for_a_row_narrower_than_the_track():
    """Pure-arithmetic model of the shipped formula, incl. the Delete button.

    Reproduces the reported failure: the row's right edge sits well left of the
    content-track edge the old code used.
    """
    def place(row_right, bar_w, wrap_right=None):
        br = row_right if wrap_right is None else min(row_right, wrap_right)
        left = br - bar_w
        return left, left + bar_w

    # Row ends at 1200; the old code anchored to a track ending at 1400.
    for bar_w in (90, 120, 150, 180):
        left, right = place(1200, bar_w)
        assert right == 1200, (bar_w, right)   # flush, zero gap
        assert right <= 1200
        assert left == 1200 - bar_w

    # The Delete button is the last child, so its right edge is the bar's right
    # edge minus the bar's padding -- inside by construction.
    left, right = place(1200, 150)
    assert right - 6 < right <= 1200

    # Horizontally scrolled row: clamped to the visible area, still flush.
    left, right = place(1500, 150, wrap_right=1000)
    assert right == 1000


# ===================== 3. FLOATING BAR OWNERSHIP =====================

def test_selection_owns_bar_for_any_selection():
    assert "function selectionOwnsBar(){ return selectedRows().length > 0; }" in TEMPLATE


def test_hover_cannot_retarget_when_anything_is_selected():
    block = TEMPLATE.split("scrollWrap?.addEventListener('mouseover'")[1][:600]
    assert "if (selectionOwnsBar()) return;" in block
    assert "length > 1" not in block, "ownership must not special-case only >1"


def test_sync_anchors_bar_to_selected_row():
    block = TEMPLATE.split("window.requisicoesFloatingBarSync = function()")[1][:800]
    assert "currentCard = anchor;" in block
    assert "currentId = anchor.getAttribute('data-req-id');" in block
    assert "positionFor(anchor);" in block


def test_clearing_selection_drops_stale_ownership():
    block = TEMPLATE.split("window.requisicoesFloatingBarSync = function()")[1][:800]
    assert "if (!rows.length){" in block
    assert "hide();" in block


def test_selection_cleared_outside_list_resyncs():
    assert "document.addEventListener('click', ()=>{ setTimeout(()=>window.requisicoesFloatingBarSync(), 0); });" in TEMPLATE


def test_bar_mouseleave_does_not_hide_selection_owned_bar():
    assert "bar.addEventListener('mouseleave', ()=>{ if (!selectionOwnsBar()) scheduleHide(); });" in TEMPLATE


def test_single_selection_updates_actions_for_selected_row():
    block = TEMPLATE.split("window.requisicoesFloatingBarSync = function()")[1][:800]
    assert "if (rows.length === 1) updatePrimaryActionFor(anchor);" in block


# ===================== 4. DS CHEVRON =====================

def test_native_summary_marker_is_suppressed():
    assert ".req-email-preview-wrap > summary::-webkit-details-marker{ display:none; }" in TEMPLATE
    assert 'list-style:none' in TEMPLATE
    assert '.req-email-preview-wrap > summary::marker{ content:""; }' in TEMPLATE


def test_ds_chevron_is_used_not_a_bespoke_shape():
    assert 'data-lucide="chevron-right"' in TEMPLATE
    assert "req-email-preview-chevron" in TEMPLATE
    for bespoke in ("▶", "►", "▼", "&#9654;", "border-left: 6px solid"):
        assert bespoke not in TEMPLATE


def test_chevron_state_follows_disclosure():
    block = TEMPLATE.split("function syncPreviewChevron()")[1][:420]
    assert "elPrevWrap.open ? 'chevron-down' : 'chevron-right'" in block
    assert "elPrevWrap?.addEventListener('toggle', syncPreviewChevron);" in TEMPLATE


def test_details_semantics_preserved():
    assert "<details id=\"req-email-preview-wrap\"" in TEMPLATE
    assert "<summary>" in TEMPLATE


# ===================== 5. DEDICATED EMAIL COLUMN =====================

def test_grid_has_ten_columns_with_email_between_atividade_and_status():
    block = LIST_CSS.split(".imp-req { --imp-cols:")[1].split("};")[0]
    lines = [l for l in block.splitlines() if "minmax" in l]
    assert len(lines) == 10, lines
    assert "Atividade" in lines[7]
    assert "E-mail" in lines[8]
    assert "Status" in lines[9]


def test_email_column_is_narrow_and_fixed_width():
    block = LIST_CSS.split(".imp-req { --imp-cols:")[1].split("};")[0]
    email_line = [l for l in block.splitlines() if "E-mail" in l][0]
    assert "minmax(28px, 28px)" in email_line


def test_list_min_width_accounts_for_new_column():
    assert "--imp-list-min-width:1212px" in LIST_CSS


def test_header_has_blank_label_for_email_column():
    assert "{'text': '', 'class': 'center req-email-cell'}," in TEMPLATE


def test_email_column_opts_out_of_the_shared_empty_dash_placeholder():
    """The shared rule paints "—" into any empty cell; this column must not."""
    assert '.impresso-card .cell:empty::before{ content:"—"' in LIST_CSS
    assert ".imp-req .impresso-card .cell.req-email-cell:empty::before{ content:none; }" in LIST_CSS


def test_empty_dash_placeholder_is_preserved_for_other_lists():
    """Scoped override only: other consumers keep the shared placeholder."""
    override = ".imp-req .impresso-card .cell.req-email-cell:empty::before"
    assert override in LIST_CSS
    # The shared rule itself is untouched (no global content:none).
    assert ".impresso-card .cell:empty::before{ content:none" not in LIST_CSS


def test_request_number_cell_shows_only_the_number():
    assert "{'class': 'center', 'content': (r.id|string)}," in TEMPLATE
    assert "req-id-cell" not in TEMPLATE


def test_icon_lives_only_in_dedicated_cell():
    assert "{'class': 'center req-email-cell', 'content': email_cell}," in TEMPLATE
    assert ".req-email-cell .req-email-pending" in TEMPLATE


def test_empty_rows_still_reserve_the_column():
    # The cell is always emitted; only its content is conditional.
    block = TEMPLATE.split("{% set email_cell %}")[1].split("{% endset %}")[0]
    assert "{% if is_email_pendente %}" in block


def test_accessibility_labels_preserved():
    assert "E-mail pendente de envio" in TEMPLATE
    assert "E-mail pendente — última tentativa falhou." in TEMPLATE
    assert 'role="img"' in TEMPLATE


# ===================== 6. CONFIRMATION COUNT GRAMMAR =====================

@pytest.mark.parametrize(
    "n,singular,plural,expected",
    [
        (1, "requisição", "requisições", "1 requisição"),
        (2, "requisição", "requisições", "2 requisições"),
        (1, "aluno", "alunos", "1 aluno"),
        (2, "aluno", "alunos", "2 alunos"),
        (1, "e-mail", "e-mails", "1 e-mail"),
        (3, "e-mail", "e-mails", "3 e-mails"),
        (0, "aluno", "alunos", "0 alunos"),
    ],
)
def test_pluralize_agrees_with_count(n, singular, plural, expected):
    assert pluralize(n, singular, plural) == expected


def test_summary_template_no_longer_hardcodes_plural_nouns():
    assert "'emailSummary': user_message('{value_1} · {value_2} · {value_3}')" in TEMPLATE
    assert "{value_1} requisições · {value_2} alunos" not in TEMPLATE


def test_summary_uses_server_agreed_parts():
    assert "value_1: data.resumo_requisicoes" in TEMPLATE
    assert "value_2: data.resumo_alunos" in TEMPLATE
    assert "value_3: data.resumo_emails" in TEMPLATE


# ===================== 7. SMART PLACEHOLDERS =====================

def test_one_request_renders_singular():
    conn, ids = _student_with(["2026-09-15"])
    ctx = build_context(_events(conn, ids), aluno_nome="Aluno", aluno_matricula="1")
    assert ctx["requisicao.possessivo"] == "Sua"
    assert ctx["requisicao.substantivo"] == "solicitação"
    assert ctx["requisicao.processamento"] == "foi processada"
    assert ctx["data.periodo"] == "do dia 15/09/2026"


def test_two_requests_same_day_renders_plural_with_single_date():
    conn, ids = _student_with(["2026-09-15", "2026-09-15"])
    ctx = build_context(_events(conn, ids), aluno_nome="Aluno", aluno_matricula="1")
    assert ctx["requisicao.possessivo"] == "Suas"
    assert ctx["requisicao.substantivo"] == "solicitações"
    assert ctx["requisicao.processamento"] == "foram processadas"
    assert ctx["data.periodo"] == "do dia 15/09/2026"


def test_two_requests_different_days_render_range():
    conn, ids = _student_with(["2026-09-15", "2026-09-18"])
    ctx = build_context(_events(conn, ids), aluno_nome="Aluno", aluno_matricula="1")
    assert ctx["requisicao.substantivo"] == "solicitações"
    assert ctx["data.periodo"] == "de 15/09/2026 a 18/09/2026"


def test_backward_compatible_placeholders_still_work():
    conn, ids = _student_with(["2026-09-15", "2026-09-18"])
    ctx = build_context(_events(conn, ids), aluno_nome="Aluno", aluno_matricula="1")
    assert ctx["data.inicio"] == "15/09/2026"
    assert ctx["data.fim"] == "18/09/2026"
    assert ctx["quantidade_requisicoes"] == "2"


def test_number_is_per_student_not_per_batch():
    """João (2) plural, Maria (1) singular, from the same selection."""
    from app.request_email_notifications import group_events_by_student, load_pending_events

    conn = new_v7_connection()
    versao = seed_activity(conn)
    joao = seed_student(conn, nome="João", matricula="1", email="j@x.com")
    maria = seed_student(conn, nome="Maria", matricula="2", email="m@x.com")
    ids = []
    for _ in range(2):
        r = seed_request(conn, aluno_id=joao, versao_id=versao); decide(conn, r, status="Deferida"); ids.append(r)
    r = seed_request(conn, aluno_id=maria, versao_id=versao); decide(conn, r, status="Deferida"); ids.append(r)

    grouped = group_events_by_student(load_pending_events(conn, ids))
    ctx_joao = build_context(grouped[joao], aluno_nome="João", aluno_matricula="1")
    ctx_maria = build_context(grouped[maria], aluno_nome="Maria", aluno_matricula="2")

    assert ctx_joao["requisicao.processamento"] == "foram processadas"
    assert ctx_maria["requisicao.processamento"] == "foi processada"


def test_expected_configurable_template_renders():
    body = ("{saudacao}, {aluno.primeironome}.\n\n"
            "{requisicao.possessivo} {requisicao.substantivo} {data.periodo}\n"
            "{requisicao.processamento}.\n\n{requisicoes}")
    conn, ids = _student_with(["2026-09-15"])
    ctx = build_context(_events(conn, ids), aluno_nome="Aluno Teste", aluno_matricula="1")
    out = render_template(body, ctx)
    assert "Sua solicitação do dia 15/09/2026" in out
    assert "foi processada." in out


def test_new_placeholders_are_valid_and_unknown_still_rejected():
    for token in ("{requisicao.possessivo}", "{requisicao.substantivo}",
                  "{requisicao.processamento}", "{data.periodo}"):
        validate_template(f"texto {token}")
    with pytest.raises(PlaceholderError):
        validate_template("{requisicao.inexistente}")


def test_new_placeholders_are_scalar_and_subject_safe():
    validate_template("{requisicao.substantivo} {data.periodo}", allow_block=False)


def test_new_placeholders_documented_in_help():
    tokens = {name for name, _help in PLACEHOLDER_HELP}
    assert {"{requisicao.possessivo}", "{requisicao.substantivo}",
            "{requisicao.processamento}", "{data.periodo}"} <= tokens
    help_by_token = dict(PLACEHOLDER_HELP)
    assert help_by_token["{requisicao.possessivo}"] == "Sua / Suas conforme a quantidade de requisições."
    assert help_by_token["{requisicao.substantivo}"] == "solicitação / solicitações."
    assert help_by_token["{requisicao.processamento}"] == "foi processada / foram processadas."
