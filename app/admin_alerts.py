from app.db_maintenance import ensure_admin_alertas_table
from app.sql_dialect import datetime_order


def list_active_admin_alertas(conn):
    ensure_admin_alertas_table(conn)
    return conn.execute(
        f"""
        SELECT id, titulo, mensagem, bg_color, border_color, visivel, criado_em
          FROM admin_alertas
         WHERE visivel = 1
      ORDER BY {datetime_order(conn, "criado_em")} DESC, id DESC
        """
    ).fetchall()
