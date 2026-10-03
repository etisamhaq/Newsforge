"""Authentication and authorization.

Two ways in:
- `X-API-Key: <API_KEY>`: a machine credential for scripts and automation; acts as an admin of
  whichever workspace the request names.
- `Authorization: Bearer <Supabase access token>`: a person. Supabase proves *who* they are
  (we verify the token's signature against the project's published JWKS, so no Supabase secret
  is needed); `members` rows decide *which workspaces* they belong to and *what they may do* there.

Every data request is scoped to one workspace, chosen with the `X-Workspace-Id` header (default:
the person's first workspace). On first sign-in a person is linked to any workspaces that invited
their email; with no invitations, they get a new workspace of their own as its admin.

Roles are ordered: viewer < editor < admin.
"""

from __future__ import annotations

import asyncio
import hmac
import time
from dataclasses import dataclass
from datetime import timedelta
from enum import IntEnum

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.base import utcnow
from app.db.models import Member, MemberRole, Workspace
from app.db.session import get_session
from app.logging import get_logger

log = get_logger(__name__)


class Role(IntEnum):
    viewer = 1
    editor = 2
    admin = 3

    @classmethod
    def parse(cls, value: str) -> Role:
        return cls[value]


@dataclass(frozen=True)
class Identity:
    """Who is calling, before any workspace is chosen."""

    via: str  # "user" | "api_key" | "open"
    email: str | None = None
    user_id: str | None = None

    @property
    def label(self) -> str:
        return self.email or ("API key" if self.via == "api_key" else "anonymous")


@dataclass(frozen=True)
class Principal:
    """Who is calling, and what they may do in the workspace this request is about."""

    role: Role
    via: str  # "user" | "api_key" | "open"
    workspace_id: int
    email: str | None = None
    user_id: str | None = None
    member_id: int | None = None

    @property
    def label(self) -> str:
        return self.email or ("API key" if self.via == "api_key" else "anonymous")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


class TokenVerifier:
    """Verifies Supabase access tokens with the project's JWKS (cached, refreshed on unknown key ids)."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        base = (settings.supabase_url or "").rstrip("/")
        self.issuer = f"{base}/auth/v1"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self.audience = settings.supabase_jwt_audience
        self.ttl = settings.jwks_cache_seconds
        self._transport = transport
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self, force: bool = False) -> None:
        async with self._lock:
            if not force and self._keys and time.monotonic() - self._fetched_at < self.ttl:
                return
            if force and time.monotonic() - self._fetched_at < 30:
                return  # don't hammer the JWKS endpoint with unknown-kid tokens
            async with httpx.AsyncClient(transport=self._transport, timeout=10) as client:
                resp = await client.get(self.jwks_url)
                resp.raise_for_status()
            keys = {}
            for data in resp.json().get("keys", []):
                try:
                    key = jwt.PyJWK(data)
                except jwt.PyJWKError:
                    continue
                if key.key_id:
                    keys[key.key_id] = key
            self._keys = keys
            self._fetched_at = time.monotonic()

    async def verify(self, token: str) -> dict:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise _unauthorized("malformed access token") from exc
        kid = header.get("kid")
        alg = header.get("alg")
        if alg not in ("ES256", "RS256", "EdDSA") or not kid:
            raise _unauthorized("unsupported access token")
        try:
            await self._refresh()
            if kid not in self._keys:
                await self._refresh(force=True)
        except httpx.HTTPError as exc:
            log.error("auth.jwks_unavailable", error=str(exc)[:200])
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "sign-in service unavailable") from exc
        key = self._keys.get(kid)
        if key is None:
            raise _unauthorized("unknown signing key")
        try:
            return jwt.decode(
                token,
                key.key,
                algorithms=[alg],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
                leeway=30,
            )
        except jwt.ExpiredSignatureError as exc:
            raise _unauthorized("session expired") from exc
        except jwt.PyJWTError as exc:
            raise _unauthorized("invalid access token") from exc


_verifier: TokenVerifier | None = None


def get_verifier() -> TokenVerifier:
    global _verifier
    if _verifier is None:
        _verifier = TokenVerifier(get_settings())
    return _verifier


def set_verifier(verifier: TokenVerifier | None) -> None:
    """Override the verifier (tests)."""
    global _verifier
    _verifier = verifier


def personal_workspace_name(email: str) -> str:
    local = (email.split("@", 1)[0] or "My").replace(".", " ").replace("_", " ").strip()
    return f"{local[:60]}'s workspace"


async def onboard(session: AsyncSession, user_id: str, email: str, settings: Settings) -> None:
    """Link pending invitations, honour ADMIN_EMAILS, and give brand-new people their own workspace."""
    changed = False
    if email:
        pending = (
            await session.execute(select(Member).where(func.lower(Member.email) == email, Member.user_id.is_(None)))
        ).scalars().all()
        for member in pending:
            # Never let a second account with the same email take over an already-linked seat.
            taken = (
                await session.execute(
                    select(Member.id).where(Member.workspace_id == member.workspace_id, Member.user_id == user_id)
                )
            ).first()
            if taken is None:
                member.user_id = user_id
                changed = True

        if email in {e.strip().lower() for e in settings.admin_emails if e.strip()}:
            original = (await session.execute(select(Workspace).order_by(Workspace.id).limit(1))).scalar_one_or_none()
            if original is not None:
                exists = (
                    await session.execute(
                        select(Member.id).where(Member.workspace_id == original.id, Member.user_id == user_id)
                    )
                ).first()
                if exists is None:
                    session.add(Member(workspace_id=original.id, email=email, user_id=user_id,
                                       role=MemberRole.admin.value, invited_by="ADMIN_EMAILS"))
                    changed = True
        if changed:
            await session.flush()

    has_any = (await session.execute(select(Member.id).where(Member.user_id == user_id).limit(1))).first()
    if has_any is None:
        ws = Workspace(name=personal_workspace_name(email), created_by_email=email or None, created_by_user_id=user_id)
        session.add(ws)
        await session.flush()
        session.add(Member(workspace_id=ws.id, email=email, user_id=user_id, role=MemberRole.admin.value, invited_by=None))
        changed = True
        log.info("workspace.created_on_signup", workspace_id=ws.id)
    if changed:
        await session.commit()


async def get_identity(
    session: AsyncSession = Depends(get_session),
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> Identity:
    settings = get_settings()
    if not settings.auth_enabled:
        return Identity("open")  # local development without credentials

    if x_api_key is not None:
        if settings.api_key and hmac.compare_digest(x_api_key, settings.api_key):
            return Identity("api_key")
        raise _unauthorized("invalid API key")

    if authorization and authorization.lower().startswith("bearer ") and settings.supabase_url:
        claims = await get_verifier().verify(authorization[7:].strip())
        if claims.get("role") != "authenticated":
            raise _unauthorized("not a signed-in user")
        email = str(claims.get("email") or "").strip().lower()
        user_id = str(claims["sub"])
        await onboard(session, user_id, email, settings)
        return Identity("user", email=email or None, user_id=user_id)

    raise _unauthorized("sign in required")


async def _default_workspace(session: AsyncSession) -> Workspace:
    """For API-key and open access: the original workspace (created if the database is empty)."""
    ws = (await session.execute(select(Workspace).order_by(Workspace.id).limit(1))).scalar_one_or_none()
    if ws is None:
        ws = Workspace(name="Newsforge")
        session.add(ws)
        await session.commit()
    return ws


async def get_principal(
    session: AsyncSession = Depends(get_session),
    identity: Identity = Depends(get_identity),
    x_workspace_id: str | None = Header(default=None),
) -> Principal:
    wanted: int | None = None
    if x_workspace_id:
        try:
            wanted = int(x_workspace_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Workspace-Id must be a number") from exc

    if identity.via in ("api_key", "open"):
        ws = await session.get(Workspace, wanted) if wanted is not None else await _default_workspace(session)
        if ws is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
        return Principal(Role.admin, identity.via, workspace_id=ws.id)

    stmt = select(Member).where(Member.user_id == identity.user_id).order_by(Member.workspace_id)
    if wanted is not None:
        stmt = stmt.where(Member.workspace_id == wanted)
    member = (await session.execute(stmt.limit(1))).scalar_one_or_none()
    if member is None:
        if wanted is not None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You're not a member of that workspace.")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You're not in any workspace. Create one to get started.")

    now = utcnow()
    last = member.last_seen_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=now.tzinfo)
    if last is None or now - last > timedelta(minutes=5):
        member.last_seen_at = now
        await session.commit()
    return Principal(Role.parse(member.role), "user", workspace_id=member.workspace_id,
                     email=member.email, user_id=member.user_id, member_id=member.id)


def require_role(minimum: Role):
    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role < minimum:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"This needs the {minimum.name} role.")
        return principal

    return dependency


require_viewer = require_role(Role.viewer)
require_editor = require_role(Role.editor)
require_admin = require_role(Role.admin)


async def current_workspace(session: AsyncSession, principal: Principal) -> Workspace:
    ws = await session.get(Workspace, principal.workspace_id)
    if ws is None:  # deleted mid-request
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
    return ws
