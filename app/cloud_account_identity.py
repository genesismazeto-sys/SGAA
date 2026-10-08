"""Logical provider-account identity for cloud accounts (prod-1/v14).

``cloud_accounts.id`` identifies one CREDENTIAL / CONNECTION instance: every
reconnect inserts a new row.  The LOGICAL Google account is identified by
Google's OpenID Connect subject (``sub``) -- stable for the account, never
reused, independent of the e-mail address.  The raw ``sub`` is never stored
or printed; the database keeps only a provider-namespaced digest:

    provider_account_key = lowercase_hex(SHA-256(b"google" + b"\\x00" + ASCII(sub)))

The key is PSEUDONYMOUS (a stable per-person technical identifier), not
anonymous: treat it as personal data under the same handling as the rest of
the database.  ``storage_objects.drive_account_key`` and
``cloud_accounts.provider_account_key`` both hold this value; the mirror
binds to the logical account, never to a credential row.

Canonicalization: the ``sub`` is used exactly as Google returns it --
case-sensitive, no trimming.  A value that would need normalization
(surrounding or embedded whitespace, non-ASCII, empty, oversized) is
REFUSED, never silently repaired.

Where ``sub`` comes from on connect: the ID token of the authorization-code
exchange (the ``openid`` scope is already requested).  It is received
directly from Google's token endpoint over TLS by this server, which OpenID
Connect Core 1.0 section 3.1.3.7 accepts in place of a signature check; the
issuer, audience (our client id) and expiry are still validated here.  No
additional Google request is made.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time

PROVIDER_ACCOUNT_KEY_LENGTH = 64
GOOGLE_PROVIDER = "google"
_PROVIDERS = frozenset({GOOGLE_PROVIDER})
_SUBJECT_RE = re.compile(r"^[\x21-\x7e]{1,255}$")
_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
_GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
_CLOCK_SKEW_SECONDS = 300


class AccountIdentityError(RuntimeError):
    """A refused identity value.  ``code`` is fixed; no value is ever echoed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def provider_account_key(provider: str, subject) -> str:
    """Provider-namespaced SHA-256 of an exact provider subject."""
    if provider not in _PROVIDERS:
        raise AccountIdentityError("ACCOUNT_IDENTITY_PROVIDER_UNSUPPORTED")
    if not isinstance(subject, str) or not _SUBJECT_RE.fullmatch(subject):
        raise AccountIdentityError("ACCOUNT_IDENTITY_SUBJECT_INVALID")
    payload = provider.encode("utf-8") + b"\x00" + subject.encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def google_account_key(subject) -> str:
    return provider_account_key(GOOGLE_PROVIDER, subject)


def is_provider_account_key(value) -> bool:
    return isinstance(value, str) and bool(_KEY_RE.fullmatch(value))


def require_provider_account_key(value) -> str:
    if not is_provider_account_key(value):
        raise AccountIdentityError("ACCOUNT_IDENTITY_KEY_INVALID")
    return value


def _segment(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def google_subject_from_id_token(id_token, *, audience: str, now: float | None = None) -> str:
    """The ``sub`` of an ID token received directly from Google's token endpoint.

    TRUST BOUNDARY: call this ONLY with the ID token of an authorization-code
    exchange that this backend itself performed, authenticated as its
    configured OAuth client, against Google's token endpoint over validated
    HTTPS, inside that same exchange.  Only then may the signature check be
    skipped (OIDC Core 3.1.3.7).  Never pass an ID token from a browser, a
    request parameter, the database, a cache or another service -- that would
    require full signature (JWKS) validation, which this function does not do.
    The single supported caller is
    ``app.services.google_drive_service.exchange_code_for_token``.

    Validates shape, ``iss``, ``aud`` (must contain the client id), ``azp``
    (when present, must equal the client id), ``exp`` and the strict ``sub``
    format; never returns or raises with any claim value.  The current flow
    sends no ``nonce`` (state + PKCE bind the request), so none is checked.
    """
    if not isinstance(id_token, str) or id_token.count(".") != 2:
        raise AccountIdentityError("ACCOUNT_IDENTITY_TOKEN_MISSING")
    try:
        claims = json.loads(_segment(id_token.split(".")[1]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise AccountIdentityError("ACCOUNT_IDENTITY_TOKEN_INVALID") from None
    if not isinstance(claims, dict):
        raise AccountIdentityError("ACCOUNT_IDENTITY_TOKEN_INVALID")
    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise AccountIdentityError("ACCOUNT_IDENTITY_ISSUER_INVALID")
    claimed_audience = claims.get("aud")
    audiences = claimed_audience if isinstance(claimed_audience, list) else [claimed_audience]
    if not audience or audience not in audiences:
        raise AccountIdentityError("ACCOUNT_IDENTITY_AUDIENCE_INVALID")
    if "azp" in claims and claims.get("azp") != audience:
        raise AccountIdentityError("ACCOUNT_IDENTITY_AUTHORIZED_PARTY_INVALID")
    expiry = claims.get("exp")
    moment = time.time() if now is None else now
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or expiry + _CLOCK_SKEW_SECONDS < moment:
        raise AccountIdentityError("ACCOUNT_IDENTITY_TOKEN_EXPIRED")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not _SUBJECT_RE.fullmatch(subject):
        raise AccountIdentityError("ACCOUNT_IDENTITY_SUBJECT_INVALID")
    return subject


__all__ = [
    "AccountIdentityError",
    "GOOGLE_PROVIDER",
    "PROVIDER_ACCOUNT_KEY_LENGTH",
    "google_account_key",
    "google_subject_from_id_token",
    "is_provider_account_key",
    "provider_account_key",
    "require_provider_account_key",
]
