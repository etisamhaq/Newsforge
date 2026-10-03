from __future__ import annotations

import asyncio

from fastapi import APIRouter, Response
from sqlalchemy import text

from app import __version__
from app.config import get_settings
from app.db.session import get_sessionmaker
from app.metrics import render_metrics

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok", "version": __version__}


async def _check_db() -> str:
    async with get_sessionmaker()() as session:
        await session.execute(text("SELECT 1"))
    return "ok"


async def _check_redis() -> str:
    import redis.asyncio as aioredis

    client = aioredis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        await client.ping()
        return "ok"
    finally:
        await client.aclose()


@router.get("/health/ready")
async def ready(response: Response) -> dict:
    """Readiness probe: dependencies are reachable."""
    checks: dict[str, str] = {}
    for name, fn in (("database", _check_db), ("redis", _check_redis)):
        try:
            checks[name] = await asyncio.wait_for(fn(), timeout=3)
        except Exception as exc:  # noqa: BLE001 - report any failure
            checks[name] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "degraded", "checks": checks}


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)
