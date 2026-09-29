"""A student's matrícula is an identity value, never a roster row number.

Every roster save used to finish with ``resequence_turma_aluno_matriculas_for_ids``,
which rewrote each matrícula of the Turma to ``<código>.NNN`` in name order. The
admin had just typed (or left untouched) the value in the form, so a plain
"Salvar" of Editar Turma replaced institutional matrículas such as ``001234``
with generated ones, and so did adding, deleting or re-saving any single
student of that Turma. These tests pin the opposite contract: nothing but an
explicit, different value submitted for that student changes their matrícula.
"""
from __future__ import annotations

import ast
import io
import re
from html.parser import HTMLParser
from pathlib import Path

from werkzeug.datastructures import MultiDict

import main
from app.user_accounts import create_usuario_pending
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TURMA_ID = 1  # seeded PPA-T10
OTHER_TURMA_ID = 2  # seeded PPA-T11
# Name order differs from insertion order, and no value looks like "PPA-T10.NNN",
# so any renumbering is visible in every row.
ROSTER = (
    ("Zeca Institucional", "zeca@ex.com", "2019.1.0457-X"),
    ("Ana Zero", "ana@ex.com", "001234"),
    ("Bruno Ace", "bruno@ex.com", "ACE-0002"),
    ("Carla Barra", "carla@ex.com", "EJ/ADM/2024/0099"),
)
OUTSIDER = ("Otto Fora", "otto@ex.com", "OUT-0001")
ROW_FIELDS = (
    "aluno_importado[]",
    "aluno_nome[]",
    "aluno_email[]",
    "aluno_matricula[]",
    "aluno_situacao[]",
)


def _seed_student(conn, nome, email, matricula, turma_id):
    usuario_id = create_usuario_pending(conn, nome, email, "aluno").lastrowid
    conn.execute(
        "INSERT INTO alunos (usuario_id,nome,email,matricula,turma_id,status)"
        " VALUES (?,?,?,?,?,'Ativo')",
        (usuario_id, nome, email, matricula, turma_id),
    )
    return usuario_id


def _seed_roster():
    with main.app.app_context():
        conn = main.get_db_connection()
        for nome, email, matricula in ROSTER:
            _seed_student(conn, nome, email, matricula, TURMA_ID)
        _seed_student(conn, *OUTSIDER, OTHER_TURMA_ID)
        conn.commit()


def _identities():
    with main.app.app_context():
        rows = main.get_db_connection().execute(
            "SELECT email, matricula, turma_id FROM alunos ORDER BY email"
        ).fetchall()
    return {row["email"]: (row["matricula"], row["turma_id"]) for row in rows}


def _credential_state():
    with main.app.app_context():
        conn = main.get_db_connection()
        return (
            [tuple(r) for r in conn.execute("SELECT id,email,senha FROM usuarios ORDER BY id")],
            [tuple(r) for r in conn.execute("SELECT * FROM usuario_credenciais ORDER BY 1")],
            [tuple(r) for r in conn.execute("SELECT * FROM senha_tokens ORDER BY 1")],
        )


def _usuario_id(email):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT id FROM usuarios WHERE email=?", (email,)
        ).fetchone()["id"]


def _turma(turma_id=TURMA_ID):
    with main.app.app_context():
        return dict(
            main.get_db_connection()
            .execute("SELECT * FROM turmas WHERE id=?", (turma_id,))
            .fetchone()
        )


class _FormFields(HTMLParser):
    """What a browser submits for the page's POST form (JS-free fields)."""

    def __init__(self):
        super().__init__()
        self.pairs: list[tuple[str, str]] = []
        self._in_form = False
        self._select: dict | None = None
        self._option: dict | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and (attrs.get("method") or "").upper() == "POST":
            self._in_form = True
        if not self._in_form:
            return
        if tag == "input" and attrs.get("name"):
            if (attrs.get("type") or "text") not in {"file", "submit", "button"}:
                self.pairs.append((attrs["name"], attrs.get("value") or ""))
        elif tag == "select" and attrs.get("name"):
            self._select = {"name": attrs["name"], "options": []}
        elif tag == "option" and self._select is not None:
            self._option = {"value": attrs.get("value"), "text": "", "selected": "selected" in attrs}
            self._select["options"].append(self._option)

    def handle_data(self, data):
        if self._option is not None:
            self._option["text"] += data

    def handle_endtag(self, tag):
        if tag == "option":
            self._option = None
        elif tag == "select" and self._select is not None:
            options = self._select["options"]
            chosen = next((o for o in options if o["selected"]), options[0] if options else None)
            if chosen is not None:
                value = chosen["value"] if chosen["value"] is not None else chosen["text"].strip()
                self.pairs.append((self._select["name"], value))
            self._select = None
        elif tag == "form":
            self._in_form = False


def _browser_payload(client, turma_id=TURMA_ID):
    """GET Editar Turma and return exactly what "Salvar" would post, untouched."""
    response = client.get(f"/admin/editar_turma/{turma_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    parser = _FormFields()
    parser.feed(html)
    # The matriz select is filled by the page script with the Turma's default.
    default_matriz = re.search(r"const defaultMatrizId = '(\d*)'", html).group(1)
    turma_fields = [(k, v) for k, v in parser.pairs if k not in ROW_FIELDS]
    turma_fields.append(("matriz_id", default_matriz))
    columns = {name: [v for k, v in parser.pairs if k == name] for name in ROW_FIELDS}
    rows = [dict(zip(ROW_FIELDS, values)) for values in zip(*columns.values())]
    return turma_fields, rows


def _post(client, turma_fields, rows, turma_id=TURMA_ID):
    items = list(turma_fields)
    for row in rows:
        items.extend((name, row[name]) for name in ROW_FIELDS)
    return client.post(f"/admin/editar_turma/{turma_id}", data=MultiDict(items))


def _with(turma_fields, **changes):
    return [(k, changes.get(k, v)) for k, v in turma_fields]


def test_unchanged_resubmission_preserves_every_matricula_byte_for_byte(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-noop.db") as env:
        _seed_roster()
        login_admin(env["client"])
        before, creds = _identities(), _credential_state()

        fields, rows = _browser_payload(env["client"])
        assert sorted(r["aluno_matricula[]"] for r in rows) == sorted(m for *_, m in ROSTER)
        response = _post(env["client"], fields, rows)

        assert response.status_code == 302
        assert _identities() == before
        assert _credential_state() == creds


def test_metadata_only_change_preserves_matriculas(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-meta.db") as env:
        _seed_roster()
        login_admin(env["client"])
        before = _identities()

        fields, rows = _browser_payload(env["client"])
        # A new number also changes the Turma code the old resequence derived from.
        response = _post(env["client"], _with(fields, turno="Noite", numero_turma="12"), rows)

        assert response.status_code == 302
        turma = _turma()
        assert (turma["turno"], turma["codigo"]) == ("Noite", "PPA-T12")
        assert _identities() == before


def test_removing_a_row_leaves_remaining_matriculas_untouched(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-remove.db") as env:
        _seed_roster()
        login_admin(env["client"])
        before = _identities()

        fields, rows = _browser_payload(env["client"])
        kept = [r for r in rows if r["aluno_email[]"] != "ana@ex.com"]
        assert _post(env["client"], fields, kept).status_code == 302

        expected = dict(before)
        expected["ana@ex.com"] = ("001234", None)  # unlinked, identity kept
        assert _identities() == expected


def test_adding_a_row_keeps_existing_matriculas_and_the_typed_new_one(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-add.db") as env:
        _seed_roster()
        login_admin(env["client"])
        before, creds = _identities(), _credential_state()

        fields, rows = _browser_payload(env["client"])
        rows.append(
            {
                "aluno_importado[]": "0",
                "aluno_nome[]": "Aaron Novo",
                "aluno_email[]": "aaron@ex.com",
                "aluno_matricula[]": "NEW-0777",
                "aluno_situacao[]": "ATIVO",
            }
        )
        assert _post(env["client"], fields, rows).status_code == 302

        after = _identities()
        assert after.pop("aaron@ex.com") == ("NEW-0777", TURMA_ID)
        assert after == before
        users, credentials, tokens = _credential_state()
        assert [u for u in users if u[1] != "aaron@ex.com"] == creds[0]
        assert tokens == creds[2]


def test_reordered_rows_keep_matricula_attached_to_the_same_student(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-reorder.db") as env:
        _seed_roster()
        login_admin(env["client"])
        before = _identities()

        fields, rows = _browser_payload(env["client"])
        assert _post(env["client"], fields, list(reversed(rows))).status_code == 302

        assert _identities() == before


def test_imported_roster_survives_an_ordinary_save(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-import.db") as env:
        login_admin(env["client"])
        seeded = _identities()
        csv_body = "Imported One,imp1@ex.com,IMP-0042\nImported Two,imp2@ex.com,000777\n"
        imported = env["client"].post(
            "/admin/turmas/importar",
            data={
                "turma_id": str(OTHER_TURMA_ID),
                "csv_arquivo": (io.BytesIO(csv_body.encode("utf-8")), "alunos.csv"),
            },
        )
        assert imported.status_code == 302
        assert _identities() == {
            **seeded,
            "imp1@ex.com": ("IMP-0042", OTHER_TURMA_ID),
            "imp2@ex.com": ("000777", OTHER_TURMA_ID),
        }

        # An e-mail correction by re-import keys on the matrícula and keeps it.
        reimport = "Imported One,imp1.new@ex.com,IMP-0042\n"
        env["client"].post(
            "/admin/turmas/importar",
            data={
                "turma_id": str(OTHER_TURMA_ID),
                "csv_arquivo": (io.BytesIO(reimport.encode("utf-8")), "alunos.csv"),
            },
        )
        after_import = _identities()
        assert after_import == {
            **seeded,
            "imp1.new@ex.com": ("IMP-0042", OTHER_TURMA_ID),
            "imp2@ex.com": ("000777", OTHER_TURMA_ID),
        }

        fields, rows = _browser_payload(env["client"], OTHER_TURMA_ID)
        response = _post(env["client"], fields, rows, OTHER_TURMA_ID)

        assert response.status_code == 302
        assert _identities() == after_import


def test_intentional_matricula_edit_changes_only_that_student(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-edit.db") as env:
        _seed_roster()
        login_admin(env["client"])
        before, creds = _identities(), _credential_state()

        fields, rows = _browser_payload(env["client"])
        for row in rows:
            if row["aluno_email[]"] == "bruno@ex.com":
                row["aluno_matricula[]"] = "ACE-0003"
        assert _post(env["client"], fields, rows).status_code == 302

        expected = dict(before)
        expected["bruno@ex.com"] = ("ACE-0003", TURMA_ID)
        assert _identities() == expected
        assert _credential_state() == creds


def _assert_rejected_atomically(client, fields, rows, before, creds, turma_before):
    response = _post(client, _with(fields, turno="Noite"), rows)
    assert response.status_code == 200  # re-rendered with the error, no redirect
    assert "Erro ao atualizar turma" in response.get_data(as_text=True)
    assert _identities() == before
    assert _credential_state() == creds
    assert _turma() == turma_before  # the Turma UPDATE rolled back with it


def test_matricula_taken_inside_the_roster_is_rejected_atomically(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-dup-in.db") as env:
        _seed_roster()
        login_admin(env["client"])
        before, creds, turma_before = _identities(), _credential_state(), _turma()

        fields, rows = _browser_payload(env["client"])
        for row in rows:
            if row["aluno_email[]"] == "bruno@ex.com":
                row["aluno_matricula[]"] = "001234"  # Ana's
        _assert_rejected_atomically(env["client"], fields, rows, before, creds, turma_before)


def test_matricula_of_a_student_elsewhere_is_rejected_atomically(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-dup-out.db") as env:
        _seed_roster()
        login_admin(env["client"])
        before, creds, turma_before = _identities(), _credential_state(), _turma()

        fields, rows = _browser_payload(env["client"])
        for row in rows:
            if row["aluno_email[]"] == "bruno@ex.com":
                row["aluno_matricula[]"] = OUTSIDER[2]
        _assert_rejected_atomically(env["client"], fields, rows, before, creds, turma_before)


def test_new_turma_keeps_the_typed_matricula(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-new-turma.db") as env:
        login_admin(env["client"])
        before = _identities()
        response = env["client"].post(
            "/admin/adicionar_turma",
            data={
                "curso_id": "1",
                "numero_turma": "41",
                "ano_inicio": "2026",
                "semestre_inicio": "1",
                "turno": "Manhã",
                "status": "Ativa",
                "matriz_id": "",
                "aluno_nome[]": "Pessoa Nova",
                "aluno_email[]": "pn@ex.com",
                "aluno_matricula[]": "0000451",
                "aluno_situacao[]": "ATIVO",
                "aluno_importado[]": "0",
            },
        )
        assert response.status_code == 302
        after = _identities()
        matricula, new_turma_id = after.pop("pn@ex.com")
        assert _turma(new_turma_id)["numero"] == 41
        assert matricula == "0000451"
        assert after == before


def test_adding_a_student_to_the_turma_does_not_renumber_the_roster(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-novo-aluno.db") as env:
        _seed_roster()
        login_admin(env["client"])
        before = _identities()

        response = env["client"].post(
            "/admin/adicionar_aluno",
            data={
                "nome": "Aaron Avulso",
                "email": "avulso@ex.com",
                "senha": "",
                "matricula": "NEW-0900",
                "turma_id": str(TURMA_ID),
                "status": "Ativo",
            },
        )
        assert response.status_code == 302
        after = _identities()
        assert after.pop("avulso@ex.com") == ("NEW-0900", TURMA_ID)
        assert after == before


def test_deleting_a_student_does_not_renumber_the_rest(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-delete.db") as env:
        _seed_roster()
        login_admin(env["client"])
        before = _identities()

        response = env["client"].post(f"/admin/deletar_aluno/{_usuario_id('ana@ex.com')}")
        assert response.status_code == 302
        del before["ana@ex.com"]
        assert _identities() == before


def test_access_save_of_a_student_does_not_renumber_either_roster(tmp_path):
    with isolated_versioned_app_env(tmp_path, "mat-acesso.db") as env:
        _seed_roster()
        login_admin(env["client"])
        before = _identities()

        def save(turma_id, nome):
            return env["client"].post(
                "/admin/acesso/salvar",
                data={
                    "usuario_id": str(_usuario_id("bruno@ex.com")),
                    "nome": nome,
                    "email": "bruno@ex.com",
                    "nivel_acesso": "usuario",
                    "matricula": "ACE-0002",
                    "status": "Ativo",
                    "turma_id": str(turma_id),
                },
            )

        # A rename moves Bruno first in name order; a transfer touches two rosters.
        assert save(TURMA_ID, "Aaa Bruno").status_code == 302
        assert _identities() == before
        assert save(OTHER_TURMA_ID, "Aaa Bruno").status_code == 302
        expected = dict(before)
        expected["bruno@ex.com"] = ("ACE-0002", OTHER_TURMA_ID)
        assert _identities() == expected


def _calls_to(tree: ast.AST, names: set[str]) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if called in names:
                lines.append(node.lineno)
    return lines


def test_no_production_flow_renumbers_matriculas():
    """Governance: no request path may rewrite matrículas as roster positions.

    The helpers stay importable (``main`` re-exports them by identity), but
    calling them from any production module would bring back the defect.
    """
    names = {"resequence_turma_aluno_matriculas", "resequence_turma_aluno_matriculas_for_ids"}
    offenders = {}
    for path in [PROJECT_ROOT / "main.py", *sorted((PROJECT_ROOT / "app").rglob("*.py"))]:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        lines = _calls_to(tree, names)
        if path.name == "academics.py":
            # The helpers' own internal delegation is not a call site.
            lines = []
        if lines:
            offenders[str(path.relative_to(PROJECT_ROOT))] = lines
    assert offenders == {}
