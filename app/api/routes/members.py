"""The current user and team management (admins only)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.auth import Principal, require_admin, require_viewer
from app.db.models import Member, MemberRole

router = APIRouter(tags=["team"])

RoleName = Literal["viewer", "editor", "admin"]
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: RoleName
    joined: bool
    invited_by: str | None
    last_seen_at: datetime | None
    created_at: datetime


class MemberCreate(BaseModel):
    email: str
    role: RoleName = "viewer"

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if len(v) > 320 or not _EMAIL.match(v):
            raise ValueError("enter a valid email address")
        return v


class MemberUpdate(BaseModel):
    role: RoleName


class Me(BaseModel):
    email: str | None
    role: RoleName
    via: str


def _out(m: Member) -> MemberOut:
    return MemberOut(
        id=m.id, email=m.email, role=m.role, joined=m.user_id is not None,
        invited_by=m.invited_by, last_seen_at=m.last_seen_at, created_at=m.created_at,
    )


@router.get("/me", response_model=Me)
async def me(principal: Principal = Depends(require_viewer)) -> Me:
    return Me(email=principal.email, role=principal.role.name, via=principal.via)


async def _admin_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count(Member.id)).where(Member.role == MemberRole.admin.value))).scalar_one()


async def _get(session: AsyncSession, member_id: int) -> Member:
    member = await session.get(Member, member_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member not found")
    return member


@router.get("/members", response_model=list[MemberOut], dependencies=[Depends(require_admin)])
async def list_members(session: AsyncSession = Depends(get_session)) -> list[MemberOut]:
    rows = (await session.execute(select(Member).order_by(Member.role.desc(), Member.email))).scalars()
    return [_out(m) for m in rows]


@router.post("/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def invite_member(
    payload: MemberCreate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_admin),
) -> MemberOut:
    member = Member(email=payload.email, role=payload.role, invited_by=principal.label)
    session.add(member)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already on the team.") from exc
    await session.refresh(member)
    return _out(member)


@router.patch("/members/{member_id}", response_model=MemberOut, dependencies=[Depends(require_admin)])
async def change_role(member_id: int, payload: MemberUpdate, session: AsyncSession = Depends(get_session)) -> MemberOut:
    member = await _get(session, member_id)
    if member.role == MemberRole.admin.value and payload.role != "admin" and await _admin_count(session) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Newsforge needs at least one admin. Make someone else an admin first.")
    member.role = payload.role
    await session.commit()
    await session.refresh(member)
    return _out(member)


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def remove_member(member_id: int, session: AsyncSession = Depends(get_session)) -> Response:
    member = await _get(session, member_id)
    if member.role == MemberRole.admin.value and await _admin_count(session) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Newsforge needs at least one admin. Make someone else an admin first.")
    await session.delete(member)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
