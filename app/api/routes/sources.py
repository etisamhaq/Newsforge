from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    Principal,
    current_workspace,
    get_session,
    require_admin,
    require_editor,
    require_viewer,
)
from app.db.models import Source
from app.schemas import SourceCreate, SourceOut, SourcePage, SourceUpdate, domain_for
from app.services.quotas import Limits, QuotaExceeded, source_count

router = APIRouter(prefix="/sources", tags=["sources"])


async def get_source_or_404(session: AsyncSession, source_id: int, workspace_id: int) -> Source:
    source = await session.get(Source, source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    return source


def _field_error(field: str, message: str) -> HTTPException:
    # Same shape as FastAPI validation errors, so the UI shows it next to the field.
    return HTTPException(422, [{"loc": ["body", field], "msg": message, "type": "limit"}])


def _check_limits(limits: Limits, data: dict) -> None:
    if "max_pages" in data and data["max_pages"] > limits.max_pages_per_crawl:
        raise _field_error("max_pages", f"This workspace allows at most {limits.max_pages_per_crawl} pages per crawl.")
    interval = data.get("crawl_interval_minutes")
    if interval is not None and interval < limits.min_crawl_interval_minutes:
        raise _field_error(
            "crawl_interval_minutes", f"This workspace can crawl at most every {limits.min_crawl_interval_minutes} minutes."
        )


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_editor),
) -> Source:
    ws = await current_workspace(session, principal)
    limits = Limits.for_workspace(ws)
    if await source_count(session, ws.id) >= limits.max_sources:
        raise QuotaExceeded(f"This workspace can have up to {limits.max_sources} sources. Delete one to add another.")
    data = payload.model_dump()
    _check_limits(limits, data)
    domain = domain_for(data["base_url"])
    data["domain"] = domain
    data["allowed_domains"] = data.get("allowed_domains") or [domain]
    source = Source(workspace_id=ws.id, **data)
    session.add(source)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "a source with this name already exists") from exc
    await session.refresh(source)
    return source


@router.get("", response_model=SourcePage)
async def list_sources(
    enabled: bool | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_viewer),
) -> dict:
    stmt = select(Source).where(Source.workspace_id == principal.workspace_id)
    if enabled is not None:
        stmt = stmt.where(Source.enabled.is_(enabled))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    items = (await session.execute(stmt.order_by(Source.id).limit(limit).offset(offset))).scalars().all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: int, session: AsyncSession = Depends(get_session), principal: Principal = Depends(require_viewer)
) -> Source:
    return await get_source_or_404(session, source_id, principal.workspace_id)


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: int,
    payload: SourceUpdate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_editor),
) -> Source:
    source = await get_source_or_404(session, source_id, principal.workspace_id)
    changes = payload.model_dump(exclude_unset=True)
    _check_limits(Limits.for_workspace(await current_workspace(session, principal)), changes)
    for key, value in changes.items():
        setattr(source, key, value)
    if "base_url" in changes:
        source.domain = domain_for(source.base_url)
        if "allowed_domains" not in changes:
            source.allowed_domains = [source.domain]
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "a source with this name already exists") from exc
    await session.refresh(source)
    return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: int, session: AsyncSession = Depends(get_session), principal: Principal = Depends(require_admin)
) -> Response:
    source = await get_source_or_404(session, source_id, principal.workspace_id)
    await session.delete(source)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
