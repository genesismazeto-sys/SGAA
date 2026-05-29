import os
import re
import logging
import datetime
import secrets as _secrets
from logging.handlers import RotatingFileHandler

from flask import Flask, url_for, request, session, abort, render_template, jsonify
from flask_compress import Compress
from flask_wtf.csrf import CSRFProtect, generate_csrf, CSRFError
from werkzeug.routing import BuildError

from presets_api import bp_presets
from app.db import close_db_connection
from app.views.aluno import bp_aluno
from app.views import core as core_views


# Singleton CSRF instance for templates / view exemptions
csrf = CSRFProtect()


def _is_truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_app_env() -> str:
    raw = (
        os.getenv("APP_ENV")
        or os.getenv("FLASK_ENV")
        or "development"
    ).strip().lower()
    if raw in {"prod", "production"}:
        return "production"
    if raw in {"test", "testing"}:
        return "testing"
    return "development"


def _resolve_secret_key(env: str) -> str:
    raw = os.getenv("APP_SECRET_KEY") or os.getenv("FLASK_SECRET_KEY")
    forbidden = {"ej_atividades_complementares_2025", "change-me", "secret", "test"}
    if raw and raw.strip() and raw.strip() not in forbidden and len(raw.strip()) >= 24:
        return raw.strip()
    if env == "production":
        raise RuntimeError(
            "APP_SECRET_KEY ausente, fraca ou usando o valor padrão público. "
            "Defina uma chave aleatória de pelo menos 32 caracteres antes de subir em produção. "
            "Sugestão: python -c \"import secrets;print(secrets.token_urlsafe(48))\""
        )
    # dev/testing: gera chave efêmera (sessões não persistem entre reinícios)
    return _secrets.token_urlsafe(48)


def _validate_production_runtime_settings() -> None:
    debug_requested = _is_truthy(os.getenv("FLASK_DEBUG", "0")) or _is_truthy(
        os.getenv("DEBUG", "0")
    )
    if debug_requested:
        raise RuntimeError(
            "APP_ENV=production exige DEBUG=False e FLASK_DEBUG=0."
        )

    from app.services.token_encryption import (
        TokenEncryptionConfigError,
        validate_token_encryption_configuration,
    )
    from services.oauth_config import OAuthConfigError, get_public_base_url

    try:
        get_public_base_url()
    except OAuthConfigError as exc:
        raise RuntimeError(str(exc)) from exc

    try:
        validate_token_encryption_configuration(env="production")
    except TokenEncryptionConfigError as exc:
        raise RuntimeError(str(exc)) from exc


def create_app(
    *,
    register_presets_blueprint: bool = True,
    register_aluno_blueprint: bool = True,
) -> Flask:
    """Cria a app Flask com bootstrap canônico e configurações de segurança.

    Em produção, APP_SECRET_KEY é obrigatório, cookies são marcados como Secure
    por padrão e cabeçalhos de segurança (CSP, HSTS, etc.) são ativados.
    """
    env = _resolve_app_env()
    is_production = env == "production"

    app_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(app_dir)
    templates_dir = os.path.join(project_root, "templates")
    static_dir = os.path.join(project_root, "static")

    app = Flask(__name__, template_folder=templates_dir, static_folder=static_dir)
    app.config["APP_ENV"] = env
    app.config["IS_PRODUCTION"] = is_production

    # ----- Segurança / sessão -----
    app.secret_key = _resolve_secret_key(env)
    app.config["SECRET_KEY"] = app.secret_key
    if is_production:
        _validate_production_runtime_settings()

    documentos_alunos_folder = (os.getenv("APP_DOCUMENTOS_ALUNOS_FOLDER") or "").strip()
    if not documentos_alunos_folder:
        documentos_alunos_folder = os.path.join(project_root, "documentos_alunos")

    app.config["UPLOAD_FOLDER"] = os.path.join(project_root, "uploads")
    app.config["DOCUMENTOS_ALUNOS_FOLDER"] = os.path.abspath(documentos_alunos_folder)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB
    app.config["BACKUP_RESTORE_MAX_CONTENT_LENGTH"] = int(
        os.getenv("APP_BACKUP_RESTORE_MAX_CONTENT_LENGTH", str(128 * 1024 * 1024))
    )

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_SAMESITE", "Lax")
    # Cookie Secure: forçado True em produção; configurável fora de produção
    secure_env = os.getenv("SESSION_COOKIE_SECURE")
    if is_production:
        app.config["SESSION_COOKIE_SECURE"] = True
    else:
        app.config["SESSION_COOKIE_SECURE"] = _is_truthy(secure_env)

    # Sessão padrão mais curta em produção (8h). Lembrar-me persiste por mais tempo.
    default_lifetime_hours = 8 if is_production else 24
    lifetime_hours = int(os.getenv("SESSION_LIFETIME_HOURS", str(default_lifetime_hours)))
    app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(hours=max(1, lifetime_hours))

    # Confiar em cabeçalho X-Forwarded-For somente quando explícito (atrás de proxy reverso)
    app.config["TRUST_PROXY_XFF"] = _is_truthy(os.getenv("TRUST_PROXY_XFF", "0"))

    # Rate limit de login
    app.config["LOGIN_MAX_ATTEMPTS"] = int(os.getenv("LOGIN_MAX_ATTEMPTS", "10"))
    app.config["LOGIN_WINDOW_SECONDS"] = int(os.getenv("LOGIN_WINDOW_SECONDS", "600"))
    app.config["LOGIN_ACCOUNT_MAX_ATTEMPTS"] = int(os.getenv("LOGIN_ACCOUNT_MAX_ATTEMPTS", "8"))

    # Bootstrap do admin padrão somente quando o ambiente permitir.
    # Em produção, exige APP_BOOTSTRAP_ADMIN_PASSWORD definido (ou recusa-se a semear).
    bootstrap_default_admin = os.getenv("APP_BOOTSTRAP_DEFAULT_ADMIN")
    if bootstrap_default_admin is None:
        app.config["BOOTSTRAP_DEFAULT_ADMIN"] = not is_production
    else:
        app.config["BOOTSTRAP_DEFAULT_ADMIN"] = _is_truthy(bootstrap_default_admin)
    app.config["BOOTSTRAP_ADMIN_EMAIL"] = (
        os.getenv("APP_BOOTSTRAP_ADMIN_EMAIL", "admin@ej.edu.br").strip().lower()
    )
    app.config["BOOTSTRAP_ADMIN_PASSWORD"] = os.getenv(
        "APP_BOOTSTRAP_ADMIN_PASSWORD", "" if is_production else "admin123"
    )

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["DOCUMENTOS_ALUNOS_FOLDER"], exist_ok=True)

    # Compressão HTTP
    Compress(app)

    # ----- CSRF -----
    # Em testes, o CSRF é desabilitado para preservar a infra existente.
    app.config["WTF_CSRF_ENABLED"] = env != "testing" and not _is_truthy(
        os.getenv("DISABLE_CSRF", "0")
    )
    # Mantém o token CSRF valido enquanto a sessao estiver viva. Anteriormente
    # WTF_CSRF_TIME_LIMIT era 7200s (2h) - menor que PERMANENT_SESSION_LIFETIME
    # (8h em producao, 24h fora). Isso fazia tokens expirarem antes da sessao e
    # gerava 400 "A pagina ficou desatualizada" quando o usuario deixava a tela
    # aberta. O default agora acompanha a vida da sessao; CSRF_TIME_LIMIT no env
    # continua sobrescrevendo se um operador quiser endurecer.
    _default_csrf_time_limit = int(
        app.config["PERMANENT_SESSION_LIFETIME"].total_seconds()
    )
    app.config["WTF_CSRF_TIME_LIMIT"] = int(
        os.getenv("CSRF_TIME_LIMIT", str(_default_csrf_time_limit))
    )
    app.config["WTF_CSRF_SSL_STRICT"] = is_production
    csrf.init_app(app)

    # ----- Templates -----
    app.config["TEMPLATES_AUTO_RELOAD"] = not is_production
    try:
        app.jinja_env.auto_reload = not is_production
    except Exception:
        pass
    try:
        app.jinja_loader.searchpath = [templates_dir]
    except Exception:
        pass

    # Disponibiliza csrf_token() globalmente nos templates
    app.jinja_env.globals["csrf_token"] = generate_csrf

    def route_url(*endpoints, **values):
        last_error = None
        for endpoint in endpoints:
            if not endpoint:
                continue
            try:
                return url_for(endpoint, **values)
            except BuildError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("route_url requires at least one endpoint name")

    app.add_template_global(route_url, name="route_url")

    # ----- Blueprints / rotas core -----
    if register_presets_blueprint:
        app.register_blueprint(bp_presets)
    if register_aluno_blueprint:
        app.register_blueprint(bp_aluno)
    core_specs = [
        ("/", "index", core_views.index, ["GET"]),
        ("/login", "login", core_views.login, ["GET", "POST"]),
        ("/logout", "logout", core_views.logout, ["GET", "POST"]),
    ]
    for rule, endpoint, view_func, methods in core_specs:
        if endpoint in app.view_functions:
            continue
        app.add_url_rule(rule, endpoint=endpoint, view_func=view_func, methods=methods)

    # Login é o único POST público; usa rate limiting próprio. Exempta CSRF
    # (sessão ainda não está estabelecida no primeiro POST de novo usuário).
    try:
        csrf.exempt(core_views.login)
    except Exception:
        pass

    # Endpoint somente-leitura para refrescar o token CSRF a partir do JS sem
    # recarregar a pagina. Usado pelo csrf-shim.js para evitar tokens stale
    # (causa do 400 "A pagina ficou desatualizada"). Requer sessao autenticada
    # para nao expor tokens a anonimos. Como e GET puro, dispensa CSRF.
    def _csrf_token_endpoint():
        if not session.get("user_id"):
            return jsonify({"error": "unauthorized"}), 401
        token = generate_csrf()
        response = jsonify({"csrf_token": token})
        # Tokens nao devem ser cacheados; cada chamada deve ir ao servidor.
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        return response

    if "csrf_token_refresh" not in app.view_functions:
        app.add_url_rule(
            "/csrf-token",
            endpoint="csrf_token_refresh",
            view_func=_csrf_token_endpoint,
            methods=["GET"],
        )

    # ----- Logging -----
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    log_fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    try:
        logs_dir = os.path.join(project_root, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(logs_dir, "app.log")
        if not any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
            rfh = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
            rfh.setFormatter(log_fmt)
            logger.addHandler(rfh)
    except Exception:
        if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
            sh = logging.StreamHandler()
            sh.setFormatter(log_fmt)
            logger.addHandler(sh)

    try:
        app.teardown_appcontext(close_db_connection)
    except Exception:
        pass

    # ----- Cabeçalhos de segurança -----
    csp_default = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com https://apis.google.com https://accounts.google.com; "
        "frame-src 'self' https://accounts.google.com https://picker.googleapis.com https://docs.google.com; "
        "connect-src 'self' https://www.googleapis.com https://oauth2.googleapis.com https://accounts.google.com; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    app.config["CONTENT_SECURITY_POLICY"] = os.getenv("CONTENT_SECURITY_POLICY", csp_default)

    _form_open_re = re.compile(rb"<form\b[^>]*\bmethod\s*=\s*[\"']?post[\"']?[^>]*>", re.IGNORECASE)
    _csrf_input_re = re.compile(rb"name\s*=\s*[\"']?csrf_token[\"']?", re.IGNORECASE)

    def _inject_csrf_into_html(body: bytes, token: str) -> bytes:
        token_bytes = token.encode("utf-8")
        injection = b'<input type="hidden" name="csrf_token" value="' + token_bytes + b'">'

        def _replace(match: "re.Match[bytes]") -> bytes:
            tag = match.group(0)
            # se a tag (ou alguma posição imediatamente após) já tem csrf, deixa
            # a verificação fina será feita por form completo abaixo via bypass.
            return tag + injection

        # Varredura em duas passadas: encontra <form>...</form> e só injeta se ausente
        out = bytearray()
        pos = 0
        # localiza pares <form> ... </form>
        open_iter = list(_form_open_re.finditer(body))
        if not open_iter:
            return body
        # mapeia cada <form ...> para próximo </form>
        cursor = 0
        idx = 0
        while idx < len(open_iter):
            m = open_iter[idx]
            start_open = m.start()
            end_open = m.end()
            # próximo </form>
            end_close = body.find(b"</form>", end_open)
            if end_close == -1:
                # form sem fechamento — copia restante
                out.extend(body[cursor:])
                cursor = len(body)
                break
            block = body[start_open:end_close]
            out.extend(body[cursor:start_open])
            if _csrf_input_re.search(block):
                out.extend(block)
            else:
                out.extend(body[start_open:end_open])
                out.extend(injection)
                out.extend(body[end_open:end_close])
            cursor = end_close
            idx += 1
        out.extend(body[cursor:])
        return bytes(out)

    @app.after_request
    def _apply_security_headers(response):
        # Cabeçalhos básicos
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
        )
        if is_production:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        # CSP
        if app.config.get("CONTENT_SECURITY_POLICY"):
            response.headers.setdefault(
                "Content-Security-Policy", app.config["CONTENT_SECURITY_POLICY"]
            )
        # Para conteúdo HTML autenticado, evita cache em dispositivos compartilhados
        try:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text/html" in content_type and session.get("user_id"):
                response.headers.setdefault(
                    "Cache-Control", "no-store, no-cache, must-revalidate, private"
                )
                response.headers.setdefault("Pragma", "no-cache")
        except Exception:
            pass
        # Auto-injeta csrf_token em todo <form method="post"> em respostas HTML
        try:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if (
                app.config.get("WTF_CSRF_ENABLED")
                and "text/html" in content_type
                and not response.direct_passthrough
                and response.status_code < 400
            ):
                body = response.get_data()
                if body and b"<form" in body.lower():
                    token = generate_csrf()
                    new_body = _inject_csrf_into_html(body, token)
                    if new_body is not body:
                        response.set_data(new_body)
                    # Também expõe token via meta para chamadas AJAX
                    if b"<meta name=\"csrf-token\"" not in body and b"<head" in body.lower():
                        head_idx_lower = body.lower().find(b"<head")
                        head_close = body.find(b">", head_idx_lower)
                        if head_close != -1:
                            updated = response.get_data()
                            insert_at = head_close + 1
                            meta = (
                                b'<meta name="csrf-token" content="'
                                + token.encode("utf-8")
                                + b'">'
                            )
                            response.set_data(updated[:insert_at] + meta + updated[insert_at:])
        except Exception:
            # Nunca falhar o request por causa do enriquecimento de cabeçalhos
            pass
        return response

    @app.errorhandler(CSRFError)
    def _handle_csrf_error(error):
        # Loga com diagnostico detalhado: motivo do CSRFError (token missing,
        # invalid, expired, session mismatch), path, metodo, referrer e quem
        # estava logado. Sem esses campos, diagnosticar 400 em producao e
        # adivinhacao. NUNCA loga o token em si.
        try:
            logger.warning(
                "CSRFError method=%s path=%s description=%r referrer=%r "
                "user_id=%r user_type=%r ua=%r",
                request.method,
                request.path,
                getattr(error, "description", None),
                request.referrer,
                session.get("user_id"),
                session.get("user_type"),
                (request.headers.get("User-Agent") or "")[:160],
            )
        except Exception:
            pass
        try:
            return render_template(
                "400.html",
                mensagem=(
                    "A página ficou desatualizada ou sua sessão expirou. "
                    "Volte para a tela anterior, recarregue a página e tente novamente."
                ),
            ), 400
        except Exception:
            return ("Sessão CSRF inválida. Recarregue a página.", 400)

    return app
