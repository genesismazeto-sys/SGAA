import base64
import hashlib
import logging
import secrets


__all__ = [
    "check_password",
    "hash_password",
    "is_legacy_password_hash",
]


def hash_password(password: str) -> str:
    """Gera hash seguro de senha (PBKDF2-SHA256, 600k iterações).

    Mantemos compat com hashes legados (sha256+salt) na verificação; o login
    re-hashifica oportunisticamente para o novo formato.
    """
    from werkzeug.security import generate_password_hash

    return generate_password_hash(str(password or ""), method="pbkdf2:sha256:600000")


def is_legacy_password_hash(stored_password: str) -> bool:
    """Retorna True para hashes do formato antigo (base64$base64 SHA256)."""
    if not stored_password or not isinstance(stored_password, str):
        return False
    if stored_password.startswith("pbkdf2:") or stored_password.startswith("scrypt:") or stored_password.startswith("argon2"):
        return False
    parts = stored_password.split("$")
    return len(parts) == 2 and all(len(p) > 0 for p in parts)


def _check_password_legacy(stored_password: str, provided_password: str) -> bool:
    try:
        salt_b64, hash_b64 = stored_password.split("$")
        salt = base64.b64decode(salt_b64)
        h = hashlib.sha256()
        h.update(salt + provided_password.encode("utf-8"))
        calculated_hash = h.digest()
        stored_hash = base64.b64decode(hash_b64)
        return secrets.compare_digest(calculated_hash, stored_hash)
    except Exception:
        return False


def check_password(stored_password: str, provided_password: str) -> bool:
    """Compara senha aceitando tanto hashes novos (werkzeug) quanto legados."""
    if not stored_password:
        return False
    try:
        if is_legacy_password_hash(stored_password):
            return _check_password_legacy(stored_password, provided_password)
        from werkzeug.security import check_password_hash

        return check_password_hash(stored_password, provided_password or "")
    except Exception as exc:
        logging.error(f"Erro ao verificar senha: tipo={type(exc).__name__}")
        return False
