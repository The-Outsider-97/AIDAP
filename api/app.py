from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from ..app.services import Services
from ..contracts.versions import ERROR_SCHEMA
from ..workers import WorkerLoop
from . import routes_core, routes_insights, routes_runs, routes_workspace  # noqa: F401  (importing registers the routes)
from .http import build_routes, security_headers

__all__ = ["create_app", "FRONTEND_DIST"]

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

_PLACEHOLDER = """<!doctype html><meta charset=utf-8><title>AIDAP</title><body style="font:16px system-ui;max-width:42rem;margin:4rem auto;padding:0 1rem">
<h1>AIDAP API is running</h1><p>The web interface has not been built yet. From <code>frontend/</code> run <code>npm install &amp;&amp; npm run build</code>,
then reload. The API is available under <code>/api/v1</code> (see <a href="/api/v1/meta">/api/v1/meta</a>).</p></body>"""


def create_app(svc: Services, *, serve_frontend: bool = True, trust_proxy: bool = False, dist: Path | None = None) -> Starlette:
    prod = svc.deps.settings.production
    dist = Path(dist) if dist else FRONTEND_DIST
    worker = WorkerLoop(svc, threads=2) if svc.deps.settings.inline_workers else None

    @asynccontextmanager
    async def lifespan(_: Starlette):
        if worker:
            worker.start()
        try:
            yield
        finally:
            if worker:
                worker.stop()

    async def api_not_found(req: Request) -> Response:
        return security_headers(JSONResponse({"schema": ERROR_SCHEMA, "error": {"code": "not_found", "message": "no such endpoint"}},
                                             status_code=404), production=prod, api_response=True)

    async def spa(req: Request) -> Response:
        rel = req.path_params.get("path", "")
        if rel:
            target = (dist / rel).resolve()
            if dist.resolve() in target.parents and target.is_file():
                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                resp: Response = FileResponse(target, media_type=ctype)
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if rel.startswith("assets/") else "no-cache"
                return security_headers(resp, production=prod, api_response=False)
            if "." in rel.rsplit("/", 1)[-1]:                         # a missing file, not a client-side route
                return security_headers(Response("Not found", status_code=404), production=prod, api_response=False)
        index = dist / "index.html"
        resp = FileResponse(index, media_type="text/html") if index.is_file() else HTMLResponse(_PLACEHOLDER)
        resp.headers["Cache-Control"] = "no-cache"
        return security_headers(resp, production=prod, api_response=False)

    routes: list[Route] = build_routes(svc, trust_proxy=trust_proxy)
    routes.append(Route("/api/{rest:path}", api_not_found, methods=["GET", "POST", "PUT", "PATCH", "DELETE"]))
    if serve_frontend:
        routes.append(Route("/{path:path}", spa, methods=["GET", "HEAD"]))
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.services = svc
    app.state.worker = worker
    return app
