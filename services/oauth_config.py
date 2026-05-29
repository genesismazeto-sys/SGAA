import logging
import os
from urllib.parse import urlsplit


logger = logging.getLogger(__name__)

_LOCAL_HTTP_HOSTS = {"localhost", "127.0.0.1"}


class OAuthConfigError(RuntimeError):
    pass


def get_app_env() -> str:
    raw = (
        os.getenv("APP_ENV")
        or os.getenv("FLASK_ENV")
        or "development"
    ).strip().lower()
    if raw in {"prod", "production"}:
        return "production"
    if raw in {"test", "testing"}:
        return "testing"
    return "development"


def _normalize_base_url(base_url: str, *, source: str) -> str:
    candidate = (base_url or "").strip().rstrip("/")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OAuthConfigError(
            f"{source} inválido: {base_url!r}. Use um URL completo como "
            "'http://localhost:5000' ou 'https://dominio-real-do-sistema'."
        )
    if parsed.query or parsed.fragment:
        raise OAuthConfigError(
            f"{source} inválido: não use query string ou fragmento em {base_url!r}."
        )
    if parsed.path not in {"", "/"}:
        raise OAuthConfigError(
            f"{source} inválido: não inclua caminho em {base_url!r}. "
            "Use apenas esquema + host (+ porta)."
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def _validate_base_url_for_env(base_url: str, *, env: str) -> str:
    parsed = urlsplit(base_url)
    host = (parsed.hostname or "").strip().lower()

    if env == "production":
        if parsed.scheme != "https":
            raise OAuthConfigError(
                "APP_PUBLIC_BASE_URL inválido para produção: use obrigatoriamente "
                "um URL com https://"
            )
        return base_url

    if parsed.scheme == "http" and host not in _LOCAL_HTTP_HOSTS:
        raise OAuthConfigError(
            "APP_PUBLIC_BASE_URL inválido para desenvolvimento: HTTP é permitido "
            "apenas para localhost ou 127.0.0.1. Para outros hosts, use HTTPS."
        )
    return base_url


def _legacy_redirect_base(env_key: str, expected_path: str) -> str:
    value = (os.getenv(env_key) or "").strip()
    if not value:
        return ""

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OAuthConfigError(
            f"{env_key} inválido: {value!r}. Defina um URL completo."
        )
    path = (parsed.path or "").rstrip("/")
    if path != expected_path:
        raise OAuthConfigError(
            f"{env_key} inválido: {value!r}. Esperado sufixo '{expected_path}'."
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def get_public_base_url() -> str:
    env = get_app_env()
    configured = (os.getenv("APP_PUBLIC_BASE_URL") or "").strip()
    legacy_google_redirect = (os.getenv("GOOGLE_REDIRECT_URI") or "").strip()
    legacy_onedrive_redirect = (os.getenv("MS_REDIRECT_URI") or "").strip()
    if configured:
        if legacy_google_redirect or legacy_onedrive_redirect:
            logger.info(
                "APP_PUBLIC_BASE_URL definido; ignorando GOOGLE_REDIRECT_URI/MS_REDIRECT_URI legados."
            )
        normalized = _normalize_base_url(configured, source="APP_PUBLIC_BASE_URL")
        return _validate_base_url_for_env(normalized, env=env)

    google_base = _legacy_redirect_base("GOOGLE_REDIRECT_URI", "/google/callback")
    onedrive_base = _legacy_redirect_base("MS_REDIRECT_URI", "/onedrive/callback")
    candidates = [item for item in (google_base, onedrive_base) if item]

    if candidates:
        selected = candidates[0]
        if any(item != selected for item in candidates[1:]):
            raise OAuthConfigError(
                "GOOGLE_REDIRECT_URI e MS_REDIRECT_URI apontam para hosts diferentes. "
                "Defina APP_PUBLIC_BASE_URL para centralizar os callbacks."
            )
        normalized = _normalize_base_url(selected, source="APP_PUBLIC_BASE_URL (legacy)")
        validated = _validate_base_url_for_env(normalized, env=env)
        logger.warning(
            "APP_PUBLIC_BASE_URL ausente; usando compatibilidade legada com GOOGLE_REDIRECT_URI/MS_REDIRECT_URI."
        )
        return validated

    if env == "production":
        raise OAuthConfigError(
            "APP_PUBLIC_BASE_URL não configurado. Defina no .env, por exemplo: "
            "https://dominio-real-do-sistema"
        )

    fallback = "http://localhost:5000"
    logger.warning(
        "APP_PUBLIC_BASE_URL ausente em desenvolvimento/testing; usando fallback explicito: %s",
        fallback,
    )
    normalized = _normalize_base_url(fallback, source="APP_PUBLIC_BASE_URL (fallback)")
    return _validate_base_url_for_env(normalized, env=env)


def get_google_redirect_uri() -> str:
    return f"{get_public_base_url()}/google/callback"


def get_onedrive_redirect_uri() -> str:
    return f"{get_public_base_url()}/onedrive/callback"
