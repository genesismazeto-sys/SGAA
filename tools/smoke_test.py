import json
import sys
import traceback
import os

# garantir que a pasta raiz (src) esteja no sys.path
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

try:
    import main
except Exception as e:
    print("IMPORT_ERROR:", e)
    traceback.print_exc()
    sys.exit(2)

app = main.app

out = {}
try:
    with app.app_context():
        # inicializa/migra DB
        main.init_db()
        client = app.test_client()
        # /health
        r = client.get('/health')
        out['health_code'] = r.status_code
        try:
            out['health_json'] = r.get_json()
        except Exception:
            out['health_data'] = r.data.decode('utf-8')[:200]
        # /login (GET)
        r2 = client.get('/login')
        out['login_code'] = r2.status_code
        out['login_html_len'] = len(r2.data)

    print(json.dumps(out, ensure_ascii=False, indent=2))
except Exception as e:
    print("RUNTIME_ERROR:", e)
    traceback.print_exc()
    sys.exit(3)
