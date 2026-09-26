"""UI-B08 geometry: the shared Design System status-column contract.

The rule under test, for any list carrying a semantic status/situação column:

  * last data column, as far right as the row's data layout allows;
  * header and values centred;
  * track sized intrinsically to its content, never to leftover width;
  * descriptive columns absorb the remaining space;
  * actions are a separate contract and unaffected.

These tests are structural and cascade-level, not pixel-level: there is no
browser in this environment, so they assert the *contract* (which selector
wins, which track is flexible, which classes are present) rather than rendered
coordinates. Semantics -- derivation, labels, tones, v10 `sent_at` -- are
covered by ``test_access_onboarding_status_ui_b08.py`` and are untouched here.
"""

from __future__ import annotations

import re
from pathlib import Path

import main
from app.status_presentation import (
    ACCESS_STATUS_TONES,
    DS_STATUS_TONES,
)
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIST_CARDS_CSS = PROJECT_ROOT / "static" / "css" / "components" / "list-cards.css"
MODERN_CSS = PROJECT_ROOT / "static" / "css" / "modern-style.css"
ACESSO_TEMPLATE = PROJECT_ROOT / "templates" / "admin_acesso.html"
DS_README = PROJECT_ROOT / "docs" / "design-system" / "README.md"

STATUS_COL_CLASS = "status-col"


def _acesso_style_block() -> str:
    """The page's own <style> block -- where a page-local rule would hide."""
    source = ACESSO_TEMPLATE.read_text(encoding="utf-8")
    return source[: source.index("{% block content %}")]


def _acesso_style_rules() -> str:
    """The same block with CSS comments stripped.

    The prose explaining *why* the page defers to the shared contract naturally
    names it; only actual declarations are evidence of a page-local rule.
    """
    return re.sub(r"/\*.*?\*/", "", _acesso_style_block(), flags=re.S)


def _rendered_pills(html: str) -> set[str]:
    """The status labels actually rendered as pills on the page."""
    return set(
        re.findall(
            r'<span class="badge status-badge status-pill status-\w+">([^<]+)</span>',
            html,
        )
    )


def _imp_cols_tracks() -> list[str]:
    """The declared `--imp-cols` tracks for .imp-acesso, in order."""
    block = _acesso_style_block()
    decl = block[block.index("--imp-cols:") :]
    decl = decl[: decl.index(";")]
    body = decl.split(":", 1)[1]
    return [line.strip() for line in body.strip().splitlines() if line.strip()]


# ------------------------------------------------- THE SHARED CONTRACT EXISTS


def test_the_status_column_contract_lives_in_the_shared_geometry_owner():
    css = LIST_CARDS_CSS.read_text(encoding="utf-8")
    assert "--imp-status-col:" in css, "the shared status track token is missing"
    assert f".cell.{STATUS_COL_CLASS}" in css, "the shared status-column class is missing"


def test_the_shared_track_is_a_stable_length_not_content_dependent():
    """The track must not consult the rendered rows, and must not be flexible.

    `max-content` is specifically rejected: it fits the widest pill *present*,
    so the same list would shift its status column between pages. `fr` is
    rejected for the opposite reason -- it absorbs the row's leftover width.
    """
    css = LIST_CARDS_CSS.read_text(encoding="utf-8")
    value = re.search(r"--imp-status-col:\s*([^;]+);", css).group(1).strip()

    assert value.startswith("calc("), f"--imp-status-col is {value!r}"
    for content_dependent in ("max-content", "min-content", "fit-content", "auto"):
        assert content_dependent not in value, (
            f"--imp-status-col uses {content_dependent!r}, so the column width "
            "depends on which statuses happen to be rendered"
        )
    assert "fr" not in value
    # Derived from the domain's label count and the shared chrome, nothing else.
    assert "var(--imp-status-col-chars)" in value
    assert "var(--imp-status-col-chrome)" in value
    assert "var(--imp-status-col-font-scale)" in value
    assert "1ch" in value, "the reservation is not typography-relative"


def test_the_font_scale_is_the_two_declared_font_sizes_and_nothing_else():
    """`ch` resolves at the grid's font-size, the text is the pill's.

    Without this term the column over-reserves by about a third -- which is how
    the first fixed-width attempt landed wider than the flexible track it
    replaced. The ratio must stay pinned to the two declared sizes so it cannot
    drift into a fudge factor.
    """
    css = LIST_CARDS_CSS.read_text(encoding="utf-8")
    modern = MODERN_CSS.read_text(encoding="utf-8")
    tokens = (PROJECT_ROOT / "static" / "css" / "foundation" / "tokens.css").read_text(
        encoding="utf-8"
    )

    numerator, denominator = (
        int(part)
        for part in re.search(
            r"--imp-status-col-font-scale:\s*calc\(\s*(\d+)\s*/\s*(\d+)\s*\)", css
        ).group(1, 2)
    )

    pill = modern[modern.index(".badge.status-pill{") :]
    pill = pill[: pill.index("}")]
    pill_font_size = int(re.search(r"font-size:(\d+)px", pill).group(1))
    grid_font_size = int(re.search(r"--font-size-base:\s*(\d+)px", tokens).group(1))

    assert (numerator, denominator) == (pill_font_size, grid_font_size), (
        f"the font scale is {numerator}/{denominator} but the pill renders at "
        f"{pill_font_size}px inside a {grid_font_size}px grid box"
    )


def test_the_track_reserves_the_longest_label_of_every_status_domain_by_default():
    """An adopting list that forgets to declare its domain must over-reserve,
    never truncate. The default therefore tracks the longest label anywhere."""
    from app.status_presentation import (
        ACCESS_STATUS_TONES,
        MATRIZ_STATUS_TONES,
        REQUEST_STATUS_TONES,
    )

    css = LIST_CARDS_CSS.read_text(encoding="utf-8")
    default_chars = int(
        re.search(r"--imp-status-col-chars:\s*(\d+)\s*;", css).group(1)
    )
    every_label = (
        list(ACCESS_STATUS_TONES) + list(REQUEST_STATUS_TONES) + list(MATRIZ_STATUS_TONES)
    )
    assert default_chars == max(len(label) for label in every_label), (
        "the file-level default no longer matches SGAA's longest status label"
    )


def test_the_chrome_term_matches_the_pill_and_cell_it_reserves_for():
    """The chrome is taken from the two owners, not guessed."""
    css = LIST_CARDS_CSS.read_text(encoding="utf-8")
    modern = MODERN_CSS.read_text(encoding="utf-8")

    pill = modern[modern.index(".badge.status-pill{") :]
    pill = pill[: pill.index("}")]
    pill_padding = int(re.search(r"padding:0 (\d+)px", pill).group(1))
    pill_gap = int(re.search(r"gap:(\d+)px", pill).group(1))
    pill_border = int(re.search(r"border:(\d+)px", pill).group(1))

    dot = modern[modern.index(".badge.status-pill::before{") :]
    dot = dot[: dot.index("}")]
    dot_width = int(re.search(r"width:(\d+)px", dot).group(1))

    cell = css[css.index(".impresso-card .cell{") :]
    cell = cell[: cell.index("}")]
    cell_padding = int(re.search(r"padding:0 (\d+)px", cell).group(1))

    expected = (
        pill_padding * 2 + pill_border * 2 + pill_gap + dot_width + cell_padding * 2
    )
    declared = int(re.search(r"--imp-status-col-chrome:\s*(\d+)px", css).group(1))
    assert declared == expected, (
        f"--imp-status-col-chrome is {declared}px but the pill and cell it reserves "
        f"for now need {expected}px"
    )


def test_the_shared_contract_centres_both_header_and_values():
    css = LIST_CARDS_CSS.read_text(encoding="utf-8")
    block = css[css.index("SHARED STATUS COLUMN CONTRACT") :]
    block = block[: block.index("@media print")]
    assert f".impresso-card .cell.{STATUS_COL_CLASS}" in block
    assert f".impresso-card.header .cell.{STATUS_COL_CLASS}" in block
    assert "justify-content:center" in block
    assert "text-align:center" in block
    # It must not smuggle a width in beside the alignment.
    assert "width:" not in block
    assert "px" not in block.split("{", 1)[1], "the alignment contract declared a pixel size"


def test_the_shared_contract_outranks_every_per_list_left_alignment():
    """Specificity + source order, the two things that decide the winner.

    Several `.imp-*` scopes left-align their whole row and re-centre individual
    columns with `:nth-child()`. The contract has to beat both.
    """
    css = LIST_CARDS_CSS.read_text(encoding="utf-8")
    contract_at = css.index(f".impressoes-cards .impresso-card .cell.{STATUS_COL_CLASS}")

    competitors = [
        m.start()
        for m in re.finditer(r"\.imp-[\w-]+ \.impresso-card(\.header)? \.cell", css)
    ]
    assert competitors, "no per-list cell rules found; this guard would be vacuous"
    assert contract_at > max(competitors), (
        "the status-column contract is declared before a per-list cell rule, so an "
        "equally specific :nth-child() would win on source order"
    )

    # (0,4,0): four compound classes in the selector.
    selector = f".impressoes-cards .impresso-card .cell.{STATUS_COL_CLASS}"
    assert selector.count(".") == 4

    # And it wins without needing !important anywhere.
    block = css[contract_at : css.index("@media print", contract_at)]
    assert "!important" not in block


def test_the_pill_cannot_wrap():
    """Guaranteed twice: by the pill itself and by the shared cell."""
    modern = MODERN_CSS.read_text(encoding="utf-8")
    pill = modern[modern.index(".badge.status-pill{") :]
    pill = pill[: pill.index("}")]
    assert "white-space:nowrap" in pill

    css = LIST_CARDS_CSS.read_text(encoding="utf-8")
    cell = css[css.index(".impresso-card .cell{") :]
    cell = cell[: cell.index("}")]
    assert "white-space:nowrap" in cell


# ---------------------------------------------------- ADMIN > ACESSO APPLIES IT


def test_status_is_the_last_declared_track_and_is_the_only_inflexible_one():
    tracks = _imp_cols_tracks()
    assert len(tracks) == 6, f"expected six data tracks, got {tracks}"

    last = tracks[-1]
    assert "var(--imp-status-col)" in last, (
        f"the last track is {last!r}; it must consume the shared token"
    )
    # The status track owns no fraction, so it cannot absorb surplus width --
    # this is what pins it to the right edge of the data layout.
    assert "fr" not in last

    # Every descriptive column keeps a fraction, so they take all the surplus.
    for track in tracks[:-1]:
        assert "fr" in track, f"descriptive track {track!r} lost its flexible share"


def test_the_five_descriptive_minima_were_not_reduced_to_pay_for_the_column():
    tracks = _imp_cols_tracks()
    minima = [int(re.search(r"minmax\((\d+)px", t).group(1)) for t in tracks[:-1]]
    assert minima == [180, 220, 180, 160, 160]


def test_the_page_declares_no_local_status_column_width_or_alignment():
    """The contract is shared or it is not a contract."""
    rules = _acesso_style_rules()

    # No page-local class of the kind the brief forbids.
    assert "acesso-status" not in rules
    assert f".imp-acesso .cell.{STATUS_COL_CLASS}" not in rules
    # No page-local rule whose selector mentions the shared class at all.
    for selector in re.findall(r"([^{}]+)\{", rules):
        assert STATUS_COL_CLASS not in selector, (
            f"page-local rule re-declares the shared contract: {selector.strip()!r}"
        )

    # The old page-local nth-child(6) left-alignment is gone.
    assert "nth-child(6)" not in rules, (
        "a page-local rule still targets the status column by position"
    )

    # And no page-local pixel width for the track.
    assert "150px" not in rules


def test_there_is_exactly_one_notion_of_the_status_column_width():
    """The scroll threshold reuses the track token; it does not restate it.

    An earlier round carried a second, unrelated `--imp-status-col-reserve:120px`
    beside the track. Two numbers for one column is how they drift apart.
    """
    block = _acesso_style_block()
    value = re.search(r"--imp-list-min-width:\s*([^;]+);", block).group(1).strip()
    assert value.startswith("calc("), f"--imp-list-min-width is a bare {value!r}"
    assert "var(--imp-status-col)" in value, (
        "the threshold does not reuse the shared status-column token"
    )
    assert "var(--imp-col-gap)" in value

    for source in (
        LIST_CARDS_CSS.read_text(encoding="utf-8"),
        _acesso_style_block(),
        (PROJECT_ROOT / "static" / "css" / "foundation" / "tokens.css").read_text(encoding="utf-8"),
    ):
        assert "--imp-status-col-reserve" not in source, (
            "a second, independent status-column width token is back"
        )


def test_the_header_and_cell_opt_in_through_the_shared_class_only():
    source = ACESSO_TEMPLATE.read_text(encoding="utf-8")

    header = source[source.index("cl.header([") :]
    header = header[: header.index("]) }}")]
    cells = re.findall(r"\{'text':\s*'([^']+)',\s*'class':'([^']+)'\}", header)
    assert cells[-1] == ("Situação", STATUS_COL_CLASS), f"header cells: {cells}"
    # It must not also carry left/center -- the shared class owns alignment.
    assert cells[-1][1] == STATUS_COL_CLASS

    row = source[source.index("{{ cl.row([") :]
    row = row[: row.index("], {")]
    status_cell = row[row.index("status_label('acesso'") :]
    assert f"'class':'{STATUS_COL_CLASS}'" in status_cell
    assert "'class':'left'" not in status_cell
    assert "'class':'center'" not in status_cell


# --------------------------------------------------------------- AS RENDERED


def test_rendered_status_cell_carries_the_shared_class_and_nothing_local(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b08-geom.db") as env:
        client = env["client"]
        login_admin(client)
        html = client.get("/admin/acesso?per_page=100").get_data(as_text=True)

        # Header: exactly one, through the shared class.
        assert html.count(f'<div class="cell {STATUS_COL_CLASS}">Situação</div>') == 1

        # Every status pill sits in a shared-class cell, never a left one.
        pills = re.findall(
            r'<div class="cell ([^"]+)">\s*<span class="badge status-badge status-pill',
            html,
        )
        assert pills, "no status pills rendered"
        assert set(pills) == {STATUS_COL_CLASS}, f"status cells carry {set(pills)}"

        # No inline centring anywhere on the column.
        for cell in re.findall(
            rf'<div class="cell {STATUS_COL_CLASS}">.*?</div>', html, re.S
        ):
            assert "style=" not in cell, f"inline style on a status cell: {cell}"
            assert "text-align" not in cell


def test_status_cell_is_the_last_cell_of_every_rendered_row(tmp_path):
    with isolated_versioned_app_env(tmp_path, "b08-geom-last.db") as env:
        client = env["client"]
        login_admin(client)
        html = client.get("/admin/acesso?per_page=100").get_data(as_text=True)

        body = html[html.index('id="acesso-list"') :]
        rows = re.findall(r'role="listitem".*?(?=role="listitem"|\Z)', body, re.S)
        assert rows, "no rows rendered"
        for row in rows:
            cells = re.findall(r'<div class="cell ([^"]+)"', row)
            assert len(cells) == 6, f"row has {len(cells)} cells: {cells}"
            assert cells[-1] == STATUS_COL_CLASS, (
                f"the status cell is not last; order was {cells}"
            )


def test_every_supported_label_renders_through_the_same_contract(tmp_path):
    """All five states, one shared cell class, one pill, no wrapping markup."""
    import datetime as dt

    from app.password_tokens import PURPOSE_FIRST_ACCESS, issue_password_token, mark_password_token_sent
    from app.security.passwords import hash_password
    from app.user_accounts import (
        CREDENTIAL_STATE_PENDING,
        CREDENTIAL_STATE_PERSONAL,
        create_usuario_with_access_level,
        set_usuario_password_hash,
    )

    with isolated_versioned_app_env(tmp_path, "b08-geom-labels.db") as env:
        client = env["client"]
        login_admin(client)
        with main.app.app_context():
            conn = main.get_db_connection()

            def seed(label, state=CREDENTIAL_STATE_PENDING):
                cursor = create_usuario_with_access_level(
                    conn, label, f"{label}@example.test", hash_password("x"),
                    "admin", "admin_total", credential_state=state,
                )
                conn.commit()
                return int(cursor.lastrowid)

            seed("geompendente")
            delivered = seed("geomdisponibilizado")
            _r, t = issue_password_token(conn, delivered, PURPOSE_FIRST_ACCESS)
            mark_password_token_sent(conn, t)
            expired = seed("geomexpirado")
            _r, t = issue_password_token(
                conn, expired, PURPOSE_FIRST_ACCESS, ttl=dt.timedelta(hours=-1)
            )
            mark_password_token_sent(conn, t)
            seed("geomativo", state=CREDENTIAL_STATE_PERSONAL)
            conn.commit()

        html = client.get("/admin/acesso?per_page=200").get_data(as_text=True)

        # Revogado is derivable but the active list excludes revoked rows by
        # pre-existing design, so four of the five are renderable here. The
        # contract still has to cover its label, which the CSS-level tests above
        # prove is width-independent.
        for label in ("Pendente", "Disponibilizado", "Ativo", "Expirado"):
            match = re.search(
                rf'<div class="cell {STATUS_COL_CLASS}">\s*'
                rf'<span class="badge status-badge status-pill status-(\w+)">{label}</span>',
                html,
            )
            assert match, f"{label} did not render through the shared contract"
            assert match.group(1) in DS_STATUS_TONES

        assert set(ACCESS_STATUS_TONES) == {
            "Pendente", "Disponibilizado", "Ativo", "Revogado", "Expirado",
        }


# --------------------------------- WIDTH IS DATASET-INDEPENDENT (the contract)


def test_acesso_reserves_its_own_domains_longest_label():
    """The declared character count IS the domain's longest supported label.

    This is what makes the reservation "largest SUPPORTED" rather than "largest
    rendered": the number is pinned to `ACCESS_STATUS_TONES`, so a new or
    renamed status that outgrows the column fails here instead of truncating in
    a browser.
    """
    from app.status_presentation import ACCESS_STATUS_TONES

    declared = int(
        re.search(
            r"\.imp-acesso\{\s*--imp-status-col-chars:\s*(\d+)\s*;",
            _acesso_style_rules(),
        ).group(1)
    )
    longest = max(ACCESS_STATUS_TONES, key=len)
    assert declared == len(longest), (
        f".imp-acesso reserves {declared} characters but the Acesso domain's longest "
        f"supported status is {longest!r} ({len(longest)} characters)"
    )
    # Every supported label fits inside the reservation, including the ones the
    # active list cannot currently render (Revogado).
    for label in ACCESS_STATUS_TONES:
        assert len(label) <= declared, f"{label!r} exceeds the reserved width"


def test_a_page_showing_only_ativo_still_reserves_disponibilizado(tmp_path):
    """The requirement, stated as its own test.

    A dataset whose longest pill is `Ativo` must still reserve the width of
    `Disponibilizado`, because the reservation is declared by the domain and the
    CSS never looks at the rows.
    """
    from app.status_presentation import ACCESS_STATUS_ATIVO, ACCESS_STATUS_TONES

    with isolated_versioned_app_env(tmp_path, "b08-width-ativo.db") as env:
        client = env["client"]
        login_admin(client)
        with main.app.app_context():
            conn = main.get_db_connection()
            # Force the whole visible population to the shortest state.
            conn.execute(
                "UPDATE usuario_credenciais SET estado='personal' WHERE acesso_ativo=1"
            )
            conn.commit()

        html = client.get("/admin/acesso?per_page=200").get_data(as_text=True)
        rendered = _rendered_pills(html)
        longest_supported = max(ACCESS_STATUS_TONES, key=len)
        # The dataset now contains only short labels -- Ativo, plus Pendente for
        # any identity with no credential row at all. What matters is that the
        # domain's longest label is nowhere on the page.
        assert ACCESS_STATUS_ATIVO in rendered
        assert longest_supported not in rendered
        assert max(len(label) for label in rendered) < len(longest_supported), (
            f"fixture did not isolate short labels: {rendered}"
        )

        # ...and the served CSS still reserves the domain's longest label.
        declared = int(
            re.search(
                r"\.imp-acesso\{\s*--imp-status-col-chars:\s*(\d+)\s*;", html
            ).group(1)
        )
        assert declared == len(max(ACCESS_STATUS_TONES, key=len)) == 15
        assert "max-content" not in html.split("--imp-cols")[1].split("}")[0]


def test_adding_a_longer_status_row_does_not_change_the_track(tmp_path):
    """Same page, two row populations, byte-identical status geometry."""
    import datetime as dt

    from app.password_tokens import (
        PURPOSE_FIRST_ACCESS,
        issue_password_token,
        mark_password_token_sent,
    )
    from app.security.passwords import hash_password
    from app.user_accounts import (
        CREDENTIAL_STATE_PENDING,
        create_usuario_with_access_level,
    )

    def geometry_of(html: str) -> tuple[str, str, str]:
        tracks = html[html.index("--imp-cols") :]
        tracks = tracks[: tracks.index("}")]
        chars = re.search(r"--imp-status-col-chars:\s*(\d+)\s*;", html).group(1)
        threshold = re.search(r"--imp-list-min-width:\s*([^;]+);", html).group(1)
        return (tracks, chars, threshold)

    with isolated_versioned_app_env(tmp_path, "b08-width-stable.db") as env:
        client = env["client"]
        login_admin(client)

        before_html = client.get("/admin/acesso?per_page=200").get_data(as_text=True)
        before = geometry_of(before_html)
        # Match rendered PILLS, not the raw word: the page's own CSS comment
        # names the longest label while explaining the reservation.
        assert _rendered_pills(before_html).isdisjoint({"Disponibilizado", "Expirado"})

        with main.app.app_context():
            conn = main.get_db_connection()
            for label, ttl in (
                ("widthdisponibilizado", None),
                ("widthexpirado", dt.timedelta(hours=-1)),
            ):
                cursor = create_usuario_with_access_level(
                    conn, label, f"{label}@example.test", hash_password("x"),
                    "admin", "admin_total", credential_state=CREDENTIAL_STATE_PENDING,
                )
                _raw, token_id = issue_password_token(
                    conn, int(cursor.lastrowid), PURPOSE_FIRST_ACCESS, ttl=ttl
                )
                mark_password_token_sent(conn, token_id)
            conn.commit()

        after_html = client.get("/admin/acesso?per_page=200").get_data(as_text=True)
        after = geometry_of(after_html)
        # The longest pill is now present...
        assert {"Disponibilizado", "Expirado"} <= _rendered_pills(after_html)
        # ...and the column's geometry did not react to it at all.
        assert after == before, (
            "the status column geometry changed when a longer status appeared:\n"
            f"  before={before}\n  after ={after}"
        )


def test_the_track_is_a_fixed_length_in_the_served_grid(tmp_path):
    """As served: the last track is the shared token and nothing content-based."""
    with isolated_versioned_app_env(tmp_path, "b08-width-served.db") as env:
        login_admin(env["client"])
        html = env["client"].get("/admin/acesso").get_data(as_text=True)
        tracks = html[html.index("--imp-cols") :]
        tracks = tracks[: tracks.index("}")]
        assert "var(--imp-status-col)" in tracks
        for content_dependent in ("max-content", "min-content", "fit-content", "auto"):
            assert content_dependent not in tracks
        # The status track is the only one with no flexible share.
        assert tracks.count("fr") == 5


# -------------------------------------------------- ACTIONS ARE UNTOUCHED


def test_the_floating_action_bar_contract_is_unchanged(tmp_path):
    """Actions are a separate contract: not a grid column, not restyled."""
    source = ACESSO_TEMPLATE.read_text(encoding="utf-8")
    for action in ("edit", "email", "reset", "delete"):
        assert f'data-action="{action}"' in source

    # The bar is appended to <body>, so it never participates in --imp-cols.
    assert "document.body.appendChild(bar)" in source
    assert "pedido-actions-float access-actions-float" in source

    # The status column added no action affordance and no bar rule.
    rules = _acesso_style_rules()
    assert ".access-actions-float .act-btn" in rules
    for selector in re.findall(r"([^{}]+)\{", rules):
        assert not (STATUS_COL_CLASS in selector and "act-btn" in selector), (
            "the status column reached into the action-bar contract"
        )

    with isolated_versioned_app_env(tmp_path, "b08-geom-actions.db") as env:
        client = env["client"]
        login_admin(client)
        html = client.get("/admin/acesso?per_page=100").get_data(as_text=True)
        for action in ("edit", "email", "reset", "delete"):
            assert f'data-action="{action}"' in html
        # Row action data attributes still ride on the row, not the status cell.
        assert "data-reset-url=" in html
        assert "data-email-url=" in html


# ------------------------------------------------------------ DOCUMENTATION


def test_the_rule_is_persisted_in_the_design_system_documentation():
    doc = DS_README.read_text(encoding="utf-8")
    assert "Status column contract" in doc
    section = doc[doc.index("Status column contract") :]
    section = section[: section.index("### 2.7")]
    for claim in (
        "last data column",
        "centred",
        "descriptive columns absorb",
        "--imp-status-col",
        STATUS_COL_CLASS,
        "actions are a separate contract",
    ):
        assert claim.lower() in section.lower(), f"the DS rule omits: {claim}"
