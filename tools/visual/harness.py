"""SGAA Design System — visual regression harness.

Renders a fixed catalogue of pages and UI states in a real browser at a fixed
viewport and writes deterministic PNGs.

Why this exists
---------------
``tools/ds_css.py`` proves that *moving* CSS declarations cannot change
rendering. It cannot prove anything about a change to selectors, specificity or
markup, because it does not have a DOM. Phases that touch those (DS-3 onward)
need a real browser.

Determinism
-----------
Screenshots are only useful if the only thing that changes between two runs is
the thing under test. This harness controls:

* **Network** — every third-party request is blocked. The app pulls Inter from
  fonts.googleapis.com and the Lucide icon set from ``unpkg.com/lucide@latest``.
  ``@latest`` means the icon library can change without any commit in this repo,
  so leaving it live would make the baseline rot on its own.
* **Fonts** — with Google Fonts blocked, ``--font-sans`` falls through to the
  next entry in its own stack. That is deterministic on one machine but *not*
  across operating systems. See "Limits".
* **Data** — a freshly seeded database, created from scratch for each run.
* **Time** — ``Date`` is pinned so that any rendered timestamp is stable.
* **Motion** — animations, transitions and the caret are disabled; scrollbars
  are hidden. ``prefers-reduced-motion`` is forced.
* **Layout** — fixed viewport, ``deviceScaleFactor`` 1.

Limits — read before trusting a green result
--------------------------------------------
* Baselines are **machine-specific**. With webfonts blocked, text falls back to
  a system font, so a baseline captured on Windows will not match one captured
  on Linux. Regenerate baselines on the machine that will verify them, and treat
  a first-run mismatch on a new machine as "regenerate", not "regression".
* Lucide icons do not render (their script is blocked). Icon *boxes* keep their
  CSS dimensions, so layout is still verified; icon glyphs are not.
* Hover states are captured where scriptable; true pointer-device behaviour is
  not simulated.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BASELINE_DIR = PROJECT_ROOT / "tests" / "visual" / "baseline"
VENDOR_DIR = PROJECT_ROOT / "tests" / "visual" / "vendor"

VIEWPORT = {"width": 1440, "height": 900}
ADMIN_EMAIL = "admin@ej.edu.br"
ADMIN_PASSWORD = "admin123"
# Created by tools/seed_demo_data.py
ALUNO_EMAIL = "aluno1@example.com"
ALUNO_PASSWORD = "aluno123"

# Every external origin the app touches. Blocked for determinism.
BLOCKED_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com", "unpkg.com")

# Injected before every screenshot. Kills every source of frame-to-frame noise
# that is not the thing under test.
STABILISE_CSS = """
*, *::before, *::after {
  transition: none !important;
  animation: none !important;
  caret-color: transparent !important;
  scroll-behavior: auto !important;
}
html { scrollbar-width: none !important; }
::-webkit-scrollbar { display: none !important; }
"""

# Pin Date so any rendered timestamp is stable across runs.
FREEZE_TIME_JS = """
(() => {
  const FIXED = new Date('2026-06-15T12:00:00Z').getTime();
  const _Date = Date;
  function FrozenDate(...args) {
    return args.length ? new _Date(...args) : new _Date(FIXED);
  }
  FrozenDate.prototype = _Date.prototype;
  FrozenDate.now = () => FIXED;
  FrozenDate.parse = _Date.parse;
  FrozenDate.UTC = _Date.UTC;
  window.Date = FrozenDate;
})();
"""


# --------------------------------------------------------------------- server

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class AppServer:
    """A real Flask server on a throwaway database, in a background thread."""

    def __init__(self) -> None:
        # A FIXED path, not mkdtemp(): the backup settings page renders the
        # configured directories, so a random runtime directory would show up
        # as a pixel difference on every single run.
        self.runtime = Path(tempfile.gettempdir()) / "sgaa_visual_runtime"
        shutil.rmtree(self.runtime, ignore_errors=True)
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.port = _free_port()
        self._server = None
        self._thread = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        os.environ.update(
            APP_ENV="testing",
            APP_DATABASE=str(self.runtime / "visual.db"),
            APP_UPLOAD_FOLDER=str(self.runtime / "uploads"),
            APP_DOCUMENTOS_ALUNOS_FOLDER=str(self.runtime / "documentos"),
            APP_LOCAL_BACKUP_DIR=str(self.runtime / "backups" / "local"),
            APP_CLOUD_BACKUP_DIR=str(self.runtime / "backups" / "cloud"),
            APP_LOG_DIR=str(self.runtime / "logs"),
            APP_BOOTSTRAP_DEFAULT_ADMIN="1",
            APP_BOOTSTRAP_ADMIN_PASSWORD=ADMIN_PASSWORD,
            DISABLE_CSRF="1",
            APP_SECRET_KEY="visual-regression-harness-fixed-key-0123456789abcdef",
        )
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))

        import main  # imported after the environment is set, like conftest does
        from werkzeug.serving import make_server

        self._seed()
        self._server = make_server("127.0.0.1", self.port, main.app, threaded=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("app server did not start")

    @staticmethod
    def _seed() -> None:
        """Populate fixed demo data so lists render populated, not empty."""
        from tools.seed_demo_data import seed

        seed()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=10)
        shutil.rmtree(self.runtime, ignore_errors=True)


# -------------------------------------------------------------------- capture

def _install_determinism(context) -> None:
    lucide = VENDOR_DIR / "lucide.min.js"
    lucide_js = lucide.read_text(encoding="utf-8") if lucide.exists() else None

    def route(handler):
        url = handler.request.url
        # The app loads lucide@latest from a CDN. "@latest" means the icon set
        # can change with no commit in this repo, which would rot the baseline
        # on its own. Serve a pinned, vendored copy instead so icons render
        # exactly as in production but never drift.
        if "unpkg.com" in url and "lucide" in url and lucide_js is not None:
            return handler.fulfill(
                status=200,
                content_type="application/javascript; charset=utf-8",
                body=lucide_js,
            )
        if any(host in url for host in BLOCKED_HOSTS):
            return handler.abort()
        return handler.continue_()

    context.route("**/*", route)
    context.add_init_script(FREEZE_TIME_JS)


def _settle(page) -> None:
    page.wait_for_load_state("networkidle")
    # Icons are injected by lucide.createIcons(); pages call it at different
    # points, so force one final pass and wait for the SVGs to land.
    page.evaluate("() => { try { window.lucide && window.lucide.createIcons(); } catch (e) {} }")
    page.add_style_tag(content=STABILISE_CSS)
    page.evaluate("() => document.fonts && document.fonts.ready")
    page.wait_for_timeout(200)


def capture(out_dir: Path, only: set[str] | None = None) -> list[str]:
    """Render the catalogue into ``out_dir``. Returns the shot names written."""
    from playwright.sync_api import sync_playwright

    from tools.visual.catalogue import SHOTS, login

    out_dir.mkdir(parents=True, exist_ok=True)
    server = AppServer()
    server.start()
    written: list[str] = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(
                viewport=VIEWPORT,
                device_scale_factor=1,
                reduced_motion="reduce",
                locale="pt-BR",
                timezone_id="UTC",
            )
            _install_determinism(context)
            page = context.new_page()

            # Shots are grouped by role so we authenticate once per role
            # instead of once per shot: fewer logins, less chance of drift.
            current_role = None
            for shot in sorted(SHOTS, key=lambda s: (s.role, s.name)):
                if only and shot.name not in only:
                    continue
                try:
                    if shot.role != current_role:
                        if shot.role == "admin":
                            login(page, server.base_url, ADMIN_EMAIL, ADMIN_PASSWORD)
                        elif shot.role == "aluno":
                            login(page, server.base_url, ALUNO_EMAIL, ALUNO_PASSWORD)
                        else:
                            page.goto(f"{server.base_url}/logout", wait_until="domcontentloaded")
                        current_role = shot.role

                    shot.render(page, server.base_url, VIEWPORT)
                    _settle(page)
                    target = out_dir / f"{shot.name}.png"
                    page.screenshot(path=str(target), full_page=shot.full_page)
                    written.append(shot.name)
                    print(f"  ok  {shot.name}")
                except Exception as exc:  # noqa: BLE001 - reported, not raised
                    print(f"  !!  {shot.name}: {type(exc).__name__}: {str(exc)[:110]}")

            context.close()
            browser.close()
    finally:
        server.stop()

    return written


def capture_isolated(out_dir: Path) -> list[str]:
    """Capture in a clean subprocess.

    The test-suite conftest binds the application's runtime directories at
    import time, and pages such as /admin/banco-dados render those paths. If the
    gate captured in-process under pytest it would embed pytest's random runtime
    root in the screenshot and disagree with a baseline captured from the CLI.
    Running the very same entry point in a fresh interpreter with the APP_*
    environment stripped makes both paths identical by construction.
    """
    import subprocess

    env = {k: v for k, v in os.environ.items() if not k.startswith("APP_")}
    env.pop("DISABLE_CSRF", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    result = subprocess.run(
        [sys.executable, "-m", "tools.visual.harness", "--out", str(out_dir)],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"visual harness failed (exit {result.returncode})\n"
            f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
        )
    return sorted(p.stem for p in Path(out_dir).glob("*.png"))


def main() -> None:  # pragma: no cover - developer utility
    import argparse

    parser = argparse.ArgumentParser(description="Capture visual baselines.")
    parser.add_argument("--out", type=Path, default=BASELINE_DIR)
    parser.add_argument("--only", nargs="*", help="capture only these shot names")
    args = parser.parse_args()

    names = capture(args.out, set(args.only) if args.only else None)
    print(f"\nwrote {len(names)} screenshots to {args.out}")


if __name__ == "__main__":  # pragma: no cover
    main()
