from __future__ import annotations

from html.parser import HTMLParser
import uuid

import pytest

import main


HOUR_KEYS = ("horas_padrao_academica", "horas_padrao_extensao")


class _MatrixHoursParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "input":
            return
        attributes = dict(attrs)
        name = attributes.get("name")
        if name in {"horas_aac_obrigatorias", "horas_extensao_obrigatorias"}:
            self.values[name] = attributes.get("value", "")


@pytest.fixture
def client():
    with main.app.app_context():
        main.init_db()
        yield main.app.test_client()


@pytest.fixture(autouse=True)
def preserve_hour_settings():
    with main.app.app_context():
        conn = main.get_db_connection()
        original = {
            row["chave"]: (row["valor"], row["atualizado_em"])
            for row in conn.execute(
                "SELECT chave, valor, atualizado_em FROM configuracoes_app "
                "WHERE chave IN (?, ?)",
                HOUR_KEYS,
            ).fetchall()
        }
    yield
    with main.app.app_context():
        conn = main.get_db_connection()
        for key in HOUR_KEYS:
            if key in original:
                value, updated_at = original[key]
                conn.execute(
                    """
                    INSERT INTO configuracoes_app (chave, valor, atualizado_em)
                    VALUES (?, ?, ?)
                    ON CONFLICT(chave) DO UPDATE
                    SET valor=excluded.valor, atualizado_em=excluded.atualizado_em
                    """,
                    (key, value, updated_at),
                )
            else:
                conn.execute("DELETE FROM configuracoes_app WHERE chave = ?", (key,))
        conn.commit()


def _login_admin(client) -> None:
    with client.session_transaction() as session:
        session.update(user_id=1, user_type="admin", user_name="Administrador")


def _save_hour_settings(aac: int, aeu: int) -> None:
    with main.app.app_context():
        conn = main.get_db_connection()
        main.save_horas_settings(
            conn,
            {
                "horas_padrao_academica": str(aac),
                "horas_padrao_extensao": str(aeu),
            },
        )
        conn.commit()


def _new_matrix_hours(client) -> dict[str, int]:
    response = client.get("/admin/adicionar_matriz")
    assert response.status_code == 200
    parser = _MatrixHoursParser()
    parser.feed(response.get_data(as_text=True))
    assert set(parser.values) == {
        "horas_aac_obrigatorias",
        "horas_extensao_obrigatorias",
    }
    return {key: int(value) for key, value in parser.values.items()}


def test_new_matrix_form_uses_saved_160_160_settings(client):
    _login_admin(client)
    _save_hour_settings(160, 160)

    assert _new_matrix_hours(client) == {
        "horas_aac_obrigatorias": 160,
        "horas_extensao_obrigatorias": 160,
    }


def test_new_matrix_form_uses_non_literal_saved_settings(client):
    _login_admin(client)
    _save_hour_settings(175, 125)

    assert _new_matrix_hours(client) == {
        "horas_aac_obrigatorias": 175,
        "horas_extensao_obrigatorias": 125,
    }


def test_matrix_creation_persists_explicit_submitted_hours(client):
    _login_admin(client)
    _save_hour_settings(175, 125)
    matrix_name = f"Matrix explicit hours {uuid.uuid4().hex}"

    with main.app.app_context():
        conn = main.get_db_connection()
        course_id = conn.execute("SELECT id FROM cursos ORDER BY id LIMIT 1").fetchone()["id"]

    response = client.post(
        "/admin/adicionar_matriz",
        data={
            "curso_id": course_id,
            "nome": matrix_name,
            "status": "rascunho",
            "horas_aac_obrigatorias": "181",
            "horas_extensao_obrigatorias": "97",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)

    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT id, horas_aac_obrigatorias, horas_extensao_obrigatorias "
            "FROM matrizes_atividades WHERE nome = ?",
            (matrix_name,),
        ).fetchone()
        assert row is not None
        assert row["horas_aac_obrigatorias"] == 181
        assert row["horas_extensao_obrigatorias"] == 97
        conn.execute("DELETE FROM matrizes_atividades WHERE id = ?", (row["id"],))
        conn.commit()


def test_changing_settings_changes_next_new_matrix_defaults(client):
    _login_admin(client)
    _save_hour_settings(170, 110)
    assert _new_matrix_hours(client) == {
        "horas_aac_obrigatorias": 170,
        "horas_extensao_obrigatorias": 110,
    }

    _save_hour_settings(180, 120)
    assert _new_matrix_hours(client) == {
        "horas_aac_obrigatorias": 180,
        "horas_extensao_obrigatorias": 120,
    }
