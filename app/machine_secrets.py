"""Windows user-bound storage for SGAA machine-local secrets.

The encrypted payload lives outside the repository.  Windows DPAPI binds the
payload to the current Windows user, so copying the file to another account or
machine does not disclose its contents.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
import tempfile
from typing import Any


_STORE_VERSION = 1
_STORE_FILENAME = "cloud-oauth.dpapi"
_DPAPI_DESCRIPTION = "SGAA cloud OAuth credentials"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class MachineSecretsError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def get_machine_secrets_path() -> str:
    local_app_data = (os.getenv("LOCALAPPDATA") or "").strip()
    if not local_app_data:
        raise MachineSecretsError(
            "LOCALAPPDATA indisponivel. Configure as credenciais OAuth em uma conta Windows local valida."
        )
    return os.path.join(local_app_data, "SGAA", "secrets", _STORE_FILENAME)


def _blob_from_bytes(payload: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(payload)
    blob = _DataBlob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _protect_bytes(payload: bytes) -> bytes:
    if os.name != "nt":
        raise MachineSecretsError("O armazenamento seguro OAuth requer Windows DPAPI.")
    source, source_buffer = _blob_from_bytes(payload)
    result = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptProtectData(
        ctypes.byref(source),
        _DPAPI_DESCRIPTION,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    )
    del source_buffer
    if not ok:
        raise MachineSecretsError("Windows DPAPI nao conseguiu proteger as credenciais OAuth.")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def _unprotect_bytes(payload: bytes) -> bytes:
    if os.name != "nt":
        raise MachineSecretsError("O armazenamento seguro OAuth requer Windows DPAPI.")
    source, source_buffer = _blob_from_bytes(payload)
    result = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    )
    del source_buffer
    if not ok:
        raise MachineSecretsError(
            "As credenciais OAuth desta instalacao nao podem ser abertas pela conta Windows atual."
        )
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def _empty_payload() -> dict[str, Any]:
    return {"version": _STORE_VERSION, "runtime": {}, "providers": {}}


def load_machine_secrets(*, path: str | None = None) -> dict[str, Any]:
    store_path = os.path.abspath(path or get_machine_secrets_path())
    if not os.path.isfile(store_path):
        return _empty_payload()
    try:
        with open(store_path, "rb") as handle:
            protected = base64.b64decode(handle.read(), validate=True)
        payload = json.loads(_unprotect_bytes(protected).decode("utf-8"))
    except MachineSecretsError:
        raise
    except Exception as exc:
        raise MachineSecretsError("O arquivo seguro de credenciais OAuth esta invalido.") from exc
    if not isinstance(payload, dict) or payload.get("version") != _STORE_VERSION:
        raise MachineSecretsError("A versao do arquivo seguro de credenciais OAuth nao e suportada.")
    payload.setdefault("runtime", {})
    payload.setdefault("providers", {})
    return payload


def save_machine_secrets(payload: dict[str, Any], *, path: str | None = None) -> str:
    store_path = os.path.abspath(path or get_machine_secrets_path())
    normalized = dict(payload)
    normalized["version"] = _STORE_VERSION
    normalized.setdefault("runtime", {})
    normalized.setdefault("providers", {})
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
    protected = base64.b64encode(_protect_bytes(encoded))
    directory = os.path.dirname(store_path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".cloud-oauth-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(protected)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, store_path)
        try:
            os.chmod(store_path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise
    return store_path


def get_machine_token_encryption_key(*, create: bool = False) -> str:
    payload = load_machine_secrets()
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    key = str(runtime.get("token_encryption_key") or "").strip()
    if key or not create:
        return key
    try:
        from cryptography.fernet import Fernet
    except Exception as exc:
        raise MachineSecretsError(
            "Dependencia cryptography ausente. Rode pip install -r requirements.txt."
        ) from exc
    key = Fernet.generate_key().decode("ascii")
    runtime["token_encryption_key"] = key
    payload["runtime"] = runtime
    save_machine_secrets(payload)
    return key


def update_machine_oauth_configuration(
    *,
    provider: str,
    values: dict[str, str],
    public_base_url: str | None = None,
) -> None:
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider not in {"google", "onedrive"}:
        raise ValueError("Provedor OAuth invalido.")
    payload = load_machine_secrets()
    providers = payload.get("providers") if isinstance(payload.get("providers"), dict) else {}
    current = providers.get(normalized_provider)
    if not isinstance(current, dict):
        current = {}
    for key, value in values.items():
        current[str(key)] = str(value or "").strip()
    providers[normalized_provider] = current
    payload["providers"] = providers
    if public_base_url is not None:
        runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        runtime["public_base_url"] = str(public_base_url or "").strip().rstrip("/")
        payload["runtime"] = runtime
    if not str((payload.get("runtime") or {}).get("token_encryption_key") or "").strip():
        try:
            from cryptography.fernet import Fernet
        except Exception as exc:
            raise MachineSecretsError(
                "Dependencia cryptography ausente. Rode pip install -r requirements.txt."
            ) from exc
        payload["runtime"]["token_encryption_key"] = Fernet.generate_key().decode("ascii")
    save_machine_secrets(payload)
