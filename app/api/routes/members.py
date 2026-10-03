"""The signed-in person, their workspaces, and team management within a workspace."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    Identity,
    Principal,
    current_workspace,
    get_identity,
    get_session,
    require_admin,
    require_viewer,
)
from app.config import get_settings
from app.db.models import Member, MemberRole, Workspace
from app.services.quotas import Limits, QuotaExceeded, active_crawls, member_count, source_count, usage_today

router = APIRouter(tags=["workspaces"])

RoleName = Literal["viewer", "editor", "admin"]
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------------------------------------------------------------------ schemas

class WorkspaceOut(BaseModel):
    id: int
    name: str
    role: RoleName
    owned: bool


class Me(BaseModel):
    email: str | None
    via: str
    workspaces: list[WorkspaceOut]


class WorkspaceName(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 1 <= len(v) <= 100:
            raise ValueError("use 1 to 100 characters")
        return v


class WorkspaceDelete(BaseModel):
    confirm_name: str


class Usage(BaseModel):
    workspace: WorkspaceOut
    limits: dict
    today: dict
    counts: dict


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


def _member_out(m: Member) -> MemberOut:
    return MemberOut(
        id=m.id, email=m.email, role=m.role, joined=m.user_id is not None,
        invited_by=m.invited_by, last_seen_at=m.last_seen_at, created_at=m.created_at,
    )


# ------------------------------------------------------------------ me & workspaces

async def _my_workspaces(session: AsyncSession, identity: Identity) -> list[WorkspaceOut]:
    if identity.via != "user":
        rows = (await session.execute(select(Workspace).order_by(Workspace.id))).scalars()
        return [WorkspaceOut(id=w.id, name=w.name, role="admin", owned=False) for w in rows]
    rows = (
        await session.execute(
            select(Workspace, Member.role)
            .join(Member, Member.workspace_id == Workspace.id)
            .where(Member.user_id == identity.user_id)
            .order_by(Workspace.id)
        )
    ).all()
    return [WorkspaceOut(id=w.id, name=w.name, role=role, owned=w.created_by_user_id == identity.user_id) for w, role in rows]


@router.get("/me", response_model=Me)
async def me(session: AsyncSession = Depends(get_session), identity: Identity = Depends(get_identity)) -> Me:
    return Me(email=identity.email, via=identity.via, workspaces=await _my_workspaces(session, identity))


@router.post("/workspaces", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceName, session: AsyncSession = Depends(get_session), identity: Identity = Depends(get_identity)
) -> WorkspaceOut:
    settings = get_settings()
    if identity.via == "user":
        owned = (
            await session.execute(select(func.count(Workspace.id)).where(Workspace.created_by_user_id == identity.user_id))
        ).scalar_one()
        if owned >= settings.max_owned_workspaces:
            raise QuotaExceeded(f"You can create up to {settings.max_owned_workspaces} workspaces. Delete one to make another.")
    ws = Workspace(name=payload.name, created_by_email=identity.email, created_by_user_id=identity.user_id)
    session.add(ws)
    await session.flush()
    if identity.via == "user":
        session.add(Member(workspace_id=ws.id, email=identity.email or "", user_id=identity.user_id, role=MemberRole.admin.value))
    await session.commit()
    return WorkspaceOut(id=ws.id, name=ws.name, role="admin", owned=identity.via == "user")


@router.get("/workspace", response_model=Usage)
async def workspace_usage(session: AsyncSession = Depends(get_session), principal: Principal = Depends(require_viewer)) -> Usage:
    ws = await current_workspace(session, principal)
    used = await usage_today(session, ws.id)
    return Usage(
        workspace=WorkspaceOut(id=ws.id, name=ws.name, role=principal.role.name,
                               owned=principal.user_id is not None and ws.created_by_user_id == principal.user_id),
        limits=Limits.for_workspace(ws).as_dict(),
        today={"pages": used.pages, "llm_calls": used.llm_calls, "crawls": used.crawls},
        counts={
            "sources": await source_count(session, ws.id),
            "members": await member_count(session, ws.id),
            "active_crawls": await active_crawls(session, ws.id),
        },
    )


@router.patch("/workspace", response_model=WorkspaceOut)
async def rename_workspace(
    payload: WorkspaceName, session: AsyncSession = Depends(get_session), principal: Principal = Depends(require_admin)
) -> WorkspaceOut:
    ws = await current_workspace(session, principal)
    ws.name = payload.name
    await session.commit()
    return WorkspaceOut(id=ws.id, name=ws.name, role="admin",
                        owned=principal.user_id is not None and ws.created_by_user_id == principal.user_id)


@router.delete("/workspace", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    payload: WorkspaceDelete, session: AsyncSession = Depends(get_session), principal: Principal = Depends(require_admin)
) -> Response:
    ws = await current_workspace(session, principal)
    if payload.confirm_name.strip() != ws.name:
        raise HTTPException(422, "Type the workspace name exactly to confirm.")
    if await active_crawls(session, ws.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cancel or wait for running crawls before deleting the workspace.")
    await session.delete(ws)  # sources, crawls, pages, articles, members and usage go with it (ON DELETE CASCADE)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ team (current workspace)

async def _admin_count(session: AsyncSession, workspace_id: int) -> int:
    stmt = select(func.count(Member.id)).where(Member.workspace_id == workspace_id, Member.role == MemberRole.admin.value)
    return (await session.execute(stmt)).scalar_one()


async def _get(session: AsyncSession, member_id: int, workspace_id: int) -> Member:
    member = await session.get(Member, member_id)
    if member is None or member.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member not found")
    return member


@router.get("/members", response_model=list[MemberOut])
async def list_members(session: AsyncSession = Depends(get_session), principal: Principal = Depends(require_admin)) -> list[MemberOut]:
    rows = (
        await session.execute(
            select(Member).where(Member.workspace_id == principal.workspace_id).order_by(Member.role.desc(), Member.email)
        )
    ).scalars()
    return [_member_out(m) for m in rows]


@router.post("/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def invite_member(
    payload: MemberCreate,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_admin),
) -> MemberOut:
    ws = await current_workspace(session, principal)
    limits = Limits.for_workspace(ws)
    if await member_count(session, ws.id) >= limits.max_members:
        raise QuotaExceeded(f"This workspace can have up to {limits.max_members} members.")
    member = Member(workspace_id=ws.id, email=payload.email, role=payload.role, invited_by=principal.label)
    session.add(member)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That email is already in this workspace.") from exc
    await session.refresh(member)
    return _member_out(member)


@router.patch("/members/{member_id}", response_model=MemberOut)
async def change_role(
    member_id: int, payload: MemberUpdate, session: AsyncSession = Depends(get_session), principal: Principal = Depends(require_admin)
) -> MemberOut:
    member = await _get(session, member_id, principal.workspace_id)
    if member.role == MemberRole.admin.value and payload.role != "admin" and await _admin_count(session, principal.workspace_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A workspace needs at least one admin. Make someone else an admin first.")
    member.role = payload.role
    await session.commit()
    await session.refresh(member)
    return _member_out(member)


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    member_id: int, session: AsyncSession = Depends(get_session), principal: Principal = Depends(require_admin)
) -> Response:
    member = await _get(session, member_id, principal.workspace_id)
    if member.role == MemberRole.admin.value and await _admin_count(session, principal.workspace_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A workspace needs at least one admin. Make someone else an admin first.")
    await session.delete(member)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
