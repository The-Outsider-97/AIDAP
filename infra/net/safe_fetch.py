"""SSRF-safe HTTP(S) GET for scheduled sources.

Validation reuses SLAI's webhook destination guard; the connection is then *pinned* to the validated address so a
DNS rebind between check and connect cannot redirect the request. Redirects are followed manually (max 3) and every
hop is re-validated. Response size is capped while streaming.
"""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from ...app.ports import FetchResult
from ...domain.utils.domain_errors import PayloadTooLarge, ValidationFailed
from ...slai.runtime import functions

__all__ = ["PinnedSafeFetcher"]


class PinnedSafeFetcher:
    def __init__(self, *, allow_http: bool = False, allow_private_hosts: bool = False, timeout: float = 15.0,
                 user_agent: str = "AIDAP-Fetcher/1.0") -> None:
        self.wh = functions("webhook")
        self.allow_http, self.allow_private, self.timeout, self.ua = allow_http, allow_private_hosts, timeout, user_agent

    def _validate(self, url: str):
        try:
            parts = self.wh._validate_endpoint_syntax(url, allow_http=self.allow_http)
            self.wh._assert_safe_destination(parts, allow_private_hosts=self.allow_private)
        except self.wh.WebhookError as exc:
            raise ValidationFailed(f"source URL rejected: {exc}", code="url_rejected") from exc
        return parts

    def _resolve(self, host: str, port: int) -> str:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        for info in infos:
            ip = info[4][0]
            if self.allow_private or ipaddress.ip_address(ip).is_global:
                return ip
        raise ValidationFailed("source host resolves only to non-public addresses", code="url_rejected")

    def fetch(self, url: str, *, max_bytes: int) -> FetchResult:
        current = url
        for _hop in range(4):
            parts = self._validate(current)
            host, secure = parts.hostname or "", parts.scheme == "https"
            port = parts.port or (443 if secure else 80)
            ip = self._resolve(host, port)
            conn = _conn(host, ip, port, secure, self.timeout)
            try:
                path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                conn.request("GET", path, headers={"Host": parts.netloc, "User-Agent": self.ua, "Accept": "*/*",
                                                   "Accept-Encoding": "identity"})
                resp = conn.getresponse()
                if resp.status in (301, 302, 303, 307, 308) and resp.getheader("Location"):
                    current = urljoin(current, resp.getheader("Location") or "")
                    continue
                if resp.status != 200:
                    raise ValidationFailed(f"source returned HTTP {resp.status}", code="fetch_failed")
                declared = resp.getheader("Content-Length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise PayloadTooLarge("source is larger than the plan allows")
                buf = bytearray()
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    buf += chunk
                    if len(buf) > max_bytes:
                        raise PayloadTooLarge("source is larger than the plan allows")
                cd = resp.getheader("Content-Disposition") or ""
                m = re.search(r'filename="?([^";]+)"?', cd)
                name = m.group(1) if m else (parts.path.rsplit("/", 1)[-1] or "source")
                return FetchResult(bytes(buf), (resp.getheader("Content-Type") or "").split(";")[0].strip(), name[:200],
                                   current, resp.getheader("ETag") or "")
            except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
                raise ValidationFailed(f"source could not be fetched: {type(exc).__name__}", code="fetch_failed") from exc
            finally:
                conn.close()
        raise ValidationFailed("too many redirects", code="fetch_failed")


def _conn(host: str, ip: str, port: int, secure: bool, timeout: float):
    if secure:
        ctx = ssl.create_default_context()

        class _S(http.client.HTTPSConnection):
            def connect(self) -> None:                                         # noqa: D401
                sock = socket.create_connection((ip, port), self.timeout)
                self.sock = ctx.wrap_socket(sock, server_hostname=host)

        return _S(host, port, timeout=timeout, context=ctx)

    class _P(http.client.HTTPConnection):
        def connect(self) -> None:
            self.sock = socket.create_connection((ip, port), self.timeout)

    return _P(host, port, timeout=timeout)
