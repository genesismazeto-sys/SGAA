# coding: utf-8
from flask import g, session

from app.auth import (
    ACCESS_LEVEL_META,
    ACCESS_RESOURCES_META,
    build_access_scope_groups,
    canonicalize_access_level,
    default_access_level_for_user_type,
    merge_resource_scopes,
    normalize_permission_scope,
    permission_scope_label,
    permission_scope_satisfies,
)
from app.db import get_db_connection
from app.db_maintenance import ensure_usuario_access_schema


def _fetch_user_access_overrides(conn, usuario_id: int | None) -> dict[str, str]:
    if not usuario_id:
        return {}
    ensure_usuario_access_schema(conn)
    rows = conn.execute(
        "SELECT recurso, escopo FROM usuarios_permissoes_acesso WHERE usuario_id = ?",
        (usuario_id,),
    ).fetchall()
    overrides = {}
    for row in rows:
        recurso = str(row["recurso"] or "").strip().lower()
        if recurso not in ACCESS_RESOURCES_META:
            continue
        overrides[recurso] = normalize_permission_scope(row["escopo"], "none")
    return overrides


def _build_access_scope_groups_for_level(access_level: str, overrides: dict[str, str]) -> list[dict[str, object]]:
    defaults = merge_resource_scopes(access_level)
    effective_scopes = merge_resource_scopes(access_level, overrides)
    grouped = []
    for group in build_access_scope_groups(effective_scopes):
        items = []
        for item in group["items"]:
            recurso = item["resource"]
            default_scope = defaults.get(recurso, "none")
            override_scope = overrides.get(recurso)
            items.append(
                {
                    **item,
                    "default_scope": default_scope,
                    "default_scope_label": permission_scope_label(default_scope),
                    "override_scope": override_scope,
                    "override_scope_label": permission_scope_label(override_scope) if override_scope else None,
                }
            )
        grouped.append({"label": group["label"], "items": items})
    return grouped


def _load_admin_access_context(conn, usuario_id: int | None = None) -> dict[str, object]:
    if not usuario_id:
        return {
            "is_admin": False,
            "access_level": None,
            "access_level_label": None,
            "overrides": {},
            "effective_scopes": {},
            "scope_groups": [],
        }

    ensure_usuario_access_schema(conn)
    row = conn.execute(
        "SELECT id, tipo, nivel_acesso FROM usuarios WHERE id = ?",
        (usuario_id,),
    ).fetchone()
    if not row or (row["tipo"] or "").strip().lower() != "admin":
        return {
            "is_admin": False,
            "access_level": None,
            "access_level_label": None,
            "overrides": {},
            "effective_scopes": {},
            "scope_groups": [],
        }

    access_level = canonicalize_access_level(
        row["nivel_acesso"],
        default_access_level_for_user_type("admin"),
    )
    overrides = _fetch_user_access_overrides(conn, row["id"])
    effective_scopes = merge_resource_scopes(access_level, overrides)
    return {
        "is_admin": True,
        "access_level": access_level,
        "access_level_label": ACCESS_LEVEL_META.get(access_level, ACCESS_LEVEL_META["administrativo"])["label"],
        "overrides": overrides,
        "effective_scopes": effective_scopes,
        "scope_groups": _build_access_scope_groups_for_level(access_level, overrides),
    }


def _get_current_admin_access_context(force_reload: bool = False) -> dict[str, object]:
    if not force_reload and hasattr(g, "admin_access_context"):
        return g.admin_access_context
    if session.get("user_type") != "admin":
        g.admin_access_context = {
            "is_admin": False,
            "access_level": None,
            "access_level_label": None,
            "overrides": {},
            "effective_scopes": {},
            "scope_groups": [],
        }
        return g.admin_access_context
    g.admin_access_context = _load_admin_access_context(get_db_connection(), session.get("user_id"))
    return g.admin_access_context


def _admin_can(resource: str | None, scope: str = "view", context: dict[str, object] | None = None) -> bool:
    if not resource:
        return False
    auth_context = context or _get_current_admin_access_context()
    if not auth_context.get("is_admin"):
        return False
    effective = auth_context.get("effective_scopes", {})
    return permission_scope_satisfies(effective.get(resource, "none"), scope)
