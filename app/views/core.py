from flask import current_app, redirect, render_template, request, session, url_for

from app.auth import (
    ACCESS_LEVEL_META,
    _clear_login_attempts,
    _clear_login_feedback_flashes,
    _client_ip,
    _login_rate_limited,
    _register_login_attempt,
    access_level_label,
    access_level_to_user_type,
    canonicalize_access_level,
    default_access_level_for_user_type,
)
from app.security.passwords import check_password, hash_password, is_legacy_password_hash
from utils.messages import flash


def _get_main_helpers():
    import main  # type: ignore

    return {
        "aluno_url": main.aluno_url,
        "ensure_usuario_access_schema": main.ensure_usuario_access_schema,
        "ensure_usuario_profile_schema": main.ensure_usuario_profile_schema,
        "get_db_connection": main.get_db_connection,
        "logger": main.logger,
        "normalize_usuario_access_for_user_type": getattr(
            main, "normalize_usuario_access_for_user_type", lambda *_a, **_k: None
        ),
    }


def login():
    helpers = _get_main_helpers()
    aluno_url = helpers["aluno_url"]
    get_db_connection = helpers["get_db_connection"]
    normalize_usuario_access_for_user_type = helpers["normalize_usuario_access_for_user_type"]
    logger = helpers["logger"]

    context = {
        "email_value": "",
        "remember_checked": False,
    }
    if request.method == "POST":
        ip = _client_ip()
        email = (request.form.get("email") or "").strip()
        senha = request.form.get("senha") or ""
        remember_me = (request.form.get("remember_me") or "").strip().lower() in ("1", "true", "on", "yes")
        context["email_value"] = email
        context["remember_checked"] = remember_me

        blocked, retry_in = _login_rate_limited(current_app, ip, account=email)
        if blocked:
            _clear_login_feedback_flashes()
            flash(f"Muitas tentativas. Tente novamente em ~{retry_in//60} min.", "error")
            return render_template("login.html", **context), 429
        conn = get_db_connection()
        # Apenas leitura aqui: evitamos writes em endpoints de pre-autentica\u00e7\u00e3o
        # para n\u00e3o virarem vetor de DoS / contention.
        user = conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()

        if user and check_password(user["senha"], senha):
            # Re-hash transparente caso o hash armazenado seja do formato legado.
            try:
                if is_legacy_password_hash(user["senha"]):
                    new_hash = hash_password(senha)
                    conn.execute("UPDATE usuarios SET senha = ? WHERE id = ?", (new_hash, user["id"]))
                    conn.commit()
            except Exception as exc:
                logger.warning("Falha ao migrar hash de senha: %s", exc)

            # Normaliza nivel_acesso quando incompatível com o tipo (ex.: aluno
            # que ficou com nivel "administrativo" por contaminação histórica).
            try:
                normalize_usuario_access_for_user_type(conn, user["id"])
                conn.commit()
                refreshed = conn.execute("SELECT * FROM usuarios WHERE id = ?", (user["id"],)).fetchone()
                if refreshed is not None:
                    user = refreshed
            except Exception as exc:
                logger.warning("Falha ao normalizar nivel_acesso no login: %s", exc)

            session.clear()
            session.permanent = remember_me
            access_level = canonicalize_access_level(
                user["nivel_acesso"] if "nivel_acesso" in user.keys() else None,
                default_access_level_for_user_type(user["tipo"]),
            )
            user_type = access_level_to_user_type(access_level)
            session["user_id"] = user["id"]
            session["user_type"] = user_type
            session["user_name"] = user["nome"]
            session["access_level"] = access_level
            session["perfil"] = access_level_label(access_level)
            if user_type == "aluno":
                foto_row = conn.execute(
                    "SELECT foto_perfil FROM alunos WHERE usuario_id = ?", (user["id"],)
                ).fetchone()
                if foto_row and foto_row["foto_perfil"]:
                    session["foto_perfil"] = foto_row["foto_perfil"]
            elif user_type == "admin" and "foto_perfil" in user.keys() and user["foto_perfil"]:
                session["foto_perfil"] = user["foto_perfil"]

            _clear_login_attempts(ip=ip, account=email)
            if user_type == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(aluno_url("aluno_dashboard"))

        _register_login_attempt(ip, account=email)
        # Loga apenas hash do email para n\u00e3o vazar PII no log
        try:
            import hashlib as _hashlib
            email_hash = _hashlib.sha256(email.encode("utf-8")).hexdigest()[:12] if email else "(vazio)"
        except Exception:
            email_hash = "(?)"
        logger.warning(f"Falha de login email_hash={email_hash} ip={ip}")
        _clear_login_feedback_flashes()
        flash("E-mail ou senha inv\u00e1lidos.", "error")
    return render_template("login.html", **context)


def logout():
    # Limpeza completa da sess\u00e3o; cookie ser\u00e1 sobrescrito pelo Flask.
    session.clear()
    flash("Voc\u00ea foi desconectado.", "info")
    return redirect(url_for("login"))


def index():
    # Google Drive e OneDrive usam callbacks dedicados; a raiz nao encaminha
    # mais respostas OAuth legadas.
    return redirect(url_for("login"))
