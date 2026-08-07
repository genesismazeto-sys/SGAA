"""UT-2 RED/contract tests — Flask composition-root unification.

Proves, before implementation, that:
  A. GET /health does not yet return the canonical Referrer-Policy.
  B. main.py still duplicates composition-root setup that create_app() owns.
  C. main still owns `add_security_headers` instead of the isolated
     `_legacy_post_response_backup_sync` transitional hook.
  D. the post-UT-2 after_request hook inventory (by __module__) is not yet
     satisfied.

After UT-2 implementation, all assertions below must be GREEN.
"""
from __future__ import annotations

import inspect
import logging
from pathlib import Path

import main

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════
# A. Canonical Referrer-Policy at runtime
# ═══════════════════════════════════════════════════════════════════


def test_health_referrer_policy_is_canonical():
    client = main.app.test_client()
    response = client.get("/health")
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


# ═══════════════════════════════════════════════════════════════════
# B. main.py no longer duplicates composition-root setup
# ═══════════════════════════════════════════════════════════════════


def test_main_no_longer_duplicates_composition_root_setup():
    forbidden_snippets = (
        'app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024',
        "Compress(app)",
        'app.config["TEMPLATES_AUTO_RELOAD"]',
        "app.jinja_loader.searchpath",
        'app.config["DATABASE_PATH"] = DATABASE',
        'app.config["LOCAL_BACKUP_DIR"] = os.getenv(',
        'app.config["CLOUD_BACKUP_DIR"] = os.getenv(',
        'app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = int(',
        'app.config["EXTERNAL_BACKUP_URL"] = os.getenv(',
        'app.config["EXTERNAL_BACKUP_TOKEN"] = os.getenv(',
        'app.config["EXTERNAL_BACKUP_ENABLED"] = os.getenv(',
        "bind_backup_settings_runtime_app(app)",
    )
    present = [snippet for snippet in forbidden_snippets if snippet in MAIN_SOURCE]
    assert present == [], f"main.py still contains duplicate composition-root setup: {present}"


def test_create_app_owns_all_relocated_config_keys():
    from app import create_app

    app = create_app(register_presets_blueprint=False, register_aluno_blueprint=False)
    for key in (
        "DATABASE_PATH",
        "LOCAL_BACKUP_DIR",
        "CLOUD_BACKUP_DIR",
        "CLOUD_SYNC_INTERVAL_SECONDS",
        "EXTERNAL_BACKUP_URL",
        "EXTERNAL_BACKUP_TOKEN",
        "EXTERNAL_BACKUP_ENABLED",
    ):
        assert key in app.config, f"create_app() does not set {key}"


# ═══════════════════════════════════════════════════════════════════
# C. main owns the isolated legacy backup-sync hook, not add_security_headers
# ═══════════════════════════════════════════════════════════════════


def test_main_no_longer_defines_add_security_headers():
    assert not hasattr(main, "add_security_headers")


def test_main_defines_legacy_post_response_backup_sync():
    assert hasattr(main, "_legacy_post_response_backup_sync")
    hook = main._legacy_post_response_backup_sync
    assert hook.__module__ == "main"
    source = inspect.getsource(hook)
    assert "_maybe_sync_database_snapshot" in source
    assert "_run_retention_cleanup" in source
    assert "_maybe_upload_to_drives" in source
    assert "headers" not in source
    assert "Referrer-Policy" not in source


# ═══════════════════════════════════════════════════════════════════
# D. Post-UT-2 after_request hook inventory (measured by __module__)
# ═══════════════════════════════════════════════════════════════════


def test_after_request_inventory_matches_post_ut2_shape():
    hooks = [
        (f.__name__, f.__module__) for f in main.app.after_request_funcs[None]
    ]
    compress_hooks = [h for h in hooks if h[1] == "flask_compress.flask_compress"]
    assert len(compress_hooks) == 1, f"expected exactly one Compress hook, got {hooks}"

    app_hooks = [h for h in hooks if h[1] == "app"]
    assert app_hooks == [("_apply_security_headers", "app")], hooks

    main_hooks = [h for h in hooks if h[1] == "main"]
    assert main_hooks == [("_legacy_post_response_backup_sync", "main")], hooks

    assert len(hooks) == 3, f"unexplained extra after_request hook(s): {hooks}"


def test_hooks_main_count_unchanged_at_seven():
    app = main.app
    main_hooks = [
        f.__name__
        for lst in (
            app.before_request_funcs[None],
            app.after_request_funcs[None],
            app.template_context_processors[None],
        )
        for f in lst
        if f.__module__ == "main"
    ]
    main_hooks += [
        fn.__name__
        for d in app.error_handler_spec.values()
        for h in (d or {}).values()
        for fn in (h or {}).values()
        if fn.__module__ == "main"
    ]
    assert len(main_hooks) == 7, main_hooks
    assert set(main_hooks) == {
        "enforce_admin_access_control",
        "inject_admin_access_helpers",
        "inject_editable_message_templates",
        "not_found",
        "internal_error",
        "handle_large_upload",
        "_legacy_post_response_backup_sync",
    }


# ═══════════════════════════════════════════════════════════════════
# Regression guards — must stay GREEN before and after UT-2
# ═══════════════════════════════════════════════════════════════════


def test_main_logger_identity_and_level_preserved():
    assert main.logger is logging.getLogger("main")
    assert main.logger.level == logging.INFO
    assert main.logger.propagate is True


def test_other_security_headers_still_present_on_health():
    client = main.app.test_client()
    response = client.get("/health")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"


# ═══════════════════════════════════════════════════════════════════
# Declared consequence of removing the duplicate Compress(app) hook:
# `_apply_security_headers` (app) now executes BEFORE compression instead
# of after it (Flask runs after_request in reverse registration order).
# Its CSRF auto-injection (_inject_csrf_into_html / <meta csrf-token>) was
# previously dead code for any gzip-accepting client, because it ran on an
# already-compressed body under the old duplicate-Compress ordering. This
# pins the now-live behavior so it is tested, not silent. Flagged in the
# UT-2 evidence report as requiring explicit supervisor acknowledgement.
# ═══════════════════════════════════════════════════════════════════


def test_csrf_auto_injection_is_live_for_gzip_accepting_clients(monkeypatch):
    import gzip

    monkeypatch.setenv("DISABLE_CSRF", "0")
    from app import create_app

    app = create_app(register_presets_blueprint=False, register_aluno_blueprint=False)
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["SERVER_NAME"] = "localhost"
    app.config["COMPRESS_MIN_SIZE"] = 0

    @app.route("/__ut2_probe_form")
    def _probe_form():
        return "<html><head></head><body><form method=\"post\"></form></body></html>"

    client = app.test_client()
    response = client.get("/__ut2_probe_form", headers={"Accept-Encoding": "gzip"})
    assert response.headers.get("Content-Encoding") == "gzip"
    body = gzip.decompress(response.get_data())
    assert b'name="csrf_token"' in body
    assert b'name="csrf-token"' in body
