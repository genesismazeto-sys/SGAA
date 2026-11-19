"""UI-B40 -- users see a closed request as Indeferida.

The owner removed the user-visible distinction between a denial
(``Indeferida``) and an administrative closure (``Encerrada``). It is
presentation only (``app.status_presentation.REQUEST_STATUS_DISPLAY``): the
stored status stays ``Encerrada``, and so do the rules that read it -- the
student still cannot edit, rectify or reclassify it, and it sends no e-mail.
"""
from __future__ import annotations

import json
import re

import pytest

import main
from app.request_email_notifications import NON_NOTIFYING_STATUSES
from app.requisition_policy import can_student_edit_requisition
from app.status_presentation import (
    REQUEST_STATUS_TONES,
    request_statuses_shown_as,
    status_label,
    status_tone,
)
from tests.canonical_request_test_support import create_admin_request, login_admin, login_student
from tests.versioned_test_support import isolated_versioned_app_env

PILL_RE = re.compile(r'class="[^"]*\bstatus-pill\b[^"]*"[^>]*>\s*([^<]+?)\s*<')


def test_a_closed_request_is_labelled_indeferida_and_nothing_else_changes():
    for spelling in ("Encerrada", "encerrada", "encerrado", "closed"):
        assert status_label("requisicao", spelling) == "Indeferida"
    assert status_tone("requisicao", "Encerrada") == status_tone("requisicao", "Indeferida") == "negative"
    for status in REQUEST_STATUS_TONES:
        if status != "Encerrada":
            assert status_label("requisicao", status) == status
    # Only the Requisições domain: a retired Matriz is still Encerrada.
    assert status_label("matriz", "encerrada") == "Encerrada"
    assert request_statuses_shown_as("Indeferida") == ("Indeferida", "Encerrada")
    assert request_statuses_shown_as("Pendente") == ("Pendente",)
    assert request_statuses_shown_as("Encerrada") == ("Encerrada",)  # an older link


@pytest.fixture
def env(tmp_path):
    with isolated_versioned_app_env(tmp_path, "ui-b40.db") as environment:
        client = environment["client"]
        login_admin(client)
        ids = {}
        for key, status in (("closed", "Encerrada"), ("denied", "Indeferida"), ("pending", "Pendente")):
            _response, row = create_admin_request(client, f"UI-B40 {key}")
            ids[key] = row["id"]
            with main.app.app_context():
                conn = main.get_db_connection()
                conn.execute(
                    "UPDATE requisicoes SET status = ?, data_processamento = ? WHERE id = ?",
                    (status, None if status == "Pendente" else "2026-01-10 10:00:00", row["id"]),
                )
                conn.commit()
        environment.update(ids)
        yield environment


def _stored(request_id):
    with main.app.app_context():
        return main.get_db_connection().execute(
            "SELECT status FROM requisicoes WHERE id = ?", (request_id,)
        ).fetchone()["status"]


def _pills(html):
    return [text.strip() for text in PILL_RE.findall(html)]


def _filter_values(html):
    schema = json.loads(
        re.search(r'<script id="filter-schema-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    )
    status = next(item for item in schema if item["param"] == "status")
    return [(value["value"], value["label"]) for value in status["values"]]


def test_the_admin_sees_indeferida_on_the_list_its_filter_and_the_request_pages(env):
    client = env["client"]
    html = client.get("/admin/requisicoes").get_data(as_text=True)
    assert "Encerrada" not in _pills(html)
    assert _pills(html).count("Indeferida") == 2
    labels = [label for _value, label in _filter_values(html)]
    assert "Encerrada" not in labels and "Indeferida" in labels
    # The Indeferida filter returns both, and so does an older link to encerrada.
    for value in ("indeferida", "encerrada"):
        listed = client.get(f"/admin/requisicoes?status={value}").get_data(as_text=True)
        assert "UI-B40 closed" in listed and "UI-B40 denied" in listed and "UI-B40 pending" not in listed
    # The text search reads the shown label too.
    found = client.get("/admin/requisicoes?q=Indeferida").get_data(as_text=True)
    assert "UI-B40 closed" in found and "UI-B40 denied" in found and "UI-B40 pending" not in found
    assert "UI-B40 closed" not in client.get("/admin/requisicoes?q=Encerrada").get_data(as_text=True)
    detail = client.get(f"/admin/requisicao/{env['closed']}").get_data(as_text=True)
    assert "Indeferida" in detail and "Encerrada" not in detail
    process = client.get(f"/admin/processar_requisicao/{env['closed']}").get_data(as_text=True)
    assert "Status atual: <strong>Indeferida</strong>" in process
    assert _stored(env["closed"]) == "Encerrada"


def test_the_student_sees_indeferida_on_the_list_its_filter_and_the_dashboard(env):
    client = env["client"]
    login_student(client)
    html = client.get("/aluno/requisicoes").get_data(as_text=True)
    assert "Encerrada" not in _pills(html)
    assert _pills(html).count("Indeferida") == 2
    values = _filter_values(html)
    assert ("Indeferida", "Indeferida") in values and not any("Encerrada" in pair for pair in values)
    listed = client.get("/aluno/requisicoes?status=Indeferida").get_data(as_text=True)
    assert sorted(re.findall(r'data-status="([^"]*)"', listed)) == ["Encerrada", "Indeferida"]
    found = client.get("/aluno/requisicoes?q=Indeferida").get_data(as_text=True)
    assert sorted(re.findall(r'data-status="([^"]*)"', found)) == ["Encerrada", "Indeferida"]
    assert re.findall(r'data-status="([^"]*)"', client.get("/aluno/requisicoes?q=Encerrada").get_data(as_text=True)) == []
    dashboard = client.get("/aluno/dashboard").get_data(as_text=True)
    count = re.search(
        r'<span class="value">(\d+)</span>\s*<span class="label"><i class="lucide" data-lucide="x-circle"></i>Indeferidas',
        dashboard,
    )
    assert count and count.group(1) == "2"
    assert _stored(env["closed"]) == "Encerrada"


def test_the_rules_still_read_the_stored_status(env):
    """A closed request stays closed: the student cannot edit it, and it sends no e-mail."""
    assert "Encerrada" in NON_NOTIFYING_STATUSES
    assert can_student_edit_requisition("Encerrada", "2026-11-18 10:00:00", return_days=30) is False
    client = env["client"]
    login_student(client)
    response = client.get(f"/aluno/requisicoes/{env['closed']}?edit=1")
    assert response.status_code in (302, 303)
    assert _stored(env["closed"]) == "Encerrada"
