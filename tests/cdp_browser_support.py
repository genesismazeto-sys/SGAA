"""Drive a real headless Chromium against the Flask test client -- no app port.

Browser-level contracts (a trusted Enter keypress, implicit form submission,
what a page really POSTs) cannot be proven from rendered HTML alone. SGAA has
exactly one application port (5000) and it belongs to the user's runtime, so
this helper never starts an HTTP server for the app. Instead Chromium's own
DevTools ``Fetch`` domain pauses every request the page makes and this module
answers it from ``app.test_client()``, against whatever isolated database the
calling test configured. Chromium's DevTools socket is a debugging channel on
an OS-assigned port, not an SGAA runtime.

Standard library only: a minimal RFC 6455 client is enough for CDP.
"""
from __future__ import annotations

import base64
import glob
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

BASE_URL = "http://localhost"


def _xor(data: bytes, mask: bytes) -> bytes:
    n = len(data)
    if not n:
        return data
    key = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(key, "big")).to_bytes(n, "big")


def find_chromium() -> str | None:
    override = os.environ.get("SGAA_CHROMIUM")
    if override and Path(override).exists():
        return override
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    patterns = (
        "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe",
        "chromium-*/chrome-win*/chrome.exe",
    )
    for pattern in patterns:
        found = sorted(glob.glob(str(root / pattern)))
        if found:
            return found[-1]
    return None


class _WebSocket:
    def __init__(self, url: str, timeout: float = 30.0):
        assert url.startswith("ws://"), url
        host_port, _, path = url[len("ws://"):].partition("/")
        host, _, port = host_port.partition(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        self.buf = bytearray()
        while b"\r\n\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake closed")
            self.buf += chunk
        head, _, rest = bytes(self.buf).partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(head.decode(errors="replace"))
        self.buf = bytearray(rest)

    def _exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("websocket closed")
            self.buf += chunk
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def send(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += n.to_bytes(2, "big")
        else:
            header.append(0x80 | 127)
            header += n.to_bytes(8, "big")
        mask = os.urandom(4)
        header += mask
        masked = _xor(payload, mask)
        self.sock.sendall(bytes(header) + masked)

    def recv(self, timeout: float) -> str | None:
        self.sock.settimeout(timeout)
        message = bytearray()
        try:
            while True:
                b0, b1 = self._exact(2)
                opcode = b0 & 0x0F
                n = b1 & 0x7F
                if n == 126:
                    n = int.from_bytes(self._exact(2), "big")
                elif n == 127:
                    n = int.from_bytes(self._exact(8), "big")
                mask = self._exact(4) if b1 & 0x80 else None
                data = self._exact(n)
                if mask:
                    data = _xor(data, mask)
                if opcode == 0x9:  # ping
                    self.sock.sendall(bytes([0x8A, 0x80 | len(data)]) + b"\0\0\0\0" + data)
                    continue
                if opcode == 0x8:
                    raise ConnectionError("websocket closed by peer")
                message += data
                if b0 & 0x80:
                    return message.decode("utf-8")
        except socket.timeout:
            if message:
                raise
            return None

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class BrowserSession:
    """One headless page whose every request is served by ``client``.

    ``requests`` records (method, path, body) for each request the page makes,
    so a test can assert that no POST happened at all -- not merely that the
    server refused one.
    """

    def __init__(self, client, binary: str):
        self.client = client
        self.requests: list[tuple[str, str, str]] = []
        self.response_rewrites: dict[str, callable] = {}
        self._profile = tempfile.mkdtemp(prefix="sgaa-cdp-")
        self._proc = subprocess.Popen(
            [
                binary,
                "--headless",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-port=0",
                f"--user-data-dir={self._profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        port_file = Path(self._profile) / "DevToolsActivePort"
        deadline = time.time() + 20
        announced = ""
        while not announced:
            if time.time() > deadline:
                self.close()
                raise RuntimeError("Chromium did not expose DevTools")
            try:
                announced = port_file.read_text().strip()
            except (FileNotFoundError, PermissionError):
                # Windows: Chromium still holds the file open while writing it.
                announced = ""
            if not announced:
                time.sleep(0.05)
        port = int(announced.split()[0])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as fh:
            targets = json.load(fh)
        page = next(t for t in targets if t.get("type") == "page")
        self._ws = _WebSocket(page["webSocketDebuggerUrl"])
        self._next_id = 0
        self._responses: dict[int, dict] = {}
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False},
        )
        self.call("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})

    # ------------------------------------------------------------ protocol
    def send(self, method: str, params: dict | None = None) -> int:
        self._next_id += 1
        self._ws.send(json.dumps({"id": self._next_id, "method": method, "params": params or {}}))
        return self._next_id

    def pump(self, seconds: float) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            self._read_one(max(0.01, deadline - time.time()))

    def _read_one(self, timeout: float) -> None:
        raw = self._ws.recv(timeout)
        if raw is None:
            return
        message = json.loads(raw)
        if "id" in message:
            self._responses[message["id"]] = message
        elif message.get("method") == "Fetch.requestPaused":
            self._serve(message["params"])

    def call(self, method: str, params: dict | None = None, timeout: float = 20.0) -> dict:
        call_id = self.send(method, params)
        deadline = time.time() + timeout
        while call_id not in self._responses:
            if time.time() > deadline:
                raise TimeoutError(method)
            self._read_one(0.2)
        response = self._responses.pop(call_id)
        if "error" in response:
            raise RuntimeError(f"{method}: {response['error']}")
        return response.get("result", {})

    # ------------------------------------------------------------- serving
    def _serve(self, params: dict) -> None:
        request = params["request"]
        request_id = params["requestId"]
        url = request["url"]
        if not url.startswith(BASE_URL + "/"):
            self.send("Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"})
            return
        path = url[len(BASE_URL):]
        method = request["method"]
        body = b""
        if request.get("postDataEntries"):
            body = b"".join(base64.b64decode(e.get("bytes", "")) for e in request["postDataEntries"])
        elif request.get("postData"):
            body = request["postData"].encode("utf-8")
        headers = {
            k: v
            for k, v in request.get("headers", {}).items()
            if k.lower() in {"content-type", "x-csrftoken", "accept", "x-requested-with"}
        }
        self.requests.append((method, path, body.decode("utf-8", errors="replace")))
        response = self.client.open(path, method=method, data=body or None, headers=headers)
        payload = response.get_data()
        rewrite = self.response_rewrites.get(path.split("?", 1)[0])
        if rewrite is not None:
            payload = rewrite(payload)
        response_headers = [
            {"name": k, "value": v}
            for k, v in response.headers.items()
            if k.lower() not in {"content-length", "set-cookie"}
        ]
        self.send(
            "Fetch.fulfillRequest",
            {
                "requestId": request_id,
                "responseCode": response.status_code,
                "responseHeaders": response_headers,
                "body": base64.b64encode(payload).decode("ascii"),
            },
        )

    # ---------------------------------------------------------------- page
    def evaluate(self, expression: str):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    def wait_for(self, expression: str, timeout: float = 15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = self.evaluate(expression)
            if value:
                return value
            self.pump(0.05)
        raise TimeoutError(expression)

    def goto(self, path: str, ready: str = "document.readyState === 'complete'") -> None:
        self.call("Page.navigate", {"url": BASE_URL + path})
        self.pump(0.2)
        self.wait_for(ready)

    def press_enter(self) -> None:
        self.call(
            "Input.dispatchKeyEvent",
            {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"},
        )
        self.call(
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
        )

    def click(self, selector: str) -> None:
        box = self.evaluate(
            "(() => { const r = document.querySelector(%s).getBoundingClientRect();"
            " return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()" % json.dumps(selector)
        )
        for kind in ("mousePressed", "mouseReleased"):
            self.call(
                "Input.dispatchMouseEvent",
                {"type": kind, "x": box["x"], "y": box["y"], "button": "left", "clickCount": 1},
            )

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass
        try:
            self._proc.kill()
            self._proc.wait(timeout=10)
        except Exception:
            pass
        # Windows keeps the profile locked for a moment after the process dies.
        for _attempt in range(20):
            shutil.rmtree(self._profile, ignore_errors=True)
            if not os.path.exists(self._profile):
                break
            time.sleep(0.1)
