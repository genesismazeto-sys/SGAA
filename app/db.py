import os
import sqlite3
from flask import g

from app.backup_settings import ensure_backup_settings_schema
from app.academics import (
    DEFAULT_CURSO_TOTAL_HORAS_AAC,
    DEFAULT_CURSO_TOTAL_HORAS_AEU,
    gerar_codigo_turma,
)
from app.db_maintenance import (
    apply_early_schema_migrations,
    apply_schema_migrations,
    ensure_atividade_versioning_schema,
    ensure_matriz_atividade_links_table,
    ensure_matrizes_atividades_table,
    ensure_reportes_table,
    ensure_requisicao_alert_receipts_table,
    ensure_usuario_access_schema,
    ensure_usuario_profile_schema,
)
from app.security.passwords import hash_password
from app.text import ptbr_sqlite_collation


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE = os.getenv("APP_DATABASE", os.path.join(PROJECT_ROOT, "database.db"))


def _sync_database_from_main():
    return DATABASE


def get_db_connection():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        try:
            g.db.create_collation("PTBR_NOACCENT", ptbr_sqlite_collation)
        except Exception:
            pass
        try:
            g.db.execute("PRAGMA foreign_keys = ON")
            g.db.execute("PRAGMA journal_mode = WAL")
            g.db.execute("PRAGMA synchronous = NORMAL")
        except Exception:
            pass
    return g.db


def close_db_connection(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _get_main_db_helpers():
    import main  # type: ignore

    return {
        "get_preferred_matriz_for_curso": main.get_preferred_matriz_for_curso,
        "logger": main.logger,
    }


def _init_db_impl():
    helpers = _get_main_db_helpers()
    default_horas_aac = DEFAULT_CURSO_TOTAL_HORAS_AAC
    default_horas_aeu = DEFAULT_CURSO_TOTAL_HORAS_AEU
    get_preferred_matriz_for_curso = helpers["get_preferred_matriz_for_curso"]
    logger = helpers["logger"]

    conn = get_db_connection()
    apply_early_schema_migrations(conn, logger=logger)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ("admin", "aluno")),
            nivel_acesso TEXT NOT NULL DEFAULT 'administrativo'
        );
        """
    )
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email)")
    except sqlite3.OperationalError:
        pass

    ensure_usuario_access_schema(conn)
    ensure_usuario_profile_schema(conn)
    ensure_backup_settings_schema(conn)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alunos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER UNIQUE,
            nome TEXT NOT NULL,
            matricula TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            turma TEXT,
            turma_id INTEGER,
            foto_perfil TEXT,
            status TEXT DEFAULT 'Ativo' CHECK(status IN ('Ativo', 'Inativo')),
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
        );
        """
    )
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alunos_usuario_id ON alunos(usuario_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alunos_matricula ON alunos(matricula)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alunos_email ON alunos(email)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alunos_turma_id ON alunos(turma_id)")
    except sqlite3.OperationalError:
        pass

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS turmas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            ano INTEGER,
            semestre INTEGER CHECK(semestre IN (1,2)),
            turno TEXT,
            status TEXT NOT NULL DEFAULT 'Ativa' CHECK(status IN ('Ativa','Inativa')),
            numero INTEGER
        );
        """
    )
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_turmas_status ON turmas(status)")
    except sqlite3.OperationalError:
        pass

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS atividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grupo TEXT NOT NULL,
            nome TEXT NOT NULL UNIQUE,
            descricao TEXT,
            limite_horas INTEGER,
            tipo_atividade TEXT NOT NULL DEFAULT 'Acadêmica Complementar' CHECK(tipo_atividade IN ('Acadêmica Complementar', 'Extensão Universitária')),
            tem_limitacao BOOLEAN DEFAULT 0,
            tipo_limitacao TEXT CHECK(tipo_limitacao IN ('total', 'semestral')),
            limite_horas_total INTEGER,
            limite_horas_semestral INTEGER,
            documentos_json TEXT
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS requisicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aluno_id INTEGER,
            atividade_id INTEGER NOT NULL,
            data_solicitacao TEXT NOT NULL,
            data_evento TEXT NOT NULL,
            horas_solicitadas REAL NOT NULL,
            nome_evento TEXT,
            status TEXT NOT NULL CHECK(status IN ('Pendente','Deferida','Deferida Parcialmente','Indeferida','Devolvida')),
            horas_deferidas REAL,
            observacao TEXT,
            arquivo_comprovante TEXT,
            data_processamento TEXT,
            admin_id INTEGER,
            aluno_update_notified_at TEXT,
            aluno_update_seen_at TEXT,
            FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE SET NULL ON UPDATE CASCADE,
            FOREIGN KEY (atividade_id) REFERENCES atividades(id) ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (admin_id) REFERENCES usuarios(id) ON DELETE SET NULL ON UPDATE CASCADE
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS requisicao_arquivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requisicao_id INTEGER NOT NULL,
            label TEXT,
            filename TEXT,
            criado_em TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(requisicao_id) REFERENCES requisicoes(id)
        )
        """
    )

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reqs_aluno ON requisicoes(aluno_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reqs_atividade ON requisicoes(atividade_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reqs_status ON requisicoes(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_req_arquivos_req ON requisicao_arquivos(requisicao_id)")
    except sqlite3.OperationalError:
        pass

    ensure_reportes_table(conn)

    admin_email = "admin@ej.edu.br"
    bootstrap_admin = False
    bootstrap_password = ""
    try:
        from flask import current_app

        admin_email = (current_app.config.get("BOOTSTRAP_ADMIN_EMAIL") or admin_email).strip().lower()
        bootstrap_admin = bool(current_app.config.get("BOOTSTRAP_DEFAULT_ADMIN"))
        bootstrap_password = (current_app.config.get("BOOTSTRAP_ADMIN_PASSWORD") or "").strip()
    except Exception:
        pass

    admin_exists = conn.execute(
        "SELECT 1 FROM usuarios WHERE LOWER(email) = ?",
        (admin_email,),
    ).fetchone()
    if not admin_exists and bootstrap_admin and bootstrap_password:
        hashed_password = hash_password(bootstrap_password)
        conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo, nivel_acesso) VALUES (?, ?, ?, ?, ?)",
            ("Administrador", admin_email, hashed_password, "admin", "admin_total"),
        )

    try:
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(alunos)").fetchall()]
        if "turma_id" not in cols:
            conn.execute("ALTER TABLE alunos ADD COLUMN turma_id INTEGER")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alunos_turma_id ON alunos(turma_id)")
    except sqlite3.OperationalError as exc:
        logger.warning("Migração turma_id já aplicada ou não necessária: %s", exc)

    try:
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(alunos)").fetchall()]
        if "foto_perfil" not in cols:
            conn.execute("ALTER TABLE alunos ADD COLUMN foto_perfil TEXT")
    except sqlite3.OperationalError as exc:
        logger.warning("Migração foto_perfil já aplicada ou não necessária: %s", exc)

    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(requisicoes)").fetchall()]
        if "nome_evento" not in cols:
            conn.execute("ALTER TABLE requisicoes ADD COLUMN nome_evento TEXT")
    except sqlite3.OperationalError as exc:
        logger.warning("Migração nome_evento já aplicada ou não necessária: %s", exc)

    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(requisicoes)").fetchall()]
        if "aluno_update_notified_at" not in cols:
            conn.execute("ALTER TABLE requisicoes ADD COLUMN aluno_update_notified_at TEXT")
    except sqlite3.OperationalError as exc:
        logger.warning("Migração aluno_update_notified_at já aplicada ou não necessária: %s", exc)

    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(requisicoes)").fetchall()]
        if "aluno_update_seen_at" not in cols:
            conn.execute("ALTER TABLE requisicoes ADD COLUMN aluno_update_seen_at TEXT")
    except sqlite3.OperationalError as exc:
        logger.warning("Migração aluno_update_seen_at já aplicada ou não necessária: %s", exc)

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reqs_aluno_update_pending ON requisicoes(aluno_id, aluno_update_seen_at, aluno_update_notified_at)")
    except sqlite3.OperationalError as exc:
        logger.warning("Falha ao garantir índice idx_reqs_aluno_update_pending: %s", exc)

    ensure_requisicao_alert_receipts_table(conn)

    try:
        cols_t = [row["name"] for row in conn.execute("PRAGMA table_info(turmas)").fetchall()]
        if "numero" not in cols_t:
            conn.execute("ALTER TABLE turmas ADD COLUMN numero INTEGER")
    except sqlite3.OperationalError as exc:
        logger.warning("Migração 'numero' já aplicada ou não necessária: %s", exc)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cursos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            codigo TEXT NOT NULL UNIQUE,
            duracao_periodos INTEGER NOT NULL CHECK(duracao_periodos > 0),
            total_horas_aac INTEGER NOT NULL DEFAULT 160 CHECK(total_horas_aac >= 0),
            total_horas_aeu INTEGER NOT NULL DEFAULT 80 CHECK(total_horas_aeu >= 0),
            periodo TEXT NOT NULL DEFAULT 'diurno',
            status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo','inativo'))
        );
        """
    )

    try:
        cols_c = [
            row[1] if isinstance(row, tuple) else row["name"]
            for row in conn.execute("PRAGMA table_info(cursos)").fetchall()
        ]
        if "periodo" not in cols_c:
            conn.execute("ALTER TABLE cursos ADD COLUMN periodo TEXT DEFAULT 'diurno'")
        if "total_horas_aac" not in cols_c:
            conn.execute(
                f"ALTER TABLE cursos ADD COLUMN total_horas_aac INTEGER NOT NULL DEFAULT {default_horas_aac}"
            )
        if "total_horas_aeu" not in cols_c:
            conn.execute(
                f"ALTER TABLE cursos ADD COLUMN total_horas_aeu INTEGER NOT NULL DEFAULT {default_horas_aeu}"
            )
        conn.execute(
            "UPDATE cursos SET total_horas_aac = ? WHERE total_horas_aac IS NULL OR total_horas_aac < 0",
            (default_horas_aac,),
        )
        conn.execute(
            "UPDATE cursos SET total_horas_aeu = ? WHERE total_horas_aeu IS NULL OR total_horas_aeu < 0",
            (default_horas_aeu,),
        )
    except sqlite3.OperationalError:
        pass

    existe_curso = conn.execute("SELECT 1 FROM cursos LIMIT 1").fetchone()
    if not existe_curso:
        conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, total_horas_aac, total_horas_aeu, status) VALUES (?,?,?,?,?,?)",
            ("Geral", "GERAL", 8, default_horas_aac, default_horas_aeu, "ativo"),
        )

    ensure_matrizes_atividades_table(conn)
    ensure_matriz_atividade_links_table(conn)
    ensure_atividade_versioning_schema(conn)

    for migration_sql in [
        "ALTER TABLE turmas ADD COLUMN curso_id INTEGER",
        "ALTER TABLE turmas ADD COLUMN ano_inicio INTEGER",
        "ALTER TABLE turmas ADD COLUMN semestre_inicio INTEGER",
        "ALTER TABLE turmas ADD COLUMN codigo TEXT",
        "ALTER TABLE turmas ADD COLUMN matriz_id INTEGER",
    ]:
        try:
            conn.execute(migration_sql)
        except sqlite3.OperationalError:
            pass

    try:
        cols_t = [row["name"] for row in conn.execute("PRAGMA table_info(turmas)").fetchall()]
        if "ano_fim" not in cols_t:
            conn.execute("ALTER TABLE turmas ADD COLUMN ano_fim INTEGER")
    except sqlite3.OperationalError as exc:
        logger.warning("Migração 'ano_fim' já aplicada ou não necessária: %s", exc)
    try:
        cols_t = [row["name"] for row in conn.execute("PRAGMA table_info(turmas)").fetchall()]
        if "semestre_fim" not in cols_t:
            conn.execute("ALTER TABLE turmas ADD COLUMN semestre_fim INTEGER")
    except sqlite3.OperationalError as exc:
        logger.warning("Migração 'semestre_fim' já aplicada ou não necessária: %s", exc)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_turmas_curso ON turmas(curso_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_turmas_matriz ON turmas(matriz_id);")
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_turma_por_curso ON turmas(curso_id, numero);")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_turma_codigo ON turmas(codigo);")
    except sqlite3.OperationalError:
        pass

    try:
        geral = conn.execute("SELECT id, codigo FROM cursos WHERE codigo='GERAL'").fetchone()
        if geral:
            conn.execute(
                "UPDATE turmas SET curso_id = ? WHERE curso_id IS NULL OR curso_id = 0",
                (geral["id"],),
            )
            turmas_sem_num = conn.execute(
                "SELECT id FROM turmas WHERE numero IS NULL OR numero = 0 ORDER BY id"
            ).fetchall()
            if turmas_sem_num:
                maxnum = conn.execute(
                    "SELECT COALESCE(MAX(numero),0) AS mx FROM turmas"
                ).fetchone()["mx"] or 0
                numero = int(maxnum)
                for turma_row in turmas_sem_num:
                    numero += 1
                    conn.execute(
                        "UPDATE turmas SET numero=? WHERE id=?",
                        (numero, turma_row["id"]),
                    )
            turmas_sem_cod = conn.execute(
                "SELECT id, numero FROM turmas WHERE (codigo IS NULL OR codigo='')"
            ).fetchall()
            for turma_row in turmas_sem_cod:
                codigo = gerar_codigo_turma(geral["codigo"], turma_row["numero"])
                try:
                    conn.execute(
                        "UPDATE turmas SET codigo=? WHERE id=?",
                        (codigo, turma_row["id"]),
                    )
                except sqlite3.IntegrityError:
                    conn.execute(
                        "UPDATE turmas SET codigo=? WHERE id=?",
                        (f"{codigo}-{turma_row['id']}", turma_row["id"]),
                    )
    except Exception as exc:
        logger.warning("População inicial de curso_id/codigo em turmas antigas: %s", exc)

    try:
        turmas_sem_matriz = conn.execute(
            "SELECT id, curso_id FROM turmas WHERE matriz_id IS NULL OR matriz_id = 0"
        ).fetchall()
        for turma_row in turmas_sem_matriz:
            matriz = get_preferred_matriz_for_curso(conn, turma_row["curso_id"])
            if matriz:
                conn.execute(
                    "UPDATE turmas SET matriz_id = ? WHERE id = ?",
                    (matriz["id"], turma_row["id"]),
                )
    except Exception as exc:
        logger.warning("População inicial de matriz_id em turmas antigas: %s", exc)

    apply_schema_migrations(conn, logger=logger)
    conn.commit()


def init_db():
    _sync_database_from_main()
    return _init_db_impl()
