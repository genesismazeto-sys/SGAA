# coding: utf-8
"""Canonical owner of the shared Flask error handlers (404 / 500 / 413).

UT-3 moved ``not_found``, ``internal_error`` and ``handle_large_upload`` out of
``main.py``.  ``main`` registers them against the composed app; this module
owns the bodies.  The ``CSRFError`` handler stays owned by ``app/__init__.py``.
"""
import logging

from flask import current_app, redirect, render_template, request, url_for

from app.presentation import _format_bytes_label
from utils.messages import flash

# Deliberately the "main" logger, not __name__: the 500 traceback stream is
# configured once in main.py and must keep landing on that exact channel.
logger = logging.getLogger("main")


def not_found(e):
    try:
        return render_template("404.html"), 404
    except Exception:
        # fallback simples caso o template 404.html não exista
        return ("<h1>404</h1><p>Página não encontrada.</p>", 404)


def internal_error(e):
    logger.exception("Erro interno do servidor")
    try:
        return (render_template("500.html"), 500)
    except Exception:
        return ("<h1>500</h1><p>Erro interno do servidor.</p>", 500)


def handle_large_upload(e):
    limit_bytes = request.max_content_length or current_app.config.get("MAX_CONTENT_LENGTH")
    flash(f"Arquivo muito grande. Tamanho máximo: {_format_bytes_label(limit_bytes)}.", "error")
    # tenta redirecionar de volta para a página anterior
    ref = request.headers.get('Referer') or url_for('index')
    return redirect(ref)
