"""Documentação exigida -- the required proofs of an activity version.

The list lives in ``atividade_versao.documentos_json`` as
``{"comprovantes_exigidos": [...]}`` and is edited on the canonical version
form. It follows the version freeze policy: a draft is edited in place, a
frozen version changes only through a new version. The regulation sentence
every version held before is not a proof name: it is never listed, never
rewritten while the list is unchanged, and kept under ``texto_anterior``.
"""
from __future__ import annotations

import json

import pytest

import main
from app.activity_catalog import apply_activity_version_semantic_changes
from app.activity_documentation import (
    LIST_KEY,
    PREVIOUS_KEY,
    REQUIRED_DOCUMENT_MAX_ITEMS,
    REQUIRED_DOCUMENT_MAX_LENGTH,
    RequiredDocumentsInvalid,
    documentos_json_for_write,
    normalize_required_documents,
    parse_required_documents_form,
    read_required_documents,
)
from app.db import write_transaction
from tests.canonical_matrix_test_support import login_admin
from tests.versioned_test_support import isolated_versioned_app_env

# What every version held before the list existed: one regulation sentence in a
# JSON array (synthetic text).
LEGACY_SENTENCE = (
    "A validação será feita mediante certificado emitido pela instituição"
    " promotora, contendo a data de realização e a carga horária total do evento."
)
LEGACY_TEXT = json.dumps([LEGACY_SENTENCE], ensure_ascii=False)
ITEMS = ["Certificado de participação", "Declaração do responsável"]
LIST_TEXT = json.dumps({LIST_KEY: ITEMS}, ensure_ascii=False)


# ------------------------------------------------------------------ owner


def test_normalize_trims_drops_blanks_and_keeps_the_first_of_a_repeat():
    assert normalize_required_documents(
        ["  Certificado   de participação ", "", "   ", "Declaração", "Certificado de participação"]
    ) == ["Certificado de participação", "Declaração"]


def test_parse_refuses_an_item_that_is_too_long_or_too_many_items():
    with pytest.raises(RequiredDocumentsInvalid):
        parse_required_documents_form(["x" * (REQUIRED_DOCUMENT_MAX_LENGTH + 1)])
    with pytest.raises(RequiredDocumentsInvalid):
        parse_required_documents_form([f"Documento {n}" for n in range(REQUIRED_DOCUMENT_MAX_ITEMS + 1)])
    assert parse_required_documents_form(["x" * REQUIRED_DOCUMENT_MAX_LENGTH]) == ["x" * REQUIRED_DOCUMENT_MAX_LENGTH]


def test_only_the_list_is_read_as_proofs_never_the_older_text():
    assert read_required_documents(LIST_TEXT) == ITEMS
    for raw in (LEGACY_TEXT, None, "[]", '"NA"', '["Certificado"]', "não é JSON", '{"outro": ["x"]}'):
        assert read_required_documents(raw) == []


def test_the_older_text_is_kept_as_it_is_and_under_texto_anterior():
    # Nobody listed proofs: the row keeps its text exactly.
    assert documentos_json_for_write(LEGACY_TEXT, []) == LEGACY_TEXT
    assert documentos_json_for_write(LIST_TEXT, list(ITEMS)) == LIST_TEXT
    assert documentos_json_for_write(None, []) == "[]"
    # The first list keeps the older text beside it.
    changed = documentos_json_for_write(LEGACY_TEXT, ITEMS)
    assert json.loads(changed) == {LIST_KEY: ITEMS, PREVIOUS_KEY: [LEGACY_SENTENCE]}
    assert "ç" in changed  # stored as text, not as \\u escapes
    # Later changes carry it on, and emptying the list loses nothing.
    reordered = documentos_json_for_write(changed, list(reversed(ITEMS)))
    assert json.loads(reordered) == {LIST_KEY: list(reversed(ITEMS)), PREVIOUS_KEY: [LEGACY_SENTENCE]}
    assert json.loads(documentos_json_for_write(reordered, [])) == {LIST_KEY: [], PREVIOUS_KEY: [LEGACY_SENTENCE]}
    assert json.loads(documentos_json_for_write(None, ITEMS)) == {LIST_KEY: ITEMS}


# ----------------------------------------------------------------- routes


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "required-documents.db") as environment:
        login_admin(environment["client"])
        yield environment


def _seed_base(*, status: str, documentos_json):
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, ?, 'ativo') RETURNING id",
            ("Palestra com documentação", "Base de teste"),
        ).fetchone()[0]
        version_id = conn.execute(
            """INSERT INTO atividade_versao (atividade_base_id, eixo, grupo, ch_por_evento,
                   observacao_aluno, observacao_admin, documentos_json, numero_versao, status)
               VALUES (?, 'AAC', '1 - Eventos', 2, NULL, NULL, ?, 1, ?) RETURNING id""",
            (base_id, documentos_json, status),
        ).fetchone()[0]
        conn.commit()
    return base_id, version_id


def _version(version_id):
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM atividade_versao WHERE id = ?", (version_id,)
        ).fetchone()
        return dict(row) if row else None


def _versions_of(base_id):
    with main.app.app_context():
        return [
            dict(row)
            for row in main.get_db_connection().execute(
                "SELECT * FROM atividade_versao WHERE atividade_base_id = ? ORDER BY numero_versao", (base_id,)
            )
        ]


def _form(**overrides):
    data = {
        "tipo_atividade": "Acadêmica Complementar",
        "grupo": "1 - Eventos",
        "nome": "Palestra com documentação",
        "descricao": "Base de teste",
        "tipo_limitacao": "",
        "limite_valor": "",
        "ch_por_evento_mode": "enabled",
        "ch_por_evento": "2",
        "observacoes": "",
        # The section's presence marker, as the real form sends it.
        "documentos_exigidos_presente": "1",
    }
    data.update(overrides)
    return data


def _rendered_items(html: str) -> list[str]:
    import re

    section = html.split('id="documentos-exigidos-list"', 1)[1].split("</ol>", 1)[0]
    return re.findall(r'name="documentos_exigidos" value="([^"]*)"', section)


def test_new_version_form_lists_the_source_proofs_in_order(env):
    base_id, version_id = _seed_base(status="ativa", documentos_json=LIST_TEXT)
    response = env["client"].get(f"/admin/catalogo-versoes/{base_id}/nova-versao?from={version_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Documentação exigida" in html
    assert _rendered_items(html) == ITEMS


def test_the_older_text_is_not_offered_as_a_proof(env):
    base_id, version_id = _seed_base(status="ativa", documentos_json=LEGACY_TEXT)
    html = env["client"].get(f"/admin/catalogo-versoes/{base_id}/nova-versao?from={version_id}").get_data(as_text=True)
    assert _rendered_items(html) == []
    assert LEGACY_SENTENCE not in html


def test_the_name_inputs_take_at_most_the_stored_limit():
    from pathlib import Path

    template = (Path(__file__).resolve().parents[1] / "templates" / "admin_catalogo_versao_form.html").read_text(
        encoding="utf-8"
    )
    inputs = [line for line in template.splitlines() if "<input" in line and 'name="documentos_exigidos"' in line]
    assert len(inputs) == 2
    assert all(f'maxlength="{REQUIRED_DOCUMENT_MAX_LENGTH}"' in line for line in inputs)


def test_a_guidance_change_alone_creates_a_draft_and_leaves_the_frozen_version_untouched(env):
    base_id, version_id = _seed_base(status="ativa", documentos_json=LIST_TEXT)
    response = env["client"].post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao?from={version_id}",
        data={
            **_form(versao_anterior_id=str(version_id)),
            "documentos_exigidos": ["Declaração do responsável", "Certificado de participação", "Lista de presença"],
        },
    )
    assert response.status_code == 302
    original, successor = _versions_of(base_id)
    assert original["documentos_json"] == LIST_TEXT and original["status"] == "ativa"
    assert successor["status"] == "rascunho" and successor["versao_anterior_id"] == version_id
    assert json.loads(successor["documentos_json"]) == {
        LIST_KEY: ["Declaração do responsável", "Certificado de participação", "Lista de presença"],
    }


def test_the_first_list_of_an_older_version_keeps_its_text(env):
    base_id, version_id = _seed_base(status="ativa", documentos_json=LEGACY_TEXT)
    response = env["client"].post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao?from={version_id}",
        data={**_form(versao_anterior_id=str(version_id)), "documentos_exigidos": ITEMS},
    )
    assert response.status_code == 302
    original, successor = _versions_of(base_id)
    assert original["documentos_json"] == LEGACY_TEXT
    assert json.loads(successor["documentos_json"]) == {LIST_KEY: ITEMS, PREVIOUS_KEY: [LEGACY_SENTENCE]}


@pytest.mark.parametrize(("stored", "submitted"), [(LIST_TEXT, ITEMS), (LEGACY_TEXT, [])])
def test_a_new_version_that_keeps_the_list_copies_the_stored_text_exactly(env, stored, submitted):
    """An older version whose text is longer than a proof name still gets a new version."""
    base_id, version_id = _seed_base(status="ativa", documentos_json=stored)
    response = env["client"].post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao?from={version_id}",
        data={**_form(versao_anterior_id=str(version_id), ch_por_evento="3"), "documentos_exigidos": submitted},
    )
    assert response.status_code == 302
    successor = _versions_of(base_id)[1]
    assert successor["ch_por_evento"] == 3
    assert successor["documentos_json"] == stored


def test_an_unchanged_form_is_still_no_effective_change(env):
    base_id, version_id = _seed_base(status="ativa", documentos_json=LIST_TEXT)
    response = env["client"].post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao?from={version_id}",
        data={
            **_form(versao_anterior_id=str(version_id)),
            "documentos_exigidos": ["Certificado de participação", " Declaração  do responsável "],
        },
    )
    assert response.status_code == 200
    assert "Nenhuma alteração efetiva informada" in response.get_data(as_text=True)
    assert len(_versions_of(base_id)) == 1


def test_a_draft_edit_reorders_removes_and_adds_items_and_a_reload_shows_them(env):
    base_id, version_id = _seed_base(status="rascunho", documentos_json=LIST_TEXT)
    url = f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar"
    response = env["client"].post(
        url,
        data={**_form(), "documentos_exigidos": ["Declaração do responsável", "", "Folha de frequência"]},
    )
    assert response.status_code == 302
    stored = _version(version_id)
    assert json.loads(stored["documentos_json"]) == {LIST_KEY: ["Declaração do responsável", "Folha de frequência"]}
    assert _rendered_items(env["client"].get(url).get_data(as_text=True)) == [
        "Declaração do responsável", "Folha de frequência",
    ]
    response = env["client"].post(url, data={**_form(), "documentos_exigidos": []})
    assert response.status_code == 302
    assert json.loads(_version(version_id)["documentos_json"]) == {LIST_KEY: []}


def test_a_frozen_version_refuses_a_guidance_edit_and_renders_it_read_only(env):
    base_id, version_id = _seed_base(status="ativa", documentos_json=LIST_TEXT)
    url = f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar"
    page = env["client"].get(url).get_data(as_text=True)
    assert _rendered_items(page) == ITEMS
    assert "<button type=\"button\" class=\"btn doc-list-add\" data-doc-add>" not in page
    assert "data-doc-remove aria-label" not in page
    assert 'name="documentos_exigidos"' in page.split('<fieldset class="form-fieldset" disabled', 1)[1]
    response = env["client"].post(url, data={**_form(), "documentos_exigidos": ["Outro documento"]})
    assert response.status_code == 302
    assert _version(version_id)["documentos_json"] == LIST_TEXT
    assert len(_versions_of(base_id)) == 1


def test_an_item_that_is_too_long_is_refused_and_the_form_keeps_what_was_typed(env):
    base_id, version_id = _seed_base(status="rascunho", documentos_json="[]")
    url = f"/admin/catalogo-versoes/{base_id}/versoes/{version_id}/editar"
    too_long = "y" * (REQUIRED_DOCUMENT_MAX_LENGTH + 1)
    response = env["client"].post(url, data={**_form(), "documentos_exigidos": ["Certificado", too_long]})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f"Use até {REQUIRED_DOCUMENT_MAX_LENGTH} caracteres por comprovante." in html
    assert _rendered_items(html) == ["Certificado", too_long]
    assert _version(version_id)["documentos_json"] == "[]"


def test_a_form_without_the_section_keeps_the_stored_guidance(env):
    """An omitted field keeps the stored value: a POST that never showed the
    list (an older page, another client) neither clears nor rewrites it."""
    base_id, version_id = _seed_base(status="ativa", documentos_json=LIST_TEXT)
    legacy_form = _form(versao_anterior_id=str(version_id))
    del legacy_form["documentos_exigidos_presente"]
    response = env["client"].post(f"/admin/catalogo-versoes/{base_id}/nova-versao?from={version_id}", data=legacy_form)
    assert response.status_code == 200
    assert "Nenhuma alteração efetiva informada" in response.get_data(as_text=True)
    response = env["client"].post(
        f"/admin/catalogo-versoes/{base_id}/nova-versao?from={version_id}", data={**legacy_form, "ch_por_evento": "3"}
    )
    assert response.status_code == 302
    assert _versions_of(base_id)[1]["documentos_json"] == LIST_TEXT

    draft_base, draft_id = _seed_base_named("Rascunho com documentação", documentos_json=LIST_TEXT)
    url = f"/admin/catalogo-versoes/{draft_base}/versoes/{draft_id}/editar"
    draft_form = _form(nome="Rascunho com documentação", ch_por_evento="5")
    del draft_form["documentos_exigidos_presente"]
    assert env["client"].post(url, data=draft_form).status_code == 302
    assert _version(draft_id)["documentos_json"] == LIST_TEXT
    # With the marker and no item, the list is emptied on purpose.
    assert env["client"].post(url, data=_form(nome="Rascunho com documentação", ch_por_evento="5")).status_code == 302
    assert json.loads(_version(draft_id)["documentos_json"]) == {LIST_KEY: []}


def _seed_base_named(name, *, documentos_json):
    with main.app.app_context():
        conn = main.get_db_connection()
        base_id = conn.execute(
            "INSERT INTO atividade_base (nome_conceito, descricao, status) VALUES (?, 'Base de teste', 'ativo') RETURNING id",
            (name,),
        ).fetchone()[0]
        version_id = conn.execute(
            """INSERT INTO atividade_versao (atividade_base_id, eixo, grupo, ch_por_evento, documentos_json,
                   numero_versao, status) VALUES (?, 'AAC', '1 - Eventos', 2, ?, 1, 'rascunho') RETURNING id""",
            (base_id, documentos_json),
        ).fetchone()[0]
        conn.commit()
    return base_id, version_id


@pytest.mark.parametrize("stored", [LIST_TEXT, LEGACY_TEXT])
def test_a_successor_made_by_the_semantic_policy_keeps_the_stored_text(env, stored):
    base_id, version_id = _seed_base(status="ativa", documentos_json=stored)
    with main.app.app_context():
        conn = main.get_db_connection()
        with write_transaction(conn):
            result = apply_activity_version_semantic_changes(conn, version_id, {"ch_por_evento": 5.0})
    assert result["mode"] == "successor"
    assert _version(result["version_id"])["documentos_json"] == stored
