# coding: utf-8
"""MP-2 slice 3: administrator import previews live in the database, not on disk.

Store-level proofs run on a fresh v16 SQLite database with an explicit clock;
the view proofs drive the real activity-import routes and use the write
tripwire to show that nothing is written to the upload folder beyond the
single-request upload (the old preview JSON would be caught).
"""

from __future__ import annotations

import datetime
import io
import os
import re
import sqlite3

import pytest

from app import import_previews
from app.prod1_ephemeral_state_ddl import IMPORT_PREVIEW_PAYLOAD_MAX_BYTES
from app.prod1_schema import bootstrap_prod1_schema
from tests.hosting_tripwire import FilesystemTripwire
from tests.session_support import stamp_auth_version

T0 = datetime.datetime(2026, 10, 9, 12, 0, 0)


@pytest.fixture
def conn(tmp_path):
    connection = sqlite3.connect(str(tmp_path / "previews.db"))
    connection.execute("PRAGMA foreign_keys=ON")
    bootstrap_prod1_schema(connection)
    connection.executescript(
        "INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(1,'A1','p1@x.test','x','admin');"
        "INSERT INTO usuarios(id,nome,email,senha,tipo) VALUES(2,'A2','p2@x.test','x','admin');"
    )
    connection.commit()
    yield connection
    connection.close()


PAYLOAD = {"mode": "upsert", "rows": [{"nome": "Atividade", "action": "create"}]}


def test_a_preview_round_trips_for_its_owner_and_is_gone_after_discard(conn):
    token = import_previews.store(conn, usuario_id=1, payload=PAYLOAD, now=T0)
    assert import_previews.load(conn, usuario_id=1, token=token, now=T0) == PAYLOAD
    import_previews.discard(conn, usuario_id=1, token=token)
    assert import_previews.load(conn, usuario_id=1, token=token, now=T0) is None


def test_only_the_digest_is_stored_and_a_peer_cannot_read_or_discard_it(conn):
    token = import_previews.store(conn, usuario_id=1, payload=PAYLOAD, now=T0)
    stored = conn.execute("SELECT token_digest FROM admin_import_previews").fetchone()[0]
    assert token not in stored and len(stored) == 64
    assert import_previews.load(conn, usuario_id=2, token=token, now=T0) is None
    import_previews.discard(conn, usuario_id=2, token=token)
    assert import_previews.load(conn, usuario_id=1, token=token, now=T0) == PAYLOAD


def test_a_preview_expires_after_the_ttl(conn):
    token = import_previews.store(conn, usuario_id=1, payload=PAYLOAD, now=T0)
    inside = T0 + datetime.timedelta(seconds=import_previews.TTL_SECONDS - 1)
    outside = T0 + datetime.timedelta(seconds=import_previews.TTL_SECONDS)
    assert import_previews.load(conn, usuario_id=1, token=token, now=inside) == PAYLOAD
    assert import_previews.load(conn, usuario_id=1, token=token, now=outside) is None


@pytest.mark.parametrize("token", ["", "x", "a" * 129, "é" * 20, None, 7])
def test_a_malformed_key_is_unknown_without_touching_the_database(conn, token):
    assert import_previews.load(conn, usuario_id=1, token=token) is None
    import_previews.discard(conn, usuario_id=1, token=token)


def test_claim_consumes_once_inside_the_callers_transaction_and_rolls_back_with_it(conn):
    from app.db import write_transaction

    token = import_previews.store(conn, usuario_id=1, payload=PAYLOAD, now=T0)
    with pytest.raises(RuntimeError):
        with write_transaction(conn):
            assert import_previews.claim(conn, usuario_id=1, token=token, now=T0) is True
            raise RuntimeError("the import failed after the claim")
    # the claim travelled with the transaction: the preview is still there to retry
    assert import_previews.load(conn, usuario_id=1, token=token, now=T0) == PAYLOAD
    with write_transaction(conn):
        assert import_previews.claim(conn, usuario_id=2, token=token, now=T0) is False  # not the owner
        assert import_previews.claim(conn, usuario_id=1, token=token, now=T0) is True
    with write_transaction(conn):
        assert import_previews.claim(conn, usuario_id=1, token=token, now=T0) is False  # spent
    assert import_previews.load(conn, usuario_id=1, token=token, now=T0) is None


def test_claim_refuses_an_expired_or_malformed_key(conn):
    from app.db import write_transaction

    token = import_previews.store(conn, usuario_id=1, payload=PAYLOAD, now=T0)
    expired = T0 + datetime.timedelta(seconds=import_previews.TTL_SECONDS)
    with write_transaction(conn):
        assert import_previews.claim(conn, usuario_id=1, token=token, now=expired) is False
        assert import_previews.claim(conn, usuario_id=1, token="short", now=T0) is False
    assert import_previews.load(conn, usuario_id=1, token=token, now=T0) == PAYLOAD


def test_a_wrong_key_is_unknown(conn):
    import_previews.store(conn, usuario_id=1, payload=PAYLOAD, now=T0)
    assert import_previews.load(conn, usuario_id=1, token="z" * 32, now=T0) is None


def test_storing_prunes_expired_previews_in_a_bounded_batch(conn):
    for index in range(import_previews.PRUNE_BATCH + 20):
        import_previews.store(conn, usuario_id=1, payload=PAYLOAD, now=T0 + datetime.timedelta(seconds=index))
    later = T0 + datetime.timedelta(seconds=import_previews.TTL_SECONDS * 3)
    import_previews.store(conn, usuario_id=1, payload=PAYLOAD, now=later)
    assert conn.execute("SELECT count(*) FROM admin_import_previews").fetchone()[0] == 20 + 1


def test_an_oversized_payload_is_refused_before_anything_is_written(conn):
    with pytest.raises(import_previews.PreviewTooLarge):
        import_previews.store(conn, usuario_id=1, payload={"x": "y" * IMPORT_PREVIEW_PAYLOAD_MAX_BYTES}, now=T0)
    assert conn.execute("SELECT count(*) FROM admin_import_previews").fetchone()[0] == 0


def test_non_ascii_payloads_survive(conn):
    payload = {"rows": [{"nome": "Extensão Universitária — Conferência"}]}
    token = import_previews.store(conn, usuario_id=1, payload=payload, now=T0)
    assert import_previews.load(conn, usuario_id=1, token=token, now=T0) == payload


# --- the real routes ---------------------------------------------------------------

CSV = "\n".join(
    [
        "nome;tipo_atividade;grupo_numero;grupo_descricao;tem_limitacao;tipo_limitacao;limite_horas_total;limite_horas_semestral",
        "Atividade Preview MP2;Acadêmica Complementar;7;Grupo MP2;sim;total;12;",
    ]
)


@pytest.fixture
def admin_client():
    import main

    with main.app.app_context():
        main.init_db()
    with main.app.test_client() as client:
        with client.session_transaction() as session:
            session.update(user_id=1, user_type="admin", user_name="Administrador")
            stamp_auth_version(session)
        yield client, main.app


def _upload(client):
    return client.post(
        "/admin/atividades/importar/preview",
        data={"mode": "upsert", "csv_arquivo": (io.BytesIO(CSV.encode()), "atividades.csv")},
        content_type="multipart/form-data",
    )


def _cleanup(app):
    import main

    with app.app_context():
        conn = main.get_db_connection()
        conn.execute("DELETE FROM atividade_versao WHERE atividade_base_id IN"
                     " (SELECT id FROM atividade_base WHERE nome_conceito='Atividade Preview MP2')")
        conn.execute("DELETE FROM atividade_base WHERE nome_conceito='Atividade Preview MP2'")
        conn.execute("DELETE FROM admin_import_previews")
        conn.commit()


def test_preview_and_confirm_write_no_preview_file_and_keep_no_upload(admin_client):
    client, app = admin_client
    upload_root = app.config["UPLOAD_FOLDER"]
    allowed = (os.path.join(upload_root, "atividades_imports"),)
    try:
        with FilesystemTripwire(allowed_roots=allowed, block_sqlite=False) as tripwire:
            response = _upload(client)
            assert response.status_code == 200
            key = re.search(r'name="preview_key" value="([^"]+)"', response.get_data(as_text=True)).group(1)
            leftovers = [n for n in os.listdir(allowed[0])] if os.path.isdir(allowed[0]) else []
            assert leftovers == [], "the uploaded CSV must not outlive its request"
            assert not os.path.exists(os.path.join(upload_root, "atividades_import_previews"))
            confirmed = client.post("/admin/atividades/importar/confirmar", data={"preview_key": key})
            assert confirmed.status_code in (302, 303)
        assert tripwire.attempts == []
        assert _base_count(app) == 1
        # one-shot: the key is spent -- the replay is refused as an unknown preview, not applied
        with client.session_transaction() as session:
            session.pop("_flashes", None)
        again = client.post("/admin/atividades/importar/confirmar", data={"preview_key": key})
        assert again.status_code in (302, 303)
        with client.session_transaction() as session:
            flashed = [message for _category, message in session.get("_flashes", [])]
        assert any("não encontrado ou expirado" in message for message in flashed), flashed
        assert not any("Falha ao confirmar" in message for message in flashed), flashed
        assert _base_count(app) == 1
    finally:
        _cleanup(app)


def _base_count(app) -> int:
    import main

    with app.app_context():
        return main.get_db_connection().execute(
            "SELECT count(*) FROM atividade_base WHERE nome_conceito='Atividade Preview MP2'"
        ).fetchone()[0]


def test_a_confirmation_that_loses_the_race_applies_nothing(admin_client, monkeypatch):
    """The preview is claimed by the import transaction: a rival that consumed it first wins."""
    client, app = admin_client
    try:
        key = re.search(r'name="preview_key" value="([^"]+)"', _upload(client).get_data(as_text=True)).group(1)
        real_claim = import_previews.claim

        def rival_first(conn, **kwargs):
            conn.execute("DELETE FROM admin_import_previews")  # the other request committed first
            return real_claim(conn, **kwargs)

        monkeypatch.setattr(import_previews, "claim", rival_first)
        response = client.post("/admin/atividades/importar/confirmar", data={"preview_key": key})
        assert response.status_code in (302, 303)
        assert _base_count(app) == 0
    finally:
        _cleanup(app)


def test_an_oversized_preview_is_refused_with_the_neutral_message_and_stores_nothing(admin_client, monkeypatch):
    import main

    client, app = admin_client
    monkeypatch.setattr(import_previews, "IMPORT_PREVIEW_PAYLOAD_MAX_BYTES", 8)
    try:
        response = _upload(client)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert re.search(r'name="preview_key" value="[^"]+"', html) is None
        assert "Envie um arquivo CSV válido." in html
        with app.app_context():
            assert main.get_db_connection().execute(
                "SELECT count(*) FROM admin_import_previews").fetchone()[0] == 0
    finally:
        _cleanup(app)


def test_a_failed_discard_never_raises_into_a_decided_import(admin_client, monkeypatch):
    from app.views.admin import atividades

    client, app = admin_client

    def broken(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(import_previews, "discard", broken)
    with app.test_request_context("/"):
        from flask import session

        session["user_id"] = 1
        assert atividades._delete_atividades_import_preview("k" * 32) is None


def test_another_administrators_key_is_not_honoured(admin_client):
    import main

    client, app = admin_client
    try:
        response = _upload(client)
        key = re.search(r'name="preview_key" value="([^"]+)"', response.get_data(as_text=True)).group(1)
        with app.app_context():
            conn = main.get_db_connection()
            conn.execute("INSERT OR IGNORE INTO usuarios(id,nome,email,senha,tipo,nivel_acesso)"
                         " VALUES(998,'Outro','outro.admin@example.test','x','admin','admin_total')")
            conn.execute("INSERT OR IGNORE INTO usuario_credenciais(usuario_id,estado) VALUES(998,'personal')")
            conn.commit()
        with app.test_client() as other:
            with other.session_transaction() as session:
                session.update(user_id=998, user_type="admin", user_name="Outro", access_level="admin_total")
                stamp_auth_version(session)
            denied = other.post("/admin/atividades/importar/confirmar", data={"preview_key": key}, follow_redirects=False)
            assert denied.status_code in (302, 303)
        with app.app_context():
            names = main.get_db_connection().execute(
                "SELECT count(*) FROM atividade_base WHERE nome_conceito='Atividade Preview MP2'").fetchone()[0]
            assert names == 0, "a peer confirmed someone else's preview"
    finally:
        with app.app_context():
            conn = main.get_db_connection()
            conn.execute("DELETE FROM usuario_credenciais WHERE usuario_id=998")
            conn.execute("DELETE FROM usuarios WHERE id=998")
            conn.commit()
        _cleanup(app)
