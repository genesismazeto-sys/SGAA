"""Ver Aluno: read-only presentation and the governed-Matriz field structure.

Two defects, one screen (``/admin/editar_aluno/<id>?view=1``):

1. **The Matriz card was structurally broken when the Turma governs it.**
   The card renders the canonical trailing-chip markup
   (``<div class="field-chip chip-right">``) that every file control in the
   system uses -- but every rule that makes that anatomy work was scoped to
   ``.field-card.file-card``. On a plain card the chip fell through to the
   2-column primitive (``40px 1fr``), so it was auto-placed into an implicit
   SECOND ROW inside the 40px icon gutter, where ``.field-chip``'s
   ``display:grid; place-items:center`` stacked its lock above its label. Tall
   card, vertical text. The DOM was already right; the stylesheet was not.

2. **View mode used ``disabled`` to mean "this is a view screen".**
   The DS paints ``disabled`` as "not applicable" -- tertiary text, dead
   border, no shadow, ``not-allowed`` -- so the whole screen read as inactive.
   DS-7 already owns the correct state: read-only, "shown, not editable".

Neither Matriz authority nor persistence is in scope here: those are pinned by
UT-AM2 / UT-AM2H and must keep passing unchanged.
"""
import os
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app import db as app_db_module
from tests.session_support import stamp_auth_version


PROJECT_ROOT = Path(BASE)
FORM_CSS = PROJECT_ROOT / "static" / "css" / "components" / "form.css"

# The six values a Ver Aluno screen must present as readable text.
EXPECTED_LABELS = (
    "Nome",
    "E-mail",
    "Matrícula",
    "Turma",
    "Matriz acadêmica",
    "Status",
)

VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)


# --------------------------------------------------------------------------
# A very small DOM: every .field-card, its row label, and its DIRECT children
#
# Direct children are the whole point. The defect was a third child landing in
# an implicit grid row, which no substring assertion on the response body can
# see -- "Definida pela turma" is equally present whether it renders inline or
# stacked down a 40px gutter.
# --------------------------------------------------------------------------


class _Card:
    def __init__(self, label, attrs):
        self.label = label
        self.attrs = attrs
        self.classes = set((attrs.get("class") or "").split())
        self.children = []  # list of (tag, attrs dict)

    def child_classes(self, index):
        return set((self.children[index][1].get("class") or "").split())

    @property
    def value_child(self):
        """The control carrying the field's value: the second direct child."""
        return self.children[1]


class _FieldCardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self._pending_label = None
        self._in_label = False
        self._label_text = []
        self._card = None
        self._depth = 0

    # -- row labels ------------------------------------------------------
    def handle_data(self, data):
        if self._in_label:
            self._label_text.append(data)

    # -- structure -------------------------------------------------------
    def handle_startendtag(self, tag, attrs):
        # A self-closing tag opens nothing. The default implementation fires
        # handle_starttag AND handle_endtag, which on <path/> inside the
        # password toggle's <svg> raised a depth that was then decremented
        # twice -- the parser lost the rest of the form.
        self.handle_starttag(tag, attrs, opens=False)

    def handle_starttag(self, tag, attrs, opens=True):
        attributes = {key: (value if value is not None else "") for key, value in attrs}
        classes = set((attributes.get("class") or "").split())

        if tag == "label" and "row-label" in classes:
            self._in_label = True
            self._label_text = []
            return

        if self._card is None:
            if "field-card" in classes:
                self._card = _Card(self._pending_label, attributes)
                self._depth = 0
            return

        if self._depth == 0:
            self._card.children.append((tag, attributes))
        if opens and tag not in VOID_TAGS:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag == "label" and self._in_label:
            self._in_label = False
            self._pending_label = "".join(self._label_text).strip()
            return
        if self._card is None:
            return
        if self._depth == 0:
            self.cards.append(self._card)
            self._card = None
        else:
            self._depth -= 1


def _cards(html):
    parser = _FieldCardParser()
    parser.feed(html)
    return parser.cards


def _card_by_label(html, label):
    for card in _cards(html):
        if card.label == label:
            return card
    raise AssertionError(
        f"no .field-card labelled {label!r}; found "
        f"{[card.label for card in _cards(html)]}"
    )


# --------------------------------------------------------------------------
# Route fixture (private prod-1 database; never touches a runtime database)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    app = main.app
    temp_root = tmp_path_factory.mktemp("ver_aluno_view")
    temp_database = temp_root / "ver_aluno.db"

    previous = {
        "env": os.environ.get("APP_DATABASE"),
        "main": main.DATABASE,
        "module": app_db_module.DATABASE,
        "config": app.config.get("DATABASE_PATH"),
        "testing": app.config.get("TESTING"),
        "uploads": app.config.get("UPLOAD_FOLDER"),
    }
    os.environ["APP_DATABASE"] = str(temp_database)
    main.DATABASE = str(temp_database)
    app_db_module.DATABASE = str(temp_database)
    app.config["DATABASE_PATH"] = str(temp_database)
    app.config["TESTING"] = True
    app.config["UPLOAD_FOLDER"] = str(temp_root / "uploads")

    try:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass
            main.init_db()
        with app.test_client() as test_client:
            yield test_client
    finally:
        with app.app_context():
            try:
                main.close_db_connection(None)
            except Exception:
                pass
        if previous["env"] is None:
            os.environ.pop("APP_DATABASE", None)
        else:
            os.environ["APP_DATABASE"] = previous["env"]
        main.DATABASE = previous["main"]
        app_db_module.DATABASE = previous["module"]
        app.config["DATABASE_PATH"] = previous["config"]
        app.config["TESTING"] = previous["testing"]
        app.config["UPLOAD_FOLDER"] = previous["uploads"]


def _login_admin(test_client):
    with test_client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"
        sess["access_level"] = "admin_total"
        sess["perfil"] = "Admin"
        stamp_auth_version(sess)


def _seed(suffix):
    """One Curso, two Matrizes, one Turma (governed by M1) and one Aluno."""
    with main.app.app_context():
        conn = main.get_db_connection()
        ids = {}
        ids["curso"] = conn.execute(
            "INSERT INTO cursos (nome, codigo, duracao_periodos, status) "
            "VALUES (?,?,?,?) RETURNING id",
            (f"Curso VA {suffix}", f"VA{suffix}", 8, "ativo"),
        ).fetchone()["id"]
        for chave, nome in (("m1", f"01.2025 {suffix}"), ("m2", f"02.2025 {suffix}")):
            ids[chave] = conn.execute(
                "INSERT INTO matrizes_atividades (curso_id, nome, status, "
                "horas_aac_obrigatorias, horas_extensao_obrigatorias) "
                "VALUES (?,?,?,?,?) RETURNING id",
                (ids["curso"], nome, "vigente", 120, 60),
            ).fetchone()["id"]
        ids["turma"] = conn.execute(
            "INSERT INTO turmas (nome, status, numero, curso_id, matriz_id, "
            "ano_inicio, semestre_inicio, codigo) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
            (f"VAT{suffix}", "Ativa", 1, ids["curso"], ids["m1"], 2026, 1, f"VAT{suffix}"),
        ).fetchone()["id"]
        email = f"va.{suffix}@teste.local"
        ids["usuario"] = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?,?,?,?) RETURNING id",
            (f"Aluno VA {suffix}", email, main.hash_password("aluno12345"), "aluno"),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, "
            "matriz_id, status) VALUES (?,?,?,?,?,?,?)",
            (
                ids["usuario"],
                f"Aluno VA {suffix}",
                f"VA-{suffix}",
                email,
                ids["turma"],
                None,
                "Ativo",
            ),
        )
        conn.commit()
        return ids


def _detach(ids, matriz_id):
    """Leave the student without a Turma, on his own Matrix authority."""
    with main.app.app_context():
        conn = main.get_db_connection()
        conn.execute(
            "UPDATE alunos SET turma_id=NULL, matriz_id=? WHERE usuario_id=?",
            (matriz_id, ids["usuario"]),
        )
        conn.commit()


@pytest.fixture(scope="module")
def governed(client):
    """A. Student WITH a Turma: the Turma governs his Matriz."""
    _login_admin(client)
    return _seed("GOV")


@pytest.fixture(scope="module")
def individual(client):
    """B. Student WITHOUT a Turma: individual Matriz authority."""
    _login_admin(client)
    ids = _seed("IND")
    _detach(ids, ids["m2"])
    return ids


def _get(client, ids, *, view):
    _login_admin(client)
    url = f"/admin/editar_aluno/{ids['usuario']}"
    if view:
        url += "?view=1"
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


# ==========================================================================
# 1. The governed-Matriz field structure
# ==========================================================================


@pytest.mark.parametrize("view", [True, False], ids=["view", "edit"])
def test_governed_matrix_card_is_one_row_of_three_direct_children(
    client, governed, view
):
    """icon | value | trailing chip -- all three DIRECT children of one card.

    A fourth child, or the chip nested inside the value wrapper, would put the
    explanatory text back into an implicit grid row.
    """
    card = _card_by_label(_get(client, governed, view=view), "Matriz acadêmica")

    assert len(card.children) == 3, [tag for tag, _ in card.children]
    assert card.children[0][0] == "div"
    assert "field-chip" in card.child_classes(0)
    assert "chip-right" not in card.child_classes(0)

    assert card.children[1][0] == "input"

    assert card.children[2][0] == "div"
    assert {"field-chip", "chip-right"} <= card.child_classes(2)


@pytest.mark.parametrize("view", [True, False], ids=["view", "edit"])
def test_governed_matrix_shows_the_real_value_and_the_turma_caption(
    client, governed, view
):
    html = _get(client, governed, view=view)
    card = _card_by_label(html, "Matriz acadêmica")

    _, attributes = card.value_child
    assert attributes["value"] == "01.2025 GOV — VAGOV"
    assert "readonly" in attributes
    # A autoridade continua na turma: nao ha seletor individual nem campo.
    assert 'name="matriz_id"' not in html
    assert "Definida pela turma" in html


def test_governed_matrix_card_is_not_a_file_card(client, governed):
    """The trailing-chip contract must reach it WITHOUT borrowing .file-card.

    Adding ``file-card`` would have made the broken layout render correctly by
    declaring the card a file control: pointer cursor, click-to-open affordance
    and a filled action chip on a field that opens nothing.
    """
    card = _card_by_label(_get(client, governed, view=True), "Matriz acadêmica")
    assert "file-card" not in card.classes


def test_trailing_chip_contract_is_owned_by_the_stylesheet(client, governed):
    """The fix is CSS, and it lives in the DS, not in the page.

    Root cause, restated as a pin: a plain .field-card carrying a direct
    .chip-right needs a third grid track and a horizontal chip box. Without
    both, the chip lands in an implicit second row inside the 40px gutter.
    """
    css = FORM_CSS.read_text(encoding="utf-8")

    assert ".field-card:not(.file-card):has(> .chip-right){" in css
    assert ".field-card:not(.file-card) > .chip-right{" in css

    track = css.split(".field-card:not(.file-card):has(> .chip-right){", 1)[1]
    track = track.split("}", 1)[0]
    assert "grid-template-columns:40px 1fr auto" in track

    chip = css.split(".field-card:not(.file-card) > .chip-right{", 1)[1]
    chip.split("}", 1)
    chip = chip.split("}", 1)[0]
    # Horizontal, on one line, and not squeezed into the icon column.
    assert "display:inline-flex" in chip
    assert "align-items:center" in chip
    assert "white-space:nowrap" in chip
    # Static caption, not an action: the file-card chip's pointer cursor and
    # filled background would read as a button.
    assert "cursor:pointer" not in chip
    assert "background:transparent" in chip


def test_generic_trailing_chip_cannot_reach_a_file_control():
    """Both rules carry :not(.file-card), so no file card is restyled."""
    css = FORM_CSS.read_text(encoding="utf-8")
    for line in css.splitlines():
        stripped = line.strip()
        if not stripped.startswith(".field-card") or ".chip-right" not in stripped:
            continue
        assert ":not(.file-card)" in stripped or ".file-card" in stripped, stripped


def test_page_adds_no_inline_style_for_the_repair():
    template = (PROJECT_ROOT / "templates" / "admin_editar_aluno.html").read_text(
        encoding="utf-8"
    )
    assert "style=" not in template


# ==========================================================================
# 2. View mode must not look disabled
# ==========================================================================


@pytest.mark.parametrize("fixture", ["governed", "individual"])
def test_view_mode_disables_no_control(client, request, fixture):
    """Not one ``disabled`` anywhere in the form surface.

    This is the whole complaint: the screen looked washed out because the DS
    disabled treatment (tertiary text, dead border, no shadow) was applied to
    every row to communicate something the page title already says.
    """
    ids = request.getfixturevalue(fixture)
    html = _get(client, ids, view=True)

    for card in _cards(html):
        for tag, attributes in card.children:
            assert "disabled" not in attributes, (card.label, tag)


@pytest.mark.parametrize("fixture", ["governed", "individual"])
def test_view_mode_presents_every_value_as_read_only_text(client, request, fixture):
    ids = request.getfixturevalue(fixture)
    html = _get(client, ids, view=True)
    cards = {card.label: card for card in _cards(html)}

    assert set(EXPECTED_LABELS) <= set(cards)

    for label in EXPECTED_LABELS:
        tag, attributes = cards[label].value_child
        assert tag == "input", (label, tag)
        assert "readonly" in attributes, label
        assert attributes.get("aria-readonly") == "true", label
        assert attributes.get("value", "").strip(), f"{label} rendered empty"


@pytest.mark.parametrize("fixture", ["governed", "individual"])
def test_view_mode_renders_no_select_at_all(client, request, fixture):
    """Turma / Matriz / Status stop being selects rather than becoming grey ones."""
    ids = request.getfixturevalue(fixture)
    html = _get(client, ids, view=True)

    assert "<select" not in html
    for card in _cards(html):
        assert [tag for tag, _ in card.children].count("select") == 0


def test_view_mode_static_values_carry_no_field_name(client, governed):
    """Nothing that replaced a select may be submittable.

    The static value is the option LABEL, never its id -- giving it the old
    field name would let a stray submit write a course name into turma_id.
    """
    html = _get(client, governed, view=True)
    for label in ("Turma", "Matriz acadêmica", "Status"):
        _, attributes = _card_by_label(html, label).value_child
        assert "name" not in attributes, label
        assert attributes.get("aria-label"), label


def test_view_mode_shows_the_real_turma_and_status(client, governed):
    html = _get(client, governed, view=True)
    assert _card_by_label(html, "Turma").value_child[1]["value"] == "VATGOV"
    assert _card_by_label(html, "Status").value_child[1]["value"] == "Ativo"


def test_view_mode_without_turma_shows_the_individual_matrix(client, individual):
    html = _get(client, individual, view=True)

    assert _card_by_label(html, "Matriz acadêmica").value_child[1]["value"] == (
        "02.2025 IND — VAIND"
    )
    assert _card_by_label(html, "Turma").value_child[1]["value"] == "—"
    # Sem turma nao ha turma que defina nada.
    assert "Definida pela turma" not in html


@pytest.mark.parametrize("fixture", ["governed", "individual"])
def test_view_mode_omits_the_password_row(client, request, fixture):
    """There is no password value, so there is no password row.

    A read-only empty password control would announce material the screen does
    not have and must not show.
    """
    ids = request.getfixturevalue(fixture)
    html = _get(client, ids, view=True)

    assert 'name="senha"' not in html
    assert 'type="password"' not in html
    assert "Nova Senha" not in html
    assert "Nova Senha (opcional)" not in [card.label for card in _cards(html)]


@pytest.mark.parametrize("fixture", ["governed", "individual"])
def test_view_mode_offers_only_navigation(client, request, fixture):
    ids = request.getfixturevalue(fixture)
    html = _get(client, ids, view=True)

    assert 'type="submit"' not in html
    assert "Salvar" not in html
    assert "Cancelar" not in html
    assert "Voltar" in html


# ==========================================================================
# 3. Edit mode must remain unchanged
# ==========================================================================


def test_edit_mode_keeps_every_editable_control(client, governed):
    html = _get(client, governed, view=False)

    for label in ("Nome", "E-mail", "Matrícula"):
        tag, attributes = _card_by_label(html, label).value_child
        assert tag == "input"
        assert "readonly" not in attributes, label
        assert "disabled" not in attributes, label

    # Troca de senha, seletor de turma, seletor de status, Salvar/Cancelar.
    assert 'name="senha"' in html
    assert 'type="password"' in html
    assert _card_by_label(html, "Turma").value_child[0] == "select"
    assert _card_by_label(html, "Status").value_child[0] == "select"
    assert 'type="submit"' in html
    assert "Salvar" in html
    assert "Cancelar" in html
    assert "Voltar" not in html


def test_edit_mode_keeps_the_turma_selector_preselected(client, governed):
    html = _get(client, governed, view=False)
    assert f'<option value="{governed["turma"]}" selected>VATGOV</option>' in html


def test_edit_mode_without_turma_keeps_the_individual_matrix_selector(
    client, individual
):
    html = _get(client, individual, view=False)

    card = _card_by_label(html, "Matriz acadêmica")
    assert card.value_child[0] == "select"
    assert card.value_child[1]["name"] == "matriz_id"
    assert f'<option value="{individual["m2"]}" selected>' in html
    # Sem turma, nenhum chip reivindica autoridade da turma.
    assert len(card.children) == 2


def test_edit_mode_matrix_authority_contract_is_untouched(client, governed):
    """Turma-bound: still no selector, still no submittable matriz_id."""
    html = _get(client, governed, view=False)
    assert 'name="matriz_id"' not in html
    assert "Definida pela turma" in html
