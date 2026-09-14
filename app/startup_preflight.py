"""Canonical SGAA startup preflight.

A normal SGAA launch must guarantee the machine-local secret infrastructure
before the application starts serving requests.  Discovering a missing key
later — while saving a Request, uploading an attachment or running a backup —
is an infrastructure defect, not a user error.

The preflight owns no cryptography of its own: it delegates to
``app.machine_secrets.ensure_machine_secret_infrastructure``.  Launchers
(``run.bat``/``run2.bat``) invoke this module instead of generating keys
themselves.

Preflight never blocks startup.  Cloud storage is an optional feature; a
machine that cannot prepare its secure store must still serve logins,
Activities, Requests and every other database-backed workflow.
"""

from __future__ import annotations

import logging
import sys

from app.machine_secrets import (
    INFRASTRUCTURE_CREATED,
    INFRASTRUCTURE_ENVIRONMENT,
    INFRASTRUCTURE_REUSED,
    MachineSecretsError,
    ensure_machine_secret_infrastructure,
)


logger = logging.getLogger(__name__)

PREFLIGHT_DEGRADED = "degraded"

_OPERATOR_SUMMARY = {
    INFRASTRUCTURE_CREATED: "Armazenamento seguro desta maquina criado.",
    INFRASTRUCTURE_REUSED: "Armazenamento seguro desta maquina verificado.",
    INFRASTRUCTURE_ENVIRONMENT: "Armazenamento seguro fornecido pelo ambiente.",
    PREFLIGHT_DEGRADED: (
        "O SGAA vai iniciar normalmente, mas as conexoes de nuvem ficam "
        "indisponiveis nesta maquina ate que o armazenamento seguro seja "
        "preparado."
    ),
}


def run_startup_preflight() -> dict[str, str]:
    """Prepare machine-local secret infrastructure.  Idempotent, never raises.

    Returns the canonical status dict from
    ``ensure_machine_secret_infrastructure``, or a ``degraded`` status when the
    store could not be prepared.
    """
    try:
        result = ensure_machine_secret_infrastructure()
    except MachineSecretsError as exc:
        logger.warning(
            "Preflight de segredos locais degradado: %s", exc.debug_detail
        )
        return {
            "status": PREFLIGHT_DEGRADED,
            "store_path": "",
            "detail": exc.debug_detail,
        }
    except Exception:  # defensive: preflight must never break a launch
        logger.exception("Preflight de segredos locais falhou de forma inesperada")
        return {
            "status": PREFLIGHT_DEGRADED,
            "store_path": "",
            "detail": "falha inesperada no preflight de segredos locais",
        }
    logger.info(
        "Preflight de segredos locais: %s (%s)", result["status"], result["detail"]
    )
    return result


def main() -> int:
    """Launcher entry point: ``python -m app.startup_preflight``."""
    result = run_startup_preflight()
    summary = _OPERATOR_SUMMARY.get(result["status"], _OPERATOR_SUMMARY[PREFLIGHT_DEGRADED])
    print(f"[preflight] {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
