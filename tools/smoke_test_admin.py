import os, sys, json, traceback
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
try:
    import main
except Exception as e:
    print('IMPORT_ERROR:', e); traceback.print_exc(); sys.exit(2)

app = main.app
with app.app_context():
    main.init_db()
    c = main.get_db_connection()
    # garante admin conhecido
    adm = c.execute("SELECT * FROM usuarios WHERE email=?", ('admin@ej.edu.br',)).fetchone()
    assert adm, 'admin padrão não encontrado'

client = app.test_client()
# login
r = client.post('/login', data={'email':'admin@ej.edu.br','senha':'admin123'}, follow_redirects=False)
print('login_status', r.status_code)
# rota protegida
r2 = client.get('/admin/dashboard')
print('admin_dashboard_status', r2.status_code, 'len', len(r2.data))
