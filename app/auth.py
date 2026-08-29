import time
import logging
import re
from functools import wraps

from flask import session, redirect, url_for, request
from unidecode import unidecode
from utils.flash import flash_error


logger = logging.getLogger(__name__)


# Histórico de tentativas de login por IP e por conta (em memória do processo).
# Para deploys multi-worker, considerar um backend externo (Redis).
_login_attempts: dict[str, list[float]] = {}
_login_attempts_by_account: dict[str, list[float]] = {}


ACCESS_SCOPES = ("none", "view", "edit", "full")
ACCESS_SCOPE_RANK = {scope: index for index, scope in enumerate(ACCESS_SCOPES)}


ACCESS_RESOURCES_META = {
    "dashboard": {"label": "Início", "group": "Visão geral"},
    "requisicoes": {"label": "Requisições", "group": "Operação"},
    "atividades": {"label": "Atividades", "group": "Cadastros"},
    "matrizes": {"label": "Matrizes de atividades", "group": "Cadastros"},
    "alunos": {"label": "Alunos", "group": "Cadastros"},
    "turmas": {"label": "Turmas", "group": "Cadastros"},
    "cursos": {"label": "Cursos", "group": "Cadastros"},
    "arquivos": {"label": "Arquivos", "group": "Cadastros"},
    "alertas": {"label": "Alertas", "group": "Operação"},
    "reportes": {"label": "Reportes", "group": "Operação"},
    "banco_dados": {"label": "Banco de dados", "group": "Segurança"},
    "acesso": {"label": "Acesso", "group": "Segurança"},
    "configuracoes": {"label": "Configurações", "group": "Sistema"},
    "mensagens": {"label": "Mensagens de sistema", "group": "Sistema"},
    "meus_dados": {"label": "Meus dados", "group": "Conta"},
}


ACCESS_RESOURCE_ORDER = tuple(ACCESS_RESOURCES_META.keys())


ACCESS_RESOURCE_GROUPS = (
    ("Visão geral", ("dashboard",)),
    ("Operação", ("requisicoes", "alertas", "reportes")),
    (
        "Cadastros",
        ("atividades", "matrizes", "alunos", "turmas", "cursos", "arquivos"),
    ),
    ("Segurança", ("banco_dados", "acesso")),
    ("Sistema", ("configuracoes", "mensagens")),
    ("Conta", ("meus_dados",)),
)


ACCESS_LEVEL_META = {
    "admin_total": {"label": "Admin", "user_type": "admin"},
    "consultivo": {"label": "Consultor", "user_type": "admin"},
    "administrativo": {"label": "Coordenador", "user_type": "admin"},
    "usuario": {"label": "Usuário", "user_type": "aluno"},
    "usuario_teste": {"label": "Usuário teste", "user_type": "aluno"},
}

DEFAULT_ACCESS_PASSWORDS = {
    "admin_total": "admin123",
    "consultivo": "consultivo123",
    "administrativo": "admin123",
    "usuario": "aluno123",
    "usuario_teste": "teste123",
}

ACCESS_LEVEL_ALIASES = {
    "admin total": "admin_total",
    "administrador": "admin_total",
    "administrator": "admin_total",
    "consultivo": "consultivo",
    "consultiva": "consultivo",
    "consultor": "consultivo",
    "consultora": "consultivo",
    "administrativo": "administrativo",
    "administrativa": "administrativo",
    "coordenador": "administrativo",
    "coordenadora": "administrativo",
    "admin": "admin_total",
    "usuario": "usuario",
    "usuário": "usuario",
    "aluno": "usuario",
    "usuario teste": "usuario_teste",
    "usuário teste": "usuario_teste",
    "usuario de teste": "usuario_teste",
    "aluno teste": "usuario_teste",
    "teste": "usuario_teste",
}


SECURITY_RESTRICTED_RESOURCES = {"banco_dados", "acesso", "configuracoes", "mensagens"}


PROFILE_RESOURCE_SCOPES = {
    "admin_total": {resource: "full" for resource in ACCESS_RESOURCE_ORDER},
    "administrativo": {
        resource: ("none" if resource in SECURITY_RESTRICTED_RESOURCES else "full")
        for resource in ACCESS_RESOURCE_ORDER
    },
    "consultivo": {
        resource: (
            "none"
            if resource in SECURITY_RESTRICTED_RESOURCES
            else "edit"
            if resource == "meus_dados"
            else "view"
        )
        for resource in ACCESS_RESOURCE_ORDER
    },
    "usuario": {},
    "usuario_teste": {},
}


def normalize_permission_scope(raw, fallback: str = "none") -> str:
    normalized = re.sub(
        r"\s+",
        " ",
        unidecode(str(raw or "")).strip().lower().replace("_", " ").replace("-", " "),
    )
    aliases = {
        "": fallback,
        "nenhum": "none",
        "sem acesso": "none",
        "none": "none",
        "visualizacao": "view",
        "visualizacao apenas": "view",
        "visualizacao total": "view",
        "visualizar": "view",
        "view": "view",
        "leitura": "view",
        "consulta": "view",
        "consultivo": "view",
        "edicao": "edit",
        "editar": "edit",
        "edit": "edit",
        "full": "full",
        "total": "full",
        "acesso total": "full",
        "completo": "full",
    }
    return aliases.get(normalized, fallback)


def permission_scope_label(scope: str) -> str:
    return {
        "none": "Sem acesso",
        "view": "Leitura",
        "edit": "Edição",
        "full": "Total",
    }.get(normalize_permission_scope(scope), "Sem acesso")


def permission_scope_satisfies(current_scope: str, required_scope: str) -> bool:
    current = normalize_permission_scope(current_scope)
    required = normalize_permission_scope(required_scope)
    return ACCESS_SCOPE_RANK[current] >= ACCESS_SCOPE_RANK[required]


def access_level_resource_defaults(access_level: str) -> dict[str, str]:
    resolved = canonicalize_access_level(access_level, default_access_level_for_user_type("admin"))
    defaults = PROFILE_RESOURCE_SCOPES.get(resolved, {})
    return {resource: defaults.get(resource, "none") for resource in ACCESS_RESOURCE_ORDER}


def merge_resource_scopes(access_level: str, overrides: dict[str, str] | None = None) -> dict[str, str]:
    merged = access_level_resource_defaults(access_level)
    for resource, scope in (overrides or {}).items():
        if resource not in ACCESS_RESOURCES_META:
            continue
        merged[resource] = normalize_permission_scope(scope, merged.get(resource, "none"))
    return merged


def build_access_scope_groups(effective_scopes: dict[str, str]) -> list[dict[str, object]]:
    groups = []
    for group_label, resources in ACCESS_RESOURCE_GROUPS:
        items = []
        for resource in resources:
            meta = ACCESS_RESOURCES_META[resource]
            scope = normalize_permission_scope(effective_scopes.get(resource, "none"))
            items.append(
                {
                    "resource": resource,
                    "label": meta["label"],
                    "scope": scope,
                    "scope_label": permission_scope_label(scope),
                }
            )
        groups.append({"label": group_label, "items": items})
    return groups


def is_admin_access_level(access_level: str) -> bool:
    return access_level_to_user_type(access_level) == "admin"


def is_student_access_level(access_level: str) -> bool:
    return access_level_to_user_type(access_level) == "aluno"


def _permission(resource: str, scope: str) -> tuple[str, str]:
    return resource, scope


class AdminAuthorizationConfigurationError(RuntimeError):
    """A resolved governed request has no unambiguous RBAC configuration."""


# Accepted REF-0C-C-A boundary: these three callbacks are administrative
# integration endpoints even though their rules are intentionally outside /admin.
# The map is method-specific so an endpoint-name similarity never expands scope.
NON_ADMIN_RBAC_GOVERNED_ENDPOINTS = {
    "auth_callback": frozenset({"GET"}),
    "google_callback": frozenset({"GET"}),
    "onedrive_callback": frozenset({"GET"}),
}

# REF-0C-C-A accepted that there are no explicit admin exemptions at present.
# Future entries must be literal (endpoint, normalized_method) keys with reviewed
# reason/current-protection/test metadata; wildcard and prefix entries are invalid.
APPROVED_ADMIN_RBAC_EXEMPTIONS: dict[tuple[str, str], dict[str, str]] = {}


def normalize_admin_permission_method(method: str | None, rule_methods=None) -> str:
    """Normalize RBAC method matching; HEAD inherits GET only when GET is allowed."""
    normalized = str(method or "GET").upper().strip()
    allowed = {str(value).upper() for value in (rule_methods or ())}
    if normalized == "HEAD" and "GET" in allowed:
        return "GET"
    return normalized


def classify_governed_admin_request(
    endpoint: str | None,
    url_rule,
    method: str | None,
) -> dict[str, object]:
    """Classify a resolved request without loading a database access context.

    ``url_rule`` is intentionally duck-typed for isolated tests.  The classifier
    relies on Flask's resolved rule, never raw request-path substring guesses.
    """
    rule_text = getattr(url_rule, "rule", None)
    rule_methods = getattr(url_rule, "methods", None)
    normalized_method = normalize_admin_permission_method(method, rule_methods)
    base = {
        "endpoint": endpoint,
        "rule": rule_text,
        "method": normalized_method,
        "requirement": None,
        "exemption": None,
    }
    if not endpoint or not rule_text:
        return {**base, "governed": False, "kind": "outside_boundary"}

    # Flask-generated OPTIONS has no handler execution to authorize.  Explicit
    # OPTIONS handlers do not set this flag and remain subject to the XOR rule.
    if str(method or "").upper().strip() == "OPTIONS" and bool(
        getattr(url_rule, "provide_automatic_options", False)
    ):
        return {**base, "governed": False, "kind": "automatic_options"}

    is_admin_rule = rule_text == "/admin" or rule_text.startswith("/admin/")
    is_external_governed = normalized_method in NON_ADMIN_RBAC_GOVERNED_ENDPOINTS.get(
        endpoint, frozenset()
    )
    if not (is_admin_rule or is_external_governed):
        return {**base, "governed": False, "kind": "outside_boundary"}

    requirement = get_admin_permission_requirement(endpoint, normalized_method)
    exemption = APPROVED_ADMIN_RBAC_EXEMPTIONS.get((endpoint, normalized_method))
    result = {**base, "governed": True, "requirement": requirement, "exemption": exemption}
    if bool(requirement) == bool(exemption):
        return {**result, "kind": "invalid_configuration" if requirement else "missing_configuration"}
    return {**result, "kind": "requirement" if requirement else "exemption"}


def get_admin_permission_requirement(endpoint: str | None, method: str = "GET") -> tuple[str, str] | None:
    if not endpoint:
        return None

    method_norm = normalize_admin_permission_method(method, {"GET", "HEAD"})

    if endpoint == "auth_callback":
        return _permission("banco_dados", "edit")
    if endpoint in {"google_callback", "onedrive_callback"}:
        return _permission("banco_dados", "edit")

    if endpoint == "presets.get_presets":
        return _permission("requisicoes", "view")
    if endpoint == "presets.post_presets":
        return _permission("requisicoes", "edit")

    if not endpoint.startswith("admin"):
        return None

    if endpoint in {"admin_dashboard", "admin_demo_clientes_form_pack"}:
        return _permission("dashboard", "view")

    if endpoint == "admin_meus_dados":
        return _permission("meus_dados", "edit" if method_norm == "POST" else "view")

    if endpoint == "admin_acesso":
        return _permission("acesso", "view")
    if endpoint.startswith("admin_acesso"):
        return _permission("acesso", "full")

    if endpoint == "admin_banco_dados":
        return _permission("banco_dados", "view")
    if endpoint == "admin_banco_dados_download":
        return _permission("banco_dados", "view")
    if endpoint == "admin_banco_dados_backup":
        return _permission("banco_dados", "edit")
    if endpoint == "admin_banco_dados_configuracoes":
        return _permission("banco_dados", "edit")
    if endpoint in {
        "admin_banco_dados_retencao",
        "admin_banco_dados_drive_settings",
        "admin_banco_dados_oauth_start",
        "admin_banco_dados_oauth_disconnect",
        "admin_backup_google_connect",
        "admin_backup_google_upload",
        "admin_backup_onedrive_connect",
        "admin_backup_onedrive_upload",
        "admin_backup_cloud_folders",
        "admin_backup_cloud_folder",
    }:
        return _permission("banco_dados", "edit")
    if endpoint == "admin_banco_dados_restaurar":
        return _permission("banco_dados", "full")
    if endpoint == "admin_banco_dados_restaurar_upload":
        return _permission("banco_dados", "full")
    if endpoint == "admin_banco_dados_excluir":
        return _permission("banco_dados", "full")

    if endpoint == "admin_configuracoes":
        return _permission("configuracoes", "view")
    if endpoint in {
        "admin_configuracoes_horas_padrao_salvar",
        "admin_configuracoes_prazo_adequacao_salvar",
        "admin_configuracoes_tempo_resposta_salvar",
    }:
        return _permission("configuracoes", "edit")
    if endpoint == "admin_configuracoes_tempo_resposta_resetar":
        return _permission("configuracoes", "full")

    if endpoint == "admin_mensagens":
        return _permission("mensagens", "view")
    if endpoint == "admin_mensagens_salvar":
        return _permission("mensagens", "edit")
    if endpoint == "admin_mensagens_resetar":
        return _permission("mensagens", "full")

    if endpoint in {"admin_reportes"}:
        return _permission("reportes", "view")
    if endpoint.startswith("admin_reportes"):
        return _permission("reportes", "full" if endpoint.endswith("deletar") else "edit")

    if endpoint == "admin_alertas":
        return _permission("alertas", "view")
    if endpoint in {"admin_salvar_alerta", "admin_alternar_alerta"}:
        return _permission("alertas", "edit")
    if endpoint == "admin_deletar_alerta":
        return _permission("alertas", "full")

    if endpoint == "admin_arquivos" or endpoint == "admin_visualizar_arquivo":
        return _permission("arquivos", "view")
    if endpoint in {"admin_adicionar_arquivo", "admin_editar_arquivo"}:
        return _permission("arquivos", "edit")
    if endpoint == "admin_deletar_arquivo":
        return _permission("arquivos", "full")

    if endpoint in {"admin_cursos", "admin_detalhes_curso", "admin_visualizar_curso"}:
        return _permission("cursos", "view")
    if endpoint in {"admin_adicionar_curso", "admin_editar_curso"}:
        return _permission("cursos", "edit")
    if endpoint == "admin_deletar_curso":
        return _permission("cursos", "full")

    if endpoint == "admin_importar_requisicoes":
        return _permission("requisicoes", "full")
    if endpoint in {
        "admin_requisicoes",
        "admin_detalhes_requisicao",
        "admin_api_requisicao",
        "admin_api_aluno_requisicao_scope",
    }:
        return _permission("requisicoes", "view")
    if endpoint in {"admin_nova_requisicao", "admin_editar_requisicao", "admin_processar_requisicao"}:
        return _permission("requisicoes", "edit")
    if endpoint == "admin_excluir_requisicao":
        return _permission("requisicoes", "full")

    if endpoint in {"admin_atividades", "admin_atividades_academicas", "admin_atividades_extensao"}:
        return _permission("atividades", "view")
    if endpoint in {"admin_adicionar_atividade", "admin_editar_atividade"}:
        return _permission("atividades", "edit")
    if endpoint in {
        "admin_atividades_importar_preview",
        "admin_atividades_importar_confirmar",
        "admin_deletar_atividade",
        "admin_grupos_renomear",
        "admin_grupos_excluir",
    }:
        return _permission("atividades", "full")

    if endpoint == "admin_alunos":
        return _permission("alunos", "view")
    if endpoint in {"admin_adicionar_aluno", "admin_editar_aluno", "admin_alterar_status_alunos"}:
        return _permission("alunos", "edit")
    if endpoint == "admin_deletar_aluno":
        return _permission("alunos", "full")

    if endpoint in {"admin_turmas", "admin_detalhes_turma"}:
        return _permission("turmas", "view")
    if endpoint in {"admin_adicionar_turma", "admin_editar_turma"}:
        return _permission("turmas", "edit")
    if endpoint in {"admin_deletar_turma", "admin_turmas_importar"}:
        return _permission("turmas", "full")

    if endpoint == "admin_matrizes":
        return _permission("matrizes", "view")
    if endpoint == "admin_adicionar_matriz":
        return _permission("matrizes", "edit")
    if endpoint == "admin_editar_matriz":
        return _permission("matrizes", "edit" if method_norm == "POST" else "view")
    if endpoint in {"admin_excluir_matrizes", "admin_excluir_matriz"}:
        return _permission("matrizes", "full")

    # REF-0C-B1 — Strongly Supported RBAC Mappings (21 HIGH-confidence routes, R1-R21).
    # Accepted diagnosis: docs/refactor/REF_0C_A_RBAC_POLICY_MATRIX_DIAGNOSIS.md (HEAD f977fd6).
    # R22-R24 (admin_diagnostico_*) are intentionally EXCLUDED pending decision D4 and must
    # remain unmapped (return None) until their diagnostic access policy is approved.
    if endpoint in {
        "admin_catalogo_versoes",          # R1  GET  /admin/catalogo-versoes
        "admin_catalogo_versao_detalhe",   # R2  GET  /admin/catalogo-versoes/<base_id>
    }:
        return _permission("atividades", "view")
    if endpoint in {
        "admin_catalogo_nova_base",        # R5/R6   GET+POST /admin/catalogo-versoes/nova-base
        "admin_catalogo_nova_versao",      # R9/R10  GET+POST /admin/catalogo-versoes/<base_id>/nova-versao
        "admin_catalogo_editar_versao",    # R11/R12 GET+POST /admin/catalogo-versoes/<base_id>/versoes/<versao_id>/editar
        "admin_catalogo_ativar_versao",    # R13 POST .../ativar
        "admin_catalogo_inativar_versao",  # R14 POST .../inativar
        "admin_catalogo_descontinuar_versao",  # R15 POST .../descontinuar
        "admin_catalogo_substituir_versao",    # R16 POST .../substituir
    }:
        return _permission("atividades", "edit")
    if endpoint == "admin_matriz_versoes":  # R17 GET /admin/matrizes/<matriz_id>/versoes
        return _permission("matrizes", "view")
    if endpoint in {
        "admin_matriz_versoes_definir",    # R18 POST /admin/matrizes/<matriz_id>/versoes/definir
        "admin_matriz_versoes_remover",    # R19 POST /admin/matrizes/<matriz_id>/versoes/remover
        "admin_matriz_nova_atividade",     # R20 POST /admin/matrizes/<matriz_id>/atividades/nova/<active_tab>
        "admin_matriz_nova_versao_card",   # R21 POST /admin/matrizes/<matriz_id>/atividades/<atividade_id>/nova-versao
    }:
        return _permission("matrizes", "edit")

    # REF-0C-B2 — supervisor-approved diagnostic mappings. These are explicit
    # GET-only requirements; unmatched methods and endpoints remain unmapped.
    if method_norm == "GET" and endpoint in {
        "admin_diagnostico_atividades_versionadas",       # R22
        "admin_diagnostico_atividades_versionadas_view",  # R23
    }:
        return _permission("atividades", "view")

    return None


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session or session.get("user_type") != "admin":
            flash_error("Acesso não autorizado.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def aluno_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session or session.get("user_type") != "aluno":
            flash_error("Acesso não autorizado.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def _clear_login_feedback_flashes():
    session.pop("_flashes", None)


def default_access_level_for_user_type(user_type: str) -> str:
    return "admin_total" if user_type == "admin" else "usuario"


def canonicalize_access_level(raw, fallback: str = "administrativo") -> str:
    normalized = re.sub(
        r"\s+",
        " ",
        unidecode(str(raw or "")).strip().lower().replace("_", " ").replace("-", " "),
    )
    if not normalized:
        return fallback
    return ACCESS_LEVEL_ALIASES.get(normalized, fallback)


def access_level_to_user_type(access_level: str) -> str:
    resolved = canonicalize_access_level(access_level)
    return ACCESS_LEVEL_META.get(resolved, ACCESS_LEVEL_META["administrativo"])["user_type"]


def access_level_label(access_level: str) -> str:
    resolved = canonicalize_access_level(access_level)
    return ACCESS_LEVEL_META.get(resolved, ACCESS_LEVEL_META["administrativo"])["label"]


def _client_ip() -> str:
    """Retorna IP do cliente.

    O cabeçalho X-Forwarded-For SÓ é considerado quando a aplicação está
    explicitamente atrás de um proxy reverso confiável (TRUST_PROXY_XFF=1).
    Caso contrário, qualquer cliente poderia rotacionar o header e burlar o
    rate limit.
    """
    try:
        from flask import current_app
        trust_xff = bool(current_app.config.get("TRUST_PROXY_XFF"))
    except Exception:
        trust_xff = False
    if trust_xff:
        fwd = request.headers.get("X-Forwarded-For")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.remote_addr or "?"


def _login_rate_limited(app, ip: str, account: str | None = None) -> tuple[bool, int]:
    """Retorna (bloqueado, restante_em_segundos) considerando IP e conta.

    Recebe app como parâmetro para não depender de import global cíclico.
    """
    now = time.time()
    win = app.config.get("LOGIN_WINDOW_SECONDS", 600)
    maxn_ip = app.config.get("LOGIN_MAX_ATTEMPTS", 10)
    maxn_acc = app.config.get("LOGIN_ACCOUNT_MAX_ATTEMPTS", 8)

    hist_ip = [t for t in _login_attempts.get(ip, []) if now - t <= win]
    _login_attempts[ip] = hist_ip
    if len(hist_ip) >= maxn_ip:
        restante = int(win - (now - hist_ip[0])) if hist_ip else win
        return True, max(1, restante)

    if account:
        key = account.strip().lower()
        hist_acc = [t for t in _login_attempts_by_account.get(key, []) if now - t <= win]
        _login_attempts_by_account[key] = hist_acc
        if len(hist_acc) >= maxn_acc:
            restante = int(win - (now - hist_acc[0])) if hist_acc else win
            return True, max(1, restante)
    return False, 0


def _register_login_attempt(ip: str, account: str | None = None):
    _login_attempts.setdefault(ip, []).append(time.time())
    if account:
        key = account.strip().lower()
        _login_attempts_by_account.setdefault(key, []).append(time.time())


def _clear_login_attempts(ip: str | None = None, account: str | None = None) -> None:
    if ip and ip in _login_attempts:
        _login_attempts.pop(ip, None)
    if account:
        _login_attempts_by_account.pop(account.strip().lower(), None)
