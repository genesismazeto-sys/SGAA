"""Product-level configuration of the SGAA cloud application credentials.

An administrator configures the Google and OneDrive *application* credentials —
and the shared public OAuth address — from Banco de Dados.  This module owns the
validation and submission semantics of that product action.  It owns no storage:
every write is delegated to ``app.machine_secrets``, the single DPAPI-protected
machine-local store, so application credentials never reach ``database.db`` and
never reach the repository.

Three invariants drive the design:

* ``client_secret`` is write-only.  A blank submission means *preserve the
  stored secret*, so the key is omitted from the submitted values instead of
  being sent as ``""`` -- ``update_machine_oauth_configuration`` writes every
  key it receives, and an empty string would silently destroy the credential.
* Google and OneDrive are independently configurable, and neither provider save
  touches ``public_base_url``: provider writes always pass
  ``public_base_url=None``.  The shared address has its own entry point.
* A store that is *missing* is a normal first-run state.  Any product write
  that would bring one into existence goes through the canonical bootstrap
  owner first, so a store never exists without its token-encryption
  infrastructure.  A store that *exists but cannot be opened* -- corrupt,
  undecryptable, or bound to another Windows account -- fails closed here.  It
  is never deleted, renamed, overwritten, recreated, or retried with a fresh
  key, because those bytes may hold the only recoverable copy of a credential.
  ``MachineSecretsError`` is translated into a sanitized product failure and the
  technical cause goes to the log, never to the operator's screen.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

from app.machine_secrets import (
    MachineSecretsError,
    load_machine_secrets,
    save_machine_secrets,
    update_machine_oauth_configuration,
)

# Machine-secret *creation* has exactly one owner, app.startup_preflight, which
# in turn delegates to machine_secrets.ensure_machine_secret_infrastructure.
# This module never mints a key; it only makes sure the canonical bootstrap has
# run before a write that would otherwise create a keyless store.
from app.startup_preflight import run_startup_preflight

# The public OAuth address is validated by the same rules that later *read* it,
# so an address this module accepts is one ``get_public_base_url()`` can use.
# Re-deriving the rules here would let the two definitions of "valid" drift.
from services.oauth_config import (
    OAuthConfigError,
    _normalize_base_url,
    _validate_base_url_for_env,
    get_app_env,
)


logger = logging.getLogger(__name__)

PROVIDERS = ("google", "onedrive")

# Identifier fields per provider.  ``client_secret`` is deliberately absent: it
# is never read back, never prefilled and never required to be resubmitted.
PROVIDER_IDENTIFIER_FIELDS: dict[str, tuple[str, ...]] = {
    "google": ("client_id",),
    "onedrive": ("client_id", "tenant_id"),
}

_FIELD_LABELS = {
    "client_id": "ID do cliente",
    "tenant_id": "ID do diretório (tenant)",
}

_PROVIDER_LABELS = {"google": "Google Drive", "onedrive": "OneDrive"}

_MAX_IDENTIFIER_LENGTH = 512
_MAX_SECRET_LENGTH = 2048


class CloudCredentialsError(RuntimeError):
    """A product-level failure of a credential or address save.

    ``str()`` is safe to show to an administrator: it never contains the
    submitted secret, an environment variable name, a script name or a
    cryptographic primitive.
    """


def normalize_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized not in PROVIDERS:
        raise CloudCredentialsError("Provedor de nuvem inválido.")
    return normalized


@contextmanager
def _product_store_failure(operation: str):
    """Translate a machine-store failure into a sanitized product failure.

    Deliberately inert: it logs and re-raises.  There is no repair branch --
    an existing store that cannot be opened is left byte-for-byte untouched.
    """
    try:
        yield
    except MachineSecretsError as exc:
        logger.warning(
            "Armazenamento local indisponível durante %s: %s",
            operation,
            exc.debug_detail,
        )
        raise CloudCredentialsError(exc.user_message) from exc


def _normalize_identifier(value: str, *, field: str, provider: str) -> str:
    text = str(value or "").strip()
    label = _FIELD_LABELS[field]
    if not text:
        raise CloudCredentialsError(
            f"Informe o {label} do aplicativo {_PROVIDER_LABELS[provider]}."
        )
    if len(text) > _MAX_IDENTIFIER_LENGTH or any(char.isspace() for char in text):
        raise CloudCredentialsError(
            f"O {label} informado não tem um formato válido. "
            "Copie o valor exatamente como aparece no portal do provedor."
        )
    return text


def _normalize_secret(value: str) -> str:
    # Never echoed, never logged, never returned to a template.
    secret = str(value or "").strip()
    if len(secret) > _MAX_SECRET_LENGTH:
        raise CloudCredentialsError(
            "A chave secreta informada não tem um formato válido. "
            "Copie o valor exatamente como aparece no portal do provedor."
        )
    return secret


def stored_secret_is_present(provider: str) -> bool:
    """Whether a client secret is already held for ``provider``.

    Fails closed: an unreadable store raises instead of reporting "absent",
    which would invite a caller to overwrite credentials it could not read.
    """
    normalized = normalize_provider(provider)
    with _product_store_failure("leitura das credenciais"):
        payload = load_machine_secrets()
    providers = payload.get("providers") if isinstance(payload.get("providers"), dict) else {}
    stored = providers.get(normalized)
    if not isinstance(stored, dict):
        return False
    return bool(str(stored.get("client_secret") or "").strip())


def save_application_credentials(
    *,
    provider: str,
    client_id: str,
    client_secret: str,
    tenant_id: str = "",
) -> dict[str, object]:
    """Persist one provider's application credentials in the machine store.

    Returns ``{"provider", "secret_rotated"}``.  Never returns, logs or raises
    the submitted secret.
    """
    normalized = normalize_provider(provider)
    submitted = {"client_id": client_id, "tenant_id": tenant_id}
    values = {
        field: _normalize_identifier(
            submitted[field], field=field, provider=normalized
        )
        for field in PROVIDER_IDENTIFIER_FIELDS[normalized]
    }

    secret = _normalize_secret(client_secret)
    if secret:
        # Only present when the administrator actually typed a new secret.
        values["client_secret"] = secret
    elif not stored_secret_is_present(normalized):
        raise CloudCredentialsError(
            "Informe a chave secreta do aplicativo "
            f"{_PROVIDER_LABELS[normalized]}: ainda não há uma chave guardada "
            "nesta máquina."
        )

    with _product_store_failure("gravação das credenciais"):
        update_machine_oauth_configuration(
            provider=normalized,
            values=values,
            # The shared public address has its own action; a credential save
            # must never rewrite it.
            public_base_url=None,
        )
    logger.info(
        "Credenciais do aplicativo %s atualizadas (chave secreta %s).",
        normalized,
        "substituída" if secret else "preservada",
    )
    return {"provider": normalized, "secret_rotated": bool(secret)}


def normalize_public_base_url(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        raise CloudCredentialsError(
            "Informe o endereço público do sistema, por exemplo "
            "http://localhost:5000."
        )
    try:
        normalized = _normalize_base_url(candidate, source="APP_PUBLIC_BASE_URL")
        return _validate_base_url_for_env(normalized, env=get_app_env())
    except OAuthConfigError as exc:
        raise CloudCredentialsError(str(exc)) from exc


def save_public_base_url(value: str) -> str:
    """Persist the shared public OAuth address, provider credentials untouched.

    Writes only ``runtime.public_base_url``; the ``providers`` section of the
    payload is round-tripped verbatim.

    A store this call brings into existence must not be keyless, so the
    canonical bootstrap runs first.  On a store that already holds a key the
    bootstrap is a no-op and the key is reused byte-for-byte; on a store that
    cannot be opened the bootstrap writes nothing and the ``load`` below fails
    closed, leaving the file exactly as it was.
    """
    normalized = normalize_public_base_url(value)
    run_startup_preflight()
    with _product_store_failure("gravação do endereço público"):
        payload = load_machine_secrets()
        runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        runtime["public_base_url"] = normalized
        payload["runtime"] = runtime
        save_machine_secrets(payload)
    logger.info("Endereço público OAuth atualizado para %s.", normalized)
    return normalized
