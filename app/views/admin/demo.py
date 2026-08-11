# coding: utf-8
"""UT-15: dono canonico do cohort "Demo".

1 simbolo relocado de main.py por MOVE-VERBATIM (1 rota: admin_demo_clientes_form_pack,
GET only).  Nenhuma importacao de main; registra apenas rotas legadas via
LegacyRouteSpec.  O escopo de autorizacao dashboard:view compartilhado com o
Dashboard e apenas escopo de autorizacao — nao move o Demo para dashboard.py.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from app.auth import admin_required
from app.views.admin import LegacyRouteSpec, configure_legacy_routes


@admin_required
def admin_demo_clientes_form_pack():
    return render_template("demo_clientes_form_pack.html")


bp_admin_demo = Blueprint(
    "admin_demo_blueprint",
    __name__,
)

LEGACY_ROUTE_SPECS = configure_legacy_routes(
    bp_admin_demo,
    (
        LegacyRouteSpec(
            "/admin/demo/clientes-form-pack",
            "admin_demo_clientes_form_pack",
            admin_demo_clientes_form_pack,
            ("GET",),
        ),
    ),
)
