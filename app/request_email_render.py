"""Deterministic placeholder renderer for request-decision e-mails.

Security posture
----------------
Stored preset text is **data, never code**.  Rendering is a single regex pass
that replaces a closed vocabulary of ``{placeholder}`` tokens with pre-computed
strings.  No Jinja, no ``eval``, no format-string evaluation, no attribute
traversal -- a preset containing ``{{ config }}`` or ``{__class__}`` renders as
an unknown-placeholder rejection, not as code.

Unknown placeholders are rejected loudly (:class:`PlaceholderError`) at preset
save time and again at preview/send time, so a typo can never reach a student as
broken literal text.
"""

from __future__ import annotations

import datetime
import re

from app.presentation import format_date_ptbr

#: Scalar placeholders -- safe anywhere, including the subject line.
SCALAR_PLACEHOLDERS = (
    "saudacao",
    "aluno.nome",
    "aluno.primeironome",
    "aluno.matricula",
    "data.inicio",
    "data.fim",
    "quantidade_requisicoes",
)

#: Block placeholder -- system-generated, body only, never allowed in a subject.
BLOCK_PLACEHOLDER = "requisicoes"

BODY_PLACEHOLDERS = (*SCALAR_PLACEHOLDERS, BLOCK_PLACEHOLDER)

#: Human-facing help shown beside the editor in Pré-definições.
PLACEHOLDER_HELP = (
    ("{saudacao}", "Bom dia / Boa tarde / Boa noite, conforme o horário do envio."),
    ("{aluno.nome}", "Nome completo do aluno."),
    ("{aluno.primeironome}", "Primeiro nome do aluno."),
    ("{aluno.matricula}", "Matrícula do aluno."),
    ("{data.inicio}", "Data da requisição mais antiga incluída no e-mail."),
    ("{data.fim}", "Data da requisição mais recente incluída no e-mail."),
    ("{quantidade_requisicoes}", "Quantidade de requisições incluídas no e-mail."),
    (
        "{requisicoes}",
        "Insere o detalhamento das requisições selecionadas para o aluno.",
    ),
)

_TOKEN_RE = re.compile(r"\{([^{}]*)\}")

# Greeting boundaries, local SGAA time. Documented and directly tested.
#   00:00-11:59 -> Bom dia
#   12:00-17:59 -> Boa tarde
#   18:00-23:59 -> Boa noite
_MORNING_END = 12
_AFTERNOON_END = 18


class PlaceholderError(ValueError):
    """A template referenced a placeholder outside the supported vocabulary."""


def greeting_for(moment: datetime.datetime | None = None) -> str:
    """Greeting computed at send/preparation time, never persisted at decision."""
    now = moment or datetime.datetime.now()
    if now.hour < _MORNING_END:
        return "Bom dia"
    if now.hour < _AFTERNOON_END:
        return "Boa tarde"
    return "Boa noite"


def first_name(full_name: str | None) -> str:
    """First meaningful token of the authoritative name (never mutates storage)."""
    for token in str(full_name or "").replace("\t", " ").split(" "):
        cleaned = token.strip()
        if cleaned:
            return cleaned
    return ""


def _format_hours(value) -> str:
    if value is None:
        return ""
    number = float(value)
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def validate_template(text: str, *, allow_block: bool = True) -> None:
    """Reject unknown placeholders; reject ``{requisicoes}`` in subjects."""
    allowed = set(BODY_PLACEHOLDERS) if allow_block else set(SCALAR_PLACEHOLDERS)
    for token in _TOKEN_RE.findall(str(text or "")):
        name = token.strip()
        if name in allowed:
            continue
        if name == BLOCK_PLACEHOLDER and not allow_block:
            raise PlaceholderError(
                "{requisicoes} não pode ser usado no assunto do e-mail."
            )
        raise PlaceholderError(f"Placeholder desconhecido: {{{name}}}")


def render_request_block(events) -> str:
    """System-owned detail block: one entry per included decision, exactly once.

    Deliberately not a template loop language -- the administrator owns the
    surrounding prose, the system owns this.  Justification text is read from the
    *decision snapshot*, never from the current preset, so editing a
    justification preset can never rewrite what a past decision said.
    """
    lines: list[str] = []
    for event in events:
        lines.append(f"Requisição nº {event['requisicao_id']}")
        lines.append(f"  Data da solicitação: {format_date_ptbr(event['data_solicitacao'])}")
        if event["atividade_nome"]:
            lines.append(f"  Atividade: {event['atividade_nome']}")
        if (event["nome_evento"] or "").strip():
            lines.append(f"  Evento: {str(event['nome_evento']).strip()}")
        lines.append(f"  Resultado: {event['status_decisao']}")
        lines.append(f"  Horas solicitadas: {_format_hours(event['horas_solicitadas'])}")
        status = str(event["status_decisao"])
        if status == "Deferida Parcialmente" and event["horas_deferidas"] is not None:
            lines.append(f"  Horas deferidas: {_format_hours(event['horas_deferidas'])}")
        elif status == "Deferida":
            lines.append(f"  Horas deferidas: {_format_hours(event['horas_solicitadas'])}")
        # Full deferment must not emit an empty "Justificativa:" label.
        justification = (event["justificativa"] or "").strip()
        if justification and status in ("Deferida Parcialmente", "Indeferida"):
            lines.append(f"  Justificativa: {justification}")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_context(events, *, aluno_nome, aluno_matricula, moment=None) -> dict[str, str]:
    """Placeholder values for exactly one student's outgoing e-mail."""
    dates = sorted(str(event["data_solicitacao"] or "") for event in events)
    return {
        "saudacao": greeting_for(moment),
        "aluno.nome": str(aluno_nome or ""),
        "aluno.primeironome": first_name(aluno_nome),
        "aluno.matricula": str(aluno_matricula or ""),
        # Same-day selections legitimately collapse to one date; no fake range.
        "data.inicio": format_date_ptbr(dates[0]) if dates else "",
        "data.fim": format_date_ptbr(dates[-1]) if dates else "",
        "quantidade_requisicoes": str(len(events)),
        BLOCK_PLACEHOLDER: render_request_block(events),
    }


def render_template(text: str, context: dict[str, str], *, allow_block: bool = True) -> str:
    """Single-pass token substitution over a closed vocabulary."""
    validate_template(text, allow_block=allow_block)
    allowed = set(BODY_PLACEHOLDERS) if allow_block else set(SCALAR_PLACEHOLDERS)

    def _replace(match: re.Match) -> str:
        name = match.group(1).strip()
        if name not in allowed:
            raise PlaceholderError(f"Placeholder desconhecido: {{{name}}}")
        return context.get(name, "")

    return _TOKEN_RE.sub(_replace, str(text or ""))


def render_student_email(
    *, assunto: str, corpo: str, events, aluno_nome, aluno_matricula, moment=None
) -> tuple[str, str]:
    """Render one student's subject/body from that student's events only."""
    context = build_context(
        events,
        aluno_nome=aluno_nome,
        aluno_matricula=aluno_matricula,
        moment=moment,
    )
    return (
        render_template(assunto, context, allow_block=False),
        render_template(corpo, context, allow_block=True),
    )


__all__ = [
    "BLOCK_PLACEHOLDER",
    "BODY_PLACEHOLDERS",
    "PLACEHOLDER_HELP",
    "PlaceholderError",
    "SCALAR_PLACEHOLDERS",
    "build_context",
    "first_name",
    "greeting_for",
    "render_request_block",
    "render_student_email",
    "render_template",
    "validate_template",
]
