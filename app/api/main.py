from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.deps import require_api_key
from app.api.routes import articles, crawls, debug, health, sources, stats
from app.config import get_settings
from app.db.session import dispose_engine
from app.logging import configure_logging, get_logger
from app.metrics import API_LATENCY, API_REQUESTS

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    log.info("api.startup", version=__version__, env=settings.environment)
    if settings.environment == "production" and (not settings.api_key or settings.api_key == "change-me"):
        log.warning("api.insecure_api_key", hint="set API_KEY to a strong secret")
    yield
    await dispose_engine()
    log.info("api.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title="Newsforge", version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            elapsed = time.perf_counter() - start
            API_REQUESTS.labels(request.method, route_path, str(status)).inc()
            API_LATENCY.labels(request.method, route_path).observe(elapsed)
            if route_path not in ("/health", "/metrics"):
                log.info(
                    "http.request",
                    method=request.method,
                    path=request.url.path,
                    status=status,
                    duration_ms=round(elapsed * 1000, 1),
                )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("http.unhandled_error", path=request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    app.include_router(health.router)
    protected = [Depends(require_api_key)]
    app.include_router(sources.router, prefix="/api/v1", dependencies=protected)
    app.include_router(crawls.router, prefix="/api/v1", dependencies=protected)
    app.include_router(articles.router, prefix="/api/v1", dependencies=protected)
    app.include_router(debug.router, prefix="/api/v1", dependencies=protected)
    app.include_router(stats.router, prefix="/api/v1", dependencies=protected)

    # Only needed when the web UI is served from a different origin than the API.
    origins = get_settings().cors_origins
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["X-API-Key", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
            max_age=600,
        )
    return app


app = create_app()
