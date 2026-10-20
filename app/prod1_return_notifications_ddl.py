"""prod-1/v18: allow a faithful return-for-correction decision snapshot.

Only the decision-status CHECK changes. No columns, data or event generations
are added. SQLite requires a table rebuild; the frozen v7 DDL stays immutable.
"""
from app.prod1_notifications_ddl import (
    NOTIFICATIONS_V7_INDEXES_SQL,
    REQUISICAO_EMAIL_EVENTOS_TABLE_SQL,
)

RETURN_NOTIFICATIONS_V18_DETAILS_JSON = (
    '{"schema_epoch":"prod-1","decision_status_added":"Devolvida","backfill":"none"}'
)
RETURN_NOTIFICATIONS_V18_TABLE_SQL = REQUISICAO_EMAIL_EVENTOS_TABLE_SQL.replace(
    "'Deferida Parcialmente','Indeferida'", "'Deferida Parcialmente','Indeferida','Devolvida'"
)
RETURN_NOTIFICATIONS_V18_STATEMENTS = (
    "CREATE TABLE _return_events_v18 AS SELECT * FROM requisicao_email_eventos",
    "DROP TABLE requisicao_email_eventos",
    RETURN_NOTIFICATIONS_V18_TABLE_SQL,
    "INSERT INTO requisicao_email_eventos SELECT * FROM _return_events_v18",
    "DROP TABLE _return_events_v18",
    *NOTIFICATIONS_V7_INDEXES_SQL[:4],
)
RETURN_NOTIFICATIONS_V18_SCHEMA_OBJECTS_SQL = ";\n".join(RETURN_NOTIFICATIONS_V18_STATEMENTS) + ";"
RETURN_NOTIFICATIONS_V18_MARKER_SQL = (
    "INSERT INTO schema_migrations(version,name,schema_epoch,details_json)\n"
    "VALUES(18,'return_notifications','prod-1','" + RETURN_NOTIFICATIONS_V18_DETAILS_JSON + "');"
)
