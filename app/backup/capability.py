# coding: utf-8
"""Capacidade de manutenção por arquivo SQLite (PostgreSQL-readiness U5-E).

Dono único da pergunta "o backend configurado suporta backup/restauração por
arquivo SQLite?". Snapshot, cópia consistente, ZIP, envio do arquivo aos
destinos e restauração por substituição do arquivo só existem para SQLite; com
PostgreSQL configurado, um ``database.db`` remanescente é dado obsoleto e
nenhuma dessas operações pode rodar nem relatar sucesso.

Contratos:

* A decisão usa a autoridade canônica do backend configurado,
  ``app.db.database_backend()``, resolvida no momento da chamada. Nenhum outro
  módulo de backup lê ``DATABASE_URL``, inspeciona ``database.db`` ou importa o
  driver para decidir isso.
* Classificar não abre conexão alguma (nem SQLite, nem PostgreSQL).
* A recusa é :class:`SQLiteMaintenanceUnsupported`, distinta de erro SQLite,
  erro de arquivo, ciclo ocupado e falha genérica de runtime (não herda de
  ``RuntimeError``/``OSError``), para que rotas, ciclos e a CLI a traduzam.
"""
from __future__ import annotations

from app import db as _app_db

_SQLITE = "sqlite"
_BACKEND_LABELS = {"postgres": "PostgreSQL"}


class SQLiteMaintenanceUnsupported(Exception):
    """Backup/restauração por arquivo SQLite indisponível para o backend ativo."""

    def __init__(self, backend: str):
        self.backend = backend
        self.backend_label = _BACKEND_LABELS.get(backend, backend)
        super().__init__(
            "Backup e restauração por arquivo SQLite indisponíveis: o banco de "
            f"dados configurado é {self.backend_label}."
        )


def configured_backend() -> str:
    return _app_db.database_backend()


def sqlite_maintenance_supported() -> bool:
    return configured_backend() == _SQLITE


def require_sqlite_maintenance_backend() -> None:
    """Recusa, antes de qualquer efeito, se o backend configurado não é SQLite."""
    backend = configured_backend()
    if backend != _SQLITE:
        raise SQLiteMaintenanceUnsupported(backend)


__all__ = [
    "SQLiteMaintenanceUnsupported",
    "configured_backend",
    "require_sqlite_maintenance_backend",
    "sqlite_maintenance_supported",
]
