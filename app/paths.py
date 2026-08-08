# coding: utf-8
"""Contenção de caminhos de sistema de arquivos (dono canônico).

UT-5 moveu ``_path_within_root`` de main.py para cá **sem alterar o
comportamento**: nenhuma política nova de realpath, normcase, symlink/junction
ou UNC foi acrescentada, e nenhum helper adicional de caminho foi criado.

main.py re-exporta este objeto por identidade
(``main._path_within_root is app.paths._path_within_root``), de modo que os
consumidores existentes -- notadamente
``main._best_effort_remove_admin_arquivo_file`` (UT-4) -- continuam chamando
exatamente a mesma função.
"""
import os


def _path_within_root(candidate_path: str, root_path: str | None) -> bool:
    if not candidate_path or not root_path:
        return False
    candidate_abs = os.path.abspath(candidate_path)
    root_abs = os.path.abspath(root_path)
    try:
        return os.path.commonpath([candidate_abs, root_abs]) == root_abs
    except ValueError:
        return False
