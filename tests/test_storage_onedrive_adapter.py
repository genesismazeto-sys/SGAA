# coding: utf-8
"""The OneDrive managed storage against a strict fake Microsoft Graph.

OneDrive has no per-file application properties, so a document's identity is
its name under its managed folder and every create uses
``conflictBehavior=fail``.  These nodes prove the consequences the mirror
worker relies on: a re-upload and a lost race adopt the existing item, a
different file under the same name surfaces as a different SHA-256 (the worker
then refuses it), and folders are found, not duplicated.

The fake validates the query strings the real service receives and answers like
the connected OneDrive for Business account: a ``$select`` naming the
``@microsoft.graph.downloadUrl`` annotation is refused (the production
read-back failure), and ``/content`` answers 302 with the pre-authorized
address in ``Location``.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from app.storage.contracts import StorageAuthorizationError, StorageError
from app.storage.onedrive import GRAPH, OneDriveManagedObjectStorage, safe_name

DOWNLOAD_HOST = "tenant-my.sharepoint.example"


class _Response:
    def __init__(self, status: int, payload=None, content: bytes = b"", headers=None) -> None:
        self.status_code = status
        self._payload = payload
        self._content = content
        self.headers = dict(headers or {})

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def iter_content(self, _size):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeGraph:
    """``/me/drive``: path addressing, children, simple upload, ``/content`` redirects, strict queries."""

    _PROPERTIES = {"id", "name", "size", "file", "folder", "parentReference"}

    def __init__(self) -> None:
        self.items = {"root": {"id": "root", "name": "root", "folder": {}, "parent": None}}
        self.content: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.downloads: list[dict] = []
        self.plant_before_put: tuple[str, bytes] | None = None
        self.unauthorized_once = False
        self.refuse_next_put = False

    def _child(self, parent: str, name: str):
        return next((item for item in self.items.values() if item["parent"] == parent and item["name"] == name), None)

    def _add(self, parent: str, name: str, *, data: bytes | None = None) -> dict:
        item_id = f"01{len(self.items):032d}"  # OneDrive for Business: 34 alphanumeric characters
        item = {"id": item_id, "name": name, "parent": parent, **({"folder": {}} if data is None else {"file": {}})}
        self.items[item_id] = item
        if data is not None:
            self.content[item_id] = data
        return item

    def _view(self, item) -> dict:
        view = {"id": item["id"], "name": item["name"], "parentReference": {"id": item["parent"]}}
        view.update({k: item[k] for k in ("folder", "file") if k in item})
        if "file" in item:
            view["size"] = len(self.content[item["id"]])
        return view

    def request(self, method, url, *, headers, timeout, allow_redirects, json=None, data=None):
        assert allow_redirects is False and headers["Authorization"].startswith("Bearer ")
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        path = unquote(parts.path)[len(urlsplit(GRAPH).path):]
        self.calls.append((method, path + ("?" + parts.query if parts.query else "")))
        if self.unauthorized_once:
            self.unauthorized_once = False
            return _Response(401)
        selected = set(",".join(query.pop("$select", [])).split(",")) - {""}
        if selected - self._PROPERTIES:  # the annotation is not a selectable property: the production refusal
            return _Response(400, {"error": {"code": "invalidRequest"}})
        base = path.replace("/me/drive/root", "/me/drive/items/root")
        if method == "PUT" and base.endswith(":/content"):
            assert query == {"@microsoft.graph.conflictBehavior": ["fail"]}
            if self.refuse_next_put:
                self.refuse_next_put = False
                return _Response(400, {"error": {"code": "invalidRequest"}})
            parent, name = base[len("/me/drive/items/"):-len(":/content")].split(":/", 1)
            if self.plant_before_put is not None:  # another pass won the race meanwhile
                self._add(parent, name, data=self.plant_before_put[1])
                self.plant_before_put = None
            if self._child(parent, name) is not None:
                return _Response(409)
            return _Response(201, self._view(self._add(parent, name, data=data)))
        assert not query, f"unexpected query {parts.query}"
        if method == "GET" and base.startswith("/me/drive/items/") and ":/" in base:
            parent, name = base[len("/me/drive/items/"):].split(":/", 1)
            found = self._child(parent, name)
            return _Response(404) if found is None else _Response(200, self._view(found))
        if method == "GET" and base.endswith("/content"):
            item_id = base[len("/me/drive/items/"):-len("/content")]
            if item_id not in self.content:
                return _Response(404)
            return _Response(302, headers={"Location": f"https://{DOWNLOAD_HOST}/download.aspx?item={item_id}"})
        if method == "GET" and base.startswith("/me/drive/items/"):
            return _Response(200, self._view(self.items[base[len("/me/drive/items/"):]]))
        if method == "POST" and base.endswith("/children"):
            assert json["@microsoft.graph.conflictBehavior"] == "fail"
            parent = base[len("/me/drive/items/"):-len("/children")]
            if self._child(parent, json["name"]) is not None:
                return _Response(409)
            return _Response(201, self._view(self._add(parent, json["name"])))
        raise AssertionError(f"unexpected Graph call {method} {path}")

    def get(self, url, *, timeout, stream, allow_redirects, **kwargs):
        parts = urlsplit(url)
        self.downloads.append({"host": parts.hostname, "credential": "headers" in kwargs or "auth" in kwargs})
        assert parts.hostname == DOWNLOAD_HOST
        return _Response(200, content=self.content[parse_qs(parts.query)["item"][0]])


@pytest.fixture
def graph():
    return FakeGraph()


def _storage(graph, refresher=None):
    return OneDriveManagedObjectStorage("token", session=graph, access_token_refresher=refresher)


def _folder(storage):
    return storage.ensure_folder(parent_id="root", kind="domain_root", semantic_id="x", display_name="ARQUIVOS")


def _upload(storage, parent, content, name="REQ-000001__Atividade__v1.pdf"):
    return storage.upload(parent_id=parent, stored_filename=name, content=content, mime_type="application/pdf",
                          operation_key="op", object_kind="comprovante", semantic_properties={})


def test_the_production_read_back_request_is_the_refused_pattern_and_carries_a_coded_diagnostic(graph):
    """What 86cb6cb sent after the upload: a metadata ``$select`` naming the download annotation.

    The account refused it; the worker recorded only ``STORAGE_ERROR`` (the plain StorageError).  The same
    refusal now carries the phase and the status -- and no address, id or body."""
    storage = _storage(graph)
    with pytest.raises(StorageError) as caught:
        storage._call("GET", "/me/drive/items/01X?$select=id,size,file,@microsoft.graph.downloadUrl",
                      phase="METADATA")
    assert type(caught.value) is StorageError
    assert caught.value.code == "ONEDRIVE_METADATA_HTTP_400"
    assert "01X" not in str(caught.value) and "graph" not in str(caught.value).lower()


def test_the_read_back_follows_the_content_redirect_without_any_credential(graph):
    storage = _storage(graph)
    content = b"%PDF-1.4 document"

    remote = _upload(storage, _folder(storage), content)

    assert remote.sha256 == hashlib.sha256(content).hexdigest() and remote.size == len(content)
    assert ("GET", f"/me/drive/items/{remote.file_id}/content") in graph.calls
    assert not any("downloadUrl" in path for _method, path in graph.calls)
    assert graph.downloads == [{"host": DOWNLOAD_HOST, "credential": False}]


def test_the_large_file_address_and_size_come_from_metadata_and_the_content_redirect(graph):
    storage = _storage(graph)
    remote = _upload(storage, _folder(storage), b"%PDF-1.4 large document")

    url, size = storage.download_url(remote.file_id)

    assert urlsplit(url).hostname == DOWNLOAD_HOST and size == len(b"%PDF-1.4 large document")


def test_a_refused_upload_is_recorded_with_its_phase_and_status(graph):
    storage = _storage(graph)
    folder = _folder(storage)
    graph.refuse_next_put = True

    with pytest.raises(StorageError) as caught:
        _upload(storage, folder, b"%PDF-1.4 document")

    assert caught.value.code == "ONEDRIVE_UPLOAD_HTTP_400" and graph.content == {}


def test_folders_follow_the_conventions_and_are_found_not_duplicated(graph):
    storage = _storage(graph)
    first = storage.ensure_folder(parent_id="root", kind="product_root", semantic_id="sgaa", display_name="SGAA")
    again = storage.ensure_folder(parent_id="root", kind="product_root", semantic_id="sgaa", display_name="SGAA")
    student = storage.ensure_folder(parent_id=first, kind="student", semantic_id="1",
                                    display_name='MAT-1 - Aluno: "Sintético"?')
    assert first == again and len([i for i in graph.items.values() if "folder" in i]) == 3
    assert graph.items[student]["name"] == safe_name('MAT-1 - Aluno: "Sintético"?') == "MAT-1 - Aluno- -Sintético--"


def test_a_repeated_upload_adopts_the_existing_file_with_its_read_back_digest(graph):
    storage = _storage(graph)
    folder = _folder(storage)
    content = b"%PDF-1.4 document"

    created = _upload(storage, folder, content)
    repeated = _upload(storage, folder, content)

    assert (created.reused, repeated.reused, created.file_id) == (False, True, repeated.file_id)
    assert created.sha256 == repeated.sha256 == hashlib.sha256(content).hexdigest()
    assert created.parent_id == folder and len(graph.content) == 1


def test_a_lost_race_adopts_the_winner_and_a_foreign_file_shows_its_own_digest(graph):
    storage = _storage(graph)
    folder = _folder(storage)
    graph.plant_before_put = ("REQ-000001__Atividade__v1.pdf", b"%PDF-1.4 document")

    adopted = _upload(storage, folder, b"%PDF-1.4 document")
    assert adopted.reused and len(graph.content) == 1

    foreign = _upload(storage, folder, b"%PDF-1.4 a different document")
    assert foreign.reused and foreign.sha256 == hashlib.sha256(b"%PDF-1.4 document").hexdigest()
    assert len(graph.content) == 1  # never a second file under the same name


def test_an_expired_token_is_refreshed_once_and_a_refused_refresh_is_an_authorization_error(graph):
    graph.unauthorized_once = True
    refreshed = []
    storage = _storage(graph, refresher=lambda: refreshed.append(1) or "fresh")
    storage.ensure_folder(parent_id="root", kind="product_root", semantic_id="sgaa", display_name="SGAA")
    assert refreshed == [1]

    graph.unauthorized_once = True
    with pytest.raises(StorageAuthorizationError):
        _storage(graph, refresher=lambda: "").ensure_folder(
            parent_id="root", kind="product_root", semantic_id="sgaa", display_name="SGAA")
