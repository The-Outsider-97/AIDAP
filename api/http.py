"""HTTP plumbing: route registry, authentication, CSRF, rate limiting, validation, error mapping, security headers.

Handlers are plain synchronous functions ``fn(c: Ctx)``; they run in a worker thread because services use a blocking
database. Handlers return JSON-able data, a ``Reply`` (status/headers/cookies) or a Starlette ``Response``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..app.context import Principal
from ..app.services import Services
from ..app.services.auth import CSRF_COOKIE, SESSION_COOKIE
from ..contracts.validation import validate
from ..contracts.versions import ERROR_SCHEMA
from ..domain.utils.domain_errors import (AIDAPError, Forbidden, PayloadTooLarge, RateLimited, Unauthenticated,
                                          UnsupportedMedia, ValidationFailed)
from ..domain.utils.domain_helpers import new_id, to_jsonable

__all__ = ["Ctx", "Reply", "api", "ROUTES", "build_routes", "security_headers", "client_ip", "read_input", "set_session_cookies",
           "clear_session_cookies"]

log = logging.getLogger("aidap.api")
PREFIX = "/api/v1"
MAX_JSON_BYTES = 6_500_000
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class Reply:
    data: Any = None
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[dict[str, Any]] = field(default_factory=list)
    delete_cookies: list[str] = field(default_factory=list)


@dataclass
class Ctx:
    svc: Services
    req: Request
    p: Principal | None
    body: dict[str, Any]
    query: dict[str, str]
    params: dict[str, str]
    ip: str
    rid: str
    raw: bytes = b""
    fields: dict[str, str] = field(default_factory=dict)          # multipart text fields
    files: dict[str, tuple[str, str, bytes]] = field(default_factory=dict)   # name -> (filename, content_type, data)
    present: frozenset = frozenset()                               # keys the client actually sent (distinguishes null from absent)

    @property
    def principal(self) -> Principal:
        if self.p is None:                                             # defensive: non-public handlers always have one
            raise Unauthenticated("sign in required")
        return self.p

    def q(self, name: str, default: str = "") -> str:
        return self.query.get(name, default)

    @property
    def ua(self) -> str:
        return self.req.headers.get("user-agent", "")[:200]


@dataclass
class RouteDef:
    path: str
    methods: list[str]
    fn: Callable[[Ctx], Any]
    public: bool = False
    body: dict[str, Any] | None = None
    payload: str = "json"            # json | upload | raw | none
    rate: str = "default"            # default | auth | none


ROUTES: list[RouteDef] = []


def api(method: str, path: str, *, public: bool = False, body: dict[str, Any] | None = None, payload: str = "",
        rate: str = "default", prefix: str = PREFIX) -> Callable[[Callable[[Ctx], Any]], Callable[[Ctx], Any]]:
    def deco(fn: Callable[[Ctx], Any]) -> Callable[[Ctx], Any]:
        kind = payload or ("json" if body is not None else "none")
        ROUTES.append(RouteDef(prefix + path, [m.strip() for m in method.split(",")], fn, public, body, kind, rate))
        return fn
    return deco


# ------------------------------------------------------------------ helpers
def client_ip(req: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        fwd = req.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
    return (req.client.host if req.client else "unknown")[:64]


def security_headers(resp: Response, *, production: bool, api_response: bool) -> Response:
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    h.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                 "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
    if production:
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if api_response:
        h["Cache-Control"] = "no-store"
    return resp


def _error(exc: AIDAPError, rid: str) -> Response:
    headers = {}
    if isinstance(exc, RateLimited):
        headers["Retry-After"] = str(int(exc.details.get("retry_after", 1)) or 1)
    if exc.http_status == 401:
        headers["WWW-Authenticate"] = 'Bearer realm="aidap"'
    return JSONResponse({"schema": ERROR_SCHEMA, "error": exc.to_dict(), "request_id": rid},
                        status_code=exc.http_status, headers=headers)


def _origin_ok(req: Request, base_url: str) -> bool:
    origin = req.headers.get("origin")
    if not origin:
        return True                                  # same-origin navigations / non-browser clients omit it
    o = urlsplit(origin)
    allowed = {urlsplit(base_url).netloc, req.headers.get("host", "")}
    return o.netloc in allowed


def authenticate(svc: Services, req: Request, ip: str) -> Principal:
    authz = req.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        return svc.auth.authenticate_api_key(authz[7:].strip(), ip=ip)
    token = req.cookies.get(SESSION_COOKIE, "")
    unsafe = req.method in _UNSAFE
    if token and unsafe and not _origin_ok(req, svc.deps.settings.base_url):
        raise Forbidden("cross-origin request refused", code="bad_origin")
    return svc.auth.authenticate_session(token, req.headers.get("x-csrf-token"), unsafe_method=unsafe, ip=ip)


def set_session_cookies(resp: Response, svc: Services, session_token: str, csrf_token: str) -> None:
    st = svc.deps.settings
    age = st.session_hours * 3600
    resp.set_cookie(SESSION_COOKIE, session_token, max_age=age, httponly=True, secure=st.cookie_secure, samesite="lax", path="/")
    resp.set_cookie(CSRF_COOKIE, csrf_token, max_age=age, httponly=False, secure=st.cookie_secure, samesite="lax", path="/")


def clear_session_cookies(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE, path="/")
    resp.delete_cookie(CSRF_COOKIE, path="/")


# ------------------------------------------------------------------ dispatch
async def _read_payload(req: Request, rd: RouteDef, max_upload: int) -> tuple[bytes, dict[str, str], dict[str, tuple[str, str, bytes]]]:
    if rd.payload == "none" or req.method not in _UNSAFE:
        return b"", {}, {}
    ctype = req.headers.get("content-type", "").split(";")[0].strip().lower()
    if rd.payload == "upload" and ctype == "multipart/form-data":
        try:
            form = await req.form(max_files=2, max_fields=40, max_part_size=1024 * 1024)
        except Exception as exc:                                       # noqa: BLE001
            if "multipart" in str(exc).lower() and "install" in str(exc).lower():
                raise UnsupportedMedia("multipart uploads need the python-multipart package; send JSON or a raw body instead") from exc
            raise ValidationFailed("the multipart body could not be read") from exc
        fields: dict[str, str] = {}
        files: dict[str, tuple[str, str, bytes]] = {}
        for k, v in form.multi_items():
            if hasattr(v, "read"):
                data = await v.read()
                if len(data) > max_upload:
                    raise PayloadTooLarge("the file exceeds the platform limit")
                files[k] = (v.filename or "", v.content_type or "", data)
            else:
                fields[k] = str(v)
        return b"", fields, files
    limit = max_upload if rd.payload in ("upload", "raw") and ctype not in ("application/json", "") else MAX_JSON_BYTES
    chunks, total = [], 0
    async for chunk in req.stream():
        total += len(chunk)
        if total > limit:
            raise PayloadTooLarge("the request body is too large")
        chunks.append(chunk)
    return b"".join(chunks), {}, {}


def _dispatch(svc: Services, rd: RouteDef, req: Request, raw: bytes, fields: dict[str, str], files: dict, trust_proxy: bool,
              rid: str) -> Response:
    ip = client_ip(req, trust_proxy)
    d = svc.deps
    p: Principal | None = None
    try:
        allowed, retry = d.limiter.check(f"ip:{ip}") if rd.rate != "none" else (True, 0.0)
        if not allowed:
            raise RateLimited("too many requests", details={"retry_after": max(1, int(retry + 0.999))})
        if not rd.public:
            p = authenticate(svc, req, ip)
            if p.kind == "api_key":
                ok, retry = d.limiter.check(f"key:{p.id}")
                if not ok:
                    raise RateLimited("API key rate limit reached", details={"retry_after": max(1, int(retry + 0.999))})
        body: dict[str, Any] = {}
        present: frozenset = frozenset()
        if rd.body is not None:
            ctype = req.headers.get("content-type", "").split(";")[0].strip().lower()
            if rd.payload == "upload" and ctype == "multipart/form-data":
                data: Any = dict(fields)
                for jk in ("metadata", "profile", "policy"):
                    if jk in data:
                        try:
                            data[jk] = json.loads(data[jk]) if data[jk] else None
                        except ValueError as exc:
                            raise ValidationFailed(f"{jk} must be a JSON object", details={"fields": {jk: "invalid JSON"}}) from exc
                for bk in ("wait",):
                    if bk in data:
                        data[bk] = data[bk].lower() in ("1", "true", "yes", "on")
            elif rd.payload == "upload" and ctype in ("application/octet-stream", "text/plain", "text/csv"):
                data = {k: v for k, v in req.query_params.items()}
                if data.get("metadata"):
                    try:
                        data["metadata"] = json.loads(data["metadata"])
                    except ValueError as exc:
                        raise ValidationFailed("metadata must be a JSON object", details={"fields": {"metadata": "invalid JSON"}}) from exc
                else:
                    data.pop("metadata", None)
                if "wait" in data:
                    data["wait"] = data["wait"].lower() in ("1", "true", "yes", "on")
            else:
                if ctype not in ("application/json", "") and raw:
                    raise UnsupportedMedia("send application/json")
                try:
                    data = json.loads(raw.decode("utf-8")) if raw.strip() else {}
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ValidationFailed("the request body is not valid JSON") from exc
            present = frozenset(data) if isinstance(data, dict) else frozenset()
            body = validate(rd.body, data)
        c = Ctx(svc, req, p, body, dict(req.query_params), dict(req.path_params), ip, rid, raw, fields, files, present)
        out = rd.fn(c)
    except AIDAPError as exc:
        return _error(exc, rid)
    except Exception:                                                  # noqa: BLE001 - never leak internals
        log.exception("unhandled error rid=%s %s %s", rid, req.method, req.url.path)
        return JSONResponse({"schema": ERROR_SCHEMA, "error": {"code": "internal_error", "message": "something went wrong on our side"},
                             "request_id": rid}, status_code=500)
    if isinstance(out, Response):
        return out
    reply = out if isinstance(out, Reply) else Reply(out)
    resp = JSONResponse(to_jsonable(reply.data) if reply.data is not None else {"ok": True}, status_code=reply.status,
                        headers=reply.headers)
    for ck in reply.cookies:
        resp.set_cookie(**ck)
    for name in reply.delete_cookies:
        resp.delete_cookie(name, path="/")
    return resp


def read_input(c: Ctx) -> tuple[bytes, str, str]:
    """The submitted artifact, whichever way it arrived: multipart ``file``, raw body, or JSON ``content``."""
    if "file" in c.files:
        name, ctype, data = c.files["file"]
        return data, name or c.body.get("filename") or "upload", ctype
    ctype = c.req.headers.get("content-type", "").split(";")[0].strip().lower()
    if c.raw and ctype != "application/json":
        name = c.req.headers.get("x-filename") or c.body.get("filename") or c.query.get("filename") or "upload"
        return c.raw, name[:200], (c.req.headers.get("x-media-type") or ctype)[:120]
    content = c.body.get("content")
    if content:
        return content.encode("utf-8"), c.body.get("filename") or "input.txt", c.body.get("media_type") or "text/plain"
    raise ValidationFailed("provide a file, a raw body or a JSON 'content' string", details={"fields": {"file": "required"}})


def build_routes(svc: Services, *, trust_proxy: bool = False) -> list[Route]:
    max_upload = svc.deps.settings.max_upload_bytes
    prod = svc.deps.settings.production
    routes: list[Route] = []
    for rd in ROUTES:
        def make(rd: RouteDef) -> Callable[[Request], Any]:
            async def endpoint(req: Request) -> Response:
                rid = req.headers.get("x-request-id", "")[:64] or new_id("req")
                t0 = time.monotonic()
                try:
                    raw, fields, files = await _read_payload(req, rd, max_upload)
                except AIDAPError as exc:
                    resp = _error(exc, rid)
                else:
                    resp = await run_in_threadpool(_dispatch, svc, rd, req, raw, fields, files, trust_proxy, rid)
                resp.headers["X-Request-ID"] = rid
                resp.headers["Server-Timing"] = f"app;dur={int((time.monotonic() - t0) * 1000)}"
                return security_headers(resp, production=prod, api_response=True)
            return endpoint
        routes.append(Route(rd.path, make(rd), methods=rd.methods))
    return routes
