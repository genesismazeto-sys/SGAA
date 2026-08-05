from app.db_maintenance import ensure_admin_arquivos_table


def get_admin_arquivo(conn, arquivo_id: int):
    ensure_admin_arquivos_table(conn)
    return conn.execute("SELECT * FROM admin_arquivos WHERE id = ?", (arquivo_id,)).fetchone()
