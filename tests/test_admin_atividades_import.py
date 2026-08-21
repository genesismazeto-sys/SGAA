import io
import re

import pytest

import main


@pytest.fixture(scope="module")
def client():
    with main.app.app_context(): main.init_db()
    with main.app.test_client() as value: yield value


def test_admin_atividades_import_preview_and_confirm(client):
    with main.app.app_context():
        conn=main.get_db_connection()
        norma=conn.execute("SELECT id FROM norma_atividade WHERE eixo='AAC' LIMIT 1").fetchone()
        if not norma:
            conn.execute("INSERT INTO norma_atividade(codigo,eixo,revisao) VALUES('IMPORT-AAC','AAC','1')")
        conn.commit()
    with client.session_transaction() as session: session.update(user_id=1,user_type='admin',user_name='Administrador')
    name='Atividade CSV Teste Nova'
    csv='\n'.join([
        'nome;tipo_atividade;grupo_numero;grupo_descricao;tem_limitacao;tipo_limitacao;limite_horas_total;limite_horas_semestral',
        f'{name};Acadêmica Complementar;7;Grupo Novo;sim;total;12;',
    ])
    response=client.post('/admin/atividades/importar/preview',data={'mode':'upsert','csv_arquivo':(io.BytesIO(csv.encode()),'atividades.csv')},content_type='multipart/form-data')
    assert response.status_code==200
    match=re.search(r'name="preview_key" value="([^"]+)"',response.get_data(as_text=True)); assert match
    assert client.post('/admin/atividades/importar/confirmar',data={'preview_key':match.group(1)}).status_code in (302,303)
    with main.app.app_context():
        conn=main.get_db_connection()
        row=conn.execute("""SELECT v.grupo,v.eixo,v.limite_total,b.id AS base_id FROM atividade_versao v
            JOIN atividade_base b ON b.id=v.atividade_base_id WHERE b.nome_conceito=?""",(name,)).fetchone()
        assert row and row['grupo']=='7 - Grupo Novo' and row['eixo']=='AAC' and row['limite_total']==12
        conn.execute('DELETE FROM atividade_versao WHERE atividade_base_id=?',(row['base_id'],)); conn.execute('DELETE FROM atividade_base WHERE id=?',(row['base_id'],)); conn.commit()
