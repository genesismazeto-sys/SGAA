from __future__ import annotations

import time


_attempts_by_ip: dict[str, list[float]] = {}
_attempts_by_account: dict[str, list[float]] = {}


def normalize_recovery_identifier(value: str | None) -> str:
    return str(value or "").strip().lower()


def password_recovery_rate_limited(
    app,
    ip: str,
    account: str,
    *,
    now: float | None = None,
) -> tuple[bool, int]:
    current = time.time() if now is None else float(now)
    window = int(app.config.get("PASSWORD_RESET_WINDOW_SECONDS", 900))
    max_ip = int(app.config.get("PASSWORD_RESET_MAX_ATTEMPTS", 6))
    max_account = int(app.config.get("PASSWORD_RESET_ACCOUNT_MAX_ATTEMPTS", 4))

    ip_key = str(ip or "?")
    account_key = normalize_recovery_identifier(account)
    ip_history = [value for value in _attempts_by_ip.get(ip_key, ()) if current - value <= window]
    account_history = [
        value
        for value in _attempts_by_account.get(account_key, ())
        if current - value <= window
    ]
    _attempts_by_ip[ip_key] = ip_history
    if account_key:
        _attempts_by_account[account_key] = account_history

    oldest = None
    if len(ip_history) >= max_ip:
        oldest = ip_history[0]
    if account_key and len(account_history) >= max_account:
        oldest = min(oldest, account_history[0]) if oldest is not None else account_history[0]
    if oldest is None:
        return False, 0
    return True, max(1, int(window - (current - oldest)))


def register_password_recovery_attempt(
    ip: str,
    account: str,
    *,
    now: float | None = None,
) -> None:
    current = time.time() if now is None else float(now)
    _attempts_by_ip.setdefault(str(ip or "?"), []).append(current)
    account_key = normalize_recovery_identifier(account)
    if account_key:
        _attempts_by_account.setdefault(account_key, []).append(current)


def clear_password_recovery_attempts() -> None:
    _attempts_by_ip.clear()
    _attempts_by_account.clear()


__all__ = [
    "clear_password_recovery_attempts",
    "normalize_recovery_identifier",
    "password_recovery_rate_limited",
    "register_password_recovery_attempt",
]
