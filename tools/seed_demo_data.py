import os
import sys

# Garante que estamos na raiz do projeto (src)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from app.db import get_db_connection, init_db
from app.security.passwords import hash_password


def seed():
    app = create_app()
    with app.app_context():
        # Garante que o schema existe
        init_db()
        conn = get_db_connection()

        # Cursos demo
        cursos = [
            ("Tecnologia em Aviação Civil", "TAC", 6),
            ("Engenharia de Produção", "ENGPROD", 10),
            ("Administração", "ADM", 8),
        ]
        for nome, codigo, duracao in cursos:
            conn.execute(
                """
                INSERT OR IGNORE INTO cursos (nome, codigo, duracao_periodos, status)
                VALUES (?, ?, ?, 'ativo')
                """,
                (nome, codigo, duracao),
            )

        # Cria turmas demo (uma por curso, se ainda não existir nenhuma turma para o curso)
        cursos_rows = conn.execute("SELECT id, codigo FROM cursos ORDER BY id").fetchall()
        turmas_criadas = []
        for c in cursos_rows:
            cid = c["id"] if not isinstance(c, tuple) else c[0]
            cod = c["codigo"] if not isinstance(c, tuple) else c[1]
            exists = conn.execute(
                "SELECT COUNT(*) FROM turmas WHERE curso_id = ?", (cid,)
            ).fetchone()[0]
            if not exists:
                nome_turma = f"{cod}-T01"
                conn.execute(
                    """
                    INSERT INTO turmas (nome, status, numero, curso_id, codigo)
                    VALUES (?, 'Ativa', 1, ?, ?)
                    """,
                    (nome_turma, cid, nome_turma),
                )
                turmas_criadas.append(nome_turma)

        # Recarrega turmas para vincular alunos
        turmas_rows = conn.execute(
            "SELECT id, nome FROM turmas ORDER BY id"
        ).fetchall()

        # Usuários/alunos demo
        alunos_demo = [
            ("Aluno Demo 1", "aluno1@example.com", "2025001"),
            ("Aluno Demo 2", "aluno2@example.com", "2025002"),
            ("Aluno Demo 3", "aluno3@example.com", "2025003"),
        ]

        for idx, (nome, email, matricula) in enumerate(alunos_demo):
            # Cria usuário se não existir
            u = conn.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
            if u:
                user_id = u[0] if isinstance(u, tuple) else u["id"]
            else:
                pwd_hash = hash_password("aluno123")
                cur = conn.execute(
                    "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?,?,?,?)",
                    (nome, email, pwd_hash, "aluno"),
                )
                user_id = cur.lastrowid

            # Escolhe uma turma para o aluno (distribui ciclicamente)
            turma_id = None
            if turmas_rows:
                turma_row = turmas_rows[idx % len(turmas_rows)]
                turma_id = turma_row["id"] if not isinstance(turma_row, tuple) else turma_row[0]

            # Cria aluno se não existir, senão atualiza turma
            a = conn.execute(
                "SELECT id FROM alunos WHERE matricula = ?",
                (matricula,),
            ).fetchone()
            if not a:
                conn.execute(
                    "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?,?,?,?, ?, 'Ativo')",
                    (user_id, nome, matricula, email, turma_id),
                )
            else:
                if turma_id is not None:
                    conn.execute(
                        "UPDATE alunos SET turma_id = ? WHERE matricula = ?",
                        (turma_id, matricula),
                    )

        conn.commit()
        print("Seed demo concluído.")
