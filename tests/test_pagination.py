import os
import pytest
from flask import Flask

# Ensure app can import
os.environ.setdefault("APP_DATABASE", os.path.join(os.path.dirname(__file__), "..", "database.db"))

import importlib

main = importlib.import_module("main")


def setup_module(module):
    with main.app.app_context():
        main.init_db()


def test_admin_requisicoes_paginated():
    app: Flask = main.app
    client = app.test_client()
    # login as admin
    rv = client.post(
        "/login",
        data={"email": "admin@ej.edu.br", "senha": "admin123"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    r = client.get("/admin/requisicoes?page=1&per_page=1")
    assert r.status_code == 200


def test_admin_alunos_turmas_paginated():
    app: Flask = main.app
    client = app.test_client()
    client.post(
        "/login",
        data={"email": "admin@ej.edu.br", "senha": "admin123"},
        follow_redirects=True,
    )
    r1 = client.get("/admin/alunos?page=1&per_page=2")
    r2 = client.get("/admin/turmas?page=1&per_page=2")
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_aluno_minhas_requisicoes_paginated():
    app: Flask = main.app
    with app.app_context():
        conn = main.get_db_connection()
        # create aluno user if not exists
        u = conn.execute("SELECT id FROM usuarios WHERE email=?", ("aluno1@ej.edu.br",)).fetchone()
        if not u:
            pw = main.hash_password("aluno123")
            cur = conn.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?,?,?,?)",
                ("Aluno 1", "aluno1@ej.edu.br", pw, "aluno"),
            )
            uid = cur.lastrowid
            conn.execute(
                "INSERT INTO alunos (usuario_id, nome, matricula, email, status) VALUES (?,?,?,?,?)",
                (uid, "Aluno 1", "M0001", "aluno1@ej.edu.br", "Ativo"),
            )
            conn.commit()
    client = app.test_client()
    # login as aluno
    rv = client.post(
        "/login",
        data={"email": "aluno1@ej.edu.br", "senha": "aluno123"},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    r = client.get("/aluno/requisicoes?page=1&per_page=5")
    assert r.status_code == 200
