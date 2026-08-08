# coding: utf-8
"""CLI de backup: ``python -m app.backup.sync``.

Executa **uma vez** o ciclo automático canônico
(:func:`app.backup.orchestrator.run_backup_cycle`) sob application context —
nunca sob request context. Substitui, como gatilho não-interativo, o hook
pós-resposta que a UT-5 removeu de main.py.

Este é o único ponto do pacote que depende de ``create_app``; a dependência
fica isolada aqui de propósito. Nada aqui importa ``main``.

Códigos de saída (determinísticos):

    0 -- ciclo concluído com sucesso **ou** pulado por política legítima
    1 -- falha de orquestração/runtime não tratada, após a app subir
    2 -- falha ao inicializar a aplicação

Falhas específicas de provedor (Google/OneDrive) permanecem *best-effort* nas
camadas inferiores e, por contrato existente, não transformam o processo em
falha.

Sem opções de linha de comando, sem prompt interativo e sem inicialização de
schema.
"""
import logging

from app import create_app
from app.backup.orchestrator import run_backup_cycle


logger = logging.getLogger("main")

EXIT_OK = 0
EXIT_RUNTIME_FAILURE = 1
EXIT_STARTUP_FAILURE = 2

_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def _configure_cli_logging() -> None:
    """Logging comum de CLI: um único handler de console, via raiz.

    O canal ``main`` não recebe handler próprio aqui de propósito: ele propaga
    para a raiz configurada por ``basicConfig``, o que evita linhas duplicadas.
    """
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    logger.setLevel(logging.INFO)


def main() -> int:
    _configure_cli_logging()

    try:
        flask_app = create_app()
    except Exception:
        logger.exception("Falha ao inicializar a aplicação para o ciclo de backup.")
        return EXIT_STARTUP_FAILURE

    try:
        with flask_app.app_context():
            result = run_backup_cycle(force=True)
    except Exception:
        logger.exception("Ciclo de backup falhou.")
        return EXIT_RUNTIME_FAILURE

    sync_result = result.get("sync") or {}
    if sync_result.get("skipped"):
        logger.info(
            "Ciclo de backup pulado por política: %s",
            sync_result.get("reason") or "sem motivo informado",
        )
        return EXIT_OK

    snapshot_path = (sync_result.get("snapshot") or {}).get("database_path") or ""
    retention = result.get("retention") or {}
    logger.info(
        "Ciclo de backup concluído: snapshot=%s retencao_removidos=%d upload_drives=%s",
        snapshot_path or "n/d",
        len(retention.get("deleted") or []),
        result.get("drive_upload_source_path") or "n/d",
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
