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


def _sanitize_preset_item(item, kind: str, *, tipo: str = "respostas"):
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

    sanitized = {
        "id": preset_id,
        "titulo": titulo,
        "texto": texto,
    }

    if tipo != "emails":
        # Justificativas keep their historical shape exactly.
        return sanitized

    # prod-1/v7: e-mail models additionally own an outbound subject and may be
    # designated the single default used by the Requisições send action.
    # Import tardio evita ciclo durante bootstrap.
    from app.request_email_render import PlaceholderError, validate_template

    assunto = item.get("assunto", "")
    if not _is_safe_string(assunto, max_len=MAX_TITLE_LEN):
        raise ValueError(f"{kind} inválido.")
    try:
        validate_template(assunto, allow_block=False)
        validate_template(texto, allow_block=True)
    except PlaceholderError as exc:
        raise ValueError(str(exc)) from exc

    sanitized["assunto"] = assunto
    sanitized["is_default"] = 1 if item.get("is_default") else 0
    return sanitized


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
        sanitized = _sanitize_preset_item(item, "Justificativa", tipo="respostas")
        if sanitized["id"] in seen_ids["respostas"]:
            raise ValueError("Justificativa inválida.")
        seen_ids["respostas"].add(sanitized["id"])
        out["respostas"].append(sanitized)
    for item in emails:
        sanitized = _sanitize_preset_item(item, "Modelo de e-mail", tipo="emails")
        if sanitized["id"] in seen_ids["emails"]:
            raise ValueError("Modelo de e-mail inválido.")
        seen_ids["emails"].add(sanitized["id"])
        out["emails"].append(sanitized)

    # At most one default; ux_configuracoes_presets_default enforces this
    # physically, so reject rather than silently picking a winner.
    defaults = [item for item in out["emails"] if item.get("is_default")]
    if len(defaults) > 1:
        raise ValueError("Apenas um modelo de e-mail pode ser o padrão.")
    return out


def ensure_presets_schema(conn):
    """Create `configuracoes_presets` from the single canonical prod-1 authority.

    `configuracoes_presets` is a prod-1 physical-contract table, so a second
    literal `CREATE TABLE` here would be a competing DDL authority: any database
    it created would carry a `sqlite_master.sql` text that `validate_prod1_schema`
    rejects as `prod-1 physical schema contract mismatch`.  The canonical
    statement in `app.prod1_presets_ddl` is the only definition, and it is
    executed verbatim so the stored DDL matches bootstrap byte for byte.

    Existing tables are left untouched -- the statement runs only when absent,
    never as a rebuild or a formatting normalization.

    prod-1/v7 added ``ux_configuracoes_presets_default``.  Dropping the table
    drops its indexes too, so the index is recreated alongside it; otherwise the
    recreated table would be physically incomplete and ``validate_prod1_schema``
    would reject the database.
    """
    # Import tardio evita ciclo: app.__init__ importa presets_api durante bootstrap.
    from app.prod1_presets_ddl import (
        CONFIGURACOES_PRESETS_DEFAULT_INDEX_SQL,
        CONFIGURACOES_PRESETS_TABLE_SQL,
    )

    already_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (PRESETS_TABLE,)
    ).fetchone()
    if already_exists:
        return
    conn.execute(CONFIGURACOES_PRESETS_TABLE_SQL)
    conn.execute(CONFIGURACOES_PRESETS_DEFAULT_INDEX_SQL)


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
                INSERT INTO {PRESETS_TABLE}
                    (tipo, preset_id, titulo, texto, atualizado_em, assunto, is_default)
                VALUES (?, ?, ?, ?, datetime('now'), ?, ?)
                """,
                (
                    tipo,
                    item["id"],
                    item["titulo"],
                    item.get("texto", ""),
                    item.get("assunto", ""),
                    1 if item.get("is_default") else 0,
                ),
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
        SELECT tipo, preset_id, titulo, texto, assunto, is_default
          FROM {PRESETS_TABLE}
         ORDER BY tipo, preset_id
        """
    ).fetchall()
    for row in rows:
        tipo = str(row["tipo"])
        item = {
            "id": int(row["preset_id"]),
            "titulo": str(row["titulo"]),
            "texto": str(row["texto"] or ""),
        }
        if tipo == "emails":
            item["assunto"] = str(row["assunto"] or "")
            item["is_default"] = int(row["is_default"] or 0)
        out[tipo].append(item)
    return out


class DefaultEmailPresetError(RuntimeError):
    """No e-mail model is designated as the default for the send action."""


def get_default_email_preset(conn):
    """The explicitly designated *and usable* outbound model.

    Never falls back to "first row", smallest id, or a hardcoded title: if no
    model is marked default the caller must tell the administrator to choose
    one, rather than silently mailing students from an arbitrary template.

    Being marked default is necessary but not sufficient.  A model with an empty
    subject or an empty body is a half-configured draft, and sending from it
    would put an empty-subject or empty-body message in a student's inbox, so it
    is refused here with the same actionable error class as "no default at all".
    ``ux_configuracoes_presets_default`` already guarantees this query can match
    at most one row.
    """
    row = conn.execute(
        f"""
        SELECT preset_id, titulo, texto, assunto
          FROM {PRESETS_TABLE}
         WHERE tipo='emails' AND is_default=1
        """
    ).fetchone()
    if row is None:
        raise DefaultEmailPresetError(
            "Nenhum modelo de e-mail padrão foi definido em "
            "Pré-definições → E-mails de resposta."
        )
    titulo = str(row["titulo"])
    assunto = str(row["assunto"] or "")
    texto = str(row["texto"] or "")
    missing = []
    if not assunto.strip():
        missing.append("assunto")
    if not texto.strip():
        missing.append("conteúdo")
    if missing:
        raise DefaultEmailPresetError(
            f"O modelo de e-mail padrão \"{titulo}\" está incompleto: preencha "
            f"{' e '.join(missing)} em Pré-definições → E-mails de resposta."
        )
    return {
        "id": int(row["preset_id"]),
        "titulo": titulo,
        "texto": texto,
        "assunto": assunto,
    }


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
