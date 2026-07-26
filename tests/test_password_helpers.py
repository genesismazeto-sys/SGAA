import base64
import hashlib
import inspect
import os
import subprocess
import sys

from app.security import passwords
import main


def _legacy_hash(password: str) -> str:
    salt = bytes(range(16))
    digest = hashlib.sha256(salt + password.encode("utf-8")).digest()
    return f"{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def test_password_module_exports_exact_public_api():
    assert passwords.__all__ == [
        "check_password",
        "hash_password",
        "is_legacy_password_hash",
    ]
    assert list(inspect.signature(passwords.hash_password).parameters) == ["password"]
    assert list(inspect.signature(passwords.check_password).parameters) == [
        "stored_password",
        "provided_password",
    ]
    assert list(inspect.signature(passwords.is_legacy_password_hash).parameters) == [
        "stored_password",
    ]


def test_modern_password_hash_preserves_algorithm_and_verification():
    password_hash = passwords.hash_password("senha-forte")

    assert password_hash.startswith("pbkdf2:sha256:600000$")
    assert passwords.check_password(password_hash, "senha-forte") is True
    assert passwords.check_password(password_hash, "senha-incorreta") is False


def test_legacy_password_hash_preserves_compatibility_and_rejects_malformed_values():
    legacy = _legacy_hash("senha-legada")

    assert passwords.is_legacy_password_hash(legacy) is True
    assert passwords.check_password(legacy, "senha-legada") is True
    assert passwords.check_password(legacy, "senha-incorreta") is False
    assert passwords.is_legacy_password_hash("pbkdf2:sha256:600000$sal$hash") is False
    assert passwords.is_legacy_password_hash("sem-separador") is False
    assert passwords.check_password("invalido$base64", "senha") is False


def test_main_preserves_password_compatibility_exports():
    assert main.hash_password is passwords.hash_password
    assert main.check_password is passwords.check_password
    assert main.is_legacy_password_hash is passwords.is_legacy_password_hash


def test_password_module_import_does_not_import_main():
    env = os.environ.copy()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from app.security import passwords; "
                "assert 'main' not in sys.modules; "
                "assert passwords.hash_password"
            ),
        ],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
