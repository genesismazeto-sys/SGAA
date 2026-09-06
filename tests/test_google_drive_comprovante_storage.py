from __future__ import annotations

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from app.storage.contracts import StorageConflictError, StorageError, StorageTransientError
from app.storage.google_drive import GoogleDriveComprovanteStorage


class ExecuteRequest:
    def __init__(self, payload, *, fail_once=False):
        self.payload = payload
        self.fail_once = fail_once
        self.calls = 0

    def execute(self, num_retries=0):
        assert num_retries == 0
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise OSError("temporary transport failure")
        return self.payload


class FailingRequest:
    def __init__(self, payload, failures):
        self.payload = payload
        self.failures = list(failures)
        self.calls = 0

    def execute(self, num_retries=0):
        assert num_retries == 0
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.payload


class UploadRequest:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def next_chunk(self, num_retries=0):
        assert num_retries == 0
        self.calls += 1
        return object(), self.payload


class FakeFiles:
    def __init__(self, list_payloads):
        self.list_payloads = list(list_payloads)
        self.list_requests = []
        self.create_bodies = []
        self.upload_requests = []
        self.folder_create_request = None

    def list(self, **kwargs):
        self.list_requests.append(kwargs)
        payload = self.list_payloads.pop(0)
        if hasattr(payload, "execute"):
            return payload
        return ExecuteRequest(payload)

    def create(self, **kwargs):
        self.create_bodies.append(kwargs)
        if kwargs.get("media_body") is not None:
            request = UploadRequest(
                {
                    "id": "file-1",
                    "name": kwargs["body"]["name"],
                    "parents": kwargs["body"]["parents"],
                    "size": "4",
                    "sha256Checksum": "sha",
                }
            )
            self.upload_requests.append(request)
            return request
        return self.folder_create_request or ExecuteRequest({"id": "folder-created"})


class FakeService:
    def __init__(self, list_payloads):
        self.api = FakeFiles(list_payloads)

    def files(self):
        return self.api


def _adapter(*payloads):
    service = FakeService(payloads)
    return GoogleDriveComprovanteStorage(
        "token", service=service, retry_delays=(0,)
    ), service.api


def test_zero_semantic_folder_match_creates_with_private_managed_properties():
    adapter, api = _adapter({"files": []})
    folder_id = adapter.ensure_folder(
        parent_id="root", kind="turma", semantic_id="42", display_name="T-42"
    )
    assert folder_id == "folder-created"
    body = api.create_bodies[0]["body"]
    assert body["name"] == "T-42"
    assert body["parents"] == ["root"]
    assert body["appProperties"] == {
        "sgaaManaged": "true", "sgaaKind": "turma", "sgaaSemanticId": "42"
    }


def test_one_semantic_folder_match_reuses_exact_id():
    adapter, api = _adapter({"files": [{"id": "folder-existing", "name": "Old display"}]})
    assert adapter.ensure_folder(
        parent_id="root", kind="student", semantic_id="7", display_name="New display"
    ) == "folder-existing"
    assert api.create_bodies == []


def test_multiple_semantic_folder_matches_are_a_hard_conflict():
    adapter, _api = _adapter({"files": [{"id": "one"}, {"id": "two"}]})
    try:
        adapter.ensure_folder(
            parent_id="root", kind="student", semantic_id="7", display_name="Student"
        )
    except StorageConflictError:
        pass
    else:
        raise AssertionError("duplicate semantic folders must not be selected arbitrarily")


def test_equal_display_name_is_not_the_identity_query():
    adapter, api = _adapter({"files": []})
    adapter.ensure_folder(
        parent_id="root", kind="student", semantic_id="7", display_name="Same name"
    )
    query = api.list_requests[0]["q"]
    assert "name=" not in query
    assert "sgaaSemanticId" in query and "value='7'" in query
    assert api.create_bodies[0]["body"]["name"] == "Same name"


def test_transport_retry_is_bounded_and_upload_uses_resumable_media():
    transient = ExecuteRequest({"files": []}, fail_once=True)
    adapter, api = _adapter(transient)
    result = adapter.upload(
        parent_id="folder",
        stored_filename="proof.pdf",
        content=b"data",
        mime_type="application/pdf",
        operation_key="operation-1",
        request_id=10,
        attachment_id=20,
    )
    assert transient.calls == 2
    assert result.file_id == "file-1"
    request = api.create_bodies[0]
    assert request["media_body"].resumable()
    assert request["body"]["appProperties"]["sgaaOperation"] == "operation-1"


def test_remote_operation_match_prevents_duplicate_upload():
    adapter, api = _adapter(
        {
            "files": [
                {
                    "id": "existing",
                    "name": "proof.pdf",
                    "parents": ["folder"],
                    "size": "4",
                    "sha256Checksum": "sha",
                }
            ]
        }
    )
    result = adapter.upload(
        parent_id="folder",
        stored_filename="proof.pdf",
        content=b"data",
        mime_type="application/pdf",
        operation_key="operation-1",
        request_id=10,
        attachment_id=20,
    )
    assert result.file_id == "existing" and result.reused
    assert api.create_bodies == []


def _http_error(status):
    return HttpError(Response({"status": str(status), "reason": "test"}), b"{}")


def test_lost_successful_folder_create_reconciles_same_remote_identity_without_repost():
    adapter, api = _adapter(
        {"files": []},
        {"files": [{"id": "folder-created", "name": "T-42"}]},
    )
    api.folder_create_request = ExecuteRequest(
        {"id": "folder-created"}, fail_once=True
    )
    assert adapter.ensure_folder(
        parent_id="root", kind="turma", semantic_id="42", display_name="T-42"
    ) == "folder-created"
    assert len(api.create_bodies) == 1
    assert api.folder_create_request.calls == 1


@pytest.mark.parametrize("status", [400, 403, 404])
def test_permanent_4xx_is_not_retried_as_transient(status):
    request = FailingRequest({}, [_http_error(status)])
    adapter, _api = _adapter(request)
    with pytest.raises(StorageError) as captured:
        adapter._list("trashed=false")
    assert not captured.value.retryable
    assert request.calls == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retryable_provider_statuses_are_bounded(status):
    request = FailingRequest({"files": []}, [_http_error(status)])
    adapter, _api = _adapter(request)
    assert adapter._list("trashed=false") == []
    assert request.calls == 2


def test_repeated_retryable_provider_failure_stops_at_configured_bound():
    request = FailingRequest({}, [_http_error(429), _http_error(429)])
    adapter, _api = _adapter(request)
    with pytest.raises(StorageTransientError):
        adapter._list("trashed=false")
    assert request.calls == 2


def test_repeated_transport_failure_stops_at_configured_bound():
    request = FailingRequest({}, [OSError("lost"), OSError("lost again")])
    adapter, _api = _adapter(request)
    with pytest.raises(StorageTransientError):
        adapter._list("trashed=false")
    assert request.calls == 2


def test_access_token_401_refreshes_canonically_and_retries_read_once():
    stale_request = FailingRequest({}, [_http_error(401)])
    stale_service = FakeService([stale_request])
    fresh_service = FakeService([{"files": [{"id": "fresh"}]}])
    refresh_calls = []
    adapter = GoogleDriveComprovanteStorage(
        "stale",
        service=stale_service,
        retry_delays=(0,),
        access_token_refresher=lambda: refresh_calls.append("refresh") or "fresh-token",
        service_factory=lambda token: fresh_service,
    )
    assert adapter._list("trashed=false") == [{"id": "fresh"}]
    assert stale_request.calls == 1
    assert refresh_calls == ["refresh"]


def test_second_provider_401_fails_without_second_refresh_attempt():
    stale_request = FailingRequest({}, [_http_error(401)])
    second_request = FailingRequest({}, [_http_error(401)])
    stale_service = FakeService([stale_request])
    second_service = FakeService([second_request])
    refresh_calls = []
    adapter = GoogleDriveComprovanteStorage(
        "stale",
        service=stale_service,
        retry_delays=(0,),
        access_token_refresher=lambda: refresh_calls.append("refresh") or "fresh-token",
        service_factory=lambda token: second_service,
    )
    with pytest.raises(StorageError) as captured:
        adapter._list("trashed=false")
    assert captured.value.code == "AUTH_RECONNECT_REQUIRED"
    assert refresh_calls == ["refresh"]
    assert stale_request.calls == second_request.calls == 1
