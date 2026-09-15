"""``app/services/mail_service.py`` is a GENERIC transport.

It is the designated foundation for first-access and password-recovery e-mail
(see ``docs/mail/AUTH_EMAIL_EXTENSION_POINT.md``).  That only holds if it stays
free of Requisições concepts, so the boundary is asserted structurally rather
than trusted to a docstring: a future consumer must be able to call it with
nothing but a recipient, a subject and a body.
"""

from __future__ import annotations

import ast
import inspect
import sqlite3
from pathlib import Path

import pytest

import app.services.mail_service as mail_service
from app.services.mail_service import (
    MailMessage,
    MailTransportError,
    is_valid_email,
    sanitize_provider_error,
    send_text_email,
)

MODULE_PATH = Path(mail_service.__file__)
SOURCE = MODULE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

#: Vocabulary that would couple the transport to the academic domain.
FORBIDDEN_DOMAIN_TERMS = (
    "requisicao",
    "requisicoes",
    "preset",
    "deferida",
    "indeferida",
    "aluno",
    "decision_event",
    "email_eventos",
    "email_envios",
    "justificativa",
    "matricula",
)


def test_message_contract_is_only_recipient_subject_body():
    fields = [field.name for field in MailMessage.__dataclass_fields__.values()]
    assert fields == ["to_address", "subject", "body_text"]


def test_message_contract_is_immutable():
    message = MailMessage(to_address="a@b.com", subject="s", body_text="b")
    with pytest.raises(Exception):
        message.to_address = "c@d.com"  # frozen dataclass


def test_send_signature_takes_no_domain_arguments():
    signature = inspect.signature(send_text_email)
    assert list(signature.parameters) == ["conn", "message"]


def _code_tokens() -> set[str]:
    """Every identifier and string literal in the module, minus docstrings.

    Prose is excluded deliberately: the module docstring legitimately says what
    the transport is *not* coupled to ("no request ids, no presets"), and that
    sentence must not read as coupling.
    """
    docstrings = set()
    for node in ast.walk(TREE):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)

    tokens: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Name):
            tokens.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            tokens.add(node.attr.lower())
        elif isinstance(node, ast.arg):
            tokens.add(node.arg.lower())
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            tokens.add(node.name.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                tokens.add(node.value.lower())
    return tokens


def test_module_code_carries_no_requisicoes_vocabulary():
    tokens = _code_tokens()
    offenders = sorted(
        {
            term
            for term in FORBIDDEN_DOMAIN_TERMS
            for token in tokens
            if term in token
        }
    )
    assert offenders == [], (
        "mail_service must stay generic; found domain coupling in code: %r"
        % (offenders,)
    )


def test_docstring_disclaimer_is_the_only_place_domain_terms_appear():
    """Belt and braces: the terms exist in the file, but only as prose."""
    assert "presets" in SOURCE.lower()
    assert "presets" not in " ".join(sorted(_code_tokens()))


def test_module_imports_nothing_from_the_request_email_feature():
    imported: list[str] = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not [name for name in imported if "request_email" in name], imported
    assert not [name for name in imported if name.startswith("app.views")], imported


def test_transport_is_reusable_by_a_caller_that_has_no_database_rows():
    """A future auth consumer passes only a message; readiness is the only gate."""
    calls: list[dict] = []

    def fake_status(conn):
        return {"ready": True, "reason": "", "message": "", "account_email": "x@y.z"}

    original_status = mail_service.mail_transport_status
    original_token = mail_service.get_authenticated_access_token
    original_send = mail_service.send_mail_with_access_token
    mail_service.mail_transport_status = fake_status
    mail_service.get_authenticated_access_token = lambda conn, provider: ("tok", "x@y.z")
    mail_service.send_mail_with_access_token = lambda **kw: (
        calls.append(kw) or {"status": "sent", "http_status": 202}
    )
    try:
        result = send_text_email(
            sqlite3.connect(":memory:"),
            MailMessage(
                to_address="novo.aluno@ex.com",
                subject="Defina sua senha de acesso",
                body_text="Use o link de uso único para criar sua senha.",
            ),
        )
    finally:
        mail_service.mail_transport_status = original_status
        mail_service.get_authenticated_access_token = original_token
        mail_service.send_mail_with_access_token = original_send

    assert result["http_status"] == 202
    assert calls[0]["to_address"] == "novo.aluno@ex.com"
    assert calls[0]["subject"] == "Defina sua senha de acesso"
    # No From override: Graph stamps the authenticated mailbox.
    assert "from_address" not in calls[0]


def test_invalid_recipient_is_rejected_before_any_provider_contact():
    calls: list[dict] = []
    original_send = mail_service.send_mail_with_access_token
    mail_service.send_mail_with_access_token = lambda **kw: calls.append(kw)
    try:
        with pytest.raises(MailTransportError) as excinfo:
            send_text_email(
                sqlite3.connect(":memory:"),
                MailMessage(to_address="not-an-email", subject="s", body_text="b"),
            )
    finally:
        mail_service.send_mail_with_access_token = original_send

    assert excinfo.value.debug_code == "INVALID_RECIPIENT"
    assert calls == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("aluno@ex.com", True),
        ("aluno.sobrenome+tag@sub.ex.com.br", True),
        ("", False),
        ("   ", False),
        ("sem-arroba", False),
        ("dois@@ex.com", False),
        ("sem@dominio", False),
        ("com espaco@ex.com", False),
        ("a@b.c" + "x" * 300, False),
    ],
)
def test_recipient_validation_is_structural_only(value, expected):
    assert is_valid_email(value) is expected


def test_sanitizer_is_the_only_persistable_error_channel():
    """Nothing token-shaped may reach an error string a caller can store."""
    assert sanitize_provider_error("") == "Falha não especificada no provedor de e-mail."
    assert "Bearer" not in sanitize_provider_error("Bearer abc.def.ghi")
    assert "[redacted]" in sanitize_provider_error("erro " + "Z" * 50)
    assert len(sanitize_provider_error("x" * 5000)) <= 320


def test_docs_contract_exists_and_claims_no_auth_implementation():
    doc = (
        MODULE_PATH.parents[2] / "docs" / "mail" / "AUTH_EMAIL_EXTENSION_POINT.md"
    ).read_text(encoding="utf-8")
    assert "Neither is" in doc and "implemented in this front" in doc
    assert "single-use link" in doc
    assert "never a generated or plaintext" in doc
    # Recovery must not leak account existence.
    assert "generic" in doc.lower()


def test_no_auth_recovery_route_was_added_by_this_front():
    """The extension point is documented, deliberately not wired."""
    import main

    rules = {str(rule) for rule in main.app.url_map.iter_rules()}
    for forbidden in ("/recuperar-senha", "/primeiro-acesso", "/esqueci-minha-senha"):
        assert forbidden not in rules
