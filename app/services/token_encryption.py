"""At-rest encryption for ``cloud_accounts.token_json``.

The machine-local encryption key is owned by ``app.machine_secrets`` and is
created by the canonical startup preflight (``app.startup_preflight``).  This
module only consumes it.

Error contract: ``str(exc)`` is always a product-level, actionable message.  It
never names an environment variable, a maintenance script or a cryptographic
primitive — those belong in ``exc.debug_detail``, which is logged here and
available to diagnostics.
"""

import logging
import os
from typing import Final

from app.machine_secrets import MachineSecretsError, get_machine_token_encryption_key


logger = logging.getLogger(__name__)

_TOKEN_PREFIX: Final[str] = "fernet:"

RECONNECT_USER_MESSAGE: Final[str] = (
    "A conexão de nuvem precisa ser refeita nesta máquina. "
    "Acesse Banco de Dados > Google Drive e use Reconectar."
)
UNAVAILABLE_USER_MESSAGE: Final[str] = (
    "As conexões de nuvem estão temporariamente indisponíveis nesta máquina. "
    "Acesse Banco de Dados > Google Drive e use Reconectar."
)


class TokenEncryptionError(RuntimeError):
    def __init__(self, message: str, *, debug_detail: str = ""):
        super().__init__(message)
        self.user_message = message
        self.debug_detail = debug_detail or message


class TokenEncryptionConfigError(TokenEncryptionError):
    pass


def _raise_config_error(user_message: str, debug_detail: str, *, cause=None):
    logger.warning("Configuração de criptografia de token indisponível: %s", debug_detail)
    error = TokenEncryptionConfigError(user_message, debug_detail=debug_detail)
    if cause is not None:
        raise error from cause
    raise error


def _normalize_env(env: str | None = None) -> str:
    raw = (
        env
        or os.getenv("APP_ENV")
        or os.getenv("FLASK_ENV")
        or "development"
    ).strip().lower()
    if raw in {"prod", "production"}:
        return "production"
    if raw in {"test", "testing"}:
        return "testing"
    return "development"


def _import_fernet():
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except Exception as exc:
        _raise_config_error(
            UNAVAILABLE_USER_MESSAGE,
            "cryptography nao esta instalado; rode pip install -r requirements.txt",
            cause=exc,
        )
    return Fernet, InvalidToken


def get_token_encryption_key() -> str:
    legacy_environment_key = (os.getenv("TOKEN_ENCRYPTION_KEY") or "").strip()
    if legacy_environment_key:
        return legacy_environment_key
    try:
        return get_machine_token_encryption_key(create=False)
    except MachineSecretsError as exc:
        _raise_config_error(str(exc), exc.debug_detail, cause=exc)


def is_token_encryption_configured() -> bool:
    return bool(get_token_encryption_key())


def is_token_json_encrypted(token_json: str) -> bool:
    return str(token_json or "").startswith(_TOKEN_PREFIX)


def validate_token_encryption_configuration(*, env: str | None = None) -> None:
    normalized_env = _normalize_env(env)
    key = get_token_encryption_key()
    if not key:
        _raise_config_error(
            RECONNECT_USER_MESSAGE,
            "chave de criptografia local ausente; o preflight de inicializacao nao a criou",
        )

    Fernet, InvalidToken = _import_fernet()
    try:
        Fernet(key.encode("utf-8"))
    except Exception as exc:
        _raise_config_error(
            RECONNECT_USER_MESSAGE,
            "chave de criptografia local presente mas invalida para Fernet",
            cause=exc,
        )

    if normalized_env == "production" and not key:
        _raise_config_error(
            RECONNECT_USER_MESSAGE,
            "APP_ENV=production exige uma chave de criptografia de token configurada",
        )


def encrypt_token_json_for_storage(token_json: str, *, env: str | None = None) -> str:
    raw_value = str(token_json or "")
    validate_token_encryption_configuration(env=env)
    Fernet, InvalidToken = _import_fernet()
    cipher = Fernet(get_token_encryption_key().encode("utf-8"))
    encrypted = cipher.encrypt(raw_value.encode("utf-8")).decode("utf-8")
    return f"{_TOKEN_PREFIX}{encrypted}"


def decrypt_token_json_from_storage(token_json: str, *, env: str | None = None) -> str:
    stored_value = str(token_json or "")
    if not stored_value:
        return ""

    normalized_env = _normalize_env(env)
    if not is_token_json_encrypted(stored_value):
        if normalized_env == "production":
            _raise_config_error(
                RECONNECT_USER_MESSAGE,
                "token OAuth armazenado sem criptografia em cloud_accounts sob APP_ENV=production",
            )
        logger.warning(
            "cloud_accounts.token_json em formato legado sem criptografia detectado no ambiente %s.",
            normalized_env,
        )
        return stored_value

    validate_token_encryption_configuration(env=env)
    Fernet, InvalidToken = _import_fernet()
    cipher = Fernet(get_token_encryption_key().encode("utf-8"))
    encrypted_blob = stored_value[len(_TOKEN_PREFIX):].strip()
    if not encrypted_blob:
        _raise_config_error(
            RECONNECT_USER_MESSAGE,
            "token OAuth criptografado invalido em cloud_accounts (payload vazio)",
        )
    try:
        return cipher.decrypt(encrypted_blob.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        # The stored token was encrypted under a key this machine no longer
        # holds.  The token is left untouched: the account is simply classified
        # as reconnect-required by app.cloud_connections.
        _raise_config_error(
            RECONNECT_USER_MESSAGE,
            "token OAuth de cloud_accounts nao pode ser descriptografado com a chave local atual",
            cause=exc,
        )
