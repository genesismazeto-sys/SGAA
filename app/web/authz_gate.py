# coding: utf-8
"""Canonical owner of the admin authorization ``before_request`` gate.

UT-3 moved ``enforce_admin_access_control`` and its two collaborators out of
``main.py``.  ``main`` re-exports them by identity for Flask registration and
backwards compatibility; this module owns the bodies.

Dependencies are resolved directly from their canonical owners
(``app.auth``, ``app.admin_access``, ``app.web.request``, ``utils.messages``)
so that no ``app.web -> main`` edge exists.
"""
import logging

from flask import current_app, g, jsonify, redirect, request, session, url_for

from app.admin_access import _admin_can, _get_current_admin_access_context
from app.auth import (
    ACCESS_RESOURCES_META,
    AdminAuthorizationConfigurationError,
    classify_governed_admin_request,
    permission_scope_label,
)
from app.web.request import _is_ajax_request
from utils.messages import flash, resolve_user_message

# Deliberately the "main" logger, not __name__: the audit stream, its handlers
# and its rotation policy are configured once in main.py and the shadow-audit
# evidence must keep landing on that exact channel.
logger = logging.getLogger("main")


def _admin_access_denied_response(resource: str, required_scope: str):
    message = resolve_user_message(
        f"Seu perfil não possui acesso {permission_scope_label(required_scope).lower()} para {ACCESS_RESOURCES_META.get(resource, {}).get('label', 'este módulo')}."
    )
    if _is_ajax_request():
        return jsonify({
            "ok": False,
            "error": "forbidden",
            "resource": resource,
            "required_scope": required_scope,
            "message": message,
        }), 403
    flash(message, "error")
    return redirect(url_for("admin_dashboard"))


def _audit_missing_admin_authorization_configuration(classification: dict[str, object]) -> None:
    """Production-only shadow evidence; never include request payload or secrets."""
    try:
        logger.error(
            "event=admin_rbac_missing_configuration endpoint=%s method=%s rule=%s "
            "access_level=%s rollout_mode=production_shadow",
            classification.get("endpoint"),
            classification.get("method"),
            classification.get("rule"),
            session.get("access_level"),
        )
    except Exception:
        # Shadow auditing must never turn a missing-policy observation into a
        # production request failure.  Do not recurse into logging or expose
        # request data through another fallback channel.
        return


def enforce_admin_access_control():
    classification = classify_governed_admin_request(
        request.endpoint,
        request.url_rule,
        request.method,
    )
    if session.get("user_type") != "admin":
        return None
    if not classification["governed"]:
        return None
    kind = classification["kind"]
    if kind == "exemption":
        return None
    if kind in {"missing_configuration", "invalid_configuration"}:
        if current_app.config.get("IS_PRODUCTION"):
            _audit_missing_admin_authorization_configuration(classification)
            return None
        raise AdminAuthorizationConfigurationError(
            "Resolved governed endpoint lacks exactly one RBAC requirement or approved exemption: "
            f"{classification.get('endpoint')} {classification.get('method')}"
        )
    requirement = classification["requirement"]
    if requirement is None:  # Defensive invariant; classifier keeps this unreachable.
        raise AdminAuthorizationConfigurationError("Governed request classifier returned no requirement")
    resource, required_scope = requirement
    auth_context = _get_current_admin_access_context(force_reload=True)
    g.admin_permission_requirement = {"resource": resource, "scope": required_scope}
    if _admin_can(resource, required_scope, auth_context):
        return None
    return _admin_access_denied_response(resource, required_scope)
