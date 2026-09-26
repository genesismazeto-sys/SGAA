"""UT-BR2-ABC: the single canonical owner for three cross-cutting baselines.

Three global truths are consumed by almost every blueprint-extraction suite:

* the ``utils.messages`` message catalog key set,
* the Flask URL contract (``tests/_artifacts/route_inventory_baseline.json``),
* the CSRF inventory snapshots (``tests/_artifacts/csrf_inventory_shadow_*.json``).

Historically each extraction suite froze its own *copy* of the corresponding
scalar (``assert len(catalog) == 556``, ``assert len(rules) == 128``,
``assert len(rows) == 77``, ``ROUTE_INVENTORY_BYTES = 20171``, ...).  Every
later extraction then had to edit dozens of unrelated magic numbers, so the
copies rotted into three mutually inconsistent eras while the real contracts
moved on to 554 catalog keys, 125 route entries and 74 CSRF rows.

This module is the ONLY place those global truths are declared.  Extraction
suites keep their own *local* semantic assertions -- blueprint ownership, owner
partitions, scanner coverage, retirement proofs, extraction deltas -- and
delegate the global totals here.

Every delegation is exact equality against a content digest, never a bare
count, so the consolidated control is strictly stronger than the scalars it
replaces: a single unauthorized added, removed, renamed or re-owned catalog
key / route / CSRF row still fails.  ``tests/test_ut_br2abc_canonical_baseline_
governance.py`` carries the mutation probes that prove it.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = Path(__file__).resolve().parent / "_artifacts"

BUSINESS_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _digest(lines) -> str:
    """Stable digest of an unordered identity collection."""
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# A. Message catalog -- named delta ledger
# ---------------------------------------------------------------------------
# The canonical count is never typed as a total: it is the arithmetic result of
# a ledger whose every term is a reviewed, documented product delta.  Adding a
# catalogued message means appending a named term here, in one place.
CATALOG_LEDGER: tuple[tuple[str, int], ...] = (
    ("FC-07 head: catalog state at the Arquivos service extraction", 526),
    ("FC-07..UT-17 legitimate net product delta", 19),
    (
        "UT-AM1 retired 'Selecione uma matriz para a turma.' "
        "(msg_4d8251747aafd60d) when the Turma Matrix became an optional default",
        -1,
    ),
    (
        "UT-AM2 explicit student Matrix assignment: 'Matriz academica' "
        "(msg_34c6fdd255ae0c6e) and 'Sem matriz' (msg_c52418de2740e169)",
        2,
    ),
    ("UT-TM1/UT-TM2 neutral Turma Matrix validation messages", 2),
    ("UT-MX3 StudentMatrixError default-text ownership", 6),
    (
        "TMA1 Turma-Matrix authority: 'Definida pela turma' "
        "(msg_35110e5b7a30e863) replaces the individual Matrix selector for a "
        "Turma-bound student, whose Matrix now comes from the Turma",
        1,
    ),
    (
        "CR1 cloud application-credential recovery: Banco de Dados now "
        "configures the Google/OneDrive application credentials and the shared "
        "public OAuth address as a normal product action, adding "
        "'Credenciais do Google Drive salvas com segurança nesta máquina.' "
        "(msg_5f1896e86e5e5197), 'Credenciais do OneDrive salvas com segurança "
        "nesta máquina.' (msg_47eb6cef00e56a30) and 'Endereço público OAuth "
        "salvo.' (msg_2b8b193d37a30c8f)",
        3,
    ),
    (
        "REN1 request e-mail notifications: the Requisições list gains the "
        "e-mail-pending row indicator, the selection-aware 'Enviar e-mail' "
        "action in both the Ações menu and the floating bar, the send "
        "confirmation/preview dialog including the unconfirmed-resend "
        "acknowledgement, and the Pré-definições → E-mails de resposta "
        "subject/default/placeholder editor surface",
        22,
    ),
    (
        "Password foundation Phase 1/2: replace the former explanatory and "
        "reset wording with default-password activation, first-access and "
        "password-recovery messages (8 additions, 8 retirements). The panel "
        "footer now reads the pre-existing \"Salvar\", so the longer "
        "\"Salvar senhas padrao\" literal retires with no new key",
        0,
    ),
    (
        "AR1 Acesso post-landing repair: the Novo acesso help text now follows "
        "the default-password switch, adding 'Se ficar em branco, o usuario "
        "devera definir a senha pelo e-mail de primeiro acesso.' "
        "(msg_de1ec3824a33c230) and 'Se ficar em branco, a senha atual sera "
        "mantida.' (msg_d62f6f50edbc09ac) for the switched-off case; and "
        "'Excluir acesso' stops deleting the academic aluno, so the raw "
        "'Nao foi possivel excluir o acesso: <sqlite text>' retires in favour "
        "of a safe-debug-identifier fallback, 'Nao foi possivel excluir o "
        "acesso porque ha registros vinculados a ele. Codigo de suporte: "
        "{value_1}' (msg_cbb52242746685c8). 3 additions, 1 retirement",
        2,
    ),
    (
        "RA1 root administrator contract: the built-in administrator ships in "
        "'default' credential state, so switching the shared default passwords "
        "off locked out the only account able to switch them back on. Root now "
        "has an independent break-glass credential and may not be removed, "
        "revoked, demoted or have its address moved through access management, "
        "adding the three refusals (msg_b74771946e0bc5ae, msg_758fb77b13d34a92, "
        "msg_8a6e1bc2d393f8f5), the audit-safe revocation of an account history "
        "still references (msg_183dcf7cbb0eb4fc). The break-glass path is "
        "deliberately invisible in the product: it is an authentication "
        "contract, not a panel notice, so nothing announces it. "
        "Access removal is now one model -- revocation -- so "
        "'Acesso excluido com sucesso.' (msg_56e46c7a8f7ce61f) retires in "
        "favour of the revocation wording, and reactivation adds "
        "msg_c6ff9cd590dd08ee and msg_52a939022460dcce. 6 additions, "
        "1 retirement",
        5,
    ),
    (
        "CP1 credential pending (prod-1/v11): the global 'Ativar senhas "
        "padrao' switch retires. Default passwords become an explicit "
        "per-account action and a blank password creates a pending account, "
        "so the switch's refusal flash 'Ative as senhas padrao antes de "
        "aplica-las a um acesso.' (msg_68bbd4601385b8d4) and the three "
        "blank-password help texts that promised the shared default "
        "(msg_6e89088d3a933113, msg_719b27dd68ea5b3e, msg_2849e4dc7c405251) "
        "retire. 0 additions, 4 retirements",
        -4,
    ),
    (
        "UI-B19 Adicionar aluno photo label: the add-student form drops the "
        "'Foto' row label beside the avatar, matching Meus dados, which never "
        "carried one. Its only consumer was that label, so 'Foto' "
        "(msg_0f5e4f087245b242) retires. 0 additions, 1 retirement",
        -1,
    ),
)

# Everything before the UT-MX3 term is MX3's exact parent state. Anchored on
# MX3's own index rather than "the ledger minus its last term": appending a
# later term must not silently redate that historical parent, which is what
# PARENT_CATALOG_KEYS_SHA256 below is frozen against.
MX3_LEDGER_INDEX = 5
PARENT_CATALOG_COUNT = sum(
    delta for _term, delta in CATALOG_LEDGER[:MX3_LEDGER_INDEX]
)
CANONICAL_CATALOG_COUNT = sum(delta for _term, delta in CATALOG_LEDGER)

# FC-07 head reconciliation.  The FC-07 era *expected* 537 keys while the actual
# head was 526: an 11-key baseline debt this project keeps deliberately visible
# rather than papering over.  After every named product delta the residual is 2.
CATALOG_FC07_HEAD_ACTUAL = CATALOG_LEDGER[0][1]
CATALOG_FC07_NET_PRODUCT_DELTA = CATALOG_LEDGER[1][1]
CATALOG_FC07_HEAD_EXPECTED = 537
# The residual is a historical reconciliation of the FC-07 era, so it is
# measured against the ledger through UT-MX3 -- the state in which it was
# established -- not against the live total. Otherwise every later product
# message would silently restate a debt incurred once and never grown.
CATALOG_DEBT_ANCHOR_COUNT = sum(
    delta for _term, delta in CATALOG_LEDGER[: MX3_LEDGER_INDEX + 1]
)
CATALOG_VISIBLE_BASELINE_DEBT = (
    CATALOG_FC07_HEAD_EXPECTED + CATALOG_FC07_NET_PRODUCT_DELTA
) - CATALOG_DEBT_ANCHOR_COUNT

# Key-set digests.  The parent digest is UT-MX3's frozen pre-candidate state;
# the canonical digest governs the live catalog and is what makes
# ``CANONICAL_CATALOG_COUNT`` unable to drift independently of the real keys.
PARENT_CATALOG_KEYS_SHA256 = (
    "f5dc176c0e574f969f566007ad05a867dc4362b4d51787a70844775136d44265"
)
# Password foundation was net zero on top of the REN1 580-key state: eight
# additions against eight retired literals.  AR1 took it to 582, RA1 to 587,
# CP1 (four retirements, no addition) to 583, UI-B19 (one retirement) to 582.
CANONICAL_CATALOG_KEYS_SHA256 = (
    "e9180f2d7a053bba61ade5900c2e10bbb0d79ba545896e9f5240686cb169c19b"
)

# Named post-MX3 key sets.  Suites that reconstruct UT-MX3's parent state have
# to subtract every term appended after it, so each such term declares its keys
# here exactly once instead of being re-typed at each reconstruction site.
CR1_CLOUD_CREDENTIAL_RECOVERY_KEYS = frozenset(
    {
        "msg_5f1896e86e5e5197",
        "msg_47eb6cef00e56a30",
        "msg_2b8b193d37a30c8f",
    }
)

# REN1 request e-mail notifications.  Removing exactly these 22 keys from the
# live catalog reproduces the previous 558-key baseline digest, which is the
# proof that this term is purely additive.
REN1_REQUEST_EMAIL_KEYS = frozenset(
    {
        # Unconfirmed-resend acknowledgement: an attempt whose outcome the
        # provider never confirmed may not be resent without explicit consent.
        "msg_babc490aa98abf35",  # Confirmo o reenvio mesmo assim...
        "msg_20eb3b2761b50aed",  # a tentativa anterior nao foi confirmada...
        "msg_7750d57868a1664b",  # E-mail pendente de envio
        "msg_bbef131134b59b54",  # E-mail pendente - ultima tentativa falhou.
        "msg_7515e4ab6b475885",  # Enviar e-mail
        "msg_be31194418051eef",  # Enviar e-mail ({value_1})
        "msg_24325ddb7752090e",  # {value_1} requisicoes selecionadas.
        "msg_a5b5d5343ac8b8cb",  # Todas as requisicoes selecionadas precisam...
        "msg_771f5b72615911fd",  # Enviar e-mail de resposta
        "msg_10d4b1ed4633f701",  # {value_1} - {value_2} - {value_3} (counts agreed server-side)
        "msg_b3a01bef14b4bd4d",  # Modelo
        "msg_5e91dcdc5796506a",  # Enviando...
        "msg_b6651f8b5faa2b3e",  # Nao foi possivel concluir o envio.
        "msg_38f5682235059385",  # Destinatarios
        "msg_2ac37ab5583ac46d",  # Pre-visualizar mensagem
        "msg_a91a95517c038bab",  # Enviar
        "msg_429c06a0a120bf5a",  # Nome interno do modelo...
        "msg_b354c345c6677949",  # Assunto do e-mail
        "msg_f94bfb6bda0978ac",  # Assunto enviado ao aluno
        "msg_8c65a50ebbda9d19",  # Usar este modelo como padrao...
        "msg_41210911d2e66292",  # Campos disponiveis
        "msg_b84bd6a7db10ccf6",  # Clique para inserir no conteudo.
    }
)

# AR1 Acesso post-landing repair.  Net +3: four additions against the retired
# raw-SQLite delete flash.  The retirement is carried separately because
# reconstructing an earlier state has to put it back, not just take these out.
AR1_ACCESS_REPAIR_KEYS = frozenset(
    {
        # Novo acesso help text for a blank password while the shared
        # default-password mechanism is switched off.
        "msg_de1ec3824a33c230",  # Se ficar em branco, o usuario devera definir...
        "msg_d62f6f50edbc09ac",  # Se ficar em branco, a senha atual sera mantida.
        # "Excluir acesso" no longer leaks the SQLite text; the only remaining
        # failure path carries a safe support identifier.
        "msg_cbb52242746685c8",  # ... Codigo de suporte: {value_1}
    }
)
AR1_ACCESS_REPAIR_RETIRED_KEYS = frozenset(
    {
        "msg_e6eb77bb0d9c2744",  # Nao foi possivel excluir o acesso: {value_1}
    }
)

# RA1 root administrator contract.  Purely additive (+6): the break-glass
# recovery path needs the lockout refusals, the audit-safe revocation, and one
# neutral statement that the protection exists.  The credential itself is never
# a catalogued message because it is never rendered.
RA1_ROOT_ADMIN_KEYS = frozenset(
    {
        "msg_b74771946e0bc5ae",  # O administrador raiz nao pode ser excluido nem revogado...
        "msg_758fb77b13d34a92",  # O administrador raiz nao pode ser rebaixado...
        "msg_8a6e1bc2d393f8f5",  # O e-mail do administrador raiz nao pode ser alterado...
        "msg_183dcf7cbb0eb4fc",  # Acesso revogado: o login foi encerrado...
        "msg_c6ff9cd590dd08ee",  # Acesso reativado e vinculado ao registro existente.
        "msg_52a939022460dcce",  # Este acesso esta revogado. Reative-o antes de enviar...
    }
)
RA1_ROOT_ADMIN_RETIRED_KEYS = frozenset(
    {
        "msg_56e46c7a8f7ce61f",  # Acesso excluido com sucesso.
    }
)

# CP1 credential pending (prod-1/v11).  Purely a retirement (-4): the global
# default-password switch is gone, and with it every message that referred to
# it or promised that a blank password applies the shared default.  CP1 adds
# no key -- the surviving help texts were already catalogued by AR1.
CP1_CREDENTIAL_PENDING_KEYS = frozenset()
CP1_CREDENTIAL_PENDING_RETIRED_KEYS = frozenset(
    {
        "msg_68bbd4601385b8d4",  # Ative as senhas padrao antes de aplica-las...
        "msg_6e89088d3a933113",  # Se ficar em branco na criacao, o sistema aplica...
        "msg_719b27dd68ea5b3e",  # Se ficar em branco, o sistema aplica a senha padrao de {value_1}.
        "msg_2849e4dc7c405251",  # Se ficar em branco, a senha atual sera mantida. A aplicacao rapida...
    }
)
# UI-B19 Adicionar aluno photo label.  Purely a retirement (-1): the "Foto"
# row label on the add-student avatar was that literal's only consumer.
UIB19_PHOTO_LABEL_KEYS = frozenset()
UIB19_PHOTO_LABEL_RETIRED_KEYS = frozenset(
    {
        "msg_0f5e4f087245b242",  # Foto
    }
)


def catalog_keys_digest(keys) -> str:
    """Digest of a catalog key set, comparable with the frozen SHA constants."""
    return _digest(keys)


def canonical_message_catalog(*, fresh: bool = True) -> dict:
    """Return the live message catalog, by default past the lru_cache."""
    from utils import messages

    if fresh:
        messages._message_catalog.cache_clear()
    return messages._message_catalog()


def assert_catalog_matches_canonical_baseline(catalog=None, *, context: str = "") -> dict:
    """Assert the message catalog is exactly the canonical key set.

    Replaces the per-suite ``assert len(catalog) == <frozen scalar>`` copies.
    Exact-equality on the key-set digest means an unauthorized addition,
    removal or key rename fails -- which the frozen count could not detect for
    a same-size swap.
    """
    if catalog is None:
        catalog = canonical_message_catalog(fresh=False)
    keys = set(catalog)
    where = f" [{context}]" if context else ""
    assert len(keys) == CANONICAL_CATALOG_COUNT, (
        f"message catalog must stay exactly {CANONICAL_CATALOG_COUNT} keys"
        f"{where}; got {len(keys)}. The canonical count is the "
        "tests/canonical_baseline_support.py CATALOG_LEDGER sum -- append a "
        "named term there instead of editing a per-suite scalar."
    )
    observed = catalog_keys_digest(keys)
    assert observed == CANONICAL_CATALOG_KEYS_SHA256, (
        f"message catalog key set diverged from the canonical baseline{where}: "
        f"digest {observed} != {CANONICAL_CATALOG_KEYS_SHA256}. The count is "
        "unchanged, so a key was renamed or swapped."
    )
    return catalog


# ---------------------------------------------------------------------------
# B. Route inventory -- delegated to the versioned artifact owner guard
# ---------------------------------------------------------------------------
ROUTE_INVENTORY_ARTIFACT = ARTIFACTS_DIR / "route_inventory_baseline.json"


def load_route_inventory_baseline() -> dict:
    return json.loads(ROUTE_INVENTORY_ARTIFACT.read_text(encoding="utf-8"))


def route_identities(routes) -> frozenset[tuple[str, str, tuple[str, ...]]]:
    """(rule, endpoint, methods) identities for artifact-shaped route entries."""
    return frozenset(
        (entry["rule"], entry["endpoint"], tuple(entry["methods"])) for entry in routes
    )


def _route_identity_lines(identities) -> list[str]:
    return [f"{rule}\t{endpoint}\t{','.join(methods)}" for rule, endpoint, methods in identities]


def route_identities_digest(identities) -> str:
    return _digest(_route_identity_lines(identities))


CANONICAL_ROUTE_IDENTITIES = route_identities(load_route_inventory_baseline()["routes"])
CANONICAL_ROUTE_ENTRY_COUNT = len(CANONICAL_ROUTE_IDENTITIES)
CANONICAL_ROUTE_ENDPOINT_COUNT = len(
    {endpoint for _rule, endpoint, _methods in CANONICAL_ROUTE_IDENTITIES}
)
CANONICAL_ROUTE_RULE_COUNT = len(
    {rule for rule, _endpoint, _methods in CANONICAL_ROUTE_IDENTITIES}
)
# Independent pin on the artifact itself.  Without it the derived counts above
# would follow any edit of the JSON; with it, a deliberate URL-contract change
# has to be declared here, exactly once, on top of regenerating the artifact.
TMA1_MATRIX_AUTHORITY_KEYS = frozenset({"msg_35110e5b7a30e863"})

# REN1 added two Requisições e-mail routes; password foundation adds the
# single-account password e-mail route and the three public password routes.
# The default-password activation is NOT a route: the Senhas padrão panel is
# one settings surface saved by the pre-existing senhas-default endpoint.
CANONICAL_ROUTE_IDENTITIES_SHA256 = (
    "239bdebf670f4c4f4142fe0ce71bc9f96026e5a97d0a3fa3775c7b9ebb653303"
)


def _route_diff(expected, actual) -> str:
    return "".join(
        difflib.unified_diff(
            sorted(_route_identity_lines(expected)),
            sorted(_route_identity_lines(actual)),
            fromfile="expected/route_inventory_baseline.json",
            tofile="actual/live-url-map",
            lineterm="",
            n=1,
        )
    )


def assert_route_inventory_artifact_is_canonical(data=None, *, context: str = "") -> dict:
    """Assert the versioned route artifact is the declared canonical contract."""
    if data is None:
        data = load_route_inventory_baseline()
    where = f" [{context}]" if context else ""
    assert data["schema_version"] == 1, f"route artifact schema_version{where}"
    assert data["generated_from"] == "main.app.url_map", (
        f"route artifact generated_from{where}"
    )
    identities = route_identities(data["routes"])
    assert len(data["routes"]) == CANONICAL_ROUTE_ENTRY_COUNT == len(identities), (
        f"route artifact must hold exactly {CANONICAL_ROUTE_ENTRY_COUNT} unique "
        f"entries{where}; got {len(data['routes'])}"
    )
    observed = route_identities_digest(identities)
    assert observed == CANONICAL_ROUTE_IDENTITIES_SHA256, (
        f"route artifact diverged from the canonical URL contract{where}: "
        f"digest {observed} != {CANONICAL_ROUTE_IDENTITIES_SHA256}\n"
        + _route_diff(CANONICAL_ROUTE_IDENTITIES, identities)
    )
    return data


def assert_live_route_inventory_matches_canonical_baseline(*, context: str = ""):
    """Delegate global URL-contract truth to the canonical owner guard.

    Reuses ``test_route_inventory_snapshot.build_route_inventory`` so there is
    exactly one definition of "the live inventory", then pins the artifact
    itself.  Together this detects a deleted route, an added route and a changed
    rule/endpoint/method pairing -- the three things the per-suite scalar counts
    were standing in for.

    The artifact declares ``generated_from = "main.app.url_map"``, so the
    canonical inventory is defined for ``main.app`` only; there is deliberately
    no ``app`` parameter to silently accept some other application.
    """
    from tests.test_route_inventory_snapshot import build_route_inventory

    where = f" [{context}]" if context else ""
    expected = assert_route_inventory_artifact_is_canonical(context=context)
    actual = build_route_inventory()
    assert actual == expected, (
        f"live URL map diverged from the versioned route baseline{where}:\n"
        + _route_diff(route_identities(expected["routes"]), route_identities(actual["routes"]))
    )
    return actual


def assert_live_route_surface_matches_canonical_baseline(app=None, *, context: str = ""):
    """Route inventory equality plus the live endpoint-registry projection.

    Replaces the ``len(rules) == 128`` / ``len(view_functions) == 127`` pairs.
    Both projections are derived from the canonical artifact, so they cannot
    disagree with it.  ``app`` may be passed for readability at the call site but
    must be ``main.app``, the only application the canonical artifact describes.
    """
    import main

    if app is None:
        app = main.app
    assert app is main.app, (
        "the canonical route inventory is defined for main.app only"
    )
    where = f" [{context}]" if context else ""
    assert_live_route_inventory_matches_canonical_baseline(context=context)
    rules = list(app.url_map.iter_rules())
    assert len(rules) == CANONICAL_ROUTE_ENTRY_COUNT, (
        f"live url_map must hold exactly {CANONICAL_ROUTE_ENTRY_COUNT} rules"
        f"{where}; got {len(rules)}"
    )
    assert len(app.view_functions) == CANONICAL_ROUTE_ENDPOINT_COUNT, (
        f"live view_functions must hold exactly {CANONICAL_ROUTE_ENDPOINT_COUNT} "
        f"endpoints{where}; got {len(app.view_functions)}"
    )
    return rules


# ---------------------------------------------------------------------------
# C. CSRF inventory snapshots -- owner partitions over one canonical row set
# ---------------------------------------------------------------------------
CSRF_OFF_ARTIFACT = ARTIFACTS_DIR / "csrf_inventory_shadow_off.json"
CSRF_ON_ARTIFACT = ARTIFACTS_DIR / "csrf_inventory_shadow_on.json"
CANONICAL_CSRF_ARTIFACTS = (CSRF_OFF_ARTIFACT, CSRF_ON_ARTIFACT)

CSRF_SUMMARY_KEYS = frozenset(
    {"total_mutating_routes", "status_counts", "high_risk_routes", "page_statuses"}
)


def load_csrf_snapshot(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def csrf_row_identities(rows) -> frozenset[tuple[str, str, str]]:
    """(route, method, view_function) -- protection surface plus its owner."""
    return frozenset(
        (row["route"], row["method"], row["view_function"]) for row in rows
    )


def _csrf_identity_lines(identities) -> list[str]:
    return [f"{route}\t{method}\t{owner}" for route, method, owner in identities]


def csrf_row_identities_digest(identities) -> str:
    return _digest(_csrf_identity_lines(identities))


def csrf_owner_partitions(rows) -> dict[str, frozenset[tuple[str, str, str]]]:
    """Partition canonical rows by the owning module of their view function."""
    partitions: dict[str, set] = {}
    for row in rows:
        owner_module = row["view_function"].rsplit(".", 1)[0]
        partitions.setdefault(owner_module, set()).add(
            (row["route"], row["method"], row["view_function"])
        )
    return {module: frozenset(members) for module, members in partitions.items()}


CANONICAL_CSRF_ROWS = tuple(load_csrf_snapshot(CSRF_OFF_ARTIFACT)["rows"])
CANONICAL_CSRF_ROW_IDENTITIES = csrf_row_identities(CANONICAL_CSRF_ROWS)
CANONICAL_CSRF_ROW_COUNT = len(CANONICAL_CSRF_ROW_IDENTITIES)
CANONICAL_CSRF_PAGE_STATUS_COUNT = len(
    load_csrf_snapshot(CSRF_OFF_ARTIFACT)["summary"]["page_statuses"]
)
# Independent pin, same rationale as CANONICAL_ROUTE_IDENTITIES_SHA256: the
# derived counts follow the artifact, this digest anchors the artifact.
CANONICAL_CSRF_ROW_IDENTITIES_SHA256 = (
    "d595981f01566cc0d98eac1a4c79a505bfb336163746b424d4ff11d5420c833e"
)
# Named owner partitions of the canonical row set.  Every extraction that moved
# handlers out of ``main`` is visible here as its own term; the terms are
# disjoint and sum to CANONICAL_CSRF_ROW_COUNT.
CANONICAL_CSRF_OWNER_PARTITIONS: dict[str, int] = {
    "app.views.admin.acesso": 6,
    "app.views.admin.alertas": 3,
    "app.views.admin.alunos_turmas_cursos": 11,
    "app.views.admin.arquivos": 3,
    "app.views.admin.atividades": 14,
    "app.views.admin.banco_dados": 11,
    "app.views.admin.matrizes": 5,
    "app.views.admin.meus_dados": 1,
    "app.views.admin.reportes": 2,
    "app.views.admin.requisicoes": 5,
    "app.views.aluno": 5,
    "app.views.core": 2,
    "app.views.passwords": 3,
    "main": 6,
    "presets_api": 1,
}


# Named retirement ledger.  Suites that reconcile a historical PHASE-4-era
# snapshot (``git show <baseline>:tests/_artifacts/csrf_inventory_*.json``)
# against the canonical snapshot must subtract exactly these retirements -- and
# nothing else -- before comparing row-for-row.  Declared once here so the three
# suites that perform that reconciliation cannot drift apart again.
NORMAS_DOMAIN_RETIRED_ROUTES = frozenset({"/admin/normas-atividade/nova"})
NORMAS_DOMAIN_RETIRED_CSRF_PAGES = frozenset(
    {"/admin/normas-atividade", "/admin/normas-atividade/nova"}
)
# The Matrix version surface retirement removed three mutating routes; the
# historical snapshot counted them in ``total_mutating_routes`` and in two
# status buckets, so those projections are corrected by the same ledger.
MATRIX_VERSION_SURFACE_RETIRED_ROUTES = frozenset(
    {
        "/admin/matrizes/<int:matriz_id>/atividades/nova/<string:active_tab>",
        "/admin/matrizes/<int:matriz_id>/versoes/definir",
        "/admin/matrizes/<int:matriz_id>/versoes/remover",
    }
)
MATRIX_VERSION_SURFACE_RETIRED_CSRF_PAGES = frozenset(
    {"/admin/matrizes/1/versoes", "/admin/catalogo-versoes"}
)
MATRIX_VERSION_SURFACE_RETIRED_STATUS_COUNTS = {
    "ok_rendered_form_token": 2,
    "ok_specific_regression_test": 1,
}

RETIRED_CSRF_ROUTES = (
    NORMAS_DOMAIN_RETIRED_ROUTES | MATRIX_VERSION_SURFACE_RETIRED_ROUTES
)
RETIRED_CSRF_PAGES = (
    NORMAS_DOMAIN_RETIRED_CSRF_PAGES | MATRIX_VERSION_SURFACE_RETIRED_CSRF_PAGES
)

PASSWORD_FOUNDATION_ADDED_KEYS = frozenset(
    {
        "msg_68bbd4601385b8d4",
        "msg_bf7e15c6432ad589",
        "msg_418b33480e418db1",
        "msg_ec5ba85c1757bfa9",
        "msg_620ad9a7c5f8d23e",
        "msg_2849e4dc7c405251",
        "msg_d851da8d55ba1305",
        "msg_5762b488d7b6e455",
    }
)

PASSWORD_FOUNDATION_RETIRED_KEYS = frozenset(
    {
        "msg_2c5ce8778bb82284",
        "msg_ccdfb7e8e0daac9b",
        "msg_daf208a908272ba0",
        "msg_16fa270deb9e5e19",
        "msg_c46c3f680d905635",
        "msg_39a1589ba92fbf99",
        "msg_45359497a041f95e",
        "msg_e5210e430345f987",
    }
)


def catalog_keys_before_password_foundation(keys) -> set[str]:
    return (set(keys) - set(PASSWORD_FOUNDATION_ADDED_KEYS)) | set(
        PASSWORD_FOUNDATION_RETIRED_KEYS
    )


def catalog_keys_before_root_admin(keys) -> set[str]:
    """Undo the RA1 term, which retires one key as well as adding seven."""
    return (set(keys) - set(RA1_ROOT_ADMIN_KEYS)) | set(RA1_ROOT_ADMIN_RETIRED_KEYS)


def catalog_keys_before_photo_label(keys) -> set[str]:
    """Undo the UI-B19 term: put the retired "Foto" key back.

    UI-B19 is the newest term, so a reconstruction walks back through this
    first, then CP1, RA1, AR1 and the password foundation.
    """
    return (set(keys) - set(UIB19_PHOTO_LABEL_KEYS)) | set(
        UIB19_PHOTO_LABEL_RETIRED_KEYS
    )


def catalog_keys_before_credential_pending(keys) -> set[str]:
    """Undo the CP1 term: put its four retired keys back.

    A reconstruction walks back through UI-B19 first, then this, then RA1,
    AR1 and the password foundation.
    """
    return (set(keys) - set(CP1_CREDENTIAL_PENDING_KEYS)) | set(
        CP1_CREDENTIAL_PENDING_RETIRED_KEYS
    )


def catalog_keys_before_access_repair(keys) -> set[str]:
    """Undo the AR1 term. Symmetric with the password-foundation helper above.

    A reconstruction walks back through CP1 and RA1 first, then this, and
    only then through the password foundation.
    """
    return (set(keys) - set(AR1_ACCESS_REPAIR_KEYS)) | set(
        AR1_ACCESS_REPAIR_RETIRED_KEYS
    )
PASSWORD_FOUNDATION_CSRF_ROUTES = frozenset(
    {
        "/admin/acesso/<int:usuario_id>/senha-por-email",
        "/esqueci-minha-senha",
        "/primeiro-acesso",
        "/redefinir-senha",
    }
)


def reconcile_historical_csrf_snapshot(snapshot: dict) -> dict:
    """Apply named retirements/additions to a pre-current era snapshot.

    Mutates and returns ``snapshot`` so the caller can then compare it row-for-row
    against the canonical one.  ``/admin/mapeamento-legado`` is deliberately left
    in place: each suite's own summary reconciliation asserts that exactly one
    such retired page is present, which is its local retirement proof.
    """
    snapshot["rows"] = [
        row for row in snapshot["rows"] if row["route"] not in RETIRED_CSRF_ROUTES
    ]
    summary = snapshot["summary"]
    summary["page_statuses"] = [
        page for page in summary["page_statuses"] if page["path"] not in RETIRED_CSRF_PAGES
    ]
    summary["total_mutating_routes"] -= len(MATRIX_VERSION_SURFACE_RETIRED_ROUTES)
    for status, retired in MATRIX_VERSION_SURFACE_RETIRED_STATUS_COUNTS.items():
        summary["status_counts"][status] -= retired
    # Password foundation added genuinely new routes after all three extraction
    # baselines. Copy only those reviewed canonical rows into the old era.
    additions = [
        row
        for row in CANONICAL_CSRF_ROWS
        if row["route"] in PASSWORD_FOUNDATION_CSRF_ROUTES
    ]
    snapshot["rows"].extend(dict(addition) for addition in additions)
    snapshot["rows"].sort(
        key=lambda row: (row["route"], row["method"], row["view_function"])
    )
    summary["total_mutating_routes"] += len(additions)
    for addition in additions:
        summary["status_counts"][addition["status"]] += 1
    public_page = next(
        page
        for page in load_csrf_snapshot(CSRF_OFF_ARTIFACT)["summary"]["page_statuses"]
        if page["path"] == "/esqueci-minha-senha"
    )
    if not any(
        page["path"] == public_page["path"] for page in summary["page_statuses"]
    ):
        login_index = next(
            index
            for index, page in enumerate(summary["page_statuses"])
            if page["path"] == "/login"
        )
        summary["page_statuses"].insert(login_index, dict(public_page))
    return snapshot


def _csrf_diff(expected, actual) -> str:
    return "".join(
        difflib.unified_diff(
            sorted(_csrf_identity_lines(expected)),
            sorted(_csrf_identity_lines(actual)),
            fromfile="expected/canonical-csrf-rows",
            tofile="actual/csrf-rows",
            lineterm="",
            n=1,
        )
    )


def assert_csrf_snapshot_matches_canonical_baseline(snapshot, *, context: str = ""):
    """Assert a CSRF snapshot is exactly the canonical protection inventory.

    Replaces the per-suite ``assert len(rows) == 77``.  Row identities carry the
    owner, so this detects a disappearing protected row, an undeclared new one
    and a silent re-owning -- none of which a row count could discriminate.
    """
    rows = snapshot["rows"] if isinstance(snapshot, dict) else list(snapshot)
    where = f" [{context}]" if context else ""
    identities = csrf_row_identities(rows)
    assert len(rows) == CANONICAL_CSRF_ROW_COUNT == len(identities), (
        f"CSRF snapshot must hold exactly {CANONICAL_CSRF_ROW_COUNT} unique "
        f"protected rows{where}; got {len(rows)} ({len(identities)} unique)"
    )
    observed = csrf_row_identities_digest(identities)
    assert observed == CANONICAL_CSRF_ROW_IDENTITIES_SHA256, (
        f"CSRF protection inventory diverged from the canonical snapshot{where}: "
        f"digest {observed} != {CANONICAL_CSRF_ROW_IDENTITIES_SHA256}\n"
        + _csrf_diff(CANONICAL_CSRF_ROW_IDENTITIES, identities)
    )
    if isinstance(snapshot, dict) and "summary" in snapshot:
        summary = snapshot["summary"]
        assert set(summary) == set(CSRF_SUMMARY_KEYS), (
            f"CSRF snapshot summary shape{where}: {sorted(summary)}"
        )
        assert len(summary["page_statuses"]) == CANONICAL_CSRF_PAGE_STATUS_COUNT, (
            f"CSRF snapshot must keep exactly {CANONICAL_CSRF_PAGE_STATUS_COUNT} "
            f"page statuses{where}; got {len(summary['page_statuses'])}"
        )
    return rows


def assert_csrf_owner_partitions_reconstruct_canonical(rows, *, context: str = ""):
    """Named owner partitions: disjoint, exactly sized, union == canonical set."""
    where = f" [{context}]" if context else ""
    partitions = csrf_owner_partitions(rows)
    assert {
        module: len(members) for module, members in partitions.items()
    } == CANONICAL_CSRF_OWNER_PARTITIONS, (
        f"CSRF owner partition sizes diverged{where}: "
        f"{ {m: len(v) for m, v in sorted(partitions.items())} }"
    )
    union: set = set()
    for module, members in partitions.items():
        overlap = union & members
        assert not overlap, f"owner partitions must stay disjoint{where}: {module} {overlap}"
        union |= members
    assert union == CANONICAL_CSRF_ROW_IDENTITIES, (
        f"owner partitions must reconstruct the canonical row set{where}\n"
        + _csrf_diff(CANONICAL_CSRF_ROW_IDENTITIES, union)
    )
    assert sum(CANONICAL_CSRF_OWNER_PARTITIONS.values()) == CANONICAL_CSRF_ROW_COUNT, (
        "the named owner ledger must sum to the canonical row count"
    )
    return partitions
