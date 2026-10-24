"""FastAPI application: typed API, SSE, optional static UI, embedded worker."""
from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import bootstrap, worker
from .config import get_settings
from .routers import auth, field, incidents, scenarios, system

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rainready")
# Windows registries often lack these; module workers and nosniff need exact JS/CSS MIME types.
for ext, mt in ((".mjs", "text/javascript"), (".js", "text/javascript"), (".css", "text/css"), (".woff2", "font/woff2")):
    mimetypes.add_type(mt, ext)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    info = bootstrap.startup()
    log.info("startup: %s | data_mode=%s model_provider=%s connectors=%s", info, s.data_mode, s.model_provider, s.action_connectors)
    if s.worker_enabled:
        worker.start()
    yield
    worker.stop()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="0.1.0", lifespan=lifespan,
                  description="Government decision-support prototype for water anomalies, flood risk and human-approved response. "
                              "All data synthetic unless DATA_MODE says otherwise; all action connectors simulated. Not an official system.",
                  openapi_tags=[{"name": "incidents"}, {"name": "scenarios"}, {"name": "twin"}, {"name": "field"}, {"name": "imports"}, {"name": "knowledge"}, {"name": "system"}, {"name": "auth"}])
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Error-Code"])
    for r in (auth.router, system.router, scenarios.router, incidents.router, field.router):
        app.include_router(r)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    static = Path(s.static_dir) if s.static_dir else None
    if static and static.exists():
        app.mount("/_next", StaticFiles(directory=static / "_next"), name="next-static")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            target = static / path
            if path and target.is_file():
                return FileResponse(target)
            html = static / f"{path}.html" if path else static / "index.html"
            if html.is_file():
                return FileResponse(html)
            idx = static / path / "index.html"
            if idx.is_file():
                return FileResponse(idx)
            return FileResponse(static / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def root():
            return JSONResponse({"app": s.app_name, "docs": "/docs", "health": "/api/health", "modes": system.modes()})
    return app


app = create_app()
