"""Interactive, non-echoing SGAA cloud OAuth configuration utility."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from urllib.parse import urlsplit


REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, REPOSITORY_ROOT)

from app.cloud_config import get_application_credential_status  # noqa: E402
from app.machine_secrets import (  # noqa: E402
    MachineSecretsError,
    load_machine_secrets,
    update_machine_oauth_configuration,
)


def _prompt(label: str, current: str = "", *, secret: bool = False) -> str:
    suffix = " [Enter preserva o valor atual]" if current else ""
    value = (getpass.getpass(label + suffix + ": ") if secret else input(label + suffix + ": ")).strip()
    return value if value else current


def _validate_base_url(value: str) -> str:
    parsed = urlsplit(value.strip().rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Informe APP_PUBLIC_BASE_URL completo, sem caminho, query ou fragmento.")
    if parsed.path not in {"", "/"}:
        raise ValueError("APP_PUBLIC_BASE_URL deve conter apenas esquema, host e porta opcional.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _configure(provider: str) -> None:
    payload = load_machine_secrets()
    providers = payload.get("providers") if isinstance(payload.get("providers"), dict) else {}
    current = providers.get(provider) if isinstance(providers.get(provider), dict) else {}
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    public_base_url = _validate_base_url(
        _prompt("URL publica do SGAA", str(runtime.get("public_base_url") or "http://localhost:5000"))
    )
    if provider == "google":
        values = {
            "client_id": _prompt("Google Client ID", str(current.get("client_id") or "")),
            "client_secret": _prompt(
                "Google Client Secret", str(current.get("client_secret") or ""), secret=True
            ),
            "scopes": str(current.get("scopes") or "").strip(),
        }
    else:
        values = {
            "client_id": _prompt("Microsoft Client ID", str(current.get("client_id") or "")),
            "client_secret": _prompt(
                "Microsoft Client Secret", str(current.get("client_secret") or ""), secret=True
            ),
            "tenant_id": _prompt("Microsoft Tenant ID", str(current.get("tenant_id") or "")),
            "graph_base_url": str(current.get("graph_base_url") or "https://graph.microsoft.com/v1.0"),
        }
    required = ("client_id", "client_secret") if provider == "google" else ("client_id", "client_secret", "tenant_id")
    if any(not values[key] for key in required):
        raise ValueError("Todos os campos obrigatorios do provedor devem ser informados.")
    update_machine_oauth_configuration(
        provider=provider,
        values=values,
        public_base_url=public_base_url,
    )


def _print_status(providers: tuple[str, ...]) -> None:
    labels = {"google": "Google Drive", "onedrive": "OneDrive"}
    for provider in providers:
        label = labels[provider]
        status = get_application_credential_status(provider)
        configured = "PRESENT" if status["configured"] else "ABSENT"
        print(f"{label}: {configured}; source={status['source']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Configura OAuth cloud do SGAA com Windows DPAPI.")
    parser.add_argument("--provider", choices=("google", "onedrive", "both"))
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    try:
        if args.status:
            selected = (
                ("google", "onedrive")
                if args.provider == "both"
                else (args.provider,)
                if args.provider
                else ("google",)
            )
            _print_status(selected)
            return 0
        if not args.provider:
            parser.error("informe --provider google, onedrive ou both")
        selected = ("google", "onedrive") if args.provider == "both" else (args.provider,)
        for provider in selected:
            _configure(provider)
        _print_status(selected)
        print("Credenciais salvas fora do repositorio e protegidas pela conta Windows atual.")
        return 0
    except (MachineSecretsError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
