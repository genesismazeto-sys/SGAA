"""ACTIVITY-VERSION-FULL-FORM-UX-R4 focused contract coverage."""
from __future__ import annotations

import json
import re
import uuid

import pytest

import main
from tests.versioned_test_support import isolated_versioned_app_env


@pytest.fixture()
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "activity_version_r4.db") as env:
        yield env


@pytest.fixture()
def client(env):
    return env["client"]


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def _seed(client, *, eixo="AAC", status="rascunho"):
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        nome = f"Atividade R4 {token}"
        base_id = conn.execute(
            "INSERT INTO atividade_base(nome_conceito,descricao,status) VALUES(?,?,'ativo') RETURNING id",
            (nome, "Descrição R4"),
        ).fetchone()[0]
        versao_id = conn.execute(
            """
            INSERT INTO atividade_versao(
                atividade_base_id,eixo,grupo,ch_por_evento,limite_semestre,
                observacao_aluno,observacao_admin,documentos_json,
                vigencia_inicio,vigencia_fim,numero_versao,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,1,?) RETURNING id
            """,
            (
                base_id, eixo, "1 - Grupo R4", 4.0, 40.0,
                "Legado aluno R4", "Observações R4", '["doc-r4"]',
                "2026-01-01", "2026-12-31", status,
            ),
        ).fetchone()[0]
        conn.commit()
    return {"base_id": base_id, "versao_id": versao_id, "nome": nome, "eixo": eixo}


def _get(client, seed, *, edit=False, view=False):
    if edit:
        url = f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/editar"
        if view:
            url += "?view=1"
    else:
        url = f"/admin/catalogo-versoes/{seed['base_id']}/nova-versao?from={seed['versao_id']}"
    return client.get(url)


def _payload(seed, **changes):
    data = {
        "tipo_atividade": "Acadêmica Complementar" if seed["eixo"] == "AAC" else "Extensão Universitária",
        "grupo": "1 - Grupo R4" if seed["eixo"] == "AAC" else "NA",
        "nome": seed["nome"],
        "descricao": "Descrição R4",
        "tipo_limitacao": "semestral",
        "limite_valor": "40",
        "ch_por_evento": "4",
        "observacoes": "Observações R4",
        "versao_anterior_id": str(seed["versao_id"]),
    }
    data.update(changes)
    return data


def _post_new(client, seed, **changes):
    return client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/nova-versao",
        data=_payload(seed, **changes),
        follow_redirects=False,
    )


def _row(versao_id):
    with main.app.app_context():
        row = main.get_db_connection().execute(
            "SELECT * FROM atividade_versao WHERE id=?", (versao_id,)
        ).fetchone()
        return dict(row) if row else None


def _versions(base_id):
    with main.app.app_context():
        return [dict(row) for row in main.get_db_connection().execute(
            "SELECT * FROM atividade_versao WHERE atividade_base_id=? ORDER BY numero_versao,id",
            (base_id,),
        ).fetchall()]


def _field_value(html, field_id):
    match = re.search(rf'id="{field_id}"[^>]*value="([^"]*)"', html)
    assert match, field_id
    return match.group(1)


def _textarea(html, field_id):
    match = re.search(rf'id="{field_id}"[^>]*>([^<]*)</textarea>', html)
    assert match, field_id
    return match.group(1)


def _selected(html, select_id):
    body = re.search(rf'<select[^>]*id="{select_id}"[^>]*>(.*?)</select>', html, re.S)
    assert body
    return re.findall(r'<option value="([^"]*)"[^>]*selected[^>]*>', body.group(1))


def _snapshot(html):
    match = re.search(
        r'<script id="versao-form-snapshot" type="application/json">(.*?)</script>',
        html, re.S,
    )
    assert match
    return json.loads(match.group(1))


def test_exact_eight_field_contract_and_forbidden_fields_absent(client):
    _login_admin(client)
    seed = _seed(client)
    html = _get(client, seed).get_data(as_text=True)
    assert re.findall(r'data-visible-field="([^"]+)"', html) == [
        "tipo", "grupo", "nome", "descricao", "limitacao",
        "ch_por_evento", "observacoes", "versao_anterior",
    ]
    for forbidden in (
        "Observação para o aluno", "Observação administrativa",
        "Vigência início", "Vigência fim", "Limite por semestre", "Limite total",
        'name="eixo"', '>Eixo<',
    ):
        assert forbidden not in html
    assert html.count('name="observacoes"') == 1
    assert '<select id="versao_anterior_id" name="versao_anterior_id"' in html


def test_activity_form_parity_and_all_effective_values_preload(client):
    _login_admin(client)
    seed = _seed(client)
    html = _get(client, seed).get_data(as_text=True)
    assert _selected(html, "tipo_atividade_sel") == ["Acadêmica Complementar"]
    assert _field_value(html, "grupo_hidden") == "1 - Grupo R4"
    assert _field_value(html, "nome") == seed["nome"]
    assert _textarea(html, "descricao") == "Descrição R4"
    assert _selected(html, "tipo_limit_card") == ["semestral"]
    assert _field_value(html, "limite_valor_hidden") == "40"
    assert _field_value(html, "ch_por_evento") == "4"
    assert _textarea(html, "observacoes") == "Observações R4"
    assert _selected(html, "versao_anterior_id") == [str(seed["versao_id"])]
    for contract in (
        'form-cards-narrow form-cards-narrow--wide', 'field-card split-2 compact-left',
        'id="grupo_num"', 'id="grupo_desc"', 'id="tipo_limit_card"',
        'class="form-actions center"', 'data-lucide="check"',
    ):
        assert contract in html


def test_dirty_snapshot_covers_all_fields_and_save_starts_disabled(client):
    _login_admin(client)
    seed = _seed(client)
    html = _get(client, seed).get_data(as_text=True)
    assert re.search(r'id="btn-salvar-versao"[^>]*disabled', html)
    assert set(_snapshot(html)) == {
        "tipo_atividade", "grupo", "nome", "descricao", "tipo_limitacao",
        "limite_valor", "ch_por_evento", "observacoes", "versao_anterior_id",
    }
    assert "Object.keys(snapshot).every" in html
    assert "Number.isNaN" in html


def test_unchanged_and_numeric_equivalent_posts_create_nothing(client):
    _login_admin(client)
    seed = _seed(client)
    before = _versions(seed["base_id"])
    for hours in ("4", "4.0"):
        response = _post_new(client, seed, ch_por_evento=hours)
        assert response.status_code == 200
        assert "Nenhuma alteração efetiva" in response.get_data(as_text=True)
        assert _versions(seed["base_id"]) == before


def test_same_type_change_creates_next_version_and_preserves_source(client):
    _login_admin(client)
    seed = _seed(client)
    before = _row(seed["versao_id"])
    response = _post_new(client, seed, ch_por_evento="6")
    assert response.status_code == 302
    v1, v2 = _versions(seed["base_id"])
    assert v1 == before
    assert (v2["numero_versao"], v2["status"], v2["versao_anterior_id"]) == (
        2, "rascunho", seed["versao_id"],
    )
    assert v2["atividade_base_id"] == seed["base_id"] and v2["ch_por_evento"] == 6


def test_aac_to_aeu_is_editable_and_uses_transition_architecture(client):
    _login_admin(client)
    seed = _seed(client)
    before = _row(seed["versao_id"])
    html = _get(client, seed).get_data(as_text=True)
    assert re.search(r'<select[^>]*name="tipo_atividade"[^>]*id="tipo_atividade_sel"[^>]*required', html)
    response = _post_new(
        client, seed, tipo_atividade="Extensão Universitária", grupo="NA",
    )
    assert response.status_code == 302
    v1, v2 = _versions(seed["base_id"])
    assert v1 == before and v2["eixo"] == "AEU"
    assert v2["atividade_base_id"] == seed["base_id"] and v2["versao_anterior_id"] is None
    with main.app.app_context():
        transition = main.get_db_connection().execute(
            "SELECT * FROM atividade_transicao WHERE from_atividade_versao_id=? AND to_atividade_versao_id=?",
            (v1["id"], v2["id"]),
        ).fetchone()
    assert transition["tipo_transicao"] == "aac_para_aeu"
    assert transition["justificativa"].strip()


def test_reverse_cross_type_without_architecture_is_rejected(client):
    _login_admin(client)
    seed = _seed(client, eixo="AEU")
    before = _versions(seed["base_id"])
    response = _post_new(
        client, seed, tipo_atividade="Acadêmica Complementar", grupo="1 - Grupo R4",
    )
    assert response.status_code == 200
    assert _versions(seed["base_id"]) == before


def test_base_owned_name_and_description_write_to_base_only(client):
    _login_admin(client)
    seed = _seed(client)
    source_before = _row(seed["versao_id"])
    response = _post_new(client, seed, nome=f"{seed['nome']} atualizado", descricao="Descrição atualizada")
    assert response.status_code == 302
    assert _row(seed["versao_id"]) == source_before
    with main.app.app_context():
        base = main.get_db_connection().execute(
            "SELECT nome_conceito,descricao FROM atividade_base WHERE id=?", (seed["base_id"],)
        ).fetchone()
    assert (base["nome_conceito"], base["descricao"]) == (
        f"{seed['nome']} atualizado", "Descrição atualizada",
    )
    assert "nome_conceito" not in _row(_versions(seed["base_id"])[1]["id"])


def test_single_observacoes_preserves_legacy_split_until_intentional_change(client):
    _login_admin(client)
    seed = _seed(client)
    assert _post_new(client, seed, ch_por_evento="6").status_code == 302
    unchanged_observation = _versions(seed["base_id"])[1]
    assert unchanged_observation["observacao_aluno"] == "Legado aluno R4"
    assert unchanged_observation["observacao_admin"] == "Observações R4"

    seed2 = _seed(client)
    assert _post_new(client, seed2, observacoes="Observação canônica nova").status_code == 302
    changed_observation = _versions(seed2["base_id"])[1]
    assert changed_observation["observacao_aluno"] == "Observação canônica nova"
    assert changed_observation["observacao_admin"] == "Observação canônica nova"


def test_single_limitation_control_writes_only_selected_owner(client):
    _login_admin(client)
    seed = _seed(client)
    response = _post_new(
        client, seed, tipo_limitacao="total", limite_valor="125",
    )
    assert response.status_code == 302
    v2 = _versions(seed["base_id"])[1]
    assert v2["limite_total"] == 125 and v2["limite_semestre"] is None


def test_vigencia_is_not_exposed_but_is_compatibly_preserved(client):
    _login_admin(client)
    seed = _seed(client)
    html = _get(client, seed).get_data(as_text=True)
    assert "vigencia_inicio" not in html and "vigencia_fim" not in html
    assert _post_new(client, seed, ch_por_evento="6").status_code == 302
    v2 = _versions(seed["base_id"])[1]
    assert (v2["vigencia_inicio"], v2["vigencia_fim"]) == ("2026-01-01", "2026-12-31")


def test_predecessor_validation_rejects_missing_and_foreign_ids(client):
    _login_admin(client)
    seed = _seed(client)
    foreign = _seed(client)
    before = _versions(seed["base_id"])
    for predecessor in ("", "999999", str(foreign["versao_id"])):
        response = _post_new(client, seed, ch_por_evento="6", versao_anterior_id=predecessor)
        assert response.status_code == 200
        assert _versions(seed["base_id"]) == before


def test_existing_exact_version_uses_same_form_and_switcher_lifecycle(client):
    _login_admin(client)
    draft = _seed(client)
    draft_html = _get(client, draft, edit=True).get_data(as_text=True)
    assert len(re.findall(r'data-visible-field="', draft_html)) == 8
    assert 'id="versao-switcher"' in draft_html
    assert 'id="btn-salvar-versao"' in draft_html
    assert '<select id="versao_anterior_id"' in draft_html

    immutable = _seed(client, status="ativa")
    view_html = _get(client, immutable, edit=True).get_data(as_text=True)
    assert len(re.findall(r'data-visible-field="', view_html)) == 8
    assert 'id="versao-switcher"' in view_html
    assert 'id="btn-salvar-versao"' not in view_html
    assert 'id="versao_anterior_meta"' in view_html


def test_existing_draft_edit_persists_visible_fields_without_vigencia_loss(client):
    _login_admin(client)
    seed = _seed(client)
    response = client.post(
        f"/admin/catalogo-versoes/{seed['base_id']}/versoes/{seed['versao_id']}/editar",
        data=_payload(
            seed, nome=f"{seed['nome']} editado", descricao="Descrição editada",
            ch_por_evento="8", observacoes="Observações editadas",
            versao_anterior_id="",
        ),
        follow_redirects=False,
    )
    assert response.status_code == 302
    row = _row(seed["versao_id"])
    assert row["ch_por_evento"] == 8
    assert row["observacao_aluno"] == row["observacao_admin"] == "Observações editadas"
    assert (row["vigencia_inicio"], row["vigencia_fim"]) == ("2026-01-01", "2026-12-31")
