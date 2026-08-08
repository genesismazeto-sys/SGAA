# coding: utf-8
"""Canonical owner of the shared Flask template context processors.

UT-3 moved ``inject_admin_access_helpers`` and
``inject_editable_message_templates`` out of ``main.py``.  ``main`` registers
them against the composed app; this module owns the bodies and resolves every
dependency from its canonical owner, so no ``app.web -> main`` edge exists.
"""
from flask import request, session

from app.admin_access import _admin_can, _get_current_admin_access_context
from app.auth import get_admin_permission_requirement, permission_scope_label
from app.db import get_db_connection
from utils.messages import frontend_message_templates


def inject_admin_access_helpers():
    requirement = get_admin_permission_requirement(request.endpoint or "", request.method)
    auth_context = _get_current_admin_access_context() if session.get("user_type") == "admin" else {
        "is_admin": False,
        "access_level": None,
        "access_level_label": None,
        "overrides": {},
        "effective_scopes": {},
        "scope_groups": [],
    }
    current_resource = requirement[0] if requirement else None
    current_scope = requirement[1] if requirement else None

    return {
        "auth_context": auth_context,
        "auth_current_resource": current_resource,
        "auth_current_required_scope": current_scope,
        "auth_current_can_edit": _admin_can(current_resource, "edit", auth_context) if current_resource else False,
        "auth_current_can_full": _admin_can(current_resource, "full", auth_context) if current_resource else False,
        "auth_can": lambda resource, scope="view": _admin_can(resource, scope, auth_context),
        "auth_scope": lambda resource: auth_context.get("effective_scopes", {}).get(resource, "none"),
        "auth_scope_label": permission_scope_label,
    }


def inject_editable_message_templates():
    try:
        templates = frontend_message_templates(get_db_connection())
    except Exception:
        templates = {}
    return {
        "app_frontend_messages": templates,
    }
