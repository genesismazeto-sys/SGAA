"""Dono canônico dos helpers de resolução de URL compartilhados pela camada web.

UT-6: módulo folha e neutro.  Não pode importar nenhum pacote de primeira parte
(``app``, ``main``, ``services``, ``utils``) — é justamente essa neutralidade que
permite a ``app/`` consumir ``aluno_url`` sem reintroduzir a dependência reversa
sobre o módulo de composição ``main``.
"""

from __future__ import annotations

from flask import url_for

USE_ALUNO_BLUEPRINT = True


def aluno_url(endpoint: str, **values):
    resolved_endpoint = f"aluno.{endpoint}" if USE_ALUNO_BLUEPRINT else endpoint
    return url_for(resolved_endpoint, **values)
