"""Derive, from the running application, which visual shots render a form.

Why this exists
---------------
The DS-7 expected-delta inventory was built by hand-mapping shot names to
template files. That mapping was wrong for at least one page:
``page_admin_nova_requisicao`` was classified as having no form surface because
``admin_requisicao_nova.html`` contains no ``.field-card``. The route in fact
resolves to different markup, and the page does render labelled required
fields — so it changed when the required marker landed, against the forecast.

Hand-mapping a URL to a template cannot be trusted: routes render templates
chosen at runtime (``base_template|default(...)``, ``render_template`` with a
different name, includes, partials). The only reliable source is the resolved
DOM.

This asks the running app directly: load each shot's page, in its own role, and
report which form markers are actually present. Use it to build the expected
list before a form-affecting change, instead of guessing.

    python -m tools.visual.form_surface
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MARKERS = {
    "field_card": ".field-card",
    "control": ".control",
    "row_label": ".row-label",
    "form_actions": ".form-actions",
    "required": ".field-card .control[required]",
    "disabled": ".field-card .control:disabled",
    "readonly": ".field-card .control[readonly]",
    "toggle": ".toggle-switch",
}

# Counts only VISIBLE matches. Counting raw DOM over-predicts badly: pages such
# as admin_requisicoes carry a whole hidden modal form, so they look like large
# form surfaces while rendering none of it until the modal opens.
PROBE = """() => {
  const vis = el => !!(el.offsetParent || el.getClientRects().length);
  const q = sel => [...document.querySelectorAll(sel)].filter(vis).length;
  return %s;
}"""


def probe() -> dict[str, dict[str, int]]:
    from playwright.sync_api import sync_playwright

    from tools.visual.harness import (
        ADMIN_EMAIL, ADMIN_PASSWORD, ALUNO_EMAIL, ALUNO_PASSWORD,
        AppServer, BLOCKED_HOSTS, FREEZE_TIME_JS, STABILISE_CSS, VENDOR_DIR,
    )
    from tools.visual.catalogue import SHOTS, login

    expr = PROBE % ("{" + ",".join(f'"{k}":q("{v}")' for k, v in MARKERS.items()) + "}")
    results: dict[str, dict[str, int]] = {}
    server = AppServer()
    server.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1440, "height": 900}, device_scale_factor=1,
                reduced_motion="reduce", locale="pt-BR", timezone_id="UTC",
            )
            lucide = (VENDOR_DIR / "lucide.min.js").read_text(encoding="utf-8")

            def route(handler):
                url = handler.request.url
                if "unpkg.com" in url and "lucide" in url:
                    return handler.fulfill(status=200, content_type="application/javascript", body=lucide)
                if any(host in url for host in BLOCKED_HOSTS):
                    return handler.abort()
                return handler.continue_()

            context.route("**/*", route)
            context.add_init_script(FREEZE_TIME_JS)
            page = context.new_page()

            role = None
            for shot in sorted(SHOTS, key=lambda s: (s.role, s.name)):
                if not shot.path:
                    continue
                if shot.role != role:
                    if shot.role == "admin":
                        login(page, server.base_url, ADMIN_EMAIL, ADMIN_PASSWORD)
                    elif shot.role == "aluno":
                        login(page, server.base_url, ALUNO_EMAIL, ALUNO_PASSWORD)
                    else:
                        page.goto(f"{server.base_url}/logout", wait_until="domcontentloaded")
                    role = shot.role
                try:
                    page.goto(f"{server.base_url}{shot.path}", wait_until="domcontentloaded")
                    if shot.after is not None:
                        shot.after(page)
                    page.add_style_tag(content=STABILISE_CSS)
                    results[shot.name] = page.evaluate(expr)
                except Exception as exc:  # noqa: BLE001
                    results[shot.name] = {"error": str(exc)[:70]}
            context.close()
            browser.close()
    finally:
        server.stop()
    return results


def main() -> None:  # pragma: no cover
    data = probe()
    form_shots = {k: v for k, v in data.items() if v.get("field_card") or v.get("form_actions")}
    plain = {k: v for k, v in data.items() if k not in form_shots}
    print(f"FORM SURFACE PRESENT ({len(form_shots)}):")
    for name, counts in sorted(form_shots.items()):
        bits = " ".join(f"{k}={v}" for k, v in counts.items() if v)
        print(f"   {name:<34} {bits}")
    print(f"\nNO FORM SURFACE ({len(plain)}):")
    for name in sorted(plain):
        print(f"   {name}")


if __name__ == "__main__":  # pragma: no cover
    main()
