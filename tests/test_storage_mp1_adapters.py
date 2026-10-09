# coding: utf-8
"""MP-1 slice 2: the two adapter read surfaces the cross-check needs (mocked HTTP boundary).

* ``SupabaseObjectStore.list_objects`` -- ``POST /storage/v1/object/list/{bucket}``,
  one folder level per request (an entry without ``id`` is a folder), paged by
  ``offset``; recursive, bounded, sanitized errors, secret only as ``apikey``.
* ``GoogleDriveManagedObjectStorage.describe_file`` -- ``files.get`` by id;
  ``None`` for a missing (404) or trashed file; transient errors retried and
  translated; an expired authorization refreshed once.

Live provider proof is the E-LIVE lane (``docs/specs/MP-1-storage-convergence.md`` §11).
"""

from __future__ import annotations

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from app.storage import supabase_store
from app.storage.contracts import RemoteObject, StorageError, StorageTransientError
from app.storage.google_drive import GoogleDriveManagedObjectStorage
from app.storage.object_store import (
    STORAGE_AUTH_FAILURE,
    STORAGE_INVALID_LOCATOR,
    STORAGE_INVALID_RESPONSE,
    CanonicalStoreError,
    ListedObject,
)
from app.storage.supabase_store import SupabaseObjectStore, SupabaseStorageConfig
from tests.canonical_store_fake import InMemoryObjectStore
from tests.storage_s3a_support import BUCKET, SUPABASE_URL, TEST_SECRET_KEY

LIST_URL = f"{SUPABASE_URL}/storage/v1/object/list/{BUCKET}"


class _Response:
    def __init__(self, status=200, json=None):
        self.status_code = status
        self._json = json
        self.headers = {}

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _file(name, size=10):
    return {"name": name, "id": f"uuid-{name}", "metadata": {"size": size, "mimetype": "application/pdf"}}


def _folder(name):
    return {"name": name, "id": None, "metadata": None}


class _ListingSession:
    """Answers ``object/list`` from a {folder: [entries]} tree, paging by limit / offset."""

    def __init__(self, tree, *, status=200, answer=None):
        self.tree = tree
        self.status = status
        self.answer = answer
        self.requests = []

    def request(self, method, url, headers=None, json=None, **kwargs):
        self.requests.append((method, url, dict(headers or {}), dict(json or {}), kwargs))
        if self.status != 200:
            return _Response(self.status, json={"statusCode": str(self.status), "error": TEST_SECRET_KEY})
        if self.answer is not None:
            return _Response(json=self.answer)
        entries = self.tree.get(json["prefix"], [])
        return _Response(json=entries[json["offset"]: json["offset"] + json["limit"]])


def _store(session):
    return SupabaseObjectStore(SupabaseStorageConfig(url=SUPABASE_URL, bucket=BUCKET, secret_key=TEST_SECRET_KEY),
                               session=session)


TREE = {
    "": [_folder("arquivos"), _folder("comprovantes"), _file("stray.pdf", 3)],
    "comprovantes": [_folder("2026")],
    "comprovantes/2026": [_folder("10")],
    "comprovantes/2026/10": [_file("a" * 32, 11), _file("b" * 32, 12), _file("c" * 32, 13)],
    "arquivos": [_file("x" * 32, None)],
}


def test_listing_walks_folders_and_pages(monkeypatch):
    monkeypatch.setattr(supabase_store, "LIST_PAGE_SIZE", 2)
    session = _ListingSession(TREE)

    listed = _store(session).list_objects(BUCKET, max_objects=100)

    assert sorted(listed, key=lambda item: item.key) == [
        ListedObject("arquivos/" + "x" * 32, None),
        ListedObject("comprovantes/2026/10/" + "a" * 32, 11),
        ListedObject("comprovantes/2026/10/" + "b" * 32, 12),
        ListedObject("comprovantes/2026/10/" + "c" * 32, 13),
        ListedObject("stray.pdf", 3),
    ]
    bodies = [body for _m, _u, _h, body, _k in session.requests]
    assert {(body["prefix"], body["offset"]) for body in bodies} >= {
        ("", 0), ("", 2), ("comprovantes/2026/10", 0), ("comprovantes/2026/10", 2)}
    assert all(body["limit"] == 2 and body["sortBy"] == {"column": "name", "order": "asc"} for body in bodies)
    for method, url, headers, _body, kwargs in session.requests:
        assert (method, url) == ("POST", LIST_URL)
        assert headers == {"apikey": TEST_SECRET_KEY}
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] == supabase_store.HTTP_TIMEOUT


def test_listing_from_a_prefix_lists_only_below_it():
    listed = _store(_ListingSession(TREE)).list_objects(BUCKET, "comprovantes/", max_objects=100)
    assert {item.key.split("/")[0] for item in listed} == {"comprovantes"} and len(listed) == 3


def test_a_service_returning_short_pages_is_read_to_the_end(monkeypatch):
    monkeypatch.setattr(supabase_store, "LIST_PAGE_SIZE", 3)
    tree = {"": [_file(f"f{index}") for index in range(5)]}

    class _CappedSession(_ListingSession):
        def request(self, method, url, headers=None, json=None, **kwargs):  # serves at most 2 per page
            response = super().request(method, url, headers=headers, json=json, **kwargs)
            return _Response(json=response._json[:2])

    listed = _store(_CappedSession(tree)).list_objects(BUCKET, max_objects=100)
    assert sorted(item.key for item in listed) == [f"f{index}" for index in range(5)]


def test_a_service_ignoring_the_offset_cannot_loop_forever(monkeypatch):
    monkeypatch.setattr(supabase_store, "LIST_MAX_REQUESTS", 5)
    with pytest.raises(CanonicalStoreError) as caught:
        _store(_ListingSession({}, answer=[_folder("loop")])).list_objects(BUCKET, max_objects=100)
    assert caught.value.detail in ("listing_requests", "listing_depth")
    with pytest.raises(CanonicalStoreError) as caught:
        _store(_ListingSession({}, answer=[_file("same")])).list_objects(BUCKET, max_objects=10_000)
    assert caught.value.detail == "listing_requests"


def test_listing_is_bounded_never_truncated():
    with pytest.raises(CanonicalStoreError) as caught:
        _store(_ListingSession(TREE)).list_objects(BUCKET, max_objects=2)
    assert (caught.value.code, caught.value.detail) == (STORAGE_INVALID_RESPONSE, "listing_bound")


def test_listing_depth_is_bounded(monkeypatch):
    monkeypatch.setattr(supabase_store, "LIST_MAX_DEPTH", 1)
    with pytest.raises(CanonicalStoreError) as caught:
        _store(_ListingSession(TREE)).list_objects(BUCKET, max_objects=100)
    assert caught.value.detail == "listing_depth"


@pytest.mark.parametrize("answer", [{"not": "a list"}, [{"id": "x"}], [{"name": "a/b", "id": "x"}], ["text"]])
def test_malformed_listing_is_refused(answer):
    with pytest.raises(CanonicalStoreError) as caught:
        _store(_ListingSession({}, answer=answer)).list_objects(BUCKET, max_objects=100)
    assert caught.value.code == STORAGE_INVALID_RESPONSE


def test_listing_errors_are_sanitized():
    with pytest.raises(CanonicalStoreError) as caught:
        _store(_ListingSession({}, status=403)).list_objects(BUCKET, max_objects=100)
    assert caught.value.code == STORAGE_AUTH_FAILURE and TEST_SECRET_KEY not in str(caught.value)
    with pytest.raises(CanonicalStoreError) as caught:
        _store(_ListingSession({})).list_objects("Bad Bucket", max_objects=100)
    assert caught.value.code == STORAGE_INVALID_LOCATOR


def test_fake_listing_matches_the_adapter_contract():
    store = InMemoryObjectStore()
    store.objects[(BUCKET, "comprovantes/2026/10/" + "a" * 32)] = (b"abc", "application/pdf")
    store.objects[(BUCKET, "arquivos/2026/10/" + "b" * 32)] = (b"abcd", "application/pdf")
    store.objects[("other", "comprovantes/x")] = (b"z", "application/pdf")
    assert store.list_objects(BUCKET, max_objects=10) == [
        ListedObject("arquivos/2026/10/" + "b" * 32, 4), ListedObject("comprovantes/2026/10/" + "a" * 32, 3)]
    assert store.list_objects(BUCKET, "comprovantes", max_objects=10) == [
        ListedObject("comprovantes/2026/10/" + "a" * 32, 3)]
    with pytest.raises(CanonicalStoreError):
        store.list_objects(BUCKET, max_objects=1)


# ---------------------------------------------------------------------------
# Drive describe_file
# ---------------------------------------------------------------------------


def _http_error(status):
    return HttpError(Response({"status": status}), b"provider detail")


class _GetRequest:
    def __init__(self, outcomes):
        self.outcomes = outcomes

    def execute(self, num_retries=0):
        assert num_retries == 0
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _Files:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.gets = []

    def get(self, **kwargs):
        self.gets.append(kwargs)
        return _GetRequest(self.outcomes)


class _Service:
    def __init__(self, outcomes):
        self._files = _Files(outcomes)

    def files(self):
        return self._files


PAYLOAD = {"id": "drvfile1", "name": "doc.pdf", "parents": ["drvparent1"], "size": "10",
           "sha256Checksum": "a" * 64, "trashed": False}


def _drive(outcomes, **kwargs):
    service = _Service(outcomes)
    return GoogleDriveManagedObjectStorage("token", service=service, retry_delays=(0, 0), **kwargs), service


def test_describe_file_returns_metadata():
    drive, service = _drive([PAYLOAD])
    assert drive.describe_file("drvfile1") == RemoteObject("drvfile1", "drvparent1", "doc.pdf", 10, "a" * 64, True)
    assert service.files().gets[0]["fileId"] == "drvfile1" and service.files().gets[0]["supportsAllDrives"] is True
    assert "sha256Checksum" in service.files().gets[0]["fields"] and "trashed" in service.files().gets[0]["fields"]


@pytest.mark.parametrize("outcome", [_http_error(404), {**PAYLOAD, "trashed": True}])
def test_describe_missing_or_trashed_file_is_none(outcome):
    drive, _service = _drive([outcome])
    assert drive.describe_file("drvfile1") is None


@pytest.mark.parametrize("outcome", [{}, {**PAYLOAD, "id": "otherfile"}, ["not", "a", "dict"]])
def test_describe_with_a_malformed_answer_is_a_failed_check(outcome):
    drive, _service = _drive([outcome])
    with pytest.raises(StorageError):
        drive.describe_file("drvfile1")


def test_describe_retries_transient_errors_then_fails_sanitized():
    drive, _service = _drive([_http_error(503), PAYLOAD])
    assert drive.describe_file("drvfile1").file_id == "drvfile1"
    drive, _service = _drive([_http_error(503)] * 3)
    with pytest.raises(StorageTransientError) as caught:
        drive.describe_file("drvfile1")
    assert "provider detail" not in str(caught.value)
    drive, _service = _drive([_http_error(403)])
    with pytest.raises(StorageError):
        drive.describe_file("drvfile1")


def test_describe_refreshes_an_expired_authorization_once():
    refreshed = []
    drive, _service = _drive([_http_error(401)], access_token_refresher=lambda: refreshed.append(1) or "fresh",
                             service_factory=lambda token: _Service([PAYLOAD]))
    assert drive.describe_file("drvfile1").file_id == "drvfile1"
    assert refreshed == [1]
