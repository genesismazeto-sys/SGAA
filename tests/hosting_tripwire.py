"""Filesystem write tripwire for the hosted-runtime proofs -- TEST ONLY.

A hosted process owns no durable disk.  The tripwire records and REFUSES any
write-shaped filesystem call whose target lies outside the allowed roots (the
scratch root), and any SQLite connection, so a test can assert "zero writes"
instead of trusting that nothing happened to be attempted.  It is
deliberately a recorder with teeth, not a mock: the refused call raises
``OSError(EROFS)``, exactly what a read-only platform filesystem does (a
``PermissionError`` would make ``tempfile.mkstemp`` retry for minutes on Windows).

Patched: ``builtins.open`` / ``io.open`` (any non-read mode), ``os.open`` (write
flags), ``os.mkdir`` / ``os.makedirs``, ``os.remove`` / ``os.unlink``,
``os.rename`` / ``os.replace``, ``os.rmdir``, ``os.chmod`` / ``os.utime``,
``os.symlink`` / ``os.link``, ``sqlite3.connect``.
"""

from __future__ import annotations

import builtins
import errno
import io
import os
import sqlite3

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _normal(path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


class FilesystemTripwire:
    def __init__(self, allowed_roots=(), *, block_sqlite: bool = True) -> None:
        self.allowed = tuple(_normal(root) for root in allowed_roots)
        self.block_sqlite = block_sqlite
        self.attempts: list[tuple[str, str]] = []
        self._saved: list[tuple[object, str, object]] = []

    # -- policy ------------------------------------------------------------

    def _inside(self, path: str) -> bool:
        return any(path == root or path.startswith(root + os.sep) for root in self.allowed)

    def _check(self, operation: str, target) -> None:
        if isinstance(target, int):  # a file descriptor: already authorised when opened
            return
        path = _normal(target)
        if not self._inside(path):
            self.attempts.append((operation, path))
            raise OSError(errno.EROFS, "write refused by the hosted-runtime tripwire", path)

    # -- patching ----------------------------------------------------------

    def _patch(self, owner, name: str, replacement) -> None:
        self._saved.append((owner, name, getattr(owner, name)))
        setattr(owner, name, replacement)

    def __enter__(self) -> "FilesystemTripwire":
        real_open = builtins.open

        def guarded_open(file, mode="r", *args, **kwargs):
            if any(flag in str(mode) for flag in "wax+"):
                self._check("open", file)
            return real_open(file, mode, *args, **kwargs)

        real_os_open = os.open

        def guarded_os_open(path, flags, *args, **kwargs):
            if flags & _WRITE_FLAGS:
                self._check("os.open", path)
            return real_os_open(path, flags, *args, **kwargs)

        def one_path(operation, original):
            def wrapper(path, *args, **kwargs):
                self._check(operation, path)
                return original(path, *args, **kwargs)

            return wrapper

        def two_paths(operation, original):
            def wrapper(source, destination, *args, **kwargs):
                self._check(operation, source)
                self._check(operation, destination)
                return original(source, destination, *args, **kwargs)

            return wrapper

        def refused_sqlite(*args, **kwargs):
            self.attempts.append(("sqlite3.connect", "<database>"))
            raise OSError(errno.EROFS, "sqlite3.connect refused by the hosted-runtime tripwire")

        self._patch(builtins, "open", guarded_open)
        self._patch(io, "open", guarded_open)
        self._patch(os, "open", guarded_os_open)
        for name in ("mkdir", "remove", "unlink", "rmdir", "chmod", "utime"):
            self._patch(os, name, one_path(f"os.{name}", getattr(os, name)))
        for name in ("rename", "replace", "symlink", "link"):
            self._patch(os, name, two_paths(f"os.{name}", getattr(os, name)))
        self._patch(os, "makedirs", one_path("os.makedirs", os.makedirs))
        if self.block_sqlite:
            self._patch(sqlite3, "connect", refused_sqlite)
        return self

    def __exit__(self, *exc_info) -> None:
        for owner, name, original in reversed(self._saved):
            setattr(owner, name, original)
        self._saved.clear()


__all__ = ["FilesystemTripwire"]
