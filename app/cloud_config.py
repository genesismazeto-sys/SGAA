"""Authoritative runtime configuration for reusable cloud connections."""

from __future__ import annotations

import os
from typing import Any

from app.machine_secrets import MachineSecretsError, load_machine_secrets


def _stored_payload() -> dict[str, Any]:
    try:
        return load_machine_secrets()
    except MachineSecretsError:
        raise


def _stored_provider(provider: str) -> dict[str, str]:
    payload = _stored_payload()
    providers = payload.get("providers") if isinstance(payload.get("providers"), dict) else {}
    item = providers.get(provider)
    return item if isinstance(item, dict) else {}


def _first(stored: dict[str, str], stored_key: str, *environment_keys: str, default: str = "") -> str:
    stored_value = str(stored.get(stored_key) or "").strip()
    if stored_value:
        return stored_value
    for key in environment_keys:
        value = str(os.getenv(key) or "").strip()
        if value:
            return value
    return default


def get_google_oauth_config() -> dict[str, str]:
    stored = _stored_provider("google")
    return {
        "client_id": _first(stored, "client_id", "GOOGLE_CLIENT_ID"),
        "client_secret": _first(stored, "client_secret", "GOOGLE_CLIENT_SECRET"),
        "scopes": _first(
            stored,
            "scopes",
            "GOOGLE_SCOPES",
            default=(
                "https://www.googleapis.com/auth/drive.file "
                "https://www.googleapis.com/auth/userinfo.email openid"
            ),
        ),
    }


def get_onedrive_oauth_config() -> dict[str, str]:
    stored = _stored_provider("onedrive")
    return {
        "client_id": _first(stored, "client_id", "MS_CLIENT_ID", "ONEDRIVE_CLIENT_ID"),
        "client_secret": _first(stored, "client_secret", "MS_CLIENT_SECRET"),
        "tenant_id": _first(stored, "tenant_id", "MS_TENANT_ID", "ONEDRIVE_TENANT_ID"),
        "graph_base_url": _first(
            stored,
            "graph_base_url",
            "MS_GRAPH_BASE_URL",
            default="https://graph.microsoft.com/v1.0",
        ),
    }


def get_public_base_url_setting() -> str:
    payload = _stored_payload()
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    return _first(runtime, "public_base_url", "APP_PUBLIC_BASE_URL")


def get_application_credential_status(provider: str) -> dict[str, object]:
    normalized = str(provider or "").strip().lower()
    if normalized not in {"google", "onedrive"}:
        raise ValueError("Provedor OAuth invalido.")
    try:
        stored = _stored_provider(normalized)
    except MachineSecretsError:
        return {"provider": normalized, "configured": False, "source": "ERROR"}
    if normalized == "google":
        config = get_google_oauth_config()
        required_keys = ("client_id", "client_secret")
    elif normalized == "onedrive":
        config = get_onedrive_oauth_config()
        required_keys = ("client_id", "client_secret", "tenant_id")
    configured = all(bool(config[key]) for key in required_keys)
    stored_configured = all(bool(str(stored.get(key) or "").strip()) for key in required_keys)
    return {
        "provider": normalized,
        "configured": configured,
        "source": (
            "MACHINE_LOCAL_DPAPI"
            if stored_configured
            else "ENVIRONMENT"
            if configured
            else "ABSENT"
        ),
    }
