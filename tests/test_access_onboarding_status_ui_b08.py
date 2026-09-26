"""UI-B08: the access/onboarding status column on Admin > Acesso.

Two things are under test and they are deliberately separated:

1. DERIVATION (``app/access_onboarding.py``) -- the state is a function of
   durable authentication evidence only. The pure-function tests pin every
   branch; the lifecycle tests drive the real routes and read the state back
   from a real database, so a handler that stops writing the evidence fails
   here even if the derivation is still correct.

2. PRESENTATION (``app/status_presentation.py`` + ``templates/admin_acesso.html``)
   -- one pill per row, last column, shared DS primitive, tone from the single
   owner, no local colour.

The state is NOT ``alunos.status``. Under the prod-1/v11 credential model it is
``Ativo`` for every account holding a usable credential -- ``personal`` or an
explicitly applied ``default`` -- and follows first-access delivery evidence
only while the account is ``pending``. No global setting moves a pill; that has
its own test.

Every test uses a disposable database. The canonical database is never written.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from pathlib import Path

import pytest

import main
from app.access_onboarding import (
    access_status_for_usuario,
    access_status_map,
    derive_access_status,
)
from app.password_tokens import (
    PURPOSE_FIRST_ACCESS,
    PURPOSE_PASSWORD_RESET,
    consume_password_token_and_set_password,
    issue_password_token,
    mark_password_token_sent,
)
from app.security.passwords import hash_password
from app.status_presentation import (
    ACCESS_STATUS_ATIVO,
    ACCESS_STATUS_DISPONIBILIZADO,
    ACCESS_STATUS_EXPIRADO,
    ACCESS_STATUS_PENDENTE,
    ACCESS_STATUS_REVOGADO,
    ACCESS_STATUS_TONES,
    DS_STATUS_TONES,
    status_label,
    status_tone,
)
from app.user_accounts import (
    CREDENTIAL_STATE_DEFAULT,
    CREDENTIAL_STATE_PENDING,
    CREDENTIAL_STATE_PERSONAL,
    create_usuario_with_access_level,
    set_usuario_access_active,
    set_usuario_password_hash,
)
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACESSO_TEMPLATE = PROJECT_ROOT / "templates" / "admin_acesso.html"

#: The five states, and nothing else. Keeping the set compact is a product
#: requirement, not an accident: "Falhou", "Indeterminado", "Não enviado" and
#: "Aguardando usuário" are all deliberately absent.
EXPECTED_STATES = {
    ACCESS_STATUS_PENDENTE,
    ACCESS_STATUS_DISPONIBILIZADO,
    ACCESS_STATUS_ATIVO,
    ACCESS_STATUS_REVOGADO,
    ACCESS_STATUS_EXPIRADO,
}


# ------------------------------------------------------------------- helpers


def _seed_access(conn, label: str, *, state: str = CREDENTIAL_STATE_PENDING) -> int:
    cursor = create_usuario_with_access_level(
        conn, label, f"{label}@example.test", hash_password("seed-secret"),
        "admin", "admin_total", credential_state=state,
    )
    conn.commit()
    return int(cursor.lastrowid)


def _send_first_access(conn, usuario_id: int, *, confirmed: bool, ttl=None) -> int:
    """Issue a first-access token and optionally record a CONFIRMED send.

    ``confirmed=False`` is the shape both a definite failure and an
    indeterminate provider result leave behind as far as *delivery evidence*
    goes: no ``sent_at``.
    """
    _raw, token_id = issue_password_token(
        conn, usuario_id, PURPOSE_FIRST_ACCESS, ttl=ttl
    )
    if confirmed:
        assert mark_password_token_sent(conn, token_id) is True
    conn.commit()
    return token_id


# --------------------------------------------------- DERIVATION (pure branch)


def test_derivation_covers_exactly_the_five_states():
    assert set(ACCESS_STATUS_TONES) == EXPECTED_STATES


def test_missing_credential_row_is_pendente_not_revogado():
    """An incomplete account was never ended; nothing was revoked."""
    assert derive_access_status(
        acesso_ativo=None, credential_state=None, now="2026-01-01 00:00:00"
    ) == ACCESS_STATUS_PENDENTE


def test_revocation_outranks_every_other_signal():
    for state in (CREDENTIAL_STATE_PENDING, CREDENTIAL_STATE_DEFAULT, CREDENTIAL_STATE_PERSONAL):
        assert derive_access_status(
            acesso_ativo=0,
            credential_state=state,
            confirmed_sent_at="2026-01-01 00:00:00",
            confirmed_expires_at="2099-01-01 00:00:00",
            now="2026-01-02 00:00:00",
        ) == ACCESS_STATUS_REVOGADO


def test_personal_credential_is_ativo_with_or_without_any_email():
    assert derive_access_status(
        acesso_ativo=1, credential_state=CREDENTIAL_STATE_PERSONAL,
        now="2026-01-01 00:00:00",
    ) == ACCESS_STATUS_ATIVO


def test_an_applied_default_credential_is_ativo_whatever_the_delivery_evidence():
    """prod-1/v11: ``default`` is a deliberately applied, usable credential.

    It is no longer what a blank account is stored as, and no switch can take
    it away, so "awaiting a credential" would be false. Delivery evidence is
    onboarding evidence; an account holding a credential is past onboarding.
    """
    for sent_at, consumed_at, invalidated_at, expires_at in (
        (None, None, None, None),
        ("2026-01-01 00:00:00", None, None, "2099-01-01 00:00:00"),
        ("2026-01-01 00:00:00", None, None, "2025-01-01 00:00:00"),
        ("2026-01-01 00:00:00", None, "2026-01-02 00:00:00", "2099-01-01 00:00:00"),
        ("2026-01-01 00:00:00", "2026-01-02 00:00:00", None, "2099-01-01 00:00:00"),
    ):
        assert derive_access_status(
            acesso_ativo=1, credential_state=CREDENTIAL_STATE_DEFAULT,
            confirmed_sent_at=sent_at, confirmed_expires_at=expires_at,
            confirmed_consumed_at=consumed_at,
            confirmed_invalidated_at=invalidated_at,
            now="2026-06-01 00:00:00",
        ) == ACCESS_STATUS_ATIVO


def test_a_token_with_no_confirmed_send_does_not_reach_disponibilizado():
    """The central rule: issuance is not delivery."""
    assert derive_access_status(
        acesso_ativo=1, credential_state=CREDENTIAL_STATE_PENDING,
        confirmed_sent_at=None, confirmed_expires_at="2099-01-01 00:00:00",
        now="2026-01-01 00:00:00",
    ) == ACCESS_STATUS_PENDENTE


def test_confirmed_send_with_a_usable_link_is_disponibilizado():
    assert derive_access_status(
        acesso_ativo=1, credential_state=CREDENTIAL_STATE_PENDING,
        confirmed_sent_at="2026-01-01 00:00:00",
        confirmed_expires_at="2026-01-04 00:00:00",
        now="2026-01-02 00:00:00",
    ) == ACCESS_STATUS_DISPONIBILIZADO


def test_confirmed_send_whose_link_expired_is_expirado():
    assert derive_access_status(
        acesso_ativo=1, credential_state=CREDENTIAL_STATE_PENDING,
        confirmed_sent_at="2026-01-01 00:00:00",
        confirmed_expires_at="2026-01-04 00:00:00",
        now="2026-01-05 00:00:00",
    ) == ACCESS_STATUS_EXPIRADO


def test_confirmed_send_that_was_invalidated_is_expirado():
    """Superseded or cancelled: an e-mail went out, nothing usable remains."""
    assert derive_access_status(
        acesso_ativo=1, credential_state=CREDENTIAL_STATE_PENDING,
        confirmed_sent_at="2026-01-01 00:00:00",
        confirmed_expires_at="2099-01-01 00:00:00",
        confirmed_invalidated_at="2026-01-02 00:00:00",
        now="2026-01-03 00:00:00",
    ) == ACCESS_STATUS_EXPIRADO


def test_a_consumed_delivery_on_a_pending_account_is_pendente_not_expirado():
    """The revoke-then-reactivate-without-password shape: onboarding was
    completed once, then the credential was taken away. No link died, so
    Expirado would be a lie; the account is awaiting a credential again."""
    assert derive_access_status(
        acesso_ativo=1, credential_state=CREDENTIAL_STATE_PENDING,
        confirmed_sent_at="2026-01-01 00:00:00",
        confirmed_expires_at="2026-01-04 00:00:00",
        confirmed_consumed_at="2026-01-02 00:00:00",
        now="2026-01-09 00:00:00",
    ) == ACCESS_STATUS_PENDENTE


def test_every_derived_state_is_one_of_the_five():
    """Brute-force the input space; nothing may fall through to an unknown."""
    stamps = (None, "2026-01-01 00:00:00")
    seen = set()
    for acesso_ativo in (None, 0, 1):
        for credential_state in (
            None, CREDENTIAL_STATE_PENDING, CREDENTIAL_STATE_DEFAULT, CREDENTIAL_STATE_PERSONAL
        ):
            for sent_at in stamps:
                for consumed_at in stamps:
                    for invalidated_at in stamps:
                        for expires_at in ("2025-01-01 00:00:00", "2099-01-01 00:00:00"):
                            seen.add(derive_access_status(
                                acesso_ativo=acesso_ativo,
                                credential_state=credential_state,
                                confirmed_sent_at=sent_at,
                                confirmed_expires_at=expires_at,
                                confirmed_consumed_at=consumed_at,
                                confirmed_invalidated_at=invalidated_at,
                                now="2026-06-01 00:00:00",
                            ))
    assert seen <= EXPECTED_STATES
    assert seen == EXPECTED_STATES, f"unreachable states: {EXPECTED_STATES - seen}"


# ------------------------------------------------- LIFECYCLE (real database)


def test_lifecycle_transitions_against_durable_evidence(tmp_path):
    """A through J of the required lifecycle, on one real database."""
    with isolated_versioned_app_env(tmp_path, "b08-lifecycle.db"):
        with main.app.app_context():
            conn = main.get_db_connection()

            # A. new account, blank password -> Pendente
            blank = _seed_access(conn, "blankuser")
            assert access_status_for_usuario(conn, blank) == ACCESS_STATUS_PENDENTE

            # B. confirmed successful send -> Disponibilizado
            sent = _seed_access(conn, "sentuser")
            _send_first_access(conn, sent, confirmed=True)
            assert access_status_for_usuario(conn, sent) == ACCESS_STATUS_DISPONIBILIZADO

            # C. definite mail failure -> remains Pendente. The failure path
            #    invalidates the token it issued and writes no sent_at.
            failed = _seed_access(conn, "faileduser")
            from app.password_tokens import invalidate_password_token

            token_id = _send_first_access(conn, failed, confirmed=False)
            invalidate_password_token(conn, token_id)
            conn.commit()
            assert access_status_for_usuario(conn, failed) == ACCESS_STATUS_PENDENTE

            # D. indeterminate result -> must NOT claim Disponibilizado. The
            #    token stays valid (the mail may have arrived) but unmarked.
            unknown = _seed_access(conn, "unknownuser")
            _send_first_access(conn, unknown, confirmed=False)
            assert conn.execute(
                "SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=? AND consumed_at IS NULL"
                " AND invalidated_at IS NULL", (unknown,)
            ).fetchone()[0] == 1, "the indeterminate token should still be live"
            assert access_status_for_usuario(conn, unknown) == ACCESS_STATUS_PENDENTE

            # E. successful first-access password definition -> Ativo
            completing = _seed_access(conn, "completinguser")
            raw, completing_token = issue_password_token(
                conn, completing, PURPOSE_FIRST_ACCESS
            )
            assert mark_password_token_sent(conn, completing_token) is True
            conn.commit()
            assert access_status_for_usuario(conn, completing) == ACCESS_STATUS_DISPONIBILIZADO
            assert consume_password_token_and_set_password(
                conn, raw, PURPOSE_FIRST_ACCESS, hash_password("chosen-secret")
            ) is not None
            assert access_status_for_usuario(conn, completing) == ACCESS_STATUS_ATIVO

            # F. explicit personal password set by an admin -> Ativo, no e-mail
            explicit = _seed_access(conn, "explicituser", state=CREDENTIAL_STATE_PERSONAL)
            assert access_status_for_usuario(conn, explicit) == ACCESS_STATUS_ATIVO
            assert conn.execute(
                "SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=?", (explicit,)
            ).fetchone()[0] == 0

            # G. revoke -> Revogado
            set_usuario_access_active(conn, sent, False)
            conn.commit()
            assert access_status_for_usuario(conn, sent) == ACCESS_STATUS_REVOGADO

            # H. reactivate -> deterministic per the credential established.
            #    With a personal password: Ativo.
            set_usuario_password_hash(
                conn, sent, hash_password("new-secret"),
                credential_state=CREDENTIAL_STATE_PERSONAL,
            )
            set_usuario_access_active(conn, sent, True)
            conn.commit()
            assert access_status_for_usuario(conn, sent) == ACCESS_STATUS_ATIVO

            #    Without one: back to Pendente, because reactivation re-issues
            #    nothing and every pre-revocation token stays invalid.
            bare = _seed_access(conn, "bareuser")
            _send_first_access(conn, bare, confirmed=True)
            assert access_status_for_usuario(conn, bare) == ACCESS_STATUS_DISPONIBILIZADO
            from app.user_accounts import invalidate_usuario_password_tokens

            set_usuario_access_active(conn, bare, False)
            invalidate_usuario_password_tokens(conn, [bare])
            conn.commit()
            assert access_status_for_usuario(conn, bare) == ACCESS_STATUS_REVOGADO
            set_usuario_access_active(conn, bare, True)
            conn.commit()
            assert access_status_for_usuario(conn, bare) == ACCESS_STATUS_EXPIRADO, (
                "a confirmed delivery whose link was killed is Expirado, not a "
                "silent Disponibilizado"
            )

            # I. resend -> the newest authoritative evidence wins, no
            #    contradictory duplicate.
            resent = _seed_access(conn, "resentuser")
            _send_first_access(conn, resent, confirmed=True, ttl=dt.timedelta(hours=-1))
            assert access_status_for_usuario(conn, resent) == ACCESS_STATUS_EXPIRADO
            _send_first_access(conn, resent, confirmed=True)
            assert access_status_for_usuario(conn, resent) == ACCESS_STATUS_DISPONIBILIZADO
            assert conn.execute(
                "SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=? AND sent_at IS NOT NULL",
                (resent,),
            ).fetchone()[0] == 2, "both deliveries are on record; only the newest decides"

            # J. expired first-access token -> Expirado
            stale = _seed_access(conn, "staleuser")
            _send_first_access(conn, stale, confirmed=True, ttl=dt.timedelta(hours=-2))
            assert access_status_for_usuario(conn, stale) == ACCESS_STATUS_EXPIRADO


def test_a_password_reset_delivery_never_moves_the_onboarding_state(tmp_path):
    """Only first_access is onboarding. A reset e-mail to an Ativo account is
    not evidence about onboarding, and cannot drag it backwards."""
    with isolated_versioned_app_env(tmp_path, "b08-reset.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_id = _seed_access(conn, "resetuser", state=CREDENTIAL_STATE_PERSONAL)
            _raw, token_id = issue_password_token(
                conn, usuario_id, PURPOSE_PASSWORD_RESET
            )
            mark_password_token_sent(conn, token_id)
            conn.commit()
            assert access_status_for_usuario(conn, usuario_id) == ACCESS_STATUS_ATIVO


def test_a_leftover_legacy_switch_row_moves_no_pill(tmp_path):
    """The retired ``default_passwords_enabled`` setting decides nothing here.

    One account per credential state; a stale legacy row is written with both
    values, and every pill stays exactly where the credential puts it.
    """
    with isolated_versioned_app_env(tmp_path, "b08-defaults.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            pending = _seed_access(conn, "switchpending")
            delivered = _seed_access(conn, "switchdelivered")
            _send_first_access(conn, delivered, confirmed=True)
            applied = _seed_access(conn, "switchapplied", state=CREDENTIAL_STATE_DEFAULT)
            personal = _seed_access(conn, "switchpersonal", state=CREDENTIAL_STATE_PERSONAL)
            watched = [pending, delivered, applied, personal]
            expected = {
                pending: ACCESS_STATUS_PENDENTE,
                delivered: ACCESS_STATUS_DISPONIBILIZADO,
                applied: ACCESS_STATUS_ATIVO,
                personal: ACCESS_STATUS_ATIVO,
            }
            assert access_status_map(conn, watched) == expected

            for value in ("1", "0"):
                conn.execute(
                    "INSERT INTO configuracoes_app(chave,valor) VALUES('default_passwords_enabled',?)"
                    " ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                    (value,),
                )
                conn.commit()
                assert access_status_map(conn, watched) == expected


def test_derivation_reads_no_global_setting():
    """Structural guard for the test above: the switch is unreachable from here."""
    source = (PROJECT_ROOT / "app" / "access_onboarding.py").read_text(encoding="utf-8")
    assert "default_passwords_enabled" not in source.split('"""', 2)[2], (
        "the derivation reached for the shared-default switch"
    )
    assert "configuracoes_app" not in source


def test_status_is_not_derived_from_the_academic_aluno_status(tmp_path):
    """An Inativo student with a personal credential is still Ativo *access*."""
    with isolated_versioned_app_env(tmp_path, "b08-academic.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            row = conn.execute(
                "SELECT usuario_id FROM alunos WHERE usuario_id IS NOT NULL ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                pytest.skip("no linked student in the seeded database")
            usuario_id = int(row["usuario_id"])
            conn.execute("UPDATE alunos SET status='Inativo' WHERE usuario_id=?", (usuario_id,))
            set_usuario_password_hash(
                conn, usuario_id, hash_password("student-secret"),
                credential_state=CREDENTIAL_STATE_PERSONAL,
            )
            conn.commit()
            assert access_status_for_usuario(conn, usuario_id) == ACCESS_STATUS_ATIVO


# ------------------------------------------------------- SEND-PATH EVIDENCE


def test_only_a_confirmed_send_writes_the_durable_evidence(tmp_path):
    """``mark_password_token_sent`` is the single writer, and it refuses to
    resurrect a spent token."""
    with isolated_versioned_app_env(tmp_path, "b08-evidence.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_id = _seed_access(conn, "evidenceuser")

            _raw, token_id = issue_password_token(conn, usuario_id, PURPOSE_FIRST_ACCESS)
            conn.commit()
            assert conn.execute(
                "SELECT sent_at FROM senha_tokens WHERE id=?", (token_id,)
            ).fetchone()[0] is None, "issuing a token must not imply a send"

            assert mark_password_token_sent(conn, token_id) is True
            first = conn.execute(
                "SELECT sent_at FROM senha_tokens WHERE id=?", (token_id,)
            ).fetchone()[0]
            assert first is not None
            # Idempotent: a second confirmation does not overwrite the first.
            assert mark_password_token_sent(conn, token_id) is False
            assert conn.execute(
                "SELECT sent_at FROM senha_tokens WHERE id=?", (token_id,)
            ).fetchone()[0] == first

            # Invalidated tokens cannot acquire evidence after the fact.
            _raw2, dead_id = issue_password_token(conn, usuario_id, PURPOSE_FIRST_ACCESS)
            conn.execute(
                "UPDATE senha_tokens SET invalidated_at=datetime('now') WHERE id=?", (dead_id,)
            )
            conn.commit()
            assert mark_password_token_sent(conn, dead_id) is False


def test_the_send_path_marks_only_the_confirmed_branch():
    """Structural: the indeterminate and failure branches must not mark."""
    source = (PROJECT_ROOT / "app" / "password_email.py").read_text(encoding="utf-8")
    assert source.count("mark_password_token_sent(conn, token_id)") == 1
    marker = source.index("mark_password_token_sent(conn, token_id)")
    # The single call site sits after the whole except block, i.e. on the path
    # reached only when send_text_email did not raise.
    assert marker > source.index('return PasswordMailOutcome("failed"'), (
        "the confirmed-send marker is reachable from a failure branch"
    )
    assert marker > source.index('"indeterminate",'), (
        "the confirmed-send marker is reachable from the indeterminate branch"
    )


# --------------------------------------------------------------- PRESENTATION


def test_tones_are_all_existing_ds_semantic_tones():
    """No invented tone, no raw colour."""
    assert set(ACCESS_STATUS_TONES.values()) <= DS_STATUS_TONES


def test_tone_mapping_is_the_documented_one():
    assert status_tone("acesso", ACCESS_STATUS_PENDENTE) == "caution"
    assert status_tone("acesso", ACCESS_STATUS_DISPONIBILIZADO) == "info"
    assert status_tone("acesso", ACCESS_STATUS_ATIVO) == "positive"
    assert status_tone("acesso", ACCESS_STATUS_REVOGADO) == "negative"
    assert status_tone("acesso", ACCESS_STATUS_EXPIRADO) == "caution"


def test_ativo_shares_the_tone_every_other_sgaa_surface_uses():
    assert status_tone("acesso", ACCESS_STATUS_ATIVO) == status_tone("matriz", "Ativa")


def test_pendente_reuses_the_tone_the_same_word_already_has():
    assert status_tone("acesso", ACCESS_STATUS_PENDENTE) == status_tone(
        "requisicao", "Pendente"
    )


def test_labels_are_one_word_each():
    for state in EXPECTED_STATES:
        assert status_label("acesso", state) == state
        assert " " not in state, f"{state!r} is not one word"


def test_an_unknown_value_falls_back_without_inventing_a_state():
    assert status_tone("acesso", "") == "neutral"
    assert status_tone("acesso", "Enviado") == "neutral"
    assert status_label("acesso", "") == "-"


def test_template_renders_the_status_through_the_shared_owner():
    source = ACESSO_TEMPLATE.read_text(encoding="utf-8")
    assert "status_label('acesso', user.access_status)" in source
    assert "status_tone('acesso', user.access_status)" in source
    # No page-local ladder and no raw colour for the pill.
    assert "status-pill" not in source.split("{% block content %}")[0].replace(
        ".badge.status-pill primitive", ""
    ).replace("status-pill primitive from modern-style.css", ""), (
        "a page-local status-pill rule was introduced"
    )


def test_status_is_the_last_data_column():
    source = ACESSO_TEMPLATE.read_text(encoding="utf-8")
    header = source[source.index("cl.header(["):]
    header = header[: header.index("]) }}")]
    labels = re.findall(r"'text':\s*'([^']+)'", header)
    assert labels == ["Nome", "E-mail", "Matrícula / Turma", "Nível", "Perfil base", "Situação"]

    row = source[source.index("{{ cl.row(["):]
    row = row[: row.index("], {")]
    assert row.rindex("user.access_status") > row.rindex("user.tipo_label"), (
        "the status cell is not the last cell of the row"
    )


# Column geometry -- track count, flexibility, minima, the shared
# `.cell.status-col` contract and the derived scroll threshold -- is owned by
# tests/test_status_column_geometry_ui_b08.py. This suite stays on semantics.


def test_rendered_page_has_exactly_one_status_pill_per_row(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b08-render.db") as env:
        client = env["client"]
        login_admin(client)
        with main.app.app_context():
            conn = main.get_db_connection()
            _send_first_access(conn, _seed_access(conn, "renderdelivered"), confirmed=True)
            _seed_access(conn, "renderpending")
            _seed_access(conn, "renderpersonal", state=CREDENTIAL_STATE_PERSONAL)

        html = client.get("/admin/acesso?per_page=100").get_data(as_text=True)
        assert html.count('<div class="cell status-col">Situação</div>') == 1

        body = html[html.index('id="acesso-list"'):]
        body = body[: body.index("</div>\n</div>")] if "</div>\n</div>" in body else body
        rows = re.findall(r'role="listitem".*?(?=role="listitem"|\Z)', body, re.S)
        assert rows, "no rows rendered"
        for row in rows:
            pills = re.findall(r'class="badge status-badge status-pill status-(\w+)"', row)
            assert len(pills) == 1, f"expected exactly one status pill, found {pills}"
            assert pills[0] in DS_STATUS_TONES

        # The three seeded states are all visible, through the shared primitive.
        assert ">Pendente</span>" in html
        assert ">Disponibilizado</span>" in html
        assert ">Ativo</span>" in html


def test_rendered_page_introduces_no_raw_colour_for_the_status_column(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b08-colour.db") as env:
        login_admin(env["client"])
        html = env["client"].get("/admin/acesso").get_data(as_text=True)
        for pill in re.findall(r'<span class="badge status-badge status-pill[^>]*>', html):
            assert "style=" not in pill, f"inline colour on a status pill: {pill}"


# --------------------------------------------------- STATUS / ACTION COHERENCE


def test_revoked_access_is_excluded_from_the_list_and_refused_an_email(tmp_path):
    """The pill and the available action can never contradict each other.

    A revoked access is history kept for attribution: the active list excludes
    it by design, so Revogado is derivable and correct but not rendered here --
    and the send-access route refuses it outright, so nothing offers to e-mail
    an account as though it were active.
    """
    with isolated_versioned_app_env(tmp_path, "b08-revoked.db") as env:
        client = env["client"]
        login_admin(client)
        with main.app.app_context():
            conn = main.get_db_connection()
            usuario_id = _seed_access(conn, "revokeduser")
            set_usuario_access_active(conn, usuario_id, False)
            conn.commit()
            assert access_status_for_usuario(conn, usuario_id) == ACCESS_STATUS_REVOGADO

        html = client.get("/admin/acesso?per_page=100").get_data(as_text=True)
        assert f'data-user-id="{usuario_id}"' not in html

        response = client.post(
            f"/admin/acesso/{usuario_id}/senha-por-email", follow_redirects=False
        )
        assert response.status_code in (302, 303)
        with main.app.app_context():
            conn = main.get_db_connection()
            assert conn.execute(
                "SELECT COUNT(*) FROM senha_tokens WHERE usuario_id=?", (usuario_id,)
            ).fetchone()[0] == 0, "a revoked access was issued a password token"


def test_the_offered_email_action_always_matches_the_derived_state(tmp_path):
    """First-access semantics for the pre-onboarding states, reset for Ativo --
    including an applied default, which is Ativo and therefore gets a reset.

    Both the label and the derivation read ``usuario_credenciais.estado``, so
    this asserts the coupling that makes them unable to disagree.
    """
    with isolated_versioned_app_env(tmp_path, "b08-actions.db") as env:
        client = env["client"]
        login_admin(client)
        with main.app.app_context():
            conn = main.get_db_connection()
            pending = _seed_access(conn, "actionpending")
            delivered = _seed_access(conn, "actiondelivered")
            _send_first_access(conn, delivered, confirmed=True)
            expired = _seed_access(conn, "actionexpired")
            _send_first_access(conn, expired, confirmed=True, ttl=dt.timedelta(hours=-1))
            personal = _seed_access(conn, "actionpersonal", state=CREDENTIAL_STATE_PERSONAL)
            applied = _seed_access(conn, "actionapplied", state=CREDENTIAL_STATE_DEFAULT)
            expected_states = access_status_map(
                conn, [pending, delivered, expired, personal, applied]
            )

        assert expected_states == {
            pending: ACCESS_STATUS_PENDENTE,
            delivered: ACCESS_STATUS_DISPONIBILIZADO,
            expired: ACCESS_STATUS_EXPIRADO,
            personal: ACCESS_STATUS_ATIVO,
            applied: ACCESS_STATUS_ATIVO,
        }

        html = client.get("/admin/acesso?per_page=100").get_data(as_text=True)
        payload = re.search(
            r'<script id="access-users-data" type="application/json">(.*?)</script>',
            html, re.S,
        ).group(1)
        import json

        users = json.loads(payload)

        first_access_states = {
            ACCESS_STATUS_PENDENTE,
            ACCESS_STATUS_DISPONIBILIZADO,
            ACCESS_STATUS_EXPIRADO,
        }
        for usuario_id, state in expected_states.items():
            label = users[str(usuario_id)]["emailActionLabel"]
            if state in first_access_states:
                assert label == "Enviar acesso", f"{state} offered {label!r}"
            else:
                assert label == "Redefinir por e-mail", f"{state} offered {label!r}"


def test_root_admin_shows_one_truthful_pill_and_no_revoke(tmp_path):
    """Root is protected: truthful state, one pill, no break-glass hint."""
    with isolated_versioned_app_env(tmp_path, "b08-root.db") as env:
        client = env["client"]
        login_admin(client)
        from app.root_admin import resolve_root_admin_id

        with main.app.app_context():
            conn = main.get_db_connection()
            root_id = int(resolve_root_admin_id(conn))
            expected = access_status_for_usuario(conn, root_id)
        assert expected in EXPECTED_STATES

        html = client.get("/admin/acesso?per_page=100").get_data(as_text=True)
        row = html[html.index(f'data-user-id="{root_id}"'):]
        row = row[: row.index("role=\"listitem\"")] if "role=\"listitem\"" in row else row
        pills = re.findall(r'class="badge status-badge status-pill status-(\w+)"', row)
        assert len(pills) == 1, f"root row rendered {len(pills)} pills"
        assert f">{expected}</span>" in row

        payload = re.search(
            r'<script id="access-users-data" type="application/json">(.*?)</script>',
            html, re.S,
        ).group(1)
        import json

        assert json.loads(payload)[str(root_id)]["isRootAdmin"] is True
        assert 'data-delete-url=""' in row or "data-delete-url" not in row

        # No master-key vocabulary reaches the page.
        lowered = html.lower()
        for forbidden in ("master", "break-glass", "breakglass", "chave mestra"):
            assert forbidden not in lowered


def test_read_only_admin_still_sees_the_column_without_write_actions(tmp_path):
    """RBAC is unaffected: the status is information, not an action."""
    with isolated_versioned_app_env(tmp_path, "b08-rbac.db") as env:
        client = env["client"]
        login_admin(client)
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute(
                "INSERT INTO usuarios_permissoes_acesso(usuario_id,recurso,escopo)"
                " VALUES(?, 'acesso', 'view')"
                " ON CONFLICT(usuario_id,recurso) DO UPDATE SET escopo='view'",
                (1,),
            )
            conn.commit()
        response = client.get("/admin/acesso?per_page=100")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # The column is still there, and still populated.
        assert '<div class="cell status-col">Situação</div>' in html
        pills = re.findall(r'class="badge status-badge status-pill status-(\w+)"', html)
        assert pills and set(pills) <= DS_STATUS_TONES
        # ...but no write affordance was granted by adding it. The action-bar
        # buttons are gated on auth_can('acesso', 'full'), so none is emitted.
        assert '<button type="button" class="act-btn danger" data-action="delete"' not in html
        assert '<button type="button" class="act-btn" data-action="email"' not in html


def test_canonical_database_is_never_written_by_this_suite():
    canonical = PROJECT_ROOT / "database.db"
    if not canonical.exists():
        pytest.skip("no canonical database present in this checkout")
    probe = sqlite3.connect(f"file:{canonical.as_posix()}?mode=ro", uri=True)
    try:
        version = probe.execute("PRAGMA user_version").fetchone()[0]
    finally:
        probe.close()
    # The canonical database is not migrated to v11 by this front.
    # Canonical was migrated to v11 on 2026-09-24 (authorised, UI-CP1).
    assert version in (9, 10, 11)
