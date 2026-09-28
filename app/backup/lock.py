# coding: utf-8
"""Exclusão mútua entre ciclos de backup (UI-C13).

Um ciclo de backup cria snapshot local, distribui para os destinos e aplica a
retenção por local. Dois ciclos simultâneos -- o agendado e o manual, ou dois
manuais -- disputariam o ``latest/``, a retenção e os envios. Este módulo é o
único dono do bloqueio que os serializa.

O bloqueio é do sistema operacional sobre um arquivo na pasta de backup local
(``msvcrt.locking`` no Windows, ``fcntl.flock`` fora dele): ele pertence ao
handle aberto, então some sozinho quando o processo termina -- inclusive por
queda --, e não existe "lock velho" a limpar. O arquivo em si é só a âncora e
pode continuar existindo. Quem não consegue o bloqueio recebe
:class:`BackupCycleBusy` imediatamente; ninguém espera.
"""
from __future__ import annotations

import contextlib
import os

LOCK_FILENAME = ".sgaa-backup.lock"


class BackupCycleBusy(RuntimeError):
    """Outro ciclo de backup está em andamento para a mesma pasta local."""


def _try_lock(handle) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def backup_cycle_lock(local_backup_dir: str):
    """Mantém o bloqueio de ciclo de backup durante o bloco ``with``.

    Levanta :class:`BackupCycleBusy` se outro ciclo (neste ou em outro
    processo) já o detém.
    """
    directory = os.path.abspath(str(local_backup_dir or ""))
    os.makedirs(directory, exist_ok=True)
    handle = open(os.path.join(directory, LOCK_FILENAME), "a+b")
    try:
        if not _try_lock(handle):
            raise BackupCycleBusy("Outro backup está em andamento.")
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()


__all__ = ["BackupCycleBusy", "LOCK_FILENAME", "backup_cycle_lock"]
