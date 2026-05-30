import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    import main as app_main  # type: ignore

    client = app_main.app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 1
        session["user_type"] = "admin"

    response = client.get("/admin/diagnostico/versioned-shadow-reads")
    payload = response.get_json(silent=True) or {}
    summary = {
        "status_code": response.status_code,
        "shadow_read_enabled": payload.get("shadow_read_enabled"),
        "shadow_read_env_raw": payload.get("shadow_read_env_raw"),
    }
    print(json.dumps(summary, ensure_ascii=True))

    if response.status_code != 200:
        return 1
    if payload.get("shadow_read_enabled") is not True:
        return 1
    if payload.get("shadow_read_env_raw") != "1":
        return 1
    if os.getenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ") != "1":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
