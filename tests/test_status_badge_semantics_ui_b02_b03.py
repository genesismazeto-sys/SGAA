"""UI-B02 / UI-B03 -- status badge semantics and colour mapping.

Two user-reported defects, one cause: every surface decided locally what a
domain status looks like.

UI-B02 (Requisições): `Pendente` and `Deferida Parcialmente` both resolved to
`status-caution` on the admin list, so a request still awaiting a decision was
indistinguishable from one that had already been partially granted. On the
aluno list the ladder had no `Deferida Parcialmente` branch at all, so a
partial approval fell through to the unknown-status neutral pill.

UI-B03 (Matrizes): the matriz list carried a *copy of the Requisições ladder*.
`vigente` appears nowhere in it, so the effective matrix fell through to the
neutral fallback and rendered identically to `Rascunho`.

These tests pin the shared mapping (`app/status_presentation.py`), the DS
tones it may use, the absence of a page-local ladder in every consumer, and
the rendered pill class on the real pages.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import main
from app.prod1_schema import REQUEST_STATUSES
from app.status_presentation import (
    DS_STATUS_TONES,
    MATRIZ_STATUS_TONES,
    REQUEST_STATUS_TONES,
    canonical_status,
    status_label,
    status_tone,
)
from tests.canonical_request_test_support import (
    create_admin_request,
    login_admin,
    login_student,
)
from tests.versioned_test_support import isolated_versioned_app_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODERN_CSS = (PROJECT_ROOT / "static" / "css" / "modern-style.css").read_text(
    encoding="utf-8"
)

ADMIN_REQUISICOES_TPL = (
    PROJECT_ROOT / "templates" / "admin_requisicoes.html"
).read_text(encoding="utf-8")
ALUNO_REQUISICOES_TPL = (
    PROJECT_ROOT / "templates" / "aluno_minhas_requisicoes.html"
).read_text(encoding="utf-8")
ADMIN_MATRIZES_TPL = (
    PROJECT_ROOT / "templates" / "admin_matrizes.html"
).read_text(encoding="utf-8")

#: The authoritative matriz lifecycle, i.e. the matrizes_atividades CHECK.
MATRIZ_STATUS_KEYS = ("rascunho", "vigente", "encerrada", "ativa", "inativa")

PILL_RE = re.compile(
    r'<(?:span|a)[^>]*class="(badge[^"]*status-pill[^"]*)"[^>]*>\s*([^<]*?)\s*</(?:span|a)>'
)


def _pills(html: str) -> dict[str, str]:
    """Map pill text -> the `status-*` tone class it carries."""
    found: dict[str, str] = {}
    for classes, text in PILL_RE.findall(html):
        tones = [c for c in classes.split() if c.startswith("status-")]
        tones = [c for c in tones if c not in {"status-pill", "status-badge"}]
        if tones and text:
            found[text] = tones[0]
    return found


# ---------------------------------------------------------------------------
# A. The shared mapping is complete and speaks only DS vocabulary
# ---------------------------------------------------------------------------


def test_a1_every_canonical_request_status_has_a_tone():
    """No request status may fall through to the unknown-value fallback."""
    assert set(REQUEST_STATUS_TONES) == set(REQUEST_STATUSES), (
        "the mapping must cover exactly app.prod1_schema.REQUEST_STATUSES; "
        f"delta={sorted(set(REQUEST_STATUS_TONES) ^ set(REQUEST_STATUSES))}"
    )


def test_a2_every_canonical_matriz_status_has_a_tone():
    for key in MATRIZ_STATUS_KEYS:
        assert canonical_status("matriz", key) is not None, key
        assert status_tone("matriz", key) in DS_STATUS_TONES, key


def test_a3_only_design_system_tones_are_ever_emitted():
    """The mapper may choose among existing DS tones. It may not invent one."""
    for table in (REQUEST_STATUS_TONES, MATRIZ_STATUS_TONES):
        for name, tone in table.items():
            assert tone in DS_STATUS_TONES, f"{name} -> unknown tone {tone!r}"


def test_a4_every_tone_used_is_declared_by_the_design_system():
    """Each tone resolves to a real `.badge.status-pill.status-*` variant."""
    used = set(REQUEST_STATUS_TONES.values()) | set(MATRIZ_STATUS_TONES.values())
    used.add(status_tone("requisicao", "algo que nao existe"))
    for tone in sorted(used):
        assert re.search(
            rf"^\.badge\.status-pill\.status-{tone}\{{", MODERN_CSS, re.M
        ), (
            f"tone {tone!r} has no variant in modern-style.css -- a tone must "
            "never be invented in a page or a mapper"
        )


def test_a5_unknown_status_is_neutral_not_a_guess():
    assert status_tone("requisicao", "Coisa Nova") == "neutral"
    assert status_tone("matriz", "") == "neutral"
    assert status_tone("requisicao", None) == "neutral"


def test_a6_aliases_normalise_to_the_canonical_status():
    assert canonical_status("requisicao", "DEFERIDO") == "Deferida"
    assert canonical_status("requisicao", "parcialmente deferida") == (
        "Deferida Parcialmente"
    )
    assert canonical_status("requisicao", "  pending ") == "Pendente"
    # Matriz surfaces pass either the stored key or the rendered label.
    assert canonical_status("matriz", "vigente") == "Vigente"
    assert canonical_status("matriz", "Vigente") == "Vigente"


def test_a7_unknown_domain_is_a_hard_error():
    with pytest.raises(ValueError):
        status_tone("curso", "Ativo")


# ---------------------------------------------------------------------------
# B. UI-B02 -- the four reported Requisições outcomes are distinguishable
# ---------------------------------------------------------------------------


REPORTED_REQUEST_STATUSES = (
    "Pendente",
    "Deferida",
    "Deferida Parcialmente",
    "Indeferida",
)


def test_b1_the_four_reported_statuses_resolve_to_four_distinct_tones():
    tones = [status_tone("requisicao", s) for s in REPORTED_REQUEST_STATUSES]
    assert len(set(tones)) == len(tones), (
        "the user named these four explicitly; none may share a tone. "
        f"got {dict(zip(REPORTED_REQUEST_STATUSES, tones))}"
    )


def test_b2_reported_statuses_take_their_intended_semantic_tones():
    assert status_tone("requisicao", "Pendente") == "caution"
    assert status_tone("requisicao", "Deferida") == "positive"
    assert status_tone("requisicao", "Deferida Parcialmente") == "info"
    assert status_tone("requisicao", "Indeferida") == "negative"


def test_b3_pendente_and_deferida_parcialmente_no_longer_collide():
    """The specific regression: a waiting state looking like a decided one."""
    assert status_tone("requisicao", "Pendente") != status_tone(
        "requisicao", "Deferida Parcialmente"
    )


def test_b4_shared_tones_are_only_within_one_semantic_category():
    """Two statuses may share a tone only inside the same category.

    caution  = open, no final decision, student-editable, non-notifying.
    negative = terminal, nothing granted.
    """
    from app.request_email_notifications import (
        FINAL_DECISION_STATUSES,
        NON_NOTIFYING_STATUSES,
    )

    by_tone: dict[str, set[str]] = {}
    for name, tone in REQUEST_STATUS_TONES.items():
        by_tone.setdefault(tone, set()).add(name)

    assert by_tone["caution"] == {"Pendente", "Devolvida"}
    for name in by_tone["caution"]:
        assert name in NON_NOTIFYING_STATUSES, (
            f"{name} shares the 'open / awaiting action' tone but is a "
            "notifying final decision"
        )

    assert by_tone["negative"] == {"Indeferida", "Encerrada"}
    assert "Indeferida" in FINAL_DECISION_STATUSES

    # Every tone with more than one member must be justified above.
    multi = {t for t, names in by_tone.items() if len(names) > 1}
    assert multi == {"caution", "negative"}, (
        f"an unjustified shared tone appeared: {sorted(multi)}"
    )


# ---------------------------------------------------------------------------
# C. UI-B03 -- Vigente is not Rascunho
# ---------------------------------------------------------------------------


def test_c1_rascunho_is_the_neutral_draft_state():
    assert status_tone("matriz", "rascunho") == "neutral"
    assert status_label("matriz", "rascunho") == "Rascunho"


def test_c2_vigente_takes_the_active_effective_tone():
    assert status_tone("matriz", "vigente") == "positive"
    assert status_label("matriz", "vigente") == "Vigente"


def test_c3_vigente_and_rascunho_are_not_visually_identical():
    assert status_tone("matriz", "vigente") != status_tone("matriz", "rascunho")


def test_c4_matriz_active_inactive_follows_the_rest_of_sgaa():
    """Alunos / Cursos / Turmas all use positive for active, neutral for not."""
    assert status_tone("matriz", "ativa") == "positive"
    assert status_tone("matriz", "inativa") == "neutral"


# ---------------------------------------------------------------------------
# D. One mapping, no page-local ladders, no page-local palette
# ---------------------------------------------------------------------------


STATUS_CONSUMERS = {
    "templates/admin_requisicoes.html": ADMIN_REQUISICOES_TPL,
    "templates/aluno_minhas_requisicoes.html": ALUNO_REQUISICOES_TPL,
    "templates/admin_matrizes.html": ADMIN_MATRIZES_TPL,
}


def test_d1_every_consumer_resolves_its_tone_through_the_shared_mapper():
    for name, source in STATUS_CONSUMERS.items():
        assert "status_tone(" in source, (
            f"{name} must take its tone from the shared mapper"
        )


def test_d2_no_consumer_hardcodes_a_tone_for_a_domain_status():
    """A literal `status-caution` / `'status_tone':'positive'` is a second
    mapping layer and is exactly how these two defects were born."""
    literal_tone = re.compile(
        r"status-(?:positive|neutral|caution|negative|info)\b"
        r"|status_tone'\s*:\s*'(?:positive|neutral|caution|negative|info)'"
    )
    for name, source in STATUS_CONSUMERS.items():
        assert not literal_tone.search(source), (
            f"{name} still pins a tone literally: "
            f"{literal_tone.search(source).group(0)!r}"
        )


def test_d3_no_consumer_declares_a_page_local_status_palette():
    """No `.status-vigente`, no `.indeferida`, no raw badge colour."""
    forbidden_class = re.compile(
        r"\.(?:status-)?(?:vigente|rascunho|pendente|deferida|indeferida|"
        r"devolvida|encerrada)\b",
        re.I,
    )
    for name, source in STATUS_CONSUMERS.items():
        assert not forbidden_class.search(source), (
            f"{name} declares a page-local status class: "
            f"{forbidden_class.search(source).group(0)!r}"
        )


def test_d4_the_shared_mapper_defines_no_colour():
    """It chooses among existing DS tones. It must never carry a literal."""
    source = (PROJECT_ROOT / "app" / "status_presentation.py").read_text(
        encoding="utf-8"
    )
    raw_colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
    assert not raw_colour.search(source), (
        "app/status_presentation.py must hold no colour value; the Design "
        "System owns what a tone looks like"
    )


def test_d5_no_raw_colour_was_added_to_the_touched_status_markup():
    """The status pill markup itself carries no inline or literal colour."""
    pill_line = re.compile(r"^.*status-pill.*$", re.M)
    raw_colour = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|style=")
    for name, source in STATUS_CONSUMERS.items():
        for line in pill_line.findall(source):
            assert not raw_colour.search(line), (
                f"{name} status pill markup carries a raw colour: {line.strip()!r}"
            )


def test_d6_status_pills_carry_no_second_colour_vocabulary():
    """`.badge.success/.warning/.danger` is the older palette. A status pill
    that also claims one of those says two contradictory things -- which is
    what let the matriz list render `success` markup as a neutral pill."""
    for name, source in STATUS_CONSUMERS.items():
        for line in re.findall(r"^.*status-pill.*$", source, re.M):
            assert not re.search(r"status-pill\s+(?:success|warning|danger)\b", line), (
                f"{name} mixes the legacy badge palette into a status pill: "
                f"{line.strip()!r}"
            )


# ---------------------------------------------------------------------------
# E. Rendered proof, on the real pages
# ---------------------------------------------------------------------------


EXPECTED_REQUEST_PILLS = {
    "Pendente": "status-caution",
    "Devolvida": "status-caution",
    "Deferida": "status-positive",
    "Deferida Parcialmente": "status-info",
    "Indeferida": "status-negative",
    "Encerrada": "status-negative",
}


def _force_status(status: str) -> None:
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute("UPDATE requisicoes SET status = ?", (status,))
        conn.commit()


@pytest.mark.parametrize("status", sorted(EXPECTED_REQUEST_PILLS))
def test_e1_admin_list_renders_the_shared_tone(tmp_path, status):
    with isolated_versioned_app_env(tmp_path, "ui-b02-admin.db") as env:
        client = env["client"]
        login_admin(client)
        create_admin_request(client, "UI-B02 admin row")
        _force_status(status)

        html = client.get("/admin/requisicoes").get_data(as_text=True)
        pills = _pills(html)
        assert pills.get(status) == EXPECTED_REQUEST_PILLS[status], (
            f"admin list rendered {status!r} as {pills.get(status)!r}"
        )


@pytest.mark.parametrize("status", sorted(EXPECTED_REQUEST_PILLS))
def test_e2_aluno_list_renders_the_same_tone_as_the_admin_list(tmp_path, status):
    with isolated_versioned_app_env(tmp_path, "ui-b02-aluno.db") as env:
        client = env["client"]
        login_admin(client)
        create_admin_request(client, "UI-B02 aluno row")
        _force_status(status)

        login_student(client)
        html = client.get("/aluno/requisicoes").get_data(as_text=True)
        pills = _pills(html)
        assert pills.get(status) == EXPECTED_REQUEST_PILLS[status], (
            f"aluno list rendered {status!r} as {pills.get(status)!r}; the same "
            "domain status must take the same tone on every surface"
        )


def test_e3_partial_approval_is_not_an_unknown_status_on_the_aluno_list(tmp_path):
    """The aluno ladder had no branch for it, so it reached the student as the
    neutral unknown-value pill. That is the UI-B02 regression, rendered."""
    with isolated_versioned_app_env(tmp_path, "ui-b02-parcial.db") as env:
        client = env["client"]
        login_admin(client)
        create_admin_request(client, "UI-B02 parcial")
        _force_status("Deferida Parcialmente")

        login_student(client)
        html = client.get("/aluno/requisicoes").get_data(as_text=True)
        pills = _pills(html)
        assert "Deferida Parcialmente" in pills
        assert pills["Deferida Parcialmente"] == "status-info"
        assert pills["Deferida Parcialmente"] != "status-neutral"


def test_e4_matriz_list_distinguishes_vigente_from_rascunho(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-b03-matrizes.db") as env:
        client = env["client"]
        login_admin(client)

        with main.app.app_context():
            conn = main.get_db_connection()
            ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM matrizes_atividades ORDER BY id"
                )
            ]
            assert len(ids) >= 2, "need two matrizes to compare two statuses"
            conn.execute(
                "UPDATE matrizes_atividades SET status='vigente' WHERE id=?",
                (ids[0],),
            )
            conn.execute(
                "UPDATE matrizes_atividades SET status='rascunho' WHERE id=?",
                (ids[1],),
            )
            conn.commit()

        html = client.get("/admin/matrizes").get_data(as_text=True)
        pills = _pills(html)
        assert pills.get("Vigente") == "status-positive", (
            f"Vigente rendered as {pills.get('Vigente')!r}"
        )
        assert pills.get("Rascunho") == "status-neutral", (
            f"Rascunho rendered as {pills.get('Rascunho')!r}"
        )
        assert pills["Vigente"] != pills["Rascunho"]


def test_e5_matriz_encerrada_renders_its_own_tone(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-b03-encerrada.db") as env:
        client = env["client"]
        login_admin(client)
        with main.app.app_context():
            conn = main.get_db_connection()
            conn.execute("UPDATE matrizes_atividades SET status='encerrada'")
            conn.commit()

        html = client.get("/admin/matrizes").get_data(as_text=True)
        assert _pills(html).get("Encerrada") == "status-negative"
