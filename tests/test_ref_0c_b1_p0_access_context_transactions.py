import main
from tests.versioned_test_support import isolated_versioned_app_env


def test_access_validators_are_transaction_neutral_on_complete_prod1_schema(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-context.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            main.ensure_usuario_access_schema(conn)
            before = conn.total_changes
            main.ensure_usuario_access_schema(conn)
            assert conn.total_changes == before


def test_access_validator_preserves_caller_transaction(tmp_path):
    with isolated_versioned_app_env(tmp_path, "access-transaction.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("BEGIN")
            main.ensure_usuario_access_schema(conn)
            assert conn.in_transaction
            conn.rollback()
