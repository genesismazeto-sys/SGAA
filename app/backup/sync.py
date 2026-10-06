# coding: utf-8
"""CLI de backup: ``python -m app.backup.sync [--scheduled]``.

Executa **um** ciclo automático canônico
(:func:`app.backup.orchestrator.run_backup_cycle`) sob application context —
nunca sob request context. Substitui, como gatilho não-interativo, o hook
pós-resposta que a UT-5 removeu de main.py.

* Sem opção: executa o ciclo sempre (contrato original).
* ``--scheduled``: o despertar da tarefa agendada (UI-C13). Só executa se o
  backup for devido segundo a periodicidade configurada **no SGAA**
  (:mod:`app.backup.automatic`); caso contrário registra e sai limpo.

Os dois modos seguram o bloqueio de ciclo (:mod:`app.backup.lock`), então
nunca correm junto com outro ciclo, com o backup manual ou com uma
restauração, e registram início, decisão, desfechos e fim em
``backup-automatico.log`` (ao lado do ``app.log``).

Este é o único ponto do pacote que depende de ``create_app``; a dependência
fica isolada aqui de propósito. Nada aqui importa ``main``.

Códigos de saída (determinísticos):

    0 -- ciclo executado (snapshot local criado; cada destino relatou o
         próprio desfecho) ou, com --scheduled, pulado de forma limpa
         (não devido, ou outro ciclo em andamento)
    1 -- falha de orquestração/runtime não tratada, após a app subir
         (inclui não conseguir criar o snapshot local)
    2 -- falha ao inicializar a aplicação
    3 -- sem --scheduled: outro ciclo de backup já está em andamento
    4 -- backend de banco configurado não suporta backup por arquivo SQLite
         (U5-E: PostgreSQL); nada foi lido, copiado ou enviado, com ou sem
         --scheduled

Falhas de destino (pasta em nuvem, Google Drive, OneDrive) permanecem
*best-effort*: são independentes entre si, aparecem no log por destino e, por
contrato existente, não transformam o processo em falha.

Sem prompt interativo e sem inicialização de schema.
"""
import argparse
import logging

from app import create_app
from app.backup.automatic import configure_run_log, run_automatic_cycle
from app.backup.capability import SQLiteMaintenanceUnsupported
from app.backup.lock import BackupCycleBusy


logger = logging.getLogger("main")

EXIT_OK = 0
EXIT_RUNTIME_FAILURE = 1
EXIT_STARTUP_FAILURE = 2
EXIT_BUSY = 3
EXIT_UNSUPPORTED_BACKEND = 4

_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def _configure_cli_logging() -> None:
    """Logging comum de CLI: um handler de console, via raiz, mais o log durável.

    O canal ``main`` não recebe handler de console próprio de propósito: ele
    propaga para a raiz configurada por ``basicConfig``, o que evita linhas
    duplicadas. O arquivo ``backup-automatico.log`` é a evidência que sobra de
    uma execução agendada, que não tem console.
    """
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    logger.setLevel(logging.INFO)
    try:
        configure_run_log()
    except OSError:
        logger.warning("Não foi possível abrir o log durável do backup automático.")


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="python -m app.backup.sync")
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="despertar agendado: executa só se o backup for devido pela periodicidade do SGAA",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    trigger = "scheduled" if args.scheduled else "cli"
    _configure_cli_logging()

    try:
        flask_app = create_app()
    except Exception:
        logger.exception("Falha ao inicializar a aplicação para o ciclo de backup (gatilho=%s).", trigger)
        return EXIT_STARTUP_FAILURE

    try:
        with flask_app.app_context():
            outcome = run_automatic_cycle(trigger=trigger)
    except SQLiteMaintenanceUnsupported as exc:
        logger.error("Backup automático indisponível (gatilho=%s): %s", trigger, exc)
        return EXIT_UNSUPPORTED_BACKEND
    except BackupCycleBusy:
        logger.info("Backup automático: outro ciclo de backup está em andamento; nada foi feito (gatilho=%s).", trigger)
        return EXIT_OK if args.scheduled else EXIT_BUSY
    except Exception:
        logger.exception("Ciclo de backup falhou (gatilho=%s).", trigger)
        return EXIT_RUNTIME_FAILURE

    result = outcome.get("result") or {}
    if outcome.get("ran"):
        snapshot_path = (result.get("snapshot") or {}).get("database_path") or ""
        retention = result.get("retention") or {}
        outcomes = result.get("outcomes") or {}
        logger.info(
            "Ciclo de backup concluído: snapshot=%s destinos=%s retencao_removidos=%d",
            snapshot_path or "n/d",
            ", ".join(
                f"{destination}={(outcome or {}).get('status') or 'n/d'}"
                for destination, outcome in outcomes.items()
            )
            or "n/d",
            len(retention.get("deleted") or []),
        )
    logger.info("Backup automático: fim (gatilho=%s, código de saída=%d).", trigger, EXIT_OK)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
