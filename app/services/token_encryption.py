import logging
import os
from typing import Final

from app.machine_secrets import MachineSecretsError, get_machine_token_encryption_key


logger = logging.getLogger(__name__)

_TOKEN_PREFIX: Final[str] = "fernet:"
_KEY_HINT: Final[str] = (
    'python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)


class TokenEncryptionError(RuntimeError):
    pass


class TokenEncryptionConfigError(TokenEncryptionError):
    pass


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
        raise TokenEncryptionConfigError(
            "Dependencia cryptography ausente. Rode pip install -r requirements.txt."
        ) from exc
    return Fernet, InvalidToken


def get_token_encryption_key() -> str:
    legacy_environment_key = (os.getenv("TOKEN_ENCRYPTION_KEY") or "").strip()
    if legacy_environment_key:
        return legacy_environment_key
    try:
        return get_machine_token_encryption_key(create=False)
    except MachineSecretsError as exc:
        raise TokenEncryptionConfigError(str(exc)) from exc


def is_token_encryption_configured() -> bool:
    return bool(get_token_encryption_key())


def is_token_json_encrypted(token_json: str) -> bool:
    return str(token_json or "").startswith(_TOKEN_PREFIX)


def validate_token_encryption_configuration(*, env: str | None = None) -> None:
    normalized_env = _normalize_env(env)
    key = get_token_encryption_key()
    if not key:
        raise TokenEncryptionConfigError(
            "Chave de criptografia OAuth ausente. Execute tools/configure_cloud_oauth.py "
            "para criar a configuracao segura desta maquina. "
            f"Compatibilidade legada: gere uma chave com {_KEY_HINT} e defina TOKEN_ENCRYPTION_KEY fora do Git."
        )

    Fernet, InvalidToken = _import_fernet()
    try:
        Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise TokenEncryptionConfigError(
            "Chave de criptografia OAuth invalida. Reconfigure o armazenamento seguro desta maquina. "
            f"Compatibilidade legada: gere uma chave Fernet com {_KEY_HINT}."
        ) from exc

    if normalized_env == "production" and not key:
        raise TokenEncryptionConfigError(
            "APP_ENV=production exige TOKEN_ENCRYPTION_KEY configurada."
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
            raise TokenEncryptionConfigError(
                "Token OAuth armazenado sem criptografia em cloud_accounts. "
                "Configure TOKEN_ENCRYPTION_KEY e reconecte a conta."
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
        raise TokenEncryptionConfigError(
            "Token OAuth criptografado inválido em cloud_accounts. Reconecte a conta."
        )
    try:
        return cipher.decrypt(encrypted_blob.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise TokenEncryptionConfigError(
            "Não foi possível descriptografar token_json de cloud_accounts. "
            "Verifique TOKEN_ENCRYPTION_KEY ou reconecte a conta."
        ) from exc
