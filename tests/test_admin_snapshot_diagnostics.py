import json
import os
import sys
import uuid

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import main
from app.views.admin import requisicoes as requisicoes_owner


@pytest.fixture()
def client():
    app = main.app
    with app.app_context():
        main.init_db()
        yield app.test_client()


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_type"] = "admin"
        sess["user_name"] = "Administrador"


def _snapshot_payload(
    *,
    atividade_versao_id: int,
    atividade_id_legacy: int,
    codigo_normativo: str = "AAC-rev6",
    extra: dict | None = None,
) -> dict:
    payload = {
        "schema_version": "d6.4.0-v1",
        "snapshot_written_at": "2026-05-31T13:15:00Z",
        "flow_origin": "admin_create",
        "resolver_status": "resolved",
        "resolver_warnings": ["warning-controlado"],
        "legacy_scope_ok": True,
        "matriz_id_efetiva": 321,
        "atividade_id_legacy": atividade_id_legacy,
        "atividade_base_id": 654,
        "atividade_versao_id": atividade_versao_id,
        "codigo_normativo": codigo_normativo,
        "eixo": "AAC",
        "grupo": "8 - Grupo Snapshot",
        "ch_por_evento": 12,
        "limite_semestre": 40,
        "limite_total": 80,
        "nome_exibivel": "Atividade versionada",
        "nome_legacy": "Atividade legado",
        "tipo_atividade_legacy": "Acadêmica Complementar",
        "versao_status": "vigente",
    }
    if extra:
        payload.update(extra)
    return payload


def _seed_admin_request(
    *,
    label: str,
    snapshot_payload: dict | None = None,
    raw_snapshot_json=None,
    atividade_versao_id=None,
    codigo_normativo_snapshot=None,
    status: str = "Pendente",
    tem_limitacao: int = 0,
) -> dict:
    token = uuid.uuid4().hex[:8]
    with main.app.app_context():
        conn = main.get_db_connection()
        curso = conn.execute("SELECT id, codigo FROM cursos ORDER BY id LIMIT 1").fetchone()
        assert curso is not None

        turma_numero = (int(token[:6], 16) % 9000) + 1000
        turma_codigo = main.gerar_codigo_turma(curso["codigo"], turma_numero)
        activity_name = f"AAC Snapshot {label} {token}"
        email = f"admin.snapshot.{label}.{token}@teste.local"
        matricula = f"SNAP-{label[:4].upper()}-{token}"

        atividade_id = conn.execute(
            """
            INSERT INTO atividades (
                grupo, nome, limite_horas, tipo_atividade, tem_limitacao, tipo_limitacao,
                limite_horas_total, limite_horas_semestral, documentos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                "8 - Grupo Snapshot",
                activity_name,
                None,
                "Acadêmica Complementar",
                tem_limitacao,
                None,
                None,
                None,
                None,
            ),
        ).fetchone()["id"]
        turma_id = conn.execute(
            """
            INSERT INTO turmas (
                nome, ano, semestre, turno, status, numero, curso_id, matriz_id,
                ano_inicio, semestre_inicio, ano_fim, semestre_fim, codigo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                turma_codigo,
                None,
                None,
                "Noite",
                "Ativa",
                turma_numero,
                curso["id"],
                None,
                2032,
                1,
                2035,
                2,
                turma_codigo,
            ),
        ).fetchone()["id"]
        usuario_id = conn.execute(
            "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?) RETURNING id",
            (f"Aluno Snapshot {label}", email, main.hash_password("aluno123"), "aluno"),
        ).fetchone()["id"]
        aluno_id = conn.execute(
            "INSERT INTO alunos (usuario_id, nome, matricula, email, turma_id, status) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            (usuario_id, f"Aluno Snapshot {label}", matricula, email, turma_id, "Ativo"),
        ).fetchone()["id"]

        if raw_snapshot_json is None and snapshot_payload is not None:
            raw_snapshot_json = json.dumps(snapshot_payload, ensure_ascii=False, sort_keys=True)

        req_id = conn.execute(
            """
            INSERT INTO requisicoes (
                aluno_id, atividade_id, data_solicitacao, data_evento, horas_solicitadas,
                nome_evento, status, horas_deferidas, observacao, arquivo_comprovante,
                data_processamento, admin_id, atividade_versao_id, regra_snapshot_json,
                codigo_normativo_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                aluno_id,
                atividade_id,
                "2032-03-10 10:00:00",
                "2032-03-10",
                8,
                f"Evento Snapshot {label}",
                status,
                None,
                None,
                None,
                None,
                None,
                atividade_versao_id,
                raw_snapshot_json,
                codigo_normativo_snapshot,
            ),
        ).fetchone()["id"]
        conn.commit()

    return {
        "req_id": req_id,
        "atividade_id": atividade_id,
        "activity_name": activity_name,
        "aluno_id": aluno_id,
        "token": token,
    }


def test_snapshot_helper_returns_none_without_versioned_columns():
    row = {
        "atividade_versao_id": None,
        "codigo_normativo_snapshot": None,
        "regra_snapshot_json": None,
    }

    assert main._build_admin_requisicao_snapshot_diagnostic(row) is None


def test_snapshot_display_flag_defaults_off_and_is_independent(monkeypatch):
    monkeypatch.delenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", raising=False)
    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", "1")
    monkeypatch.setenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", "1")

    assert main.is_versioned_requisicao_snapshot_display_enabled() is False
    assert main.is_versioned_requisicao_snapshot_write_enabled() is True
    assert main.is_versioned_resolver_shadow_read_enabled() is True

    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", "1")
    monkeypatch.delenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", raising=False)
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)

    assert main.is_versioned_requisicao_snapshot_display_enabled() is True
    assert main.is_versioned_requisicao_snapshot_write_enabled() is False
    assert main.is_versioned_resolver_shadow_read_enabled() is False


def test_snapshot_helper_curates_payload_and_ignores_sensitive_fields():
    row = {
        "atividade_versao_id": 777,
        "codigo_normativo_snapshot": "AAC-rev6",
        "regra_snapshot_json": json.dumps(
            _snapshot_payload(
                atividade_versao_id=777,
                atividade_id_legacy=15,
                extra={
                    "observacao_aluno": "nao pode vazar",
                    "observacao_admin": "nao pode vazar",
                    "documentos": ["/tmp/doc.pdf"],
                    "paths": ["C:/segredo"],
                    "dados_pessoais_adicionais": {"nome": "Aluno"},
                },
            ),
            ensure_ascii=False,
            sort_keys=True,
        ),
    }

    diagnostic = main._build_admin_requisicao_snapshot_diagnostic(row)

    assert diagnostic is not None
    assert diagnostic["diagnostico_disponivel"] is True
    assert diagnostic["atividade_versao_id"] == 777
    assert diagnostic["codigo_normativo_snapshot"] == "AAC-rev6"
    assert diagnostic["codigo_normativo"] == "AAC-rev6"
    assert diagnostic["nome_exibivel"] == "Atividade versionada"
    assert diagnostic["nome_legacy"] == "Atividade legado"
    assert diagnostic["tipo_atividade_legacy"] == _snapshot_payload(
        atividade_versao_id=777,
        atividade_id_legacy=15,
    )["tipo_atividade_legacy"]
    assert diagnostic["resolver_status"] == "resolved"
    assert "observacao_aluno" not in diagnostic
    assert "observacao_admin" not in diagnostic
    assert "documentos" not in diagnostic
    assert "paths" not in diagnostic
    assert "dados_pessoais_adicionais" not in diagnostic


def test_snapshot_helper_ignores_non_scalar_comparison_fields():
    row = {
        "atividade_versao_id": 778,
        "codigo_normativo_snapshot": "AAC-rev6",
        "regra_snapshot_json": json.dumps(
            _snapshot_payload(
                atividade_versao_id=778,
                atividade_id_legacy=16,
                extra={
                    "nome_exibivel": {"valor": "nao renderizar"},
                    "nome_legacy": ["nao renderizar"],
                    "tipo_atividade_legacy": {"tipo": "nao renderizar"},
                },
            ),
            ensure_ascii=False,
            sort_keys=True,
        ),
    }

    diagnostic = main._build_admin_requisicao_snapshot_diagnostic(row)

    assert diagnostic is not None
    assert diagnostic["diagnostico_disponivel"] is True
    assert "nome_exibivel" not in diagnostic
    assert "nome_legacy" not in diagnostic
    assert "tipo_atividade_legacy" not in diagnostic


def test_admin_requisicoes_list_shows_legacy_and_versioned_rows_in_mixed_base(client):
    suffix = uuid.uuid4().hex[:6]
    legacy_req = _seed_admin_request(label=f"mista-antiga-{suffix}")
    versioned_req = _seed_admin_request(
        label=f"mista-nova-{suffix}",
        snapshot_payload=_snapshot_payload(atividade_versao_id=901, atividade_id_legacy=1),
        atividade_versao_id=901,
        codigo_normativo_snapshot="AAC-rev6",
    )

    _login_admin(client)

    response = client.get("/admin/requisicoes", query_string={"q": suffix})
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert legacy_req["activity_name"] in html
    assert versioned_req["activity_name"] in html
    assert html.count('data-snapshot-versioned="1"') == 1
    assert html.count('data-snapshot-versioned="0"') == 1


def test_admin_requisicoes_list_omits_snapshot_visual_badge_for_versioned_request(client):
    seeded = _seed_admin_request(
        label="badge",
        snapshot_payload=_snapshot_payload(atividade_versao_id=777, atividade_id_legacy=1),
        atividade_versao_id=777,
        codigo_normativo_snapshot="AAC-rev6",
    )

    _login_admin(client)

    response = client.get("/admin/requisicoes", query_string={"q": seeded["activity_name"]})
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert seeded["activity_name"] in html
    assert "Registrada" not in html
    assert "Snapshot versionado" not in html
    assert "Versão registrada" not in html
    assert "req-snapshot-badge" not in html
    assert 'data-snapshot-versioned="1"' in html


def test_admin_processar_requisicao_shows_snapshot_diagnostic_block(client):
    seeded = _seed_admin_request(
        label="process-valid",
        snapshot_payload=_snapshot_payload(
            atividade_versao_id=333,
            atividade_id_legacy=1,
            extra={
                "observacao_aluno": "nao mostrar aluno",
                "observacao_admin": "nao mostrar admin",
                "documentos": ["segredo.pdf"],
                "paths": ["C:/interno"],
                "texto_livre_usuario": "nao mostrar texto livre",
            },
        ),
        atividade_versao_id=333,
        codigo_normativo_snapshot="AAC-rev6",
    )

    _login_admin(client)

    response = client.get(f"/admin/processar_requisicao/{seeded['req_id']}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "atividade_versao_id" in html
    assert "333" in html
    assert "codigo_normativo_snapshot" in html
    assert "AAC-rev6" in html
    assert "flow_origin" in html
    assert "admin_create" in html
    assert "snapshot_written_at" in html
    assert "2026-05-31T13:15:00Z" in html
    assert "resolver_status" in html
    assert "resolved" in html
    assert "observacao_aluno" not in html
    assert "observacao_admin" not in html
    assert "documentos" not in html
    assert "paths" not in html
    assert "nao mostrar aluno" not in html
    assert "nao mostrar admin" not in html
    assert "segredo.pdf" not in html
    assert "C:/interno" not in html
    assert "nao mostrar texto livre" not in html
    assert "Comparação com cadastro atual" not in html
    assert "Nome atual no cadastro" not in html
    assert "Nome no momento da solicitação" not in html


def test_admin_processar_requisicao_with_display_flag_on_shows_legacy_vs_snapshot_comparison(client, monkeypatch):
    seeded = _seed_admin_request(
        label="process-display-on",
        snapshot_payload=_snapshot_payload(atividade_versao_id=334, atividade_id_legacy=1),
        atividade_versao_id=334,
        codigo_normativo_snapshot="AAC-rev6",
    )

    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", "1")
    monkeypatch.delenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_WRITE", raising=False)
    monkeypatch.delenv("SGAA_VERSIONED_RESOLVER_SHADOW_READ", raising=False)
    _login_admin(client)

    response = client.get(f"/admin/processar_requisicao/{seeded['req_id']}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Comparação com cadastro atual" in html
    assert "Este bloco é apenas para conferência e não altera a decisão operacional." in html
    assert "Nome atual no cadastro" in html
    assert seeded["activity_name"] in html
    assert "Tipo atual no cadastro" in html
    assert "ID atual no cadastro" in html
    assert str(seeded["atividade_id"]) in html
    assert "Nome no momento da solicitação" in html
    assert "Atividade versionada" in html
    assert "Tipo no momento da solicitação" in html
    assert "Nome registrado na solicitação" in html
    assert "Atividade legado" in html
    assert "atividade_versao_id" in html
    assert "334" in html


def test_admin_processar_requisicao_without_snapshot_shows_neutral_state(client):
    seeded = _seed_admin_request(label="process-none")

    _login_admin(client)

    response = client.get(f"/admin/processar_requisicao/{seeded['req_id']}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Sem registro de versão" in html


def test_admin_processar_requisicao_with_malformed_snapshot_json_shows_unavailable_message(client):
    seeded = _seed_admin_request(
        label="process-invalid",
        raw_snapshot_json="{json invalido",
        atividade_versao_id=444,
        codigo_normativo_snapshot="AAC-rev6",
    )

    _login_admin(client)

    response = client.get(f"/admin/processar_requisicao/{seeded['req_id']}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Registro da solicitação presente, mas" in html


def test_admin_processar_requisicao_with_partial_snapshot_payload_does_not_break(client, monkeypatch):
    seeded = _seed_admin_request(
        label="process-partial",
        snapshot_payload={
            "flow_origin": "aluno_create",
            "resolver_status": "resolved",
            "snapshot_written_at": "2026-05-31T13:45:00Z",
        },
        atividade_versao_id=555,
        codigo_normativo_snapshot="AAC-rev6",
    )

    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", "1")
    _login_admin(client)

    response = client.get(f"/admin/processar_requisicao/{seeded['req_id']}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Registro da solicitação presente, mas" not in html
    assert "Comparação com cadastro atual" in html
    assert "flow_origin" in html
    assert "aluno_create" in html
    assert "resolver_status" in html
    assert "resolved" in html
    assert "2026-05-31T13:45:00Z" in html
    assert "Nome no momento da solicitação" not in html
    assert "Tipo no momento da solicitação" not in html


def test_admin_processar_requisicao_post_keeps_legacy_activity_id_for_decision(client, monkeypatch):
    seeded = _seed_admin_request(
        label="process-legacy",
        snapshot_payload=_snapshot_payload(
            atividade_versao_id=888,
            atividade_id_legacy=99999,
            extra={"atividade_base_id": 1234},
        ),
        atividade_versao_id=888,
        codigo_normativo_snapshot="AAC-rev6",
    )

    called = []

    def fake_scope_check(conn, atividade_id, curso_id, matriz_id):
        called.append((atividade_id, curso_id, matriz_id))
        return True

    monkeypatch.setattr(
        requisicoes_owner, "is_activity_allowed_for_turma_matrix", fake_scope_check
    )
    _login_admin(client)

    response = client.post(
        f"/admin/processar_requisicao/{seeded['req_id']}",
        data={"status": "Deferida", "observacao": "Diagnostico nao decide"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    assert called
    assert called[0][0] == seeded["atividade_id"]
    assert called[0][0] != 99999
    assert called[0][0] != 888

    with main.app.app_context():
        conn = main.get_db_connection()
        row = conn.execute(
            "SELECT status, observacao, atividade_id FROM requisicoes WHERE id = ?",
            (seeded["req_id"],),
        ).fetchone()
        assert row is not None
        assert row["status"] == "Deferida"
        assert row["observacao"] == "Diagnostico nao decide"
        assert row["atividade_id"] == seeded["atividade_id"]


def test_admin_requisicoes_does_not_gain_snapshot_comparison_when_display_flag_is_on(client, monkeypatch):
    seeded = _seed_admin_request(
        label="list-no-compare",
        snapshot_payload=_snapshot_payload(atividade_versao_id=990, atividade_id_legacy=1),
        atividade_versao_id=990,
        codigo_normativo_snapshot="AAC-rev6",
    )

    monkeypatch.setenv("SGAA_VERSIONED_REQUISICAO_SNAPSHOT_DISPLAY", "1")
    _login_admin(client)

    response = client.get("/admin/requisicoes", query_string={"q": seeded["activity_name"]})
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert seeded["activity_name"] in html
    assert "Registrada" not in html
    assert "Snapshot versionado" not in html
    assert "req-snapshot-badge" not in html
    assert "Comparação com cadastro atual" not in html
    assert "Nome atual no cadastro" not in html
    assert "Nome no momento da solicitação" not in html
