import uuid

import pytest

import main


@pytest.fixture(scope="module")
def client():
    with main.app.app_context():
        main.init_db()
    with main.app.test_client() as value:
        yield value


def _login(client):
    with client.session_transaction() as session:
        session.update(user_id=1, user_type="admin", user_name="Administrador")


def _seed(name, axis, group, total=None):
    conn = main.get_db_connection()
    base = conn.execute("INSERT INTO atividade_base(nome_conceito) VALUES(?) RETURNING id", (name,)).fetchone()[0]
    version = conn.execute("""INSERT INTO atividade_versao
        (atividade_base_id,eixo,grupo,limite_total,status)
        VALUES(?,?,?,?,'ativa') RETURNING id""", (base,axis,group,total)).fetchone()[0]
    return base, version


def _cleanup(base_ids):
    conn = main.get_db_connection()
    conn.executemany("DELETE FROM atividade_versao WHERE atividade_base_id=?", [(value,) for value in base_ids])
    conn.executemany("DELETE FROM atividade_base WHERE id=?", [(value,) for value in base_ids])
    conn.commit()


def test_admin_atividades_uses_shared_filter_schema_and_backend_filters(client):
    names = ("AAC Filtro Padrao Limitada", "AAC Filtro Padrao Sem Limite", "AEA Filtro Padrao")
    with main.app.app_context():
        seeds = [_seed(names[0],"AAC","77 - Grupo Filtro",12), _seed(names[1],"AAC","78 - Grupo Filtro"), _seed(names[2],"AEU","79 - Grupo Extensao")]
        main.get_db_connection().commit()
    _login(client)
    try:
        html = client.get("/admin/atividades").get_data(as_text=True)
        assert 'id="filter-schema-data"' in html and '"param": "limitacao"' in html
        limited = client.get("/admin/atividades?limitacao=limitadas").get_data(as_text=True)
        assert names[0] in limited and names[1] not in limited
        extension = client.get("/admin/atividades?tipo=Extens%C3%A3o+Universit%C3%A1ria").get_data(as_text=True)
        assert names[2] in extension and names[0] not in extension
        searched = client.get("/admin/atividades?nome=Padrao+Sem+Limite").get_data(as_text=True)
        assert names[1] in searched and names[0] not in searched
    finally:
        with main.app.app_context(): _cleanup([seed[0] for seed in seeds])


def test_admin_atividades_uses_shared_sort_param_s(client):
    names = ("AAA Ordenacao Atividades", "ZZZ Ordenacao Atividades")
    with main.app.app_context():
        seeds = [_seed(name,"AAC","88 - Grupo Ordenacao") for name in names]
        main.get_db_connection().commit()
    _login(client)
    try:
        html = client.get("/admin/atividades?s=nome&dir=desc").get_data(as_text=True)
        assert html.index(names[1]) < html.index(names[0])
    finally:
        with main.app.app_context(): _cleanup([seed[0] for seed in seeds])
