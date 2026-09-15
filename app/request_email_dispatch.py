"""Batch orchestration for request-decision e-mails.

One engine, no separate individual path: a single selected request is simply a
batch of one request / one student / one e-mail, through the same grouping,
renderer, persistence and transport.

Isolation guarantee
-------------------
Every outbound message is built from exactly one bucket of
:func:`group_events_by_student`, so one student's decisions can never reach
another student's message.

Failure posture
---------------
External mail is not part of the academic-decision transaction.  Each student's
e-mail is attempted independently; one student's failure never blocks another's.
Only events belonging to a *confirmed* successful send lose pending status.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from app.request_email_notifications import (
    attach_events_to_send,
    group_events_by_student,
    load_pending_events,
    mark_events_sent,
)
from app.request_email_render import PlaceholderError, render_student_email
from app.services.mail_service import (
    MailMessage,
    MailTransportError,
    is_valid_email,
    send_text_email,
)


def compute_idempotency_key(aluno_id: int, event_ids) -> str:
    """Stable identity for "this exact student + this exact set of decisions".

    A duplicate POST (double click, browser retry, reload) reproduces the same
    key, and the UNIQUE constraint on ``email_envios.idempotency_key`` turns the
    second attempt into a no-op instead of a second student e-mail.
    """
    payload = json.dumps(
        {"aluno_id": int(aluno_id), "events": sorted(int(i) for i in event_ids)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_plan(conn: sqlite3.Connection, requisicao_ids, template) -> list[dict]:
    """Render one outgoing message per student without sending anything.

    Powers both the confirmation/preview step and the send itself, so what the
    administrator approves is what the transport receives.
    """
    events = load_pending_events(conn, requisicao_ids)
    grouped = group_events_by_student(events)
    plan: list[dict] = []
    for aluno_id, student_events in grouped.items():
        first = student_events[0]
        recipient = str(first["aluno_email"] or "").strip()
        entry: dict = {
            "aluno_id": aluno_id,
            "aluno_nome": str(first["aluno_nome"] or ""),
            "aluno_matricula": str(first["aluno_matricula"] or ""),
            "destinatario": recipient,
            "event_ids": [int(event["id"]) for event in student_events],
            "requisicao_ids": [int(event["requisicao_id"]) for event in student_events],
            "quantidade": len(student_events),
            "assunto": "",
            "corpo": "",
            "blocked": "",
        }
        if not is_valid_email(recipient):
            entry["blocked"] = (
                "Aluno sem e-mail cadastrado."
                if not recipient
                else "E-mail do aluno é inválido."
            )
            plan.append(entry)
            continue
        try:
            assunto, corpo = render_student_email(
                assunto=template["assunto"],
                corpo=template["texto"],
                events=student_events,
                aluno_nome=first["aluno_nome"],
                aluno_matricula=first["aluno_matricula"],
            )
        except PlaceholderError as exc:
            entry["blocked"] = str(exc)
            plan.append(entry)
            continue
        entry["assunto"] = assunto
        entry["corpo"] = corpo
        plan.append(entry)
    return plan


#: A prior attempt in one of these states was CONFIRMED delivered. Never resend.
_SETTLED_SENT_STATUSES = ("sent",)

#: A prior attempt in one of these states has an UNKNOWN outcome: the message
#: may already be in the student's inbox.  Resending could duplicate it, so the
#: send action holds instead, and only an explicit per-student acknowledgement
#: from the administrator releases it.
_UNRESOLVED_STATUSES = ("sending", "indeterminate")

UNRESOLVED_HOLD_DETAIL = (
    "A tentativa anterior não foi confirmada pelo provedor: o e-mail pode já ter "
    "sido entregue. Verifique a caixa de itens enviados e confirme o reenvio."
)


def _existing_send(conn: sqlite3.Connection, idempotency_key: str):
    return conn.execute(
        "SELECT id,status FROM email_envios WHERE idempotency_key=?",
        (idempotency_key,),
    ).fetchone()


def unresolved_student_ids(conn: sqlite3.Connection, plan) -> set[int]:
    """Students whose exact planned send already has an unresolved attempt.

    Lets the confirmation step warn *before* the administrator commits, instead
    of discovering the hold only in the result line.
    """
    unresolved: set[int] = set()
    for entry in plan:
        if entry["blocked"]:
            continue
        existing = _existing_send(
            conn, compute_idempotency_key(entry["aluno_id"], entry["event_ids"])
        )
        if existing is not None and str(existing["status"]) in _UNRESOLVED_STATUSES:
            unresolved.add(int(entry["aluno_id"]))
    return unresolved


def dispatch(
    conn: sqlite3.Connection, plan, template, *, confirmed_resend=()
) -> dict:
    """Attempt one e-mail per planned student. Returns per-student outcomes.

    ``confirmed_resend`` carries the ``aluno_id`` values for which the
    administrator has explicitly acknowledged that a previous attempt had an
    unknown outcome and that a duplicate is acceptable.  Without that
    acknowledgement an unresolved attempt is *held*, not retried: a definite
    failure is safe to retry, an unknown one is not.
    """
    outcomes: list[dict] = []
    sent_count = failed_count = skipped_count = held_count = 0
    acknowledged = {int(value) for value in confirmed_resend}

    for entry in plan:
        result: dict = {
            "aluno_id": entry["aluno_id"],
            "aluno_nome": entry["aluno_nome"],
            "destinatario": entry["destinatario"],
            "quantidade": entry["quantidade"],
            "requisicao_ids": entry["requisicao_ids"],
        }
        if entry["blocked"]:
            result.update(status="failed", detail=entry["blocked"])
            outcomes.append(result)
            failed_count += 1
            continue

        key = compute_idempotency_key(entry["aluno_id"], entry["event_ids"])
        existing = _existing_send(conn, key)
        existing_status = str(existing["status"]) if existing is not None else ""

        if existing_status in _SETTLED_SENT_STATUSES:
            # Confirmed delivered for this exact set: never send it again.
            result.update(
                status="skipped",
                detail="Este e-mail já foi enviado anteriormente.",
                email_envio_id=int(existing["id"]),
            )
            outcomes.append(result)
            skipped_count += 1
            continue

        if (
            existing_status in _UNRESOLVED_STATUSES
            and int(entry["aluno_id"]) not in acknowledged
        ):
            # Outcome unknown. Retrying here is exactly how a student ends up
            # with two copies of the same decision e-mail, so stop and hand the
            # decision back to a human.
            result.update(
                status="held",
                detail=UNRESOLVED_HOLD_DETAIL,
                email_envio_id=int(existing["id"]),
                requer_confirmacao=True,
            )
            outcomes.append(result)
            held_count += 1
            continue

        if existing is None:
            cursor = conn.execute(
                """
                INSERT INTO email_envios
                    (aluno_id,destinatario,preset_id,preset_titulo,assunto,corpo,
                     status,tentativas,idempotency_key)
                VALUES (?,?,?,?,?,?, 'sending', 1, ?)
                """,
                (
                    entry["aluno_id"],
                    entry["destinatario"],
                    template.get("id"),
                    template.get("titulo"),
                    entry["assunto"],
                    entry["corpo"],
                    key,
                ),
            )
            envio_id = int(cursor.lastrowid)
        else:
            envio_id = int(existing["id"])
            # Retry re-sends the persisted snapshot, not a re-render.
            conn.execute(
                "UPDATE email_envios"
                "   SET status='sending', tentativas=tentativas+1, ultimo_erro=NULL"
                " WHERE id=?",
                (envio_id,),
            )
        # Link the still-pending generations to THIS attempt before the provider
        # is contacted, so a failure is attributable to this exact decision set
        # rather than to the student in general.
        attach_events_to_send(
            conn, event_ids=entry["event_ids"], email_envio_id=envio_id
        )
        conn.commit()

        try:
            provider = send_text_email(
                conn,
                MailMessage(
                    to_address=entry["destinatario"],
                    subject=entry["assunto"],
                    body_text=entry["corpo"],
                ),
            )
        except MailTransportError as exc:
            status = "indeterminate" if exc.indeterminate else "failed"
            conn.execute(
                "UPDATE email_envios SET status=?, ultimo_erro=? WHERE id=?",
                (status, str(exc), envio_id),
            )
            conn.commit()
            result.update(
                status=status,
                detail=str(exc),
                email_envio_id=envio_id,
            )
            outcomes.append(result)
            failed_count += 1
            continue

        conn.execute(
            "UPDATE email_envios"
            "   SET status='sent', enviado_em=datetime('now'), ultimo_erro=NULL,"
            "       provider_message_id=? WHERE id=?",
            (str(provider.get("http_status") or ""), envio_id),
        )
        mark_events_sent(conn, event_ids=entry["event_ids"], email_envio_id=envio_id)
        conn.commit()
        result.update(status="sent", email_envio_id=envio_id)
        outcomes.append(result)
        sent_count += 1

    return {
        "outcomes": outcomes,
        "sent": sent_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "held": held_count,
        "total": len(plan),
    }


def summarize(result: dict) -> str:
    """UI feedback, e.g. "2 e-mails enviados. 1 não pôde ser enviado."."""
    parts: list[str] = []
    sent, failed, skipped = result["sent"], result["failed"], result["skipped"]
    held = result.get("held", 0)
    if sent:
        parts.append(f"{sent} e-mail{'s' if sent > 1 else ''} enviado{'s' if sent > 1 else ''}.")
    if failed:
        parts.append(
            f"{failed} não pôde ser enviado." if failed == 1
            else f"{failed} não puderam ser enviados."
        )
    if skipped:
        parts.append(
            f"{skipped} já havia sido enviado." if skipped == 1
            else f"{skipped} já haviam sido enviados."
        )
    if held:
        parts.append(
            f"{held} aguarda confirmação de reenvio." if held == 1
            else f"{held} aguardam confirmação de reenvio."
        )
    return " ".join(parts) or "Nenhum e-mail foi enviado."


__all__ = [
    "UNRESOLVED_HOLD_DETAIL",
    "build_plan",
    "compute_idempotency_key",
    "dispatch",
    "summarize",
    "unresolved_student_ids",
]
