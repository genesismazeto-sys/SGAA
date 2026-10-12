"""OAuth 2.0 PKCE and cloud drive upload/retention for Google Drive and OneDrive.

All HTTP calls use only the standard library (urllib) to avoid new dependencies.
"""

import base64
import datetime
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

from app.cloud_config import get_google_oauth_config, get_onedrive_oauth_config

UTC = datetime.timezone.utc


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge_S256) for OAuth PKCE flow."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def token_expires_at(expires_in: int) -> str:
    """ISO-8601 UTC expiry timestamp, 60 s before the real deadline."""
    expiry = datetime.datetime.now(UTC) + datetime.timedelta(seconds=max(0, int(expires_in)) - 60)
    return expiry.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_token_expired(expires_at_iso: str) -> bool:
    if not expires_at_iso:
        return True
    try:
        expiry = datetime.datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00"))
        return datetime.datetime.now(UTC) >= expiry
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# Internal HTTP helpers
# ---------------------------------------------------------------------------

def _post_form(url: str, fields: dict) -> dict:
    """POST application/x-www-form-urlencoded, return parsed JSON."""
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()) or {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc


def _api(
    url: str,
    *,
    method: str = "GET",
    token: str,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: int = 60,
) -> dict | None:
    """Authenticated API request. Returns parsed JSON or None (empty/204 body)."""
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return None  # No Content is success for DELETE
        raise RuntimeError(f"HTTP {exc.code}") from exc


# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------

_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE = "https://oauth2.googleapis.com/revoke"
_GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v3/userinfo"
_GOOGLE_FILES = "https://www.googleapis.com/drive/v3/files"
_GOOGLE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
_GOOGLE_SCOPE_DEFAULT = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/userinfo.email openid"


def _google_scope_value() -> str:
    return get_google_oauth_config()["scopes"] or _GOOGLE_SCOPE_DEFAULT


def google_auth_url(client_id: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    return _GOOGLE_AUTH + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _google_scope_value(),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",  # forces refresh_token to be returned
    })


def google_exchange(
    client_id: str, client_secret: str, code: str, redirect_uri: str, code_verifier: str
) -> dict:
    data: dict = {
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    if client_secret:
        data["client_secret"] = client_secret
    return _post_form(_GOOGLE_TOKEN, data)


def google_refresh(client_id: str, client_secret: str, refresh_token: str) -> dict:
    data: dict = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    if client_secret:
        data["client_secret"] = client_secret
    return _post_form(_GOOGLE_TOKEN, data)


def google_userinfo(access_token: str) -> dict:
    return _api(_GOOGLE_USERINFO, token=access_token) or {}


def google_revoke(token: str) -> None:
    url = f"{_GOOGLE_REVOKE}?token={urllib.parse.quote(token)}"
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except urllib.error.HTTPError:
        pass  # best-effort: ignore errors (token may already be expired)


def _google_ensure_folder(token: str, folder_path: str) -> str:
    """Walk/create nested folder path in Drive, return the leaf folder ID."""
    parts = [p for p in folder_path.strip("/").split("/") if p]
    parent_id = "root"
    for part in parts:
        q = (
            f"name='{part}' and mimeType='application/vnd.google-apps.folder'"
            f" and '{parent_id}' in parents and trashed=false"
        )
        url = f"{_GOOGLE_FILES}?q={urllib.parse.quote(q)}&fields=files(id)"
        result = _api(url, token=token) or {}
        files = result.get("files") or []
        if files:
            parent_id = files[0]["id"]
        else:
            body = json.dumps({
                "name": part,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }).encode()
            created = _api(
                _GOOGLE_FILES, method="POST", token=token,
                body=body, content_type="application/json",
            ) or {}
            parent_id = created["id"]
    return parent_id


def google_upload(token: str, file_path: str, dest_folder: str) -> dict:
    """Upload a file to Google Drive via multipart upload. Returns file metadata."""
    folder_id = _google_ensure_folder(token, dest_folder or "Backups")
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as fh:
        file_bytes = fh.read()
    boundary = f"gupload-{secrets.token_hex(12)}"
    metadata = json.dumps({"name": filename, "parents": [folder_id]}).encode()
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
        + metadata + b"\r\n"
        + f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
        + file_bytes + b"\r\n"
        + f"--{boundary}--".encode()
    )
    return _api(
        _GOOGLE_UPLOAD, method="POST", token=token, body=body,
        content_type=f"multipart/related; boundary={boundary}", timeout=120,
    ) or {}


def google_list_db_files(token: str, dest_folder: str) -> list[dict]:
    """List .db files in dest_folder. Returns list of {id, name, createdTime}."""
    try:
        folder_id = _google_ensure_folder(token, dest_folder or "Backups")
    except RuntimeError:
        return []
    q = f"'{folder_id}' in parents and trashed=false and name contains '.db'"
    url = (
        f"{_GOOGLE_FILES}?q={urllib.parse.quote(q)}"
        f"&fields=files(id,name,createdTime)&orderBy=createdTime&pageSize=200"
    )
    result = _api(url, token=token) or {}
    return result.get("files") or []


def google_delete_file(token: str, file_id: str) -> None:
    _api(f"{_GOOGLE_FILES}/{file_id}", method="DELETE", token=token)


def _download(url: str, path: str, headers: dict | None = None) -> None:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=120) as response, open(path, "wb") as handle:
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            handle.write(chunk)


def google_download_to(token: str, file_id: str, path: str) -> None:
    """Write the bytes of a Drive file to ``path`` (server side, with the account's token)."""
    _download(f"{_GOOGLE_FILES}/{urllib.parse.quote(file_id, safe='')}?alt=media", path,
              {"Authorization": f"Bearer {token}"})


def onedrive_download_to(token: str, item_id: str, path: str, *, drive_id: str | None = None) -> None:
    """Write the bytes of a OneDrive file to ``path`` through Graph's pre-authorized address."""
    address = onedrive_download_url(token, item_id, drive_id=drive_id)
    if not address:
        raise RuntimeError("Graph returned no download address")
    _download(address, path)


def google_download_link(token: str, file_id: str) -> str:
    """The file's download link (served to the Google account signed in on the browser)."""
    url = f"{_GOOGLE_FILES}/{urllib.parse.quote(file_id, safe='')}?fields=webContentLink"
    result = _api(url, token=token) or {}
    return str(result.get("webContentLink") or "")


#: A folder listing follows the provider's continuation up to this many pages.  A shorter listing only
#: ever lets retention delete less: every file it would delete is older than the ones it keeps.
LISTING_MAX_PAGES = 50


def google_list_folder_files(token: str, folder_id: str, name_prefix: str) -> list[dict]:
    """Files directly in the folder ``folder_id`` whose name starts with ``name_prefix``: {id, name}."""
    # Filtered here, not by Drive's word-based ``contains``: only exact name prefixes ever qualify.
    q = f"'{folder_id}' in parents and trashed=false"
    base = f"{_GOOGLE_FILES}?q={urllib.parse.quote(q)}&fields=nextPageToken,files(id,name)&orderBy=name%20desc&pageSize=1000"
    found, token_page = [], None
    for _page in range(LISTING_MAX_PAGES):  # every page (A19 R3 N3); bounded
        url = base + (f"&pageToken={urllib.parse.quote(token_page, safe='')}" if token_page else "")
        result = _api(url, token=token) or {}
        found += [f for f in (result.get("files") or []) if str(f.get("name") or "").startswith(name_prefix)]
        token_page = result.get("nextPageToken")
        if not token_page:
            break
    return found


# ---------------------------------------------------------------------------
# OneDrive (Microsoft Graph)
# ---------------------------------------------------------------------------

_GRAPH = "https://graph.microsoft.com/v1.0"
_ONEDRIVE_SCOPE = "Files.ReadWrite offline_access User.Read"


def _onedrive_tenant() -> str:
    tenant = get_onedrive_oauth_config()["tenant_id"] or "common"
    return tenant


def _onedrive_auth_endpoint() -> str:
    return f"https://login.microsoftonline.com/{_onedrive_tenant()}/oauth2/v2.0/authorize"


def _onedrive_token_endpoint() -> str:
    return f"https://login.microsoftonline.com/{_onedrive_tenant()}/oauth2/v2.0/token"


def onedrive_auth_url(client_id: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    return _onedrive_auth_endpoint() + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _ONEDRIVE_SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })


def onedrive_exchange(client_id: str, code: str, redirect_uri: str, code_verifier: str) -> dict:
    return _post_form(_onedrive_token_endpoint(), {
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
        "scope": _ONEDRIVE_SCOPE,
    })


def onedrive_refresh(client_id: str, refresh_token: str) -> dict:
    return _post_form(_onedrive_token_endpoint(), {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": _ONEDRIVE_SCOPE,
    })


def onedrive_userinfo(access_token: str) -> dict:
    return _api(f"{_GRAPH}/me", token=access_token) or {}


def onedrive_upload(token: str, file_path: str, dest_folder: str) -> dict:
    """Upload file via OneDrive Graph API PUT. Returns item metadata."""
    filename = os.path.basename(file_path)
    folder = (dest_folder or "Backups").strip("/")
    encoded_folder = urllib.parse.quote(folder)
    encoded_name = urllib.parse.quote(filename)
    url = f"{_GRAPH}/me/drive/root:/{encoded_folder}/{encoded_name}:/content"
    with open(file_path, "rb") as fh:
        data = fh.read()
    return _api(
        url, method="PUT", token=token, body=data,
        content_type="application/octet-stream", timeout=120,
    ) or {}


def onedrive_list_db_files(token: str, dest_folder: str) -> list[dict]:
    """List .db files in dest_folder. Returns list of {id, name, createdDateTime}."""
    folder = (dest_folder or "Backups").strip("/")
    url = (
        f"{_GRAPH}/me/drive/root:/{urllib.parse.quote(folder)}:/children"
        f"?$select=id,name,createdDateTime&$top=200"
    )
    try:
        result = _api(url, token=token) or {}
    except RuntimeError:
        return []
    return [f for f in (result.get("value") or []) if (f.get("name") or "").endswith(".db")]


def onedrive_delete_file(token: str, item_id: str) -> None:
    _api(f"{_GRAPH}/me/drive/items/{item_id}", method="DELETE", token=token)


def onedrive_download_url(token: str, item_id: str, *, drive_id: str | None = None) -> str:
    """Graph's short-lived, pre-authorized download address of a file (no token in the browser), in the
    drive the receipt names (A19 R3 M5; the signed-in user's own drive when it names none)."""
    url = (f"{_onedrive_drive_base(drive_id)}/items/{urllib.parse.quote(item_id, safe='')}"
           "?$select=id,@microsoft.graph.downloadUrl")
    result = _api(url, token=token) or {}
    return str(result.get("@microsoft.graph.downloadUrl") or "")


def _onedrive_drive_base(drive_id: str | None) -> str:
    return f"{_GRAPH}/drives/{urllib.parse.quote(drive_id, safe='')}" if drive_id else f"{_GRAPH}/me/drive"


def onedrive_list_folder_children(token: str, *, folder_id: str | None, drive_id: str | None,
                                  folder_path: str) -> list[dict]:
    """Children of the chosen folder (by id; ``root``), else of ``folder_path`` from the root: {id, name}."""
    base = _onedrive_drive_base(drive_id)
    if folder_id and folder_id.lower() != "root":
        url = f"{base}/items/{urllib.parse.quote(folder_id, safe='')}/children"
    elif folder_id:
        url = f"{base}/root/children"
    else:
        url = f"{base}/root:/{urllib.parse.quote(folder_path.strip('/'))}:/children"
    found, url = [], f"{url}?$select=id,name&$top=200"
    for _page in range(LISTING_MAX_PAGES):  # every page (A19 R3 N3); bounded
        result = _api(url, token=token) or {}
        found += result.get("value") or []
        following = str(result.get("@odata.nextLink") or "")
        if not following.startswith(_GRAPH + "/"):  # only Graph's own continuation address
            break
        url = following
    return found


def onedrive_delete_item(token: str, item_id: str, *, drive_id: str | None = None) -> None:
    _api(f"{_onedrive_drive_base(drive_id)}/items/{urllib.parse.quote(item_id, safe='')}", method="DELETE",
         token=token)


# ---------------------------------------------------------------------------
# Shared: token refresh (reads client credentials from environment)
# ---------------------------------------------------------------------------

def refresh_google_if_needed(settings: dict) -> tuple[str, dict | None]:
    """Return (access_token, updated_fields_or_None). Refreshes silently if expired."""
    token = settings.get("gdrive_access_token") or ""
    if not is_token_expired(settings.get("gdrive_expires_at") or ""):
        return token, None
    config = get_google_oauth_config()
    client_id = config["client_id"]
    client_secret = config["client_secret"]
    refresh_tok = settings.get("gdrive_refresh_token") or ""
    if not refresh_tok or not client_id:
        raise RuntimeError("Google Drive: GOOGLE_CLIENT_ID ou refresh_token ausente.")
    resp = google_refresh(client_id, client_secret, refresh_tok)
    new_token = resp.get("access_token") or ""
    updates: dict = {
        "gdrive_access_token": new_token,
        "gdrive_expires_at": token_expires_at(int(resp.get("expires_in") or 3600)),
    }
    if resp.get("refresh_token"):
        updates["gdrive_refresh_token"] = resp["refresh_token"]
    return new_token, updates


def refresh_onedrive_if_needed(settings: dict) -> tuple[str, dict | None]:
    token = settings.get("onedrive_access_token") or ""
    if not is_token_expired(settings.get("onedrive_expires_at") or ""):
        return token, None
    client_id = get_onedrive_oauth_config()["client_id"]
    refresh_tok = settings.get("onedrive_refresh_token") or ""
    if not refresh_tok or not client_id:
        raise RuntimeError("OneDrive: ONEDRIVE_CLIENT_ID ou refresh_token ausente.")
    resp = onedrive_refresh(client_id, refresh_tok)
    new_token = resp.get("access_token") or ""
    updates: dict = {
        "onedrive_access_token": new_token,
        "onedrive_expires_at": token_expires_at(int(resp.get("expires_in") or 3600)),
    }
    if resp.get("refresh_token"):
        updates["onedrive_refresh_token"] = resp["refresh_token"]
    return new_token, updates


# ---------------------------------------------------------------------------
# Shared: remote retention policy
# ---------------------------------------------------------------------------

def apply_retention_to_drive(
    provider: str,
    *,
    token: str,
    dest_folder: str,
    policy: list[dict],
    logger=None,
) -> dict:
    """List remote .db files and delete excess according to the GFS retention policy."""
    now = datetime.datetime.now(UTC)

    if provider == "google":
        raw = google_list_db_files(token, dest_folder)
        files = [{"id": f.get("id"), "name": f.get("name"), "_ts": f.get("createdTime")} for f in raw]
    elif provider == "onedrive":
        raw = onedrive_list_db_files(token, dest_folder)
        files = [{"id": f.get("id"), "name": f.get("name"), "_ts": f.get("createdDateTime")} for f in raw]
    else:
        return {"deleted": [], "errors": [f"Provedor desconhecido: {provider}"]}

    parsed: list[dict] = []
    for f in files:
        ts = (f.get("_ts") or "").replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(ts)
        except ValueError:
            continue
        parsed.append({**f, "_dt": dt})
    parsed.sort(key=lambda x: x["_dt"], reverse=True)

    kept: set[str] = set()
    for window in policy:
        try:
            period_h = float(window["period_hours"])
            interval_h = float(window["interval_hours"])
            slots = int(window["slots"])
        except (KeyError, TypeError, ValueError):
            continue
        if interval_h <= 0 or slots <= 0:
            continue
        cutoff = now - datetime.timedelta(hours=period_h)
        buckets: dict[int, dict] = {}
        for f in parsed:
            if f["_dt"] < cutoff:
                continue
            age_h = (now - f["_dt"]).total_seconds() / 3600.0
            bidx = int(age_h / interval_h)
            if bidx not in buckets:
                buckets[bidx] = f
        for i, (_, f) in enumerate(sorted(buckets.items())):
            if i >= slots:
                break
            if f.get("id"):
                kept.add(f["id"])

    deleted: list[str] = []
    errors: list[str] = []
    for f in parsed:
        fid = f.get("id")
        if not fid or fid in kept:
            continue
        try:
            if provider == "google":
                google_delete_file(token, fid)
            else:
                onedrive_delete_file(token, fid)
            deleted.append(f.get("name") or fid)
            if logger:
                logger.info("Retenção remota [%s]: %s removido.", provider, f.get("name") or fid)
        except Exception as exc:
            errors.append(str(exc))

    return {"deleted": deleted, "errors": errors}
