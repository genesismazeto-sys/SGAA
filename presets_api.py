# coding: utf-8
import os
import json
import sys
import sqlite3
from flask import Blueprint, request, jsonify, session, g

PRESETS_PATH = os.path.join(os.path.dirname(__file__), 'presets_data.json')
PRESETS_TABLE = 'configuracoes_presets'
MAX_PAYLOAD_BYTES = 256 * 1024  # 256 KB
MAX_LIST_ENTRIES = 500
MAX_STRING_LEN = 4000
MAX_TITLE_LEN = 200

bp_presets = Blueprint('presets', __name__)


def _resolve_database_path():
    main = sys.modules.get("main")
    if main is not None:
        database = getattr(main, "DATABASE", None)
        if database:
            return database
    return os.getenv("APP_DATABASE", os.path.join(os.path.dirname(__file__), 'database.db'))


def _get_db_connection():
    if 'db' not in g:
        g.db = sqlite3.connect(_resolve_database_path())
        g.db.row_factory = sqlite3.Row
        try:
            g.db.execute("PRAGMA foreign_keys = ON")
            g.db.execute("PRAGMA journal_mode = WAL")
            g.db.execute("PRAGMA synchronous = NORMAL")
        except Exception:
            pass
    return g.db


def _require_admin():
    # Import tardio evita ciclo: app.__init__ importa presets_api durante bootstrap.
    from app.auth import get_admin_permission_requirement

    if session.get("user_type") != "admin":
        return jsonify({"ok": False, "error": "forbidden"}), 403

    requirement = get_admin_permission_requirement(request.endpoint, request.method)
    if requirement is None:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    effective_requirement = getattr(g, "admin_permission_requirement", None)
    if not isinstance(effective_requirement, dict):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    resource, scope = requirement
    if (
        effective_requirement.get("resource") != resource
        or effective_requirement.get("scope") != scope
    ):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    return None


def _is_safe_string(value, max_len: int = MAX_STRING_LEN) -> bool:
    return isinstance(value, str) and len(value) <= max_len


def _sanitize_preset_item(item, kind: str):
    if not isinstance(item, dict):
        raise ValueError(f"{kind} inválido.")

    preset_id = item.get("id")
    titulo = item.get("titulo")
    texto = item.get("texto", "")

    if not isinstance(preset_id, int) or preset_id <= 0:
        raise ValueError(f"{kind} inválido.")
    if not _is_safe_string(titulo, max_len=MAX_TITLE_LEN) or not titulo.strip():
        raise ValueError(f"{kind} inválido.")
    if not _is_safe_string(texto):
        raise ValueError(f"{kind} inválido.")

    return {
        "id": preset_id,
        "titulo": titulo,
        "texto": texto,
    }


def _sanitize_presets(payload):
    if not isinstance(payload, dict):
        raise ValueError("Payload precisa ser um objeto JSON.")
    out = {"respostas": [], "emails": []}
    respostas = payload.get("respostas") or []
    emails = payload.get("emails") or []
    if not isinstance(respostas, list) or not isinstance(emails, list):
        raise ValueError("Listas inválidas.")
    if len(respostas) > MAX_LIST_ENTRIES or len(emails) > MAX_LIST_ENTRIES:
        raise ValueError("Listas excedem o limite de entradas.")
    seen_ids = {"respostas": set(), "emails": set()}
    for item in respostas:
        sanitized = _sanitize_preset_item(item, "Justificativa")
        if sanitized["id"] in seen_ids["respostas"]:
            raise ValueError("Justificativa inválida.")
        seen_ids["respostas"].add(sanitized["id"])
        out["respostas"].append(sanitized)
    for item in emails:
        sanitized = _sanitize_preset_item(item, "Modelo de e-mail")
        if sanitized["id"] in seen_ids["emails"]:
            raise ValueError("Modelo de e-mail inválido.")
        seen_ids["emails"].add(sanitized["id"])
        out["emails"].append(sanitized)
    return out


def ensure_presets_schema(conn):
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {PRESETS_TABLE} (
            tipo TEXT NOT NULL CHECK(tipo IN ('respostas', 'emails')),
            preset_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            texto TEXT NOT NULL DEFAULT '',
            atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (tipo, preset_id)
        )
        """
    )


def _load_legacy_presets_file():
    if not os.path.exists(PRESETS_PATH):
        return {"respostas": [], "emails": []}
    with open(PRESETS_PATH, 'r', encoding='utf-8') as f:
        return _sanitize_presets(json.load(f))


def _replace_presets_in_db(conn, data):
    ensure_presets_schema(conn)
    conn.execute(f"DELETE FROM {PRESETS_TABLE}")
    for tipo in ("respostas", "emails"):
        for item in data.get(tipo, []):
            conn.execute(
                f"""
                INSERT INTO {PRESETS_TABLE} (tipo, preset_id, titulo, texto, atualizado_em)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (tipo, item["id"], item["titulo"], item.get("texto", "")),
            )


def _migrate_legacy_presets_if_needed(conn):
    ensure_presets_schema(conn)
    has_rows = conn.execute(f"SELECT 1 FROM {PRESETS_TABLE} LIMIT 1").fetchone()
    if has_rows:
        return False
    legacy_data = _load_legacy_presets_file()
    if not legacy_data["respostas"] and not legacy_data["emails"]:
        return False
    _replace_presets_in_db(conn, legacy_data)
    conn.commit()
    return True


def load_presets():
    conn = _get_db_connection()
    ensure_presets_schema(conn)
    _migrate_legacy_presets_if_needed(conn)

    out = {"respostas": [], "emails": []}
    rows = conn.execute(
        f"""
        SELECT tipo, preset_id, titulo, texto
          FROM {PRESETS_TABLE}
         ORDER BY tipo, preset_id
        """
    ).fetchall()
    for row in rows:
        out[str(row["tipo"])].append(
            {
                "id": int(row["preset_id"]),
                "titulo": str(row["titulo"]),
                "texto": str(row["texto"] or ""),
            }
        )
    return out


def save_presets(data):
    conn = _get_db_connection()
    sanitized = _sanitize_presets(data)
    _replace_presets_in_db(conn, sanitized)
    conn.commit()
    return sanitized


@bp_presets.route('/admin/api/presets', methods=['GET'])
def get_presets():
    guard = _require_admin()
    if guard is not None:
        return guard
    return jsonify(load_presets())


@bp_presets.route('/admin/api/presets', methods=['POST'])
def post_presets():
    guard = _require_admin()
    if guard is not None:
        return guard
    raw = request.get_data(cache=False, as_text=False) or b""
    if len(raw) > MAX_PAYLOAD_BYTES:
        return jsonify({"ok": False, "error": "payload_too_large"}), 413
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        return jsonify({"ok": False, "error": "invalid_payload", "detail": str(exc)}), 400
    try:
        save_presets(data)
    except ValueError as exc:
        return jsonify({"ok": False, "error": "invalid_payload", "detail": str(exc)}), 400
    return jsonify({"ok": True})
