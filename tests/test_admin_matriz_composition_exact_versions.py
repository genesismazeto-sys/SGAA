"""Surface A exact-version selection and frozen/read-only composition contracts."""
from __future__ import annotations

import html as html_module
import re
import uuid

import main
from tests.canonical_matrix_test_support import current_version_id, login_admin, seed_matrix_graph
from tests.versioned_test_support import isolated_versioned_app_env


def _assign_matrix(conn, seed: dict[str, int]) -> None:
    conn.execute(
        """INSERT INTO turmas
               (nome,turno,status,numero,curso_id,ano_inicio,semestre_inicio,codigo,matriz_id)
             VALUES (?,'Noite','Ativa',?,?,2026,1,?,?)""",
        (
            f"Frozen {seed['matrix_id']}",
            7000 + seed["matrix_id"],
            seed["course_id"],
            f"SURFACE-A-{seed['matrix_id']}",
            seed["matrix_id"],
        ),
    )
    conn.commit()


def _matrix_links(conn, matrix_id: int) -> list[tuple[int, int]]:
    return [
        (row["atividade_base_id"], row["atividade_versao_id"])
        for row in conn.execute(
            """SELECT atividade_base_id, atividade_versao_id
                 FROM matriz_atividade_versao_item
                WHERE matriz_id=?
                ORDER BY atividade_base_id""",
            (matrix_id,),
        ).fetchall()
    ]


def test_initial_selection_exposes_and_persists_exact_version(tmp_path):
    with isolated_versioned_app_env(tmp_path, "surface-a-initial.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Exact initial choice")
            conn.execute(
                "DELETE FROM matriz_atividade_versao_item WHERE matriz_id=?",
                (seed["matrix_id"],),
            )
            single_base = conn.execute(
                "INSERT INTO atividade_base(nome_conceito,descricao,status) VALUES (?,?,'ativo') RETURNING id",
                ("Single-version activity", "single-version proof"),
            ).fetchone()["id"]
            single_v1 = conn.execute(
                """INSERT INTO atividade_versao
                       (atividade_base_id,eixo,grupo,numero_versao,status)
                     VALUES (?,'AAC','2 - Single',1,'ativa') RETURNING id""",
                (single_base,),
            ).fetchone()["id"]
            conn.commit()
        login_admin(env["client"])

        page = env["client"].get(f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac")
        rendered = html_module.unescape(page.get_data(as_text=True))
        assert page.status_code == 200
        assert rendered.count(f'data-base-id="{seed["base_id"]}"') == 1
        assert rendered.count(f'data-base-id="{single_base}"') == 1
        multi_card = re.search(
            rf'<div class="matriz-transfer-item"[^>]*data-base-id="{seed["base_id"]}".*?</div>',
            rendered,
            re.S,
        ).group(0)
        assert f'value="{seed["v1"]}"' in multi_card
        assert f'value="{seed["v2"]}"' in multi_card
        assert f'value="{seed["v3_inactive"]}"' not in multi_card
        assert re.search(r'>v1</option>', multi_card)
        assert re.search(r'>v2</option>', multi_card)
        assert '<option value="" selected>Selecione</option>' not in multi_card
        assert re.search(rf'value="{seed["v2"]}"[^>]*selected', multi_card, re.S)
        assert not re.search(r'type="checkbox".*?disabled', multi_card, re.S)

        single_card = re.search(
            rf'<div class="matriz-transfer-item"[^>]*data-base-id="{single_base}".*?</div>',
            rendered,
            re.S,
        ).group(0)
        assert f'data-activity-id="{single_v1}"' in single_card
        assert '>v1</option>' in single_card
        assert not re.search(r'type="checkbox".*?disabled', single_card, re.S)
        assert '>v</option>' not in rendered
        assert "sua versão exata" in rendered

        saved = env["client"].post(
            f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac",
            data={"active_tab": "aac", "selected_activity_ids": [str(seed["v2"]), str(single_v1)]},
            follow_redirects=True,
        )
        assert saved.status_code == 200
        assert "Lista da matriz atualizada com sucesso." in saved.get_data(as_text=True)
        with main.app.app_context():
            assert _matrix_links(main.get_db_connection(), seed["matrix_id"]) == [
                (seed["base_id"], seed["v2"]),
                (single_base, single_v1),
            ]

        reloaded = html_module.unescape(
            env["client"].get(f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac").get_data(as_text=True)
        )
        selected_list = re.search(
            r'data-role="selected-list"(?P<body>.*?)<div class="matriz-transfer-empty" data-empty="selected"',
            reloaded,
            re.S,
        ).group("body")
        assert f'data-activity-id="{seed["v2"]}"' in selected_list
        assert f'data-activity-id="{seed["v1"]}"' not in selected_list
        selected_card = re.search(
            rf'<div class="matriz-transfer-item"[^>]*data-base-id="{seed["base_id"]}".*?</div>',
            selected_list,
            re.S,
        ).group(0)
        assert 'data-role="available-version-field" hidden' in selected_card
        assert f'value="{seed["v1"]}"' in selected_card
        assert f'value="{seed["v2"]}"' in selected_card
        assert '>v1</option>' in selected_card
        assert '>v2</option>' in selected_card


def test_ambiguous_same_base_payload_is_rejected_atomically(tmp_path):
    with isolated_versioned_app_env(tmp_path, "surface-a-ambiguous.db") as env:
        with main.app.app_context():
            seed = seed_matrix_graph(main.get_db_connection(), name="Ambiguous payload")
        login_admin(env["client"])

        response = env["client"].post(
            f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac",
            data={
                "active_tab": "aac",
                "selected_activity_ids": [str(seed["v1"]), str(seed["v2"])],
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Parâmetros inválidos." in response.get_data(as_text=True)
        with main.app.app_context():
            conn = main.get_db_connection()
            assert current_version_id(conn, seed) == seed["v1"]
            assert _matrix_links(conn, seed["matrix_id"]) == [(seed["base_id"], seed["v1"])]


def test_ineligible_exact_version_payload_is_rejected_atomically(tmp_path):
    with isolated_versioned_app_env(tmp_path, "surface-a-ineligible.db") as env:
        with main.app.app_context():
            seed = seed_matrix_graph(main.get_db_connection(), name="Ineligible payload")
        login_admin(env["client"])

        for invalid_version in (seed["v3_inactive"], "not-an-id"):
            response = env["client"].post(
                f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac",
                data={"active_tab": "aac", "selected_activity_ids": [str(invalid_version)]},
                follow_redirects=True,
            )
            assert "Parâmetros inválidos." in response.get_data(as_text=True)
            with main.app.app_context():
                assert current_version_id(main.get_db_connection(), seed) == seed["v1"]


def test_remove_membership_removes_only_the_exact_matrix_link(tmp_path):
    with isolated_versioned_app_env(tmp_path, "surface-a-remove.db") as env:
        with main.app.app_context():
            seed = seed_matrix_graph(main.get_db_connection(), name="Composition removal")
        login_admin(env["client"])

        response = env["client"].post(
            f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac",
            data={"active_tab": "aac"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "Lista da matriz atualizada com sucesso." in response.get_data(as_text=True)
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) is None


def test_frozen_composition_has_no_mutation_affordance_or_client_writer(tmp_path):
    with isolated_versioned_app_env(tmp_path, "surface-a-frozen.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Frozen composition")
            _assign_matrix(conn, seed)
        login_admin(env["client"])

        page = env["client"].get(f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac")
        rendered = html_module.unescape(page.get_data(as_text=True))
        assert page.status_code == 200
        assert "sua composição está disponível somente para consulta" in rendered
        assert 'class="flash flash-info matriz-tab-notice"' in rendered
        assert 'data-transfer-root data-readonly="1"' in rendered
        assert '<form method="POST" class="matriz-transfer-form"' not in rendered
        assert 'name="selected_activity_ids"' not in rendered
        assert 'data-move=' not in rendered
        assert 'data-open-new-activity-modal' not in rendered
        assert 'data-open-version-modal' not in rendered
        assert 'id="matriz-version-form"' not in rendered
        assert 'data-side="available"' not in rendered
        assert 'data-side="selected"' not in rendered
        assert '<span class="btn-label">Salvar</span>' not in rendered
        assert 'class="version-identifier version-badge"' in rendered

        env["client"].post(
            f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac",
            data={"active_tab": "aac", "selected_activity_ids": [str(seed["v2"])]},
        )
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) == seed["v1"]


def test_modal_availability_state_is_truthful(tmp_path):
    with isolated_versioned_app_env(tmp_path, "surface-a-modal.db"):
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Modal availability")
            conn.execute("UPDATE atividade_versao SET status='inativa' WHERE id=?", (seed["v2"],))
            conn.commit()
            data = main.get_card_version_menu_data(conn, seed["matrix_id"], [seed["v1"]])
            entry = data[str(seed["v1"])]
            assert entry["alternative_count"] == 0
            assert entry["availability_message"] == "A versão atual é a única versão ativa elegível."
            assert [version["id"] for version in entry["versoes"]] == [seed["v1"]]


def test_consultive_access_is_readonly_and_post_is_denied(tmp_path):
    with isolated_versioned_app_env(tmp_path, "surface-a-rbac.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Consultive composition")
            user_id = conn.execute(
                """INSERT INTO usuarios(nome,email,senha,tipo,nivel_acesso)
                     VALUES (?,?,?,'admin','consultivo') RETURNING id""",
                (
                    "Consultive Surface A",
                    f"surface-a-{uuid.uuid4().hex[:8]}@example.com",
                    main.hash_password("surface-a-test"),
                ),
            ).fetchone()["id"]
            conn.commit()
        with env["client"].session_transaction() as session:
            session.update(user_id=user_id, user_type="admin", user_name="Consultive Surface A")

        page = env["client"].get(f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac")
        rendered = page.get_data(as_text=True)
        assert page.status_code == 200
        assert "Seu acesso a esta Matriz é somente para consulta." in rendered
        assert 'data-transfer-root data-readonly="1"' in rendered
        assert '<form method="POST" class="matriz-transfer-form"' not in rendered

        denied = env["client"].post(
            f"/admin/editar_matriz/{seed['matrix_id']}?tab=aac",
            data={"active_tab": "aac", "selected_activity_ids": [str(seed["v2"])]},
        )
        assert denied.status_code == 302
        assert denied.headers["Location"].endswith("/admin/dashboard")
        with main.app.app_context():
            assert current_version_id(main.get_db_connection(), seed) == seed["v1"]


def test_transfer_script_replaces_same_base_and_never_implicitly_chooses_from_add_all():
    template = open("templates/admin_matriz_form.html", encoding="utf-8").read()
    assert "{% set composition_locked = readonly or is_academically_frozen %}" in template
    assert "interaction_locked" not in template
    assert ".matriz-tab-notice{" in template
    assert "margin-bottom: var(--form-gap);" in template
    assert 'data-role="available-version-select"' in template
    assert ".matriz-transfer-version-field[hidden]{ display:none; }" in template
    assert template.count('class="field-card is-compact matriz-transfer-version-control"') == 2
    assert ".matriz-transfer-version-control .control{" in template
    assert "{% set default_version = item.eligible_versions|last %}" in template
    assert 'data-activity-id="{{ item.id or default_version.id }}"' in template
    assert "version.id == (item.id or default_version.id)" in template
    assert 'data-role="selected-version-display"' in template
    assert 'data-role="available-version-field" hidden' in template
    assert "if (targetList === availableList && versionField)" in template
    assert "versionField.hidden = false" in template
    assert "selectedVersionDisplay.hidden = true" in template
    assert "item.dataset.activityId = activityId" in template
    assert "checkbox.disabled = !activityId" in template
    assert "if (item.dataset.activityId) return true" in template
    assert "syncHiddenInputs();" in template
    assert ".card-version-menu-btn[hidden]{ display:none !important; }" in template
    assert "#version-modal-availability[hidden]{ display:none !important; }" in template
    assert "Selecione uma versão exata para atividades com mais de uma opção." in template
    assert "Esta atividade não possui versões cadastradas." not in template


def test_aeu_available_versions_are_grouped_by_activity_base(tmp_path):
    with isolated_versioned_app_env(tmp_path, "surface-a-aeu-grouped.db") as env:
        with main.app.app_context():
            conn = main.get_db_connection()
            seed = seed_matrix_graph(conn, name="Grouped AEU")
            conn.execute(
                "DELETE FROM matriz_atividade_versao_item WHERE matriz_id=?",
                (seed["matrix_id"],),
            )
            base_id = conn.execute(
                "INSERT INTO atividade_base(nome_conceito,status) VALUES('AEU grouped base','ativo') RETURNING id"
            ).fetchone()["id"]
            v1 = conn.execute(
                """INSERT INTO atividade_versao(atividade_base_id,eixo,grupo,numero_versao,status)
                     VALUES (?,'AEU','NA',1,'ativa') RETURNING id""",
                (base_id,),
            ).fetchone()["id"]
            v2 = conn.execute(
                """INSERT INTO atividade_versao(atividade_base_id,eixo,grupo,numero_versao,status)
                     VALUES (?,'AEU','NA',2,'ativa') RETURNING id""",
                (base_id,),
            ).fetchone()["id"]
            conn.commit()
        login_admin(env["client"])

        rendered = html_module.unescape(
            env["client"].get(
                f"/admin/editar_matriz/{seed['matrix_id']}?tab=aea"
            ).get_data(as_text=True)
        )
        assert rendered.count(f'data-base-id="{base_id}"') == 1
        assert f'value="{v1}"' in rendered
        assert f'value="{v2}"' in rendered
        assert '>v1</option>' in rendered
        assert '>v2</option>' in rendered
        assert re.search(rf'value="{v2}"[^>]*selected', rendered, re.S)
