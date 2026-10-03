from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.db.models import Source
from app.schemas import SourceCreate, SourceOut, SourcePage, SourceUpdate, domain_for

router = APIRouter(prefix="/sources", tags=["sources"])


async def get_source_or_404(session: AsyncSession, source_id: int) -> Source:
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    return source


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(payload: SourceCreate, session: AsyncSession = Depends(get_session)) -> Source:
    data = payload.model_dump()
    domain = domain_for(data["base_url"])
    data["domain"] = domain
    data["allowed_domains"] = data.get("allowed_domains") or [domain]
    source = Source(**data)
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
) -> dict:
    stmt = select(Source)
    if enabled is not None:
        stmt = stmt.where(Source.enabled.is_(enabled))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    items = (await session.execute(stmt.order_by(Source.id).limit(limit).offset(offset))).scalars().all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(source_id: int, session: AsyncSession = Depends(get_session)) -> Source:
    return await get_source_or_404(session, source_id)


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(source_id: int, payload: SourceUpdate, session: AsyncSession = Depends(get_session)) -> Source:
    source = await get_source_or_404(session, source_id)
    changes = payload.model_dump(exclude_unset=True)
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
async def delete_source(source_id: int, session: AsyncSession = Depends(get_session)) -> Response:
    source = await get_source_or_404(session, source_id)
    await session.delete(source)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
