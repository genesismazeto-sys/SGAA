from app.db_maintenance import ensure_backup_settings_structural_schema


_runtime_backup_settings_app = None


def bind_backup_settings_runtime_app(flask_app) -> None:
    """Bind the historical module-level Flask app used by backup settings."""
    if flask_app is None:
        raise ValueError("backup-settings runtime app cannot be None")
    global _runtime_backup_settings_app
    _runtime_backup_settings_app = flask_app


def _get_backup_settings_runtime_app():
    if _runtime_backup_settings_app is None:
        raise RuntimeError("backup-settings runtime app has not been bound")
    return _runtime_backup_settings_app


def _backup_settings_defaults() -> dict[str, str]:
    runtime_app = _get_backup_settings_runtime_app()
    return {
        "local_backup_dir": str(runtime_app.config.get("LOCAL_BACKUP_DIR") or ""),
        "cloud_backup_dir": str(runtime_app.config.get("CLOUD_BACKUP_DIR") or ""),
        "cloud_sync_interval_seconds": str(
            runtime_app.config.get("CLOUD_SYNC_INTERVAL_SECONDS") or 600
        ),
        "external_backup_url": str(runtime_app.config.get("EXTERNAL_BACKUP_URL") or ""),
        "external_backup_token": str(
            runtime_app.config.get("EXTERNAL_BACKUP_TOKEN") or ""
        ),
        "external_backup_enabled": (
            "1" if runtime_app.config.get("EXTERNAL_BACKUP_ENABLED") else "0"
        ),
    }


def seed_backup_settings_default_data(
    conn, defaults: dict[str, str]
) -> None:
    for chave, valor in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO configuracoes_backup (chave, valor) VALUES (?, ?)",
            (chave, valor),
        )


def normalize_legacy_backup_sync_interval(
    conn, defaults: dict[str, str]
) -> None:
    intervalo_atual = conn.execute(
        "SELECT valor FROM configuracoes_backup WHERE chave = 'cloud_sync_interval_seconds'"
    ).fetchone()
    if intervalo_atual and str(intervalo_atual["valor"] or "").strip() == "300":
        conn.execute(
            "UPDATE configuracoes_backup SET valor = ?, atualizado_em = datetime('now') WHERE chave = 'cloud_sync_interval_seconds'",
            (defaults["cloud_sync_interval_seconds"],),
        )


def read_backup_settings(
    conn, defaults: dict[str, str]
) -> dict[str, str]:
    rows = conn.execute("SELECT chave, valor FROM configuracoes_backup").fetchall()
    settings = dict(defaults)
    for row in rows:
        settings[str(row["chave"])] = str(row["valor"])
    return settings


def _apply_backup_settings_to_app(settings: dict[str, str]) -> None:
    runtime_app = _get_backup_settings_runtime_app()
    runtime_app.config["LOCAL_BACKUP_DIR"] = (
        settings.get("local_backup_dir")
        or runtime_app.config.get("LOCAL_BACKUP_DIR")
    )
    runtime_app.config["CLOUD_BACKUP_DIR"] = settings.get("cloud_backup_dir") or ""
    try:
        runtime_app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = max(
            0, int(settings.get("cloud_sync_interval_seconds") or 600)
        )
    except (TypeError, ValueError):
        runtime_app.config["CLOUD_SYNC_INTERVAL_SECONDS"] = 600
    runtime_app.config["EXTERNAL_BACKUP_URL"] = (
        settings.get("external_backup_url") or ""
    )
    runtime_app.config["EXTERNAL_BACKUP_TOKEN"] = (
        settings.get("external_backup_token") or ""
    )
    runtime_app.config["EXTERNAL_BACKUP_ENABLED"] = str(
        settings.get("external_backup_enabled") or "0"
    ) in {"1", "true", "True"}


def get_backup_settings(conn) -> dict[str, str]:
    defaults = _backup_settings_defaults()
    return read_backup_settings(conn, defaults)


def ensure_backup_settings_schema(conn) -> None:
    ensure_backup_settings_structural_schema(conn)
    defaults = _backup_settings_defaults()
    seed_backup_settings_default_data(conn, defaults)
    normalize_legacy_backup_sync_interval(conn, defaults)
    settings = read_backup_settings(conn, defaults)
    _apply_backup_settings_to_app(settings)
