"""The catalogue of pages and UI states captured by the visual harness.

Adding a shot here is how you extend visual coverage. Each shot must be
*deterministic*: same data, same layout, no clock, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Shot:
    name: str
    path: str = ""
    full_page: bool = True
    role: str = "admin"
    after: Callable | None = None
    """Optional interaction run after navigation, to reach a UI state."""
    viewport: tuple[int, int] | None = None
    """Capture at a different size, to pin a responsive breakpoint."""

    def render(self, page, base_url: str, default_viewport: dict) -> None:
        # Always set the viewport, never only when this shot overrides it:
        # otherwise a resized shot leaks its size into every shot after it.
        width, height = self.viewport or (default_viewport["width"], default_viewport["height"])
        page.set_viewport_size({"width": width, "height": height})
        if self.path:
            page.goto(f"{base_url}{self.path}", wait_until="domcontentloaded")
        if self.after is not None:
            self.after(page)


# --------------------------------------------------------------------- auth

def login(page, base_url: str, email: str, password: str) -> None:
    page.goto(f"{base_url}/logout", wait_until="domcontentloaded")
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")
    page.fill("#email", email)
    page.fill("#senha", password)
    page.click("button[type=submit], input[type=submit]")
    page.wait_for_load_state("domcontentloaded")


# ----------------------------------------------------------- state helpers

def _click_if_present(page, selector: str) -> None:
    locator = page.locator(selector).first
    if locator.count() and locator.is_visible():
        locator.click()
        page.wait_for_timeout(150)


def open_sort_popover(page) -> None:
    _click_if_present(page, "#sort-field")


def open_filter_popover(page) -> None:
    _click_if_present(page, "#filter-btn")


def focus_first_control(page) -> None:
    """Reach :focus-visible the way a keyboard user does."""
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    page.wait_for_timeout(100)


def focus_sort_field(page) -> None:
    """Tab to the sort field button, so its :focus-visible ring renders.

    Must be a real Tab: calling .focus() moves focus without arming
    :focus-visible, and the ring is exactly what this shot exists to pin.

    Before F-7 the two sort controls set `outline:0` and `box-shadow:none`
    unconditionally, so a keyboard user saw nothing at all here.
    """
    page.evaluate("() => { if (document.activeElement && document.activeElement.blur) "
                  "document.activeElement.blur(); }")
    for _ in range(60):
        page.keyboard.press("Tab")
        if page.evaluate("() => document.activeElement === document.querySelector('#sort-field')"):
            page.wait_for_timeout(100)
            return
    raise RuntimeError("never reached #sort-field by keyboard — this shot would pin nothing")


def open_actions_menu(page) -> None:
    """Open the toolbar's selection actions menu."""
    page.click(".toolbar-actions-shell > .btn[aria-haspopup='menu']")
    page.wait_for_timeout(150)
    if page.evaluate("() => document.querySelector('.popover.toolbar-actions-menu').hidden"):
        raise RuntimeError("actions menu did not open — this shot would pin nothing")


def open_modal(modal_id: str):
    """Reveal a modal deterministically by dropping its `hidden` attribute.

    Every modal in this codebase is a `.modal-overlay` hidden with the `hidden`
    attribute and shown by `.modal-overlay[hidden]{display:none}`. Unhiding it
    directly is stable across runs, whereas driving the real trigger depends on
    per-page JavaScript, seeded rows and menu state. What is under test here is
    the modal's CSS, and that renders identically either way.
    """

    def _open(page):
        page.evaluate(
            """(id) => {
                const el = document.getElementById(id);
                if (!el) throw new Error('modal not found: ' + id);
                el.removeAttribute('hidden');
            }""",
            modal_id,
        )
        page.wait_for_timeout(150)

    return _open


def focus_toolbar_search(page) -> None:
    """Focus the toolbar search box.

    The toolbar input group restyles itself on :focus-within (border, chip
    background, focus ring). DS-5 relocates the ID-scoped toolbar overrides
    that sit right next to those rules, so this state needs to be pinned
    before anything moves.
    """
    page.click("#busca-impressoes")
    page.wait_for_timeout(150)


def scroll_toolbar_into_view(page) -> None:
    """Bring a below-the-fold toolbar into the captured frame.

    ``full_page=True`` does nothing in this application. ``.app-layout`` is
    ``height:100vh`` and ``.app-main`` is ``overflow:auto``, so the *document*
    is always exactly viewport-height and the page scrolls INSIDE .app-main:
    measured on /admin/acesso at 768, documentElement.scrollHeight is 900 while
    .app-main.scrollHeight is 1545. A "full page" screenshot therefore captures
    the viewport and nothing more, on every shot in this catalogue.

    /admin/acesso is the only toolbar consumer that renders a long preamble
    (five profile cards plus the default-password panel) above its toolbar, so
    at 768 the toolbar sits at y=1264 — 364px below the fold and invisible to
    the capture. Scrolling .app-main is what actually reveals it.

    Deterministic on purpose: the scroll offset is computed from the toolbar's
    own position rather than a literal, and nothing here animates
    (scroll-behavior is never set to smooth in this codebase).
    """
    page.evaluate(
        """() => {
            const main = document.querySelector('.app-main');
            const toolbar = document.querySelector('.app-track .toolbar');
            if (!main || !toolbar) throw new Error('no .app-main/.toolbar to scroll to');
            main.scrollTop +=
                toolbar.getBoundingClientRect().top - main.getBoundingClientRect().top - 24;
        }"""
    )
    page.wait_for_timeout(150)


def focus_form_control(page) -> None:
    """Focus the first text control inside a .field-card.

    Pins .field-card:focus-within plus input.control:focus, which is the only
    focus contract the form pack has.
    """
    page.evaluate(
        """() => {
            const el = document.querySelector('.field-card input.control, .field-card select.control');
            if (!el) throw new Error('no .field-card control on this page');
            el.focus();
        }"""
    )
    page.wait_for_timeout(150)


def hover_form_control(page) -> None:
    page.locator(".field-card").first.hover()
    page.wait_for_timeout(150)


def disable_form_controls(page) -> None:
    """Disable every form control.

    There is no `:disabled` rule for .control anywhere in the codebase, so this
    captures the browser default. It exists to detect a change, not to protect
    a designed state — see the accessibility notes in docs/design-system.
    """
    page.evaluate(
        """() => document.querySelectorAll('.field-card .control')
                    .forEach(el => el.setAttribute('disabled', 'disabled'))"""
    )
    page.wait_for_timeout(150)


def invalidate_natively(page) -> None:
    """Reach `:user-invalid` the way a user does.

    Types a value the browser itself rejects into a type=email control and
    blurs. `:user-invalid` only applies after interaction, which is exactly why
    the contract uses it instead of `:invalid` — the latter would flag every
    empty required field the moment a blank "Adicionar" form opened.

    Kept separate from the aria-invalid shot on purpose: they exercise
    different selectors and could regress independently.
    """
    # Must be TRUSTED input: assigning .value from JS does not mark the control
    # as user-interacted, so `:user-invalid` never matches and the shot would
    # silently pin nothing. Playwright's fill/press go through CDP and are
    # trusted, which is what actually flips the state.
    field = page.locator('.field-card input[type="email"].control').first
    field.click()
    field.fill("nao-e-um-email")
    page.keyboard.press("Tab")
    page.wait_for_timeout(250)
    matched = page.evaluate(
        """() => !!document.querySelector('.field-card input[type="email"].control:user-invalid')"""
    )
    if not matched:
        raise RuntimeError(":user-invalid did not apply — this shot would pin nothing")


def invalidate_via_aria(page) -> None:
    """Server/application validation: `[aria-invalid="true"]` plus a message.

    This is the path a Flask-rendered error takes. It shares no selector with
    the `:user-invalid` rule.
    """
    page.evaluate(
        """() => {
            const el = document.querySelector('.field-card input.control');
            if (!el) throw new Error('no control on this page');
            el.setAttribute('aria-invalid', 'true');
            const row = el.closest('.form-row');
            const msg = document.createElement('span');
            msg.className = 'field-error';
            msg.textContent = 'Já existe um aluno com este nome.';
            row.appendChild(msg);
        }"""
    )
    page.wait_for_timeout(150)


def make_readonly(page) -> None:
    page.evaluate(
        """() => {
            const cs = [...document.querySelectorAll('.field-card input.control')];
            if (!cs.length) throw new Error('no control on this page');
            cs.slice(0, 2).forEach(el => el.setAttribute('readonly', 'readonly'));
        }"""
    )
    page.wait_for_timeout(150)


def show_toast(page) -> None:
    page.evaluate(
        """() => {
            const t = document.createElement('div');
            t.className = 'toast show success';
            t.textContent = 'Operação concluída com sucesso';
            document.body.appendChild(t);
        }"""
    )
    page.wait_for_timeout(100)


# ------------------------------------------------------------------- shots

ADMIN_PAGES = [
    ("admin_dashboard", "/admin/dashboard"),
    ("admin_requisicoes", "/admin/requisicoes"),
    ("admin_atividades", "/admin/atividades"),
    ("admin_matrizes", "/admin/matrizes"),
    ("admin_alunos", "/admin/alunos"),
    ("admin_turmas", "/admin/turmas"),
    ("admin_cursos", "/admin/cursos"),
    ("admin_arquivos", "/admin/arquivos"),
    ("admin_alertas", "/admin/alertas"),
    ("admin_reportes", "/admin/reportes"),
    ("admin_meus_dados", "/admin/meus_dados"),
    ("admin_acesso", "/admin/acesso"),
    ("admin_configuracoes", "/admin/configuracoes"),
    ("admin_mensagens", "/admin/mensagens"),
    ("admin_banco_dados", "/admin/banco-dados"),
    ("admin_normas_atividade", "/admin/normas-atividade"),
    ("admin_catalogo_versoes", "/admin/catalogo-versoes"),
    ("admin_mapeamento_legado", "/admin/mapeamento-legado"),
    ("admin_adicionar_aluno", "/admin/adicionar_aluno"),
    ("admin_adicionar_turma", "/admin/adicionar_turma"),
    ("admin_adicionar_curso", "/admin/cursos/adicionar"),
    # The edit twin of the page above: same four fields, same labels. It had no
    # visual coverage at all, which is how it came to be the one form in the
    # system rendering at .form-cards width and clipping its labels from 1366px
    # down. The id is literal because tools/seed_demo_data.py inserts its three
    # cursos into a database created from scratch for every run, so curso 1
    # exists and is the same curso every time.
    ("admin_editar_curso", "/admin/cursos/1/editar"),
    ("admin_adicionar_atividade", "/admin/adicionar_atividade"),
    ("admin_adicionar_matriz", "/admin/adicionar_matriz"),
    ("admin_nova_requisicao", "/admin/requisicoes/nova"),
    ("admin_importar_requisicoes", "/admin/importar_requisicoes"),
    ("admin_turmas_importar", "/admin/turmas/importar"),
    ("admin_demo_form_pack", "/admin/demo/clientes-form-pack"),
]

ALUNO_PAGES = [
    ("aluno_dashboard", "/aluno/dashboard"),
    ("aluno_requisicoes", "/aluno/requisicoes"),
    ("aluno_arquivos", "/aluno/arquivos"),
    ("aluno_reportar", "/aluno/reportar"),
    ("aluno_progresso", "/aluno/progresso"),
    ("aluno_meus_dados", "/aluno/meus_dados"),
    ("aluno_nova_requisicao", "/aluno/nova-requisicao"),
]

# List pages whose primary button (#filter-apply, class="btn primary") lives
# INSIDE the filter popover and is invisible until it is opened. Without these
# shots a change to .btn.primary would go unseen on every one of these pages —
# which is precisely the selector the button-contract work targets.
FILTER_POPOVER_PAGES = [
    ("alunos", "/admin/alunos"),
    ("requisicoes", "/admin/requisicoes"),
    ("atividades", "/admin/atividades"),
    ("turmas", "/admin/turmas"),
    ("cursos", "/admin/cursos"),
    ("arquivos", "/admin/arquivos"),
    ("reportes", "/admin/reportes"),
    ("alertas", "/admin/alertas"),
]

# Every .modal-overlay in the codebase. The modal core is duplicated across
# these templates with no owner; these shots are what makes extracting it into
# components/modal.css verifiable rather than hopeful.
MODAL_SHOTS = [
    ("acesso_edit",        "/admin/acesso",            "access-modal",               "admin"),
    ("acesso_password",    "/admin/acesso",            "access-password-modal",      "admin"),
    ("alerta",             "/admin/alertas",           "admin-alerta-modal",         "admin"),
    ("arquivo",            "/admin/arquivos",          "admin-arquivo-modal",        "admin"),
    ("atividades_grupos",  "/admin/atividades",        "grupos-modal",               "admin"),
    ("atividades_import",  "/admin/atividades",        "importar-atividades-modal",  "admin"),
    # admin_matriz_form.html's two modals are omitted on purpose: they are
    # rendered only when the server passes new_activity_modal /
    # card_version_menu_data, so they cannot be revealed deterministically from
    # the client. They also define none of the shared modal core — they carry
    # their own classes — so they are outside what DS-4 migrates.
    # admin_acesso.html is omitted for the same reason: it uses a separate
    # .access-modal-* namespace, not the shared core.
    ("reporte",            "/admin/reportes",          "reporte-modal",              "admin"),
    ("requisicao",         "/admin/requisicoes",       "req-modal",                  "admin"),
    ("requisicao_presets", "/admin/requisicoes",       "req-presets-modal",          "admin"),
    ("turmas_import",      "/admin/turmas",            "importar-turmas-modal",      "admin"),
    ("aluno_reporte",      "/aluno/reportar",          "meu-reporte-modal",          "aluno"),
]

SHOTS: list[Shot] = (
    [
        Shot(
            name=f"modal_{name}",
            path=path,
            after=open_modal(modal_id),
            full_page=False,
            role=role,
        )
        for name, path, modal_id, role in MODAL_SHOTS
    ]
    +
    [Shot(name=f"page_{name}", path=path) for name, path in ADMIN_PAGES]
    + [Shot(name=f"page_{name}", path=path, role="aluno") for name, path in ALUNO_PAGES]
    + [
        Shot(
            name=f"state_filter_{name}",
            path=path,
            after=open_filter_popover,
            full_page=False,
        )
        for name, path in FILTER_POPOVER_PAGES
    ]
    + [
        # Public / unauthenticated
        Shot(name="page_login", path="/login", role="public"),
        # UI states — the parts a static cascade analyser can never verify
        Shot(
            name="state_sort_popover",
            path="/admin/alunos",
            after=open_sort_popover,
            full_page=False,
        ),
        # --- popover viewport clamp (F-6A2) --------------------------------
        # The eight state_filter_* shots above all render at 1440, where a
        # 520px popover anchored to its button still fits. Below that it did
        # not: measured +87 past the viewport's right edge at 900 and +219 at
        # 768 on /admin/atividades, taking #filter-apply — which sits at the
        # popover's bottom-right — off screen with it. Nothing pinned that
        # band. These three shots are the clamp's contract: where it binds the
        # popover sits exactly 12px inside the right edge, and where it does
        # not bind the popover stays on its button.
        #
        # /admin/atividades has the widest toolbar in the system, so its
        # Filtrar button sits furthest right and clamps hardest.
        Shot(name="popover_filter_atividades_900", path="/admin/atividades",
             after=open_filter_popover, viewport=(900, 900), full_page=False),
        Shot(name="popover_filter_atividades_768", path="/admin/atividades",
             after=open_filter_popover, viewport=(768, 900), full_page=False),
        # Sort shares openPopover with filter but is a different button in a
        # different toolbar position, so it clamps by a different amount.
        Shot(name="popover_sort_alunos_768", path="/admin/alunos",
             after=open_sort_popover, viewport=(768, 900), full_page=False),
        # --- dashboard track-relative responsiveness (F-6B) -----------------
        # page_admin_dashboard and page_aluno_dashboard render at 1440, where
        # four KPI columns still fit, so nothing pinned the band where they did
        # not. .kpi-grid needs 792px of track for four columns but used to drop
        # to two at a 920px VIEWPORT — a 586px track — leaving it overflowing
        # its own box from 1120 down to 920 and correct again below. Broken
        # wide, correct narrow.
        #
        # 1094 is squarely inside that band. 920 is the old breakpoint, and the
        # most telling frame in the system: the KPI grid had already snapped to
        # a correct 2x2 while .dashboard-turma-row-kpis, governed by a SECOND
        # wrong threshold of 900, was still four wide and cut off mid-sentence.
        Shot(name="dashboard_admin_1094", path="/admin/dashboard", viewport=(1094, 900)),
        Shot(name="dashboard_admin_920", path="/admin/dashboard", viewport=(920, 900)),
        # The aluno dashboard shares .kpi-grid and had the identical defect,
        # without any of the turma grids.
        Shot(name="dashboard_aluno_1024", path="/aluno/dashboard", viewport=(1024, 900),
             role="aluno"),
        # --- Resumo row wrap (F-6B2) ---------------------------------------
        # A separate defect from the .kpi-grid one above, at the other end of
        # the range. The "Resumo" row is five .item children in a nowrap flex
        # box whose min-content is their sum, 432.56px, so below a 466.56px
        # track the fifth statistic was cut off by the card edge — 33px at this
        # width. Nothing pinned it: dashboard_aluno_1024 is far too wide to see
        # it, and the 768 case is where the supported floor actually sits.
        Shot(name="dashboard_aluno_768", path="/aluno/dashboard", viewport=(768, 900),
             role="aluno"),
        Shot(
            name="state_focus_visible",
            path="/admin/alunos",
            after=focus_first_control,
            full_page=False,
        ),
        # --- popover viewport containment, vertical axis (F-7) --------------
        # The first shots in this catalogue where viewport HEIGHT is the load-
        # bearing dimension, which is why they carry it in their names.
        #
        # /admin/acesso is the only consumer that renders a long preamble above
        # its toolbar — five profile cards plus the default-password panel — so
        # it is the only page where an opened popover ran past the bottom edge.
        # Measured before F-7 at 1366x768: the filter popover overran by 105px,
        # taking #filter-apply and #filter-clear-all off screen, and the actions
        # menu by 179px, taking Excluir, Redefinir and Nova senha with it. The
        # earlier deferral assumed .app-main could be scrolled to reach them; it
        # cannot, because the popover is positioned in viewport coordinates and
        # does not move when .app-main scrolls.
        Shot(name="popover_filter_acesso_1366x768", path="/admin/acesso",
             after=open_filter_popover, viewport=(1366, 768), full_page=False),
        Shot(name="popover_actions_acesso_1366x768", path="/admin/acesso",
             after=open_actions_menu, viewport=(1366, 768), full_page=False),
        # The actions menu had NO baseline at any width. It is the consumer whose
        # width was measured while it was still display:none, so the clamp always
        # saw the 190px fallback instead of the real 212-395px and the menu came
        # to rest flush against the viewport's right edge. This pins the restored
        # 12px margin at the harness's own viewport.
        Shot(name="popover_actions_alunos_1440", path="/admin/alunos",
             after=open_actions_menu, full_page=False),
        # The sort control pair's focus ring (F-7). state_focus_visible above
        # lands on the first focusable control on the page, which is not one of
        # these two.
        Shot(name="state_sort_focus_visible", path="/admin/alunos",
             after=focus_sort_field, full_page=False),
        # --- form states (DS-6) -------------------------------------------
        Shot(name="form_focus_within", path="/admin/adicionar_aluno",
             after=focus_form_control, full_page=False),
        Shot(name="form_hover", path="/admin/adicionar_aluno",
             after=hover_form_control, full_page=False),
        Shot(name="form_disabled", path="/admin/adicionar_aluno",
             after=disable_form_controls, full_page=False),
        # The two validation mechanisms are pinned separately: :user-invalid
        # and [aria-invalid] are different selectors and can regress apart.
        Shot(name="form_invalid_user", path="/admin/adicionar_aluno",
             after=invalidate_natively, full_page=False),
        Shot(name="form_invalid_aria", path="/admin/adicionar_aluno",
             after=invalidate_via_aria, full_page=False),
        Shot(name="form_readonly", path="/admin/adicionar_aluno",
             after=make_readonly, full_page=False),
        # Two different label patterns with two different responsive stories.
        # .row-label (107 uses) is absolutely positioned and has NO responsive
        # rule anywhere; these pin its behaviour as-is.
        Shot(name="form_responsive_960", path="/admin/adicionar_aluno", viewport=(960, 900)),
        Shot(name="form_responsive_640", path="/admin/adicionar_aluno", viewport=(640, 900)),
        # 720 is the exact width at which the stacked-label contract activates
        # and the narrow containment contract takes over, and nothing pinned
        # it: form_responsive_640/960 sit either side of it. F-5E found both
        # families overflowing their track hardest right here (+90 standard,
        # +228 wide) with no shot to catch it. The wide family had no
        # responsive coverage at any width at all.
        Shot(name="form_responsive_720", path="/admin/adicionar_aluno", viewport=(720, 900)),
        Shot(name="form_responsive_wide_720", path="/admin/adicionar_atividade",
             viewport=(720, 900)),
        # .field-label (2 templates) does reflow from absolute to block under
        # @media (max-width:1000px); this is the only page that exercises it.
        Shot(name="form_field_label_reflow", path="/admin/demo/clientes-form-pack",
             viewport=(960, 900)),
        # The file control is the most structurally complex field variant.
        Shot(name="form_file_control", path="/aluno/nova-requisicao", role="aluno"),
        # Toggle switches need no dedicated shot: they are visible on load and
        # already covered by page_admin_configuracoes, page_admin_banco_dados,
        # page_admin_alertas and modal_arquivo.
        Shot(
            name="state_toolbar_search_focus",
            path="/admin/alunos",
            after=focus_toolbar_search,
            full_page=False,
        ),
        # --- toolbar wrap (F-6A1) -----------------------------------------
        # Every list page's toolbar was a nowrap flex row whose min-content
        # width is the sum of its controls, so it ran off the content column
        # on ordinary laptops with nothing pinning it: the whole catalogue
        # renders at 1440, where every toolbar still fits. These four widths
        # are the bands the 19-consumer matrix identified.
        #
        # /admin/atividades is the most demanding toolbar in the system
        # (1042.5px minimum, seven controls). 1366 is where it first runs past
        # .app-track; 1280 is where it is genuinely cut off, and is an ordinary
        # laptop resolution.
        Shot(name="toolbar_atividades_1366", path="/admin/atividades", viewport=(1366, 900)),
        Shot(name="toolbar_atividades_1280", path="/admin/atividades", viewport=(1280, 900)),
        # The 823.4px family — alunos, cursos, arquivos, matrizes, alertas,
        # detalhes-turma all measure identically. One representative pins them.
        Shot(name="toolbar_alunos_1120", path="/admin/alunos", viewport=(1120, 900)),
        # /admin/acesso renders its toolbar 364px BELOW THE FOLD at this width,
        # behind five profile cards and the default-password panel. full_page
        # cannot reach it — the document is pinned to 100vh and .app-main is
        # what scrolls — so the shot scrolls .app-main first. See
        # scroll_toolbar_into_view. It is also the only consumer with an extra
        # nesting level inside .actions (.access-toolbar-actions).
        Shot(name="toolbar_acesso_768", path="/admin/acesso", viewport=(768, 900),
             after=scroll_toolbar_into_view, full_page=False),
        Shot(
            name="state_toast_success",
            path="/admin/alunos",
            after=show_toast,
            full_page=False,
        ),
        # Error pages: standalone templates with their own <head>
        Shot(name="page_404", path="/admin/nao-existe-esta-rota"),
    ]
)
