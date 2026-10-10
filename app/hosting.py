"""Hosted-runtime contract: mode declaration, scratch space and startup blockers.

SGAA runs in one of two declared modes.  ``local`` is the Windows workstation
runtime and the default: SQLite or PostgreSQL, a persistent project directory,
a DPAPI secret store.  ``hosted`` (``SGAA_RUNTIME=hosted``) is the serverless
runtime: PostgreSQL only, no durable local disk, every secret from the
environment.  The mode is declared, never inferred, so a changed platform
marker cannot silently switch semantics; the single exception is a refusal --
a serverless platform with no declaration refuses to start, because local
semantics on an ephemeral disk would lose data without a sound.

No module-level import reaches into ``app``: ``app.machine_secrets`` and
``app.create_app`` ask the mode through here without a cycle (the blocker
check imports the database and storage owners lazily, when it runs).
Everything raised names variables and fixed codes, never a value.  The
operator command line is ``app.hosting_cli``; the web runtime never imports it.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

RUNTIME_ENV = "SGAA_RUNTIME"
MODE_HOSTED = "hosted"
MODE_LOCAL = "local"
PROXY_TRUST_ENV = "TRUST_PROXY_XFF"
LOG_DIR_ENV = "APP_LOG_DIR"
#: Vercel Cron's own variable name; the scheduler front reads it (never a query string).
CRON_SECRET_ENV = "CRON_SECRET"
CRON_SECRET_MIN_LENGTH = 32
SCRATCH_DIRNAME = "sgaa-scratch"

_SERVERLESS_MARKERS = ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME")
_BOOLEAN_WORDS = frozenset({"0", "1", "true", "false", "yes", "no", "on", "off"})

RUNTIME_MODE_INVALID = "RUNTIME_MODE_INVALID"
RUNTIME_MODE_UNDECLARED = "RUNTIME_MODE_UNDECLARED"
HOSTED_POSTGRES_REQUIRED = "HOSTED_POSTGRES_REQUIRED"
HOSTED_PROXY_TRUST_UNDECIDED = "HOSTED_PROXY_TRUST_UNDECIDED"
HOSTED_STORAGE_CONFIG_REQUIRED = "HOSTED_STORAGE_CONFIG_REQUIRED"
HOSTED_SECRET_KEY_REQUIRED = "HOSTED_SECRET_KEY_REQUIRED"
HOSTED_TOKEN_KEY_REQUIRED = "HOSTED_TOKEN_KEY_REQUIRED"
HOSTED_PUBLIC_URL_INVALID = "HOSTED_PUBLIC_URL_INVALID"


@dataclass(frozen=True)
class Blocker:
    """One reason the process must not start: a fixed code and variable NAMES."""

    code: str
    names: tuple[str, ...]


class HostingConfigurationError(RuntimeError):
    """The hosted-runtime contract is not met; ``blockers`` says why, value-free."""

    def __init__(self, blockers: tuple[Blocker, ...]) -> None:
        self.blockers = tuple(blockers)
        super().__init__("; ".join(f"{b.code}: {','.join(b.names)}" for b in self.blockers))


def single(code: str, *names: str) -> HostingConfigurationError:
    return HostingConfigurationError((Blocker(code, tuple(names)),))


def _environ(environ):
    return os.environ if environ is None else environ


def declared_mode(environ=None) -> str | None:
    """The declared mode, ``None`` when undeclared; an unknown value is refused."""
    raw = str(_environ(environ).get(RUNTIME_ENV) or "").strip().lower()
    if not raw:
        return None
    if raw not in (MODE_HOSTED, MODE_LOCAL):
        raise single(RUNTIME_MODE_INVALID, RUNTIME_ENV)
    return raw


def serverless_platform(environ=None) -> bool:
    env = _environ(environ)
    return any(str(env.get(name) or "").strip() for name in _SERVERLESS_MARKERS)


def is_hosted(environ=None) -> bool:
    return declared_mode(environ) == MODE_HOSTED


def require_declared_runtime(environ=None) -> bool:
    """Whether the process is hosted; refuses an undeclared serverless platform."""
    mode = declared_mode(environ)
    if mode is None and serverless_platform(environ):
        raise single(RUNTIME_MODE_UNDECLARED, RUNTIME_ENV)
    return mode == MODE_HOSTED


def scratch_root() -> str:
    """The only directory a hosted process may write; created by its consumers, lazily."""
    return os.path.join(tempfile.gettempdir(), SCRATCH_DIRNAME)


def apply_hosted_defaults(environ=None) -> None:
    """Point the one setting read before the application factory runs at scratch.

    ``main`` creates its log directory at import, ahead of ``create_app``; a
    hosted process must not write the project directory even by default, so its
    ``APP_LOG_DIR`` defaults to scratch.  An explicit value is respected.
    Called once, when the ``app`` package is first imported.
    """
    env = os.environ if environ is None else environ
    try:
        hosted = is_hosted(env)
    except HostingConfigurationError:
        return  # an invalid declaration is refused, with its code, by create_app
    if hosted and not str(env.get(LOG_DIR_ENV) or "").strip():
        env[LOG_DIR_ENV] = os.path.join(scratch_root(), "logs")


def cron_secret(environ=None) -> str | None:
    """The scheduler credential, or ``None`` when the front is disabled.

    One rule for the front and the readiness report: surrounding whitespace is
    ignored, at least ``CRON_SECRET_MIN_LENGTH`` characters, ASCII only (an HTTP
    header cannot carry anything else faithfully).
    """
    secret = str(_environ(environ).get(CRON_SECRET_ENV) or "").strip()
    return secret if len(secret) >= CRON_SECRET_MIN_LENGTH and secret.isascii() else None


def scheduler_secret_configured(environ=None) -> bool:
    return cron_secret(environ) is not None


def startup_blockers(environ=None, *, production: bool) -> tuple[Blocker, ...]:
    """Hosted-only conditions that make starting wrong.

    The secret key, the token key and the public address keep their existing
    owners (``create_app`` translates their refusals into the codes above);
    this adds what only a hosted process needs.  The database backend is read
    from ``app.db`` -- the runtime's own view -- and the storage variables
    from the adapter's own configuration reader.
    """
    from app import db as app_db
    from app.storage.object_store import CanonicalStoreError
    from app.storage.supabase_store import SupabaseStorageConfig

    env = _environ(environ)
    found: list[Blocker] = []
    try:
        postgres = app_db.database_backend() == "postgres"
    except ValueError:
        postgres = False
    if not postgres:
        found.append(Blocker(HOSTED_POSTGRES_REQUIRED, ("DATABASE_URL",)))
    if str(env.get(PROXY_TRUST_ENV) or "").strip().lower() not in _BOOLEAN_WORDS:
        found.append(Blocker(HOSTED_PROXY_TRUST_UNDECIDED, (PROXY_TRUST_ENV,)))
    if production:
        try:
            SupabaseStorageConfig.from_environment(env)
        except CanonicalStoreError as exc:
            names = tuple(name for name in exc.detail.split(",") if name)
            found.append(Blocker(HOSTED_STORAGE_CONFIG_REQUIRED, names))
    return tuple(found)


def require_ready(environ=None, *, production: bool) -> None:
    blockers = startup_blockers(environ, production=production)
    if blockers:
        raise HostingConfigurationError(blockers)


if __name__ == "__main__":
    # `python -m app.hosting` once ran the check; a CI gate that still calls it must fail, not pass.
    raise SystemExit("this module has no command line: use `python -m app.hosting_cli check`")


__all__ = [
    "Blocker",
    "CRON_SECRET_ENV",
    "CRON_SECRET_MIN_LENGTH",
    "cron_secret",
    "HOSTED_POSTGRES_REQUIRED",
    "HOSTED_PROXY_TRUST_UNDECIDED",
    "HOSTED_PUBLIC_URL_INVALID",
    "HOSTED_SECRET_KEY_REQUIRED",
    "HOSTED_STORAGE_CONFIG_REQUIRED",
    "HOSTED_TOKEN_KEY_REQUIRED",
    "HostingConfigurationError",
    "LOG_DIR_ENV",
    "MODE_HOSTED",
    "MODE_LOCAL",
    "PROXY_TRUST_ENV",
    "RUNTIME_ENV",
    "RUNTIME_MODE_INVALID",
    "RUNTIME_MODE_UNDECLARED",
    "apply_hosted_defaults",
    "declared_mode",
    "is_hosted",
    "require_declared_runtime",
    "require_ready",
    "scheduler_secret_configured",
    "scratch_root",
    "serverless_platform",
    "single",
    "startup_blockers",
]
