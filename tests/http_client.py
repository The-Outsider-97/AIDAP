"""A tiny real-HTTP test client: uvicorn in a thread + urllib with a cookie jar (no httpx in this environment)."""

from __future__ import annotations

import http.cookiejar
import json
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

import uvicorn


class Server:
    def __init__(self, app: Any) -> None:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning", lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("server did not start")
        self.base = f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)


class Resp:
    def __init__(self, status: int, headers: Any, body: bytes) -> None:
        self.status, self.headers, self.body = status, headers, body

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


class Client:
    def __init__(self, base: str, bearer: str = "") -> None:
        self.base, self.bearer = base, bearer
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect())

    def cookie(self, name: str) -> str:
        return next((c.value for c in self.jar if c.name == name), "")

    def request(self, method: str, path: str, *, json_body: Any = None, data: bytes | None = None, headers: dict[str, str] | None = None,
                csrf: bool = True, content_type: str = "") -> Resp:
        h = dict(headers or {})
        body = data
        if json_body is not None:
            body = json.dumps(json_body).encode()
            h["Content-Type"] = "application/json"
        if content_type:
            h["Content-Type"] = content_type
        if self.bearer:
            h["Authorization"] = "Bearer " + self.bearer
        elif csrf and method != "GET" and self.cookie("aidap_csrf"):
            h["X-CSRF-Token"] = self.cookie("aidap_csrf")
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=h)
        try:
            with self.opener.open(req, timeout=60) as r:
                return Resp(r.status, r.headers, r.read())
        except urllib.error.HTTPError as e:
            return Resp(e.code, e.headers, e.read())

    def get(self, path: str, **kw: Any) -> Resp:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> Resp:
        return self.request("POST", path, json_body=body if body is not None else {}, **kw)

    def upload(self, path: str, fields: dict[str, str], filename: str, content: bytes, ctype: str = "application/json") -> Resp:
        b = "----aidap" + uuid.uuid4().hex
        parts = []
        for k, v in fields.items():
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
                     + content + b"\r\n")
        parts.append(f"--{b}--\r\n".encode())
        return self.request("POST", path, data=b"".join(parts), content_type=f"multipart/form-data; boundary={b}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **k: Any) -> None:  # type: ignore[override]
        return None
