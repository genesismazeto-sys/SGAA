import os, sys
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main

@pytest.fixture(scope="module")
def client():
    app = main.app
    with app.app_context():
        main.init_db()
        yield app.test_client()


def test_health_ok(client):
    r = client.get('/health')
    assert r.status_code == 200
    assert r.get_json().get('status') == 'ok'


def test_login_get(client):
    r = client.get('/login')
    assert r.status_code == 200
    assert b'login' in r.data.lower() or b'entrar' in r.data.lower()


def test_admin_dashboard_requires_auth(client):
    r = client.get('/admin/dashboard', follow_redirects=False)
    # deve redirecionar para login quando não autenticado
    assert r.status_code in (302, 301)


def test_admin_login_and_dashboard(client):
    r = client.post('/login', data={'email':'admin@ej.edu.br', 'senha':'admin123'}, follow_redirects=False)
    assert r.status_code in (302, 303)
    # após autenticar, acessar dashboard
    r2 = client.get('/admin/dashboard')
    assert r2.status_code == 200
