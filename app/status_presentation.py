"""Authoritative domain-status -> Design System semantic tone mapping.

One owner for the question "what does this status look like".

Before this module every surface answered it locally: `admin_requisicoes.html`
and `aluno_minhas_requisicoes.html` each carried their own copy of the
Requisições ladder (and they had already drifted -- the aluno copy had no
`Deferida Parcialmente` branch at all), while `admin_matrizes.html` carried a
*pasted copy of the Requisições ladder* to classify Matriz statuses, which is
why `Vigente` matched none of its branches and fell through to `neutral`,
rendering identically to `Rascunho`.

The tones are the ones `static/css/modern-style.css` already publishes as
`.badge.status-pill.status-*`: positive, neutral, caution, negative, info. No
colour is defined here and none may be. This module chooses which *existing*
named tone a status means; the Design System decides what that tone looks like.

Deliberately not under ``app/views/**``: that tree is scanned by
``utils/messages.py`` for user-facing literals, and these labels are
presentation vocabulary, not editable messages.
"""

from __future__ import annotations


#: The five semantic tones published by the Design System status pill.
DS_STATUS_TONES = frozenset(
    {"positive", "neutral", "caution", "negative", "info"}
)

#: Tone used when a status is not recognised. Neutral is the only honest
#: answer: an unknown value carries no semantics to signal.
FALLBACK_TONE = "neutral"

DOMAIN_REQUISICAO = "requisicao"
DOMAIN_MATRIZ = "matriz"
DOMAIN_ACESSO = "acesso"


# ---------------------------------------------------------------------------
# Requisições
# ---------------------------------------------------------------------------
#
# Canonical statuses are ``app.prod1_schema.REQUEST_STATUSES``, which is the
# same set the ``requisicoes.status`` CHECK constraint enforces.
#
# Semantic categories, taken from the domain code rather than from taste:
#
#   open / no decision yet    Pendente, Devolvida
#       Both are non-final, both are student-editable
#       (``app.requisition_policy.can_student_edit_requisition``) and both are
#       in ``app.request_email_notifications.NON_NOTIFYING_STATUSES``.
#       -> caution, the DS tone for "waiting on someone".
#
#   final decision, granted   Deferida, Deferida Parcialmente
#       Both in ``app.versioning.request_history.APPROVED_STATUSES``, but a
#       full grant and a partial grant are different outcomes to the student,
#       so they do not share a tone. Full grant takes the positive tone;
#       the partial grant takes ``info``, the only remaining non-neutral tone
#       and the right reading for a qualified/intermediate outcome.
#
#   terminal, nothing granted Indeferida, Encerrada
#       A denial and an administrative closure. Same category -- the request
#       is over and no hours were awarded -- and the admin UI already groups
#       them (the "Encerrar" action carries `btn-indeferir` and the same
#       circle-x icon). The distinction is carried by the pill text.
#       -> negative.
#
REQUEST_STATUS_TONES: dict[str, str] = {
    "Pendente": "caution",
    "Devolvida": "caution",
    "Deferida": "positive",
    "Deferida Parcialmente": "info",
    "Indeferida": "negative",
    "Encerrada": "negative",
}

#: Lowercased spellings accepted for each canonical status. These preserve the
#: tolerance the two list templates already had -- legacy rows and imported
#: data are not guaranteed to use the canonical casing or wording.
REQUEST_STATUS_ALIASES: dict[str, str] = {
    "pendente": "Pendente",
    "aguardando": "Pendente",
    "pending": "Pendente",
    "devolvida": "Devolvida",
    "devolvido": "Devolvida",
    "deferida": "Deferida",
    "deferido": "Deferida",
    "aprovada": "Deferida",
    "aprovado": "Deferida",
    "approved": "Deferida",
    "deferida parcialmente": "Deferida Parcialmente",
    "deferido parcialmente": "Deferida Parcialmente",
    "parcialmente deferida": "Deferida Parcialmente",
    "parcialmente deferido": "Deferida Parcialmente",
    "partially approved": "Deferida Parcialmente",
    "indeferida": "Indeferida",
    "indeferido": "Indeferida",
    "rejeitada": "Indeferida",
    "rejeitado": "Indeferida",
    "encerrada": "Encerrada",
    "encerrado": "Encerrada",
    "closed": "Encerrada",
}


# ---------------------------------------------------------------------------
# Matrizes
# ---------------------------------------------------------------------------
#
# Canonical statuses are the ``matrizes_atividades.status`` CHECK constraint:
# rascunho, vigente, encerrada, ativa, inativa. The Matriz form and the list
# filter only offer the first three; ativa/inativa are reachable only through
# stored data, and are mapped here so they cannot fall through to the unknown
# branch.
#
#   rascunho   not yet the effective matrix -- draft, informational -> neutral
#   vigente    the currently effective matrix -> positive
#   encerrada  retired, no longer usable -> negative
#   ativa      active, same reading as every other SGAA active/inactive pair
#              (Alunos, Cursos, Turmas all use positive/neutral) -> positive
#   inativa    inactive is not an error, it is an absence -> neutral
#
MATRIZ_STATUS_TONES: dict[str, str] = {
    "Rascunho": "neutral",
    "Vigente": "positive",
    "Encerrada": "negative",
    "Ativa": "positive",
    "Inativa": "neutral",
}

#: Matriz surfaces hand this module either the stored key (``vigente``, from
#: the view layer) or the rendered label (``Vigente``, from the list payload,
#: which has already been through ``_matriz_status_label``). Both normalise to
#: the same canonical entry.
MATRIZ_STATUS_ALIASES: dict[str, str] = {
    "rascunho": "Rascunho",
    "vigente": "Vigente",
    "encerrada": "Encerrada",
    "ativa": "Ativa",
    "inativa": "Inativa",
}


# ---------------------------------------------------------------------------
# Acesso (access / onboarding lifecycle)
# ---------------------------------------------------------------------------
#
# These are NOT stored values: there is no ``status`` column to read. The five
# states are derived from durable authentication evidence by
# ``app.access_onboarding.derive_access_status``, which owns their meaning. The
# constants live here because this module is the status *vocabulary* owner and,
# per the note at the top of the file, is deliberately outside ``app/views/**``
# where user-facing literals are catalogued.
#
# Tones are taken from what this DS already says with them elsewhere, not from
# taste:
#
#   Pendente         caution. The very same word is already `caution` in the
#                    Requisições ladder above, for the very same reason:
#                    waiting on somebody. Reusing it is the consistent answer.
#
#   Disponibilizado  info. A real step forward that is not yet the finish line
#                    -- exactly the qualified/intermediate reading `info`
#                    already carries for `Deferida Parcialmente`.
#
#   Ativo            positive. Every other SGAA surface maps Ativo/Ativa to
#                    positive (Alunos, Cursos, Turmas, Matrizes).
#
#   Revogado         negative. Terminal and nothing granted, the category
#                    `Indeferida`/`Encerrada` occupy.
#
#   Expirado         caution, NOT negative. Nothing is terminal here: the
#                    account is still perfectly onboardable, a first-access
#                    link simply needs sending again. That is "waiting on
#                    somebody" -- an administrator this time -- which is what
#                    caution means in this DS. `Pendente` and `Devolvida`
#                    already share caution for the same reason, so two waiting
#                    states on one tone is the established pattern, and the
#                    pill text carries the distinction.
#
ACCESS_STATUS_PENDENTE = "Pendente"
ACCESS_STATUS_DISPONIBILIZADO = "Disponibilizado"
ACCESS_STATUS_ATIVO = "Ativo"
ACCESS_STATUS_REVOGADO = "Revogado"
ACCESS_STATUS_EXPIRADO = "Expirado"

ACCESS_STATUS_TONES: dict[str, str] = {
    ACCESS_STATUS_PENDENTE: "caution",
    ACCESS_STATUS_DISPONIBILIZADO: "info",
    ACCESS_STATUS_ATIVO: "positive",
    ACCESS_STATUS_REVOGADO: "negative",
    ACCESS_STATUS_EXPIRADO: "caution",
}

#: Only the canonical lowercase spellings. Unlike Requisições and Matrizes,
#: these values are computed on every read rather than stored, so there is no
#: legacy or imported data to be tolerant of.
ACCESS_STATUS_ALIASES: dict[str, str] = {
    "pendente": ACCESS_STATUS_PENDENTE,
    "disponibilizado": ACCESS_STATUS_DISPONIBILIZADO,
    "ativo": ACCESS_STATUS_ATIVO,
    "revogado": ACCESS_STATUS_REVOGADO,
    "expirado": ACCESS_STATUS_EXPIRADO,
}


_DOMAINS: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    DOMAIN_REQUISICAO: (REQUEST_STATUS_TONES, REQUEST_STATUS_ALIASES),
    DOMAIN_MATRIZ: (MATRIZ_STATUS_TONES, MATRIZ_STATUS_ALIASES),
    DOMAIN_ACESSO: (ACCESS_STATUS_TONES, ACCESS_STATUS_ALIASES),
}


def _tables(domain: str) -> tuple[dict[str, str], dict[str, str]]:
    try:
        return _DOMAINS[domain]
    except KeyError:
        raise ValueError(
            f"unknown status domain {domain!r}; "
            f"expected one of {sorted(_DOMAINS)}"
        ) from None


def canonical_status(domain: str, status) -> str | None:
    """Return the canonical status name, or ``None`` when unrecognised."""
    tones, aliases = _tables(domain)
    raw = str(status or "").strip()
    if not raw:
        return None
    if raw in tones:
        return raw
    return aliases.get(raw.casefold())


def status_tone(domain: str, status) -> str:
    """Return the Design System semantic tone for a domain status.

    The returned value is always a member of :data:`DS_STATUS_TONES`, so a
    template may interpolate it straight into ``status-{{ tone }}``.
    """
    tones, _ = _tables(domain)
    canonical = canonical_status(domain, status)
    if canonical is None:
        return FALLBACK_TONE
    return tones[canonical]


def status_label(domain: str, status) -> str:
    """Return the canonical display label, falling back to the raw value.

    An unrecognised non-empty value is shown verbatim rather than hidden --
    the same thing both list templates already did.
    """
    canonical = canonical_status(domain, status)
    if canonical is not None:
        return canonical
    raw = str(status or "").strip()
    return raw or "-"
