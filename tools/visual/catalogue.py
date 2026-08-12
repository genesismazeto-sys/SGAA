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

    def render(self, page, base_url: str) -> None:
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

SHOTS: list[Shot] = (
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
        Shot(
            name="state_focus_visible",
            path="/admin/alunos",
            after=focus_first_control,
            full_page=False,
        ),
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
